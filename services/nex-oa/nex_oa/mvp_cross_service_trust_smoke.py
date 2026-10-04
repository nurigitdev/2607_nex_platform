from __future__ import annotations

from collections.abc import Mapping
from typing import Any


EXPECTED_DATABASE = "nex_oa_test"
EXPECTED_ROLE = "nex_oa_user"
EXPECTED_MIGRATION_COUNT = 17
EXPECTED_CONSUMERS = ("nex-ae-api", "nex-cx", "nex-mo", "nex-ag")
EXPECTED_RESIDUE_KEYS = frozenset(
    {
        "credential_count",
        "principal_count",
        "revocation_count",
        "signing_key_count",
    }
)


def evaluate_oa_cross_service_trust_smoke(
    migration: Mapping[str, Any],
    workflow: Mapping[str, Any],
) -> dict[str, Any]:
    planned = tuple(str(item) for item in migration.get("planned", ()))
    checks_in = _booleans(workflow.get("checks"))
    observations = _mapping(workflow.get("db_observations"))
    consumers = _mapping(workflow.get("consumers"))
    consumer_checks = {
        service_id: _consumer_passed(consumers.get(service_id))
        for service_id in EXPECTED_CONSUMERS
    }
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
        "consumer_inventory_exact": set(consumers) == set(EXPECTED_CONSUMERS),
        "all_consumers_passed": all(consumer_checks.values()),
        "lifecycle_rows_persisted": (
            observations.get("principal_count") == 1
            and observations.get("credential_count") == 1
            and observations.get("signing_key_count") == 1
            and observations.get("revocation_count") == 4
            and observations.get("revocation_digest_count") == 4
        ),
        "private_and_raw_material_absent": (
            observations.get("private_jwk_member_count") == 0
            and observations.get("raw_token_match_count") == 0
            and observations.get("raw_secret_match_count") == 0
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
            None if passed else "oa_cross_service_trust_smoke_failed"
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
            "revoked_denial_count": sum(
                _mapping(item).get("revoked_denied") is True
                for item in consumers.values()
            ),
            "cleanup_residue_count": sum(residue.values()),
        },
        "workflow": dict(workflow),
    }


def _consumer_passed(value: object) -> bool:
    item = _mapping(value)
    return (
        item.get("status_code") == 200
        and item.get("claim_status") == "VALID"
        and item.get("token_kind") == "SIGNED"
        and item.get("introspection_status") == "ACTIVE"
        and item.get("rollout_profile") == "SIGNED_ONLY"
        and item.get("mock_rejected") is True
        and item.get("revoked_denied") is True
        and item.get("revoked_error_code") == "nex.token_introspection_inactive"
        and item.get("accepted_signed_count") == 1
        and item.get("introspected_count") == 1
        and item.get("rejected_count") == 2
    )


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _booleans(value: object) -> dict[str, bool]:
    return {
        str(name): item is True for name, item in _mapping(value).items()
    }
