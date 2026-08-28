from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import nex_ae_api.artifacts as ae_artifacts
from nex_ae_api.artifacts import (
    ArtifactHandoffError,
    ArtifactHandoffStore,
    ArtifactRecordStore,
    HttpCxArtifactSourceClient,
    SqlAlchemyArtifactHandoffStore,
    SqlAlchemyArtifactRecordStore,
    actor_claims_ref_from_payload,
    artifact_intent_from_payload,
    artifact_type_from_payload,
    build_artifact_links,
    build_artifact_handoff_record,
    build_markdown_artifact_files,
    build_markdown_render_result,
    build_artifact_record_from_handoff,
    deterministic_render_job_id,
    language_from_payload,
    markdown_target_formats_from_payload,
    register_artifact_handoff_routes,
    render_markdown_from_structured_draft,
    resolve_artifact_file_payload,
    safe_file_stem,
    target_formats_from_payload,
    validate_artifact_handoff_record,
    validate_structured_draft_for_markdown_render,
)
from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token


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
        "target_formats": ["MD", "HTML_PREVIEW", "PDF", "MD"],
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


def sqlite_artifact_session_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
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
    assert record["target_formats"] == ["MD", "HTML_PREVIEW", "PDF"]
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
    versions = client.get(
        f"/api/v1/artifacts/{payload['artifact_id']}/versions",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert repeat.json() == payload
    assert readback.status_code == 200
    assert readback.json() == payload
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
        json={"target_formats": ["PDF"]},
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
    assert loaded_again["target_formats"] == ["MD", "HTML_PREVIEW", "PDF"]
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
    assert ae_artifacts._datetime_value(
        ae_artifacts.datetime(2026, 8, 28, 0, 0, tzinfo=ae_artifacts.UTC)
    ) == "2026-08-28T00:00:00Z"
    assert ae_artifacts._datetime_value(
        type("FakeDate", (), {"isoformat": lambda self: "2026-08-28T00:00:00+00:00"})()
    ) == "2026-08-28T00:00:00Z"


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
