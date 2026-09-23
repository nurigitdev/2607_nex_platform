from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse

from nex_runtime import (
    CX_WORKER_CANCELLATION_REQUESTED_EVENT,
    CX_WORKER_RECONCILIATION_APPLIED_EVENT,
    FAILED,
    JobQueue,
    JobQueueError,
    OperationalEventEmitter,
    WorkerHeartbeatError,
    WorkerHeartbeatStore,
    build_subject_ref,
    operational_event_emitter_from_app,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
)
from nex_cx.authorization import authorize_cx_request
from nex_cx.worker_leases import SqlAlchemyCxWorkerLeaseStore
from nex_cx.worker_lifecycle import project_worker_readiness
from nex_cx.worker_reconciliation import (
    RecoveryHandler,
    CxWorkerReconciliationError,
    apply_worker_reconciliation_plan,
    build_worker_reconciliation_plan,
)
from nex_cx.worker_resilience import project_dead_letter_job
from nex_cx.worker_runtime import CxWorkerRuntimeError, request_worker_cancellation


CX_WORKER_OPERATIONS_SCHEMA_VERSION = "cx_worker_operations.v1"
DEFAULT_DEAD_LETTER_LIMIT = 50
MAX_DEAD_LETTER_LIMIT = 500


@dataclass(frozen=True)
class CxWorkerOperationsError(Exception):
    error_code: str
    detail: str
    status_code: int = 500
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


def register_worker_operations_routes(
    app: FastAPI,
    *,
    job_queue: JobQueue,
    heartbeat_store: WorkerHeartbeatStore,
    lease_store: SqlAlchemyCxWorkerLeaseStore | None,
    recovery_handlers: Mapping[str, RecoveryHandler] | None = None,
    event_emitter: OperationalEventEmitter | None = None,
) -> None:
    emitter = event_emitter or operational_event_emitter_from_app(
        app,
        service_id="nex-cx",
    )

    @app.get("/internal/v1/workers/{worker_id}/readiness", response_model=None)
    def get_worker_readiness(
        worker_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
        stale_after_seconds: int = Query(default=60, ge=1, le=86_400),
    ):
        auth_failure = authorize_cx_request(request, authorization)
        if auth_failure is not None:
            return auth_failure
        try:
            heartbeat = heartbeat_store.get_heartbeat("nex-cx", worker_id)
            return project_worker_readiness(
                heartbeat,
                stale_after_seconds=stale_after_seconds,
            )
        except WorkerHeartbeatError as exc:
            return _worker_problem_response(
                request,
                CxWorkerOperationsError(
                    error_code=exc.error_code,
                    detail=exc.detail,
                    status_code=exc.status_code,
                    retryable=exc.status_code >= 500,
                ),
            )

    @app.get("/internal/v1/workers/reconciliation-plan", response_model=None)
    def get_worker_reconciliation_plan(
        request: Request,
        authorization: str | None = Header(default=None),
        observed_at: str | None = Query(default=None),
        heartbeat_stale_after_seconds: int = Query(
            default=60,
            ge=1,
            le=86_400,
        ),
    ):
        auth_failure = authorize_cx_request(request, authorization)
        if auth_failure is not None:
            return auth_failure
        try:
            return _build_reconciliation_plan(
                job_queue=job_queue,
                lease_store=lease_store,
                heartbeat_store=heartbeat_store,
                observed_at=observed_at,
                heartbeat_stale_after_seconds=heartbeat_stale_after_seconds,
            )
        except CxWorkerOperationsError as exc:
            return _worker_problem_response(request, exc)

    @app.post("/internal/v1/workers/reconcile", response_model=None)
    def reconcile_workers(
        request: Request,
        authorization: str | None = Header(default=None),
        observed_at: str | None = Query(default=None),
        heartbeat_stale_after_seconds: int = Query(
            default=60,
            ge=1,
            le=86_400,
        ),
    ):
        auth_failure = authorize_cx_request(request, authorization)
        if auth_failure is not None:
            return auth_failure
        try:
            plan = _build_reconciliation_plan(
                job_queue=job_queue,
                lease_store=lease_store,
                heartbeat_store=heartbeat_store,
                observed_at=observed_at,
                heartbeat_stale_after_seconds=heartbeat_stale_after_seconds,
            )
            result = apply_worker_reconciliation_plan(
                plan,
                job_queue=job_queue,
                recovery_handlers=recovery_handlers,
            )
        except CxWorkerOperationsError as exc:
            return _worker_problem_response(request, exc)
        except CxWorkerReconciliationError as exc:
            return _worker_problem_response(request, _reconciliation_error(exc))
        event_result = emitter.safe_emit(
            event_type=CX_WORKER_RECONCILIATION_APPLIED_EVENT,
            severity="WARNING" if result["applied_count"] else "INFO",
            message="CX worker reconciliation plan was applied.",
            trace_id=trace_id_from_headers(request),
            request_id=request_id_from_headers(request),
            subject_ref=build_subject_ref("worker.fleet", "nex-cx"),
            details={
                "running_job_count": plan["running_job_count"],
                "recoverable_count": plan["recoverable_count"],
                "manual_review_count": plan["manual_review_count"],
                "applied_count": result["applied_count"],
            },
            event_id=_operation_event_id(
                "reconciliation",
                str(plan["observed_at"]),
            ),
        )
        return {
            "worker_operations_schema_version": (
                CX_WORKER_OPERATIONS_SCHEMA_VERSION
            ),
            "action": "RECONCILE",
            "plan": plan,
            "result": result,
            "observability": event_result.to_summary(),
        }

    @app.post(
        "/internal/v1/workers/jobs/{job_id}/cancel",
        response_model=None,
    )
    def cancel_worker_job(
        job_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_failure = authorize_cx_request(request, authorization)
        if auth_failure is not None:
            return auth_failure
        try:
            result = request_worker_cancellation(job_queue, job_id)
        except CxWorkerRuntimeError as exc:
            return _worker_problem_response(
                request,
                CxWorkerOperationsError(
                    error_code=exc.error_code,
                    detail=exc.detail,
                    status_code=exc.status_code,
                    retryable=exc.retryable,
                ),
            )
        event_result = emitter.safe_emit(
            event_type=CX_WORKER_CANCELLATION_REQUESTED_EVENT,
            severity="INFO",
            message="CX worker job cancellation was requested.",
            trace_id=trace_id_from_headers(request),
            request_id=request_id_from_headers(request),
            subject_ref=build_subject_ref("job", job_id),
            details={
                "job_type": result["job_type"],
                "job_status": result["status"],
                "already_cancelled": result["already_cancelled"],
            },
            event_id=_operation_event_id(
                "cancellation",
                job_id,
                str(result["cancellation_requested_at"]),
            ),
        )
        return {
            "worker_operations_schema_version": (
                CX_WORKER_OPERATIONS_SCHEMA_VERSION
            ),
            "action": "CANCEL",
            "result": result,
            "observability": event_result.to_summary(),
        }

    @app.get("/internal/v1/workers/dead-letters", response_model=None)
    def list_worker_dead_letters(
        request: Request,
        authorization: str | None = Header(default=None),
        limit: int = Query(
            default=DEFAULT_DEAD_LETTER_LIMIT,
            ge=1,
            le=MAX_DEAD_LETTER_LIMIT,
        ),
    ):
        auth_failure = authorize_cx_request(request, authorization)
        if auth_failure is not None:
            return auth_failure
        try:
            failed_jobs = job_queue.list_jobs(status=FAILED)
        except JobQueueError as exc:
            return _worker_problem_response(
                request,
                CxWorkerOperationsError(
                    error_code="cx.worker_operations.dead_letter_read_failed",
                    detail=exc.detail,
                    status_code=exc.status_code,
                    retryable=exc.status_code >= 500,
                ),
            )
        dead_letters = [
            project_dead_letter_job(job)
            for job in failed_jobs
            if isinstance(job.get("error"), Mapping)
            and job["error"].get("dead_lettered") is True
        ][:limit]
        return {
            "worker_operations_schema_version": (
                CX_WORKER_OPERATIONS_SCHEMA_VERSION
            ),
            "limit": limit,
            "dead_letter_count": len(dead_letters),
            "dead_letters": dead_letters,
        }


def _build_reconciliation_plan(
    *,
    job_queue: JobQueue,
    lease_store: SqlAlchemyCxWorkerLeaseStore | None,
    heartbeat_store: WorkerHeartbeatStore,
    observed_at: str | None,
    heartbeat_stale_after_seconds: int,
) -> dict[str, Any]:
    if lease_store is None:
        raise CxWorkerOperationsError(
            error_code="cx.worker_operations.postgres_required",
            detail="Durable worker reconciliation requires PostgreSQL persistence.",
            status_code=503,
            retryable=True,
        )
    try:
        return build_worker_reconciliation_plan(
            job_queue=job_queue,
            lease_store=lease_store,
            heartbeat_store=heartbeat_store,
            observed_at=observed_at or _utc_now(),
            heartbeat_stale_after_seconds=heartbeat_stale_after_seconds,
        )
    except CxWorkerReconciliationError as exc:
        raise _reconciliation_error(exc) from exc


def _reconciliation_error(
    exc: CxWorkerReconciliationError,
) -> CxWorkerOperationsError:
    return CxWorkerOperationsError(
        error_code=exc.error_code,
        detail=exc.detail,
        status_code=exc.status_code,
        retryable=exc.retryable,
    )


def _operation_event_id(*parts: str) -> str:
    return str(uuid5(NAMESPACE_URL, "cx-worker-operation:" + ":".join(parts)))


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _worker_problem_response(
    request: Request,
    exc: CxWorkerOperationsError,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="CX worker operation failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/cx-worker-operation-failed",
    )
