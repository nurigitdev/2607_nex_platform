from __future__ import annotations

import os

import pytest

import run_s145_postgresql_recovery_acceptance as smoke


def test_recovery_acceptance_skips_without_opt_in() -> None:
    result = smoke.run_postgresql_recovery_acceptance({})
    assert result["status"] == "SKIP"
    assert result["reason"] == smoke.SMOKE_ENV
    assert smoke.summary_line(result) == (
        "postgres_recovery_acceptance=skip "
        "reason=NEX_S145_POSTGRES_RECOVERY_ACCEPTANCE"
    )


def test_recovery_acceptance_cli_summary_json_and_failure(monkeypatch, capsys) -> None:
    passed = {
        "status": "PASS",
        "checks": {"one": True},
        "metrics": {"database_count": 5, "wal_segment_count": 2, "elapsed_seconds": 1.2},
        "next_slice": "1452",
    }
    monkeypatch.setattr(smoke, "run_postgresql_recovery_acceptance", lambda _env: passed)
    assert smoke.main(["--execute", "--summary"]) == 0
    assert "postgres_recovery_acceptance=pass checks=1/1" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    failed = {**passed, "status": "FAIL", "next_slice": "blocked"}
    monkeypatch.setattr(smoke, "run_postgresql_recovery_acceptance", lambda _env: failed)
    assert smoke.main([]) == 1


def test_protected_recovery_acceptance() -> None:
    if os.environ.get(smoke.SMOKE_ENV) != "1":
        pytest.skip(f"{smoke.SMOKE_ENV}=1 is required")
    result = smoke.run_postgresql_recovery_acceptance()
    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["metrics"]["database_count"] == 5
    assert result["next_slice"] == "1452"
