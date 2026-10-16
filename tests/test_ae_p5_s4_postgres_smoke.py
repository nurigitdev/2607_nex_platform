from __future__ import annotations

from types import SimpleNamespace

import run_p5_s4_postgres_smoke as smoke

DATABASE_URL = "postgresql://nex_ae_user:test-secret@127.0.0.1:5432/nex_ae_test"


def test_protected_smoke_skips_without_opt_in() -> None:
    evidence = smoke.run_p5_s4_postgres_smoke({})

    assert evidence["status"] == "SKIPPED"
    assert evidence["actual_postgres"] is False


def test_protected_smoke_rejects_missing_and_wrong_targets() -> None:
    missing = smoke.run_p5_s4_postgres_smoke({smoke.SMOKE_ENV: "1"})
    wrong = smoke.run_p5_s4_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: "postgresql://other:secret@localhost/nex_ae_dev",
        }
    )

    assert missing["failure_code"] == "database_url_missing"
    assert wrong["failure_code"] == "target_not_allowed"


def test_smoke_composes_migration_and_execution_evidence(monkeypatch) -> None:
    migration = SimpleNamespace(
        planned=("2103_ae_capability_plan_validation",),
        applied=(),
        skipped=("2103_ae_capability_plan_validation",),
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
            "checks": {"validation_valid": True},
            "row_counts": {"plan_validation": 1, "compile_rows": 0},
            "cleanup_counts": {"remaining": 0},
        },
    )

    evidence = smoke.run_p5_s4_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.DATABASE_ENV: DATABASE_URL}
    )

    assert evidence["status"] == "PASS"
    assert evidence["checks"] == {
        "migration_current": True,
        "validation_valid": True,
    }
    assert "test-secret" not in evidence["redacted_database_url"]
    assert "checks=2/2" in smoke.summary_line(evidence)
    assert "validations=1" in smoke.summary_line(evidence)
    assert "compile_rows=0" in smoke.summary_line(evidence)


def test_smoke_reports_failed_checks_and_redacts_errors(monkeypatch) -> None:
    migration = SimpleNamespace(
        planned=("2103_ae_capability_plan_validation",), applied=(), skipped=()
    )
    monkeypatch.setattr(smoke, "run_service_migrations", lambda *a, **k: migration)
    monkeypatch.setattr(
        smoke,
        "_execute_postgres_smoke",
        lambda _url: {
            "status": "PASS",
            "checks": {"validation_valid": False},
            "row_counts": {},
            "cleanup_counts": {},
        },
    )
    failed = smoke.run_p5_s4_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.DATABASE_ENV: DATABASE_URL}
    )
    assert failed["status"] == "FAIL"
    assert failed["failure_code"] == "p5_s4_postgres_smoke_failed"

    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError(DATABASE_URL)),
    )
    error = smoke.run_p5_s4_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.DATABASE_ENV: DATABASE_URL}
    )
    assert error["failure_code"] == "execution_failed"
    assert "test-secret" not in error["detail"]


def test_target_guard_and_summary_failure_defaults() -> None:
    assert smoke._target_url_allowed(DATABASE_URL) is True
    assert smoke._target_url_allowed(
        "postgresql://nex_ae_user:pw@localhost/other"
    ) is False
    assert smoke.summary_line({"status": "SKIPPED"}).startswith(
        "p5_s4_postgres=skipped"
    )
