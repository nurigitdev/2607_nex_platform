from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from nex_runtime import (
    CX_WORKER_CANCELLATION_REQUESTED_EVENT,
    CX_WORKER_RECONCILIATION_APPLIED_EVENT,
    IDLE,
    InMemoryJobQueue,
    InMemoryOperationalEventStore,
    InMemoryWorkerHeartbeatStore,
    JobQueueError,
    OperationalEventEmitter,
    PERSISTENCE_MODE_MEMORY,
    PERSISTENCE_MODE_POSTGRES,
    SERVICE_SPECS,
    SqlAlchemyJobQueue,
    WorkerHeartbeatEmitter,
    WorkerHeartbeatError,
    build_common_job,
    build_job_error,
    build_service_app,
    build_session_factory,
    build_subject_ref,
    issue_mock_service_token,
)
from nex_cx.main import build_cx_worker_lease_store
from nex_cx.worker_leases import SqlAlchemyCxWorkerLeaseStore
from nex_cx.worker_operations import (
    CX_WORKER_OPERATIONS_SCHEMA_VERSION,
    CxWorkerOperationsError,
    _operation_event_id,
    register_worker_operations_routes,
)


NOW = "2026-09-23T06:00:00Z"
EXPIRED = "2026-09-23T06:02:01Z"
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"


def _headers() -> dict[str, str]:
    token = issue_mock_service_token(service_id="nex-ag", audience="nex-cx")
    return {
        "Authorization": f"Bearer {token.access_token}",
        "X-Request-ID": "request-0979",
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def _job(
    index: int,
    *,
    max_attempts: int = 3,
    job_type: str = "cx.document_processing",
) -> dict[str, Any]:
    return build_common_job(
        job_id=f"job-{index}",
        job_type=job_type,
        trace_id=TRACE_ID,
        request_id=f"09790000-0000-4000-8000-{index:012d}",
        subject_ref=build_subject_ref("cx.document", f"document-{index}"),
        idempotency_key=f"worker-operation-{index}",
        created_at=NOW,
        max_attempts=max_attempts,
    )


def _sql_stores() -> tuple[SqlAlchemyJobQueue, SqlAlchemyCxWorkerLeaseStore]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        future=True,
        poolclass=StaticPool,
    )
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


def _client(
    *,
    queue=None,
    heartbeats=None,
    leases=None,
    emitter=None,
    recovery_handlers=None,
):
    selected_queue = queue or InMemoryJobQueue()
    selected_heartbeats = heartbeats or InMemoryWorkerHeartbeatStore()
    event_store = None
    if emitter is None:
        event_store = InMemoryOperationalEventStore()
        emitter = OperationalEventEmitter(service_id="nex-cx", store=event_store)
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    register_worker_operations_routes(
        app,
        job_queue=selected_queue,
        heartbeat_store=selected_heartbeats,
        lease_store=leases,
        recovery_handlers=recovery_handlers,
        event_emitter=emitter,
    )
    return TestClient(app), selected_queue, selected_heartbeats, event_store


def test_readiness_route_is_protected_and_reports_missing_or_ready() -> None:
    client, _, heartbeats, _ = _client()

    assert (
        client.get("/internal/v1/workers/worker-a/readiness").status_code == 401
    )
    missing = client.get(
        "/internal/v1/workers/worker-a/readiness",
        headers=_headers(),
    )
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    WorkerHeartbeatEmitter(
        service_id="nex-cx",
        worker_id="worker-a",
        worker_type="cx.processing.worker",
        store=heartbeats,
        started_at=now,
    ).emit(status=IDLE, observed_at=now)
    ready = client.get(
        "/internal/v1/workers/worker-a/readiness",
        headers=_headers(),
    )
    invalid = client.get(
        "/internal/v1/workers/worker-a/readiness?stale_after_seconds=0",
        headers=_headers(),
    )

    assert missing.json()["reason_code"] == "heartbeat_missing"
    assert ready.json()["readiness"] == "READY"
    assert invalid.status_code == 422


def test_worker_operation_mutations_and_lists_are_protected() -> None:
    client, _, _, _ = _client()

    assert client.get("/internal/v1/workers/reconciliation-plan").status_code == 401
    assert client.post("/internal/v1/workers/reconcile").status_code == 401
    assert (
        client.post("/internal/v1/workers/jobs/job-1/cancel").status_code == 401
    )
    assert client.get("/internal/v1/workers/dead-letters").status_code == 401


def test_cancel_is_idempotent_observed_and_raw_safe() -> None:
    client, queue, _, event_store = _client()
    queue.enqueue(_job(1))

    first = client.post(
        "/internal/v1/workers/jobs/job-1/cancel",
        headers=_headers(),
    )
    repeated = client.post(
        "/internal/v1/workers/jobs/job-1/cancel",
        headers=_headers(),
    )
    missing = client.post(
        "/internal/v1/workers/jobs/missing/cancel",
        headers=_headers(),
    )

    assert first.status_code == 200
    assert first.json()["worker_operations_schema_version"] == (
        CX_WORKER_OPERATIONS_SCHEMA_VERSION
    )
    assert first.json()["result"]["status"] == "CANCELLED"
    assert first.json()["result"]["already_cancelled"] is False
    assert repeated.json()["result"]["already_cancelled"] is True
    assert missing.status_code == 404
    assert event_store is not None
    events = event_store.list_events(
        event_type=CX_WORKER_CANCELLATION_REQUESTED_EVENT
    )
    assert len(events) == 2
    assert events[0]["details"]["job_type"] == "cx.document_processing"
    assert "payload" not in str(events).lower()


def test_dead_letter_projection_is_bounded_and_excludes_plain_failures() -> None:
    client, queue, _, _ = _client()
    for index in (1, 2):
        queue.enqueue(_job(index))
        queue.start_job(f"job-{index}", updated_at=NOW)
    queue.dead_letter_job(
        "job-1",
        error=build_job_error(
            error_code="cx.worker.poison",
            detail="safe",
            retryable=False,
        ),
        failed_at=EXPIRED,
    )
    queue.fail_job("job-2", updated_at=EXPIRED)

    response = client.get(
        "/internal/v1/workers/dead-letters?limit=1",
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.json()["dead_letter_count"] == 1
    assert response.json()["dead_letters"][0] == {
        "job_id": "job-1",
        "job_type": "cx.document_processing",
        "status": "FAILED",
        "attempt_count": 1,
        "max_attempts": 3,
        "error_code": "cx.worker.poison",
        "dead_lettered": True,
        "failed_at": EXPIRED,
    }


def test_reconciliation_plan_and_apply_use_durable_lease_and_emit_event() -> None:
    queue, leases = _sql_stores()
    queue.enqueue(_job(1))
    assert queue.claim_next_job("worker-a", updated_at=NOW) is not None
    client, _, _, event_store = _client(queue=queue, leases=leases)

    plan_response = client.get(
        "/internal/v1/workers/reconciliation-plan",
        headers=_headers(),
        params={"observed_at": EXPIRED},
    )
    apply_response = client.post(
        "/internal/v1/workers/reconcile",
        headers=_headers(),
        params={"observed_at": EXPIRED},
    )

    assert plan_response.status_code == 200
    assert plan_response.json()["recoverable_count"] == 1
    assert apply_response.status_code == 200
    assert apply_response.json()["result"]["results"][0]["result"] == (
        "RETRY_SCHEDULED"
    )
    assert queue.get_job("job-1")["status"] == "QUEUED"
    assert event_store is not None
    events = event_store.list_events(
        event_type=CX_WORKER_RECONCILIATION_APPLIED_EVENT
    )
    assert len(events) == 1
    assert events[0]["details"]["applied_count"] == 1


def test_empty_reconciliation_uses_current_time_and_info_observability() -> None:
    queue, leases = _sql_stores()
    client, _, _, event_store = _client(queue=queue, leases=leases)

    response = client.post(
        "/internal/v1/workers/reconcile",
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.json()["result"]["applied_count"] == 0
    assert event_store is not None
    event = event_store.list_events(
        event_type=CX_WORKER_RECONCILIATION_APPLIED_EVENT
    )[0]
    assert event["severity"] == "INFO"


def test_reconciliation_handler_failure_returns_safe_problem() -> None:
    queue, leases = _sql_stores()
    queue.enqueue(_job(1, job_type="cx.document_ingestion"))
    assert queue.claim_next_job("worker-a", updated_at=NOW) is not None

    def fail(job: dict[str, Any], observed_at: str):
        raise RuntimeError("private provider detail")

    client, _, _, _ = _client(
        queue=queue,
        leases=leases,
        recovery_handlers={"cx.document_ingestion": fail},
    )
    response = client.post(
        "/internal/v1/workers/reconcile",
        headers=_headers(),
        params={"observed_at": EXPIRED},
    )

    assert response.status_code == 500
    assert response.json()["error_code"] == (
        "cx.worker_reconciliation.handler_failed"
    )
    assert "private provider detail" not in str(response.json()).lower()


def test_reconciliation_fails_closed_without_postgres_or_with_bad_time() -> None:
    memory_client, _, _, _ = _client()
    unavailable = memory_client.get(
        "/internal/v1/workers/reconciliation-plan",
        headers=_headers(),
    )
    unavailable_apply = memory_client.post(
        "/internal/v1/workers/reconcile",
        headers=_headers(),
    )
    queue, leases = _sql_stores()
    queue.enqueue(_job(1))
    assert queue.claim_next_job("worker-a", updated_at=NOW) is not None
    sql_client, _, _, _ = _client(queue=queue, leases=leases)
    invalid = sql_client.get(
        "/internal/v1/workers/reconciliation-plan",
        headers=_headers(),
        params={"observed_at": "not-a-time"},
    )

    assert unavailable.status_code == 503
    assert unavailable.json()["error_code"] == (
        "cx.worker_operations.postgres_required"
    )
    assert unavailable_apply.status_code == 503
    assert invalid.status_code == 422
    assert invalid.json()["error_code"] == (
        "cx.worker_reconciliation.lease_read_failed"
    )


def test_dependency_failures_return_safe_problem_details() -> None:
    class BrokenHeartbeats(InMemoryWorkerHeartbeatStore):
        def get_heartbeat(self, service_id: str, worker_id: str):
            raise WorkerHeartbeatError(
                error_code="worker_heartbeat.store_unavailable",
                detail="heartbeat unavailable",
                status_code=503,
            )

    class BrokenQueue(InMemoryJobQueue):
        def list_jobs(self, **kwargs: Any):
            raise JobQueueError("job.store_unavailable", "queue unavailable", 503)

    heartbeat_client, _, _, _ = _client(heartbeats=BrokenHeartbeats())
    queue_client, _, _, _ = _client(queue=BrokenQueue())

    readiness = heartbeat_client.get(
        "/internal/v1/workers/worker-a/readiness",
        headers=_headers(),
    )
    dead_letters = queue_client.get(
        "/internal/v1/workers/dead-letters",
        headers=_headers(),
    )

    assert readiness.status_code == 503
    assert readiness.json()["retryable"] is True
    assert dead_letters.status_code == 503
    assert dead_letters.json()["error_code"] == (
        "cx.worker_operations.dead_letter_read_failed"
    )


def test_observability_failure_does_not_rollback_cancellation() -> None:
    class ExplodingEventStore:
        def append(self, event: dict[str, Any]):
            raise RuntimeError("offline")

    queue = InMemoryJobQueue()
    queue.enqueue(_job(1))
    emitter = OperationalEventEmitter(
        service_id="nex-cx",
        store=ExplodingEventStore(),
    )
    client, _, _, _ = _client(queue=queue, emitter=emitter)

    response = client.post(
        "/internal/v1/workers/jobs/job-1/cancel",
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.json()["observability"]["ok"] is False
    assert queue.get_job("job-1")["status"] == "CANCELLED"


def test_helpers_and_main_dependency_builder_are_deterministic() -> None:
    first = _operation_event_id("cancel", "job-1", NOW)
    assert first == _operation_event_id("cancel", "job-1", NOW)
    assert first != _operation_event_id("cancel", "job-2", NOW)
    assert str(CxWorkerOperationsError("code", "safe")) == "safe"

    memory = SimpleNamespace(
        mode=PERSISTENCE_MODE_MEMORY,
        worker_session_factory=None,
    )
    assert build_cx_worker_lease_store(memory) is None
    _, leases = _sql_stores()
    postgres = SimpleNamespace(
        mode=PERSISTENCE_MODE_POSTGRES,
        worker_session_factory=leases._session_factory,
    )
    assert isinstance(
        build_cx_worker_lease_store(postgres),
        SqlAlchemyCxWorkerLeaseStore,
    )
