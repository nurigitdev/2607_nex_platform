from __future__ import annotations

from pathlib import Path

import run_platform_oa_backed_trust_boundary as boundary


def test_repository_boundary_passes_and_freezes_s134() -> None:
    result = boundary.run_platform_oa_backed_trust_boundary()

    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["findings"] == {
        "service_count": 5,
        "trust_axis_count": 2,
        "current_gap_count": 4,
        "denial_scenario_count": 4,
    }
    assert result["decision"]["default_signer_fail_closed"] is True
    assert result["decision"]["shared_database_allowed"] is False
    assert result["decision"]["remote_provider_required"] is False
    assert result["decision"]["next_slice"] == "1333"


def test_boundary_fails_closed_for_empty_repository(tmp_path: Path) -> None:
    result = boundary.run_platform_oa_backed_trust_boundary(tmp_path)

    assert result["status"] == "FAIL"
    assert result["issues"]
    assert result["checks"]["required_paths_present"] is False


def test_text_summary_and_main_branches(tmp_path: Path, monkeypatch, capsys) -> None:
    source = tmp_path / "source.md"
    source.write_text("content", encoding="utf-8")
    assert boundary._read_text(source) == "content"
    assert boundary._read_text(tmp_path / "missing.md") == ""

    passing = {
        "status": "PASS",
        "findings": {"service_count": 5, "trust_axis_count": 2, "current_gap_count": 4},
        "decision": {"next_slice": "1333"},
    }
    assert boundary.summary_line(passing) == (
        "platform_oa_backed_trust_boundary=pass services=5 trust_axes=2 gaps=4 next=1333"
    )
    assert boundary.summary_line({"status": "FAIL", "issues": [1]}) == (
        "platform_oa_backed_trust_boundary=fail issues=1"
    )

    monkeypatch.setattr(boundary, "run_platform_oa_backed_trust_boundary", lambda: passing)
    assert boundary.main(["--summary"]) == 0
    assert "next=1333" in capsys.readouterr().out
    assert boundary.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(boundary, "run_platform_oa_backed_trust_boundary", lambda: {"status": "FAIL", "issues": []})
    assert boundary.main([]) == 1

