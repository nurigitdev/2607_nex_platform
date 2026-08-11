from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
from jsonschema import Draft202012Validator
from fastapi.testclient import TestClient
import pytest

import nex_ae_api.documents as ae_documents
from nex_ae_api.documents import (
    DocumentLibraryError,
    HttpCxDocumentLibraryClient,
    build_document_detail_from_cx,
    build_document_detail_projection,
    build_document_library_item_from_cx,
    build_document_library_item,
    build_summary_projection,
    cx_document_detail_item,
    extraction_status,
    markdown_available,
    owner_scope_query_params,
    register_document_library_routes,
    search_summary_items,
)
from nex_ae_api.uploads import UploadHandoffStore
from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"
SOURCE_HASH = "d12261539d27dcab69f873a5e1a30587919b8ce4802782151f1bc2ba5390b610"


class FakeCxDocumentLibraryClient:
    def __init__(self, *, fail_document: bool = False, with_summary: bool = True) -> None:
        self.fail_document = fail_document
        self.with_summary = with_summary
        self.calls: list[str] = []

    def get_document(
        self,
        document_id: str,
        *,
        tenant_id: str,
        owner_user_id: str,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        self.calls.append(f"document:{document_id}:{tenant_id}:{owner_user_id}")
        if self.fail_document:
            raise DocumentLibraryError(
                status_code=503,
                error_code="cx.document_unavailable",
                detail="CX document unavailable.",
                retryable=True,
            )
        return {
            **cx_detail_projection(document_id=document_id),
        }

    def get_summary(
        self,
        document_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any] | None:
        self.calls.append(f"summary:{document_id}")
        if not self.with_summary:
            return None
        return {
            "document_id": document_id,
            "status": "SUCCEEDED",
            "summary_text_sha256": "a" * 64,
            "summary_preview": "MVP upload retrieval generation audit flow.",
            "summary_char_count": 42,
        }

    def get_summary_embedding(
        self,
        document_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any] | None:
        self.calls.append(f"summary-embedding:{document_id}")
        if not self.with_summary:
            return None
        return {
            "document_id": document_id,
            "status": "READY",
            "model_profile_id": "qwen3-embedding-4b-bf16",
            "dimension": 8,
        }


def auth_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience="nex-ae-api")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def upload_handoff(
    *,
    upload_handoff_id: str = "handoff-001",
    workspace_id: str = "workspace-001",
    filename: str = "mvp-srs.md",
    document_id: str = "doc-001",
) -> dict[str, Any]:
    return {
        "upload_handoff_id": upload_handoff_id,
        "workspace_id": workspace_id,
        "tenant_id": "tenant-a",
        "owner_user_id": "user-a",
        "source": {
            "filename": filename,
            "content_type": "text/markdown",
            "size_bytes": 23,
            "source_sha256": SOURCE_HASH,
        },
        "cx_document_ref": {
            "document_id": document_id,
            "upload_id": "upload-001",
            "ingestion_job_id": "job-001",
            "extraction_status": "PENDING",
            "markdown_available": False,
            "dedupe_status": "CREATED",
            "existing_document_id": None,
        },
    }


def cx_detail_projection(
    *,
    document_id: str = "doc-001",
    summary_available: bool = True,
    processing_status: str = "SUCCEEDED",
) -> dict[str, Any]:
    return {
        "projection_schema_version": "cx_document_detail_projection.v1",
        "source": {
            "source_kind": "upload",
        },
        "document": {
            "document_detail_schema_version": "cx_document_detail_item.v1",
            "document_id": document_id,
            "tenant_ref": {
                "ref_type": "oa.tenant",
                "id": "tenant-a",
            },
            "owner_subject_ref": {
                "ref_type": "oa.user",
                "id": "user-a",
            },
            "uploaded_by_subject_ref": {
                "ref_type": "oa.user",
                "id": "user-a",
            },
            "upload": {
                "upload_id": "upload-001",
                "upload_handoff_id": "handoff-001",
                "filename": "mvp-srs.md",
                "content_type": "text/markdown",
                "size_bytes": 23,
                "source_sha256": SOURCE_HASH,
                "source_content_in_record": False,
            },
            "extraction": {
                "available": True,
                "job_id": "job-001",
                "status": "SUCCEEDED",
                "markdown_available": True,
                "markdown_text_sha256": "b" * 64,
                "markdown_char_count": 512,
            },
            "summary": {
                "available": summary_available,
                "status": "SUCCEEDED" if summary_available else "NOT_READY",
                "summary_text_sha256": "a" * 64 if summary_available else None,
                "summary_preview": (
                    "MVP upload retrieval generation audit flow."
                    if summary_available
                    else None
                ),
                "summary_char_count": 42 if summary_available else 0,
            },
            "summary_embedding": {
                "available": summary_available,
                "status": "READY" if summary_available else "NOT_READY",
                "model_profile_id": (
                    "qwen3-embedding-4b-bf16" if summary_available else None
                ),
                "vector_dimension": 8 if summary_available else None,
            },
            "processing": {
                "available": True,
                "latest_pipeline_run_id": "run-001",
                "status": processing_status,
                "step_total": 4,
                "step_failed": 0,
                "updated_at": "2026-08-11T00:00:00Z",
            },
            "source_lineage": {
                "source_file_id": "source-file-001",
                "source_sha256": SOURCE_HASH,
                "content_type": "text/markdown",
                "size_bytes": 23,
                "storage_key_included": False,
                "storage_uri_included": False,
                "storage_path_included": False,
                "storage_path": "/data/nex-platform/cx/source-files/private.md",
            },
        },
        "metadata": {
            "owner_scoped": True,
            "not_found_and_not_authorized_collapsed": True,
        },
    }


def build_client(
    *,
    store: UploadHandoffStore | None = None,
    cx_client: FakeCxDocumentLibraryClient | None = None,
) -> tuple[TestClient, UploadHandoffStore, FakeCxDocumentLibraryClient]:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    upload_store = store or UploadHandoffStore()
    client = cx_client or FakeCxDocumentLibraryClient()
    register_document_library_routes(app, upload_store=upload_store, cx_client=client)
    return TestClient(app), upload_store, client


def test_build_document_library_item_projects_safe_status_and_summary() -> None:
    item = build_document_library_item(
        upload_handoff=upload_handoff(),
        cx_document={
            "extraction": {
                "status": "SUCCEEDED",
                "markdown_available": True,
            }
        },
        summary={
            "status": "SUCCEEDED",
            "summary_text_sha256": "a" * 64,
            "summary_preview": "MVP upload retrieval generation audit flow.",
            "summary_char_count": 42,
        },
        summary_embedding={
            "status": "READY",
            "model_profile_id": "qwen3-embedding-4b-bf16",
            "dimension": 8,
        },
    )

    assert item["status"]["extraction_status"] == "SUCCEEDED"
    assert item["summary"]["summary_available"] is True
    assert item["summary"]["summary_embedding_dimension"] == 8
    assert item["metadata"]["raw_summary_stored_in_ae"] is False
    assert "source_storage_path" not in str(item)


def test_summary_projection_handles_missing_summary_and_fallback_extraction() -> None:
    projection = build_summary_projection(None, None)

    assert projection["summary_available"] is False
    assert projection["summary_preview"] is None
    assert extraction_status({}, {"extraction_status": "PENDING"}) == "PENDING"
    assert markdown_available({}, {"markdown_available": False}) is False


def test_owner_scope_query_params_trim_and_validate() -> None:
    assert owner_scope_query_params(
        tenant_id=" tenant-a ",
        owner_user_id=" user-a ",
    ) == {"tenant_id": "tenant-a", "owner_user_id": "user-a"}

    with pytest.raises(DocumentLibraryError) as tenant_exc:
        owner_scope_query_params(tenant_id=" ", owner_user_id="user-a")
    with pytest.raises(DocumentLibraryError) as owner_exc:
        owner_scope_query_params(tenant_id="tenant-a", owner_user_id=None)

    assert tenant_exc.value.error_code == "ae.document_owner_scope_invalid"
    assert tenant_exc.value.status_code == 422
    assert owner_exc.value.detail == "owner_user_id must be a non-empty string."


def test_status_helpers_accept_cx_document_detail_projection() -> None:
    detail_projection = {
        "projection_schema_version": "cx_document_detail_projection.v1",
        "document": {
            "extraction": {
                "available": True,
                "job_id": "job-001",
                "status": "SUCCEEDED",
                "markdown_available": True,
            }
        },
    }

    assert extraction_status(
        detail_projection,
        {"extraction_status": "PENDING"},
    ) == "SUCCEEDED"
    assert markdown_available(
        detail_projection,
        {"markdown_available": False},
    ) is True


def test_cx_document_detail_item_accepts_nested_and_flat_payloads() -> None:
    nested = cx_detail_projection()
    flat = {"document_id": "doc-flat"}

    assert cx_document_detail_item(nested)["document_id"] == "doc-001"
    assert cx_document_detail_item(flat) == flat


def test_build_document_detail_projection_projects_safe_cx_detail() -> None:
    projection = build_document_detail_projection(
        upload_handoff=upload_handoff(),
        cx_document=cx_detail_projection(),
    )

    document = projection["document"]
    assert projection["projection_schema_version"] == "ae_document_detail_projection.v1"
    assert document["document_detail_schema_version"] == "ae_document_detail_item.v1"
    assert document["document_id"] == "doc-001"
    assert document["status"] == {
        "dedupe_status": "CREATED",
        "extraction_status": "SUCCEEDED",
        "markdown_available": True,
        "summary_status": "SUCCEEDED",
        "summary_embedding_status": "READY",
        "processing_status": "SUCCEEDED",
    }
    assert document["summary"]["summary_available"] is True
    assert document["summary"]["summary_embedding_dimension"] == 8
    assert document["processing"]["step_total"] == 4
    assert document["source_lineage"]["source_file_id"] == "source-file-001"
    assert document["source_lineage"]["storage_path_included"] is False
    assert projection["cx"]["owner_scoped"] is True
    assert projection["cx"]["not_found_and_not_authorized_collapsed"] is True
    assert projection["metadata"]["cx_detail_passthrough"] is False
    assert "/data/nex-platform" not in str(projection)
    assert "private.md" not in str(projection)
    assert "raw_summary_text" not in str(projection)


def test_build_document_detail_projection_matches_contract_schema() -> None:
    schema_path = (
        Path(__file__).parents[1]
        / "contracts"
        / "schemas"
        / "service"
        / "nex_ae_api"
        / "document_detail_projection.v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    projection = build_document_detail_projection(
        upload_handoff=upload_handoff(),
        cx_document=cx_detail_projection(),
    )

    Draft202012Validator(schema).validate(projection)


def test_build_document_detail_projection_defaults_unavailable_parts() -> None:
    projection = build_document_detail_projection(
        upload_handoff=upload_handoff(),
        cx_document={
            "projection_schema_version": "cx_document_detail_projection.v1",
            "document": {
                "document_detail_schema_version": "cx_document_detail_item.v1",
                "extraction": {
                    "status": "RUNNING",
                    "markdown_available": False,
                },
                "summary": {
                    "available": False,
                    "summary_char_count": -1,
                },
                "summary_embedding": {
                    "available": False,
                    "vector_dimension": 0,
                },
                "processing": {
                    "available": False,
                    "status": False,
                    "step_total": True,
                    "step_failed": -2,
                },
                "source_lineage": "not-a-mapping",
            },
            "metadata": {
                "owner_scoped": False,
            },
        },
    )

    assert projection["document"]["status"]["extraction_status"] == "RUNNING"
    assert projection["document"]["status"]["markdown_available"] is False
    assert projection["document"]["status"]["summary_status"] == "NOT_READY"
    assert projection["document"]["status"]["summary_embedding_status"] == "NOT_READY"
    assert projection["document"]["summary"]["summary_char_count"] == 0
    assert projection["document"]["summary"]["summary_embedding_dimension"] is None
    assert projection["document"]["processing"]["status"] == "NOT_READY"
    assert projection["document"]["processing"]["step_total"] == 0
    assert projection["document"]["processing"]["step_failed"] == 0
    assert projection["document"]["source_lineage"]["source_sha256"] == SOURCE_HASH
    assert projection["document"]["source_lineage"]["size_bytes"] == 23
    assert projection["cx"]["owner_scoped"] is False


def test_build_document_detail_from_cx_passes_owner_scope_and_uses_detail_once() -> None:
    client = FakeCxDocumentLibraryClient()

    detail = build_document_detail_from_cx(
        client=client,
        upload_handoff={
            **upload_handoff(),
            "tenant_id": " tenant-a ",
            "owner_user_id": " user-a ",
        },
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert detail["document"]["document_id"] == "doc-001"
    assert detail["document"]["summary"]["summary_available"] is True
    assert client.calls == ["document:doc-001:tenant-a:user-a"]


def test_search_summary_items_scores_and_sorts_matches() -> None:
    first = build_document_library_item(
        upload_handoff=upload_handoff(filename="mvp-srs.md"),
        cx_document={"extraction": {"status": "SUCCEEDED", "markdown_available": True}},
        summary={
            "status": "SUCCEEDED",
            "summary_text_sha256": "a" * 64,
            "summary_preview": "retrieval generation",
            "summary_char_count": 20,
        },
        summary_embedding=None,
    )
    second = build_document_library_item(
        upload_handoff=upload_handoff(
            upload_handoff_id="handoff-002",
            filename="audit.md",
            document_id="doc-002",
        ),
        cx_document={"extraction": {"status": "SUCCEEDED", "markdown_available": True}},
        summary={
            "status": "SUCCEEDED",
            "summary_text_sha256": "b" * 64,
            "summary_preview": "audit",
            "summary_char_count": 5,
        },
        summary_embedding=None,
    )

    matches = search_summary_items([first, second], query="generation retrieval")

    assert [match["document"]["filename"] for match in matches] == ["mvp-srs.md"]
    assert matches[0]["score"] == 2
    assert search_summary_items([first], query="   ") == []


def test_build_document_library_item_from_cx_passes_owner_scope() -> None:
    client = FakeCxDocumentLibraryClient()

    item = build_document_library_item_from_cx(
        client=client,
        upload_handoff={
            **upload_handoff(),
            "tenant_id": " tenant-a ",
            "owner_user_id": " user-a ",
        },
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert item["document_id"] == "doc-001"
    assert item["status"]["extraction_status"] == "SUCCEEDED"
    assert client.calls == [
        "document:doc-001:tenant-a:user-a",
        "summary:doc-001",
        "summary-embedding:doc-001",
    ]


def test_document_library_routes_list_empty_and_populated_workspace() -> None:
    store = UploadHandoffStore()
    store.save(upload_handoff())
    client, _, cx_client = build_client(store=store)

    empty = client.get("/api/v1/workspaces/empty/documents", headers=auth_headers())
    populated = client.get("/api/v1/workspaces/workspace-001/documents", headers=auth_headers())

    assert empty.status_code == 200
    assert empty.json() == {"workspace_id": "empty", "documents": []}
    assert populated.status_code == 200
    assert populated.json()["documents"][0]["document_id"] == "doc-001"
    assert cx_client.calls == [
        "document:doc-001:tenant-a:user-a",
        "summary:doc-001",
        "summary-embedding:doc-001",
    ]


def test_document_summary_search_route_matches_by_summary_preview() -> None:
    store = UploadHandoffStore()
    store.save(upload_handoff())
    client, _, _ = build_client(store=store)

    response = client.get(
        "/api/v1/documents/summary-search?workspace_id=workspace-001&query=retrieval",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert response.json()["matches"][0]["document"]["filename"] == "mvp-srs.md"


def test_document_detail_route_returns_owner_scoped_projection() -> None:
    store = UploadHandoffStore()
    store.save(upload_handoff())
    client, _, cx_client = build_client(store=store)

    response = client.get("/api/v1/documents/doc-001", headers=auth_headers())

    assert response.status_code == 200
    payload = response.json()
    assert payload["projection_schema_version"] == "ae_document_detail_projection.v1"
    assert payload["workspace_id"] == "workspace-001"
    assert payload["document"]["document_id"] == "doc-001"
    assert payload["document"]["summary"]["summary_available"] is True
    assert payload["document"]["source_lineage"]["storage_uri_included"] is False
    assert cx_client.calls == ["document:doc-001:tenant-a:user-a"]


def test_document_detail_route_requires_auth() -> None:
    client, _, cx_client = build_client()

    response = client.get("/api/v1/documents/doc-001")

    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"
    assert cx_client.calls == []


def test_document_detail_route_returns_not_found_without_cx_call() -> None:
    store = UploadHandoffStore()
    store.save({**upload_handoff(upload_handoff_id="broken"), "cx_document_ref": None})
    client, _, cx_client = build_client(store=store)

    response = client.get("/api/v1/documents/missing", headers=auth_headers())

    assert response.status_code == 404
    assert response.json()["error_code"] == "ae.document_not_found"
    assert cx_client.calls == []


def test_document_detail_route_rejects_invalid_handoff_owner_scope() -> None:
    store = UploadHandoffStore()
    store.save({**upload_handoff(), "tenant_id": " "})
    client, _, cx_client = build_client(store=store)

    response = client.get("/api/v1/documents/doc-001", headers=auth_headers())

    assert response.status_code == 422
    assert response.json()["error_code"] == "ae.document_owner_scope_invalid"
    assert response.json()["detail"] == "tenant_id must be a non-empty string."
    assert cx_client.calls == []


def test_document_detail_route_propagates_cx_error() -> None:
    store = UploadHandoffStore()
    store.save(upload_handoff())
    client, _, cx_client = build_client(
        store=store,
        cx_client=FakeCxDocumentLibraryClient(fail_document=True),
    )

    response = client.get("/api/v1/documents/doc-001", headers=auth_headers())

    assert response.status_code == 503
    assert response.json()["error_code"] == "cx.document_unavailable"
    assert response.json()["retryable"] is True
    assert cx_client.calls == ["document:doc-001:tenant-a:user-a"]


def test_document_summary_search_route_requires_auth() -> None:
    client, _, cx_client = build_client()

    response = client.get(
        "/api/v1/documents/summary-search?workspace_id=workspace-001&query=retrieval"
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"
    assert cx_client.calls == []


def test_document_library_routes_require_auth_and_propagate_cx_error() -> None:
    store = UploadHandoffStore()
    store.save(upload_handoff())
    client, _, _ = build_client(
        store=store,
        cx_client=FakeCxDocumentLibraryClient(fail_document=True),
    )

    unauthorized = client.get("/api/v1/workspaces/workspace-001/documents")
    failed = client.get("/api/v1/workspaces/workspace-001/documents", headers=auth_headers())

    assert unauthorized.status_code == 401
    assert failed.status_code == 503
    assert failed.json()["error_code"] == "cx.document_unavailable"
    assert failed.json()["retryable"] is True


def test_document_library_route_handles_missing_summary() -> None:
    store = UploadHandoffStore()
    store.save(upload_handoff())
    client, _, _ = build_client(
        store=store,
        cx_client=FakeCxDocumentLibraryClient(with_summary=False),
    )

    response = client.get("/api/v1/workspaces/workspace-001/documents", headers=auth_headers())

    assert response.status_code == 200
    assert response.json()["documents"][0]["summary"]["summary_available"] is False
    assert response.json()["documents"][0]["status"]["summary_status"] == "NOT_READY"


def test_document_library_route_rejects_invalid_handoff_owner_scope() -> None:
    store = UploadHandoffStore()
    store.save({**upload_handoff(), "owner_user_id": " "})
    client, _, cx_client = build_client(store=store)

    response = client.get("/api/v1/workspaces/workspace-001/documents", headers=auth_headers())

    assert response.status_code == 422
    assert response.json()["error_code"] == "ae.document_owner_scope_invalid"
    assert response.json()["detail"] == "owner_user_id must be a non-empty string."
    assert cx_client.calls == []


def test_document_summary_search_route_rejects_invalid_handoff_owner_scope() -> None:
    store = UploadHandoffStore()
    store.save({**upload_handoff(), "tenant_id": None})
    client, _, cx_client = build_client(store=store)

    response = client.get(
        "/api/v1/documents/summary-search?workspace_id=workspace-001&query=retrieval",
        headers=auth_headers(),
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "ae.document_owner_scope_invalid"
    assert response.json()["detail"] == "tenant_id must be a non-empty string."
    assert cx_client.calls == []


def test_http_cx_document_library_client_fetches_and_maps_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[tuple[str, dict[str, str] | None]] = []

    def fake_get(
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, str] | None = None,
        timeout: float,
    ) -> httpx.Response:
        captured.append((url, params))
        if url.endswith("/summary"):
            return httpx.Response(status_code=404, json={"error_code": "missing"})
        if url.endswith("/summary-embedding"):
            return httpx.Response(
                status_code=503,
                json={
                    "error_code": "cx.summary_embedding_unavailable",
                    "detail": "Unavailable.",
                    "retryable": True,
                },
            )
        return httpx.Response(status_code=200, json={"document_id": "doc-001"})

    monkeypatch.setattr(ae_documents.httpx, "get", fake_get)
    client = HttpCxDocumentLibraryClient(base_url="http://cx")

    assert client.get_document(
        "doc-001",
        tenant_id="tenant-a",
        owner_user_id="user-a",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    ) == {"document_id": "doc-001"}
    assert client.get_summary("doc-001", request_id=REQUEST_ID, trace_id=TRACE_ID) is None
    with pytest.raises(DocumentLibraryError) as exc:
        client.get_summary_embedding(
            "doc-001",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert captured == [
        (
            "http://cx/api/v1/documents/doc-001",
            {"tenant_id": "tenant-a", "owner_user_id": "user-a"},
        ),
        ("http://cx/api/v1/documents/doc-001/summary", None),
        ("http://cx/api/v1/documents/doc-001/summary-embedding", None),
    ]
    assert exc.value.error_code == "cx.summary_embedding_unavailable"


def test_http_cx_document_library_client_uses_default_error_for_bad_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get(*args: Any, **kwargs: Any) -> httpx.Response:
        return httpx.Response(status_code=500, content=b"broken")

    monkeypatch.setattr(ae_documents.httpx, "get", fake_get)
    with pytest.raises(DocumentLibraryError) as exc:
        HttpCxDocumentLibraryClient(base_url="http://cx").get_document(
            "doc-001",
            tenant_id="tenant-a",
            owner_user_id="user-a",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert exc.value.error_code == "cx.document_library_request_failed"


def test_http_cx_document_library_client_uses_default_error_for_non_object_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get(*args: Any, **kwargs: Any) -> httpx.Response:
        return httpx.Response(status_code=500, json=["broken"])

    monkeypatch.setattr(ae_documents.httpx, "get", fake_get)
    with pytest.raises(DocumentLibraryError) as exc:
        HttpCxDocumentLibraryClient(base_url="http://cx").get_document(
            "doc-001",
            tenant_id="tenant-a",
            owner_user_id="user-a",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert exc.value.error_code == "cx.document_library_request_failed"
