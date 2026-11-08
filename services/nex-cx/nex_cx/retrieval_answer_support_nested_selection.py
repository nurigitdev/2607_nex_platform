from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from nex_runtime.model_calibration import (
    BinaryCalibrationConstraints,
    evaluate_binary_score_calibration,
    evaluate_binary_score_threshold,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

import nex_cx.retrieval_calibration_nested_selection as nested_support
from nex_cx.retrieval_answer_support_collection import (
    ANSWER_SUPPORT_COLLECTION_POLICY_ID,
    ANSWER_SUPPORT_COLLECTION_SCHEMA_VERSION,
    validate_answer_support_calibration_collection,
)
from nex_cx.retrieval_answer_support_signal import (
    ANSWER_SUPPORT_EVIDENCE_SCHEMA_VERSION,
    ANSWER_SUPPORT_FEATURE_SCHEMA_VERSION,
    ANSWER_SUPPORT_POLICY_ID,
    ANSWER_SUPPORT_SCORE_SEMANTICS,
    PROVIDER_BINDING_FIELDS,
    build_answer_support_package_features,
)

ANSWER_SUPPORT_NESTED_DESIGN_SCHEMA_VERSION = (
    "cx_answer_support_nested_calibration_design.v1"
)
ANSWER_SUPPORT_NESTED_SAMPLE_SCHEMA_VERSION = (
    "cx_answer_support_nested_calibration_sample.v1"
)
ANSWER_SUPPORT_NESTED_SELECTION_SCHEMA_VERSION = (
    "cx_answer_support_nested_profile_selection.v1"
)

SOURCE_FEATURE_FIELDS = (
    "direct_or_support_fraction",
    "second_answer_support_score",
    "top_two_answer_support_mean",
    "maximum_contradiction_score",
    "mean_contradiction_score",
    "support_contradiction_margin",
)
AVAILABLE_FEATURE_FIELDS = (
    "direct_or_support_fraction",
    "second_answer_support_score",
    "top_two_answer_support_mean",
    "inverse_maximum_contradiction_score",
    "inverse_mean_contradiction_score",
    "normalized_support_contradiction_margin",
)

_DESIGN_FIELDS = {
    "design_schema_version",
    "design_id",
    "status",
    "source_contract",
    "feature_transforms",
    "profile_shortlist",
    "selection_protocol",
    "admission",
    "safety",
}
_SAMPLE_FIELDS = {
    "sample_schema_version",
    "sample_id",
    "scenario_id",
    "expected_ready",
    "domain",
    "language_profile",
    "features",
    "source_feature_hash",
    "source_evidence_hash",
    "sample_hash",
}


def validate_answer_support_nested_design(
    design: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate the pre-frozen P-J feature shortlist and admission boundary."""
    _exact_mapping(design, _DESIGN_FIELDS, "answer support nested design")
    if (
        design.get("design_schema_version")
        != ANSWER_SUPPORT_NESTED_DESIGN_SCHEMA_VERSION
        or design.get("status") != "FROZEN_CALIBRATION_ONLY"
    ):
        raise ValueError("answer support nested design identity is invalid")
    _required_text(design.get("design_id"), "design_id")
    source = _mapping(design.get("source_contract"), "source contract")
    if dict(source) != {
        "collection_policy_id": ANSWER_SUPPORT_COLLECTION_POLICY_ID,
        "collection_schema_version": ANSWER_SUPPORT_COLLECTION_SCHEMA_VERSION,
        "feature_schema_version": ANSWER_SUPPORT_FEATURE_SCHEMA_VERSION,
        "signal_policy_id": ANSWER_SUPPORT_POLICY_ID,
    }:
        raise ValueError("answer support nested source contract is invalid")
    transforms = _mapping(design.get("feature_transforms"), "feature transforms")
    if transforms.get("source_fields") != list(SOURCE_FEATURE_FIELDS) or transforms.get(
        "available_fields"
    ) != list(AVAILABLE_FEATURE_FIELDS):
        raise ValueError("answer support nested feature transforms are invalid")
    if {
        key: transforms.get(key)
        for key in (
            "inverse_maximum_contradiction_score",
            "inverse_mean_contradiction_score",
            "normalized_support_contradiction_margin",
        )
    } != {
        "inverse_maximum_contradiction_score": "1 - maximum_contradiction_score",
        "inverse_mean_contradiction_score": "1 - mean_contradiction_score",
        "normalized_support_contradiction_margin": (
            "(support_contradiction_margin + 1) / 2"
        ),
    }:
        raise ValueError("answer support nested feature transforms are invalid")
    profiles = _profiles(design.get("profile_shortlist"))
    if len(profiles) != 4:
        raise ValueError("answer support nested profile shortlist is invalid")
    protocol = _mapping(design.get("selection_protocol"), "selection protocol")
    if (
        protocol.get("mode")
        != "NESTED_STRATIFIED_GROUP_CV_WITH_PREFROZEN_ANSWER_SUPPORT_SHORTLIST"
        or protocol.get("group_key") != "scenario_id"
        or protocol.get("outer_fold_count") != 5
        or protocol.get("inner_fold_count") != 4
        or protocol.get("selection_objective")
        != "CONSTRAINT_FIRST_BALANCED_ACCURACY"
    ):
        raise ValueError("answer support nested selection protocol is invalid")
    expected_tie_break = [
        "HIGHER_BALANCED_ACCURACY",
        "HIGHER_READY_RECALL",
        "LOWER_FALSE_READY_RATE",
        "HIGHER_PACKAGE_AUC",
        "PROFILE_SHORTLIST_ORDER",
    ]
    if protocol.get("selection_tie_break") != expected_tie_break:
        raise ValueError("answer support nested selection tie break is invalid")
    admission = _admission(design.get("admission"))
    if admission["point_constraints_remain_authoritative"] is not True:
        raise ValueError("answer support nested admission is invalid")
    safety = _mapping(design.get("safety"), "nested design safety")
    if dict(safety) != {
        "candidate_truth_runtime_input_permitted": False,
        "holdout_access_permitted": False,
        "outer_validation_reselection_permitted": False,
        "runtime_activation_permitted": False,
        "threshold_relaxation_permitted": False,
    }:
        raise ValueError("answer support nested safety is invalid")
    normalized = dict(design)
    normalized["profile_shortlist"] = profiles
    normalized["admission"] = admission
    normalized["design_hash"] = semantic_sha256_hash_ref(normalized)
    return normalized


def build_answer_support_nested_samples(
    collection: Mapping[str, Any],
    dataset_cases: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Join text-free P-I evidence to CALIBRATION metadata and labels only."""
    normalized = validate_answer_support_calibration_collection(collection)
    if isinstance(dataset_cases, (str, bytes)) or not isinstance(
        dataset_cases, Sequence
    ):
        raise TypeError("answer support nested dataset cases are invalid")
    calibration: dict[str, Mapping[str, Any]] = {}
    for raw in dataset_cases:
        case = _mapping(raw, "answer support nested dataset case")
        if case.get("partition") != "CALIBRATION":
            continue
        case_id = _required_text(case.get("case_id"), "case_id")
        if case_id in calibration:
            raise ValueError("answer support nested dataset case is duplicated")
        calibration[case_id] = case
    packages = {
        str(row["package_id"]): row for row in normalized["package_evidence"]
    }
    if set(calibration) != set(packages):
        raise ValueError("answer support nested package coverage is invalid")

    samples = []
    for package_id, case in sorted(calibration.items()):
        package = packages[package_id]
        evidence = _reconstruct_evidence(normalized, package)
        projection = build_answer_support_package_features(evidence)
        features = _transformed_features(projection["features"])
        sample: dict[str, Any] = {
            "sample_schema_version": ANSWER_SUPPORT_NESTED_SAMPLE_SCHEMA_VERSION,
            "sample_id": package_id,
            "scenario_id": _required_text(case.get("scenario_id"), "scenario_id"),
            "expected_ready": _required_bool(
                case.get("expected_ready"), "expected_ready"
            ),
            "domain": _required_text(case.get("domain"), "domain"),
            "language_profile": _required_text(
                case.get("language_profile"), "language_profile"
            ),
            "features": features,
            "source_feature_hash": projection["feature_hash"],
            "source_evidence_hash": package["evidence_hash"],
        }
        sample["sample_hash"] = semantic_sha256_hash_ref(sample)
        samples.append(sample)
    return _normalize_samples(samples)


def select_nested_answer_support_profile(
    samples: Sequence[Mapping[str, Any]],
    *,
    dataset_id: str,
    dataset_sha256: str,
    collection_hash: str,
    provider_binding: Mapping[str, Any],
    design: Mapping[str, Any],
    fold_plan: Mapping[str, Any],
) -> dict[str, Any]:
    """Select one P-J profile using CALIBRATION nested folds only."""
    normalized = _normalize_samples(samples)
    scenario_ids = {str(row["scenario_id"]) for row in normalized}
    normalized_design = validate_answer_support_nested_design(design)
    profiles = normalized_design["profile_shortlist"]
    admission = normalized_design["admission"]
    outer_folds = _validated_outer_folds(
        fold_plan,
        scenario_ids=scenario_ids,
        outer_count=5,
        inner_count=4,
    )
    constraints = BinaryCalibrationConstraints(
        maximum_false_ready_rate=admission["maximum_false_ready_rate"],
        minimum_ready_recall=admission["minimum_ready_recall"],
    )
    binding = _provider_binding(provider_binding)
    source_collection_hash = validate_hash_ref(collection_hash)

    outer_results = []
    oof_rows: list[dict[str, Any]] = []
    for outer in outer_folds:
        result, validation_rows = _evaluate_outer_fold(
            normalized,
            outer=outer,
            profiles=profiles,
            constraints=constraints,
            minimum_package_auc=admission["minimum_package_auc"],
            dataset_id=dataset_id,
        )
        outer_results.append(result)
        oof_rows.extend(validation_rows)

    completed = [row for row in outer_results if row["status"] == "EVALUATED"]
    selected_counts = Counter(str(row["selected_profile_id"]) for row in completed)
    stable_profile_id, stable_count = (
        selected_counts.most_common(1)[0] if selected_counts else (None, 0)
    )
    aggregate = nested_support._aggregate_metrics(
        [nested_support._mapping(row.get("metrics")) for row in completed]
    )
    thresholds = [float(row["threshold"]) for row in completed]
    threshold_spread = (
        round(max(thresholds) - min(thresholds), 8) if thresholds else None
    )
    minimum_outer_accuracy = (
        min(float(row["metrics"]["balanced_accuracy"]) for row in completed)
        if completed
        else None
    )
    package_auc = _auc(oof_rows) if oof_rows else None
    checks = {
        "all_outer_folds_evaluated": len(completed) == len(outer_folds),
        "stable_profile_selected": stable_count
        >= admission["minimum_profile_selection_fold_count"],
        "false_ready_rate_within_limit": aggregate is not None
        and aggregate["false_ready_rate"] <= admission["maximum_false_ready_rate"],
        "ready_recall_within_limit": aggregate is not None
        and aggregate["ready_recall"] >= admission["minimum_ready_recall"],
        "package_auc_within_limit": package_auc is not None
        and package_auc >= admission["minimum_package_auc"],
        "minimum_outer_accuracy_within_limit": minimum_outer_accuracy is not None
        and minimum_outer_accuracy
        >= admission["minimum_outer_fold_balanced_accuracy"],
        "outer_threshold_spread_within_limit": threshold_spread is not None
        and threshold_spread <= admission["maximum_outer_threshold_spread"],
    }
    admitted = all(checks.values())
    final_fit = None
    stable_profile = None
    if admitted and stable_profile_id is not None:
        stable_profile = _find_profile(profiles, stable_profile_id)
        final_fit = evaluate_binary_score_calibration(
            _profile_scores(normalized, profile=stable_profile),
            dataset_id=f"{dataset_id}:answer-support:full-calibration",
            constraints=constraints,
        )
        checks["full_calibration_threshold_fitted"] = (
            final_fit["status"] == "PASSED"
        )
        if not checks["full_calibration_threshold_fitted"]:
            admitted = False
            final_fit = None

    result: dict[str, Any] = {
        "selection_schema_version": ANSWER_SUPPORT_NESTED_SELECTION_SCHEMA_VERSION,
        "status": (
            "CALIBRATION_OOF_ADMITTED" if admitted else "NO_ADMISSIBLE_PROFILE"
        ),
        "reason_code": (
            "ANSWER_SUPPORT_NESTED_CONSTRAINTS_SATISFIED"
            if admitted
            else "ANSWER_SUPPORT_NESTED_CONSTRAINTS_NOT_SATISFIED"
        ),
        "runtime_activation_permitted": False,
        "holdout_access_permitted": False,
        "dataset": {
            "dataset_id": _required_text(dataset_id, "dataset_id"),
            "dataset_sha256": _required_text(dataset_sha256, "dataset_sha256"),
            "partition": "CALIBRATION",
            "scenario_count": len(scenario_ids),
            "package_count": len(normalized),
            "sample_set_hash": semantic_sha256_hash_ref(
                sorted(str(row["sample_hash"]) for row in normalized)
            ),
        },
        "binding": {
            "source_collection_hash": source_collection_hash,
            "answer_support_design_hash": normalized_design["design_hash"],
            "provider_binding": binding,
        },
        "protocol": {
            "mode": normalized_design["selection_protocol"]["mode"],
            "outer_fold_count": len(outer_folds),
            "inner_fold_count": 4,
            "profile_shortlist": [row["profile_id"] for row in profiles],
            "inner_training_scope": "CALIBRATION_INNER_TRAINING_ONLY",
            "outer_validation_reselection_permitted": False,
            "holdout_selection_permitted": False,
        },
        "outer_folds": outer_results,
        "oof_evaluation": {
            "metrics": aggregate,
            "confidence_intervals": nested_support._confidence_intervals(aggregate),
            "package_auc": package_auc,
            "minimum_outer_fold_balanced_accuracy": minimum_outer_accuracy,
            "threshold_spread": threshold_spread,
            "profile_selection_counts": dict(sorted(selected_counts.items())),
            "stable_profile_id": stable_profile_id,
            "stable_profile_fold_count": stable_count,
        },
        "checks": checks,
        "selected": (
            {
                "profile_id": stable_profile_id,
                "profile": stable_profile,
                "threshold": final_fit["selected_threshold"],
                "fit": final_fit,
            }
            if admitted and stable_profile is not None and final_fit is not None
            else None
        ),
        "holdout": {
            "status": "SEALED_NOT_OPENED",
            "scenario_count": 20,
            "threshold_reselected": False,
        },
    }
    result["selection_hash"] = semantic_sha256_hash_ref(result)
    return result


def _evaluate_outer_fold(
    samples: Sequence[Mapping[str, Any]],
    *,
    outer: Mapping[str, Any],
    profiles: Sequence[Mapping[str, Any]],
    constraints: BinaryCalibrationConstraints,
    minimum_package_auc: float,
    dataset_id: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    outer_index = int(outer["fold_index"])
    validation_ids = set(outer["validation_scenario_ids"])
    all_ids = {str(row["scenario_id"]) for row in samples}
    training_ids = all_ids - validation_ids
    candidates = []
    for shortlist_index, profile in enumerate(profiles):
        folds = []
        all_thresholds_available = True
        inner_rows: list[dict[str, Any]] = []
        for inner in outer["inner_folds"]:
            inner_validation_ids = set(inner["validation_scenario_ids"])
            inner_training_ids = training_ids - inner_validation_ids
            training_scores = _profile_scores(
                samples, profile=profile, scenario_ids=inner_training_ids
            )
            fit = evaluate_binary_score_calibration(
                training_scores,
                dataset_id=(
                    f"{dataset_id}:answer-support:outer-{outer_index}:"
                    f"inner-{inner['fold_index']}:train:{profile['profile_id']}"
                ),
                constraints=constraints,
            )
            threshold = fit.get("selected_threshold")
            if threshold is None:
                all_thresholds_available = False
                threshold = nested_support._mapping(
                    fit.get("best_effort_metrics")
                ).get("threshold")
            if threshold is None:
                continue
            validation_scores = _profile_scores(
                samples, profile=profile, scenario_ids=inner_validation_ids
            )
            evaluated = evaluate_binary_score_threshold(
                validation_scores,
                dataset_id=(
                    f"{dataset_id}:answer-support:outer-{outer_index}:"
                    f"inner-{inner['fold_index']}:validation"
                ),
                threshold=float(threshold),
                constraints=nested_support._partition_constraints(
                    len(validation_scores), constraints=constraints
                ),
            )
            inner_rows.extend(validation_scores)
            folds.append(
                {
                    "fold_index": inner["fold_index"],
                    "threshold": float(threshold),
                    "threshold_source": (
                        "SELECTED_THRESHOLD"
                        if fit.get("selected_threshold") is not None
                        else "BEST_EFFORT_DIAGNOSTIC_ONLY"
                    ),
                    "training_package_count": len(training_scores),
                    "metrics": evaluated["metrics"],
                }
            )
        metrics = nested_support._aggregate_metrics(
            [nested_support._mapping(row["metrics"]) for row in folds]
        )
        package_auc = _auc(inner_rows) if inner_rows else None
        admissible = (
            all_thresholds_available
            and len(folds) == len(outer["inner_folds"])
            and metrics is not None
            and metrics["false_ready_rate"] <= constraints.maximum_false_ready_rate
            and metrics["ready_recall"] >= constraints.minimum_ready_recall
            and package_auc is not None
            and package_auc >= minimum_package_auc
        )
        candidates.append(
            {
                "profile_id": profile["profile_id"],
                "shortlist_index": shortlist_index,
                "status": "ADMISSIBLE" if admissible else "REJECTED",
                "metrics": metrics,
                "package_auc": package_auc,
                "inner_folds": folds,
            }
        )
    admissible = [row for row in candidates if row["status"] == "ADMISSIBLE"]
    if not admissible:
        return (
            {
                "fold_index": outer_index,
                "status": "NO_ADMISSIBLE_PROFILE",
                "selected_profile_id": None,
                "threshold": None,
                "metrics": None,
                "inner_selection": candidates,
            },
            [],
        )
    selected = max(admissible, key=_selection_key)
    profile = _find_profile(profiles, str(selected["profile_id"]))
    training_scores = _profile_scores(samples, profile=profile, scenario_ids=training_ids)
    fit = evaluate_binary_score_calibration(
        training_scores,
        dataset_id=f"{dataset_id}:answer-support:outer-{outer_index}:refit",
        constraints=constraints,
    )
    threshold = fit.get("selected_threshold")
    if threshold is None:
        return (
            {
                "fold_index": outer_index,
                "status": "OUTER_REFIT_FAILED",
                "selected_profile_id": selected["profile_id"],
                "threshold": None,
                "metrics": None,
                "inner_selection": candidates,
            },
            [],
        )
    validation_scores = _profile_scores(
        samples, profile=profile, scenario_ids=validation_ids
    )
    evaluated = evaluate_binary_score_threshold(
        validation_scores,
        dataset_id=f"{dataset_id}:answer-support:outer-{outer_index}:validation",
        threshold=float(threshold),
        constraints=nested_support._partition_constraints(
            len(validation_scores), constraints=constraints
        ),
    )
    return (
        {
            "fold_index": outer_index,
            "status": "EVALUATED",
            "selected_profile_id": selected["profile_id"],
            "threshold": float(threshold),
            "training_package_count": len(training_scores),
            "metrics": evaluated["metrics"],
            "confidence_intervals": evaluated["confidence_intervals"],
            "inner_selection": candidates,
        },
        validation_scores,
    )


def _reconstruct_evidence(
    collection: Mapping[str, Any], package: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "evidence_schema_version": ANSWER_SUPPORT_EVIDENCE_SCHEMA_VERSION,
        "policy_id": ANSWER_SUPPORT_POLICY_ID,
        "status": "CONTRACT_EVIDENCE_NORMALIZED",
        "design_hash": collection["answer_support_design_hash"],
        "request_id": package["request_id"],
        "request_hash": package["request_hash"],
        "query_sha256": package["query_sha256"],
        "provider_binding": collection["provider_binding"],
        "score_semantics": ANSWER_SUPPORT_SCORE_SEMANTICS,
        "candidate_evidence": package["candidate_evidence"],
        "privacy": {
            "raw_query_persisted": False,
            "raw_candidate_text_persisted": False,
            "free_form_rationale_persisted": False,
        },
        "safety": {
            "candidate_truth_runtime_input_permitted": False,
            "holdout_access_permitted": False,
            "threshold_selected": False,
            "ready_decision_emitted": False,
            "runtime_activation_permitted": False,
        },
        "evidence_hash": package["evidence_hash"],
    }


def _transformed_features(value: Mapping[str, Any]) -> dict[str, float]:
    features = _mapping(value, "answer support package features")
    source = {field: _bounded(features.get(field), field, lower=-1.0) for field in SOURCE_FEATURE_FIELDS}
    for field in SOURCE_FEATURE_FIELDS[:-1]:
        if not 0.0 <= source[field] <= 1.0:
            raise ValueError("answer support package feature is invalid")
    transformed = {
        "direct_or_support_fraction": source["direct_or_support_fraction"],
        "second_answer_support_score": source["second_answer_support_score"],
        "top_two_answer_support_mean": source["top_two_answer_support_mean"],
        "inverse_maximum_contradiction_score": 1.0
        - source["maximum_contradiction_score"],
        "inverse_mean_contradiction_score": 1.0
        - source["mean_contradiction_score"],
        "normalized_support_contradiction_margin": (
            source["support_contradiction_margin"] + 1.0
        )
        / 2.0,
    }
    return {field: round(transformed[field], 12) for field in AVAILABLE_FEATURE_FIELDS}


def _normalize_samples(
    values: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise TypeError("answer support nested samples are invalid")
    normalized = []
    seen = set()
    scenario_labels: dict[str, set[bool]] = {}
    scenario_counts: Counter[str] = Counter()
    for raw in values:
        _exact_mapping(raw, _SAMPLE_FIELDS, "answer support nested sample")
        row = dict(raw)
        sample_hash = validate_hash_ref(row.pop("sample_hash", None))
        if sample_hash != semantic_sha256_hash_ref(row):
            raise ValueError("answer support nested sample integrity is invalid")
        if row.get("sample_schema_version") != ANSWER_SUPPORT_NESTED_SAMPLE_SCHEMA_VERSION:
            raise ValueError("answer support nested sample identity is invalid")
        sample_id = _required_text(row.get("sample_id"), "sample_id")
        if sample_id in seen:
            raise ValueError("answer support nested sample is duplicated")
        seen.add(sample_id)
        scenario_id = _required_text(row.get("scenario_id"), "scenario_id")
        expected_ready = _required_bool(row.get("expected_ready"), "expected_ready")
        _required_text(row.get("domain"), "domain")
        _required_text(row.get("language_profile"), "language_profile")
        features = _mapping(row.get("features"), "answer support nested features")
        if set(features) != set(AVAILABLE_FEATURE_FIELDS):
            raise ValueError("answer support nested feature fields are invalid")
        row["features"] = {
            field: _bounded(features[field], field) for field in AVAILABLE_FEATURE_FIELDS
        }
        validate_hash_ref(row.get("source_feature_hash"))
        validate_hash_ref(row.get("source_evidence_hash"))
        scenario_labels.setdefault(scenario_id, set()).add(expected_ready)
        scenario_counts[scenario_id] += 1
        row["sample_hash"] = sample_hash
        normalized.append(row)
    if not normalized or any(count != 2 for count in scenario_counts.values()):
        raise ValueError("answer support nested scenario pairs are invalid")
    if any(labels != {False, True} for labels in scenario_labels.values()):
        raise ValueError("answer support nested scenario labels are invalid")
    return sorted(normalized, key=lambda row: str(row["sample_id"]))


def _validated_outer_folds(
    fold_plan: Mapping[str, Any],
    *,
    scenario_ids: set[str],
    outer_count: int,
    inner_count: int,
) -> list[dict[str, Any]]:
    folds = nested_support._outer_folds(
        fold_plan, expected_scenarios=scenario_ids
    )
    if len(folds) != outer_count:
        raise ValueError("answer support nested outer fold count is invalid")
    for outer in folds:
        validation = set(outer["validation_scenario_ids"])
        training = scenario_ids - validation
        inner = outer.get("inner_folds")
        if isinstance(inner, (str, bytes)) or not isinstance(inner, Sequence):
            raise TypeError("answer support nested inner folds are invalid")
        inner_sets = [set(row["validation_scenario_ids"]) for row in inner]
        if (
            len(inner_sets) != inner_count
            or set().union(*inner_sets) != training
            or sum(len(values) for values in inner_sets) != len(training)
        ):
            raise ValueError("answer support nested inner fold coverage is invalid")
    return folds


def _profile_scores(
    samples: Sequence[Mapping[str, Any]],
    *,
    profile: Mapping[str, Any],
    scenario_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    fields = profile["feature_fields"]
    weights = profile["weights"]
    return [
        {
            "sample_id": row["sample_id"],
            "expected_ready": row["expected_ready"],
            "score": round(
                sum(float(row["features"][field]) * weights[field] for field in fields),
                12,
            ),
        }
        for row in samples
        if scenario_ids is None or row["scenario_id"] in scenario_ids
    ]


def _profiles(value: object) -> list[dict[str, Any]]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError("answer support nested profiles are invalid")
    profiles = []
    seen = set()
    for raw in value:
        profile = _mapping(raw, "answer support nested profile")
        _exact_mapping(
            profile,
            {"profile_id", "feature_fields", "weights"},
            "answer support nested profile",
        )
        profile_id = _required_text(profile.get("profile_id"), "profile_id")
        fields = profile.get("feature_fields")
        weights = _mapping(profile.get("weights"), "answer support nested weights")
        if (
            isinstance(fields, (str, bytes))
            or not isinstance(fields, Sequence)
            or not fields
            or len(set(fields)) != len(fields)
            or not set(fields) <= set(AVAILABLE_FEATURE_FIELDS)
            or set(weights) != set(fields)
        ):
            raise ValueError("answer support nested profile fields are invalid")
        normalized_weights = {field: _bounded(weights[field], field) for field in fields}
        if not math.isclose(sum(normalized_weights.values()), 1.0, abs_tol=1e-12):
            raise ValueError("answer support nested profile weights are invalid")
        if profile_id in seen:
            raise ValueError("answer support nested profile is duplicated")
        seen.add(profile_id)
        profiles.append(
            {
                "profile_id": profile_id,
                "feature_fields": list(fields),
                "weights": normalized_weights,
            }
        )
    if not profiles:
        raise ValueError("answer support nested profiles are empty")
    return profiles


def _admission(value: object) -> dict[str, Any]:
    admission = _mapping(value, "answer support nested admission")
    expected = {
        "maximum_false_ready_rate",
        "minimum_ready_recall",
        "minimum_package_auc",
        "minimum_outer_fold_balanced_accuracy",
        "maximum_outer_threshold_spread",
        "minimum_profile_selection_fold_count",
        "point_constraints_remain_authoritative",
    }
    if set(admission) != expected:
        raise ValueError("answer support nested admission fields are invalid")
    return {
        "maximum_false_ready_rate": _bounded(
            admission["maximum_false_ready_rate"], "maximum_false_ready_rate"
        ),
        "minimum_ready_recall": _bounded(
            admission["minimum_ready_recall"], "minimum_ready_recall"
        ),
        "minimum_package_auc": _bounded(
            admission["minimum_package_auc"], "minimum_package_auc"
        ),
        "minimum_outer_fold_balanced_accuracy": _bounded(
            admission["minimum_outer_fold_balanced_accuracy"],
            "minimum_outer_fold_balanced_accuracy",
        ),
        "maximum_outer_threshold_spread": _bounded(
            admission["maximum_outer_threshold_spread"],
            "maximum_outer_threshold_spread",
        ),
        "minimum_profile_selection_fold_count": _positive_int(
            admission["minimum_profile_selection_fold_count"],
            "minimum_profile_selection_fold_count",
        ),
        "point_constraints_remain_authoritative": admission[
            "point_constraints_remain_authoritative"
        ],
    }


def _selection_key(value: Mapping[str, Any]) -> tuple[Any, ...]:
    metrics = nested_support._mapping(value.get("metrics"))
    return (
        float(metrics.get("balanced_accuracy", -1.0)),
        float(metrics.get("ready_recall", -1.0)),
        -float(metrics.get("false_ready_rate", 1.0)),
        float(value.get("package_auc", -1.0)),
        -int(value.get("shortlist_index", 10_000)),
    )


def _auc(values: Sequence[Mapping[str, Any]]) -> float:
    positives = [float(row["score"]) for row in values if row["expected_ready"]]
    negatives = [float(row["score"]) for row in values if not row["expected_ready"]]
    if not positives or not negatives:
        raise ValueError("answer support package AUC requires both labels")
    wins = sum(
        1.0 if positive > negative else 0.5 if positive == negative else 0.0
        for positive in positives
        for negative in negatives
    )
    return round(wins / (len(positives) * len(negatives)), 8)


def _find_profile(
    profiles: Sequence[Mapping[str, Any]], profile_id: str
) -> Mapping[str, Any]:
    for profile in profiles:
        if profile["profile_id"] == profile_id:
            return profile
    raise ValueError("answer support nested profile binding is invalid")


def _provider_binding(value: Mapping[str, Any]) -> dict[str, str]:
    binding = _mapping(value, "answer support provider binding")
    if set(binding) != set(PROVIDER_BINDING_FIELDS):
        raise ValueError("answer support provider binding fields are invalid")
    return {
        field: _required_text(binding.get(field), field)
        for field in PROVIDER_BINDING_FIELDS
    }


def _exact_mapping(value: object, fields: set[str], name: str) -> Mapping[str, Any]:
    mapping = _mapping(value, name)
    if set(mapping) != fields:
        raise ValueError(f"{name} fields are invalid")
    return mapping


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} is invalid")
    return value


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is invalid")
    return value.strip()


def _required_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field} is invalid")
    return value


def _bounded(
    value: object, field: str, *, lower: float = 0.0, upper: float = 1.0
) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(float(value))
        or not lower <= float(value) <= upper
    ):
        raise ValueError(f"{field} is invalid")
    return float(value)


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field} is invalid")
    return value
