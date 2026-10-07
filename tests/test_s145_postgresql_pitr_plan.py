from __future__ import annotations

import run_s145_postgresql_pitr_plan as audit


def test_pitr_plan_audit_passes() -> None:
    result = audit.run_postgresql_pitr_plan()
    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["metrics"] == {"database_targets": 5, "base_generations": 2, "archive_timeout_seconds": 300}
    assert result["next_slice"] == "1449"


def test_summary_and_main_branches(monkeypatch, capsys) -> None:
    passing = audit.run_postgresql_pitr_plan()
    assert audit.summary_line(passing) == "postgres_pitr_plan=pass checks=8/8 databases=5 bases=2 wal=300s next=1449"
    failed = {"status": "FAIL", "checks": {"one": False}, "metrics": {}, "next_slice": "blocked"}
    assert audit.summary_line(failed) == "postgres_pitr_plan=fail checks=0/1 databases=0 bases=0 wal=0s next=blocked"
    monkeypatch.setattr(audit, "run_postgresql_pitr_plan", lambda: passing)
    assert audit.main(["--summary"]) == 0
    assert "plan=pass" in capsys.readouterr().out
    assert audit.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(audit, "run_postgresql_pitr_plan", lambda: failed)
    assert audit.main([]) == 1
