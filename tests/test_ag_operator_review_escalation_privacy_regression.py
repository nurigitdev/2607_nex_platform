from __future__ import annotations

import json

import pytest

import run_ag_operator_review_escalation_privacy_regression as privacy


def test_ag_operator_review_escalation_privacy_regression_passes() -> None:
    evidence = privacy.run_ag_operator_review_escalation_privacy_regression()

    assert evidence["audit_schema_version"] == (
        "ag_operator_review_escalation_privacy_regression.v1"
    )
    assert evidence["status"] == "PASS"
    assert evidence["failure_code"] is None
    assert evidence["surface_count"] == 5
    assert evidence["fixture"]["covered_surfaces"] == [
        "escalation_list",
        "escalation_detail",
        "dashboard",
        "issue_candidates",
        "action_mutation",
    ]
    assert all(evidence["checks"].values())
    assert all(not surface["leak_labels"] for surface in evidence["surfaces"])
    serialized = json.dumps(evidence, sort_keys=True)
    assert privacy.RAW_PROMPT not in serialized
    assert privacy.ACTION_IDEMPOTENCY_KEY not in serialized


def test_ag_operator_review_escalation_privacy_helpers_detect_leaks() -> None:
    assert privacy._leak_labels(
        f"payload {privacy.RAW_NOTIFICATION_PAYLOAD}",
        privacy.FORBIDDEN_VALUES,
    ) == ["raw_notification_payload"]
    assert privacy._contains_forbidden_keys(
        {"nested": [{"raw_action_comment": "secret"}]},
        privacy.FORBIDDEN_KEYS,
    )
    assert not privacy._contains_forbidden_keys(
        {"safe": [{"action_comment_hash": "abc"}]},
        privacy.FORBIDDEN_KEYS,
    )
    assert privacy._redaction_flags_safe(
        {"redaction": {"raw_action_comment_included": False}, "items": []}
    )
    assert not privacy._redaction_flags_safe(
        {"redaction": {"raw_action_comment_included": True}}
    )


def test_ag_operator_review_escalation_privacy_surface_guards() -> None:
    safe_dashboard = {
        "operator_review_escalations": {
            "summary": {"escalation_count": 1, "action_required_count": 1},
            "redaction": {"raw_action_comment_included": False},
        }
    }
    unsafe_dashboard = {
        "operator_review_escalations": {
            "summary": {"escalation_count": 1, "action_required_count": 0}
        }
    }
    safe_issue_candidates = {
        "issue_candidates": [
            {
                "rule_id": "operator_review_escalation_action_required.v1",
                "service_id": "nex-ag",
                "signal": {"count": 1},
            }
        ]
    }
    unsafe_issue_candidates = {"issue_candidates": []}

    assert privacy._dashboard_escalation_summary_safe(safe_dashboard)
    assert not privacy._dashboard_escalation_summary_safe(unsafe_dashboard)
    assert not privacy._dashboard_escalation_summary_safe({"operator_review_escalations": []})
    assert privacy._issue_candidate_surface_safe(safe_issue_candidates)
    assert not privacy._issue_candidate_surface_safe(unsafe_issue_candidates)
    assert not privacy._issue_candidate_surface_safe({"issue_candidates": {}})


def test_ag_operator_review_escalation_privacy_summary_and_evidence_guard(
    capsys: pytest.CaptureFixture[str],
) -> None:
    pass_evidence = privacy.run_ag_operator_review_escalation_privacy_regression()
    fail_evidence = {
        **pass_evidence,
        "status": "FAIL",
        "failure_code": "ag_operator_review_escalation_privacy_regression_failed",
        "checks": {"first": True, "second": False},
    }

    assert "privacy_regression=pass" in privacy.summary_line(pass_evidence)
    assert "failed_checks=second" in privacy.summary_line(fail_evidence)
    with pytest.raises(ValueError):
        privacy.assert_privacy_evidence_redacted(privacy.RAW_PROMPT)

    assert privacy.main(["--summary"]) == 0
    assert "ag_operator_review_escalation_privacy_regression=pass" in (
        capsys.readouterr().out
    )
