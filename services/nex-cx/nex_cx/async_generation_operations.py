from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from nex_runtime import (
    JobQueue,
    JobQueueError,
    request_id_from_headers,
    trace_id_from_headers,
)

from nex_cx.authorization import (
    CX_SUBJECT_HEADER,
    CX_TENANT_HEADER,
    authorize_cx_owner_request,
)
from nex_cx.async_generation import (
    AsyncGenerationAdmissionError,
    admit_async_generation,
)
from nex_cx.async_generation_contracts import (
    project_async_generation_job,
    validate_async_generation_job,
)
from nex_cx.async_generation_recovery import (
    AsyncGenerationCancellation,
    async_generation_access_context,
    async_generation_request_receipt,
    finalize_async_generation_failure,
)
from nex_cx.generation import (
    GenerationFacadeError,
    RetrievalPackageStore,
    build_mo_generation_payload,
    validate_generation_request,
)
from nex_cx.generation_request_store import load_generation_request_envelope
from nex_cx.generation_runtime import GroundedGenerationRuntime
from nex_cx.private_content import CxPrivateContentError, CxPrivateTextStore


def register_async_generation_operations_routes(
    app: FastAPI,
    *,
    job_queue: JobQueue,
    runtime: GroundedGenerationRuntime | None,
    request_store: CxPrivateTextStore,
    retrieval_store: RetrievalPackageStore | None = None,
) -> None:
    @app.post("/api/v1/generation-jobs", response_model=None)
    def create_async_generation(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
        cx_tenant_id: str | None = Header(default=None, alias=CX_TENANT_HEADER),
        cx_subject_id: str | None = Header(default=None, alias=CX_SUBJECT_HEADER),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        context = authorize_cx_owner_request(
            request,
            authorization,
            tenant_id=cx_tenant_id,
            subject_id=cx_subject_id,
        )
        if isinstance(context, JSONResponse):
            return context
        if runtime is None:
            return _problem(
                503,
                "cx.async_generation.runtime_unavailable",
                "Durable asynchronous generation runtime is unavailable.",
                retryable=True,
            )
        request_id = request_id_from_headers(request)
        trace_id = payload.get("trace_id") or trace_id_from_headers(request)
        try:
            compatibility_rule, retrieval_package = validate_generation_request(
                payload,
                retrieval_store=retrieval_store,
                access_context=context,
            )
            mo_payload = build_mo_generation_payload(
                payload,
                trace_id=trace_id,
                retrieval_package=retrieval_package,
            )
            result = admit_async_generation(
                source_payload=payload,
                mo_payload=mo_payload,
                compatibility_rule=compatibility_rule,
                retrieval_package=retrieval_package,
                access_context=context,
                request_id=request_id,
                trace_id=trace_id,
                idempotency_key=idempotency_key,
                runtime=runtime,
                request_store=request_store,
                job_queue=job_queue,
            )
            status_code = 200 if result["admission_status"] == "REPLAYED" else 202
            return JSONResponse(status_code=status_code, content=result)
        except (AsyncGenerationAdmissionError, GenerationFacadeError) as exc:
            return _exception_problem(exc)

    @app.get("/api/v1/generation-jobs/{job_id}", response_model=None)
    def get_async_generation_job(
        job_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
        cx_tenant_id: str | None = Header(default=None, alias=CX_TENANT_HEADER),
        cx_subject_id: str | None = Header(default=None, alias=CX_SUBJECT_HEADER),
    ):
        context = authorize_cx_owner_request(
            request, authorization, tenant_id=cx_tenant_id, subject_id=cx_subject_id
        )
        if isinstance(context, JSONResponse):
            return context
        try:
            job = job_queue.get_job(job_id)
            if job is None or not _visible(job, context.tenant_id, context.subject_id):
                return _not_found()
            return project_async_generation_job(job)
        except JobQueueError as exc:
            return _exception_problem(exc)

    @app.post("/api/v1/generation-jobs/{job_id}/cancel", response_model=None)
    def cancel_async_generation_job(
        job_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
        cx_tenant_id: str | None = Header(default=None, alias=CX_TENANT_HEADER),
        cx_subject_id: str | None = Header(default=None, alias=CX_SUBJECT_HEADER),
    ):
        context = authorize_cx_owner_request(
            request, authorization, tenant_id=cx_tenant_id, subject_id=cx_subject_id
        )
        if isinstance(context, JSONResponse):
            return context
        if runtime is None:
            return _problem(
                503,
                "cx.async_generation.runtime_unavailable",
                "Durable asynchronous generation runtime is unavailable.",
                retryable=True,
            )
        try:
            current = job_queue.get_job(job_id)
            if current is None or not _visible(
                current, context.tenant_id, context.subject_id
            ):
                return _not_found()
            normalized = validate_async_generation_job(current)
            cancelled = job_queue.cancel_job(job_id)
            if current["status"] == "QUEUED":
                worker_context = async_generation_access_context(normalized)
                envelope = load_generation_request_envelope(
                    private_text_store=request_store,
                    access_context=worker_context,
                    cx_generation_id=normalized["payload"]["cx_generation_id"],
                    receipt=async_generation_request_receipt(normalized["payload"]),
                )
                if envelope is None:
                    raise CxPrivateContentError(
                        status_code=503,
                        error_code="CX_GENERATION_REQUEST_NOT_FOUND",
                        detail="Private async generation request is unavailable.",
                        retryable=True,
                    )
                finalize_async_generation_failure(
                    job=normalized,
                    envelope=envelope,
                    access_context=worker_context,
                    runtime=runtime,
                    failure=AsyncGenerationCancellation("cancelled"),
                )
            return project_async_generation_job(cancelled)
        except (JobQueueError, CxPrivateContentError) as exc:
            return _exception_problem(exc)


def _visible(job: dict[str, Any], tenant_id: str, subject_id: str) -> bool:
    try:
        payload = validate_async_generation_job(job)["payload"]
    except Exception:
        return False
    return (
        payload["tenant_ref_id"] == tenant_id
        and payload["owner_subject_ref_id"] == subject_id
    )


def _not_found() -> JSONResponse:
    return _problem(
        404,
        "cx.async_generation.job_not_found",
        "Async generation job was not found.",
    )


def _exception_problem(exc: object) -> JSONResponse:
    return _problem(
        int(getattr(exc, "status_code", 500)),
        str(getattr(exc, "error_code", "cx.async_generation.failed")),
        str(getattr(exc, "detail", "Async generation operation failed.")),
        retryable=bool(getattr(exc, "retryable", False)),
    )


def _problem(
    status_code: int,
    error_code: str,
    detail: str,
    *,
    retryable: bool = False,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error_code": error_code,
            "detail": detail,
            "retryable": retryable,
        },
    )
