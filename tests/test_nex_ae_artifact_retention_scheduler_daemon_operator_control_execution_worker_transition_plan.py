from __future__ import annotations

from copy import deepcopy

import pytest

from nex_ae_api.artifact_retention_scheduler_daemon import (
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_TRANSITION_PLAN_SCHEMA_VERSION,
    build_artifact_retention_scheduler_daemon_operator_control_execution_worker_command,
    build_artifact_retention_scheduler_daemon_operator_control_execution_worker_transition_plan,
    operator_control_execution_worker_transition_plan_summary_line,
    summarize_artifact_retention_scheduler_daemon_operator_control_execution_worker_transition_plan,
    validate_artifact_retention_scheduler_daemon_operator_control_execution_worker_transition_plan,
)
from nex_ae_api.artifacts import ArtifactHandoffError
from test_nex_ae_artifact_retention_scheduler_daemon_operator_control_execution_state import (
    assert_safe_metadata_only,
    execution_state,
    process,
)
from test_nex_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_contract import (
    COMMANDED_AT,
    worker_command,
    worker_plan,
)


TRANSITION_PLANNED_AT = "2026-09-08T07:00:10Z"


def transition_plan(
    terminal_status: str = "SUCCEEDED",
    *,
    command: dict[str, object] | None = None,
) -> dict[str, object]:
    return build_artifact_retention_scheduler_daemon_operator_control_execution_worker_transition_plan(
        operator_control_execution_worker_command=command or worker_command(),
        terminal_status=terminal_status,
        transition_planned_at=TRANSITION_PLANNED_AT,
    )


def test_ready_worker_command_builds_success_transition_plan() -> None:
    payload = transition_plan()
    summary = (
        summarize_artifact_retention_scheduler_daemon_operator_control_execution_worker_transition_plan(
            payload
        )
    )

    assert payload[
        "operator_control_execution_worker_transition_plan_schema_version"
    ] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_TRANSITION_PLAN_SCHEMA_VERSION
    )
    assert payload["service_id"] == "nex-ae-api"
    assert payload["transition_plan_status"] == "READY"
    assert payload["terminal_status"] == "SUCCEEDED"
    assert payload["decision_reason"] == "ready_for_worker_execution_state_transitions"
    assert payload["transition_count"] == 2
    assert payload["planned_transitions"] == [
        {
            "ordinal": 1,
            "from_status": "ADMITTED",
            "to_status": "EXECUTING",
            "decision_reason": "worker_execution_started",
            "terminal": False,
        },
        {
            "ordinal": 2,
            "from_status": "EXECUTING",
            "to_status": "SUCCEEDED",
            "decision_reason": "worker_execution_succeeded",
            "terminal": True,
        },
    ]
    assert payload["guardrails"]["ready_for_transition_persistence"] is True
    assert payload["guardrails"]["uses_existing_execution_state_transition_table"] is True
    assert payload["guardrails"]["new_database_table_required"] is False
    assert payload["guardrails"]["database_write_performed"] is False
    assert payload["metadata"]["status_path"] == [
        "ADMITTED",
        "EXECUTING",
        "SUCCEEDED",
    ]
    assert summary["ready_for_transition_persistence"] is True
    assert "status=READY" in operator_control_execution_worker_transition_plan_summary_line(
        payload
    )
    assert validate_artifact_retention_scheduler_daemon_operator_control_execution_worker_transition_plan(
        payload
    ) == payload
    assert_safe_metadata_only(payload)


def test_ready_worker_command_builds_failure_transition_plan() -> None:
    payload = transition_plan("FAILED")

    assert payload["transition_plan_status"] == "READY"
    assert payload["terminal_status"] == "FAILED"
    assert payload["planned_transitions"][1] == {
        "ordinal": 2,
        "from_status": "EXECUTING",
        "to_status": "FAILED",
        "decision_reason": "worker_execution_failed",
        "terminal": True,
    }
    assert payload["guardrails"]["executing_to_failed_planned"] is True
    assert payload["guardrails"]["terminal_status_failure_supported"] is True
    assert payload["metadata"]["status_path"] == ["ADMITTED", "EXECUTING", "FAILED"]


def test_blocked_worker_command_builds_blocked_transition_plan_without_transitions() -> None:
    blocked_command = build_artifact_retention_scheduler_daemon_operator_control_execution_worker_command(
        operator_control_execution_worker_plan=worker_plan(
            execution_mode="contract_only",
        ),
        commanded_at=COMMANDED_AT,
    )
    payload = transition_plan(command=blocked_command)

    assert blocked_command["command_status"] == "BLOCKED"
    assert payload["transition_plan_status"] == "BLOCKED"
    assert payload["terminal_status"] == "BLOCKED"
    assert payload["transition_count"] == 0
    assert payload["planned_transitions"] == []
    assert payload["decision_reason"] == blocked_command["decision_reason"]
    assert payload["guardrails"]["blocked_command_has_no_transitions"] is True
    assert payload["guardrails"]["ready_for_transition_persistence"] is False
    assert payload["metadata"]["status_path"] == []
    assert "path=blocked" in operator_control_execution_worker_transition_plan_summary_line(
        payload
    )


def test_restart_command_keeps_single_execution_state_path() -> None:
    command = worker_command(
        "restart_daemon",
        current_process=process("RUNNING", process_id=6201),
    )
    payload = transition_plan(command=command)

    assert command["supervisor_command_count"] == 2
    assert [item["command"]["action"] for item in command["supervisor_commands"]] == [
        "stop_daemon",
        "start_daemon",
    ]
    assert payload["transition_count"] == 2
    assert payload["metadata"]["status_path"] == [
        "ADMITTED",
        "EXECUTING",
        "SUCCEEDED",
    ]
    assert payload["metadata"]["supervisor_actions"] == [
        "stop_daemon",
        "start_daemon",
    ]


def test_ready_command_rejects_blocked_terminal_status() -> None:
    with pytest.raises(ArtifactHandoffError) as exc_info:
        transition_plan("BLOCKED")

    assert exc_info.value.error_code == (
        "ae.artifact_retention_scheduler_daemon_operator_control_execution_worker_transition_plan_invalid"
    )


@pytest.mark.parametrize(
    "mutate",
    (
        lambda plan: {**plan, "extra": True},
        lambda plan: {
            **plan,
            "operator_control_execution_worker_transition_plan_schema_version": "wrong",
        },
        lambda plan: {**plan, "service_id": "nex-ag"},
        lambda plan: {**plan, "scheduler_id": "wrong"},
        lambda plan: {
            **plan,
            "operator_control_execution_worker_command_id": "wrong",
        },
        lambda plan: {**plan, "operator_control_execution_worker_plan_id": "wrong"},
        lambda plan: {**plan, "operator_control_execution_state_id": "wrong"},
        lambda plan: {**plan, "operator_control_execution_request_id": "wrong"},
        lambda plan: {**plan, "action": "status_probe"},
        lambda plan: {**plan, "execution_mode": "contract_only"},
        lambda plan: {**plan, "worker_mode": "real_subprocess_worker"},
        lambda plan: {**plan, "transition_plan_status": "FAILED"},
        lambda plan: {**plan, "transition_plan_status": "BLOCKED"},
        lambda plan: {**plan, "terminal_status": "BLOCKED"},
        lambda plan: {**plan, "terminal_status": "NOOP"},
        lambda plan: {**plan, "decision_reason": "wrong"},
        lambda plan: {**plan, "transition_count": 1},
        lambda plan: {**plan, "planned_transitions": []},
        lambda plan: {
            **plan,
            "planned_transitions": [
                {**plan["planned_transitions"][0], "to_status": "SUCCEEDED"},
                plan["planned_transitions"][1],
            ],
        },
        lambda plan: {
            **plan,
            "planned_transitions": [
                {**plan["planned_transitions"][0], "ordinal": 2},
                plan["planned_transitions"][1],
            ],
        },
        lambda plan: {
            **plan,
            "planned_transitions": [
                {**plan["planned_transitions"][0], "terminal": True},
                plan["planned_transitions"][1],
            ],
        },
        lambda plan: {**plan, "guardrails": {}},
        lambda plan: {**plan, "metadata": {}},
        lambda plan: {
            **plan,
            "operator_control_execution_worker_transition_plan_id": "wrong",
        },
    ),
)
def test_worker_transition_plan_validation_rejects_invalid_payloads(mutate) -> None:
    with pytest.raises(ArtifactHandoffError) as exc_info:
        validate_artifact_retention_scheduler_daemon_operator_control_execution_worker_transition_plan(
            mutate(deepcopy(transition_plan()))
        )

    assert exc_info.value.error_code in {
        "ae.artifact_retention_scheduler_daemon_operator_control_execution_worker_transition_plan_invalid",
        "ae.artifact_retention_scheduler_daemon_operator_control_execution_worker_transition_plan_schema_invalid",
    }


def test_worker_transition_plan_rejects_non_mapping_and_bad_command() -> None:
    with pytest.raises(ArtifactHandoffError):
        validate_artifact_retention_scheduler_daemon_operator_control_execution_worker_transition_plan(
            "bad"
        )
    with pytest.raises(ArtifactHandoffError):
        build_artifact_retention_scheduler_daemon_operator_control_execution_worker_transition_plan(
            operator_control_execution_worker_command={"not": "a command"},
            terminal_status="SUCCEEDED",
        )


def test_transition_plan_defaults_transition_planned_at_to_command_time() -> None:
    command = build_artifact_retention_scheduler_daemon_operator_control_execution_worker_command(
        operator_control_execution_worker_plan=worker_plan(),
        commanded_at=COMMANDED_AT,
    )
    payload = build_artifact_retention_scheduler_daemon_operator_control_execution_worker_transition_plan(
        operator_control_execution_worker_command=command,
    )

    assert payload["transition_planned_at"] == COMMANDED_AT
    assert payload["metadata"]["transition_planned_at"] == COMMANDED_AT
