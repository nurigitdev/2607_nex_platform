from __future__ import annotations

import json
from copy import deepcopy

import pytest

from nex_ae_api.artifact_retention_scheduler_daemon import (
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_ADMISSION_SCHEMA_VERSION,
    build_artifact_retention_scheduler_daemon_operator_control_admission,
    build_artifact_retention_scheduler_daemon_operator_control_request,
    build_artifact_retention_scheduler_daemon_supervised_process_snapshot,
    build_artifact_retention_scheduler_daemon_supervisor_command,
    operator_control_admission_summary_line,
    summarize_artifact_retention_scheduler_daemon_operator_control_admission,
    validate_artifact_retention_scheduler_daemon_operator_control_admission,
)
from nex_ae_api.artifacts import ArtifactHandoffError


REQUESTED_AT = "2026-09-08T03:00:00Z"
OBSERVED_AT = "2026-09-08T03:00:05Z"
STARTED_AT = "2026-09-08T03:00:10Z"
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


def request(
    action: str,
    *,
    idempotency_key: str,
    reason: str,
    max_cycles: int | str = 1,
    run_worker: bool = False,
) -> dict[str, object]:
    start_like = action in {"start_daemon", "restart_daemon"}
    return build_artifact_retention_scheduler_daemon_operator_control_request(
        action=action,
        operator_subject=SUBJECT,
        idempotency_key=idempotency_key,
        reason=reason,
        requested_at=REQUESTED_AT,
        enabled=start_like,
        explicit_opt_in=start_like,
        max_cycles=max_cycles,
        run_worker=run_worker,
        approval=approval(reason) if start_like else None,
    )


def process(
    process_status: str,
    *,
    process_id: int | None = None,
    host_id: str | None = None,
    observed_at: str = OBSERVED_AT,
) -> dict[str, object]:
    return {
        "process_status": process_status,
        "process_id": process_id,
        "host_id": host_id,
        "observed_at": observed_at,
    }


def test_status_probe_admission_is_metadata_only_and_dispatch_ready() -> None:
    admission = build_artifact_retention_scheduler_daemon_operator_control_admission(
        operator_control_request=request(
            "status_probe",
            idempotency_key="idem-0583-status",
            reason="operator status check",
        ),
        checked_at=OBSERVED_AT,
    )
    summary = summarize_artifact_retention_scheduler_daemon_operator_control_admission(
        admission
    )
    serialized = json.dumps(admission, ensure_ascii=False, sort_keys=True)

    assert admission["operator_control_admission_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_ADMISSION_SCHEMA_VERSION
    )
    assert admission["admission_status"] == "READY"
    assert admission["decision_reason"] == "status_probe_allowed"
    assert admission["current_process"]["process_source"] == "none"
    assert admission["current_process"]["process_status"] == "MISSING"
    assert admission["next_supervisor_actions"] == [
        {
            "sequence": 1,
            "action": "status_probe",
            "mutates_process": False,
            "requires_distinct_evidence": False,
            "requires_follow_up_admission": False,
        }
    ]
    assert admission["guardrails"]["admission_only"] is True
    assert admission["guardrails"]["contract_starts_process"] is False
    assert admission["guardrails"]["contract_stops_process"] is False
    assert admission["guardrails"]["ag_direct_process_control_allowed"] is False
    assert admission["metadata"]["ready_for_dispatch"] is True
    assert admission["metadata"]["next_supervisor_action_count"] == 1
    assert summary["next_supervisor_actions"] == ["status_probe"]
    assert "status=READY" in operator_control_admission_summary_line(admission)
    assert validate_artifact_retention_scheduler_daemon_operator_control_admission(
        admission
    ) == admission
    assert "postgresql://" not in serialized
    assert "/data/nex-platform" not in serialized
    assert "nuri1004" not in serialized
    assert "ed6@c496em" not in serialized


@pytest.mark.parametrize(
    ("current_process", "expected_status", "expected_reason", "expected_actions"),
    (
        (None, "READY", "start_allowed_no_running_process", ["start_daemon"]),
        (
            process("STOPPED", process_id=3101, host_id="ae-node-01"),
            "READY",
            "start_allowed_no_running_process",
            ["start_daemon"],
        ),
        (
            process("RUNNING", process_id=3101, host_id="ae-node-01"),
            "NOOP",
            "daemon_already_running",
            [],
        ),
        (
            process("START_REQUESTED"),
            "BLOCKED",
            "start_already_requested",
            [],
        ),
        (
            process("STALE", process_id=3101, host_id="ae-node-01"),
            "BLOCKED",
            "stale_process_requires_stop_or_review",
            [],
        ),
        (
            process("FAILED", process_id=3101, host_id="ae-node-01"),
            "BLOCKED",
            "process_state_requires_review",
            [],
        ),
    ),
)
def test_start_admission_respects_existing_process_state(
    current_process: object,
    expected_status: str,
    expected_reason: str,
    expected_actions: list[str],
) -> None:
    admission = build_artifact_retention_scheduler_daemon_operator_control_admission(
        operator_control_request=request(
            "start_daemon",
            idempotency_key=f"idem-0583-start-{expected_reason}",
            reason="operator start request",
            max_cycles="3",
            run_worker=True,
        ),
        current_process=current_process,  # type: ignore[arg-type]
        checked_at=OBSERVED_AT,
    )

    assert admission["admission_status"] == expected_status
    assert admission["decision_reason"] == expected_reason
    assert [
        item["action"] for item in admission["next_supervisor_actions"]
    ] == expected_actions
    assert admission["metadata"]["approval_granted"] is True
    assert admission["metadata"]["ready_for_dispatch"] is (
        expected_status == "READY"
    )


@pytest.mark.parametrize(
    ("current_process", "expected_status", "expected_reason", "expected_actions"),
    (
        (
            process("RUNNING", process_id=4201, host_id="ae-node-01"),
            "READY",
            "stop_allowed_for_observed_process",
            ["stop_daemon"],
        ),
        (
            process("STALE", process_id=4201, host_id="ae-node-01"),
            "READY",
            "stop_allowed_for_observed_process",
            ["stop_daemon"],
        ),
        (
            process("START_REQUESTED"),
            "READY",
            "stop_allowed_for_observed_process",
            ["stop_daemon"],
        ),
        (
            process("STOP_REQUESTED", process_id=4201, host_id="ae-node-01"),
            "BLOCKED",
            "stop_already_requested",
            [],
        ),
        (None, "NOOP", "daemon_not_running", []),
        (
            process("EXITED", process_id=4201, host_id="ae-node-01"),
            "NOOP",
            "daemon_not_running",
            [],
        ),
        (
            process("BLOCKED"),
            "BLOCKED",
            "process_state_requires_review",
            [],
        ),
    ),
)
def test_stop_admission_respects_process_prerequisites(
    current_process: object,
    expected_status: str,
    expected_reason: str,
    expected_actions: list[str],
) -> None:
    admission = build_artifact_retention_scheduler_daemon_operator_control_admission(
        operator_control_request=request(
            "stop_daemon",
            idempotency_key=f"idem-0583-stop-{expected_reason}",
            reason="operator stop request",
        ),
        current_process=current_process,  # type: ignore[arg-type]
        checked_at=OBSERVED_AT,
    )

    assert admission["admission_status"] == expected_status
    assert admission["decision_reason"] == expected_reason
    assert [
        item["action"] for item in admission["next_supervisor_actions"]
    ] == expected_actions
    assert admission["metadata"]["approval_required"] is False


@pytest.mark.parametrize(
    ("current_process", "expected_status", "expected_reason", "expected_actions"),
    (
        (
            process("RUNNING", process_id=5201, host_id="ae-node-01"),
            "READY",
            "restart_allowed_stop_then_start",
            ["stop_daemon", "start_daemon"],
        ),
        (
            process("STALE", process_id=5201, host_id="ae-node-01"),
            "READY",
            "restart_allowed_stop_then_start",
            ["stop_daemon", "start_daemon"],
        ),
        (
            process("MISSING"),
            "BLOCKED",
            "restart_requires_running_process",
            [],
        ),
        (
            process("STOPPED", process_id=5201, host_id="ae-node-01"),
            "BLOCKED",
            "restart_requires_running_process",
            [],
        ),
        (
            process("START_REQUESTED"),
            "BLOCKED",
            "start_in_progress",
            [],
        ),
        (
            process("STOP_REQUESTED", process_id=5201, host_id="ae-node-01"),
            "BLOCKED",
            "stop_in_progress",
            [],
        ),
        (
            process("FAILED", process_id=5201, host_id="ae-node-01"),
            "BLOCKED",
            "process_state_requires_review",
            [],
        ),
    ),
)
def test_restart_admission_decomposes_to_stop_then_start_when_safe(
    current_process: object,
    expected_status: str,
    expected_reason: str,
    expected_actions: list[str],
) -> None:
    admission = build_artifact_retention_scheduler_daemon_operator_control_admission(
        operator_control_request=request(
            "restart_daemon",
            idempotency_key=f"idem-0583-restart-{expected_reason}",
            reason="operator restart request",
        ),
        current_process=current_process,  # type: ignore[arg-type]
        checked_at=OBSERVED_AT,
    )

    assert admission["admission_status"] == expected_status
    assert admission["decision_reason"] == expected_reason
    assert [
        item["action"] for item in admission["next_supervisor_actions"]
    ] == expected_actions
    assert admission["guardrails"]["restart_decomposes_to_stop_then_start"] is True
    assert admission["guardrails"]["restart_requires_follow_up_admission"] is True
    if expected_actions:
        assert admission["next_supervisor_actions"][1][
            "requires_follow_up_admission"
        ] is True


def test_admission_accepts_supervised_process_snapshot_and_record_sources() -> None:
    command = build_artifact_retention_scheduler_daemon_supervisor_command(
        action="start_daemon",
        enabled=True,
        explicit_opt_in=True,
        checked_at=REQUESTED_AT,
    )
    snapshot = build_artifact_retention_scheduler_daemon_supervised_process_snapshot(
        supervisor_command=command,
        process_status="RUNNING",
        process_id=6201,
        host_id="ae-node-02",
        observed_at=OBSERVED_AT,
        started_at=STARTED_AT,
    )
    stop_request = request(
        "stop_daemon",
        idempotency_key="idem-0583-stop-snapshot",
        reason="operator stop request",
    )

    from_snapshot = build_artifact_retention_scheduler_daemon_operator_control_admission(
        operator_control_request=stop_request,
        current_process=snapshot,
        checked_at=OBSERVED_AT,
    )
    from_record = build_artifact_retention_scheduler_daemon_operator_control_admission(
        operator_control_request=stop_request,
        current_process={"supervised_process_snapshot": snapshot},
        checked_at=OBSERVED_AT,
    )

    assert from_snapshot["current_process"]["process_source"] == "snapshot"
    assert from_record["current_process"]["process_source"] == "record"
    assert from_snapshot["current_process"]["process_status"] == "RUNNING"
    assert from_record["current_process"]["daemon_supervised_process_id"] == (
        snapshot["daemon_supervised_process_id"]
    )
    assert from_snapshot["admission_status"] == "READY"
    assert from_record["admission_status"] == "READY"


@pytest.mark.parametrize(
    ("mutate", "error_code", "detail"),
    (
        (
            lambda admission: [],
            "ae.artifact_retention_scheduler_daemon_operator_control_admission_invalid",
            "object",
        ),
        (
            lambda admission: {
                **admission,
                "operator_control_admission_schema_version": "wrong",
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_admission_schema_invalid",
            "schema",
        ),
        (
            lambda admission: {**admission, "service_id": "nex-ag"},
            "ae.artifact_retention_scheduler_daemon_operator_control_admission_invalid",
            "service id",
        ),
        (
            lambda admission: {**admission, "scheduler_id": "other"},
            "ae.artifact_retention_scheduler_daemon_operator_control_admission_invalid",
            "scheduler scope",
        ),
        (
            lambda admission: {
                **admission,
                "operator_control_request_id": "other",
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_admission_invalid",
            "request scope",
        ),
        (
            lambda admission: {**admission, "action": "stop_daemon"},
            "ae.artifact_retention_scheduler_daemon_operator_control_admission_invalid",
            "action scope",
        ),
        (
            lambda admission: {
                **admission,
                "current_process": {
                    **admission["current_process"],
                    "process_running": False,
                },
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_admission_invalid",
            "running flag",
        ),
        (
            lambda admission: {**admission, "admission_status": "maybe"},
            "ae.artifact_retention_scheduler_daemon_operator_control_admission_invalid",
            "admission status",
        ),
        (
            lambda admission: {**admission, "admission_status": "NOOP"},
            "ae.artifact_retention_scheduler_daemon_operator_control_admission_invalid",
            "status",
        ),
        (
            lambda admission: {**admission, "decision_reason": "other"},
            "ae.artifact_retention_scheduler_daemon_operator_control_admission_invalid",
            "decision reason",
        ),
        (
            lambda admission: {**admission, "next_supervisor_actions": []},
            "ae.artifact_retention_scheduler_daemon_operator_control_admission_invalid",
            "supervisor actions",
        ),
        (
            lambda admission: {
                **admission,
                "execution_intent": {
                    **admission["execution_intent"],
                    "runs_worker": True,
                },
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_admission_invalid",
            "execution intent",
        ),
        (
            lambda admission: {
                **admission,
                "guardrails": {
                    **admission["guardrails"],
                    "contract_starts_process": True,
                },
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_admission_invalid",
            "guardrails",
        ),
        (
            lambda admission: {
                **admission,
                "metadata": {
                    **admission["metadata"],
                    "subprocess_started": True,
                },
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_admission_invalid",
            "metadata",
        ),
        (
            lambda admission: {
                **admission,
                "operator_control_admission_id": "wrong",
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_admission_invalid",
            "id",
        ),
        (
            lambda admission: {**admission, "database_url": "postgresql://secret"},
            "ae.artifact_retention_scheduler_daemon_operator_control_admission_invalid",
            "keys",
        ),
    ),
)
def test_operator_control_admission_validation_edges(
    mutate: object,
    error_code: str,
    detail: str,
) -> None:
    admission = build_artifact_retention_scheduler_daemon_operator_control_admission(
        operator_control_request=request(
            "restart_daemon",
            idempotency_key="idem-0583-restart-valid",
            reason="operator restart request",
        ),
        current_process=process("RUNNING", process_id=7101, host_id="ae-node-03"),
        checked_at=OBSERVED_AT,
    )

    with pytest.raises(ArtifactHandoffError) as exc_info:
        validate_artifact_retention_scheduler_daemon_operator_control_admission(
            mutate(deepcopy(admission))  # type: ignore[misc]
        )

    assert exc_info.value.error_code == error_code
    assert detail in exc_info.value.detail


@pytest.mark.parametrize(
    ("current_process", "detail"),
    (
        ("bad", "current process is invalid"),
        (
            {"process_source": "socket", "process_status": "MISSING"},
            "current process keys",
        ),
        (
            {
                "process_source": "none",
                "process_status": "RUNNING",
                "process_running": True,
                "daemon_supervised_process_id": None,
                "daemon_supervisor_command_id": None,
                "process_id": None,
                "host_id": None,
                "observed_at": OBSERVED_AT,
            },
            "empty current process",
        ),
        (
            process("RUNNING", host_id="ae-node-01"),
            "current process id is required",
        ),
    ),
)
def test_operator_control_admission_rejects_invalid_current_process(
    current_process: object,
    detail: str,
) -> None:
    with pytest.raises(ArtifactHandoffError) as exc_info:
        build_artifact_retention_scheduler_daemon_operator_control_admission(
            operator_control_request=request(
                "status_probe",
                idempotency_key=f"idem-0583-invalid-{detail}",
                reason="operator status check",
            ),
            current_process=current_process,  # type: ignore[arg-type]
            checked_at=OBSERVED_AT,
        )

    assert detail in exc_info.value.detail
