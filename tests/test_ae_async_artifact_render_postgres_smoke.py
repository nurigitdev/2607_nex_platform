from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

import run_ae_async_artifact_render_postgres_smoke as smoke
from run_migrations import MigrationError

DATABASE_URL = "postgresql+psycopg://nex_ae_user:private@127.0.0.1:5432/nex_ae_test"


def _migration(*, current: bool = True):
    return SimpleNamespace(
        planned=("001", "002"),
        applied=() if current else ("001",),
        skipped=("001", "002") if current else (),
    )


def _evidence(*, durable: bool = True):
    return {
        "execution_state": "EXECUTED",
        "database_identity": {
            "database": smoke.DATABASE_NAME,
            "role": smoke.DATABASE_ROLE,
        },
        "checks": {"durable_async_render": durable},
        "row_counts": {"artifacts": 1, "render_jobs": 2, "queue_jobs": 2},
        "cleanup_counts": {"remaining": 0},
    }


def _env():
    return {smoke.SMOKE_ENV: "1", smoke.DATABASE_ENV: DATABASE_URL}


def test_smoke_is_opt_in_and_requires_database_url() -> None:
    skipped = smoke.run_ae_async_artifact_render_postgres_smoke({})
    missing = smoke.run_ae_async_artifact_render_postgres_smoke({smoke.SMOKE_ENV: "1"})

    assert skipped["status"] == "SKIPPED"
    assert skipped["actual_postgres"] is False
    assert missing["failure_code"] == "database_url_missing"
    assert smoke.summary_line(skipped).endswith(f"reason={smoke.SMOKE_ENV}")


@pytest.mark.parametrize(
    "database_url",
    [
        DATABASE_URL.replace("nex_ae_test", "nex_ae_dev"),
        DATABASE_URL.replace("nex_ae_user", "postgres"),
        "postgresql://[",
    ],
)
def test_smoke_rejects_non_test_database_or_role(database_url: str) -> None:
    result = smoke.run_ae_async_artifact_render_postgres_smoke(
        {**_env(), smoke.DATABASE_ENV: database_url}
    )

    assert result["failure_code"] == "database_target_not_allowed"


def test_smoke_runs_current_migration_and_executor(monkeypatch) -> None:
    calls = []

    def migrate(service_id, **kwargs):
        calls.append((service_id, kwargs["profile"], kwargs["database_url"]))
        return _migration()

    monkeypatch.setattr(smoke, "run_service_migrations", migrate)
    result = smoke.run_ae_async_artifact_render_postgres_smoke(
        _env(), executor=lambda **kwargs: _evidence()
    )

    assert result["status"] == "PASS"
    assert calls == [(smoke.SERVICE_ID, "test", DATABASE_URL)]
    assert result["checks"]["migration_current"] is True
    assert result["actual_postgres"] is True
    assert result["remote_provider_required"] is False
    assert result["private_storage_mode"] == "temporary-local-filesystem"
    assert "private" not in result["database"]
    assert result["migration"] == {
        "planned_count": 2,
        "applied_count": 0,
        "skipped_count": 2,
        "latest_version": "002",
    }


def test_smoke_fails_closed_for_checks_and_redacts_errors(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke, "run_service_migrations", lambda *args, **kwargs: _migration()
    )
    failed = smoke.run_ae_async_artifact_render_postgres_smoke(
        _env(), executor=lambda **kwargs: _evidence(durable=False)
    )

    assert failed["status"] == "FAIL"
    assert failed["failed_checks"] == ["durable_async_render"]

    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            MigrationError(f"failed {DATABASE_URL}")
        ),
    )
    errored = smoke.run_ae_async_artifact_render_postgres_smoke(_env())
    assert errored["failure_code"] == "execution_failed"
    assert "private" not in errored["detail"]
    assert "***" in errored["detail"]

    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(Exception("private")),
    )
    assert smoke.run_ae_async_artifact_render_postgres_smoke(_env())["detail"] == (
        "Exception"
    )


def test_helpers_summary_and_cli(monkeypatch, capsys) -> None:
    assert smoke._migration_current(_migration()) is True
    assert smoke._migration_current(_migration(current=False)) is False
    assert smoke._migration_summary(SimpleNamespace())["latest_version"] is None
    assert smoke._target_url_allowed("postgresql://[") is False
    assert (
        smoke._redact_detail(
            "safe detail",
            database_url=(
                "postgresql+psycopg://nex_ae_user@127.0.0.1:5432/nex_ae_test"
            ),
        )
        == "safe detail"
    )

    passing = {
        "status": "PASS",
        **_evidence(),
        "checks": {"one": True, "two": True},
    }
    assert "checks=2" in smoke.summary_line(passing)
    assert "rows=5" in smoke.summary_line(passing)
    assert "remaining=0" in smoke.summary_line(passing)
    assert "code=checks_failed" in smoke.summary_line({"status": "FAIL"})

    monkeypatch.setattr(
        smoke, "run_ae_async_artifact_render_postgres_smoke", lambda: passing
    )
    assert smoke.main(["--summary"]) == 0
    assert "ae_async_artifact_render_postgres=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        smoke,
        "run_ae_async_artifact_render_postgres_smoke",
        lambda: {"status": "FAIL"},
    )
    assert smoke.main([]) == 1


@pytest.mark.skipif(
    os.getenv(smoke.SMOKE_ENV) != "1",
    reason=f"{smoke.SMOKE_ENV}=1 is required for protected PostgreSQL smoke",
)
def test_actual_ae_async_artifact_render_postgres_smoke() -> None:
    result = smoke.run_ae_async_artifact_render_postgres_smoke()

    assert result["status"] == "PASS", result
    assert result["actual_postgres"] is True
    assert result["database_identity"] == {
        "database": smoke.DATABASE_NAME,
        "role": smoke.DATABASE_ROLE,
    }
    assert result["checks"]["worker_completed_after_restart"] is True
    assert result["checks"]["private_payloads_materialized"] is True
    assert result["checks"]["metadata_only_in_postgres"] is True
    assert result["checks"]["bounded_retry_persisted"] is True
    assert result["checks"]["retry_state_reconciled"] is True
    assert result["cleanup_counts"]["remaining"] == 0
