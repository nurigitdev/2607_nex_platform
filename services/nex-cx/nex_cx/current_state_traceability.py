from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_VERSION = "cx_capability_traceability_inventory.v1"
EXPECTED_REQUIREMENT_IDS = tuple(f"CX-FR-{number:03d}" for number in range(1, 9))


@dataclass(frozen=True)
class EvidenceRef:
    layer: str
    path: str
    token: str | None = None


@dataclass(frozen=True)
class CapabilitySpec:
    requirement_id: str
    capability: str
    evidence: tuple[EvidenceRef, ...]


CAPABILITY_SPECS = (
    CapabilitySpec(
        "CX-FR-001",
        "owner-scoped source and content registration",
        (
            EvidenceRef(
                "implementation",
                "services/nex-cx/nex_cx/ingestion.py",
                "class ContentIngestionStore",
            ),
            EvidenceRef(
                "implementation", "services/nex-cx/nex_cx/repository.py"
            ),
            EvidenceRef(
                "contract",
                "contracts/schemas/service/nex_cx/"
                "upload_registration.v1.schema.json",
            ),
            EvidenceRef(
                "migration",
                "database/nex-cx/migrations/"
                "0022_source_file_storage_policy.sql",
            ),
            EvidenceRef(
                "migration",
                "database/nex-cx/migrations/"
                "0194_cx_source_ownership_schema_migration.sql",
            ),
            EvidenceRef("test", "tests/test_nex_cx_ingestion.py"),
            EvidenceRef("test", "tests/test_nex_cx_repository.py"),
            EvidenceRef(
                "route",
                "services/nex-cx/nex_cx/main.py",
                "register_ingestion_routes(",
            ),
        ),
    ),
    CapabilitySpec(
        "CX-FR-002",
        "source extraction and Markdown materialization",
        (
            EvidenceRef(
                "implementation",
                "services/nex-cx/nex_cx/extractors.py",
                "class LocalMockTextExtractor",
            ),
            EvidenceRef(
                "implementation",
                "services/nex-cx/nex_cx/processing.py",
                "def run_document_processing_pipeline",
            ),
            EvidenceRef(
                "contract",
                "contracts/schemas/service/nex_cx/"
                "text_extraction.v1.schema.json",
            ),
            EvidenceRef(
                "migration",
                "database/nex-cx/migrations/"
                "0021_content_summary_prompt_foundation.sql",
            ),
            EvidenceRef("test", "tests/test_nex_cx_extractors.py"),
            EvidenceRef("test", "tests/test_nex_cx_processing.py"),
            EvidenceRef(
                "route",
                "services/nex-cx/nex_cx/main.py",
                "register_processing_routes(",
            ),
        ),
    ),
    CapabilitySpec(
        "CX-FR-003",
        "versioned 1000_100 chunk-set construction",
        (
            EvidenceRef(
                "implementation",
                "services/nex-cx/nex_cx/chunking.py",
                "def register_chunking_routes",
            ),
            EvidenceRef(
                "implementation", "services/nex-cx/nex_cx/repository.py"
            ),
            EvidenceRef(
                "contract",
                "contracts/schemas/service/nex_cx/chunk_set.v1.schema.json",
            ),
            EvidenceRef(
                "migration",
                "database/nex-cx/migrations/"
                "0021_content_summary_prompt_foundation.sql",
            ),
            EvidenceRef("test", "tests/test_nex_cx_chunking.py"),
            EvidenceRef("test", "tests/test_nex_cx_repository.py"),
            EvidenceRef(
                "route",
                "services/nex-cx/nex_cx/main.py",
                "register_chunking_routes(",
            ),
        ),
    ),
    CapabilitySpec(
        "CX-FR-004",
        "lexical and embedding index freshness",
        (
            EvidenceRef(
                "implementation",
                "services/nex-cx/nex_cx/lexical_index.py",
                "def register_lexical_index_routes",
            ),
            EvidenceRef(
                "implementation",
                "services/nex-cx/nex_cx/embedding_index.py",
                "def register_embedding_index_routes",
            ),
            EvidenceRef(
                "contract",
                "contracts/schemas/service/nex_cx/lexical_index.v1.schema.json",
            ),
            EvidenceRef(
                "contract",
                "contracts/schemas/service/nex_cx/embedding_index.v1.schema.json",
            ),
            EvidenceRef(
                "migration",
                "database/nex-cx/migrations/"
                "0021_content_summary_prompt_foundation.sql",
            ),
            EvidenceRef("test", "tests/test_nex_cx_lexical_index.py"),
            EvidenceRef("test", "tests/test_nex_cx_embedding_index.py"),
            EvidenceRef(
                "route",
                "services/nex-cx/nex_cx/main.py",
                "register_lexical_index_routes(",
            ),
            EvidenceRef(
                "route",
                "services/nex-cx/nex_cx/main.py",
                "register_embedding_index_routes(",
            ),
        ),
    ),
    CapabilitySpec(
        "CX-FR-005",
        "permission-filtered hybrid retrieval and reranking",
        (
            EvidenceRef(
                "implementation",
                "services/nex-cx/nex_cx/retrieval.py",
                "def build_retrieval_context_package",
            ),
            EvidenceRef(
                "implementation",
                "services/nex-cx/nex_cx/source_ownership.py",
            ),
            EvidenceRef(
                "contract",
                "contracts/schemas/service/nex_cx/"
                "retrieval_context_package.v1.schema.json",
            ),
            EvidenceRef(
                "migration",
                "database/nex-cx/migrations/"
                "0172_cx_retrieval_package_persistence.sql",
            ),
            EvidenceRef(
                "migration",
                "database/nex-cx/migrations/"
                "0194_cx_source_ownership_schema_migration.sql",
            ),
            EvidenceRef("test", "tests/test_nex_cx_retrieval.py"),
            EvidenceRef("test", "tests/test_nex_cx_source_ownership.py"),
            EvidenceRef(
                "route",
                "services/nex-cx/nex_cx/main.py",
                "register_retrieval_routes(",
            ),
        ),
    ),
    CapabilitySpec(
        "CX-FR-006",
        "persisted retrieval context package handoff",
        (
            EvidenceRef(
                "implementation",
                "services/nex-cx/nex_cx/retrieval.py",
                "def build_retrieval_context_package",
            ),
            EvidenceRef(
                "implementation",
                "services/nex-cx/nex_cx/retrieval_persistence.py",
            ),
            EvidenceRef(
                "contract",
                "contracts/schemas/service/nex_cx/"
                "retrieval_context_package.v1.schema.json",
            ),
            EvidenceRef(
                "migration",
                "database/nex-cx/migrations/"
                "0172_cx_retrieval_package_persistence.sql",
            ),
            EvidenceRef("test", "tests/test_nex_cx_retrieval.py"),
            EvidenceRef(
                "test", "tests/test_nex_cx_retrieval_persistence.py"
            ),
            EvidenceRef(
                "route",
                "services/nex-cx/nex_cx/main.py",
                "register_retrieval_routes(",
            ),
        ),
    ),
    CapabilitySpec(
        "CX-FR-007",
        "grounded generation request validation",
        (
            EvidenceRef(
                "implementation",
                "services/nex-cx/nex_cx/generation.py",
                "class GroundedGenerationBoundaryDecision",
            ),
            EvidenceRef(
                "implementation", "services/nex-cx/nex_cx/prompts.py"
            ),
            EvidenceRef(
                "contract",
                "contracts/schemas/generation/"
                "cx_structured_draft.v1.schema.json",
            ),
            EvidenceRef(
                "contract",
                "contracts/schemas/generation/"
                "generation_compatibility_rule.v1.schema.json",
            ),
            EvidenceRef(
                "migration",
                "database/nex-cx/migrations/0029_prompt_registry_seed.sql",
            ),
            EvidenceRef("test", "tests/test_nex_cx_generation.py"),
            EvidenceRef("test", "tests/test_nex_cx_drafts.py"),
            EvidenceRef(
                "route",
                "services/nex-cx/nex_cx/main.py",
                "register_generation_routes(",
            ),
        ),
    ),
    CapabilitySpec(
        "CX-FR-008",
        "generation execution, progress, recovery, and lineage",
        (
            EvidenceRef(
                "implementation",
                "services/nex-cx/nex_cx/generation.py",
                "class GenerationExecutionStore",
            ),
            EvidenceRef(
                "implementation",
                "services/nex-cx/nex_cx/remediation_execution.py",
                "def register_remediation_execution_routes",
            ),
            EvidenceRef(
                "contract",
                "contracts/schemas/generation/"
                "cx_generation_execution_record.v1.schema.json",
            ),
            EvidenceRef(
                "contract",
                "contracts/schemas/generation/"
                "generation_progress_event.v1.schema.json",
            ),
            EvidenceRef(
                "contract",
                "contracts/schemas/generation/"
                "generation_recovery_policy.v1.schema.json",
            ),
            EvidenceRef(
                "migration",
                "database/nex-cx/migrations/"
                "0355_cx_repair_attempt_lineage_persistence_foundation.sql",
            ),
            EvidenceRef("test", "tests/test_nex_cx_generation.py"),
            EvidenceRef("test", "tests/test_nex_cx_progress.py"),
            EvidenceRef(
                "test", "tests/test_nex_cx_remediation_execution.py"
            ),
            EvidenceRef(
                "route",
                "services/nex-cx/nex_cx/main.py",
                "register_remediation_execution_routes(",
            ),
        ),
    ),
)


def build_cx_capability_traceability_inventory(
    root: Path = ROOT,
    *,
    specs: Sequence[CapabilitySpec] = CAPABILITY_SPECS,
) -> dict[str, Any]:
    inventory = []
    issues = []
    for spec in specs:
        evidence = [_inspect_evidence(root, ref) for ref in spec.evidence]
        traceable = all(item["present"] for item in evidence)
        layers = sorted({item["layer"] for item in evidence})
        inventory.append(
            {
                "requirement_id": spec.requirement_id,
                "capability": spec.capability,
                "traceability_status": (
                    "TRACEABLE" if traceable else "EVIDENCE_GAP"
                ),
                "evidence_layers": layers,
                "evidence": evidence,
            }
        )
        issues.extend(
            {
                "category": "evidence_missing",
                "requirement_id": spec.requirement_id,
                "layer": item["layer"],
                "path": item["path"],
            }
            for item in evidence
            if not item["present"]
        )

    requirement_ids = tuple(item["requirement_id"] for item in inventory)
    required_layers = {"implementation", "contract", "migration", "test", "route"}
    checks = {
        "requirement_set_complete": requirement_ids == EXPECTED_REQUIREMENT_IDS,
        "requirement_ids_unique": len(requirement_ids) == len(set(requirement_ids)),
        "all_capabilities_traceable": all(
            item["traceability_status"] == "TRACEABLE" for item in inventory
        ),
        "all_layers_represented": all(
            required_layers.issubset(set(item["evidence_layers"]))
            for item in inventory
        ),
    }
    passed = all(checks.values())
    return {
        "inventory_schema_version": SCHEMA_VERSION,
        "slice": "0902",
        "requirement": "S91",
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None if passed else "cx_capability_traceability_inventory_failed"
        ),
        "decision": {
            "scope": "CX-FR-001..CX-FR-008",
            "inventory_role": "current_state_reaudit_baseline",
            "traceability_is_not_acceptance": True,
            "repository_evidence_is_authoritative": True,
            "new_table_required": False,
            "next_slice": "0903",
        },
        "summary": {
            "requirement_count": len(inventory),
            "traceable_count": sum(
                item["traceability_status"] == "TRACEABLE"
                for item in inventory
            ),
            "evidence_count": sum(len(item["evidence"]) for item in inventory),
        },
        "checks": checks,
        "issues": issues,
        "capabilities": inventory,
    }


def _inspect_evidence(root: Path, ref: EvidenceRef) -> dict[str, Any]:
    path = root / ref.path
    present = path.is_file()
    if present and ref.token is not None:
        present = ref.token in path.read_text(encoding="utf-8")
    return {
        "layer": ref.layer,
        "path": ref.path,
        "token_checked": ref.token is not None,
        "present": present,
    }
