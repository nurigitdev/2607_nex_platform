from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from threading import Barrier

import nex_eos.fx_rates as fx
import psycopg
import pytest
from fastapi.testclient import TestClient
from nex_eos import (
    EOS_FX_RATE_POLICY_TABLE,
    EOS_LEGAL_ENTITY_TABLE,
    EOS_METADATA,
    EosFxRateError,
    EosFxRateService,
    FxRatePolicyInput,
    FxRateSnapshotInput,
    LegalEntityInput,
    SqlAlchemyEosFxRateRepository,
    SqlAlchemyEosLegalEntityRepository,
    build_eos_database_runtime,
    create_eos_app,
    fx_policy_hash,
)
from nex_eos.authorization import AuthorizationSubjectDenied
from nex_runtime import issue_mock_service_token, psycopg_database_url
from psycopg import sql
from run_migrations import run_service_migrations
from sqlalchemy import create_engine, make_url, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
POSTGRES_SMOKE = os.getenv("NEX_EOS_MYBEE_S1_04_POSTGRES_SMOKE") == "1"

TENANT_ID = "tenant-a"
SUBJECT_ID = "fx-owner"
COMPANY_ID = "f1000000-0000-4000-8000-000000000001"
POLICY_ID = "f2000000-0000-4000-8000-000000000001"
SNAPSHOT_ID = "f3000000-0000-4000-8000-000000000001"
PROOF = "sha256:" + "a" * 64
SOURCE_HASH = "sha256:" + "b" * 64
SOURCE_URI = "https://www.smbs.biz/ExRate/TodayExRate.jsp"


class AuthorizationSource:
    def __init__(self) -> None:
        self.value: object = {
            "active": True,
            "tenant_id": TENANT_ID,
            "subject_id": SUBJECT_ID,
            "scopes": ["finance:fx:publish", "finance:fx:read"],
            "revision_hash": "c" * 64,
        }
        self.denied = False
        self.unavailable = False

    def effective_authorization(self, *, tenant_id: str, subject_id: str):
        if self.denied:
            raise AuthorizationSubjectDenied("inactive")
        if self.unavailable:
            raise RuntimeError("private OA outage")
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
    _seed_company(factory)
    repository = SqlAlchemyEosFxRateRepository(factory)
    authorization = AuthorizationSource()
    service = EosFxRateService(repository, authorization)
    yield engine, factory, repository, authorization, service
    engine.dispose()


def _seed_company(factory) -> None:
    SqlAlchemyEosLegalEntityRepository(factory).create_legal_entity(
        LegalEntityInput(
            tenant_id=TENANT_ID,
            company_id=COMPANY_ID,
            company_code="NEXKR",
            name="NeX Korea",
            functional_currency="KRW",
            presentation_currency="KRW",
            business_timezone="Asia/Seoul",
            effective_from=date(2026, 1, 1),
        )
    )


def _policy(
    *,
    policy_id: str = POLICY_ID,
    selector: str = "FINAL",
    allow_previous: bool = True,
    staleness: int = 1,
    effective_from: date = date(2026, 1, 1),
    effective_to: date | None = None,
    purpose: str = "TRANSACTION_SPOT",
    approved_by: str = SUBJECT_ID,
    company_id: str = COMPANY_ID,
) -> FxRatePolicyInput:
    semantics = {
        "tenant_id": TENANT_ID,
        "company_id": company_id,
        "policy_id": policy_id,
        "version": 1,
        "purpose": purpose,
        "base_currency": "JPY",
        "quote_currency": "KRW",
        "rate_kind": "MARKET_BASE",
        "source_provider_id": "SMBS_TODAY_EXRATE",
        "publication_selector": selector,
        "effective_from": effective_from.isoformat(),
        "effective_to": effective_to.isoformat() if effective_to else None,
        "allow_previous_business_day": allow_previous,
        "max_staleness_business_days": staleness,
        "rounding_mode": "HALF_EVEN",
        "rate_decimal_scale": 6,
        "approved_by": approved_by,
        "approval_proof_hash": PROOF,
    }
    return FxRatePolicyInput(
        tenant_id=TENANT_ID,
        company_id=company_id,
        policy_id=policy_id,
        version=1,
        purpose=purpose,
        base_currency="JPY",
        quote_currency="KRW",
        rate_kind="MARKET_BASE",
        source_provider_id="SMBS_TODAY_EXRATE",
        publication_selector=selector,
        effective_from=effective_from,
        effective_to=effective_to,
        allow_previous_business_day=allow_previous,
        max_staleness_business_days=staleness,
        rounding_mode="HALF_EVEN",
        rate_decimal_scale=6,
        approved_by=approved_by,
        approval_proof_hash=PROOF,
        policy_hash=fx_policy_hash(semantics),
    )


def _snapshot(
    *,
    snapshot_id: str = SNAPSHOT_ID,
    desired: date = date(2026, 11, 9),
    rate_date: date = date(2026, 11, 9),
    is_final: bool = True,
    source_record_id: str = "smbs:2026-11-09:jpy:final",
    published_rate: Decimal = Decimal("960.50"),
) -> FxRateSnapshotInput:
    return FxRateSnapshotInput(
        tenant_id=TENANT_ID,
        company_id=COMPANY_ID,
        rate_snapshot_id=snapshot_id,
        rate_policy_id=POLICY_ID,
        rate_policy_version=1,
        source_provider_id="SMBS_TODAY_EXRATE",
        base_currency="JPY",
        quote_currency="KRW",
        quote_unit=Decimal(100),
        published_rate=published_rate,
        desired_rate_date=desired,
        rate_date=rate_date,
        rate_as_of=datetime(2026, 11, 9, 10, 0, tzinfo=UTC),
        published_at=datetime(2026, 11, 9, 9, 0, tzinfo=UTC),
        publication_issue="FINAL",
        is_final=is_final,
        source_record_id=source_record_id,
        source_uri=SOURCE_URI,
        source_sha256=SOURCE_HASH,
        calendar_ref="KR_BUSINESS_DAY_V1",
        source_timezone="Asia/Seoul",
        provenance={"acquisition_mode": "MANUAL_APPROVED_IMPORT", "row": 12},
    )


def _policy_payload(value: FxRatePolicyInput) -> dict[str, object]:
    return {
        "company_id": value.company_id,
        "policy_id": value.policy_id,
        "version": value.version,
        "purpose": value.purpose,
        "base_currency": value.base_currency,
        "quote_currency": value.quote_currency,
        "rate_kind": value.rate_kind,
        "source_provider_id": value.source_provider_id,
        "publication_selector": value.publication_selector,
        "effective_from": value.effective_from.isoformat(),
        "effective_to": value.effective_to.isoformat() if value.effective_to else None,
        "allow_previous_business_day": value.allow_previous_business_day,
        "max_staleness_business_days": value.max_staleness_business_days,
        "rounding_mode": value.rounding_mode,
        "rate_decimal_scale": value.rate_decimal_scale,
        "approved_by": value.approved_by,
        "approval_proof_hash": value.approval_proof_hash,
        "policy_hash": value.policy_hash,
    }


def _snapshot_payload(value: FxRateSnapshotInput) -> dict[str, object]:
    return {
        "company_id": value.company_id,
        "rate_snapshot_id": value.rate_snapshot_id,
        "rate_policy_id": value.rate_policy_id,
        "rate_policy_version": value.rate_policy_version,
        "source_provider_id": value.source_provider_id,
        "base_currency": value.base_currency,
        "quote_currency": value.quote_currency,
        "quote_unit": str(value.quote_unit),
        "published_rate": str(value.published_rate),
        "desired_rate_date": value.desired_rate_date.isoformat(),
        "rate_date": value.rate_date.isoformat(),
        "rate_as_of": value.rate_as_of.isoformat(),
        "published_at": value.published_at.isoformat(),
        "publication_issue": value.publication_issue,
        "is_final": value.is_final,
        "source_record_id": value.source_record_id,
        "source_uri": value.source_uri,
        "source_sha256": value.source_sha256,
        "calendar_ref": value.calendar_ref,
        "source_timezone": value.source_timezone,
        "provenance": dict(value.provenance),
    }


def test_policy_and_snapshot_exact_replay_normalize_quote_unit(runtime) -> None:
    _engine, _factory, repository, _authorization, _service = runtime
    policy = repository.create_approved_policy(_policy())
    assert repository.create_approved_policy(_policy()) == policy
    snapshot = repository.import_approved_snapshot(_snapshot())
    replay = repository.import_approved_snapshot(_snapshot())
    assert replay == snapshot
    assert snapshot["published_rate"] == "960.5"
    assert snapshot["quote_unit"] == "100"
    assert snapshot["normalized_rate"] == "9.605"
    assert snapshot["source_uri"] == SOURCE_URI
    assert snapshot["source_sha256"] == SOURCE_HASH
    assert snapshot["provenance_json"]["acquisition_mode"] == "MANUAL_APPROVED_IMPORT"


def test_policy_validation_overlap_and_company_guards(runtime) -> None:
    _engine, factory, repository, _authorization, _service = runtime
    with pytest.raises(EosFxRateError, match="policy_hash"):
        repository.create_approved_policy(replace(_policy(), policy_hash=PROOF))
    repository.create_approved_policy(_policy())
    with pytest.raises(EosFxRateError, match="different semantics"):
        repository.create_approved_policy(_policy(approved_by="other"))
    with pytest.raises(EosFxRateError, match="overlaps"):
        repository.create_approved_policy(_policy(policy_id=str(uuid.uuid4())))
    with factory.begin() as session:
        session.execute(
            EOS_FX_RATE_POLICY_TABLE.delete().where(
                EOS_FX_RATE_POLICY_TABLE.c.tenant_id == TENANT_ID
            )
        )
        session.execute(
            EOS_LEGAL_ENTITY_TABLE.update()
            .where(
                EOS_LEGAL_ENTITY_TABLE.c.tenant_id == TENANT_ID,
                EOS_LEGAL_ENTITY_TABLE.c.company_id == COMPANY_ID,
            )
            .values(status="INACTIVE")
        )
    with pytest.raises(EosFxRateError, match="not active"):
        repository.create_approved_policy(_policy(policy_id=str(uuid.uuid4())))


def test_snapshot_policy_binding_publication_and_source_conflicts(runtime) -> None:
    _engine, _factory, repository, _authorization, _service = runtime
    repository.create_approved_policy(_policy())
    with pytest.raises(EosFxRateError, match="FINAL policy"):
        repository.import_approved_snapshot(_snapshot(is_final=False))
    admitted = repository.import_approved_snapshot(_snapshot())
    assert admitted["approved_state"] == "APPROVED"
    source_replay = repository.import_approved_snapshot(
        _snapshot(snapshot_id=str(uuid.uuid4()))
    )
    assert source_replay["rate_snapshot_id"] == SNAPSHOT_ID
    with pytest.raises(EosFxRateError, match="different semantics"):
        repository.import_approved_snapshot(_snapshot(published_rate=Decimal("961.50")))
    with pytest.raises(EosFxRateError, match="already admitted"):
        repository.import_approved_snapshot(
            _snapshot(
                snapshot_id=str(uuid.uuid4()),
                published_rate=Decimal("961.50"),
            )
        )
    with pytest.raises(EosFxRateError, match="does not match"):
        repository.import_approved_snapshot(
            replace(_snapshot(snapshot_id=str(uuid.uuid4())), base_currency="USD")
        )


def test_exact_and_previous_business_day_resolution_are_fail_closed(runtime) -> None:
    _engine, _factory, repository, _authorization, _service = runtime
    repository.create_approved_policy(_policy())
    repository.import_approved_snapshot(_snapshot())
    exact = repository.resolve_rate(
        tenant_id=TENANT_ID,
        company_id=COMPANY_ID,
        purpose="TRANSACTION_SPOT",
        base_currency="JPY",
        quote_currency="KRW",
        desired_rate_date=date(2026, 11, 9),
        as_of=datetime(2026, 11, 9, 10, 0, tzinfo=UTC),
    )
    assert exact["staleness_business_days"] == 0
    fallback = repository.resolve_rate(
        tenant_id=TENANT_ID,
        company_id=COMPANY_ID,
        purpose="TRANSACTION_SPOT",
        base_currency="JPY",
        quote_currency="KRW",
        desired_rate_date=date(2026, 11, 10),
    )
    assert fallback["selected_rate_date"] == "2026-11-09"
    assert fallback["staleness_business_days"] == 1
    with pytest.raises(EosFxRateError) as stale:
        repository.resolve_rate(
            tenant_id=TENANT_ID,
            company_id=COMPANY_ID,
            purpose="TRANSACTION_SPOT",
            base_currency="JPY",
            quote_currency="KRW",
            desired_rate_date=date(2026, 11, 11),
        )
    assert stale.value.error_code == "FX_RATE_STALE_OR_UNTRUSTED"
    with pytest.raises(EosFxRateError) as missing:
        repository.resolve_rate(
            tenant_id=TENANT_ID,
            company_id=COMPANY_ID,
            purpose="MONETARY_CLOSE",
            base_currency="JPY",
            quote_currency="KRW",
            desired_rate_date=date(2026, 11, 9),
        )
    assert missing.value.error_code == "FX_RATE_UNAVAILABLE"


def test_previous_day_requires_explicit_policy_and_available_as_of(runtime) -> None:
    _engine, _factory, repository, _authorization, _service = runtime
    repository.create_approved_policy(_policy(allow_previous=False, staleness=0))
    repository.import_approved_snapshot(_snapshot())
    with pytest.raises(EosFxRateError, match="fallback is not approved"):
        repository.resolve_rate(
            tenant_id=TENANT_ID,
            company_id=COMPANY_ID,
            purpose="TRANSACTION_SPOT",
            base_currency="JPY",
            quote_currency="KRW",
            desired_rate_date=date(2026, 11, 10),
        )
    with pytest.raises(EosFxRateError, match="no trusted"):
        repository.resolve_rate(
            tenant_id=TENANT_ID,
            company_id=COMPANY_ID,
            purpose="TRANSACTION_SPOT",
            base_currency="JPY",
            quote_currency="KRW",
            desired_rate_date=date(2026, 11, 9),
            as_of=datetime(2026, 11, 9, 8, 59, tzinfo=UTC),
        )


def test_service_batch_authorization_validation_and_resolution(runtime) -> None:
    _engine, _factory, _repository, authorization, service = runtime
    policy = _policy()
    created = service.create_approved_policy(
        tenant_id=TENANT_ID,
        requester_subject_id=SUBJECT_ID,
        payload=_policy_payload(policy),
    )
    assert created["policy_hash"] == policy.policy_hash
    result = service.import_rates(
        tenant_id=TENANT_ID,
        requester_subject_id=SUBJECT_ID,
        payload={"snapshots": [_snapshot_payload(_snapshot())]},
    )
    assert len(result["snapshots"]) == 1
    resolved = service.resolve_rate(
        tenant_id=TENANT_ID,
        requester_subject_id=SUBJECT_ID,
        company_id=COMPANY_ID,
        purpose="TRANSACTION_SPOT",
        base_currency="JPY",
        quote_currency="KRW",
        desired_rate_date=date(2026, 11, 9),
    )
    assert resolved["normalized_rate"] == "9.605"
    with pytest.raises(EosFxRateError, match="non-empty array"):
        service.import_rates(
            tenant_id=TENANT_ID,
            requester_subject_id=SUBJECT_ID,
            payload={"snapshots": []},
        )
    authorization.denied = True
    with pytest.raises(EosFxRateError) as denied:
        service.resolve_rate(
            tenant_id=TENANT_ID,
            requester_subject_id=SUBJECT_ID,
            company_id=COMPANY_ID,
            purpose="TRANSACTION_SPOT",
            base_currency="JPY",
            quote_currency="KRW",
            desired_rate_date=date(2026, 11, 9),
        )
    assert denied.value.status_code == 403
    authorization.denied = False
    authorization.unavailable = True
    with pytest.raises(EosFxRateError) as unavailable:
        service.create_approved_policy(
            tenant_id=TENANT_ID,
            requester_subject_id=SUBJECT_ID,
            payload=_policy_payload(policy),
        )
    assert unavailable.value.retryable is True


def test_signed_fx_routes_require_trust_and_map_domain_errors(runtime) -> None:
    _engine, _factory, _repository, authorization, service = runtime
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
        "X-NeX-Tenant-Id": TENANT_ID,
        "X-NeX-Subject-Id": SUBJECT_ID,
    }
    policy_path = "/internal/v2/finance/fx-rate-policies/approved"
    assert client.post(policy_path, headers=headers, json={}).status_code == 401
    token = issue_mock_service_token(service_id="nex-ae-api", audience="nex-eos")
    trusted = {**headers, "Authorization": f"Bearer {token.access_token}"}
    assert (
        client.post(
            policy_path, headers=trusted, json=_policy_payload(_policy())
        ).status_code
        == 503
    )
    app.state.eos_fx_rate_service = service
    assert (
        client.post(
            policy_path, headers=trusted, json=_policy_payload(_policy())
        ).status_code
        == 201
    )
    imported = client.post(
        "/internal/v2/finance/fx-rate-batches",
        headers=trusted,
        json={"snapshots": [_snapshot_payload(_snapshot())]},
    )
    assert imported.status_code == 201
    resolved = client.get(
        "/internal/v2/finance/fx-rates:resolve",
        headers=trusted,
        params={
            "company_id": COMPANY_ID,
            "purpose": "TRANSACTION_SPOT",
            "base_currency": "JPY",
            "quote_currency": "KRW",
            "desired_rate_date": "2026-11-09",
        },
    )
    assert resolved.status_code == 200
    assert resolved.json()["normalized_rate"] == "9.605"
    authorization.value = {
        "active": True,
        "tenant_id": TENANT_ID,
        "subject_id": SUBJECT_ID,
        "scopes": ["finance:fx:read"],
        "revision_hash": "c" * 64,
    }
    denied = client.post(
        "/internal/v2/finance/fx-rate-batches",
        headers=trusted,
        json={"snapshots": [_snapshot_payload(_snapshot())]},
    )
    assert denied.status_code == 403


def test_first_publication_and_bounded_policy_intervals(runtime) -> None:
    _engine, _factory, repository, _authorization, _service = runtime
    first = _policy(
        selector="FIRST",
        effective_to=date(2026, 7, 1),
        allow_previous=False,
        staleness=0,
    )
    repository.create_approved_policy(first)
    first_snapshot = _snapshot(
        desired=date(2026, 6, 30),
        rate_date=date(2026, 6, 30),
        source_record_id="smbs:2026-06-30:jpy:first",
    )
    with pytest.raises(EosFxRateError, match="FIRST policy"):
        repository.import_approved_snapshot(first_snapshot)
    admitted = repository.import_approved_snapshot(
        replace(first_snapshot, is_final=False)
    )
    assert admitted["is_final"] is False
    later = _policy(
        policy_id=str(uuid.uuid4()),
        effective_from=date(2026, 7, 1),
        purpose="MONETARY_CLOSE",
    )
    assert repository.create_approved_policy(later)["effective_from"] == "2026-07-01"


def test_missing_company_policy_and_malformed_authority_fail_closed(runtime) -> None:
    _engine, _factory, repository, authorization, service = runtime
    with pytest.raises(EosFxRateError) as missing_company:
        repository.create_approved_policy(_policy(company_id=str(uuid.uuid4())))
    assert missing_company.value.status_code == 404
    with pytest.raises(EosFxRateError, match="approved FX policy"):
        repository.import_approved_snapshot(_snapshot())
    for malformed in (
        None,
        {"active": True},
        {
            "active": True,
            "tenant_id": TENANT_ID,
            "subject_id": SUBJECT_ID,
            "scopes": "finance:fx:read",
            "revision_hash": "c" * 64,
        },
        {
            "active": True,
            "tenant_id": TENANT_ID,
            "subject_id": SUBJECT_ID,
            "scopes": [1],
            "revision_hash": "c" * 64,
        },
        {
            "active": True,
            "tenant_id": TENANT_ID,
            "subject_id": SUBJECT_ID,
            "scopes": ["finance:fx:read"],
            "revision_hash": "bad",
        },
    ):
        authorization.value = malformed
        with pytest.raises(EosFxRateError) as error:
            service.resolve_rate(
                tenant_id=TENANT_ID,
                requester_subject_id=SUBJECT_ID,
                company_id=COMPANY_ID,
                purpose="TRANSACTION_SPOT",
                base_currency="JPY",
                quote_currency="KRW",
                desired_rate_date=date(2026, 11, 9),
            )
        assert error.value.status_code in {403, 503}


@pytest.mark.parametrize(
    ("builder", "message"),
    [
        (lambda: fx._policy_record(object()), "FxRatePolicyInput"),
        (
            lambda: fx._policy_record(
                replace(
                    _policy(effective_to=date(2026, 1, 2)),
                    effective_to=date(2025, 12, 31),
                )
            ),
            "effective_to",
        ),
        (
            lambda: fx._policy_record(
                replace(
                    _policy(allow_previous=False, staleness=0),
                    max_staleness_business_days=1,
                )
            ),
            "staleness",
        ),
        (
            lambda: fx._policy_record(replace(_policy(), rounding_mode="HALF_UP")),
            "rounding_mode",
        ),
        (
            lambda: fx._policy_record(replace(_policy(), quote_currency="JPY")),
            "must differ",
        ),
        (lambda: fx._snapshot_values(object()), "FxRateSnapshotInput"),
        (
            lambda: fx._snapshot_values(
                replace(_snapshot(), source_timezone="Mars/Base")
            ),
            "IANA timezone",
        ),
        (
            lambda: fx._snapshot_values(replace(_snapshot(), provenance=[])),
            "provenance",
        ),
        (
            lambda: fx._snapshot_values(replace(_snapshot(), quote_unit=Decimal(0))),
            "greater than zero",
        ),
        (
            lambda: fx._snapshot_values(
                replace(_snapshot(), source_uri="file:///tmp/rate")
            ),
            "http or https",
        ),
        (
            lambda: fx._business_day_distance(date(2026, 11, 10), date(2026, 11, 9)),
            "cannot follow",
        ),
    ],
)
def test_domain_validation_rejects_ambiguous_inputs(builder, message) -> None:
    with pytest.raises(EosFxRateError, match=message):
        builder()


@pytest.mark.parametrize(
    "operation",
    [
        lambda: fx._policy_input(TENANT_ID, object()),
        lambda: fx._snapshot_input(TENANT_ID, object()),
        lambda: fx._policy_input(TENANT_ID, {**_policy_payload(_policy()), "extra": 1}),
        lambda: fx._snapshot_input(
            TENANT_ID, {**_snapshot_payload(_snapshot()), "extra": 1}
        ),
        lambda: fx._parse_date("value", None),
        lambda: fx._parse_date("value", "not-a-date"),
        lambda: fx._parse_datetime("value", None),
        lambda: fx._parse_datetime("value", "not-a-datetime"),
        lambda: fx._aware_datetime(
            "value", datetime.fromisoformat("2026-01-01T00:00:00")
        ),
        lambda: fx._decimal("value", True),
        lambda: fx._decimal("value", "not-decimal"),
        lambda: fx._uuid("value", "bad"),
        lambda: fx._scoped_id("value", "bad value"),
        lambda: fx._currency("value", "jpy"),
        lambda: fx._choice("value", "BAD", fx.FX_POLICY_PURPOSES),
        lambda: fx._date("value", datetime.now(UTC)),
        lambda: fx._bounded_int("value", True, 0, 1),
        lambda: fx._boolean("value", "true"),
        lambda: fx._text("value", "", maximum=4),
        lambda: fx._hash_ref("value", "bad"),
    ],
)
def test_boundary_parsers_reject_malformed_values(operation) -> None:
    with pytest.raises(EosFxRateError):
        operation()


@pytest.mark.skipif(
    not DATABASE_URL or not POSTGRES_SMOKE,
    reason="Protected S1-04 EOS PostgreSQL smoke is disabled",
)
def test_actual_postgres_fx_policy_snapshot_concurrency_and_zero_residue() -> None:
    schema_name = f"mybee_s104_{uuid.uuid4().hex}"
    psycopg_url = psycopg_database_url(DATABASE_URL)
    with (
        psycopg.connect(psycopg_url, autocommit=True) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT current_database(), current_user")
        assert cursor.fetchone() == ("nex_eos_test", "nex_eos_user")
        cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
    scoped_url = (
        make_url(DATABASE_URL)
        .update_query_dict({"options": f"-csearch_path={schema_name}"})
        .render_as_string(hide_password=False)
    )
    try:
        result = run_service_migrations(
            "nex-eos", database_url=scoped_url, profile="test"
        )
        assert "2522_eos_fx_rate_policy_snapshot" in result.applied
        db = build_eos_database_runtime(
            environ={"NEX_EOS_TEST_DATABASE_URL": scoped_url},
            database_env="NEX_EOS_TEST_DATABASE_URL",
        )
        _seed_company(db.session_factory)
        repository = SqlAlchemyEosFxRateRepository(db.session_factory)
        barrier = Barrier(2)

        def insert_policy(index: int) -> str:
            try:
                barrier.wait(timeout=5)
                repository.create_approved_policy(
                    _policy(policy_id=str(uuid.UUID(int=index + 1)))
                )
                return "COMMITTED"
            except EosFxRateError as exc:
                return exc.error_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(insert_policy, range(2)))
        assert sorted(outcomes) == ["COMMITTED", "EOS_FX_RATE_CONFLICT"]
        with db.session_factory() as session:
            policy_id = session.execute(
                select(EOS_FX_RATE_POLICY_TABLE.c.policy_id)
            ).scalar_one()
        accepted = repository.import_approved_snapshot(
            replace(_snapshot(), rate_policy_id=policy_id)
        )
        assert accepted["normalized_rate"] == "9.605"
        resolved = repository.resolve_rate(
            tenant_id=TENANT_ID,
            company_id=COMPANY_ID,
            purpose="TRANSACTION_SPOT",
            base_currency="JPY",
            quote_currency="KRW",
            desired_rate_date=date(2026, 11, 9),
        )
        assert resolved["source_sha256"] == SOURCE_HASH
        with (
            psycopg.connect(psycopg_database_url(scoped_url)) as connection,
            connection.cursor() as cursor,
        ):
            with pytest.raises(psycopg.errors.CheckViolation):
                cursor.execute(
                    """
                    INSERT INTO eos_fx_rate_snapshot (
                        tenant_id, company_id, rate_snapshot_id,
                        source_provider_id, rate_policy_id, rate_policy_version,
                        base_currency, quote_currency, quote_unit,
                        published_rate, normalized_rate, desired_rate_date,
                        rate_date, rate_as_of, published_at, publication_issue,
                        is_final, effective_business_date, source_record_id,
                        source_uri, source_sha256, calendar_ref,
                        source_timezone, provenance_json, snapshot_hash,
                        imported_at, approved_state
                    )
                    SELECT
                        tenant_id, company_id, %s, source_provider_id,
                        rate_policy_id, rate_policy_version, base_currency,
                        quote_currency, quote_unit, published_rate, 1,
                        desired_rate_date, rate_date, rate_as_of, published_at,
                        publication_issue, is_final, effective_business_date,
                        %s, source_uri, source_sha256, calendar_ref,
                        source_timezone, provenance_json, %s, imported_at,
                        approved_state
                    FROM eos_fx_rate_snapshot
                    WHERE tenant_id = %s
                    """,
                    (
                        str(uuid.uuid4()),
                        "smbs:bad-normalization",
                        "sha256:" + "d" * 64,
                        TENANT_ID,
                    ),
                )
            connection.rollback()
            with pytest.raises(psycopg.errors.CheckViolation):
                cursor.execute(
                    "UPDATE eos_fx_rate_snapshot SET published_rate=1 "
                    "WHERE tenant_id=%s",
                    (TENANT_ID,),
                )
            connection.rollback()
            with pytest.raises(psycopg.errors.CheckViolation):
                cursor.execute(
                    "DELETE FROM eos_fx_rate_policy WHERE tenant_id=%s",
                    (TENANT_ID,),
                )
        db.dispose()
    finally:
        with (
            psycopg.connect(psycopg_url, autocommit=True) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name))
            )
            cursor.execute(
                "SELECT count(*) FROM information_schema.schemata WHERE schema_name=%s",
                (schema_name,),
            )
            assert cursor.fetchone()[0] == 0
