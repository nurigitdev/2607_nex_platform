from __future__ import annotations

"""Metadata-only operational events for asynchronous grounded generation."""

from collections.abc import Mapping
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from nex_runtime import (
    OperationalEventEmitResult,
    OperationalEventEmitter,
    build_subject_ref,
)


ASYNC_GENERATION_OBSERVABILITY_SCHEMA_VERSION = (
    "cx_async_generation_observability.v1"
)
CX_ASYNC_GENERATION_ADMITTED_EVENT = "cx.async_generation.admitted"
CX_ASYNC_GENERATION_CANCELLED_EVENT = "cx.async_generation.cancelled"

_ADMISSION_ACTIONS = frozenset({"ENQUEUED", "JOINED", "REPLAYED"})
_SUPPORTED_ACTIONS = _ADMISSION_ACTIONS | {"CANCELLED"}


def observe_async_generation_job(
    emitter: OperationalEventEmitter,
    job: Mapping[str, Any],
    *,
    action: str,
    trace_id: str | None,
    request_id: str | None,
) -> OperationalEventEmitResult:
    normalized_action = str(action).strip().upper()
    if normalized_action not in _SUPPORTED_ACTIONS:
        raise ValueError("unsupported async generation observability action")
    job_id = _required_text(job.get("job_id"), "job_id")
    generation_id = _required_text(
        job.get("cx_generation_id"), "cx_generation_id"
    )
    status = _required_text(job.get("status"), "status").upper()
    error = job.get("error") if isinstance(job.get("error"), Mapping) else {}
    return emitter.safe_emit(
        event_type=(
            CX_ASYNC_GENERATION_ADMITTED_EVENT
            if normalized_action in _ADMISSION_ACTIONS
            else CX_ASYNC_GENERATION_CANCELLED_EVENT
        ),
        severity="WARNING" if normalized_action == "CANCELLED" else "INFO",
        message=(
            "CX asynchronous generation was cancelled."
            if normalized_action == "CANCELLED"
            else "CX asynchronous generation was admitted."
        ),
        trace_id=trace_id,
        request_id=request_id,
        subject_ref=build_subject_ref("cx.async_generation_job", job_id),
        details={
            "observability_schema_version": (
                ASYNC_GENERATION_OBSERVABILITY_SCHEMA_VERSION
            ),
            "action": normalized_action,
            "generation_id": generation_id,
            "job_status": status,
            "attempt_count": _safe_int(job.get("attempt_count")),
            "max_attempts": _safe_int(job.get("max_attempts")),
            "retryable": job.get("retryable") is True,
            "error_code": _optional_text(error.get("error_code")),
            "dead_lettered": error.get("dead_lettered") is True,
        },
        event_id=str(
            uuid5(
                NAMESPACE_URL,
                f"cx-async-generation:{job_id}:{normalized_action}:"
                f"{status}:{_safe_int(job.get('attempt_count'))}",
            )
        ),
    )


def _required_text(value: object, field_name: str) -> str:
    normalized = _optional_text(value)
    if normalized is None:
        raise ValueError(f"{field_name} must be a non-empty string")
    return normalized


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _safe_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0
