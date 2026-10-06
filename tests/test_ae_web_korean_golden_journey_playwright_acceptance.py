from __future__ import annotations

import json
from pathlib import Path

import run_ae_web_korean_golden_journey_playwright_acceptance as acceptance


def test_repository_korean_golden_journey_playwright_is_ready() -> None:
    result = acceptance.run_ae_web_korean_golden_journey_playwright_acceptance()

    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["summary"] == {
        "viewport_count": 2,
        "journey_stage_count": 9,
        "ui_action_family_count": 3,
        "artifact_action_count": 2,
        "screenshot_count": 2,
        "issue_count": 0,
    }
    assert result["decision"]["actual_browser"] == "chromium"
    assert result["decision"]["next_slice"] == "1390"


def test_korean_golden_journey_playwright_fails_without_repo(
    tmp_path: Path,
) -> None:
    result = acceptance.run_ae_web_korean_golden_journey_playwright_acceptance(
        tmp_path
    )

    assert result["status"] == "FAIL"
    assert result["playwright_acceptance_readiness"] == "BLOCKED"
    assert result["issues"]
    assert result["decision"]["next_slice"] == "blocked"


def test_korean_golden_journey_helpers_and_cli(monkeypatch, tmp_path, capsys) -> None:
    source = tmp_path / "source.js"
    source.write_text("chromium", encoding="utf-8")
    assert acceptance._read_text(source) == "chromium"
    assert acceptance._read_text(tmp_path / "missing") == ""
    assert acceptance.summary_line({"status": "FAIL", "issues": [1]}) == (
        "ae_web_korean_golden_journey_playwright=fail issues=1"
    )

    passing = acceptance.run_ae_web_korean_golden_journey_playwright_acceptance()
    monkeypatch.setattr(
        acceptance,
        "run_ae_web_korean_golden_journey_playwright_acceptance",
        lambda: passing,
    )
    assert acceptance.main(["--summary"]) == 0
    assert "next=1390" in capsys.readouterr().out
    assert acceptance.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        acceptance,
        "run_ae_web_korean_golden_journey_playwright_acceptance",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert acceptance.main([]) == 1
