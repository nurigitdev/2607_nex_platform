from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from nex_runtime.model_calibration import (
    BinaryCalibrationConstraints,
    evaluate_binary_score_threshold,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

from nex_cx.retrieval_confidence_calibration import RetrievalConfidenceWeights
from nex_cx.retrieval_confidence_multisignal import (
    WEIGHTED_FEATURE_FIELDS,
    evaluate_multisignal_calibration,
    reweight_multisignal_feature_package,
)

WEIGHT_SELECTION_SCHEMA_VERSION = "cx_retrieval_confidence_weight_selection.v1"
WEIGHT_SELECTION_POLICY_ID = "cx_multisignal_group_cv_grid_v1"
DEFAULT_FOLD_COUNT = 5
DEFAULT_GRID_STEP = 0.05
DEFAULT_MIN_FEATURE_WEIGHT = 0.05
DEFAULT_MAX_FEATURE_WEIGHT = 0.70
DEFAULT_MAX_THRESHOLD_SPREAD = 0.20
DEFAULT_MIN_FOLD_BALANCED_ACCURACY = 0.50


@dataclass(frozen=True)
class MultiSignalWeightSelectionConstraints:
    fold_count: int = DEFAULT_FOLD_COUNT
    grid_step: float = DEFAULT_GRID_STEP
    minimum_feature_weight: float = DEFAULT_MIN_FEATURE_WEIGHT
    maximum_feature_weight: float = DEFAULT_MAX_FEATURE_WEIGHT
    minimum_reranker_weight: float = 0.30
    minimum_retrieval_weight: float = 0.20
    maximum_threshold_spread: float = DEFAULT_MAX_THRESHOLD_SPREAD
    minimum_fold_balanced_accuracy: float = DEFAULT_MIN_FOLD_BALANCED_ACCURACY
    calibration: BinaryCalibrationConstraints = field(
        default_factory=BinaryCalibrationConstraints
    )

    def __post_init__(self) -> None:
        if (
            self.fold_count < 2
            or self.grid_step <= 0.0
            or self.grid_step > 1.0
            or self.minimum_feature_weight < 0.0
            or self.maximum_feature_weight > 1.0
            or self.minimum_feature_weight > self.maximum_feature_weight
            or not 0.0 <= self.minimum_reranker_weight <= 1.0
            or not 0.0 <= self.minimum_retrieval_weight <= 1.0
            or not 0.0 <= self.maximum_threshold_spread <= 1.0
            or not 0.0 <= self.minimum_fold_balanced_accuracy <= 1.0
        ):
            raise ValueError("multi-signal weight selection constraints are invalid")
        units = round(1.0 / self.grid_step)
        if not math.isclose(units * self.grid_step, 1.0, abs_tol=1e-9):
            raise ValueError("weight grid step must divide one exactly")


DEFAULT_WEIGHT_SELECTION_CONSTRAINTS = MultiSignalWeightSelectionConstraints()


def select_multisignal_calibration_weights(
    samples: Sequence[Mapping[str, Any]],
    *,
    dataset_id: str,
    dataset_sha256: str,
    expected_binding: Mapping[str, Any],
    constraints: MultiSignalWeightSelectionConstraints = (
        DEFAULT_WEIGHT_SELECTION_CONSTRAINTS
    ),
) -> dict[str, Any]:
    normalized, groups = _normalize_grouped_samples(samples)
    if len(normalized) < constraints.calibration.minimum_sample_count:
        raise ValueError("multi-signal calibration sample count is insufficient")
    if len(groups) < constraints.fold_count:
        raise ValueError("multi-signal calibration group count is insufficient")
    fold_groups = _fold_groups(
        groups,
        dataset_id=dataset_id,
        fold_count=constraints.fold_count,
    )
    candidates = _weight_grid(constraints)
    evaluated: list[dict[str, Any]] = []
    admissible: list[dict[str, Any]] = []
    for weights in candidates:
        evaluation = _evaluate_candidate(
            normalized,
            weights=weights,
            fold_groups=fold_groups,
            dataset_id=dataset_id,
            dataset_sha256=dataset_sha256,
            expected_binding=expected_binding,
            constraints=constraints,
        )
        evaluated.append(evaluation)
        if evaluation["status"] == "ADMISSIBLE":
            admissible.append(evaluation)

    selected = max(admissible, key=_selection_key) if admissible else None
    best_effort = max(evaluated, key=_selection_key) if evaluated else None
    result: dict[str, Any] = {
        "weight_selection_schema_version": WEIGHT_SELECTION_SCHEMA_VERSION,
        "policy_id": WEIGHT_SELECTION_POLICY_ID,
        "status": (
            "SELECTED" if selected is not None else "NO_ACCEPTABLE_WEIGHT_PROFILE"
        ),
        "reason_code": (
            "GROUP_CV_WEIGHT_PROFILE_SELECTED"
            if selected is not None
            else "GROUP_CV_CONSTRAINTS_NOT_SATISFIED"
        ),
        "runtime_activation_permitted": False,
        "dataset": {
            "dataset_id": dataset_id,
            "dataset_sha256": dataset_sha256,
            "partition": "CALIBRATION",
            "sample_count": len(normalized),
            "group_count": len(groups),
        },
        "grid": {
            "step": constraints.grid_step,
            "minimum_feature_weight": constraints.minimum_feature_weight,
            "maximum_feature_weight": constraints.maximum_feature_weight,
            "minimum_reranker_weight": constraints.minimum_reranker_weight,
            "minimum_retrieval_weight": constraints.minimum_retrieval_weight,
            "candidate_count": len(candidates),
            "admissible_candidate_count": len(admissible),
        },
        "cross_validation": {
            "fold_count": constraints.fold_count,
            "assignment_hash": semantic_sha256_hash_ref(fold_groups),
            "maximum_threshold_spread": constraints.maximum_threshold_spread,
            "minimum_fold_balanced_accuracy": (
                constraints.minimum_fold_balanced_accuracy
            ),
        },
        "selected": _candidate_projection(selected),
        "best_effort": _candidate_projection(best_effort),
    }
    result["selection_hash"] = semantic_sha256_hash_ref(result)
    return result


def apply_multisignal_weights(
    samples: Sequence[Mapping[str, Any]],
    *,
    weights: Mapping[str, Any],
) -> list[dict[str, Any]]:
    profile = _weight_profile(weights)
    rebuilt: list[dict[str, Any]] = []
    for sample in samples:
        if not isinstance(sample, Mapping):
            raise TypeError("multi-signal calibration sample is invalid")
        sample_id = _required_string(sample.get("sample_id"), "sample_id")
        expected_ready = sample.get("expected_ready")
        feature_package = sample.get("feature_package")
        if not isinstance(expected_ready, bool) or not isinstance(
            feature_package, Mapping
        ):
            raise TypeError("multi-signal calibration sample is invalid")
        rebuilt.append(
            {
                "sample_id": sample_id,
                "expected_ready": expected_ready,
                "feature_package": reweight_multisignal_feature_package(
                    feature_package,
                    weights=profile,
                ),
            }
        )
    return rebuilt


def _evaluate_candidate(
    samples: Sequence[Mapping[str, Any]],
    *,
    weights: RetrievalConfidenceWeights,
    fold_groups: Sequence[Sequence[str]],
    dataset_id: str,
    dataset_sha256: str,
    expected_binding: Mapping[str, Any],
    constraints: MultiSignalWeightSelectionConstraints,
) -> dict[str, Any]:
    reweighted = apply_multisignal_weights(samples, weights=weights.to_wire())
    fold_evaluations: list[dict[str, Any]] = []
    for fold_index, validation_groups in enumerate(fold_groups):
        validation_group_set = set(validation_groups)
        training = [
            sample
            for sample in reweighted
            if _group_id(str(sample["sample_id"])) not in validation_group_set
        ]
        validation = [
            sample
            for sample in reweighted
            if _group_id(str(sample["sample_id"])) in validation_group_set
        ]
        training_evaluation = evaluate_multisignal_calibration(
            training,
            dataset_id=f"{dataset_id}:weight-selection:fold-{fold_index}:train",
            dataset_sha256=dataset_sha256,
            expected_binding=expected_binding,
            constraints=constraints.calibration,
        )
        nested = _mapping(training_evaluation.get("evaluation"))
        threshold_source = "SELECTED_THRESHOLD"
        threshold_value = nested.get("selected_threshold")
        if threshold_value is None:
            threshold_source = "TRAIN_BEST_EFFORT_THRESHOLD"
            threshold_value = _mapping(nested.get("best_effort_metrics")).get(
                "threshold"
            )
        if threshold_value is None:
            return _rejected_candidate(
                weights,
                "FOLD_TRAINING_THRESHOLD_UNAVAILABLE",
                fold_evaluations,
            )
        threshold = float(threshold_value)
        validation_evaluation = evaluate_binary_score_threshold(
            _scored_samples(validation),
            dataset_id=(f"{dataset_id}:weight-selection:fold-{fold_index}:validation"),
            threshold=threshold,
            constraints=BinaryCalibrationConstraints(
                minimum_sample_count=len(validation),
                minimum_positive_count=len(validation) // 2,
                minimum_negative_count=len(validation) // 2,
                maximum_false_ready_rate=(
                    constraints.calibration.maximum_false_ready_rate
                ),
                minimum_ready_recall=constraints.calibration.minimum_ready_recall,
            ),
        )
        fold_evaluations.append(
            {
                "fold_index": fold_index,
                "training_group_count": (
                    sum(len(groups) for groups in fold_groups) - len(validation_groups)
                ),
                "validation_group_count": len(validation_groups),
                "threshold": threshold,
                "threshold_source": threshold_source,
                "metrics": validation_evaluation["metrics"],
            }
        )

    aggregate = _aggregate_fold_metrics(fold_evaluations)
    full_calibration = evaluate_multisignal_calibration(
        reweighted,
        dataset_id=dataset_id,
        dataset_sha256=dataset_sha256,
        expected_binding=expected_binding,
        constraints=constraints.calibration,
    )
    thresholds = [float(item["threshold"]) for item in fold_evaluations]
    threshold_spread = round(max(thresholds) - min(thresholds), 8)
    minimum_fold_accuracy = min(
        float(_mapping(item["metrics"])["balanced_accuracy"])
        for item in fold_evaluations
    )
    admissible = (
        full_calibration.get("status") == "PASSED"
        and aggregate["false_ready_rate"]
        <= constraints.calibration.maximum_false_ready_rate
        and aggregate["ready_recall"] >= constraints.calibration.minimum_ready_recall
        and minimum_fold_accuracy >= constraints.minimum_fold_balanced_accuracy
        and threshold_spread <= constraints.maximum_threshold_spread
    )
    return {
        "status": "ADMISSIBLE" if admissible else "REJECTED",
        "reason_code": (
            "GROUP_CV_CONSTRAINTS_SATISFIED"
            if admissible
            else "GROUP_CV_CONSTRAINTS_NOT_SATISFIED"
        ),
        "weights": weights.to_wire(),
        "oof_metrics": aggregate,
        "minimum_fold_balanced_accuracy": round(minimum_fold_accuracy, 8),
        "threshold_spread": threshold_spread,
        "folds": fold_evaluations,
        "calibration": full_calibration,
    }


def _normalize_grouped_samples(
    samples: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    if isinstance(samples, (str, bytes)) or not isinstance(samples, Sequence):
        raise TypeError("multi-signal calibration samples are invalid")
    normalized: list[dict[str, Any]] = []
    labels: dict[str, set[bool]] = {}
    seen: set[str] = set()
    for sample in samples:
        if not isinstance(sample, Mapping):
            raise TypeError("multi-signal calibration sample is invalid")
        sample_id = _required_string(sample.get("sample_id"), "sample_id")
        if sample_id in seen:
            raise ValueError("multi-signal calibration sample IDs must be unique")
        seen.add(sample_id)
        expected_ready = sample.get("expected_ready")
        feature_package = sample.get("feature_package")
        if not isinstance(expected_ready, bool) or not isinstance(
            feature_package, Mapping
        ):
            raise TypeError("multi-signal calibration sample is invalid")
        group_id = _group_id(sample_id)
        labels.setdefault(group_id, set()).add(expected_ready)
        normalized.append(
            {
                "sample_id": sample_id,
                "expected_ready": expected_ready,
                "feature_package": dict(feature_package),
            }
        )
    if any(values != {False, True} for values in labels.values()):
        raise ValueError("each calibration group requires positive and negative labels")
    return sorted(normalized, key=lambda item: item["sample_id"]), sorted(labels)


def _fold_groups(
    groups: Sequence[str],
    *,
    dataset_id: str,
    fold_count: int,
) -> list[list[str]]:
    ordered = sorted(
        groups,
        key=lambda group_id: semantic_sha256_hash_ref(
            {"dataset_id": dataset_id, "group_id": group_id}
        ),
    )
    folds = [[] for _ in range(fold_count)]
    for index, group_id in enumerate(ordered):
        folds[index % fold_count].append(group_id)
    if any(not fold for fold in folds):
        raise ValueError("each calibration fold requires at least one group")
    return folds


def _weight_grid(
    constraints: MultiSignalWeightSelectionConstraints,
) -> list[RetrievalConfidenceWeights]:
    total_units = round(1.0 / constraints.grid_step)
    minimum_units = round(constraints.minimum_feature_weight / constraints.grid_step)
    maximum_units = round(constraints.maximum_feature_weight / constraints.grid_step)
    minimum_reranker_units = round(
        constraints.minimum_reranker_weight / constraints.grid_step
    )
    minimum_retrieval_units = round(
        constraints.minimum_retrieval_weight / constraints.grid_step
    )
    profiles: list[RetrievalConfidenceWeights] = []
    for reranker_score in range(minimum_units, maximum_units + 1):
        for reranker_margin in range(minimum_units, maximum_units + 1):
            for rrf_score in range(minimum_units, maximum_units + 1):
                channel = total_units - reranker_score - reranker_margin - rrf_score
                if not minimum_units <= channel <= maximum_units:
                    continue
                if reranker_score + reranker_margin < minimum_reranker_units:
                    continue
                if rrf_score + channel < minimum_retrieval_units:
                    continue
                profiles.append(
                    RetrievalConfidenceWeights(
                        reranker_score=round(reranker_score * constraints.grid_step, 8),
                        reranker_margin=round(
                            reranker_margin * constraints.grid_step, 8
                        ),
                        rrf_normalized_score=round(
                            rrf_score * constraints.grid_step, 8
                        ),
                        channel_support=round(channel * constraints.grid_step, 8),
                    )
                )
    return profiles


def _aggregate_fold_metrics(
    folds: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    totals = {
        "true_ready": 0,
        "false_low_confidence": 0,
        "false_ready": 0,
        "true_low_confidence": 0,
    }
    for fold in folds:
        metrics = _mapping(fold.get("metrics"))
        for metric_name in totals:
            totals[metric_name] += int(metrics[metric_name])
    positive = totals["true_ready"] + totals["false_low_confidence"]
    negative = totals["false_ready"] + totals["true_low_confidence"]
    predicted_ready = totals["true_ready"] + totals["false_ready"]
    recall = _ratio(totals["true_ready"], positive)
    specificity = _ratio(totals["true_low_confidence"], negative)
    return {
        **totals,
        "ready_precision": _ratio(totals["true_ready"], predicted_ready),
        "ready_recall": recall,
        "false_ready_rate": _ratio(totals["false_ready"], negative),
        "balanced_accuracy": round((recall + specificity) / 2.0, 8),
    }


def _candidate_projection(candidate: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if candidate is None:
        return None
    calibration = _mapping(candidate.get("calibration"))
    evaluation = _mapping(calibration.get("evaluation"))
    return {
        "status": candidate.get("status"),
        "reason_code": candidate.get("reason_code"),
        "weights": candidate.get("weights"),
        "oof_metrics": candidate.get("oof_metrics"),
        "minimum_fold_balanced_accuracy": candidate.get(
            "minimum_fold_balanced_accuracy"
        ),
        "threshold_spread": candidate.get("threshold_spread"),
        "folds": candidate.get("folds"),
        "calibration": calibration,
        "selected_threshold": evaluation.get("selected_threshold"),
    }


def _rejected_candidate(
    weights: RetrievalConfidenceWeights,
    reason_code: str,
    folds: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "status": "REJECTED",
        "reason_code": reason_code,
        "weights": weights.to_wire(),
        "oof_metrics": None,
        "minimum_fold_balanced_accuracy": None,
        "threshold_spread": None,
        "folds": list(folds),
        "calibration": None,
    }


def _selection_key(candidate: Mapping[str, Any]) -> tuple[Any, ...]:
    metrics = _mapping(candidate.get("oof_metrics"))
    weights = _mapping(candidate.get("weights"))
    baseline = {
        "reranker_score": 0.20,
        "reranker_margin": 0.10,
        "rrf_normalized_score": 0.40,
        "channel_support": 0.30,
    }
    distance = sum(
        abs(float(weights.get(field, 0.0)) - baseline[field])
        for field in WEIGHTED_FEATURE_FIELDS
    )
    return (
        candidate.get("status") == "ADMISSIBLE",
        float(metrics.get("balanced_accuracy", -1.0)),
        float(metrics.get("ready_precision", -1.0)),
        float(metrics.get("ready_recall", -1.0)),
        -float(metrics.get("false_ready_rate", 1.0)),
        _number_or_default(candidate.get("minimum_fold_balanced_accuracy"), -1.0),
        -_number_or_default(candidate.get("threshold_spread"), 1.0),
        -round(distance, 8),
        tuple(float(weights.get(field, 0.0)) for field in WEIGHTED_FEATURE_FIELDS),
    )


def _scored_samples(samples: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "sample_id": sample["sample_id"],
            "expected_ready": sample["expected_ready"],
            "score": _mapping(sample["feature_package"])["features"][  # type: ignore[index]
                "composite_score"
            ],
        }
        for sample in samples
    ]


def _weight_profile(weights: Mapping[str, Any]) -> RetrievalConfidenceWeights:
    if set(weights) != set(WEIGHTED_FEATURE_FIELDS):
        raise ValueError("multi-signal weight profile is invalid")
    return RetrievalConfidenceWeights(
        reranker_score=weights["reranker_score"],
        reranker_margin=weights["reranker_margin"],
        rrf_normalized_score=weights["rrf_normalized_score"],
        channel_support=weights["channel_support"],
    )


def _group_id(sample_id: str) -> str:
    group_id, separator, label = sample_id.rpartition(":")
    if not separator or not group_id or label not in {"positive", "negative"}:
        raise ValueError("sample_id must use '<group>:positive|negative'")
    return group_id


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is invalid")
    return value.strip()


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 8) if denominator else 0.0


def _number_or_default(value: object, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return default
    return float(value)
