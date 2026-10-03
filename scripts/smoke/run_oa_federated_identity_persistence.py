#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/_shared"))
sys.path.insert(0, str(ROOT / "services/nex-oa"))

from nex_oa.federated_identities import (  # noqa: E402
    build_external_identity_link,
    build_federation_provider,
)
from nex_oa.federated_identity_repository import (  # noqa: E402
    InMemoryOaFederatedIdentityRepository,
)


MIGRATION = "database/nex-oa/migrations/1284_oa_federated_identity.sql"


def run_oa_federated_identity_persistence(root: Path = ROOT) -> dict[str, Any]:
    sql = _read_text(root / MIGRATION)
    identifiers = _identifiers(sql)
    provider_sql = _table_body(sql, "oa_fed_providers")
    identity_sql = _table_body(sql, "oa_fed_identities")
    repository = InMemoryOaFederatedIdentityRepository()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    provider = build_federation_provider(
        {
            "provider_id": "company-oidc",
            "issuer": "https://id.example.test",
            "client_id": "nex-platform",
            "discovery_url": "https://id.example.test/.well-known/openid-configuration",
            "display_name": "Company OIDC",
        },
        now=now,
    )
    identity = build_external_identity_link(
        {
            "provider_id": "company-oidc",
            "external_subject": "opaque-subject",
            "tenant_id": "company",
            "subject_id": "employee-1001",
        },
        provider=provider,
        now=now,
    )
    repository.save_provider(provider)
    repository.save_identity(identity)
    checks = {
        "provider_table": bool(provider_sql),
        "identity_table": bool(identity_sql),
        "digest_only_external_subject": (
            "external_subject_digest CHAR(64)" in identity_sql
            and "external_subject TEXT" not in identity_sql
        ),
        "provider_secret_absent": (
            "client_secret" not in provider_sql and "provider_secret" not in provider_sql
        ),
        "subject_foreign_key": "fk_oa_fed_identity_subject" in identity_sql,
        "one_identity_per_provider_subject": "uq_oa_fed_identity_subject" in identity_sql,
        "revision_guards": sql.count("revision BIGINT NOT NULL") == 2,
        "operational_indexes": (
            "ix_oa_fed_providers_status" in sql
            and "ix_oa_fed_identities_subject" in sql
        ),
        "migration_ledger": "'1284_oa_federated_identity'" in sql,
        "transaction_wrapped": sql.strip().startswith("BEGIN;") and sql.strip().endswith("COMMIT;"),
        "identifier_lengths_safe": bool(identifiers) and max(map(len, identifiers)) <= 63,
        "short_table_names": all(len(name) <= 20 for name in ("oa_fed_providers", "oa_fed_identities")),
        "repository_round_trip": (
            repository.get_provider("company-oidc") == provider
            and repository.find_identity(
                provider_id="company-oidc",
                external_subject_digest=identity["external_subject_digest"],
            )
            == identity
        ),
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "oa_federated_identity_persistence_evidence.v1",
        "slice": "1284",
        "requirement": "S129",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "oa_federated_identity_persistence_failed",
        "migration": MIGRATION,
        "checks": checks,
        "summary": {
            "table_count": sum(bool(body) for body in (provider_sql, identity_sql)),
            "identifier_count": len(identifiers),
            "longest_identifier_length": max(map(len, identifiers), default=0),
            "provider_count": len(repository.list_providers()),
            "identity_count": len(repository.list_identities()),
        },
        "next_slice": "1285" if passed else "blocked",
    }


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


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
    checks = evidence.get("checks") or {}
    return (
        "oa_federated_identity_persistence="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"tables={summary.get('table_count', 0)} "
        f"longest={summary.get('longest_identifier_length', 0)} "
        f"next={evidence.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_federated_identity_persistence()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
