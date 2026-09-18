from __future__ import annotations

import io
import json
from typing import Any

import pytest
from nex_runtime import DatabaseConfigError

import nex_ag.liveness_ack_expiry_automation as automation
import nex_ag.liveness_ack_expiry_automation_cli as cli
from nex_ag.operator_review_liveness_ack import (
    OperatorReviewLivenessAckStateStore,
    build_operator_review_liveness_ack_state_record,
)


ENABLED_ENV = {automation.ACK_EXPIRY_AUTOMATION_ENABLED_ENV: "1"}
OBSERVED_AT = "2026-09-18T02:00:00Z"


def expired_state() -> dict[str, Any]:
    return build_operator_review_liveness_ack_state_record(
        ack_state_id="ack-cli-0825",
        acknowledgement_key="nex-ag:ack-cli-0825:stale",
        service_id="nex-ag",
        worker_id="ag-dispatch-execution-daemon",
        worker_type="operator_review_dispatch_daemon",
        liveness_status="STALE",
        action="suppress_for_ttl",
        state_status="SUPPRESSED",
        operator_ref={"operator_type": "service", "operator_id": "test-0825"},
        reason_codes=["automation_cli_test"],
        comment="must not be emitted",
        idempotency_key="secret-idempotency-key",
        requested_ttl_seconds=300,
        suppressed_until="2026-09-18T01:30:00Z",
        created_at="2026-09-18T01:00:00Z",
        updated_at="2026-09-18T01:00:00Z",
    )


def test_cli_plan_is_read_only_and_redacted() -> None:
    store = OperatorReviewLivenessAckStateStore()
    store.save(expired_state())

    result = cli.execute_liveness_ack_expiry_automation_cli(
        store,
        action="plan",
        environ=ENABLED_ENV,
        request_id="req-plan-0825",
        trace_id="trace-0825",
        observed_at=OBSERVED_AT,
    )
    serialized = json.dumps(result)

    assert result["result_status"] == "PLANNED"
    assert result["plan"]["plan_status"] == "READY"
    assert result["tick_result"] is None
    assert result["database_bound"] is False
    assert store.get("ack-cli-0825")["state_status"] == "SUPPRESSED"
    assert "must not be emitted" not in serialized
    assert "secret-idempotency-key" not in serialized


def test_cli_run_once_requires_confirmation() -> None:
    store = OperatorReviewLivenessAckStateStore()
    store.save(expired_state())

    result = cli.execute_liveness_ack_expiry_automation_cli(
        store,
        action="run-once",
        environ=ENABLED_ENV,
        request_id="req-blocked-0825",
        observed_at=OBSERVED_AT,
    )

    assert result["result_status"] == "BLOCKED"
    assert result["tick_result"]["blocked_reason"] == "confirm_tick_required"
    assert store.get("ack-cli-0825")["state_status"] == "SUPPRESSED"


def test_cli_confirmed_run_once_applies_one_tick() -> None:
    store = OperatorReviewLivenessAckStateStore()
    store.save(expired_state())

    result = cli.execute_liveness_ack_expiry_automation_cli(
        store,
        action="run_once",
        environ=ENABLED_ENV,
        request_id="req-run-0825",
        confirm_tick=True,
        observed_at=OBSERVED_AT,
    )

    assert result["result_status"] == "EXECUTED"
    assert result["tick_result"]["applied_count"] == 1
    assert store.get("ack-cli-0825")["state_status"] == "EXPIRED"


def test_cli_default_request_id_is_deterministic() -> None:
    store = OperatorReviewLivenessAckStateStore()
    first = cli.execute_liveness_ack_expiry_automation_cli(
        store,
        environ={},
        observed_at=OBSERVED_AT,
    )
    second = cli.execute_liveness_ack_expiry_automation_cli(
        store,
        environ={},
        observed_at=OBSERVED_AT,
    )

    assert first["request_id"] == second["request_id"]


def test_cli_rejects_unknown_action() -> None:
    with pytest.raises(ValueError, match="Unsupported acknowledgement"):
        cli.execute_liveness_ack_expiry_automation_cli(
            OperatorReviewLivenessAckStateStore(),
            action="forever",
            environ={},
        )


def test_runtime_store_uses_worker_pool_and_allowed_database_env() -> None:
    captured: dict[str, Any] = {}

    class FakeEngine:
        pass

    engine = FakeEngine()

    def engine_factory(database_url: str, *, pool_settings: Any) -> FakeEngine:
        captured["database_url"] = database_url
        captured["pool_settings"] = pool_settings
        return engine

    store, actual_engine = cli.build_liveness_ack_expiry_automation_runtime_store(
        database_env=cli.ACK_EXPIRY_AUTOMATION_TEST_DATABASE_ENV,
        environ={
            cli.ACK_EXPIRY_AUTOMATION_TEST_DATABASE_ENV: "sqlite+pysqlite:///:memory:"
        },
        engine_factory=engine_factory,
        session_factory_builder=lambda value: ("sessions", value),
    )

    assert actual_engine is engine
    assert captured["database_url"] == "sqlite+pysqlite:///:memory:"
    assert captured["pool_settings"].workload == "worker"
    assert store._session_factory == ("sessions", engine)


def test_runtime_store_rejects_unapproved_database_env() -> None:
    with pytest.raises(DatabaseConfigError, match="unsupported acknowledgement"):
        cli.build_liveness_ack_expiry_automation_runtime_store(
            database_env="UNSAFE_DATABASE_URL",
            environ={"UNSAFE_DATABASE_URL": "postgresql://secret"},
        )


def test_summary_line_reports_only_aggregate_state() -> None:
    result = cli.execute_liveness_ack_expiry_automation_cli(
        OperatorReviewLivenessAckStateStore(),
        environ={},
        request_id="req-summary",
        observed_at=OBSERVED_AT,
    )

    summary = cli.summary_line(result)

    assert "ag_ack_expiry_automation_cli=planned" in summary
    assert "action=plan" in summary
    assert "database_bound=False" in summary


def test_parser_defaults_to_plan_and_primary_database_env() -> None:
    args = cli.build_parser().parse_args([])

    assert args.plan is False
    assert args.run_once is False
    assert args.database_env == cli.ACK_EXPIRY_AUTOMATION_DATABASE_ENV


def test_main_disabled_plan_does_not_require_database() -> None:
    stdout = io.StringIO()

    exit_code = cli.main(["--summary"], stdout, environ={})

    assert exit_code == 0
    assert "ag_ack_expiry_automation_cli=planned" in stdout.getvalue()


def test_main_enabled_runtime_disposes_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    store = OperatorReviewLivenessAckStateStore()
    store.save(expired_state())

    class FakeEngine:
        disposed = False

        def dispose(self) -> None:
            self.disposed = True

    engine = FakeEngine()
    monkeypatch.setattr(
        cli,
        "build_liveness_ack_expiry_automation_runtime_store",
        lambda **_kwargs: (store, engine),
    )
    stdout = io.StringIO()

    exit_code = cli.main(
        ["--run-once", "--confirm-tick", "--observed-at", OBSERVED_AT],
        stdout,
        environ=ENABLED_ENV,
    )
    payload = json.loads(stdout.getvalue())

    assert exit_code == 0
    assert payload["result_status"] == "EXECUTED"
    assert engine.disposed is True


def test_main_reports_safe_database_configuration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli,
        "build_liveness_ack_expiry_automation_runtime_store",
        lambda **_kwargs: (_ for _ in ()).throw(
            DatabaseConfigError("missing database URL env NEX_AG_DATABASE_URL")
        ),
    )
    stdout = io.StringIO()

    exit_code = cli.main([], stdout, environ=ENABLED_ENV)
    payload = json.loads(stdout.getvalue())

    assert exit_code == 2
    assert payload["error_code"] == "database_configuration_invalid"
    assert payload["database_url_included"] is False
