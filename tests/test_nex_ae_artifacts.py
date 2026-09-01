from __future__ import annotations

import base64
import json
from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace
from typing import Any
from zipfile import ZipFile

import httpx
import pypdf
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import nex_ae_api.artifacts as ae_artifacts
from nex_ae_api.artifacts import (
    ArtifactHandoffError,
    ArtifactHandoffStore,
    ArtifactRetentionExecutionHistoryStore,
    ArtifactRecordStore,
    ARTIFACT_COLLECTION_SCHEMA_VERSION,
    ARTIFACT_COLLECTION_ITEM_SCHEMA_VERSION,
    AE_ARTIFACT_LIFECYCLE_ACTION_RESULT_SCHEMA_VERSION,
    AE_ARTIFACT_LIFECYCLE_ACTION_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_BATCH_PLAN_ITEM_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_BATCH_PLAN_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_EXECUTION_HISTORY_COLLECTION_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_EXECUTION_HISTORY_ITEM_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_EXECUTION_HISTORY_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_EXECUTION_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_POLICY_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULE_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_CONFIG_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_TICK_PLAN_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULED_EXECUTION_COMMAND_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULED_EXECUTION_WORKER_RESULT_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULED_JOB_COLLECTION_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULED_JOB_ADMISSION_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULED_JOB_ENQUEUE_RESULT_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULED_JOB_PAYLOAD_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULED_JOB_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULED_JOB_TYPE,
    AE_ARTIFACT_RETENTION_SCHEDULED_WORKER_TYPE,
    HttpCxArtifactSourceClient,
    InMemoryRenderedArtifactStorage,
    LocalRenderedArtifactStorage,
    SqlAlchemyArtifactHandoffStore,
    SqlAlchemyArtifactRetentionExecutionHistoryStore,
    SqlAlchemyArtifactRecordStore,
    actor_claims_ref_from_payload,
    apply_artifact_lifecycle_action,
    artifact_content_kind,
    artifact_file_extension,
    artifact_file_name_for_format,
    artifact_intent_from_payload,
    artifact_mime_type,
    artifact_format_spec,
    artifact_type_from_payload,
    build_artifact_links,
    build_artifact_links_for_files,
    build_artifact_collection_filter,
    build_artifact_collection_item,
    build_artifact_lifecycle_action_request,
    build_artifact_lifecycle_action_result,
    build_artifact_retention_batch_plan,
    build_artifact_retention_candidate_filter,
    build_artifact_retention_candidate_collection,
    build_artifact_retention_execution,
    build_artifact_retention_execution_history_collection,
    build_artifact_retention_execution_history_filter,
    build_artifact_retention_execution_history_item,
    build_artifact_retention_execution_history_record,
    build_artifact_retention_policy,
    build_artifact_retention_schedule,
    build_artifact_retention_scheduler_config,
    build_artifact_retention_scheduler_runtime_config,
    build_artifact_retention_scheduler_tick_plan,
    build_artifact_retention_scheduled_execution_command,
    build_artifact_retention_scheduled_job_collection,
    build_artifact_retention_scheduled_job_admission,
    build_artifact_retention_scheduled_job,
    build_artifact_retention_scheduled_job_payload,
    build_artifact_retention_scheduled_worker_config,
    build_artifact_retention_scheduled_worker_handler,
    build_default_artifact_handoff_store,
    build_default_artifact_retention_execution_history_store,
    build_default_artifact_record_store,
    build_default_rendered_artifact_storage,
    build_artifact_handoff_record,
    build_docx_export_artifact_file,
    build_html_preview_artifact_file,
    build_markdown_artifact_files,
    build_markdown_render_result,
    build_pdf_export_artifact_file,
    build_rendered_artifact_file,
    build_rendered_payloads_from_markdown,
    build_artifact_record_from_handoff,
    deterministic_render_job_id,
    normalize_artifact_collection_limit,
    normalize_artifact_retention_delete_limit,
    normalize_artifact_retention_days,
    normalize_artifact_retention_scheduled_job_status,
    normalize_artifact_lifecycle_action,
    normalize_artifact_restore_status,
    language_from_payload,
    markdown_target_formats_from_payload,
    register_artifact_handoff_routes,
    render_docx_export_from_markdown,
    render_html_preview_from_markdown,
    render_markdown_from_structured_draft,
    render_pdf_export_from_markdown,
    render_stage_sequence_for_formats,
    render_target_formats_from_payload,
    rendered_download_fields_from_payload,
    rendered_text_from_payload,
    resolve_artifact_file_payload,
    resolve_rendered_artifact_file_payload,
    safe_file_stem,
    sha256_bytes,
    summarize_artifact_retention_batch_plan,
    summarize_artifact_retention_scheduled_execution_command,
    summarize_artifact_retention_scheduled_execution_worker_result,
    summarize_artifact_retention_scheduled_job,
    summarize_artifact_retention_execution_history,
    target_formats_from_payload,
    parse_artifact_retention_timestamp,
    run_artifact_retention_scheduled_execution_mock_worker,
    run_artifact_retention_scheduled_worker_batch,
    run_artifact_retention_scheduled_worker_once,
    enqueue_artifact_retention_scheduled_job,
    artifact_retention_scheduled_command_from_job,
    artifact_retention_scheduled_job_admission_idempotency_key,
    artifact_retention_scheduled_job_id,
    artifact_retention_scheduled_job_idempotency_key,
    assert_artifact_retention_history_payload_safe,
    validate_artifact_retention_batch_plan,
    validate_artifact_retention_execution,
    validate_artifact_retention_execution_history_record,
    validate_artifact_retention_policy,
    validate_artifact_retention_schedule,
    validate_artifact_retention_scheduler_config,
    validate_artifact_retention_scheduler_tick_plan,
    validate_artifact_retention_scheduled_execution_command,
    validate_artifact_retention_scheduled_job_collection,
    validate_artifact_retention_scheduled_execution_worker_result,
    validate_artifact_retention_scheduled_job_admission,
    validate_artifact_retention_scheduled_job_enqueue_result,
    validate_artifact_retention_scheduled_job,
    validate_artifact_retention_scheduled_job_payload,
    validate_artifact_handoff_record,
    validate_structured_draft_for_markdown_render,
)
from nex_runtime import (
    InMemoryJobQueue,
    InMemoryWorkerHeartbeatStore,
    JobQueueError,
    SERVICE_SPECS,
    WorkerHeartbeatEmitter,
    build_service_app,
    issue_mock_service_token,
)


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


class FakeCxArtifactSourceClient:
    def __init__(
        self,
        *,
        generation_record: dict[str, Any] | None = None,
        structured_draft: dict[str, Any] | None = None,
    ) -> None:
        self.generation_record = generation_record or sample_generation_record()
        self.structured_draft = structured_draft or sample_structured_draft()
        self.calls: list[tuple[str, str]] = []

    def get_generation(
        self,
        cx_generation_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        self.calls.append(("generation", cx_generation_id))
        return self.generation_record

    def get_structured_draft(
        self,
        cx_generation_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        self.calls.append(("draft", cx_generation_id))
        return self.structured_draft


def auth_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience="nex-ae-api")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
        "Idempotency-Key": "artifact-request-001",
    }


def sample_generation_record(*, status: str = "COMPLETED") -> dict[str, Any]:
    return {
        "cx_generation_id": "cx-gen-001",
        "status": status,
        "request_metadata": {
            "structured_draft_id": "draft-001",
            "grounding_required": True,
            "retrieval_package_id": "cx-ret-001",
            "retrieval_package_hash": "d" * 64,
            "selected_evidence_count": 2,
        },
    }


def sample_structured_draft(
    *,
    status: str = "VALIDATED",
    citation_status: str = "VALIDATED",
    cx_generation_id: str = "cx-gen-001",
    structured_draft_id: str = "draft-001",
    content_hash: str = "c" * 64,
) -> dict[str, Any]:
    return {
        "structured_draft_schema_version": "cx_structured_draft.v1",
        "structured_draft_id": structured_draft_id,
        "cx_generation_id": cx_generation_id,
        "status": status,
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "title": "Grounded report",
        "summary": "Safe summary.",
        "content_hash": content_hash,
        "sections": [
            {
                "section_id": "section-001",
                "ordinal": 1,
                "heading": "Overview",
                "blocks": [
                    {
                        "block_id": "block-001",
                        "block_type": "paragraph",
                        "text_hash": "e" * 64,
                        "text_preview": "Grounded answer [1].",
                    },
                    {
                        "block_id": "block-002",
                        "block_type": "paragraph",
                        "text_hash": "f" * 64,
                        "text_preview": "Second finding [2].",
                    },
                ],
            }
        ],
        "citations": [
            {
                "citation_label": "[1]",
                "evidence_id": "evidence-001",
                "retrieval_package_id": "cx-ret-001",
                "valid": True,
                "validation_error": None,
            },
            {
                "citation_label": "[2]",
                "evidence_id": "evidence-002",
                "retrieval_package_id": "cx-ret-001",
                "valid": True,
                "validation_error": None,
            },
        ],
        "validation": {
            "validator_profile_id": "mock-structured-draft-validator-v1",
            "citation_status": citation_status,
            "errors": [] if citation_status == "VALIDATED" else [{"code": "bad"}],
            "warnings": [],
        },
    }


def artifact_payload() -> dict[str, Any]:
    return {
        "cx_generation_id": "cx-gen-001",
        "chat_document_id": "chat-doc-001",
        "interaction_id": "interaction-001",
        "workspace_id": "workspace-001",
        "tenant_id": "tenant-001",
        "owner_user_id": "user-001",
        "artifact_intent": "create_and_export",
        "target_formats": ["MD", "HTML_PREVIEW", "DOCX", "PDF", "MD"],
        "artifact_title": "Generated report",
        "language": "ko",
        "actor_claims_ref": {
            "actor_type": "user",
            "actor_id": "user-001",
            "tenant_id": "tenant-001",
        },
    }


def build_client(
    cx_client: FakeCxArtifactSourceClient | None = None,
) -> tuple[TestClient, ArtifactHandoffStore, FakeCxArtifactSourceClient]:
    client, store, _, source_client = build_client_with_artifact_store(cx_client)
    return client, store, source_client


def build_client_with_artifact_store(
    cx_client: FakeCxArtifactSourceClient | None = None,
    retention_history_store: ArtifactRetentionExecutionHistoryStore | None = None,
    job_queue: Any | None = None,
) -> tuple[
    TestClient,
    ArtifactHandoffStore,
    ArtifactRecordStore,
    FakeCxArtifactSourceClient,
]:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    store = ArtifactHandoffStore()
    artifact_store = ArtifactRecordStore()
    client = cx_client or FakeCxArtifactSourceClient()
    register_artifact_handoff_routes(
        app,
        store=store,
        artifact_store=artifact_store,
        retention_history_store=retention_history_store,
        job_queue=job_queue,
        cx_client=client,
    )
    return TestClient(app), store, artifact_store, client


def sample_handoff_record() -> dict[str, Any]:
    return build_artifact_handoff_record(
        source_payload=artifact_payload(),
        generation_record=sample_generation_record(),
        structured_draft=sample_structured_draft(),
        artifact_request_id="artifact-request-001",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )


def sample_collection_artifact_record(
    *,
    artifact_request_id: str,
    artifact_status: str = "DRAFT",
    tenant_id: str = "tenant-001",
    workspace_id: str = "workspace-001",
    owner_user_id: str = "user-001",
    display_title: str = "Generated report",
    updated_at: str = "2026-08-30T00:00:00Z",
) -> dict[str, Any]:
    handoff = {
        **sample_handoff_record(),
        "artifact_handoff_id": f"handoff-{artifact_request_id}",
        "artifact_request_id": f"handoff-request-{artifact_request_id}",
        "artifact_title": display_title,
        "actor_claims_ref": {
            "actor_type": "user",
            "actor_id": owner_user_id,
            "tenant_id": tenant_id,
        },
        "workspace_ref": {
            "workspace_id": workspace_id,
            "tenant_id": tenant_id,
        },
    }
    record = build_artifact_record_from_handoff(
        source_payload={
            "artifact_request_id": artifact_request_id,
            "display_title": display_title,
        },
        handoff_record=handoff,
        artifact_request_id=None,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    record["artifact_status"] = artifact_status
    record["updated_at"] = updated_at
    return record


def save_rendered_retention_artifact(
    store: ArtifactRecordStore | SqlAlchemyArtifactRecordStore,
    *,
    artifact_request_id: str,
    artifact_status: str = "DELETED",
    updated_at: str = "2026-07-31T00:00:00Z",
    target_formats: list[str] | None = None,
) -> dict[str, Any]:
    artifact_record = sample_collection_artifact_record(
        artifact_request_id=artifact_request_id,
        artifact_status="DRAFT",
        updated_at=updated_at,
    )
    created = store.create(artifact_record)
    render_result = build_markdown_render_result(
        artifact_record=created,
        structured_draft=sample_structured_draft(),
        target_formats=target_formats or ["MD", "HTML_PREVIEW"],
        render_request_id=f"render-{artifact_request_id}",
        render_job_id=deterministic_render_job_id(
            created["artifact_id"],
            f"render-{artifact_request_id}",
        ),
    )
    rendered = store.apply_markdown_render(
        artifact_id=created["artifact_id"],
        artifact_version=render_result["artifact_version"],
        render_job=render_result["render_job"],
        markdown=render_result["markdown"],
        artifact_files=render_result["artifact_files"],
        artifact_links=render_result["artifact_links"],
        rendered_payloads=render_result["rendered_payloads"],
    )
    rendered["artifact_status"] = artifact_status
    rendered["updated_at"] = updated_at
    store.save(rendered)
    return rendered


def sample_retention_execution(**overrides: Any) -> dict[str, Any]:
    payload = {
        "tenant_id": "tenant-001",
        "workspace_id": "workspace-001",
        "owner_user_id": "user-001",
        "as_of": "2026-09-01T00:00:00Z",
        "checked_at": "2026-09-01T02:30:00Z",
        "candidate_count": 2,
        "selected_count": 1,
        "idempotency_key": "retention-history-001",
        "request_id": REQUEST_ID,
        "trace_id": TRACE_ID,
    }
    payload.update(overrides)
    return build_artifact_retention_execution(**payload)


def sqlite_artifact_session_factory():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        future=True,
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE ae_artifact_handoffs (
                    artifact_handoff_id TEXT PRIMARY KEY,
                    handoff_schema_version TEXT NOT NULL,
                    artifact_request_id TEXT NOT NULL UNIQUE,
                    handoff_status TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    chat_document_id TEXT NOT NULL,
                    interaction_id TEXT NOT NULL,
                    cx_generation_id TEXT NOT NULL,
                    structured_draft_id TEXT NOT NULL,
                    draft_schema_version TEXT NOT NULL,
                    structured_draft_content_hash TEXT NOT NULL,
                    citation_claims_hash TEXT NOT NULL,
                    validation_result_hash TEXT NOT NULL,
                    template_id TEXT,
                    template_version TEXT,
                    rendering_template_id TEXT,
                    artifact_intent TEXT NOT NULL,
                    target_formats TEXT NOT NULL,
                    artifact_title TEXT NOT NULL,
                    language TEXT NOT NULL,
                    retention_policy_ref TEXT NOT NULL,
                    actor_claims_ref TEXT NOT NULL,
                    workspace_ref TEXT NOT NULL,
                    quality_summary TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE ae_artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    artifact_schema_version TEXT NOT NULL,
                    artifact_type TEXT NOT NULL,
                    artifact_status TEXT NOT NULL,
                    current_version_id TEXT,
                    artifact_handoff_id TEXT NOT NULL,
                    artifact_request_id TEXT NOT NULL UNIQUE,
                    tenant_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL,
                    chat_document_id TEXT NOT NULL,
                    interaction_id TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    display_title TEXT NOT NULL,
                    language TEXT NOT NULL,
                    artifact_intent TEXT NOT NULL,
                    target_formats TEXT NOT NULL,
                    retention_policy_ref TEXT NOT NULL,
                    owner_actor_ref TEXT NOT NULL,
                    workspace_ref TEXT NOT NULL,
                    template_ref TEXT NOT NULL,
                    handoff_ref TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE ae_artifact_source_refs (
                    source_ref_id TEXT PRIMARY KEY,
                    artifact_id TEXT NOT NULL,
                    cx_generation_id TEXT NOT NULL,
                    structured_draft_id TEXT NOT NULL,
                    draft_schema_version TEXT NOT NULL,
                    structured_draft_content_hash TEXT NOT NULL,
                    citation_claims_hash TEXT NOT NULL,
                    validation_result_hash TEXT NOT NULL,
                    retrieval_package_id TEXT,
                    retrieval_package_hash TEXT,
                    evidence_ref_count INTEGER NOT NULL,
                    source_anchor_count INTEGER NOT NULL,
                    quality_summary TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE ae_artifact_versions (
                    artifact_version_id TEXT PRIMARY KEY,
                    artifact_id TEXT NOT NULL,
                    version_no INTEGER NOT NULL,
                    version_reason TEXT NOT NULL,
                    source_generation_id TEXT NOT NULL,
                    source_structured_draft_id TEXT NOT NULL,
                    source_content_hash TEXT NOT NULL,
                    source_citation_claims_hash TEXT NOT NULL,
                    render_policy_hash TEXT NOT NULL,
                    artifact_content_hash TEXT NOT NULL,
                    rendered_formats TEXT NOT NULL,
                    validation_snapshot TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE ae_artifact_render_jobs (
                    render_job_id TEXT PRIMARY KEY,
                    artifact_id TEXT NOT NULL,
                    artifact_version_id TEXT,
                    job_status TEXT NOT NULL,
                    current_stage TEXT NOT NULL,
                    progress_mode TEXT NOT NULL,
                    progress_percent INTEGER NOT NULL,
                    retryable INTEGER NOT NULL,
                    failure_code TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE ae_artifact_files (
                    artifact_file_id TEXT PRIMARY KEY,
                    artifact_version_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    format TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    storage_ref TEXT NOT NULL,
                    file_size_bytes INTEGER NOT NULL,
                    file_hash TEXT NOT NULL,
                    source_version_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE ae_artifact_links (
                    artifact_link_id TEXT PRIMARY KEY,
                    artifact_file_id TEXT NOT NULL,
                    link_type TEXT NOT NULL,
                    access_policy TEXT NOT NULL,
                    link_route TEXT NOT NULL,
                    expires_at TEXT,
                    created_by_actor_ref TEXT NOT NULL,
                    download_count INTEGER NOT NULL,
                    revoked_at TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE ae_artifact_retention_executions (
                    retention_execution_id TEXT PRIMARY KEY,
                    execution_history_schema_version TEXT NOT NULL,
                    artifact_retention_execution_schema_version TEXT NOT NULL,
                    policy_id TEXT NOT NULL,
                    service_id TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    execution_status TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL,
                    retention_days_after_logical_purge INTEGER NOT NULL,
                    as_of TEXT NOT NULL,
                    cutoff_at TEXT NOT NULL,
                    checked_at TEXT NOT NULL,
                    scan_limit INTEGER NOT NULL,
                    max_delete_count INTEGER NOT NULL,
                    candidate_count INTEGER NOT NULL,
                    selected_count INTEGER NOT NULL,
                    delete_enabled INTEGER NOT NULL,
                    storage_mutation_enabled INTEGER NOT NULL,
                    database_row_delete_enabled INTEGER NOT NULL,
                    deleted_counts TEXT NOT NULL,
                    requested_by TEXT NOT NULL,
                    idempotency_key TEXT,
                    trace_id TEXT,
                    request_id TEXT,
                    blocked_reason TEXT,
                    error TEXT,
                    audit TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    execution TEXT NOT NULL,
                    execution_payload_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (
                        tenant_id,
                        workspace_id,
                        owner_user_id,
                        idempotency_key
                    )
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE service_jobs (
                    job_id TEXT PRIMARY KEY,
                    job_schema_version TEXT NOT NULL,
                    job_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    subject_type TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL,
                    max_attempts INTEGER NOT NULL,
                    retryable INTEGER NOT NULL,
                    links TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    error TEXT,
                    replay_lineage TEXT,
                    available_at TEXT NOT NULL,
                    locked_at TEXT,
                    locked_by TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (job_type, idempotency_key)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE service_worker_heartbeats (
                    service_id TEXT NOT NULL,
                    worker_id TEXT NOT NULL,
                    heartbeat_schema_version TEXT NOT NULL,
                    worker_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    active_job_id TEXT,
                    trace_id TEXT,
                    started_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (service_id, worker_id)
                )
                """
            )
        )
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def test_build_artifact_handoff_record_copies_only_safe_lineage() -> None:
    record = build_artifact_handoff_record(
        source_payload=artifact_payload(),
        generation_record=sample_generation_record(),
        structured_draft=sample_structured_draft(),
        artifact_request_id=None,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert record["handoff_schema_version"] == "ae_artifact_handoff.v1"
    assert record["handoff_status"] == "READY_FOR_RENDERING"
    assert record["artifact_title"] == "Generated report"
    assert record["target_formats"] == ["MD", "HTML_PREVIEW", "DOCX", "PDF"]
    assert record["structured_draft_content_hash"] == "c" * 64
    assert len(record["citation_claims_hash"]) == 64
    assert len(record["validation_result_hash"]) == 64
    assert record["quality_summary"]["evidence_ref_count"] == 2
    assert "raw prompt" not in str(record).lower()
    assert "/data/nex-platform" not in str(record)


def test_build_artifact_record_from_handoff_creates_safe_record_family() -> None:
    record = build_artifact_record_from_handoff(
        source_payload={"artifact_type": "summary", "display_title": "Brief report"},
        handoff_record=sample_handoff_record(),
        artifact_request_id="artifact-create-001",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert record["artifact_schema_version"] == "ae_artifact_record.v1"
    assert record["artifact_type"] == "summary"
    assert record["artifact_status"] == "DRAFT"
    assert record["current_version_id"] is None
    assert record["display_title"] == "Brief report"
    assert record["handoff_ref"]["artifact_request_id"] == "artifact-request-001"
    assert record["source_refs"][0]["cx_generation_id"] == "cx-gen-001"
    assert record["source_refs"][0]["source_anchor_count"] == 2
    assert record["versions"] == []
    assert record["render_jobs"] == []
    assert record["files"] == []
    assert record["links"] == []
    assert "Safe summary." not in str(record)
    assert "/data/nex-platform" not in str(record)


def test_build_artifact_record_uses_required_request_id_and_validates_handoff() -> None:
    record = build_artifact_record_from_handoff(
        source_payload={"artifact_request_id": "artifact-create-001"},
        handoff_record=sample_handoff_record(),
        artifact_request_id=None,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    assert record["artifact_type"] == "generated_document"

    with pytest.raises(ArtifactHandoffError) as request_exc:
        build_artifact_record_from_handoff(
            source_payload={},
            handoff_record=sample_handoff_record(),
            artifact_request_id=None,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    assert request_exc.value.error_code == "ae.artifact_request_id_required"

    broken_handoff = {**sample_handoff_record(), "handoff_status": "FAILED"}
    with pytest.raises(ArtifactHandoffError) as handoff_exc:
        validate_artifact_handoff_record(broken_handoff)
    assert handoff_exc.value.error_code == "ae.artifact_handoff_not_ready"

    missing_field = dict(sample_handoff_record())
    del missing_field["quality_summary"]
    with pytest.raises(ArtifactHandoffError) as missing_exc:
        validate_artifact_handoff_record(missing_field)
    assert missing_exc.value.error_code == "ae.artifact_handoff_invalid"


def test_markdown_renderer_uses_safe_draft_previews_and_citations() -> None:
    markdown = render_markdown_from_structured_draft(sample_structured_draft())

    assert markdown.startswith("# Grounded report")
    assert "## Overview" in markdown
    assert "Grounded answer [1]." in markdown
    assert "Second finding [2]." in markdown
    assert "## Citations" in markdown
    assert "`evidence-001`" in markdown
    assert "/data/nex-platform" not in markdown


def test_build_markdown_render_result_creates_version_and_completed_job() -> None:
    artifact_record = build_artifact_record_from_handoff(
        source_payload={"artifact_request_id": "artifact-create-001"},
        handoff_record=sample_handoff_record(),
        artifact_request_id=None,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    render_job_id = deterministic_render_job_id(
        artifact_record["artifact_id"],
        "render-request-001",
    )

    result = build_markdown_render_result(
        artifact_record=artifact_record,
        structured_draft=sample_structured_draft(),
        target_formats=["MD"],
        render_request_id="render-request-001",
        render_job_id=render_job_id,
    )

    assert result["render_request_id"] == "render-request-001"
    assert result["render_job"]["render_job_id"] == render_job_id
    assert result["render_job"]["job_status"] == "COMPLETED"
    assert result["render_job"]["progress_percent"] == 100
    assert result["artifact_version"]["version_no"] == 1
    assert result["artifact_version"]["version_reason"] == "initial_render"
    assert result["artifact_version"]["rendered_formats"] == ["MD"]
    assert len(result["artifact_version"]["artifact_content_hash"]) == 64
    assert result["artifact_files"][0]["format"] == "MD"
    assert result["artifact_files"][0]["storage_ref"].startswith("ae://artifacts/")
    assert result["artifact_links"][0]["link_type"] == "preview"
    assert result["artifact_links"][1]["link_type"] == "download"
    assert result["markdown"].startswith("# Grounded report")


def test_artifact_file_metadata_helpers_create_safe_routes_and_refs() -> None:
    artifact_record = build_artifact_record_from_handoff(
        source_payload={
            "artifact_request_id": "artifact-create-001",
            "display_title": "Generated Report: 2026/08",
        },
        handoff_record=sample_handoff_record(),
        artifact_request_id=None,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    render_result = build_markdown_render_result(
        artifact_record=artifact_record,
        structured_draft=sample_structured_draft(),
        target_formats=["MD"],
        render_request_id="render-request-001",
        render_job_id=deterministic_render_job_id(
            artifact_record["artifact_id"],
            "render-request-001",
        ),
    )
    artifact_file = build_markdown_artifact_files(
        artifact_record=artifact_record,
        artifact_version=render_result["artifact_version"],
        markdown=render_result["markdown"],
    )[0]
    links = build_artifact_links(
        artifact_file=artifact_file,
        created_by_actor_ref=artifact_record["owner_actor_ref"],
        created_at=render_result["artifact_version"]["created_at"],
    )

    assert safe_file_stem("한글 제목") == "artifact"
    assert artifact_file["file_name"] == "generated-report-2026-08.md"
    assert artifact_file["storage_ref"].startswith("ae://artifacts/")
    assert "/data/nex-platform" not in artifact_file["storage_ref"]
    assert {link["link_type"] for link in links} == {"preview", "download"}
    assert all(link["link_route"].startswith("/api/v1/artifact-files/") for link in links)
    assert all(link["access_policy"] == "owner_only" for link in links)


def test_artifact_transformer_catalog_and_format_helpers_are_explicit() -> None:
    assert set(ae_artifacts.ARTIFACT_TRANSFORMER_CATALOG) == {
        "MD",
        "HTML_PREVIEW",
        "DOCX",
        "PDF",
    }
    assert ae_artifacts.IMPLEMENTED_RENDER_FORMATS == {
        "MD",
        "HTML_PREVIEW",
        "DOCX",
        "PDF",
    }
    assert artifact_format_spec("MD")["render_stage"] == "MARKDOWN_RENDERING"
    assert artifact_format_spec("DOCX")["content_kind"] == "binary"
    assert artifact_mime_type("HTML_PREVIEW") == "text/html"
    assert artifact_file_extension("PDF") == "pdf"
    assert artifact_content_kind("DOCX") == "binary"
    assert artifact_file_name_for_format("Generated Report: 2026/08", "DOCX") == (
        "generated-report-2026-08.docx"
    )

    with pytest.raises(ArtifactHandoffError) as exc_info:
        artifact_format_spec("TXT")
    assert exc_info.value.error_code == "ae.render_format_unsupported"


def test_render_target_formats_allows_all_materialized_formats() -> None:
    artifact_record = build_artifact_record_from_handoff(
        source_payload={"artifact_request_id": "artifact-create-001"},
        handoff_record=sample_handoff_record(),
        artifact_request_id=None,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert render_target_formats_from_payload({}, artifact_record) == ["MD"]
    assert render_target_formats_from_payload(
        {"target_formats": ["MD", "HTML_PREVIEW", "MD"]},
        artifact_record,
    ) == ["MD", "HTML_PREVIEW"]
    assert render_target_formats_from_payload(
        {"target_formats": ["DOCX", "HTML_PREVIEW"]},
        artifact_record,
    ) == ["DOCX", "HTML_PREVIEW"]
    assert render_target_formats_from_payload(
        {"target_formats": ["PDF", "MD", "PDF"]},
        artifact_record,
    ) == ["PDF", "MD"]

    with pytest.raises(ArtifactHandoffError) as empty_exc:
        render_target_formats_from_payload({"target_formats": []}, artifact_record)
    assert empty_exc.value.error_code == "ae.target_formats_invalid"

    with pytest.raises(ArtifactHandoffError) as unknown_exc:
        render_target_formats_from_payload({"target_formats": ["TXT"]}, artifact_record)
    assert unknown_exc.value.error_code == "ae.render_format_unsupported"

    markdown_only_record = {**artifact_record, "target_formats": ["MD"]}
    with pytest.raises(ArtifactHandoffError) as not_requested_exc:
        render_target_formats_from_payload(
            {"target_formats": ["HTML_PREVIEW"]},
            markdown_only_record,
        )
    assert not_requested_exc.value.error_code == "ae.render_format_not_requested"


def test_render_stage_sequence_uses_canonical_multi_format_order() -> None:
    assert ae_artifacts.MULTI_FORMAT_RENDER_STAGE_ORDER == (
        "HANDOFF_VALIDATING",
        "MARKDOWN_RENDERING",
        "HTML_PREVIEW_RENDERING",
        "DOCX_RENDERING",
        "PDF_RENDERING",
        "LINK_CREATING",
        "FINALIZING",
    )
    assert render_stage_sequence_for_formats(["PDF", "MD", "HTML_PREVIEW"]) == [
        "HANDOFF_VALIDATING",
        "MARKDOWN_RENDERING",
        "HTML_PREVIEW_RENDERING",
        "PDF_RENDERING",
        "LINK_CREATING",
        "FINALIZING",
    ]


def test_html_preview_materializer_escapes_markdown_and_lists() -> None:
    html_preview = render_html_preview_from_markdown(
        "# Report <x>\n"
        "\n"
        "Intro <script>bad</script>\n"
        "\n"
        "## Findings\n"
        "\n"
        "- item <one>\n"
        "- item two\n"
    )

    assert html_preview.startswith("<!doctype html>")
    assert '<html lang="ko">' in html_preview
    assert "<h1>Report &lt;x&gt;</h1>" in html_preview
    assert "<h2>Findings</h2>" in html_preview
    assert "<ul>" in html_preview
    assert "<li>item &lt;one&gt;</li>" in html_preview
    assert "<script>" not in html_preview
    assert "&lt;script&gt;bad&lt;/script&gt;" in html_preview
    assert html_preview.endswith("</html>\n")


def test_markdown_render_result_materializes_html_preview_file() -> None:
    artifact_record = build_artifact_record_from_handoff(
        source_payload={"artifact_request_id": "artifact-create-001"},
        handoff_record=sample_handoff_record(),
        artifact_request_id=None,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    result = build_markdown_render_result(
        artifact_record=artifact_record,
        structured_draft=sample_structured_draft(),
        target_formats=["MD", "HTML_PREVIEW"],
        render_request_id="render-request-001",
        render_job_id=deterministic_render_job_id(
            artifact_record["artifact_id"],
            "render-request-001",
        ),
    )
    html_file = next(
        artifact_file
        for artifact_file in result["artifact_files"]
        if artifact_file["format"] == "HTML_PREVIEW"
    )
    html_preview = result["rendered_payloads"]["HTML_PREVIEW"].decode("utf-8")
    html_helper_file = build_html_preview_artifact_file(
        artifact_record=artifact_record,
        artifact_version=result["artifact_version"],
        html_preview=html_preview,
    )
    links = build_artifact_links_for_files(
        artifact_files=result["artifact_files"],
        created_by_actor_ref=artifact_record["owner_actor_ref"],
        created_at=result["artifact_version"]["created_at"],
    )

    assert result["artifact_version"]["rendered_formats"] == ["MD", "HTML_PREVIEW"]
    assert [artifact_file["format"] for artifact_file in result["artifact_files"]] == [
        "MD",
        "HTML_PREVIEW",
    ]
    assert set(result["rendered_payloads"]) == {"MD", "HTML_PREVIEW"}
    assert html_file["mime_type"] == "text/html"
    assert html_file["file_name"].endswith(".html")
    assert html_file["file_hash"] == sha256_bytes(
        result["rendered_payloads"]["HTML_PREVIEW"]
    )
    assert html_helper_file == html_file
    assert len(result["artifact_links"]) == 4
    assert links == result["artifact_links"]
    assert "<article class=\"ae-artifact-preview\">" in html_preview


def test_docx_export_materializer_builds_ooxml_bytes() -> None:
    docx_payload = render_docx_export_from_markdown(
        "# Report <x>\n"
        "\n"
        "Intro paragraph.\n"
        "\n"
        "## Findings\n"
        "\n"
        "- first item\n"
        "- second item\n"
    )

    assert docx_payload.startswith(b"PK")
    with ZipFile(BytesIO(docx_payload)) as archive:
        names = set(archive.namelist())
        document_xml = archive.read("word/document.xml").decode("utf-8")

    assert "word/document.xml" in names
    assert "Report &lt;x&gt;" in document_xml
    assert "Intro paragraph." in document_xml
    assert "Findings" in document_xml
    assert "first item" in document_xml
    assert "/data/nex-platform" not in document_xml


def test_markdown_render_result_materializes_docx_file() -> None:
    artifact_record = build_artifact_record_from_handoff(
        source_payload={"artifact_request_id": "artifact-create-001"},
        handoff_record=sample_handoff_record(),
        artifact_request_id=None,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    result = build_markdown_render_result(
        artifact_record=artifact_record,
        structured_draft=sample_structured_draft(),
        target_formats=["MD", "DOCX"],
        render_request_id="render-request-001",
        render_job_id=deterministic_render_job_id(
            artifact_record["artifact_id"],
            "render-request-001",
        ),
    )
    docx_file = next(
        artifact_file
        for artifact_file in result["artifact_files"]
        if artifact_file["format"] == "DOCX"
    )
    helper_file = build_docx_export_artifact_file(
        artifact_record=artifact_record,
        artifact_version=result["artifact_version"],
        docx_payload=result["rendered_payloads"]["DOCX"],
    )

    assert result["artifact_version"]["rendered_formats"] == ["MD", "DOCX"]
    assert set(result["rendered_payloads"]) == {"MD", "DOCX"}
    assert docx_file["mime_type"] == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert docx_file["file_name"].endswith(".docx")
    assert docx_file["file_size_bytes"] == len(result["rendered_payloads"]["DOCX"])
    assert docx_file["file_hash"] == sha256_bytes(result["rendered_payloads"]["DOCX"])
    assert helper_file == docx_file


def test_pdf_export_materializer_builds_readable_pdf_bytes() -> None:
    pdf_payload = render_pdf_export_from_markdown(
        "# Report (Q3)\n"
        "\n"
        "Intro paragraph with safe ASCII text.\n"
        "\n"
        "## Findings\n"
        "\n"
        "- first item\n"
        "- second item\n"
    )
    reader = pypdf.PdfReader(BytesIO(pdf_payload))
    extracted = "\n".join(page.extract_text() or "" for page in reader.pages)

    assert pdf_payload.startswith(b"%PDF-1.4")
    assert len(reader.pages) == 1
    assert "Report (Q3)" in extracted
    assert "Intro paragraph" in extracted
    assert "first item" in extracted
    assert "/data/nex-platform" not in extracted


def test_markdown_render_result_materializes_pdf_file() -> None:
    artifact_record = build_artifact_record_from_handoff(
        source_payload={"artifact_request_id": "artifact-create-001"},
        handoff_record=sample_handoff_record(),
        artifact_request_id=None,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    result = build_markdown_render_result(
        artifact_record=artifact_record,
        structured_draft=sample_structured_draft(),
        target_formats=["MD", "HTML_PREVIEW", "DOCX", "PDF"],
        render_request_id="render-request-001",
        render_job_id=deterministic_render_job_id(
            artifact_record["artifact_id"],
            "render-request-001",
        ),
    )
    pdf_file = next(
        artifact_file
        for artifact_file in result["artifact_files"]
        if artifact_file["format"] == "PDF"
    )
    helper_file = build_pdf_export_artifact_file(
        artifact_record=artifact_record,
        artifact_version=result["artifact_version"],
        pdf_payload=result["rendered_payloads"]["PDF"],
    )
    policy_hash_for_pdf_only = build_markdown_render_result(
        artifact_record=artifact_record,
        structured_draft=sample_structured_draft(),
        target_formats=["PDF"],
        render_request_id="render-request-002",
        render_job_id=deterministic_render_job_id(
            artifact_record["artifact_id"],
            "render-request-002",
        ),
    )["artifact_version"]["render_policy_hash"]

    assert result["artifact_version"]["rendered_formats"] == [
        "MD",
        "HTML_PREVIEW",
        "DOCX",
        "PDF",
    ]
    assert set(result["rendered_payloads"]) == {"MD", "HTML_PREVIEW", "DOCX", "PDF"}
    assert pdf_file["mime_type"] == "application/pdf"
    assert pdf_file["file_name"].endswith(".pdf")
    assert pdf_file["file_size_bytes"] == len(result["rendered_payloads"]["PDF"])
    assert pdf_file["file_hash"] == sha256_bytes(result["rendered_payloads"]["PDF"])
    assert helper_file == pdf_file
    assert len(result["artifact_links"]) == 8
    assert policy_hash_for_pdf_only != result["artifact_version"]["render_policy_hash"]


def test_rendered_payload_builders_report_missing_payload() -> None:
    artifact_record = build_artifact_record_from_handoff(
        source_payload={"artifact_request_id": "artifact-create-001"},
        handoff_record=sample_handoff_record(),
        artifact_request_id=None,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    render_result = build_markdown_render_result(
        artifact_record=artifact_record,
        structured_draft=sample_structured_draft(),
        target_formats=["MD"],
        render_request_id="render-request-001",
        render_job_id=deterministic_render_job_id(
            artifact_record["artifact_id"],
            "render-request-001",
        ),
    )

    with pytest.raises(ArtifactHandoffError) as exc_info:
        ae_artifacts.build_rendered_artifact_files_from_payloads(
            artifact_record=artifact_record,
            artifact_version=render_result["artifact_version"],
            target_formats=["PDF"],
            rendered_payloads=build_rendered_payloads_from_markdown(
                render_result["markdown"],
                ["MD"],
            ),
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.error_code == "ae.render_payload_missing"


def test_build_rendered_artifact_file_uses_format_catalog_and_bytes_hash() -> None:
    artifact_record = build_artifact_record_from_handoff(
        source_payload={
            "artifact_request_id": "artifact-create-001",
            "display_title": "Generated Report: 2026/08",
        },
        handoff_record=sample_handoff_record(),
        artifact_request_id=None,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    render_result = build_markdown_render_result(
        artifact_record=artifact_record,
        structured_draft=sample_structured_draft(),
        target_formats=["MD"],
        render_request_id="render-request-001",
        render_job_id=deterministic_render_job_id(
            artifact_record["artifact_id"],
            "render-request-001",
        ),
    )
    payload = b"%PDF-safe-future-export"

    artifact_file = build_rendered_artifact_file(
        artifact_record=artifact_record,
        artifact_version=render_result["artifact_version"],
        target_format="PDF",
        payload=payload,
    )

    assert artifact_file["format"] == "PDF"
    assert artifact_file["mime_type"] == "application/pdf"
    assert artifact_file["file_name"] == "generated-report-2026-08.pdf"
    assert artifact_file["file_size_bytes"] == len(payload)
    assert artifact_file["file_hash"] == sha256_bytes(payload)
    assert artifact_file["source_version_hash"] == render_result["artifact_version"][
        "artifact_content_hash"
    ]
    assert artifact_file["storage_ref"].endswith("/generated-report-2026-08.pdf")
    assert "/data/nex-platform" not in artifact_file["storage_ref"]


def test_format_neutral_storage_round_trips_text_and_binary_payloads(tmp_path) -> None:
    artifact_record = build_artifact_record_from_handoff(
        source_payload={"artifact_request_id": "artifact-create-001"},
        handoff_record=sample_handoff_record(),
        artifact_request_id=None,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    render_result = build_markdown_render_result(
        artifact_record=artifact_record,
        structured_draft=sample_structured_draft(),
        target_formats=["MD"],
        render_request_id="render-request-001",
        render_job_id=deterministic_render_job_id(
            artifact_record["artifact_id"],
            "render-request-001",
        ),
    )
    markdown_file = render_result["artifact_files"][0]
    pdf_file = build_rendered_artifact_file(
        artifact_record=artifact_record,
        artifact_version=render_result["artifact_version"],
        target_format="PDF",
        payload=b"%PDF-safe",
    )
    memory_storage = InMemoryRenderedArtifactStorage()
    local_storage = LocalRenderedArtifactStorage(tmp_path / "artifact-storage")

    assert memory_storage.save_rendered_artifact_file(pdf_file, b"%PDF-safe") == (
        pdf_file["storage_ref"]
    )
    assert memory_storage.get_rendered_artifact_file(pdf_file) == b"%PDF-safe"
    assert memory_storage.save_markdown(markdown_file, render_result["markdown"]) == (
        markdown_file["storage_ref"]
    )
    assert memory_storage.get_rendered_artifact_file(markdown_file) == (
        render_result["markdown"].encode("utf-8")
    )
    assert memory_storage.get_markdown(markdown_file) == render_result["markdown"]

    assert local_storage.get_rendered_artifact_file(pdf_file) is None
    assert local_storage.save_rendered_artifact_file(pdf_file, b"%PDF-safe") == (
        pdf_file["storage_ref"]
    )
    assert local_storage.get_rendered_artifact_file(pdf_file) == b"%PDF-safe"
    assert local_storage.save_markdown(markdown_file, render_result["markdown"]) == (
        markdown_file["storage_ref"]
    )
    assert local_storage.get_markdown(markdown_file) == render_result["markdown"]
    assert list((tmp_path / "artifact-storage").rglob("*.pdf"))
    assert list((tmp_path / "artifact-storage").rglob("*.md"))


def test_artifact_record_store_keeps_format_neutral_payloads_private() -> None:
    store = ArtifactRecordStore()
    artifact_record = build_artifact_record_from_handoff(
        source_payload={"artifact_request_id": "artifact-create-001"},
        handoff_record=sample_handoff_record(),
        artifact_request_id=None,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    store.create(artifact_record)
    render_result = build_markdown_render_result(
        artifact_record=artifact_record,
        structured_draft=sample_structured_draft(),
        target_formats=["MD"],
        render_request_id="render-request-001",
        render_job_id=deterministic_render_job_id(
            artifact_record["artifact_id"],
            "render-request-001",
        ),
    )
    artifact_file = render_result["artifact_files"][0]

    updated = store.apply_markdown_render(
        artifact_id=artifact_record["artifact_id"],
        artifact_version=render_result["artifact_version"],
        render_job=render_result["render_job"],
        markdown=render_result["markdown"],
        artifact_files=render_result["artifact_files"],
        artifact_links=render_result["artifact_links"],
        rendered_payloads={"MD": render_result["markdown"].encode("utf-8")},
    )
    file_payload = resolve_rendered_artifact_file_payload(
        store,
        artifact_file_id=artifact_file["artifact_file_id"],
        link_type="download",
    )

    assert updated["files"][0] == artifact_file
    assert store.get_rendered_artifact_file(artifact_file) == (
        render_result["markdown"].encode("utf-8")
    )
    assert file_payload[2] == render_result["markdown"].encode("utf-8")
    assert render_result["markdown"] not in str(updated)


def test_artifact_collection_item_summarizes_rendered_record_without_payloads() -> None:
    store = ArtifactRecordStore()
    artifact_record = sample_collection_artifact_record(
        artifact_request_id="collection-ready-001",
        display_title="Ready collection report",
    )
    store.create(artifact_record)
    render_result = build_markdown_render_result(
        artifact_record=artifact_record,
        structured_draft=sample_structured_draft(),
        target_formats=["MD", "HTML_PREVIEW", "DOCX"],
        render_request_id="render-request-collection-001",
        render_job_id=deterministic_render_job_id(
            artifact_record["artifact_id"],
            "render-request-collection-001",
        ),
    )
    updated = store.apply_markdown_render(
        artifact_id=artifact_record["artifact_id"],
        artifact_version=render_result["artifact_version"],
        render_job=render_result["render_job"],
        markdown=render_result["markdown"],
        artifact_files=render_result["artifact_files"],
        artifact_links=render_result["artifact_links"],
        rendered_payloads=render_result["rendered_payloads"],
    )

    item = build_artifact_collection_item(updated)
    serialized = json.dumps(item, ensure_ascii=False)

    assert item["artifact_collection_item_schema_version"] == (
        ARTIFACT_COLLECTION_ITEM_SCHEMA_VERSION
    )
    assert item["artifact_id"] == updated["artifact_id"]
    assert item["artifact_status"] == "READY"
    assert item["available_formats"] == ["DOCX", "HTML_PREVIEW", "MD"]
    assert item["downloadable_formats"] == ["DOCX", "HTML_PREVIEW", "MD"]
    assert item["previewable_formats"] == ["DOCX", "HTML_PREVIEW", "MD"]
    assert item["current_version_no"] == 1
    assert item["version_count"] == 1
    assert item["file_count"] == 3
    assert item["link_count"] == 6
    assert item["render_job_count"] == 1
    assert item["latest_render_job"]["job_status"] == "COMPLETED"
    assert item["source_summary"]["cx_generation_id"] == "cx-gen-001"
    assert item["quality_summary"]["citation_status"] == "VALIDATED"
    assert item["routes"] == {
        "detail": f"/api/v1/artifacts/{updated['artifact_id']}",
        "versions": f"/api/v1/artifacts/{updated['artifact_id']}/versions",
    }
    assert "storage_ref" not in serialized
    assert "rendered_payloads" not in serialized
    assert render_result["markdown"] not in serialized


def test_artifact_collection_filter_normalizes_scope_status_and_limit() -> None:
    collection_filter = build_artifact_collection_filter(
        tenant_id=" tenant-001 ",
        workspace_id=" workspace-001 ",
        owner_user_id=" user-001 ",
        status="ready",
        limit="2",
    )

    assert collection_filter == {
        "tenant_id": "tenant-001",
        "workspace_id": "workspace-001",
        "owner_user_id": "user-001",
        "status": "READY",
        "limit": 2,
    }
    assert normalize_artifact_collection_limit(None) == 20

    with pytest.raises(ArtifactHandoffError) as scope_exc:
        build_artifact_collection_filter(
            tenant_id="",
            workspace_id="workspace-001",
            owner_user_id="user-001",
        )
    assert scope_exc.value.error_code == "ae.artifact_collection_scope_required"

    with pytest.raises(ArtifactHandoffError) as status_exc:
        build_artifact_collection_filter(
            tenant_id="tenant-001",
            workspace_id="workspace-001",
            owner_user_id="user-001",
            status="MISSING",
        )
    assert status_exc.value.error_code == "ae.artifact_collection_status_invalid"

    for bad_limit in (0, 101, True, "many"):
        with pytest.raises(ArtifactHandoffError) as limit_exc:
            normalize_artifact_collection_limit(bad_limit)
        assert limit_exc.value.error_code == "ae.artifact_collection_limit_invalid"


def test_artifact_lifecycle_action_request_builds_safe_archive_contract() -> None:
    artifact_record = sample_collection_artifact_record(
        artifact_request_id="lifecycle-ready-001",
        artifact_status="READY",
    )

    action_request = build_artifact_lifecycle_action_request(
        payload={
            "action": "archive",
            "reason_code": "user_requested",
            "comment": "Keep it out of the active library.",
        },
        artifact_record=artifact_record,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="lifecycle-archive-001",
    )
    archived_record = {**artifact_record, "artifact_status": "ARCHIVED"}
    result = build_artifact_lifecycle_action_result(
        action_request=action_request,
        artifact_record=archived_record,
    )
    serialized = json.dumps(result, ensure_ascii=False)

    assert action_request["artifact_lifecycle_action_schema_version"] == (
        AE_ARTIFACT_LIFECYCLE_ACTION_SCHEMA_VERSION
    )
    assert action_request["action"] == "ARCHIVE"
    assert action_request["previous_status"] == "READY"
    assert action_request["target_status"] == "ARCHIVED"
    assert action_request["comment_hash"] == ae_artifacts.sha256_text(
        "Keep it out of the active library."
    )
    assert action_request["comment_length"] == 34
    assert action_request["metadata"] == {
        "physical_delete_requested": False,
        "storage_mutation_requested": False,
        "raw_comment_included": False,
    }
    assert result["artifact_lifecycle_action_result_schema_version"] == (
        AE_ARTIFACT_LIFECYCLE_ACTION_RESULT_SCHEMA_VERSION
    )
    assert result["transition_applied"] is True
    assert result["metadata"]["physical_delete_executed"] is False
    assert "Keep it out of the active library." not in serialized
    assert "storage_ref" not in serialized


def test_artifact_lifecycle_action_request_supports_restore_and_delete_paths() -> None:
    archived_record = sample_collection_artifact_record(
        artifact_request_id="lifecycle-archived-001",
        artifact_status="ARCHIVED",
    )
    deleted_record = sample_collection_artifact_record(
        artifact_request_id="lifecycle-deleted-001",
        artifact_status="DELETED",
    )

    restore = build_artifact_lifecycle_action_request(
        payload={"action": "restore", "restore_status": "failed"},
        artifact_record=archived_record,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    mark_deleted = build_artifact_lifecycle_action_request(
        payload={"lifecycle_action": "mark-deleted"},
        artifact_record=deleted_record,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    fallback_actor = ae_artifacts.lifecycle_actor_ref_from_payload(
        {},
        {**archived_record, "owner_actor_ref": "not-a-dict"},
    )

    assert normalize_artifact_lifecycle_action("mark-deleted") == "MARK_DELETED"
    assert normalize_artifact_restore_status("ready") == "READY"
    assert normalize_artifact_restore_status(None) is None
    assert restore["target_status"] == "FAILED"
    assert mark_deleted["target_status"] == "DELETED"
    assert fallback_actor == {
        "actor_type": "user",
        "actor_id": "local-user",
        "tenant_id": "local-tenant",
    }


def test_artifact_lifecycle_action_contract_covers_idempotent_and_actor_paths() -> None:
    archived_record = sample_collection_artifact_record(
        artifact_request_id="lifecycle-idempotent-archive-001",
        artifact_status="ARCHIVED",
    )
    deleted_record = sample_collection_artifact_record(
        artifact_request_id="lifecycle-idempotent-delete-001",
        artifact_status="DELETED",
    )

    archived_again = build_artifact_lifecycle_action_request(
        payload={
            "action": "ARCHIVE",
            "artifact_id": archived_record["artifact_id"],
            "idempotency_key": "archive-again-001",
            "actor_ref": {
                "actor_type": "operator",
                "actor_id": "operator-001",
            },
        },
        artifact_record=archived_record,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    deleted_again = build_artifact_lifecycle_action_request(
        payload={"action": "MARK_DELETED", "lifecycle_action_request_id": "delete-001"},
        artifact_record=deleted_record,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    restored_default = build_artifact_lifecycle_action_request(
        payload={"action": "RESTORE"},
        artifact_record=deleted_record,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    unapplied_result = build_artifact_lifecycle_action_result(
        action_request=archived_again,
        artifact_record={**archived_record, "artifact_status": "READY"},
    )

    assert archived_again["target_status"] == "ARCHIVED"
    assert archived_again["actor_ref"] == {
        "actor_type": "operator",
        "actor_id": "operator-001",
        "tenant_id": "tenant-001",
    }
    assert archived_again["idempotency_key"] == "archive-again-001"
    assert deleted_again["target_status"] == "DELETED"
    assert deleted_again["idempotency_key"] == "delete-001"
    assert restored_default["target_status"] == "READY"
    assert unapplied_result["transition_applied"] is False


def test_artifact_lifecycle_action_request_rejects_invalid_inputs() -> None:
    ready_record = sample_collection_artifact_record(
        artifact_request_id="lifecycle-invalid-001",
        artifact_status="READY",
    )
    rendering_record = {
        **ready_record,
        "artifact_status": "RENDERING",
    }
    archived_record = {
        **ready_record,
        "artifact_status": "ARCHIVED",
    }

    invalid_cases = [
        (
            {},
            ready_record,
            "ae.artifact_lifecycle_action_required",
        ),
        (
            {"action": "PURGE_STORAGE"},
            ready_record,
            "ae.artifact_lifecycle_action_invalid",
        ),
        (
            {"artifact_id": "other-artifact", "action": "ARCHIVE"},
            ready_record,
            "ae.artifact_lifecycle_artifact_mismatch",
        ),
        (
            {"action": "ARCHIVE"},
            rendering_record,
            "ae.artifact_lifecycle_transition_invalid",
        ),
        (
            {"action": "MARK_DELETED"},
            rendering_record,
            "ae.artifact_lifecycle_transition_invalid",
        ),
        (
            {"action": "RESTORE"},
            ready_record,
            "ae.artifact_lifecycle_transition_invalid",
        ),
        (
            {"action": "RESTORE", "restore_status": "ARCHIVED"},
            archived_record,
            "ae.artifact_lifecycle_restore_status_invalid",
        ),
    ]

    for payload, record, expected_code in invalid_cases:
        with pytest.raises(ArtifactHandoffError) as exc:
            build_artifact_lifecycle_action_request(
                payload=payload,
                artifact_record=record,
                request_id=REQUEST_ID,
                trace_id=TRACE_ID,
            )
        assert exc.value.error_code == expected_code

    with pytest.raises(ArtifactHandoffError) as status_exc:
        ae_artifacts.artifact_lifecycle_target_status(
            current_status="UNKNOWN",
            action="ARCHIVE",
        )
    assert status_exc.value.error_code == "ae.artifact_lifecycle_current_status_invalid"

    action_request = build_artifact_lifecycle_action_request(
        payload={"action": "ARCHIVE"},
        artifact_record=ready_record,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    action_request["artifact_lifecycle_action_schema_version"] = "wrong"
    with pytest.raises(ArtifactHandoffError) as schema_exc:
        ae_artifacts.validate_artifact_lifecycle_action_request(action_request)
    assert schema_exc.value.error_code == "ae.artifact_lifecycle_schema_invalid"

    action_request = build_artifact_lifecycle_action_request(
        payload={"action": "ARCHIVE"},
        artifact_record=ready_record,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    action_request["target_status"] = "READY"
    with pytest.raises(ArtifactHandoffError) as mismatch_exc:
        ae_artifacts.validate_artifact_lifecycle_action_request(action_request)
    assert mismatch_exc.value.error_code == "ae.artifact_lifecycle_target_status_mismatch"

    with pytest.raises(ArtifactHandoffError) as unsafe_exc:
        ae_artifacts.assert_artifact_lifecycle_payload_safe(
            {"comment_text": "raw private reason"}
        )
    assert unsafe_exc.value.error_code == "ae.artifact_lifecycle_payload_unsafe"


def test_artifact_lifecycle_action_applies_to_in_memory_store() -> None:
    store = ArtifactRecordStore()
    ready_record = sample_collection_artifact_record(
        artifact_request_id="lifecycle-store-ready-001",
        artifact_status="READY",
    )
    store.save(ready_record)
    action_request = build_artifact_lifecycle_action_request(
        payload={"action": "ARCHIVE"},
        artifact_record=ready_record,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="lifecycle-store-archive-001",
    )

    result = store.apply_lifecycle_action(ready_record["artifact_id"], action_request)

    assert result["artifact_status"] == "ARCHIVED"
    assert result["transition_applied"] is True
    assert store.get(ready_record["artifact_id"])["artifact_status"] == "ARCHIVED"
    assert store.list_artifacts(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        status="ARCHIVED",
    )["count"] == 1


def test_artifact_lifecycle_action_apply_rejects_mismatch_and_missing_record() -> None:
    store = ArtifactRecordStore()
    ready_record = sample_collection_artifact_record(
        artifact_request_id="lifecycle-store-mismatch-001",
        artifact_status="READY",
    )
    store.save(ready_record)
    action_request = build_artifact_lifecycle_action_request(
        payload={"action": "ARCHIVE"},
        artifact_record=ready_record,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    stale_record = {**ready_record, "artifact_status": "FAILED"}
    with pytest.raises(ArtifactHandoffError) as stale_exc:
        apply_artifact_lifecycle_action(
            artifact_record=stale_record,
            action_request=action_request,
        )
    assert stale_exc.value.error_code == "ae.artifact_lifecycle_status_changed"

    mismatched_request = {**action_request, "artifact_id": "other-artifact"}
    with pytest.raises(ArtifactHandoffError) as mismatch_exc:
        apply_artifact_lifecycle_action(
            artifact_record=ready_record,
            action_request=mismatched_request,
        )
    assert mismatch_exc.value.error_code == "ae.artifact_lifecycle_artifact_mismatch"

    with pytest.raises(ArtifactHandoffError) as missing_exc:
        store.apply_lifecycle_action("missing-artifact", action_request)
    assert missing_exc.value.error_code == "ae.artifact_not_found"


def test_artifact_retention_policy_contract_defaults_and_presets_are_safe() -> None:
    default_policy = build_artifact_retention_policy()
    fifteen_day_policy = build_artifact_retention_policy(
        {
            "retention_policy_id": "ae-artifact-logical-purge-15d-local-v1",
            "retention_days": "15",
        }
    )
    serialized = json.dumps(default_policy, ensure_ascii=False, sort_keys=True)

    assert default_policy["artifact_retention_policy_schema_version"] == (
        AE_ARTIFACT_RETENTION_POLICY_SCHEMA_VERSION
    )
    assert default_policy["retention_policy_id"] == (
        "ae-artifact-logical-purge-30d-local-v1"
    )
    assert default_policy["logical_purge"] == {
        "enabled": True,
        "flag_field": "artifact_status",
        "flag_value": "DELETED",
        "first_action": "MARK_DELETED",
        "reversible_before_physical_purge": True,
    }
    assert default_policy["physical_purge"]["enabled"] is False
    assert default_policy["physical_purge"]["dry_run_required"] is True
    assert default_policy["physical_purge"]["storage_mutation_enabled"] is False
    assert default_policy["physical_purge"]["database_row_delete_enabled"] is False
    assert default_policy["physical_purge"][
        "retention_days_after_logical_purge"
    ] == 30
    assert default_policy["physical_purge"]["supported_retention_day_presets"] == [
        15,
        30,
    ]
    assert default_policy["physical_purge"]["batch_window"] == {
        "timezone": "Asia/Seoul",
        "start_local_time": "02:00",
        "end_local_time": "05:00",
    }
    assert default_policy["candidate_query"] == {
        "status": "DELETED",
        "timestamp_field": "updated_at",
        "metadata_only": True,
        "default_limit": 20,
        "max_limit": 100,
    }
    assert fifteen_day_policy["physical_purge"][
        "retention_days_after_logical_purge"
    ] == 15
    assert "/data/nex-platform" not in serialized
    assert "storage_ref" not in serialized


def test_artifact_retention_policy_contract_rejects_invalid_inputs() -> None:
    assert normalize_artifact_retention_days(None) == 30
    assert normalize_artifact_retention_days("30") == 30

    for bad_value in (0, 366, True, "many"):
        with pytest.raises(ArtifactHandoffError) as days_exc:
            normalize_artifact_retention_days(bad_value)
        assert days_exc.value.error_code == "ae.artifact_retention_days_invalid"

    policy = build_artifact_retention_policy()
    broken_schema = {**policy, "artifact_retention_policy_schema_version": "wrong"}
    with pytest.raises(ArtifactHandoffError) as schema_exc:
        validate_artifact_retention_policy(broken_schema)
    assert schema_exc.value.error_code == "ae.artifact_retention_policy_schema_invalid"

    for patch, expected_detail in (
        (
            {"logical_purge": {**policy["logical_purge"], "flag_field": "status"}},
            "flag field",
        ),
        (
            {"logical_purge": {**policy["logical_purge"], "flag_value": "PURGED"}},
            "flag value",
        ),
        (
            {"physical_purge": {**policy["physical_purge"], "enabled": True}},
            "disabled",
        ),
        (
            {"physical_purge": {**policy["physical_purge"], "dry_run_required": False}},
            "dry-run",
        ),
        (
            {"candidate_query": {**policy["candidate_query"], "metadata_only": False}},
            "metadata-only",
        ),
    ):
        with pytest.raises(ArtifactHandoffError) as policy_exc:
            validate_artifact_retention_policy({**policy, **patch})
        assert policy_exc.value.error_code == "ae.artifact_retention_policy_invalid"
        assert expected_detail in policy_exc.value.detail

    with pytest.raises(ArtifactHandoffError) as section_exc:
        validate_artifact_retention_policy({**policy, "logical_purge": "bad"})
    assert section_exc.value.error_code == "ae.artifact_retention_policy_invalid"

    with pytest.raises(ArtifactHandoffError) as unsafe_exc:
        ae_artifacts.assert_artifact_retention_payload_safe(
            {"storage_ref": "ae://artifacts/private"}
        )
    assert unsafe_exc.value.error_code == "ae.artifact_retention_payload_unsafe"


def test_artifact_retention_schedule_contract_defaults_are_safe() -> None:
    schedule = build_artifact_retention_schedule()
    fifteen_day_schedule = build_artifact_retention_schedule(
        {
            "schedule_id": "ae-artifact-retention-schedule-15d-local-v1",
            "retention_days": "15",
            "max_delete_count": "10",
        }
    )
    serialized = json.dumps(schedule, ensure_ascii=False, sort_keys=True)

    assert schedule["artifact_retention_schedule_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULE_SCHEMA_VERSION
    )
    assert schedule["schedule_id"] == "ae-artifact-retention-schedule-local-v1"
    assert schedule["policy_id"] == "ae-artifact-logical-purge-30d-local-v1"
    assert schedule["service_id"] == "nex-ae-api"
    assert schedule["schedule_enabled"] is False
    assert schedule["planning_enabled"] is True
    assert schedule["default_mode"] == "DRY_RUN"
    assert schedule["allowed_modes"] == ["DRY_RUN", "EXECUTE"]
    assert schedule["retention"] == {
        "logical_purge_status": "DELETED",
        "logical_purge_timestamp_field": "updated_at",
        "retention_days_after_logical_purge": 30,
        "supported_retention_day_presets": [15, 30],
    }
    assert schedule["batch_window"] == {
        "timezone": "Asia/Seoul",
        "start_local_time": "02:00",
        "end_local_time": "05:00",
    }
    assert schedule["limits"] == {
        "default_scan_limit": 20,
        "max_scan_limit": 100,
        "default_max_delete_count": 20,
        "max_delete_count": 100,
    }
    assert schedule["guardrails"] == {
        "dry_run_required_before_execute": True,
        "execute_requires_delete_enabled": True,
        "execute_requires_storage_mutation_enabled": True,
        "execute_requires_database_row_delete_enabled": True,
        "history_required_for_execute": True,
    }
    assert schedule["ownership"] == {
        "artifact_system_of_record": "nex-ae-api",
        "operator_projection_owner": "nex-ag",
        "ag_dispatch_policy": "ae_api_only",
        "ag_direct_database_write_allowed": False,
    }
    assert fifteen_day_schedule["retention"]["retention_days_after_logical_purge"] == 15
    assert fifteen_day_schedule["limits"]["default_max_delete_count"] == 10
    assert validate_artifact_retention_schedule(schedule) is None
    assert "/data/nex-platform" not in serialized
    assert "postgresql://" not in serialized


def test_artifact_retention_schedule_contract_rejects_invalid_inputs() -> None:
    schedule = build_artifact_retention_schedule()
    with pytest.raises(ArtifactHandoffError) as object_exc:
        validate_artifact_retention_schedule("bad")  # type: ignore[arg-type]
    assert object_exc.value.error_code == "ae.artifact_retention_schedule_invalid"

    broken_schema = {
        **schedule,
        "artifact_retention_schedule_schema_version": "wrong",
    }
    with pytest.raises(ArtifactHandoffError) as schema_exc:
        validate_artifact_retention_schedule(broken_schema)
    assert schema_exc.value.error_code == "ae.artifact_retention_schedule_schema_invalid"

    invalid_cases = (
        ({"service_id": "nex-cx"}, "service id"),
        ({"schedule_enabled": True}, "disabled"),
        ({"planning_enabled": False}, "planning"),
        ({"default_mode": "EXECUTE"}, "DRY_RUN"),
        ({"allowed_modes": ["EXECUTE", "DRY_RUN"]}, "modes"),
        ({"retention": "bad"}, "retention section"),
        (
            {
                "retention": {
                    **schedule["retention"],
                    "logical_purge_status": "ARCHIVED",
                }
            },
            "logical purge status",
        ),
        (
            {
                "retention": {
                    **schedule["retention"],
                    "logical_purge_timestamp_field": "created_at",
                }
            },
            "timestamp field",
        ),
        (
            {
                "retention": {
                    **schedule["retention"],
                    "supported_retention_day_presets": [30, 15],
                }
            },
            "presets",
        ),
        (
            {"batch_window": {**schedule["batch_window"], "start_local_time": "01:00"}},
            "batch window",
        ),
        (
            {"limits": {**schedule["limits"], "default_scan_limit": 10}},
            "default scan",
        ),
        (
            {"limits": {**schedule["limits"], "max_scan_limit": 50}},
            "max scan",
        ),
        (
            {"limits": {**schedule["limits"], "max_delete_count": 50}},
            "max delete",
        ),
        (
            {
                "guardrails": {
                    **schedule["guardrails"],
                    "history_required_for_execute": False,
                }
            },
            "guardrails",
        ),
        (
            {
                "ownership": {
                    **schedule["ownership"],
                    "ag_direct_database_write_allowed": True,
                }
            },
            "ownership",
        ),
    )
    for patch, detail in invalid_cases:
        with pytest.raises(ArtifactHandoffError) as invalid_exc:
            validate_artifact_retention_schedule({**schedule, **patch})
        assert invalid_exc.value.error_code == "ae.artifact_retention_schedule_invalid"
        assert detail in invalid_exc.value.detail

    with pytest.raises(ArtifactHandoffError) as unsafe_exc:
        validate_artifact_retention_schedule(
            {**schedule, "database_url": "postgresql://nex_ae_user:secret@host/db"}
        )
    assert unsafe_exc.value.error_code == "ae.artifact_retention_payload_unsafe"


def test_artifact_retention_scheduler_config_exposes_safe_runtime_surface() -> None:
    queue = InMemoryJobQueue()
    config = build_artifact_retention_scheduler_config(job_queue=queue)
    serialized = json.dumps(config, ensure_ascii=False, sort_keys=True)

    assert config["artifact_retention_scheduler_config_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_CONFIG_SCHEMA_VERSION
    )
    assert config["service_id"] == "nex-ae-api"
    assert config["scheduler_id"] == "ae-artifact-retention-scheduler-local-v1"
    assert config["policy"]["retention_policy_id"] == (
        "ae-artifact-logical-purge-30d-local-v1"
    )
    assert config["schedule"]["schedule_enabled"] is False
    assert config["job_contract"] == {
        "job_schema_version": "common_job.v1",
        "scheduled_job_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULED_JOB_SCHEMA_VERSION
        ),
        "scheduled_job_payload_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULED_JOB_PAYLOAD_SCHEMA_VERSION
        ),
        "scheduled_job_admission_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULED_JOB_ADMISSION_SCHEMA_VERSION
        ),
        "scheduled_job_enqueue_result_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULED_JOB_ENQUEUE_RESULT_SCHEMA_VERSION
        ),
        "scheduled_job_collection_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULED_JOB_COLLECTION_SCHEMA_VERSION
        ),
        "job_type": AE_ARTIFACT_RETENTION_SCHEDULED_JOB_TYPE,
        "worker_type": AE_ARTIFACT_RETENTION_SCHEDULED_WORKER_TYPE,
        "default_max_attempts": 3,
        "trigger_types": ["scheduler_tick", "operator_dispatch"],
    }
    assert config["runtime"] == {
        "scheduler_daemon_enabled": False,
        "scheduler_tick_admission_enabled": True,
        "operator_dispatch_admission_enabled": True,
        "default_execution_mode": "DRY_RUN",
        "job_queue_available": True,
        "job_queue_backend": "InMemoryJobQueue",
        "worker_runner_available": True,
        "physical_delete_automation_enabled": False,
        "automation_profile": "disabled-dry-run-local-v1",
        "scheduler_tick_interval_seconds": 900,
        "scheduler_tick_jitter_seconds": 60,
        "scheduler_tick_lock_ttl_seconds": 600,
        "scheduler_tick_stale_after_seconds": 3600,
        "scheduler_tick_max_jobs_per_tick": 1,
        "scheduler_tick_batch_window_enforced": True,
        "scheduler_tick_timezone": "Asia/Seoul",
        "scheduler_tick_window_start": "02:00",
        "scheduler_tick_window_end": "05:00",
    }
    assert config["api_routes"][
        "scheduled_job_admission"
    ] == "/api/v1/artifact-retention/scheduled-jobs/admission"
    assert config["guardrails"] == {
        "metadata_only": True,
        "dry_run_required_before_execute": True,
        "queue_admission_requires_ae_api": True,
        "ag_direct_job_enqueue_allowed": False,
        "ag_direct_database_write_allowed": False,
        "scheduler_daemon_started": False,
        "worker_execution_performed_by_admission": False,
        "storage_mutation_enabled": False,
        "database_row_delete_enabled": False,
    }
    assert validate_artifact_retention_scheduler_config(config) is config
    assert "storage_ref" not in serialized
    assert "nuri1004" not in serialized


def test_artifact_retention_scheduler_runtime_config_defaults_without_queue() -> None:
    runtime = build_artifact_retention_scheduler_runtime_config()

    assert runtime["scheduler_daemon_enabled"] is False
    assert runtime["scheduler_tick_admission_enabled"] is True
    assert runtime["job_queue_available"] is False
    assert runtime["job_queue_backend"] == "unconfigured"
    assert runtime["automation_profile"] == "disabled-dry-run-local-v1"
    assert runtime["scheduler_tick_interval_seconds"] == 900
    assert runtime["scheduler_tick_jitter_seconds"] == 60
    assert runtime["scheduler_tick_lock_ttl_seconds"] == 600
    assert runtime["scheduler_tick_stale_after_seconds"] == 3600
    assert runtime["scheduler_tick_max_jobs_per_tick"] == 1
    assert runtime["scheduler_tick_batch_window_enforced"] is True
    assert runtime["scheduler_tick_timezone"] == "Asia/Seoul"
    assert runtime["scheduler_tick_window_start"] == "02:00"
    assert runtime["scheduler_tick_window_end"] == "05:00"


def test_artifact_retention_scheduler_config_rejects_contract_drift() -> None:
    config = build_artifact_retention_scheduler_config()

    with pytest.raises(ArtifactHandoffError) as type_exc:
        validate_artifact_retention_scheduler_config([])  # type: ignore[arg-type]
    assert type_exc.value.error_code == (
        "ae.artifact_retention_scheduler_config_invalid"
    )

    invalid_cases = (
        (
            {"artifact_retention_scheduler_config_schema_version": "wrong"},
            "ae.artifact_retention_scheduler_config_schema_invalid",
            "schema version",
        ),
        (
            {"service_id": "nex-ag"},
            "ae.artifact_retention_scheduler_config_invalid",
            "service id",
        ),
        (
            {"policy": []},
            "ae.artifact_retention_policy_invalid",
            "policy",
        ),
        (
            {"job_contract": {**config["job_contract"], "job_type": "wrong"}},
            "ae.artifact_retention_scheduler_config_invalid",
            "job contract",
        ),
        (
            {"runtime": {**config["runtime"], "scheduler_daemon_enabled": True}},
            "ae.artifact_retention_scheduler_config_invalid",
            "runtime",
        ),
        (
            {"api_routes": {**config["api_routes"], "purge": "/private"}},
            "ae.artifact_retention_scheduler_config_invalid",
            "routes",
        ),
        (
            {
                "guardrails": {
                    **config["guardrails"],
                    "ag_direct_job_enqueue_allowed": True,
                }
            },
            "ae.artifact_retention_scheduler_config_invalid",
            "guardrails",
        ),
    )
    for patch, error_code, detail in invalid_cases:
        with pytest.raises(ArtifactHandoffError) as invalid_exc:
            validate_artifact_retention_scheduler_config({**config, **patch})
        assert invalid_exc.value.error_code == error_code
        assert detail in invalid_exc.value.detail


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("scheduler_daemon_enabled", True),
        ("scheduler_tick_admission_enabled", False),
        ("operator_dispatch_admission_enabled", False),
        ("default_execution_mode", "EXECUTE"),
        ("job_queue_available", "yes"),
        ("job_queue_backend", ""),
        ("worker_runner_available", False),
        ("physical_delete_automation_enabled", True),
        ("automation_profile", "enabled-local-v1"),
        ("scheduler_tick_interval_seconds", 60),
        ("scheduler_tick_jitter_seconds", 0),
        ("scheduler_tick_lock_ttl_seconds", 60),
        ("scheduler_tick_stale_after_seconds", 600),
        ("scheduler_tick_max_jobs_per_tick", 2),
        ("scheduler_tick_batch_window_enforced", False),
        ("scheduler_tick_timezone", "UTC"),
        ("scheduler_tick_window_start", "00:00"),
        ("scheduler_tick_window_end", "23:59"),
    ),
)
def test_artifact_retention_scheduler_config_rejects_runtime_knob_drift(
    field: str,
    value: Any,
) -> None:
    config = build_artifact_retention_scheduler_config()
    runtime = {**config["runtime"], field: value}

    with pytest.raises(ArtifactHandoffError) as exc:
        validate_artifact_retention_scheduler_config({**config, "runtime": runtime})

    assert exc.value.error_code == "ae.artifact_retention_scheduler_config_invalid"
    assert "runtime" in exc.value.detail


def test_artifact_retention_scheduler_config_rejects_runtime_key_drift() -> None:
    config = build_artifact_retention_scheduler_config()
    runtime = dict(config["runtime"])
    runtime.pop("scheduler_tick_interval_seconds")

    with pytest.raises(ArtifactHandoffError) as missing_exc:
        validate_artifact_retention_scheduler_config({**config, "runtime": runtime})
    assert missing_exc.value.error_code == "ae.artifact_retention_scheduler_config_invalid"

    runtime = {**config["runtime"], "unexpected_scheduler_knob": True}
    with pytest.raises(ArtifactHandoffError) as extra_exc:
        validate_artifact_retention_scheduler_config({**config, "runtime": runtime})
    assert extra_exc.value.error_code == "ae.artifact_retention_scheduler_config_invalid"


def test_artifact_retention_scheduler_tick_plan_builds_ready_command_preview() -> None:
    store = ArtifactRecordStore()
    save_rendered_retention_artifact(
        store,
        artifact_request_id="scheduler-tick-plan-old-001",
        updated_at="2026-07-31T00:00:00Z",
        target_formats=["MD", "HTML_PREVIEW"],
    )
    batch_plan = store.plan_retention_batch(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        retention_days="30",
        as_of="2026-09-01T00:00:00Z",
        scan_limit="10",
        max_delete_count="1",
        checked_at="2026-09-01T02:10:00Z",
        idempotency_key="scheduler-tick-plan-ready-source",
    )
    scheduler_config = build_artifact_retention_scheduler_config(
        job_queue=InMemoryJobQueue()
    )

    tick_plan = build_artifact_retention_scheduler_tick_plan(
        batch_plan,
        scheduler_config=scheduler_config,
        tick_at="2026-08-31T17:30:00Z",
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
        idempotency_key="scheduler-tick-ready-001",
    )
    serialized = json.dumps(tick_plan, ensure_ascii=False, sort_keys=True)

    assert tick_plan["artifact_retention_scheduler_tick_plan_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_TICK_PLAN_SCHEMA_VERSION
    )
    assert tick_plan["tick_status"] == "READY"
    assert tick_plan["skip_reason"] is None
    assert tick_plan["trace_id"] == TRACE_ID
    assert tick_plan["request_id"] == REQUEST_ID
    assert tick_plan["source_plan_id"] == batch_plan["plan_id"]
    assert tick_plan["runtime"]["scheduler_daemon_enabled"] is False
    assert tick_plan["runtime"]["scheduler_daemon_started"] is False
    assert tick_plan["runtime"]["job_queue_available"] is True
    assert tick_plan["runtime"]["in_batch_window"] is True
    assert tick_plan["runtime"]["tick_interval_seconds"] == 900
    assert tick_plan["runtime"]["batch_window"] == {
        "timezone": "Asia/Seoul",
        "start_local_time": "02:00",
        "end_local_time": "05:00",
    }
    assert tick_plan["admission"] == {
        "admission_ready": True,
        "admission_performed": False,
        "trigger_type": "scheduler_tick",
        "requested_at": "2026-08-31T17:30:00Z",
        "idempotency_key": "scheduler-tick-ready-001",
        "max_jobs_per_tick": 1,
    }
    assert tick_plan["command_preview"]["trigger_type"] == "scheduler_tick"
    assert tick_plan["command_preview"]["command_status"] == "READY"
    assert tick_plan["command_preview"]["command_created_at"] == tick_plan["tick_at"]
    assert tick_plan["metadata"] == {
        "metadata_only": True,
        "job_enqueued": False,
        "worker_executed": False,
        "history_write_executed": False,
        "physical_delete_automation_enabled": False,
        "dry_run": True,
    }
    assert validate_artifact_retention_scheduler_tick_plan(tick_plan) is tick_plan
    assert "storage_ref" not in serialized
    assert "postgresql://" not in serialized


def test_artifact_retention_scheduler_tick_plan_skips_when_queue_unavailable() -> None:
    store = ArtifactRecordStore()
    save_rendered_retention_artifact(
        store,
        artifact_request_id="scheduler-tick-plan-noqueue-001",
        updated_at="2026-07-31T00:00:00Z",
    )
    batch_plan = store.plan_retention_batch(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        retention_days="30",
        as_of="2026-09-01T00:00:00Z",
        scan_limit="10",
        max_delete_count="1",
        checked_at="2026-09-01T02:10:00Z",
    )

    tick_plan = build_artifact_retention_scheduler_tick_plan(
        batch_plan,
        tick_at="2026-08-31T17:30:00Z",
    )

    assert tick_plan["tick_status"] == "SKIPPED"
    assert tick_plan["skip_reason"] == "job_queue_unavailable"
    assert tick_plan["command_preview"] is None
    assert tick_plan["admission"]["admission_ready"] is False
    assert tick_plan["runtime"]["job_queue_backend"] == "unconfigured"


def test_artifact_retention_scheduler_tick_plan_skips_outside_batch_window() -> None:
    store = ArtifactRecordStore()
    save_rendered_retention_artifact(
        store,
        artifact_request_id="scheduler-tick-plan-window-001",
        updated_at="2026-07-31T00:00:00Z",
    )
    batch_plan = store.plan_retention_batch(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        retention_days="30",
        as_of="2026-09-01T00:00:00Z",
        scan_limit="10",
        max_delete_count="1",
        checked_at="2026-09-01T02:10:00Z",
    )

    tick_plan = build_artifact_retention_scheduler_tick_plan(
        batch_plan,
        scheduler_config=build_artifact_retention_scheduler_config(
            job_queue=InMemoryJobQueue()
        ),
        tick_at="2026-09-01T10:00:00Z",
    )

    assert tick_plan["tick_status"] == "SKIPPED"
    assert tick_plan["skip_reason"] == "outside_batch_window"
    assert tick_plan["runtime"]["in_batch_window"] is False
    assert tick_plan["command_preview"] is None


def test_artifact_retention_scheduler_tick_plan_noop_when_no_candidates() -> None:
    candidate_filter = build_artifact_retention_candidate_filter(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        retention_days="30",
        as_of="2026-09-01T00:00:00Z",
        limit="10",
    )
    batch_plan = build_artifact_retention_batch_plan(
        build_artifact_retention_candidate_collection(
            [],
            candidate_filter=candidate_filter,
        ),
        checked_at="2026-09-01T02:10:00Z",
    )

    tick_plan = build_artifact_retention_scheduler_tick_plan(
        batch_plan,
        scheduler_config=build_artifact_retention_scheduler_config(
            job_queue=InMemoryJobQueue()
        ),
        tick_at="2026-08-31T17:30:00Z",
    )

    assert tick_plan["tick_status"] == "NOOP"
    assert tick_plan["skip_reason"] == "no_retention_candidates"
    assert tick_plan["source_plan_summary"]["plan_status"] == "NOOP"
    assert tick_plan["command_preview"] is None
    assert tick_plan["admission"]["admission_ready"] is False


def test_artifact_retention_scheduler_tick_plan_rejects_contract_drift() -> None:
    store = ArtifactRecordStore()
    save_rendered_retention_artifact(
        store,
        artifact_request_id="scheduler-tick-plan-invalid-001",
        updated_at="2026-07-31T00:00:00Z",
    )
    batch_plan = store.plan_retention_batch(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        retention_days="30",
        as_of="2026-09-01T00:00:00Z",
        scan_limit="10",
        max_delete_count="1",
        checked_at="2026-09-01T02:10:00Z",
    )
    tick_plan = build_artifact_retention_scheduler_tick_plan(
        batch_plan,
        scheduler_config=build_artifact_retention_scheduler_config(
            job_queue=InMemoryJobQueue()
        ),
        tick_at="2026-08-31T17:30:00Z",
        idempotency_key="scheduler-tick-invalid-001",
    )

    with pytest.raises(ArtifactHandoffError) as type_exc:
        validate_artifact_retention_scheduler_tick_plan([])  # type: ignore[arg-type]
    assert type_exc.value.error_code == (
        "ae.artifact_retention_scheduler_tick_plan_invalid"
    )

    invalid_cases = (
        (
            {"artifact_retention_scheduler_tick_plan_schema_version": "wrong"},
            "ae.artifact_retention_scheduler_tick_plan_schema_invalid",
            "schema version",
        ),
        (
            {"service_id": "nex-ag"},
            "ae.artifact_retention_scheduler_tick_plan_invalid",
            "service id",
        ),
        (
            {"source_plan_summary": []},
            "ae.artifact_retention_scheduler_tick_plan_invalid",
            "source_plan_summary",
        ),
        (
            {"runtime": []},
            "ae.artifact_retention_scheduler_tick_plan_invalid",
            "runtime",
        ),
        (
            {"scheduler_id": ""},
            "ae.artifact_retention_scheduler_tick_plan_invalid",
            "scheduler id",
        ),
        (
            {"tick_id": ""},
            "ae.artifact_retention_scheduler_tick_plan_invalid",
            "tick id",
        ),
        (
            {"source_plan_id": ""},
            "ae.artifact_retention_scheduler_tick_plan_invalid",
            "source plan id",
        ),
        (
            {"tick_at": "not-a-date"},
            "ae.artifact_retention_timestamp_invalid",
            "tick_at",
        ),
        (
            {"tick_status": "RUNNING"},
            "ae.artifact_retention_scheduler_tick_plan_invalid",
            "status",
        ),
        (
            {"metadata": {**tick_plan["metadata"], "job_enqueued": True}},
            "ae.artifact_retention_scheduler_tick_plan_invalid",
            "metadata",
        ),
        (
            {"skip_reason": "outside_batch_window"},
            "ae.artifact_retention_scheduler_tick_plan_invalid",
            "cannot skip",
        ),
        (
            {"command_preview": None},
            "ae.artifact_retention_scheduled_command_invalid",
            "object",
        ),
        (
            {
                "command_preview": {
                    **tick_plan["command_preview"],
                    "trigger_type": "operator_dispatch",
                }
            },
            "ae.artifact_retention_scheduler_tick_plan_invalid",
            "command preview",
        ),
    )
    for patch, error_code, detail in invalid_cases:
        with pytest.raises(ArtifactHandoffError) as invalid_exc:
            validate_artifact_retention_scheduler_tick_plan({**tick_plan, **patch})
        assert invalid_exc.value.error_code == error_code
        assert detail in invalid_exc.value.detail

    runtime_invalid_cases = (
        {"automation_profile": "enabled-local-v1"},
        {"scheduler_daemon_enabled": True},
        {"scheduler_daemon_started": True},
        {"scheduler_tick_admission_enabled": False},
        {"job_queue_available": "yes"},
        {"job_queue_backend": ""},
        {"worker_runner_available": False},
        {"physical_delete_automation_enabled": True},
        {"default_execution_mode": "EXECUTE"},
        {"tick_interval_seconds": 60},
        {"tick_jitter_seconds": 0},
        {"tick_lock_ttl_seconds": 60},
        {"tick_stale_after_seconds": 600},
        {"max_jobs_per_tick": 2},
        {"batch_window_enforced": False},
        {"in_batch_window": "yes"},
        {"batch_window": {"timezone": "UTC"}},
    )
    for patch in runtime_invalid_cases:
        with pytest.raises(ArtifactHandoffError) as runtime_exc:
            validate_artifact_retention_scheduler_tick_plan(
                {**tick_plan, "runtime": {**tick_plan["runtime"], **patch}}
            )
        assert runtime_exc.value.error_code == (
            "ae.artifact_retention_scheduler_tick_plan_invalid"
        )
        assert "runtime" in runtime_exc.value.detail

    runtime_missing_key = dict(tick_plan["runtime"])
    runtime_missing_key.pop("tick_interval_seconds")
    for runtime in (
        runtime_missing_key,
        {**tick_plan["runtime"], "unexpected_runtime_field": True},
    ):
        with pytest.raises(ArtifactHandoffError) as runtime_key_exc:
            validate_artifact_retention_scheduler_tick_plan(
                {**tick_plan, "runtime": runtime}
            )
        assert runtime_key_exc.value.error_code == (
            "ae.artifact_retention_scheduler_tick_plan_invalid"
        )
        assert "runtime" in runtime_key_exc.value.detail

    admission_invalid_cases = (
        {"admission_ready": False},
        {"admission_performed": True},
        {"trigger_type": "operator_dispatch"},
        {"requested_at": ""},
        {"idempotency_key": ""},
        {"max_jobs_per_tick": 2},
    )
    for patch in admission_invalid_cases:
        with pytest.raises(ArtifactHandoffError) as admission_exc:
            validate_artifact_retention_scheduler_tick_plan(
                {**tick_plan, "admission": {**tick_plan["admission"], **patch}}
            )
        assert admission_exc.value.error_code == (
            "ae.artifact_retention_scheduler_tick_plan_invalid"
        )
        assert "admission" in admission_exc.value.detail

    admission_missing_key = dict(tick_plan["admission"])
    admission_missing_key.pop("max_jobs_per_tick")
    with pytest.raises(ArtifactHandoffError) as admission_key_exc:
        validate_artifact_retention_scheduler_tick_plan(
            {**tick_plan, "admission": admission_missing_key}
        )
    assert admission_key_exc.value.error_code == (
        "ae.artifact_retention_scheduler_tick_plan_invalid"
    )

    skipped = build_artifact_retention_scheduler_tick_plan(
        batch_plan,
        tick_at="2026-08-31T17:30:00Z",
    )
    skipped_invalid_cases = (
        (
            {"skip_reason": "no_retention_candidates"},
            "ae.artifact_retention_scheduler_tick_plan_invalid",
            "skipped reason",
        ),
        (
            {"command_preview": tick_plan["command_preview"]},
            "ae.artifact_retention_scheduler_tick_plan_invalid",
            "skipped plan cannot carry command",
        ),
    )
    for patch, error_code, detail in skipped_invalid_cases:
        with pytest.raises(ArtifactHandoffError) as invalid_exc:
            validate_artifact_retention_scheduler_tick_plan({**skipped, **patch})
        assert invalid_exc.value.error_code == error_code
        assert detail in invalid_exc.value.detail

    noop = {
        **skipped,
        "tick_status": "NOOP",
        "skip_reason": "outside_batch_window",
    }
    with pytest.raises(ArtifactHandoffError) as noop_exc:
        validate_artifact_retention_scheduler_tick_plan(noop)
    assert noop_exc.value.error_code == "ae.artifact_retention_scheduler_tick_plan_invalid"
    assert "noop reason" in noop_exc.value.detail

    skipped_unknown_reason = {**skipped, "skip_reason": "maintenance_window"}
    with pytest.raises(ArtifactHandoffError) as skipped_reason_exc:
        validate_artifact_retention_scheduler_tick_plan(skipped_unknown_reason)
    assert skipped_reason_exc.value.error_code == (
        "ae.artifact_retention_scheduler_tick_plan_invalid"
    )
    assert "skip reason" in skipped_reason_exc.value.detail

    config = build_artifact_retention_scheduler_config(job_queue=InMemoryJobQueue())
    disabled_config = {
        **config,
        "runtime": {**config["runtime"], "scheduler_tick_admission_enabled": False},
    }
    assert ae_artifacts._artifact_retention_scheduler_tick_skip_reason(
        disabled_config,
        batch_plan,
        True,
    ) == "scheduler_tick_admission_disabled"


def test_artifact_retention_execution_contract_defaults_to_safe_dry_run() -> None:
    execution = build_artifact_retention_execution(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="owner-001",
        as_of="2026-09-01T00:00:00Z",
        checked_at="2026-09-01T02:30:00Z",
        candidate_count=3,
        selected_count=0,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert execution["artifact_retention_execution_schema_version"] == (
        AE_ARTIFACT_RETENTION_EXECUTION_SCHEMA_VERSION
    )
    assert execution["mode"] == "DRY_RUN"
    assert execution["execution_status"] == "PLANNED"
    assert execution["delete_enabled"] is False
    assert execution["storage_mutation_enabled"] is False
    assert execution["database_row_delete_enabled"] is False
    assert execution["retention_days_after_logical_purge"] == 30
    assert execution["cutoff_at"] == "2026-08-02T00:00:00Z"
    assert execution["scan_limit"] == 20
    assert execution["max_delete_count"] == 20
    assert execution["candidate_count"] == 3
    assert execution["deleted_counts"] == {
        "artifacts": 0,
        "source_refs": 0,
        "versions": 0,
        "render_jobs": 0,
        "files": 0,
        "links": 0,
        "storage_files": 0,
    }
    assert execution["requested_by"] == {
        "actor_type": "service",
        "actor_id": "nex-ae-api",
        "service_id": "nex-ae-api",
    }
    assert execution["audit"]["audit_event_type"] == "ae_artifact.retention.execution"
    assert validate_artifact_retention_execution(execution) is execution
    assert "storage_ref" not in json.dumps(execution, sort_keys=True)


def test_artifact_retention_execution_contract_supports_guarded_execute() -> None:
    blocked = build_artifact_retention_execution(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="owner-001",
        mode="execute",
        execution_status="blocked",
        as_of="2026-09-01T00:00:00Z",
        checked_at="2026-09-01T02:30:00Z",
        candidate_count=2,
        selected_count=0,
        blocked_reason="delete_not_enabled",
        requested_by={"actor_type": "service", "actor_id": "nex-ag"},
    )
    succeeded = build_artifact_retention_execution(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="owner-001",
        mode="EXECUTE",
        execution_status="SUCCEEDED",
        retention_days="15",
        as_of="2026-09-01T00:00:00Z",
        checked_at="2026-09-01T02:30:00Z",
        max_delete_count="10",
        candidate_count=2,
        selected_count=1,
        deleted_counts={
            "artifacts": 1,
            "source_refs": 1,
            "versions": 1,
            "render_jobs": 1,
            "files": 2,
            "links": 4,
            "storage_files": 2,
        },
        delete_enabled=True,
        storage_mutation_enabled=True,
        database_row_delete_enabled=True,
        idempotency_key="retention-execute-001",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert blocked["execution_status"] == "BLOCKED"
    assert blocked["blocked_reason"] == "delete_not_enabled"
    assert blocked["requested_by"] == {
        "actor_type": "service",
        "actor_id": "nex-ag",
        "service_id": "nex-ae-api",
    }
    assert succeeded["mode"] == "EXECUTE"
    assert succeeded["execution_status"] == "SUCCEEDED"
    assert succeeded["retention_days_after_logical_purge"] == 15
    assert succeeded["max_delete_count"] == 10
    assert succeeded["deleted_counts"]["artifacts"] == 1
    assert succeeded["deleted_counts"]["storage_files"] == 2
    assert validate_artifact_retention_execution(succeeded) is succeeded


def test_artifact_retention_execution_contract_rejects_unsafe_edges() -> None:
    base = {
        "tenant_id": "tenant-001",
        "workspace_id": "workspace-001",
        "owner_user_id": "owner-001",
        "as_of": "2026-09-01T00:00:00Z",
        "checked_at": "2026-09-01T02:30:00Z",
    }

    assert normalize_artifact_retention_delete_limit(None) == 20
    assert normalize_artifact_retention_delete_limit("100") == 100
    for bad_value in (0, 101, True, "many"):
        with pytest.raises(ArtifactHandoffError) as limit_exc:
            normalize_artifact_retention_delete_limit(bad_value)
        assert limit_exc.value.error_code == (
            "ae.artifact_retention_delete_limit_invalid"
        )

    invalid_cases = [
        (
            {**base, "mode": "preview"},
            "ae.artifact_retention_execution_mode_invalid",
        ),
        (
            {**base, "execution_status": "done"},
            "ae.artifact_retention_execution_status_invalid",
        ),
        (
            {**base, "delete_enabled": True},
            "ae.artifact_retention_dry_run_delete_enabled_invalid",
        ),
        (
            {
                **base,
                "mode": "EXECUTE",
                "execution_status": "SUCCEEDED",
                "delete_enabled": True,
            },
            "ae.artifact_retention_execute_not_enabled",
        ),
        (
            {**base, "candidate_count": 1, "selected_count": 2},
            "ae.artifact_retention_selected_count_invalid",
        ),
        (
            {**base, "deleted_counts": {"artifacts": 1}},
            "ae.artifact_retention_deleted_counts_invalid",
        ),
        (
            {**base, "requested_by": {"actor_id": "storage_ref"}},
            "ae.artifact_retention_payload_unsafe",
        ),
        (
            {**base, "error": {"error_code": "boom"}},
            "ae.artifact_retention_error_invalid",
        ),
        (
            {**base, "error": "boom"},
            "ae.artifact_retention_error_invalid",
        ),
        (
            {**base, "candidate_count": True},
            "ae.artifact_retention_count_invalid",
        ),
        (
            {**base, "candidate_count": "many"},
            "ae.artifact_retention_count_invalid",
        ),
        (
            {**base, "candidate_count": -1},
            "ae.artifact_retention_count_invalid",
        ),
    ]
    for kwargs, error_code in invalid_cases:
        with pytest.raises(ArtifactHandoffError) as exc:
            build_artifact_retention_execution(**kwargs)
        assert exc.value.error_code == error_code

    without_checked_at = build_artifact_retention_execution(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="owner-001",
        as_of="2026-09-01T00:00:00Z",
    )
    assert without_checked_at["checked_at"].endswith("Z")

    valid = build_artifact_retention_execution(**base, candidate_count=5)
    validation_mutations = [
        (
            {"policy_id": "wrong"},
            "ae.artifact_retention_execution_policy_invalid",
        ),
        (
            {"service_id": "nex-cx"},
            "ae.artifact_retention_execution_service_invalid",
        ),
        (
            {"delete_enabled": "yes"},
            "ae.artifact_retention_execution_flag_invalid",
        ),
        (
            {"retention_days_after_logical_purge": "30"},
            "ae.artifact_retention_execution_days_invalid",
        ),
        (
            {"scan_limit": "20"},
            "ae.artifact_retention_execution_scan_limit_invalid",
        ),
        (
            {"max_delete_count": "20"},
            "ae.artifact_retention_execution_delete_limit_invalid",
        ),
        (
            {"selected_count": 21, "candidate_count": 30},
            "ae.artifact_retention_selected_count_invalid",
        ),
        (
            {
                "mode": "EXECUTE",
                "execution_status": "SUCCEEDED",
                "delete_enabled": True,
                "storage_mutation_enabled": True,
                "database_row_delete_enabled": True,
                "selected_count": 2,
                "deleted_counts": {
                    "artifacts": 1,
                    "source_refs": 0,
                    "versions": 0,
                    "render_jobs": 0,
                    "files": 0,
                    "links": 0,
                    "storage_files": 0,
                },
            },
            "ae.artifact_retention_deleted_counts_invalid",
        ),
        (
            {"metadata": {"candidate_scan_metadata_only": False}},
            "ae.artifact_retention_execution_metadata_invalid",
        ),
        (
            {"audit": {**valid["audit"], "audit_event_type": "wrong"}},
            "ae.artifact_retention_audit_invalid",
        ),
        (
            {"audit": {**valid["audit"], "audit_event_id": "wrong"}},
            "ae.artifact_retention_audit_invalid",
        ),
        (
            {"audit": {**valid["audit"], "emitted": "no"}},
            "ae.artifact_retention_audit_invalid",
        ),
    ]
    for mutation, error_code in validation_mutations:
        with pytest.raises(ArtifactHandoffError) as exc:
            validate_artifact_retention_execution({**valid, **mutation})
        assert exc.value.error_code == error_code

    with pytest.raises(ArtifactHandoffError) as missing_exc:
        validate_artifact_retention_execution({**valid, "audit": []})  # type: ignore[dict-item]
    assert missing_exc.value.error_code == "ae.artifact_retention_audit_invalid"
    missing_required = dict(valid)
    missing_required.pop("metadata")
    with pytest.raises(ArtifactHandoffError) as required_exc:
        validate_artifact_retention_execution(missing_required)
    assert required_exc.value.error_code == "ae.artifact_retention_execution_invalid"
    with pytest.raises(ArtifactHandoffError) as type_exc:
        validate_artifact_retention_execution(["bad"])  # type: ignore[arg-type]
    assert type_exc.value.error_code == "ae.artifact_retention_execution_invalid"
    with pytest.raises(ArtifactHandoffError) as schema_exc:
        validate_artifact_retention_execution(
            {**valid, "artifact_retention_execution_schema_version": "wrong"}
        )
    assert schema_exc.value.error_code == (
        "ae.artifact_retention_execution_schema_invalid"
    )


def test_artifact_retention_execution_history_record_derives_safe_metadata() -> None:
    execution = sample_retention_execution(
        execution_status="SUCCEEDED",
        checked_at="2026-09-01T02:00:00Z",
        requested_by={"actor_type": "service", "actor_id": "nex-ag"},
    )
    record = build_artifact_retention_execution_history_record(
        execution,
        created_at="2026-09-01T02:01:00Z",
    )

    assert record["execution_history_schema_version"] == (
        AE_ARTIFACT_RETENTION_EXECUTION_HISTORY_SCHEMA_VERSION
    )
    assert record["retention_execution_id"] == execution["execution_id"]
    assert record["artifact_retention_execution_schema_version"] == (
        AE_ARTIFACT_RETENTION_EXECUTION_SCHEMA_VERSION
    )
    assert record["execution"] == execution
    assert record["created_at"] == "2026-09-01T02:01:00Z"
    assert record["execution_payload_hash"] == ae_artifacts.sha256_json(execution)
    assert validate_artifact_retention_execution_history_record(record) is record
    assert "storage_ref" not in json.dumps(record, ensure_ascii=False, sort_keys=True)
    assert "postgresql" not in json.dumps(record, ensure_ascii=False, sort_keys=True)

    invalid_cases = [
        (
            {**record, "execution_history_schema_version": "wrong"},
            "ae.artifact_retention_history_schema_invalid",
        ),
        (
            {**record, "candidate_count": record["candidate_count"] + 1},
            "ae.artifact_retention_history_mismatch",
        ),
        (
            {**record, "retention_execution_id": "wrong"},
            "ae.artifact_retention_history_mismatch",
        ),
        (
            {**record, "execution_payload_hash": "0" * 64},
            "ae.artifact_retention_history_hash_invalid",
        ),
        (
            {**record, "created_at": "not-a-date"},
            "ae.artifact_retention_timestamp_invalid",
        ),
    ]
    for mutation, error_code in invalid_cases:
        with pytest.raises(ArtifactHandoffError) as exc_info:
            validate_artifact_retention_execution_history_record(mutation)
        assert exc_info.value.error_code == error_code

    missing_required = dict(record)
    missing_required.pop("execution")
    with pytest.raises(ArtifactHandoffError) as missing_exc:
        validate_artifact_retention_execution_history_record(missing_required)
    assert missing_exc.value.error_code == "ae.artifact_retention_history_invalid"
    with pytest.raises(ArtifactHandoffError) as type_exc:
        validate_artifact_retention_execution_history_record(["bad"])  # type: ignore[arg-type]
    assert type_exc.value.error_code == "ae.artifact_retention_history_invalid"


def test_artifact_retention_execution_history_collection_is_metadata_only() -> None:
    succeeded = build_artifact_retention_execution_history_record(
        sample_retention_execution(
            mode="EXECUTE",
            execution_status="SUCCEEDED",
            checked_at="2026-09-01T02:45:00Z",
            delete_enabled=True,
            storage_mutation_enabled=True,
            database_row_delete_enabled=True,
            deleted_counts={
                "artifacts": 1,
                "source_refs": 1,
                "versions": 1,
                "render_jobs": 1,
                "files": 2,
                "links": 4,
                "storage_files": 2,
            },
        )
    )
    blocked = build_artifact_retention_execution_history_record(
        sample_retention_execution(
            mode="EXECUTE",
            execution_status="BLOCKED",
            checked_at="2026-09-01T02:40:00Z",
            selected_count=0,
            idempotency_key=None,
            blocked_reason="delete_not_enabled",
        )
    )
    history_filter = build_artifact_retention_execution_history_filter(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        mode="execute",
        limit="10",
    )

    collection = build_artifact_retention_execution_history_collection(
        [succeeded, blocked],
        history_filter=history_filter,
    )
    first_item = collection["items"][0]
    serialized = json.dumps(collection, ensure_ascii=False, sort_keys=True)

    assert collection[
        "artifact_retention_execution_history_collection_schema_version"
    ] == AE_ARTIFACT_RETENTION_EXECUTION_HISTORY_COLLECTION_SCHEMA_VERSION
    assert collection["filter"] == {
        "tenant_id": "tenant-001",
        "workspace_id": "workspace-001",
        "owner_user_id": "user-001",
        "mode": "EXECUTE",
        "execution_status": None,
        "limit": 10,
    }
    assert collection["count"] == 2
    assert collection["metadata"]["metadata_only"] is True
    assert collection["summary"] == {
        "item_count": 2,
        "mode_counts": {"EXECUTE": 2},
        "status_counts": {"SUCCEEDED": 1, "BLOCKED": 1},
        "dry_run_count": 0,
        "execute_count": 2,
        "succeeded_count": 1,
        "blocked_count": 1,
        "failed_count": 0,
        "total_deleted_artifacts": 1,
        "total_deleted_storage_files": 2,
        "latest_checked_at": "2026-09-01T02:45:00Z",
    }
    assert first_item[
        "artifact_retention_execution_history_item_schema_version"
    ] == AE_ARTIFACT_RETENTION_EXECUTION_HISTORY_ITEM_SCHEMA_VERSION
    assert first_item["execution_payload_hash"] == succeeded["execution_payload_hash"]
    assert first_item["metadata"] == {
        "metadata_only": True,
        "candidate_scan_metadata_only": True,
        "logical_purge_required_before_physical_delete": True,
        "scheduled_batch_timezone": "Asia/Seoul",
        "scheduled_batch_window": {
            "start_local_time": "02:00",
            "end_local_time": "05:00",
        },
        "policy_snapshot": {},
        "safety": {},
    }
    assert '"execution":' not in serialized
    assert "storage_ref" not in serialized
    assert summarize_artifact_retention_execution_history([]) == {
        "item_count": 0,
        "mode_counts": {},
        "status_counts": {},
        "dry_run_count": 0,
        "execute_count": 0,
        "succeeded_count": 0,
        "blocked_count": 0,
        "failed_count": 0,
        "total_deleted_artifacts": 0,
        "total_deleted_storage_files": 0,
        "latest_checked_at": None,
    }


def test_artifact_retention_execution_history_read_model_rejects_unsafe_payloads() -> None:
    record = build_artifact_retention_execution_history_record(
        sample_retention_execution()
    )
    with pytest.raises(ArtifactHandoffError) as raw_execution_exc:
        assert_artifact_retention_history_payload_safe(
            {"execution": record["execution"]}
        )
    with pytest.raises(ArtifactHandoffError) as private_token_exc:
        assert_artifact_retention_history_payload_safe({"leak": "storage_ref"})
    with pytest.raises(ArtifactHandoffError) as mismatch_exc:
        build_artifact_retention_execution_history_item(
            {**record, "metadata": {"private": "storage_ref"}}
        )
    with pytest.raises(ArtifactHandoffError) as mode_exc:
        build_artifact_retention_execution_history_filter(
            tenant_id="tenant-001",
            workspace_id="workspace-001",
            owner_user_id="user-001",
            mode="preview",
        )

    assert raw_execution_exc.value.error_code == (
        "ae.artifact_retention_history_payload_unsafe"
    )
    assert private_token_exc.value.error_code == (
        "ae.artifact_retention_payload_unsafe"
    )
    assert mismatch_exc.value.error_code == "ae.artifact_retention_history_mismatch"
    assert mode_exc.value.error_code == (
        "ae.artifact_retention_execution_mode_invalid"
    )


def test_artifact_retention_execution_history_store_scopes_idempotency_and_lists() -> None:
    store = ArtifactRetentionExecutionHistoryStore()
    first = store.save(
        sample_retention_execution(
            execution_status="SUCCEEDED",
            checked_at="2026-09-01T02:00:00Z",
            idempotency_key="same-key",
        )
    )
    duplicate = store.save(
        sample_retention_execution(
            execution_status="SUCCEEDED",
            checked_at="2026-09-01T02:05:00Z",
            idempotency_key="same-key",
        )
    )
    blocked = store.save(
        sample_retention_execution(
            mode="EXECUTE",
            execution_status="BLOCKED",
            checked_at="2026-09-01T02:10:00Z",
            selected_count=0,
            idempotency_key=None,
            blocked_reason="delete_not_enabled",
        )
    )
    other_owner = store.save(
        sample_retention_execution(
            owner_user_id="user-002",
            execution_status="SUCCEEDED",
            checked_at="2026-09-01T02:20:00Z",
            idempotency_key="same-key",
        )
    )

    assert duplicate is first
    assert store.get(first["retention_execution_id"]) is first
    assert store.get_by_idempotency_key(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        idempotency_key="same-key",
    ) is first
    assert store.get_by_idempotency_key(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        idempotency_key=None,
    ) is None
    assert other_owner is not first
    listed = store.list_executions(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
    )
    blocked_only = store.list_executions(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        execution_status="blocked",
        limit="1",
    )

    assert [item["retention_execution_id"] for item in listed] == [
        blocked["retention_execution_id"],
        first["retention_execution_id"],
    ]
    assert blocked_only == [blocked]
    with pytest.raises(ArtifactHandoffError) as scope_exc:
        store.list_executions(
            tenant_id=" ",
            workspace_id="workspace-001",
            owner_user_id="user-001",
        )
    assert scope_exc.value.error_code == "ae.artifact_collection_scope_required"


def test_sqlalchemy_artifact_retention_execution_history_store_round_trips_with_sqlite() -> None:
    session_factory = sqlite_artifact_session_factory()
    store = SqlAlchemyArtifactRetentionExecutionHistoryStore(session_factory)
    first_execution = sample_retention_execution(
        execution_status="SUCCEEDED",
        checked_at="2026-09-01T02:30:00Z",
        idempotency_key="sql-history-key",
    )
    duplicate_execution = sample_retention_execution(
        execution_status="SUCCEEDED",
        checked_at="2026-09-01T02:31:00Z",
        idempotency_key="sql-history-key",
    )
    execute_execution = sample_retention_execution(
        mode="EXECUTE",
        execution_status="SUCCEEDED",
        checked_at="2026-09-01T02:35:00Z",
        idempotency_key=None,
        delete_enabled=True,
        storage_mutation_enabled=True,
        database_row_delete_enabled=True,
        deleted_counts={
            "artifacts": 1,
            "source_refs": 1,
            "versions": 1,
            "render_jobs": 1,
            "files": 2,
            "links": 4,
            "storage_files": 2,
        },
    )

    first = store.save(first_execution)
    duplicate = store.save(duplicate_execution)
    executed = store.save(execute_execution)
    fetched = store.get(first["retention_execution_id"])
    by_key = store.get_by_idempotency_key(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        idempotency_key="sql-history-key",
    )
    listed = store.list_executions(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        limit=1,
    )
    dry_runs = store.list_executions(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        mode="dry_run",
    )

    assert duplicate["retention_execution_id"] == first["retention_execution_id"]
    assert fetched == first
    assert by_key == first
    assert listed == [executed]
    assert dry_runs == [first]
    assert store.get("missing-history") is None
    assert store.get_by_idempotency_key(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        idempotency_key=None,
    ) is None
    with session_factory() as session:
        row = session.execute(
            text(
                """
                SELECT error, execution_payload_hash
                FROM ae_artifact_retention_executions
                WHERE retention_execution_id = :retention_execution_id
                """
            ),
            {"retention_execution_id": first["retention_execution_id"]},
        ).first()
    assert row is not None
    assert row[0] is None
    assert len(row[1]) == 64
    assert "storage_ref" not in json.dumps(executed, sort_keys=True)


@pytest.mark.parametrize("operation", ["ensure", "save", "get", "idempotency", "list"])
def test_sqlalchemy_artifact_retention_execution_history_store_maps_database_errors(
    operation: str,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    store = SqlAlchemyArtifactRetentionExecutionHistoryStore(session_factory)

    with pytest.raises(ArtifactHandoffError) as exc_info:
        if operation == "ensure":
            store.ensure_available()
        elif operation == "save":
            store.save(sample_retention_execution())
        elif operation == "get":
            store.get("missing-history")
        elif operation == "idempotency":
            store.get_by_idempotency_key(
                tenant_id="tenant-001",
                workspace_id="workspace-001",
                owner_user_id="user-001",
                idempotency_key="missing-key",
            )
        else:
            store.list_executions(
                tenant_id="tenant-001",
                workspace_id="workspace-001",
                owner_user_id="user-001",
            )

    assert exc_info.value.status_code == 503
    assert exc_info.value.retryable is True
    assert exc_info.value.error_code == (
        "ae.artifact_retention_history_store_unavailable"
    )


def test_artifact_retention_candidate_read_model_filters_logical_purge_age() -> None:
    store = ArtifactRecordStore()
    old_deleted = sample_collection_artifact_record(
        artifact_request_id="retention-old-deleted-001",
        artifact_status="DELETED",
        display_title="Old deleted report",
        updated_at="2026-07-31T00:00:00Z",
    )
    recent_deleted = sample_collection_artifact_record(
        artifact_request_id="retention-recent-deleted-001",
        artifact_status="DELETED",
        display_title="Recent deleted report",
        updated_at="2026-08-25T00:00:00Z",
    )
    ready_old = sample_collection_artifact_record(
        artifact_request_id="retention-ready-old-001",
        artifact_status="READY",
        display_title="Ready old report",
        updated_at="2026-07-01T00:00:00Z",
    )
    other_owner = sample_collection_artifact_record(
        artifact_request_id="retention-other-owner-001",
        artifact_status="DELETED",
        owner_user_id="user-002",
        display_title="Other owner deleted report",
        updated_at="2026-07-01T00:00:00Z",
    )
    for record in (recent_deleted, old_deleted, ready_old, other_owner):
        store.save(record)

    candidates = store.list_retention_candidates(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        retention_days="30",
        as_of="2026-09-01T00:00:00Z",
        limit=10,
    )
    short_window = store.list_retention_candidates(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        retention_days=1,
        as_of="2026-09-01T00:00:00Z",
        limit=10,
    )
    serialized = json.dumps(candidates, ensure_ascii=False, sort_keys=True)

    assert candidates["artifact_retention_candidate_collection_schema_version"] == (
        "ae_artifact_retention_candidate_collection.v1"
    )
    assert candidates["policy"]["candidate_query"]["metadata_only"] is True
    assert candidates["filter"]["cutoff_at"] == "2026-08-02T00:00:00Z"
    assert candidates["count"] == 1
    assert candidates["items"][0]["artifact_id"] == old_deleted["artifact_id"]
    assert candidates["items"][0]["logical_purged_at"] == "2026-07-31T00:00:00Z"
    assert candidates["items"][0]["purge_eligible_at"] == "2026-08-30T00:00:00Z"
    assert candidates["items"][0]["age_days_after_logical_purge"] == 32
    assert candidates["items"][0]["purge_plan"] == {
        "dry_run": True,
        "logical_purge_already_applied": True,
        "physical_delete_deferred": True,
        "storage_mutation_enabled": False,
        "database_row_delete_enabled": False,
        "planned_execution": "scheduled_batch_after_retention",
    }
    assert [item["display_title"] for item in short_window["items"]] == [
        "Old deleted report",
        "Recent deleted report",
    ]
    assert "storage_ref" not in serialized
    assert "rendered_payloads" not in serialized


def test_artifact_retention_candidate_filter_rejects_invalid_inputs() -> None:
    candidate_filter = build_artifact_retention_candidate_filter(
        tenant_id=" tenant-001 ",
        workspace_id=" workspace-001 ",
        owner_user_id=" user-001 ",
        retention_days="15",
        as_of="2026-09-01T00:00:00Z",
        limit="2",
    )

    assert candidate_filter == {
        "tenant_id": "tenant-001",
        "workspace_id": "workspace-001",
        "owner_user_id": "user-001",
        "status": "DELETED",
        "retention_days_after_logical_purge": 15,
        "as_of": "2026-09-01T00:00:00Z",
        "cutoff_at": "2026-08-17T00:00:00Z",
        "limit": 2,
        "dry_run": True,
    }
    assert parse_artifact_retention_timestamp(
        "2026-09-01T09:00:00+09:00",
        field_name="as_of",
    ).isoformat() == "2026-09-01T00:00:00+00:00"

    for bad_kwargs, expected_code in (
        (
            {"tenant_id": "", "workspace_id": "workspace-001", "owner_user_id": "user-001"},
            "ae.artifact_collection_scope_required",
        ),
        (
            {
                "tenant_id": "tenant-001",
                "workspace_id": "workspace-001",
                "owner_user_id": "user-001",
                "as_of": "not-a-date",
            },
            "ae.artifact_retention_timestamp_invalid",
        ),
    ):
        with pytest.raises(ArtifactHandoffError) as exc:
            build_artifact_retention_candidate_filter(**bad_kwargs)
        assert exc.value.error_code == expected_code

    with pytest.raises(ArtifactHandoffError) as unsafe_exc:
        build_artifact_retention_candidate_collection(
            [],
            candidate_filter={**candidate_filter, "storage_ref": "ae://artifacts/x"},
        )
    assert unsafe_exc.value.error_code == "ae.artifact_retention_payload_unsafe"


def test_sqlalchemy_artifact_record_store_lists_retention_candidates_with_sqlite() -> None:
    session_factory = sqlite_artifact_session_factory()
    handoff_store = SqlAlchemyArtifactHandoffStore(session_factory)
    store = SqlAlchemyArtifactRecordStore(session_factory)
    old_deleted = sample_collection_artifact_record(
        artifact_request_id="sql-retention-old-deleted-001",
        artifact_status="DELETED",
        display_title="SQL old deleted report",
        updated_at="2026-07-31T00:00:00Z",
    )
    recent_deleted = sample_collection_artifact_record(
        artifact_request_id="sql-retention-recent-deleted-001",
        artifact_status="DELETED",
        display_title="SQL recent deleted report",
        updated_at="2026-08-30T00:00:00Z",
    )
    for record in (old_deleted, recent_deleted):
        handoff_store.save(
            {
                **sample_handoff_record(),
                "artifact_handoff_id": record["handoff_ref"]["artifact_handoff_id"],
                "artifact_request_id": record["handoff_ref"]["artifact_request_id"],
            }
        )
        store.save(record)

    candidates = store.list_retention_candidates(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        retention_days=30,
        as_of="2026-09-01T00:00:00Z",
        limit=10,
    )

    assert candidates["count"] == 1
    assert candidates["items"][0]["display_title"] == "SQL old deleted report"
    assert candidates["items"][0]["file_count"] == 0
    assert candidates["items"][0]["link_count"] == 0


def test_artifact_retention_batch_plan_read_model_selects_candidates_safely() -> None:
    store = ArtifactRecordStore()
    first = save_rendered_retention_artifact(
        store,
        artifact_request_id="retention-plan-old-001",
        updated_at="2026-07-31T00:00:00Z",
        target_formats=["MD", "HTML_PREVIEW", "DOCX"],
    )
    save_rendered_retention_artifact(
        store,
        artifact_request_id="retention-plan-old-002",
        updated_at="2026-07-31T01:00:00Z",
        target_formats=["MD"],
    )
    save_rendered_retention_artifact(
        store,
        artifact_request_id="retention-plan-recent-001",
        updated_at="2026-08-31T00:00:00Z",
    )

    plan = store.plan_retention_batch(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        retention_days="30",
        as_of="2026-09-01T00:00:00Z",
        scan_limit="10",
        max_delete_count="1",
        checked_at="2026-09-01T02:15:00Z",
        requested_by={"actor_type": "service", "actor_id": "nex-ag"},
        idempotency_key="retention-plan-001",
    )
    selected = plan["selected_candidates"][0]
    serialized = json.dumps(plan, ensure_ascii=False, sort_keys=True)

    assert plan["artifact_retention_batch_plan_schema_version"] == (
        AE_ARTIFACT_RETENTION_BATCH_PLAN_SCHEMA_VERSION
    )
    assert plan["plan_status"] == "READY"
    assert plan["scheduler_status"] == "DISABLED"
    assert plan["execution_advice"] == "manual_dispatch_after_operator_approval"
    assert plan["mode"] == "DRY_RUN"
    assert plan["candidate_count"] == 2
    assert plan["selected_count"] == 1
    assert plan["unselected_count"] == 1
    assert plan["max_delete_count"] == 1
    assert plan["idempotency_key"] == "retention-plan-001"
    assert plan["metadata"] == {
        "metadata_only": True,
        "dry_run": True,
        "physical_delete_executed": False,
        "storage_mutation_executed": False,
        "database_row_delete_executed": False,
        "history_write_executed": False,
        "source_collection_count": 2,
    }
    assert selected["artifact_retention_batch_plan_item_schema_version"] == (
        AE_ARTIFACT_RETENTION_BATCH_PLAN_ITEM_SCHEMA_VERSION
    )
    assert selected["selection_order"] == 1
    assert selected["artifact_id"] == first["artifact_id"]
    assert selected["planned_action"] == "PHYSICAL_DELETE"
    assert selected["dry_run"] is True
    assert plan["estimated_deleted_counts"] == {
        "artifacts": 1,
        "source_refs": 0,
        "versions": 1,
        "render_jobs": 1,
        "files": 3,
        "links": 6,
        "storage_files": 3,
    }
    assert summarize_artifact_retention_batch_plan(plan) == {
        "plan_status": "READY",
        "scheduler_status": "DISABLED",
        "candidate_count": 2,
        "selected_count": 1,
        "unselected_count": 1,
        "estimated_deleted_artifacts": 1,
        "estimated_deleted_storage_files": 3,
        "checked_at": "2026-09-01T02:15:00Z",
        "next_action": "manual_dispatch_after_operator_approval",
    }
    assert validate_artifact_retention_batch_plan(plan) is plan
    assert "storage_ref" not in serialized
    assert "content_base64" not in serialized
    assert store.get(first["artifact_id"]) is not None


def test_artifact_retention_batch_plan_noop_and_validation_edges() -> None:
    candidate_filter = build_artifact_retention_candidate_filter(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        retention_days="15",
        as_of="2026-09-01T00:00:00Z",
        limit="5",
    )
    collection = build_artifact_retention_candidate_collection(
        [],
        candidate_filter=candidate_filter,
    )
    noop = build_artifact_retention_batch_plan(
        collection,
        schedule={"retention_days": "15", "max_delete_count": "7"},
        checked_at="2026-09-01T02:20:00Z",
    )

    assert noop["plan_status"] == "NOOP"
    assert noop["execution_advice"] == "no_retention_candidates"
    assert noop["candidate_count"] == 0
    assert noop["selected_count"] == 0
    assert noop["max_delete_count"] == 7
    assert noop["schedule"]["retention"]["retention_days_after_logical_purge"] == 15
    assert noop["schedule"]["limits"]["default_max_delete_count"] == 7
    assert summarize_artifact_retention_batch_plan(noop)["next_action"] == (
        "no_retention_candidates"
    )

    with pytest.raises(ArtifactHandoffError) as collection_type_exc:
        build_artifact_retention_batch_plan([])  # type: ignore[arg-type]
    assert collection_type_exc.value.error_code == (
        "ae.artifact_retention_batch_plan_invalid"
    )

    with pytest.raises(ArtifactHandoffError) as collection_schema_exc:
        build_artifact_retention_batch_plan(
            {
                **collection,
                "artifact_retention_candidate_collection_schema_version": "wrong",
            }
        )
    assert collection_schema_exc.value.error_code == (
        "ae.artifact_retention_batch_plan_invalid"
    )

    with pytest.raises(ArtifactHandoffError) as collection_filter_exc:
        build_artifact_retention_batch_plan({**collection, "filter": []})  # type: ignore[dict-item]
    assert collection_filter_exc.value.error_code == (
        "ae.artifact_retention_batch_plan_invalid"
    )

    with pytest.raises(ArtifactHandoffError) as plan_type_exc:
        validate_artifact_retention_batch_plan("bad")  # type: ignore[arg-type]
    assert plan_type_exc.value.error_code == "ae.artifact_retention_batch_plan_invalid"

    invalid_cases = [
        (
            {"artifact_retention_batch_plan_schema_version": "wrong"},
            "ae.artifact_retention_batch_plan_schema_invalid",
        ),
        ({"candidate_filter": []}, "ae.artifact_retention_batch_plan_invalid"),
        ({"estimated_deleted_counts": []}, "ae.artifact_retention_batch_plan_invalid"),
        ({"requested_by": []}, "ae.artifact_retention_batch_plan_invalid"),
        ({"metadata": []}, "ae.artifact_retention_batch_plan_invalid"),
        ({"candidate_filter": {**noop["candidate_filter"], "tenant_id": " "}},
         "ae.artifact_retention_batch_plan_invalid"),
        ({"mode": "EXECUTE"}, "ae.artifact_retention_batch_plan_invalid"),
        ({"plan_status": "RUNNING"}, "ae.artifact_retention_batch_plan_invalid"),
        ({"scheduler_status": "ENABLED"}, "ae.artifact_retention_batch_plan_invalid"),
        ({"selected_count": 1}, "ae.artifact_retention_batch_plan_invalid"),
        ({"candidate_count": 0, "selected_count": 0, "unselected_count": 1},
         "ae.artifact_retention_batch_plan_invalid"),
        ({"metadata": {**noop["metadata"], "metadata_only": False}},
         "ae.artifact_retention_batch_plan_invalid"),
        ({"storage_ref": "ae://artifacts/private.md"},
         "ae.artifact_retention_payload_unsafe"),
    ]
    for mutation, error_code in invalid_cases:
        with pytest.raises(ArtifactHandoffError) as exc_info:
            validate_artifact_retention_batch_plan({**noop, **mutation})
        assert exc_info.value.error_code == error_code


def test_artifact_retention_scheduled_execution_command_builds_safe_dispatch() -> None:
    store = ArtifactRecordStore()
    save_rendered_retention_artifact(
        store,
        artifact_request_id="scheduled-command-old-001",
        updated_at="2026-07-31T00:00:00Z",
        target_formats=["MD", "HTML_PREVIEW"],
    )
    save_rendered_retention_artifact(
        store,
        artifact_request_id="scheduled-command-old-002",
        updated_at="2026-07-31T01:00:00Z",
        target_formats=["MD"],
    )

    plan = store.plan_retention_batch(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        retention_days="30",
        as_of="2026-09-01T00:00:00Z",
        scan_limit="10",
        max_delete_count="1",
        checked_at="2026-09-01T02:10:00Z",
        requested_by={"actor_type": "service", "actor_id": "nex-ag"},
        idempotency_key="scheduled-plan-001",
    )
    command = build_artifact_retention_scheduled_execution_command(
        plan,
        trigger_type="operator-dispatch",
        command_created_at="2026-09-01T02:15:00Z",
        idempotency_key="scheduled-command-001",
    )
    request_payload = command["execution_request"]["payload"]
    serialized = json.dumps(command, ensure_ascii=False, sort_keys=True)

    assert command[
        "artifact_retention_scheduled_execution_command_schema_version"
    ] == AE_ARTIFACT_RETENTION_SCHEDULED_EXECUTION_COMMAND_SCHEMA_VERSION
    assert command["source_plan_id"] == plan["plan_id"]
    assert command["trigger_type"] == "operator_dispatch"
    assert command["command_status"] == "READY"
    assert command["execution_mode"] == "DRY_RUN"
    assert command["selected_count"] == 1
    assert command["estimated_deleted_counts"]["artifacts"] == 1
    assert command["batch_plan_summary"] == summarize_artifact_retention_batch_plan(
        plan
    )
    assert command["execution_request"]["route"] == "/api/v1/artifact-retention/purge"
    assert request_payload["mode"] == "DRY_RUN"
    assert request_payload["dry_run"] is True
    assert request_payload["delete_enabled"] is False
    assert request_payload["storage_mutation_enabled"] is False
    assert request_payload["database_row_delete_enabled"] is False
    assert request_payload["idempotency_key"] == "scheduled-command-001"
    assert command["guardrails"]["ag_dispatch_policy"] == "ae_api_only"
    assert command["guardrails"]["ag_direct_database_write_allowed"] is False
    assert command["metadata"] == {
        "metadata_only": True,
        "batch_plan_embedded": False,
        "worker_execution_performed": False,
        "history_write_executed": False,
        "physical_delete_executed": False,
        "storage_mutation_executed": False,
        "database_row_delete_executed": False,
    }
    assert summarize_artifact_retention_scheduled_execution_command(command) == {
        "command_status": "READY",
        "trigger_type": "operator_dispatch",
        "scheduler_status": "DISABLED",
        "execution_mode": "DRY_RUN",
        "candidate_count": 2,
        "selected_count": 1,
        "estimated_deleted_artifacts": 1,
        "estimated_deleted_storage_files": 2,
        "command_created_at": "2026-09-01T02:15:00Z",
        "next_action": "manual_dispatch_after_operator_approval",
    }
    assert validate_artifact_retention_scheduled_execution_command(command) is command
    assert "storage_ref" not in serialized
    assert "postgresql://" not in serialized


def test_artifact_retention_scheduled_execution_command_noop_and_validation_edges() -> None:
    candidate_filter = build_artifact_retention_candidate_filter(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        retention_days="30",
        as_of="2026-09-01T00:00:00Z",
        limit="10",
    )
    collection = build_artifact_retention_candidate_collection(
        [],
        candidate_filter=candidate_filter,
    )
    plan = build_artifact_retention_batch_plan(
        collection,
        checked_at="2026-09-01T02:00:00Z",
    )
    noop = build_artifact_retention_scheduled_execution_command(
        plan,
        command_created_at="2026-09-01T02:05:00Z",
    )

    assert noop["command_status"] == "NOOP"
    assert noop["execution_request"] is None
    assert noop["requested_by"]["actor_id"] == "nex-ae-api"

    with pytest.raises(ArtifactHandoffError) as invalid_plan_exc:
        build_artifact_retention_scheduled_execution_command(
            {**plan, "mode": "EXECUTE"},
            command_created_at="2026-09-01T02:05:00Z",
        )
    assert invalid_plan_exc.value.error_code == (
        "ae.artifact_retention_batch_plan_invalid"
    )
    with pytest.raises(ArtifactHandoffError) as trigger_exc:
        build_artifact_retention_scheduled_execution_command(
            plan,
            trigger_type="daemon",
            command_created_at="2026-09-01T02:05:00Z",
        )
    assert trigger_exc.value.error_code == (
        "ae.artifact_retention_scheduled_trigger_invalid"
    )
    with pytest.raises(ArtifactHandoffError) as type_exc:
        validate_artifact_retention_scheduled_execution_command([])  # type: ignore[arg-type]
    assert type_exc.value.error_code == (
        "ae.artifact_retention_scheduled_command_invalid"
    )
    with pytest.raises(ArtifactHandoffError) as schema_exc:
        validate_artifact_retention_scheduled_execution_command(
            {
                **noop,
                "artifact_retention_scheduled_execution_command_schema_version": (
                    "wrong"
                ),
            }
        )
    assert schema_exc.value.error_code == (
        "ae.artifact_retention_scheduled_command_schema_invalid"
    )

    ready_store = ArtifactRecordStore()
    save_rendered_retention_artifact(
        ready_store,
        artifact_request_id="scheduled-command-validation-old-001",
        updated_at="2026-07-31T00:00:00Z",
    )
    ready_plan = ready_store.plan_retention_batch(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        retention_days="30",
        as_of="2026-09-01T00:00:00Z",
        scan_limit="10",
        checked_at="2026-09-01T02:00:00Z",
    )
    ready_command = build_artifact_retention_scheduled_execution_command(
        ready_plan,
        command_created_at="2026-09-01T02:05:00Z",
    )
    validation_mutations = [
        ({"service_id": "nex-cx"}, "service id"),
        ({"trigger_type": None}, "trigger"),
        ({"scheduler_status": "ENABLED"}, "scheduler"),
        ({"command_status": "RUNNING"}, "status"),
        ({"execution_mode": "EXECUTE"}, "DRY_RUN"),
        ({"tenant_id": " "}, "scope"),
        ({"selected_count": 2, "candidate_count": 1}, "counts"),
        ({"execution_request": None}, "execution request"),
        (
            {
                "command_status": "NOOP",
                "selected_count": 0,
                "candidate_count": 0,
            },
            "NOOP request",
        ),
        (
            {
                "batch_plan_summary": {
                    **ready_command["batch_plan_summary"],
                    "selected_count": 0,
                }
            },
            "summary",
        ),
        (
            {
                "guardrails": {
                    **ready_command["guardrails"],
                    "dry_run_required": False,
                }
            },
            "guardrails",
        ),
        (
            {
                "guardrails": {
                    **ready_command["guardrails"],
                    "ag_direct_database_write_allowed": True,
                }
            },
            "AG boundary",
        ),
        (
            {
                "metadata": {
                    **ready_command["metadata"],
                    "worker_execution_performed": True,
                }
            },
            "metadata",
        ),
        ({"storage_ref": "ae://artifacts/private"}, "private"),
    ]
    for mutation, detail in validation_mutations:
        with pytest.raises(ArtifactHandoffError) as exc_info:
            validate_artifact_retention_scheduled_execution_command(
                {**ready_command, **mutation}
            )
        assert exc_info.value.error_code in {
            "ae.artifact_retention_scheduled_command_invalid",
            "ae.artifact_retention_scheduled_trigger_invalid",
            "ae.artifact_retention_payload_unsafe",
        }
        assert detail in exc_info.value.detail

    request_mutations = [
        ({"method": "GET"}, "route"),
        ({"payload": []}, "payload"),
        (
            {
                "payload": {
                    **ready_command["execution_request"]["payload"],
                    "tenant_id": "other-tenant",
                }
            },
            "scope",
        ),
        (
            {
                "payload": {
                    **ready_command["execution_request"]["payload"],
                    "dry_run": False,
                }
            },
            "dry-run",
        ),
        (
            {
                "payload": {
                    **ready_command["execution_request"]["payload"],
                    "delete_enabled": True,
                }
            },
            "dry-run",
        ),
        (
            {
                "metadata": {
                    **ready_command["execution_request"]["metadata"],
                    "history_write_expected": False,
                }
            },
            "metadata",
        ),
    ]
    for request_patch, detail in request_mutations:
        execution_request = {
            **ready_command["execution_request"],
            **request_patch,
        }
        with pytest.raises(ArtifactHandoffError) as request_exc:
            validate_artifact_retention_scheduled_execution_command(
                {**ready_command, "execution_request": execution_request}
            )
        assert request_exc.value.error_code == (
            "ae.artifact_retention_scheduled_command_invalid"
        )
        assert detail in request_exc.value.detail


def test_artifact_retention_scheduled_job_contract_builds_common_job_payload() -> None:
    store = ArtifactRecordStore()
    save_rendered_retention_artifact(
        store,
        artifact_request_id="scheduled-job-old-001",
        updated_at="2026-07-31T00:00:00Z",
        target_formats=["MD", "HTML_PREVIEW"],
    )
    save_rendered_retention_artifact(
        store,
        artifact_request_id="scheduled-job-old-002",
        updated_at="2026-07-31T01:00:00Z",
        target_formats=["MD"],
    )
    plan = store.plan_retention_batch(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        retention_days="30",
        as_of="2026-09-01T00:00:00Z",
        scan_limit="10",
        max_delete_count="1",
        checked_at="2026-09-01T02:10:00Z",
        requested_by={"actor_type": "service", "actor_id": "nex-ag"},
        idempotency_key="scheduled-job-plan-001",
    )
    command = build_artifact_retention_scheduled_execution_command(
        plan,
        trigger_type="scheduler_tick",
        command_created_at="2026-09-01T02:15:00Z",
        idempotency_key="scheduled-job-command-001",
    )

    payload = build_artifact_retention_scheduled_job_payload(
        command,
        requested_at="2026-09-01T02:16:00Z",
    )
    job = build_artifact_retention_scheduled_job(
        command,
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
        requested_at="2026-09-01T02:16:00Z",
    )
    serialized = json.dumps(job, ensure_ascii=False, sort_keys=True)

    assert payload["payload_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULED_JOB_PAYLOAD_SCHEMA_VERSION
    )
    assert payload["scheduled_command"] == command
    assert payload["command_summary"] == (
        summarize_artifact_retention_scheduled_execution_command(command)
    )
    assert payload["idempotency_key"] == "scheduled-job-command-001"
    assert payload["redaction_summary"] == {
        "metadata_only": True,
        "scheduled_command_embedded": True,
        "batch_plan_embedded": False,
        "artifact_payload_included": False,
        "prompt_content_included": False,
        "generation_output_included": False,
        "storage_locator_included": False,
        "database_url_included": False,
    }
    assert validate_artifact_retention_scheduled_job_payload(payload) is payload
    assert job["artifact_retention_scheduled_job_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULED_JOB_SCHEMA_VERSION
    )
    assert job["job_schema_version"] == "common_job.v1"
    assert job["job_id"] == artifact_retention_scheduled_job_id(command["command_id"])
    assert job["job_type"] == AE_ARTIFACT_RETENTION_SCHEDULED_JOB_TYPE
    assert job["status"] == "QUEUED"
    assert job["trace_id"] == TRACE_ID
    assert job["request_id"] == REQUEST_ID
    assert job["subject_ref"] == {
        "type": "ae.artifact_retention.scheduled_execution",
        "id": command["command_id"],
    }
    assert job["idempotency_key"] == (
        artifact_retention_scheduled_job_idempotency_key(payload)
    )
    assert job["attempt_count"] == 0
    assert job["max_attempts"] == 3
    assert job["retryable"] is True
    assert job["created_at"] == "2026-09-01T02:16:00Z"
    assert job["updated_at"] == "2026-09-01T02:16:00Z"
    assert job["payload"] == payload
    assert job["links"] == {
        "ae_retention_batch_plan": "/api/v1/artifact-retention/batch-plan",
        "ae_retention_purge": "/api/v1/artifact-retention/purge",
        "ae_retention_history": "/api/v1/artifact-retention/executions",
    }
    assert summarize_artifact_retention_scheduled_job(job) == {
        "job_id": job["job_id"],
        "job_type": "ae.artifact_retention.scheduled_execution",
        "status": "QUEUED",
        "command_id": command["command_id"],
        "source_plan_id": plan["plan_id"],
        "trigger_type": "scheduler_tick",
        "execution_mode": "DRY_RUN",
        "candidate_count": 2,
        "selected_count": 1,
        "history_write_expected": True,
        "physical_delete_automation_enabled": False,
    }
    assert validate_artifact_retention_scheduled_job(job) is job
    assert "storage_ref" not in serialized
    assert "postgresql://" not in serialized
    assert "nuri1004" not in serialized


def test_artifact_retention_scheduled_job_contract_noop_and_validation_edges() -> None:
    candidate_filter = build_artifact_retention_candidate_filter(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        retention_days="30",
        as_of="2026-09-01T00:00:00Z",
        limit="10",
    )
    noop_plan = build_artifact_retention_batch_plan(
        build_artifact_retention_candidate_collection(
            [],
            candidate_filter=candidate_filter,
        ),
        checked_at="2026-09-01T02:10:00Z",
    )
    noop_command = build_artifact_retention_scheduled_execution_command(
        noop_plan,
        command_created_at="2026-09-01T02:15:00Z",
    )
    with pytest.raises(ArtifactHandoffError) as noop_payload_exc:
        build_artifact_retention_scheduled_job_payload(noop_command)
    assert noop_payload_exc.value.error_code == (
        "ae.artifact_retention_scheduled_job_not_ready"
    )
    with pytest.raises(ArtifactHandoffError) as noop_job_exc:
        build_artifact_retention_scheduled_job(
            noop_command,
            trace_id=TRACE_ID,
            request_id=REQUEST_ID,
        )
    assert noop_job_exc.value.error_code == (
        "ae.artifact_retention_scheduled_job_not_ready"
    )

    store = ArtifactRecordStore()
    save_rendered_retention_artifact(
        store,
        artifact_request_id="scheduled-job-edge-old-001",
        updated_at="2026-07-31T00:00:00Z",
    )
    command = build_artifact_retention_scheduled_execution_command(
        store.plan_retention_batch(
            tenant_id="tenant-001",
            workspace_id="workspace-001",
            owner_user_id="user-001",
            retention_days="30",
            as_of="2026-09-01T00:00:00Z",
            scan_limit="10",
            checked_at="2026-09-01T02:10:00Z",
        ),
        command_created_at="2026-09-01T02:15:00Z",
        idempotency_key="scheduled-job-edge-command-001",
    )
    payload = build_artifact_retention_scheduled_job_payload(
        command,
        requested_at="2026-09-01T02:16:00Z",
    )
    job = build_artifact_retention_scheduled_job(
        command,
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
        requested_at="2026-09-01T02:16:00Z",
    )

    with pytest.raises(ArtifactHandoffError) as payload_type_exc:
        validate_artifact_retention_scheduled_job_payload([])  # type: ignore[arg-type]
    assert payload_type_exc.value.error_code == (
        "ae.artifact_retention_scheduled_job_payload_invalid"
    )
    with pytest.raises(ArtifactHandoffError) as payload_schema_exc:
        validate_artifact_retention_scheduled_job_payload(
            {**payload, "payload_schema_version": "wrong"}
        )
    assert payload_schema_exc.value.error_code == (
        "ae.artifact_retention_scheduled_job_payload_schema_invalid"
    )

    payload_mutations = [
        ({"scheduled_command": []}, "scheduled_command"),
        ({"estimated_deleted_counts": []}, "estimated_deleted_counts"),
        ({"requested_by": []}, "requested_by"),
    ]
    for mutation, detail in payload_mutations:
        with pytest.raises(ArtifactHandoffError) as exc_info:
            validate_artifact_retention_scheduled_job_payload(
                {**payload, **mutation}
            )
        assert exc_info.value.error_code == (
            "ae.artifact_retention_scheduled_job_payload_invalid"
        )
        assert detail in exc_info.value.detail

    mismatched_command_id = deepcopy(payload)
    mismatched_command_id["scheduled_command"]["command_id"] = "other-command"
    with pytest.raises(ArtifactHandoffError) as command_id_exc:
        validate_artifact_retention_scheduled_job_payload(mismatched_command_id)
    assert command_id_exc.value.error_code == (
        "ae.artifact_retention_scheduled_job_payload_invalid"
    )
    assert "command command_id" in command_id_exc.value.detail

    mismatched_estimates = deepcopy(payload)
    mismatched_estimates["estimated_deleted_counts"]["artifacts"] = 7
    with pytest.raises(ArtifactHandoffError) as estimates_exc:
        validate_artifact_retention_scheduled_job_payload(mismatched_estimates)
    assert estimates_exc.value.error_code == (
        "ae.artifact_retention_scheduled_job_payload_invalid"
    )
    assert "estimates" in estimates_exc.value.detail

    mismatched_summary = deepcopy(payload)
    mismatched_summary["command_summary"]["selected_count"] = 99
    with pytest.raises(ArtifactHandoffError) as summary_exc:
        validate_artifact_retention_scheduled_job_payload(mismatched_summary)
    assert summary_exc.value.error_code == (
        "ae.artifact_retention_scheduled_job_payload_invalid"
    )
    assert "summary" in summary_exc.value.detail

    bad_redaction = deepcopy(payload)
    bad_redaction["redaction_summary"]["storage_locator_included"] = True
    with pytest.raises(ArtifactHandoffError) as redaction_exc:
        validate_artifact_retention_scheduled_job_payload(bad_redaction)
    assert redaction_exc.value.error_code == (
        "ae.artifact_retention_scheduled_job_payload_invalid"
    )
    assert "redaction" in redaction_exc.value.detail

    unsafe_payload = {**payload, "database_url": "postgresql://private"}
    with pytest.raises(ArtifactHandoffError) as unsafe_payload_exc:
        validate_artifact_retention_scheduled_job_payload(unsafe_payload)
    assert unsafe_payload_exc.value.error_code == (
        "ae.artifact_retention_payload_unsafe"
    )

    with pytest.raises(ArtifactHandoffError) as invalid_trace_exc:
        build_artifact_retention_scheduled_job(
            command,
            trace_id="bad-trace",
            request_id=REQUEST_ID,
        )
    assert invalid_trace_exc.value.error_code == (
        "ae.artifact_retention_scheduled_job_trace_id_invalid"
    )
    with pytest.raises(ArtifactHandoffError) as missing_request_exc:
        build_artifact_retention_scheduled_job(
            command,
            trace_id=TRACE_ID,
            request_id=" ",
        )
    assert missing_request_exc.value.error_code == (
        "ae.artifact_retention_scheduled_job_request_id_required"
    )

    with pytest.raises(ArtifactHandoffError) as job_type_exc:
        validate_artifact_retention_scheduled_job([])  # type: ignore[arg-type]
    assert job_type_exc.value.error_code == (
        "ae.artifact_retention_scheduled_job_invalid"
    )
    job_mutations = [
        (
            {"job_schema_version": "wrong"},
            "ae.artifact_retention_scheduled_job_invalid",
            "job_schema_version",
        ),
        (
            {"artifact_retention_scheduled_job_schema_version": "wrong"},
            "ae.artifact_retention_scheduled_job_schema_invalid",
            "schema version",
        ),
        (
            {"job_type": "ae.other"},
            "ae.artifact_retention_scheduled_job_invalid",
            "type",
        ),
        (
            {"subject_ref": {"type": "ae.other", "id": payload["command_id"]}},
            "ae.artifact_retention_scheduled_job_invalid",
            "subject",
        ),
        (
            {"created_at": "2026-09-01T02:17:00Z"},
            "ae.artifact_retention_scheduled_job_invalid",
            "created_at",
        ),
        (
            {"max_attempts": 1},
            "ae.artifact_retention_scheduled_job_invalid",
            "max attempts",
        ),
        (
            {"retryable": False},
            "ae.artifact_retention_scheduled_job_invalid",
            "retryable",
        ),
        (
            {"links": {}},
            "ae.artifact_retention_scheduled_job_invalid",
            "links",
        ),
    ]
    for mutation, error_code, detail in job_mutations:
        with pytest.raises(ArtifactHandoffError) as exc_info:
            validate_artifact_retention_scheduled_job({**job, **mutation})
        assert exc_info.value.error_code == error_code
        assert detail in exc_info.value.detail


def test_artifact_retention_scheduled_job_admission_plans_and_enqueues_once() -> None:
    store = ArtifactRecordStore()
    save_rendered_retention_artifact(
        store,
        artifact_request_id="scheduled-job-admission-old-001",
        updated_at="2026-07-31T00:00:00Z",
        target_formats=["MD", "HTML_PREVIEW"],
    )
    save_rendered_retention_artifact(
        store,
        artifact_request_id="scheduled-job-admission-old-002",
        updated_at="2026-07-31T01:00:00Z",
        target_formats=["MD"],
    )
    plan = store.plan_retention_batch(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        retention_days="30",
        as_of="2026-09-01T00:00:00Z",
        scan_limit="10",
        max_delete_count="1",
        checked_at="2026-09-01T02:10:00Z",
        requested_by={"actor_type": "service", "actor_id": "nex-ag"},
        idempotency_key="scheduled-job-admission-plan-001",
    )
    expected_idempotency = artifact_retention_scheduled_job_admission_idempotency_key(
        plan,
        trigger_type="scheduler_tick",
    )

    admission = build_artifact_retention_scheduled_job_admission(
        plan,
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
        requested_at="2026-09-01T02:16:00Z",
    )
    queue = InMemoryJobQueue()
    result = enqueue_artifact_retention_scheduled_job(queue, admission)
    duplicate = enqueue_artifact_retention_scheduled_job(queue, admission)
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)

    assert admission[
        "artifact_retention_scheduled_job_admission_schema_version"
    ] == AE_ARTIFACT_RETENTION_SCHEDULED_JOB_ADMISSION_SCHEMA_VERSION
    assert admission["admission_status"] == "READY"
    assert admission["enqueue_required"] is True
    assert admission["skip_reason"] is None
    assert admission["idempotency_key"] == expected_idempotency
    assert admission["command"]["idempotency_key"] == expected_idempotency
    assert admission["job"]["idempotency_key"] == expected_idempotency
    assert admission["requested_at"] == "2026-09-01T02:16:00Z"
    assert admission["command"]["command_created_at"] == "2026-09-01T02:16:00Z"
    assert admission["queue_admission"] == {
        "queue_service_id": "nex-ae-api",
        "queue_backend": "service_job_queue",
        "target_job_type": "ae.artifact_retention.scheduled_execution",
        "job_enqueued": False,
        "worker_execution_performed": False,
        "scheduler_daemon_started": False,
        "physical_delete_automation_enabled": False,
    }
    assert admission["job_summary"] == (
        summarize_artifact_retention_scheduled_job(admission["job"])
    )
    assert validate_artifact_retention_scheduled_job_admission(
        admission
    ) is admission
    assert result[
        "artifact_retention_scheduled_job_enqueue_result_schema_version"
    ] == AE_ARTIFACT_RETENTION_SCHEDULED_JOB_ENQUEUE_RESULT_SCHEMA_VERSION
    assert result["enqueue_status"] == "ENQUEUED"
    assert result["job_enqueued"] is True
    assert result["duplicate_returned"] is False
    assert result["queue_admission"]["job_enqueued"] is True
    assert result["enqueued_job"] == queue.get_job(admission["job_id"])
    assert duplicate["enqueued_job"] == result["enqueued_job"]
    assert len(queue.list_jobs(job_type=AE_ARTIFACT_RETENTION_SCHEDULED_JOB_TYPE)) == 1
    assert validate_artifact_retention_scheduled_job_enqueue_result(result) is result
    assert "storage_ref" not in serialized
    assert "postgresql://" not in serialized
    assert "nuri1004" not in serialized


def test_artifact_retention_scheduled_job_admission_skips_noop_without_queue() -> None:
    candidate_filter = build_artifact_retention_candidate_filter(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        retention_days="30",
        as_of="2026-09-01T00:00:00Z",
        limit="10",
    )
    plan = build_artifact_retention_batch_plan(
        build_artifact_retention_candidate_collection(
            [],
            candidate_filter=candidate_filter,
        ),
        checked_at="2026-09-01T02:10:00Z",
    )
    admission = build_artifact_retention_scheduled_job_admission(
        plan,
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
    )

    class ExplodingQueue:
        def enqueue(self, job: dict[str, Any]) -> dict[str, Any]:
            raise AssertionError("NOOP admissions must not touch the queue")

    result = enqueue_artifact_retention_scheduled_job(ExplodingQueue(), admission)

    assert admission["admission_status"] == "SKIPPED"
    assert admission["enqueue_required"] is False
    assert admission["skip_reason"] == "no_retention_candidates"
    assert admission["job_id"] is None
    assert admission["job"] is None
    assert admission["job_summary"] is None
    assert admission["requested_at"] == "2026-09-01T02:10:00Z"
    assert result["enqueue_status"] == "SKIPPED"
    assert result["job_enqueued"] is False
    assert result["enqueued_job"] is None
    assert result["queue_admission"]["job_enqueued"] is False
    assert validate_artifact_retention_scheduled_job_enqueue_result(result) is result


def test_artifact_retention_scheduled_job_admission_validation_edges() -> None:
    store = ArtifactRecordStore()
    save_rendered_retention_artifact(
        store,
        artifact_request_id="scheduled-job-admission-edge-old-001",
        updated_at="2026-07-31T00:00:00Z",
    )
    ready_plan = store.plan_retention_batch(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        retention_days="30",
        as_of="2026-09-01T00:00:00Z",
        scan_limit="10",
        checked_at="2026-09-01T02:10:00Z",
    )
    ready_admission = build_artifact_retention_scheduled_job_admission(
        ready_plan,
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
        requested_at="2026-09-01T02:16:00Z",
        idempotency_key="scheduled-job-admission-edge-001",
    )
    noop_plan = build_artifact_retention_batch_plan(
        build_artifact_retention_candidate_collection(
            [],
            candidate_filter=build_artifact_retention_candidate_filter(
                tenant_id="tenant-001",
                workspace_id="workspace-001",
                owner_user_id="user-001",
                retention_days="30",
                as_of="2026-09-01T00:00:00Z",
                limit="10",
            ),
        ),
        checked_at="2026-09-01T02:10:00Z",
    )
    noop_admission = build_artifact_retention_scheduled_job_admission(
        noop_plan,
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
    )

    with pytest.raises(ArtifactHandoffError) as trace_exc:
        build_artifact_retention_scheduled_job_admission(
            ready_plan,
            trace_id="bad-trace",
            request_id=REQUEST_ID,
        )
    assert trace_exc.value.error_code == (
        "ae.artifact_retention_scheduled_job_trace_id_invalid"
    )
    with pytest.raises(ArtifactHandoffError) as request_exc:
        build_artifact_retention_scheduled_job_admission(
            ready_plan,
            trace_id=TRACE_ID,
            request_id=" ",
        )
    assert request_exc.value.error_code == (
        "ae.artifact_retention_scheduled_job_request_id_required"
    )
    with pytest.raises(ArtifactHandoffError) as type_exc:
        validate_artifact_retention_scheduled_job_admission([])  # type: ignore[arg-type]
    assert type_exc.value.error_code == (
        "ae.artifact_retention_scheduled_job_admission_invalid"
    )
    with pytest.raises(ArtifactHandoffError) as schema_exc:
        validate_artifact_retention_scheduled_job_admission(
            {
                **ready_admission,
                "artifact_retention_scheduled_job_admission_schema_version": "wrong",
            }
        )
    assert schema_exc.value.error_code == (
        "ae.artifact_retention_scheduled_job_admission_schema_invalid"
    )

    admission_mutations = [
        ({"service_id": "nex-cx"}, "service id"),
        ({"command_summary": []}, "command_summary"),
        (
            {
                "command_summary": {
                    **ready_admission["command_summary"],
                    "selected_count": 99,
                }
            },
            "command summary",
        ),
        ({"queue_admission": []}, "queue_admission"),
        (
            {
                "queue_admission": {
                    **ready_admission["queue_admission"],
                    "job_enqueued": True,
                }
            },
            "queue admission",
        ),
        ({"tenant_id": "other-tenant"}, "command tenant_id"),
        ({"job": None}, "READY admission"),
        ({"skip_reason": "no_retention_candidates"}, "READY admission"),
        ({"storage_ref": "ae://private/file"}, "private"),
    ]
    for mutation, detail in admission_mutations:
        with pytest.raises(ArtifactHandoffError) as exc_info:
            validate_artifact_retention_scheduled_job_admission(
                {**ready_admission, **mutation}
            )
        assert exc_info.value.error_code in {
            "ae.artifact_retention_scheduled_job_admission_invalid",
            "ae.artifact_retention_payload_unsafe",
        }
        assert detail in exc_info.value.detail

    skipped_mutations = [
        ({"admission_status": "READY"}, "skipped admission"),
        ({"enqueue_required": True}, "skipped admission"),
        ({"skip_reason": None}, "skipped admission"),
        ({"job_id": ready_admission["job_id"]}, "skipped admission"),
        ({"job": ready_admission["job"]}, "skipped admission"),
        ({"job_summary": ready_admission["job_summary"]}, "skipped admission"),
    ]
    for mutation, detail in skipped_mutations:
        with pytest.raises(ArtifactHandoffError) as exc_info:
            validate_artifact_retention_scheduled_job_admission(
                {**noop_admission, **mutation}
            )
        assert exc_info.value.error_code == (
            "ae.artifact_retention_scheduled_job_admission_invalid"
        )
        assert detail in exc_info.value.detail

    with pytest.raises(ArtifactHandoffError) as queue_exc:
        enqueue_artifact_retention_scheduled_job(None, ready_admission)  # type: ignore[arg-type]
    assert queue_exc.value.error_code == (
        "ae.artifact_retention_scheduled_job_queue_invalid"
    )

    class FailingQueue:
        def enqueue(self, job: dict[str, Any]) -> dict[str, Any]:
            raise JobQueueError(
                error_code="job.store_unavailable",
                detail="queue is unavailable",
                status_code=503,
            )

    with pytest.raises(ArtifactHandoffError) as failing_queue_exc:
        enqueue_artifact_retention_scheduled_job(FailingQueue(), ready_admission)
    assert failing_queue_exc.value.error_code == (
        "ae.artifact_retention_scheduled_job_admission_failed"
    )
    assert failing_queue_exc.value.retryable is True

    result = enqueue_artifact_retention_scheduled_job(
        InMemoryJobQueue(),
        ready_admission,
    )
    with pytest.raises(ArtifactHandoffError) as result_type_exc:
        validate_artifact_retention_scheduled_job_enqueue_result([])  # type: ignore[arg-type]
    assert result_type_exc.value.error_code == (
        "ae.artifact_retention_scheduled_job_enqueue_result_invalid"
    )
    with pytest.raises(ArtifactHandoffError) as result_schema_exc:
        validate_artifact_retention_scheduled_job_enqueue_result(
            {
                **result,
                "artifact_retention_scheduled_job_enqueue_result_schema_version": (
                    "wrong"
                ),
            }
        )
    assert result_schema_exc.value.error_code == (
        "ae.artifact_retention_scheduled_job_enqueue_result_schema_invalid"
    )
    result_mutations = [
        ({"service_id": "nex-cx"}, "service id"),
        ({"command_id": "other-command"}, "admission command_id"),
        ({"queue_admission": []}, "queue admission"),
        ({"enqueue_status": "SKIPPED"}, "queue admission"),
        ({"job_enqueued": False}, "enqueue result"),
        (
            {"enqueued_job": {**result["enqueued_job"], "idempotency_key": "other"}},
            "enqueue result",
        ),
    ]
    for mutation, detail in result_mutations:
        with pytest.raises(ArtifactHandoffError) as exc_info:
            validate_artifact_retention_scheduled_job_enqueue_result(
                {**result, **mutation}
            )
        assert exc_info.value.error_code in {
            "ae.artifact_retention_scheduled_job_admission_invalid",
            "ae.artifact_retention_scheduled_job_enqueue_result_invalid",
            "ae.artifact_retention_scheduled_job_payload_invalid",
        }
        assert detail in exc_info.value.detail


def test_artifact_retention_scheduled_job_collection_filters_queue_jobs() -> None:
    store = ArtifactRecordStore()
    save_rendered_retention_artifact(
        store,
        artifact_request_id="scheduled-job-collection-old-001",
        updated_at="2026-07-31T00:00:00Z",
    )
    plan = store.plan_retention_batch(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        retention_days="30",
        as_of="2026-09-01T00:00:00Z",
        scan_limit="10",
        max_delete_count="1",
        checked_at="2026-09-01T02:10:00Z",
    )
    admission = build_artifact_retention_scheduled_job_admission(
        plan,
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
        trigger_type="operator_dispatch",
        requested_at="2026-09-01T02:16:00Z",
        idempotency_key="scheduled-job-collection-001",
    )
    queue = InMemoryJobQueue()
    enqueue_result = enqueue_artifact_retention_scheduled_job(queue, admission)

    collection = build_artifact_retention_scheduled_job_collection(
        queue.list_jobs(job_type=AE_ARTIFACT_RETENTION_SCHEDULED_JOB_TYPE),
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        status="queued",
        limit="5",
    )
    empty_collection = build_artifact_retention_scheduled_job_collection(
        queue.list_jobs(job_type=AE_ARTIFACT_RETENTION_SCHEDULED_JOB_TYPE),
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="other-user",
        status="QUEUED",
        limit="5",
    )
    serialized = json.dumps(collection, ensure_ascii=False, sort_keys=True)

    assert collection["artifact_retention_scheduled_job_collection_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULED_JOB_COLLECTION_SCHEMA_VERSION
    )
    assert collection["filter"] == {
        "tenant_id": "tenant-001",
        "workspace_id": "workspace-001",
        "owner_user_id": "user-001",
        "status": "QUEUED",
        "job_type": AE_ARTIFACT_RETENTION_SCHEDULED_JOB_TYPE,
        "limit": 5,
    }
    assert collection["count"] == 1
    assert collection["items"][0]["job_id"] == enqueue_result["job_id"]
    assert collection["items"][0]["payload"]["trigger_type"] == "operator_dispatch"
    assert collection["summary"]["total_jobs"] == 1
    assert collection["summary"]["status_counts"]["QUEUED"] == 1
    assert collection["summary"]["estimated_deleted_counts"]["artifacts"] == 1
    assert collection["metadata"] == {
        "metadata_only": True,
        "queue_backend": "service_job_queue",
        "physical_delete_automation_enabled": False,
    }
    assert empty_collection["count"] == 0
    assert validate_artifact_retention_scheduled_job_collection(collection) is collection
    assert normalize_artifact_retention_scheduled_job_status("running") == "RUNNING"
    assert normalize_artifact_retention_scheduled_job_status(None) is None
    assert "storage_ref" not in serialized


def test_artifact_retention_scheduled_job_collection_validation_edges() -> None:
    collection = build_artifact_retention_scheduled_job_collection(
        [],
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
    )

    with pytest.raises(ArtifactHandoffError) as type_exc:
        build_artifact_retention_scheduled_job_collection(  # type: ignore[arg-type]
            {},
            tenant_id="tenant-001",
            workspace_id="workspace-001",
            owner_user_id="user-001",
        )
    assert type_exc.value.error_code == "ae.artifact_retention_scheduled_jobs_invalid"

    edge_cases = (
        (
            lambda: build_artifact_retention_scheduled_job_collection(
                [],
                tenant_id=" ",
                workspace_id="workspace-001",
                owner_user_id="user-001",
            ),
            "ae.artifact_collection_scope_required",
        ),
        (
            lambda: normalize_artifact_retention_scheduled_job_status("WAITING"),
            "ae.artifact_retention_scheduled_job_status_invalid",
        ),
        (
            lambda: normalize_artifact_retention_scheduled_job_status(True),
            "ae.artifact_retention_scheduled_job_status_invalid",
        ),
        (
            lambda: validate_artifact_retention_scheduled_job_collection([]),  # type: ignore[arg-type]
            "ae.artifact_retention_scheduled_jobs_invalid",
        ),
        (
            lambda: validate_artifact_retention_scheduled_job_collection(
                {
                    **collection,
                    "artifact_retention_scheduled_job_collection_schema_version": (
                        "wrong"
                    ),
                }
            ),
            "ae.artifact_retention_scheduled_jobs_schema_invalid",
        ),
        (
            lambda: validate_artifact_retention_scheduled_job_collection(
                {
                    **collection,
                    "filter": {
                        **collection["filter"],
                        "job_type": "ae.other_job",
                    },
                }
            ),
            "ae.artifact_retention_scheduled_jobs_invalid",
        ),
        (
            lambda: validate_artifact_retention_scheduled_job_collection(
                {**collection, "count": 99}
            ),
            "ae.artifact_retention_scheduled_jobs_invalid",
        ),
        (
            lambda: validate_artifact_retention_scheduled_job_collection(
                {
                    **collection,
                    "metadata": {
                        **collection["metadata"],
                        "physical_delete_automation_enabled": True,
                    },
                }
            ),
            "ae.artifact_retention_scheduled_jobs_invalid",
        ),
    )
    for call, error_code in edge_cases:
        with pytest.raises(ArtifactHandoffError) as exc_info:
            call()
        assert exc_info.value.error_code == error_code


def test_artifact_retention_scheduled_worker_once_runs_dry_run_history() -> None:
    store = ArtifactRecordStore()
    history_store = ArtifactRetentionExecutionHistoryStore()
    first = save_rendered_retention_artifact(
        store,
        artifact_request_id="scheduled-worker-runner-old-001",
        updated_at="2026-07-31T00:00:00Z",
        target_formats=["MD", "HTML_PREVIEW"],
    )
    save_rendered_retention_artifact(
        store,
        artifact_request_id="scheduled-worker-runner-old-002",
        updated_at="2026-07-31T01:00:00Z",
        target_formats=["MD"],
    )
    plan = store.plan_retention_batch(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        retention_days="30",
        as_of="2026-09-01T00:00:00Z",
        scan_limit="10",
        max_delete_count="1",
        checked_at="2026-09-01T02:10:00Z",
    )
    admission = build_artifact_retention_scheduled_job_admission(
        plan,
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
        requested_at="2026-09-01T02:16:00Z",
    )
    queue = InMemoryJobQueue()
    enqueue_artifact_retention_scheduled_job(queue, admission)
    heartbeat_store = InMemoryWorkerHeartbeatStore()
    heartbeat_emitter = WorkerHeartbeatEmitter(
        service_id="nex-ae-api",
        worker_id="ae-retention-worker-test-001",
        worker_type=AE_ARTIFACT_RETENTION_SCHEDULED_WORKER_TYPE,
        store=heartbeat_store,
        started_at="2026-09-01T02:16:00Z",
    )

    execution = run_artifact_retention_scheduled_worker_once(
        job_queue=queue,
        artifact_store=store,
        history_store=history_store,
        worker_id="ae-retention-worker-test-001",
        worker_heartbeat_emitter=heartbeat_emitter,
        clock=lambda: "2026-09-01T02:20:00Z",
    )
    final_job = queue.get_job(admission["job_id"])
    heartbeat = heartbeat_store.get_heartbeat(
        "nex-ae-api",
        "ae-retention-worker-test-001",
    )

    assert execution.status == "SUCCEEDED"
    assert execution.job["status"] == "RUNNING"
    assert execution.completed_job["status"] == "SUCCEEDED"
    assert execution.handler_result["worker_status"] == "SUCCEEDED"
    assert execution.handler_result["history"]["history_written"] is True
    assert execution.handler_result["execution"]["mode"] == "DRY_RUN"
    assert final_job["status"] == "SUCCEEDED"
    assert final_job["attempt_count"] == 1
    assert heartbeat["status"] == "IDLE"
    assert heartbeat["active_job_id"] is None
    persisted_history = history_store.list_executions(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
    )
    assert persisted_history[0]["retention_execution_id"] == (
        execution.handler_result["history"]["retention_execution_id"]
    )
    assert execution.handler_result["trigger_type"] == "scheduler_tick"
    assert store.get(first["artifact_id"]) is not None


def test_artifact_retention_scheduled_worker_batch_processes_until_idle() -> None:
    store = ArtifactRecordStore()
    history_store = ArtifactRetentionExecutionHistoryStore()
    save_rendered_retention_artifact(
        store,
        artifact_request_id="scheduled-worker-batch-old-001",
        updated_at="2026-07-31T00:00:00Z",
    )
    plan = store.plan_retention_batch(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        retention_days="30",
        as_of="2026-09-01T00:00:00Z",
        scan_limit="10",
        checked_at="2026-09-01T02:10:00Z",
    )
    admission = build_artifact_retention_scheduled_job_admission(
        plan,
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
        requested_at="2026-09-01T02:16:00Z",
    )
    queue = InMemoryJobQueue()
    enqueue_artifact_retention_scheduled_job(queue, admission)

    batch = run_artifact_retention_scheduled_worker_batch(
        job_queue=queue,
        artifact_store=store,
        history_store=history_store,
        worker_id="ae-retention-worker-batch-001",
        max_jobs=3,
        clock=lambda: "2026-09-01T02:20:00Z",
    )
    summary = batch.to_summary()

    assert batch.claimed_count == 1
    assert batch.succeeded_count == 1
    assert batch.idle_count == 1
    assert summary["service_id"] == "nex-ae-api"
    assert summary["worker_type"] == AE_ARTIFACT_RETENTION_SCHEDULED_WORKER_TYPE
    assert summary["job_type"] == AE_ARTIFACT_RETENTION_SCHEDULED_JOB_TYPE
    assert summary["executions"][0]["handler_result"]["worker_status"] == "SUCCEEDED"
    assert queue.get_job(admission["job_id"])["status"] == "SUCCEEDED"


def test_artifact_retention_scheduled_worker_adapter_edges() -> None:
    store = ArtifactRecordStore()
    save_rendered_retention_artifact(
        store,
        artifact_request_id="scheduled-worker-edge-runner-old-001",
        updated_at="2026-07-31T00:00:00Z",
    )
    admission = build_artifact_retention_scheduled_job_admission(
        store.plan_retention_batch(
            tenant_id="tenant-001",
            workspace_id="workspace-001",
            owner_user_id="user-001",
            retention_days="30",
            as_of="2026-09-01T00:00:00Z",
            scan_limit="10",
            checked_at="2026-09-01T02:10:00Z",
        ),
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
        requested_at="2026-09-01T02:16:00Z",
    )
    job = admission["job"]

    command = artifact_retention_scheduled_command_from_job(job)
    assert command == job["payload"]["scheduled_command"]
    persisted_common_job = deepcopy(job)
    persisted_common_job.pop("artifact_retention_scheduled_job_schema_version")
    assert artifact_retention_scheduled_command_from_job(persisted_common_job) == (
        job["payload"]["scheduled_command"]
    )
    assert validate_artifact_retention_scheduled_job(persisted_common_job)[
        "artifact_retention_scheduled_job_schema_version"
    ] == AE_ARTIFACT_RETENTION_SCHEDULED_JOB_SCHEMA_VERSION
    assert build_artifact_retention_scheduled_worker_config(
        worker_id="ae-retention-worker-config-001",
        max_jobs=2,
    ).max_jobs == 2
    with pytest.raises(ArtifactHandoffError) as job_type_exc:
        artifact_retention_scheduled_command_from_job([])  # type: ignore[arg-type]
    assert job_type_exc.value.error_code == (
        "ae.artifact_retention_scheduled_worker_job_invalid"
    )
    with pytest.raises(ArtifactHandoffError) as handler_exc:
        build_artifact_retention_scheduled_worker_handler(
            artifact_store=None,
        )(job)
    assert handler_exc.value.error_code == (
        "ae.artifact_retention_scheduled_worker_store_invalid"
    )

    idle_execution = run_artifact_retention_scheduled_worker_once(
        job_queue=InMemoryJobQueue(),
        artifact_store=store,
        history_store=ArtifactRetentionExecutionHistoryStore(),
        worker_id="ae-retention-worker-idle-001",
        clock=lambda: "2026-09-01T02:20:00Z",
    )
    assert idle_execution.status == "IDLE"
    assert idle_execution.job is None

    failing_queue = InMemoryJobQueue()
    enqueue_artifact_retention_scheduled_job(failing_queue, admission)
    failed_execution = run_artifact_retention_scheduled_worker_once(
        job_queue=failing_queue,
        artifact_store=None,
        history_store=ArtifactRetentionExecutionHistoryStore(),
        worker_id="ae-retention-worker-failing-001",
        clock=lambda: "2026-09-01T02:20:00Z",
    )
    retried_job = failing_queue.get_job(admission["job_id"])

    assert failed_execution.status == "FAILED"
    assert failed_execution.error_code == (
        "ae.artifact_retention_scheduled_worker_store_invalid"
    )
    assert failed_execution.completed_job["status"] == "QUEUED"
    assert retried_job["status"] == "QUEUED"
    assert retried_job["attempt_count"] == 1
    assert retried_job["error"]["error_code"] == (
        "ae.artifact_retention_scheduled_worker_store_invalid"
    )


def test_artifact_retention_scheduled_execution_mock_worker_writes_dry_run_history() -> None:
    store = ArtifactRecordStore()
    history_store = ArtifactRetentionExecutionHistoryStore()
    first = save_rendered_retention_artifact(
        store,
        artifact_request_id="scheduled-worker-old-001",
        updated_at="2026-07-31T00:00:00Z",
        target_formats=["MD", "HTML_PREVIEW"],
    )
    second = save_rendered_retention_artifact(
        store,
        artifact_request_id="scheduled-worker-old-002",
        updated_at="2026-07-31T01:00:00Z",
        target_formats=["MD"],
    )
    plan = store.plan_retention_batch(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        retention_days="30",
        as_of="2026-09-01T00:00:00Z",
        scan_limit="10",
        max_delete_count="1",
        checked_at="2026-09-01T02:30:00Z",
        requested_by={"actor_type": "service", "actor_id": "nex-ag"},
        idempotency_key="scheduled-worker-plan-001",
    )
    command = build_artifact_retention_scheduled_execution_command(
        plan,
        trigger_type="scheduler_tick",
        command_created_at="2026-09-01T02:35:00Z",
        idempotency_key="scheduled-worker-command-001",
    )

    result = run_artifact_retention_scheduled_execution_mock_worker(
        command,
        artifact_store=store,
        history_store=history_store,
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
    )
    execution = result["execution"]
    summary = summarize_artifact_retention_scheduled_execution_worker_result(result)
    listed_history = history_store.list_executions(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
    )
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)

    assert result[
        "artifact_retention_scheduled_execution_worker_result_schema_version"
    ] == AE_ARTIFACT_RETENTION_SCHEDULED_EXECUTION_WORKER_RESULT_SCHEMA_VERSION
    assert result["worker_status"] == "SUCCEEDED"
    assert result["command_id"] == command["command_id"]
    assert execution["mode"] == "DRY_RUN"
    assert execution["execution_status"] == "SUCCEEDED"
    assert execution["selected_count"] == 1
    assert execution["delete_enabled"] is False
    assert execution["storage_mutation_enabled"] is False
    assert execution["database_row_delete_enabled"] is False
    assert result["history"]["history_written"] is True
    assert result["history"]["retention_execution_id"] == execution["execution_id"]
    assert listed_history[0]["execution"]["execution_id"] == execution["execution_id"]
    assert summary == {
        "worker_status": "SUCCEEDED",
        "trigger_type": "scheduler_tick",
        "command_status": "READY",
        "execution_mode": "DRY_RUN",
        "candidate_count": 2,
        "selected_count": 1,
        "history_written": True,
        "retention_execution_id": execution["execution_id"],
    }
    assert store.get(first["artifact_id"]) is not None
    assert store.get(second["artifact_id"]) is not None
    assert "storage_ref" not in serialized


def test_artifact_retention_scheduled_execution_mock_worker_noop_and_edges() -> None:
    candidate_filter = build_artifact_retention_candidate_filter(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        retention_days="30",
        as_of="2026-09-01T00:00:00Z",
        limit="10",
    )
    plan = build_artifact_retention_batch_plan(
        build_artifact_retention_candidate_collection(
            [],
            candidate_filter=candidate_filter,
        ),
        checked_at="2026-09-01T02:30:00Z",
    )
    noop_command = build_artifact_retention_scheduled_execution_command(
        plan,
        command_created_at="2026-09-01T02:35:00Z",
    )
    noop_result = run_artifact_retention_scheduled_execution_mock_worker(
        noop_command,
        artifact_store=ArtifactRecordStore(),
        history_store=ArtifactRetentionExecutionHistoryStore(),
    )

    assert noop_result["worker_status"] == "NOOP"
    assert noop_result["execution"] is None
    assert noop_result["history"]["history_written"] is False
    assert summarize_artifact_retention_scheduled_execution_worker_result(
        noop_result
    )["retention_execution_id"] is None

    with pytest.raises(ArtifactHandoffError) as store_exc:
        run_artifact_retention_scheduled_execution_mock_worker(
            noop_command,
            artifact_store=None,
        )
    assert store_exc.value.error_code == (
        "ae.artifact_retention_scheduled_worker_store_invalid"
    )
    with pytest.raises(ArtifactHandoffError) as history_exc:
        run_artifact_retention_scheduled_execution_mock_worker(
            noop_command,
            artifact_store=ArtifactRecordStore(),
            history_store=object(),
        )
    assert history_exc.value.error_code == (
        "ae.artifact_retention_scheduled_worker_history_invalid"
    )
    with pytest.raises(ArtifactHandoffError) as type_exc:
        validate_artifact_retention_scheduled_execution_worker_result([])  # type: ignore[arg-type]
    assert type_exc.value.error_code == (
        "ae.artifact_retention_scheduled_worker_result_invalid"
    )
    with pytest.raises(ArtifactHandoffError) as schema_exc:
        validate_artifact_retention_scheduled_execution_worker_result(
            {
                **noop_result,
                "artifact_retention_scheduled_execution_worker_result_schema_version": (
                    "wrong"
                ),
            }
        )
    assert schema_exc.value.error_code == (
        "ae.artifact_retention_scheduled_worker_result_schema_invalid"
    )

    validation_mutations = [
        ({"service_id": "nex-cx"}, "service id"),
        ({"worker_status": "RUNNING"}, "status"),
        ({"command_summary": []}, "command_summary"),
        (
            {
                "command_summary": {
                    **noop_result["command_summary"],
                    "trigger_type": "operator_dispatch",
                }
            },
            "command summary",
        ),
        (
            {
                "history": {
                    **noop_result["history"],
                    "retention_execution_id": "unexpected",
                }
            },
            "NOOP result",
        ),
        (
            {
                "metadata": {
                    **noop_result["metadata"],
                    "storage_mutation_executed": True,
                }
            },
            "metadata",
        ),
        ({"storage_ref": "ae://private/file.md"}, "private"),
    ]
    for mutation, detail in validation_mutations:
        with pytest.raises(ArtifactHandoffError) as exc_info:
            validate_artifact_retention_scheduled_execution_worker_result(
                {**noop_result, **mutation}
            )
        assert exc_info.value.error_code in {
            "ae.artifact_retention_scheduled_worker_result_invalid",
            "ae.artifact_retention_payload_unsafe",
        }
        assert detail in exc_info.value.detail

    ready_store = ArtifactRecordStore()
    save_rendered_retention_artifact(
        ready_store,
        artifact_request_id="scheduled-worker-edge-old-001",
        updated_at="2026-07-31T00:00:00Z",
    )
    ready_command = build_artifact_retention_scheduled_execution_command(
        ready_store.plan_retention_batch(
            tenant_id="tenant-001",
            workspace_id="workspace-001",
            owner_user_id="user-001",
            retention_days="30",
            as_of="2026-09-01T00:00:00Z",
            scan_limit="10",
            checked_at="2026-09-01T02:30:00Z",
        ),
        command_created_at="2026-09-01T02:35:00Z",
    )
    ready_result = run_artifact_retention_scheduled_execution_mock_worker(
        ready_command,
        artifact_store=ready_store,
    )
    ready_execution = ready_result["execution"]
    execute_like_evidence = build_artifact_retention_execution(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        mode="EXECUTE",
        execution_status="SUCCEEDED",
        retention_days="30",
        as_of="2026-09-01T00:00:00Z",
        checked_at="2026-09-01T02:30:00Z",
        scan_limit="10",
        max_delete_count="20",
        candidate_count=1,
        selected_count=1,
        deleted_counts={
            "artifacts": 1,
            "source_refs": 0,
            "versions": 0,
            "render_jobs": 0,
            "files": 0,
            "links": 0,
            "storage_files": 0,
        },
        delete_enabled=True,
        storage_mutation_enabled=True,
        database_row_delete_enabled=True,
    )

    ready_mutations = [
        ({"execution": None}, "command summary"),
        (
            {
                "command_summary": {
                    **ready_result["command_summary"],
                    "command_status": "NOOP",
                }
            },
            "command summary",
        ),
        (
            {"execution": execute_like_evidence},
            "safe dry-run",
        ),
        (
            {
                "history": {
                    **ready_result["history"],
                    "history_written": None,
                }
            },
            "history flag",
        ),
        (
            {
                "history": {
                    **ready_result["history"],
                    "retention_execution_id": "unexpected",
                }
            },
            "history",
        ),
        (
            {
                "history": {
                    "history_written": True,
                    "retention_execution_id": "wrong",
                    "execution_payload_hash": "0" * 64,
                    "created_at": "2026-09-01T02:35:00Z",
                }
            },
            "history reference",
        ),
    ]
    for mutation, detail in ready_mutations:
        with pytest.raises(ArtifactHandoffError) as ready_exc:
            validate_artifact_retention_scheduled_execution_worker_result(
                {**ready_result, **mutation}
            )
        assert ready_exc.value.error_code == (
            "ae.artifact_retention_scheduled_worker_result_invalid"
        )
        assert detail in ready_exc.value.detail


def test_sqlalchemy_artifact_record_store_plans_retention_batch_with_sqlite() -> None:
    session_factory = sqlite_artifact_session_factory()
    storage = InMemoryRenderedArtifactStorage()
    store = SqlAlchemyArtifactRecordStore(
        session_factory,
        rendered_storage=storage,
    )
    first = save_rendered_retention_artifact(
        store,
        artifact_request_id="sql-retention-plan-old-001",
        updated_at="2026-07-31T00:00:00Z",
    )
    save_rendered_retention_artifact(
        store,
        artifact_request_id="sql-retention-plan-old-002",
        updated_at="2026-07-31T01:00:00Z",
    )

    plan = store.plan_retention_batch(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        retention_days=30,
        as_of="2026-09-01T00:00:00Z",
        scan_limit=10,
        max_delete_count=1,
        checked_at="2026-09-01T02:25:00Z",
    )

    assert plan["plan_status"] == "READY"
    assert plan["candidate_count"] == 2
    assert plan["selected_count"] == 1
    assert plan["selected_candidates"][0]["artifact_id"] == first["artifact_id"]
    assert plan["estimated_deleted_counts"]["files"] == 2
    assert plan["estimated_deleted_counts"]["links"] == 4
    assert store.get(first["artifact_id"]) is not None
    assert len(storage.rendered_artifact_files) == 4


def test_artifact_record_store_purge_retention_candidates_is_safe_by_default() -> None:
    store = ArtifactRecordStore()
    old_deleted = save_rendered_retention_artifact(
        store,
        artifact_request_id="retention-purge-old-001",
        updated_at="2026-07-31T00:00:00Z",
    )
    save_rendered_retention_artifact(
        store,
        artifact_request_id="retention-purge-recent-001",
        updated_at="2026-08-31T00:00:00Z",
    )
    dry_run = store.purge_retention_candidates(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        retention_days="30",
        as_of="2026-09-01T00:00:00Z",
        checked_at="2026-09-01T02:00:00Z",
        scan_limit=10,
        max_delete_count=1,
        requested_by={"actor_type": "service", "actor_id": "nex-ag"},
        idempotency_key="retention-dry-run-001",
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
    )
    blocked = store.purge_retention_candidates(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        retention_days=30,
        as_of="2026-09-01T00:00:00Z",
        checked_at="2026-09-01T02:05:00Z",
        dry_run=False,
        max_delete_count=1,
    )

    assert dry_run["mode"] == "DRY_RUN"
    assert dry_run["execution_status"] == "SUCCEEDED"
    assert dry_run["candidate_count"] == 1
    assert dry_run["selected_count"] == 1
    assert set(dry_run["deleted_counts"].values()) == {0}
    assert dry_run["idempotency_key"] == "retention-dry-run-001"
    assert blocked["mode"] == "EXECUTE"
    assert blocked["execution_status"] == "BLOCKED"
    assert blocked["blocked_reason"] == "delete_not_enabled"
    assert blocked["selected_count"] == 0
    assert store.get(old_deleted["artifact_id"]) is not None
    assert "storage_ref" not in json.dumps(dry_run, sort_keys=True)


def test_artifact_record_store_executes_guarded_retention_purge() -> None:
    store = ArtifactRecordStore()
    old_deleted = save_rendered_retention_artifact(
        store,
        artifact_request_id="retention-execute-old-001",
        updated_at="2026-07-31T00:00:00Z",
        target_formats=["MD", "HTML_PREVIEW", "DOCX"],
    )
    later_deleted = save_rendered_retention_artifact(
        store,
        artifact_request_id="retention-execute-old-002",
        updated_at="2026-07-31T01:00:00Z",
    )

    execution = store.purge_retention_candidates(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        retention_days=30,
        as_of="2026-09-01T00:00:00Z",
        checked_at="2026-09-01T02:10:00Z",
        dry_run=False,
        max_delete_count="1",
        delete_enabled=True,
        storage_mutation_enabled=True,
        database_row_delete_enabled=True,
    )

    assert execution["mode"] == "EXECUTE"
    assert execution["execution_status"] == "SUCCEEDED"
    assert execution["candidate_count"] == 2
    assert execution["selected_count"] == 1
    assert execution["deleted_counts"] == {
        "artifacts": 1,
        "source_refs": 1,
        "versions": 1,
        "render_jobs": 1,
        "files": 3,
        "links": 6,
        "storage_files": 3,
    }
    assert store.get(old_deleted["artifact_id"]) is None
    assert store.get(later_deleted["artifact_id"]) is not None
    assert set(store.rendered_markdown) == {later_deleted["current_version_id"]}
    assert set(store.artifact_files) == {
        artifact_file["artifact_file_id"] for artifact_file in later_deleted["files"]
    }
    assert "storage_ref" not in json.dumps(execution, sort_keys=True)


def test_artifact_record_store_retention_purge_respects_scan_limit() -> None:
    store = ArtifactRecordStore()
    first = save_rendered_retention_artifact(
        store,
        artifact_request_id="retention-scan-limit-001",
        updated_at="2026-07-31T00:00:00Z",
    )
    second = save_rendered_retention_artifact(
        store,
        artifact_request_id="retention-scan-limit-002",
        updated_at="2026-07-31T01:00:00Z",
    )

    execution = store.purge_retention_candidates(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        retention_days=30,
        as_of="2026-09-01T00:00:00Z",
        scan_limit=1,
        max_delete_count=10,
    )

    assert execution["candidate_count"] == 1
    assert execution["selected_count"] == 1
    assert store.get(first["artifact_id"]) is not None
    assert store.get(second["artifact_id"]) is not None


def test_sqlalchemy_artifact_record_store_executes_guarded_retention_purge_with_sqlite() -> None:
    session_factory = sqlite_artifact_session_factory()
    storage = InMemoryRenderedArtifactStorage()
    store = SqlAlchemyArtifactRecordStore(
        session_factory,
        rendered_storage=storage,
    )
    first = save_rendered_retention_artifact(
        store,
        artifact_request_id="sql-retention-purge-old-001",
        updated_at="2026-07-31T00:00:00Z",
        target_formats=["MD", "HTML_PREVIEW"],
    )
    second = save_rendered_retention_artifact(
        store,
        artifact_request_id="sql-retention-purge-old-002",
        updated_at="2026-07-31T01:00:00Z",
        target_formats=["MD"],
    )

    blocked = store.purge_retention_candidates(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        retention_days=30,
        as_of="2026-09-01T00:00:00Z",
        dry_run=False,
        max_delete_count=1,
    )
    execution = store.purge_retention_candidates(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        retention_days=30,
        as_of="2026-09-01T00:00:00Z",
        checked_at="2026-09-01T02:20:00Z",
        dry_run=False,
        max_delete_count=1,
        delete_enabled=True,
        storage_mutation_enabled=True,
        database_row_delete_enabled=True,
    )

    assert blocked["execution_status"] == "BLOCKED"
    assert blocked["candidate_count"] == 2
    assert execution["execution_status"] == "SUCCEEDED"
    assert execution["candidate_count"] == 2
    assert execution["selected_count"] == 1
    assert execution["deleted_counts"] == {
        "artifacts": 1,
        "source_refs": 1,
        "versions": 1,
        "render_jobs": 1,
        "files": 2,
        "links": 4,
        "storage_files": 2,
    }
    assert store.get(first["artifact_id"]) is None
    assert store.get(second["artifact_id"]) is not None
    assert len(storage.rendered_artifact_files) == 1
    assert "storage_ref" not in json.dumps(execution, sort_keys=True)


def test_artifact_retention_candidate_route_returns_metadata_only_candidates() -> None:
    client, _, artifact_store, _ = build_client_with_artifact_store()
    old_deleted = sample_collection_artifact_record(
        artifact_request_id="route-retention-old-deleted-001",
        artifact_status="DELETED",
        display_title="Route old deleted report",
        updated_at="2026-07-31T00:00:00Z",
    )
    recent_deleted = sample_collection_artifact_record(
        artifact_request_id="route-retention-recent-deleted-001",
        artifact_status="DELETED",
        display_title="Route recent deleted report",
        updated_at="2026-08-30T00:00:00Z",
    )
    artifact_store.save(old_deleted)
    artifact_store.save(recent_deleted)
    headers = auth_headers()

    response = client.get(
        "/api/v1/artifact-retention/candidates",
        params={
            "tenant_id": "tenant-001",
            "workspace_id": "workspace-001",
            "owner_user_id": "user-001",
            "retention_days": "30",
            "as_of": "2026-09-01T00:00:00Z",
            "limit": "10",
        },
        headers=headers,
    )
    unauthorized = client.get("/api/v1/artifact-retention/candidates")
    missing_scope = client.get(
        "/api/v1/artifact-retention/candidates",
        headers=headers,
    )
    invalid_retention_days = client.get(
        "/api/v1/artifact-retention/candidates",
        params={
            "tenant_id": "tenant-001",
            "workspace_id": "workspace-001",
            "owner_user_id": "user-001",
            "retention_days": "many",
        },
        headers=headers,
    )
    invalid_as_of = client.get(
        "/api/v1/artifact-retention/candidates",
        params={
            "tenant_id": "tenant-001",
            "workspace_id": "workspace-001",
            "owner_user_id": "user-001",
            "as_of": "not-a-date",
        },
        headers=headers,
    )
    payload = response.json()
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    assert response.status_code == 200
    assert payload["count"] == 1
    assert payload["items"][0]["artifact_id"] == old_deleted["artifact_id"]
    assert payload["items"][0]["display_title"] == "Route old deleted report"
    assert payload["metadata"] == {
        "dry_run": True,
        "physical_delete_executed": False,
        "storage_mutation_executed": False,
        "database_row_delete_executed": False,
    }
    assert payload["policy"]["physical_purge"]["database_row_delete_enabled"] is False
    assert "storage_ref" not in serialized
    assert "content_base64" not in serialized
    assert unauthorized.status_code == 401
    assert missing_scope.status_code == 422
    assert missing_scope.json()["error_code"] == "ae.artifact_collection_scope_required"
    assert invalid_retention_days.status_code == 422
    assert invalid_retention_days.json()["error_code"] == (
        "ae.artifact_retention_days_invalid"
    )
    assert invalid_as_of.status_code == 422
    assert invalid_as_of.json()["error_code"] == (
        "ae.artifact_retention_timestamp_invalid"
    )


def test_artifact_retention_batch_plan_route_returns_metadata_only_plan() -> None:
    client, _, artifact_store, _ = build_client_with_artifact_store()
    first = save_rendered_retention_artifact(
        artifact_store,
        artifact_request_id="route-retention-plan-old-001",
        updated_at="2026-07-31T00:00:00Z",
    )
    save_rendered_retention_artifact(
        artifact_store,
        artifact_request_id="route-retention-plan-old-002",
        updated_at="2026-07-31T01:00:00Z",
    )
    save_rendered_retention_artifact(
        artifact_store,
        artifact_request_id="route-retention-plan-recent-001",
        updated_at="2026-08-31T00:00:00Z",
    )
    headers = {**auth_headers(), "Idempotency-Key": "route-retention-plan-001"}

    response = client.get(
        "/api/v1/artifact-retention/batch-plan",
        params={
            "tenant_id": "tenant-001",
            "workspace_id": "workspace-001",
            "owner_user_id": "user-001",
            "retention_days": "30",
            "as_of": "2026-09-01T00:00:00Z",
            "checked_at": "2026-09-01T02:30:00Z",
            "scan_limit": "10",
            "max_delete_count": "1",
        },
        headers=headers,
    )
    unauthorized = client.get("/api/v1/artifact-retention/batch-plan")
    missing_scope = client.get(
        "/api/v1/artifact-retention/batch-plan",
        headers=headers,
    )
    invalid_delete_count = client.get(
        "/api/v1/artifact-retention/batch-plan",
        params={
            "tenant_id": "tenant-001",
            "workspace_id": "workspace-001",
            "owner_user_id": "user-001",
            "max_delete_count": "many",
        },
        headers=headers,
    )
    noop = client.get(
        "/api/v1/artifact-retention/batch-plan",
        params={
            "tenant_id": "tenant-001",
            "workspace_id": "workspace-001",
            "owner_user_id": "user-001",
            "retention_days": "30",
            "as_of": "2026-08-01T00:00:00Z",
            "checked_at": "2026-09-01T02:31:00Z",
        },
        headers=headers,
    )
    payload = response.json()
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    assert response.status_code == 200
    assert payload["artifact_retention_batch_plan_schema_version"] == (
        AE_ARTIFACT_RETENTION_BATCH_PLAN_SCHEMA_VERSION
    )
    assert payload["plan_status"] == "READY"
    assert payload["scheduler_status"] == "DISABLED"
    assert payload["candidate_count"] == 2
    assert payload["selected_count"] == 1
    assert payload["selected_candidates"][0]["artifact_id"] == first["artifact_id"]
    assert payload["requested_by"] == {
        "actor_type": "service",
        "actor_id": "nex-ag",
        "service_id": "nex-ae-api",
    }
    assert payload["idempotency_key"] == "route-retention-plan-001"
    assert payload["metadata"]["metadata_only"] is True
    assert payload["metadata"]["physical_delete_executed"] is False
    assert artifact_store.get(first["artifact_id"]) is not None
    assert "storage_ref" not in serialized
    assert "content_base64" not in serialized
    assert unauthorized.status_code == 401
    assert missing_scope.status_code == 422
    assert missing_scope.json()["error_code"] == "ae.artifact_collection_scope_required"
    assert invalid_delete_count.status_code == 422
    assert invalid_delete_count.json()["error_code"] == (
        "ae.artifact_retention_delete_limit_invalid"
    )
    assert noop.status_code == 200
    assert noop.json()["plan_status"] == "NOOP"
    assert noop.json()["execution_advice"] == "no_retention_candidates"


def test_artifact_retention_scheduler_config_route_returns_runtime_surface() -> None:
    queue = InMemoryJobQueue()
    client, _, _, _ = build_client_with_artifact_store(job_queue=queue)

    response = client.get(
        "/api/v1/artifact-retention/scheduler-config",
        headers=auth_headers(),
    )
    unauthorized = client.get("/api/v1/artifact-retention/scheduler-config")
    payload = response.json()
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    assert response.status_code == 200
    assert payload["artifact_retention_scheduler_config_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_CONFIG_SCHEMA_VERSION
    )
    assert payload["runtime"]["job_queue_available"] is True
    assert payload["runtime"]["scheduler_daemon_enabled"] is False
    assert payload["runtime"]["automation_profile"] == "disabled-dry-run-local-v1"
    assert payload["runtime"]["scheduler_tick_interval_seconds"] == 900
    assert payload["runtime"]["scheduler_tick_batch_window_enforced"] is True
    assert payload["api_routes"]["scheduled_jobs"] == (
        "/api/v1/artifact-retention/scheduled-jobs"
    )
    assert payload["api_routes"]["scheduled_job_admission"] == (
        "/api/v1/artifact-retention/scheduled-jobs/admission"
    )
    assert payload["guardrails"]["queue_admission_requires_ae_api"] is True
    assert unauthorized.status_code == 401
    assert "postgresql://" not in serialized
    assert "storage_ref" not in serialized


def test_artifact_retention_scheduled_job_routes_enqueue_and_list() -> None:
    queue = InMemoryJobQueue()
    client, _, artifact_store, _ = build_client_with_artifact_store(job_queue=queue)
    save_rendered_retention_artifact(
        artifact_store,
        artifact_request_id="route-scheduled-job-old-001",
        updated_at="2026-07-31T00:00:00Z",
    )
    headers = auth_headers()
    plan_response = client.get(
        "/api/v1/artifact-retention/batch-plan",
        params={
            "tenant_id": "tenant-001",
            "workspace_id": "workspace-001",
            "owner_user_id": "user-001",
            "retention_days": "30",
            "as_of": "2026-09-01T00:00:00Z",
            "checked_at": "2026-09-01T02:30:00Z",
            "scan_limit": "10",
            "max_delete_count": "1",
        },
        headers={**headers, "Idempotency-Key": "route-scheduled-job-plan-001"},
    )
    admission_body = {
        "batch_plan": plan_response.json(),
        "trigger_type": "operator_dispatch",
        "requested_at": "2026-09-01T02:31:00Z",
        "idempotency_key": "route-scheduled-job-admission-001",
    }

    admission = client.post(
        "/api/v1/artifact-retention/scheduled-jobs/admission",
        json=admission_body,
        headers={
            **headers,
            "Idempotency-Key": "route-scheduled-job-admission-001",
        },
    )
    duplicate = client.post(
        "/api/v1/artifact-retention/scheduled-jobs/admission",
        json=admission_body,
        headers={
            **headers,
            "Idempotency-Key": "route-scheduled-job-admission-001",
        },
    )
    listed = client.get(
        "/api/v1/artifact-retention/scheduled-jobs",
        params={
            "tenant_id": "tenant-001",
            "workspace_id": "workspace-001",
            "owner_user_id": "user-001",
            "status": "queued",
            "limit": "10",
        },
        headers=headers,
    )
    unauthorized_list = client.get("/api/v1/artifact-retention/scheduled-jobs")
    missing_scope = client.get(
        "/api/v1/artifact-retention/scheduled-jobs",
        headers=headers,
    )
    invalid_status = client.get(
        "/api/v1/artifact-retention/scheduled-jobs",
        params={
            "tenant_id": "tenant-001",
            "workspace_id": "workspace-001",
            "owner_user_id": "user-001",
            "status": "waiting",
        },
        headers=headers,
    )
    unauthorized_admission = client.post(
        "/api/v1/artifact-retention/scheduled-jobs/admission",
        json=admission_body,
    )
    payload = admission.json()
    collection = listed.json()
    serialized_collection = json.dumps(
        collection,
        ensure_ascii=False,
        sort_keys=True,
    )

    assert plan_response.status_code == 200
    assert admission.status_code == 200
    assert payload["artifact_retention_scheduled_job_enqueue_result_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULED_JOB_ENQUEUE_RESULT_SCHEMA_VERSION
    )
    assert payload["enqueue_status"] == "ENQUEUED"
    assert payload["job_enqueued"] is True
    assert payload["enqueued_job"]["status"] == "QUEUED"
    assert payload["trigger_type"] == "operator_dispatch"
    assert queue.get_job(payload["job_id"]) is not None
    assert duplicate.status_code == 200
    assert duplicate.json()["job_id"] == payload["job_id"]
    assert listed.status_code == 200
    assert collection["artifact_retention_scheduled_job_collection_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULED_JOB_COLLECTION_SCHEMA_VERSION
    )
    assert collection["count"] == 1
    assert collection["items"][0]["job_id"] == payload["job_id"]
    assert collection["summary"]["status_counts"]["QUEUED"] == 1
    assert "storage_ref" not in serialized_collection
    assert unauthorized_list.status_code == 401
    assert missing_scope.status_code == 422
    assert missing_scope.json()["error_code"] == "ae.artifact_collection_scope_required"
    assert invalid_status.status_code == 422
    assert invalid_status.json()["error_code"] == (
        "ae.artifact_retention_scheduled_job_status_invalid"
    )
    assert unauthorized_admission.status_code == 401


def test_artifact_retention_scheduled_job_admission_route_skips_noop() -> None:
    queue = InMemoryJobQueue()
    client, _, artifact_store, _ = build_client_with_artifact_store(job_queue=queue)
    save_rendered_retention_artifact(
        artifact_store,
        artifact_request_id="route-scheduled-job-noop-recent-001",
        updated_at="2026-08-31T00:00:00Z",
    )
    headers = auth_headers()
    plan_response = client.get(
        "/api/v1/artifact-retention/batch-plan",
        params={
            "tenant_id": "tenant-001",
            "workspace_id": "workspace-001",
            "owner_user_id": "user-001",
            "retention_days": "30",
            "as_of": "2026-09-01T00:00:00Z",
            "checked_at": "2026-09-01T02:32:00Z",
        },
        headers={**headers, "Idempotency-Key": "route-scheduled-job-noop-plan"},
    )
    admission = client.post(
        "/api/v1/artifact-retention/scheduled-jobs/admission",
        json={
            "batch_plan": plan_response.json(),
            "requested_at": "2026-09-01T02:33:00Z",
        },
        headers={**headers, "Idempotency-Key": "route-scheduled-job-noop"},
    )

    assert plan_response.status_code == 200
    assert plan_response.json()["plan_status"] == "NOOP"
    assert admission.status_code == 200
    assert admission.json()["enqueue_status"] == "SKIPPED"
    assert admission.json()["job_enqueued"] is False
    assert queue.list_jobs(job_type=AE_ARTIFACT_RETENTION_SCHEDULED_JOB_TYPE) == []


def test_artifact_retention_scheduled_job_list_route_reports_queue_failure() -> None:
    class FailingListQueue:
        def enqueue(self, job: dict[str, Any]) -> dict[str, Any]:
            raise AssertionError("not used")

        def list_jobs(
            self,
            *,
            job_type: str | None = None,
            status: str | None = None,
        ) -> list[dict[str, Any]]:
            raise JobQueueError(
                error_code="job.store_unavailable",
                detail="queue unavailable",
                status_code=503,
            )

    client, _, _, _ = build_client_with_artifact_store(job_queue=FailingListQueue())

    response = client.get(
        "/api/v1/artifact-retention/scheduled-jobs",
        params={
            "tenant_id": "tenant-001",
            "workspace_id": "workspace-001",
            "owner_user_id": "user-001",
        },
        headers=auth_headers(),
    )

    assert response.status_code == 503
    assert response.json()["error_code"] == (
        "ae.artifact_retention_scheduled_job_queue_unavailable"
    )
    assert response.json()["retryable"] is True


def test_artifact_retention_purge_route_requires_guarded_control_flags() -> None:
    client, _, artifact_store, _ = build_client_with_artifact_store()
    old_deleted = save_rendered_retention_artifact(
        artifact_store,
        artifact_request_id="route-retention-purge-old-001",
        updated_at="2026-07-31T00:00:00Z",
    )
    recent_deleted = save_rendered_retention_artifact(
        artifact_store,
        artifact_request_id="route-retention-purge-recent-001",
        updated_at="2026-08-31T00:00:00Z",
    )
    base_payload = {
        "tenant_id": "tenant-001",
        "workspace_id": "workspace-001",
        "owner_user_id": "user-001",
        "retention_days": "30",
        "as_of": "2026-09-01T00:00:00Z",
        "checked_at": "2026-09-01T02:30:00Z",
        "scan_limit": "10",
        "max_delete_count": "1",
        "requested_by": {"actor_type": "service", "actor_id": "nex-ag"},
    }

    dry_run = client.post(
        "/api/v1/artifact-retention/purge",
        json=base_payload,
        headers={**auth_headers(), "Idempotency-Key": "route-retention-dry-run-001"},
    )
    blocked = client.post(
        "/api/v1/artifact-retention/purge",
        json={**base_payload, "dry_run": False},
        headers={**auth_headers(), "Idempotency-Key": "route-retention-blocked-001"},
    )
    invalid_bool = client.post(
        "/api/v1/artifact-retention/purge",
        json={**base_payload, "dry_run": "false"},
        headers={**auth_headers(), "Idempotency-Key": "route-retention-invalid-001"},
    )
    unsafe_dry_run = client.post(
        "/api/v1/artifact-retention/purge",
        json={**base_payload, "delete_enabled": True},
        headers={**auth_headers(), "Idempotency-Key": "route-retention-unsafe-001"},
    )
    missing_scope = client.post(
        "/api/v1/artifact-retention/purge",
        json={},
        headers={**auth_headers(), "Idempotency-Key": "route-retention-missing-001"},
    )
    unauthorized = client.post(
        "/api/v1/artifact-retention/purge",
        json=base_payload,
    )
    execute = client.post(
        "/api/v1/artifact-retention/purge",
        json={
            **base_payload,
            "dry_run": False,
            "delete_enabled": True,
            "storage_mutation_enabled": True,
            "database_row_delete_enabled": True,
        },
        headers={**auth_headers(), "Idempotency-Key": "route-retention-execute-001"},
    )
    payload = execute.json()
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    assert dry_run.status_code == 200
    assert dry_run.json()["artifact_retention_execution_schema_version"] == (
        AE_ARTIFACT_RETENTION_EXECUTION_SCHEMA_VERSION
    )
    assert dry_run.json()["mode"] == "DRY_RUN"
    assert dry_run.json()["candidate_count"] == 1
    assert dry_run.json()["selected_count"] == 1
    assert dry_run.json()["idempotency_key"] == "route-retention-dry-run-001"
    assert dry_run.json()["requested_by"] == {
        "actor_type": "service",
        "actor_id": "nex-ag",
        "service_id": "nex-ae-api",
    }
    assert blocked.status_code == 200
    assert blocked.json()["execution_status"] == "BLOCKED"
    assert blocked.json()["blocked_reason"] == "delete_not_enabled"
    assert invalid_bool.status_code == 422
    assert invalid_bool.json()["error_code"] == (
        "ae.artifact_retention_dry_run_invalid"
    )
    assert unsafe_dry_run.status_code == 422
    assert unsafe_dry_run.json()["error_code"] == (
        "ae.artifact_retention_dry_run_delete_enabled_invalid"
    )
    assert missing_scope.status_code == 422
    assert missing_scope.json()["error_code"] == "ae.artifact_collection_scope_required"
    assert unauthorized.status_code == 401
    assert execute.status_code == 200
    assert payload["mode"] == "EXECUTE"
    assert payload["execution_status"] == "SUCCEEDED"
    assert payload["deleted_counts"]["artifacts"] == 1
    assert payload["deleted_counts"]["files"] == 2
    assert payload["deleted_counts"]["links"] == 4
    assert payload["deleted_counts"]["storage_files"] == 2
    assert artifact_store.get(old_deleted["artifact_id"]) is None
    assert artifact_store.get(recent_deleted["artifact_id"]) is not None
    assert "storage_ref" not in serialized


def test_artifact_retention_purge_route_persists_history_and_reuses_idempotency() -> None:
    history_store = ArtifactRetentionExecutionHistoryStore()
    client, _, artifact_store, _ = build_client_with_artifact_store(
        retention_history_store=history_store
    )
    old_deleted = save_rendered_retention_artifact(
        artifact_store,
        artifact_request_id="route-retention-history-old-001",
        updated_at="2026-07-31T00:00:00Z",
    )
    base_payload = {
        "tenant_id": "tenant-001",
        "workspace_id": "workspace-001",
        "owner_user_id": "user-001",
        "retention_days": "30",
        "as_of": "2026-09-01T00:00:00Z",
        "checked_at": "2026-09-01T02:40:00Z",
        "scan_limit": "10",
        "max_delete_count": "1",
        "requested_by": {"actor_type": "service", "actor_id": "nex-ag"},
    }

    first = client.post(
        "/api/v1/artifact-retention/purge",
        json=base_payload,
        headers={**auth_headers(), "Idempotency-Key": "route-history-dry-001"},
    )
    duplicate = client.post(
        "/api/v1/artifact-retention/purge",
        json={**base_payload, "checked_at": "2026-09-01T02:41:00Z"},
        headers={**auth_headers(), "Idempotency-Key": "route-history-dry-001"},
    )
    execute = client.post(
        "/api/v1/artifact-retention/purge",
        json={
            **base_payload,
            "checked_at": "2026-09-01T02:45:00Z",
            "dry_run": False,
            "delete_enabled": True,
            "storage_mutation_enabled": True,
            "database_row_delete_enabled": True,
        },
        headers={**auth_headers(), "Idempotency-Key": "route-history-execute-001"},
    )
    first_payload = first.json()
    duplicate_payload = duplicate.json()
    execute_payload = execute.json()
    histories = history_store.list_executions(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
    )

    assert first.status_code == 200
    assert duplicate.status_code == 200
    assert execute.status_code == 200
    assert duplicate_payload["execution_id"] == first_payload["execution_id"]
    assert duplicate_payload["checked_at"] == first_payload["checked_at"]
    assert execute_payload["mode"] == "EXECUTE"
    assert execute_payload["execution_status"] == "SUCCEEDED"
    assert execute_payload["deleted_counts"]["artifacts"] == 1
    assert artifact_store.get(old_deleted["artifact_id"]) is None
    assert len(histories) == 2
    assert {
        item["execution"]["execution_id"] for item in histories
    } == {first_payload["execution_id"], execute_payload["execution_id"]}
    assert history_store.get_by_idempotency_key(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        idempotency_key="route-history-execute-001",
    )["execution"]["deleted_counts"]["artifacts"] == 1


def test_artifact_retention_execution_history_route_lists_metadata_only() -> None:
    history_store = ArtifactRetentionExecutionHistoryStore()
    client, _, _, _ = build_client_with_artifact_store(
        retention_history_store=history_store
    )
    succeeded = history_store.save(
        sample_retention_execution(
            mode="EXECUTE",
            execution_status="SUCCEEDED",
            checked_at="2026-09-01T02:45:00Z",
            delete_enabled=True,
            storage_mutation_enabled=True,
            database_row_delete_enabled=True,
            deleted_counts={
                "artifacts": 1,
                "source_refs": 1,
                "versions": 1,
                "render_jobs": 1,
                "files": 2,
                "links": 4,
                "storage_files": 2,
            },
            idempotency_key="route-history-query-execute-001",
        )
    )
    blocked = history_store.save(
        sample_retention_execution(
            mode="EXECUTE",
            execution_status="BLOCKED",
            checked_at="2026-09-01T02:40:00Z",
            selected_count=0,
            blocked_reason="delete_not_enabled",
            idempotency_key="route-history-query-blocked-001",
        )
    )
    history_store.save(
        sample_retention_execution(
            owner_user_id="user-002",
            execution_status="SUCCEEDED",
            checked_at="2026-09-01T02:50:00Z",
            idempotency_key="route-history-query-other-owner-001",
        )
    )

    response = client.get(
        "/api/v1/artifact-retention/executions",
        params={
            "tenant_id": "tenant-001",
            "workspace_id": "workspace-001",
            "owner_user_id": "user-001",
            "mode": "execute",
            "limit": "10",
        },
        headers=auth_headers(),
    )
    blocked_response = client.get(
        "/api/v1/artifact-retention/executions",
        params={
            "tenant_id": "tenant-001",
            "workspace_id": "workspace-001",
            "owner_user_id": "user-001",
            "execution_status": "blocked",
            "limit": "1",
        },
        headers=auth_headers(),
    )
    missing_scope = client.get(
        "/api/v1/artifact-retention/executions",
        params={
            "tenant_id": "tenant-001",
            "workspace_id": "workspace-001",
        },
        headers=auth_headers(),
    )
    invalid_mode = client.get(
        "/api/v1/artifact-retention/executions",
        params={
            "tenant_id": "tenant-001",
            "workspace_id": "workspace-001",
            "owner_user_id": "user-001",
            "mode": "preview",
        },
        headers=auth_headers(),
    )
    unauthorized = client.get(
        "/api/v1/artifact-retention/executions",
        params={
            "tenant_id": "tenant-001",
            "workspace_id": "workspace-001",
            "owner_user_id": "user-001",
        },
    )
    payload = response.json()
    blocked_payload = blocked_response.json()
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    assert response.status_code == 200
    assert payload[
        "artifact_retention_execution_history_collection_schema_version"
    ] == AE_ARTIFACT_RETENTION_EXECUTION_HISTORY_COLLECTION_SCHEMA_VERSION
    assert payload["count"] == 2
    assert payload["filter"]["mode"] == "EXECUTE"
    assert payload["summary"]["execute_count"] == 2
    assert payload["summary"]["blocked_count"] == 1
    assert [item["retention_execution_id"] for item in payload["items"]] == [
        succeeded["retention_execution_id"],
        blocked["retention_execution_id"],
    ]
    assert payload["items"][0]["execution_payload_hash"] == (
        succeeded["execution_payload_hash"]
    )
    assert '"execution":' not in serialized
    assert "storage_ref" not in serialized
    assert blocked_response.status_code == 200
    assert blocked_payload["count"] == 1
    assert blocked_payload["items"][0]["retention_execution_id"] == (
        blocked["retention_execution_id"]
    )
    assert missing_scope.status_code == 422
    assert missing_scope.json()["error_code"] == "ae.artifact_collection_scope_required"
    assert invalid_mode.status_code == 422
    assert invalid_mode.json()["error_code"] == (
        "ae.artifact_retention_execution_mode_invalid"
    )
    assert unauthorized.status_code == 401


def test_artifact_retention_purge_route_checks_history_store_before_execute() -> None:
    class FailingHistoryStore(ArtifactRetentionExecutionHistoryStore):
        def ensure_available(self) -> None:
            raise ArtifactHandoffError(
                status_code=503,
                error_code="ae.artifact_retention_history_store_unavailable",
                detail="history unavailable",
                retryable=True,
            )

    history_store = FailingHistoryStore()
    client, _, artifact_store, _ = build_client_with_artifact_store(
        retention_history_store=history_store
    )
    old_deleted = save_rendered_retention_artifact(
        artifact_store,
        artifact_request_id="route-retention-history-unavailable-001",
        updated_at="2026-07-31T00:00:00Z",
    )

    response = client.post(
        "/api/v1/artifact-retention/purge",
        json={
            "tenant_id": "tenant-001",
            "workspace_id": "workspace-001",
            "owner_user_id": "user-001",
            "retention_days": "30",
            "as_of": "2026-09-01T00:00:00Z",
            "dry_run": False,
            "delete_enabled": True,
            "storage_mutation_enabled": True,
            "database_row_delete_enabled": True,
        },
        headers={**auth_headers(), "Idempotency-Key": "route-history-fail-001"},
    )

    assert response.status_code == 503
    assert response.json()["error_code"] == (
        "ae.artifact_retention_history_store_unavailable"
    )
    assert artifact_store.get(old_deleted["artifact_id"]) is not None
    assert history_store.records == {}


def test_sqlalchemy_artifact_record_store_applies_lifecycle_with_sqlite() -> None:
    session_factory = sqlite_artifact_session_factory()
    store = SqlAlchemyArtifactRecordStore(session_factory)
    ready_record = sample_collection_artifact_record(
        artifact_request_id="sql-lifecycle-ready-001",
        artifact_status="READY",
    )
    handoff_store = SqlAlchemyArtifactHandoffStore(session_factory)
    handoff_store.save(
        {
            **sample_handoff_record(),
            "artifact_handoff_id": ready_record["handoff_ref"]["artifact_handoff_id"],
            "artifact_request_id": ready_record["handoff_ref"]["artifact_request_id"],
        }
    )
    store.save(ready_record)
    action_request = build_artifact_lifecycle_action_request(
        payload={"action": "MARK_DELETED"},
        artifact_record=ready_record,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    result = store.apply_lifecycle_action(ready_record["artifact_id"], action_request)

    assert result["artifact_status"] == "DELETED"
    assert store.get(ready_record["artifact_id"])["artifact_status"] == "DELETED"
    assert store.list_artifacts(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        status="DELETED",
    )["count"] == 1


def test_artifact_lifecycle_route_applies_and_reports_errors() -> None:
    client, _, artifact_store, _ = build_client_with_artifact_store()
    ready_record = sample_collection_artifact_record(
        artifact_request_id="route-lifecycle-ready-001",
        artifact_status="READY",
    )
    artifact_store.save(ready_record)
    headers = auth_headers()

    archive = client.post(
        f"/api/v1/artifacts/{ready_record['artifact_id']}/lifecycle-actions",
        json={"action": "ARCHIVE", "reason_code": "user_requested"},
        headers=headers,
    )
    missing = client.post(
        "/api/v1/artifacts/missing-artifact/lifecycle-actions",
        json={"action": "ARCHIVE"},
        headers=headers,
    )
    invalid = client.post(
        f"/api/v1/artifacts/{ready_record['artifact_id']}/lifecycle-actions",
        json={"action": "RESTORE", "restore_status": "ARCHIVED"},
        headers=headers,
    )
    unauthorized = client.post(
        f"/api/v1/artifacts/{ready_record['artifact_id']}/lifecycle-actions",
        json={"action": "ARCHIVE"},
    )

    assert archive.status_code == 200
    assert archive.json()["artifact_lifecycle_action_result_schema_version"] == (
        AE_ARTIFACT_LIFECYCLE_ACTION_RESULT_SCHEMA_VERSION
    )
    assert archive.json()["artifact_status"] == "ARCHIVED"
    assert archive.json()["lifecycle_action"]["idempotency_key"] == (
        "artifact-request-001"
    )
    assert artifact_store.get(ready_record["artifact_id"])["artifact_status"] == (
        "ARCHIVED"
    )
    assert missing.status_code == 404
    assert missing.json()["error_code"] == "ae.artifact_not_found"
    assert invalid.status_code == 422
    assert invalid.json()["error_code"] == (
        "ae.artifact_lifecycle_restore_status_invalid"
    )
    assert unauthorized.status_code == 401


def test_artifact_collection_read_model_guards_private_and_sparse_payloads() -> None:
    sparse_record = sample_collection_artifact_record(
        artifact_request_id="collection-sparse-001",
        display_title="Sparse report",
    )
    sparse_record["source_refs"] = "not-a-list"
    sparse_record["versions"] = "not-a-list"
    sparse_record["render_jobs"] = []
    sparse_record["files"] = []
    sparse_record["links"] = []

    item = build_artifact_collection_item(sparse_record)

    assert item["source_summary"]["evidence_ref_count"] == 0
    assert item["quality_summary"] == {}
    assert item["current_version_no"] is None
    assert item["latest_render_job"] is None
    assert item["available_formats"] == []

    nested_safe_value = ae_artifacts._collection_json_safe_value(
        [{"keep": object(), "drop": None}]
    )
    assert "object" in nested_safe_value[0]["keep"]
    assert "drop" not in nested_safe_value[0]

    with pytest.raises(ArtifactHandoffError) as unsafe_exc:
        ae_artifacts.assert_artifact_collection_payload_safe(
            {"storage_ref": "ae://artifacts/private"}
        )
    assert unsafe_exc.value.error_code == "ae.artifact_collection_payload_unsafe"


def test_in_memory_artifact_store_lists_owner_scoped_collection_items() -> None:
    store = ArtifactRecordStore()
    ready = sample_collection_artifact_record(
        artifact_request_id="collection-ready-001",
        artifact_status="READY",
        display_title="Ready report",
        updated_at="2026-08-30T09:00:00Z",
    )
    draft = sample_collection_artifact_record(
        artifact_request_id="collection-draft-001",
        artifact_status="DRAFT",
        display_title="Draft report",
        updated_at="2026-08-30T08:00:00Z",
    )
    other_owner = sample_collection_artifact_record(
        artifact_request_id="collection-other-001",
        owner_user_id="user-002",
        display_title="Other owner report",
        updated_at="2026-08-30T10:00:00Z",
    )
    for record in (draft, other_owner, ready):
        store.create(record)

    collection = store.list_artifacts(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        limit=10,
    )
    ready_only = store.list_artifacts(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        status="ready",
    )
    limited = store.list_artifacts(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        limit=1,
    )

    assert collection["artifact_collection_schema_version"] == (
        ARTIFACT_COLLECTION_SCHEMA_VERSION
    )
    assert collection["count"] == 2
    assert collection["next_cursor"] is None
    assert [item["display_title"] for item in collection["items"]] == [
        "Ready report",
        "Draft report",
    ]
    assert all(item["owner_user_id"] == "user-001" for item in collection["items"])
    assert ready_only["count"] == 1
    assert ready_only["items"][0]["artifact_status"] == "READY"
    assert limited["count"] == 1
    assert limited["items"][0]["display_title"] == "Ready report"


def test_resolve_rendered_artifact_file_payload_reports_missing_payload() -> None:
    store = ArtifactRecordStore()
    artifact_record = build_artifact_record_from_handoff(
        source_payload={"artifact_request_id": "artifact-create-001"},
        handoff_record=sample_handoff_record(),
        artifact_request_id=None,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    store.create(artifact_record)
    render_result = build_markdown_render_result(
        artifact_record=artifact_record,
        structured_draft=sample_structured_draft(),
        target_formats=["MD"],
        render_request_id="render-request-001",
        render_job_id=deterministic_render_job_id(
            artifact_record["artifact_id"],
            "render-request-001",
        ),
    )
    artifact_file = render_result["artifact_files"][0]
    store.artifact_files[artifact_file["artifact_file_id"]] = artifact_file
    store.artifact_links[render_result["artifact_links"][1]["artifact_link_id"]] = (
        render_result["artifact_links"][1]
    )

    with pytest.raises(ArtifactHandoffError) as exc_info:
        resolve_rendered_artifact_file_payload(
            store,
            artifact_file_id=artifact_file["artifact_file_id"],
            link_type="download",
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.error_code == "ae.artifact_file_not_ready"


def test_rendered_text_from_payload_rejects_binary_and_invalid_utf8() -> None:
    markdown_file = {
        "format": "MD",
        "mime_type": "text/markdown",
        "artifact_file_id": "file-md",
    }
    pdf_file = {
        "format": "PDF",
        "mime_type": "application/pdf",
        "artifact_file_id": "file-pdf",
    }

    assert rendered_text_from_payload(markdown_file, "# Safe\n".encode("utf-8")) == (
        "# Safe\n"
    )
    with pytest.raises(ArtifactHandoffError) as binary_exc:
        rendered_text_from_payload(pdf_file, b"%PDF-safe")
    assert binary_exc.value.error_code == "ae.artifact_file_preview_unavailable"

    with pytest.raises(ArtifactHandoffError) as utf8_exc:
        rendered_text_from_payload(markdown_file, b"\xff\xfe")
    assert utf8_exc.value.error_code == "ae.artifact_file_not_ready"


def test_rendered_download_fields_encode_binary_payloads() -> None:
    markdown_file = {
        "format": "MD",
        "mime_type": "text/markdown",
        "artifact_file_id": "file-md",
    }
    docx_file = {
        "format": "DOCX",
        "mime_type": (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        "artifact_file_id": "file-docx",
    }
    docx_payload = b"PK-docx-bytes"

    assert rendered_download_fields_from_payload(markdown_file, b"# Safe\n") == {
        "content": "# Safe\n"
    }
    encoded = rendered_download_fields_from_payload(docx_file, docx_payload)

    assert encoded["content_encoding"] == "base64"
    assert base64.b64decode(encoded["content_base64"]) == docx_payload
    assert "content" not in encoded


def test_markdown_render_guards_reject_invalid_sources_and_formats() -> None:
    artifact_record = build_artifact_record_from_handoff(
        source_payload={"artifact_request_id": "artifact-create-001"},
        handoff_record=sample_handoff_record(),
        artifact_request_id=None,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert markdown_target_formats_from_payload({}, artifact_record) == ["MD"]
    assert markdown_target_formats_from_payload(
        {"target_formats": ["MD", "MD"]},
        artifact_record,
    ) == ["MD"]

    with pytest.raises(ArtifactHandoffError) as formats_exc:
        markdown_target_formats_from_payload({"target_formats": []}, artifact_record)
    assert formats_exc.value.error_code == "ae.target_formats_invalid"

    with pytest.raises(ArtifactHandoffError) as format_exc:
        markdown_target_formats_from_payload(
            {"target_formats": ["HTML_PREVIEW"]},
            artifact_record,
        )
    assert format_exc.value.error_code == "ae.render_format_unsupported"

    no_markdown_record = {
        **artifact_record,
        "target_formats": ["HTML_PREVIEW"],
    }
    with pytest.raises(ArtifactHandoffError) as not_requested_exc:
        markdown_target_formats_from_payload({}, no_markdown_record)
    assert not_requested_exc.value.error_code == "ae.render_format_not_requested"

    with pytest.raises(ArtifactHandoffError) as status_exc:
        validate_structured_draft_for_markdown_render(
            artifact_record,
            sample_structured_draft(status="VALIDATION_FAILED"),
        )
    assert status_exc.value.error_code == "ae.citation_validation_required"

    with pytest.raises(ArtifactHandoffError) as citation_exc:
        validate_structured_draft_for_markdown_render(
            artifact_record,
            sample_structured_draft(citation_status="FAILED"),
        )
    assert citation_exc.value.error_code == "ae.citation_validation_required"

    with pytest.raises(ArtifactHandoffError) as draft_exc:
        validate_structured_draft_for_markdown_render(
            artifact_record,
            sample_structured_draft(structured_draft_id="draft-other"),
        )
    assert draft_exc.value.error_code == "ae.source_draft_hash_mismatch"

    with pytest.raises(ArtifactHandoffError) as hash_exc:
        validate_structured_draft_for_markdown_render(
            artifact_record,
            sample_structured_draft(content_hash="9" * 64),
        )
    assert hash_exc.value.error_code == "ae.source_draft_hash_mismatch"

    archived_record = {**artifact_record, "artifact_status": "ARCHIVED"}
    with pytest.raises(ArtifactHandoffError) as archived_exc:
        validate_structured_draft_for_markdown_render(
            archived_record,
            sample_structured_draft(),
        )
    assert archived_exc.value.error_code == "ae.artifact_not_renderable"


def test_artifact_handoff_route_fetches_cx_records_and_allows_readback() -> None:
    client, store, cx_client = build_client()

    response = client.post(
        "/api/v1/artifact-handoffs",
        json=artifact_payload(),
        headers=auth_headers(),
    )
    payload = response.json()
    readback = client.get(
        f"/api/v1/artifact-handoffs/{payload['artifact_handoff_id']}",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert cx_client.calls == [
        ("generation", "cx-gen-001"),
        ("draft", "cx-gen-001"),
    ]
    assert payload["artifact_request_id"] == "artifact-request-001"
    assert store.get(payload["artifact_handoff_id"]) == payload
    assert readback.status_code == 200
    assert readback.json() == payload


def test_artifact_route_creates_record_from_handoff_and_allows_readback() -> None:
    client, store, _ = build_client()
    handoff = store.save(sample_handoff_record())

    response = client.post(
        "/api/v1/artifacts",
        json={
            "artifact_handoff_id": handoff["artifact_handoff_id"],
            "artifact_type": "generated_document",
        },
        headers={**auth_headers(), "Idempotency-Key": "artifact-create-001"},
    )
    payload = response.json()
    repeat = client.post(
        "/api/v1/artifacts",
        json={"artifact_handoff_id": handoff["artifact_handoff_id"]},
        headers={**auth_headers(), "Idempotency-Key": "artifact-create-001"},
    )
    readback = client.get(
        f"/api/v1/artifacts/{payload['artifact_id']}",
        headers=auth_headers(),
    )
    collection = client.get(
        "/api/v1/artifacts",
        params={
            "tenant_id": "tenant-001",
            "workspace_id": "workspace-001",
            "owner_user_id": "user-001",
        },
        headers=auth_headers(),
    )
    versions = client.get(
        f"/api/v1/artifacts/{payload['artifact_id']}/versions",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert repeat.json() == payload
    assert readback.status_code == 200
    assert readback.json() == payload
    assert collection.status_code == 200
    assert collection.json()["artifact_collection_schema_version"] == (
        ARTIFACT_COLLECTION_SCHEMA_VERSION
    )
    assert collection.json()["count"] == 1
    assert collection.json()["items"][0]["artifact_id"] == payload["artifact_id"]
    assert versions.status_code == 200
    assert versions.json() == {
        "artifact_id": payload["artifact_id"],
        "current_version_id": None,
        "versions": [],
    }
    assert payload["handoff_ref"]["artifact_handoff_id"] == handoff[
        "artifact_handoff_id"
    ]
    assert payload["source_refs"][0]["structured_draft_content_hash"] == "c" * 64
    assert "Safe summary." not in str(payload)
    assert "/data/nex-platform" not in str(payload)


def test_artifact_collection_route_filters_owner_scope_status_and_limit() -> None:
    client, _, artifact_store, _ = build_client_with_artifact_store()
    ready = sample_collection_artifact_record(
        artifact_request_id="route-ready-001",
        artifact_status="READY",
        display_title="Route ready report",
        updated_at="2026-08-30T09:00:00Z",
    )
    draft = sample_collection_artifact_record(
        artifact_request_id="route-draft-001",
        artifact_status="DRAFT",
        display_title="Route draft report",
        updated_at="2026-08-30T08:00:00Z",
    )
    other = sample_collection_artifact_record(
        artifact_request_id="route-other-001",
        owner_user_id="user-002",
        display_title="Route other report",
        updated_at="2026-08-30T10:00:00Z",
    )
    for record in (draft, other, ready):
        artifact_store.create(record)

    response = client.get(
        "/api/v1/artifacts",
        params={
            "tenant_id": "tenant-001",
            "workspace_id": "workspace-001",
            "owner_user_id": "user-001",
            "limit": "10",
        },
        headers=auth_headers(),
    )
    ready_only = client.get(
        "/api/v1/artifacts",
        params={
            "tenant_id": "tenant-001",
            "workspace_id": "workspace-001",
            "owner_user_id": "user-001",
            "status": "ready",
            "limit": "1",
        },
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert [item["display_title"] for item in response.json()["items"]] == [
        "Route ready report",
        "Route draft report",
    ]
    assert "storage_ref" not in json.dumps(response.json(), ensure_ascii=False)
    assert ready_only.status_code == 200
    assert ready_only.json()["filter"]["status"] == "READY"
    assert ready_only.json()["count"] == 1
    assert ready_only.json()["items"][0]["display_title"] == "Route ready report"


def test_artifact_collection_route_reports_auth_scope_and_query_errors() -> None:
    client, _, _, _ = build_client_with_artifact_store()

    unauthorized = client.get("/api/v1/artifacts")
    missing_scope = client.get("/api/v1/artifacts", headers=auth_headers())
    invalid_status = client.get(
        "/api/v1/artifacts",
        params={
            "tenant_id": "tenant-001",
            "workspace_id": "workspace-001",
            "owner_user_id": "user-001",
            "status": "bad",
        },
        headers=auth_headers(),
    )
    invalid_limit = client.get(
        "/api/v1/artifacts",
        params={
            "tenant_id": "tenant-001",
            "workspace_id": "workspace-001",
            "owner_user_id": "user-001",
            "limit": "many",
        },
        headers=auth_headers(),
    )

    assert unauthorized.status_code == 401
    assert missing_scope.status_code == 422
    assert missing_scope.json()["error_code"] == "ae.artifact_collection_scope_required"
    assert invalid_status.status_code == 422
    assert invalid_status.json()["error_code"] == "ae.artifact_collection_status_invalid"
    assert invalid_limit.status_code == 422
    assert invalid_limit.json()["error_code"] == "ae.artifact_collection_limit_invalid"


def test_markdown_render_route_updates_artifact_and_preserves_private_content() -> None:
    client, handoff_store, artifact_store, _ = build_client_with_artifact_store()
    handoff = handoff_store.save(sample_handoff_record())
    created = client.post(
        "/api/v1/artifacts",
        json={"artifact_handoff_id": handoff["artifact_handoff_id"]},
        headers={**auth_headers(), "Idempotency-Key": "artifact-create-001"},
    )
    artifact_id = created.json()["artifact_id"]

    rendered = client.post(
        f"/api/v1/artifacts/{artifact_id}/render-jobs",
        json={},
        headers={**auth_headers(), "Idempotency-Key": "render-request-001"},
    )
    payload = rendered.json()
    render_job = payload["render_job"]
    artifact = payload["artifact"]
    artifact_file = artifact["files"][0]
    repeated = client.post(
        f"/api/v1/artifacts/{artifact_id}/render-jobs",
        json={},
        headers={**auth_headers(), "Idempotency-Key": "render-request-001"},
    )
    job_readback = client.get(
        f"/api/v1/artifact-render-jobs/{render_job['render_job_id']}",
        headers=auth_headers(),
    )
    file_readback = client.get(
        f"/api/v1/artifact-files/{artifact_file['artifact_file_id']}",
        headers=auth_headers(),
    )
    preview = client.get(
        f"/api/v1/artifact-files/{artifact_file['artifact_file_id']}/preview",
        headers=auth_headers(),
    )
    download = client.get(
        f"/api/v1/artifact-files/{artifact_file['artifact_file_id']}/download",
        headers=auth_headers(),
    )

    assert rendered.status_code == 200
    assert payload["render_result_schema_version"] == "ae_markdown_render_result.v1"
    assert artifact["artifact_status"] == "READY"
    assert artifact["current_version_id"] == artifact["versions"][0][
        "artifact_version_id"
    ]
    assert artifact["versions"][0]["rendered_formats"] == ["MD"]
    assert artifact["render_jobs"][0] == render_job
    assert artifact_file["storage_ref"].startswith("ae://artifacts/")
    assert {link["link_type"] for link in artifact["links"]} == {"preview", "download"}
    assert "Grounded answer [1]." not in str(payload)
    assert artifact_store.get_rendered_markdown(
        artifact["current_version_id"]
    ).startswith("# Grounded report")
    assert repeated.json() == payload
    assert job_readback.status_code == 200
    assert job_readback.json() == render_job
    assert file_readback.status_code == 200
    assert file_readback.json() == artifact_file
    assert preview.status_code == 200
    assert preview.json()["preview_schema_version"] == "ae_artifact_file_preview.v1"
    assert "Grounded answer [1]." in preview.json()["text_preview"]
    assert "/data/nex-platform" not in str(preview.json())
    assert download.status_code == 200
    assert download.json()["download_schema_version"] == "ae_artifact_file_download.v1"
    assert download.json()["download_file_name"] == artifact_file["file_name"]
    assert download.json()["content_hash"] == artifact_file["file_hash"]


def test_html_preview_render_route_updates_artifact_and_private_storage() -> None:
    client, handoff_store, artifact_store, _ = build_client_with_artifact_store()
    handoff = handoff_store.save(sample_handoff_record())
    created = client.post(
        "/api/v1/artifacts",
        json={"artifact_handoff_id": handoff["artifact_handoff_id"]},
        headers={**auth_headers(), "Idempotency-Key": "artifact-create-001"},
    )
    artifact_id = created.json()["artifact_id"]

    rendered = client.post(
        f"/api/v1/artifacts/{artifact_id}/render-jobs",
        json={"target_formats": ["MD", "HTML_PREVIEW"]},
        headers={**auth_headers(), "Idempotency-Key": "render-request-html-001"},
    )
    artifact = rendered.json()["artifact"]
    html_file = next(
        artifact_file
        for artifact_file in artifact["files"]
        if artifact_file["format"] == "HTML_PREVIEW"
    )
    preview = client.get(
        f"/api/v1/artifact-files/{html_file['artifact_file_id']}/preview",
        headers=auth_headers(),
    )
    download = client.get(
        f"/api/v1/artifact-files/{html_file['artifact_file_id']}/download",
        headers=auth_headers(),
    )

    assert rendered.status_code == 200
    assert artifact["versions"][0]["rendered_formats"] == ["MD", "HTML_PREVIEW"]
    assert [artifact_file["format"] for artifact_file in artifact["files"]] == [
        "MD",
        "HTML_PREVIEW",
    ]
    assert len(artifact["links"]) == 4
    assert html_file["mime_type"] == "text/html"
    assert html_file["file_name"].endswith(".html")
    assert artifact_store.get_rendered_artifact_file(html_file).startswith(
        b"<!doctype html>"
    )
    assert "<article" not in str(rendered.json())
    assert preview.status_code == 200
    assert preview.json()["content_type"] == "text/html"
    assert "<article class=\"ae-artifact-preview\">" in preview.json()["text_preview"]
    assert download.status_code == 200
    assert download.json()["content_type"] == "text/html"
    assert download.json()["download_file_name"] == html_file["file_name"]
    assert download.json()["content"].startswith("<!doctype html>")
    assert download.json()["content_hash"] == html_file["file_hash"]


def test_docx_render_route_stores_binary_and_downloads_base64() -> None:
    client, handoff_store, artifact_store, _ = build_client_with_artifact_store()
    handoff = handoff_store.save(sample_handoff_record())
    created = client.post(
        "/api/v1/artifacts",
        json={"artifact_handoff_id": handoff["artifact_handoff_id"]},
        headers={**auth_headers(), "Idempotency-Key": "artifact-create-001"},
    )
    artifact_id = created.json()["artifact_id"]

    rendered = client.post(
        f"/api/v1/artifacts/{artifact_id}/render-jobs",
        json={"target_formats": ["DOCX"]},
        headers={**auth_headers(), "Idempotency-Key": "render-request-docx-001"},
    )
    artifact = rendered.json()["artifact"]
    docx_file = artifact["files"][0]
    preview = client.get(
        f"/api/v1/artifact-files/{docx_file['artifact_file_id']}/preview",
        headers=auth_headers(),
    )
    download = client.get(
        f"/api/v1/artifact-files/{docx_file['artifact_file_id']}/download",
        headers=auth_headers(),
    )
    stored_payload = artifact_store.get_rendered_artifact_file(docx_file)

    assert rendered.status_code == 200
    assert artifact["versions"][0]["rendered_formats"] == ["DOCX"]
    assert docx_file["format"] == "DOCX"
    assert docx_file["file_name"].endswith(".docx")
    assert stored_payload is not None
    assert stored_payload.startswith(b"PK")
    assert preview.status_code == 409
    assert preview.json()["error_code"] == "ae.artifact_file_preview_unavailable"
    assert download.status_code == 200
    assert download.json()["content_type"] == docx_file["mime_type"]
    assert download.json()["download_file_name"] == docx_file["file_name"]
    assert download.json()["content_hash"] == docx_file["file_hash"]
    assert download.json()["content_encoding"] == "base64"
    assert base64.b64decode(download.json()["content_base64"]) == stored_payload
    assert "content" not in download.json()


def test_pdf_render_route_stores_binary_and_downloads_base64() -> None:
    client, handoff_store, artifact_store, _ = build_client_with_artifact_store()
    handoff = handoff_store.save(sample_handoff_record())
    created = client.post(
        "/api/v1/artifacts",
        json={"artifact_handoff_id": handoff["artifact_handoff_id"]},
        headers={**auth_headers(), "Idempotency-Key": "artifact-create-001"},
    )
    artifact_id = created.json()["artifact_id"]

    rendered = client.post(
        f"/api/v1/artifacts/{artifact_id}/render-jobs",
        json={"target_formats": ["PDF"]},
        headers={**auth_headers(), "Idempotency-Key": "render-request-pdf-001"},
    )
    artifact = rendered.json()["artifact"]
    pdf_file = artifact["files"][0]
    preview = client.get(
        f"/api/v1/artifact-files/{pdf_file['artifact_file_id']}/preview",
        headers=auth_headers(),
    )
    download = client.get(
        f"/api/v1/artifact-files/{pdf_file['artifact_file_id']}/download",
        headers=auth_headers(),
    )
    stored_payload = artifact_store.get_rendered_artifact_file(pdf_file)
    reader = pypdf.PdfReader(BytesIO(stored_payload or b""))

    assert rendered.status_code == 200
    assert artifact["versions"][0]["rendered_formats"] == ["PDF"]
    assert pdf_file["format"] == "PDF"
    assert pdf_file["mime_type"] == "application/pdf"
    assert stored_payload is not None
    assert stored_payload.startswith(b"%PDF-1.4")
    assert len(reader.pages) == 1
    assert preview.status_code == 409
    assert preview.json()["error_code"] == "ae.artifact_file_preview_unavailable"
    assert download.status_code == 200
    assert download.json()["content_type"] == "application/pdf"
    assert download.json()["content_encoding"] == "base64"
    assert base64.b64decode(download.json()["content_base64"]) == stored_payload
    assert "content" not in download.json()


def test_markdown_render_route_reports_missing_and_invalid_requests() -> None:
    client, handoff_store, _, source_client = build_client_with_artifact_store()
    handoff = handoff_store.save(sample_handoff_record())
    created = client.post(
        "/api/v1/artifacts",
        json={"artifact_handoff_id": handoff["artifact_handoff_id"]},
        headers={**auth_headers(), "Idempotency-Key": "artifact-create-001"},
    )
    artifact_id = created.json()["artifact_id"]

    missing_artifact = client.post(
        "/api/v1/artifacts/missing/render-jobs",
        json={},
        headers=auth_headers(),
    )
    missing_request_id = client.post(
        f"/api/v1/artifacts/{artifact_id}/render-jobs",
        json={},
        headers={
            key: value
            for key, value in auth_headers().items()
            if key != "Idempotency-Key"
        },
    )
    invalid_format = client.post(
        f"/api/v1/artifacts/{artifact_id}/render-jobs",
        json={"target_formats": ["TXT"]},
        headers=auth_headers(),
    )
    missing_job = client.get(
        "/api/v1/artifact-render-jobs/missing",
        headers=auth_headers(),
    )
    missing_file = client.get(
        "/api/v1/artifact-files/missing",
        headers=auth_headers(),
    )
    missing_preview = client.get(
        "/api/v1/artifact-files/missing/preview",
        headers=auth_headers(),
    )
    source_client.structured_draft = sample_structured_draft(content_hash="9" * 64)
    mismatch = client.post(
        f"/api/v1/artifacts/{artifact_id}/render-jobs",
        json={},
        headers={**auth_headers(), "Idempotency-Key": "render-request-mismatch"},
    )

    assert missing_artifact.status_code == 404
    assert missing_artifact.json()["error_code"] == "ae.artifact_not_found"
    assert missing_request_id.status_code == 422
    assert missing_request_id.json()["error_code"] == "ae.render_request_id_required"
    assert invalid_format.status_code == 422
    assert invalid_format.json()["error_code"] == "ae.render_format_unsupported"
    assert missing_job.status_code == 404
    assert missing_job.json()["error_code"] == "ae.render_job_not_found"
    assert missing_file.status_code == 404
    assert missing_file.json()["error_code"] == "ae.artifact_file_not_found"
    assert missing_preview.status_code == 404
    assert missing_preview.json()["error_code"] == "ae.artifact_file_not_found"
    assert mismatch.status_code == 409
    assert mismatch.json()["error_code"] == "ae.source_draft_hash_mismatch"


def test_artifact_file_payload_resolution_requires_link_and_private_content() -> None:
    store = ArtifactRecordStore()
    artifact_record = build_artifact_record_from_handoff(
        source_payload={"artifact_request_id": "artifact-create-001"},
        handoff_record=sample_handoff_record(),
        artifact_request_id=None,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    store.create(artifact_record)
    render_result = build_markdown_render_result(
        artifact_record=artifact_record,
        structured_draft=sample_structured_draft(),
        target_formats=["MD"],
        render_request_id="render-request-001",
        render_job_id=deterministic_render_job_id(
            artifact_record["artifact_id"],
            "render-request-001",
        ),
    )
    artifact_file = render_result["artifact_files"][0]
    store.artifact_files[artifact_file["artifact_file_id"]] = artifact_file

    with pytest.raises(ArtifactHandoffError) as link_exc:
        resolve_artifact_file_payload(
            store,
            artifact_file_id=artifact_file["artifact_file_id"],
            link_type="download",
        )
    assert link_exc.value.error_code == "ae.artifact_link_not_found"

    store.artifact_links[render_result["artifact_links"][1]["artifact_link_id"]] = (
        render_result["artifact_links"][1]
    )
    with pytest.raises(ArtifactHandoffError) as content_exc:
        resolve_artifact_file_payload(
            store,
            artifact_file_id=artifact_file["artifact_file_id"],
            link_type="download",
    )
    assert content_exc.value.error_code == "ae.artifact_file_not_ready"


def test_local_rendered_artifact_storage_writes_under_configured_root(
    tmp_path,
) -> None:
    artifact_record = build_artifact_record_from_handoff(
        source_payload={"artifact_request_id": "artifact-create-001"},
        handoff_record=sample_handoff_record(),
        artifact_request_id=None,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    render_result = build_markdown_render_result(
        artifact_record=artifact_record,
        structured_draft=sample_structured_draft(),
        target_formats=["MD"],
        render_request_id="render-request-001",
        render_job_id=deterministic_render_job_id(
            artifact_record["artifact_id"],
            "render-request-001",
        ),
    )
    artifact_file = render_result["artifact_files"][0]
    storage = LocalRenderedArtifactStorage(tmp_path / "ae-artifacts")

    assert storage.get_markdown(artifact_file) is None
    returned_ref = storage.save_markdown(artifact_file, render_result["markdown"])
    loaded = storage.get_markdown(artifact_file)
    private_path = storage.path_for_storage_ref(artifact_file["storage_ref"])

    assert returned_ref == artifact_file["storage_ref"]
    assert loaded == render_result["markdown"]
    assert private_path.is_relative_to((tmp_path / "ae-artifacts").resolve())
    assert private_path.read_text(encoding="utf-8") == render_result["markdown"]
    assert str(tmp_path) not in str(artifact_file)
    assert artifact_file["storage_ref"].startswith("ae://artifacts/")
    assert storage.delete_rendered_artifact_file(artifact_file) is True
    assert storage.get_markdown(artifact_file) is None
    assert storage.delete_rendered_artifact_file(artifact_file) is False


@pytest.mark.parametrize(
    "storage_ref",
    [
        "/data/nex-platform/ae/artifact.md",
        "s3://bucket/artifact.md",
        "ae://artifacts/",
        "ae://artifacts/../escape.md",
        "ae://artifacts/artifact//file.md",
    ],
)
def test_local_rendered_artifact_storage_rejects_unsafe_storage_refs(
    tmp_path,
    storage_ref: str,
) -> None:
    storage = LocalRenderedArtifactStorage(tmp_path)

    with pytest.raises(ArtifactHandoffError) as exc_info:
        storage.path_for_storage_ref(storage_ref)

    assert exc_info.value.status_code == 422
    assert exc_info.value.error_code == "ae.artifact_storage_ref_invalid"


def test_default_rendered_artifact_storage_uses_env_root_or_memory(tmp_path) -> None:
    memory_storage = build_default_rendered_artifact_storage({})
    local_storage = build_default_rendered_artifact_storage(
        {"NEX_AE_ARTIFACT_STORAGE_ROOT": str(tmp_path / "configured")}
    )

    assert isinstance(memory_storage, InMemoryRenderedArtifactStorage)
    assert isinstance(local_storage, LocalRenderedArtifactStorage)
    assert local_storage.root == tmp_path / "configured"


def test_default_artifact_stores_use_persistence_session_factory(tmp_path, monkeypatch) -> None:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    session_factory = sqlite_artifact_session_factory()
    app.state.nex_persistence = SimpleNamespace(api_session_factory=session_factory)
    monkeypatch.setenv(
        "NEX_AE_ARTIFACT_STORAGE_ROOT",
        str(tmp_path / "artifact-storage"),
    )

    handoff_store = build_default_artifact_handoff_store(app)
    artifact_store = build_default_artifact_record_store(app)
    history_store = build_default_artifact_retention_execution_history_store(app)

    assert isinstance(handoff_store, SqlAlchemyArtifactHandoffStore)
    assert isinstance(artifact_store, SqlAlchemyArtifactRecordStore)
    assert isinstance(history_store, SqlAlchemyArtifactRetentionExecutionHistoryStore)
    assert isinstance(artifact_store._rendered_storage, LocalRenderedArtifactStorage)


def test_artifact_routes_use_sqlalchemy_defaults_with_local_storage(
    tmp_path,
    monkeypatch,
) -> None:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    app.state.nex_persistence = SimpleNamespace(
        api_session_factory=sqlite_artifact_session_factory()
    )
    storage_root = tmp_path / "artifact-storage"
    monkeypatch.setenv("NEX_AE_ARTIFACT_STORAGE_ROOT", str(storage_root))
    register_artifact_handoff_routes(app, cx_client=FakeCxArtifactSourceClient())
    client = TestClient(app)

    handoff_response = client.post(
        "/api/v1/artifact-handoffs",
        json=artifact_payload(),
        headers=auth_headers(),
    )
    handoff = handoff_response.json()
    artifact_response = client.post(
        "/api/v1/artifacts",
        json={"artifact_handoff_id": handoff["artifact_handoff_id"]},
        headers={**auth_headers(), "Idempotency-Key": "artifact-create-001"},
    )
    artifact_id = artifact_response.json()["artifact_id"]
    render_response = client.post(
        f"/api/v1/artifacts/{artifact_id}/render-jobs",
        json={},
        headers={**auth_headers(), "Idempotency-Key": "render-request-001"},
    )
    rendered = render_response.json()
    artifact_file = rendered["artifact"]["files"][0]
    preview = client.get(
        f"/api/v1/artifact-files/{artifact_file['artifact_file_id']}/preview",
        headers=auth_headers(),
    )
    download = client.get(
        f"/api/v1/artifact-files/{artifact_file['artifact_file_id']}/download",
        headers=auth_headers(),
    )
    collection = client.get(
        "/api/v1/artifacts",
        params={
            "tenant_id": "tenant-001",
            "workspace_id": "workspace-001",
            "owner_user_id": "user-001",
            "status": "READY",
        },
        headers=auth_headers(),
    )

    assert handoff_response.status_code == 200
    assert artifact_response.status_code == 200
    assert render_response.status_code == 200
    assert rendered["artifact"]["artifact_status"] == "READY"
    assert preview.status_code == 200
    assert "Grounded answer [1]." in preview.json()["text_preview"]
    assert download.status_code == 200
    assert download.json()["content"].startswith("# Grounded report")
    assert collection.status_code == 200
    assert collection.json()["count"] == 1
    assert collection.json()["items"][0]["artifact_id"] == artifact_id
    assert collection.json()["items"][0]["downloadable_formats"] == ["MD"]
    assert list(storage_root.rglob("*.md"))
    assert str(storage_root) not in str(rendered)
    assert str(storage_root) not in str(preview.json())
    assert str(storage_root) not in str(collection.json())


def test_sqlalchemy_artifact_handoff_store_round_trips_with_sqlite() -> None:
    store = SqlAlchemyArtifactHandoffStore(sqlite_artifact_session_factory())
    handoff = sample_handoff_record()

    saved = store.save(handoff)
    loaded = store.get(handoff["artifact_handoff_id"])
    saved_again = store.save({**handoff, "artifact_title": "Generated report v2"})
    loaded_again = store.get(handoff["artifact_handoff_id"])
    deleted_rows = store.delete(handoff["artifact_handoff_id"])

    assert saved == handoff
    assert loaded == handoff
    assert saved_again["artifact_title"] == "Generated report v2"
    assert loaded_again is not None
    assert loaded_again["artifact_title"] == "Generated report v2"
    assert loaded_again["target_formats"] == ["MD", "HTML_PREVIEW", "DOCX", "PDF"]
    assert deleted_rows == 1
    assert store.get(handoff["artifact_handoff_id"]) is None


def test_sqlalchemy_artifact_record_store_round_trips_render_metadata_with_sqlite() -> None:
    session_factory = sqlite_artifact_session_factory()
    handoff = sample_handoff_record()
    SqlAlchemyArtifactHandoffStore(session_factory).save(handoff)
    store = SqlAlchemyArtifactRecordStore(session_factory)
    artifact_record = build_artifact_record_from_handoff(
        source_payload={"artifact_request_id": "artifact-create-001"},
        handoff_record=handoff,
        artifact_request_id=None,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    created = store.create(artifact_record)
    repeated = store.create(artifact_record)
    render_result = build_markdown_render_result(
        artifact_record=created,
        structured_draft=sample_structured_draft(),
        target_formats=["MD"],
        render_request_id="render-request-001",
        render_job_id=deterministic_render_job_id(
            created["artifact_id"],
            "render-request-001",
        ),
    )
    updated = store.apply_markdown_render(
        artifact_id=created["artifact_id"],
        artifact_version=render_result["artifact_version"],
        render_job=render_result["render_job"],
        markdown=render_result["markdown"],
        artifact_files=render_result["artifact_files"],
        artifact_links=render_result["artifact_links"],
    )
    artifact_file = render_result["artifact_files"][0]

    assert created == artifact_record
    assert repeated == artifact_record
    assert store.get(created["artifact_id"]) == updated
    assert updated["artifact_status"] == "READY"
    assert store.list_versions(created["artifact_id"]) == [render_result["artifact_version"]]
    assert store.list_versions("missing") is None
    assert store.get_render_job(render_result["render_job"]["render_job_id"]) == (
        render_result["render_job"]
    )
    assert store.get_file(artifact_file["artifact_file_id"]) == artifact_file
    assert store.get_file_link(artifact_file["artifact_file_id"], "preview") == (
        render_result["artifact_links"][0]
    )
    assert store.get_rendered_markdown(
        render_result["artifact_version"]["artifact_version_id"]
    ) == render_result["markdown"]
    assert "/data/nex-platform" not in str(updated)
    assert store.delete(created["artifact_id"]) == 1
    assert store.get(created["artifact_id"]) is None


def test_sqlalchemy_artifact_record_store_lists_owner_scoped_collection_with_sqlite() -> None:
    session_factory = sqlite_artifact_session_factory()
    handoff_store = SqlAlchemyArtifactHandoffStore(session_factory)
    store = SqlAlchemyArtifactRecordStore(session_factory)
    ready = sample_collection_artifact_record(
        artifact_request_id="sql-collection-ready-001",
        artifact_status="READY",
        display_title="SQL ready report",
        updated_at="2026-08-30T09:00:00Z",
    )
    draft = sample_collection_artifact_record(
        artifact_request_id="sql-collection-draft-001",
        artifact_status="DRAFT",
        display_title="SQL draft report",
        updated_at="2026-08-30T08:00:00Z",
    )
    other_workspace = sample_collection_artifact_record(
        artifact_request_id="sql-collection-other-001",
        workspace_id="workspace-002",
        display_title="SQL other workspace report",
        updated_at="2026-08-30T10:00:00Z",
    )
    for record in (draft, other_workspace, ready):
        handoff_store.save(
            {
                **sample_handoff_record(),
                "artifact_handoff_id": record["handoff_ref"]["artifact_handoff_id"],
                "artifact_request_id": record["handoff_ref"]["artifact_request_id"],
                "artifact_title": record["display_title"],
                "actor_claims_ref": record["owner_actor_ref"],
                "workspace_ref": record["workspace_ref"],
            }
        )
        store.save(record)

    collection = store.list_artifacts(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        limit="10",
    )
    ready_only = store.list_artifacts(
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        status="READY",
        limit=10,
    )
    empty = store.list_artifacts(
        tenant_id="tenant-001",
        workspace_id="workspace-999",
        owner_user_id="user-001",
    )

    assert collection["count"] == 2
    assert [item["display_title"] for item in collection["items"]] == [
        "SQL ready report",
        "SQL draft report",
    ]
    assert all(item["workspace_id"] == "workspace-001" for item in collection["items"])
    assert ready_only["count"] == 1
    assert ready_only["items"][0]["artifact_status"] == "READY"
    assert empty["count"] == 0
    assert "storage_ref" not in json.dumps(collection, ensure_ascii=False)


def test_sqlalchemy_artifact_record_store_reports_missing_render_target() -> None:
    store = SqlAlchemyArtifactRecordStore(sqlite_artifact_session_factory())

    with pytest.raises(ArtifactHandoffError) as exc_info:
        store.apply_markdown_render(
            artifact_id="missing",
            artifact_version={"artifact_version_id": "version-missing"},
            render_job={"completed_at": "2026-08-28T00:00:00Z"},
            markdown="# Missing\n",
            artifact_files=[],
            artifact_links=[],
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.error_code == "ae.artifact_not_found"


def test_sqlalchemy_artifact_record_store_reads_markdown_from_local_storage(
    tmp_path,
) -> None:
    session_factory = sqlite_artifact_session_factory()
    handoff = sample_handoff_record()
    SqlAlchemyArtifactHandoffStore(session_factory).save(handoff)
    storage = LocalRenderedArtifactStorage(tmp_path / "artifact-storage")
    store = SqlAlchemyArtifactRecordStore(
        session_factory,
        rendered_storage=storage,
    )
    artifact_record = build_artifact_record_from_handoff(
        source_payload={"artifact_request_id": "artifact-create-001"},
        handoff_record=handoff,
        artifact_request_id=None,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    created = store.create(artifact_record)
    render_result = build_markdown_render_result(
        artifact_record=created,
        structured_draft=sample_structured_draft(),
        target_formats=["MD"],
        render_request_id="render-request-001",
        render_job_id=deterministic_render_job_id(
            created["artifact_id"],
            "render-request-001",
        ),
    )

    updated = store.apply_markdown_render(
        artifact_id=created["artifact_id"],
        artifact_version=render_result["artifact_version"],
        render_job=render_result["render_job"],
        markdown=render_result["markdown"],
        artifact_files=render_result["artifact_files"],
        artifact_links=render_result["artifact_links"],
    )
    markdown = store.get_rendered_markdown(updated["current_version_id"])

    assert markdown == render_result["markdown"]
    assert store.rendered_markdown == {}
    assert storage.get_markdown(updated["files"][0]) == render_result["markdown"]
    assert store.get_rendered_markdown("missing-version") is None
    assert str(tmp_path) not in str(updated)


@pytest.mark.parametrize(
    ("store_type", "operation"),
    [
        ("handoff", "save"),
        ("handoff", "get"),
        ("handoff", "delete"),
        ("record", "save"),
        ("record", "get"),
        ("record", "render_job"),
        ("record", "file"),
        ("record", "file_link"),
        ("record", "list"),
        ("record", "retention_purge"),
        ("record", "delete"),
    ],
)
def test_sqlalchemy_artifact_stores_map_database_errors(
    store_type: str,
    operation: str,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    handoff = sample_handoff_record()
    artifact_record = build_artifact_record_from_handoff(
        source_payload={"artifact_request_id": "artifact-create-001"},
        handoff_record=handoff,
        artifact_request_id=None,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    with pytest.raises(ArtifactHandoffError) as exc_info:
        if store_type == "handoff":
            store = SqlAlchemyArtifactHandoffStore(session_factory)
            if operation == "save":
                store.save(handoff)
            elif operation == "get":
                store.get(handoff["artifact_handoff_id"])
            else:
                store.delete(handoff["artifact_handoff_id"])
        else:
            store = SqlAlchemyArtifactRecordStore(session_factory)
            if operation == "save":
                store.save(artifact_record)
            elif operation == "get":
                store.get(artifact_record["artifact_id"])
            elif operation == "render_job":
                store.get_render_job("missing")
            elif operation == "file":
                store.get_file("missing")
            elif operation == "file_link":
                store.get_file_link("missing", "preview")
            elif operation == "list":
                store.list_artifacts(
                    tenant_id="tenant-001",
                    workspace_id="workspace-001",
                    owner_user_id="user-001",
                )
            elif operation == "retention_purge":
                store.purge_retention_candidates(
                    tenant_id="tenant-001",
                    workspace_id="workspace-001",
                    owner_user_id="user-001",
                )
            else:
                store.delete(artifact_record["artifact_id"])

    assert exc_info.value.status_code == 503
    assert exc_info.value.retryable is True
    assert exc_info.value.error_code in {
        "ae.artifact_handoff_store_unavailable",
        "ae.artifact_store_unavailable",
    }


def test_artifact_sqlalchemy_storage_helpers_cover_dialects_and_nulls() -> None:
    assert ae_artifacts._json_param_expr("target_formats", "postgresql") == (
        "CAST(:target_formats AS jsonb)"
    )
    assert ae_artifacts._json_param_expr("target_formats", "sqlite") == ":target_formats"
    assert ae_artifacts._json_value(None, []) == []
    assert ae_artifacts._json_value({"ok": True}, {}) == {"ok": True}
    assert ae_artifacts._nullable_datetime_value(None) is None
    assert ae_artifacts._datetime_value(None).endswith("Z")
    assert ae_artifacts._datetime_value(
        ae_artifacts.datetime(2026, 8, 28, 0, 0, tzinfo=ae_artifacts.UTC)
    ) == "2026-08-28T00:00:00Z"
    assert ae_artifacts._datetime_value(
        ae_artifacts.datetime.fromisoformat("2026-09-01T09:00:00+09:00")
    ) == "2026-09-01T00:00:00Z"
    assert ae_artifacts._datetime_value(
        type("FakeDate", (), {"isoformat": lambda self: "2026-08-28T00:00:00+00:00"})()
    ) == "2026-08-28T00:00:00Z"
    history_record = build_artifact_retention_execution_history_record(
        sample_retention_execution()
    )
    history_params = ae_artifacts._artifact_retention_execution_history_params(
        history_record
    )
    assert history_params["error"] is None
    assert isinstance(history_params["execution"], str)
    assert ae_artifacts._artifact_retention_execution_history_filter_params(
        {
            "tenant_id": "tenant-001",
            "workspace_id": "workspace-001",
            "owner_user_id": "user-001",
            "mode": None,
            "execution_status": None,
            "limit": 20,
        }
    ) == {
        "tenant_id": "tenant-001",
        "workspace_id": "workspace-001",
        "owner_user_id": "user-001",
        "limit": 20,
    }


def test_artifact_route_requires_auth_and_reports_missing_records() -> None:
    client, _, _ = build_client()

    unauthorized = client.post(
        "/api/v1/artifacts",
        json={"artifact_handoff_id": "handoff-001"},
    )
    missing_handoff = client.post(
        "/api/v1/artifacts",
        json={"artifact_handoff_id": "missing"},
        headers=auth_headers(),
    )
    missing_artifact = client.get(
        "/api/v1/artifacts/missing",
        headers=auth_headers(),
    )
    missing_versions = client.get(
        "/api/v1/artifacts/missing/versions",
        headers=auth_headers(),
    )

    assert unauthorized.status_code == 401
    assert missing_handoff.status_code == 404
    assert missing_handoff.json()["error_code"] == "ae.artifact_handoff_not_found"
    assert missing_artifact.status_code == 404
    assert missing_artifact.json()["error_code"] == "ae.artifact_not_found"
    assert missing_versions.status_code == 404
    assert missing_versions.json()["error_code"] == "ae.artifact_not_found"


def test_artifact_handoff_route_requires_auth_and_reports_missing() -> None:
    client, _, _ = build_client()

    unauthorized = client.post("/api/v1/artifact-handoffs", json=artifact_payload())
    missing = client.get(
        "/api/v1/artifact-handoffs/missing",
        headers=auth_headers(),
    )

    assert unauthorized.status_code == 401
    assert missing.status_code == 404
    assert missing.json()["error_code"] == "ae.artifact_handoff_not_found"


def test_artifact_handoff_rejects_unready_generation_and_invalid_draft() -> None:
    with pytest.raises(ArtifactHandoffError) as generation_exc:
        build_artifact_handoff_record(
            source_payload=artifact_payload(),
            generation_record=sample_generation_record(status="FAILED"),
            structured_draft=sample_structured_draft(),
            artifact_request_id=None,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    assert generation_exc.value.error_code == "ae.source_generation_not_ready"
    assert "COMPLETED" in generation_exc.value.detail

    with pytest.raises(ArtifactHandoffError) as draft_exc:
        build_artifact_handoff_record(
            source_payload=artifact_payload(),
            generation_record=sample_generation_record(),
            structured_draft=sample_structured_draft(status="VALIDATION_FAILED"),
            artifact_request_id=None,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    assert draft_exc.value.error_code == "ae.citation_validation_required"
    assert "validated" in draft_exc.value.detail

    with pytest.raises(ArtifactHandoffError) as citation_exc:
        build_artifact_handoff_record(
            source_payload=artifact_payload(),
            generation_record=sample_generation_record(),
            structured_draft=sample_structured_draft(citation_status="FAILED"),
            artifact_request_id=None,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    assert citation_exc.value.error_code == "ae.citation_validation_required"
    assert "Citation validation" in citation_exc.value.detail


def test_artifact_handoff_rejects_source_draft_mismatch() -> None:
    with pytest.raises(ArtifactHandoffError) as generation_id_exc:
        build_artifact_handoff_record(
            source_payload=artifact_payload(),
            generation_record=sample_generation_record(),
            structured_draft=sample_structured_draft(cx_generation_id="cx-gen-other"),
            artifact_request_id=None,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    assert generation_id_exc.value.error_code == "ae.source_draft_hash_mismatch"
    assert "does not belong" in generation_id_exc.value.detail

    with pytest.raises(ArtifactHandoffError) as draft_id_exc:
        build_artifact_handoff_record(
            source_payload=artifact_payload(),
            generation_record=sample_generation_record(),
            structured_draft=sample_structured_draft(structured_draft_id="draft-other"),
            artifact_request_id=None,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    assert draft_id_exc.value.error_code == "ae.source_draft_hash_mismatch"
    assert "draft ID" in draft_id_exc.value.detail


def test_artifact_handoff_payload_validation_helpers() -> None:
    assert artifact_intent_from_payload({}) == "create_artifact"
    assert artifact_type_from_payload({}) == "generated_document"
    assert target_formats_from_payload({}) == ["MD", "HTML_PREVIEW"]
    assert language_from_payload({}) == "ko"
    assert actor_claims_ref_from_payload({"owner_user_id": "user-001"}) == {
        "actor_type": "user",
        "actor_id": "user-001",
        "tenant_id": "local-tenant",
    }

    with pytest.raises(ArtifactHandoffError) as intent_exc:
        artifact_intent_from_payload({"artifact_intent": "bad"})
    assert intent_exc.value.error_code == "ae.artifact_intent_invalid"
    assert "artifact intent" in intent_exc.value.detail

    with pytest.raises(ArtifactHandoffError) as type_exc:
        artifact_type_from_payload({"artifact_type": "bad"})
    assert type_exc.value.error_code == "ae.artifact_type_invalid"

    with pytest.raises(ArtifactHandoffError) as formats_exc:
        target_formats_from_payload({"target_formats": []})
    assert formats_exc.value.error_code == "ae.target_formats_invalid"
    assert "target_formats" in formats_exc.value.detail

    with pytest.raises(ArtifactHandoffError) as format_exc:
        target_formats_from_payload({"target_formats": ["TXT"]})
    assert format_exc.value.error_code == "ae.render_format_unsupported"

    with pytest.raises(ArtifactHandoffError) as language_exc:
        language_from_payload({"language": "ja"})
    assert language_exc.value.error_code == "ae.language_invalid"

    with pytest.raises(ArtifactHandoffError) as actor_exc:
        actor_claims_ref_from_payload({"actor_claims_ref": "bad"})
    assert actor_exc.value.error_code == "ae.actor_claims_ref_invalid"


def test_artifact_handoff_route_maps_invalid_payload_to_problem() -> None:
    client, _, _ = build_client()

    response = client.post(
        "/api/v1/artifact-handoffs",
        json={**artifact_payload(), "target_formats": ["TXT"]},
        headers=auth_headers(),
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "ae.render_format_unsupported"


def test_http_cx_artifact_source_client_reads_generation_and_draft(monkeypatch) -> None:
    seen_urls: list[str] = []

    def fake_get(url: str, *, headers: dict[str, str], timeout: float) -> httpx.Response:
        seen_urls.append(url)
        assert headers["X-Service-ID"] == "nex-ae-api"
        if url.endswith("/structured-draft"):
            return httpx.Response(status_code=200, json={"structured_draft_id": "draft-001"})
        return httpx.Response(status_code=200, json={"cx_generation_id": "cx-gen-001"})

    monkeypatch.setattr(ae_artifacts.httpx, "get", fake_get)
    client = HttpCxArtifactSourceClient(base_url="http://cx.test")

    assert client.get_generation(
        "cx-gen-001",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    ) == {"cx_generation_id": "cx-gen-001"}
    assert client.get_structured_draft(
        "cx-gen-001",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    ) == {"structured_draft_id": "draft-001"}
    assert seen_urls == [
        "http://cx.test/api/v1/generations/cx-gen-001",
        "http://cx.test/api/v1/generations/cx-gen-001/structured-draft",
    ]


def test_http_cx_artifact_source_client_maps_error_and_bad_json(monkeypatch) -> None:
    def post_error(*args: Any, **kwargs: Any) -> httpx.Response:
        return httpx.Response(
            status_code=503,
            json={
                "error_code": "cx.down",
                "detail": "CX unavailable.",
                "retryable": True,
            },
        )

    monkeypatch.setattr(ae_artifacts.httpx, "get", post_error)
    with pytest.raises(ArtifactHandoffError) as exc_info:
        HttpCxArtifactSourceClient(base_url="http://cx.test").get_generation(
            "cx-gen-001",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    assert exc_info.value.error_code == "cx.down"
    assert exc_info.value.retryable is True

    def bad_json(*args: Any, **kwargs: Any) -> httpx.Response:
        return httpx.Response(status_code=500, content=b"broken")

    monkeypatch.setattr(ae_artifacts.httpx, "get", bad_json)
    with pytest.raises(ArtifactHandoffError) as fallback_exc:
        HttpCxArtifactSourceClient(base_url="http://cx.test").get_structured_draft(
            "cx-gen-001",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    assert fallback_exc.value.error_code == "cx.artifact_source_request_failed"
