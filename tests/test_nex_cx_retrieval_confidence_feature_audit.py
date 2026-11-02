from __future__ import annotations

import pytest
from nex_cx.retrieval_confidence_calibration import RetrievalConfidenceWeights
from nex_cx.retrieval_confidence_feature_audit import (
    audit_multisignal_feature_discriminativeness,
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
