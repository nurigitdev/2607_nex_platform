from __future__ import annotations

import os
import uuid
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest
import test_nex_eos_mybee_voucher_candidate as posting_fixture
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nex_eos import (
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_COST_SOURCE_POOL_TABLE,
    EOS_PROJECT_COMPANY_BINDING_TABLE,
    CostSourceFacts,
    EosCostSourcePoolError,
    EosCostSourcePoolService,
    SqlAlchemyEosCostSourceFactsSource,
    SqlAlchemyEosCostSourcePoolRepository,
    cost_source_pool_api,
    cost_source_pools,
)
from nex_eos.cost_source_pool_api import register_cost_source_pool_routes
from nex_runtime import psycopg_database_url
from psycopg import sql
from run_migrations import load_migrations, run_service_migrations
from sqlalchemy import create_engine, func, make_url, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

TENANT = "VO00"
COMPANY_ID = "71000000-0000-4000-8000-000000000001"
JOURNAL_ID = "71000000-0000-4000-8000-000000000002"
OPERATION_ID = "71000000-0000-4000-8000-000000000003"
PROJECT_ID = "71000000-0000-4000-8000-000000000004"
PROJECT_CODE = "VO00D260001"
ACCOUNT_ID = "71000000-0000-4000-8000-000000000005"
PERIOD_ID = "71000000-0000-4000-8000-000000000006"
NOW = datetime(2026, 11, 13, 1, 0, tzinfo=UTC)
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64
HASH_D = "sha256:" + "d" * 64
HASH_E = "sha256:" + "e" * 64
DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
POSTGRES_SMOKE = os.getenv("NEX_EOS_MYBEE_S6_01_POSTGRES_SMOKE") == "1"


class StaticSource:
    def __init__(self, facts: CostSourceFacts | None) -> None:
        self.facts = facts

    def load(self, **_identity):
        return self.facts


def _facts(**overrides) -> CostSourceFacts:
    value = CostSourceFacts(
        tenant_id=TENANT,
        company_id=COMPANY_ID,
        journal_id=JOURNAL_ID,
        journal_line_no=1,
        business_operation_id=OPERATION_ID,
        journal_hash=HASH_A,
        journal_state="POSTED",
        recognition_date=date(2026, 11, 13),
        period_id=PERIOD_ID,
        posted_at=NOW,
        account_id=ACCOUNT_ID,
        account_category="EXPENSE",
        is_monetary=False,
        account_policy_release_hash=HASH_B,
        posting_rule_release_hash=HASH_C,
        project_id=PROJECT_ID,
        project_code=PROJECT_CODE,
        project_status="ACTIVE",
        project_company_binding_hash=HASH_D,
        debit_functional=Decimal("13502000.0000"),
        credit_functional=Decimal("0.0000"),
        functional_currency="KRW",
        source_record_ref="voucher:golden-a:line:1",
        evidence_hash=HASH_E,
        line_hash=HASH_B,
    )
    return replace(value, **overrides)


def _repository():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_COST_SOURCE_POOL_TABLE.create(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return engine, sessions, SqlAlchemyEosCostSourcePoolRepository(sessions)


def _payload(
    *, source_kind: str = "SERVICE", allocation_mode: str = "MANAGEMENT_ALLOCATION"
):
    return {
        "schema_version": "eos_cost_source_pool_admit.v1",
        "source_kind": source_kind,
        "allocation_mode": allocation_mode,
    }


def _service(facts: CostSourceFacts | None = None):
    engine, sessions, repository = _repository()
    return (
        engine,
        sessions,
        EosCostSourcePoolService(
            source=StaticSource(_facts() if facts is None else facts),
            repository=repository,
            clock=lambda: NOW,
        ),
    )


def test_s6_01_migration_contract_and_openapi_are_additive() -> None:
    migration = next(
        item
        for item in load_migrations("nex-eos")
        if item.version == "2541_eos_cost_source_allocation"
    )
    compact = " ".join(migration.sql.lower().split())
    for table_name in (
        "eos_cost_source_pool",
        "eos_cost_allocation_plan",
        "eos_cost_allocation_plan_line",
        "eos_cost_allocation_batch",
        "eos_cost_allocation_line",
        "eos_cost_allocation_adjustment",
    ):
        assert f"create table if not exists {table_name}" in compact
    assert "eligible_amount_functional = source_amount_functional" in compact
    assert "ux_eos_cost_pool_source" in compact
    assert all(
        constraint.name is None or len(constraint.name) <= 63
        for constraint in EOS_COST_SOURCE_POOL_TABLE.constraints
    )

    spec = yaml.safe_load(
        Path("contracts/openapi/nex-eos.openapi.yaml").read_text(encoding="utf-8")
    )
    route = spec["paths"][
        "/internal/v2/finance/journals/{journal_id}/lines/"
        "{journal_line_no}/cost-source-pool"
    ]["post"]
    assert route["operationId"] == "FINANCE.COST_SOURCE_POOL.ADMIT"
    assert route["x-nex-business-scope"] == "finance:cost-allocation:write"


def test_expense_management_source_is_created_replayed_and_read() -> None:
    engine, sessions, service = _service()
    created = service.admit(
        tenant_id=TENANT,
        company_id=COMPANY_ID,
        journal_id=JOURNAL_ID,
        journal_line_no=1,
        payload=_payload(),
    )
    replay = service.admit(
        tenant_id=TENANT,
        company_id=COMPANY_ID,
        journal_id=JOURNAL_ID,
        journal_line_no=1,
        payload=_payload(),
    )
    loaded = service.get(
        tenant_id=TENANT,
        company_id=COMPANY_ID,
        pool_id=created["pool_id"],
    )

    assert created["idempotency_disposition"] == "CREATED"
    assert replay["idempotency_disposition"] == "EXACT_REPLAY"
    assert replay["pool_id"] == created["pool_id"]
    assert loaded["operation"] == "FINANCE.COST_SOURCE_POOL.GET"
    assert created["pool_state"] == "OPEN"
    assert created["source_amount_functional"] == "13502000.0000"
    assert created["eligible_amount_functional"] == "13502000.0000"
    assert created["eligible_component_id"] == f"ACCOUNT:{ACCOUNT_ID}"
    with sessions() as session:
        assert (
            session.execute(
                select(func.count()).select_from(EOS_COST_SOURCE_POOL_TABLE)
            ).scalar_one()
            == 1
        )
    engine.dispose()


def test_direct_revenue_and_fx_sources_preserve_booked_functional_direction() -> None:
    revenue = _facts(
        account_category="REVENUE",
        is_monetary=True,
        debit_functional=Decimal("0.0000"),
        credit_functional=Decimal("91.2500"),
    )
    engine, _sessions, service = _service(revenue)
    direct = service.admit(
        tenant_id=TENANT,
        company_id=COMPANY_ID,
        journal_id=JOURNAL_ID,
        journal_line_no=1,
        payload=_payload(source_kind="REVENUE", allocation_mode="DIRECT"),
    )
    assert direct["source_amount_functional"] == "91.2500"
    assert direct["pool_state"] == "ALLOCATED"
    assert direct["monetary_class"] == "MONETARY"
    engine.dispose()

    fx = replace(
        revenue,
        debit_functional=Decimal("20.0000"),
        credit_functional=Decimal("0.0000"),
    )
    engine, _sessions, service = _service(fx)
    loss = service.admit(
        tenant_id=TENANT,
        company_id=COMPANY_ID,
        journal_id=JOURNAL_ID,
        journal_line_no=1,
        payload=_payload(source_kind="FX_GAIN_LOSS"),
    )
    assert loss["source_amount_functional"] == "-20.0000"
    engine.dispose()


@pytest.mark.parametrize(
    ("facts", "source_kind", "detail"),
    (
        (_facts(account_category="ASSET"), "SERVICE", "Cash, liability"),
        (_facts(account_category="LIABILITY"), "PAYROLL", "Cash, liability"),
        (_facts(account_category="REVENUE"), "SERVICE", "EXPENSE account"),
        (_facts(account_category="EXPENSE"), "REVENUE", "REVENUE account"),
        (_facts(project_status="INACTIVE"), "SERVICE", "Project is not active"),
        (
            _facts(debit_functional=Decimal(0), credit_functional=Decimal(0)),
            "SERVICE",
            "Zero-value",
        ),
        (_facts(journal_state="DRAFT"), "SERVICE", "not POSTED"),
    ),
)
def test_ineligible_source_categories_and_states_fail_closed(
    facts: CostSourceFacts, source_kind: str, detail: str
) -> None:
    engine, _sessions, service = _service(facts)
    with pytest.raises(EosCostSourcePoolError, match=detail) as rejected:
        service.admit(
            tenant_id=TENANT,
            company_id=COMPANY_ID,
            journal_id=JOURNAL_ID,
            journal_line_no=1,
            payload=_payload(source_kind=source_kind),
        )
    assert rejected.value.error_code == "EOS_COST_SOURCE_INELIGIBLE"
    engine.dispose()


def test_source_identity_rejects_changed_mode_and_invalid_contracts() -> None:
    engine, _sessions, service = _service()
    service.admit(
        tenant_id=TENANT,
        company_id=COMPANY_ID,
        journal_id=JOURNAL_ID,
        journal_line_no=1,
        payload=_payload(),
    )
    with pytest.raises(EosCostSourcePoolError) as conflict:
        service.admit(
            tenant_id=TENANT,
            company_id=COMPANY_ID,
            journal_id=JOURNAL_ID,
            journal_line_no=1,
            payload=_payload(allocation_mode="DIRECT"),
        )
    assert conflict.value.error_code == "EOS_COST_SOURCE_POOL_CONFLICT"

    for payload in (
        {"schema_version": "wrong", "source_kind": "SERVICE", "allocation_mode": "DIRECT"},
        {**_payload(), "amount": "1.0000"},
        _payload(allocation_mode="GL_COST_TRANSFER"),
        _payload(source_kind="CASH"),
    ):
        with pytest.raises(EosCostSourcePoolError) as invalid:
            service.admit(
                tenant_id=TENANT,
                company_id=COMPANY_ID,
                journal_id=JOURNAL_ID,
                journal_line_no=1,
                payload=payload,
            )
        assert invalid.value.status_code == 422
    engine.dispose()


def test_missing_source_and_pool_are_tenant_scoped() -> None:
    engine, _sessions, repository = _repository()
    service = EosCostSourcePoolService(
        source=StaticSource(None), repository=repository, clock=lambda: NOW
    )
    with pytest.raises(EosCostSourcePoolError) as missing_source:
        service.admit(
            tenant_id=TENANT,
            company_id=COMPANY_ID,
            journal_id=JOURNAL_ID,
            journal_line_no=1,
            payload=_payload(),
        )
    assert missing_source.value.status_code == 404
    with pytest.raises(EosCostSourcePoolError) as missing_pool:
        service.get(
            tenant_id=TENANT,
            company_id=COMPANY_ID,
            pool_id=str(uuid.uuid4()),
        )
    assert missing_pool.value.error_code == "EOS_COST_SOURCE_POOL_NOT_FOUND"
    engine.dispose()


def _sqlite_posted_source_runtime():
    engine, sessions, candidates, command, _authorization = posting_fixture._runtime()
    with sessions.begin() as session:
        session.execute(
            EOS_PROJECT_COMPANY_BINDING_TABLE.insert().values(
                tenant_id=posting_fixture.TENANT,
                binding_id=str(uuid.uuid4()),
                project_id=posting_fixture.PROJECT_ID,
                company_id=posting_fixture.COMPANY_ID,
                valid_from=date(2026, 1, 1),
                valid_until=None,
                approved_proof_hash=posting_fixture.PROOF_HASH,
                state="APPROVED",
                version=1,
                created_at=posting_fixture.NOW,
                updated_at=posting_fixture.NOW,
            )
        )
    command.execute(posting_fixture._payload(), caller=posting_fixture.CALLER)
    posting, payload = posting_fixture._prepare_atomic_posting(sessions, candidates)
    committed = posting.execute(posting_fixture.CANDIDATE_ID, payload)
    return engine, sessions, payload, committed


def test_sqlalchemy_source_loads_only_verified_effective_journal_facts() -> None:
    engine, sessions, _payload_value, committed = _sqlite_posted_source_runtime()
    source = SqlAlchemyEosCostSourceFactsSource(sessions)
    identity = {
        "tenant_id": posting_fixture.TENANT,
        "company_id": posting_fixture.COMPANY_ID,
        "journal_id": committed["result"]["journal_id"],
    }
    facts = source.load(**identity, journal_line_no=1)
    assert facts is not None
    assert facts.account_category == "EXPENSE"
    assert facts.project_company_binding_hash == posting_fixture.PROOF_HASH
    assert facts.debit_functional == Decimal("10000.0000")
    assert source.load(**identity, journal_line_no=99) is None
    assert source.load(
        tenant_id=posting_fixture.TENANT,
        company_id=posting_fixture.COMPANY_ID,
        journal_id=str(uuid.uuid4()),
        journal_line_no=1,
    ) is None
    engine.dispose()


def test_sqlalchemy_source_rejects_unverified_journal_and_maps_operation_errors() -> None:
    engine, sessions, payload, committed = _sqlite_posted_source_runtime()
    source = SqlAlchemyEosCostSourceFactsSource(sessions)
    identity = {
        "tenant_id": posting_fixture.TENANT,
        "company_id": posting_fixture.COMPANY_ID,
        "journal_id": committed["result"]["journal_id"],
        "journal_line_no": 1,
    }
    with sessions.begin() as session:
        session.execute(
            update(EOS_BUSINESS_OPERATION_TABLE)
            .where(
                EOS_BUSINESS_OPERATION_TABLE.c.tenant_id == posting_fixture.TENANT,
                EOS_BUSINESS_OPERATION_TABLE.c.business_operation_id
                == payload["business_operation_id"],
            )
            .values(commit_state="PENDING")
        )
    with pytest.raises(EosCostSourcePoolError) as unverified:
        source.load(**identity)
    assert unverified.value.error_code == "EOS_COST_SOURCE_JOURNAL_UNVERIFIED"

    class FailedOperation:
        def __init__(self, status_code: int) -> None:
            self.status_code = status_code

        def reconcile(self, **_identity):
            raise cost_source_pools.EosJournalOperationError(
                "BROKEN_RECONCILIATION",
                "reconciliation failed",
                status_code=self.status_code,
                retryable=self.status_code >= 500,
            )

    for status_code, expected in ((409, 409), (503, 503)):
        source._operations = FailedOperation(status_code)
        with pytest.raises(EosCostSourcePoolError) as mapped:
            source.load(**identity)
        assert mapped.value.status_code == expected
    engine.dispose()


class _BrokenContext:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, _statement):
        raise SQLAlchemyError("database unavailable")


class _BrokenFactory:
    def __call__(self):
        return _BrokenContext()

    def begin(self):
        return _BrokenContext()


def test_source_and_repository_translate_persistence_failures() -> None:
    source = SqlAlchemyEosCostSourceFactsSource(_BrokenFactory())
    with pytest.raises(EosCostSourcePoolError) as source_failure:
        source.load(
            tenant_id=TENANT,
            company_id=COMPANY_ID,
            journal_id=JOURNAL_ID,
            journal_line_no=1,
        )
    assert source_failure.value.retryable is True

    repository = SqlAlchemyEosCostSourcePoolRepository(_BrokenFactory())
    record = cost_source_pools._build_pool_record(
        _facts(),
        source_kind="SERVICE",
        allocation_mode="MANAGEMENT_ALLOCATION",
        created_at=NOW,
    )
    with pytest.raises(EosCostSourcePoolError) as get_failure:
        repository.get(tenant_id=TENANT, company_id=COMPANY_ID, pool_id=JOURNAL_ID)
    assert get_failure.value.error_code == "EOS_COST_SOURCE_POOL_UNAVAILABLE"
    with pytest.raises(EosCostSourcePoolError) as create_failure:
        repository.create_or_replay(record)
    assert create_failure.value.retryable is True
    with pytest.raises(EosCostSourcePoolError):
        repository._replay_after_race(record)


def test_repository_integrity_race_resolves_to_exact_replay() -> None:
    engine, sessions, service = _service()
    created = service.admit(
        tenant_id=TENANT,
        company_id=COMPANY_ID,
        journal_id=JOURNAL_ID,
        journal_line_no=1,
        payload=_payload(),
    )
    with sessions() as session:
        record = dict(
            session.execute(
                select(EOS_COST_SOURCE_POOL_TABLE).where(
                    EOS_COST_SOURCE_POOL_TABLE.c.pool_id == created["pool_id"]
                )
            )
            .mappings()
            .one()
        )

    class EmptyResult:
        def mappings(self):
            return self

        def one_or_none(self):
            return None

    class RaceSession:
        def execute(self, statement):
            if statement.is_select:
                return EmptyResult()
            raise IntegrityError("insert", {}, RuntimeError("duplicate"))

    class RaceContext:
        def __enter__(self):
            return RaceSession()

        def __exit__(self, *_args):
            return False

    class RaceFactory:
        def begin(self):
            return RaceContext()

        def __call__(self):
            return sessions()

    replay, was_created = SqlAlchemyEosCostSourcePoolRepository(
        RaceFactory()
    ).create_or_replay(record)
    assert was_created is False
    assert replay["pool_id"] == created["pool_id"]

    empty_engine, _empty_sessions, empty_repository = _repository()
    with pytest.raises(EosCostSourcePoolError) as vanished:
        empty_repository._replay_after_race(record)
    assert vanished.value.retryable is True
    empty_engine.dispose()
    engine.dispose()


def test_validation_and_timestamp_guards_are_fail_closed() -> None:
    engine, _sessions, service = _service()
    bad_calls = (
        {"tenant_id": "bad tenant", "company_id": COMPANY_ID, "journal_line_no": 1},
        {"tenant_id": TENANT, "company_id": "not-a-uuid", "journal_line_no": 1},
        {"tenant_id": TENANT, "company_id": COMPANY_ID, "journal_line_no": 0},
        {"tenant_id": TENANT, "company_id": COMPANY_ID, "journal_line_no": True},
    )
    for values in bad_calls:
        with pytest.raises(EosCostSourcePoolError):
            service.admit(
                tenant_id=values["tenant_id"],
                company_id=values["company_id"],
                journal_id=JOURNAL_ID,
                journal_line_no=values["journal_line_no"],
                payload=_payload(),
            )
    for value in ("not-a-number", Decimal("NaN"), Decimal("1.00001")):
        with pytest.raises(EosCostSourcePoolError):
            cost_source_pools._decimal_amount("amount", value)
    with pytest.raises(EosCostSourcePoolError):
        cost_source_pools._wire_time("not-a-time")

    second_engine, _, repository = _repository()
    naive_clock_service = EosCostSourcePoolService(
        source=StaticSource(_facts()),
        repository=repository,
        clock=lambda: datetime(2026, 11, 13, 1, 0),  # noqa: DTZ001
    )
    with pytest.raises(EosCostSourcePoolError):
        naive_clock_service.admit(
            tenant_id=TENANT,
            company_id=COMPANY_ID,
            journal_id=JOURNAL_ID,
            journal_line_no=1,
            payload=_payload(),
        )
    second_engine.dispose()
    engine.dispose()


def test_cost_source_pool_api_created_replay_get_and_fail_closed(monkeypatch) -> None:
    monkeypatch.setattr(
        cost_source_pool_api,
        "admit_service_token_from_request",
        lambda *_args, **_kwargs: SimpleNamespace(
            subject="nex-ae-api", audience="nex-eos", scopes=("service:call",)
        ),
    )
    engine, _sessions, service = _service()
    app = FastAPI()
    register_cost_source_pool_routes(app)
    headers = {
        "Authorization": "Bearer service-token",
        "X-NeX-Tenant-Id": TENANT,
        "X-NeX-Company-Id": COMPANY_ID,
    }
    path = f"/internal/v2/finance/journals/{JOURNAL_ID}/lines/1/cost-source-pool"
    with TestClient(app) as client:
        unavailable = client.post(path, json=_payload(), headers=headers)
        unavailable_get = client.get(
            f"/internal/v2/finance/cost-source-pools/{uuid.uuid4()}",
            headers=headers,
        )
        app.state.eos_cost_source_pool_service = service
        created = client.post(path, json=_payload(), headers=headers)
        replay = client.post(path, json=_payload(), headers=headers)
        conflict = client.post(
            path,
            json=_payload(allocation_mode="DIRECT"),
            headers=headers,
        )
        loaded = client.get(
            f"/internal/v2/finance/cost-source-pools/{created.json()['pool_id']}",
            headers=headers,
        )
        missing = client.get(
            f"/internal/v2/finance/cost-source-pools/{uuid.uuid4()}",
            headers=headers,
        )
    assert unavailable.status_code == 503
    assert unavailable_get.status_code == 503
    assert created.status_code == 201
    assert replay.status_code == 200
    assert conflict.status_code == 409
    assert loaded.status_code == 200
    assert missing.status_code == 404
    engine.dispose()


def test_cost_source_pool_api_propagates_service_token_denial(monkeypatch) -> None:
    monkeypatch.setattr(
        cost_source_pool_api,
        "admit_service_token_from_request",
        lambda *_args, **_kwargs: cost_source_pool_api.JSONResponse(
            {"error_code": "SERVICE_TOKEN_DENIED"}, status_code=403
        ),
    )
    app = FastAPI()
    register_cost_source_pool_routes(app)
    with TestClient(app) as client:
        response = client.post(
            f"/internal/v2/finance/journals/{JOURNAL_ID}/lines/1/cost-source-pool",
            json=_payload(),
            headers={"X-NeX-Tenant-Id": TENANT, "X-NeX-Company-Id": COMPANY_ID},
        )
        denied_get = client.get(
            f"/internal/v2/finance/cost-source-pools/{uuid.uuid4()}",
            headers={"X-NeX-Tenant-Id": TENANT, "X-NeX-Company-Id": COMPANY_ID},
        )
    assert response.status_code == 403
    assert denied_get.status_code == 403


@pytest.mark.skipif(
    not DATABASE_URL or not POSTGRES_SMOKE,
    reason="Protected S6-01 EOS PostgreSQL smoke is disabled",
)
def test_actual_postgres_posted_gl_source_pool_admission(monkeypatch) -> None:
    schema_name = f"mybee_s601_{uuid.uuid4().hex}"
    psycopg_url = psycopg_database_url(DATABASE_URL)
    with psycopg.connect(psycopg_url, autocommit=True) as connection:
        assert connection.execute(
            "SELECT current_database(), current_user"
        ).fetchone() == ("nex_eos_test", "nex_eos_user")
        connection.execute(
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name))
        )
    scoped_url = (
        make_url(DATABASE_URL)
        .update_query_dict({"options": f"-csearch_path={schema_name}"})
        .render_as_string(hide_password=False)
    )
    engine = None
    try:
        migration = run_service_migrations(
            "nex-eos", database_url=scoped_url, profile="test"
        )
        assert "2541_eos_cost_source_allocation" in migration.applied
        engine = create_engine(scoped_url, pool_pre_ping=True)
        _engine, sessions, candidates, command, _authorization = (
            posting_fixture._runtime(engine=engine)
        )
        with sessions.begin() as session:
            session.execute(
                EOS_PROJECT_COMPANY_BINDING_TABLE.insert().values(
                    tenant_id=posting_fixture.TENANT,
                    binding_id=str(uuid.uuid4()),
                    project_id=posting_fixture.PROJECT_ID,
                    company_id=posting_fixture.COMPANY_ID,
                    valid_from=date(2026, 1, 1),
                    valid_until=None,
                    approved_proof_hash=posting_fixture.PROOF_HASH,
                    state="APPROVED",
                    version=1,
                    created_at=posting_fixture.NOW,
                    updated_at=posting_fixture.NOW,
                )
            )
        command.execute(posting_fixture._payload(), caller=posting_fixture.CALLER)
        posting, post_payload = posting_fixture._prepare_atomic_posting(
            sessions, candidates
        )
        committed = posting.execute(posting_fixture.CANDIDATE_ID, post_payload)
        service = EosCostSourcePoolService(
            source=SqlAlchemyEosCostSourceFactsSource(sessions),
            repository=SqlAlchemyEosCostSourcePoolRepository(sessions),
            clock=lambda: posting_fixture.NOW,
        )
        monkeypatch.setattr(
            cost_source_pool_api,
            "admit_service_token_from_request",
            lambda *_args, **_kwargs: SimpleNamespace(
                subject="nex-ae-api",
                audience="nex-eos",
                scopes=("service:call",),
            ),
        )
        app = FastAPI()
        register_cost_source_pool_routes(app)
        app.state.eos_cost_source_pool_service = service
        journal_id = committed["result"]["journal_id"]
        headers = {
            "Authorization": "Bearer signed-service-token",
            "X-NeX-Tenant-Id": posting_fixture.TENANT,
            "X-NeX-Company-Id": posting_fixture.COMPANY_ID,
        }
        with TestClient(app) as client:
            created = client.post(
                f"/internal/v2/finance/journals/{journal_id}/lines/1/cost-source-pool",
                headers=headers,
                json=_payload(),
            )
            replay = client.post(
                f"/internal/v2/finance/journals/{journal_id}/lines/1/cost-source-pool",
                headers=headers,
                json=_payload(),
            )
            ineligible = client.post(
                f"/internal/v2/finance/journals/{journal_id}/lines/2/cost-source-pool",
                headers=headers,
                json=_payload(),
            )
        assert created.status_code == 201, created.text
        assert replay.status_code == 200, replay.text
        assert replay.json()["pool_id"] == created.json()["pool_id"]
        assert ineligible.status_code == 409, ineligible.text
        assert ineligible.json()["error_code"] == "EOS_COST_SOURCE_INELIGIBLE"
        with sessions() as session:
            assert (
                session.execute(
                    select(func.count()).select_from(EOS_COST_SOURCE_POOL_TABLE)
                ).scalar_one()
                == 1
            )
        engine.dispose()
        engine = None
    finally:
        if engine is not None:
            engine.dispose()
        with psycopg.connect(psycopg_url, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema_name)
                )
            )
            assert connection.execute(
                "SELECT to_regnamespace(%s)", (schema_name,)
            ).fetchone() == (None,)
