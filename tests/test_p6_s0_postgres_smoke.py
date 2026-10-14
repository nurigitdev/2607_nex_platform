from __future__ import annotations

import sys
from types import SimpleNamespace

import run_p6_s0_postgres_smoke as smoke

DATABASE_URL = "postgresql://nex_ae_user:test-secret@127.0.0.1:5432/nex_ae_test"


def test_protected_smoke_skips_without_opt_in() -> None:
    evidence = smoke.run_p6_s0_postgres_smoke({})

    assert evidence["status"] == "SKIPPED"
    assert evidence["actual_postgres"] is False
    assert smoke.SMOKE_ENV in evidence["skip_reason"]


def test_protected_smoke_rejects_missing_and_wrong_targets() -> None:
    missing = smoke.run_p6_s0_postgres_smoke({smoke.SMOKE_ENV: "1"})
    wrong = smoke.run_p6_s0_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: "postgresql://other:secret@localhost/nex_ae_dev",
        }
    )

    assert missing["failure_code"] == "database_url_missing"
    assert wrong["failure_code"] == "target_not_allowed"
    assert smoke._target_url_allowed(DATABASE_URL) is True


def test_smoke_composes_migration_and_runtime_evidence(monkeypatch) -> None:
    migration = SimpleNamespace(
        planned=tuple(sorted(smoke.REQUIRED_MIGRATIONS)),
        applied=(),
        skipped=tuple(sorted(smoke.REQUIRED_MIGRATIONS)),
    )
    monkeypatch.setattr(smoke, "run_service_migrations", lambda *a, **k: migration)
    monkeypatch.setattr(
        smoke,
        "_execute_postgres_smoke",
        lambda _url: {
            "status": "PASS",
            "actual_postgres": True,
            "database": "nex_ae_test",
            "role": "nex_ae_user",
            "checks": {
                "runtime_job_completed": True,
                "restart_is_idempotent": True,
                "zero_residue": True,
            },
            "row_counts": {
                "runtime_job": 1,
                "runtime_job_attempt": 1,
                "heartbeat": 1,
            },
            "cleanup_counts": {"remaining": 0},
            "worker": {},
        },
    )

    evidence = smoke.run_p6_s0_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.DATABASE_ENV: DATABASE_URL}
    )

    assert evidence["status"] == "PASS"
    assert evidence["checks"]["migration_current"] is True
    assert "test-secret" not in evidence["redacted_database_url"]
    assert "checks=4/4" in smoke.summary_line(evidence)
    assert "jobs=1" in smoke.summary_line(evidence)
    assert "remaining=0" in smoke.summary_line(evidence)


def test_smoke_reports_failed_checks_and_redacts_execution_errors(monkeypatch) -> None:
    migration = SimpleNamespace(
        planned=tuple(sorted(smoke.REQUIRED_MIGRATIONS)),
        applied=(),
        skipped=tuple(sorted(smoke.REQUIRED_MIGRATIONS)),
    )
    monkeypatch.setattr(smoke, "run_service_migrations", lambda *a, **k: migration)
    monkeypatch.setattr(
        smoke,
        "_execute_postgres_smoke",
        lambda _url: {
            "status": "PASS",
            "checks": {"restart_is_idempotent": False},
            "row_counts": {},
            "cleanup_counts": {},
        },
    )
    failed = smoke.run_p6_s0_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.DATABASE_ENV: DATABASE_URL}
    )
    assert failed["status"] == "FAIL"
    assert failed["failure_code"] == "p6_s0_postgres_smoke_failed"

    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError(DATABASE_URL)),
    )
    error = smoke.run_p6_s0_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.DATABASE_ENV: DATABASE_URL}
    )
    assert error["failure_code"] == "execution_failed"
    assert "test-secret" not in error["detail"]
    assert "***" in error["detail"]


def test_summary_handles_skip_defaults() -> None:
    line = smoke.summary_line({"status": "SKIPPED"})

    assert line.startswith("p6_s0_postgres=skipped")
    assert "checks=0/0" in line


def test_cli_loads_missing_env_file_and_reports_protected_skip(
    monkeypatch, capsys, tmp_path
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_p6_s0_postgres_smoke.py",
            "--summary",
            "--env-file",
            str(tmp_path / "missing.env"),
        ],
    )

    assert smoke.main() == 0
    assert "p6_s0_postgres=skipped" in capsys.readouterr().out
