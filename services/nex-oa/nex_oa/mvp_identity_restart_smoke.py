from __future__ import annotations

from collections.abc import Mapping
from typing import Any


EXPECTED_DATABASE = "nex_oa_test"
EXPECTED_ROLE = "nex_oa_user"
EXPECTED_MIGRATION_COUNT = 17
EXPECTED_RESIDUE_KEYS = frozenset(
    {
        "authz_event_count",
        "group_role_count",
        "group_member_count",
        "group_count",
        "role_count",
        "session_count",
        "credential_count",
        "membership_count",
        "subject_count",
        "tenant_count",
    }
)


def evaluate_oa_identity_restart_smoke(
    migration: Mapping[str, Any],
    workflow: Mapping[str, Any],
) -> dict[str, Any]:
    planned = tuple(str(item) for item in migration.get("planned", ()))
    checks_in = {
        str(name): value is True
        for name, value in _mapping(workflow.get("checks")).items()
    }
    observations = _mapping(workflow.get("db_observations"))
    residue = {
        str(name): int(value)
        for name, value in _mapping(workflow.get("cleanup_residue")).items()
        if isinstance(value, int) and not isinstance(value, bool)
    }
    checks = {
        "migration_inventory_current": (
            len(planned) == EXPECTED_MIGRATION_COUNT
            and observations.get("migration_ledger_count")
            == EXPECTED_MIGRATION_COUNT
        ),
        "actual_test_database": workflow.get("database") == EXPECTED_DATABASE,
        "expected_test_role": workflow.get("role") == EXPECTED_ROLE,
        "runtime_postgres": workflow.get("runtime_mode") == "postgres",
        "workflow_checks_complete": bool(checks_in)
        and all(checks_in.values()),
        "all_identity_rows_persisted": all(
            observations.get(name) == expected
            for name, expected in {
                "tenant_count": 1,
                "subject_count": 1,
                "membership_count": 1,
                "credential_count": 1,
                "session_count": 1,
                "role_count": 1,
                "group_count": 1,
                "group_member_count": 1,
                "group_role_count": 1,
                "authz_event_count": 4,
            }.items()
        ),
        "private_material_absent": (
            observations.get("raw_password_match_count") == 0
            and observations.get("password_hash_count") == 1
        ),
        "cleanup_residue_complete": set(residue) == EXPECTED_RESIDUE_KEYS,
        "cleanup_residue_zero": bool(residue)
        and all(value == 0 for value in residue.values()),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    passed = not failed_checks
    return {
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None if passed else "oa_identity_restart_smoke_failed"
        ),
        "checks": checks,
        "failed_checks": failed_checks,
        "summary": {
            "migration_count": len(planned),
            "restart_read_count": sum(checks_in.values()),
            "persisted_row_class_count": 10,
            "cleanup_residue_count": sum(residue.values()),
        },
        "workflow": dict(workflow),
    }


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}
