from __future__ import annotations

from copy import deepcopy

import pytest
from nex_cx.retrieval_confidence_calibration import RetrievalConfidenceWeights
from nex_cx.retrieval_confidence_multisignal import (
    MULTISIGNAL_FEATURE_PACKAGE_SCHEMA_VERSION,
    MULTISIGNAL_FEATURE_SCHEMA_VERSION,
    MULTISIGNAL_POLICY_ID,
    MULTISIGNAL_PROFILE_SCHEMA_VERSION,
    MultiSignalCalibrationError,
    build_admitted_multisignal_profile,
    build_multisignal_feature_package,
    decide_multisignal_confidence,
    evaluate_multisignal_calibration,
)
from nex_runtime.model_calibration import evaluate_binary_score_threshold
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

RERANKER_REVISION = "hf:" + "2" * 40


def _binding(**overrides: str) -> dict[str, str]:
    value = {
        "embedding_model_revision": "Qwen3-Embedding-4B",
        "reranker_model_revision": RERANKER_REVISION,
        "ranking_policy_id": "weighted_rrf_vector_bm25_v1",
        "tokenizer_policy_id": "mecab_ko_v1",
        "chunk_policy_id": "chunk_1000_100",
    }
    value.update(overrides)
    return value


def _evidence(
    *,
    first_rerank: float = 0.9,
    second_rerank: float = 0.6,
    first_rrf: float = 0.95,
    second_rrf: float = 0.7,
    first_channel: float = 1.0,
) -> list[dict[str, object]]:
    return [
        {
            "rank": 1,
            "scores": {
                "bm25_score": 4.2,
                "vector_score": 0.82,
                "bm25_rank": 1,
                "vector_rank": 2,
                "rrf_score": 0.0162,
                "rrf_normalized_score": first_rrf,
                "channel_support_score": first_channel,
                "rerank_score": first_rerank,
                "final_score": first_rerank,
            },
        },
        {
            "rank": 2,
            "scores": {
                "bm25_score": None,
                "vector_score": 0.8,
                "bm25_rank": None,
                "vector_rank": 1,
                "rrf_score": 0.0114,
                "rrf_normalized_score": second_rrf,
                "channel_support_score": 0.7,
                "rerank_score": second_rerank,
                "final_score": second_rerank,
            },
        },
    ]


def _package(**kwargs: object) -> dict[str, object]:
    return build_multisignal_feature_package(
        kwargs.pop("evidence_items", _evidence()),  # type: ignore[arg-type]
        binding=kwargs.pop("binding", _binding()),  # type: ignore[arg-type]
        **kwargs,  # type: ignore[arg-type]
    )


def _resign(package: dict[str, object]) -> dict[str, object]:
    package.pop("feature_package_hash", None)
    package["feature_package_hash"] = semantic_sha256_hash_ref(package)
    return package


def test_feature_package_is_versioned_hash_bound_and_permission_neutral() -> None:
    package = _package()

    assert package["feature_package_schema_version"] == (
        MULTISIGNAL_FEATURE_PACKAGE_SCHEMA_VERSION
    )
    assert package["policy_id"] == MULTISIGNAL_POLICY_ID
    assert package["permission_signals_used"] is False
    assert package["ownership_signals_used"] is False
    assert package["feature_package_hash"] == semantic_sha256_hash_ref(
        {key: value for key, value in package.items() if key != "feature_package_hash"}
    )
    features = package["features"]
    assert features == {
        "feature_schema_version": MULTISIGNAL_FEATURE_SCHEMA_VERSION,
        "status": "COMPLETE",
        "reason_codes": [],
        "candidate_count": 2,
        "reranker_score": 0.9,
        "reranker_margin": 0.3,
        "rrf_normalized_score": 0.95,
        "channel_support": 1.0,
        "composite_score": 0.89,
        "diagnostics": {
            "reranker_rrf_order_agreement": 1.0,
            "lexical_channel_candidate_ratio": 0.5,
            "vector_channel_candidate_ratio": 1.0,
            "admitted_candidate_count": 2,
            "diagnostics_used_in_composite": False,
        },
        "weighted_feature_fields": [
            "reranker_score",
            "reranker_margin",
            "rrf_normalized_score",
            "channel_support",
        ],
    }


def test_rank_agreement_is_diagnostic_and_does_not_change_composite() -> None:
    concordant = _package()
    discordant = _package(evidence_items=_evidence(first_rrf=0.95, second_rrf=0.99))

    assert (
        concordant["features"]["composite_score"]
        == (  # type: ignore[index]
            discordant["features"]["composite_score"]  # type: ignore[index]
        )
    )
    assert (
        discordant["features"]["diagnostics"][  # type: ignore[index]
            "reranker_rrf_order_agreement"
        ]
        == 0.0
    )


@pytest.mark.parametrize(
    ("mutator", "reason"),
    [
        (
            lambda items: items[0]["scores"].pop("rerank_score"),
            "RERANKER_SCORE_MISSING",
        ),
        (
            lambda items: items[0]["scores"].pop("rrf_normalized_score"),
            "RRF_NORMALIZED_SCORE_MISSING",
        ),
        (
            lambda items: items[0]["scores"].pop("channel_support_score"),
            "CHANNEL_SUPPORT_SCORE_MISSING",
        ),
        (
            lambda items: items[0]["scores"].update(
                {"bm25_rank": None, "vector_rank": None}
            ),
            "RETRIEVAL_CHANNEL_RANK_MISSING",
        ),
    ],
)
def test_missing_signals_are_explicit_and_fail_closed(
    mutator: object,
    reason: str,
) -> None:
    evidence = _evidence()
    mutator(evidence)  # type: ignore[operator]
    package = _package(evidence_items=evidence)

    assert package["features"]["status"] == "INCOMPLETE"  # type: ignore[index]
    assert reason in package["features"]["reason_codes"]  # type: ignore[index]
    decision = decide_multisignal_confidence(
        package,
        expected_binding=_binding(),
        threshold=0.7,
    )
    assert decision["status"] == "LOW_CONFIDENCE"
    assert (
        decision["reason_code"]
        in package["features"][  # type: ignore[index]
            "reason_codes"
        ]
    )


def test_empty_and_single_candidate_packages_have_distinct_semantics() -> None:
    empty = _package(evidence_items=[])
    single = _package(evidence_items=_evidence()[:1])

    no_answer = decide_multisignal_confidence(
        empty,
        expected_binding=_binding(),
        threshold=0.7,
    )
    low = decide_multisignal_confidence(
        single,
        expected_binding=_binding(),
        threshold=0.7,
    )
    assert no_answer["status"] == "NO_ANSWER"
    assert no_answer["reason_code"] == "NO_ADMITTED_CANDIDATES"
    assert low["status"] == "LOW_CONFIDENCE"
    assert low["reason_code"] == "RERANKER_MARGIN_UNAVAILABLE"


def test_decision_is_deterministic_inclusive_and_binding_strict() -> None:
    package = _package()

    first = decide_multisignal_confidence(
        package,
        expected_binding=_binding(),
        threshold=0.89,
    )
    replay = decide_multisignal_confidence(
        package,
        expected_binding=_binding(),
        threshold=0.89,
    )
    low = decide_multisignal_confidence(
        package,
        expected_binding=_binding(),
        threshold=0.9,
    )
    mismatch = decide_multisignal_confidence(
        package,
        expected_binding=_binding(reranker_model_revision="hf:" + "3" * 40),
        threshold=0.7,
    )

    assert first == replay
    assert first["status"] == "READY"
    assert first["reason_code"] == "COMPOSITE_SCORE_AT_OR_ABOVE_THRESHOLD"
    assert low["reason_code"] == "COMPOSITE_SCORE_BELOW_THRESHOLD"
    assert mismatch["reason_code"] == "MODEL_OR_POLICY_BINDING_MISMATCH"


@pytest.mark.parametrize(
    "field",
    [
        "tenant_id",
        "owner_subject_id",
        "permission_score",
        "authorization_weight",
        "actor_role",
        "acl_rank",
    ],
)
def test_permission_and_ownership_features_are_rejected(field: str) -> None:
    evidence = _evidence()
    evidence[0][field] = "adversarial"

    with pytest.raises(
        MultiSignalCalibrationError,
        match="cannot become relevance features",
    ) as exc_info:
        _package(evidence_items=evidence)
    assert exc_info.value.error_code.endswith("forbidden_relevance_signal")


@pytest.mark.parametrize(
    ("evidence", "message"),
    [
        ("bad", "evidence_items"),
        (["bad"], "evidence_item"),
        ([{"rank": 1, "scores": {}, "extra": True}], "fields"),
        ([{"rank": True, "scores": {}}], "rank"),
        (
            [
                {"rank": 1, "scores": {}},
                {"rank": 1, "scores": {}},
            ],
            "rank",
        ),
        ([{"rank": 1, "scores": "bad"}], "scores"),
        ([{"rank": 1, "scores": {"unknown_score": 0.5}}], "fields"),
        (
            [
                {
                    "rank": 1,
                    "scores": {
                        "rerank_score": float("nan"),
                        "rrf_normalized_score": 0.5,
                        "channel_support_score": 0.5,
                    },
                }
            ],
            "rerank_score",
        ),
    ],
)
def test_malformed_feature_inputs_are_rejected(
    evidence: object,
    message: str,
) -> None:
    with pytest.raises(MultiSignalCalibrationError, match=message):
        _package(evidence_items=evidence)


def test_rank_gaps_and_reranker_reordering_are_rejected() -> None:
    gap = _evidence()
    gap[1]["rank"] = 3
    reordered = _evidence(first_rerank=0.6, second_rerank=0.9)

    with pytest.raises(MultiSignalCalibrationError, match="contiguous"):
        _package(evidence_items=gap)
    with pytest.raises(MultiSignalCalibrationError, match="descending"):
        _package(evidence_items=reordered)


def test_mutable_reranker_revision_and_incomplete_binding_are_rejected() -> None:
    with pytest.raises(MultiSignalCalibrationError, match="immutable"):
        _package(binding=_binding(reranker_model_revision="Qwen3-Reranker-4B"))
    incomplete = _binding()
    incomplete.pop("chunk_policy_id")
    with pytest.raises(MultiSignalCalibrationError, match="binding"):
        _package(binding=incomplete)


def test_package_integrity_and_contract_tampering_are_rejected() -> None:
    package = _package()
    package["features"]["composite_score"] = 0.99  # type: ignore[index]
    with pytest.raises(MultiSignalCalibrationError, match="integrity"):
        decide_multisignal_confidence(
            package,
            expected_binding=_binding(),
            threshold=0.7,
        )

    contract = _package()
    contract["permission_signals_used"] = True
    _resign(contract)
    with pytest.raises(MultiSignalCalibrationError, match="contract"):
        decide_multisignal_confidence(
            contract,
            expected_binding=_binding(),
            threshold=0.7,
        )

    composite = _package()
    composite["features"]["composite_score"] = 0.99  # type: ignore[index]
    _resign(composite)
    with pytest.raises(MultiSignalCalibrationError, match="bound feature weights"):
        decide_multisignal_confidence(
            composite,
            expected_binding=_binding(),
            threshold=0.7,
        )


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda package: package["features"].update({"extra": 1}), "fields"),
        (
            lambda package: package["features"].update(
                {"feature_schema_version": "wrong"}
            ),
            "feature_schema_version",
        ),
        (lambda package: package["features"].update({"status": "wrong"}), "status"),
        (
            lambda package: package["features"].update({"candidate_count": True}),
            "candidate_count",
        ),
        (
            lambda package: package["features"].update(
                {"reason_codes": ["unexpected"]}
            ),
            "complete",
        ),
        (
            lambda package: package["features"].update({"weighted_feature_fields": []}),
            "weighted_feature_fields",
        ),
        (lambda package: package["weights"].pop("channel_support"), "weights"),
        (
            lambda package: package["features"].update({"owner_score": 1.0}),
            "cannot become relevance features",
        ),
    ],
)
def test_resigned_malformed_packages_still_fail_contract_validation(
    mutator: object,
    message: str,
) -> None:
    package = _package()
    mutator(package)  # type: ignore[operator]
    _resign(package)

    with pytest.raises(MultiSignalCalibrationError, match=message):
        decide_multisignal_confidence(
            package,
            expected_binding=_binding(),
            threshold=0.7,
        )


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda features: features.update({"reason_codes": []}), "reason_codes"),
        (
            lambda features: features.update({"reason_codes": [""]}),
            "reason_codes",
        ),
        (
            lambda features: features.update({"composite_score": 0.1}),
            "composite_score",
        ),
    ],
)
def test_resigned_incomplete_package_requires_valid_missing_semantics(
    mutator: object,
    message: str,
) -> None:
    package = _package(evidence_items=[])
    mutator(package["features"])  # type: ignore[operator]
    _resign(package)

    with pytest.raises(MultiSignalCalibrationError, match=message):
        decide_multisignal_confidence(
            package,
            expected_binding=_binding(),
            threshold=0.7,
        )


def test_non_mapping_package_and_non_string_feature_key_are_rejected() -> None:
    with pytest.raises(MultiSignalCalibrationError, match="feature_package"):
        decide_multisignal_confidence(
            "bad",  # type: ignore[arg-type]
            expected_binding=_binding(),
            threshold=0.7,
        )
    evidence = _evidence()
    evidence[0]["scores"][1] = 0.5  # type: ignore[index]
    with pytest.raises(MultiSignalCalibrationError, match="feature_key"):
        _package(evidence_items=evidence)


def _calibration_samples() -> list[dict[str, object]]:
    samples: list[dict[str, object]] = []
    for index in range(10):
        samples.append(
            {
                "sample_id": f"ready-{index:02d}",
                "expected_ready": True,
                "feature_package": _package(
                    evidence_items=_evidence(
                        first_rerank=0.88 + index * 0.005,
                        second_rerank=0.58,
                        first_rrf=0.9,
                        first_channel=1.0,
                    )
                ),
            }
        )
        samples.append(
            {
                "sample_id": f"low-{index:02d}",
                "expected_ready": False,
                "feature_package": _package(
                    evidence_items=_evidence(
                        first_rerank=0.45 + index * 0.005,
                        second_rerank=0.42,
                        first_rrf=0.48,
                        first_channel=0.7,
                    )
                ),
            }
        )
    return samples


def test_calibration_evaluator_selects_threshold_without_runtime_activation() -> None:
    result = evaluate_multisignal_calibration(
        _calibration_samples(),
        dataset_id="gb2-reranker-calibration-v2:calibration",
        dataset_sha256="a" * 64,
        expected_binding=_binding(),
    )
    replay = evaluate_multisignal_calibration(
        list(reversed(_calibration_samples())),
        dataset_id="gb2-reranker-calibration-v2:calibration",
        dataset_sha256="a" * 64,
        expected_binding=_binding(),
    )

    assert result["status"] == "PASSED"
    assert result["reason_code"] == "CALIBRATED_THRESHOLD_SELECTED"
    assert result["runtime_activation_permitted"] is False
    assert result["evaluation"]["selected_metrics"]["false_ready_rate"] == 0.0
    assert result["evaluation"]["selected_metrics"]["ready_recall"] == 1.0
    assert result["evaluation_hash"] == replay["evaluation_hash"]


def _admitted_profile_inputs() -> tuple[dict[str, object], dict[str, object]]:
    calibration = evaluate_multisignal_calibration(
        _calibration_samples(),
        dataset_id="gb2-reranker-calibration-v2",
        dataset_sha256="a" * 64,
        expected_binding=_binding(),
    )
    threshold = calibration["evaluation"]["selected_threshold"]  # type: ignore[index]
    threshold_samples = [
        {
            "sample_id": sample["sample_id"],
            "expected_ready": sample["expected_ready"],
            "score": sample["feature_package"]["features"][  # type: ignore[index]
                "composite_score"
            ],
        }
        for sample in _calibration_samples()
    ]
    holdout = evaluate_binary_score_threshold(
        threshold_samples,
        dataset_id="gb2-reranker-calibration-v2:holdout",
        threshold=threshold,
    )
    return calibration, holdout


def test_admitted_profile_requires_passed_calibration_and_untouched_holdout() -> None:
    calibration, holdout = _admitted_profile_inputs()

    profile = build_admitted_multisignal_profile(
        profile_id="gb2-s20q-live-v2",
        version="0001",
        expected_binding=_binding(),
        dataset_id="gb2-reranker-calibration-v2",
        dataset_sha256="a" * 64,
        calibration_result=calibration,
        holdout_evaluation=holdout,
    )

    assert profile["profile_schema_version"] == MULTISIGNAL_PROFILE_SCHEMA_VERSION
    assert profile["status"] == "ACTIVE"
    assert profile["runtime_activation_permitted"] is True
    assert (
        profile["threshold"]
        == calibration["evaluation"][  # type: ignore[index]
            "selected_threshold"
        ]
    )
    assert profile["profile_hash"] == semantic_sha256_hash_ref(
        {key: value for key, value in profile.items() if key != "profile_hash"}
    )


def test_admitted_profile_rejects_calibration_holdout_and_integrity_drift() -> None:
    calibration, holdout = _admitted_profile_inputs()
    rejected = deepcopy(calibration)
    rejected["status"] = "NO_ACCEPTABLE_THRESHOLD"
    with pytest.raises(MultiSignalCalibrationError, match="passed, frozen"):
        build_admitted_multisignal_profile(
            profile_id="profile",
            version="1",
            expected_binding=_binding(),
            dataset_id="gb2-reranker-calibration-v2",
            dataset_sha256="a" * 64,
            calibration_result=rejected,
            holdout_evaluation=holdout,
        )

    tampered = deepcopy(calibration)
    tampered["evaluation_hash"] = "sha256:" + "0" * 64
    with pytest.raises(MultiSignalCalibrationError, match="integrity"):
        build_admitted_multisignal_profile(
            profile_id="profile",
            version="1",
            expected_binding=_binding(),
            dataset_id="gb2-reranker-calibration-v2",
            dataset_sha256="a" * 64,
            calibration_result=tampered,
            holdout_evaluation=holdout,
        )

    failed_holdout = deepcopy(holdout)
    failed_holdout["status"] = "REJECTED"
    with pytest.raises(MultiSignalCalibrationError, match="holdout"):
        build_admitted_multisignal_profile(
            profile_id="profile",
            version="1",
            expected_binding=_binding(),
            dataset_id="gb2-reranker-calibration-v2",
            dataset_sha256="a" * 64,
            calibration_result=calibration,
            holdout_evaluation=failed_holdout,
        )


@pytest.mark.parametrize(
    "field",
    ["evaluation_schema_version", "status", "dataset_id", "threshold"],
)
def test_admitted_profile_rejects_each_holdout_binding_drift(field: str) -> None:
    calibration, holdout = _admitted_profile_inputs()
    holdout[field] = {
        "evaluation_schema_version": "wrong",
        "status": "REJECTED",
        "dataset_id": "wrong:holdout",
        "threshold": 0.0,
    }[field]

    with pytest.raises(MultiSignalCalibrationError, match="holdout"):
        build_admitted_multisignal_profile(
            profile_id="profile",
            version="1",
            expected_binding=_binding(),
            dataset_id="gb2-reranker-calibration-v2",
            dataset_sha256="a" * 64,
            calibration_result=calibration,
            holdout_evaluation=holdout,
        )


def test_calibration_rejects_replay_incomplete_binding_and_mixed_weights() -> None:
    replay = _calibration_samples()
    replay[1]["sample_id"] = replay[0]["sample_id"]
    with pytest.raises(MultiSignalCalibrationError, match="replayed"):
        evaluate_multisignal_calibration(
            replay,
            dataset_id="dataset",
            dataset_sha256="a" * 64,
            expected_binding=_binding(),
        )

    incomplete = _calibration_samples()
    incomplete[0]["feature_package"] = _package(evidence_items=_evidence()[:1])
    with pytest.raises(MultiSignalCalibrationError, match="complete"):
        evaluate_multisignal_calibration(
            incomplete,
            dataset_id="dataset",
            dataset_sha256="a" * 64,
            expected_binding=_binding(),
        )

    drifted = _calibration_samples()
    drifted[0]["feature_package"] = _package(
        binding=_binding(ranking_policy_id="other-policy")
    )
    with pytest.raises(MultiSignalCalibrationError, match="does not match"):
        evaluate_multisignal_calibration(
            drifted,
            dataset_id="dataset",
            dataset_sha256="a" * 64,
            expected_binding=_binding(),
        )

    mixed = _calibration_samples()
    mixed[0]["feature_package"] = _package(
        weights=RetrievalConfidenceWeights(
            reranker_score=0.25,
            reranker_margin=0.15,
            rrf_normalized_score=0.35,
            channel_support=0.25,
        )
    )
    with pytest.raises(MultiSignalCalibrationError, match="same feature weights"):
        evaluate_multisignal_calibration(
            mixed,
            dataset_id="dataset",
            dataset_sha256="a" * 64,
            expected_binding=_binding(),
        )


def test_calibration_reports_insufficient_and_no_threshold_outcomes() -> None:
    insufficient = evaluate_multisignal_calibration(
        _calibration_samples()[:2],
        dataset_id="dataset",
        dataset_sha256="a" * 64,
        expected_binding=_binding(),
    )
    inseparable = _calibration_samples()
    common = _package(
        evidence_items=_evidence(
            first_rerank=0.5,
            second_rerank=0.4,
            first_rrf=0.5,
            first_channel=0.7,
        )
    )
    for sample in inseparable:
        sample["feature_package"] = deepcopy(common)
    no_threshold = evaluate_multisignal_calibration(
        inseparable,
        dataset_id="dataset",
        dataset_sha256="b" * 64,
        expected_binding=_binding(),
    )

    assert insufficient["reason_code"] == "INSUFFICIENT_CALIBRATION_SAMPLES"
    assert no_threshold["reason_code"] == "NO_ACCEPTABLE_THRESHOLD"


@pytest.mark.parametrize("threshold", [-0.1, True, float("inf")])
def test_decision_rejects_invalid_threshold(threshold: object) -> None:
    with pytest.raises(MultiSignalCalibrationError, match="threshold"):
        decide_multisignal_confidence(
            _package(),
            expected_binding=_binding(),
            threshold=threshold,
        )


def test_calibration_rejects_invalid_dataset_digest_and_sample_shape() -> None:
    with pytest.raises(MultiSignalCalibrationError, match="dataset_sha256"):
        evaluate_multisignal_calibration(
            _calibration_samples(),
            dataset_id="dataset",
            dataset_sha256="bad",
            expected_binding=_binding(),
        )
    with pytest.raises(MultiSignalCalibrationError, match="samples"):
        evaluate_multisignal_calibration(
            "bad",  # type: ignore[arg-type]
            dataset_id="dataset",
            dataset_sha256="a" * 64,
            expected_binding=_binding(),
        )


def test_calibration_rejects_non_mapping_invalid_label_and_blank_identifiers() -> None:
    base = _calibration_samples()
    with pytest.raises(MultiSignalCalibrationError, match="sample"):
        evaluate_multisignal_calibration(
            ["bad"],  # type: ignore[list-item]
            dataset_id="dataset",
            dataset_sha256="a" * 64,
            expected_binding=_binding(),
        )
    invalid_label = deepcopy(base)
    invalid_label[0]["expected_ready"] = "yes"
    with pytest.raises(MultiSignalCalibrationError, match="expected_ready"):
        evaluate_multisignal_calibration(
            invalid_label,
            dataset_id="dataset",
            dataset_sha256="a" * 64,
            expected_binding=_binding(),
        )
    with pytest.raises(MultiSignalCalibrationError, match="dataset_id"):
        evaluate_multisignal_calibration(
            base,
            dataset_id=" ",
            dataset_sha256="a" * 64,
            expected_binding=_binding(),
        )


def test_empty_calibration_set_is_reported_as_insufficient() -> None:
    result = evaluate_multisignal_calibration(
        [],
        dataset_id="dataset",
        dataset_sha256="a" * 64,
        expected_binding=_binding(),
    )
    assert result["status"] == "INSUFFICIENT_SAMPLES"
    assert result["weights"] is None
