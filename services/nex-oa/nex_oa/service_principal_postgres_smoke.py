from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


EXPECTED_DATABASE = "nex_oa_test"
EXPECTED_ROLE = "nex_oa_user"
REQUIRED_MIGRATION = "1254_oa_service_principal_lifecycle"
EXPECTED_CLEANUP_KEYS = frozenset(("credential_count", "principal_count"))


def evaluate_service_principal_postgres_smoke(
    migration: Mapping[str, Any], workflow: Mapping[str, Any]
) -> dict[str, Any]:
    planned = _strings(migration.get("planned"))
    applied = _strings(migration.get("applied"))
    skipped = _strings(migration.get("skipped"))
    workflow_checks = _booleans(workflow.get("checks"))
    observations = _mapping(workflow.get("db_observations"))
    residue = _integers(workflow.get("cleanup_residue"))
    checks = {
        "migration_planned": REQUIRED_MIGRATION in planned,
        "migration_applied_or_current": REQUIRED_MIGRATION in {*applied, *skipped},
        "migration_inventory_current": (
            len(planned) == 15
            and observations.get("migration_ledger_count") == 15
            and observations.get("required_migration_count") == 1
        ),
        "actual_test_database": workflow.get("database") == EXPECTED_DATABASE,
        "expected_test_role": workflow.get("role") == EXPECTED_ROLE,
        "runtime_postgres": workflow.get("runtime_mode") == "postgres",
        "workflow_checks_complete": bool(workflow_checks)
        and all(workflow_checks.values()),
        "rows_persisted": (
            observations.get("principal_count") == 1
            and observations.get("credential_count") == 2
            and observations.get("rotating_credential_count") == 1
            and observations.get("revoked_credential_count") == 1
        ),
        "secrets_hashed_only": (
            observations.get("argon2id_hash_count") == 2
            and observations.get("plaintext_match_count") == 0
            and observations.get("distinct_secret_hint_count") == 2
        ),
        "restart_readback_verified": (
            observations.get("restart_principal_count") == 1
            and observations.get("restart_credential_count") == 2
        ),
        "cleanup_residue_complete": set(residue) == EXPECTED_CLEANUP_KEYS,
        "cleanup_residue_zero": bool(residue)
        and all(value == 0 for value in residue.values()),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    status = "PASS" if not failed_checks else "FAIL"
    return {
        "status": status,
        "failure_code": (
            None if status == "PASS" else "oa_service_principal_postgres_smoke_failed"
        ),
        "database_readiness": (
            "ACTUAL_TEST_DATABASE_SERVICE_PRINCIPAL_VERIFIED"
            if status == "PASS"
            else "BLOCKED"
        ),
        "checks": checks,
        "failed_checks": failed_checks,
        "summary": {
            "migration_count": len(planned),
            "workflow_check_count": len(workflow_checks),
            "persisted_credential_count": int(
                observations.get("credential_count") or 0
            ),
            "argon2id_hash_count": int(observations.get("argon2id_hash_count") or 0),
            "cleanup_residue_count": sum(residue.values()),
        },
        "workflow": dict(workflow),
    }


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(str(item) for item in value)


def _booleans(value: Any) -> dict[str, bool]:
    return {str(key): item is True for key, item in _mapping(value).items()}


def _integers(value: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    for key, item in _mapping(value).items():
        if isinstance(item, bool):
            continue
        try:
            result[str(key)] = int(item)
        except (TypeError, ValueError):
            continue
    return result
