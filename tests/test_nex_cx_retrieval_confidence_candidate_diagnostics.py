from __future__ import annotations

from copy import deepcopy

import nex_cx.retrieval_confidence_candidate_diagnostics as candidate_diagnostics
import pytest
from nex_cx.retrieval_confidence_candidate_diagnostics import (
    CORRECTED_PACKAGE_FEATURE_FIELDS,
    build_candidate_diagnostic_observations,
    build_candidate_feature_calibration_samples,
    diagnose_candidate_feature_correction,
)


def _case(scenario: str, *, ready: bool) -> dict[str, object]:
    if ready:
        candidates = (
            ("primary-answer", "PRIMARY_ANSWER", True),
            ("supporting-answer", "SUPPORTING_ANSWER", True),
            ("hard-non-answer", "HARD_NON_ANSWER", False),
            ("easy-non-answer", "EASY_NON_ANSWER", False),
        )
    else:
        candidates = (
            ("hard-non-answer", "HARD_NON_ANSWER", False),
            ("related-non-answer", "RELATED_NON_ANSWER", False),
            ("contradictory-non-answer", "CONTRADICTORY_NON_ANSWER", False),
            ("easy-non-answer", "EASY_NON_ANSWER", False),
        )
    return {
        "scenario_id": scenario,
        "expected_ready": ready,
        "query": "must never be projected",
        "candidates": [
            {
                "candidate_id": candidate_id,
                "evidence_role": role,
                "expected_relevant": relevant,
                "text": "must never be projected",
            }
            for candidate_id, role, relevant in candidates
        ],
    }


def _evidence(
    case: dict[str, object],
    *,
    scores: tuple[float, float, float, float],
    reverse_vector: bool = False,
) -> list[dict[str, object]]:
    candidates = case["candidates"]
    return [
        {
            "candidate_id": candidate["candidate_id"],
            "rank": rank,
            "scores": {
                "rerank_score": scores[rank - 1],
                "rrf_normalized_score": scores[rank - 1],
                "channel_support_score": 1.0,
                "bm25_rank": rank,
                "vector_rank": 5 - rank if reverse_vector else rank,
                "private": "must not be projected",
            },
        }
        for rank, candidate in enumerate(candidates, start=1)  # type: ignore[arg-type]
    ]


def _observations() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index in range(2):
        ready = _case(f"scenario-{index}", ready=True)
        low = _case(f"scenario-{index}", ready=False)
        rows.extend(
            build_candidate_diagnostic_observations(
                ready,
                _evidence(
                    ready,
                    scores=(0.95 - index * 0.02, 0.82, 0.20, 0.05),
                ),
            )
        )
        rows.extend(
            build_candidate_diagnostic_observations(
                low,
                _evidence(
                    low,
                    scores=(0.45, 0.34, 0.22, 0.10),
                    reverse_vector=True,
                ),
            )
        )
    return rows


def _binding() -> dict[str, str]:
    return {
        "embedding_model_revision": "embedding",
        "reranker_model_revision": "hf:" + "a" * 40,
        "ranking_policy_id": "weighted_rrf_vector_bm25_v1",
    }


def test_projects_text_free_integrity_bound_candidate_observations() -> None:
    case = _case("scenario-a", ready=True)
    observations = build_candidate_diagnostic_observations(
        case,
        list(reversed(_evidence(case, scores=(0.9, 0.8, 0.2, 0.1)))),
    )

    assert [row["rank"] for row in observations] == [1, 2, 3, 4]
    assert observations[0]["sample_id"] == "scenario-a:positive"
    assert observations[0]["expected_relevant"] is True
    assert observations[-1]["expected_relevant"] is False
    assert all(
        str(row["observation_hash"]).startswith("sha256:") for row in observations
    )
    assert "must never be projected" not in str(observations)
    assert "private" not in str(observations)


def test_diagnoses_candidate_ranking_and_corrected_package_features_only() -> None:
    result = diagnose_candidate_feature_correction(
        _observations(),
        dataset_id="dataset-v3",
        dataset_sha256="a" * 64,
        expected_binding=_binding(),
    )

    assert result["status"] == "DIAGNOSED"
    assert result["runtime_activation_permitted"] is False
    assert result["feature_selection_permitted"] is False
    assert result["holdout_access_permitted"] is False
    assert result["dataset"]["package_count"] == 4
    assert result["dataset"]["candidate_observation_count"] == 16
    assert result["candidate_ranking"] == {
        "ready_package_count": 2,
        "low_confidence_package_count": 2,
        "ready_top1_relevant_rate": 1.0,
        "ready_top2_relevant_recall": 1.0,
        "ready_mean_reciprocal_relevant_rank": 1.0,
    }
    assert (
        result["candidate_signals"]["reranker_score"]["classification"] == "DIRECTIONAL"
    )
    correction = result["feature_set_correction"]
    assert correction["corrected_candidate_fields"] == list(
        CORRECTED_PACKAGE_FEATURE_FIELDS
    )
    assert "reranker_top2_mean" in correction["directional_corrected_candidates"]
    assert correction["selection_deferred_to"] == "GB2-CA00-S20Q-G"
    assert (
        result["package_features"]["top_channel_support"]["classification"]
        == "CONSTANT"
    )

    samples = build_candidate_feature_calibration_samples(_observations())
    assert len(samples) == 4
    assert samples[0]["sample_schema_version"].endswith(".v1")
    assert samples[0]["features"]["reranker_second_score"] > 0.0
    assert all(str(sample["sample_hash"]).startswith("sha256:") for sample in samples)
    assert "must never be projected" not in str(samples)


@pytest.mark.parametrize(
    "mutation,error,detail",
    [
        (lambda case, evidence: case.update(expected_ready="yes"), TypeError, "case"),
        (lambda case, evidence: case.update(candidates=[]), ValueError, "four"),
        (
            lambda case, evidence: case["candidates"].__setitem__(0, "bad"),
            TypeError,
            "truth",
        ),
        (
            lambda case, evidence: case["candidates"][0].update(
                expected_relevant="yes"
            ),
            ValueError,
            "truth",
        ),
        (lambda case, evidence: evidence.pop(), ValueError, "four"),
        (lambda case, evidence: evidence.__setitem__(0, "bad"), TypeError, "item"),
        (
            lambda case, evidence: evidence[0].update(candidate_id="unknown"),
            ValueError,
            "scope",
        ),
        (
            lambda case, evidence: evidence[0].update(rank=2),
            ValueError,
            "scope",
        ),
        (
            lambda case, evidence: evidence[0].update(scores=[]),
            TypeError,
            "scores",
        ),
        (
            lambda case, evidence: evidence[0]["scores"].update(
                bm25_rank=None, vector_rank=None
            ),
            ValueError,
            "ranks",
        ),
        (
            lambda case, evidence: evidence[0]["scores"].update(
                rerank_score=float("nan")
            ),
            ValueError,
            "rerank_score",
        ),
    ],
)
def test_projection_rejects_malformed_truth_or_numeric_evidence(
    mutation, error: type[Exception], detail: str
) -> None:
    case = _case("scenario-a", ready=True)
    evidence = _evidence(case, scores=(0.9, 0.8, 0.2, 0.1))
    mutation(case, evidence)
    with pytest.raises(error, match=detail):
        build_candidate_diagnostic_observations(case, evidence)


def test_projection_rejects_non_mapping_empty_identity_and_non_contiguous_rank() -> (
    None
):
    with pytest.raises(TypeError, match="case"):
        build_candidate_diagnostic_observations(  # type: ignore[arg-type]
            [], []
        )
    case = _case("scenario-a", ready=True)
    case["scenario_id"] = ""
    with pytest.raises(ValueError, match="scenario_id"):
        build_candidate_diagnostic_observations(
            case,
            _evidence(_case("scenario-a", ready=True), scores=(0.9, 0.8, 0.2, 0.1)),
        )

    case = _case("scenario-a", ready=True)
    evidence = _evidence(case, scores=(0.9, 0.8, 0.2, 0.1))
    evidence[-1]["rank"] = 5
    with pytest.raises(ValueError, match="incomplete"):
        build_candidate_diagnostic_observations(case, evidence)

    evidence = _evidence(case, scores=(0.9, 0.8, 0.2, 0.1))
    evidence[0]["rank"] = True
    with pytest.raises(TypeError, match="rank"):
        build_candidate_diagnostic_observations(case, evidence)

    evidence = _evidence(case, scores=(0.9, 0.8, 0.2, 0.1))
    evidence[0]["scores"]["rerank_score"] = "bad"  # type: ignore[index]
    with pytest.raises(TypeError, match="rerank_score"):
        build_candidate_diagnostic_observations(case, evidence)


def test_diagnostic_rejects_tamper_replay_and_incomplete_pair_semantics() -> None:
    observations = _observations()
    tampered = deepcopy(observations)
    tampered[0]["signals"]["reranker_score"] = 0.01  # type: ignore[index]
    with pytest.raises(ValueError, match="integrity"):
        diagnose_candidate_feature_correction(
            tampered,
            dataset_id="dataset-v3",
            dataset_sha256="a" * 64,
            expected_binding=_binding(),
        )

    replayed = [*observations, deepcopy(observations[0])]
    with pytest.raises(ValueError, match="integrity"):
        diagnose_candidate_feature_correction(
            replayed,
            dataset_id="dataset-v3",
            dataset_sha256="a" * 64,
            expected_binding=_binding(),
        )

    one_label = [
        row for row in observations if row["sample_id"] != "scenario-0:negative"
    ]
    with pytest.raises(ValueError, match="pairs"):
        diagnose_candidate_feature_correction(
            one_label,
            dataset_id="dataset-v3",
            dataset_sha256="a" * 64,
            expected_binding=_binding(),
        )


def test_diagnostic_rejects_schema_value_and_package_semantic_drift() -> None:
    observations = _observations()
    malformed = deepcopy(observations)
    malformed[0]["observation_schema_version"] = "wrong"
    unsigned = dict(malformed[0])
    unsigned.pop("observation_hash")
    from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

    malformed[0]["observation_hash"] = semantic_sha256_hash_ref(unsigned)
    with pytest.raises(ValueError, match="schema"):
        diagnose_candidate_feature_correction(
            malformed,
            dataset_id="dataset-v3",
            dataset_sha256="a" * 64,
            expected_binding=_binding(),
        )

    malformed_value = deepcopy(observations)
    malformed_value[0]["expected_relevant"] = "yes"
    unsigned = dict(malformed_value[0])
    unsigned.pop("observation_hash")
    malformed_value[0]["observation_hash"] = semantic_sha256_hash_ref(unsigned)
    with pytest.raises(TypeError, match="values"):
        diagnose_candidate_feature_correction(
            malformed_value,
            dataset_id="dataset-v3",
            dataset_sha256="a" * 64,
            expected_binding=_binding(),
        )

    malformed_identity = deepcopy(observations)
    for row in malformed_identity:
        if row["sample_id"] == "scenario-0:negative":
            row["sample_id"] = "invalid:not-negative"
            unsigned = dict(row)
            unsigned.pop("observation_hash")
            row["observation_hash"] = semantic_sha256_hash_ref(unsigned)
    with pytest.raises(ValueError, match="identity"):
        diagnose_candidate_feature_correction(
            malformed_identity,
            dataset_id="dataset-v3",
            dataset_sha256="a" * 64,
            expected_binding=_binding(),
        )

    with pytest.raises(TypeError, match="observation"):
        diagnose_candidate_feature_correction(  # type: ignore[list-item]
            ["bad"],
            dataset_id="dataset-v3",
            dataset_sha256="a" * 64,
            expected_binding=_binding(),
        )

    wrong_truth = deepcopy(observations)
    wrong_truth[0]["expected_relevant"] = False
    unsigned = dict(wrong_truth[0])
    unsigned.pop("observation_hash")
    wrong_truth[0]["observation_hash"] = semantic_sha256_hash_ref(unsigned)
    with pytest.raises(ValueError, match="semantics"):
        diagnose_candidate_feature_correction(
            wrong_truth,
            dataset_id="dataset-v3",
            dataset_sha256="a" * 64,
            expected_binding=_binding(),
        )


def test_diagnostic_requires_nonempty_sequence_and_binding() -> None:
    with pytest.raises(TypeError, match="observations"):
        diagnose_candidate_feature_correction(  # type: ignore[arg-type]
            "bad",
            dataset_id="dataset-v3",
            dataset_sha256="a" * 64,
            expected_binding=_binding(),
        )
    with pytest.raises(TypeError, match="binding"):
        diagnose_candidate_feature_correction(
            _observations(),
            dataset_id="dataset-v3",
            dataset_sha256="a" * 64,
            expected_binding={},
        )


def test_low_level_classification_and_missing_rank_quality_guards() -> None:
    assert candidate_diagnostics._classification(0.4, near_constant=False) == "INVERTED"
    assert (
        candidate_diagnostics._classification(0.5, near_constant=False)
        == "NON_DISCRIMINATIVE"
    )
    assert candidate_diagnostics._channel_rank_quality(None, None) == 0.0
    with pytest.raises(ValueError, match="labels"):
        candidate_diagnostics._auc([], [0.1])
