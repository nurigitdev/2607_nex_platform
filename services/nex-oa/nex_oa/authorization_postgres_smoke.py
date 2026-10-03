from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


EXPECTED_DATABASE = "nex_oa_test"
EXPECTED_ROLE = "nex_oa_user"
REQUIRED_MIGRATION = "1234_oa_group_role_authorization"
EXPECTED_CLEANUP_KEYS = frozenset(
    {
        "authz_event_count",
        "group_role_count",
        "group_member_count",
        "role_count",
        "group_count",
        "session_count",
        "membership_count",
        "subject_count",
        "tenant_count",
    }
)


def evaluate_authorization_postgres_smoke(
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
        "authorization_rows_persisted": (
            observations.get("role_revision") == 2
            and observations.get("group_count") == 1
            and observations.get("group_member_count") == 1
            and observations.get("group_role_count") == 1
        ),
        "authorization_events_persisted": (
            observations.get("event_count") == 5
            and observations.get("server_actor_count") == 5
            and observations.get("request_trace_count") == 5
            and observations.get("revocation_event_count") == 2
        ),
        "sessions_revoked": (
            observations.get("revoked_session_count") == 2
            and observations.get("active_session_count") == 0
        ),
        "restart_readback_verified": (
            observations.get("restart_role_count") == 1
            and observations.get("restart_group_count") == 1
            and observations.get("restart_group_role_count") == 1
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
            None if status == "PASS" else "oa_authorization_postgres_smoke_failed"
        ),
        "database_readiness": (
            "ACTUAL_TEST_DATABASE_AUTHORIZATION_VERIFIED"
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
