from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from nex_runtime import InMemoryJobQueue, JobQueueError

from nex_cx.access_context import CxAccessContext
from nex_cx.async_generation import (
    AsyncGenerationAdmissionError,
    admit_async_generation,
)
from nex_cx.generation_request_store import load_generation_request_envelope
from nex_cx.generation_runtime import (
    GroundedGenerationRuntime,
    InMemoryGenerationAdmissionRepository,
)
from nex_cx.private_text_store import FileSystemCxPrivateTextStore


def _context() -> CxAccessContext:
    return CxAccessContext(
        caller_service_id="nex-ae-api",
        tenant_id="tenant-1",
        subject_id="user-1",
        request_id="request-1",
        trace_id="trace-1",
        scopes=("service:call",),
    )


@dataclass
class ExecutionRepository:
    records: dict[str, dict] = field(default_factory=dict)

    def get(self, cx_generation_id, *, access_context):
        record = self.records.get(cx_generation_id)
        return deepcopy(record) if record is not None else None

    def save(self, execution_record, *, access_context, private_output_metadata):
        self.records[execution_record["cx_generation_id"]] = dict(execution_record)
        return dict(execution_record)


def _runtime(tmp_path) -> GroundedGenerationRuntime:
    return GroundedGenerationRuntime(
        admission_repository=InMemoryGenerationAdmissionRepository(),
        execution_repository=ExecutionRepository(),
        private_output_store=FileSystemCxPrivateTextStore(tmp_path / "outputs"),
        clock=lambda: datetime(2026, 9, 24, tzinfo=UTC),
    )


def _arguments(tmp_path, runtime, queue):
    return {
        "source_payload": {"prompt": "private question"},
        "mo_payload": {
            "cx_generation_id": "temporary",
            "alias": "general-llm-default",
            "provider_capability": "generation",
            "workload_class": "LLM_INTERACTIVE",
            "reasoning_mode": "disabled",
            "provider_prompt_package_hash": "a" * 64,
            "input": "private question",
            "metadata": {},
        },
        "compatibility_rule": {"grounding_required": False},
        "retrieval_package": None,
        "access_context": _context(),
        "request_id": "request-1",
        "trace_id": "trace-1",
        "idempotency_key": "idem-1",
        "runtime": runtime,
        "request_store": FileSystemCxPrivateTextStore(tmp_path / "requests"),
        "job_queue": queue,
    }


def test_admits_and_idempotently_joins_existing_job(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    queue = InMemoryJobQueue()
    arguments = _arguments(tmp_path, runtime, queue)

    first = admit_async_generation(**arguments)
    second = admit_async_generation(**arguments)

    assert first["admission_status"] == "ENQUEUED"
    assert second["admission_status"] == "JOINED"
    assert second["job"] == first["job"]
    assert len(queue.jobs) == 1
    stored = queue.get_job(first["job"]["job_id"])
    envelope = load_generation_request_envelope(
        private_text_store=arguments["request_store"],
        access_context=_context(),
        cx_generation_id=first["job"]["cx_generation_id"],
        receipt={
            "request_receipt_schema_version": "cx_generation_request_receipt.v1",
            "request_storage_backend": "filesystem-text-v1",
            "request_storage_uri": "cx-private://internal",
            "request_envelope_sha256": stored["payload"]["request_envelope_sha256"],
            "request_envelope_size_bytes": stored["payload"]["request_envelope_size_bytes"],
        },
    )
    assert envelope["source_payload"]["prompt"] == "private question"


def test_recovers_after_enqueue_failure_by_joining(tmp_path) -> None:
    runtime = _runtime(tmp_path)

    class FailingQueue(InMemoryJobQueue):
        def enqueue(self, job):
            raise JobQueueError("job.store_unavailable", "unavailable", 503)

    with pytest.raises(AsyncGenerationAdmissionError) as error:
        admit_async_generation(**_arguments(tmp_path, runtime, FailingQueue()))
    assert error.value.retryable is True

    recovered = admit_async_generation(
        **_arguments(tmp_path, runtime, InMemoryJobQueue())
    )
    assert recovered["admission_status"] == "JOINED"


def test_replays_terminal_generation_with_or_without_job(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    queue = InMemoryJobQueue()
    arguments = _arguments(tmp_path, runtime, queue)
    admitted = admit_async_generation(**arguments)
    generation_id = admitted["job"]["cx_generation_id"]
    runtime.execution_repository.records[generation_id] = {
        "cx_generation_id": generation_id,
        "status": "COMPLETED",
    }
    replay = admit_async_generation(**arguments)
    assert replay["admission_status"] == "REPLAYED"
    assert replay["job"] is not None
    assert replay["generation"]["status"] == "COMPLETED"

    runtime_without_job = _runtime(tmp_path / "other")
    arguments_without_job = _arguments(
        tmp_path / "other", runtime_without_job, InMemoryJobQueue()
    )
    initial = admit_async_generation(**arguments_without_job)
    generation_id = initial["job"]["cx_generation_id"]
    runtime_without_job.execution_repository.records[generation_id] = {
        "cx_generation_id": generation_id,
        "status": "FAILED",
    }
    arguments_without_job["job_queue"] = InMemoryJobQueue()
    replay_without_job = admit_async_generation(**arguments_without_job)
    assert replay_without_job["job"] is None


def test_detects_existing_job_envelope_conflict(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    queue = InMemoryJobQueue()
    arguments = _arguments(tmp_path, runtime, queue)
    first = admit_async_generation(**arguments)
    job = queue.jobs[first["job"]["job_id"]]
    job["payload"]["request_envelope_sha256"] = "b" * 64

    with pytest.raises(AsyncGenerationAdmissionError) as error:
        admit_async_generation(**arguments)
    assert error.value.error_code == "cx.async_generation.idempotency_conflict"


def test_maps_private_store_and_runtime_failures(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    bad = _arguments(tmp_path, runtime, InMemoryJobQueue())
    bad["source_payload"] = {"api_key": "secret"}
    with pytest.raises(AsyncGenerationAdmissionError) as private_error:
        admit_async_generation(**bad)
    assert private_error.value.error_code == "CX_GENERATION_REQUEST_INVALID"

    conflict = _arguments(tmp_path, runtime, InMemoryJobQueue())
    conflict["mo_payload"] = {
        **conflict["mo_payload"],
        "provider_prompt_package_hash": "b" * 64,
    }
    with pytest.raises(AsyncGenerationAdmissionError) as runtime_error:
        admit_async_generation(**conflict)
    assert runtime_error.value.error_code == "cx.generation_runtime.idempotency_conflict"
    assert str(runtime_error.value) == runtime_error.value.detail
