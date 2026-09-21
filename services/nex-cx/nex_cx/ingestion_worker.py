from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from nex_runtime import (
    RUNNING as JOB_RUNNING,
    JobQueue,
    JobQueueError,
    JobRetryPolicy,
    RETRY_ACTION_REQUEUE,
    build_job_error,
    plan_job_retry,
    validate_common_job,
)

from nex_cx.ingestion_coordinator import (
    IngestionCheckpointExecutionError,
    IngestionStepHandler,
    execute_all_ingestion_checkpoints,
)
from nex_cx.ingestion_orchestration import (
    QUEUED,
    RUNNING,
    WAITING_RETRY,
    claim_ingestion_run,
    fail_ingestion_step,
    requeue_ingestion_run,
)
from nex_cx.ingestion_orchestration_repository import (
    IngestionRunRepository,
    IngestionRunRepositoryError,
)


CX_INGESTION_JOB_TYPE = "cx.document_ingestion"
CX_INGESTION_WORKER_ID = "cx-ingestion-worker"
CX_INGESTION_WORKER_RESULT_SCHEMA_VERSION = "cx_ingestion_worker_result.v1"
SAFE_INGESTION_FAILURE_DETAIL = "CX ingestion checkpoint execution failed."

WorkerClock = Callable[[], str]


@dataclass(frozen=True)
class IngestionWorkerPolicy:
    lease_ttl_seconds: int = 120
    retry_initial_delay_seconds: int = 30
    retry_max_delay_seconds: int = 900
    retry_backoff_multiplier: float = 2.0

    def __post_init__(self) -> None:
        if not isinstance(self.lease_ttl_seconds, int) or self.lease_ttl_seconds < 1:
            raise IngestionWorkerError(
                error_code="cx.ingestion_worker.lease_ttl_invalid",
                detail="lease_ttl_seconds must be a positive integer.",
                status_code=422,
                retryable=False,
            )
        JobRetryPolicy(
            initial_delay_seconds=self.retry_initial_delay_seconds,
            max_delay_seconds=self.retry_max_delay_seconds,
            backoff_multiplier=self.retry_backoff_multiplier,
        )

    def job_retry_policy(self) -> JobRetryPolicy:
        return JobRetryPolicy(
            initial_delay_seconds=self.retry_initial_delay_seconds,
            max_delay_seconds=self.retry_max_delay_seconds,
            backoff_multiplier=self.retry_backoff_multiplier,
        )


@dataclass(frozen=True)
class IngestionWorkerError(Exception):
    error_code: str
    detail: str
    status_code: int = 500
    retryable: bool = True

    def __str__(self) -> str:
        return self.detail


def run_ingestion_worker_once(
    *,
    job_queue: JobQueue,
    run_repository: IngestionRunRepository,
    step_handlers: Mapping[str, IngestionStepHandler],
    worker_id: str = CX_INGESTION_WORKER_ID,
    policy: IngestionWorkerPolicy | None = None,
    clock: WorkerClock | None = None,
) -> dict[str, Any]:
    observed_at = (clock or _utc_now)()
    try:
        job = job_queue.claim_next_job(
            _required_string(worker_id, "worker_id"),
            job_type=CX_INGESTION_JOB_TYPE,
            updated_at=observed_at,
        )
    except JobQueueError as exc:
        raise _dependency_error("claim_failed", exc) from exc
    if job is None:
        return _worker_result(
            worker_id=worker_id,
            status="IDLE",
            observed_at=observed_at,
        )
    return execute_claimed_ingestion_job(
        job,
        job_queue=job_queue,
        run_repository=run_repository,
        step_handlers=step_handlers,
        worker_id=worker_id,
        policy=policy,
        observed_at=observed_at,
    )


def execute_claimed_ingestion_job(
    job: Mapping[str, Any],
    *,
    job_queue: JobQueue,
    run_repository: IngestionRunRepository,
    step_handlers: Mapping[str, IngestionStepHandler],
    worker_id: str,
    policy: IngestionWorkerPolicy | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    observed = observed_at or _utc_now()
    normalized_job = _claimed_ingestion_job(job)
    resolved_policy = policy or IngestionWorkerPolicy()
    run = _run_for_job(run_repository, str(normalized_job["job_id"]))
    if run is None:
        return _fail_job_without_run(
            normalized_job,
            job_queue=job_queue,
            worker_id=worker_id,
            observed_at=observed,
        )

    try:
        active_run = _claim_run_for_job(
            run,
            run_repository=run_repository,
            worker_id=worker_id,
            policy=resolved_policy,
            observed_at=observed,
        )
        completed_run = execute_all_ingestion_checkpoints(
            active_run,
            run_repository=run_repository,
            worker_id=worker_id,
            step_handlers=step_handlers,
            observed_at=observed,
        )
        completed_job = job_queue.complete_job(
            str(normalized_job["job_id"]),
            updated_at=observed,
        )
    except IngestionCheckpointExecutionError as exc:
        current_run = _run_for_job(
            run_repository,
            str(normalized_job["job_id"]),
        )
        if current_run is None:
            raise IngestionWorkerError(
                error_code="cx.ingestion_worker.run_lost",
                detail="The durable ingestion run disappeared during execution.",
                status_code=503,
            ) from exc
        return _record_worker_failure(
            normalized_job,
            current_run,
            failure=exc,
            job_queue=job_queue,
            run_repository=run_repository,
            worker_id=worker_id,
            policy=resolved_policy,
            observed_at=observed,
            recovered=False,
        )
    except (JobQueueError, IngestionRunRepositoryError) as exc:
        raise _dependency_error("execution_persistence_failed", exc) from exc

    return _worker_result(
        worker_id=worker_id,
        status="SUCCEEDED",
        observed_at=observed,
        job=completed_job,
        run=completed_run,
    )


def recover_expired_ingestion_job(
    job_id: str,
    *,
    job_queue: JobQueue,
    run_repository: IngestionRunRepository,
    policy: IngestionWorkerPolicy | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    observed = observed_at or _utc_now()
    resolved_job_id = _required_string(job_id, "job_id")
    try:
        job = job_queue.get_job(resolved_job_id)
    except JobQueueError as exc:
        raise _dependency_error("recovery_job_read_failed", exc) from exc
    if job is None:
        raise IngestionWorkerError(
            error_code="cx.ingestion_worker.job_not_found",
            detail="The ingestion job was not found.",
            status_code=404,
            retryable=False,
        )
    normalized_job = _claimed_ingestion_job(job)
    run = _run_for_job(run_repository, resolved_job_id)
    if run is None:
        raise IngestionWorkerError(
            error_code="cx.ingestion_worker.run_not_found",
            detail="The durable ingestion run was not found.",
            status_code=404,
            retryable=False,
        )
    if run["status"] != RUNNING or not _timestamp_due(
        str(run["lease_expires_at"]), observed
    ):
        raise IngestionWorkerError(
            error_code="cx.ingestion_worker.lease_not_expired",
            detail="Only an ingestion run with an expired active lease can recover.",
            status_code=409,
            retryable=False,
        )
    lease_owner = _required_string(run.get("lease_owner"), "lease_owner")
    failure = IngestionCheckpointExecutionError(
        error_code="cx.ingestion_worker.lease_expired",
        detail="The ingestion worker lease expired before completion.",
        retryable=True,
        failed_step=str(run["current_step"]),
        status_code=503,
    )
    return _record_worker_failure(
        normalized_job,
        run,
        failure=failure,
        job_queue=job_queue,
        run_repository=run_repository,
        worker_id=lease_owner,
        policy=policy or IngestionWorkerPolicy(),
        observed_at=observed,
        recovered=True,
    )


def _claim_run_for_job(
    run: Mapping[str, Any],
    *,
    run_repository: IngestionRunRepository,
    worker_id: str,
    policy: IngestionWorkerPolicy,
    observed_at: str,
) -> dict[str, Any]:
    current = dict(run)
    if current["status"] == WAITING_RETRY:
        retry_at = str(current["retry_at"])
        if not _timestamp_due(retry_at, observed_at):
            raise IngestionWorkerError(
                error_code="cx.ingestion_worker.retry_not_ready",
                detail="The durable ingestion retry is not ready.",
                status_code=409,
                retryable=False,
            )
        requeued = requeue_ingestion_run(
            current,
            observed_at=observed_at,
            expected_checkpoint_version=int(current["checkpoint_version"]),
        )
        current = run_repository.save(
            requeued,
            expected_checkpoint_version=int(current["checkpoint_version"]),
        )
    if current["status"] != QUEUED:
        raise IngestionWorkerError(
            error_code="cx.ingestion_worker.run_not_claimable",
            detail="The durable ingestion run is not claimable.",
            status_code=409,
            retryable=False,
        )
    claimed = claim_ingestion_run(
        current,
        worker_id=worker_id,
        lease_expires_at=_add_seconds(observed_at, policy.lease_ttl_seconds),
        observed_at=observed_at,
        expected_checkpoint_version=int(current["checkpoint_version"]),
    )
    return run_repository.save(
        claimed,
        expected_checkpoint_version=int(current["checkpoint_version"]),
    )


def _record_worker_failure(
    job: dict[str, Any],
    run: Mapping[str, Any],
    *,
    failure: IngestionCheckpointExecutionError,
    job_queue: JobQueue,
    run_repository: IngestionRunRepository,
    worker_id: str,
    policy: IngestionWorkerPolicy,
    observed_at: str,
    recovered: bool,
) -> dict[str, Any]:
    try:
        retry_decision = None
        if failure.retryable:
            retry_decision = plan_job_retry(
                job,
                error=build_job_error(
                    error_code=failure.error_code,
                    detail=SAFE_INGESTION_FAILURE_DETAIL,
                    retryable=True,
                ),
                failed_at=observed_at,
                policy=policy.job_retry_policy(),
            )
        can_retry = bool(
            retry_decision is not None
            and retry_decision.action == RETRY_ACTION_REQUEUE
        )
        failed_run = fail_ingestion_step(
            run,
            worker_id=worker_id,
            error_code=failure.error_code,
            retryable=can_retry,
            retry_at=retry_decision.available_at if can_retry else None,
            observed_at=observed_at,
            expected_checkpoint_version=int(run["checkpoint_version"]),
        )
        saved_run = run_repository.save(
            failed_run,
            expected_checkpoint_version=int(run["checkpoint_version"]),
        )
        if can_retry:
            saved_job = job_queue.retry_job(
                str(job["job_id"]),
                error=build_job_error(
                    error_code=failure.error_code,
                    detail=SAFE_INGESTION_FAILURE_DETAIL,
                    retryable=True,
                ),
                failed_at=observed_at,
                policy=policy.job_retry_policy(),
            )
            status = "RETRY_SCHEDULED"
        else:
            saved_job = job_queue.fail_job(
                str(job["job_id"]),
                updated_at=observed_at,
            )
            status = "FAILED"
    except (JobQueueError, IngestionRunRepositoryError) as exc:
        raise _dependency_error("failure_persistence_failed", exc) from exc
    return _worker_result(
        worker_id=worker_id,
        status=status,
        observed_at=observed_at,
        job=saved_job,
        run=saved_run,
        error_code=failure.error_code,
        failed_step=failure.failed_step,
        recovered=recovered,
    )


def _fail_job_without_run(
    job: dict[str, Any],
    *,
    job_queue: JobQueue,
    worker_id: str,
    observed_at: str,
) -> dict[str, Any]:
    try:
        failed_job = job_queue.fail_job(str(job["job_id"]), updated_at=observed_at)
    except JobQueueError as exc:
        raise _dependency_error("missing_run_job_failure_failed", exc) from exc
    return _worker_result(
        worker_id=worker_id,
        status="FAILED",
        observed_at=observed_at,
        job=failed_job,
        error_code="cx.ingestion_worker.run_not_found",
    )


def _run_for_job(
    repository: IngestionRunRepository,
    job_id: str,
) -> dict[str, Any] | None:
    try:
        return repository.find_by_job_id(job_id)
    except IngestionRunRepositoryError as exc:
        raise _dependency_error("run_read_failed", exc) from exc


def _claimed_ingestion_job(job: Mapping[str, Any]) -> dict[str, Any]:
    try:
        normalized = validate_common_job(dict(job))
    except JobQueueError as exc:
        raise IngestionWorkerError(
            error_code="cx.ingestion_worker.job_invalid",
            detail=exc.detail,
            status_code=422,
            retryable=False,
        ) from exc
    if normalized["job_type"] != CX_INGESTION_JOB_TYPE:
        raise IngestionWorkerError(
            error_code="cx.ingestion_worker.job_type_invalid",
            detail="The claimed job is not a CX document ingestion job.",
            status_code=422,
            retryable=False,
        )
    if normalized["status"] != JOB_RUNNING:
        raise IngestionWorkerError(
            error_code="cx.ingestion_worker.job_not_running",
            detail="The ingestion job must be claimed before execution.",
            status_code=409,
            retryable=False,
        )
    return normalized


def _worker_result(
    *,
    worker_id: str,
    status: str,
    observed_at: str,
    job: Mapping[str, Any] | None = None,
    run: Mapping[str, Any] | None = None,
    error_code: str | None = None,
    failed_step: str | None = None,
    recovered: bool = False,
) -> dict[str, Any]:
    return {
        "worker_result_schema_version": CX_INGESTION_WORKER_RESULT_SCHEMA_VERSION,
        "worker_id": worker_id,
        "status": status,
        "job_id": str(job["job_id"]) if job is not None else None,
        "job_status": str(job["status"]) if job is not None else None,
        "run_id": str(run["run_id"]) if run is not None else None,
        "run_status": str(run["status"]) if run is not None else None,
        "checkpoint_version": int(run["checkpoint_version"]) if run else None,
        "retry_at": run.get("retry_at") if run is not None else None,
        "error_code": error_code,
        "failed_step": failed_step,
        "recovered": bool(recovered),
        "observed_at": observed_at,
    }


def _dependency_error(suffix: str, exc: Exception) -> IngestionWorkerError:
    return IngestionWorkerError(
        error_code=f"cx.ingestion_worker.{suffix}",
        detail=str(getattr(exc, "detail", "Ingestion worker dependency failed.")),
        status_code=int(getattr(exc, "status_code", 503)),
        retryable=True,
    )


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IngestionWorkerError(
            error_code="cx.ingestion_worker.field_invalid",
            detail=f"{field_name} must be a non-empty string.",
            status_code=422,
            retryable=False,
        )
    return value.strip()


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise IngestionWorkerError(
            error_code="cx.ingestion_worker.timestamp_invalid",
            detail="Ingestion worker timestamps must be ISO-8601 values.",
            status_code=422,
            retryable=False,
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _timestamp_due(value: str, observed_at: str) -> bool:
    return _timestamp(value) <= _timestamp(observed_at)


def _add_seconds(value: str, seconds: int) -> str:
    return (_timestamp(value) + timedelta(seconds=seconds)).isoformat().replace(
        "+00:00", "Z"
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
