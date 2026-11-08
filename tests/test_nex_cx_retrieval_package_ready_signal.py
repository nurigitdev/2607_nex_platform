from __future__ import annotations

from copy import deepcopy

import pytest
from nex_cx.retrieval_confidence_candidate_diagnostics import (
    EXPANDED_CANDIDATE_RELEVANCE_SAMPLE_SCHEMA_VERSION,
)
from nex_cx.retrieval_package_ready_signal import (
    CANDIDATE_PROBABILITY_MODEL_SCHEMA_VERSION,
    CANDIDATE_PROBABILITY_POLICY_ID,
    PACKAGE_READY_SIGNAL_POLICY_ID,
    build_package_ready_signal,
    fit_candidate_probability_model,
    predict_candidate_relevance_probability,
    score_candidate_relevance_samples,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

PROFILE = {
    "profile_id": "balanced-v1",
    "weights": [
        {"field": "reranker_score", "weight": 0.6},
        {"field": "rrf_normalized_score", "weight": 0.4},
    ],
}
BINDING = {
    "dataset_id": "dataset-v4",
    "embedding_revision": "embedding-revision",
    "reranker_revision": "reranker-revision",
}


def _sample(
    sample_id: str,
    candidate_id: str,
    *,
    expected_ready: bool,
    expected_relevant: bool,
    score: float,
) -> dict:
    value = {
        "sample_schema_version": (
            EXPANDED_CANDIDATE_RELEVANCE_SAMPLE_SCHEMA_VERSION
        ),
        "sample_id": sample_id,
        "candidate_id": candidate_id,
        "expected_ready": expected_ready,
        "expected_relevant": expected_relevant,
        "signals": {
            "reranker_score": score,
            "rrf_normalized_score": score,
            "channel_rank_quality": score,
            "bm25_score_quality": score,
            "vector_similarity_quality": score,
        },
    }
    value["sample_hash"] = semantic_sha256_hash_ref(value)
    return value


def _samples(*, inverted: bool = False) -> list[dict]:
    rows = []
    for scenario in range(2):
        positive_scores = [0.9, 0.8, 0.2, 0.1]
        if inverted:
            positive_scores = [0.1, 0.2, 0.8, 0.9]
        for index, score in enumerate(positive_scores):
            rows.append(
                _sample(
                    f"scenario-{scenario}:positive",
                    f"p-{scenario}-{index}",
                    expected_ready=True,
                    expected_relevant=index < 2,
                    score=score,
                )
            )
        for index, score in enumerate([0.45, 0.35, 0.25, 0.15]):
            rows.append(
                _sample(
                    f"scenario-{scenario}:negative",
                    f"n-{scenario}-{index}",
                    expected_ready=False,
                    expected_relevant=False,
                    score=score,
                )
            )
    return rows


def _model(*, inverted: bool = False) -> tuple[list[dict], dict]:
    scored = score_candidate_relevance_samples(_samples(inverted=inverted), profile=PROFILE)
    model = fit_candidate_probability_model(
        scored,
        source_profile_id="balanced-v1",
        expected_binding=BINDING,
    )
    return scored, model


def _package(scored: list[dict], sample_id: str) -> list[dict]:
    return [
        {
            "candidate_id": row["candidate_id"],
            "candidate_score": row["candidate_score"],
        }
        for row in scored
        if row["sample_id"] == sample_id
    ]


def _rehash_sample(value: dict) -> None:
    value["sample_hash"] = semantic_sha256_hash_ref(
        {key: item for key, item in value.items() if key != "sample_hash"}
    )


def _rehash_score(value: dict) -> None:
    value["score_hash"] = semantic_sha256_hash_ref(
        {key: item for key, item in value.items() if key != "score_hash"}
    )


def _rehash_model(value: dict) -> None:
    value["model_hash"] = semantic_sha256_hash_ref(
        {key: item for key, item in value.items() if key != "model_hash"}
    )


def test_probability_model_and_package_signal_are_deterministic() -> None:
    scored, model = _model()
    repeated = fit_candidate_probability_model(
        scored,
        source_profile_id="balanced-v1",
        expected_binding=BINDING,
    )

    assert model == repeated
    assert model["model_schema_version"] == CANDIDATE_PROBABILITY_MODEL_SCHEMA_VERSION
    assert model["policy_id"] == CANDIDATE_PROBABILITY_POLICY_ID
    assert model["status"] == "CALIBRATION_ONLY_FITTED"
    assert model["parameters"]["coefficient"] > 0.0
    assert model["safety"] == {
        "candidate_truth_runtime_input_permitted": False,
        "holdout_access_permitted": False,
        "runtime_activation_permitted": False,
        "ready_threshold_selected": False,
    }
    assert predict_candidate_relevance_probability(0.9, model=model) > (
        predict_candidate_relevance_probability(0.2, model=model)
    )

    ready = build_package_ready_signal(
        _package(scored, "scenario-0:positive"),
        model=model,
        expected_binding=BINDING,
    )
    low = build_package_ready_signal(
        _package(scored, "scenario-0:negative"),
        model=model,
        expected_binding=BINDING,
    )

    assert ready["policy_id"] == PACKAGE_READY_SIGNAL_POLICY_ID
    assert ready["status"] == "CALIBRATION_ONLY_PROJECTED"
    assert ready["features"]["ready_probability_at_least_two"] > (
        low["features"]["ready_probability_at_least_two"]
    )
    assert ready["semantics"]["package_threshold"] is None
    assert ready["semantics"]["ready_decision"] is None
    assert ready["safety"]["runtime_activation_permitted"] is False
    assert sum(ready["relevant_count_probability"].values()) == pytest.approx(1.0)
    assert len(ready["candidate_probabilities"]) == 4
    assert ready["signal_hash"].startswith("sha256:")


def test_scoring_rejects_sample_and_profile_drift() -> None:
    samples = _samples()
    tampered = deepcopy(samples)
    tampered[0]["signals"]["reranker_score"] = 0.1
    with pytest.raises(ValueError, match="integrity"):
        score_candidate_relevance_samples(tampered, profile=PROFILE)

    duplicate = deepcopy(samples)
    duplicate[1]["candidate_id"] = duplicate[0]["candidate_id"]
    duplicate[1]["sample_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in duplicate[1].items() if key != "sample_hash"}
    )
    with pytest.raises(ValueError, match="duplicated"):
        score_candidate_relevance_samples(duplicate, profile=PROFILE)

    bad_profile = deepcopy(PROFILE)
    bad_profile["weights"][1]["weight"] = 0.3
    with pytest.raises(ValueError, match="weights"):
        score_candidate_relevance_samples(samples, profile=bad_profile)

    missing_signal = deepcopy(PROFILE)
    missing_signal["weights"][0]["field"] = "missing"
    with pytest.raises(ValueError, match="signal is missing"):
        score_candidate_relevance_samples(samples, profile=missing_signal)


def test_training_and_model_guards_fail_closed() -> None:
    scored, model = _model()
    with pytest.raises(ValueError, match="holdout"):
        fit_candidate_probability_model(
            scored,
            source_profile_id="balanced-v1",
            expected_binding=BINDING,
            training_scope="HOLDOUT",
        )
    with pytest.raises(ValueError, match="regularization"):
        fit_candidate_probability_model(
            scored,
            source_profile_id="balanced-v1",
            expected_binding=BINDING,
            regularization=101.0,
        )

    wrong_profile = deepcopy(scored)
    wrong_profile[0]["source_profile_id"] = "other"
    wrong_profile[0]["score_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in wrong_profile[0].items() if key != "score_hash"}
    )
    with pytest.raises(ValueError, match="profile binding"):
        fit_candidate_probability_model(
            wrong_profile,
            source_profile_id="balanced-v1",
            expected_binding=BINDING,
        )

    tampered_model = deepcopy(model)
    tampered_model["parameters"]["intercept"] += 1.0
    with pytest.raises(ValueError, match="integrity"):
        predict_candidate_relevance_probability(0.5, model=tampered_model)
    with pytest.raises(ValueError, match="binding"):
        build_package_ready_signal(
            _package(scored, "scenario-0:positive"),
            model=model,
            expected_binding={"dataset_id": "other"},
        )


def test_non_directional_model_cannot_project_probability() -> None:
    _scored, model = _model(inverted=True)

    assert model["status"] == "REJECTED_NON_DIRECTIONAL_OR_UNCONVERGED"
    assert model["parameters"]["monotonic_non_decreasing"] is False
    with pytest.raises(ValueError, match="not admitted"):
        predict_candidate_relevance_probability(0.5, model=model)


@pytest.mark.parametrize(
    ("candidates", "detail"),
    [
        ([{"candidate_id": "one", "candidate_score": 0.5}], "four items"),
        (
            [
                {"candidate_id": "same", "candidate_score": 0.9},
                {"candidate_id": "same", "candidate_score": 0.8},
                {"candidate_id": "three", "candidate_score": 0.2},
                {"candidate_id": "four", "candidate_score": 0.1},
            ],
            "duplicated",
        ),
    ],
)
def test_package_signal_rejects_invalid_scope(candidates, detail: str) -> None:
    _scored, model = _model()

    with pytest.raises(ValueError, match=detail):
        build_package_ready_signal(
            candidates,
            model=model,
            expected_binding=BINDING,
        )


def test_candidate_sample_validation_matrix() -> None:
    with pytest.raises(TypeError, match="samples"):
        score_candidate_relevance_samples("bad", profile=PROFILE)
    with pytest.raises(TypeError, match="sample is invalid"):
        score_candidate_relevance_samples([None], profile=PROFILE)
    with pytest.raises(ValueError, match="packages are missing"):
        score_candidate_relevance_samples([], profile=PROFILE)

    bad_schema = deepcopy(_samples())
    bad_schema[0]["sample_schema_version"] = "bad"
    _rehash_sample(bad_schema[0])
    with pytest.raises(ValueError, match="schema"):
        score_candidate_relevance_samples(bad_schema, profile=PROFILE)

    bad_values = deepcopy(_samples())
    bad_values[0]["expected_ready"] = "yes"
    _rehash_sample(bad_values[0])
    with pytest.raises(TypeError, match="values"):
        score_candidate_relevance_samples(bad_values, profile=PROFILE)

    empty_signals = deepcopy(_samples())
    empty_signals[0]["signals"] = {}
    _rehash_sample(empty_signals[0])
    with pytest.raises(ValueError, match="signals are missing"):
        score_candidate_relevance_samples(empty_signals, profile=PROFILE)

    incomplete = deepcopy(_samples())[:-1]
    with pytest.raises(ValueError, match="package semantics"):
        score_candidate_relevance_samples(incomplete, profile=PROFILE)


def test_profile_validation_matrix() -> None:
    samples = _samples()
    for profile, error, detail in (
        (None, TypeError, "profile is invalid"),
        ({"profile_id": "p", "weights": "bad"}, TypeError, "weights"),
        ({"profile_id": "p", "weights": [None]}, TypeError, "weight is invalid"),
        ({"profile_id": "p", "weights": []}, ValueError, "weights"),
        (
            {
                "profile_id": "p",
                "weights": [
                    {"field": "reranker_score", "weight": 0.5},
                    {"field": "reranker_score", "weight": 0.5},
                ],
            },
            ValueError,
            "duplicated",
        ),
    ):
        with pytest.raises(error, match=detail):
            score_candidate_relevance_samples(samples, profile=profile)


def test_scored_candidate_validation_matrix() -> None:
    scored, _model_value = _model()
    common = {
        "source_profile_id": "balanced-v1",
        "expected_binding": BINDING,
    }
    with pytest.raises(TypeError, match="scored candidates"):
        fit_candidate_probability_model("bad", **common)
    with pytest.raises(TypeError, match="scored candidate is invalid"):
        fit_candidate_probability_model([None], **common)

    tampered = deepcopy(scored)
    tampered[0]["candidate_score"] = 0.0
    with pytest.raises(ValueError, match="integrity"):
        fit_candidate_probability_model(tampered, **common)

    bad_schema = deepcopy(scored)
    bad_schema[0]["score_schema_version"] = "bad"
    _rehash_score(bad_schema[0])
    with pytest.raises(ValueError, match="schema"):
        fit_candidate_probability_model(bad_schema, **common)

    bad_truth = deepcopy(scored)
    bad_truth[0]["expected_relevant"] = "yes"
    _rehash_score(bad_truth[0])
    with pytest.raises(TypeError, match="truth"):
        fit_candidate_probability_model(bad_truth, **common)

    duplicate = deepcopy(scored)
    duplicate[1]["candidate_id"] = duplicate[0]["candidate_id"]
    _rehash_score(duplicate[1])
    with pytest.raises(ValueError, match="identity is duplicated"):
        fit_candidate_probability_model(duplicate, **common)

    with pytest.raises(ValueError, match="cardinality"):
        fit_candidate_probability_model(scored[:-1], **common)

    bad_package_truth = deepcopy(scored)
    positive = next(row for row in bad_package_truth if row["expected_relevant"])
    positive["expected_relevant"] = False
    _rehash_score(positive)
    with pytest.raises(ValueError, match="package truth"):
        fit_candidate_probability_model(bad_package_truth, **common)

    negative_only = [
        row for row in scored if row["sample_id"].endswith(":negative")
    ]
    with pytest.raises(ValueError, match="labels are incomplete"):
        fit_candidate_probability_model(negative_only, **common)


def test_numeric_binding_and_probability_model_validation_matrix() -> None:
    scored, model = _model()
    for regularization, error in (
        (0.0, ValueError),
        ("bad", TypeError),
        (float("inf"), ValueError),
    ):
        with pytest.raises(error, match="regularization"):
            fit_candidate_probability_model(
                scored,
                source_profile_id="balanced-v1",
                expected_binding=BINDING,
                regularization=regularization,
            )
    with pytest.raises(TypeError, match="binding"):
        fit_candidate_probability_model(
            scored,
            source_profile_id="balanced-v1",
            expected_binding={},
        )
    with pytest.raises(ValueError, match="source_profile_id"):
        fit_candidate_probability_model(
            scored,
            source_profile_id=" ",
            expected_binding=BINDING,
        )
    with pytest.raises(ValueError, match="candidate_score"):
        predict_candidate_relevance_probability(-0.1, model=model)
    with pytest.raises(TypeError, match="model is invalid"):
        predict_candidate_relevance_probability(0.5, model=None)

    bad_schema = deepcopy(model)
    bad_schema["model_schema_version"] = "bad"
    _rehash_model(bad_schema)
    with pytest.raises(ValueError, match="not admitted"):
        predict_candidate_relevance_probability(0.5, model=bad_schema)

    bad_parameters = deepcopy(model)
    bad_parameters["parameters"] = "bad"
    _rehash_model(bad_parameters)
    with pytest.raises(TypeError, match="parameters"):
        predict_candidate_relevance_probability(0.5, model=bad_parameters)

    bad_candidate = _package(scored, "scenario-0:positive")
    bad_candidate[0] = None
    with pytest.raises(TypeError, match="package candidate is invalid"):
        build_package_ready_signal(
            bad_candidate,
            model=model,
            expected_binding=BINDING,
        )
