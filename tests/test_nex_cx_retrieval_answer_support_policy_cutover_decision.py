from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from nex_cx.retrieval_answer_support_controlled_activation import (
    ControlledRuntimeActivationError,
)
from nex_cx.retrieval_answer_support_extended_review import (
    build_extended_shadow_operator_decision,
    decide_extended_shadow_review,
)
from nex_cx.retrieval_answer_support_policy_cutover_decision import (
    APPROVED_SCOPE,
    DECISION,
    NEXT_BOUNDARY,
    PolicyCutoverDecisionError,
    _exact,
    _hash_ref,
    _mapping,
    _required_text,
    _timestamp,
    _validate_review_receipt,
    _validate_review_report,
    build_policy_cutover_operator_decision,
    decide_policy_cutover,
    validate_policy_cutover_decision_design,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from test_nex_cx_retrieval_answer_support_extended_review import (
    _design as _extended_review_design,
)
from test_nex_cx_retrieval_answer_support_extended_review import (
    _report as _extended_operations_report,
)

ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = (
    ROOT
    / "scripts/smoke/data/s136_answer_support_policy_cutover_decision_v1_design.json"
)
BUNDLE_PATH = (
    ROOT / "services/nex-cx/nex_cx/data/answer_support_controlled_activation.v1.json"
)


def test_policy_cutover_decision_approves_but_does_not_execute_cutover() -> None:
    review_receipt, review_report = _review_evidence()
    bundle = _bundle()
    design = _design(review_receipt, review_report, bundle)
    operator = build_policy_cutover_operator_decision(
        operator_id="operator-one",
        decided_at="2026-11-06T13:00:00Z",
        design=design,
        review_receipt=review_receipt,
        review_report=review_report,
        activation_bundle=bundle,
    )

    manifest = decide_policy_cutover(
        design=design,
        review_receipt=review_receipt,
        review_report=review_report,
        activation_bundle=bundle,
        operator_decision=operator,
    )

    assert manifest["status"] == "PASS"
    assert manifest["decision"] == DECISION
    assert manifest["approved_scope"] == APPROVED_SCOPE
    assert manifest["policy_cutover_permitted"] is True
    assert manifest["policy_cutover_executed"] is False
    assert manifest["runtime_change_executed"] is False
    assert manifest["user_visible_policy_change_approved"] is True
    assert manifest["user_visible_policy_change_executed"] is False
    assert manifest["production_cutover_permitted"] is False
    assert manifest["observed_metrics"]["sample_count"] == 30
    assert manifest["next_boundary"] == NEXT_BOUNDARY
    assert all(manifest["checks"].values())


def test_committed_design_is_integrity_bound() -> None:
    design = _base_design()
    normalized = validate_policy_cutover_decision_design(design)
    assert normalized["design_hash"] == design["design_hash"]

    drift = deepcopy(design)
    drift["cutover_boundary"]["cutover_execution_permitted_in_this_slice"] = True
    with pytest.raises(PolicyCutoverDecisionError):
        validate_policy_cutover_decision_design(drift)

    identity = deepcopy(design)
    identity["status"] = "DRAFT"
    with pytest.raises(PolicyCutoverDecisionError):
        validate_policy_cutover_decision_design(identity)

    stale = deepcopy(design)
    stale["design_id"] += "-copy"
    with pytest.raises(PolicyCutoverDecisionError) as raised:
        validate_policy_cutover_decision_design(stale)
    assert raised.value.error_code == "CX_POLICY_CUTOVER_DECISION_INTEGRITY"


def test_receipt_report_and_bundle_tamper_fail_closed() -> None:
    receipt, report = _review_evidence()
    bundle = _bundle()
    design = _design(receipt, report, bundle)

    tampered_receipt = deepcopy(receipt)
    tampered_receipt["runtime_changed"] = True
    with pytest.raises(PolicyCutoverDecisionError) as raised:
        build_policy_cutover_operator_decision(
            operator_id="operator-one",
            decided_at="2026-11-06T13:00:00Z",
            design=design,
            review_receipt=tampered_receipt,
            review_report=report,
            activation_bundle=bundle,
        )
    assert raised.value.error_code == "CX_POLICY_CUTOVER_DECISION_INTEGRITY"

    tampered_report = deepcopy(report)
    tampered_report["observed_metrics"]["sample_count"] = 29
    with pytest.raises(PolicyCutoverDecisionError) as raised:
        build_policy_cutover_operator_decision(
            operator_id="operator-one",
            decided_at="2026-11-06T13:00:00Z",
            design=design,
            review_receipt=receipt,
            review_report=tampered_report,
            activation_bundle=bundle,
        )
    assert raised.value.error_code == "CX_POLICY_CUTOVER_DECISION_INTEGRITY"

    tampered_bundle = deepcopy(bundle)
    tampered_bundle["selected_policy"]["status"] = "DRIFTED"
    with pytest.raises(ControlledRuntimeActivationError):
        build_policy_cutover_operator_decision(
            operator_id="operator-one",
            decided_at="2026-11-06T13:00:00Z",
            design=design,
            review_receipt=receipt,
            review_report=report,
            activation_bundle=tampered_bundle,
        )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda report: report["observed_metrics"].update(sample_count=29),
        lambda report: report["observed_metrics"].update(provider_call_count=29),
        lambda report: report["observed_metrics"].update(peak_in_flight=3),
        lambda report: report["observed_metrics"].update(
            provider_p95_latency_ms=15000.1
        ),
        lambda report: report["observed_metrics"].update(e2e_p95_latency_ms=20000.1),
        lambda report: report["observed_metrics"].update(test_database_residue_rows=1),
        lambda report: report.update(candidate_policy_status="UNADMITTED"),
    ],
)
def test_review_semantic_failures_are_rejected(mutate) -> None:
    receipt, report = _review_evidence()
    bundle = _bundle()
    mutate(report)
    design = _design(receipt, report, bundle)
    with pytest.raises(PolicyCutoverDecisionError) as raised:
        build_policy_cutover_operator_decision(
            operator_id="operator-one",
            decided_at="2026-11-06T13:00:00Z",
            design=design,
            review_receipt=receipt,
            review_report=report,
            activation_bundle=bundle,
        )
    assert raised.value.error_code == "CX_POLICY_CUTOVER_DECISION_INVALID"


def test_operator_tamper_and_guard_helpers_fail_closed() -> None:
    receipt, report = _review_evidence()
    bundle = _bundle()
    design = _design(receipt, report, bundle)
    operator = build_policy_cutover_operator_decision(
        operator_id="operator-one",
        decided_at="2026-11-06T13:00:00Z",
        design=design,
        review_receipt=receipt,
        review_report=report,
        activation_bundle=bundle,
    )
    operator["policy_cutover_executed"] = True
    operator["decision_hash"] = _semantic_hash_without(operator, "decision_hash")
    with pytest.raises(PolicyCutoverDecisionError):
        decide_policy_cutover(
            design=design,
            review_receipt=receipt,
            review_report=report,
            activation_bundle=bundle,
            operator_decision=operator,
        )

    operator = build_policy_cutover_operator_decision(
        operator_id="operator-one",
        decided_at="2026-11-06T13:00:00Z",
        design=design,
        review_receipt=receipt,
        review_report=report,
        activation_bundle=bundle,
    )
    operator["operator_id"] = "tampered"
    with pytest.raises(PolicyCutoverDecisionError) as raised:
        decide_policy_cutover(
            design=design,
            review_receipt=receipt,
            review_report=report,
            activation_bundle=bundle,
            operator_decision=operator,
        )
    assert raised.value.error_code == "CX_POLICY_CUTOVER_DECISION_INTEGRITY"

    invalid_receipt = deepcopy(receipt)
    invalid_receipt["status"] = "FAIL"
    invalid_receipt["receipt_hash"] = _semantic_hash_without(
        invalid_receipt, "receipt_hash"
    )
    with pytest.raises(PolicyCutoverDecisionError) as raised:
        _validate_review_receipt(invalid_receipt)
    assert raised.value.error_code == "CX_POLICY_CUTOVER_DECISION_INVALID"

    invalid_report = deepcopy(report)
    invalid_report["failed_checks"] = ["forced"]
    with pytest.raises(PolicyCutoverDecisionError) as raised:
        _validate_review_report(invalid_report, receipt=receipt)
    assert raised.value.error_code == "CX_POLICY_CUTOVER_DECISION_INVALID"

    with pytest.raises(PolicyCutoverDecisionError):
        _timestamp("2026-11-06T13:00:00", "timestamp")
    with pytest.raises(PolicyCutoverDecisionError):
        _timestamp("badZ", "timestamp")
    with pytest.raises(PolicyCutoverDecisionError):
        _hash_ref(None, "hash")
    with pytest.raises(PolicyCutoverDecisionError):
        _hash_ref("bad", "hash")
    with pytest.raises(PolicyCutoverDecisionError):
        _mapping([], "mapping")
    with pytest.raises(PolicyCutoverDecisionError):
        _required_text(" ", "text")
    with pytest.raises(PolicyCutoverDecisionError):
        _exact({}, {"required"}, "fields")


def _base_design() -> dict[str, Any]:
    return json.loads(DESIGN_PATH.read_text(encoding="utf-8"))


def _bundle() -> dict[str, Any]:
    return json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))


def _design(
    receipt: dict[str, Any], report: dict[str, Any], bundle: dict[str, Any]
) -> dict[str, Any]:
    design = _base_design()
    source = design["source_binding"]
    source.update(
        {
            "review_design_hash": receipt["design_hash"],
            "review_operator_decision_hash": receipt["operator_decision_hash"],
            "review_manifest_hash": receipt["manifest_hash"],
            "review_receipt_hash": receipt["receipt_hash"],
            "review_receipt_document_hash": semantic_sha256_hash_ref(receipt),
            "review_report_document_hash": semantic_sha256_hash_ref(report),
            "extended_operations_evidence_hash": receipt["source_evidence_hash"],
            "activation_bundle_hash": bundle["bundle_hash"],
            "activation_bundle_document_hash": semantic_sha256_hash_ref(bundle),
            "selected_policy_hash": bundle["selected_policy"]["policy_hash"],
            "provider_binding_hash": bundle["source_binding"]["provider_binding_hash"],
            "readiness_manifest_hash": bundle["readiness_manifest"]["manifest_hash"],
        }
    )
    design["design_hash"] = _semantic_hash_without(design, "design_hash")
    return design


def _review_evidence() -> tuple[dict[str, Any], dict[str, Any]]:
    operations = _extended_operations_report()
    design = _extended_review_design(operations)
    operator = build_extended_shadow_operator_decision(
        operator_id="source-operator",
        decided_at="2026-11-06T12:00:00Z",
        design=design,
        source_report=operations,
    )
    manifest = decide_extended_shadow_review(
        design=design,
        source_report=operations,
        operator_decision=operator,
    )
    receipt: dict[str, Any] = {
        "receipt_schema_version": (
            "cx_answer_support_extended_shadow_operator_review_receipt.v1"
        ),
        "status": "PASS",
        "decision": manifest["decision"],
        "decision_status": manifest["decision_status"],
        "design_hash": design["design_hash"],
        "operator_decision_hash": operator["decision_hash"],
        "manifest_hash": manifest["manifest_hash"],
        "source_evidence_hash": manifest["source_evidence_hash"],
        "source_report_document_hash": manifest["source_report_document_hash"],
        "approved_scope": manifest["approved_scope"],
        "next_boundary": manifest["next_boundary"],
        "decided_at": operator["decided_at"],
        "cutover_review_approved": True,
        "cutover_executed": False,
        "runtime_changed": False,
        "user_visible_decision_change_permitted": False,
        "production_cutover_permitted": False,
    }
    receipt["receipt_hash"] = semantic_sha256_hash_ref(receipt)
    report = {
        "evidence_schema_version": ("gb2_s20qpae_extended_shadow_operator_review.v1"),
        "slice_id": "GB2-CA00-S20Q-P-AE",
        **manifest,
        "decision_receipt_hash": receipt["receipt_hash"],
    }
    return receipt, report


def _semantic_hash_without(value: dict[str, Any], field: str) -> str:
    payload = deepcopy(value)
    payload.pop(field, None)
    return semantic_sha256_hash_ref(payload)
