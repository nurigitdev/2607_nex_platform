from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import run_cx_async_generation_postgres_smoke as smoke
from run_migrations import MigrationError


DATABASE_URL = (
    "postgresql+psycopg://nex_cx_user:private@127.0.0.1:5432/nex_cx_test"
)


def _execution(*, failed_checks=None):
    return {
        "database": smoke.EXPECTED_DATABASE,
        "role": smoke.EXPECTED_ROLE,
        "probe_id": "probe",
        "probe_residue": 0,
        "details": {
            "job_status_counts": {"CANCELLED": 1, "SUCCEEDED": 3},
            "recovered_status": "RETRY_SCHEDULED",
        },
        "checks": {"cleanup_verified": True},
        "failed_checks": list(failed_checks or []),
    }


def _patch_database(monkeypatch, *, executor=None):
    migration = SimpleNamespace(
        planned=(smoke.LATEST_MIGRATION_VERSION,),
        applied=(),
        skipped=(smoke.LATEST_MIGRATION_VERSION,),
    )
    monkeypatch.setattr(
        smoke, "service_database_env", lambda *a, **k: "NEX_CX_TEST_DATABASE_URL"
    )
    monkeypatch.setattr(
        smoke, "service_database_url", lambda *a, **k: DATABASE_URL
    )
    monkeypatch.setattr(
        smoke, "run_service_migrations", lambda *a, **k: migration
    )
    return executor or (lambda **kwargs: _execution())


def test_smoke_is_opt_in_and_test_profile_only() -> None:
    skipped = smoke.run_cx_async_generation_postgres_smoke({})
    rejected = smoke.run_cx_async_generation_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.PROFILE_ENV: "dev"}
    )

    assert skipped["status"] == "SKIPPED"
    assert rejected["failure_code"] == "profile_not_allowed"
    assert smoke.summary_line(skipped).endswith(f"reason={smoke.SMOKE_ENV}")


def test_smoke_rejects_wrong_database_or_role(monkeypatch) -> None:
    monkeypatch.setattr(smoke, "service_database_env", lambda *a, **k: "DB")
    monkeypatch.setattr(
        smoke,
        "service_database_url",
        lambda *a, **k: DATABASE_URL.replace("nex_cx_test", "nex_cx_dev"),
    )

    result = smoke.run_cx_async_generation_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )

    assert result["failure_code"] == "target_not_allowed"
    assert smoke._target_url_allowed(DATABASE_URL) is True
    assert smoke._target_url_allowed(
        DATABASE_URL.replace("nex_cx_user", "postgres")
    ) is False
    assert smoke._target_url_allowed("postgresql://user:%zz@[") is False


def test_smoke_runs_migrations_and_mock_executor(monkeypatch) -> None:
    executor = _patch_database(monkeypatch)

    result = smoke.run_cx_async_generation_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}, executor=executor
    )

    assert result["status"] == "PASS"
    assert result["provider_mode"] == "deterministic_mock"
    assert result["remote_provider_required"] is False
    assert result["migration"]["skipped"] == [smoke.LATEST_MIGRATION_VERSION]
    assert "private" not in result["redacted_database_url"]


def test_smoke_fails_closed_for_checks_and_errors(monkeypatch) -> None:
    executor = _patch_database(
        monkeypatch,
        executor=lambda **kwargs: _execution(failed_checks=["retry_failed"]),
    )
    failed = smoke.run_cx_async_generation_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}, executor=executor
    )
    assert failed["failure_code"] == "async_generation_smoke_failed"
    assert failed["detail"] == "retry_failed"

    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *a, **k: (_ for _ in ()).throw(
            MigrationError(f"failed {DATABASE_URL}")
        ),
    )
    errored = smoke.run_cx_async_generation_postgres_smoke(
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
    unexpected = smoke.run_cx_async_generation_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )
    assert unexpected["detail"] == "RuntimeError"


def test_mock_client_helpers_summary_and_cli(monkeypatch, capsys) -> None:
    client = smoke.DeterministicMockGenerationClient(fail_first=True)
    with pytest.raises(Exception, match="timeout"):
        client.create_generation(
            {"alias": "mock"}, request_id="request", trace_id="trace"
        )
    response = client.create_generation(
        {"alias": "mock"}, request_id="request", trace_id="trace"
    )
    assert response["model_revision"] == "deterministic-mock-v1"
    assert client.call_count == 2
    assert client.failure_count == 1
    assert smoke.PRIVATE_MARKER in smoke._request_payload("one")["prompt"]
    assert smoke._headers("a" * 32, "request", "one")["Idempotency-Key"] == (
        "s99-one"
    )
    assert smoke._access_context("trace", "request", "owner").subject_id == (
        "owner"
    )
    assert smoke._wire(datetime(2026, 9, 24, tzinfo=UTC)) == (
        "2026-09-24T00:00:00Z"
    )
    assert smoke._redact_detail("plain", database_url="") == "plain"

    passing = {
        "status": "PASS",
        **_execution(),
        "remote_provider_required": False,
    }
    summary = smoke.summary_line(passing)
    assert "postgres_smoke=pass" in summary
    assert "recovery=RETRY_SCHEDULED" in summary
    assert "residue=0" in summary

    monkeypatch.setattr(
        smoke, "run_cx_async_generation_postgres_smoke", lambda: passing
    )
    assert smoke.main(["--summary"]) == 0
    assert "postgres_smoke=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        smoke,
        "run_cx_async_generation_postgres_smoke",
        lambda: {"status": "FAIL"},
    )
    assert smoke.main([]) == 1
