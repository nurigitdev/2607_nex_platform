from __future__ import annotations

import json
from pathlib import Path

import run_oa_signed_token_migration as migration


def test_signed_token_migration_is_complete_private_and_identifier_safe() -> None:
    result = migration.run_oa_signed_token_migration()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["summary"]["table_count"] == 2
    assert result["summary"]["longest_identifier_length"] <= 63


def test_migration_fails_closed_when_file_is_missing(tmp_path: Path) -> None:
    result = migration.run_oa_signed_token_migration(tmp_path)

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "oa_signed_token_migration_failed"
    assert result["summary"]["identifier_count"] == 0


def test_migration_helpers_parse_tables_and_unique_indexes() -> None:
    sql = (
        "CREATE TABLE IF NOT EXISTS oa_x (\n"
        " id TEXT CONSTRAINT ck_oa_x CHECK (id <> '')\n);\n"
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_oa_x ON oa_x (id);"
    )

    assert "id TEXT" in migration._table_body(sql, "oa_x")
    assert migration._table_body(sql, "missing") == ""
    assert migration._identifiers(sql) == {"oa_x", "ck_oa_x", "ux_oa_x"}


def test_migration_cli_covers_output_modes(monkeypatch, capsys) -> None:
    passing = migration.run_oa_signed_token_migration()
    assert "tables=2" in migration.summary_line(passing)
    assert migration.main(["--summary"]) == 0
    assert "migration=pass" in capsys.readouterr().out
    assert migration.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        migration,
        "run_oa_signed_token_migration",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert migration.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
