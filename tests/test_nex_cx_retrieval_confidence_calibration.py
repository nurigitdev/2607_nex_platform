from __future__ import annotations

from copy import deepcopy

import pytest

from nex_cx.retrieval_confidence_calibration import (
    RETRIEVAL_CONFIDENCE_FEATURE_SCHEMA_VERSION,
    RETRIEVAL_CONFIDENCE_POLICY_ID,
    RetrievalConfidenceCalibrationError,
    RetrievalConfidenceWeights,
    build_retrieval_confidence_profile,
    decide_retrieval_confidence,
    project_retrieval_confidence_features,
    select_retrieval_confidence_profile,
)
from nex_runtime import evaluate_binary_score_calibration


def _evidence(
    *,
    first_rerank: float = 0.9,
    second_rerank: float = 0.6,
    rrf: float = 0.95,
    channel: float = 1.0,
) -> list[dict[str, object]]:
    return [
        {
            "rank": 1,
            "scores": {
                "rerank_score": first_rerank,
                "rrf_normalized_score": rrf,
                "channel_support_score": channel,
            },
        },
        {
            "rank": 2,
            "scores": {
                "rerank_score": second_rerank,
                "rrf_normalized_score": 0.7,
                "channel_support_score": 0.7,
            },
        },
    ]


def _evaluation() -> dict[str, object]:
    samples = [
        {
            "sample_id": f"ready-{index}",
            "expected_ready": True,
            "score": round(0.78 + index * 0.01, 3),
        }
        for index in range(10)
    ] + [
        {
            "sample_id": f"low-{index}",
            "expected_ready": False,
            "score": round(0.48 + index * 0.01, 3),
        }
        for index in range(10)
    ]
    return evaluate_binary_score_calibration(
        samples,
        dataset_id="cx-multisignal-test-v1",
    )


def _profile(**overrides: object) -> dict[str, object]:
    values = {
        "profile_id": "qwen-embedding-reranker-weighted-rrf-v1",
        "version": "0001",
        "status": "ACTIVE",
        "embedding_model_revision": "Qwen3-Embedding-4B",
        "reranker_model_revision": "Qwen3-Reranker-4B",
        "ranking_policy_id": "weighted_rrf_vector_bm25_v1",
        "weights": RetrievalConfidenceWeights(),
        "evaluation": _evaluation(),
    }
    values.update(overrides)
    return build_retrieval_confidence_profile(**values)  # type: ignore[arg-type]


def test_feature_projection_combines_rerank_margin_rrf_and_channel_support() -> None:
    features = project_retrieval_confidence_features(_evidence())

    assert features == {
        "feature_schema_version": RETRIEVAL_CONFIDENCE_FEATURE_SCHEMA_VERSION,
        "candidate_count": 2,
        "reranker_score": 0.9,
        "reranker_margin": 0.3,
        "rrf_normalized_score": 0.95,
        "channel_support": 1.0,
        "composite_score": 0.89,
    }
    assert project_retrieval_confidence_features([])["composite_score"] == 0.0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"reranker_score": True},
        {"reranker_margin": -0.1},
        {"rrf_normalized_score": float("nan")},
        {"channel_support": 1.1},
        {"reranker_score": 0.1},
    ],
)
def test_weights_require_finite_bounded_sum_of_one(kwargs: dict[str, object]) -> None:
    with pytest.raises(RetrievalConfidenceCalibrationError, match="weights"):
        RetrievalConfidenceWeights(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("evidence", "message"),
    [
        ("bad", "evidence_items"),
        (["bad"], "evidence_item"),
        ([{"rank": True, "scores": {}}], "evidence_item"),
        ([{"rank": 0, "scores": {}}], "evidence_item"),
        (
            [
                {
                    "rank": 1,
                    "scores": {
                        "rrf_normalized_score": 0.5,
                        "channel_support_score": 0.5,
                    },
                },
                {
                    "rank": 1,
                    "scores": {
                        "rrf_normalized_score": 0.5,
                        "channel_support_score": 0.5,
                    },
                },
            ],
            "evidence_item",
        ),
        ([{"rank": 1, "scores": "bad"}], "evidence_item"),
        (
            [
                {
                    "rank": 1,
                    "scores": {
                        "rerank_score": 2.0,
                        "rrf_normalized_score": 0.5,
                        "channel_support_score": 0.5,
                    },
                }
            ],
            "reranker_score",
        ),
        (
            [
                {
                    "rank": 1,
                    "scores": {
                        "rerank_score": None,
                        "rrf_normalized_score": "bad",
                        "channel_support_score": 0.5,
                    },
                }
            ],
            "rrf_normalized_score",
        ),
    ],
)
def test_feature_projection_rejects_invalid_evidence(
    evidence: object,
    message: str,
) -> None:
    with pytest.raises(RetrievalConfidenceCalibrationError, match=message):
        project_retrieval_confidence_features(evidence)  # type: ignore[arg-type]


def test_profile_is_hash_bound_and_selected_by_both_models_and_policy() -> None:
    profile = _profile()

    assert profile["status"] == "ACTIVE"
    assert profile["threshold"] == 0.675
    assert len(str(profile["profile_hash"])) == 64
    assert select_retrieval_confidence_profile(
        [profile],
        embedding_model_revision="Qwen3-Embedding-4B",
        reranker_model_revision="Qwen3-Reranker-4B",
        ranking_policy_id="weighted_rrf_vector_bm25_v1",
    ) == profile
    assert select_retrieval_confidence_profile(
        [profile],
        embedding_model_revision="other-embedding",
        reranker_model_revision="Qwen3-Reranker-4B",
        ranking_policy_id="weighted_rrf_vector_bm25_v1",
    ) is None
    assert select_retrieval_confidence_profile(
        [profile],
        embedding_model_revision=None,
        reranker_model_revision="Qwen3-Reranker-4B",
        ranking_policy_id="weighted_rrf_vector_bm25_v1",
    ) is None
    assert select_retrieval_confidence_profile(
        [_profile(status="CANDIDATE")],
        embedding_model_revision="Qwen3-Embedding-4B",
        reranker_model_revision="Qwen3-Reranker-4B",
        ranking_policy_id="weighted_rrf_vector_bm25_v1",
    ) is None


def test_decision_requires_exact_active_profile_and_uses_composite_threshold() -> None:
    missing = decide_retrieval_confidence(
        _evidence(),
        profiles=(),
        embedding_model_revision="Qwen3-Embedding-4B",
        reranker_model_revision="Qwen3-Reranker-4B",
        ranking_policy_id="weighted_rrf_vector_bm25_v1",
    )
    assert missing["status"] == "LOW_CONFIDENCE"
    assert missing["reason"] == "active_calibration_profile_missing"
    assert missing["low_confidence_threshold"] is None

    ready = decide_retrieval_confidence(
        _evidence(),
        profiles=(_profile(),),
        embedding_model_revision="Qwen3-Embedding-4B",
        reranker_model_revision="Qwen3-Reranker-4B",
        ranking_policy_id="weighted_rrf_vector_bm25_v1",
    )
    low = decide_retrieval_confidence(
        _evidence(first_rerank=0.4, second_rerank=0.39, rrf=0.5, channel=0.3),
        profiles=(_profile(),),
        embedding_model_revision="Qwen3-Embedding-4B",
        reranker_model_revision="Qwen3-Reranker-4B",
        ranking_policy_id="weighted_rrf_vector_bm25_v1",
    )
    no_answer = decide_retrieval_confidence(
        [],
        profiles=(),
        embedding_model_revision=None,
        reranker_model_revision=None,
        ranking_policy_id="weighted_rrf_vector_bm25_v1",
    )

    assert ready["status"] == "READY"
    assert ready["policy_id"] == RETRIEVAL_CONFIDENCE_POLICY_ID
    assert ready["calibration_profile_hash"] == _profile()["profile_hash"]
    assert low["status"] == "LOW_CONFIDENCE"
    assert low["reason"] == "composite_score_below_calibrated_threshold"
    assert no_answer["status"] == "NO_ANSWER"
    assert no_answer["reason"] == "no_permission_admitted_candidates"


def test_profile_validation_rejects_bad_evaluation_binding_and_integrity() -> None:
    failed = _evaluation()
    failed["status"] = "NO_ACCEPTABLE_THRESHOLD"
    with pytest.raises(RetrievalConfidenceCalibrationError, match="passed"):
        _profile(evaluation=failed)
    with pytest.raises(RetrievalConfidenceCalibrationError, match="status"):
        _profile(status="bad")
    with pytest.raises(RetrievalConfidenceCalibrationError, match="model"):
        _profile(embedding_model_revision=" ")

    first = _profile()
    second = _profile(profile_id="duplicate", version="0002")
    with pytest.raises(RetrievalConfidenceCalibrationError, match="Exactly one"):
        select_retrieval_confidence_profile(
            [first, second],
            embedding_model_revision="Qwen3-Embedding-4B",
            reranker_model_revision="Qwen3-Reranker-4B",
            ranking_policy_id="weighted_rrf_vector_bm25_v1",
        )

    tampered = deepcopy(first)
    tampered["threshold"] = 0.7
    with pytest.raises(RetrievalConfidenceCalibrationError, match="threshold"):
        select_retrieval_confidence_profile(
            [tampered],
            embedding_model_revision="Qwen3-Embedding-4B",
            reranker_model_revision="Qwen3-Reranker-4B",
            ranking_policy_id="weighted_rrf_vector_bm25_v1",
        )

    tampered = deepcopy(first)
    tampered["profile_hash"] = "0" * 64
    with pytest.raises(RetrievalConfidenceCalibrationError, match="integrity"):
        select_retrieval_confidence_profile(
            [tampered],
            embedding_model_revision="Qwen3-Embedding-4B",
            reranker_model_revision="Qwen3-Reranker-4B",
            ranking_policy_id="weighted_rrf_vector_bm25_v1",
        )
