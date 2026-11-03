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
    CANDIDATE_RELEVANCE_SAMPLE_SCHEMA_VERSION,
    CANDIDATE_SIGNAL_FIELDS,
    EXPANDED_CANDIDATE_RELEVANCE_SAMPLE_SCHEMA_VERSION,
    EXPANDED_CANDIDATE_SIGNAL_FIELDS,
)

CANDIDATE_RELEVANCE_CALIBRATION_SCHEMA_VERSION = (
    "cx_candidate_relevance_calibration.v1"
)
CANDIDATE_RELEVANCE_POLICY_SCHEMA_VERSION = "cx_candidate_relevance_policy.v1"
CANDIDATE_RELEVANCE_POLICY_ID = "cx_candidate_relevance_two_evidence_v1"
EXPANDED_CANDIDATE_RELEVANCE_POLICY_ID = (
    "cx_candidate_relevance_expanded_channel_scores_v1"
)


@dataclass(frozen=True)
class CandidateRelevanceConstraints:
    fold_count: int = 5
    grid_step: float = 0.10
    maximum_feature_count: int = 3
    minimum_candidate_auc: float = 0.70
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
            or not 1
            <= self.maximum_feature_count
            <= len(EXPANDED_CANDIDATE_SIGNAL_FIELDS)
            or not 0.5 <= self.minimum_candidate_auc <= 1.0
            or not 0.0 <= self.maximum_threshold_spread <= 1.0
            or not 0.0 <= self.minimum_fold_balanced_accuracy <= 1.0
        ):
            raise ValueError("candidate relevance constraints are invalid")


DEFAULT_CANDIDATE_RELEVANCE_CONSTRAINTS = CandidateRelevanceConstraints()


def calibrate_candidate_relevance_policy(
    samples: Sequence[Mapping[str, Any]],
    *,
    dataset_id: str,
    dataset_sha256: str,
    expected_binding: Mapping[str, Any],
    pipeline_repeatability: Mapping[str, Any],
    numeric_tolerance: float,
    constraints: CandidateRelevanceConstraints = (
        DEFAULT_CANDIDATE_RELEVANCE_CONSTRAINTS
    ),
    signal_fields: Sequence[str] = CANDIDATE_SIGNAL_FIELDS,
    policy_id: str = CANDIDATE_RELEVANCE_POLICY_ID,
    signal_tolerances: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Calibrate candidate relevance before deriving package readiness."""
    admitted_signal_fields = _signal_fields(signal_fields, constraints=constraints)
    admitted_policy_id = _required_string(policy_id, "policy_id")
    normalized, groups, packages = _normalize_samples(
        samples,
        signal_fields=admitted_signal_fields,
    )
    tolerance = _tolerance(numeric_tolerance)
    admitted_tolerances = _signal_tolerances(
        admitted_signal_fields,
        reranker_tolerance=tolerance,
        values=signal_tolerances,
    )
    folds = _fold_groups(groups, dataset_id=dataset_id, count=constraints.fold_count)
    profiles = _profiles(constraints, signal_fields=admitted_signal_fields)
    signal_diagnostics = {
        field: {
            "candidate_auc": _auc(
                _score_candidates(
                    normalized,
                    feature_fields=(field,),
                    weights={field: 1.0},
                    numeric_tolerance=0.0,
                )
            )
        }
        for field in admitted_signal_fields
    }
    candidates = [
        _evaluate_profile(
            normalized,
            packages=packages,
            feature_fields=fields,
            weights=weights,
            folds=folds,
            dataset_id=dataset_id,
            numeric_tolerance=tolerance,
            signal_tolerances=admitted_tolerances,
            constraints=constraints,
        )
        for fields, weights in profiles
    ]
    admissible = [row for row in candidates if row["status"] == "ADMISSIBLE"]
    selected = max(admissible, key=_selection_key) if admissible else None
    best_effort = max(candidates, key=_selection_key)
    pipeline_stable = pipeline_repeatability.get("status") == "STABLE"
    frozen = selected is not None and pipeline_stable
    if not pipeline_stable:
        status = "PIPELINE_UNSTABLE"
        reason = "FULL_PIPELINE_REPEATABILITY_NOT_SATISFIED"
    elif selected is None:
        status = "NO_ACCEPTABLE_POLICY"
        reason = "CANDIDATE_RELEVANCE_CONSTRAINTS_NOT_SATISFIED"
    else:
        status = "FROZEN"
        reason = "CANDIDATE_RELEVANCE_POLICY_FROZEN"
    result: dict[str, Any] = {
        "calibration_schema_version": CANDIDATE_RELEVANCE_CALIBRATION_SCHEMA_VERSION,
        "policy_id": admitted_policy_id,
        "status": status,
        "reason_code": reason,
        "runtime_activation_permitted": False,
        "holdout_access_permitted": False,
        "dataset": {
            "dataset_id": _required_string(dataset_id, "dataset_id"),
            "dataset_sha256": _required_string(dataset_sha256, "dataset_sha256"),
            "partition": "CALIBRATION",
            "scenario_count": len(groups),
            "package_count": len(packages),
            "candidate_count": len(normalized),
            "sample_set_hash": semantic_sha256_hash_ref(
                sorted(str(row["sample_hash"]) for row in normalized)
            ),
        },
        "binding": _binding(expected_binding),
        "semantics": {
            "candidate_score_meaning": "RELEVANCE_LIKELIHOOD_PROXY",
            "package_score": "SECOND_HIGHEST_CANDIDATE_SCORE",
            "ready_meaning": "AT_LEAST_TWO_RELEVANT_CANDIDATES",
            "candidate_truth_used_at_runtime": False,
        },
        "repeatability": {
            "status": pipeline_repeatability.get("status"),
            "repeatability_hash": _hash_ref(
                pipeline_repeatability.get("repeatability_hash"),
                "repeatability_hash",
            ),
            "numeric_tolerance": tolerance,
            "signal_tolerances": admitted_tolerances,
        },
        "search": {
            "signal_fields": list(admitted_signal_fields),
            "signal_diagnostics": signal_diagnostics,
            "grid_step": constraints.grid_step,
            "profile_count": len(candidates),
            "admissible_profile_count": len(admissible),
        },
        "cross_validation": {
            "fold_count": constraints.fold_count,
            "assignment_hash": semantic_sha256_hash_ref(folds),
            "maximum_threshold_spread": constraints.maximum_threshold_spread,
            "minimum_fold_balanced_accuracy": (
                constraints.minimum_fold_balanced_accuracy
            ),
            "minimum_candidate_auc": constraints.minimum_candidate_auc,
            "constraints": _constraints_payload(constraints.calibration),
        },
        "selected": _profile_projection(selected),
        "best_effort": _profile_projection(best_effort),
        "holdout": {"status": "SEALED_NOT_OPENED", "threshold_reselected": False},
        "frozen_policy": None,
    }
    if frozen:
        result["frozen_policy"] = _freeze_policy(selected, result)
    result["calibration_hash"] = semantic_sha256_hash_ref(result)
    return result


def _evaluate_profile(
    samples: Sequence[Mapping[str, Any]],
    *,
    packages: Mapping[str, Sequence[Mapping[str, Any]]],
    feature_fields: tuple[str, ...],
    weights: Mapping[str, float],
    folds: Sequence[Sequence[str]],
    dataset_id: str,
    numeric_tolerance: float,
    constraints: CandidateRelevanceConstraints,
    signal_tolerances: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    candidate_scores = _score_candidates(
        samples,
        feature_fields=feature_fields,
        weights=weights,
        numeric_tolerance=numeric_tolerance,
        signal_tolerances=signal_tolerances,
    )
    auc = _auc(candidate_scores)
    package_scores = _package_scores(packages, candidate_scores)
    evaluations: list[dict[str, Any]] = []
    for index, validation_groups in enumerate(folds):
        validation_set = set(validation_groups)
        training = [
            row
            for row in package_scores
            if _group_id(str(row["sample_id"])) not in validation_set
        ]
        validation = [
            row
            for row in package_scores
            if _group_id(str(row["sample_id"])) in validation_set
        ]
        fit = evaluate_binary_score_calibration(
            training,
            dataset_id=f"{dataset_id}:relevance:fold-{index}:train",
            constraints=constraints.calibration,
        )
        threshold_source = "SELECTED_THRESHOLD"
        threshold = fit.get("selected_threshold")
        if threshold is None:
            threshold_source = "TRAIN_BEST_EFFORT_THRESHOLD"
            threshold = _mapping(fit.get("best_effort_metrics")).get("threshold")
        if threshold is None:
            return _rejected(
                feature_fields,
                weights,
                auc,
                "FOLD_TRAINING_THRESHOLD_UNAVAILABLE",
                evaluations,
            )
        evaluation = evaluate_binary_score_threshold(
            validation,
            dataset_id=f"{dataset_id}:relevance:fold-{index}:validation",
            threshold=float(threshold),
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
                "fold_index": index,
                "threshold": float(threshold),
                "threshold_source": threshold_source,
                "metrics": evaluation["metrics"],
            }
        )
    aggregate = _aggregate_metrics(evaluations)
    full_fit = evaluate_binary_score_calibration(
        package_scores,
        dataset_id=f"{dataset_id}:relevance:full-calibration",
        constraints=constraints.calibration,
    )
    thresholds = [float(row["threshold"]) for row in evaluations]
    spread = round(max(thresholds) - min(thresholds), 8)
    minimum_accuracy = min(
        float(_mapping(row["metrics"])["balanced_accuracy"])
        for row in evaluations
    )
    admissible = (
        full_fit["status"] == "PASSED"
        and auc >= constraints.minimum_candidate_auc
        and aggregate["false_ready_rate"]
        <= constraints.calibration.maximum_false_ready_rate
        and aggregate["ready_recall"]
        >= constraints.calibration.minimum_ready_recall
        and spread <= constraints.maximum_threshold_spread
        and minimum_accuracy >= constraints.minimum_fold_balanced_accuracy
    )
    return {
        "status": "ADMISSIBLE" if admissible else "REJECTED",
        "reason_code": (
            "CANDIDATE_RELEVANCE_CONSTRAINTS_SATISFIED"
            if admissible
            else "CANDIDATE_RELEVANCE_CONSTRAINTS_NOT_SATISFIED"
        ),
        "feature_fields": list(feature_fields),
        "weights": dict(weights),
        "candidate_auc": auc,
        "oof_metrics": aggregate,
        "minimum_fold_balanced_accuracy": round(minimum_accuracy, 8),
        "threshold_spread": spread,
        "folds": evaluations,
        "selected_threshold": full_fit.get("selected_threshold"),
    }


def _normalize_samples(
    samples: Sequence[Mapping[str, Any]],
    *,
    signal_fields: Sequence[str] = CANDIDATE_SIGNAL_FIELDS,
) -> tuple[list[dict[str, Any]], list[str], dict[str, list[dict[str, Any]]]]:
    normalized_signal_fields = _signal_fields(signal_fields)
    if isinstance(samples, (str, bytes)) or not isinstance(samples, Sequence):
        raise TypeError("candidate relevance samples are invalid")
    normalized: list[dict[str, Any]] = []
    packages: dict[str, list[dict[str, Any]]] = {}
    seen: set[str] = set()
    labels: dict[str, set[bool]] = {}
    for value in samples:
        if not isinstance(value, Mapping):
            raise TypeError("candidate relevance sample is invalid")
        row = dict(value)
        sample_hash = _hash_ref(row.pop("sample_hash", None), "sample_hash")
        if sample_hash in seen or sample_hash != semantic_sha256_hash_ref(row):
            raise ValueError("candidate relevance sample integrity is invalid")
        seen.add(sample_hash)
        expected_schema = (
            EXPANDED_CANDIDATE_RELEVANCE_SAMPLE_SCHEMA_VERSION
            if any(
                field not in CANDIDATE_SIGNAL_FIELDS
                for field in normalized_signal_fields
            )
            else CANDIDATE_RELEVANCE_SAMPLE_SCHEMA_VERSION
        )
        if row.get("sample_schema_version") != expected_schema:
            raise ValueError("candidate relevance sample schema is invalid")
        sample_id = _required_string(row.get("sample_id"), "sample_id")
        candidate_id = _required_string(row.get("candidate_id"), "candidate_id")
        expected_ready = row.get("expected_ready")
        expected_relevant = row.get("expected_relevant")
        signals = _mapping(row.get("signals"))
        if type(expected_ready) is not bool or type(expected_relevant) is not bool:
            raise TypeError("candidate relevance labels are invalid")
        normalized_row = {
            **row,
            "sample_id": sample_id,
            "candidate_id": candidate_id,
            "expected_ready": expected_ready,
            "expected_relevant": expected_relevant,
            "signals": {
                field: _score(signals.get(field), field)
                for field in normalized_signal_fields
            },
            "sample_hash": sample_hash,
        }
        packages.setdefault(sample_id, []).append(normalized_row)
        labels.setdefault(_group_id(sample_id), set()).add(expected_ready)
        normalized.append(normalized_row)
    for sample_id, rows in packages.items():
        ready = sample_id.endswith(":positive")
        if (
            len(rows) != 4
            or len({row["candidate_id"] for row in rows}) != 4
            or any(row["expected_ready"] is not ready for row in rows)
            or sum(bool(row["expected_relevant"]) for row in rows)
            != (2 if ready else 0)
        ):
            raise ValueError("candidate relevance package semantics are invalid")
    if not packages or any(values != {False, True} for values in labels.values()):
        raise ValueError("candidate relevance scenario pairs are incomplete")
    return (
        sorted(normalized, key=lambda row: (row["sample_id"], row["candidate_id"])),
        sorted(labels),
        packages,
    )


def _score_candidates(
    samples: Sequence[Mapping[str, Any]],
    *,
    feature_fields: Sequence[str],
    weights: Mapping[str, float],
    numeric_tolerance: float,
    signal_tolerances: Mapping[str, float] | None = None,
) -> dict[tuple[str, str], dict[str, Any]]:
    tolerances = {
        "reranker_score": numeric_tolerance,
        **dict(signal_tolerances or {}),
    }
    scored: dict[tuple[str, str], dict[str, Any]] = {}
    for row in samples:
        signals = _mapping(row["signals"])
        raw = sum(float(signals[field]) * weights[field] for field in feature_fields)
        adverse = sum(
            float(weights.get(field, 0.0)) * float(tolerances.get(field, 0.0))
            for field in feature_fields
        )
        score = (
            max(0.0, raw - adverse)
            if row["expected_relevant"]
            else min(1.0, raw + adverse)
        )
        scored[(str(row["sample_id"]), str(row["candidate_id"]))] = {
            "expected_relevant": bool(row["expected_relevant"]),
            "score": round(score, 8),
        }
    return scored


def _package_scores(
    packages: Mapping[str, Sequence[Mapping[str, Any]]],
    candidate_scores: Mapping[tuple[str, str], Mapping[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for sample_id, rows in packages.items():
        scores = sorted(
            (
                float(candidate_scores[(sample_id, str(row["candidate_id"]))]["score"])
                for row in rows
            ),
            reverse=True,
        )
        result.append(
            {
                "sample_id": sample_id,
                "expected_ready": bool(rows[0]["expected_ready"]),
                "score": scores[1],
            }
        )
    return sorted(result, key=lambda row: str(row["sample_id"]))


def _profiles(
    constraints: CandidateRelevanceConstraints,
    *,
    signal_fields: Sequence[str] = CANDIDATE_SIGNAL_FIELDS,
) -> list[tuple[tuple[str, ...], dict[str, float]]]:
    normalized_signal_fields = _signal_fields(signal_fields, constraints=constraints)
    total = round(1.0 / constraints.grid_step)
    result: list[tuple[tuple[str, ...], dict[str, float]]] = []
    for count in range(1, constraints.maximum_feature_count + 1):
        for fields in itertools.combinations(normalized_signal_fields, count):
            for units in _positive_compositions(total, count):
                result.append(
                    (
                        fields,
                        {
                            field: round(unit * constraints.grid_step, 8)
                            for field, unit in zip(fields, units, strict=True)
                        },
                    )
                )
    return result


def _positive_compositions(total: int, count: int) -> list[tuple[int, ...]]:
    if count == 1:
        return [(total,)]
    return [
        (head, *tail)
        for head in range(1, total - count + 2)
        for tail in _positive_compositions(total - head, count - 1)
    ]


def _fold_groups(groups: Sequence[str], *, dataset_id: str, count: int) -> list[list[str]]:
    ordered = sorted(
        groups,
        key=lambda group: semantic_sha256_hash_ref(
            {"dataset_id": dataset_id, "group_id": group}
        ),
    )
    folds = [[] for _ in range(count)]
    for index, group in enumerate(ordered):
        folds[index % count].append(group)
    if any(not fold for fold in folds):
        raise ValueError("candidate relevance folds are incomplete")
    return folds


def _auc(scores: Mapping[tuple[str, str], Mapping[str, Any]]) -> float:
    positives = [float(row["score"]) for row in scores.values() if row["expected_relevant"]]
    negatives = [float(row["score"]) for row in scores.values() if not row["expected_relevant"]]
    if not positives or not negatives:
        raise ValueError("candidate relevance AUC labels are incomplete")
    favorable = sum(
        1.0 if positive > negative else 0.5 if positive == negative else 0.0
        for positive in positives
        for negative in negatives
    )
    return round(favorable / (len(positives) * len(negatives)), 8)


def _aggregate_metrics(folds: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    totals = {
        "true_ready": 0,
        "false_low_confidence": 0,
        "false_ready": 0,
        "true_low_confidence": 0,
    }
    for fold in folds:
        metrics = _mapping(fold["metrics"])
        for metric_name in totals:
            totals[metric_name] += int(metrics[metric_name])
    positive = totals["true_ready"] + totals["false_low_confidence"]
    negative = totals["false_ready"] + totals["true_low_confidence"]
    predicted = totals["true_ready"] + totals["false_ready"]
    recall = _ratio(totals["true_ready"], positive)
    specificity = _ratio(totals["true_low_confidence"], negative)
    return {
        **totals,
        "ready_precision": _ratio(totals["true_ready"], predicted),
        "ready_recall": recall,
        "false_ready_rate": _ratio(totals["false_ready"], negative),
        "balanced_accuracy": round((recall + specificity) / 2.0, 8),
    }


def _rejected(
    fields: Sequence[str],
    weights: Mapping[str, float],
    auc: float,
    reason: str,
    folds: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "status": "REJECTED",
        "reason_code": reason,
        "feature_fields": list(fields),
        "weights": dict(weights),
        "candidate_auc": auc,
        "oof_metrics": None,
        "minimum_fold_balanced_accuracy": None,
        "threshold_spread": None,
        "folds": list(folds),
        "selected_threshold": None,
    }


def _selection_key(value: Mapping[str, Any]) -> tuple[Any, ...]:
    metrics = _mapping(value.get("oof_metrics"))
    fields = tuple(str(field) for field in value.get("feature_fields", []))
    weights = _mapping(value.get("weights"))
    return (
        value.get("status") == "ADMISSIBLE",
        float(metrics.get("balanced_accuracy", -1.0)),
        float(metrics.get("ready_recall", -1.0)),
        -float(metrics.get("false_ready_rate", 1.0)),
        float(value.get("candidate_auc", -1.0)),
        -len(fields),
        tuple(-float(weights.get(field, 0.0)) for field in fields),
        tuple(reversed(fields)),
    )


def _profile_projection(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        field: value.get(field)
        for field in (
            "status",
            "reason_code",
            "feature_fields",
            "weights",
            "candidate_auc",
            "oof_metrics",
            "minimum_fold_balanced_accuracy",
            "threshold_spread",
            "folds",
            "selected_threshold",
        )
    }


def _freeze_policy(selected: Mapping[str, Any], result: Mapping[str, Any]) -> dict[str, Any]:
    policy = {
        "policy_schema_version": CANDIDATE_RELEVANCE_POLICY_SCHEMA_VERSION,
        "policy_id": result["policy_id"],
        "version": "1",
        "status": "CANDIDATE_FROZEN",
        "runtime_activation_permitted": False,
        "feature_fields": selected["feature_fields"],
        "weights": selected["weights"],
        "candidate_relevance_threshold": selected["selected_threshold"],
        "package_ready_rule": "SECOND_HIGHEST_SCORE_AT_OR_ABOVE_THRESHOLD",
        "dataset": result["dataset"],
        "binding": result["binding"],
        "repeatability": result["repeatability"],
        "cross_validation": {
            **dict(_mapping(result["cross_validation"])),
            "candidate_auc": selected["candidate_auc"],
            "oof_metrics": selected["oof_metrics"],
        },
        "holdout_status": "SEALED_NOT_OPENED",
    }
    policy["policy_hash"] = semantic_sha256_hash_ref(policy)
    return policy


def _binding(value: Mapping[str, Any]) -> dict[str, str]:
    fields = (
        "chunk_policy_id",
        "embedding_model_revision",
        "ranking_policy_id",
        "reranker_model_revision",
        "tokenizer_policy_id",
    )
    if not isinstance(value, Mapping):
        raise TypeError("candidate relevance binding is invalid")
    return {field: _required_string(value.get(field), field) for field in fields}


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
        raise ValueError("candidate relevance sample identity is invalid")
    return group


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _signal_fields(
    values: Sequence[str],
    *,
    constraints: CandidateRelevanceConstraints | None = None,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise TypeError("candidate relevance signal fields are invalid")
    normalized = tuple(values)
    if (
        not normalized
        or len(set(normalized)) != len(normalized)
        or any(field not in EXPANDED_CANDIDATE_SIGNAL_FIELDS for field in normalized)
        or (
            constraints is not None
            and constraints.maximum_feature_count > len(normalized)
        )
    ):
        raise ValueError("candidate relevance signal fields are invalid")
    return normalized


def _signal_tolerances(
    signal_fields: Sequence[str],
    *,
    reranker_tolerance: float,
    values: Mapping[str, float] | None,
) -> dict[str, float]:
    if values is not None and not isinstance(values, Mapping):
        raise TypeError("candidate relevance signal tolerances are invalid")
    provided = dict(values or {})
    if any(field not in signal_fields for field in provided):
        raise ValueError("candidate relevance signal tolerances are invalid")
    result = {field: 0.0 for field in signal_fields}
    if "reranker_score" in result:
        result["reranker_score"] = reranker_tolerance
    for signal_field, value in provided.items():
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(float(value))
            or not 0.0 <= float(value) <= 0.01
        ):
            raise ValueError("candidate relevance signal tolerances are invalid")
        result[signal_field] = float(value)
    if "reranker_score" in result and not math.isclose(
        result["reranker_score"], reranker_tolerance, abs_tol=1e-12
    ):
        raise ValueError("candidate relevance signal tolerances are invalid")
    return result


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is invalid")
    return value.strip()


def _hash_ref(value: object, field: str) -> str:
    text = _required_string(value, field)
    if not text.startswith("sha256:") or len(text) != 71:
        raise ValueError(f"{field} is invalid")
    return text


def _score(value: object, field: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(float(value))
        or not 0.0 <= float(value) <= 1.0
    ):
        raise ValueError(f"{field} is invalid")
    return float(value)


def _tolerance(value: object) -> float:
    tolerance = _score(value, "numeric_tolerance")
    if not 0.0 < tolerance <= 0.005:
        raise ValueError("numeric_tolerance is invalid")
    return tolerance


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 8) if denominator else 0.0
