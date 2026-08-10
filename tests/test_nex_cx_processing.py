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
    CX_PROCESSING_BACKGROUND_WORKER_ID,
    CX_PROCESSING_WORKER_ID,
    CX_PROCESSING_WORKER_TYPE,
    PROCESSING_EVENT_FAILED,
    PROCESSING_EVENT_STARTED,
    PROCESSING_EVENT_SUCCEEDED,
    PROCESSING_WORKER_EVENT_BUSY,
    PROCESSING_WORKER_EVENT_ERROR,
    PROCESSING_WORKER_EVENT_IDLE,
    ProcessingPipelineError,
    _enqueue_or_resume_processing_job,
    _failed_step_id,
    _processing_run_repository_from_request,
    _safe_emit_processing_event,
    _safe_emit_processing_worker_heartbeat,
    _safe_emit_processing_worker_lifecycle_event,
    _safe_fail_job,
    build_pipeline_run_record,
    build_queued_pipeline_run_record,
    build_processing_job,
    enqueue_document_processing_pipeline,
    extraction_job_id_for_document,
    output_ref_for_step,
    processing_event_id,
    processing_worker_event_id,
    processing_job_snapshot,
    register_processing_routes,
    run_cx_document_processing_worker_once,
    run_document_processing_pipeline,
    safe_error_from_exception,
)
from nex_cx.repository import (
    CxContentRepository,
    CxContentRepositoryError,
    InMemoryCxContentRepository,
    SqlAlchemyCxContentRepository,
    build_processing_run_persistence_record,
)
from nex_runtime import (
    BUSY,
    ERROR,
    IDLE,
    InMemoryJobQueue,
    InMemoryOperationalEventStore,
    InMemoryWorkerHeartbeatStore,
    OperationalEventEmitter,
    PERSISTENCE_MODE_POSTGRES,
    SERVICE_SPECS,
    WorkerHeartbeatEmitter,
    WorkerHeartbeatEmitResult,
    build_service_app,
    issue_mock_service_token,
)
from nex_runtime.jobs import JobQueueError

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"
NOW = "2026-08-05T00:00:00Z"
LATER = "2026-08-05T00:00:30Z"


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


class ExplodingWorkerHeartbeatStore:
    def upsert_heartbeat(self, heartbeat: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("worker heartbeat store unavailable")

    def get_heartbeat(self, service_id: str, worker_id: str) -> dict[str, Any] | None:
        return None

    def list_heartbeats(self, **kwargs: Any) -> list[dict[str, Any]]:
        return []


class UnavailableProcessingRunRepository:
    def get_latest_processing_run_record(self, document_id: str) -> dict[str, Any] | None:
        raise CxContentRepositoryError(
            error_code="cx_content.repository_unavailable",
            detail=f"Processing run repository unavailable for: {document_id}",
            status_code=503,
        )


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
    processing_run_repository: CxContentRepository | None = None,
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
        processing_run_repository=processing_run_repository,
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


def event_by_type(events: list[dict[str, Any]], event_type: str) -> dict[str, Any]:
    return next(event for event in events if event["event_type"] == event_type)


def processing_event_types(events: list[dict[str, Any]]) -> set[str]:
    return {
        event["event_type"]
        for event in events
        if event["event_type"]
        in {PROCESSING_EVENT_STARTED, PROCESSING_EVENT_SUCCEEDED, PROCESSING_EVENT_FAILED}
    }


def worker_event_types(events: list[dict[str, Any]]) -> set[str]:
    return {
        event["event_type"]
        for event in events
        if event["event_type"]
        in {PROCESSING_WORKER_EVENT_BUSY, PROCESSING_WORKER_EVENT_IDLE, PROCESSING_WORKER_EVENT_ERROR}
    }


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


def test_enqueue_document_processing_pipeline_queues_without_running_steps(
    tmp_path: Path,
) -> None:
    store = ContentIngestionStore()
    job_queue = InMemoryJobQueue()
    document = save_source_document(store, tmp_path)

    queued = enqueue_document_processing_pipeline(
        document["document_id"],
        store=store,
        job_queue=job_queue,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        created_at=NOW,
    )
    duplicate = enqueue_document_processing_pipeline(
        document["document_id"],
        store=store,
        job_queue=job_queue,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        created_at=LATER,
    )

    assert duplicate == queued
    assert queued["status"] == "QUEUED"
    assert queued["queued_at"] == NOW
    assert queued["started_at"] is None
    assert queued["completed_at"] is None
    assert queued["steps"] == []
    assert queued["step_summary"] == {"total": 0, "succeeded": 0, "skipped": 0, "failed": 0}
    assert queued["job"]["status"] == "QUEUED"
    assert job_queue.get_job(queued["job"]["job_id"])["status"] == "QUEUED"
    assert store.get_latest_document_processing_run(document["document_id"]) == queued


def test_cx_document_processing_worker_claims_queued_job_and_runs_pipeline(
    tmp_path: Path,
) -> None:
    store = ContentIngestionStore()
    mo_client = FakeMoEmbeddingClient()
    job_queue = InMemoryJobQueue()
    heartbeat_store = InMemoryWorkerHeartbeatStore()
    heartbeat_emitter = WorkerHeartbeatEmitter(
        service_id="nex-cx",
        worker_id=CX_PROCESSING_BACKGROUND_WORKER_ID,
        worker_type=CX_PROCESSING_WORKER_TYPE,
        store=heartbeat_store,
        started_at=NOW,
        metadata={"queue": "cx.document_processing", "runtime": "background"},
    )
    document = save_source_document(store, tmp_path)
    queued = enqueue_document_processing_pipeline(
        document["document_id"],
        store=store,
        job_queue=job_queue,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    execution = run_cx_document_processing_worker_once(
        store=store,
        storage_config=storage_config(tmp_path),
        mo_client=mo_client,
        embedding_alias="mock-embedding-default",
        job_queue=job_queue,
        worker_heartbeat_emitter=heartbeat_emitter,
    )

    latest = store.get_latest_document_processing_run(document["document_id"])
    heartbeat = heartbeat_store.get_heartbeat("nex-cx", CX_PROCESSING_BACKGROUND_WORKER_ID)
    assert execution.status == "SUCCEEDED"
    assert execution.job is not None
    assert execution.job["job_id"] == queued["job"]["job_id"]
    assert execution.handler_result["pipeline_run_id"] == queued["pipeline_run_id"]
    assert latest is not None
    assert latest["status"] == "SUCCEEDED"
    assert latest["job"]["status"] == "SUCCEEDED"
    assert job_queue.get_job(queued["job"]["job_id"])["status"] == "SUCCEEDED"
    assert heartbeat is not None
    assert heartbeat["status"] == IDLE
    assert heartbeat["metadata"]["runtime"] == "background"
    assert len(mo_client.calls) == 2


def test_cx_document_processing_worker_reports_idle_without_queued_job(
    tmp_path: Path,
) -> None:
    store = ContentIngestionStore()
    heartbeat_store = InMemoryWorkerHeartbeatStore()
    heartbeat_emitter = WorkerHeartbeatEmitter(
        service_id="nex-cx",
        worker_id=CX_PROCESSING_BACKGROUND_WORKER_ID,
        worker_type=CX_PROCESSING_WORKER_TYPE,
        store=heartbeat_store,
        started_at=NOW,
    )

    execution = run_cx_document_processing_worker_once(
        store=store,
        storage_config=storage_config(tmp_path),
        mo_client=FakeMoEmbeddingClient(),
        embedding_alias="mock-embedding-default",
        job_queue=InMemoryJobQueue(),
        worker_heartbeat_emitter=heartbeat_emitter,
    )

    heartbeat = heartbeat_store.get_heartbeat("nex-cx", CX_PROCESSING_BACKGROUND_WORKER_ID)
    assert execution.status == IDLE
    assert execution.job is None
    assert heartbeat is not None
    assert heartbeat["status"] == IDLE


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
    started_event = event_by_type(events, PROCESSING_EVENT_STARTED)
    succeeded_event = event_by_type(events, PROCESSING_EVENT_SUCCEEDED)
    busy_event = event_by_type(events, PROCESSING_WORKER_EVENT_BUSY)
    idle_event = event_by_type(events, PROCESSING_WORKER_EVENT_IDLE)

    assert processing_event_types(events) == {
        PROCESSING_EVENT_STARTED,
        PROCESSING_EVENT_SUCCEEDED,
    }
    assert worker_event_types(events) == {
        PROCESSING_WORKER_EVENT_BUSY,
        PROCESSING_WORKER_EVENT_IDLE,
    }
    assert succeeded_event["subject_ref"] == {
        "type": "cx.document",
        "id": document["document_id"],
    }
    assert succeeded_event["details"] == {
        "pipeline_run_id": run["pipeline_run_id"],
        "job_id": run["job"]["job_id"],
        "job_status": "SUCCEEDED",
        "step_summary": {"total": 6, "succeeded": 6, "skipped": 0, "failed": 0},
    }
    assert started_event["details"] == {
        "pipeline_run_id": run["pipeline_run_id"],
        "job_id": run["job"]["job_id"],
        "job_status": "RUNNING",
    }
    assert busy_event["subject_ref"] == {
        "type": "worker",
        "id": CX_PROCESSING_WORKER_ID,
    }
    assert busy_event["details"]["worker_status"] == BUSY
    assert busy_event["details"]["active_job_id"] == run["job"]["job_id"]
    assert busy_event["details"]["heartbeat_emit_ok"] is None
    assert idle_event["details"]["worker_status"] == IDLE
    assert idle_event["details"]["job_status"] == "SUCCEEDED"
    assert idle_event["details"]["step_summary"] == {
        "total": 6,
        "succeeded": 6,
        "skipped": 0,
        "failed": 0,
    }
    assert "Pipeline source text" not in str(events)


def test_run_document_processing_pipeline_updates_worker_heartbeat_on_success(
    tmp_path: Path,
) -> None:
    store = ContentIngestionStore()
    mo_client = FakeMoEmbeddingClient()
    job_queue = InMemoryJobQueue()
    heartbeat_store = InMemoryWorkerHeartbeatStore()
    heartbeat_emitter = WorkerHeartbeatEmitter(
        service_id="nex-cx",
        worker_id=CX_PROCESSING_WORKER_ID,
        worker_type=CX_PROCESSING_WORKER_TYPE,
        store=heartbeat_store,
        started_at=NOW,
        metadata={"queue": "cx.document_processing"},
    )
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
        worker_heartbeat_emitter=heartbeat_emitter,
    )

    heartbeat = heartbeat_store.get_heartbeat("nex-cx", CX_PROCESSING_WORKER_ID)
    assert heartbeat is not None
    assert heartbeat["status"] == IDLE
    assert heartbeat["active_job_id"] is None
    assert heartbeat["trace_id"] == TRACE_ID
    assert heartbeat["metadata"] == {
        "document_id": document["document_id"],
        "job_id": run["job"]["job_id"],
        "job_status": "SUCCEEDED",
        "pipeline_run_id": run["pipeline_run_id"],
        "queue": "cx.document_processing",
        "step_summary": {"total": 6, "succeeded": 6, "skipped": 0, "failed": 0},
    }


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
    failed_event = event_by_type(events, PROCESSING_EVENT_FAILED)
    error_event = event_by_type(events, PROCESSING_WORKER_EVENT_ERROR)
    assert processing_event_types(events) == {
        PROCESSING_EVENT_FAILED,
        PROCESSING_EVENT_STARTED,
    }
    assert worker_event_types(events) == {
        PROCESSING_WORKER_EVENT_BUSY,
        PROCESSING_WORKER_EVENT_ERROR,
    }
    assert failed_event["severity"] == "ERROR"
    assert failed_event["details"] == {
        "pipeline_run_id": failed_run["pipeline_run_id"],
        "job_id": failed_run["job"]["job_id"],
        "job_status": "FAILED",
        "step_summary": {"total": 1, "succeeded": 0, "skipped": 0, "failed": 1},
        "failed_step": "extraction",
    }
    assert error_event["severity"] == "ERROR"
    assert error_event["details"]["worker_status"] == ERROR
    assert error_event["details"]["active_job_id"] == failed_run["job"]["job_id"]
    assert error_event["details"]["failed_step"] == "extraction"


def test_run_document_processing_pipeline_updates_worker_heartbeat_on_failure(
    tmp_path: Path,
) -> None:
    store = ContentIngestionStore()
    job_queue = InMemoryJobQueue()
    heartbeat_store = InMemoryWorkerHeartbeatStore()
    heartbeat_emitter = WorkerHeartbeatEmitter(
        service_id="nex-cx",
        worker_id=CX_PROCESSING_WORKER_ID,
        worker_type=CX_PROCESSING_WORKER_TYPE,
        store=heartbeat_store,
        started_at=NOW,
    )
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
            worker_heartbeat_emitter=heartbeat_emitter,
        )
    except ProcessingPipelineError as exc:
        failed_run = exc.pipeline_run
    else:
        raise AssertionError("expected pipeline failure")

    assert failed_run is not None
    heartbeat = heartbeat_store.get_heartbeat("nex-cx", CX_PROCESSING_WORKER_ID)
    assert heartbeat is not None
    assert heartbeat["status"] == ERROR
    assert heartbeat["active_job_id"] == failed_run["job"]["job_id"]
    assert heartbeat["metadata"]["job_status"] == "FAILED"
    assert heartbeat["metadata"]["failed_step"] == "extraction"
    assert heartbeat["metadata"]["step_summary"] == {
        "total": 1,
        "succeeded": 0,
        "skipped": 0,
        "failed": 1,
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


def test_run_document_processing_pipeline_isolates_worker_heartbeat_failures(
    tmp_path: Path,
) -> None:
    store = ContentIngestionStore()
    mo_client = FakeMoEmbeddingClient()
    document = save_source_document(store, tmp_path)
    heartbeat_emitter = WorkerHeartbeatEmitter(
        service_id="nex-cx",
        worker_id=CX_PROCESSING_WORKER_ID,
        worker_type=CX_PROCESSING_WORKER_TYPE,
        store=ExplodingWorkerHeartbeatStore(),
        started_at=NOW,
    )

    run = run_document_processing_pipeline(
        document["document_id"],
        store=store,
        storage_config=storage_config(tmp_path),
        mo_client=mo_client,
        embedding_alias="mock-embedding-default",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        worker_heartbeat_emitter=heartbeat_emitter,
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


def test_processing_route_read_latest_prefers_persisted_repository(
    tmp_path: Path,
) -> None:
    document_id = "persisted-document"
    persisted_repository = InMemoryCxContentRepository()
    persisted_job = build_processing_job(
        document_id=document_id,
        pipeline_run_id="persisted-run",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        created_at=NOW,
    )
    persisted_repository.save_processing_run_record(
        build_processing_run_persistence_record(
            build_queued_pipeline_run_record(
                document_id=document_id,
                pipeline_run_id="persisted-run",
                request_id=REQUEST_ID,
                trace_id=TRACE_ID,
                queued_at=NOW,
                job=persisted_job,
            )
        )
    )
    client, store, _ = build_test_client(
        tmp_path,
        processing_run_repository=persisted_repository,
    )
    memory_job = build_processing_job(
        document_id=document_id,
        pipeline_run_id="memory-run",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        created_at=LATER,
    )
    store.save_document_processing_run(
        build_queued_pipeline_run_record(
            document_id=document_id,
            pipeline_run_id="memory-run",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
            queued_at=LATER,
            job=memory_job,
        )
    )

    response = client.get(
        f"/api/v1/documents/{document_id}/processing",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["pipeline_run_id"] == "persisted-run"
    assert payload["processing_run_schema_version"] == (
        "cx_document_processing_run.persistence.v1"
    )
    assert payload["job_id"] == persisted_job["job_id"]
    assert payload["steps_included"] is True
    assert "job" not in payload


def test_processing_route_read_latest_falls_back_to_memory_record(
    tmp_path: Path,
) -> None:
    document_id = "memory-document"
    client, store, _ = build_test_client(
        tmp_path,
        processing_run_repository=InMemoryCxContentRepository(),
    )
    job = build_processing_job(
        document_id=document_id,
        pipeline_run_id="memory-only-run",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        created_at=NOW,
    )
    store.save_document_processing_run(
        build_queued_pipeline_run_record(
            document_id=document_id,
            pipeline_run_id="memory-only-run",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
            queued_at=NOW,
            job=job,
        )
    )

    response = client.get(
        f"/api/v1/documents/{document_id}/processing",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["pipeline_run_id"] == "memory-only-run"
    assert payload["job"]["job_id"] == job["job_id"]
    assert "processing_run_schema_version" not in payload


def test_processing_route_read_latest_maps_repository_error_to_problem(
    tmp_path: Path,
) -> None:
    client, _, _ = build_test_client(
        tmp_path,
        processing_run_repository=(
            UnavailableProcessingRunRepository()  # type: ignore[arg-type]
        ),
    )

    response = client.get(
        "/api/v1/documents/unavailable/processing",
        headers=auth_headers(),
    )

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["error_code"] == "cx_content.repository_unavailable"


def test_processing_run_repository_resolution_prefers_explicit_repository() -> None:
    explicit_repository = InMemoryCxContentRepository()
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                nex_persistence=SimpleNamespace(
                    mode=PERSISTENCE_MODE_POSTGRES,
                    api_session_factory=lambda: None,
                )
            )
        )
    )

    resolved = _processing_run_repository_from_request(
        request,  # type: ignore[arg-type]
        processing_run_repository=explicit_repository,
    )

    assert resolved is explicit_repository


def test_processing_run_repository_resolution_uses_postgres_runtime() -> None:
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                nex_persistence=SimpleNamespace(
                    mode=PERSISTENCE_MODE_POSTGRES,
                    api_session_factory=lambda: None,
                )
            )
        )
    )

    resolved = _processing_run_repository_from_request(request)  # type: ignore[arg-type]

    assert isinstance(resolved, SqlAlchemyCxContentRepository)


def test_processing_run_repository_resolution_skips_memory_runtime() -> None:
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                nex_persistence=SimpleNamespace(
                    mode="memory",
                    api_session_factory=lambda: None,
                )
            )
        )
    )
    missing_session_factory_request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                nex_persistence=SimpleNamespace(
                    mode=PERSISTENCE_MODE_POSTGRES,
                    api_session_factory=None,
                )
            )
        )
    )

    assert (
        _processing_run_repository_from_request(request)  # type: ignore[arg-type]
        is None
    )
    assert (
        _processing_run_repository_from_request(  # type: ignore[arg-type]
            missing_session_factory_request
        )
        is None
    )


def test_processing_routes_enqueue_and_worker_can_complete_pipeline(tmp_path: Path) -> None:
    job_queue = InMemoryJobQueue()
    client, store, mo_client = build_test_client(tmp_path, job_queue=job_queue)
    uploaded = client.post(
        "/api/v1/documents/uploads",
        json={
            "filename": "source.txt",
            "content_type": "text/plain",
            "content_text": "route enqueue worker text",
        },
        headers=auth_headers(),
    ).json()

    queued_response = client.post(
        f"/api/v1/documents/{uploaded['document_id']}/processing/enqueue",
        headers=auth_headers(),
    )
    queued = queued_response.json()
    latest_queued = client.get(
        f"/api/v1/documents/{uploaded['document_id']}/processing",
        headers=auth_headers(),
    ).json()
    execution = run_cx_document_processing_worker_once(
        store=store,
        storage_config=storage_config(tmp_path),
        mo_client=mo_client,
        embedding_alias="mock-embedding-default",
        job_queue=job_queue,
    )
    latest_done = client.get(
        f"/api/v1/documents/{uploaded['document_id']}/processing",
        headers=auth_headers(),
    ).json()

    assert queued_response.status_code == 202
    assert queued["status"] == "QUEUED"
    assert latest_queued["pipeline_run_id"] == queued["pipeline_run_id"]
    assert execution.status == "SUCCEEDED"
    assert latest_done["status"] == "SUCCEEDED"
    assert latest_done["job"]["job_id"] == queued["job"]["job_id"]


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
    assert processing_event_types(events) == {
        PROCESSING_EVENT_SUCCEEDED,
        PROCESSING_EVENT_STARTED,
    }
    assert worker_event_types(events) == {
        PROCESSING_WORKER_EVENT_BUSY,
        PROCESSING_WORKER_EVENT_IDLE,
    }
    succeeded_event = event_by_type(events, PROCESSING_EVENT_SUCCEEDED)
    idle_event = event_by_type(events, PROCESSING_WORKER_EVENT_IDLE)
    assert succeeded_event["details"]["pipeline_run_id"] == response.json()["pipeline_run_id"]
    assert idle_event["details"]["heartbeat_emit_ok"] is True


def test_processing_route_emits_worker_heartbeat_to_app_persistence_store(tmp_path: Path) -> None:
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    store = ContentIngestionStore()
    mo_client = FakeMoEmbeddingClient()
    config = storage_config(tmp_path)
    heartbeat_store = InMemoryWorkerHeartbeatStore()
    app.state.nex_persistence = SimpleNamespace(worker_heartbeat_store=heartbeat_store)
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
            "content_text": "route heartbeat text",
        },
        headers=auth_headers(),
    ).json()

    response = client.post(
        f"/api/v1/documents/{uploaded['document_id']}/processing/run",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    heartbeat = heartbeat_store.get_heartbeat("nex-cx", CX_PROCESSING_WORKER_ID)
    assert heartbeat is not None
    assert heartbeat["worker_type"] == CX_PROCESSING_WORKER_TYPE
    assert heartbeat["status"] == IDLE
    assert heartbeat["metadata"]["pipeline_run_id"] == response.json()["pipeline_run_id"]


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
    queued = build_queued_pipeline_run_record(
        document_id="doc-1",
        pipeline_run_id="run-queued",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        queued_at=NOW,
        job=job,
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
    assert queued["status"] == "QUEUED"
    assert queued["step_summary"] == {"total": 0, "succeeded": 0, "skipped": 0, "failed": 0}
    assert queued["job"]["status"] == "QUEUED"
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


def test_processing_worker_lifecycle_event_helper_builds_stable_safe_events() -> None:
    event_store = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id="nex-cx", store=event_store)
    failed_heartbeat = WorkerHeartbeatEmitResult.failed(
        error_code="worker_heartbeat.emit_failed",
        detail="worker heartbeat emission failed",
        status_code=503,
    )
    job = {
        "job_id": "job-001",
        "status": "FAILED",
    }

    skipped_result = _safe_emit_processing_worker_lifecycle_event(
        None,
        event_type=PROCESSING_WORKER_EVENT_ERROR,
        severity="ERROR",
        message="CX processing worker reported an error.",
        status=ERROR,
        document_id="doc-1",
        pipeline_run_id="run-1",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        job=job,
        heartbeat_result=failed_heartbeat,
    )
    result = _safe_emit_processing_worker_lifecycle_event(
        emitter,
        event_type=PROCESSING_WORKER_EVENT_ERROR,
        severity="ERROR",
        message="CX processing worker reported an error.",
        status=ERROR,
        document_id="doc-1",
        pipeline_run_id="run-1",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        job=job,
        heartbeat_result=failed_heartbeat,
        step_summary={"total": 1, "succeeded": 0, "skipped": 0, "failed": 1},
        failed_step="extraction",
        created_at=NOW,
    )

    assert skipped_result is None
    assert result is not None
    assert result.ok is True
    assert result.event is not None
    assert result.event["event_id"] == processing_worker_event_id(
        pipeline_run_id="run-1",
        event_type=PROCESSING_WORKER_EVENT_ERROR,
    )
    assert result.event["subject_ref"] == {
        "type": "worker",
        "id": CX_PROCESSING_WORKER_ID,
    }
    assert result.event["details"] == {
        "worker_id": CX_PROCESSING_WORKER_ID,
        "worker_type": CX_PROCESSING_WORKER_TYPE,
        "worker_status": ERROR,
        "pipeline_run_id": "run-1",
        "document_id": "doc-1",
        "heartbeat_emit_ok": False,
        "heartbeat_error_code": "worker_heartbeat.emit_failed",
        "active_job_id": "job-001",
        "job_id": "job-001",
        "job_status": "FAILED",
        "step_summary": {"total": 1, "succeeded": 0, "skipped": 0, "failed": 1},
        "failed_step": "extraction",
    }


def test_processing_worker_heartbeat_helper_is_safe_and_builds_metadata() -> None:
    heartbeat_store = InMemoryWorkerHeartbeatStore()
    emitter = WorkerHeartbeatEmitter(
        service_id="nex-cx",
        worker_id=CX_PROCESSING_WORKER_ID,
        worker_type=CX_PROCESSING_WORKER_TYPE,
        store=heartbeat_store,
        started_at=NOW,
        metadata={"queue": "cx.document_processing"},
    )
    job = {
        "job_id": "job-001",
        "status": "RUNNING",
    }

    skipped_result = _safe_emit_processing_worker_heartbeat(
        None,
        status=BUSY,
        document_id="doc-1",
        pipeline_run_id="run-1",
        trace_id=TRACE_ID,
        job=job,
    )
    result = _safe_emit_processing_worker_heartbeat(
        emitter,
        status=BUSY,
        document_id="doc-1",
        pipeline_run_id="run-1",
        trace_id=TRACE_ID,
        job=job,
        observed_at=LATER,
    )

    assert skipped_result is None
    assert result is not None
    assert result.ok is True
    assert result.heartbeat is not None
    assert result.heartbeat["status"] == BUSY
    assert result.heartbeat["active_job_id"] == "job-001"
    assert result.heartbeat["metadata"] == {
        "document_id": "doc-1",
        "job_id": "job-001",
        "job_status": "RUNNING",
        "pipeline_run_id": "run-1",
        "queue": "cx.document_processing",
    }


def test_extraction_job_id_for_document_reports_missing_document() -> None:
    try:
        extraction_job_id_for_document(ContentIngestionStore(), "missing")
    except Exception as exc:
        assert getattr(exc, "error_code") == "cx.document_not_found"
    else:
        raise AssertionError("expected missing document error")
