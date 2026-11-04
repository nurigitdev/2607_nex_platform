from __future__ import annotations

from copy import deepcopy

import nex_cx.retrieval_package_identifiability_audit as audit_module
import pytest
from nex_cx.retrieval_package_identifiability_audit import (
    audit_package_ready_identifiability,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

BINDING = {
    "embedding_model_revision": "embedding-revision",
    "reranker_model_revision": "reranker-revision",
    "ranking_policy_id": "ranking-v1",
    "tokenizer_policy_id": "tokenizer-v1",
    "chunk_policy_id": "chunk-v1",
}
PROFILES = [
    {
        "profile_id": "candidate-v1",
        "feature_fields": ["reranker_score"],
        "weights": {"reranker_score": 1.0},
    }
]
ORDINAL_DESIGN = {
    "design_schema_version": "cx_retrieval_package_ordinal_calibrator_design.v1",
    "design_id": "test-ordinal-v1",
    "policy_id": "cx_dependence_robust_package_ordinal_score_v1",
    "status": "FROZEN_CALIBRATION_ONLY",
    "feature_fields": [
        "expected_relevant_fraction",
        "second_candidate_probability",
        "top_two_probability_mean",
        "probability_at_least_half_fraction",
    ],
    "profile_shortlist": [
        {
            "profile_id": "ordinal-expected-v1",
            "evidence_source": "test",
            "weights": {
                "expected_relevant_fraction": 1.0,
                "second_candidate_probability": 0.0,
                "top_two_probability_mean": 0.0,
                "probability_at_least_half_fraction": 0.0,
            },
        },
        {
            "profile_id": "ordinal-top-two-v1",
            "evidence_source": "test",
            "weights": {
                "expected_relevant_fraction": 0.0,
                "second_candidate_probability": 0.5,
                "top_two_probability_mean": 0.5,
                "probability_at_least_half_fraction": 0.0,
            },
        },
    ],
    "safety": {
        "candidate_truth_runtime_input_permitted": False,
        "holdout_access_permitted": False,
        "runtime_activation_permitted": False,
    },
}


def _fixture(*, overlap: bool = True, scenarios: int = 12) -> tuple[list[dict], dict]:
    observations: list[dict] = []
    metadata: dict[str, dict[str, str]] = {}
    for scenario in range(scenarios):
        for ready in (False, True):
            label = "positive" if ready else "negative"
            sample_id = f"scenario-{scenario}:{label}"
            metadata[sample_id] = {
                "domain": "FINANCE" if scenario % 2 else "PROJECT",
                "language_profile": "KOREAN" if scenario % 3 else "ENGLISH",
            }
            if ready:
                roles = (
                    "PRIMARY_ANSWER",
                    "SUPPORTING_ANSWER",
                    "HARD_NON_ANSWER",
                    "EASY_NON_ANSWER",
                )
                scores = (0.80, 0.70, 0.10, 0.05) if overlap else (
                    0.95,
                    0.85,
                    0.10,
                    0.05,
                )
            else:
                roles = (
                    "HARD_NON_ANSWER",
                    "RELATED_NON_ANSWER",
                    "CONTRADICTORY_NON_ANSWER",
                    "EASY_NON_ANSWER",
                )
                scores = (0.90, 0.80, 0.10, 0.05) if overlap else (
                    0.35,
                    0.25,
                    0.15,
                    0.05,
                )
            for index, (role, score) in enumerate(zip(roles, scores, strict=True)):
                row = {
                    "observation_schema_version": (
                        "cx_retrieval_confidence_candidate_observation.v2"
                    ),
                    "sample_id": sample_id,
                    "candidate_id": f"candidate-{index}",
                    "evidence_role": role,
                    "expected_relevant": role
                    in {"PRIMARY_ANSWER", "SUPPORTING_ANSWER"},
                    "package_expected_ready": ready,
                    "rank": index + 1,
                    "signals": {
                        "reranker_score": score,
                        "rrf_normalized_score": score,
                        "channel_support": 1.0,
                        "bm25_score_quality": score,
                        "vector_similarity_quality": score,
                        "bm25_rank": index + 1,
                        "vector_rank": index + 1,
                    },
                }
                row["observation_hash"] = semantic_sha256_hash_ref(row)
                observations.append(row)
    return observations, metadata


def _audit(*, overlap: bool = True) -> dict:
    observations, metadata = _fixture(overlap=overlap)
    return audit_package_ready_identifiability(
        observations,
        candidate_profiles=PROFILES,
        ordinal_design=ORDINAL_DESIGN,
        expected_binding=BINDING,
        package_metadata=metadata,
    )


def test_audit_requires_answerability_signal_when_package_order_is_inverted() -> None:
    result = _audit()

    assert result["status"] == "DIAGNOSED"
    assert result["decision"] == "ANSWERABILITY_SIGNAL_REQUIRED"
    assert result["identifiability"]["candidate_signal_directional"]
    assert not result["identifiability"][
        "existing_package_signal_constraint_feasible"
    ]
    selected = result["identifiability"]["selected_diagnostic_combination"]
    assert selected["best_safety_point"]["ready_recall"] < 0.8
    assert selected["best_recall_floor_point"]["false_ready_rate"] > 0.1
    assert result["identifiability"]["error_topology"]["domain"]
    diagnostic = result["profile_diagnostics"][0]
    assert diagnostic["answer_support_vs_negative_role_auc"][
        "HARD_NON_ANSWER"
    ] < 0.7
    assert diagnostic["package_feature_correlations"]
    assert result["audit_hash"].startswith("sha256:")


def test_audit_reports_existing_signal_feasibility_without_admitting_runtime() -> None:
    result = _audit(overlap=False)

    assert result["decision"] == "EXISTING_SIGNAL_RECALIBRATION_JUSTIFIED"
    assert result["identifiability"][
        "existing_package_signal_constraint_feasible"
    ]
    assert result["identifiability"]["feasible_combination_ids"]
    assert result["next_contract"]["required_signal"] is None
    assert result["next_contract"]["runtime_activation_permitted"] is False


def test_audit_rejects_profile_metadata_and_role_drift() -> None:
    observations, metadata = _fixture()
    with pytest.raises(TypeError, match="candidate profiles"):
        audit_package_ready_identifiability(
            observations,
            candidate_profiles="bad",
            ordinal_design=ORDINAL_DESIGN,
            expected_binding=BINDING,
            package_metadata=metadata,
        )
    with pytest.raises(ValueError, match="profiles are missing"):
        audit_package_ready_identifiability(
            observations,
            candidate_profiles=[],
            ordinal_design=ORDINAL_DESIGN,
            expected_binding=BINDING,
            package_metadata=metadata,
        )
    incomplete = dict(metadata)
    incomplete.pop(next(iter(incomplete)))
    with pytest.raises(ValueError, match="metadata coverage"):
        audit_package_ready_identifiability(
            observations,
            candidate_profiles=PROFILES,
            ordinal_design=ORDINAL_DESIGN,
            expected_binding=BINDING,
            package_metadata=incomplete,
        )

    bad_role = deepcopy(observations)
    bad_role[0]["evidence_role"] = "PRIMARY_ANSWER"
    bad_role[0]["observation_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in bad_role[0].items() if key != "observation_hash"}
    )
    with pytest.raises(ValueError, match="role label"):
        audit_package_ready_identifiability(
            bad_role,
            candidate_profiles=PROFILES,
            ordinal_design=ORDINAL_DESIGN,
            expected_binding=BINDING,
            package_metadata=metadata,
        )


def test_audit_preserves_rejected_candidate_probability_diagnostic() -> None:
    observations, metadata = _fixture()
    for row in observations:
        row["signals"]["reranker_score"] = 0.5
        row["observation_hash"] = semantic_sha256_hash_ref(
            {key: value for key, value in row.items() if key != "observation_hash"}
        )
    result = audit_package_ready_identifiability(
        observations,
        candidate_profiles=PROFILES,
        ordinal_design=ORDINAL_DESIGN,
        expected_binding=BINDING,
        package_metadata=metadata,
    )

    assert result["status"] == "INCONCLUSIVE"
    assert result["decision"] == "STOP_FOR_REVIEW"
    assert result["profile_diagnostics"][0]["status"] == (
        "PROBABILITY_MODEL_REJECTED"
    )


def test_audit_package_semantics_guard() -> None:
    observations, metadata = _fixture()
    target = next(
        row
        for row in observations
        if row["package_expected_ready"] and row["evidence_role"] == "HARD_NON_ANSWER"
    )
    target["evidence_role"] = "SUPPORTING_ANSWER"
    target["expected_relevant"] = True
    target["observation_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in target.items() if key != "observation_hash"}
    )
    with pytest.raises(ValueError, match="package semantics"):
        audit_package_ready_identifiability(
            observations,
            candidate_profiles=PROFILES,
            ordinal_design=ORDINAL_DESIGN,
            expected_binding=BINDING,
            package_metadata=metadata,
        )


def test_audit_helper_guard_matrix() -> None:
    assert audit_module._select_diagnostic_combination([]) is None
    assert audit_module._pearson([1.0, 1.0], [0.0, 1.0]) is None
    with pytest.raises(ValueError, match="correlation values"):
        audit_module._pearson([], [])
    with pytest.raises(ValueError, match="distribution is missing"):
        audit_module._distribution([])
    with pytest.raises(ValueError, match="scores are missing"):
        audit_module._threshold_topology(
            [], maximum_false_ready_rate=0.1, minimum_ready_recall=0.8
        )
    with pytest.raises(ValueError, match="labels are incomplete"):
        audit_module._threshold_metrics(
            [{"score": 0.5, "expected_ready": True}], 0.5
        )
    with pytest.raises(ValueError, match="maximum_false_ready_rate"):
        audit_module._rate(2.0, "maximum_false_ready_rate")
    with pytest.raises(TypeError, match="candidate profile"):
        audit_module._candidate_profiles([None])
    with pytest.raises(TypeError, match="candidate profile"):
        audit_module._candidate_profiles([{"profile_id": "bad"}])
    with pytest.raises(TypeError, match="metadata is invalid"):
        audit_module._package_metadata([], [])
    with pytest.raises(TypeError, match="metadata row"):
        audit_module._package_metadata(
            {"sample": None}, [{"sample_id": "sample"}]
        )
    with pytest.raises(ValueError, match="evidence role is invalid"):
        audit_module._role_index(
            [{"sample_id": "sample", "candidate_id": "candidate", "evidence_role": "BAD"}],
            [
                {
                    "sample_id": "sample",
                    "candidate_id": "candidate",
                    "expected_relevant": False,
                }
            ],
        )
    with pytest.raises(ValueError, match="role is duplicated"):
        audit_module._role_index(
            [
                {
                    "sample_id": "sample",
                    "candidate_id": "candidate",
                    "evidence_role": "HARD_NON_ANSWER",
                },
                {
                    "sample_id": "sample",
                    "candidate_id": "candidate",
                    "evidence_role": "HARD_NON_ANSWER",
                },
            ],
            [
                {
                    "sample_id": "sample",
                    "candidate_id": "candidate",
                    "expected_relevant": False,
                }
            ],
        )
    with pytest.raises(ValueError, match="role coverage"):
        audit_module._role_index(
            [],
            [
                {
                    "sample_id": "sample",
                    "candidate_id": "candidate",
                    "expected_relevant": False,
                }
            ],
        )
    with pytest.raises(ValueError, match="package semantics"):
        audit_module._validate_package_semantics(
            {"sample": [{"candidate_id": "one"}]},
            {"sample": False},
            {"sample": 0},
        )
    with pytest.raises(ValueError, match="scenario pairs"):
        audit_module._paired_directional_rate(
            [
                {
                    "scenario_id": "scenario",
                    "expected_ready": True,
                    "score": 0.5,
                }
            ]
        )
    with pytest.raises(ValueError, match="AUC labels"):
        audit_module._auc([(0.5, True)])
    with pytest.raises(ValueError, match="field is invalid"):
        audit_module._required_string("", "field")
