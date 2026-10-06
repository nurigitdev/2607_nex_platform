from __future__ import annotations

import json
from pathlib import Path

import run_ae_web_viewport_accessibility_acceptance as acceptance


def test_repository_viewport_accessibility_acceptance_is_ready() -> None:
    result = acceptance.run_ae_web_viewport_accessibility_acceptance()

    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["summary"] == {
        "viewport_count": 2,
        "required_region_count": 9,
        "non_overlap_pair_count": 5,
        "minimum_control_target_px": 24,
        "issue_count": 0,
    }
    assert result["decision"]["actual_browser_required_next"] is True
    assert result["decision"]["next_slice"] == "1389"


def test_viewport_accessibility_acceptance_fails_without_repo(
    tmp_path: Path,
) -> None:
    result = acceptance.run_ae_web_viewport_accessibility_acceptance(tmp_path)

    assert result["status"] == "FAIL"
    assert result["viewport_accessibility_readiness"] == "BLOCKED"
    assert result["issues"]
    assert result["decision"]["next_slice"] == "blocked"


def test_viewport_accessibility_helpers_and_cli(monkeypatch, tmp_path, capsys) -> None:
    source = tmp_path / "source.js"
    source.write_text("desktop", encoding="utf-8")
    assert acceptance._read_text(source) == "desktop"
    assert acceptance._read_text(tmp_path / "missing") == ""
    assert acceptance.summary_line({"status": "FAIL", "issues": [1]}) == (
        "ae_web_viewport_accessibility=fail issues=1"
    )

    passing = acceptance.run_ae_web_viewport_accessibility_acceptance()
    monkeypatch.setattr(
        acceptance,
        "run_ae_web_viewport_accessibility_acceptance",
        lambda: passing,
    )
    assert acceptance.main(["--summary"]) == 0
    assert "next=1389" in capsys.readouterr().out
    assert acceptance.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        acceptance,
        "run_ae_web_viewport_accessibility_acceptance",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert acceptance.main([]) == 1
