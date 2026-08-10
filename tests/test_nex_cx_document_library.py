from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from nex_cx.document_library import (
    CX_DOCUMENT_LIBRARY_PROJECTION_SCHEMA_VERSION,
    build_document_library_projection,
    build_document_library_query_filters,
    register_document_library_routes,
)
from nex_cx.ingestion import (
    ContentIngestionStore,
    CxStorageConfig,
    build_upload_registration,
    sha256_text,
)
from nex_cx.repository import (
    CxContentRepositoryError,
    InMemoryCxContentRepository,
    build_content_object_record,
    build_source_file_record,
)
from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


def storage_config(tmp_path: Path) -> CxStorageConfig:
    return CxStorageConfig(
        data_root=tmp_path,
        source_root=tmp_path / "cx" / "source-files",
        extracted_markdown_root=tmp_path / "cx" / "extracted-markdown",
        extraction_temp_root=tmp_path / "cx" / "extraction-temp",
        chunk_policy="chunk_1000_100",
        chunk_size=1000,
        chunk_overlap=100,
        bm25_tokenizer="mecab_ko",
        bm25_tokenizer_fallback="korean_mixed_v1",
    )


def upload_registration(
    tmp_path: Path,
    *,
    content_text: str,
    tenant_id: str = "tenant-a",
    owner_user_id: str = "user-a",
) -> dict[str, Any]:
    return build_upload_registration(
        {
            "filename": "source.md",
            "content_type": "text/markdown",
            "content_text": content_text,
            "tenant_id": tenant_id,
            "owner_user_id": owner_user_id,
        },
        storage_config=storage_config(tmp_path),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )


def auth_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-ae-api", audience="nex-cx")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def document_library_client(
    *,
    store: ContentIngestionStore | None = None,
    database_env: str | None = None,
    redacted_database_url: str | None = None,
    source_kind: str = "memory",
) -> tuple[TestClient, ContentIngestionStore]:
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    selected_store = store or ContentIngestionStore()
    register_document_library_routes(
        app,
        store=selected_store,
        database_env=database_env,
        redacted_database_url=redacted_database_url,
        source_kind=source_kind,
    )
    return TestClient(app), selected_store


class FailingDocumentLibraryRepository:
    def list_active_content_objects(self, **_: object) -> list[dict[str, Any]]:
        raise CxContentRepositoryError(
            error_code="cx.content_repository_unavailable",
            detail="repository offline",
            status_code=503,
        )


def test_document_library_filters_normalize_owner_scope_and_limit() -> None:
    filters = build_document_library_query_filters(
        tenant_id=" tenant-a ",
        owner_user_id=" user-a ",
        limit="250",
    )

    assert filters["tenant_ref"] == {"type": "oa.tenant", "id": "tenant-a"}
    assert filters["owner_subject_ref"] == {"type": "oa.user", "id": "user-a"}
    assert filters["lifecycle_status"] == "ACTIVE"
    assert filters["limit"] == 100
    assert build_document_library_query_filters(limit=0)["limit"] == 1
    with pytest.raises(ValueError, match="limit must be an integer"):
        build_document_library_query_filters(limit="many")
    with pytest.raises(ValueError, match="tenant_id"):
        build_document_library_query_filters(tenant_id=" ")


def test_document_library_projection_is_owner_scoped_and_raw_safe(
    tmp_path: Path,
) -> None:
    store = ContentIngestionStore()
    user_a = store.save_upload_registration(
        upload_registration(tmp_path, content_text="private source for user a"),
        source_text="private source for user a",
    )
    store.save_upload_registration(
        upload_registration(
            tmp_path,
            content_text="private source for user b",
            owner_user_id="user-b",
        ),
        source_text="private source for user b",
    )
    summary = {
        "document_summary_id": "summary-a",
        "document_id": user_a["document_id"],
        "status": "READY",
        "summary_text_sha256": sha256_text("private summary body"),
        "summary_preview": "private summary preview",
        "summary_char_count": 22,
        "summarizer": {
            "model_profile_id": "mock-document-summary",
            "model_revision": "slice-0027",
        },
        "updated_at": "2026-08-10T00:00:00Z",
    }
    store.save_document_summary(summary, summary_text="private summary body")
    store.save_summary_embedding_index(
        {
            "summary_embedding_id": "summary-embedding-a",
            "document_id": user_a["document_id"],
            "document_summary_id": summary["document_summary_id"],
            "provider_alias": "qwen3-embedding",
            "model_revision": "Qwen3-Embedding-4B",
            "vector_dimension": 3,
            "embedding_sha256": sha256_text("embedding metadata only"),
            "status": "READY",
            "created_at": "2026-08-10T00:00:01Z",
        },
        embedding_vector=[0.1, 0.2, 0.3],
    )
    processing_run = {
        "pipeline_run_id": "pipeline-run-a",
        "document_id": user_a["document_id"],
        "status": "SUCCEEDED",
        "step_summary": {"total": 4, "failed": 0},
        "updated_at": "2026-08-10T00:00:02Z",
    }
    store.document_processing_runs[processing_run["pipeline_run_id"]] = processing_run
    store.latest_processing_run_ids_by_document[user_a["document_id"]] = (
        processing_run["pipeline_run_id"]
    )

    projection = build_document_library_projection(
        store=store,
        tenant_id="tenant-a",
        owner_user_id="user-a",
    )

    assert projection["projection_schema_version"] == (
        CX_DOCUMENT_LIBRARY_PROJECTION_SCHEMA_VERSION
    )
    assert projection["pagination"] == {"limit": 50, "returned": 1}
    assert projection["summary"] == {
        "document_count": 1,
        "summary_available_count": 1,
        "summary_embedding_available_count": 1,
    }
    item = projection["documents"][0]
    assert item["document_id"] == user_a["document_id"]
    assert item["owner_subject_ref"] == {"type": "oa.user", "id": "user-a"}
    assert item["summary"]["summary_preview"] == "private summary preview"
    assert item["summary_embedding"]["vector_dimension"] == 3
    assert item["processing"]["latest_pipeline_run_id"] == "pipeline-run-a"
    assert "private source for user b" not in str(projection)
    assert "private summary body" not in str(projection)
    assert "source_storage_path" not in str(projection)
    assert "[0.1, 0.2, 0.3]" not in str(projection)
    assert item["metadata"]["storage_path_redacted"] is True


def test_document_library_projection_reads_persisted_summary_metadata(
    tmp_path: Path,
) -> None:
    repository = InMemoryCxContentRepository()
    upload = upload_registration(tmp_path, content_text="source")
    source_file = repository.save_source_file(build_source_file_record(upload))
    content_object = repository.save_content_object(
        build_content_object_record(
            upload,
            tenant_id="tenant-a",
            owner_user_id="user-a",
            source_file_id=source_file["source_file_id"],
        )
    )
    repository.save_document_summary_record(
        {
            "document_summary_id": "persisted-summary-a",
            "content_object_id": content_object["content_object_id"],
            "extraction_artifact_id": "extraction-a",
            "summary_text_sha256": sha256_text("summary"),
            "summary_char_count": 7,
            "summary_max_chars": 900,
            "summary_hard_limit_chars": 1000,
            "summary_chunk_policy_id": "summary_1000_0",
            "summary_storage_uri": "local://cx/document-summaries/hidden.md",
            "status": "READY",
            "model_profile_id": "mock-document-summary",
            "model_revision": "slice-0027",
            "created_at": "2026-08-10T00:00:00Z",
            "updated_at": "2026-08-10T00:00:00Z",
        }
    )
    repository.save_summary_embedding_record(
        {
            "summary_embedding_id": "persisted-summary-embedding-a",
            "document_summary_id": "persisted-summary-a",
            "provider_alias": "qwen3-embedding",
            "model_profile_id": "Qwen3-Embedding-4B",
            "model_revision": "BF16",
            "deployment_id": "dgx-vllm-embedding",
            "vector_dimension": 2560,
            "embedding_sha256": sha256_text("summary embedding"),
            "status": "READY",
            "created_at": "2026-08-10T00:00:01Z",
        }
    )
    store = ContentIngestionStore(content_repository=repository)

    projection = build_document_library_projection(
        store=store,
        tenant_id="tenant-a",
        owner_user_id="user-a",
    )

    item = projection["documents"][0]
    assert item["summary"]["document_summary_id"] == "persisted-summary-a"
    assert item["summary"]["summary_preview"] is None
    assert item["summary"]["model_profile_id"] == "mock-document-summary"
    assert item["summary_embedding"]["model_profile_id"] == "Qwen3-Embedding-4B"
    assert item["summary_embedding"]["vector_dimension"] == 2560
    assert "summary_storage_uri" not in str(projection)


def test_document_library_projection_handles_missing_derived_records(
    tmp_path: Path,
) -> None:
    store = ContentIngestionStore()
    upload = store.save_upload_registration(
        upload_registration(tmp_path, content_text="source"),
    )

    projection = build_document_library_projection(
        store=store,
        tenant_id="tenant-a",
        owner_user_id="user-a",
    )

    item = projection["documents"][0]
    assert item["document_id"] == upload["document_id"]
    assert item["summary"]["available"] is False
    assert item["summary_embedding"]["available"] is False
    assert item["processing"]["available"] is False
    assert projection["metadata"]["raw_source_included"] is False


def test_document_library_projection_handles_sparse_summary_metadata(
    tmp_path: Path,
) -> None:
    store = ContentIngestionStore()
    upload = store.save_upload_registration(
        upload_registration(tmp_path, content_text="source"),
    )
    store.document_summaries[upload["document_id"]] = {
        "document_summary_id": None,
        "status": "READY",
        "summary_text_sha256": None,
        "summary_char_count": True,
        "summarizer": "legacy-string-shape",
        "updated_at": None,
    }
    processing_run = {
        "pipeline_run_id": "pipeline-run-sparse",
        "document_id": upload["document_id"],
        "status": "FAILED",
        "step_summary": {"total": "unknown", "failed": True},
        "updated_at": "2026-08-10T00:00:00Z",
    }
    store.document_processing_runs[processing_run["pipeline_run_id"]] = processing_run
    store.latest_processing_run_ids_by_document[upload["document_id"]] = (
        processing_run["pipeline_run_id"]
    )

    projection = build_document_library_projection(
        store=store,
        tenant_id="tenant-a",
        owner_user_id="user-a",
    )

    item = projection["documents"][0]
    assert item["summary"]["available"] is True
    assert item["summary"]["document_summary_id"] is None
    assert item["summary"]["summary_char_count"] == 0
    assert item["summary"]["model_profile_id"] is None
    assert item["summary_embedding"]["available"] is False
    assert item["processing"]["step_total"] == 0
    assert item["processing"]["step_failed"] == 0


@pytest.mark.parametrize("vector_dimension", [True, "2560", 0])
def test_document_library_projection_redacts_untrusted_embedding_dimensions(
    tmp_path: Path,
    vector_dimension: object,
) -> None:
    store = ContentIngestionStore()
    upload = store.save_upload_registration(
        upload_registration(tmp_path, content_text=f"source {vector_dimension}"),
    )
    store.save_summary_embedding_index(
        {
            "summary_embedding_id": f"summary-embedding-{vector_dimension}",
            "document_id": upload["document_id"],
            "document_summary_id": "summary-a",
            "provider_alias": "qwen3-embedding",
            "model_revision": "Qwen3-Embedding-4B",
            "vector_dimension": vector_dimension,
            "embedding_sha256": sha256_text(f"embedding {vector_dimension}"),
            "status": "READY",
            "created_at": "2026-08-10T00:00:01Z",
        },
        embedding_vector=[0.1],
    )

    projection = build_document_library_projection(
        store=store,
        tenant_id="tenant-a",
        owner_user_id="user-a",
    )

    assert projection["documents"][0]["summary_embedding"]["vector_dimension"] is None


def test_document_library_route_lists_owner_scoped_documents(
    tmp_path: Path,
) -> None:
    client, store = document_library_client(
        database_env="NEX_CX_TEST_DATABASE_URL",
        redacted_database_url=(
            "postgresql+psycopg://nex_cx_user:***@127.0.0.1:5432/nex_cx_test"
        ),
        source_kind="postgres-read",
    )
    user_a = store.save_upload_registration(
        upload_registration(tmp_path, content_text="source a"),
    )
    store.save_upload_registration(
        upload_registration(
            tmp_path,
            content_text="source b",
            owner_user_id="user-b",
        ),
    )

    response = client.get(
        "/api/v1/documents",
        params={"tenant_id": "tenant-a", "owner_user_id": "user-a", "limit": 10},
        headers=auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["projection_schema_version"] == (
        CX_DOCUMENT_LIBRARY_PROJECTION_SCHEMA_VERSION
    )
    assert payload["source"] == {
        "source_kind": "postgres-read",
        "database_env": "NEX_CX_TEST_DATABASE_URL",
        "redacted_database_url": (
            "postgresql+psycopg://nex_cx_user:***@127.0.0.1:5432/nex_cx_test"
        ),
    }
    assert payload["pagination"] == {"limit": 10, "returned": 1}
    assert payload["documents"][0]["document_id"] == user_a["document_id"]
    assert payload["documents"][0]["links"]["cx_document"].endswith(
        f"/{user_a['document_id']}"
    )
    assert "source b" not in str(payload)


def test_document_library_route_requires_service_claim() -> None:
    client, _ = document_library_client()

    response = client.get("/api/v1/documents")

    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"


def test_document_library_route_maps_query_validation_error() -> None:
    client, _ = document_library_client()

    response = client.get(
        "/api/v1/documents",
        params={"tenant_id": " ", "owner_user_id": "user-a"},
        headers=auth_headers(),
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "cx.document_library_query_invalid"


def test_document_library_route_maps_repository_unavailable() -> None:
    client, _ = document_library_client(
        store=ContentIngestionStore(
            content_repository=FailingDocumentLibraryRepository(),
        ),
    )

    response = client.get(
        "/api/v1/documents",
        params={"tenant_id": "tenant-a", "owner_user_id": "user-a"},
        headers=auth_headers(),
    )

    assert response.status_code == 503
    payload = response.json()
    assert payload["error_code"] == "cx.content_repository_unavailable"
    assert payload["retryable"] is True
