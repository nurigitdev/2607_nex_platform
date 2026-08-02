#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import psycopg


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
sys.path.insert(0, str(SHARED_PATH))

from nex_runtime import load_env_file  # noqa: E402


DATABASE_ROOT = ROOT / "database"

SERVICE_DATABASE_ENVS = {
    "nex-oa": "NEX_OA_DATABASE_URL",
    "nex-ag": "NEX_AG_DATABASE_URL",
    "nex-ae-api": "NEX_AE_DATABASE_URL",
    "nex-cx": "NEX_CX_DATABASE_URL",
    "nex-mo": "NEX_MO_DATABASE_URL",
}


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
    connect: Any = psycopg.connect,
) -> MigrationRunResult:
    if service_id not in SERVICE_DATABASE_ENVS:
        raise MigrationError(f"unknown service id: {service_id}")

    migrations = load_migrations(service_id, database_root=database_root)
    planned = tuple(migration.version for migration in migrations)
    if dry_run:
        return MigrationRunResult(
            service_id=service_id,
            planned=planned,
            applied=planned,
            skipped=(),
            dry_run=True,
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
    environ: dict[str, str] | None = None,
) -> str:
    env = environ if environ is not None else os.environ
    env_name = SERVICE_DATABASE_ENVS[service_id]
    database_url = env.get(env_name)
    if not database_url:
        raise MigrationError(f"missing database URL env {env_name} for {service_id}")
    if "<password>" in database_url:
        raise MigrationError(f"database URL env {env_name} still contains placeholder password")
    return database_url


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
    parser.add_argument("--dry-run", action="store_true", help="List pending migration plan only.")
    return parser


def format_result(result: MigrationRunResult) -> str:
    if result.dry_run:
        versions = ", ".join(result.planned) if result.planned else "none"
        return f"{result.service_id}: DRY_RUN planned={versions}"
    applied = ", ".join(result.applied) if result.applied else "none"
    skipped = ", ".join(result.skipped) if result.skipped else "none"
    return f"{result.service_id}: applied={applied} skipped={skipped}"


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    load_env_file(args.env_file)

    try:
        for service_id in selected_services(args):
            result = run_service_migrations(
                service_id,
                database_url="" if args.dry_run else service_database_url(service_id),
                database_root=DATABASE_ROOT,
                dry_run=args.dry_run,
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
