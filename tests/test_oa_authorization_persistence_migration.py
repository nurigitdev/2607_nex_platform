from pathlib import Path

import run_oa_authorization_persistence_migration as migration


def test_repository_migration_is_complete_and_identifier_safe() -> None:
    result = migration.run_oa_authorization_persistence_migration()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["summary"]["table_count"] == 5
    assert result["summary"]["longest_identifier_length"] <= 63


def test_migration_fails_closed_when_missing(tmp_path: Path) -> None:
    result = migration.run_oa_authorization_persistence_migration(tmp_path)

    assert result["status"] == "FAIL"
    assert result["summary"]["table_count"] == 0
    assert result["summary"]["identifier_count"] == 0


def test_identifier_parsers_and_cli(monkeypatch, capsys) -> None:
    sql = (
        "CREATE TABLE IF NOT EXISTS oa_x (id TEXT CONSTRAINT ck_oa_x CHECK (id <> ''));"
        "CREATE INDEX IF NOT EXISTS ix_oa_x ON oa_x (id);"
    )
    assert migration._identifiers(sql) == {"oa_x", "ck_oa_x", "ix_oa_x"}
    assert migration._tables(sql) == {"oa_x"}

    assert migration.main(["--summary"]) == 0
    assert "migration=pass" in capsys.readouterr().out
    monkeypatch.setattr(
        migration,
        "run_oa_authorization_persistence_migration",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert migration.main([]) == 1
