from __future__ import annotations

import run_s145_backup_catalog_retention as audit


def test_catalog_retention_audit_passes() -> None:
    result = audit.run_backup_catalog_retention()
    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["metrics"] == {"catalog_entries": 1, "retained": 28, "deleted": 2, "quarantined_partials": 1}
    assert result["next_slice"] == "1448"


def test_summary_and_main_branches(monkeypatch, capsys) -> None:
    passing = audit.run_backup_catalog_retention()
    assert audit.summary_line(passing) == "postgres_backup_catalog_retention=pass checks=6/6 retained=28 deleted=2 quarantine=1 next=1448"
    failed = {"status": "FAIL", "checks": {"one": False}, "metrics": {}, "next_slice": "blocked"}
    assert audit.summary_line(failed) == "postgres_backup_catalog_retention=fail checks=0/1 retained=0 deleted=0 quarantine=0 next=blocked"
    monkeypatch.setattr(audit, "run_backup_catalog_retention", lambda: passing)
    assert audit.main(["--summary"]) == 0
    assert "retention=pass" in capsys.readouterr().out
    assert audit.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(audit, "run_backup_catalog_retention", lambda: failed)
    assert audit.main([]) == 1

