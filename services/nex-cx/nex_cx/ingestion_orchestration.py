from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid5


INGESTION_RUN_SCHEMA_VERSION = "cx_ingest_run.v1"
INGESTION_PIPELINE_STEPS = (
    "extraction",
    "chunking",
    "lexical_index",
    "embedding_index",
    "summary",
    "summary_embedding",
)

QUEUED = "QUEUED"
RUNNING = "RUNNING"
WAITING_RETRY = "WAITING_RETRY"
SUCCEEDED = "SUCCEEDED"
FAILED = "FAILED"
CANCELLED = "CANCELLED"

INGESTION_RUN_STATUSES = (
    QUEUED,
    RUNNING,
    WAITING_RETRY,
    SUCCEEDED,
    FAILED,
    CANCELLED,
)
TERMINAL_INGESTION_RUN_STATUSES = (SUCCEEDED, FAILED, CANCELLED)

PENDING = "PENDING"
STEP_RUNNING = "RUNNING"
STEP_SUCCEEDED = "SUCCEEDED"
STEP_SKIPPED = "SKIPPED"
STEP_FAILED = "FAILED"
INGESTION_STEP_STATUSES = (
    PENDING,
    STEP_RUNNING,
    STEP_SUCCEEDED,
    STEP_SKIPPED,
    STEP_FAILED,
)

_RUN_FIELDS = frozenset(
    {
        "run_schema_version",
        "run_id",
        "document_id",
        "job_id",
        "idempotency_key",
        "status",
        "current_step",
        "step_states",
        "attempt_count",
        "max_attempts",
        "checkpoint_version",
        "tenant_ref",
        "owner_subject_ref",
        "trace_id",
        "request_id",
        "lease_owner",
        "lease_expires_at",
        "retry_at",
        "last_error",
        "created_at",
        "updated_at",
        "completed_at",
    }
)
_STEP_FIELDS = frozenset(
    {
        "step_id",
        "status",
        "attempt_count",
        "output_ref",
        "started_at",
        "completed_at",
        "error_code",
    }
)
_REF_FIELDS = frozenset({"type", "id"})
_ERROR_FIELDS = frozenset(
    {"error_code", "retryable", "failed_step", "failed_at"}
)


@dataclass(frozen=True)
class IngestionOrchestrationError(Exception):
    error_code: str
    detail: str
    status_code: int = 409

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class IngestionOrchestrationPolicy:
    max_attempts: int = 3
    lease_ttl_seconds: int = 120
    retry_initial_delay_seconds: int = 30
    retry_max_delay_seconds: int = 900

    def __post_init__(self) -> None:
        _positive_int(self.max_attempts, "max_attempts")
        _positive_int(self.lease_ttl_seconds, "lease_ttl_seconds")
        _non_negative_int(
            self.retry_initial_delay_seconds,
            "retry_initial_delay_seconds",
        )
        _non_negative_int(self.retry_max_delay_seconds, "retry_max_delay_seconds")
        if self.retry_max_delay_seconds < self.retry_initial_delay_seconds:
            raise IngestionOrchestrationError(
                error_code="cx.ingestion_policy.retry_delay_invalid",
                detail=(
                    "retry_max_delay_seconds must be greater than or equal to "
                    "retry_initial_delay_seconds."
                ),
                status_code=422,
            )


def build_ingestion_run(
    *,
    document_id: str,
    job_id: str,
    idempotency_key: str,
    tenant_ref: Mapping[str, Any],
    owner_subject_ref: Mapping[str, Any],
    trace_id: str,
    request_id: str,
    created_at: str | None = None,
    run_id: str | None = None,
    policy: IngestionOrchestrationPolicy | None = None,
) -> dict[str, Any]:
    resolved_document_id = _required_string(document_id, "document_id")
    resolved_idempotency_key = _required_string(
        idempotency_key, "idempotency_key"
    )
    observed_at = created_at or _utc_now()
    resolved_run_id = run_id or str(
        uuid5(
            NAMESPACE_URL,
            f"cx-ingest-run:{resolved_document_id}:{resolved_idempotency_key}",
        )
    )
    resolved_policy = policy or IngestionOrchestrationPolicy()
    run = {
        "run_schema_version": INGESTION_RUN_SCHEMA_VERSION,
        "run_id": _required_string(resolved_run_id, "run_id"),
        "document_id": resolved_document_id,
        "job_id": _required_string(job_id, "job_id"),
        "idempotency_key": resolved_idempotency_key,
        "status": QUEUED,
        "current_step": INGESTION_PIPELINE_STEPS[0],
        "step_states": {
            step_id: _new_step_state(step_id) for step_id in INGESTION_PIPELINE_STEPS
        },
        "attempt_count": 0,
        "max_attempts": resolved_policy.max_attempts,
        "checkpoint_version": 0,
        "tenant_ref": _validate_ref(tenant_ref, "tenant_ref", expected_type="oa.tenant"),
        "owner_subject_ref": _validate_ref(
            owner_subject_ref,
            "owner_subject_ref",
            expected_type="oa.user",
        ),
        "trace_id": _required_string(trace_id, "trace_id"),
        "request_id": _required_string(request_id, "request_id"),
        "lease_owner": None,
        "lease_expires_at": None,
        "retry_at": None,
        "last_error": None,
        "created_at": _required_string(observed_at, "created_at"),
        "updated_at": observed_at,
        "completed_at": None,
    }
    return validate_ingestion_run(run)


def claim_ingestion_run(
    run: Mapping[str, Any],
    *,
    worker_id: str,
    lease_expires_at: str,
    observed_at: str | None = None,
    expected_checkpoint_version: int | None = None,
) -> dict[str, Any]:
    claimed = validate_ingestion_run(run)
    _require_version(claimed, expected_checkpoint_version)
    if claimed["status"] != QUEUED:
        raise _transition_error(claimed["status"], RUNNING)
    now = observed_at or _utc_now()
    step = claimed["step_states"][claimed["current_step"]]
    if step["status"] != PENDING:
        raise IngestionOrchestrationError(
            error_code="cx.ingestion_step.claim_invalid",
            detail="The current ingestion step must be pending before claim.",
        )
    step["status"] = STEP_RUNNING
    step["attempt_count"] += 1
    step["started_at"] = now
    step["completed_at"] = None
    step["error_code"] = None
    claimed["status"] = RUNNING
    claimed["attempt_count"] += 1
    claimed["lease_owner"] = _required_string(worker_id, "worker_id")
    claimed["lease_expires_at"] = _required_string(
        lease_expires_at, "lease_expires_at"
    )
    claimed["retry_at"] = None
    claimed["last_error"] = None
    return _bump_checkpoint(claimed, now)


def complete_ingestion_step(
    run: Mapping[str, Any],
    *,
    worker_id: str,
    output_ref: str,
    observed_at: str | None = None,
    skipped: bool = False,
    expected_checkpoint_version: int | None = None,
) -> dict[str, Any]:
    completed = validate_ingestion_run(run)
    _require_version(completed, expected_checkpoint_version)
    _require_active_lease(completed, worker_id)
    now = observed_at or _utc_now()
    current_step = str(completed["current_step"])
    step = completed["step_states"][current_step]
    if step["status"] != STEP_RUNNING:
        raise IngestionOrchestrationError(
            error_code="cx.ingestion_step.complete_invalid",
            detail="Only the running ingestion step can be completed.",
        )
    step["status"] = STEP_SKIPPED if skipped else STEP_SUCCEEDED
    step["output_ref"] = _required_string(output_ref, "output_ref")
    step["completed_at"] = now
    next_step = _next_step(current_step)
    if next_step is None:
        completed["status"] = SUCCEEDED
        completed["current_step"] = None
        completed["completed_at"] = now
        _release_lease(completed)
    else:
        completed["current_step"] = next_step
        next_state = completed["step_states"][next_step]
        next_state["status"] = STEP_RUNNING
        next_state["attempt_count"] += 1
        next_state["started_at"] = now
    return _bump_checkpoint(completed, now)


def fail_ingestion_step(
    run: Mapping[str, Any],
    *,
    worker_id: str,
    error_code: str,
    retryable: bool,
    retry_at: str | None = None,
    observed_at: str | None = None,
    expected_checkpoint_version: int | None = None,
) -> dict[str, Any]:
    failed = validate_ingestion_run(run)
    _require_version(failed, expected_checkpoint_version)
    _require_active_lease(failed, worker_id)
    now = observed_at or _utc_now()
    current_step = str(failed["current_step"])
    step = failed["step_states"][current_step]
    if step["status"] != STEP_RUNNING:
        raise IngestionOrchestrationError(
            error_code="cx.ingestion_step.fail_invalid",
            detail="Only the running ingestion step can fail.",
        )
    resolved_error_code = _required_string(error_code, "error_code")
    can_retry = bool(retryable) and failed["attempt_count"] < failed["max_attempts"]
    if can_retry and retry_at is None:
        raise IngestionOrchestrationError(
            error_code="cx.ingestion_retry.retry_at_required",
            detail="retry_at is required for a retryable ingestion failure.",
            status_code=422,
        )
    step["status"] = STEP_FAILED
    step["completed_at"] = now
    step["error_code"] = resolved_error_code
    failed["last_error"] = {
        "error_code": resolved_error_code,
        "retryable": can_retry,
        "failed_step": current_step,
        "failed_at": now,
    }
    if can_retry:
        failed["status"] = WAITING_RETRY
        failed["retry_at"] = _required_string(retry_at, "retry_at")
    else:
        failed["status"] = FAILED
        failed["retry_at"] = None
        failed["completed_at"] = now
    _release_lease(failed)
    return _bump_checkpoint(failed, now)


def requeue_ingestion_run(
    run: Mapping[str, Any],
    *,
    observed_at: str | None = None,
    expected_checkpoint_version: int | None = None,
) -> dict[str, Any]:
    requeued = validate_ingestion_run(run)
    _require_version(requeued, expected_checkpoint_version)
    if requeued["status"] != WAITING_RETRY:
        raise _transition_error(requeued["status"], QUEUED)
    current_step = str(requeued["current_step"])
    step = requeued["step_states"][current_step]
    step["status"] = PENDING
    step["output_ref"] = None
    step["started_at"] = None
    step["completed_at"] = None
    step["error_code"] = None
    requeued["status"] = QUEUED
    requeued["retry_at"] = None
    return _bump_checkpoint(requeued, observed_at or _utc_now())


def cancel_ingestion_run(
    run: Mapping[str, Any],
    *,
    observed_at: str | None = None,
    expected_checkpoint_version: int | None = None,
) -> dict[str, Any]:
    cancelled = validate_ingestion_run(run)
    _require_version(cancelled, expected_checkpoint_version)
    if cancelled["status"] in TERMINAL_INGESTION_RUN_STATUSES:
        raise _transition_error(cancelled["status"], CANCELLED)
    now = observed_at or _utc_now()
    cancelled["status"] = CANCELLED
    cancelled["completed_at"] = now
    cancelled["retry_at"] = None
    _release_lease(cancelled)
    return _bump_checkpoint(cancelled, now)


def validate_ingestion_run(run: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(run, Mapping):
        raise IngestionOrchestrationError(
            error_code="cx.ingestion_run.invalid",
            detail="Ingestion run must be an object.",
            status_code=422,
        )
    unknown = set(run) - _RUN_FIELDS
    missing = _RUN_FIELDS - set(run)
    if unknown or missing:
        raise IngestionOrchestrationError(
            error_code="cx.ingestion_run.shape_invalid",
            detail=_shape_detail("ingestion run", unknown=unknown, missing=missing),
            status_code=422,
        )
    normalized = deepcopy(dict(run))
    if normalized["run_schema_version"] != INGESTION_RUN_SCHEMA_VERSION:
        raise IngestionOrchestrationError(
            error_code="cx.ingestion_run.schema_version_invalid",
            detail=f"run_schema_version must be {INGESTION_RUN_SCHEMA_VERSION}.",
            status_code=422,
        )
    for field_name in (
        "run_id",
        "document_id",
        "job_id",
        "idempotency_key",
        "trace_id",
        "request_id",
        "created_at",
        "updated_at",
    ):
        _required_string(normalized[field_name], field_name)
    if normalized["status"] not in INGESTION_RUN_STATUSES:
        raise IngestionOrchestrationError(
            error_code="cx.ingestion_run.status_invalid",
            detail=f"Unsupported ingestion run status: {normalized['status']}",
            status_code=422,
        )
    _non_negative_int(normalized["attempt_count"], "attempt_count")
    _positive_int(normalized["max_attempts"], "max_attempts")
    _non_negative_int(normalized["checkpoint_version"], "checkpoint_version")
    normalized["tenant_ref"] = _validate_ref(
        normalized["tenant_ref"], "tenant_ref", expected_type="oa.tenant"
    )
    normalized["owner_subject_ref"] = _validate_ref(
        normalized["owner_subject_ref"],
        "owner_subject_ref",
        expected_type="oa.user",
    )
    _validate_optional_string(normalized["lease_owner"], "lease_owner")
    _validate_optional_string(normalized["lease_expires_at"], "lease_expires_at")
    _validate_optional_string(normalized["retry_at"], "retry_at")
    _validate_optional_string(normalized["completed_at"], "completed_at")
    _validate_error(normalized["last_error"])
    normalized["step_states"] = _validate_step_states(normalized["step_states"])
    current_step = normalized["current_step"]
    if current_step is not None and current_step not in INGESTION_PIPELINE_STEPS:
        raise IngestionOrchestrationError(
            error_code="cx.ingestion_run.current_step_invalid",
            detail="current_step must identify a known ingestion pipeline step.",
            status_code=422,
        )
    if normalized["status"] == SUCCEEDED and current_step is not None:
        raise IngestionOrchestrationError(
            error_code="cx.ingestion_run.terminal_step_invalid",
            detail="A succeeded ingestion run cannot have a current step.",
            status_code=422,
        )
    if normalized["status"] == RUNNING:
        if not normalized["lease_owner"] or not normalized["lease_expires_at"]:
            raise IngestionOrchestrationError(
                error_code="cx.ingestion_run.lease_required",
                detail="A running ingestion run requires an active lease.",
                status_code=422,
            )
    return normalized


def _new_step_state(step_id: str) -> dict[str, Any]:
    return {
        "step_id": step_id,
        "status": PENDING,
        "attempt_count": 0,
        "output_ref": None,
        "started_at": None,
        "completed_at": None,
        "error_code": None,
    }


def _validate_step_states(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, Mapping) or set(value) != set(INGESTION_PIPELINE_STEPS):
        raise IngestionOrchestrationError(
            error_code="cx.ingestion_run.steps_invalid",
            detail="step_states must contain every canonical ingestion step exactly once.",
            status_code=422,
        )
    normalized: dict[str, dict[str, Any]] = {}
    for step_id in INGESTION_PIPELINE_STEPS:
        state = value[step_id]
        if not isinstance(state, Mapping) or set(state) != _STEP_FIELDS:
            raise IngestionOrchestrationError(
                error_code="cx.ingestion_step.shape_invalid",
                detail=f"Invalid checkpoint shape for ingestion step: {step_id}",
                status_code=422,
            )
        item = deepcopy(dict(state))
        if item["step_id"] != step_id or item["status"] not in INGESTION_STEP_STATUSES:
            raise IngestionOrchestrationError(
                error_code="cx.ingestion_step.value_invalid",
                detail=f"Invalid checkpoint value for ingestion step: {step_id}",
                status_code=422,
            )
        _non_negative_int(item["attempt_count"], f"{step_id}.attempt_count")
        for field_name in ("output_ref", "started_at", "completed_at", "error_code"):
            _validate_optional_string(item[field_name], f"{step_id}.{field_name}")
        normalized[step_id] = item
    return normalized


def _validate_ref(
    value: Mapping[str, Any],
    field_name: str,
    *,
    expected_type: str,
) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != _REF_FIELDS:
        raise IngestionOrchestrationError(
            error_code=f"cx.ingestion_run.{field_name}_invalid",
            detail=f"{field_name} must contain only type and id.",
            status_code=422,
        )
    ref_type = _required_string(value.get("type"), f"{field_name}.type")
    if ref_type != expected_type:
        raise IngestionOrchestrationError(
            error_code=f"cx.ingestion_run.{field_name}_type_invalid",
            detail=f"{field_name}.type must be {expected_type}.",
            status_code=422,
        )
    return {"type": ref_type, "id": _required_string(value.get("id"), f"{field_name}.id")}


def _validate_error(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, Mapping) or set(value) != _ERROR_FIELDS:
        raise IngestionOrchestrationError(
            error_code="cx.ingestion_run.last_error_invalid",
            detail="last_error must use the metadata-only ingestion error shape.",
            status_code=422,
        )
    _required_string(value.get("error_code"), "last_error.error_code")
    _required_string(value.get("failed_step"), "last_error.failed_step")
    _required_string(value.get("failed_at"), "last_error.failed_at")
    if not isinstance(value.get("retryable"), bool):
        raise IngestionOrchestrationError(
            error_code="cx.ingestion_run.last_error_invalid",
            detail="last_error.retryable must be a boolean.",
            status_code=422,
        )


def _require_active_lease(run: Mapping[str, Any], worker_id: str) -> None:
    if run["status"] != RUNNING:
        raise _transition_error(str(run["status"]), RUNNING)
    resolved_worker_id = _required_string(worker_id, "worker_id")
    if run["lease_owner"] != resolved_worker_id:
        raise IngestionOrchestrationError(
            error_code="cx.ingestion_run.lease_owner_mismatch",
            detail="The ingestion run lease belongs to another worker.",
            status_code=409,
        )


def _require_version(run: Mapping[str, Any], expected: int | None) -> None:
    if expected is None:
        return
    _non_negative_int(expected, "expected_checkpoint_version")
    if run["checkpoint_version"] != expected:
        raise IngestionOrchestrationError(
            error_code="cx.ingestion_run.checkpoint_conflict",
            detail="The ingestion checkpoint version changed before this operation.",
            status_code=409,
        )


def _next_step(current_step: str) -> str | None:
    index = INGESTION_PIPELINE_STEPS.index(current_step)
    return (
        INGESTION_PIPELINE_STEPS[index + 1]
        if index + 1 < len(INGESTION_PIPELINE_STEPS)
        else None
    )


def _release_lease(run: dict[str, Any]) -> None:
    run["lease_owner"] = None
    run["lease_expires_at"] = None


def _bump_checkpoint(run: dict[str, Any], observed_at: str) -> dict[str, Any]:
    run["checkpoint_version"] += 1
    run["updated_at"] = observed_at
    return validate_ingestion_run(run)


def _transition_error(current: str, target: str) -> IngestionOrchestrationError:
    return IngestionOrchestrationError(
        error_code="cx.ingestion_run.transition_invalid",
        detail=f"Invalid ingestion run transition: {current} -> {target}",
        status_code=409,
    )


def _shape_detail(label: str, *, unknown: set[str], missing: set[str]) -> str:
    parts = []
    if unknown:
        parts.append(f"unknown={','.join(sorted(unknown))}")
    if missing:
        parts.append(f"missing={','.join(sorted(missing))}")
    return f"Invalid {label} shape: {'; '.join(parts)}"


def _required_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IngestionOrchestrationError(
            error_code="cx.ingestion_run.field_invalid",
            detail=f"{field_name} must be a non-empty string.",
            status_code=422,
        )
    return value.strip()


def _validate_optional_string(value: Any, field_name: str) -> None:
    if value is not None:
        _required_string(value, field_name)


def _positive_int(value: Any, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise IngestionOrchestrationError(
            error_code="cx.ingestion_run.field_invalid",
            detail=f"{field_name} must be a positive integer.",
            status_code=422,
        )


def _non_negative_int(value: Any, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise IngestionOrchestrationError(
            error_code="cx.ingestion_run.field_invalid",
            detail=f"{field_name} must be a non-negative integer.",
            status_code=422,
        )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
