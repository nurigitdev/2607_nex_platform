from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from nex_runtime import InMemoryJobQueue

from nex_cx.access_context import CxAccessContext
from nex_cx.async_generation import admit_async_generation
from nex_cx.async_generation_recovery import (
    AsyncGenerationLeaseExpired,
    finalize_async_generation_failure,
    recover_expired_async_generation_job,
    should_finalize_generation_failure,
)
from nex_cx.async_generation_worker import (
    AsyncGenerationWorkerError,
    AsyncGenerationWorkerHandler,
)
from nex_cx.generation import GenerationFacadeError
from nex_cx.generation_request_store import load_generation_request_envelope
from nex_cx.generation_runtime import (
    GroundedGenerationRuntime,
    InMemoryGenerationAdmissionRepository,
)
from nex_cx.private_text_store import FileSystemCxPrivateTextStore
from nex_cx.worker_reconciliation import SPECIALIZED_RECOVERY_JOB_TYPES
from nex_cx.worker_runtime import CxWorkerCancellationRequested


@dataclass
class ExecutionRepository:
    records: dict[str, dict] = field(default_factory=dict)

    def get(self, cx_generation_id, *, access_context):
        return deepcopy(self.records.get(cx_generation_id))

    def save(self, execution_record, *, access_context, private_output_metadata):
        stored = deepcopy(dict(execution_record))
        self.records[stored["cx_generation_id"]] = stored
        return stored


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
        clock=lambda: datetime(2026, 9, 24, 2, tzinfo=UTC),
    )


def _admitted(tmp_path, *, max_attempts=3):
    runtime = _runtime(tmp_path)
    queue = InMemoryJobQueue()
    request_store = FileSystemCxPrivateTextStore(tmp_path / "requests")
    result = admit_async_generation(
        source_payload={"prompt": "private question"},
        mo_payload={
            "cx_generation_id": "temporary", "alias": "general-llm-default",
            "provider_capability": "generation", "workload_class": "LLM_INTERACTIVE",
            "provider_prompt_package_hash": "a" * 64,
            "response_format": {"type": "text"}, "reasoning_mode": "disabled",
            "metadata": {},
        },
        compatibility_rule={"compatibility_rule_id": "rule-1", "grounding_required": False},
        retrieval_package=None, access_context=_context(), request_id="request-1",
        trace_id="trace-1", idempotency_key="idem-1", runtime=runtime,
        request_store=request_store, job_queue=queue,
    )
    job_id = result["job"]["job_id"]
    queue.jobs[job_id]["max_attempts"] = max_attempts
    queue.start_job(job_id, updated_at="2026-09-24T02:00:00Z")
    job = queue.get_job(job_id)
    payload = job["payload"]
    envelope = load_generation_request_envelope(
        private_text_store=request_store, access_context=_context(),
        cx_generation_id=payload["cx_generation_id"],
        receipt={
            "request_receipt_schema_version": "cx_generation_request_receipt.v1",
            "request_storage_backend": "owner-private",
            "request_storage_uri": "cx-private://request",
            "request_envelope_sha256": payload["request_envelope_sha256"],
            "request_envelope_size_bytes": payload["request_envelope_size_bytes"],
        },
    )
    return runtime, queue, request_store, job, envelope


def test_intermediate_failure_remains_retryable_without_terminal_generation(tmp_path) -> None:
    runtime, queue, _, job, envelope = _admitted(tmp_path)
    failure = AsyncGenerationLeaseExpired("expired")
    assert should_finalize_generation_failure(job, failure) is False

    result = recover_expired_async_generation_job(
        job, "2026-09-24T02:02:00Z", job_queue=queue
    )
    assert result["status"] == "RETRY_SCHEDULED"
    assert result["generation"] is None
    assert runtime.execution_repository.records == {}


def test_exhausted_lease_recovery_dead_letters_and_finalizes_generation(tmp_path) -> None:
    runtime, queue, _, job, envelope = _admitted(tmp_path, max_attempts=1)
    result = recover_expired_async_generation_job(
        job, "2026-09-24T02:02:00Z", job_queue=queue,
        envelope=envelope, access_context=_context(), runtime=runtime,
    )
    assert result["status"] == "DEAD_LETTERED"
    assert result["generation"]["generation_status"] == "FAILED"
    assert result["private_payload_included"] is False


def test_terminal_recovery_requires_generation_dependencies(tmp_path) -> None:
    _, queue, _, job, _ = _admitted(tmp_path, max_attempts=1)
    with pytest.raises(ValueError, match="requires"):
        recover_expired_async_generation_job(
            job, "2026-09-24T02:02:00Z", job_queue=queue
        )


def test_permanent_failure_finalization_is_metadata_only(tmp_path) -> None:
    runtime, _, _, job, envelope = _admitted(tmp_path)
    failure = GenerationFacadeError(422, "cx.invalid", "private detail", False)
    assert should_finalize_generation_failure(job, failure) is True
    result = finalize_async_generation_failure(
        job=job, envelope=envelope, access_context=_context(),
        runtime=runtime, failure=failure,
    )
    assert result["generation_status"] == "FAILED"
    assert result["failure_code"] == "cx.invalid"
    assert "private detail" not in str(runtime.execution_repository.records)


def test_worker_finalizes_cancellation(tmp_path) -> None:
    runtime, queue, request_store, job, _ = _admitted(tmp_path)

    class CancellingToken:
        def checkpoint(self):
            raise CxWorkerCancellationRequested(job["job_id"], "2026-09-24T02:01:00Z")

    handler = AsyncGenerationWorkerHandler(queue, runtime, request_store, object())
    with pytest.raises(CxWorkerCancellationRequested):
        handler({"job_id": job["job_id"]}, CancellingToken())
    assert next(iter(runtime.execution_repository.records.values()))["status"] == "FAILED"


def test_worker_finalizes_last_retryable_attempt(tmp_path) -> None:
    runtime, queue, request_store, job, _ = _admitted(tmp_path, max_attempts=1)

    class FailingClient:
        def create_generation(self, payload, *, request_id, trace_id):
            raise GenerationFacadeError(503, "mo.timeout", "timeout", True)

    class Token:
        def checkpoint(self):
            return None

    handler = AsyncGenerationWorkerHandler(queue, runtime, request_store, FailingClient())
    with pytest.raises(AsyncGenerationWorkerError) as error:
        handler({"job_id": job["job_id"]}, Token())
    assert error.value.retryable is True
    assert next(iter(runtime.execution_repository.records.values()))["status"] == "FAILED"


def test_async_generation_is_specialized_recovery_workload() -> None:
    assert "cx.grounded-generation.execute" in SPECIALIZED_RECOVERY_JOB_TYPES
