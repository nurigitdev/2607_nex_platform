#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = "database/nex-oa/migrations/1234_oa_group_role_authorization.sql"
EXPECTED_TABLES = {
    "oa_roles",
    "oa_groups",
    "oa_group_members",
    "oa_group_roles",
    "oa_authz_events",
}


def run_oa_authorization_persistence_migration(
    root: Path = ROOT,
) -> dict[str, Any]:
    path = root / MIGRATION_PATH
    sql = path.read_text(encoding="utf-8") if path.is_file() else ""
    identifiers = _identifiers(sql)
    tables = _tables(sql)
    event_sql = (
        sql.split("CREATE TABLE IF NOT EXISTS oa_authz_events", maxsplit=1)[1].split(
            ");", maxsplit=1
        )[0]
        if "CREATE TABLE IF NOT EXISTS oa_authz_events" in sql
        else ""
    )
    checks = {
        "all_tables_declared": EXPECTED_TABLES == tables,
        "tenant_foreign_keys_present": sql.count("REFERENCES oa_tenants(tenant_id)") >= 3,
        "group_member_membership_fk_present": "fk_oa_group_members_membership" in sql,
        "group_role_foreign_keys_present": all(
            token in sql
            for token in ("fk_oa_group_roles_group", "fk_oa_group_roles_role")
        ),
        "revision_guards_present": sql.count("revision BIGINT NOT NULL DEFAULT 1") == 4,
        "status_guards_present": sql.count("status IN ('ACTIVE', 'DISABLED')") == 4,
        "privacy_safe_event_shape": "details JSONB" in event_sql
        and not any(
            forbidden in event_sql
            for forbidden in ("password", "session_id", "service_token", "database_url")
        ),
        "lookup_indexes_present": all(
            token in sql
            for token in (
                "ix_oa_roles_status",
                "ix_oa_groups_status",
                "ix_oa_group_members_subject",
                "ix_oa_group_roles_role",
                "ix_oa_authz_events_tenant_time",
            )
        ),
        "migration_ledger_present": "'1234_oa_group_role_authorization'" in sql,
        "transaction_wrapped": sql.strip().startswith("BEGIN;")
        and sql.strip().endswith("COMMIT;"),
        "identifiers_within_postgres_limit": bool(identifiers)
        and max(map(len, identifiers)) <= 63,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "oa_authorization_persistence_migration.v1",
        "slice": "1234",
        "requirement": "S124",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "oa_authorization_persistence_migration_failed",
        "checks": checks,
        "summary": {
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "table_count": len(tables),
            "identifier_count": len(identifiers),
            "longest_identifier_length": max(map(len, identifiers), default=0),
        },
    }


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


def _tables(sql: str) -> set[str]:
    return {
        match.group(1).lower()
        for match in re.finditer(
            r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-z][a-z0-9_]*)",
            sql,
            flags=re.IGNORECASE,
        )
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "oa_authorization_persistence_migration="
        f"{'pass' if evidence.get('status') == 'PASS' else 'fail'} "
        f"checks={summary.get('passed_check_count', 0)}/{summary.get('check_count', 0)} "
        f"tables={summary.get('table_count', 0)} "
        f"longest={summary.get('longest_identifier_length', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_authorization_persistence_migration()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
