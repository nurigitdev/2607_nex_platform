from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from nex_oa.service_principal_postgres_smoke import (
    EXPECTED_CLEANUP_KEYS,
    REQUIRED_MIGRATION,
    _booleans,
    _integers,
    _mapping,
    _strings,
    evaluate_service_principal_postgres_smoke,
)
import run_oa_service_principal_postgres_smoke as runner


DATABASE_URL = (
    "postgresql+psycopg://nex_oa_user:private@127.0.0.1:5432/nex_oa_test"
)


def _migration() -> dict:
    planned = tuple(f"migration-{index}" for index in range(14)) + (
        REQUIRED_MIGRATION,
    )
    return {"planned": planned, "applied": (), "skipped": planned}


def _workflow() -> dict:
    return {
        "database": "nex_oa_test",
        "role": "nex_oa_user",
        "runtime_mode": "postgres",
        "checks": {
            "protected_create": True,
            "one_time_issue": True,
            "initial_secret_verified": True,
            "rotation_persisted": True,
            "old_secret_grace_verified": True,
            "replacement_secret_verified": True,
            "protected_readback": True,
            "revocation_persisted": True,
            "revoked_secret_rejected": True,
            "restart_readback": True,
        },
        "db_observations": {
            "migration_ledger_count": 15,
            "required_migration_count": 1,
            "principal_count": 1,
            "credential_count": 2,
            "rotating_credential_count": 1,
            "revoked_credential_count": 1,
            "argon2id_hash_count": 2,
            "plaintext_match_count": 0,
            "distinct_secret_hint_count": 2,
            "restart_principal_count": 1,
            "restart_credential_count": 2,
        },
        "cleanup_residue": {key: 0 for key in EXPECTED_CLEANUP_KEYS},
    }


def test_evaluator_accepts_actual_service_principal_database_evidence() -> None:
    result = evaluate_service_principal_postgres_smoke(_migration(), _workflow())

    assert result["status"] == "PASS"
    assert result["database_readiness"] == (
        "ACTUAL_TEST_DATABASE_SERVICE_PRINCIPAL_VERIFIED"
    )
    assert all(result["checks"].values())
    assert result["failed_checks"] == []
    assert result["summary"] == {
        "migration_count": 15,
        "workflow_check_count": 10,
        "persisted_credential_count": 2,
        "argon2id_hash_count": 2,
        "cleanup_residue_count": 0,
    }


@pytest.mark.parametrize(
    "mutation",
    [
        "migration_plan",
        "migration_current",
        "migration_count",
        "database",
        "role",
        "runtime",
        "workflow_empty",
        "workflow_false",
        "rows",
        "hashes",
        "restart",
        "residue_keys",
        "residue_nonzero",
    ],
)
def test_evaluator_fails_closed_for_each_boundary(mutation: str) -> None:
    migration = _migration()
    workflow = _workflow()
    if mutation == "migration_plan":
        migration["planned"] = ()
    elif mutation == "migration_current":
        migration["skipped"] = ()
    elif mutation == "migration_count":
        workflow["db_observations"]["migration_ledger_count"] = 14
    elif mutation == "database":
        workflow["database"] = "nex_oa_dev"
    elif mutation == "role":
        workflow["role"] = "postgres"
    elif mutation == "runtime":
        workflow["runtime_mode"] = "memory"
    elif mutation == "workflow_empty":
        workflow["checks"] = {}
    elif mutation == "workflow_false":
        workflow["checks"]["protected_create"] = False
    elif mutation == "rows":
        workflow["db_observations"]["credential_count"] = 1
    elif mutation == "hashes":
        workflow["db_observations"]["plaintext_match_count"] = 1
    elif mutation == "restart":
        workflow["db_observations"]["restart_credential_count"] = 1
    elif mutation == "residue_keys":
        workflow["cleanup_residue"].pop("credential_count")
    else:
        workflow["cleanup_residue"]["credential_count"] = 1

    result = evaluate_service_principal_postgres_smoke(migration, workflow)

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "oa_service_principal_postgres_smoke_failed"
    assert result["database_readiness"] == "BLOCKED"
    assert result["failed_checks"]


def test_evaluator_helpers_normalize_only_safe_shapes() -> None:
    assert _mapping({"ok": True}) == {"ok": True}
    assert _mapping(None) == {}
    assert _strings([1, "two"]) == ("1", "two")
    assert _strings("unsafe") == ()
    assert _booleans({"true": True, "truthy": 1}) == {
        "true": True,
        "truthy": False,
    }
    assert _integers({"one": "1", "bad": "x", "bool": True}) == {"one": 1}


def test_runner_requires_opt_in_and_exact_target() -> None:
    skipped = runner.run_oa_service_principal_postgres_smoke({})
    missing = runner.run_oa_service_principal_postgres_smoke({runner.SMOKE_ENV: "1"})
    wrong = runner.run_oa_service_principal_postgres_smoke(
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
    migration = SimpleNamespace(**_migration())
    monkeypatch.setattr(
        runner, "run_service_migrations", lambda *_args, **_kwargs: migration
    )
    monkeypatch.setattr(
        runner,
        "_execute_service_principal_postgres_smoke",
        lambda **_kwargs: _workflow(),
    )
    result = runner.run_oa_service_principal_postgres_smoke(
        {runner.SMOKE_ENV: "1", runner.DATABASE_ENV: DATABASE_URL}
    )
    assert result["status"] == "PASS"
    assert result["redacted_database_url"] == (
        "postgresql+psycopg://nex_oa_user:***@127.0.0.1:5432/nex_oa_test"
    )
    assert result["migration"]["planned_count"] == 15
    assert "private" not in str(result)


def test_runner_contains_configuration_and_execution_failures(monkeypatch) -> None:
    env = {runner.SMOKE_ENV: "1", runner.DATABASE_ENV: DATABASE_URL}
    monkeypatch.setattr(
        runner,
        "run_service_migrations",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            runner.MigrationError("invalid migration")
        ),
    )
    assert runner.run_oa_service_principal_postgres_smoke(env)[
        "failure_code"
    ] == "configuration_invalid"

    monkeypatch.setattr(
        runner,
        "run_service_migrations",
        lambda *_args, **_kwargs: SimpleNamespace(planned=(), applied=(), skipped=()),
    )
    monkeypatch.setattr(
        runner,
        "_execute_service_principal_postgres_smoke",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("private")),
    )
    failed = runner.run_oa_service_principal_postgres_smoke(env)
    assert failed["failure_code"] == "execution_failed"
    assert failed["detail"] == "RuntimeError"


@pytest.mark.parametrize(
    "runtime",
    [
        SimpleNamespace(api_session_factory=None, api_engine=object()),
        SimpleNamespace(api_session_factory=object(), api_engine=None),
    ],
)
def test_execute_rejects_incomplete_postgres_runtime(monkeypatch, runtime) -> None:
    monkeypatch.setattr(runner, "build_service_app", lambda _spec: object())
    monkeypatch.setattr(
        runner,
        "attach_service_persistence_runtime",
        lambda *_args, **_kwargs: runtime,
    )
    with pytest.raises(RuntimeError, match="PostgreSQL runtime is unavailable"):
        runner._execute_service_principal_postgres_smoke(
            database_url=DATABASE_URL, runtime_environ={}
        )


def test_runner_helpers_summary_and_main_paths(monkeypatch, capsys) -> None:
    headers = runner._service_headers("service-principal:read")
    assert headers["Authorization"].startswith("Bearer ")
    assert headers["traceparent"].startswith("00-")

    disposed: list[str] = []

    class Engine:
        def __init__(self, name: str) -> None:
            self.name = name

        def dispose(self) -> None:
            disposed.append(self.name)

    runner._dispose_runtime(
        SimpleNamespace(api_engine=Engine("api"), worker_engine=Engine("worker"))
    )
    runner._dispose_runtime(SimpleNamespace(api_engine=None, worker_engine=None))
    assert disposed == ["api", "worker"]

    passing = {
        "status": "PASS",
        "workflow": {"database": "nex_oa_test"},
        "summary": {
            "persisted_credential_count": 2,
            "argon2id_hash_count": 2,
            "cleanup_residue_count": 0,
        },
    }
    assert "postgres_smoke=pass" in runner.summary_line(passing)
    assert "reason=" in runner.summary_line({"status": "SKIPPED"})
    assert "postgres_smoke=fail" in runner.summary_line({"status": "FAIL"})
    monkeypatch.setattr(
        runner, "run_oa_service_principal_postgres_smoke", lambda: passing
    )
    assert runner.main(["--summary"]) == 0
    assert "credentials=2" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        runner,
        "run_oa_service_principal_postgres_smoke",
        lambda: {"status": "FAIL"},
    )
    assert runner.main([]) == 1


@pytest.mark.skipif(
    os.getenv(runner.SMOKE_ENV) != "1",
    reason=f"{runner.SMOKE_ENV} is not enabled",
)
def test_protected_actual_oa_service_principal_postgres_smoke() -> None:
    result = runner.run_oa_service_principal_postgres_smoke()

    assert result["status"] == "PASS"
    assert result["workflow"]["database"] == "nex_oa_test"
    assert result["workflow"]["role"] == "nex_oa_user"
    assert result["summary"]["migration_count"] == 15
    assert result["summary"]["persisted_credential_count"] == 2
    assert result["summary"]["argon2id_hash_count"] == 2
    assert result["summary"]["cleanup_residue_count"] == 0
