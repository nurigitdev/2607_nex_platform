from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from nex_ag.artifact_operations import (
    AG_ARTIFACT_OPERATION_COLLECTION_PROJECTION_SCHEMA_VERSION,
    AG_ARTIFACT_OPERATION_DETAIL_PROJECTION_SCHEMA_VERSION,
    AG_ARTIFACT_OPERATION_LIFECYCLE_PROJECTION_SCHEMA_VERSION,
    AG_ARTIFACT_OPERATION_RETENTION_AUTOMATION_PROJECTION_SCHEMA_VERSION,
    AG_ARTIFACT_OPERATION_RETENTION_BATCH_PROJECTION_SCHEMA_VERSION,
    AG_ARTIFACT_OPERATION_RETENTION_DAEMON_PROJECTION_SCHEMA_VERSION,
    AG_ARTIFACT_OPERATION_RETENTION_HISTORY_PROJECTION_SCHEMA_VERSION,
    AG_ARTIFACT_OPERATION_RETENTION_SCHEDULED_DISPATCH_SCHEMA_VERSION,
    AG_ARTIFACT_OPERATION_RETENTION_SCHEDULED_JOB_PROJECTION_SCHEMA_VERSION,
    AE_ARTIFACT_SOURCE_SERVICE_ID,
    DEFAULT_AE_ARTIFACT_TIMEOUT_SECONDS,
    NEX_AG_AE_ARTIFACT_BASE_URL_ENV,
    NEX_AG_AE_ARTIFACT_SERVICE_TOKEN_ENV,
    NEX_AG_AE_ARTIFACT_TIMEOUT_SECONDS_ENV,
    AeArtifactOperationsError,
    HttpAeArtifactOperationsClient,
    InMemoryAeArtifactOperationsClient,
    assert_artifact_operation_projection_redacted,
    build_artifact_operation_collection_projection,
    build_artifact_operation_detail_projection,
    build_artifact_operation_lifecycle_projection,
    build_artifact_operation_retention_automation_projection,
    build_artifact_operation_retention_batch_projection,
    build_artifact_operation_retention_daemon_projection,
    build_artifact_operation_retention_history_projection,
    build_artifact_operation_retention_scheduled_dispatch_projection,
    build_artifact_operation_retention_scheduled_job_projection,
    build_default_ae_artifact_operations_client,
    register_artifact_operation_routes,
    summarize_artifact_operation_collection,
    summarize_artifact_operation_detail,
    summarize_artifact_operation_lifecycle,
    summarize_artifact_retention_batch_operations,
    summarize_artifact_retention_automation_operations,
    summarize_artifact_retention_daemon_operations,
    summarize_artifact_retention_history_operations,
    summarize_artifact_retention_scheduled_dispatch,
    summarize_artifact_retention_scheduled_job_operations,
)
import nex_ag.artifact_operations as artifact_operations
from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"
ARTIFACT_ID = "artifact-0409"
HANDOFF_ID = "handoff-0409"
INTERACTION_ID = "interaction-0409"


def auth_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience="nex-ag")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def artifact_record(*, include_private: bool = True) -> dict[str, Any]:
    record = {
        "artifact_id": ARTIFACT_ID,
        "artifact_schema_version": "ae_artifact_record.v1",
        "artifact_type": "generated_document",
        "artifact_status": "READY",
        "display_title": "Generated report",
        "current_version_id": "version-0409",
        "artifact_request_id": "request-0409",
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "owner_actor_ref": {
            "tenant_id": "tenant-0409",
            "user_id": "user-0409",
            "actor_type": "user",
        },
        "workspace_ref": {
            "workspace_id": "workspace-0409",
            "document_group_id": "group-0409",
            "chat_document_id": "chat-doc-0409",
            "local_path": "/data/nex-platform/private",
        },
        "target_formats": ["MD", "HTML_PREVIEW"],
        "handoff_ref": {
            "artifact_handoff_id": HANDOFF_ID,
            "artifact_request_id": "request-0409",
        },
        "source_refs": [
            {
                "cx_generation_id": "cx-gen-0409",
                "structured_draft_id": "draft-0409",
                "structured_draft_content_hash": "a" * 64,
                "generation_response_hash": "b" * 64,
                "quality_summary": {
                    "citation_status": "VALIDATED",
                    "citation_count": 2,
                    "validation_error_count": 0,
                    "warning_count": 0,
                    "grounding_required": True,
                    "retrieval_package_id": "retrieval-0409",
                    "retrieval_package_hash": "c" * 64,
                    "system_prompt": "SECRET_SYSTEM_PROMPT",
                },
                "raw_source": "raw source text",
            }
        ],
        "versions": [
            {
                "artifact_version_id": "version-0409",
                "artifact_id": ARTIFACT_ID,
                "version_no": 1,
                "version_reason": "initial_render",
                "source_content_hash": "a" * 64,
                "artifact_content_hash": "d" * 64,
                "rendered_formats": ["MD"],
                "validation_snapshot": {"quality_status": "PASS"},
                "created_at": "2026-08-29T00:00:00Z",
            }
        ],
        "render_jobs": [
            {
                "render_job_id": "render-job-0409",
                "artifact_id": ARTIFACT_ID,
                "artifact_version_id": "version-0409",
                "render_status": "SUCCEEDED",
                "renderer_policy_id": "ae-markdown-renderer-v1",
                "target_formats": ["MD"],
                "failure_summary": {},
                "started_at": "2026-08-29T00:00:00Z",
                "completed_at": "2026-08-29T00:00:01Z",
                "created_at": "2026-08-29T00:00:00Z",
            }
        ],
        "files": [
            {
                "artifact_file_id": "file-0409",
                "artifact_version_id": "version-0409",
                "artifact_id": ARTIFACT_ID,
                "format": "MD",
                "mime_type": "text/markdown",
                "file_name": "generated-report.md",
                "file_hash": "e" * 64,
                "file_size_bytes": 128,
                "storage_ref": "ae://artifacts/tenant-0409/file-0409.md",
                "created_at": "2026-08-29T00:00:01Z",
                "content": "PRIVATE_MARKDOWN",
            },
            {
                "artifact_file_id": "unsafe-file-0409",
                "artifact_version_id": "version-0409",
                "artifact_id": ARTIFACT_ID,
                "format": "PDF",
                "mime_type": "application/pdf",
                "file_name": "generated-report.pdf",
                "file_hash": "f" * 64,
                "file_size_bytes": "not-a-number",
                "storage_ref": "/data/nex-platform/ae/private.pdf",
            },
        ],
        "links": [
            {
                "artifact_link_id": "link-0409",
                "artifact_file_id": "file-0409",
                "link_type": "preview",
                "link_route": "/api/v1/artifact-files/file-0409/preview",
                "created_at": "2026-08-29T00:00:01Z",
            },
            {
                "artifact_link_id": "unsafe-link-0409",
                "artifact_file_id": "file-0409",
                "link_type": "download",
                "link_route": "file:///data/nex-platform/ae/private.md",
            },
        ],
        "created_at": "2026-08-29T00:00:00Z",
        "updated_at": "2026-08-29T00:00:01Z",
    }
    if include_private:
        record["source_text"] = "SECRET_SOURCE_TEXT"
    return record


def handoff_record() -> dict[str, Any]:
    return {
        "artifact_handoff_id": HANDOFF_ID,
        "handoff_schema_version": "ae_artifact_handoff.v1",
        "handoff_status": "READY_FOR_RENDERING",
        "artifact_request_id": "request-0409",
        "artifact_intent": "create_and_export",
        "artifact_type": "generated_document",
        "artifact_title": "Generated report",
        "cx_generation_id": "cx-gen-0409",
        "structured_draft_id": "draft-0409",
        "structured_draft_content_hash": "a" * 64,
        "generation_response_hash": "b" * 64,
        "target_formats": ["MD", "HTML_PREVIEW"],
        "quality_summary": {
            "citation_status": "VALIDATED",
            "citation_count": 2,
            "hidden_prompt": "hidden prompt",
        },
        "workspace_ref": {"workspace_id": "workspace-0409"},
        "created_at": "2026-08-29T00:00:00Z",
        "updated_at": "2026-08-29T00:00:01Z",
    }


def chat_artifact_ref() -> dict[str, Any]:
    return {
        "chat_artifact_ref_id": "chat-ref-0409",
        "chat_interaction_id": INTERACTION_ID,
        "chat_document_id": "chat-doc-0409",
        "tenant_id": "tenant-0409",
        "user_id": "user-0409",
        "artifact_id": ARTIFACT_ID,
        "artifact_version_id": "version-0409",
        "display_title": "Generated report",
        "artifact_type": "generated_document",
        "artifact_status": "READY",
        "primary_format": "MD",
        "available_formats": ["MD", "HTML_PREVIEW"],
        "preview_route": "/api/v1/artifact-files/file-0409/preview",
        "download_routes": {
            "MD": "/api/v1/artifact-files/file-0409/download",
            "unsafe": "/data/nex-platform/private",
        },
        "source_generation_id": "cx-gen-0409",
        "source_content_hash": "a" * 64,
        "quality_summary": {"citation_status": "VALIDATED", "citation_count": 2},
        "actions": {"preview": True, "download": True, "unsafe": {"nested": "no"}},
        "created_at": "2026-08-29T00:00:01Z",
        "updated_at": "2026-08-29T00:00:02Z",
    }


def artifact_collection_item(
    *,
    artifact_id: str = ARTIFACT_ID,
    status: str = "READY",
    owner_user_id: str = "user-0409",
    display_title: str = "Generated report",
    updated_at: str = "2026-08-29T00:00:01Z",
) -> dict[str, Any]:
    return {
        "artifact_collection_item_schema_version": "ae_artifact_collection_item.v1",
        "artifact_id": artifact_id,
        "artifact_type": "generated_document",
        "artifact_status": status,
        "display_title": display_title,
        "language": "ko",
        "artifact_intent": "create_and_export",
        "target_formats": ["MD", "HTML_PREVIEW"],
        "available_formats": ["MD", "HTML_PREVIEW"],
        "downloadable_formats": ["MD"],
        "previewable_formats": ["HTML_PREVIEW"],
        "current_version_id": "version-0409",
        "current_version_no": 1,
        "version_count": 1,
        "file_count": 2,
        "link_count": 2,
        "render_job_count": 1,
        "latest_render_job": {
            "render_job_id": "render-job-0409",
            "artifact_version_id": "version-0409",
            "render_status": "SUCCEEDED",
            "renderer_policy_id": "ae-markdown-renderer-v1",
            "target_formats": ["MD"],
            "created_at": updated_at,
            "storage_ref": "/data/nex-platform/private",
        },
        "source_summary": {
            "cx_generation_id": "cx-gen-0409",
            "structured_draft_id": "draft-0409",
            "structured_draft_content_hash": "a" * 64,
            "raw_source": "raw source",
        },
        "quality_summary": {
            "citation_status": "VALIDATED",
            "citation_count": 2,
            "hidden_prompt": "hidden prompt",
        },
        "routes": {
            "detail": f"/api/v1/artifacts/{artifact_id}",
            "versions": f"/api/v1/artifacts/{artifact_id}/versions",
            "unsafe": "file:///data/nex-platform/private.md",
        },
        "tenant_id": "tenant-0409",
        "workspace_id": "workspace-0409",
        "owner_user_id": owner_user_id,
        "chat_document_id": "chat-doc-0409",
        "interaction_id": INTERACTION_ID,
        "created_at": "2026-08-29T00:00:00Z",
        "updated_at": updated_at,
        "content_base64": "PRIVATE_CONTENT",
    }


def artifact_collection_payload() -> dict[str, Any]:
    return {
        "artifact_collection_schema_version": "ae_artifact_collection.v1",
        "filter": {
            "tenant_id": "tenant-0409",
            "workspace_id": "workspace-0409",
            "owner_user_id": "user-0409",
            "status": None,
            "limit": 20,
        },
        "count": 2,
        "limit": 20,
        "next_cursor": None,
        "items": [
            artifact_collection_item(),
            artifact_collection_item(
                artifact_id="artifact-draft-0409",
                status="DRAFT",
                display_title="Draft report",
                updated_at="2026-08-29T00:00:00Z",
            ),
        ],
    }


def artifact_retention_history_collection_payload() -> dict[str, Any]:
    return {
        "artifact_retention_execution_history_collection_schema_version": (
            "ae_artifact_retention_execution_history_collection.v1"
        ),
        "filter": {
            "tenant_id": "tenant-0409",
            "workspace_id": "workspace-0409",
            "owner_user_id": "user-0409",
            "mode": None,
            "execution_status": None,
            "limit": 20,
        },
        "count": 3,
        "limit": 20,
        "next_cursor": None,
        "items": [
            {
                "artifact_retention_execution_history_item_schema_version": (
                    "ae_artifact_retention_execution_history_item.v1"
                ),
                "retention_execution_id": "retention-execute-0409",
                "policy_id": "ae-artifact-logical-purge-30d-local-v1",
                "service_id": "nex-ae-api",
                "mode": "EXECUTE",
                "execution_status": "SUCCEEDED",
                "tenant_id": "tenant-0409",
                "workspace_id": "workspace-0409",
                "owner_user_id": "user-0409",
                "retention_days_after_logical_purge": 30,
                "as_of": "2026-09-01T00:00:00Z",
                "cutoff_at": "2026-08-02T00:00:00Z",
                "checked_at": "2026-09-01T02:50:00Z",
                "scan_limit": 10,
                "max_delete_count": 1,
                "candidate_count": 2,
                "selected_count": 1,
                "delete_enabled": True,
                "storage_mutation_enabled": True,
                "database_row_delete_enabled": True,
                "deleted_counts": {
                    "artifacts": 1,
                    "source_refs": 1,
                    "versions": 1,
                    "render_jobs": 1,
                    "files": 2,
                    "links": 4,
                    "storage_files": 2,
                },
                "requested_by": {
                    "actor_type": "service",
                    "actor_id": "nex-ag",
                    "service_id": "nex-ae-api",
                },
                "idempotency_key": "history-execute-0409",
                "trace_id": TRACE_ID,
                "request_id": REQUEST_ID,
                "blocked_reason": None,
                "error": None,
                "audit": {
                    "audit_event_type": "ae_artifact.retention.execution",
                    "audit_event_id": "audit-retention-execute-0409",
                    "emitted": False,
                },
                "metadata": {
                    "metadata_only": True,
                    "candidate_scan_metadata_only": True,
                    "logical_purge_required_before_physical_delete": True,
                    "scheduled_batch_timezone": "Asia/Seoul",
                    "scheduled_batch_window": {
                        "start_local_time": "02:00",
                        "end_local_time": "05:00",
                    },
                },
                "execution_payload_hash": "a" * 64,
                "created_at": "2026-09-01T02:50:00Z",
            },
            {
                "retention_execution_id": "retention-blocked-0409",
                "mode": "EXECUTE",
                "execution_status": "BLOCKED",
                "tenant_id": "tenant-0409",
                "workspace_id": "workspace-0409",
                "owner_user_id": "user-0409",
                "checked_at": "2026-09-01T02:45:00Z",
                "candidate_count": 2,
                "selected_count": 0,
                "deleted_counts": {"artifacts": 0, "storage_files": 0},
                "blocked_reason": "delete_not_enabled",
                "execution_payload_hash": "b" * 64,
            },
            {
                "retention_execution_id": "retention-dry-0409",
                "mode": "DRY_RUN",
                "execution_status": "SUCCEEDED",
                "tenant_id": "tenant-0409",
                "workspace_id": "workspace-0409",
                "owner_user_id": "user-0409",
                "checked_at": "2026-09-01T02:40:00Z",
                "candidate_count": 2,
                "selected_count": 1,
                "deleted_counts": {"artifacts": 0, "storage_files": 0},
                "execution_payload_hash": "c" * 64,
            },
        ],
    }


def artifact_retention_batch_plan_payload() -> dict[str, Any]:
    return {
        "artifact_retention_batch_plan_schema_version": (
            "ae_artifact_retention_batch_plan.v1"
        ),
        "plan_id": "retention-batch-plan-0409",
        "service_id": "nex-ae-api",
        "schedule": {
            "schedule_id": "ae-artifact-retention-schedule-local-v1",
            "policy_id": "ae-artifact-logical-purge-30d-local-v1",
            "service_id": "nex-ae-api",
            "enabled": False,
            "planning_enabled": True,
            "default_mode": "DRY_RUN",
            "allowed_modes": ["DRY_RUN", "EXECUTE"],
            "retention_days_presets": [15, 30],
            "default_retention_days_after_logical_purge": 30,
            "max_scan_limit": 100,
            "max_delete_count": 10,
            "timezone": "Asia/Seoul",
            "batch_window": {
                "start_local_time": "02:00",
                "end_local_time": "05:00",
            },
            "scheduler": {
                "daemon_enabled": False,
                "cron": "SECRET_SYSTEM_PROMPT",
            },
            "execution_guards": {
                "delete_enabled": False,
                "storage_mutation_enabled": False,
                "database_row_delete_enabled": False,
            },
            "ownership": {
                "system_of_record": "nex-ae-api",
                "database_url": "DATABASE_URL_SHOULD_NOT_LEAK",
            },
        },
        "candidate_filter": {
            "tenant_id": "tenant-0409",
            "workspace_id": "workspace-0409",
            "owner_user_id": "user-0409",
            "status": "DELETED",
            "retention_days": 30,
            "as_of": "2026-09-01T00:00:00Z",
            "cutoff_at": "2026-08-02T00:00:00Z",
            "limit": 20,
            "dry_run": True,
        },
        "tenant_id": "tenant-0409",
        "workspace_id": "workspace-0409",
        "owner_user_id": "user-0409",
        "mode": "DRY_RUN",
        "plan_status": "READY",
        "scheduler_status": "DISABLED",
        "execution_advice": "Review dry-run evidence before enabling deletes.",
        "as_of": "2026-09-01T00:00:00Z",
        "cutoff_at": "2026-08-02T00:00:00Z",
        "checked_at": "2026-09-01T02:30:00Z",
        "scan_limit": 20,
        "max_delete_count": 1,
        "candidate_count": 2,
        "selected_count": 1,
        "unselected_count": 1,
        "estimated_deleted_counts": {
            "artifacts": 1,
            "source_refs": 1,
            "versions": 1,
            "render_jobs": 1,
            "files": 2,
            "links": 4,
            "storage_files": 2,
        },
        "selected_candidates": [
            {
                "artifact_retention_batch_candidate_schema_version": (
                    "ae_artifact_retention_batch_candidate.v1"
                ),
                "selection_order": 1,
                "artifact_id": ARTIFACT_ID,
                "display_title": "Generated report",
                "artifact_status": "DELETED",
                "logical_purged_at": "2026-07-31T00:00:00Z",
                "purge_eligible_at": "2026-08-30T00:00:00Z",
                "age_days_after_logical_purge": 32,
                "version_count": 1,
                "file_count": 2,
                "link_count": 4,
                "render_job_count": 1,
                "planned_action": "retention_purge_dry_run",
                "execution_mode": "dry-run",
                "dry_run": True,
                "storage_ref": "/data/nex-platform/ae/private.md",
                "rendered_markdown": "PRIVATE_MARKDOWN",
            }
        ],
        "requested_by": {
            "actor_type": "service",
            "actor_id": "nex-ag",
            "service_id": "nex-ae-api",
        },
        "idempotency_key": "retention-batch-plan-0409",
        "metadata": {
            "metadata_only": True,
            "dry_run": True,
            "physical_delete_executed": False,
            "storage_mutation_executed": False,
            "database_row_delete_executed": False,
            "history_write_executed": False,
            "source_collection_count": 2,
            "database_url": "DATABASE_URL_SHOULD_NOT_LEAK",
        },
    }


def artifact_retention_scheduled_job_payload(
    *,
    job_id: str = "job-retention-scheduled-0409",
    status: str = "QUEUED",
    owner_user_id: str = "user-0409",
    updated_at: str = "2026-09-01T02:16:00Z",
    retryable: bool = True,
    selected_count: int = 1,
) -> dict[str, Any]:
    command_id = f"command-{job_id}"
    estimated_deleted_counts = {
        "artifacts": selected_count,
        "source_refs": selected_count,
        "versions": selected_count,
        "render_jobs": selected_count,
        "files": selected_count * 2,
        "links": selected_count * 4,
        "storage_files": selected_count * 2,
    }
    command_summary = {
        "command_status": "READY",
        "trigger_type": "scheduler_tick",
        "scheduler_status": "DISABLED",
        "execution_mode": "DRY_RUN",
        "candidate_count": 2,
        "selected_count": selected_count,
        "estimated_deleted_artifacts": selected_count,
        "estimated_deleted_storage_files": selected_count * 2,
        "command_created_at": "2026-09-01T02:15:00Z",
        "next_action": "Review dry-run evidence before enabling deletes.",
    }
    return {
        "artifact_retention_scheduled_job_schema_version": (
            "ae_artifact_retention_scheduled_job.v1"
        ),
        "job_schema_version": "common_job.v1",
        "job_id": job_id,
        "job_type": "ae.artifact_retention.scheduled_execution",
        "status": status,
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "subject_ref": {
            "type": "ae.artifact_retention.scheduled_execution",
            "id": command_id,
            "database_url": "postgresql://nuri1004@private",
        },
        "idempotency_key": f"idem-{job_id}",
        "attempt_count": 0 if status == "QUEUED" else 1,
        "max_attempts": 3,
        "retryable": retryable,
        "links": {
            "ae_retention_batch_plan": "/api/v1/artifact-retention/batch-plan",
            "ae_retention_purge": "/api/v1/artifact-retention/purge",
            "ae_retention_history": "/api/v1/artifact-retention/executions",
            "unsafe_storage": "/data/nex-platform/ae/private.md",
        },
        "payload": {
            "payload_schema_version": "ae_artifact_retention_scheduled_job_payload.v1",
            "command_id": command_id,
            "source_plan_id": "retention-batch-plan-0409",
            "tenant_id": "tenant-0409",
            "workspace_id": "workspace-0409",
            "owner_user_id": owner_user_id,
            "trigger_type": "scheduler_tick",
            "scheduler_status": "DISABLED",
            "command_status": "READY",
            "execution_mode": "dry-run",
            "retention_days_after_logical_purge": "30",
            "scan_limit": "20",
            "max_delete_count": "1",
            "candidate_count": "2",
            "selected_count": str(selected_count),
            "estimated_deleted_counts": estimated_deleted_counts,
            "command_summary": command_summary,
            "scheduled_command": {
                "execution_request": {
                    "storage_ref": "/data/nex-platform/ae/private.md",
                }
            },
            "requested_by": {
                "actor_type": "service",
                "actor_id": "nex-ag",
                "service_id": "nex-ae-api",
                "database_url": "DATABASE_URL_SHOULD_NOT_LEAK",
            },
            "idempotency_key": f"idem-{job_id}",
            "requested_at": "2026-09-01T02:16:00Z",
            "redaction_summary": {
                "metadata_only": True,
                "scheduled_command_embedded": True,
                "batch_plan_embedded": False,
                "artifact_payload_included": False,
                "prompt_content_included": False,
                "generation_output_included": False,
                "storage_locator_included": False,
                "database_url_included": False,
            },
        },
        "created_at": "2026-09-01T02:16:00Z",
        "updated_at": updated_at,
    }


def artifact_retention_scheduled_job_collection_payload() -> dict[str, Any]:
    return {
        "artifact_retention_scheduled_job_collection_schema_version": (
            "ae_artifact_retention_scheduled_job_collection.v1"
        ),
        "filter": {
            "tenant_id": "tenant-0409",
            "workspace_id": "workspace-0409",
            "owner_user_id": "user-0409",
            "status": None,
            "limit": 20,
        },
        "count": 3,
        "limit": 20,
        "next_cursor": None,
        "items": [
            artifact_retention_scheduled_job_payload(),
            artifact_retention_scheduled_job_payload(
                job_id="job-retention-scheduled-failed-0409",
                status="FAILED",
                updated_at="2026-09-01T02:18:00Z",
                retryable=True,
                selected_count=2,
            ),
            artifact_retention_scheduled_job_payload(
                job_id="job-retention-scheduled-succeeded-0409",
                status="SUCCEEDED",
                updated_at="2026-09-01T02:17:00Z",
                retryable=False,
                selected_count=1,
            ),
        ],
        "metadata": {
            "metadata_only": True,
            "system_of_record": "nex-ae-api",
        },
    }


def artifact_retention_scheduled_dispatch_response_payload() -> dict[str, Any]:
    job = artifact_retention_scheduled_job_payload()
    return {
        "artifact_retention_scheduled_job_enqueue_result_schema_version": (
            "ae_artifact_retention_scheduled_job_enqueue_result.v1"
        ),
        "service_id": "nex-ae-api",
        "source_plan_id": "retention-batch-plan-0409",
        "command_id": job["payload"]["command_id"],
        "job_id": job["job_id"],
        "job_type": job["job_type"],
        "tenant_id": "tenant-0409",
        "workspace_id": "workspace-0409",
        "owner_user_id": "user-0409",
        "trigger_type": "operator_dispatch",
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "idempotency_key": "dispatch-idem-0409",
        "enqueue_status": "ENQUEUED",
        "job_enqueued": True,
        "duplicate_returned": False,
        "queue_admission": {
            "queue_service_id": "nex-ae-api",
            "queue_backend": "service_job_queue",
            "target_job_type": "ae.artifact_retention.scheduled_execution",
            "job_enqueued": True,
            "worker_execution_performed": False,
            "scheduler_daemon_started": False,
            "physical_delete_automation_enabled": False,
            "database_url": "DATABASE_URL_SHOULD_NOT_LEAK",
        },
        "command_summary": job["payload"]["command_summary"],
        "job_summary": {
            "job_id": job["job_id"],
            "job_type": job["job_type"],
            "status": "QUEUED",
            "command_id": job["payload"]["command_id"],
            "source_plan_id": "retention-batch-plan-0409",
            "trigger_type": "operator_dispatch",
            "execution_mode": "DRY_RUN",
            "candidate_count": 2,
            "selected_count": 1,
            "history_write_expected": True,
            "physical_delete_automation_enabled": False,
        },
        "admission": {
            "command": {
                "execution_request": {
                    "storage_ref": "/data/nex-platform/ae/private.md",
                }
            }
        },
        "enqueued_job": job,
    }


def artifact_retention_scheduler_daemon_config_payload(
    *,
    job_queue_available: bool = True,
    lease_available: bool = True,
) -> dict[str, Any]:
    manual_status = "READY" if job_queue_available and lease_available else "BLOCKED"
    manual_block_reason = None
    if not lease_available:
        manual_block_reason = "lease_repository_unavailable"
    elif not job_queue_available:
        manual_block_reason = "job_queue_unavailable"
    runtime = {
        "scheduler_daemon_enabled": False,
        "scheduler_daemon_started": False,
        "daemon_auto_start_allowed": False,
        "continuous_loop_enabled": False,
        "continuous_loop_started": False,
        "manual_tick_once_enabled": True,
        "manual_tick_once_requires_lease": True,
        "scheduler_tick_admission_enabled": True,
        "operator_dispatch_admission_enabled": True,
        "default_execution_mode": "DRY_RUN",
        "job_queue_available": job_queue_available,
        "job_queue_backend": "service_job_queue" if job_queue_available else "missing",
        "scheduler_tick_interval_seconds": 900,
        "scheduler_tick_jitter_seconds": 60,
        "scheduler_tick_lock_ttl_seconds": 120,
        "scheduler_tick_stale_after_seconds": 900,
        "scheduler_tick_max_jobs_per_tick": 1,
        "scheduler_tick_batch_window_enforced": True,
        "scheduler_tick_timezone": "Asia/Seoul",
        "scheduler_tick_window_start": "02:00",
        "scheduler_tick_window_end": "05:00",
    }
    lease_repository = {
        "required": True,
        "available": lease_available,
        "backend": "sqlalchemy" if lease_available else "not_configured",
        "lease_record_schema_version": (
            "ae_artifact_retention_scheduler_lease_record.v1"
        ),
        "failure_code": None if lease_available else "lease_repository_unavailable",
    }
    return {
        "daemon_config_schema_version": (
            "ae_artifact_retention_scheduler_daemon_config.v1"
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": "ae-artifact-retention-scheduler",
        "checked_at": "2026-09-01T02:30:00Z",
        "source_scheduler_config_schema_version": (
            "ae_artifact_retention_scheduler_config.v1"
        ),
        "runtime": runtime,
        "lease_repository": lease_repository,
        "supported_actions": [
            {
                "action": "status_probe",
                "decision_status": "NOOP",
                "requires_lease": False,
                "runs_tick_once": False,
                "starts_daemon": False,
                "starts_continuous_loop": False,
                "block_reason": None,
            },
            {
                "action": "manual_tick_once",
                "decision_status": manual_status,
                "requires_lease": True,
                "runs_tick_once": manual_status == "READY",
                "starts_daemon": False,
                "starts_continuous_loop": False,
                "block_reason": manual_block_reason,
            },
            {
                "action": "start_daemon",
                "decision_status": "BLOCKED",
                "requires_lease": False,
                "runs_tick_once": False,
                "starts_daemon": False,
                "starts_continuous_loop": False,
                "block_reason": "daemon_disabled_by_policy",
            },
            {
                "action": "stop_daemon",
                "decision_status": "NOOP",
                "requires_lease": False,
                "runs_tick_once": False,
                "starts_daemon": False,
                "starts_continuous_loop": False,
                "block_reason": None,
            },
        ],
        "guardrails": {
            "metadata_only": True,
            "manual_tick_once_only": True,
            "lease_required_before_tick": True,
            "daemon_auto_start_allowed": False,
            "scheduler_daemon_started": False,
            "continuous_loop_started": False,
            "continuous_loop_allowed_before_lease": False,
            "physical_delete_automation_enabled": False,
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
        },
        "metadata": {
            "metadata_only": True,
            "database_url_included": False,
            "storage_path_included": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_included": False,
            "scheduler_daemon_started": False,
            "continuous_loop_started": False,
            "physical_delete_automation_enabled": False,
        },
    }


def artifact_retention_scheduler_daemon_dispatch_payload(
    *,
    action: str = "manual_tick_once",
    dispatch_status: str = "DISPATCHED",
) -> dict[str, Any]:
    config = artifact_retention_scheduler_daemon_config_payload()
    control_plan = {
        "daemon_control_plan_schema_version": (
            "ae_artifact_retention_scheduler_daemon_control_plan.v1"
        ),
        "daemon_control_plan_id": "daemon-control-plan-0522",
        "service_id": "nex-ae-api",
        "scheduler_id": config["scheduler_id"],
        "action": action,
        "decision_status": "READY" if dispatch_status == "DISPATCHED" else "BLOCKED",
        "block_reason": None if dispatch_status == "DISPATCHED" else "blocked",
        "requested_at": "2026-09-01T02:35:00Z",
        "requested_by": {
            "actor_type": "operator",
            "actor_id": "ag-retention-operator",
        },
        "reason": "manual AG dispatch",
        "daemon_config": config,
        "execution_plan": {
            "requires_lease": True,
            "runs_tick_once": dispatch_status == "DISPATCHED",
            "dispatches_job_queue": dispatch_status == "DISPATCHED",
            "starts_daemon": False,
            "starts_continuous_loop": False,
            "writes_history": False,
            "physical_delete_enabled": False,
        },
        "guardrails": config["guardrails"],
        "metadata": {
            "metadata_only": True,
            "database_url_included": False,
            "storage_path_included": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_included": False,
            "tick_once_dispatched": dispatch_status == "DISPATCHED",
            "scheduler_daemon_started": False,
            "continuous_loop_started": False,
            "physical_delete_automation_enabled": False,
        },
    }
    return {
        "daemon_dispatch_result_schema_version": (
            "ae_artifact_retention_scheduler_daemon_dispatch_result.v1"
        ),
        "daemon_dispatch_result_id": "daemon-dispatch-result-0522",
        "service_id": "nex-ae-api",
        "scheduler_id": config["scheduler_id"],
        "dispatch_status": dispatch_status,
        "control_plan": control_plan,
        "tick_once_result": None,
        "guardrails": {
            **config["guardrails"],
            "daemon_control_plan_required": True,
            "tick_once_requires_ready_control_plan": True,
        },
        "metadata": {
            "metadata_only": True,
            "database_url_included": False,
            "storage_path_included": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_included": False,
            "control_plan_ready": dispatch_status == "DISPATCHED",
            "tick_once_dispatched": dispatch_status == "DISPATCHED",
            "lease_acquired_before_tick": False,
            "lease_released": False,
            "job_enqueued": dispatch_status == "DISPATCHED",
            "worker_executed": False,
            "scheduler_daemon_started": False,
            "continuous_loop_started": False,
            "physical_delete_automation_enabled": False,
        },
    }


def artifact_client() -> InMemoryAeArtifactOperationsClient:
    return InMemoryAeArtifactOperationsClient(
        artifacts={ARTIFACT_ID: artifact_record()},
        artifact_retention_history_collections={
            artifact_operations._artifact_retention_history_cache_key(
                tenant_id="tenant-0409",
                workspace_id="workspace-0409",
                owner_user_id="user-0409",
                mode=None,
                execution_status=None,
                limit=20,
            ): artifact_retention_history_collection_payload(),
            artifact_operations._artifact_retention_history_cache_key(
                tenant_id="tenant-0409",
                workspace_id="workspace-0409",
                owner_user_id="user-0409",
                mode="EXECUTE",
                execution_status=None,
                limit=20,
            ): {
                **artifact_retention_history_collection_payload(),
                "filter": {
                    **artifact_retention_history_collection_payload()["filter"],
                    "mode": "EXECUTE",
                },
                "count": 2,
                "items": artifact_retention_history_collection_payload()["items"][:2],
            },
        },
        artifact_retention_batch_plans={
            artifact_operations._artifact_retention_batch_plan_cache_key(
                tenant_id="tenant-0409",
                workspace_id="workspace-0409",
                owner_user_id="user-0409",
                retention_days=30,
                as_of="2026-09-01T00:00:00Z",
                scan_limit=20,
                max_delete_count=1,
                checked_at="2026-09-01T02:30:00Z",
            ): artifact_retention_batch_plan_payload()
        },
        artifact_retention_scheduled_job_collections={
            artifact_operations._artifact_retention_scheduled_job_cache_key(
                tenant_id="tenant-0409",
                workspace_id="workspace-0409",
                owner_user_id="user-0409",
                status=None,
                limit=20,
            ): artifact_retention_scheduled_job_collection_payload(),
        },
        artifact_retention_scheduled_jobs={
            "job-retention-scheduled-filtered-0409": (
                artifact_retention_scheduled_job_payload(
                    job_id="job-retention-scheduled-filtered-0409",
                    status="RUNNING",
                    updated_at="2026-09-01T02:19:00Z",
                )
            ),
            "job-retention-scheduled-other-owner": (
                artifact_retention_scheduled_job_payload(
                    job_id="job-retention-scheduled-other-owner",
                    owner_user_id="other-user",
                )
            ),
            "job-retention-scheduled-other-type": {
                **artifact_retention_scheduled_job_payload(
                    job_id="job-retention-scheduled-other-type"
                ),
                "job_type": "ae.other",
            },
        },
        artifact_retention_scheduler_daemon_config=(
            artifact_retention_scheduler_daemon_config_payload()
        ),
        handoffs={HANDOFF_ID: handoff_record()},
        chat_artifact_refs={INTERACTION_ID: {"artifact_refs": [chat_artifact_ref()]}},
    )


def test_artifact_operation_projection_summarizes_and_redacts() -> None:
    source_client = artifact_client()
    projection = build_artifact_operation_detail_projection(
        artifact=source_client.get_artifact(
            ARTIFACT_ID,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        ),
        handoff=source_client.get_artifact_handoff(
            HANDOFF_ID,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        ),
        chat_artifact_refs=source_client.list_chat_artifact_refs(
            INTERACTION_ID,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        ),
        source_client=source_client,
        request_trace_id=TRACE_ID,
    )

    artifact = projection["artifact"]
    assert projection["projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_DETAIL_PROJECTION_SCHEMA_VERSION
    )
    assert projection["projection_status"] == "READY"
    assert projection["summary"] == {
        "artifact_status": "READY",
        "artifact_type": "generated_document",
        "version_count": 1,
        "render_job_count": 1,
        "file_count": 2,
        "link_count": 2,
        "source_ref_count": 1,
        "chat_artifact_ref_count": 1,
        "handoff_loaded": True,
        "latest_render_status": "SUCCEEDED",
    }
    assert artifact["owner_scope"] == {
        "tenant_id": "tenant-0409",
        "user_id": "user-0409",
        "actor_type": "user",
    }
    assert artifact["files"][0]["storage_ref"].startswith("ae://artifacts/")
    assert artifact["files"][1]["storage_ref"] is None
    assert artifact["links"][1]["link_route"] is None
    assert projection["chat_artifact_refs"][0]["download_routes"] == {
        "MD": "/api/v1/artifact-files/file-0409/download"
    }
    assert "SECRET" not in str(projection)
    assert "/data/nex-platform" not in str(projection)


def test_artifact_operation_collection_projection_summarizes_and_redacts() -> None:
    projection = build_artifact_operation_collection_projection(
        collection=artifact_collection_payload(),
        source_client=InMemoryAeArtifactOperationsClient(),
        request_trace_id=TRACE_ID,
    )

    assert projection["projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_COLLECTION_PROJECTION_SCHEMA_VERSION
    )
    assert projection["operation_type"] == "ae_artifact_collection"
    assert projection["projection_status"] == "READY"
    assert projection["filter"] == {
        "tenant_id": "tenant-0409",
        "workspace_id": "workspace-0409",
        "owner_user_id": "user-0409",
        "status": None,
        "limit": 20,
    }
    assert projection["summary"] == {
        "item_count": 2,
        "ready_count": 1,
        "draft_count": 1,
        "failed_count": 0,
        "downloadable_count": 2,
        "previewable_count": 2,
        "status_counts": {"READY": 1, "DRAFT": 1},
        "latest_updated_at": "2026-08-29T00:00:01Z",
    }
    assert projection["items"][0]["routes"] == {
        "detail": f"/api/v1/artifacts/{ARTIFACT_ID}",
        "versions": f"/api/v1/artifacts/{ARTIFACT_ID}/versions",
    }
    assert projection["items"][0]["latest_render_job"]["render_status"] == ("SUCCEEDED")
    assert projection["source_status"]["item_count"] == 2
    assert projection["request_trace_id"] == TRACE_ID
    assert "PRIVATE_CONTENT" not in str(projection)
    assert "hidden prompt" not in str(projection)
    assert "/data/nex-platform" not in str(projection)


def test_artifact_operation_retention_history_projection_summarizes_and_redacts() -> (
    None
):
    projection = build_artifact_operation_retention_history_projection(
        collection=artifact_retention_history_collection_payload(),
        source_client=InMemoryAeArtifactOperationsClient(),
        request_trace_id=TRACE_ID,
    )

    assert projection["projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_RETENTION_HISTORY_PROJECTION_SCHEMA_VERSION
    )
    assert projection["operation_type"] == "ae_artifact_retention_history"
    assert projection["projection_status"] == "READY"
    assert projection["filter"] == {
        "tenant_id": "tenant-0409",
        "workspace_id": "workspace-0409",
        "owner_user_id": "user-0409",
        "mode": None,
        "execution_status": None,
        "limit": 20,
    }
    assert projection["summary"] == {
        "item_count": 3,
        "mode_counts": {"EXECUTE": 2, "DRY_RUN": 1},
        "status_counts": {"SUCCEEDED": 2, "BLOCKED": 1},
        "dry_run_count": 1,
        "execute_count": 2,
        "succeeded_count": 2,
        "blocked_count": 1,
        "failed_count": 0,
        "operator_attention_count": 1,
        "total_deleted_artifacts": 1,
        "total_deleted_storage_files": 2,
        "latest_checked_at": "2026-09-01T02:50:00Z",
    }
    assert projection["items"][0]["retention_execution_id"] == (
        "retention-execute-0409"
    )
    assert projection["items"][0]["execution_payload_hash"] == "a" * 64
    assert projection["items"][0]["metadata"]["scheduled_batch_window"] == {
        "start_local_time": "02:00",
        "end_local_time": "05:00",
    }
    assert projection["source_status"]["history_loaded"] is True
    assert projection["operator_guidance"]["metadata_only"] is True
    assert projection["request_trace_id"] == TRACE_ID
    assert "storage_ref" not in str(projection)
    assert "'execution':" not in str(projection)


def test_artifact_operation_retention_history_projection_handles_sparse_edges() -> None:
    projection = build_artifact_operation_retention_history_projection(
        collection={
            "filter": "not-a-mapping",
            "count": "bad",
            "limit": None,
            "items": [
                {
                    "retention_execution_id": "sparse-history",
                    "mode": "dry-run",
                    "execution_status": "failed",
                    "deleted_counts": "bad",
                    "requested_by": "bad",
                    "metadata": {"raw": "ignored"},
                    "execution_payload_hash": None,
                },
                "not-a-mapping",
            ],
        },
        source_errors=[
            AeArtifactOperationsError(
                error_code="ag.optional_retention_history_warning",
                detail="partial retention history source warning",
                status_code=503,
            )
        ],
    )

    assert projection["projection_status"] == "DEGRADED"
    assert projection["filter"] == {}
    assert projection["count"] == 0
    assert projection["items"][0]["mode"] == "DRY_RUN"
    assert projection["items"][0]["execution_status"] == "FAILED"
    assert projection["items"][0]["deleted_counts"] == {}
    assert projection["summary"] == summarize_artifact_retention_history_operations(
        projection["items"]
    )
    assert projection["summary"]["operator_attention_count"] == 1
    assert projection["source_status"]["errors"][0]["error_code"] == (
        "ag.optional_retention_history_warning"
    )


def test_artifact_operation_retention_batch_projection_summarizes_and_redacts() -> None:
    projection = build_artifact_operation_retention_batch_projection(
        plan=artifact_retention_batch_plan_payload(),
        source_client=InMemoryAeArtifactOperationsClient(),
        request_trace_id=TRACE_ID,
    )

    assert projection["projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_RETENTION_BATCH_PROJECTION_SCHEMA_VERSION
    )
    assert projection["operation_type"] == "ae_artifact_retention_batch_plan"
    assert projection["projection_status"] == "READY"
    assert projection["plan"]["plan_status"] == "READY"
    assert projection["plan"]["mode"] == "DRY_RUN"
    assert projection["plan"]["schedule"]["scheduler"] == {
        "daemon_enabled": False,
    }
    assert projection["plan"]["schedule"]["ownership"] == {
        "system_of_record": "nex-ae-api",
    }
    assert projection["plan"]["selected_candidates"][0] == {
        "artifact_retention_batch_candidate_schema_version": (
            "ae_artifact_retention_batch_candidate.v1"
        ),
        "selection_order": 1,
        "artifact_id": ARTIFACT_ID,
        "display_title": "Generated report",
        "artifact_status": "DELETED",
        "logical_purged_at": "2026-07-31T00:00:00Z",
        "purge_eligible_at": "2026-08-30T00:00:00Z",
        "age_days_after_logical_purge": 32,
        "version_count": 1,
        "file_count": 2,
        "link_count": 4,
        "render_job_count": 1,
        "planned_action": "retention_purge_dry_run",
        "execution_mode": "DRY_RUN",
        "dry_run": True,
    }
    assert projection["summary"] == {
        "plan_status": "READY",
        "scheduler_status": "DISABLED",
        "candidate_count": 2,
        "selected_count": 1,
        "unselected_count": 1,
        "estimated_deleted_artifacts": 1,
        "estimated_deleted_storage_files": 2,
        "operator_attention_required": True,
        "dispatch_available": True,
        "latest_checked_at": "2026-09-01T02:30:00Z",
    }
    assert projection["source_status"]["plan_loaded"] is True
    assert projection["operator_guidance"]["ag_direct_database_write_allowed"] is False
    assert projection["request_trace_id"] == TRACE_ID
    assert "storage_ref" not in str(projection)
    assert "PRIVATE_MARKDOWN" not in str(projection)
    assert "nuri1004" not in str(projection)


def test_artifact_operation_retention_batch_projection_handles_sparse_edges() -> None:
    projection = build_artifact_operation_retention_batch_projection(
        plan={
            "schedule": "not-a-mapping",
            "candidate_filter": "not-a-mapping",
            "mode": "execute",
            "plan_status": "noop",
            "candidate_count": "bad",
            "selected_count": "0",
            "estimated_deleted_counts": "bad",
            "selected_candidates": [
                {
                    "artifact_id": "sparse-batch",
                    "artifact_status": "deleted",
                    "execution_mode": None,
                    "dry_run": False,
                },
                "not-a-mapping",
            ],
            "requested_by": "bad",
        },
        source_errors=[
            AeArtifactOperationsError(
                error_code="ag.optional_retention_batch_warning",
                detail="partial retention batch source warning",
                status_code=503,
            )
        ],
    )

    assert projection["projection_status"] == "DEGRADED"
    assert projection["plan"]["schedule"] == {}
    assert projection["plan"]["candidate_filter"] == {}
    assert projection["plan"]["mode"] == "EXECUTE"
    assert projection["plan"]["plan_status"] == "NOOP"
    assert projection["plan"]["candidate_count"] == 0
    assert projection["plan"]["selected_candidates"][0]["artifact_status"] == "DELETED"
    assert projection["plan"]["selected_candidates"][0]["dry_run"] is False
    assert projection["summary"] == summarize_artifact_retention_batch_operations(
        projection["plan"]
    )
    assert projection["summary"]["operator_attention_required"] is False
    assert projection["summary"]["dispatch_available"] is False
    assert projection["source_status"]["plan_loaded"] is False
    assert projection["source_status"]["errors"][0]["error_code"] == (
        "ag.optional_retention_batch_warning"
    )


def test_artifact_operation_retention_scheduled_job_projection_summarizes_and_redacts() -> (
    None
):
    projection = build_artifact_operation_retention_scheduled_job_projection(
        collection=artifact_retention_scheduled_job_collection_payload(),
        source_client=InMemoryAeArtifactOperationsClient(),
        request_trace_id=TRACE_ID,
    )

    first_item = projection["items"][0]

    assert projection["projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_RETENTION_SCHEDULED_JOB_PROJECTION_SCHEMA_VERSION
    )
    assert projection["operation_type"] == "ae_artifact_retention_scheduled_jobs"
    assert projection["projection_status"] == "READY"
    assert projection["filter"] == {
        "tenant_id": "tenant-0409",
        "workspace_id": "workspace-0409",
        "owner_user_id": "user-0409",
        "status": None,
        "limit": 20,
    }
    assert first_item["status"] == "QUEUED"
    assert first_item["job_type"] == "ae.artifact_retention.scheduled_execution"
    assert first_item["subject_ref"] == {
        "type": "ae.artifact_retention.scheduled_execution",
        "id": "command-job-retention-scheduled-0409",
    }
    assert first_item["links"] == {
        "ae_retention_batch_plan": "/api/v1/artifact-retention/batch-plan",
        "ae_retention_purge": "/api/v1/artifact-retention/purge",
        "ae_retention_history": "/api/v1/artifact-retention/executions",
    }
    assert first_item["payload"]["execution_mode"] == "DRY_RUN"
    assert first_item["payload"]["command_summary"] == {
        "command_status": "READY",
        "trigger_type": "scheduler_tick",
        "scheduler_status": "DISABLED",
        "execution_mode": "DRY_RUN",
        "candidate_count": 2,
        "selected_count": 1,
        "estimated_deleted_artifacts": 1,
        "estimated_deleted_storage_files": 2,
        "command_created_at": "2026-09-01T02:15:00Z",
        "next_action": "Review dry-run evidence before enabling deletes.",
    }
    assert "scheduled_command" not in first_item["payload"]
    assert projection["summary"] == {
        "job_count": 3,
        "active_count": 1,
        "queued_count": 1,
        "running_count": 0,
        "terminal_count": 2,
        "failed_count": 1,
        "retryable_failed_count": 1,
        "dry_run_job_count": 3,
        "selected_artifact_count": 4,
        "estimated_deleted_artifacts": 4,
        "estimated_deleted_storage_files": 8,
        "operator_attention_required": True,
        "latest_updated_at": "2026-09-01T02:18:00Z",
    }
    assert projection["source_status"]["jobs_loaded"] is True
    assert projection["operator_guidance"]["ag_direct_database_write_allowed"] is False
    assert projection["operator_guidance"]["ag_direct_job_enqueue_allowed"] is False
    assert projection["request_trace_id"] == TRACE_ID
    assert "storage_ref" not in str(projection)
    assert "DATABASE_URL_SHOULD_NOT_LEAK" not in str(projection)
    assert "nuri1004" not in str(projection)


def test_artifact_operation_retention_scheduled_job_projection_handles_sparse_edges() -> (
    None
):
    projection = build_artifact_operation_retention_scheduled_job_projection(
        collection={
            "filter": "bad",
            "count": "bad",
            "limit": "bad",
            "items": [
                {
                    "job_id": "sparse-scheduled-job",
                    "job_type": "ae.artifact_retention.scheduled_execution",
                    "status": "failed",
                    "retryable": True,
                    "payload": "bad",
                    "links": {"ae_retention_purge": "/unsafe/private"},
                },
                "not-a-mapping",
            ],
        },
        source_errors=[
            AeArtifactOperationsError(
                error_code="ag.optional_retention_scheduled_job_warning",
                detail="partial scheduled job source warning",
                status_code=503,
            )
        ],
    )

    assert projection["projection_status"] == "DEGRADED"
    assert projection["filter"] == {}
    assert projection["count"] == 0
    assert projection["limit"] == 0
    assert projection["items"][0]["status"] == "FAILED"
    assert projection["items"][0]["payload"] == {}
    assert projection["items"][0]["links"] == {}
    assert projection[
        "summary"
    ] == summarize_artifact_retention_scheduled_job_operations(projection["items"])
    assert projection["summary"]["failed_count"] == 1
    assert projection["summary"]["retryable_failed_count"] == 1
    assert projection["summary"]["operator_attention_required"] is True
    assert projection["source_status"]["jobs_loaded"] is False
    assert projection["source_status"]["errors"][0]["error_code"] == (
        "ag.optional_retention_scheduled_job_warning"
    )


def test_artifact_operation_retention_scheduled_dispatch_projection_summarizes_and_redacts() -> (
    None
):
    dispatch_request = {
        "tenant_id": "tenant-0409",
        "workspace_id": "workspace-0409",
        "owner_user_id": "user-0409",
        "retention_days": 30,
        "as_of": "2026-09-01T00:00:00Z",
        "scan_limit": 20,
        "max_delete_count": 1,
        "checked_at": "2026-09-01T02:30:00Z",
        "trigger_type": "operator-dispatch",
        "requested_at": "2026-09-01T02:35:00Z",
        "idempotency_key": "dispatch-idem-0409",
        "confirm_dispatch": True,
        "database_url": "DATABASE_URL_SHOULD_NOT_LEAK",
    }
    projection = build_artifact_operation_retention_scheduled_dispatch_projection(
        dispatch_request=dispatch_request,
        batch_plan=artifact_retention_batch_plan_payload(),
        dispatch_response=artifact_retention_scheduled_dispatch_response_payload(),
        source_client=InMemoryAeArtifactOperationsClient(),
        request_trace_id=TRACE_ID,
    )

    assert projection["projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_RETENTION_SCHEDULED_DISPATCH_SCHEMA_VERSION
    )
    assert projection["operation_type"] == "ae_artifact_retention_scheduled_dispatch"
    assert projection["dispatch_request"] == {
        "tenant_id": "tenant-0409",
        "workspace_id": "workspace-0409",
        "owner_user_id": "user-0409",
        "retention_days": 30,
        "as_of": "2026-09-01T00:00:00Z",
        "scan_limit": 20,
        "max_delete_count": 1,
        "checked_at": "2026-09-01T02:30:00Z",
        "trigger_type": "operator_dispatch",
        "requested_at": "2026-09-01T02:35:00Z",
        "idempotency_key": "dispatch-idem-0409",
        "confirm_dispatch": True,
    }
    assert projection["dispatch_response"]["enqueue_status"] == "ENQUEUED"
    assert projection["dispatch_response"]["queue_admission"] == {
        "queue_service_id": "nex-ae-api",
        "queue_backend": "service_job_queue",
        "target_job_type": "ae.artifact_retention.scheduled_execution",
        "job_enqueued": True,
        "worker_execution_performed": False,
        "scheduler_daemon_started": False,
        "physical_delete_automation_enabled": False,
    }
    assert projection["summary"] == summarize_artifact_retention_scheduled_dispatch(
        batch_plan=projection["batch_plan"],
        dispatch_response=projection["dispatch_response"],
    )
    assert projection["summary"]["dispatch_available"] is True
    assert projection["summary"]["job_enqueued"] is True
    assert projection["summary"]["job_status"] == "QUEUED"
    assert projection["source_status"]["dispatch_response_loaded"] is True
    assert projection["operator_guidance"]["confirm_dispatch_required"] is True
    assert projection["operator_guidance"]["ag_direct_job_enqueue_allowed"] is False
    assert "execution_request" not in str(projection)
    assert "storage_ref" not in str(projection)
    assert "DATABASE_URL_SHOULD_NOT_LEAK" not in str(projection)
    assert "nuri1004" not in str(projection)


def test_artifact_operation_retention_scheduled_dispatch_projection_handles_sparse_edges() -> (
    None
):
    projection = build_artifact_operation_retention_scheduled_dispatch_projection(
        dispatch_request={
            "tenant_id": "tenant-0409",
            "workspace_id": "workspace-0409",
            "owner_user_id": "user-0409",
            "scan_limit": "bad",
            "max_delete_count": "bad",
            "trigger_type": "bad",
            "confirm_dispatch": False,
        },
        batch_plan={
            "mode": "dry-run",
            "plan_status": "noop",
            "selected_count": "0",
        },
        dispatch_response=[],
        source_errors=[
            AeArtifactOperationsError(
                error_code="ag.optional_retention_scheduled_dispatch_warning",
                detail="partial scheduled dispatch source warning",
                status_code=503,
            )
        ],
    )

    assert projection["projection_status"] == "DEGRADED"
    assert projection["dispatch_request"]["trigger_type"] is None
    assert projection["dispatch_request"]["confirm_dispatch"] is False
    assert projection["dispatch_response"] == {}
    assert projection["summary"]["dispatch_available"] is False
    assert projection["summary"]["job_enqueued"] is False
    assert projection["summary"]["job_status"] is None
    assert projection["source_status"]["dispatch_response_loaded"] is False
    assert projection["source_status"]["errors"][0]["error_code"] == (
        "ag.optional_retention_scheduled_dispatch_warning"
    )


def test_artifact_operation_retention_daemon_projection_summarizes_and_redacts() -> (
    None
):
    dispatch = artifact_retention_scheduler_daemon_dispatch_payload()
    dispatch["tick_once_result"] = {
        "tick_once_result_schema_version": (
            "ae_artifact_retention_scheduler_tick_once_result.v1"
        ),
        "tick_once_result_id": "tick-once-result-0523",
        "service_id": "nex-ae-api",
        "scheduler_id": "ae-artifact-retention-scheduler",
        "lease_owner_id": "ae-retention-manual-once",
        "run_at": "2026-09-01T02:35:00Z",
        "result_status": "SUCCEEDED",
        "skip_reason": None,
        "batch_plan": artifact_retention_batch_plan_payload(),
        "metadata": {
            "metadata_only": True,
            "persistence_endpoint_included": False,
            "storage_locator_included": False,
            "artifact_payload_included": False,
            "execution_payload_included": False,
            "control_plan_ready": True,
            "tick_once_dispatched": True,
            "lease_acquired_before_tick": True,
            "lease_released": True,
            "job_enqueued": True,
            "worker_executed": True,
            "scheduler_daemon_started": False,
            "continuous_loop_started": False,
            "physical_delete_automation_enabled": False,
        },
    }

    projection = build_artifact_operation_retention_daemon_projection(
        daemon_config=artifact_retention_scheduler_daemon_config_payload(),
        dispatch_response=dispatch,
        source_client=InMemoryAeArtifactOperationsClient(),
        request_trace_id=TRACE_ID,
    )

    assert projection["projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_RETENTION_DAEMON_PROJECTION_SCHEMA_VERSION
    )
    assert projection["operation_type"] == "ae_artifact_retention_scheduler_daemon"
    assert projection["projection_status"] == "READY"
    assert projection["daemon_config"]["runtime"]["scheduler_daemon_started"] is False
    assert projection["daemon_config"]["supported_actions"][1] == {
        "action": "manual_tick_once",
        "decision_status": "READY",
        "requires_lease": True,
        "runs_tick_once": True,
        "starts_daemon": False,
        "starts_continuous_loop": False,
        "block_reason": None,
    }
    assert projection["dispatch_response"]["control_plan"]["action"] == (
        "manual_tick_once"
    )
    assert projection["dispatch_response"]["tick_once_result"] == {
        "tick_once_result_schema_version": (
            "ae_artifact_retention_scheduler_tick_once_result.v1"
        ),
        "tick_once_result_id": "tick-once-result-0523",
        "service_id": "nex-ae-api",
        "scheduler_id": "ae-artifact-retention-scheduler",
        "lease_owner_id": "ae-retention-manual-once",
        "run_at": "2026-09-01T02:35:00Z",
        "result_status": "SUCCEEDED",
        "skip_reason": None,
        "metadata": {
            "metadata_only": True,
            "persistence_endpoint_included": False,
            "storage_locator_included": False,
            "artifact_payload_included": False,
            "execution_payload_included": False,
            "control_plan_ready": True,
            "tick_once_dispatched": True,
            "lease_acquired_before_tick": True,
            "lease_released": True,
            "job_enqueued": True,
            "worker_executed": True,
            "scheduler_daemon_started": False,
            "continuous_loop_started": False,
            "physical_delete_automation_enabled": False,
        },
    }
    assert projection["summary"] == summarize_artifact_retention_daemon_operations(
        daemon_config=projection["daemon_config"],
        dispatch_response=projection["dispatch_response"],
    )
    assert projection["summary"]["manual_tick_once_available"] is True
    assert projection["summary"]["start_daemon_available"] is False
    assert projection["summary"]["last_dispatch_job_enqueued"] is True
    assert projection["source_status"]["daemon_config_loaded"] is True
    assert projection["source_status"]["dispatch_response_loaded"] is True
    assert projection["operator_guidance"]["manual_tick_once_requires_ae_api"] is True
    assert projection["operator_guidance"]["ag_direct_database_write_allowed"] is False
    assert "batch_plan" not in str(projection["dispatch_response"]["tick_once_result"])
    assert "storage_ref" not in str(projection)
    assert "DATABASE_URL_SHOULD_NOT_LEAK" not in str(projection)
    assert "nuri1004" not in str(projection)


def test_artifact_operation_retention_daemon_projection_handles_sparse_edges() -> None:
    config = artifact_retention_scheduler_daemon_config_payload(
        job_queue_available=False,
        lease_available=True,
    )
    config["runtime"] = "bad"
    config["lease_repository"] = "bad"
    config["supported_actions"] = [
        {"action": "unknown", "decision_status": "READY"},
        "not-a-mapping",
    ]
    dispatch = artifact_retention_scheduler_daemon_dispatch_payload(
        action="start_daemon",
        dispatch_status="BLOCKED",
    )
    dispatch["control_plan"] = {
        **dispatch["control_plan"],
        "action": "bad",
        "requested_by": "bad",
        "execution_plan": "bad",
        "guardrails": "bad",
        "metadata": "bad",
    }
    projection = build_artifact_operation_retention_daemon_projection(
        daemon_config=config,
        dispatch_response=dispatch,
        source_errors=[
            AeArtifactOperationsError(
                error_code="ag.optional_daemon_warning",
                detail="partial daemon source warning",
                status_code=503,
            )
        ],
    )

    assert projection["projection_status"] == "DEGRADED"
    assert projection["daemon_config"]["runtime"] == {}
    assert projection["daemon_config"]["lease_repository"] == {}
    assert projection["daemon_config"]["supported_actions"][0]["action"] is None
    assert projection["dispatch_response"]["control_plan"]["action"] is None
    assert projection["dispatch_response"]["control_plan"]["requested_by"] == {}
    assert projection["dispatch_response"]["control_plan"]["execution_plan"] == {}
    assert projection["dispatch_response"]["tick_once_result"] == {}
    assert projection["summary"]["manual_tick_once_decision_status"] == "BLOCKED"
    assert projection["summary"]["manual_tick_once_available"] is False
    assert projection["summary"]["operator_attention_required"] is True
    assert projection["source_status"]["daemon_config_loaded"] is False
    assert projection["source_status"]["dispatch_response_loaded"] is False
    assert projection["source_status"]["errors"][0]["error_code"] == (
        "ag.optional_daemon_warning"
    )
    assert artifact_operations._project_retention_scheduler_daemon_config([]) == {}
    assert artifact_operations._project_retention_scheduler_daemon_runtime([]) == {}
    assert (
        artifact_operations._project_retention_scheduler_daemon_lease_repository([])
        == {}
    )
    assert artifact_operations._project_retention_scheduler_daemon_guardrails([]) == {}
    assert artifact_operations._project_retention_scheduler_daemon_metadata([]) == {}
    assert (
        artifact_operations._project_retention_scheduler_daemon_dispatch_response([])
        == {}
    )
    assert artifact_operations._project_retention_scheduler_daemon_control_plan([]) == {}
    assert artifact_operations._project_retention_scheduler_tick_once_summary([]) == {}


def test_artifact_operation_retention_automation_projection_summarizes_and_redacts() -> (
    None
):
    projection = build_artifact_operation_retention_automation_projection(
        plan=artifact_retention_batch_plan_payload(),
        scheduled_jobs=artifact_retention_scheduled_job_collection_payload(),
        history=artifact_retention_history_collection_payload(),
        daemon_config=artifact_retention_scheduler_daemon_config_payload(),
        source_client=InMemoryAeArtifactOperationsClient(),
        request_trace_id=TRACE_ID,
    )

    assert projection["projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_RETENTION_AUTOMATION_PROJECTION_SCHEMA_VERSION
    )
    assert projection["operation_type"] == "ae_artifact_retention_automation"
    assert projection["projection_status"] == "READY"
    assert projection["batch_plan"]["plan"]["plan_id"] == "retention-batch-plan-0409"
    assert projection["scheduled_jobs"]["summary"]["job_count"] == 3
    assert projection["history"]["summary"]["blocked_count"] == 1
    assert projection["scheduler_daemon"]["summary"]["manual_tick_once_available"] is True
    assert projection["scheduler_daemon"]["summary"]["start_daemon_available"] is False
    assert projection["summary"] == {
        "safety_status": "FAILED_ATTENTION",
        "dispatch_available": True,
        "batch_plan_status": "READY",
        "scheduler_status": "DISABLED",
        "scheduled_job_count": 3,
        "active_job_count": 1,
        "queued_job_count": 1,
        "running_job_count": 0,
        "failed_job_count": 1,
        "retryable_failed_job_count": 1,
        "history_count": 3,
        "history_blocked_count": 1,
        "history_failed_count": 0,
        "history_execute_count": 2,
        "history_dry_run_count": 1,
        "daemon_scheduler_id": "ae-artifact-retention-scheduler",
        "daemon_manual_tick_once_available": True,
        "daemon_start_daemon_available": False,
        "daemon_scheduler_daemon_started": False,
        "daemon_continuous_loop_started": False,
        "daemon_lease_repository_available": True,
        "daemon_job_queue_available": True,
        "daemon_operator_attention_required": False,
        "approval_blocked_count": 0,
        "delete_guard_blocked_count": 1,
        "selected_artifact_count": 1,
        "estimated_deleted_artifacts": 1,
        "estimated_deleted_storage_files": 2,
        "total_deleted_artifacts": 1,
        "total_deleted_storage_files": 2,
        "operator_attention_required": True,
        "automated_execute_enabled": False,
        "physical_delete_automation_enabled": False,
        "physical_delete_operator_approval_required": True,
        "latest_activity_at": "2026-09-01T02:50:00Z",
    }
    assert projection["source_status"]["batch_plan_loaded"] is True
    assert projection["source_status"]["scheduled_jobs_loaded"] is True
    assert projection["source_status"]["history_loaded"] is True
    assert projection["source_status"]["daemon_config_loaded"] is True
    assert projection["operator_guidance"]["ae_daemon_config_route"] == (
        "/api/v1/artifact-retention/scheduler-daemon-config"
    )
    assert projection["operator_guidance"]["ag_daemon_operations_route"] == (
        "/admin/v1/operations/artifact-retention/scheduler-daemon"
    )
    assert projection["operator_guidance"]["ag_direct_database_write_allowed"] is False
    assert projection["operator_guidance"]["ag_direct_job_enqueue_allowed"] is False
    assert (
        projection["operator_guidance"]["physical_delete_operator_approval_required"]
        is True
    )
    assert projection["request_trace_id"] == TRACE_ID
    assert "storage_ref" not in str(projection)
    assert "DATABASE_URL_SHOULD_NOT_LEAK" not in str(projection)
    assert "nuri1004" not in str(projection)


def test_artifact_operation_retention_automation_projection_handles_sparse_edges() -> (
    None
):
    projection = build_artifact_operation_retention_automation_projection(
        plan={
            "mode": "dry-run",
            "plan_status": "noop",
            "checked_at": "2026-09-01T02:00:00Z",
        },
        scheduled_jobs={
            "filter": "bad",
            "count": "bad",
            "limit": "bad",
            "items": [
                {
                    "job_id": "sparse-automation-job",
                    "job_type": "ae.artifact_retention.scheduled_execution",
                    "status": "running",
                    "payload": {},
                },
                "not-a-mapping",
            ],
        },
        history={
            "filter": "bad",
            "count": "bad",
            "limit": "bad",
            "items": [
                {
                    "retention_execution_id": "approval-blocked",
                    "mode": "execute",
                    "execution_status": "blocked",
                    "blocked_reason": "operator_approval_required",
                    "deleted_counts": "bad",
                    "checked_at": "2026-09-01T02:05:00Z",
                }
            ],
        },
        source_errors=[
            AeArtifactOperationsError(
                error_code="ag.optional_retention_automation_warning",
                detail="partial automation source warning",
                status_code=503,
            )
        ],
    )

    assert projection["projection_status"] == "DEGRADED"
    assert projection["batch_plan"]["plan"]["plan_status"] == "NOOP"
    assert projection["scheduled_jobs"]["filter"] == {}
    assert projection["scheduled_jobs"]["items"][0]["status"] == "RUNNING"
    assert projection["history"]["items"][0]["blocked_reason"] == (
        "operator_approval_required"
    )
    assert projection["summary"] == summarize_artifact_retention_automation_operations(
        batch_plan=projection["batch_plan"]["plan"],
        scheduled_jobs=projection["scheduled_jobs"]["items"],
        history=projection["history"]["items"],
    )
    assert projection["summary"]["safety_status"] == "OPERATOR_ATTENTION"
    assert projection["summary"]["approval_blocked_count"] == 1
    assert projection["summary"]["daemon_manual_tick_once_available"] is False
    assert projection["summary"]["daemon_operator_attention_required"] is False
    assert projection["summary"]["latest_activity_at"] == "2026-09-01T02:05:00Z"
    assert projection["source_status"]["batch_plan_loaded"] is False
    assert projection["source_status"]["scheduled_jobs_loaded"] is False
    assert projection["source_status"]["history_loaded"] is False
    assert projection["source_status"]["daemon_config_loaded"] is False
    assert projection["source_status"]["errors"][0]["error_code"] == (
        "ag.optional_retention_automation_warning"
    )
    idle_summary = summarize_artifact_retention_automation_operations(
        batch_plan={
            "mode": "DRY_RUN",
            "plan_status": "NOOP",
            "selected_count": 0,
            "estimated_deleted_counts": {},
        },
        scheduled_jobs=[],
        history=[],
    )
    no_status_job_summary = summarize_artifact_retention_scheduled_job_operations(
        [{"status": None, "payload": "bad"}]
    )
    assert idle_summary["safety_status"] == "IDLE"
    assert idle_summary["operator_attention_required"] is False
    assert idle_summary["daemon_scheduler_id"] is None
    assert no_status_job_summary["job_count"] == 1
    assert no_status_job_summary["active_count"] == 0


def test_artifact_operation_collection_projection_handles_sparse_values() -> None:
    degraded = build_artifact_operation_collection_projection(
        collection={
            "filter": "not-a-mapping",
            "count": "not-a-number",
            "limit": None,
            "items": [
                {
                    "artifact_id": "artifact-sparse",
                    "artifact_status": "FAILED",
                    "downloadable_formats": "bad",
                    "previewable_formats": [],
                    "routes": {"detail": "/unsafe"},
                },
                "not-a-mapping",
            ],
        },
        source_errors=[
            AeArtifactOperationsError(
                error_code="ag.optional_collection_warning",
                detail="partial source warning",
                status_code=503,
            )
        ],
    )

    assert degraded["projection_status"] == "DEGRADED"
    assert degraded["filter"] == {}
    assert degraded["count"] == 0
    assert degraded["summary"] == summarize_artifact_operation_collection(
        degraded["items"]
    )
    assert degraded["items"][0]["routes"] == {}
    assert degraded["source_status"]["errors"][0]["error_code"] == (
        "ag.optional_collection_warning"
    )


def test_artifact_operation_lifecycle_projection_summarizes_ready_state() -> None:
    projection = build_artifact_operation_lifecycle_projection(
        artifact=artifact_record(include_private=True),
        source_client=InMemoryAeArtifactOperationsClient(),
        request_trace_id=TRACE_ID,
    )

    assert projection["projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_LIFECYCLE_PROJECTION_SCHEMA_VERSION
    )
    assert projection["operation_type"] == "ae_artifact_lifecycle"
    assert projection["projection_status"] == "READY"
    assert projection["artifact"]["routes"] == {
        "detail": f"/api/v1/artifacts/{ARTIFACT_ID}",
        "lifecycle_action": f"/api/v1/artifacts/{ARTIFACT_ID}/lifecycle-actions",
    }
    assert projection["lifecycle"]["metadata_only"] is True
    assert projection["lifecycle"]["physical_delete_allowed"] is False
    assert projection["summary"] == {
        "artifact_status": "READY",
        "enabled_action_count": 2,
        "blocked_action_count": 1,
        "enabled_actions": ["ARCHIVE", "MARK_DELETED"],
        "blocked_actions": ["RESTORE"],
        "archive_available": True,
        "restore_available": False,
        "mark_deleted_available": True,
        "is_hidden_from_active_library": False,
        "is_logically_deleted": False,
        "metadata_only": True,
    }
    assert (
        summarize_artifact_operation_lifecycle(
            projection["artifact"],
            projection["lifecycle"]["actions"],
        )
        == projection["summary"]
    )
    assert projection["request_trace_id"] == TRACE_ID
    assert "SECRET" not in str(projection)
    assert "raw_comment" not in str(projection)
    assert "/data/nex-platform" not in str(projection)


@pytest.mark.parametrize(
    ("status", "enabled_actions", "blocked_actions", "idempotent_action"),
    [
        ("ARCHIVED", ["ARCHIVE", "RESTORE", "MARK_DELETED"], [], "ARCHIVE"),
        ("DELETED", ["RESTORE", "MARK_DELETED"], ["ARCHIVE"], "MARK_DELETED"),
        ("FAILED", ["ARCHIVE", "MARK_DELETED"], ["RESTORE"], None),
    ],
)
def test_artifact_operation_lifecycle_projection_status_matrix(
    status: str,
    enabled_actions: list[str],
    blocked_actions: list[str],
    idempotent_action: str | None,
) -> None:
    projection = build_artifact_operation_lifecycle_projection(
        artifact={**artifact_record(include_private=False), "artifact_status": status}
    )
    actions = {
        action["action"]: action for action in projection["lifecycle"]["actions"]
    }

    assert projection["summary"]["enabled_actions"] == enabled_actions
    assert projection["summary"]["blocked_actions"] == blocked_actions
    assert projection["summary"]["is_hidden_from_active_library"] is (
        status in {"ARCHIVED", "DELETED"}
    )
    assert projection["summary"]["is_logically_deleted"] is (status == "DELETED")
    if idempotent_action:
        assert actions[idempotent_action]["idempotent"] is True
    for action in enabled_actions:
        assert actions[action]["route"].endswith("/lifecycle-actions")
        assert actions[action]["reason_code"] == "user_requested"


def test_artifact_operation_lifecycle_projection_degrades_source_contract_edges() -> (
    None
):
    rendering = build_artifact_operation_lifecycle_projection(
        artifact={
            **artifact_record(include_private=False),
            "artifact_status": "RENDERING",
            "comment_text": "raw private operator comment",
        }
    )
    unknown = build_artifact_operation_lifecycle_projection(
        artifact={
            **artifact_record(include_private=False),
            "artifact_id": None,
            "artifact_status": "UNKNOWN",
        },
        source_errors=[
            AeArtifactOperationsError(
                error_code="ag.ae_artifact_lifecycle_source_warning",
                detail="source contract changed",
                status_code=503,
            )
        ],
    )

    assert rendering["projection_status"] == "DEGRADED"
    assert rendering["issues"][0]["subject"] == "rendering_artifact"
    assert all(
        action["enabled"] is False for action in rendering["lifecycle"]["actions"]
    )
    assert unknown["projection_status"] == "DEGRADED"
    assert {issue["subject"] for issue in unknown["issues"]} == {
        "artifact_status",
        "artifact_id",
    }
    assert unknown["source_status"]["errors"][0]["error_code"] == (
        "ag.ae_artifact_lifecycle_source_warning"
    )
    assert all(action["route"] is None for action in unknown["lifecycle"]["actions"])
    assert artifact_operations._artifact_lifecycle_target(
        current_status="READY",
        action="PURGE",
    ) == (None, "artifact_lifecycle_action_unsupported", False)


def test_artifact_operation_projection_handles_sparse_values_and_errors() -> None:
    projection = build_artifact_operation_detail_projection(
        artifact={
            "artifact_id": ARTIFACT_ID,
            "artifact_type": "summary",
            "artifact_status": "DRAFT",
            "versions": "not-a-list",
            "render_jobs": "not-a-list",
            "files": "not-a-list",
            "links": "not-a-list",
            "source_refs": "not-a-list",
            "owner_actor_ref": "not-a-mapping",
            "workspace_ref": "not-a-mapping",
        },
        source_errors=[
            AeArtifactOperationsError(
                error_code="ag.ae_artifact_source_request_failed",
                detail="optional handoff failed",
                status_code=503,
            )
        ],
    )

    assert projection["projection_status"] == "DEGRADED"
    assert projection["summary"] == summarize_artifact_operation_detail(
        projection["artifact"],
        None,
        [],
    )
    assert projection["artifact"]["owner_scope"] == {
        "tenant_id": None,
        "user_id": None,
        "actor_type": None,
    }
    assert projection["source_status"]["errors"][0]["status_code"] == 503


def test_artifact_operation_projection_helper_edges() -> None:
    record = artifact_record(include_private=False)
    record["artifact_handoff_id"] = "handoff-top-level"
    record["handoff_ref"] = {"artifact_handoff_id": "handoff-nested"}
    record["source_refs"][0]["quality_summary"] = "not-a-mapping"
    record["versions"][0]["validation_snapshot"] = "not-a-mapping"
    record["render_jobs"][0]["failure_summary"] = "not-a-mapping"
    record["files"].append({"artifact_file_id": "empty-file", "storage_ref": None})
    record["links"].append({"artifact_link_id": "empty-link", "link_route": None})
    ref = chat_artifact_ref()
    ref["download_routes"] = "not-a-mapping"
    ref["actions"] = "not-a-mapping"
    ref["preview_route"] = None

    projection = build_artifact_operation_detail_projection(
        artifact=record,
        chat_artifact_refs=[ref],
    )

    assert projection["artifact"]["artifact_handoff_id"] == "handoff-top-level"
    assert projection["artifact"]["source_refs"][0]["quality_summary"] == {}
    assert projection["artifact"]["versions"][0]["validation_snapshot"] == {}
    assert projection["artifact"]["render_jobs"][0]["failure_summary"] == {}
    assert projection["artifact"]["files"][-1]["storage_ref"] is None
    assert projection["artifact"]["links"][-1]["link_route"] is None
    assert projection["chat_artifact_refs"][0]["download_routes"] == {}
    assert projection["chat_artifact_refs"][0]["actions"] == {}
    assert projection["chat_artifact_refs"][0]["preview_route"] is None
    assert artifact_operations._json_safe_value(
        ["x", {"keep": object(), "drop": None}]
    )[1]["keep"].startswith("<object object")


def test_artifact_operation_projection_redaction_guard_raises() -> None:
    with pytest.raises(ValueError, match="private data"):
        assert_artifact_operation_projection_redacted(
            {"artifact": {"storage_ref": "/data/nex-platform/private.md"}}
        )


def test_in_memory_artifact_operations_client_returns_copies_and_missing_values() -> (
    None
):
    client = artifact_client()
    artifact = client.get_artifact(
        ARTIFACT_ID, request_id=REQUEST_ID, trace_id=TRACE_ID
    )
    refs = client.list_chat_artifact_refs(
        INTERACTION_ID,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    artifact["artifact_status"] = "MUTATED"
    refs[0]["artifact_status"] = "MUTATED"

    assert (
        client.get_artifact("missing", request_id=REQUEST_ID, trace_id=TRACE_ID) is None
    )
    assert (
        client.get_artifact_handoff("missing", request_id=REQUEST_ID, trace_id=TRACE_ID)
        is None
    )
    assert (
        client.list_chat_artifact_refs(
            "missing", request_id=REQUEST_ID, trace_id=TRACE_ID
        )
        == []
    )
    assert client.artifacts[ARTIFACT_ID]["artifact_status"] == "READY"
    assert (
        client.chat_artifact_refs[INTERACTION_ID]["artifact_refs"][0]["artifact_status"]
        == "READY"
    )


def test_in_memory_artifact_operations_client_lists_owner_scoped_collections() -> None:
    ready = artifact_record(include_private=False)
    ready["owner_actor_ref"] = {
        "tenant_id": "tenant-0409",
        "actor_id": "user-0409",
        "actor_type": "user",
    }
    ready["updated_at"] = "2026-08-29T02:00:00Z"
    ready["files"][0]["format"] = "MD"
    ready["links"][0]["link_route"] = "/api/v1/artifact-files/file-0409/preview"
    ready["links"].append(
        {
            "artifact_link_id": "download-link-0409",
            "artifact_file_id": "file-0409",
            "link_type": "download",
            "link_route": "/api/v1/artifact-files/file-0409/download",
        }
    )
    draft = {
        **artifact_record(include_private=False),
        "artifact_id": "artifact-draft-0409",
        "artifact_status": "DRAFT",
        "display_title": "Draft report",
        "updated_at": "2026-08-29T01:00:00Z",
    }
    other_owner = {
        **artifact_record(include_private=False),
        "artifact_id": "artifact-other-owner-0409",
        "owner_actor_ref": {
            "tenant_id": "tenant-0409",
            "actor_id": "user-other",
            "actor_type": "user",
        },
    }
    client = InMemoryAeArtifactOperationsClient(
        artifacts={
            ready["artifact_id"]: ready,
            draft["artifact_id"]: draft,
            other_owner["artifact_id"]: other_owner,
        }
    )

    collection = client.list_artifacts(
        tenant_id="tenant-0409",
        workspace_id="workspace-0409",
        owner_user_id="user-0409",
        status=None,
        limit=10,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    ready_only = client.list_artifacts(
        tenant_id="tenant-0409",
        workspace_id="workspace-0409",
        owner_user_id="user-0409",
        status="ready",
        limit=1,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert collection["count"] == 2
    assert [item["artifact_id"] for item in collection["items"]] == [
        ARTIFACT_ID,
        "artifact-draft-0409",
    ]
    assert collection["items"][0]["downloadable_formats"] == ["MD"]
    assert collection["items"][0]["previewable_formats"] == ["MD"]
    assert ready_only["count"] == 1
    assert ready_only["filter"]["status"] == "READY"
    assert "PRIVATE_MARKDOWN" not in str(collection)


def test_artifact_operation_collection_helper_edges() -> None:
    key = artifact_operations._artifact_collection_cache_key(
        tenant_id="tenant-0409",
        workspace_id="workspace-0409",
        owner_user_id="user-0409",
        status=None,
        limit=20,
    )
    client = InMemoryAeArtifactOperationsClient(
        artifact_collections={key: artifact_collection_payload()}
    )

    cached = client.list_artifacts(
        tenant_id="tenant-0409",
        workspace_id="workspace-0409",
        owner_user_id="user-0409",
        status=None,
        limit=20,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    cached["items"][0]["artifact_id"] = "mutated"

    assert client.artifact_collections[key]["items"][0]["artifact_id"] == ARTIFACT_ID
    assert artifact_operations._collection_limit("many") is None
    assert artifact_operations._collection_limit("0") is None
    assert artifact_operations._collection_limit(None) == 20
    assert artifact_operations._safe_artifact_route_mapping("bad") == {}
    assert artifact_operations._safe_artifact_route(None) is None
    assert artifact_operations._first_mapping([]) == {}
    assert artifact_operations._first_mapping(["bad", {"ok": True}]) == {"ok": True}
    assert artifact_operations._owner_tenant_id({"tenant_id": "tenant-fallback"}) == (
        "tenant-fallback"
    )
    assert artifact_operations._owner_user_id({"owner_user_id": "owner-fallback"}) == (
        "owner-fallback"
    )
    assert artifact_operations._workspace_id(
        {"workspace_id": "workspace-fallback"}
    ) == ("workspace-fallback")
    assert artifact_operations._current_version_no([], "missing") == 0
    assert artifact_operations._latest_render_job_summary([]) == {}
    assert artifact_operations._normalized_retention_mode("dry-run") == "DRY_RUN"
    assert artifact_operations._normalized_retention_mode(None) is None
    assert artifact_operations._normalized_retention_status("blocked") == "BLOCKED"
    assert artifact_operations._normalized_retention_status(None) is None
    assert artifact_operations._normalized_retention_batch_status("ready") == "READY"
    assert artifact_operations._normalized_retention_batch_status(None) is None
    assert artifact_operations._retention_days_filter("many") is None
    assert artifact_operations._retention_days_filter("366") is None
    assert artifact_operations._retention_days_filter(None) is None
    assert artifact_operations._project_retention_batch_plan("bad") == {}
    assert artifact_operations._safe_deleted_counts("bad") == {}
    assert (
        artifact_operations._safe_deleted_counts({"artifacts": "2"})["artifacts"] == 2
    )
    assert (
        artifact_operations._latest_timestamp_text(
            None,
            "2026-09-01T02:00:00Z",
            "2026-09-01T02:05:00Z",
        )
        == "2026-09-01T02:05:00Z"
    )
    assert artifact_operations._latest_timestamp_text(None) is None
    assert (
        artifact_operations._current_version_no(
            [
                {"artifact_version_id": "old", "version_no": 1},
                {"artifact_version_id": "current", "version_no": "2"},
            ],
            "current",
        )
        == 2
    )
    assert (
        artifact_operations._project_lifecycle_action(
            artifact_id=None,
            current_status="READY",
            action="ARCHIVE",
        )["blocked_reason"]
        == "artifact_id_missing"
    )
    assert summarize_artifact_operation_collection(
        [
            {"artifact_status": None, "updated_at": None},
            {"artifact_status": "", "updated_at": "2026-08-28T00:00:00Z"},
        ]
    ) == {
        "item_count": 2,
        "ready_count": 0,
        "draft_count": 0,
        "failed_count": 0,
        "downloadable_count": 0,
        "previewable_count": 0,
        "status_counts": {},
        "latest_updated_at": "2026-08-28T00:00:00Z",
    }
    assert summarize_artifact_retention_history_operations(
        [
            {"mode": None, "execution_status": None, "deleted_counts": None},
            {
                "mode": "",
                "execution_status": "",
                "checked_at": "2026-09-01T01:00:00Z",
            },
        ]
    ) == {
        "item_count": 2,
        "mode_counts": {},
        "status_counts": {},
        "dry_run_count": 0,
        "execute_count": 0,
        "succeeded_count": 0,
        "blocked_count": 0,
        "failed_count": 0,
        "operator_attention_count": 0,
        "total_deleted_artifacts": 0,
        "total_deleted_storage_files": 0,
        "latest_checked_at": "2026-09-01T01:00:00Z",
    }
    assert summarize_artifact_retention_batch_operations(
        {"estimated_deleted_counts": "bad", "plan_status": None}
    ) == {
        "plan_status": None,
        "scheduler_status": None,
        "candidate_count": 0,
        "selected_count": 0,
        "unselected_count": 0,
        "estimated_deleted_artifacts": 0,
        "estimated_deleted_storage_files": 0,
        "operator_attention_required": False,
        "dispatch_available": False,
        "latest_checked_at": None,
    }


def test_in_memory_artifact_operations_client_lists_retention_history() -> None:
    client = artifact_client()
    history = client.list_artifact_retention_executions(
        tenant_id="tenant-0409",
        workspace_id="workspace-0409",
        owner_user_id="user-0409",
        mode=None,
        execution_status=None,
        limit=20,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    execute_history = client.list_artifact_retention_executions(
        tenant_id="tenant-0409",
        workspace_id="workspace-0409",
        owner_user_id="user-0409",
        mode="execute",
        execution_status=None,
        limit=20,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    empty_history = client.list_artifact_retention_executions(
        tenant_id="tenant-0409",
        workspace_id="workspace-0409",
        owner_user_id="user-0409",
        mode=None,
        execution_status="FAILED",
        limit=20,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    history["items"][0]["retention_execution_id"] = "mutated"

    assert (
        client.artifact_retention_history_collections[
            artifact_operations._artifact_retention_history_cache_key(
                tenant_id="tenant-0409",
                workspace_id="workspace-0409",
                owner_user_id="user-0409",
                mode=None,
                execution_status=None,
                limit=20,
            )
        ]["items"][0]["retention_execution_id"]
        == "retention-execute-0409"
    )
    assert execute_history["count"] == 2
    assert execute_history["filter"]["mode"] == "EXECUTE"
    assert empty_history["count"] == 0
    assert empty_history["filter"]["execution_status"] == "FAILED"


def test_in_memory_artifact_operations_client_gets_retention_batch_plan() -> None:
    client = artifact_client()
    cached = client.get_artifact_retention_batch_plan(
        tenant_id="tenant-0409",
        workspace_id="workspace-0409",
        owner_user_id="user-0409",
        retention_days=30,
        as_of="2026-09-01T00:00:00Z",
        scan_limit=20,
        max_delete_count=1,
        checked_at="2026-09-01T02:30:00Z",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    defaulted = client.get_artifact_retention_batch_plan(
        tenant_id="tenant-0409",
        workspace_id="workspace-0409",
        owner_user_id="user-0409",
        retention_days=None,
        as_of=None,
        scan_limit=20,
        max_delete_count=20,
        checked_at=None,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    cached["plan_id"] = "mutated"

    assert (
        client.artifact_retention_batch_plans[
            artifact_operations._artifact_retention_batch_plan_cache_key(
                tenant_id="tenant-0409",
                workspace_id="workspace-0409",
                owner_user_id="user-0409",
                retention_days=30,
                as_of="2026-09-01T00:00:00Z",
                scan_limit=20,
                max_delete_count=1,
                checked_at="2026-09-01T02:30:00Z",
            )
        ]["plan_id"]
        == "retention-batch-plan-0409"
    )
    assert defaulted["plan_status"] == "NOOP"
    assert defaulted["candidate_filter"]["retention_days"] == 30
    assert defaulted["metadata"]["physical_delete_executed"] is False


def test_in_memory_artifact_operations_client_lists_retention_scheduled_jobs() -> None:
    client = artifact_client()
    cached = client.list_artifact_retention_scheduled_jobs(
        tenant_id="tenant-0409",
        workspace_id="workspace-0409",
        owner_user_id="user-0409",
        status=None,
        limit=20,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    running = client.list_artifact_retention_scheduled_jobs(
        tenant_id="tenant-0409",
        workspace_id="workspace-0409",
        owner_user_id="user-0409",
        status="running",
        limit=20,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    empty = client.list_artifact_retention_scheduled_jobs(
        tenant_id="tenant-0409",
        workspace_id="workspace-0409",
        owner_user_id="user-0409",
        status="FAILED",
        limit=20,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    cached["items"][0]["job_id"] = "mutated"

    assert (
        client.artifact_retention_scheduled_job_collections[
            artifact_operations._artifact_retention_scheduled_job_cache_key(
                tenant_id="tenant-0409",
                workspace_id="workspace-0409",
                owner_user_id="user-0409",
                status=None,
                limit=20,
            )
        ]["items"][0]["job_id"]
        == "job-retention-scheduled-0409"
    )
    assert cached["count"] == 3
    assert running["count"] == 1
    assert running["filter"]["status"] == "RUNNING"
    assert running["items"][0]["job_id"] == "job-retention-scheduled-filtered-0409"
    assert empty["count"] == 0
    assert empty["metadata"]["system_of_record"] == AE_ARTIFACT_SOURCE_SERVICE_ID


def test_in_memory_artifact_operations_client_dispatches_retention_scheduled_job() -> (
    None
):
    cached_key = artifact_operations._artifact_retention_scheduled_dispatch_cache_key(
        plan_id="retention-batch-plan-0409",
        trigger_type="operator_dispatch",
        idempotency_key="dispatch-idem-0409",
    )
    client = InMemoryAeArtifactOperationsClient(
        artifact_retention_scheduled_dispatch_results={
            cached_key: artifact_retention_scheduled_dispatch_response_payload()
        }
    )

    cached = client.dispatch_artifact_retention_scheduled_job(
        batch_plan=artifact_retention_batch_plan_payload(),
        trigger_type="operator_dispatch",
        requested_at="2026-09-01T02:35:00Z",
        idempotency_key="dispatch-idem-0409",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    synthesized = (
        InMemoryAeArtifactOperationsClient().dispatch_artifact_retention_scheduled_job(
            batch_plan=artifact_retention_batch_plan_payload(),
            trigger_type="operator_dispatch",
            requested_at="2026-09-01T02:35:00Z",
            idempotency_key=None,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    )
    cached["job_id"] = "mutated"

    assert (
        client.artifact_retention_scheduled_dispatch_results[cached_key]["job_id"]
        == "job-retention-scheduled-0409"
    )
    assert synthesized["enqueue_status"] == "ENQUEUED"
    assert synthesized["job_enqueued"] is True
    assert synthesized["enqueued_job"]["status"] == "QUEUED"
    assert synthesized["enqueued_job"]["payload"]["execution_mode"] == "DRY_RUN"
    assert synthesized["queue_admission"]["worker_execution_performed"] is False
    assert synthesized["queue_admission"]["physical_delete_automation_enabled"] is False


def test_in_memory_artifact_operations_client_gets_and_dispatches_daemon_controls() -> (
    None
):
    cached_key = (
        artifact_operations._artifact_retention_scheduler_daemon_dispatch_cache_key(
            action="manual-tick-once",
            tenant_id="tenant-0409",
            workspace_id="workspace-0409",
            owner_user_id="user-0409",
            idempotency_key="daemon-idem-0522",
        )
    )
    client = InMemoryAeArtifactOperationsClient(
        artifact_retention_scheduler_daemon_config=(
            artifact_retention_scheduler_daemon_config_payload()
        ),
        artifact_retention_scheduler_daemon_dispatch_results={
            cached_key: artifact_retention_scheduler_daemon_dispatch_payload()
        },
    )

    config = client.get_artifact_retention_scheduler_daemon_config(
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    cached = client.dispatch_artifact_retention_scheduler_daemon_control(
        action="manual-tick-once",
        tenant_id="tenant-0409",
        workspace_id="workspace-0409",
        owner_user_id="user-0409",
        retention_days=30,
        as_of="2026-09-01T00:00:00Z",
        scan_limit=20,
        max_delete_count=1,
        requested_at="2026-09-01T02:35:00Z",
        requested_by={"actor_type": "operator", "actor_id": "ag-operator"},
        reason="manual dispatch",
        tick_at=None,
        run_worker=False,
        worker_id=None,
        idempotency_key="daemon-idem-0522",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    fallback = InMemoryAeArtifactOperationsClient()
    default_config = fallback.get_artifact_retention_scheduler_daemon_config(
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    default_dispatch = fallback.dispatch_artifact_retention_scheduler_daemon_control(
        action="unknown",
        tenant_id=None,
        workspace_id=None,
        owner_user_id=None,
        retention_days=None,
        as_of=None,
        scan_limit=None,
        max_delete_count=None,
        requested_at=None,
        requested_by=None,
        reason=None,
        tick_at=None,
        run_worker=False,
        worker_id=None,
        idempotency_key=None,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    cached["scheduler_id"] = "mutated"

    assert config["daemon_config_schema_version"] == (
        "ae_artifact_retention_scheduler_daemon_config.v1"
    )
    assert config["runtime"]["scheduler_daemon_started"] is False
    assert config["supported_actions"][1]["action"] == "manual_tick_once"
    assert (
        client.artifact_retention_scheduler_daemon_dispatch_results[cached_key][
            "scheduler_id"
        ]
        == "ae-artifact-retention-scheduler"
    )
    assert cached["dispatch_status"] == "DISPATCHED"
    assert default_config["lease_repository"]["available"] is False
    assert default_dispatch["dispatch_status"] == "NOOP"
    assert default_dispatch["control_plan"]["action"] == "status_probe"
    assert default_dispatch["metadata"]["scheduler_daemon_started"] is False
    assert (
        artifact_operations._normalized_daemon_action("manual-tick-once")
        == "manual_tick_once"
    )
    assert artifact_operations._normalized_daemon_action("bad") is None
    assert artifact_operations._normalized_daemon_action(None) is None
    assert artifact_operations._normalized_scheduled_trigger(None) is None


def test_in_memory_daemon_default_action_helpers_cover_blocked_edges() -> None:
    base_runtime = (
        artifact_retention_scheduler_daemon_config_payload()["runtime"] | {}
    )
    base_lease = (
        artifact_retention_scheduler_daemon_config_payload()["lease_repository"] | {}
    )

    operator_blocked = artifact_operations._empty_artifact_retention_scheduler_daemon_actions(
        runtime={**base_runtime, "operator_dispatch_admission_enabled": False},
        lease_repository=base_lease,
    )
    scheduler_blocked = (
        artifact_operations._empty_artifact_retention_scheduler_daemon_actions(
            runtime={**base_runtime, "scheduler_tick_admission_enabled": False},
            lease_repository=base_lease,
        )
    )
    job_queue_blocked = (
        artifact_operations._empty_artifact_retention_scheduler_daemon_actions(
            runtime={**base_runtime, "job_queue_available": False},
            lease_repository=base_lease,
        )
    )
    missing_action = artifact_operations._daemon_action_item(
        {"supported_actions": [{"action": "status_probe"}, "bad"]},
        "manual_tick_once",
    )

    assert operator_blocked[1]["block_reason"] == (
        "operator_dispatch_admission_disabled"
    )
    assert scheduler_blocked[1]["block_reason"] == (
        "scheduler_tick_admission_disabled"
    )
    assert job_queue_blocked[1]["block_reason"] == "job_queue_unavailable"
    assert missing_action["decision_status"] == "BLOCKED"
    assert missing_action["block_reason"] == "daemon_control_action_unavailable"


def test_in_memory_artifact_operations_client_skips_non_matching_scope() -> None:
    tenant_mismatch = {
        **artifact_record(include_private=False),
        "artifact_id": "tenant-mismatch",
        "owner_actor_ref": {
            "tenant_id": "tenant-other",
            "actor_id": "user-0409",
            "actor_type": "user",
        },
    }
    workspace_mismatch = {
        **artifact_record(include_private=False),
        "artifact_id": "workspace-mismatch",
        "workspace_ref": {
            "workspace_id": "workspace-other",
            "document_group_id": "group-0409",
            "chat_document_id": "chat-doc-0409",
        },
    }
    status_mismatch = {
        **artifact_record(include_private=False),
        "artifact_id": "status-mismatch",
        "artifact_status": "DRAFT",
    }
    client = InMemoryAeArtifactOperationsClient(
        artifacts={
            item["artifact_id"]: item
            for item in (tenant_mismatch, workspace_mismatch, status_mismatch)
        }
    )

    collection = client.list_artifacts(
        tenant_id="tenant-0409",
        workspace_id="workspace-0409",
        owner_user_id="user-0409",
        status="READY",
        limit=20,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert collection["count"] == 0


def build_app(source_client: object) -> TestClient:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_artifact_operation_routes(app, client=source_client)
    return TestClient(app)


def test_artifact_operation_route_returns_collection_projection() -> None:
    client = build_app(artifact_client())

    response = client.get(
        "/admin/v1/operations/artifacts",
        params={
            "tenant_id": "tenant-0409",
            "workspace_id": "workspace-0409",
            "owner_user_id": "user-0409",
            "limit": "10",
        },
        headers=auth_headers(),
    )
    ready_only = client.get(
        "/admin/v1/operations/artifacts",
        params={
            "tenant_id": "tenant-0409",
            "workspace_id": "workspace-0409",
            "owner_user_id": "user-0409",
            "status": "ready",
            "limit": "1",
        },
        headers=auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["operation_type"] == "ae_artifact_collection"
    assert payload["projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_COLLECTION_PROJECTION_SCHEMA_VERSION
    )
    assert payload["summary"]["item_count"] == 1
    assert payload["summary"]["ready_count"] == 1
    assert payload["items"][0]["artifact_id"] == ARTIFACT_ID
    assert payload["items"][0]["owner_user_id"] == "user-0409"
    assert payload["request_trace_id"] == TRACE_ID
    assert ready_only.status_code == 200
    assert ready_only.json()["filter"]["status"] == "READY"
    assert ready_only.json()["summary"]["item_count"] == 1


def test_artifact_operation_collection_route_auth_filter_and_error_edges() -> None:
    client = build_app(artifact_client())
    params = {
        "tenant_id": "tenant-0409",
        "workspace_id": "workspace-0409",
        "owner_user_id": "user-0409",
    }

    unauthorized = client.get("/admin/v1/operations/artifacts", params=params)
    invalid_service = client.get(
        "/admin/v1/operations/artifacts",
        params={**params, "service_id": "nex-cx"},
        headers=auth_headers(),
    )
    missing_scope = client.get(
        "/admin/v1/operations/artifacts",
        params={"tenant_id": "tenant-0409", "workspace_id": "workspace-0409"},
        headers=auth_headers(),
    )
    invalid_status = client.get(
        "/admin/v1/operations/artifacts",
        params={**params, "status": "unknown"},
        headers=auth_headers(),
    )
    invalid_limit = client.get(
        "/admin/v1/operations/artifacts",
        params={**params, "limit": "101"},
        headers=auth_headers(),
    )

    class BrokenCollectionClient(InMemoryAeArtifactOperationsClient):
        def list_artifacts(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            raise AeArtifactOperationsError(
                error_code="ag.ae_artifact_collection_source_failed",
                detail="AE collection source unavailable",
                status_code=503,
            )

    source_failed = build_app(BrokenCollectionClient()).get(
        "/admin/v1/operations/artifacts",
        params=params,
        headers=auth_headers(),
    )

    assert unauthorized.status_code == 401
    assert invalid_service.status_code == 400
    assert missing_scope.status_code == 400
    assert missing_scope.json()["error_code"] == (
        "ag.ae_artifact_collection_scope_missing"
    )
    assert invalid_status.json()["error_code"] == (
        "ag.ae_artifact_collection_status_invalid"
    )
    assert invalid_limit.json()["error_code"] == (
        "ag.ae_artifact_collection_limit_invalid"
    )
    assert source_failed.status_code == 503
    assert source_failed.json()["error_code"] == (
        "ag.ae_artifact_collection_source_failed"
    )


def test_artifact_retention_history_operations_route_returns_projection() -> None:
    client = build_app(artifact_client())

    response = client.get(
        "/admin/v1/operations/artifact-retention/executions",
        params={
            "tenant_id": "tenant-0409",
            "workspace_id": "workspace-0409",
            "owner_user_id": "user-0409",
            "limit": "20",
        },
        headers=auth_headers(),
    )
    execute_only = client.get(
        "/admin/v1/operations/artifact-retention/executions",
        params={
            "tenant_id": "tenant-0409",
            "workspace_id": "workspace-0409",
            "owner_user_id": "user-0409",
            "mode": "execute",
        },
        headers=auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_RETENTION_HISTORY_PROJECTION_SCHEMA_VERSION
    )
    assert payload["operation_type"] == "ae_artifact_retention_history"
    assert payload["summary"]["item_count"] == 3
    assert payload["summary"]["operator_attention_count"] == 1
    assert payload["items"][0]["retention_execution_id"] == ("retention-execute-0409")
    assert payload["request_trace_id"] == TRACE_ID
    assert execute_only.status_code == 200
    assert execute_only.json()["filter"]["mode"] == "EXECUTE"
    assert execute_only.json()["summary"]["execute_count"] == 2


def test_artifact_retention_history_operations_route_auth_filter_and_error_edges() -> (
    None
):
    client = build_app(artifact_client())
    params = {
        "tenant_id": "tenant-0409",
        "workspace_id": "workspace-0409",
        "owner_user_id": "user-0409",
    }

    unauthorized = client.get(
        "/admin/v1/operations/artifact-retention/executions",
        params=params,
    )
    invalid_service = client.get(
        "/admin/v1/operations/artifact-retention/executions",
        params={**params, "service_id": "nex-cx"},
        headers=auth_headers(),
    )
    missing_scope = client.get(
        "/admin/v1/operations/artifact-retention/executions",
        params={"tenant_id": "tenant-0409", "workspace_id": "workspace-0409"},
        headers=auth_headers(),
    )
    invalid_mode = client.get(
        "/admin/v1/operations/artifact-retention/executions",
        params={**params, "mode": "preview"},
        headers=auth_headers(),
    )
    invalid_status = client.get(
        "/admin/v1/operations/artifact-retention/executions",
        params={**params, "execution_status": "unknown"},
        headers=auth_headers(),
    )
    invalid_limit = client.get(
        "/admin/v1/operations/artifact-retention/executions",
        params={**params, "limit": "101"},
        headers=auth_headers(),
    )

    class BrokenRetentionHistoryClient(InMemoryAeArtifactOperationsClient):
        def list_artifact_retention_executions(
            self,
            *args: Any,
            **kwargs: Any,
        ) -> dict[str, Any]:
            raise AeArtifactOperationsError(
                error_code="ag.ae_artifact_retention_history_source_failed",
                detail="AE retention history source unavailable",
                status_code=503,
            )

    source_failed = build_app(BrokenRetentionHistoryClient()).get(
        "/admin/v1/operations/artifact-retention/executions",
        params=params,
        headers=auth_headers(),
    )

    assert unauthorized.status_code == 401
    assert invalid_service.status_code == 400
    assert missing_scope.status_code == 400
    assert missing_scope.json()["error_code"] == (
        "ag.ae_artifact_retention_history_scope_missing"
    )
    assert invalid_mode.json()["error_code"] == (
        "ag.ae_artifact_retention_history_mode_invalid"
    )
    assert invalid_status.json()["error_code"] == (
        "ag.ae_artifact_retention_history_status_invalid"
    )
    assert invalid_limit.json()["error_code"] == (
        "ag.ae_artifact_retention_history_limit_invalid"
    )
    assert source_failed.status_code == 503
    assert source_failed.json()["error_code"] == (
        "ag.ae_artifact_retention_history_source_failed"
    )


def test_artifact_retention_batch_operations_route_returns_projection() -> None:
    client = build_app(artifact_client())

    response = client.get(
        "/admin/v1/operations/artifact-retention/batch-plan",
        params={
            "tenant_id": "tenant-0409",
            "workspace_id": "workspace-0409",
            "owner_user_id": "user-0409",
            "retention_days": "30",
            "as_of": "2026-09-01T00:00:00Z",
            "scan_limit": "20",
            "max_delete_count": "1",
            "checked_at": "2026-09-01T02:30:00Z",
        },
        headers=auth_headers(),
    )
    noop = client.get(
        "/admin/v1/operations/artifact-retention/batch-plan",
        params={
            "tenant_id": "tenant-0409",
            "workspace_id": "workspace-0409",
            "owner_user_id": "user-0409",
        },
        headers=auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_RETENTION_BATCH_PROJECTION_SCHEMA_VERSION
    )
    assert payload["operation_type"] == "ae_artifact_retention_batch_plan"
    assert payload["plan"]["plan_id"] == "retention-batch-plan-0409"
    assert payload["summary"]["candidate_count"] == 2
    assert payload["summary"]["selected_count"] == 1
    assert payload["summary"]["dispatch_available"] is True
    assert payload["request_trace_id"] == TRACE_ID
    assert noop.status_code == 200
    assert noop.json()["plan"]["plan_status"] == "NOOP"
    assert noop.json()["summary"]["dispatch_available"] is False


def test_artifact_retention_batch_operations_route_auth_filter_and_error_edges() -> (
    None
):
    client = build_app(artifact_client())
    params = {
        "tenant_id": "tenant-0409",
        "workspace_id": "workspace-0409",
        "owner_user_id": "user-0409",
    }

    unauthorized = client.get(
        "/admin/v1/operations/artifact-retention/batch-plan",
        params=params,
    )
    invalid_service = client.get(
        "/admin/v1/operations/artifact-retention/batch-plan",
        params={**params, "service_id": "nex-cx"},
        headers=auth_headers(),
    )
    missing_scope = client.get(
        "/admin/v1/operations/artifact-retention/batch-plan",
        params={"tenant_id": "tenant-0409", "workspace_id": "workspace-0409"},
        headers=auth_headers(),
    )
    invalid_retention_days = client.get(
        "/admin/v1/operations/artifact-retention/batch-plan",
        params={**params, "retention_days": "0"},
        headers=auth_headers(),
    )
    invalid_scan_limit = client.get(
        "/admin/v1/operations/artifact-retention/batch-plan",
        params={**params, "scan_limit": "101"},
        headers=auth_headers(),
    )
    invalid_delete_limit = client.get(
        "/admin/v1/operations/artifact-retention/batch-plan",
        params={**params, "max_delete_count": "many"},
        headers=auth_headers(),
    )

    class BrokenRetentionBatchClient(InMemoryAeArtifactOperationsClient):
        def get_artifact_retention_batch_plan(
            self,
            *args: Any,
            **kwargs: Any,
        ) -> dict[str, Any]:
            raise AeArtifactOperationsError(
                error_code="ag.ae_artifact_retention_batch_source_failed",
                detail="AE retention batch source unavailable",
                status_code=503,
            )

    source_failed = build_app(BrokenRetentionBatchClient()).get(
        "/admin/v1/operations/artifact-retention/batch-plan",
        params=params,
        headers=auth_headers(),
    )

    assert unauthorized.status_code == 401
    assert invalid_service.status_code == 400
    assert missing_scope.status_code == 400
    assert missing_scope.json()["error_code"] == (
        "ag.ae_artifact_retention_batch_scope_missing"
    )
    assert invalid_retention_days.json()["error_code"] == (
        "ag.ae_artifact_retention_batch_retention_days_invalid"
    )
    assert invalid_scan_limit.json()["error_code"] == (
        "ag.ae_artifact_retention_batch_scan_limit_invalid"
    )
    assert invalid_delete_limit.json()["error_code"] == (
        "ag.ae_artifact_retention_batch_delete_limit_invalid"
    )
    assert source_failed.status_code == 503
    assert source_failed.json()["error_code"] == (
        "ag.ae_artifact_retention_batch_source_failed"
    )


def test_artifact_retention_scheduled_job_operations_route_returns_projection() -> None:
    client = build_app(artifact_client())

    response = client.get(
        "/admin/v1/operations/artifact-retention/scheduled-jobs",
        params={
            "tenant_id": "tenant-0409",
            "workspace_id": "workspace-0409",
            "owner_user_id": "user-0409",
            "limit": "20",
        },
        headers=auth_headers(),
    )
    running = client.get(
        "/admin/v1/operations/artifact-retention/scheduled-jobs",
        params={
            "tenant_id": "tenant-0409",
            "workspace_id": "workspace-0409",
            "owner_user_id": "user-0409",
            "status": "running",
        },
        headers=auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_RETENTION_SCHEDULED_JOB_PROJECTION_SCHEMA_VERSION
    )
    assert payload["operation_type"] == "ae_artifact_retention_scheduled_jobs"
    assert payload["summary"]["job_count"] == 3
    assert payload["summary"]["failed_count"] == 1
    assert payload["summary"]["retryable_failed_count"] == 1
    assert payload["request_trace_id"] == TRACE_ID
    assert running.status_code == 200
    assert running.json()["filter"]["status"] == "RUNNING"
    assert running.json()["summary"]["running_count"] == 1


def test_artifact_retention_scheduled_job_operations_route_auth_filter_and_error_edges() -> (
    None
):
    client = build_app(artifact_client())
    params = {
        "tenant_id": "tenant-0409",
        "workspace_id": "workspace-0409",
        "owner_user_id": "user-0409",
    }

    unauthorized = client.get(
        "/admin/v1/operations/artifact-retention/scheduled-jobs",
        params=params,
    )
    invalid_service = client.get(
        "/admin/v1/operations/artifact-retention/scheduled-jobs",
        params={**params, "service_id": "nex-cx"},
        headers=auth_headers(),
    )
    missing_scope = client.get(
        "/admin/v1/operations/artifact-retention/scheduled-jobs",
        params={"tenant_id": "tenant-0409", "workspace_id": "workspace-0409"},
        headers=auth_headers(),
    )
    invalid_status = client.get(
        "/admin/v1/operations/artifact-retention/scheduled-jobs",
        params={**params, "status": "blocked"},
        headers=auth_headers(),
    )
    invalid_limit = client.get(
        "/admin/v1/operations/artifact-retention/scheduled-jobs",
        params={**params, "limit": "0"},
        headers=auth_headers(),
    )

    class BrokenRetentionScheduledJobClient(InMemoryAeArtifactOperationsClient):
        def list_artifact_retention_scheduled_jobs(
            self,
            *args: Any,
            **kwargs: Any,
        ) -> dict[str, Any]:
            raise AeArtifactOperationsError(
                error_code="ag.ae_artifact_retention_scheduled_job_source_failed",
                detail="AE retention scheduled job source unavailable",
                status_code=503,
            )

    source_failed = build_app(BrokenRetentionScheduledJobClient()).get(
        "/admin/v1/operations/artifact-retention/scheduled-jobs",
        params=params,
        headers=auth_headers(),
    )

    assert unauthorized.status_code == 401
    assert invalid_service.status_code == 400
    assert missing_scope.status_code == 400
    assert missing_scope.json()["error_code"] == (
        "ag.ae_artifact_retention_scheduled_job_scope_missing"
    )
    assert invalid_status.status_code == 400
    assert invalid_status.json()["error_code"] == (
        "ag.ae_artifact_retention_scheduled_job_status_invalid"
    )
    assert invalid_limit.status_code == 400
    assert invalid_limit.json()["error_code"] == (
        "ag.ae_artifact_retention_scheduled_job_limit_invalid"
    )
    assert source_failed.status_code == 503
    assert source_failed.json()["error_code"] == (
        "ag.ae_artifact_retention_scheduled_job_source_failed"
    )


def test_artifact_retention_automation_operations_route_returns_projection() -> None:
    client = build_app(artifact_client())

    response = client.get(
        "/admin/v1/operations/artifact-retention/automation",
        params={
            "tenant_id": "tenant-0409",
            "workspace_id": "workspace-0409",
            "owner_user_id": "user-0409",
            "retention_days": "30",
            "as_of": "2026-09-01T00:00:00Z",
            "scan_limit": "20",
            "max_delete_count": "1",
            "checked_at": "2026-09-01T02:30:00Z",
            "limit": "20",
        },
        headers=auth_headers(),
    )
    running = client.get(
        "/admin/v1/operations/artifact-retention/automation",
        params={
            "tenant_id": "tenant-0409",
            "workspace_id": "workspace-0409",
            "owner_user_id": "user-0409",
            "retention_days": "30",
            "as_of": "2026-09-01T00:00:00Z",
            "scan_limit": "20",
            "max_delete_count": "1",
            "checked_at": "2026-09-01T02:30:00Z",
            "scheduled_status": "running",
            "limit": "20",
        },
        headers=auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_RETENTION_AUTOMATION_PROJECTION_SCHEMA_VERSION
    )
    assert payload["operation_type"] == "ae_artifact_retention_automation"
    assert payload["batch_plan"]["summary"]["dispatch_available"] is True
    assert payload["scheduled_jobs"]["summary"]["failed_count"] == 1
    assert payload["history"]["summary"]["blocked_count"] == 1
    assert payload["scheduler_daemon"]["summary"][
        "manual_tick_once_available"
    ] is True
    assert payload["scheduler_daemon"]["summary"]["start_daemon_available"] is False
    assert payload["summary"]["safety_status"] == "FAILED_ATTENTION"
    assert payload["summary"]["daemon_manual_tick_once_available"] is True
    assert payload["summary"]["daemon_start_daemon_available"] is False
    assert payload["summary"]["physical_delete_operator_approval_required"] is True
    assert payload["source_status"]["daemon_config_loaded"] is True
    assert payload["operator_guidance"]["ae_daemon_config_route"] == (
        "/api/v1/artifact-retention/scheduler-daemon-config"
    )
    assert payload["operator_guidance"]["ag_direct_database_write_allowed"] is False
    assert payload["request_trace_id"] == TRACE_ID
    assert running.status_code == 200
    assert running.json()["scheduled_jobs"]["filter"]["status"] == "RUNNING"
    assert running.json()["scheduled_jobs"]["summary"]["running_count"] == 1


def test_artifact_retention_automation_operations_route_guardrails() -> None:
    client = build_app(artifact_client())
    params = {
        "tenant_id": "tenant-0409",
        "workspace_id": "workspace-0409",
        "owner_user_id": "user-0409",
    }

    unauthorized = client.get(
        "/admin/v1/operations/artifact-retention/automation",
        params=params,
    )
    invalid_service = client.get(
        "/admin/v1/operations/artifact-retention/automation",
        params={**params, "service_id": "nex-cx"},
        headers=auth_headers(),
    )
    missing_scope = client.get(
        "/admin/v1/operations/artifact-retention/automation",
        params={"tenant_id": "tenant-0409", "workspace_id": "workspace-0409"},
        headers=auth_headers(),
    )
    invalid_retention_days = client.get(
        "/admin/v1/operations/artifact-retention/automation",
        params={**params, "retention_days": "0"},
        headers=auth_headers(),
    )
    invalid_scan_limit = client.get(
        "/admin/v1/operations/artifact-retention/automation",
        params={**params, "scan_limit": "101"},
        headers=auth_headers(),
    )
    invalid_delete_limit = client.get(
        "/admin/v1/operations/artifact-retention/automation",
        params={**params, "max_delete_count": "many"},
        headers=auth_headers(),
    )
    invalid_job_status = client.get(
        "/admin/v1/operations/artifact-retention/automation",
        params={**params, "scheduled_status": "waiting"},
        headers=auth_headers(),
    )
    invalid_history_mode = client.get(
        "/admin/v1/operations/artifact-retention/automation",
        params={**params, "history_mode": "purge"},
        headers=auth_headers(),
    )
    invalid_history_status = client.get(
        "/admin/v1/operations/artifact-retention/automation",
        params={**params, "history_status": "paused"},
        headers=auth_headers(),
    )
    invalid_limit = client.get(
        "/admin/v1/operations/artifact-retention/automation",
        params={**params, "limit": "0"},
        headers=auth_headers(),
    )

    class BrokenRetentionAutomationClient(InMemoryAeArtifactOperationsClient):
        def list_artifact_retention_executions(
            self,
            *args: Any,
            **kwargs: Any,
        ) -> dict[str, Any]:
            raise AeArtifactOperationsError(
                error_code="ag.ae_artifact_retention_automation_source_failed",
                detail="AE retention automation source unavailable",
                status_code=503,
            )

    source_failed = build_app(
        BrokenRetentionAutomationClient(
            artifact_retention_batch_plans=artifact_client().artifact_retention_batch_plans,
            artifact_retention_scheduled_job_collections=(
                artifact_client().artifact_retention_scheduled_job_collections
            ),
        )
    ).get(
        "/admin/v1/operations/artifact-retention/automation",
        params={
            **params,
            "retention_days": "30",
            "as_of": "2026-09-01T00:00:00Z",
            "scan_limit": "20",
            "max_delete_count": "1",
            "checked_at": "2026-09-01T02:30:00Z",
        },
        headers=auth_headers(),
    )

    class BrokenRetentionAutomationDaemonClient(InMemoryAeArtifactOperationsClient):
        def get_artifact_retention_scheduler_daemon_config(
            self,
            *args: Any,
            **kwargs: Any,
        ) -> dict[str, Any]:
            raise AeArtifactOperationsError(
                error_code="ag.ae_artifact_retention_automation_daemon_failed",
                detail="AE retention daemon config unavailable",
                status_code=503,
            )

    daemon_source_failed = build_app(
        BrokenRetentionAutomationDaemonClient(
            artifact_retention_batch_plans=artifact_client().artifact_retention_batch_plans,
            artifact_retention_scheduled_job_collections=(
                artifact_client().artifact_retention_scheduled_job_collections
            ),
            artifact_retention_history_collections=(
                artifact_client().artifact_retention_history_collections
            ),
        )
    ).get(
        "/admin/v1/operations/artifact-retention/automation",
        params={
            **params,
            "retention_days": "30",
            "as_of": "2026-09-01T00:00:00Z",
            "scan_limit": "20",
            "max_delete_count": "1",
            "checked_at": "2026-09-01T02:30:00Z",
        },
        headers=auth_headers(),
    )

    assert unauthorized.status_code == 401
    assert invalid_service.status_code == 400
    assert missing_scope.status_code == 400
    assert missing_scope.json()["error_code"] == (
        "ag.ae_artifact_retention_automation_scope_missing"
    )
    assert invalid_retention_days.status_code == 400
    assert invalid_retention_days.json()["error_code"] == (
        "ag.ae_artifact_retention_automation_retention_days_invalid"
    )
    assert invalid_scan_limit.status_code == 400
    assert invalid_scan_limit.json()["error_code"] == (
        "ag.ae_artifact_retention_automation_scan_limit_invalid"
    )
    assert invalid_delete_limit.status_code == 400
    assert invalid_delete_limit.json()["error_code"] == (
        "ag.ae_artifact_retention_automation_delete_limit_invalid"
    )
    assert invalid_job_status.status_code == 400
    assert invalid_job_status.json()["error_code"] == (
        "ag.ae_artifact_retention_automation_job_status_invalid"
    )
    assert invalid_history_mode.status_code == 400
    assert invalid_history_mode.json()["error_code"] == (
        "ag.ae_artifact_retention_automation_history_mode_invalid"
    )
    assert invalid_history_status.status_code == 400
    assert invalid_history_status.json()["error_code"] == (
        "ag.ae_artifact_retention_automation_history_status_invalid"
    )
    assert invalid_limit.status_code == 400
    assert invalid_limit.json()["error_code"] == (
        "ag.ae_artifact_retention_automation_limit_invalid"
    )
    assert source_failed.status_code == 503
    assert source_failed.json()["error_code"] == (
        "ag.ae_artifact_retention_automation_source_failed"
    )
    assert daemon_source_failed.status_code == 503
    assert daemon_source_failed.json()["error_code"] == (
        "ag.ae_artifact_retention_automation_daemon_failed"
    )


def test_artifact_retention_scheduler_daemon_operations_route_returns_projection() -> (
    None
):
    client = build_app(artifact_client())

    response = client.get(
        "/admin/v1/operations/artifact-retention/scheduler-daemon",
        headers=auth_headers(),
    )
    filtered = client.get(
        "/admin/v1/operations/artifact-retention/scheduler-daemon",
        params={"service_id": "nex-ae-api"},
        headers=auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_RETENTION_DAEMON_PROJECTION_SCHEMA_VERSION
    )
    assert payload["operation_type"] == "ae_artifact_retention_scheduler_daemon"
    assert payload["summary"]["manual_tick_once_available"] is True
    assert payload["summary"]["start_daemon_available"] is False
    assert payload["source_status"]["daemon_config_loaded"] is True
    assert payload["operator_guidance"]["manual_tick_once_only"] is True
    assert payload["operator_guidance"]["ag_direct_job_enqueue_allowed"] is False
    assert payload["request_trace_id"] == TRACE_ID
    assert filtered.status_code == 200
    assert filtered.json()["source_status"]["service_id"] == "nex-ae-api"


def test_artifact_retention_scheduler_daemon_operations_route_guardrails() -> None:
    client = build_app(artifact_client())

    unauthorized = client.get(
        "/admin/v1/operations/artifact-retention/scheduler-daemon",
    )
    invalid_service = client.get(
        "/admin/v1/operations/artifact-retention/scheduler-daemon",
        params={"service_id": "nex-cx"},
        headers=auth_headers(),
    )

    class BrokenDaemonConfigClient(InMemoryAeArtifactOperationsClient):
        def get_artifact_retention_scheduler_daemon_config(
            self,
            *args: Any,
            **kwargs: Any,
        ) -> dict[str, Any]:
            raise AeArtifactOperationsError(
                error_code="ag.ae_artifact_retention_daemon_source_failed",
                detail="AE scheduler daemon source unavailable",
                status_code=503,
            )

    source_failed = build_app(BrokenDaemonConfigClient()).get(
        "/admin/v1/operations/artifact-retention/scheduler-daemon",
        headers=auth_headers(),
    )

    assert unauthorized.status_code == 401
    assert invalid_service.status_code == 400
    assert invalid_service.json()["error_code"] == "ag.ae_artifact_service_invalid"
    assert source_failed.status_code == 503
    assert source_failed.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_source_failed"
    )


def test_artifact_retention_scheduler_daemon_manual_tick_route_dispatches() -> None:
    class CapturingDaemonControlClient(InMemoryAeArtifactOperationsClient):
        def __init__(self) -> None:
            super().__init__(
                artifact_retention_scheduler_daemon_config=(
                    artifact_retention_scheduler_daemon_config_payload()
                )
            )
            self.captured_dispatch: dict[str, Any] | None = None

        def dispatch_artifact_retention_scheduler_daemon_control(
            self,
            **kwargs: Any,
        ) -> dict[str, Any]:
            self.captured_dispatch = dict(kwargs)
            return super().dispatch_artifact_retention_scheduler_daemon_control(
                **kwargs
            )

    source_client = CapturingDaemonControlClient()
    client = build_app(source_client)

    response = client.post(
        "/admin/v1/operations/artifact-retention/scheduler-daemon/manual-tick-once",
        json={
            "tenant_id": "tenant-0409",
            "workspace_id": "workspace-0409",
            "owner_user_id": "user-0409",
            "retention_days": "30",
            "as_of": "2026-09-01T00:00:00Z",
            "scan_limit": "20",
            "max_delete_count": "1",
            "requested_at": "2026-09-01T02:35:00Z",
            "requested_by": {
                "actor_type": "operator",
                "actor_id": "ag-retention-operator",
                "tenant_id": "tenant-0409",
                "workspace_id": "workspace-0409",
                "database_url": "DATABASE_URL_SHOULD_NOT_LEAK",
            },
            "reason": "manual AG tick",
            "tick_at": "2026-09-01T02:35:00Z",
            "run_worker": True,
            "confirm_worker_run": True,
            "idempotency_key": "body-idem-0525",
            "confirm_dispatch": True,
        },
        headers={**auth_headers(), "Idempotency-Key": "header-idem-0525"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["operation_type"] == "ae_artifact_retention_scheduler_daemon"
    assert payload["dispatch_response"]["dispatch_status"] == "DISPATCHED"
    assert payload["dispatch_response"]["control_plan"]["action"] == (
        "manual_tick_once"
    )
    assert payload["summary"]["last_dispatch_action"] == "manual_tick_once"
    assert payload["summary"]["manual_tick_once_available"] is True
    assert payload["request_trace_id"] == TRACE_ID
    assert "DATABASE_URL_SHOULD_NOT_LEAK" not in str(payload)
    assert source_client.captured_dispatch is not None
    assert source_client.captured_dispatch["action"] == "manual_tick_once"
    assert source_client.captured_dispatch["idempotency_key"] == "header-idem-0525"
    assert source_client.captured_dispatch["run_worker"] is True
    assert source_client.captured_dispatch["requested_by"] == {
        "actor_type": "operator",
        "actor_id": "ag-retention-operator",
        "tenant_id": "tenant-0409",
        "workspace_id": "workspace-0409",
    }


def test_artifact_retention_scheduler_daemon_manual_tick_route_guardrails() -> None:
    client = build_app(artifact_client())
    request_payload = {
        "tenant_id": "tenant-0409",
        "workspace_id": "workspace-0409",
        "owner_user_id": "user-0409",
        "confirm_dispatch": True,
    }

    unauthorized = client.post(
        "/admin/v1/operations/artifact-retention/scheduler-daemon/manual-tick-once",
        json=request_payload,
    )
    invalid_service = client.post(
        "/admin/v1/operations/artifact-retention/scheduler-daemon/manual-tick-once",
        params={"service_id": "nex-cx"},
        json=request_payload,
        headers=auth_headers(),
    )
    confirmation_required = client.post(
        "/admin/v1/operations/artifact-retention/scheduler-daemon/manual-tick-once",
        json={**request_payload, "confirm_dispatch": False},
        headers=auth_headers(),
    )
    invalid_action = client.post(
        "/admin/v1/operations/artifact-retention/scheduler-daemon/manual-tick-once",
        json={**request_payload, "action": "start_daemon"},
        headers=auth_headers(),
    )
    missing_scope = client.post(
        "/admin/v1/operations/artifact-retention/scheduler-daemon/manual-tick-once",
        json={
            "tenant_id": "tenant-0409",
            "workspace_id": "workspace-0409",
            "confirm_dispatch": True,
        },
        headers=auth_headers(),
    )
    invalid_retention_days = client.post(
        "/admin/v1/operations/artifact-retention/scheduler-daemon/manual-tick-once",
        json={**request_payload, "retention_days": "0"},
        headers=auth_headers(),
    )
    invalid_scan_limit = client.post(
        "/admin/v1/operations/artifact-retention/scheduler-daemon/manual-tick-once",
        json={**request_payload, "scan_limit": "101"},
        headers=auth_headers(),
    )
    invalid_delete_limit = client.post(
        "/admin/v1/operations/artifact-retention/scheduler-daemon/manual-tick-once",
        json={**request_payload, "max_delete_count": "many"},
        headers=auth_headers(),
    )
    invalid_worker_flag = client.post(
        "/admin/v1/operations/artifact-retention/scheduler-daemon/manual-tick-once",
        json={**request_payload, "run_worker": "yes"},
        headers=auth_headers(),
    )
    worker_confirmation_required = client.post(
        "/admin/v1/operations/artifact-retention/scheduler-daemon/manual-tick-once",
        json={**request_payload, "run_worker": True},
        headers=auth_headers(),
    )

    blocked_client = InMemoryAeArtifactOperationsClient(
        artifact_retention_scheduler_daemon_config=(
            artifact_retention_scheduler_daemon_config_payload(
                job_queue_available=False,
                lease_available=True,
            )
        )
    )
    blocked = build_app(blocked_client).post(
        "/admin/v1/operations/artifact-retention/scheduler-daemon/manual-tick-once",
        json=request_payload,
        headers=auth_headers(),
    )

    class BrokenDaemonManualConfigClient(InMemoryAeArtifactOperationsClient):
        def get_artifact_retention_scheduler_daemon_config(
            self,
            *args: Any,
            **kwargs: Any,
        ) -> dict[str, Any]:
            raise AeArtifactOperationsError(
                error_code="ag.ae_artifact_retention_daemon_config_failed",
                detail="AE scheduler daemon config unavailable",
                status_code=503,
            )

    config_source_failed = build_app(BrokenDaemonManualConfigClient()).post(
        "/admin/v1/operations/artifact-retention/scheduler-daemon/manual-tick-once",
        json=request_payload,
        headers=auth_headers(),
    )

    class BrokenDaemonDispatchClient(InMemoryAeArtifactOperationsClient):
        def __init__(self) -> None:
            super().__init__(
                artifact_retention_scheduler_daemon_config=(
                    artifact_retention_scheduler_daemon_config_payload()
                )
            )

        def dispatch_artifact_retention_scheduler_daemon_control(
            self,
            **kwargs: Any,
        ) -> dict[str, Any]:
            raise AeArtifactOperationsError(
                error_code="ag.ae_artifact_retention_daemon_dispatch_failed",
                detail="AE scheduler daemon dispatch unavailable",
                status_code=503,
            )

    source_failed = build_app(BrokenDaemonDispatchClient()).post(
        "/admin/v1/operations/artifact-retention/scheduler-daemon/manual-tick-once",
        json=request_payload,
        headers=auth_headers(),
    )

    assert unauthorized.status_code == 401
    assert invalid_service.status_code == 400
    assert confirmation_required.status_code == 409
    assert confirmation_required.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_manual_tick_confirmation_required"
    )
    assert invalid_action.status_code == 400
    assert invalid_action.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_manual_tick_action_invalid"
    )
    assert missing_scope.status_code == 400
    assert missing_scope.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_manual_tick_scope_missing"
    )
    assert invalid_retention_days.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_manual_tick_retention_days_invalid"
    )
    assert invalid_scan_limit.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_manual_tick_scan_limit_invalid"
    )
    assert invalid_delete_limit.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_manual_tick_delete_limit_invalid"
    )
    assert invalid_worker_flag.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_manual_tick_worker_flag_invalid"
    )
    assert worker_confirmation_required.status_code == 409
    assert worker_confirmation_required.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_manual_tick_worker_confirmation_required"
    )
    assert blocked.status_code == 409
    assert blocked.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_manual_tick_blocked"
    )
    assert config_source_failed.status_code == 503
    assert config_source_failed.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_config_failed"
    )
    assert source_failed.status_code == 503
    assert source_failed.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_dispatch_failed"
    )


def test_artifact_retention_scheduler_daemon_manual_tick_validator_edges() -> None:
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": (
                "/admin/v1/operations/artifact-retention/"
                "scheduler-daemon/manual-tick-once"
            ),
            "headers": [(b"x-request-id", REQUEST_ID.encode())],
        }
    )

    invalid = artifact_operations._validate_artifact_retention_daemon_manual_tick_request(
        request,
        payload=[],
        idempotency_key_header=None,
    )
    valid = artifact_operations._validate_artifact_retention_daemon_manual_tick_request(
        request,
        payload={
            "tenant_id": " tenant-0409 ",
            "workspace_id": " workspace-0409 ",
            "owner_user_id": " user-0409 ",
            "confirm_dispatch": True,
            "idempotency_key": "body-idem-0525",
        },
        idempotency_key_header="",
    )

    assert isinstance(invalid, artifact_operations.JSONResponse)
    assert invalid.status_code == 400
    assert not isinstance(valid, artifact_operations.JSONResponse)
    assert valid["tenant_id"] == "tenant-0409"
    assert valid["scan_limit"] == artifact_operations.DEFAULT_ARTIFACT_COLLECTION_LIMIT
    assert valid["idempotency_key"] == "body-idem-0525"
    assert valid["requested_by"] == {
        "actor_type": "operator",
        "actor_id": "nex-ag-artifact-retention-operator",
        "tenant_id": "tenant-0409",
        "workspace_id": "workspace-0409",
        "request_id": REQUEST_ID,
        "service_id": "nex-ag",
    }


def test_artifact_retention_scheduled_dispatch_route_returns_projection() -> None:
    client = build_app(artifact_client())

    response = client.post(
        "/admin/v1/operations/artifact-retention/scheduled-jobs/dispatch",
        json={
            "tenant_id": "tenant-0409",
            "workspace_id": "workspace-0409",
            "owner_user_id": "user-0409",
            "retention_days": "30",
            "as_of": "2026-09-01T00:00:00Z",
            "scan_limit": "20",
            "max_delete_count": "1",
            "checked_at": "2026-09-01T02:30:00Z",
            "trigger_type": "operator-dispatch",
            "requested_at": "2026-09-01T02:35:00Z",
            "idempotency_key": "dispatch-idem-0409",
            "confirm_dispatch": True,
        },
        headers=auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_RETENTION_SCHEDULED_DISPATCH_SCHEMA_VERSION
    )
    assert payload["operation_type"] == "ae_artifact_retention_scheduled_dispatch"
    assert payload["dispatch_request"]["trigger_type"] == "operator_dispatch"
    assert payload["summary"]["dispatch_available"] is True
    assert payload["summary"]["enqueue_status"] == "ENQUEUED"
    assert payload["summary"]["job_enqueued"] is True
    assert payload["summary"]["job_status"] == "QUEUED"
    assert payload["source_status"]["dispatch_response_loaded"] is True
    assert payload["request_trace_id"] == TRACE_ID


def test_artifact_retention_scheduled_dispatch_route_guardrail_edges() -> None:
    client = build_app(artifact_client())
    request_payload = {
        "tenant_id": "tenant-0409",
        "workspace_id": "workspace-0409",
        "owner_user_id": "user-0409",
        "confirm_dispatch": True,
    }

    unauthorized = client.post(
        "/admin/v1/operations/artifact-retention/scheduled-jobs/dispatch",
        json=request_payload,
    )
    invalid_service = client.post(
        "/admin/v1/operations/artifact-retention/scheduled-jobs/dispatch",
        params={"service_id": "nex-cx"},
        json=request_payload,
        headers=auth_headers(),
    )
    confirmation_required = client.post(
        "/admin/v1/operations/artifact-retention/scheduled-jobs/dispatch",
        json={**request_payload, "confirm_dispatch": False},
        headers=auth_headers(),
    )
    missing_scope = client.post(
        "/admin/v1/operations/artifact-retention/scheduled-jobs/dispatch",
        json={
            "tenant_id": "tenant-0409",
            "workspace_id": "workspace-0409",
            "confirm_dispatch": True,
        },
        headers=auth_headers(),
    )
    invalid_trigger = client.post(
        "/admin/v1/operations/artifact-retention/scheduled-jobs/dispatch",
        json={**request_payload, "trigger_type": "manual-now"},
        headers=auth_headers(),
    )
    invalid_retention_days = client.post(
        "/admin/v1/operations/artifact-retention/scheduled-jobs/dispatch",
        json={**request_payload, "retention_days": "0"},
        headers=auth_headers(),
    )
    invalid_scan_limit = client.post(
        "/admin/v1/operations/artifact-retention/scheduled-jobs/dispatch",
        json={**request_payload, "scan_limit": "101"},
        headers=auth_headers(),
    )
    invalid_delete_limit = client.post(
        "/admin/v1/operations/artifact-retention/scheduled-jobs/dispatch",
        json={**request_payload, "max_delete_count": "many"},
        headers=auth_headers(),
    )
    blocked = client.post(
        "/admin/v1/operations/artifact-retention/scheduled-jobs/dispatch",
        json={
            "tenant_id": "tenant-0409",
            "workspace_id": "workspace-0409",
            "owner_user_id": "user-0409",
            "confirm_dispatch": True,
            "scan_limit": "20",
            "max_delete_count": "20",
        },
        headers=auth_headers(),
    )

    class BrokenRetentionDispatchClient(InMemoryAeArtifactOperationsClient):
        def dispatch_artifact_retention_scheduled_job(
            self,
            *args: Any,
            **kwargs: Any,
        ) -> dict[str, Any]:
            raise AeArtifactOperationsError(
                error_code="ag.ae_artifact_retention_scheduled_dispatch_source_failed",
                detail="AE retention scheduled dispatch source unavailable",
                status_code=503,
            )

    source_failed = build_app(
        BrokenRetentionDispatchClient(
            artifact_retention_batch_plans=artifact_client().artifact_retention_batch_plans
        )
    ).post(
        "/admin/v1/operations/artifact-retention/scheduled-jobs/dispatch",
        json={
            **request_payload,
            "retention_days": "30",
            "as_of": "2026-09-01T00:00:00Z",
            "scan_limit": "20",
            "max_delete_count": "1",
            "checked_at": "2026-09-01T02:30:00Z",
        },
        headers=auth_headers(),
    )

    assert unauthorized.status_code == 401
    assert invalid_service.status_code == 400
    assert confirmation_required.status_code == 409
    assert confirmation_required.json()["error_code"] == (
        "ag.ae_artifact_retention_scheduled_dispatch_confirmation_required"
    )
    assert missing_scope.status_code == 400
    assert missing_scope.json()["error_code"] == (
        "ag.ae_artifact_retention_scheduled_dispatch_scope_missing"
    )
    assert invalid_trigger.json()["error_code"] == (
        "ag.ae_artifact_retention_scheduled_dispatch_trigger_invalid"
    )
    assert invalid_retention_days.json()["error_code"] == (
        "ag.ae_artifact_retention_scheduled_dispatch_retention_days_invalid"
    )
    assert invalid_scan_limit.json()["error_code"] == (
        "ag.ae_artifact_retention_scheduled_dispatch_scan_limit_invalid"
    )
    assert invalid_delete_limit.json()["error_code"] == (
        "ag.ae_artifact_retention_scheduled_dispatch_delete_limit_invalid"
    )
    assert blocked.status_code == 409
    assert blocked.json()["error_code"] == (
        "ag.ae_artifact_retention_scheduled_dispatch_blocked"
    )
    assert source_failed.status_code == 503
    assert source_failed.json()["error_code"] == (
        "ag.ae_artifact_retention_scheduled_dispatch_source_failed"
    )


def test_artifact_operation_route_returns_detail_projection() -> None:
    client = build_app(artifact_client())

    response = client.get(
        f"/admin/v1/operations/artifacts/{ARTIFACT_ID}",
        params={"interaction_id": INTERACTION_ID},
        headers=auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["operation_type"] == "ae_artifact"
    assert payload["artifact"]["artifact_id"] == ARTIFACT_ID
    assert payload["handoff"]["artifact_handoff_id"] == HANDOFF_ID
    assert payload["chat_artifact_refs"][0]["chat_interaction_id"] == INTERACTION_ID
    assert payload["request_trace_id"] == TRACE_ID


def test_artifact_operation_route_returns_lifecycle_projection() -> None:
    client = build_app(artifact_client())

    response = client.get(
        f"/admin/v1/operations/artifacts/{ARTIFACT_ID}/lifecycle",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_LIFECYCLE_PROJECTION_SCHEMA_VERSION
    )
    assert payload["operation_type"] == "ae_artifact_lifecycle"
    assert payload["summary"]["enabled_actions"] == ["ARCHIVE", "MARK_DELETED"]
    assert payload["lifecycle"]["actions"][0]["route"] == (
        f"/api/v1/artifacts/{ARTIFACT_ID}/lifecycle-actions"
    )
    assert payload["request_trace_id"] == TRACE_ID


def test_artifact_operation_lifecycle_route_auth_filter_missing_and_source_errors() -> (
    None
):
    client = build_app(artifact_client())

    unauthorized = client.get(f"/admin/v1/operations/artifacts/{ARTIFACT_ID}/lifecycle")
    invalid_service = client.get(
        f"/admin/v1/operations/artifacts/{ARTIFACT_ID}/lifecycle",
        params={"service_id": "nex-cx"},
        headers=auth_headers(),
    )
    missing = client.get(
        "/admin/v1/operations/artifacts/missing/lifecycle",
        headers=auth_headers(),
    )

    class BrokenLifecycleClient(InMemoryAeArtifactOperationsClient):
        def get_artifact(self, *args: Any, **kwargs: Any) -> dict[str, Any] | None:
            raise AeArtifactOperationsError(
                error_code="ag.ae_artifact_lifecycle_source_failed",
                detail="AE lifecycle source unavailable",
                status_code=503,
            )

    source_failed = build_app(BrokenLifecycleClient()).get(
        f"/admin/v1/operations/artifacts/{ARTIFACT_ID}/lifecycle",
        headers=auth_headers(),
    )

    assert unauthorized.status_code == 401
    assert invalid_service.status_code == 400
    assert invalid_service.json()["error_code"] == "ag.ae_artifact_service_invalid"
    assert missing.status_code == 404
    assert source_failed.status_code == 503
    assert source_failed.json()["error_code"] == (
        "ag.ae_artifact_lifecycle_source_failed"
    )


def test_artifact_operation_route_can_disable_optional_reads() -> None:
    client = build_app(artifact_client())

    response = client.get(
        f"/admin/v1/operations/artifacts/{ARTIFACT_ID}",
        params={
            "interaction_id": INTERACTION_ID,
            "include_handoff": "false",
            "include_chat_links": "false",
        },
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert response.json()["handoff"] is None
    assert response.json()["chat_artifact_refs"] == []


def test_artifact_operation_route_auth_filter_missing_and_optional_error_edges() -> (
    None
):
    client = build_app(artifact_client())

    unauthorized = client.get(f"/admin/v1/operations/artifacts/{ARTIFACT_ID}")
    invalid_service = client.get(
        f"/admin/v1/operations/artifacts/{ARTIFACT_ID}",
        params={"service_id": "nex-cx"},
        headers=auth_headers(),
    )
    missing = client.get(
        "/admin/v1/operations/artifacts/missing",
        headers=auth_headers(),
    )

    class OptionalFailureClient(InMemoryAeArtifactOperationsClient):
        def get_artifact_handoff(
            self, *args: Any, **kwargs: Any
        ) -> dict[str, Any] | None:
            raise AeArtifactOperationsError(
                error_code="ag.optional_handoff_failed",
                detail="handoff unavailable",
            )

        def list_chat_artifact_refs(
            self, *args: Any, **kwargs: Any
        ) -> list[dict[str, Any]]:
            raise AeArtifactOperationsError(
                error_code="ag.optional_chat_links_failed",
                detail="chat links unavailable",
            )

    degraded_client = OptionalFailureClient(
        artifacts={ARTIFACT_ID: artifact_record(include_private=False)}
    )
    degraded = build_app(degraded_client).get(
        f"/admin/v1/operations/artifacts/{ARTIFACT_ID}",
        params={"interaction_id": INTERACTION_ID},
        headers=auth_headers(),
    )

    assert unauthorized.status_code == 401
    assert invalid_service.status_code == 400
    assert invalid_service.json()["error_code"] == "ag.ae_artifact_service_invalid"
    assert missing.status_code == 404
    assert degraded.status_code == 200
    assert degraded.json()["projection_status"] == "DEGRADED"
    assert len(degraded.json()["source_status"]["errors"]) == 2


def test_artifact_operation_route_reports_primary_source_error() -> None:
    class BrokenClient(InMemoryAeArtifactOperationsClient):
        def get_artifact(self, *args: Any, **kwargs: Any) -> dict[str, Any] | None:
            raise AeArtifactOperationsError(
                error_code="ag.ae_artifact_source_request_failed",
                detail="AE unavailable",
                status_code=502,
            )

    response = build_app(BrokenClient()).get(
        f"/admin/v1/operations/artifacts/{ARTIFACT_ID}",
        headers=auth_headers(),
    )

    assert response.status_code == 502
    assert response.json()["error_code"] == "ag.ae_artifact_source_request_failed"


class FakeHttpResponse:
    def __init__(self, status_code: int, payload: Any = None) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        if isinstance(self._payload, ValueError):
            raise self._payload
        return self._payload


def test_http_artifact_operations_client_requests_expected_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_get(
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, str],
        timeout: float,
    ) -> FakeHttpResponse:
        calls.append(
            {"url": url, "headers": headers, "params": params, "timeout": timeout}
        )
        if url.endswith("/api/v1/artifacts") and params.get("tenant_id"):
            return FakeHttpResponse(200, artifact_collection_payload())
        if url.endswith("/api/v1/artifact-retention/executions"):
            return FakeHttpResponse(
                200, artifact_retention_history_collection_payload()
            )
        if url.endswith("/api/v1/artifact-retention/batch-plan"):
            return FakeHttpResponse(200, artifact_retention_batch_plan_payload())
        if url.endswith("/api/v1/artifact-retention/scheduled-jobs"):
            return FakeHttpResponse(
                200,
                artifact_retention_scheduled_job_collection_payload(),
            )
        if url.endswith("/api/v1/artifact-retention/scheduler-daemon-config"):
            return FakeHttpResponse(
                200,
                artifact_retention_scheduler_daemon_config_payload(),
            )
        if url.endswith(f"/api/v1/artifacts/{ARTIFACT_ID}"):
            return FakeHttpResponse(200, artifact_record(include_private=False))
        if url.endswith(f"/api/v1/artifact-handoffs/{HANDOFF_ID}"):
            return FakeHttpResponse(200, handoff_record())
        if url.endswith(f"/api/v1/chat/interactions/{INTERACTION_ID}/artifact-links"):
            return FakeHttpResponse(200, {"artifact_refs": [chat_artifact_ref()]})
        return FakeHttpResponse(404, {})

    def fake_post(
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
        timeout: float,
    ) -> FakeHttpResponse:
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        if url.endswith("/api/v1/artifact-retention/scheduled-jobs/admission"):
            return FakeHttpResponse(
                200,
                artifact_retention_scheduled_dispatch_response_payload(),
            )
        if url.endswith("/api/v1/artifact-retention/scheduler-daemon-controls"):
            return FakeHttpResponse(
                200,
                artifact_retention_scheduler_daemon_dispatch_payload(),
            )
        return FakeHttpResponse(404, {})

    monkeypatch.setattr(artifact_operations.httpx, "get", fake_get)
    monkeypatch.setattr(artifact_operations.httpx, "post", fake_post)
    client = HttpAeArtifactOperationsClient(
        base_url="http://ae.example.local/",
        service_token="token-0409",
        timeout_seconds=12.5,
    )

    artifact = client.get_artifact(
        ARTIFACT_ID, request_id=REQUEST_ID, trace_id=TRACE_ID
    )
    handoff = client.get_artifact_handoff(
        HANDOFF_ID,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    refs = client.list_chat_artifact_refs(
        INTERACTION_ID,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    collection = client.list_artifacts(
        tenant_id="tenant-0409",
        workspace_id="workspace-0409",
        owner_user_id="user-0409",
        status="READY",
        limit=25,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    retention_history = client.list_artifact_retention_executions(
        tenant_id="tenant-0409",
        workspace_id="workspace-0409",
        owner_user_id="user-0409",
        mode="EXECUTE",
        execution_status="BLOCKED",
        limit=20,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    retention_batch_plan = client.get_artifact_retention_batch_plan(
        tenant_id="tenant-0409",
        workspace_id="workspace-0409",
        owner_user_id="user-0409",
        retention_days=30,
        as_of="2026-09-01T00:00:00Z",
        scan_limit=20,
        max_delete_count=1,
        checked_at="2026-09-01T02:30:00Z",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    retention_scheduled_jobs = client.list_artifact_retention_scheduled_jobs(
        tenant_id="tenant-0409",
        workspace_id="workspace-0409",
        owner_user_id="user-0409",
        status="QUEUED",
        limit=20,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    scheduled_dispatch = client.dispatch_artifact_retention_scheduled_job(
        batch_plan=artifact_retention_batch_plan_payload(),
        trigger_type="operator_dispatch",
        requested_at="2026-09-01T02:35:00Z",
        idempotency_key="dispatch-idem-0409",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    daemon_config = client.get_artifact_retention_scheduler_daemon_config(
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    daemon_dispatch = client.dispatch_artifact_retention_scheduler_daemon_control(
        action="manual_tick_once",
        tenant_id="tenant-0409",
        workspace_id="workspace-0409",
        owner_user_id="user-0409",
        retention_days=30,
        as_of="2026-09-01T00:00:00Z",
        scan_limit=20,
        max_delete_count=1,
        requested_at="2026-09-01T02:35:00Z",
        requested_by={
            "actor_type": "operator",
            "actor_id": "ag-retention-operator",
        },
        reason="manual AG dispatch",
        tick_at="2026-09-01T02:35:00Z",
        run_worker=True,
        worker_id="ae-retention-worker-0522",
        idempotency_key="daemon-idem-0522",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert artifact["artifact_id"] == ARTIFACT_ID
    assert handoff["artifact_handoff_id"] == HANDOFF_ID
    assert refs[0]["artifact_id"] == ARTIFACT_ID
    assert collection["count"] == 2
    assert retention_history["count"] == 3
    assert retention_batch_plan["plan_id"] == "retention-batch-plan-0409"
    assert retention_scheduled_jobs["count"] == 3
    assert scheduled_dispatch["enqueue_status"] == "ENQUEUED"
    assert daemon_config["daemon_config_schema_version"] == (
        "ae_artifact_retention_scheduler_daemon_config.v1"
    )
    assert daemon_dispatch["dispatch_status"] == "DISPATCHED"
    assert calls[0]["url"] == f"http://ae.example.local/api/v1/artifacts/{ARTIFACT_ID}"
    assert calls[0]["headers"]["Authorization"] == "Bearer token-0409"
    assert calls[0]["headers"]["X-Service-ID"] == "nex-ag"
    assert calls[0]["timeout"] == 12.5
    assert calls[3]["url"] == "http://ae.example.local/api/v1/artifacts"
    assert calls[3]["params"] == {
        "tenant_id": "tenant-0409",
        "workspace_id": "workspace-0409",
        "owner_user_id": "user-0409",
        "limit": "25",
        "status": "READY",
    }
    assert calls[4]["url"] == (
        "http://ae.example.local/api/v1/artifact-retention/executions"
    )
    assert calls[4]["params"] == {
        "tenant_id": "tenant-0409",
        "workspace_id": "workspace-0409",
        "owner_user_id": "user-0409",
        "limit": "20",
        "mode": "EXECUTE",
        "execution_status": "BLOCKED",
    }
    assert calls[5]["url"] == (
        "http://ae.example.local/api/v1/artifact-retention/batch-plan"
    )
    assert calls[5]["params"] == {
        "tenant_id": "tenant-0409",
        "workspace_id": "workspace-0409",
        "owner_user_id": "user-0409",
        "scan_limit": "20",
        "max_delete_count": "1",
        "retention_days": "30",
        "as_of": "2026-09-01T00:00:00Z",
        "checked_at": "2026-09-01T02:30:00Z",
    }
    assert calls[6]["url"] == (
        "http://ae.example.local/api/v1/artifact-retention/scheduled-jobs"
    )
    assert calls[6]["params"] == {
        "tenant_id": "tenant-0409",
        "workspace_id": "workspace-0409",
        "owner_user_id": "user-0409",
        "limit": "20",
        "status": "QUEUED",
    }
    assert calls[7]["url"] == (
        "http://ae.example.local/api/v1/artifact-retention/scheduled-jobs/admission"
    )
    assert calls[7]["headers"]["Idempotency-Key"] == "dispatch-idem-0409"
    assert calls[7]["json"]["trigger_type"] == "operator_dispatch"
    assert calls[7]["json"]["requested_at"] == "2026-09-01T02:35:00Z"
    assert calls[7]["json"]["idempotency_key"] == "dispatch-idem-0409"
    assert calls[7]["json"]["batch_plan"]["plan_id"] == "retention-batch-plan-0409"
    assert calls[8]["url"] == (
        "http://ae.example.local/api/v1/artifact-retention/"
        "scheduler-daemon-config"
    )
    assert calls[8]["params"] == {}
    assert calls[9]["url"] == (
        "http://ae.example.local/api/v1/artifact-retention/"
        "scheduler-daemon-controls"
    )
    assert calls[9]["headers"]["Idempotency-Key"] == "daemon-idem-0522"
    assert calls[9]["json"] == {
        "action": "manual_tick_once",
        "run_worker": True,
        "trace_id": TRACE_ID,
        "tenant_id": "tenant-0409",
        "workspace_id": "workspace-0409",
        "owner_user_id": "user-0409",
        "retention_days": 30,
        "as_of": "2026-09-01T00:00:00Z",
        "scan_limit": 20,
        "max_delete_count": 1,
        "requested_at": "2026-09-01T02:35:00Z",
        "requested_by": {
            "actor_type": "operator",
            "actor_id": "ag-retention-operator",
        },
        "reason": "manual AG dispatch",
        "tick_at": "2026-09-01T02:35:00Z",
        "worker_id": "ae-retention-worker-0522",
        "idempotency_key": "daemon-idem-0522",
    }


def test_http_artifact_operations_client_handles_404_and_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = [
        FakeHttpResponse(404, {}),
        FakeHttpResponse(404, {}),
        FakeHttpResponse(
            503,
            {
                "error_code": "ae.artifact_source_down",
                "detail": "source down",
            },
        ),
        FakeHttpResponse(500, ValueError("not json")),
        FakeHttpResponse(200, []),
    ]

    def fake_get(
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, str],
        timeout: float,
    ) -> FakeHttpResponse:
        return responses.pop(0)

    monkeypatch.setattr(artifact_operations.httpx, "get", fake_get)
    client = HttpAeArtifactOperationsClient(base_url="http://ae.example.local")

    assert (
        client.get_artifact(ARTIFACT_ID, request_id=REQUEST_ID, trace_id=TRACE_ID)
        is None
    )
    assert (
        client.list_chat_artifact_refs(
            INTERACTION_ID, request_id=REQUEST_ID, trace_id=TRACE_ID
        )
        == []
    )
    with pytest.raises(AeArtifactOperationsError) as problem:
        client.get_artifact(ARTIFACT_ID, request_id=REQUEST_ID, trace_id=TRACE_ID)
    with pytest.raises(AeArtifactOperationsError) as fallback:
        client.get_artifact(ARTIFACT_ID, request_id=REQUEST_ID, trace_id=TRACE_ID)
    assert client._get_json("/ok", request_id=REQUEST_ID, trace_id=TRACE_ID) == []
    assert artifact_operations._safe_response_json(FakeHttpResponse(500, [])) == {}
    assert problem.value.error_code == "ae.artifact_source_down"
    assert fallback.value.error_code == "ag.ae_artifact_source_request_failed"


def test_http_artifact_operations_client_dispatch_handles_post_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = [
        FakeHttpResponse(
            409,
            {
                "error_code": "ae.artifact_retention_scheduled_job_not_ready",
                "detail": "not ready",
            },
        ),
        FakeHttpResponse(500, ValueError("not json")),
    ]

    def fake_post(
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
        timeout: float,
    ) -> FakeHttpResponse:
        return responses.pop(0)

    monkeypatch.setattr(artifact_operations.httpx, "post", fake_post)
    client = HttpAeArtifactOperationsClient(base_url="http://ae.example.local")

    with pytest.raises(AeArtifactOperationsError) as not_ready:
        client.dispatch_artifact_retention_scheduled_job(
            batch_plan=artifact_retention_batch_plan_payload(),
            trigger_type="operator_dispatch",
            requested_at=None,
            idempotency_key=None,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    with pytest.raises(AeArtifactOperationsError) as fallback:
        client.dispatch_artifact_retention_scheduled_job(
            batch_plan=artifact_retention_batch_plan_payload(),
            trigger_type="operator_dispatch",
            requested_at=None,
            idempotency_key=None,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    def unreachable_post(*args: Any, **kwargs: Any) -> FakeHttpResponse:
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(artifact_operations.httpx, "post", unreachable_post)
    with pytest.raises(AeArtifactOperationsError) as unreachable:
        client.dispatch_artifact_retention_scheduled_job(
            batch_plan=artifact_retention_batch_plan_payload(),
            trigger_type="operator_dispatch",
            requested_at=None,
            idempotency_key=None,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert not_ready.value.error_code == "ae.artifact_retention_scheduled_job_not_ready"
    assert fallback.value.error_code == "ag.ae_artifact_source_request_failed"
    assert unreachable.value.error_code == "ag.ae_artifact_source_unreachable"


def test_http_artifact_operations_client_wraps_network_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get(
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, str],
        timeout: float,
    ) -> FakeHttpResponse:
        raise httpx.ConnectError("unreachable")

    monkeypatch.setattr(artifact_operations.httpx, "get", fake_get)
    client = HttpAeArtifactOperationsClient(base_url="http://ae.example.local")

    with pytest.raises(AeArtifactOperationsError) as error:
        client.get_artifact(ARTIFACT_ID, request_id=REQUEST_ID, trace_id=TRACE_ID)

    assert error.value.error_code == "ag.ae_artifact_source_unreachable"


def test_default_ae_artifact_operations_client_uses_env_and_timeout_defaults() -> None:
    defaulted = build_default_ae_artifact_operations_client({})
    configured = build_default_ae_artifact_operations_client(
        {
            NEX_AG_AE_ARTIFACT_BASE_URL_ENV: "http://ae.example.local/",
            NEX_AG_AE_ARTIFACT_SERVICE_TOKEN_ENV: "token-0409",
            NEX_AG_AE_ARTIFACT_TIMEOUT_SECONDS_ENV: "15",
        }
    )
    invalid_timeout = build_default_ae_artifact_operations_client(
        {NEX_AG_AE_ARTIFACT_TIMEOUT_SECONDS_ENV: "bad"}
    )
    negative_timeout = build_default_ae_artifact_operations_client(
        {NEX_AG_AE_ARTIFACT_TIMEOUT_SECONDS_ENV: "-1"}
    )

    assert configured.base_url == "http://ae.example.local"
    assert configured.service_token == "token-0409"
    assert configured.timeout_seconds == 15.0
    assert defaulted.timeout_seconds == DEFAULT_AE_ARTIFACT_TIMEOUT_SECONDS
    assert invalid_timeout.base_url == "http://127.0.0.1:8103"
    assert invalid_timeout.timeout_seconds == DEFAULT_AE_ARTIFACT_TIMEOUT_SECONDS
    assert negative_timeout.timeout_seconds == DEFAULT_AE_ARTIFACT_TIMEOUT_SECONDS


def test_artifact_operations_registered_on_main_app() -> None:
    from nex_ag.main import app

    paths = {route.path for route in app.routes}
    assert "/admin/v1/operations/artifacts" in paths
    assert "/admin/v1/operations/artifact-retention/executions" in paths
    assert "/admin/v1/operations/artifact-retention/batch-plan" in paths
    assert "/admin/v1/operations/artifact-retention/automation" in paths
    assert "/admin/v1/operations/artifact-retention/scheduler-daemon" in paths
    assert (
        "/admin/v1/operations/artifact-retention/scheduler-daemon/manual-tick-once"
        in paths
    )
    assert "/admin/v1/operations/artifact-retention/scheduled-jobs" in paths
    assert "/admin/v1/operations/artifact-retention/scheduled-jobs/dispatch" in paths
    assert "/admin/v1/operations/artifacts/{artifact_id}" in paths
    assert "/admin/v1/operations/artifacts/{artifact_id}/lifecycle" in paths
    assert AE_ARTIFACT_SOURCE_SERVICE_ID == "nex-ae-api"
