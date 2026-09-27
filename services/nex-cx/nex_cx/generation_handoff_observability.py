from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from nex_runtime import (
    OperationalEventEmitResult,
    OperationalEventEmitter,
    build_subject_ref,
)


GENERATION_HANDOFF_OBSERVABILITY_SCHEMA_VERSION = (
    "cx_generation_handoff_observability.v1"
)
CX_GENERATION_HANDOFF_OBSERVED_EVENT = "cx.generation_handoff.observed"
CX_GENERATION_HANDOFF_FAILED_EVENT = "cx.generation_handoff.failed"


def observe_generation_handoff(
    emitter: OperationalEventEmitter,
    handoff: Mapping[str, Any],
    *,
    trace_id: str | None,
    request_id: str | None,
) -> OperationalEventEmitResult:
    job = _mapping(handoff.get("job"))
    generation = _mapping(handoff.get("generation"))
    content = _mapping(handoff.get("content"))
    job_id = _required(job.get("job_id"), "job_id")
    generation_id = _required(job.get("cx_generation_id"), "cx_generation_id")
    handoff_status = _required(handoff.get("handoff_status"), "handoff_status")
    job_status = _required(job.get("status"), "job.status")
    return emitter.safe_emit(
        event_type=CX_GENERATION_HANDOFF_OBSERVED_EVENT,
        severity="INFO" if handoff_status == "READY" else "WARNING",
        message="CX asynchronous generation handoff was observed.",
        trace_id=trace_id,
        request_id=request_id,
        subject_ref=build_subject_ref("cx.async_generation_job", job_id),
        details={
            "observability_schema_version": (
                GENERATION_HANDOFF_OBSERVABILITY_SCHEMA_VERSION
            ),
            "handoff_status": handoff_status,
            "next_action": _optional(handoff.get("next_action")),
            "job_status": job_status,
            "generation_id": generation_id,
            "attempt_count": _safe_int(job.get("attempt_count")),
            "max_attempts": _safe_int(job.get("max_attempts")),
            "retryable": job.get("retryable") is True,
            "generation_available": bool(generation),
            "content_available": bool(content),
            "content_size_bytes": _safe_optional_int(content.get("size_bytes")),
        },
        event_id=str(
            uuid5(
                NAMESPACE_URL,
                "cx-generation-handoff:"
                f"{job_id}:{handoff_status}:{job_status}:"
                f"{_safe_int(job.get('attempt_count'))}",
            )
        ),
    )


def observe_generation_handoff_failure(
    emitter: OperationalEventEmitter,
    *,
    job_id: str,
    error_code: str,
    status_code: int,
    retryable: bool,
    trace_id: str | None,
    request_id: str | None,
) -> OperationalEventEmitResult:
    safe_job_id = _required(job_id, "job_id")
    safe_error_code = _required(error_code, "error_code")
    return emitter.safe_emit(
        event_type=CX_GENERATION_HANDOFF_FAILED_EVENT,
        severity="ERROR" if status_code >= 500 else "WARNING",
        message="CX asynchronous generation handoff failed.",
        trace_id=trace_id,
        request_id=request_id,
        subject_ref=build_subject_ref("cx.async_generation_job", safe_job_id),
        details={
            "observability_schema_version": (
                GENERATION_HANDOFF_OBSERVABILITY_SCHEMA_VERSION
            ),
            "error_code": safe_error_code,
            "status_code": status_code,
            "retryable": retryable,
        },
        event_id=str(
            uuid5(
                NAMESPACE_URL,
                "cx-generation-handoff-failure:"
                f"{safe_job_id}:{safe_error_code}:{status_code}:{retryable}",
            )
        ),
    )


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _required(value: object, field: str) -> str:
    normalized = _optional(value)
    if normalized is None:
        raise ValueError(f"{field} must be a non-empty string")
    return normalized


def _optional(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _safe_int(value: object) -> int:
    return _safe_optional_int(value) or 0


def _safe_optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
