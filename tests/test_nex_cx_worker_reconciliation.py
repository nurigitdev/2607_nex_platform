from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text

from nex_runtime import (
    ERROR,
    IDLE,
    InMemoryJobQueue,
    InMemoryWorkerHeartbeatStore,
    JobQueueError,
    SqlAlchemyJobQueue,
    WorkerHeartbeatEmitter,
    WorkerHeartbeatError,
    build_common_job,
    build_engine,
    build_session_factory,
    build_subject_ref,
)
from nex_cx.worker_leases import CxWorkerLeaseError, SqlAlchemyCxWorkerLeaseStore
from nex_cx.worker_reconciliation import (
    HEALTHY,
    MANUAL_REVIEW,
    RECOVER,
    WAIT_HEARTBEAT,
    WAIT_LEASE,
    CxWorkerReconciliationError,
    ExpiredWorkerLeaseFailure,
    apply_worker_reconciliation_plan,
    build_worker_reconciliation_plan,
)


NOW = "2026-09-23T05:00:00Z"
EXPIRED = "2026-09-23T05:02:01Z"
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"


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


def _job(
    index: int,
    *,
    job_type: str = "cx.document_processing",
    max_attempts: int = 3,
) -> dict[str, Any]:
    return build_common_job(
        job_id=f"job-{index}",
        job_type=job_type,
        trace_id=TRACE_ID,
        request_id=f"09780000-0000-4000-8000-{index:012d}",
        subject_ref=build_subject_ref("cx.document", f"doc-{index}"),
        idempotency_key=f"idem-{index}",
        created_at=NOW,
        max_attempts=max_attempts,
    )


def _claim(queue: SqlAlchemyJobQueue, job: dict[str, Any], worker_id: str) -> None:
    queue.enqueue(job)
    assert queue.claim_next_job(worker_id, updated_at=NOW) is not None


def _heartbeat(
    store: InMemoryWorkerHeartbeatStore,
    worker_id: str,
    *,
    status: str = IDLE,
    observed_at: str = NOW,
) -> None:
    emitter = WorkerHeartbeatEmitter(
        service_id="nex-cx",
        worker_id=worker_id,
        worker_type="cx.processing.worker",
        store=store,
        started_at=NOW,
    )
    emitter.emit(status=status, observed_at=observed_at)


@pytest.mark.parametrize(
    ("checked_at", "with_heartbeat", "expected_action"),
    [
        (NOW, True, HEALTHY),
        (NOW, False, WAIT_LEASE),
        (EXPIRED, True, WAIT_HEARTBEAT),
        (EXPIRED, False, RECOVER),
    ],
)
def test_reconciliation_requires_expired_lease_and_unavailable_heartbeat(
    checked_at: str,
    with_heartbeat: bool,
    expected_action: str,
) -> None:
    queue, leases = _stores()
    heartbeats = InMemoryWorkerHeartbeatStore()
    _claim(queue, _job(1), "worker-a")
    if with_heartbeat:
        _heartbeat(heartbeats, "worker-a", observed_at=checked_at)

    plan = build_worker_reconciliation_plan(
        job_queue=queue,
        lease_store=leases,
        heartbeat_store=heartbeats,
        observed_at=checked_at,
    )

    assert plan["entries"][0]["action"] == expected_action
    assert plan["recoverable_count"] == int(expected_action == RECOVER)


def test_terminal_or_stale_heartbeat_allows_recovery_after_lease_expiry() -> None:
    queue, leases = _stores()
    heartbeats = InMemoryWorkerHeartbeatStore()
    _claim(queue, _job(1), "worker-a")
    _heartbeat(heartbeats, "worker-a", status=ERROR, observed_at=EXPIRED)

    terminal = build_worker_reconciliation_plan(
        job_queue=queue,
        lease_store=leases,
        heartbeat_store=heartbeats,
        observed_at=EXPIRED,
    )
    assert terminal["entries"][0]["action"] == RECOVER

    _heartbeat(heartbeats, "worker-a", observed_at=NOW)
    stale = build_worker_reconciliation_plan(
        job_queue=queue,
        lease_store=leases,
        heartbeat_store=heartbeats,
        observed_at=EXPIRED,
        heartbeat_stale_after_seconds=60,
    )
    assert stale["entries"][0]["action"] == RECOVER


def test_applies_generic_recovery_idempotently_with_bounded_retry() -> None:
    queue, leases = _stores()
    _claim(queue, _job(1), "worker-a")
    plan = build_worker_reconciliation_plan(
        job_queue=queue,
        lease_store=leases,
        heartbeat_store=InMemoryWorkerHeartbeatStore(),
        observed_at=EXPIRED,
    )

    applied = apply_worker_reconciliation_plan(plan, job_queue=queue)
    repeated = apply_worker_reconciliation_plan(plan, job_queue=queue)

    assert applied["results"][0]["result"] == "RETRY_SCHEDULED"
    assert queue.get_job("job-1")["status"] == "QUEUED"
    assert repeated["results"][0]["result"] == "ALREADY_SETTLED"


def test_exhausted_recovery_dead_letters() -> None:
    queue, leases = _stores()
    _claim(queue, _job(1, max_attempts=1), "worker-a")
    plan = build_worker_reconciliation_plan(
        job_queue=queue,
        lease_store=leases,
        heartbeat_store=InMemoryWorkerHeartbeatStore(),
        observed_at=EXPIRED,
    )
    applied = apply_worker_reconciliation_plan(plan, job_queue=queue)
    assert applied["results"][0]["result"] == "DEAD_LETTERED"


def test_specialized_ingestion_recovery_fails_closed_without_handler() -> None:
    queue, leases = _stores()
    _claim(queue, _job(1, job_type="cx.document_ingestion"), "worker-a")
    plan = build_worker_reconciliation_plan(
        job_queue=queue,
        lease_store=leases,
        heartbeat_store=InMemoryWorkerHeartbeatStore(),
        observed_at=EXPIRED,
    )

    guarded = apply_worker_reconciliation_plan(plan, job_queue=queue)
    assert guarded["results"][0]["result"] == "HANDLER_REQUIRED"
    assert queue.get_job("job-1")["status"] == "RUNNING"

    handled = apply_worker_reconciliation_plan(
        plan,
        job_queue=queue,
        recovery_handlers={
            "cx.document_ingestion": lambda job, observed_at: {
                "status": "RETRY_SCHEDULED"
            }
        },
    )
    assert handled["results"][0] == {
        "job_id": "job-1",
        "job_type": "cx.document_ingestion",
        "result": "HANDLED",
        "action": "RETRY_SCHEDULED",
    }


def test_missing_durable_lease_requires_manual_review() -> None:
    queue, leases = _stores()
    queue.enqueue(_job(1))
    queue.start_job("job-1", updated_at=NOW)
    plan = build_worker_reconciliation_plan(
        job_queue=queue,
        lease_store=leases,
        heartbeat_store=InMemoryWorkerHeartbeatStore(),
        observed_at=EXPIRED,
    )
    assert plan["entries"][0]["action"] == MANUAL_REVIEW
    assert plan["manual_review_count"] == 1


def test_plan_and_dependency_failures_are_typed() -> None:
    with pytest.raises(CxWorkerReconciliationError) as invalid:
        apply_worker_reconciliation_plan({}, job_queue=InMemoryJobQueue())
    assert invalid.value.error_code == "cx.worker_reconciliation.plan_invalid"
    with pytest.raises(CxWorkerReconciliationError) as invalid_entries:
        apply_worker_reconciliation_plan(
            {
                "reconciliation_schema_version": "cx_worker_reconciliation_plan.v1",
                "observed_at": NOW,
                "entries": {},
            },
            job_queue=InMemoryJobQueue(),
        )
    assert invalid_entries.value.error_code == "cx.worker_reconciliation.plan_invalid"

    class BrokenQueue(InMemoryJobQueue):
        def list_jobs(self, **kwargs: Any) -> list[dict[str, Any]]:
            raise JobQueueError("job.store_unavailable", "offline", 503)

    queue, leases = _stores()
    with pytest.raises(CxWorkerReconciliationError) as unavailable:
        build_worker_reconciliation_plan(
            job_queue=BrokenQueue(),
            lease_store=leases,
            heartbeat_store=InMemoryWorkerHeartbeatStore(),
            observed_at=NOW,
        )
    assert unavailable.value.error_code == (
        "cx.worker_reconciliation.job_list_failed"
    )


def test_handler_and_heartbeat_failures_are_typed() -> None:
    queue, leases = _stores()
    _claim(queue, _job(1, job_type="cx.document_ingestion"), "worker-a")
    plan = build_worker_reconciliation_plan(
        job_queue=queue,
        lease_store=leases,
        heartbeat_store=InMemoryWorkerHeartbeatStore(),
        observed_at=EXPIRED,
    )

    def fail(job: dict[str, Any], observed_at: str) -> dict[str, Any]:
        raise RuntimeError("private")

    with pytest.raises(CxWorkerReconciliationError) as handler:
        apply_worker_reconciliation_plan(
            plan,
            job_queue=queue,
            recovery_handlers={"cx.document_ingestion": fail},
        )
    assert handler.value.error_code == "cx.worker_reconciliation.handler_failed"

    class BrokenHeartbeats(InMemoryWorkerHeartbeatStore):
        def get_heartbeat(self, service_id: str, worker_id: str) -> None:
            raise WorkerHeartbeatError(
                error_code="worker_heartbeat.store_unavailable",
                detail="offline",
                status_code=503,
            )

    with pytest.raises(CxWorkerReconciliationError) as heartbeat:
        build_worker_reconciliation_plan(
            job_queue=queue,
            lease_store=leases,
            heartbeat_store=BrokenHeartbeats(),
            observed_at=EXPIRED,
        )
    assert heartbeat.value.error_code == (
        "cx.worker_reconciliation.heartbeat_read_failed"
    )
    assert str(CxWorkerReconciliationError("code", "detail")) == "detail"
    assert ExpiredWorkerLeaseFailure().retryable is True


def test_apply_skips_non_recovery_entries_and_rejects_blank_observed_at() -> None:
    skipped = apply_worker_reconciliation_plan(
        {
            "reconciliation_schema_version": "cx_worker_reconciliation_plan.v1",
            "observed_at": NOW,
            "entries": ["invalid", {"action": HEALTHY}],
        },
        job_queue=InMemoryJobQueue(),
    )
    assert skipped["applied_count"] == 0
    with pytest.raises(CxWorkerReconciliationError) as blank:
        apply_worker_reconciliation_plan(
            {
                "reconciliation_schema_version": (
                    "cx_worker_reconciliation_plan.v1"
                ),
                "observed_at": " ",
                "entries": [],
            },
            job_queue=InMemoryJobQueue(),
        )
    assert blank.value.error_code == "cx.worker_reconciliation.field_invalid"


def test_apply_job_read_and_settlement_failures_are_typed() -> None:
    recover_plan = {
        "reconciliation_schema_version": "cx_worker_reconciliation_plan.v1",
        "observed_at": EXPIRED,
        "entries": [
            {
                "job_id": "job-1",
                "job_type": "cx.document_processing",
                "action": RECOVER,
            }
        ],
    }

    class ReadBrokenQueue(InMemoryJobQueue):
        def get_job(self, job_id: str) -> None:
            raise JobQueueError("job.store_unavailable", "offline", 503)

    with pytest.raises(CxWorkerReconciliationError) as read_failure:
        apply_worker_reconciliation_plan(
            recover_plan,
            job_queue=ReadBrokenQueue(),
        )
    assert read_failure.value.error_code == (
        "cx.worker_reconciliation.job_read_failed"
    )

    class SettlementBrokenQueue(InMemoryJobQueue):
        def retry_job(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            raise JobQueueError("job.store_unavailable", "offline", 503)

    queue = SettlementBrokenQueue()
    queue.enqueue(_job(1))
    queue.claim_next_job("worker-a", updated_at=NOW)
    with pytest.raises(CxWorkerReconciliationError) as settlement:
        apply_worker_reconciliation_plan(recover_plan, job_queue=queue)
    assert settlement.value.error_code == (
        "cx.worker_reconciliation.settlement_failed"
    )


def test_lease_read_failure_is_typed() -> None:
    queue, leases = _stores()
    _claim(queue, _job(1), "worker-a")

    class BrokenLeases:
        def inspect(self, *args: Any, **kwargs: Any) -> None:
            raise CxWorkerLeaseError(
                "cx.worker_lease.store_unavailable",
                "offline",
                503,
                True,
            )

    with pytest.raises(CxWorkerReconciliationError) as lease:
        build_worker_reconciliation_plan(
            job_queue=queue,
            lease_store=BrokenLeases(),
            heartbeat_store=InMemoryWorkerHeartbeatStore(),
            observed_at=EXPIRED,
        )
    assert lease.value.error_code == "cx.worker_reconciliation.lease_read_failed"
