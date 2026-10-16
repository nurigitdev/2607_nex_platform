from __future__ import annotations

from types import SimpleNamespace

import run_p4_agent_runtime_postgres_smoke as smoke

DATABASE_URL = (
    "postgresql://nex_ae_user:test-secret@127.0.0.1:5432/nex_ae_test"
)


def test_protected_smoke_skips_without_opt_in() -> None:
    evidence = smoke.run_p4_agent_runtime_postgres_smoke({})
    assert evidence["status"] == "SKIPPED"
    assert evidence["actual_postgres"] is False
    assert "NEX_AE_P4_POSTGRES_SMOKE" in evidence["skip_reason"]


def test_protected_smoke_rejects_missing_and_wrong_database_targets() -> None:
    missing = smoke.run_p4_agent_runtime_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )
    wrong = smoke.run_p4_agent_runtime_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: (
                "postgresql://other:secret@127.0.0.1:5432/nex_ae_dev"
            ),
        }
    )
    assert missing["failure_code"] == "database_url_missing"
    assert wrong["failure_code"] == "target_not_allowed"


def test_protected_smoke_composes_migration_and_execution_evidence(monkeypatch) -> None:
    migration = SimpleNamespace(
        planned=("one", "2006_ae_agent_result"),
        applied=("2006_ae_agent_result",),
        skipped=("one",),
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
            "checks": {"runtime_chain": True},
            "row_counts": {"execution": 2, "job": 2, "step": 2,
                           "result": 1, "delivery": 1},
            "cleanup_counts": {"remaining": 0},
        },
    )
    evidence = smoke.run_p4_agent_runtime_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.DATABASE_ENV: DATABASE_URL}
    )
    assert evidence["status"] == "PASS"
    assert evidence["checks"] == {
        "migration_current": True,
        "runtime_chain": True,
    }
    assert evidence["migration"]["latest_version"] == "2006_ae_agent_result"
    assert "test-secret" not in evidence["redacted_database_url"]
    assert "checks=2/2" in smoke.summary_line(evidence)
    assert "chain_rows=2/2/2/1/1" in smoke.summary_line(evidence)


def test_protected_smoke_reports_failed_checks_and_redacts_exceptions(monkeypatch) -> None:
    migration = SimpleNamespace(
        planned=("2006_ae_agent_result",), applied=(), skipped=()
    )
    monkeypatch.setattr(smoke, "run_service_migrations", lambda *a, **k: migration)
    monkeypatch.setattr(
        smoke,
        "_execute_postgres_smoke",
        lambda _url: {
            "status": "PASS",
            "checks": {"runtime_chain": False},
            "row_counts": {},
            "cleanup_counts": {},
        },
    )
    failed = smoke.run_p4_agent_runtime_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.DATABASE_ENV: DATABASE_URL}
    )
    assert failed["status"] == "FAIL"
    assert failed["failure_code"] == "p4_agent_runtime_postgres_smoke_failed"

    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError(DATABASE_URL)),
    )
    exception = smoke.run_p4_agent_runtime_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.DATABASE_ENV: DATABASE_URL}
    )
    assert exception["failure_code"] == "execution_failed"
    assert "test-secret" not in exception["detail"]
    assert "***" in exception["detail"]

    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *a, **k: migration,
    )
    monkeypatch.setattr(
        smoke,
        "_execute_postgres_smoke",
        lambda _url: (_ for _ in ()).throw(
            smoke.AgentResultError("ae.agent_result_store_unavailable", "offline")
        ),
    )
    domain_failure = smoke.run_p4_agent_runtime_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.DATABASE_ENV: DATABASE_URL}
    )
    assert domain_failure["failure_code"] == "execution_failed"
    assert domain_failure["detail"] == "offline"


def test_target_guard_and_summary_cover_failure_defaults() -> None:
    assert smoke._target_url_allowed(DATABASE_URL) is True
    assert smoke._target_url_allowed(
        "postgresql://nex_ae_user:pw@127.0.0.1:5432/other"
    ) is False
    assert smoke.summary_line({"status": "SKIPPED"}).startswith(
        "p4_agent_runtime_postgres=skipped"
    )
