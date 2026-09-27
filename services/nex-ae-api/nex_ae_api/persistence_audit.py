from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_VERSION = "ae_persistence_gap_rebaseline.v1"


@dataclass(frozen=True)
class PersistenceSurface:
    surface_id: str
    owner: str
    runtime_path: str
    runtime_token: str
    persistence_status: str
    gap_class: str | None
    target_tables: tuple[str, ...] = ()
    migration_path: str | None = None
    migration_token: str | None = None


PERSISTENCE_SURFACES = (
    PersistenceSurface(
        "workspace_state",
        "nex-ae-api",
        "services/nex-ae-api/nex_ae_api/workspace.py",
        "DEFAULT_WORKSPACE_STORE = WorkspaceStateStore()",
        "IN_MEMORY_GAP",
        "schema_and_adapter_decision",
    ),
    PersistenceSurface(
        "upload_handoffs",
        "nex-ae-api",
        "services/nex-ae-api/nex_ae_api/uploads.py",
        "DEFAULT_UPLOAD_HANDOFF_STORE = UploadHandoffStore()",
        "IN_MEMORY_GAP",
        "schema_and_adapter_decision",
    ),
    PersistenceSurface(
        "document_library",
        "nex-cx",
        "services/nex-ae-api/nex_ae_api/documents.py",
        "class HttpCxDocumentLibraryClient",
        "DELEGATED_SYSTEM_OF_RECORD",
        None,
    ),
    PersistenceSurface(
        "chat_interactions",
        "nex-ae-api",
        "services/nex-ae-api/nex_ae_api/chat.py",
        "class SqlAlchemyChatInteractionStore",
        "POSTGRES_ADAPTER_READY",
        None,
        ("ae_chat_interactions",),
        "database/nex-ae-api/migrations/0021_prompt_analytics_foundation.sql",
        "ae_chat_interactions",
    ),
    PersistenceSurface(
        "retrieval_interactions",
        "nex-ae-api",
        "services/nex-ae-api/nex_ae_api/retrieval.py",
        "DEFAULT_RETRIEVAL_STORE = RetrievalInteractionStore()",
        "IN_MEMORY_GAP",
        "schema_and_adapter_decision",
    ),
    PersistenceSurface(
        "generation_recovery_requests",
        "nex-ae-api",
        "services/nex-ae-api/nex_ae_api/recovery_requests.py",
        "DEFAULT_RECOVERY_REQUEST_STORE = GenerationRecoveryRequestStore()",
        "IN_MEMORY_GAP",
        "schema_and_adapter_decision",
    ),
    PersistenceSurface(
        "artifact_metadata",
        "nex-ae-api",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "class SqlAlchemyArtifactRecordStore",
        "POSTGRES_ADAPTER_READY",
        None,
        (
            "ae_artifacts",
            "ae_artifact_versions",
            "ae_artifact_render_jobs",
            "ae_artifact_files",
        ),
        "database/nex-ae-api/migrations/0402_ae_artifact_persistence_foundation.sql",
        "ae_artifact_files",
    ),
    PersistenceSurface(
        "artifact_rendered_payloads",
        "nex-ae-api",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "NEX_AE_ARTIFACT_STORAGE_ROOT",
        "CONFIGURABLE_LOCAL_STORAGE",
        "runtime_configuration_required",
    ),
    PersistenceSurface(
        "generation_feedback",
        "nex-ae-api",
        "services/nex-ae-api/nex_ae_api/generation_feedback.py",
        "class SqlAlchemyGenerationFeedbackStore",
        "POSTGRES_ADAPTER_READY",
        None,
        ("ae_generation_feedback",),
        "database/nex-ae-api/migrations/0334_ae_generation_feedback_persistence.sql",
        "ae_generation_feedback",
    ),
    PersistenceSurface(
        "repaired_response_handoffs",
        "nex-ae-api",
        "services/nex-ae-api/nex_ae_api/repaired_responses.py",
        "class SqlAlchemyRepairedResponseHandoffStore",
        "POSTGRES_ADAPTER_READY",
        None,
        ("ae_repaired_response_handoffs",),
        "database/nex-ae-api/migrations/0383_ae_repaired_response_handoff_persistence.sql",
        "ae_repaired_response_handoffs",
    ),
    PersistenceSurface(
        "repaired_response_decisions",
        "nex-ae-api",
        "services/nex-ae-api/nex_ae_api/repaired_response_decisions.py",
        "class SqlAlchemyRepairedResponseDecisionStore",
        "POSTGRES_ADAPTER_READY",
        None,
        ("ae_repaired_response_decisions",),
        "database/nex-ae-api/migrations/0387_ae_repaired_response_decision_persistence.sql",
        "ae_repaired_response_decisions",
    ),
    PersistenceSurface(
        "prompt_analytics",
        "nex-ae-api",
        "services/nex-ae-api/nex_ae_api/analytics.py",
        "DEFAULT_PROMPT_ANALYTICS_STORE = PromptAnalyticsStore()",
        "SCHEMA_READY_RUNTIME_IN_MEMORY",
        "postgres_adapter_required",
        (
            "ae_prompt_events",
            "ae_prompt_intent_classifications",
            "ae_user_task_profiles",
            "ae_automation_recommendations",
        ),
        "database/nex-ae-api/migrations/0021_prompt_analytics_foundation.sql",
        "ae_prompt_events",
    ),
    PersistenceSurface(
        "prompt_registry",
        "nex-ae-api",
        "services/nex-ae-api/nex_ae_api/prompts.py",
        "DEFAULT_AE_PROMPT_STORE = PromptRegistryStore()",
        "SCHEMA_READY_RUNTIME_IN_MEMORY",
        "postgres_adapter_required",
        ("ae_prompt_templates", "ae_prompt_template_versions", "ae_prompt_bindings"),
        "database/nex-ae-api/migrations/0021_prompt_analytics_foundation.sql",
        "ae_prompt_bindings",
    ),
    PersistenceSurface(
        "browser_auth_sessions",
        "nex-oa",
        "services/nex-ae-api/nex_ae_api/oa_session_client.py",
        "class OaUserSessionClient",
        "DELEGATED_SYSTEM_OF_RECORD",
        None,
    ),
    PersistenceSurface(
        "artifact_scheduler_worker_operations",
        "nex-ae-api",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "class SqlAlchemyArtifactRetentionSchedulerDaemonRunStore",
        "POSTGRES_ADAPTER_READY",
        None,
        (
            "ae_artifact_retention_scheduler_daemon_runs",
            "ae_op_exec_worker_results",
        ),
        "database/nex-ae-api/migrations/0612_ae_worker_result_persistence.sql",
        "ae_op_exec_worker_results",
    ),
)


def build_ae_persistence_gap_rebaseline(
    root: Path = ROOT,
    *,
    surfaces: Sequence[PersistenceSurface] = PERSISTENCE_SURFACES,
) -> dict[str, Any]:
    inspected = [_inspect_surface(root, surface) for surface in surfaces]
    evidence_issues = [
        {
            "category": "persistence_evidence_missing",
            "surface_id": item["surface_id"],
            "path": item["failed_path"],
        }
        for item in inspected
        if not item["evidence_present"]
    ]
    gap_surfaces = [item for item in inspected if item["gap_class"] is not None]
    checks = {
        "surface_inventory_complete": len(inspected) == 15,
        "runtime_and_migration_evidence_present": not evidence_issues,
        "system_of_record_explicit": all(item["owner"] for item in inspected),
        "gaps_classified": all(item["gap_class"] for item in gap_surfaces),
        "delegated_boundaries_not_duplicated": all(
            not item["target_tables"]
            for item in inspected
            if item["persistence_status"] == "DELEGATED_SYSTEM_OF_RECORD"
        ),
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1004",
        "requirement": "S101",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "ae_persistence_gap_rebaseline_failed",
        "checkpoint_status": "GAPS_CONFIRMED" if passed else "BLOCKED",
        "decision": {
            "postgres_metadata_first": True,
            "oa_and_cx_systems_of_record_not_duplicated": True,
            "artifact_payloads_outside_postgresql": True,
            "new_table_required_now": False,
            "schema_decision_required_count": 4,
            "adapter_only_gap_count": 2,
            "runtime_configuration_gap_count": 1,
            "next_slice": "1005",
        },
        "summary": {
            "surface_count": len(inspected),
            "postgres_ready_count": sum(
                item["persistence_status"] == "POSTGRES_ADAPTER_READY"
                for item in inspected
            ),
            "delegated_count": sum(
                item["persistence_status"] == "DELEGATED_SYSTEM_OF_RECORD"
                for item in inspected
            ),
            "gap_count": len(gap_surfaces),
            "evidence_issue_count": len(evidence_issues),
        },
        "checks": checks,
        "issues": evidence_issues,
        "surfaces": inspected,
    }


def _inspect_surface(root: Path, surface: PersistenceSurface) -> dict[str, Any]:
    runtime_path = root / surface.runtime_path
    runtime_present = runtime_path.is_file() and surface.runtime_token in runtime_path.read_text(
        encoding="utf-8"
    )
    migration_present = True
    failed_path = None
    if surface.migration_path is not None:
        migration_path = root / surface.migration_path
        migration_present = migration_path.is_file()
        if migration_present and surface.migration_token is not None:
            migration_present = surface.migration_token in migration_path.read_text(
                encoding="utf-8"
            )
        if not migration_present:
            failed_path = surface.migration_path
    if not runtime_present:
        failed_path = surface.runtime_path
    return {
        "surface_id": surface.surface_id,
        "owner": surface.owner,
        "persistence_status": surface.persistence_status,
        "gap_class": surface.gap_class,
        "target_tables": list(surface.target_tables),
        "runtime_path": surface.runtime_path,
        "migration_path": surface.migration_path,
        "evidence_present": runtime_present and migration_present,
        "failed_path": failed_path,
    }
