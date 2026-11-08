from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from nex_cx.retrieval_calibration_policy_audit import (
    INCUMBENT_EMBEDDING_REVISION,
    INCUMBENT_RERANKER_REVISION,
    CalibrationPolicyAuditError,
    audit_calibration_dataset_and_package_policy,
)
from nex_cx.retrieval_candidate_relevance_calibration import (
    EXPANDED_CANDIDATE_RELEVANCE_POLICY_ID,
    calibrate_candidate_relevance_policy,
)
from nex_cx.retrieval_confidence_candidate_diagnostics import (
    EXPANDED_CANDIDATE_RELEVANCE_SAMPLE_SCHEMA_VERSION,
    EXPANDED_CANDIDATE_SIGNAL_FIELDS,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = ROOT / "scripts/smoke/data/s136_retrieval_package_calibration_v3.json"


def _cases() -> list[dict]:
    payload = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    return [case for case in payload["cases"] if case["partition"] == "CALIBRATION"]


def _samples() -> list[dict]:
    rows: list[dict] = []
    for case in _cases():
        label = "positive" if case["expected_ready"] else "negative"
        sample_id = f"{case['scenario_id']}:{label}"
        for index, candidate in enumerate(case["candidates"]):
            relevant = candidate["expected_relevant"]
            base = 0.5
            signals = {
                field: round(base - index * 0.001, 8)
                for field in EXPANDED_CANDIDATE_SIGNAL_FIELDS
            }
            unsigned = {
                "sample_schema_version": (
                    EXPANDED_CANDIDATE_RELEVANCE_SAMPLE_SCHEMA_VERSION
                ),
                "sample_id": sample_id,
                "candidate_id": candidate["candidate_id"],
                "expected_ready": case["expected_ready"],
                "expected_relevant": relevant,
                "signals": signals,
            }
            rows.append({**unsigned, "sample_hash": semantic_sha256_hash_ref(unsigned)})
    return rows


def _binding() -> dict[str, str]:
    return {
        "chunk_policy_id": "chunk_1000_100",
        "embedding_model_revision": INCUMBENT_EMBEDDING_REVISION,
        "ranking_policy_id": "weighted_rrf_vector_bm25_v1",
        "reranker_model_revision": INCUMBENT_RERANKER_REVISION,
        "tokenizer_policy_id": "cx-tokenizer-profile:sha256:" + "a" * 64,
    }


def _evidence() -> dict:
    calibration = calibrate_candidate_relevance_policy(
        _samples(),
        dataset_id="s136-retrieval-package-confidence-public-v3",
        dataset_sha256="edde3040ef27adf2ae450cc3c2193a0900620e2e514dc372a31ebe57085b34fb",
        expected_binding=_binding(),
        pipeline_repeatability={
            "status": "STABLE",
            "repeatability_hash": "sha256:" + "b" * 64,
        },
        numeric_tolerance=0.0005,
        signal_fields=EXPANDED_CANDIDATE_SIGNAL_FIELDS,
        policy_id=EXPANDED_CANDIDATE_RELEVANCE_POLICY_ID,
        signal_tolerances={"vector_similarity_quality": 0.005},
    )
    assert calibration["status"] == "NO_ACCEPTABLE_POLICY"
    return {
        "status": "PASS",
        "checks": {"complete": True},
        "dataset": {
            "dataset_id": "s136-retrieval-package-confidence-public-v3",
            "dataset_sha256": "edde3040ef27adf2ae450cc3c2193a0900620e2e514dc372a31ebe57085b34fb",
            "partition": "CALIBRATION",
            "scenario_count": 20,
            "package_count": 40,
            "candidate_count": 160,
            "holdout_status": "SEALED_NOT_COLLECTED",
        },
        "binding": _binding(),
        "candidate_relevance_calibration": calibration,
    }


def test_audit_exposes_effective_sample_policy_risk_and_keeps_incumbent() -> None:
    current = _evidence()
    historical = deepcopy(current)
    result = audit_calibration_dataset_and_package_policy(
        _cases(),
        _samples(),
        current,
        historical_evidence=historical,
        numeric_tolerance=0.0005,
        signal_tolerances={
            "reranker_score": 0.0005,
            "rrf_normalized_score": 0.0,
            "channel_rank_quality": 0.0,
            "bm25_score_quality": 0.0,
            "vector_similarity_quality": 0.005,
        },
    )

    assert result["status"] == "AUDITED"
    assert result["dataset"]["effective_independent_count"] == 20
    assert result["dataset"]["candidate_label_counts"] == {
        "relevant": 40,
        "non_relevant": 120,
    }
    assert result["package_policy"]["semantic_alignment"] == "EXACT"
    assert result["statistical_resolution"]["fold_rate_increment"] == 0.25
    assert result["statistical_resolution"]["selection_bias_risk"] == "HIGH"
    assert result["cross_execution"]["decision_stable"] is True
    assert result["decision"]["incumbent_action"] == (
        "KEEP_4B_4B_AS_NON_ADMITTED_BASELINE"
    )
    assert result["decision"]["threshold_relaxation_permitted"] is False
    assert result["decision"]["holdout_access_permitted"] is False
    assert result["audit_hash"].startswith("sha256:")


@pytest.mark.parametrize(
    "mutation,error_code",
    [
        (
            lambda evidence: evidence["binding"].update(
                embedding_model_revision="hf:" + "c" * 40
            ),
            "S20QL_MODEL_OR_POLICY_BINDING_DRIFT",
        ),
        (
            lambda evidence: evidence["dataset"].update(
                holdout_status="OPENED"
            ),
            "S20QL_HOLDOUT_BOUNDARY_INVALID",
        ),
        (
            lambda evidence: evidence.update(status="FAIL"),
            "S20QL_EVIDENCE_NOT_ADMITTED",
        ),
    ],
)
def test_audit_rejects_binding_holdout_and_evidence_drift(
    mutation, error_code: str
) -> None:
    current = _evidence()
    historical = deepcopy(current)
    mutation(historical)
    with pytest.raises(CalibrationPolicyAuditError, match=error_code):
        audit_calibration_dataset_and_package_policy(
            _cases(),
            _samples(),
            current,
            historical_evidence=historical,
            numeric_tolerance=0.0005,
            signal_tolerances={
                "reranker_score": 0.0005,
                "vector_similarity_quality": 0.005,
            },
        )


def test_audit_rejects_case_pair_and_incumbent_drift() -> None:
    current = _evidence()
    historical = deepcopy(current)
    with pytest.raises(CalibrationPolicyAuditError, match="EFFECTIVE_SAMPLE"):
        audit_calibration_dataset_and_package_policy(
            _cases()[:-1],
            _samples(),
            current,
            historical_evidence=historical,
            numeric_tolerance=0.0005,
            signal_tolerances={"reranker_score": 0.0005},
        )

    current["binding"]["embedding_model_revision"] = "hf:" + "d" * 40
    historical = deepcopy(current)
    with pytest.raises(CalibrationPolicyAuditError, match="INCUMBENT"):
        audit_calibration_dataset_and_package_policy(
            _cases(),
            _samples(),
            current,
            historical_evidence=historical,
            numeric_tolerance=0.0005,
            signal_tolerances={"reranker_score": 0.0005},
        )


def test_case_and_statistical_boundary_helpers_fail_closed() -> None:
    current = _evidence()
    historical = deepcopy(current)

    dataset_drift = deepcopy(historical)
    dataset_drift["dataset"]["dataset_sha256"] = "different"
    with pytest.raises(CalibrationPolicyAuditError, match="DATASET_BINDING_DRIFT"):
        audit_calibration_dataset_and_package_policy(
            _cases(),
            _samples(),
            current,
            historical_evidence=dataset_drift,
            numeric_tolerance=0.0005,
            signal_tolerances={"reranker_score": 0.0005},
        )

    invalid_profiles = deepcopy(current)
    invalid_profiles["candidate_relevance_calibration"]["search"]["profile_count"] = 0
    with pytest.raises(CalibrationPolicyAuditError, match="PROFILE_COUNT_INVALID"):
        audit_calibration_dataset_and_package_policy(
            _cases(),
            _samples(),
            invalid_profiles,
            historical_evidence=deepcopy(invalid_profiles),
            numeric_tolerance=0.0005,
            signal_tolerances={"reranker_score": 0.0005},
        )

    with pytest.raises(TypeError, match="cases"):
        audit_calibration_dataset_and_package_policy(
            "bad",  # type: ignore[arg-type]
            _samples(),
            current,
            historical_evidence=historical,
            numeric_tolerance=0.0005,
            signal_tolerances={"reranker_score": 0.0005},
        )

    mutations = []
    non_mapping = _cases()
    non_mapping[0] = "bad"  # type: ignore[assignment]
    mutations.append((non_mapping, "CALIBRATION_CASE_INVALID"))
    wrong_label = _cases()
    wrong_label[0]["expected_ready"] = "yes"
    mutations.append((wrong_label, "CALIBRATION_CASE_INVALID"))
    duplicated = _cases()
    duplicated[-1] = deepcopy(duplicated[0])
    mutations.append((duplicated, "CALIBRATION_CASE_DUPLICATE"))
    metadata_drift = _cases()
    metadata_drift[1]["domain"] = "OTHER"
    mutations.append((metadata_drift, "SCENARIO_METADATA_DRIFT"))
    role_invalid = _cases()
    role_invalid[0]["candidates"][0] = "bad"
    mutations.append((role_invalid, "CANDIDATE_ROLE_INVALID"))
    missing_string = _cases()
    missing_string[0]["domain"] = ""
    mutations.append((missing_string, "DOMAIN_INVALID"))
    for cases, code in mutations:
        with pytest.raises(CalibrationPolicyAuditError, match=code):
            audit_calibration_dataset_and_package_policy(
                cases,
                _samples(),
                current,
                historical_evidence=historical,
                numeric_tolerance=0.0005,
                signal_tolerances={"reranker_score": 0.0005},
            )
