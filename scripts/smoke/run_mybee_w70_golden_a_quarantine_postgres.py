#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import psycopg

ROOT = Path(__file__).resolve().parents[2]
for source_root in (ROOT / "services/_shared", ROOT / "scripts/smoke"):
    sys.path.insert(0, str(source_root))

from nex_runtime import psycopg_database_url, redact_database_url
from run_mybee_w70_golden_a_retirement_postgres import (
    DATABASE_ENV,
    EXPECTED_DATABASE,
    EXPECTED_ROLE,
    _collect,
    _target_allowed,
)

SCHEMA_VERSION = "mybee.w70.golden_a_quarantine_postgres.v1"
SMOKE_ENV = "NEX_MYBEE_W70_GA_RET_02_POSTGRES"
REPORT_PATH = ROOT / "reports/smoke/mybee-w70-ga-ret-02-postgres.json"


def run_postgres_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "schema_version": SCHEMA_VERSION,
            "slice": "CP-M1-GA-RET-02",
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
                "slice": "CP-M1-GA-RET-02",
                "actual_postgres": True,
                "database_env": DATABASE_ENV,
                "redacted_database_url": redact_database_url(database_url),
                "mutation_performed": False,
            }
        )
        evidence["status"] = "PASS" if all(evidence["checks"].values()) else "FAIL"
        if evidence["status"] == "FAIL":
            evidence["failure_code"] = "historical_lineage_not_quiescent"
        return evidence
    except (OSError, psycopg.Error, ValueError) as exc:
        return _failure(
            "execution_failed", str(exc).replace(database_url, "<redacted>")
        )


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "slice": "CP-M1-GA-RET-02",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
        "actual_postgres": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify AE PostgreSQL is quiescent before Golden A quarantine."
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
            "w70_golden_a_quarantine_postgres="
            f"{result['status'].lower()} actual_postgres={result['actual_postgres']}"
        )
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
