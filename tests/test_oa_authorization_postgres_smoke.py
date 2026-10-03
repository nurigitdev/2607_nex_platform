from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from nex_oa.authorization_postgres_smoke import (
    EXPECTED_CLEANUP_KEYS,
    REQUIRED_MIGRATION,
    _booleans,
    _integers,
    _mapping,
    _strings,
    evaluate_authorization_postgres_smoke,
)
import run_oa_authorization_postgres_smoke as runner


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
        "checks": {"protected_routes": True, "restart_readback": True},
        "db_observations": {
            "role_revision": 2,
            "group_count": 1,
            "group_member_count": 1,
            "group_role_count": 1,
            "event_count": 5,
            "server_actor_count": 5,
            "request_trace_count": 5,
            "revocation_event_count": 2,
            "revoked_session_count": 2,
            "active_session_count": 0,
            "restart_role_count": 1,
            "restart_group_count": 1,
            "restart_group_role_count": 1,
        },
        "cleanup_residue": {key: 0 for key in EXPECTED_CLEANUP_KEYS},
    }


def test_evaluator_accepts_actual_authorization_database_evidence() -> None:
    result = evaluate_authorization_postgres_smoke(_migration(), _workflow())
    assert result["status"] == "PASS"
    assert result["database_readiness"] == (
        "ACTUAL_TEST_DATABASE_AUTHORIZATION_VERIFIED"
    )
    assert all(result["checks"].values())
    assert result["failed_checks"] == []
    assert result["summary"] == {
        "migration_count": 2,
        "workflow_check_count": 2,
        "event_count": 5,
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
        "rows",
        "events",
        "sessions",
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
    elif mutation == "database":
        workflow["database"] = "nex_oa_dev"
    elif mutation == "role":
        workflow["role"] = "postgres"
    elif mutation == "runtime":
        workflow["runtime_mode"] = "memory"
    elif mutation == "workflow_empty":
        workflow["checks"] = {}
    elif mutation == "workflow_false":
        workflow["checks"]["protected_routes"] = False
    elif mutation == "rows":
        workflow["db_observations"]["role_revision"] = 1
    elif mutation == "events":
        workflow["db_observations"]["event_count"] = 4
    elif mutation == "sessions":
        workflow["db_observations"]["active_session_count"] = 1
    elif mutation == "restart":
        workflow["db_observations"]["restart_role_count"] = 0
    elif mutation == "residue_keys":
        workflow["cleanup_residue"].pop("authz_event_count")
    else:
        workflow["cleanup_residue"]["authz_event_count"] = 1

    result = evaluate_authorization_postgres_smoke(migration, workflow)
    assert result["status"] == "FAIL"
    assert result["failure_code"] == "oa_authorization_postgres_smoke_failed"
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
    skipped = runner.run_oa_authorization_postgres_smoke({})
    missing = runner.run_oa_authorization_postgres_smoke({runner.SMOKE_ENV: "1"})
    wrong = runner.run_oa_authorization_postgres_smoke(
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
        runner, "_execute_authorization_postgres_smoke", lambda **_kwargs: _workflow()
    )
    result = runner.run_oa_authorization_postgres_smoke(
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
            runner.MigrationError("invalid migration")
        ),
    )
    assert runner.run_oa_authorization_postgres_smoke(env)[
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
        "_execute_authorization_postgres_smoke",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("private")),
    )
    failed = runner.run_oa_authorization_postgres_smoke(env)
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

    with pytest.raises(RuntimeError, match="PostgreSQL smoke runtime is unavailable"):
        runner._execute_authorization_postgres_smoke(
            database_url=DATABASE_URL,
            runtime_environ={},
        )


def test_runner_helpers_summary_and_main_paths(monkeypatch, capsys) -> None:
    normal = runner._service_headers()
    admin = runner._service_headers("authorization:admin")
    assert normal["Authorization"].startswith("Bearer ")
    assert admin["Authorization"].startswith("Bearer ")
    assert normal["traceparent"].startswith("00-")

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
            "event_count": 5,
            "revoked_session_count": 2,
            "cleanup_residue_count": 0,
        },
    }
    assert "postgres_smoke=pass" in runner.summary_line(passing)
    assert "reason=" in runner.summary_line({"status": "SKIPPED"})
    assert "postgres_smoke=fail" in runner.summary_line({"status": "FAIL"})
    monkeypatch.setattr(
        runner, "run_oa_authorization_postgres_smoke", lambda: passing
    )
    assert runner.main(["--summary"]) == 0
    assert "events=5" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        runner,
        "run_oa_authorization_postgres_smoke",
        lambda: {"status": "FAIL"},
    )
    assert runner.main([]) == 1


@pytest.mark.skipif(
    os.getenv(runner.SMOKE_ENV) != "1",
    reason=f"{runner.SMOKE_ENV} is not enabled",
)
def test_protected_actual_oa_authorization_postgres_smoke() -> None:
    result = runner.run_oa_authorization_postgres_smoke()
    assert result["status"] == "PASS"
    assert result["workflow"]["database"] == "nex_oa_test"
    assert result["workflow"]["role"] == "nex_oa_user"
    assert result["summary"]["event_count"] == 5
    assert result["summary"]["revoked_session_count"] == 2
    assert result["summary"]["cleanup_residue_count"] == 0
