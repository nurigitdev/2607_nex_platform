from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from nex_runtime.model_calibration import (
    BinaryCalibrationConstraints,
    evaluate_binary_score_calibration,
    evaluate_binary_score_threshold,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

import nex_cx.retrieval_calibration_nested_selection as nested_support
from nex_cx.retrieval_package_ready_calibrator import (
    build_package_ordinal_features,
    score_package_ordinal_features,
    validate_package_ordinal_calibrator_design,
)
from nex_cx.retrieval_package_ready_signal import (
    build_package_ready_signal,
    fit_candidate_probability_model,
    score_candidate_relevance_samples,
)

PACKAGE_ORDINAL_NESTED_SELECTION_SCHEMA_VERSION = (
    "cx_retrieval_package_ordinal_nested_selection.v1"
)


def select_nested_package_ordinal_profile(
    samples: Sequence[Mapping[str, Any]],
    *,
    dataset_id: str,
    dataset_sha256: str,
    retrieval_design: Mapping[str, Any],
    fold_plan: Mapping[str, Any],
    ordinal_design: Mapping[str, Any],
    expected_binding: Mapping[str, Any],
) -> dict[str, Any]:
    """Select candidate and package profiles using CALIBRATION folds only."""
    normalized, scenario_ids = nested_support._normalize_samples(samples)
    retrieval_selection = nested_support._mapping(
        retrieval_design.get("selection_protocol")
    )
    admission = nested_support._mapping(retrieval_design.get("admission"))
    candidate_profiles = nested_support._profiles(
        retrieval_selection.get("profile_shortlist")
    )
    package_design = validate_package_ordinal_calibrator_design(ordinal_design)
    package_profiles = package_design["profile_shortlist"]
    outer_folds = nested_support._outer_folds(
        fold_plan, expected_scenarios=scenario_ids
    )
    binding = nested_support._binding(expected_binding)
    constraints = _constraints(admission)
    minimum_candidate_auc = nested_support._score(
        admission.get("minimum_candidate_auc"), "minimum_candidate_auc"
    )

    outer_results: list[dict[str, Any]] = []
    outer_candidates: list[dict[str, Any]] = []
    for outer in outer_folds:
        result, validation_candidates = _evaluate_outer_fold(
            normalized,
            outer=outer,
            candidate_profiles=candidate_profiles,
            package_profiles=package_profiles,
            package_design_hash=package_design["design_hash"],
            constraints=constraints,
            minimum_candidate_auc=minimum_candidate_auc,
            dataset_id=dataset_id,
            expected_binding=binding,
        )
        outer_results.append(result)
        outer_candidates.extend(validation_candidates)

    completed = [row for row in outer_results if row["status"] == "EVALUATED"]
    selected_counts = Counter(str(row["selected_combination_id"]) for row in completed)
    stable_combination_id, stable_count = (
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
    candidate_auc = (
        nested_support._candidate_auc(outer_candidates)
        if outer_candidates
        else None
    )
    checks = {
        "all_outer_folds_evaluated": len(completed) == len(outer_folds),
        "stable_combination_selected": stable_count
        >= nested_support._positive_int(
            admission.get("minimum_profile_selection_fold_count"),
            "minimum_profile_selection_fold_count",
        ),
        "false_ready_rate_within_limit": aggregate is not None
        and aggregate["false_ready_rate"]
        <= float(admission["maximum_false_ready_rate"]),
        "ready_recall_within_limit": aggregate is not None
        and aggregate["ready_recall"] >= float(admission["minimum_ready_recall"]),
        "candidate_auc_within_limit": candidate_auc is not None
        and candidate_auc >= minimum_candidate_auc,
        "minimum_outer_accuracy_within_limit": minimum_outer_accuracy is not None
        and minimum_outer_accuracy
        >= float(admission["minimum_outer_fold_balanced_accuracy"]),
        "outer_threshold_spread_within_limit": threshold_spread is not None
        and threshold_spread <= float(admission["maximum_outer_threshold_spread"]),
    }
    admitted = all(checks.values())
    final_fit = None
    final_probability_model = None
    stable_candidate_profile = None
    stable_package_profile = None
    if admitted and stable_combination_id is not None:
        stable_candidate_id, stable_package_id = _split_combination_id(
            stable_combination_id
        )
        stable_candidate_profile = _find_profile(
            candidate_profiles, stable_candidate_id
        )
        stable_package_profile = _find_profile(package_profiles, stable_package_id)
        final_probability_model, final_features = _fit_probability_and_features(
            normalized,
            candidate_profile=stable_candidate_profile,
            scenario_ids=scenario_ids,
            expected_binding=binding,
            training_scope="CALIBRATION_FULL_ORDINAL_REFIT",
        )
        final_scores = (
            _ordinal_scores(
                final_features,
                package_profile=stable_package_profile,
                design_hash=package_design["design_hash"],
            )
            if final_features is not None
            else None
        )
        if final_scores is not None:
            final_fit = evaluate_binary_score_calibration(
                final_scores,
                dataset_id=f"{dataset_id}:ordinal-nested-selection:full-calibration",
                constraints=constraints,
            )
        if final_fit is None or final_fit["status"] != "PASSED":
            admitted = False
            checks["full_calibration_probability_and_threshold_fitted"] = False
            final_fit = None
            final_probability_model = None
        else:
            checks["full_calibration_probability_and_threshold_fitted"] = True

    result: dict[str, Any] = {
        "selection_schema_version": (
            PACKAGE_ORDINAL_NESTED_SELECTION_SCHEMA_VERSION
        ),
        "status": (
            "CALIBRATION_OOF_ADMITTED" if admitted else "NO_ADMISSIBLE_PROFILE"
        ),
        "reason_code": (
            "PACKAGE_ORDINAL_NESTED_CONSTRAINTS_SATISFIED"
            if admitted
            else "PACKAGE_ORDINAL_NESTED_CONSTRAINTS_NOT_SATISFIED"
        ),
        "runtime_activation_permitted": False,
        "holdout_access_permitted": False,
        "dataset": {
            "dataset_id": nested_support._required_string(dataset_id, "dataset_id"),
            "dataset_sha256": nested_support._required_string(
                dataset_sha256, "dataset_sha256"
            ),
            "partition": "CALIBRATION",
            "scenario_count": len(scenario_ids),
            "package_count": len(scenario_ids) * 2,
            "candidate_count": len(normalized),
            "sample_set_hash": semantic_sha256_hash_ref(
                sorted(str(row["sample_hash"]) for row in normalized)
            ),
        },
        "binding": binding,
        "protocol": {
            "mode": retrieval_selection.get("mode"),
            "candidate_probability_fit_scope": "EACH_INNER_TRAINING_FOLD",
            "package_signal_mode": "DEPENDENCE_ROBUST_ORDINAL_SCORE_V1",
            "package_design_hash": package_design["design_hash"],
            "candidate_profile_shortlist": [
                row["profile_id"] for row in candidate_profiles
            ],
            "package_profile_shortlist": [
                row["profile_id"] for row in package_profiles
            ],
            "combination_count": len(candidate_profiles) * len(package_profiles),
            "outer_fold_count": len(outer_folds),
            "inner_fold_count": retrieval_selection.get("inner_fold_count"),
            "outer_validation_reselection_permitted": False,
            "holdout_selection_permitted": False,
        },
        "outer_folds": outer_results,
        "oof_evaluation": {
            "metrics": aggregate,
            "confidence_intervals": nested_support._confidence_intervals(aggregate),
            "candidate_auc": candidate_auc,
            "minimum_outer_fold_balanced_accuracy": minimum_outer_accuracy,
            "threshold_spread": threshold_spread,
            "combination_selection_counts": dict(sorted(selected_counts.items())),
            "stable_combination_id": stable_combination_id,
            "stable_combination_fold_count": stable_count,
        },
        "checks": checks,
        "selected": (
            {
                "combination_id": stable_combination_id,
                "candidate_profile_id": stable_candidate_profile["profile_id"],
                "package_profile_id": stable_package_profile["profile_id"],
                "threshold": final_fit["selected_threshold"],
                "fit": final_fit,
                "candidate_probability_model": final_probability_model,
                "package_design_hash": package_design["design_hash"],
            }
            if admitted
            and stable_candidate_profile is not None
            and stable_package_profile is not None
            and final_fit is not None
            and final_probability_model is not None
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
    candidate_profiles: Sequence[Mapping[str, Any]],
    package_profiles: Sequence[Mapping[str, Any]],
    package_design_hash: str,
    constraints: BinaryCalibrationConstraints,
    minimum_candidate_auc: float,
    dataset_id: str,
    expected_binding: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    outer_index = int(outer["fold_index"])
    validation_ids = set(outer["validation_scenario_ids"])
    training_ids = {
        nested_support._scenario_id(str(row["sample_id"])) for row in samples
    } - validation_ids
    candidates: list[dict[str, Any]] = []
    for candidate_index, candidate_profile in enumerate(candidate_profiles):
        candidate_auc = nested_support._candidate_auc(
            nested_support._candidate_scores(
                samples,
                profile=candidate_profile,
                scenario_ids=training_ids,
            )
        )
        inner_cache = _inner_feature_cache(
            samples,
            outer=outer,
            outer_index=outer_index,
            training_ids=training_ids,
            candidate_profile=candidate_profile,
            expected_binding=expected_binding,
        )
        for package_index, package_profile in enumerate(package_profiles):
            folds = []
            all_thresholds_available = True
            probability_fit_failures = 0
            for cached in inner_cache:
                if cached["training_features"] is None:
                    all_thresholds_available = False
                    probability_fit_failures += 1
                    continue
                training_scores = _ordinal_scores(
                    cached["training_features"],
                    package_profile=package_profile,
                    design_hash=package_design_hash,
                )
                fit = evaluate_binary_score_calibration(
                    training_scores,
                    dataset_id=(
                        f"{dataset_id}:ordinal:outer-{outer_index}:inner-"
                        f"{cached['fold_index']}:train:"
                        f"{candidate_profile['profile_id']}:"
                        f"{package_profile['profile_id']}"
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
                validation_scores = _ordinal_scores(
                    cached["validation_features"],
                    package_profile=package_profile,
                    design_hash=package_design_hash,
                )
                evaluated = evaluate_binary_score_threshold(
                    validation_scores,
                    dataset_id=(
                        f"{dataset_id}:ordinal:outer-{outer_index}:inner-"
                        f"{cached['fold_index']}:validation"
                    ),
                    threshold=float(threshold),
                    constraints=nested_support._partition_constraints(
                        len(validation_scores), constraints=constraints
                    ),
                )
                folds.append(
                    {
                        "fold_index": cached["fold_index"],
                        "threshold": float(threshold),
                        "threshold_source": (
                            "SELECTED_THRESHOLD"
                            if fit.get("selected_threshold") is not None
                            else "BEST_EFFORT_DIAGNOSTIC_ONLY"
                        ),
                        "candidate_probability_model_hash": cached["model_hash"],
                        "candidate_probability_training_candidate_count": cached[
                            "training_candidate_count"
                        ],
                        "metrics": evaluated["metrics"],
                    }
                )
            metrics = nested_support._aggregate_metrics(
                [nested_support._mapping(row["metrics"]) for row in folds]
            )
            admissible = (
                all_thresholds_available
                and probability_fit_failures == 0
                and len(folds) == len(outer["inner_folds"])
                and metrics is not None
                and metrics["false_ready_rate"]
                <= constraints.maximum_false_ready_rate
                and metrics["ready_recall"] >= constraints.minimum_ready_recall
                and candidate_auc >= minimum_candidate_auc
            )
            candidates.append(
                {
                    "combination_id": _combination_id(
                        candidate_profile["profile_id"],
                        package_profile["profile_id"],
                    ),
                    "candidate_profile_id": candidate_profile["profile_id"],
                    "package_profile_id": package_profile["profile_id"],
                    "shortlist_index": (
                        candidate_index * len(package_profiles) + package_index
                    ),
                    "status": "ADMISSIBLE" if admissible else "REJECTED",
                    "metrics": metrics,
                    "candidate_auc": candidate_auc,
                    "probability_fit_failures": probability_fit_failures,
                    "inner_folds": folds,
                }
            )

    admissible = [row for row in candidates if row["status"] == "ADMISSIBLE"]
    if not admissible:
        return (
            {
                "fold_index": outer_index,
                "status": "NO_ADMISSIBLE_PROFILE",
                "selected_combination_id": None,
                "threshold": None,
                "metrics": None,
                "inner_selection": candidates,
            },
            [],
        )
    selected = max(admissible, key=_selection_key)
    selected_candidate = _find_profile(
        candidate_profiles, str(selected["candidate_profile_id"])
    )
    selected_package = _find_profile(
        package_profiles, str(selected["package_profile_id"])
    )
    probability_model, training_features = _fit_probability_and_features(
        samples,
        candidate_profile=selected_candidate,
        scenario_ids=training_ids,
        expected_binding=expected_binding,
        training_scope=f"CALIBRATION_OUTER_{outer_index}_ORDINAL_REFIT",
    )
    if training_features is None:
        return (
            {
                "fold_index": outer_index,
                "status": "OUTER_PROBABILITY_REFIT_FAILED",
                "selected_combination_id": selected["combination_id"],
                "threshold": None,
                "metrics": None,
                "inner_selection": candidates,
            },
            [],
        )
    fit = evaluate_binary_score_calibration(
        _ordinal_scores(
            training_features,
            package_profile=selected_package,
            design_hash=package_design_hash,
        ),
        dataset_id=f"{dataset_id}:ordinal:outer-{outer_index}:refit",
        constraints=constraints,
    )
    threshold = fit.get("selected_threshold")
    if threshold is None:
        return (
            {
                "fold_index": outer_index,
                "status": "OUTER_REFIT_FAILED",
                "selected_combination_id": selected["combination_id"],
                "threshold": None,
                "metrics": None,
                "inner_selection": candidates,
            },
            [],
        )
    validation_features = _ordinal_feature_rows(
        samples,
        candidate_profile=selected_candidate,
        scenario_ids=validation_ids,
        probability_model=probability_model,
        expected_binding=expected_binding,
    )
    evaluation = evaluate_binary_score_threshold(
        _ordinal_scores(
            validation_features,
            package_profile=selected_package,
            design_hash=package_design_hash,
        ),
        dataset_id=f"{dataset_id}:ordinal:outer-{outer_index}:validation",
        threshold=float(threshold),
        constraints=nested_support._partition_constraints(
            len(validation_features), constraints=constraints
        ),
    )
    return (
        {
            "fold_index": outer_index,
            "status": "EVALUATED",
            "selected_combination_id": selected["combination_id"],
            "candidate_profile_id": selected_candidate["profile_id"],
            "package_profile_id": selected_package["profile_id"],
            "threshold": float(threshold),
            "candidate_probability_model_hash": probability_model["model_hash"],
            "candidate_probability_training_candidate_count": probability_model[
                "training"
            ]["candidate_count"],
            "metrics": evaluation["metrics"],
            "confidence_intervals": evaluation["confidence_intervals"],
            "inner_selection": candidates,
        },
        nested_support._candidate_scores(
            samples,
            profile=selected_candidate,
            scenario_ids=validation_ids,
        ),
    )


def _inner_feature_cache(
    samples: Sequence[Mapping[str, Any]],
    *,
    outer: Mapping[str, Any],
    outer_index: int,
    training_ids: set[str],
    candidate_profile: Mapping[str, Any],
    expected_binding: Mapping[str, Any],
) -> list[dict[str, Any]]:
    cached = []
    for inner in outer["inner_folds"]:
        validation_ids = set(inner["validation_scenario_ids"])
        inner_training_ids = training_ids - validation_ids
        model, training_features = _fit_probability_and_features(
            samples,
            candidate_profile=candidate_profile,
            scenario_ids=inner_training_ids,
            expected_binding=expected_binding,
            training_scope=(
                f"CALIBRATION_OUTER_{outer_index}_INNER_"
                f"{inner['fold_index']}_ORDINAL_TRAINING"
            ),
        )
        validation_features = (
            _ordinal_feature_rows(
                samples,
                candidate_profile=candidate_profile,
                scenario_ids=validation_ids,
                probability_model=model,
                expected_binding=expected_binding,
            )
            if training_features is not None
            else None
        )
        cached.append(
            {
                "fold_index": inner["fold_index"],
                "model_hash": model["model_hash"],
                "training_candidate_count": model["training"]["candidate_count"],
                "training_features": training_features,
                "validation_features": validation_features,
            }
        )
    return cached


def _fit_probability_and_features(
    samples: Sequence[Mapping[str, Any]],
    *,
    candidate_profile: Mapping[str, Any],
    scenario_ids: set[str],
    expected_binding: Mapping[str, Any],
    training_scope: str,
) -> tuple[dict[str, Any], list[dict[str, Any]] | None]:
    subset = nested_support._sample_subset(samples, scenario_ids=scenario_ids)
    scored = score_candidate_relevance_samples(
        subset,
        profile=nested_support._probability_profile(candidate_profile),
    )
    model = fit_candidate_probability_model(
        scored,
        source_profile_id=str(candidate_profile["profile_id"]),
        expected_binding=expected_binding,
        training_scope=training_scope,
    )
    if model["status"] != "CALIBRATION_ONLY_FITTED":
        return model, None
    return (
        model,
        _ordinal_feature_rows(
            subset,
            candidate_profile=candidate_profile,
            scenario_ids=scenario_ids,
            probability_model=model,
            expected_binding=expected_binding,
        ),
    )


def _ordinal_feature_rows(
    samples: Sequence[Mapping[str, Any]],
    *,
    candidate_profile: Mapping[str, Any],
    scenario_ids: set[str],
    probability_model: Mapping[str, Any],
    expected_binding: Mapping[str, Any],
) -> list[dict[str, Any]]:
    subset = nested_support._sample_subset(samples, scenario_ids=scenario_ids)
    scored = score_candidate_relevance_samples(
        subset,
        profile=nested_support._probability_profile(candidate_profile),
    )
    labels = {str(row["sample_id"]): bool(row["expected_ready"]) for row in subset}
    packages: dict[str, list[dict[str, Any]]] = {}
    for row in scored:
        packages.setdefault(str(row["sample_id"]), []).append(
            {
                "candidate_id": row["candidate_id"],
                "candidate_score": row["candidate_score"],
            }
        )
    return [
        {
            "sample_id": sample_id,
            "expected_ready": labels[sample_id],
            "feature_vector": build_package_ordinal_features(
                build_package_ready_signal(
                    candidates,
                    model=probability_model,
                    expected_binding=expected_binding,
                )
            ),
        }
        for sample_id, candidates in sorted(packages.items())
    ]


def _ordinal_scores(
    feature_rows: Sequence[Mapping[str, Any]],
    *,
    package_profile: Mapping[str, Any],
    design_hash: str,
) -> list[dict[str, Any]]:
    return [
        {
            "sample_id": row["sample_id"],
            "expected_ready": row["expected_ready"],
            "score": score_package_ordinal_features(
                row["feature_vector"],
                profile=package_profile,
                design_hash=design_hash,
            )["ordinal_score"],
        }
        for row in feature_rows
    ]


def _constraints(admission: Mapping[str, Any]) -> BinaryCalibrationConstraints:
    return BinaryCalibrationConstraints(
        maximum_false_ready_rate=nested_support._score(
            admission.get("maximum_false_ready_rate"),
            "maximum_false_ready_rate",
        ),
        minimum_ready_recall=nested_support._score(
            admission.get("minimum_ready_recall"), "minimum_ready_recall"
        ),
    )


def _selection_key(value: Mapping[str, Any]) -> tuple[Any, ...]:
    metrics = nested_support._mapping(value.get("metrics"))
    return (
        float(metrics.get("balanced_accuracy", -1.0)),
        float(metrics.get("ready_recall", -1.0)),
        -float(metrics.get("false_ready_rate", 1.0)),
        float(value.get("candidate_auc", -1.0)),
        -int(value.get("shortlist_index", 10_000)),
    )


def _combination_id(candidate_profile_id: str, package_profile_id: str) -> str:
    return f"{candidate_profile_id}::{package_profile_id}"


def _split_combination_id(value: str) -> tuple[str, str]:
    candidate_id, separator, package_id = value.partition("::")
    if not separator or not candidate_id or not package_id:
        raise ValueError("package ordinal combination id is invalid")
    return candidate_id, package_id


def _find_profile(
    profiles: Sequence[Mapping[str, Any]], profile_id: str
) -> Mapping[str, Any]:
    for profile in profiles:
        if profile.get("profile_id") == profile_id:
            return profile
    raise ValueError("package ordinal profile binding is invalid")
