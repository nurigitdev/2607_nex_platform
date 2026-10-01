from __future__ import annotations

from pathlib import Path

import run_oa_identity_lifecycle_repository as smoke


def test_repository_evidence_passes() -> None:
    result = smoke.run_oa_identity_lifecycle_repository()
    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["event_count"] == 2


def test_repository_evidence_fails_without_migration(tmp_path: Path) -> None:
    result = smoke.run_oa_identity_lifecycle_repository(tmp_path)
    assert result["status"] == "FAIL"
    assert result["checks"]["short_event_table_present"] is False


def test_summary_and_main_cover_paths(monkeypatch, capsys) -> None:
    passing = smoke.run_oa_identity_lifecycle_repository()
    assert "repository=pass" in smoke.summary_line(passing)
    assert "repository=fail" in smoke.summary_line({"status": "FAIL"})
    monkeypatch.setattr(smoke, "run_oa_identity_lifecycle_repository", lambda: passing)
    assert smoke.main(["--summary"]) == 0
    assert "repository=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        smoke,
        "run_oa_identity_lifecycle_repository",
        lambda: {"status": "FAIL"},
    )
    assert smoke.main([]) == 1
