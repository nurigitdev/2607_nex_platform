from __future__ import annotations

from typing import Any, Mapping

from nex_runtime import JobQueue

from nex_cx.access_context import CxAccessContext
from nex_cx.async_generation_contracts import validate_async_generation_job
from nex_cx.generation import GenerationFacadeError, build_generation_failure_record
from nex_cx.generation_runtime import (
    GroundedGenerationAdmission,
    GroundedGenerationRuntime,
)
from nex_cx.generation_request_store import load_generation_request_envelope
from nex_cx.private_content import CxPrivateTextStore
from nex_cx.worker_resilience import settle_worker_failure


CX_ASYNC_GENERATION_RECOVERY_SCHEMA_VERSION = "cx_async_generation_recovery.v1"


class AsyncGenerationLeaseExpired(RuntimeError):
    error_code = "cx.async_generation.lease_expired"
    status_code = 503
    retryable = True


class AsyncGenerationCancellation(RuntimeError):
    error_code = "cx.async_generation.cancelled"
    status_code = 409
    retryable = False


def should_finalize_generation_failure(
    job: Mapping[str, Any], failure: object
) -> bool:
    retryable = bool(getattr(failure, "retryable", False))
    return not retryable or int(job["attempt_count"]) >= int(job["max_attempts"])


def finalize_async_generation_failure(
    *,
    job: Mapping[str, Any],
    envelope: Mapping[str, Any],
    access_context: CxAccessContext,
    runtime: GroundedGenerationRuntime,
    failure: object,
) -> dict[str, Any]:
    facade_error = GenerationFacadeError(
        status_code=int(getattr(failure, "status_code", 500)),
        error_code=str(
            getattr(failure, "error_code", "cx.async_generation.execution_failed")
        ),
        detail="Asynchronous grounded generation execution failed.",
        retryable=bool(getattr(failure, "retryable", False)),
    )
    record = build_generation_failure_record(
        source_payload=dict(envelope["source_payload"]),
        mo_payload=dict(envelope["mo_payload"]),
        failure=facade_error,
        compatibility_rule=dict(envelope["compatibility_rule"]),
        retrieval_package=(
            dict(envelope["retrieval_package"])
            if envelope.get("retrieval_package") is not None
            else None
        ),
        request_id=str(envelope["request_id"]),
        trace_id=str(envelope["trace_id"]),
    )
    stored = runtime.persist_failed(
        admission=GroundedGenerationAdmission(
            "JOIN",
            {"admission_id": envelope["admission_id"]},
            dict(envelope["mo_payload"]),
        ),
        execution_record=record,
        access_context=access_context,
    )
    return {
        "recovery_schema_version": CX_ASYNC_GENERATION_RECOVERY_SCHEMA_VERSION,
        "job_id": str(job["job_id"]),
        "cx_generation_id": stored["cx_generation_id"],
        "generation_status": stored["status"],
        "failure_code": facade_error.error_code,
        "retryable": facade_error.retryable,
        "private_payload_included": False,
    }


def recover_expired_async_generation_job(
    job: Mapping[str, Any],
    observed_at: str,
    *,
    job_queue: JobQueue,
    envelope: Mapping[str, Any] | None = None,
    access_context: CxAccessContext | None = None,
    runtime: GroundedGenerationRuntime | None = None,
) -> dict[str, Any]:
    failure = AsyncGenerationLeaseExpired(
        "Asynchronous generation worker lease expired."
    )
    settlement = settle_worker_failure(
        job_queue=job_queue,
        job=job,
        failure=failure,
        failed_at=observed_at,
    )
    terminal = settlement["action"] == "DEAD_LETTERED"
    generation = None
    if terminal:
        if envelope is None or access_context is None or runtime is None:
            raise ValueError(
                "Terminal async generation recovery requires its private envelope and runtime."
            )
        generation = finalize_async_generation_failure(
            job=job,
            envelope=envelope,
            access_context=access_context,
            runtime=runtime,
            failure=failure,
        )
    return {
        "recovery_schema_version": CX_ASYNC_GENERATION_RECOVERY_SCHEMA_VERSION,
        "job_id": str(job["job_id"]),
        "status": settlement["action"],
        "generation": generation,
        "private_payload_included": False,
    }


def recover_persisted_async_generation_job(
    job: Mapping[str, Any],
    observed_at: str,
    *,
    job_queue: JobQueue,
    request_store: CxPrivateTextStore,
    runtime: GroundedGenerationRuntime,
) -> dict[str, Any]:
    normalized = validate_async_generation_job(job)
    context = async_generation_access_context(normalized)
    payload = normalized["payload"]
    envelope = load_generation_request_envelope(
        private_text_store=request_store,
        access_context=context,
        cx_generation_id=payload["cx_generation_id"],
        receipt=async_generation_request_receipt(payload),
    )
    if envelope is None:
        raise ValueError("Private async generation request is unavailable.")
    return recover_expired_async_generation_job(
        normalized,
        observed_at,
        job_queue=job_queue,
        envelope=envelope,
        access_context=context,
        runtime=runtime,
    )


def async_generation_access_context(job: Mapping[str, Any]) -> CxAccessContext:
    payload = job["payload"]
    return CxAccessContext(
        caller_service_id="nex-cx",
        tenant_id=str(payload["tenant_ref_id"]),
        subject_id=str(payload["owner_subject_ref_id"]),
        request_id=str(job["request_id"]),
        trace_id=str(job["trace_id"]),
        scopes=("service:call",),
    )


def async_generation_request_receipt(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "request_receipt_schema_version": "cx_generation_request_receipt.v1",
        "request_storage_backend": "owner-private",
        "request_storage_uri": "cx-private://generation-request",
        "request_envelope_sha256": payload["request_envelope_sha256"],
        "request_envelope_size_bytes": payload["request_envelope_size_bytes"],
    }
