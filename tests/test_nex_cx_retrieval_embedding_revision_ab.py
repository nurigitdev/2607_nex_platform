from __future__ import annotations

from copy import deepcopy

import pytest
from nex_cx.retrieval_embedding_revision_ab import (
    EmbeddingRevisionABError,
    build_embedding_revision_profile,
    compare_embedding_revision_profiles,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

REVISION_A = "hf:" + "a" * 40
REVISION_B = "hf:" + "b" * 40
SHA_A = "sha256:" + "1" * 64
SHA_B = "sha256:" + "2" * 64


def _metrics(*, false_ready: float = 0.15, recall: float = 0.65) -> dict:
    return {
        "feature_fields": ["reranker_score", "vector_similarity_quality"],
        "weights": {"reranker_score": 0.8, "vector_similarity_quality": 0.2},
        "candidate_auc": 0.84,
        "oof_metrics": {
            "false_ready_rate": false_ready,
            "ready_recall": recall,
            "balanced_accuracy": 0.75,
        },
        "minimum_fold_balanced_accuracy": 0.625,
        "threshold_spread": 0.03,
    }


def _artifact(revision: str = REVISION_A) -> dict:
    return {
        "schema_version": "model_artifact_revision.v1",
        "status": "PASS",
        "revision_source": "HUGGINGFACE_LOCAL_METADATA",
        "artifact_revision": revision,
        "metadata_file_count": 13,
        "metadata_target_count": 13,
        "weight_artifact_count": 2,
        "metadata_manifest_digest": "sha256:" + "c" * 64,
        "model_path_persisted": False,
        "artifact_content_persisted": False,
    }


def _provider(
    revision: str = REVISION_A,
    model: str = "embedding-a",
    dimension: int = 2560,
) -> dict:
    return {
        "served_model_name": model,
        "model_revision": revision,
        "deployment_id": f"deployment-{model}",
        "request_shape": "openai_embeddings",
        "response_model_revision": revision,
        "response_deployment_id": f"deployment-{model}",
        "item_count": 2,
        "indices": [0, 1],
        "vector_dimension": dimension,
        "consistent_dimension": True,
        "finite_vectors": True,
    }


def _source(
    revision: str = REVISION_A,
    *,
    status: str = "NO_ACCEPTABLE_POLICY",
    metrics: dict | None = None,
) -> dict:
    decision_metrics = metrics or _metrics()
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
            "embedding_model_revision": revision,
            "reranker_model_revision": "hf:" + "d" * 40,
            "ranking_policy_id": "ranking-v1",
            "tokenizer_policy_id": "tokenizer-v1",
            "chunk_policy_id": "chunk-v1",
        },
        "signal_contract": {
            "contract_hash": "sha256:" + "4" * 64,
            "truth_or_permission_signal_included": False,
        },
        "pipeline_repeatability": {
            "status": "STABLE",
            "policy_id": "pipeline-repeatability-v1",
            "repeatability_hash": "sha256:" + "5" * 64,
            "measurement": {"repeat_count": 5},
            "stages": {
                "max_vector_similarity_quality_delta": 0.003,
                "vector_rank_change_count": 0,
            },
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
                "signal_diagnostics": {
                    "vector_similarity_quality": {"candidate_auc": 0.72}
                },
            },
            "cross_validation": {
                "fold_count": 5,
                "constraints": {
                    "maximum_false_ready_rate": 0.1,
                    "minimum_ready_recall": 0.8,
                },
            },
            "selected": decision_metrics if status == "FROZEN" else None,
            "best_effort": decision_metrics,
        },
    }


def _profile(
    slot: str,
    *,
    revision: str,
    model: str,
    dimension: int,
    status: str = "NO_ACCEPTABLE_POLICY",
    metrics: dict | None = None,
) -> dict:
    return build_embedding_revision_profile(
        _source(revision, status=status, metrics=metrics),
        artifact_evidence=_artifact(revision),
        provider_binding=_provider(revision, model, dimension),
        slot=slot,
        source_evidence_sha256=SHA_A,
        artifact_evidence_sha256=SHA_B,
    )


def test_profile_projection_is_bounded_and_integrity_bound() -> None:
    profile = _profile(
        "A", revision=REVISION_A, model="embedding-a", dimension=2560
    )

    assert profile["status"] == "ADMITTED"
    assert profile["embedding_binding"]["artifact_revision"] == REVISION_A
    assert profile["embedding_binding"]["vector_dimension"] == 2560
    assert profile["repeatability"]["max_vector_similarity_quality_delta"] == 0.003
    assert profile["holdout_access_permitted"] is False
    assert profile["runtime_activation_permitted"] is False
    assert profile["evidence"]["raw_text_persisted"] is False
    assert profile["evidence"]["embedding_vector_persisted"] is False
    assert "data" not in profile["evidence"]
    assert profile["profile_hash"].startswith("sha256:")


def test_no_admissible_revision_defers_to_contract_review() -> None:
    result = compare_embedding_revision_profiles(
        _profile("A", revision=REVISION_A, model="embedding-a", dimension=2560),
        _profile("B", revision=REVISION_B, model="embedding-b", dimension=4096),
    )

    assert result["decision"] == {
        "status": "NO_ADMISSIBLE_REVISION",
        "selected_slot": None,
        "reason_code": "CALIBRATION_CONSTRAINTS_NOT_SATISFIED",
        "next_action": "CALIBRATION_DATASET_AND_RELEVANCE_POLICY_REVIEW",
        "holdout_access_permitted": False,
        "runtime_activation_permitted": False,
    }


def test_admissible_selection_is_safety_first_and_keeps_exact_tie() -> None:
    rejected = _profile(
        "A", revision=REVISION_A, model="embedding-a", dimension=2560
    )
    admitted_b = _profile(
        "B",
        revision=REVISION_B,
        model="embedding-b",
        dimension=4096,
        status="FROZEN",
        metrics=_metrics(false_ready=0.1, recall=0.8),
    )
    single = compare_embedding_revision_profiles(rejected, admitted_b)
    assert single["decision"]["selected_slot"] == "B"
    assert single["decision"]["reason_code"] == "ONLY_ADMISSIBLE_REVISION_SELECTED"

    admitted_a = _profile(
        "A",
        revision=REVISION_A,
        model="embedding-a",
        dimension=2560,
        status="FROZEN",
        metrics=_metrics(false_ready=0.1, recall=0.9),
    )
    safer_b = _profile(
        "B",
        revision=REVISION_B,
        model="embedding-b",
        dimension=4096,
        status="FROZEN",
        metrics=_metrics(false_ready=0.05, recall=0.8),
    )
    selected = compare_embedding_revision_profiles(admitted_a, safer_b)
    assert selected["decision"]["selected_slot"] == "B"
    assert selected["decision"]["reason_code"] == (
        "ADMISSIBLE_REVISION_QUALITY_SELECTED"
    )

    equal_b = _profile(
        "B",
        revision=REVISION_B,
        model="embedding-b",
        dimension=4096,
        status="FROZEN",
        metrics=_metrics(false_ready=0.1, recall=0.9),
    )
    incumbent = compare_embedding_revision_profiles(admitted_a, equal_b)
    assert incumbent["decision"]["selected_slot"] == "A"
    assert incumbent["decision"]["reason_code"] == (
        "EQUIVALENT_REVISIONS_KEEP_INCUMBENT"
    )


@pytest.mark.parametrize(
    "mutation,error_code",
    [
        (
            lambda source: source.update(status="FAIL"),
            "S20QK_SOURCE_EVIDENCE_NOT_ADMITTED",
        ),
        (
            lambda source: source["candidate_relevance_calibration"].update(
                status="PIPELINE_UNSTABLE"
            ),
            "S20QK_CALIBRATION_INCOMPLETE",
        ),
        (
            lambda source: source["candidate_relevance_calibration"].update(
                holdout_access_permitted=True
            ),
            "S20QK_CALIBRATION_BOUNDARY_INVALID",
        ),
        (
            lambda source: source["dataset"].update(partition="HOLDOUT"),
            "S20QK_EXPERIMENT_BOUNDARY_INVALID",
        ),
    ],
)
def test_profile_projection_rejects_invalid_source_boundaries(
    mutation, error_code: str
) -> None:
    source = _source()
    mutation(source)
    with pytest.raises(EmbeddingRevisionABError, match=error_code):
        build_embedding_revision_profile(
            source,
            artifact_evidence=_artifact(),
            provider_binding=_provider(),
            slot="A",
            source_evidence_sha256=SHA_A,
            artifact_evidence_sha256=SHA_B,
        )


def test_profile_projection_rejects_artifact_provider_and_metric_errors() -> None:
    artifact = _artifact()
    artifact["metadata_target_count"] = 12
    with pytest.raises(EmbeddingRevisionABError, match="ARTIFACT_EVIDENCE_INVALID"):
        build_embedding_revision_profile(
            _source(),
            artifact_evidence=artifact,
            provider_binding=_provider(),
            slot="A",
            source_evidence_sha256=SHA_A,
            artifact_evidence_sha256=SHA_B,
        )

    provider = _provider()
    provider["response_model_revision"] = REVISION_B
    with pytest.raises(EmbeddingRevisionABError, match="PROVENANCE_MISMATCH"):
        build_embedding_revision_profile(
            _source(),
            artifact_evidence=_artifact(),
            provider_binding=provider,
            slot="A",
            source_evidence_sha256=SHA_A,
            artifact_evidence_sha256=SHA_B,
        )

    invalid = _source(metrics=_metrics(false_ready=1.1))
    with pytest.raises(EmbeddingRevisionABError, match="FALSE_READY_RATE_INVALID"):
        build_embedding_revision_profile(
            invalid,
            artifact_evidence=_artifact(),
            provider_binding=_provider(),
            slot="A",
            source_evidence_sha256=SHA_A,
            artifact_evidence_sha256=SHA_B,
        )


def test_comparison_rejects_tamper_drift_same_revision_and_shape_change() -> None:
    profile_a = _profile(
        "A", revision=REVISION_A, model="embedding-a", dimension=2560
    )
    profile_b = _profile(
        "B", revision=REVISION_B, model="embedding-b", dimension=4096
    )

    tampered = deepcopy(profile_a)
    tampered["calibration"]["status"] = "FROZEN"
    with pytest.raises(EmbeddingRevisionABError, match="INTEGRITY_INVALID"):
        compare_embedding_revision_profiles(tampered, profile_b)

    drifted = deepcopy(profile_b)
    drifted["experiment_binding"]["invariant_binding"]["ranking_policy_id"] = (
        "ranking-v2"
    )
    drifted["experiment_binding_hash"] = semantic_sha256_hash_ref(
        drifted["experiment_binding"]
    )
    drifted.pop("profile_hash")
    drifted["profile_hash"] = semantic_sha256_hash_ref(drifted)
    with pytest.raises(EmbeddingRevisionABError, match="EXPERIMENT_BINDING_DRIFT"):
        compare_embedding_revision_profiles(profile_a, drifted)

    same = _profile("B", revision=REVISION_A, model="embedding-a", dimension=2560)
    with pytest.raises(EmbeddingRevisionABError, match="REVISIONS_MUST_DIFFER"):
        compare_embedding_revision_profiles(profile_a, same)

    shape = deepcopy(profile_b)
    shape["embedding_binding"]["request_shape"] = "legacy"
    shape.pop("profile_hash")
    shape["profile_hash"] = semantic_sha256_hash_ref(shape)
    with pytest.raises(EmbeddingRevisionABError, match="SEMANTICS_DRIFT"):
        compare_embedding_revision_profiles(profile_a, shape)


def test_profile_admission_and_scalar_guards_are_fail_closed() -> None:
    with pytest.raises(EmbeddingRevisionABError, match="PROFILE_SLOT_INVALID"):
        _profile("C", revision=REVISION_A, model="embedding-a", dimension=2560)

    profile_a = _profile(
        "A", revision=REVISION_A, model="embedding-a", dimension=2560
    )
    profile_b = _profile(
        "B", revision=REVISION_B, model="embedding-b", dimension=4096
    )
    rejected = deepcopy(profile_b)
    rejected["status"] = "REJECTED"
    with pytest.raises(EmbeddingRevisionABError, match="PROFILE_NOT_ADMITTED"):
        compare_embedding_revision_profiles(profile_a, rejected)

    nested = deepcopy(profile_b)
    nested["experiment_binding_hash"] = "sha256:" + "f" * 64
    unsigned = deepcopy(nested)
    unsigned.pop("profile_hash")
    nested["profile_hash"] = semantic_sha256_hash_ref(unsigned)
    with pytest.raises(EmbeddingRevisionABError, match="BINDING_INTEGRITY_INVALID"):
        compare_embedding_revision_profiles(profile_a, nested)

    incomplete = deepcopy(profile_b)
    incomplete["calibration"]["status"] = "PIPELINE_UNSTABLE"
    unsigned = deepcopy(incomplete)
    unsigned.pop("profile_hash")
    incomplete["profile_hash"] = semantic_sha256_hash_ref(unsigned)
    with pytest.raises(EmbeddingRevisionABError, match="CALIBRATION_INCOMPLETE"):
        compare_embedding_revision_profiles(profile_a, incomplete)

    invalid_cases = [
        (_source(), _provider()),
        (_source(), _provider()),
        (_source(), _provider()),
        (_source(), _provider()),
        (_source(), _provider()),
    ]
    invalid_cases[0][0]["binding"]["chunk_policy_id"] = ""
    invalid_cases[1][0]["signal_contract"]["contract_hash"] = "not-a-hash"
    invalid_cases[2][0]["pipeline_repeatability"]["measurement"]["repeat_count"] = 0
    invalid_cases[3][0]["pipeline_repeatability"]["stages"][
        "max_vector_similarity_quality_delta"
    ] = 0.006
    invalid_cases[4][1]["vector_dimension"] = 0
    for source, provider in invalid_cases:
        with pytest.raises(EmbeddingRevisionABError):
            build_embedding_revision_profile(
                source,
                artifact_evidence=_artifact(),
                provider_binding=provider,
                slot="A",
                source_evidence_sha256=SHA_A,
                artifact_evidence_sha256=SHA_B,
            )

    wrong_type = _source(metrics=_metrics())
    wrong_type["candidate_relevance_calibration"]["best_effort"][
        "candidate_auc"
    ] = True
    with pytest.raises(EmbeddingRevisionABError, match="CANDIDATE_AUC_INVALID"):
        build_embedding_revision_profile(
            wrong_type,
            artifact_evidence=_artifact(),
            provider_binding=_provider(),
            slot="A",
            source_evidence_sha256=SHA_A,
            artifact_evidence_sha256=SHA_B,
        )
