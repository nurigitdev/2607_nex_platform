from __future__ import annotations

from pathlib import Path
from typing import Any

from nex_oa.mvp_acceptance import OA_MVP_REQUIREMENTS


OA_MVP_TRACEABILITY_SCHEMA_VERSION = "oa_mvp_traceability.v1"

_EVIDENCE = {
    "OA-FR-001": (
        "docs/slices/1221_s122_oa_identity_membership_lifecycle_closure.md",
        "docs/slices/1231_s123_oa_credential_session_security_closure.md",
        "docs/slices/1291_s129_federated_auth_ag_integration_closure.md",
        "tests/test_nex_oa_identity_lifecycle_service.py",
        "tests/test_nex_oa_credentials.py",
        "tests/test_oa_federated_login.py",
    ),
    "OA-FR-002": (
        "docs/slices/1231_s123_oa_credential_session_security_closure.md",
        "docs/slices/1261_s126_oa_service_principal_lifecycle_closure.md",
        "docs/slices/1271_s127_oa_signed_token_lifecycle_closure.md",
        "docs/slices/1281_s128_platform_signed_token_adoption_closure.md",
        "tests/test_nex_oa_signed_tokens.py",
        "tests/test_nex_runtime_service_token_admission.py",
    ),
    "OA-FR-003": (
        "docs/slices/1271_s127_oa_signed_token_lifecycle_closure.md",
        "docs/slices/1281_s128_platform_signed_token_adoption_closure.md",
        "tests/test_nex_oa_signed_token_api.py",
        "tests/test_nex_runtime_signed_token_verifier.py",
    ),
    "OA-FR-004": (
        "docs/slices/1241_s124_oa_group_role_authorization_closure.md",
        "docs/slices/1261_s126_oa_service_principal_lifecycle_closure.md",
        "docs/slices/1281_s128_platform_signed_token_adoption_closure.md",
        "docs/slices/1291_s129_federated_auth_ag_integration_closure.md",
        "tests/test_nex_oa_authorization_resolver.py",
        "tests/test_ag_federated_operator_authorization.py",
    ),
    "OA-FR-005": (
        "docs/slices/1231_s123_oa_credential_session_security_closure.md",
        "docs/slices/1293_oa_signed_token_failure_audit_hardening.md",
        "tests/test_oa_auth_events.py",
        "tests/test_oa_signed_token_failure_audit.py",
    ),
}


def build_oa_mvp_traceability_inventory(root: Path) -> dict[str, Any]:
    requirements = []
    for requirement_id in OA_MVP_REQUIREMENTS:
        paths = _EVIDENCE[requirement_id]
        evidence = [
            {"path": path, "present": (root / path).is_file()}
            for path in paths
        ]
        requirements.append(
            {
                "requirement_id": requirement_id,
                "status": (
                    "READY"
                    if all(item["present"] for item in evidence)
                    else "GAP"
                ),
                "evidence": evidence,
                "evidence_count": len(evidence),
                "missing_evidence_count": sum(
                    not item["present"] for item in evidence
                ),
            }
        )
    return {
        "traceability_schema_version": OA_MVP_TRACEABILITY_SCHEMA_VERSION,
        "requirements": requirements,
        "requirement_count": len(requirements),
        "ready_count": sum(
            item["status"] == "READY" for item in requirements
        ),
        "missing_evidence_count": sum(
            item["missing_evidence_count"] for item in requirements
        ),
        "next_live_slice": "1295",
    }
