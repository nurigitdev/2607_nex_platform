from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


EXPECTED_DATABASE = "nex_oa_test"
EXPECTED_ROLE = "nex_oa_user"
REQUIRED_MIGRATION = "1264_oa_signed_token_lifecycle"
EXPECTED_MIGRATION_COUNT = 16
EXPECTED_CONSUMERS = ("nex-ae-api", "nex-cx", "nex-mo", "nex-ag")
EXPECTED_CLEANUP_KEYS = frozenset(
    ("signing_key_count", "credential_count", "principal_count")
)


def evaluate_platform_signed_token_postgres_smoke(
    migration: Mapping[str, Any],
    workflow: Mapping[str, Any],
) -> dict[str, Any]:
    planned = _strings(migration.get("planned"))
    applied = _strings(migration.get("applied"))
    skipped = _strings(migration.get("skipped"))
    workflow_checks = _booleans(workflow.get("checks"))
    observations = _mapping(workflow.get("db_observations"))
    consumers = _mapping(workflow.get("consumers"))
    residue = _integers(workflow.get("cleanup_residue"))
    consumer_checks = {
        service_id: _consumer_passed(consumers.get(service_id))
        for service_id in EXPECTED_CONSUMERS
    }
    checks = {
        "migration_planned": REQUIRED_MIGRATION in planned,
        "migration_applied_or_current": REQUIRED_MIGRATION in {*applied, *skipped},
        "migration_inventory_current": (
            len(planned) == EXPECTED_MIGRATION_COUNT
            and observations.get("migration_ledger_count")
            == EXPECTED_MIGRATION_COUNT
            and observations.get("required_migration_count") == 1
        ),
        "actual_test_database": workflow.get("database") == EXPECTED_DATABASE,
        "expected_test_role": workflow.get("role") == EXPECTED_ROLE,
        "runtime_postgres": workflow.get("runtime_mode") == "postgres",
        "workflow_checks_complete": bool(workflow_checks)
        and all(workflow_checks.values()),
        "all_consumer_loopbacks_passed": all(consumer_checks.values()),
        "consumer_inventory_exact": set(consumers) == set(EXPECTED_CONSUMERS),
        "lifecycle_rows_persisted": (
            observations.get("principal_count") == 1
            and observations.get("credential_count") == 1
            and observations.get("signing_key_count") == 1
        ),
        "private_and_raw_material_absent": (
            observations.get("private_jwk_member_count") == 0
            and observations.get("private_reference_count") == 1
            and observations.get("raw_token_match_count") == 0
            and observations.get("raw_secret_match_count") == 0
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
            None
            if status == "PASS"
            else "platform_signed_token_postgres_smoke_failed"
        ),
        "database_readiness": (
            "ACTUAL_TEST_DATABASE_PLATFORM_TOKEN_VERIFIED"
            if status == "PASS"
            else "BLOCKED"
        ),
        "checks": checks,
        "consumer_checks": consumer_checks,
        "failed_checks": failed_checks,
        "summary": {
            "migration_count": len(planned),
            "consumer_count": len(consumers),
            "passed_consumer_count": sum(consumer_checks.values()),
            "issued_token_count": int(
                observations.get("issued_token_count") or 0
            ),
            "cleanup_residue_count": sum(residue.values()),
        },
        "workflow": dict(workflow),
    }


def _consumer_passed(value: object) -> bool:
    item = _mapping(value)
    return (
        item.get("claim_status") == "VALID"
        and item.get("token_kind") == "SIGNED"
        and item.get("rollout_profile") == "SIGNED_ONLY"
        and item.get("mock_rejected") is True
        and item.get("accepted_signed_count") == 2
        and item.get("rejected_count") == 1
    )


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(str(item) for item in value)


def _booleans(value: object) -> dict[str, bool]:
    return {str(key): item is True for key, item in _mapping(value).items()}


def _integers(value: object) -> dict[str, int]:
    result: dict[str, int] = {}
    for key, item in _mapping(value).items():
        if isinstance(item, bool):
            continue
        try:
            result[str(key)] = int(item)
        except (TypeError, ValueError):
            continue
    return result
