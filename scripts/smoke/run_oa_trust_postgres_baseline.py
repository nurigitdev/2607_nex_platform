#!/usr/bin/env python3
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit

import psycopg


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services/_shared",
    ROOT / "services/nex-oa",
    ROOT / "scripts/db",
    ROOT / "scripts/smoke",
):
    sys.path.insert(0, str(path))

from nex_oa.trust_postgres_baseline import (  # noqa: E402
    EXPECTED_DATABASE,
    EXPECTED_ROLE,
    evaluate_trust_postgres_baseline,
)
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    issue_mock_service_token,
    load_env_file,
    psycopg_database_url,
    redact_database_url,
    validate_mock_service_token,
)
from run_migrations import run_service_migrations  # noqa: E402
from run_oa_session_postgres_smoke import (  # noqa: E402
    _execute_oa_session_postgres_smoke,
)


SMOKE_ENV = "NEX_OA_TRUST_BASELINE_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_OA_TEST_DATABASE_URL"
SCHEMA_VERSION = "oa_trust_postgres_baseline_smoke.v1"
SERVICE_ID = "nex-oa"


def run_oa_trust_postgres_baseline(
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
        migration_result = run_service_migrations(
            SERVICE_ID,
            database_url=database_url,
            profile="test",
        )
        snapshot = _collect_snapshot(database_url)
        workflow = _execute_oa_session_postgres_smoke(
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
            session_id=str(workflow["session_id"]),
        )
        mock_compatibility = _mock_compatibility_evidence()
        evidence = evaluate_trust_postgres_baseline(
            snapshot=snapshot,
            migration={
                "planned": migration_result.planned,
                "applied": migration_result.applied,
                "skipped": migration_result.skipped,
            },
            workflow=workflow,
            mock_compatibility=mock_compatibility,
        )
        evidence.update(
            smoke_schema_version=SCHEMA_VERSION,
            profile="test",
            database_env=DATABASE_ENV,
            redacted_database_url=redact_database_url(database_url),
            migration={
                "planned_count": len(migration_result.planned),
                "applied": list(migration_result.applied),
                "skipped_count": len(migration_result.skipped),
            },
        )
        return evidence
    except Exception as exc:
        return _failure("execution_failed", exc.__class__.__name__)


def _collect_snapshot(
    database_url: str,
    *,
    connect: Any = psycopg.connect,
) -> dict[str, Any]:
    with connect(psycopg_database_url(database_url)) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), current_user, version()")
            database, role, server_version = cursor.fetchone()
            cursor.execute("SELECT version FROM schema_migrations ORDER BY version")
            migration_versions = [row[0] for row in cursor.fetchall()]
            cursor.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' ORDER BY table_name"
            )
            tables = [row[0] for row in cursor.fetchall()]
            cursor.execute(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' ORDER BY table_name, ordinal_position"
            )
            columns = [
                {"table": row[0], "column": row[1]} for row in cursor.fetchall()
            ]
        connection.rollback()
    return {
        "database": database,
        "role": role,
        "server_kind": (
            "PostgreSQL" if str(server_version).startswith("PostgreSQL") else "UNKNOWN"
        ),
        "migration_versions": migration_versions,
        "tables": tables,
        "columns": columns,
    }


def _collect_cleanup_residue(
    database_url: str,
    *,
    tenant_id: str,
    subject_id: str,
    session_id: str,
    connect: Any = psycopg.connect,
) -> dict[str, int]:
    with connect(psycopg_database_url(database_url)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT "
                "(SELECT count(*) FROM oa_user_sessions WHERE session_id = %s), "
                "(SELECT count(*) FROM oa_tenant_memberships "
                " WHERE tenant_id = %s AND subject_id = %s), "
                "(SELECT count(*) FROM oa_subjects "
                " WHERE tenant_id = %s AND subject_id = %s), "
                "(SELECT count(*) FROM oa_tenants WHERE tenant_id = %s)",
                (
                    session_id,
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
        "membership_count": int(row[1]),
        "subject_count": int(row[2]),
        "tenant_count": int(row[3]),
    }


def _mock_compatibility_evidence() -> dict[str, Any]:
    issued = issue_mock_service_token(
        service_id="nex-ae-api",
        audience="nex-oa",
    )
    validation = validate_mock_service_token(
        issued.access_token,
        expected_audience="nex-oa",
    )
    return {
        "issued": True,
        "validated": validation.ok,
        "storage_mode": "memory_only",
        "database_mutation": False,
        "token_fingerprint": sha256(issued.access_token.encode()).hexdigest()[:16],
        "production_status": "transitional_test_compatibility_only",
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
    if evidence.get("status") == "SKIPPED":
        return f"oa_trust_postgres_baseline=skipped reason={SMOKE_ENV}"
    summary = evidence.get("summary") or {}
    return (
        "oa_trust_postgres_baseline="
        f"{'pass' if evidence.get('status') == 'PASS' else 'fail'} "
        f"database={evidence.get('database', 'not-run')} "
        f"migrations={summary.get('actual_migration_count', 0)}/"
        f"{summary.get('expected_migration_count', 0)} "
        f"residue={summary.get('cleanup_residue_count', 0)} "
        f"next={evidence.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_oa_trust_postgres_baseline()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
