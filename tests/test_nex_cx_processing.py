from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from nex_cx.ingestion import (
    ContentIngestionStore,
    CxStorageConfig,
    build_upload_registration,
    register_ingestion_routes,
    sha256_text,
)
from nex_cx.processing import (
    ProcessingPipelineError,
    build_pipeline_run_record,
    extraction_job_id_for_document,
    output_ref_for_step,
    register_processing_routes,
    run_document_processing_pipeline,
    safe_error_from_exception,
)
from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


class FakeMoEmbeddingClient:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def create_embeddings(
        self,
        inputs: list[str],
        *,
        alias: str,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        self.calls.append(inputs)
        return {
            "object": "list",
            "alias": alias,
            "model_revision": "mock-embedding-v1",
            "deployment_id": "mock-embedding-local",
            "data": [
                {"object": "embedding", "index": index, "embedding": [0.1, 0.2, 0.3]}
                for index, _ in enumerate(inputs)
            ],
            "usage": {
                "input_tokens": len(inputs),
                "output_tokens": 0,
                "total_tokens": len(inputs),
            },
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


def auth_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-ae-api", audience="nex-cx")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def build_test_client(
    tmp_path: Path,
) -> tuple[TestClient, ContentIngestionStore, FakeMoEmbeddingClient]:
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    store = ContentIngestionStore()
    mo_client = FakeMoEmbeddingClient()
    config = storage_config(tmp_path)
    register_ingestion_routes(app, store=store, storage_config=config)
    register_processing_routes(
        app,
        store=store,
        storage_config=config,
        mo_client=mo_client,
        embedding_alias="mock-embedding-default",
    )
    return TestClient(app), store, mo_client


def save_source_document(
    store: ContentIngestionStore,
    tmp_path: Path,
    *,
    text: str = "Pipeline source text for retrieval and summary.",
) -> dict[str, Any]:
    document = build_upload_registration(
        {
            "filename": "source.txt",
            "content_type": "text/plain",
            "content_text": text,
        },
        storage_config=storage_config(tmp_path),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    return store.save_upload_registration(document, source_text=text)


def test_run_document_processing_pipeline_builds_all_indexes_and_summaries(
    tmp_path: Path,
) -> None:
    store = ContentIngestionStore()
    mo_client = FakeMoEmbeddingClient()
    document = save_source_document(store, tmp_path)

    run = run_document_processing_pipeline(
        document["document_id"],
        store=store,
        storage_config=storage_config(tmp_path),
        mo_client=mo_client,
        embedding_alias="mock-embedding-default",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert run["pipeline_schema_version"] == "cx_document_processing_pipeline.v1"
    assert run["status"] == "SUCCEEDED"
    assert [step["status"] for step in run["steps"]] == ["SUCCEEDED"] * 6
    assert run["step_summary"] == {"total": 6, "succeeded": 6, "skipped": 0, "failed": 0}
    assert store.get_extraction_result(document["document_id"]) is not None
    assert store.get_chunk_set(document["document_id"]) is not None
    assert store.get_lexical_index(document["document_id"]) is not None
    assert store.get_embedding_index(document["document_id"]) is not None
    assert store.get_document_summary(document["document_id"]) is not None
    assert store.get_summary_embedding_index(document["document_id"]) is not None
    assert len(mo_client.calls) == 2
    assert "Pipeline source text" not in str(run)


def test_run_document_processing_pipeline_is_idempotent_for_existing_outputs(
    tmp_path: Path,
) -> None:
    store = ContentIngestionStore()
    mo_client = FakeMoEmbeddingClient()
    document = save_source_document(store, tmp_path)
    run_document_processing_pipeline(
        document["document_id"],
        store=store,
        storage_config=storage_config(tmp_path),
        mo_client=mo_client,
        embedding_alias="mock-embedding-default",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    second = run_document_processing_pipeline(
        document["document_id"],
        store=store,
        storage_config=storage_config(tmp_path),
        mo_client=mo_client,
        embedding_alias="mock-embedding-default",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert [step["status"] for step in second["steps"]] == ["SKIPPED"] * 6
    assert second["step_summary"] == {"total": 6, "succeeded": 0, "skipped": 6, "failed": 0}
    assert len(mo_client.calls) == 2


def test_run_document_processing_pipeline_records_failed_step(
    tmp_path: Path,
) -> None:
    store = ContentIngestionStore()
    metadata_only = build_upload_registration(
        {
            "filename": "source.pdf",
            "source_sha256": "a" * 64,
            "size_bytes": 10,
        },
        storage_config=storage_config(tmp_path),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    store.save_upload_registration(metadata_only)
    error: ProcessingPipelineError | None = None

    try:
        run_document_processing_pipeline(
            metadata_only["document_id"],
            store=store,
            storage_config=storage_config(tmp_path),
            mo_client=FakeMoEmbeddingClient(),
            embedding_alias="mock-embedding-default",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    except ProcessingPipelineError as exc:
        error = exc
        failed = exc.pipeline_run
    else:
        raise AssertionError("expected pipeline failure")

    assert error is not None
    assert error.status_code == 409
    assert error.error_code == "cx.source_content_unavailable"
    assert error.failed_step == "extraction"
    assert failed is not None
    assert failed["status"] == "FAILED"
    assert failed["step_summary"] == {"total": 1, "succeeded": 0, "skipped": 0, "failed": 1}
    assert store.get_latest_document_processing_run(metadata_only["document_id"]) == failed


def test_processing_routes_run_and_read_latest_pipeline(tmp_path: Path) -> None:
    client, store, mo_client = build_test_client(tmp_path)
    uploaded = client.post(
        "/api/v1/documents/uploads",
        json={
            "filename": "source.txt",
            "content_type": "text/plain",
            "content_text": "route pipeline text",
        },
        headers=auth_headers(),
    ).json()

    response = client.post(
        f"/api/v1/documents/{uploaded['document_id']}/processing/run",
        headers=auth_headers(),
    )
    latest = client.get(
        f"/api/v1/documents/{uploaded['document_id']}/processing",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert latest.status_code == 200
    assert latest.json()["pipeline_run_id"] == response.json()["pipeline_run_id"]
    assert store.get_latest_document_processing_run(uploaded["document_id"]) == response.json()
    assert len(mo_client.calls) == 2


def test_processing_routes_require_service_claim(tmp_path: Path) -> None:
    client, _, _ = build_test_client(tmp_path)

    run_response = client.post("/api/v1/documents/missing/processing/run")
    read_response = client.get("/api/v1/documents/missing/processing")

    assert run_response.status_code == 401
    assert read_response.status_code == 401
    assert run_response.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"


def test_processing_route_problem_includes_safe_pipeline_details(tmp_path: Path) -> None:
    client, _, _ = build_test_client(tmp_path)

    response = client.post(
        "/api/v1/documents/missing/processing/run",
        headers=auth_headers(),
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "cx.document_not_found"
    assert response.json()["details"]["failed_step"] == "extraction"
    assert response.json()["details"]["step_summary"] == {
        "total": 1,
        "succeeded": 0,
        "skipped": 0,
        "failed": 1,
    }


def test_processing_read_reports_not_found(tmp_path: Path) -> None:
    client, _, _ = build_test_client(tmp_path)

    response = client.get("/api/v1/documents/missing/processing", headers=auth_headers())

    assert response.status_code == 404
    assert response.json()["error_code"] == "cx.processing_run_not_found"


def test_processing_helpers_return_safe_metadata() -> None:
    summary_ref = output_ref_for_step(
        "summary",
        {
            "document_id": "doc-1",
            "document_summary_id": "summary-1",
            "summary_text_sha256": sha256_text("private summary"),
        },
    )
    run = build_pipeline_run_record(
        document_id="doc-1",
        pipeline_run_id="run-1",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        started_at="2026-08-04T00:00:00Z",
        steps=[
            {"step_id": "summary", "status": "SKIPPED", "output_ref": summary_ref, "error": None}
        ],
        status="SUCCEEDED",
    )

    assert summary_ref == {
        "type": "cx.document_summary",
        "id": "summary-1",
        "document_id": "doc-1",
    }
    assert run["step_summary"] == {"total": 1, "succeeded": 0, "skipped": 1, "failed": 0}
    assert safe_error_from_exception(ValueError("boom")) == {
        "error_code": "cx.processing_step_failed",
        "detail": "Document processing step failed.",
        "retryable": False,
    }


def test_extraction_job_id_for_document_reports_missing_document() -> None:
    try:
        extraction_job_id_for_document(ContentIngestionStore(), "missing")
    except Exception as exc:
        assert getattr(exc, "error_code") == "cx.document_not_found"
    else:
        raise AssertionError("expected missing document error")
