from __future__ import annotations

import json
from pathlib import Path

import run_ae_web_korean_golden_journey_boundary as boundary


def test_repository_boundary_freezes_s139_and_s140_handoff() -> None:
    result = boundary.run_ae_web_korean_golden_journey_boundary()

    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["summary"] == {
        "required_path_count": 12,
        "evidence_token_count": 8,
        "acceptance_gap_count": 8,
        "open_gap_count": 8,
        "focused_playwright_count": 4,
        "viewport_count": 2,
        "missing_path_count": 0,
        "missing_token_count": 0,
    }
    assert result["decision"] == {
        "new_table_required": False,
        "remote_model_provider_required": False,
        "actual_browser_required_now": False,
        "protected_browser_deferred_to_slice": "1390",
        "direct_service_or_database_browser_access_allowed": False,
        "next_slice": "1383",
    }


def test_boundary_fails_closed_for_missing_repository(tmp_path: Path) -> None:
    result = boundary.run_ae_web_korean_golden_journey_boundary(tmp_path)

    assert result["status"] == "FAIL"
    assert result["boundary_readiness"] == "AUDIT_FAILED"
    assert result["issues"]
    assert result["decision"]["next_slice"] == "blocked"


def test_boundary_helpers_and_cli_branches(monkeypatch, tmp_path, capsys) -> None:
    source = tmp_path / "source.md"
    source.write_text("line one\n line two", encoding="utf-8")

    assert boundary._read_text(source) == "line one\n line two"
    assert boundary._normalized_text(source) == "line one line two"
    assert boundary._read_text(tmp_path / "missing.md") == ""
    assert boundary.summary_line({"status": "FAIL", "issues": [1]}) == (
        "ae_web_korean_golden_journey_boundary=fail issues=1"
    )

    passing = boundary.run_ae_web_korean_golden_journey_boundary()
    monkeypatch.setattr(
        boundary,
        "run_ae_web_korean_golden_journey_boundary",
        lambda: passing,
    )
    assert boundary.main(["--summary"]) == 0
    assert "next=1383" in capsys.readouterr().out
    assert boundary.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        boundary,
        "run_ae_web_korean_golden_journey_boundary",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert boundary.main([]) == 1
