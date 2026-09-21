from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from nex_runtime import JobQueue, JobQueueError

from nex_cx.ingestion_orchestration import (
    IngestionOrchestrationPolicy,
    build_ingestion_run,
)
from nex_cx.ingestion_orchestration_repository import (
    IngestionRunRepository,
    IngestionRunRepositoryError,
)


CX_DURABLE_INGESTION_ADMISSION_SCHEMA_VERSION = (
    "cx_durable_ingestion_admission.v1"
)


@dataclass(frozen=True)
class DurableIngestionAdmissionError(Exception):
    error_code: str
    detail: str
    status_code: int = 503
    retryable: bool = True

    def __str__(self) -> str:
        return self.detail


def admit_durable_ingestion(
    registration: Mapping[str, Any],
    *,
    job_queue: JobQueue,
    run_repository: IngestionRunRepository,
    policy: IngestionOrchestrationPolicy | None = None,
) -> dict[str, Any]:
    document_id = _required_string(registration.get("document_id"), "document_id")
    upload_id = _required_string(registration.get("upload_id"), "upload_id")
    trace_id = _required_string(registration.get("trace_id"), "trace_id")
    request_id = _required_string(registration.get("request_id"), "request_id")
    ownership_ref = _required_mapping(registration.get("ownership_ref"), "ownership_ref")
    tenant_ref = _required_mapping(ownership_ref.get("tenant_ref"), "tenant_ref")
    owner_subject_ref = _required_mapping(
        ownership_ref.get("owner_subject_ref"),
        "owner_subject_ref",
    )
    registration_job = _required_mapping(
        registration.get("ingestion_job"),
        "ingestion_job",
    )
    resolved_policy = policy or IngestionOrchestrationPolicy()
    job = {
        **registration_job,
        "max_attempts": resolved_policy.max_attempts,
        "retryable": True,
    }
    try:
        queued_job = job_queue.enqueue(job)
    except JobQueueError as exc:
        raise DurableIngestionAdmissionError(
            error_code="cx.ingestion_admission.job_queue_failed",
            detail=exc.detail,
            status_code=exc.status_code,
            retryable=exc.status_code >= 500,
        ) from exc
    if queued_job.get("job_id") != registration_job.get("job_id"):
        raise DurableIngestionAdmissionError(
            error_code="cx.ingestion_admission.job_identity_conflict",
            detail="Durable ingestion admission resolved a different queue job.",
            status_code=409,
            retryable=False,
        )

    run = build_ingestion_run(
        document_id=document_id,
        job_id=_required_string(queued_job.get("job_id"), "ingestion_job.job_id"),
        idempotency_key=upload_id,
        tenant_ref=tenant_ref,
        owner_subject_ref=owner_subject_ref,
        trace_id=trace_id,
        request_id=request_id,
        created_at=_required_string(registration.get("created_at"), "created_at"),
        policy=resolved_policy,
    )
    try:
        admitted_run = run_repository.create(run)
    except IngestionRunRepositoryError as exc:
        raise DurableIngestionAdmissionError(
            error_code="cx.ingestion_admission.run_repository_failed",
            detail=exc.detail,
            status_code=exc.status_code,
            retryable=exc.status_code >= 500,
        ) from exc
    if admitted_run["job_id"] != queued_job["job_id"]:
        raise DurableIngestionAdmissionError(
            error_code="cx.ingestion_admission.run_identity_conflict",
            detail="Durable ingestion run is linked to a different queue job.",
            status_code=409,
            retryable=False,
        )
    return {
        "admission_schema_version": CX_DURABLE_INGESTION_ADMISSION_SCHEMA_VERSION,
        "status": "ADMITTED",
        "document_id": document_id,
        "upload_id": upload_id,
        "job": queued_job,
        "ingestion_run": admitted_run,
        "idempotent": (
            queued_job.get("created_at") != job.get("created_at")
            or admitted_run["run_id"] != run["run_id"]
            or registration.get("dedupe", {}).get("status") == "ALREADY_EXISTS"
        ),
        "recovery_policy": {
            "partial_success": "retry_same_owner_upload_id",
            "job_queue_idempotent": True,
            "run_repository_idempotent": True,
        },
    }


def _required_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DurableIngestionAdmissionError(
            error_code="cx.ingestion_admission.registration_invalid",
            detail=f"{field_name} must be an object.",
            status_code=422,
            retryable=False,
        )
    return value


def _required_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DurableIngestionAdmissionError(
            error_code="cx.ingestion_admission.registration_invalid",
            detail=f"{field_name} must be a non-empty string.",
            status_code=422,
            retryable=False,
        )
    return value.strip()
