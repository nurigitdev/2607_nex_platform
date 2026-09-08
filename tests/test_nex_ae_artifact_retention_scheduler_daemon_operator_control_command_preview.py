from __future__ import annotations

import json
from copy import deepcopy

import pytest

from nex_ae_api.artifact_retention_scheduler_daemon import (
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_COMMAND_PREVIEW_SCHEMA_VERSION,
    build_artifact_retention_scheduler_daemon_operator_control_admission,
    build_artifact_retention_scheduler_daemon_operator_control_command_preview,
    build_artifact_retention_scheduler_daemon_operator_control_request,
    operator_control_command_preview_summary_line,
    summarize_artifact_retention_scheduler_daemon_operator_control_command_preview,
    validate_artifact_retention_scheduler_daemon_operator_control_command_preview,
)
from nex_ae_api.artifacts import ArtifactHandoffError


REQUESTED_AT = "2026-09-08T04:00:00Z"
CHECKED_AT = "2026-09-08T04:00:10Z"
SUBJECT = {
    "actor_type": "operator",
    "actor_id": "employee-1001",
    "tenant_id": "tenant-a",
    "workspace_id": "workspace-a",
    "service_id": "nex-ag",
}


def approval(reason: str) -> dict[str, object]:
    return {
        "approved": True,
        "approved_by": dict(SUBJECT),
        "approved_at": REQUESTED_AT,
        "reason": reason,
    }


def request(action: str, *, idempotency_key: str, reason: str) -> dict[str, object]:
    start_like = action in {"start_daemon", "restart_daemon"}
    return build_artifact_retention_scheduler_daemon_operator_control_request(
        action=action,
        operator_subject=SUBJECT,
        idempotency_key=idempotency_key,
        reason=reason,
        requested_at=REQUESTED_AT,
        enabled=start_like,
        explicit_opt_in=start_like,
        max_cycles=3,
        run_worker=True,
        approval=approval(reason) if start_like else None,
    )


def process(process_status: str, *, process_id: int | None = None) -> dict[str, object]:
    return {
        "process_status": process_status,
        "process_id": process_id,
        "host_id": "ae-node-01" if process_id is not None else None,
        "observed_at": CHECKED_AT,
    }


def admission(
    action: str,
    *,
    current_process: dict[str, object] | None = None,
) -> dict[str, object]:
    reason = f"operator {action.replace('_daemon', '')} request"
    return build_artifact_retention_scheduler_daemon_operator_control_admission(
        operator_control_request=request(
            action,
            idempotency_key=f"idem-0584-{action}",
            reason=reason,
        ),
        current_process=current_process,
        checked_at=CHECKED_AT,
    )


def test_status_probe_preview_is_safe_single_supervisor_command() -> None:
    preview = build_artifact_retention_scheduler_daemon_operator_control_command_preview(
        operator_control_admission=admission("status_probe"),
        checked_at=CHECKED_AT,
    )
    summary = summarize_artifact_retention_scheduler_daemon_operator_control_command_preview(
        preview
    )
    command = preview["supervisor_command_previews"][0]["supervisor_command"]
    serialized = json.dumps(preview, ensure_ascii=False, sort_keys=True)

    assert preview["operator_control_command_preview_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_COMMAND_PREVIEW_SCHEMA_VERSION
    )
    assert preview["preview_status"] == "READY"
    assert preview["action"] == "status_probe"
    assert preview["supervisor_command_previews"][0]["action"] == "status_probe"
    assert preview["supervisor_command_previews"][0]["requires_distinct_evidence"] is False
    assert command["command"]["action"] == "status_probe"
    assert command["command"]["enabled"] is False
    assert command["metadata"]["requested_by"] == {
        "actor_type": "operator",
        "actor_id": "employee-1001",
    }
    assert command["metadata"]["reason"] == "operator status_probe request"
    assert preview["guardrails"]["preview_only"] is True
    assert preview["guardrails"]["supervisor_adapter_invoked"] is False
    assert preview["metadata"]["command_preview_count"] == 1
    assert preview["metadata"]["status_probe_preview_count"] == 1
    assert summary["supervisor_actions"] == ["status_probe"]
    assert "commands=1" in operator_control_command_preview_summary_line(preview)
    assert validate_artifact_retention_scheduler_daemon_operator_control_command_preview(
        preview
    ) == preview
    assert "postgresql://" not in serialized
    assert "/data/nex-platform" not in serialized
    assert "nuri1004" not in serialized
    assert "ed6@c496em" not in serialized


def test_start_ready_preview_carries_bounded_runtime_request_without_starting() -> None:
    preview = build_artifact_retention_scheduler_daemon_operator_control_command_preview(
        operator_control_admission=admission("start_daemon"),
        checked_at=CHECKED_AT,
    )
    item = preview["supervisor_command_previews"][0]
    command = item["supervisor_command"]

    assert preview["preview_status"] == "READY"
    assert item["action"] == "start_daemon"
    assert item["requires_distinct_evidence"] is True
    assert item["requires_follow_up_admission"] is False
    assert command["command"]["action"] == "start_daemon"
    assert command["command"]["enabled"] is True
    assert command["command"]["explicit_opt_in"] is True
    assert command["command"]["max_cycles"] == 3
    assert command["command"]["run_worker"] is True
    assert command["execution_plan"]["supervisor_adapter_invoked"] is False
    assert command["metadata"]["bounded_loop_started"] is False
    assert preview["guardrails"]["contract_starts_process"] is False
    assert preview["metadata"]["start_preview_count"] == 1


def test_blocked_or_noop_admission_produces_empty_preview() -> None:
    blocked = build_artifact_retention_scheduler_daemon_operator_control_command_preview(
        operator_control_admission=admission(
            "restart_daemon",
            current_process=process("MISSING"),
        ),
        checked_at=CHECKED_AT,
    )
    noop = build_artifact_retention_scheduler_daemon_operator_control_command_preview(
        operator_control_admission=admission(
            "stop_daemon",
            current_process=process("EXITED", process_id=4201),
        ),
        checked_at=CHECKED_AT,
    )

    assert blocked["preview_status"] == "BLOCKED"
    assert blocked["supervisor_command_previews"] == []
    assert blocked["metadata"]["blocked"] is True
    assert blocked["metadata"]["ready_for_dispatch"] is False
    assert noop["preview_status"] == "NOOP"
    assert noop["supervisor_command_previews"] == []
    assert noop["metadata"]["noop"] is True
    assert "next=none" in operator_control_command_preview_summary_line(noop)


def test_restart_ready_preview_decomposes_to_stop_then_start_commands() -> None:
    preview = build_artifact_retention_scheduler_daemon_operator_control_command_preview(
        operator_control_admission=admission(
            "restart_daemon",
            current_process=process("RUNNING", process_id=5201),
        ),
        checked_at=CHECKED_AT,
    )
    stop_item, start_item = preview["supervisor_command_previews"]

    assert preview["preview_status"] == "READY"
    assert [stop_item["action"], start_item["action"]] == [
        "stop_daemon",
        "start_daemon",
    ]
    assert stop_item["sequence"] == 1
    assert stop_item["requires_follow_up_admission"] is False
    assert start_item["sequence"] == 2
    assert start_item["requires_follow_up_admission"] is True
    assert stop_item["supervisor_command"]["command"]["action"] == "stop_daemon"
    assert stop_item["supervisor_command"]["command"]["enabled"] is False
    assert start_item["supervisor_command"]["command"]["action"] == "start_daemon"
    assert start_item["supervisor_command"]["command"]["enabled"] is True
    assert start_item["supervisor_command"]["command"]["explicit_opt_in"] is True
    assert preview["metadata"]["command_preview_count"] == 2
    assert preview["metadata"]["start_preview_count"] == 1
    assert preview["metadata"]["stop_preview_count"] == 1
    assert preview["guardrails"]["restart_decomposes_to_stop_then_start"] is True


@pytest.mark.parametrize(
    ("mutate", "error_code", "detail"),
    (
        (
            lambda preview: [],
            "ae.artifact_retention_scheduler_daemon_operator_control_command_preview_invalid",
            "object",
        ),
        (
            lambda preview: {
                **preview,
                "operator_control_command_preview_schema_version": "wrong",
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_command_preview_schema_invalid",
            "schema",
        ),
        (
            lambda preview: {**preview, "service_id": "nex-ag"},
            "ae.artifact_retention_scheduler_daemon_operator_control_command_preview_invalid",
            "service id",
        ),
        (
            lambda preview: {**preview, "scheduler_id": "other"},
            "ae.artifact_retention_scheduler_daemon_operator_control_command_preview_invalid",
            "scheduler scope",
        ),
        (
            lambda preview: {
                **preview,
                "operator_control_admission_id": "other",
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_command_preview_invalid",
            "admission scope",
        ),
        (
            lambda preview: {
                **preview,
                "operator_control_request_id": "other",
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_command_preview_invalid",
            "request scope",
        ),
        (
            lambda preview: {**preview, "action": "stop_daemon"},
            "ae.artifact_retention_scheduler_daemon_operator_control_command_preview_invalid",
            "action scope",
        ),
        (
            lambda preview: {**preview, "preview_status": "NOOP"},
            "ae.artifact_retention_scheduler_daemon_operator_control_command_preview_invalid",
            "preview status",
        ),
        (
            lambda preview: {**preview, "supervisor_command_previews": "bad"},
            "ae.artifact_retention_scheduler_daemon_operator_control_command_preview_invalid",
            "must be a list",
        ),
        (
            lambda preview: {**preview, "supervisor_command_previews": []},
            "ae.artifact_retention_scheduler_daemon_operator_control_command_preview_invalid",
            "command count",
        ),
        (
            lambda preview: {
                **preview,
                "supervisor_command_previews": [
                    {
                        "sequence": 1,
                        "action": "stop_daemon",
                    },
                    preview["supervisor_command_previews"][1],
                ],
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_command_preview_invalid",
            "keys",
        ),
        (
            lambda preview: {
                **preview,
                "supervisor_command_previews": [
                    {
                        **preview["supervisor_command_previews"][0],
                        "sequence": 2,
                    },
                    preview["supervisor_command_previews"][1],
                ],
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_command_preview_invalid",
            "sequence",
        ),
        (
            lambda preview: {
                **preview,
                "supervisor_command_previews": [
                    {
                        **preview["supervisor_command_previews"][0],
                        "action": "status_probe",
                    },
                    preview["supervisor_command_previews"][1],
                ],
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_command_preview_invalid",
            "action",
        ),
        (
            lambda preview: {
                **preview,
                "supervisor_command_previews": [
                    {
                        **preview["supervisor_command_previews"][0],
                        "requires_distinct_evidence": False,
                    },
                    preview["supervisor_command_previews"][1],
                ],
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_command_preview_invalid",
            "evidence flag",
        ),
        (
            lambda preview: {
                **preview,
                "supervisor_command_previews": [
                    preview["supervisor_command_previews"][0],
                    {
                        **preview["supervisor_command_previews"][1],
                        "requires_follow_up_admission": False,
                    },
                ],
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_command_preview_invalid",
            "follow-up flag",
        ),
        (
            lambda preview: {
                **preview,
                "supervisor_command_previews": [
                    {
                        **preview["supervisor_command_previews"][0],
                        "supervisor_command": preview[
                            "supervisor_command_previews"
                        ][1]["supervisor_command"],
                    },
                    preview["supervisor_command_previews"][1],
                ],
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_command_preview_invalid",
            "command action",
        ),
        (
            lambda preview: {
                **preview,
                "guardrails": {
                    **preview["guardrails"],
                    "supervisor_adapter_invoked": True,
                },
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_command_preview_invalid",
            "guardrails",
        ),
        (
            lambda preview: {
                **preview,
                "metadata": {
                    **preview["metadata"],
                    "subprocess_started": True,
                },
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_command_preview_invalid",
            "metadata",
        ),
        (
            lambda preview: {
                **preview,
                "operator_control_command_preview_id": "wrong",
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_command_preview_invalid",
            "id",
        ),
        (
            lambda preview: {**preview, "database_url": "postgresql://secret"},
            "ae.artifact_retention_scheduler_daemon_operator_control_command_preview_invalid",
            "keys",
        ),
    ),
)
def test_operator_control_command_preview_validation_edges(
    mutate: object,
    error_code: str,
    detail: str,
) -> None:
    preview = build_artifact_retention_scheduler_daemon_operator_control_command_preview(
        operator_control_admission=admission(
            "restart_daemon",
            current_process=process("RUNNING", process_id=7101),
        ),
        checked_at=CHECKED_AT,
    )

    with pytest.raises(ArtifactHandoffError) as exc_info:
        validate_artifact_retention_scheduler_daemon_operator_control_command_preview(
            mutate(deepcopy(preview))  # type: ignore[misc]
        )

    assert exc_info.value.error_code == error_code
    assert detail in exc_info.value.detail
