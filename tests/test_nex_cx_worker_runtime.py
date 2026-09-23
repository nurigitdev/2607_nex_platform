from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import text

from nex_runtime import (
    InMemoryJobQueue,
    JobQueueError,
    SqlAlchemyJobQueue,
    build_common_job,
    build_engine,
    build_session_factory,
    build_subject_ref,
)
from nex_cx.worker_leases import SqlAlchemyCxWorkerLeaseStore
from nex_cx.worker_runtime import (
    CxCancellationToken,
    CxWorkerCancellationRequested,
    CxWorkerRuntimeError,
    CxWorkerRuntimePolicy,
    _execute_claimed,
    _job as read_job,
    _safe_error_code,
    _timestamp,
    request_worker_cancellation,
    run_bounded_worker_batch,
)


NOW = "2026-09-23T02:00:00Z"
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "09750000-0000-4000-8000-000000000001"


def _stores() -> tuple[SqlAlchemyJobQueue, SqlAlchemyCxWorkerLeaseStore]:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE service_jobs (
                    job_id TEXT PRIMARY KEY,
                    job_schema_version TEXT NOT NULL,
                    job_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    subject_type TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL,
                    max_attempts INTEGER NOT NULL,
                    retryable INTEGER NOT NULL,
                    links TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    error TEXT,
                    replay_lineage TEXT,
                    available_at TEXT NOT NULL,
                    locked_at TEXT,
                    locked_by TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (job_type, idempotency_key)
                )
                """
            )
        )
    factory = build_session_factory(engine)
    return SqlAlchemyJobQueue(factory), SqlAlchemyCxWorkerLeaseStore(factory)


def _job(index: int, *, max_attempts: int = 2) -> dict[str, Any]:
    return build_common_job(
        job_id=f"job-{index}",
        job_type="cx.document_processing",
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
        subject_ref=build_subject_ref("cx.document", f"doc-{index}"),
        idempotency_key=f"idem-{index}",
        created_at=NOW,
        max_attempts=max_attempts,
    )


def _clock(*values: str):
    iterator: Iterator[str] = iter(values)
    return lambda: next(iterator)


def test_runs_successful_jobs_until_max_jobs_bound() -> None:
    queue, leases = _stores()
    queue.enqueue(_job(1))
    queue.enqueue(_job(2))
    queue.enqueue(_job(3))
    result = run_bounded_worker_batch(
        job_queue=queue,
        lease_store=leases,
        handler=lambda execution, cancellation: {"ok": True},
        worker_id="worker-a",
        worker_type="cx.processing.worker",
        workload="document_processing",
        runtime_policy=CxWorkerRuntimePolicy(max_jobs=2),
        clock=_clock(
            NOW,
            NOW,
            NOW,
            NOW,
            NOW,
            NOW,
            NOW,
            NOW,
            NOW,
            NOW,
            NOW,
            NOW,
        ),
    )

    assert result["stop_reason"] == "MAX_JOBS"
    assert result["claimed_count"] == 2
    assert result["succeeded_count"] == 2
    assert [item["state"] for item in result["executions"]] == [
        "SUCCEEDED",
        "SUCCEEDED",
    ]
    assert queue.get_job("job-3")["status"] == "QUEUED"


def test_stops_idle_without_claiming() -> None:
    queue, leases = _stores()
    result = run_bounded_worker_batch(
        job_queue=queue,
        lease_store=leases,
        handler=lambda execution, cancellation: None,
        worker_id="worker-a",
        worker_type="cx.processing.worker",
        workload="document_processing",
        clock=_clock(NOW, NOW, NOW),
    )
    assert result["stop_reason"] == "IDLE"
    assert result["claimed_count"] == 0


def test_stops_before_claim_when_duration_bound_is_reached() -> None:
    queue, leases = _stores()
    queue.enqueue(_job(1))
    result = run_bounded_worker_batch(
        job_queue=queue,
        lease_store=leases,
        handler=lambda execution, cancellation: None,
        worker_id="worker-a",
        worker_type="cx.processing.worker",
        workload="document_processing",
        runtime_policy=CxWorkerRuntimePolicy(max_duration_seconds=5),
        clock=_clock(NOW, "2026-09-23T02:00:05Z", "2026-09-23T02:00:05Z"),
    )
    assert result["stop_reason"] == "MAX_DURATION"
    assert queue.get_job("job-1")["status"] == "QUEUED"


def test_handler_observes_cooperative_cancellation() -> None:
    queue, leases = _stores()
    queue.enqueue(_job(1))

    def cancel(execution: dict[str, Any], token: CxCancellationToken) -> None:
        request_worker_cancellation(queue, execution["job_id"], observed_at=NOW)
        token.checkpoint(observed_at=NOW)

    result = run_bounded_worker_batch(
        job_queue=queue,
        lease_store=leases,
        handler=cancel,
        worker_id="worker-a",
        worker_type="cx.processing.worker",
        workload="document_processing",
        runtime_policy=CxWorkerRuntimePolicy(max_jobs=1),
        clock=lambda: NOW,
    )

    assert result["cancelled_count"] == 1
    assert result["executions"][0]["state"] == "CANCELLED"
    assert result["executions"][0]["cancellation_requested_at"] == NOW
    assert queue.get_job("job-1")["status"] == "CANCELLED"


def test_handler_failure_retries_then_dead_letters_and_stops() -> None:
    queue, leases = _stores()
    queue.enqueue(_job(1, max_attempts=2))

    class HandlerFailure(Exception):
        error_code = "cx.processing.transient"

    def fail(execution: dict[str, Any], token: CxCancellationToken) -> None:
        raise HandlerFailure("private detail")

    retry = run_bounded_worker_batch(
        job_queue=queue,
        lease_store=leases,
        handler=fail,
        worker_id="worker-a",
        worker_type="cx.processing.worker",
        workload="document_processing",
        clock=lambda: NOW,
    )
    assert retry["stop_reason"] == "FAILURE"
    assert retry["retry_scheduled_count"] == 1
    assert queue.get_job("job-1")["error"]["detail"] != "private detail"

    second_time = queue.get_job("job-1")["available_at"]
    dead = run_bounded_worker_batch(
        job_queue=queue,
        lease_store=leases,
        handler=fail,
        worker_id="worker-b",
        worker_type="cx.processing.worker",
        workload="document_processing",
        clock=lambda: second_time,
    )
    assert dead["dead_lettered_count"] == 1
    assert queue.get_job("job-1")["status"] == "FAILED"


def test_cancellation_request_is_idempotent_and_checkpoint_validates_state() -> None:
    queue = InMemoryJobQueue()
    queue.enqueue(_job(1))
    first = request_worker_cancellation(queue, "job-1", observed_at=NOW)
    second = request_worker_cancellation(queue, "job-1", observed_at=NOW)
    assert first["already_cancelled"] is False
    assert second["already_cancelled"] is True

    token = CxCancellationToken(queue, "job-1")
    with pytest.raises(CxWorkerCancellationRequested) as requested:
        token.checkpoint(observed_at=NOW)
    assert requested.value.error_code == "cx.worker_runtime.cancellation_requested"

    queue.enqueue(_job(2))
    with pytest.raises(CxWorkerRuntimeError) as not_running:
        CxCancellationToken(queue, "job-2").checkpoint(observed_at=NOW)
    assert not_running.value.error_code == "cx.worker_runtime.job_not_running"
    with pytest.raises(CxWorkerRuntimeError) as missing:
        CxCancellationToken(queue, "missing").checkpoint(observed_at=NOW)
    assert missing.value.error_code == "cx.worker_runtime.job_not_found"


def test_runtime_policy_and_helpers_reject_invalid_values() -> None:
    for value in (0, True, 101):
        with pytest.raises(CxWorkerRuntimeError) as invalid_jobs:
            CxWorkerRuntimePolicy(max_jobs=value)
        assert invalid_jobs.value.error_code == "cx.worker_runtime.max_jobs_invalid"
    for value in (0, True, 3_601):
        with pytest.raises(CxWorkerRuntimeError) as invalid_duration:
            CxWorkerRuntimePolicy(max_duration_seconds=value)
        assert invalid_duration.value.error_code == (
            "cx.worker_runtime.max_duration_invalid"
        )
    with pytest.raises(CxWorkerRuntimeError) as invalid_stop:
        CxWorkerRuntimePolicy(stop_on_failure="yes")
    assert invalid_stop.value.error_code == (
        "cx.worker_runtime.stop_on_failure_invalid"
    )
    with pytest.raises(CxWorkerRuntimeError) as invalid_timestamp:
        _timestamp([], "time")
    assert invalid_timestamp.value.error_code == "cx.worker_runtime.timestamp_invalid"
    with pytest.raises(CxWorkerRuntimeError):
        _timestamp("bad", "time")
    assert _timestamp("2026-09-23T02:00:00", "time").tzinfo is not None
    assert _safe_error_code(RuntimeError("private")) == (
        "cx.worker_runtime.handler_failed"
    )


def test_queue_dependency_failures_are_typed_and_safe() -> None:
    class BrokenQueue(InMemoryJobQueue):
        def get_job(self, job_id: str) -> None:
            raise JobQueueError("job.store_unavailable", "offline", 503)

    token = CxCancellationToken(BrokenQueue(), "job")
    with pytest.raises(CxWorkerRuntimeError) as read_failure:
        token.checkpoint(observed_at=NOW)
    assert read_failure.value.error_code == (
        "cx.worker_runtime.cancellation_read_failed"
    )
    assert read_failure.value.retryable is True
    with pytest.raises(CxWorkerRuntimeError) as write_failure:
        request_worker_cancellation(BrokenQueue(), "job", observed_at=NOW)
    assert write_failure.value.error_code == (
        "cx.worker_runtime.cancellation_write_failed"
    )


def test_runtime_error_string_and_blank_job_id() -> None:
    error = CxWorkerRuntimeError("code", "detail")
    assert str(error) == "detail"
    with pytest.raises(CxWorkerRuntimeError) as blank:
        request_worker_cancellation(InMemoryJobQueue(), " ", observed_at=NOW)
    assert blank.value.error_code == "cx.worker_runtime.field_invalid"


def test_missing_cancellation_and_direct_cancellation_signal_paths() -> None:
    queue = InMemoryJobQueue()
    with pytest.raises(CxWorkerRuntimeError) as missing:
        request_worker_cancellation(queue, "missing", observed_at=NOW)
    assert missing.value.error_code == "cx.worker_runtime.job_not_found"

    queue.enqueue(_job(1))
    running = queue.claim_next_job(
        "worker-a",
        job_type="cx.document_processing",
        updated_at=NOW,
    )
    assert running is not None
    from nex_cx.worker_contracts import build_cx_worker_execution

    execution = build_cx_worker_execution(
        running,
        worker_id="worker-a",
        worker_type="cx.processing.worker",
        workload="document_processing",
        lease_expires_at="2026-09-23T02:02:00Z",
        observed_at=NOW,
    )

    def signal(execution: dict[str, Any], token: CxCancellationToken) -> None:
        raise CxWorkerCancellationRequested(execution["job_id"], NOW)

    cancelled = _execute_claimed(
        execution,
        job_queue=queue,
        handler=signal,
        observed_clock=lambda: NOW,
    )
    assert cancelled["state"] == "CANCELLED"
    assert queue.get_job("job-1")["status"] == "CANCELLED"


def test_runtime_propagates_typed_handler_and_retry_persistence_failures() -> None:
    queue = InMemoryJobQueue()
    queue.enqueue(_job(1))
    running = queue.claim_next_job(
        "worker-a",
        job_type="cx.document_processing",
        updated_at=NOW,
    )
    assert running is not None
    from nex_cx.worker_contracts import build_cx_worker_execution

    execution = build_cx_worker_execution(
        running,
        worker_id="worker-a",
        worker_type="cx.processing.worker",
        workload="document_processing",
        lease_expires_at="2026-09-23T02:02:00Z",
        observed_at=NOW,
    )

    def typed(execution: dict[str, Any], token: CxCancellationToken) -> None:
        raise CxWorkerRuntimeError("cx.typed", "typed")

    with pytest.raises(CxWorkerRuntimeError) as typed_failure:
        _execute_claimed(
            execution,
            job_queue=queue,
            handler=typed,
            observed_clock=lambda: NOW,
        )
    assert typed_failure.value.error_code == "cx.typed"

    class RetryBrokenQueue(InMemoryJobQueue):
        def retry_job(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            raise JobQueueError("job.store_unavailable", "offline", 503)

    broken = RetryBrokenQueue()
    broken.enqueue(_job(2))
    broken_running = broken.claim_next_job(
        "worker-a",
        job_type="cx.document_processing",
        updated_at=NOW,
    )
    assert broken_running is not None
    broken_execution = build_cx_worker_execution(
        broken_running,
        worker_id="worker-a",
        worker_type="cx.processing.worker",
        workload="document_processing",
        lease_expires_at="2026-09-23T02:02:00Z",
        observed_at=NOW,
    )
    with pytest.raises(CxWorkerRuntimeError) as persistence:
        _execute_claimed(
            broken_execution,
            job_queue=broken,
            handler=lambda execution, token: (_ for _ in ()).throw(RuntimeError()),
            observed_clock=lambda: NOW,
        )
    assert persistence.value.error_code == "cx.worker_runtime.failure_write_failed"


def test_job_reader_failures_and_default_clock_are_covered() -> None:
    class BrokenQueue(InMemoryJobQueue):
        def get_job(self, job_id: str) -> None:
            raise JobQueueError("job.store_unavailable", "offline", 503)

    with pytest.raises(CxWorkerRuntimeError) as unavailable:
        read_job(BrokenQueue(), "job")
    assert unavailable.value.error_code == "cx.worker_runtime.job_read_failed"
    with pytest.raises(CxWorkerRuntimeError) as missing:
        read_job(InMemoryJobQueue(), "job")
    assert missing.value.error_code == "cx.worker_runtime.job_not_found"

    import nex_cx.worker_runtime as worker_runtime

    assert worker_runtime._utc_now().endswith("Z")
