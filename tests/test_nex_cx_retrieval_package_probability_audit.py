from __future__ import annotations

from copy import deepcopy

import pytest
import nex_cx.retrieval_package_probability_audit as audit_module
from nex_cx.retrieval_package_probability_audit import (
    audit_candidate_probability_failure,
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


def _samples(*, overlap: bool = True) -> list[dict]:
    rows = []
    for scenario in range(12):
        for ready in (False, True):
            label = "positive" if ready else "negative"
            if overlap:
                if ready:
                    scores = (
                        (0.70, 0.65, 0.40, 0.35)
                        if scenario < 8
                        else (0.50, 0.45, 0.40, 0.35)
                    )
                else:
                    scores = (
                        (0.72, 0.68, 0.40, 0.35)
                        if scenario < 3
                        else (0.55, 0.50, 0.40, 0.35)
                    )
            else:
                scores = (0.95, 0.85, 0.15, 0.05) if ready else (
                    0.35,
                    0.25,
                    0.15,
                    0.05,
                )
            for index, score in enumerate(scores):
                row = {
                    "sample_schema_version": (
                        "cx_retrieval_confidence_candidate_relevance_sample.v2"
                    ),
                    "sample_id": f"scenario-{scenario}:{label}",
                    "candidate_id": f"{scenario}-{label}-{index}",
                    "expected_ready": ready,
                    "expected_relevant": ready and index < 2,
                    "signals": {"reranker_score": score},
                }
                row["sample_hash"] = semantic_sha256_hash_ref(row)
                rows.append(row)
    return rows


def test_audit_attributes_overlap_to_package_boundary() -> None:
    result = audit_candidate_probability_failure(
        _samples(), profiles=PROFILES, expected_binding=BINDING
    )

    assert result["status"] == "DIAGNOSED"
    assert result["decision"] == "DEPENDENCE_ROBUST_PACKAGE_SCORE_REQUIRED"
    assert result["checks"]["candidate_signal_is_directional"]
    assert result["checks"]["no_full_calibration_profile_meets_constraints"]
    profile = result["profile_diagnostics"][0]
    assert profile["package_semantics"]["ready_relevant_count"] == 2
    assert profile["package_semantics"]["low_confidence_relevant_count"] == 0
    assert profile["dependence_audit"]["conditional_independence_admitted"] is False
    assert profile["dependence_audit"][
        "mean_probability_mass_on_unobserved_counts"
    ] > 0
    assert result["audit_hash"].startswith("sha256:")


def test_audit_is_inconclusive_when_existing_signal_passes() -> None:
    result = audit_candidate_probability_failure(
        _samples(overlap=False), profiles=PROFILES, expected_binding=BINDING
    )

    assert result["status"] == "INCONCLUSIVE"
    assert result["decision"] == "STOP_FOR_REVIEW"
    assert result["checks"]["no_full_calibration_profile_meets_constraints"] is False


def test_audit_rejects_invalid_profiles_and_package_truth() -> None:
    with pytest.raises(TypeError, match="profiles"):
        audit_candidate_probability_failure(
            _samples(), profiles="bad", expected_binding=BINDING
        )
    with pytest.raises(ValueError, match="profiles are missing"):
        audit_candidate_probability_failure(
            _samples(), profiles=[], expected_binding=BINDING
        )

    bad = deepcopy(_samples())
    bad[0]["expected_relevant"] = True
    bad[0]["sample_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in bad[0].items() if key != "sample_hash"}
    )
    with pytest.raises(ValueError, match="package semantics"):
        audit_candidate_probability_failure(
            bad, profiles=PROFILES, expected_binding=BINDING
        )


def test_audit_rejects_malformed_profile() -> None:
    with pytest.raises(TypeError, match="profile is invalid"):
        audit_candidate_probability_failure(
            _samples(), profiles=[{"profile_id": "bad"}], expected_binding=BINDING
        )

    with pytest.raises(TypeError, match="profile is invalid"):
        audit_candidate_probability_failure(
            _samples(), profiles=[None], expected_binding=BINDING
        )


def test_audit_preserves_rejected_probability_model_diagnostic() -> None:
    samples = _samples()
    for row in samples:
        row["signals"]["reranker_score"] = 0.5
        row["sample_hash"] = semantic_sha256_hash_ref(
            {key: value for key, value in row.items() if key != "sample_hash"}
        )

    result = audit_candidate_probability_failure(
        samples, profiles=PROFILES, expected_binding=BINDING
    )

    assert result["status"] == "INCONCLUSIVE"
    assert result["profile_diagnostics"] == [
        {
            "profile_id": "candidate-v1",
            "status": "PROBABILITY_MODEL_REJECTED",
            "candidate_probability_model_status": (
                "REJECTED_NON_DIRECTIONAL_OR_UNCONVERGED"
            ),
        }
    ]


def test_audit_metric_guard_matrix() -> None:
    with pytest.raises(ValueError, match="values are missing"):
        audit_module._probability_metrics([])
    with pytest.raises(ValueError, match="labels are incomplete"):
        audit_module._auc([(0.5, True)])
    with pytest.raises(ValueError, match="distribution is missing"):
        audit_module._distribution([])
    with pytest.raises(ValueError, match="semantics are inconsistent"):
        audit_module._only_count(
            [{"actual_relevant_count": 0}, {"actual_relevant_count": 2}]
        )
    with pytest.raises(ValueError, match="pairs are incomplete"):
        audit_module._paired_directional_rate(
            [
                {
                    "sample_id": "scenario:positive",
                    "expected_ready": True,
                    "score": 0.5,
                }
            ]
        )
