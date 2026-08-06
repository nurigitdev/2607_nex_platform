from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable, Protocol

from .jobs import FAILED, JobQueue, JobQueueError, SUCCEEDED, build_job_error
from .worker_heartbeats import (
    BUSY,
    ERROR,
    IDLE,
    STARTING,
    WorkerHeartbeatEmitter,
    WorkerHeartbeatEmitResult,
)

WorkerClock = Callable[[], str]


class WorkerJobHandler(Protocol):
    def __call__(self, job: dict[str, Any]) -> dict[str, Any] | None:
        ...


@dataclass(frozen=True)
class WorkerRunnerConfig:
    service_id: str
    worker_id: str
    worker_type: str
    job_type: str
    max_jobs: int = 1

    def __post_init__(self) -> None:
        _required_string(self.service_id, "service_id")
        _required_string(self.worker_id, "worker_id")
        _required_string(self.worker_type, "worker_type")
        _required_string(self.job_type, "job_type")
        if not isinstance(self.max_jobs, int) or self.max_jobs < 1:
            raise WorkerRunnerError(
                error_code="worker_runner.max_jobs_invalid",
                detail="max_jobs must be a positive integer",
            )


@dataclass(frozen=True)
class WorkerJobExecution:
    status: str
    job: dict[str, Any] | None = None
    completed_job: dict[str, Any] | None = None
    handler_result: dict[str, Any] | None = None
    error_code: str | None = None
    error_detail: str | None = None
    heartbeat_results: tuple[dict[str, Any], ...] = ()

    def to_summary(self) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "status": self.status,
            "heartbeat_results": list(self.heartbeat_results),
        }
        if self.job is not None:
            summary["job_id"] = self.job["job_id"]
            summary["job_type"] = self.job["job_type"]
            summary["attempt_count"] = self.job["attempt_count"]
        if self.completed_job is not None:
            summary["completed_status"] = self.completed_job["status"]
        if self.handler_result is not None:
            summary["handler_result"] = deepcopy(self.handler_result)
        if self.error_code is not None:
            summary["error_code"] = self.error_code
            summary["error_detail"] = self.error_detail
        return summary


@dataclass(frozen=True)
class WorkerBatchResult:
    service_id: str
    worker_id: str
    worker_type: str
    job_type: str
    executions: tuple[WorkerJobExecution, ...] = field(default_factory=tuple)

    @property
    def claimed_count(self) -> int:
        return sum(1 for execution in self.executions if execution.job is not None)

    @property
    def succeeded_count(self) -> int:
        return sum(1 for execution in self.executions if execution.status == SUCCEEDED)

    @property
    def failed_count(self) -> int:
        return sum(1 for execution in self.executions if execution.status == FAILED)

    @property
    def idle_count(self) -> int:
        return sum(1 for execution in self.executions if execution.status == IDLE)

    def to_summary(self) -> dict[str, Any]:
        return {
            "service_id": self.service_id,
            "worker_id": self.worker_id,
            "worker_type": self.worker_type,
            "job_type": self.job_type,
            "claimed": self.claimed_count,
            "succeeded": self.succeeded_count,
            "failed": self.failed_count,
            "idle": self.idle_count,
            "executions": [execution.to_summary() for execution in self.executions],
        }


@dataclass(frozen=True)
class WorkerRunnerError(Exception):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


def run_worker_once(
    *,
    config: WorkerRunnerConfig,
    queue: JobQueue,
    heartbeat_emitter: WorkerHeartbeatEmitter,
    handler: WorkerJobHandler,
    handler_finalizes_job: bool = False,
    clock: WorkerClock | None = None,
) -> WorkerJobExecution:
    observed_clock = clock or _utc_now
    heartbeat_results = [
        _heartbeat_summary(
            heartbeat_emitter.safe_emit(
                status=STARTING,
                metadata={"job_type": config.job_type},
                observed_at=observed_clock(),
            )
        )
    ]
    try:
        job = queue.claim_next_job(
            config.worker_id,
            job_type=config.job_type,
            updated_at=observed_clock(),
        )
    except JobQueueError as exc:
        heartbeat_results.append(
            _heartbeat_summary(
                heartbeat_emitter.safe_emit(
                    status=ERROR,
                    metadata={
                        "job_type": config.job_type,
                        "error_code": exc.error_code,
                    },
                    observed_at=observed_clock(),
                )
            )
        )
        return WorkerJobExecution(
            status=FAILED,
            error_code=exc.error_code,
            error_detail=exc.detail,
            heartbeat_results=tuple(heartbeat_results),
        )

    if job is None:
        heartbeat_results.append(
            _heartbeat_summary(
                heartbeat_emitter.safe_emit(
                    status=IDLE,
                    metadata={"job_type": config.job_type, "claimed": False},
                    observed_at=observed_clock(),
                )
            )
        )
        return WorkerJobExecution(
            status=IDLE,
            heartbeat_results=tuple(heartbeat_results),
        )

    heartbeat_results.append(
        _heartbeat_summary(
            heartbeat_emitter.safe_emit(
                status=BUSY,
                active_job_id=str(job["job_id"]),
                trace_id=str(job["trace_id"]),
                metadata=_job_metadata(job),
                observed_at=observed_clock(),
            )
        )
    )

    try:
        handler_result = handler(deepcopy(job)) or {}
    except Exception as exc:
        error_code = str(getattr(exc, "error_code", "worker_runner.handler_failed"))
        error_detail = str(getattr(exc, "detail", exc.__class__.__name__))
        failed_job = _safe_retry_job(
            queue,
            str(job["job_id"]),
            error=build_job_error(
                error_code=error_code,
                detail=error_detail,
                retryable=True,
            ),
            failed_at=observed_clock(),
        )
        heartbeat_results.append(
            _heartbeat_summary(
                heartbeat_emitter.safe_emit(
                    status=ERROR,
                    active_job_id=str(job["job_id"]),
                    trace_id=str(job["trace_id"]),
                    metadata={
                        **_job_metadata(failed_job or job),
                        "error_code": error_code,
                    },
                    observed_at=observed_clock(),
                )
            )
        )
        return WorkerJobExecution(
            status=FAILED,
            job=job,
            completed_job=failed_job,
            error_code=error_code,
            error_detail=error_detail,
            heartbeat_results=tuple(heartbeat_results),
        )

    completed_job = (
        queue.get_job(str(job["job_id"]))
        if handler_finalizes_job
        else queue.complete_job(str(job["job_id"]), updated_at=observed_clock())
    )
    completed_job = completed_job or job
    heartbeat_results.append(
        _heartbeat_summary(
            heartbeat_emitter.safe_emit(
                status=IDLE,
                trace_id=str(completed_job["trace_id"]),
                metadata=_job_metadata(completed_job),
                observed_at=observed_clock(),
            )
        )
    )
    return WorkerJobExecution(
        status=str(completed_job["status"]),
        job=job,
        completed_job=completed_job,
        handler_result=handler_result,
        heartbeat_results=tuple(heartbeat_results),
    )


def run_worker_batch(
    *,
    config: WorkerRunnerConfig,
    queue: JobQueue,
    heartbeat_emitter: WorkerHeartbeatEmitter,
    handler: WorkerJobHandler,
    handler_finalizes_job: bool = False,
    stop_on_failure: bool = True,
    clock: WorkerClock | None = None,
) -> WorkerBatchResult:
    executions: list[WorkerJobExecution] = []
    for _ in range(config.max_jobs):
        execution = run_worker_once(
            config=config,
            queue=queue,
            heartbeat_emitter=heartbeat_emitter,
            handler=handler,
            handler_finalizes_job=handler_finalizes_job,
            clock=clock,
        )
        executions.append(execution)
        if execution.status == IDLE:
            break
        if execution.status == FAILED and stop_on_failure:
            break
    return WorkerBatchResult(
        service_id=config.service_id,
        worker_id=config.worker_id,
        worker_type=config.worker_type,
        job_type=config.job_type,
        executions=tuple(executions),
    )


def _safe_retry_job(
    queue: JobQueue,
    job_id: str,
    *,
    error: dict[str, Any],
    failed_at: str,
) -> dict[str, Any] | None:
    try:
        return queue.retry_job(job_id, error=error, failed_at=failed_at)
    except JobQueueError:
        return queue.get_job(job_id)


def _job_metadata(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": str(job["job_id"]),
        "job_type": str(job["job_type"]),
        "job_status": str(job["status"]),
        "attempt_count": int(job["attempt_count"]),
    }


def _heartbeat_summary(result: WorkerHeartbeatEmitResult) -> dict[str, Any]:
    return result.to_summary()


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise WorkerRunnerError(
            error_code="worker_runner.field_invalid",
            detail=f"{field_name} must be a non-empty string",
        )
    return value


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
