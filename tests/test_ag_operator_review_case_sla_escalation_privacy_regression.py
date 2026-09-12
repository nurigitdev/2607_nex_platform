from __future__ import annotations

import json

import pytest

import run_ag_operator_review_case_sla_escalation_privacy_regression as privacy


def test_ag_operator_review_case_sla_escalation_privacy_regression_passes() -> None:
    evidence = privacy.run_ag_operator_review_case_sla_escalation_privacy_regression()

    assert evidence["audit_schema_version"] == (
        "ag_operator_review_case_sla_escalation_privacy_regression.v1"
    )
    assert evidence["status"] == "PASS"
    assert evidence["failure_code"] is None
    assert evidence["surface_count"] == 4
    assert evidence["fixture"]["covered_surfaces"] == [
        "sla_policy",
        "aging",
        "escalations",
        "dashboard",
    ]
    assert all(evidence["checks"].values())
    assert all(not surface["leak_labels"] for surface in evidence["surfaces"])
    serialized = json.dumps(evidence, sort_keys=True)
    assert privacy.RAW_PROMPT not in serialized
    assert privacy.DATABASE_URL not in serialized


def test_ag_operator_review_case_sla_escalation_privacy_helpers_detect_leaks() -> None:
    assert privacy._leak_labels(
        f"payload {privacy.RAW_PROMPT}",
        privacy.FORBIDDEN_VALUES,
    ) == ["raw_prompt"]
    assert privacy._contains_forbidden_keys(
        {"nested": [{"raw_prompt": "secret"}]},
        privacy.FORBIDDEN_KEYS,
    )
    assert not privacy._contains_forbidden_keys({"safe": ["value"]}, privacy.FORBIDDEN_KEYS)
    assert privacy._redaction_flags_safe(
        {"redaction": {"raw_prompt_included": False}, "items": []}
    )
    assert not privacy._redaction_flags_safe(
        {"redaction": {"raw_prompt_included": True}}
    )


def test_ag_operator_review_case_sla_escalation_privacy_dashboard_guard() -> None:
    safe_dashboard = {
        "operator_review_cases": {
            "sla_aging": {"summary": {"overdue_case_count": 1}},
            "escalations": {"summary": {"candidate_count": 1}},
            "redaction": {"raw_prompt_included": False},
        }
    }
    unsafe_dashboard = {
        "operator_review_cases": {
            "sla_aging": {"summary": {"overdue_case_count": 0}},
            "escalations": {"summary": {"candidate_count": 1}},
        }
    }

    assert privacy._dashboard_sla_summary_safe(safe_dashboard)
    assert not privacy._dashboard_sla_summary_safe(unsafe_dashboard)
    assert not privacy._dashboard_sla_summary_safe({"operator_review_cases": []})


def test_ag_operator_review_case_sla_escalation_privacy_summary_and_evidence_guard(
    capsys: pytest.CaptureFixture[str],
) -> None:
    pass_evidence = privacy.run_ag_operator_review_case_sla_escalation_privacy_regression()
    fail_evidence = {
        **pass_evidence,
        "status": "FAIL",
        "failure_code": "ag_operator_review_case_sla_escalation_privacy_regression_failed",
        "checks": {"first": True, "second": False},
    }

    assert "privacy_regression=pass" in privacy.summary_line(pass_evidence)
    assert "failed_checks=second" in privacy.summary_line(fail_evidence)
    with pytest.raises(ValueError):
        privacy.assert_privacy_evidence_redacted(privacy.RAW_PROMPT)

    assert privacy.main(["--summary"]) == 0
    assert "ag_operator_review_case_sla_escalation_privacy_regression=pass" in (
        capsys.readouterr().out
    )
