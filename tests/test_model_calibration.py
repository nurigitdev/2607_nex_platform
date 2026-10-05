from __future__ import annotations

from copy import deepcopy

import pytest

from nex_runtime.model_calibration import (
    BinaryCalibrationConstraints,
    ModelCalibrationError,
    build_model_calibration_profile,
    classify_calibrated_score,
    evaluate_binary_score_calibration,
    select_model_calibration_profile,
)


def _samples() -> list[dict[str, object]]:
    return [
        {
            "sample_id": f"positive-{index:02d}",
            "expected_ready": True,
            "score": round(0.70 + index * 0.02, 3),
        }
        for index in range(10)
    ] + [
        {
            "sample_id": f"negative-{index:02d}",
            "expected_ready": False,
            "score": round(0.10 + index * 0.03, 3),
        }
        for index in range(10)
    ]


def _evaluation() -> dict[str, object]:
    return evaluate_binary_score_calibration(
        _samples(),
        dataset_id="s136-public-calibration-v1",
    )


def _profile(**overrides: object) -> dict[str, object]:
    values = {
        "profile_id": "reranker-model-a-weighted-rrf-v1",
        "version": "0001",
        "status": "ACTIVE",
        "capability": "reranking",
        "model_revision": "model-a",
        "request_shape": "rerank",
        "score_semantics": "provider_native_relevance_0_1",
        "policy_id": "weighted_rrf_vector_bm25_v1",
        "evaluation": _evaluation(),
    }
    values.update(overrides)
    return build_model_calibration_profile(**values)  # type: ignore[arg-type]


def test_evaluation_selects_threshold_under_false_ready_and_recall_constraints() -> None:
    evaluation = _evaluation()

    assert evaluation["status"] == "PASSED"
    assert evaluation["sample_count"] == 20
    assert evaluation["positive_count"] == 10
    assert evaluation["negative_count"] == 10
    assert evaluation["selected_threshold"] == 0.535
    assert evaluation["selected_metrics"] == {
        "threshold": 0.535,
        "true_ready": 10,
        "false_low_confidence": 0,
        "false_ready": 0,
        "true_low_confidence": 10,
        "ready_precision": 1.0,
        "ready_recall": 1.0,
        "false_ready_rate": 0.0,
        "false_low_rate": 0.0,
        "balanced_accuracy": 1.0,
    }
    assert len(evaluation["dataset_sha256"]) == 64


def test_evaluation_is_order_independent_and_reports_insufficient_samples() -> None:
    forward = _evaluation()
    reverse = evaluate_binary_score_calibration(
        list(reversed(_samples())),
        dataset_id="s136-public-calibration-v1",
    )
    assert reverse == forward

    insufficient = evaluate_binary_score_calibration(
        _samples()[:9],
        dataset_id="small",
    )
    assert insufficient["status"] == "INSUFFICIENT_SAMPLES"
    assert insufficient["selected_threshold"] is None
    assert insufficient["candidate_count"] == 0


def test_evaluation_rejects_distribution_without_acceptable_threshold() -> None:
    samples = [
        {
            "sample_id": f"positive-{index}",
            "expected_ready": True,
            "score": 0.1,
        }
        for index in range(10)
    ] + [
        {
            "sample_id": f"negative-{index}",
            "expected_ready": False,
            "score": 0.9,
        }
        for index in range(10)
    ]

    evaluation = evaluate_binary_score_calibration(samples, dataset_id="inverted")

    assert evaluation["status"] == "NO_ACCEPTABLE_THRESHOLD"
    assert evaluation["selected_threshold"] is None
    assert evaluation["candidate_count"] > 0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"minimum_sample_count": 0},
        {"minimum_positive_count": 0},
        {"minimum_negative_count": 0},
        {"maximum_false_ready_rate": -0.1},
        {"maximum_false_ready_rate": 1.1},
        {"minimum_ready_recall": -0.1},
        {"minimum_ready_recall": 1.1},
    ],
)
def test_constraints_reject_invalid_values(kwargs: dict[str, object]) -> None:
    with pytest.raises(ModelCalibrationError, match="constraints"):
        BinaryCalibrationConstraints(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda samples: samples[0].update(sample_id=" "), "sample_id"),
        (lambda samples: samples[0].update(expected_ready="yes"), "expected_ready"),
        (lambda samples: samples[0].update(score=True), "score"),
        (lambda samples: samples[0].update(score=-0.1), "score"),
        (lambda samples: samples[1].update(sample_id=samples[0]["sample_id"]), "unique"),
    ],
)
def test_evaluation_rejects_invalid_samples(mutator, message: str) -> None:
    samples = _samples()
    mutator(samples)
    with pytest.raises(ModelCalibrationError, match=message):
        evaluate_binary_score_calibration(samples, dataset_id="dataset")


def test_profile_is_hash_bound_and_selected_only_by_exact_active_binding() -> None:
    profile = _profile()

    assert profile["threshold"] == 0.535
    assert len(profile["profile_hash"]) == 64
    selected = select_model_calibration_profile(
        [profile],
        capability="reranking",
        model_revision="model-a",
        request_shape="rerank",
        score_semantics="provider_native_relevance_0_1",
        policy_id="weighted_rrf_vector_bm25_v1",
    )
    assert selected == profile
    assert selected is not profile

    assert select_model_calibration_profile(
        [profile],
        capability="reranking",
        model_revision="model-b",
        request_shape="rerank",
        score_semantics="provider_native_relevance_0_1",
        policy_id="weighted_rrf_vector_bm25_v1",
    ) is None
    candidate = _profile(status="CANDIDATE")
    assert select_model_calibration_profile(
        [candidate],
        capability="reranking",
        model_revision="model-a",
        request_shape="rerank",
        score_semantics="provider_native_relevance_0_1",
        policy_id="weighted_rrf_vector_bm25_v1",
    ) is None


def test_profile_selection_rejects_ambiguous_active_binding() -> None:
    first = _profile()
    second = _profile(profile_id="duplicate", version="0002")

    with pytest.raises(ModelCalibrationError, match="Exactly one"):
        select_model_calibration_profile(
            [first, second],
            capability="reranking",
            model_revision="model-a",
            request_shape="rerank",
            score_semantics="provider_native_relevance_0_1",
            policy_id="weighted_rrf_vector_bm25_v1",
        )


def test_profile_selection_and_classification_reject_tampering() -> None:
    profile = _profile()
    profile["threshold"] = 0.7

    with pytest.raises(ModelCalibrationError, match="does not match"):
        select_model_calibration_profile(
            [profile],
            capability="reranking",
            model_revision="model-a",
            request_shape="rerank",
            score_semantics="provider_native_relevance_0_1",
            policy_id="weighted_rrf_vector_bm25_v1",
        )

    profile = _profile()
    profile["profile_hash"] = "0" * 64
    with pytest.raises(ModelCalibrationError, match="integrity"):
        classify_calibrated_score(0.9, profile=profile)

    malformed = _profile()
    malformed["profile_schema_version"] = "bad"
    with pytest.raises(ModelCalibrationError, match="profile_schema_version"):
        classify_calibrated_score(0.9, profile=malformed)

    malformed = _profile()
    malformed["evaluation"]["status"] = "REJECTED"  # type: ignore[index]
    with pytest.raises(ModelCalibrationError, match="evaluation.status"):
        classify_calibrated_score(0.9, profile=malformed)


def test_classification_does_not_activate_candidate_or_retired_profiles() -> None:
    for status in ("CANDIDATE", "RETIRED"):
        result = classify_calibrated_score(0.9, profile=_profile(status=status))
        assert result["status"] == "CALIBRATION_REQUIRED"
        assert result["threshold"] is None


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"status": "bad"}, "status"),
        ({"capability": "search"}, "capability"),
        ({"model_revision": " "}, "model_revision"),
        ({"request_shape": " "}, "request_shape"),
        ({"score_semantics": " "}, "score_semantics"),
        ({"policy_id": " "}, "policy_id"),
    ],
)
def test_profile_rejects_invalid_binding(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(ModelCalibrationError, match=message):
        _profile(**overrides)


def test_profile_requires_passed_well_formed_evaluation() -> None:
    malformed = _evaluation()
    malformed["evaluation_schema_version"] = "bad"
    with pytest.raises(ModelCalibrationError, match="evaluation_schema_version"):
        _profile(evaluation=malformed)

    rejected = _evaluation()
    rejected["status"] = "NO_ACCEPTABLE_THRESHOLD"
    with pytest.raises(ModelCalibrationError, match="passed evaluation"):
        _profile(evaluation=rejected)

    missing_threshold = _evaluation()
    missing_threshold["selected_threshold"] = None
    with pytest.raises(ModelCalibrationError, match="selected_threshold"):
        _profile(evaluation=missing_threshold)


def test_classification_fails_closed_without_profile_and_uses_selected_threshold() -> None:
    missing = classify_calibrated_score(0.9, profile=None)
    assert missing == {
        "status": "CALIBRATION_REQUIRED",
        "reason": "active_model_calibration_profile_missing",
        "score": 0.9,
        "threshold": None,
        "profile_id": None,
        "profile_hash": None,
    }

    profile = _profile()
    ready = classify_calibrated_score(0.535, profile=profile)
    low = classify_calibrated_score(0.534, profile=profile)
    assert ready["status"] == "READY"
    assert ready["reason"] is None
    assert low["status"] == "LOW_CONFIDENCE"
    assert low["reason"] == "score_below_calibrated_threshold"
    assert low["profile_id"] == profile["profile_id"]

    bad_profile = deepcopy(profile)
    bad_profile["threshold"] = 2.0
    with pytest.raises(ModelCalibrationError, match="threshold"):
        classify_calibrated_score(0.5, profile=bad_profile)
    with pytest.raises(ModelCalibrationError, match="score"):
        classify_calibrated_score("bad", profile=profile)
