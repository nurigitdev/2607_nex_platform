from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

from nex_runtime.model_calibration import (
    BinaryCalibrationConstraints,
    evaluate_binary_score_calibration,
)
from nex_cx.retrieval_package_ready_signal import (
    build_package_ready_signal,
    fit_candidate_probability_model,
    predict_candidate_relevance_probability,
    score_candidate_relevance_samples,
)

PACKAGE_PROBABILITY_AUDIT_SCHEMA_VERSION = (
    "cx_retrieval_package_probability_failure_audit.v1"
)
PACKAGE_PROBABILITY_AUDIT_POLICY_ID = (
    "cx_candidate_probability_failure_attribution_v1"
)


def audit_candidate_probability_failure(
    samples: Sequence[Mapping[str, Any]],
    *,
    profiles: Sequence[Mapping[str, Any]],
    expected_binding: Mapping[str, Any],
    maximum_false_ready_rate: float = 0.10,
    minimum_ready_recall: float = 0.80,
) -> dict[str, Any]:
    """Attribute package-signal failure without selecting a runtime policy."""
    if isinstance(profiles, (str, bytes)) or not isinstance(profiles, Sequence):
        raise TypeError("candidate probability audit profiles are invalid")
    constraints = BinaryCalibrationConstraints(
        maximum_false_ready_rate=maximum_false_ready_rate,
        minimum_ready_recall=minimum_ready_recall,
    )
    diagnostics = [
        _audit_profile(
            samples,
            profile=profile,
            expected_binding=expected_binding,
            constraints=constraints,
        )
        for profile in profiles
    ]
    if not diagnostics:
        raise ValueError("candidate probability audit profiles are missing")

    fitted = [row for row in diagnostics if row["status"] == "DIAGNOSED"]
    checks = {
        "all_profiles_diagnosed": len(fitted) == len(diagnostics),
        "package_semantics_remain_exact": all(
            row["package_semantics"]["ready_relevant_count"] == 2
            and row["package_semantics"]["low_confidence_relevant_count"] == 0
            for row in fitted
        ),
        "candidate_signal_is_directional": bool(fitted)
        and max(float(row["candidate_calibration"]["auc"]) for row in fitted)
        >= 0.70,
        "no_full_calibration_profile_meets_constraints": bool(fitted)
        and not any(
            row["package_calibration"]["threshold_fit_status"] == "PASSED"
            for row in fitted
        ),
        "independence_assumption_not_admitted": all(
            row["dependence_audit"]["conditional_independence_admitted"] is False
            for row in fitted
        ),
        "holdout_access_prohibited": True,
        "runtime_activation_prohibited": True,
    }
    result: dict[str, Any] = {
        "audit_schema_version": PACKAGE_PROBABILITY_AUDIT_SCHEMA_VERSION,
        "policy_id": PACKAGE_PROBABILITY_AUDIT_POLICY_ID,
        "status": "DIAGNOSED" if all(checks.values()) else "INCONCLUSIVE",
        "decision": (
            "DEPENDENCE_ROBUST_PACKAGE_SCORE_REQUIRED"
            if all(checks.values())
            else "STOP_FOR_REVIEW"
        ),
        "profile_diagnostics": diagnostics,
        "failure_attribution": {
            "candidate_probability_directional": checks[
                "candidate_signal_is_directional"
            ],
            "package_threshold_separation_insufficient": checks[
                "no_full_calibration_profile_meets_constraints"
            ],
            "structured_package_labels_not_independent": checks[
                "independence_assumption_not_admitted"
            ],
            "dataset_or_label_change_authorized": False,
            "model_revision_change_authorized": False,
        },
        "next_contract": {
            "required_signal": "DEPENDENCE_ROBUST_PACKAGE_ORDINAL_SCORE",
            "candidate_truth_runtime_input_permitted": False,
            "calibration_partition_only": True,
            "holdout_access_permitted": False,
            "runtime_activation_permitted": False,
        },
        "checks": checks,
    }
    result["audit_hash"] = semantic_sha256_hash_ref(result)
    return result


def _audit_profile(
    samples: Sequence[Mapping[str, Any]],
    *,
    profile: Mapping[str, Any],
    expected_binding: Mapping[str, Any],
    constraints: BinaryCalibrationConstraints,
) -> dict[str, Any]:
    candidate_profile = _candidate_profile(profile)
    scored = score_candidate_relevance_samples(samples, profile=candidate_profile)
    model = fit_candidate_probability_model(
        scored,
        source_profile_id=candidate_profile["profile_id"],
        expected_binding=expected_binding,
        training_scope="CALIBRATION_FULL_DIAGNOSTIC_ONLY",
    )
    if model["status"] != "CALIBRATION_ONLY_FITTED":
        return {
            "profile_id": candidate_profile["profile_id"],
            "status": "PROBABILITY_MODEL_REJECTED",
            "candidate_probability_model_status": model["status"],
        }

    candidate_rows = [
        {
            "sample_id": row["sample_id"],
            "candidate_id": row["candidate_id"],
            "expected_relevant": bool(row["expected_relevant"]),
            "probability": predict_candidate_relevance_probability(
                float(row["candidate_score"]), model=model
            ),
        }
        for row in scored
    ]
    truths = {
        (str(row["sample_id"]), str(row["candidate_id"])): {
            "expected_ready": bool(row["expected_ready"]),
            "expected_relevant": bool(row["expected_relevant"]),
        }
        for row in samples
    }
    packages: dict[str, list[dict[str, Any]]] = {}
    labels: dict[str, bool] = {}
    relevant_counts: dict[str, int] = {}
    for scored_row in scored:
        sample_id = str(scored_row["sample_id"])
        truth = truths[(sample_id, str(scored_row["candidate_id"]))]
        labels[sample_id] = truth["expected_ready"]
        relevant_counts[sample_id] = relevant_counts.get(sample_id, 0) + int(
            truth["expected_relevant"]
        )
        packages.setdefault(sample_id, []).append(
            {
                "candidate_id": scored_row["candidate_id"],
                "candidate_score": scored_row["candidate_score"],
            }
        )

    package_rows: list[dict[str, Any]] = []
    count_distributions: list[list[float]] = []
    for sample_id, package in sorted(packages.items()):
        signal = build_package_ready_signal(
            package,
            model=model,
            expected_binding=expected_binding,
        )
        count_distribution = [
            float(signal["relevant_count_probability"][str(index)])
            for index in range(5)
        ]
        count_distributions.append(count_distribution)
        package_rows.append(
            {
                "sample_id": sample_id,
                "expected_ready": labels[sample_id],
                "actual_relevant_count": relevant_counts[sample_id],
                "score": float(
                    signal["features"]["ready_probability_at_least_two"]
                ),
                "expected_relevant_count": float(
                    signal["features"]["expected_relevant_count"]
                ),
                "count_distribution": count_distribution,
            }
        )

    fit = evaluate_binary_score_calibration(
        package_rows,
        dataset_id=(
            "s20qpd:full-calibration-diagnostic-only:"
            f"{candidate_profile['profile_id']}"
        ),
        constraints=constraints,
    )
    ready = [row for row in package_rows if row["expected_ready"]]
    low = [row for row in package_rows if not row["expected_ready"]]
    unobserved_mass = statistics.fmean(
        distribution[1] + distribution[3] + distribution[4]
        for distribution in count_distributions
    )
    observed = [0.5, 0.0, 0.5, 0.0, 0.0]
    predicted = [
        statistics.fmean(distribution[index] for distribution in count_distributions)
        for index in range(5)
    ]
    return {
        "profile_id": candidate_profile["profile_id"],
        "status": "DIAGNOSED",
        "candidate_probability_model_hash": model["model_hash"],
        "candidate_calibration": _probability_metrics(
            [
                (row["probability"], row["expected_relevant"])
                for row in candidate_rows
            ]
        ),
        "package_calibration": {
            **_probability_metrics(
                [(row["score"], row["expected_ready"]) for row in package_rows]
            ),
            "threshold_fit_status": fit["status"],
            "best_effort_metrics": fit.get("best_effort_metrics"),
            "ready_probability": _distribution(
                [float(row["score"]) for row in ready]
            ),
            "low_confidence_probability": _distribution(
                [float(row["score"]) for row in low]
            ),
            "paired_directional_rate": _paired_directional_rate(package_rows),
        },
        "package_semantics": {
            "ready_relevant_count": _only_count(ready),
            "low_confidence_relevant_count": _only_count(low),
            "package_count": len(package_rows),
            "candidate_count": len(candidate_rows),
        },
        "dependence_audit": {
            "aggregation": "POISSON_BINOMIAL_V1",
            "conditional_independence_admitted": False,
            "reason_code": "STRUCTURED_PACKAGE_LABEL_DEPENDENCE_NOT_MODELED",
            "mean_predicted_count_distribution": {
                str(index): round(value, 8)
                for index, value in enumerate(predicted)
            },
            "observed_count_distribution": {
                str(index): value for index, value in enumerate(observed)
            },
            "count_distribution_total_variation": round(
                0.5 * sum(abs(a - b) for a, b in zip(predicted, observed, strict=True)),
                8,
            ),
            "mean_probability_mass_on_unobserved_counts": round(
                unobserved_mass, 8
            ),
        },
    }


def _candidate_profile(profile: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(profile, Mapping):
        raise TypeError("candidate probability audit profile is invalid")
    profile_id = profile.get("profile_id")
    fields = profile.get("feature_fields")
    weights = profile.get("weights")
    if (
        not isinstance(profile_id, str)
        or not profile_id.strip()
        or isinstance(fields, (str, bytes))
        or not isinstance(fields, Sequence)
        or not isinstance(weights, Mapping)
    ):
        raise TypeError("candidate probability audit profile is invalid")
    return {
        "profile_id": profile_id.strip(),
        "weights": [
            {"field": str(field), "weight": weights.get(field)} for field in fields
        ],
    }


def _probability_metrics(values: Sequence[tuple[float, bool]]) -> dict[str, float]:
    if not values:
        raise ValueError("probability audit values are missing")
    clipped = [
        (min(max(float(score), 1e-12), 1.0 - 1e-12), label)
        for score, label in values
    ]
    brier = statistics.fmean(
        (score - float(label)) ** 2 for score, label in clipped
    )
    log_loss = -statistics.fmean(
        math.log(score) if label else math.log(1.0 - score)
        for score, label in clipped
    )
    return {
        "auc": round(_auc(clipped), 8),
        "brier_score": round(brier, 8),
        "log_loss": round(log_loss, 8),
        "expected_calibration_error_10_bin": round(_ece(clipped), 8),
    }


def _auc(values: Sequence[tuple[float, bool]]) -> float:
    positives = [score for score, label in values if label]
    negatives = [score for score, label in values if not label]
    if not positives or not negatives:
        raise ValueError("probability audit labels are incomplete")
    wins = sum(
        1.0 if positive > negative else 0.5 if positive == negative else 0.0
        for positive in positives
        for negative in negatives
    )
    return wins / (len(positives) * len(negatives))


def _ece(values: Sequence[tuple[float, bool]]) -> float:
    total = len(values)
    error = 0.0
    for index in range(10):
        lower = index / 10
        upper = (index + 1) / 10
        bucket = [
            (score, label)
            for score, label in values
            if lower <= score < upper or (index == 9 and score == 1.0)
        ]
        if bucket:
            confidence = statistics.fmean(score for score, _ in bucket)
            accuracy = statistics.fmean(float(label) for _, label in bucket)
            error += len(bucket) / total * abs(confidence - accuracy)
    return error


def _distribution(values: Sequence[float]) -> dict[str, float]:
    if not values:
        raise ValueError("probability audit distribution is missing")
    return {
        "minimum": round(min(values), 8),
        "maximum": round(max(values), 8),
        "mean": round(statistics.fmean(values), 8),
        "median": round(statistics.median(values), 8),
    }


def _only_count(rows: Sequence[Mapping[str, Any]]) -> int:
    counts = {int(row["actual_relevant_count"]) for row in rows}
    if len(counts) != 1:
        raise ValueError("package relevant-count semantics are inconsistent")
    return counts.pop()


def _paired_directional_rate(rows: Sequence[Mapping[str, Any]]) -> float:
    pairs: dict[str, dict[bool, float]] = {}
    for row in rows:
        scenario_id = str(row["sample_id"]).split(":", 1)[0]
        pairs.setdefault(scenario_id, {})[bool(row["expected_ready"])] = float(
            row["score"]
        )
    complete = [pair for pair in pairs.values() if set(pair) == {False, True}]
    if not complete:
        raise ValueError("package probability pairs are incomplete")
    return round(
        sum(pair[True] > pair[False] for pair in complete) / len(complete), 8
    )
