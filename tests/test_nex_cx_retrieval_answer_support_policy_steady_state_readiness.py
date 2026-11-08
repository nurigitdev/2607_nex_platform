from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from nex_cx.retrieval_answer_support_policy_steady_state_readiness import (
    ACTIVATION_STATUS,
    NEXT_BOUNDARY,
    READINESS_DECISION,
    PolicySteadyStateReadinessError,
    _hash_ref,
    _mapping,
    decide_policy_steady_state_operations_readiness,
    validate_policy_steady_state_readiness_design,
)
from nex_cx.retrieval_answer_support_policy_sustained_operations_review import (
    build_policy_sustained_operations_operator_decision,
    decide_policy_sustained_operations_review,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from test_nex_cx_retrieval_answer_support_policy_sustained_operations_review import (
    _design as review_design,
)
from test_nex_cx_retrieval_answer_support_policy_sustained_operations_review import (
    _report as sustained_report,
)

ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = (
    ROOT
    / "scripts/smoke/data/"
    "s136_answer_support_policy_steady_state_readiness_v1_design.json"
)


def test_readiness_admits_only_separate_operator_decision() -> None:
    report, receipt = _evidence()
    manifest = decide_policy_steady_state_operations_readiness(
        report,
        receipt,
        design=_bind_design(_base_design(), report, receipt),
    )

    assert manifest["status"] == "PASS"
    assert manifest["decision"] == READINESS_DECISION
    assert manifest["activation_status"] == ACTIVATION_STATUS
    assert manifest["operations_profile"]["status"] == "READY_FOR_OPERATOR_DECISION"
    assert manifest["operations_profile"]["review_sample_interval"] == 12
    assert manifest["operations_profile"]["maximum_concurrency"] == 4
    assert manifest["operations_profile"]["runtime_activation_permitted"] is False
    assert manifest["provider_calls"] == manifest["database_calls"] == 0
    assert manifest["holdout_accessed"] is False
    assert manifest["runtime_change_permitted"] is False
    assert manifest["steady_state_activation_permitted"] is False
    assert manifest["production_cutover_permitted"] is False
    assert manifest["next_boundary"] == NEXT_BOUNDARY
    assert all(manifest["checks"].values())


def test_committed_design_is_frozen_and_integrity_bound() -> None:
    design = _base_design()
    normalized = validate_policy_steady_state_readiness_design(design)
    assert normalized["design_hash"] == design["design_hash"]

    for field, value in (
        ("status", "DRAFT"),
        ("design_schema_version", "wrong"),
        ("design_id", ""),
    ):
        drift = deepcopy(design)
        drift[field] = value
        with pytest.raises(PolicySteadyStateReadinessError):
            validate_policy_steady_state_readiness_design(drift)

    drift = deepcopy(design)
    drift["safety"]["steady_state_activation_permitted"] = True
    with pytest.raises(PolicySteadyStateReadinessError):
        validate_policy_steady_state_readiness_design(drift)

    stale = deepcopy(design)
    stale["design_id"] += "-copy"
    with pytest.raises(PolicySteadyStateReadinessError) as raised:
        validate_policy_steady_state_readiness_design(stale)
    assert raised.value.error_code == "POLICY_STEADY_STATE_READINESS_INTEGRITY"


def test_report_and_receipt_integrity_fail_closed() -> None:
    report, receipt = _evidence()
    design = _bind_design(_base_design(), report, receipt)
    report["observed_metrics"]["sample_count"] = 11
    with pytest.raises(PolicySteadyStateReadinessError) as raised:
        decide_policy_steady_state_operations_readiness(
            report, receipt, design=design
        )
    assert raised.value.error_code == "POLICY_STEADY_STATE_READINESS_INTEGRITY"

    report, receipt = _evidence()
    report["manifest_hash"] = "sha256:" + "8" * 64
    design = _bind_design(_base_design(), report, receipt)
    with pytest.raises(PolicySteadyStateReadinessError) as raised:
        decide_policy_steady_state_operations_readiness(
            report, receipt, design=design
        )
    assert raised.value.error_code == "POLICY_STEADY_STATE_READINESS_INTEGRITY"

    report, receipt = _evidence()
    receipt["runtime_changed"] = True
    _reseal_receipt(receipt)
    report["decision_receipt_hash"] = receipt["receipt_hash"]
    _reseal_report_manifest(report)
    design = _bind_design(_base_design(), report, receipt)
    with pytest.raises(PolicySteadyStateReadinessError) as raised:
        decide_policy_steady_state_operations_readiness(
            report, receipt, design=design
        )
    assert raised.value.error_code == "POLICY_STEADY_STATE_READINESS_INTEGRITY"

    report, receipt = _evidence()
    design = _bind_design(_base_design(), report, receipt)
    receipt["runtime_changed"] = True
    with pytest.raises(PolicySteadyStateReadinessError) as raised:
        decide_policy_steady_state_operations_readiness(
            report, receipt, design=design
        )
    assert raised.value.error_code == "POLICY_STEADY_STATE_READINESS_INTEGRITY"

    report, receipt = _evidence()
    report.pop("checks")
    with pytest.raises(PolicySteadyStateReadinessError):
        decide_policy_steady_state_operations_readiness(
            report, receipt, design=_base_design()
        )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda report: report["observed_metrics"].update(
            provider_p95_latency_ms=15000.1
        ),
        lambda report: report["observed_metrics"].update(
            e2e_p95_latency_ms=20000.1
        ),
        lambda report: report["observed_metrics"].update(peak_in_flight=3),
        lambda report: report["observed_metrics"].update(provider_call_count=11),
        lambda report: report["observed_metrics"].update(ready_count=0),
        lambda report: report["observed_metrics"].update(low_confidence_count=2),
        lambda report: report["checks"].update(runtime_unchanged=False),
        lambda report: report.update(provider_calls=1),
        lambda report: report.update(database_calls=1),
        lambda report: report.update(holdout_accessed=True),
        lambda report: report.update(runtime_change_permitted=True),
        lambda report: report.update(steady_state_activation_permitted=True),
        lambda report: report.update(production_cutover_permitted=True),
        lambda report: report.update(rollback_contract_preserved=False),
    ],
)
def test_readiness_semantic_failures_are_rejected(mutate) -> None:
    report, receipt = _evidence()
    mutate(report)
    _reseal_review(report, receipt)
    design = _bind_design(_base_design(), report, receipt)
    with pytest.raises(PolicySteadyStateReadinessError) as raised:
        decide_policy_steady_state_operations_readiness(
            report, receipt, design=design
        )
    assert raised.value.error_code == "POLICY_STEADY_STATE_READINESS_INVALID"


def test_malformed_metrics_and_cross_binding_fail_closed() -> None:
    report, receipt = _evidence()
    report["observed_metrics"]["elapsed_seconds"] = True
    _reseal_review(report, receipt)
    with pytest.raises(PolicySteadyStateReadinessError):
        decide_policy_steady_state_operations_readiness(
            report,
            receipt,
            design=_bind_design(_base_design(), report, receipt),
        )

    report, receipt = _evidence()
    report["observed_metrics"]["sample_count"] = 12.0
    _reseal_review(report, receipt)
    with pytest.raises(PolicySteadyStateReadinessError):
        decide_policy_steady_state_operations_readiness(
            report,
            receipt,
            design=_bind_design(_base_design(), report, receipt),
        )

    report, receipt = _evidence()
    receipt["source_report_document_hash"] = "sha256:" + "9" * 64
    _reseal_receipt(receipt)
    report["decision_receipt_hash"] = receipt["receipt_hash"]
    _reseal_report_manifest(report)
    design = _bind_design(_base_design(), report, receipt)
    with pytest.raises(PolicySteadyStateReadinessError) as raised:
        decide_policy_steady_state_operations_readiness(
            report, receipt, design=design
        )
    assert raised.value.error_code == "POLICY_STEADY_STATE_READINESS_INTEGRITY"


def test_hash_and_mapping_guards() -> None:
    with pytest.raises(PolicySteadyStateReadinessError):
        _hash_ref(None, "hash")
    with pytest.raises(PolicySteadyStateReadinessError):
        _hash_ref("bad", "hash")
    with pytest.raises(PolicySteadyStateReadinessError):
        _mapping([], "mapping")


def _base_design() -> dict[str, Any]:
    return json.loads(DESIGN_PATH.read_text(encoding="utf-8"))


def _evidence() -> tuple[dict[str, Any], dict[str, Any]]:
    source = sustained_report()
    design = review_design(source)
    operator = build_policy_sustained_operations_operator_decision(
        operator_id="operator-one",
        decided_at="2026-11-06T15:00:00Z",
        design=design,
        source_report=source,
    )
    manifest = decide_policy_sustained_operations_review(
        design=design,
        source_report=source,
        operator_decision=operator,
    )
    receipt: dict[str, Any] = {
        "receipt_schema_version": (
            "cx_answer_support_policy_sustained_operations_"
            "operator_review_receipt.v1"
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
        "sustained_operations_continuation_approved": True,
        "runtime_changed": False,
        "rollback_contract_preserved": True,
        "steady_state_activation_permitted": False,
        "production_cutover_permitted": False,
    }
    _reseal_receipt(receipt)
    report = {
        "evidence_schema_version": (
            "gb2_s20qpak_answer_support_policy_sustained_operations_"
            "operator_review.v1"
        ),
        "slice_id": "GB2-CA00-S20Q-P-AK",
        **manifest,
        "decision_receipt_hash": receipt["receipt_hash"],
    }
    return report, receipt


def _reseal_review(report: dict[str, Any], receipt: dict[str, Any]) -> None:
    _reseal_report_manifest(report)
    receipt["manifest_hash"] = report["manifest_hash"]
    _reseal_receipt(receipt)
    report["decision_receipt_hash"] = receipt["receipt_hash"]


def _reseal_report_manifest(report: dict[str, Any]) -> None:
    manifest = deepcopy(report)
    manifest.pop("evidence_schema_version")
    manifest.pop("slice_id")
    manifest.pop("decision_receipt_hash")
    manifest.pop("manifest_hash")
    report["manifest_hash"] = semantic_sha256_hash_ref(manifest)


def _reseal_receipt(receipt: dict[str, Any]) -> None:
    unsigned = deepcopy(receipt)
    unsigned.pop("receipt_hash", None)
    receipt["receipt_hash"] = semantic_sha256_hash_ref(unsigned)


def _bind_design(
    design: dict[str, Any], report: dict[str, Any], receipt: dict[str, Any]
) -> dict[str, Any]:
    source = design["source_binding"]
    source.update(
        {
            "review_report_hash": semantic_sha256_hash_ref(report),
            "review_receipt_document_hash": semantic_sha256_hash_ref(receipt),
            "review_receipt_hash": receipt["receipt_hash"],
            "review_design_hash": report["design_hash"],
            "operator_decision_hash": report["operator_decision_hash"],
            "review_manifest_hash": report["manifest_hash"],
            "source_evidence_hash": report["source_evidence_hash"],
            "sustained_policy_hash": report["sustained_policy_hash"],
            "authorization_hash": report["authorization_hash"],
            "activation_bundle_hash": report["activation_bundle_hash"],
            "selected_policy_hash": report["selected_policy_hash"],
        }
    )
    unsigned = deepcopy(design)
    unsigned.pop("design_hash", None)
    design["design_hash"] = semantic_sha256_hash_ref(unsigned)
    return design
