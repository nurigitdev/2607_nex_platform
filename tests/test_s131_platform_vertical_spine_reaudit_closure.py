from __future__ import annotations

from pathlib import Path

import run_s131_platform_vertical_spine_reaudit_closure as closure


def test_repository_closure_passes_and_hands_off_to_s132() -> None:
    result = closure.run_s131_platform_vertical_spine_reaudit_closure()

    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["failed_checks"] == []
    assert result["summary"] == {
        "audit_count": 9,
        "passed_audit_count": 9,
        "check_count": 11,
        "passed_check_count": 11,
        "http_edge_count": 11,
        "migration_count": 95,
        "trace_client_count": 13,
        "p0_gap_count": 8,
        "p1_gap_count": 4,
        "named_e2e_count": 10,
    }
    assert result["decision"]["service_ownership_model_retained"] is True
    assert result["decision"]["current_vertical_spine_is_release_accepted"] is False
    assert result["decision"]["next_requirement"] == "S132"


def test_closure_fails_closed_for_empty_repository(tmp_path: Path) -> None:
    result = closure.run_s131_platform_vertical_spine_reaudit_closure(tmp_path)

    assert result["status"] == "FAIL"
    assert result["failed_checks"]
    assert result["decision"]["next_requirement"] == "blocked"


def test_helpers_cover_mapping_finding_and_text_branches(tmp_path: Path) -> None:
    evidence = {"findings": {"count": 3}}
    assert closure._finding(evidence, "count") == 3
    assert closure._finding(evidence, "missing", 7) == 7
    assert closure._finding({}, "missing", 8) == 8
    assert closure._mapping({"ok": True}) == {"ok": True}
    assert closure._mapping(None) == {}

    path = tmp_path / "source.md"
    path.write_text("content", encoding="utf-8")
    assert closure._read_text(path) == "content"
    assert closure._read_text(tmp_path / "missing.md") == ""


def test_summary_and_main_branches(monkeypatch, capsys) -> None:
    passing = {
        "status": "PASS",
        "summary": {
            "passed_audit_count": 9,
            "audit_count": 9,
            "passed_check_count": 11,
            "check_count": 11,
            "http_edge_count": 11,
            "migration_count": 90,
            "named_e2e_count": 10,
        },
        "decision": {"next_requirement": "S132"},
    }
    assert closure.summary_line(passing) == (
        "s131_platform_vertical_spine_reaudit_closure=pass audits=9/9 "
        "checks=11/11 edges=11 migrations=90 named_e2e=10/10 next=S132"
    )
    assert closure.summary_line(
        {"status": "FAIL", "failed_checks": ["a"]}
    ) == "s131_platform_vertical_spine_reaudit_closure=fail checks=1"

    monkeypatch.setattr(
        closure,
        "run_s131_platform_vertical_spine_reaudit_closure",
        lambda: passing,
    )
    assert closure.main(["--summary"]) == 0
    assert "next=S132" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        closure,
        "run_s131_platform_vertical_spine_reaudit_closure",
        lambda: {"status": "FAIL", "failed_checks": []},
    )
    assert closure.main([]) == 1
