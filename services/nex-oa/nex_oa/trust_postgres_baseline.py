from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from nex_oa.service_principal_boundary import PROPOSED_TABLES


ROOT = Path(__file__).resolve().parents[3]
EXPECTED_DATABASE = "nex_oa_test"
EXPECTED_ROLE = "nex_oa_user"
FORBIDDEN_TRUST_COLUMNS = frozenset(
    {
        "access_token",
        "refresh_token",
        "raw_token",
        "api_key",
        "client_secret",
        "credential_secret",
        "private_key",
        "session_token",
        "password",
    }
)
EXPECTED_CLEANUP_KEYS = (
    "deleted_sessions",
    "deleted_memberships",
    "deleted_subjects",
    "deleted_tenants",
)
EXPECTED_RESIDUE_KEYS = (
    "session_count",
    "membership_count",
    "subject_count",
    "tenant_count",
)


def expected_migration_versions(root: Path = ROOT) -> tuple[str, ...]:
    return tuple(
        path.stem
        for path in sorted((root / "database/nex-oa/migrations").glob("*.sql"))
    )


def evaluate_trust_postgres_baseline(
    *,
    snapshot: Mapping[str, Any],
    migration: Mapping[str, Any],
    workflow: Mapping[str, Any],
    mock_compatibility: Mapping[str, Any],
    root: Path = ROOT,
) -> dict[str, Any]:
    expected_versions = set(expected_migration_versions(root))
    actual_versions = set(snapshot.get("migration_versions") or ())
    planned = tuple(migration.get("planned") or ())
    applied = set(migration.get("applied") or ())
    skipped = set(migration.get("skipped") or ())
    tables = set(snapshot.get("tables") or ())
    forbidden_columns = sorted(
        f"{item['table']}.{item['column']}"
        for item in snapshot.get("columns") or ()
        if item.get("column") in FORBIDDEN_TRUST_COLUMNS
    )
    premature_tables = sorted(tables.intersection(PROPOSED_TABLES))
    workflow_checks = workflow.get("checks") or {}
    cleanup = workflow.get("cleanup_observations") or {}
    residue = workflow.get("cleanup_residue") or {}
    checks = {
        "actual_postgresql_server": (
            snapshot.get("server_kind") == "PostgreSQL"
        ),
        "test_database_exact": snapshot.get("database") == EXPECTED_DATABASE,
        "service_role_exact": snapshot.get("role") == EXPECTED_ROLE,
        "migration_plan_exact": planned == expected_migration_versions(root),
        "migration_execution_complete": (
            not (applied & skipped) and applied | skipped == expected_versions
        ),
        "migration_ledger_exact": actual_versions == expected_versions,
        "forbidden_trust_columns_absent": not forbidden_columns,
        "s126_tables_not_premature": not premature_tables,
        "opaque_session_workflow_verified": (
            bool(workflow_checks) and all(workflow_checks.values())
        ),
        "workflow_cleanup_verified": all(
            cleanup.get(name) == 1 for name in EXPECTED_CLEANUP_KEYS
        ),
        "workflow_cleanup_residue_absent": all(
            residue.get(name) == 0 for name in EXPECTED_RESIDUE_KEYS
        ),
        "mock_compatibility_is_transitional_memory_only": (
            mock_compatibility.get("issued") is True
            and mock_compatibility.get("validated") is True
            and mock_compatibility.get("storage_mode") == "memory_only"
            and mock_compatibility.get("database_mutation") is False
            and bool(mock_compatibility.get("token_fingerprint"))
            and "access_token" not in mock_compatibility
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    passed = not failed_checks
    return {
        "baseline_schema_version": "oa_trust_postgres_baseline.v1",
        "slice": "1250",
        "requirement": "S125",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "oa_trust_postgres_baseline_failed",
        "database": snapshot.get("database"),
        "role": snapshot.get("role"),
        "server_kind": snapshot.get("server_kind"),
        "summary": {
            "expected_migration_count": len(expected_versions),
            "actual_migration_count": len(actual_versions),
            "table_count": len(tables),
            "forbidden_column_count": len(forbidden_columns),
            "premature_table_count": len(premature_tables),
            "workflow_check_count": len(workflow_checks),
            "failed_check_count": len(failed_checks),
            "cleanup_residue_count": sum(int(value) for value in residue.values()),
        },
        "forbidden_columns": forbidden_columns,
        "premature_tables": premature_tables,
        "workflow_evidence": {
            "checks": dict(workflow_checks),
            "cleanup_observations": dict(cleanup),
            "cleanup_residue": dict(residue),
        },
        "mock_compatibility": dict(mock_compatibility),
        "checks": checks,
        "failed_checks": failed_checks,
        "next_slice": "1251",
    }
