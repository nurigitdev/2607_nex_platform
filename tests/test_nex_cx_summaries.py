from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nex_cx.ingestion import (
    ContentIngestionStore,
    CxStorageConfig,
    build_upload_registration,
    register_ingestion_routes,
    run_text_extraction_job,
    sha256_text,
)
from nex_cx.summaries import (
    DEFAULT_SUMMARY_HARD_LIMIT_CHARS,
    DEFAULT_SUMMARY_MAX_CHARS,
    SummaryError,
    build_and_store_document_summary,
    build_document_summary_record,
    normalize_markdown_for_summary,
    register_summary_routes,
    summarize_markdown_text,
    trim_to_limit,
    validate_summary_limits,
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


def build_store_with_extraction(
    tmp_path: Path,
    *,
    text: str = "# Source\n\nThis document explains traceable retrieval and generation.",
) -> tuple[ContentIngestionStore, dict[str, object]]:
    store = ContentIngestionStore()
    config = storage_config(tmp_path)
    document = build_upload_registration(
        {
            "filename": "source.md",
            "content_type": "text/markdown",
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
    return store, extraction


def build_test_client(tmp_path: Path) -> tuple[TestClient, ContentIngestionStore]:
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    store = ContentIngestionStore()
    config = storage_config(tmp_path)
    register_ingestion_routes(app, store=store, storage_config=config)
    register_summary_routes(app, store=store)
    return TestClient(app), store


def test_normalize_markdown_for_summary_removes_heading_markup() -> None:
    assert normalize_markdown_for_summary("# Title\n\nBody line\n\n## Detail") == (
        "Title Body line Detail"
    )


def test_summarize_markdown_text_keeps_summary_under_default_chunk_limit() -> None:
    text = "# Title\n\n" + "important detail " * 120

    summary = summarize_markdown_text(text)

    assert len(summary) <= DEFAULT_SUMMARY_MAX_CHARS
    assert len(summary) <= DEFAULT_SUMMARY_HARD_LIMIT_CHARS
    assert summary.endswith("...")


def test_summarize_markdown_text_handles_blank_markdown() -> None:
    assert summarize_markdown_text(" \n ") == (
        "No extractable text was available for this document."
    )


def test_trim_to_limit_handles_tiny_limits() -> None:
    assert trim_to_limit("abcdef", 3) == "abc"
    assert trim_to_limit("abcdef", 5) == "ab..."


@pytest.mark.parametrize(
    ("max_chars", "hard_limit_chars", "detail"),
    [
        (0, 1000, "positive"),
        (900, 1001, "between 1 and 1000"),
        (901, 900, "must not exceed"),
    ],
)
def test_validate_summary_limits_rejects_invalid_policy(
    max_chars: int,
    hard_limit_chars: int,
    detail: str,
) -> None:
    with pytest.raises(SummaryError) as exc:
        validate_summary_limits(max_chars=max_chars, hard_limit_chars=hard_limit_chars)

    assert exc.value.error_code == "cx.summary_policy_invalid"
    assert detail in exc.value.detail


def test_build_document_summary_record_rejects_hard_limit_overflow() -> None:
    with pytest.raises(SummaryError) as exc:
        build_document_summary_record(
            document_id="doc-001",
            extraction={
                "job_id": "job-001",
                "extracted_markdown_sha256": "a" * 64,
            },
            summary_text="x" * 1001,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
            max_chars=1000,
            hard_limit_chars=1000,
        )

    assert exc.value.status_code == 502
    assert exc.value.retryable is True
    assert exc.value.error_code == "cx.summary_hard_limit_exceeded"


def test_build_and_store_document_summary_saves_private_text(tmp_path: Path) -> None:
    store, extraction = build_store_with_extraction(tmp_path)

    record = build_and_store_document_summary(
        extraction["document_id"],
        store=store,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    private_text = store.get_summary_text(record["document_summary_id"])
    assert record["document_summary_schema_version"] == "cx_document_summary.v1"
    assert record["summary_chunk_policy_id"] == "summary_1000_0"
    assert record["summary_char_count"] <= 1000
    assert record["summary_text_sha256"] == sha256_text(private_text)
    assert store.get_document_summary(extraction["document_id"]) == record
    assert "traceable retrieval" not in str(record["summary_text_sha256"])


def test_build_and_store_document_summary_reports_missing_extraction() -> None:
    with pytest.raises(SummaryError) as exc:
        build_and_store_document_summary(
            "missing-doc",
            store=ContentIngestionStore(),
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert exc.value.error_code == "cx.extraction_result_not_found"


def test_build_and_store_document_summary_reports_missing_markdown_file(
    tmp_path: Path,
) -> None:
    store, extraction = build_store_with_extraction(tmp_path)
    Path(extraction["extracted_markdown_path"]).unlink()

    with pytest.raises(SummaryError) as exc:
        build_and_store_document_summary(
            extraction["document_id"],
            store=store,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert exc.value.status_code == 409
    assert exc.value.retryable is True
    assert exc.value.error_code == "cx.extracted_markdown_missing"


def test_summary_endpoint_materializes_and_reads_summary(tmp_path: Path) -> None:
    client, store = build_test_client(tmp_path)
    created = client.post(
        "/api/v1/documents/uploads",
        json={
            "filename": "source.md",
            "content_type": "text/markdown",
            "content_text": "# Source\n\nImportant summary material.",
        },
        headers=auth_headers(),
    ).json()
    client.post(f"/api/v1/jobs/{created['extraction']['job_id']}/run", headers=auth_headers())

    run_response = client.post(
        f"/api/v1/documents/{created['document_id']}/summary/run",
        headers=auth_headers(),
    )
    read_response = client.get(
        f"/api/v1/documents/{created['document_id']}/summary",
        headers=auth_headers(),
    )

    assert run_response.status_code == 200
    summary = run_response.json()
    assert summary["summary_preview"] == "Source Important summary material."
    assert store.get_summary_text(summary["document_summary_id"]) == (
        "Source Important summary material."
    )
    assert read_response.status_code == 200
    assert read_response.json()["summary_text_sha256"] == summary["summary_text_sha256"]


def test_summary_endpoints_require_service_claim(tmp_path: Path) -> None:
    client, _ = build_test_client(tmp_path)

    run_response = client.post("/api/v1/documents/missing/summary/run")
    read_response = client.get("/api/v1/documents/missing/summary")

    assert run_response.status_code == 401
    assert read_response.status_code == 401
    assert run_response.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"


def test_summary_endpoint_reports_not_found(tmp_path: Path) -> None:
    client, _ = build_test_client(tmp_path)

    run_response = client.post(
        "/api/v1/documents/missing/summary/run",
        headers=auth_headers(),
    )
    read_response = client.get(
        "/api/v1/documents/missing/summary",
        headers=auth_headers(),
    )

    assert run_response.status_code == 404
    assert run_response.json()["error_code"] == "cx.extraction_result_not_found"
    assert read_response.status_code == 404
    assert read_response.json()["error_code"] == "cx.document_summary_not_found"
