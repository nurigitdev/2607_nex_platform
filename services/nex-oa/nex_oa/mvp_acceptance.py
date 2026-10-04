from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


OA_MVP_ACCEPTANCE_SCHEMA_VERSION = "oa_mvp_acceptance_policy.v1"
OA_MVP_REQUIREMENTS = (
    "OA-FR-001",
    "OA-FR-002",
    "OA-FR-003",
    "OA-FR-004",
    "OA-FR-005",
)


@dataclass(frozen=True)
class OaMvpRequirementGate:
    requirement_id: str
    priority: str
    acceptance_statement: str
    repository_evidence_required: bool
    actual_postgres_required: bool
    restart_required: bool
    cross_service_required: bool
    failure_evidence_required: bool

    def to_wire(self) -> dict[str, Any]:
        return asdict(self)


_GATES = (
    OaMvpRequirementGate(
        requirement_id="OA-FR-001",
        priority="MUST",
        acceptance_statement=(
            "local or federated identity can establish an OA-backed opaque "
            "user session and survive runtime reconstruction"
        ),
        repository_evidence_required=True,
        actual_postgres_required=True,
        restart_required=True,
        cross_service_required=False,
        failure_evidence_required=True,
    ),
    OaMvpRequirementGate(
        requirement_id="OA-FR-002",
        priority="MUST",
        acceptance_statement=(
            "OA issues and validates opaque browser sessions and short-lived "
            "RS256 service access tokens without production mock fallback"
        ),
        repository_evidence_required=True,
        actual_postgres_required=True,
        restart_required=True,
        cross_service_required=True,
        failure_evidence_required=True,
    ),
    OaMvpRequirementGate(
        requirement_id="OA-FR-003",
        priority="MUST",
        acceptance_statement=(
            "OA publishes bounded public JWKS and provides revocation-aware "
            "introspection for sensitive service operations"
        ),
        repository_evidence_required=True,
        actual_postgres_required=True,
        restart_required=True,
        cross_service_required=True,
        failure_evidence_required=True,
    ),
    OaMvpRequirementGate(
        requirement_id="OA-FR-004",
        priority="MUST",
        acceptance_statement=(
            "user, tenant, group, role, scope, and service-principal references "
            "are owner-scoped and usable without cross-service database reads"
        ),
        repository_evidence_required=True,
        actual_postgres_required=True,
        restart_required=True,
        cross_service_required=True,
        failure_evidence_required=False,
    ),
    OaMvpRequirementGate(
        requirement_id="OA-FR-005",
        priority="SHOULD",
        acceptance_statement=(
            "login, token-validation, and service-auth failures emit durable "
            "privacy-safe OA authentication events"
        ),
        repository_evidence_required=True,
        actual_postgres_required=True,
        restart_required=True,
        cross_service_required=True,
        failure_evidence_required=True,
    ),
)


def build_oa_mvp_acceptance_policy() -> dict[str, Any]:
    gates = [gate.to_wire() for gate in _GATES]
    return {
        "acceptance_schema_version": OA_MVP_ACCEPTANCE_SCHEMA_VERSION,
        "service_id": "nex-oa",
        "requirements": gates,
        "requirement_count": len(gates),
        "blocking_requirement_count": len(gates),
        "browser_access_profile": "OPAQUE_OA_BACKED_SESSION",
        "service_access_profile": "RS256_SIGNED_ONLY",
        "sensitive_route_validation": "LOCAL_SIGNATURE_PLUS_INTROSPECTION",
        "actual_database": "nex_oa_test",
        "actual_role": "nex_oa_user",
        "all_required_gates_must_pass": True,
        "skipped_required_gate_allowed": False,
        "raw_secret_or_token_evidence_allowed": False,
        "database_private_key_material_allowed": False,
        "remote_model_provider_required": False,
        "new_tables": (),
        "final_evidence": (
            "postgresql_identity_session_authorization_restart",
            "postgresql_signing_key_rotation_jwks_overlap_restart",
            "postgresql_revocation_introspection_restart",
            "ae_cx_mo_ag_signed_only_protected_calls",
            "full_regression_coverage_contract_gate",
        ),
    }


def evaluate_oa_mvp_acceptance_inputs(
    evidence: dict[str, bool],
) -> dict[str, Any]:
    expected = {
        "repository",
        "postgres_restart",
        "key_rotation",
        "revocation",
        "cross_service",
        "failure_audit",
        "contracts_privacy",
        "full_gate",
    }
    provided = set(evidence)
    missing = sorted(expected - provided)
    unexpected = sorted(provided - expected)
    failed = sorted(
        name for name in expected if evidence.get(name) is not True
    )
    passed = not missing and not unexpected and not failed
    return {
        "status": "ACCEPTED" if passed else "BLOCKED",
        "passed_gate_count": sum(evidence.get(name) is True for name in expected),
        "gate_count": len(expected),
        "missing_gates": missing,
        "unexpected_gates": unexpected,
        "failed_gates": failed,
    }
