#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit

import psycopg


ROOT = Path(__file__).resolve().parents[2]
OA_PATH = ROOT / "services" / "nex-oa"
SHARED_PATH = ROOT / "services" / "_shared"
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
SMOKE_PATH = ROOT / "scripts" / "smoke"
for path in (OA_PATH, SHARED_PATH, DB_SCRIPT_PATH, SMOKE_PATH):
    sys.path.insert(0, str(path))

from nex_oa.postgres_reaudit import (  # noqa: E402
    EXPECTED_DATABASE,
    EXPECTED_ROLE,
    evaluate_oa_postgres_reaudit,
)
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    load_env_file,
    psycopg_database_url,
    redact_database_url,
)
from run_migrations import run_service_migrations  # noqa: E402
from run_oa_user_login_postgres_smoke import (  # noqa: E402
    _execute_oa_user_login_postgres_smoke,
)


SCHEMA_VERSION = "oa_current_state_postgres_reaudit_smoke.v1"
SMOKE_ENV = "NEX_OA_CURRENT_STATE_POSTGRES_REAUDIT"
DATABASE_ENV = "NEX_OA_TEST_DATABASE_URL"
SERVICE_ID = "nex-oa"
PROFILE = "test"


def run_oa_current_state_postgres_reaudit(
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
        workflow = _execute_oa_user_login_postgres_smoke(
            database_env=DATABASE_ENV,
            database_url=database_url,
            runtime_environ={
                **env,
                SERVICE_SPECS[SERVICE_ID].database_env: database_url,
                "NEX_OA_PERSISTENCE_MODE": "postgres",
            },
        )
        workflow["cleanup_residue"] = _collect_cleanup_residue(
            database_url,
            tenant_id=str(workflow["tenant_id"]),
            subject_id=str(workflow["subject_id"]),
            normalized_employee_id=str(workflow["normalized_employee_id"]),
            session_id=str(workflow["session_id"]),
        )
        evidence = evaluate_oa_postgres_reaudit(
            snapshot,
            {
                "planned": migration.planned,
                "applied": migration.applied,
                "skipped": migration.skipped,
            },
            workflow,
        )
        evidence["smoke_schema_version"] = SCHEMA_VERSION
        evidence["profile"] = PROFILE
        evidence["database_env"] = DATABASE_ENV
        evidence["redacted_database_url"] = redact_database_url(database_url)
        return evidence
    except Exception as exc:
        return _failure("execution_failed", exc.__class__.__name__)


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
        "longest_identifier_length": len(longest_identifier.encode("utf-8")),
    }


def _collect_cleanup_residue(
    database_url: str,
    *,
    tenant_id: str,
    subject_id: str,
    normalized_employee_id: str,
    session_id: str,
    connect: Any = psycopg.connect,
) -> dict[str, int]:
    with connect(psycopg_database_url(database_url)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT "
                "(SELECT count(*) FROM oa_user_sessions WHERE session_id = %s), "
                "(SELECT count(*) FROM oa_local_credentials "
                " WHERE tenant_id = %s AND normalized_employee_id = %s), "
                "(SELECT count(*) FROM oa_tenant_memberships "
                " WHERE tenant_id = %s AND subject_id = %s), "
                "(SELECT count(*) FROM oa_subjects "
                " WHERE tenant_id = %s AND subject_id = %s), "
                "(SELECT count(*) FROM oa_tenants WHERE tenant_id = %s)",
                (
                    session_id,
                    tenant_id,
                    normalized_employee_id,
                    tenant_id,
                    subject_id,
                    tenant_id,
                    subject_id,
                    tenant_id,
                ),
            )
            row = cursor.fetchone()
        connection.rollback()
    return {
        "session_count": int(row[0]),
        "credential_count": int(row[1]),
        "membership_count": int(row[2]),
        "subject_count": int(row[3]),
        "tenant_count": int(row[4]),
    }


def _target_url_allowed(database_url: str) -> bool:
    parsed = urlsplit(database_url)
    return (
        unquote(parsed.username or "") == EXPECTED_ROLE
        and unquote(parsed.path.lstrip("/")) == EXPECTED_DATABASE
    )


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
        "oa_current_state_postgres_reaudit="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"database={evidence.get('database', 'not-run')} "
        f"migrations={summary.get('actual_migration_count', 0)}/"
        f"{summary.get('expected_migration_count', 0)} "
        f"tables={summary.get('core_table_count', 0)} "
        f"workflow_checks={summary.get('workflow_check_count', 0)} "
        f"failed_checks={summary.get('failed_check_count', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_oa_current_state_postgres_reaudit()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
