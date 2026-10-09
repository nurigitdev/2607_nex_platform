from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
import re
from typing import Any


SECURITY_ACCEPTANCE_SCHEMA_VERSION = "preproduction_security_acceptance.v1"
DECISIONS = frozenset({"ALLOW", "DENY", "PASS", "FAIL"})
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
SAFE_REASON = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
FORBIDDEN_KEY_PARTS = (
    "authorization",
    "cookie",
    "database_url",
    "document",
    "endpoint",
    "generated_text",
    "object_key",
    "password",
    "physical_path",
    "private_payload",
    "prompt",
    "secret",
    "source_text",
    "token",
    "vector",
)


class SecurityAcceptanceError(ValueError):
    pass


@dataclass(frozen=True)
class SecurityProbeSpec:
    probe_id: str
    category: str
    expected_decision: str


@dataclass(frozen=True)
class SecurityProbeResult:
    probe_id: str
    category: str
    observed_decision: str
    reason_code: str
    isolation_violation_count: int = 0


REQUIRED_PROBES = (
    SecurityProbeSpec("security:cross-tenant-read", "tenant_isolation", "DENY"),
    SecurityProbeSpec("security:cross-owner-read", "owner_isolation", "DENY"),
    SecurityProbeSpec("security:token-audience", "service_token_audience", "DENY"),
    SecurityProbeSpec("security:token-scope", "service_token_scope", "DENY"),
    SecurityProbeSpec("security:token-expired", "expired_credential", "DENY"),
    SecurityProbeSpec("security:token-revoked", "revoked_credential", "DENY"),
    SecurityProbeSpec("security:object-traversal", "object_key_traversal", "DENY"),
    SecurityProbeSpec("security:unsafe-redirect", "unsafe_redirect", "DENY"),
    SecurityProbeSpec("security:forwarded-header", "untrusted_forwarded_header", "DENY"),
    SecurityProbeSpec("security:evidence-redaction", "evidence_privacy", "PASS"),
    SecurityProbeSpec("security:signal-redaction", "log_trace_alert_privacy", "PASS"),
    SecurityProbeSpec("security:post-recovery-authz", "post_recovery_authorization", "DENY"),
)


def build_passing_security_probe_results() -> tuple[SecurityProbeResult, ...]:
    return tuple(
        SecurityProbeResult(
            probe_id=spec.probe_id,
            category=spec.category,
            observed_decision=spec.expected_decision,
            reason_code=(
                "privacy_clean" if spec.expected_decision == "PASS" else "access_denied"
            ),
        )
        for spec in REQUIRED_PROBES
    )


def evaluate_security_privacy_acceptance(
    results: Sequence[SecurityProbeResult],
    *,
    evidence_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    if not results:
        raise SecurityAcceptanceError("security probe results are required")
    normalized = [_validate_result(item) for item in results]
    result_ids = [item.probe_id for item in normalized]
    expected = {item.probe_id: item for item in REQUIRED_PROBES}
    if len(result_ids) != len(set(result_ids)) or set(result_ids) != set(expected):
        raise SecurityAcceptanceError("security probe inventory must be exact and unique")
    if not isinstance(evidence_metadata, Mapping):
        raise SecurityAcceptanceError("evidence metadata must be a mapping")
    privacy_violations = sorted(set(_privacy_violations(evidence_metadata)))
    mismatches = sorted(
        item.probe_id
        for item in normalized
        if item.category != expected[item.probe_id].category
        or item.observed_decision != expected[item.probe_id].expected_decision
    )
    by_category = {item.category: item for item in normalized}
    checks = {
        "all_required_probes_match": not mismatches,
        "tenant_owner_isolation_enforced": all(
            by_category[name].observed_decision == "DENY"
            for name in ("tenant_isolation", "owner_isolation")
        ),
        "service_token_boundary_enforced": all(
            by_category[name].observed_decision == "DENY"
            for name in ("service_token_audience", "service_token_scope")
        ),
        "credential_lifecycle_enforced": all(
            by_category[name].observed_decision == "DENY"
            for name in ("expired_credential", "revoked_credential")
        ),
        "storage_boundary_enforced": by_category[
            "object_key_traversal"
        ].observed_decision
        == "DENY",
        "request_boundary_enforced": all(
            by_category[name].observed_decision == "DENY"
            for name in ("unsafe_redirect", "untrusted_forwarded_header")
        ),
        "post_recovery_authorization_enforced": by_category[
            "post_recovery_authorization"
        ].observed_decision
        == "DENY",
        "evidence_and_signal_privacy_passed": all(
            by_category[name].observed_decision == "PASS"
            for name in ("evidence_privacy", "log_trace_alert_privacy")
        ),
        "zero_isolation_violations": sum(
            item.isolation_violation_count for item in normalized
        )
        == 0,
        "metadata_privacy_clean": not privacy_violations,
    }
    passed = all(checks.values())
    return {
        "acceptance_schema_version": SECURITY_ACCEPTANCE_SCHEMA_VERSION,
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "failed_checks": sorted(name for name, value in checks.items() if not value),
        "mismatched_probe_ids": mismatches,
        "privacy_violation_paths": privacy_violations,
        "probes": [asdict(item) for item in normalized],
        "summary": {
            "required_probe_count": len(REQUIRED_PROBES),
            "observed_probe_count": len(normalized),
            "matched_probe_count": len(normalized) - len(mismatches),
            "denial_probe_count": sum(
                item.expected_decision == "DENY" for item in REQUIRED_PROBES
            ),
            "privacy_probe_count": sum(
                item.expected_decision == "PASS" for item in REQUIRED_PROBES
            ),
            "isolation_violation_count": sum(
                item.isolation_violation_count for item in normalized
            ),
            "privacy_violation_count": len(privacy_violations),
        },
    }


def _validate_result(result: SecurityProbeResult) -> SecurityProbeResult:
    if not isinstance(result, SecurityProbeResult):
        raise SecurityAcceptanceError("security probe result is invalid")
    _safe_id(result.probe_id, "probe_id")
    _safe_id(result.category, "category")
    if result.observed_decision not in DECISIONS:
        raise SecurityAcceptanceError("security probe decision is invalid")
    if SAFE_REASON.fullmatch(result.reason_code) is None:
        raise SecurityAcceptanceError("security probe reason code is invalid")
    if (
        not isinstance(result.isolation_violation_count, int)
        or isinstance(result.isolation_violation_count, bool)
        or result.isolation_violation_count < 0
    ):
        raise SecurityAcceptanceError("isolation violation count is invalid")
    return result


def _safe_id(value: object, field: str) -> str:
    if not isinstance(value, str) or SAFE_ID.fullmatch(value) is None:
        raise SecurityAcceptanceError(f"{field} is invalid")
    return value


def _privacy_violations(value: object, *, path: str = "$") -> list[str]:
    violations: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            name = str(key)
            child = f"{path}.{name}"
            if any(part in name.lower() for part in FORBIDDEN_KEY_PARTS):
                violations.append(child)
            violations.extend(_privacy_violations(item, path=child))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, item in enumerate(value):
            violations.extend(_privacy_violations(item, path=f"{path}[{index}]"))
    return violations

