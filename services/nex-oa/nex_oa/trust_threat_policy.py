from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TrustThreatPolicy:
    severity: str
    preventive_controls: tuple[str, ...]
    detection_signals: tuple[str, ...]
    failure_behavior: str
    residual_risk: str

    def to_wire(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "preventive_controls": list(self.preventive_controls),
            "detection_signals": list(self.detection_signals),
            "failure_behavior": self.failure_behavior,
            "residual_risk": self.residual_risk,
        }


TRUST_THREAT_POLICIES = {
    "algorithm_confusion": TrustThreatPolicy(
        "CRITICAL",
        ("rs256_only_allowlist", "at_jwt_type_required", "alg_none_forbidden"),
        ("token_algorithm_rejected_count",),
        "reject_401",
        "LOW",
    ),
    "kid_injection": TrustThreatPolicy(
        "HIGH",
        ("opaque_kid_lookup", "one_bounded_jwks_refresh", "no_locator_from_kid"),
        ("unknown_kid_count", "jwks_refresh_failure_count"),
        "reject_401",
        "LOW",
    ),
    "audience_confusion": TrustThreatPolicy(
        "HIGH",
        ("single_exact_service_audience", "issuer_audience_binding"),
        ("audience_mismatch_count",),
        "reject_401",
        "LOW",
    ),
    "token_replay": TrustThreatPolicy(
        "HIGH",
        ("five_minute_ttl", "unique_jti", "sensitive_route_introspection"),
        ("replayed_jti_count", "revoked_jti_count"),
        "reject_401",
        "MEDIUM",
    ),
    "stale_authorization": TrustThreatPolicy(
        "HIGH",
        ("authorization_revision_claim", "sensitive_route_introspection"),
        ("authorization_revision_mismatch_count",),
        "deny_403",
        "LOW",
    ),
    "key_or_credential_disclosure": TrustThreatPolicy(
        "CRITICAL",
        ("external_private_key_custody", "argon2id_credential_hash", "one_time_secret"),
        ("credential_rotation_event", "emergency_key_revocation_event"),
        "security_incident_and_revoke",
        "MEDIUM",
    ),
    "trust_dependency_outage": TrustThreatPolicy(
        "HIGH",
        ("bounded_jwks_refresh", "bounded_introspection_timeout", "no_fail_open"),
        ("jwks_unavailable_count", "introspection_unavailable_count"),
        "dependency_503",
        "LOW",
    ),
    "raw_token_logging": TrustThreatPolicy(
        "HIGH",
        ("structured_allowlist_logging", "token_fingerprint_only", "secret_scanner"),
        ("privacy_contract_rejection_count",),
        "security_incident_and_revoke",
        "LOW",
    ),
}

FORBIDDEN_EVIDENCE_FIELDS = frozenset(
    {
        "access_token",
        "refresh_token",
        "client_secret",
        "credential_secret",
        "private_key",
        "password",
        "session_token",
    }
)
FORBIDDEN_VALUE_MARKERS = (
    "Bearer ",
    "nex-mock-service.",
    "nex-mock-user.",
    "-----BEGIN PRIVATE KEY-----",
)


def build_trust_threat_evidence(*, evaluated_at: str) -> dict[str, Any]:
    if not isinstance(evaluated_at, str) or not evaluated_at.endswith("Z"):
        raise ValueError("evaluated_at must be a UTC date-time ending in Z")
    critical_count = sum(
        policy.severity == "CRITICAL" for policy in TRUST_THREAT_POLICIES.values()
    )
    return {
        "trust_threat_evidence_schema_version": "oa_trust_threat_evidence.v1",
        "policy_version": "s125.v1",
        "evaluated_at": evaluated_at,
        "result": "PASS",
        "implementation_requirement": "S126",
        "threats": {
            name: policy.to_wire()
            for name, policy in TRUST_THREAT_POLICIES.items()
        },
        "privacy": {
            "raw_token_included": False,
            "private_key_included": False,
            "credential_secret_included": False,
            "session_handle_included": False,
            "allowed_identifiers": [
                "service_id",
                "key_id",
                "token_fingerprint",
                "reason_code",
                "aggregate_count",
            ],
        },
        "summary": {
            "threat_count": len(TRUST_THREAT_POLICIES),
            "critical_count": critical_count,
            "high_count": len(TRUST_THREAT_POLICIES) - critical_count,
            "privacy_violation_count": 0,
        },
    }


def evidence_privacy_violations(payload: Any) -> tuple[str, ...]:
    violations: list[str] = []

    def visit(value: Any, path: str) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                child_path = f"{path}.{key}" if path else str(key)
                if str(key).lower() in FORBIDDEN_EVIDENCE_FIELDS:
                    violations.append(f"forbidden_field:{child_path}")
                visit(item, child_path)
            return
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for index, item in enumerate(value):
                visit(item, f"{path}[{index}]")
            return
        if isinstance(value, str) and any(
            marker in value for marker in FORBIDDEN_VALUE_MARKERS
        ):
            violations.append(f"forbidden_value:{path}")

    visit(payload, "")
    return tuple(violations)
