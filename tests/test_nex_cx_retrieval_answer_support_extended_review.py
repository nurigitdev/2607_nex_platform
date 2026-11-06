from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from nex_cx.retrieval_answer_support_extended_review import (
    APPROVED_SCOPE,
    DECISION,
    NEXT_BOUNDARY,
    ExtendedShadowReviewError,
    _hash_ref,
    _mapping,
    _timestamp,
    build_extended_shadow_operator_decision,
    decide_extended_shadow_review,
    validate_extended_shadow_review_design,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = (
    ROOT
    / "scripts/smoke/data/s136_answer_support_extended_shadow_review_v1_design.json"
)


def test_extended_review_approves_only_a_separate_cutover_review() -> None:
    report = _report()
    design = _design(report)
    decision = build_extended_shadow_operator_decision(
        operator_id="operator-one",
        decided_at="2026-11-06T12:00:00Z",
        design=design,
        source_report=report,
    )

    manifest = decide_extended_shadow_review(
        design=design,
        source_report=report,
        operator_decision=decision,
    )

    assert manifest["status"] == "PASS"
    assert manifest["decision"] == DECISION
    assert manifest["approved_scope"] == APPROVED_SCOPE
    assert manifest["observed_metrics"]["sample_count"] == 30
    assert manifest["observed_metrics"]["provider_p95_latency_ms"] == 10999.170554
    assert manifest["cutover_review_permitted"] is True
    assert manifest["cutover_execution_permitted"] is False
    assert manifest["runtime_change_permitted"] is False
    assert manifest["holdout_accessed"] is False
    assert manifest["production_cutover_permitted"] is False
    assert manifest["next_boundary"] == NEXT_BOUNDARY
    assert all(manifest["checks"].values())


def test_committed_design_is_integrity_bound() -> None:
    design = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
    normalized = validate_extended_shadow_review_design(design)
    assert normalized["design_hash"] == design["design_hash"]

    drift = deepcopy(design)
    drift["decision_boundary"]["cutover_execution_permitted"] = True
    with pytest.raises(ExtendedShadowReviewError):
        validate_extended_shadow_review_design(drift)

    identity = deepcopy(design)
    identity["status"] = "DRAFT"
    with pytest.raises(ExtendedShadowReviewError):
        validate_extended_shadow_review_design(identity)

    stale = deepcopy(design)
    stale["design_id"] += "-copy"
    with pytest.raises(ExtendedShadowReviewError) as raised:
        validate_extended_shadow_review_design(stale)
    assert raised.value.error_code == "CX_EXTENDED_SHADOW_REVIEW_INTEGRITY"


def test_source_report_integrity_and_exact_binding_fail_closed() -> None:
    report = _report()
    design = _design(report)
    report["live_execution"]["sample_count"] = 29
    with pytest.raises(ExtendedShadowReviewError) as raised:
        build_extended_shadow_operator_decision(
            operator_id="operator-one",
            decided_at="2026-11-06T12:00:00Z",
            design=design,
            source_report=report,
        )
    assert raised.value.error_code == "CX_EXTENDED_SHADOW_REVIEW_INTEGRITY"

    report = _report()
    design = _design(report)
    rebound = deepcopy(report)
    rebound["live_execution"]["elapsed_seconds"] = 88.0
    rebound["evidence_hash"] = _semantic_hash_without(rebound, "evidence_hash")
    with pytest.raises(ExtendedShadowReviewError) as raised:
        build_extended_shadow_operator_decision(
            operator_id="operator-one",
            decided_at="2026-11-06T12:00:00Z",
            design=design,
            source_report=rebound,
        )
    assert raised.value.error_code == "CX_EXTENDED_SHADOW_REVIEW_INTEGRITY"

    malformed = _report()
    malformed.pop("source_operator_decision")
    with pytest.raises(ExtendedShadowReviewError):
        build_extended_shadow_operator_decision(
            operator_id="operator-one",
            decided_at="2026-11-06T12:00:00Z",
            design=_design(_report()),
            source_report=malformed,
        )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda report: report["live_execution"].update(provider_p95_latency_ms=15000.1),
        lambda report: report["live_execution"].update(e2e_p95_latency_ms=20000.1),
        lambda report: report["live_execution"].update(peak_in_flight=3),
        lambda report: report["window"].update(remaining_provider_samples=1),
        lambda report: report["checks"].update(zero_provider_failures=False),
        lambda report: report.update(test_database_residue_rows=1),
        lambda report: report["source_operator_decision"].update(
            decision_status="EXECUTED"
        ),
        lambda report: report["continuation_authorization"].update(
            decision_receipt_hash="sha256:" + "0" * 64
        ),
    ],
)
def test_review_semantic_failures_are_rejected(mutate) -> None:
    report = _report()
    mutate(report)
    design = _bind_report(_base_design(), report)
    with pytest.raises(ExtendedShadowReviewError) as raised:
        build_extended_shadow_operator_decision(
            operator_id="operator-one",
            decided_at="2026-11-06T12:00:00Z",
            design=design,
            source_report=report,
        )
    assert raised.value.error_code == "CX_EXTENDED_SHADOW_REVIEW_INVALID"


def test_malformed_metrics_and_operator_tamper_fail_closed() -> None:
    report = _report()
    report["live_execution"]["elapsed_seconds"] = True
    with pytest.raises(ExtendedShadowReviewError):
        build_extended_shadow_operator_decision(
            operator_id="operator-one",
            decided_at="2026-11-06T12:00:00Z",
            design=_bind_report(_base_design(), report),
            source_report=report,
        )

    report = _report()
    design = _design(report)
    decision = build_extended_shadow_operator_decision(
        operator_id="operator-one",
        decided_at="2026-11-06T12:00:00Z",
        design=design,
        source_report=report,
    )
    decision["cutover_executed"] = True
    decision["decision_hash"] = _semantic_hash_without(decision, "decision_hash")
    with pytest.raises(ExtendedShadowReviewError):
        decide_extended_shadow_review(
            design=design,
            source_report=report,
            operator_decision=decision,
        )

    decision = build_extended_shadow_operator_decision(
        operator_id="operator-one",
        decided_at="2026-11-06T12:00:00Z",
        design=design,
        source_report=report,
    )
    decision["operator_id"] = "tampered"
    with pytest.raises(ExtendedShadowReviewError) as raised:
        decide_extended_shadow_review(
            design=design,
            source_report=report,
            operator_decision=decision,
        )
    assert raised.value.error_code == "CX_EXTENDED_SHADOW_REVIEW_INTEGRITY"


def test_text_timestamp_hash_and_mapping_guards() -> None:
    report = _report()
    design = _design(report)
    with pytest.raises(ExtendedShadowReviewError):
        build_extended_shadow_operator_decision(
            operator_id=" ",
            decided_at="2026-11-06T12:00:00Z",
            design=design,
            source_report=report,
        )
    with pytest.raises(ExtendedShadowReviewError):
        _timestamp("2026-11-06T12:00:00", "timestamp")
    with pytest.raises(ExtendedShadowReviewError):
        _timestamp("badZ", "timestamp")
    with pytest.raises(ExtendedShadowReviewError):
        _hash_ref(None, "hash")
    with pytest.raises(ExtendedShadowReviewError):
        _hash_ref("bad", "hash")
    with pytest.raises(ExtendedShadowReviewError):
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
        "checks": {
            name: True
            for name in (
                "activation_bundle_binding_verified",
                "all_limited_samples_observed",
                "bounded_c4_profile_preserved",
                "e2e_p95_slo_preserved",
                "exact_provider_sample_cap_observed",
                "fresh_window_marker_verified",
                "limited_policy_integrity_verified",
                "operator_continuation_bound",
                "operator_review_required",
                "post_cap_request_provider_blocked",
                "primary_policy_unchanged",
                "production_cutover_prohibited",
                "provider_p95_slo_preserved",
                "raw_text_projection_prohibited",
                "restart_sample_cap_preserved",
                "zero_provider_failures",
            )
        },
        "continuation_authorization": {
            "decision_receipt_hash": (
                "sha256:fae6534f558766d59f5eab53084cbc9e"
                "479f0de619bc30529ccba611f89988af"
            ),
            "operator_decision_hash": (
                "sha256:bb7c3a3c077fa3471c2b84e83ad1a698"
                "e9246aa2662b96ae7b1468376a7ac510"
            ),
            "review_design_hash": (
                "sha256:f92c6d8e96b194383b19f9a9308696a2"
                "e29a833e2838be8c04dab492653477f9"
            ),
            "source_evidence_hash": "sha256:" + "1" * 64,
            "source_report_document_hash": "sha256:" + "2" * 64,
        },
        "database_profile": "test",
        "decision": "EXTENDED_LIMITED_SHADOW_RUNTIME_OPERATIONS_ACCEPTED",
        "evidence_schema_version": (
            "gb2_s20qpad_extended_limited_shadow_operations.v1"
        ),
        "failed_checks": [],
        "holdout_accessed": False,
        "live_execution": {
            "e2e_p95_latency_ms": 11024.212,
            "elapsed_seconds": 87.437285,
            "peak_in_flight": 4,
            "provider_call_count": 30,
            "provider_p95_latency_ms": 10999.170554,
            "sample_count": 30,
            "wave_concurrency": 4,
            "wave_count": 8,
        },
        "next_boundary": "EXTENDED_LIMITED_SHADOW_OPERATOR_REVIEW_DECISION",
        "operations_policy_hash": (
            "sha256:c273eb6078573d96fb8bb25fb8478524a61c0020bf570c342c451ea1a3baa3d3"
        ),
        "operations_status": "REVIEW_REQUIRED",
        "production_cutover_permitted": False,
        "slice_id": "GB2-CA00-S20Q-P-AD",
        "source_operator_decision": {
            "decision": "CONTINUE_LIMITED_SHADOW_OBSERVATION_APPROVED",
            "decision_receipt_document_hash": "sha256:" + "3" * 64,
            "decision_receipt_hash": (
                "sha256:fae6534f558766d59f5eab53084cbc9e"
                "479f0de619bc30529ccba611f89988af"
            ),
            "decision_status": "APPROVED_NOT_EXECUTED",
            "operator_decision_hash": (
                "sha256:bb7c3a3c077fa3471c2b84e83ad1a698"
                "e9246aa2662b96ae7b1468376a7ac510"
            ),
        },
        "status": "PASS",
        "test_database_residue_rows": 0,
        "user_visible_decision_change": False,
        "window": {
            "maximum_provider_samples": 30,
            "minimum_operator_review_samples": 30,
            "policy_hash": (
                "sha256:c273eb6078573d96fb8bb25fb8478524a61c0020bf570c342c451ea1a3baa3d3"
            ),
            "provider_sample_count": 30,
            "remaining_provider_samples": 0,
            "sample_cap_reached": True,
            "window_id": "s20qpad-extended-limited-shadow-window-v1",
        },
        "window_id": "s20qpad-extended-limited-shadow-window-v1",
    }
    report["evidence_hash"] = semantic_sha256_hash_ref(report)
    return report
