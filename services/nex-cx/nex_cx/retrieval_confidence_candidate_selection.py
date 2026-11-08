from __future__ import annotations

import itertools
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from nex_runtime.model_calibration import (
    BinaryCalibrationConstraints,
    evaluate_binary_score_calibration,
    evaluate_binary_score_threshold,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

from nex_cx.retrieval_confidence_candidate_diagnostics import (
    CANDIDATE_FEATURE_SAMPLE_SCHEMA_VERSION,
)

CANDIDATE_POLICY_SELECTION_SCHEMA_VERSION = (
    "cx_retrieval_confidence_candidate_policy_selection.v1"
)
CANDIDATE_POLICY_SCHEMA_VERSION = "cx_retrieval_confidence_candidate_policy.v1"
CANDIDATE_POLICY_ID = "cx_calibration_only_candidate_policy_v1"

SELECTABLE_FEATURE_FIELDS = (
    "reranker_top_score",
    "reranker_top_margin",
    "reranker_top2_mean",
    "reranker_second_score",
    "reranker_score_spread",
)
FEATURE_TOLERANCE_MULTIPLIERS = {
    "reranker_top_score": 1.0,
    "reranker_top_margin": 2.0,
    "reranker_top2_mean": 1.0,
    "reranker_second_score": 1.0,
    "reranker_score_spread": 2.0,
}


@dataclass(frozen=True)
class CandidatePolicySelectionConstraints:
    fold_count: int = 5
    grid_step: float = 0.10
    maximum_feature_count: int = 3
    maximum_threshold_spread: float = 0.20
    minimum_fold_balanced_accuracy: float = 0.50
    calibration: BinaryCalibrationConstraints = field(
        default_factory=BinaryCalibrationConstraints
    )

    def __post_init__(self) -> None:
        units = round(1.0 / self.grid_step) if self.grid_step > 0.0 else 0
        if (
            self.fold_count < 2
            or not 0.0 < self.grid_step <= 1.0
            or not math.isclose(units * self.grid_step, 1.0, abs_tol=1e-9)
            or not 1 <= self.maximum_feature_count <= len(SELECTABLE_FEATURE_FIELDS)
            or not 0.0 <= self.maximum_threshold_spread <= 1.0
            or not 0.0 <= self.minimum_fold_balanced_accuracy <= 1.0
        ):
            raise ValueError("candidate policy selection constraints are invalid")


DEFAULT_CANDIDATE_POLICY_CONSTRAINTS = CandidatePolicySelectionConstraints()


def select_and_freeze_candidate_policy(
    samples: Sequence[Mapping[str, Any]],
    *,
    dataset_id: str,
    dataset_sha256: str,
    expected_binding: Mapping[str, Any],
    directional_feature_fields: Sequence[str],
    diagnostic_hash: str,
    repeatability_profile_id: str,
    repeatability_evidence_sha256: str,
    revision_evidence_sha256: str,
    numeric_tolerance: float,
    constraints: CandidatePolicySelectionConstraints = (
        DEFAULT_CANDIDATE_POLICY_CONSTRAINTS
    ),
) -> dict[str, Any]:
    normalized, groups = _normalize_samples(samples)
    features = _normalize_directional_features(directional_feature_fields)
    tolerance = _numeric_tolerance(numeric_tolerance)
    if len(normalized) < constraints.calibration.minimum_sample_count:
        raise ValueError("candidate policy calibration sample count is insufficient")
    if len(groups) < constraints.fold_count:
        raise ValueError("candidate policy calibration group count is insufficient")

    folds = _fold_groups(
        groups, dataset_id=dataset_id, fold_count=constraints.fold_count
    )
    profiles = _candidate_profiles(features, constraints=constraints)
    admissible: list[dict[str, Any]] = []
    best_effort: dict[str, Any] | None = None
    rejection_counts: dict[str, int] = {}
    for feature_fields, weights in profiles:
        candidate = _evaluate_candidate(
            normalized,
            feature_fields=feature_fields,
            weights=weights,
            folds=folds,
            dataset_id=dataset_id,
            numeric_tolerance=tolerance,
            constraints=constraints,
        )
        if best_effort is None or _selection_key(candidate) > _selection_key(
            best_effort
        ):
            best_effort = candidate
        if candidate["status"] == "ADMISSIBLE":
            admissible.append(candidate)
        else:
            code = str(candidate["reason_code"])
            rejection_counts[code] = rejection_counts.get(code, 0) + 1

    selected = max(admissible, key=_selection_key) if admissible else None
    selection_status = "FROZEN" if selected is not None else "NO_ACCEPTABLE_POLICY"
    result: dict[str, Any] = {
        "selection_schema_version": CANDIDATE_POLICY_SELECTION_SCHEMA_VERSION,
        "policy_id": CANDIDATE_POLICY_ID,
        "status": selection_status,
        "reason_code": (
            "CALIBRATION_ONLY_POLICY_FROZEN"
            if selected is not None
            else "GROUP_CV_CONSTRAINTS_NOT_SATISFIED"
        ),
        "runtime_activation_permitted": False,
        "holdout_access_permitted": False,
        "dataset": {
            "dataset_id": _required_string(dataset_id, "dataset_id"),
            "dataset_sha256": _required_string(dataset_sha256, "dataset_sha256"),
            "partition": "CALIBRATION",
            "sample_count": len(normalized),
            "group_count": len(groups),
            "sample_set_hash": semantic_sha256_hash_ref(
                sorted(str(sample["sample_hash"]) for sample in normalized)
            ),
        },
        "binding": _binding(expected_binding),
        "source_evidence": {
            "diagnostic_hash": _hash_ref(diagnostic_hash, "diagnostic_hash"),
            "repeatability_profile_id": _required_string(
                repeatability_profile_id, "repeatability_profile_id"
            ),
            "repeatability_evidence_sha256": _hash_ref(
                repeatability_evidence_sha256, "repeatability_evidence_sha256"
            ),
            "revision_evidence_sha256": _hash_ref(
                revision_evidence_sha256, "revision_evidence_sha256"
            ),
        },
        "repeatability_policy": {
            "base_numeric_tolerance": tolerance,
            "feature_tolerance_multipliers": {
                field: FEATURE_TOLERANCE_MULTIPLIERS[field] for field in features
            },
            "evaluation_mode": "LABEL_ADVERSE_WORST_CASE",
        },
        "search": {
            "directional_feature_fields": list(features),
            "maximum_feature_count": constraints.maximum_feature_count,
            "grid_step": constraints.grid_step,
            "candidate_count": len(profiles),
            "admissible_candidate_count": len(admissible),
            "rejection_counts": dict(sorted(rejection_counts.items())),
        },
        "cross_validation": {
            "fold_count": constraints.fold_count,
            "assignment_hash": semantic_sha256_hash_ref(folds),
            "maximum_threshold_spread": constraints.maximum_threshold_spread,
            "minimum_fold_balanced_accuracy": (
                constraints.minimum_fold_balanced_accuracy
            ),
            "constraints": _constraints_payload(constraints.calibration),
        },
        "selected": _candidate_projection(selected),
        "best_effort": _candidate_projection(best_effort),
        "holdout": {
            "status": "SEALED_NOT_OPENED",
            "threshold_reselected": False,
        },
    }
    if selected is not None:
        result["frozen_policy"] = _freeze_policy(
            selected,
            dataset=result["dataset"],
            binding=result["binding"],
            source_evidence=result["source_evidence"],
            repeatability_policy=result["repeatability_policy"],
            cross_validation=result["cross_validation"],
        )
    else:
        result["frozen_policy"] = None
    result["selection_hash"] = semantic_sha256_hash_ref(result)
    return result


def _evaluate_candidate(
    samples: Sequence[Mapping[str, Any]],
    *,
    feature_fields: tuple[str, ...],
    weights: Mapping[str, float],
    folds: Sequence[Sequence[str]],
    dataset_id: str,
    numeric_tolerance: float,
    constraints: CandidatePolicySelectionConstraints,
) -> dict[str, Any]:
    composite_tolerance = round(
        sum(
            weights[field] * FEATURE_TOLERANCE_MULTIPLIERS[field] * numeric_tolerance
            for field in feature_fields
        ),
        8,
    )
    scored = _score_samples(
        samples,
        feature_fields=feature_fields,
        weights=weights,
        composite_tolerance=composite_tolerance,
    )
    evaluations: list[dict[str, Any]] = []
    for fold_index, validation_groups in enumerate(folds):
        validation_set = set(validation_groups)
        training = [
            row for row in scored if _group_id(row["sample_id"]) not in validation_set
        ]
        validation = [
            row for row in scored if _group_id(row["sample_id"]) in validation_set
        ]
        fit = evaluate_binary_score_calibration(
            training,
            dataset_id=f"{dataset_id}:candidate:fold-{fold_index}:train",
            constraints=constraints.calibration,
        )
        threshold_source = "SELECTED_THRESHOLD"
        threshold_value = fit.get("selected_threshold")
        if threshold_value is None:
            threshold_source = "TRAIN_BEST_EFFORT_THRESHOLD"
            threshold_value = _mapping(fit.get("best_effort_metrics")).get("threshold")
        if threshold_value is None:
            return _rejected_candidate(
                feature_fields,
                weights,
                composite_tolerance,
                "FOLD_TRAINING_THRESHOLD_UNAVAILABLE",
                evaluations,
            )
        threshold = float(threshold_value)
        evaluation = evaluate_binary_score_threshold(
            validation,
            dataset_id=f"{dataset_id}:candidate:fold-{fold_index}:validation",
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
        evaluations.append(
            {
                "fold_index": fold_index,
                "training_group_count": sum(len(fold) for fold in folds)
                - len(validation_groups),
                "validation_group_count": len(validation_groups),
                "threshold": threshold,
                "threshold_source": threshold_source,
                "metrics": evaluation["metrics"],
            }
        )

    aggregate = _aggregate_metrics(evaluations)
    full_fit = evaluate_binary_score_calibration(
        scored,
        dataset_id=f"{dataset_id}:candidate:full-calibration",
        constraints=constraints.calibration,
    )
    if full_fit["status"] != "PASSED":
        return _rejected_candidate(
            feature_fields,
            weights,
            composite_tolerance,
            "FULL_CALIBRATION_THRESHOLD_UNAVAILABLE",
            evaluations,
            oof_metrics=aggregate,
        )
    thresholds = [float(item["threshold"]) for item in evaluations]
    spread = round(max(thresholds) - min(thresholds), 8)
    minimum_fold_accuracy = min(
        float(_mapping(item["metrics"])["balanced_accuracy"]) for item in evaluations
    )
    admissible = (
        aggregate["false_ready_rate"]
        <= constraints.calibration.maximum_false_ready_rate
        and aggregate["ready_recall"] >= constraints.calibration.minimum_ready_recall
        and minimum_fold_accuracy >= constraints.minimum_fold_balanced_accuracy
        and spread <= constraints.maximum_threshold_spread
    )
    return {
        "status": "ADMISSIBLE" if admissible else "REJECTED",
        "reason_code": (
            "GROUP_CV_CONSTRAINTS_SATISFIED"
            if admissible
            else "GROUP_CV_CONSTRAINTS_NOT_SATISFIED"
        ),
        "feature_fields": list(feature_fields),
        "weights": dict(weights),
        "composite_tolerance": composite_tolerance,
        "oof_metrics": aggregate,
        "minimum_fold_balanced_accuracy": round(minimum_fold_accuracy, 8),
        "threshold_spread": spread,
        "folds": evaluations,
        "full_calibration": full_fit,
        "selected_threshold": full_fit["selected_threshold"],
    }


def _score_samples(
    samples: Sequence[Mapping[str, Any]],
    *,
    feature_fields: Sequence[str],
    weights: Mapping[str, float],
    composite_tolerance: float,
) -> list[dict[str, Any]]:
    scored: list[dict[str, Any]] = []
    for sample in samples:
        features = _mapping(sample["features"])
        score = round(
            sum(float(features[field]) * weights[field] for field in feature_fields),
            8,
        )
        expected_ready = bool(sample["expected_ready"])
        robust_score = (
            max(0.0, score - composite_tolerance)
            if expected_ready
            else min(1.0, score + composite_tolerance)
        )
        scored.append(
            {
                "sample_id": sample["sample_id"],
                "expected_ready": expected_ready,
                "score": round(robust_score, 8),
            }
        )
    return scored


def _candidate_profiles(
    features: Sequence[str],
    *,
    constraints: CandidatePolicySelectionConstraints,
) -> list[tuple[tuple[str, ...], dict[str, float]]]:
    total_units = round(1.0 / constraints.grid_step)
    profiles: list[tuple[tuple[str, ...], dict[str, float]]] = []
    for count in range(1, min(constraints.maximum_feature_count, len(features)) + 1):
        for fields in itertools.combinations(features, count):
            for units in _positive_compositions(total_units, count):
                profiles.append(
                    (
                        fields,
                        {
                            field: round(unit * constraints.grid_step, 8)
                            for field, unit in zip(fields, units, strict=True)
                        },
                    )
                )
    return profiles


def _positive_compositions(total: int, count: int) -> list[tuple[int, ...]]:
    if count == 1:
        return [(total,)]
    return [
        (head, *tail)
        for head in range(1, total - count + 2)
        for tail in _positive_compositions(total - head, count - 1)
    ]


def _normalize_samples(
    samples: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    if isinstance(samples, (str, bytes)) or not isinstance(samples, Sequence):
        raise TypeError("candidate policy samples are invalid")
    normalized: list[dict[str, Any]] = []
    labels: dict[str, set[bool]] = {}
    seen: set[str] = set()
    for value in samples:
        if not isinstance(value, Mapping):
            raise TypeError("candidate policy sample is invalid")
        sample = dict(value)
        sample_hash = _hash_ref(sample.pop("sample_hash", None), "sample_hash")
        if sample_hash in seen or sample_hash != semantic_sha256_hash_ref(sample):
            raise ValueError("candidate policy sample integrity is invalid")
        seen.add(sample_hash)
        if (
            sample.get("sample_schema_version")
            != CANDIDATE_FEATURE_SAMPLE_SCHEMA_VERSION
        ):
            raise ValueError("candidate policy sample schema is invalid")
        sample_id = _required_string(sample.get("sample_id"), "sample_id")
        expected_ready = sample.get("expected_ready")
        features = sample.get("features")
        if type(expected_ready) is not bool or not isinstance(features, Mapping):
            raise TypeError("candidate policy sample values are invalid")
        normalized_features = {
            field: _bounded_score(features.get(field), field)
            for field in SELECTABLE_FEATURE_FIELDS
        }
        group_id = _group_id(sample_id)
        labels.setdefault(group_id, set()).add(expected_ready)
        normalized.append(
            {
                "sample_schema_version": CANDIDATE_FEATURE_SAMPLE_SCHEMA_VERSION,
                "sample_id": sample_id,
                "expected_ready": expected_ready,
                "features": normalized_features,
                "sample_hash": sample_hash,
            }
        )
    if any(values != {False, True} for values in labels.values()):
        raise ValueError(
            "each candidate policy group requires positive and negative labels"
        )
    return sorted(normalized, key=lambda row: row["sample_id"]), sorted(labels)


def _normalize_directional_features(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise TypeError("directional feature fields are invalid")
    features = tuple(sorted({_required_string(value, "feature") for value in values}))
    if not features or any(
        field not in SELECTABLE_FEATURE_FIELDS for field in features
    ):
        raise ValueError("directional feature fields are invalid")
    return features


def _fold_groups(
    groups: Sequence[str], *, dataset_id: str, fold_count: int
) -> list[list[str]]:
    ordered = sorted(
        groups,
        key=lambda group: semantic_sha256_hash_ref(
            {"dataset_id": dataset_id, "group_id": group}
        ),
    )
    folds = [[] for _ in range(fold_count)]
    for index, group in enumerate(ordered):
        folds[index % fold_count].append(group)
    if any(not fold for fold in folds):
        raise ValueError("each candidate policy fold requires at least one group")
    return folds


def _aggregate_metrics(folds: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
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
    positives = totals["true_ready"] + totals["false_low_confidence"]
    negatives = totals["false_ready"] + totals["true_low_confidence"]
    predicted_ready = totals["true_ready"] + totals["false_ready"]
    recall = _ratio(totals["true_ready"], positives)
    specificity = _ratio(totals["true_low_confidence"], negatives)
    return {
        **totals,
        "ready_precision": _ratio(totals["true_ready"], predicted_ready),
        "ready_recall": recall,
        "false_ready_rate": _ratio(totals["false_ready"], negatives),
        "balanced_accuracy": round((recall + specificity) / 2.0, 8),
    }


def _rejected_candidate(
    feature_fields: Sequence[str],
    weights: Mapping[str, float],
    composite_tolerance: float,
    reason_code: str,
    folds: Sequence[Mapping[str, Any]],
    *,
    oof_metrics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "status": "REJECTED",
        "reason_code": reason_code,
        "feature_fields": list(feature_fields),
        "weights": dict(weights),
        "composite_tolerance": composite_tolerance,
        "oof_metrics": dict(oof_metrics) if oof_metrics is not None else None,
        "minimum_fold_balanced_accuracy": None,
        "threshold_spread": None,
        "folds": list(folds),
        "full_calibration": None,
        "selected_threshold": None,
    }


def _candidate_projection(candidate: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if candidate is None:
        return None
    return {
        field: candidate.get(field)
        for field in (
            "status",
            "reason_code",
            "feature_fields",
            "weights",
            "composite_tolerance",
            "oof_metrics",
            "minimum_fold_balanced_accuracy",
            "threshold_spread",
            "folds",
            "selected_threshold",
        )
    }


def _selection_key(candidate: Mapping[str, Any]) -> tuple[Any, ...]:
    metrics = _mapping(candidate.get("oof_metrics"))
    fields = tuple(str(field) for field in candidate.get("feature_fields", []))
    weights = _mapping(candidate.get("weights"))
    return (
        candidate.get("status") == "ADMISSIBLE",
        float(metrics.get("balanced_accuracy", -1.0)),
        float(metrics.get("ready_precision", -1.0)),
        float(metrics.get("ready_recall", -1.0)),
        -float(metrics.get("false_ready_rate", 1.0)),
        _number(candidate.get("minimum_fold_balanced_accuracy"), -1.0),
        -_number(candidate.get("threshold_spread"), 1.0),
        -len(fields),
        tuple(-float(weights.get(field, 0.0)) for field in fields),
        tuple(reversed(fields)),
    )


def _freeze_policy(
    candidate: Mapping[str, Any],
    *,
    dataset: object,
    binding: object,
    source_evidence: object,
    repeatability_policy: object,
    cross_validation: object,
) -> dict[str, Any]:
    policy = {
        "policy_schema_version": CANDIDATE_POLICY_SCHEMA_VERSION,
        "policy_id": CANDIDATE_POLICY_ID,
        "version": "1",
        "status": "CANDIDATE_FROZEN",
        "runtime_activation_permitted": False,
        "feature_fields": candidate["feature_fields"],
        "weights": candidate["weights"],
        "threshold": candidate["selected_threshold"],
        "composite_tolerance": candidate["composite_tolerance"],
        "dataset": dataset,
        "binding": binding,
        "source_evidence": source_evidence,
        "repeatability_policy": repeatability_policy,
        "cross_validation": {
            **dict(_mapping(cross_validation)),
            "oof_metrics": candidate["oof_metrics"],
            "minimum_fold_balanced_accuracy": candidate[
                "minimum_fold_balanced_accuracy"
            ],
            "threshold_spread": candidate["threshold_spread"],
        },
        "holdout_status": "SEALED_NOT_OPENED",
    }
    policy["policy_hash"] = semantic_sha256_hash_ref(policy)
    return policy


def _binding(value: Mapping[str, Any]) -> dict[str, str]:
    required = (
        "chunk_policy_id",
        "embedding_model_revision",
        "ranking_policy_id",
        "reranker_model_revision",
        "tokenizer_policy_id",
    )
    if not isinstance(value, Mapping) or any(
        not isinstance(value.get(field), str) or not str(value[field]).strip()
        for field in required
    ):
        raise ValueError("candidate policy binding is invalid")
    return {field: _required_string(value.get(field), field) for field in required}


def _constraints_payload(value: BinaryCalibrationConstraints) -> dict[str, Any]:
    return {
        "minimum_sample_count": value.minimum_sample_count,
        "minimum_positive_count": value.minimum_positive_count,
        "minimum_negative_count": value.minimum_negative_count,
        "maximum_false_ready_rate": value.maximum_false_ready_rate,
        "minimum_ready_recall": value.minimum_ready_recall,
    }


def _group_id(sample_id: str) -> str:
    group, separator, label = sample_id.rpartition(":")
    if not separator or not group or label not in {"positive", "negative"}:
        raise ValueError("sample_id must use '<group>:positive|negative'")
    return group


def _bounded_score(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{field} is invalid")
    score = float(value)
    if not math.isfinite(score) or not 0.0 <= score <= 1.0:
        raise ValueError(f"{field} is invalid")
    return score


def _numeric_tolerance(value: object) -> float:
    tolerance = _bounded_score(value, "numeric_tolerance")
    if tolerance <= 0.0 or tolerance > 0.005:
        raise ValueError("numeric_tolerance is invalid")
    return tolerance


def _hash_ref(value: object, field: str) -> str:
    normalized = _required_string(value, field)
    payload = normalized.removeprefix("sha256:")
    if len(payload) != 64 or any(
        character not in "0123456789abcdef" for character in payload
    ):
        raise ValueError(f"{field} is invalid")
    return f"sha256:{payload}"


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is invalid")
    return value.strip()


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 8) if denominator else 0.0


def _number(value: object, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return default
    return float(value)
