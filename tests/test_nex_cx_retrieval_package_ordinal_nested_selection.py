from __future__ import annotations

import json
from pathlib import Path

import nex_cx.retrieval_package_ordinal_nested_selection as selection
import pytest
from nex_cx.retrieval_package_ready_calibrator import (
    validate_package_ordinal_calibrator_design,
)
from nex_cx.retrieval_package_ordinal_nested_selection import (
    select_nested_package_ordinal_profile,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "scripts" / "smoke" / "data"


def _artifacts() -> tuple[dict, dict, dict]:
    retrieval = json.loads(
        (DATA / "s136_retrieval_package_calibration_v4_design.json").read_text()
    )
    folds = json.loads(
        (DATA / "s136_retrieval_package_calibration_v4_folds.json").read_text()
    )
    ordinal = json.loads(
        (DATA / "s136_package_ordinal_calibrator_v1_design.json").read_text()
    )
    return retrieval, folds, ordinal


def _binding() -> dict[str, str]:
    return {
        "embedding_model_revision": "embedding-revision",
        "reranker_model_revision": "reranker-revision",
        "ranking_policy_id": "ranking-v1",
        "tokenizer_policy_id": "tokenizer-v1",
        "chunk_policy_id": "chunk-v1",
    }


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


def _select(*, discriminative: bool) -> dict:
    retrieval, folds, ordinal = _artifacts()
    return select_nested_package_ordinal_profile(
        _samples(discriminative=discriminative),
        dataset_id="dataset-v4",
        dataset_sha256="dataset-sha",
        retrieval_design=retrieval,
        fold_plan=folds,
        ordinal_design=ordinal,
        expected_binding=_binding(),
    )


def test_nested_ordinal_selection_admits_without_fold_leakage() -> None:
    result = _select(discriminative=True)

    assert result["status"] == "CALIBRATION_OOF_ADMITTED"
    assert result["protocol"]["combination_count"] == 16
    assert result["protocol"]["package_signal_mode"] == (
        "DEPENDENCE_ROBUST_ORDINAL_SCORE_V1"
    )
    assert result["selected"]["candidate_probability_model"]["training"][
        "candidate_count"
    ] == 640
    assert all(result["checks"].values())
    assert result["holdout_access_permitted"] is False
    assert result["runtime_activation_permitted"] is False
    for outer in result["outer_folds"]:
        assert outer["candidate_probability_training_candidate_count"] == 512
        for combination in outer["inner_selection"]:
            assert {
                fold["candidate_probability_training_candidate_count"]
                for fold in combination["inner_folds"]
            } == {384}


def test_nested_ordinal_selection_rejects_non_directional_candidates() -> None:
    result = _select(discriminative=False)

    assert result["status"] == "NO_ADMISSIBLE_PROFILE"
    assert result["selected"] is None
    assert result["holdout"]["status"] == "SEALED_NOT_OPENED"
    assert all(
        combination["probability_fit_failures"] == 4
        for outer in result["outer_folds"]
        for combination in outer["inner_selection"]
    )


def test_full_refit_failure_remains_fail_closed(monkeypatch) -> None:
    actual = selection.evaluate_binary_score_calibration

    def evaluator(rows, *, dataset_id, constraints):
        if "full-calibration" in dataset_id:
            return {
                "status": "NO_ACCEPTABLE_THRESHOLD",
                "selected_threshold": None,
                "best_effort_metrics": None,
            }
        return actual(rows, dataset_id=dataset_id, constraints=constraints)

    monkeypatch.setattr(selection, "evaluate_binary_score_calibration", evaluator)
    result = _select(discriminative=True)

    assert result["status"] == "NO_ADMISSIBLE_PROFILE"
    assert result["selected"] is None
    assert result["checks"][
        "full_calibration_probability_and_threshold_fitted"
    ] is False


def test_full_probability_refit_failure_remains_fail_closed(monkeypatch) -> None:
    actual = selection._fit_probability_and_features

    def fit(*args, training_scope, **kwargs):
        model, features = actual(*args, training_scope=training_scope, **kwargs)
        return (model, None) if training_scope == "CALIBRATION_FULL_ORDINAL_REFIT" else (model, features)

    monkeypatch.setattr(selection, "_fit_probability_and_features", fit)
    result = _select(discriminative=True)

    assert result["status"] == "NO_ADMISSIBLE_PROFILE"
    assert result["checks"][
        "full_calibration_probability_and_threshold_fitted"
    ] is False


def _outer_scope() -> tuple:
    retrieval, folds, ordinal = _artifacts()
    samples, scenario_ids = selection.nested_support._normalize_samples(
        _samples(discriminative=True)
    )
    outer = selection.nested_support._outer_folds(
        folds, expected_scenarios=scenario_ids
    )[0]
    candidate = selection.nested_support._profiles(
        retrieval["selection_protocol"]["profile_shortlist"]
    )[0]
    package = validate_package_ordinal_calibrator_design(ordinal)[
        "profile_shortlist"
    ][0]
    constraints = selection._constraints(retrieval["admission"])
    return retrieval, samples, outer, candidate, package, constraints


def test_outer_probability_refit_failure_is_explicit(monkeypatch) -> None:
    retrieval, samples, outer, candidate, package, constraints = _outer_scope()
    actual = selection._fit_probability_and_features

    def fit(*args, training_scope, **kwargs):
        model, features = actual(*args, training_scope=training_scope, **kwargs)
        if training_scope.endswith("ORDINAL_REFIT"):
            return model, None
        return model, features

    monkeypatch.setattr(selection, "_fit_probability_and_features", fit)
    result, candidates = selection._evaluate_outer_fold(
        samples,
        outer=outer,
        candidate_profiles=[candidate],
        package_profiles=[package],
        package_design_hash="sha256:" + "a" * 64,
        constraints=constraints,
        minimum_candidate_auc=retrieval["admission"]["minimum_candidate_auc"],
        dataset_id="dataset-v4",
        expected_binding=_binding(),
    )

    assert result["status"] == "OUTER_PROBABILITY_REFIT_FAILED"
    assert candidates == []


def test_outer_threshold_and_inner_threshold_absence_are_explicit(
    monkeypatch,
) -> None:
    retrieval, samples, outer, candidate, package, constraints = _outer_scope()
    actual = selection.evaluate_binary_score_calibration

    def outer_refit_failure(rows, *, dataset_id, constraints):
        if dataset_id.endswith(":refit"):
            return {"selected_threshold": None}
        return actual(rows, dataset_id=dataset_id, constraints=constraints)

    monkeypatch.setattr(
        selection, "evaluate_binary_score_calibration", outer_refit_failure
    )
    result, _ = selection._evaluate_outer_fold(
        samples,
        outer=outer,
        candidate_profiles=[candidate],
        package_profiles=[package],
        package_design_hash="sha256:" + "a" * 64,
        constraints=constraints,
        minimum_candidate_auc=retrieval["admission"]["minimum_candidate_auc"],
        dataset_id="dataset-v4",
        expected_binding=_binding(),
    )
    assert result["status"] == "OUTER_REFIT_FAILED"

    def inner_fit_failure(rows, *, dataset_id, constraints):
        if ":inner-" in dataset_id and ":train:" in dataset_id:
            return {"selected_threshold": None, "best_effort_metrics": None}
        return actual(rows, dataset_id=dataset_id, constraints=constraints)

    monkeypatch.setattr(
        selection, "evaluate_binary_score_calibration", inner_fit_failure
    )
    result, _ = selection._evaluate_outer_fold(
        samples,
        outer=outer,
        candidate_profiles=[candidate],
        package_profiles=[package],
        package_design_hash="sha256:" + "a" * 64,
        constraints=constraints,
        minimum_candidate_auc=retrieval["admission"]["minimum_candidate_auc"],
        dataset_id="dataset-v4",
        expected_binding=_binding(),
    )
    assert result["status"] == "NO_ADMISSIBLE_PROFILE"


def test_combination_and_profile_binding_guards() -> None:
    assert selection._split_combination_id("candidate::package") == (
        "candidate",
        "package",
    )
    with pytest.raises(ValueError, match="combination id"):
        selection._split_combination_id("bad")
    with pytest.raises(ValueError, match="profile binding"):
        selection._find_profile([], "missing")
    assert selection._find_profile(
        [{"profile_id": "other"}, {"profile_id": "target"}], "target"
    )["profile_id"] == "target"
