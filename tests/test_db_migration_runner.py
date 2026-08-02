from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import run_migrations
from run_migrations import (
    MigrationError,
    format_result,
    load_migrations,
    run_service_migrations,
    service_database_url,
    validate_migration_sql,
)


class FakeCursor:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def execute(self, sql: str) -> None:
        self.connection.executed.append(sql)

    def fetchall(self) -> list[tuple[str]]:
        return [(version,) for version in self.connection.applied_versions]


class FakeConnection:
    def __init__(self, applied_versions: set[str] | None = None) -> None:
        self.applied_versions = applied_versions or set()
        self.executed: list[str] = []

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)


def migration_text(version: str) -> str:
    return f"""
BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO schema_migrations (version, description)
VALUES ('{version}', 'test migration')
ON CONFLICT (version) DO NOTHING;

COMMIT;
"""


def write_migration(root: Path, service_id: str, filename: str, sql: str) -> Path:
    path = root / service_id / "migrations" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sql, encoding="utf-8")
    return path


def test_load_migrations_returns_sorted_valid_migrations(tmp_path: Path) -> None:
    write_migration(tmp_path, "nex-cx", "0024_second.sql", migration_text("0024_second"))
    write_migration(tmp_path, "nex-cx", "0023_first.sql", migration_text("0023_first"))

    migrations = load_migrations("nex-cx", database_root=tmp_path)

    assert [migration.version for migration in migrations] == ["0023_first", "0024_second"]


@pytest.mark.parametrize(
    ("sql", "message"),
    [
        ("COMMIT;", "BEGIN"),
        ("BEGIN;", "COMMIT"),
        ("BEGIN;\nCOMMIT;", "schema_migrations"),
    ],
)
def test_validate_migration_sql_rejects_invalid_shape(sql: str, message: str) -> None:
    with pytest.raises(MigrationError) as exc:
        validate_migration_sql(Path("bad.sql"), sql)

    assert message in str(exc.value)


def test_run_service_migrations_applies_only_pending_migrations(tmp_path: Path) -> None:
    write_migration(tmp_path, "nex-cx", "0023_first.sql", migration_text("0023_first"))
    write_migration(tmp_path, "nex-cx", "0024_second.sql", migration_text("0024_second"))
    connection = FakeConnection(applied_versions={"0023_first"})
    connect_calls: list[dict[str, Any]] = []

    def connect(database_url: str, autocommit: bool) -> FakeConnection:
        connect_calls.append({"database_url": database_url, "autocommit": autocommit})
        return connection

    result = run_service_migrations(
        "nex-cx",
        database_url="postgresql://example",
        database_root=tmp_path,
        connect=connect,
    )

    assert connect_calls == [{"database_url": "postgresql://example", "autocommit": True}]
    assert result.skipped == ("0023_first",)
    assert result.applied == ("0024_second",)
    assert any("CREATE TABLE IF NOT EXISTS schema_migrations" in sql for sql in connection.executed)
    assert migration_text("0024_second").strip() in connection.executed[-1]


def test_run_service_migrations_dry_run_does_not_connect(tmp_path: Path) -> None:
    write_migration(tmp_path, "nex-oa", "0023_first.sql", migration_text("0023_first"))

    def connect(database_url: str, autocommit: bool) -> FakeConnection:
        raise AssertionError("dry-run should not connect")

    result = run_service_migrations(
        "nex-oa",
        database_url="postgresql://example",
        database_root=tmp_path,
        dry_run=True,
        connect=connect,
    )

    assert result.dry_run is True
    assert result.applied == ("0023_first",)
    assert format_result(result) == "nex-oa: DRY_RUN planned=0023_first"


def test_service_database_url_rejects_missing_and_placeholder_values() -> None:
    with pytest.raises(MigrationError):
        service_database_url("nex-cx", environ={})

    with pytest.raises(MigrationError):
        service_database_url(
            "nex-cx",
            environ={"NEX_CX_DATABASE_URL": "postgresql://user:<password>@localhost/db"},
        )


def test_main_reports_missing_env_without_leaking_password(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(run_migrations, "load_env_file", lambda path: None)
    monkeypatch.delenv("NEX_CX_DATABASE_URL", raising=False)

    assert run_migrations.main(["--service", "nex-cx"]) == 2

    captured = capsys.readouterr()
    assert "missing database URL env NEX_CX_DATABASE_URL" in captured.err
    assert "password" not in captured.err


def test_main_dry_run_lists_plan_without_database_env(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    write_migration(tmp_path, "nex-cx", "0023_first.sql", migration_text("0023_first"))
    monkeypatch.setattr(run_migrations, "DATABASE_ROOT", tmp_path)
    monkeypatch.setattr(run_migrations, "load_env_file", lambda path: None)
    monkeypatch.delenv("NEX_CX_DATABASE_URL", raising=False)

    assert run_migrations.main(["--service", "nex-cx", "--dry-run"]) == 0

    captured = capsys.readouterr()
    assert captured.out.strip() == "nex-cx: DRY_RUN planned=0023_first"
