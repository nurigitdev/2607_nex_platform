from __future__ import annotations

import run_s145_postgresql_backup_policy as audit


def test_canonical_backup_policy_passes() -> None:
    result = audit.run_postgresql_backup_policy()
    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["policy"]["database_count"] == 5
    assert result["next_slice"] == "1445"
    assert audit.summary_line(result) == (
        "postgresql_backup_policy=pass checks=7/7 databases=5 rpo=6h rto=60m next=1445"
    )


def test_summary_and_main_failure_branches(monkeypatch, capsys) -> None:
    failed = {"status": "FAIL", "checks": {"one": False}, "policy": {}, "next_slice": "blocked"}
    assert audit.summary_line(failed) == (
        "postgresql_backup_policy=fail checks=0/1 databases=0 rpo=0h rto=0m next=blocked"
    )
    passing = audit.run_postgresql_backup_policy()
    monkeypatch.setattr(audit, "run_postgresql_backup_policy", lambda: passing)
    assert audit.main(["--summary"]) == 0
    assert "policy=pass" in capsys.readouterr().out
    assert audit.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(audit, "run_postgresql_backup_policy", lambda: failed)
    assert audit.main([]) == 1

