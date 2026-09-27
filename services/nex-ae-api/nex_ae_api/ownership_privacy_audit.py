from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_VERSION = "ae_auth_ownership_privacy_audit.v1"


@dataclass(frozen=True)
class BoundarySurface:
    surface_id: str
    path: str
    token: str
    status: str
    risk: str
    authority: str
    privacy_posture: str


BOUNDARY_SURFACES = (
    BoundarySurface(
        "auth_session_redaction",
        "services/nex-ae-api/nex_ae_api/auth_sessions.py",
        '"password_included": False',
        "HARDENED",
        "LOW",
        "oa_session_claim",
        "password_and_raw_token_excluded",
    ),
    BoundarySurface(
        "facade_route_auth",
        "services/nex-ae-api/nex_ae_api/route_auth.py",
        "class AeFacadeRouteAuthContext",
        "HARDENED",
        "LOW",
        "service_claim_or_browser_user_claim",
        "raw_token_excluded",
    ),
    BoundarySurface(
        "upload_routes",
        "services/nex-ae-api/nex_ae_api/uploads.py",
        "_browser_owner_scoped_payload(",
        "HARDENED",
        "LOW",
        "browser_claim_for_browser_service_payload_for_service",
        "source_bytes_not_persisted_by_ae",
    ),
    BoundarySurface(
        "document_library_routes",
        "services/nex-ae-api/nex_ae_api/documents.py",
        "visible_upload_handoffs(",
        "HARDENED",
        "LOW",
        "browser_claim_visibility_filter",
        "not_found_and_not_authorized_collapsed",
    ),
    BoundarySurface(
        "retrieval_routes",
        "services/nex-ae-api/nex_ae_api/retrieval.py",
        "browser_actor_scoped_retrieval_payload(",
        "HARDENED",
        "LOW",
        "browser_claim_owner_scope",
        "cross_owner_not_found",
    ),
    BoundarySurface(
        "web_session_route_guard",
        "apps/nex-ae-web/src/sessionRouteGuard.js",
        "ownerScopeFromSessionState",
        "HARDENED",
        "LOW",
        "authenticated_session_state",
        "owner_scope_derived_not_user_editable",
    ),
    BoundarySurface(
        "cx_owner_header_propagation",
        "services/nex-ae-api/nex_ae_api/cx_owner_context.py",
        "def cx_owner_headers",
        "HARDENED",
        "LOW",
        "canonical_tenant_and_subject_headers",
        "no_provider_secret_exposure",
    ),
    BoundarySurface(
        "workspace_routes",
        "services/nex-ae-api/nex_ae_api/workspace.py",
        "authorize_ae_facade_route_request",
        "HARDENED",
        "LOW",
        "browser_claim_for_browser_service_payload_for_service",
        "cross_owner_not_found",
    ),
    BoundarySurface(
        "chat_routes",
        "services/nex-ae-api/nex_ae_api/chat.py",
        "def _authorize_ae_request",
        "REFACTOR_REQUIRED",
        "HIGH",
        "service_claim_only_payload_owner",
        "browser_claim_owner_not_enforced",
    ),
    BoundarySurface(
        "artifact_file_delivery_routes",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "def _authorize_ae_request",
        "REFACTOR_REQUIRED",
        "HIGH",
        "service_claim_only_artifact_id_lookup",
        "browser_claim_permission_recheck_missing",
    ),
)


def build_ae_auth_ownership_privacy_audit(
    root: Path = ROOT,
    *,
    surfaces: Sequence[BoundarySurface] = BOUNDARY_SURFACES,
) -> dict[str, Any]:
    inspected = [_inspect_surface(root, surface) for surface in surfaces]
    evidence_issues = [
        {
            "category": "boundary_evidence_missing",
            "surface_id": item["surface_id"],
            "path": item["path"],
        }
        for item in inspected
        if not item["evidence_present"]
    ]
    refactor_surfaces = [
        item for item in inspected if item["status"] == "REFACTOR_REQUIRED"
    ]
    high_risk = [item for item in refactor_surfaces if item["risk"] == "HIGH"]
    checks = {
        "surface_inventory_complete": len(inspected) == 10,
        "boundary_evidence_present": not evidence_issues,
        "authority_explicit": all(item["authority"] for item in inspected),
        "privacy_posture_explicit": all(item["privacy_posture"] for item in inspected),
        "high_risk_gaps_classified": len(high_risk) == 2,
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1005",
        "requirement": "S101",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "ae_auth_ownership_privacy_audit_failed",
        "readiness": "GAPS_CONFIRMED" if passed else "BLOCKED",
        "decision": {
            "browser_owner_authority": "validated_user_claim",
            "service_owner_authority": "validated_service_claim_plus_explicit_scope",
            "cross_owner_behavior": "not_found",
            "credentials_and_raw_tokens_in_outputs": False,
            "refactor_before_feature": True,
            "new_table_required": False,
            "next_slice": "1006",
        },
        "summary": {
            "surface_count": len(inspected),
            "hardened_count": sum(item["status"] == "HARDENED" for item in inspected),
            "refactor_count": len(refactor_surfaces),
            "high_risk_count": len(high_risk),
            "evidence_issue_count": len(evidence_issues),
        },
        "checks": checks,
        "issues": evidence_issues,
        "surfaces": inspected,
    }


def _inspect_surface(root: Path, surface: BoundarySurface) -> dict[str, Any]:
    path = root / surface.path
    present = path.is_file()
    if present:
        present = surface.token in path.read_text(encoding="utf-8")
    return {
        "surface_id": surface.surface_id,
        "path": surface.path,
        "status": surface.status,
        "risk": surface.risk,
        "authority": surface.authority,
        "privacy_posture": surface.privacy_posture,
        "evidence_present": present,
    }
