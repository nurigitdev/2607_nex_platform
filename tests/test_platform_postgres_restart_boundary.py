from __future__ import annotations

from pathlib import Path

import run_platform_postgres_restart_boundary as boundary


def test_repository_boundary_passes_and_freezes_s133() -> None:
    result = boundary.run_platform_postgres_restart_boundary()

    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["findings"]["service_count"] == 5
    assert result["findings"]["migration_total"] >= boundary.S133_MIGRATION_BASELINE
    assert result["findings"]["migration_counts"]["nex-ae-api"] >= 23
    assert result["findings"]["integration_gap_count"] == 5
    assert result["decision"]["shared_database_allowed"] is False
    assert result["decision"]["actual_test_databases_required"] is True
    assert result["decision"]["next_slice"] == "1323"


def test_boundary_fails_closed_for_empty_repository(tmp_path: Path) -> None:
    result = boundary.run_platform_postgres_restart_boundary(tmp_path)

    assert result["status"] == "FAIL"
    assert result["issues"]
    assert result["findings"]["migration_total"] == 0


def test_text_summary_and_main_branches(tmp_path: Path, monkeypatch, capsys) -> None:
    source = tmp_path / "source.md"
    source.write_text("content", encoding="utf-8")
    assert boundary._read_text(source) == "content"
    assert boundary._read_text(tmp_path / "missing.md") == ""

    passing = {
        "status": "PASS",
        "findings": {
            "service_count": 5,
            "migration_total": 89,
            "integration_gap_count": 5,
        },
        "decision": {"next_slice": "1323"},
    }
    assert boundary.summary_line(passing) == (
        "platform_postgres_restart_boundary=pass services=5 "
        "migrations=89 gaps=5 next=1323"
    )
    assert boundary.summary_line(
        {"status": "FAIL", "issues": [1]}
    ) == "platform_postgres_restart_boundary=fail issues=1"

    monkeypatch.setattr(
        boundary, "run_platform_postgres_restart_boundary", lambda: passing
    )
    assert boundary.main(["--summary"]) == 0
    assert "next=1323" in capsys.readouterr().out
    assert boundary.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        boundary,
        "run_platform_postgres_restart_boundary",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert boundary.main([]) == 1
