from __future__ import annotations

from types import SimpleNamespace

import pytest

import run_ag_operator_review_escalation_dispatch_daemon_process_postgres_smoke as smoke
from nex_runtime import InMemoryOperationalEventStore
from run_migrations import MigrationError


class FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


def smoke_env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        smoke.DATABASE_ENV: "postgresql://nex_ag_user:secret@localhost/nex_ag_test",
    }


def test_dispatch_daemon_process_postgres_smoke_skips_without_opt_in() -> None:
    evidence = (
        smoke.run_ag_operator_review_escalation_dispatch_daemon_process_postgres_smoke(
            {}
        )
    )

    assert evidence["status"] == "SKIPPED"
    assert smoke.SMOKE_ENV in evidence["skip_reason"]
    assert "process_postgres_smoke=skipped" in smoke.summary_line(evidence)


def test_dispatch_daemon_process_postgres_smoke_requires_database_url() -> None:
    evidence = (
        smoke.run_ag_operator_review_escalation_dispatch_daemon_process_postgres_smoke(
            {smoke.SMOKE_ENV: "1"}
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "database_url_missing"


def test_dispatch_daemon_process_postgres_smoke_reports_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(MigrationError("bad migration")),
    )

    evidence = (
        smoke.run_ag_operator_review_escalation_dispatch_daemon_process_postgres_smoke(
            smoke_env()
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "migration_failed"
    assert "bad migration" in evidence["detail"]


def test_dispatch_daemon_process_postgres_smoke_reports_engine_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smoke, "run_service_migrations", _migration_result)
    monkeypatch.setattr(
        smoke,
        "build_engine",
        lambda database_url: (_ for _ in ()).throw(ValueError("bad database url")),
    )

    evidence = (
        smoke.run_ag_operator_review_escalation_dispatch_daemon_process_postgres_smoke(
            smoke_env()
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "smoke_execution_failed"
    assert "bad database url" in evidence["detail"]


def test_dispatch_daemon_process_postgres_smoke_success_is_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = FakeEngine()
    cleanup_calls: list[dict[str, int]] = []
    event_store = InMemoryOperationalEventStore()
    monkeypatch.setattr(smoke, "run_service_migrations", _migration_result)
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: fake_engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda engine: object())
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyOperationalEventStore",
        lambda session_factory: event_store,
    )
    monkeypatch.setattr(
        smoke,
        "_db_lifecycle_observations",
        lambda engine, *, trace_id, event_ids: {
            "event_count": len(event_ids),
            "expected_event_count": len(event_ids),
            "expected_event_ids_persisted": True,
            "event_type_counts": {
                smoke.DISPATCH_EXECUTION_DAEMON_LIFECYCLE_EVENT_STARTED: 1,
                smoke.DISPATCH_EXECUTION_DAEMON_LIFECYCLE_EVENT_COMPLETED: 1,
            },
            "severity_counts": {"INFO": 2},
            "raw_value_leak_count": 0,
        },
    )

    def fake_cleanup(*args, **kwargs) -> dict[str, int]:
        cleanup = {"events": len(event_store.events)}
        cleanup_calls.append(cleanup)
        return cleanup

    monkeypatch.setattr(smoke, "_cleanup_smoke_events", fake_cleanup)
    env = smoke_env()

    evidence = (
        smoke.run_ag_operator_review_escalation_dispatch_daemon_process_postgres_smoke(
            env
        )
    )
    serialized = str(evidence)

    assert evidence["status"] == "PASS"
    assert evidence["smoke_schema_version"] == smoke.SCHEMA_VERSION
    assert evidence["checks"]["lifecycle_events_emitted"] is True
    assert evidence["checks"]["process_control_is_contract_only"] is True
    assert evidence["dashboard_process_summary"]["new_tables_required"] is False
    assert evidence["process_control_summary"]["action"] == "status_probe"
    assert evidence["cleanup"]["events"] == 2
    assert len(cleanup_calls) == 1
    assert fake_engine.disposed is True
    assert env[smoke.DATABASE_ENV] not in serialized
    assert smoke.RAW_PROCESS_SECRET not in serialized
    assert "secret" not in evidence["redacted_database_url"]
    assert "process_postgres_smoke=pass" in smoke.summary_line(evidence)


def test_dispatch_daemon_process_postgres_smoke_reports_failed_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = FakeEngine()
    event_store = InMemoryOperationalEventStore()
    monkeypatch.setattr(smoke, "run_service_migrations", _migration_result)
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: fake_engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda engine: object())
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyOperationalEventStore",
        lambda session_factory: event_store,
    )
    monkeypatch.setattr(
        smoke,
        "_db_lifecycle_observations",
        lambda engine, *, trace_id, event_ids: {
            "event_count": 1,
            "expected_event_count": len(event_ids),
            "expected_event_ids_persisted": False,
            "event_type_counts": {},
            "severity_counts": {},
            "raw_value_leak_count": 0,
        },
    )
    monkeypatch.setattr(
        smoke,
        "_cleanup_smoke_events",
        lambda *args, **kwargs: {"events": 2},
    )

    evidence = (
        smoke.run_ag_operator_review_escalation_dispatch_daemon_process_postgres_smoke(
            smoke_env()
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "checks_failed"
    assert evidence["checks"]["db_rows_persisted"] is False
    assert fake_engine.disposed is True


def test_dispatch_daemon_process_postgres_smoke_lifecycle_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = FakeEngine()
    monkeypatch.setattr(smoke, "run_service_migrations", _migration_result)
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: fake_engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda engine: object())
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyOperationalEventStore",
        lambda session_factory: object(),
    )
    monkeypatch.setattr(
        smoke,
        "execute_dispatch_execution_daemon_cli",
        lambda *args, **kwargs: {
            "lifecycle_events": [
                {"ok": False, "error_code": "emit_failed"},
            ]
        },
    )
    monkeypatch.setattr(
        smoke,
        "_cleanup_smoke_events",
        lambda *args, **kwargs: {"events": 0},
    )

    evidence = (
        smoke.run_ag_operator_review_escalation_dispatch_daemon_process_postgres_smoke(
            smoke_env()
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "smoke_execution_failed"
    assert "emit_failed" in evidence["detail"]
    assert fake_engine.disposed is True


def test_dispatch_daemon_process_postgres_smoke_lifecycle_shape_guards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "execute_dispatch_execution_daemon_cli",
        lambda *args, **kwargs: {"lifecycle_events": object()},
    )

    with pytest.raises(ValueError, match="not a list"):
        smoke._emit_process_lifecycle_events(
            InMemoryOperationalEventStore(),
            request_id="request-0778",
            trace_id="trace-0778",
        )

    monkeypatch.setattr(
        smoke,
        "execute_dispatch_execution_daemon_cli",
        lambda *args, **kwargs: {
            "lifecycle_events": [{"ok": True, "event_id": "event-1"}]
        },
    )

    with pytest.raises(ValueError, match="count mismatch"):
        smoke._emit_process_lifecycle_events(
            InMemoryOperationalEventStore(),
            request_id="request-0778",
            trace_id="trace-0778",
        )


def test_dispatch_daemon_process_postgres_smoke_main(monkeypatch, capsys) -> None:
    monkeypatch.setattr(smoke, "load_env_file", lambda *_args: None)
    monkeypatch.setattr(
        smoke,
        "run_ag_operator_review_escalation_dispatch_daemon_process_postgres_smoke",
        lambda: {"status": "PASS", "cleanup": {}, "observations": {}},
    )

    assert smoke.main(["--summary"]) == 0
    assert "process_postgres_smoke=pass" in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_ag_operator_review_escalation_dispatch_daemon_process_postgres_smoke",
        lambda: {"status": "FAIL", "failure_code": "boom"},
    )
    assert smoke.main([]) == 1
    assert '"failure_code": "boom"' in capsys.readouterr().out


def test_dispatch_daemon_process_postgres_smoke_redaction_failure() -> None:
    with pytest.raises(ValueError):
        smoke.assert_smoke_evidence_redacted(
            smoke.RAW_PROCESS_SECRET,
            {},
        )

    assert "process_postgres_smoke=fail failure=boom" in smoke.summary_line(
        {"status": "FAIL", "failure_code": "boom"}
    )


def test_dispatch_daemon_process_postgres_smoke_db_helpers() -> None:
    engine = FakeSqlEngine(
        rows=[
            {
                "event_id": "event-1",
                "event_type": smoke.DISPATCH_EXECUTION_DAEMON_LIFECYCLE_EVENT_STARTED,
                "severity": "INFO",
                "details_text": "{}",
            },
            {
                "event_id": "event-2",
                "event_type": smoke.DISPATCH_EXECUTION_DAEMON_LIFECYCLE_EVENT_COMPLETED,
                "severity": "INFO",
                "details_text": smoke.RAW_PROCESS_SECRET,
            },
        ],
        rowcount=2,
    )

    observations = smoke._db_lifecycle_observations(
        engine,
        trace_id="trace-0778",
        event_ids=["event-1", "event-2", "event-3"],
    )
    cleanup = smoke._cleanup_smoke_events(engine, trace_id="trace-0778")

    assert observations["event_count"] == 2
    assert observations["expected_event_count"] == 3
    assert observations["expected_event_ids_persisted"] is False
    assert observations["event_type_counts"] == {
        smoke.DISPATCH_EXECUTION_DAEMON_LIFECYCLE_EVENT_STARTED: 1,
        smoke.DISPATCH_EXECUTION_DAEMON_LIFECYCLE_EVENT_COMPLETED: 1,
    }
    assert observations["severity_counts"] == {"INFO": 2}
    assert observations["raw_value_leak_count"] == 1
    assert cleanup == {"events": 2}
    assert len(engine.connections) == 2


def _migration_result(*args, **kwargs) -> SimpleNamespace:
    return SimpleNamespace(
        service_id=smoke.SERVICE_ID,
        planned=("0778",),
        applied=(),
        skipped=("0778",),
    )


class FakeMappings:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def mappings(self) -> FakeMappings:
        return self

    def __iter__(self):
        return iter(self._rows)


class FakeSqlConnection:
    def __init__(self, rows: list[dict[str, object]], rowcount: int) -> None:
        self.rows = rows
        self.rowcount = rowcount
        self.statements: list[object] = []

    def execute(self, statement, params):
        self.statements.append((statement, params))
        if "SELECT" in str(statement):
            return FakeMappings(self.rows)
        return SimpleNamespace(rowcount=self.rowcount)


class FakeBegin:
    def __init__(self, connection: FakeSqlConnection) -> None:
        self.connection = connection

    def __enter__(self) -> FakeSqlConnection:
        return self.connection

    def __exit__(self, exc_type, exc, traceback) -> bool:
        return False


class FakeSqlEngine:
    def __init__(self, *, rows: list[dict[str, object]], rowcount: int) -> None:
        self.rows = rows
        self.rowcount = rowcount
        self.connections: list[FakeSqlConnection] = []

    def begin(self) -> FakeBegin:
        connection = FakeSqlConnection(self.rows, self.rowcount)
        self.connections.append(connection)
        return FakeBegin(connection)
