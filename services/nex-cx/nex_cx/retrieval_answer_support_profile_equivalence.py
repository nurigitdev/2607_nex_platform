from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from nex_runtime.model_calibration import (
    BinaryCalibrationConstraints,
    evaluate_binary_score_calibration,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

from nex_cx.retrieval_answer_support_nested_selection import (
    ANSWER_SUPPORT_NESTED_SELECTION_SCHEMA_VERSION,
    AVAILABLE_FEATURE_FIELDS,
    _find_profile,
    _normalize_samples,
    _profile_scores,
    _validated_outer_folds,
    validate_answer_support_nested_design,
)

PROFILE_EQUIVALENCE_AUDIT_DESIGN_SCHEMA_VERSION = (
    "cx_answer_support_profile_equivalence_audit_design.v1"
)
PROFILE_EQUIVALENCE_AUDIT_SCHEMA_VERSION = (
    "cx_answer_support_profile_equivalence_audit.v1"
)
PROFILE_EQUIVALENCE_AUDIT_POLICY_ID = (
    "cx_answer_support_exact_profile_stability_equivalence_audit_v1"
)

_DESIGN_FIELDS = {
    "audit_schema_version",
    "audit_id",
    "status",
    "source_binding",
    "compared_profiles",
    "empirical_equivalence",
    "semantic_equivalence",
    "counterfactual_pairs",
    "safety",
}


def audit_answer_support_profile_equivalence(
    samples: Sequence[Mapping[str, Any]],
    *,
    nested_design: Mapping[str, Any],
    fold_plan: Mapping[str, Any],
    p_j_selection: Mapping[str, Any],
    audit_design: Mapping[str, Any],
) -> dict[str, Any]:
    """Separate empirical closeness from semantic profile equivalence."""
    normalized_samples = _normalize_samples(samples)
    normalized_nested = validate_answer_support_nested_design(nested_design)
    normalized_audit = validate_profile_equivalence_audit_design(audit_design)
    normalized_selection = _validate_p_j_selection(
        p_j_selection,
        expected_selection_hash=normalized_audit["source_binding"][
            "p_j_selection_hash"
        ],
        expected_collection_hash=normalized_audit["source_binding"][
            "collection_hash"
        ],
        expected_design_hash=normalized_nested["design_hash"],
        compared_profiles=set(normalized_audit["compared_profiles"]),
    )
    scenario_ids = {str(row["scenario_id"]) for row in normalized_samples}
    folds = _validated_outer_folds(
        fold_plan,
        scenario_ids=scenario_ids,
        outer_count=5,
        inner_count=4,
    )
    profiles = [
        _find_profile(normalized_nested["profile_shortlist"], profile_id)
        for profile_id in normalized_audit["compared_profiles"]
    ]
    constraints = BinaryCalibrationConstraints(
        maximum_false_ready_rate=normalized_nested["admission"][
            "maximum_false_ready_rate"
        ],
        minimum_ready_recall=normalized_nested["admission"][
            "minimum_ready_recall"
        ],
    )

    empirical = _empirical_diagnostics(
        normalized_samples,
        profiles=profiles,
        folds=folds,
        constraints=constraints,
        criteria=normalized_audit["empirical_equivalence"],
    )
    semantic = _semantic_diagnostics(
        profiles,
        counterfactual_pairs=normalized_audit["counterfactual_pairs"],
        criteria=normalized_audit["semantic_equivalence"],
    )
    empirical_equivalent = all(empirical["checks"].values())
    semantic_equivalent = all(semantic["checks"].values())
    if empirical_equivalent and semantic_equivalent:
        decision = "PREDECLARED_EQUIVALENCE_DESIGN_REVIEW_JUSTIFIED"
    elif empirical_equivalent:
        decision = "EMPIRICALLY_CLOSE_SEMANTICALLY_DISTINCT_CANONICAL_PROFILE_REQUIRED"
    else:
        decision = "DISTINCT_PROFILES_FRESH_DESIGN_REQUIRED"

    checks = {
        "p_j_exact_profile_instability_bound": normalized_selection["status"]
        == "NO_ADMISSIBLE_PROFILE",
        "all_outer_folds_compared": empirical["fold_count"] == len(folds),
        "empirical_diagnostics_complete": empirical["status"] == "COMPARED",
        "holdout_access_prohibited": True,
        "runtime_activation_prohibited": True,
        "equivalence_not_retroactively_authorized": True,
    }
    result: dict[str, Any] = {
        "audit_schema_version": PROFILE_EQUIVALENCE_AUDIT_SCHEMA_VERSION,
        "policy_id": PROFILE_EQUIVALENCE_AUDIT_POLICY_ID,
        "status": "DIAGNOSED" if all(checks.values()) else "INCONCLUSIVE",
        "decision": decision if all(checks.values()) else "STOP_FOR_REVIEW",
        "source_binding": {
            "collection_hash": normalized_audit["source_binding"][
                "collection_hash"
            ],
            "nested_design_hash": normalized_nested["design_hash"],
            "p_j_selection_hash": normalized_selection["selection_hash"],
            "audit_design_hash": normalized_audit["audit_design_hash"],
        },
        "dataset": {
            "partition": "CALIBRATION",
            "scenario_count": len(scenario_ids),
            "package_count": len(normalized_samples),
        },
        "compared_profiles": list(normalized_audit["compared_profiles"]),
        "empirical_equivalence": empirical,
        "semantic_equivalence": semantic,
        "equivalence_family_authorized": False,
        "next_contract": {
            "canonical_profile_design_required": not semantic_equivalent,
            "fresh_calibration_evidence_required": True,
            "holdout_access_permitted": False,
            "runtime_activation_permitted": False,
        },
        "checks": checks,
    }
    result["audit_hash"] = semantic_sha256_hash_ref(result)
    return result


def validate_profile_equivalence_audit_design(
    design: Mapping[str, Any],
) -> dict[str, Any]:
    _exact_mapping(design, _DESIGN_FIELDS, "profile equivalence audit design")
    if (
        design.get("audit_schema_version")
        != PROFILE_EQUIVALENCE_AUDIT_DESIGN_SCHEMA_VERSION
        or design.get("status") != "FROZEN_CALIBRATION_ONLY"
    ):
        raise ValueError("profile equivalence audit design identity is invalid")
    audit_id = _required_text(design.get("audit_id"), "audit_id")
    binding = _mapping(design.get("source_binding"), "source binding")
    if set(binding) != {
        "collection_hash",
        "nested_design_id",
        "p_j_selection_hash",
    }:
        raise ValueError("profile equivalence source binding is invalid")
    normalized_binding = {
        "collection_hash": validate_hash_ref(binding.get("collection_hash")),
        "nested_design_id": _required_text(
            binding.get("nested_design_id"), "nested_design_id"
        ),
        "p_j_selection_hash": validate_hash_ref(
            binding.get("p_j_selection_hash")
        ),
    }
    profiles = design.get("compared_profiles")
    if (
        isinstance(profiles, (str, bytes))
        or not isinstance(profiles, Sequence)
        or len(profiles) != 2
        or len(set(profiles)) != 2
    ):
        raise ValueError("profile equivalence compared profiles are invalid")
    normalized_profiles = [_required_text(value, "profile_id") for value in profiles]
    empirical = _criteria(
        design.get("empirical_equivalence"),
        expected={
            "maximum_oof_decision_disagreement_rate",
            "minimum_score_ordering_agreement_rate",
            "require_complete_fold_local_thresholds",
        },
        name="empirical equivalence",
    )
    semantic = _criteria(
        design.get("semantic_equivalence"),
        expected={
            "counterfactual_delta_tolerance",
            "require_equal_feature_dependency_sets",
            "require_counterfactual_response_equivalence",
        },
        name="semantic equivalence",
    )
    normalized_empirical = {
        "maximum_oof_decision_disagreement_rate": _rate(
            empirical["maximum_oof_decision_disagreement_rate"],
            "maximum_oof_decision_disagreement_rate",
        ),
        "minimum_score_ordering_agreement_rate": _rate(
            empirical["minimum_score_ordering_agreement_rate"],
            "minimum_score_ordering_agreement_rate",
        ),
        "require_complete_fold_local_thresholds": _required_bool(
            empirical["require_complete_fold_local_thresholds"],
            "require_complete_fold_local_thresholds",
        ),
    }
    normalized_semantic = {
        "counterfactual_delta_tolerance": _nonnegative(
            semantic["counterfactual_delta_tolerance"],
            "counterfactual_delta_tolerance",
        ),
        "require_equal_feature_dependency_sets": _required_bool(
            semantic["require_equal_feature_dependency_sets"],
            "require_equal_feature_dependency_sets",
        ),
        "require_counterfactual_response_equivalence": _required_bool(
            semantic["require_counterfactual_response_equivalence"],
            "require_counterfactual_response_equivalence",
        ),
    }
    if normalized_empirical["require_complete_fold_local_thresholds"] is not True:
        raise ValueError("empirical equivalence threshold requirement is invalid")
    if (
        normalized_semantic["require_equal_feature_dependency_sets"] is not True
        or normalized_semantic["require_counterfactual_response_equivalence"]
        is not True
    ):
        raise ValueError("semantic equivalence requirements are invalid")
    pairs = _counterfactual_pairs(design.get("counterfactual_pairs"))
    safety = _mapping(design.get("safety"), "profile equivalence safety")
    if dict(safety) != {
        "equivalence_family_authorized": False,
        "holdout_access_permitted": False,
        "profile_or_threshold_mutation_permitted": False,
        "runtime_activation_permitted": False,
    }:
        raise ValueError("profile equivalence safety is invalid")
    normalized: dict[str, Any] = {
        "audit_schema_version": PROFILE_EQUIVALENCE_AUDIT_DESIGN_SCHEMA_VERSION,
        "audit_id": audit_id,
        "status": "FROZEN_CALIBRATION_ONLY",
        "source_binding": normalized_binding,
        "compared_profiles": normalized_profiles,
        "empirical_equivalence": normalized_empirical,
        "semantic_equivalence": normalized_semantic,
        "counterfactual_pairs": pairs,
        "safety": dict(safety),
    }
    normalized["audit_design_hash"] = semantic_sha256_hash_ref(normalized)
    return normalized


def _validate_p_j_selection(
    selection: Mapping[str, Any],
    *,
    expected_selection_hash: str,
    expected_collection_hash: str,
    expected_design_hash: str,
    compared_profiles: set[str],
) -> dict[str, Any]:
    normalized = dict(_mapping(selection, "P-J selection"))
    selection_hash = validate_hash_ref(normalized.pop("selection_hash", None))
    if selection_hash != semantic_sha256_hash_ref(normalized):
        raise ValueError("P-J selection integrity is invalid")
    if (
        selection_hash != expected_selection_hash
        or normalized.get("selection_schema_version")
        != ANSWER_SUPPORT_NESTED_SELECTION_SCHEMA_VERSION
        or normalized.get("status") != "NO_ADMISSIBLE_PROFILE"
        or normalized.get("runtime_activation_permitted") is not False
        or normalized.get("holdout_access_permitted") is not False
    ):
        raise ValueError("P-J selection boundary is invalid")
    binding = _mapping(normalized.get("binding"), "P-J binding")
    if (
        binding.get("source_collection_hash") != expected_collection_hash
        or binding.get("answer_support_design_hash") != expected_design_hash
    ):
        raise ValueError("P-J selection binding is invalid")
    evaluation = _mapping(normalized.get("oof_evaluation"), "P-J evaluation")
    counts = _mapping(
        evaluation.get("profile_selection_counts"), "P-J profile counts"
    )
    if set(counts) != compared_profiles or sum(int(value) for value in counts.values()) != 5:
        raise ValueError("P-J exact-profile instability is invalid")
    normalized["selection_hash"] = selection_hash
    return normalized


def _empirical_diagnostics(
    samples: Sequence[Mapping[str, Any]],
    *,
    profiles: Sequence[Mapping[str, Any]],
    folds: Sequence[Mapping[str, Any]],
    constraints: BinaryCalibrationConstraints,
    criteria: Mapping[str, Any],
) -> dict[str, Any]:
    score_maps = [
        {str(row["sample_id"]): float(row["score"]) for row in _profile_scores(samples, profile=profile)}
        for profile in profiles
    ]
    ordering = _ordering_agreement(score_maps[0], score_maps[1])
    thresholds: dict[str, list[float]] = {
        str(profile["profile_id"]): [] for profile in profiles
    }
    compared = 0
    disagreements = 0
    failed_refits: list[dict[str, Any]] = []
    all_scenarios = {str(row["scenario_id"]) for row in samples}
    for outer in folds:
        validation_ids = set(outer["validation_scenario_ids"])
        training_ids = all_scenarios - validation_ids
        fold_predictions = []
        for profile in profiles:
            training = _profile_scores(
                samples, profile=profile, scenario_ids=training_ids
            )
            fit = evaluate_binary_score_calibration(
                training,
                dataset_id=(
                    "s20q-p-k:outer-"
                    f"{outer['fold_index']}:{profile['profile_id']}:train"
                ),
                constraints=constraints,
            )
            threshold = fit.get("selected_threshold")
            if threshold is None:
                failed_refits.append(
                    {
                        "fold_index": outer["fold_index"],
                        "profile_id": profile["profile_id"],
                    }
                )
                fold_predictions.append({})
                continue
            thresholds[str(profile["profile_id"])].append(float(threshold))
            validation = _profile_scores(
                samples, profile=profile, scenario_ids=validation_ids
            )
            fold_predictions.append(
                {
                    str(row["sample_id"]): float(row["score"]) >= float(threshold)
                    for row in validation
                }
            )
        if all(fold_predictions):
            sample_ids = set(fold_predictions[0])
            if sample_ids != set(fold_predictions[1]):
                raise ValueError("profile equivalence OOF package coverage is invalid")
            compared += len(sample_ids)
            disagreements += sum(
                fold_predictions[0][sample_id] != fold_predictions[1][sample_id]
                for sample_id in sample_ids
            )
    disagreement_rate = round(disagreements / compared, 8) if compared else None
    thresholds_complete = not failed_refits and all(
        len(values) == len(folds) for values in thresholds.values()
    )
    checks = {
        "score_ordering_agreement_within_limit": ordering
        >= criteria["minimum_score_ordering_agreement_rate"],
        "oof_decision_disagreement_within_limit": disagreement_rate is not None
        and disagreement_rate
        <= criteria["maximum_oof_decision_disagreement_rate"],
        "fold_local_thresholds_complete": thresholds_complete,
    }
    return {
        "status": "COMPARED" if thresholds_complete else "INCONCLUSIVE",
        "fold_count": len(folds),
        "package_count": len(samples),
        "score_ordering_agreement_rate": ordering,
        "oof_compared_package_count": compared,
        "oof_decision_disagreement_count": disagreements,
        "oof_decision_disagreement_rate": disagreement_rate,
        "fold_local_thresholds": thresholds,
        "failed_refits": failed_refits,
        "checks": checks,
    }


def _semantic_diagnostics(
    profiles: Sequence[Mapping[str, Any]],
    *,
    counterfactual_pairs: Sequence[Mapping[str, Any]],
    criteria: Mapping[str, Any],
) -> dict[str, Any]:
    dependency_sets = {
        str(profile["profile_id"]): sorted(str(value) for value in profile["feature_fields"])
        for profile in profiles
    }
    dependencies_equal = len({tuple(value) for value in dependency_sets.values()}) == 1
    tolerance = float(criteria["counterfactual_delta_tolerance"])
    probes = []
    responses_equivalent = True
    for pair in counterfactual_pairs:
        deltas = {
            str(profile["profile_id"]): round(
                _score_features(pair["variant"], profile)
                - _score_features(pair["baseline"], profile),
                12,
            )
            for profile in profiles
        }
        delta_values = list(deltas.values())
        equivalent = math.isclose(
            delta_values[0], delta_values[1], abs_tol=tolerance
        )
        responses_equivalent = responses_equivalent and equivalent
        probes.append(
            {
                "pair_id": pair["pair_id"],
                "profile_score_deltas": deltas,
                "response_equivalent": equivalent,
            }
        )
    checks = {
        "feature_dependency_sets_equal": dependencies_equal,
        "counterfactual_responses_equivalent": responses_equivalent,
    }
    return {
        "status": "COMPARED",
        "feature_dependency_sets": dependency_sets,
        "counterfactual_probes": probes,
        "checks": checks,
    }


def _ordering_agreement(
    left: Mapping[str, float], right: Mapping[str, float]
) -> float:
    if not left or set(left) != set(right):
        raise ValueError("profile equivalence score coverage is invalid")
    sample_ids = sorted(left)
    agreements = 0
    comparisons = 0
    for index, first in enumerate(sample_ids):
        for second in sample_ids[index + 1 :]:
            left_direction = _direction(left[first] - left[second])
            right_direction = _direction(right[first] - right[second])
            agreements += left_direction == right_direction
            comparisons += 1
    if comparisons == 0:
        raise ValueError("profile equivalence ordering requires two packages")
    return round(agreements / comparisons, 8)


def _counterfactual_pairs(value: object) -> list[dict[str, Any]]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or not value:
        raise ValueError("profile equivalence counterfactual pairs are invalid")
    pairs = []
    seen = set()
    for raw in value:
        pair = _mapping(raw, "counterfactual pair")
        if set(pair) != {"pair_id", "baseline", "variant"}:
            raise ValueError("profile equivalence counterfactual pair fields are invalid")
        pair_id = _required_text(pair.get("pair_id"), "pair_id")
        if pair_id in seen:
            raise ValueError("profile equivalence counterfactual pair is duplicated")
        seen.add(pair_id)
        pairs.append(
            {
                "pair_id": pair_id,
                "baseline": _features(pair.get("baseline")),
                "variant": _features(pair.get("variant")),
            }
        )
    return pairs


def _features(value: object) -> dict[str, float]:
    features = _mapping(value, "counterfactual features")
    if set(features) != set(AVAILABLE_FEATURE_FIELDS):
        raise ValueError("counterfactual feature fields are invalid")
    return {field: _rate(features[field], field) for field in AVAILABLE_FEATURE_FIELDS}


def _score_features(
    features: Mapping[str, float], profile: Mapping[str, Any]
) -> float:
    return sum(
        float(features[field]) * float(profile["weights"][field])
        for field in profile["feature_fields"]
    )


def _criteria(value: object, *, expected: set[str], name: str) -> Mapping[str, Any]:
    criteria = _mapping(value, name)
    if set(criteria) != expected:
        raise ValueError(f"{name} fields are invalid")
    return criteria


def _direction(value: float) -> int:
    return 1 if value > 0 else -1 if value < 0 else 0


def _rate(value: object, field: str) -> float:
    number = _nonnegative(value, field)
    if number > 1.0:
        raise ValueError(f"{field} is invalid")
    return number


def _nonnegative(value: object, field: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(float(value))
        or float(value) < 0.0
    ):
        raise ValueError(f"{field} is invalid")
    return float(value)


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is invalid")
    return value.strip()


def _required_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field} is invalid")
    return value


def _exact_mapping(value: object, fields: set[str], name: str) -> Mapping[str, Any]:
    mapping = _mapping(value, name)
    if set(mapping) != fields:
        raise ValueError(f"{name} fields are invalid")
    return mapping


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} is invalid")
    return value
