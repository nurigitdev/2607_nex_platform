from __future__ import annotations

from types import SimpleNamespace

import run_p5_s1_postgres_smoke as smoke

DATABASE_URL = "postgresql://nex_ae_user:test-secret@127.0.0.1:5432/nex_ae_test"


def test_protected_smoke_skips_without_opt_in() -> None:
    evidence = smoke.run_p5_s1_postgres_smoke({})
    assert evidence["status"] == "SKIPPED"
    assert evidence["actual_postgres"] is False
    assert smoke.SMOKE_ENV in evidence["skip_reason"]


def test_protected_smoke_rejects_missing_and_wrong_database_targets() -> None:
    missing = smoke.run_p5_s1_postgres_smoke({smoke.SMOKE_ENV: "1"})
    wrong = smoke.run_p5_s1_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: "postgresql://other:secret@localhost/nex_ae_dev",
        }
    )
    assert missing["failure_code"] == "database_url_missing"
    assert wrong["failure_code"] == "target_not_allowed"


def test_smoke_composes_current_migration_and_postgres_evidence(monkeypatch) -> None:
    migration = SimpleNamespace(
        planned=("2006_ae_agent_result", "2100_ae_prompt_registry_hardening", "2101_ae_work_intent"),
        applied=("2100_ae_prompt_registry_hardening", "2101_ae_work_intent"),
        skipped=("2006_ae_agent_result",),
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
            "checks": {"work_intent_idempotent": True},
            "row_counts": {"binding_history": 1, "work_intent": 1},
            "cleanup_counts": {"remaining": 0},
        },
    )

    evidence = smoke.run_p5_s1_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.DATABASE_ENV: DATABASE_URL}
    )

    assert evidence["status"] == "PASS"
    assert evidence["checks"] == {
        "migration_current": True,
        "work_intent_idempotent": True,
    }
    assert evidence["migration"]["latest_version"] == "2101_ae_work_intent"
    assert "test-secret" not in evidence["redacted_database_url"]
    assert "checks=2/2" in smoke.summary_line(evidence)
    assert "rows=1/1" in smoke.summary_line(evidence)


def test_smoke_reports_failed_checks_and_redacts_exception(monkeypatch) -> None:
    migration = SimpleNamespace(
        planned=("2101_ae_work_intent",), applied=(), skipped=("2101_ae_work_intent",)
    )
    monkeypatch.setattr(smoke, "run_service_migrations", lambda *a, **k: migration)
    monkeypatch.setattr(
        smoke,
        "_execute_postgres_smoke",
        lambda _url: {
            "status": "PASS",
            "checks": {"work_intent_idempotent": False},
            "row_counts": {},
            "cleanup_counts": {},
        },
    )
    failed = smoke.run_p5_s1_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.DATABASE_ENV: DATABASE_URL}
    )
    assert failed["status"] == "FAIL"
    assert failed["failure_code"] == "p5_s1_postgres_smoke_failed"

    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError(DATABASE_URL)),
    )
    exception = smoke.run_p5_s1_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.DATABASE_ENV: DATABASE_URL}
    )
    assert exception["failure_code"] == "execution_failed"
    assert "test-secret" not in exception["detail"]
    assert "***" in exception["detail"]


def test_target_guard_and_summary_cover_skip_defaults() -> None:
    assert smoke._target_url_allowed(DATABASE_URL) is True
    assert smoke._target_url_allowed(
        "postgresql://nex_ae_user:pw@localhost/other"
    ) is False
    assert smoke.summary_line({"status": "SKIPPED"}).startswith(
        "p5_s1_postgres=skipped"
    )
