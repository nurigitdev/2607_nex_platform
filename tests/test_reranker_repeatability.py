from __future__ import annotations

import math

import pytest

import reranker_repeatability as repeatability


PAIR_META = {
    "case:strong-positive": True,
    "case:acceptable-positive": True,
    "case:hard-negative": False,
    "case:easy-negative": False,
}


def _observations(
    score_sets: list[list[float]],
) -> list[dict]:
    pair_ids = list(PAIR_META)
    observations = []
    for repeat_index, scores in enumerate(score_sets, start=1):
        order = sorted(range(4), key=lambda index: (-scores[index], index))
        ranks = {index: rank for rank, index in enumerate(order, start=1)}
        for index, pair_id in enumerate(pair_ids):
            observations.append(
                {
                    "case_id": "case",
                    "pair_id": pair_id,
                    "expected_ready": PAIR_META[pair_id],
                    "repeat_index": repeat_index,
                    "score": scores[index],
                    "rank": ranks[index],
                }
            )
    return observations


def test_candidate_tolerance_is_guarded_quantized_and_bounded() -> None:
    assert repeatability.candidate_score_tolerance(0.0) == 0.0005
    assert repeatability.candidate_score_tolerance(0.002392) == 0.003
    assert repeatability.candidate_score_tolerance(0.0041) == 0.0055

    for invalid in (math.inf, math.nan, -0.1):
        with pytest.raises(ValueError, match="invalid"):
            repeatability.candidate_score_tolerance(invalid)
    with pytest.raises(ValueError, match="invalid"):
        repeatability.candidate_score_tolerance(0.1, quantum=0.0)
    with pytest.raises(ValueError, match="invalid"):
        repeatability.candidate_score_tolerance(0.1, guard_factor=0.9)
    with pytest.raises(ValueError, match="invalid"):
        repeatability.candidate_score_tolerance(0.1, hard_cap=0.0)


def test_analysis_separates_same_label_near_and_cross_label_exchanges() -> None:
    same_label = _observations(
        [
            [0.901, 0.900, 0.500, 0.100],
            [0.900, 0.901, 0.500, 0.100],
        ]
    )
    same_result = repeatability.analyze_reranker_repeatability(
        same_label,
        expected_pair_ids=set(PAIR_META),
        repeat_count=2,
        score_tolerance=0.002,
    )
    assert same_result["cross_label_rank_exchange_count"] == 0
    assert same_result["same_label_near_tie_exchange_count"] == 1
    assert same_result["same_label_non_near_exchange_count"] == 0
    assert same_result["max_pair_score_range"] == pytest.approx(0.001)

    cross_label = _observations(
        [
            [0.901, 0.700, 0.900, 0.100],
            [0.900, 0.700, 0.901, 0.100],
        ]
    )
    cross_result = repeatability.analyze_reranker_repeatability(
        cross_label,
        expected_pair_ids=set(PAIR_META),
        repeat_count=2,
        score_tolerance=0.002,
    )
    assert cross_result["cross_label_rank_exchange_count"] == 1


def test_analysis_detects_non_near_exchange_and_incomplete_coverage() -> None:
    non_near = _observations(
        [
            [0.95, 0.70, 0.50, 0.10],
            [0.69, 0.96, 0.50, 0.10],
        ]
    )
    result = repeatability.analyze_reranker_repeatability(
        non_near,
        expected_pair_ids=set(PAIR_META),
        repeat_count=2,
        score_tolerance=0.01,
    )
    assert result["same_label_non_near_exchange_count"] == 1

    incomplete = repeatability.analyze_reranker_repeatability(
        non_near[:1],
        expected_pair_ids=set(PAIR_META),
        repeat_count=2,
        score_tolerance=0.01,
    )
    assert incomplete["pair_coverage_complete"] is False
    assert math.isinf(incomplete["max_pair_score_range"])
    assert math.isinf(incomplete["p95_pair_score_range"])


@pytest.mark.parametrize(
    "response, detail",
    [
        ({"results": None}, "list"),
        ({"results": ["bad"]}, "object"),
        ({"results": [{"index": "0", "score": 0.5}]}, "invalid"),
        ({"results": [{"index": 0, "score": True}]}, "invalid"),
        (
            {
                "results": [
                    {"index": 0, "score": 0.5},
                    {"index": 0, "score": 0.4},
                ]
            },
            "duplicate",
        ),
        ({"results": [{"index": 0, "score": 0.5}]}, "every document"),
    ],
)
def test_scored_results_rejects_malformed_response(response, detail: str) -> None:
    count = 2 if detail in {"duplicate", "every document"} else 1
    with pytest.raises(ValueError, match=detail):
        repeatability.scored_reranker_results(response, count)


def test_collection_validates_shape_and_collects(monkeypatch) -> None:
    with pytest.raises(ValueError, match="at least two"):
        repeatability.collect_reranker_repeat_observations(
            {}, repeat_count=1, environ={}, requester=None
        )
    with pytest.raises(ValueError, match="cases"):
        repeatability.collect_reranker_repeat_observations(
            {}, repeat_count=2, environ={}, requester=None
        )
    with pytest.raises(ValueError, match="documents"):
        repeatability.collect_reranker_repeat_observations(
            {"cases": [{"case_id": "case", "query": "q", "partition": "P", "documents": []}]},
            repeat_count=2,
            environ={},
            requester=None,
        )

    monkeypatch.setattr(
        repeatability,
        "execute_remote_rerank_request",
        lambda _payload, **_kwargs: {
            "model_revision": "model",
            "deployment_id": "deployment",
            "results": [{"index": 0, "score": 0.5}],
        },
    )
    dataset = {
        "cases": [
            {
                "case_id": "case",
                "query": "query",
                "partition": "CALIBRATION",
                "documents": [
                    {
                        "document_id": "document",
                        "relevance_grade": "STRONG_POSITIVE",
                        "expected_ready": True,
                        "text": "text",
                    }
                ],
            }
        ]
    }
    observations = repeatability.collect_reranker_repeat_observations(
        dataset, repeat_count=2, environ={}, requester=None
    )
    assert len(observations) == 2
    assert {item["repeat_index"] for item in observations} == {1, 2}

    dataset["cases"][0]["documents"][0]["expected_ready"] = "yes"
    with pytest.raises(ValueError, match="boolean"):
        repeatability.collect_reranker_repeat_observations(
            dataset, repeat_count=2, environ={}, requester=None
        )
