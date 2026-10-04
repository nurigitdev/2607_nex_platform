from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any


TRUST_EVIDENCE_SCHEMA_VERSION = "platform_oa_backed_trust_evidence.v1"
REQUIRED_HOPS = (
    "oa_user_login",
    "nex-ae-api",
    "nex-cx",
    "nex-mo",
    "nex-ag",
)
REQUIRED_DENIALS = (
    "wrong_audience",
    "missing_scope",
    "revoked_session",
    "revoked_service_token",
)
FORBIDDEN_KEY_PARTS = (
    "access_token",
    "authorization",
    "client_secret",
    "cookie",
    "database_url",
    "password",
    "private_key",
    "raw_token",
    "session_id",
)


def evaluate_platform_trust_evidence(payload: Mapping[str, Any]) -> dict[str, Any]:
    privacy_violations = sorted(set(_privacy_violations(payload)))
    hops = _indexed_items(payload.get("hops"), key="hop_id")
    denials = _indexed_items(payload.get("denials"), key="scenario")
    restart = _mapping(payload.get("restart"))
    databases = _mapping(payload.get("databases"))

    hop_checks = {
        hop_id: _hop_passed(hop_id, hops.get(hop_id)) for hop_id in REQUIRED_HOPS
    }
    denial_checks = {
        scenario: _denial_passed(denials.get(scenario))
        for scenario in REQUIRED_DENIALS
    }
    checks = {
        "hop_inventory_exact": set(hops) == set(REQUIRED_HOPS),
        "all_trust_hops_passed": all(hop_checks.values()),
        "denial_inventory_exact": set(denials) == set(REQUIRED_DENIALS),
        "all_denials_fail_closed": all(denial_checks.values()),
        "restart_generation_exact": restart.get("generation_count") == 2,
        "restart_state_restored": all(
            restart.get(name) is True
            for name in (
                "user_session_restored",
                "signing_key_restored",
                "revoked_service_token_denied",
            )
        ),
        "five_service_databases_proven": databases.get("service_count") == 5,
        "database_cleanup_zero": databases.get("cleanup_residue_count") == 0,
        "temporary_key_cleanup_zero": databases.get("temporary_key_residue_count") == 0,
        "privacy_safe": not privacy_violations,
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    return {
        "evidence_schema_version": TRUST_EVIDENCE_SCHEMA_VERSION,
        "status": "PASS" if not failed_checks else "FAIL",
        "failure_code": None if not failed_checks else "platform_oa_backed_trust_evidence_failed",
        "checks": checks,
        "hop_checks": hop_checks,
        "denial_checks": denial_checks,
        "failed_checks": failed_checks,
        "privacy_violations": privacy_violations,
        "summary": {
            "hop_count": len(hops),
            "passed_hop_count": sum(hop_checks.values()),
            "denial_count": len(denials),
            "passed_denial_count": sum(denial_checks.values()),
            "restart_generation_count": int(restart.get("generation_count") or 0),
            "database_service_count": int(databases.get("service_count") or 0),
            "cleanup_residue_count": int(databases.get("cleanup_residue_count") or 0),
            "privacy_violation_count": len(privacy_violations),
        },
        "hops": [_safe_hop(hops[name]) for name in REQUIRED_HOPS if name in hops],
        "denials": [
            _safe_denial(denials[name]) for name in REQUIRED_DENIALS if name in denials
        ],
        "restart": _safe_restart(restart),
        "databases": _safe_databases(databases),
    }


def _hop_passed(hop_id: str, value: object) -> bool:
    hop = _mapping(value)
    expected_kind = "OPAQUE_USER_SESSION" if hop_id == "nex-ae-api" else "SIGNED_SERVICE"
    signed_checks = (
        hop.get("jwks_verified") is True
        and hop.get("scope_enforced") is True
        and hop.get("introspection_status") == "ACTIVE"
    ) if expected_kind == "SIGNED_SERVICE" else hop.get("owner_claim_authoritative") is True
    return (
        hop.get("status_code") == 200
        and hop.get("auth_kind") == expected_kind
        and hop.get("request_id_propagated") is True
        and hop.get("trace_id_propagated") is True
        and signed_checks
    )


def _denial_passed(value: object) -> bool:
    denial = _mapping(value)
    return (
        denial.get("status_code") in {401, 403}
        and denial.get("failed_closed") is True
        and isinstance(denial.get("error_code"), str)
        and bool(str(denial.get("error_code")).strip())
    )


def _indexed_items(value: object, *, key: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for item in value:
        record = _mapping(item)
        identity = record.get(key)
        if isinstance(identity, str) and identity and identity not in result:
            result[identity] = record
    return result


def _privacy_violations(value: object, *, path: str = "$") -> list[str]:
    violations: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            name = str(key)
            child = f"{path}.{name}"
            normalized = name.lower()
            if any(part in normalized for part in FORBIDDEN_KEY_PARTS):
                violations.append(child)
            violations.extend(_privacy_violations(item, path=child))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, item in enumerate(value):
            violations.extend(_privacy_violations(item, path=f"{path}[{index}]"))
    return violations


def _safe_hop(value: Mapping[str, Any]) -> dict[str, Any]:
    return _safe_projection(
        value,
        (
            "hop_id",
            "service_id",
            "status_code",
            "auth_kind",
            "jwks_verified",
            "scope_enforced",
            "introspection_status",
            "owner_claim_authoritative",
            "request_id_propagated",
            "trace_id_propagated",
        ),
    )


def _safe_denial(value: Mapping[str, Any]) -> dict[str, Any]:
    return _safe_projection(
        value, ("scenario", "service_id", "status_code", "error_code", "failed_closed")
    )


def _safe_restart(value: Mapping[str, Any]) -> dict[str, Any]:
    return _safe_projection(
        value,
        (
            "generation_count",
            "user_session_restored",
            "signing_key_restored",
            "revoked_service_token_denied",
        ),
    )


def _safe_databases(value: Mapping[str, Any]) -> dict[str, Any]:
    return _safe_projection(
        value,
        ("service_count", "migration_count", "cleanup_residue_count", "temporary_key_residue_count"),
    )


def _safe_projection(value: Mapping[str, Any], names: Sequence[str]) -> dict[str, Any]:
    return {name: deepcopy(value[name]) for name in names if name in value}


def _mapping(value: object) -> dict[str, Any]:
    return deepcopy(dict(value)) if isinstance(value, Mapping) else {}

