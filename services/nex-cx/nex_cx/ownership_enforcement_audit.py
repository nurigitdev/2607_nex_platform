from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
CX_OWNERSHIP_ENFORCEMENT_AUDIT_SCHEMA_VERSION = (
    "cx_ownership_enforcement_audit.v1"
)


@dataclass(frozen=True)
class EnforcementSurface:
    surface_id: str
    source_path: str
    evidence_tokens: tuple[str, ...]
    current_status: str
    risk: str
    finding: str


ENFORCEMENT_SURFACES = (
    EnforcementSurface(
        "upload_intake",
        "services/nex-cx/nex_cx/ingestion.py",
        ("resolve_upload_ownership(", 'record["ownership_ref"]'),
        "CALLER_ASSERTED_OWNER_VALIDATED",
        "MEDIUM",
        "Canonical OA refs are validated, but remain caller asserted.",
    ),
    EnforcementSurface(
        "document_library",
        "services/nex-cx/nex_cx/document_library.py",
        ("list_active_content_objects(", '"owner_scoped": True'),
        "CALLER_ASSERTED_OWNER_FILTERED",
        "MEDIUM",
        "Repository filtering is owner scoped; auth does not bind the owner ref.",
    ),
    EnforcementSurface(
        "document_detail_and_source_materialization",
        "services/nex-cx/nex_cx/document_library.py",
        ("_content_object_matches_detail_scope(", '"not_found_and_not_authorized_collapsed": True'),
        "CALLER_ASSERTED_OWNER_FILTERED",
        "MEDIUM",
        "Owner filters and 404 collapse exist; principal binding is absent.",
    ),
    EnforcementSurface(
        "ingestion_job_and_extraction_reads",
        "services/nex-cx/nex_cx/ingestion.py",
        ('@app.get("/api/v1/jobs/{job_id}"', '@app.get("/api/v1/documents/{document_id}/extraction"'),
        "SERVICE_TOKEN_ONLY_ID_LOOKUP",
        "HIGH",
        "Job and extraction reads do not require an owner-scoped access context.",
    ),
    EnforcementSurface(
        "processing_control_and_reads",
        "services/nex-cx/nex_cx/processing.py",
        ('@app.post("/api/v1/documents/{document_id}/processing/run"', '@app.get("/api/v1/documents/{document_id}/processing"'),
        "SERVICE_TOKEN_ONLY_ID_LOOKUP",
        "HIGH",
        "Processing run, enqueue, and read routes authorize the service only.",
    ),
    EnforcementSurface(
        "retrieval_creation",
        "services/nex-cx/nex_cx/retrieval.py",
        ("def build_permission_snapshot(", "def document_ids_from_scope("),
        "DECLARED_PERMISSION_SNAPSHOT_ONLY",
        "HIGH",
        "The snapshot records requested scope but does not enforce repository ACLs.",
    ),
    EnforcementSurface(
        "retrieval_package_read",
        "services/nex-cx/nex_cx/retrieval.py",
        ('@app.get("/api/v1/retrieval/context/{retrieval_package_id}"', "store.get_retrieval_package(retrieval_package_id)"),
        "SERVICE_TOKEN_ONLY_ID_LOOKUP",
        "HIGH",
        "Persisted and memory package reads are not principal scoped.",
    ),
    EnforcementSurface(
        "generation_and_repair",
        "services/nex-cx/nex_cx/generation.py",
        ("def register_generation_routes(", "retrieval_package_id"),
        "SERVICE_TOKEN_ONLY_REFERENCE_LOOKUP",
        "HIGH",
        "Generation trusts referenced retrieval lineage without owner binding.",
    ),
)


def build_cx_ownership_enforcement_audit(
    root: Path = ROOT,
) -> dict[str, Any]:
    surfaces = []
    issues = []
    for spec in ENFORCEMENT_SURFACES:
        path = root / spec.source_path
        content = path.read_text(encoding="utf-8") if path.is_file() else ""
        evidence_present = path.is_file() and all(
            token in content for token in spec.evidence_tokens
        )
        surfaces.append(
            {
                "surface_id": spec.surface_id,
                "source_path": spec.source_path,
                "evidence_present": evidence_present,
                "current_status": spec.current_status,
                "risk": spec.risk,
                "finding": spec.finding,
            }
        )
        if not evidence_present:
            issues.append(
                {
                    "category": "ownership_audit_evidence_missing",
                    "surface_id": spec.surface_id,
                    "source_path": spec.source_path,
                }
            )

    high_risk = [item for item in surfaces if item["risk"] == "HIGH"]
    return {
        "audit_schema_version": CX_OWNERSHIP_ENFORCEMENT_AUDIT_SCHEMA_VERSION,
        "slice": "0905",
        "requirement": "S91",
        "status": "PASS" if not issues else "FAIL",
        "failure_code": (
            None if not issues else "cx_ownership_enforcement_audit_failed"
        ),
        "enforcement_readiness": "GAPS_CONFIRMED",
        "trust_boundary": {
            "current": "service_token_plus_caller_asserted_owner_or_resource_id",
            "target": "service_identity_plus_validated_cx_access_context",
            "external_user_auth_owner": "nex-oa",
            "resource_authorization_owner": "nex-cx",
        },
        "target_refactoring": {
            "name": "CxAccessContext",
            "required_fields": [
                "caller_service_id",
                "tenant_ref",
                "subject_ref",
                "request_id",
                "trace_id",
            ],
            "rules": [
                "derive once at the service boundary",
                "authorize repository reads and commands by tenant and subject",
                "persist owner refs on jobs, processing runs, and retrieval packages",
                "collapse not-found and not-authorized responses",
                "never trust actor_claims_ref as authorization proof",
            ],
            "implementation_requirement": "S92",
        },
        "summary": {
            "surface_count": len(surfaces),
            "evidence_gap_count": len(issues),
            "high_risk_gap_count": len(high_risk),
            "caller_asserted_filtered_count": sum(
                "CALLER_ASSERTED" in item["current_status"] for item in surfaces
            ),
            "service_only_count": sum(
                item["current_status"].startswith("SERVICE_TOKEN_ONLY")
                for item in surfaces
            ),
        },
        "surfaces": surfaces,
        "issues": issues,
        "next_slice": "0906",
    }
