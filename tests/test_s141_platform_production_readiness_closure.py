from __future__ import annotations

from pathlib import Path

import run_s141_platform_production_readiness_closure as closure


def test_repository_closure_passes_and_hands_off_to_s142() -> None:
    result = closure.run_s141_platform_production_readiness_closure()

    assert result["status"] == "PASS", result
    assert result["closure_readiness"] == "READY_FOR_S142"
    assert result["failed_checks"] == []
    assert all(result["checks"].values())
    assert result["summary"] == {
        "audit_count": 9,
        "passed_audit_count": 9,
        "check_count": 16,
        "passed_check_count": 16,
        "deferral_count": 9,
        "nonproduction_path_count": 9,
        "configuration_gap_count": 10,
        "operational_gap_count": 12,
        "transition_requirement_count": 9,
        "evidence_field_count": 20,
    }
    assert result["decision"] == {
        "production_deployment_approved": False,
        "production_resources_contacted": False,
        "s140_release_candidate_retained": True,
        "full_gate_registered": True,
        "next_requirement": "S142",
        "next_requirement_scope": (
            "reproducible_deployment_packaging_and_environment_topology"
        ),
    }


def test_closure_fails_closed_for_empty_repository(tmp_path: Path) -> None:
    result = closure.run_s141_platform_production_readiness_closure(tmp_path)

    assert result["status"] == "FAIL"
    assert result["closure_readiness"] == "BLOCKED"
    assert result["summary"]["audit_count"] == 0
    assert result["decision"]["full_gate_registered"] is False
    assert result["decision"]["next_requirement"] == "blocked"
    assert result["failed_checks"]


def test_helpers_cover_mapping_text_and_noncanonical_root(tmp_path: Path) -> None:
    assert closure._mapping({"ok": True}) == {"ok": True}
    assert closure._mapping(None) == {}
    assert closure._run_evidence(tmp_path) == {}

    source = tmp_path / "source.md"
    source.write_text("content", encoding="utf-8")
    assert closure._read_text(source) == "content"
    assert closure._read_text(tmp_path / "missing.md") == ""


def test_summary_and_main_branches(monkeypatch, capsys) -> None:
    passing = {
        "status": "PASS",
        "summary": {
            "passed_audit_count": 9,
            "audit_count": 9,
            "deferral_count": 9,
            "nonproduction_path_count": 9,
            "configuration_gap_count": 10,
            "operational_gap_count": 12,
            "transition_requirement_count": 9,
            "evidence_field_count": 20,
        },
        "decision": {"next_requirement": "S142"},
    }
    assert closure.summary_line(passing) == (
        "s141_platform_production_readiness_closure=pass audits=9/9 "
        "deferrals=9 paths=9 config_gaps=10 operations=12 requirements=9 "
        "fields=20 next=S142"
    )
    failing = {"status": "FAIL", "failed_checks": ["one"]}
    assert closure.summary_line(failing) == (
        "s141_platform_production_readiness_closure=fail checks=1"
    )

    monkeypatch.setattr(
        closure,
        "run_s141_platform_production_readiness_closure",
        lambda: passing,
    )
    assert closure.main(["--summary"]) == 0
    assert "next=S142" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        closure,
        "run_s141_platform_production_readiness_closure",
        lambda: failing,
    )
    assert closure.main([]) == 1
