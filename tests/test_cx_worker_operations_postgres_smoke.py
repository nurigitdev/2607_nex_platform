from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import run_cx_worker_operations_postgres_smoke as smoke
from run_migrations import MigrationError


DATABASE_URL = (
    "postgresql+psycopg://nex_cx_user:private@127.0.0.1:5432/nex_cx_test"
)


def _passing_execution() -> dict[str, object]:
    return {
        "database": smoke.EXPECTED_DATABASE,
        "role": smoke.EXPECTED_ROLE,
        "probe_residue": 0,
        "details": {
            "unique_claimed_job_count": smoke.CONCURRENT_JOB_COUNT,
            "concurrent_workers": smoke.CONCURRENT_JOB_COUNT,
            "applied_count": smoke.CONCURRENT_JOB_COUNT - 2,
        },
        "checks": {"concurrent_claim": True, "cleanup_verified": True},
        "failed_checks": [],
    }


def test_worker_postgres_smoke_is_opt_in_and_test_only() -> None:
    skipped = smoke.run_cx_worker_operations_postgres_smoke({})
    rejected = smoke.run_cx_worker_operations_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.PROFILE_ENV: "dev"}
    )

    assert skipped["status"] == "SKIPPED"
    assert rejected["status"] == "FAIL"
    assert rejected["failure_code"] == "profile_not_allowed"
    assert smoke.summary_line(skipped).endswith(f"reason={smoke.SMOKE_ENV}")


def test_worker_postgres_smoke_rejects_wrong_database_or_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smoke, "service_database_env", lambda *a, **k: "DB")
    monkeypatch.setattr(
        smoke,
        "service_database_url",
        lambda *a, **k: DATABASE_URL.replace("nex_cx_test", "nex_cx_dev"),
    )

    result = smoke.run_cx_worker_operations_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )

    assert result["failure_code"] == "target_not_allowed"
    assert smoke._target_url_allowed(DATABASE_URL) is True
    assert smoke._target_url_allowed(
        DATABASE_URL.replace("nex_cx_user", "postgres")
    ) is False
    assert smoke._target_url_allowed("postgresql://user:%zz@[") is False


def test_worker_postgres_smoke_runs_migrations_and_redacts_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = SimpleNamespace(
        planned=(smoke.LATEST_MIGRATION_VERSION,),
        applied=(),
        skipped=(smoke.LATEST_MIGRATION_VERSION,),
    )
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        smoke,
        "service_database_env",
        lambda *a, **k: "NEX_CX_TEST_DATABASE_URL",
    )
    monkeypatch.setattr(
        smoke,
        "service_database_url",
        lambda *a, **k: DATABASE_URL,
    )
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda service_id, database_url, profile: calls.append(
            (service_id, profile)
        )
        or migration,
    )
    monkeypatch.setattr(
        smoke,
        "_execute_worker_operations_smoke",
        lambda **kwargs: _passing_execution(),
    )

    result = smoke.run_cx_worker_operations_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )

    assert result["status"] == "PASS"
    assert result["migration"]["skipped"] == [smoke.LATEST_MIGRATION_VERSION]
    assert result["dgx_live_provider_required"] is False
    assert result["redacted_database_url"].endswith(
        "@127.0.0.1:5432/nex_cx_test"
    )
    assert "private" not in result["redacted_database_url"]
    assert calls == [(smoke.SERVICE_ID, "test")]


def test_worker_postgres_smoke_fails_closed_for_checks_and_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = SimpleNamespace(planned=(), applied=(), skipped=())
    monkeypatch.setattr(smoke, "service_database_env", lambda *a, **k: "DB")
    monkeypatch.setattr(
        smoke,
        "service_database_url",
        lambda *a, **k: DATABASE_URL,
    )
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *a, **k: migration,
    )
    monkeypatch.setattr(
        smoke,
        "_execute_worker_operations_smoke",
        lambda **kwargs: {
            **_passing_execution(),
            "failed_checks": ["cleanup_verified"],
        },
    )

    failed = smoke.run_cx_worker_operations_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )
    assert failed["failure_code"] == "worker_operations_smoke_failed"
    assert failed["detail"] == "cleanup_verified"

    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *a, **k: (_ for _ in ()).throw(
            MigrationError(f"failed {DATABASE_URL}")
        ),
    )
    errored = smoke.run_cx_worker_operations_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )
    assert errored["failure_code"] == "execution_failed"
    assert "private" not in errored["detail"]
    assert "***" in errored["detail"]

    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("private")),
    )
    unexpected = smoke.run_cx_worker_operations_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )
    assert unexpected["detail"] == "RuntimeError"


def test_worker_postgres_smoke_helpers_and_cli(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    passing = {
        "status": "PASS",
        **_passing_execution(),
        "dgx_live_provider_required": False,
    }
    assert smoke._redact_detail("plain", database_url="") == "plain"
    timestamp = smoke._wire_timestamp(datetime(2026, 9, 23, tzinfo=UTC))
    assert timestamp == "2026-09-23T00:00:00Z"
    summary = smoke.summary_line(passing)
    assert "claims=6/6" in summary
    assert "recovered=4" in summary
    assert "residue=0" in summary

    monkeypatch.setattr(
        smoke,
        "run_cx_worker_operations_postgres_smoke",
        lambda: passing,
    )
    assert smoke.main(["--summary"]) == 0
    assert "postgres_smoke=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_cx_worker_operations_postgres_smoke",
        lambda: {"status": "FAIL"},
    )
    assert smoke.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
