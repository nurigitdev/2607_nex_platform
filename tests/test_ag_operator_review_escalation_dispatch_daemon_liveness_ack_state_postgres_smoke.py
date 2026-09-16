from __future__ import annotations

from types import SimpleNamespace

import pytest

import run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_postgres_smoke as smoke
from nex_ag.operator_review_liveness_ack import (
    OperatorReviewLivenessAckStateStore,
    apply_operator_review_liveness_ack_state_transition,
)
from nex_runtime import InMemoryWorkerHeartbeatStore
from run_migrations import MigrationError


class FakeUrl:
    database = "nex_ag_test"

    def get_backend_name(self) -> str:
        return "postgresql"


class FakeEngine:
    def __init__(
        self,
        *,
        rows: list[dict[str, object]] | None = None,
        rowcount: int = 1,
    ) -> None:
        self.disposed = False
        self.url = FakeUrl()
        self.rows = list(rows or [])
        self.rowcount = rowcount
        self.connections: list[FakeSqlConnection] = []

    def begin(self) -> FakeBegin:
        connection = FakeSqlConnection(self.rows, self.rowcount)
        self.connections.append(connection)
        return FakeBegin(connection)

    def dispose(self) -> None:
        self.disposed = True


class FakeBegin:
    def __init__(self, connection: "FakeSqlConnection") -> None:
        self.connection = connection

    def __enter__(self) -> "FakeSqlConnection":
        return self.connection

    def __exit__(self, *_args: object) -> None:
        return None


class FakeSqlConnection:
    def __init__(
        self,
        rows: list[dict[str, object]],
        rowcount: int,
    ) -> None:
        self.rows = rows
        self.rowcount = rowcount
        self.statements: list[str] = []

    def execute(self, statement: object, _params: object | None = None) -> "FakeResult":
        self.statements.append(str(statement))
        return FakeResult(self.rows, self.rowcount)


class FakeResult:
    def __init__(
        self,
        rows: list[dict[str, object]],
        rowcount: int,
    ) -> None:
        self._rows = rows
        self.rowcount = rowcount

    def mappings(self) -> "FakeResult":
        return self

    def __iter__(self):
        return iter(self._rows)


def smoke_env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        smoke.DATABASE_ENV: "postgresql://nex_ag_user:secret@localhost/nex_ag_test",
    }


def test_dispatch_daemon_liveness_ack_state_postgres_smoke_skips_without_opt_in() -> None:
    evidence = (
        smoke.run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_postgres_smoke(
            {}
        )
    )

    assert evidence["status"] == "SKIPPED"
    assert smoke.SMOKE_ENV in evidence["skip_reason"]
    assert "liveness_ack_state_postgres_smoke=skipped" in smoke.summary_line(
        evidence
    )


def test_dispatch_daemon_liveness_ack_state_postgres_smoke_requires_database_url() -> None:
    evidence = (
        smoke.run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_postgres_smoke(
            {smoke.SMOKE_ENV: "1"}
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "database_url_missing"


def test_dispatch_daemon_liveness_ack_state_postgres_smoke_reports_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            MigrationError("bad migration")
        ),
    )

    evidence = (
        smoke.run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_postgres_smoke(
            smoke_env()
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "migration_failed"
    assert "bad migration" in evidence["detail"]


def test_dispatch_daemon_liveness_ack_state_postgres_smoke_reports_engine_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smoke, "run_service_migrations", _migration_result)
    monkeypatch.setattr(
        smoke,
        "build_engine",
        lambda database_url: (_ for _ in ()).throw(ValueError("bad database url")),
    )

    evidence = (
        smoke.run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_postgres_smoke(
            smoke_env()
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "smoke_execution_failed"
    assert "bad database url" in evidence["detail"]


def test_dispatch_daemon_liveness_ack_state_postgres_smoke_success_is_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = FakeEngine(rowcount=1)
    heartbeat_store = InMemoryWorkerHeartbeatStore()
    ack_state_store = OperatorReviewLivenessAckStateStore()
    monkeypatch.setattr(smoke, "run_service_migrations", _migration_result)
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: fake_engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda engine: object())
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyWorkerHeartbeatStore",
        lambda session_factory: heartbeat_store,
    )
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyOperatorReviewLivenessAckStateStore",
        lambda session_factory: ack_state_store,
    )
    monkeypatch.setattr(
        smoke,
        "_db_ack_state_observations",
        lambda engine, *, ack_state_id: {
            "table_name": "ag_op_review_ack_state",
            "row_count": 1,
            "backend": "postgresql",
            "database": "nex_ag_test",
            "state_statuses": [
                "CLEARED"
                if ack_state_store.get(ack_state_id)["state_status"] == "CLEARED"
                else "SUPPRESSED"
            ],
            "actions": [ack_state_store.get(ack_state_id)["action"]],
            "comment_hash_present": True,
            "idempotency_key_hash_present": True,
            "raw_value_leak_count": 0,
        },
    )
    env = smoke_env()

    evidence = (
        smoke.run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_postgres_smoke(
            env
        )
    )
    serialized = str(evidence)

    assert evidence["status"] == "PASS"
    assert evidence["smoke_schema_version"] == smoke.SCHEMA_VERSION
    assert evidence["checks"]["backend_is_postgresql"] is True
    assert evidence["checks"]["ack_state_row_persisted"] is True
    assert evidence["checks"]["get_by_id_round_trip"] is True
    assert evidence["checks"]["get_by_key_round_trip"] is True
    assert evidence["checks"]["list_round_trip"] is True
    assert evidence["checks"]["recovery_overlay_reads_persisted_state"] is True
    assert evidence["checks"]["clear_round_trip"] is True
    assert evidence["liveness_summary"]["liveness_status"] == "STALE"
    assert evidence["recovery_overlay"]["overlay_status"] == "STATE_PRESENT"
    assert evidence["recovery_overlay"]["effective_state_status"] == "SUPPRESSED"
    assert evidence["cleanup"]["deleted_heartbeat_rows"] == 1
    assert evidence["cleanup"]["deleted_ack_state_rows"] == 1
    assert fake_engine.disposed is True
    assert env[smoke.DATABASE_ENV] not in serialized
    assert smoke.RAW_IDEMPOTENCY_SECRET not in serialized
    assert "secret" not in evidence["redacted_database_url"]
    assert "liveness_ack_state_postgres_smoke=pass" in smoke.summary_line(evidence)


def test_dispatch_daemon_liveness_ack_state_postgres_smoke_reports_failed_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = FakeEngine(rowcount=0)
    heartbeat_store = InMemoryWorkerHeartbeatStore()
    ack_state_store = OperatorReviewLivenessAckStateStore()
    monkeypatch.setattr(smoke, "run_service_migrations", _migration_result)
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: fake_engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda engine: object())
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyWorkerHeartbeatStore",
        lambda session_factory: heartbeat_store,
    )
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyOperatorReviewLivenessAckStateStore",
        lambda session_factory: ack_state_store,
    )
    monkeypatch.setattr(
        smoke,
        "_db_ack_state_observations",
        lambda engine, *, ack_state_id: {
            "table_name": "ag_op_review_ack_state",
            "row_count": 0,
            "backend": "postgresql",
            "database": "nex_ag_test",
            "state_statuses": [],
            "actions": [],
            "comment_hash_present": False,
            "idempotency_key_hash_present": False,
            "raw_value_leak_count": 0,
        },
    )

    evidence = (
        smoke.run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_postgres_smoke(
            smoke_env()
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "checks_failed"
    assert evidence["checks"]["ack_state_row_persisted"] is False
    assert evidence["checks"]["clear_round_trip"] is False
    assert fake_engine.disposed is True


def test_dispatch_daemon_liveness_ack_state_postgres_smoke_cleans_up_after_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = FakeEngine(rowcount=1)
    heartbeat_store = InMemoryWorkerHeartbeatStore()
    ack_state_store = OperatorReviewLivenessAckStateStore()
    monkeypatch.setattr(smoke, "run_service_migrations", _migration_result)
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: fake_engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda engine: object())
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyWorkerHeartbeatStore",
        lambda session_factory: heartbeat_store,
    )
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyOperatorReviewLivenessAckStateStore",
        lambda session_factory: ack_state_store,
    )
    monkeypatch.setattr(
        smoke,
        "_db_ack_state_observations",
        lambda engine, *, ack_state_id: (_ for _ in ()).throw(
            ValueError("observation failed")
        ),
    )

    evidence = (
        smoke.run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_postgres_smoke(
            smoke_env()
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "smoke_execution_failed"
    assert "observation failed" in evidence["detail"]
    assert fake_engine.disposed is True
    assert len(fake_engine.connections) == 2


def test_dispatch_daemon_liveness_ack_state_postgres_smoke_restores_original_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = FakeEngine(rowcount=0)
    heartbeat_store = InMemoryWorkerHeartbeatStore()
    ack_state_store = OperatorReviewLivenessAckStateStore()
    original_heartbeat = smoke._smoke_heartbeat(
        suffix="original",
        trace_id="0" * 32,
        last_seen_at=smoke.datetime.now(smoke.UTC),
    )
    heartbeat_store.upsert_heartbeat(original_heartbeat)
    original_state = apply_operator_review_liveness_ack_state_transition(
        service_id=smoke.SERVICE_ID,
        worker_id=smoke.WORKER_ID,
        worker_type=smoke.DISPATCH_EXECUTION_DAEMON_HEARTBEAT_WORKER_TYPE,
        liveness_status="STALE",
        action="acknowledge_once",
        operator_ref={"operator_type": "service", "operator_id": "original"},
        reason_codes=["original_state"],
        observed_at=smoke.datetime.now(smoke.UTC),
    )["state"]
    ack_state_store.save(original_state)
    monkeypatch.setattr(smoke, "run_service_migrations", _migration_result)
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: fake_engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda engine: object())
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyWorkerHeartbeatStore",
        lambda session_factory: heartbeat_store,
    )
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyOperatorReviewLivenessAckStateStore",
        lambda session_factory: ack_state_store,
    )
    monkeypatch.setattr(
        smoke,
        "_db_ack_state_observations",
        lambda engine, *, ack_state_id: {
            "table_name": "ag_op_review_ack_state",
            "row_count": 1,
            "backend": "postgresql",
            "database": "nex_ag_test",
            "state_statuses": [
                "CLEARED"
                if ack_state_store.get(ack_state_id)["state_status"] == "CLEARED"
                else "SUPPRESSED"
            ],
            "actions": [ack_state_store.get(ack_state_id)["action"]],
            "comment_hash_present": True,
            "idempotency_key_hash_present": True,
            "raw_value_leak_count": 0,
        },
    )

    evidence = (
        smoke.run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_postgres_smoke(
            smoke_env()
        )
    )

    restored_heartbeat = heartbeat_store.get_heartbeat(smoke.SERVICE_ID, smoke.WORKER_ID)
    restored_state = ack_state_store.get(original_state["ack_state_id"])
    assert evidence["status"] == "PASS"
    assert evidence["cleanup"]["restored_original_heartbeat"] is True
    assert evidence["cleanup"]["restored_original_ack_state"] is True
    assert evidence["cleanup"]["deleted_heartbeat_rows"] == 0
    assert evidence["cleanup"]["deleted_ack_state_rows"] == 0
    assert restored_heartbeat == original_heartbeat
    assert restored_state == original_state


def test_dispatch_daemon_liveness_ack_state_postgres_smoke_main(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(smoke, "load_env_file", lambda *_args: None)
    monkeypatch.setattr(
        smoke,
        "run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_postgres_smoke",
        lambda: {
            "status": "PASS",
            "cleanup": {},
            "suppressed_observations": {},
            "cleared_observations": {},
            "recovery_overlay": {},
        },
    )

    assert smoke.main(["--summary"]) == 0
    assert "liveness_ack_state_postgres_smoke=pass" in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_postgres_smoke",
        lambda: {"status": "FAIL", "failure_code": "boom"},
    )
    assert smoke.main([]) == 1
    assert '"failure_code": "boom"' in capsys.readouterr().out


def test_dispatch_daemon_liveness_ack_state_postgres_smoke_redaction_failure() -> None:
    with pytest.raises(ValueError):
        smoke.assert_smoke_evidence_redacted(
            smoke.RAW_IDEMPOTENCY_SECRET,
            {},
        )

    assert "liveness_ack_state_postgres_smoke=fail failure=boom" in smoke.summary_line(
        {"status": "FAIL", "failure_code": "boom"}
    )


def test_dispatch_daemon_liveness_ack_state_postgres_smoke_db_helpers() -> None:
    engine = FakeEngine(
        rows=[
            {
                "ack_state_id": "ack-0808",
                "acknowledgement_key": "nex-ag:worker:stale",
                "service_id": smoke.SERVICE_ID,
                "worker_id": smoke.WORKER_ID,
                "liveness_status": "STALE",
                "action": "suppress_for_ttl",
                "state_status": "SUPPRESSED",
                "comment_preview": "safe preview",
                "comment_hash": "a" * 64,
                "idempotency_key_hash": "b" * 64,
                "metadata_text": "{}",
            },
            {
                "ack_state_id": "ack-0808",
                "acknowledgement_key": "nex-ag:worker:stale",
                "service_id": smoke.SERVICE_ID,
                "worker_id": smoke.WORKER_ID,
                "liveness_status": "STALE",
                "action": "clear",
                "state_status": "CLEARED",
                "comment_preview": None,
                "comment_hash": None,
                "idempotency_key_hash": smoke.RAW_IDEMPOTENCY_SECRET,
                "metadata_text": smoke.RAW_IDEMPOTENCY_SECRET,
            },
        ],
        rowcount=2,
    )

    observations = smoke._db_ack_state_observations(
        engine,
        ack_state_id="ack-0808",
    )
    deleted_heartbeat = smoke._delete_smoke_heartbeat(engine)
    deleted_ack_state = smoke._delete_smoke_ack_state(engine, ack_state_id="ack-0808")
    no_delete_cleanup = smoke._restore_or_delete_ack_state(
        OperatorReviewLivenessAckStateStore(),
        engine,
        original_ack_state=None,
        ack_state_id=None,
    )

    assert observations["row_count"] == 2
    assert observations["table_name"] == "ag_op_review_ack_state"
    assert observations["backend"] == "postgresql"
    assert observations["database"] == "nex_ag_test"
    assert observations["state_statuses"] == ["CLEARED", "SUPPRESSED"]
    assert observations["actions"] == ["clear", "suppress_for_ttl"]
    assert observations["comment_hash_present"] is True
    assert observations["idempotency_key_hash_present"] is True
    assert observations["raw_value_leak_count"] == 2
    assert deleted_heartbeat == 2
    assert deleted_ack_state == 2
    assert no_delete_cleanup == {
        "restored_original_ack_state": False,
        "deleted_ack_state_rows": 0,
    }


def test_dispatch_daemon_liveness_ack_state_postgres_smoke_defensive_helpers() -> None:
    assert smoke._overlay_summary(None) == {"present": False}
    assert smoke._engine_backend(SimpleNamespace(url=object())) == "unknown"


def test_dispatch_daemon_liveness_ack_state_quality_gate_wiring() -> None:
    quality_gate = (
        smoke.ROOT / "scripts" / "quality" / "run_quality_gate.sh"
    ).read_text(encoding="utf-8")

    assert (
        "run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_postgres_smoke.py --summary"
        in quality_gate
    )


def _migration_result(*_args: object, **_kwargs: object) -> SimpleNamespace:
    return SimpleNamespace(
        service_id=smoke.SERVICE_ID,
        planned=("0802_ag_liveness_ack_state",),
        applied=("0802_ag_liveness_ack_state",),
        skipped=(),
    )
