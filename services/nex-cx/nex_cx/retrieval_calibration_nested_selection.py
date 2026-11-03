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
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

from nex_cx.retrieval_confidence_candidate_diagnostics import (
    EXPANDED_CANDIDATE_RELEVANCE_SAMPLE_SCHEMA_VERSION,
)

NESTED_SELECTION_SCHEMA_VERSION = "cx_retrieval_nested_profile_selection.v1"


def select_nested_retrieval_profile(
    samples: Sequence[Mapping[str, Any]],
    *,
    dataset_id: str,
    dataset_sha256: str,
    design: Mapping[str, Any],
    fold_plan: Mapping[str, Any],
    expected_binding: Mapping[str, Any],
) -> dict[str, Any]:
    """Select a frozen profile by nested scenario-grouped calibration only."""
    normalized, scenario_ids = _normalize_samples(samples)
    selection = _mapping(design.get("selection_protocol"))
    admission = _mapping(design.get("admission"))
    profiles = _profiles(selection.get("profile_shortlist"))
    outer_folds = _outer_folds(fold_plan, expected_scenarios=scenario_ids)
    constraints = BinaryCalibrationConstraints(
        maximum_false_ready_rate=_score(
            admission.get("maximum_false_ready_rate"),
            "maximum_false_ready_rate",
        ),
        minimum_ready_recall=_score(
            admission.get("minimum_ready_recall"), "minimum_ready_recall"
        ),
    )

    outer_results: list[dict[str, Any]] = []
    outer_scored_candidates: list[dict[str, Any]] = []
    for outer in outer_folds:
        result, validation_candidates = _evaluate_outer_fold(
            normalized,
            outer=outer,
            profiles=profiles,
            constraints=constraints,
            dataset_id=dataset_id,
            minimum_candidate_auc=_score(
                admission.get("minimum_candidate_auc"), "minimum_candidate_auc"
            ),
        )
        outer_results.append(result)
        outer_scored_candidates.extend(validation_candidates)

    completed = [row for row in outer_results if row["status"] == "EVALUATED"]
    selected_counts = Counter(str(row["selected_profile_id"]) for row in completed)
    stable_profile_id, stable_count = (
        selected_counts.most_common(1)[0] if selected_counts else (None, 0)
    )
    aggregate = _aggregate_metrics(
        [_mapping(row.get("metrics")) for row in completed]
    )
    thresholds = [float(row["threshold"]) for row in completed]
    threshold_spread = (
        round(max(thresholds) - min(thresholds), 8) if thresholds else None
    )
    minimum_outer_accuracy = (
        min(float(_mapping(row["metrics"])["balanced_accuracy"]) for row in completed)
        if completed
        else None
    )
    candidate_auc = (
        _candidate_auc(outer_scored_candidates) if outer_scored_candidates else None
    )
    checks = {
        "all_outer_folds_evaluated": len(completed) == len(outer_folds),
        "stable_profile_selected": stable_count
        >= _positive_int(
            admission.get("minimum_profile_selection_fold_count"),
            "minimum_profile_selection_fold_count",
        ),
        "false_ready_rate_within_limit": (
            aggregate is not None
            and aggregate["false_ready_rate"]
            <= float(admission["maximum_false_ready_rate"])
        ),
        "ready_recall_within_limit": (
            aggregate is not None
            and aggregate["ready_recall"]
            >= float(admission["minimum_ready_recall"])
        ),
        "candidate_auc_within_limit": (
            candidate_auc is not None
            and candidate_auc >= float(admission["minimum_candidate_auc"])
        ),
        "minimum_outer_accuracy_within_limit": (
            minimum_outer_accuracy is not None
            and minimum_outer_accuracy
            >= float(admission["minimum_outer_fold_balanced_accuracy"])
        ),
        "outer_threshold_spread_within_limit": (
            threshold_spread is not None
            and threshold_spread
            <= float(admission["maximum_outer_threshold_spread"])
        ),
    }
    admitted = all(checks.values())
    final_fit = None
    if admitted and stable_profile_id is not None:
        stable_profile = next(
            profile for profile in profiles if profile["profile_id"] == stable_profile_id
        )
        final_fit = evaluate_binary_score_calibration(
            _package_scores(normalized, profile=stable_profile),
            dataset_id=f"{dataset_id}:nested-selection:full-calibration",
            constraints=constraints,
        )
        if final_fit["status"] != "PASSED":
            admitted = False
            checks["full_calibration_threshold_fitted"] = False
            final_fit = None
        else:
            checks["full_calibration_threshold_fitted"] = True

    result: dict[str, Any] = {
        "selection_schema_version": NESTED_SELECTION_SCHEMA_VERSION,
        "status": (
            "CALIBRATION_OOF_ADMITTED" if admitted else "NO_ADMISSIBLE_PROFILE"
        ),
        "reason_code": (
            "NESTED_CALIBRATION_CONSTRAINTS_SATISFIED"
            if admitted
            else "NESTED_CALIBRATION_CONSTRAINTS_NOT_SATISFIED"
        ),
        "runtime_activation_permitted": False,
        "holdout_access_permitted": False,
        "dataset": {
            "dataset_id": _required_string(dataset_id, "dataset_id"),
            "dataset_sha256": _required_string(dataset_sha256, "dataset_sha256"),
            "partition": "CALIBRATION",
            "scenario_count": len(scenario_ids),
            "package_count": len(scenario_ids) * 2,
            "candidate_count": len(normalized),
            "sample_set_hash": semantic_sha256_hash_ref(
                sorted(str(row["sample_hash"]) for row in normalized)
            ),
        },
        "binding": _binding(expected_binding),
        "protocol": {
            "mode": selection.get("mode"),
            "outer_fold_count": len(outer_folds),
            "inner_fold_count": selection.get("inner_fold_count"),
            "profile_shortlist": [profile["profile_id"] for profile in profiles],
            "selection_objective": selection.get("selection_objective"),
            "outer_validation_reselection_permitted": False,
        },
        "outer_folds": outer_results,
        "oof_evaluation": {
            "metrics": aggregate,
            "confidence_intervals": _confidence_intervals(aggregate),
            "candidate_auc": candidate_auc,
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
                "threshold": final_fit["selected_threshold"],
                "fit": final_fit,
            }
            if admitted and final_fit is not None
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
    dataset_id: str,
    minimum_candidate_auc: float,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    outer_index = int(outer["fold_index"])
    validation_ids = set(outer["validation_scenario_ids"])
    training_ids = {_scenario_id(row["sample_id"]) for row in samples} - validation_ids
    candidates: list[dict[str, Any]] = []
    for shortlist_index, profile in enumerate(profiles):
        folds: list[dict[str, Any]] = []
        all_thresholds_available = True
        for inner in outer["inner_folds"]:
            inner_validation_ids = set(inner["validation_scenario_ids"])
            inner_training_ids = training_ids - inner_validation_ids
            fit = evaluate_binary_score_calibration(
                _package_scores(samples, profile=profile, scenario_ids=inner_training_ids),
                dataset_id=(
                    f"{dataset_id}:outer-{outer_index}:inner-"
                    f"{inner['fold_index']}:train:{profile['profile_id']}"
                ),
                constraints=constraints,
            )
            threshold = fit.get("selected_threshold")
            if threshold is None:
                all_thresholds_available = False
                threshold = _mapping(fit.get("best_effort_metrics")).get("threshold")
            if threshold is None:
                continue
            evaluated = evaluate_binary_score_threshold(
                _package_scores(
                    samples,
                    profile=profile,
                    scenario_ids=inner_validation_ids,
                ),
                dataset_id=(
                    f"{dataset_id}:outer-{outer_index}:inner-"
                    f"{inner['fold_index']}:validation:{profile['profile_id']}"
                ),
                threshold=float(threshold),
                constraints=_partition_constraints(
                    len(inner_validation_ids) * 2, constraints=constraints
                ),
            )
            folds.append(
                {
                    "fold_index": inner["fold_index"],
                    "threshold": float(threshold),
                    "threshold_source": (
                        "SELECTED_THRESHOLD"
                        if fit.get("selected_threshold") is not None
                        else "BEST_EFFORT_DIAGNOSTIC_ONLY"
                    ),
                    "metrics": evaluated["metrics"],
                }
            )
        metrics = _aggregate_metrics([_mapping(row["metrics"]) for row in folds])
        auc = _candidate_auc(
            _candidate_scores(samples, profile=profile, scenario_ids=training_ids)
        )
        admissible = (
            all_thresholds_available
            and len(folds) == len(outer["inner_folds"])
            and metrics is not None
            and metrics["false_ready_rate"] <= constraints.maximum_false_ready_rate
            and metrics["ready_recall"] >= constraints.minimum_ready_recall
            and auc >= minimum_candidate_auc
        )
        candidates.append(
            {
                "profile_id": profile["profile_id"],
                "shortlist_index": shortlist_index,
                "status": "ADMISSIBLE" if admissible else "REJECTED",
                "metrics": metrics,
                "candidate_auc": auc,
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
    profile = next(
        row for row in profiles if row["profile_id"] == selected["profile_id"]
    )
    fit = evaluate_binary_score_calibration(
        _package_scores(samples, profile=profile, scenario_ids=training_ids),
        dataset_id=f"{dataset_id}:outer-{outer_index}:refit:{profile['profile_id']}",
        constraints=constraints,
    )
    threshold = fit.get("selected_threshold")
    if threshold is None:
        return (
            {
                "fold_index": outer_index,
                "status": "OUTER_REFIT_FAILED",
                "selected_profile_id": profile["profile_id"],
                "threshold": None,
                "metrics": None,
                "inner_selection": candidates,
            },
            [],
        )
    evaluation = evaluate_binary_score_threshold(
        _package_scores(samples, profile=profile, scenario_ids=validation_ids),
        dataset_id=f"{dataset_id}:outer-{outer_index}:validation",
        threshold=float(threshold),
        constraints=_partition_constraints(len(validation_ids) * 2, constraints=constraints),
    )
    return (
        {
            "fold_index": outer_index,
            "status": "EVALUATED",
            "selected_profile_id": profile["profile_id"],
            "threshold": float(threshold),
            "metrics": evaluation["metrics"],
            "confidence_intervals": evaluation["confidence_intervals"],
            "inner_selection": candidates,
        },
        _candidate_scores(samples, profile=profile, scenario_ids=validation_ids),
    )


def _package_scores(
    samples: Sequence[Mapping[str, Any]],
    *,
    profile: Mapping[str, Any],
    scenario_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    candidates = _candidate_scores(samples, profile=profile, scenario_ids=scenario_ids)
    packages: dict[str, list[dict[str, Any]]] = {}
    for row in candidates:
        packages.setdefault(str(row["sample_id"]), []).append(row)
    return [
        {
            "sample_id": sample_id,
            "expected_ready": rows[0]["expected_ready"],
            "score": sorted((float(row["score"]) for row in rows), reverse=True)[1],
        }
        for sample_id, rows in sorted(packages.items())
    ]


def _candidate_scores(
    samples: Sequence[Mapping[str, Any]],
    *,
    profile: Mapping[str, Any],
    scenario_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    weights = _mapping(profile["weights"])
    fields = profile["feature_fields"]
    return [
        {
            "sample_id": row["sample_id"],
            "candidate_id": row["candidate_id"],
            "expected_ready": row["expected_ready"],
            "expected_relevant": row["expected_relevant"],
            "score": round(
                sum(float(_mapping(row["signals"])[field]) * float(weights[field]) for field in fields),
                8,
            ),
        }
        for row in samples
        if scenario_ids is None or _scenario_id(str(row["sample_id"])) in scenario_ids
    ]


def _normalize_samples(
    samples: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], set[str]]:
    if isinstance(samples, (str, bytes)) or not isinstance(samples, Sequence):
        raise TypeError("nested calibration samples are invalid")
    normalized: list[dict[str, Any]] = []
    package_counts: Counter[str] = Counter()
    scenario_labels: dict[str, set[bool]] = {}
    identities: set[tuple[str, str]] = set()
    for value in samples:
        if not isinstance(value, Mapping):
            raise TypeError("nested calibration sample is invalid")
        row = dict(value)
        sample_hash = _hash_ref(row.pop("sample_hash", None), "sample_hash")
        if sample_hash != semantic_sha256_hash_ref(row):
            raise ValueError("nested calibration sample integrity is invalid")
        if (
            row.get("sample_schema_version")
            != EXPANDED_CANDIDATE_RELEVANCE_SAMPLE_SCHEMA_VERSION
        ):
            raise ValueError("nested calibration sample schema is invalid")
        sample_id = _required_string(row.get("sample_id"), "sample_id")
        candidate_id = _required_string(row.get("candidate_id"), "candidate_id")
        identity = (sample_id, candidate_id)
        if identity in identities:
            raise ValueError("nested calibration candidate identity is duplicated")
        identities.add(identity)
        expected_ready = row.get("expected_ready")
        expected_relevant = row.get("expected_relevant")
        signals = _mapping(row.get("signals"))
        if type(expected_ready) is not bool or type(expected_relevant) is not bool:
            raise TypeError("nested calibration labels are invalid")
        normalized_signals = {
            field: _score(signals.get(field), field)
            for field in (
                "reranker_score",
                "rrf_normalized_score",
                "channel_rank_quality",
                "bm25_score_quality",
            )
        }
        scenario_id = _scenario_id(sample_id)
        scenario_labels.setdefault(scenario_id, set()).add(expected_ready)
        package_counts[sample_id] += 1
        normalized.append(
            {
                **row,
                "sample_hash": sample_hash,
                "sample_id": sample_id,
                "candidate_id": candidate_id,
                "signals": normalized_signals,
            }
        )
    if not normalized or any(count != 4 for count in package_counts.values()):
        raise ValueError("nested calibration package coverage is invalid")
    if any(labels != {False, True} for labels in scenario_labels.values()):
        raise ValueError("nested calibration scenario pairs are invalid")
    return sorted(normalized, key=lambda row: (row["sample_id"], row["candidate_id"])), set(scenario_labels)


def _profiles(value: object) -> list[dict[str, Any]]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError("nested profile shortlist is invalid")
    profiles: list[dict[str, Any]] = []
    seen: set[str] = set()
    allowed = {
        "reranker_score",
        "rrf_normalized_score",
        "channel_rank_quality",
        "bm25_score_quality",
    }
    for item in value:
        if not isinstance(item, Mapping):
            raise TypeError("nested profile is invalid")
        profile_id = _required_string(item.get("profile_id"), "profile_id")
        fields = item.get("feature_fields")
        weights = _mapping(item.get("weights"))
        if (
            profile_id in seen
            or isinstance(fields, (str, bytes))
            or not isinstance(fields, Sequence)
            or not fields
            or set(fields) != set(weights)
            or not set(fields) <= allowed
            or not math.isclose(sum(float(weights[field]) for field in fields), 1.0)
        ):
            raise ValueError("nested profile is invalid")
        seen.add(profile_id)
        profiles.append(
            {
                "profile_id": profile_id,
                "feature_fields": list(fields),
                "weights": {field: _score(weights[field], field) for field in fields},
            }
        )
    return profiles


def _outer_folds(
    fold_plan: Mapping[str, Any], *, expected_scenarios: set[str]
) -> list[dict[str, Any]]:
    assignment = _mapping(fold_plan.get("assignment"))
    values = assignment.get("outer_folds")
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise TypeError("nested outer folds are invalid")
    folds = [dict(value) for value in values if isinstance(value, Mapping)]
    observed = {
        str(scenario_id)
        for fold in folds
        for scenario_id in fold.get("validation_scenario_ids", [])
    }
    if len(folds) != assignment.get("outer_fold_count") or observed != expected_scenarios:
        raise ValueError("nested outer fold coverage is invalid")
    return folds


def _selection_key(value: Mapping[str, Any]) -> tuple[Any, ...]:
    metrics = _mapping(value.get("metrics"))
    return (
        float(metrics.get("balanced_accuracy", -1.0)),
        float(metrics.get("ready_recall", -1.0)),
        -float(metrics.get("false_ready_rate", 1.0)),
        float(value.get("candidate_auc", -1.0)),
        -int(value.get("shortlist_index", 10_000)),
    )


def _aggregate_metrics(values: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    if not values:
        return None
    totals = {
        field: sum(int(value[field]) for value in values)
        for field in (
            "true_ready",
            "false_low_confidence",
            "false_ready",
            "true_low_confidence",
        )
    }
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


def _candidate_auc(values: Sequence[Mapping[str, Any]]) -> float:
    positives = [float(row["score"]) for row in values if row["expected_relevant"]]
    negatives = [float(row["score"]) for row in values if not row["expected_relevant"]]
    if not positives or not negatives:
        raise ValueError("candidate AUC requires both relevance labels")
    wins = sum(
        1.0 if positive > negative else 0.5 if positive == negative else 0.0
        for positive in positives
        for negative in negatives
    )
    return round(wins / (len(positives) * len(negatives)), 8)


def _confidence_intervals(metrics: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if metrics is None:
        return None
    positives = int(metrics["true_ready"]) + int(metrics["false_low_confidence"])
    negatives = int(metrics["false_ready"]) + int(metrics["true_low_confidence"])
    return {
        "method": "WILSON_SCORE",
        "confidence_level": 0.95,
        "false_ready_rate": _wilson(int(metrics["false_ready"]), negatives),
        "ready_recall": _wilson(int(metrics["true_ready"]), positives),
    }


def _wilson(successes: int, total: int) -> dict[str, float]:
    if total <= 0:
        return {"lower": 0.0, "upper": 1.0}
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1.0 + z * z / total
    center = (proportion + z * z / (2.0 * total)) / denominator
    margin = z * math.sqrt(
        proportion * (1.0 - proportion) / total + z * z / (4.0 * total * total)
    ) / denominator
    return {"lower": round(max(0.0, center - margin), 8), "upper": round(min(1.0, center + margin), 8)}


def _partition_constraints(
    sample_count: int, *, constraints: BinaryCalibrationConstraints
) -> BinaryCalibrationConstraints:
    return BinaryCalibrationConstraints(
        minimum_sample_count=sample_count,
        minimum_positive_count=sample_count // 2,
        minimum_negative_count=sample_count // 2,
        maximum_false_ready_rate=constraints.maximum_false_ready_rate,
        minimum_ready_recall=constraints.minimum_ready_recall,
    )


def _binding(value: Mapping[str, Any]) -> dict[str, str]:
    return {
        field: _required_string(value.get(field), field)
        for field in (
            "embedding_model_revision",
            "reranker_model_revision",
            "ranking_policy_id",
            "tokenizer_policy_id",
            "chunk_policy_id",
        )
    }


def _scenario_id(sample_id: str) -> str:
    scenario_id, separator, label = sample_id.rpartition(":")
    if not separator or label not in {"positive", "negative"} or not scenario_id:
        raise ValueError("nested calibration sample ID is invalid")
    return scenario_id


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


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


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field} is invalid")
    return value


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 8) if denominator else 0.0
