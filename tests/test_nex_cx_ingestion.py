from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nex_cx.ingestion import (
    ContentIngestionStore,
    CxStorageConfig,
    IngestionError,
    build_ingestion_job,
    build_storage_config,
    build_upload_registration,
    markdown_from_source_text,
    register_ingestion_routes,
    run_text_extraction_job,
    sanitize_filename,
    sha256_text,
    storage_date_partition,
    storage_paths_for_document,
    stored_extension_for,
    write_extracted_markdown,
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


def build_test_client(
    tmp_path: Path,
) -> tuple[TestClient, ContentIngestionStore]:
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    store = ContentIngestionStore()
    register_ingestion_routes(app, store=store, storage_config=storage_config(tmp_path))
    return TestClient(app), store


def test_build_storage_config_uses_data_root_defaults() -> None:
    config = build_storage_config({"NEX_DATA_ROOT": "/data/nex-platform"})

    assert str(config.data_root) == "/data/nex-platform"
    assert str(config.source_root) == "/data/nex-platform/cx/source-files"
    assert str(config.extracted_markdown_root) == "/data/nex-platform/cx/extracted-markdown"
    assert str(config.extraction_temp_root) == "/data/nex-platform/cx/extraction-temp"
    assert config.chunk_size == 1000
    assert config.chunk_overlap == 100
    assert config.bm25_tokenizer == "mecab_ko"
    assert config.bm25_tokenizer_fallback == "korean_mixed_v1"


def test_build_storage_config_accepts_explicit_overrides() -> None:
    config = build_storage_config(
        {
            "NEX_DATA_ROOT": "/nex-data",
            "NEX_CX_SOURCE_STORAGE_ROOT": "/source",
            "NEX_CX_EXTRACTED_MARKDOWN_ROOT": "/markdown",
            "NEX_CX_EXTRACTION_TEMP_ROOT": "/temp",
            "NEX_CX_DEFAULT_CHUNK_POLICY": "custom",
            "NEX_CX_CHUNK_SIZE": "1200",
            "NEX_CX_CHUNK_OVERLAP": "80",
            "NEX_CX_BM25_TOKENIZER": "mecab_ko",
            "NEX_CX_BM25_TOKENIZER_FALLBACK": "korean_mixed_v1",
        }
    )

    assert str(config.source_root) == "/source"
    assert str(config.extracted_markdown_root) == "/markdown"
    assert str(config.extraction_temp_root) == "/temp"
    assert config.chunk_policy == "custom"
    assert config.chunk_size == 1200
    assert config.chunk_overlap == 80


@pytest.mark.parametrize(
    "env",
    [
        {"NEX_CX_CHUNK_SIZE": "0"},
        {"NEX_CX_CHUNK_SIZE": "not-an-int"},
        {"NEX_CX_CHUNK_OVERLAP": "-1"},
        {"NEX_CX_CHUNK_OVERLAP": "not-an-int"},
    ],
)
def test_build_storage_config_rejects_bad_numeric_values(env: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        build_storage_config(env)


def test_sanitize_filename_trims_basename() -> None:
    assert sanitize_filename("  report.pdf  ") == "report.pdf"


@pytest.mark.parametrize("filename", ["", ".", "..", "../report.pdf", "a/b.pdf", "bad\x00.pdf"])
def test_sanitize_filename_rejects_unsafe_names(filename: str) -> None:
    with pytest.raises(IngestionError):
        sanitize_filename(filename)


def test_sanitize_filename_rejects_long_name() -> None:
    with pytest.raises(IngestionError):
        sanitize_filename("a" * 256)


def test_storage_paths_partition_by_date_hash_and_generated_filename(tmp_path: Path) -> None:
    paths = storage_paths_for_document(
        storage_config=storage_config(tmp_path),
        filename="report.md",
        source_sha256="a" * 64,
        document_id="doc-001",
        created_at="2026-08-02T00:00:00Z",
    )

    assert paths["source_storage_backend"] == "local_filesystem"
    assert paths["source_storage_key"] == "20260802/aa/aa/doc-001.md"
    assert paths["source_storage_path"].endswith("/cx/source-files/20260802/aa/aa/doc-001.md")
    assert paths["stored_filename"] == "doc-001.md"
    assert paths["stored_extension"] == ".md"
    assert paths["extracted_markdown_path"].endswith("/cx/extracted-markdown/aa/doc-001.md")
    assert paths["extraction_temp_path"].endswith("/cx/extraction-temp/doc-001")


def test_stored_extension_for_uses_safe_lowercase_suffix_only() -> None:
    assert stored_extension_for("REPORT.PDF") == ".pdf"
    assert stored_extension_for("archive.tar.gz") == ".gz"
    assert stored_extension_for("source") == ""
    assert stored_extension_for("unsafe.$$$") == ""


def test_storage_date_partition_falls_back_for_invalid_timestamp() -> None:
    partition = storage_date_partition("not-a-timestamp")

    assert len(partition) == 8
    assert partition.isdigit()


def test_build_ingestion_job_links_document() -> None:
    job = build_ingestion_job(
        document_id="doc-001",
        upload_id="upload-001",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        created_at="2026-08-02T00:00:00Z",
    )

    assert job["job_schema_version"] == "common_job.v1"
    assert job["status"] == "QUEUED"
    assert job["subject_ref"] == {"type": "cx.document", "id": "doc-001"}
    assert job["links"]["document"] == "/api/v1/documents/doc-001"


def test_build_upload_registration_hashes_content_without_leaking_text(tmp_path: Path) -> None:
    record = build_upload_registration(
        {
            "filename": "mvp-srs.md",
            "content_type": "text/markdown",
            "content_text": "# MVP\nTraceable content",
        },
        storage_config=storage_config(tmp_path),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert record["document_schema_version"] == "cx_upload_registration.v1"
    assert record["source_sha256"] == sha256_text("# MVP\nTraceable content")
    assert record["size_bytes"] == len("# MVP\nTraceable content".encode("utf-8"))
    assert record["retrieval_policy"]["chunk_policy"] == "chunk_1000_100"
    assert record["retrieval_policy"]["bm25_tokenizer_fallback"] == "korean_mixed_v1"
    assert "Traceable content" not in str(record)


def test_store_keeps_source_text_private_for_mock_extraction(tmp_path: Path) -> None:
    store = ContentIngestionStore()
    record = build_upload_registration(
        {"filename": "source.md", "content_text": "private source text"},
        storage_config=storage_config(tmp_path),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    store.save_upload_registration(record, source_text="private source text")

    assert store.get_source_text(record["upload_id"]) == "private source text"
    assert "private source text" not in str(store.get_document(record["document_id"]))


def test_build_upload_registration_accepts_precomputed_hash(tmp_path: Path) -> None:
    record = build_upload_registration(
        {
            "filename": "source.pdf",
            "content_type": "application/pdf",
            "source_sha256": "A" * 64,
            "size_bytes": 2048,
        },
        storage_config=storage_config(tmp_path),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert record["source_sha256"] == "a" * 64
    assert record["size_bytes"] == 2048
    assert record["storage"]["source_storage_key"].endswith(f"/{record['document_id']}.pdf")
    assert record["storage"]["stored_extension"] == ".pdf"
    assert "/source.pdf" not in record["storage"]["source_storage_path"]


@pytest.mark.parametrize(
    ("payload", "error_code"),
    [
        ({"content_text": "hello"}, "cx.filename_required"),
        ({"filename": "report.pdf", "size_bytes": 10}, "cx.source_sha256_required"),
        (
            {"filename": "report.pdf", "source_sha256": "bad", "size_bytes": 10},
            "cx.upload_hash_invalid",
        ),
        (
            {"filename": "report.pdf", "source_sha256": "a" * 64},
            "cx.upload_size_required",
        ),
        (
            {"filename": "report.pdf", "source_sha256": "a" * 64, "size_bytes": -1},
            "cx.upload_size_invalid",
        ),
        (
            {"filename": "report.pdf", "content_type": "", "content_text": "hello"},
            "cx.content_type_invalid",
        ),
        (
            {"filename": "report.pdf", "content_text": ["hello"]},
            "cx.upload_content_text_invalid",
        ),
    ],
)
def test_build_upload_registration_reports_validation_errors(
    tmp_path: Path,
    payload: dict[str, object],
    error_code: str,
) -> None:
    with pytest.raises(IngestionError) as exc:
        build_upload_registration(
            payload,
            storage_config=storage_config(tmp_path),
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert exc.value.error_code == error_code


def test_upload_registration_endpoint_requires_service_claim(tmp_path: Path) -> None:
    client, _ = build_test_client(tmp_path)

    response = client.post("/api/v1/documents/uploads", json={"filename": "report.pdf"})

    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"


def test_upload_registration_endpoint_creates_document_and_job(tmp_path: Path) -> None:
    client, store = build_test_client(tmp_path)

    response = client.post(
        "/api/v1/documents/uploads",
        json={
            "filename": "source.md",
            "content_type": "text/markdown",
            "content_text": "hello from upload",
        },
        headers=auth_headers(),
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["trace_id"] == TRACE_ID
    assert payload["request_id"] == REQUEST_ID
    assert payload["extraction"]["status"] == "PENDING"
    assert payload["extraction"]["markdown_available"] is False
    assert store.get_document(payload["document_id"]) == payload
    assert store.get_job(payload["extraction"]["job_id"]) == payload["ingestion_job"]


def test_markdown_from_source_text_preserves_markdown() -> None:
    markdown = markdown_from_source_text(
        "# Existing\n\nBody",
        filename="source.md",
        content_type="text/markdown",
    )

    assert markdown == "# Existing\n\nBody\n"


def test_markdown_from_source_text_wraps_plain_text_with_title() -> None:
    markdown = markdown_from_source_text(
        "Plain extracted body",
        filename="source.txt",
        content_type="text/plain",
    )

    assert markdown == "# source.txt\n\nPlain extracted body\n"


def test_markdown_from_source_text_keeps_existing_trailing_newline() -> None:
    markdown = markdown_from_source_text(
        "Plain extracted body\n",
        filename="source.txt",
        content_type="text/plain",
    )

    assert markdown == "# source.txt\n\nPlain extracted body\n"


def test_markdown_from_source_text_handles_blank_source() -> None:
    assert markdown_from_source_text("  ", filename="empty.pdf", content_type="application/pdf") == (
        "# empty.pdf\n\n"
    )


def test_write_extracted_markdown_creates_parent_directory(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "document.md"

    write_extracted_markdown(path, "# Written\n")

    assert path.read_text(encoding="utf-8") == "# Written\n"


def test_run_text_extraction_job_writes_markdown_and_updates_state(tmp_path: Path) -> None:
    store = ContentIngestionStore()
    config = storage_config(tmp_path)
    document = build_upload_registration(
        {
            "filename": "source.txt",
            "content_type": "text/plain",
            "content_text": "hello extraction",
        },
        storage_config=config,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    store.save_upload_registration(document, source_text="hello extraction")

    result = run_text_extraction_job(
        document["extraction"]["job_id"],
        store=store,
        storage_config=config,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    markdown_path = Path(result["extracted_markdown_path"])
    assert result["extraction_schema_version"] == "cx_text_extraction.v1"
    assert result["status"] == "SUCCEEDED"
    assert result["markdown_preview"] == "# source.txt\n\nhello extraction\n"
    assert result["extracted_markdown_sha256"] == sha256_text(markdown_path.read_text())
    assert store.get_job(result["job_id"])["status"] == "SUCCEEDED"
    assert store.get_document(result["document_id"])["extraction"]["markdown_available"] is True
    assert store.get_extraction_result(result["document_id"]) == result


def test_run_text_extraction_job_reports_unknown_job(tmp_path: Path) -> None:
    with pytest.raises(IngestionError) as exc:
        run_text_extraction_job(
            "missing",
            store=ContentIngestionStore(),
            storage_config=storage_config(tmp_path),
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert exc.value.error_code == "cx.ingestion_job_not_found"


def test_run_text_extraction_job_reports_missing_document(tmp_path: Path) -> None:
    store = ContentIngestionStore()
    job = build_ingestion_job(
        document_id="missing-doc",
        upload_id="upload-001",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        created_at="2026-08-02T00:00:00Z",
    )
    store.jobs[job["job_id"]] = job

    with pytest.raises(IngestionError) as exc:
        run_text_extraction_job(
            job["job_id"],
            store=store,
            storage_config=storage_config(tmp_path),
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert exc.value.error_code == "cx.document_not_found"


def test_run_text_extraction_job_reports_missing_source_text(tmp_path: Path) -> None:
    store = ContentIngestionStore()
    config = storage_config(tmp_path)
    document = build_upload_registration(
        {"filename": "source.pdf", "source_sha256": "a" * 64, "size_bytes": 10},
        storage_config=config,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    store.save_upload_registration(document)

    with pytest.raises(IngestionError) as exc:
        run_text_extraction_job(
            document["extraction"]["job_id"],
            store=store,
            storage_config=config,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert exc.value.status_code == 409
    assert exc.value.error_code == "cx.source_content_unavailable"


def test_store_save_extraction_result_requires_existing_state() -> None:
    with pytest.raises(IngestionError) as exc:
        ContentIngestionStore().save_extraction_result(
            {
                "document_id": "missing-doc",
                "job_id": "missing-job",
                "updated_at": "2026-08-02T00:00:00Z",
            }
        )

    assert exc.value.error_code == "cx.ingestion_state_not_found"


def test_upload_registration_endpoint_returns_problem_for_bad_filename(
    tmp_path: Path,
) -> None:
    client, _ = build_test_client(tmp_path)

    response = client.post(
        "/api/v1/documents/uploads",
        json={"filename": "../source.md", "content_text": "hello"},
        headers=auth_headers(),
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "cx.upload_filename_invalid"


def test_document_and_job_can_be_read_back(tmp_path: Path) -> None:
    client, _ = build_test_client(tmp_path)
    created = client.post(
        "/api/v1/documents/uploads",
        json={"filename": "source.md", "content_text": "hello"},
        headers=auth_headers(),
    ).json()

    document_response = client.get(
        f"/api/v1/documents/{created['document_id']}",
        headers=auth_headers(),
    )
    job_response = client.get(
        f"/api/v1/jobs/{created['extraction']['job_id']}",
        headers=auth_headers(),
    )

    assert document_response.status_code == 200
    assert document_response.json()["document_id"] == created["document_id"]
    assert job_response.status_code == 200
    assert job_response.json()["job_id"] == created["extraction"]["job_id"]


def test_run_job_endpoint_materializes_markdown_and_extraction_readback(
    tmp_path: Path,
) -> None:
    client, _ = build_test_client(tmp_path)
    created = client.post(
        "/api/v1/documents/uploads",
        json={
            "filename": "source.txt",
            "content_type": "text/plain",
            "content_text": "hello endpoint",
        },
        headers=auth_headers(),
    ).json()

    run_response = client.post(
        f"/api/v1/jobs/{created['extraction']['job_id']}/run",
        headers=auth_headers(),
    )
    read_response = client.get(
        f"/api/v1/documents/{created['document_id']}/extraction",
        headers=auth_headers(),
    )

    assert run_response.status_code == 200
    result = run_response.json()
    assert Path(result["extracted_markdown_path"]).read_text(encoding="utf-8") == (
        "# source.txt\n\nhello endpoint\n"
    )
    assert read_response.status_code == 200
    assert read_response.json()["extracted_markdown_sha256"] == result["extracted_markdown_sha256"]


def test_run_job_endpoint_requires_service_claim(tmp_path: Path) -> None:
    client, _ = build_test_client(tmp_path)

    response = client.post("/api/v1/jobs/missing/run")

    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"


def test_extraction_read_requires_service_claim(tmp_path: Path) -> None:
    client, _ = build_test_client(tmp_path)

    response = client.get("/api/v1/documents/missing/extraction")

    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"


def test_run_job_endpoint_reports_missing_source_content(tmp_path: Path) -> None:
    client, _ = build_test_client(tmp_path)
    created = client.post(
        "/api/v1/documents/uploads",
        json={
            "filename": "source.pdf",
            "content_type": "application/pdf",
            "source_sha256": "a" * 64,
            "size_bytes": 10,
        },
        headers=auth_headers(),
    ).json()

    response = client.post(
        f"/api/v1/jobs/{created['extraction']['job_id']}/run",
        headers=auth_headers(),
    )

    assert response.status_code == 409
    assert response.json()["error_code"] == "cx.source_content_unavailable"


def test_extraction_read_reports_not_found(tmp_path: Path) -> None:
    client, _ = build_test_client(tmp_path)

    response = client.get(
        "/api/v1/documents/missing/extraction",
        headers=auth_headers(),
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "cx.extraction_result_not_found"


def test_document_read_requires_service_claim(tmp_path: Path) -> None:
    client, _ = build_test_client(tmp_path)

    response = client.get("/api/v1/documents/missing")

    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"


def test_job_read_requires_service_claim(tmp_path: Path) -> None:
    client, _ = build_test_client(tmp_path)

    response = client.get("/api/v1/jobs/missing")

    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"


def test_document_and_job_reads_return_not_found(tmp_path: Path) -> None:
    client, _ = build_test_client(tmp_path)

    document_response = client.get("/api/v1/documents/missing", headers=auth_headers())
    job_response = client.get("/api/v1/jobs/missing", headers=auth_headers())

    assert document_response.status_code == 404
    assert document_response.json()["error_code"] == "cx.document_not_found"
    assert job_response.status_code == 404
    assert job_response.json()["error_code"] == "cx.ingestion_job_not_found"
