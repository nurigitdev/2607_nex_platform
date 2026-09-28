from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

import run_ae_generated_response_postgres_smoke as smoke
from run_migrations import MigrationError


AE_URL = "postgresql+psycopg://nex_ae_user:private@127.0.0.1:5432/nex_ae_test"
CX_URL = "postgresql+psycopg://nex_cx_user:private@127.0.0.1:5432/nex_cx_test"


def _migration(*, current: bool = True):
    return SimpleNamespace(
        planned=("001", "002"),
        applied=() if current else ("001",),
        skipped=("001", "002") if current else (),
    )


def _evidence(*, durable: bool = True):
    return {
        "execution_state": "EXECUTED",
        "checks": {"content_persisted_privately_and_verified": durable},
        "row_counts": {"ae_chat": 1, "cx_job": 1},
        "cleanup_counts": {"ae_remaining": 0, "cx_remaining": 0},
    }


def _env():
    return {
        smoke.SMOKE_ENV: "1",
        smoke.AE_DATABASE_ENV: AE_URL,
        smoke.CX_DATABASE_ENV: CX_URL,
    }


def test_smoke_is_opt_in_and_requires_both_database_urls() -> None:
    skipped = smoke.run_ae_generated_response_postgres_smoke({})
    missing = smoke.run_ae_generated_response_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )

    assert skipped["status"] == "SKIPPED"
    assert skipped["actual_postgres"] is False
    assert missing["failure_code"] == "database_url_missing"
    assert smoke.summary_line(skipped).endswith(f"reason={smoke.SMOKE_ENV}")


def test_smoke_rejects_non_test_database_and_roles() -> None:
    bad_ae = smoke.run_ae_generated_response_postgres_smoke(
        {**_env(), smoke.AE_DATABASE_ENV: AE_URL.replace("nex_ae_test", "nex_ae_dev")}
    )
    bad_cx = smoke.run_ae_generated_response_postgres_smoke(
        {**_env(), smoke.CX_DATABASE_ENV: CX_URL.replace("nex_cx_user", "postgres")}
    )

    assert bad_ae["failure_code"] == "ae_target_not_allowed"
    assert bad_cx["failure_code"] == "cx_target_not_allowed"


def test_smoke_runs_current_migrations_and_executor(monkeypatch) -> None:
    calls = []

    def migrate(service_id, **kwargs):
        calls.append((service_id, kwargs["profile"]))
        return _migration()

    monkeypatch.setattr(smoke, "run_service_migrations", migrate)
    result = smoke.run_ae_generated_response_postgres_smoke(
        _env(), executor=lambda **kwargs: _evidence()
    )

    assert result["status"] == "PASS"
    assert calls == [("nex-ae-api", "test"), ("nex-cx", "test")]
    assert result["checks"]["ae_migration_current"] is True
    assert result["checks"]["cx_migration_current"] is True
    assert result["private_storage_mode"] == "temporary-local-filesystem"
    assert result["remote_provider_required"] is False
    assert "private" not in str(result["databases"])


def test_smoke_fails_closed_and_redacts_errors(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke, "run_service_migrations", lambda *args, **kwargs: _migration()
    )
    failed = smoke.run_ae_generated_response_postgres_smoke(
        _env(), executor=lambda **kwargs: _evidence(durable=False)
    )
    assert failed["status"] == "FAIL"
    assert failed["failed_checks"] == [
        "content_persisted_privately_and_verified"
    ]

    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            MigrationError(f"failed {AE_URL} and {CX_URL}")
        ),
    )
    errored = smoke.run_ae_generated_response_postgres_smoke(_env())
    assert errored["failure_code"] == "execution_failed"
    assert "private" not in errored["detail"]
    assert "***" in errored["detail"]

    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(Exception("private")),
    )
    assert smoke.run_ae_generated_response_postgres_smoke(_env())["detail"] == (
        "Exception"
    )


def test_summary_and_cli(monkeypatch, capsys) -> None:
    passing = {
        "status": "PASS",
        **_evidence(),
        "checks": {"one": True, "two": True},
    }
    assert "checks=2" in smoke.summary_line(passing)
    assert "cleanup=0/0" in smoke.summary_line(passing)
    assert "code=checks_failed" in smoke.summary_line({"status": "FAIL"})

    monkeypatch.setattr(
        smoke, "run_ae_generated_response_postgres_smoke", lambda: passing
    )
    assert smoke.main(["--summary"]) == 0
    assert "ae_generated_response_postgres=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        smoke,
        "run_ae_generated_response_postgres_smoke",
        lambda: {"status": "FAIL"},
    )
    assert smoke.main([]) == 1


@pytest.mark.skipif(
    os.getenv(smoke.SMOKE_ENV) != "1",
    reason=f"{smoke.SMOKE_ENV}=1 is required for protected PostgreSQL smoke",
)
def test_actual_ae_generated_response_postgres_smoke() -> None:
    result = smoke.run_ae_generated_response_postgres_smoke()

    assert result["status"] == "PASS", result
    assert result["actual_postgres"] is True
    assert result["checks"]["content_persisted_privately_and_verified"] is True
    assert result["checks"]["response_metadata_only_in_postgres"] is True
    assert result["cleanup_counts"]["ae_remaining"] == 0
    assert result["cleanup_counts"]["cx_remaining"] == 0
