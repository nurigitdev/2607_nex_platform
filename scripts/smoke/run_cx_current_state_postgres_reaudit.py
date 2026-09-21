#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit
from uuid import uuid4

import psycopg


ROOT = Path(__file__).resolve().parents[2]
CX_PATH = ROOT / "services" / "nex-cx"
SHARED_PATH = ROOT / "services" / "_shared"
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
for path in (CX_PATH, SHARED_PATH, DB_SCRIPT_PATH):
    sys.path.insert(0, str(path))

from nex_cx.postgres_reaudit import (  # noqa: E402
    EXPECTED_DATABASE,
    EXPECTED_ROLE,
    evaluate_cx_postgres_reaudit,
)
from nex_runtime import (  # noqa: E402
    load_env_file,
    psycopg_database_url,
    redact_database_url,
)
from run_migrations import MigrationError, run_service_migrations  # noqa: E402


SCHEMA_VERSION = "cx_current_state_postgres_reaudit_smoke.v1"
SMOKE_ENV = "NEX_CX_CURRENT_STATE_POSTGRES_REAUDIT"
DATABASE_ENV = "NEX_CX_TEST_DATABASE_URL"
SERVICE_ID = "nex-cx"
PROFILE = "test"


def run_cx_current_state_postgres_reaudit(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    database_url = env.get(DATABASE_ENV, "")
    if not database_url:
        return _failure("database_url_missing", f"{DATABASE_ENV} is required.")
    if not _target_url_allowed(database_url):
        return _failure(
            "target_not_allowed",
            f"database target must be {EXPECTED_ROLE}@.../{EXPECTED_DATABASE}",
        )

    try:
        migration = run_service_migrations(
            SERVICE_ID,
            database_url=database_url,
            profile=PROFILE,
        )
        snapshot = _collect_database_snapshot(database_url)
        evidence = evaluate_cx_postgres_reaudit(
            snapshot,
            {
                "planned": migration.planned,
                "applied": migration.applied,
                "skipped": migration.skipped,
            },
        )
        evidence["smoke_schema_version"] = SCHEMA_VERSION
        evidence["profile"] = PROFILE
        evidence["database_env"] = DATABASE_ENV
        evidence["redacted_database_url"] = redact_database_url(database_url)
        return evidence
    except (MigrationError, psycopg.Error, OSError, ValueError) as exc:
        return _failure(
            "execution_failed",
            _redact_detail(str(exc), database_url=database_url),
        )


def _collect_database_snapshot(
    database_url: str,
    *,
    connect: Any = psycopg.connect,
) -> dict[str, Any]:
    with connect(psycopg_database_url(database_url)) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), current_user")
            database, role = cursor.fetchone()
            cursor.execute("SELECT version FROM schema_migrations ORDER BY version")
            versions = [row[0] for row in cursor.fetchall()]
            cursor.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' ORDER BY table_name"
            )
            tables = [row[0] for row in cursor.fetchall()]
            cursor.execute(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname = 'public' ORDER BY indexname"
            )
            indexes = [row[0] for row in cursor.fetchall()]
            cursor.execute(
                "SELECT constraint_name FROM information_schema.table_constraints "
                "WHERE constraint_schema = 'public' ORDER BY constraint_name"
            )
            constraints = [row[0] for row in cursor.fetchall()]
            cursor.execute(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' ORDER BY table_name, ordinal_position"
            )
            columns = [
                {"table": row[0], "column": row[1]} for row in cursor.fetchall()
            ]
        connection.rollback()

        token = f"cx-s91-{uuid4().hex}"
        with connection.cursor() as cursor:
            cursor.execute(
                "CREATE TEMPORARY TABLE cx_s91_reaudit_probe "
                "(probe_token TEXT PRIMARY KEY) ON COMMIT DROP"
            )
            cursor.execute(
                "INSERT INTO cx_s91_reaudit_probe (probe_token) VALUES (%s)",
                (token,),
            )
            write_observed = cursor.rowcount == 1
            cursor.execute(
                "SELECT probe_token FROM cx_s91_reaudit_probe WHERE probe_token = %s",
                (token,),
            )
            read_observed = cursor.fetchone() == (token,)
        connection.rollback()
        with connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass('pg_temp.cx_s91_reaudit_probe')")
            rollback_observed = cursor.fetchone() == (None,)
        connection.rollback()

    identifiers = tables + indexes + constraints
    longest_identifier = max(identifiers, key=len, default="")
    return {
        "database": database,
        "role": role,
        "migration_versions": versions,
        "tables": tables,
        "indexes": indexes,
        "constraints": constraints,
        "columns": columns,
        "longest_identifier": longest_identifier,
        "longest_identifier_length": len(longest_identifier),
        "rollback_probe": {
            "write_observed": write_observed,
            "read_observed": read_observed,
            "rollback_observed": rollback_observed,
        },
    }


def _target_url_allowed(database_url: str) -> bool:
    parsed = urlsplit(database_url)
    return (
        unquote(parsed.username or "") == EXPECTED_ROLE
        and unquote(parsed.path.lstrip("/")) == EXPECTED_DATABASE
    )


def _redact_detail(detail: str, *, database_url: str) -> str:
    redacted = detail.replace(database_url, redact_database_url(database_url))
    password = urlsplit(database_url).password
    return redacted.replace(unquote(password), "***") if password else redacted


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "cx_current_state_postgres_reaudit="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"database={evidence.get('database', 'not-run')} "
        f"migrations={summary.get('actual_migration_count', 0)}/"
        f"{summary.get('expected_migration_count', 0)} "
        f"tables={summary.get('core_table_count', 0)} "
        f"private_columns={summary.get('private_column_violation_count', 0)} "
        f"failed_checks={summary.get('failed_check_count', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_cx_current_state_postgres_reaudit()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
