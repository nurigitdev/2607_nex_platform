from __future__ import annotations

from contextlib import nullcontext
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from nex_oa.service_principal_boundary import PROPOSED_TABLES
from nex_oa.trust_postgres_baseline import (
    EXPECTED_CLEANUP_KEYS,
    EXPECTED_RESIDUE_KEYS,
    evaluate_trust_postgres_baseline,
    expected_migration_versions,
)
import run_oa_trust_postgres_baseline as runner


DATABASE_URL = (
    "postgresql+psycopg://nex_oa_user:private@127.0.0.1:5432/nex_oa_test"
)


def _snapshot(root: Path = runner.ROOT) -> dict[str, Any]:
    return {
        "database": "nex_oa_test",
        "role": "nex_oa_user",
        "server_kind": "PostgreSQL",
        "migration_versions": expected_migration_versions(root),
        "tables": ["schema_migrations", "oa_user_sessions"],
        "columns": [
            {"table": "oa_user_sessions", "column": "session_id"},
            {"table": "oa_local_credentials", "column": "password_hash"},
        ],
    }


def _migration(root: Path = runner.ROOT) -> dict[str, Any]:
    versions = expected_migration_versions(root)
    return {"planned": versions, "applied": (), "skipped": versions}


def _workflow() -> dict[str, Any]:
    return {
        "checks": {"issued": True, "introspected": True, "revoked": True},
        "cleanup_observations": {
            name: 1 for name in EXPECTED_CLEANUP_KEYS
        },
        "cleanup_residue": {name: 0 for name in EXPECTED_RESIDUE_KEYS},
    }


def _mock() -> dict[str, Any]:
    return {
        "issued": True,
        "validated": True,
        "storage_mode": "memory_only",
        "database_mutation": False,
        "token_fingerprint": "0123456789abcdef",
    }


def test_trust_postgres_baseline_evaluation_passes() -> None:
    result = evaluate_trust_postgres_baseline(
        snapshot=_snapshot(),
        migration=_migration(),
        workflow=_workflow(),
        mock_compatibility=_mock(),
    )

    assert result["status"] == "PASS"
    assert result["database"] == "nex_oa_test"
    assert result["role"] == "nex_oa_user"
    assert all(result["checks"].values())
    assert result["summary"]["cleanup_residue_count"] == 0
    assert result["forbidden_columns"] == []
    assert result["premature_tables"] == []


@pytest.mark.parametrize(
    "mutation",
    [
        "server",
        "database",
        "role",
        "plan",
        "execution",
        "ledger",
        "column",
        "table",
        "workflow",
        "cleanup",
        "residue",
        "mock_issue",
        "mock_validate",
        "mock_storage",
        "mock_mutation",
        "mock_fingerprint",
        "mock_raw_token",
    ],
)
def test_trust_postgres_baseline_fails_closed_for_drift(mutation: str) -> None:
    snapshot = _snapshot()
    migration = _migration()
    workflow = _workflow()
    mock = _mock()
    if mutation == "server":
        snapshot["server_kind"] = "SQLite"
    elif mutation == "database":
        snapshot["database"] = "nex_oa_dev"
    elif mutation == "role":
        snapshot["role"] = "postgres"
    elif mutation == "plan":
        migration["planned"] = migration["planned"][:-1]
    elif mutation == "execution":
        migration["applied"] = migration["skipped"][:1]
    elif mutation == "ledger":
        snapshot["migration_versions"] = snapshot["migration_versions"][:-1]
    elif mutation == "column":
        snapshot["columns"].append(
            {"table": "oa_user_sessions", "column": "access_token"}
        )
    elif mutation == "table":
        snapshot["tables"].append(PROPOSED_TABLES[0])
    elif mutation == "workflow":
        workflow["checks"]["revoked"] = False
    elif mutation == "cleanup":
        workflow["cleanup_observations"]["deleted_sessions"] = 0
    elif mutation == "residue":
        workflow["cleanup_residue"]["session_count"] = 1
    elif mutation == "mock_issue":
        mock["issued"] = False
    elif mutation == "mock_validate":
        mock["validated"] = False
    elif mutation == "mock_storage":
        mock["storage_mode"] = "postgres"
    elif mutation == "mock_mutation":
        mock["database_mutation"] = True
    elif mutation == "mock_fingerprint":
        mock["token_fingerprint"] = ""
    else:
        mock["access_token"] = "test-only"

    result = evaluate_trust_postgres_baseline(
        snapshot=snapshot,
        migration=migration,
        workflow=workflow,
        mock_compatibility=mock,
    )

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "oa_trust_postgres_baseline_failed"
    assert result["failed_checks"]


def test_expected_migrations_handles_empty_root(tmp_path: Path) -> None:
    assert expected_migration_versions(tmp_path) == ()


class _Cursor:
    def __init__(self) -> None:
        self.query = ""

    def __enter__(self):
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def execute(self, query: str, _params: tuple[str, ...] = ()) -> None:
        self.query = query

    def fetchone(self) -> tuple[Any, ...]:
        if "version()" in self.query:
            return ("nex_oa_test", "nex_oa_user", "PostgreSQL 17")
        if "oa_user_sessions" in self.query:
            return (0, 0, 0, 0)
        raise AssertionError(self.query)

    def fetchall(self) -> list[tuple[str, ...]]:
        if "schema_migrations" in self.query:
            return [(version,) for version in expected_migration_versions()]
        if "information_schema.tables" in self.query:
            return [("oa_user_sessions",), ("schema_migrations",)]
        if "information_schema.columns" in self.query:
            return [("oa_user_sessions", "session_id")]
        raise AssertionError(self.query)


class _Connection:
    def __init__(self) -> None:
        self.rollback_count = 0

    def cursor(self) -> _Cursor:
        return _Cursor()

    def rollback(self) -> None:
        self.rollback_count += 1


def test_snapshot_and_residue_collect_actual_postgres_shapes() -> None:
    connection = _Connection()
    snapshot = runner._collect_snapshot(
        DATABASE_URL,
        connect=lambda _url: nullcontext(connection),
    )
    residue = runner._collect_cleanup_residue(
        DATABASE_URL,
        tenant_id="tenant",
        subject_id="subject",
        session_id="session",
        connect=lambda _url: nullcontext(connection),
    )

    assert snapshot["server_kind"] == "PostgreSQL"
    assert len(snapshot["migration_versions"]) == len(expected_migration_versions())
    assert residue == {name: 0 for name in EXPECTED_RESIDUE_KEYS}
    assert connection.rollback_count == 2


def test_snapshot_identifies_non_postgres_server() -> None:
    class Cursor(_Cursor):
        def fetchone(self) -> tuple[Any, ...]:
            return ("nex_oa_test", "nex_oa_user", "Other DB")

    class Connection(_Connection):
        def cursor(self) -> Cursor:
            return Cursor()

    snapshot = runner._collect_snapshot(
        DATABASE_URL,
        connect=lambda _url: nullcontext(Connection()),
    )
    assert snapshot["server_kind"] == "UNKNOWN"


def test_runner_opt_in_target_and_helpers() -> None:
    assert runner.run_oa_trust_postgres_baseline({})["status"] == "SKIPPED"
    missing = runner.run_oa_trust_postgres_baseline({runner.SMOKE_ENV: "1"})
    wrong = runner.run_oa_trust_postgres_baseline(
        {
            runner.SMOKE_ENV: "1",
            runner.DATABASE_ENV: DATABASE_URL.replace("nex_oa_test", "nex_oa_dev"),
        }
    )
    assert missing["failure_code"] == "database_url_missing"
    assert wrong["failure_code"] == "target_not_allowed"
    assert runner._target_url_allowed(DATABASE_URL) is True
    assert runner._target_url_allowed("not-a-url") is False
    mock = runner._mock_compatibility_evidence()
    assert mock["issued"] is True
    assert mock["validated"] is True
    assert "access_token" not in mock


def test_runner_composes_migration_workflow_snapshot_and_residue(monkeypatch) -> None:
    versions = expected_migration_versions()
    monkeypatch.setattr(
        runner,
        "run_service_migrations",
        lambda *_args, **_kwargs: SimpleNamespace(
            planned=versions,
            applied=(),
            skipped=versions,
        ),
    )
    monkeypatch.setattr(runner, "_collect_snapshot", lambda _url: _snapshot())
    monkeypatch.setattr(
        runner,
        "_execute_oa_session_postgres_smoke",
        lambda **_kwargs: {
            **_workflow(),
            "tenant_id": "tenant",
            "subject_id": "subject",
            "session_id": "session",
        },
    )
    monkeypatch.setattr(
        runner,
        "_collect_cleanup_residue",
        lambda *_args, **_kwargs: {
            name: 0 for name in EXPECTED_RESIDUE_KEYS
        },
    )

    result = runner.run_oa_trust_postgres_baseline(
        {runner.SMOKE_ENV: "1", runner.DATABASE_ENV: DATABASE_URL}
    )

    assert result["status"] == "PASS"
    assert result["redacted_database_url"].endswith("@127.0.0.1:5432/nex_oa_test")
    assert result["migration"]["skipped_count"] == len(versions)


def test_runner_execution_failure_summary_and_main(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        runner,
        "run_service_migrations",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    failed = runner.run_oa_trust_postgres_baseline(
        {runner.SMOKE_ENV: "1", runner.DATABASE_ENV: DATABASE_URL}
    )
    assert failed["failure_code"] == "execution_failed"
    assert runner.summary_line(failed).startswith("oa_trust_postgres_baseline=fail")
    skipped = runner.run_oa_trust_postgres_baseline({})
    assert "skipped" in runner.summary_line(skipped)

    monkeypatch.setattr(runner, "run_oa_trust_postgres_baseline", lambda: _passing())
    assert runner.main(["--summary"]) == 0
    assert "baseline=pass" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"
    monkeypatch.setattr(
        runner,
        "run_oa_trust_postgres_baseline",
        lambda: {"status": "FAIL"},
    )
    assert runner.main([]) == 1


def _passing() -> dict[str, Any]:
    return {
        "status": "PASS",
        "database": "nex_oa_test",
        "summary": {
            "actual_migration_count": 14,
            "expected_migration_count": 14,
            "cleanup_residue_count": 0,
        },
        "next_slice": "1251",
    }


@pytest.mark.skipif(
    os.getenv(runner.SMOKE_ENV) != "1",
    reason=f"{runner.SMOKE_ENV}=1 is required for protected PostgreSQL smoke",
)
def test_protected_actual_oa_trust_postgres_baseline() -> None:
    result = runner.run_oa_trust_postgres_baseline()

    assert result["status"] == "PASS"
    assert result["database"] == "nex_oa_test"
    assert result["role"] == "nex_oa_user"
    assert result["server_kind"] == "PostgreSQL"
    assert result["summary"]["cleanup_residue_count"] == 0
    assert result["migration"]["planned_count"] == result["summary"][
        "actual_migration_count"
    ]
