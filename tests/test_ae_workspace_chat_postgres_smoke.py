from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import run_ae_workspace_chat_postgres_smoke as smoke
from run_migrations import MigrationError


DATABASE_URL = (
    "postgresql+psycopg://nex_ae_user:private@127.0.0.1:5432/nex_ae_test"
)


def _execution() -> dict:
    return {
        "status": "PASS",
        "execution_state": "EXECUTED",
        "actual_postgres": True,
        "database": "nex_ae_test",
        "role": "nex_ae_user",
        "checks": {
            "actual_database_identity": True,
            "workspace_written": True,
            "chat_api_completed": True,
            "workspace_lineage_preserved": True,
            "restart_workspace_read": True,
            "restart_activity_read": True,
            "restart_chat_read": True,
            "cross_owner_hidden": True,
            "retry_idempotent": True,
            "operational_events_persisted": True,
            "operational_events_private": True,
            "cleanup_complete": True,
        },
        "row_counts": {
            "workspace": 1,
            "activities": 3,
            "chat": 1,
            "events": 2,
        },
        "cleanup_counts": {
            "events": 2,
            "chat": 1,
            "workspace": 1,
            "remaining": 0,
        },
        "provider_mode": "deterministic-mock",
        "provider_call_count": 1,
    }


def _migration(latest: str = "1014_ae_workspace_activity_persistence"):
    return SimpleNamespace(
        planned=("0021_prompt_analytics_foundation", latest),
        applied=(),
        skipped=("0021_prompt_analytics_foundation", latest),
    )


def test_runner_requires_explicit_test_database_opt_in() -> None:
    skipped = smoke.run_ae_workspace_chat_postgres_smoke({})
    missing = smoke.run_ae_workspace_chat_postgres_smoke({smoke.SMOKE_ENV: "1"})
    wrong = smoke.run_ae_workspace_chat_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: DATABASE_URL.replace("nex_ae_test", "nex_ae_dev"),
        }
    )

    assert skipped["status"] == "SKIPPED"
    assert skipped["actual_postgres"] is False
    assert missing["failure_code"] == "database_url_missing"
    assert wrong["failure_code"] == "target_not_allowed"
    assert smoke._target_url_allowed(DATABASE_URL) is True
    assert smoke._target_url_allowed("not-a-url") is False
    assert "traceparent" not in smoke._headers("tenant-a", "user-a")
    assert smoke._headers(
        "tenant-a",
        "user-a",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
    )["traceparent"].startswith("00-4bf92f3577b34da6a3ce929d0e0e4736-")


def test_runner_executes_migrations_and_postgres_probe(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *_args, **_kwargs: _migration(),
    )
    monkeypatch.setattr(smoke, "_execute_postgres_smoke", lambda _url: _execution())

    result = smoke.run_ae_workspace_chat_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.DATABASE_ENV: DATABASE_URL}
    )

    assert result["status"] == "PASS"
    assert result["checks"]["migration_current"] is True
    assert result["migration"] == {
        "planned_count": 2,
        "applied_count": 0,
        "skipped_count": 2,
        "latest_version": "1014_ae_workspace_activity_persistence",
    }
    assert "private" not in result["redacted_database_url"]


@pytest.mark.parametrize(
    ("migration", "expected"),
    [
        (_migration("1000_old"), False),
        (
            SimpleNamespace(
                planned=("1014_ae_workspace_activity_persistence",),
                applied=(),
                skipped=(),
            ),
            False,
        ),
    ],
)
def test_runner_fails_when_migration_ledger_is_not_current(
    monkeypatch,
    migration,
    expected,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *_args, **_kwargs: migration,
    )
    monkeypatch.setattr(smoke, "_execute_postgres_smoke", lambda _url: _execution())

    result = smoke.run_ae_workspace_chat_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.DATABASE_ENV: DATABASE_URL}
    )

    assert result["checks"]["migration_current"] is expected
    assert result["status"] == "FAIL"
    assert result["failure_code"] == "ae_workspace_chat_postgres_smoke_failed"


def test_runner_redacts_execution_failures(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            MigrationError(f"failed {DATABASE_URL}")
        ),
    )

    result = smoke.run_ae_workspace_chat_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.DATABASE_ENV: DATABASE_URL}
    )

    assert result["failure_code"] == "execution_failed"
    assert "private" not in result["detail"]
    assert "***" in result["detail"]


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = {
        **_execution(),
        "migration": {"planned_count": 24},
    }
    assert smoke.summary_line(passing) == (
        "ae_workspace_chat_postgres=pass execution=executed "
        "database=nex_ae_test checks=12/12 migrations=24 "
        "rows=1/3/1/2 cleanup=0"
    )
    assert "execution=not-run" in smoke.summary_line({"status": "SKIPPED"})

    monkeypatch.setattr(
        smoke,
        "run_ae_workspace_chat_postgres_smoke",
        lambda: passing,
    )
    assert smoke.main(["--summary"]) == 0
    assert "execution=executed" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        smoke,
        "run_ae_workspace_chat_postgres_smoke",
        lambda: {"status": "FAIL"},
    )
    assert smoke.main([]) == 1
