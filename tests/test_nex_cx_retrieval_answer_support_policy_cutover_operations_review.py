from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from nex_cx.retrieval_answer_support_policy_cutover_operations_review import (
    APPROVED_SCOPE,
    DECISION,
    NEXT_BOUNDARY,
    PolicyCutoverOperationsReviewError,
    _hash_ref,
    _mapping,
    _timestamp,
    build_policy_cutover_operations_operator_decision,
    decide_policy_cutover_operations_review,
    validate_policy_cutover_operations_review_design,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = (
    ROOT
    / "scripts/smoke/data/s136_answer_support_policy_cutover_operations_review_v1_design.json"
)


def test_review_approves_only_controlled_operations_continuation() -> None:
    report = _report()
    design = _design(report)
    decision = build_policy_cutover_operations_operator_decision(
        operator_id="operator-one",
        decided_at="2026-11-06T13:00:00Z",
        design=design,
        source_report=report,
    )

    manifest = decide_policy_cutover_operations_review(
        design=design,
        source_report=report,
        operator_decision=decision,
    )

    assert manifest["status"] == "PASS"
    assert manifest["decision"] == DECISION
    assert manifest["approved_scope"] == APPROVED_SCOPE
    assert manifest["observed_metrics"]["sample_count"] == 12
    assert manifest["observed_metrics"]["ready_count"] == 9
    assert manifest["controlled_continuation_permitted"] is True
    assert manifest["runtime_change_permitted"] is False
    assert manifest["rollback_contract_preserved"] is True
    assert manifest["provider_calls"] == manifest["database_calls"] == 0
    assert manifest["holdout_accessed"] is False
    assert manifest["production_cutover_permitted"] is False
    assert manifest["next_boundary"] == NEXT_BOUNDARY
    assert all(manifest["checks"].values())


def test_committed_design_is_integrity_bound() -> None:
    design = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
    normalized = validate_policy_cutover_operations_review_design(design)
    assert normalized["design_hash"] == design["design_hash"]

    for field, value in (
        ("status", "DRAFT"),
        ("design_schema_version", "wrong"),
        ("design_id", ""),
    ):
        drift = deepcopy(design)
        drift[field] = value
        with pytest.raises(PolicyCutoverOperationsReviewError):
            validate_policy_cutover_operations_review_design(drift)

    drift = deepcopy(design)
    drift["safety"]["provider_call_permitted"] = True
    with pytest.raises(PolicyCutoverOperationsReviewError):
        validate_policy_cutover_operations_review_design(drift)

    stale = deepcopy(design)
    stale["design_id"] += "-copy"
    with pytest.raises(PolicyCutoverOperationsReviewError) as raised:
        validate_policy_cutover_operations_review_design(stale)
    assert raised.value.error_code == "POLICY_CUTOVER_OPERATIONS_REVIEW_INTEGRITY"


def test_source_report_integrity_and_exact_binding_fail_closed() -> None:
    report = _report()
    design = _design(report)
    report["live_execution"]["sample_count"] = 11
    with pytest.raises(PolicyCutoverOperationsReviewError) as raised:
        build_policy_cutover_operations_operator_decision(
            operator_id="operator-one",
            decided_at="2026-11-06T13:00:00Z",
            design=design,
            source_report=report,
        )
    assert raised.value.error_code == "POLICY_CUTOVER_OPERATIONS_REVIEW_INTEGRITY"

    report = _report()
    design = _design(report)
    rebound = deepcopy(report)
    rebound["live_execution"]["elapsed_seconds"] = 34.0
    rebound["evidence_hash"] = _semantic_hash_without(rebound, "evidence_hash")
    with pytest.raises(PolicyCutoverOperationsReviewError) as raised:
        build_policy_cutover_operations_operator_decision(
            operator_id="operator-one",
            decided_at="2026-11-06T13:00:00Z",
            design=design,
            source_report=rebound,
        )
    assert raised.value.error_code == "POLICY_CUTOVER_OPERATIONS_REVIEW_INTEGRITY"

    malformed = _report()
    malformed.pop("restart_safe")
    with pytest.raises(PolicyCutoverOperationsReviewError):
        build_policy_cutover_operations_operator_decision(
            operator_id="operator-one",
            decided_at="2026-11-06T13:00:00Z",
            design=_design(_report()),
            source_report=malformed,
        )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda report: report["live_execution"].update(
            provider_p95_latency_ms=15000.1
        ),
        lambda report: report["live_execution"].update(e2e_p95_latency_ms=20000.1),
        lambda report: report["live_execution"].update(peak_in_flight=3),
        lambda report: report["live_execution"].update(provider_call_count=11),
        lambda report: report["live_execution"].update(ready_count=0),
        lambda report: report["live_execution"].update(low_confidence_count=2),
        lambda report: report["checks"].update(no_fallback_or_skip=False),
        lambda report: report.update(test_database_residue_rows=1),
        lambda report: report.update(restart_safe=False),
        lambda report: report.update(user_visible_policy_change=False),
        lambda report: report.update(production_cutover_permitted=True),
        lambda report: report.update(holdout_accessed=True),
    ],
)
def test_review_semantic_failures_are_rejected(mutate) -> None:
    report = _report()
    mutate(report)
    design = _bind_report(_base_design(), report)
    with pytest.raises(PolicyCutoverOperationsReviewError) as raised:
        build_policy_cutover_operations_operator_decision(
            operator_id="operator-one",
            decided_at="2026-11-06T13:00:00Z",
            design=design,
            source_report=report,
        )
    assert raised.value.error_code == "POLICY_CUTOVER_OPERATIONS_REVIEW_INVALID"


def test_malformed_metrics_and_operator_tamper_fail_closed() -> None:
    report = _report()
    report["live_execution"]["elapsed_seconds"] = True
    with pytest.raises(PolicyCutoverOperationsReviewError):
        build_policy_cutover_operations_operator_decision(
            operator_id="operator-one",
            decided_at="2026-11-06T13:00:00Z",
            design=_bind_report(_base_design(), report),
            source_report=report,
        )

    report = _report()
    report["live_execution"]["sample_count"] = 12.0
    with pytest.raises(PolicyCutoverOperationsReviewError):
        build_policy_cutover_operations_operator_decision(
            operator_id="operator-one",
            decided_at="2026-11-06T13:00:00Z",
            design=_bind_report(_base_design(), report),
            source_report=report,
        )

    report = _report()
    design = _design(report)
    decision = build_policy_cutover_operations_operator_decision(
        operator_id="operator-one",
        decided_at="2026-11-06T13:00:00Z",
        design=design,
        source_report=report,
    )
    decision["production_cutover_approved"] = True
    decision["decision_hash"] = _semantic_hash_without(decision, "decision_hash")
    with pytest.raises(PolicyCutoverOperationsReviewError):
        decide_policy_cutover_operations_review(
            design=design,
            source_report=report,
            operator_decision=decision,
        )

    decision = build_policy_cutover_operations_operator_decision(
        operator_id="operator-one",
        decided_at="2026-11-06T13:00:00Z",
        design=design,
        source_report=report,
    )
    decision["operator_id"] = "tampered"
    with pytest.raises(PolicyCutoverOperationsReviewError) as raised:
        decide_policy_cutover_operations_review(
            design=design,
            source_report=report,
            operator_decision=decision,
        )
    assert raised.value.error_code == "POLICY_CUTOVER_OPERATIONS_REVIEW_INTEGRITY"


def test_text_timestamp_hash_and_mapping_guards() -> None:
    report = _report()
    design = _design(report)
    with pytest.raises(PolicyCutoverOperationsReviewError):
        build_policy_cutover_operations_operator_decision(
            operator_id=" ",
            decided_at="2026-11-06T13:00:00Z",
            design=design,
            source_report=report,
        )
    with pytest.raises(PolicyCutoverOperationsReviewError):
        _timestamp("2026-11-06T13:00:00", "timestamp")
    with pytest.raises(PolicyCutoverOperationsReviewError):
        _timestamp("badZ", "timestamp")
    with pytest.raises(PolicyCutoverOperationsReviewError):
        _hash_ref(None, "hash")
    with pytest.raises(PolicyCutoverOperationsReviewError):
        _hash_ref("bad", "hash")
    with pytest.raises(PolicyCutoverOperationsReviewError):
        _mapping([], "mapping")


def _base_design() -> dict[str, Any]:
    return json.loads(DESIGN_PATH.read_text(encoding="utf-8"))


def _design(report: dict[str, Any]) -> dict[str, Any]:
    return _bind_report(_base_design(), report)


def _bind_report(design: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    report["evidence_hash"] = _semantic_hash_without(report, "evidence_hash")
    design["source_binding"]["source_evidence_hash"] = report["evidence_hash"]
    design["source_binding"]["source_report_document_hash"] = semantic_sha256_hash_ref(
        report
    )
    design["design_hash"] = _semantic_hash_without(design, "design_hash")
    return design


def _semantic_hash_without(value: dict[str, Any], field: str) -> str:
    payload = deepcopy(value)
    payload.pop(field, None)
    return semantic_sha256_hash_ref(payload)


def _report() -> dict[str, Any]:
    report: dict[str, Any] = {
        "activation_bundle_hash": (
            "sha256:6d5c631c9e18418ae2787d4053d06cdf87cc49a3cbc67aea6258b11f29893a06"
        ),
        "authorization_hash": (
            "sha256:fe45b9267af3e81095b957c0488ee86dba7f88114b3fff99708ccc812108fc00"
        ),
        "checks": {
            name: True
            for name in (
                "all_decisions_user_visible",
                "bounded_c4_profile_preserved",
                "bounded_observation_window_complete",
                "cutover_remained_active",
                "decision_distribution_complete",
                "exact_cutover_authorization_bound",
                "exact_provider_sample_count",
                "holdout_not_accessed",
                "no_fallback_or_skip",
                "pag_acceptance_bound",
                "permission_and_evidence_preserved",
                "production_cutover_prohibited",
                "progress_completed",
                "restart_state_recovered",
                "restart_window_recovered",
                "slo_checks_passed",
                "test_database_zero_residue",
                "window_cap_is_observational",
            )
        },
        "database_profile": "test",
        "decision": "ANSWER_SUPPORT_POLICY_CUTOVER_OPERATIONS_ACCEPTED",
        "evidence_schema_version": (
            "gb2_s20qpah_answer_support_policy_cutover_operations.v1"
        ),
        "failed_checks": [],
        "holdout_accessed": False,
        "live_execution": {
            "e2e_p95_latency_ms": 11422.5,
            "elapsed_seconds": 33.589883,
            "feedback_p95_latency_ms": 1.149283,
            "low_confidence_count": 3,
            "peak_in_flight": 4,
            "provider_call_count": 12,
            "provider_p95_latency_ms": 11340.367061,
            "ready_count": 9,
            "sample_count": 12,
        },
        "next_boundary": "ANSWER_SUPPORT_POLICY_CUTOVER_OPERATIONS_OPERATOR_REVIEW",
        "operations_status": "REVIEW_REQUIRED",
        "policy_hash": (
            "sha256:7f6dd67840bf1de1ba0d5b9f2d6c5d66afffba6e0ebc5bdb71620d2c7259e439"
        ),
        "production_cutover_permitted": False,
        "restart_safe": True,
        "selected_policy_hash": (
            "sha256:c81f7a0bf3d3d72d7bbc5de1f564ada3b415f2206689c1939fcb925f172168cb"
        ),
        "slice_id": "GB2-CA00-S20Q-P-AH",
        "status": "PASS",
        "test_database_residue_rows": 0,
        "user_visible_policy_change": True,
    }
    report["evidence_hash"] = semantic_sha256_hash_ref(report)
    return report
