from __future__ import annotations

import base64
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
    ArtifactRecordStore,
    HttpCxArtifactSourceClient,
    InMemoryRenderedArtifactStorage,
    LocalRenderedArtifactStorage,
    SqlAlchemyArtifactHandoffStore,
    SqlAlchemyArtifactRecordStore,
    actor_claims_ref_from_payload,
    artifact_content_kind,
    artifact_file_extension,
    artifact_file_name_for_format,
    artifact_intent_from_payload,
    artifact_mime_type,
    artifact_format_spec,
    artifact_type_from_payload,
    build_artifact_links,
    build_artifact_links_for_files,
    build_default_artifact_handoff_store,
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

    assert isinstance(handoff_store, SqlAlchemyArtifactHandoffStore)
    assert isinstance(artifact_store, SqlAlchemyArtifactRecordStore)
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

    assert handoff_response.status_code == 200
    assert artifact_response.status_code == 200
    assert render_response.status_code == 200
    assert rendered["artifact"]["artifact_status"] == "READY"
    assert preview.status_code == 200
    assert "Grounded answer [1]." in preview.json()["text_preview"]
    assert download.status_code == 200
    assert download.json()["content"].startswith("# Grounded report")
    assert list(storage_root.rglob("*.md"))
    assert str(storage_root) not in str(rendered)
    assert str(storage_root) not in str(preview.json())


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
    assert ae_artifacts._datetime_value(None).endswith("Z")
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
