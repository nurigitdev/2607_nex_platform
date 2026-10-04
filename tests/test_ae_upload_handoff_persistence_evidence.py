from __future__ import annotations

from pathlib import Path

import run_ae_upload_handoff_persistence as smoke


def test_repository_evidence_passes() -> None:
    evidence = smoke.run_ae_upload_handoff_persistence()
    assert evidence["status"] == "PASS", evidence
    assert all(evidence["checks"].values())
    assert evidence["database_used"] == "sqlite_regression"
    assert evidence["actual_postgres_deferred_to"] == "1350"
    assert evidence["next_slice"] == "1345"


def test_evidence_fails_for_empty_root(tmp_path: Path) -> None:
    evidence = smoke.run_ae_upload_handoff_persistence(tmp_path)
    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["migration_present"] is False


def test_summary_helpers_and_main(monkeypatch, tmp_path: Path, capsys) -> None:
    source = tmp_path / "source"
    source.write_text("value", encoding="utf-8")
    assert smoke._read_text(source) == "value"
    assert smoke._read_text(tmp_path / "missing") == ""

    passing = {
        "status": "PASS",
        "checks": {"one": True, "two": True},
        "index_count": 3,
        "next_slice": "1345",
    }
    assert smoke.summary_line(passing) == (
        "ae_upload_handoff_persistence=pass checks=2/2 indexes=3 next=1345"
    )
    assert smoke.summary_line({"status": "FAIL", "issues": [1]}) == (
        "ae_upload_handoff_persistence=fail issues=1"
    )
    monkeypatch.setattr(smoke, "run_ae_upload_handoff_persistence", lambda: passing)
    assert smoke.main(["--summary"]) == 0
    assert "next=1345" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        smoke,
        "run_ae_upload_handoff_persistence",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert smoke.main([]) == 1
