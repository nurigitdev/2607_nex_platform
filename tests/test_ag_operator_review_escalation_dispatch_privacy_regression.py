from __future__ import annotations

import json

import pytest

import run_ag_operator_review_escalation_dispatch_privacy_regression as privacy


def test_ag_operator_review_escalation_dispatch_privacy_regression_passes() -> None:
    evidence = privacy.run_ag_operator_review_escalation_dispatch_privacy_regression()

    assert evidence["audit_schema_version"] == (
        "ag_operator_review_escalation_dispatch_privacy_regression.v1"
    )
    assert evidence["status"] == "PASS"
    assert evidence["failure_code"] is None
    assert evidence["surface_count"] == 6
    assert evidence["fixture"]["covered_surfaces"] == [
        "dispatch_plan",
        "dispatch_list",
        "dispatch_detail",
        "dashboard",
        "issue_candidates",
        "action_mutation",
    ]
    assert all(evidence["checks"].values())
    assert all(not surface["leak_labels"] for surface in evidence["surfaces"])
    serialized = json.dumps(evidence, sort_keys=True)
    assert privacy.RAW_PROVIDER_PAYLOAD not in serialized
    assert privacy.DISPATCH_IDEMPOTENCY_KEY not in serialized
    assert privacy.ACTION_IDEMPOTENCY_KEY not in serialized


def test_ag_operator_review_escalation_dispatch_privacy_helpers_detect_leaks() -> None:
    assert privacy._leak_labels(
        f"payload {privacy.RAW_NOTIFICATION_PAYLOAD}",
        privacy.FORBIDDEN_VALUES,
    ) == ["raw_notification_payload"]
    assert privacy._contains_forbidden_keys(
        {"nested": [{"raw_provider_payload": "secret"}]},
        privacy.FORBIDDEN_KEYS,
    )
    assert not privacy._contains_forbidden_keys(
        {"safe": [{"provider_payload_hash": "abc"}]},
        privacy.FORBIDDEN_KEYS,
    )
    assert privacy._redaction_flags_safe(
        {"redaction": {"raw_provider_payload_included": False}, "items": []}
    )
    assert not privacy._redaction_flags_safe(
        {"redaction": {"raw_provider_payload_included": True}}
    )
    assert privacy._created_dispatch_id(
        {"dispatch_record": {"dispatch_id": "dispatch-0709"}}
    ) == "dispatch-0709"
    assert privacy._created_dispatch_id({"dispatch_record": []}) == ""


def test_ag_operator_review_escalation_dispatch_privacy_surface_guards() -> None:
    safe_dashboard = {
        "operator_review_escalation_dispatches": {
            "summary": {"dispatch_count": 1, "attention_count": 1},
            "redaction": {"raw_provider_payload_included": False},
        }
    }
    unsafe_dashboard = {
        "operator_review_escalation_dispatches": {
            "summary": {"dispatch_count": 1, "attention_count": 0}
        }
    }
    safe_issue_candidates = {
        "issue_candidates": [
            {
                "rule_id": "operator_review_escalation_dispatch_attention_required.v1",
                "service_id": "nex-ag",
                "signal": {"count": 1},
            }
        ]
    }
    unsafe_issue_candidates = {"issue_candidates": []}

    assert privacy._dashboard_dispatch_summary_safe(safe_dashboard)
    assert not privacy._dashboard_dispatch_summary_safe(unsafe_dashboard)
    assert not privacy._dashboard_dispatch_summary_safe(
        {"operator_review_escalation_dispatches": []}
    )
    assert not privacy._dashboard_dispatch_summary_safe(
        {"operator_review_escalation_dispatches": {"summary": []}}
    )
    assert privacy._issue_candidate_surface_safe(safe_issue_candidates)
    assert not privacy._issue_candidate_surface_safe(unsafe_issue_candidates)
    assert not privacy._issue_candidate_surface_safe({"issue_candidates": {}})


def test_ag_operator_review_escalation_dispatch_privacy_summary_and_evidence_guard(
    capsys: pytest.CaptureFixture[str],
) -> None:
    pass_evidence = privacy.run_ag_operator_review_escalation_dispatch_privacy_regression()
    fail_evidence = {
        **pass_evidence,
        "status": "FAIL",
        "failure_code": (
            "ag_operator_review_escalation_dispatch_privacy_regression_failed"
        ),
        "checks": {"first": True, "second": False},
    }

    assert "dispatch_privacy_regression=pass" in privacy.summary_line(pass_evidence)
    assert "failed_checks=second" in privacy.summary_line(fail_evidence)
    with pytest.raises(ValueError):
        privacy.assert_privacy_evidence_redacted(privacy.RAW_PROVIDER_PAYLOAD)

    assert privacy.main(["--summary"]) == 0
    assert "ag_operator_review_escalation_dispatch_privacy_regression=pass" in (
        capsys.readouterr().out
    )
