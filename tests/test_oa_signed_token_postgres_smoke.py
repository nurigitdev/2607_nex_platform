from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from nex_oa.signed_token_postgres_smoke import (
    EXPECTED_CLEANUP_KEYS,
    EXPECTED_MIGRATION_COUNT,
    REQUIRED_MIGRATION,
    _booleans,
    _integers,
    _mapping,
    _strings,
    evaluate_signed_token_postgres_smoke,
)
import run_oa_signed_token_postgres_smoke as runner


DATABASE_URL = "postgresql+psycopg://nex_oa_user:private@127.0.0.1:5432/nex_oa_test"


def _migration() -> dict:
    planned = tuple(f"migration-{index}" for index in range(15)) + (
        REQUIRED_MIGRATION,
    )
    return {"planned": planned, "applied": (), "skipped": planned}


def _workflow() -> dict:
    return {
        "database": "nex_oa_test",
        "role": "nex_oa_user",
        "runtime_mode": "postgres",
        "checks": {
            "principal_and_credential_persisted": True,
            "rs256_token_issued": True,
            "public_jwks_readback": True,
            "restart_validation_active": True,
            "revocation_persisted": True,
            "private_key_remained_in_memory": True,
            "raw_token_not_persisted": True,
            "jti_stored_as_digest": True,
        },
        "db_observations": {
            "migration_ledger_count": EXPECTED_MIGRATION_COUNT,
            "required_migration_count": 1,
            "principal_count": 1,
            "credential_count": 1,
            "signing_key_count": 1,
            "revocation_count": 1,
            "private_jwk_member_count": 0,
            "private_reference_count": 1,
            "raw_token_match_count": 0,
            "jti_digest_match_count": 1,
            "raw_jti_match_count": 0,
            "restart_key_count": 1,
            "restart_revocation_count": 1,
        },
        "cleanup_residue": {key: 0 for key in EXPECTED_CLEANUP_KEYS},
    }


def test_evaluator_accepts_actual_signed_token_database_evidence() -> None:
    result = evaluate_signed_token_postgres_smoke(_migration(), _workflow())
    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["database_readiness"] == "ACTUAL_TEST_DATABASE_SIGNED_TOKEN_VERIFIED"
    assert result["summary"] == {
        "migration_count": 16,
        "workflow_check_count": 8,
        "signing_key_count": 1,
        "revocation_count": 1,
        "cleanup_residue_count": 0,
    }


@pytest.mark.parametrize(
    "mutation",
    [
        "migration_plan", "migration_current", "migration_count", "database",
        "role", "runtime", "workflow_empty", "workflow_false", "rows",
        "private", "digest", "restart", "residue_keys", "residue_nonzero",
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
        workflow["db_observations"]["migration_ledger_count"] = 15
    elif mutation == "database":
        workflow["database"] = "nex_oa_dev"
    elif mutation == "role":
        workflow["role"] = "postgres"
    elif mutation == "runtime":
        workflow["runtime_mode"] = "memory"
    elif mutation == "workflow_empty":
        workflow["checks"] = {}
    elif mutation == "workflow_false":
        workflow["checks"]["rs256_token_issued"] = False
    elif mutation == "rows":
        workflow["db_observations"]["signing_key_count"] = 0
    elif mutation == "private":
        workflow["db_observations"]["private_jwk_member_count"] = 1
    elif mutation == "digest":
        workflow["db_observations"]["raw_jti_match_count"] = 1
    elif mutation == "restart":
        workflow["db_observations"]["restart_key_count"] = 0
    elif mutation == "residue_keys":
        workflow["cleanup_residue"].pop("signing_key_count")
    else:
        workflow["cleanup_residue"]["signing_key_count"] = 1
    result = evaluate_signed_token_postgres_smoke(migration, workflow)
    assert result["status"] == "FAIL"
    assert result["failure_code"] == "oa_signed_token_postgres_smoke_failed"
    assert result["failed_checks"]


def test_evaluator_helpers_accept_only_safe_shapes() -> None:
    assert _mapping({"ok": True}) == {"ok": True}
    assert _mapping(None) == {}
    assert _strings([1, "two"]) == ("1", "two")
    assert _strings("unsafe") == ()
    assert _booleans({"yes": True, "truthy": 1}) == {"yes": True, "truthy": False}
    assert _integers({"one": "1", "bad": "x", "bool": True}) == {"one": 1}


def test_runner_requires_opt_in_and_exact_target() -> None:
    assert runner.run_oa_signed_token_postgres_smoke({})["status"] == "SKIPPED"
    assert runner.run_oa_signed_token_postgres_smoke({runner.SMOKE_ENV: "1"})["failure_code"] == "database_url_missing"
    wrong = runner.run_oa_signed_token_postgres_smoke(
        {runner.SMOKE_ENV: "1", runner.DATABASE_ENV: DATABASE_URL.replace("nex_oa_test", "nex_oa_dev")}
    )
    assert wrong["failure_code"] == "target_not_allowed"
    assert runner._target_url_allowed(DATABASE_URL) is True
    assert runner._target_url_allowed("not-a-url") is False


def test_runner_migrates_executes_evaluates_and_redacts(monkeypatch) -> None:
    migration = SimpleNamespace(**_migration())
    monkeypatch.setattr(runner, "run_service_migrations", lambda *a, **k: migration)
    monkeypatch.setattr(runner, "_execute_signed_token_postgres_smoke", lambda **k: _workflow())
    result = runner.run_oa_signed_token_postgres_smoke(
        {runner.SMOKE_ENV: "1", runner.DATABASE_ENV: DATABASE_URL}
    )
    assert result["status"] == "PASS"
    assert result["redacted_database_url"] == "postgresql+psycopg://nex_oa_user:***@127.0.0.1:5432/nex_oa_test"
    assert result["migration"]["planned_count"] == 16
    assert "private" not in result["redacted_database_url"]


def test_runner_contains_configuration_and_execution_failures(monkeypatch) -> None:
    env = {runner.SMOKE_ENV: "1", runner.DATABASE_ENV: DATABASE_URL}
    monkeypatch.setattr(
        runner,
        "run_service_migrations",
        lambda *a, **k: (_ for _ in ()).throw(runner.MigrationError("bad")),
    )
    assert runner.run_oa_signed_token_postgres_smoke(env)["failure_code"] == "configuration_invalid"
    monkeypatch.setattr(
        runner,
        "run_service_migrations",
        lambda *a, **k: SimpleNamespace(planned=(), applied=(), skipped=()),
    )
    monkeypatch.setattr(
        runner,
        "_execute_signed_token_postgres_smoke",
        lambda **k: (_ for _ in ()).throw(RuntimeError("private")),
    )
    failed = runner.run_oa_signed_token_postgres_smoke(env)
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
    monkeypatch.setattr(runner, "build_service_app", lambda *a, **k: object())
    monkeypatch.setattr(runner, "attach_service_persistence_runtime", lambda *a, **k: runtime)
    with pytest.raises(RuntimeError, match="PostgreSQL runtime is unavailable"):
        runner._execute_signed_token_postgres_smoke(
            database_url=DATABASE_URL, runtime_environ={}
        )


def test_runner_helpers_summary_and_main_paths(monkeypatch, capsys) -> None:
    disposed: list[str] = []

    class Engine:
        def __init__(self, name: str) -> None:
            self.name = name

        def dispose(self) -> None:
            disposed.append(self.name)

    same = Engine("same")
    runner._dispose_runtime(SimpleNamespace(api_engine=same, worker_engine=same))
    runner._dispose_runtime(SimpleNamespace(api_engine=None, worker_engine=None))
    assert disposed == ["same"]
    passing = {
        "status": "PASS", "workflow": {"database": "nex_oa_test"},
        "summary": {"signing_key_count": 1, "revocation_count": 1, "cleanup_residue_count": 0},
    }
    assert "postgres_smoke=pass" in runner.summary_line(passing)
    assert "reason=" in runner.summary_line({"status": "SKIPPED"})
    assert "postgres_smoke=fail" in runner.summary_line({"status": "FAIL"})
    monkeypatch.setattr(runner, "run_oa_signed_token_postgres_smoke", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "keys=1" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(runner, "run_oa_signed_token_postgres_smoke", lambda: {"status": "FAIL"})
    assert runner.main([]) == 1


@pytest.mark.skipif(
    os.getenv(runner.SMOKE_ENV) != "1",
    reason=f"{runner.SMOKE_ENV} is not enabled",
)
def test_protected_actual_oa_signed_token_postgres_smoke() -> None:
    result = runner.run_oa_signed_token_postgres_smoke()
    assert result["status"] == "PASS"
    assert result["workflow"]["database"] == "nex_oa_test"
    assert result["workflow"]["role"] == "nex_oa_user"
    assert result["summary"]["migration_count"] == 16
    assert result["summary"]["signing_key_count"] == 1
    assert result["summary"]["revocation_count"] == 1
    assert result["summary"]["cleanup_residue_count"] == 0
