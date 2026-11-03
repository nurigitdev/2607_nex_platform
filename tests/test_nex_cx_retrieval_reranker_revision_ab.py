from __future__ import annotations

from copy import deepcopy

import pytest
from nex_cx.retrieval_reranker_revision_ab import (
    RerankerRevisionABError,
    build_reranker_revision_profile,
    compare_reranker_revision_profiles,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

REVISION_A = "hf:" + "a" * 40
REVISION_B = "hf:" + "b" * 40
SHA_A = "sha256:" + "1" * 64
SHA_B = "sha256:" + "2" * 64
SHA_C = "sha256:" + "3" * 64


def _metrics(*, false_ready: float = 0.1, recall: float = 0.8) -> dict:
    return {
        "feature_fields": ["reranker_score", "channel_rank_quality"],
        "weights": {"reranker_score": 0.7, "channel_rank_quality": 0.3},
        "candidate_auc": 0.84,
        "oof_metrics": {
            "false_ready_rate": false_ready,
            "ready_recall": recall,
            "balanced_accuracy": 0.85,
        },
        "minimum_fold_balanced_accuracy": 0.75,
        "threshold_spread": 0.03,
    }


def _repeatability(model: str = "model-a") -> dict:
    return {
        "status": "PASS",
        "checks": {"complete": True},
        "candidate_profile": {
            "status": "CANDIDATE",
            "profile_id": f"repeatability-{model}",
            "binding": {
                "model_name": model,
                "deployment_id": f"deployment-{model}",
                "request_shape": "rerank",
                "score_semantics": "provider_native_relevance_0_1",
            },
            "measurement": {"repeat_count": 5, "observation_count": 600},
            "policy": {"score_delta_tolerance": 0.0005},
        },
    }


def _revision(revision: str = REVISION_A, model: str = "model-a") -> dict:
    return {
        "status": "PASS",
        "checks": {"complete": True},
        "binding": {
            "served_model_name": model,
            "artifact_revision": revision,
            "deployment_id": f"deployment-{model}",
        },
    }


def _source(
    revision: str = REVISION_A,
    model: str = "model-a",
    *,
    status: str = "NO_ACCEPTABLE_POLICY",
    metrics: dict | None = None,
) -> dict:
    decision_metrics = metrics or _metrics(false_ready=0.15, recall=0.65)
    selected = decision_metrics if status == "FROZEN" else None
    return {
        "status": "PASS",
        "checks": {"complete": True},
        "dataset": {
            "dataset_id": "dataset-v3",
            "dataset_sha256": "dataset-sha",
            "partition": "CALIBRATION",
            "holdout_status": "SEALED_NOT_COLLECTED",
            "scenario_count": 20,
            "package_count": 40,
            "candidate_count": 160,
        },
        "binding": {
            "embedding_model_revision": "embedding-a",
            "reranker_model_revision": revision,
            "ranking_policy_id": "ranking-v1",
            "tokenizer_policy_id": "tokenizer-v1",
            "chunk_policy_id": "chunk-v1",
        },
        "signal_contract": {
            "contract_hash": "sha256:" + "4" * 64,
            "truth_or_permission_signal_included": False,
        },
        "provenance": {
            "artifact_revision": revision,
            "served_model_name": model,
            "repeatability_evidence_sha256": SHA_B,
            "revision_evidence_sha256": SHA_C,
        },
        "pipeline_repeatability": {
            "status": "STABLE",
            "policy_id": "pipeline-repeatability-v1",
            "repeatability_hash": "sha256:" + "5" * 64,
            "measurement": {"repeat_count": 5},
        },
        "candidate_relevance_calibration": {
            "policy_id": "candidate-relevance-v1",
            "status": status,
            "runtime_activation_permitted": False,
            "holdout_access_permitted": False,
            "holdout": {"status": "SEALED_NOT_OPENED"},
            "search": {
                "signal_fields": [
                    "reranker_score",
                    "rrf_normalized_score",
                    "channel_rank_quality",
                    "bm25_score_quality",
                    "vector_similarity_quality",
                ],
                "admissible_profile_count": 1 if status == "FROZEN" else 0,
                "signal_diagnostics": {"reranker_score": {"candidate_auc": 0.84}},
            },
            "cross_validation": {
                "fold_count": 5,
                "constraints": {
                    "maximum_false_ready_rate": 0.1,
                    "minimum_ready_recall": 0.8,
                },
            },
            "selected": selected,
            "best_effort": decision_metrics,
        },
    }


def _profile(
    slot: str,
    *,
    revision: str,
    model: str,
    status: str = "NO_ACCEPTABLE_POLICY",
    metrics: dict | None = None,
) -> dict:
    return build_reranker_revision_profile(
        _source(revision, model, status=status, metrics=metrics),
        repeatability=_repeatability(model),
        revision=_revision(revision, model),
        slot=slot,
        source_evidence_sha256=SHA_A,
        repeatability_evidence_sha256=SHA_B,
        revision_evidence_sha256=SHA_C,
    )


def test_profile_projection_is_bounded_and_integrity_bound() -> None:
    profile = _profile("A", revision=REVISION_A, model="model-a")

    assert profile["status"] == "ADMITTED"
    assert profile["reranker_binding"]["artifact_revision"] == REVISION_A
    assert profile["calibration"]["status"] == "NO_ACCEPTABLE_POLICY"
    assert profile["holdout_access_permitted"] is False
    assert profile["runtime_activation_permitted"] is False
    assert "candidate_observations" not in str(profile)
    assert profile["profile_hash"].startswith("sha256:")


def test_no_admissible_revision_defers_to_embedding_ab() -> None:
    result = compare_reranker_revision_profiles(
        _profile("A", revision=REVISION_A, model="model-a"),
        _profile("B", revision=REVISION_B, model="model-b"),
    )

    assert result["status"] == "DECIDED"
    assert result["decision"] == {
        "status": "NO_ADMISSIBLE_REVISION",
        "selected_slot": None,
        "reason_code": "CALIBRATION_CONSTRAINTS_NOT_SATISFIED",
        "next_action": "CONTROLLED_EMBEDDING_REVISION_AB",
        "holdout_access_permitted": False,
        "runtime_activation_permitted": False,
    }


def test_single_admissible_revision_is_selected_without_opening_holdout() -> None:
    result = compare_reranker_revision_profiles(
        _profile("A", revision=REVISION_A, model="model-a"),
        _profile(
            "B",
            revision=REVISION_B,
            model="model-b",
            status="FROZEN",
            metrics=_metrics(),
        ),
    )
    assert result["decision"]["status"] == "REVISION_B_SELECTED"
    assert result["decision"]["reason_code"] == "ONLY_ADMISSIBLE_REVISION_SELECTED"
    assert result["decision"]["next_action"] == "ORIGINAL_S20Q_HOLDOUT_ACCEPTANCE"


def test_two_admissible_revisions_use_safety_first_tie_breaking() -> None:
    profile_a = _profile(
        "A",
        revision=REVISION_A,
        model="model-a",
        status="FROZEN",
        metrics=_metrics(false_ready=0.1, recall=0.9),
    )
    profile_b = _profile(
        "B",
        revision=REVISION_B,
        model="model-b",
        status="FROZEN",
        metrics=_metrics(false_ready=0.05, recall=0.8),
    )
    selected = compare_reranker_revision_profiles(profile_a, profile_b)
    assert selected["decision"]["selected_slot"] == "B"
    assert selected["decision"]["reason_code"] == (
        "ADMISSIBLE_REVISION_QUALITY_SELECTED"
    )

    equal = _profile(
        "B",
        revision=REVISION_B,
        model="model-b",
        status="FROZEN",
        metrics=_metrics(false_ready=0.1, recall=0.9),
    )
    incumbent = compare_reranker_revision_profiles(profile_a, equal)
    assert incumbent["decision"]["selected_slot"] == "A"
    assert incumbent["decision"]["reason_code"] == (
        "EQUIVALENT_REVISIONS_KEEP_INCUMBENT"
    )


@pytest.mark.parametrize(
    "mutation,error_code",
    [
        (
            lambda source: source.update(status="FAIL"),
            "S20QJ_SOURCE_EVIDENCE_NOT_ADMITTED",
        ),
        (
            lambda source: source["candidate_relevance_calibration"].update(
                status="PIPELINE_UNSTABLE"
            ),
            "S20QJ_CALIBRATION_INCOMPLETE",
        ),
        (
            lambda source: source["candidate_relevance_calibration"].update(
                holdout_access_permitted=True
            ),
            "S20QJ_CALIBRATION_BOUNDARY_INVALID",
        ),
        (
            lambda source: source["dataset"].update(partition="HOLDOUT"),
            "S20QJ_EXPERIMENT_BOUNDARY_INVALID",
        ),
    ],
)
def test_profile_projection_rejects_invalid_source_boundaries(
    mutation, error_code: str
) -> None:
    source = _source()
    mutation(source)
    with pytest.raises(RerankerRevisionABError, match=error_code):
        build_reranker_revision_profile(
            source,
            repeatability=_repeatability(),
            revision=_revision(),
            slot="A",
            source_evidence_sha256=SHA_A,
            repeatability_evidence_sha256=SHA_B,
            revision_evidence_sha256=SHA_C,
        )


def test_profile_projection_rejects_provenance_and_metric_errors() -> None:
    source = _source()
    source["provenance"]["artifact_revision"] = REVISION_B
    with pytest.raises(RerankerRevisionABError, match="PROVENANCE_MISMATCH"):
        build_reranker_revision_profile(
            source,
            repeatability=_repeatability(),
            revision=_revision(),
            slot="A",
            source_evidence_sha256=SHA_A,
            repeatability_evidence_sha256=SHA_B,
            revision_evidence_sha256=SHA_C,
        )

    invalid = _source(metrics=_metrics(false_ready=1.1))
    with pytest.raises(RerankerRevisionABError, match="FALSE_READY_RATE_INVALID"):
        build_reranker_revision_profile(
            invalid,
            repeatability=_repeatability(),
            revision=_revision(),
            slot="A",
            source_evidence_sha256=SHA_A,
            repeatability_evidence_sha256=SHA_B,
            revision_evidence_sha256=SHA_C,
        )


def test_comparison_rejects_tamper_drift_same_revision_and_semantics_change() -> None:
    profile_a = _profile("A", revision=REVISION_A, model="model-a")
    profile_b = _profile("B", revision=REVISION_B, model="model-b")

    tampered = deepcopy(profile_a)
    tampered["calibration"]["status"] = "FROZEN"
    with pytest.raises(RerankerRevisionABError, match="INTEGRITY_INVALID"):
        compare_reranker_revision_profiles(tampered, profile_b)

    drifted = _profile("B", revision=REVISION_B, model="model-b")
    unsigned = deepcopy(drifted)
    unsigned["experiment_binding"]["invariant_binding"]["embedding_model_revision"] = (
        "embedding-b"
    )
    unsigned["experiment_binding_hash"] = semantic_sha256_hash_ref(
        unsigned["experiment_binding"]
    )
    unsigned.pop("profile_hash")
    unsigned["profile_hash"] = semantic_sha256_hash_ref(unsigned)
    with pytest.raises(RerankerRevisionABError, match="EXPERIMENT_BINDING_DRIFT"):
        compare_reranker_revision_profiles(profile_a, unsigned)

    same = _profile("B", revision=REVISION_A, model="model-a")
    with pytest.raises(RerankerRevisionABError, match="REVISIONS_MUST_DIFFER"):
        compare_reranker_revision_profiles(profile_a, same)

    semantics = _profile("B", revision=REVISION_B, model="model-b")
    unsigned = deepcopy(semantics)
    unsigned["reranker_binding"]["score_semantics"] = "different"
    unsigned.pop("profile_hash")
    unsigned["profile_hash"] = semantic_sha256_hash_ref(unsigned)
    with pytest.raises(RerankerRevisionABError, match="SEMANTICS_DRIFT"):
        compare_reranker_revision_profiles(profile_a, unsigned)


def test_profile_slot_and_integrity_admission_are_fail_closed() -> None:
    with pytest.raises(RerankerRevisionABError, match="PROFILE_SLOT_INVALID"):
        _profile("C", revision=REVISION_A, model="model-a")

    profile_a = _profile("A", revision=REVISION_A, model="model-a")
    profile_b = _profile("B", revision=REVISION_B, model="model-b")
    profile_b["status"] = "REJECTED"
    with pytest.raises(RerankerRevisionABError, match="PROFILE_NOT_ADMITTED"):
        compare_reranker_revision_profiles(profile_a, profile_b)


def test_nested_hash_calibration_and_scalar_guards_are_fail_closed() -> None:
    profile_a = _profile("A", revision=REVISION_A, model="model-a")
    profile_b = _profile("B", revision=REVISION_B, model="model-b")

    nested_tamper = deepcopy(profile_b)
    nested_tamper["experiment_binding_hash"] = "sha256:" + "f" * 64
    unsigned = deepcopy(nested_tamper)
    unsigned.pop("profile_hash")
    nested_tamper["profile_hash"] = semantic_sha256_hash_ref(unsigned)
    with pytest.raises(RerankerRevisionABError, match="BINDING_INTEGRITY_INVALID"):
        compare_reranker_revision_profiles(profile_a, nested_tamper)

    incomplete = deepcopy(profile_b)
    incomplete["calibration"]["status"] = "PIPELINE_UNSTABLE"
    unsigned = deepcopy(incomplete)
    unsigned.pop("profile_hash")
    incomplete["profile_hash"] = semantic_sha256_hash_ref(unsigned)
    with pytest.raises(RerankerRevisionABError, match="CALIBRATION_INCOMPLETE"):
        compare_reranker_revision_profiles(profile_a, incomplete)

    invalid_cases = [
        (_source(), _repeatability(), _revision(), "A"),
        (_source(), _repeatability(), _revision(), "A"),
        (_source(), _repeatability(), _revision(), "A"),
        (_source(), _repeatability(), _revision(), "A"),
        (_source(), _repeatability(), _revision(), "A"),
    ]
    invalid_cases[0][0]["binding"]["chunk_policy_id"] = ""
    invalid_cases[1][0]["signal_contract"]["contract_hash"] = "not-a-hash"
    invalid_cases[2][1]["candidate_profile"]["measurement"]["repeat_count"] = 0
    invalid_cases[3][0]["candidate_relevance_calibration"]["search"][
        "admissible_profile_count"
    ] = -1
    invalid_cases[4][1]["candidate_profile"]["policy"]["score_delta_tolerance"] = 0.0
    for source, repeatability, revision, slot in invalid_cases:
        with pytest.raises(RerankerRevisionABError):
            build_reranker_revision_profile(
                source,
                repeatability=repeatability,
                revision=revision,
                slot=slot,
                source_evidence_sha256=SHA_A,
                repeatability_evidence_sha256=SHA_B,
                revision_evidence_sha256=SHA_C,
            )

    wrong_type = _source(metrics=_metrics())
    wrong_type["candidate_relevance_calibration"]["best_effort"]["candidate_auc"] = True
    with pytest.raises(RerankerRevisionABError, match="CANDIDATE_AUC_INVALID"):
        build_reranker_revision_profile(
            wrong_type,
            repeatability=_repeatability(),
            revision=_revision(),
            slot="A",
            source_evidence_sha256=SHA_A,
            repeatability_evidence_sha256=SHA_B,
            revision_evidence_sha256=SHA_C,
        )
