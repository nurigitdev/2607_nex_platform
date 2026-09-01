from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from nex_ag.artifact_operations import (
    AG_ARTIFACT_OPERATION_COLLECTION_PROJECTION_SCHEMA_VERSION,
    AG_ARTIFACT_OPERATION_DETAIL_PROJECTION_SCHEMA_VERSION,
    AG_ARTIFACT_OPERATION_LIFECYCLE_PROJECTION_SCHEMA_VERSION,
    AG_ARTIFACT_OPERATION_RETENTION_HISTORY_PROJECTION_SCHEMA_VERSION,
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
    build_artifact_operation_retention_history_projection,
    build_default_ae_artifact_operations_client,
    register_artifact_operation_routes,
    summarize_artifact_operation_collection,
    summarize_artifact_operation_detail,
    summarize_artifact_operation_lifecycle,
    summarize_artifact_retention_history_operations,
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
    assert projection["items"][0]["latest_render_job"]["render_status"] == (
        "SUCCEEDED"
    )
    assert projection["source_status"]["item_count"] == 2
    assert projection["request_trace_id"] == TRACE_ID
    assert "PRIVATE_CONTENT" not in str(projection)
    assert "hidden prompt" not in str(projection)
    assert "/data/nex-platform" not in str(projection)


def test_artifact_operation_retention_history_projection_summarizes_and_redacts() -> None:
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
    assert summarize_artifact_operation_lifecycle(
        projection["artifact"],
        projection["lifecycle"]["actions"],
    ) == projection["summary"]
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
        action["action"]: action
        for action in projection["lifecycle"]["actions"]
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


def test_artifact_operation_lifecycle_projection_degrades_source_contract_edges() -> None:
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
        action["enabled"] is False
        for action in rendering["lifecycle"]["actions"]
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
    assert artifact_operations._json_safe_value(["x", {"keep": object(), "drop": None}])[
        1
    ]["keep"].startswith("<object object")


def test_artifact_operation_projection_redaction_guard_raises() -> None:
    with pytest.raises(ValueError, match="private data"):
        assert_artifact_operation_projection_redacted(
            {"artifact": {"storage_ref": "/data/nex-platform/private.md"}}
        )


def test_in_memory_artifact_operations_client_returns_copies_and_missing_values() -> None:
    client = artifact_client()
    artifact = client.get_artifact(ARTIFACT_ID, request_id=REQUEST_ID, trace_id=TRACE_ID)
    refs = client.list_chat_artifact_refs(
        INTERACTION_ID,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    artifact["artifact_status"] = "MUTATED"
    refs[0]["artifact_status"] = "MUTATED"

    assert client.get_artifact("missing", request_id=REQUEST_ID, trace_id=TRACE_ID) is None
    assert client.get_artifact_handoff("missing", request_id=REQUEST_ID, trace_id=TRACE_ID) is None
    assert client.list_chat_artifact_refs("missing", request_id=REQUEST_ID, trace_id=TRACE_ID) == []
    assert client.artifacts[ARTIFACT_ID]["artifact_status"] == "READY"
    assert client.chat_artifact_refs[INTERACTION_ID]["artifact_refs"][0]["artifact_status"] == "READY"


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
    assert artifact_operations._owner_tenant_id({"tenant_id": "tenant-fallback"}) == (
        "tenant-fallback"
    )
    assert artifact_operations._owner_user_id({"owner_user_id": "owner-fallback"}) == (
        "owner-fallback"
    )
    assert artifact_operations._workspace_id({"workspace_id": "workspace-fallback"}) == (
        "workspace-fallback"
    )
    assert artifact_operations._current_version_no([], "missing") == 0
    assert artifact_operations._latest_render_job_summary([]) == {}
    assert artifact_operations._normalized_retention_mode("dry-run") == "DRY_RUN"
    assert artifact_operations._normalized_retention_mode(None) is None
    assert artifact_operations._normalized_retention_status("blocked") == "BLOCKED"
    assert artifact_operations._normalized_retention_status(None) is None
    assert artifact_operations._safe_deleted_counts("bad") == {}
    assert artifact_operations._safe_deleted_counts({"artifacts": "2"})["artifacts"] == 2


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

    assert client.artifact_retention_history_collections[
        artifact_operations._artifact_retention_history_cache_key(
            tenant_id="tenant-0409",
            workspace_id="workspace-0409",
            owner_user_id="user-0409",
            mode=None,
            execution_status=None,
            limit=20,
        )
    ]["items"][0]["retention_execution_id"] == "retention-execute-0409"
    assert execute_history["count"] == 2
    assert execute_history["filter"]["mode"] == "EXECUTE"
    assert empty_history["count"] == 0
    assert empty_history["filter"]["execution_status"] == "FAILED"


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
    assert payload["items"][0]["retention_execution_id"] == (
        "retention-execute-0409"
    )
    assert payload["request_trace_id"] == TRACE_ID
    assert execute_only.status_code == 200
    assert execute_only.json()["filter"]["mode"] == "EXECUTE"
    assert execute_only.json()["summary"]["execute_count"] == 2


def test_artifact_retention_history_operations_route_auth_filter_and_error_edges() -> None:
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


def test_artifact_operation_lifecycle_route_auth_filter_missing_and_source_errors() -> None:
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


def test_artifact_operation_route_auth_filter_missing_and_optional_error_edges() -> None:
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
        def get_artifact_handoff(self, *args: Any, **kwargs: Any) -> dict[str, Any] | None:
            raise AeArtifactOperationsError(
                error_code="ag.optional_handoff_failed",
                detail="handoff unavailable",
            )

        def list_chat_artifact_refs(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
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
            return FakeHttpResponse(200, artifact_retention_history_collection_payload())
        if url.endswith(f"/api/v1/artifacts/{ARTIFACT_ID}"):
            return FakeHttpResponse(200, artifact_record(include_private=False))
        if url.endswith(f"/api/v1/artifact-handoffs/{HANDOFF_ID}"):
            return FakeHttpResponse(200, handoff_record())
        if url.endswith(f"/api/v1/chat/interactions/{INTERACTION_ID}/artifact-links"):
            return FakeHttpResponse(200, {"artifact_refs": [chat_artifact_ref()]})
        return FakeHttpResponse(404, {})

    monkeypatch.setattr(artifact_operations.httpx, "get", fake_get)
    client = HttpAeArtifactOperationsClient(
        base_url="http://ae.example.local/",
        service_token="token-0409",
        timeout_seconds=12.5,
    )

    artifact = client.get_artifact(ARTIFACT_ID, request_id=REQUEST_ID, trace_id=TRACE_ID)
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

    assert artifact["artifact_id"] == ARTIFACT_ID
    assert handoff["artifact_handoff_id"] == HANDOFF_ID
    assert refs[0]["artifact_id"] == ARTIFACT_ID
    assert collection["count"] == 2
    assert retention_history["count"] == 3
    assert calls[0]["url"] == f"http://ae.example.local/api/v1/artifacts/{ARTIFACT_ID}"
    assert calls[0]["headers"]["Authorization"] == "Bearer token-0409"
    assert calls[0]["headers"]["X-Service-ID"] == "nex-ag"
    assert calls[0]["timeout"] == 12.5
    assert calls[-2]["url"] == "http://ae.example.local/api/v1/artifacts"
    assert calls[-2]["params"] == {
        "tenant_id": "tenant-0409",
        "workspace_id": "workspace-0409",
        "owner_user_id": "user-0409",
        "limit": "25",
        "status": "READY",
    }
    assert calls[-1]["url"] == (
        "http://ae.example.local/api/v1/artifact-retention/executions"
    )
    assert calls[-1]["params"] == {
        "tenant_id": "tenant-0409",
        "workspace_id": "workspace-0409",
        "owner_user_id": "user-0409",
        "limit": "20",
        "mode": "EXECUTE",
        "execution_status": "BLOCKED",
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

    assert client.get_artifact(ARTIFACT_ID, request_id=REQUEST_ID, trace_id=TRACE_ID) is None
    assert client.list_chat_artifact_refs(INTERACTION_ID, request_id=REQUEST_ID, trace_id=TRACE_ID) == []
    with pytest.raises(AeArtifactOperationsError) as problem:
        client.get_artifact(ARTIFACT_ID, request_id=REQUEST_ID, trace_id=TRACE_ID)
    with pytest.raises(AeArtifactOperationsError) as fallback:
        client.get_artifact(ARTIFACT_ID, request_id=REQUEST_ID, trace_id=TRACE_ID)
    assert client._get_json("/ok", request_id=REQUEST_ID, trace_id=TRACE_ID) == []
    assert artifact_operations._safe_response_json(FakeHttpResponse(500, [])) == {}
    assert problem.value.error_code == "ae.artifact_source_down"
    assert fallback.value.error_code == "ag.ae_artifact_source_request_failed"


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
    assert "/admin/v1/operations/artifacts/{artifact_id}" in paths
    assert "/admin/v1/operations/artifacts/{artifact_id}/lifecycle" in paths
    assert AE_ARTIFACT_SOURCE_SERVICE_ID == "nex-ae-api"
