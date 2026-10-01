#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "database/nex-oa/migrations/1225_oa_credential_session_security.sql"


def run_oa_security_persistence_migration(root: Path = ROOT) -> dict[str, Any]:
    path = root / "database/nex-oa/migrations/1225_oa_credential_session_security.sql"
    sql = path.read_text(encoding="utf-8") if path.is_file() else ""
    auth_event_sql = (
        sql.split("CREATE TABLE IF NOT EXISTS oa_auth_events", maxsplit=1)[1].split(
            ");", maxsplit=1
        )[0]
        if "CREATE TABLE IF NOT EXISTS oa_auth_events" in sql
        else ""
    )
    required = {
        "argon2id_constraint": "'argon2id.v1'" in sql and "'pbkdf2_sha256.v1'" in sql,
        "last_seen_column": "last_seen_at TIMESTAMPTZ" in sql,
        "idle_expiry_column": "idle_expires_at TIMESTAMPTZ" in sql,
        "idle_time_constraint": "ck_oa_user_sessions_idle_time" in sql,
        "auth_event_table": "CREATE TABLE IF NOT EXISTS oa_auth_events" in sql,
        "auth_event_privacy_shape": "details JSONB" in auth_event_sql
        and not any(
            forbidden in auth_event_sql
            for forbidden in ("password_hash", "session_id", "service_token", "database_url")
        ),
        "migration_ledger": "'1225_oa_credential_session_security'" in sql,
        "transaction_wrapped": sql.strip().startswith("BEGIN;")
        and sql.strip().endswith("COMMIT;"),
    }
    identifiers = _identifiers(sql)
    checks = {
        **required,
        "identifiers_within_postgres_limit": bool(identifiers)
        and max(map(len, identifiers)) <= 63,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "oa_security_persistence_migration.v1",
        "slice": "1225",
        "requirement": "S123",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "oa_security_persistence_migration_failed",
        "checks": checks,
        "summary": {
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "table": "oa_auth_events",
            "identifier_count": len(identifiers),
            "longest_identifier_length": max(map(len, identifiers), default=0),
        },
    }


def _identifiers(sql: str) -> set[str]:
    import re

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
        f"oa_security_persistence_migration={str(evidence.get('status')).lower()} "
        f"checks={summary.get('passed_check_count', 0)}/{summary.get('check_count', 0)} "
        f"table={summary.get('table')} longest={summary.get('longest_identifier_length')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_security_persistence_migration()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
