#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = "database/nex-oa/migrations/1264_oa_signed_token_lifecycle.sql"


def run_oa_signed_token_migration(root: Path = ROOT) -> dict[str, Any]:
    path = root / MIGRATION
    sql = path.read_text(encoding="utf-8") if path.is_file() else ""
    key_sql = _table_body(sql, "oa_signing_keys")
    revocation_sql = _table_body(sql, "oa_token_revocations")
    identifiers = _identifiers(sql)
    lowered = sql.lower()
    checks = {
        "signing_key_table": bool(key_sql),
        "revocation_table": bool(revocation_sql),
        "public_jwk_only": (
            "public_jwk JSONB NOT NULL" in key_sql
            and "public_jwk ?| ARRAY['d', 'p', 'q', 'dp', 'dq', 'qi', 'oth']" in key_sql
        ),
        "external_private_key_reference_only": (
            "private_key_ref TEXT NOT NULL" in key_sql
            and "private_key " not in lowered
            and "private_key_pem" not in lowered
        ),
        "key_windows_constrained": (
            "ck_oa_signing_keys_windows" in key_sql
            and "INTERVAL '330 seconds'" in key_sql
        ),
        "one_active_key_per_issuer": (
            "ux_oa_signing_keys_active" in sql
            and "WHERE state = 'ACTIVE'" in sql
        ),
        "hashed_jti_only": (
            "jti_digest CHAR(64) NOT NULL UNIQUE" in revocation_sql
            and "jti_digest ~ '^[0-9a-f]{64}$'" in revocation_sql
            and re.search(r"\bjti\s+", revocation_sql, re.IGNORECASE) is None
        ),
        "raw_token_columns_absent": all(
            name not in lowered
            for name in ("access_token ", "raw_token ", "client_secret ")
        ),
        "revocation_expiry_constrained": (
            "ck_oa_token_revocations_expiry" in revocation_sql
            and "expires_at > revoked_at" in revocation_sql
        ),
        "operational_indexes": all(
            name in sql
            for name in (
                "ix_oa_signing_keys_state",
                "ix_oa_token_revocations_expiry",
                "ix_oa_token_revocations_subject",
            )
        ),
        "migration_ledger": "'1264_oa_signed_token_lifecycle'" in sql,
        "transaction_wrapped": sql.strip().startswith("BEGIN;") and sql.strip().endswith("COMMIT;"),
        "identifiers_within_postgres_limit": bool(identifiers) and max(map(len, identifiers)) <= 63,
        "table_names_under_30": all(len(name) < 30 for name in ("oa_signing_keys", "oa_token_revocations")),
    }
    passed = all(checks.values())
    return {
        "migration_schema_version": "oa_signed_token_migration.v1",
        "slice": "1264",
        "requirement": "S127",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "oa_signed_token_migration_failed",
        "migration": MIGRATION,
        "checks": checks,
        "summary": {
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "table_count": sum(bool(item) for item in (key_sql, revocation_sql)),
            "identifier_count": len(identifiers),
            "longest_identifier_length": max(map(len, identifiers), default=0),
        },
        "next_slice": "1265",
    }


def _table_body(sql: str, table_name: str) -> str:
    marker = f"CREATE TABLE IF NOT EXISTS {table_name}"
    if marker not in sql:
        return ""
    return sql.split(marker, maxsplit=1)[1].split("\n);", maxsplit=1)[0]


def _identifiers(sql: str) -> set[str]:
    patterns = (
        r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-z][a-z0-9_]*)",
        r"\bCREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-z][a-z0-9_]*)",
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
        "oa_signed_token_migration="
        f"{str(evidence.get('status')).lower()} "
        f"checks={summary.get('passed_check_count', 0)}/{summary.get('check_count', 0)} "
        f"tables={summary.get('table_count', 0)} "
        f"longest={summary.get('longest_identifier_length', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_signed_token_migration()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
