from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from nex_cx.database_drift_audit import CORE_CX_TABLES
from nex_cx.postgres_reaudit import (
    PRIVATE_PAYLOAD_COLUMNS,
    _named_identifiers,
    evaluate_cx_postgres_reaudit,
    expected_cx_postgres_state,
)
import run_cx_current_state_postgres_reaudit as runner
from run_migrations import MigrationError


DATABASE_URL = (
    "postgresql+psycopg://nex_cx_user:private@127.0.0.1:5432/nex_cx_test"
)


def _migration(root: Path | None = None) -> dict[str, tuple[str, ...]]:
    versions = expected_cx_postgres_state(root or runner.ROOT)["migration_versions"]
    return {"planned": versions, "applied": (), "skipped": versions}


def _snapshot(root: Path | None = None) -> dict[str, Any]:
    expected = expected_cx_postgres_state(root or runner.ROOT)
    return {
        "database": "nex_cx_test",
        "role": "nex_cx_user",
        "migration_versions": expected["migration_versions"],
        "tables": sorted(CORE_CX_TABLES | {"schema_migrations"}),
        "indexes": expected["indexes"],
        "constraints": expected["constraints"],
        "columns": [{"table": "cx_source_files", "column": "content_sha256"}],
        "longest_identifier": "cx_document_summary_embeddings_document_summary_id_key",
        "longest_identifier_length": 56,
        "rollback_probe": {
            "write_observed": True,
            "read_observed": True,
            "rollback_observed": True,
        },
    }


def test_repository_postgres_reaudit_evaluation_passes() -> None:
    result = evaluate_cx_postgres_reaudit(_snapshot(), _migration())

    assert result["status"] == "PASS"
    assert result["database_readiness"] == "ACTUAL_TEST_DATABASE_CLEAN"
    assert all(result["checks"].values())
    assert result["summary"]["expected_migration_count"] == 18
    assert result["summary"]["core_table_count"] == 18
    assert result["private_column_violations"] == []
    assert result["privacy_policy"]["scope"] == "public_schema"


@pytest.mark.parametrize(
    "mutation",
    [
        "database",
        "role",
        "migration_plan",
        "migration_execution",
        "ledger",
        "table",
        "legacy_table",
        "index",
        "constraint",
        "identifier",
        "private_column",
        "probe",
    ],
)
def test_postgres_reaudit_fails_closed_for_each_drift(mutation: str) -> None:
    snapshot = _snapshot()
    migration = _migration()
    if mutation == "database":
        snapshot["database"] = "nex_cx_dev"
    elif mutation == "role":
        snapshot["role"] = "postgres"
    elif mutation == "migration_plan":
        migration["planned"] = migration["planned"][:-1]
    elif mutation == "migration_execution":
        migration["applied"] = migration["skipped"][:1]
    elif mutation == "ledger":
        snapshot["migration_versions"] = (*snapshot["migration_versions"][:-1], "9999_extra")
    elif mutation == "table":
        snapshot["tables"].remove("cx_source_files")
    elif mutation == "legacy_table":
        snapshot["tables"].append("cx_source_blobs")
    elif mutation == "index":
        snapshot["indexes"] = snapshot["indexes"][:-1]
    elif mutation == "constraint":
        snapshot["constraints"] = snapshot["constraints"][:-1]
    elif mutation == "identifier":
        snapshot["longest_identifier_length"] = 64
    elif mutation == "private_column":
        snapshot["columns"].append(
            {"table": "cx_chunks", "column": next(iter(PRIVATE_PAYLOAD_COLUMNS))}
        )
    else:
        snapshot["rollback_probe"]["rollback_observed"] = False

    result = evaluate_cx_postgres_reaudit(snapshot, migration)

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "cx_postgres_reaudit_failed"
    assert result["failed_checks"]


def test_expected_state_and_identifier_parser_fail_closed_without_inputs(
    tmp_path: Path,
) -> None:
    expected = expected_cx_postgres_state()
    assert len(expected["migration_versions"]) == 18
    assert expected["indexes"]
    assert expected["constraints"]
    assert _named_identifiers("CREATE INDEX idx_x ON x (id)", r"INDEX\s+([a-z_]+)") == {
        "idx_x"
    }

    result = evaluate_cx_postgres_reaudit({}, {}, root=tmp_path)
    assert result["status"] == "FAIL"
    assert result["summary"]["expected_migration_count"] == 0


class _Cursor:
    def __init__(self, expected: dict[str, tuple[str, ...]]) -> None:
        self.expected = expected
        self.query = ""
        self.parameters: tuple[str, ...] = ()
        self.rowcount = -1

    def __enter__(self):
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def execute(self, query: str, parameters: tuple[str, ...] = ()) -> None:
        self.query = query
        self.parameters = parameters
        self.rowcount = 1 if query.startswith("INSERT") else -1

    def fetchall(self) -> list[tuple[str, ...]]:
        if "schema_migrations" in self.query:
            return [(item,) for item in self.expected["migration_versions"]]
        if "information_schema.tables" in self.query:
            return [(item,) for item in sorted(CORE_CX_TABLES | {"schema_migrations"})]
        if "pg_indexes" in self.query:
            return [(item,) for item in self.expected["indexes"]]
        if "table_constraints" in self.query:
            return [(item,) for item in self.expected["constraints"]]
        if "information_schema.columns" in self.query:
            return [("cx_source_files", "content_sha256")]
        raise AssertionError(self.query)

    def fetchone(self) -> tuple[Any, ...]:
        if "current_database" in self.query:
            return ("nex_cx_test", "nex_cx_user")
        if "probe_token FROM" in self.query:
            return (self.parameters[0],)
        if "to_regclass" in self.query:
            return (None,)
        raise AssertionError(self.query)


class _Connection:
    def __init__(self) -> None:
        self.expected = expected_cx_postgres_state()
        self.rollbacks = 0

    def cursor(self) -> _Cursor:
        return _Cursor(self.expected)

    def rollback(self) -> None:
        self.rollbacks += 1


def test_database_snapshot_reads_catalog_and_rolls_back_probe() -> None:
    connection = _Connection()
    snapshot = runner._collect_database_snapshot(
        DATABASE_URL,
        connect=lambda _url: nullcontext(connection),
    )

    assert snapshot["database"] == "nex_cx_test"
    assert len(snapshot["migration_versions"]) == 18
    assert snapshot["rollback_probe"] == {
        "write_observed": True,
        "read_observed": True,
        "rollback_observed": True,
    }
    assert connection.rollbacks == 3


def test_runner_requires_opt_in_url_and_exact_test_target() -> None:
    skipped = runner.run_cx_current_state_postgres_reaudit({})
    missing = runner.run_cx_current_state_postgres_reaudit({runner.SMOKE_ENV: "1"})
    wrong = runner.run_cx_current_state_postgres_reaudit(
        {
            runner.SMOKE_ENV: "1",
            runner.DATABASE_ENV: DATABASE_URL.replace("nex_cx_test", "nex_cx_dev"),
        }
    )

    assert skipped["status"] == "SKIPPED"
    assert missing["failure_code"] == "database_url_missing"
    assert wrong["failure_code"] == "target_not_allowed"
    assert runner._target_url_allowed(DATABASE_URL) is True
    assert runner._target_url_allowed("not-a-url") is False


def test_runner_executes_migration_snapshot_and_redacts_failures(monkeypatch) -> None:
    migration = _migration()
    migration_result = SimpleNamespace(**migration)
    monkeypatch.setattr(runner, "run_service_migrations", lambda *_args, **_kwargs: migration_result)
    monkeypatch.setattr(runner, "_collect_database_snapshot", lambda _url: _snapshot())
    env = {runner.SMOKE_ENV: "1", runner.DATABASE_ENV: DATABASE_URL}

    passing = runner.run_cx_current_state_postgres_reaudit(env)
    assert passing["status"] == "PASS"
    assert passing["redacted_database_url"].endswith("@127.0.0.1:5432/nex_cx_test")
    assert "private" not in passing["redacted_database_url"]

    monkeypatch.setattr(
        runner,
        "run_service_migrations",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            MigrationError(f"failed {DATABASE_URL}")
        ),
    )
    failed = runner.run_cx_current_state_postgres_reaudit(env)
    assert failed["failure_code"] == "execution_failed"
    assert "private" not in failed["detail"]
    assert "***" in failed["detail"]


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = evaluate_cx_postgres_reaudit(_snapshot(), _migration())
    assert "postgres_reaudit=pass" in runner.summary_line(passing)
    assert "migrations=18/18" in runner.summary_line(passing)
    assert "database=not-run" in runner.summary_line({"status": "SKIPPED"})

    monkeypatch.setattr(runner, "run_cx_current_state_postgres_reaudit", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "failed_checks=0" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_cx_current_state_postgres_reaudit",
        lambda: {"status": "FAIL"},
    )
    assert runner.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
