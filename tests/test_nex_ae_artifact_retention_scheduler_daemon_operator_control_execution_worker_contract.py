from __future__ import annotations

import json
from copy import deepcopy

import pytest

from nex_ae_api.artifact_retention_scheduler_daemon import (
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_COMMAND_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_PLAN_SCHEMA_VERSION,
    build_artifact_retention_scheduler_daemon_operator_control_execution_worker_command,
    build_artifact_retention_scheduler_daemon_operator_control_execution_worker_plan,
    operator_control_execution_worker_command_summary_line,
    operator_control_execution_worker_plan_summary_line,
    summarize_artifact_retention_scheduler_daemon_operator_control_execution_worker_command,
    summarize_artifact_retention_scheduler_daemon_operator_control_execution_worker_plan,
    validate_artifact_retention_scheduler_daemon_operator_control_execution_worker_command,
    validate_artifact_retention_scheduler_daemon_operator_control_execution_worker_plan,
)
from nex_ae_api.artifacts import ArtifactHandoffError
from test_nex_ae_artifact_retention_scheduler_daemon_operator_control_execution_state import (
    OBSERVED_AT,
    TRANSITIONED_AT,
    assert_safe_metadata_only,
    execution_state,
    process,
)


PLANNED_AT = "2026-09-08T07:00:00Z"
COMMANDED_AT = "2026-09-08T07:00:05Z"


def worker_plan(
    action: str = "start_daemon",
    *,
    current_process: dict[str, object] | None = None,
    execution_mode: str = "fake_dry_run_supervisor_persistent_dispatch",
) -> dict[str, object]:
    return build_artifact_retention_scheduler_daemon_operator_control_execution_worker_plan(
        operator_control_execution_state=execution_state(
            action,
            current_process=current_process,
            execution_mode=execution_mode,
            observed_at=OBSERVED_AT,
        ),
        planned_at=PLANNED_AT,
    )


def worker_command(
    action: str = "start_daemon",
    *,
    current_process: dict[str, object] | None = None,
    execution_mode: str = "fake_dry_run_supervisor_persistent_dispatch",
) -> dict[str, object]:
    return build_artifact_retention_scheduler_daemon_operator_control_execution_worker_command(
        operator_control_execution_worker_plan=worker_plan(
            action,
            current_process=current_process,
            execution_mode=execution_mode,
        ),
        commanded_at=COMMANDED_AT,
    )


def test_ready_fake_dispatch_state_builds_worker_plan() -> None:
    payload = worker_plan()
    summary = summarize_artifact_retention_scheduler_daemon_operator_control_execution_worker_plan(
        payload
    )

    assert payload["operator_control_execution_worker_plan_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_PLAN_SCHEMA_VERSION
    )
    assert payload["service_id"] == "nex-ae-api"
    assert payload["action"] == "start_daemon"
    assert payload["execution_mode"] == "fake_dry_run_supervisor_persistent_dispatch"
    assert payload["plan_status"] == "READY"
    assert payload["decision_reason"] == "ready_for_fake_dry_run_supervisor_worker"
    assert payload["supervisor_command_count"] == 1
    assert payload["supervisor_actions"] == ["start_daemon"]
    assert payload["guardrails"]["worker_plan_only"] is True
    assert payload["guardrails"]["source_execution_state_admitted"] is True
    assert payload["guardrails"]["worker_execution_performed"] is False
    assert payload["guardrails"]["physical_delete_automation_enabled"] is False
    assert payload["metadata"]["ready_for_worker"] is True
    assert summary["ready_for_worker"] is True
    assert "status=READY" in operator_control_execution_worker_plan_summary_line(
        payload
    )
    assert validate_artifact_retention_scheduler_daemon_operator_control_execution_worker_plan(
        payload
    ) == payload
    assert_safe_metadata_only(payload)


def test_ready_worker_plan_builds_worker_command() -> None:
    payload = worker_command()
    summary = (
        summarize_artifact_retention_scheduler_daemon_operator_control_execution_worker_command(
            payload
        )
    )

    assert payload["operator_control_execution_worker_command_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_COMMAND_SCHEMA_VERSION
    )
    assert payload["service_id"] == "nex-ae-api"
    assert payload["worker_mode"] == "fake_dry_run_supervisor_persistent_dispatch_worker"
    assert payload["command_status"] == "READY"
    assert (
        payload["decision_reason"]
        == "worker_command_ready_for_fake_dry_run_supervisor_dispatch"
    )
    assert payload["supervisor_command_count"] == 1
    assert payload["supervisor_commands"][0]["command"]["action"] == "start_daemon"
    assert payload["guardrails"]["worker_command_only"] is True
    assert payload["guardrails"]["source_worker_plan_ready"] is True
    assert payload["guardrails"]["worker_execution_performed"] is False
    assert payload["metadata"]["ready_for_worker_execution"] is True
    assert summary["ready_for_worker_execution"] is True
    assert "status=READY" in operator_control_execution_worker_command_summary_line(
        payload
    )
    assert validate_artifact_retention_scheduler_daemon_operator_control_execution_worker_command(
        payload
    ) == payload
    assert_safe_metadata_only(payload)


def test_restart_worker_plan_preserves_stop_then_start_commands() -> None:
    payload = worker_command(
        "restart_daemon",
        current_process=process("RUNNING", process_id=6201),
    )

    assert payload["action"] == "restart_daemon"
    assert payload["supervisor_command_count"] == 2
    assert [item["command"]["action"] for item in payload["supervisor_commands"]] == [
        "stop_daemon",
        "start_daemon",
    ]
    assert payload["guardrails"]["source_worker_plan_ready"] is True
    assert payload["operator_control_execution_worker_plan"]["guardrails"][
        "restart_decomposes_to_stop_then_start"
    ] is True


def test_non_admitted_source_state_builds_blocked_plan_and_command() -> None:
    plan = worker_plan(execution_mode="contract_only")
    command = build_artifact_retention_scheduler_daemon_operator_control_execution_worker_command(
        operator_control_execution_worker_plan=plan,
        commanded_at=COMMANDED_AT,
    )

    assert plan["plan_status"] == "BLOCKED"
    assert plan["decision_reason"] == "source_execution_state_not_admitted"
    assert plan["metadata"]["ready_for_worker"] is False
    assert plan["guardrails"]["source_execution_state_admitted"] is False
    assert command["command_status"] == "BLOCKED"
    assert command["decision_reason"] == "source_execution_state_not_admitted"
    assert command["supervisor_command_count"] == 0
    assert command["supervisor_commands"] == []
    assert command["metadata"]["ready_for_worker_execution"] is False
    assert "status=BLOCKED" in operator_control_execution_worker_command_summary_line(
        command
    )


@pytest.mark.parametrize(
    "mutate",
    (
        lambda plan: {**plan, "extra": True},
        lambda plan: {
            **plan,
            "operator_control_execution_worker_plan_schema_version": "wrong",
        },
        lambda plan: {**plan, "service_id": "nex-cx"},
        lambda plan: {**plan, "scheduler_id": "wrong"},
        lambda plan: {**plan, "operator_control_execution_state_id": "wrong"},
        lambda plan: {**plan, "operator_control_execution_request_id": "wrong"},
        lambda plan: {**plan, "action": "status_probe"},
        lambda plan: {**plan, "execution_mode": "contract_only"},
        lambda plan: {**plan, "plan_status": "FAILED"},
        lambda plan: {**plan, "plan_status": "BLOCKED"},
        lambda plan: {**plan, "decision_reason": "wrong"},
        lambda plan: {**plan, "supervisor_command_count": 2},
        lambda plan: {**plan, "supervisor_actions": ["stop_daemon"]},
        lambda plan: {**plan, "supervisor_command_ids": ["wrong"]},
        lambda plan: {**plan, "guardrails": {}},
        lambda plan: {**plan, "metadata": {}},
        lambda plan: {**plan, "operator_control_execution_worker_plan_id": "wrong"},
    ),
)
def test_worker_plan_validation_rejects_invalid_payloads(mutate) -> None:
    with pytest.raises(ArtifactHandoffError) as exc_info:
        validate_artifact_retention_scheduler_daemon_operator_control_execution_worker_plan(
            mutate(deepcopy(worker_plan()))
        )

    assert exc_info.value.error_code in {
        "ae.artifact_retention_scheduler_daemon_operator_control_execution_worker_plan_invalid",
        "ae.artifact_retention_scheduler_daemon_operator_control_execution_worker_plan_schema_invalid",
    }


@pytest.mark.parametrize(
    "mutate",
    (
        lambda command: {**command, "extra": True},
        lambda command: {
            **command,
            "operator_control_execution_worker_command_schema_version": "wrong",
        },
        lambda command: {**command, "service_id": "nex-ag"},
        lambda command: {**command, "scheduler_id": "wrong"},
        lambda command: {**command, "operator_control_execution_worker_plan_id": "wrong"},
        lambda command: {**command, "operator_control_execution_state_id": "wrong"},
        lambda command: {**command, "operator_control_execution_request_id": "wrong"},
        lambda command: {**command, "action": "status_probe"},
        lambda command: {**command, "execution_mode": "contract_only"},
        lambda command: {**command, "worker_mode": "real_subprocess_worker"},
        lambda command: {**command, "command_status": "FAILED"},
        lambda command: {**command, "command_status": "BLOCKED"},
        lambda command: {**command, "decision_reason": "wrong"},
        lambda command: {**command, "supervisor_command_count": 0},
        lambda command: {**command, "supervisor_commands": []},
        lambda command: {**command, "supervisor_commands": "bad"},
        lambda command: {**command, "guardrails": {}},
        lambda command: {**command, "metadata": {}},
        lambda command: {
            **command,
            "operator_control_execution_worker_command_id": "wrong",
        },
    ),
)
def test_worker_command_validation_rejects_invalid_payloads(mutate) -> None:
    with pytest.raises(ArtifactHandoffError) as exc_info:
        validate_artifact_retention_scheduler_daemon_operator_control_execution_worker_command(
            mutate(deepcopy(worker_command()))
        )

    assert exc_info.value.error_code in {
        "ae.artifact_retention_scheduler_daemon_operator_control_execution_worker_command_invalid",
        "ae.artifact_retention_scheduler_daemon_operator_control_execution_worker_command_schema_invalid",
        "ae.artifact_retention_scheduler_daemon_supervisor_command_invalid",
    }


def test_worker_contract_builders_reject_non_mapping_inputs() -> None:
    with pytest.raises(ArtifactHandoffError):
        validate_artifact_retention_scheduler_daemon_operator_control_execution_worker_plan(
            "bad"
        )
    with pytest.raises(ArtifactHandoffError):
        validate_artifact_retention_scheduler_daemon_operator_control_execution_worker_command(
            "bad"
        )


def test_worker_command_defaults_commanded_at_to_plan_time() -> None:
    plan = build_artifact_retention_scheduler_daemon_operator_control_execution_worker_plan(
        operator_control_execution_state=execution_state(),
        planned_at=TRANSITIONED_AT,
    )
    command = build_artifact_retention_scheduler_daemon_operator_control_execution_worker_command(
        operator_control_execution_worker_plan=plan,
    )

    assert command["commanded_at"] == TRANSITIONED_AT
    assert command["metadata"]["commanded_at"] == TRANSITIONED_AT
