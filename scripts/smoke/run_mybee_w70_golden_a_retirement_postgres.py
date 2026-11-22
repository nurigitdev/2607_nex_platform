#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import psycopg

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/_shared"))

from nex_runtime import psycopg_database_url, redact_database_url  # noqa: E402

SCHEMA_VERSION = "mybee.w70.golden_a_retirement_postgres.v1"
SMOKE_ENV = "NEX_MYBEE_W70_GA_RET_01_POSTGRES"
DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
EXPECTED_DATABASE = "nex_ae_test"
EXPECTED_ROLE = "nex_ae_user"
REPORT_PATH = ROOT / "reports/smoke/mybee-w70-ga-ret-01-postgres.json"

_GOLDEN_PREDICATE = "(" + " OR ".join(
    (
        "{column}::text ILIKE '%FINANCE.CREATE_VOUCHER_DRAFT%'",
        "{column}::text ILIKE '%FINANCE.VOUCHER_DRAFT.CREATE%'",
        "{column}::text ILIKE '%FINANCE.VOUCHER_DRAFT_CREATE%'",
        "{column}::text ILIKE '%createEosVoucherDraft%'",
    )
) + ")"


def run_postgres_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "schema_version": SCHEMA_VERSION,
            "slice": "CP-M1-GA-RET-01",
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
            "actual_postgres": False,
        }
    database_url = str(env.get(DATABASE_ENV) or "")
    if not database_url:
        return _failure("database_url_missing", f"{DATABASE_ENV} is required.")
    if not _target_allowed(database_url):
        return _failure(
            "target_not_allowed",
            f"database target must be {EXPECTED_ROLE}@.../{EXPECTED_DATABASE}",
        )
    try:
        with psycopg.connect(psycopg_database_url(database_url)) as connection:
            evidence = _collect(connection)
            connection.rollback()
        evidence.update(
            {
                "schema_version": SCHEMA_VERSION,
                "slice": "CP-M1-GA-RET-01",
                "actual_postgres": True,
                "database_env": DATABASE_ENV,
                "redacted_database_url": redact_database_url(database_url),
            }
        )
        evidence["status"] = (
            "PASS" if all(evidence["checks"].values()) else "FAIL"
        )
        if evidence["status"] == "FAIL":
            evidence["failure_code"] = "golden_a_lineage_not_drained"
        return evidence
    except (OSError, psycopg.Error, ValueError) as exc:
        return _failure("execution_failed", str(exc).replace(database_url, "<redacted>"))


def _collect(connection: Any) -> dict[str, Any]:
    required_tables = {
        "ae_agent_execution",
        "ae_agent_plan",
        "ae_executable_plan",
        "ae_runtime_job",
        "ae_work_intent",
    }
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database(), current_user")
        database, role = cursor.fetchone()
        cursor.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public'"
        )
        tables = {str(row[0]) for row in cursor.fetchall()}
        if not required_tables.issubset(tables):
            missing = sorted(required_tables - tables)
            return {
                "database": database,
                "role": role,
                "checks": {
                    "database_identity": (
                        database == EXPECTED_DATABASE and role == EXPECTED_ROLE
                    ),
                    "runtime_tables_present": False,
                    "no_in_flight_golden_execution": False,
                    "no_runnable_golden_runtime_job": False,
                },
                "missing_tables": missing,
                "golden_lineage": {},
            }
        lineage_query = _lineage_cte()
        cursor.execute(
            lineage_query
            + " SELECT count(*) FROM golden_execution ge "
            "JOIN ae_agent_execution e ON e.tenant_id = ge.tenant_id "
            "AND e.agent_execution_id = ge.agent_execution_id "
            "WHERE e.state NOT IN "
            "('SUCCEEDED','FAILED','BLOCKED','ESCALATED','CANCELLED')"
        )
        active_executions = int(cursor.fetchone()[0])
        cursor.execute(
            lineage_query
            + " SELECT count(*) FROM golden_execution ge "
            "JOIN ae_runtime_job j ON j.tenant_id = ge.tenant_id "
            "AND j.execution_id = ge.agent_execution_id::text "
            "WHERE j.state IN ('QUEUED','RUNNING')"
        )
        runnable_jobs = int(cursor.fetchone()[0])
        cursor.execute(lineage_query + " SELECT count(*) FROM golden_execution")
        total_lineage = int(cursor.fetchone()[0])
    return {
        "database": str(database),
        "role": str(role),
        "checks": {
            "database_identity": (
                database == EXPECTED_DATABASE and role == EXPECTED_ROLE
            ),
            "runtime_tables_present": True,
            "no_in_flight_golden_execution": active_executions == 0,
            "no_runnable_golden_runtime_job": runnable_jobs == 0,
        },
        "missing_tables": [],
        "golden_lineage": {
            "total_execution_count": total_lineage,
            "in_flight_execution_count": active_executions,
            "runnable_runtime_job_count": runnable_jobs,
            "content_included": False,
        },
    }


def _lineage_cte() -> str:
    sources = (
        ("ae_work_intent", "intent_json"),
        ("ae_agent_plan", "plan_json"),
        ("ae_executable_plan", "plan_json"),
    )
    selects = [
        "SELECT tenant_id, agent_execution_id FROM "
        + table
        + " WHERE "
        + _GOLDEN_PREDICATE.format(column=column)
        for table, column in sources
    ]
    return (
        "WITH golden_execution AS ("
        + " UNION ".join(selects)
        + ")"
    )


def _target_allowed(database_url: str) -> bool:
    parsed = urlsplit(database_url.replace("postgresql+psycopg://", "postgresql://", 1))
    return (
        unquote(parsed.username or "") == EXPECTED_ROLE
        and parsed.path.lstrip("/") == EXPECTED_DATABASE
    )


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "slice": "CP-M1-GA-RET-01",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
        "actual_postgres": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check actual AE PostgreSQL for Golden A in-flight lineage."
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output", type=Path, default=REPORT_PATH)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    env = dict(os.environ)
    if args.execute:
        env[SMOKE_ENV] = "1"
    result = run_postgres_smoke(env)
    if result["status"] != "SKIPPED":
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if args.summary:
        print(
            "w70_golden_a_retirement_postgres="
            f"{result['status'].lower()} actual_postgres={result['actual_postgres']}"
        )
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
