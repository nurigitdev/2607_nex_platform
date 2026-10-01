from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from nex_oa.credential_security_postgres_smoke import (
    EXPECTED_CLEANUP_KEYS,
    EXPECTED_EVENT_COUNTS,
    REQUIRED_MIGRATION,
    _booleans,
    _integers,
    _mapping,
    _strings,
    evaluate_credential_security_postgres_smoke,
)
import run_oa_credential_security_postgres_smoke as runner


DATABASE_URL = (
    "postgresql+psycopg://nex_oa_user:private@127.0.0.1:5432/nex_oa_test"
)


def _migration() -> dict:
    return {
        "planned": ("0023_baseline", REQUIRED_MIGRATION),
        "applied": (),
        "skipped": ("0023_baseline", REQUIRED_MIGRATION),
    }


def _workflow() -> dict:
    return {
        "database": "nex_oa_test",
        "role": "nex_oa_user",
        "runtime_mode": "postgres",
        "checks": {
            "lockout": True,
            "rehash": True,
            "rotation": True,
            "privacy": True,
        },
        "db_observations": {
            "credential_status": "ACTIVE",
            "password_hash_algorithm": "argon2id.v1",
            "failed_attempt_count": 0,
            "locked_at": None,
            "revoked_session_count": 2,
            "active_session_count": 0,
            "event_counts": dict(EXPECTED_EVENT_COUNTS),
            "succeeded_event_count": 6,
            "blocked_event_count": 6,
            "failed_event_count": 0,
        },
        "cleanup_residue": {key: 0 for key in EXPECTED_CLEANUP_KEYS},
    }


def test_evaluator_accepts_actual_credential_security_evidence() -> None:
    result = evaluate_credential_security_postgres_smoke(_migration(), _workflow())

    assert result["status"] == "PASS"
    assert result["database_readiness"] == (
        "ACTUAL_TEST_DATABASE_CREDENTIAL_SECURITY_VERIFIED"
    )
    assert all(result["checks"].values())
    assert result["failed_checks"] == []
    assert result["summary"] == {
        "migration_count": 2,
        "workflow_check_count": 4,
        "auth_event_count": 12,
        "revoked_session_count": 2,
        "cleanup_residue_count": 0,
    }


@pytest.mark.parametrize(
    "mutation",
    [
        "migration_plan",
        "migration_current",
        "database",
        "role",
        "runtime",
        "workflow_empty",
        "workflow_false",
        "credential_status",
        "hash_algorithm",
        "failed_attempts",
        "locked_at",
        "sessions_revoked",
        "sessions_active",
        "event_type",
        "event_success",
        "event_blocked",
        "event_failed",
        "residue_keys",
        "residue_nonzero",
    ],
)
def test_evaluator_fails_closed_for_each_evidence_boundary(mutation: str) -> None:
    migration = _migration()
    workflow = _workflow()
    observations = workflow["db_observations"]
    if mutation == "migration_plan":
        migration["planned"] = ()
    elif mutation == "migration_current":
        migration["skipped"] = ()
    elif mutation == "database":
        workflow["database"] = "nex_oa_dev"
    elif mutation == "role":
        workflow["role"] = "postgres"
    elif mutation == "runtime":
        workflow["runtime_mode"] = "memory"
    elif mutation == "workflow_empty":
        workflow["checks"] = {}
    elif mutation == "workflow_false":
        workflow["checks"]["privacy"] = False
    elif mutation == "credential_status":
        observations["credential_status"] = "LOCKED"
    elif mutation == "hash_algorithm":
        observations["password_hash_algorithm"] = "pbkdf2_sha256.v1"
    elif mutation == "failed_attempts":
        observations["failed_attempt_count"] = 1
    elif mutation == "locked_at":
        observations["locked_at"] = "2026-01-01T00:00:00Z"
    elif mutation == "sessions_revoked":
        observations["revoked_session_count"] = 1
    elif mutation == "sessions_active":
        observations["active_session_count"] = 1
    elif mutation == "event_type":
        observations["event_counts"]["LOGIN_FAILED"] = 4
    elif mutation == "event_success":
        observations["succeeded_event_count"] = 5
    elif mutation == "event_blocked":
        observations["blocked_event_count"] = 5
    elif mutation == "event_failed":
        observations["failed_event_count"] = 1
    elif mutation == "residue_keys":
        workflow["cleanup_residue"].pop("event_count")
    else:
        workflow["cleanup_residue"]["event_count"] = 1

    result = evaluate_credential_security_postgres_smoke(migration, workflow)

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "oa_credential_security_postgres_smoke_failed"
    assert result["database_readiness"] == "BLOCKED"
    assert result["failed_checks"]


def test_evaluator_helpers_accept_only_safe_shapes() -> None:
    assert _mapping({"ok": True}) == {"ok": True}
    assert _mapping(None) == {}
    assert _strings([1, "two"]) == ("1", "two")
    assert _strings("unsafe") == ()
    assert _booleans({"true": True, "truthy": 1}) == {
        "true": True,
        "truthy": False,
    }
    assert _integers({"one": "1", "bad": "x", "bool": True}) == {"one": 1}


def test_runner_requires_opt_in_and_exact_test_target() -> None:
    skipped = runner.run_oa_credential_security_postgres_smoke({})
    missing = runner.run_oa_credential_security_postgres_smoke(
        {runner.SMOKE_ENV: "1"}
    )
    wrong = runner.run_oa_credential_security_postgres_smoke(
        {
            runner.SMOKE_ENV: "1",
            runner.DATABASE_ENV: DATABASE_URL.replace("nex_oa_test", "nex_oa_dev"),
        }
    )

    assert skipped["status"] == "SKIPPED"
    assert missing["failure_code"] == "database_url_missing"
    assert wrong["failure_code"] == "target_not_allowed"
    assert runner._target_url_allowed(DATABASE_URL) is True
    assert runner._target_url_allowed("not-a-url") is False


def test_runner_migrates_executes_evaluates_and_redacts(monkeypatch) -> None:
    migration = SimpleNamespace(
        planned=_migration()["planned"],
        applied=(),
        skipped=_migration()["skipped"],
    )
    monkeypatch.setattr(
        runner, "run_service_migrations", lambda *_args, **_kwargs: migration
    )
    monkeypatch.setattr(
        runner,
        "_execute_credential_security_postgres_smoke",
        lambda **_kwargs: _workflow(),
    )

    result = runner.run_oa_credential_security_postgres_smoke(
        {runner.SMOKE_ENV: "1", runner.DATABASE_ENV: DATABASE_URL}
    )

    assert result["status"] == "PASS"
    assert result["redacted_database_url"] == (
        "postgresql+psycopg://nex_oa_user:***@127.0.0.1:5432/nex_oa_test"
    )
    assert result["migration"]["planned_count"] == 2
    assert "private" not in str(result)


def test_runner_contains_configuration_and_execution_failures(monkeypatch) -> None:
    env = {runner.SMOKE_ENV: "1", runner.DATABASE_ENV: DATABASE_URL}
    monkeypatch.setattr(
        runner,
        "run_service_migrations",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            runner.MigrationError("invalid")
        ),
    )
    assert runner.run_oa_credential_security_postgres_smoke(env)[
        "failure_code"
    ] == "configuration_invalid"

    monkeypatch.setattr(
        runner,
        "run_service_migrations",
        lambda *_args, **_kwargs: SimpleNamespace(
            planned=(), applied=(), skipped=()
        ),
    )
    monkeypatch.setattr(
        runner,
        "_execute_credential_security_postgres_smoke",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("private")),
    )
    failure = runner.run_oa_credential_security_postgres_smoke(env)
    assert failure["failure_code"] == "execution_failed"
    assert failure["detail"] == "RuntimeError"


def test_runner_privacy_helpers_summary_and_main(monkeypatch, capsys) -> None:
    assert runner._events_are_private(
        [{"event_type": "LOGIN_FAILED", "details": {"error_code": "blocked"}}]
    )
    assert runner._events_are_private([{"details": {"session_id": "private"}}]) is False
    assert runner._events_are_private(
        [{"details": {"value": runner.INITIAL_PASSWORD}}]
    ) is False
    headers = runner._service_headers()
    assert headers["Authorization"].startswith("Bearer ")
    assert headers["traceparent"].startswith("00-")

    passing = {
        "status": "PASS",
        "workflow": {"database": "nex_oa_test"},
        "summary": {
            "auth_event_count": 12,
            "revoked_session_count": 2,
            "cleanup_residue_count": 0,
        },
    }
    assert "postgres_smoke=pass" in runner.summary_line(passing)
    assert "reason=" in runner.summary_line({"status": "SKIPPED"})
    assert "postgres_smoke=fail" in runner.summary_line({"status": "FAIL"})

    monkeypatch.setattr(
        runner, "run_oa_credential_security_postgres_smoke", lambda: passing
    )
    assert runner.main(["--summary"]) == 0
    assert "events=12" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        runner,
        "run_oa_credential_security_postgres_smoke",
        lambda: {"status": "FAIL"},
    )
    assert runner.main([]) == 1


@pytest.mark.skipif(
    os.getenv(runner.SMOKE_ENV) != "1",
    reason=f"{runner.SMOKE_ENV} is not enabled",
)
def test_protected_actual_oa_credential_security_postgres_smoke() -> None:
    result = runner.run_oa_credential_security_postgres_smoke()

    assert result["status"] == "PASS"
    assert result["workflow"]["database"] == "nex_oa_test"
    assert result["workflow"]["role"] == "nex_oa_user"
    assert result["summary"]["auth_event_count"] == 12
    assert result["summary"]["revoked_session_count"] == 2
    assert result["summary"]["cleanup_residue_count"] == 0
