from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


EXPECTED_DATABASE = "nex_oa_test"
EXPECTED_ROLE = "nex_oa_user"
REQUIRED_MIGRATION = "1225_oa_credential_session_security"
EXPECTED_EVENT_COUNTS = {
    "LOGIN_FAILED": 5,
    "LOGIN_SUCCEEDED": 2,
    "PASSWORD_CHANGED": 2,
    "PASSWORD_RESET": 1,
    "SESSION_INTROSPECTED": 2,
}
EXPECTED_CLEANUP_KEYS = frozenset(
    {
        "event_count",
        "session_count",
        "credential_count",
        "membership_count",
        "subject_count",
        "tenant_count",
    }
)


def evaluate_credential_security_postgres_smoke(
    migration: Mapping[str, Any], workflow: Mapping[str, Any]
) -> dict[str, Any]:
    planned = _strings(migration.get("planned"))
    applied = _strings(migration.get("applied"))
    skipped = _strings(migration.get("skipped"))
    workflow_checks = _booleans(workflow.get("checks"))
    residue = _integers(workflow.get("cleanup_residue"))
    observations = _mapping(workflow.get("db_observations"))
    event_counts = _integers(observations.get("event_counts"))

    checks = {
        "migration_planned": REQUIRED_MIGRATION in planned,
        "migration_applied_or_current": REQUIRED_MIGRATION in {*applied, *skipped},
        "actual_test_database": workflow.get("database") == EXPECTED_DATABASE,
        "expected_test_role": workflow.get("role") == EXPECTED_ROLE,
        "runtime_postgres": workflow.get("runtime_mode") == "postgres",
        "workflow_checks_complete": bool(workflow_checks)
        and all(workflow_checks.values()),
        "credential_recovered_and_rehashed": (
            observations.get("credential_status") == "ACTIVE"
            and observations.get("password_hash_algorithm") == "argon2id.v1"
            and observations.get("failed_attempt_count") == 0
            and observations.get("locked_at") is None
        ),
        "sessions_revoked": (
            observations.get("revoked_session_count") == 2
            and observations.get("active_session_count") == 0
        ),
        "auth_event_counts_exact": event_counts == EXPECTED_EVENT_COUNTS,
        "auth_event_outcomes_exact": (
            observations.get("succeeded_event_count") == 6
            and observations.get("blocked_event_count") == 6
            and observations.get("failed_event_count") == 0
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
            None if status == "PASS" else "oa_credential_security_postgres_smoke_failed"
        ),
        "database_readiness": (
            "ACTUAL_TEST_DATABASE_CREDENTIAL_SECURITY_VERIFIED"
            if status == "PASS"
            else "BLOCKED"
        ),
        "checks": checks,
        "failed_checks": failed_checks,
        "summary": {
            "migration_count": len(planned),
            "workflow_check_count": len(workflow_checks),
            "auth_event_count": sum(event_counts.values()),
            "revoked_session_count": int(
                observations.get("revoked_session_count") or 0
            ),
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
