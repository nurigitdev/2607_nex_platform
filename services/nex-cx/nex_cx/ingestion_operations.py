from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse

from nex_runtime import (
    CX_INGESTION_LEASE_RECOVERED_EVENT,
    JobQueue,
    OperationalEventEmitter,
    build_subject_ref,
    operational_event_emitter_from_app,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
)
from nex_cx.authorization import (
    CX_SUBJECT_HEADER,
    CX_TENANT_HEADER,
    authorize_cx_owner_request,
    authorize_cx_request,
)
from nex_cx.ingestion_orchestration_repository import IngestionRunRepository
from nex_cx.ingestion_read_model import (
    IngestionReadModelError,
    build_ingestion_restart_plan,
    get_ingestion_run_read_model,
    list_document_ingestion_run_read_models,
)
from nex_cx.ingestion_worker import (
    IngestionWorkerError,
    recover_expired_ingestion_job,
)


CX_INGESTION_RECOVERY_SCHEMA_VERSION = "cx_ingestion_recovery.v1"


@dataclass(frozen=True)
class IngestionOperationsError(Exception):
    error_code: str
    detail: str
    status_code: int = 500
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


def register_ingestion_operations_routes(
    app: FastAPI,
    *,
    job_queue: JobQueue,
    run_repository: IngestionRunRepository,
    event_emitter: OperationalEventEmitter | None = None,
) -> None:
    emitter = event_emitter or operational_event_emitter_from_app(
        app,
        service_id="nex-cx",
    )

    @app.get("/api/v1/ingestion-runs/{run_id}", response_model=None)
    def get_ingestion_run(
        run_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
        cx_tenant_id: str | None = Header(default=None, alias=CX_TENANT_HEADER),
        cx_subject_id: str | None = Header(default=None, alias=CX_SUBJECT_HEADER),
    ):
        access_context = authorize_cx_owner_request(
            request,
            authorization,
            tenant_id=cx_tenant_id,
            subject_id=cx_subject_id,
        )
        if isinstance(access_context, JSONResponse):
            return access_context
        try:
            result = get_ingestion_run_read_model(
                run_id,
                tenant_id=access_context.tenant_id,
                owner_subject_id=access_context.subject_id,
                run_repository=run_repository,
            )
        except IngestionReadModelError as exc:
            return _operations_problem_response(request, _read_model_error(exc))
        if result is None:
            return _operations_problem_response(request, _run_not_found())
        return result

    @app.get(
        "/api/v1/documents/{document_id}/ingestion-runs",
        response_model=None,
    )
    def list_document_ingestion_runs(
        document_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
        cx_tenant_id: str | None = Header(default=None, alias=CX_TENANT_HEADER),
        cx_subject_id: str | None = Header(default=None, alias=CX_SUBJECT_HEADER),
    ):
        access_context = authorize_cx_owner_request(
            request,
            authorization,
            tenant_id=cx_tenant_id,
            subject_id=cx_subject_id,
        )
        if isinstance(access_context, JSONResponse):
            return access_context
        try:
            return list_document_ingestion_run_read_models(
                document_id,
                tenant_id=access_context.tenant_id,
                owner_subject_id=access_context.subject_id,
                run_repository=run_repository,
            )
        except IngestionReadModelError as exc:
            return _operations_problem_response(request, _read_model_error(exc))

    @app.get("/internal/v1/ingestion/restart-plan", response_model=None)
    def get_ingestion_restart_plan(
        request: Request,
        authorization: str | None = Header(default=None),
        limit: str | None = Query(default=None),
    ):
        auth_failure = authorize_cx_request(request, authorization)
        if auth_failure is not None:
            return auth_failure
        try:
            return build_ingestion_restart_plan(
                job_queue=job_queue,
                run_repository=run_repository,
                limit=limit,
            )
        except IngestionReadModelError as exc:
            return _operations_problem_response(request, _read_model_error(exc))

    @app.post(
        "/internal/v1/ingestion/jobs/{job_id}/recover-expired-lease",
        response_model=None,
    )
    def recover_ingestion_lease(
        job_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_failure = authorize_cx_request(request, authorization)
        if auth_failure is not None:
            return auth_failure
        try:
            result = recover_expired_ingestion_job(
                job_id,
                job_queue=job_queue,
                run_repository=run_repository,
            )
        except IngestionWorkerError as exc:
            return _operations_problem_response(request, _worker_error(exc))
        event_result = emitter.safe_emit(
            event_type=CX_INGESTION_LEASE_RECOVERED_EVENT,
            severity="WARNING",
            message="CX durable ingestion lease was recovered.",
            trace_id=trace_id_from_headers(request),
            request_id=request_id_from_headers(request),
            subject_ref=build_subject_ref("job", job_id),
            details={
                "run_id": result["run_id"],
                "job_status": result["job_status"],
                "run_status": result["run_status"],
                "checkpoint_version": result["checkpoint_version"],
                "retry_at": result["retry_at"],
                "failed_step": result["failed_step"],
                "error_code": result["error_code"],
                "recovered": result["recovered"],
            },
            event_id=_recovery_event_id(
                job_id=job_id,
                checkpoint_version=result["checkpoint_version"],
            ),
        )
        return {
            "recovery_schema_version": CX_INGESTION_RECOVERY_SCHEMA_VERSION,
            "action": "RECOVER_EXPIRED_LEASE",
            "result": result,
            "observability": event_result.to_summary(),
        }


def _recovery_event_id(*, job_id: str, checkpoint_version: object) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            f"cx-ingestion-recovery:{job_id}:{checkpoint_version}",
        )
    )


def _read_model_error(exc: IngestionReadModelError) -> IngestionOperationsError:
    return IngestionOperationsError(
        error_code=exc.error_code,
        detail=exc.detail,
        status_code=exc.status_code,
        retryable=exc.status_code >= 500,
    )


def _worker_error(exc: IngestionWorkerError) -> IngestionOperationsError:
    return IngestionOperationsError(
        error_code=exc.error_code,
        detail=exc.detail,
        status_code=exc.status_code,
        retryable=exc.retryable,
    )


def _run_not_found() -> IngestionOperationsError:
    return IngestionOperationsError(
        error_code="cx.ingestion_run.not_found",
        detail="Ingestion run was not found in the owner scope.",
        status_code=404,
    )


def _operations_problem_response(
    request: Request,
    exc: IngestionOperationsError,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Durable ingestion operation failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/durable-ingestion-operation-failed",
    )
