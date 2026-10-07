from __future__ import annotations

import run_s145_postgresql_compose_rehearsal as audit


def test_compose_rehearsal_audit_passes() -> None:
    result = audit.run_postgresql_compose_rehearsal()
    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["metrics"] == {
        "service_count": 5,
        "archive_count": 5,
        "attempt_count": 1,
    }
    assert result["next_slice"] == "1451"


def test_compose_rehearsal_cli_and_failure(monkeypatch, capsys) -> None:
    passed = audit.run_postgresql_compose_rehearsal()
    assert audit.main(["--summary"]) == 0
    assert "postgres_compose_rehearsal=pass" in capsys.readouterr().out
    assert audit.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    failed = {**passed, "status": "FAIL", "next_slice": "blocked"}
    monkeypatch.setattr(audit, "run_postgresql_compose_rehearsal", lambda: failed)
    assert audit.main([]) == 1
