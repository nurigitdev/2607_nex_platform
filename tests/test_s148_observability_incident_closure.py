from __future__ import annotations

import json
from pathlib import Path

import run_s148_observability_incident_closure as closure


def test_s148_closure_passes_with_repository_evidence() -> None:
    result = closure.run_observability_incident_closure()

    assert result["status"] == "PASS"
    assert result["closure_readiness"] == "READY_FOR_S149"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "audit_count": 8,
        "passed_audit_count": 8,
        "check_count": 14,
        "passed_check_count": 14,
        "openapi_path_count": 6,
        "alert_table_count": 3,
    }
    assert result["decision"] == {
        "observability_framework_complete": True,
        "protected_postgres_evidence_complete": True,
        "external_incident_endpoint_activated": False,
        "external_acceptance": "MOCK_ACCEPTED",
        "external_activation": "EXTERNAL_NOT_ACTIVATED",
        "s149_rehearsal_ready": True,
        "s149_external_delivery_dependency_open": True,
        "production_deployment_approved": False,
        "next_requirement": "S149",
    }


def test_s148_closure_fails_closed_for_missing_repository(tmp_path: Path) -> None:
    result = closure.run_observability_incident_closure(tmp_path)

    assert result["status"] == "FAIL"
    assert result["closure_readiness"] == "BLOCKED"
    assert result["audit_statuses"] == {}
    assert result["decision"]["next_requirement"] == "blocked"
    assert result["failed_checks"]
    assert closure._run_audits(tmp_path) == {}
    assert closure._read_text(tmp_path / "missing.md") == ""


def test_s148_closure_summary_and_cli(monkeypatch, capsys) -> None:
    passing = closure.run_observability_incident_closure()
    assert closure.summary_line(passing) == (
        "s148_observability_incident_closure=pass audits=8/8 checks=14/14 "
        "paths=6 tables=3 external=EXTERNAL_NOT_ACTIVATED next=S149"
    )
    monkeypatch.setattr(
        closure, "run_observability_incident_closure", lambda: passing
    )
    assert closure.main(["--summary"]) == 0
    assert "audits=8/8" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    failing = {"status": "FAIL", "failed_checks": ["drift"]}
    assert closure.summary_line(failing) == (
        "s148_observability_incident_closure=fail checks=1"
    )
    monkeypatch.setattr(
        closure, "run_observability_incident_closure", lambda: failing
    )
    assert closure.main(["--summary"]) == 1
    assert "closure=fail" in capsys.readouterr().out
