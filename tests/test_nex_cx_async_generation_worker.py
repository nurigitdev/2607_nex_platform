from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text

from nex_runtime import (
    SqlAlchemyJobQueue,
    build_engine,
    build_session_factory,
)
from nex_cx.access_context import CxAccessContext
from nex_cx.async_generation import admit_async_generation
from nex_cx.async_generation_worker import (
    AsyncGenerationWorkerError,
    AsyncGenerationWorkerHandler,
)
from nex_cx import async_generation_worker as worker_module
from nex_cx.generation import GenerationFacadeError
from nex_cx.generation_runtime import (
    GroundedGenerationRuntime,
    GroundedGenerationRuntimeError,
    InMemoryGenerationAdmissionRepository,
)
from nex_cx.private_content import CxPrivateContentError
from nex_cx.private_text_store import FileSystemCxPrivateTextStore
from nex_cx.worker_leases import SqlAlchemyCxWorkerLeaseStore
from nex_cx.worker_runtime import CxWorkerRuntimePolicy, run_bounded_worker_batch


NOW = "2026-09-24T01:00:00Z"


@dataclass
class ExecutionRepository:
    records: dict[str, dict[str, Any]] = field(default_factory=dict)

    def get(self, cx_generation_id, *, access_context):
        return deepcopy(self.records.get(cx_generation_id))

    def save(self, execution_record, *, access_context, private_output_metadata):
        stored = {**deepcopy(dict(execution_record)), **dict(private_output_metadata or {})}
        self.records[stored["cx_generation_id"]] = stored
        return deepcopy(stored)


class MockGenerationClient:
    def __init__(self, response: dict[str, Any] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.response = response

    def create_generation(self, payload, *, request_id, trace_id):
        self.calls.append({"payload": payload, "request_id": request_id, "trace_id": trace_id})
        return self.response or {
            "mo_generation_id": "mo-1",
            "alias": payload["alias"],
            "model_revision": "mock-v1",
            "deployment_id": "mock-local",
            "provider_type": "mock-generation",
            "output": {"type": "text", "text": "Deterministic mock response."},
            "finish_reason": "STOP",
            "usage": {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5},
            "runtime_metadata": {"request_id": request_id, "trace_id": trace_id},
        }


def _stores():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE service_jobs (
                job_id TEXT PRIMARY KEY, job_schema_version TEXT NOT NULL,
                job_type TEXT NOT NULL, status TEXT NOT NULL, trace_id TEXT NOT NULL,
                request_id TEXT NOT NULL, subject_type TEXT NOT NULL,
                subject_id TEXT NOT NULL, idempotency_key TEXT NOT NULL,
                attempt_count INTEGER NOT NULL, max_attempts INTEGER NOT NULL,
                retryable INTEGER NOT NULL, links TEXT NOT NULL, payload TEXT NOT NULL,
                error TEXT, replay_lineage TEXT, available_at TEXT NOT NULL,
                locked_at TEXT, locked_by TEXT, started_at TEXT, completed_at TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE (job_type, idempotency_key)
            )
        """))
    factory = build_session_factory(engine)
    return SqlAlchemyJobQueue(factory), SqlAlchemyCxWorkerLeaseStore(factory)


def _context() -> CxAccessContext:
    return CxAccessContext(
        caller_service_id="nex-ae-api", tenant_id="tenant-1", subject_id="user-1",
        request_id="request-1", trace_id="trace-1", scopes=("service:call",),
    )


def _runtime(tmp_path):
    return GroundedGenerationRuntime(
        admission_repository=InMemoryGenerationAdmissionRepository(),
        execution_repository=ExecutionRepository(),
        private_output_store=FileSystemCxPrivateTextStore(tmp_path / "outputs"),
        clock=lambda: datetime(2026, 9, 24, 1, tzinfo=UTC),
    )


def _admit(tmp_path, runtime, queue):
    request_store = FileSystemCxPrivateTextStore(tmp_path / "requests")
    result = admit_async_generation(
        source_payload={"prompt": "private question"},
        mo_payload={
            "cx_generation_id": "temporary", "alias": "general-llm-default",
            "provider_capability": "generation", "workload_class": "LLM_INTERACTIVE",
            "generation_profile": "general-answer", "provider_prompt_package_hash": "a" * 64,
            "response_format": {"type": "text"}, "reasoning_mode": "disabled",
            "max_output_tokens": 64, "temperature": 0.0, "stream": False,
            "metadata": {},
        },
        compatibility_rule={
            "compatibility_rule_id": "rule-1", "grounding_required": False
        },
        retrieval_package=None, access_context=_context(), request_id="request-1",
        trace_id="trace-1", idempotency_key="idem-1", runtime=runtime,
        request_store=request_store, job_queue=queue,
    )
    return result, request_store


def test_bounded_worker_executes_mock_provider_and_persists_output(tmp_path) -> None:
    queue, leases = _stores()
    runtime = _runtime(tmp_path)
    admitted, request_store = _admit(tmp_path, runtime, queue)
    client = MockGenerationClient()
    handler = AsyncGenerationWorkerHandler(queue, runtime, request_store, client)

    result = run_bounded_worker_batch(
        job_queue=queue, lease_store=leases, handler=handler,
        worker_id="cx-generation-worker-1", worker_type="cx.generation.worker",
        workload="grounded_generation", runtime_policy=CxWorkerRuntimePolicy(max_jobs=1),
        clock=lambda: NOW,
    )

    assert result["succeeded_count"] == 1
    assert queue.get_job(admitted["job"]["job_id"])["status"] == "SUCCEEDED"
    assert len(client.calls) == 1
    generation_id = admitted["job"]["cx_generation_id"]
    stored = runtime.execution_repository.records[generation_id]
    assert stored["status"] == "COMPLETED"
    assert stored["output_storage_uri"].startswith("cx-private://")
    assert "output_text" not in stored


def test_worker_retries_missing_private_request(tmp_path) -> None:
    queue, leases = _stores()
    runtime = _runtime(tmp_path)
    admitted, _ = _admit(tmp_path, runtime, queue)
    handler = AsyncGenerationWorkerHandler(
        queue, runtime, FileSystemCxPrivateTextStore(tmp_path / "missing"), MockGenerationClient()
    )
    result = run_bounded_worker_batch(
        job_queue=queue, lease_store=leases, handler=handler,
        worker_id="worker-1", worker_type="cx.generation.worker",
        workload="grounded_generation", runtime_policy=CxWorkerRuntimePolicy(max_jobs=1),
        clock=lambda: NOW,
    )
    assert result["retry_scheduled_count"] == 1
    assert queue.get_job(admitted["job"]["job_id"])["status"] == "QUEUED"


def test_worker_maps_provider_output_validation_failure(tmp_path) -> None:
    queue, leases = _stores()
    runtime = _runtime(tmp_path)
    _, request_store = _admit(tmp_path, runtime, queue)
    client = MockGenerationClient({"output": {"type": "text", "text": ""}})
    result = run_bounded_worker_batch(
        job_queue=queue, lease_store=leases,
        handler=AsyncGenerationWorkerHandler(queue, runtime, request_store, client),
        worker_id="worker-1", worker_type="cx.generation.worker",
        workload="grounded_generation", runtime_policy=CxWorkerRuntimePolicy(max_jobs=1),
        clock=lambda: NOW,
    )
    assert result["retry_scheduled_count"] == 1


def test_worker_rejects_missing_job_and_maps_queue_error(tmp_path) -> None:
    runtime = _runtime(tmp_path)

    class MissingQueue:
        def get_job(self, job_id):
            return None

    handler = AsyncGenerationWorkerHandler(
        MissingQueue(), runtime, FileSystemCxPrivateTextStore(tmp_path), MockGenerationClient()
    )
    with pytest.raises(AsyncGenerationWorkerError, match="not found"):
        handler({"job_id": "missing"}, object())

    class BrokenQueue:
        def get_job(self, job_id):
            from nex_runtime import JobQueueError
            raise JobQueueError("job.store_unavailable", "unavailable", 503)

    handler.job_queue = BrokenQueue()
    with pytest.raises(AsyncGenerationWorkerError) as error:
        handler({"job_id": "missing"}, object())
    assert error.value.retryable is True
    assert str(error.value) == "unavailable"


def test_worker_maps_private_runtime_and_facade_errors(tmp_path, monkeypatch) -> None:
    queue, _ = _stores()
    runtime = _runtime(tmp_path)
    _, request_store = _admit(tmp_path, runtime, queue)
    job_id = next(iter(queue.list_jobs()))["job_id"]

    class Cancellation:
        def checkpoint(self):
            return None

    handler = AsyncGenerationWorkerHandler(
        queue, runtime, request_store, MockGenerationClient()
    )
    monkeypatch.setattr(
        worker_module,
        "load_generation_request_envelope",
        lambda **kwargs: (_ for _ in ()).throw(
            CxPrivateContentError(
                status_code=409,
                error_code="CX_PRIVATE_CORRUPT",
                detail="corrupt",
            )
        ),
    )
    with pytest.raises(AsyncGenerationWorkerError) as private_error:
        handler({"job_id": job_id}, Cancellation())
    assert private_error.value.error_code == "CX_PRIVATE_CORRUPT"

    monkeypatch.undo()

    class FacadeFailingClient:
        def create_generation(self, payload, *, request_id, trace_id):
            raise GenerationFacadeError(503, "mo.unavailable", "unavailable", True)

    handler.generation_client = FacadeFailingClient()
    with pytest.raises(AsyncGenerationWorkerError) as facade_error:
        handler({"job_id": job_id}, Cancellation())
    assert facade_error.value.retryable is True

    class FailingRuntime:
        def persist_completed(self, **kwargs):
            raise GroundedGenerationRuntimeError(
                error_code="cx.runtime.failed",
                detail="runtime failed",
                status_code=503,
                retryable=True,
            )

    handler.generation_client = MockGenerationClient()
    handler.runtime = FailingRuntime()
    with pytest.raises(AsyncGenerationWorkerError) as runtime_error:
        handler({"job_id": job_id}, Cancellation())
    assert runtime_error.value.error_code == "cx.runtime.failed"
