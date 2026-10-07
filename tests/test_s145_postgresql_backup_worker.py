from __future__ import annotations

import run_s145_postgresql_backup_worker as audit


def test_backup_worker_audit_passes() -> None:
    result = audit.run_postgresql_backup_worker_audit()
    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["metrics"] == {
        "attempt_count": 2,
        "service_count": 5,
        "max_attempts": 3,
    }
    assert result["next_slice"] == "1450"
    assert "password" not in str(result).lower()


def test_backup_worker_audit_cli_and_failure(monkeypatch, capsys) -> None:
    passed = audit.run_postgresql_backup_worker_audit()
    assert audit.main(["--summary"]) == 0
    assert "postgres_backup_worker=pass" in capsys.readouterr().out
    assert audit.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    failed = {**passed, "status": "FAIL", "next_slice": "blocked"}
    monkeypatch.setattr(audit, "run_postgresql_backup_worker_audit", lambda: failed)
    assert audit.main([]) == 1
