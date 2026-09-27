from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Mapping

from nex_ae_api.database_drift_audit import (
    CORE_AE_TABLES,
    POSTGRES_IDENTIFIER_MAX_LENGTH,
)


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_VERSION = "ae_postgres_reaudit.v1"
EXPECTED_DATABASE = "nex_ae_test"
EXPECTED_ROLE = "nex_ae_user"
LEGACY_TABLES = frozenset({"ae_artifact_blobs", "ae_source_files"})
FORBIDDEN_PRIVATE_COLUMNS = frozenset(
    {
        "access_token",
        "api_key",
        "password",
        "raw_output",
        "raw_prompt",
        "refresh_token",
        "source_bytes",
    }
)


def expected_ae_postgres_state(root: Path = ROOT) -> dict[str, tuple[str, ...]]:
    migration_paths = sorted(
        (root / "database/nex-ae-api/migrations").glob("*.sql")
    )
    source = "\n".join(path.read_text(encoding="utf-8") for path in migration_paths)
    indexes = _named_identifiers(
        source,
        r"\bCREATE\s+(?:UNIQUE\s+)?INDEX\s+"
        r"(?:IF\s+NOT\s+EXISTS\s+)?([a-z][a-z0-9_]*)",
    )
    constraints = _named_identifiers(
        source,
        r"\bCONSTRAINT\s+([a-z][a-z0-9_]*)",
    )
    return {
        "migration_versions": tuple(path.stem for path in migration_paths),
        "indexes": tuple(sorted(_postgres_identifier(item) for item in indexes)),
        "constraints": tuple(
            sorted(_postgres_identifier(item) for item in constraints)
        ),
    }


def evaluate_ae_postgres_reaudit(
    snapshot: Mapping[str, Any],
    migration_result: Mapping[str, Any],
    browser_result: Mapping[str, Any],
    *,
    privacy_runbook_ready: bool,
    root: Path = ROOT,
) -> dict[str, Any]:
    expected = expected_ae_postgres_state(root)
    expected_versions = set(expected["migration_versions"])
    actual_versions = set(snapshot.get("migration_versions") or ())
    actual_tables = set(snapshot.get("tables") or ())
    actual_indexes = set(snapshot.get("indexes") or ())
    actual_constraints = set(snapshot.get("constraints") or ())
    forbidden_columns = sorted(
        {
            f"{item['table']}.{item['column']}"
            for item in snapshot.get("columns") or ()
            if item.get("column") in FORBIDDEN_PRIVATE_COLUMNS
        }
    )
    missing_versions = sorted(expected_versions - actual_versions)
    unexpected_versions = sorted(actual_versions - expected_versions)
    missing_tables = sorted(CORE_AE_TABLES - actual_tables)
    legacy_tables = sorted(LEGACY_TABLES & actual_tables)
    missing_indexes = sorted(set(expected["indexes"]) - actual_indexes)
    missing_constraints = sorted(
        set(expected["constraints"]) - actual_constraints
    )
    planned = tuple(migration_result.get("planned") or ())
    applied = set(migration_result.get("applied") or ())
    skipped = set(migration_result.get("skipped") or ())
    probe = snapshot.get("domain_probe") or {}
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
        "forbidden_private_columns_absent": not forbidden_columns,
        "domain_upsert_select_rollback_verified": all(
            probe.get(key) is True
            for key in (
                "insert_observed",
                "upsert_observed",
                "select_observed",
                "rollback_observed",
            )
        ),
        "actual_browser_runtime_verified": browser_result.get("status") == "PASS",
        "privacy_runbook_ready": privacy_runbook_ready,
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    status = "PASS" if not failed_checks else "FAIL"
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1010",
        "requirement": "S101",
        "status": status,
        "failure_code": None if status == "PASS" else "ae_postgres_reaudit_failed",
        "database_readiness": (
            "ACTUAL_TEST_DATABASE_AND_BROWSER_VERIFIED"
            if status == "PASS"
            else "RUNTIME_DRIFT_FOUND"
        ),
        "database": snapshot.get("database"),
        "role": snapshot.get("role"),
        "summary": {
            "expected_migration_count": len(expected_versions),
            "actual_migration_count": len(actual_versions),
            "core_table_count": len(CORE_AE_TABLES),
            "actual_table_count": len(actual_tables),
            "declared_index_count": len(expected["indexes"]),
            "declared_constraint_count": len(expected["constraints"]),
            "longest_identifier_length": int(
                snapshot.get("longest_identifier_length") or 0
            ),
            "forbidden_column_count": len(forbidden_columns),
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
        "forbidden_private_columns": forbidden_columns,
        "longest_identifier": snapshot.get("longest_identifier") or "",
        "identifier_limit": POSTGRES_IDENTIFIER_MAX_LENGTH,
        "domain_probe": dict(probe),
        "browser_runtime": {
            "status": browser_result.get("status"),
            "tool": browser_result.get("tool"),
            "browser": browser_result.get("browser"),
        },
        "migration_result": {
            "applied": sorted(applied),
            "skipped": sorted(skipped),
        },
        "privacy_policy": {
            "probe_payload": "synthetic_metadata_only",
            "transaction": "rollback_required",
            "evidence_output": "metadata_counts_and_names_only",
            "database_url": "redacted",
        },
        "next_slice": "1011",
    }


def _named_identifiers(source: str, pattern: str) -> set[str]:
    return {
        match.group(1).lower()
        for match in re.finditer(pattern, source, flags=re.IGNORECASE)
    }


def _postgres_identifier(identifier: str) -> str:
    encoded = identifier.encode("utf-8")
    if len(encoded) <= POSTGRES_IDENTIFIER_MAX_LENGTH:
        return identifier
    return encoded[:POSTGRES_IDENTIFIER_MAX_LENGTH].decode("utf-8", errors="ignore")
