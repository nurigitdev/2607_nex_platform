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
RETRIEVAL_OBSERVABILITY_SCHEMA_VERSION = "cx_retrieval_observability.v2"


def observe_retrieval_package(
    emitter: OperationalEventEmitter,
    package: Mapping[str, Any],
) -> OperationalEventEmitResult:
    package_id = _safe_string(package.get("retrieval_package_id"), "unknown")
    status = _safe_string(package.get("status"), "UNKNOWN").upper()
    profile = _mapping(package.get("retrieval_profile"))
    quality_policy = _mapping(profile.get("quality_policy"))
    candidate_summary = _mapping(profile.get("candidate_summary"))
    embedding_profile = _mapping(profile.get("embedding_profile"))
    reranker_profile = _mapping(profile.get("reranker_profile"))
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
            "confidence_policy_id": _optional_string(
                score_summary.get("confidence_policy_id")
            ),
            "confidence_bucket": _optional_string(
                score_summary.get("confidence_bucket")
            ),
            "confidence_decision_reason": _optional_string(
                score_summary.get("decision_reason")
            ),
            "confidence_feature_schema_version": _optional_string(
                score_summary.get("confidence_feature_schema_version")
            ),
            "calibration_profile_id": _optional_string(
                score_summary.get("calibration_profile_id")
            ),
            "calibration_profile_hash": _optional_string(
                score_summary.get("calibration_profile_hash")
            ),
            "best_score": _safe_number(score_summary.get("best_score")),
            "low_confidence_threshold": _safe_number(
                score_summary.get("low_confidence_threshold")
            ),
            "evidence_count": _safe_count(evidence_items),
            "document_count": _safe_int(source_summary.get("document_count")),
            "candidate_count": _safe_int(source_summary.get("chunk_count")),
            "bm25_candidate_count": _safe_int(
                candidate_summary.get("bm25_candidate_count")
            ),
            "vector_candidate_count": _safe_int(
                candidate_summary.get("vector_candidate_count")
            ),
            "fused_candidate_count": _safe_int(
                candidate_summary.get("fused_candidate_count")
            ),
            "embedding_provider_alias": _optional_string(
                embedding_profile.get("provider_alias")
            ),
            "embedding_model_revision": _optional_string(
                embedding_profile.get("model_revision")
            ),
            "embedding_deployment_id": _optional_string(
                embedding_profile.get("deployment_id")
            ),
            "reranker_provider_alias": _optional_string(
                reranker_profile.get("provider_alias")
            ),
            "reranker_model_revision": _optional_string(
                reranker_profile.get("model_revision")
            ),
            "reranker_deployment_id": _optional_string(
                reranker_profile.get("deployment_id")
            ),
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
            "provider_role": _failure_provider_role(safe_error_code),
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


def _safe_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _failure_provider_role(error_code: str) -> str | None:
    if "EMBEDDING" in error_code:
        return "embedding"
    if "RERANK" in error_code:
        return "reranker"
    if "VECTOR" in error_code:
        return "vector_search"
    if "TOKENIZER" in error_code:
        return "lexical_search"
    if "EVIDENCE" in error_code or "PRIVATE_CHUNK" in error_code:
        return "private_evidence"
    if "CANDIDATE" in error_code:
        return "candidate_pipeline"
    if "PERSISTENCE" in error_code:
        return "persistence"
    return None


def _safe_string(value: object, fallback: str) -> str:
    normalized = _optional_string(value)
    return normalized or fallback


def _optional_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None
