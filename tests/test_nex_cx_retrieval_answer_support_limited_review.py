from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from nex_cx.retrieval_answer_support_limited_review import (
    APPROVED_SCOPE,
    DECISION,
    NEXT_BOUNDARY,
    LimitedShadowReviewError,
    _hash_ref,
    _mapping,
    _timestamp,
    build_limited_shadow_operator_decision,
    decide_limited_shadow_review,
    validate_limited_shadow_review_design,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = (
    ROOT
    / "scripts/smoke/data/s136_answer_support_limited_shadow_review_v1_design.json"
)


def test_operator_review_approves_only_an_unexecuted_second_window() -> None:
    report = _report()
    design = _design(report)
    decision = build_limited_shadow_operator_decision(
        operator_id="operator-one",
        decided_at="2026-11-05T12:00:00Z",
        design=design,
        source_report=report,
    )

    manifest = decide_limited_shadow_review(
        design=design,
        source_report=report,
        operator_decision=decision,
    )

    assert manifest["status"] == "PASS"
    assert manifest["decision"] == DECISION
    assert manifest["approved_scope"] == APPROVED_SCOPE
    assert manifest["next_window"] == {
        "maximum_provider_samples": 30,
        "maximum_concurrency": 4,
        "fresh_window_policy_required": True,
        "execution_permitted": False,
    }
    assert manifest["observed_metrics"]["sample_count"] == 12
    assert manifest["observed_metrics"]["provider_p95_latency_ms"] == 10987.585349
    assert manifest["continuation_decision_permitted"] is True
    assert manifest["continuation_execution_permitted"] is False
    assert manifest["holdout_accessed"] is False
    assert manifest["production_cutover_permitted"] is False
    assert manifest["next_boundary"] == NEXT_BOUNDARY
    assert all(manifest["checks"].values())


def test_committed_design_is_integrity_bound() -> None:
    design = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
    normalized = validate_limited_shadow_review_design(design)
    assert normalized["design_hash"] == design["design_hash"]

    drift = deepcopy(design)
    drift["continuation_boundary"]["next_window_maximum_provider_samples"] = 31
    with pytest.raises(LimitedShadowReviewError) as raised:
        validate_limited_shadow_review_design(drift)
    assert raised.value.error_code in {
        "CX_LIMITED_SHADOW_REVIEW_INVALID",
        "CX_LIMITED_SHADOW_REVIEW_INTEGRITY",
    }

    identity = deepcopy(design)
    identity["status"] = "DRAFT"
    with pytest.raises(LimitedShadowReviewError):
        validate_limited_shadow_review_design(identity)

    stale = deepcopy(design)
    stale["design_id"] = "cx-answer-support-limited-shadow-operator-review-v1-copy"
    with pytest.raises(LimitedShadowReviewError) as raised:
        validate_limited_shadow_review_design(stale)
    assert raised.value.error_code == "CX_LIMITED_SHADOW_REVIEW_INTEGRITY"


def test_source_report_integrity_binding_and_fields_fail_closed() -> None:
    report = _report()
    design = _design(report)
    drift = deepcopy(report)
    drift["live_execution"]["sample_count"] = 11
    with pytest.raises(LimitedShadowReviewError) as raised:
        build_limited_shadow_operator_decision(
            operator_id="operator-one",
            decided_at="2026-11-05T12:00:00Z",
            design=design,
            source_report=drift,
        )
    assert raised.value.error_code == "CX_LIMITED_SHADOW_REVIEW_INTEGRITY"

    rebound = deepcopy(report)
    rebound["live_execution"]["elapsed_seconds"] = 33.0
    rebound["evidence_hash"] = _semantic_hash_without(rebound, "evidence_hash")
    with pytest.raises(LimitedShadowReviewError) as raised:
        build_limited_shadow_operator_decision(
            operator_id="operator-one",
            decided_at="2026-11-05T12:00:00Z",
            design=design,
            source_report=rebound,
        )
    assert raised.value.error_code == "CX_LIMITED_SHADOW_REVIEW_INTEGRITY"

    malformed = deepcopy(report)
    malformed.pop("window")
    with pytest.raises(LimitedShadowReviewError):
        build_limited_shadow_operator_decision(
            operator_id="operator-one",
            decided_at="2026-11-05T12:00:00Z",
            design=design,
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
        lambda report: report["window"].update(remaining_provider_samples=1),
        lambda report: report["checks"].update(restart_sample_cap_preserved=False),
        lambda report: report.update(test_database_residue_rows=1),
    ],
)
def test_review_semantic_failures_are_rejected(mutate) -> None:
    report = _report()
    mutate(report)
    design = _bind_report(_base_design(), report)
    with pytest.raises(LimitedShadowReviewError) as raised:
        build_limited_shadow_operator_decision(
            operator_id="operator-one",
            decided_at="2026-11-05T12:00:00Z",
            design=design,
            source_report=report,
        )
    assert raised.value.error_code == "CX_LIMITED_SHADOW_REVIEW_INVALID"


def test_malformed_metrics_and_operator_tamper_fail_closed() -> None:
    report = _report()
    report["live_execution"]["elapsed_seconds"] = True
    design = _bind_report(_base_design(), report)
    with pytest.raises(LimitedShadowReviewError):
        build_limited_shadow_operator_decision(
            operator_id="operator-one",
            decided_at="2026-11-05T12:00:00Z",
            design=design,
            source_report=report,
        )

    report = _report()
    design = _design(report)
    decision = build_limited_shadow_operator_decision(
        operator_id="operator-one",
        decided_at="2026-11-05T12:00:00Z",
        design=design,
        source_report=report,
    )
    decision["continuation_executed"] = True
    decision["decision_hash"] = _semantic_hash_without(decision, "decision_hash")
    with pytest.raises(LimitedShadowReviewError):
        decide_limited_shadow_review(
            design=design,
            source_report=report,
            operator_decision=decision,
        )

    decision = build_limited_shadow_operator_decision(
        operator_id="operator-one",
        decided_at="2026-11-05T12:00:00Z",
        design=design,
        source_report=report,
    )
    decision["operator_id"] = "tampered"
    with pytest.raises(LimitedShadowReviewError) as raised:
        decide_limited_shadow_review(
            design=design,
            source_report=report,
            operator_decision=decision,
        )
    assert raised.value.error_code == "CX_LIMITED_SHADOW_REVIEW_INTEGRITY"


def test_text_timestamp_and_hash_guards_reject_invalid_values() -> None:
    report = _report()
    design = _design(report)
    with pytest.raises(LimitedShadowReviewError):
        build_limited_shadow_operator_decision(
            operator_id=" ",
            decided_at="2026-11-05T12:00:00Z",
            design=design,
            source_report=report,
        )
    with pytest.raises(LimitedShadowReviewError):
        _timestamp("2026-11-05T12:00:00", "timestamp")
    with pytest.raises(LimitedShadowReviewError):
        _timestamp("not-a-timeZ", "timestamp")
    with pytest.raises(LimitedShadowReviewError):
        _hash_ref(None, "hash")
    with pytest.raises(LimitedShadowReviewError):
        _hash_ref("bad", "hash")
    with pytest.raises(LimitedShadowReviewError):
        _mapping([], "mapping")


def _base_design() -> dict[str, Any]:
    return json.loads(DESIGN_PATH.read_text(encoding="utf-8"))


def _design(report: dict[str, Any]) -> dict[str, Any]:
    return _bind_report(_base_design(), report)


def _bind_report(design: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    report["evidence_hash"] = _semantic_hash_without(report, "evidence_hash")
    design["source_binding"]["source_evidence_hash"] = report["evidence_hash"]
    design["source_binding"]["source_report_document_hash"] = (
        semantic_sha256_hash_ref(report)
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
            "sha256:6d5c631c9e18418ae2787d4053d06cdf"
            "87cc49a3cbc67aea6258b11f29893a06"
        ),
        "checks": {name: True for name in (
            "activation_bundle_binding_verified",
            "all_limited_samples_observed",
            "bounded_c4_profile_preserved",
            "exact_provider_sample_cap_observed",
            "limited_policy_integrity_verified",
            "operator_review_required",
            "primary_policy_unchanged",
            "production_cutover_prohibited",
            "raw_text_projection_prohibited",
            "restart_sample_cap_preserved",
            "thirteenth_request_provider_blocked",
        )},
        "database_profile": "test",
        "decision": "LIMITED_SHADOW_RUNTIME_OPERATIONS_ACCEPTED",
        "evidence_schema_version": "gb2_s20qpab_limited_shadow_operations.v1",
        "failed_checks": [],
        "holdout_accessed": False,
        "live_execution": {
            "e2e_p95_latency_ms": 11012.279,
            "elapsed_seconds": 32.773598,
            "peak_in_flight": 4,
            "provider_call_count": 12,
            "provider_p95_latency_ms": 10987.585349,
            "sample_count": 12,
            "wave_concurrency": 4,
            "wave_count": 3,
        },
        "next_boundary": "LIMITED_SHADOW_OPERATOR_REVIEW_DECISION",
        "operations_policy_hash": (
            "sha256:f47aef621065761e4b04b082e61f95e7"
            "50f9647e26fd0b3bf175d8ef40db5d82"
        ),
        "operations_status": "REVIEW_REQUIRED",
        "production_cutover_permitted": False,
        "slice_id": "GB2-CA00-S20Q-P-AB",
        "status": "PASS",
        "test_database_residue_rows": 0,
        "user_visible_decision_change": False,
        "window": {
            "maximum_provider_samples": 12,
            "minimum_operator_review_samples": 12,
            "policy_hash": (
                "sha256:f47aef621065761e4b04b082e61f95e7"
                "50f9647e26fd0b3bf175d8ef40db5d82"
            ),
            "provider_sample_count": 12,
            "remaining_provider_samples": 0,
            "sample_cap_reached": True,
            "window_id": "s20qpab-limited-shadow-window-v1",
        },
        "window_id": "s20qpab-limited-shadow-window-v1",
    }
    report["evidence_hash"] = semantic_sha256_hash_ref(report)
    return report
