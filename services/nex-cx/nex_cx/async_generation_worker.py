from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from nex_runtime import JobQueue, JobQueueError

from nex_cx.access_context import CxAccessContext
from nex_cx.async_generation_contracts import validate_async_generation_job
from nex_cx.drafts import build_structured_draft
from nex_cx.generation import (
    GenerationFacadeError,
    MoGenerationClient,
    build_generation_execution_record,
    output_text_from_mo_response,
    selected_evidence_ids_from_payload,
)
from nex_cx.generation_request_store import load_generation_request_envelope
from nex_cx.generation_runtime import (
    GroundedGenerationAdmission,
    GroundedGenerationRuntime,
    GroundedGenerationRuntimeError,
)
from nex_cx.grounded_output_validation import (
    GroundedOutputValidationError,
    normalize_generation_provider_response,
)
from nex_cx.private_content import CxPrivateContentError, CxPrivateTextStore
from nex_cx.worker_runtime import CxCancellationToken


CX_ASYNC_GENERATION_WORKER_RESULT_SCHEMA_VERSION = (
    "cx_async_generation_worker_result.v1"
)


@dataclass(frozen=True)
class AsyncGenerationWorkerError(Exception):
    error_code: str
    detail: str
    status_code: int = 500
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass
class AsyncGenerationWorkerHandler:
    job_queue: JobQueue
    runtime: GroundedGenerationRuntime
    request_store: CxPrivateTextStore
    generation_client: MoGenerationClient

    def __call__(
        self,
        execution: dict[str, Any],
        cancellation: CxCancellationToken,
    ) -> Mapping[str, Any]:
        try:
            job = self.job_queue.get_job(str(execution["job_id"]))
            if job is None:
                raise AsyncGenerationWorkerError(
                    error_code="cx.async_generation.job_not_found",
                    detail="Async generation job was not found.",
                    status_code=404,
                )
            normalized_job = validate_async_generation_job(job)
            payload = normalized_job["payload"]
            context = _worker_access_context(normalized_job)
            envelope = load_generation_request_envelope(
                private_text_store=self.request_store,
                access_context=context,
                cx_generation_id=payload["cx_generation_id"],
                receipt=_request_receipt(payload),
            )
            if envelope is None:
                raise AsyncGenerationWorkerError(
                    error_code="cx.async_generation.request_missing",
                    detail="Private async generation request is unavailable.",
                    status_code=503,
                    retryable=True,
                )
            cancellation.checkpoint()
            raw_response = self.generation_client.create_generation(
                envelope["mo_payload"],
                request_id=envelope["request_id"],
                trace_id=envelope["trace_id"],
            )
            cancellation.checkpoint()
            compatibility_rule = envelope["compatibility_rule"]
            retrieval_package = envelope["retrieval_package"]
            source_payload = envelope["source_payload"]
            mo_response = normalize_generation_provider_response(
                raw_response,
                grounding_required=bool(
                    compatibility_rule.get("grounding_required")
                ),
                retrieval_package=retrieval_package,
                selected_evidence_ids=selected_evidence_ids_from_payload(
                    source_payload
                ),
            )
            output_text = output_text_from_mo_response(mo_response)
            draft = build_structured_draft(
                cx_generation_id=payload["cx_generation_id"],
                trace_id=envelope["trace_id"],
                request_id=envelope["request_id"],
                output_text=output_text,
                compatibility_rule=compatibility_rule,
                retrieval_package=retrieval_package,
                selected_evidence_ids=selected_evidence_ids_from_payload(
                    source_payload
                ),
            )
            record = build_generation_execution_record(
                source_payload=source_payload,
                mo_payload=envelope["mo_payload"],
                mo_response=mo_response,
                compatibility_rule=compatibility_rule,
                retrieval_package=retrieval_package,
                structured_draft=draft,
                request_id=envelope["request_id"],
                trace_id=envelope["trace_id"],
            )
            stored = self.runtime.persist_completed(
                admission=GroundedGenerationAdmission(
                    "JOIN",
                    {"admission_id": envelope["admission_id"]},
                    envelope["mo_payload"],
                ),
                execution_record=record,
                output_text=output_text,
                access_context=context,
            )
            return {
                "worker_result_schema_version": (
                    CX_ASYNC_GENERATION_WORKER_RESULT_SCHEMA_VERSION
                ),
                "job_id": normalized_job["job_id"],
                "cx_generation_id": stored["cx_generation_id"],
                "generation_status": stored["status"],
                "output_sha256": stored["response_metadata"]["output_hash"],
                "provider_called": True,
                "private_output_included": False,
            }
        except AsyncGenerationWorkerError:
            raise
        except GroundedOutputValidationError as exc:
            raise _mapped_error(exc) from exc
        except GroundedGenerationRuntimeError as exc:
            raise _mapped_error(exc) from exc
        except CxPrivateContentError as exc:
            raise _mapped_error(exc) from exc
        except JobQueueError as exc:
            raise AsyncGenerationWorkerError(
                error_code=exc.error_code,
                detail=exc.detail,
                status_code=exc.status_code,
                retryable=exc.status_code >= 500,
            ) from exc
        except GenerationFacadeError as exc:
            raise _mapped_error(exc) from exc


def _worker_access_context(job: Mapping[str, Any]) -> CxAccessContext:
    payload = job["payload"]
    return CxAccessContext(
        caller_service_id="nex-cx",
        tenant_id=payload["tenant_ref_id"],
        subject_id=payload["owner_subject_ref_id"],
        request_id=job["request_id"],
        trace_id=job["trace_id"],
        scopes=("service:call",),
    )


def _request_receipt(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "request_receipt_schema_version": "cx_generation_request_receipt.v1",
        "request_storage_backend": "owner-private",
        "request_storage_uri": "cx-private://generation-request",
        "request_envelope_sha256": payload["request_envelope_sha256"],
        "request_envelope_size_bytes": payload["request_envelope_size_bytes"],
    }


def _mapped_error(exc: object) -> AsyncGenerationWorkerError:
    return AsyncGenerationWorkerError(
        error_code=str(
            getattr(exc, "error_code", "cx.async_generation.execution_failed")
        ),
        detail=str(getattr(exc, "detail", "Async generation execution failed.")),
        status_code=int(getattr(exc, "status_code", 500)),
        retryable=bool(getattr(exc, "retryable", False)),
    )
