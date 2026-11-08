from __future__ import annotations

import math
import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

from nex_cx.retrieval_confidence_candidate_diagnostics import (
    build_expanded_candidate_relevance_calibration_samples,
)
from nex_cx.retrieval_package_ready_calibrator import (
    PACKAGE_ORDINAL_FEATURE_FIELDS,
    build_package_ordinal_features,
    score_package_ordinal_features,
    validate_package_ordinal_calibrator_design,
)
from nex_cx.retrieval_package_ready_signal import (
    build_package_ready_signal,
    fit_candidate_probability_model,
    predict_candidate_relevance_probability,
    score_candidate_relevance_samples,
)

PACKAGE_IDENTIFIABILITY_AUDIT_SCHEMA_VERSION = (
    "cx_retrieval_package_identifiability_audit.v1"
)
PACKAGE_IDENTIFIABILITY_AUDIT_POLICY_ID = (
    "cx_package_ready_identifiability_error_topology_v1"
)
POSITIVE_ROLES = frozenset({"PRIMARY_ANSWER", "SUPPORTING_ANSWER"})
NEGATIVE_ROLES = frozenset(
    {
        "HARD_NON_ANSWER",
        "RELATED_NON_ANSWER",
        "CONTRADICTORY_NON_ANSWER",
        "EASY_NON_ANSWER",
    }
)
ALLOWED_ROLES = POSITIVE_ROLES | NEGATIVE_ROLES


def audit_package_ready_identifiability(
    observations: Sequence[Mapping[str, Any]],
    *,
    candidate_profiles: Sequence[Mapping[str, Any]],
    ordinal_design: Mapping[str, Any],
    expected_binding: Mapping[str, Any],
    package_metadata: Mapping[str, Mapping[str, Any]],
    maximum_false_ready_rate: float = 0.10,
    minimum_ready_recall: float = 0.80,
) -> dict[str, Any]:
    """Diagnose whether frozen retrieval signals can identify package READY."""
    samples = build_expanded_candidate_relevance_calibration_samples(observations)
    profiles = _candidate_profiles(candidate_profiles)
    package_design = validate_package_ordinal_calibrator_design(ordinal_design)
    metadata = _package_metadata(package_metadata, samples)
    roles = _role_index(observations, samples)
    false_ready_limit = _rate(maximum_false_ready_rate, "maximum_false_ready_rate")
    recall_floor = _rate(minimum_ready_recall, "minimum_ready_recall")

    profile_diagnostics: list[dict[str, Any]] = []
    combinations: list[dict[str, Any]] = []
    package_rows_by_combination: dict[str, list[dict[str, Any]]] = {}
    for profile in profiles:
        diagnostic, rows = _audit_candidate_profile(
            samples,
            profile=profile,
            package_profiles=package_design["profile_shortlist"],
            package_design_hash=package_design["design_hash"],
            expected_binding=expected_binding,
            metadata=metadata,
            roles=roles,
            maximum_false_ready_rate=false_ready_limit,
            minimum_ready_recall=recall_floor,
        )
        profile_diagnostics.append(diagnostic)
        combinations.extend(diagnostic.get("package_combinations", []))
        package_rows_by_combination.update(rows)

    diagnosed = [row for row in profile_diagnostics if row["status"] == "DIAGNOSED"]
    feasible = [row for row in combinations if row["constraint_feasible"]]
    selected = _select_diagnostic_combination(combinations)
    candidate_directional = bool(diagnosed) and max(
        float(row["candidate_auc"]) for row in diagnosed
    ) >= 0.70
    existing_signal_feasible = bool(feasible)
    if existing_signal_feasible:
        decision = "EXISTING_SIGNAL_RECALIBRATION_JUSTIFIED"
    elif candidate_directional:
        decision = "ANSWERABILITY_SIGNAL_REQUIRED"
    else:
        decision = "SIGNAL_AND_DATASET_REVIEW_REQUIRED"

    selected_rows = (
        package_rows_by_combination.get(str(selected["combination_id"]), [])
        if selected is not None
        else []
    )
    selected_threshold = (
        float(selected["best_safety_point"]["threshold"])
        if selected is not None
        else None
    )
    checks = {
        "all_candidate_profiles_diagnosed": len(diagnosed) == len(profiles),
        "all_frozen_combinations_evaluated": len(combinations)
        == len(profiles) * len(package_design["profile_shortlist"]),
        "candidate_signal_directionality_recorded": bool(diagnosed),
        "package_semantics_validated": True,
        "holdout_access_prohibited": True,
        "runtime_activation_prohibited": True,
    }
    result: dict[str, Any] = {
        "audit_schema_version": PACKAGE_IDENTIFIABILITY_AUDIT_SCHEMA_VERSION,
        "policy_id": PACKAGE_IDENTIFIABILITY_AUDIT_POLICY_ID,
        "status": "DIAGNOSED" if all(checks.values()) else "INCONCLUSIVE",
        "decision": decision if all(checks.values()) else "STOP_FOR_REVIEW",
        "constraints": {
            "maximum_false_ready_rate": false_ready_limit,
            "minimum_ready_recall": recall_floor,
            "point_constraints_remain_authoritative": True,
        },
        "dataset": {
            "partition": "CALIBRATION",
            "scenario_count": len(metadata) // 2,
            "package_count": len(metadata),
            "candidate_count": len(samples),
            "domain_counts": _metadata_counts(metadata, "domain"),
            "language_profile_counts": _metadata_counts(
                metadata, "language_profile"
            ),
        },
        "profile_diagnostics": profile_diagnostics,
        "identifiability": {
            "candidate_signal_directional": candidate_directional,
            "existing_package_signal_constraint_feasible": (
                existing_signal_feasible
            ),
            "feasible_combination_ids": sorted(
                str(row["combination_id"]) for row in feasible
            ),
            "selected_diagnostic_combination": selected,
            "error_topology": (
                _error_topology(selected_rows, selected_threshold)
                if selected_rows and selected_threshold is not None
                else None
            ),
            "threshold_relaxation_authorized": False,
            "dataset_or_label_change_authorized": False,
            "model_revision_change_authorized": False,
        },
        "next_contract": {
            "required_signal": (
                "PROVIDER_NEUTRAL_ANSWER_SUPPORT_AND_CONTRADICTION_EVIDENCE"
                if decision == "ANSWERABILITY_SIGNAL_REQUIRED"
                else None
            ),
            "candidate_truth_runtime_input_permitted": False,
            "calibration_partition_only": True,
            "holdout_access_permitted": False,
            "runtime_activation_permitted": False,
        },
        "checks": checks,
    }
    result["audit_hash"] = semantic_sha256_hash_ref(result)
    return result


def _audit_candidate_profile(
    samples: Sequence[Mapping[str, Any]],
    *,
    profile: Mapping[str, Any],
    package_profiles: Sequence[Mapping[str, Any]],
    package_design_hash: str,
    expected_binding: Mapping[str, Any],
    metadata: Mapping[str, Mapping[str, str]],
    roles: Mapping[tuple[str, str], str],
    maximum_false_ready_rate: float,
    minimum_ready_recall: float,
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    scored = score_candidate_relevance_samples(samples, profile=profile)
    model = fit_candidate_probability_model(
        scored,
        source_profile_id=str(profile["profile_id"]),
        expected_binding=expected_binding,
        training_scope="CALIBRATION_FULL_IDENTIFIABILITY_DIAGNOSTIC_ONLY",
    )
    if model["status"] != "CALIBRATION_ONLY_FITTED":
        return (
            {
                "candidate_profile_id": profile["profile_id"],
                "status": "PROBABILITY_MODEL_REJECTED",
                "candidate_probability_model_status": model["status"],
            },
            {},
        )

    truths = {
        (str(row["sample_id"]), str(row["candidate_id"])): {
            "expected_ready": bool(row["expected_ready"]),
            "expected_relevant": bool(row["expected_relevant"]),
        }
        for row in samples
    }
    probabilities: list[dict[str, Any]] = []
    package_candidates: dict[str, list[dict[str, Any]]] = defaultdict(list)
    package_labels: dict[str, bool] = {}
    package_relevant_counts: dict[str, int] = defaultdict(int)
    for row in scored:
        sample_id = str(row["sample_id"])
        candidate_id = str(row["candidate_id"])
        truth = truths[(sample_id, candidate_id)]
        probability = predict_candidate_relevance_probability(
            float(row["candidate_score"]), model=model
        )
        role = roles[(sample_id, candidate_id)]
        probabilities.append(
            {
                "sample_id": sample_id,
                "candidate_id": candidate_id,
                "role": role,
                "expected_relevant": truth["expected_relevant"],
                "probability": probability,
            }
        )
        package_candidates[sample_id].append(
            {
                "candidate_id": candidate_id,
                "candidate_score": float(row["candidate_score"]),
            }
        )
        package_labels[sample_id] = truth["expected_ready"]
        package_relevant_counts[sample_id] += int(truth["expected_relevant"])

    _validate_package_semantics(package_candidates, package_labels, package_relevant_counts)
    package_features: dict[str, dict[str, Any]] = {}
    for sample_id, candidates in sorted(package_candidates.items()):
        signal = build_package_ready_signal(
            candidates,
            model=model,
            expected_binding=expected_binding,
        )
        package_features[sample_id] = build_package_ordinal_features(signal)

    combination_rows: dict[str, list[dict[str, Any]]] = {}
    combinations: list[dict[str, Any]] = []
    for package_profile in package_profiles:
        combination_id = f"{profile['profile_id']}::{package_profile['profile_id']}"
        rows = [
            {
                "sample_id": sample_id,
                "scenario_id": sample_id.split(":", 1)[0],
                "expected_ready": package_labels[sample_id],
                "score": float(
                    score_package_ordinal_features(
                        package_features[sample_id],
                        profile=package_profile,
                        design_hash=package_design_hash,
                    )["ordinal_score"]
                ),
                "domain": metadata[sample_id]["domain"],
                "language_profile": metadata[sample_id]["language_profile"],
            }
            for sample_id in sorted(package_candidates)
        ]
        topology = _threshold_topology(
            rows,
            maximum_false_ready_rate=maximum_false_ready_rate,
            minimum_ready_recall=minimum_ready_recall,
        )
        combinations.append(
            {
                "combination_id": combination_id,
                "candidate_profile_id": profile["profile_id"],
                "package_profile_id": package_profile["profile_id"],
                "package_auc": round(
                    _auc([(float(row["score"]), bool(row["expected_ready"])) for row in rows]),
                    8,
                ),
                "paired_directional_rate": _paired_directional_rate(rows),
                **topology,
            }
        )
        combination_rows[combination_id] = rows

    feature_values = {
        field: [
            float(package_features[sample_id]["features"][field])
            for sample_id in sorted(package_features)
        ]
        for field in PACKAGE_ORDINAL_FEATURE_FIELDS
    }
    return (
        {
            "candidate_profile_id": profile["profile_id"],
            "status": "DIAGNOSED",
            "candidate_probability_model_hash": model["model_hash"],
            "candidate_auc": round(
                _auc(
                    [
                        (float(row["probability"]), bool(row["expected_relevant"]))
                        for row in probabilities
                    ]
                ),
                8,
            ),
            "role_probability_distributions": _role_distributions(probabilities),
            "answer_support_vs_negative_role_auc": _role_overlap(probabilities),
            "package_feature_correlations": _feature_correlations(feature_values),
            "package_combinations": combinations,
        },
        combination_rows,
    )


def _threshold_topology(
    rows: Sequence[Mapping[str, Any]],
    *,
    maximum_false_ready_rate: float,
    minimum_ready_recall: float,
) -> dict[str, Any]:
    scores = sorted({float(row["score"]) for row in rows}, reverse=True)
    if not scores:
        raise ValueError("package identifiability scores are missing")
    thresholds = [math.nextafter(scores[0], math.inf), *scores]
    points = [_threshold_metrics(rows, threshold) for threshold in thresholds]
    frontier: list[dict[str, Any]] = []
    highest_recall = -1.0
    for point in sorted(
        points,
        key=lambda row: (
            float(row["false_ready_rate"]),
            -float(row["ready_recall"]),
            -float(row["threshold"]),
        ),
    ):
        if float(point["ready_recall"]) > highest_recall:
            frontier.append(point)
            highest_recall = float(point["ready_recall"])
    safe = [
        row
        for row in points
        if float(row["false_ready_rate"]) <= maximum_false_ready_rate
    ]
    recall_eligible = [
        row for row in points if float(row["ready_recall"]) >= minimum_ready_recall
    ]
    best_safety = max(
        safe,
        key=lambda row: (
            float(row["ready_recall"]),
            float(row["balanced_accuracy"]),
            -float(row["false_ready_rate"]),
        ),
    )
    best_recall = min(
        recall_eligible,
        key=lambda row: (
            float(row["false_ready_rate"]),
            -float(row["balanced_accuracy"]),
        ),
    )
    return {
        "constraint_feasible": any(
            float(row["false_ready_rate"]) <= maximum_false_ready_rate
            and float(row["ready_recall"]) >= minimum_ready_recall
            for row in points
        ),
        "best_safety_point": best_safety,
        "best_recall_floor_point": best_recall,
        "pareto_frontier": frontier,
        "threshold_count": len(points),
    }


def _threshold_metrics(
    rows: Sequence[Mapping[str, Any]], threshold: float
) -> dict[str, Any]:
    positive = [row for row in rows if bool(row["expected_ready"])]
    negative = [row for row in rows if not bool(row["expected_ready"])]
    if not positive or not negative:
        raise ValueError("package identifiability labels are incomplete")
    true_ready = sum(float(row["score"]) >= threshold for row in positive)
    false_ready = sum(float(row["score"]) >= threshold for row in negative)
    recall = true_ready / len(positive)
    false_ready_rate = false_ready / len(negative)
    return {
        "threshold": round(threshold, 12),
        "true_ready": true_ready,
        "false_ready": false_ready,
        "false_low_confidence": len(positive) - true_ready,
        "true_low_confidence": len(negative) - false_ready,
        "ready_recall": round(recall, 8),
        "false_ready_rate": round(false_ready_rate, 8),
        "balanced_accuracy": round((recall + 1.0 - false_ready_rate) / 2.0, 8),
    }


def _select_diagnostic_combination(
    combinations: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    if not combinations:
        return None
    selected = max(
        combinations,
        key=lambda row: (
            float(row["best_safety_point"]["ready_recall"]),
            float(row["best_safety_point"]["balanced_accuracy"]),
            -float(row["best_safety_point"]["false_ready_rate"]),
            float(row["package_auc"]),
            str(row["combination_id"]),
        ),
    )
    return {
        "combination_id": selected["combination_id"],
        "candidate_profile_id": selected["candidate_profile_id"],
        "package_profile_id": selected["package_profile_id"],
        "package_auc": selected["package_auc"],
        "paired_directional_rate": selected["paired_directional_rate"],
        "constraint_feasible": selected["constraint_feasible"],
        "best_safety_point": selected["best_safety_point"],
        "best_recall_floor_point": selected["best_recall_floor_point"],
    }


def _error_topology(
    rows: Sequence[Mapping[str, Any]], threshold: float
) -> dict[str, Any]:
    return {
        "domain": _stratum_metrics(rows, threshold, "domain"),
        "language_profile": _stratum_metrics(
            rows, threshold, "language_profile"
        ),
    }


def _stratum_metrics(
    rows: Sequence[Mapping[str, Any]], threshold: float, field: str
) -> dict[str, Any]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row[field])].append(row)
    return {
        name: _threshold_metrics(values, threshold)
        for name, values in sorted(groups.items())
    }


def _role_distributions(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, float | int]]:
    groups: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        groups[str(row["role"])].append(float(row["probability"]))
    return {
        role: {"count": len(values), **_distribution(values)}
        for role, values in sorted(groups.items())
    }


def _role_overlap(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    by_role: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        by_role[str(row["role"])].append(float(row["probability"]))
    answer_support = [
        score for role in POSITIVE_ROLES for score in by_role.get(role, [])
    ]
    return {
        role: round(
            _auc(
                [
                    *[(score, True) for score in answer_support],
                    *[(score, False) for score in by_role.get(role, [])],
                ]
            ),
            8,
        )
        for role in sorted(NEGATIVE_ROLES)
    }


def _feature_correlations(
    values: Mapping[str, Sequence[float]],
) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    fields = list(PACKAGE_ORDINAL_FEATURE_FIELDS)
    for index, left in enumerate(fields):
        for right in fields[index + 1 :]:
            result[f"{left}::{right}"] = _pearson(values[left], values[right])
    return result


def _pearson(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right) or not left:
        raise ValueError("package feature correlation values are invalid")
    left_mean = statistics.fmean(left)
    right_mean = statistics.fmean(right)
    numerator = sum(
        (a - left_mean) * (b - right_mean)
        for a, b in zip(left, right, strict=True)
    )
    left_scale = math.sqrt(sum((value - left_mean) ** 2 for value in left))
    right_scale = math.sqrt(sum((value - right_mean) ** 2 for value in right))
    if left_scale == 0.0 or right_scale == 0.0:
        return None
    return round(numerator / (left_scale * right_scale), 8)


def _candidate_profiles(
    values: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise TypeError("package identifiability candidate profiles are invalid")
    profiles: list[dict[str, Any]] = []
    for value in values:
        if not isinstance(value, Mapping):
            raise TypeError("package identifiability candidate profile is invalid")
        profile_id = value.get("profile_id")
        fields = value.get("feature_fields")
        weights = value.get("weights")
        if (
            not isinstance(profile_id, str)
            or not profile_id.strip()
            or isinstance(fields, (str, bytes))
            or not isinstance(fields, Sequence)
            or not isinstance(weights, Mapping)
        ):
            raise TypeError("package identifiability candidate profile is invalid")
        profiles.append(
            {
                "profile_id": profile_id.strip(),
                "weights": [
                    {"field": str(field), "weight": weights.get(field)}
                    for field in fields
                ],
            }
        )
    if not profiles or len({row["profile_id"] for row in profiles}) != len(profiles):
        raise ValueError("package identifiability candidate profiles are missing")
    return profiles


def _package_metadata(
    values: Mapping[str, Mapping[str, Any]],
    samples: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, str]]:
    if not isinstance(values, Mapping):
        raise TypeError("package identifiability metadata is invalid")
    sample_ids = {str(row["sample_id"]) for row in samples}
    if set(values) != sample_ids:
        raise ValueError("package identifiability metadata coverage is invalid")
    normalized: dict[str, dict[str, str]] = {}
    for sample_id, value in values.items():
        if not isinstance(value, Mapping):
            raise TypeError("package identifiability metadata row is invalid")
        normalized[str(sample_id)] = {
            "domain": _required_string(value.get("domain"), "domain"),
            "language_profile": _required_string(
                value.get("language_profile"), "language_profile"
            ),
        }
    return normalized


def _role_index(
    observations: Sequence[Mapping[str, Any]],
    samples: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str], str]:
    expected = {
        (str(row["sample_id"]), str(row["candidate_id"])): bool(
            row["expected_relevant"]
        )
        for row in samples
    }
    roles: dict[tuple[str, str], str] = {}
    for value in observations:
        key = (str(value.get("sample_id")), str(value.get("candidate_id")))
        role = _required_string(value.get("evidence_role"), "evidence_role")
        if role not in ALLOWED_ROLES or key not in expected:
            raise ValueError("package identifiability evidence role is invalid")
        if expected[key] is not (role in POSITIVE_ROLES):
            raise ValueError("package identifiability evidence role label is invalid")
        if key in roles:
            raise ValueError("package identifiability evidence role is duplicated")
        roles[key] = role
    if set(roles) != set(expected):
        raise ValueError("package identifiability evidence role coverage is invalid")
    return roles


def _validate_package_semantics(
    packages: Mapping[str, Sequence[Mapping[str, Any]]],
    labels: Mapping[str, bool],
    relevant_counts: Mapping[str, int],
) -> None:
    if any(len(rows) != 4 for rows in packages.values()) or any(
        relevant_counts[sample_id] != (2 if labels[sample_id] else 0)
        for sample_id in packages
    ):
        raise ValueError("package identifiability package semantics are invalid")


def _metadata_counts(
    metadata: Mapping[str, Mapping[str, str]], field: str
) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for value in metadata.values():
        counts[value[field]] += 1
    return dict(sorted(counts.items()))


def _paired_directional_rate(rows: Sequence[Mapping[str, Any]]) -> float:
    pairs: dict[str, dict[bool, float]] = defaultdict(dict)
    for row in rows:
        pairs[str(row["scenario_id"])][bool(row["expected_ready"])] = float(
            row["score"]
        )
    if not pairs or any(set(pair) != {False, True} for pair in pairs.values()):
        raise ValueError("package identifiability scenario pairs are incomplete")
    return round(
        sum(pair[True] > pair[False] for pair in pairs.values()) / len(pairs), 8
    )


def _auc(values: Sequence[tuple[float, bool]]) -> float:
    positives = [score for score, label in values if label]
    negatives = [score for score, label in values if not label]
    if not positives or not negatives:
        raise ValueError("package identifiability AUC labels are incomplete")
    wins = sum(
        1.0 if positive > negative else 0.5 if positive == negative else 0.0
        for positive in positives
        for negative in negatives
    )
    return wins / (len(positives) * len(negatives))


def _distribution(values: Sequence[float]) -> dict[str, float]:
    if not values:
        raise ValueError("package identifiability distribution is missing")
    ordered = sorted(values)
    return {
        "minimum": round(ordered[0], 8),
        "maximum": round(ordered[-1], 8),
        "mean": round(statistics.fmean(ordered), 8),
        "median": round(statistics.median(ordered), 8),
    }


def _rate(value: object, field: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(float(value))
        or not 0.0 <= float(value) <= 1.0
    ):
        raise ValueError(f"{field} is invalid")
    return float(value)


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is invalid")
    return value.strip()
