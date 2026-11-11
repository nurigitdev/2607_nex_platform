from __future__ import annotations

import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date
from threading import Barrier, Event

import psycopg
import pytest
from fastapi.testclient import TestClient
from nex_eos import (
    EOS_ACCOUNTING_PERIOD_TABLE,
    EOS_LEGAL_ENTITY_TABLE,
    EOS_METADATA,
    AccountingPeriodInput,
    EosAccountingPeriodError,
    EosAccountingPeriodService,
    LegalEntityInput,
    SqlAlchemyEosAccountingPeriodRepository,
    SqlAlchemyEosLegalEntityRepository,
    build_eos_database_runtime,
    create_eos_app,
)
from nex_eos.authorization import AuthorizationSubjectDenied
from nex_runtime import issue_mock_service_token, psycopg_database_url
from psycopg import sql
from run_migrations import run_service_migrations
from sqlalchemy import create_engine, make_url, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
POSTGRES_SMOKE = os.getenv("NEX_EOS_MYBEE_S1_03_POSTGRES_SMOKE") == "1"

TENANT_ID = "tenant-a"
SUBJECT_ID = "finance-period-owner"
COMPANY_ID = "e1000000-0000-4000-8000-000000000001"
PERIOD_ID = "e2000000-0000-4000-8000-000000000001"
SECOND_PERIOD_ID = "e2000000-0000-4000-8000-000000000002"
PROOF = "sha256:" + "a" * 64


class AuthorizationSource:
    def __init__(self) -> None:
        self.value: object = {
            "active": True,
            "tenant_id": TENANT_ID,
            "subject_id": SUBJECT_ID,
            "scopes": ["finance:period:read", "finance:period:close"],
            "revision_hash": "b" * 64,
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
    repository = SqlAlchemyEosAccountingPeriodRepository(factory)
    auth = AuthorizationSource()
    service = EosAccountingPeriodService(repository, auth)
    yield engine, factory, repository, auth, service
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


def _period(
    period_id: str = PERIOD_ID,
    *,
    period_no: int = 1,
    start_date: date = date(2026, 1, 1),
    end_date: date = date(2026, 1, 31),
) -> AccountingPeriodInput:
    return AccountingPeriodInput(
        tenant_id=TENANT_ID,
        company_id=COMPANY_ID,
        period_id=period_id,
        fiscal_year=2026,
        period_no=period_no,
        start_date=start_date,
        end_date=end_date,
    )


def test_create_get_exact_replay_overlap_and_company_guards(runtime) -> None:
    _engine, factory, repository, _auth, _service = runtime
    created = repository.create_open_period(_period())
    replay = repository.create_open_period(_period())
    assert created == replay
    assert created["state"] == "OPEN"
    assert created["version"] == 1
    assert (
        repository.get_period(
            tenant_id=TENANT_ID,
            company_id=COMPANY_ID,
            period_id=PERIOD_ID,
        )
        == created
    )
    assert (
        repository.get_period(
            tenant_id=TENANT_ID,
            company_id=COMPANY_ID,
            period_id=str(uuid.uuid4()),
        )
        is None
    )

    with pytest.raises(EosAccountingPeriodError, match="different semantics"):
        repository.create_open_period(replace(_period(), period_no=2))
    with pytest.raises(EosAccountingPeriodError, match="overlaps"):
        repository.create_open_period(
            _period(
                SECOND_PERIOD_ID,
                period_no=2,
                start_date=date(2026, 1, 15),
                end_date=date(2026, 2, 15),
            )
        )
    with pytest.raises(EosAccountingPeriodError, match="identity or range guard"):
        repository.create_open_period(
            _period(
                str(uuid.uuid4()),
                period_no=1,
                start_date=date(2026, 2, 1),
                end_date=date(2026, 2, 28),
            )
        )
    with pytest.raises(EosAccountingPeriodError, match="LegalEntity"):
        repository.create_open_period(
            replace(
                _period(
                    str(uuid.uuid4()),
                    period_no=3,
                    start_date=date(2026, 3, 1),
                    end_date=date(2026, 3, 31),
                ),
                company_id=str(uuid.uuid4()),
            )
        )
    with factory.begin() as session:
        session.execute(
            EOS_LEGAL_ENTITY_TABLE.update()
            .where(EOS_LEGAL_ENTITY_TABLE.c.company_id == COMPANY_ID)
            .values(status="INACTIVE")
        )
    with pytest.raises(EosAccountingPeriodError, match="not active"):
        repository.create_open_period(
            _period(
                SECOND_PERIOD_ID,
                period_no=2,
                start_date=date(2026, 2, 1),
                end_date=date(2026, 2, 28),
            )
        )


def test_close_state_machine_and_posting_admission_are_fail_closed(runtime) -> None:
    _engine, factory, repository, _auth, _service = runtime
    repository.create_open_period(_period())
    with factory.begin() as session:
        admitted = repository.lock_open_for_post(
            session,
            tenant_id=TENANT_ID,
            company_id=COMPANY_ID,
            posting_date=date(2026, 1, 31),
        )
    assert admitted["period_id"] == PERIOD_ID

    with pytest.raises(EosAccountingPeriodError, match="must enter CLOSING"):
        repository.advance_close(
            tenant_id=TENANT_ID,
            company_id=COMPANY_ID,
            period_id=PERIOD_ID,
            expected_version=1,
            close_proof_ref=PROOF,
            ledger_cutoff_watermark="journal:100",
        )
    closing = repository.advance_close(
        tenant_id=TENANT_ID,
        company_id=COMPANY_ID,
        period_id=PERIOD_ID,
        expected_version=1,
    )
    assert (closing["state"], closing["version"]) == ("CLOSING", 2)
    assert (
        repository.advance_close(
            tenant_id=TENANT_ID,
            company_id=COMPANY_ID,
            period_id=PERIOD_ID,
            expected_version=1,
        )
        == closing
    )

    with (
        factory.begin() as session,
        pytest.raises(EosAccountingPeriodError) as not_open,
    ):
        repository.lock_open_for_post(
            session,
            tenant_id=TENANT_ID,
            company_id=COMPANY_ID,
            posting_date=date(2026, 1, 15),
        )
    assert not_open.value.error_code == "EOS_ACCOUNTING_PERIOD_NOT_OPEN"
    with pytest.raises(EosAccountingPeriodError, match="supplied together"):
        repository.advance_close(
            tenant_id=TENANT_ID,
            company_id=COMPANY_ID,
            period_id=PERIOD_ID,
            expected_version=2,
            close_proof_ref=PROOF,
        )
    with pytest.raises(EosAccountingPeriodError, match="version changed"):
        repository.advance_close(
            tenant_id=TENANT_ID,
            company_id=COMPANY_ID,
            period_id=PERIOD_ID,
            expected_version=1,
            close_proof_ref=PROOF,
            ledger_cutoff_watermark="journal:100",
        )
    closed = repository.advance_close(
        tenant_id=TENANT_ID,
        company_id=COMPANY_ID,
        period_id=PERIOD_ID,
        expected_version=2,
        close_proof_ref=PROOF,
        ledger_cutoff_watermark="journal:100",
    )
    assert (closed["state"], closed["version"]) == ("CLOSED", 3)
    assert closed["closed_at"] is not None
    assert (
        repository.advance_close(
            tenant_id=TENANT_ID,
            company_id=COMPANY_ID,
            period_id=PERIOD_ID,
            expected_version=2,
            close_proof_ref=PROOF,
            ledger_cutoff_watermark="journal:100",
        )
        == closed
    )
    with pytest.raises(EosAccountingPeriodError, match="cannot be reopened"):
        repository.advance_close(
            tenant_id=TENANT_ID,
            company_id=COMPANY_ID,
            period_id=PERIOD_ID,
            expected_version=3,
        )


def test_period_lock_rejects_corrupt_ambiguity_and_lock_scope_is_dialect_aware(
    runtime,
) -> None:
    _engine, factory, repository, _auth, _service = runtime
    repository.create_open_period(_period())
    with factory.begin() as session:
        first = (
            session.execute(
                select(EOS_ACCOUNTING_PERIOD_TABLE).where(
                    EOS_ACCOUNTING_PERIOD_TABLE.c.period_id == PERIOD_ID
                )
            )
            .mappings()
            .one()
        )
        session.execute(
            EOS_ACCOUNTING_PERIOD_TABLE.insert().values(
                **{
                    **first,
                    "period_id": SECOND_PERIOD_ID,
                    "period_no": 2,
                }
            )
        )
    with (
        factory.begin() as session,
        pytest.raises(EosAccountingPeriodError, match="ambiguous"),
    ):
        repository.lock_open_for_post(
            session,
            tenant_id=TENANT_ID,
            company_id=COMPANY_ID,
            posting_date=date(2026, 1, 15),
        )

    class Dialect:
        name = "postgresql"

    class Bind:
        dialect = Dialect()

    class FakeSession:
        bind = Bind()

        def __init__(self) -> None:
            self.executed = False

        def execute(self, statement, parameters):
            self.executed = "pg_advisory_xact_lock" in str(statement)
            assert parameters == {"scope": f"{TENANT_ID}:{COMPANY_ID}"}

    fake = FakeSession()
    repository._lock_company_scope(
        fake, tenant_id=TENANT_ID, company_id=COMPANY_ID  # type: ignore[arg-type]
    )
    assert fake.executed is True

    class UnboundSession:
        bind = None

    repository._lock_company_scope(
        UnboundSession(), tenant_id=TENANT_ID, company_id=COMPANY_ID  # type: ignore[arg-type]
    )


def test_close_state_transition_rejects_every_stale_or_unknown_variant() -> None:
    next_state = SqlAlchemyEosAccountingPeriodRepository._next_close_state
    with pytest.raises(EosAccountingPeriodError, match="version changed"):
        next_state(
            {"state": "OPEN", "version": 2},
            expected_version=1,
            close_proof_ref=None,
            ledger_cutoff_watermark=None,
        )
    with pytest.raises(EosAccountingPeriodError, match="version changed"):
        next_state(
            {"state": "CLOSING", "version": 2},
            expected_version=99,
            close_proof_ref=None,
            ledger_cutoff_watermark=None,
        )
    with pytest.raises(EosAccountingPeriodError, match="cannot be reopened"):
        next_state(
            {
                "state": "CLOSED",
                "version": 3,
                "close_proof_ref": PROOF,
                "ledger_cutoff_watermark": "journal:100",
            },
            expected_version=1,
            close_proof_ref=PROOF,
            ledger_cutoff_watermark="journal:100",
        )
    with pytest.raises(EosAccountingPeriodError, match="cannot be reopened"):
        next_state(
            {"state": "CORRUPT", "version": 1},
            expected_version=1,
            close_proof_ref=None,
            ledger_cutoff_watermark=None,
        )


def test_missing_period_and_input_validation_are_typed(runtime) -> None:
    _engine, factory, repository, _auth, _service = runtime
    invalid_values = [
        object(),
        replace(_period(), end_date=date(2025, 12, 31)),
        replace(_period(), fiscal_year=1899),
        replace(_period(), period_no=0),
        replace(_period(), company_id="bad"),
        replace(_period(), start_date="2026-01-01"),  # type: ignore[arg-type]
    ]
    for value in invalid_values:
        with pytest.raises(EosAccountingPeriodError) as exc:
            repository.create_open_period(value)  # type: ignore[arg-type]
        assert exc.value.status_code == 422

    with (
        factory.begin() as session,
        pytest.raises(EosAccountingPeriodError) as missing_date,
    ):
        repository.lock_open_for_post(
            session,
            tenant_id=TENANT_ID,
            company_id=COMPANY_ID,
            posting_date=date(2026, 3, 1),
        )
    assert missing_date.value.status_code == 404
    with pytest.raises(EosAccountingPeriodError) as missing_period:
        repository.advance_close(
            tenant_id=TENANT_ID,
            company_id=COMPANY_ID,
            period_id=str(uuid.uuid4()),
            expected_version=1,
        )
    assert missing_period.value.status_code == 404
    with pytest.raises(EosAccountingPeriodError, match="SHA-256"):
        repository.advance_close(
            tenant_id=TENANT_ID,
            company_id=COMPANY_ID,
            period_id=str(uuid.uuid4()),
            expected_version=1,
            close_proof_ref="bad",
            ledger_cutoff_watermark="journal:100",
        )
    with pytest.raises(EosAccountingPeriodError, match="1..128"):
        repository.advance_close(
            tenant_id=TENANT_ID,
            company_id=COMPANY_ID,
            period_id=str(uuid.uuid4()),
            expected_version=1,
            close_proof_ref=PROOF,
            ledger_cutoff_watermark="",
        )


def test_service_authorization_and_projection_are_tenant_scoped(runtime) -> None:
    _engine, _factory, repository, auth, service = runtime
    repository.create_open_period(_period())
    result = service.get_period(
        tenant_id=TENANT_ID,
        requester_subject_id=SUBJECT_ID,
        company_id=COMPANY_ID,
        period_id=PERIOD_ID,
    )
    assert result["period_id"] == PERIOD_ID
    closing = service.advance_close(
        tenant_id=TENANT_ID,
        requester_subject_id=SUBJECT_ID,
        period_id=PERIOD_ID,
        payload={"company_id": COMPANY_ID, "expected_version": 1},
    )
    assert closing["state"] == "CLOSING"

    auth.denied = True
    with pytest.raises(EosAccountingPeriodError) as denied:
        service.get_period(
            tenant_id=TENANT_ID,
            requester_subject_id=SUBJECT_ID,
            company_id=COMPANY_ID,
            period_id=PERIOD_ID,
        )
    assert denied.value.status_code == 403
    auth.denied = False
    auth.unavailable = True
    with pytest.raises(EosAccountingPeriodError) as unavailable:
        service.get_period(
            tenant_id=TENANT_ID,
            requester_subject_id=SUBJECT_ID,
            company_id=COMPANY_ID,
            period_id=PERIOD_ID,
        )
    assert unavailable.value.retryable is True
    auth.unavailable = False

    malformed = [
        None,
        {"active": False},
        {
            "active": True,
            "tenant_id": "wrong",
            "subject_id": SUBJECT_ID,
            "scopes": ["finance:period:read"],
            "revision_hash": "b" * 64,
        },
        {
            "active": True,
            "tenant_id": TENANT_ID,
            "subject_id": SUBJECT_ID,
            "scopes": "finance:period:read",
            "revision_hash": "b" * 64,
        },
        {
            "active": True,
            "tenant_id": TENANT_ID,
            "subject_id": SUBJECT_ID,
            "scopes": [""],
            "revision_hash": "b" * 64,
        },
        {
            "active": True,
            "tenant_id": TENANT_ID,
            "subject_id": SUBJECT_ID,
            "scopes": ["finance:period:read"],
            "revision_hash": "bad",
        },
    ]
    for value in malformed:
        auth.value = value
        with pytest.raises(EosAccountingPeriodError):
            service.get_period(
                tenant_id=TENANT_ID,
                requester_subject_id=SUBJECT_ID,
                company_id=COMPANY_ID,
                period_id=PERIOD_ID,
            )
    auth.value = {
        "active": True,
        "tenant_id": TENANT_ID,
        "subject_id": SUBJECT_ID,
        "scopes": ["finance:period:close"],
        "revision_hash": "b" * 64,
    }
    with pytest.raises(EosAccountingPeriodError) as wrong_scope:
        service.get_period(
            tenant_id=TENANT_ID,
            requester_subject_id=SUBJECT_ID,
            company_id=COMPANY_ID,
            period_id=PERIOD_ID,
        )
    assert wrong_scope.value.status_code == 403
    auth.value = {
        "active": True,
        "tenant_id": TENANT_ID,
        "subject_id": SUBJECT_ID,
        "scopes": ["finance:period:read", "finance:period:close"],
        "revision_hash": "b" * 64,
    }
    with pytest.raises(EosAccountingPeriodError) as missing:
        service.get_period(
            tenant_id=TENANT_ID,
            requester_subject_id=SUBJECT_ID,
            company_id=COMPANY_ID,
            period_id=str(uuid.uuid4()),
        )
    assert missing.value.status_code == 404
    with pytest.raises(EosAccountingPeriodError, match="payload must be an object"):
        service.advance_close(
            tenant_id=TENANT_ID,
            requester_subject_id=SUBJECT_ID,
            period_id=PERIOD_ID,
            payload=None,  # type: ignore[arg-type]
        )
    with pytest.raises(EosAccountingPeriodError, match="unsupported fields"):
        service.advance_close(
            tenant_id=TENANT_ID,
            requester_subject_id=SUBJECT_ID,
            period_id=PERIOD_ID,
            payload={
                "company_id": COMPANY_ID,
                "expected_version": 1,
                "unexpected": True,
            },
        )
    with pytest.raises(EosAccountingPeriodError, match="stable-reference"):
        service.get_period(
            tenant_id="",
            requester_subject_id=SUBJECT_ID,
            company_id=COMPANY_ID,
            period_id=PERIOD_ID,
        )


def test_persistence_failures_are_retryable_and_private() -> None:
    class BrokenFactory:
        def __call__(self):
            raise SQLAlchemyError("private database failure")

        def begin(self):
            raise SQLAlchemyError("private database failure")

    repository = SqlAlchemyEosAccountingPeriodRepository(BrokenFactory())  # type: ignore[arg-type]
    with pytest.raises(EosAccountingPeriodError) as read_error:
        repository.get_period(
            tenant_id=TENANT_ID,
            company_id=COMPANY_ID,
            period_id=PERIOD_ID,
        )
    assert read_error.value.retryable is True
    assert "private" not in read_error.value.detail
    with pytest.raises(EosAccountingPeriodError) as write_error:
        repository.create_open_period(_period())
    assert (
        write_error.value.error_code == "EOS_ACCOUNTING_PERIOD_PERSISTENCE_UNAVAILABLE"
    )
    with pytest.raises(EosAccountingPeriodError) as transition_error:
        repository.advance_close(
            tenant_id=TENANT_ID,
            company_id=COMPANY_ID,
            period_id=PERIOD_ID,
            expected_version=1,
        )
    assert transition_error.value.retryable is True


def test_signed_period_routes_require_trust_and_map_domain_errors(runtime) -> None:
    _engine, _factory, repository, auth, service = runtime
    repository.create_open_period(_period())
    app = create_eos_app(
        environ={
            "NEX_PROFILE": "test",
            "NEX_VERSION": "test",
            "NEX_BUILD_SHA": "test",
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
        }
    )
    client = TestClient(app)
    path = f"/internal/v2/finance/periods/{PERIOD_ID}"
    headers = {
        "X-NeX-Tenant-Id": TENANT_ID,
        "X-NeX-Subject-Id": SUBJECT_ID,
    }
    params = {"company_id": COMPANY_ID}
    assert client.get(path, params=params, headers=headers).status_code == 401
    token = issue_mock_service_token(service_id="nex-ae-api", audience="nex-eos")
    trusted = {**headers, "Authorization": f"Bearer {token.access_token}"}
    assert client.get(path, params=params, headers=trusted).status_code == 503
    app.state.eos_accounting_period_service = service
    assert client.get(path, params=params, headers=trusted).status_code == 200
    close = client.post(
        f"{path}:close",
        headers=trusted,
        json={"company_id": COMPANY_ID, "expected_version": 1},
    )
    assert close.status_code == 200
    assert close.json()["state"] == "CLOSING"
    malformed = client.post(
        f"{path}:close",
        headers=trusted,
        json={"company_id": "bad", "expected_version": 2},
    )
    assert malformed.status_code == 422
    auth.value = {
        "active": True,
        "tenant_id": TENANT_ID,
        "subject_id": SUBJECT_ID,
        "scopes": ["finance:period:read"],
        "revision_hash": "b" * 64,
    }
    denied = client.post(
        f"{path}:close",
        headers=trusted,
        json={"company_id": COMPANY_ID, "expected_version": 2},
    )
    assert denied.status_code == 403


@pytest.mark.skipif(
    not DATABASE_URL or not POSTGRES_SMOKE,
    reason="Protected S1-03 EOS PostgreSQL smoke is disabled",
)
def test_actual_postgres_close_post_race_overlap_and_zero_residue() -> None:
    schema_name = f"mybee_s103_{uuid.uuid4().hex}"
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
        assert "2521_eos_accounting_period_runtime" in result.applied
        db = build_eos_database_runtime(
            environ={"NEX_EOS_TEST_DATABASE_URL": scoped_url},
            database_env="NEX_EOS_TEST_DATABASE_URL",
        )
        _seed_company(db.session_factory)
        repository = SqlAlchemyEosAccountingPeriodRepository(db.session_factory)
        repository.create_open_period(_period())

        locked = Event()
        release = Event()

        def admitted_post() -> str:
            with db.session_factory.begin() as session:
                repository.lock_open_for_post(
                    session,
                    tenant_id=TENANT_ID,
                    company_id=COMPANY_ID,
                    posting_date=date(2026, 1, 15),
                )
                locked.set()
                assert release.wait(timeout=5)
            return "POST_COMMITTED"

        def request_close() -> dict[str, object]:
            return repository.advance_close(
                tenant_id=TENANT_ID,
                company_id=COMPANY_ID,
                period_id=PERIOD_ID,
                expected_version=1,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            post_future = executor.submit(admitted_post)
            assert locked.wait(timeout=5)
            close_future = executor.submit(request_close)
            time.sleep(0.15)
            assert close_future.done() is False
            release.set()
            assert post_future.result(timeout=5) == "POST_COMMITTED"
            assert close_future.result(timeout=5)["state"] == "CLOSING"

        def rejected_post(_attempt: int) -> str:
            try:
                with db.session_factory.begin() as session:
                    repository.lock_open_for_post(
                        session,
                        tenant_id=TENANT_ID,
                        company_id=COMPANY_ID,
                        posting_date=date(2026, 1, 15),
                    )
            except EosAccountingPeriodError as exc:
                return exc.error_code
            return "UNEXPECTED_COMMIT"

        with ThreadPoolExecutor(max_workers=8) as executor:
            outcomes = list(executor.map(rejected_post, range(20)))
        assert outcomes == ["EOS_ACCOUNTING_PERIOD_NOT_OPEN"] * 20
        closed = repository.advance_close(
            tenant_id=TENANT_ID,
            company_id=COMPANY_ID,
            period_id=PERIOD_ID,
            expected_version=2,
            close_proof_ref=PROOF,
            ledger_cutoff_watermark="journal:100",
        )
        assert closed["state"] == "CLOSED"

        barrier = Barrier(2)

        def insert_overlapping(period_id: str, period_no: int) -> str:
            with psycopg.connect(psycopg_database_url(scoped_url)) as connection:
                try:
                    with connection.cursor() as cursor:
                        barrier.wait(timeout=5)
                        cursor.execute(
                            """
                            INSERT INTO eos_accounting_period (
                                tenant_id, company_id, period_id, fiscal_year,
                                period_no, start_date, end_date, state, version,
                                created_at, updated_at
                            ) VALUES (
                                %s, %s, %s, 2026, %s, '2026-02-01',
                                '2026-02-28', 'OPEN', 1, now(), now()
                            )
                            """,
                            (TENANT_ID, COMPANY_ID, period_id, period_no),
                        )
                        time.sleep(0.15)
                    connection.commit()
                    return "COMMITTED"
                except psycopg.Error as exc:
                    connection.rollback()
                    return exc.sqlstate or "UNKNOWN"

        ids = [str(uuid.uuid4()), str(uuid.uuid4())]
        with ThreadPoolExecutor(max_workers=2) as executor:
            overlaps = list(executor.map(insert_overlapping, ids, (2, 3)))
        assert sorted(overlaps) == ["23505", "COMMITTED"]
        with db.session_factory() as session:
            rows = (
                session.execute(select(EOS_ACCOUNTING_PERIOD_TABLE.c.period_id))
                .scalars()
                .all()
            )
        assert len(rows) == 2
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
            cursor.execute(
                "SELECT count(*) FROM information_schema.schemata WHERE schema_name = %s",
                (schema_name,),
            )
            assert cursor.fetchone() == (0,)
