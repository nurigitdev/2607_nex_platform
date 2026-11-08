from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from nex_cx.retrieval_answer_support_runtime_activation_decision import (
    ACTIVATION_SCOPE,
    ACTIVATION_STATUS,
    DECISION,
    NEXT_BOUNDARY,
    RuntimeActivationDecisionError,
    _hash_ref,
    _timestamp,
    build_runtime_activation_operator_decision,
    decide_runtime_activation,
    validate_runtime_activation_decision_design,
)
from nex_cx.retrieval_answer_support_synchronous_runtime import (
    evaluate_synchronous_runtime_e2e_receipt,
    validate_synchronous_runtime_e2e_design,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from test_nex_cx_retrieval_answer_support_synchronous_runtime import (
    _acceptance_fixtures,
)

ROOT = Path(__file__).resolve().parents[1]
NOW = "2026-11-05T09:00:00Z"


def test_operator_approves_controlled_shadow_activation_without_activating() -> None:
    fixtures = _fixtures()
    operator = build_runtime_activation_operator_decision(
        operator_id="operator-one",
        decided_at=NOW,
        **fixtures,
    )
    manifest = decide_runtime_activation(operator_decision=operator, **fixtures)
    assert manifest["decision"] == DECISION
    assert manifest["activation_status"] == ACTIVATION_STATUS
    assert manifest["approved_activation_scope"] == ACTIVATION_SCOPE
    assert manifest["observed_execution"]["peak_in_flight"] == 4
    assert manifest["observed_metrics"]["e2e_p95_latency_ms"] == 12_000.0
    assert manifest["runtime_activation_permitted"] is True
    assert manifest["runtime_activated"] is False
    assert manifest["user_visible_decision_change_permitted"] is False
    assert manifest["production_cutover_permitted"] is False
    assert manifest["fallback_policy"] == manifest["rollback_target"]
    assert manifest["failed_checks"] == []
    assert manifest["next_boundary"] == NEXT_BOUNDARY


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        (None, "status", "DRAFT"),
        ("activation_policy", "required_sample_count", 29),
        ("activation_boundary", "approved_scope", "PRODUCTION"),
        ("rollback_policy", "provider_error", "IGNORE"),
        ("safety", "production_cutover_permitted", True),
    ],
)
def test_design_rejects_identity_policy_boundary_rollback_and_safety_drift(
    section: str | None, field: str, value: object
) -> None:
    design = deepcopy(_fixtures()["design"])
    target = design if section is None else design[section]
    target[field] = value
    with pytest.raises(RuntimeActivationDecisionError):
        validate_runtime_activation_decision_design(design)


def test_design_accepts_matching_hash_and_rejects_stale_hash() -> None:
    design = deepcopy(_fixtures()["design"])
    normalized = validate_runtime_activation_decision_design(design)
    design["design_hash"] = normalized["design_hash"]
    assert validate_runtime_activation_decision_design(design)["design_hash"] == (
        normalized["design_hash"]
    )
    design["design_hash"] = "sha256:" + "f" * 64
    with pytest.raises(RuntimeActivationDecisionError) as raised:
        validate_runtime_activation_decision_design(design)
    assert raised.value.error_code == "RUNTIME_ACTIVATION_DECISION_INTEGRITY"


def test_decision_rejects_report_receipt_and_binding_tamper() -> None:
    fixtures = _fixtures()
    tampered_report = deepcopy(fixtures["e2e_report"])
    tampered_report["metrics"]["e2e_p95_latency_ms"] = 1.0
    with pytest.raises(RuntimeActivationDecisionError) as raised:
        build_runtime_activation_operator_decision(
            operator_id="operator",
            decided_at=NOW,
            **{**fixtures, "e2e_report": tampered_report},
        )
    assert raised.value.error_code == "RUNTIME_ACTIVATION_DECISION_INTEGRITY"

    tampered_receipt = deepcopy(fixtures["e2e_receipt"])
    tampered_receipt["execution"]["peak_in_flight"] = 3
    with pytest.raises(RuntimeActivationDecisionError):
        build_runtime_activation_operator_decision(
            operator_id="operator",
            decided_at=NOW,
            **{**fixtures, "e2e_receipt": tampered_receipt},
        )

    design = deepcopy(fixtures["design"])
    design["source_binding"]["provider_binding_hash"] = "sha256:" + "e" * 64
    with pytest.raises(RuntimeActivationDecisionError):
        build_runtime_activation_operator_decision(
            operator_id="operator", decided_at=NOW, **{**fixtures, "design": design}
        )

    malformed_report = deepcopy(fixtures["e2e_report"])
    malformed_report["slice_id"] = "GB2-CA00-S20Q-P-X"
    design = deepcopy(fixtures["design"])
    design["source_binding"]["e2e_report_document_hash"] = semantic_sha256_hash_ref(
        malformed_report
    )
    with pytest.raises(RuntimeActivationDecisionError) as raised:
        build_runtime_activation_operator_decision(
            operator_id="operator",
            decided_at=NOW,
            **{**fixtures, "design": design, "e2e_report": malformed_report},
        )
    assert raised.value.error_code == "RUNTIME_ACTIVATION_DECISION_INVALID"


def test_decision_rejects_nonaccepted_execution_and_operator_tamper() -> None:
    fixtures = _fixtures()
    receipt = deepcopy(fixtures["e2e_receipt"])
    receipt["execution"]["provider_error_count"] = 1
    _rehash_receipt(receipt)
    manifest = evaluate_synchronous_runtime_e2e_receipt(
        receipt,
        design=fixtures["e2e_design"],
        decision_receipt=fixtures["interactive_slo_decision_receipt"],
    )
    report = _report(manifest)
    report["status"] = "PASS"
    design = _bind_design(fixtures["design"], report=report, receipt=receipt)
    with pytest.raises(RuntimeActivationDecisionError) as raised:
        build_runtime_activation_operator_decision(
            operator_id="operator",
            decided_at=NOW,
            **{
                **fixtures,
                "design": design,
                "e2e_report": report,
                "e2e_receipt": receipt,
            },
        )
    assert raised.value.error_code == "RUNTIME_ACTIVATION_DECISION_INVALID"

    operator = build_runtime_activation_operator_decision(
        operator_id="operator", decided_at=NOW, **fixtures
    )
    stale_hash = deepcopy(operator)
    stale_hash["operator_id"] = "tampered"
    with pytest.raises(RuntimeActivationDecisionError) as raised:
        decide_runtime_activation(operator_decision=stale_hash, **fixtures)
    assert raised.value.error_code == "RUNTIME_ACTIVATION_DECISION_INTEGRITY"

    operator["runtime_activated"] = True
    operator["decision_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in operator.items() if key != "decision_hash"}
    )
    with pytest.raises(RuntimeActivationDecisionError):
        decide_runtime_activation(operator_decision=operator, **fixtures)


def test_contract_helpers_reject_invalid_shapes_hashes_and_timestamps() -> None:
    with pytest.raises(RuntimeActivationDecisionError):
        validate_runtime_activation_decision_design([])  # type: ignore[arg-type]
    with pytest.raises(RuntimeActivationDecisionError):
        validate_runtime_activation_decision_design({})
    with pytest.raises(RuntimeActivationDecisionError):
        _hash_ref(None, "hash")
    with pytest.raises(RuntimeActivationDecisionError):
        _hash_ref("bad", "hash")
    for value in ("", "2026-11-05", "badZ"):
        with pytest.raises(RuntimeActivationDecisionError):
            _timestamp(value, "decided_at")


def _fixtures() -> dict:
    acceptance = _acceptance_fixtures()
    manifest = evaluate_synchronous_runtime_e2e_receipt(
        acceptance["receipt"],
        design=acceptance["design"],
        decision_receipt=acceptance["decision_receipt"],
    )
    report = _report(manifest)
    design = json.loads(
        (
            ROOT / "scripts/smoke/data/"
            "s136_answer_support_runtime_activation_operator_decision_v1_design.json"
        ).read_text(encoding="utf-8")
    )
    source = design["source_binding"]
    receipt_source = acceptance["receipt"]["source_binding"]
    source.update(
        {
            "e2e_design_hash": validate_synchronous_runtime_e2e_design(
                acceptance["design"]
            )["design_hash"],
            "e2e_manifest_hash": manifest["manifest_hash"],
            "e2e_receipt_document_hash": semantic_sha256_hash_ref(
                acceptance["receipt"]
            ),
            "e2e_receipt_hash": acceptance["receipt"]["receipt_hash"],
            "e2e_report_document_hash": semantic_sha256_hash_ref(report),
            "provider_binding_hash": receipt_source["provider_binding_hash"],
            "readiness_manifest_hash": receipt_source["readiness_manifest_hash"],
            "runtime_profile_hash": receipt_source["runtime_profile_hash"],
            "selected_policy_hash": manifest["selected_policy_hash"],
        }
    )
    return {
        "design": design,
        "e2e_report": report,
        "e2e_receipt": acceptance["receipt"],
        "e2e_design": acceptance["design"],
        "interactive_slo_decision_receipt": acceptance["decision_receipt"],
    }


def _report(manifest: dict) -> dict:
    return {
        "evidence_schema_version": "gb2_s20qpy_sync_runtime_e2e.v1",
        "slice_id": "GB2-CA00-S20Q-P-Y",
        "status": (
            "PASS"
            if manifest["decision"].startswith("SYNCHRONOUS_RUNTIME_E2E_ACCEPTED")
            else "FAIL"
        ),
        "decision": manifest["decision"],
        "design_hash": manifest["design_hash"],
        "receipt_hash": manifest["source_receipt_hash"],
        "manifest_hash": manifest["manifest_hash"],
        "selected_policy_hash": manifest["selected_policy_hash"],
        "checks": manifest["checks"],
        "failed_checks": manifest["failed_checks"],
        "execution": manifest["execution"],
        "metrics": manifest["metrics"],
        "provider_http_requests": manifest["execution"]["provider_call_count"],
        "database_calls": 0,
        "holdout_accessed": False,
        "runtime_activation_permitted": False,
        "production_cutover_permitted": False,
        "next_boundary": manifest["next_boundary"],
    }


def _bind_design(design: dict, *, report: dict, receipt: dict) -> dict:
    result = deepcopy(design)
    result["source_binding"]["e2e_manifest_hash"] = report["manifest_hash"]
    result["source_binding"]["e2e_receipt_document_hash"] = semantic_sha256_hash_ref(
        receipt
    )
    result["source_binding"]["e2e_receipt_hash"] = receipt["receipt_hash"]
    result["source_binding"]["e2e_report_document_hash"] = semantic_sha256_hash_ref(
        report
    )
    return result


def _rehash_receipt(value: dict) -> None:
    value.pop("receipt_hash", None)
    value["receipt_hash"] = semantic_sha256_hash_ref(value)
