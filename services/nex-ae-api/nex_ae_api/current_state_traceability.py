from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_VERSION = "ae_capability_traceability_inventory.v1"
EXPECTED_REQUIREMENT_IDS = (
    *(f"AEAPI-FR-{number:03d}" for number in range(1, 7)),
    *(f"AEWEB-FR-{number:03d}" for number in range(1, 6)),
)
API_LAYERS = ("implementation", "contract", "migration", "test", "route")
WEB_LAYERS = ("implementation", "contract", "test", "route")


@dataclass(frozen=True)
class EvidenceRef:
    layer: str
    path: str
    token: str | None = None


@dataclass(frozen=True)
class CapabilitySpec:
    requirement_id: str
    capability: str
    required_layers: tuple[str, ...]
    evidence: tuple[EvidenceRef, ...]


CAPABILITY_SPECS = (
    CapabilitySpec(
        "AEAPI-FR-001",
        "workspace chat activity and prompt analytics ownership",
        API_LAYERS,
        (
            EvidenceRef("implementation", "services/nex-ae-api/nex_ae_api/workspace.py", "class WorkspaceStateStore"),
            EvidenceRef("implementation", "services/nex-ae-api/nex_ae_api/chat.py", "class SqlAlchemyChatInteractionStore"),
            EvidenceRef("contract", "contracts/schemas/service/nex_ae_api/workspace_state.v1.schema.json"),
            EvidenceRef("contract", "contracts/schemas/service/nex_ae_api/chat_interaction.v1.schema.json"),
            EvidenceRef("migration", "database/nex-ae-api/migrations/0021_prompt_analytics_foundation.sql", "ae_chat_interactions"),
            EvidenceRef("test", "tests/test_nex_ae_workspace.py"),
            EvidenceRef("test", "tests/test_nex_ae_chat.py"),
            EvidenceRef("route", "services/nex-ae-api/nex_ae_api/main.py", "register_workspace_routes(app)"),
        ),
    ),
    CapabilitySpec(
        "AEAPI-FR-002",
        "intent mode template prompt output and quality selection",
        API_LAYERS,
        (
            EvidenceRef("implementation", "services/nex-ae-api/nex_ae_api/workspace.py"),
            EvidenceRef("implementation", "services/nex-ae-api/nex_ae_api/prompts.py", "DEFAULT_AE_PROMPT_STORE"),
            EvidenceRef("contract", "contracts/schemas/service/nex_ae_api/workspace_state.v1.schema.json"),
            EvidenceRef("contract", "contracts/schemas/common/prompt_render_event.v1.schema.json"),
            EvidenceRef("migration", "database/nex-ae-api/migrations/0029_prompt_registry_seed.sql"),
            EvidenceRef("test", "tests/test_nex_ae_workspace.py"),
            EvidenceRef("test", "tests/test_prompt_registry.py"),
            EvidenceRef("route", "services/nex-ae-api/nex_ae_api/main.py", "register_prompt_registry_routes("),
        ),
    ),
    CapabilitySpec(
        "AEAPI-FR-003",
        "owner-scoped CX upload retrieval and generation orchestration",
        API_LAYERS,
        (
            EvidenceRef("implementation", "services/nex-ae-api/nex_ae_api/uploads.py", "class HttpCxUploadClient"),
            EvidenceRef("implementation", "services/nex-ae-api/nex_ae_api/retrieval.py", "class HttpCxRetrievalClient"),
            EvidenceRef("implementation", "services/nex-ae-api/nex_ae_api/chat.py", "class HttpCxGenerationClient"),
            EvidenceRef("contract", "contracts/schemas/service/nex_ae_api/upload_handoff.v1.schema.json"),
            EvidenceRef("contract", "contracts/schemas/service/nex_ae_api/retrieval_interaction.v1.schema.json"),
            EvidenceRef("migration", "database/nex-ae-api/migrations/0021_prompt_analytics_foundation.sql", "ae_chat_interactions"),
            EvidenceRef("test", "tests/test_nex_ae_uploads.py"),
            EvidenceRef("test", "tests/test_nex_ae_retrieval.py"),
            EvidenceRef("route", "services/nex-ae-api/nex_ae_api/main.py", "register_retrieval_routes(app)"),
        ),
    ),
    CapabilitySpec(
        "AEAPI-FR-004",
        "artifact records versions render jobs files preview and download",
        API_LAYERS,
        (
            EvidenceRef("implementation", "services/nex-ae-api/nex_ae_api/artifacts.py", "class SqlAlchemyArtifactRecordStore"),
            EvidenceRef("contract", "contracts/schemas/generation/ae_artifact_record.v1.schema.json"),
            EvidenceRef("contract", "contracts/schemas/generation/ae_artifact_handoff.v1.schema.json"),
            EvidenceRef("migration", "database/nex-ae-api/migrations/0402_ae_artifact_persistence_foundation.sql", "ae_artifact_render_jobs"),
            EvidenceRef("test", "tests/test_nex_ae_artifacts.py"),
            EvidenceRef("test", "tests/test_ae_artifact_postgres_smoke.py"),
            EvidenceRef("route", "services/nex-ae-api/nex_ae_api/main.py", "register_artifact_handoff_routes(app)"),
        ),
    ),
    CapabilitySpec(
        "AEAPI-FR-005",
        "chat artifact quality source progress and recovery attachments",
        API_LAYERS,
        (
            EvidenceRef("implementation", "services/nex-ae-api/nex_ae_api/chat.py", "artifact-links"),
            EvidenceRef("implementation", "services/nex-ae-api/nex_ae_api/recovery_requests.py"),
            EvidenceRef("contract", "contracts/schemas/service/nex_ae_api/chat_interaction.v1.schema.json"),
            EvidenceRef("contract", "contracts/schemas/service/nex_ae_api/generation_recovery_request.v1.schema.json"),
            EvidenceRef("migration", "database/nex-ae-api/migrations/0407_ae_chat_artifact_refs_foundation.sql", "ae_chat_artifact_refs"),
            EvidenceRef("test", "tests/test_nex_ae_chat.py"),
            EvidenceRef("test", "tests/test_nex_ae_recovery_requests.py"),
            EvidenceRef("route", "services/nex-ae-api/nex_ae_api/main.py", "register_generation_recovery_request_routes(app)"),
        ),
    ),
    CapabilitySpec(
        "AEAPI-FR-006",
        "permission recheck before artifact preview or download",
        API_LAYERS,
        (
            EvidenceRef("implementation", "services/nex-ae-api/nex_ae_api/artifacts.py", "def _authorize_ae_request"),
            EvidenceRef("implementation", "services/nex-ae-api/nex_ae_api/auth_guard.py", "class BrowserUserAuthContext"),
            EvidenceRef("contract", "contracts/openapi/nex-ae-api.openapi.yaml", "downloadAeArtifactFile"),
            EvidenceRef("migration", "database/nex-ae-api/migrations/0402_ae_artifact_persistence_foundation.sql", "ae_artifact_files"),
            EvidenceRef("test", "tests/test_nex_ae_artifacts.py"),
            EvidenceRef("test", "tests/test_nex_ae_auth_guard.py"),
            EvidenceRef("route", "services/nex-ae-api/nex_ae_api/main.py", "register_artifact_handoff_routes(app)"),
        ),
    ),
    CapabilitySpec(
        "AEWEB-FR-001",
        "Korean-default English-ready workspace shell",
        WEB_LAYERS,
        (
            EvidenceRef("implementation", "apps/nex-ae-web/index.html", 'lang="ko"'),
            EvidenceRef("implementation", "apps/nex-ae-web/src/styles.css"),
            EvidenceRef("contract", "contracts/schemas/service/nex_ae_web/fetch_mode_smoke_evidence.v1.schema.json"),
            EvidenceRef("test", "apps/nex-ae-web/test/runtimeConfig.test.mjs"),
            EvidenceRef("test", "tests/test_ae_web_static_browser_smoke.py"),
            EvidenceRef("route", "apps/nex-ae-web/src/main.js"),
        ),
    ),
    CapabilitySpec(
        "AEWEB-FR-002",
        "chat prompt mode template and runtime controls",
        WEB_LAYERS,
        (
            EvidenceRef("implementation", "apps/nex-ae-web/src/documentScope.js", "buildRetrievalRequest"),
            EvidenceRef("implementation", "apps/nex-ae-web/src/runtimeConfig.js"),
            EvidenceRef("contract", "contracts/schemas/service/nex_ae_api/workspace_state.v1.schema.json"),
            EvidenceRef("test", "apps/nex-ae-web/test/documentScope.test.mjs"),
            EvidenceRef("test", "apps/nex-ae-web/test/runtimeConfig.test.mjs"),
            EvidenceRef("route", "apps/nex-ae-web/src/main.js", "buildRuntimeConfigSummary"),
        ),
    ),
    CapabilitySpec(
        "AEWEB-FR-003",
        "upload ingestion search generation rendering and recovery progress",
        WEB_LAYERS,
        (
            EvidenceRef("implementation", "apps/nex-ae-web/src/operationState.js", "markOperationRunning"),
            EvidenceRef("implementation", "apps/nex-ae-web/src/authenticatedUploadWorkflow.js"),
            EvidenceRef("contract", "contracts/schemas/common/common_job.v1.schema.json"),
            EvidenceRef("test", "apps/nex-ae-web/test/operationState.test.mjs"),
            EvidenceRef("test", "apps/nex-ae-web/test/authenticatedUploadWorkflow.test.mjs"),
            EvidenceRef("route", "apps/nex-ae-web/src/main.js", "buildOperationStateSummary"),
        ),
    ),
    CapabilitySpec(
        "AEWEB-FR-004",
        "evidence citation source answer artifact preview and download surfaces",
        WEB_LAYERS,
        (
            EvidenceRef("implementation", "apps/nex-ae-web/src/artifactCard.js", "renderArtifactCard"),
            EvidenceRef("implementation", "apps/nex-ae-web/src/retrievalClient.js"),
            EvidenceRef("contract", "contracts/schemas/service/nex_ae_api/retrieval_interaction.v1.schema.json"),
            EvidenceRef("contract", "contracts/schemas/generation/ae_artifact_record.v1.schema.json"),
            EvidenceRef("test", "apps/nex-ae-web/test/artifactCard.test.mjs"),
            EvidenceRef("test", "apps/nex-ae-web/test/retrievalClient.test.mjs"),
            EvidenceRef("route", "apps/nex-ae-web/src/main.js", "renderArtifactPreviewPanel"),
        ),
    ),
    CapabilitySpec(
        "AEWEB-FR-005",
        "no-answer confidence citation completeness and manual warnings",
        WEB_LAYERS,
        (
            EvidenceRef("implementation", "apps/nex-ae-web/src/retrievalQualityWarnings.js"),
            EvidenceRef("implementation", "apps/nex-ae-web/src/groundedResponseQuality.js"),
            EvidenceRef("contract", "contracts/schemas/service/nex_ae_api/chat_interaction.v1.schema.json"),
            EvidenceRef("test", "apps/nex-ae-web/test/retrievalQualityWarnings.test.mjs"),
            EvidenceRef("test", "apps/nex-ae-web/test/groundedResponseQuality.test.mjs"),
            EvidenceRef("route", "apps/nex-ae-web/src/main.js", "buildGroundedResponseQualitySurface"),
        ),
    ),
)


def build_ae_capability_traceability_inventory(
    root: Path = ROOT,
    *,
    specs: Sequence[CapabilitySpec] = CAPABILITY_SPECS,
) -> dict[str, Any]:
    inventory = []
    issues = []
    for spec in specs:
        evidence = [_inspect_evidence(root, ref) for ref in spec.evidence]
        layers = sorted({item["layer"] for item in evidence})
        traceable = all(item["present"] for item in evidence)
        inventory.append(
            {
                "requirement_id": spec.requirement_id,
                "capability": spec.capability,
                "traceability_status": "TRACEABLE" if traceable else "EVIDENCE_GAP",
                "required_layers": list(spec.required_layers),
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
    checks = {
        "requirement_set_complete": requirement_ids == EXPECTED_REQUIREMENT_IDS,
        "requirement_ids_unique": len(requirement_ids) == len(set(requirement_ids)),
        "all_capabilities_traceable": all(
            item["traceability_status"] == "TRACEABLE" for item in inventory
        ),
        "required_layers_represented": all(
            set(item["required_layers"]).issubset(set(item["evidence_layers"]))
            for item in inventory
        ),
    }
    passed = all(checks.values())
    return {
        "inventory_schema_version": SCHEMA_VERSION,
        "slice": "1003",
        "requirement": "S101",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "ae_capability_traceability_inventory_failed",
        "decision": {
            "scope": "AEAPI-FR-001..006_and_AEWEB-FR-001..005",
            "inventory_role": "current_state_reaudit_baseline",
            "traceability_is_not_acceptance": True,
            "repository_evidence_is_authoritative": True,
            "new_table_required": False,
            "next_slice": "1004",
        },
        "summary": {
            "requirement_count": len(inventory),
            "traceable_count": sum(
                item["traceability_status"] == "TRACEABLE" for item in inventory
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
