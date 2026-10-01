from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[3]
REQUIRED_REQUIREMENTS = tuple(f"OA-FR-{number:03d}" for number in range(1, 6))
REQUIRED_LAYERS = ("requirement", "implementation", "test", "operations")


@dataclass(frozen=True)
class EvidenceRef:
    layer: str
    relative_path: str
    token: str | None = None


@dataclass(frozen=True)
class CapabilitySpec:
    requirement_id: str
    capability: str
    implementation_status: str
    gap: str | None
    evidence: tuple[EvidenceRef, ...]


CAPABILITY_SPECS = (
    CapabilitySpec(
        "OA-FR-001",
        "bootstrap employee identity and login flow",
        "IMPLEMENTED",
        None,
        (
            EvidenceRef(
                "requirement",
                "docs/30_service_specific_requirement_partition.md",
                "OA-FR-001",
            ),
            EvidenceRef(
                "implementation",
                "services/nex-oa/nex_oa/user_login.py",
                "class OaUserLoginService",
            ),
            EvidenceRef(
                "implementation",
                "services/nex-oa/nex_oa/credentials.py",
                "class SqlAlchemyOaCredentialRegistry",
            ),
            EvidenceRef(
                "test",
                "tests/test_nex_oa_user_login.py",
                "test_user_login_verifies_password_and_issues_browser_session",
            ),
            EvidenceRef(
                "operations",
                "services/nex-oa/README.md",
                "POST /internal/v1/auth/user-login",
            ),
        ),
    ),
    CapabilitySpec(
        "OA-FR-002",
        "user sessions and service credentials",
        "PARTIAL",
        "user sessions are durable but service-token issuance remains unsigned mock runtime behavior",
        (
            EvidenceRef(
                "requirement",
                "docs/30_service_specific_requirement_partition.md",
                "OA-FR-002",
            ),
            EvidenceRef(
                "implementation",
                "services/nex-oa/nex_oa/sessions.py",
                "def issue_session",
            ),
            EvidenceRef(
                "implementation",
                "services/_shared/nex_runtime/auth.py",
                "def issue_mock_service_token",
            ),
            EvidenceRef(
                "test",
                "tests/test_nex_oa_sessions.py",
                "test_session_issue_requires_active_membership_and_granted_scopes",
            ),
            EvidenceRef(
                "operations",
                "services/nex-oa/README.md",
                "POST /api/v1/auth/service-token",
            ),
        ),
    ),
    CapabilitySpec(
        "OA-FR-003",
        "user and service credential validation",
        "PARTIAL",
        "opaque user-session introspection exists but production service-token introspection or JWKS does not",
        (
            EvidenceRef(
                "requirement",
                "docs/30_service_specific_requirement_partition.md",
                "OA-FR-003",
            ),
            EvidenceRef(
                "implementation",
                "services/nex-oa/nex_oa/sessions.py",
                "def introspect_session",
            ),
            EvidenceRef(
                "implementation",
                "services/_shared/nex_runtime/auth.py",
                "def validate_mock_service_token",
            ),
            EvidenceRef(
                "test",
                "tests/test_nex_oa_sessions.py",
                "test_session_introspection_reports_active_inactive_and_hides_credentials",
            ),
            EvidenceRef(
                "operations",
                "services/nex-oa/README.md",
                "POST /internal/v1/auth/user-sessions/introspect",
            ),
        ),
    ),
    CapabilitySpec(
        "OA-FR-004",
        "user role scope and service-principal claim references",
        "PARTIAL",
        "user roles/scopes and service identity exist but group claim references are absent",
        (
            EvidenceRef(
                "requirement",
                "docs/30_service_specific_requirement_partition.md",
                "OA-FR-004",
            ),
            EvidenceRef(
                "implementation",
                "services/_shared/nex_runtime/auth.py",
                "class UserClaims",
            ),
            EvidenceRef(
                "implementation",
                "services/_shared/nex_runtime/auth.py",
                "class ServiceClaims",
            ),
            EvidenceRef(
                "test",
                "tests/test_nex_oa_sessions.py",
                '"roles": ["employee", "analyst"]',
            ),
            EvidenceRef(
                "operations",
                "services/nex-oa/README.md",
                "User claims carry tenant, user, roles, scopes, audience",
            ),
        ),
    ),
    CapabilitySpec(
        "OA-FR-005",
        "privacy-safe authentication audit events",
        "PARTIAL",
        "a durable redacted event substrate exists but login/session-specific audit emission is not wired",
        (
            EvidenceRef(
                "requirement",
                "docs/30_service_specific_requirement_partition.md",
                "OA-FR-005",
            ),
            EvidenceRef(
                "implementation",
                "services/_shared/nex_runtime/persistence.py",
                "operational_event_store: OperationalEventStore",
            ),
            EvidenceRef(
                "implementation",
                "database/nex-oa/migrations/0085_service_operational_events_foundation.sql",
                "CREATE TABLE IF NOT EXISTS service_operational_events",
            ),
            EvidenceRef(
                "test",
                "tests/test_nex_runtime_operational_events.py",
                "test_build_operational_event_redacts_sensitive_details_and_normalizes_severity",
            ),
            EvidenceRef(
                "operations",
                "services/nex-oa/README.md",
                "and login audit",
            ),
        ),
    ),
)


def build_oa_capability_traceability_inventory(
    root: Path = ROOT,
    *,
    specs: Iterable[CapabilitySpec] = CAPABILITY_SPECS,
) -> dict[str, Any]:
    selected = tuple(specs)
    capabilities: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for spec in selected:
        evidence = [_inspect_evidence(root, ref) for ref in spec.evidence]
        layers = {item["layer"] for item in evidence if item["present"]}
        missing_layers = sorted(set(REQUIRED_LAYERS) - layers)
        missing_evidence = [item for item in evidence if not item["present"]]
        traceable = not missing_layers and not missing_evidence
        capabilities.append(
            {
                "requirement_id": spec.requirement_id,
                "capability": spec.capability,
                "implementation_status": spec.implementation_status,
                "gap": spec.gap,
                "traceable": traceable,
                "missing_layers": missing_layers,
                "evidence": evidence,
            }
        )
        issues.extend(
            {
                "category": "evidence_missing",
                "requirement_id": spec.requirement_id,
                "path": item["path"],
                "layer": item["layer"],
            }
            for item in missing_evidence
        )
        issues.extend(
            {
                "category": "layer_missing",
                "requirement_id": spec.requirement_id,
                "layer": layer,
            }
            for layer in missing_layers
        )

    requirement_ids = [item.requirement_id for item in selected]
    checks = {
        "requirement_set_complete": tuple(requirement_ids) == REQUIRED_REQUIREMENTS,
        "requirement_ids_unique": len(requirement_ids) == len(set(requirement_ids)),
        "all_capabilities_traceable": all(item["traceable"] for item in capabilities),
        "partial_capabilities_have_explicit_gaps": all(
            spec.implementation_status != "PARTIAL" or bool(spec.gap)
            for spec in selected
        ),
    }
    status = "PASS" if all(checks.values()) and not issues else "FAIL"
    return {
        "inventory_schema_version": "oa_capability_traceability_inventory.v1",
        "slice": "1203",
        "requirement": "S121",
        "status": status,
        "failure_code": None if status == "PASS" else "oa_traceability_inventory_failed",
        "checks": checks,
        "summary": {
            "requirement_count": len(capabilities),
            "traceable_count": sum(item["traceable"] for item in capabilities),
            "implemented_count": sum(
                item["implementation_status"] == "IMPLEMENTED"
                for item in capabilities
            ),
            "partial_count": sum(
                item["implementation_status"] == "PARTIAL"
                for item in capabilities
            ),
            "evidence_count": sum(len(item["evidence"]) for item in capabilities),
        },
        "decision": {
            "traceability_is_not_acceptance": True,
            "partial_requirements_are_s122_inputs": True,
            "new_table_required": False,
        },
        "capabilities": capabilities,
        "issues": issues,
    }


def _inspect_evidence(root: Path, ref: EvidenceRef) -> dict[str, Any]:
    path = root / ref.relative_path
    text = path.read_text(encoding="utf-8") if path.is_file() and ref.token else ""
    present = path.is_file() and (ref.token is None or ref.token in text)
    return {
        "layer": ref.layer,
        "path": ref.relative_path,
        "token_checked": ref.token is not None,
        "present": present,
    }
