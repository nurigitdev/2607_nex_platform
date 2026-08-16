from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any
from urllib.parse import quote, urlencode


AG_RETRIEVAL_THRESHOLD_DECISION_PROJECTION_SCHEMA_VERSION = (
    "ag_retrieval_threshold_decision_projection.v1"
)
AG_RETRIEVAL_THRESHOLD_OPERATOR_REVIEW_SCHEMA_VERSION = (
    "ag_retrieval_threshold_operator_review.v1"
)
AG_RETRIEVAL_THRESHOLD_CALIBRATION_CLOSURE_SCHEMA_VERSION = (
    "ag_retrieval_threshold_calibration_closure.v1"
)
RETRIEVAL_THRESHOLD_SAMPLE_READINESS = (
    "SOURCE_DEGRADED",
    "NO_DECISION_CHECKPOINT",
    "INSUFFICIENT_SAMPLES",
    "NEEDS_OPERATOR_REVIEW",
    "READY_FOR_REVIEW",
)
RETRIEVAL_THRESHOLD_CALIBRATION_CLOSURE_STATUSES = (
    "NO_DECISIONS",
    "BLOCKED",
    "COLLECTING_SAMPLES",
    "OPERATOR_REVIEW_REQUIRED",
    "READY_FOR_POLICY_REVIEW",
)
RETRIEVAL_THRESHOLD_OPERATOR_REVIEW_RUNBOOKS: Mapping[str, Mapping[str, Any]] = {
    "repair_retrieval_operations_source": {
        "review_status": "BLOCKED_SOURCE",
        "runbook_id": "retrieval_threshold.repair_operations_source.v1",
        "action_label": "Repair retrieval operations source",
        "severity": "ERROR",
        "blocking_reason": "retrieval_operations_source_degraded",
        "requires_live_provider_access": False,
        "requires_policy_registry_update": False,
        "evidence_requirements": [
            "restore_retrieval_package_source_status",
            "rerun_threshold_decision_projection",
        ],
    },
    "register_threshold_decision": {
        "review_status": "MISSING_CHECKPOINT",
        "runbook_id": "retrieval_threshold.register_decision_checkpoint.v1",
        "action_label": "Register threshold decision checkpoint",
        "severity": "WARNING",
        "blocking_reason": "threshold_decision_checkpoint_missing",
        "requires_live_provider_access": False,
        "requires_policy_registry_update": True,
        "evidence_requirements": [
            "add_threshold_decision_metadata_to_policy",
            "validate_retrieval_policy_registry",
        ],
    },
    "collect_live_score_samples": {
        "review_status": "COLLECTING_SAMPLES",
        "runbook_id": "retrieval_threshold.collect_live_score_samples.v1",
        "action_label": "Collect live score samples",
        "severity": "INFO",
        "blocking_reason": "insufficient_live_score_samples",
        "requires_live_provider_access": True,
        "requires_policy_registry_update": False,
        "evidence_requirements": [
            "collect_minimum_live_rag_score_samples",
            "review_score_margin_distribution",
        ],
    },
    "review_threshold_override_samples": {
        "review_status": "REVIEW_REQUIRED",
        "runbook_id": "retrieval_threshold.review_override_samples.v1",
        "action_label": "Review threshold override samples",
        "severity": "WARNING",
        "blocking_reason": "threshold_override_samples_present",
        "requires_live_provider_access": True,
        "requires_policy_registry_update": False,
        "evidence_requirements": [
            "inspect_override_sample_queries",
            "compare_observed_and_default_threshold_outcomes",
        ],
    },
    "review_low_confidence_samples": {
        "review_status": "REVIEW_REQUIRED",
        "runbook_id": "retrieval_threshold.review_low_confidence_samples.v1",
        "action_label": "Review low confidence samples",
        "severity": "WARNING",
        "blocking_reason": "low_confidence_or_no_answer_samples_present",
        "requires_live_provider_access": True,
        "requires_policy_registry_update": False,
        "evidence_requirements": [
            "inspect_low_confidence_sample_queries",
            "compare_reranker_and_generation_outcomes",
        ],
    },
    "prepare_threshold_policy_review": {
        "review_status": "READY_FOR_POLICY_REVIEW",
        "runbook_id": "retrieval_threshold.prepare_policy_review.v1",
        "action_label": "Prepare threshold policy review",
        "severity": "INFO",
        "blocking_reason": None,
        "requires_live_provider_access": False,
        "requires_policy_registry_update": False,
        "evidence_requirements": [
            "export_calibration_rollup",
            "prepare_policy_review_note",
        ],
    },
}
UNKNOWN_OPERATOR_REVIEW_RUNBOOK: Mapping[str, Any] = {
    "review_status": "UNKNOWN_ACTION",
    "runbook_id": "retrieval_threshold.unknown_operator_action.v1",
    "action_label": "Review unknown operator action",
    "severity": "WARNING",
    "blocking_reason": "unknown_operator_action",
    "requires_live_provider_access": False,
    "requires_policy_registry_update": False,
    "evidence_requirements": ["inspect_threshold_decision_projection"],
}


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
    observed_sample_count = _safe_int_count(sample_summary.get("total_samples"))
    observed_threshold_override_count = _safe_int_count(
        sample_summary.get("threshold_override_count")
    )
    observed_default_pass_count = _safe_int_count(
        sample_summary.get("would_pass_default_threshold")
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
        "observed_sample_count": observed_sample_count,
        "observed_threshold_override_count": observed_threshold_override_count,
        "observed_default_pass_count": observed_default_pass_count,
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
        "operator_review": build_retrieval_threshold_operator_review(
            service_id=service_id,
            policy_id=str(policy["policy_id"]),
            sample_readiness=sample_readiness,
            recommended_operator_action=recommended_action,
            observed_sample_count=observed_sample_count,
            minimum_live_samples_before_change=minimum_samples,
        ),
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


def summarize_retrieval_threshold_calibration_closure(
    decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    readiness_counts: dict[str, int] = {}
    ready_policy_ids: list[str] = []
    blocked_policy_ids: list[str] = []
    recommended_next_actions: set[str] = set()
    for decision in decisions:
        readiness = str(decision.get("sample_readiness", "UNKNOWN"))
        readiness_counts[readiness] = readiness_counts.get(readiness, 0) + 1
        policy_id = str(decision.get("policy_id") or "UNKNOWN")
        if readiness == "READY_FOR_REVIEW":
            ready_policy_ids.append(policy_id)
        else:
            blocked_policy_ids.append(policy_id)
        action = decision.get("recommended_operator_action")
        if action:
            recommended_next_actions.add(str(action))

    closure_status = _calibration_closure_status(readiness_counts, len(decisions))
    blocking_readiness = [
        readiness
        for readiness in RETRIEVAL_THRESHOLD_SAMPLE_READINESS
        if readiness != "READY_FOR_REVIEW" and readiness_counts.get(readiness, 0) > 0
    ]
    return {
        "closure_schema_version": (
            AG_RETRIEVAL_THRESHOLD_CALIBRATION_CLOSURE_SCHEMA_VERSION
        ),
        "closure_status": closure_status,
        "total_decisions": len(decisions),
        "closed_decision_count": readiness_counts.get("READY_FOR_REVIEW", 0),
        "open_decision_count": len(decisions)
        - readiness_counts.get("READY_FOR_REVIEW", 0),
        "readiness_counts": readiness_counts,
        "blocking_readiness": blocking_readiness,
        "ready_policy_ids": sorted(ready_policy_ids),
        "blocked_policy_ids": sorted(blocked_policy_ids),
        "recommended_next_actions": sorted(recommended_next_actions),
        "minimum_live_samples_satisfied": (
            len(decisions) > 0
            and readiness_counts.get("SOURCE_DEGRADED", 0) == 0
            and readiness_counts.get("NO_DECISION_CHECKPOINT", 0) == 0
            and readiness_counts.get("INSUFFICIENT_SAMPLES", 0) == 0
        ),
        "policy_review_ready": closure_status == "READY_FOR_POLICY_REVIEW",
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


def _calibration_closure_status(
    readiness_counts: Mapping[str, int],
    total_decisions: int,
) -> str:
    if total_decisions == 0:
        return "NO_DECISIONS"
    if (
        readiness_counts.get("SOURCE_DEGRADED", 0) > 0
        or readiness_counts.get("NO_DECISION_CHECKPOINT", 0) > 0
    ):
        return "BLOCKED"
    if readiness_counts.get("INSUFFICIENT_SAMPLES", 0) > 0:
        return "COLLECTING_SAMPLES"
    if readiness_counts.get("NEEDS_OPERATOR_REVIEW", 0) > 0:
        return "OPERATOR_REVIEW_REQUIRED"
    return "READY_FOR_POLICY_REVIEW"


def build_retrieval_threshold_operator_review(
    *,
    service_id: str,
    policy_id: str,
    sample_readiness: str,
    recommended_operator_action: str,
    observed_sample_count: int,
    minimum_live_samples_before_change: int,
) -> dict[str, Any]:
    known_action = (
        recommended_operator_action in RETRIEVAL_THRESHOLD_OPERATOR_REVIEW_RUNBOOKS
    )
    runbook = (
        RETRIEVAL_THRESHOLD_OPERATOR_REVIEW_RUNBOOKS[recommended_operator_action]
        if known_action
        else UNKNOWN_OPERATOR_REVIEW_RUNBOOK
    )
    operator_action = (
        recommended_operator_action if known_action else "unknown_operator_action"
    )
    remaining_sample_count = max(
        minimum_live_samples_before_change - observed_sample_count,
        0,
    )
    query = urlencode({"service_id": service_id, "retrieval_policy_id": policy_id})
    return {
        "review_schema_version": (
            AG_RETRIEVAL_THRESHOLD_OPERATOR_REVIEW_SCHEMA_VERSION
        ),
        "review_status": runbook["review_status"],
        "runbook_id": runbook["runbook_id"],
        "operator_action": operator_action,
        "action_label": runbook["action_label"],
        "severity": runbook["severity"],
        "sample_readiness": sample_readiness,
        "remaining_sample_count": remaining_sample_count,
        "requires_live_provider_access": runbook["requires_live_provider_access"],
        "requires_policy_registry_update": runbook[
            "requires_policy_registry_update"
        ],
        "blocking_reason": runbook["blocking_reason"],
        "threshold_decision_path": (
            f"/admin/v1/operations/retrieval-threshold-decisions?{query}"
        ),
        "calibration_samples_path": (
            f"/admin/v1/operations/retrieval-score-calibration?{query}"
        ),
        "policy_detail_path": (
            f"/admin/v1/policies/retrieval/{quote(policy_id, safe='')}"
        ),
        "evidence_requirements": deepcopy(runbook["evidence_requirements"]),
    }


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
