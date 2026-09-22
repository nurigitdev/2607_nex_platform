from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from nex_runtime import (
    OperationalEventEmitResult,
    OperationalEventEmitter,
    build_subject_ref,
)


CX_RETRIEVAL_PACKAGE_OBSERVED_EVENT = "cx.retrieval.package_observed"
CX_RETRIEVAL_PACKAGE_FAILED_EVENT = "cx.retrieval.package_failed"
RETRIEVAL_OBSERVABILITY_SCHEMA_VERSION = "cx_retrieval_observability.v1"


def observe_retrieval_package(
    emitter: OperationalEventEmitter,
    package: Mapping[str, Any],
) -> OperationalEventEmitResult:
    package_id = _safe_string(package.get("retrieval_package_id"), "unknown")
    status = _safe_string(package.get("status"), "UNKNOWN").upper()
    profile = _mapping(package.get("retrieval_profile"))
    quality_policy = _mapping(profile.get("quality_policy"))
    score_summary = _mapping(package.get("score_summary"))
    source_summary = _mapping(package.get("source_summary"))
    permission_snapshot = _mapping(package.get("permission_snapshot"))
    evidence_items = package.get("evidence_items")
    warnings = package.get("warnings")
    return emitter.safe_emit(
        event_type=CX_RETRIEVAL_PACKAGE_OBSERVED_EVENT,
        severity="INFO" if status == "READY" else "WARNING",
        message="CX permission-filtered retrieval package was observed.",
        trace_id=_optional_string(package.get("trace_id")),
        request_id=_optional_string(package.get("request_id")),
        subject_ref=build_subject_ref("cx.retrieval_package", package_id),
        details={
            "observability_schema_version": RETRIEVAL_OBSERVABILITY_SCHEMA_VERSION,
            "retrieval_status": status,
            "runtime_schema_version": _optional_string(
                package.get("retrieval_runtime_schema_version")
            ),
            "policy_id": _optional_string(quality_policy.get("policy_id")),
            "permission_policy_version": _optional_string(
                permission_snapshot.get("policy_version")
            ),
            "rerank_state": _optional_string(score_summary.get("rerank_state")),
            "evidence_count": _safe_count(evidence_items),
            "document_count": _safe_int(source_summary.get("document_count")),
            "candidate_count": _safe_int(source_summary.get("chunk_count")),
            "warning_count": _safe_count(warnings),
            "no_answer_reason": _optional_string(package.get("no_answer_reason")),
        },
        event_id=_outcome_event_id(package_id=package_id, status=status),
    )


def observe_retrieval_failure(
    emitter: OperationalEventEmitter,
    *,
    error_code: str,
    status_code: int,
    retryable: bool,
    stage: str,
    runtime_mode: str,
    trace_id: str | None,
    request_id: str | None,
) -> OperationalEventEmitResult:
    safe_error_code = _safe_string(error_code, "CX_RETRIEVAL_FAILED")
    safe_stage = _safe_string(stage, "unknown")
    safe_runtime_mode = _safe_string(runtime_mode, "unknown")
    return emitter.safe_emit(
        event_type=CX_RETRIEVAL_PACKAGE_FAILED_EVENT,
        severity="ERROR" if status_code >= 500 else "WARNING",
        message="CX permission-filtered retrieval package failed.",
        trace_id=trace_id,
        request_id=request_id,
        details={
            "observability_schema_version": RETRIEVAL_OBSERVABILITY_SCHEMA_VERSION,
            "error_code": safe_error_code,
            "status_code": status_code,
            "retryable": retryable,
            "failure_stage": safe_stage,
            "runtime_mode": safe_runtime_mode,
        },
        event_id=_failure_event_id(
            error_code=safe_error_code,
            stage=safe_stage,
            runtime_mode=safe_runtime_mode,
            trace_id=trace_id,
            request_id=request_id,
        ),
    )


def _outcome_event_id(*, package_id: str, status: str) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            f"cx-retrieval-package-observed:{package_id}:{status}",
        )
    )


def _failure_event_id(
    *,
    error_code: str,
    stage: str,
    runtime_mode: str,
    trace_id: str | None,
    request_id: str | None,
) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            "cx-retrieval-package-failed:"
            f"{trace_id or 'none'}:{request_id or 'none'}:"
            f"{error_code}:{stage}:{runtime_mode}",
        )
    )


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _safe_count(value: object) -> int:
    return len(value) if isinstance(value, list) else 0


def _safe_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _safe_string(value: object, fallback: str) -> str:
    normalized = _optional_string(value)
    return normalized or fallback


def _optional_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None
