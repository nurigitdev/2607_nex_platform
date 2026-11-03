from __future__ import annotations

from copy import deepcopy

import nex_cx.retrieval_pipeline_repeatability as repeatability
import pytest
from nex_cx.retrieval_confidence_candidate_diagnostics import (
    build_candidate_diagnostic_observations,
)
from nex_cx.retrieval_pipeline_repeatability import (
    analyze_retrieval_pipeline_repeatability,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref


def _observations(scenario: str, *, ready: bool) -> list[dict[str, object]]:
    candidates = [
        {
            "candidate_id": f"candidate-{index}",
            "evidence_role": "ANSWER" if ready and index < 2 else "NON_ANSWER",
            "expected_relevant": ready and index < 2,
        }
        for index in range(4)
    ]
    case = {
        "scenario_id": scenario,
        "expected_ready": ready,
        "candidates": candidates,
    }
    evidence = [
        {
            "candidate_id": candidate["candidate_id"],
            "rank": index + 1,
            "scores": {
                "rerank_score": 0.9 - index * 0.2,
                "rrf_normalized_score": 0.8 - index * 0.1,
                "channel_support_score": 1.0,
                "bm25_score": 10.0 - index,
                "vector_score": 0.9 - index * 0.2,
                "bm25_rank": index + 1,
                "vector_rank": index + 1,
            },
        }
        for index, candidate in enumerate(candidates)
    ]
    return build_candidate_diagnostic_observations(case, evidence)


def _run(index: int) -> dict[str, object]:
    observations = [
        *_observations("scenario-a", ready=True),
        *_observations("scenario-a", ready=False),
    ]
    unsigned = {
        "repeat_index": index,
        "sample_count": 2,
        "candidate_observation_count": 8,
        "sample_set_hash": semantic_sha256_hash_ref(["samples"]),
        "observation_set_hash": semantic_sha256_hash_ref(
            sorted(str(row["observation_hash"]) for row in observations)
        ),
        "candidate_observations": observations,
    }
    return {**unsigned, "run_hash": semantic_sha256_hash_ref(unsigned)}


def _rehash_observation(row: dict[str, object]) -> None:
    unsigned = dict(row)
    unsigned.pop("observation_hash")
    row["observation_hash"] = semantic_sha256_hash_ref(unsigned)


def _rehash_run(run: dict[str, object]) -> None:
    unsigned = dict(run)
    unsigned.pop("run_hash")
    run["run_hash"] = semantic_sha256_hash_ref(unsigned)


def test_stable_pipeline_repeatability_is_text_free_and_holdout_closed() -> None:
    result = analyze_retrieval_pipeline_repeatability(
        [_run(0), _run(1), _run(2)],
        expected_repeat_count=3,
        expected_package_count=2,
    )

    assert result["status"] == "STABLE"
    assert result["runtime_activation_permitted"] is False
    assert result["holdout_access_permitted"] is False
    assert result["measurement"]["comparison_count"] == 16
    assert result["stages"]["first_unstable_stage"] is None
    assert result["stages"]["max_reranker_score_delta"] == 0.0
    assert str(result["repeatability_hash"]).startswith("sha256:")


@pytest.mark.parametrize(
    "mutation,stage,count_field",
    [
        (
            lambda row: row["signals"].update(bm25_rank=4),
            "BM25_RANK",
            "bm25_rank_change_count",
        ),
        (
            lambda row: row["signals"].update(vector_rank=4),
            "VECTOR_RANK",
            "vector_rank_change_count",
        ),
        (
            lambda row: row["signals"].update(bm25_score_quality=0.7),
            "BM25_SCORE_QUALITY",
            "bm25_score_quality_drift_count",
        ),
        (
            lambda row: row["signals"].update(vector_similarity_quality=0.7),
            "VECTOR_SIMILARITY_QUALITY",
            "vector_similarity_quality_drift_count",
        ),
        (
            lambda row: row["signals"].update(rrf_normalized_score=0.7),
            "RRF_SCORE",
            "rrf_score_drift_count",
        ),
        (
            lambda row: row["signals"].update(reranker_score=0.8),
            "RERANKER_SCORE",
            "reranker_score_drift_count",
        ),
        (
            lambda row: row.update(rank=4),
            "FINAL_RANK",
            "final_rank_change_count",
        ),
    ],
)
def test_detects_first_unstable_pipeline_stage(mutation, stage: str, count_field: str) -> None:
    baseline = _run(0)
    changed = _run(1)
    row = changed["candidate_observations"][0]
    mutation(row)
    _rehash_observation(row)
    _rehash_run(changed)

    result = analyze_retrieval_pipeline_repeatability(
        [baseline, changed],
        expected_repeat_count=2,
        expected_package_count=2,
    )

    assert result["status"] == "UNSTABLE"
    assert result["stages"]["first_unstable_stage"] == stage
    assert result["stages"][count_field] == 1


def test_score_delta_within_admitted_tolerance_remains_stable() -> None:
    baseline = _run(0)
    changed = _run(1)
    row = changed["candidate_observations"][0]
    row["signals"]["reranker_score"] += 0.0004
    _rehash_observation(row)
    _rehash_run(changed)

    result = analyze_retrieval_pipeline_repeatability(
        [baseline, changed],
        expected_repeat_count=2,
        expected_package_count=2,
    )
    assert result["status"] == "STABLE"
    assert result["stages"]["max_reranker_score_delta"] == 0.0004


def test_rejects_membership_drift_tamper_replay_and_invalid_configuration() -> None:
    baseline = _run(0)
    changed = _run(1)
    row = changed["candidate_observations"][0]
    row["candidate_id"] = "replacement"
    _rehash_observation(row)
    _rehash_run(changed)
    result = analyze_retrieval_pipeline_repeatability(
        [baseline, changed],
        expected_repeat_count=2,
        expected_package_count=2,
    )
    assert result["stages"]["first_unstable_stage"] == "CANDIDATE_MEMBERSHIP"

    tampered = deepcopy(_run(0))
    tampered["candidate_observations"][0]["rank"] = 4
    with pytest.raises(ValueError, match="run integrity"):
        analyze_retrieval_pipeline_repeatability(
            [tampered], expected_repeat_count=1, expected_package_count=2
        )

    replay = _run(0)
    replay["candidate_observations"][1]["candidate_id"] = replay[
        "candidate_observations"
    ][0]["candidate_id"]
    _rehash_observation(replay["candidate_observations"][1])
    _rehash_run(replay)
    with pytest.raises(ValueError, match="duplicated"):
        analyze_retrieval_pipeline_repeatability(
            [replay], expected_repeat_count=1, expected_package_count=2
        )

    with pytest.raises(ValueError, match="tolerances"):
        analyze_retrieval_pipeline_repeatability(
            [_run(0)],
            expected_repeat_count=1,
            expected_package_count=2,
            reranker_score_tolerance=0.1,
        )


def test_rejects_incomplete_runs_indexes_observations_and_package_coverage() -> None:
    with pytest.raises(ValueError, match="runs are incomplete"):
        analyze_retrieval_pipeline_repeatability(
            [], expected_repeat_count=1, expected_package_count=2
        )

    bad_index = _run(1)
    with pytest.raises(ValueError, match="indexes"):
        analyze_retrieval_pipeline_repeatability(
            [bad_index], expected_repeat_count=1, expected_package_count=2
        )

    bad_observations = _run(0)
    bad_observations["candidate_observations"] = "bad"
    _rehash_run(bad_observations)
    with pytest.raises(TypeError, match="observations"):
        analyze_retrieval_pipeline_repeatability(
            [bad_observations], expected_repeat_count=1, expected_package_count=2
        )

    incomplete = _run(0)
    incomplete["candidate_observations"].pop()
    incomplete["candidate_observation_count"] = 7
    _rehash_run(incomplete)
    with pytest.raises(ValueError, match="coverage"):
        analyze_retrieval_pipeline_repeatability(
            [incomplete], expected_repeat_count=1, expected_package_count=2
        )

    wrong_packages = _run(0)
    for row in wrong_packages["candidate_observations"][-4:]:
        row["sample_id"] = "scenario-a:positive"
        _rehash_observation(row)
    _rehash_run(wrong_packages)
    with pytest.raises((ValueError, TypeError), match="duplicated|package coverage"):
        analyze_retrieval_pipeline_repeatability(
            [wrong_packages], expected_repeat_count=1, expected_package_count=2
        )

    one_package = _run(0)
    for index, row in enumerate(one_package["candidate_observations"][-4:]):
        row["sample_id"] = "scenario-a:positive"
        row["candidate_id"] = f"replacement-{index}"
        _rehash_observation(row)
    _rehash_run(one_package)
    with pytest.raises(ValueError, match="package coverage"):
        analyze_retrieval_pipeline_repeatability(
            [one_package], expected_repeat_count=1, expected_package_count=2
        )

    bad_integrity = _run(0)
    bad_integrity["candidate_observations"][0]["rank"] = 4
    _rehash_run(bad_integrity)
    with pytest.raises(ValueError, match="observation integrity"):
        analyze_retrieval_pipeline_repeatability(
            [bad_integrity], expected_repeat_count=1, expected_package_count=2
        )

    with pytest.raises(ValueError, match="hash"):
        repeatability._hash_ref("bad", "hash")


@pytest.mark.parametrize(
    "mutation,error,match",
    [
        (lambda run: run["candidate_observations"].__setitem__(0, "bad"), TypeError, "observation"),
        (
            lambda run: run["candidate_observations"][0].update(
                observation_schema_version="wrong"
            ),
            ValueError,
            "schema",
        ),
        (
            lambda run: run["candidate_observations"][0].update(sample_id=""),
            ValueError,
            "sample_id",
        ),
        (
            lambda run: run["candidate_observations"][0].update(rank=True),
            ValueError,
            "rank",
        ),
        (
            lambda run: run["candidate_observations"][0]["signals"].update(
                reranker_score=2.0
            ),
            ValueError,
            "reranker_score",
        ),
    ],
)
def test_rejects_malformed_observation_fields(mutation, error, match: str) -> None:
    run = _run(0)
    mutation(run)
    if isinstance(run["candidate_observations"][0], dict):
        _rehash_observation(run["candidate_observations"][0])
    _rehash_run(run)
    with pytest.raises(error, match=match):
        analyze_retrieval_pipeline_repeatability(
            [run], expected_repeat_count=1, expected_package_count=2
        )
