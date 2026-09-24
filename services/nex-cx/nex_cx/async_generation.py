from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from nex_runtime import JobQueue, JobQueueError

from nex_cx.access_context import CxAccessContext
from nex_cx.async_generation_contracts import (
    build_async_generation_job,
    project_async_generation_job,
    validate_async_generation_job,
)
from nex_cx.generation_request_store import (
    build_generation_request_envelope,
    persist_generation_request_envelope,
)
from nex_cx.generation_runtime import (
    GroundedGenerationRuntime,
    GroundedGenerationRuntimeError,
)
from nex_cx.private_content import CxPrivateContentError, CxPrivateTextStore


@dataclass(frozen=True)
class AsyncGenerationAdmissionError(Exception):
    error_code: str
    detail: str
    status_code: int = 409
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


def admit_async_generation(
    *,
    source_payload: Mapping[str, Any],
    mo_payload: Mapping[str, Any],
    compatibility_rule: Mapping[str, Any],
    retrieval_package: Mapping[str, Any] | None,
    access_context: CxAccessContext,
    request_id: str,
    trace_id: str,
    idempotency_key: str | None,
    runtime: GroundedGenerationRuntime,
    request_store: CxPrivateTextStore,
    job_queue: JobQueue,
) -> dict[str, Any]:
    try:
        admission = runtime.admit(
            source_payload=source_payload,
            mo_payload=mo_payload,
            access_context=access_context,
            request_id=request_id,
            trace_id=trace_id,
            idempotency_key=idempotency_key,
            allow_in_progress_join=True,
        )
        generation_id = admission.mo_payload["cx_generation_id"]
        if admission.is_replay:
            existing_job = job_queue.get_job(_job_id_for_admission(admission))
            return {
                "admission_status": "REPLAYED",
                "job": (
                    project_async_generation_job(existing_job)
                    if existing_job is not None
                    else None
                ),
                "generation": admission.existing_record,
            }

        envelope = build_generation_request_envelope(
            access_context=access_context,
            cx_generation_id=generation_id,
            admission_id=admission.admission["admission_id"],
            source_payload=source_payload,
            mo_payload=admission.mo_payload,
            compatibility_rule=compatibility_rule,
            retrieval_package=retrieval_package,
            request_id=request_id,
            trace_id=trace_id,
        )
        receipt = persist_generation_request_envelope(
            private_text_store=request_store,
            access_context=access_context,
            envelope=envelope,
        )
        candidate = build_async_generation_job(
            cx_generation_id=generation_id,
            admission_id=admission.admission["admission_id"],
            access_context=access_context,
            request_envelope_sha256=receipt["request_envelope_sha256"],
            request_envelope_size_bytes=receipt["request_envelope_size_bytes"],
            trace_id=trace_id,
            request_id=request_id,
        )
        stored = validate_async_generation_job(job_queue.enqueue(candidate))
        _assert_same_envelope(stored, candidate)
        return {
            "admission_status": "JOINED" if admission.is_join else "ENQUEUED",
            "job": project_async_generation_job(stored),
            "generation": None,
        }
    except AsyncGenerationAdmissionError:
        raise
    except GroundedGenerationRuntimeError as exc:
        raise AsyncGenerationAdmissionError(
            error_code=exc.error_code,
            detail=exc.detail,
            status_code=exc.status_code,
            retryable=exc.retryable,
        ) from exc
    except CxPrivateContentError as exc:
        raise AsyncGenerationAdmissionError(
            error_code=exc.error_code,
            detail=exc.detail,
            status_code=exc.status_code,
            retryable=exc.retryable,
        ) from exc
    except JobQueueError as exc:
        raise AsyncGenerationAdmissionError(
            error_code=exc.error_code,
            detail=exc.detail,
            status_code=exc.status_code,
            retryable=exc.status_code >= 500,
        ) from exc


def _assert_same_envelope(
    stored: Mapping[str, Any], candidate: Mapping[str, Any]
) -> None:
    stored_payload = stored["payload"]
    candidate_payload = candidate["payload"]
    for field in (
        "cx_generation_id",
        "admission_id",
        "tenant_ref_id",
        "owner_subject_ref_id",
        "request_envelope_sha256",
        "request_envelope_size_bytes",
    ):
        if stored_payload[field] != candidate_payload[field]:
            raise AsyncGenerationAdmissionError(
                error_code="cx.async_generation.idempotency_conflict",
                detail="Existing async generation job is bound to another request.",
                status_code=409,
            )


def _job_id_for_admission(admission: object) -> str:
    from nex_cx.async_generation_contracts import async_generation_job_id

    mo_payload = getattr(admission, "mo_payload")
    return async_generation_job_id(str(mo_payload["cx_generation_id"]))
