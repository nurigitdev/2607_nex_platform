from __future__ import annotations

from copy import deepcopy

import nex_cx.retrieval_confidence_candidate_selection as selection
import pytest
from nex_cx.retrieval_confidence_candidate_diagnostics import (
    CANDIDATE_FEATURE_SAMPLE_SCHEMA_VERSION,
)
from nex_cx.retrieval_confidence_candidate_selection import (
    CandidatePolicySelectionConstraints,
    select_and_freeze_candidate_policy,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref


def _binding() -> dict[str, str]:
    return {
        "chunk_policy_id": "chunk_1000_100",
        "embedding_model_revision": "embedding-revision",
        "ranking_policy_id": "weighted_rrf_vector_bm25_v1",
        "reranker_model_revision": "hf:" + "a" * 40,
        "tokenizer_policy_id": "tokenizer-policy",
    }


def _samples(*, separable: bool = True) -> list[dict[str, object]]:
    samples: list[dict[str, object]] = []
    for index in range(20):
        for expected_ready, label in ((True, "positive"), (False, "negative")):
            base = (
                0.82 + index * 0.002
                if expected_ready and separable
                else 0.32 + index * 0.002
                if separable
                else 0.50
            )
            sample: dict[str, object] = {
                "sample_schema_version": CANDIDATE_FEATURE_SAMPLE_SCHEMA_VERSION,
                "sample_id": f"scenario-{index}:{label}",
                "expected_ready": expected_ready,
                "features": {
                    "reranker_top_score": base,
                    "reranker_top_margin": base / 3,
                    "reranker_top2_mean": base * 0.9,
                    "reranker_second_score": base * 0.8,
                    "reranker_score_spread": base * 0.7,
                },
            }
            sample["sample_hash"] = semantic_sha256_hash_ref(sample)
            samples.append(sample)
    return samples


def _select(
    samples: list[dict[str, object]],
    **overrides: object,
) -> dict[str, object]:
    arguments = {
        "dataset_id": "dataset-v3",
        "dataset_sha256": "b" * 64,
        "expected_binding": _binding(),
        "directional_feature_fields": (
            "reranker_top_score",
            "reranker_top_margin",
            "reranker_top2_mean",
            "reranker_second_score",
            "reranker_score_spread",
        ),
        "diagnostic_hash": "sha256:" + "c" * 64,
        "repeatability_profile_id": "repeatability-v1",
        "repeatability_evidence_sha256": "sha256:" + "d" * 64,
        "revision_evidence_sha256": "sha256:" + "e" * 64,
        "numeric_tolerance": 0.0005,
        **overrides,
    }
    return select_and_freeze_candidate_policy(samples, **arguments)  # type: ignore[arg-type]


def test_selects_deterministic_calibration_only_candidate_policy() -> None:
    result = _select(_samples())
    replay = _select(list(reversed(_samples())))

    assert result == replay
    assert result["status"] == "FROZEN"
    assert result["runtime_activation_permitted"] is False
    assert result["holdout"] == {
        "status": "SEALED_NOT_OPENED",
        "threshold_reselected": False,
    }
    assert result["search"]["candidate_count"] == 455  # type: ignore[index]
    frozen = result["frozen_policy"]
    assert frozen["status"] == "CANDIDATE_FROZEN"  # type: ignore[index]
    assert frozen["runtime_activation_permitted"] is False  # type: ignore[index]
    assert frozen["policy_hash"].startswith("sha256:")  # type: ignore[index]
    assert result["selection_hash"].startswith("sha256:")  # type: ignore[index]


def test_no_acceptable_policy_fails_closed_without_freeze() -> None:
    result = _select(_samples(separable=False))

    assert result["status"] == "NO_ACCEPTABLE_POLICY"
    assert result["frozen_policy"] is None
    assert result["search"]["admissible_candidate_count"] == 0  # type: ignore[index]
    assert result["best_effort"]["status"] == "REJECTED"  # type: ignore[index]


def test_rejects_tamper_pair_drift_feature_drift_and_bad_provenance() -> None:
    tampered = deepcopy(_samples())
    tampered[0]["features"]["reranker_top_score"] = 0.1  # type: ignore[index]
    with pytest.raises(ValueError, match="integrity"):
        _select(tampered)

    incomplete = _samples()[1:]
    with pytest.raises(ValueError, match="positive and negative"):
        _select(incomplete)

    with pytest.raises(ValueError, match="directional"):
        _select(_samples(), directional_feature_fields=("rrf_top_score",))

    with pytest.raises(ValueError, match="diagnostic_hash"):
        _select(_samples(), diagnostic_hash="mutable")


@pytest.mark.parametrize(
    "kwargs,error",
    [
        ({"fold_count": 1}, "constraints"),
        ({"grid_step": 0.3}, "constraints"),
        ({"maximum_feature_count": 0}, "constraints"),
        ({"maximum_threshold_spread": 2.0}, "constraints"),
    ],
)
def test_constraint_guards(kwargs: dict[str, object], error: str) -> None:
    with pytest.raises(ValueError, match=error):
        CandidatePolicySelectionConstraints(**kwargs)  # type: ignore[arg-type]


def test_sample_shape_tolerance_and_binding_guards() -> None:
    malformed = deepcopy(_samples())
    malformed[0]["sample_schema_version"] = "wrong"
    unsigned = dict(malformed[0])
    unsigned.pop("sample_hash")
    malformed[0]["sample_hash"] = semantic_sha256_hash_ref(unsigned)
    with pytest.raises(ValueError, match="schema"):
        _select(malformed)

    with pytest.raises(ValueError, match="numeric_tolerance"):
        _select(_samples(), numeric_tolerance=0.0)
    with pytest.raises(ValueError, match="binding"):
        _select(_samples(), expected_binding={})


def test_collection_and_low_level_shape_guards() -> None:
    with pytest.raises(TypeError, match="samples"):
        _select("bad")  # type: ignore[arg-type]
    malformed = _samples()
    malformed[0] = "bad"  # type: ignore[assignment]
    with pytest.raises(TypeError, match="sample is invalid"):
        _select(malformed)

    malformed = deepcopy(_samples())
    malformed[0]["expected_ready"] = "yes"
    unsigned = dict(malformed[0])
    unsigned.pop("sample_hash")
    malformed[0]["sample_hash"] = semantic_sha256_hash_ref(unsigned)
    with pytest.raises(TypeError, match="values"):
        _select(malformed)

    with pytest.raises(TypeError, match="directional"):
        _select(_samples(), directional_feature_fields="bad")
    with pytest.raises(ValueError, match="sample_id"):
        selection._group_id("bad")
    with pytest.raises(TypeError, match="score"):
        selection._bounded_score(True, "score")
    with pytest.raises(ValueError, match="score"):
        selection._bounded_score(float("nan"), "score")
    with pytest.raises(ValueError, match="field"):
        selection._required_string("", "field")
    with pytest.raises(ValueError, match="fold"):
        selection._fold_groups(["one"], dataset_id="dataset", fold_count=2)


def test_sample_and_group_minimum_guards() -> None:
    with pytest.raises(ValueError, match="sample count"):
        _select(
            _samples()[:20],
            constraints=CandidatePolicySelectionConstraints(
                calibration=selection.BinaryCalibrationConstraints(
                    minimum_sample_count=21,
                    minimum_positive_count=8,
                    minimum_negative_count=8,
                )
            ),
        )
    with pytest.raises(ValueError, match="group count"):
        _select(
            _samples(),
            constraints=CandidatePolicySelectionConstraints(fold_count=21),
        )
