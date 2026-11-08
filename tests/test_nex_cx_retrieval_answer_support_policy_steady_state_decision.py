from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from nex_cx.retrieval_answer_support_policy_steady_state_decision import (
    APPROVED_SCOPE,
    DECISION,
    DECISION_STATUS,
    NEXT_BOUNDARY,
    PolicySteadyStateDecisionError,
    _hash_ref,
    _mapping,
    _timestamp,
    build_policy_steady_state_operator_decision,
    decide_policy_steady_state_operations,
    validate_policy_steady_state_decision_design,
)
from nex_cx.retrieval_answer_support_policy_steady_state_readiness import (
    decide_policy_steady_state_operations_readiness,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from test_nex_cx_retrieval_answer_support_policy_steady_state_readiness import (
    _base_design as readiness_base_design,
)
from test_nex_cx_retrieval_answer_support_policy_steady_state_readiness import (
    _bind_design as bind_readiness_design,
)
from test_nex_cx_retrieval_answer_support_policy_steady_state_readiness import (
    _evidence as readiness_source_evidence,
)

ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = (
    ROOT
    / "scripts/smoke/data/"
    "s136_answer_support_policy_steady_state_decision_v1_design.json"
)


def test_operator_decision_approves_without_executing_activation() -> None:
    report = _readiness_report()
    design = _bind_design(_base_design(), report)
    operator = _operator(design, report)

    manifest = decide_policy_steady_state_operations(
        design=design,
        readiness_report=report,
        operator_decision=operator,
    )

    assert manifest["status"] == "PASS"
    assert manifest["decision"] == DECISION
    assert manifest["decision_status"] == DECISION_STATUS
    assert manifest["approved_scope"] == APPROVED_SCOPE
    assert manifest["steady_state_operations_approved"] is True
    assert manifest["steady_state_operations_activated"] is False
    assert manifest["runtime_change_executed"] is False
    assert manifest["provider_calls"] == manifest["database_calls"] == 0
    assert manifest["holdout_accessed"] is False
    assert manifest["production_cutover_permitted"] is False
    assert manifest["next_boundary"] == NEXT_BOUNDARY
    assert all(manifest["checks"].values())


def test_committed_design_is_frozen_and_integrity_bound() -> None:
    design = _base_design()
    assert validate_policy_steady_state_decision_design(design)["design_hash"] == (
        design["design_hash"]
    )

    for field, value in (
        ("status", "DRAFT"),
        ("design_schema_version", "wrong"),
        ("design_id", ""),
    ):
        drift = deepcopy(design)
        drift[field] = value
        with pytest.raises(PolicySteadyStateDecisionError):
            validate_policy_steady_state_decision_design(drift)

    for field in ("decision_policy", "activation_boundary", "rollback_policy", "safety"):
        drift = deepcopy(design)
        drift[field][next(iter(drift[field]))] = "drift"
        with pytest.raises(PolicySteadyStateDecisionError):
            validate_policy_steady_state_decision_design(drift)

    stale = deepcopy(design)
    stale["design_id"] += "-stale"
    with pytest.raises(PolicySteadyStateDecisionError) as raised:
        validate_policy_steady_state_decision_design(stale)
    assert raised.value.error_code == "POLICY_STEADY_STATE_DECISION_INTEGRITY"


def test_readiness_report_and_nested_hashes_fail_closed() -> None:
    report = _readiness_report()
    design = _bind_design(_base_design(), report)
    report["observed_metrics"]["sample_count"] = 11
    with pytest.raises(PolicySteadyStateDecisionError) as raised:
        _operator(design, report)
    assert raised.value.error_code == "POLICY_STEADY_STATE_DECISION_INTEGRITY"

    report = _readiness_report()
    report["manifest_hash"] = "sha256:" + "1" * 64
    design = _bind_design(_base_design(), report)
    with pytest.raises(PolicySteadyStateDecisionError) as raised:
        _operator(design, report)
    assert raised.value.error_code == "POLICY_STEADY_STATE_DECISION_INTEGRITY"

    report = _readiness_report()
    report["operations_profile"]["profile_hash"] = "sha256:" + "2" * 64
    _reseal_report(report)
    design = _bind_design(_base_design(), report)
    with pytest.raises(PolicySteadyStateDecisionError) as raised:
        _operator(design, report)
    assert raised.value.error_code == "POLICY_STEADY_STATE_DECISION_INTEGRITY"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda report: report.update(status="FAIL"),
        lambda report: report.update(activation_status="ACTIVATED"),
        lambda report: report["operations_profile"].update(status="DRAFT"),
        lambda report: report["operations_profile"].update(
            runtime_activation_permitted=True
        ),
        lambda report: report["checks"].update(current_runtime_unchanged=False),
        lambda report: report.update(provider_calls=1),
        lambda report: report.update(database_calls=1),
        lambda report: report.update(holdout_accessed=True),
        lambda report: report.update(runtime_change_permitted=True),
        lambda report: report.update(steady_state_activation_permitted=True),
        lambda report: report.update(production_cutover_permitted=True),
        lambda report: report["observed_metrics"].update(provider_call_count=11),
        lambda report: report["observed_metrics"].update(peak_in_flight=3),
        lambda report: report["observed_metrics"].update(
            provider_p95_latency_ms=15000.1
        ),
        lambda report: report["observed_metrics"].update(e2e_p95_latency_ms=20000.1),
        lambda report: report["observed_metrics"].update(low_confidence_count=2),
    ],
)
def test_readiness_semantic_drift_is_rejected(mutate) -> None:
    report = _readiness_report()
    mutate(report)
    _reseal_nested(report)
    _reseal_report(report)
    design = _bind_design(_base_design(), report)
    with pytest.raises(PolicySteadyStateDecisionError) as raised:
        _operator(design, report)
    assert raised.value.error_code == "POLICY_STEADY_STATE_DECISION_INVALID"


def test_operator_decision_tamper_and_identity_guards() -> None:
    report = _readiness_report()
    design = _bind_design(_base_design(), report)

    with pytest.raises(PolicySteadyStateDecisionError):
        build_policy_steady_state_operator_decision(
            operator_id=" ",
            decided_at="2026-11-06T12:00:00Z",
            design=design,
            readiness_report=report,
        )
    with pytest.raises(PolicySteadyStateDecisionError):
        build_policy_steady_state_operator_decision(
            operator_id="ops-one",
            decided_at="not-a-time",
            design=design,
            readiness_report=report,
        )

    operator = _operator(design, report)
    operator["runtime_changed"] = True
    with pytest.raises(PolicySteadyStateDecisionError) as raised:
        decide_policy_steady_state_operations(
            design=design,
            readiness_report=report,
            operator_decision=operator,
        )
    assert raised.value.error_code == "POLICY_STEADY_STATE_DECISION_INTEGRITY"

    operator = _operator(design, report)
    operator["runtime_changed"] = True
    _reseal_decision(operator)
    with pytest.raises(PolicySteadyStateDecisionError) as raised:
        decide_policy_steady_state_operations(
            design=design,
            readiness_report=report,
            operator_decision=operator,
        )
    assert raised.value.error_code == "POLICY_STEADY_STATE_DECISION_INVALID"


def test_primitive_guards_reject_malformed_values() -> None:
    with pytest.raises(PolicySteadyStateDecisionError):
        _mapping([], "mapping")
    with pytest.raises(PolicySteadyStateDecisionError):
        _hash_ref("bad", "hash")
    with pytest.raises(PolicySteadyStateDecisionError):
        _timestamp("2026-11-06T12:00:00", "timestamp")
    extra = _base_design()
    extra["unexpected"] = True
    with pytest.raises(PolicySteadyStateDecisionError):
        validate_policy_steady_state_decision_design(extra)


def _base_design() -> dict[str, Any]:
    return json.loads(DESIGN_PATH.read_text(encoding="utf-8"))


def _readiness_report() -> dict[str, Any]:
    review_report, review_receipt = readiness_source_evidence()
    readiness_design = bind_readiness_design(
        readiness_base_design(), review_report, review_receipt
    )
    manifest = decide_policy_steady_state_operations_readiness(
        review_report,
        review_receipt,
        design=readiness_design,
    )
    return {
        "evidence_schema_version": (
            "gb2_s20qpal_answer_support_policy_steady_state_readiness.v1"
        ),
        "slice_id": "GB2-CA00-S20Q-P-AL",
        "status": "PASS",
        **manifest,
    }


def _bind_design(design: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    profile = report["operations_profile"]
    source = design["source_binding"]
    source.update(
        {
            "readiness_report_hash": semantic_sha256_hash_ref(report),
            "readiness_design_hash": report["design_hash"],
            "readiness_manifest_hash": report["manifest_hash"],
            "operations_profile_hash": profile["profile_hash"],
            "source_evidence_hash": report["source_evidence"][
                "source_evidence_hash"
            ],
            "selected_policy_hash": profile["source_binding"][
                "selected_policy_hash"
            ],
            "sustained_policy_hash": profile["source_binding"][
                "sustained_policy_hash"
            ],
            "review_receipt_hash": profile["source_binding"][
                "review_receipt_hash"
            ],
        }
    )
    unsigned = deepcopy(design)
    unsigned.pop("design_hash", None)
    design["design_hash"] = semantic_sha256_hash_ref(unsigned)
    return design


def _operator(design: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    return build_policy_steady_state_operator_decision(
        operator_id="ops-one",
        decided_at="2026-11-06T12:00:00Z",
        design=design,
        readiness_report=report,
    )


def _reseal_nested(report: dict[str, Any]) -> None:
    profile = report["operations_profile"]
    unsigned = deepcopy(profile)
    unsigned.pop("profile_hash", None)
    profile["profile_hash"] = semantic_sha256_hash_ref(unsigned)


def _reseal_report(report: dict[str, Any]) -> None:
    manifest = deepcopy(report)
    manifest.pop("evidence_schema_version")
    manifest.pop("slice_id")
    manifest.pop("manifest_hash")
    report["manifest_hash"] = semantic_sha256_hash_ref(manifest)


def _reseal_decision(decision: dict[str, Any]) -> None:
    unsigned = deepcopy(decision)
    unsigned.pop("decision_hash", None)
    decision["decision_hash"] = semantic_sha256_hash_ref(unsigned)
