from __future__ import annotations

from types import SimpleNamespace

import pytest

import run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_postgres_smoke as smoke
from nex_runtime import InMemoryOperationalEventStore, InMemoryWorkerHeartbeatStore
from run_migrations import MigrationError


class FakeUrl:
    database = "nex_ag_test"

    def get_backend_name(self) -> str:
        return "postgresql"


class FakeEngine:
    def __init__(
        self,
        *,
        heartbeat_rows: list[dict[str, object]] | None = None,
        event_rows: list[dict[str, object]] | None = None,
        rowcount: int = 1,
    ) -> None:
        self.disposed = False
        self.url = FakeUrl()
        self.heartbeat_rows = list(heartbeat_rows or [])
        self.event_rows = list(event_rows or [])
        self.rowcount = rowcount
        self.connections: list[FakeSqlConnection] = []

    def begin(self) -> FakeBegin:
        connection = FakeSqlConnection(
            heartbeat_rows=self.heartbeat_rows,
            event_rows=self.event_rows,
            rowcount=self.rowcount,
        )
        self.connections.append(connection)
        return FakeBegin(connection)

    def dispose(self) -> None:
        self.disposed = True


def smoke_env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        smoke.DATABASE_ENV: "postgresql://nex_ag_user:secret@localhost/nex_ag_test",
    }


def test_dispatch_daemon_liveness_recovery_postgres_smoke_skips_without_opt_in() -> None:
    evidence = (
        smoke.run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_postgres_smoke(
            {}
        )
    )

    assert evidence["status"] == "SKIPPED"
    assert smoke.SMOKE_ENV in evidence["skip_reason"]
    assert "liveness_recovery_postgres_smoke=skipped" in smoke.summary_line(evidence)


def test_dispatch_daemon_liveness_recovery_postgres_smoke_requires_database_url() -> None:
    evidence = (
        smoke.run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_postgres_smoke(
            {smoke.SMOKE_ENV: "1"}
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "database_url_missing"


def test_dispatch_daemon_liveness_recovery_postgres_smoke_reports_migration_failure(
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
        smoke.run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_postgres_smoke(
            smoke_env()
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "migration_failed"
    assert "bad migration" in evidence["detail"]


def test_dispatch_daemon_liveness_recovery_postgres_smoke_reports_engine_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smoke, "run_service_migrations", _migration_result)
    monkeypatch.setattr(
        smoke,
        "build_engine",
        lambda database_url: (_ for _ in ()).throw(ValueError("bad database url")),
    )

    evidence = (
        smoke.run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_postgres_smoke(
            smoke_env()
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "smoke_execution_failed"
    assert "bad database url" in evidence["detail"]


def test_dispatch_daemon_liveness_recovery_postgres_smoke_success_is_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = FakeEngine(rowcount=1)
    heartbeat_store = InMemoryWorkerHeartbeatStore()
    event_store = InMemoryOperationalEventStore()
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
        "SqlAlchemyOperationalEventStore",
        lambda session_factory: event_store,
    )
    monkeypatch.setattr(
        smoke,
        "_db_recovery_observations",
        lambda engine, *, worker_id, trace_id, audit_event_ids: {
            "heartbeat_table": "service_worker_heartbeats",
            "event_table": "service_operational_events",
            "heartbeat_row_count": 1,
            "event_count": 1,
            "backend": "postgresql",
            "database": "nex_ag_test",
            "heartbeat_trace_id_persisted": True,
            "expected_audit_event_count": 1,
            "expected_audit_event_ids_persisted": True,
            "event_type_counts": {
                smoke.AG_OPERATOR_REVIEW_DISPATCH_DAEMON_LIVENESS_RECOVERY_EVENT_PLANNED: 1
            },
            "severity_counts": {"INFO": 1},
            "raw_value_leak_count": 0,
        },
    )
    env = smoke_env()

    evidence = (
        smoke.run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_postgres_smoke(
            env
        )
    )
    serialized = str(evidence)

    assert evidence["status"] == "PASS"
    assert evidence["smoke_schema_version"] == smoke.SCHEMA_VERSION
    assert evidence["checks"]["backend_is_postgresql"] is True
    assert evidence["checks"]["heartbeat_row_persisted"] is True
    assert evidence["checks"]["audit_event_emitted"] is True
    assert evidence["checks"]["audit_event_row_persisted"] is True
    assert evidence["checks"]["recovery_plan_actionable"] is True
    assert evidence["checks"]["dashboard_recovery_actionable"] is True
    assert evidence["checks"]["issue_candidate_ack_policy_ready"] is True
    assert evidence["liveness_summary"]["liveness_status"] == "STALE"
    assert evidence["recovery_plan_summary"]["requires_operator_action"] is True
    assert evidence["recovery_policy_summary"]["policy_status"] == "ACTIONABLE"
    assert evidence["dashboard_recovery_status"] == "ACTION_RECOMMENDED"
    assert evidence["audit_event"]["ok"] is True
    assert evidence["issue_candidate"]["ack_policy_status"] == "ACTIONABLE"
    assert evidence["cleanup"]["deleted_heartbeat_rows"] == 1
    assert evidence["cleanup"]["deleted_audit_event_rows"] == 1
    assert fake_engine.disposed is True
    assert env[smoke.DATABASE_ENV] not in serialized
    assert smoke.RAW_RECOVERY_SECRET not in serialized
    assert "secret" not in evidence["redacted_database_url"]
    assert "liveness_recovery_postgres_smoke=pass" in smoke.summary_line(evidence)


def test_dispatch_daemon_liveness_recovery_postgres_smoke_reports_failed_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = FakeEngine(rowcount=0)
    heartbeat_store = InMemoryWorkerHeartbeatStore()
    event_store = InMemoryOperationalEventStore()
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
        "SqlAlchemyOperationalEventStore",
        lambda session_factory: event_store,
    )
    monkeypatch.setattr(
        smoke,
        "_db_recovery_observations",
        lambda engine, *, worker_id, trace_id, audit_event_ids: {
            "heartbeat_table": "service_worker_heartbeats",
            "event_table": "service_operational_events",
            "heartbeat_row_count": 0,
            "event_count": 0,
            "backend": "postgresql",
            "database": "nex_ag_test",
            "heartbeat_trace_id_persisted": False,
            "expected_audit_event_count": 1,
            "expected_audit_event_ids_persisted": False,
            "event_type_counts": {},
            "severity_counts": {},
            "raw_value_leak_count": 0,
        },
    )

    evidence = (
        smoke.run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_postgres_smoke(
            smoke_env()
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "checks_failed"
    assert evidence["checks"]["heartbeat_row_persisted"] is False
    assert evidence["checks"]["audit_event_row_persisted"] is False
    assert fake_engine.disposed is True


def test_dispatch_daemon_liveness_recovery_postgres_smoke_cleans_up_after_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = FakeEngine(rowcount=1)
    heartbeat_store = InMemoryWorkerHeartbeatStore()
    event_store = InMemoryOperationalEventStore()
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
        "SqlAlchemyOperationalEventStore",
        lambda session_factory: event_store,
    )
    monkeypatch.setattr(
        smoke,
        "_db_recovery_observations",
        lambda engine, *, worker_id, trace_id, audit_event_ids: (_ for _ in ()).throw(
            ValueError("observation failed")
        ),
    )

    evidence = (
        smoke.run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_postgres_smoke(
            smoke_env()
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "smoke_execution_failed"
    assert "observation failed" in evidence["detail"]
    assert fake_engine.disposed is True
    assert len(fake_engine.connections) == 2


def test_dispatch_daemon_liveness_recovery_postgres_smoke_restores_original_heartbeat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = FakeEngine(rowcount=0)
    heartbeat_store = InMemoryWorkerHeartbeatStore()
    event_store = InMemoryOperationalEventStore()
    original = smoke._smoke_heartbeat(
        suffix="original",
        status="IDLE",
        trace_id="0" * 32,
        last_seen_at=smoke.datetime.now(smoke.UTC),
    )
    heartbeat_store.upsert_heartbeat(original)
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
        "SqlAlchemyOperationalEventStore",
        lambda session_factory: event_store,
    )
    monkeypatch.setattr(
        smoke,
        "_db_recovery_observations",
        lambda engine, *, worker_id, trace_id, audit_event_ids: {
            "heartbeat_table": "service_worker_heartbeats",
            "event_table": "service_operational_events",
            "heartbeat_row_count": 1,
            "event_count": 1,
            "backend": "postgresql",
            "database": "nex_ag_test",
            "heartbeat_trace_id_persisted": True,
            "expected_audit_event_count": 1,
            "expected_audit_event_ids_persisted": True,
            "event_type_counts": {
                smoke.AG_OPERATOR_REVIEW_DISPATCH_DAEMON_LIVENESS_RECOVERY_EVENT_PLANNED: 1
            },
            "severity_counts": {"INFO": 1},
            "raw_value_leak_count": 0,
        },
    )

    evidence = (
        smoke.run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_postgres_smoke(
            smoke_env()
        )
    )

    restored = heartbeat_store.get_heartbeat(smoke.SERVICE_ID, smoke.WORKER_ID)
    assert evidence["status"] == "PASS"
    assert evidence["cleanup"]["restored_original_heartbeat"] is True
    assert evidence["cleanup"]["deleted_heartbeat_rows"] == 0
    assert restored == original


def test_dispatch_daemon_liveness_recovery_postgres_smoke_main(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(smoke, "load_env_file", lambda *_args: None)
    monkeypatch.setattr(
        smoke,
        "run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_postgres_smoke",
        lambda: {"status": "PASS", "cleanup": {}, "observations": {}},
    )

    assert smoke.main(["--summary"]) == 0
    assert "liveness_recovery_postgres_smoke=pass" in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_postgres_smoke",
        lambda: {"status": "FAIL", "failure_code": "boom"},
    )
    assert smoke.main([]) == 1
    assert '"failure_code": "boom"' in capsys.readouterr().out


def test_dispatch_daemon_liveness_recovery_postgres_smoke_redaction_failure() -> None:
    with pytest.raises(ValueError):
        smoke.assert_smoke_evidence_redacted(
            smoke.RAW_RECOVERY_SECRET,
            {},
        )

    assert "liveness_recovery_postgres_smoke=fail failure=boom" in smoke.summary_line(
        {"status": "FAIL", "failure_code": "boom"}
    )


def test_dispatch_daemon_liveness_recovery_postgres_smoke_db_helpers() -> None:
    event_id = "event-0797"
    engine = FakeEngine(
        heartbeat_rows=[
            {
                "service_id": smoke.SERVICE_ID,
                "worker_id": smoke.WORKER_ID,
                "worker_type": smoke.DISPATCH_EXECUTION_DAEMON_HEARTBEAT_WORKER_TYPE,
                "status": "IDLE",
                "trace_id": "trace-0797",
                "metadata_text": "{}",
            },
            {
                "service_id": smoke.SERVICE_ID,
                "worker_id": smoke.WORKER_ID,
                "worker_type": smoke.DISPATCH_EXECUTION_DAEMON_HEARTBEAT_WORKER_TYPE,
                "status": "ERROR",
                "trace_id": None,
                "metadata_text": smoke.RAW_RECOVERY_SECRET,
            },
        ],
        event_rows=[
            {
                "event_id": event_id,
                "event_type": (
                    smoke.AG_OPERATOR_REVIEW_DISPATCH_DAEMON_LIVENESS_RECOVERY_EVENT_PLANNED
                ),
                "severity": "INFO",
                "subject_type": "operator_review_dispatch_daemon_liveness_recovery",
                "subject_id": "recovery_plan",
                "details_text": "{}",
            },
            {
                "event_id": "event-secret",
                "event_type": "other",
                "severity": "ERROR",
                "subject_type": "other",
                "subject_id": "other",
                "details_text": smoke.RAW_RECOVERY_SECRET,
            },
        ],
        rowcount=2,
    )

    observations = smoke._db_recovery_observations(
        engine,
        worker_id=smoke.WORKER_ID,
        trace_id="trace-0797",
        audit_event_ids=[event_id],
    )
    deleted_heartbeat = smoke._delete_smoke_heartbeat(
        engine,
        worker_id=smoke.WORKER_ID,
    )
    deleted_events = smoke._delete_smoke_events(engine, trace_id="trace-0797")

    assert observations["heartbeat_row_count"] == 2
    assert observations["event_count"] == 2
    assert observations["heartbeat_table"] == "service_worker_heartbeats"
    assert observations["event_table"] == "service_operational_events"
    assert observations["backend"] == "postgresql"
    assert observations["database"] == "nex_ag_test"
    assert observations["heartbeat_trace_id_persisted"] is True
    assert observations["expected_audit_event_ids_persisted"] is True
    assert observations["event_type_counts"][
        smoke.AG_OPERATOR_REVIEW_DISPATCH_DAEMON_LIVENESS_RECOVERY_EVENT_PLANNED
    ] == 1
    assert observations["severity_counts"]["ERROR"] == 1
    assert observations["raw_value_leak_count"] == 2
    assert deleted_heartbeat == 2
    assert deleted_events == 2


def test_dispatch_daemon_liveness_recovery_postgres_smoke_helper_edge_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert smoke._liveness_issue_candidate({"issue_candidates": object()}) is None
    assert smoke._liveness_issue_candidate({"issue_candidates": []}) is None
    assert smoke._liveness_issue_candidate(
        {"issue_candidates": [{"rule_id": "other"}]}
    ) is None
    assert smoke._issue_candidate_ack_policy(None) == {}
    assert smoke._issue_candidate_ack_policy({"signal": "bad"}) == {}
    assert smoke._issue_candidate_summary(None) == {"present": False}
    assert smoke._issue_candidate_summary(
        {
            "rule_id": "operator_review_dispatch_daemon_liveness_attention_required.v1",
            "severity": "ERROR",
            "signal": "not-a-mapping",
        }
    ) == {
        "present": True,
        "rule_id": "operator_review_dispatch_daemon_liveness_attention_required.v1",
        "severity": "ERROR",
        "signal_status": None,
        "worker_id": None,
        "ack_policy_status": None,
        "ack_policy_new_tables_required": None,
    }
    assert smoke._recovery_policy_summary("bad") == {"present": False}
    assert smoke._recovery_policy_summary({"state_storage": "bad"}) == {
        "present": True,
        "policy_status": None,
        "liveness_status": None,
        "supported_actions": [],
        "new_tables_required": None,
    }
    assert smoke._audit_emit_summary(
        SimpleNamespace(
            to_summary=lambda: {
                "ok": False,
                "error_code": "boom",
                "detail": "bad",
                "status_code": 503,
            }
        )
    ) == {
        "ok": False,
        "event_id": None,
        "event_type": None,
        "severity": None,
        "error_code": "boom",
    }
    assert smoke._engine_backend(object()) == "unknown"
    assert smoke._engine_database(object()) is None
    assert smoke._redact_detail("db=postgresql://u:p@h/db", database_url="x") == (
        "db=postgresql://u:p@h/db"
    )

    monkeypatch.setenv("NEX_AG_DISPATCH_DAEMON_ENABLED", "0")
    with smoke._temporary_environ({"NEX_AG_DISPATCH_DAEMON_ENABLED": "1"}):
        assert smoke.os.environ["NEX_AG_DISPATCH_DAEMON_ENABLED"] == "1"
    assert smoke.os.environ["NEX_AG_DISPATCH_DAEMON_ENABLED"] == "0"


def _migration_result(*args, **kwargs) -> SimpleNamespace:
    return SimpleNamespace(
        service_id=smoke.SERVICE_ID,
        planned=("0797",),
        applied=(),
        skipped=("0797",),
    )


class FakeMappings:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def mappings(self) -> FakeMappings:
        return self

    def __iter__(self):
        return iter(self._rows)


class FakeSqlConnection:
    def __init__(
        self,
        *,
        heartbeat_rows: list[dict[str, object]],
        event_rows: list[dict[str, object]],
        rowcount: int,
    ) -> None:
        self.heartbeat_rows = heartbeat_rows
        self.event_rows = event_rows
        self.rowcount = rowcount
        self.statements: list[object] = []

    def execute(self, statement, params):
        self.statements.append((statement, params))
        sql = str(statement)
        if "SELECT" in sql and "service_worker_heartbeats" in sql:
            return FakeMappings(self.heartbeat_rows)
        if "SELECT" in sql and "service_operational_events" in sql:
            return FakeMappings(self.event_rows)
        return SimpleNamespace(rowcount=self.rowcount)


class FakeBegin:
    def __init__(self, connection: FakeSqlConnection) -> None:
        self.connection = connection

    def __enter__(self) -> FakeSqlConnection:
        return self.connection

    def __exit__(self, exc_type, exc, traceback) -> bool:
        return False
