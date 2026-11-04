from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

CANONICAL_PROFILE_DESIGN_SCHEMA_VERSION = (
    "cx_answer_support_canonical_profile_design.v1"
)
CANONICAL_PROFILE_FREEZE_SCHEMA_VERSION = (
    "cx_answer_support_canonical_profile_freeze.v1"
)
CANONICAL_PROFILE_POLICY_ID = "cx_answer_support_contradiction_aware_ready_v2"
CANONICAL_PROFILE_ID = "answer-support-contradiction-aware-v2"
LINEAGE_PROFILE_ID = "answer-support-contradiction-aware-v1"
P_K_DECISION = "DISTINCT_PROFILES_FRESH_DESIGN_REQUIRED"

FEATURE_FIELDS = (
    "direct_or_support_fraction",
    "second_answer_support_score",
    "top_two_answer_support_mean",
    "inverse_maximum_contradiction_score",
    "normalized_support_contradiction_margin",
)
FEATURE_WEIGHTS = {
    "direct_or_support_fraction": 0.3,
    "inverse_maximum_contradiction_score": 0.1,
    "normalized_support_contradiction_margin": 0.15,
    "second_answer_support_score": 0.25,
    "top_two_answer_support_mean": 0.2,
}
REQUIRED_SIGNALS = (
    "DIRECT_OR_SUPPORT_COVERAGE",
    "SECOND_CANDIDATE_SUPPORT_STRENGTH",
    "TOP_TWO_SUPPORT_STRENGTH",
    "MAXIMUM_CONTRADICTION_BOUND",
    "POSITIVE_SUPPORT_CONTRADICTION_MARGIN",
)

_DESIGN_FIELDS = {
    "design_schema_version",
    "design_id",
    "policy_id",
    "status",
    "source_binding",
    "ready_semantics",
    "feature_transforms",
    "canonical_profile",
    "admission",
    "evidence_plan",
    "safety",
}


def validate_canonical_answer_support_profile_design(
    design: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate the pre-evidence, product-semantic canonical profile freeze."""
    _exact_mapping(design, _DESIGN_FIELDS, "canonical profile design")
    if (
        design.get("design_schema_version")
        != CANONICAL_PROFILE_DESIGN_SCHEMA_VERSION
        or design.get("policy_id") != CANONICAL_PROFILE_POLICY_ID
        or design.get("status") != "FROZEN_PRE_EVIDENCE"
    ):
        raise ValueError("canonical profile design identity is invalid")
    _required_text(design.get("design_id"), "design_id")

    binding = _mapping(design.get("source_binding"), "source binding")
    _exact_mapping(
        binding,
        {"p_k_audit_hash", "p_k_decision", "p_k_source_selection_hash"},
        "canonical profile source binding",
    )
    normalized_binding = {
        "p_k_audit_hash": validate_hash_ref(binding.get("p_k_audit_hash")),
        "p_k_decision": _required_text(binding.get("p_k_decision"), "p_k_decision"),
        "p_k_source_selection_hash": validate_hash_ref(
            binding.get("p_k_source_selection_hash")
        ),
    }
    if normalized_binding["p_k_decision"] != P_K_DECISION:
        raise ValueError("canonical profile P-K decision is invalid")

    semantics = _mapping(design.get("ready_semantics"), "READY semantics")
    if dict(semantics) != {
        "decision_unit": "RETRIEVAL_PACKAGE",
        "meaning": "ANSWER_SUPPORT_SUFFICIENT_AND_CONTRADICTION_BOUNDED",
        "required_signals": list(REQUIRED_SIGNALS),
        "score_semantics": (
            "WEIGHTED_BOUNDED_ORDINAL_NOT_CALIBRATED_PROBABILITY"
        ),
    }:
        raise ValueError("canonical profile READY semantics are invalid")
    transforms = _mapping(design.get("feature_transforms"), "feature transforms")
    if dict(transforms) != {
        "inverse_maximum_contradiction_score": (
            "1 - maximum_contradiction_score"
        ),
        "normalized_support_contradiction_margin": (
            "(support_contradiction_margin + 1) / 2"
        ),
    }:
        raise ValueError("canonical profile feature transforms are invalid")

    profile = _mapping(design.get("canonical_profile"), "canonical profile")
    _exact_mapping(
        profile,
        {
            "profile_id",
            "lineage_profile_id",
            "feature_fields",
            "weights",
            "missing_feature_behavior",
            "threshold",
        },
        "canonical profile",
    )
    if (
        profile.get("profile_id") != CANONICAL_PROFILE_ID
        or profile.get("lineage_profile_id") != LINEAGE_PROFILE_ID
        or profile.get("feature_fields") != list(FEATURE_FIELDS)
        or dict(_mapping(profile.get("weights"), "canonical profile weights"))
        != FEATURE_WEIGHTS
        or profile.get("missing_feature_behavior") != "FAIL_CLOSED_NOT_READY"
        or profile.get("threshold") is not None
    ):
        raise ValueError("canonical profile definition is invalid")
    admission = _mapping(design.get("admission"), "canonical admission")
    if dict(admission) != {
        "maximum_false_ready_rate": 0.1,
        "maximum_outer_threshold_spread": 0.2,
        "minimum_outer_fold_balanced_accuracy": 0.5,
        "minimum_package_auc": 0.8,
        "minimum_ready_recall": 0.8,
        "outer_fold_count": 5,
        "point_constraints_remain_authoritative": True,
    }:
        raise ValueError("canonical profile admission is invalid")
    evidence_plan = _mapping(design.get("evidence_plan"), "evidence plan")
    if dict(evidence_plan) != {
        "existing_evidence_role": "DIAGNOSTIC_ONLY_NOT_THRESHOLD_ADMISSIBLE",
        "fresh_calibration_package_count": 200,
        "fresh_calibration_scenario_count": 100,
        "profile_selection_mode": "SINGLE_CANONICAL_PROFILE_THRESHOLD_ONLY",
    }:
        raise ValueError("canonical profile evidence plan is invalid")
    safety = _mapping(design.get("safety"), "canonical profile safety")
    if dict(safety) != {
        "equivalence_family_authorized": False,
        "existing_evidence_threshold_fit_permitted": False,
        "holdout_access_permitted": False,
        "profile_search_permitted": False,
        "runtime_activation_permitted": False,
        "threshold_selection_permitted": False,
    }:
        raise ValueError("canonical profile safety is invalid")

    normalized = dict(design)
    normalized["source_binding"] = normalized_binding
    normalized["design_hash"] = semantic_sha256_hash_ref(normalized)
    return normalized


def freeze_canonical_answer_support_profile(
    design: Mapping[str, Any],
    *,
    p_k_audit: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind the semantic freeze to an intact P-K fail-closed audit."""
    normalized = validate_canonical_answer_support_profile_design(design)
    audit = dict(_mapping(p_k_audit, "P-K audit"))
    audit_hash = validate_hash_ref(audit.pop("audit_hash", None))
    if semantic_sha256_hash_ref(audit) != audit_hash:
        raise ValueError("P-K audit integrity is invalid")
    binding = normalized["source_binding"]
    next_contract = _mapping(audit.get("next_contract"), "P-K next contract")
    semantic = _mapping(audit.get("semantic_equivalence"), "P-K semantics")
    semantic_checks = _mapping(semantic.get("checks"), "P-K semantic checks")
    if (
        audit_hash != binding["p_k_audit_hash"]
        or audit.get("status") != "DIAGNOSED"
        or audit.get("decision") != binding["p_k_decision"]
        or audit.get("equivalence_family_authorized") is not False
        or audit.get("source_binding", {}).get("p_j_selection_hash")
        != binding["p_k_source_selection_hash"]
        or semantic_checks.get("feature_dependency_sets_equal") is not False
        or semantic_checks.get("counterfactual_responses_equivalent") is not False
        or next_contract.get("canonical_profile_design_required") is not True
        or next_contract.get("fresh_calibration_evidence_required") is not True
        or next_contract.get("holdout_access_permitted") is not False
        or next_contract.get("runtime_activation_permitted") is not False
    ):
        raise ValueError("P-K audit boundary is invalid")

    profile = dict(normalized["canonical_profile"])
    profile["profile_hash"] = semantic_sha256_hash_ref(
        {
            "policy_id": normalized["policy_id"],
            "ready_semantics": normalized["ready_semantics"],
            "feature_transforms": normalized["feature_transforms"],
            "profile": profile,
        }
    )
    result: dict[str, Any] = {
        "freeze_schema_version": CANONICAL_PROFILE_FREEZE_SCHEMA_VERSION,
        "status": "CANONICAL_PROFILE_FROZEN_FRESH_CALIBRATION_REQUIRED",
        "policy_id": normalized["policy_id"],
        "design_hash": normalized["design_hash"],
        "source_audit_hash": audit_hash,
        "canonical_profile": profile,
        "admission": normalized["admission"],
        "evidence_plan": normalized["evidence_plan"],
        "holdout_access_permitted": False,
        "runtime_activation_permitted": False,
    }
    result["freeze_hash"] = semantic_sha256_hash_ref(result)
    return result


def _exact_mapping(value: object, fields: set[str], name: str) -> Mapping[str, Any]:
    item = _mapping(value, name)
    if set(item) != fields:
        raise ValueError(f"{name} fields are invalid")
    return item


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} is invalid")
    return value


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is invalid")
    return value.strip()
