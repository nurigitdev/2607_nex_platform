from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

from nex_cx.retrieval_package_ready_signal import (
    PACKAGE_READY_SIGNAL_POLICY_ID,
    PACKAGE_READY_SIGNAL_SCHEMA_VERSION,
)

PACKAGE_ORDINAL_DESIGN_SCHEMA_VERSION = (
    "cx_retrieval_package_ordinal_calibrator_design.v1"
)
PACKAGE_ORDINAL_FEATURE_SCHEMA_VERSION = (
    "cx_retrieval_package_ordinal_features.v1"
)
PACKAGE_ORDINAL_SCORE_SCHEMA_VERSION = "cx_retrieval_package_ordinal_score.v1"
PACKAGE_ORDINAL_POLICY_ID = "cx_dependence_robust_package_ordinal_score_v1"
PACKAGE_ORDINAL_FEATURE_FIELDS = (
    "expected_relevant_fraction",
    "second_candidate_probability",
    "top_two_probability_mean",
    "probability_at_least_half_fraction",
)
EXPECTED_CANDIDATE_COUNT = 4


def validate_package_ordinal_calibrator_design(
    design: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate and hash the frozen, calibration-only ordinal design."""
    if not isinstance(design, Mapping):
        raise TypeError("package ordinal calibrator design is invalid")
    normalized = dict(design)
    if (
        normalized.get("design_schema_version")
        != PACKAGE_ORDINAL_DESIGN_SCHEMA_VERSION
        or normalized.get("policy_id") != PACKAGE_ORDINAL_POLICY_ID
        or normalized.get("status") != "FROZEN_CALIBRATION_ONLY"
    ):
        raise ValueError("package ordinal calibrator design identity is invalid")
    fields = normalized.get("feature_fields")
    if (
        list(fields) if isinstance(fields, list) else None
    ) != list(PACKAGE_ORDINAL_FEATURE_FIELDS):
        raise ValueError("package ordinal calibrator feature fields are invalid")
    profiles = _profiles(normalized.get("profile_shortlist"))
    safety = normalized.get("safety")
    if not isinstance(safety, Mapping) or any(
        safety.get(field) is not False
        for field in (
            "candidate_truth_runtime_input_permitted",
            "holdout_access_permitted",
            "runtime_activation_permitted",
        )
    ):
        raise ValueError("package ordinal calibrator safety is invalid")
    result = {
        **normalized,
        "profile_shortlist": profiles,
    }
    result["design_hash"] = semantic_sha256_hash_ref(result)
    return result


def build_package_ordinal_features(
    package_signal: Mapping[str, Any],
) -> dict[str, Any]:
    """Project dependence-robust order statistics without candidate truth."""
    signal = _verified_package_signal(package_signal)
    features = _mapping(signal.get("features"), "package signal features")
    candidate_probabilities = signal.get("candidate_probabilities")
    if (
        isinstance(candidate_probabilities, (str, bytes))
        or not isinstance(candidate_probabilities, Sequence)
        or len(candidate_probabilities) != EXPECTED_CANDIDATE_COUNT
    ):
        raise ValueError("package signal candidate probabilities are invalid")
    values = {
        "expected_relevant_fraction": _bounded(
            features.get("expected_relevant_count"),
            "expected_relevant_count",
            upper=float(EXPECTED_CANDIDATE_COUNT),
        )
        / EXPECTED_CANDIDATE_COUNT,
        "second_candidate_probability": _bounded(
            features.get("second_candidate_probability"),
            "second_candidate_probability",
        ),
        "top_two_probability_mean": _bounded(
            features.get("top_two_probability_mean"),
            "top_two_probability_mean",
        ),
        "probability_at_least_half_fraction": _bounded(
            features.get("probability_at_least_half_count"),
            "probability_at_least_half_count",
            upper=float(EXPECTED_CANDIDATE_COUNT),
        )
        / EXPECTED_CANDIDATE_COUNT,
    }
    result: dict[str, Any] = {
        "feature_schema_version": PACKAGE_ORDINAL_FEATURE_SCHEMA_VERSION,
        "policy_id": PACKAGE_ORDINAL_POLICY_ID,
        "status": "CALIBRATION_ONLY_PROJECTED",
        "source_signal_hash": signal["signal_hash"],
        "source_candidate_probability_model_hash": signal[
            "candidate_probability_model_hash"
        ],
        "binding": signal["binding"],
        "features": {field: round(values[field], 12) for field in values},
        "semantics": {
            "output_kind": "ORDINAL_SCORE_NOT_PROBABILITY",
            "conditional_independence_assumption": False,
            "candidate_truth_runtime_input_permitted": False,
        },
        "safety": {
            "diagnostic_only": True,
            "holdout_access_permitted": False,
            "profile_selection_permitted": False,
            "threshold_selection_permitted": False,
            "runtime_activation_permitted": False,
        },
    }
    result["feature_hash"] = semantic_sha256_hash_ref(result)
    return result


def score_package_ordinal_features(
    feature_vector: Mapping[str, Any],
    *,
    profile: Mapping[str, Any],
    design_hash: str,
) -> dict[str, Any]:
    """Score one frozen profile without interpreting the result as probability."""
    features = _verified_feature_vector(feature_vector)
    normalized_profile = _profile(profile)
    normalized_design_hash = _hash_ref(design_hash, "design_hash")
    values = _mapping(features.get("features"), "package ordinal features")
    score = sum(
        float(values[field]) * weight
        for field, weight in normalized_profile["weights"].items()
    )
    result: dict[str, Any] = {
        "score_schema_version": PACKAGE_ORDINAL_SCORE_SCHEMA_VERSION,
        "policy_id": PACKAGE_ORDINAL_POLICY_ID,
        "status": "CALIBRATION_ONLY_SCORED",
        "profile_id": normalized_profile["profile_id"],
        "profile_hash": normalized_profile["profile_hash"],
        "design_hash": normalized_design_hash,
        "source_feature_hash": features["feature_hash"],
        "binding": features["binding"],
        "ordinal_score": round(score, 12),
        "semantics": {
            "higher_is_more_package_support": True,
            "score_is_probability": False,
            "ready_threshold": None,
            "ready_decision": None,
        },
        "safety": {
            "diagnostic_only": True,
            "holdout_access_permitted": False,
            "runtime_activation_permitted": False,
        },
    }
    result["score_hash"] = semantic_sha256_hash_ref(result)
    return result


def _verified_package_signal(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("package ready signal is invalid")
    signal = dict(value)
    signal_hash = _hash_ref(signal.pop("signal_hash", None), "signal_hash")
    if signal_hash != semantic_sha256_hash_ref(signal):
        raise ValueError("package ready signal integrity is invalid")
    if (
        signal.get("signal_schema_version") != PACKAGE_READY_SIGNAL_SCHEMA_VERSION
        or signal.get("policy_id") != PACKAGE_READY_SIGNAL_POLICY_ID
        or signal.get("status") != "CALIBRATION_ONLY_PROJECTED"
    ):
        raise ValueError("package ready signal identity is invalid")
    signal["signal_hash"] = signal_hash
    return signal


def _verified_feature_vector(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("package ordinal feature vector is invalid")
    vector = dict(value)
    feature_hash = _hash_ref(vector.pop("feature_hash", None), "feature_hash")
    if feature_hash != semantic_sha256_hash_ref(vector):
        raise ValueError("package ordinal feature vector integrity is invalid")
    if (
        vector.get("feature_schema_version")
        != PACKAGE_ORDINAL_FEATURE_SCHEMA_VERSION
        or vector.get("policy_id") != PACKAGE_ORDINAL_POLICY_ID
        or vector.get("status") != "CALIBRATION_ONLY_PROJECTED"
    ):
        raise ValueError("package ordinal feature vector identity is invalid")
    fields = _mapping(vector.get("features"), "package ordinal features")
    if set(fields) != set(PACKAGE_ORDINAL_FEATURE_FIELDS):
        raise ValueError("package ordinal feature fields are invalid")
    for field in PACKAGE_ORDINAL_FEATURE_FIELDS:
        _bounded(fields[field], field)
    vector["feature_hash"] = feature_hash
    return vector


def _profiles(value: object) -> list[dict[str, Any]]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError("package ordinal profiles are invalid")
    profiles = [_profile(item) for item in value]
    if not profiles or len({row["profile_id"] for row in profiles}) != len(profiles):
        raise ValueError("package ordinal profile identities are invalid")
    return profiles


def _profile(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("package ordinal profile is invalid")
    profile_id = value.get("profile_id")
    weights = value.get("weights")
    if not isinstance(profile_id, str) or not profile_id.strip():
        raise ValueError("package ordinal profile id is invalid")
    if not isinstance(weights, Mapping) or set(weights) != set(
        PACKAGE_ORDINAL_FEATURE_FIELDS
    ):
        raise ValueError("package ordinal profile weights are invalid")
    normalized_weights = {
        field: _bounded(weights[field], field)
        for field in PACKAGE_ORDINAL_FEATURE_FIELDS
    }
    if not math.isclose(sum(normalized_weights.values()), 1.0, abs_tol=1e-9):
        raise ValueError("package ordinal profile weights are invalid")
    profile = {
        "profile_id": profile_id.strip(),
        "weights": normalized_weights,
        "evidence_source": value.get("evidence_source"),
    }
    profile["profile_hash"] = semantic_sha256_hash_ref(profile)
    return profile


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} is invalid")
    return value


def _bounded(value: object, field: str, *, upper: float = 1.0) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(float(value))
        or not 0.0 <= float(value) <= upper
    ):
        raise ValueError(f"{field} is invalid")
    return float(value)


def _hash_ref(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("sha256:")
        or len(value) != 71
    ):
        raise ValueError(f"{field} is invalid")
    return value
