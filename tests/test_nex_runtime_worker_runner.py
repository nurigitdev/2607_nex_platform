from __future__ import annotations

from typing import Any

import pytest

from nex_runtime import (
    BUSY,
    ERROR,
    FAILED,
    IDLE,
    QUEUED,
    RUNNING,
    SUCCEEDED,
    InMemoryJobQueue,
    InMemoryWorkerHeartbeatStore,
    WorkerHeartbeatEmitter,
    WorkerRunnerConfig,
    WorkerRunnerError,
    build_common_job,
    build_subject_ref,
    run_worker_batch,
    run_worker_once,
)
from nex_runtime.worker_runner import _job_metadata

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"
NOW = "2026-08-05T00:00:00Z"
LATER = "2026-08-05T00:00:01Z"


class StaticClock:
    def __init__(self) -> None:
        self.ticks = 0

    def __call__(self) -> str:
        self.ticks += 1
        return f"2026-08-05T00:00:{self.ticks:02d}Z"


class BrokenClaimQueue:
    def claim_next_job(self, worker_id: str, *, job_type: str | None = None, updated_at=None):
        from nex_runtime import JobQueueError

        raise JobQueueError(
            error_code="job.store_unavailable",
            detail="job queue store is unavailable",
            status_code=503,
        )


class BrokenRetryQueue(InMemoryJobQueue):
    def retry_job(
        self,
        job_id: str,
        *,
        error: dict[str, Any] | None = None,
        failed_at: str | None = None,
        policy=None,
    ) -> dict[str, Any]:
        from nex_runtime import JobQueueError

        raise JobQueueError("job.retry_unavailable", "retry is unavailable")


def sample_job(**overrides: Any) -> dict[str, Any]:
    return build_common_job(
        job_id=overrides.pop("job_id", "job-001"),
        job_type=overrides.pop("job_type", "cx.document_processing"),
        trace_id=overrides.pop("trace_id", TRACE_ID),
        request_id=overrides.pop("request_id", REQUEST_ID),
        subject_ref=overrides.pop("subject_ref", build_subject_ref("cx.document", "doc-001")),
        idempotency_key=overrides.pop("idempotency_key", "idem-001"),
        created_at=overrides.pop("created_at", NOW),
        max_attempts=overrides.pop("max_attempts", 2),
        retryable=overrides.pop("retryable", True),
        links=overrides.pop("links", {"document": "/api/v1/documents/doc-001"}),
        status=overrides.pop("status", QUEUED),
    )


def config(max_jobs: int = 1) -> WorkerRunnerConfig:
    return WorkerRunnerConfig(
        service_id="nex-cx",
        worker_id="cx-worker-001",
        worker_type="cx.document_processing.worker",
        job_type="cx.document_processing",
        max_jobs=max_jobs,
    )


def heartbeat_emitter() -> tuple[WorkerHeartbeatEmitter, InMemoryWorkerHeartbeatStore]:
    store = InMemoryWorkerHeartbeatStore()
    return (
        WorkerHeartbeatEmitter(
            service_id="nex-cx",
            worker_id="cx-worker-001",
            worker_type="cx.document_processing.worker",
            store=store,
            started_at=NOW,
            metadata={"queue": "cx.document_processing"},
        ),
        store,
    )


def test_worker_runner_config_rejects_invalid_shape() -> None:
    with pytest.raises(WorkerRunnerError) as blank:
        WorkerRunnerConfig(
            service_id="nex-cx",
            worker_id="",
            worker_type="cx.document_processing.worker",
            job_type="cx.document_processing",
        )
    with pytest.raises(WorkerRunnerError) as max_jobs:
        config(max_jobs=0)

    assert blank.value.error_code == "worker_runner.field_invalid"
    assert max_jobs.value.error_code == "worker_runner.max_jobs_invalid"


def test_run_worker_once_reports_idle_when_no_job_is_available() -> None:
    queue = InMemoryJobQueue()
    emitter, store = heartbeat_emitter()

    execution = run_worker_once(
        config=config(),
        queue=queue,
        heartbeat_emitter=emitter,
        handler=lambda job: {"processed": job["job_id"]},
        clock=StaticClock(),
    )

    assert execution.status == IDLE
    assert execution.job is None
    assert execution.heartbeat_results[-1]["status"] == IDLE
    heartbeat = store.get_heartbeat("nex-cx", "cx-worker-001")
    assert heartbeat is not None
    assert heartbeat["status"] == IDLE
    assert heartbeat["metadata"]["claimed"] is False


def test_run_worker_once_claims_handles_and_completes_job() -> None:
    queue = InMemoryJobQueue()
    queue.enqueue(sample_job())
    emitter, store = heartbeat_emitter()
    seen_jobs: list[dict[str, Any]] = []

    execution = run_worker_once(
        config=config(),
        queue=queue,
        heartbeat_emitter=emitter,
        handler=lambda job: seen_jobs.append(job) or {"document_id": job["subject_ref"]["id"]},
        clock=StaticClock(),
    )

    stored = queue.get_job("job-001")
    heartbeat = store.get_heartbeat("nex-cx", "cx-worker-001")
    assert execution.status == SUCCEEDED
    assert execution.completed_job is not None
    assert execution.completed_job["status"] == SUCCEEDED
    assert execution.handler_result == {"document_id": "doc-001"}
    assert seen_jobs[0]["status"] == "RUNNING"
    assert stored is not None
    assert stored["status"] == SUCCEEDED
    assert stored["attempt_count"] == 1
    assert heartbeat is not None
    assert heartbeat["status"] == IDLE
    assert heartbeat["active_job_id"] is None
    assert heartbeat["metadata"]["job_status"] == SUCCEEDED
    assert execution.to_summary()["completed_status"] == SUCCEEDED


def test_run_worker_once_requeues_job_when_handler_raises() -> None:
    class HandlerError(Exception):
        error_code = "cx.processing_step_failed"
        detail = "Document processing step failed."

    queue = InMemoryJobQueue()
    queue.enqueue(sample_job())
    emitter, store = heartbeat_emitter()

    def handler(job: dict[str, Any]) -> dict[str, Any]:
        raise HandlerError()

    execution = run_worker_once(
        config=config(),
        queue=queue,
        heartbeat_emitter=emitter,
        handler=handler,
        clock=StaticClock(),
    )

    stored = queue.get_job("job-001")
    heartbeat = store.get_heartbeat("nex-cx", "cx-worker-001")
    assert execution.status == FAILED
    assert execution.error_code == "cx.processing_step_failed"
    assert execution.error_detail == "Document processing step failed."
    assert stored is not None
    assert stored["status"] == "QUEUED"
    assert stored["available_at"] == "2026-08-05T00:00:34Z"
    assert stored["error"]["error_code"] == "cx.processing_step_failed"
    assert stored["error"]["dead_lettered"] is False
    assert heartbeat is not None
    assert heartbeat["status"] == ERROR
    assert heartbeat["active_job_id"] == "job-001"
    assert heartbeat["metadata"]["error_code"] == "cx.processing_step_failed"


def test_run_worker_once_dead_letters_exhausted_handler_failure() -> None:
    queue = InMemoryJobQueue()
    queue.enqueue(sample_job(max_attempts=1))
    emitter, _ = heartbeat_emitter()

    execution = run_worker_once(
        config=config(),
        queue=queue,
        heartbeat_emitter=emitter,
        handler=lambda job: (_ for _ in ()).throw(RuntimeError("boom")),
        clock=StaticClock(),
    )

    stored = queue.get_job("job-001")
    assert execution.status == FAILED
    assert execution.completed_job is not None
    assert execution.completed_job["status"] == FAILED
    assert stored is not None
    assert stored["retryable"] is False
    assert stored["error"]["dead_lettered"] is True


def test_run_worker_once_reports_queue_claim_failure_without_raising() -> None:
    emitter, store = heartbeat_emitter()

    execution = run_worker_once(
        config=config(),
        queue=BrokenClaimQueue(),
        heartbeat_emitter=emitter,
        handler=lambda job: {"processed": job["job_id"]},
        clock=StaticClock(),
    )

    heartbeat = store.get_heartbeat("nex-cx", "cx-worker-001")
    assert execution.status == FAILED
    assert execution.error_code == "job.store_unavailable"
    assert heartbeat is not None
    assert heartbeat["status"] == ERROR
    assert heartbeat["metadata"]["error_code"] == "job.store_unavailable"


def test_run_worker_once_returns_current_job_when_retry_is_not_possible() -> None:
    queue = BrokenRetryQueue()
    queue.enqueue(sample_job())
    emitter, _ = heartbeat_emitter()

    execution = run_worker_once(
        config=config(),
        queue=queue,
        heartbeat_emitter=emitter,
        handler=lambda job: (_ for _ in ()).throw(RuntimeError("boom")),
        clock=StaticClock(),
    )

    assert execution.status == FAILED
    assert execution.completed_job is not None
    assert execution.completed_job["status"] == RUNNING
    assert queue.get_job("job-001")["status"] == RUNNING


def test_run_worker_batch_processes_until_idle_and_summarizes() -> None:
    queue = InMemoryJobQueue()
    queue.enqueue(sample_job(job_id="job-001", idempotency_key="idem-001"))
    queue.enqueue(sample_job(job_id="job-002", idempotency_key="idem-002"))
    emitter, _ = heartbeat_emitter()

    result = run_worker_batch(
        config=config(max_jobs=5),
        queue=queue,
        heartbeat_emitter=emitter,
        handler=lambda job: {"processed": job["job_id"]},
        clock=StaticClock(),
    )

    assert result.claimed_count == 2
    assert result.succeeded_count == 2
    assert result.failed_count == 0
    assert result.idle_count == 1
    assert result.to_summary()["claimed"] == 2
    assert [execution.status for execution in result.executions] == [
        SUCCEEDED,
        SUCCEEDED,
        IDLE,
    ]


def test_run_worker_batch_stops_on_failure_by_default_or_continues_when_requested() -> None:
    stop_queue = InMemoryJobQueue()
    stop_queue.enqueue(sample_job(job_id="job-001", idempotency_key="idem-001"))
    stop_queue.enqueue(sample_job(job_id="job-002", idempotency_key="idem-002"))
    emitter, _ = heartbeat_emitter()

    stopped = run_worker_batch(
        config=config(max_jobs=2),
        queue=stop_queue,
        heartbeat_emitter=emitter,
        handler=lambda job: (_ for _ in ()).throw(RuntimeError("boom")),
        clock=StaticClock(),
    )

    continue_queue = InMemoryJobQueue()
    continue_queue.enqueue(sample_job(job_id="job-001", idempotency_key="idem-001"))
    continue_queue.enqueue(sample_job(job_id="job-002", idempotency_key="idem-002"))
    continued = run_worker_batch(
        config=config(max_jobs=2),
        queue=continue_queue,
        heartbeat_emitter=emitter,
        handler=lambda job: (_ for _ in ()).throw(RuntimeError("boom")),
        stop_on_failure=False,
        clock=StaticClock(),
    )

    assert [execution.status for execution in stopped.executions] == [FAILED]
    assert [execution.status for execution in continued.executions] == [FAILED, FAILED]


def test_worker_runner_job_metadata_is_safe_and_minimal() -> None:
    assert _job_metadata({**sample_job(), "status": "RUNNING", "attempt_count": 1}) == {
        "job_id": "job-001",
        "job_type": "cx.document_processing",
        "job_status": "RUNNING",
        "attempt_count": 1,
    }
