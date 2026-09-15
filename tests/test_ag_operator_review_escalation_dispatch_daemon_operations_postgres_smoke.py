from __future__ import annotations

from types import SimpleNamespace

import pytest

import run_ag_operator_review_escalation_dispatch_daemon_operations_postgres_smoke as smoke
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


def test_dispatch_daemon_operations_postgres_smoke_skips_without_opt_in() -> None:
    evidence = (
        smoke.run_ag_operator_review_escalation_dispatch_daemon_operations_postgres_smoke(
            {}
        )
    )

    assert evidence["status"] == "SKIPPED"
    assert smoke.SMOKE_ENV in evidence["skip_reason"]
    assert "skipped" in smoke.summary_line(evidence)


def test_dispatch_daemon_operations_postgres_smoke_requires_database_url() -> None:
    evidence = (
        smoke.run_ag_operator_review_escalation_dispatch_daemon_operations_postgres_smoke(
            {smoke.SMOKE_ENV: "1"}
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "database_url_missing"
    assert "failure=database_url_missing" in smoke.summary_line(evidence)


def test_dispatch_daemon_operations_postgres_smoke_reports_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(MigrationError("bad migration")),
    )

    evidence = (
        smoke.run_ag_operator_review_escalation_dispatch_daemon_operations_postgres_smoke(
            smoke_env()
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "migration_failed"
    assert "bad migration" in evidence["detail"]


def test_dispatch_daemon_operations_postgres_smoke_reports_engine_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smoke, "run_service_migrations", _migration_result)
    monkeypatch.setattr(
        smoke,
        "build_engine",
        lambda database_url: (_ for _ in ()).throw(ValueError("bad database url")),
    )

    evidence = (
        smoke.run_ag_operator_review_escalation_dispatch_daemon_operations_postgres_smoke(
            smoke_env()
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "smoke_execution_failed"
    assert "bad database url" in evidence["detail"]


def test_dispatch_daemon_operations_postgres_smoke_success_is_redacted(
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
        "_db_event_observations",
        lambda engine, *, trace_id, event_ids: {
            "event_count": len(event_ids),
            "expected_event_count": len(event_ids),
            "expected_event_ids_persisted": True,
            "event_type_counts": {
                "ag.operator_review_dispatch_daemon.control.succeeded": 1,
                "ag.operator_review_dispatch_daemon.control.rejected": 1,
                "ag.operator_review_dispatch_daemon.control.failed": 1,
            },
            "severity_counts": {"INFO": 1, "WARNING": 1, "ERROR": 1},
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
        smoke.run_ag_operator_review_escalation_dispatch_daemon_operations_postgres_smoke(
            env
        )
    )
    serialized = str(evidence)

    assert evidence["status"] == "PASS"
    assert evidence["smoke_schema_version"] == smoke.SCHEMA_VERSION
    assert evidence["checks"]["history_has_all_events"] is True
    assert evidence["checks"]["dashboard_has_smoke_events"] is True
    assert evidence["checks"]["issue_candidate_covers_failed_rejected"] is True
    assert evidence["issue_candidate"] == {
        "rule_id": "operator_review_dispatch_daemon_control_attention_required.v1",
        "severity": "ERROR",
        "status": "FAILED",
        "count": 2,
        "failed_count": 1,
        "rejected_count": 1,
    }
    assert evidence["cleanup"]["events"] == 3
    assert len(cleanup_calls) == 2
    assert fake_engine.disposed is True
    assert env[smoke.DATABASE_ENV] not in serialized
    assert "secret" not in evidence["redacted_database_url"]
    assert smoke.RAW_REQUEST_PAYLOAD not in serialized
    assert smoke.RAW_PROVIDER_PAYLOAD not in serialized
    assert smoke.RAW_OPERATOR_COMMENT not in serialized
    assert "operations_postgres_smoke=pass" in smoke.summary_line(evidence)


def test_dispatch_daemon_operations_postgres_smoke_reports_failed_checks(
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
        "_db_event_observations",
        lambda engine, *, trace_id, event_ids: {
            "event_count": 2,
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
        lambda *args, **kwargs: {"events": 3},
    )

    evidence = (
        smoke.run_ag_operator_review_escalation_dispatch_daemon_operations_postgres_smoke(
            smoke_env()
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "checks_failed"
    assert evidence["checks"]["db_rows_persisted"] is False


def test_dispatch_daemon_operations_postgres_smoke_emit_failure(
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
        "emit_operator_review_escalation_dispatch_daemon_control_audit_event",
        lambda *args, **kwargs: SimpleNamespace(
            ok=False,
            event=None,
            error_code="emit_failed",
            detail="nope",
        ),
    )
    monkeypatch.setattr(
        smoke,
        "_cleanup_smoke_events",
        lambda *args, **kwargs: {"events": 0},
    )

    evidence = (
        smoke.run_ag_operator_review_escalation_dispatch_daemon_operations_postgres_smoke(
            smoke_env()
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "smoke_execution_failed"
    assert "emit_failed" in evidence["detail"]
    assert fake_engine.disposed is True


def test_dispatch_daemon_operations_postgres_smoke_main(monkeypatch, capsys) -> None:
    monkeypatch.setattr(smoke, "load_env_file", lambda *_args: None)
    monkeypatch.setattr(
        smoke,
        "run_ag_operator_review_escalation_dispatch_daemon_operations_postgres_smoke",
        lambda: {"status": "PASS", "cleanup": {}, "observations": {}},
    )

    assert smoke.main(["--summary"]) == 0
    assert "operations_postgres_smoke=pass" in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_ag_operator_review_escalation_dispatch_daemon_operations_postgres_smoke",
        lambda: {"status": "FAIL", "failure_code": "boom"},
    )
    assert smoke.main([]) == 1
    assert '"failure_code": "boom"' in capsys.readouterr().out


def test_dispatch_daemon_operations_postgres_smoke_redaction_failure() -> None:
    with pytest.raises(ValueError):
        smoke.assert_smoke_evidence_redacted(
            smoke.RAW_REQUEST_PAYLOAD,
            {},
            forbidden_values=(smoke.RAW_REQUEST_PAYLOAD,),
        )


def test_dispatch_daemon_operations_postgres_smoke_helpers() -> None:
    assert smoke._dispatch_daemon_issue_candidate({"issue_candidates": []}) is None
    assert smoke._control_event_ids(object()) == set()
    assert smoke._issue_candidate_summary(None) is None


def test_dispatch_daemon_operations_postgres_smoke_db_helpers() -> None:
    engine = FakeSqlEngine(
        rows=[
            {
                "event_id": "event-1",
                "event_type": "ag.operator_review_dispatch_daemon.control.failed",
                "severity": "ERROR",
                "details_text": "{}",
            },
            {
                "event_id": "event-2",
                "event_type": "ag.operator_review_dispatch_daemon.control.rejected",
                "severity": "WARNING",
                "details_text": smoke.RAW_PROVIDER_PAYLOAD,
            },
        ],
        rowcount=2,
    )

    observations = smoke._db_event_observations(
        engine,
        trace_id="trace-0768",
        event_ids=["event-1", "event-2", "event-3"],
    )
    cleanup = smoke._cleanup_smoke_events(engine, trace_id="trace-0768")

    assert observations["event_count"] == 2
    assert observations["expected_event_count"] == 3
    assert observations["expected_event_ids_persisted"] is False
    assert observations["event_type_counts"] == {
        "ag.operator_review_dispatch_daemon.control.failed": 1,
        "ag.operator_review_dispatch_daemon.control.rejected": 1,
    }
    assert observations["severity_counts"] == {"ERROR": 1, "WARNING": 1}
    assert observations["raw_value_leak_count"] == 1
    assert cleanup == {"events": 2}
    assert len(engine.connections) == 2


def _migration_result(*args, **kwargs) -> SimpleNamespace:
    return SimpleNamespace(
        service_id=smoke.SERVICE_ID,
        planned=("0768",),
        applied=(),
        skipped=("0768",),
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
