from __future__ import annotations

from pathlib import Path
import re
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
CX_DATABASE_DRIFT_AUDIT_SCHEMA_VERSION = "cx_database_drift_audit.v1"
POSTGRES_IDENTIFIER_MAX_LENGTH = 63

CORE_CX_TABLES = frozenset(
    {
        "cx_source_files",
        "cx_content_objects",
        "cx_content_acl_entries",
        "cx_extraction_artifacts",
        "cx_chunk_sets",
        "cx_chunks",
        "cx_chunk_embeddings",
        "cx_lexical_terms",
        "cx_lexical_postings",
        "cx_document_summaries",
        "cx_document_summary_embeddings",
        "cx_retrieval_packages",
        "cx_retrieval_evidence_items",
        "cx_document_processing_runs",
        "cx_document_processing_steps",
        "cx_remediation_execution_attempts",
    }
)


def build_cx_database_drift_audit(root: Path = ROOT) -> dict[str, Any]:
    migration_dir = root / "database/nex-cx/migrations"
    migration_paths = sorted(migration_dir.glob("*.sql"))
    migrations = []
    identifiers: set[str] = set()
    declared_tables: set[str] = set()
    issues = []

    for path in migration_paths:
        sql = path.read_text(encoding="utf-8")
        compact = " ".join(sql.lower().split())
        version = path.stem
        recorded = (
            "schema_migrations" in compact
            and f"'{version.lower()}'" in compact
        )
        transaction_wrapped = compact.startswith("begin;") and compact.endswith(
            "commit;"
        )
        migration = {
            "version": version,
            "path": str(path.relative_to(root)),
            "ledger_recorded": recorded,
            "transaction_wrapped": transaction_wrapped,
        }
        migrations.append(migration)
        if not recorded:
            issues.append({"category": "migration_ledger_missing", "version": version})
        if not transaction_wrapped:
            issues.append(
                {"category": "migration_transaction_missing", "version": version}
            )
        parsed = _sql_identifiers(sql)
        identifiers.update(parsed)
        declared_tables.update(_declared_table_names(sql))

    versions = [item["version"] for item in migrations]
    too_long = sorted(
        identifier
        for identifier in identifiers
        if len(identifier) > POSTGRES_IDENTIFIER_MAX_LENGTH
    )
    missing_tables = sorted(CORE_CX_TABLES - declared_tables)
    repository_paths = (
        root / "services/nex-cx/nex_cx/repository.py",
        root / "services/nex-cx/nex_cx/remediation_execution.py",
    )
    repository_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in repository_paths
        if path.is_file()
    )
    missing_repository_refs = sorted(
        table for table in CORE_CX_TABLES if table not in repository_source
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
        "migration_count_expected": len(migrations) == 13,
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
        "postgres_identifier_lengths_safe": not too_long,
        "migration_runner_ready": runner_ready,
    }
    if missing_tables:
        issues.append({"category": "core_tables_missing", "tables": missing_tables})
    if missing_repository_refs:
        issues.append(
            {
                "category": "repository_table_refs_missing",
                "tables": missing_repository_refs,
            }
        )
    if too_long:
        issues.append({"category": "identifier_too_long", "identifiers": too_long})
    if not runner_ready:
        issues.append({"category": "migration_runner_incomplete"})

    passed = all(checks.values()) and not issues
    longest_identifier = max(identifiers, key=len, default="")
    alembic_path = root / "database/nex-cx/alembic"
    return {
        "audit_schema_version": CX_DATABASE_DRIFT_AUDIT_SCHEMA_VERSION,
        "slice": "0907",
        "requirement": "S91",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "cx_database_drift_audit_failed",
        "database_readiness": "STATIC_CHAIN_CLEAN_RUNTIME_DATABASE_PENDING",
        "migration_strategy": {
            "canonical": "versioned_sql_schema_migrations_runner",
            "alembic_status": (
                "CONFIGURED" if alembic_path.is_dir() else "NOT_CONFIGURED"
            ),
            "alembic_config_builder_present": (
                "def build_alembic_config(" in migration_runner_source
            ),
            "decision_required_before_next_schema_change": True,
            "policy": "keep_exactly_one_canonical_migration_history",
        },
        "summary": {
            "migration_count": len(migrations),
            "declared_table_count": len(declared_tables),
            "core_table_count": len(CORE_CX_TABLES),
            "identifier_count": len(identifiers),
            "longest_identifier": longest_identifier,
            "longest_identifier_length": len(longest_identifier),
            "identifier_limit": POSTGRES_IDENTIFIER_MAX_LENGTH,
            "issue_count": len(issues),
        },
        "checks": checks,
        "migrations": migrations,
        "missing_tables": missing_tables,
        "missing_repository_refs": missing_repository_refs,
        "overlength_identifiers": too_long,
        "issues": issues,
        "actual_database_comparison": {
            "status": "DEFERRED_TO_SLICE_0909",
            "database_env": "NEX_CX_TEST_DATABASE_URL",
        },
        "next_slice": "0908",
    }


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
    created = {
        match.group(1).lower()
        for match in re.finditer(
            r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-z][a-z0-9_]*)",
            sql,
            flags=re.IGNORECASE,
        )
    }
    renamed = {
        match.group(1).lower()
        for match in re.finditer(
            r"\bRENAME\s+TO\s+([a-z][a-z0-9_]*)",
            sql,
            flags=re.IGNORECASE,
        )
    }
    return created | renamed
