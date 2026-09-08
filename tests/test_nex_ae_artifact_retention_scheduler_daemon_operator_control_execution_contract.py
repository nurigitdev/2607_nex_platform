from __future__ import annotations

import json
from copy import deepcopy

import pytest

from nex_ae_api.artifact_retention_scheduler_daemon import (
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_REQUEST_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_RESULT_SCHEMA_VERSION,
    build_artifact_retention_scheduler_daemon_operator_control_admission,
    build_artifact_retention_scheduler_daemon_operator_control_command_preview,
    build_artifact_retention_scheduler_daemon_operator_control_execution_request,
    build_artifact_retention_scheduler_daemon_operator_control_execution_result,
    build_artifact_retention_scheduler_daemon_operator_control_facade,
    build_artifact_retention_scheduler_daemon_operator_control_policy,
    build_artifact_retention_scheduler_daemon_operator_control_request,
    operator_control_execution_request_summary_line,
    operator_control_execution_result_summary_line,
    summarize_artifact_retention_scheduler_daemon_operator_control_execution_request,
    summarize_artifact_retention_scheduler_daemon_operator_control_execution_result,
    validate_artifact_retention_scheduler_daemon_operator_control_execution_request,
    validate_artifact_retention_scheduler_daemon_operator_control_execution_result,
)
from nex_ae_api.artifacts import ArtifactHandoffError


REQUESTED_AT = "2026-09-08T06:00:00Z"
CHECKED_AT = "2026-09-08T06:00:12Z"
OBSERVED_AT = "2026-09-08T06:00:30Z"
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


def operator_request(
    action: str,
    *,
    idempotency_key: str,
    reason: str,
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


def operator_facade(
    action: str,
    *,
    current_process: dict[str, object] | None = None,
) -> dict[str, object]:
    reason = f"operator {action.replace('_daemon', '')} execution request"
    admission = build_artifact_retention_scheduler_daemon_operator_control_admission(
        operator_control_request=operator_request(
            action,
            idempotency_key=f"idem-0592-{action}",
            reason=reason,
        ),
        current_process=current_process,
        checked_at=CHECKED_AT,
    )
    preview = build_artifact_retention_scheduler_daemon_operator_control_command_preview(
        operator_control_admission=admission,
        checked_at=CHECKED_AT,
    )
    policy = build_artifact_retention_scheduler_daemon_operator_control_policy(
        checked_at=CHECKED_AT
    )
    return build_artifact_retention_scheduler_daemon_operator_control_facade(
        operator_control_policy=policy,
        operator_control_command_preview=preview,
        checked_at=CHECKED_AT,
    )


def execution_request(
    action: str = "start_daemon",
    *,
    current_process: dict[str, object] | None = None,
    execution_mode: str = "contract_only",
) -> dict[str, object]:
    return build_artifact_retention_scheduler_daemon_operator_control_execution_request(
        operator_control_facade=operator_facade(
            action,
            current_process=current_process,
        ),
        execution_mode=execution_mode,
        requested_at=REQUESTED_AT,
    )


def execution_result(
    action: str = "start_daemon",
    *,
    current_process: dict[str, object] | None = None,
    execution_mode: str = "contract_only",
) -> dict[str, object]:
    return build_artifact_retention_scheduler_daemon_operator_control_execution_result(
        operator_control_execution_request=execution_request(
            action,
            current_process=current_process,
            execution_mode=execution_mode,
        ),
        observed_at=OBSERVED_AT,
    )


def assert_safe_metadata_only(payload: dict[str, object]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    assert "postgresql://" not in serialized
    assert "postgresql+psycopg://" not in serialized
    assert "/data/nex-platform" not in serialized
    assert "nuri1004" not in serialized
    assert "ed6@c496em" not in serialized
    assert "storage_ref" not in serialized
    assert "raw_text" not in serialized


def test_execution_request_wraps_ready_facade_as_metadata_only_contract() -> None:
    payload = execution_request()
    summary = summarize_artifact_retention_scheduler_daemon_operator_control_execution_request(
        payload
    )

    assert payload["operator_control_execution_request_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_REQUEST_SCHEMA_VERSION
    )
    assert payload["service_id"] == "nex-ae-api"
    assert payload["action"] == "start_daemon"
    assert payload["facade_status"] == "READY"
    assert payload["execution_mode"] == "contract_only"
    assert payload["reason_hash"]
    assert payload["supervisor_command_count"] == 1
    assert payload["supervisor_actions"] == ["start_daemon"]
    assert payload["guardrails"]["execution_request_only"] is True
    assert payload["guardrails"]["supervisor_dispatch_performed"] is False
    assert payload["guardrails"]["ag_direct_process_control_allowed"] is False
    assert payload["metadata"]["execution_contract_only"] is True
    assert payload["metadata"]["ready_for_execution"] is False
    assert summary["ready_for_execution"] is False
    assert "mode=contract_only" in operator_control_execution_request_summary_line(
        payload
    )
    assert validate_artifact_retention_scheduler_daemon_operator_control_execution_request(
        payload
    ) == payload
    assert_safe_metadata_only(payload)


def test_fake_dry_run_execution_request_reserves_ready_dispatch_mode() -> None:
    payload = execution_request(
        execution_mode="fake_dry_run_supervisor_persistent_dispatch"
    )
    result = build_artifact_retention_scheduler_daemon_operator_control_execution_result(
        operator_control_execution_request=payload,
        observed_at=OBSERVED_AT,
    )

    assert payload["guardrails"]["contract_only_mode"] is False
    assert payload["guardrails"]["fake_dry_run_supervisor_dispatch_mode"] is True
    assert payload["metadata"]["ready_for_execution"] is True
    assert result["execution_status"] == "READY"
    assert result["decision_reason"] == "ready_for_fake_dry_run_supervisor_dispatch"
    assert result["guardrails"]["ready_status_reserved_for_fake_dry_run_dispatch"] is True
    assert result["metadata"]["dispatch_count"] == 0


@pytest.mark.parametrize(
    ("action", "current_process", "expected_status", "expected_reason"),
    (
        ("start_daemon", None, "BLOCKED", "execution_contract_only"),
        ("restart_daemon", process("MISSING"), "BLOCKED", "restart_requires_running_process"),
        ("stop_daemon", None, "NOOP", "daemon_not_running"),
        (
            "status_probe",
            None,
            "BLOCKED",
            "execution_contract_only",
        ),
    ),
)
def test_execution_result_preserves_facade_decisions_without_dispatch(
    action: str,
    current_process: dict[str, object] | None,
    expected_status: str,
    expected_reason: str,
) -> None:
    payload = execution_result(action, current_process=current_process)
    summary = summarize_artifact_retention_scheduler_daemon_operator_control_execution_result(
        payload
    )

    assert payload["operator_control_execution_result_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_RESULT_SCHEMA_VERSION
    )
    assert payload["execution_status"] == expected_status
    assert payload["decision_reason"] == expected_reason
    assert payload["supervisor_dispatch_results"] == []
    assert payload["guardrails"]["execution_result_only"] is True
    assert payload["guardrails"]["supervisor_adapter_invoked"] is False
    assert payload["metadata"]["blocked"] is (expected_status == "BLOCKED")
    assert payload["metadata"]["noop"] is (expected_status == "NOOP")
    assert summary["dispatch_count"] == 0
    assert "dispatches=0" in operator_control_execution_result_summary_line(payload)
    assert validate_artifact_retention_scheduler_daemon_operator_control_execution_result(
        payload
    ) == payload
    assert_safe_metadata_only(payload)


def test_restart_ready_execution_request_carries_stop_then_start_sequence() -> None:
    payload = execution_request(
        "restart_daemon",
        current_process=process("RUNNING", process_id=5201),
        execution_mode="fake_dry_run_supervisor_persistent_dispatch",
    )
    result = build_artifact_retention_scheduler_daemon_operator_control_execution_result(
        operator_control_execution_request=payload,
        observed_at=OBSERVED_AT,
    )

    assert payload["facade_status"] == "READY"
    assert payload["supervisor_command_count"] == 2
    assert payload["supervisor_actions"] == ["stop_daemon", "start_daemon"]
    assert payload["guardrails"]["restart_decomposes_to_stop_then_start"] is True
    assert payload["metadata"]["ready_for_execution"] is True
    assert result["execution_status"] == "READY"
    assert result["metadata"]["supervisor_actions"] == ["stop_daemon", "start_daemon"]


@pytest.mark.parametrize(
    ("mutate", "error_code", "detail"),
    (
        (
            lambda payload: [],
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_request_invalid",
            "object",
        ),
        (
            lambda payload: {
                **payload,
                "operator_control_execution_request_schema_version": "wrong",
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_request_schema_invalid",
            "schema",
        ),
        (
            lambda payload: {**payload, "service_id": "nex-ag"},
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_request_invalid",
            "service id",
        ),
        (
            lambda payload: {**payload, "scheduler_id": "other-scheduler"},
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_request_invalid",
            "scheduler scope",
        ),
        (
            lambda payload: {**payload, "operator_control_facade_id": "wrong"},
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_request_invalid",
            "source scope",
        ),
        (
            lambda payload: {**payload, "action": "stop_daemon"},
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_request_invalid",
            "action scope",
        ),
        (
            lambda payload: {**payload, "facade_status": "NOOP"},
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_request_invalid",
            "facade status",
        ),
        (
            lambda payload: {**payload, "execution_mode": "production"},
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_request_invalid",
            "mode",
        ),
        (
            lambda payload: {
                **payload,
                "operator_subject": {
                    **payload["operator_subject"],
                    "actor_id": "other-operator",
                },
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_request_invalid",
            "operator subject",
        ),
        (
            lambda payload: {**payload, "idempotency_key": "wrong"},
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_request_invalid",
            "idempotency scope",
        ),
        (
            lambda payload: {**payload, "reason_hash": "0" * 64},
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_request_invalid",
            "reason hash",
        ),
        (
            lambda payload: {**payload, "supervisor_command_count": True},
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_request_invalid",
            "supervisor_command_count",
        ),
        (
            lambda payload: {**payload, "supervisor_actions": ["stop_daemon"]},
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_request_invalid",
            "supervisor actions",
        ),
        (
            lambda payload: {
                **payload,
                "guardrails": {**payload["guardrails"], "metadata_only": False},
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_request_invalid",
            "guardrails",
        ),
        (
            lambda payload: {
                **payload,
                "metadata": {**payload["metadata"], "metadata_only": False},
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_request_invalid",
            "metadata",
        ),
        (
            lambda payload: {
                **payload,
                "operator_control_execution_request_id": "wrong",
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_request_invalid",
            "id",
        ),
    ),
)
def test_execution_request_validation_edges(
    mutate,
    error_code: str,
    detail: str,
) -> None:
    payload = execution_request()
    with pytest.raises(ArtifactHandoffError) as exc_info:
        validate_artifact_retention_scheduler_daemon_operator_control_execution_request(
            mutate(deepcopy(payload))
        )

    assert exc_info.value.error_code == error_code
    assert detail in exc_info.value.detail


@pytest.mark.parametrize(
    ("mutate", "error_code", "detail"),
    (
        (
            lambda payload: [],
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_result_invalid",
            "object",
        ),
        (
            lambda payload: {
                **payload,
                "operator_control_execution_result_schema_version": "wrong",
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_result_schema_invalid",
            "schema",
        ),
        (
            lambda payload: {**payload, "service_id": "nex-ag"},
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_result_invalid",
            "service id",
        ),
        (
            lambda payload: {**payload, "scheduler_id": "other-scheduler"},
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_result_invalid",
            "scheduler scope",
        ),
        (
            lambda payload: {**payload, "operator_control_facade_id": "wrong"},
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_result_invalid",
            "source scope",
        ),
        (
            lambda payload: {
                **payload,
                "operator_control_execution_request_id": "wrong",
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_result_invalid",
            "request scope",
        ),
        (
            lambda payload: {**payload, "action": "stop_daemon"},
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_result_invalid",
            "action scope",
        ),
        (
            lambda payload: {**payload, "execution_mode": "production"},
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_result_invalid",
            "mode",
        ),
        (
            lambda payload: {**payload, "execution_status": "SUCCEEDED"},
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_result_invalid",
            "status",
        ),
        (
            lambda payload: {**payload, "decision_reason": "wrong"},
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_result_invalid",
            "decision reason",
        ),
        (
            lambda payload: {
                **payload,
                "supervisor_dispatch_results": [{"private": "not-yet"}],
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_result_invalid",
            "dispatch results",
        ),
        (
            lambda payload: {
                **payload,
                "guardrails": {**payload["guardrails"], "metadata_only": False},
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_result_invalid",
            "guardrails",
        ),
        (
            lambda payload: {
                **payload,
                "metadata": {**payload["metadata"], "metadata_only": False},
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_result_invalid",
            "metadata",
        ),
        (
            lambda payload: {
                **payload,
                "operator_control_execution_result_id": "wrong",
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_result_invalid",
            "id",
        ),
    ),
)
def test_execution_result_validation_edges(
    mutate,
    error_code: str,
    detail: str,
) -> None:
    payload = execution_result()
    with pytest.raises(ArtifactHandoffError) as exc_info:
        validate_artifact_retention_scheduler_daemon_operator_control_execution_result(
            mutate(deepcopy(payload))
        )

    assert exc_info.value.error_code == error_code
    assert detail in exc_info.value.detail
