from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from nex_cx.ingestion import (
    ContentIngestionStore,
    CxStorageConfig,
    build_upload_registration,
    register_ingestion_routes,
    run_text_extraction_job,
)
from nex_cx.summaries import build_and_store_document_summary, register_summary_routes
from nex_cx.summary_embeddings import (
    SummaryEmbeddingError,
    build_and_store_summary_embedding_index,
    embedding_vector_from_item,
    register_summary_embedding_routes,
    sha256_json,
    store_summary_embedding_index,
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
            "data": [{"object": "embedding", "index": 0, "embedding": [0.0, 0.5, 1.0]}],
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
        raise SummaryEmbeddingError(
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


def build_store_with_summary(tmp_path: Path) -> tuple[ContentIngestionStore, dict[str, Any]]:
    store = ContentIngestionStore()
    config = storage_config(tmp_path)
    document = build_upload_registration(
        {
            "filename": "source.md",
            "content_type": "text/markdown",
            "content_text": "# Source\n\nSummary embedding material.",
        },
        storage_config=config,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    store.save_upload_registration(document, source_text="# Source\n\nSummary embedding material.")
    extraction = run_text_extraction_job(
        document["extraction"]["job_id"],
        store=store,
        storage_config=config,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    summary = build_and_store_document_summary(
        extraction["document_id"],
        store=store,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    return store, summary


def build_test_client(
    tmp_path: Path,
    mo_client: FakeMoEmbeddingClient | FailingMoEmbeddingClient | None = None,
) -> tuple[TestClient, ContentIngestionStore, FakeMoEmbeddingClient | FailingMoEmbeddingClient]:
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    store = ContentIngestionStore()
    config = storage_config(tmp_path)
    client = mo_client or FakeMoEmbeddingClient()
    register_ingestion_routes(app, store=store, storage_config=config)
    register_summary_routes(app, store=store)
    register_summary_embedding_routes(
        app,
        store=store,
        mo_client=client,
        embedding_alias="mock-embedding-default",
    )
    return TestClient(app), store, client


def test_store_summary_embedding_index_hashes_vector_without_leak(
    tmp_path: Path,
) -> None:
    store, summary = build_store_with_summary(tmp_path)
    response = FakeMoEmbeddingClient().create_embeddings(
        [store.get_summary_text(summary["document_summary_id"])],
        alias="mock-embedding-default",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    record = store_summary_embedding_index(
        document_id=summary["document_id"],
        summary=summary,
        mo_response=response,
        store=store,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert record["summary_embedding_schema_version"] == "cx_document_summary_embedding.v1"
    assert record["embedding_sha256"] == sha256_json({"embedding": [0.0, 0.5, 1.0]})
    assert record["vector_dimension"] == 3
    assert store.get_summary_embedding_vector(summary["document_summary_id"]) == [
        0.0,
        0.5,
        1.0,
    ]
    assert "embedding': [0.0" not in str(record)


def test_store_summary_embedding_index_rejects_count_mismatch(
    tmp_path: Path,
) -> None:
    store, summary = build_store_with_summary(tmp_path)

    with pytest.raises(SummaryEmbeddingError) as exc:
        store_summary_embedding_index(
            document_id=summary["document_id"],
            summary=summary,
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
    assert exc.value.error_code == "cx.summary_embedding_response_invalid"


@pytest.mark.parametrize(
    "item",
    [
        ["bad"],
        {"embedding": []},
        {"embedding": ["bad"]},
        {"embedding": [True]},
    ],
)
def test_embedding_vector_from_item_rejects_bad_vectors(item: object) -> None:
    with pytest.raises(SummaryEmbeddingError) as exc:
        embedding_vector_from_item(item)

    assert exc.value.retryable is True
    assert exc.value.error_code == "cx.summary_embedding_response_invalid"


def test_build_and_store_summary_embedding_index_calls_mo_client(
    tmp_path: Path,
) -> None:
    store, summary = build_store_with_summary(tmp_path)
    mo_client = FakeMoEmbeddingClient()

    record = build_and_store_summary_embedding_index(
        summary["document_id"],
        store=store,
        mo_client=mo_client,
        embedding_alias="mock-embedding-default",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert mo_client.calls[0]["inputs"] == [
        store.get_summary_text(summary["document_summary_id"])
    ]
    assert mo_client.calls[0]["trace_id"] == TRACE_ID
    assert record["provider_alias"] == "mock-embedding-default"
    assert store.get_summary_embedding_index(summary["document_id"]) == record


def test_build_and_store_summary_embedding_reports_missing_summary() -> None:
    with pytest.raises(SummaryEmbeddingError) as exc:
        build_and_store_summary_embedding_index(
            "missing-doc",
            store=ContentIngestionStore(),
            mo_client=FakeMoEmbeddingClient(),
            embedding_alias="mock-embedding-default",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert exc.value.error_code == "cx.document_summary_not_found"


def test_build_and_store_summary_embedding_reports_missing_private_text(
    tmp_path: Path,
) -> None:
    store, summary = build_store_with_summary(tmp_path)
    store.summary_texts.clear()

    with pytest.raises(SummaryEmbeddingError) as exc:
        build_and_store_summary_embedding_index(
            summary["document_id"],
            store=store,
            mo_client=FakeMoEmbeddingClient(),
            embedding_alias="mock-embedding-default",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert exc.value.status_code == 409
    assert exc.value.retryable is True
    assert exc.value.error_code == "cx.summary_text_unavailable"


def test_build_and_store_summary_embedding_propagates_mo_error(
    tmp_path: Path,
) -> None:
    store, summary = build_store_with_summary(tmp_path)

    with pytest.raises(SummaryEmbeddingError) as exc:
        build_and_store_summary_embedding_index(
            summary["document_id"],
            store=store,
            mo_client=FailingMoEmbeddingClient(),
            embedding_alias="mock-embedding-default",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert exc.value.status_code == 503
    assert exc.value.retryable is True


def test_summary_embedding_endpoint_materializes_and_reads_index(
    tmp_path: Path,
) -> None:
    client, store, mo_client = build_test_client(tmp_path)
    created = client.post(
        "/api/v1/documents/uploads",
        json={
            "filename": "source.md",
            "content_type": "text/markdown",
            "content_text": "# Source\n\nSummary embedding material.",
        },
        headers=auth_headers(),
    ).json()
    client.post(f"/api/v1/jobs/{created['extraction']['job_id']}/run", headers=auth_headers())
    client.post(f"/api/v1/documents/{created['document_id']}/summary/run", headers=auth_headers())

    run_response = client.post(
        f"/api/v1/documents/{created['document_id']}/summary-embedding/run",
        headers=auth_headers(),
    )
    read_response = client.get(
        f"/api/v1/documents/{created['document_id']}/summary-embedding",
        headers=auth_headers(),
    )

    assert run_response.status_code == 200
    record = run_response.json()
    assert record["vector_dimension"] == 3
    assert mo_client.calls[0]["alias"] == "mock-embedding-default"
    assert store.get_summary_embedding_vector(record["document_summary_id"]) == [
        0.0,
        0.5,
        1.0,
    ]
    assert read_response.status_code == 200
    assert read_response.json()["embedding_sha256"] == record["embedding_sha256"]


def test_summary_embedding_endpoints_require_service_claim(tmp_path: Path) -> None:
    client, _, _ = build_test_client(tmp_path)

    run_response = client.post("/api/v1/documents/missing/summary-embedding/run")
    read_response = client.get("/api/v1/documents/missing/summary-embedding")

    assert run_response.status_code == 401
    assert read_response.status_code == 401
    assert run_response.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"


def test_summary_embedding_endpoint_reports_not_found(tmp_path: Path) -> None:
    client, _, _ = build_test_client(tmp_path)

    run_response = client.post(
        "/api/v1/documents/missing/summary-embedding/run",
        headers=auth_headers(),
    )
    read_response = client.get(
        "/api/v1/documents/missing/summary-embedding",
        headers=auth_headers(),
    )

    assert run_response.status_code == 404
    assert run_response.json()["error_code"] == "cx.document_summary_not_found"
    assert read_response.status_code == 404
    assert read_response.json()["error_code"] == "cx.summary_embedding_not_found"
