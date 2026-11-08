from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import nex_cx.retrieval_calibration_nested_selection as selection
import pytest
from nex_cx.retrieval_calibration_nested_selection import (
    evaluate_candidate_probability_package_repeatability,
    select_nested_candidate_probability_profile,
    select_nested_retrieval_profile,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "scripts" / "smoke" / "data"


def _artifacts() -> tuple[dict, dict]:
    design = json.loads(
        (DATA / "s136_retrieval_package_calibration_v4_design.json").read_text()
    )
    folds = json.loads(
        (DATA / "s136_retrieval_package_calibration_v4_folds.json").read_text()
    )
    return design, folds


def _samples(*, discriminative: bool) -> list[dict]:
    dataset = json.loads(
        (DATA / "s136_retrieval_package_calibration_v4.json").read_text()
    )
    rows = []
    for case in dataset["cases"]:
        if case["partition"] != "CALIBRATION":
            continue
        label = "positive" if case["expected_ready"] else "negative"
        for candidate in case["candidates"]:
            relevant = candidate["expected_relevant"]
            score = (0.9 if relevant else 0.1) if discriminative else 0.5
            row = {
                "sample_schema_version": (
                    "cx_retrieval_confidence_candidate_relevance_sample.v2"
                ),
                "sample_id": f"{case['scenario_id']}:{label}",
                "candidate_id": candidate["candidate_id"],
                "expected_ready": case["expected_ready"],
                "expected_relevant": relevant,
                "signals": {
                    "reranker_score": score,
                    "rrf_normalized_score": score,
                    "channel_rank_quality": score,
                    "bm25_score_quality": score,
                    "vector_similarity_quality": score,
                },
            }
            row["sample_hash"] = semantic_sha256_hash_ref(row)
            rows.append(row)
    return rows


def _binding() -> dict[str, str]:
    return {
        "embedding_model_revision": "embedding-revision",
        "reranker_model_revision": "reranker-revision",
        "ranking_policy_id": "ranking-v1",
        "tokenizer_policy_id": "tokenizer-v1",
        "chunk_policy_id": "chunk-v1",
    }


def test_probability_nested_selection_admits_without_fold_leakage() -> None:
    design, folds = _artifacts()
    result = select_nested_candidate_probability_profile(
        _samples(discriminative=True),
        dataset_id="dataset-v4",
        dataset_sha256="dataset-sha",
        design=design,
        fold_plan=folds,
        expected_binding=_binding(),
    )

    assert result["status"] == "CALIBRATION_OOF_ADMITTED"
    assert result["protocol"]["package_signal_mode"] == (
        "CANDIDATE_PROBABILITY_AT_LEAST_TWO_V1"
    )
    assert result["protocol"]["candidate_probability_fit_scope"] == (
        "EACH_INNER_TRAINING_FOLD"
    )
    assert result["selected"]["profile_id"] == "reranker-only-v1"
    assert result["selected"]["candidate_probability_model"]["training"][
        "candidate_count"
    ] == 640
    assert all(result["checks"].values())
    assert result["holdout_access_permitted"] is False
    assert result["runtime_activation_permitted"] is False
    for outer in result["outer_folds"]:
        assert outer["candidate_probability_training_candidate_count"] == 512
        for profile in outer["inner_selection"]:
            assert profile["probability_fit_failures"] == 0
            assert len(profile["inner_folds"]) == 4
            assert {
                fold["candidate_probability_training_candidate_count"]
                for fold in profile["inner_folds"]
            } == {384}


def test_probability_nested_selection_rejects_non_directional_signal() -> None:
    design, folds = _artifacts()
    result = select_nested_candidate_probability_profile(
        _samples(discriminative=False),
        dataset_id="dataset-v4",
        dataset_sha256="dataset-sha",
        design=design,
        fold_plan=folds,
        expected_binding=_binding(),
    )

    assert result["status"] == "NO_ADMISSIBLE_PROFILE"
    assert result["selected"] is None
    assert result["checks"]["all_outer_folds_evaluated"] is False
    assert all(
        profile["probability_fit_failures"] == 4
        for outer in result["outer_folds"]
        for profile in outer["inner_selection"]
    )
    assert result["holdout"] == {
        "status": "SEALED_NOT_OPENED",
        "scenario_count": 20,
        "threshold_reselected": False,
    }


def test_legacy_second_highest_selector_remains_available() -> None:
    design, folds = _artifacts()
    samples = _samples(discriminative=True)

    legacy = select_nested_retrieval_profile(
        samples,
        dataset_id="dataset-v4",
        dataset_sha256="dataset-sha",
        design=design,
        fold_plan=folds,
        expected_binding=_binding(),
    )
    probability = select_nested_candidate_probability_profile(
        samples,
        dataset_id="dataset-v4",
        dataset_sha256="dataset-sha",
        design=design,
        fold_plan=folds,
        expected_binding=_binding(),
    )

    assert legacy["selection_schema_version"] == (
        "cx_retrieval_nested_profile_selection.v1"
    )
    assert "package_signal_mode" not in legacy["protocol"]
    assert probability["selection_schema_version"] != (
        legacy["selection_schema_version"]
    )


def test_probability_nested_final_fit_failure_remains_fail_closed(
    monkeypatch,
) -> None:
    design, folds = _artifacts()
    samples = _samples(discriminative=True)
    actual_evaluator = selection.evaluate_binary_score_calibration

    def select() -> dict:
        return select_nested_candidate_probability_profile(
            samples,
            dataset_id="dataset-v4",
            dataset_sha256="dataset-sha",
            design=design,
            fold_plan=folds,
            expected_binding=_binding(),
        )

    def evaluator(rows, *, dataset_id, constraints):
        if ":full-calibration" in dataset_id:
            return {
                "status": "NO_ACCEPTABLE_THRESHOLD",
                "selected_threshold": None,
                "best_effort_metrics": None,
            }
        return actual_evaluator(rows, dataset_id=dataset_id, constraints=constraints)

    monkeypatch.setattr(
        selection,
        "evaluate_binary_score_calibration",
        evaluator,
    )
    final = select()
    assert final["status"] == "NO_ADMISSIBLE_PROFILE"
    assert final["checks"][
        "full_calibration_probability_and_threshold_fitted"
    ] is False


def test_package_ready_repeatability_requires_invariant_admitted_decisions() -> None:
    design, folds = _artifacts()
    samples = _samples(discriminative=True)
    admitted = select_nested_candidate_probability_profile(
        samples,
        dataset_id="dataset-v4",
        dataset_sha256="dataset-sha",
        design=design,
        fold_plan=folds,
        expected_binding=_binding(),
    )

    stable = evaluate_candidate_probability_package_repeatability(
        [samples, deepcopy(samples)],
        selection_result=admitted,
        design=design,
        expected_binding=_binding(),
        expected_repeat_count=2,
    )
    changed_samples = deepcopy(samples)
    for row in changed_samples:
        row["signals"]["reranker_score"] = 0.0
        unsigned = dict(row)
        unsigned.pop("sample_hash")
        row["sample_hash"] = semantic_sha256_hash_ref(unsigned)
    unstable = evaluate_candidate_probability_package_repeatability(
        [samples, changed_samples],
        selection_result=admitted,
        design=design,
        expected_binding=_binding(),
        expected_repeat_count=2,
    )

    assert stable["status"] == "STABLE"
    assert stable["decision_change_count"] == 0
    assert stable["admission_permitted"] is True
    assert unstable["status"] == "UNSTABLE"
    assert unstable["decision_change_count"] > 0
    assert unstable["admission_permitted"] is False
    assert unstable["holdout_access_permitted"] is False


def test_package_ready_repeatability_is_not_applicable_without_profile() -> None:
    result = evaluate_candidate_probability_package_repeatability(
        [],
        selection_result={"status": "NO_ADMISSIBLE_PROFILE"},
        design={},
        expected_binding={},
    )

    assert result["status"] == "NOT_APPLICABLE_PROFILE_NOT_ADMITTED"
    assert result["admission_permitted"] is False
    assert result["runtime_activation_permitted"] is False

    with pytest.raises(ValueError, match="repeat samples are incomplete"):
        evaluate_candidate_probability_package_repeatability(
            [],
            selection_result={"status": "CALIBRATION_OOF_ADMITTED"},
            design={},
            expected_binding={},
            expected_repeat_count=2,
        )
