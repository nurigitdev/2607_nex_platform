from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text

from nex_runtime import (
    BUSY,
    ERROR,
    IDLE,
    STARTING,
    STOPPED,
    STOPPING,
    InMemoryWorkerHeartbeatStore,
    SqlAlchemyJobQueue,
    WorkerHeartbeatEmitter,
    WorkerHeartbeatError,
    build_common_job,
    build_engine,
    build_session_factory,
    build_subject_ref,
)
from nex_cx.worker_leases import SqlAlchemyCxWorkerLeaseStore
from nex_cx.worker_lifecycle import (
    NOT_READY,
    READY,
    CxWorkerLifecycleController,
    CxWorkerLifecycleError,
    project_worker_readiness,
)
from nex_cx.worker_runtime import (
    CxCancellationToken,
    CxWorkerRuntimeError,
    CxWorkerRuntimePolicy,
    run_bounded_worker_batch,
)


NOW = "2026-09-23T04:00:00Z"
LATER = "2026-09-23T04:00:10Z"
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"


def _controller(
    store: InMemoryWorkerHeartbeatStore | None = None,
) -> CxWorkerLifecycleController:
    resolved_store = store or InMemoryWorkerHeartbeatStore()
    emitter = WorkerHeartbeatEmitter(
        service_id="nex-cx",
        worker_id="worker-a",
        worker_type="cx.processing.worker",
        store=resolved_store,
        started_at=NOW,
    )
    return CxWorkerLifecycleController(emitter=emitter, store=resolved_store)


def _stores() -> tuple[SqlAlchemyJobQueue, SqlAlchemyCxWorkerLeaseStore]:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE service_jobs (
                    job_id TEXT PRIMARY KEY, job_schema_version TEXT NOT NULL,
                    job_type TEXT NOT NULL, status TEXT NOT NULL,
                    trace_id TEXT NOT NULL, request_id TEXT NOT NULL,
                    subject_type TEXT NOT NULL, subject_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL, attempt_count INTEGER NOT NULL,
                    max_attempts INTEGER NOT NULL, retryable INTEGER NOT NULL,
                    links TEXT NOT NULL, payload TEXT NOT NULL, error TEXT,
                    replay_lineage TEXT, available_at TEXT NOT NULL,
                    locked_at TEXT, locked_by TEXT, started_at TEXT,
                    completed_at TEXT, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (job_type, idempotency_key)
                )
                """
            )
        )
    factory = build_session_factory(engine)
    return SqlAlchemyJobQueue(factory), SqlAlchemyCxWorkerLeaseStore(factory)


def _job(index: int) -> dict[str, Any]:
    return build_common_job(
        job_id=f"job-{index}",
        job_type="cx.document_processing",
        trace_id=TRACE_ID,
        request_id=f"09770000-0000-4000-8000-{index:012d}",
        subject_ref=build_subject_ref("cx.document", f"doc-{index}"),
        idempotency_key=f"idem-{index}",
        created_at=NOW,
        max_attempts=2,
    )


def test_lifecycle_emits_start_ready_busy_idle_and_readiness() -> None:
    lifecycle = _controller()
    lifecycle.starting(observed_at=NOW)
    assert lifecycle.readiness(checked_at=NOW)["reason_code"] == "worker_starting"
    lifecycle.idle(observed_at=NOW)
    assert lifecycle.readiness(checked_at=NOW)["readiness"] == READY
    lifecycle.busy(job_id="job-1", trace_id=TRACE_ID, observed_at=LATER)
    busy = lifecycle.readiness(checked_at=LATER)
    assert busy["status"] == BUSY
    assert busy["reason_code"] == "worker_busy"
    lifecycle.idle(observed_at=LATER)
    assert [item["status"] for item in lifecycle.emissions] == [
        STARTING,
        IDLE,
        BUSY,
        IDLE,
    ]


def test_graceful_shutdown_blocks_claims_and_finishes_stopped() -> None:
    lifecycle = _controller()
    lifecycle.starting(observed_at=NOW)
    lifecycle.idle(observed_at=NOW)
    stopping = lifecycle.request_shutdown(observed_at=LATER)
    assert stopping["status"] == STOPPING
    assert lifecycle.shutdown_requested is True
    assert lifecycle.can_claim is False
    assert lifecycle.idle(observed_at=LATER)["status"] == STOPPING
    with pytest.raises(CxWorkerLifecycleError) as blocked:
        lifecycle.busy(job_id="job", trace_id=TRACE_ID, observed_at=LATER)
    assert blocked.value.error_code == "cx.worker_lifecycle.shutdown_in_progress"
    assert lifecycle.stopped(observed_at=LATER)["status"] == STOPPED
    assert lifecycle.readiness(checked_at=LATER)["readiness"] == NOT_READY


def test_readiness_handles_missing_stale_error_and_starting() -> None:
    assert project_worker_readiness(None)["reason_code"] == "heartbeat_missing"
    lifecycle = _controller()
    lifecycle.starting(observed_at=NOW)
    stale = lifecycle.readiness(
        stale_after_seconds=5,
        checked_at="2026-09-23T04:00:06Z",
    )
    assert stale["reason_code"] == "heartbeat_stale"
    lifecycle.failed(error_code="cx.worker.failed", observed_at=LATER)
    failed = lifecycle.readiness(checked_at=LATER)
    assert failed["status"] == ERROR
    assert failed["reason_code"] == "worker_error"


def test_runtime_stops_before_second_claim_after_shutdown_request() -> None:
    queue, leases = _stores()
    queue.enqueue(_job(1))
    queue.enqueue(_job(2))
    lifecycle = _controller()

    def handler(
        execution: dict[str, Any],
        cancellation: CxCancellationToken,
    ) -> None:
        lifecycle.request_shutdown(observed_at=NOW)

    result = run_bounded_worker_batch(
        job_queue=queue,
        lease_store=leases,
        handler=handler,
        worker_id="worker-a",
        worker_type="cx.processing.worker",
        workload="document_processing",
        runtime_policy=CxWorkerRuntimePolicy(max_jobs=2),
        lifecycle=lifecycle,
        clock=lambda: NOW,
    )

    assert result["stop_reason"] == "SHUTDOWN"
    assert result["claimed_count"] == 1
    assert queue.get_job("job-2")["status"] == "QUEUED"
    assert lifecycle.readiness(checked_at=NOW)["status"] == STOPPED


def test_runtime_failure_emits_error_heartbeat() -> None:
    queue, leases = _stores()
    queue.enqueue(_job(1))
    lifecycle = _controller()

    def fail(
        execution: dict[str, Any],
        cancellation: CxCancellationToken,
    ) -> None:
        raise CxWorkerRuntimeError("cx.worker.typed", "typed")

    with pytest.raises(CxWorkerRuntimeError):
        run_bounded_worker_batch(
            job_queue=queue,
            lease_store=leases,
            handler=fail,
            worker_id="worker-a",
            worker_type="cx.processing.worker",
            workload="document_processing",
            lifecycle=lifecycle,
            clock=lambda: NOW,
        )
    assert lifecycle.readiness(checked_at=NOW)["status"] == ERROR


def test_runtime_failure_without_lifecycle_propagates_unchanged() -> None:
    queue, leases = _stores()
    queue.enqueue(_job(1))

    def fail(
        execution: dict[str, Any],
        cancellation: CxCancellationToken,
    ) -> None:
        raise CxWorkerRuntimeError("cx.worker.typed", "typed")

    with pytest.raises(CxWorkerRuntimeError) as failure:
        run_bounded_worker_batch(
            job_queue=queue,
            lease_store=leases,
            handler=fail,
            worker_id="worker-a",
            worker_type="cx.processing.worker",
            workload="document_processing",
            clock=lambda: NOW,
        )
    assert failure.value.error_code == "cx.worker.typed"


def test_lifecycle_validation_and_safe_emit_failure() -> None:
    first = InMemoryWorkerHeartbeatStore()
    second = InMemoryWorkerHeartbeatStore()
    emitter = WorkerHeartbeatEmitter(
        service_id="nex-cx",
        worker_id="worker-a",
        worker_type="cx.worker",
        store=first,
        started_at=NOW,
    )
    with pytest.raises(CxWorkerLifecycleError) as mismatch:
        CxWorkerLifecycleController(emitter=emitter, store=second)
    assert mismatch.value.error_code == "cx.worker_lifecycle.store_mismatch"

    class BrokenStore(InMemoryWorkerHeartbeatStore):
        def upsert_heartbeat(self, heartbeat: dict[str, Any]) -> dict[str, Any]:
            raise WorkerHeartbeatError(
                error_code="worker_heartbeat.store_unavailable",
                detail="offline",
                status_code=503,
            )

    broken = BrokenStore()
    broken_lifecycle = _controller(broken)
    result = broken_lifecycle.starting(observed_at=NOW)
    assert result["ok"] is False
    assert result["error_code"] == "worker_heartbeat.store_unavailable"
    with pytest.raises(CxWorkerLifecycleError) as blank:
        lifecycle = _controller()
        lifecycle.request_shutdown(reason_code=" ", observed_at=NOW)
    assert blank.value.error_code == "cx.worker_lifecycle.field_invalid"
    assert str(CxWorkerLifecycleError("code", "detail")) == "detail"
