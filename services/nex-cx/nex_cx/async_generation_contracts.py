from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
import re
from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid5

from nex_runtime import build_common_job, validate_common_job

from nex_cx.access_context import CxAccessContext


CX_ASYNC_GENERATION_JOB_SCHEMA_VERSION = "cx_async_generation_job.v1"
CX_ASYNC_GENERATION_JOB_TYPE = "cx.grounded-generation.execute"
DEFAULT_ASYNC_GENERATION_MAX_ATTEMPTS = 3

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_PRIVATE_KEYS = frozenset(
    {
        "prompt",
        "prompt_text",
        "output_text",
        "evidence_text",
        "request_body",
        "api_key",
        "authorization",
        "service_token",
    }
)


@dataclass(frozen=True)
class AsyncGenerationContractError(ValueError):
    error_code: str
    detail: str
    status_code: int = 422

    def __str__(self) -> str:
        return self.detail


def build_async_generation_job(
    *,
    cx_generation_id: str,
    admission_id: str,
    access_context: CxAccessContext,
    request_envelope_sha256: str,
    request_envelope_size_bytes: int,
    trace_id: str,
    request_id: str,
    created_at: str | None = None,
    max_attempts: int = DEFAULT_ASYNC_GENERATION_MAX_ATTEMPTS,
) -> dict[str, Any]:
    generation_id = _required_text(cx_generation_id, "cx_generation_id")
    payload = {
        "async_generation_schema_version": CX_ASYNC_GENERATION_JOB_SCHEMA_VERSION,
        "cx_generation_id": generation_id,
        "admission_id": _required_text(admission_id, "admission_id"),
        "tenant_ref_id": _required_text(access_context.tenant_id, "tenant_ref_id"),
        "owner_subject_ref_id": _required_text(
            access_context.subject_id,
            "owner_subject_ref_id",
        ),
        "request_envelope_sha256": _sha256(request_envelope_sha256),
        "request_envelope_size_bytes": _positive_int(
            request_envelope_size_bytes,
            "request_envelope_size_bytes",
        ),
    }
    timestamp = created_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    job = build_common_job(
        job_id=async_generation_job_id(generation_id),
        job_type=CX_ASYNC_GENERATION_JOB_TYPE,
        trace_id=_required_text(trace_id, "trace_id"),
        request_id=_required_text(request_id, "request_id"),
        subject_ref={"type": "oa.user", "id": access_context.subject_id},
        idempotency_key=f"cx-async-generation:{generation_id}",
        created_at=timestamp,
        max_attempts=_positive_int(max_attempts, "max_attempts"),
        retryable=True,
        links={
            "generation": f"/api/v1/generations/{generation_id}",
            "async_job": f"/api/v1/generation-jobs/{async_generation_job_id(generation_id)}",
        },
    )
    job["payload"] = payload
    return validate_async_generation_job(job)


def validate_async_generation_job(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid("Async generation job must be an object.")
    candidate = validate_common_job(deepcopy(dict(value)))
    if candidate["job_type"] != CX_ASYNC_GENERATION_JOB_TYPE:
        raise _invalid("Async generation job type is invalid.")
    payload = candidate.get("payload")
    if not isinstance(payload, Mapping):
        raise _invalid("Async generation job payload is required.")
    if payload.get("async_generation_schema_version") != (
        CX_ASYNC_GENERATION_JOB_SCHEMA_VERSION
    ):
        raise _invalid("Async generation payload schema version is invalid.")
    normalized_payload = {
        "async_generation_schema_version": CX_ASYNC_GENERATION_JOB_SCHEMA_VERSION,
        "cx_generation_id": _required_text(
            payload.get("cx_generation_id"), "cx_generation_id"
        ),
        "admission_id": _required_text(payload.get("admission_id"), "admission_id"),
        "tenant_ref_id": _required_text(
            payload.get("tenant_ref_id"), "tenant_ref_id"
        ),
        "owner_subject_ref_id": _required_text(
            payload.get("owner_subject_ref_id"), "owner_subject_ref_id"
        ),
        "request_envelope_sha256": _sha256(
            payload.get("request_envelope_sha256")
        ),
        "request_envelope_size_bytes": _positive_int(
            payload.get("request_envelope_size_bytes"),
            "request_envelope_size_bytes",
        ),
    }
    if candidate["job_id"] != async_generation_job_id(
        normalized_payload["cx_generation_id"]
    ):
        raise _invalid("Async generation job identity is invalid.")
    if candidate["subject_ref"] != {
        "type": "oa.user",
        "id": normalized_payload["owner_subject_ref_id"],
    }:
        raise _invalid("Async generation owner binding is invalid.")
    if _contains_private_payload(candidate):
        raise _invalid("Async generation job contains private request material.")
    candidate["payload"] = normalized_payload
    return candidate


def project_async_generation_job(value: Mapping[str, Any]) -> dict[str, Any]:
    job = validate_async_generation_job(value)
    payload = job["payload"]
    error = job.get("error")
    safe_error = None
    if isinstance(error, Mapping):
        safe_error = {
            "error_code": str(error.get("error_code", "cx.async_generation.failed")),
            "retryable": bool(error.get("retryable")),
            "dead_lettered": bool(error.get("dead_lettered")),
        }
    return {
        "async_generation_schema_version": CX_ASYNC_GENERATION_JOB_SCHEMA_VERSION,
        "job_id": job["job_id"],
        "cx_generation_id": payload["cx_generation_id"],
        "status": job["status"],
        "attempt_count": job["attempt_count"],
        "max_attempts": job["max_attempts"],
        "retryable": job["retryable"],
        "available_at": job.get("available_at"),
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
        "links": deepcopy(job["links"]),
        "error": safe_error,
    }


def async_generation_job_id(cx_generation_id: str) -> str:
    generation_id = _required_text(cx_generation_id, "cx_generation_id")
    return str(uuid5(NAMESPACE_URL, f"cx-async-generation-job:{generation_id}"))


def _contains_private_payload(value: object, *, parent_key: str | None = None) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in _PRIVATE_KEYS:
                return True
            if _contains_private_payload(item, parent_key=normalized):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_private_payload(item, parent_key=parent_key) for item in value)
    return False


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"{field_name} must be a non-empty string.")
    return value.strip()


def _sha256(value: object) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise _invalid("request_envelope_sha256 must be a lowercase SHA-256 value.")
    return value


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _invalid(f"{field_name} must be a positive integer.")
    return value


def _invalid(detail: str) -> AsyncGenerationContractError:
    return AsyncGenerationContractError(
        error_code="cx.async_generation.contract_invalid",
        detail=detail,
    )
