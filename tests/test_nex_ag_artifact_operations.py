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
    AG_ARTIFACT_OPERATION_RETENTION_DAEMON_ATTENTION_SCHEMA_VERSION,
    AG_ARTIFACT_OPERATION_RETENTION_DAEMON_LIFECYCLE_PROJECTION_SCHEMA_VERSION,
    AG_ARTIFACT_OPERATION_RETENTION_DAEMON_PROJECTION_SCHEMA_VERSION,
    AG_ARTIFACT_OPERATION_RETENTION_DAEMON_RUN_COLLECTION_PROJECTION_SCHEMA_VERSION,
    AG_ARTIFACT_OPERATION_RETENTION_DAEMON_RUN_DETAIL_PROJECTION_SCHEMA_VERSION,
    AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_COLLECTION_PROJECTION_SCHEMA_VERSION,
    AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_DETAIL_PROJECTION_SCHEMA_VERSION,
    AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_COLLECTION_PROJECTION_SCHEMA_VERSION,
    AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_DETAIL_PROJECTION_SCHEMA_VERSION,
    AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_PROJECTION_SCHEMA_VERSION,
    AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_PROJECTION_SCHEMA_VERSION,
    AG_ARTIFACT_OPERATION_RETENTION_DAEMON_SUPERVISOR_COLLECTION_PROJECTION_SCHEMA_VERSION,
    AG_ARTIFACT_OPERATION_RETENTION_DAEMON_SUPERVISOR_DETAIL_PROJECTION_SCHEMA_VERSION,
    AG_ARTIFACT_OPERATION_RETENTION_DAEMON_SUPERVISED_PROCESS_COLLECTION_PROJECTION_SCHEMA_VERSION,
    AG_ARTIFACT_OPERATION_RETENTION_DAEMON_SUPERVISED_PROCESS_DETAIL_PROJECTION_SCHEMA_VERSION,
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
    build_artifact_operation_retention_daemon_operator_control_execution_collection_projection,
    build_artifact_operation_retention_daemon_operator_control_execution_detail_projection,
    build_artifact_operation_retention_daemon_operator_control_execution_worker_result_collection_projection,
    build_artifact_operation_retention_daemon_operator_control_execution_worker_result_detail_projection,
    build_artifact_operation_retention_daemon_operator_control_execution_worker_projection,
    build_artifact_operation_retention_daemon_operator_control_projection,
    build_artifact_operation_retention_daemon_run_collection_projection,
    build_artifact_operation_retention_daemon_run_detail_projection,
    build_artifact_operation_retention_daemon_supervised_process_collection_projection,
    build_artifact_operation_retention_daemon_supervised_process_detail_projection,
    build_artifact_operation_retention_daemon_supervisor_collection_projection,
    build_artifact_operation_retention_daemon_supervisor_detail_projection,
    build_artifact_operation_retention_history_projection,
    build_artifact_operation_retention_scheduled_dispatch_projection,
    build_artifact_operation_retention_scheduled_job_projection,
    build_artifact_retention_daemon_lifecycle_projection,
    build_default_ae_artifact_operations_client,
    classify_artifact_retention_daemon_attention,
    register_artifact_operation_routes,
    summarize_artifact_operation_collection,
    summarize_artifact_operation_detail,
    summarize_artifact_operation_lifecycle,
    summarize_artifact_retention_batch_operations,
    summarize_artifact_retention_automation_operations,
    summarize_artifact_retention_daemon_operations,
    summarize_artifact_retention_daemon_operator_control_projection,
    summarize_artifact_retention_daemon_operator_control_execution_detail,
    summarize_artifact_retention_daemon_operator_control_execution_operations,
    summarize_artifact_retention_daemon_operator_control_execution_worker_result,
    summarize_artifact_retention_daemon_operator_control_execution_worker_result_operations,
    summarize_artifact_retention_daemon_lifecycle_projection,
    summarize_artifact_retention_daemon_run_detail,
    summarize_artifact_retention_daemon_run_operations,
    summarize_artifact_retention_daemon_supervised_process_detail,
    summarize_artifact_retention_daemon_supervised_process_operations,
    summarize_artifact_retention_daemon_supervisor_detail,
    summarize_artifact_retention_daemon_supervisor_operations,
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


def artifact_retention_scheduler_daemon_runtime_payload(
    *,
    status: str = "BUSY",
    active_job_id: str | None = "daemon-loop-plan-0538",
    observed: bool = True,
    heartbeat_store_available: bool = True,
    runtime_state: dict[str, Any] | None = None,
    bounded_loop_result: dict[str, Any] | None = None,
    shutdown_transition: dict[str, Any] | None = None,
    retry_circuit_guard: dict[str, Any] | None = None,
) -> dict[str, Any]:
    heartbeat = None
    if observed:
        heartbeat = {
            "heartbeat_schema_version": "worker_heartbeat.v1",
            "service_id": "nex-ae-api",
            "worker_id": "ae-retention-daemon-runtime-0538",
            "worker_type": "ae.artifact_retention.scheduler_daemon",
            "status": status,
            "active_job_id": active_job_id,
            "trace_id": TRACE_ID,
            "started_at": "2026-09-01T02:30:00Z",
            "last_seen_at": "2026-09-01T02:40:00Z",
            "metadata": {
                "scheduler_id": "ae-artifact-retention-scheduler",
                "daemon_loop_plan_id": "daemon-loop-plan-0538",
                "phase": "tick_once_running",
                "loop_decision_status": "READY",
                "loop_decision_reason": None,
                "tick_once_result_status": None,
                "tick_once_skip_reason": None,
                "database_url": "DATABASE_URL_SHOULD_NOT_LEAK",
                "one_cycle_only": True,
                "scheduler_daemon_started": False,
                "continuous_loop_started": False,
                "physical_delete_automation_enabled": False,
            },
        }
    payload = {
        "runtime_observation_schema_version": (
            "ae_artifact_retention_scheduler_daemon_runtime_observation.v1"
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": "ae-artifact-retention-scheduler",
        "checked_at": "2026-09-01T02:41:00Z",
        "worker_type": "ae.artifact_retention.scheduler_daemon",
        "heartbeat_store": {
            "available": heartbeat_store_available,
            "backend": (
                "SqlAlchemyWorkerHeartbeatStore"
                if heartbeat_store_available
                else "not_configured"
            ),
            "failure_code": None if heartbeat_store_available else "unavailable",
        },
        "heartbeat": heartbeat,
        "heartbeat_count": 1 if observed else 0,
        "daemon_config_checked_at": "2026-09-01T02:30:00Z",
        "guardrails": {
            "metadata_only": True,
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
            "scheduler_daemon_started": False,
            "continuous_loop_started": False,
            "physical_delete_automation_enabled": False,
            "heartbeat_observation_read_only": True,
        },
        "metadata": {
            "metadata_only": True,
            "heartbeat_observed": observed,
            "heartbeat_store_available": heartbeat_store_available,
            "database_url_included": False,
            "storage_path_included": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_included": False,
            "scheduler_daemon_started": False,
            "continuous_loop_started": False,
            "physical_delete_automation_enabled": False,
        },
    }
    if runtime_state is not None:
        payload["runtime_state"] = runtime_state
    if bounded_loop_result is not None:
        payload["bounded_loop_result"] = bounded_loop_result
    if shutdown_transition is not None:
        payload["shutdown_transition"] = shutdown_transition
    if retry_circuit_guard is not None:
        payload["retry_circuit_guard"] = retry_circuit_guard
    return payload


def artifact_retention_scheduler_daemon_runtime_state_payload(
    *,
    lifecycle_status: str = "RUNNING",
    lifecycle_reason: str | None = "started",
    stop_requested: bool = False,
    shutdown_requested_at: str | None = None,
    last_cycle_status: str | None = "SUCCEEDED",
    consecutive_failure_count: int = 0,
) -> dict[str, Any]:
    last_cycle = None
    if last_cycle_status is not None:
        last_cycle = {
            "run_at": "2026-09-01T02:39:00Z",
            "result_status": last_cycle_status,
            "skip_reason": None,
            "error_code": (
                "ae.retention_daemon_cycle_failed"
                if last_cycle_status == "FAILED"
                else None
            ),
            "duration_ms": 1500,
        }
    return {
        "daemon_runtime_state_schema_version": (
            "ae_artifact_retention_scheduler_daemon_runtime_state.v1"
        ),
        "daemon_runtime_state_id": "ae-daemon-runtime-state-0548",
        "service_id": "nex-ae-api",
        "scheduler_id": "ae-artifact-retention-scheduler",
        "daemon_instance_id": "ae-retention-daemon-runtime-0548",
        "observed_at": "2026-09-01T02:41:00Z",
        "lifecycle_status": lifecycle_status,
        "lifecycle_reason": lifecycle_reason,
        "stop_requested": stop_requested,
        "shutdown_requested_at": shutdown_requested_at,
        "last_cycle": last_cycle,
        "next_tick_at": None if stop_requested else "2026-09-01T02:55:00Z",
        "cycle_count": 3,
        "consecutive_failure_count": consecutive_failure_count,
        "heartbeat_worker_id": "ae-retention-daemon-runtime-0538",
        "guardrails": {
            "metadata_only": True,
            "state_snapshot_only": True,
            "daemon_process_owner_ae": True,
            "daemon_as_jobqueue_job_allowed": False,
            "retention_work_uses_job_queue": True,
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
        },
        "metadata": {
            "metadata_only": True,
            "safe_for_ag_projection": True,
            "state_snapshot_only": True,
            "lifecycle_running": lifecycle_status == "RUNNING",
            "lifecycle_stopped": lifecycle_status == "STOPPED",
            "lifecycle_error": lifecycle_status == "ERROR",
            "stop_requested": stop_requested,
            "shutdown_requested": shutdown_requested_at is not None,
            "last_cycle_present": last_cycle is not None,
            "last_cycle_failed": last_cycle_status == "FAILED",
            "consecutive_failures_present": consecutive_failure_count > 0,
        },
    }


def artifact_retention_scheduler_daemon_bounded_loop_result_payload(
    *,
    result_status: str = "SUCCEEDED",
    stop_reason: str = "max_cycles_reached",
    final_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "daemon_bounded_loop_result_schema_version": (
            "ae_artifact_retention_scheduler_daemon_bounded_loop_result.v1"
        ),
        "daemon_bounded_loop_result_id": "ae-daemon-bounded-loop-0548",
        "service_id": "nex-ae-api",
        "scheduler_id": "ae-artifact-retention-scheduler",
        "daemon_instance_id": "ae-retention-daemon-runtime-0548",
        "result_status": result_status,
        "stop_reason": stop_reason,
        "started_at": "2026-09-01T02:30:00Z",
        "finished_at": "2026-09-01T02:41:00Z",
        "max_cycles": 3,
        "cycle_count": 3,
        "consecutive_failure_count": 1 if result_status == "FAILED" else 0,
        "final_state": final_state,
        "guardrails": {
            "metadata_only": True,
            "bounded_loop_is_finite": True,
            "continuous_loop_started": False,
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
        },
        "metadata": {
            "metadata_only": True,
            "safe_for_ag_projection": True,
            "bounded_loop_started": True,
            "stopped_by_max_cycles": stop_reason == "max_cycles_reached",
            "tick_once_ran": True,
            "job_enqueued": True,
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
    start_stop_guardrail = None
    if action in {"start_daemon", "stop_daemon"}:
        guardrail_status = "BLOCKED" if action == "start_daemon" else "NOOP"
        guardrail_reason = (
            "daemon_disabled_by_policy"
            if action == "start_daemon"
            else "daemon_not_running"
        )
        start_stop_guardrail = {
            "daemon_start_stop_guardrail_schema_version": (
                "ae_artifact_retention_scheduler_daemon_start_stop_guardrail.v1"
            ),
            "daemon_start_stop_guardrail_id": "daemon-start-stop-guardrail-0535",
            "service_id": "nex-ae-api",
            "scheduler_id": config["scheduler_id"],
            "action": action,
            "guardrail_status": guardrail_status,
            "guardrail_reason": guardrail_reason,
            "requested_at": "2026-09-01T02:35:00Z",
            "control_plan": control_plan,
            "action_allowed": False,
            "runtime_state_transition": "NONE",
            "execution_plan": {
                "requires_control_plan": True,
                "requires_lease": False,
                "runs_tick_once": False,
                "dispatches_job_queue": False,
                "starts_daemon": False,
                "stops_daemon": False,
                "sends_stop_signal": False,
                "starts_continuous_loop": False,
                "runtime_state_mutated": False,
                "writes_history": False,
                "physical_delete_enabled": False,
                "mirrors_control_action": action,
            },
            "guardrails": {
                **config["guardrails"],
                "start_stop_control_guardrail_required": True,
                "start_control_enabled": False,
                "stop_control_enabled": False,
                "start_daemon_allowed": False,
                "stop_runtime_mutation_allowed": False,
                "stop_signal_allowed": False,
                "runtime_state_mutation_allowed": False,
                "future_supervisor_required_before_start": True,
            },
            "metadata": {
                "metadata_only": True,
                "database_url_included": False,
                "storage_path_included": False,
                "raw_artifact_payload_included": False,
                "raw_execution_payload_included": False,
                "safe_for_ag_projection": True,
                "start_stop_guardrail_evaluated": True,
                "start_action": action == "start_daemon",
                "stop_action": action == "stop_daemon",
                "guardrail_blocked": guardrail_status == "BLOCKED",
                "guardrail_noop": guardrail_status == "NOOP",
                "policy_reason_present": True,
                "action_allowed": False,
                "runtime_state_mutated": False,
                "stop_signal_sent": False,
                "tick_once_dispatched": False,
                "lease_acquired_before_tick": False,
                "lease_released": False,
                "job_enqueued": False,
                "worker_executed": False,
                "history_write_executed": False,
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
        "start_stop_guardrail": start_stop_guardrail,
        "guardrails": {
            **config["guardrails"],
            "daemon_control_plan_required": True,
            "tick_once_requires_ready_control_plan": True,
            "start_stop_guardrail_required_for_start_stop": True,
            "start_stop_runtime_mutation_allowed": False,
            "stop_signal_allowed": False,
        },
        "metadata": {
            "metadata_only": True,
            "database_url_included": False,
            "storage_path_included": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_included": False,
            "control_plan_ready": dispatch_status == "DISPATCHED",
            "tick_once_dispatched": dispatch_status == "DISPATCHED",
            "start_stop_guardrail_evaluated": start_stop_guardrail is not None,
            "lease_acquired_before_tick": False,
            "lease_released": False,
            "job_enqueued": dispatch_status == "DISPATCHED",
            "worker_executed": False,
            "runtime_state_mutated": False,
            "stop_signal_sent": False,
            "scheduler_daemon_started": False,
            "continuous_loop_started": False,
            "physical_delete_automation_enabled": False,
        },
    }


def artifact_retention_scheduler_daemon_operator_control_policy_payload() -> (
    dict[str, Any]
):
    return (
        artifact_operations._empty_artifact_retention_scheduler_daemon_operator_control_policy_payload(
            checked_at="2026-09-03T02:00:00Z"
        )
    )


def artifact_retention_scheduler_daemon_operator_control_facade_payload(
    *,
    action: str = "restart_daemon",
    current_process: dict[str, Any] | None = None,
) -> dict[str, Any]:
    process = current_process or {
        "process_source": "read_model",
        "process_status": "RUNNING",
        "process_running": True,
        "daemon_supervised_process_id": "daemon-supervised-process-0587",
        "daemon_supervisor_command_id": "daemon-supervisor-command-0587",
        "process_id": 5870,
        "host_id": "ae-worker-0587",
        "observed_at": "2026-09-03T02:00:00Z",
    }
    facade = (
        artifact_operations._memory_artifact_retention_scheduler_daemon_operator_control_preview_payload(
            action=action,
            operator_subject={
                "actor_type": "operator",
                "actor_id": "ag-retention-operator",
                "tenant_id": "tenant-0409",
                "workspace_id": "workspace-0409",
                "database_url": "DATABASE_URL_SHOULD_NOT_LEAK",
            },
            idempotency_key="operator-control-idem-0587",
            reason="preview restart",
            requested_at="2026-09-03T02:00:00Z",
            checked_at="2026-09-03T02:00:00Z",
            profile="test",
            enabled=True,
            explicit_opt_in=True,
            max_cycles=2,
            run_worker=False,
            approval={
                "approved": True,
                "approved_by": "ag-retention-lead",
                "approved_at": "2026-09-03T01:59:00Z",
                "approval_reason": "maintenance",
            },
            current_process=process,
        )
    )
    facade["operator_control_command_preview"]["supervisor_command_previews"][0][
        "supervisor_command"
    ]["private_path"] = "/data/nex-platform/ae/private"
    facade["operator_control_admission"]["current_process"][
        "database_url"
    ] = "DATABASE_URL_SHOULD_NOT_LEAK"
    facade["operator_control_request"]["reason"] = "SECRET_SYSTEM_PROMPT"
    return facade


def artifact_retention_scheduler_daemon_operator_control_execution_state_payload(
    *,
    state_id: str = "operator-control-execution-state-0597",
    action: str = "restart_daemon",
    execution_status: str = "ADMITTED",
    idempotency_status: str = "NEW",
    observed_at: str = "2026-09-04T02:00:00Z",
) -> dict[str, Any]:
    allowed_next_statuses = {
        "ADMITTED": ["EXECUTING", "BLOCKED"],
        "EXECUTING": ["SUCCEEDED", "FAILED"],
    }.get(execution_status, [])
    return {
        "operator_control_execution_state_schema_version": (
            "ae_artifact_retention_scheduler_daemon_operator_control_execution_state.v1"
        ),
        "operator_control_execution_state_id": state_id,
        "service_id": "nex-ae-api",
        "scheduler_id": "ae-artifact-retention-scheduler",
        "operator_control_execution_request_id": (
            f"{state_id}:execution-request"
        ),
        "operator_control_facade_id": "operator-control-facade-0587",
        "operator_control_request_id": "operator-control-request-0587",
        "operator_control_admission_id": "operator-control-admission-0587",
        "operator_control_command_preview_id": (
            "operator-control-command-preview-0587"
        ),
        "action": action,
        "execution_mode": "fake_dry_run_supervisor_persistent_dispatch",
        "execution_status": execution_status,
        "idempotency_key": f"{state_id}:idempotency-secret",
        "idempotency_status": idempotency_status,
        "decision_reason": "operator_control_execution_admitted",
        "observed_at": observed_at,
        "prior_execution_state_id": None,
        "operator_control_execution_request_hash": "a" * 64,
        "operator_control_execution_request": {
            "private_path": "/data/nex-platform/ae/private",
            "database_url": "DATABASE_URL_SHOULD_NOT_LEAK",
            "reason": "SECRET_SYSTEM_PROMPT",
        },
        "allowed_next_statuses": allowed_next_statuses,
        "summary": {
            "scheduler_id": "ae-artifact-retention-scheduler",
            "operator_control_execution_state_id": state_id,
            "operator_control_execution_request_id": (
                f"{state_id}:execution-request"
            ),
            "action": action,
            "execution_status": execution_status,
            "idempotency_status": idempotency_status,
            "decision_reason": "operator_control_execution_admitted",
            "allowed_next_statuses": allowed_next_statuses,
            "safe_for_ag_projection": True,
            "database_url": "DATABASE_URL_SHOULD_NOT_LEAK",
        },
        "guardrails": {
            "metadata_only": True,
            "state_machine_only": True,
            "operator_control_execution_request_validated": True,
            "idempotency_key_required": True,
            "idempotency_key_scoped_to_request": True,
            "idempotency_replay_blocks_duplicate_dispatch": (
                idempotency_status == "REPLAYED"
            ),
            "idempotency_conflict_blocks_dispatch": (
                idempotency_status == "CONFLICT"
            ),
            "admitted_allows_execution_transition": (
                execution_status == "ADMITTED"
            ),
            "executing_allows_terminal_transition": (
                execution_status == "EXECUTING"
            ),
            "terminal_state": execution_status
            in {"SUCCEEDED", "FAILED", "BLOCKED", "NOOP"},
            "supervisor_dispatch_performed": False,
            "supervisor_adapter_invoked": False,
            "subprocess_started": False,
            "subprocess_stopped": False,
            "database_write_performed": False,
            "job_queue_enqueue_performed": False,
            "worker_execution_performed": False,
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
            "ag_direct_process_control_allowed": False,
            "physical_delete_automation_enabled": False,
            "database_url_included": False,
            "raw_execution_payload_included": False,
            "secrets_redacted": True,
        },
        "metadata": {
            "safe_for_ag_projection": True,
            "metadata_only": True,
            "execution_state_machine_only": True,
            "operator_control_execution_request_hash": "a" * 64,
            "observed_at": observed_at,
            "source_facade_status": "READY",
            "execution_mode": "fake_dry_run_supervisor_persistent_dispatch",
            "execution_status": execution_status,
            "idempotency_status": idempotency_status,
            "idempotency_replayed": idempotency_status == "REPLAYED",
            "idempotency_conflict": idempotency_status == "CONFLICT",
            "allowed_next_statuses": allowed_next_statuses,
            "supervisor_command_count": 2,
            "supervisor_actions": ["stop_daemon", "start_daemon"],
            "supervisor_dispatch_performed": False,
            "supervisor_adapter_invoked": False,
            "subprocess_started": False,
            "subprocess_stopped": False,
            "database_write_performed": False,
            "job_queue_enqueue_performed": False,
            "worker_execution_performed": False,
            "private_path": "/data/nex-platform/ae/private",
            "secrets_redacted": True,
        },
    }


def artifact_retention_scheduler_daemon_operator_control_execution_transition_payload(
    *,
    state: dict[str, Any] | None = None,
    to_status: str = "EXECUTING",
    transitioned_at: str = "2026-09-04T02:01:00Z",
) -> dict[str, Any]:
    execution_state = (
        state
        or artifact_retention_scheduler_daemon_operator_control_execution_state_payload()
    )
    from_status = execution_state["execution_status"]
    return {
        "operator_control_execution_state_transition_schema_version": (
            "ae_artifact_retention_scheduler_daemon_operator_control_execution_state_transition.v1"
        ),
        "operator_control_execution_state_transition_id": (
            f"{execution_state['operator_control_execution_state_id']}:{to_status}"
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": execution_state["scheduler_id"],
        "operator_control_execution_state_id": (
            execution_state["operator_control_execution_state_id"]
        ),
        "operator_control_execution_request_id": (
            execution_state["operator_control_execution_request_id"]
        ),
        "from_status": from_status,
        "to_status": to_status,
        "decision_reason": "operator_control_execution_transition_recorded",
        "transitioned_at": transitioned_at,
        "operator_control_execution_state": {
            **execution_state,
            "database_url": "DATABASE_URL_SHOULD_NOT_LEAK",
        },
        "summary": {
            "scheduler_id": execution_state["scheduler_id"],
            "operator_control_execution_state_transition_id": (
                f"{execution_state['operator_control_execution_state_id']}:{to_status}"
            ),
            "operator_control_execution_state_id": (
                execution_state["operator_control_execution_state_id"]
            ),
            "from_status": from_status,
            "to_status": to_status,
            "transitioned_at": transitioned_at,
            "safe_for_ag_projection": True,
            "database_url": "DATABASE_URL_SHOULD_NOT_LEAK",
        },
        "guardrails": {
            "metadata_only": True,
            "state_transition_only": True,
            "source_state_validated": True,
            "transition_allowed": True,
            "admitted_to_executing": from_status == "ADMITTED"
            and to_status == "EXECUTING",
            "supervisor_dispatch_performed": False,
            "supervisor_adapter_invoked": False,
            "subprocess_started": False,
            "subprocess_stopped": False,
            "database_write_performed": False,
            "job_queue_enqueue_performed": False,
            "worker_execution_performed": False,
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
            "ag_direct_process_control_allowed": False,
            "physical_delete_automation_enabled": False,
            "database_url_included": False,
            "raw_execution_payload_included": False,
            "secrets_redacted": True,
        },
        "metadata": {
            "safe_for_ag_projection": True,
            "metadata_only": True,
            "execution_state_transition_only": True,
            "operator_control_execution_state_hash": "b" * 64,
            "transitioned_at": transitioned_at,
            "from_status": from_status,
            "to_status": to_status,
            "source_idempotency_status": execution_state["idempotency_status"],
            "to_terminal": to_status in {"SUCCEEDED", "FAILED", "BLOCKED"},
            "supervisor_dispatch_performed": False,
            "supervisor_adapter_invoked": False,
            "subprocess_started": False,
            "subprocess_stopped": False,
            "database_write_performed": False,
            "job_queue_enqueue_performed": False,
            "worker_execution_performed": False,
            "private_path": "/data/nex-platform/ae/private",
            "secrets_redacted": True,
        },
    }


def artifact_retention_scheduler_daemon_operator_control_execution_collection_payload() -> (
    dict[str, Any]
):
    records = [
        artifact_retention_scheduler_daemon_operator_control_execution_state_payload(),
        artifact_retention_scheduler_daemon_operator_control_execution_state_payload(
            state_id="operator-control-execution-state-conflict-0597",
            execution_status="FAILED",
            idempotency_status="CONFLICT",
            observed_at="2026-09-04T02:05:00Z",
        ),
    ]
    return {
        "operator_control_execution_collection_schema_version": (
            "ae_artifact_retention_scheduler_daemon_operator_control_execution_collection.v1"
        ),
        "service_id": "nex-ae-api",
        "filter": {
            "scheduler_id": "ae-artifact-retention-scheduler",
            "action": None,
            "execution_status": None,
            "idempotency_status": None,
        },
        "count": len(records),
        "limit": 20,
        "items": records,
        "guardrails": {
            "read_only": True,
            "ae_owned_persistence": True,
            "ae_owned_execution_state": True,
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
            "ag_direct_process_control_allowed": False,
            "supervisor_dispatch_performed": False,
            "physical_delete_automation_enabled": False,
            "database_url_included": False,
            "raw_execution_payload_included": False,
            "secrets_redacted": True,
        },
        "metadata": {
            "safe_for_ag_projection": True,
            "metadata_only": True,
            "read_model": "ae_daemon_operator_control_execution_states",
            "item_count": len(records),
            "limit": 20,
            "has_more": False,
            "newest_observed_at": records[1]["observed_at"],
            "database_url_included": False,
            "raw_execution_payload_included": False,
            "private_path": "/data/nex-platform/ae/private",
            "secrets_redacted": True,
        },
    }


def artifact_retention_scheduler_daemon_operator_control_execution_detail_payload() -> (
    dict[str, Any]
):
    state = artifact_retention_scheduler_daemon_operator_control_execution_state_payload()
    transitions = [
        artifact_retention_scheduler_daemon_operator_control_execution_transition_payload(
            state=state
        )
    ]
    return {
        "operator_control_execution_detail_schema_version": (
            "ae_artifact_retention_scheduler_daemon_operator_control_execution_detail.v1"
        ),
        "service_id": "nex-ae-api",
        "operator_control_execution_state_id": (
            state["operator_control_execution_state_id"]
        ),
        "execution_state": state,
        "transition_count": len(transitions),
        "transitions": transitions,
        "guardrails": {
            "read_only": True,
            "ae_owned_persistence": True,
            "ae_owned_execution_state": True,
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
            "ag_direct_process_control_allowed": False,
            "supervisor_dispatch_performed": False,
            "physical_delete_automation_enabled": False,
            "database_url_included": False,
            "raw_execution_payload_included": False,
            "secrets_redacted": True,
        },
        "metadata": {
            "safe_for_ag_projection": True,
            "metadata_only": True,
            "read_model": (
                "ae_artifact_retention_scheduler_daemon_operator_control_execution_detail"
            ),
            "operator_control_execution_state_id": (
                state["operator_control_execution_state_id"]
            ),
            "transition_count": len(transitions),
            "transition_statuses": ["ADMITTED->EXECUTING"],
            "database_url_included": False,
            "raw_execution_payload_included": False,
            "private_path": "/data/nex-platform/ae/private",
            "secrets_redacted": True,
        },
    }


def artifact_retention_scheduler_daemon_operator_control_execution_worker_result_payload(
    *,
    worker_status: str = "SUCCEEDED",
    supervisor_result_statuses: list[str] | None = None,
) -> dict[str, Any]:
    statuses = supervisor_result_statuses or ["SUCCEEDED", "SUCCEEDED"]
    return {
        "operator_control_execution_worker_result_schema_version": (
            "ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_result.v1"
        ),
        "operator_control_execution_worker_result_id": (
            "operator-control-execution-worker-result-0607"
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": "ae-artifact-retention-scheduler",
        "operator_control_execution_worker_command_id": (
            "operator-control-execution-worker-command-0607"
        ),
        "operator_control_execution_worker_plan_id": (
            "operator-control-execution-worker-plan-0607"
        ),
        "operator_control_execution_worker_transition_plan_id": (
            "operator-control-execution-worker-transition-plan-0607"
        ),
        "operator_control_execution_state_id": (
            "operator-control-execution-state-0597"
        ),
        "operator_control_execution_request_id": (
            "operator-control-execution-state-0597:execution-request"
        ),
        "action": "restart_daemon",
        "execution_mode": "fake_dry_run_supervisor_persistent_dispatch",
        "worker_mode": "fake_dry_run_supervisor_dispatch",
        "worker_status": worker_status,
        "decision_reason": "fake_dry_run_worker_completed",
        "observed_at": "2026-09-04T02:02:00Z",
        "operator_control_execution_worker_command": {
            "operator_control_execution_worker_command_id": (
                "operator-control-execution-worker-command-0607"
            ),
            "operator_control_execution_worker_plan": {
                "operator_control_execution_worker_plan_id": (
                    "operator-control-execution-worker-plan-0607"
                ),
                "plan_status": "READY",
                "operator_control_execution_state": {
                    "database_url": "DATABASE_URL_SHOULD_NOT_LEAK",
                    "reason": "SECRET_SYSTEM_PROMPT",
                },
            },
            "command_status": "READY",
            "private_path": "/data/nex-platform/ae/private",
        },
        "operator_control_execution_worker_transition_plan": {
            "operator_control_execution_worker_transition_plan_id": (
                "operator-control-execution-worker-transition-plan-0607"
            ),
            "transition_plan_status": "READY",
            "terminal_status": worker_status,
            "transition_count": 2,
            "metadata": {
                "status_path": ["ADMITTED", "EXECUTING", worker_status],
                "database_url_included": False,
            },
        },
        "supervisor_result_count": len(statuses),
        "supervisor_results": [
            {
                "daemon_supervisor_result_id": f"supervisor-result-0607-{index}",
                "action": action,
                "result_status": status,
                "metadata": {
                    "supervisor_adapter_invoked": True,
                    "process_started": action == "start_daemon",
                    "process_stopped": action == "stop_daemon",
                    "private_path": "/data/nex-platform/ae/private",
                },
            }
            for index, (action, status) in enumerate(
                zip(["stop_daemon", "start_daemon"], statuses, strict=True),
                start=1,
            )
        ],
        "guardrails": {
            "worker_result_only": True,
            "source_worker_command_validated": True,
            "source_transition_plan_validated": True,
            "requires_ready_worker_command": True,
            "source_worker_command_ready": True,
            "ready_transition_plan_required": True,
            "source_transition_plan_ready": True,
            "transition_terminal_matches_worker_status": True,
            "fake_dry_run_worker_only": True,
            "uses_existing_supervisor_runner": True,
            "uses_fake_supervisor_adapter_first": True,
            "supervisor_dispatch_performed": True,
            "supervisor_adapter_invoked": True,
            "supervisor_result_persisted": False,
            "supervisor_event_persisted": False,
            "subprocess_started": True,
            "subprocess_stopped": True,
            "database_write_performed": False,
            "job_queue_enqueue_performed": False,
            "worker_execution_performed": True,
            "transition_persistence_performed": False,
            "worker_succeeded": worker_status == "SUCCEEDED",
            "worker_failed": worker_status == "FAILED",
            "worker_blocked": worker_status == "BLOCKED",
            "test_profile_required": True,
            "bounded_max_cycles_required": True,
            "database_url_included": False,
            "storage_path_included": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_included": False,
            "raw_daemon_runtime_payload_included": False,
            "raw_supervised_process_snapshot_included": False,
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
            "ag_direct_process_control_allowed": False,
            "physical_delete_automation_enabled": False,
            "secrets_redacted": True,
        },
        "metadata": {
            "safe_for_ag_projection": True,
            "metadata_only": True,
            "worker_result_only": True,
            "operator_control_execution_worker_command_hash": "c" * 64,
            "operator_control_execution_worker_transition_plan_hash": "d" * 64,
            "observed_at": "2026-09-04T02:02:00Z",
            "worker_status": worker_status,
            "decision_reason": "fake_dry_run_worker_completed",
            "transition_plan_status": "READY",
            "transition_terminal_status": worker_status,
            "status_path": ["ADMITTED", "EXECUTING", worker_status],
            "supervisor_result_count": len(statuses),
            "supervisor_result_statuses": statuses,
            "supervisor_actions": ["stop_daemon", "start_daemon"],
            "supervisor_result_ids": [
                f"supervisor-result-0607-{index}" for index in range(1, 3)
            ],
            "supervisor_dispatch_performed": True,
            "supervisor_adapter_invoked": True,
            "supervisor_result_persisted": False,
            "supervisor_event_persisted": False,
            "subprocess_started": True,
            "subprocess_stopped": True,
            "database_write_performed": False,
            "job_queue_enqueue_performed": False,
            "worker_execution_performed": True,
            "transition_persistence_performed": False,
            "physical_delete_automation_enabled": False,
            "database_url_included": False,
            "storage_path_included": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_included": False,
            "raw_daemon_runtime_payload_included": False,
            "raw_supervised_process_snapshot_included": False,
            "private_path": "/data/nex-platform/ae/private",
            "secrets_redacted": True,
        },
    }


def artifact_retention_scheduler_daemon_operator_control_execution_worker_result_record_payload(
    *,
    worker_status: str = "SUCCEEDED",
    observed_at: str = "2026-09-04T02:02:00Z",
) -> dict[str, Any]:
    source = (
        artifact_retention_scheduler_daemon_operator_control_execution_worker_result_payload(
            worker_status=worker_status,
            supervisor_result_statuses=(
                ["FAILED", "SUCCEEDED"]
                if worker_status == "FAILED"
                else ["SUCCEEDED", "SUCCEEDED"]
            ),
        )
    )
    return {
        "operator_control_execution_worker_result_record_schema_version": (
            "ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_record.v1"
        ),
        "operator_control_execution_worker_result_id": (
            source["operator_control_execution_worker_result_id"]
        ),
        "service_id": source["service_id"],
        "scheduler_id": source["scheduler_id"],
        "operator_control_execution_worker_command_id": source[
            "operator_control_execution_worker_command_id"
        ],
        "operator_control_execution_worker_plan_id": source[
            "operator_control_execution_worker_plan_id"
        ],
        "operator_control_execution_worker_transition_plan_id": source[
            "operator_control_execution_worker_transition_plan_id"
        ],
        "operator_control_execution_state_id": source[
            "operator_control_execution_state_id"
        ],
        "operator_control_execution_request_id": source[
            "operator_control_execution_request_id"
        ],
        "action": source["action"],
        "execution_mode": source["execution_mode"],
        "worker_mode": source["worker_mode"],
        "worker_status": worker_status,
        "decision_reason": source["decision_reason"],
        "observed_at": observed_at,
        "transition_plan_status": "READY",
        "transition_terminal_status": worker_status,
        "transition_count": 2,
        "status_path": ["ADMITTED", "EXECUTING", worker_status],
        "supervisor_result_count": source["supervisor_result_count"],
        "supervisor_result_statuses": source["metadata"][
            "supervisor_result_statuses"
        ],
        "supervisor_actions": source["metadata"]["supervisor_actions"],
        "supervisor_result_ids": source["metadata"]["supervisor_result_ids"],
        "operator_control_execution_worker_command_hash": "c" * 64,
        "operator_control_execution_worker_transition_plan_hash": "d" * 64,
        "supervisor_results_hash": "e" * 64,
        "worker_result_hash": "f" * 64,
        "metadata": {
            **source["metadata"],
            "read_model": "ae_op_exec_worker_results",
            "private_path": "/data/nex-platform/ae/private",
            "database_url": "DATABASE_URL_SHOULD_NOT_LEAK",
        },
        "guardrails": {
            **source["guardrails"],
            "read_only": True,
            "ae_owned_worker_result": True,
            "database_url_included": False,
            "storage_path_included": False,
            "raw_execution_payload_included": False,
            "secrets_redacted": True,
        },
    }


def artifact_retention_scheduler_daemon_operator_control_execution_worker_result_collection_payload() -> (
    dict[str, Any]
):
    items = [
        artifact_retention_scheduler_daemon_operator_control_execution_worker_result_record_payload(),
        {
            **artifact_retention_scheduler_daemon_operator_control_execution_worker_result_record_payload(
                worker_status="FAILED",
                observed_at="2026-09-04T02:05:00Z",
            ),
            "operator_control_execution_worker_result_id": (
                "operator-control-execution-worker-result-failed-0616"
            ),
        },
    ]
    return {
        "operator_control_execution_worker_result_collection_schema_version": (
            "ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_collection.v1"
        ),
        "service_id": "nex-ae-api",
        "filter": {
            "scheduler_id": "ae-artifact-retention-scheduler",
            "action": None,
            "worker_status": None,
            "operator_control_execution_state_id": None,
            "operator_control_execution_request_id": None,
        },
        "count": len(items),
        "limit": 20,
        "items": items,
        "guardrails": {
            "read_only": True,
            "ae_owned_persistence": True,
            "ae_owned_worker_result": True,
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
            "ag_direct_process_control_allowed": False,
            "database_url_included": False,
            "raw_execution_payload_included": False,
            "secrets_redacted": True,
        },
        "metadata": {
            "safe_for_ag_projection": True,
            "metadata_only": True,
            "read_model": "ae_op_exec_worker_results",
            "item_count": len(items),
            "newest_observed_at": "2026-09-04T02:05:00Z",
            "private_path": "/data/nex-platform/ae/private",
            "secrets_redacted": True,
        },
    }


def artifact_retention_scheduler_daemon_operator_control_execution_worker_result_detail_payload() -> (
    dict[str, Any]
):
    record = (
        artifact_retention_scheduler_daemon_operator_control_execution_worker_result_record_payload()
    )
    return {
        "operator_control_execution_worker_result_detail_schema_version": (
            "ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_detail.v1"
        ),
        "service_id": "nex-ae-api",
        "operator_control_execution_worker_result_id": (
            record["operator_control_execution_worker_result_id"]
        ),
        "worker_result_record": record,
        "summary": {
            "worker_status": "SUCCEEDED",
            "supervisor_result_count": 2,
            "failed_supervisor_count": 0,
            "metadata_only": True,
        },
        "guardrails": {
            "read_only": True,
            "ae_owned_persistence": True,
            "ae_owned_worker_result": True,
            "database_url_included": False,
            "raw_execution_payload_included": False,
            "secrets_redacted": True,
        },
        "metadata": {
            "safe_for_ag_projection": True,
            "metadata_only": True,
            "read_model": "ae_op_exec_worker_results",
            "private_path": "/data/nex-platform/ae/private",
            "secrets_redacted": True,
        },
    }


def artifact_retention_scheduler_daemon_run_record_payload(
    *,
    daemon_run_record_id: str = "daemon-run-record-0559",
    result_status: str = "SUCCEEDED",
    completed_at: str = "2026-09-01T02:42:00Z",
) -> dict[str, Any]:
    return {
        "daemon_run_record_schema_version": (
            "ae_artifact_retention_scheduler_daemon_run_record.v1"
        ),
        "daemon_run_record_id": daemon_run_record_id,
        "service_id": "nex-ae-api",
        "scheduler_id": "ae-artifact-retention-scheduler",
        "daemon_instance_id": "ae-daemon-instance-0559",
        "daemon_cli_execution_result_id": "daemon-cli-execution-result-0559",
        "daemon_cli_execute_command_id": "daemon-cli-execute-command-0559",
        "daemon_process_lock_id": "daemon-process-lock-0559",
        "started_daemon_run_id": "started-daemon-run-0559",
        "completed_daemon_run_id": "completed-daemon-run-0559",
        "process_id": 5590,
        "host_id": "ae-node-0559",
        "run_status": "SUCCEEDED" if result_status == "SUCCEEDED" else "FAILED",
        "result_status": result_status,
        "stop_reason": (
            "max_cycles_reached" if result_status == "SUCCEEDED" else "cycle_failed"
        ),
        "max_cycles": 2,
        "cycle_count": 2 if result_status == "SUCCEEDED" else 1,
        "worker_requested": True,
        "job_enqueued": result_status == "SUCCEEDED",
        "worker_executed": result_status == "SUCCEEDED",
        "started_at": "2026-09-01T02:40:00Z",
        "completed_at": completed_at,
        "checked_at": "2026-09-01T02:40:00Z",
        "summary": {
            "scheduler_id": "ae-artifact-retention-scheduler",
            "result_status": result_status,
            "stop_reason": (
                "max_cycles_reached"
                if result_status == "SUCCEEDED"
                else "cycle_failed"
            ),
            "max_cycles": 2,
            "cycle_count": 2 if result_status == "SUCCEEDED" else 1,
            "job_enqueued": result_status == "SUCCEEDED",
            "worker_executed": result_status == "SUCCEEDED",
            "run_record_persisted": True,
            "bounded_loop_started": True,
        },
        "metadata": {
            "metadata_only": True,
            "safe_for_ag_projection": True,
            "bounded_loop_started": True,
            "job_enqueued": result_status == "SUCCEEDED",
            "worker_executed": result_status == "SUCCEEDED",
            "run_record_persisted": True,
            "lifecycle_event_persisted": True,
            "database_url_included": False,
            "storage_path_included": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_included": False,
            "raw_daemon_runtime_payload_included": False,
            "physical_delete_automation_enabled": False,
        },
        "execution_result_hash": "a" * 64,
        "created_at": completed_at,
    }


def artifact_retention_scheduler_daemon_lifecycle_event_payload(
    *,
    event_type: str,
    run_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record = run_record or artifact_retention_scheduler_daemon_run_record_payload()
    completed = event_type == "RUN_COMPLETED"
    return {
        "daemon_lifecycle_event_schema_version": (
            "ae_artifact_retention_scheduler_daemon_lifecycle_event.v1"
        ),
        "daemon_lifecycle_event_id": (
            f"{record['daemon_run_record_id']}:{event_type.lower()}"
        ),
        "daemon_run_record_id": record["daemon_run_record_id"],
        "daemon_cli_execution_result_id": record["daemon_cli_execution_result_id"],
        "daemon_run_metadata_id": (
            record["completed_daemon_run_id"]
            if completed
            else record["started_daemon_run_id"]
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": record["scheduler_id"],
        "daemon_instance_id": record["daemon_instance_id"],
        "event_type": event_type,
        "run_status": record["run_status"] if completed else "RUNNING",
        "result_status": record["result_status"] if completed else None,
        "stop_reason": record["stop_reason"] if completed else None,
        "cycle_count": record["cycle_count"] if completed else 0,
        "occurred_at": record["completed_at"] if completed else record["started_at"],
        "process_id": record["process_id"],
        "host_id": record["host_id"],
        "summary": {
            "event_type": event_type,
            "run_status": record["run_status"] if completed else "RUNNING",
            "result_status": record["result_status"] if completed else None,
            "stop_reason": record["stop_reason"] if completed else None,
            "cycle_count": record["cycle_count"] if completed else 0,
            "occurred_at": (
                record["completed_at"] if completed else record["started_at"]
            ),
        },
        "metadata": record["metadata"],
        "created_at": record["completed_at"] if completed else record["started_at"],
    }


def artifact_retention_scheduler_daemon_run_collection_payload() -> dict[str, Any]:
    records = [
        artifact_retention_scheduler_daemon_run_record_payload(),
        artifact_retention_scheduler_daemon_run_record_payload(
            daemon_run_record_id="daemon-run-record-failed-0559",
            result_status="FAILED",
            completed_at="2026-09-01T02:41:00Z",
        ),
    ]
    return {
        "daemon_run_collection_schema_version": (
            "ae_artifact_retention_scheduler_daemon_run_collection.v1"
        ),
        "service_id": "nex-ae-api",
        "filter": {
            "scheduler_id": "ae-artifact-retention-scheduler",
            "result_status": None,
        },
        "count": len(records),
        "limit": 20,
        "items": records,
        "guardrails": {
            "read_only": True,
            "ae_owned_persistence": True,
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
            "process_control_allowed": False,
            "database_url_included": False,
            "storage_path_included": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_included": False,
            "raw_daemon_runtime_payload_included": False,
            "physical_delete_automation_enabled": False,
        },
        "metadata": {
            "safe_for_ag_projection": True,
            "read_model": "ae_artifact_retention_scheduler_daemon_runs",
            "item_count": len(records),
            "limit": 20,
            "has_more": False,
            "newest_completed_at": records[0]["completed_at"],
            "database_url_included": False,
            "storage_path_included": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_included": False,
            "raw_daemon_runtime_payload_included": False,
        },
    }


def artifact_retention_scheduler_daemon_run_detail_payload() -> dict[str, Any]:
    record = artifact_retention_scheduler_daemon_run_record_payload()
    events = [
        artifact_retention_scheduler_daemon_lifecycle_event_payload(
            event_type="RUN_STARTED",
            run_record=record,
        ),
        artifact_retention_scheduler_daemon_lifecycle_event_payload(
            event_type="RUN_COMPLETED",
            run_record=record,
        ),
    ]
    return {
        "daemon_run_detail_schema_version": (
            "ae_artifact_retention_scheduler_daemon_run_detail.v1"
        ),
        "service_id": "nex-ae-api",
        "daemon_run_record_id": record["daemon_run_record_id"],
        "run_record": record,
        "lifecycle_event_count": len(events),
        "lifecycle_events": events,
        "guardrails": {
            "read_only": True,
            "ae_owned_persistence": True,
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
            "process_control_allowed": False,
            "database_url_included": False,
            "storage_path_included": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_included": False,
            "raw_daemon_runtime_payload_included": False,
            "physical_delete_automation_enabled": False,
        },
        "metadata": {
            "safe_for_ag_projection": True,
            "read_model": "ae_artifact_retention_scheduler_daemon_run_detail",
            "daemon_run_record_id": record["daemon_run_record_id"],
            "lifecycle_event_count": len(events),
            "event_types": ["RUN_STARTED", "RUN_COMPLETED"],
            "database_url_included": False,
            "storage_path_included": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_included": False,
            "raw_daemon_runtime_payload_included": False,
        },
    }


def artifact_retention_scheduler_daemon_supervisor_record_payload(
    *,
    record_id: str = "daemon-supervisor-record-0567",
    action: str = "start_daemon",
    result_status: str = "BLOCKED",
    observed_at: str = "2026-09-01T05:56:09Z",
) -> dict[str, Any]:
    runtime_ready = result_status == "READY"
    return {
        "daemon_supervisor_record_schema_version": (
            "ae_artifact_retention_scheduler_daemon_supervisor_record.v1"
        ),
        "daemon_supervisor_record_id": record_id,
        "service_id": "nex-ae-api",
        "scheduler_id": "ae-artifact-retention-scheduler",
        "daemon_supervisor_command_id": f"{record_id}:command",
        "daemon_supervisor_result_id": f"{record_id}:result",
        "action": action,
        "result_status": result_status,
        "decision_reason": (
            "fake_supervisor_dry_run_start_blocked"
            if result_status == "BLOCKED"
            else "fake_supervisor_status_ready"
        ),
        "observed_at": observed_at,
        "checked_at": "2026-09-01T05:56:06Z",
        "runtime_ready": runtime_ready,
        "supervisor_adapter_available": True,
        "supervisor_adapter_invoked": True,
        "adapter_name": "FakeArtifactRetentionSchedulerDaemonSupervisorAdapter",
        "process_started": False,
        "process_stopped": False,
        "message": "fake supervisor dry-run",
        "summary": {
            "scheduler_id": "ae-artifact-retention-scheduler",
            "action": action,
            "result_status": result_status,
            "decision_reason": (
                "fake_supervisor_dry_run_start_blocked"
                if result_status == "BLOCKED"
                else "fake_supervisor_status_ready"
            ),
            "runtime_ready": runtime_ready,
            "supervisor_adapter_available": True,
            "supervisor_adapter_invoked": True,
            "process_started": False,
            "process_stopped": False,
            "database_url": "SHOULD_NOT_LEAK",
        },
        "metadata": {
            "metadata_only": True,
            "safe_for_ag_projection": True,
            "supervisor_result_persisted": True,
            "supervisor_event_persisted": True,
            "ag_direct_process_control_allowed": False,
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
            "database_url_included": False,
            "storage_path_included": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_included": False,
            "raw_daemon_runtime_payload_included": False,
            "physical_delete_automation_enabled": False,
            "private_path": "/data/nex-platform/private",
        },
        "supervisor_command": {"private": "drop", "database_url": "SHOULD_NOT_LEAK"},
        "supervisor_result": {"private": "drop", "database_url": "SHOULD_NOT_LEAK"},
        "supervisor_result_hash": "f" * 64,
        "created_at": observed_at,
    }


def artifact_retention_scheduler_daemon_supervisor_event_payload(
    *,
    record: dict[str, Any] | None = None,
    event_type: str = "SUPERVISOR_RESULT_RECORDED",
) -> dict[str, Any]:
    supervisor_record = (
        record or artifact_retention_scheduler_daemon_supervisor_record_payload()
    )
    return {
        "daemon_supervisor_event_schema_version": (
            "ae_artifact_retention_scheduler_daemon_supervisor_event.v1"
        ),
        "daemon_supervisor_event_id": (
            f"{supervisor_record['daemon_supervisor_record_id']}:"
            f"{event_type.lower()}"
        ),
        "daemon_supervisor_record_id": (
            supervisor_record["daemon_supervisor_record_id"]
        ),
        "daemon_supervisor_command_id": (
            supervisor_record["daemon_supervisor_command_id"]
        ),
        "daemon_supervisor_result_id": (
            supervisor_record["daemon_supervisor_result_id"]
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": supervisor_record["scheduler_id"],
        "action": supervisor_record["action"],
        "result_status": supervisor_record["result_status"],
        "decision_reason": supervisor_record["decision_reason"],
        "event_type": event_type,
        "occurred_at": supervisor_record["observed_at"],
        "summary": {
            "event_type": event_type,
            "scheduler_id": supervisor_record["scheduler_id"],
            "action": supervisor_record["action"],
            "result_status": supervisor_record["result_status"],
            "decision_reason": supervisor_record["decision_reason"],
            "occurred_at": supervisor_record["observed_at"],
            "database_url": "SHOULD_NOT_LEAK",
        },
        "metadata": supervisor_record["metadata"],
        "created_at": supervisor_record["observed_at"],
    }


def artifact_retention_scheduler_daemon_supervisor_collection_payload() -> (
    dict[str, Any]
):
    records = [
        artifact_retention_scheduler_daemon_supervisor_record_payload(),
        artifact_retention_scheduler_daemon_supervisor_record_payload(
            record_id="daemon-supervisor-record-ready-0567",
            action="status_probe",
            result_status="READY",
            observed_at="2026-09-01T05:56:11Z",
        ),
    ]
    return {
        "daemon_supervisor_collection_schema_version": (
            "ae_artifact_retention_scheduler_daemon_supervisor_collection.v1"
        ),
        "service_id": "nex-ae-api",
        "filter": {
            "scheduler_id": "ae-artifact-retention-scheduler",
            "action": None,
            "result_status": None,
        },
        "count": len(records),
        "limit": 20,
        "items": records,
        "guardrails": {
            "read_only": True,
            "ae_owned_persistence": True,
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
            "process_control_allowed": False,
            "database_url_included": False,
            "storage_path_included": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_included": False,
            "raw_daemon_runtime_payload_included": False,
            "physical_delete_automation_enabled": False,
        },
        "metadata": {
            "safe_for_ag_projection": True,
            "read_model": (
                "ae_artifact_retention_scheduler_daemon_supervisor_results"
            ),
            "item_count": len(records),
            "limit": 20,
            "has_more": False,
            "newest_observed_at": records[1]["observed_at"],
            "database_url_included": False,
            "storage_path_included": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_included": False,
            "raw_daemon_runtime_payload_included": False,
        },
    }


def artifact_retention_scheduler_daemon_supervisor_detail_payload() -> dict[str, Any]:
    record = artifact_retention_scheduler_daemon_supervisor_record_payload()
    events = [
        artifact_retention_scheduler_daemon_supervisor_event_payload(
            record=record,
            event_type="SUPERVISOR_COMMAND_ACCEPTED",
        ),
        artifact_retention_scheduler_daemon_supervisor_event_payload(
            record=record,
            event_type="SUPERVISOR_RESULT_RECORDED",
        ),
    ]
    return {
        "daemon_supervisor_detail_schema_version": (
            "ae_artifact_retention_scheduler_daemon_supervisor_detail.v1"
        ),
        "service_id": "nex-ae-api",
        "daemon_supervisor_record_id": record["daemon_supervisor_record_id"],
        "supervisor_record": record,
        "supervisor_event_count": len(events),
        "supervisor_events": events,
        "guardrails": {
            "read_only": True,
            "ae_owned_persistence": True,
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
            "process_control_allowed": False,
            "database_url_included": False,
            "storage_path_included": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_included": False,
            "raw_daemon_runtime_payload_included": False,
            "physical_delete_automation_enabled": False,
        },
        "metadata": {
            "safe_for_ag_projection": True,
            "read_model": (
                "ae_artifact_retention_scheduler_daemon_supervisor_detail"
            ),
            "daemon_supervisor_record_id": record["daemon_supervisor_record_id"],
            "supervisor_event_count": len(events),
            "event_types": [
                "SUPERVISOR_COMMAND_ACCEPTED",
                "SUPERVISOR_RESULT_RECORDED",
            ],
            "database_url_included": False,
            "storage_path_included": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_included": False,
            "raw_daemon_runtime_payload_included": False,
        },
    }


def artifact_retention_scheduler_daemon_supervised_process_record_payload(
    *,
    record_id: str = "daemon-supervised-process-record-0576",
    action: str = "start_daemon",
    process_status: str = "RUNNING",
    observed_at: str = "2026-09-02T01:12:03Z",
) -> dict[str, Any]:
    return {
        "daemon_supervised_process_record_schema_version": (
            "ae_artifact_retention_scheduler_daemon_supervised_process_record.v1"
        ),
        "daemon_supervised_process_record_id": record_id,
        "service_id": "nex-ae-api",
        "scheduler_id": "ae-artifact-retention-scheduler",
        "daemon_supervisor_command_id": f"{record_id}:command",
        "daemon_supervised_process_id": f"{record_id}:process",
        "action": action,
        "process_status": process_status,
        "process_mode": "subprocess_adapter",
        "process_id": 5741,
        "host_id": "ae-worker-01",
        "observed_at": observed_at,
        "started_at": "2026-09-02T01:11:58Z",
        "completed_at": None if process_status == "RUNNING" else observed_at,
        "exit_code": 0 if process_status == "STOPPED" else None,
        "termination_signal": None,
        "process_running": process_status == "RUNNING",
        "process_started_observed": process_status in {"RUNNING", "STOPPED"},
        "process_stopped_observed": process_status == "STOPPED",
        "subprocess_adapter_required": True,
        "message": "scheduler daemon process observed",
        "summary": {
            "scheduler_id": "ae-artifact-retention-scheduler",
            "action": action,
            "process_status": process_status,
            "process_mode": "subprocess_adapter",
            "process_running": process_status == "RUNNING",
            "process_started_observed": process_status in {"RUNNING", "STOPPED"},
            "process_stopped_observed": process_status == "STOPPED",
            "subprocess_adapter_required": True,
            "observed_at": observed_at,
            "database_url": "SHOULD_NOT_LEAK",
        },
        "metadata": {
            "metadata_only": True,
            "safe_for_ag_projection": True,
            "supervised_process_record_persisted": True,
            "supervised_process_event_persisted": True,
            "process_control_allowed": False,
            "ag_direct_process_control_allowed": False,
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
            "database_url_included": False,
            "storage_path_included": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_included": False,
            "raw_daemon_runtime_payload_included": False,
            "physical_delete_automation_enabled": False,
            "process_started": process_status in {"RUNNING", "STOPPED"},
            "process_stopped": process_status == "STOPPED",
            "private_path": "/data/nex-platform/private",
        },
        "supervised_process_snapshot": {
            "private": "drop",
            "database_url": "SHOULD_NOT_LEAK",
        },
        "supervised_process_snapshot_hash": "9" * 64,
        "created_at": observed_at,
    }


def artifact_retention_scheduler_daemon_supervised_process_event_payload(
    *,
    record: dict[str, Any] | None = None,
    event_type: str = "PROCESS_SNAPSHOT_RECORDED",
) -> dict[str, Any]:
    process_record = (
        record
        or artifact_retention_scheduler_daemon_supervised_process_record_payload()
    )
    return {
        "daemon_supervised_process_event_schema_version": (
            "ae_artifact_retention_scheduler_daemon_supervised_process_event.v1"
        ),
        "daemon_supervised_process_event_id": (
            f"{process_record['daemon_supervised_process_record_id']}:"
            f"{event_type.lower()}"
        ),
        "daemon_supervised_process_record_id": (
            process_record["daemon_supervised_process_record_id"]
        ),
        "daemon_supervised_process_id": (
            process_record["daemon_supervised_process_id"]
        ),
        "daemon_supervisor_command_id": (
            process_record["daemon_supervisor_command_id"]
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": process_record["scheduler_id"],
        "action": process_record["action"],
        "process_status": process_record["process_status"],
        "event_type": event_type,
        "occurred_at": process_record["observed_at"],
        "summary": {
            "event_type": event_type,
            "scheduler_id": process_record["scheduler_id"],
            "action": process_record["action"],
            "process_status": process_record["process_status"],
            "occurred_at": process_record["observed_at"],
            "database_url": "SHOULD_NOT_LEAK",
        },
        "metadata": process_record["metadata"],
        "created_at": process_record["observed_at"],
    }


def artifact_retention_scheduler_daemon_supervised_process_collection_payload() -> (
    dict[str, Any]
):
    records = [
        artifact_retention_scheduler_daemon_supervised_process_record_payload(),
        artifact_retention_scheduler_daemon_supervised_process_record_payload(
            record_id="daemon-supervised-process-record-stale-0576",
            action="status_probe",
            process_status="STALE",
            observed_at="2026-09-02T01:12:09Z",
        ),
    ]
    return {
        "daemon_supervised_process_collection_schema_version": (
            "ae_artifact_retention_scheduler_daemon_process_snapshot_collection.v1"
        ),
        "service_id": "nex-ae-api",
        "filter": {
            "scheduler_id": "ae-artifact-retention-scheduler",
            "action": None,
            "process_status": None,
        },
        "count": len(records),
        "limit": 20,
        "items": records,
        "guardrails": {
            "read_only": True,
            "ae_owned_persistence": True,
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
            "process_control_allowed": False,
            "database_url_included": False,
            "storage_path_included": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_included": False,
            "raw_daemon_runtime_payload_included": False,
            "physical_delete_automation_enabled": False,
        },
        "metadata": {
            "safe_for_ag_projection": True,
            "read_model": (
                "ae_artifact_retention_scheduler_daemon_process_snapshots"
            ),
            "item_count": len(records),
            "limit": 20,
            "has_more": False,
            "newest_observed_at": records[1]["observed_at"],
            "database_url_included": False,
            "storage_path_included": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_included": False,
            "raw_daemon_runtime_payload_included": False,
        },
    }


def artifact_retention_scheduler_daemon_supervised_process_detail_payload() -> (
    dict[str, Any]
):
    record = artifact_retention_scheduler_daemon_supervised_process_record_payload()
    events = [
        artifact_retention_scheduler_daemon_supervised_process_event_payload(
            record=record,
            event_type="PROCESS_START_OBSERVED",
        ),
        artifact_retention_scheduler_daemon_supervised_process_event_payload(
            record=record,
            event_type="PROCESS_SNAPSHOT_RECORDED",
        ),
    ]
    return {
        "daemon_supervised_process_detail_schema_version": (
            "ae_artifact_retention_scheduler_daemon_process_snapshot_detail.v1"
        ),
        "service_id": "nex-ae-api",
        "daemon_supervised_process_record_id": (
            record["daemon_supervised_process_record_id"]
        ),
        "supervised_process_record": record,
        "supervised_process_event_count": len(events),
        "supervised_process_events": events,
        "guardrails": {
            "read_only": True,
            "ae_owned_persistence": True,
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
            "process_control_allowed": False,
            "database_url_included": False,
            "storage_path_included": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_included": False,
            "raw_daemon_runtime_payload_included": False,
            "physical_delete_automation_enabled": False,
        },
        "metadata": {
            "safe_for_ag_projection": True,
            "read_model": (
                "ae_artifact_retention_scheduler_daemon_process_detail"
            ),
            "daemon_supervised_process_record_id": (
                record["daemon_supervised_process_record_id"]
            ),
            "supervised_process_event_count": len(events),
            "event_types": [
                "PROCESS_START_OBSERVED",
                "PROCESS_SNAPSHOT_RECORDED",
            ],
            "database_url_included": False,
            "storage_path_included": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_included": False,
            "raw_daemon_runtime_payload_included": False,
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
        artifact_retention_scheduler_daemon_runtime=(
            artifact_retention_scheduler_daemon_runtime_payload()
        ),
        artifact_retention_scheduler_daemon_run_collections={
            artifact_operations._artifact_retention_scheduler_daemon_run_cache_key(
                scheduler_id="ae-artifact-retention-scheduler",
                result_status=None,
                limit=20,
            ): artifact_retention_scheduler_daemon_run_collection_payload(),
            artifact_operations._artifact_retention_scheduler_daemon_run_cache_key(
                scheduler_id="ae-artifact-retention-scheduler",
                result_status="SUCCEEDED",
                limit=1,
            ): {
                **artifact_retention_scheduler_daemon_run_collection_payload(),
                "filter": {
                    "scheduler_id": "ae-artifact-retention-scheduler",
                    "result_status": "SUCCEEDED",
                },
                "count": 1,
                "limit": 1,
                "items": [
                    artifact_retention_scheduler_daemon_run_record_payload()
                ],
            },
        },
        artifact_retention_scheduler_daemon_run_details={
            "daemon-run-record-0559": (
                artifact_retention_scheduler_daemon_run_detail_payload()
            ),
        },
        artifact_retention_scheduler_daemon_supervisor_collections={
            artifact_operations._artifact_retention_scheduler_daemon_supervisor_cache_key(
                scheduler_id="ae-artifact-retention-scheduler",
                action=None,
                result_status=None,
                limit=20,
            ): artifact_retention_scheduler_daemon_supervisor_collection_payload(),
            artifact_operations._artifact_retention_scheduler_daemon_supervisor_cache_key(
                scheduler_id="ae-artifact-retention-scheduler",
                action="start_daemon",
                result_status="BLOCKED",
                limit=1,
            ): {
                **artifact_retention_scheduler_daemon_supervisor_collection_payload(),
                "filter": {
                    "scheduler_id": "ae-artifact-retention-scheduler",
                    "action": "start_daemon",
                    "result_status": "BLOCKED",
                },
                "count": 1,
                "limit": 1,
                "items": [
                    artifact_retention_scheduler_daemon_supervisor_record_payload()
                ],
            },
        },
        artifact_retention_scheduler_daemon_supervisor_details={
            "daemon-supervisor-record-0567": (
                artifact_retention_scheduler_daemon_supervisor_detail_payload()
            ),
        },
        artifact_retention_scheduler_daemon_process_snapshot_collections={
            artifact_operations._artifact_retention_scheduler_daemon_process_snapshot_cache_key(
                scheduler_id="ae-artifact-retention-scheduler",
                action=None,
                process_status=None,
                limit=20,
            ): artifact_retention_scheduler_daemon_supervised_process_collection_payload(),
            artifact_operations._artifact_retention_scheduler_daemon_process_snapshot_cache_key(
                scheduler_id="ae-artifact-retention-scheduler",
                action="start_daemon",
                process_status="RUNNING",
                limit=1,
            ): {
                **artifact_retention_scheduler_daemon_supervised_process_collection_payload(),
                "filter": {
                    "scheduler_id": "ae-artifact-retention-scheduler",
                    "action": "start_daemon",
                    "process_status": "RUNNING",
                },
                "count": 1,
                "limit": 1,
                "items": [
                    artifact_retention_scheduler_daemon_supervised_process_record_payload()
                ],
            },
        },
        artifact_retention_scheduler_daemon_process_snapshot_details={
            "daemon-supervised-process-record-0576": (
                artifact_retention_scheduler_daemon_supervised_process_detail_payload()
            ),
        },
        artifact_retention_scheduler_daemon_operator_control_execution_collections={
            artifact_operations._artifact_retention_scheduler_daemon_operator_control_execution_cache_key(
                scheduler_id="ae-artifact-retention-scheduler",
                action=None,
                execution_status=None,
                idempotency_status=None,
                limit=20,
            ): artifact_retention_scheduler_daemon_operator_control_execution_collection_payload(),
            artifact_operations._artifact_retention_scheduler_daemon_operator_control_execution_cache_key(
                scheduler_id="ae-artifact-retention-scheduler",
                action="restart_daemon",
                execution_status="FAILED",
                idempotency_status="CONFLICT",
                limit=1,
            ): {
                **artifact_retention_scheduler_daemon_operator_control_execution_collection_payload(),
                "filter": {
                    "scheduler_id": "ae-artifact-retention-scheduler",
                    "action": "restart_daemon",
                    "execution_status": "FAILED",
                    "idempotency_status": "CONFLICT",
                },
                "count": 1,
                "limit": 1,
                "items": [
                    artifact_retention_scheduler_daemon_operator_control_execution_state_payload(
                        state_id="operator-control-execution-state-conflict-0597",
                        execution_status="FAILED",
                        idempotency_status="CONFLICT",
                        observed_at="2026-09-04T02:05:00Z",
                    )
                ],
            },
        },
        artifact_retention_scheduler_daemon_operator_control_execution_details={
            "operator-control-execution-state-0597": (
                artifact_retention_scheduler_daemon_operator_control_execution_detail_payload()
            ),
        },
        artifact_retention_scheduler_daemon_operator_control_execution_worker_results={
            artifact_operations._artifact_retention_scheduler_daemon_operator_control_execution_worker_cache_key(
                operator_control_execution_state_id=(
                    "operator-control-execution-state-0597"
                ),
                checked_at=None,
                worker_observed_at=None,
            ): (
                artifact_retention_scheduler_daemon_operator_control_execution_worker_result_payload()
            ),
        },
        artifact_retention_scheduler_daemon_operator_control_execution_worker_result_collections={
            artifact_operations._artifact_retention_scheduler_daemon_operator_control_execution_worker_result_cache_key(
                scheduler_id="ae-artifact-retention-scheduler",
                action=None,
                worker_status=None,
                operator_control_execution_state_id=None,
                operator_control_execution_request_id=None,
                limit=20,
            ): (
                artifact_retention_scheduler_daemon_operator_control_execution_worker_result_collection_payload()
            ),
            artifact_operations._artifact_retention_scheduler_daemon_operator_control_execution_worker_result_cache_key(
                scheduler_id="ae-artifact-retention-scheduler",
                action="restart_daemon",
                worker_status="FAILED",
                operator_control_execution_state_id=(
                    "operator-control-execution-state-0597"
                ),
                operator_control_execution_request_id=(
                    "operator-control-execution-state-0597:execution-request"
                ),
                limit=1,
            ): {
                **artifact_retention_scheduler_daemon_operator_control_execution_worker_result_collection_payload(),
                "filter": {
                    "scheduler_id": "ae-artifact-retention-scheduler",
                    "action": "restart_daemon",
                    "worker_status": "FAILED",
                    "operator_control_execution_state_id": (
                        "operator-control-execution-state-0597"
                    ),
                    "operator_control_execution_request_id": (
                        "operator-control-execution-state-0597:execution-request"
                    ),
                },
                "count": 1,
                "limit": 1,
                "items": [
                    artifact_retention_scheduler_daemon_operator_control_execution_worker_result_record_payload(
                        worker_status="FAILED",
                        observed_at="2026-09-04T02:05:00Z",
                    )
                ],
            },
        },
        artifact_retention_scheduler_daemon_operator_control_execution_worker_result_details={
            "operator-control-execution-worker-result-0607": (
                artifact_retention_scheduler_daemon_operator_control_execution_worker_result_detail_payload()
            ),
        },
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
            "start_stop_guardrail_evaluated": False,
            "lease_acquired_before_tick": True,
            "lease_released": True,
            "job_enqueued": True,
            "worker_executed": True,
            "runtime_state_mutated": False,
            "stop_signal_sent": False,
            "scheduler_daemon_started": False,
            "continuous_loop_started": False,
            "physical_delete_automation_enabled": False,
        },
    }

    projection = build_artifact_operation_retention_daemon_projection(
        daemon_config=artifact_retention_scheduler_daemon_config_payload(),
        daemon_runtime=artifact_retention_scheduler_daemon_runtime_payload(),
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
    assert projection["daemon_runtime"]["runtime_projection_schema_version"] == (
        artifact_operations.AG_ARTIFACT_OPERATION_RETENTION_DAEMON_RUNTIME_PROJECTION_SCHEMA_VERSION
    )
    assert projection["daemon_runtime"]["heartbeat_store"]["available"] is True
    assert projection["daemon_runtime"]["heartbeat"]["status"] == "BUSY"
    assert projection["daemon_runtime"]["heartbeat"]["active_job_id"] == (
        "daemon-loop-plan-0538"
    )
    assert projection["daemon_runtime"]["heartbeat"]["metadata"]["phase"] == (
        "tick_once_running"
    )
    assert projection["lifecycle_projection"]["lifecycle_projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_RETENTION_DAEMON_LIFECYCLE_PROJECTION_SCHEMA_VERSION
    )
    assert projection["lifecycle_projection"]["lifecycle"]["status"] == "RUNNING"
    assert projection["lifecycle_projection"]["lifecycle"]["source"] == "heartbeat"
    assert projection["lifecycle_projection"]["lifecycle"]["heartbeat_status"] == (
        "BUSY"
    )
    assert projection["lifecycle_projection"]["attention"]["attention_status"] == (
        "READY"
    )
    assert projection["lifecycle_projection"]["guardrails"][
        "ag_direct_database_write_allowed"
    ] is False
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
            "start_stop_guardrail_evaluated": False,
            "lease_acquired_before_tick": True,
            "lease_released": True,
            "job_enqueued": True,
            "worker_executed": True,
            "runtime_state_mutated": False,
            "stop_signal_sent": False,
            "scheduler_daemon_started": False,
            "continuous_loop_started": False,
            "physical_delete_automation_enabled": False,
        },
    }
    assert projection["dispatch_response"]["start_stop_guardrail"] == {}
    assert projection["issue_candidates"] == []
    assert projection["summary"] == summarize_artifact_retention_daemon_operations(
        daemon_config=projection["daemon_config"],
        daemon_runtime=projection["daemon_runtime"],
        dispatch_response=projection["dispatch_response"],
    )
    assert projection["summary"]["manual_tick_once_available"] is True
    assert projection["summary"]["start_daemon_available"] is False
    assert projection["summary"]["last_dispatch_job_enqueued"] is True
    assert projection["summary"]["runtime_observation_available"] is True
    assert projection["summary"]["runtime_heartbeat_store_available"] is True
    assert projection["summary"]["runtime_heartbeat_observed"] is True
    assert projection["summary"]["runtime_heartbeat_status"] == "BUSY"
    assert projection["summary"]["runtime_heartbeat_worker_id"] == (
        "ae-retention-daemon-runtime-0538"
    )
    assert projection["summary"]["runtime_heartbeat_active_job_id"] == (
        "daemon-loop-plan-0538"
    )
    assert projection["summary"]["runtime_heartbeat_last_seen_at"] == (
        "2026-09-01T02:40:00Z"
    )
    assert projection["summary"]["lifecycle_status"] == "RUNNING"
    assert projection["summary"]["lifecycle_reason"] == "heartbeat_busy"
    assert projection["summary"]["lifecycle_source"] == "heartbeat"
    assert projection["summary"]["lifecycle_attention_status"] == "READY"
    assert projection["summary"]["lifecycle_operator_attention_required"] is False
    assert projection["summary"]["retry_allowed"] is False
    assert projection["summary"]["runtime_issue_candidate_count"] == 0
    assert projection["summary"]["attention_status"] == "DISPATCH_ATTENTION"
    assert projection["summary"]["attention_level"] == "INFO"
    assert projection["summary"]["attention_reason_codes"] == [
        "last_dispatch_observed",
        "last_dispatch_dispatched",
        "start_daemon_disabled_by_policy",
        "continuous_loop_disabled_by_policy",
    ]
    assert projection["attention"] == {
        "attention_schema_version": (
            AG_ARTIFACT_OPERATION_RETENTION_DAEMON_ATTENTION_SCHEMA_VERSION
        ),
        "attention_status": "DISPATCH_ATTENTION",
        "attention_level": "INFO",
        "reason_codes": [
            "last_dispatch_observed",
            "last_dispatch_dispatched",
            "start_daemon_disabled_by_policy",
            "continuous_loop_disabled_by_policy",
        ],
        "operator_actions": ["review_last_daemon_dispatch"],
        "operator_attention_required": True,
        "manual_tick_once_safe": True,
        "start_daemon_blocked_by_policy": True,
        "continuous_loop_blocked_by_policy": True,
        "batch_window_enforced": True,
        "metadata_only": True,
    }
    assert projection["source_status"]["daemon_config_loaded"] is True
    assert projection["source_status"]["daemon_runtime_loaded"] is True
    assert projection["source_status"]["dispatch_response_loaded"] is True
    assert projection["operator_guidance"]["ae_daemon_runtime_route"] == (
        "/api/v1/artifact-retention/scheduler-daemon-runtime"
    )
    assert projection["operator_guidance"]["ae_daemon_lifecycle_projection"] == (
        "metadata_only"
    )
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
        daemon_runtime={
            "runtime_observation_schema_version": "runtime.v1",
            "service_id": "nex-ae-api",
            "scheduler_id": "ae-artifact-retention-scheduler",
            "checked_at": "2026-09-01T02:41:00Z",
            "worker_type": "ae.artifact_retention.scheduler_daemon",
            "heartbeat_store": "bad",
            "heartbeat": "bad",
            "heartbeat_count": "bad",
            "guardrails": "bad",
            "metadata": "bad",
        },
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
    assert projection["daemon_runtime"]["heartbeat_store"] == {}
    assert projection["daemon_runtime"]["heartbeat"] == {}
    assert projection["daemon_runtime"]["heartbeat_count"] == 0
    assert projection["daemon_runtime"]["runtime_state"] == {}
    assert projection["daemon_runtime"]["bounded_loop_result"] == {}
    assert projection["daemon_runtime"]["shutdown_transition"] == {}
    assert projection["daemon_runtime"]["retry_circuit_guard"] == {}
    assert projection["daemon_runtime"]["guardrails"] == {}
    assert projection["daemon_runtime"]["metadata"] == {}
    assert projection["lifecycle_projection"]["lifecycle"]["status"] == "UNKNOWN"
    assert projection["lifecycle_projection"]["attention"]["attention_status"] == (
        "OBSERVATION_GAP"
    )
    assert projection["dispatch_response"]["control_plan"]["action"] is None
    assert projection["dispatch_response"]["control_plan"]["requested_by"] == {}
    assert projection["dispatch_response"]["control_plan"]["execution_plan"] == {}
    assert projection["dispatch_response"]["tick_once_result"] == {}
    assert projection["dispatch_response"]["start_stop_guardrail"]["action"] == (
        "start_daemon"
    )
    assert projection["dispatch_response"]["start_stop_guardrail"][
        "guardrail_status"
    ] == "BLOCKED"
    assert projection["dispatch_response"]["start_stop_guardrail"][
        "guardrail_reason"
    ] == "daemon_disabled_by_policy"
    assert projection["dispatch_response"]["start_stop_guardrail"][
        "action_allowed"
    ] is False
    assert projection["dispatch_response"]["start_stop_guardrail"]["execution_plan"][
        "starts_daemon"
    ] is False
    assert projection["dispatch_response"]["start_stop_guardrail"]["guardrails"][
        "future_supervisor_required_before_start"
    ] is True
    assert projection["dispatch_response"]["start_stop_guardrail"]["metadata"][
        "stop_signal_sent"
    ] is False
    assert projection["issue_candidates"] == []
    assert projection["summary"]["manual_tick_once_decision_status"] == "BLOCKED"
    assert projection["summary"]["manual_tick_once_available"] is False
    assert projection["summary"]["attention_status"] == "DISPATCH_ATTENTION"
    assert projection["summary"]["operator_attention_required"] is True
    assert projection["source_status"]["daemon_config_loaded"] is False
    assert projection["source_status"]["daemon_runtime_loaded"] is False
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
        artifact_operations._project_retention_scheduler_daemon_runtime_observation([])
        == {}
    )
    assert (
        artifact_operations._project_retention_scheduler_daemon_heartbeat_store([])
        == {}
    )
    assert artifact_operations._project_retention_scheduler_daemon_heartbeat([]) == {}
    assert (
        artifact_operations._project_retention_scheduler_daemon_heartbeat_metadata([])
        == {}
    )
    assert (
        artifact_operations._project_retention_scheduler_daemon_runtime_guardrails([])
        == {}
    )
    assert (
        artifact_operations._project_retention_scheduler_daemon_runtime_metadata([])
        == {}
    )
    assert (
        artifact_operations._project_retention_scheduler_daemon_runtime_state([])
        == {}
    )
    assert (
        artifact_operations._project_retention_scheduler_daemon_bounded_loop_result([])
        == {}
    )
    assert (
        artifact_operations._project_retention_scheduler_daemon_shutdown_transition([])
        == {}
    )
    assert (
        artifact_operations._project_retention_scheduler_daemon_retry_circuit_guard([])
        == {}
    )
    assert (
        artifact_operations._project_retention_scheduler_daemon_lifecycle_guardrails([])
        == {}
    )
    assert (
        artifact_operations._project_retention_scheduler_daemon_lifecycle_metadata([])
        == {}
    )
    assert (
        artifact_operations.build_artifact_retention_daemon_runtime_issue_candidates(
            daemon_runtime=None
        )
        == []
    )
    assert artifact_operations._retention_daemon_runtime_issue_signals({}) == []
    assert artifact_operations._normalized_daemon_heartbeat_status("BROKEN") is None
    assert (
        artifact_operations._project_retention_scheduler_daemon_dispatch_response([])
        == {}
    )
    assert artifact_operations._project_retention_scheduler_daemon_control_plan([]) == {}
    assert artifact_operations._project_retention_scheduler_start_stop_guardrail([]) == {}
    assert artifact_operations._project_retention_scheduler_tick_once_summary([]) == {}


def test_artifact_retention_daemon_lifecycle_projection_reads_runtime_contracts() -> (
    None
):
    runtime_state = artifact_retention_scheduler_daemon_runtime_state_payload(
        lifecycle_status="ERROR",
        lifecycle_reason="cycle_failed",
        last_cycle_status="FAILED",
        consecutive_failure_count=3,
    )
    bounded_loop_result = artifact_retention_scheduler_daemon_bounded_loop_result_payload(
        result_status="FAILED",
        stop_reason="cycle_failed",
        final_state=runtime_state,
    )
    shutdown_transition = {
        "daemon_shutdown_transition_schema_version": (
            "ae_artifact_retention_scheduler_daemon_shutdown_transition.v1"
        ),
        "daemon_shutdown_transition_id": "ae-daemon-shutdown-0548",
        "service_id": "nex-ae-api",
        "scheduler_id": "ae-artifact-retention-scheduler",
        "daemon_instance_id": "ae-retention-daemon-runtime-0548",
        "requested_at": "2026-09-01T02:42:00Z",
        "decision_status": "READY",
        "decision_reason": "stop_requested",
        "previous_state": runtime_state,
        "next_state": artifact_retention_scheduler_daemon_runtime_state_payload(
            lifecycle_status="STOPPING",
            lifecycle_reason="stop_requested",
            stop_requested=True,
            shutdown_requested_at="2026-09-01T02:42:00Z",
            last_cycle_status="FAILED",
            consecutive_failure_count=3,
        ),
        "execution_plan": {
            "requires_runtime_state": True,
            "sends_stop_signal": True,
            "runs_tick_once": False,
            "dispatches_job_queue": False,
            "bounded_loop_should_stop_before_next_cycle": True,
            "writes_history": False,
            "physical_delete_enabled": False,
        },
        "guardrails": {
            "metadata_only": True,
            "runtime_state_mutated": False,
            "database_write_performed": False,
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
        },
        "metadata": {
            "metadata_only": True,
            "safe_for_ag_projection": True,
            "shutdown_requested": True,
            "runtime_state_mutated": False,
            "database_write_performed": False,
        },
    }
    retry_circuit_guard = {
        "daemon_retry_circuit_guard_schema_version": (
            "ae_artifact_retention_scheduler_daemon_retry_circuit_guard.v1"
        ),
        "daemon_retry_circuit_guard_id": "ae-daemon-retry-0548",
        "service_id": "nex-ae-api",
        "scheduler_id": "ae-artifact-retention-scheduler",
        "daemon_instance_id": "ae-retention-daemon-runtime-0548",
        "requested_at": "2026-09-01T02:43:00Z",
        "decision_status": "CIRCUIT_OPEN",
        "decision_reason": "max_consecutive_failures_reached",
        "retry_allowed": False,
        "next_retry_at": None,
        "failure_threshold": 3,
        "backoff_seconds": 120,
        "execution_plan": {
            "requires_runtime_state": True,
            "retry_allowed": False,
            "runs_tick_once": False,
            "dispatches_job_queue": False,
            "writes_history": False,
            "physical_delete_enabled": False,
        },
        "guardrails": {
            "metadata_only": True,
            "retry_decision_only": True,
            "runtime_state_mutated": False,
            "database_write_performed": False,
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
        },
        "metadata": {
            "metadata_only": True,
            "safe_for_ag_projection": True,
            "circuit_open": True,
            "runtime_state_mutated": False,
            "database_write_performed": False,
        },
    }
    runtime = artifact_retention_scheduler_daemon_runtime_payload(
        status="ERROR",
        active_job_id="daemon-loop-error",
        runtime_state=runtime_state,
        bounded_loop_result=bounded_loop_result,
        shutdown_transition=shutdown_transition,
        retry_circuit_guard=retry_circuit_guard,
    )

    projection = build_artifact_retention_daemon_lifecycle_projection(
        daemon_config=artifact_retention_scheduler_daemon_config_payload(),
        daemon_runtime=runtime,
        dispatch_response=artifact_retention_scheduler_daemon_dispatch_payload(
            action="stop_daemon",
            dispatch_status="BLOCKED",
        ),
    )
    summary = summarize_artifact_retention_daemon_lifecycle_projection(
        daemon_config=artifact_retention_scheduler_daemon_config_payload(),
        daemon_runtime=runtime,
    )
    parent_projection = build_artifact_operation_retention_daemon_projection(
        daemon_config=artifact_retention_scheduler_daemon_config_payload(),
        daemon_runtime=runtime,
    )

    assert projection["lifecycle_projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_RETENTION_DAEMON_LIFECYCLE_PROJECTION_SCHEMA_VERSION
    )
    assert projection["lifecycle"]["status"] == "ERROR"
    assert projection["lifecycle"]["reason"] == "cycle_failed"
    assert projection["lifecycle"]["source"] == "runtime_state"
    assert projection["lifecycle"]["last_cycle_status"] == "FAILED"
    assert projection["lifecycle"]["consecutive_failure_count"] == 3
    assert projection["bounded_loop"]["result_status"] == "FAILED"
    assert projection["bounded_loop"]["stop_reason"] == "cycle_failed"
    assert projection["shutdown_transition"]["decision_status"] == "READY"
    assert projection["retry_circuit_guard"]["decision_status"] == "CIRCUIT_OPEN"
    assert projection["retry_circuit_guard"]["retry_allowed"] is False
    assert projection["last_control_action"] == "stop_daemon"
    assert projection["attention"] == {
        "attention_status": "ACTION_REQUIRED",
        "attention_level": "ERROR",
        "reason_code": "max_consecutive_failures_reached",
        "operator_action": "review_ae_scheduler_daemon_failure",
        "operator_attention_required": True,
        "metadata_only": True,
    }
    assert projection["operator_guidance"]["ag_direct_daemon_process_control_allowed"] is False
    assert summary["lifecycle_status"] == "ERROR"
    assert summary["retry_circuit_status"] == "CIRCUIT_OPEN"
    assert summary["operator_attention_required"] is True
    assert parent_projection["summary"]["lifecycle_status"] == "ERROR"
    assert parent_projection["summary"]["retry_circuit_status"] == "CIRCUIT_OPEN"
    assert parent_projection["summary"]["lifecycle_operator_attention_required"] is True
    assert "database_url" not in str(projection)
    assert "nuri1004" not in str(parent_projection)


def test_artifact_retention_daemon_lifecycle_projection_status_matrix() -> None:
    config = artifact_retention_scheduler_daemon_config_payload()
    stopping_state = artifact_retention_scheduler_daemon_runtime_state_payload(
        lifecycle_status="STOPPING",
        lifecycle_reason="stop_requested",
        stop_requested=True,
        shutdown_requested_at="2026-09-01T02:42:00Z",
        last_cycle_status=None,
    )
    backoff_runtime = artifact_retention_scheduler_daemon_runtime_payload(
        status="BUSY",
        runtime_state=artifact_retention_scheduler_daemon_runtime_state_payload(
            lifecycle_status="RUNNING",
            lifecycle_reason="cycle_failed",
            last_cycle_status="FAILED",
            consecutive_failure_count=1,
        ),
        retry_circuit_guard={
            "decision_status": "BACKING_OFF",
            "decision_reason": "backoff_window_active",
            "retry_allowed": False,
            "next_retry_at": "2026-09-01T02:45:00Z",
            "failure_threshold": 3,
        },
    )
    idle_runtime = artifact_retention_scheduler_daemon_runtime_payload(
        status="IDLE",
        active_job_id=None,
    )
    bounded_failed_runtime = artifact_retention_scheduler_daemon_runtime_payload(
        status="BUSY",
        runtime_state=artifact_retention_scheduler_daemon_runtime_state_payload(
            lifecycle_status="RUNNING",
            lifecycle_reason="started",
        ),
        bounded_loop_result=artifact_retention_scheduler_daemon_bounded_loop_result_payload(
            result_status="FAILED",
            stop_reason="cycle_failed",
        ),
    )
    configured_disabled = artifact_retention_scheduler_daemon_config_payload()
    configured_disabled["runtime"] = {
        **configured_disabled["runtime"],
        "daemon_auto_start_allowed": True,
    }

    stopping_projection = build_artifact_retention_daemon_lifecycle_projection(
        daemon_config=config,
        daemon_runtime=artifact_retention_scheduler_daemon_runtime_payload(
            runtime_state=stopping_state,
            shutdown_transition={
                "decision_status": "READY",
                "decision_reason": "stop_requested",
                "requested_at": "2026-09-01T02:42:00Z",
            },
        ),
    )
    backoff_projection = build_artifact_retention_daemon_lifecycle_projection(
        daemon_config=config,
        daemon_runtime=backoff_runtime,
    )
    idle_projection = build_artifact_retention_daemon_lifecycle_projection(
        daemon_config=config,
        daemon_runtime=idle_runtime,
    )
    disabled_projection = build_artifact_retention_daemon_lifecycle_projection(
        daemon_config=artifact_retention_scheduler_daemon_config_payload(),
        daemon_runtime=None,
    )
    configured_disabled_projection = (
        build_artifact_retention_daemon_lifecycle_projection(
            daemon_config=configured_disabled,
            daemon_runtime=None,
        )
    )
    bounded_failed_projection = build_artifact_retention_daemon_lifecycle_projection(
        daemon_config=config,
        daemon_runtime=bounded_failed_runtime,
    )
    unknown_projection = build_artifact_retention_daemon_lifecycle_projection(
        daemon_config={},
        daemon_runtime={"heartbeat": {"status": "MAYBE"}},
    )

    assert stopping_projection["lifecycle"]["status"] == "STOPPING"
    assert stopping_projection["lifecycle"]["stop_requested"] is True
    assert stopping_projection["attention"]["attention_status"] == (
        "SHUTDOWN_IN_PROGRESS"
    )
    assert stopping_projection["attention"]["operator_attention_required"] is True
    assert backoff_projection["lifecycle"]["status"] == "RUNNING"
    assert backoff_projection["attention"]["attention_status"] == "RETRY_BACKOFF"
    assert backoff_projection["attention"]["attention_level"] == "INFO"
    assert idle_projection["lifecycle"]["status"] == "STOPPED"
    assert idle_projection["lifecycle"]["reason"] == "heartbeat_idle"
    assert disabled_projection["lifecycle"]["status"] == "DISABLED"
    assert disabled_projection["lifecycle"]["reason"] == "explicit_opt_in_required"
    assert disabled_projection["attention"]["attention_status"] == "OBSERVATION_GAP"
    assert configured_disabled_projection["lifecycle"]["reason"] == (
        "scheduler_daemon_disabled"
    )
    assert bounded_failed_projection["attention"] == {
        "attention_status": "ACTION_REQUIRED",
        "attention_level": "ERROR",
        "reason_code": "bounded_loop_failed",
        "operator_action": "review_ae_scheduler_daemon_bounded_loop",
        "operator_attention_required": True,
        "metadata_only": True,
    }
    assert unknown_projection["projection_status"] == "NO_DAEMON_CONFIG"
    assert unknown_projection["lifecycle"]["status"] == "UNKNOWN"
    assert artifact_operations._normalized_daemon_lifecycle_status("bad") is None
    assert artifact_operations._daemon_lifecycle_status_and_source(
        daemon_config={},
        runtime_state={},
        heartbeat={"status": "STARTING"},
    ) == ("STARTING", "heartbeat")


def test_artifact_retention_daemon_attention_classifies_operational_edges() -> None:
    ready = classify_artifact_retention_daemon_attention(
        daemon_config=artifact_retention_scheduler_daemon_config_payload()
    )
    lease_attention = classify_artifact_retention_daemon_attention(
        daemon_config=artifact_retention_scheduler_daemon_config_payload(
            lease_available=False
        )
    )
    queue_attention = classify_artifact_retention_daemon_attention(
        daemon_config=artifact_retention_scheduler_daemon_config_payload(
            job_queue_available=False
        )
    )
    dispatch_attention = classify_artifact_retention_daemon_attention(
        daemon_config=artifact_retention_scheduler_daemon_config_payload(),
        dispatch_response=artifact_retention_scheduler_daemon_dispatch_payload(
            dispatch_status="FAILED"
        ),
    )
    heartbeat_store_attention = classify_artifact_retention_daemon_attention(
        daemon_config=artifact_retention_scheduler_daemon_config_payload(),
        daemon_runtime=artifact_retention_scheduler_daemon_runtime_payload(
            observed=False,
            heartbeat_store_available=False,
        ),
    )
    heartbeat_error_attention = classify_artifact_retention_daemon_attention(
        daemon_config=artifact_retention_scheduler_daemon_config_payload(),
        daemon_runtime=artifact_retention_scheduler_daemon_runtime_payload(
            status="ERROR",
            active_job_id="daemon-loop-error",
        ),
    )
    unknown_status_attention = classify_artifact_retention_daemon_attention(
        daemon_config=artifact_retention_scheduler_daemon_config_payload(),
        daemon_runtime=artifact_retention_scheduler_daemon_runtime_payload(
            status="MAYBE",
            active_job_id=None,
        ),
    )

    batch_window_config = artifact_retention_scheduler_daemon_config_payload()
    batch_window_config["supported_actions"][1] = {
        **batch_window_config["supported_actions"][1],
        "decision_status": "BLOCKED",
        "runs_tick_once": False,
        "block_reason": "batch_window_closed",
    }
    batch_window_attention = classify_artifact_retention_daemon_attention(
        daemon_config=batch_window_config
    )
    control_attention_config = artifact_retention_scheduler_daemon_config_payload()
    control_attention_config["supported_actions"][1] = {
        **control_attention_config["supported_actions"][1],
        "decision_status": "BLOCKED",
        "runs_tick_once": False,
        "block_reason": "operator_dispatch_admission_disabled",
    }
    control_attention = classify_artifact_retention_daemon_attention(
        daemon_config=control_attention_config
    )
    missing_attention = classify_artifact_retention_daemon_attention(
        daemon_config={}
    )

    assert ready["attention_schema_version"] == (
        AG_ARTIFACT_OPERATION_RETENTION_DAEMON_ATTENTION_SCHEMA_VERSION
    )
    assert ready["attention_status"] == "READY"
    assert ready["attention_level"] == "OK"
    assert ready["operator_attention_required"] is False
    assert ready["manual_tick_once_safe"] is True
    assert ready["reason_codes"] == [
        "manual_tick_once_ready",
        "start_daemon_disabled_by_policy",
        "continuous_loop_disabled_by_policy",
    ]
    assert lease_attention["attention_status"] == "LEASE_ATTENTION"
    assert lease_attention["reason_codes"][0] == "lease_repository_unavailable"
    assert lease_attention["operator_actions"] == [
        "configure_ae_scheduler_lease_repository"
    ]
    assert lease_attention["operator_attention_required"] is True
    assert queue_attention["attention_status"] == "QUEUE_ATTENTION"
    assert queue_attention["reason_codes"][0] == "job_queue_unavailable"
    assert queue_attention["operator_actions"] == ["configure_ae_job_queue"]
    assert dispatch_attention["attention_status"] == "DISPATCH_ATTENTION"
    assert dispatch_attention["attention_level"] == "WARN"
    assert "last_dispatch_failed" in dispatch_attention["reason_codes"]
    assert heartbeat_store_attention["attention_status"] == "HEARTBEAT_ATTENTION"
    assert heartbeat_store_attention["reason_codes"] == [
        "heartbeat_store_unavailable",
        "start_daemon_disabled_by_policy",
        "continuous_loop_disabled_by_policy",
    ]
    assert heartbeat_store_attention["operator_actions"] == [
        "inspect_ae_scheduler_daemon_runtime_route",
        "configure_ae_scheduler_daemon_heartbeat_store",
    ]
    assert heartbeat_store_attention["operator_attention_required"] is True
    assert heartbeat_error_attention["attention_status"] == "HEARTBEAT_ATTENTION"
    assert heartbeat_error_attention["reason_codes"][0] == "daemon_heartbeat_error"
    assert heartbeat_error_attention["operator_actions"] == [
        "review_ae_scheduler_daemon_error_heartbeat",
        "inspect_ae_artifact_retention_history",
    ]
    assert unknown_status_attention["attention_status"] == "HEARTBEAT_ATTENTION"
    assert unknown_status_attention["reason_codes"][0] == (
        "daemon_heartbeat_status_unknown"
    )
    assert batch_window_attention["attention_status"] == "BATCH_WINDOW_ATTENTION"
    assert batch_window_attention["operator_actions"] == [
        "retry_inside_retention_batch_window"
    ]
    assert control_attention["attention_status"] == "CONTROL_POLICY_BLOCKED"
    assert control_attention["operator_actions"] == [
        "review_ae_daemon_control_policy"
    ]
    assert missing_attention == {
        "attention_schema_version": (
            AG_ARTIFACT_OPERATION_RETENTION_DAEMON_ATTENTION_SCHEMA_VERSION
        ),
        "attention_status": "NO_DAEMON_CONFIG",
        "attention_level": "INFO",
        "reason_codes": ["daemon_config_missing"],
        "operator_actions": ["load_ae_scheduler_daemon_config"],
        "operator_attention_required": False,
        "manual_tick_once_safe": False,
        "start_daemon_blocked_by_policy": False,
        "continuous_loop_blocked_by_policy": False,
        "batch_window_enforced": False,
        "metadata_only": True,
    }


def test_artifact_retention_daemon_runtime_issue_candidates_are_metadata_only() -> (
    None
):
    runtime = artifact_retention_scheduler_daemon_runtime_payload(
        status="ERROR",
        active_job_id="daemon-loop-error",
    )
    projection = build_artifact_operation_retention_daemon_projection(
        daemon_config=artifact_retention_scheduler_daemon_config_payload(),
        daemon_runtime=runtime,
        source_client=InMemoryAeArtifactOperationsClient(),
    )
    store_candidates = (
        artifact_operations.build_artifact_retention_daemon_runtime_issue_candidates(
            daemon_runtime=artifact_retention_scheduler_daemon_runtime_payload(
                observed=False,
                heartbeat_store_available=False,
            )
        )
    )
    unknown_candidates = (
        artifact_operations.build_artifact_retention_daemon_runtime_issue_candidates(
            daemon_runtime=artifact_retention_scheduler_daemon_runtime_payload(
                status="MAYBE",
                active_job_id=None,
            )
        )
    )

    assert projection["summary"]["attention_status"] == "HEARTBEAT_ATTENTION"
    assert projection["summary"]["attention_reason_codes"][0] == (
        "daemon_heartbeat_error"
    )
    assert projection["summary"]["runtime_issue_candidate_count"] == 1
    assert projection["attention"]["operator_attention_required"] is True
    assert len(projection["issue_candidates"]) == 1
    candidate = projection["issue_candidates"][0]
    assert candidate["candidate_schema_version"] == (
        artifact_operations.AG_ARTIFACT_OPERATION_RETENTION_DAEMON_RUNTIME_ISSUE_CANDIDATE_SCHEMA_VERSION
    )
    assert candidate["rule_id"] == "ae_scheduler_daemon_heartbeat_error.v1"
    assert candidate["service_id"] == "nex-ae-api"
    assert candidate["severity"] == "ERROR"
    assert candidate["signal"] == {
        "worker_type": "ae.artifact_retention.scheduler_daemon",
        "worker_id": "ae-retention-daemon-runtime-0538",
        "active_job_id": "daemon-loop-error",
        "last_seen_at": "2026-09-01T02:40:00Z",
        "phase": "tick_once_running",
    }
    assert candidate["recommended_operator_actions"] == [
        "review_ae_scheduler_daemon_error_heartbeat",
        "inspect_ae_artifact_retention_history",
    ]
    assert candidate["metadata_only"] is True
    assert store_candidates[0]["rule_id"] == (
        "ae_scheduler_daemon_heartbeat_store_unavailable.v1"
    )
    assert store_candidates[0]["severity"] == "WARNING"
    assert store_candidates[0]["signal"]["failure_code"] == (
        "heartbeat_store_unavailable"
    )
    assert unknown_candidates[0]["rule_id"] == (
        "ae_scheduler_daemon_heartbeat_status_unknown.v1"
    )
    assert unknown_candidates[0]["severity"] == "WARNING"
    assert "DATABASE_URL_SHOULD_NOT_LEAK" not in str(projection)
    assert "nuri1004" not in str(projection)


def test_artifact_operation_retention_automation_projection_summarizes_and_redacts() -> (
    None
):
    projection = build_artifact_operation_retention_automation_projection(
        plan=artifact_retention_batch_plan_payload(),
        scheduled_jobs=artifact_retention_scheduled_job_collection_payload(),
        history=artifact_retention_history_collection_payload(),
        daemon_config=artifact_retention_scheduler_daemon_config_payload(),
        daemon_process_snapshots=(
            artifact_retention_scheduler_daemon_supervised_process_collection_payload()
        ),
        operator_control_policy=(
            artifact_retention_scheduler_daemon_operator_control_policy_payload()
        ),
        operator_control_facade=(
            artifact_retention_scheduler_daemon_operator_control_facade_payload(
                action="status_probe"
            )
        ),
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
    assert projection["scheduler_daemon"]["attention"]["attention_status"] == "READY"
    assert projection["scheduler_daemon_processes"]["summary"][
        "supervised_process_record_count"
    ] == 2
    assert projection["scheduler_daemon_processes"]["summary"]["running_count"] == 1
    assert projection["scheduler_daemon_processes"]["summary"]["stale_count"] == 1
    assert projection["operator_control"]["summary"]["action"] == "status_probe"
    assert projection["operator_control"]["summary"]["facade_status"] == "READY"
    assert projection["operator_control"]["summary"]["restart_supported"] is True
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
        "daemon_attention_status": "READY",
        "daemon_attention_level": "OK",
        "daemon_attention_reason_codes": [
            "manual_tick_once_ready",
            "start_daemon_disabled_by_policy",
            "continuous_loop_disabled_by_policy",
        ],
        "daemon_attention_operator_actions": ["manual_tick_once_available"],
        "daemon_process_record_count": 2,
        "daemon_process_running_count": 1,
        "daemon_process_failed_count": 0,
        "daemon_process_stale_count": 1,
        "daemon_process_blocked_count": 0,
        "daemon_process_adapter_required_count": 2,
        "daemon_process_operator_attention_required": True,
        "daemon_process_status_counts": {"RUNNING": 1, "STALE": 1},
        "daemon_process_latest_observed_at": "2026-09-02T01:12:09Z",
        "operator_control_policy_loaded": True,
        "operator_control_facade_loaded": True,
        "operator_control_action": "status_probe",
        "operator_control_facade_status": "READY",
        "operator_control_ready_for_dispatch": True,
        "operator_control_command_preview_count": 1,
        "operator_control_restart_supported": True,
        "operator_control_operator_attention_required": False,
        "operator_control_preview_only": True,
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
        "latest_activity_at": "2026-09-02T01:12:09Z",
    }
    assert projection["source_status"]["batch_plan_loaded"] is True
    assert projection["source_status"]["scheduled_jobs_loaded"] is True
    assert projection["source_status"]["history_loaded"] is True
    assert projection["source_status"]["daemon_config_loaded"] is True
    assert projection["source_status"]["daemon_process_snapshots_loaded"] is True
    assert projection["source_status"]["daemon_process_snapshot_count"] == 2
    assert projection["source_status"]["operator_control_policy_loaded"] is True
    assert projection["source_status"]["operator_control_facade_loaded"] is True
    assert projection["operator_guidance"]["ae_daemon_config_route"] == (
        "/api/v1/artifact-retention/scheduler-daemon-config"
    )
    assert projection["operator_guidance"]["ag_daemon_operations_route"] == (
        "/admin/v1/operations/artifact-retention/scheduler-daemon"
    )
    assert projection["operator_guidance"]["ag_daemon_process_snapshots_route"] == (
        "/admin/v1/operations/artifact-retention/"
        "scheduler-daemon-process-snapshots"
    )
    assert projection["operator_guidance"]["ag_operator_control_preview_route"] == (
        "/admin/v1/operations/artifact-retention/"
        "scheduler-daemon-operator-control-preview"
    )
    assert projection["operator_guidance"]["ag_direct_database_write_allowed"] is False
    assert projection["operator_guidance"]["ag_direct_job_enqueue_allowed"] is False
    assert (
        projection["operator_guidance"]["ag_direct_daemon_process_control_allowed"]
        is False
    )
    assert projection["operator_guidance"]["operator_control_preview_only"] is True
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
    assert projection["summary"]["daemon_attention_status"] == "NO_DAEMON_CONFIG"
    assert projection["summary"]["daemon_attention_reason_codes"] == [
        "daemon_config_missing"
    ]
    assert projection["summary"]["daemon_process_record_count"] == 0
    assert projection["summary"]["daemon_process_operator_attention_required"] is False
    assert projection["summary"]["operator_control_policy_loaded"] is False
    assert projection["summary"]["operator_control_facade_loaded"] is False
    assert projection["summary"]["operator_control_action"] is None
    assert projection["summary"]["operator_control_preview_only"] is True
    assert projection["summary"]["latest_activity_at"] == "2026-09-01T02:05:00Z"
    assert projection["source_status"]["batch_plan_loaded"] is False
    assert projection["source_status"]["scheduled_jobs_loaded"] is False
    assert projection["source_status"]["history_loaded"] is False
    assert projection["source_status"]["daemon_config_loaded"] is False
    assert projection["source_status"]["daemon_process_snapshots_loaded"] is False
    assert projection["source_status"]["operator_control_policy_loaded"] is False
    assert projection["source_status"]["operator_control_facade_loaded"] is False
    assert projection["source_status"]["errors"][0]["error_code"] == (
        "ag.optional_retention_automation_warning"
    )
    process_degraded = build_artifact_operation_retention_automation_projection(
        plan=artifact_retention_batch_plan_payload(),
        scheduled_jobs=artifact_retention_scheduled_job_collection_payload(),
        history=artifact_retention_history_collection_payload(),
        daemon_config=artifact_retention_scheduler_daemon_config_payload(),
        daemon_process_errors=[
            AeArtifactOperationsError(
                error_code="ag.optional_process_read_model_warning",
                detail="AE supervised process read model unavailable",
                status_code=503,
            )
        ],
    )
    assert process_degraded["projection_status"] == "DEGRADED"
    assert process_degraded["source_status"]["batch_plan_loaded"] is True
    assert process_degraded["source_status"]["scheduled_jobs_loaded"] is True
    assert process_degraded["source_status"]["history_loaded"] is True
    assert process_degraded["source_status"]["daemon_config_loaded"] is True
    assert (
        process_degraded["source_status"]["daemon_process_snapshots_loaded"] is False
    )
    assert process_degraded["source_status"]["errors"][0]["error_code"] == (
        "ag.optional_process_read_model_warning"
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
    assert idle_summary["daemon_process_record_count"] == 0
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
    assert (
        artifact_operations._normalized_daemon_supervisor_action("start-daemon")
        == "start_daemon"
    )
    assert artifact_operations._normalized_daemon_supervisor_action("bad") is None
    assert artifact_operations._normalized_daemon_supervisor_action(None) is None
    assert (
        artifact_operations._normalized_daemon_supervisor_result_status("blocked")
        == "BLOCKED"
    )
    assert (
        artifact_operations._normalized_daemon_supervisor_result_status("bad")
        is None
    )
    assert (
        artifact_operations._normalized_daemon_supervisor_result_status(None)
        is None
    )
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
    source_client = artifact_client()
    captured_operator_control_preview: dict[str, Any] = {}
    original_operator_control_preview = (
        source_client.preview_artifact_retention_scheduler_daemon_operator_control
    )

    def capture_operator_control_preview(**kwargs: Any) -> dict[str, Any]:
        captured_operator_control_preview.update(kwargs)
        return original_operator_control_preview(**kwargs)

    source_client.preview_artifact_retention_scheduler_daemon_operator_control = (
        capture_operator_control_preview
    )
    client = build_app(source_client)

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
    assert payload["scheduler_daemon"]["attention"]["attention_status"] == "READY"
    assert payload["scheduler_daemon_processes"]["summary"][
        "supervised_process_record_count"
    ] == 2
    assert payload["scheduler_daemon_processes"]["summary"]["running_count"] == 1
    assert payload["scheduler_daemon_processes"]["summary"]["stale_count"] == 1
    assert payload["summary"]["safety_status"] == "FAILED_ATTENTION"
    assert payload["summary"]["daemon_manual_tick_once_available"] is True
    assert payload["summary"]["daemon_start_daemon_available"] is False
    assert payload["summary"]["daemon_attention_status"] == "READY"
    assert payload["summary"]["daemon_process_record_count"] == 2
    assert payload["summary"]["daemon_process_operator_attention_required"] is True
    assert payload["summary"]["operator_control_policy_loaded"] is True
    assert payload["summary"]["operator_control_facade_loaded"] is True
    assert payload["summary"]["operator_control_action"] == "status_probe"
    assert payload["summary"]["operator_control_facade_status"] == "READY"
    assert payload["summary"]["operator_control_command_preview_count"] == 1
    assert payload["operator_control"]["summary"]["policy_loaded"] is True
    assert payload["operator_control"]["summary"]["facade_loaded"] is True
    assert payload["operator_control"]["preview_only"] is True
    assert payload["summary"]["daemon_attention_reason_codes"] == [
        "manual_tick_once_ready",
        "start_daemon_disabled_by_policy",
        "continuous_loop_disabled_by_policy",
    ]
    assert payload["summary"]["physical_delete_operator_approval_required"] is True
    assert payload["source_status"]["daemon_config_loaded"] is True
    assert payload["source_status"]["daemon_process_snapshots_loaded"] is True
    assert payload["source_status"]["operator_control_policy_loaded"] is True
    assert payload["source_status"]["operator_control_facade_loaded"] is True
    assert payload["operator_guidance"]["ae_daemon_config_route"] == (
        "/api/v1/artifact-retention/scheduler-daemon-config"
    )
    assert payload["operator_guidance"]["ae_daemon_process_snapshots_route"] == (
        "/api/v1/artifact-retention/scheduler-daemon-process-snapshots"
    )
    assert payload["operator_guidance"]["ae_operator_control_preview_route"] == (
        "/api/v1/artifact-retention/scheduler-daemon-operator-control-preview"
    )
    assert payload["operator_guidance"]["ag_operator_control_preview_route"] == (
        "/admin/v1/operations/artifact-retention/"
        "scheduler-daemon-operator-control-preview"
    )
    assert payload["operator_guidance"]["ag_direct_database_write_allowed"] is False
    assert (
        payload["operator_guidance"]["ag_direct_daemon_process_control_allowed"]
        is False
    )
    assert payload["request_trace_id"] == TRACE_ID
    assert captured_operator_control_preview["action"] == "status_probe"
    assert captured_operator_control_preview["idempotency_key"].startswith(
        "ag-artifact-retention-automation-operator-control:"
    )
    assert captured_operator_control_preview["operator_subject"] == {
        "actor_type": "service",
        "actor_id": "nex-ag",
        "service_id": "nex-ag",
    }
    assert captured_operator_control_preview["current_process"][
        "process_status"
    ] == "RUNNING"
    assert captured_operator_control_preview["current_process"][
        "process_source"
    ] == "scheduler_daemon_process_snapshots"
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

    class BrokenRetentionAutomationProcessClient(InMemoryAeArtifactOperationsClient):
        def list_artifact_retention_scheduler_daemon_process_snapshots(
            self,
            *args: Any,
            **kwargs: Any,
        ) -> dict[str, Any]:
            raise AeArtifactOperationsError(
                error_code="ag.ae_artifact_retention_automation_process_failed",
                detail="AE retention daemon process read model unavailable",
                status_code=503,
            )

    process_source_degraded = build_app(
        BrokenRetentionAutomationProcessClient(
            artifact_retention_batch_plans=artifact_client().artifact_retention_batch_plans,
            artifact_retention_scheduled_job_collections=(
                artifact_client().artifact_retention_scheduled_job_collections
            ),
            artifact_retention_history_collections=(
                artifact_client().artifact_retention_history_collections
            ),
            artifact_retention_scheduler_daemon_config=(
                artifact_retention_scheduler_daemon_config_payload()
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
    operator_control_policy_source = artifact_client()

    def broken_operator_control_policy(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AeArtifactOperationsError(
            error_code="ag.ae_artifact_retention_automation_operator_control_failed",
            detail="AE operator-control policy unavailable",
            status_code=503,
        )

    operator_control_policy_source.get_artifact_retention_scheduler_daemon_operator_control_policy = (
        broken_operator_control_policy
    )
    operator_control_policy_degraded = build_app(operator_control_policy_source).get(
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
    operator_control_preview_source = artifact_client()

    def broken_operator_control_preview(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AeArtifactOperationsError(
            error_code="ag.ae_artifact_retention_automation_operator_preview_failed",
            detail="AE operator-control preview unavailable",
            status_code=503,
        )

    operator_control_preview_source.preview_artifact_retention_scheduler_daemon_operator_control = (
        broken_operator_control_preview
    )
    operator_control_preview_degraded = build_app(operator_control_preview_source).get(
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
    assert process_source_degraded.status_code == 200
    assert process_source_degraded.json()["projection_status"] == "DEGRADED"
    assert (
        process_source_degraded.json()["source_status"][
            "daemon_process_snapshots_loaded"
        ]
        is False
    )
    assert process_source_degraded.json()["source_status"]["errors"][0][
        "error_code"
    ] == "ag.ae_artifact_retention_automation_process_failed"
    assert operator_control_policy_degraded.status_code == 200
    assert operator_control_policy_degraded.json()["projection_status"] == "DEGRADED"
    assert (
        operator_control_policy_degraded.json()["source_status"][
            "operator_control_policy_loaded"
        ]
        is False
    )
    assert operator_control_policy_degraded.json()["source_status"]["errors"][0][
        "error_code"
    ] == "ag.ae_artifact_retention_automation_operator_control_failed"
    assert operator_control_preview_degraded.status_code == 200
    assert operator_control_preview_degraded.json()["projection_status"] == "DEGRADED"
    assert (
        operator_control_preview_degraded.json()["source_status"][
            "operator_control_policy_loaded"
        ]
        is True
    )
    assert (
        operator_control_preview_degraded.json()["source_status"][
            "operator_control_facade_loaded"
        ]
        is False
    )
    assert operator_control_preview_degraded.json()["source_status"]["errors"][0][
        "error_code"
    ] == "ag.ae_artifact_retention_automation_operator_preview_failed"


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
    assert payload["summary"]["attention_status"] == "READY"
    assert payload["summary"]["runtime_heartbeat_status"] == "BUSY"
    assert payload["summary"]["runtime_heartbeat_observed"] is True
    assert payload["summary"]["lifecycle_status"] == "RUNNING"
    assert payload["summary"]["lifecycle_source"] == "heartbeat"
    assert payload["summary"]["lifecycle_attention_status"] == "READY"
    assert payload["attention"]["attention_status"] == "READY"
    assert payload["lifecycle_projection"]["lifecycle"]["status"] == "RUNNING"
    assert payload["lifecycle_projection"]["lifecycle"]["source"] == "heartbeat"
    assert payload["lifecycle_projection"]["operator_guidance"][
        "ag_direct_daemon_process_control_allowed"
    ] is False
    assert payload["daemon_runtime"]["heartbeat"]["worker_id"] == (
        "ae-retention-daemon-runtime-0538"
    )
    assert payload["source_status"]["daemon_config_loaded"] is True
    assert payload["source_status"]["daemon_runtime_loaded"] is True
    assert payload["operator_guidance"]["manual_tick_once_only"] is True
    assert payload["operator_guidance"]["ae_daemon_runtime_route"] == (
        "/api/v1/artifact-retention/scheduler-daemon-runtime"
    )
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

    class BrokenDaemonRuntimeClient(InMemoryAeArtifactOperationsClient):
        def __init__(self) -> None:
            super().__init__(
                artifact_retention_scheduler_daemon_config=(
                    artifact_retention_scheduler_daemon_config_payload()
                )
            )

        def get_artifact_retention_scheduler_daemon_runtime(
            self,
            *args: Any,
            **kwargs: Any,
        ) -> dict[str, Any]:
            raise AeArtifactOperationsError(
                error_code="ag.ae_artifact_retention_daemon_runtime_failed",
                detail="AE scheduler daemon runtime unavailable",
                status_code=503,
            )

    runtime_failed = build_app(BrokenDaemonRuntimeClient()).get(
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
    assert runtime_failed.status_code == 200
    runtime_payload = runtime_failed.json()
    assert runtime_payload["projection_status"] == "DEGRADED"
    assert runtime_payload["source_status"]["daemon_config_loaded"] is False
    assert runtime_payload["source_status"]["daemon_runtime_loaded"] is False
    assert runtime_payload["source_status"]["errors"][0]["error_code"] == (
        "ag.ae_artifact_retention_daemon_runtime_warning"
    )


def test_artifact_retention_scheduler_daemon_run_projections_summarize_and_redact() -> (
    None
):
    collection = artifact_retention_scheduler_daemon_run_collection_payload()
    detail = artifact_retention_scheduler_daemon_run_detail_payload()
    collection_projection = (
        build_artifact_operation_retention_daemon_run_collection_projection(
            collection=collection,
            source_client=artifact_client(),
            request_trace_id=TRACE_ID,
        )
    )
    detail_projection = build_artifact_operation_retention_daemon_run_detail_projection(
        detail=detail,
        source_client=artifact_client(),
        request_trace_id=TRACE_ID,
    )

    assert collection_projection["projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_RETENTION_DAEMON_RUN_COLLECTION_PROJECTION_SCHEMA_VERSION
    )
    assert collection_projection["operation_type"] == (
        "ae_artifact_retention_scheduler_daemon_runs"
    )
    assert collection_projection["summary"] == (
        summarize_artifact_retention_daemon_run_operations(
            collection_projection["items"]
        )
    )
    assert collection_projection["summary"]["run_count"] == 2
    assert collection_projection["summary"]["succeeded_count"] == 1
    assert collection_projection["summary"]["failed_count"] == 1
    assert collection_projection["summary"]["operator_attention_required"] is True
    assert collection_projection["source_status"]["run_collection_loaded"] is True
    assert collection_projection["operator_guidance"][
        "ag_direct_daemon_process_control_allowed"
    ] is False
    assert detail_projection["projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_RETENTION_DAEMON_RUN_DETAIL_PROJECTION_SCHEMA_VERSION
    )
    assert detail_projection["summary"] == (
        summarize_artifact_retention_daemon_run_detail(
            run_record=detail_projection["run_record"],
            lifecycle_events=detail_projection["lifecycle_events"],
        )
    )
    assert detail_projection["summary"]["lifecycle_event_types"] == [
        "RUN_STARTED",
        "RUN_COMPLETED",
    ]
    assert detail_projection["source_status"]["run_detail_loaded"] is True
    assert "daemon_cli_execution_result_id" in detail_projection["run_record"]
    assert collection_projection["items"][0]["metadata"][
        "execution_payload_included"
    ] is False
    assert_artifact_operation_projection_redacted(collection_projection)
    assert_artifact_operation_projection_redacted(detail_projection)


def test_artifact_retention_scheduler_daemon_supervisor_projections_summarize_and_redact() -> (
    None
):
    collection = artifact_retention_scheduler_daemon_supervisor_collection_payload()
    detail = artifact_retention_scheduler_daemon_supervisor_detail_payload()
    collection_projection = (
        build_artifact_operation_retention_daemon_supervisor_collection_projection(
            collection=collection,
            source_client=artifact_client(),
            request_trace_id=TRACE_ID,
        )
    )
    detail_projection = (
        build_artifact_operation_retention_daemon_supervisor_detail_projection(
            detail=detail,
            source_client=artifact_client(),
            request_trace_id=TRACE_ID,
        )
    )

    assert collection_projection["projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_RETENTION_DAEMON_SUPERVISOR_COLLECTION_PROJECTION_SCHEMA_VERSION
    )
    assert collection_projection["operation_type"] == (
        "ae_artifact_retention_scheduler_daemon_supervisor_results"
    )
    assert collection_projection["filter"] == {
        "scheduler_id": "ae-artifact-retention-scheduler",
        "action": None,
        "result_status": None,
    }
    assert collection_projection["summary"] == (
        summarize_artifact_retention_daemon_supervisor_operations(
            collection_projection["items"]
        )
    )
    assert collection_projection["summary"]["supervisor_record_count"] == 2
    assert collection_projection["summary"]["ready_count"] == 1
    assert collection_projection["summary"]["blocked_count"] == 1
    assert collection_projection["summary"]["adapter_invoked_count"] == 2
    assert collection_projection["summary"]["operator_attention_required"] is False
    assert collection_projection["source_status"][
        "supervisor_collection_loaded"
    ] is True
    assert collection_projection["operator_guidance"][
        "ag_direct_daemon_process_control_allowed"
    ] is False
    assert collection_projection["items"][0]["metadata"][
        "persistence_endpoint_included"
    ] is False
    assert collection_projection["items"][0]["routes"]["ag_detail"].endswith(
        "/scheduler-daemon-supervisor-results/daemon-supervisor-record-0567"
    )
    assert "supervisor_command" not in collection_projection["items"][0]
    assert "supervisor_result" not in collection_projection["items"][0]

    assert detail_projection["projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_RETENTION_DAEMON_SUPERVISOR_DETAIL_PROJECTION_SCHEMA_VERSION
    )
    assert detail_projection["summary"] == (
        summarize_artifact_retention_daemon_supervisor_detail(
            supervisor_record=detail_projection["supervisor_record"],
            supervisor_events=detail_projection["supervisor_events"],
        )
    )
    assert detail_projection["summary"]["supervisor_event_types"] == [
        "SUPERVISOR_COMMAND_ACCEPTED",
        "SUPERVISOR_RESULT_RECORDED",
    ]
    assert detail_projection["source_status"]["supervisor_detail_loaded"] is True
    assert detail_projection["supervisor_record"]["supervisor_result_hash"] == "f" * 64
    assert "supervisor_command" not in detail_projection["supervisor_record"]
    assert "supervisor_result" not in detail_projection["supervisor_record"]
    assert "database_url" not in str(collection_projection)
    assert "/data/nex-platform" not in str(detail_projection)
    assert_artifact_operation_projection_redacted(collection_projection)
    assert_artifact_operation_projection_redacted(detail_projection)

    degraded_projection = (
        build_artifact_operation_retention_daemon_supervisor_collection_projection(
            collection={"items": [], "filter": {}, "count": 0, "limit": 20},
            source_client=artifact_client(),
            source_errors=[
                AeArtifactOperationsError(
                    error_code=(
                        "ag.ae_artifact_retention_daemon_supervisor_source_failed"
                    ),
                    detail="AE scheduler daemon supervisor source unavailable",
                    status_code=503,
                )
            ],
        )
    )
    assert degraded_projection["projection_status"] == "DEGRADED"
    assert degraded_projection["source_status"][
        "supervisor_collection_loaded"
    ] is False
    assert degraded_projection["source_status"]["errors"][0]["status_code"] == 503


def test_in_memory_artifact_operations_client_returns_supervisor_read_models() -> None:
    source_client = artifact_client()

    collection = (
        source_client.list_artifact_retention_scheduler_daemon_supervisor_results(
            scheduler_id="ae-artifact-retention-scheduler",
            action="start_daemon",
            result_status="BLOCKED",
            limit=1,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    )
    collection["items"][0]["result_status"] = "FAILED"
    collection_again = (
        source_client.list_artifact_retention_scheduler_daemon_supervisor_results(
            scheduler_id="ae-artifact-retention-scheduler",
            action="start_daemon",
            result_status="BLOCKED",
            limit=1,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    )
    fallback = (
        source_client.list_artifact_retention_scheduler_daemon_supervisor_results(
            scheduler_id="ae-artifact-retention-scheduler",
            action="stop_daemon",
            result_status="NOOP",
            limit=5,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    )
    detail = source_client.get_artifact_retention_scheduler_daemon_supervisor_detail(
        "daemon-supervisor-record-0567",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    missing = source_client.get_artifact_retention_scheduler_daemon_supervisor_detail(
        "missing",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert collection_again["count"] == 1
    assert collection_again["items"][0]["result_status"] == "BLOCKED"
    assert fallback["count"] == 0
    assert fallback["filter"] == {
        "scheduler_id": "ae-artifact-retention-scheduler",
        "action": "stop_daemon",
        "result_status": "NOOP",
    }
    assert detail is not None
    assert detail["daemon_supervisor_record_id"] == "daemon-supervisor-record-0567"
    assert missing is None


def test_artifact_retention_scheduler_daemon_supervised_process_projections_summarize_and_redact() -> (
    None
):
    collection = (
        artifact_retention_scheduler_daemon_supervised_process_collection_payload()
    )
    detail = artifact_retention_scheduler_daemon_supervised_process_detail_payload()
    collection_projection = (
        build_artifact_operation_retention_daemon_supervised_process_collection_projection(
            collection=collection,
            source_client=artifact_client(),
            request_trace_id=TRACE_ID,
        )
    )
    detail_projection = (
        build_artifact_operation_retention_daemon_supervised_process_detail_projection(
            detail=detail,
            source_client=artifact_client(),
            request_trace_id=TRACE_ID,
        )
    )

    assert collection_projection["projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_RETENTION_DAEMON_SUPERVISED_PROCESS_COLLECTION_PROJECTION_SCHEMA_VERSION
    )
    assert collection_projection["operation_type"] == (
        "ae_artifact_retention_scheduler_daemon_process_snapshots"
    )
    assert collection_projection["filter"] == {
        "scheduler_id": "ae-artifact-retention-scheduler",
        "action": None,
        "process_status": None,
    }
    assert collection_projection["summary"] == (
        summarize_artifact_retention_daemon_supervised_process_operations(
            collection_projection["items"]
        )
    )
    assert collection_projection["summary"]["supervised_process_record_count"] == 2
    assert collection_projection["summary"]["running_count"] == 1
    assert collection_projection["summary"]["stale_count"] == 1
    assert collection_projection["summary"]["adapter_required_count"] == 2
    assert collection_projection["summary"][
        "operator_attention_required"
    ] is True
    assert collection_projection["source_status"][
        "process_snapshot_collection_loaded"
    ] is True
    assert collection_projection["operator_guidance"][
        "ag_direct_daemon_process_control_allowed"
    ] is False
    assert collection_projection["items"][0]["metadata"][
        "persistence_endpoint_included"
    ] is False
    assert collection_projection["items"][0]["routes"]["ag_detail"].endswith(
        "/scheduler-daemon-process-snapshots/"
        "daemon-supervised-process-record-0576"
    )
    assert "supervised_process_snapshot" not in collection_projection["items"][0]

    assert detail_projection["projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_RETENTION_DAEMON_SUPERVISED_PROCESS_DETAIL_PROJECTION_SCHEMA_VERSION
    )
    assert detail_projection["summary"] == (
        summarize_artifact_retention_daemon_supervised_process_detail(
            supervised_process_record=(
                detail_projection["supervised_process_record"]
            ),
            supervised_process_events=(
                detail_projection["supervised_process_events"]
            ),
        )
    )
    assert detail_projection["summary"]["supervised_process_event_types"] == [
        "PROCESS_START_OBSERVED",
        "PROCESS_SNAPSHOT_RECORDED",
    ]
    assert detail_projection["source_status"][
        "process_snapshot_detail_loaded"
    ] is True
    assert detail_projection["supervised_process_record"][
        "supervised_process_snapshot_hash"
    ] == "9" * 64
    assert "supervised_process_snapshot" not in (
        detail_projection["supervised_process_record"]
    )
    assert "database_url" not in str(collection_projection)
    assert "/data/nex-platform" not in str(detail_projection)
    assert_artifact_operation_projection_redacted(collection_projection)
    assert_artifact_operation_projection_redacted(detail_projection)

    degraded_projection = (
        build_artifact_operation_retention_daemon_supervised_process_collection_projection(
            collection={"items": [], "filter": {}, "count": 0, "limit": 20},
            source_client=artifact_client(),
            source_errors=[
                AeArtifactOperationsError(
                    error_code=(
                        "ag.ae_artifact_retention_daemon_process_source_failed"
                    ),
                    detail="AE scheduler daemon process source unavailable",
                    status_code=503,
                )
            ],
        )
    )
    assert degraded_projection["projection_status"] == "DEGRADED"
    assert degraded_projection["source_status"][
        "process_snapshot_collection_loaded"
    ] is False
    assert degraded_projection["source_status"]["errors"][0]["status_code"] == 503


def test_artifact_retention_scheduler_daemon_operator_control_projection_redacts_and_summarizes() -> (
    None
):
    policy = artifact_retention_scheduler_daemon_operator_control_policy_payload()
    facade = artifact_retention_scheduler_daemon_operator_control_facade_payload()

    projection = build_artifact_operation_retention_daemon_operator_control_projection(
        policy=policy,
        facade=facade,
        source_client=artifact_client(),
        request_trace_id=TRACE_ID,
    )
    summary = summarize_artifact_retention_daemon_operator_control_projection(
        policy=projection["policy"],
        facade=projection["facade"] or {},
    )
    sparse_projection = (
        build_artifact_operation_retention_daemon_operator_control_projection(
            policy={},
            facade={},
            source_client=artifact_client(),
            source_errors=[
                AeArtifactOperationsError(
                    error_code=(
                        "ag.ae_artifact_retention_daemon_operator_control_failed"
                    ),
                    detail="AE operator-control source unavailable",
                    status_code=503,
                )
            ],
        )
    )

    assert projection["projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_PROJECTION_SCHEMA_VERSION
    )
    assert projection["operation_type"] == (
        "ae_artifact_retention_scheduler_daemon_operator_control"
    )
    assert projection["summary"] == summary
    assert projection["summary"]["supported_action_count"] == 4
    assert projection["summary"]["mutating_action_count"] == 3
    assert projection["summary"]["restart_supported"] is True
    assert projection["summary"]["action"] == "restart_daemon"
    assert projection["summary"]["facade_status"] == "READY"
    assert projection["summary"]["command_preview_count"] == 2
    assert projection["summary"]["supervisor_actions"] == [
        "stop_daemon",
        "start_daemon",
    ]
    assert projection["facade"]["operator_control_request"][
        "idempotency_key_present"
    ] is True
    assert projection["facade"]["operator_control_request"][
        "reason_present"
    ] is True
    assert projection["facade"]["operator_control_request"]["operator_subject"] == {
        "actor_type": "operator",
        "actor_id": "ag-retention-operator",
        "tenant_id": "tenant-0409",
        "workspace_id": "workspace-0409",
    }
    assert projection["facade"]["operator_control_admission"][
        "current_process"
    ]["process_status"] == "RUNNING"
    assert projection["facade"]["operator_control_command_preview"][
        "supervisor_command_previews"
    ][0]["command_action"] == "stop_daemon"
    assert projection["operator_guidance"]["preview_only"] is True
    assert projection["operator_guidance"][
        "ag_direct_process_control_allowed"
    ] is False
    assert projection["operator_guidance"][
        "ag_direct_database_write_allowed"
    ] is False
    assert projection["source_status"]["operator_control_policy_loaded"] is True
    assert projection["source_status"]["operator_control_facade_loaded"] is True
    assert sparse_projection["projection_status"] == "DEGRADED"
    assert sparse_projection["summary"]["policy_loaded"] is False
    assert sparse_projection["source_status"][
        "operator_control_policy_loaded"
    ] is False
    assert "operator-control-idem-0587" not in str(projection)
    assert "SECRET_SYSTEM_PROMPT" not in str(projection)
    assert "DATABASE_URL_SHOULD_NOT_LEAK" not in str(projection)
    assert "/data/nex-platform" not in str(projection)
    assert_artifact_operation_projection_redacted(projection)


def test_artifact_retention_scheduler_daemon_operator_control_projection_handles_sparse_edges() -> (
    None
):
    policy = {
        "operator_control_policy_id": "operator-control-policy-sparse",
        "scheduler_id": "ae-artifact-retention-scheduler",
        "supported_actions": [
            {"action": "status_probe"},
            {"action": "unknown"},
            "ignored-action",
        ],
    }
    facade = {
        "operator_control_facade_id": "operator-control-facade-sparse",
        "operator_control_policy_id": "operator-control-policy-sparse",
        "operator_control_request": "not-a-request",
        "operator_control_admission": {
            "admission_status": "blocked",
            "current_process": "not-a-process",
            "next_supervisor_actions": ["ignored-action"],
        },
        "operator_control_command_preview": {
            "preview_status": "blocked",
            "supervisor_command_previews": ["ignored-preview"],
            "metadata": {"ready_for_dispatch": False},
        },
        "facade_status": "blocked",
    }

    projection = build_artifact_operation_retention_daemon_operator_control_projection(
        policy=policy,
        facade=facade,
        source_client=None,
        request_trace_id=None,
    )

    assert projection["projection_status"] == "READY"
    assert projection["source_status"]["source_kind"] == "provided"
    assert projection["source_status"]["base_url"] is None
    assert projection["summary"]["operator_attention_required"] is True
    assert projection["summary"]["restart_supported"] is False
    assert projection["summary"]["command_preview_count"] == 0
    assert projection["facade"]["operator_control_request"] == {}
    assert projection["facade"]["operator_control_admission"][
        "current_process"
    ] == {}
    assert projection["facade"]["operator_control_admission"][
        "next_supervisor_actions"
    ] == []
    assert projection["facade"]["operator_control_command_preview"][
        "supervisor_command_previews"
    ] == []
    assert artifact_operations._project_retention_scheduler_daemon_operator_control_policy(
        None
    ) == {}
    assert artifact_operations._project_retention_scheduler_daemon_operator_control_supported_action(
        None
    ) == {}
    assert artifact_operations._project_retention_scheduler_daemon_operator_control_facade(
        None
    ) == {}
    assert artifact_operations._project_retention_scheduler_daemon_operator_control_request(
        None
    ) == {}
    assert artifact_operations._project_retention_scheduler_daemon_operator_control_admission(
        None
    ) == {}
    assert artifact_operations._project_retention_scheduler_daemon_operator_control_command_preview(
        None
    ) == {}
    assert artifact_operations._project_retention_scheduler_daemon_operator_current_process(
        None
    ) == {}
    assert artifact_operations._project_retention_scheduler_daemon_operator_next_supervisor_action(
        None
    ) == {}
    assert artifact_operations._project_retention_scheduler_daemon_operator_supervisor_command_preview(
        None
    ) == {}
    assert artifact_operations._safe_operator_control_guardrails(None) == {}
    assert artifact_operations._safe_operator_control_metadata(None) == {}
    assert artifact_operations._project_retention_scheduler_daemon_operator_control_execution_worker_result(
        None
    ) == {}
    assert artifact_operations._safe_operator_control_execution_worker_metadata(
        None
    ) == {}
    assert artifact_operations._safe_operator_control_execution_worker_guardrails(
        None
    ) == {}
    assert artifact_operations._normalized_operator_control_execution_statuses(
        ["not-supported"]
    ) == []
    assert artifact_operations._normalized_daemon_supervisor_actions(
        ["not-supported"]
    ) == []
    assert artifact_operations._normalized_operator_control_execution_worker_status(
        "not-supported"
    ) is None


def test_artifact_retention_scheduler_daemon_operator_control_execution_projections_summarize_and_redact() -> (
    None
):
    collection = (
        artifact_retention_scheduler_daemon_operator_control_execution_collection_payload()
    )
    detail = (
        artifact_retention_scheduler_daemon_operator_control_execution_detail_payload()
    )
    collection_projection = build_artifact_operation_retention_daemon_operator_control_execution_collection_projection(
        collection=collection,
        source_client=artifact_client(),
        request_trace_id=TRACE_ID,
    )
    detail_projection = build_artifact_operation_retention_daemon_operator_control_execution_detail_projection(
        detail=detail,
        source_client=artifact_client(),
        request_trace_id=TRACE_ID,
    )
    degraded_projection = build_artifact_operation_retention_daemon_operator_control_execution_collection_projection(
        collection={"items": [], "filter": {}, "count": 0, "limit": 20},
        source_client=artifact_client(),
        source_errors=[
            AeArtifactOperationsError(
                error_code=(
                    "ag.ae_artifact_retention_daemon_operator_control_execution_source_failed"
                ),
                detail="AE operator-control execution source unavailable",
                status_code=503,
            )
        ],
    )

    assert collection_projection["projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_COLLECTION_PROJECTION_SCHEMA_VERSION
    )
    assert collection_projection["operation_type"] == (
        "ae_artifact_retention_scheduler_daemon_operator_control_executions"
    )
    assert collection_projection["filter"] == {
        "scheduler_id": "ae-artifact-retention-scheduler",
        "action": None,
        "execution_status": None,
        "idempotency_status": None,
    }
    assert collection_projection["summary"] == (
        summarize_artifact_retention_daemon_operator_control_execution_operations(
            collection_projection["items"]
        )
    )
    assert collection_projection["summary"][
        "operator_control_execution_state_count"
    ] == 2
    assert collection_projection["summary"]["admitted_count"] == 1
    assert collection_projection["summary"]["failed_count"] == 1
    assert collection_projection["summary"]["conflict_count"] == 1
    assert collection_projection["summary"][
        "operator_attention_required"
    ] is True
    assert collection_projection["summary"]["latest_observed_at"] == (
        "2026-09-04T02:05:00Z"
    )
    assert collection_projection["source_status"][
        "execution_collection_loaded"
    ] is True
    assert collection_projection["items"][0][
        "operator_control_execution_request_hash"
    ] == ("a" * 64)
    assert collection_projection["items"][0]["routes"]["ag_detail"].endswith(
        "/scheduler-daemon-operator-control-executions/"
        "operator-control-execution-state-0597"
    )
    assert "operator_control_execution_request" not in (
        collection_projection["items"][0]
    )
    assert "idempotency_key" not in collection_projection["items"][0]

    assert detail_projection["projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_DETAIL_PROJECTION_SCHEMA_VERSION
    )
    assert detail_projection["summary"] == (
        summarize_artifact_retention_daemon_operator_control_execution_detail(
            execution_state=detail_projection["execution_state"],
            transitions=detail_projection["transitions"],
        )
    )
    assert detail_projection["summary"]["transition_statuses"] == [
        "ADMITTED->EXECUTING"
    ]
    assert detail_projection["summary"]["latest_transitioned_at"] == (
        "2026-09-04T02:01:00Z"
    )
    assert detail_projection["source_status"]["execution_detail_loaded"] is True
    assert "operator_control_execution_state" not in detail_projection["transitions"][0]
    assert "operator_control_execution_request" not in detail_projection[
        "execution_state"
    ]
    assert "idempotency_key" not in detail_projection["execution_state"]
    assert degraded_projection["projection_status"] == "DEGRADED"
    assert degraded_projection["source_status"][
        "execution_collection_loaded"
    ] is False
    assert "SECRET_SYSTEM_PROMPT" not in str(collection_projection)
    assert "DATABASE_URL_SHOULD_NOT_LEAK" not in str(detail_projection)
    assert "/data/nex-platform" not in str(detail_projection)
    assert_artifact_operation_projection_redacted(collection_projection)
    assert_artifact_operation_projection_redacted(detail_projection)


def test_artifact_retention_scheduler_daemon_operator_control_execution_worker_projection_summarizes_and_redacts() -> (
    None
):
    worker_result = (
        artifact_retention_scheduler_daemon_operator_control_execution_worker_result_payload()
    )
    projection = build_artifact_operation_retention_daemon_operator_control_execution_worker_projection(
        worker_result=worker_result,
        source_client=artifact_client(),
        request_trace_id=TRACE_ID,
    )
    failed_projection = build_artifact_operation_retention_daemon_operator_control_execution_worker_projection(
        worker_result=(
            artifact_retention_scheduler_daemon_operator_control_execution_worker_result_payload(
                worker_status="FAILED",
                supervisor_result_statuses=["FAILED", "SUCCEEDED"],
            )
        ),
        source_client=artifact_client(),
    )
    degraded_projection = build_artifact_operation_retention_daemon_operator_control_execution_worker_projection(
        worker_result={},
        source_client=artifact_client(),
        source_errors=[
            AeArtifactOperationsError(
                error_code=(
                    "ag.ae_artifact_retention_daemon_operator_control_execution_worker_source_failed"
                ),
                detail="AE operator-control execution worker source unavailable",
                status_code=503,
            )
        ],
    )

    assert projection["projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_PROJECTION_SCHEMA_VERSION
    )
    assert projection["operation_type"] == (
        "ae_artifact_retention_scheduler_daemon_operator_control_execution_worker"
    )
    assert projection["operator_control_execution_state_id"] == (
        "operator-control-execution-state-0597"
    )
    assert projection["summary"] == (
        summarize_artifact_retention_daemon_operator_control_execution_worker_result(
            projection["worker_result"]
        )
    )
    assert projection["summary"]["worker_status"] == "SUCCEEDED"
    assert projection["summary"]["status_path"] == [
        "ADMITTED",
        "EXECUTING",
        "SUCCEEDED",
    ]
    assert projection["summary"]["operator_attention_required"] is False
    assert projection["worker_result"]["supervisor_actions"] == [
        "stop_daemon",
        "start_daemon",
    ]
    assert projection["worker_result"]["metadata"][
        "persistence_endpoint_included"
    ] is False
    assert projection["worker_result"]["guardrails"][
        "execution_payload_included"
    ] is False
    assert projection["worker_result"]["routes"]["ae_worker"].endswith(
        "/scheduler-daemon-operator-control-execution-workers"
    )
    assert "operator_control_execution_worker_command" not in (
        projection["worker_result"]
    )
    assert "operator_control_execution_worker_transition_plan" not in (
        projection["worker_result"]
    )
    assert "supervisor_results" not in projection["worker_result"]
    assert failed_projection["summary"]["worker_status"] == "FAILED"
    assert failed_projection["summary"]["failed_supervisor_count"] == 1
    assert failed_projection["summary"]["operator_attention_required"] is True
    assert degraded_projection["projection_status"] == "DEGRADED"
    assert degraded_projection["source_status"][
        "execution_worker_result_loaded"
    ] is False
    assert "SECRET_SYSTEM_PROMPT" not in str(projection)
    assert "DATABASE_URL_SHOULD_NOT_LEAK" not in str(projection)
    assert "database_url" not in str(projection)
    assert "/data/nex-platform" not in str(projection)
    assert_artifact_operation_projection_redacted(projection)
    assert_artifact_operation_projection_redacted(failed_projection)


def test_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_read_model_projections_summarize_and_redact() -> (
    None
):
    collection = (
        artifact_retention_scheduler_daemon_operator_control_execution_worker_result_collection_payload()
    )
    detail = (
        artifact_retention_scheduler_daemon_operator_control_execution_worker_result_detail_payload()
    )
    collection_projection = build_artifact_operation_retention_daemon_operator_control_execution_worker_result_collection_projection(
        collection=collection,
        source_client=artifact_client(),
        request_trace_id=TRACE_ID,
    )
    detail_projection = build_artifact_operation_retention_daemon_operator_control_execution_worker_result_detail_projection(
        detail=detail,
        source_client=artifact_client(),
        request_trace_id=TRACE_ID,
    )
    degraded_projection = build_artifact_operation_retention_daemon_operator_control_execution_worker_result_collection_projection(
        collection={"items": [], "filter": {}, "count": 0, "limit": 20},
        source_client=artifact_client(),
        source_errors=[
            AeArtifactOperationsError(
                error_code=(
                    "ag.ae_artifact_retention_daemon_operator_control_execution_worker_result_source_failed"
                ),
                detail="AE worker result read-model source unavailable",
                status_code=503,
            )
        ],
    )

    assert collection_projection["projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_COLLECTION_PROJECTION_SCHEMA_VERSION
    )
    assert collection_projection["operation_type"] == (
        "ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_results"
    )
    assert collection_projection["filter"] == {
        "scheduler_id": "ae-artifact-retention-scheduler",
        "action": None,
        "worker_status": None,
        "operator_control_execution_state_id": None,
        "operator_control_execution_request_id": None,
    }
    assert collection_projection["summary"] == (
        summarize_artifact_retention_daemon_operator_control_execution_worker_result_operations(
            collection_projection["items"]
        )
    )
    assert collection_projection["summary"][
        "operator_control_execution_worker_result_count"
    ] == 2
    assert collection_projection["summary"]["succeeded_count"] == 1
    assert collection_projection["summary"]["failed_count"] == 1
    assert collection_projection["summary"]["failed_supervisor_count"] == 1
    assert collection_projection["summary"][
        "operator_attention_required"
    ] is True
    assert collection_projection["summary"]["latest_observed_at"] == (
        "2026-09-04T02:05:00Z"
    )
    assert collection_projection["source_status"][
        "worker_result_collection_loaded"
    ] is True
    assert collection_projection["operator_guidance"]["read_model"] == (
        "ae_op_exec_worker_results"
    )
    assert collection_projection["items"][0]["hashes"] == {
        "operator_control_execution_worker_command_hash": "c" * 64,
        "operator_control_execution_worker_transition_plan_hash": "d" * 64,
        "supervisor_results_hash": "e" * 64,
        "worker_result_hash": "f" * 64,
    }
    assert collection_projection["items"][0]["routes"]["ag_detail"].endswith(
        "/scheduler-daemon-operator-control-execution-worker-results/"
        "operator-control-execution-worker-result-0607"
    )

    assert detail_projection["projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_DETAIL_PROJECTION_SCHEMA_VERSION
    )
    assert detail_projection["operator_control_execution_worker_result_id"] == (
        "operator-control-execution-worker-result-0607"
    )
    assert detail_projection["summary"]["worker_status"] == "SUCCEEDED"
    assert detail_projection["source_status"][
        "worker_result_detail_loaded"
    ] is True
    assert degraded_projection["projection_status"] == "DEGRADED"
    assert degraded_projection["source_status"][
        "worker_result_collection_loaded"
    ] is False
    assert "operator_control_execution_worker_command" not in (
        collection_projection["items"][0]
    )
    assert "operator_control_execution_worker_transition_plan" not in (
        detail_projection["worker_result"]
    )
    assert "supervisor_results" not in detail_projection["worker_result"]
    assert "DATABASE_URL_SHOULD_NOT_LEAK" not in str(collection_projection)
    assert "database_url" not in str(detail_projection)
    assert "/data/nex-platform" not in str(detail_projection)
    assert_artifact_operation_projection_redacted(collection_projection)
    assert_artifact_operation_projection_redacted(detail_projection)


def test_in_memory_artifact_operations_client_returns_operator_control_execution_read_models() -> (
    None
):
    source_client = artifact_client()

    collection = source_client.list_artifact_retention_scheduler_daemon_operator_control_executions(
        scheduler_id="ae-artifact-retention-scheduler",
        action="restart_daemon",
        execution_status="FAILED",
        idempotency_status="CONFLICT",
        limit=1,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    collection["items"][0]["execution_status"] = "SUCCEEDED"
    collection_again = source_client.list_artifact_retention_scheduler_daemon_operator_control_executions(
        scheduler_id="ae-artifact-retention-scheduler",
        action="restart_daemon",
        execution_status="FAILED",
        idempotency_status="CONFLICT",
        limit=1,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    fallback = source_client.list_artifact_retention_scheduler_daemon_operator_control_executions(
        scheduler_id="ae-artifact-retention-scheduler",
        action="stop_daemon",
        execution_status="NOOP",
        idempotency_status="REPLAYED",
        limit=5,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    detail = source_client.get_artifact_retention_scheduler_daemon_operator_control_execution_detail(
        "operator-control-execution-state-0597",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    missing = source_client.get_artifact_retention_scheduler_daemon_operator_control_execution_detail(
        "missing",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert collection_again["count"] == 1
    assert collection_again["items"][0]["execution_status"] == "FAILED"
    assert fallback["count"] == 0
    assert fallback["filter"] == {
        "scheduler_id": "ae-artifact-retention-scheduler",
        "action": "stop_daemon",
        "execution_status": "NOOP",
        "idempotency_status": "REPLAYED",
    }
    assert detail is not None
    assert detail["operator_control_execution_state_id"] == (
        "operator-control-execution-state-0597"
    )
    assert missing is None


def test_in_memory_artifact_operations_client_returns_operator_control_execution_worker_result() -> (
    None
):
    source_client = artifact_client()

    worker_result = source_client.run_artifact_retention_scheduler_daemon_operator_control_execution_worker(
        operator_control_execution_state_id="operator-control-execution-state-0597",
        operator_control_execution_state=None,
        checked_at=None,
        worker_observed_at=None,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    worker_result["worker_status"] = "FAILED"
    worker_result_again = source_client.run_artifact_retention_scheduler_daemon_operator_control_execution_worker(
        operator_control_execution_state_id="operator-control-execution-state-0597",
        operator_control_execution_state=None,
        checked_at=None,
        worker_observed_at=None,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    fallback = source_client.run_artifact_retention_scheduler_daemon_operator_control_execution_worker(
        operator_control_execution_state_id=None,
        operator_control_execution_state=artifact_retention_scheduler_daemon_operator_control_execution_state_payload(
            state_id="missing-worker-state"
        ),
        checked_at="2026-09-04T02:03:00Z",
        worker_observed_at=None,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert worker_result_again["worker_status"] == "SUCCEEDED"
    assert worker_result_again["operator_control_execution_worker_result_id"] == (
        "operator-control-execution-worker-result-0607"
    )
    assert fallback["worker_status"] == "BLOCKED"
    assert fallback["operator_control_execution_state_id"] == "missing-worker-state"
    assert fallback["metadata"]["decision_reason"] == (
        "operator_control_execution_worker_result_missing"
    )


def test_in_memory_artifact_operations_client_returns_operator_control_execution_worker_result_read_models() -> (
    None
):
    source_client = artifact_client()

    collection = source_client.list_artifact_retention_scheduler_daemon_operator_control_execution_worker_results(
        scheduler_id="ae-artifact-retention-scheduler",
        action="restart_daemon",
        worker_status="FAILED",
        operator_control_execution_state_id="operator-control-execution-state-0597",
        operator_control_execution_request_id=(
            "operator-control-execution-state-0597:execution-request"
        ),
        limit=1,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    collection["items"][0]["worker_status"] = "SUCCEEDED"
    collection_again = source_client.list_artifact_retention_scheduler_daemon_operator_control_execution_worker_results(
        scheduler_id="ae-artifact-retention-scheduler",
        action="restart_daemon",
        worker_status="FAILED",
        operator_control_execution_state_id="operator-control-execution-state-0597",
        operator_control_execution_request_id=(
            "operator-control-execution-state-0597:execution-request"
        ),
        limit=1,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    fallback = source_client.list_artifact_retention_scheduler_daemon_operator_control_execution_worker_results(
        scheduler_id="ae-artifact-retention-scheduler",
        action="stop_daemon",
        worker_status="BLOCKED",
        operator_control_execution_state_id="missing-state",
        operator_control_execution_request_id="missing-request",
        limit=5,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    detail = source_client.get_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_detail(
        "operator-control-execution-worker-result-0607",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    missing = source_client.get_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_detail(
        "missing",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert collection_again["count"] == 1
    assert collection_again["items"][0]["worker_status"] == "FAILED"
    assert fallback["count"] == 0
    assert fallback["filter"] == {
        "scheduler_id": "ae-artifact-retention-scheduler",
        "action": "stop_daemon",
        "worker_status": "BLOCKED",
        "operator_control_execution_state_id": "missing-state",
        "operator_control_execution_request_id": "missing-request",
    }
    assert fallback["metadata"]["read_model"] == "ae_op_exec_worker_results"
    assert detail is not None
    assert detail["operator_control_execution_worker_result_id"] == (
        "operator-control-execution-worker-result-0607"
    )
    assert missing is None


def test_http_artifact_operations_client_requests_operator_control_execution_read_models(
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
        if url.endswith(
            "/api/v1/artifact-retention/"
            "scheduler-daemon-operator-control-executions"
        ):
            return FakeHttpResponse(
                200,
                artifact_retention_scheduler_daemon_operator_control_execution_collection_payload(),
            )
        if url.endswith(
            "/api/v1/artifact-retention/"
            "scheduler-daemon-operator-control-executions/"
            "operator-control-execution-state-0597"
        ):
            return FakeHttpResponse(
                200,
                artifact_retention_scheduler_daemon_operator_control_execution_detail_payload(),
            )
        return FakeHttpResponse(404, {})

    monkeypatch.setattr(artifact_operations.httpx, "get", fake_get)
    client = HttpAeArtifactOperationsClient(
        base_url="http://ae.example.local/",
        service_token="token-0597",
        timeout_seconds=13.0,
    )

    collection = client.list_artifact_retention_scheduler_daemon_operator_control_executions(
        scheduler_id="ae-artifact-retention-scheduler",
        action="restart_daemon",
        execution_status="FAILED",
        idempotency_status="CONFLICT",
        limit=10,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    detail = client.get_artifact_retention_scheduler_daemon_operator_control_execution_detail(
        "operator-control-execution-state-0597",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    missing = client.get_artifact_retention_scheduler_daemon_operator_control_execution_detail(
        "missing",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert collection["count"] == 2
    assert detail is not None
    assert detail["operator_control_execution_state_id"] == (
        "operator-control-execution-state-0597"
    )
    assert missing is None
    assert calls[0]["url"] == (
        "http://ae.example.local/api/v1/artifact-retention/"
        "scheduler-daemon-operator-control-executions"
    )
    assert calls[0]["headers"]["Authorization"] == "Bearer token-0597"
    assert calls[0]["params"] == {
        "limit": "10",
        "scheduler_id": "ae-artifact-retention-scheduler",
        "action": "restart_daemon",
        "execution_status": "FAILED",
        "idempotency_status": "CONFLICT",
    }
    assert calls[0]["timeout"] == 13.0
    assert calls[1]["url"] == (
        "http://ae.example.local/api/v1/artifact-retention/"
        "scheduler-daemon-operator-control-executions/"
        "operator-control-execution-state-0597"
    )
    assert calls[1]["params"] == {}
    assert calls[2]["url"].endswith(
        "/api/v1/artifact-retention/"
        "scheduler-daemon-operator-control-executions/missing"
    )


def test_http_artifact_operations_client_requests_operator_control_execution_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_post(
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
        timeout: float,
    ) -> FakeHttpResponse:
        calls.append(
            {
                "url": url,
                "headers": headers,
                "json": json,
                "timeout": timeout,
            }
        )
        return FakeHttpResponse(
            200,
            artifact_retention_scheduler_daemon_operator_control_execution_worker_result_payload(),
        )

    monkeypatch.setattr(artifact_operations.httpx, "post", fake_post)
    client = HttpAeArtifactOperationsClient(
        base_url="http://ae.example.local/",
        service_token="token-0607",
        timeout_seconds=17.0,
    )

    worker_result = client.run_artifact_retention_scheduler_daemon_operator_control_execution_worker(
        operator_control_execution_state_id="operator-control-execution-state-0597",
        operator_control_execution_state=None,
        checked_at="2026-09-04T02:03:00Z",
        worker_observed_at="2026-09-04T02:04:00Z",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert worker_result["operator_control_execution_worker_result_id"] == (
        "operator-control-execution-worker-result-0607"
    )
    assert calls == [
        {
            "url": (
                "http://ae.example.local/api/v1/artifact-retention/"
                "scheduler-daemon-operator-control-execution-workers"
            ),
            "headers": {
                "Authorization": "Bearer token-0607",
                "X-Request-ID": REQUEST_ID,
                "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
                "X-Service-ID": "nex-ag",
            },
            "json": {
                "operator_control_execution_state_id": (
                    "operator-control-execution-state-0597"
                ),
                "checked_at": "2026-09-04T02:03:00Z",
                "worker_observed_at": "2026-09-04T02:04:00Z",
            },
            "timeout": 17.0,
        }
    ]


def test_http_artifact_operations_client_requests_operator_control_execution_worker_result_read_models(
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
        if url.endswith(
            "/api/v1/artifact-retention/"
            "scheduler-daemon-operator-control-execution-worker-results"
        ):
            return FakeHttpResponse(
                200,
                artifact_retention_scheduler_daemon_operator_control_execution_worker_result_collection_payload(),
            )
        if url.endswith(
            "/api/v1/artifact-retention/"
            "scheduler-daemon-operator-control-execution-worker-results/"
            "operator-control-execution-worker-result-0607"
        ):
            return FakeHttpResponse(
                200,
                artifact_retention_scheduler_daemon_operator_control_execution_worker_result_detail_payload(),
            )
        return FakeHttpResponse(404, {})

    monkeypatch.setattr(artifact_operations.httpx, "get", fake_get)
    client = HttpAeArtifactOperationsClient(
        base_url="http://ae.example.local/",
        service_token="token-0616",
        timeout_seconds=19.0,
    )

    collection = client.list_artifact_retention_scheduler_daemon_operator_control_execution_worker_results(
        scheduler_id="ae-artifact-retention-scheduler",
        action="restart_daemon",
        worker_status="FAILED",
        operator_control_execution_state_id="operator-control-execution-state-0597",
        operator_control_execution_request_id=(
            "operator-control-execution-state-0597:execution-request"
        ),
        limit=10,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    detail = client.get_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_detail(
        "operator-control-execution-worker-result-0607",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    missing = client.get_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_detail(
        "missing",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert collection["count"] == 2
    assert detail is not None
    assert detail["operator_control_execution_worker_result_id"] == (
        "operator-control-execution-worker-result-0607"
    )
    assert missing is None
    assert calls[0]["url"] == (
        "http://ae.example.local/api/v1/artifact-retention/"
        "scheduler-daemon-operator-control-execution-worker-results"
    )
    assert calls[0]["headers"]["Authorization"] == "Bearer token-0616"
    assert calls[0]["params"] == {
        "limit": "10",
        "scheduler_id": "ae-artifact-retention-scheduler",
        "action": "restart_daemon",
        "worker_status": "FAILED",
        "operator_control_execution_state_id": (
            "operator-control-execution-state-0597"
        ),
        "operator_control_execution_request_id": (
            "operator-control-execution-state-0597:execution-request"
        ),
    }
    assert calls[0]["timeout"] == 19.0
    assert calls[1]["url"] == (
        "http://ae.example.local/api/v1/artifact-retention/"
        "scheduler-daemon-operator-control-execution-worker-results/"
        "operator-control-execution-worker-result-0607"
    )
    assert calls[1]["params"] == {}
    assert calls[2]["url"].endswith(
        "/api/v1/artifact-retention/"
        "scheduler-daemon-operator-control-execution-worker-results/missing"
    )


def test_artifact_retention_automation_operator_control_current_process_selection() -> (
    None
):
    collection = {
        "items": [
            {
                "daemon_supervised_process_record_id": "stale-record",
                "daemon_supervised_process_id": "stale-process",
                "daemon_supervisor_command_id": "stale-command",
                "process_status": "STALE",
                "process_running": True,
                "process_id": 5881,
                "host_id": "worker-stale",
                "observed_at": "2026-09-03T02:00:00Z",
            },
            {
                "daemon_supervised_process_record_id": "running-record",
                "daemon_supervised_process_id": "running-process",
                "daemon_supervisor_command_id": "running-command",
                "process_status": "RUNNING",
                "process_running": True,
                "process_id": 5882,
                "host_id": "worker-running",
                "observed_at": "2026-09-03T02:01:00Z",
            },
        ]
    }
    fallback_collection = {
        "items": [
            {
                "daemon_supervised_process_record_id": "unknown-record",
                "process_status": "UNKNOWN",
                "process_running": False,
            }
        ]
    }

    selected = (
        artifact_operations._artifact_retention_automation_operator_control_current_process(
            collection
        )
    )
    fallback_selected = (
        artifact_operations._artifact_retention_automation_operator_control_current_process(
            fallback_collection
        )
    )

    assert selected == {
        "process_source": "scheduler_daemon_process_snapshots",
        "process_status": "RUNNING",
        "process_running": True,
        "daemon_supervised_process_id": "running-process",
        "daemon_supervisor_command_id": "running-command",
        "process_id": 5882,
        "host_id": "worker-running",
        "observed_at": "2026-09-03T02:01:00Z",
    }
    assert fallback_selected["daemon_supervised_process_id"] == "unknown-record"
    assert fallback_selected["process_status"] is None
    assert (
        artifact_operations._artifact_retention_automation_operator_control_current_process(
            []
        )
        is None
    )
    assert (
        artifact_operations._artifact_retention_automation_operator_control_current_process(
            {"items": []}
        )
        is None
    )


def test_in_memory_artifact_operations_client_returns_supervised_process_read_models() -> (
    None
):
    source_client = artifact_client()

    collection = (
        source_client.list_artifact_retention_scheduler_daemon_process_snapshots(
            scheduler_id="ae-artifact-retention-scheduler",
            action="start_daemon",
            process_status="RUNNING",
            limit=1,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    )
    collection["items"][0]["process_status"] = "FAILED"
    collection_again = (
        source_client.list_artifact_retention_scheduler_daemon_process_snapshots(
            scheduler_id="ae-artifact-retention-scheduler",
            action="start_daemon",
            process_status="RUNNING",
            limit=1,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    )
    fallback = (
        source_client.list_artifact_retention_scheduler_daemon_process_snapshots(
            scheduler_id="ae-artifact-retention-scheduler",
            action="stop_daemon",
            process_status="STOPPED",
            limit=5,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    )
    detail = (
        source_client.get_artifact_retention_scheduler_daemon_process_snapshot_detail(
            "daemon-supervised-process-record-0576",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    )
    missing = (
        source_client.get_artifact_retention_scheduler_daemon_process_snapshot_detail(
            "missing",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    )

    assert collection_again["count"] == 1
    assert collection_again["items"][0]["process_status"] == "RUNNING"
    assert fallback["count"] == 0
    assert fallback["filter"] == {
        "scheduler_id": "ae-artifact-retention-scheduler",
        "action": "stop_daemon",
        "process_status": "STOPPED",
    }
    assert detail is not None
    assert detail["daemon_supervised_process_record_id"] == (
        "daemon-supervised-process-record-0576"
    )
    assert missing is None


def test_in_memory_artifact_operations_client_returns_operator_control_facade() -> (
    None
):
    policy = artifact_retention_scheduler_daemon_operator_control_policy_payload()
    facade = artifact_retention_scheduler_daemon_operator_control_facade_payload()
    preview_key = (
        artifact_operations._artifact_retention_scheduler_daemon_operator_control_preview_cache_key(
            action="restart-daemon",
            idempotency_key="operator-control-idem-0587",
            checked_at="2026-09-03T02:00:00Z",
        )
    )
    source_client = InMemoryAeArtifactOperationsClient(
        artifact_retention_scheduler_daemon_operator_control_policy=policy,
        artifact_retention_scheduler_daemon_operator_control_previews={
            preview_key: facade
        },
    )

    cached_policy = (
        source_client.get_artifact_retention_scheduler_daemon_operator_control_policy(
            checked_at="2026-09-03T02:00:00Z",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    )
    cached_facade = (
        source_client.preview_artifact_retention_scheduler_daemon_operator_control(
            action="restart-daemon",
            operator_subject={"actor_type": "operator", "actor_id": "ag"},
            idempotency_key="operator-control-idem-0587",
            reason="preview restart",
            requested_at="2026-09-03T02:00:00Z",
            checked_at="2026-09-03T02:00:00Z",
            profile="test",
            enabled=True,
            explicit_opt_in=True,
            max_cycles=2,
            run_worker=False,
            approval={"approved": True},
            current_process={"process_status": "RUNNING", "process_id": 5870},
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    )
    fallback_facade = (
        InMemoryAeArtifactOperationsClient().preview_artifact_retention_scheduler_daemon_operator_control(
            action="restart_daemon",
            operator_subject={"actor_type": "operator", "actor_id": "ag"},
            idempotency_key="fallback-operator-control-idem",
            reason="fallback restart preview",
            requested_at=None,
            checked_at=None,
            profile="test",
            enabled=True,
            explicit_opt_in=True,
            max_cycles=2,
            run_worker=True,
            approval={"approved": True},
            current_process=None,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    )
    cached_policy["operator_control_policy_id"] = "mutated"
    cached_facade["operator_control_facade_id"] = "mutated"

    assert (
        source_client.artifact_retention_scheduler_daemon_operator_control_policy[
            "operator_control_policy_id"
        ]
        == policy["operator_control_policy_id"]
    )
    assert (
        source_client.artifact_retention_scheduler_daemon_operator_control_previews[
            preview_key
        ]["operator_control_facade_id"]
        == facade["operator_control_facade_id"]
    )
    assert fallback_facade["action"] == "restart_daemon"
    assert fallback_facade["facade_status"] == "READY"
    assert fallback_facade["operator_control_command_preview"]["metadata"][
        "supervisor_actions"
    ] == ["stop_daemon", "start_daemon"]
    assert (
        artifact_operations._normalized_daemon_operator_control_action(
            "restart-daemon"
        )
        == "restart_daemon"
    )
    assert (
        artifact_operations._normalized_daemon_operator_control_action("bad")
        is None
    )
    assert artifact_operations._normalized_daemon_operator_control_action(None) is None
    assert (
        artifact_operations._normalized_operator_control_admission_status("ready")
        == "READY"
    )
    assert (
        artifact_operations._normalized_operator_control_admission_status("bad")
        is None
    )


def test_in_memory_operator_control_facade_covers_admission_matrix() -> None:
    source_client = InMemoryAeArtifactOperationsClient()

    def preview(
        action: str,
        *,
        current_process: dict[str, Any] | None,
        explicit_opt_in: bool = False,
    ) -> dict[str, Any]:
        return source_client.preview_artifact_retention_scheduler_daemon_operator_control(
            action=action,
            operator_subject={"actor_type": "operator", "actor_id": "ag"},
            idempotency_key=f"operator-control-{action}",
            reason=f"{action} preview",
            requested_at=None,
            checked_at="2026-09-03T02:00:00Z",
            profile="test",
            enabled=True,
            explicit_opt_in=explicit_opt_in,
            max_cycles=3,
            run_worker=True,
            approval=None,
            current_process=current_process,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    status_probe = preview("status_probe", current_process=None)
    start_ready = preview(
        "start_daemon",
        current_process=None,
        explicit_opt_in=True,
    )
    start_noop = preview(
        "start_daemon",
        current_process={"process_status": "RUNNING", "process_id": 5871},
    )
    start_blocked = preview(
        "start_daemon",
        current_process={"process_status": "STALE", "process_id": 5872},
    )
    stop_ready = preview("stop_daemon", current_process=None)
    stop_noop = preview(
        "stop_daemon",
        current_process={"process_status": "MISSING"},
    )
    stop_blocked = preview(
        "stop_daemon",
        current_process={"process_status": "FAILED", "process_id": 5873},
    )
    restart_ready = preview(
        "restart_daemon",
        current_process={"process_status": "STALE", "process_id": 5874},
        explicit_opt_in=True,
    )
    restart_blocked = preview(
        "restart_daemon",
        current_process={"process_status": "STOPPED"},
    )

    assert status_probe["facade_status"] == "READY"
    assert status_probe["operator_control_admission"]["decision_reason"] == (
        "status_probe_allowed"
    )
    assert status_probe["operator_control_command_preview"]["metadata"][
        "status_probe_preview_count"
    ] == 1
    assert start_ready["facade_status"] == "READY"
    assert start_ready["operator_control_admission"]["decision_reason"] == (
        "start_allowed_no_running_process"
    )
    assert start_ready["operator_control_command_preview"][
        "supervisor_command_previews"
    ][0]["supervisor_command"]["command"]["explicit_opt_in"] is True
    assert start_noop["facade_status"] == "NOOP"
    assert start_noop["operator_control_command_preview"]["metadata"][
        "command_preview_count"
    ] == 0
    assert start_blocked["facade_status"] == "BLOCKED"
    assert stop_ready["facade_status"] == "READY"
    assert stop_ready["operator_control_admission"]["current_process"][
        "process_status"
    ] == "RUNNING"
    assert stop_noop["facade_status"] == "NOOP"
    assert stop_noop["operator_control_admission"]["decision_reason"] == (
        "daemon_not_running"
    )
    assert stop_blocked["facade_status"] == "BLOCKED"
    assert restart_ready["facade_status"] == "READY"
    assert restart_ready["operator_control_command_preview"]["metadata"][
        "supervisor_actions"
    ] == ["stop_daemon", "start_daemon"]
    assert restart_blocked["facade_status"] == "BLOCKED"
    assert artifact_operations._memory_operator_control_admission_decision(
        action="unknown",
        process_status="RUNNING",
    ) == ("BLOCKED", "operator_control_action_invalid")


def test_artifact_retention_scheduler_daemon_supervised_process_routes_return_read_models() -> (
    None
):
    client = build_app(artifact_client())

    collection_response = client.get(
        (
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-process-snapshots"
        ),
        params={
            "service_id": "nex-ae-api",
            "scheduler_id": "ae-artifact-retention-scheduler",
            "action": "start-daemon",
            "process_status": "running",
            "limit": "1",
        },
        headers=auth_headers(),
    )
    detail_response = client.get(
        (
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-process-snapshots/"
            "daemon-supervised-process-record-0576"
        ),
        headers=auth_headers(),
    )

    assert collection_response.status_code == 200
    collection = collection_response.json()
    assert collection["projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_RETENTION_DAEMON_SUPERVISED_PROCESS_COLLECTION_PROJECTION_SCHEMA_VERSION
    )
    assert collection["filter"] == {
        "scheduler_id": "ae-artifact-retention-scheduler",
        "action": "start_daemon",
        "process_status": "RUNNING",
    }
    assert collection["limit"] == 1
    assert collection["summary"]["running_count"] == 1
    assert collection["items"][0]["routes"]["ag_detail"].endswith(
        "/scheduler-daemon-process-snapshots/"
        "daemon-supervised-process-record-0576"
    )
    assert collection["operator_guidance"][
        "ag_direct_daemon_process_control_allowed"
    ] is False
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_RETENTION_DAEMON_SUPERVISED_PROCESS_DETAIL_PROJECTION_SCHEMA_VERSION
    )
    assert detail["daemon_supervised_process_record_id"] == (
        "daemon-supervised-process-record-0576"
    )
    assert detail["supervised_process_event_count"] == 2
    assert detail["request_trace_id"] == TRACE_ID
    assert "database_url" not in str(collection)
    assert "/data/nex-platform" not in str(detail)


def test_artifact_retention_scheduler_daemon_supervised_process_route_guardrails() -> (
    None
):
    client = build_app(artifact_client())

    unauthorized = client.get(
        (
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-process-snapshots"
        ),
    )
    invalid_service = client.get(
        (
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-process-snapshots"
        ),
        params={"service_id": "nex-cx"},
        headers=auth_headers(),
    )
    invalid_action = client.get(
        (
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-process-snapshots"
        ),
        params={"action": "manual_tick_once"},
        headers=auth_headers(),
    )
    invalid_status = client.get(
        (
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-process-snapshots"
        ),
        params={"process_status": "SUCCEEDED"},
        headers=auth_headers(),
    )
    invalid_limit = client.get(
        (
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-process-snapshots"
        ),
        params={"limit": "101"},
        headers=auth_headers(),
    )
    missing_detail = client.get(
        (
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-process-snapshots/missing"
        ),
        headers=auth_headers(),
    )

    class BrokenDaemonProcessClient(InMemoryAeArtifactOperationsClient):
        def list_artifact_retention_scheduler_daemon_process_snapshots(
            self,
            *args: Any,
            **kwargs: Any,
        ) -> dict[str, Any]:
            raise AeArtifactOperationsError(
                error_code=(
                    "ag.ae_artifact_retention_daemon_process_source_failed"
                ),
                detail="AE scheduler daemon process source unavailable",
                status_code=503,
            )

    source_failed = build_app(BrokenDaemonProcessClient()).get(
        (
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-process-snapshots"
        ),
        headers=auth_headers(),
    )

    assert unauthorized.status_code == 401
    assert invalid_service.status_code == 400
    assert invalid_action.status_code == 400
    assert invalid_action.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_process_action_invalid"
    )
    assert invalid_status.status_code == 400
    assert invalid_status.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_process_status_invalid"
    )
    assert invalid_limit.status_code == 400
    assert invalid_limit.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_process_limit_invalid"
    )
    assert missing_detail.status_code == 404
    assert missing_detail.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_process_not_found"
    )
    assert source_failed.status_code == 503
    assert source_failed.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_process_source_failed"
    )


def test_artifact_retention_scheduler_daemon_operator_control_routes_return_projection() -> (
    None
):
    class CapturingOperatorControlClient(InMemoryAeArtifactOperationsClient):
        def __init__(self) -> None:
            super().__init__(
                artifact_retention_scheduler_daemon_operator_control_policy=(
                    artifact_retention_scheduler_daemon_operator_control_policy_payload()
                ),
                artifact_retention_scheduler_daemon_operator_control_previews={
                    artifact_operations._artifact_retention_scheduler_daemon_operator_control_preview_cache_key(
                        action="restart_daemon",
                        idempotency_key="header-operator-control-idem-0587",
                        checked_at="2026-09-03T02:00:00Z",
                    ): artifact_retention_scheduler_daemon_operator_control_facade_payload()
                },
            )
            self.captured_preview: dict[str, Any] | None = None

        def preview_artifact_retention_scheduler_daemon_operator_control(
            self,
            **kwargs: Any,
        ) -> dict[str, Any]:
            self.captured_preview = dict(kwargs)
            return super().preview_artifact_retention_scheduler_daemon_operator_control(
                **kwargs
            )

    source_client = CapturingOperatorControlClient()
    client = build_app(source_client)

    policy_response = client.get(
        (
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-operator-control-policy"
        ),
        params={
            "service_id": "nex-ae-api",
            "checked_at": "2026-09-03T02:00:00Z",
        },
        headers=auth_headers(),
    )
    preview_response = client.post(
        (
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-operator-control-preview"
        ),
        json={
            "action": "restart-daemon",
            "requested_by": {
                "actor_type": "operator",
                "actor_id": "ag-retention-operator",
                "tenant_id": "tenant-0409",
                "workspace_id": "workspace-0409",
                "database_url": "DATABASE_URL_SHOULD_NOT_LEAK",
            },
            "reason": "restart preview",
            "requested_at": "2026-09-03T02:00:00Z",
            "checked_at": "2026-09-03T02:00:00Z",
            "profile": "test",
            "enabled": True,
            "explicit_opt_in": True,
            "max_cycles": "2",
            "run_worker": False,
            "approval": {
                "approved": True,
                "approved_by": "ag-retention-lead",
                "approved_at": "2026-09-03T01:59:00Z",
                "approval_reason": "maintenance",
            },
            "current_process": {
                "process_source": "read_model",
                "process_status": "RUNNING",
                "process_running": True,
                "daemon_supervised_process_id": "daemon-supervised-process-0587",
                "daemon_supervisor_command_id": "daemon-supervisor-command-0587",
                "process_id": 5870,
                "host_id": "ae-worker-0587",
                "observed_at": "2026-09-03T02:00:00Z",
            },
            "idempotency_key": "body-operator-control-idem-0587",
        },
        headers={
            **auth_headers(),
            "Idempotency-Key": "header-operator-control-idem-0587",
        },
    )

    assert policy_response.status_code == 200
    policy_payload = policy_response.json()
    assert policy_payload["projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_PROJECTION_SCHEMA_VERSION
    )
    assert policy_payload["summary"]["policy_loaded"] is True
    assert policy_payload["summary"]["facade_loaded"] is False
    assert policy_payload["source_status"]["operator_control_policy_loaded"] is True
    assert policy_payload["operator_guidance"][
        "ag_direct_process_control_allowed"
    ] is False

    assert preview_response.status_code == 200
    preview_payload = preview_response.json()
    assert preview_payload["projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_PROJECTION_SCHEMA_VERSION
    )
    assert preview_payload["summary"]["action"] == "restart_daemon"
    assert preview_payload["summary"]["facade_status"] == "READY"
    assert preview_payload["summary"]["command_preview_count"] == 2
    assert preview_payload["summary"]["supervisor_actions"] == [
        "stop_daemon",
        "start_daemon",
    ]
    assert preview_payload["source_status"]["operator_control_facade_loaded"] is True
    assert preview_payload["request_trace_id"] == TRACE_ID
    assert source_client.captured_preview is not None
    assert source_client.captured_preview["idempotency_key"] == (
        "header-operator-control-idem-0587"
    )
    assert source_client.captured_preview["action"] == "restart_daemon"
    assert source_client.captured_preview["max_cycles"] == 2
    assert source_client.captured_preview["operator_subject"] == {
        "actor_type": "operator",
        "actor_id": "ag-retention-operator",
        "tenant_id": "tenant-0409",
        "workspace_id": "workspace-0409",
    }
    assert "DATABASE_URL_SHOULD_NOT_LEAK" not in str(preview_payload)
    assert "body-operator-control-idem-0587" not in str(preview_payload)
    assert "header-operator-control-idem-0587" not in str(preview_payload)


def test_artifact_retention_scheduler_daemon_operator_control_route_defaults_payload_idempotency() -> (
    None
):
    class CapturingOperatorControlClient(InMemoryAeArtifactOperationsClient):
        def __init__(self) -> None:
            super().__init__()
            self.captured_preview: dict[str, Any] | None = None

        def preview_artifact_retention_scheduler_daemon_operator_control(
            self,
            **kwargs: Any,
        ) -> dict[str, Any]:
            self.captured_preview = dict(kwargs)
            return super().preview_artifact_retention_scheduler_daemon_operator_control(
                **kwargs
            )

    source_client = CapturingOperatorControlClient()
    client = build_app(source_client)

    unauthorized_post = client.post(
        (
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-operator-control-preview"
        ),
        json={"reason": "probe", "idempotency_key": "payload-idem-0587"},
    )
    invalid_service_post = client.post(
        (
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-operator-control-preview"
        ),
        params={"service_id": "nex-cx"},
        json={"reason": "probe", "idempotency_key": "payload-idem-0587"},
        headers=auth_headers(),
    )
    preview_response = client.post(
        (
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-operator-control-preview"
        ),
        json={
            "reason": "probe",
            "idempotency_key": "payload-idem-0587",
            "enabled": None,
            "explicit_opt_in": None,
        },
        headers=auth_headers(),
    )

    assert unauthorized_post.status_code == 401
    assert invalid_service_post.status_code == 400
    assert preview_response.status_code == 200
    assert source_client.captured_preview is not None
    assert source_client.captured_preview["action"] == "status_probe"
    assert source_client.captured_preview["idempotency_key"] == "payload-idem-0587"
    assert source_client.captured_preview["enabled"] is False
    assert source_client.captured_preview["explicit_opt_in"] is False
    assert source_client.captured_preview["run_worker"] is False
    assert source_client.captured_preview["max_cycles"] == 1
    assert source_client.captured_preview["profile"] == "test"
    assert source_client.captured_preview["approval"] is None
    assert source_client.captured_preview["current_process"] is None
    assert source_client.captured_preview["operator_subject"]["actor_id"] == (
        "nex-ag-artifact-retention-operator"
    )
    assert "payload-idem-0587" not in str(preview_response.json())


def test_artifact_retention_scheduler_daemon_operator_control_route_guardrails() -> (
    None
):
    client = build_app(artifact_client())

    unauthorized = client.get(
        (
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-operator-control-policy"
        ),
    )
    invalid_service = client.get(
        (
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-operator-control-policy"
        ),
        params={"service_id": "nex-cx"},
        headers=auth_headers(),
    )
    missing_reason = client.post(
        (
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-operator-control-preview"
        ),
        json={"action": "status_probe", "idempotency_key": "idem"},
        headers=auth_headers(),
    )
    missing_idempotency_key = client.post(
        (
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-operator-control-preview"
        ),
        json={"action": "status_probe", "reason": "probe"},
        headers=auth_headers(),
    )
    invalid_action = client.post(
        (
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-operator-control-preview"
        ),
        json={
            "action": "manual_tick_once",
            "reason": "probe",
            "idempotency_key": "idem",
        },
        headers=auth_headers(),
    )
    invalid_bool = client.post(
        (
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-operator-control-preview"
        ),
        json={
            "action": "status_probe",
            "reason": "probe",
            "idempotency_key": "idem",
            "run_worker": "yes",
        },
        headers=auth_headers(),
    )
    invalid_enabled = client.post(
        (
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-operator-control-preview"
        ),
        json={
            "action": "status_probe",
            "reason": "probe",
            "idempotency_key": "idem",
            "enabled": "yes",
        },
        headers=auth_headers(),
    )
    invalid_explicit_opt_in = client.post(
        (
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-operator-control-preview"
        ),
        json={
            "action": "status_probe",
            "reason": "probe",
            "idempotency_key": "idem",
            "explicit_opt_in": "yes",
        },
        headers=auth_headers(),
    )
    invalid_cycles = client.post(
        (
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-operator-control-preview"
        ),
        json={
            "action": "status_probe",
            "reason": "probe",
            "idempotency_key": "idem",
            "max_cycles": "101",
        },
        headers=auth_headers(),
    )
    invalid_current_process = client.post(
        (
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-operator-control-preview"
        ),
        json={
            "action": "status_probe",
            "reason": "probe",
            "idempotency_key": "idem",
            "current_process": "bad",
        },
        headers=auth_headers(),
    )

    class BrokenOperatorControlClient(InMemoryAeArtifactOperationsClient):
        def get_artifact_retention_scheduler_daemon_operator_control_policy(
            self,
            *args: Any,
            **kwargs: Any,
        ) -> dict[str, Any]:
            raise AeArtifactOperationsError(
                error_code=(
                    "ag.ae_artifact_retention_daemon_operator_control_source_failed"
                ),
                detail="AE operator-control source unavailable",
                status_code=503,
            )

        def preview_artifact_retention_scheduler_daemon_operator_control(
            self,
            *args: Any,
            **kwargs: Any,
        ) -> dict[str, Any]:
            raise AeArtifactOperationsError(
                error_code=(
                    "ag.ae_artifact_retention_daemon_operator_control_preview_failed"
                ),
                detail="AE operator-control preview unavailable",
                status_code=503,
            )

    source_policy_failed = build_app(BrokenOperatorControlClient()).get(
        (
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-operator-control-policy"
        ),
        headers=auth_headers(),
    )
    source_preview_failed = build_app(BrokenOperatorControlClient()).post(
        (
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-operator-control-preview"
        ),
        json={"action": "status_probe", "reason": "probe", "idempotency_key": "idem"},
        headers=auth_headers(),
    )

    assert unauthorized.status_code == 401
    assert invalid_service.status_code == 400
    assert missing_reason.status_code == 400
    assert missing_reason.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_operator_control_reason_missing"
    )
    assert missing_idempotency_key.status_code == 400
    assert missing_idempotency_key.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_operator_control_idempotency_key_missing"
    )
    assert invalid_action.status_code == 400
    assert invalid_action.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_operator_control_action_invalid"
    )
    assert invalid_bool.status_code == 400
    assert invalid_bool.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_operator_control_boolean_invalid"
    )
    assert invalid_enabled.status_code == 400
    assert invalid_enabled.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_operator_control_boolean_invalid"
    )
    assert invalid_explicit_opt_in.status_code == 400
    assert invalid_explicit_opt_in.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_operator_control_boolean_invalid"
    )
    assert invalid_cycles.status_code == 400
    assert invalid_cycles.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_operator_control_max_cycles_invalid"
    )
    assert invalid_current_process.status_code == 400
    assert invalid_current_process.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_operator_control_current_process_invalid"
    )
    assert source_policy_failed.status_code == 503
    assert source_policy_failed.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_operator_control_source_failed"
    )
    assert source_preview_failed.status_code == 503
    assert source_preview_failed.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_operator_control_preview_failed"
    )


def test_artifact_retention_scheduler_daemon_operator_control_validator_edges() -> (
    None
):
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": (
                "/admin/v1/operations/artifact-retention/"
                "scheduler-daemon-operator-control-preview"
            ),
            "headers": [],
            "query_string": b"",
        }
    )

    invalid_payload = (
        artifact_operations._validate_artifact_retention_daemon_operator_control_preview_request(
            request,
            payload=["not", "a", "mapping"],
            idempotency_key_header=None,
        )
    )
    invalid_none_cycles = (
        artifact_operations._validate_artifact_retention_daemon_operator_control_preview_request(
            request,
            payload={
                "action": "status_probe",
                "reason": "probe",
                "idempotency_key": "idem",
                "max_cycles": None,
            },
            idempotency_key_header=None,
        )
    )
    direct_subject = artifact_operations._artifact_retention_daemon_operator_subject(
        request=request,
        payload={
            "operator_subject": {
                "actor_type": "operator",
                "actor_id": "direct-operator",
                "tenant_id": "tenant-0587",
                "database_url": "DATABASE_URL_SHOULD_NOT_LEAK",
            }
        },
    )

    assert invalid_payload.status_code == 400
    assert invalid_none_cycles.status_code == 400
    assert direct_subject == {
        "actor_type": "operator",
        "actor_id": "direct-operator",
        "tenant_id": "tenant-0587",
    }


def test_artifact_retention_scheduler_daemon_operator_control_execution_routes_return_read_models() -> (
    None
):
    client = build_app(artifact_client())

    collection_response = client.get(
        (
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-operator-control-executions"
        ),
        params={
            "service_id": "nex-ae-api",
            "scheduler_id": "ae-artifact-retention-scheduler",
            "action": "restart-daemon",
            "execution_status": "failed",
            "idempotency_status": "conflict",
            "limit": "1",
        },
        headers=auth_headers(),
    )
    detail_response = client.get(
        (
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-operator-control-executions/"
            "operator-control-execution-state-0597"
        ),
        headers=auth_headers(),
    )

    assert collection_response.status_code == 200
    collection = collection_response.json()
    assert collection["projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_COLLECTION_PROJECTION_SCHEMA_VERSION
    )
    assert collection["filter"] == {
        "scheduler_id": "ae-artifact-retention-scheduler",
        "action": "restart_daemon",
        "execution_status": "FAILED",
        "idempotency_status": "CONFLICT",
    }
    assert collection["limit"] == 1
    assert collection["summary"]["failed_count"] == 1
    assert collection["summary"]["conflict_count"] == 1
    assert collection["summary"]["operator_attention_required"] is True
    assert collection["operator_guidance"][
        "ag_direct_daemon_process_control_allowed"
    ] is False
    assert collection["items"][0]["routes"]["ag_detail"].endswith(
        "/scheduler-daemon-operator-control-executions/"
        "operator-control-execution-state-conflict-0597"
    )

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_DETAIL_PROJECTION_SCHEMA_VERSION
    )
    assert detail["operator_control_execution_state_id"] == (
        "operator-control-execution-state-0597"
    )
    assert detail["transition_count"] == 1
    assert detail["summary"]["transition_statuses"] == [
        "ADMITTED->EXECUTING"
    ]
    assert detail["request_trace_id"] == TRACE_ID
    assert "DATABASE_URL_SHOULD_NOT_LEAK" not in str(collection)
    assert "SECRET_SYSTEM_PROMPT" not in str(detail)
    assert "/data/nex-platform" not in str(detail)


def test_artifact_retention_scheduler_daemon_operator_control_execution_worker_route_returns_projection() -> (
    None
):
    client = build_app(artifact_client())
    route = (
        "/admin/v1/operations/artifact-retention/"
        "scheduler-daemon-operator-control-execution-workers"
    )

    response = client.post(
        route,
        params={"service_id": "nex-ae-api"},
        json={
            "operator_control_execution_state_id": (
                "operator-control-execution-state-0597"
            )
        },
        headers=auth_headers(),
    )
    state_payload_response = client.post(
        route,
        json={
            "operator_control_execution_state": (
                artifact_retention_scheduler_daemon_operator_control_execution_state_payload()
            ),
            "worker_observed_at": "2026-09-04T02:04:00Z",
        },
        headers=auth_headers(),
    )

    assert response.status_code == 200
    projection = response.json()
    assert projection["projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_PROJECTION_SCHEMA_VERSION
    )
    assert projection["summary"]["worker_status"] == "SUCCEEDED"
    assert projection["summary"]["operator_attention_required"] is False
    assert projection["source_status"]["execution_worker_result_loaded"] is True
    assert projection["operator_guidance"][
        "ag_direct_process_control_allowed"
    ] is False
    assert projection["operator_guidance"][
        "ag_direct_database_write_allowed"
    ] is False
    assert projection["request_trace_id"] == TRACE_ID
    assert state_payload_response.status_code == 200
    assert state_payload_response.json()["summary"]["worker_status"] == "BLOCKED"
    assert "operator_control_execution_worker_command" not in projection[
        "worker_result"
    ]
    assert "DATABASE_URL_SHOULD_NOT_LEAK" not in str(projection)
    assert "SECRET_SYSTEM_PROMPT" not in str(projection)
    assert "database_url" not in str(projection)
    assert "/data/nex-platform" not in str(projection)


def test_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_routes_return_read_models() -> (
    None
):
    client = build_app(artifact_client())
    collection_route = (
        "/admin/v1/operations/artifact-retention/"
        "scheduler-daemon-operator-control-execution-worker-results"
    )
    detail_route = (
        "/admin/v1/operations/artifact-retention/"
        "scheduler-daemon-operator-control-execution-worker-results/"
        "operator-control-execution-worker-result-0607"
    )

    collection_response = client.get(
        collection_route,
        params={
            "service_id": "nex-ae-api",
            "scheduler_id": "ae-artifact-retention-scheduler",
            "action": "restart-daemon",
            "worker_status": "failed",
            "operator_control_execution_state_id": (
                "operator-control-execution-state-0597"
            ),
            "operator_control_execution_request_id": (
                "operator-control-execution-state-0597:execution-request"
            ),
            "limit": "1",
        },
        headers=auth_headers(),
    )
    detail_response = client.get(
        detail_route,
        headers=auth_headers(),
    )

    assert collection_response.status_code == 200
    collection = collection_response.json()
    assert collection["projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_COLLECTION_PROJECTION_SCHEMA_VERSION
    )
    assert collection["filter"] == {
        "scheduler_id": "ae-artifact-retention-scheduler",
        "action": "restart_daemon",
        "worker_status": "FAILED",
        "operator_control_execution_state_id": (
            "operator-control-execution-state-0597"
        ),
        "operator_control_execution_request_id": (
            "operator-control-execution-state-0597:execution-request"
        ),
    }
    assert collection["limit"] == 1
    assert collection["summary"]["failed_count"] == 1
    assert collection["summary"]["operator_attention_required"] is True
    assert collection["source_status"][
        "worker_result_collection_loaded"
    ] is True
    assert collection["operator_guidance"][
        "ag_direct_daemon_process_control_allowed"
    ] is False
    assert collection["items"][0]["routes"]["ag_detail"].endswith(
        "/scheduler-daemon-operator-control-execution-worker-results/"
        "operator-control-execution-worker-result-0607"
    )

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_DETAIL_PROJECTION_SCHEMA_VERSION
    )
    assert detail["operator_control_execution_worker_result_id"] == (
        "operator-control-execution-worker-result-0607"
    )
    assert detail["summary"]["worker_status"] == "SUCCEEDED"
    assert detail["source_status"]["worker_result_detail_loaded"] is True
    assert detail["request_trace_id"] == TRACE_ID
    assert "operator_control_execution_worker_command" not in detail[
        "worker_result"
    ]
    assert "DATABASE_URL_SHOULD_NOT_LEAK" not in str(collection)
    assert "database_url" not in str(detail)
    assert "/data/nex-platform" not in str(detail)


def test_artifact_retention_scheduler_daemon_operator_control_execution_route_guardrails() -> (
    None
):
    client = build_app(artifact_client())
    route = (
        "/admin/v1/operations/artifact-retention/"
        "scheduler-daemon-operator-control-executions"
    )

    unauthorized = client.get(route)
    invalid_service = client.get(
        route,
        params={"service_id": "nex-cx"},
        headers=auth_headers(),
    )
    invalid_action = client.get(
        route,
        params={"action": "manual_tick_once"},
        headers=auth_headers(),
    )
    invalid_execution_status = client.get(
        route,
        params={"execution_status": "READY"},
        headers=auth_headers(),
    )
    invalid_idempotency_status = client.get(
        route,
        params={"idempotency_status": "DUPLICATE"},
        headers=auth_headers(),
    )
    invalid_limit = client.get(
        route,
        params={"limit": "101"},
        headers=auth_headers(),
    )
    missing_detail = client.get(
        (
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-operator-control-executions/missing"
        ),
        headers=auth_headers(),
    )

    class BrokenOperatorControlExecutionClient(InMemoryAeArtifactOperationsClient):
        def list_artifact_retention_scheduler_daemon_operator_control_executions(
            self,
            *args: Any,
            **kwargs: Any,
        ) -> dict[str, Any]:
            raise AeArtifactOperationsError(
                error_code=(
                    "ag.ae_artifact_retention_daemon_operator_control_execution_source_failed"
                ),
                detail="AE operator-control execution source unavailable",
                status_code=503,
            )

    source_failed = build_app(BrokenOperatorControlExecutionClient()).get(
        route,
        headers=auth_headers(),
    )

    assert unauthorized.status_code == 401
    assert invalid_service.status_code == 400
    assert invalid_action.status_code == 400
    assert invalid_action.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_operator_control_execution_action_invalid"
    )
    assert invalid_execution_status.status_code == 400
    assert invalid_execution_status.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_operator_control_execution_status_invalid"
    )
    assert invalid_idempotency_status.status_code == 400
    assert invalid_idempotency_status.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_operator_control_execution_idempotency_status_invalid"
    )
    assert invalid_limit.status_code == 400
    assert invalid_limit.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_operator_control_execution_limit_invalid"
    )
    assert missing_detail.status_code == 404
    assert missing_detail.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_operator_control_execution_not_found"
    )
    assert source_failed.status_code == 503
    assert source_failed.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_operator_control_execution_source_failed"
    )


def test_artifact_retention_scheduler_daemon_operator_control_execution_worker_route_guardrails() -> (
    None
):
    client = build_app(artifact_client())
    route = (
        "/admin/v1/operations/artifact-retention/"
        "scheduler-daemon-operator-control-execution-workers"
    )

    unauthorized = client.post(route, json={})
    invalid_service = client.post(
        route,
        params={"service_id": "nex-cx"},
        json={
            "operator_control_execution_state_id": (
                "operator-control-execution-state-0597"
            )
        },
        headers=auth_headers(),
    )
    missing_state_id = client.post(route, json={}, headers=auth_headers())
    invalid_state = client.post(
        route,
        json={"operator_control_execution_state": "not-object"},
        headers=auth_headers(),
    )

    class BrokenOperatorControlExecutionWorkerClient(InMemoryAeArtifactOperationsClient):
        def run_artifact_retention_scheduler_daemon_operator_control_execution_worker(
            self,
            *args: Any,
            **kwargs: Any,
        ) -> dict[str, Any]:
            raise AeArtifactOperationsError(
                error_code=(
                    "ag.ae_artifact_retention_daemon_operator_control_execution_worker_source_failed"
                ),
                detail="AE operator-control execution worker source unavailable",
                status_code=503,
            )

    source_failed = build_app(BrokenOperatorControlExecutionWorkerClient()).post(
        route,
        json={
            "operator_control_execution_state_id": (
                "operator-control-execution-state-0597"
            )
        },
        headers=auth_headers(),
    )

    assert unauthorized.status_code == 401
    assert invalid_service.status_code == 400
    assert missing_state_id.status_code == 400
    assert missing_state_id.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_operator_control_execution_worker_state_id_missing"
    )
    assert invalid_state.status_code == 400
    assert invalid_state.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_operator_control_execution_worker_state_invalid"
    )
    assert source_failed.status_code == 503
    assert source_failed.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_operator_control_execution_worker_source_failed"
    )


def test_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_route_guardrails() -> (
    None
):
    client = build_app(artifact_client())
    route = (
        "/admin/v1/operations/artifact-retention/"
        "scheduler-daemon-operator-control-execution-worker-results"
    )

    unauthorized = client.get(route)
    invalid_service = client.get(
        route,
        params={"service_id": "nex-cx"},
        headers=auth_headers(),
    )
    invalid_action = client.get(
        route,
        params={"action": "manual_tick_once"},
        headers=auth_headers(),
    )
    invalid_worker_status = client.get(
        route,
        params={"worker_status": "EXECUTING"},
        headers=auth_headers(),
    )
    invalid_limit = client.get(
        route,
        params={"limit": "101"},
        headers=auth_headers(),
    )
    missing_detail = client.get(
        (
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-operator-control-execution-worker-results/missing"
        ),
        headers=auth_headers(),
    )

    class BrokenOperatorControlExecutionWorkerResultClient(
        InMemoryAeArtifactOperationsClient
    ):
        def list_artifact_retention_scheduler_daemon_operator_control_execution_worker_results(
            self,
            *args: Any,
            **kwargs: Any,
        ) -> dict[str, Any]:
            raise AeArtifactOperationsError(
                error_code=(
                    "ag.ae_artifact_retention_daemon_operator_control_execution_worker_result_source_failed"
                ),
                detail="AE operator-control execution worker result source unavailable",
                status_code=503,
            )

    source_failed = build_app(
        BrokenOperatorControlExecutionWorkerResultClient()
    ).get(
        route,
        headers=auth_headers(),
    )

    assert unauthorized.status_code == 401
    assert invalid_service.status_code == 400
    assert invalid_action.status_code == 400
    assert invalid_action.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_operator_control_execution_worker_result_action_invalid"
    )
    assert invalid_worker_status.status_code == 400
    assert invalid_worker_status.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_operator_control_execution_worker_result_status_invalid"
    )
    assert invalid_limit.status_code == 400
    assert invalid_limit.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_operator_control_execution_worker_result_limit_invalid"
    )
    assert missing_detail.status_code == 404
    assert missing_detail.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_operator_control_execution_worker_result_not_found"
    )
    assert source_failed.status_code == 503
    assert source_failed.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_operator_control_execution_worker_result_source_failed"
    )


def test_artifact_retention_scheduler_daemon_supervisor_routes_return_read_models() -> (
    None
):
    client = build_app(artifact_client())

    collection_response = client.get(
        (
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-supervisor-results"
        ),
        params={
            "service_id": "nex-ae-api",
            "scheduler_id": "ae-artifact-retention-scheduler",
            "action": "start-daemon",
            "result_status": "blocked",
            "limit": "1",
        },
        headers=auth_headers(),
    )
    detail_response = client.get(
        (
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-supervisor-results/daemon-supervisor-record-0567"
        ),
        headers=auth_headers(),
    )

    assert collection_response.status_code == 200
    collection = collection_response.json()
    assert collection["projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_RETENTION_DAEMON_SUPERVISOR_COLLECTION_PROJECTION_SCHEMA_VERSION
    )
    assert collection["filter"] == {
        "scheduler_id": "ae-artifact-retention-scheduler",
        "action": "start_daemon",
        "result_status": "BLOCKED",
    }
    assert collection["limit"] == 1
    assert collection["summary"]["blocked_count"] == 1
    assert collection["items"][0]["routes"]["ag_detail"].endswith(
        "/scheduler-daemon-supervisor-results/daemon-supervisor-record-0567"
    )
    assert collection["operator_guidance"][
        "ag_direct_daemon_process_control_allowed"
    ] is False
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_RETENTION_DAEMON_SUPERVISOR_DETAIL_PROJECTION_SCHEMA_VERSION
    )
    assert detail["daemon_supervisor_record_id"] == "daemon-supervisor-record-0567"
    assert detail["supervisor_event_count"] == 2
    assert detail["request_trace_id"] == TRACE_ID
    assert "database_url" not in str(collection)
    assert "/data/nex-platform" not in str(detail)


def test_artifact_retention_scheduler_daemon_supervisor_route_guardrails() -> None:
    client = build_app(artifact_client())

    unauthorized = client.get(
        (
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-supervisor-results"
        ),
    )
    invalid_service = client.get(
        (
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-supervisor-results"
        ),
        params={"service_id": "nex-cx"},
        headers=auth_headers(),
    )
    invalid_action = client.get(
        (
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-supervisor-results"
        ),
        params={"action": "manual_tick_once"},
        headers=auth_headers(),
    )
    invalid_status = client.get(
        (
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-supervisor-results"
        ),
        params={"result_status": "SUCCEEDED"},
        headers=auth_headers(),
    )
    invalid_limit = client.get(
        (
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-supervisor-results"
        ),
        params={"limit": "101"},
        headers=auth_headers(),
    )
    missing_detail = client.get(
        (
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-supervisor-results/missing"
        ),
        headers=auth_headers(),
    )

    class BrokenDaemonSupervisorClient(InMemoryAeArtifactOperationsClient):
        def list_artifact_retention_scheduler_daemon_supervisor_results(
            self,
            *args: Any,
            **kwargs: Any,
        ) -> dict[str, Any]:
            raise AeArtifactOperationsError(
                error_code=(
                    "ag.ae_artifact_retention_daemon_supervisor_source_failed"
                ),
                detail="AE scheduler daemon supervisor source unavailable",
                status_code=503,
            )

    source_failed = build_app(BrokenDaemonSupervisorClient()).get(
        (
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-supervisor-results"
        ),
        headers=auth_headers(),
    )

    assert unauthorized.status_code == 401
    assert invalid_service.status_code == 400
    assert invalid_action.status_code == 400
    assert invalid_action.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_supervisor_action_invalid"
    )
    assert invalid_status.status_code == 400
    assert invalid_status.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_supervisor_status_invalid"
    )
    assert invalid_limit.status_code == 400
    assert invalid_limit.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_supervisor_limit_invalid"
    )
    assert missing_detail.status_code == 404
    assert missing_detail.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_supervisor_not_found"
    )
    assert source_failed.status_code == 503
    assert source_failed.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_supervisor_source_failed"
    )


def test_artifact_retention_scheduler_daemon_run_routes_return_read_models() -> None:
    client = build_app(artifact_client())

    collection_response = client.get(
        "/admin/v1/operations/artifact-retention/scheduler-daemon-runs",
        params={
            "service_id": "nex-ae-api",
            "scheduler_id": "ae-artifact-retention-scheduler",
            "result_status": "SUCCEEDED",
            "limit": "1",
        },
        headers=auth_headers(),
    )
    detail_response = client.get(
        (
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-runs/daemon-run-record-0559"
        ),
        headers=auth_headers(),
    )

    assert collection_response.status_code == 200
    collection = collection_response.json()
    assert collection["projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_RETENTION_DAEMON_RUN_COLLECTION_PROJECTION_SCHEMA_VERSION
    )
    assert collection["filter"] == {
        "scheduler_id": "ae-artifact-retention-scheduler",
        "result_status": "SUCCEEDED",
    }
    assert collection["limit"] == 1
    assert collection["summary"]["succeeded_count"] == 1
    assert collection["items"][0]["routes"]["ag_detail"].endswith(
        "/scheduler-daemon-runs/daemon-run-record-0559"
    )
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_RETENTION_DAEMON_RUN_DETAIL_PROJECTION_SCHEMA_VERSION
    )
    assert detail["daemon_run_record_id"] == "daemon-run-record-0559"
    assert detail["lifecycle_event_count"] == 2
    assert detail["request_trace_id"] == TRACE_ID


def test_artifact_retention_scheduler_daemon_run_route_guardrails() -> None:
    client = build_app(artifact_client())

    unauthorized = client.get(
        "/admin/v1/operations/artifact-retention/scheduler-daemon-runs",
    )
    invalid_service = client.get(
        "/admin/v1/operations/artifact-retention/scheduler-daemon-runs",
        params={"service_id": "nex-cx"},
        headers=auth_headers(),
    )
    invalid_status = client.get(
        "/admin/v1/operations/artifact-retention/scheduler-daemon-runs",
        params={"result_status": "RUNNING"},
        headers=auth_headers(),
    )
    invalid_limit = client.get(
        "/admin/v1/operations/artifact-retention/scheduler-daemon-runs",
        params={"limit": "0"},
        headers=auth_headers(),
    )
    missing_detail = client.get(
        (
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-runs/missing"
        ),
        headers=auth_headers(),
    )

    class BrokenDaemonRunClient(InMemoryAeArtifactOperationsClient):
        def list_artifact_retention_scheduler_daemon_runs(
            self,
            *args: Any,
            **kwargs: Any,
        ) -> dict[str, Any]:
            raise AeArtifactOperationsError(
                error_code="ag.ae_artifact_retention_daemon_run_source_failed",
                detail="AE scheduler daemon run source unavailable",
                status_code=503,
            )

    source_failed = build_app(BrokenDaemonRunClient()).get(
        "/admin/v1/operations/artifact-retention/scheduler-daemon-runs",
        headers=auth_headers(),
    )

    assert unauthorized.status_code == 401
    assert invalid_service.status_code == 400
    assert invalid_status.status_code == 400
    assert invalid_status.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_run_status_invalid"
    )
    assert invalid_limit.status_code == 400
    assert invalid_limit.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_run_limit_invalid"
    )
    assert missing_detail.status_code == 404
    assert missing_detail.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_run_not_found"
    )
    assert source_failed.status_code == 503
    assert source_failed.json()["error_code"] == (
        "ag.ae_artifact_retention_daemon_run_source_failed"
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
        if url.endswith("/api/v1/artifact-retention/scheduler-daemon-runtime"):
            return FakeHttpResponse(
                200,
                artifact_retention_scheduler_daemon_runtime_payload(),
            )
        if url.endswith("/api/v1/artifact-retention/scheduler-daemon-runs"):
            return FakeHttpResponse(
                200,
                artifact_retention_scheduler_daemon_run_collection_payload(),
            )
        if url.endswith(
            "/api/v1/artifact-retention/"
            "scheduler-daemon-runs/daemon-run-record-0559"
        ):
            return FakeHttpResponse(
                200,
                artifact_retention_scheduler_daemon_run_detail_payload(),
            )
        if url.endswith(
            "/api/v1/artifact-retention/scheduler-daemon-supervisor-results"
        ):
            return FakeHttpResponse(
                200,
                artifact_retention_scheduler_daemon_supervisor_collection_payload(),
            )
        if url.endswith(
            "/api/v1/artifact-retention/"
            "scheduler-daemon-supervisor-results/daemon-supervisor-record-0567"
        ):
            return FakeHttpResponse(
                200,
                artifact_retention_scheduler_daemon_supervisor_detail_payload(),
            )
        if url.endswith(
            "/api/v1/artifact-retention/"
            "scheduler-daemon-process-snapshots"
        ):
            return FakeHttpResponse(
                200,
                artifact_retention_scheduler_daemon_supervised_process_collection_payload(),
            )
        if url.endswith(
            "/api/v1/artifact-retention/scheduler-daemon-process-snapshots/"
            "daemon-supervised-process-record-0576"
        ):
            return FakeHttpResponse(
                200,
                artifact_retention_scheduler_daemon_supervised_process_detail_payload(),
            )
        if url.endswith(
            "/api/v1/artifact-retention/"
            "scheduler-daemon-operator-control-policy"
        ):
            return FakeHttpResponse(
                200,
                artifact_retention_scheduler_daemon_operator_control_policy_payload(),
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
        if url.endswith(
            "/api/v1/artifact-retention/"
            "scheduler-daemon-operator-control-preview"
        ):
            return FakeHttpResponse(
                200,
                artifact_retention_scheduler_daemon_operator_control_facade_payload(),
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
    daemon_runtime = client.get_artifact_retention_scheduler_daemon_runtime(
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
    daemon_runs = client.list_artifact_retention_scheduler_daemon_runs(
        scheduler_id="ae-artifact-retention-scheduler",
        result_status="SUCCEEDED",
        limit=20,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    daemon_run_detail = client.get_artifact_retention_scheduler_daemon_run_detail(
        "daemon-run-record-0559",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    daemon_supervisor_results = (
        client.list_artifact_retention_scheduler_daemon_supervisor_results(
            scheduler_id="ae-artifact-retention-scheduler",
            action="start_daemon",
            result_status="BLOCKED",
            limit=20,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    )
    daemon_supervisor_detail = (
        client.get_artifact_retention_scheduler_daemon_supervisor_detail(
            "daemon-supervisor-record-0567",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    )
    daemon_process_snapshots = (
        client.list_artifact_retention_scheduler_daemon_process_snapshots(
            scheduler_id="ae-artifact-retention-scheduler",
            action="start_daemon",
            process_status="RUNNING",
            limit=20,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    )
    daemon_process_detail = (
        client.get_artifact_retention_scheduler_daemon_process_snapshot_detail(
            "daemon-supervised-process-record-0576",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    )
    operator_control_policy = (
        client.get_artifact_retention_scheduler_daemon_operator_control_policy(
            checked_at="2026-09-03T02:00:00Z",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    )
    operator_control_preview = (
        client.preview_artifact_retention_scheduler_daemon_operator_control(
            action="restart_daemon",
            operator_subject={
                "actor_type": "operator",
                "actor_id": "ag-retention-operator",
            },
            idempotency_key="operator-control-idem-0587",
            reason="restart preview",
            requested_at="2026-09-03T02:00:00Z",
            checked_at="2026-09-03T02:00:00Z",
            profile="test",
            enabled=True,
            explicit_opt_in=True,
            max_cycles=2,
            run_worker=False,
            approval={"approved": True},
            current_process={"process_status": "RUNNING", "process_id": 5870},
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
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
    assert daemon_runtime["heartbeat"]["status"] == "BUSY"
    assert daemon_dispatch["dispatch_status"] == "DISPATCHED"
    assert daemon_runs["count"] == 2
    assert daemon_run_detail is not None
    assert daemon_run_detail["daemon_run_record_id"] == "daemon-run-record-0559"
    assert daemon_supervisor_results["count"] == 2
    assert daemon_supervisor_detail is not None
    assert daemon_supervisor_detail["daemon_supervisor_record_id"] == (
        "daemon-supervisor-record-0567"
    )
    assert daemon_process_snapshots["count"] == 2
    assert daemon_process_detail is not None
    assert daemon_process_detail["daemon_supervised_process_record_id"] == (
        "daemon-supervised-process-record-0576"
    )
    assert operator_control_policy["operator_control_policy_id"]
    assert operator_control_preview["facade_status"] == "READY"
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
        "scheduler-daemon-runtime"
    )
    assert calls[9]["params"] == {}
    assert calls[10]["url"] == (
        "http://ae.example.local/api/v1/artifact-retention/"
        "scheduler-daemon-controls"
    )
    assert calls[10]["headers"]["Idempotency-Key"] == "daemon-idem-0522"
    assert calls[10]["json"] == {
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
    assert calls[11]["url"] == (
        "http://ae.example.local/api/v1/artifact-retention/"
        "scheduler-daemon-runs"
    )
    assert calls[11]["params"] == {
        "limit": "20",
        "scheduler_id": "ae-artifact-retention-scheduler",
        "result_status": "SUCCEEDED",
    }
    assert calls[12]["url"] == (
        "http://ae.example.local/api/v1/artifact-retention/"
        "scheduler-daemon-runs/daemon-run-record-0559"
    )
    assert calls[12]["params"] == {}
    assert calls[13]["url"] == (
        "http://ae.example.local/api/v1/artifact-retention/"
        "scheduler-daemon-supervisor-results"
    )
    assert calls[13]["params"] == {
        "limit": "20",
        "scheduler_id": "ae-artifact-retention-scheduler",
        "action": "start_daemon",
        "result_status": "BLOCKED",
    }
    assert calls[14]["url"] == (
        "http://ae.example.local/api/v1/artifact-retention/"
        "scheduler-daemon-supervisor-results/daemon-supervisor-record-0567"
    )
    assert calls[14]["params"] == {}
    assert calls[15]["url"] == (
        "http://ae.example.local/api/v1/artifact-retention/"
        "scheduler-daemon-process-snapshots"
    )
    assert calls[15]["params"] == {
        "limit": "20",
        "scheduler_id": "ae-artifact-retention-scheduler",
        "action": "start_daemon",
        "process_status": "RUNNING",
    }
    assert calls[16]["url"] == (
        "http://ae.example.local/api/v1/artifact-retention/"
        "scheduler-daemon-process-snapshots/"
        "daemon-supervised-process-record-0576"
    )
    assert calls[16]["params"] == {}
    assert calls[17]["url"] == (
        "http://ae.example.local/api/v1/artifact-retention/"
        "scheduler-daemon-operator-control-policy"
    )
    assert calls[17]["params"] == {"checked_at": "2026-09-03T02:00:00Z"}
    assert calls[18]["url"] == (
        "http://ae.example.local/api/v1/artifact-retention/"
        "scheduler-daemon-operator-control-preview"
    )
    assert calls[18]["headers"]["Idempotency-Key"] == "operator-control-idem-0587"
    assert calls[18]["json"]["action"] == "restart_daemon"
    assert calls[18]["json"]["operator_subject"] == {
        "actor_type": "operator",
        "actor_id": "ag-retention-operator",
    }
    assert calls[18]["json"]["max_cycles"] == 2


def test_http_operator_control_client_handles_sparse_response_and_optional_body(
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
        return FakeHttpResponse(200, ["not-a-policy-object"])

    def fake_post(
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
        timeout: float,
    ) -> FakeHttpResponse:
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return FakeHttpResponse(200, ["not-a-facade-object"])

    monkeypatch.setattr(artifact_operations.httpx, "get", fake_get)
    monkeypatch.setattr(artifact_operations.httpx, "post", fake_post)
    client = HttpAeArtifactOperationsClient(
        base_url="http://ae.example.local/",
        service_token=None,
        timeout_seconds=7.0,
    )

    policy = client.get_artifact_retention_scheduler_daemon_operator_control_policy(
        checked_at=None,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    preview = client.preview_artifact_retention_scheduler_daemon_operator_control(
        action="status_probe",
        operator_subject={"actor_type": "operator", "actor_id": "ag"},
        idempotency_key="operator-control-sparse-idem",
        reason="probe",
        requested_at=None,
        checked_at=None,
        profile="test",
        enabled=False,
        explicit_opt_in=False,
        max_cycles=1,
        run_worker=False,
        approval=None,
        current_process=None,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert policy == {}
    assert preview == {}
    assert calls[0]["params"] == {}
    assert calls[0]["headers"]["Authorization"].startswith("Bearer ")
    assert calls[0]["headers"]["X-Service-ID"] == "nex-ag"
    assert calls[1]["headers"]["Idempotency-Key"] == "operator-control-sparse-idem"
    assert calls[1]["json"] == {
        "action": "status_probe",
        "operator_subject": {"actor_type": "operator", "actor_id": "ag"},
        "idempotency_key": "operator-control-sparse-idem",
        "reason": "probe",
        "profile": "test",
        "enabled": False,
        "explicit_opt_in": False,
        "max_cycles": 1,
        "run_worker": False,
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
