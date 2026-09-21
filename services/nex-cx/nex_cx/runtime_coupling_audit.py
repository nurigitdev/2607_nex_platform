from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
CX_RUNTIME_COUPLING_AUDIT_SCHEMA_VERSION = "cx_runtime_coupling_audit.v1"


@dataclass(frozen=True)
class CouplingFinding:
    finding_id: str
    source_path: str
    token: str
    disposition: str
    risk: str
    rationale: str


COUPLING_FINDINGS = (
    CouplingFinding(
        "import_time_singleton_composition",
        "services/nex-cx/nex_cx/main.py",
        "DEFAULT_INGESTION_STORE.content_repository = CX_CONTENT_REPOSITORY",
        "REFACTOR_REQUIRED",
        "HIGH",
        "Import-time mutation makes runtime isolation and restart testing harder.",
    ),
    CouplingFinding(
        "monolithic_runtime_store",
        "services/nex-cx/nex_cx/ingestion.py",
        "class ContentIngestionStore",
        "REFACTOR_REQUIRED",
        "HIGH",
        "One object owns jobs, private payloads, projections, and write-through.",
    ),
    CouplingFinding(
        "concrete_store_route_dependencies",
        "services/nex-cx/nex_cx/retrieval.py",
        "store: ContentIngestionStore",
        "REFACTOR_REQUIRED",
        "HIGH",
        "Routes depend on the broad concrete store instead of capability ports.",
    ),
    CouplingFinding(
        "duplicated_service_authorization",
        "docs/slices/0906_cx_runtime_coupling_refactoring_checkpoint.md",
        "service authorization helpers",
        "REFACTOR_REQUIRED",
        "MEDIUM",
        "S91 recorded the authorization duplication that S92 must remove.",
    ),
    CouplingFinding(
        "global_generation_store",
        "services/nex-cx/nex_cx/generation.py",
        "DEFAULT_GENERATION_STORE = GenerationExecutionStore()",
        "REFACTOR_REQUIRED",
        "MEDIUM",
        "Generation state remains process-local and globally shared.",
    ),
    CouplingFinding(
        "memory_fallback_mode",
        "services/nex-cx/nex_cx/main.py",
        'else "memory"',
        "ACCEPTED_FOR_NOW",
        "LOW",
        "Deterministic memory mode remains useful for regression and mocks.",
    ),
    CouplingFinding(
        "content_repository_protocol",
        "services/nex-cx/nex_cx/repository.py",
        "class CxContentRepository(Protocol):",
        "GOOD_BOUNDARY",
        "LOW",
        "Metadata persistence already has a replaceable service-local port.",
    ),
    CouplingFinding(
        "provider_protocols",
        "services/nex-cx/nex_cx/generation.py",
        "class MoGenerationClient(Protocol):",
        "GOOD_BOUNDARY",
        "LOW",
        "Provider calls are mockable and kept behind protocol boundaries.",
    ),
)


def build_cx_runtime_coupling_audit(root: Path = ROOT) -> dict[str, Any]:
    findings = []
    issues = []
    for spec in COUPLING_FINDINGS:
        path = root / spec.source_path
        present = path.is_file() and spec.token in path.read_text(encoding="utf-8")
        findings.append(
            {
                "finding_id": spec.finding_id,
                "source_path": spec.source_path,
                "evidence_present": present,
                "disposition": spec.disposition,
                "risk": spec.risk,
                "rationale": spec.rationale,
            }
        )
        if not present:
            issues.append(
                {
                    "category": "runtime_coupling_evidence_missing",
                    "finding_id": spec.finding_id,
                    "source_path": spec.source_path,
                }
            )

    auth_helper_count = sum(
        "def _authorize_cx_request(" in path.read_text(encoding="utf-8")
        for path in (root / "services/nex-cx/nex_cx").glob("*.py")
        if path.name != "runtime_coupling_audit.py"
    ) if (root / "services/nex-cx/nex_cx").is_dir() else 0
    return {
        "audit_schema_version": CX_RUNTIME_COUPLING_AUDIT_SCHEMA_VERSION,
        "slice": "0906",
        "requirement": "S91",
        "status": "PASS" if not issues else "FAIL",
        "failure_code": (
            None if not issues else "cx_runtime_coupling_audit_failed"
        ),
        "refactoring_readiness": "TARGETED_REFACTOR_REQUIRED_BEFORE_S92_FEATURES",
        "summary": {
            "finding_count": len(findings),
            "refactor_required_count": sum(
                item["disposition"] == "REFACTOR_REQUIRED" for item in findings
            ),
            "accepted_for_now_count": sum(
                item["disposition"] == "ACCEPTED_FOR_NOW" for item in findings
            ),
            "good_boundary_count": sum(
                item["disposition"] == "GOOD_BOUNDARY" for item in findings
            ),
            "duplicated_authorization_helper_count": auth_helper_count,
            "evidence_gap_count": len(issues),
        },
        "findings": findings,
        "target_runtime_composition": {
            "name": "CxRuntimeDependencies",
            "construction": "app_factory_owned_no_import_time_mutation",
            "capability_ports": [
                "CxAccessContextResolver",
                "CxContentRepository",
                "CxPrivateTextStore",
                "CxVectorStore",
                "CxProcessingStateStore",
                "CxGenerationExecutionStore",
            ],
        },
        "ordered_refactoring": [
            "centralize CxAccessContext derivation and service authorization",
            "introduce app-factory-owned CxRuntimeDependencies",
            "extract private text and vector payload ports",
            "narrow route dependencies to capability protocols",
            "retain deterministic memory adapters for regression",
        ],
        "guardrails": [
            "no big-bang rewrite",
            "preserve public contracts and route behavior per slice",
            "keep file and provider IO outside database transactions",
            "retain repository and provider protocol boundaries",
        ],
        "issues": issues,
        "next_slice": "0907",
    }
