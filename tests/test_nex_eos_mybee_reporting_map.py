from __future__ import annotations

import json
import os
import uuid
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from nex_eos import (
    EOS_COA_DEFINITION_RELEASE_TABLE,
    EOS_COA_REPORTING_RELEASE_TABLE,
    EOS_METADATA,
    CoaDefinitionReleaseInput,
    CoaEntryInput,
    EosReportingMapError,
    EosReportingMapService,
    ReportingMapReleaseInput,
    ReportingMapRuleInput,
    SqlAlchemyEosReportingMapRepository,
    SqlAlchemyEosUnifiedCoaRepository,
    build_eos_database_runtime,
    create_eos_app,
)
from nex_eos.authorization import AuthorizationSubjectDenied
from nex_runtime import issue_mock_service_token, psycopg_database_url
from psycopg import sql
from run_migrations import run_service_migrations
from sqlalchemy import create_engine, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
POSTGRES_SMOKE = os.getenv("NEX_EOS_MYBEE_COA_06_POSTGRES_SMOKE") == "1"

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_DIR = ROOT / "domains/mybee/config/account_catalog"
TENANT_ID = "tenant-a"
SUBJECT_ID = "finance-report-reader"
COA_RELEASE_ID = "e0000000-0000-4000-8000-000000000001"
ENTRY_ID = "e1000000-0000-4000-8000-000000000001"
MAP_RELEASE_ID = "e2000000-0000-4000-8000-000000000001"
RULE_ID = "e3000000-0000-4000-8000-000000000001"
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64
START = date(2026, 1, 1)


class AuthorizationSource:
    def __init__(self) -> None:
        self.scopes = {"finance:report:read"}
        self.active = True
        self.denied = False
        self.unavailable = False
        self.revision_hash = "d" * 64

    def effective_authorization(self, *, tenant_id: str, subject_id: str):
        if self.unavailable:
            raise RuntimeError("private OA failure")
        if self.denied:
            raise AuthorizationSubjectDenied("inactive")
        return {
            "active": self.active,
            "tenant_id": tenant_id,
            "subject_id": subject_id,
            "scopes": sorted(self.scopes),
            "revision_hash": self.revision_hash,
        }


@pytest.fixture
def runtime():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    _seed_coa(factory)
    auth = AuthorizationSource()
    repository = SqlAlchemyEosReportingMapRepository(factory)
    service = EosReportingMapService(repository, auth)
    yield engine, factory, auth, repository, service
    engine.dispose()


def _seed_coa(factory) -> None:
    repository = SqlAlchemyEosUnifiedCoaRepository(factory)
    repository.create_draft_release(
        release=CoaDefinitionReleaseInput(
            definition_release_id=COA_RELEASE_ID,
            scope_type="GLOBAL",
            chart_profile="MYBEE-KIFRS",
            release_version="2026.01",
            effective_from=START,
            source_reference="approved-standard-chart.v1.json",
            source_hash=HASH_A,
            approved_proof_ref=HASH_B,
            content_hash=HASH_C,
            created_by=SUBJECT_ID,
        ),
        entries=[
            CoaEntryInput(
                entry_id=ENTRY_ID,
                account_code="10000000",
                semantic_key="MB-COA-ASSET",
                account_name="Assets",
                hierarchy_level=1,
                category="ASSET",
                normal_balance="DR",
                account_type="ACCOUNT_GROUP",
                is_postable=False,
                is_contra=False,
                is_monetary_default=True,
                source_lineage="approved-standard-chart.v1",
                source_row_hash=HASH_A,
            )
        ],
    )
    with factory.begin() as session:
        session.execute(
            EOS_COA_DEFINITION_RELEASE_TABLE.update()
            .where(
                EOS_COA_DEFINITION_RELEASE_TABLE.c.definition_release_id
                == COA_RELEASE_ID
            )
            .values(status="PUBLISHED", published_at=datetime.now().astimezone())
        )


def _release(**changes) -> ReportingMapReleaseInput:
    value = ReportingMapReleaseInput(
        mapping_release_id=MAP_RELEASE_ID,
        jurisdiction="KR",
        taxonomy_name="TEST-KIFRS",
        taxonomy_version="2026.1-test-only",
        effective_from=START,
        source_reference="test-only-taxonomy.json",
        source_hash=HASH_A,
        approved_proof_ref=HASH_B,
        content_hash=HASH_C,
        created_by=SUBJECT_ID,
    )
    return replace(value, **changes)


def _rule(status: str = "MAPPING_PENDING", **changes) -> ReportingMapRuleInput:
    value = ReportingMapRuleInput(
        mapping_rule_id=RULE_ID,
        entry_id=ENTRY_ID,
        statement_kind="BALANCE_SHEET",
        mapping_status=status,
        taxonomy_concept_id=("test_CashAndCashEquivalents" if status == "RESOLVED" else None),
        context={"period_type": "instant"},
        source_row_hash=HASH_A,
    )
    return replace(value, **changes)


def _publish(repository: SqlAlchemyEosReportingMapRepository) -> dict[str, object]:
    return repository.publish_approved(
        mapping_release_id=MAP_RELEASE_ID,
        source_hash=HASH_A,
        approved_proof_ref=HASH_B,
        content_hash=HASH_C,
    )


def test_product_registry_is_schema_valid_and_source_pending() -> None:
    schema = json.loads(
        (REGISTRY_DIR / "reporting_taxonomy_registry.schema.json").read_text()
    )
    registry = json.loads(
        (REGISTRY_DIR / "reporting_taxonomy_registry.v1.json").read_text()
    )
    Draft202012Validator(schema).validate(registry)
    assert registry["admission_state"] == "SOURCE_PENDING_NOT_ADMITTED"
    assert registry["approved_releases"] == []
    assert registry["constraints"]["regulated_export_when_pending"] == "FAIL_CLOSED"


@pytest.mark.parametrize("status", ["RESOLVED", "NOT_APPLICABLE"])
def test_published_non_pending_mapping_is_regulated_export_eligible(
    runtime, status: str
) -> None:
    _engine, _factory, _auth, repository, service = runtime
    repository.create_draft(release=_release(), rules=[_rule(status)])
    published = _publish(repository)
    replayed = _publish(repository)
    assert published["status"] == "PUBLISHED"
    assert replayed["published_at"] == published["published_at"]

    result = service.get_mapping(
        tenant_id=TENANT_ID,
        requester_subject_id=SUBJECT_ID,
        mapping_release_id=MAP_RELEASE_ID,
        entry_id=ENTRY_ID,
        effective_on=date(2026, 11, 11),
        regulated_export=True,
    )
    assert result["regulated_export_eligible"] is True
    assert result["rules"][0]["mapping_status"] == status
    assert result["evidence_hash"].startswith("sha256:")


def test_pending_mapping_is_queryable_but_regulated_export_fails_closed(runtime) -> None:
    _engine, _factory, _auth, repository, service = runtime
    draft = repository.create_draft(release=_release(), rules=[_rule()])
    assert draft["status"] == "DRAFT"
    assert draft["rules"][0]["context"]["context_hash"].startswith("sha256:")
    _publish(repository)

    internal = service.get_mapping(
        tenant_id=TENANT_ID,
        requester_subject_id=SUBJECT_ID,
        mapping_release_id=MAP_RELEASE_ID,
        entry_id=ENTRY_ID,
        effective_on=START,
        regulated_export=False,
    )
    assert internal["regulated_export_eligible"] is False
    with pytest.raises(EosReportingMapError) as captured:
        service.get_mapping(
            tenant_id=TENANT_ID,
            requester_subject_id=SUBJECT_ID,
            mapping_release_id=MAP_RELEASE_ID,
            entry_id=ENTRY_ID,
            effective_on=START,
            regulated_export=True,
        )
    assert captured.value.error_code == "EOS_COA_REPORTING_MAPPING_PENDING"


def test_publication_rejects_evidence_drift_and_duplicate_versions(runtime) -> None:
    _engine, _factory, _auth, repository, _service = runtime
    repository.create_draft(release=_release(), rules=[_rule()])
    with pytest.raises(EosReportingMapError, match="differs"):
        repository.publish_approved(
            mapping_release_id=MAP_RELEASE_ID,
            source_hash=HASH_C,
            approved_proof_ref=HASH_B,
            content_hash=HASH_C,
        )
    with pytest.raises(EosReportingMapError, match="conflicts"):
        repository.create_draft(
            release=_release(mapping_release_id=str(uuid.uuid4())),
            rules=[_rule(mapping_rule_id=str(uuid.uuid4()))],
        )


@pytest.mark.parametrize(
    ("release", "rule", "error"),
    [
        (_release(effective_until=START), _rule(), "effective_until"),
        (_release(jurisdiction="!"), _rule(), "jurisdiction"),
        (_release(source_hash="bad"), _rule(), "source_hash"),
        (_release(), _rule("RESOLVED", taxonomy_concept_id=None), "concept"),
        (_release(), _rule(taxonomy_concept_id="not-allowed"), "absent"),
        (_release(), _rule(statement_kind="INVALID"), "unsupported"),
        (_release(), _rule(context=[]), "object"),
    ],
)
def test_input_validation_fails_closed(runtime, release, rule, error: str) -> None:
    _engine, _factory, _auth, repository, _service = runtime
    with pytest.raises(EosReportingMapError, match=error):
        repository.create_draft(release=release, rules=[rule])


def test_rule_collection_and_query_validation_fail_closed(runtime) -> None:
    _engine, _factory, _auth, repository, _service = runtime
    with pytest.raises(EosReportingMapError, match="non-empty"):
        repository.create_draft(release=_release(), rules=[])
    with pytest.raises(EosReportingMapError, match="duplicate"):
        repository.create_draft(release=_release(), rules=[_rule(), _rule()])
    with pytest.raises(EosReportingMapError, match="UUID"):
        repository.publish_approved(
            mapping_release_id="bad",
            source_hash=HASH_A,
            approved_proof_ref=HASH_B,
            content_hash=HASH_C,
        )
    repository.create_draft(release=_release(), rules=[_rule()])
    with pytest.raises(EosReportingMapError, match="not effective"):
        repository.get_mapping(
            mapping_release_id=MAP_RELEASE_ID,
            entry_id=ENTRY_ID,
            effective_on=START,
            regulated_export=False,
        )


def test_missing_release_entry_expiry_and_terminal_publish_fail_closed(runtime) -> None:
    _engine, factory, _auth, repository, _service = runtime
    with pytest.raises(EosReportingMapError, match="not found"):
        _publish(repository)

    repository.create_draft(
        release=_release(effective_until=date(2026, 6, 1)),
        rules=[_rule()],
    )
    with factory.begin() as session:
        session.execute(
            EOS_COA_REPORTING_RELEASE_TABLE.update()
            .where(
                EOS_COA_REPORTING_RELEASE_TABLE.c.mapping_release_id
                == MAP_RELEASE_ID
            )
            .values(status="SUPERSEDED", published_at=datetime.now().astimezone())
        )
    with pytest.raises(EosReportingMapError, match="cannot be published"):
        _publish(repository)

    with factory.begin() as session:
        session.execute(
            EOS_COA_REPORTING_RELEASE_TABLE.update()
            .where(
                EOS_COA_REPORTING_RELEASE_TABLE.c.mapping_release_id
                == MAP_RELEASE_ID
            )
            .values(status="PUBLISHED")
        )
    with pytest.raises(EosReportingMapError, match="not effective"):
        repository.get_mapping(
            mapping_release_id=MAP_RELEASE_ID,
            entry_id=ENTRY_ID,
            effective_on=date(2026, 6, 1),
            regulated_export=False,
        )
    with pytest.raises(EosReportingMapError, match="entry was not found"):
        repository.get_mapping(
            mapping_release_id=MAP_RELEASE_ID,
            entry_id=str(uuid.uuid4()),
            effective_on=START,
            regulated_export=False,
        )
    with pytest.raises(EosReportingMapError, match="boolean"):
        repository.get_mapping(
            mapping_release_id=MAP_RELEASE_ID,
            entry_id=ENTRY_ID,
            effective_on=START,
            regulated_export="false",  # type: ignore[arg-type]
        )


def test_persistence_errors_are_translated_without_leaking_details() -> None:
    class BrokenFactory:
        def begin(self):
            raise SQLAlchemyError("private create/publish failure")

        def __call__(self):
            raise SQLAlchemyError("private read failure")

    repository = SqlAlchemyEosReportingMapRepository(BrokenFactory())  # type: ignore[arg-type]
    with pytest.raises(EosReportingMapError) as create_error:
        repository.create_draft(release=_release(), rules=[_rule()])
    assert create_error.value.error_code == "EOS_COA_REPORTING_PERSISTENCE_UNAVAILABLE"
    with pytest.raises(EosReportingMapError) as publish_error:
        _publish(repository)
    assert publish_error.value.retryable is True
    with pytest.raises(EosReportingMapError) as read_error:
        repository.get_mapping(
            mapping_release_id=MAP_RELEASE_ID,
            entry_id=ENTRY_ID,
            effective_on=START,
            regulated_export=False,
        )
    assert "private" not in read_error.value.detail


def test_malformed_rule_and_scalar_boundaries_are_rejected(runtime) -> None:
    _engine, _factory, _auth, repository, service = runtime
    invalid_cases = [
        (_release(created_by=""), [_rule()], "created_by"),
        (_release(taxonomy_name=""), [_rule()], "taxonomy_name"),
        (
            _release(effective_from=datetime.now().astimezone()),
            [_rule()],
            "effective_from",
        ),
        (_release(), [object()], "ReportingMapRuleInput"),
        (_release(), [_rule(context={"value": object()})], "canonical JSON"),
    ]
    for release, rules, expected in invalid_cases:
        with pytest.raises(EosReportingMapError, match=expected):
            repository.create_draft(release=release, rules=rules)  # type: ignore[arg-type]
    with pytest.raises(EosReportingMapError, match="stable reference"):
        service.get_mapping(
            tenant_id="",
            requester_subject_id=SUBJECT_ID,
            mapping_release_id=MAP_RELEASE_ID,
            entry_id=ENTRY_ID,
            effective_on=START,
            regulated_export=False,
        )


def test_authorization_distinguishes_denied_from_unavailable(runtime) -> None:
    _engine, _factory, auth, repository, service = runtime
    repository.create_draft(release=_release(), rules=[_rule("NOT_APPLICABLE")])
    _publish(repository)
    arguments = {
        "tenant_id": TENANT_ID,
        "requester_subject_id": SUBJECT_ID,
        "mapping_release_id": MAP_RELEASE_ID,
        "entry_id": ENTRY_ID,
        "effective_on": START,
        "regulated_export": False,
    }
    auth.scopes.clear()
    with pytest.raises(EosReportingMapError) as denied:
        service.get_mapping(**arguments)
    assert denied.value.status_code == 403
    auth.scopes.add("finance:report:read")
    auth.active = False
    with pytest.raises(EosReportingMapError) as inactive_payload:
        service.get_mapping(**arguments)
    assert inactive_payload.value.status_code == 403
    auth.active = True
    original = auth.effective_authorization
    auth.effective_authorization = lambda **_kwargs: {  # type: ignore[method-assign]
        "active": True,
        "tenant_id": "wrong-tenant",
        "subject_id": SUBJECT_ID,
        "scopes": ["finance:report:read"],
        "revision_hash": "d" * 64,
    }
    with pytest.raises(EosReportingMapError) as wrong_identity:
        service.get_mapping(**arguments)
    assert wrong_identity.value.status_code == 403
    auth.effective_authorization = lambda **_kwargs: {  # type: ignore[method-assign]
        "active": True,
        "tenant_id": TENANT_ID,
        "subject_id": SUBJECT_ID,
        "scopes": "finance:report:read",
        "revision_hash": "d" * 64,
    }
    with pytest.raises(EosReportingMapError) as malformed_scopes:
        service.get_mapping(**arguments)
    assert malformed_scopes.value.status_code == 503
    auth.effective_authorization = original  # type: ignore[method-assign]
    auth.revision_hash = "bad"
    with pytest.raises(EosReportingMapError) as invalid:
        service.get_mapping(**arguments)
    assert invalid.value.status_code == 503
    auth.unavailable = True
    with pytest.raises(EosReportingMapError) as unavailable:
        service.get_mapping(**arguments)
    assert unavailable.value.retryable is True
    auth.unavailable = False
    auth.denied = True
    with pytest.raises(EosReportingMapError) as inactive:
        service.get_mapping(**arguments)
    assert inactive.value.status_code == 403


def test_signed_route_enforces_service_trust_and_maps_domain_errors(runtime) -> None:
    _engine, _factory, _auth, repository, service = runtime
    repository.create_draft(release=_release(), rules=[_rule()])
    _publish(repository)
    app = create_eos_app(
        environ={
            "NEX_PROFILE": "test",
            "NEX_VERSION": "test",
            "NEX_BUILD_SHA": "test",
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
        }
    )
    client = TestClient(app)
    path = "/internal/v2/finance/reporting-map"
    params = {
        "mapping_release_id": MAP_RELEASE_ID,
        "entry_id": ENTRY_ID,
        "effective_on": START.isoformat(),
        "regulated_export": "true",
    }
    headers = {
        "X-NeX-Tenant-Id": TENANT_ID,
        "X-NeX-Subject-Id": SUBJECT_ID,
    }
    assert client.get(path, params=params, headers=headers).status_code == 401
    token = issue_mock_service_token(service_id="nex-ae-api", audience="nex-eos")
    trusted = {**headers, "Authorization": f"Bearer {token.access_token}"}
    unavailable = client.get(path, params=params, headers=trusted)
    assert unavailable.status_code == 503
    app.state.eos_reporting_map_service = service
    pending = client.get(path, params=params, headers=trusted)
    assert pending.status_code == 409
    assert pending.json()["error_code"] == "EOS_COA_REPORTING_MAPPING_PENDING"


@pytest.mark.skipif(
    not DATABASE_URL or not POSTGRES_SMOKE,
    reason="Protected COA-06 EOS PostgreSQL smoke is disabled",
)
def test_actual_postgres_reporting_map_and_zero_residue() -> None:
    schema_name = f"mybee_coa06_{uuid.uuid4().hex}"
    psycopg_url = psycopg_database_url(DATABASE_URL)
    with (
        psycopg.connect(psycopg_url, autocommit=True) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT current_database(), current_user")
        assert cursor.fetchone() == ("nex_eos_test", "nex_eos_user")
        cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
    scoped_url = make_url(DATABASE_URL).update_query_dict(
        {"options": f"-csearch_path={schema_name}"}
    ).render_as_string(hide_password=False)
    try:
        result = run_service_migrations("nex-eos", database_url=scoped_url, profile="test")
        assert "2519_eos_coa_reporting_map" in result.applied
        db = build_eos_database_runtime(
            environ={"NEX_EOS_TEST_DATABASE_URL": scoped_url},
            database_env="NEX_EOS_TEST_DATABASE_URL",
        )
        _seed_coa(db.session_factory)
        repository = SqlAlchemyEosReportingMapRepository(db.session_factory)
        repository.create_draft(release=_release(), rules=[_rule("RESOLVED")])
        _publish(repository)
        resolved = repository.get_mapping(
            mapping_release_id=MAP_RELEASE_ID,
            entry_id=ENTRY_ID,
            effective_on=date(2026, 11, 11),
            regulated_export=True,
        )
        assert resolved["regulated_export_eligible"] is True
        assert resolved["rules"][0]["taxonomy_concept_id"].startswith("test_")
        db.dispose()
    finally:
        with (
            psycopg.connect(psycopg_url, autocommit=True) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema_name)
                )
            )
