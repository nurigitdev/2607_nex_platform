from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import run_migrations
from run_migrations import (
    MigrationError,
    MigrationRunResult,
    build_alembic_config,
    format_result,
    load_migrations,
    run_service_migrations,
    service_database_env,
    service_database_url,
    service_migration_settings,
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


def test_service_database_env_supports_dev_and_test_profiles() -> None:
    assert service_database_env("nex-cx") == "NEX_CX_DATABASE_URL"
    assert service_database_env("nex-cx", profile="test") == "NEX_CX_TEST_DATABASE_URL"

    with pytest.raises(MigrationError, match="unknown database profile"):
        service_database_env("nex-cx", profile="prod")

    with pytest.raises(MigrationError, match="unknown service id"):
        service_database_env("unknown-service", profile="test")


def test_service_database_url_uses_test_profile_env() -> None:
    assert (
        service_database_url(
            "nex-cx",
            profile="test",
            environ={"NEX_CX_TEST_DATABASE_URL": "postgresql://user:secret@localhost/nex_cx_test"},
        )
        == "postgresql://user:secret@localhost/nex_cx_test"
    )


def test_service_migration_settings_redacts_url_and_sets_paths(tmp_path: Path) -> None:
    settings = service_migration_settings(
        "nex-ae-api",
        profile="test",
        environ={
            "NEX_AE_TEST_DATABASE_URL": "postgresql://nex_ae_user:secret@localhost/nex_ae_test"
        },
        database_root=tmp_path,
    )

    assert settings.database_env == "NEX_AE_TEST_DATABASE_URL"
    assert settings.redacted_database_url == "postgresql://nex_ae_user:***@localhost/nex_ae_test"
    assert settings.migrations_dir == tmp_path / "nex-ae-api" / "migrations"
    assert settings.alembic_script_location == tmp_path / "nex-ae-api" / "alembic"


def test_service_migration_settings_can_skip_database_url_for_dry_run(tmp_path: Path) -> None:
    settings = service_migration_settings(
        "nex-mo",
        profile="test",
        environ={},
        database_root=tmp_path,
        require_database_url=False,
    )

    assert settings.database_env == "NEX_MO_TEST_DATABASE_URL"
    assert settings.database_url == ""
    assert settings.redacted_database_url == ""


def test_build_alembic_config_uses_service_settings(tmp_path: Path) -> None:
    settings = service_migration_settings(
        "nex-oa",
        environ={"NEX_OA_DATABASE_URL": "postgresql://nex_oa_user:secret@localhost/nex_oa_dev"},
        database_root=tmp_path,
    )

    config = build_alembic_config(settings)

    assert config.get_main_option("script_location") == str(tmp_path / "nex-oa" / "alembic")
    assert config.get_main_option("sqlalchemy.url") == settings.database_url
    assert config.get_main_option("nex.service_id") == "nex-oa"
    assert config.get_main_option("nex.database_profile") == "dev"
    assert config.get_main_option("nex.database_env") == "NEX_OA_DATABASE_URL"


def test_build_alembic_config_requires_database_url(tmp_path: Path) -> None:
    settings = service_migration_settings(
        "nex-oa",
        environ={},
        database_root=tmp_path,
        require_database_url=False,
    )

    with pytest.raises(MigrationError, match="requires a database URL"):
        build_alembic_config(settings)


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


def test_main_uses_test_profile_database_url(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[dict[str, object]] = []

    def fake_run_service_migrations(
        service_id: str,
        *,
        database_url: str,
        database_root: Path,
        dry_run: bool,
        profile: str,
    ) -> MigrationRunResult:
        calls.append(
            {
                "service_id": service_id,
                "database_url": database_url,
                "database_root": database_root,
                "dry_run": dry_run,
                "profile": profile,
            }
        )
        return MigrationRunResult(
            service_id=service_id,
            planned=("0023_first",),
            applied=("0023_first",),
            skipped=(),
            dry_run=dry_run,
            profile=profile,
        )

    monkeypatch.setattr(run_migrations, "load_env_file", lambda path: None)
    monkeypatch.setattr(run_migrations, "run_service_migrations", fake_run_service_migrations)
    monkeypatch.setenv(
        "NEX_CX_TEST_DATABASE_URL",
        "postgresql://nex_cx_user:secret@localhost/nex_cx_test",
    )

    assert run_migrations.main(["--service", "nex-cx", "--profile", "test"]) == 0

    assert calls == [
        {
            "service_id": "nex-cx",
            "database_url": "postgresql://nex_cx_user:secret@localhost/nex_cx_test",
            "database_root": run_migrations.DATABASE_ROOT,
            "dry_run": False,
            "profile": "test",
        }
    ]
    assert capsys.readouterr().out.strip() == "nex-cx profile=test: applied=0023_first skipped=none"
