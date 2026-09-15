from __future__ import annotations

import json
from io import StringIO

import pytest

from nex_ag.operator_review_dispatch_daemon import (
    DISPATCH_EXECUTION_DAEMON_CLI_PLAN_SCHEMA_VERSION,
    DISPATCH_EXECUTION_DAEMON_CLI_RESULT_SCHEMA_VERSION,
    build_dispatch_execution_daemon_cli_plan,
    execute_dispatch_execution_daemon_cli,
    main,
    summary_line,
    _default_request_id,
    _normalize_cli_action,
    _utc_now,
)
from nex_ag.operator_review_dispatch_execution import (
    DISPATCH_EXECUTION_DAEMON_ENABLED_ENV,
    assert_dispatch_execution_result_redacted,
)


def test_dispatch_daemon_cli_plan_defaults_to_safe_disabled() -> None:
    plan = build_dispatch_execution_daemon_cli_plan(
        environ={},
        started_at="2026-09-15T11:00:00Z",
    )

    assert plan["daemon_cli_plan_schema_version"] == (
        DISPATCH_EXECUTION_DAEMON_CLI_PLAN_SCHEMA_VERSION
    )
    assert plan["action"] == "plan"
    assert plan["command_mode"] == "bounded_loop"
    assert plan["will_execute"] is False
    assert plan["confirm_tick"] is False
    assert plan["dry_run"] is True
    assert plan["policy"]["enabled"] is False
    assert plan["loop_policy"]["new_tables_required"] is False
    assert plan["process_metadata"]["process_status"] == "DISABLED"
    assert plan["new_tables_required"] is False
    assert "postgresql://" not in json.dumps(plan)
    assert_dispatch_execution_result_redacted(plan)


def test_dispatch_daemon_cli_plan_honors_run_once_overrides() -> None:
    plan = build_dispatch_execution_daemon_cli_plan(
        action="run-once",
        environ={DISPATCH_EXECUTION_DAEMON_ENABLED_ENV: "1"},
        request_id="request-0774",
        trace_id="trace-0774",
        worker_id="worker-0774",
        confirm_tick=True,
        dry_run=False,
        cycle_limit=2,
        started_at="2026-09-15T11:01:00Z",
    )

    assert plan["action"] == "run_once"
    assert plan["will_execute"] is True
    assert plan["request_id"] == "request-0774"
    assert plan["trace_id"] == "trace-0774"
    assert plan["worker_id"] == "worker-0774"
    assert plan["confirm_tick"] is True
    assert plan["dry_run"] is False
    assert plan["loop_policy"]["cycle_limit"] == 2
    assert plan["process_metadata"]["process_status"] == "READY"


def test_dispatch_daemon_cli_execute_plan_only() -> None:
    result = execute_dispatch_execution_daemon_cli(
        action="plan",
        environ={},
        started_at="2026-09-15T11:02:00Z",
    )

    assert result["daemon_cli_result_schema_version"] == (
        DISPATCH_EXECUTION_DAEMON_CLI_RESULT_SCHEMA_VERSION
    )
    assert result["result_status"] == "PLANNED"
    assert result["loop_result"] is None
    assert result["loop_summary"] is None
    assert result["runtime_state"]["state_status"] == "DISABLED"
    assert "loop=NONE" in summary_line(result)


def test_dispatch_daemon_cli_execute_run_once_idle() -> None:
    result = execute_dispatch_execution_daemon_cli(
        action="run_once",
        environ={DISPATCH_EXECUTION_DAEMON_ENABLED_ENV: "1"},
        request_id="request-0774-run",
        confirm_tick=True,
        dry_run=True,
        cycle_limit=1,
        started_at="2026-09-15T11:03:00Z",
    )

    assert result["result_status"] == "EXECUTED"
    assert result["loop_result"]["loop_status"] == "IDLE"
    assert result["loop_summary"]["loop_status"] == "IDLE"
    assert result["loop_summary"]["stop_reason"] == "idle"
    assert result["runtime_state"]["state_status"] == "STOPPED"
    assert result["new_tables_required"] is False
    assert_dispatch_execution_result_redacted(result)


def test_dispatch_daemon_cli_execute_run_once_blocks_without_confirm() -> None:
    result = execute_dispatch_execution_daemon_cli(
        action="run_once",
        environ={DISPATCH_EXECUTION_DAEMON_ENABLED_ENV: "1"},
        request_id="request-0774-block",
        confirm_tick=False,
        cycle_limit=1,
        started_at="2026-09-15T11:04:00Z",
    )

    assert result["loop_result"]["loop_status"] == "BLOCKED"
    assert result["loop_summary"]["stop_reason"] == "confirm_tick_required"
    assert result["runtime_state"]["state_status"] == "DEGRADED"


def test_dispatch_daemon_cli_main_outputs_summary_and_json() -> None:
    summary_out = StringIO()
    assert (
        main(
            [
                "--run-once",
                "--confirm-tick",
                "--cycle-limit",
                "1",
                "--started-at",
                "2026-09-15T11:05:00Z",
                "--summary",
            ],
            stdout=summary_out,
        )
        == 0
    )
    assert "ag_dispatch_execution_daemon_cli=executed" in summary_out.getvalue()

    json_out = StringIO()
    assert main(["--plan", "--started-at", "2026-09-15T11:06:00Z"], stdout=json_out) == 0
    payload = json.loads(json_out.getvalue())
    assert payload["result_status"] == "PLANNED"


def test_dispatch_daemon_cli_action_helpers() -> None:
    assert _normalize_cli_action("run-once") == "run_once"
    with pytest.raises(ValueError):
        _normalize_cli_action("forever")

    request_id = _default_request_id(
        "plan",
        "worker-0774",
        "2026-09-15T11:07:00Z",
    )
    assert request_id == _default_request_id(
        "plan",
        "worker-0774",
        "2026-09-15T11:07:00Z",
    )
    assert _utc_now().endswith("Z")
