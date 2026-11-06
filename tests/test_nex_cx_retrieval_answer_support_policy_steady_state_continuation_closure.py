from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from nex_cx.retrieval_answer_support_policy_steady_state_continuation_closure import (
    BASELINE_STATUS,
    CLOSURE_STATUS,
    DECISION,
    NEXT_BOUNDARY,
    RUNTIME_DISPOSITION,
    PolicySteadyStateContinuationClosureError,
    _hash_ref,
    _mapping,
    build_policy_steady_state_continuation_closure,
    validate_policy_steady_state_continuation_closure_design,
)
from nex_cx.retrieval_answer_support_policy_steady_state_continuation_review import (
    build_policy_steady_state_continuation_operator_decision,
    decide_policy_steady_state_continuation_review,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from test_nex_cx_retrieval_answer_support_policy_steady_state_continuation_review import (
    _design as _review_design,
)
from test_nex_cx_retrieval_answer_support_policy_steady_state_continuation_review import (
    _report as _continuation_report,
)

ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = (
    ROOT / "scripts/smoke/data/"
    "s136_answer_support_policy_steady_state_continuation_closure_v1_design.json"
)


def test_closure_freezes_controlled_operations_baseline() -> None:
    report, receipt = _sources()
    closure = build_policy_steady_state_continuation_closure(
        design=_design(report, receipt),
        operator_review_report=report,
        operator_review_receipt=receipt,
    )

    assert closure["status"] == "PASS"
    assert closure["decision"] == DECISION
    assert closure["closure_status"] == CLOSURE_STATUS
    assert closure["baseline_status"] == BASELINE_STATUS
    assert closure["runtime_disposition"] == RUNTIME_DISPOSITION
    assert closure["corrective_chain_closed"] is True
    assert closure["automatic_reopen_permitted"] is False
    assert len(closure["reopen_triggers"]) == 7
    assert closure["provider_calls"] == closure["database_calls"] == 0
    assert closure["holdout_accessed"] is False
    assert closure["runtime_changed"] is False
    assert closure["rollback_contract_preserved"] is True
    assert closure["production_cutover_permitted"] is False
    assert closure["next_boundary"] == NEXT_BOUNDARY
    assert all(closure["checks"].values())


def test_committed_closure_design_is_integrity_bound() -> None:
    design = _base_design()
    normalized = validate_policy_steady_state_continuation_closure_design(design)
    assert normalized["design_hash"] == design["design_hash"]

    without_hash = deepcopy(design)
    without_hash.pop("design_hash")
    assert (
        validate_policy_steady_state_continuation_closure_design(without_hash)[
            "design_hash"
        ]
        == design["design_hash"]
    )

    for field, value in (
        ("status", "DRAFT"),
        ("design_schema_version", "wrong"),
        ("design_id", ""),
    ):
        drift = deepcopy(design)
        drift[field] = value
        with pytest.raises(PolicySteadyStateContinuationClosureError):
            validate_policy_steady_state_continuation_closure_design(drift)

    drift = deepcopy(design)
    drift["closure_policy"]["automatic_reopen_permitted"] = True
    with pytest.raises(PolicySteadyStateContinuationClosureError):
        validate_policy_steady_state_continuation_closure_design(drift)

    drift = deepcopy(design)
    drift["safety"]["provider_call_permitted"] = True
    with pytest.raises(PolicySteadyStateContinuationClosureError):
        validate_policy_steady_state_continuation_closure_design(drift)

    stale = deepcopy(design)
    stale["design_id"] += "-copy"
    with pytest.raises(PolicySteadyStateContinuationClosureError) as raised:
        validate_policy_steady_state_continuation_closure_design(stale)
    assert raised.value.error_code == (
        "POLICY_STEADY_STATE_CONTINUATION_CLOSURE_INTEGRITY"
    )


def test_source_document_and_internal_hash_drift_fail_closed() -> None:
    report, receipt = _sources()
    design = _design(report, receipt)
    report["observed_metrics"]["elapsed_seconds"] = 99.0
    with pytest.raises(PolicySteadyStateContinuationClosureError) as raised:
        _build(design, report, receipt)
    assert raised.value.error_code == (
        "POLICY_STEADY_STATE_CONTINUATION_CLOSURE_INTEGRITY"
    )

    report, receipt = _sources()
    receipt["receipt_hash"] = "sha256:" + "0" * 64
    design = _design(report, receipt)
    with pytest.raises(PolicySteadyStateContinuationClosureError) as raised:
        _build(design, report, receipt)
    assert raised.value.error_code == (
        "POLICY_STEADY_STATE_CONTINUATION_CLOSURE_INTEGRITY"
    )

    report, receipt = _sources()
    report.pop("reason_codes")
    with pytest.raises(PolicySteadyStateContinuationClosureError):
        _build(_design(*_sources()), report, receipt)


@pytest.mark.parametrize(
    "mutate_report",
    [
        lambda report: report.update(status="FAIL"),
        lambda report: report.update(provider_calls=1),
        lambda report: report.update(database_calls=1),
        lambda report: report.update(holdout_accessed=True),
        lambda report: report.update(controlled_continuation_confirmed=False),
        lambda report: report.update(runtime_change_permitted=True),
        lambda report: report.update(rollback_contract_preserved=False),
        lambda report: report.update(production_cutover_permitted=True),
        lambda report: report["checks"].update(runtime_unchanged=False),
        lambda report: report.update(failed_checks=["forced"]),
    ],
)
def test_report_semantic_failures_are_rejected(mutate_report) -> None:
    report, receipt = _sources()
    mutate_report(report)
    _rehash_report(report)
    design = _design(report, receipt)
    with pytest.raises(PolicySteadyStateContinuationClosureError) as raised:
        _build(design, report, receipt)
    assert raised.value.error_code == (
        "POLICY_STEADY_STATE_CONTINUATION_CLOSURE_INVALID"
    )


@pytest.mark.parametrize(
    "mutate_receipt",
    [
        lambda receipt: receipt.update(status="FAIL"),
        lambda receipt: receipt.update(runtime_changed=True),
        lambda receipt: receipt.update(rollback_contract_preserved=False),
        lambda receipt: receipt.update(production_cutover_permitted=True),
        lambda receipt: receipt.update(steady_state_continuation_confirmed=False),
        lambda receipt: receipt.update(next_boundary="wrong"),
    ],
)
def test_receipt_semantic_failures_are_rejected(mutate_receipt) -> None:
    report, receipt = _sources()
    mutate_receipt(receipt)
    _rehash_receipt(receipt)
    report["decision_receipt_hash"] = receipt["receipt_hash"]
    _rehash_report(report)
    design = _design(report, receipt)
    with pytest.raises(PolicySteadyStateContinuationClosureError) as raised:
        _build(design, report, receipt)
    assert raised.value.error_code == (
        "POLICY_STEADY_STATE_CONTINUATION_CLOSURE_INVALID"
    )


def test_hash_and_mapping_guards() -> None:
    with pytest.raises(PolicySteadyStateContinuationClosureError):
        _hash_ref(None, "hash")
    with pytest.raises(PolicySteadyStateContinuationClosureError):
        _hash_ref("bad", "hash")
    with pytest.raises(PolicySteadyStateContinuationClosureError):
        _mapping([], "mapping")


def _build(
    design: dict[str, Any], report: dict[str, Any], receipt: dict[str, Any]
) -> dict[str, Any]:
    return build_policy_steady_state_continuation_closure(
        design=design,
        operator_review_report=report,
        operator_review_receipt=receipt,
    )


def _base_design() -> dict[str, Any]:
    return json.loads(DESIGN_PATH.read_text(encoding="utf-8"))


def _design(report: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any]:
    design = _base_design()
    source = design["source_binding"]
    source.update(
        {
            "operator_review_design_hash": report["design_hash"],
            "operator_decision_hash": report["operator_decision_hash"],
            "operator_review_manifest_hash": report["manifest_hash"],
            "operator_review_receipt_hash": receipt["receipt_hash"],
            "operator_review_report_document_hash": semantic_sha256_hash_ref(report),
            "operator_review_receipt_document_hash": semantic_sha256_hash_ref(receipt),
            "source_continuation_evidence_hash": report["source_evidence_hash"],
            "source_continuation_report_document_hash": report[
                "source_report_document_hash"
            ],
            "continuation_policy_hash": report["continuation_policy_hash"],
            "operations_profile_hash": report["operations_profile_hash"],
            "selected_policy_hash": report["selected_policy_hash"],
            "prior_continuation_receipt_hash": report[
                "prior_continuation_receipt_hash"
            ],
        }
    )
    design["design_hash"] = _semantic_hash_without(design, "design_hash")
    return design


def _sources() -> tuple[dict[str, Any], dict[str, Any]]:
    continuation = _continuation_report()
    review_design = _review_design(continuation)
    operator = build_policy_steady_state_continuation_operator_decision(
        operator_id="operator-one",
        decided_at="2026-11-06T21:00:00Z",
        design=review_design,
        source_report=continuation,
    )
    manifest = decide_policy_steady_state_continuation_review(
        design=review_design,
        source_report=continuation,
        operator_decision=operator,
    )
    receipt: dict[str, Any] = {
        "receipt_schema_version": (
            "cx_answer_support_policy_steady_state_continuation_"
            "operator_review_receipt.v1"
        ),
        "status": "PASS",
        "decision": manifest["decision"],
        "decision_status": manifest["decision_status"],
        "design_hash": review_design["design_hash"],
        "operator_decision_hash": operator["decision_hash"],
        "manifest_hash": manifest["manifest_hash"],
        "source_evidence_hash": manifest["source_evidence_hash"],
        "source_report_document_hash": manifest["source_report_document_hash"],
        "prior_continuation_receipt_hash": manifest["prior_continuation_receipt_hash"],
        "approved_scope": manifest["approved_scope"],
        "next_boundary": manifest["next_boundary"],
        "decided_at": operator["decided_at"],
        "steady_state_continuation_confirmed": True,
        "runtime_changed": False,
        "rollback_contract_preserved": True,
        "production_cutover_permitted": False,
    }
    receipt["receipt_hash"] = semantic_sha256_hash_ref(receipt)
    report = {
        "evidence_schema_version": (
            "gb2_s20qpar_answer_support_policy_steady_state_operations_"
            "continuation_operator_review.v1"
        ),
        "slice_id": "GB2-CA00-S20Q-P-AR",
        **manifest,
        "decision_receipt_hash": receipt["receipt_hash"],
    }
    return report, receipt


def _rehash_report(report: dict[str, Any]) -> None:
    payload = deepcopy(report)
    for field in (
        "evidence_schema_version",
        "slice_id",
        "decision_receipt_hash",
        "manifest_hash",
    ):
        payload.pop(field)
    report["manifest_hash"] = semantic_sha256_hash_ref(payload)


def _rehash_receipt(receipt: dict[str, Any]) -> None:
    receipt["receipt_hash"] = _semantic_hash_without(receipt, "receipt_hash")


def _semantic_hash_without(value: dict[str, Any], field: str) -> str:
    payload = deepcopy(value)
    payload.pop(field, None)
    return semantic_sha256_hash_ref(payload)
