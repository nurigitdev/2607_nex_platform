from __future__ import annotations

from copy import deepcopy

import nex_cx.retrieval_candidate_relevance_calibration as calibration
import pytest
from nex_cx.retrieval_candidate_relevance_calibration import (
    EXPANDED_CANDIDATE_RELEVANCE_POLICY_ID,
    CandidateRelevanceConstraints,
    calibrate_candidate_relevance_policy,
    diagnose_candidate_relevance_profile_outcomes,
)
from nex_cx.retrieval_confidence_candidate_diagnostics import (
    CANDIDATE_RELEVANCE_SAMPLE_SCHEMA_VERSION,
    EXPANDED_CANDIDATE_RELEVANCE_SAMPLE_SCHEMA_VERSION,
    EXPANDED_CANDIDATE_SIGNAL_FIELDS,
)
from nex_runtime import BinaryCalibrationConstraints
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref


def _samples(*, separated: bool = True) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for scenario_index in range(6):
        for ready in (True, False):
            sample_id = f"scenario-{scenario_index}:{'positive' if ready else 'negative'}"
            for candidate_index in range(4):
                relevant = ready and candidate_index < 2
                if separated:
                    value = 0.9 - candidate_index * 0.05 if relevant else 0.2
                else:
                    value = 0.5
                unsigned = {
                    "sample_schema_version": CANDIDATE_RELEVANCE_SAMPLE_SCHEMA_VERSION,
                    "sample_id": sample_id,
                    "candidate_id": f"candidate-{candidate_index}",
                    "expected_ready": ready,
                    "expected_relevant": relevant,
                    "signals": {
                        "reranker_score": value,
                        "rrf_normalized_score": value,
                        "channel_rank_quality": value,
                    },
                }
                rows.append(
                    {**unsigned, "sample_hash": semantic_sha256_hash_ref(unsigned)}
                )
    return rows


def _constraints() -> CandidateRelevanceConstraints:
    return CandidateRelevanceConstraints(
        fold_count=3,
        grid_step=0.5,
        minimum_candidate_auc=0.7,
        calibration=BinaryCalibrationConstraints(
            minimum_sample_count=4,
            minimum_positive_count=2,
            minimum_negative_count=2,
            maximum_false_ready_rate=0.1,
            minimum_ready_recall=0.8,
        ),
    )


def _expanded_samples() -> list[dict[str, object]]:
    rows = _samples()
    for row in rows:
        row["sample_schema_version"] = (
            EXPANDED_CANDIDATE_RELEVANCE_SAMPLE_SCHEMA_VERSION
        )
        signals = row["signals"]
        signals["bm25_score_quality"] = signals["reranker_score"]
        signals["vector_similarity_quality"] = signals["reranker_score"]
        unsigned = dict(row)
        unsigned.pop("sample_hash")
        row["sample_hash"] = semantic_sha256_hash_ref(unsigned)
    return rows


def _repeatability(status: str = "STABLE") -> dict[str, str]:
    return {
        "status": status,
        "repeatability_hash": "sha256:" + "a" * 64,
    }


def _binding() -> dict[str, str]:
    return {
        "chunk_policy_id": "chunk-1000-100",
        "embedding_model_revision": "embedding-revision",
        "ranking_policy_id": "weighted-rrf",
        "reranker_model_revision": "hf:" + "b" * 40,
        "tokenizer_policy_id": "mecab-ko",
    }


def test_freezes_candidate_relevance_policy_with_two_evidence_semantics() -> None:
    result = calibrate_candidate_relevance_policy(
        _samples(),
        dataset_id="dataset-v3",
        dataset_sha256="c" * 64,
        expected_binding=_binding(),
        pipeline_repeatability=_repeatability(),
        numeric_tolerance=0.0005,
        constraints=_constraints(),
    )

    assert result["status"] == "FROZEN"
    assert result["runtime_activation_permitted"] is False
    assert result["holdout_access_permitted"] is False
    assert result["semantics"]["package_score"] == "SECOND_HIGHEST_CANDIDATE_SCORE"
    assert result["selected"]["candidate_auc"] == 1.0
    assert result["selected"]["oof_metrics"]["false_ready_rate"] == 0.0
    assert result["selected"]["oof_metrics"]["ready_recall"] == 1.0
    assert result["frozen_policy"]["runtime_activation_permitted"] is False
    assert result["frozen_policy"]["holdout_status"] == "SEALED_NOT_OPENED"


def test_expanded_channel_signal_policy_is_explicit_and_deterministic() -> None:
    result = calibrate_candidate_relevance_policy(
        _expanded_samples(),
        dataset_id="dataset-v3",
        dataset_sha256="c" * 64,
        expected_binding=_binding(),
        pipeline_repeatability=_repeatability(),
        numeric_tolerance=0.0005,
        constraints=_constraints(),
        signal_fields=EXPANDED_CANDIDATE_SIGNAL_FIELDS,
        policy_id=EXPANDED_CANDIDATE_RELEVANCE_POLICY_ID,
    )

    assert result["status"] == "FROZEN"
    assert result["policy_id"] == EXPANDED_CANDIDATE_RELEVANCE_POLICY_ID
    assert result["search"]["signal_fields"] == list(
        EXPANDED_CANDIDATE_SIGNAL_FIELDS
    )
    assert set(result["search"]["signal_diagnostics"]) == set(
        EXPANDED_CANDIDATE_SIGNAL_FIELDS
    )
    assert result["frozen_policy"]["policy_id"] == result["policy_id"]


def test_unstable_pipeline_and_inseparable_features_fail_closed() -> None:
    unstable = calibrate_candidate_relevance_policy(
        _samples(),
        dataset_id="dataset-v3",
        dataset_sha256="c" * 64,
        expected_binding=_binding(),
        pipeline_repeatability=_repeatability("UNSTABLE"),
        numeric_tolerance=0.0005,
        constraints=_constraints(),
    )
    assert unstable["status"] == "PIPELINE_UNSTABLE"
    assert unstable["selected"] is not None
    assert unstable["frozen_policy"] is None

    rejected = calibrate_candidate_relevance_policy(
        _samples(separated=False),
        dataset_id="dataset-v3",
        dataset_sha256="c" * 64,
        expected_binding=_binding(),
        pipeline_repeatability=_repeatability(),
        numeric_tolerance=0.0005,
        constraints=_constraints(),
    )
    assert rejected["status"] == "NO_ACCEPTABLE_POLICY"
    assert rejected["best_effort"]["candidate_auc"] == 0.5
    assert rejected["frozen_policy"] is None


def test_replay_is_deterministic_and_tamper_or_semantic_drift_is_rejected() -> None:
    kwargs = {
        "dataset_id": "dataset-v3",
        "dataset_sha256": "c" * 64,
        "expected_binding": _binding(),
        "pipeline_repeatability": _repeatability(),
        "numeric_tolerance": 0.0005,
        "constraints": _constraints(),
    }
    first = calibrate_candidate_relevance_policy(_samples(), **kwargs)
    replay = calibrate_candidate_relevance_policy(_samples(), **kwargs)
    assert replay["calibration_hash"] == first["calibration_hash"]
    assert replay["frozen_policy"]["policy_hash"] == first["frozen_policy"]["policy_hash"]

    tampered = deepcopy(_samples())
    tampered[0]["signals"]["reranker_score"] = 0.0
    with pytest.raises(ValueError, match="integrity"):
        calibrate_candidate_relevance_policy(tampered, **kwargs)

    missing = _samples()[:-1]
    with pytest.raises(ValueError, match="package semantics"):
        calibrate_candidate_relevance_policy(missing, **kwargs)

    duplicated = [*_samples(), deepcopy(_samples()[0])]
    with pytest.raises(ValueError, match="integrity"):
        calibrate_candidate_relevance_policy(duplicated, **kwargs)

    with pytest.raises(ValueError, match="numeric_tolerance"):
        calibrate_candidate_relevance_policy(
            _samples(), **{**kwargs, "numeric_tolerance": 0.0}
        )


def test_rejects_invalid_constraints_samples_binding_and_fold_shape() -> None:
    with pytest.raises(ValueError, match="constraints"):
        CandidateRelevanceConstraints(fold_count=1)
    with pytest.raises(TypeError, match="samples"):
        calibration._normalize_samples("bad")
    with pytest.raises(TypeError, match="sample"):
        calibration._normalize_samples(["bad"])

    wrong_schema = _samples()
    wrong_schema[0]["sample_schema_version"] = "wrong"
    unsigned = dict(wrong_schema[0])
    unsigned.pop("sample_hash")
    wrong_schema[0]["sample_hash"] = semantic_sha256_hash_ref(unsigned)
    with pytest.raises(ValueError, match="schema"):
        calibration._normalize_samples(wrong_schema)

    wrong_label = _samples()
    wrong_label[0]["expected_relevant"] = "yes"
    unsigned = dict(wrong_label[0])
    unsigned.pop("sample_hash")
    wrong_label[0]["sample_hash"] = semantic_sha256_hash_ref(unsigned)
    with pytest.raises(TypeError, match="labels"):
        calibration._normalize_samples(wrong_label)

    one_label = [row for row in _samples() if not row["sample_id"].endswith(":negative")]
    with pytest.raises(ValueError, match="pairs"):
        calibration._normalize_samples(one_label)

    with pytest.raises(ValueError, match="folds"):
        calibration._fold_groups(["one"], dataset_id="dataset", count=2)
    with pytest.raises(ValueError, match="AUC labels"):
        calibration._auc({("sample", "candidate"): {"expected_relevant": True, "score": 0.5}})

    with pytest.raises(TypeError, match="binding"):
        calibrate_candidate_relevance_policy(
            _samples(),
            dataset_id="dataset-v3",
            dataset_sha256="c" * 64,
            expected_binding=[],  # type: ignore[arg-type]
            pipeline_repeatability=_repeatability(),
            numeric_tolerance=0.0005,
            constraints=_constraints(),
        )

    with pytest.raises(TypeError, match="signal fields"):
        calibration._signal_fields("reranker_score")
    with pytest.raises(ValueError, match="signal fields"):
        calibration._signal_fields(("reranker_score", "reranker_score"))
    with pytest.raises(ValueError, match="signal fields"):
        calibration._signal_fields(("unknown",))

    assert calibration._signal_tolerances(
        ("vector_similarity_quality",),
        reranker_tolerance=0.0005,
        values=None,
    ) == {"vector_similarity_quality": 0.0}
    with pytest.raises(TypeError, match="signal tolerances"):
        calibration._signal_tolerances(
            ("reranker_score",),
            reranker_tolerance=0.0005,
            values=[],  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="signal tolerances"):
        calibration._signal_tolerances(
            ("reranker_score",),
            reranker_tolerance=0.0005,
            values={"unknown": 0.0},
        )
    with pytest.raises(ValueError, match="signal tolerances"):
        calibration._signal_tolerances(
            ("reranker_score",),
            reranker_tolerance=0.0005,
            values={"reranker_score": True},
        )
    with pytest.raises(ValueError, match="signal tolerances"):
        calibration._signal_tolerances(
            ("reranker_score",),
            reranker_tolerance=0.0005,
            values={"reranker_score": 0.001},
        )


def test_defensive_helpers_and_unavailable_fold_threshold() -> None:
    with pytest.raises(ValueError, match="identity"):
        calibration._group_id("bad")
    with pytest.raises(ValueError, match="required"):
        calibration._required_string("", "required")
    with pytest.raises(ValueError, match="hash"):
        calibration._hash_ref("bad", "hash")
    with pytest.raises(ValueError, match="score"):
        calibration._score(float("nan"), "score")
    assert calibration._ratio(1, 0) == 0.0

    normalized, _groups, packages = calibration._normalize_samples(_samples())
    rejected = calibration._evaluate_profile(
        normalized,
        packages=packages,
        feature_fields=("reranker_score",),
        weights={"reranker_score": 1.0},
        folds=calibration._fold_groups(
            [f"scenario-{index}" for index in range(6)],
            dataset_id="dataset-v3",
            count=3,
        ),
        dataset_id="dataset-v3",
        numeric_tolerance=0.0005,
        constraints=CandidateRelevanceConstraints(
            fold_count=3,
            grid_step=1.0,
            calibration=BinaryCalibrationConstraints(
                minimum_sample_count=100,
                minimum_positive_count=50,
                minimum_negative_count=50,
            ),
        ),
    )
    assert rejected["reason_code"] == "FOLD_TRAINING_THRESHOLD_UNAVAILABLE"


def test_profile_outcome_diagnostic_reconstructs_exact_group_cv_metrics() -> None:
    samples = _expanded_samples()
    calibration_result = calibrate_candidate_relevance_policy(
        samples,
        dataset_id="dataset-v3",
        dataset_sha256="c" * 64,
        expected_binding=_binding(),
        pipeline_repeatability=_repeatability(),
        numeric_tolerance=0.0005,
        constraints=_constraints(),
        signal_fields=EXPANDED_CANDIDATE_SIGNAL_FIELDS,
        policy_id=EXPANDED_CANDIDATE_RELEVANCE_POLICY_ID,
    )
    diagnostic = diagnose_candidate_relevance_profile_outcomes(
        samples,
        dataset_id="dataset-v3",
        profile=calibration_result["selected"],
        numeric_tolerance=0.0005,
        signal_fields=EXPANDED_CANDIDATE_SIGNAL_FIELDS,
    )

    assert diagnostic["status"] == "DIAGNOSED"
    assert diagnostic["metrics"] == calibration_result["selected"]["oof_metrics"]
    assert len(diagnostic["outcomes"]) == 12
    assert all(len(row["ranked_candidates"]) == 4 for row in diagnostic["outcomes"])
    assert diagnostic["runtime_activation_permitted"] is False
    assert diagnostic["holdout_access_permitted"] is False


def test_profile_outcome_diagnostic_rejects_profile_drift() -> None:
    samples = _expanded_samples()
    result = calibrate_candidate_relevance_policy(
        samples,
        dataset_id="dataset-v3",
        dataset_sha256="c" * 64,
        expected_binding=_binding(),
        pipeline_repeatability=_repeatability(),
        numeric_tolerance=0.0005,
        constraints=_constraints(),
        signal_fields=EXPANDED_CANDIDATE_SIGNAL_FIELDS,
    )
    profile = deepcopy(result["selected"])
    profile["weights"] = {profile["feature_fields"][0]: 0.5}
    with pytest.raises(ValueError, match="weights"):
        diagnose_candidate_relevance_profile_outcomes(
            samples,
            dataset_id="dataset-v3",
            profile=profile,
            numeric_tolerance=0.0005,
            signal_fields=EXPANDED_CANDIDATE_SIGNAL_FIELDS,
        )

    profile = deepcopy(result["selected"])
    profile["folds"][0]["threshold"] = 0.0
    with pytest.raises(ValueError, match="do not match"):
        diagnose_candidate_relevance_profile_outcomes(
            samples,
            dataset_id="dataset-v3",
            profile=profile,
            numeric_tolerance=0.0005,
            signal_fields=EXPANDED_CANDIDATE_SIGNAL_FIELDS,
        )
