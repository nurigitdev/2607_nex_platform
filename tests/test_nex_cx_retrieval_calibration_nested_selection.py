from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import nex_cx.retrieval_calibration_nested_selection as selection
import pytest
from nex_cx.retrieval_calibration_nested_selection import (
    _candidate_auc,
    _confidence_intervals,
    _hash_ref,
    _normalize_samples,
    _outer_folds,
    _partition_constraints,
    _positive_int,
    _profiles,
    _required_string,
    _scenario_id,
    _score,
    _wilson,
    select_nested_retrieval_profile,
)
from nex_runtime.model_calibration import BinaryCalibrationConstraints
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "scripts" / "smoke" / "data"


def _artifacts() -> tuple[dict, dict, dict]:
    dataset = json.loads(
        (DATA / "s136_retrieval_package_calibration_v4.json").read_text()
    )
    design = json.loads(
        (DATA / "s136_retrieval_package_calibration_v4_design.json").read_text()
    )
    folds = json.loads(
        (DATA / "s136_retrieval_package_calibration_v4_folds.json").read_text()
    )
    return dataset, design, folds


def _samples(*, discriminative: bool) -> list[dict]:
    dataset, _, _ = _artifacts()
    rows = []
    for case in dataset["cases"]:
        if case["partition"] != "CALIBRATION":
            continue
        label = "positive" if case["expected_ready"] else "negative"
        for index, candidate in enumerate(case["candidates"], start=1):
            relevant = candidate["expected_relevant"]
            score = (1.0 if relevant else 0.0) if discriminative else 0.5
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


def test_nested_selection_admits_perfect_calibration_without_opening_holdout() -> None:
    _, design, folds = _artifacts()
    result = select_nested_retrieval_profile(
        _samples(discriminative=True),
        dataset_id="s136-retrieval-package-confidence-public-v4",
        dataset_sha256="dataset-sha",
        design=design,
        fold_plan=folds,
        expected_binding=_binding(),
    )

    assert result["status"] == "CALIBRATION_OOF_ADMITTED"
    assert result["selected"]["profile_id"] == "reranker-only-v1"
    assert result["selected"]["threshold"] == 0.5
    assert result["oof_evaluation"]["candidate_auc"] == 1.0
    assert result["oof_evaluation"]["profile_selection_counts"] == {
        "reranker-only-v1": 5
    }
    assert all(result["checks"].values())
    assert result["holdout"] == {
        "status": "SEALED_NOT_OPENED",
        "scenario_count": 20,
        "threshold_reselected": False,
    }
    assert result["runtime_activation_permitted"] is False
    assert str(result["selection_hash"]).startswith("sha256:")


def test_nested_selection_returns_valid_fail_closed_result() -> None:
    _, design, folds = _artifacts()
    result = select_nested_retrieval_profile(
        _samples(discriminative=False),
        dataset_id="dataset-v4",
        dataset_sha256="dataset-sha",
        design=design,
        fold_plan=folds,
        expected_binding=_binding(),
    )

    assert result["status"] == "NO_ADMISSIBLE_PROFILE"
    assert result["selected"] is None
    assert result["oof_evaluation"]["stable_profile_id"] is None
    assert result["checks"]["all_outer_folds_evaluated"] is False
    assert result["holdout_access_permitted"] is False


def test_nested_selection_rejects_integrity_scope_and_profile_drift() -> None:
    _, design, folds = _artifacts()
    samples = _samples(discriminative=True)

    tampered = deepcopy(samples)
    tampered[0]["signals"]["reranker_score"] = 0.25
    with pytest.raises(ValueError, match="integrity"):
        select_nested_retrieval_profile(
            tampered,
            dataset_id="dataset-v4",
            dataset_sha256="sha",
            design=design,
            fold_plan=folds,
            expected_binding=_binding(),
        )

    duplicated = deepcopy(samples)
    duplicated.append(deepcopy(samples[0]))
    with pytest.raises(ValueError, match="duplicated"):
        select_nested_retrieval_profile(
            duplicated,
            dataset_id="dataset-v4",
            dataset_sha256="sha",
            design=design,
            fold_plan=folds,
            expected_binding=_binding(),
        )

    missing_fold = deepcopy(folds)
    missing_fold["assignment"]["outer_folds"][0]["validation_scenario_ids"].pop()
    with pytest.raises(ValueError, match="fold coverage"):
        select_nested_retrieval_profile(
            samples,
            dataset_id="dataset-v4",
            dataset_sha256="sha",
            design=design,
            fold_plan=missing_fold,
            expected_binding=_binding(),
        )

    duplicate_profile = deepcopy(design)
    duplicate_profile["selection_protocol"]["profile_shortlist"][1][
        "profile_id"
    ] = "reranker-only-v1"
    with pytest.raises(ValueError, match="profile"):
        select_nested_retrieval_profile(
            samples,
            dataset_id="dataset-v4",
            dataset_sha256="sha",
            design=duplicate_profile,
            fold_plan=folds,
            expected_binding=_binding(),
        )


def test_nested_selection_small_helpers_cover_guard_branches() -> None:
    assert _candidate_auc(
        [
            {"expected_relevant": True, "score": 0.5},
            {"expected_relevant": False, "score": 0.5},
        ]
    ) == 0.5
    with pytest.raises(ValueError, match="both relevance"):
        _candidate_auc([{"expected_relevant": True, "score": 1.0}])

    constraints = _partition_constraints(
        32,
        constraints=BinaryCalibrationConstraints(),
    )
    assert constraints.minimum_sample_count == 32
    assert constraints.minimum_positive_count == 16
    assert _confidence_intervals(None) is None
    assert _wilson(0, 0) == {"lower": 0.0, "upper": 1.0}


def test_nested_selection_input_guards_are_fail_closed() -> None:
    samples = _samples(discriminative=True)
    with pytest.raises(TypeError, match="samples"):
        _normalize_samples("invalid")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="sample is invalid"):
        _normalize_samples(["invalid"])  # type: ignore[list-item]

    wrong_schema = deepcopy(samples)
    wrong_schema[0]["sample_schema_version"] = "wrong"
    unsigned = dict(wrong_schema[0])
    unsigned.pop("sample_hash")
    wrong_schema[0]["sample_hash"] = semantic_sha256_hash_ref(unsigned)
    with pytest.raises(ValueError, match="schema"):
        _normalize_samples(wrong_schema)

    wrong_label = deepcopy(samples)
    wrong_label[0]["expected_ready"] = "yes"
    unsigned = dict(wrong_label[0])
    unsigned.pop("sample_hash")
    wrong_label[0]["sample_hash"] = semantic_sha256_hash_ref(unsigned)
    with pytest.raises(TypeError, match="labels"):
        _normalize_samples(wrong_label)

    with pytest.raises(ValueError, match="package coverage"):
        _normalize_samples(samples[:-1])
    positives_only = [row for row in samples if row["expected_ready"]]
    with pytest.raises(ValueError, match="scenario pairs"):
        _normalize_samples(positives_only)

    with pytest.raises(TypeError, match="shortlist"):
        _profiles("invalid")
    with pytest.raises(TypeError, match="profile is invalid"):
        _profiles(["invalid"])
    with pytest.raises(TypeError, match="outer folds"):
        _outer_folds({"assignment": {"outer_folds": "bad"}}, expected_scenarios=set())

    for call in (
        lambda: _scenario_id("bad"),
        lambda: _required_string("", "value"),
        lambda: _hash_ref("sha256:bad", "hash"),
        lambda: _score(True, "score"),
        lambda: _positive_int(0, "count"),
    ):
        with pytest.raises(ValueError):
            call()


def test_nested_selection_handles_inner_outer_and_final_fit_failures(monkeypatch) -> None:
    _, design, folds = _artifacts()
    samples = _samples(discriminative=True)
    actual = selection.evaluate_binary_score_calibration

    def run_with_failure(fragment: str) -> dict:
        def evaluator(rows, *, dataset_id, constraints):
            if fragment in dataset_id:
                return {
                    "status": "NO_ACCEPTABLE_THRESHOLD",
                    "selected_threshold": None,
                    "best_effort_metrics": None,
                }
            return actual(rows, dataset_id=dataset_id, constraints=constraints)

        monkeypatch.setattr(selection, "evaluate_binary_score_calibration", evaluator)
        return select_nested_retrieval_profile(
            samples,
            dataset_id="dataset-v4",
            dataset_sha256="sha",
            design=design,
            fold_plan=folds,
            expected_binding=_binding(),
        )

    inner = run_with_failure(":inner-")
    assert inner["status"] == "NO_ADMISSIBLE_PROFILE"

    monkeypatch.setattr(selection, "evaluate_binary_score_calibration", actual)
    outer = run_with_failure(":refit:")
    assert outer["status"] == "NO_ADMISSIBLE_PROFILE"
    assert all(row["status"] == "OUTER_REFIT_FAILED" for row in outer["outer_folds"])

    monkeypatch.setattr(selection, "evaluate_binary_score_calibration", actual)
    final = run_with_failure(":full-calibration")
    assert final["status"] == "NO_ADMISSIBLE_PROFILE"
    assert final["checks"]["full_calibration_threshold_fitted"] is False
