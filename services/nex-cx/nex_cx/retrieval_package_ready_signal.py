from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

from nex_cx.retrieval_confidence_candidate_diagnostics import (
    EXPANDED_CANDIDATE_RELEVANCE_SAMPLE_SCHEMA_VERSION,
)

CANDIDATE_PROBABILITY_MODEL_SCHEMA_VERSION = (
    "cx_retrieval_candidate_probability_model.v1"
)
PACKAGE_READY_SIGNAL_SCHEMA_VERSION = "cx_retrieval_package_ready_signal.v1"
CANDIDATE_SCORE_SCHEMA_VERSION = "cx_retrieval_candidate_profile_score.v1"
CANDIDATE_PROBABILITY_POLICY_ID = "cx_monotonic_platt_candidate_probability_v1"
PACKAGE_READY_SIGNAL_POLICY_ID = "cx_probability_at_least_two_relevant_v1"
EXPECTED_CANDIDATE_COUNT = 4
MINIMUM_TRAINING_CANDIDATE_COUNT = 8
DEFAULT_REGULARIZATION = 0.001
MAXIMUM_ITERATIONS = 100
CONVERGENCE_TOLERANCE = 1e-10


def score_candidate_relevance_samples(
    samples: Sequence[Mapping[str, Any]],
    *,
    profile: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Apply one frozen linear profile without using candidate truth as input."""
    profile_id, weights = _profile(profile)
    normalized = _candidate_samples(samples)
    scored: list[dict[str, Any]] = []
    for row in normalized:
        missing_fields = [
            field for field, _ in weights if field not in row["signals"]
        ]
        if missing_fields:
            raise ValueError("candidate score profile signal is missing")
        score = sum(
            float(row["signals"][field]) * weight for field, weight in weights
        )
        projected = {
            "score_schema_version": CANDIDATE_SCORE_SCHEMA_VERSION,
            "sample_id": row["sample_id"],
            "candidate_id": row["candidate_id"],
            "expected_relevant": row["expected_relevant"],
            "source_profile_id": profile_id,
            "candidate_score": round(score, 12),
        }
        projected["score_hash"] = semantic_sha256_hash_ref(projected)
        scored.append(projected)
    return sorted(scored, key=lambda row: (row["sample_id"], row["candidate_id"]))


def fit_candidate_probability_model(
    scored_candidates: Sequence[Mapping[str, Any]],
    *,
    source_profile_id: str,
    expected_binding: Mapping[str, Any],
    training_scope: str = "CALIBRATION_INNER_TRAINING",
    regularization: float = DEFAULT_REGULARIZATION,
) -> dict[str, Any]:
    """Fit a monotonic calibration-only Platt model deterministically."""
    normalized_profile_id = _required_string(
        source_profile_id, "source_profile_id"
    )
    rows = _scored_candidates(
        scored_candidates,
        expected_profile_id=normalized_profile_id,
    )
    scope = _required_string(training_scope, "training_scope")
    if "HOLDOUT" in scope.upper():
        raise ValueError("candidate probability training scope cannot be holdout")
    penalty = _positive_finite(regularization, "regularization")
    if penalty > 100.0:
        raise ValueError("regularization is invalid")

    scores = [float(row["candidate_score"]) for row in rows]
    labels = [1.0 if row["expected_relevant"] else 0.0 for row in rows]
    positives = int(sum(labels))
    negatives = len(labels) - positives
    if (
        len(rows) < MINIMUM_TRAINING_CANDIDATE_COUNT
        or positives < 2
        or negatives < 2
    ):
        raise ValueError("candidate probability training labels are incomplete")

    center = statistics.fmean(scores)
    scale = max(statistics.pstdev(scores), 1e-6)
    values = [(score - center) / scale for score in scores]
    intercept = math.log((positives + 0.5) / (negatives + 0.5))
    coefficient = 0.0
    converged = False
    iteration_count = 0
    for iteration_count in range(1, MAXIMUM_ITERATIONS + 1):
        probabilities = [
            _sigmoid(intercept + coefficient * value) for value in values
        ]
        weights = [probability * (1.0 - probability) for probability in probabilities]
        gradient_intercept = sum(
            probability - label
            for probability, label in zip(probabilities, labels, strict=True)
        )
        gradient_coefficient = sum(
            (probability - label) * value
            for probability, label, value in zip(
                probabilities, labels, values, strict=True
            )
        ) + penalty * coefficient
        if max(abs(gradient_intercept), abs(gradient_coefficient)) <= (
            CONVERGENCE_TOLERANCE
        ):
            converged = True
            break

        hessian_intercept = sum(weights)
        hessian_cross = sum(
            weight * value for weight, value in zip(weights, values, strict=True)
        )
        hessian_coefficient = sum(
            weight * value * value
            for weight, value in zip(weights, values, strict=True)
        ) + penalty
        determinant = (
            hessian_intercept * hessian_coefficient - hessian_cross * hessian_cross
        )
        if determinant <= 1e-18:
            break
        delta_intercept = (
            hessian_coefficient * gradient_intercept
            - hessian_cross * gradient_coefficient
        ) / determinant
        delta_coefficient = (
            hessian_intercept * gradient_coefficient
            - hessian_cross * gradient_intercept
        ) / determinant
        current_objective = _objective(
            values,
            labels,
            intercept=intercept,
            coefficient=coefficient,
            regularization=penalty,
        )
        accepted = False
        step = 1.0
        for _ in range(24):
            proposed_intercept = intercept - step * delta_intercept
            proposed_coefficient = max(
                0.0, coefficient - step * delta_coefficient
            )
            proposed_objective = _objective(
                values,
                labels,
                intercept=proposed_intercept,
                coefficient=proposed_coefficient,
                regularization=penalty,
            )
            if proposed_objective <= current_objective + 1e-12:
                accepted = True
                break
            step *= 0.5
        if not accepted:
            break
        change = max(
            abs(proposed_intercept - intercept),
            abs(proposed_coefficient - coefficient),
        )
        intercept = proposed_intercept
        coefficient = proposed_coefficient
        if change <= CONVERGENCE_TOLERANCE:
            converged = True
            break

    directional = coefficient > 1e-12
    status = (
        "CALIBRATION_ONLY_FITTED"
        if converged and directional
        else "REJECTED_NON_DIRECTIONAL_OR_UNCONVERGED"
    )
    model: dict[str, Any] = {
        "model_schema_version": CANDIDATE_PROBABILITY_MODEL_SCHEMA_VERSION,
        "policy_id": CANDIDATE_PROBABILITY_POLICY_ID,
        "status": status,
        "source_profile_id": normalized_profile_id,
        "training": {
            "scope": scope,
            "candidate_count": len(rows),
            "positive_count": positives,
            "negative_count": negatives,
            "candidate_set_hash": semantic_sha256_hash_ref(
                sorted(str(row["score_hash"]) for row in rows)
            ),
        },
        "binding": _binding(expected_binding),
        "parameters": {
            "transform": "MONOTONIC_PLATT_LOGISTIC_V1",
            "score_center": round(center, 12),
            "score_scale": round(scale, 12),
            "intercept": round(intercept, 12),
            "coefficient": round(coefficient, 12),
            "regularization": penalty,
            "iteration_count": iteration_count,
            "converged": converged,
            "monotonic_non_decreasing": directional,
        },
        "safety": {
            "candidate_truth_runtime_input_permitted": False,
            "holdout_access_permitted": False,
            "runtime_activation_permitted": False,
            "ready_threshold_selected": False,
        },
    }
    model["model_hash"] = semantic_sha256_hash_ref(model)
    return model


def predict_candidate_relevance_probability(
    candidate_score: float,
    *,
    model: Mapping[str, Any],
) -> float:
    """Project a candidate score through one admitted calibration-only model."""
    normalized = _probability_model(model)
    score = _bounded_score(candidate_score, "candidate_score")
    return _predict_from_normalized(score, normalized)


def build_package_ready_signal(
    candidates: Sequence[Mapping[str, Any]],
    *,
    model: Mapping[str, Any],
    expected_binding: Mapping[str, Any],
) -> dict[str, Any]:
    """Estimate P(at least two relevant candidates) without making a decision."""
    normalized_model = _probability_model(model)
    binding = _binding(expected_binding)
    if normalized_model["binding"] != binding:
        raise ValueError("candidate probability model binding is invalid")
    rows = _package_candidates(candidates)
    projected = [
        {
            "candidate_id": row["candidate_id"],
            "candidate_score": row["candidate_score"],
            "relevance_probability": _predict_from_normalized(
                row["candidate_score"], normalized_model
            ),
        }
        for row in rows
    ]
    projected.sort(
        key=lambda row: (-row["relevance_probability"], row["candidate_id"])
    )
    probabilities = [float(row["relevance_probability"]) for row in projected]
    count_distribution = _relevant_count_distribution(probabilities)
    ready_probability = sum(count_distribution[2:])
    features = {
        "ready_probability_at_least_two": round(ready_probability, 12),
        "expected_relevant_count": round(sum(probabilities), 12),
        "second_candidate_probability": probabilities[1],
        "top_two_probability_mean": round(statistics.fmean(probabilities[:2]), 12),
        "second_third_probability_gap": round(
            max(0.0, probabilities[1] - probabilities[2]), 12
        ),
        "candidate_probability_spread": round(
            probabilities[0] - probabilities[-1], 12
        ),
        "probability_at_least_half_count": sum(
            probability >= 0.5 for probability in probabilities
        ),
        "historical_second_highest_candidate_score": sorted(
            (float(row["candidate_score"]) for row in rows), reverse=True
        )[1],
    }
    result: dict[str, Any] = {
        "signal_schema_version": PACKAGE_READY_SIGNAL_SCHEMA_VERSION,
        "policy_id": PACKAGE_READY_SIGNAL_POLICY_ID,
        "status": "CALIBRATION_ONLY_PROJECTED",
        "source_profile_id": normalized_model["source_profile_id"],
        "candidate_probability_model_hash": normalized_model["model_hash"],
        "binding": binding,
        "candidate_probabilities": projected,
        "relevant_count_probability": {
            str(count): round(probability, 12)
            for count, probability in enumerate(count_distribution)
        },
        "features": features,
        "semantics": {
            "ready_definition": "AT_LEAST_TWO_RELEVANT_CANDIDATES",
            "aggregation": "POISSON_BINOMIAL_V1",
            "conditional_independence_assumption": True,
            "candidate_truth_runtime_input_permitted": False,
            "package_threshold": None,
            "ready_decision": None,
        },
        "safety": {
            "diagnostic_only": True,
            "holdout_access_permitted": False,
            "profile_selection_permitted": False,
            "threshold_selection_permitted": False,
            "runtime_activation_permitted": False,
        },
    }
    result["signal_hash"] = semantic_sha256_hash_ref(result)
    return result


def _candidate_samples(
    samples: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if not _sequence(samples):
        raise TypeError("candidate relevance samples are invalid")
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    packages: dict[str, list[dict[str, Any]]] = {}
    for value in samples:
        if not isinstance(value, Mapping):
            raise TypeError("candidate relevance sample is invalid")
        raw = dict(value)
        sample_hash = _required_string(raw.pop("sample_hash", None), "sample_hash")
        if sample_hash != semantic_sha256_hash_ref(raw):
            raise ValueError("candidate relevance sample integrity is invalid")
        if (
            raw.get("sample_schema_version")
            != EXPANDED_CANDIDATE_RELEVANCE_SAMPLE_SCHEMA_VERSION
        ):
            raise ValueError("candidate relevance sample schema is invalid")
        sample_id = _required_string(raw.get("sample_id"), "sample_id")
        candidate_id = _required_string(raw.get("candidate_id"), "candidate_id")
        identity = (sample_id, candidate_id)
        if identity in seen:
            raise ValueError("candidate relevance sample identity is duplicated")
        expected_ready = raw.get("expected_ready")
        expected_relevant = raw.get("expected_relevant")
        signals = raw.get("signals")
        if (
            type(expected_ready) is not bool
            or type(expected_relevant) is not bool
            or not isinstance(signals, Mapping)
        ):
            raise TypeError("candidate relevance sample values are invalid")
        normalized = {
            "sample_id": sample_id,
            "candidate_id": candidate_id,
            "expected_ready": expected_ready,
            "expected_relevant": expected_relevant,
            "signals": {
                _required_string(field, "signal_field"): _bounded_score(
                    signal, str(field)
                )
                for field, signal in signals.items()
            },
        }
        if not normalized["signals"]:
            raise ValueError("candidate relevance sample signals are missing")
        seen.add(identity)
        rows.append(normalized)
        packages.setdefault(sample_id, []).append(normalized)
    _validate_package_truth(packages)
    return rows


def _scored_candidates(
    values: Sequence[Mapping[str, Any]],
    *,
    expected_profile_id: str,
) -> list[dict[str, Any]]:
    if not _sequence(values):
        raise TypeError("scored candidates are invalid")
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    packages: dict[str, list[dict[str, Any]]] = {}
    for value in values:
        if not isinstance(value, Mapping):
            raise TypeError("scored candidate is invalid")
        raw = dict(value)
        score_hash = _required_string(raw.pop("score_hash", None), "score_hash")
        if score_hash != semantic_sha256_hash_ref(raw):
            raise ValueError("scored candidate integrity is invalid")
        if raw.get("score_schema_version") != CANDIDATE_SCORE_SCHEMA_VERSION:
            raise ValueError("scored candidate schema is invalid")
        sample_id = _required_string(raw.get("sample_id"), "sample_id")
        candidate_id = _required_string(raw.get("candidate_id"), "candidate_id")
        profile_id = _required_string(
            raw.get("source_profile_id"), "source_profile_id"
        )
        expected_relevant = raw.get("expected_relevant")
        if profile_id != expected_profile_id:
            raise ValueError("scored candidate profile binding is invalid")
        if type(expected_relevant) is not bool:
            raise TypeError("scored candidate truth is invalid")
        identity = (sample_id, candidate_id)
        if identity in seen:
            raise ValueError("scored candidate identity is duplicated")
        normalized = {
            **raw,
            "score_hash": score_hash,
            "sample_id": sample_id,
            "candidate_id": candidate_id,
            "expected_relevant": expected_relevant,
            "candidate_score": _bounded_score(
                raw.get("candidate_score"), "candidate_score"
            ),
        }
        seen.add(identity)
        rows.append(normalized)
        packages.setdefault(sample_id, []).append(normalized)
    if not packages or any(
        len(package) != EXPECTED_CANDIDATE_COUNT
        for package in packages.values()
    ):
        raise ValueError("scored candidate package cardinality is invalid")
    if any(
        sum(bool(row["expected_relevant"]) for row in package) not in {0, 2}
        for package in packages.values()
    ):
        raise ValueError("scored candidate package truth is invalid")
    return sorted(rows, key=lambda row: (row["sample_id"], row["candidate_id"]))


def _validate_package_truth(
    packages: Mapping[str, Sequence[Mapping[str, Any]]],
) -> None:
    if not packages:
        raise ValueError("candidate relevance packages are missing")
    for rows in packages.values():
        expected_ready = {row["expected_ready"] for row in rows}
        relevant_count = sum(bool(row["expected_relevant"]) for row in rows)
        if (
            len(rows) != EXPECTED_CANDIDATE_COUNT
            or len(expected_ready) != 1
            or relevant_count != (2 if rows[0]["expected_ready"] else 0)
        ):
            raise ValueError("candidate relevance package semantics are invalid")


def _profile(profile: Mapping[str, Any]) -> tuple[str, list[tuple[str, float]]]:
    if not isinstance(profile, Mapping):
        raise TypeError("candidate score profile is invalid")
    profile_id = _required_string(profile.get("profile_id"), "profile_id")
    raw_weights = profile.get("weights")
    if not _sequence(raw_weights):
        raise TypeError("candidate score profile weights are invalid")
    weights: list[tuple[str, float]] = []
    seen: set[str] = set()
    for item in raw_weights:
        if not isinstance(item, Mapping):
            raise TypeError("candidate score profile weight is invalid")
        field = _required_string(item.get("field"), "field")
        weight = _positive_finite(item.get("weight"), "weight")
        if field in seen:
            raise ValueError("candidate score profile field is duplicated")
        seen.add(field)
        weights.append((field, weight))
    if not weights or not math.isclose(
        sum(weight for _, weight in weights), 1.0, abs_tol=1e-9
    ):
        raise ValueError("candidate score profile weights are invalid")
    return profile_id, weights


def _probability_model(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("candidate probability model is invalid")
    model = dict(value)
    model_hash = _required_string(model.pop("model_hash", None), "model_hash")
    if model_hash != semantic_sha256_hash_ref(model):
        raise ValueError("candidate probability model integrity is invalid")
    if (
        model.get("model_schema_version")
        != CANDIDATE_PROBABILITY_MODEL_SCHEMA_VERSION
        or model.get("policy_id") != CANDIDATE_PROBABILITY_POLICY_ID
        or model.get("status") != "CALIBRATION_ONLY_FITTED"
    ):
        raise ValueError("candidate probability model is not admitted")
    parameters = model.get("parameters")
    if not isinstance(parameters, Mapping):
        raise TypeError("candidate probability model parameters are invalid")
    normalized_parameters = {
        "score_center": _bounded_score(parameters.get("score_center"), "score_center"),
        "score_scale": _positive_finite(parameters.get("score_scale"), "score_scale"),
        "intercept": _finite(parameters.get("intercept"), "intercept"),
        "coefficient": _positive_finite(
            parameters.get("coefficient"), "coefficient"
        ),
    }
    return {
        **model,
        "model_hash": model_hash,
        "source_profile_id": _required_string(
            model.get("source_profile_id"), "source_profile_id"
        ),
        "binding": _binding(model.get("binding")),
        "parameters": normalized_parameters,
    }


def _package_candidates(values: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not _sequence(values) or len(values) != EXPECTED_CANDIDATE_COUNT:
        raise ValueError("package candidates require exactly four items")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, Mapping):
            raise TypeError("package candidate is invalid")
        candidate_id = _required_string(value.get("candidate_id"), "candidate_id")
        if candidate_id in seen:
            raise ValueError("package candidate identity is duplicated")
        seen.add(candidate_id)
        rows.append(
            {
                "candidate_id": candidate_id,
                "candidate_score": _bounded_score(
                    value.get("candidate_score"), "candidate_score"
                ),
            }
        )
    return rows


def _predict_from_normalized(score: float, model: Mapping[str, Any]) -> float:
    parameters = model["parameters"]
    value = (score - parameters["score_center"]) / parameters["score_scale"]
    return round(
        _sigmoid(parameters["intercept"] + parameters["coefficient"] * value),
        12,
    )


def _relevant_count_distribution(probabilities: Sequence[float]) -> list[float]:
    distribution = [1.0]
    for probability in probabilities:
        updated = [0.0] * (len(distribution) + 1)
        for count, current in enumerate(distribution):
            updated[count] += current * (1.0 - probability)
            updated[count + 1] += current * probability
        distribution = updated
    return distribution


def _objective(
    values: Sequence[float],
    labels: Sequence[float],
    *,
    intercept: float,
    coefficient: float,
    regularization: float,
) -> float:
    return sum(
        _softplus(intercept + coefficient * value)
        - label * (intercept + coefficient * value)
        for value, label in zip(values, labels, strict=True)
    ) + 0.5 * regularization * coefficient * coefficient


def _softplus(value: float) -> float:
    if value > 0.0:
        return value + math.log1p(math.exp(-value))
    return math.log1p(math.exp(value))


def _sigmoid(value: float) -> float:
    if value >= 0.0:
        factor = math.exp(-value)
        return 1.0 / (1.0 + factor)
    factor = math.exp(value)
    return factor / (1.0 + factor)


def _binding(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping) or not value:
        raise TypeError("candidate probability binding is invalid")
    return {
        _required_string(key, "binding_key"): _required_string(item, str(key))
        for key, item in value.items()
    }


def _bounded_score(value: object, field: str) -> float:
    numeric = _finite(value, field)
    if numeric < 0.0 or numeric > 1.0:
        raise ValueError(f"{field} is invalid")
    return numeric


def _positive_finite(value: object, field: str) -> float:
    numeric = _finite(value, field)
    if numeric <= 0.0:
        raise ValueError(f"{field} is invalid")
    return numeric


def _finite(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} is invalid")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError(f"{field} is invalid")
    return numeric


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is invalid")
    return value.strip()


def _sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    )
