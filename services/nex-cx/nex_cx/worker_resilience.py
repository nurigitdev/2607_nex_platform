from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from nex_runtime import (
    FAILED,
    QUEUED,
    JobQueue,
    JobQueueError,
    JobRetryPolicy,
    build_job_error,
)


CX_WORKER_FAILURE_SETTLEMENT_SCHEMA_VERSION = "cx_worker_failure_settlement.v1"
TRANSIENT = "TRANSIENT"
PERMANENT = "PERMANENT"
POISON = "POISON"
FAILURE_CLASSES = (TRANSIENT, PERMANENT, POISON)
SAFE_FAILURE_DETAIL = "CX worker execution failed."
DEFAULT_PERMANENT_STATUS_CODES = frozenset(
    status for status in range(400, 500) if status not in {408, 409, 425, 429}
)


@dataclass(frozen=True)
class CxWorkerResilienceError(Exception):
    error_code: str
    detail: str
    status_code: int = 500
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class CxWorkerResiliencePolicy:
    initial_delay_seconds: int = 30
    max_delay_seconds: int = 900
    backoff_multiplier: float = 2.0
    poison_error_codes: tuple[str, ...] = (
        "cx.worker.poison",
        "cx.worker.payload_corrupt",
    )

    def __post_init__(self) -> None:
        try:
            JobRetryPolicy(
                initial_delay_seconds=self.initial_delay_seconds,
                max_delay_seconds=self.max_delay_seconds,
                backoff_multiplier=self.backoff_multiplier,
            )
        except JobQueueError as exc:
            raise CxWorkerResilienceError(
                error_code="cx.worker_resilience.retry_policy_invalid",
                detail=exc.detail,
                status_code=422,
            ) from exc
        if not isinstance(self.poison_error_codes, tuple) or not all(
            isinstance(item, str) and item.strip()
            for item in self.poison_error_codes
        ):
            raise CxWorkerResilienceError(
                error_code="cx.worker_resilience.poison_codes_invalid",
                detail="poison_error_codes must be a tuple of non-empty strings.",
                status_code=422,
            )

    def retry_policy(self) -> JobRetryPolicy:
        return JobRetryPolicy(
            initial_delay_seconds=self.initial_delay_seconds,
            max_delay_seconds=self.max_delay_seconds,
            backoff_multiplier=self.backoff_multiplier,
        )


def classify_worker_failure(
    failure: Exception,
    *,
    policy: CxWorkerResiliencePolicy | None = None,
) -> dict[str, Any]:
    resolved_policy = policy or CxWorkerResiliencePolicy()
    error_code = safe_failure_code(failure)
    explicit_class = getattr(failure, "failure_class", None)
    retryable = getattr(failure, "retryable", None)
    status_code = getattr(failure, "status_code", None)
    if error_code in resolved_policy.poison_error_codes or explicit_class == "poison":
        failure_class = POISON
    elif explicit_class in {"validation", "authorization", "contract", "permanent"}:
        failure_class = PERMANENT
    elif retryable is False:
        failure_class = PERMANENT
    elif isinstance(status_code, int) and status_code in DEFAULT_PERMANENT_STATUS_CODES:
        failure_class = PERMANENT
    else:
        failure_class = TRANSIENT
    return {
        "error_code": error_code,
        "failure_class": failure_class,
        "retryable": failure_class == TRANSIENT,
        "status_code": status_code if isinstance(status_code, int) else None,
    }


def settle_worker_failure(
    *,
    job_queue: JobQueue,
    job: Mapping[str, Any],
    failure: Exception,
    failed_at: str,
    policy: CxWorkerResiliencePolicy | None = None,
) -> dict[str, Any]:
    resolved_policy = policy or CxWorkerResiliencePolicy()
    classification = classify_worker_failure(failure, policy=resolved_policy)
    safe_error = build_job_error(
        error_code=classification["error_code"],
        detail=SAFE_FAILURE_DETAIL,
        retryable=bool(classification["retryable"]),
    )
    job_id = _required_string(job.get("job_id"), "job_id")
    try:
        if classification["retryable"]:
            persisted = job_queue.retry_job(
                job_id,
                error=safe_error,
                failed_at=failed_at,
                policy=resolved_policy.retry_policy(),
            )
        else:
            persisted = job_queue.dead_letter_job(
                job_id,
                error=safe_error,
                failed_at=failed_at,
            )
    except JobQueueError as exc:
        raise CxWorkerResilienceError(
            error_code="cx.worker_resilience.settlement_failed",
            detail=exc.detail,
            status_code=exc.status_code,
            retryable=exc.status_code >= 500,
        ) from exc
    action = "RETRY_SCHEDULED" if persisted["status"] == QUEUED else "DEAD_LETTERED"
    return {
        "settlement_schema_version": CX_WORKER_FAILURE_SETTLEMENT_SCHEMA_VERSION,
        "job_id": job_id,
        "job_type": str(persisted["job_type"]),
        "action": action,
        "failure_class": classification["failure_class"],
        "error_code": classification["error_code"],
        "attempt_count": int(persisted["attempt_count"]),
        "max_attempts": int(persisted["max_attempts"]),
        "retry_at": persisted.get("available_at") if action == "RETRY_SCHEDULED" else None,
        "dead_lettered": bool(
            persisted["status"] == FAILED
            and isinstance(persisted.get("error"), Mapping)
            and persisted["error"].get("dead_lettered") is True
        ),
        "failed_at": failed_at,
    }


def project_dead_letter_job(job: Mapping[str, Any]) -> dict[str, Any]:
    error = job.get("error")
    if (
        job.get("status") != FAILED
        or not isinstance(error, Mapping)
        or error.get("dead_lettered") is not True
    ):
        raise CxWorkerResilienceError(
            error_code="cx.worker_resilience.dead_letter_required",
            detail="The job is not a dead-lettered worker job.",
            status_code=409,
        )
    return {
        "job_id": _required_string(job.get("job_id"), "job_id"),
        "job_type": _required_string(job.get("job_type"), "job_type"),
        "status": FAILED,
        "attempt_count": int(job.get("attempt_count", 0)),
        "max_attempts": int(job.get("max_attempts", 0)),
        "error_code": _required_string(error.get("error_code"), "error_code"),
        "dead_lettered": True,
        "failed_at": _required_string(job.get("updated_at"), "updated_at"),
    }


def safe_failure_code(failure: Exception) -> str:
    value = getattr(failure, "error_code", None)
    if not isinstance(value, str) or not value.strip():
        return "cx.worker_resilience.handler_failed"
    return value.strip()[:160]


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CxWorkerResilienceError(
            error_code="cx.worker_resilience.field_invalid",
            detail=f"{field_name} must be a non-empty string.",
            status_code=422,
        )
    return value.strip()
