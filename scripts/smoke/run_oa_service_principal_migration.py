#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = "database/nex-oa/migrations/1254_oa_service_principal_lifecycle.sql"


def run_oa_service_principal_migration(root: Path = ROOT) -> dict[str, Any]:
    path = root / MIGRATION
    sql = path.read_text(encoding="utf-8") if path.is_file() else ""
    credential_sql = _table_body(sql, "oa_service_creds")
    principal_sql = _table_body(sql, "oa_service_principals")
    identifiers = _identifiers(sql)
    checks = {
        "principal_table": bool(principal_sql),
        "credential_table": bool(credential_sql),
        "principal_allowlists": (
            "allowed_audiences JSONB NOT NULL" in principal_sql
            and "allowed_scopes JSONB NOT NULL" in principal_sql
        ),
        "optimistic_revisions": sql.count("revision BIGINT NOT NULL") == 2,
        "argon2id_hash_only": (
            "secret_hash TEXT NOT NULL" in credential_sql
            and "secret_hash LIKE '$argon2id$%'" in credential_sql
            and "client_secret" not in credential_sql
        ),
        "credential_lifetime_constraints": (
            "ck_oa_service_creds_expiry" in credential_sql
            and "ck_oa_service_creds_grace" in credential_sql
            and "INTERVAL '24 hours'" in credential_sql
        ),
        "operational_indexes": (
            "ix_oa_service_principals_service" in sql
            and "ix_oa_service_creds_principal" in sql
            and "ix_oa_service_creds_expiry" in sql
        ),
        "migration_ledger": "'1254_oa_service_principal_lifecycle'" in sql,
        "transaction_wrapped": (
            sql.strip().startswith("BEGIN;") and sql.strip().endswith("COMMIT;")
        ),
        "identifiers_within_postgres_limit": bool(identifiers)
        and max(map(len, identifiers)) <= 63,
        "table_names_under_30": all(
            len(name) < 30
            for name in ("oa_service_principals", "oa_service_creds")
        ),
        "signed_runtime_tables_deferred": (
            "oa_signing_keys" not in sql and "oa_token_revocations" not in sql
        ),
    }
    passed = all(checks.values())
    return {
        "migration_schema_version": "oa_service_principal_migration.v1",
        "slice": "1254",
        "requirement": "S126",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "oa_service_principal_migration_failed",
        "migration": MIGRATION,
        "checks": checks,
        "summary": {
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "table_count": sum(
                bool(body) for body in (principal_sql, credential_sql)
            ),
            "identifier_count": len(identifiers),
            "longest_identifier_length": max(map(len, identifiers), default=0),
        },
        "next_slice": "1255",
    }


def _table_body(sql: str, table_name: str) -> str:
    marker = f"CREATE TABLE IF NOT EXISTS {table_name}"
    if marker not in sql:
        return ""
    return sql.split(marker, maxsplit=1)[1].split("\n);", maxsplit=1)[0]


def _identifiers(sql: str) -> set[str]:
    patterns = (
        r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-z][a-z0-9_]*)",
        r"\bCREATE\s+INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-z][a-z0-9_]*)",
        r"\bCONSTRAINT\s+([a-z][a-z0-9_]*)",
    )
    return {
        match.group(1).lower()
        for pattern in patterns
        for match in re.finditer(pattern, sql, flags=re.IGNORECASE)
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "oa_service_principal_migration="
        f"{str(evidence.get('status')).lower()} "
        f"checks={summary.get('passed_check_count', 0)}/{summary.get('check_count', 0)} "
        f"tables={summary.get('table_count', 0)} "
        f"longest={summary.get('longest_identifier_length', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_service_principal_migration()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
