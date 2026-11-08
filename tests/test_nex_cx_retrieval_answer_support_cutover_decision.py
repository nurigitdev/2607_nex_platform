from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from nex_cx.retrieval_answer_support_cutover_decision import (
    AnswerSupportCutoverDecisionError,
    CUTOVER_DECISION,
    assess_runtime_cutover_blockers,
    build_runtime_cutover_operator_decision,
    decide_answer_support_runtime_cutover,
    validate_cutover_decision_design,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

ROOT = Path(__file__).resolve().parents[1]
NOW = "2026-11-05T03:00:00Z"


def test_corrected_canary_receipt_produces_fail_closed_operator_deferral() -> None:
    receipt, design = _fixtures()

    normalized, blockers = assess_runtime_cutover_blockers(receipt, design=design)
    operator = build_runtime_cutover_operator_decision(
        operator_id="operator-one",
        decided_at=NOW,
        receipt=receipt,
        design=design,
    )
    manifest = decide_answer_support_runtime_cutover(
        receipt, operator, design=design
    )

    assert normalized["receipt_hash"] == receipt["receipt_hash"]
    assert blockers == (
        "SHADOW_SAMPLE_COUNT_BELOW_MINIMUM",
        "PRODUCTION_LATENCY_SLO_NOT_FROZEN",
        "DISAGREEMENT_REQUIRES_EXTENDED_OBSERVATION",
    )
    assert operator["decision"] == CUTOVER_DECISION
    assert manifest["status"] == "PASS"
    assert manifest["decision"] == CUTOVER_DECISION
    assert manifest["observed_metrics"] == {
        "sample_count": 6,
        "failed_count": 0,
        "latency_sample_count": 6,
        "p95_latency_ms": 38912.964,
        "maximum_latency_ms": 38912.964,
        "disagreement_count": 1,
        "disagreement_rate": 0.166666666667,
    }
    assert manifest["provider_calls"] == 0
    assert manifest["holdout_accessed"] is False
    assert manifest["runtime_activation_permitted"] is False
    assert manifest["production_cutover_permitted"] is False


def test_zero_latency_defect_receipt_is_not_admitted() -> None:
    receipt, design = _fixtures()
    receipt["checks"].pop("latency_samples_complete")
    receipt["snapshot"].pop("latency_sample_count")
    receipt["snapshot"]["p95_latency_ms"] = 0
    receipt["snapshot"]["maximum_latency_ms"] = 0
    _rehash_snapshot(receipt)
    _bind_receipt(receipt, design)

    with pytest.raises(AnswerSupportCutoverDecisionError) as exc_info:
        assess_runtime_cutover_blockers(receipt, design=design)

    assert exc_info.value.error_code.endswith("contract_invalid")


@pytest.mark.parametrize(
    ("mutate", "expected_suffix"),
    [
        (lambda receipt: receipt.update(status="FAIL"), "integrity_invalid"),
        (
            lambda receipt: receipt["snapshot"].update(failed_count=1),
            "integrity_invalid",
        ),
        (
            lambda receipt: receipt["provider_http_requests"].update(total=5),
            "integrity_invalid",
        ),
    ],
)
def test_receipt_drift_is_rejected(mutate, expected_suffix: str) -> None:
    receipt, design = _fixtures()
    mutate(receipt)

    with pytest.raises(AnswerSupportCutoverDecisionError) as exc_info:
        assess_runtime_cutover_blockers(receipt, design=design)

    assert exc_info.value.error_code.endswith(expected_suffix)


def test_rehashed_but_invalid_receipt_boundaries_are_rejected() -> None:
    for mutation in (
        lambda value: value["snapshot"].update(status="HALTED"),
        lambda value: value["snapshot"].update(maximum_latency_ms=1.0),
        lambda value: value.update(completed_at=value["started_at"]),
        lambda value: value["checks"].update(no_provider_failures=False),
        lambda value: value["provider_http_requests"].update(generation=5),
    ):
        receipt, design = _fixtures()
        mutation(receipt)
        _rehash_snapshot(receipt)
        _bind_receipt(receipt, design)
        with pytest.raises(AnswerSupportCutoverDecisionError):
            assess_runtime_cutover_blockers(receipt, design=design)


def test_design_and_operator_decision_drift_fail_closed() -> None:
    receipt, design = _fixtures()
    for section, field, value in (
        ("decision_policy", "minimum_completed_shadow_samples", 6),
        ("rollout_boundary", "candidate_mode", "ACTIVE"),
        ("invalid_evidence_policy", "latency_sample_count_required", False),
        ("safety", "provider_call_permitted", True),
    ):
        drifted = copy.deepcopy(design)
        drifted[section][field] = value
        with pytest.raises(AnswerSupportCutoverDecisionError):
            validate_cutover_decision_design(drifted)

    normalized_design = validate_cutover_decision_design(design)
    supplied = copy.deepcopy(design)
    supplied["design_hash"] = normalized_design["design_hash"]
    assert validate_cutover_decision_design(supplied)["design_hash"] == supplied[
        "design_hash"
    ]
    supplied["design_hash"] = "sha256:" + "0" * 64
    with pytest.raises(AnswerSupportCutoverDecisionError) as exc_info:
        validate_cutover_decision_design(supplied)
    assert exc_info.value.error_code.endswith("integrity_invalid")

    operator = build_runtime_cutover_operator_decision(
        operator_id="operator-one",
        decided_at=NOW,
        receipt=receipt,
        design=design,
    )
    stale = copy.deepcopy(operator)
    stale["operator_id"] = "operator-two"
    with pytest.raises(AnswerSupportCutoverDecisionError) as exc_info:
        decide_answer_support_runtime_cutover(receipt, stale, design=design)
    assert exc_info.value.error_code.endswith("integrity_invalid")

    operator["production_cutover_approved"] = True
    operator.pop("decision_hash")
    operator["decision_hash"] = semantic_sha256_hash_ref(operator)
    with pytest.raises(AnswerSupportCutoverDecisionError):
        decide_answer_support_runtime_cutover(receipt, operator, design=design)


def test_extended_sample_without_disagreement_retains_only_slo_blocker() -> None:
    receipt, design = _fixtures()
    snapshot = receipt["snapshot"]
    snapshot.update(
        provider_calls=30,
        maximum_provider_calls=30,
        observed_count=30,
        latency_sample_count=30,
        disagreement_count=0,
        disagreement_rate=0.0,
    )
    receipt["maximum_provider_calls"] = 30
    receipt["provider_http_requests"] = {"generation": 30, "total": 30}
    _rehash_snapshot(receipt)
    _bind_receipt(receipt, design)

    _, blockers = assess_runtime_cutover_blockers(receipt, design=design)

    assert blockers == ("PRODUCTION_LATENCY_SLO_NOT_FROZEN",)


def test_contract_helpers_reject_invalid_types_counts_and_timestamps() -> None:
    receipt, design = _fixtures()
    cases = []

    invalid, invalid_design = _fixtures()
    invalid["snapshot"]["p95_latency_ms"] = True
    _rehash_snapshot(invalid)
    _bind_receipt(invalid, invalid_design)
    cases.append((invalid, invalid_design))

    invalid, invalid_design = _fixtures()
    invalid["snapshot"]["provider_calls"] = -1
    _rehash_snapshot(invalid)
    _bind_receipt(invalid, invalid_design)
    cases.append((invalid, invalid_design))

    invalid, invalid_design = _fixtures()
    invalid["maximum_provider_calls"] = 0
    _bind_receipt(invalid, invalid_design)
    cases.append((invalid, invalid_design))

    invalid, invalid_design = _fixtures()
    invalid["started_at"] = "not-a-time"
    _bind_receipt(invalid, invalid_design)
    cases.append((invalid, invalid_design))

    for invalid_receipt, invalid_design in cases:
        with pytest.raises(AnswerSupportCutoverDecisionError):
            assess_runtime_cutover_blockers(
                invalid_receipt, design=invalid_design
            )

    with pytest.raises(AnswerSupportCutoverDecisionError):
        build_runtime_cutover_operator_decision(
            operator_id=" ", decided_at=NOW, receipt=receipt, design=design
        )
    with pytest.raises(AnswerSupportCutoverDecisionError):
        build_runtime_cutover_operator_decision(
            operator_id="operator",
            decided_at="2026-11-05",
            receipt=receipt,
            design=design,
        )
    with pytest.raises(AnswerSupportCutoverDecisionError):
        build_runtime_cutover_operator_decision(
            operator_id="operator",
            decided_at="badZ",
            receipt=receipt,
            design=design,
        )
    with pytest.raises(AnswerSupportCutoverDecisionError):
        validate_cutover_decision_design([])
    invalid_design = copy.deepcopy(design)
    invalid_design["decision_policy"] = []
    with pytest.raises(AnswerSupportCutoverDecisionError):
        validate_cutover_decision_design(invalid_design)


def test_inner_integrity_layers_are_verified_independently() -> None:
    receipt, design = _fixtures()
    design["source_binding"]["shadow_canary_receipt_document_hash"] = (
        "sha256:" + "0" * 64
    )
    with pytest.raises(AnswerSupportCutoverDecisionError) as exc_info:
        assess_runtime_cutover_blockers(receipt, design=design)
    assert exc_info.value.error_code.endswith("integrity_invalid")

    receipt, design = _fixtures()
    receipt["snapshot"]["failed_count"] = 1
    _bind_receipt(receipt, design)
    with pytest.raises(AnswerSupportCutoverDecisionError) as exc_info:
        assess_runtime_cutover_blockers(receipt, design=design)
    assert exc_info.value.error_code.endswith("integrity_invalid")

    receipt, design = _fixtures()
    design["status"] = "DRAFT"
    with pytest.raises(AnswerSupportCutoverDecisionError) as exc_info:
        validate_cutover_decision_design(design)
    assert exc_info.value.error_code.endswith("contract_invalid")


def _fixtures() -> tuple[dict, dict]:
    design = json.loads(
        (
            ROOT
            / "scripts/smoke/data/s136_answer_support_runtime_cutover_decision_v1_design.json"
        ).read_text(encoding="utf-8")
    )
    source = design["source_binding"]
    snapshot = {
        "approval_hash": "sha256:" + "a" * 64,
        "disagreement_count": 1,
        "disagreement_rate": 0.166666666667,
        "error_rate": 0.0,
        "failed_count": 0,
        "latency_sample_count": 6,
        "maximum_latency_ms": 38912.964,
        "maximum_provider_calls": 6,
        "observed_count": 6,
        "p95_latency_ms": 38912.964,
        "policy_hash": source["shadow_canary_policy_hash"],
        "production_cutover_permitted": False,
        "provider_calls": 6,
        "runtime_activation_permitted": False,
        "snapshot_schema_version": "cx_answer_support_shadow_canary_snapshot.v1",
        "status": "COMPLETED",
        "terminal_reason": None,
        "total_tokens": 2790,
        "user_visible": False,
    }
    snapshot["snapshot_hash"] = semantic_sha256_hash_ref(snapshot)
    receipt = {
        "approval_hash": snapshot["approval_hash"],
        "checks": {
            "holdout_not_accessed": True,
            "latency_budget_passed": True,
            "latency_samples_complete": True,
            "no_provider_failures": True,
            "one_shot_budget_completed": True,
            "operator_approval_bound": True,
            "production_cutover_prohibited": True,
            "provider_calls_exact": True,
            "runtime_activation_prohibited": True,
            "shadow_not_user_visible": True,
            "token_budget_passed": True,
        },
        "completed_at": "2026-11-05T02:45:27Z",
        "decision": "SHADOW_CANARY_ACCEPTED_OPERATOR_REVIEW_REQUIRED",
        "manifest_hash": source["readiness_manifest_hash"],
        "maximum_provider_calls": 6,
        "policy_hash": source["shadow_canary_policy_hash"],
        "production_cutover_permitted": False,
        "profile_hash": source["runtime_profile_hash"],
        "provider_binding_hash": source["provider_binding_hash"],
        "provider_http_requests": {"generation": 6, "total": 6},
        "receipt_schema_version": "cx_answer_support_shadow_canary_receipt.v1",
        "runtime_activation_permitted": False,
        "snapshot": snapshot,
        "started_at": "2026-11-05T02:42:57Z",
        "status": "PASS",
    }
    _bind_receipt(receipt, design)
    return receipt, design


def _rehash_snapshot(receipt: dict) -> None:
    snapshot = receipt["snapshot"]
    snapshot.pop("snapshot_hash", None)
    snapshot["snapshot_hash"] = semantic_sha256_hash_ref(snapshot)


def _bind_receipt(receipt: dict, design: dict) -> None:
    receipt.pop("receipt_hash", None)
    receipt["receipt_hash"] = semantic_sha256_hash_ref(receipt)
    design["source_binding"]["shadow_canary_receipt_hash"] = receipt[
        "receipt_hash"
    ]
    design["source_binding"][
        "shadow_canary_receipt_document_hash"
    ] = semantic_sha256_hash_ref(receipt)
