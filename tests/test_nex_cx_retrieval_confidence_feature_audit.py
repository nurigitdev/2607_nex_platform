from __future__ import annotations

import pytest
from nex_cx.retrieval_confidence_calibration import RetrievalConfidenceWeights
from nex_cx.retrieval_confidence_feature_audit import (
    audit_multisignal_feature_discriminativeness,
    diagnose_mixed_candidate_feature_discriminativeness,
)
from nex_cx.retrieval_confidence_multisignal import (
    MultiSignalCalibrationError,
    build_multisignal_feature_package,
    reweight_multisignal_feature_package,
)


def _binding() -> dict[str, str]:
    return {
        "embedding_model_revision": "embedding-revision",
        "reranker_model_revision": "hf:" + "2" * 40,
        "ranking_policy_id": "weighted_rrf_vector_bm25_v1",
        "tokenizer_policy_id": "cx-tokenizer-profile:sha256:" + "b" * 64,
        "chunk_policy_id": "chunk_1000_100",
    }


def _package(*, ready: bool, index: int) -> dict[str, object]:
    if ready:
        top, margin, rrf, channel = 0.85 + index * 0.001, 0.05, 0.85, 0.5
    else:
        top, margin, rrf, channel = 0.35 + index * 0.001, 0.30, 0.35, 0.5
    return build_multisignal_feature_package(
        [
            {
                "rank": 1,
                "scores": {
                    "bm25_rank": 1,
                    "vector_rank": 1,
                    "rrf_normalized_score": rrf,
                    "channel_support_score": channel,
                    "rerank_score": top,
                },
            },
            {
                "rank": 2,
                "scores": {
                    "bm25_rank": 2,
                    "vector_rank": 2,
                    "rrf_normalized_score": max(0.0, rrf - 0.1),
                    "channel_support_score": channel,
                    "rerank_score": top - margin,
                },
            },
        ],
        binding=_binding(),
    )


def _samples() -> list[dict[str, object]]:
    return [
        {
            "sample_id": f"group-{index:02d}:{label}",
            "expected_ready": ready,
            "feature_package": _package(ready=ready, index=index),
        }
        for index in range(20)
        for label, ready in (("positive", True), ("negative", False))
    ]


def _mixed_package(*, ready: bool, index: int) -> dict[str, object]:
    if ready:
        top, margin, rrf, channel = 0.85 + index * 0.001, 0.08, 0.88, 1.0
    else:
        top, margin, rrf, channel = 0.42 + index * 0.001, 0.02, 0.46, 0.7
    return build_multisignal_feature_package(
        [
            {
                "rank": rank,
                "scores": {
                    "bm25_rank": rank if rank <= 3 else None,
                    "vector_rank": rank,
                    "rrf_normalized_score": max(0.0, rrf - (rank - 1) * 0.1),
                    "channel_support_score": channel if rank <= 3 else 0.7,
                    "rerank_score": max(0.0, top - (rank - 1) * margin),
                },
            }
            for rank in range(1, 5)
        ],
        binding=_binding(),
    )


def _mixed_samples() -> list[dict[str, object]]:
    return [
        {
            "sample_id": f"group-{index:02d}:{label}",
            "expected_ready": ready,
            "retrieval_scope": {
                "candidate_count": 4,
                "single_mixed_candidate_retrieval": True,
                "label_filtered_retrieval": False,
            },
            "feature_package": _mixed_package(ready=ready, index=index),
        }
        for index in range(20)
        for label, ready in (("positive", True), ("negative", False))
    ]


def _audit(samples: object) -> dict[str, object]:
    return audit_multisignal_feature_discriminativeness(
        samples,  # type: ignore[arg-type]
        dataset_id="calibration-v2",
        dataset_sha256="a" * 64,
        expected_binding=_binding(),
    )


def test_feature_audit_exposes_direction_inversion_and_constant_semantics() -> None:
    result = _audit(_samples())

    assert result["status"] == "AUDITED"
    assert result["runtime_activation_permitted"] is False
    assert result["holdout_access_permitted"] is False
    assert result["dataset"] == {
        "dataset_id": "calibration-v2",
        "dataset_sha256": "a" * 64,
        "partition": "CALIBRATION",
        "sample_count": 40,
        "group_count": 20,
    }
    features = result["features"]
    assert features["reranker_score"]["classification"] == "DIRECTIONAL"
    assert features["reranker_score"]["higher_is_ready_auc"] == 1.0
    assert features["reranker_margin"]["classification"] == "INVERTED"
    assert features["reranker_margin"]["higher_is_ready_auc"] == 0.0
    assert features["channel_support"]["classification"] == "CONSTANT"
    assert features["channel_support"]["paired_delta"] == {
        "minimum": 0.0,
        "maximum": 0.0,
        "mean": 0.0,
        "median": 0.0,
        "positive_higher_count": 0,
        "tied_count": 20,
        "negative_higher_count": 0,
    }
    assert result["correlations"]["channel_support"]["reranker_score"] is None
    assert "RERANKER_MARGIN_INVERTED" in result["findings"]
    assert "CHANNEL_SUPPORT_CONSTANT" in result["findings"]


def test_feature_audit_is_order_independent_and_contains_no_raw_content() -> None:
    first = _audit(_samples())
    replay = _audit(list(reversed(_samples())))

    assert first["audit_hash"] == replay["audit_hash"]
    serialized = str(first)
    assert "query" not in serialized.lower()
    assert "document_text" not in serialized


def test_feature_audit_classifies_equal_nonconstant_distributions() -> None:
    samples = _samples()
    for index in range(20):
        samples[index * 2 + 1]["feature_package"] = _package(ready=True, index=index)

    result = _audit(samples)

    assert result["features"]["reranker_score"]["classification"] == (
        "NON_DISCRIMINATIVE"
    )
    assert result["features"]["reranker_score"]["higher_is_ready_auc"] == 0.5


def test_feature_audit_rejects_tamper_binding_weight_and_pair_violations() -> None:
    tampered = _samples()
    tampered[0]["feature_package"]["features"]["reranker_score"] = 0.1  # type: ignore[index]
    with pytest.raises(MultiSignalCalibrationError, match="integrity"):
        _audit(tampered)

    binding = _samples()
    binding[0]["feature_package"] = build_multisignal_feature_package(
        [], binding={**_binding(), "ranking_policy_id": "drift"}
    )
    with pytest.raises(ValueError, match="binding does not match"):
        _audit(binding)

    weights = _samples()
    weights[0]["feature_package"]["weights"].pop("channel_support")  # type: ignore[index]
    with pytest.raises(ValueError, match="weights are invalid"):
        _audit(weights)

    replay = _samples()
    replay[1]["sample_id"] = replay[0]["sample_id"]
    with pytest.raises(ValueError, match="unique"):
        _audit(replay)

    mismatched_label = _samples()
    mismatched_label[0]["expected_ready"] = False
    with pytest.raises(ValueError, match="pair semantics"):
        _audit(mismatched_label)

    missing_pair = _samples()[:-1]
    with pytest.raises(ValueError, match="positive and negative"):
        _audit(missing_pair)

    malformed_id = _samples()
    malformed_id[0]["sample_id"] = "malformed"
    with pytest.raises(ValueError, match=r"positive\|negative"):
        _audit(malformed_id)

    missing_package = _samples()
    missing_package[0]["feature_package"] = None
    with pytest.raises(TypeError, match="sample is invalid"):
        _audit(missing_package)


@pytest.mark.parametrize("samples", ["bad", ["bad"], []])
def test_feature_audit_rejects_invalid_collections(samples: object) -> None:
    with pytest.raises((TypeError, ValueError), match="invalid|requires"):
        _audit(samples)


def test_feature_audit_rejects_incomplete_and_mixed_weights() -> None:
    incomplete = _samples()
    incomplete[0]["feature_package"] = build_multisignal_feature_package(
        [], binding=_binding()
    )
    with pytest.raises(ValueError, match="complete"):
        _audit(incomplete)

    mixed = _samples()
    original = mixed[0]["feature_package"]
    changed = reweight_multisignal_feature_package(
        original,
        weights=RetrievalConfidenceWeights(
            reranker_score=0.25,
            reranker_margin=0.15,
            rrf_normalized_score=0.35,
            channel_support=0.25,
        ),
    )
    mixed[0]["feature_package"] = changed
    with pytest.raises(ValueError, match="weights do not match"):
        _audit(mixed)

    with pytest.raises(ValueError, match="dataset_id is invalid"):
        audit_multisignal_feature_discriminativeness(
            _samples(),
            dataset_id="",
            dataset_sha256="a" * 64,
            expected_binding=_binding(),
        )


def test_mixed_package_diagnostics_are_calibration_only_and_select_no_policy() -> None:
    result = diagnose_mixed_candidate_feature_discriminativeness(
        _mixed_samples(),
        dataset_id="calibration-v3",
        dataset_sha256="b" * 64,
        expected_binding=_binding(),
    )

    assert result["status"] == "DIAGNOSED"
    assert result["runtime_activation_permitted"] is False
    assert result["threshold_selection_permitted"] is False
    assert result["weight_selection_permitted"] is False
    assert result["holdout_access_permitted"] is False
    assert result["dataset"] == {
        "dataset_id": "calibration-v3",
        "dataset_sha256": "b" * 64,
        "partition": "CALIBRATION",
        "sample_count": 40,
        "group_count": 20,
    }
    assert result["package_semantics"] == {
        "pair_semantics": "POSITIVE_PAIR_VS_NEGATIVE_PAIR",
        "retrieval_unit": "ONE_FOUR_CANDIDATE_MIXED_RETRIEVAL_PER_PACKAGE",
        "single_mixed_candidate_retrieval": True,
        "label_filtered_retrieval": False,
        "finding_scope": "diagnostic_only",
    }
    reranker = result["features"]["reranker_score"]
    assert reranker["classification"] == "DIRECTIONAL"
    assert reranker["higher_is_ready_auc"] == 1.0
    assert reranker["unique_value_count"] == 40
    assert "univariate_threshold" not in reranker
    assert "selected_threshold" not in str(result)


def test_mixed_package_diagnostics_are_deterministic_and_reject_split_scopes() -> None:
    samples = _mixed_samples()
    first = diagnose_mixed_candidate_feature_discriminativeness(
        samples,
        dataset_id="calibration-v3",
        dataset_sha256="b" * 64,
        expected_binding=_binding(),
    )
    replay = diagnose_mixed_candidate_feature_discriminativeness(
        list(reversed(samples)),
        dataset_id="calibration-v3",
        dataset_sha256="b" * 64,
        expected_binding=_binding(),
    )
    assert first["diagnostic_hash"] == replay["diagnostic_hash"]

    samples[0]["retrieval_scope"]["label_filtered_retrieval"] = True  # type: ignore[index]
    with pytest.raises(ValueError, match="four-candidate retrieval"):
        diagnose_mixed_candidate_feature_discriminativeness(
            samples,
            dataset_id="calibration-v3",
            dataset_sha256="b" * 64,
            expected_binding=_binding(),
        )

    with pytest.raises(TypeError, match="samples are invalid"):
        diagnose_mixed_candidate_feature_discriminativeness(
            "bad",  # type: ignore[arg-type]
            dataset_id="calibration-v3",
            dataset_sha256="b" * 64,
            expected_binding=_binding(),
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda sample: sample.update(retrieval_scope=None),
        lambda sample: sample["retrieval_scope"].update(candidate_count=3),
        lambda sample: sample["retrieval_scope"].update(
            single_mixed_candidate_retrieval=False
        ),
        lambda sample: sample["retrieval_scope"].update(
            label_filtered_retrieval=True
        ),
        lambda sample: sample.update(feature_package=None),
        lambda sample: sample["feature_package"]["features"].update(
            candidate_count=3
        ),
    ],
)
def test_mixed_package_diagnostics_fail_closed_on_incomplete_scope(mutation) -> None:
    samples = _mixed_samples()
    mutation(samples[0])
    with pytest.raises(ValueError, match="four-candidate retrieval"):
        diagnose_mixed_candidate_feature_discriminativeness(
            samples,
            dataset_id="calibration-v3",
            dataset_sha256="b" * 64,
            expected_binding=_binding(),
        )

    with pytest.raises(TypeError, match="sample is invalid"):
        diagnose_mixed_candidate_feature_discriminativeness(
            ["bad"],  # type: ignore[list-item]
            dataset_id="calibration-v3",
            dataset_sha256="b" * 64,
            expected_binding=_binding(),
        )
