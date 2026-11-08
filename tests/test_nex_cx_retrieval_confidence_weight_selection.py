from __future__ import annotations

from copy import deepcopy

import pytest
from nex_cx.retrieval_confidence_calibration import RetrievalConfidenceWeights
from nex_cx.retrieval_confidence_multisignal import (
    MultiSignalCalibrationError,
    build_multisignal_feature_package,
    reweight_multisignal_feature_package,
)
from nex_cx.retrieval_confidence_weight_selection import (
    MultiSignalWeightSelectionConstraints,
    _aggregate_fold_metrics,
    _fold_groups,
    _group_id,
    _number_or_default,
    _weight_grid,
    apply_multisignal_weights,
    select_multisignal_calibration_weights,
)
from nex_runtime.model_calibration import BinaryCalibrationConstraints

RERANKER_REVISION = "hf:" + "2" * 40
DATASET_DIGEST = "a" * 64


def _binding() -> dict[str, str]:
    return {
        "embedding_model_revision": "Qwen3-Embedding-4B",
        "reranker_model_revision": RERANKER_REVISION,
        "ranking_policy_id": "weighted_rrf_vector_bm25_v1",
        "tokenizer_policy_id": "cx-tokenizer-profile:sha256:" + "b" * 64,
        "chunk_policy_id": "chunk_1000_100",
    }


def _package(*, ready: bool, index: int = 0) -> dict[str, object]:
    if ready:
        top = 0.86 + (index % 3) * 0.01
        second = 0.46
        rrf = 0.40
        channel = 0.50
    else:
        top = 0.44 + (index % 3) * 0.01
        second = 0.40
        rrf = 1.00
        channel = 1.00
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
                    "rerank_score": second,
                },
            },
        ],
        binding=_binding(),
    )


def _samples(*, indistinguishable: bool = False) -> list[dict[str, object]]:
    samples: list[dict[str, object]] = []
    for index in range(20):
        positive = _package(ready=True, index=index)
        negative = (
            deepcopy(positive)
            if indistinguishable
            else _package(ready=False, index=index)
        )
        samples.extend(
            [
                {
                    "sample_id": f"group-{index:02d}:positive",
                    "expected_ready": True,
                    "feature_package": positive,
                },
                {
                    "sample_id": f"group-{index:02d}:negative",
                    "expected_ready": False,
                    "feature_package": negative,
                },
            ]
        )
    return samples


def _constraints() -> MultiSignalWeightSelectionConstraints:
    return MultiSignalWeightSelectionConstraints(
        grid_step=0.10,
        minimum_feature_weight=0.10,
        maximum_feature_weight=0.70,
    )


def test_group_cv_selects_deterministic_profile_without_holdout_data() -> None:
    first = select_multisignal_calibration_weights(
        _samples(),
        dataset_id="calibration-only-v2",
        dataset_sha256=DATASET_DIGEST,
        expected_binding=_binding(),
        constraints=_constraints(),
    )
    replay = select_multisignal_calibration_weights(
        list(reversed(_samples())),
        dataset_id="calibration-only-v2",
        dataset_sha256=DATASET_DIGEST,
        expected_binding=_binding(),
        constraints=_constraints(),
    )

    assert first["status"] == "SELECTED"
    assert first["runtime_activation_permitted"] is False
    assert first["dataset"]["partition"] == "CALIBRATION"
    assert first["dataset"]["sample_count"] == 40
    assert first["dataset"]["group_count"] == 20
    assert first["selected"]["oof_metrics"]["false_ready_rate"] <= 0.10
    assert first["selected"]["oof_metrics"]["ready_recall"] >= 0.80
    assert first["selected"]["calibration"]["status"] == "PASSED"
    assert all(
        fold["training_group_count"] == 16
        and fold["validation_group_count"] == 4
        and fold["threshold_source"]
        in {"SELECTED_THRESHOLD", "TRAIN_BEST_EFFORT_THRESHOLD"}
        for fold in first["selected"]["folds"]
    )
    assert first["selection_hash"] == replay["selection_hash"]


def test_group_cv_rejects_indistinguishable_labels_and_keeps_runtime_closed() -> None:
    result = select_multisignal_calibration_weights(
        _samples(indistinguishable=True),
        dataset_id="calibration-only-v2",
        dataset_sha256=DATASET_DIGEST,
        expected_binding=_binding(),
        constraints=_constraints(),
    )

    assert result["status"] == "NO_ACCEPTABLE_WEIGHT_PROFILE"
    assert result["selected"] is None
    assert result["runtime_activation_permitted"] is False
    assert result["best_effort"]["status"] == "REJECTED"


def test_group_cv_rejects_when_fold_training_threshold_is_unavailable() -> None:
    result = select_multisignal_calibration_weights(
        _samples()[:20],
        dataset_id="calibration-only-v2",
        dataset_sha256=DATASET_DIGEST,
        expected_binding=_binding(),
        constraints=_constraints(),
    )

    assert result["status"] == "NO_ACCEPTABLE_WEIGHT_PROFILE"
    assert result["best_effort"]["reason_code"] == (
        "FOLD_TRAINING_THRESHOLD_UNAVAILABLE"
    )


def test_reweighting_rebuilds_integrity_bound_composite_without_mutation() -> None:
    original = _package(ready=True)
    original_hash = original["feature_package_hash"]
    selected = RetrievalConfidenceWeights(
        reranker_score=0.60,
        reranker_margin=0.20,
        rrf_normalized_score=0.10,
        channel_support=0.10,
    )

    rebuilt = reweight_multisignal_feature_package(original, weights=selected)

    assert original["feature_package_hash"] == original_hash
    assert rebuilt["feature_package_hash"] != original_hash
    assert rebuilt["weights"] == selected.to_wire()
    assert (
        rebuilt["features"]["composite_score"]
        != original["features"][  # type: ignore[index]
            "composite_score"
        ]
    )

    replay = reweight_multisignal_feature_package(rebuilt, weights=selected)
    assert replay == rebuilt

    incomplete = build_multisignal_feature_package([], binding=_binding())
    incomplete_rebuilt = reweight_multisignal_feature_package(
        incomplete, weights=selected
    )
    assert incomplete_rebuilt["features"]["composite_score"] is None  # type: ignore[index]

    tampered = deepcopy(original)
    tampered["features"]["reranker_score"] = 0.1  # type: ignore[index]
    with pytest.raises(MultiSignalCalibrationError, match="integrity"):
        reweight_multisignal_feature_package(tampered, weights=selected)


def test_apply_selected_weights_preserves_only_calibration_identity_and_label() -> None:
    samples = _samples()[:2]
    samples[0]["ignored"] = "not propagated"
    weights = {
        "reranker_score": 0.60,
        "reranker_margin": 0.20,
        "rrf_normalized_score": 0.10,
        "channel_support": 0.10,
    }

    rebuilt = apply_multisignal_weights(samples, weights=weights)

    assert set(rebuilt[0]) == {
        "sample_id",
        "expected_ready",
        "feature_package",
    }
    assert rebuilt[0]["feature_package"]["weights"] == weights  # type: ignore[index]
    assert samples[0]["feature_package"]["weights"] != weights  # type: ignore[index]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"fold_count": 1},
        {"grid_step": 0.3},
        {"minimum_feature_weight": 0.8, "maximum_feature_weight": 0.7},
        {"minimum_reranker_weight": 1.1},
        {"minimum_retrieval_weight": -0.1},
        {"maximum_threshold_spread": 1.1},
        {"minimum_fold_balanced_accuracy": -0.1},
    ],
)
def test_selection_constraints_reject_invalid_profiles(kwargs: dict) -> None:
    with pytest.raises(ValueError, match="invalid|divide"):
        MultiSignalWeightSelectionConstraints(**kwargs)


def test_group_contract_rejects_replay_missing_pair_and_small_sets() -> None:
    duplicate = _samples()
    duplicate[1]["sample_id"] = duplicate[0]["sample_id"]
    with pytest.raises(ValueError, match="unique"):
        select_multisignal_calibration_weights(
            duplicate,
            dataset_id="dataset",
            dataset_sha256=DATASET_DIGEST,
            expected_binding=_binding(),
            constraints=_constraints(),
        )

    missing_label = [
        sample
        for sample in _samples()
        if not str(sample["sample_id"]).endswith("negative")
    ]
    with pytest.raises(ValueError, match="positive and negative"):
        select_multisignal_calibration_weights(
            missing_label,
            dataset_id="dataset",
            dataset_sha256=DATASET_DIGEST,
            expected_binding=_binding(),
            constraints=_constraints(),
        )

    too_small = _samples()[:8]
    with pytest.raises(ValueError, match="sample count"):
        select_multisignal_calibration_weights(
            too_small,
            dataset_id="dataset",
            dataset_sha256=DATASET_DIGEST,
            expected_binding=_binding(),
            constraints=_constraints(),
        )

    four_groups = _samples()[:8]
    with pytest.raises(ValueError, match="group count"):
        select_multisignal_calibration_weights(
            four_groups,
            dataset_id="dataset",
            dataset_sha256=DATASET_DIGEST,
            expected_binding=_binding(),
            constraints=MultiSignalWeightSelectionConstraints(
                fold_count=5,
                grid_step=0.10,
                minimum_feature_weight=0.10,
                maximum_feature_weight=0.70,
                calibration=BinaryCalibrationConstraints(
                    minimum_sample_count=8,
                    minimum_positive_count=4,
                    minimum_negative_count=4,
                ),
            ),
        )


def test_apply_and_group_helpers_fail_closed_for_malformed_input() -> None:
    with pytest.raises(ValueError, match="profile"):
        apply_multisignal_weights(_samples()[:2], weights={"bad": 1.0})
    with pytest.raises(TypeError, match="sample"):
        apply_multisignal_weights(["bad"], weights=_package_weights())  # type: ignore[list-item]
    malformed = deepcopy(_samples()[:2])
    malformed[0]["expected_ready"] = "yes"
    with pytest.raises(TypeError, match="sample"):
        apply_multisignal_weights(malformed, weights=_package_weights())
    with pytest.raises(TypeError, match="samples"):
        select_multisignal_calibration_weights(  # type: ignore[arg-type]
            "bad",
            dataset_id="dataset",
            dataset_sha256=DATASET_DIGEST,
            expected_binding=_binding(),
            constraints=_constraints(),
        )
    with pytest.raises(TypeError, match="sample"):
        select_multisignal_calibration_weights(  # type: ignore[list-item]
            ["bad"],
            dataset_id="dataset",
            dataset_sha256=DATASET_DIGEST,
            expected_binding=_binding(),
            constraints=_constraints(),
        )
    invalid_fields = deepcopy(_samples())
    invalid_fields[0]["expected_ready"] = "yes"
    with pytest.raises(TypeError, match="sample"):
        select_multisignal_calibration_weights(
            invalid_fields,
            dataset_id="dataset",
            dataset_sha256=DATASET_DIGEST,
            expected_binding=_binding(),
            constraints=_constraints(),
        )
    with pytest.raises(ValueError, match="sample_id"):
        select_multisignal_calibration_weights(
            [
                {
                    "sample_id": "",
                    "expected_ready": True,
                    "feature_package": _package(ready=True),
                }
            ],
            dataset_id="dataset",
            dataset_sha256=DATASET_DIGEST,
            expected_binding=_binding(),
            constraints=_constraints(),
        )
    with pytest.raises(ValueError, match="sample_id"):
        _group_id("missing-label")

    folds = _fold_groups(["a", "b", "c", "d", "e"], dataset_id="dataset", fold_count=5)
    assert sorted(group for fold in folds for group in fold) == [
        "a",
        "b",
        "c",
        "d",
        "e",
    ]
    with pytest.raises(ValueError, match="at least one"):
        _fold_groups(["a"], dataset_id="dataset", fold_count=2)


def test_grid_aggregate_and_numeric_helpers() -> None:
    grid = _weight_grid(_constraints())
    assert grid
    assert all(
        sum(profile.to_wire().values()) == pytest.approx(1.0) for profile in grid
    )
    assert all(
        min(profile.to_wire().values()) >= 0.10
        and max(profile.to_wire().values()) <= 0.70
        for profile in grid
    )
    aggregate = _aggregate_fold_metrics(
        [
            {
                "metrics": {
                    "true_ready": 4,
                    "false_low_confidence": 0,
                    "false_ready": 0,
                    "true_low_confidence": 4,
                }
            },
            {
                "metrics": {
                    "true_ready": 3,
                    "false_low_confidence": 1,
                    "false_ready": 1,
                    "true_low_confidence": 3,
                }
            },
        ]
    )
    assert aggregate["ready_recall"] == 0.875
    assert aggregate["false_ready_rate"] == 0.125
    assert _number_or_default(0.0, 1.0) == 0.0
    assert _number_or_default(None, 1.0) == 1.0

    retrieval_heavy = _weight_grid(
        MultiSignalWeightSelectionConstraints(
            grid_step=0.10,
            minimum_feature_weight=0.10,
            maximum_feature_weight=0.70,
            minimum_reranker_weight=0.0,
            minimum_retrieval_weight=0.80,
        )
    )
    assert retrieval_heavy
    assert all(
        profile.rrf_normalized_score + profile.channel_support + 1e-9 >= 0.80
        for profile in retrieval_heavy
    )


def _package_weights() -> dict[str, float]:
    return {
        "reranker_score": 0.20,
        "reranker_margin": 0.10,
        "rrf_normalized_score": 0.40,
        "channel_support": 0.30,
    }
