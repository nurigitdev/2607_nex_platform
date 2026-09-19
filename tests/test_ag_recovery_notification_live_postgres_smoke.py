from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any

import pytest

import run_ag_recovery_notification_live_postgres_smoke as smoke
from nex_ag.operator_review_cases import (
    OperatorReviewCaseService,
    OperatorReviewCaseStore,
    OperatorReviewEscalationDispatchStore,
    OperatorReviewEscalationStore,
)
from run_ag_recovery_notification_live_loopback_smoke import (
    _RecoveryNotificationLoopbackServer,
)
from run_migrations import MigrationError


class FakeUrl:
    database = "nex_ag_test"

    def get_backend_name(self) -> str:
        return "postgresql"


class FakeEngine:
    def __init__(self) -> None:
        self.url = FakeUrl()
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


class FakeServer:
    endpoint_url = "http://127.0.0.1:34567/recovery-notification"

    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


def _env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        smoke.DATABASE_ENV: (
            "postgresql+psycopg://nex_ag_user:secret@127.0.0.1:5432/"
            "nex_ag_test"
        ),
    }


def _migration() -> SimpleNamespace:
    return SimpleNamespace(
        service_id=smoke.SERVICE_ID,
        planned=("0001",),
        applied=(),
        skipped=("0001",),
    )


def _context() -> dict[str, str]:
    return {
        "case_id": "case-0858-unit",
        "target_id": "target-0858-unit",
        "request_id": "request-0858-unit",
        "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
        "worker_id": "worker-0858-unit",
        "case_idempotency_key": "case-idem-0858-unit",
        "escalation_idempotency_key": "escalation-idem-0858-unit",
        "dispatch_idempotency_key": "dispatch-idem-0858-unit",
    }


def _observation(*, pending: bool) -> dict[str, Any]:
    return {
        "backend": "postgresql",
        "database": "nex_ag_test",
        "tables_present": {
            "ag_op_cases": True,
            "ag_op_escalations": True,
            "ag_op_esc_dispatches": True,
        },
        "case_count": 1,
        "escalation_count": 1,
        "dispatch_count": 1,
        "pending_count": 1 if pending else 0,
        "succeeded_count": 0 if pending else 1,
        "live_http_metadata_count": 0 if pending else 1,
        "raw_value_leak_count": 0,
    }


def test_smoke_skips_without_opt_in_and_requires_database_url() -> None:
    skipped = smoke.run_ag_recovery_notification_live_postgres_smoke({})
    missing = smoke.run_ag_recovery_notification_live_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )

    assert skipped["status"] == "SKIPPED"
    assert smoke.SMOKE_ENV in skipped["skip_reason"]
    assert "smoke=skipped" in smoke.summary_line(skipped)
    assert missing["failure_code"] == "database_url_missing"


def test_smoke_redacts_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = _env()
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            MigrationError(f"cannot connect {env[smoke.DATABASE_ENV]}")
        ),
    )

    evidence = smoke.run_ag_recovery_notification_live_postgres_smoke(env)

    assert evidence["failure_code"] == "migration_failed"
    assert env[smoke.DATABASE_ENV] not in evidence["detail"]


@pytest.mark.parametrize(
    ("runtime_check", "remaining_rows", "expected_status"),
    [(True, 0, "PASS"), (False, 1, "FAIL")],
)
def test_smoke_orchestrates_server_database_and_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    runtime_check: bool,
    remaining_rows: int,
    expected_status: str,
) -> None:
    engine = FakeEngine()
    server = FakeServer()
    monkeypatch.setattr(smoke, "run_service_migrations", lambda *_a, **_k: _migration())
    monkeypatch.setattr(smoke, "_RecoveryNotificationLoopbackServer", lambda: server)
    monkeypatch.setattr(smoke, "build_engine", lambda _url: engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda _engine: object())
    monkeypatch.setattr(smoke, "SqlAlchemyOperatorReviewCaseStore", lambda _f: object())
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyOperatorReviewEscalationStore",
        lambda _f: object(),
    )
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyOperatorReviewEscalationDispatchStore",
        lambda _f: object(),
    )
    monkeypatch.setattr(smoke, "OperatorReviewCaseService", lambda *_a, **_k: object())
    monkeypatch.setattr(
        smoke,
        "_execute_smoke",
        lambda *_a, **_k: {
            "smoke_schema_version": smoke.SCHEMA_VERSION,
            "status": "PENDING",
            "owned_context": _context(),
            "checks": {"runtime": runtime_check},
        },
    )
    monkeypatch.setattr(
        smoke,
        "_cleanup_owned_rows",
        lambda *_a, **_k: {
            "cases": 1,
            "escalations": 1,
            "dispatches": 1,
            "remaining_rows": remaining_rows,
        },
    )

    evidence = smoke.run_ag_recovery_notification_live_postgres_smoke(_env())

    assert evidence["status"] == expected_status
    assert server.started is True
    assert server.stopped is True
    assert engine.disposed is True


def test_smoke_cleans_up_after_execution_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = FakeEngine()
    server = FakeServer()
    cleanup_calls: list[dict[str, str]] = []
    monkeypatch.setattr(smoke, "run_service_migrations", lambda *_a, **_k: _migration())
    monkeypatch.setattr(smoke, "_RecoveryNotificationLoopbackServer", lambda: server)
    monkeypatch.setattr(smoke, "build_engine", lambda _url: engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda _engine: object())
    monkeypatch.setattr(smoke, "SqlAlchemyOperatorReviewCaseStore", lambda _f: object())
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyOperatorReviewEscalationStore",
        lambda _f: object(),
    )
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyOperatorReviewEscalationDispatchStore",
        lambda _f: object(),
    )
    monkeypatch.setattr(smoke, "OperatorReviewCaseService", lambda *_a, **_k: object())
    monkeypatch.setattr(
        smoke,
        "_execute_smoke",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("private failure")),
    )
    monkeypatch.setattr(
        smoke,
        "_cleanup_owned_rows",
        lambda _engine, *, context: cleanup_calls.append(dict(context)) or {},
    )

    evidence = smoke.run_ag_recovery_notification_live_postgres_smoke(_env())

    assert evidence["failure_code"] == "smoke_execution_failed"
    assert len(cleanup_calls) == 1
    assert server.stopped is True
    assert engine.disposed is True


def test_smoke_handles_server_creation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smoke, "run_service_migrations", lambda *_a, **_k: _migration())
    monkeypatch.setattr(
        smoke,
        "_RecoveryNotificationLoopbackServer",
        lambda: (_ for _ in ()).throw(OSError("bind unavailable")),
    )

    evidence = smoke.run_ag_recovery_notification_live_postgres_smoke(_env())

    assert evidence["failure_code"] == "smoke_execution_failed"


def test_execute_smoke_persists_and_executes_live_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = FakeEngine()
    case_store = OperatorReviewCaseStore()
    escalation_store = OperatorReviewEscalationStore()
    dispatch_store = OperatorReviewEscalationDispatchStore()
    service = OperatorReviewCaseService(
        case_store,
        escalation_store=escalation_store,
        dispatch_store=dispatch_store,
    )
    observations = [_observation(pending=True), _observation(pending=False)]
    monkeypatch.setattr(
        smoke,
        "_database_observation",
        lambda *_a, **_k: observations.pop(0),
    )
    server = _RecoveryNotificationLoopbackServer()
    server.start()
    try:
        evidence = smoke._execute_smoke(
            engine,
            service,
            case_store=case_store,
            escalation_store=escalation_store,
            dispatch_store=dispatch_store,
            server=server,
            migration=_migration(),
            database_url=_env()[smoke.DATABASE_ENV],
            context=_context(),
        )
    finally:
        server.stop()

    assert all(evidence["checks"].values())
    assert evidence["execution"]["provider_mode"] == "live_http"
    assert evidence["execution"]["http_status_code"] == 202
    assert evidence["loopback"]["request_count"] == 1


def test_database_observation_reads_live_http_metadata() -> None:
    class Result:
        def __init__(self, value: object) -> None:
            self.value = value

        def scalar(self) -> object:
            return self.value

        def mappings(self):
            return self

        def one(self) -> object:
            return self.value

    class Connection:
        def __init__(self) -> None:
            self.results = iter(
                [
                    Result("public.ag_op_cases"),
                    Result("public.ag_op_escalations"),
                    Result("public.ag_op_esc_dispatches"),
                    Result(
                        {
                            "database_name": "nex_ag_test",
                            "case_count": 1,
                            "escalation_count": 1,
                            "dispatch_count": 1,
                            "pending_count": 0,
                            "succeeded_count": 1,
                            "live_http_metadata_count": 1,
                            "raw_value_leak_count": 0,
                        }
                    ),
                ]
            )

        def execute(self, *_args: object, **_kwargs: object) -> Result:
            return next(self.results)

    class Engine(FakeEngine):
        def connect(self):
            return nullcontext(Connection())

    observation = smoke._database_observation(Engine(), context=_context())

    assert observation["database"] == "nex_ag_test"
    assert all(observation["tables_present"].values())
    assert observation["live_http_metadata_count"] == 1


def test_evidence_redaction_rejects_each_sensitive_value() -> None:
    env = _env()
    endpoint = FakeServer.endpoint_url
    forbidden = (
        env[smoke.DATABASE_ENV],
        smoke.LOOPBACK_TOKEN,
        endpoint,
        "/recovery-notification",
        smoke.RAW_IDEMPOTENCY_KEY,
        "Authorization: Bearer",
    )

    for value in forbidden:
        with pytest.raises(ValueError, match="contains a secret"):
            smoke.assert_smoke_evidence_redacted(
                f"evidence={value}",
                env,
                endpoint_url=endpoint,
            )
    smoke.assert_smoke_evidence_redacted("safe", env, endpoint_url=endpoint)


def test_summary_line_reports_pass_and_failure() -> None:
    passed = smoke.summary_line(
        {
            "status": "PASS",
            "execution": {"provider_mode": "live_http", "http_status_code": 202},
            "after": {"database": "nex_ag_test"},
            "loopback": {"request_count": 1},
            "cleanup": {"remaining_rows": 0},
        }
    )
    failed = smoke.summary_line({"status": "FAIL", "failure_code": "checks_failed"})

    assert "smoke=pass" in passed
    assert "database=nex_ag_test" in passed
    assert "provider=live_http" in passed
    assert "smoke=fail" in failed


def test_main_prints_summary_and_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(smoke, "load_env_file", lambda _path: {})
    monkeypatch.setattr(
        smoke,
        "run_ag_recovery_notification_live_postgres_smoke",
        lambda: {"status": "SKIPPED", "skip_reason": "disabled"},
    )

    assert smoke.main(["--summary", "--env-file", "test.env"]) == 0
    assert "smoke=skipped" in capsys.readouterr().out
    assert smoke.main(["--env-file", "test.env"]) == 0
    assert '"status": "SKIPPED"' in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_ag_recovery_notification_live_postgres_smoke",
        lambda: {"status": "FAIL", "failure_code": "test"},
    )
    assert smoke.main([]) == 1
