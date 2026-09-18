from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any

import pytest

import run_ag_recovery_notification_postgres_smoke as smoke
from nex_ag.operator_review_liveness_ack import (
    OperatorReviewLivenessAckStateStore,
    acknowledgement_key_for_liveness,
)
from run_migrations import MigrationError


class FakeUrl:
    database = "nex_ag_test"

    def get_backend_name(self) -> str:
        return "postgresql"


class FakeEngine:
    def __init__(self, row: dict[str, object] | None = None) -> None:
        self.url = FakeUrl()
        self.row = row or {}
        self.disposed = False

    def begin(self):
        return nullcontext(FakeConnection(self.row))

    def dispose(self) -> None:
        self.disposed = True


class FakeConnection:
    def __init__(self, row: dict[str, object]) -> None:
        self.row = row

    def execute(self, _statement: object, _params: object):
        return FakeResult(self.row)


class FakeResult:
    def __init__(self, row: dict[str, object]) -> None:
        self.row = row

    def mappings(self):
        return self

    def one(self) -> dict[str, object]:
        return self.row


def smoke_env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        smoke.DATABASE_ENV: (
            "postgresql+psycopg://nex_ag_user:secret@127.0.0.1:5432/"
            "nex_ag_test"
        ),
    }


def migration_result() -> SimpleNamespace:
    return SimpleNamespace(
        service_id=smoke.SERVICE_ID,
        planned=("0802",),
        applied=(),
        skipped=("0802",),
    )


def test_recovery_notification_postgres_smoke_skips_without_opt_in() -> None:
    evidence = smoke.run_ag_recovery_notification_postgres_smoke({})

    assert evidence["status"] == "SKIPPED"
    assert smoke.SMOKE_ENV in evidence["skip_reason"]
    assert "postgres_smoke=skipped" in smoke.summary_line(evidence)


def test_recovery_notification_postgres_smoke_requires_database_url() -> None:
    evidence = smoke.run_ag_recovery_notification_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "database_url_missing"


def test_recovery_notification_postgres_smoke_redacts_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = smoke_env()
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            MigrationError(f"cannot connect {env[smoke.DATABASE_ENV]}")
        ),
    )

    evidence = smoke.run_ag_recovery_notification_postgres_smoke(env)

    assert evidence["failure_code"] == "migration_failed"
    assert env[smoke.DATABASE_ENV] not in evidence["detail"]


@pytest.mark.parametrize(
    ("runtime_check", "deleted_rows", "expected_status"),
    [(True, 1, "PASS"), (False, 0, "FAIL")],
)
def test_recovery_notification_postgres_smoke_orchestrates_result(
    monkeypatch: pytest.MonkeyPatch,
    runtime_check: bool,
    deleted_rows: int,
    expected_status: str,
) -> None:
    engine = FakeEngine()
    store = object()
    evidence = {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "PENDING",
        "checks": {"runtime": runtime_check},
    }
    monkeypatch.setattr(smoke, "run_service_migrations", lambda *_a, **_k: migration_result())
    monkeypatch.setattr(smoke, "build_engine", lambda _url: engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda _engine: object())
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyOperatorReviewLivenessAckStateStore",
        lambda _factory: store,
    )
    monkeypatch.setattr(
        smoke,
        "_execute_smoke",
        lambda *_args, **_kwargs: evidence,
    )
    monkeypatch.setattr(
        smoke,
        "_cleanup_owned_state",
        lambda *_args, **_kwargs: {
            "deleted_state_rows": deleted_rows,
            "remaining_state_rows": 0,
        },
    )

    result = smoke.run_ag_recovery_notification_postgres_smoke(smoke_env())

    assert result["status"] == expected_status
    assert engine.disposed is True


def test_recovery_notification_postgres_smoke_cleans_after_execution_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = FakeEngine()
    store = object()
    cleanup: list[str] = []
    monkeypatch.setattr(smoke, "run_service_migrations", lambda *_a, **_k: migration_result())
    monkeypatch.setattr(smoke, "build_engine", lambda _url: engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda _engine: object())
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyOperatorReviewLivenessAckStateStore",
        lambda _factory: store,
    )

    def fail(*_args: object, **_kwargs: object):
        raise RuntimeError("private runtime failure")

    monkeypatch.setattr(smoke, "_execute_smoke", fail)
    monkeypatch.setattr(
        smoke,
        "_cleanup_owned_state",
        lambda *_args, **_kwargs: cleanup.append("called"),
    )

    result = smoke.run_ag_recovery_notification_postgres_smoke(smoke_env())

    assert result["failure_code"] == "smoke_execution_failed"
    assert cleanup == ["called"]
    assert engine.disposed is True


def test_recovery_notification_postgres_smoke_handles_engine_creation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smoke, "run_service_migrations", lambda *_a, **_k: migration_result())
    monkeypatch.setattr(
        smoke,
        "build_engine",
        lambda _url: (_ for _ in ()).throw(ValueError("bad database url")),
    )

    result = smoke.run_ag_recovery_notification_postgres_smoke(smoke_env())

    assert result["failure_code"] == "smoke_execution_failed"
    assert result["detail"] == "bad database url"


def test_execute_smoke_builds_suppressed_read_only_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = FakeEngine()
    store = OperatorReviewLivenessAckStateStore()
    observation = {
        "backend": "postgresql",
        "database": "nex_ag_test",
        "ack_state_table_present": True,
        "dispatch_table_present": True,
        "event_table_present": True,
        "row_count": 1,
        "state_status": "SUPPRESSED",
        "row_fingerprint": "same-fingerprint",
        "dispatch_count": 0,
        "event_count": 0,
    }
    monkeypatch.setattr(
        smoke,
        "_database_observation",
        lambda *_args, **_kwargs: dict(observation),
    )
    monkeypatch.setattr(
        smoke,
        "_invoke_preview",
        lambda *_args, **_kwargs: {
            "unauthorized_status": 401,
            "status_code": 200,
            "payload": {
                "plan_status": "SUPPRESSED",
                "decision": {
                    "decision_status": "SUPPRESSED",
                    "effective_ack_state": "SUPPRESSED",
                    "reason_codes": ["active_suppression"],
                },
                "delivery": {
                    "performed": False,
                    "provider_invocation_performed": False,
                },
            },
        },
    )

    state_id = "recovery-notification-smoke-0838-unit"
    evidence = smoke._execute_smoke(
        engine,
        store,
        state_id=state_id,
        migration=migration_result(),
        database_url=smoke_env()[smoke.DATABASE_ENV],
    )

    assert all(evidence["checks"].values())
    assert evidence["route"]["plan_status"] == "SUPPRESSED"
    assert store.get(state_id) is not None


def test_invoke_preview_uses_protected_route_and_persisted_state() -> None:
    store = OperatorReviewLivenessAckStateStore()
    worker_id = "ag-recovery-notification-smoke-unit"
    state_id = "recovery-notification-smoke-unit"
    acknowledgement_key = acknowledgement_key_for_liveness(
        service_id=smoke.SERVICE_ID,
        worker_id=worker_id,
        liveness_status="MISSING",
    )
    store.save(
        smoke._smoke_state(
            state_id=state_id,
            worker_id=worker_id,
            acknowledgement_key=acknowledgement_key,
        )
    )

    result = smoke._invoke_preview(
        store,
        worker_id=worker_id,
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
    )

    assert result["unauthorized_status"] == 401
    assert result["status_code"] == 200
    assert result["payload"]["plan_status"] == "SUPPRESSED"


def test_invoke_preview_rejects_non_success_response() -> None:
    with pytest.raises(ValueError, match="HTTP 400"):
        smoke._invoke_preview(
            OperatorReviewLivenessAckStateStore(),
            worker_id=" ",
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        )


def test_invoke_preview_rejects_non_object_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        status_code = 200

        def json(self) -> list[object]:
            return []

    class FakeClient:
        def __init__(self, _app: object) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def get(self, *_args: object, **_kwargs: object) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr(smoke, "TestClient", FakeClient)

    with pytest.raises(ValueError, match="must return an object"):
        smoke._invoke_preview(
            OperatorReviewLivenessAckStateStore(),
            worker_id="worker-0838",
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        )


def test_database_observation_and_cleanup_helpers() -> None:
    engine = FakeEngine(
        {
            "database_name": "nex_ag_test",
            "ack_state_table": "public.ag_op_review_ack_state",
            "dispatch_table": "public.ag_op_esc_dispatches",
            "event_table": "public.service_operational_events",
            "row_count": 1,
            "state_status": "SUPPRESSED",
            "row_fingerprint": "abc",
            "dispatch_count": 0,
            "event_count": 0,
        }
    )
    observation = smoke._database_observation(
        engine,
        state_id="state-0838",
        trace_id="a" * 32,
    )
    store = OperatorReviewLivenessAckStateStore()
    state = smoke._smoke_state(
        state_id="state-0838",
        worker_id="worker-0838",
        acknowledgement_key="nex-ag:worker-0838:missing",
    )
    store.save(state)

    cleanup = smoke._cleanup_owned_state(store, state_id="state-0838")

    assert observation["backend"] == "postgresql"
    assert observation["ack_state_table_present"] is True
    assert observation["dispatch_table_present"] is True
    assert cleanup == {"deleted_state_rows": 1, "remaining_state_rows": 0}


def test_smoke_helpers_redaction_and_summary() -> None:
    env = smoke_env()
    assert smoke._mapping([]) == {}
    assert smoke._regclass_matches("public.table", "table") is True
    assert smoke._engine_backend(object()) == "unknown"
    assert smoke._engine_database(object()) is None
    assert smoke._failure("bad", "detail")["status"] == "FAIL"
    assert "postgres_smoke=fail" in smoke.summary_line(
        {"status": "FAIL", "failure_code": "bad"}
    )
    with pytest.raises(ValueError, match="sensitive"):
        smoke.assert_smoke_evidence_redacted(env[smoke.DATABASE_ENV], env)
    smoke.assert_smoke_evidence_redacted("safe", env)

    passed = {
        "status": "PASS",
        "database": {
            "database": "nex_ag_test",
            "backend": "postgresql",
            "dispatch_count": 0,
            "event_count": 0,
        },
        "route": {"plan_status": "SUPPRESSED"},
        "cleanup": {"deleted_state_rows": 1},
    }
    assert "plan=SUPPRESSED" in smoke.summary_line(passed)


def test_main_prints_summary_and_sets_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(smoke, "load_env_file", lambda _path: None)
    monkeypatch.setattr(
        smoke,
        "run_ag_recovery_notification_postgres_smoke",
        lambda: {"status": "SKIPPED"},
    )
    assert smoke.main(["--summary"]) == 0
    assert "postgres_smoke=skipped" in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_ag_recovery_notification_postgres_smoke",
        lambda: {"status": "FAIL", "failure_code": "test"},
    )
    assert smoke.main([]) == 1
    assert '"failure_code": "test"' in capsys.readouterr().out
