from __future__ import annotations

import math
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from nex_eos import (
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_IDEMPOTENCY_TABLE,
    EOS_METADATA,
    EOS_OUTBOX_TABLE,
    EosBusinessOperationError,
    EosBusinessOperationRequest,
    InMemoryEosBusinessTransactionCoordinator,
    SqlAlchemyEosBusinessTransactionCoordinator,
)
from nex_eos.app import create_eos_app
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from run_migrations import load_migrations
from sqlalchemy import (
    Column,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    func,
    select,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 21, 8, 30, tzinfo=UTC)
BUSINESS_OPERATION_ID = "11111111-1111-4111-8111-111111111111"
OUTBOX_ID = "22222222-2222-4222-8222-222222222222"
EVENT_ID = "33333333-3333-4333-8333-333333333333"


def _request(**overrides: Any) -> EosBusinessOperationRequest:
    values = {
        "tenant_id": "tenant-a",
        "business_operation_id": BUSINESS_OPERATION_ID,
        "idempotency_key": "write:tenant-a:operation-1:node-1",
        "operation": "CREATE_VOUCHER_DRAFT",
        "payload_hash": semantic_sha256_hash_ref(
            {"project_id": "project-1", "amount": "1000.00"}
        ),
        "event_type": "BUSINESS_TRANSACTION_COMMITTED",
    }
    values.update(overrides)
    return EosBusinessOperationRequest(**values)


def _result() -> dict[str, Any]:
    return {
        "business_result_ref": "eos:voucher-draft:voucher-1",
        "voucher_status": "DRAFT",
    }


def _ids(*values: str):
    iterator = iter(values)
    return lambda: next(iterator)


def _memory() -> InMemoryEosBusinessTransactionCoordinator:
    return InMemoryEosBusinessTransactionCoordinator(
        id_factory=_ids(OUTBOX_ID, EVENT_ID),
        clock=lambda: NOW,
    )


def _sqlite_stack():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata = MetaData()
    probe = Table(
        "eos_s09_unit_probe",
        metadata,
        Column("probe_id", String(64), primary_key=True),
        Column("mutation_count", Integer, nullable=False),
    )
    EOS_METADATA.create_all(engine)
    metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    coordinator = SqlAlchemyEosBusinessTransactionCoordinator(
        sessions,
        id_factory=_ids(OUTBOX_ID, EVENT_ID),
        clock=lambda: NOW,
    )
    return engine, sessions, coordinator, probe


def _count(session, table: Table) -> int:
    return session.execute(select(func.count()).select_from(table)).scalar_one()


def test_s09_migration_declares_only_transaction_core_tables() -> None:
    migrations = load_migrations("nex-eos")

    assert [migration.version for migration in migrations] == [
        "2500_eos_schema_migrations_baseline",
        "2501_eos_business_transaction_core",
    ]
    sql = migrations[-1].sql
    compact = " ".join(sql.lower().split())
    assert "create table if not exists eos_business_operation" in compact
    assert "create table if not exists eos_idempotency" in compact
    assert "create table if not exists eos_outbox" in compact
    assert "eos_voucher_draft" not in compact
    assert "eos_org_unit" not in compact
    assert "schema_migrations" in compact

    identifiers = [
        token.strip()
        for line in sql.splitlines()
        if "constraint " in line.lower() or "index if not exists " in line.lower()
        for token in [line.split()[-1]]
    ]
    assert identifiers
    assert all(len(identifier) <= 63 for identifier in identifiers)


def test_memory_exact_duplicate_reuses_original_result_and_outbox() -> None:
    coordinator = _memory()
    calls = 0

    def mutation(_session):
        nonlocal calls
        calls += 1
        return _result()

    created = coordinator.execute(_request(), mutation)
    replayed = coordinator.execute(
        _request(),
        lambda _session: pytest.fail("idempotent replay must not mutate"),
    )

    assert created.created is True
    assert replayed.created is False
    assert replayed.result == created.result == _result()
    assert replayed.outbox_id == created.outbox_id == OUTBOX_ID
    assert replayed.event_id == created.event_id == EVENT_ID
    assert replayed.commit_state == "COMMITTED"
    assert calls == 1
    assert coordinator.record_counts() == {
        "business_operations": 1,
        "idempotency": 1,
        "outbox": 1,
    }
    projection = replayed.to_public_projection()
    assert projection["outbox"]["delivery_state"] == "PENDING"
    assert projection["result"]["business_result_ref"].endswith("voucher-1")


def test_memory_result_without_reference_emits_identity_only_event() -> None:
    coordinator = _memory()

    created = coordinator.execute(
        _request(),
        lambda _session: {"status": "COMMITTED"},
    )

    assert created.created is True
    assert created.result == {"status": "COMMITTED"}


@pytest.mark.parametrize(
    "changed",
    (
        {"payload_hash": semantic_sha256_hash_ref({"amount": "999.00"})},
        {"operation": "UPDATE_VOUCHER_DRAFT"},
        {"business_operation_id": "44444444-4444-4444-8444-444444444444"},
        {"event_type": "VOUCHER_DRAFT_CREATED"},
    ),
)
def test_memory_same_key_rejects_changed_semantics(changed: dict[str, str]) -> None:
    coordinator = _memory()
    coordinator.execute(_request(), lambda _session: _result())

    with pytest.raises(EosBusinessOperationError) as error:
        coordinator.execute(_request(**changed), lambda _session: _result())

    assert error.value.error_code == "EOS_IDEMPOTENCY_CONFLICT"
    assert error.value.status_code == 409
    assert error.value.retryable is False
    assert coordinator.record_counts()["business_operations"] == 1


def test_memory_same_business_operation_rejects_changed_key() -> None:
    coordinator = _memory()
    coordinator.execute(_request(), lambda _session: _result())

    with pytest.raises(EosBusinessOperationError) as error:
        coordinator.execute(
            _request(idempotency_key="different-key"),
            lambda _session: _result(),
        )

    assert error.value.error_code == "EOS_IDEMPOTENCY_CONFLICT"
    assert coordinator.record_counts() == {
        "business_operations": 1,
        "idempotency": 1,
        "outbox": 1,
    }


def test_memory_concurrent_duplicate_executes_mutation_once() -> None:
    generated_ids = iter((OUTBOX_ID, EVENT_ID))
    coordinator = InMemoryEosBusinessTransactionCoordinator(
        id_factory=lambda: next(generated_ids),
        clock=lambda: NOW,
    )
    calls = 0
    call_lock = threading.Lock()

    def mutation(_session):
        nonlocal calls
        with call_lock:
            calls += 1
        return _result()

    with ThreadPoolExecutor(max_workers=12) as executor:
        results = list(
            executor.map(
                lambda _index: coordinator.execute(_request(), mutation),
                range(24),
            )
        )

    assert calls == 1
    assert sum(result.created for result in results) == 1
    assert {result.outbox_id for result in results} == {OUTBOX_ID}
    assert coordinator.record_counts()["outbox"] == 1


def test_memory_identity_is_tenant_qualified() -> None:
    coordinator = InMemoryEosBusinessTransactionCoordinator(
        id_factory=_ids(
            OUTBOX_ID,
            EVENT_ID,
            "55555555-5555-4555-8555-555555555555",
            "66666666-6666-4666-8666-666666666666",
        ),
        clock=lambda: NOW,
    )

    first = coordinator.execute(_request(), lambda _session: _result())
    second = coordinator.execute(
        _request(tenant_id="tenant-b"),
        lambda _session: _result(),
    )

    assert first.created is True
    assert second.created is True
    assert first.business_operation_id == second.business_operation_id
    assert first.idempotency_key == second.idempotency_key
    assert coordinator.record_counts() == {
        "business_operations": 2,
        "idempotency": 2,
        "outbox": 2,
    }


def test_memory_failed_mutation_leaves_no_core_records() -> None:
    coordinator = _memory()

    def fail(_session):
        raise RuntimeError("sensitive database detail")

    with pytest.raises(EosBusinessOperationError) as error:
        coordinator.execute(_request(), fail)

    assert error.value.error_code == "EOS_BUSINESS_MUTATION_FAILED"
    assert "sensitive" not in str(error.value)
    assert coordinator.record_counts() == {
        "business_operations": 0,
        "idempotency": 0,
        "outbox": 0,
    }


@pytest.mark.parametrize(
    "candidate",
    (
        _request(tenant_id="bad tenant"),
        _request(business_operation_id="not-a-uuid"),
        _request(idempotency_key=" key"),
        _request(idempotency_key="x" * 257),
        _request(operation="lowercase"),
        _request(payload_hash="sha256:bad"),
        _request(event_type="UNKNOWN_EVENT"),
        _request(business_operation_id=7),  # type: ignore[arg-type]
    ),
)
def test_request_validation_fails_before_mutation(
    candidate: EosBusinessOperationRequest,
) -> None:
    coordinator = _memory()

    with pytest.raises(EosBusinessOperationError) as error:
        coordinator.execute(
            candidate,
            lambda _session: pytest.fail("invalid requests must not mutate"),
        )

    assert error.value.error_code == "EOS_TRANSACTION_REQUEST_INVALID"
    assert error.value.status_code == 400


def test_request_and_result_runtime_boundaries_fail_closed() -> None:
    coordinator = _memory()
    with pytest.raises(EosBusinessOperationError):
        coordinator.execute("invalid", lambda _session: _result())  # type: ignore[arg-type]
    with pytest.raises(EosBusinessOperationError):
        coordinator.execute(_request(), None)  # type: ignore[arg-type]
    with pytest.raises(EosBusinessOperationError):
        coordinator.execute(_request(), lambda _session: ["not", "an", "object"])  # type: ignore[return-value]
    with pytest.raises(EosBusinessOperationError):
        coordinator.execute(_request(), lambda _session: {"value": math.nan})
    with pytest.raises(EosBusinessOperationError):
        coordinator.execute(
            _request(),
            lambda _session: {"business_result_ref": " bad-ref"},
        )


def test_memory_rejects_naive_clock_and_invalid_generated_id() -> None:
    naive_clock = InMemoryEosBusinessTransactionCoordinator(
        id_factory=_ids(OUTBOX_ID, EVENT_ID),
        clock=lambda: datetime(2026, 10, 21, 8, 30),  # noqa: DTZ001
    )
    with pytest.raises(EosBusinessOperationError, match="timezone-aware"):
        naive_clock.execute(_request(), lambda _session: _result())

    invalid_id = InMemoryEosBusinessTransactionCoordinator(
        id_factory=lambda: "not-a-uuid",
        clock=lambda: NOW,
    )
    with pytest.raises(EosBusinessOperationError, match="outbox_id"):
        invalid_id.execute(_request(), lambda _session: _result())


def test_sqlite_transaction_commits_business_result_and_safe_outbox_atomically() -> (
    None
):
    engine, sessions, coordinator, probe = _sqlite_stack()

    def mutation(session):
        assert session is not None
        session.execute(probe.insert().values(probe_id="probe-1", mutation_count=1))
        return {
            **_result(),
            "private_financial_detail": "must-not-enter-outbox",
        }

    created = coordinator.execute(_request(), mutation)
    replayed = coordinator.execute(
        _request(),
        lambda _session: pytest.fail("replay must not execute mutation"),
    )
    conflict_reloaded = coordinator._load_after_integrity_conflict(_request())

    with sessions() as session:
        assert _count(session, EOS_BUSINESS_OPERATION_TABLE) == 1
        assert _count(session, EOS_IDEMPOTENCY_TABLE) == 1
        assert _count(session, EOS_OUTBOX_TABLE) == 1
        assert _count(session, probe) == 1
        event_payload = session.execute(
            select(EOS_OUTBOX_TABLE.c.event_payload)
        ).scalar_one()

    engine.dispose()
    assert created.created is True
    assert replayed.created is False
    assert conflict_reloaded is not None
    assert conflict_reloaded.created is False
    assert replayed.result["private_financial_detail"] == "must-not-enter-outbox"
    assert "private_financial_detail" not in event_payload
    assert event_payload["business_result_ref"] == "eos:voucher-draft:voucher-1"


def test_sqlite_mutation_failure_rolls_back_business_and_core_records() -> None:
    engine, sessions, coordinator, probe = _sqlite_stack()

    def mutation(session):
        assert session is not None
        session.execute(probe.insert().values(probe_id="rollback", mutation_count=1))
        raise RuntimeError("rollback")

    with pytest.raises(EosBusinessOperationError) as error:
        coordinator.execute(_request(), mutation)

    with sessions() as session:
        assert _count(session, EOS_BUSINESS_OPERATION_TABLE) == 0
        assert _count(session, EOS_IDEMPOTENCY_TABLE) == 0
        assert _count(session, EOS_OUTBOX_TABLE) == 0
        assert _count(session, probe) == 0
    engine.dispose()
    assert error.value.error_code == "EOS_BUSINESS_MUTATION_FAILED"


def test_sqlite_conflict_and_incomplete_state_fail_closed() -> None:
    engine, sessions, coordinator, _probe = _sqlite_stack()
    coordinator.execute(_request(), lambda _session: _result())

    with pytest.raises(EosBusinessOperationError) as conflict:
        coordinator.execute(
            _request(payload_hash=semantic_sha256_hash_ref({"changed": True})),
            lambda _session: _result(),
        )
    assert conflict.value.error_code == "EOS_IDEMPOTENCY_CONFLICT"

    with sessions.begin() as session:
        session.execute(EOS_OUTBOX_TABLE.delete())
    with pytest.raises(EosBusinessOperationError) as invalid_state:
        coordinator.execute(_request(), lambda _session: _result())
    engine.dispose()
    assert invalid_state.value.error_code == "EOS_TRANSACTION_STATE_INVALID"


def test_sqlite_idempotency_binding_and_result_drift_fail_closed() -> None:
    engine, sessions, coordinator, _probe = _sqlite_stack()
    coordinator.execute(_request(), lambda _session: _result())

    with sessions.begin() as session:
        session.execute(
            EOS_IDEMPOTENCY_TABLE.update().values(operation="ALTERED_OPERATION")
        )
    with pytest.raises(EosBusinessOperationError) as binding:
        coordinator.execute(_request(), lambda _session: _result())
    assert binding.value.error_code == "EOS_IDEMPOTENCY_CONFLICT"

    with sessions.begin() as session:
        session.execute(
            EOS_IDEMPOTENCY_TABLE.update().values(
                operation="CREATE_VOUCHER_DRAFT",
                result_json={"business_result_ref": "different-result"},
            )
        )
    with pytest.raises(EosBusinessOperationError) as result_drift:
        coordinator.execute(_request(), lambda _session: _result())
    engine.dispose()
    assert result_drift.value.error_code == "EOS_TRANSACTION_STATE_INVALID"


def test_sqlite_integrity_race_replays_or_fails_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, _sessions, coordinator, _probe = _sqlite_stack()
    replay = _memory().execute(_request(), lambda _session: _result())

    def duplicate(*_args, **_kwargs):
        raise IntegrityError("insert", {}, RuntimeError("duplicate"))

    monkeypatch.setattr(coordinator, "_execute_new", duplicate)
    monkeypatch.setattr(
        coordinator,
        "_load_after_integrity_conflict",
        lambda _request: replay,
    )
    resolved = coordinator.execute(_request(), lambda _session: _result())
    assert resolved is replay

    monkeypatch.setattr(
        coordinator,
        "_load_after_integrity_conflict",
        lambda _request: None,
    )
    with pytest.raises(EosBusinessOperationError) as unavailable:
        coordinator.execute(_request(), lambda _session: _result())
    engine.dispose()
    assert unavailable.value.error_code == "EOS_TRANSACTION_UNAVAILABLE"


def test_integrity_conflict_reload_normalizes_store_failure() -> None:
    def broken_session():
        raise SQLAlchemyError("unavailable")

    coordinator = SqlAlchemyEosBusinessTransactionCoordinator(
        broken_session,  # type: ignore[arg-type]
    )

    with pytest.raises(EosBusinessOperationError) as error:
        coordinator._load_after_integrity_conflict(_request())

    assert error.value.error_code == "EOS_TRANSACTION_UNAVAILABLE"


def test_sqlite_unavailable_store_returns_safe_retryable_error() -> None:
    engine, _sessions, coordinator, _probe = _sqlite_stack()
    EOS_METADATA.drop_all(engine)

    with pytest.raises(EosBusinessOperationError) as error:
        coordinator.execute(_request(), lambda _session: _result())

    engine.dispose()
    assert error.value.error_code == "EOS_TRANSACTION_UNAVAILABLE"
    assert error.value.status_code == 503
    assert error.value.retryable is True


def test_app_wires_sql_transaction_coordinator_only_with_database_runtime() -> None:
    base = {
        "NEX_EOS_SERVICE_ID": "nex-eos",
        "NEX_PROFILE": "test",
        "NEX_VERSION": "2.1.0-p8-s09",
        "NEX_BUILD_SHA": "p8s09test",
        "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
    }
    without_database = create_eos_app(environ=base)
    assert without_database.state.eos_business_transactions is None

    with_database = create_eos_app(
        environ={**base, "NEX_EOS_DATABASE_URL": "sqlite+pysqlite:///:memory:"}
    )
    try:
        assert isinstance(
            with_database.state.eos_business_transactions,
            SqlAlchemyEosBusinessTransactionCoordinator,
        )
    finally:
        with_database.state.eos_database_runtime.dispose()


def test_environment_example_protects_s09_postgres_smoke() -> None:
    contents = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "NEX_EOS_P8_S09_POSTGRES_SMOKE=0" in contents
