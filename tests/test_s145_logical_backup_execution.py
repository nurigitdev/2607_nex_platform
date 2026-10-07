from __future__ import annotations

import run_s145_logical_backup_execution as audit


def test_deterministic_logical_backup_execution_passes() -> None:
    result = audit.run_logical_backup_execution()
    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["metrics"]["database_targets"] == 5
    assert result["next_slice"] == "1446"
    assert audit.summary_line(result).startswith("postgres_logical_backup_execution=pass checks=8/8")


def test_summary_and_main_branches(monkeypatch, capsys) -> None:
    failed = {"status": "FAIL", "checks": {"one": False}, "metrics": {}, "next_slice": "blocked"}
    assert audit.summary_line(failed) == "postgres_logical_backup_execution=fail checks=0/1 targets=0 bytes=0 next=blocked"
    passing = audit.run_logical_backup_execution()
    monkeypatch.setattr(audit, "run_logical_backup_execution", lambda: passing)
    assert audit.main(["--summary"]) == 0
    assert "execution=pass" in capsys.readouterr().out
    assert audit.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(audit, "run_logical_backup_execution", lambda: failed)
    assert audit.main([]) == 1

