from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nex_cx.chunking import (
    ChunkingError,
    build_and_store_chunk_set,
    build_chunk_items,
    chunk_text,
    register_chunking_routes,
    store_chunk_set,
    validate_chunk_policy,
)
from nex_cx.ingestion import (
    ContentIngestionStore,
    CxStorageConfig,
    build_upload_registration,
    register_ingestion_routes,
    run_text_extraction_job,
    sha256_text,
)
from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


def auth_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-ae-api", audience="nex-cx")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def storage_config(tmp_path: Path, *, chunk_size: int = 1000, overlap: int = 100) -> CxStorageConfig:
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


def build_test_client(
    tmp_path: Path,
    *,
    chunk_size: int = 1000,
    overlap: int = 100,
) -> tuple[TestClient, ContentIngestionStore]:
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    store = ContentIngestionStore()
    config = storage_config(tmp_path, chunk_size=chunk_size, overlap=overlap)
    register_ingestion_routes(app, store=store, storage_config=config)
    register_chunking_routes(app, store=store, storage_config=config)
    return TestClient(app), store


def build_store_with_extraction(
    tmp_path: Path,
    *,
    text: str = "hello extraction",
    chunk_size: int = 1000,
    overlap: int = 100,
) -> tuple[ContentIngestionStore, CxStorageConfig, dict[str, object]]:
    store = ContentIngestionStore()
    config = storage_config(tmp_path, chunk_size=chunk_size, overlap=overlap)
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
    return store, config, extraction


def test_chunk_text_returns_empty_for_empty_text() -> None:
    assert chunk_text("", chunk_size=5, chunk_overlap=2) == []


def test_chunk_text_uses_overlap_offsets() -> None:
    chunks = chunk_text("abcdefghijkl", chunk_size=5, chunk_overlap=2)

    assert chunks == [
        {"start_offset": 0, "end_offset": 5, "text": "abcde"},
        {"start_offset": 3, "end_offset": 8, "text": "defgh"},
        {"start_offset": 6, "end_offset": 11, "text": "ghijk"},
        {"start_offset": 9, "end_offset": 12, "text": "jkl"},
    ]


def test_chunk_text_uses_single_chunk_for_short_text() -> None:
    assert chunk_text("abc", chunk_size=5, chunk_overlap=2) == [
        {"start_offset": 0, "end_offset": 3, "text": "abc"}
    ]


@pytest.mark.parametrize(
    ("chunk_size", "overlap", "detail"),
    [
        (0, 0, "positive"),
        (10, -1, "non-negative"),
        (10, 10, "smaller"),
        (10, 11, "smaller"),
    ],
)
def test_validate_chunk_policy_rejects_invalid_values(
    chunk_size: int,
    overlap: int,
    detail: str,
) -> None:
    with pytest.raises(ChunkingError) as exc:
        validate_chunk_policy(chunk_size=chunk_size, chunk_overlap=overlap)

    assert exc.value.error_code == "cx.chunk_policy_invalid"
    assert detail in exc.value.detail


def test_build_chunk_items_returns_public_metadata_and_private_text() -> None:
    public, private = build_chunk_items(
        [{"start_offset": 0, "end_offset": 5, "text": "abcde"}],
        document_id="doc-001",
    )

    chunk_id = public[0]["chunk_id"]
    assert public[0]["ordinal"] == 0
    assert public[0]["text_sha256"] == sha256_text("abcde")
    assert public[0]["text_preview"] == "abcde"
    assert private == {chunk_id: "abcde"}


def test_store_chunk_set_saves_private_chunk_text(tmp_path: Path) -> None:
    store, config, extraction = build_store_with_extraction(
        tmp_path,
        text="abcdefghij",
        chunk_size=5,
        overlap=1,
    )

    chunk_set = store_chunk_set(
        document_id=extraction["document_id"],
        extraction=extraction,
        markdown_text="abcdefghij",
        store=store,
        storage_config=config,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    first_chunk_id = chunk_set["chunks"][0]["chunk_id"]
    assert chunk_set["chunk_count"] == 3
    assert store.get_chunk_set(extraction["document_id"]) == chunk_set
    assert store.get_chunk_text(first_chunk_id) == "abcde"
    assert "abcdefghij" not in str(chunk_set)


def test_build_and_store_chunk_set_reads_extracted_markdown(tmp_path: Path) -> None:
    store, config, extraction = build_store_with_extraction(
        tmp_path,
        text="abcdefghijkl",
        chunk_size=5,
        overlap=2,
    )

    chunk_set = build_and_store_chunk_set(
        extraction["document_id"],
        store=store,
        storage_config=config,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert chunk_set["chunk_set_schema_version"] == "cx_chunk_set.v1"
    assert chunk_set["chunk_policy"] == "chunk_1000_100"
    assert chunk_set["chunk_size"] == 5
    assert chunk_set["chunk_overlap"] == 2
    assert chunk_set["chunk_count"] > 1


def test_build_and_store_chunk_set_reports_missing_extraction(tmp_path: Path) -> None:
    with pytest.raises(ChunkingError) as exc:
        build_and_store_chunk_set(
            "missing-doc",
            store=ContentIngestionStore(),
            storage_config=storage_config(tmp_path),
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert exc.value.error_code == "cx.extraction_result_not_found"


def test_build_and_store_chunk_set_reports_missing_markdown_file(tmp_path: Path) -> None:
    store, config, extraction = build_store_with_extraction(tmp_path)
    Path(extraction["extracted_markdown_path"]).unlink()

    with pytest.raises(ChunkingError) as exc:
        build_and_store_chunk_set(
            extraction["document_id"],
            store=store,
            storage_config=config,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert exc.value.status_code == 409
    assert exc.value.retryable is True
    assert exc.value.error_code == "cx.extracted_markdown_missing"


def test_run_chunks_endpoint_requires_service_claim(tmp_path: Path) -> None:
    client, _ = build_test_client(tmp_path)

    response = client.post("/api/v1/documents/missing/chunks/run")

    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"


def test_get_chunks_endpoint_requires_service_claim(tmp_path: Path) -> None:
    client, _ = build_test_client(tmp_path)

    response = client.get("/api/v1/documents/missing/chunks")

    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"


def test_chunks_endpoint_materializes_and_reads_chunk_set(tmp_path: Path) -> None:
    client, store = build_test_client(tmp_path, chunk_size=10, overlap=3)
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

    run_response = client.post(
        f"/api/v1/documents/{created['document_id']}/chunks/run",
        headers=auth_headers(),
    )
    read_response = client.get(
        f"/api/v1/documents/{created['document_id']}/chunks",
        headers=auth_headers(),
    )

    assert run_response.status_code == 200
    payload = run_response.json()
    assert payload["document_id"] == created["document_id"]
    assert payload["chunk_count"] == len(payload["chunks"])
    assert store.get_chunk_text(payload["chunks"][0]["chunk_id"]) is not None
    assert read_response.status_code == 200
    assert read_response.json()["source_markdown_sha256"] == payload["source_markdown_sha256"]


def test_chunks_endpoint_reports_missing_extraction(tmp_path: Path) -> None:
    client, _ = build_test_client(tmp_path)

    response = client.post(
        "/api/v1/documents/missing/chunks/run",
        headers=auth_headers(),
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "cx.extraction_result_not_found"


def test_get_chunks_endpoint_reports_not_found(tmp_path: Path) -> None:
    client, _ = build_test_client(tmp_path)

    response = client.get("/api/v1/documents/missing/chunks", headers=auth_headers())

    assert response.status_code == 404
    assert response.json()["error_code"] == "cx.chunk_set_not_found"
