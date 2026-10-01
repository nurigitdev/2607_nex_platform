from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from nex_oa.database_drift_audit import CORE_OA_TABLES
from nex_oa.postgres_reaudit import (
    EXPECTED_CLEANUP_KEYS,
    EXPECTED_RESIDUE_KEYS,
    FORBIDDEN_PRIVATE_COLUMNS,
    _named_identifiers,
    _postgres_identifier,
    evaluate_oa_postgres_reaudit,
    expected_oa_postgres_state,
)
import run_oa_current_state_postgres_reaudit as runner


DATABASE_URL = (
    "postgresql+psycopg://nex_oa_user:private@127.0.0.1:5432/nex_oa_test"
)


def _migration(root: Path | None = None) -> dict[str, tuple[str, ...]]:
    versions = expected_oa_postgres_state(root or runner.ROOT)["migration_versions"]
    return {"planned": versions, "applied": (), "skipped": versions}


def _workflow() -> dict[str, Any]:
    return {
        "checks": {
            "runtime_mode": True,
            "credential_persisted": True,
            "membership_persisted": True,
            "session_persisted": True,
            "raw_password_not_stored": True,
        },
        "db_observations": {
            "credential_count": 1,
            "membership_count": 1,
            "session_count": 1,
            "session_status": "REVOKED",
            "hash_algorithm": "pbkdf2_sha256.v1",
            "raw_password_match_count": 0,
        },
        "cleanup_observations": {key: 1 for key in EXPECTED_CLEANUP_KEYS},
        "cleanup_residue": {key: 0 for key in EXPECTED_RESIDUE_KEYS},
    }


def _snapshot(root: Path | None = None) -> dict[str, Any]:
    expected = expected_oa_postgres_state(root or runner.ROOT)
    return {
        "database": "nex_oa_test",
        "role": "nex_oa_user",
        "migration_versions": expected["migration_versions"],
        "tables": sorted(CORE_OA_TABLES | {"schema_migrations"}),
        "indexes": expected["indexes"],
        "constraints": expected["constraints"],
        "columns": [{"table": "oa_local_credentials", "column": "password_hash"}],
        "longest_identifier": "ix_service_log_retention_history_idempotency",
        "longest_identifier_length": 44,
    }


def test_repository_postgres_reaudit_evaluation_passes() -> None:
    result = evaluate_oa_postgres_reaudit(_snapshot(), _migration(), _workflow())

    assert result["status"] == "PASS"
    assert result["database_readiness"] == (
        "ACTUAL_TEST_DATABASE_IDENTITY_FLOW_VERIFIED"
    )
    assert all(result["checks"].values())
    assert result["summary"]["expected_migration_count"] == 13
    assert result["summary"]["core_table_count"] == 5
    assert result["summary"]["workflow_check_count"] == 5
    assert result["forbidden_private_columns"] == []
    assert result["workflow_evidence"]["cleanup_residue"] == {
        key: 0 for key in EXPECTED_RESIDUE_KEYS
    }
    assert result["privacy_policy"]["database_url"] == "redacted"


@pytest.mark.parametrize(
    "mutation",
    [
        "database",
        "role",
        "migration_plan",
        "migration_execution",
        "ledger",
        "table",
        "index",
        "constraint",
        "identifier",
        "private_column",
        "workflow",
        "cleanup",
        "residue",
    ],
)
def test_postgres_reaudit_fails_closed_for_each_drift(mutation: str) -> None:
    snapshot = _snapshot()
    migration = _migration()
    workflow = _workflow()
    if mutation == "database":
        snapshot["database"] = "nex_oa_dev"
    elif mutation == "role":
        snapshot["role"] = "postgres"
    elif mutation == "migration_plan":
        migration["planned"] = migration["planned"][:-1]
    elif mutation == "migration_execution":
        migration["applied"] = migration["skipped"][:1]
    elif mutation == "ledger":
        snapshot["migration_versions"] = (
            *snapshot["migration_versions"][:-1],
            "9999_extra",
        )
    elif mutation == "table":
        snapshot["tables"].remove("oa_subjects")
    elif mutation == "index":
        snapshot["indexes"] = snapshot["indexes"][:-1]
    elif mutation == "constraint":
        snapshot["constraints"] = snapshot["constraints"][:-1]
    elif mutation == "identifier":
        snapshot["longest_identifier_length"] = 64
    elif mutation == "private_column":
        snapshot["columns"].append(
            {"table": "oa_subjects", "column": next(iter(FORBIDDEN_PRIVATE_COLUMNS))}
        )
    elif mutation == "workflow":
        workflow["checks"]["session_persisted"] = False
    elif mutation == "cleanup":
        workflow["cleanup_observations"]["deleted_sessions"] = 0
    else:
        workflow["cleanup_residue"]["session_count"] = 1

    result = evaluate_oa_postgres_reaudit(snapshot, migration, workflow)

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "oa_postgres_reaudit_failed"
    assert result["failed_checks"]


def test_expected_state_and_identifier_helpers_fail_closed_without_inputs(
    tmp_path: Path,
) -> None:
    expected = expected_oa_postgres_state()

    assert len(expected["migration_versions"]) == 13
    assert expected["indexes"]
    assert expected["constraints"]
    assert _named_identifiers(
        "CREATE INDEX IDX_X ON x (id)",
        r"INDEX\s+([a-z_]+)",
    ) == {"idx_x"}
    assert _postgres_identifier("short_name") == "short_name"
    assert len(_postgres_identifier("x" * 80)) == 63

    result = evaluate_oa_postgres_reaudit({}, {}, {}, root=tmp_path)
    assert result["status"] == "FAIL"
    assert result["summary"]["expected_migration_count"] == 0


class _Cursor:
    def __init__(self, expected: dict[str, tuple[str, ...]]) -> None:
        self.expected = expected
        self.query = ""

    def __enter__(self):
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def execute(self, query: str, _parameters: tuple[str, ...] = ()) -> None:
        self.query = query

    def fetchall(self) -> list[tuple[str, ...]]:
        if "schema_migrations" in self.query:
            return [(item,) for item in self.expected["migration_versions"]]
        if "information_schema.tables" in self.query:
            return [(item,) for item in sorted(CORE_OA_TABLES | {"schema_migrations"})]
        if "pg_indexes" in self.query:
            return [(item,) for item in self.expected["indexes"]]
        if "table_constraints" in self.query:
            return [(item,) for item in self.expected["constraints"]]
        if "information_schema.columns" in self.query:
            return [("oa_local_credentials", "password_hash")]
        raise AssertionError(self.query)

    def fetchone(self) -> tuple[Any, ...]:
        if "current_database" in self.query:
            return ("nex_oa_test", "nex_oa_user")
        if "oa_user_sessions" in self.query:
            return (0, 0, 0, 0, 0)
        raise AssertionError(self.query)


class _Connection:
    def __init__(self) -> None:
        self.expected = expected_oa_postgres_state()
        self.rollbacks = 0

    def cursor(self) -> _Cursor:
        return _Cursor(self.expected)

    def rollback(self) -> None:
        self.rollbacks += 1


def test_database_snapshot_and_cleanup_residue_read_actual_shapes() -> None:
    connection = _Connection()
    snapshot = runner._collect_database_snapshot(
        DATABASE_URL,
        connect=lambda _url: nullcontext(connection),
    )
    residue = runner._collect_cleanup_residue(
        DATABASE_URL,
        tenant_id="tenant",
        subject_id="subject",
        normalized_employee_id="employee",
        session_id="session",
        connect=lambda _url: nullcontext(connection),
    )

    assert snapshot["database"] == "nex_oa_test"
    assert len(snapshot["migration_versions"]) == 13
    assert residue == {key: 0 for key in EXPECTED_RESIDUE_KEYS}
    assert connection.rollbacks == 2


def test_runner_requires_opt_in_url_and_exact_test_target() -> None:
    skipped = runner.run_oa_current_state_postgres_reaudit({})
    missing = runner.run_oa_current_state_postgres_reaudit({runner.SMOKE_ENV: "1"})
    wrong = runner.run_oa_current_state_postgres_reaudit(
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


def test_runner_executes_migration_catalog_workflow_and_residue(monkeypatch) -> None:
    migration_result = SimpleNamespace(**_migration())
    workflow = {
        **_workflow(),
        "tenant_id": "tenant",
        "subject_id": "subject",
        "normalized_employee_id": "employee",
        "session_id": "session",
    }
    monkeypatch.setattr(
        runner,
        "run_service_migrations",
        lambda *_args, **_kwargs: migration_result,
    )
    monkeypatch.setattr(runner, "_collect_database_snapshot", lambda _url: _snapshot())
    monkeypatch.setattr(
        runner,
        "_execute_oa_user_login_postgres_smoke",
        lambda **_kwargs: dict(workflow),
    )
    monkeypatch.setattr(
        runner,
        "_collect_cleanup_residue",
        lambda *_args, **_kwargs: {key: 0 for key in EXPECTED_RESIDUE_KEYS},
    )
    env = {runner.SMOKE_ENV: "1", runner.DATABASE_ENV: DATABASE_URL}

    result = runner.run_oa_current_state_postgres_reaudit(env)

    assert result["status"] == "PASS"
    assert result["redacted_database_url"].endswith(
        "@127.0.0.1:5432/nex_oa_test"
    )
    assert "private" not in result["redacted_database_url"]

    monkeypatch.setattr(
        runner,
        "run_service_migrations",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("private")),
    )
    failed = runner.run_oa_current_state_postgres_reaudit(env)
    assert failed == {
        "smoke_schema_version": runner.SCHEMA_VERSION,
        "status": "FAIL",
        "failure_code": "execution_failed",
        "detail": "RuntimeError",
    }


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = evaluate_oa_postgres_reaudit(_snapshot(), _migration(), _workflow())

    assert "postgres_reaudit=pass" in runner.summary_line(passing)
    assert "migrations=13/13" in runner.summary_line(passing)
    assert "database=not-run" in runner.summary_line({"status": "SKIPPED"})

    monkeypatch.setattr(runner, "load_env_file", lambda _path: None)
    monkeypatch.setattr(
        runner,
        "run_oa_current_state_postgres_reaudit",
        lambda: passing,
    )
    assert runner.main(["--summary"]) == 0
    assert "failed_checks=0" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_oa_current_state_postgres_reaudit",
        lambda: {"status": "FAIL"},
    )
    assert runner.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
