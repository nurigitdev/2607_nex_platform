from __future__ import annotations

import pytest

import run_ag_operator_review_escalation_dispatch_daemon_api_admission_guard_evidence as admission


def test_dispatch_daemon_api_admission_guard_evidence_passes() -> None:
    evidence = (
        admission.run_ag_operator_review_escalation_dispatch_daemon_api_admission_guard_evidence()
    )

    assert evidence["status"] == "PASS"
    assert evidence["admission_schema_version"] == admission.SCHEMA_VERSION
    assert evidence["slice"] == "0759"
    assert evidence["scenario_count"] == 6
    assert evidence["accepted_count"] == 2
    assert evidence["rejected_count"] == 4
    assert evidence["mutating_success_names"] == ["tick_once_confirmed"]
    assert all(evidence["checks"].values())
    assert all(item["status_code_ok"] for item in evidence["scenarios"])
    assert all(item["error_code_ok"] for item in evidence["scenarios"])
    assert "mutation_only_confirmed=True" in admission.summary_line(evidence)


def test_dispatch_daemon_api_admission_guard_scenarios_preserve_mutation_boundary() -> (
    None
):
    evidence = (
        admission.run_ag_operator_review_escalation_dispatch_daemon_api_admission_guard_evidence()
    )
    scenarios = {item["name"]: item for item in evidence["scenarios"]}

    assert scenarios["tick_once_missing_confirm"]["status_code"] == 409
    assert scenarios["tick_once_missing_confirm"]["mutation_observed"] is False
    assert scenarios["tick_once_disabled"]["error_code"].endswith("daemon_disabled")
    assert scenarios["tick_once_dry_run"]["status_code"] == 200
    assert scenarios["tick_once_dry_run"]["summary_mutation_performed"] is False
    assert scenarios["tick_once_confirmed"]["status_code"] == 200
    assert scenarios["tick_once_confirmed"]["after_dispatch_status"] == "SUCCEEDED"
    assert scenarios["tick_once_confirmed"]["mutation_observed"] is True


def test_dispatch_daemon_api_admission_guard_detects_sensitive_values() -> None:
    payload = {
        "nested": {
            "database_url": admission.SENSITIVE_VALUES["database_url"],
            "safe": True,
        }
    }

    assert admission._forbidden_labels(payload) == [
        "database_password",
        "database_url",
    ]
    assert admission._forbidden_labels({"safe": True}) == []


def test_dispatch_daemon_api_admission_guard_reports_failed_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = admission.SCENARIOS[0]
    bad = admission.AdmissionScenario(
        name=original.name,
        method=original.method,
        path=original.path,
        include_auth=original.include_auth,
        params=original.params,
        payload_name=original.payload_name,
        expected_status_code=200,
        expected_error_code=None,
        expected_mutation=True,
    )
    monkeypatch.setattr(admission, "SCENARIOS", (bad,))

    evidence = (
        admission.run_ag_operator_review_escalation_dispatch_daemon_api_admission_guard_evidence()
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["expected_status_codes"] is False
    assert evidence["checks"]["expected_error_codes"] is False
    assert evidence["checks"]["mutation_expectations_met"] is False
    assert "admission_guard=fail" in admission.summary_line(evidence)


def test_dispatch_daemon_api_admission_guard_main(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        admission,
        "run_ag_operator_review_escalation_dispatch_daemon_api_admission_guard_evidence",
        lambda: {
            "status": "PASS",
            "scenario_count": 6,
            "rejected_count": 4,
            "checks": {
                "mutation_only_after_confirmed_tick": True,
                "sensitive_values_absent": True,
            },
        },
    )

    assert admission.main(["--summary"]) == 0
    assert "admission_guard=pass" in capsys.readouterr().out

    assert admission.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        admission,
        "run_ag_operator_review_escalation_dispatch_daemon_api_admission_guard_evidence",
        lambda: {"status": "FAIL", "failure_code": "boom"},
    )
    assert admission.main(["--summary"]) == 1
