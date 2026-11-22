from __future__ import annotations

import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, datetime
from threading import Barrier

import psycopg
import pytest
from fastapi.testclient import TestClient
from nex_eos import (
    EOS_COA_COMPANY_ADOPTION_TABLE,
    EOS_COA_DEFINITION_RELEASE_TABLE,
    EOS_COA_ENTRY_TABLE,
    EOS_LEGAL_ENTITY_TABLE,
    EOS_METADATA,
    CoaDefinitionReleaseInput,
    CoaEntryInput,
    EosCoaReleaseAdminError,
    EosCoaReleaseAdminService,
    ReportingMapReleaseInput,
    ReportingMapRuleInput,
    SqlAlchemyEosCoaReleaseAdminRepository,
    SqlAlchemyEosReportingMapRepository,
    SqlAlchemyEosUnifiedCoaRepository,
    build_eos_database_runtime,
    create_eos_app,
)
from nex_eos.authorization import AuthorizationSubjectDenied
from nex_runtime import issue_mock_service_token, psycopg_database_url
from psycopg import sql
from run_migrations import run_service_migrations
from sqlalchemy import create_engine, func, make_url, select
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
POSTGRES_SMOKE = os.getenv("NEX_EOS_MYBEE_COA_07_POSTGRES_SMOKE") == "1"

ACTOR_TENANT = "product-tenant"
SUBJECT_ID = "product-accounting-owner"
BASE_RELEASE_ID = "f0000000-0000-4000-8000-000000000001"
TARGET_RELEASE_ID = "f0000000-0000-4000-8000-000000000002"
BASE_ROOT_ID = "f1000000-0000-4000-8000-000000000001"
TARGET_ROOT_ID = "f1000000-0000-4000-8000-000000000002"
TARGET_CHILD_ID = "f1000000-0000-4000-8000-000000000003"
BASE_UNCHANGED_ID = "f1000000-0000-4000-8000-000000000004"
TARGET_UNCHANGED_ID = "f1000000-0000-4000-8000-000000000005"
MAP_RELEASE_ID = "f2000000-0000-4000-8000-000000000001"
MAP_RULE_ID = "f3000000-0000-4000-8000-000000000001"
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64


class AuthorizationSource:
    def __init__(self) -> None:
        self.value: object = {
            "active": True,
            "tenant_id": ACTOR_TENANT,
            "subject_id": SUBJECT_ID,
            "scopes": ["finance:catalog:publish"],
            "revision_hash": "d" * 64,
        }
        self.denied = False
        self.unavailable = False

    def effective_authorization(self, *, tenant_id: str, subject_id: str):
        if self.unavailable:
            raise RuntimeError("private OA failure")
        if self.denied:
            raise AuthorizationSubjectDenied("inactive")
        return self.value


@pytest.fixture
def runtime():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    _seed_releases(factory)
    auth = AuthorizationSource()
    repository = SqlAlchemyEosCoaReleaseAdminRepository(factory)
    service = EosCoaReleaseAdminService(repository, auth)
    yield engine, factory, auth, repository, service
    engine.dispose()


def _release(
    release_id: str,
    version: str,
    effective_from: date,
    **changes,
) -> CoaDefinitionReleaseInput:
    value = CoaDefinitionReleaseInput(
        definition_release_id=release_id,
        scope_type="GLOBAL",
        chart_profile="MYBEE-KIFRS",
        release_version=version,
        effective_from=effective_from,
        source_reference=f"approved-standard-chart.{version}.json",
        source_hash=HASH_A,
        approved_proof_ref=HASH_B,
        content_hash=HASH_C,
        created_by=SUBJECT_ID,
    )
    return replace(value, **changes)


def _entry(
    entry_id: str,
    code: str,
    semantic_key: str,
    account_name: str,
    level: int,
    *,
    parent_entry_id: str | None = None,
    source_hash: str = HASH_A,
) -> CoaEntryInput:
    return CoaEntryInput(
        entry_id=entry_id,
        account_code=code,
        semantic_key=semantic_key,
        account_name=account_name,
        hierarchy_level=level,
        category="ASSET",
        account_type="ACCOUNT_GROUP",
        normal_balance="DR",
        is_contra=False,
        is_postable=False,
        is_monetary_default=True,
        source_lineage="approved-standard-chart",
        source_row_hash=source_hash,
        parent_entry_id=parent_entry_id,
    )


def _seed_releases(factory) -> None:
    repository = SqlAlchemyEosUnifiedCoaRepository(factory)
    repository.create_draft_release(
        release=_release(BASE_RELEASE_ID, "2026.01", date(2026, 1, 1)),
        entries=[
            _entry(
                BASE_ROOT_ID,
                "10000000",
                "MB-COA-ASSET",
                "Assets",
                1,
            ),
            _entry(
                BASE_UNCHANGED_ID,
                "10200000",
                "MB-COA-NONCURRENT-ASSET",
                "Non-current assets",
                2,
                parent_entry_id=BASE_ROOT_ID,
            ),
        ],
    )
    repository.create_draft_release(
        release=_release(TARGET_RELEASE_ID, "2027.01", date(2027, 1, 1)),
        entries=[
            _entry(
                TARGET_ROOT_ID,
                "10000000",
                "MB-COA-ASSET",
                "Total assets",
                1,
                source_hash=HASH_B,
            ),
            _entry(
                TARGET_CHILD_ID,
                "10100000",
                "MB-COA-CURRENT-ASSET",
                "Current assets",
                2,
                parent_entry_id=TARGET_ROOT_ID,
            ),
            _entry(
                TARGET_UNCHANGED_ID,
                "10200000",
                "MB-COA-NONCURRENT-ASSET",
                "Non-current assets",
                2,
                parent_entry_id=TARGET_ROOT_ID,
            ),
        ],
    )


def _service_arguments() -> dict[str, str]:
    return {
        "actor_tenant_id": ACTOR_TENANT,
        "requester_subject_id": SUBJECT_ID,
    }


def test_release_diff_reports_added_changed_and_stable_evidence(runtime) -> None:
    _engine, _factory, _auth, _repository, service = runtime
    first = service.preview_diff(
        **_service_arguments(),
        base_release_id=BASE_RELEASE_ID,
        target_release_id=TARGET_RELEASE_ID,
    )
    second = service.preview_diff(
        **_service_arguments(),
        base_release_id=BASE_RELEASE_ID,
        target_release_id=TARGET_RELEASE_ID,
    )
    assert first["summary"] == {
        "added": 1,
        "removed": 0,
        "changed": 1,
        "unchanged": 1,
    }
    assert first["added_account_codes"] == ["10100000"]
    assert first["changed"][0]["changed_fields"] == [
        "account_name",
        "source_row_hash",
    ]
    assert first["evidence_hash"] == second["evidence_hash"]


def test_operations_snapshot_exposes_metadata_only_pending_readiness(runtime) -> None:
    _engine, factory, _auth, _repository, service = runtime
    initial = service.operations_snapshot(**_service_arguments())
    assert initial["counts"]["releases"] == {"DRAFT": 2}
    assert initial["counts"]["entries"] == 5
    assert initial["readiness"]["regulated_reporting"] == "NO_PENDING_MAPPINGS"

    reporting = SqlAlchemyEosReportingMapRepository(factory)
    reporting.create_draft(
        release=ReportingMapReleaseInput(
            mapping_release_id=MAP_RELEASE_ID,
            jurisdiction="KR",
            taxonomy_name="TEST-KIFRS",
            taxonomy_version="2026-test-only",
            effective_from=date(2026, 1, 1),
            source_reference="test-taxonomy.json",
            source_hash=HASH_A,
            approved_proof_ref=HASH_B,
            content_hash=HASH_C,
            created_by=SUBJECT_ID,
        ),
        rules=[
            ReportingMapRuleInput(
                mapping_rule_id=MAP_RULE_ID,
                entry_id=BASE_ROOT_ID,
                statement_kind="BALANCE_SHEET",
                mapping_status="MAPPING_PENDING",
                source_row_hash=HASH_A,
            )
        ],
    )
    pending = service.operations_snapshot(**_service_arguments())
    assert pending["counts"]["reporting_mappings"] == {"MAPPING_PENDING": 1}
    assert pending["readiness"]["regulated_reporting"] == "BLOCKED_MAPPING_PENDING"
    assert pending["evidence_hash"].startswith("sha256:")


def test_release_diff_rejects_missing_same_incompatible_and_reverse(runtime) -> None:
    _engine, factory, _auth, repository, _service = runtime
    with pytest.raises(EosCoaReleaseAdminError, match="distinct"):
        repository.preview_diff(
            base_release_id=BASE_RELEASE_ID,
            target_release_id=BASE_RELEASE_ID,
        )
    with pytest.raises(EosCoaReleaseAdminError) as missing:
        repository.preview_diff(
            base_release_id=BASE_RELEASE_ID,
            target_release_id=str(uuid.uuid4()),
        )
    assert missing.value.status_code == 404
    with pytest.raises(EosCoaReleaseAdminError, match="after the base"):
        repository.preview_diff(
            base_release_id=TARGET_RELEASE_ID,
            target_release_id=BASE_RELEASE_ID,
        )
    with factory.begin() as session:
        session.execute(
            EOS_COA_DEFINITION_RELEASE_TABLE.update()
            .where(
                EOS_COA_DEFINITION_RELEASE_TABLE.c.definition_release_id
                == TARGET_RELEASE_ID
            )
            .values(chart_profile="OTHER-GAAP")
        )
    with pytest.raises(EosCoaReleaseAdminError, match="scope and profile"):
        repository.preview_diff(
            base_release_id=BASE_RELEASE_ID,
            target_release_id=TARGET_RELEASE_ID,
        )
    with pytest.raises(EosCoaReleaseAdminError, match="UUID"):
        repository.preview_diff(base_release_id="bad", target_release_id=TARGET_RELEASE_ID)


def test_admin_authority_denial_and_malformed_evidence_fail_closed(runtime) -> None:
    _engine, _factory, auth, _repository, service = runtime
    arguments = _service_arguments()
    auth.denied = True
    with pytest.raises(EosCoaReleaseAdminError) as denied:
        service.operations_snapshot(**arguments)
    assert denied.value.status_code == 403
    auth.denied = False
    auth.unavailable = True
    with pytest.raises(EosCoaReleaseAdminError) as unavailable:
        service.operations_snapshot(**arguments)
    assert unavailable.value.retryable is True
    auth.unavailable = False
    malformed_values = [
        None,
        {"active": False},
        {
            "active": True,
            "tenant_id": "wrong",
            "subject_id": SUBJECT_ID,
            "scopes": ["finance:catalog:publish"],
            "revision_hash": "d" * 64,
        },
        {
            "active": True,
            "tenant_id": ACTOR_TENANT,
            "subject_id": SUBJECT_ID,
            "scopes": "finance:catalog:publish",
            "revision_hash": "d" * 64,
        },
        {
            "active": True,
            "tenant_id": ACTOR_TENANT,
            "subject_id": SUBJECT_ID,
            "scopes": [],
            "revision_hash": "d" * 64,
        },
        {
            "active": True,
            "tenant_id": ACTOR_TENANT,
            "subject_id": SUBJECT_ID,
            "scopes": ["finance:catalog:publish"],
            "revision_hash": "bad",
        },
    ]
    for value in malformed_values:
        auth.value = value
        with pytest.raises(EosCoaReleaseAdminError):
            service.operations_snapshot(**arguments)
    auth.value = malformed_values[-1]
    with pytest.raises(EosCoaReleaseAdminError, match="stable reference"):
        service.operations_snapshot(
            actor_tenant_id="", requester_subject_id=SUBJECT_ID
        )


def test_persistence_failures_are_retryable_and_private() -> None:
    class BrokenFactory:
        def __call__(self):
            raise SQLAlchemyError("private database failure")

    repository = SqlAlchemyEosCoaReleaseAdminRepository(BrokenFactory())  # type: ignore[arg-type]
    with pytest.raises(EosCoaReleaseAdminError) as diff_error:
        repository.preview_diff(
            base_release_id=BASE_RELEASE_ID,
            target_release_id=TARGET_RELEASE_ID,
        )
    assert diff_error.value.retryable is True
    assert "private" not in diff_error.value.detail
    with pytest.raises(EosCoaReleaseAdminError) as snapshot_error:
        repository.operations_snapshot()
    assert snapshot_error.value.error_code == "EOS_COA_ADMIN_PERSISTENCE_UNAVAILABLE"


def test_signed_admin_routes_require_trust_and_map_domain_errors(runtime) -> None:
    _engine, _factory, auth, _repository, service = runtime
    app = create_eos_app(
        environ={
            "NEX_PROFILE": "test",
            "NEX_VERSION": "test",
            "NEX_BUILD_SHA": "test",
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
        }
    )
    client = TestClient(app)
    headers = {
        "X-NeX-Tenant-Id": ACTOR_TENANT,
        "X-NeX-Subject-Id": SUBJECT_ID,
    }
    path = "/internal/v2/finance/coa/releases/diff"
    params = {
        "base_release_id": BASE_RELEASE_ID,
        "target_release_id": TARGET_RELEASE_ID,
    }
    assert client.get(path, params=params, headers=headers).status_code == 401
    operations_path = "/internal/v2/finance/coa/operations"
    assert client.get(operations_path, headers=headers).status_code == 401
    token = issue_mock_service_token(service_id="nex-ag", audience="nex-eos")
    trusted = {**headers, "Authorization": f"Bearer {token.access_token}"}
    assert client.get(path, params=params, headers=trusted).status_code == 503
    assert client.get(operations_path, headers=trusted).status_code == 503
    app.state.eos_coa_release_admin_service = service
    diff = client.get(path, params=params, headers=trusted)
    snapshot = client.get(operations_path, headers=trusted)
    assert diff.status_code == 200
    assert snapshot.status_code == 200
    bad = client.get(
        path,
        params={**params, "target_release_id": BASE_RELEASE_ID},
        headers=trusted,
    )
    assert bad.status_code == 422
    assert bad.json()["error_code"] == "EOS_COA_ADMIN_INPUT_INVALID"
    auth.denied = True
    denied = client.get(operations_path, headers=trusted)
    assert denied.status_code == 403
    assert denied.json()["error_code"] == "EOS_COA_ADMIN_AUTHORIZATION_DENIED"


@pytest.mark.skipif(
    not DATABASE_URL or not POSTGRES_SMOKE,
    reason="Protected COA-07 EOS PostgreSQL smoke is disabled",
)
def test_actual_postgres_upgrade_immutability_rollback_and_zero_residue() -> None:
    schema_name = f"mybee_coa07_{uuid.uuid4().hex}"
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
        assert "2520_eos_coa_adoption_concurrency" in result.applied
        db = build_eos_database_runtime(
            environ={"NEX_EOS_TEST_DATABASE_URL": scoped_url},
            database_env="NEX_EOS_TEST_DATABASE_URL",
        )
        _seed_releases(db.session_factory)
        repository = SqlAlchemyEosCoaReleaseAdminRepository(db.session_factory)
        diff = repository.preview_diff(
            base_release_id=BASE_RELEASE_ID,
            target_release_id=TARGET_RELEASE_ID,
        )
        assert diff["summary"]["added"] == 1
        with db.session_factory.begin() as session:
            session.execute(
                EOS_COA_DEFINITION_RELEASE_TABLE.update()
                .where(
                    EOS_COA_DEFINITION_RELEASE_TABLE.c.definition_release_id
                    == BASE_RELEASE_ID
                )
                .values(status="PUBLISHED", published_at=datetime.now().astimezone())
            )
            session.execute(
                EOS_LEGAL_ENTITY_TABLE.insert().values(
                    tenant_id="tenant-a",
                    company_id="f4000000-0000-4000-8000-000000000001",
                    company_code="COMPANY-A",
                    name="Company A",
                    functional_currency="KRW",
                    presentation_currency="KRW",
                    business_timezone="Asia/Seoul",
                    status="ACTIVE",
                    effective_from=date(2026, 1, 1),
                    version=1,
                    created_at=datetime.now().astimezone(),
                    updated_at=datetime.now().astimezone(),
                )
            )
        with (
            pytest.raises(DBAPIError, match="immutable"),
            db.session_factory.begin() as session,
        ):
            session.execute(
                EOS_COA_ENTRY_TABLE.update()
                .where(EOS_COA_ENTRY_TABLE.c.entry_id == BASE_ROOT_ID)
                .values(account_name="Tampered")
            )
        rollback_id = str(uuid.uuid4())
        with (
            pytest.raises(RuntimeError, match="injected crash"),
            db.session_factory.begin() as session,
        ):
            session.execute(
                EOS_COA_DEFINITION_RELEASE_TABLE.insert().values(
                    definition_release_id=rollback_id,
                    scope_type="GLOBAL",
                    owner_tenant_id=None,
                    base_global_release_id=None,
                    chart_profile="MYBEE-KIFRS",
                    release_version="rollback-test",
                    effective_from=date(2028, 1, 1),
                    source_reference="rollback-test.json",
                    source_hash=HASH_A,
                    approved_proof_ref=HASH_B,
                    content_hash=HASH_C,
                    status="DRAFT",
                    created_by=SUBJECT_ID,
                    created_at=datetime.now().astimezone(),
                    published_at=None,
                )
            )
            raise RuntimeError("injected crash")
        with db.session_factory() as session:
            rollback_count = session.execute(
                select(func.count())
                .select_from(EOS_COA_DEFINITION_RELEASE_TABLE)
                .where(
                    EOS_COA_DEFINITION_RELEASE_TABLE.c.definition_release_id
                    == rollback_id
                )
            ).scalar_one()
            stored_name = session.execute(
                select(EOS_COA_ENTRY_TABLE.c.account_name).where(
                    EOS_COA_ENTRY_TABLE.c.entry_id == BASE_ROOT_ID
                )
            ).scalar_one()
        assert rollback_count == 0
        assert stored_name == "Assets"

        barrier = Barrier(2)
        scoped_psycopg_url = psycopg_database_url(scoped_url)

        def insert_overlapping_adoption(adoption_id: str) -> str:
            with psycopg.connect(scoped_psycopg_url) as connection:
                barrier.wait(timeout=5)
                try:
                    connection.execute(
                        """
                        INSERT INTO eos_coa_company_adoption (
                            tenant_id, adoption_id, company_id,
                            global_release_id, extension_release_id,
                            effective_from, effective_until,
                            approved_proof_ref, state, created_by, created_at
                        ) VALUES (
                            'tenant-a', %s,
                            'f4000000-0000-4000-8000-000000000001',
                            %s, NULL, DATE '2026-01-01', NULL,
                            %s, 'APPROVED', %s, now()
                        )
                        """,
                        (adoption_id, BASE_RELEASE_ID, HASH_B, SUBJECT_ID),
                    )
                    time.sleep(0.2)
                    connection.commit()
                    return "COMMITTED"
                except psycopg.Error as exc:
                    connection.rollback()
                    return exc.sqlstate or "UNKNOWN"

        adoption_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(insert_overlapping_adoption, adoption_ids))
        assert sorted(outcomes) == ["23505", "COMMITTED"]
        with db.session_factory() as session:
            adoption_count = session.execute(
                select(func.count()).select_from(EOS_COA_COMPANY_ADOPTION_TABLE)
            ).scalar_one()
        assert adoption_count == 1
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
