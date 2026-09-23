from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from nex_runtime import (
    CANCELLED as JOB_CANCELLED,
    FAILED as JOB_FAILED,
    QUEUED as JOB_QUEUED,
    RUNNING as JOB_RUNNING,
    JobQueue,
    JobQueueError,
    build_job_error,
)
from nex_cx.worker_contracts import (
    CANCELLED,
    CANCELLATION_REQUESTED,
    DEAD_LETTERED,
    RETRY_SCHEDULED,
    RUNNING,
    SUCCEEDED,
    project_cx_worker_execution,
    transition_cx_worker_execution,
)
from nex_cx.worker_leases import (
    CxWorkerLeasePolicy,
    SqlAlchemyCxWorkerLeaseStore,
    claim_next_worker_execution,
)


CX_WORKER_RUNTIME_RESULT_SCHEMA_VERSION = "cx_worker_runtime_result.v1"
SAFE_HANDLER_FAILURE_DETAIL = "CX worker handler execution failed."
DEFAULT_MAX_DURATION_SECONDS = 300
MAX_DURATION_SECONDS = 3_600

WorkerClock = Callable[[], str]


class CxCooperativeWorkerHandler(Protocol):
    def __call__(
        self,
        execution: dict[str, Any],
        cancellation: CxCancellationToken,
    ) -> Mapping[str, Any] | None:
        ...


@dataclass(frozen=True)
class CxWorkerRuntimeError(Exception):
    error_code: str
    detail: str
    status_code: int = 500
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class CxWorkerCancellationRequested(Exception):
    job_id: str
    observed_at: str

    @property
    def error_code(self) -> str:
        return "cx.worker_runtime.cancellation_requested"


@dataclass(frozen=True)
class CxWorkerRuntimePolicy:
    max_jobs: int = 10
    max_duration_seconds: int = DEFAULT_MAX_DURATION_SECONDS
    stop_on_failure: bool = True

    def __post_init__(self) -> None:
        if (
            not isinstance(self.max_jobs, int)
            or isinstance(self.max_jobs, bool)
            or self.max_jobs < 1
            or self.max_jobs > 100
        ):
            raise CxWorkerRuntimeError(
                error_code="cx.worker_runtime.max_jobs_invalid",
                detail="max_jobs must be an integer between 1 and 100.",
                status_code=422,
            )
        if (
            not isinstance(self.max_duration_seconds, int)
            or isinstance(self.max_duration_seconds, bool)
            or self.max_duration_seconds < 1
            or self.max_duration_seconds > MAX_DURATION_SECONDS
        ):
            raise CxWorkerRuntimeError(
                error_code="cx.worker_runtime.max_duration_invalid",
                detail=(
                    "max_duration_seconds must be an integer between 1 and "
                    f"{MAX_DURATION_SECONDS}."
                ),
                status_code=422,
            )
        if not isinstance(self.stop_on_failure, bool):
            raise CxWorkerRuntimeError(
                error_code="cx.worker_runtime.stop_on_failure_invalid",
                detail="stop_on_failure must be a boolean.",
                status_code=422,
            )


@dataclass(frozen=True)
class CxCancellationToken:
    job_queue: JobQueue
    job_id: str

    def checkpoint(self, *, observed_at: str | None = None) -> None:
        observed = _wire_timestamp(
            _timestamp(observed_at or _utc_now(), "observed_at")
        )
        try:
            job = self.job_queue.get_job(self.job_id)
        except JobQueueError as exc:
            raise _dependency_error("cancellation_read_failed", exc) from exc
        if job is None:
            raise CxWorkerRuntimeError(
                error_code="cx.worker_runtime.job_not_found",
                detail="The worker job was not found at a cancellation checkpoint.",
                status_code=404,
            )
        if job["status"] == JOB_CANCELLED:
            raise CxWorkerCancellationRequested(
                job_id=self.job_id,
                observed_at=observed,
            )
        if job["status"] != JOB_RUNNING:
            raise CxWorkerRuntimeError(
                error_code="cx.worker_runtime.job_not_running",
                detail="The worker job is no longer running.",
                status_code=409,
            )


def request_worker_cancellation(
    job_queue: JobQueue,
    job_id: str,
    *,
    observed_at: str | None = None,
) -> dict[str, Any]:
    resolved_job_id = _required_string(job_id, "job_id")
    observed = _wire_timestamp(_timestamp(observed_at or _utc_now(), "observed_at"))
    try:
        previous = job_queue.get_job(resolved_job_id)
        if previous is None:
            raise CxWorkerRuntimeError(
                error_code="cx.worker_runtime.job_not_found",
                detail="The worker job was not found.",
                status_code=404,
            )
        cancelled = job_queue.cancel_job(resolved_job_id, updated_at=observed)
    except CxWorkerRuntimeError:
        raise
    except JobQueueError as exc:
        raise _dependency_error("cancellation_write_failed", exc) from exc
    return {
        "job_id": resolved_job_id,
        "job_type": str(cancelled["job_type"]),
        "status": str(cancelled["status"]),
        "already_cancelled": previous["status"] == JOB_CANCELLED,
        "cancellation_requested_at": observed,
    }


def run_bounded_worker_batch(
    *,
    job_queue: JobQueue,
    lease_store: SqlAlchemyCxWorkerLeaseStore,
    handler: CxCooperativeWorkerHandler,
    worker_id: str,
    worker_type: str,
    workload: str,
    runtime_policy: CxWorkerRuntimePolicy | None = None,
    lease_policy: CxWorkerLeasePolicy | None = None,
    clock: WorkerClock | None = None,
) -> dict[str, Any]:
    resolved_runtime_policy = runtime_policy or CxWorkerRuntimePolicy()
    observed_clock = clock or _utc_now
    started_at = _timestamp(observed_clock(), "started_at")
    executions: list[dict[str, Any]] = []
    stop_reason = "MAX_JOBS"
    for _ in range(resolved_runtime_policy.max_jobs):
        observed = _timestamp(observed_clock(), "observed_at")
        if (observed - started_at).total_seconds() >= (
            resolved_runtime_policy.max_duration_seconds
        ):
            stop_reason = "MAX_DURATION"
            break
        execution = claim_next_worker_execution(
            job_queue=job_queue,
            lease_store=lease_store,
            worker_id=worker_id,
            worker_type=worker_type,
            workload=workload,
            policy=lease_policy,
            observed_at=_wire_timestamp(observed),
        )
        if execution is None:
            stop_reason = "IDLE"
            break
        outcome = _execute_claimed(
            execution,
            job_queue=job_queue,
            handler=handler,
            observed_clock=observed_clock,
        )
        executions.append(outcome)
        if (
            outcome["state"] in {RETRY_SCHEDULED, DEAD_LETTERED}
            and resolved_runtime_policy.stop_on_failure
        ):
            stop_reason = "FAILURE"
            break
    completed_at = _timestamp(observed_clock(), "completed_at")
    return _runtime_result(
        worker_id=worker_id,
        worker_type=worker_type,
        workload=workload,
        started_at=started_at,
        completed_at=completed_at,
        stop_reason=stop_reason,
        executions=executions,
    )


def _execute_claimed(
    execution: Mapping[str, Any],
    *,
    job_queue: JobQueue,
    handler: CxCooperativeWorkerHandler,
    observed_clock: WorkerClock,
) -> dict[str, Any]:
    started = transition_cx_worker_execution(
        execution,
        RUNNING,
        observed_at=observed_clock(),
    )
    token = CxCancellationToken(
        job_queue=job_queue,
        job_id=str(started["job_id"]),
    )
    try:
        token.checkpoint(observed_at=observed_clock())
        handler(deepcopy(started), token)
        token.checkpoint(observed_at=observed_clock())
        completed_at = observed_clock()
        job_queue.complete_job(str(started["job_id"]), updated_at=completed_at)
        return transition_cx_worker_execution(
            started,
            SUCCEEDED,
            observed_at=completed_at,
        )
    except CxWorkerCancellationRequested as exc:
        current = _job(job_queue, str(started["job_id"]))
        if current["status"] != JOB_CANCELLED:
            request_worker_cancellation(
                job_queue,
                str(started["job_id"]),
                observed_at=exc.observed_at,
            )
        cancelling = transition_cx_worker_execution(
            started,
            CANCELLATION_REQUESTED,
            observed_at=exc.observed_at,
        )
        return transition_cx_worker_execution(
            cancelling,
            CANCELLED,
            observed_at=exc.observed_at,
        )
    except CxWorkerRuntimeError:
        raise
    except Exception as exc:
        error_code = _safe_error_code(exc)
        failed_at = observed_clock()
        try:
            job = job_queue.retry_job(
                str(started["job_id"]),
                error=build_job_error(
                    error_code=error_code,
                    detail=SAFE_HANDLER_FAILURE_DETAIL,
                    retryable=True,
                ),
                failed_at=failed_at,
            )
        except JobQueueError as queue_exc:
            raise _dependency_error("failure_write_failed", queue_exc) from queue_exc
        target = RETRY_SCHEDULED if job["status"] == JOB_QUEUED else DEAD_LETTERED
        return transition_cx_worker_execution(
            started,
            target,
            observed_at=failed_at,
            error_code=error_code,
        )


def _runtime_result(
    *,
    worker_id: str,
    worker_type: str,
    workload: str,
    started_at: datetime,
    completed_at: datetime,
    stop_reason: str,
    executions: list[dict[str, Any]],
) -> dict[str, Any]:
    projected = [project_cx_worker_execution(item) for item in executions]
    return {
        "runtime_result_schema_version": CX_WORKER_RUNTIME_RESULT_SCHEMA_VERSION,
        "worker_id": _required_string(worker_id, "worker_id"),
        "worker_type": _required_string(worker_type, "worker_type"),
        "workload": _required_string(workload, "workload"),
        "stop_reason": stop_reason,
        "claimed_count": len(projected),
        "succeeded_count": sum(item["state"] == SUCCEEDED for item in projected),
        "cancelled_count": sum(item["state"] == CANCELLED for item in projected),
        "retry_scheduled_count": sum(
            item["state"] == RETRY_SCHEDULED for item in projected
        ),
        "dead_lettered_count": sum(
            item["state"] == DEAD_LETTERED for item in projected
        ),
        "started_at": _wire_timestamp(started_at),
        "completed_at": _wire_timestamp(completed_at),
        "executions": projected,
    }


def _job(job_queue: JobQueue, job_id: str) -> dict[str, Any]:
    try:
        job = job_queue.get_job(job_id)
    except JobQueueError as exc:
        raise _dependency_error("job_read_failed", exc) from exc
    if job is None:
        raise CxWorkerRuntimeError(
            error_code="cx.worker_runtime.job_not_found",
            detail="The worker job was not found.",
            status_code=404,
        )
    return job


def _safe_error_code(exc: Exception) -> str:
    value = getattr(exc, "error_code", None)
    if not isinstance(value, str) or not value.strip():
        return "cx.worker_runtime.handler_failed"
    return value.strip()[:160]


def _dependency_error(suffix: str, exc: JobQueueError) -> CxWorkerRuntimeError:
    return CxWorkerRuntimeError(
        error_code=f"cx.worker_runtime.{suffix}",
        detail=exc.detail,
        status_code=exc.status_code,
        retryable=exc.status_code >= 500,
    )


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CxWorkerRuntimeError(
            error_code="cx.worker_runtime.field_invalid",
            detail=f"{field_name} must be a non-empty string.",
            status_code=422,
        )
    return value.strip()


def _timestamp(value: object, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise CxWorkerRuntimeError(
            error_code="cx.worker_runtime.timestamp_invalid",
            detail=f"{field_name} must be an ISO-8601 timestamp.",
            status_code=422,
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CxWorkerRuntimeError(
            error_code="cx.worker_runtime.timestamp_invalid",
            detail=f"{field_name} must be an ISO-8601 timestamp.",
            status_code=422,
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _wire_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
