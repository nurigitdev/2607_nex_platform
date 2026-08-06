from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable
from uuid import NAMESPACE_URL, uuid5

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    BUSY,
    CX_PROCESSING_EVENT_FAILED,
    CX_PROCESSING_EVENT_STARTED,
    CX_PROCESSING_EVENT_SUCCEEDED,
    ERROR,
    IDLE,
    InMemoryJobQueue,
    JobQueue,
    JobQueueError,
    OperationalEventEmitResult,
    OperationalEventEmitter,
    WorkerHeartbeatEmitResult,
    WorkerHeartbeatEmitter,
    build_common_job,
    build_subject_ref,
    operational_event_emitter_from_app,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
    validate_authorization_header,
    worker_heartbeat_emitter_from_app,
)
from nex_runtime.prompts import PromptRegistryStore

from nex_cx.chunking import ChunkingError, build_and_store_chunk_set
from nex_cx.embedding_index import (
    DEFAULT_EMBEDDING_ALIAS,
    EmbeddingIndexError,
    MoEmbeddingClient,
    build_and_store_embedding_index,
    build_default_mo_embedding_client,
)
from nex_cx.ingestion import (
    ContentIngestionStore,
    CxStorageConfig,
    IngestionError,
    build_storage_config,
    run_text_extraction_job,
)
from nex_cx.lexical_index import LexicalIndexError, build_and_store_lexical_index
from nex_cx.summaries import SummaryError, build_and_store_document_summary
from nex_cx.summary_embeddings import (
    SummaryEmbeddingError,
    build_and_store_summary_embedding_index,
)


PIPELINE_STEPS = (
    "extraction",
    "chunking",
    "lexical_index",
    "embedding_index",
    "summary",
    "summary_embedding",
)
PROCESSING_EVENT_STARTED = CX_PROCESSING_EVENT_STARTED
PROCESSING_EVENT_SUCCEEDED = CX_PROCESSING_EVENT_SUCCEEDED
PROCESSING_EVENT_FAILED = CX_PROCESSING_EVENT_FAILED
CX_PROCESSING_WORKER_ID = "cx-processing-inline-worker"
CX_PROCESSING_WORKER_TYPE = "cx.document_processing.worker"


@dataclass(frozen=True)
class ProcessingPipelineError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False
    pipeline_run: dict[str, Any] | None = None
    failed_step: str | None = None


def register_processing_routes(
    app: FastAPI,
    *,
    store: ContentIngestionStore,
    storage_config: CxStorageConfig | None = None,
    mo_client: MoEmbeddingClient | None = None,
    embedding_alias: str | None = None,
    prompt_store: PromptRegistryStore | None = None,
    job_queue: JobQueue | None = None,
    event_emitter: OperationalEventEmitter | None = None,
    worker_heartbeat_emitter: WorkerHeartbeatEmitter | None = None,
) -> None:
    config = storage_config or build_storage_config()
    client = mo_client or build_default_mo_embedding_client()
    alias = embedding_alias or DEFAULT_EMBEDDING_ALIAS
    queue = job_queue or InMemoryJobQueue()
    emitter = (
        event_emitter
        if event_emitter is not None
        else operational_event_emitter_from_app(app, service_id="nex-cx")
    )
    heartbeat_emitter = (
        worker_heartbeat_emitter
        if worker_heartbeat_emitter is not None
        else worker_heartbeat_emitter_from_app(
            app,
            service_id="nex-cx",
            worker_id=CX_PROCESSING_WORKER_ID,
            worker_type=CX_PROCESSING_WORKER_TYPE,
            metadata={"queue": "cx.document_processing", "runtime": "inline"},
        )
    )

    @app.post("/api/v1/documents/{document_id}/processing/run", response_model=None)
    def run_processing(
        document_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_cx_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        try:
            return run_document_processing_pipeline(
                document_id,
                store=store,
                storage_config=config,
                mo_client=client,
                embedding_alias=alias,
                prompt_store=prompt_store,
                job_queue=queue,
                event_emitter=emitter,
                worker_heartbeat_emitter=heartbeat_emitter,
                request_id=request_id_from_headers(request),
                trace_id=trace_id_from_headers(request),
            )
        except ProcessingPipelineError as exc:
            return _processing_problem_response(request, exc)

    @app.get("/api/v1/documents/{document_id}/processing", response_model=None)
    def get_latest_processing(
        document_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_cx_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        record = store.get_latest_document_processing_run(document_id)
        if record is None:
            return _processing_problem_response(
                request,
                ProcessingPipelineError(
                    status_code=404,
                    error_code="cx.processing_run_not_found",
                    detail=f"Processing run was not found: {document_id}",
                ),
            )
        return record


def run_document_processing_pipeline(
    document_id: str,
    *,
    store: ContentIngestionStore,
    storage_config: CxStorageConfig,
    mo_client: MoEmbeddingClient,
    embedding_alias: str,
    request_id: str,
    trace_id: str,
    prompt_store: PromptRegistryStore | None = None,
    job_queue: JobQueue | None = None,
    event_emitter: OperationalEventEmitter | None = None,
    worker_heartbeat_emitter: WorkerHeartbeatEmitter | None = None,
) -> dict[str, Any]:
    started_at = _utc_now()
    pipeline_run_id = str(
        uuid5(NAMESPACE_URL, f"cx-processing:{document_id}:{request_id}:{trace_id}")
    )
    queue = job_queue or InMemoryJobQueue()
    job, existing_run = _enqueue_or_resume_processing_job(
        queue,
        document_id=document_id,
        pipeline_run_id=pipeline_run_id,
        request_id=request_id,
        trace_id=trace_id,
        created_at=started_at,
        store=store,
    )
    if existing_run is not None:
        return existing_run
    _safe_emit_processing_event(
        event_emitter,
        event_type=PROCESSING_EVENT_STARTED,
        severity="INFO",
        message="CX document processing started.",
        document_id=document_id,
        pipeline_run_id=pipeline_run_id,
        request_id=request_id,
        trace_id=trace_id,
        job=job,
        created_at=started_at,
    )
    _safe_emit_processing_worker_heartbeat(
        worker_heartbeat_emitter,
        status=BUSY,
        document_id=document_id,
        pipeline_run_id=pipeline_run_id,
        trace_id=trace_id,
        job=job,
        observed_at=started_at,
    )
    steps: list[dict[str, Any]] = []

    try:
        _append_or_run_step(
            steps,
            step_id="extraction",
            existing=store.get_extraction_result(document_id),
            output_factory=lambda: run_text_extraction_job(
                extraction_job_id_for_document(store, document_id),
                store=store,
                storage_config=storage_config,
                request_id=request_id,
                trace_id=trace_id,
            ),
        )
        _append_or_run_step(
            steps,
            step_id="chunking",
            existing=store.get_chunk_set(document_id),
            output_factory=lambda: build_and_store_chunk_set(
                document_id,
                store=store,
                storage_config=storage_config,
                request_id=request_id,
                trace_id=trace_id,
            ),
        )
        _append_or_run_step(
            steps,
            step_id="lexical_index",
            existing=store.get_lexical_index(document_id),
            output_factory=lambda: build_and_store_lexical_index(
                document_id,
                store=store,
                storage_config=storage_config,
                request_id=request_id,
                trace_id=trace_id,
            ),
        )
        _append_or_run_step(
            steps,
            step_id="embedding_index",
            existing=store.get_embedding_index(document_id),
            output_factory=lambda: build_and_store_embedding_index(
                document_id,
                store=store,
                mo_client=mo_client,
                embedding_alias=embedding_alias,
                request_id=request_id,
                trace_id=trace_id,
            ),
        )
        _append_or_run_step(
            steps,
            step_id="summary",
            existing=store.get_document_summary(document_id),
            output_factory=lambda: build_and_store_document_summary(
                document_id,
                store=store,
                prompt_store=prompt_store,
                request_id=request_id,
                trace_id=trace_id,
            ),
        )
        _append_or_run_step(
            steps,
            step_id="summary_embedding",
            existing=store.get_summary_embedding_index(document_id),
            output_factory=lambda: build_and_store_summary_embedding_index(
                document_id,
                store=store,
                mo_client=mo_client,
                embedding_alias=embedding_alias,
                request_id=request_id,
                trace_id=trace_id,
            ),
        )
    except Exception as exc:
        failed_step = _failed_step_id(steps)
        failed_run = build_pipeline_run_record(
            document_id=document_id,
            pipeline_run_id=pipeline_run_id,
            request_id=request_id,
            trace_id=trace_id,
            started_at=started_at,
            steps=steps,
            status="FAILED",
            job=_safe_fail_job(queue, job["job_id"]),
        )
        saved_failed_run = store.save_document_processing_run(failed_run)
        _safe_emit_processing_event(
            event_emitter,
            event_type=PROCESSING_EVENT_FAILED,
            severity="ERROR",
            message="CX document processing failed.",
            document_id=document_id,
            pipeline_run_id=pipeline_run_id,
            request_id=request_id,
            trace_id=trace_id,
            job=saved_failed_run.get("job"),
            step_summary=saved_failed_run["step_summary"],
            failed_step=failed_step,
            created_at=saved_failed_run["completed_at"],
        )
        _safe_emit_processing_worker_heartbeat(
            worker_heartbeat_emitter,
            status=ERROR,
            document_id=document_id,
            pipeline_run_id=pipeline_run_id,
            trace_id=trace_id,
            job=saved_failed_run.get("job"),
            step_summary=saved_failed_run["step_summary"],
            failed_step=failed_step,
            observed_at=saved_failed_run["completed_at"],
        )
        raise _pipeline_error_from_exception(
            exc,
            pipeline_run=saved_failed_run,
            failed_step=failed_step,
        ) from exc

    completed_job = queue.complete_job(job["job_id"])
    record = build_pipeline_run_record(
        document_id=document_id,
        pipeline_run_id=pipeline_run_id,
        request_id=request_id,
        trace_id=trace_id,
        started_at=started_at,
        steps=steps,
        status="SUCCEEDED",
        job=completed_job,
    )
    saved_record = store.save_document_processing_run(record)
    _safe_emit_processing_event(
        event_emitter,
        event_type=PROCESSING_EVENT_SUCCEEDED,
        severity="INFO",
        message="CX document processing succeeded.",
        document_id=document_id,
        pipeline_run_id=pipeline_run_id,
        request_id=request_id,
        trace_id=trace_id,
        job=saved_record.get("job"),
        step_summary=saved_record["step_summary"],
        created_at=saved_record["completed_at"],
    )
    _safe_emit_processing_worker_heartbeat(
        worker_heartbeat_emitter,
        status=IDLE,
        document_id=document_id,
        pipeline_run_id=pipeline_run_id,
        trace_id=trace_id,
        job=saved_record.get("job"),
        step_summary=saved_record["step_summary"],
        observed_at=saved_record["completed_at"],
    )
    return saved_record


def build_processing_job(
    *,
    document_id: str,
    pipeline_run_id: str,
    request_id: str,
    trace_id: str,
    created_at: str,
) -> dict[str, Any]:
    return build_common_job(
        job_id=str(uuid5(NAMESPACE_URL, f"cx-processing-job:{pipeline_run_id}")),
        job_type="cx.document_processing",
        trace_id=trace_id,
        request_id=request_id,
        subject_ref=build_subject_ref("cx.document", document_id),
        idempotency_key=pipeline_run_id,
        max_attempts=1,
        retryable=True,
        links={
            "document": f"/api/v1/documents/{document_id}",
            "processing": f"/api/v1/documents/{document_id}/processing",
        },
        created_at=created_at,
    )


def processing_event_id(
    *,
    pipeline_run_id: str,
    event_type: str,
) -> str:
    return str(uuid5(NAMESPACE_URL, f"cx-processing-event:{pipeline_run_id}:{event_type}"))


def _safe_emit_processing_event(
    event_emitter: OperationalEventEmitter | None,
    *,
    event_type: str,
    severity: str,
    message: str,
    document_id: str,
    pipeline_run_id: str,
    request_id: str,
    trace_id: str,
    job: dict[str, Any] | None = None,
    step_summary: dict[str, Any] | None = None,
    failed_step: str | None = None,
    created_at: str | None = None,
) -> OperationalEventEmitResult | None:
    if event_emitter is None:
        return None
    details: dict[str, Any] = {"pipeline_run_id": pipeline_run_id}
    if job is not None:
        details["job_id"] = str(job["job_id"])
        details["job_status"] = str(job["status"])
    if step_summary is not None:
        details["step_summary"] = dict(step_summary)
    if failed_step is not None:
        details["failed_step"] = failed_step
    return event_emitter.safe_emit(
        event_type=event_type,
        severity=severity,
        message=message,
        trace_id=trace_id,
        request_id=request_id,
        subject_ref=build_subject_ref("cx.document", document_id),
        details=details,
        created_at=created_at,
        event_id=processing_event_id(
            pipeline_run_id=pipeline_run_id,
            event_type=event_type,
        ),
    )


def _safe_emit_processing_worker_heartbeat(
    worker_heartbeat_emitter: WorkerHeartbeatEmitter | None,
    *,
    status: str,
    document_id: str,
    pipeline_run_id: str,
    trace_id: str,
    job: dict[str, Any] | None,
    step_summary: dict[str, Any] | None = None,
    failed_step: str | None = None,
    observed_at: str | None = None,
) -> WorkerHeartbeatEmitResult | None:
    if worker_heartbeat_emitter is None:
        return None
    metadata: dict[str, Any] = {
        "document_id": document_id,
        "pipeline_run_id": pipeline_run_id,
    }
    active_job_id = None
    if job is not None:
        active_job_id = str(job["job_id"]) if status in (BUSY, ERROR) else None
        metadata["job_id"] = str(job["job_id"])
        metadata["job_status"] = str(job["status"])
    if step_summary is not None:
        metadata["step_summary"] = dict(step_summary)
    if failed_step is not None:
        metadata["failed_step"] = failed_step
    return worker_heartbeat_emitter.safe_emit(
        status=status,
        active_job_id=active_job_id,
        trace_id=trace_id,
        metadata=metadata,
        observed_at=observed_at,
    )


def _enqueue_or_resume_processing_job(
    queue: JobQueue,
    *,
    document_id: str,
    pipeline_run_id: str,
    request_id: str,
    trace_id: str,
    created_at: str,
    store: ContentIngestionStore,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    job = queue.enqueue(
        build_processing_job(
            document_id=document_id,
            pipeline_run_id=pipeline_run_id,
            request_id=request_id,
            trace_id=trace_id,
            created_at=created_at,
        )
    )
    if job["status"] == "QUEUED":
        return queue.start_job(job["job_id"], updated_at=created_at), None
    if job["status"] == "RUNNING":
        return job, None

    existing_run = store.get_document_processing_run(pipeline_run_id)
    if existing_run is not None:
        return job, existing_run
    raise ProcessingPipelineError(
        status_code=409,
        error_code="cx.processing_job_terminal",
        detail=f"Processing job is already terminal: {job['job_id']}",
        retryable=False,
    )


def _safe_fail_job(queue: JobQueue, job_id: str) -> dict[str, Any] | None:
    try:
        return queue.fail_job(job_id)
    except JobQueueError:
        return queue.get_job(job_id)


def extraction_job_id_for_document(store: ContentIngestionStore, document_id: str) -> str:
    document = store.get_document(document_id)
    if document is None:
        raise IngestionError(
            status_code=404,
            error_code="cx.document_not_found",
            detail=f"Document registration was not found: {document_id}",
        )
    return str(document["extraction"]["job_id"])


def _append_or_run_step(
    steps: list[dict[str, Any]],
    *,
    step_id: str,
    existing: dict[str, Any] | None,
    output_factory: Callable[[], dict[str, Any]],
) -> None:
    if existing is not None:
        steps.append(build_pipeline_step(step_id, status="SKIPPED", output=existing))
        return
    try:
        output = output_factory()
    except Exception as exc:
        steps.append(build_failed_pipeline_step(step_id, exc))
        raise
    steps.append(build_pipeline_step(step_id, status="SUCCEEDED", output=output))


def build_pipeline_run_record(
    *,
    document_id: str,
    pipeline_run_id: str,
    request_id: str,
    trace_id: str,
    started_at: str,
    steps: list[dict[str, Any]],
    status: str,
    job: dict[str, Any] | None = None,
) -> dict[str, Any]:
    completed_at = _utc_now()
    record = {
        "pipeline_schema_version": "cx_document_processing_pipeline.v1",
        "pipeline_run_id": pipeline_run_id,
        "document_id": document_id,
        "status": status,
        "trace_id": trace_id,
        "request_id": request_id,
        "steps": steps,
        "step_summary": {
            "total": len(steps),
            "succeeded": _count_steps(steps, "SUCCEEDED"),
            "skipped": _count_steps(steps, "SKIPPED"),
            "failed": _count_steps(steps, "FAILED"),
        },
        "started_at": started_at,
        "completed_at": completed_at,
        "updated_at": completed_at,
    }
    if job is not None:
        record["job"] = processing_job_snapshot(job)
    return record


def processing_job_snapshot(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_schema_version": job["job_schema_version"],
        "job_id": job["job_id"],
        "job_type": job["job_type"],
        "status": job["status"],
        "subject_ref": dict(job["subject_ref"]),
        "idempotency_key": job["idempotency_key"],
        "attempt_count": job["attempt_count"],
        "max_attempts": job["max_attempts"],
        "retryable": job["retryable"],
        "links": dict(job["links"]),
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
    }


def build_pipeline_step(
    step_id: str,
    *,
    status: str,
    output: dict[str, Any],
) -> dict[str, Any]:
    return {
        "step_id": step_id,
        "status": status,
        "output_ref": output_ref_for_step(step_id, output),
        "error": None,
    }


def build_failed_pipeline_step(step_id: str, exc: Exception) -> dict[str, Any]:
    return {
        "step_id": step_id,
        "status": "FAILED",
        "output_ref": None,
        "error": safe_error_from_exception(exc),
    }


def output_ref_for_step(step_id: str, output: dict[str, Any]) -> dict[str, Any]:
    if step_id == "summary":
        return {
            "type": "cx.document_summary",
            "id": output["document_summary_id"],
            "document_id": output["document_id"],
        }
    if step_id == "summary_embedding":
        return {
            "type": "cx.document_summary_embedding",
            "id": output["document_summary_id"],
            "document_id": output["document_id"],
        }
    return {
        "type": f"cx.{step_id}",
        "id": output["document_id"],
        "document_id": output["document_id"],
    }


def safe_error_from_exception(exc: Exception) -> dict[str, Any]:
    return {
        "error_code": str(getattr(exc, "error_code", "cx.processing_step_failed")),
        "detail": str(getattr(exc, "detail", "Document processing step failed.")),
        "retryable": bool(getattr(exc, "retryable", False)),
    }


def _pipeline_error_from_exception(
    exc: Exception,
    *,
    pipeline_run: dict[str, Any],
    failed_step: str | None,
) -> ProcessingPipelineError:
    return ProcessingPipelineError(
        status_code=int(getattr(exc, "status_code", 500)),
        error_code=str(getattr(exc, "error_code", "cx.processing_pipeline_failed")),
        detail=str(getattr(exc, "detail", "Document processing pipeline failed.")),
        retryable=bool(getattr(exc, "retryable", False)),
        pipeline_run=pipeline_run,
        failed_step=failed_step,
    )


def _failed_step_id(steps: list[dict[str, Any]]) -> str | None:
    for step in steps:
        if step["status"] == "FAILED":
            return str(step["step_id"])
    return None


def _count_steps(steps: list[dict[str, Any]], status: str) -> int:
    return sum(1 for step in steps if step["status"] == status)


def _authorize_cx_request(
    request: Request,
    authorization: str | None,
) -> JSONResponse | None:
    result = validate_authorization_header(
        authorization,
        expected_audience="nex-cx",
        required_scopes=[DEFAULT_SERVICE_SCOPE],
    )
    if result.ok:
        return None

    return problem_response(
        request,
        status_code=401,
        error_code=result.error_code or "SERVICE_CLAIM_INVALID",
        title="Authentication failed",
        detail=result.detail or "CX requires a valid service claim.",
        type_uri="https://nex-platform.local/problems/authentication-failed",
    )


def _processing_problem_response(
    request: Request,
    exc: ProcessingPipelineError,
) -> JSONResponse:
    details = None
    if exc.pipeline_run is not None:
        details = {
            "pipeline_run_id": exc.pipeline_run["pipeline_run_id"],
            "failed_step": exc.failed_step,
            "step_summary": exc.pipeline_run["step_summary"],
        }
        if "job" in exc.pipeline_run:
            details["job_id"] = exc.pipeline_run["job"]["job_id"]
            details["job_status"] = exc.pipeline_run["job"]["status"]
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Document processing pipeline failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/document-processing-failed",
        details=details,
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
