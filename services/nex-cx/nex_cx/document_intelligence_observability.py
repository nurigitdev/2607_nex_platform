from __future__ import annotations

"""Metadata-only operational events for document intelligence."""

from collections.abc import Mapping
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from nex_runtime import (
    OperationalEventEmitResult,
    OperationalEventEmitter,
    build_subject_ref,
)


DOCUMENT_INTELLIGENCE_OBSERVABILITY_SCHEMA_VERSION = (
    "cx_document_intelligence_observability.v1"
)
CX_DOCUMENT_INTELLIGENCE_READY_EVENT = "cx.document_intelligence.ready"
CX_DOCUMENT_INTELLIGENCE_SIMILARITY_EVENT = (
    "cx.document_intelligence.similarity_observed"
)
CX_DOCUMENT_INTELLIGENCE_FAILED_EVENT = "cx.document_intelligence.failed"


def observe_document_intelligence_ready(
    emitter: OperationalEventEmitter,
    *,
    document_id: str,
    result: Mapping[str, Any],
    trace_id: str | None,
    request_id: str | None,
) -> OperationalEventEmitResult:
    summary = _mapping(result.get("summary"))
    embedding = _mapping(result.get("summary_embedding"))
    vector = _mapping(result.get("summary_vector"))
    freshness = _mapping(vector.get("freshness"))
    summary_id = _optional_string(summary.get("document_summary_id"))
    return emitter.safe_emit(
        event_type=CX_DOCUMENT_INTELLIGENCE_READY_EVENT,
        severity="INFO",
        message="CX document intelligence became ready.",
        trace_id=trace_id,
        request_id=request_id,
        subject_ref=build_subject_ref("cx.document", document_id),
        details={
            "observability_schema_version": (
                DOCUMENT_INTELLIGENCE_OBSERVABILITY_SCHEMA_VERSION
            ),
            "status": _safe_string(result.get("status"), "UNKNOWN"),
            "document_summary_id": summary_id,
            "summary_text_sha256": _optional_string(
                summary.get("summary_text_sha256")
            ),
            "summary_char_count": _safe_int(summary.get("summary_char_count")),
            "provider_alias": _optional_string(embedding.get("provider_alias")),
            "model_revision": _optional_string(embedding.get("model_revision")),
            "embedding_sha256": _optional_string(
                embedding.get("embedding_sha256")
            ),
            "vector_dimension": _safe_int(embedding.get("vector_dimension")),
            "profile_fingerprint": _optional_string(
                vector.get("profile_fingerprint")
            ),
            "freshness_state": _optional_string(freshness.get("state")),
            "freshness_usable": freshness.get("usable") is True,
        },
        event_id=_event_id(
            operation="run",
            document_id=document_id,
            discriminator=summary_id or "unknown",
        ),
    )


def observe_document_intelligence_similarity(
    emitter: OperationalEventEmitter,
    *,
    document_id: str,
    result: Mapping[str, Any],
    trace_id: str | None,
    request_id: str | None,
) -> OperationalEventEmitResult:
    source = _mapping(result.get("source_document"))
    similarity = _mapping(result.get("result"))
    freshness = _mapping(result.get("freshness"))
    summary_id = _optional_string(source.get("document_summary_id"))
    return emitter.safe_emit(
        event_type=CX_DOCUMENT_INTELLIGENCE_SIMILARITY_EVENT,
        severity="INFO",
        message="CX owner-scoped document-summary similarity was observed.",
        trace_id=trace_id,
        request_id=request_id,
        subject_ref=build_subject_ref("cx.document", document_id),
        details={
            "observability_schema_version": (
                DOCUMENT_INTELLIGENCE_OBSERVABILITY_SCHEMA_VERSION
            ),
            "document_summary_id": summary_id,
            "summary_embedding_id": _optional_string(
                source.get("summary_embedding_id")
            ),
            "profile_fingerprint": _optional_string(
                source.get("profile_fingerprint")
            ),
            "candidate_source": _optional_string(
                similarity.get("candidate_source")
            ),
            "candidate_count": _safe_int(similarity.get("candidate_count")),
            "minimum_score": _safe_number(similarity.get("minimum_score")),
            "freshness_state": _optional_string(freshness.get("state")),
            "freshness_usable": freshness.get("usable") is True,
        },
        event_id=_event_id(
            operation="similarity",
            document_id=document_id,
            discriminator=summary_id or "unknown",
        ),
    )


def observe_document_intelligence_failure(
    emitter: OperationalEventEmitter,
    *,
    document_id: str,
    operation: str,
    error_code: str,
    status_code: int,
    retryable: bool,
    trace_id: str | None,
    request_id: str | None,
) -> OperationalEventEmitResult:
    safe_operation = _safe_string(operation, "unknown")
    safe_error_code = _safe_string(
        error_code,
        "CX_DOCUMENT_INTELLIGENCE_FAILED",
    )
    return emitter.safe_emit(
        event_type=CX_DOCUMENT_INTELLIGENCE_FAILED_EVENT,
        severity="ERROR" if status_code >= 500 else "WARNING",
        message="CX document intelligence request failed.",
        trace_id=trace_id,
        request_id=request_id,
        subject_ref=build_subject_ref("cx.document", document_id),
        details={
            "observability_schema_version": (
                DOCUMENT_INTELLIGENCE_OBSERVABILITY_SCHEMA_VERSION
            ),
            "operation": safe_operation,
            "error_code": safe_error_code,
            "status_code": status_code,
            "retryable": retryable,
        },
        event_id=_event_id(
            operation=safe_operation,
            document_id=document_id,
            discriminator=(
                f"{trace_id or 'none'}:{request_id or 'none'}:{safe_error_code}"
            ),
        ),
    )


def _event_id(*, operation: str, document_id: str, discriminator: str) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            f"cx-document-intelligence:{operation}:{document_id}:{discriminator}",
        )
    )


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _safe_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _safe_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _safe_string(value: object, fallback: str) -> str:
    return _optional_string(value) or fallback


def _optional_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None
