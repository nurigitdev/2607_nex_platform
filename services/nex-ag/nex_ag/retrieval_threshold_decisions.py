from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any


AG_RETRIEVAL_THRESHOLD_DECISION_PROJECTION_SCHEMA_VERSION = (
    "ag_retrieval_threshold_decision_projection.v1"
)
RETRIEVAL_THRESHOLD_SAMPLE_READINESS = (
    "SOURCE_DEGRADED",
    "NO_DECISION_CHECKPOINT",
    "INSUFFICIENT_SAMPLES",
    "NEEDS_OPERATOR_REVIEW",
    "READY_FOR_REVIEW",
)


def project_retrieval_threshold_decision(
    policy: Mapping[str, Any],
    *,
    sample_summary: Mapping[str, Any],
    source_degraded: bool,
    service_id: str,
) -> dict[str, Any]:
    decision = _mapping_value(policy.get("threshold_decision"))
    minimum_samples = _integer_or_none(
        decision.get("minimum_live_samples_before_change")
    )
    if minimum_samples is None:
        minimum_samples = 0
    sample_readiness, recommended_action = threshold_decision_readiness(
        decision=decision,
        sample_summary=sample_summary,
        minimum_samples=minimum_samples,
        source_degraded=source_degraded,
    )
    return {
        "service_id": service_id,
        "operation_type": "retrieval_threshold_decision",
        "policy_id": policy["policy_id"],
        "policy_version": policy.get("version"),
        "policy_status": policy.get("status"),
        "decision_id": decision.get("decision_id"),
        "decision_status": str(decision.get("decision_status") or "UNSPECIFIED"),
        "canonical_low_confidence_threshold": _number_or_none(
            decision.get("canonical_low_confidence_threshold")
        ),
        "candidate_low_confidence_threshold": _number_or_none(
            decision.get("candidate_low_confidence_threshold")
        ),
        "live_smoke_override_threshold": _number_or_none(
            decision.get("live_smoke_override_threshold")
        ),
        "minimum_live_samples_before_change": minimum_samples,
        "observed_sample_count": _safe_int_count(
            sample_summary.get("total_samples")
        ),
        "observed_threshold_override_count": _safe_int_count(
            sample_summary.get("threshold_override_count")
        ),
        "observed_default_pass_count": _safe_int_count(
            sample_summary.get("would_pass_default_threshold")
        ),
        "observed_default_confidence_buckets": deepcopy(
            _mapping_value(sample_summary.get("by_default_confidence_bucket"))
        ),
        "observed_calibration_actions": deepcopy(
            _mapping_value(sample_summary.get("by_calibration_action"))
        ),
        "observed_score_margin_to_default_threshold": deepcopy(
            sample_summary.get("score_margin_to_default_threshold")
        ),
        "sample_readiness": sample_readiness,
        "recommended_operator_action": recommended_action,
        "review_owner_service": decision.get("review_owner_service"),
        "policy_hash": policy.get("policy_hash"),
        "evidence_sources": deepcopy(_list_value(decision.get("evidence_sources"))),
        "decision_note": decision.get("decision_note"),
    }


def summarize_retrieval_threshold_decisions(
    decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    by_readiness: dict[str, int] = {}
    by_decision_status: dict[str, int] = {}
    for decision in decisions:
        readiness = str(decision["sample_readiness"])
        status = str(decision["decision_status"])
        by_readiness[readiness] = by_readiness.get(readiness, 0) + 1
        by_decision_status[status] = by_decision_status.get(status, 0) + 1
    return {
        "total_decisions": len(decisions),
        "by_sample_readiness": by_readiness,
        "by_decision_status": by_decision_status,
        "observed_sample_count": sum(
            _safe_int_count(decision["observed_sample_count"])
            for decision in decisions
        ),
        "threshold_override_count": sum(
            _safe_int_count(decision["observed_threshold_override_count"])
            for decision in decisions
        ),
        "ready_for_review": by_readiness.get("READY_FOR_REVIEW", 0),
        "needs_operator_review": by_readiness.get("NEEDS_OPERATOR_REVIEW", 0),
        "insufficient_samples": by_readiness.get("INSUFFICIENT_SAMPLES", 0),
        "source_degraded": by_readiness.get("SOURCE_DEGRADED", 0),
    }


def threshold_decision_readiness(
    *,
    decision: Mapping[str, Any],
    sample_summary: Mapping[str, Any],
    minimum_samples: int,
    source_degraded: bool,
) -> tuple[str, str]:
    if source_degraded:
        return "SOURCE_DEGRADED", "repair_retrieval_operations_source"
    if not decision:
        return "NO_DECISION_CHECKPOINT", "register_threshold_decision"
    observed_samples = _safe_int_count(sample_summary.get("total_samples"))
    if observed_samples < minimum_samples:
        return "INSUFFICIENT_SAMPLES", "collect_live_score_samples"
    override_count = _safe_int_count(sample_summary.get("threshold_override_count"))
    if override_count > 0:
        return "NEEDS_OPERATOR_REVIEW", "review_threshold_override_samples"
    bucket_counts = _mapping_value(sample_summary.get("by_default_confidence_bucket"))
    if (
        _safe_int_count(bucket_counts.get("LOW_CONFIDENCE")) > 0
        or _safe_int_count(bucket_counts.get("NO_ANSWER")) > 0
    ):
        return "NEEDS_OPERATOR_REVIEW", "review_low_confidence_samples"
    return "READY_FOR_REVIEW", "prepare_threshold_policy_review"


def _safe_int_count(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(value, 0)
    return 0


def _number_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _integer_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _mapping_value(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_value(value: Any) -> list[Any]:
    return deepcopy(value) if isinstance(value, list) else []
