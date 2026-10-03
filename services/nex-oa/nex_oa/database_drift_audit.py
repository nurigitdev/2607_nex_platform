from __future__ import annotations

from pathlib import Path
import re
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_VERSION = "oa_database_drift_audit.v1"
POSTGRES_IDENTIFIER_MAX_LENGTH = 63
MINIMUM_OA_MIGRATION_COUNT = 11

CORE_OA_TABLES = frozenset(
    {
        "oa_tenants",
        "oa_subjects",
        "oa_tenant_memberships",
        "oa_user_sessions",
        "oa_local_credentials",
        "oa_roles",
        "oa_groups",
        "oa_group_members",
        "oa_group_roles",
        "oa_authz_events",
        "oa_service_principals",
        "oa_service_creds",
    }
)


def build_oa_database_drift_audit(root: Path = ROOT) -> dict[str, Any]:
    migration_dir = root / "database/nex-oa/migrations"
    migration_paths = sorted(migration_dir.glob("*.sql"))
    migrations = []
    identifiers: set[str] = set()
    declared_tables: set[str] = set()
    evidence_issues = []

    for path in migration_paths:
        sql = path.read_text(encoding="utf-8")
        compact = " ".join(sql.lower().split())
        version = path.stem
        ledger_recorded = (
            "schema_migrations" in compact and f"'{version.lower()}'" in compact
        )
        transaction_wrapped = compact.startswith("begin;") and compact.endswith(
            "commit;"
        )
        migrations.append(
            {
                "version": version,
                "path": str(path.relative_to(root)),
                "ledger_recorded": ledger_recorded,
                "transaction_wrapped": transaction_wrapped,
            }
        )
        if not ledger_recorded:
            evidence_issues.append(
                {"category": "migration_ledger_missing", "version": version}
            )
        if not transaction_wrapped:
            evidence_issues.append(
                {"category": "migration_transaction_missing", "version": version}
            )
        identifiers.update(_sql_identifiers(sql))
        declared_tables.update(_declared_table_names(sql))

    versions = [item["version"] for item in migrations]
    overlength = sorted(
        identifier
        for identifier in identifiers
        if len(identifier.encode("utf-8")) > POSTGRES_IDENTIFIER_MAX_LENGTH
    )
    missing_tables = sorted(CORE_OA_TABLES - declared_tables)
    repository_source = _repository_source(root)
    missing_repository_refs = sorted(
        table for table in CORE_OA_TABLES if table not in repository_source
    )
    migration_runner_path = root / "scripts/db/run_migrations.py"
    migration_runner_source = (
        migration_runner_path.read_text(encoding="utf-8")
        if migration_runner_path.is_file()
        else ""
    )
    runner_ready = all(
        token in migration_runner_source
        for token in (
            "def load_migrations(",
            "def validate_migration_sql(",
            "def ensure_schema_migrations_table(",
        )
    )
    checks = {
        "migration_count_expected": len(migrations) >= MINIMUM_OA_MIGRATION_COUNT,
        "migration_versions_ordered_unique": (
            versions == sorted(versions) and len(versions) == len(set(versions))
        ),
        "migration_ledger_complete": all(
            item["ledger_recorded"] for item in migrations
        ),
        "migration_transactions_complete": all(
            item["transaction_wrapped"] for item in migrations
        ),
        "core_tables_declared": not missing_tables,
        "repository_core_table_refs_complete": not missing_repository_refs,
        "migration_runner_ready": runner_ready,
        "postgres_identifiers_within_limit": not overlength,
    }
    if missing_tables:
        evidence_issues.append(
            {"category": "core_tables_missing", "tables": missing_tables}
        )
    if missing_repository_refs:
        evidence_issues.append(
            {
                "category": "repository_table_refs_missing",
                "tables": missing_repository_refs,
            }
        )
    if not runner_ready:
        evidence_issues.append({"category": "migration_runner_incomplete"})
    if overlength:
        evidence_issues.append(
            {
                "category": "postgres_identifier_overlength",
                "identifiers": overlength,
            }
        )

    passed = all(checks.values()) and not evidence_issues
    longest_identifier = max(
        identifiers,
        key=lambda item: len(item.encode("utf-8")),
        default="",
    )
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1204",
        "requirement": "S121",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "oa_database_drift_audit_failed",
        "database_readiness": (
            "STATIC_CHAIN_CLEAN_RUNTIME_DATABASE_PENDING"
            if passed
            else "STATIC_CHAIN_INVALID"
        ),
        "migration_strategy": {
            "canonical": "versioned_sql_schema_migrations_runner",
            "alembic_status": (
                "CONFIGURED"
                if (root / "database/nex-oa/alembic").is_dir()
                else "NOT_CONFIGURED"
            ),
            "alembic_config_builder_present": (
                "def build_alembic_config(" in migration_runner_source
            ),
            "policy": "keep_exactly_one_canonical_migration_history",
        },
        "summary": {
            "migration_count": len(migrations),
            "declared_table_count": len(declared_tables),
            "core_table_count": len(CORE_OA_TABLES),
            "identifier_count": len(identifiers),
            "longest_identifier": longest_identifier,
            "longest_identifier_length": len(longest_identifier.encode("utf-8")),
            "identifier_limit": POSTGRES_IDENTIFIER_MAX_LENGTH,
            "overlength_identifier_count": len(overlength),
            "evidence_issue_count": len(evidence_issues),
        },
        "checks": checks,
        "migrations": migrations,
        "missing_tables": missing_tables,
        "missing_repository_refs": missing_repository_refs,
        "overlength_identifiers": overlength,
        "issues": evidence_issues,
        "actual_database_comparison": {
            "status": "DEFERRED_TO_SLICE_1210",
            "database_env": "NEX_OA_TEST_DATABASE_URL",
        },
        "next_slice": "1205",
    }


def _repository_source(root: Path) -> str:
    paths = (
        root / "services/nex-oa/nex_oa/subjects.py",
        root / "services/nex-oa/nex_oa/memberships.py",
        root / "services/nex-oa/nex_oa/sessions.py",
        root / "services/nex-oa/nex_oa/credentials.py",
        root / "services/nex-oa/nex_oa/authorization.py",
        root / "services/nex-oa/nex_oa/service_principal_repository.py",
    )
    return "\n".join(
        path.read_text(encoding="utf-8") for path in paths if path.is_file()
    )


def _sql_identifiers(sql: str) -> set[str]:
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


def _declared_table_names(sql: str) -> set[str]:
    return {
        match.group(1).lower()
        for match in re.finditer(
            r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-z][a-z0-9_]*)",
            sql,
            flags=re.IGNORECASE,
        )
    }
