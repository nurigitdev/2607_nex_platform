from __future__ import annotations

from copy import deepcopy

import nex_cx.retrieval_answer_support_runtime_readiness as readiness
import pytest
from nex_cx.retrieval_answer_support_runtime_readiness import (
    ACTIVATION_STATUS,
    READINESS_DECISION,
    AnswerSupportRuntimeReadinessError,
    decide_answer_support_runtime_readiness,
    validate_runtime_readiness_design,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

REVISION = "hf:" + "a" * 40
PROFILE_HASH = "sha256:" + "b" * 64
DATASET_HASH = "sha256:" + "c" * 64
REQUEST_PROFILE_HASH = "sha256:" + "d" * 64
AUTHORIZATION_HASH = "sha256:" + "e" * 64
FREEZE_HASH = "sha256:" + "f" * 64
EXECUTION_ID = "s20qpq-" + "e" * 24


def _fixture(
    *, false_ready_rate: float = 0.05, provider_revision: str = REVISION
) -> tuple[dict, dict, dict]:
    provider = {
        "deployment_id": "deployment",
        "model_revision": provider_revision,
        "provider_alias": "general-llm-default",
        "provider_type": "vllm",
        "request_profile_id": "request-profile",
        "score_semantics_id": "bounded-ordinal-answer-support-v1",
    }
    evaluation = {
        "evaluation_schema_version": "cx_answer_support_holdout_evaluation.v1",
        "status": "HOLDOUT_ADMITTED",
        "terminal_status": "PASS",
        "dataset": {
            "dataset_id": "dataset-v4",
            "dataset_sha256": DATASET_HASH,
            "partition": "HOLDOUT",
        },
        "candidate": {
            "profile_id": "answer-support-contradiction-aware-v2",
            "profile_hash": PROFILE_HASH,
            "threshold": 0.46375,
        },
        "provider_binding": provider,
        "collection_hash": "sha256:" + "1" * 64,
        "metrics": {
            "false_ready_rate": false_ready_rate,
            "ready_recall": 1.0,
        },
        "confidence_intervals": {},
        "package_auc": 1.0,
        "checks": {
            "false_ready_rate_within_limit": True,
            "fixed_threshold_evaluated": True,
            "package_auc_within_limit": True,
            "profile_selection_not_performed": True,
            "ready_recall_within_limit": True,
            "runtime_activation_prohibited": True,
            "threshold_selection_not_performed": True,
        },
        "threshold_reselected": False,
        "profile_reselected": False,
        "runtime_activation_permitted": False,
    }
    evaluation["evaluation_hash"] = semantic_sha256_hash_ref(evaluation)
    receipt = {
        "receipt_schema_version": "cx_answer_support_holdout_receipt.v1",
        "status": "PASS",
        "execution_id": EXECUTION_ID,
        "authorization_hash": AUTHORIZATION_HASH,
        "freeze_hash": FREEZE_HASH,
        "attempt_number": 1,
        "started_at": "start",
        "completed_at": "complete",
        "provider_evaluation_count": 40,
        "provider_http_request_count": 40,
        "dataset_file_sha256": "sha256:" + "2" * 64,
        "dataset_semantic_sha256": DATASET_HASH,
        "evaluation_hash": evaluation["evaluation_hash"],
        "terminal_reason": None,
    }
    receipt["receipt_hash"] = semantic_sha256_hash_ref(receipt)
    report = {
        "evidence_schema_version": "gb2_s20qpq_one_shot_holdout.v1",
        "slice_id": "GB2-CA00-S20Q-P-Q",
        "status": "PASS",
        "decision": (
            "HOLDOUT_EXECUTED_CANDIDATE_ADMITTED_SEPARATE_ACTIVATION_REQUIRED"
        ),
        "execution_id": EXECUTION_ID,
        "authorization_hash": AUTHORIZATION_HASH,
        "receipt": deepcopy(receipt),
        "provider_evaluation_count": 40,
        "provider_http_request_counts": {"generation": 40, "total": 40},
        "collection": {
            "request_profile_hash": REQUEST_PROFILE_HASH,
            "provider_binding": provider,
        },
        "evaluation": evaluation,
        "checks": {
            "execution_id_preserved": True,
            "fixed_profile_preserved": True,
            "fixed_threshold_preserved": True,
            "holdout_candidate_count_complete": True,
            "holdout_package_count_complete": True,
            "one_shot_receipt_terminal": True,
            "provider_evaluations_exact": True,
            "provider_http_requests_exact": True,
            "runtime_activation_prohibited": True,
        },
        "failed_checks": [],
        "runtime_activation_permitted": False,
    }
    design = {
        "design_schema_version": (
            "cx_answer_support_runtime_activation_readiness_design.v1"
        ),
        "design_id": "design",
        "status": "FROZEN_POST_HOLDOUT_DECISION",
        "source_binding": {
            "authorization_hash": AUTHORIZATION_HASH,
            "canonical_profile_hash": PROFILE_HASH,
            "dataset_semantic_sha256": DATASET_HASH,
            "evaluation_hash": evaluation["evaluation_hash"],
            "execution_id": EXECUTION_ID,
            "holdout_report_hash": semantic_sha256_hash_ref(report),
            "model_revision": REVISION,
            "profile_id": "answer-support-contradiction-aware-v2",
            "receipt_document_hash": semantic_sha256_hash_ref(receipt),
            "receipt_hash": receipt["receipt_hash"],
            "request_profile_hash": REQUEST_PROFILE_HASH,
            "threshold": 0.46375,
        },
        "runtime_inventory": {
            "candidate_profile_schema": "cx_answer_support_runtime_profile.v1",
            "current_confidence_consumer_schema": (
                "cx_retrieval_confidence_calibration_profile.v1"
            ),
            "direct_activation_compatible": False,
            "runtime_answer_support_evaluator_installed": False,
        },
        "readiness_policy": {
            "activation_status": "NOT_ACTIVATED",
            "admitted_readiness": "READY_FOR_SHADOW_RUNTIME_INTEGRATION",
            "expected_provider_evaluations": 40,
            "expected_provider_http_requests": 40,
            "maximum_false_ready_rate": 0.1,
            "minimum_package_auc": 0.8,
            "minimum_ready_recall": 0.8,
            "required_holdout_status": "HOLDOUT_ADMITTED",
        },
        "rollout_boundary": {
            "cutover_requires_new_holdout": False,
            "cutover_requires_separate_operator_approval": True,
            "fail_closed_on_binding_drift": True,
            "fallback_policy": "CURRENT_ACTIVE_RETRIEVAL_CONFIDENCE_POLICY",
            "first_stage": "SHADOW",
            "rollback_target": "CURRENT_ACTIVE_RETRIEVAL_CONFIDENCE_POLICY",
            "shadow_decision_user_visible": False,
        },
        "safety": {
            "candidate_truth_runtime_input_permitted": False,
            "holdout_reexecution_permitted": False,
            "production_cutover_permitted_in_this_slice": False,
            "provider_call_permitted_in_this_slice": False,
            "runtime_activation_permitted_in_this_slice": False,
            "threshold_or_profile_reselection_permitted": False,
        },
    }
    return report, receipt, design


def test_pass_receipt_admits_shadow_readiness_without_activation() -> None:
    report, receipt, design = _fixture()

    result = decide_answer_support_runtime_readiness(
        report, receipt, design=design
    )

    assert result["status"] == "PASS"
    assert result["decision"] == READINESS_DECISION
    assert result["activation_status"] == ACTIVATION_STATUS
    assert result["candidate_profile"]["status"] == "READY_FOR_SHADOW"
    assert result["candidate_profile"]["runtime_activation_permitted"] is False
    assert result["runtime_activation_permitted"] is False
    assert result["holdout_reexecution_permitted"] is False
    assert result["new_provider_calls"] == result["new_database_calls"] == 0
    assert result["manifest_hash"].startswith("sha256:")


def test_holdout_report_and_receipt_tamper_fail_closed() -> None:
    report, receipt, design = _fixture()
    report["provider_evaluation_count"] = 39
    with pytest.raises(AnswerSupportRuntimeReadinessError) as report_error:
        decide_answer_support_runtime_readiness(report, receipt, design=design)
    assert report_error.value.error_code.endswith("integrity_invalid")

    report, receipt, design = _fixture()
    receipt["completed_at"] = "changed"
    with pytest.raises(AnswerSupportRuntimeReadinessError) as receipt_error:
        decide_answer_support_runtime_readiness(report, receipt, design=design)
    assert receipt_error.value.error_code.endswith("integrity_invalid")


def test_metrics_remain_authoritative_after_hash_consistent_evidence() -> None:
    report, receipt, design = _fixture(false_ready_rate=0.11)

    with pytest.raises(AnswerSupportRuntimeReadinessError) as exc_info:
        decide_answer_support_runtime_readiness(report, receipt, design=design)

    assert exc_info.value.error_code.endswith("holdout_not_admitted")


def test_model_revision_drift_is_rejected_even_with_intact_evidence() -> None:
    report, receipt, design = _fixture(provider_revision="hf:" + "9" * 40)

    with pytest.raises(AnswerSupportRuntimeReadinessError) as exc_info:
        decide_answer_support_runtime_readiness(report, receipt, design=design)

    assert exc_info.value.error_code.endswith("contract_invalid")
    assert "source_binding" in str(exc_info.value)


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("runtime_inventory", "direct_activation_compatible", True),
        ("rollout_boundary", "first_stage", "DIRECT_CUTOVER"),
        ("safety", "holdout_reexecution_permitted", True),
        ("readiness_policy", "maximum_false_ready_rate", 0.2),
    ],
)
def test_design_cannot_relax_activation_boundary(
    section: str, field: str, value: object
) -> None:
    _report, _receipt, design = _fixture()
    design[section][field] = value

    with pytest.raises(AnswerSupportRuntimeReadinessError):
        validate_runtime_readiness_design(design)


def test_design_rejects_unknown_fields_and_invalid_binding_values() -> None:
    _report, _receipt, design = _fixture()
    design["unexpected"] = True
    with pytest.raises(AnswerSupportRuntimeReadinessError):
        validate_runtime_readiness_design(design)


def test_low_level_contract_guards_reject_each_invalid_boundary() -> None:
    report, receipt, design = _fixture()

    invalid_design = deepcopy(design)
    invalid_design["status"] = "ACTIVE"
    with pytest.raises(AnswerSupportRuntimeReadinessError):
        validate_runtime_readiness_design(invalid_design)

    mismatched_embedded = deepcopy(report)
    mismatched_embedded["receipt"]["started_at"] = "other"
    design_for_mismatch = deepcopy(design)
    design_for_mismatch["source_binding"]["holdout_report_hash"] = (
        semantic_sha256_hash_ref(mismatched_embedded)
    )
    with pytest.raises(AnswerSupportRuntimeReadinessError, match="embedded_receipt"):
        decide_answer_support_runtime_readiness(
            mismatched_embedded, receipt, design=design_for_mismatch
        )

    invalid_report = deepcopy(report)
    invalid_report["failed_checks"] = ["bad"]
    with pytest.raises(AnswerSupportRuntimeReadinessError):
        readiness._validate_report_identity(invalid_report)

    invalid_receipt = deepcopy(receipt)
    invalid_receipt["provider_http_request_count"] = 39
    with pytest.raises(AnswerSupportRuntimeReadinessError):
        readiness._validate_receipt(
            invalid_receipt, source=design["source_binding"]
        )

    invalid_evaluation = deepcopy(report["evaluation"])
    invalid_evaluation["status"] = "HOLDOUT_REJECTED"
    with pytest.raises(AnswerSupportRuntimeReadinessError):
        readiness._validate_evaluation(
            invalid_evaluation, source=design["source_binding"]
        )

    invalid_counts = deepcopy(report)
    invalid_counts["provider_http_request_counts"]["generation"] = 39
    with pytest.raises(AnswerSupportRuntimeReadinessError):
        readiness._validate_report_counts(invalid_counts, receipt=receipt)

    with pytest.raises(AnswerSupportRuntimeReadinessError):
        readiness._mapping([], "mapping")
    with pytest.raises(AnswerSupportRuntimeReadinessError):
        readiness._required_text(" ", "text")
    with pytest.raises(AnswerSupportRuntimeReadinessError):
        readiness._bounded(2.0, "score")

    _report, _receipt, design = _fixture()
    design["source_binding"]["threshold"] = True
    with pytest.raises(AnswerSupportRuntimeReadinessError):
        validate_runtime_readiness_design(design)
