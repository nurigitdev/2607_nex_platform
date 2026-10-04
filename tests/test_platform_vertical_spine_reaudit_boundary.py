from __future__ import annotations

from pathlib import Path

import run_platform_vertical_spine_reaudit_boundary as audit


def test_boundary_audit_passes_for_repository() -> None:
    result = audit.run_platform_vertical_spine_reaudit_boundary()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["decision"]["audit_scope"] == (
        "oa_to_ae_web_api_to_cx_to_mo_to_ag"
    )
    assert result["decision"]["cross_service_http_api_only"] is True
    assert result["decision"]["shared_database_reads_allowed"] is False
    assert result["decision"]["next_requirement"] == "S132"
    assert result["baseline_findings"]["backend_service_shell_count"] == 5
    assert result["baseline_findings"]["golden_scenario_contract_count"] == 10
    assert result["baseline_findings"][
        "executable_named_golden_scenario_count"
    ] == 0
    assert len(result["audit_surfaces"]) == 8
    assert len(result["slice_plan"]) == 10
    assert result["quality_cadence"]["checkpoint_gate"] == "1306"
    assert result["quality_cadence"]["full_gate"] == "1311"


def test_boundary_audit_reports_missing_paths_and_tokens(tmp_path: Path) -> None:
    result = audit.run_platform_vertical_spine_reaudit_boundary(tmp_path)

    assert result["status"] == "FAIL"
    assert result["checks"] == {
        "required_paths_present": False,
        "required_tokens_present": False,
        "s130_handoff_ready": False,
        "five_service_and_web_entries_present": False,
        "requirements_and_golden_scenarios_frozen": False,
    }
    assert any(item["category"] == "path_missing" for item in result["issues"])
    assert any(
        item["category"] == "source_token_missing" for item in result["issues"]
    )


def test_executable_golden_scenario_inventory(tmp_path: Path) -> None:
    tests = tmp_path / "tests"
    scripts = tmp_path / "scripts"
    tests.mkdir()
    scripts.mkdir()
    (tests / "test_flow.py").write_text(
        "GEN-E2E-001 GEN-E2E-010", encoding="utf-8"
    )
    (scripts / "flow.sh").write_text("GEN-E2E-001", encoding="utf-8")
    (scripts / "ignored.txt").write_text("GEN-E2E-002", encoding="utf-8")

    assert audit._executable_golden_scenario_ids(tmp_path) == [
        "GEN-E2E-001",
        "GEN-E2E-010",
    ]


def test_helpers_cover_missing_text_and_groups(tmp_path: Path) -> None:
    present = tmp_path / "present.txt"
    present.write_text("content", encoding="utf-8")
    items = [
        {"group": "ready", "present": True},
        {"group": "blocked", "present": False},
    ]

    assert audit._read_text(present) == "content"
    assert audit._read_text(tmp_path / "missing.txt") == ""
    assert audit._group_present(items, "ready") is True
    assert audit._group_present(items, "blocked") is False
    assert audit._group_present(items, "missing") is False


def test_summary_line_reports_pass_and_failure() -> None:
    passing = {
        "status": "PASS",
        "decision": {
            "audit_scope": "oa_to_ae_web_api_to_cx_to_mo_to_ag",
            "actual_test_database_evidence_required": False,
            "protected_live_provider_evidence_required": False,
            "next_requirement": "S132",
        },
        "baseline_findings": {
            "backend_service_shell_count": 5,
            "executable_named_golden_scenario_count": 0,
        },
    }

    assert audit.summary_line(passing) == (
        "platform_vertical_spine_reaudit_boundary=pass "
        "scope=oa_to_ae_web_api_to_cx_to_mo_to_ag services=5+web "
        "named_e2e=0/10 postgres_required=False live_required=False next=S132"
    )
    assert audit.summary_line({"status": "FAIL", "issues": [1]}) == (
        "platform_vertical_spine_reaudit_boundary=fail issues=1"
    )


def test_main_prints_summary_json_and_failure(monkeypatch, capsys) -> None:
    passing = {
        "status": "PASS",
        "decision": {
            "audit_scope": "spine",
            "actual_test_database_evidence_required": False,
            "protected_live_provider_evidence_required": False,
            "next_requirement": "S132",
        },
        "baseline_findings": {
            "backend_service_shell_count": 5,
            "executable_named_golden_scenario_count": 0,
        },
    }
    monkeypatch.setattr(
        audit,
        "run_platform_vertical_spine_reaudit_boundary",
        lambda: passing,
    )
    assert audit.main(["--summary"]) == 0
    assert "boundary=pass" in capsys.readouterr().out
    assert audit.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        audit,
        "run_platform_vertical_spine_reaudit_boundary",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert audit.main([]) == 1
