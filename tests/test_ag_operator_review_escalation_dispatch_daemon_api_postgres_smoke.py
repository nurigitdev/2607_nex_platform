from __future__ import annotations

from types import SimpleNamespace

import pytest

import run_ag_operator_review_escalation_dispatch_daemon_api_postgres_smoke as smoke
from nex_ag.operator_review_cases import (
    OperatorReviewCaseStore,
    OperatorReviewEscalationDispatchStore,
    OperatorReviewEscalationStore,
)
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


def test_dispatch_daemon_api_postgres_smoke_skips_without_opt_in() -> None:
    evidence = (
        smoke.run_ag_operator_review_escalation_dispatch_daemon_api_postgres_smoke({})
    )

    assert evidence["status"] == "SKIPPED"
    assert smoke.SMOKE_ENV in evidence["skip_reason"]
    assert smoke.summary_line(evidence) == (
        "ag_operator_review_escalation_dispatch_daemon_api_postgres_smoke="
        f"skipped reason={smoke.SMOKE_ENV}"
    )


def test_dispatch_daemon_api_postgres_smoke_requires_database_url() -> None:
    evidence = (
        smoke.run_ag_operator_review_escalation_dispatch_daemon_api_postgres_smoke(
            {smoke.SMOKE_ENV: "1"}
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "database_url_missing"
    assert "failure=database_url_missing" in smoke.summary_line(evidence)


def test_dispatch_daemon_api_postgres_smoke_reports_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(MigrationError("bad migration")),
    )

    evidence = (
        smoke.run_ag_operator_review_escalation_dispatch_daemon_api_postgres_smoke(
            smoke_env()
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "migration_failed"
    assert "bad migration" in evidence["detail"]


def test_dispatch_daemon_api_postgres_smoke_reports_engine_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smoke, "run_service_migrations", _migration_result)
    monkeypatch.setattr(
        smoke,
        "build_engine",
        lambda database_url: (_ for _ in ()).throw(ValueError("bad database url")),
    )

    evidence = (
        smoke.run_ag_operator_review_escalation_dispatch_daemon_api_postgres_smoke(
            smoke_env()
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "smoke_execution_failed"
    assert "bad database url" in evidence["detail"]


def test_dispatch_daemon_api_postgres_smoke_success_is_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = FakeEngine()
    cleanup_calls: list[dict[str, int]] = []
    monkeypatch.setattr(smoke, "run_service_migrations", _migration_result)
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: fake_engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda engine: object())
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyOperatorReviewCaseStore",
        lambda session_factory: OperatorReviewCaseStore(),
    )
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyOperatorReviewEscalationStore",
        lambda session_factory: OperatorReviewEscalationStore(),
    )
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyOperatorReviewEscalationDispatchStore",
        lambda session_factory: OperatorReviewEscalationDispatchStore(),
    )
    monkeypatch.setattr(smoke, "_db_observations", lambda *args, **kwargs: _observations())

    def fake_cleanup(*args, **kwargs) -> dict[str, int]:
        cleanup = {"cases": 1, "escalations": 1, "dispatches": 1, "events": 0}
        cleanup_calls.append(cleanup)
        return cleanup

    monkeypatch.setattr(smoke, "_cleanup_smoke_rows", fake_cleanup)
    env = smoke_env()

    evidence = (
        smoke.run_ag_operator_review_escalation_dispatch_daemon_api_postgres_smoke(
            env
        )
    )
    serialized = str(evidence)

    assert evidence["status"] == "PASS"
    assert evidence["checks"]["tick_plan_http_ok"] is True
    assert evidence["checks"]["tick_once_http_ok"] is True
    assert evidence["checks"]["tick_once_mutated"] is True
    assert evidence["checks"]["final_dispatch_succeeded"] is True
    assert evidence["api"]["tick_once_status_code"] == 200
    assert evidence["tick_once_summary"]["mutation_performed"] is True
    assert evidence["cleanup"] == {
        "cases": 1,
        "escalations": 1,
        "dispatches": 1,
        "events": 0,
    }
    assert len(cleanup_calls) == 3
    assert fake_engine.disposed is True
    assert env[smoke.DATABASE_ENV] not in serialized
    assert "secret" not in evidence["redacted_database_url"]
    assert "dispatch-idem" not in serialized
    assert smoke.summary_line(evidence).startswith(
        "ag_operator_review_escalation_dispatch_daemon_api_postgres_smoke=pass"
    )


def test_dispatch_daemon_api_postgres_smoke_reports_failed_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = FakeEngine()
    monkeypatch.setattr(smoke, "run_service_migrations", _migration_result)
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: fake_engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda engine: object())
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyOperatorReviewCaseStore",
        lambda session_factory: OperatorReviewCaseStore(),
    )
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyOperatorReviewEscalationStore",
        lambda session_factory: OperatorReviewEscalationStore(),
    )
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyOperatorReviewEscalationDispatchStore",
        lambda session_factory: OperatorReviewEscalationDispatchStore(),
    )
    monkeypatch.setattr(
        smoke,
        "_db_observations",
        lambda *args, **kwargs: {**_observations(), "execution_metadata_count": 0},
    )
    monkeypatch.setattr(
        smoke,
        "_cleanup_smoke_rows",
        lambda *args, **kwargs: {
            "cases": 1,
            "escalations": 1,
            "dispatches": 1,
            "events": 0,
        },
    )

    evidence = (
        smoke.run_ag_operator_review_escalation_dispatch_daemon_api_postgres_smoke(
            smoke_env()
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "checks_failed"
    assert evidence["checks"]["execution_metadata_persisted"] is False


def test_dispatch_daemon_api_postgres_smoke_main(monkeypatch, capsys) -> None:
    monkeypatch.setattr(smoke, "load_env_file", lambda *_args: None)
    monkeypatch.setattr(
        smoke,
        "run_ag_operator_review_escalation_dispatch_daemon_api_postgres_smoke",
        lambda: {"status": "PASS", "cleanup": {}, "observations": {}},
    )

    assert smoke.main(["--summary"]) == 0
    assert "daemon_api_postgres_smoke=pass" in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_ag_operator_review_escalation_dispatch_daemon_api_postgres_smoke",
        lambda: {"status": "FAIL", "failure_code": "boom"},
    )
    assert smoke.main([]) == 1
    assert '"failure_code": "boom"' in capsys.readouterr().out


def test_created_dispatch_id_defaults_when_record_is_missing() -> None:
    assert smoke._created_dispatch_id({}) == ""


def _migration_result(*args, **kwargs) -> SimpleNamespace:
    return SimpleNamespace(
        service_id=smoke.SERVICE_ID,
        planned=("0754",),
        applied=(),
        skipped=("0754",),
    )


def _observations() -> dict[str, object]:
    return {
        "tables_present": {
            "ag_op_cases": True,
            "ag_op_escalations": True,
            "ag_op_esc_dispatches": True,
            "service_operational_events": True,
        },
        "case_count": 1,
        "escalation_count": 1,
        "dispatch_count": 1,
        "succeeded_count": 1,
        "execution_metadata_count": 1,
        "last_action_succeed_count": 1,
        "raw_value_leak_count": 0,
        "idempotency_leak_count": 0,
    }
