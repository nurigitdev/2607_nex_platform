from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from nex_runtime import (
    ACTIVE_WORKER_HEARTBEAT_STATUSES,
    RUNNING,
    JobQueue,
    JobQueueError,
    WorkerHeartbeatError,
    WorkerHeartbeatStore,
    worker_heartbeat_is_stale,
)
from nex_cx.worker_leases import (
    CxWorkerLeaseError,
    CxWorkerLeasePolicy,
    SqlAlchemyCxWorkerLeaseStore,
)
from nex_cx.worker_resilience import (
    CxWorkerResilienceError,
    settle_worker_failure,
)


CX_WORKER_RECONCILIATION_PLAN_SCHEMA_VERSION = "cx_worker_reconciliation_plan.v1"
RECOVER = "RECOVER"
WAIT_LEASE = "WAIT_LEASE"
WAIT_HEARTBEAT = "WAIT_HEARTBEAT"
HEALTHY = "HEALTHY"
MANUAL_REVIEW = "MANUAL_REVIEW"
RECONCILIATION_ACTIONS = (
    RECOVER,
    WAIT_LEASE,
    WAIT_HEARTBEAT,
    HEALTHY,
    MANUAL_REVIEW,
)
SPECIALIZED_RECOVERY_JOB_TYPES = frozenset(
    {"cx.document_ingestion", "cx.grounded-generation.execute"}
)

RecoveryHandler = Callable[[dict[str, Any], str], Mapping[str, Any]]


@dataclass(frozen=True)
class CxWorkerReconciliationError(Exception):
    error_code: str
    detail: str
    status_code: int = 500
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class ExpiredWorkerLeaseFailure(Exception):
    error_code: str = "cx.worker_reconciliation.lease_expired"
    detail: str = "The worker lease expired after heartbeat loss."
    status_code: int = 503
    retryable: bool = True
    failure_class: str = "dependency"


def build_worker_reconciliation_plan(
    *,
    job_queue: JobQueue,
    lease_store: SqlAlchemyCxWorkerLeaseStore,
    heartbeat_store: WorkerHeartbeatStore,
    observed_at: str,
    lease_policy: CxWorkerLeasePolicy | None = None,
    heartbeat_stale_after_seconds: int = 60,
) -> dict[str, Any]:
    try:
        jobs = job_queue.list_jobs(status=RUNNING)
    except JobQueueError as exc:
        raise _dependency_error("job_list_failed", exc) from exc
    entries = [
        _plan_job(
            job,
            lease_store=lease_store,
            heartbeat_store=heartbeat_store,
            observed_at=observed_at,
            lease_policy=lease_policy,
            heartbeat_stale_after_seconds=heartbeat_stale_after_seconds,
        )
        for job in jobs
    ]
    return {
        "reconciliation_schema_version": (
            CX_WORKER_RECONCILIATION_PLAN_SCHEMA_VERSION
        ),
        "observed_at": observed_at,
        "running_job_count": len(entries),
        "recoverable_count": sum(item["action"] == RECOVER for item in entries),
        "manual_review_count": sum(
            item["action"] == MANUAL_REVIEW for item in entries
        ),
        "entries": entries,
    }


def apply_worker_reconciliation_plan(
    plan: Mapping[str, Any],
    *,
    job_queue: JobQueue,
    recovery_handlers: Mapping[str, RecoveryHandler] | None = None,
) -> dict[str, Any]:
    if plan.get("reconciliation_schema_version") != (
        CX_WORKER_RECONCILIATION_PLAN_SCHEMA_VERSION
    ):
        raise CxWorkerReconciliationError(
            error_code="cx.worker_reconciliation.plan_invalid",
            detail="The worker reconciliation plan is invalid.",
            status_code=422,
        )
    observed_at = _required_string(plan.get("observed_at"), "observed_at")
    entries = plan.get("entries")
    if not isinstance(entries, list):
        raise CxWorkerReconciliationError(
            error_code="cx.worker_reconciliation.plan_invalid",
            detail="The worker reconciliation entries must be a list.",
            status_code=422,
        )
    handlers = recovery_handlers or {}
    results = []
    for entry in entries:
        if not isinstance(entry, Mapping) or entry.get("action") != RECOVER:
            continue
        job_id = _required_string(entry.get("job_id"), "job_id")
        job_type = _required_string(entry.get("job_type"), "job_type")
        try:
            job = job_queue.get_job(job_id)
        except JobQueueError as exc:
            raise _dependency_error("job_read_failed", exc) from exc
        if job is None or job.get("status") != RUNNING:
            results.append(
                {
                    "job_id": job_id,
                    "job_type": job_type,
                    "result": "ALREADY_SETTLED",
                }
            )
            continue
        handler = handlers.get(job_type)
        if handler is not None:
            try:
                handled = dict(handler(job, observed_at))
            except Exception as exc:
                raise CxWorkerReconciliationError(
                    error_code="cx.worker_reconciliation.handler_failed",
                    detail=str(
                        getattr(exc, "detail", "Worker recovery handler failed.")
                    ),
                    status_code=int(getattr(exc, "status_code", 500)),
                    retryable=bool(getattr(exc, "retryable", True)),
                ) from exc
            results.append(
                {
                    "job_id": job_id,
                    "job_type": job_type,
                    "result": "HANDLED",
                    "action": handled.get("status"),
                }
            )
            continue
        if job_type in SPECIALIZED_RECOVERY_JOB_TYPES:
            results.append(
                {
                    "job_id": job_id,
                    "job_type": job_type,
                    "result": "HANDLER_REQUIRED",
                }
            )
            continue
        try:
            settlement = settle_worker_failure(
                job_queue=job_queue,
                job=job,
                failure=ExpiredWorkerLeaseFailure(),
                failed_at=observed_at,
            )
        except CxWorkerResilienceError as exc:
            raise CxWorkerReconciliationError(
                error_code="cx.worker_reconciliation.settlement_failed",
                detail=exc.detail,
                status_code=exc.status_code,
                retryable=exc.retryable,
            ) from exc
        results.append(
            {
                "job_id": job_id,
                "job_type": job_type,
                "result": str(settlement["action"]),
            }
        )
    return {
        "reconciliation_schema_version": (
            CX_WORKER_RECONCILIATION_PLAN_SCHEMA_VERSION
        ),
        "observed_at": observed_at,
        "applied_count": len(results),
        "results": results,
    }


def _plan_job(
    job: Mapping[str, Any],
    *,
    lease_store: SqlAlchemyCxWorkerLeaseStore,
    heartbeat_store: WorkerHeartbeatStore,
    observed_at: str,
    lease_policy: CxWorkerLeasePolicy | None,
    heartbeat_stale_after_seconds: int,
) -> dict[str, Any]:
    job_id = _required_string(job.get("job_id"), "job_id")
    try:
        lease = lease_store.inspect(
            job_id,
            policy=lease_policy,
            observed_at=observed_at,
        )
    except CxWorkerLeaseError as exc:
        raise CxWorkerReconciliationError(
            error_code="cx.worker_reconciliation.lease_read_failed",
            detail=exc.detail,
            status_code=exc.status_code,
            retryable=exc.retryable,
        ) from exc
    if lease is None or lease.get("worker_id") is None or lease.get("locked_at") is None:
        return _entry(
            job,
            action=MANUAL_REVIEW,
            reason_code="durable_lease_missing",
            lease=lease,
            heartbeat=None,
        )
    worker_id = str(lease["worker_id"])
    try:
        heartbeat = heartbeat_store.get_heartbeat("nex-cx", worker_id)
    except WorkerHeartbeatError as exc:
        raise CxWorkerReconciliationError(
            error_code="cx.worker_reconciliation.heartbeat_read_failed",
            detail=exc.detail,
            status_code=exc.status_code,
            retryable=exc.status_code >= 500,
        ) from exc
    heartbeat_available = bool(
        heartbeat is not None
        and heartbeat["status"] in ACTIVE_WORKER_HEARTBEAT_STATUSES
        and not worker_heartbeat_is_stale(
            heartbeat,
            stale_after_seconds=heartbeat_stale_after_seconds,
            checked_at=observed_at,
        )
    )
    lease_expired = bool(lease["expired"])
    if lease_expired and not heartbeat_available:
        action, reason_code = RECOVER, "lease_expired_heartbeat_unavailable"
    elif lease_expired:
        action, reason_code = WAIT_HEARTBEAT, "lease_expired_heartbeat_fresh"
    elif not heartbeat_available:
        action, reason_code = WAIT_LEASE, "heartbeat_unavailable_lease_active"
    else:
        action, reason_code = HEALTHY, "lease_and_heartbeat_active"
    return _entry(
        job,
        action=action,
        reason_code=reason_code,
        lease=lease,
        heartbeat=heartbeat,
    )


def _entry(
    job: Mapping[str, Any],
    *,
    action: str,
    reason_code: str,
    lease: Mapping[str, Any] | None,
    heartbeat: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "job_id": _required_string(job.get("job_id"), "job_id"),
        "job_type": _required_string(job.get("job_type"), "job_type"),
        "worker_id": lease.get("worker_id") if lease is not None else None,
        "action": action,
        "reason_code": reason_code,
        "lease_expires_at": lease.get("expires_at") if lease is not None else None,
        "lease_expired": lease.get("expired") if lease is not None else None,
        "heartbeat_status": (
            heartbeat.get("status") if heartbeat is not None else None
        ),
        "heartbeat_last_seen_at": (
            heartbeat.get("last_seen_at") if heartbeat is not None else None
        ),
    }


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CxWorkerReconciliationError(
            error_code="cx.worker_reconciliation.field_invalid",
            detail=f"{field_name} must be a non-empty string.",
            status_code=422,
        )
    return value.strip()


def _dependency_error(
    suffix: str,
    exc: JobQueueError,
) -> CxWorkerReconciliationError:
    return CxWorkerReconciliationError(
        error_code=f"cx.worker_reconciliation.{suffix}",
        detail=exc.detail,
        status_code=exc.status_code,
        retryable=exc.status_code >= 500,
    )
