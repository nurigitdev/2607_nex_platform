from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from nex_cx.retrieval_package_ready_calibrator import (
    build_package_ordinal_features,
    score_package_ordinal_features,
    validate_package_ordinal_calibrator_design,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = (
    ROOT
    / "scripts"
    / "smoke"
    / "data"
    / "s136_package_ordinal_calibrator_v1_design.json"
)


def _design() -> dict:
    return json.loads(DESIGN_PATH.read_text(encoding="utf-8"))


def _signal() -> dict:
    signal = {
        "signal_schema_version": "cx_retrieval_package_ready_signal.v1",
        "policy_id": "cx_probability_at_least_two_relevant_v1",
        "status": "CALIBRATION_ONLY_PROJECTED",
        "source_profile_id": "profile-v1",
        "candidate_probability_model_hash": "sha256:" + "a" * 64,
        "binding": {"dataset_id": "dataset-v4"},
        "candidate_probabilities": [
            {"candidate_id": str(index), "relevance_probability": probability}
            for index, probability in enumerate((0.9, 0.7, 0.2, 0.1))
        ],
        "relevant_count_probability": {},
        "features": {
            "ready_probability_at_least_two": 0.7,
            "expected_relevant_count": 1.9,
            "second_candidate_probability": 0.7,
            "top_two_probability_mean": 0.8,
            "second_third_probability_gap": 0.5,
            "candidate_probability_spread": 0.8,
            "probability_at_least_half_count": 2,
            "historical_second_highest_candidate_score": 0.7,
        },
        "semantics": {},
        "safety": {},
    }
    signal["signal_hash"] = semantic_sha256_hash_ref(signal)
    return signal


def _rehash(value: dict, hash_field: str) -> None:
    value[hash_field] = semantic_sha256_hash_ref(
        {key: item for key, item in value.items() if key != hash_field}
    )


def test_design_features_and_scores_are_deterministic_and_fail_closed() -> None:
    design = validate_package_ordinal_calibrator_design(_design())
    features = build_package_ordinal_features(_signal())
    repeated = build_package_ordinal_features(_signal())
    scores = [
        score_package_ordinal_features(
            features,
            profile=profile,
            design_hash=design["design_hash"],
        )
        for profile in design["profile_shortlist"]
    ]

    assert features == repeated
    assert features["features"] == {
        "expected_relevant_fraction": 0.475,
        "second_candidate_probability": 0.7,
        "top_two_probability_mean": 0.8,
        "probability_at_least_half_fraction": 0.5,
    }
    assert all(0.0 <= row["ordinal_score"] <= 1.0 for row in scores)
    assert all(row["semantics"]["score_is_probability"] is False for row in scores)
    assert all(row["safety"]["runtime_activation_permitted"] is False for row in scores)
    assert design["design_hash"].startswith("sha256:")


def test_design_validation_guard_matrix() -> None:
    with pytest.raises(TypeError, match="design is invalid"):
        validate_package_ordinal_calibrator_design(None)

    for field, value, detail in (
        ("status", "ACTIVE", "identity"),
        ("feature_fields", [], "feature fields"),
        ("profile_shortlist", "bad", "profiles"),
        ("safety", {}, "safety"),
    ):
        design = _design()
        design[field] = value
        with pytest.raises((TypeError, ValueError), match=detail):
            validate_package_ordinal_calibrator_design(design)

    duplicate = _design()
    duplicate["profile_shortlist"].append(
        deepcopy(duplicate["profile_shortlist"][0])
    )
    with pytest.raises(ValueError, match="identities"):
        validate_package_ordinal_calibrator_design(duplicate)


def test_signal_projection_guard_matrix() -> None:
    with pytest.raises(TypeError, match="signal is invalid"):
        build_package_ordinal_features(None)

    tampered = _signal()
    tampered["features"]["expected_relevant_count"] = 3.0
    with pytest.raises(ValueError, match="integrity"):
        build_package_ordinal_features(tampered)

    bad_identity = _signal()
    bad_identity["status"] = "ACTIVE"
    _rehash(bad_identity, "signal_hash")
    with pytest.raises(ValueError, match="identity"):
        build_package_ordinal_features(bad_identity)

    bad_candidates = _signal()
    bad_candidates["candidate_probabilities"] = []
    _rehash(bad_candidates, "signal_hash")
    with pytest.raises(ValueError, match="candidate probabilities"):
        build_package_ordinal_features(bad_candidates)

    bad_feature = _signal()
    bad_feature["features"]["expected_relevant_count"] = 5
    _rehash(bad_feature, "signal_hash")
    with pytest.raises(ValueError, match="expected_relevant_count"):
        build_package_ordinal_features(bad_feature)


def test_feature_and_profile_scoring_guard_matrix() -> None:
    design = validate_package_ordinal_calibrator_design(_design())
    features = build_package_ordinal_features(_signal())
    profile = design["profile_shortlist"][0]

    with pytest.raises(TypeError, match="feature vector"):
        score_package_ordinal_features(
            None, profile=profile, design_hash=design["design_hash"]
        )
    tampered = deepcopy(features)
    tampered["features"]["expected_relevant_fraction"] = 0.1
    with pytest.raises(ValueError, match="integrity"):
        score_package_ordinal_features(
            tampered, profile=profile, design_hash=design["design_hash"]
        )
    bad_fields = deepcopy(features)
    bad_fields["features"].pop("top_two_probability_mean")
    _rehash(bad_fields, "feature_hash")
    with pytest.raises(ValueError, match="feature fields"):
        score_package_ordinal_features(
            bad_fields, profile=profile, design_hash=design["design_hash"]
        )
    bad_identity = deepcopy(features)
    bad_identity["status"] = "ACTIVE"
    _rehash(bad_identity, "feature_hash")
    with pytest.raises(ValueError, match="feature vector identity"):
        score_package_ordinal_features(
            bad_identity, profile=profile, design_hash=design["design_hash"]
        )
    bad_feature_mapping = deepcopy(features)
    bad_feature_mapping["features"] = "bad"
    _rehash(bad_feature_mapping, "feature_hash")
    with pytest.raises(TypeError, match="ordinal features"):
        score_package_ordinal_features(
            bad_feature_mapping,
            profile=profile,
            design_hash=design["design_hash"],
        )
    with pytest.raises(TypeError, match="profile is invalid"):
        score_package_ordinal_features(
            features, profile=None, design_hash=design["design_hash"]
        )
    bad_profile = deepcopy(profile)
    bad_profile["weights"]["expected_relevant_fraction"] = 0.5
    with pytest.raises(ValueError, match="weights"):
        score_package_ordinal_features(
            features, profile=bad_profile, design_hash=design["design_hash"]
        )
    missing_profile_id = deepcopy(profile)
    missing_profile_id["profile_id"] = " "
    with pytest.raises(ValueError, match="profile id"):
        score_package_ordinal_features(
            features,
            profile=missing_profile_id,
            design_hash=design["design_hash"],
        )
    missing_weights = deepcopy(profile)
    missing_weights["weights"] = {}
    with pytest.raises(ValueError, match="profile weights"):
        score_package_ordinal_features(
            features,
            profile=missing_weights,
            design_hash=design["design_hash"],
        )
    with pytest.raises(ValueError, match="design_hash"):
        score_package_ordinal_features(
            features, profile=profile, design_hash="mutable"
        )
