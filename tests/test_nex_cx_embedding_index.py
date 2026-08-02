from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

import nex_cx.embedding_index as embedding_index
from nex_cx.chunking import build_and_store_chunk_set
from nex_cx.embedding_index import (
    EmbeddingIndexError,
    HttpMoEmbeddingClient,
    build_and_store_embedding_index,
    ordered_chunk_texts,
    register_embedding_index_routes,
    sha256_json,
    store_embedding_index,
)
from nex_cx.ingestion import (
    ContentIngestionStore,
    CxStorageConfig,
    build_upload_registration,
    register_ingestion_routes,
    run_text_extraction_job,
)
from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


class FakeMoEmbeddingClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create_embeddings(
        self,
        inputs: list[str],
        *,
        alias: str,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "inputs": inputs,
                "alias": alias,
                "request_id": request_id,
                "trace_id": trace_id,
            }
        )
        return {
            "object": "list",
            "alias": alias,
            "model_revision": "mock-embedding-v1",
            "deployment_id": "mock-embedding-local",
            "data": [
                {"object": "embedding", "index": index, "embedding": [float(index), 0.5, 1.0]}
                for index, _ in enumerate(inputs)
            ],
            "usage": {
                "input_tokens": len(inputs),
                "output_tokens": 0,
                "total_tokens": len(inputs),
            },
        }


class FailingMoEmbeddingClient:
    def create_embeddings(
        self,
        inputs: list[str],
        *,
        alias: str,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        raise EmbeddingIndexError(
            status_code=503,
            error_code="mo.embedding_unavailable",
            detail="Embedding provider unavailable.",
            retryable=True,
        )


def auth_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-ae-api", audience="nex-cx")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def storage_config(tmp_path: Path, *, chunk_size: int = 10, overlap: int = 3) -> CxStorageConfig:
    return CxStorageConfig(
        data_root=tmp_path,
        source_root=tmp_path / "cx" / "source-files",
        extracted_markdown_root=tmp_path / "cx" / "extracted-markdown",
        extraction_temp_root=tmp_path / "cx" / "extraction-temp",
        chunk_policy="chunk_1000_100",
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        bm25_tokenizer="mecab_ko",
        bm25_tokenizer_fallback="korean_mixed_v1",
    )


def build_store_with_chunks(
    tmp_path: Path,
    *,
    text: str = "abcdefghijklmnopqrstuvwxyz",
) -> tuple[ContentIngestionStore, dict[str, Any]]:
    store = ContentIngestionStore()
    config = storage_config(tmp_path)
    document = build_upload_registration(
        {
            "filename": "source.txt",
            "content_type": "text/plain",
            "content_text": text,
        },
        storage_config=config,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    store.save_upload_registration(document, source_text=text)
    extraction = run_text_extraction_job(
        document["extraction"]["job_id"],
        store=store,
        storage_config=config,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    chunk_set = build_and_store_chunk_set(
        extraction["document_id"],
        store=store,
        storage_config=config,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    return store, chunk_set


def build_test_client(
    tmp_path: Path,
    mo_client: FakeMoEmbeddingClient | FailingMoEmbeddingClient | None = None,
) -> tuple[TestClient, ContentIngestionStore, FakeMoEmbeddingClient | FailingMoEmbeddingClient]:
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    store = ContentIngestionStore()
    config = storage_config(tmp_path)
    client = mo_client or FakeMoEmbeddingClient()
    register_ingestion_routes(app, store=store, storage_config=config)
    from nex_cx.chunking import register_chunking_routes

    register_chunking_routes(app, store=store, storage_config=config)
    register_embedding_index_routes(
        app,
        store=store,
        mo_client=client,
        embedding_alias="mock-embedding-default",
    )
    return TestClient(app), store, client


def test_ordered_chunk_texts_returns_chunk_text_in_ordinal_order(tmp_path: Path) -> None:
    store, chunk_set = build_store_with_chunks(tmp_path)
    chunk_set["chunks"] = list(reversed(chunk_set["chunks"]))

    ordered = ordered_chunk_texts(chunk_set, store)

    assert ordered[0].startswith("# source")
    assert len(ordered) == chunk_set["chunk_count"]


def test_ordered_chunk_texts_reports_missing_private_text(tmp_path: Path) -> None:
    store, chunk_set = build_store_with_chunks(tmp_path)
    store.chunk_texts.clear()

    with pytest.raises(EmbeddingIndexError) as exc:
        ordered_chunk_texts(chunk_set, store)

    assert exc.value.status_code == 409
    assert exc.value.retryable is True
    assert exc.value.error_code == "cx.chunk_text_unavailable"


def test_store_embedding_index_saves_hashes_without_vector_leak(tmp_path: Path) -> None:
    store, chunk_set = build_store_with_chunks(tmp_path)
    response = FakeMoEmbeddingClient().create_embeddings(
        ordered_chunk_texts(chunk_set, store),
        alias="mock-embedding-default",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    record = store_embedding_index(
        document_id=chunk_set["document_id"],
        chunk_set=chunk_set,
        mo_response=response,
        store=store,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    first = record["chunk_embeddings"][0]
    assert record["embedding_index_schema_version"] == "cx_embedding_index.v1"
    assert record["chunk_count"] == chunk_set["chunk_count"]
    assert record["vector_dimension"] == 3
    assert first["embedding_sha256"] == sha256_json({"embedding": [0.0, 0.5, 1.0]})
    assert store.get_embedding_vector(first["chunk_id"]) == [0.0, 0.5, 1.0]
    assert "embedding': [0.0" not in str(record)


def test_store_embedding_index_rejects_count_mismatch(tmp_path: Path) -> None:
    store, chunk_set = build_store_with_chunks(tmp_path)

    with pytest.raises(EmbeddingIndexError) as exc:
        store_embedding_index(
            document_id=chunk_set["document_id"],
            chunk_set=chunk_set,
            mo_response={
                "alias": "mock-embedding-default",
                "model_revision": "mock-embedding-v1",
                "deployment_id": "mock-embedding-local",
                "data": [],
            },
            store=store,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert exc.value.status_code == 502
    assert exc.value.error_code == "cx.embedding_response_invalid"


@pytest.mark.parametrize(
    "data",
    [
        ["not-object"],
        [{"embedding": []}],
        [{"embedding": ["bad"]}],
        [{"embedding": [True]}],
    ],
)
def test_store_embedding_index_rejects_bad_embedding_items(
    tmp_path: Path,
    data: list[object],
) -> None:
    store, chunk_set = build_store_with_chunks(tmp_path, text="short")
    chunk_set["chunks"] = chunk_set["chunks"][:1]
    chunk_set["chunk_count"] = 1

    with pytest.raises(EmbeddingIndexError) as exc:
        store_embedding_index(
            document_id=chunk_set["document_id"],
            chunk_set=chunk_set,
            mo_response={
                "alias": "mock-embedding-default",
                "model_revision": "mock-embedding-v1",
                "deployment_id": "mock-embedding-local",
                "data": data,
            },
            store=store,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert exc.value.error_code == "cx.embedding_response_invalid"


def test_build_and_store_embedding_index_calls_mo_client(tmp_path: Path) -> None:
    store, chunk_set = build_store_with_chunks(tmp_path)
    mo_client = FakeMoEmbeddingClient()

    record = build_and_store_embedding_index(
        chunk_set["document_id"],
        store=store,
        mo_client=mo_client,
        embedding_alias="mock-embedding-default",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert mo_client.calls[0]["alias"] == "mock-embedding-default"
    assert mo_client.calls[0]["trace_id"] == TRACE_ID
    assert record["provider_alias"] == "mock-embedding-default"
    assert store.get_embedding_index(chunk_set["document_id"]) == record


def test_build_and_store_embedding_index_reports_missing_chunk_set(tmp_path: Path) -> None:
    with pytest.raises(EmbeddingIndexError) as exc:
        build_and_store_embedding_index(
            "missing-doc",
            store=ContentIngestionStore(),
            mo_client=FakeMoEmbeddingClient(),
            embedding_alias="mock-embedding-default",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert exc.value.error_code == "cx.chunk_set_not_found"


def test_build_and_store_embedding_index_propagates_mo_error(tmp_path: Path) -> None:
    store, chunk_set = build_store_with_chunks(tmp_path)

    with pytest.raises(EmbeddingIndexError) as exc:
        build_and_store_embedding_index(
            chunk_set["document_id"],
            store=store,
            mo_client=FailingMoEmbeddingClient(),
            embedding_alias="mock-embedding-default",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert exc.value.status_code == 503
    assert exc.value.retryable is True


def test_embedding_index_endpoint_requires_service_claim(tmp_path: Path) -> None:
    client, _, _ = build_test_client(tmp_path)

    response = client.post("/api/v1/documents/missing/embeddings/run")

    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"


def test_embedding_index_read_requires_service_claim(tmp_path: Path) -> None:
    client, _, _ = build_test_client(tmp_path)

    response = client.get("/api/v1/documents/missing/embeddings")

    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"


def test_embedding_index_endpoint_materializes_and_reads_index(tmp_path: Path) -> None:
    client, store, mo_client = build_test_client(tmp_path)
    created = client.post(
        "/api/v1/documents/uploads",
        json={
            "filename": "source.txt",
            "content_type": "text/plain",
            "content_text": "abcdefghijklmnopqrstuvwxyz",
        },
        headers=auth_headers(),
    ).json()
    client.post(f"/api/v1/jobs/{created['extraction']['job_id']}/run", headers=auth_headers())
    client.post(f"/api/v1/documents/{created['document_id']}/chunks/run", headers=auth_headers())

    run_response = client.post(
        f"/api/v1/documents/{created['document_id']}/embeddings/run",
        headers=auth_headers(),
    )
    read_response = client.get(
        f"/api/v1/documents/{created['document_id']}/embeddings",
        headers=auth_headers(),
    )

    assert run_response.status_code == 200
    payload = run_response.json()
    assert payload["chunk_count"] == len(mo_client.calls[0]["inputs"])
    assert payload["vector_dimension"] == 3
    assert store.get_embedding_vector(payload["chunk_embeddings"][0]["chunk_id"]) is not None
    assert read_response.status_code == 200
    assert read_response.json()["provider_alias"] == "mock-embedding-default"


def test_embedding_index_endpoint_reports_missing_chunk_set(tmp_path: Path) -> None:
    client, _, _ = build_test_client(tmp_path)

    response = client.post(
        "/api/v1/documents/missing/embeddings/run",
        headers=auth_headers(),
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "cx.chunk_set_not_found"


def test_embedding_index_endpoint_reports_mo_failure(tmp_path: Path) -> None:
    client, _, _ = build_test_client(tmp_path, mo_client=FailingMoEmbeddingClient())
    created = client.post(
        "/api/v1/documents/uploads",
        json={"filename": "source.txt", "content_type": "text/plain", "content_text": "abc"},
        headers=auth_headers(),
    ).json()
    client.post(f"/api/v1/jobs/{created['extraction']['job_id']}/run", headers=auth_headers())
    client.post(f"/api/v1/documents/{created['document_id']}/chunks/run", headers=auth_headers())

    response = client.post(
        f"/api/v1/documents/{created['document_id']}/embeddings/run",
        headers=auth_headers(),
    )

    assert response.status_code == 503
    assert response.json()["error_code"] == "mo.embedding_unavailable"


def test_embedding_index_read_reports_not_found(tmp_path: Path) -> None:
    client, _, _ = build_test_client(tmp_path)

    response = client.get(
        "/api/v1/documents/missing/embeddings",
        headers=auth_headers(),
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "cx.embedding_index_not_found"


def test_http_mo_embedding_client_posts_with_mock_token(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake_post(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return httpx.Response(
            200,
            json={
                "object": "list",
                "alias": "mock-embedding-default",
                "model_revision": "mock-embedding-v1",
                "deployment_id": "mock-embedding-local",
                "data": [{"object": "embedding", "index": 0, "embedding": [0.1]}],
            },
        )

    monkeypatch.setattr(embedding_index.httpx, "post", fake_post)

    response = HttpMoEmbeddingClient(base_url="http://mo.test").create_embeddings(
        ["hello"],
        alias="mock-embedding-default",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert response["alias"] == "mock-embedding-default"
    assert calls[0]["args"] == ("http://mo.test/api/v1/embeddings",)
    assert calls[0]["kwargs"]["json"] == {
        "alias": "mock-embedding-default",
        "inputs": ["hello"],
    }
    assert calls[0]["kwargs"]["headers"]["Authorization"].startswith(
        "Bearer nex-mock-service."
    )


def test_http_mo_embedding_client_raises_safe_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(*args, **kwargs):
        return httpx.Response(
            503,
            json={
                "error_code": "mo.unavailable",
                "detail": "Unavailable",
                "retryable": True,
            },
        )

    monkeypatch.setattr(embedding_index.httpx, "post", fake_post)

    with pytest.raises(EmbeddingIndexError) as exc:
        HttpMoEmbeddingClient(base_url="http://mo.test").create_embeddings(
            ["hello"],
            alias="mock-embedding-default",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert exc.value.status_code == 503
    assert exc.value.error_code == "mo.unavailable"
    assert exc.value.retryable is True


def test_http_mo_embedding_client_handles_non_json_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_post(*args, **kwargs):
        return httpx.Response(500, content=b"not-json")

    monkeypatch.setattr(embedding_index.httpx, "post", fake_post)

    with pytest.raises(EmbeddingIndexError) as exc:
        HttpMoEmbeddingClient(base_url="http://mo.test").create_embeddings(
            ["hello"],
            alias="mock-embedding-default",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert exc.value.error_code == "mo.embedding_request_failed"
