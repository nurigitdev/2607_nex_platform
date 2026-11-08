from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from nex_cx.retrieval_answer_support_policy_steady_state_continuation_review import (
    APPROVED_SCOPE,
    DECISION,
    NEXT_BOUNDARY,
    PolicySteadyStateContinuationReviewError,
    _hash_ref,
    _mapping,
    _timestamp,
    build_policy_steady_state_continuation_operator_decision,
    decide_policy_steady_state_continuation_review,
    validate_policy_steady_state_continuation_review_design,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = (
    ROOT / "scripts/smoke/data/"
    "s136_answer_support_policy_steady_state_continuation_review_v1_design.json"
)


def test_review_confirms_only_controlled_steady_state_continuation() -> None:
    report = _report()
    design = _design(report)
    decision = _build(design, report)

    manifest = decide_policy_steady_state_continuation_review(
        design=design,
        source_report=report,
        operator_decision=decision,
    )

    assert manifest["status"] == "PASS"
    assert manifest["decision"] == DECISION
    assert manifest["approved_scope"] == APPROVED_SCOPE
    assert manifest["observed_metrics"]["sample_count"] == 12
    assert manifest["observed_metrics"]["ready_count"] == 9
    assert manifest["controlled_continuation_confirmed"] is True
    assert manifest["runtime_change_permitted"] is False
    assert manifest["rollback_contract_preserved"] is True
    assert manifest["production_cutover_permitted"] is False
    assert manifest["provider_calls"] == manifest["database_calls"] == 0
    assert manifest["holdout_accessed"] is False
    assert manifest["next_boundary"] == NEXT_BOUNDARY
    assert all(manifest["checks"].values())


def test_committed_continuation_review_design_is_integrity_bound() -> None:
    design = _base_design()
    normalized = validate_policy_steady_state_continuation_review_design(design)
    assert normalized["design_hash"] == design["design_hash"]

    without_hash = deepcopy(design)
    without_hash.pop("design_hash")
    assert (
        validate_policy_steady_state_continuation_review_design(without_hash)[
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
        with pytest.raises(PolicySteadyStateContinuationReviewError):
            validate_policy_steady_state_continuation_review_design(drift)

    drift = deepcopy(design)
    drift["safety"]["provider_call_permitted"] = True
    with pytest.raises(PolicySteadyStateContinuationReviewError):
        validate_policy_steady_state_continuation_review_design(drift)

    stale = deepcopy(design)
    stale["design_id"] += "-copy"
    with pytest.raises(PolicySteadyStateContinuationReviewError) as raised:
        validate_policy_steady_state_continuation_review_design(stale)
    assert raised.value.error_code == (
        "POLICY_STEADY_STATE_CONTINUATION_REVIEW_INTEGRITY"
    )


def test_source_integrity_and_prior_review_lineage_fail_closed() -> None:
    report = _report()
    design = _design(report)
    report["live_execution"]["sample_count"] = 11
    with pytest.raises(PolicySteadyStateContinuationReviewError) as raised:
        _build(design, report)
    assert raised.value.error_code == (
        "POLICY_STEADY_STATE_CONTINUATION_REVIEW_INTEGRITY"
    )

    report = _report()
    design = _design(report)
    rebound = deepcopy(report)
    rebound["source_review_report_document_hash"] = "sha256:" + "0" * 64
    rebound["evidence_hash"] = _semantic_hash_without(rebound, "evidence_hash")
    with pytest.raises(PolicySteadyStateContinuationReviewError) as raised:
        _build(design, rebound)
    assert raised.value.error_code == (
        "POLICY_STEADY_STATE_CONTINUATION_REVIEW_INTEGRITY"
    )

    malformed = _report()
    malformed.pop("continuation_receipt_hash")
    with pytest.raises(PolicySteadyStateContinuationReviewError):
        _build(_design(_report()), malformed)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda report: report["live_execution"].update(provider_p95_latency_ms=15000.1),
        lambda report: report["live_execution"].update(e2e_p95_latency_ms=20000.1),
        lambda report: report["live_execution"].update(peak_in_flight=3),
        lambda report: report["live_execution"].update(provider_call_count=11),
        lambda report: report["live_execution"].update(ready_count=0),
        lambda report: report["live_execution"].update(low_confidence_count=2),
        lambda report: report["checks"].update(continuation_policy_bound=False),
        lambda report: report.update(test_database_residue_rows=1),
        lambda report: report.update(restart_safe=False),
        lambda report: report.update(rollback_contract_preserved=False),
        lambda report: report.update(rollback_projection="ACTIVE"),
        lambda report: report.update(runtime_stopped_at_review_cadence=True),
        lambda report: report.update(production_cutover_permitted=True),
        lambda report: report.update(holdout_accessed=True),
        lambda report: report.update(operations_status="MONITORING"),
        lambda report: report.update(health_status="READY"),
        lambda report: report.update(database_profile="dev"),
        lambda report: report.update(
            next_boundary="ANSWER_SUPPORT_POLICY_STEADY_STATE_OPERATIONS"
        ),
    ],
)
def test_review_semantic_failures_are_rejected(mutate) -> None:
    report = _report()
    mutate(report)
    design = _bind_report(_base_design(), report)
    with pytest.raises(PolicySteadyStateContinuationReviewError) as raised:
        _build(design, report)
    assert raised.value.error_code == (
        "POLICY_STEADY_STATE_CONTINUATION_REVIEW_INVALID"
    )


def test_malformed_metrics_and_operator_tamper_fail_closed() -> None:
    report = _report()
    report["live_execution"]["elapsed_seconds"] = True
    with pytest.raises(PolicySteadyStateContinuationReviewError):
        _build(_bind_report(_base_design(), report), report)

    report = _report()
    report["live_execution"]["sample_count"] = 12.0
    with pytest.raises(PolicySteadyStateContinuationReviewError):
        _build(_bind_report(_base_design(), report), report)

    report = _report()
    design = _design(report)
    decision = _build(design, report)
    decision["production_cutover_approved"] = True
    decision["decision_hash"] = _semantic_hash_without(decision, "decision_hash")
    with pytest.raises(PolicySteadyStateContinuationReviewError):
        decide_policy_steady_state_continuation_review(
            design=design,
            source_report=report,
            operator_decision=decision,
        )

    decision = _build(design, report)
    decision["operator_id"] = "tampered"
    with pytest.raises(PolicySteadyStateContinuationReviewError) as raised:
        decide_policy_steady_state_continuation_review(
            design=design,
            source_report=report,
            operator_decision=decision,
        )
    assert raised.value.error_code == (
        "POLICY_STEADY_STATE_CONTINUATION_REVIEW_INTEGRITY"
    )


def test_text_timestamp_hash_and_mapping_guards() -> None:
    report = _report()
    design = _design(report)
    with pytest.raises(PolicySteadyStateContinuationReviewError):
        build_policy_steady_state_continuation_operator_decision(
            operator_id=" ",
            decided_at="2026-11-06T20:30:00Z",
            design=design,
            source_report=report,
        )
    with pytest.raises(PolicySteadyStateContinuationReviewError):
        _timestamp("2026-11-06T20:30:00", "timestamp")
    with pytest.raises(PolicySteadyStateContinuationReviewError):
        _timestamp("badZ", "timestamp")
    with pytest.raises(PolicySteadyStateContinuationReviewError):
        _hash_ref(None, "hash")
    with pytest.raises(PolicySteadyStateContinuationReviewError):
        _hash_ref("bad", "hash")
    with pytest.raises(PolicySteadyStateContinuationReviewError):
        _mapping([], "mapping")


def _build(design: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    return build_policy_steady_state_continuation_operator_decision(
        operator_id="operator-one",
        decided_at="2026-11-06T20:30:00Z",
        design=design,
        source_report=report,
    )


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
        "checks": {
            name: True
            for name in (
                "all_provider_decisions_applied",
                "bounded_c4_profile_preserved",
                "cadence_does_not_stop_runtime",
                "continuation_policy_bound",
                "decision_distribution_complete",
                "exact_operations_profile_bound",
                "exact_provider_sample_count",
                "exact_steady_state_authorization_bound",
                "holdout_not_accessed",
                "no_fallback_or_skip",
                "only_review_escalation_present",
                "pan_activation_evidence_bound",
                "pap_continuation_receipt_bound",
                "pap_review_report_bound",
                "permission_and_evidence_preserved",
                "production_cutover_prohibited",
                "progress_completed",
                "restart_cadence_recovered",
                "restart_state_recovered",
                "rollback_current_request_fell_back",
                "rollback_state_dominates",
                "slo_checks_passed",
                "steady_state_cadence_complete",
                "steady_state_remained_active",
                "test_database_zero_residue",
            )
        },
        "continuation_receipt_hash": (
            "sha256:adf95c82d9c5d3ec0adec71c93231f7ed9a50e68ffd94c7e2420a0ffce7985fd"
        ),
        "database_profile": "test",
        "decision": (
            "ANSWER_SUPPORT_POLICY_STEADY_STATE_OPERATIONS_CONTINUATION_ACCEPTED"
        ),
        "evidence_schema_version": (
            "gb2_s20qpaq_answer_support_policy_steady_state_operations_continuation.v1"
        ),
        "failed_checks": [],
        "health_status": "ATTENTION",
        "holdout_accessed": False,
        "live_execution": {
            "e2e_p95_latency_ms": 11082.871,
            "elapsed_seconds": 33.136231,
            "feedback_p95_latency_ms": 6.962794,
            "low_confidence_count": 3,
            "peak_in_flight": 4,
            "provider_call_count": 12,
            "provider_p95_latency_ms": 11044.687128,
            "ready_count": 9,
            "sample_count": 12,
        },
        "next_boundary": (
            "ANSWER_SUPPORT_POLICY_STEADY_STATE_OPERATIONS_CONTINUATION_OPERATOR_REVIEW"
        ),
        "operations_profile_hash": (
            "sha256:a7332978f9779253959c555bf9e4186ff59020363431d0962b9442d4712d5376"
        ),
        "operations_status": "OPERATOR_REVIEW_DUE",
        "policy_hash": (
            "sha256:7fc019a786ce1ad7e6022f6a2e11daab8829d6ff32e0b4034048406f2a176b97"
        ),
        "production_cutover_permitted": False,
        "restart_safe": True,
        "rollback_contract_preserved": True,
        "rollback_projection": "ROLLED_BACK",
        "runtime_stopped_at_review_cadence": False,
        "selected_policy_hash": (
            "sha256:c81f7a0bf3d3d72d7bbc5de1f564ada3b415f2206689c1939fcb925f172168cb"
        ),
        "slice_id": "GB2-CA00-S20Q-P-AQ",
        "source_activation_evidence_hash": (
            "sha256:f03487ff10b867e0b19c60933369c1dbc8e26c9c0c90b1972d7c14dbb506bcbc"
        ),
        "source_review_report_document_hash": (
            "sha256:92025d7f50af8a7c2ef546a07c5e313044a40f8f4be06a5afd9cdb1a1fb4e07c"
        ),
        "status": "PASS",
        "steady_state_authorization_hash": (
            "sha256:082356e051209a0819886b48be5b8dadf41ef63991572b97ce5ede059cefd008"
        ),
        "test_database_residue_rows": 0,
    }
    report["evidence_hash"] = semantic_sha256_hash_ref(report)
    return report
