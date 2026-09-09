from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

import pytest

from nex_ae_api.artifact_retention_scheduler_daemon import (
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_SCHEMA_VERSION,
    FakeArtifactRetentionSchedulerDaemonSupervisorAdapter,
    build_artifact_retention_scheduler_daemon_operator_control_execution_worker_command,
    build_artifact_retention_scheduler_daemon_operator_control_execution_worker_result,
    build_artifact_retention_scheduler_daemon_operator_control_execution_worker_transition_plan,
    build_artifact_retention_scheduler_daemon_supervisor_result,
    operator_control_execution_worker_result_summary_line,
    run_artifact_retention_scheduler_daemon_operator_control_execution_worker,
    summarize_artifact_retention_scheduler_daemon_operator_control_execution_worker_result,
    validate_artifact_retention_scheduler_daemon_operator_control_execution_worker_result,
    validate_artifact_retention_scheduler_daemon_supervisor_command,
)
from nex_ae_api.artifacts import ArtifactHandoffError
from test_nex_ae_artifact_retention_scheduler_daemon_operator_control_execution_state import (
    assert_safe_metadata_only,
    process,
)
from test_nex_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_contract import (
    COMMANDED_AT,
    worker_command,
    worker_plan,
)
from test_nex_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_transition_plan import (
    TRANSITION_PLANNED_AT,
    transition_plan,
)


OBSERVED_AT = "2026-09-08T07:00:20Z"


class FailingSupervisorAdapter:
    adapter_name = "failing_fake_supervisor"

    def execute_supervisor_command(
        self,
        supervisor_command: Mapping[str, Any],
        *,
        observed_at: str | None = None,
    ) -> dict[str, Any]:
        command = validate_artifact_retention_scheduler_daemon_supervisor_command(
            supervisor_command
        )
        return build_artifact_retention_scheduler_daemon_supervisor_result(
            supervisor_command=command,
            result_status="FAILED",
            observed_at=observed_at,
            message="simulated fake supervisor failure",
            supervisor_adapter_available=True,
            supervisor_adapter_invoked=True,
            adapter_name=self.adapter_name,
        )


def run_worker(
    command: dict[str, object] | None = None,
    *,
    transition: dict[str, object] | None = None,
    adapter: object | None = None,
) -> dict[str, object]:
    return run_artifact_retention_scheduler_daemon_operator_control_execution_worker(
        operator_control_execution_worker_command=command or worker_command(),
        operator_control_execution_worker_transition_plan=transition,
        supervisor_adapter=adapter,
        observed_at=OBSERVED_AT,
    )


def test_fake_worker_runs_start_with_fake_supervisor_without_process_side_effects() -> None:
    payload = run_worker()
    summary = (
        summarize_artifact_retention_scheduler_daemon_operator_control_execution_worker_result(
            payload
        )
    )

    assert payload["operator_control_execution_worker_result_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_SCHEMA_VERSION
    )
    assert payload["service_id"] == "nex-ae-api"
    assert payload["worker_status"] == "SUCCEEDED"
    assert payload["decision_reason"] == "fake_dry_run_worker_completed"
    assert payload["supervisor_result_count"] == 1
    assert payload["supervisor_results"][0]["result_status"] == "BLOCKED"
    assert payload["supervisor_results"][0]["metadata"][
        "supervisor_adapter_invoked"
    ] is True
    assert payload["operator_control_execution_worker_transition_plan"][
        "terminal_status"
    ] == "SUCCEEDED"
    assert payload["guardrails"]["fake_dry_run_worker_only"] is True
    assert payload["guardrails"]["supervisor_dispatch_performed"] is True
    assert payload["guardrails"]["supervisor_adapter_invoked"] is True
    assert payload["guardrails"]["subprocess_started"] is False
    assert payload["guardrails"]["subprocess_stopped"] is False
    assert payload["guardrails"]["database_write_performed"] is False
    assert payload["guardrails"]["job_queue_enqueue_performed"] is False
    assert payload["guardrails"]["physical_delete_automation_enabled"] is False
    assert payload["metadata"]["worker_execution_performed"] is True
    assert payload["metadata"]["supervisor_result_statuses"] == ["BLOCKED"]
    assert summary["worker_execution_performed"] is True
    assert "status=SUCCEEDED" in operator_control_execution_worker_result_summary_line(
        payload
    )
    assert validate_artifact_retention_scheduler_daemon_operator_control_execution_worker_result(
        payload
    ) == payload
    assert_safe_metadata_only(payload)


def test_fake_worker_runs_restart_stop_then_start_in_order() -> None:
    command = worker_command(
        "restart_daemon",
        current_process=process("RUNNING", process_id=6201),
    )
    payload = run_worker(command)

    assert payload["action"] == "restart_daemon"
    assert payload["worker_status"] == "SUCCEEDED"
    assert payload["supervisor_result_count"] == 2
    assert [item["action"] for item in payload["supervisor_results"]] == [
        "stop_daemon",
        "start_daemon",
    ]
    assert [item["result_status"] for item in payload["supervisor_results"]] == [
        "NOOP",
        "BLOCKED",
    ]
    assert payload["metadata"]["supervisor_actions"] == [
        "stop_daemon",
        "start_daemon",
    ]


def test_blocked_worker_command_returns_blocked_without_invoking_adapter() -> None:
    command = build_artifact_retention_scheduler_daemon_operator_control_execution_worker_command(
        operator_control_execution_worker_plan=worker_plan(
            execution_mode="contract_only",
        ),
        commanded_at=COMMANDED_AT,
    )
    payload = run_worker(command)

    assert command["command_status"] == "BLOCKED"
    assert payload["worker_status"] == "BLOCKED"
    assert payload["supervisor_result_count"] == 0
    assert payload["supervisor_results"] == []
    assert payload["operator_control_execution_worker_transition_plan"][
        "transition_plan_status"
    ] == "BLOCKED"
    assert payload["guardrails"]["supervisor_dispatch_performed"] is False
    assert payload["guardrails"]["supervisor_adapter_invoked"] is False
    assert payload["guardrails"]["worker_execution_performed"] is False
    assert payload["metadata"]["worker_execution_performed"] is False


def test_fake_worker_failure_adapter_produces_failed_terminal_result() -> None:
    payload = run_worker(adapter=FailingSupervisorAdapter())

    assert payload["worker_status"] == "FAILED"
    assert payload["decision_reason"] == "fake_dry_run_worker_supervisor_failed"
    assert payload["operator_control_execution_worker_transition_plan"][
        "terminal_status"
    ] == "FAILED"
    assert payload["supervisor_results"][0]["result_status"] == "FAILED"
    assert payload["metadata"]["supervisor_result_statuses"] == ["FAILED"]
    assert payload["guardrails"]["worker_failed"] is True
    assert payload["guardrails"]["subprocess_started"] is False


def test_worker_result_rejects_transition_plan_terminal_mismatch() -> None:
    command = worker_command()
    supervisor_result = build_artifact_retention_scheduler_daemon_supervisor_result(
        supervisor_command=command["supervisor_commands"][0],
        result_status="FAILED",
        observed_at=OBSERVED_AT,
        message="simulated failure",
        supervisor_adapter_available=True,
        supervisor_adapter_invoked=True,
        adapter_name=FailingSupervisorAdapter.adapter_name,
    )
    success_transition = transition_plan(command=command)

    with pytest.raises(ArtifactHandoffError) as exc_info:
        build_artifact_retention_scheduler_daemon_operator_control_execution_worker_result(
            operator_control_execution_worker_command=command,
            operator_control_execution_worker_transition_plan=success_transition,
            supervisor_results=[supervisor_result],
            observed_at=OBSERVED_AT,
        )

    assert exc_info.value.error_code == (
        "ae.artifact_retention_scheduler_daemon_operator_control_execution_worker_result_invalid"
    )


@pytest.mark.parametrize(
    "mutate",
    (
        lambda result: {**result, "extra": True},
        lambda result: {
            **result,
            "operator_control_execution_worker_result_schema_version": "wrong",
        },
        lambda result: {**result, "service_id": "nex-ag"},
        lambda result: {**result, "scheduler_id": "wrong"},
        lambda result: {
            **result,
            "operator_control_execution_worker_command_id": "wrong",
        },
        lambda result: {**result, "operator_control_execution_worker_plan_id": "wrong"},
        lambda result: {
            **result,
            "operator_control_execution_worker_transition_plan_id": "wrong",
        },
        lambda result: {**result, "operator_control_execution_state_id": "wrong"},
        lambda result: {**result, "operator_control_execution_request_id": "wrong"},
        lambda result: {**result, "action": "status_probe"},
        lambda result: {**result, "execution_mode": "contract_only"},
        lambda result: {**result, "worker_mode": "real_subprocess_worker"},
        lambda result: {**result, "worker_status": "READY"},
        lambda result: {**result, "worker_status": "FAILED"},
        lambda result: {**result, "decision_reason": "wrong"},
        lambda result: {**result, "supervisor_result_count": 0},
        lambda result: {**result, "supervisor_results": []},
        lambda result: {**result, "supervisor_results": "bad"},
        lambda result: {**result, "guardrails": {}},
        lambda result: {**result, "metadata": {}},
        lambda result: {
            **result,
            "operator_control_execution_worker_result_id": "wrong",
        },
    ),
)
def test_worker_result_validation_rejects_invalid_payloads(mutate) -> None:
    with pytest.raises(ArtifactHandoffError) as exc_info:
        validate_artifact_retention_scheduler_daemon_operator_control_execution_worker_result(
            mutate(deepcopy(run_worker()))
        )

    assert exc_info.value.error_code in {
        "ae.artifact_retention_scheduler_daemon_operator_control_execution_worker_result_invalid",
        "ae.artifact_retention_scheduler_daemon_operator_control_execution_worker_result_schema_invalid",
        "ae.artifact_retention_scheduler_daemon_supervisor_result_invalid",
    }


def test_worker_result_rejects_non_mapping_and_bad_command() -> None:
    with pytest.raises(ArtifactHandoffError):
        validate_artifact_retention_scheduler_daemon_operator_control_execution_worker_result(
            "bad"
        )
    with pytest.raises(ArtifactHandoffError):
        run_artifact_retention_scheduler_daemon_operator_control_execution_worker(
            operator_control_execution_worker_command={"not": "a command"},
        )


def test_worker_result_defaults_observed_at_to_command_time() -> None:
    command = worker_command()
    transition = build_artifact_retention_scheduler_daemon_operator_control_execution_worker_transition_plan(
        operator_control_execution_worker_command=command,
        terminal_status="SUCCEEDED",
        transition_planned_at=TRANSITION_PLANNED_AT,
    )
    supervisor_result = FakeArtifactRetentionSchedulerDaemonSupervisorAdapter().execute_supervisor_command(
        command["supervisor_commands"][0],
        observed_at=COMMANDED_AT,
    )
    payload = build_artifact_retention_scheduler_daemon_operator_control_execution_worker_result(
        operator_control_execution_worker_command=command,
        operator_control_execution_worker_transition_plan=transition,
        supervisor_results=[supervisor_result],
    )

    assert payload["observed_at"] == COMMANDED_AT
    assert payload["metadata"]["observed_at"] == COMMANDED_AT
