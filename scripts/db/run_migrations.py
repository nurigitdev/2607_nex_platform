#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import psycopg
from alembic.config import Config


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
sys.path.insert(0, str(SHARED_PATH))

from nex_runtime import (  # noqa: E402
    DatabaseConfigError,
    load_env_file,
    redact_database_url,
    required_database_url,
)


DATABASE_ROOT = ROOT / "database"

DEV_DATABASE_ENVS = {
    "nex-oa": "NEX_OA_DATABASE_URL",
    "nex-ag": "NEX_AG_DATABASE_URL",
    "nex-ae-api": "NEX_AE_DATABASE_URL",
    "nex-cx": "NEX_CX_DATABASE_URL",
    "nex-mo": "NEX_MO_DATABASE_URL",
}

TEST_DATABASE_ENVS = {
    "nex-oa": "NEX_OA_TEST_DATABASE_URL",
    "nex-ag": "NEX_AG_TEST_DATABASE_URL",
    "nex-ae-api": "NEX_AE_TEST_DATABASE_URL",
    "nex-cx": "NEX_CX_TEST_DATABASE_URL",
    "nex-mo": "NEX_MO_TEST_DATABASE_URL",
}

PROFILE_DATABASE_ENVS = {
    "dev": DEV_DATABASE_ENVS,
    "test": TEST_DATABASE_ENVS,
}

SERVICE_DATABASE_ENVS = DEV_DATABASE_ENVS


@dataclass(frozen=True)
class Migration:
    service_id: str
    version: str
    path: Path
    sql: str


@dataclass(frozen=True)
class MigrationRunResult:
    service_id: str
    planned: tuple[str, ...]
    applied: tuple[str, ...]
    skipped: tuple[str, ...]
    dry_run: bool
    profile: str = "dev"


@dataclass(frozen=True)
class ServiceMigrationSettings:
    service_id: str
    profile: str
    database_env: str
    database_url: str
    redacted_database_url: str
    migrations_dir: Path
    alembic_script_location: Path


class MigrationError(Exception):
    pass


def load_migrations(
    service_id: str,
    *,
    database_root: Path = DATABASE_ROOT,
) -> list[Migration]:
    migrations_dir = database_root / service_id / "migrations"
    if not migrations_dir.exists():
        raise MigrationError(f"migration directory not found for {service_id}: {migrations_dir}")

    migrations: list[Migration] = []
    for path in sorted(migrations_dir.glob("*.sql")):
        sql = path.read_text(encoding="utf-8")
        validate_migration_sql(path, sql)
        migrations.append(
            Migration(
                service_id=service_id,
                version=path.stem,
                path=path,
                sql=sql,
            )
        )
    return migrations


def validate_migration_sql(path: Path, sql: str) -> None:
    compact = " ".join(sql.lower().split())
    if not compact.startswith("begin;"):
        raise MigrationError(f"migration must start with BEGIN: {path}")
    if not compact.endswith("commit;"):
        raise MigrationError(f"migration must end with COMMIT: {path}")
    if "schema_migrations" not in compact:
        raise MigrationError(f"migration must record schema_migrations: {path}")


def run_service_migrations(
    service_id: str,
    *,
    database_url: str,
    database_root: Path = DATABASE_ROOT,
    dry_run: bool = False,
    profile: str = "dev",
    connect: Any = psycopg.connect,
) -> MigrationRunResult:
    validate_service_id(service_id)

    migrations = load_migrations(service_id, database_root=database_root)
    planned = tuple(migration.version for migration in migrations)
    if dry_run:
        return MigrationRunResult(
            service_id=service_id,
            planned=planned,
            applied=planned,
            skipped=(),
            dry_run=True,
            profile=profile,
        )

    applied_versions: set[str]
    applied: list[str] = []
    skipped: list[str] = []
    with connect(database_url, autocommit=True) as connection:
        ensure_schema_migrations_table(connection)
        applied_versions = read_applied_versions(connection)
        for migration in migrations:
            if migration.version in applied_versions:
                skipped.append(migration.version)
                continue
            with connection.cursor() as cursor:
                cursor.execute(migration.sql)
            applied.append(migration.version)

    return MigrationRunResult(
        service_id=service_id,
        planned=planned,
        applied=tuple(applied),
        skipped=tuple(skipped),
        dry_run=False,
        profile=profile,
    )


def ensure_schema_migrations_table(connection: Any) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                description TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )


def read_applied_versions(connection: Any) -> set[str]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT version FROM schema_migrations")
        return {row[0] for row in cursor.fetchall()}


def service_database_url(
    service_id: str,
    *,
    profile: str = "dev",
    environ: dict[str, str] | None = None,
) -> str:
    env = environ if environ is not None else os.environ
    env_name = service_database_env(service_id, profile=profile)
    try:
        return required_database_url(env_name, env)
    except DatabaseConfigError as exc:
        raise MigrationError(f"{exc} for {service_id}") from exc


def service_database_env(service_id: str, *, profile: str = "dev") -> str:
    try:
        envs = PROFILE_DATABASE_ENVS[profile]
    except KeyError as exc:
        raise MigrationError(f"unknown database profile: {profile}") from exc
    try:
        return envs[service_id]
    except KeyError as exc:
        raise MigrationError(f"unknown service id: {service_id}") from exc


def validate_service_id(service_id: str) -> None:
    if service_id not in SERVICE_DATABASE_ENVS:
        raise MigrationError(f"unknown service id: {service_id}")


def service_migration_settings(
    service_id: str,
    *,
    profile: str = "dev",
    environ: dict[str, str] | None = None,
    database_root: Path = DATABASE_ROOT,
    require_database_url: bool = True,
) -> ServiceMigrationSettings:
    env = environ if environ is not None else os.environ
    database_env = service_database_env(service_id, profile=profile)
    database_url = (
        service_database_url(service_id, profile=profile, environ=env)
        if require_database_url
        else env.get(database_env, "")
    )
    return ServiceMigrationSettings(
        service_id=service_id,
        profile=profile,
        database_env=database_env,
        database_url=database_url,
        redacted_database_url=redact_database_url(database_url) if database_url else "",
        migrations_dir=database_root / service_id / "migrations",
        alembic_script_location=database_root / service_id / "alembic",
    )


def build_alembic_config(settings: ServiceMigrationSettings) -> Config:
    if not settings.database_url:
        raise MigrationError("alembic config requires a database URL")
    config = Config()
    config.set_main_option("script_location", str(settings.alembic_script_location))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    config.set_main_option("nex.service_id", settings.service_id)
    config.set_main_option("nex.database_profile", settings.profile)
    config.set_main_option("nex.database_env", settings.database_env)
    return config


def selected_services(args: argparse.Namespace) -> tuple[str, ...]:
    if args.all:
        return tuple(SERVICE_DATABASE_ENVS)
    return tuple(args.service or ())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run service-owned PostgreSQL migrations.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="Run migrations for every service.")
    group.add_argument(
        "--service",
        action="append",
        choices=tuple(SERVICE_DATABASE_ENVS),
        help="Service id to migrate. May be supplied multiple times.",
    )
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env.local")
    parser.add_argument(
        "--profile",
        choices=tuple(PROFILE_DATABASE_ENVS),
        default="dev",
        help="Database env profile to use for execution.",
    )
    parser.add_argument("--dry-run", action="store_true", help="List pending migration plan only.")
    return parser


def format_result(result: MigrationRunResult) -> str:
    service_label = (
        result.service_id
        if result.profile == "dev"
        else f"{result.service_id} profile={result.profile}"
    )
    if result.dry_run:
        versions = ", ".join(result.planned) if result.planned else "none"
        return f"{service_label}: DRY_RUN planned={versions}"
    applied = ", ".join(result.applied) if result.applied else "none"
    skipped = ", ".join(result.skipped) if result.skipped else "none"
    return f"{service_label}: applied={applied} skipped={skipped}"


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    load_env_file(args.env_file)

    try:
        for service_id in selected_services(args):
            result = run_service_migrations(
                service_id,
                database_url=(
                    "" if args.dry_run else service_database_url(service_id, profile=args.profile)
                ),
                database_root=DATABASE_ROOT,
                dry_run=args.dry_run,
                profile=args.profile,
            )
            print(format_result(result))
    except MigrationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"ERROR: migration execution failed: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
