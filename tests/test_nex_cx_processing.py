from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
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
    PROCESSING_EVENT_FAILED,
    PROCESSING_EVENT_STARTED,
    PROCESSING_EVENT_SUCCEEDED,
    ProcessingPipelineError,
    _enqueue_or_resume_processing_job,
    _failed_step_id,
    _safe_emit_processing_event,
    _safe_fail_job,
    build_pipeline_run_record,
    build_processing_job,
    extraction_job_id_for_document,
    output_ref_for_step,
    processing_event_id,
    processing_job_snapshot,
    register_processing_routes,
    run_document_processing_pipeline,
    safe_error_from_exception,
)
from nex_runtime import (
    InMemoryJobQueue,
    InMemoryOperationalEventStore,
    OperationalEventEmitter,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
)
from nex_runtime.jobs import JobQueueError

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"
NOW = "2026-08-05T00:00:00Z"


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
    *,
    job_queue: InMemoryJobQueue | None = None,
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
        job_queue=job_queue,
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
    job_queue = InMemoryJobQueue()
    document = save_source_document(store, tmp_path)

    run = run_document_processing_pipeline(
        document["document_id"],
        store=store,
        storage_config=storage_config(tmp_path),
        mo_client=mo_client,
        embedding_alias="mock-embedding-default",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        job_queue=job_queue,
    )

    assert run["pipeline_schema_version"] == "cx_document_processing_pipeline.v1"
    assert run["status"] == "SUCCEEDED"
    assert run["job"]["job_type"] == "cx.document_processing"
    assert run["job"]["status"] == "SUCCEEDED"
    assert run["job"]["attempt_count"] == 1
    assert job_queue.get_job(run["job"]["job_id"])["status"] == "SUCCEEDED"
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


def test_run_document_processing_pipeline_emits_started_and_succeeded_events(
    tmp_path: Path,
) -> None:
    store = ContentIngestionStore()
    mo_client = FakeMoEmbeddingClient()
    job_queue = InMemoryJobQueue()
    event_store = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id="nex-cx", store=event_store)
    document = save_source_document(store, tmp_path)

    run = run_document_processing_pipeline(
        document["document_id"],
        store=store,
        storage_config=storage_config(tmp_path),
        mo_client=mo_client,
        embedding_alias="mock-embedding-default",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        job_queue=job_queue,
        event_emitter=emitter,
    )

    events = event_store.list_events(trace_id=TRACE_ID, limit=10)
    event_types = [event["event_type"] for event in events]

    assert event_types == [PROCESSING_EVENT_SUCCEEDED, PROCESSING_EVENT_STARTED]
    assert events[0]["subject_ref"] == {
        "type": "cx.document",
        "id": document["document_id"],
    }
    assert events[0]["details"] == {
        "pipeline_run_id": run["pipeline_run_id"],
        "job_id": run["job"]["job_id"],
        "job_status": "SUCCEEDED",
        "step_summary": {"total": 6, "succeeded": 6, "skipped": 0, "failed": 0},
    }
    assert events[1]["details"] == {
        "pipeline_run_id": run["pipeline_run_id"],
        "job_id": run["job"]["job_id"],
        "job_status": "RUNNING",
    }
    assert "Pipeline source text" not in str(events)


def test_run_document_processing_pipeline_emits_failed_event(
    tmp_path: Path,
) -> None:
    store = ContentIngestionStore()
    job_queue = InMemoryJobQueue()
    event_store = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id="nex-cx", store=event_store)
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

    try:
        run_document_processing_pipeline(
            metadata_only["document_id"],
            store=store,
            storage_config=storage_config(tmp_path),
            mo_client=FakeMoEmbeddingClient(),
            embedding_alias="mock-embedding-default",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
            job_queue=job_queue,
            event_emitter=emitter,
        )
    except ProcessingPipelineError as exc:
        failed_run = exc.pipeline_run
    else:
        raise AssertionError("expected pipeline failure")

    assert failed_run is not None
    events = event_store.list_events(trace_id=TRACE_ID, limit=10)
    assert [event["event_type"] for event in events] == [
        PROCESSING_EVENT_FAILED,
        PROCESSING_EVENT_STARTED,
    ]
    assert events[0]["severity"] == "ERROR"
    assert events[0]["details"] == {
        "pipeline_run_id": failed_run["pipeline_run_id"],
        "job_id": failed_run["job"]["job_id"],
        "job_status": "FAILED",
        "step_summary": {"total": 1, "succeeded": 0, "skipped": 0, "failed": 1},
        "failed_step": "extraction",
    }


def test_run_document_processing_pipeline_isolates_operational_event_failures(
    tmp_path: Path,
) -> None:
    class ExplodingStore:
        def append(self, event: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("event store is unavailable")

        def get_event(self, event_id: str) -> dict[str, Any] | None:
            return None

        def list_events(self, **kwargs: Any) -> list[dict[str, Any]]:
            return []

    store = ContentIngestionStore()
    mo_client = FakeMoEmbeddingClient()
    document = save_source_document(store, tmp_path)
    emitter = OperationalEventEmitter(service_id="nex-cx", store=ExplodingStore())

    run = run_document_processing_pipeline(
        document["document_id"],
        store=store,
        storage_config=storage_config(tmp_path),
        mo_client=mo_client,
        embedding_alias="mock-embedding-default",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        event_emitter=emitter,
    )

    assert run["status"] == "SUCCEEDED"
    assert len(mo_client.calls) == 2


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


def test_run_document_processing_pipeline_reuses_terminal_job_for_same_request(
    tmp_path: Path,
) -> None:
    store = ContentIngestionStore()
    mo_client = FakeMoEmbeddingClient()
    job_queue = InMemoryJobQueue()
    document = save_source_document(store, tmp_path)
    first = run_document_processing_pipeline(
        document["document_id"],
        store=store,
        storage_config=storage_config(tmp_path),
        mo_client=mo_client,
        embedding_alias="mock-embedding-default",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        job_queue=job_queue,
    )

    second = run_document_processing_pipeline(
        document["document_id"],
        store=store,
        storage_config=storage_config(tmp_path),
        mo_client=mo_client,
        embedding_alias="mock-embedding-default",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        job_queue=job_queue,
    )

    assert second == first
    assert len(mo_client.calls) == 2
    assert job_queue.summary()["statuses"]["SUCCEEDED"] == 1


def test_processing_job_resume_handles_running_and_orphaned_terminal_jobs(
    tmp_path: Path,
) -> None:
    store = ContentIngestionStore()
    queue = InMemoryJobQueue()
    pipeline_run_id = "run-001"
    job = build_processing_job(
        document_id="doc-001",
        pipeline_run_id=pipeline_run_id,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        created_at=NOW,
    )
    queue.enqueue(job)
    running = queue.start_job(job["job_id"])

    resumed, existing_run = _enqueue_or_resume_processing_job(
        queue,
        document_id="doc-001",
        pipeline_run_id=pipeline_run_id,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        created_at=NOW,
        store=store,
    )
    assert resumed == running
    assert existing_run is None

    queue.complete_job(job["job_id"])
    try:
        _enqueue_or_resume_processing_job(
            queue,
            document_id="doc-001",
            pipeline_run_id=pipeline_run_id,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
            created_at=NOW,
            store=store,
        )
    except ProcessingPipelineError as exc:
        assert exc.error_code == "cx.processing_job_terminal"
    else:
        raise AssertionError("expected terminal job error without stored pipeline run")


def test_safe_fail_job_returns_current_snapshot_when_transition_fails() -> None:
    class FailingQueue:
        def fail_job(self, job_id: str):
            raise JobQueueError("job.transition_invalid", "cannot fail")

        def get_job(self, job_id: str):
            return {"job_id": job_id, "status": "SUCCEEDED"}

    assert _safe_fail_job(FailingQueue(), "job-001") == {
        "job_id": "job-001",
        "status": "SUCCEEDED",
    }


def test_run_document_processing_pipeline_records_failed_step(
    tmp_path: Path,
) -> None:
    store = ContentIngestionStore()
    job_queue = InMemoryJobQueue()
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
            job_queue=job_queue,
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
    assert failed["job"]["status"] == "FAILED"
    assert job_queue.get_job(failed["job"]["job_id"])["status"] == "FAILED"
    assert failed["step_summary"] == {"total": 1, "succeeded": 0, "skipped": 0, "failed": 1}
    assert store.get_latest_document_processing_run(metadata_only["document_id"]) == failed


def test_processing_routes_run_and_read_latest_pipeline(tmp_path: Path) -> None:
    job_queue = InMemoryJobQueue()
    client, store, mo_client = build_test_client(tmp_path, job_queue=job_queue)
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
    assert latest.json()["job"]["status"] == "SUCCEEDED"
    assert job_queue.summary()["statuses"]["SUCCEEDED"] == 1
    assert store.get_latest_document_processing_run(uploaded["document_id"]) == response.json()
    assert len(mo_client.calls) == 2


def test_processing_route_emits_events_to_app_persistence_store(tmp_path: Path) -> None:
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    store = ContentIngestionStore()
    mo_client = FakeMoEmbeddingClient()
    config = storage_config(tmp_path)
    event_store = InMemoryOperationalEventStore()
    app.state.nex_persistence = SimpleNamespace(operational_event_store=event_store)
    register_ingestion_routes(app, store=store, storage_config=config)
    register_processing_routes(
        app,
        store=store,
        storage_config=config,
        mo_client=mo_client,
        embedding_alias="mock-embedding-default",
    )
    client = TestClient(app)
    uploaded = client.post(
        "/api/v1/documents/uploads",
        json={
            "filename": "source.txt",
            "content_type": "text/plain",
            "content_text": "route event text",
        },
        headers=auth_headers(),
    ).json()

    response = client.post(
        f"/api/v1/documents/{uploaded['document_id']}/processing/run",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    events = event_store.list_events(trace_id=TRACE_ID, limit=10)
    assert [event["event_type"] for event in events] == [
        PROCESSING_EVENT_SUCCEEDED,
        PROCESSING_EVENT_STARTED,
    ]
    assert events[0]["details"]["pipeline_run_id"] == response.json()["pipeline_run_id"]


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
    assert response.json()["details"]["job_status"] == "FAILED"
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
    job = build_processing_job(
        document_id="doc-1",
        pipeline_run_id="run-1",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        created_at="2026-08-04T00:00:00Z",
    )
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
        job={**job, "status": "SUCCEEDED", "attempt_count": 1},
    )
    run_without_job = build_pipeline_run_record(
        document_id="doc-1",
        pipeline_run_id="run-2",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        started_at="2026-08-04T00:00:00Z",
        steps=[],
        status="SUCCEEDED",
    )

    assert summary_ref == {
        "type": "cx.document_summary",
        "id": "summary-1",
        "document_id": "doc-1",
    }
    assert run["step_summary"] == {"total": 1, "succeeded": 0, "skipped": 1, "failed": 0}
    assert run["job"] == processing_job_snapshot(
        {**job, "status": "SUCCEEDED", "attempt_count": 1}
    )
    assert run["job"]["links"]["processing"] == "/api/v1/documents/doc-1/processing"
    assert "job" not in run_without_job
    assert _failed_step_id(run_without_job["steps"]) is None
    assert safe_error_from_exception(ValueError("boom")) == {
        "error_code": "cx.processing_step_failed",
        "detail": "Document processing step failed.",
        "retryable": False,
    }


def test_processing_event_helpers_build_stable_safe_events() -> None:
    event_store = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id="nex-cx", store=event_store)

    skipped_result = _safe_emit_processing_event(
        None,
        event_type=PROCESSING_EVENT_STARTED,
        severity="INFO",
        message="CX document processing started.",
        document_id="doc-1",
        pipeline_run_id="run-1",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    result = _safe_emit_processing_event(
        emitter,
        event_type=PROCESSING_EVENT_STARTED,
        severity="INFO",
        message="CX document processing started.",
        document_id="doc-1",
        pipeline_run_id="run-1",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        created_at=NOW,
    )

    assert skipped_result is None
    assert result is not None
    assert result.ok is True
    assert result.event is not None
    assert result.event["event_id"] == processing_event_id(
        pipeline_run_id="run-1",
        event_type=PROCESSING_EVENT_STARTED,
    )
    assert result.event["subject_ref"] == {"type": "cx.document", "id": "doc-1"}
    assert result.event["details"] == {"pipeline_run_id": "run-1"}


def test_extraction_job_id_for_document_reports_missing_document() -> None:
    try:
        extraction_job_id_for_document(ContentIngestionStore(), "missing")
    except Exception as exc:
        assert getattr(exc, "error_code") == "cx.document_not_found"
    else:
        raise AssertionError("expected missing document error")
