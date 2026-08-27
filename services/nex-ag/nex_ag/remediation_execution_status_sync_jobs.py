from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from nex_runtime import build_common_job, build_subject_ref


AG_REMEDIATION_EXECUTION_STATUS_SYNC_JOB_PLAN_SCHEMA_VERSION = (
    "ag_remediation_execution_status_sync_job_plan.v1"
)
AG_REMEDIATION_EXECUTION_STATUS_SYNC_JOB_PAYLOAD_SCHEMA_VERSION = (
    "ag_remediation_execution_status_sync_job_payload.v1"
)
AG_REMEDIATION_EXECUTION_STATUS_SYNC_JOB_TYPE = (
    "ag.remediation_execution.status_sync"
)
AG_REMEDIATION_EXECUTION_STATUS_SYNC_SUBJECT_TYPE = (
    "ag.remediation_execution.status_sync"
)
AG_REMEDIATION_EXECUTION_STATUS_SYNC_READY_STATES = {"SYNC_REQUIRED"}
AG_REMEDIATION_EXECUTION_STATUS_SYNC_BLOCKED_STATES = {
    "NO_EXECUTION",
    "ORPHAN_EXECUTION",
    "TERMINAL_TASK_DIVERGED",
    "UNKNOWN_EXECUTION_STATUS",
}
AG_REMEDIATION_EXECUTION_STATUS_SYNC_DEFAULT_MAX_ATTEMPTS = 3

_SENSITIVE_KEY_PARTS = (
    "api_key",
    "authorization",
    "credential",
    "database_url",
    "password",
    "provider_endpoint",
    "provider_url",
    "raw_evidence",
    "raw_generation_output",
    "raw_output",
    "raw_prompt",
    "raw_source",
    "raw_text",
    "storage_path",
    "token",
)


@dataclass
class RemediationExecutionStatusSyncJobPlanningError(Exception):
    error_code: str
    detail: str
    status_code: int = 422

    def __str__(self) -> str:
        return self.detail


def build_remediation_execution_status_sync_job_plan(
    operation: Mapping[str, Any],
    *,
    requested_at: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    normalized = _normalize_operation(operation)
    debug_paths = _status_sync_debug_paths(normalized)
    redaction_summary = _status_sync_redaction_summary()
    plan = {
        "plan_schema_version": (
            AG_REMEDIATION_EXECUTION_STATUS_SYNC_JOB_PLAN_SCHEMA_VERSION
        ),
        "plan_status": "SKIPPED",
        "reason_code": "attention_not_required",
        "remediation_action_id": normalized["remediation_action_id"],
        "cx_generation_id": normalized["cx_generation_id"],
        "trace_id": normalized["trace_id"],
        "request_id": normalized["request_id"],
        "status_sync_state": normalized["status_sync_state"],
        "task_status": normalized["task_status"],
        "execution_status": normalized["execution_status"],
        "target_task_status": normalized["target_task_status"],
        "attention_required": normalized["attention_required"],
        "job": None,
        "job_admission": {
            "enqueue_required": False,
            "job_type": AG_REMEDIATION_EXECUTION_STATUS_SYNC_JOB_TYPE,
            "idempotency_key": None,
            "dedupe_key": None,
        },
        "debug_paths": debug_paths,
        "redaction_summary": redaction_summary,
    }

    if normalized["attention_required"] is not True:
        return plan

    status_sync_state = normalized["status_sync_state"]
    if status_sync_state in AG_REMEDIATION_EXECUTION_STATUS_SYNC_BLOCKED_STATES:
        plan["plan_status"] = "BLOCKED"
        plan["reason_code"] = f"{status_sync_state.lower()}_requires_operator_review"
        return plan
    if status_sync_state not in AG_REMEDIATION_EXECUTION_STATUS_SYNC_READY_STATES:
        plan["plan_status"] = "SKIPPED"
        plan["reason_code"] = "status_sync_state_not_actionable"
        return plan

    missing_runtime_fields = [
        field_name
        for field_name in ("trace_id", "request_id")
        if not normalized[field_name]
    ]
    if missing_runtime_fields:
        plan["plan_status"] = "BLOCKED"
        plan["reason_code"] = "runtime_correlation_missing"
        plan["job_admission"]["missing_fields"] = missing_runtime_fields
        return plan

    observed_requested_at = requested_at or _utc_now()
    job = build_remediation_execution_status_sync_job(
        normalized,
        requested_at=observed_requested_at,
        idempotency_key=idempotency_key,
    )
    plan["plan_status"] = "READY"
    plan["reason_code"] = None
    plan["job"] = job
    plan["job_admission"] = {
        "enqueue_required": True,
        "job_type": AG_REMEDIATION_EXECUTION_STATUS_SYNC_JOB_TYPE,
        "idempotency_key": job["idempotency_key"],
        "dedupe_key": f"{job['job_type']}:{job['idempotency_key']}",
    }
    return plan


def build_remediation_execution_status_sync_job(
    operation: Mapping[str, Any],
    *,
    requested_at: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    normalized = _normalize_operation(operation)
    if normalized["status_sync_state"] not in (
        AG_REMEDIATION_EXECUTION_STATUS_SYNC_READY_STATES
    ):
        raise RemediationExecutionStatusSyncJobPlanningError(
            error_code="ag.remediation_execution_status_sync_job_state_not_ready",
            detail="Only SYNC_REQUIRED remediation execution operations can be queued.",
            status_code=409,
        )
    if not normalized["trace_id"] or not normalized["request_id"]:
        raise RemediationExecutionStatusSyncJobPlanningError(
            error_code="ag.remediation_execution_status_sync_job_correlation_missing",
            detail="Status sync jobs require trace_id and request_id.",
            status_code=422,
        )

    action_id = _required_text(normalized, "remediation_action_id")
    cx_generation_id = _required_text(normalized, "cx_generation_id")
    created_at = requested_at or _utc_now()
    job = build_common_job(
        job_id=remediation_execution_status_sync_job_id(action_id),
        job_type=AG_REMEDIATION_EXECUTION_STATUS_SYNC_JOB_TYPE,
        trace_id=_required_text(normalized, "trace_id"),
        request_id=_required_text(normalized, "request_id"),
        subject_ref=build_subject_ref(
            AG_REMEDIATION_EXECUTION_STATUS_SYNC_SUBJECT_TYPE,
            action_id,
        ),
        idempotency_key=(
            _optional_text(idempotency_key)
            or remediation_execution_status_sync_idempotency_key(action_id)
        ),
        created_at=created_at,
        max_attempts=AG_REMEDIATION_EXECUTION_STATUS_SYNC_DEFAULT_MAX_ATTEMPTS,
        retryable=True,
        links={
            "ag_remediation_task": (
                f"/admin/v1/generation-audit/generations/{cx_generation_id}"
                f"/remediation-tasks/{action_id}"
            ),
            "ag_remediation_execution_operations": (
                "/admin/v1/operations/remediation-executions"
                f"?remediation_action_id={action_id}"
            ),
            "cx_remediation_execution": (
                f"/api/v1/generations/{cx_generation_id}"
                f"/remediation-executions/{action_id}"
            ),
        },
    )
    job["payload"] = _status_sync_job_payload(
        normalized,
        requested_at=created_at,
    )
    assert_remediation_execution_status_sync_job_redaction_safe(job)
    return job


def remediation_execution_status_sync_job_id(remediation_action_id: str) -> str:
    action_id = _required_text(
        {"remediation_action_id": remediation_action_id},
        "remediation_action_id",
    )
    return str(
        uuid5(
            NAMESPACE_URL,
            (
                "https://nex-platform.local/jobs/ag/"
                f"remediation-execution-status-sync/{action_id}"
            ),
        )
    )


def remediation_execution_status_sync_idempotency_key(
    remediation_action_id: str,
) -> str:
    action_id = _required_text(
        {"remediation_action_id": remediation_action_id},
        "remediation_action_id",
    )
    return f"ag-remediation-execution-status-sync:{action_id}"


def assert_remediation_execution_status_sync_job_redaction_safe(
    payload: Mapping[str, Any],
) -> None:
    _assert_no_sensitive_keys(payload, path="$")


def _normalize_operation(operation: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(operation, Mapping):
        raise RemediationExecutionStatusSyncJobPlanningError(
            error_code="ag.remediation_execution_status_sync_operation_invalid",
            detail="Remediation execution status sync planning requires an operation.",
        )
    return {
        "remediation_action_id": _required_text(operation, "remediation_action_id"),
        "cx_generation_id": _required_text(operation, "cx_generation_id"),
        "trace_id": _optional_text(operation.get("trace_id")),
        "request_id": _optional_text(operation.get("request_id")),
        "tenant_id": _optional_text(operation.get("tenant_id")),
        "operation_timestamp": _optional_text(operation.get("operation_timestamp")),
        "task_status": _optional_text(operation.get("task_status")),
        "execution_status": _optional_text(operation.get("execution_status")),
        "target_task_status": _optional_text(operation.get("target_task_status")),
        "status_sync_state": _required_text(operation, "status_sync_state"),
        "attention_required": operation.get("attention_required") is True,
        "attempt_no": _optional_int(operation.get("attempt_no")),
        "failure": deepcopy(_safe_failure(operation.get("failure"))),
    }


def _status_sync_job_payload(
    operation: Mapping[str, Any],
    *,
    requested_at: str,
) -> dict[str, Any]:
    payload = {
        "payload_schema_version": (
            AG_REMEDIATION_EXECUTION_STATUS_SYNC_JOB_PAYLOAD_SCHEMA_VERSION
        ),
        "remediation_action_id": operation["remediation_action_id"],
        "cx_generation_id": operation["cx_generation_id"],
        "tenant_id": operation["tenant_id"],
        "trace_id": operation["trace_id"],
        "request_id": operation["request_id"],
        "operation_timestamp": operation["operation_timestamp"],
        "requested_at": requested_at,
        "status_sync_state": operation["status_sync_state"],
        "task_status": operation["task_status"],
        "execution_status": operation["execution_status"],
        "target_task_status": operation["target_task_status"],
        "attempt_no": operation["attempt_no"],
        "failure": deepcopy(operation["failure"]),
        "debug_paths": _status_sync_debug_paths(operation),
        "redaction_summary": _status_sync_redaction_summary(),
    }
    assert_remediation_execution_status_sync_job_redaction_safe(payload)
    return payload


def _status_sync_debug_paths(operation: Mapping[str, Any]) -> dict[str, str]:
    action_id = str(operation.get("remediation_action_id") or "")
    cx_generation_id = str(operation.get("cx_generation_id") or "")
    return {
        "ag_remediation_task_path": (
            f"/admin/v1/generation-audit/generations/{cx_generation_id}"
            f"/remediation-tasks/{action_id}"
        ),
        "ag_remediation_execution_operations_path": (
            "/admin/v1/operations/remediation-executions"
            f"?remediation_action_id={action_id}"
        ),
        "cx_remediation_execution_path": (
            f"/api/v1/generations/{cx_generation_id}"
            f"/remediation-executions/{action_id}"
        ),
    }


def _safe_failure(value: object) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    return {
        "error_code": _optional_text(value.get("error_code")),
        "error_detail_sha256": _optional_text(value.get("error_detail_sha256")),
        "retryable": value.get("retryable") is True,
    }


def _status_sync_redaction_summary() -> dict[str, bool]:
    return {
        "raw_prompt_included": False,
        "raw_generation_output_included": False,
        "raw_source_document_text_included": False,
        "raw_evidence_included": False,
        "provider_detail_included": False,
    }


def _required_text(source: Mapping[str, Any], field_name: str) -> str:
    value = _optional_text(source.get(field_name))
    if value is None:
        raise RemediationExecutionStatusSyncJobPlanningError(
            error_code=(
                "ag.remediation_execution_status_sync_"
                f"{field_name}_required"
            ),
            detail=f"Status sync job planning requires {field_name}.",
        )
    return value


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return str(value)


def _optional_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError:
            return None
        return parsed if parsed >= 0 else None
    return None


def _assert_no_sensitive_keys(value: object, *, path: str) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_text = str(key)
            if path.endswith(".redaction_summary") and key_text.endswith("_included"):
                if nested is not False:
                    raise RemediationExecutionStatusSyncJobPlanningError(
                        error_code=(
                            "ag.remediation_execution_status_sync_job_sensitive_payload"
                        ),
                        detail=(
                            "Status sync job redaction summary must keep "
                            f"{path}.{key_text}=false."
                        ),
                    )
                continue
            if _is_sensitive_key(key_text):
                raise RemediationExecutionStatusSyncJobPlanningError(
                    error_code=(
                        "ag.remediation_execution_status_sync_job_sensitive_payload"
                    ),
                    detail=(
                        "Status sync job payload contains a sensitive key: "
                        f"{path}.{key_text}"
                    ),
                )
            _assert_no_sensitive_keys(nested, path=f"{path}.{key_text}")
        return
    if isinstance(value, list):
        for index, nested in enumerate(value):
            _assert_no_sensitive_keys(nested, path=f"{path}[{index}]")


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower()
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
