from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


EXPECTED_DATABASE = "nex_oa_test"
EXPECTED_ROLE = "nex_oa_user"
REQUIRED_MIGRATION = "1215_oa_identity_lifecycle"
EXPECTED_CLEANUP_KEYS = frozenset(
    {
        "event_count",
        "session_count",
        "membership_count",
        "subject_count",
        "tenant_count",
    }
)


def evaluate_identity_lifecycle_postgres_smoke(
    migration: Mapping[str, Any], workflow: Mapping[str, Any]
) -> dict[str, Any]:
    planned = _strings(migration.get("planned"))
    applied = _strings(migration.get("applied"))
    skipped = _strings(migration.get("skipped"))
    workflow_checks = _booleans(workflow.get("checks"))
    residue = _integers(workflow.get("cleanup_residue"))
    observations = _mapping(workflow.get("db_observations"))

    checks = {
        "migration_planned": REQUIRED_MIGRATION in planned,
        "migration_applied_or_current": REQUIRED_MIGRATION in {*applied, *skipped},
        "actual_test_database": workflow.get("database") == EXPECTED_DATABASE,
        "expected_test_role": workflow.get("role") == EXPECTED_ROLE,
        "runtime_postgres": workflow.get("runtime_mode") == "postgres",
        "workflow_checks_complete": bool(workflow_checks)
        and all(workflow_checks.values()),
        "subject_event_persisted": (
            observations.get("subject_status") == "DISABLED"
            and observations.get("subject_revision") == 2
            and observations.get("subject_event_count") == 1
        ),
        "membership_event_persisted": (
            observations.get("membership_status") == "DISABLED"
            and observations.get("membership_revision") == 2
            and observations.get("membership_event_count") == 1
        ),
        "sessions_revoked": (
            observations.get("revoked_session_count") == 2
            and observations.get("active_session_count") == 0
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
            None if status == "PASS" else "oa_identity_lifecycle_postgres_smoke_failed"
        ),
        "database_readiness": (
            "ACTUAL_TEST_DATABASE_LIFECYCLE_VERIFIED"
            if status == "PASS"
            else "BLOCKED"
        ),
        "checks": checks,
        "failed_checks": failed_checks,
        "summary": {
            "migration_count": len(planned),
            "workflow_check_count": len(workflow_checks),
            "event_count": int(observations.get("event_count") or 0),
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
