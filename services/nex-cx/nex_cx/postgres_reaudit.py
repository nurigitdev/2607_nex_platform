from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Mapping

from nex_cx.database_drift_audit import (
    CORE_CX_TABLES,
    POSTGRES_IDENTIFIER_MAX_LENGTH,
)


ROOT = Path(__file__).resolve().parents[3]
CX_POSTGRES_REAUDIT_SCHEMA_VERSION = "cx_postgres_reaudit.v1"
EXPECTED_DATABASE = "nex_cx_test"
EXPECTED_ROLE = "nex_cx_user"
LEGACY_TABLES = frozenset({"cx_source_blobs"})
PRIVATE_PAYLOAD_COLUMNS = frozenset(
    {
        "api_key",
        "chunk_text",
        "embedding_vector",
        "evidence_text",
        "markdown_text",
        "password",
        "prompt_text",
        "query_text",
        "raw_output",
        "source_bytes",
        "source_text",
        "summary_embedding_vector",
        "summary_text",
    }
)


def expected_cx_postgres_state(root: Path = ROOT) -> dict[str, tuple[str, ...]]:
    migration_paths = sorted((root / "database/nex-cx/migrations").glob("*.sql"))
    source = "\n".join(path.read_text(encoding="utf-8") for path in migration_paths)
    return {
        "migration_versions": tuple(path.stem for path in migration_paths),
        "indexes": tuple(
            sorted(
                _named_identifiers(
                    source,
                    r"\bCREATE\s+(?:UNIQUE\s+)?INDEX\s+"
                    r"(?:IF\s+NOT\s+EXISTS\s+)?([a-z][a-z0-9_]*)",
                )
            )
        ),
        "constraints": tuple(
            sorted(
                _named_identifiers(
                    source,
                    r"\bCONSTRAINT\s+([a-z][a-z0-9_]*)",
                )
            )
        ),
    }


def evaluate_cx_postgres_reaudit(
    snapshot: Mapping[str, Any],
    migration_result: Mapping[str, Any],
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    expected = expected_cx_postgres_state(root)
    expected_versions = set(expected["migration_versions"])
    actual_versions = set(snapshot.get("migration_versions") or ())
    actual_tables = set(snapshot.get("tables") or ())
    actual_indexes = set(snapshot.get("indexes") or ())
    actual_constraints = set(snapshot.get("constraints") or ())
    private_columns = sorted(
        {
            f"{item['table']}.{item['column']}"
            for item in snapshot.get("columns") or ()
            if item.get("column") in PRIVATE_PAYLOAD_COLUMNS
        }
    )
    missing_versions = sorted(expected_versions - actual_versions)
    unexpected_versions = sorted(actual_versions - expected_versions)
    missing_tables = sorted(CORE_CX_TABLES - actual_tables)
    legacy_tables = sorted(LEGACY_TABLES & actual_tables)
    missing_indexes = sorted(set(expected["indexes"]) - actual_indexes)
    missing_constraints = sorted(
        set(expected["constraints"]) - actual_constraints
    )
    planned = tuple(migration_result.get("planned") or ())
    applied = set(migration_result.get("applied") or ())
    skipped = set(migration_result.get("skipped") or ())
    probe = snapshot.get("rollback_probe") or {}
    checks = {
        "test_database_exact": snapshot.get("database") == EXPECTED_DATABASE,
        "service_role_exact": snapshot.get("role") == EXPECTED_ROLE,
        "migration_plan_exact": planned == expected["migration_versions"],
        "migration_execution_complete": (
            not (applied & skipped) and applied | skipped == expected_versions
        ),
        "migration_ledger_exact": not missing_versions and not unexpected_versions,
        "core_tables_present": not missing_tables,
        "legacy_tables_absent": not legacy_tables,
        "declared_indexes_present": not missing_indexes,
        "declared_constraints_present": not missing_constraints,
        "identifier_lengths_safe": (
            int(snapshot.get("longest_identifier_length") or 0)
            <= POSTGRES_IDENTIFIER_MAX_LENGTH
        ),
        "public_schema_metadata_only": not private_columns,
        "rollback_probe_verified": all(
            probe.get(key) is True
            for key in ("write_observed", "read_observed", "rollback_observed")
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    status = "PASS" if not failed_checks else "FAIL"
    return {
        "audit_schema_version": CX_POSTGRES_REAUDIT_SCHEMA_VERSION,
        "slice": "0909",
        "requirement": "S91",
        "status": status,
        "failure_code": None if status == "PASS" else "cx_postgres_reaudit_failed",
        "database_readiness": (
            "ACTUAL_TEST_DATABASE_CLEAN" if status == "PASS" else "DATABASE_DRIFT_FOUND"
        ),
        "database": snapshot.get("database"),
        "role": snapshot.get("role"),
        "summary": {
            "expected_migration_count": len(expected_versions),
            "actual_migration_count": len(actual_versions),
            "core_table_count": len(CORE_CX_TABLES),
            "actual_table_count": len(actual_tables),
            "declared_index_count": len(expected["indexes"]),
            "declared_constraint_count": len(expected["constraints"]),
            "longest_identifier_length": int(
                snapshot.get("longest_identifier_length") or 0
            ),
            "private_column_violation_count": len(private_columns),
            "failed_check_count": len(failed_checks),
        },
        "checks": checks,
        "failed_checks": failed_checks,
        "missing_migrations": missing_versions,
        "unexpected_migrations": unexpected_versions,
        "missing_tables": missing_tables,
        "legacy_tables": legacy_tables,
        "missing_indexes": missing_indexes,
        "missing_constraints": missing_constraints,
        "private_column_violations": private_columns,
        "longest_identifier": snapshot.get("longest_identifier") or "",
        "identifier_limit": POSTGRES_IDENTIFIER_MAX_LENGTH,
        "rollback_probe": dict(probe),
        "migration_result": {
            "applied": sorted(applied),
            "skipped": sorted(skipped),
        },
        "privacy_policy": {
            "scope": "public_schema",
            "private_payload_columns": sorted(PRIVATE_PAYLOAD_COLUMNS),
            "evidence_output": "metadata_counts_and_names_only",
        },
        "next_slice": "0910",
    }


def _named_identifiers(source: str, pattern: str) -> set[str]:
    return {
        match.group(1).lower()
        for match in re.finditer(pattern, source, flags=re.IGNORECASE)
    }
