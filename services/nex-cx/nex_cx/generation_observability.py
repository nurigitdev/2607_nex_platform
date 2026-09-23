from __future__ import annotations

"""Metadata-only operational events for grounded generation."""

from collections.abc import Mapping
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from nex_runtime import (
    OperationalEventEmitResult,
    OperationalEventEmitter,
    build_subject_ref,
)


GENERATION_OBSERVABILITY_SCHEMA_VERSION = "cx_generation_observability.v1"
CX_GENERATION_COMPLETED_EVENT = "cx.generation.completed"
CX_GENERATION_FAILED_EVENT = "cx.generation.failed"
CX_GENERATION_REPLAYED_EVENT = "cx.generation.replayed"
CX_GENERATION_READ_FAILED_EVENT = "cx.generation.read_failed"


def observe_generation_outcome(
    emitter: OperationalEventEmitter,
    record: Mapping[str, Any],
    *,
    replayed: bool = False,
) -> OperationalEventEmitResult:
    generation_id = _safe_string(record.get("cx_generation_id"), "unknown")
    status = _safe_string(record.get("status"), "UNKNOWN").upper()
    request_metadata = _mapping(record.get("request_metadata"))
    response_metadata = _mapping(record.get("response_metadata"))
    content_ref = _mapping(record.get("content_ref"))
    private_output = _mapping(record.get("private_output_metadata"))
    usage = _mapping(record.get("usage"))
    failure = _mapping(record.get("failure"))
    event_type = (
        CX_GENERATION_REPLAYED_EVENT
        if replayed
        else (
            CX_GENERATION_COMPLETED_EVENT
            if status == "COMPLETED"
            else CX_GENERATION_FAILED_EVENT
        )
    )
    return emitter.safe_emit(
        event_type=event_type,
        severity="INFO" if status == "COMPLETED" else "ERROR",
        message=(
            "CX grounded generation was replayed."
            if replayed
            else "CX grounded generation reached a terminal state."
        ),
        trace_id=_optional_string(record.get("trace_id")),
        request_id=_optional_string(record.get("request_id")),
        subject_ref=build_subject_ref("cx.generation", generation_id),
        details={
            "observability_schema_version": GENERATION_OBSERVABILITY_SCHEMA_VERSION,
            "generation_status": status,
            "replayed": replayed,
            "provider_alias": _optional_string(record.get("alias")),
            "provider_capability": _optional_string(
                record.get("provider_capability")
            ),
            "compatibility_rule_id": _optional_string(
                request_metadata.get("compatibility_rule_id")
            ),
            "grounding_required": request_metadata.get("grounding_required") is True,
            "selected_evidence_count": _safe_int(
                request_metadata.get("selected_evidence_count")
            ),
            "finish_reason": _optional_string(
                response_metadata.get("finish_reason")
            ),
            "output_sha256": _first_string(
                response_metadata.get("output_hash"),
                content_ref.get("content_sha256"),
                private_output.get("output_sha256"),
            ),
            "output_size_bytes": _first_int(
                content_ref.get("size_bytes"),
                private_output.get("output_size_bytes"),
            ),
            "input_unit_count": _first_int(
                usage.get("input_tokens"), usage.get("prompt_tokens")
            ),
            "output_unit_count": _first_int(
                usage.get("output_tokens"), usage.get("completion_tokens")
            ),
            "total_unit_count": _safe_optional_int(usage.get("total_tokens")),
            "error_code": _optional_string(failure.get("failure_code")),
            "failed_stage": _optional_string(failure.get("failed_stage")),
            "retryable": failure.get("retryable") is True,
        },
        event_id=_outcome_event_id(
            generation_id=generation_id,
            status=status,
            replayed=replayed,
        ),
    )


def observe_generation_request_failure(
    emitter: OperationalEventEmitter,
    *,
    operation: str,
    error_code: str,
    status_code: int,
    retryable: bool,
    trace_id: str | None,
    request_id: str | None,
    cx_generation_id: str | None = None,
) -> OperationalEventEmitResult:
    safe_operation = _safe_string(operation, "unknown")
    safe_error_code = _safe_string(error_code, "cx.generation_failed")
    generation_id = _optional_string(cx_generation_id)
    return emitter.safe_emit(
        event_type=(
            CX_GENERATION_READ_FAILED_EVENT
            if safe_operation in {"metadata_read", "content_read"}
            else CX_GENERATION_FAILED_EVENT
        ),
        severity="ERROR" if status_code >= 500 else "WARNING",
        message="CX grounded generation request failed.",
        trace_id=trace_id,
        request_id=request_id,
        subject_ref=(
            build_subject_ref("cx.generation", generation_id)
            if generation_id is not None
            else None
        ),
        details={
            "observability_schema_version": GENERATION_OBSERVABILITY_SCHEMA_VERSION,
            "operation": safe_operation,
            "error_code": safe_error_code,
            "status_code": status_code,
            "retryable": retryable,
        },
        event_id=_failure_event_id(
            operation=safe_operation,
            error_code=safe_error_code,
            cx_generation_id=generation_id,
            trace_id=trace_id,
            request_id=request_id,
        ),
    )


def _outcome_event_id(*, generation_id: str, status: str, replayed: bool) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            f"cx-generation-outcome:{generation_id}:{status}:{replayed}",
        )
    )


def _failure_event_id(
    *,
    operation: str,
    error_code: str,
    cx_generation_id: str | None,
    trace_id: str | None,
    request_id: str | None,
) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            "cx-generation-failure:"
            f"{operation}:{cx_generation_id or 'none'}:"
            f"{trace_id or 'none'}:{request_id or 'none'}:{error_code}",
        )
    )


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _safe_int(value: object) -> int:
    return _safe_optional_int(value) or 0


def _safe_optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _first_int(*values: object) -> int | None:
    return next(
        (
            normalized
            for value in values
            if (normalized := _safe_optional_int(value)) is not None
        ),
        None,
    )


def _safe_string(value: object, fallback: str) -> str:
    return _optional_string(value) or fallback


def _optional_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _first_string(*values: object) -> str | None:
    return next(
        (
            normalized
            for value in values
            if (normalized := _optional_string(value)) is not None
        ),
        None,
    )
