from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Mapping

from nex_oa.database_drift_audit import (
    CORE_OA_TABLES,
    POSTGRES_IDENTIFIER_MAX_LENGTH,
)


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_VERSION = "oa_postgres_reaudit.v1"
EXPECTED_DATABASE = "nex_oa_test"
EXPECTED_ROLE = "nex_oa_user"
FORBIDDEN_PRIVATE_COLUMNS = frozenset(
    {
        "access_token",
        "api_key",
        "password",
        "raw_token",
        "refresh_token",
        "secret",
    }
)
EXPECTED_CLEANUP_KEYS = (
    "deleted_sessions",
    "deleted_credentials",
    "deleted_memberships",
    "deleted_subjects",
    "deleted_tenants",
)
EXPECTED_RESIDUE_KEYS = (
    "session_count",
    "credential_count",
    "membership_count",
    "subject_count",
    "tenant_count",
)


def expected_oa_postgres_state(root: Path = ROOT) -> dict[str, tuple[str, ...]]:
    migration_paths = sorted((root / "database/nex-oa/migrations").glob("*.sql"))
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


def evaluate_oa_postgres_reaudit(
    snapshot: Mapping[str, Any],
    migration_result: Mapping[str, Any],
    workflow_result: Mapping[str, Any],
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    expected = expected_oa_postgres_state(root)
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
    missing_tables = sorted(CORE_OA_TABLES - actual_tables)
    missing_indexes = sorted(set(expected["indexes"]) - actual_indexes)
    missing_constraints = sorted(
        set(expected["constraints"]) - actual_constraints
    )
    planned = tuple(migration_result.get("planned") or ())
    applied = set(migration_result.get("applied") or ())
    skipped = set(migration_result.get("skipped") or ())
    workflow_checks = workflow_result.get("checks") or {}
    cleanup = workflow_result.get("cleanup_observations") or {}
    residue = workflow_result.get("cleanup_residue") or {}
    checks = {
        "test_database_exact": snapshot.get("database") == EXPECTED_DATABASE,
        "service_role_exact": snapshot.get("role") == EXPECTED_ROLE,
        "migration_plan_exact": planned == expected["migration_versions"],
        "migration_execution_complete": (
            not (applied & skipped) and applied | skipped == expected_versions
        ),
        "migration_ledger_exact": not missing_versions and not unexpected_versions,
        "core_tables_present": not missing_tables,
        "declared_indexes_present": not missing_indexes,
        "declared_constraints_present": not missing_constraints,
        "identifier_lengths_safe": (
            int(snapshot.get("longest_identifier_length") or 0)
            <= POSTGRES_IDENTIFIER_MAX_LENGTH
        ),
        "forbidden_private_columns_absent": not forbidden_columns,
        "identity_login_session_workflow_verified": (
            bool(workflow_checks) and all(workflow_checks.values())
        ),
        "cleanup_delete_counts_verified": all(
            cleanup.get(key) == 1 for key in EXPECTED_CLEANUP_KEYS
        ),
        "cleanup_residue_absent": all(
            residue.get(key) == 0 for key in EXPECTED_RESIDUE_KEYS
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    status = "PASS" if not failed_checks else "FAIL"
    db_observations = workflow_result.get("db_observations") or {}
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1210",
        "requirement": "S121",
        "status": status,
        "failure_code": None if status == "PASS" else "oa_postgres_reaudit_failed",
        "database_readiness": (
            "ACTUAL_TEST_DATABASE_IDENTITY_FLOW_VERIFIED"
            if status == "PASS"
            else "RUNTIME_DRIFT_FOUND"
        ),
        "database": snapshot.get("database"),
        "role": snapshot.get("role"),
        "summary": {
            "expected_migration_count": len(expected_versions),
            "actual_migration_count": len(actual_versions),
            "core_table_count": len(CORE_OA_TABLES),
            "actual_table_count": len(actual_tables),
            "declared_index_count": len(expected["indexes"]),
            "declared_constraint_count": len(expected["constraints"]),
            "longest_identifier_length": int(
                snapshot.get("longest_identifier_length") or 0
            ),
            "forbidden_column_count": len(forbidden_columns),
            "workflow_check_count": len(workflow_checks),
            "failed_check_count": len(failed_checks),
        },
        "checks": checks,
        "failed_checks": failed_checks,
        "missing_migrations": missing_versions,
        "unexpected_migrations": unexpected_versions,
        "missing_tables": missing_tables,
        "missing_indexes": missing_indexes,
        "missing_constraints": missing_constraints,
        "forbidden_private_columns": forbidden_columns,
        "longest_identifier": snapshot.get("longest_identifier") or "",
        "identifier_limit": POSTGRES_IDENTIFIER_MAX_LENGTH,
        "workflow_evidence": {
            "checks": dict(workflow_checks),
            "credential_count": int(db_observations.get("credential_count") or 0),
            "membership_count": int(db_observations.get("membership_count") or 0),
            "session_count": int(db_observations.get("session_count") or 0),
            "session_status": db_observations.get("session_status"),
            "hash_algorithm": db_observations.get("hash_algorithm"),
            "raw_password_match_count": int(
                db_observations.get("raw_password_match_count") or 0
            ),
            "cleanup_observations": dict(cleanup),
            "cleanup_residue": dict(residue),
        },
        "migration_result": {
            "applied": sorted(applied),
            "skipped": sorted(skipped),
        },
        "privacy_policy": {
            "payload": "synthetic_identity_metadata_only",
            "secrets_in_evidence": False,
            "database_url": "redacted",
            "cleanup": "required_and_residue_verified",
        },
        "next_slice": "1211",
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
