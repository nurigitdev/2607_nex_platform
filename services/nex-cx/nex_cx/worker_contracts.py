from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Mapping

from nex_runtime import RUNNING as JOB_RUNNING, JobQueueError, validate_common_job


CX_WORKER_EXECUTION_SCHEMA_VERSION = "cx_worker_execution.v1"

CLAIMED = "CLAIMED"
RUNNING = "RUNNING"
CANCELLATION_REQUESTED = "CANCELLATION_REQUESTED"
SUCCEEDED = "SUCCEEDED"
RETRY_SCHEDULED = "RETRY_SCHEDULED"
DEAD_LETTERED = "DEAD_LETTERED"
CANCELLED = "CANCELLED"

ACTIVE_EXECUTION_STATES = (CLAIMED, RUNNING, CANCELLATION_REQUESTED)
TERMINAL_EXECUTION_STATES = (
    SUCCEEDED,
    RETRY_SCHEDULED,
    DEAD_LETTERED,
    CANCELLED,
)
EXECUTION_STATES = ACTIVE_EXECUTION_STATES + TERMINAL_EXECUTION_STATES

VALID_EXECUTION_TRANSITIONS = {
    CLAIMED: (
        RUNNING,
        CANCELLATION_REQUESTED,
        RETRY_SCHEDULED,
        DEAD_LETTERED,
        CANCELLED,
    ),
    RUNNING: (
        CANCELLATION_REQUESTED,
        SUCCEEDED,
        RETRY_SCHEDULED,
        DEAD_LETTERED,
    ),
    CANCELLATION_REQUESTED: (
        SUCCEEDED,
        RETRY_SCHEDULED,
        DEAD_LETTERED,
        CANCELLED,
    ),
    SUCCEEDED: (),
    RETRY_SCHEDULED: (),
    DEAD_LETTERED: (),
    CANCELLED: (),
}

CURRENT_CX_WORKLOADS = {
    "document_ingestion": "cx.document_ingestion",
    "document_processing": "cx.document_processing",
    "remediation_execution": "cx.remediation_execution",
}


@dataclass(frozen=True)
class CxWorkerExecutionPolicy:
    lease_ttl_seconds: int = 120
    cancellation_check_interval_seconds: int = 5
    max_batch_jobs: int = 10

    def __post_init__(self) -> None:
        _positive_int(self.lease_ttl_seconds, "lease_ttl_seconds")
        _positive_int(
            self.cancellation_check_interval_seconds,
            "cancellation_check_interval_seconds",
        )
        _bounded_positive_int(self.max_batch_jobs, "max_batch_jobs", maximum=100)


@dataclass(frozen=True)
class CxWorkerContractError(Exception):
    error_code: str
    detail: str
    status_code: int = 422

    def __str__(self) -> str:
        return self.detail


def build_cx_worker_execution(
    job: Mapping[str, Any],
    *,
    worker_id: str,
    worker_type: str,
    workload: str,
    lease_expires_at: str,
    observed_at: str | None = None,
) -> dict[str, Any]:
    normalized_job = _running_job(job)
    resolved_workload = _required_string(workload, "workload")
    expected_job_type = CURRENT_CX_WORKLOADS.get(resolved_workload)
    if expected_job_type is None:
        raise CxWorkerContractError(
            error_code="cx.worker_execution.workload_invalid",
            detail="workload must name a registered CX worker workload.",
        )
    if normalized_job["job_type"] != expected_job_type:
        raise CxWorkerContractError(
            error_code="cx.worker_execution.job_type_mismatch",
            detail="job_type does not match the selected CX workload.",
            status_code=409,
        )
    observed = _timestamp(observed_at or _utc_now(), "observed_at")
    lease_expiry = _timestamp(lease_expires_at, "lease_expires_at")
    if lease_expiry <= observed:
        raise CxWorkerContractError(
            error_code="cx.worker_execution.lease_expired",
            detail="lease_expires_at must be later than observed_at.",
            status_code=409,
        )
    execution = {
        "execution_schema_version": CX_WORKER_EXECUTION_SCHEMA_VERSION,
        "execution_id": (
            f"{normalized_job['job_id']}:{normalized_job['attempt_count']}"
        ),
        "job_id": str(normalized_job["job_id"]),
        "job_type": str(normalized_job["job_type"]),
        "workload": resolved_workload,
        "worker_id": _required_string(worker_id, "worker_id"),
        "worker_type": _required_string(worker_type, "worker_type"),
        "state": CLAIMED,
        "state_version": 1,
        "attempt_count": int(normalized_job["attempt_count"]),
        "max_attempts": int(normalized_job["max_attempts"]),
        "retryable": bool(normalized_job["retryable"]),
        "trace_id": str(normalized_job["trace_id"]),
        "request_id": str(normalized_job["request_id"]),
        "subject_ref": deepcopy(normalized_job["subject_ref"]),
        "lease_expires_at": _wire_timestamp(lease_expiry),
        "cancellation_requested_at": None,
        "error_code": None,
        "started_at": _wire_timestamp(observed),
        "updated_at": _wire_timestamp(observed),
        "completed_at": None,
    }
    return validate_cx_worker_execution(execution)


def transition_cx_worker_execution(
    execution: Mapping[str, Any],
    target_state: str,
    *,
    observed_at: str | None = None,
    error_code: str | None = None,
) -> dict[str, Any]:
    normalized = validate_cx_worker_execution(execution)
    target = _execution_state(target_state)
    if target == normalized["state"]:
        return normalized
    if target not in VALID_EXECUTION_TRANSITIONS[normalized["state"]]:
        raise CxWorkerContractError(
            error_code="cx.worker_execution.transition_invalid",
            detail=(
                f"cannot transition CX worker execution from "
                f"{normalized['state']} to {target}"
            ),
            status_code=409,
        )
    observed = _timestamp(observed_at or _utc_now(), "observed_at")
    if observed < _timestamp(normalized["updated_at"], "updated_at"):
        raise CxWorkerContractError(
            error_code="cx.worker_execution.time_regression",
            detail="worker execution timestamps must not move backwards.",
            status_code=409,
        )
    updated = deepcopy(normalized)
    updated["state"] = target
    updated["state_version"] += 1
    updated["updated_at"] = _wire_timestamp(observed)
    if target == CANCELLATION_REQUESTED:
        updated["cancellation_requested_at"] = _wire_timestamp(observed)
    if target in {RETRY_SCHEDULED, DEAD_LETTERED}:
        updated["error_code"] = _required_string(error_code, "error_code")
    elif error_code is not None:
        raise CxWorkerContractError(
            error_code="cx.worker_execution.error_code_unexpected",
            detail="error_code is only valid for retry or dead-letter outcomes.",
        )
    if target in TERMINAL_EXECUTION_STATES:
        updated["completed_at"] = _wire_timestamp(observed)
        updated["lease_expires_at"] = None
    return validate_cx_worker_execution(updated)


def validate_cx_worker_execution(
    execution: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(execution, Mapping):
        raise CxWorkerContractError(
            error_code="cx.worker_execution.invalid",
            detail="worker execution must be an object.",
        )
    normalized = deepcopy(dict(execution))
    required = (
        "execution_schema_version",
        "execution_id",
        "job_id",
        "job_type",
        "workload",
        "worker_id",
        "worker_type",
        "state",
        "state_version",
        "attempt_count",
        "max_attempts",
        "retryable",
        "trace_id",
        "request_id",
        "subject_ref",
        "lease_expires_at",
        "cancellation_requested_at",
        "error_code",
        "started_at",
        "updated_at",
        "completed_at",
    )
    missing = [field for field in required if field not in normalized]
    if missing:
        raise CxWorkerContractError(
            error_code="cx.worker_execution.fields_missing",
            detail=f"worker execution is missing fields: {', '.join(missing)}",
        )
    if normalized["execution_schema_version"] != CX_WORKER_EXECUTION_SCHEMA_VERSION:
        raise CxWorkerContractError(
            error_code="cx.worker_execution.schema_version_invalid",
            detail="execution_schema_version is unsupported.",
        )
    for field in (
        "execution_id",
        "job_id",
        "job_type",
        "workload",
        "worker_id",
        "worker_type",
        "trace_id",
        "request_id",
    ):
        normalized[field] = _required_string(normalized[field], field)
    normalized["state"] = _execution_state(normalized["state"])
    _bounded_positive_int(normalized["state_version"], "state_version")
    _bounded_positive_int(normalized["attempt_count"], "attempt_count")
    _bounded_positive_int(normalized["max_attempts"], "max_attempts")
    if normalized["attempt_count"] > normalized["max_attempts"]:
        raise CxWorkerContractError(
            error_code="cx.worker_execution.attempt_invalid",
            detail="attempt_count must not exceed max_attempts.",
        )
    if not isinstance(normalized["retryable"], bool):
        raise CxWorkerContractError(
            error_code="cx.worker_execution.retryable_invalid",
            detail="retryable must be a boolean.",
        )
    subject_ref = normalized["subject_ref"]
    if not isinstance(subject_ref, Mapping):
        raise CxWorkerContractError(
            error_code="cx.worker_execution.subject_ref_invalid",
            detail="subject_ref must be an object.",
        )
    normalized["subject_ref"] = {
        "type": _required_string(subject_ref.get("type"), "subject_ref.type"),
        "id": _required_string(subject_ref.get("id"), "subject_ref.id"),
    }
    for field in ("started_at", "updated_at"):
        normalized[field] = _wire_timestamp(_timestamp(normalized[field], field))
    for field in (
        "lease_expires_at",
        "cancellation_requested_at",
        "completed_at",
    ):
        if normalized[field] is not None:
            normalized[field] = _wire_timestamp(
                _timestamp(normalized[field], field)
            )
    if normalized["error_code"] is not None:
        normalized["error_code"] = _required_string(
            normalized["error_code"], "error_code"
        )
    _validate_state_fields(normalized)
    return normalized


def project_cx_worker_execution(
    execution: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = validate_cx_worker_execution(execution)
    return {
        field: deepcopy(normalized[field])
        for field in (
            "execution_schema_version",
            "execution_id",
            "job_id",
            "job_type",
            "workload",
            "worker_id",
            "worker_type",
            "state",
            "state_version",
            "attempt_count",
            "max_attempts",
            "retryable",
            "trace_id",
            "request_id",
            "subject_ref",
            "lease_expires_at",
            "cancellation_requested_at",
            "error_code",
            "started_at",
            "updated_at",
            "completed_at",
        )
    }


def _validate_state_fields(execution: Mapping[str, Any]) -> None:
    state = execution["state"]
    if state in ACTIVE_EXECUTION_STATES and execution["lease_expires_at"] is None:
        raise CxWorkerContractError(
            error_code="cx.worker_execution.lease_required",
            detail="active worker executions require lease_expires_at.",
        )
    if state in TERMINAL_EXECUTION_STATES and execution["completed_at"] is None:
        raise CxWorkerContractError(
            error_code="cx.worker_execution.completed_at_required",
            detail="terminal worker executions require completed_at.",
        )
    if state == CANCELLATION_REQUESTED and not execution[
        "cancellation_requested_at"
    ]:
        raise CxWorkerContractError(
            error_code="cx.worker_execution.cancellation_time_required",
            detail="cancellation_requested_at is required for cancellation state.",
        )
    if state in {RETRY_SCHEDULED, DEAD_LETTERED} and not execution["error_code"]:
        raise CxWorkerContractError(
            error_code="cx.worker_execution.error_code_required",
            detail="retry and dead-letter outcomes require error_code.",
        )


def _running_job(job: Mapping[str, Any]) -> dict[str, Any]:
    try:
        normalized = validate_common_job(deepcopy(dict(job)))
    except (JobQueueError, TypeError, ValueError) as exc:
        raise CxWorkerContractError(
            error_code="cx.worker_execution.job_invalid",
            detail=str(getattr(exc, "detail", "job is invalid.")),
        ) from exc
    if normalized["status"] != JOB_RUNNING:
        raise CxWorkerContractError(
            error_code="cx.worker_execution.job_not_running",
            detail="job must be atomically claimed before worker execution.",
            status_code=409,
        )
    return normalized


def _execution_state(value: object) -> str:
    state = _required_string(value, "state")
    if state not in EXECUTION_STATES:
        raise CxWorkerContractError(
            error_code="cx.worker_execution.state_invalid",
            detail=f"unsupported CX worker execution state: {state}",
        )
    return state


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CxWorkerContractError(
            error_code="cx.worker_execution.field_invalid",
            detail=f"{field_name} must be a non-empty string.",
        )
    return value.strip()


def _positive_int(value: object, field_name: str) -> int:
    return _bounded_positive_int(value, field_name)


def _bounded_positive_int(
    value: object,
    field_name: str,
    *,
    maximum: int | None = None,
) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise CxWorkerContractError(
            error_code="cx.worker_execution.integer_invalid",
            detail=f"{field_name} must be a positive integer.",
        )
    if maximum is not None and value > maximum:
        raise CxWorkerContractError(
            error_code="cx.worker_execution.integer_too_large",
            detail=f"{field_name} must be at most {maximum}.",
        )
    return value


def _timestamp(value: object, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise CxWorkerContractError(
            error_code="cx.worker_execution.timestamp_invalid",
            detail=f"{field_name} must be an ISO-8601 timestamp.",
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CxWorkerContractError(
            error_code="cx.worker_execution.timestamp_invalid",
            detail=f"{field_name} must be an ISO-8601 timestamp.",
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _wire_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
