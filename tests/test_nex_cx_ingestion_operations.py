from __future__ import annotations

from copy import deepcopy
from typing import Any

from fastapi.testclient import TestClient

from nex_runtime import (
    CX_INGESTION_LEASE_RECOVERED_EVENT,
    InMemoryJobQueue,
    InMemoryOperationalEventStore,
    JobQueueError,
    OperationalEventEmitter,
    SERVICE_SPECS,
    build_common_job,
    build_service_app,
    build_subject_ref,
    issue_mock_service_token,
)
from nex_cx.ingestion_operations import (
    CX_INGESTION_RECOVERY_SCHEMA_VERSION,
    IngestionOperationsError,
    _recovery_event_id,
    register_ingestion_operations_routes,
)
from nex_cx.ingestion_orchestration import build_ingestion_run, claim_ingestion_run
from nex_cx.ingestion_orchestration_repository import (
    InMemoryIngestionRunRepository,
    IngestionRunRepositoryError,
)
from nex_cx.ingestion_worker import CX_INGESTION_JOB_TYPE


NOW = "2026-09-21T00:00:00Z"
EXPIRED = "2026-09-21T00:00:01Z"
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "request-0928"


def auth_headers(
    *, tenant_id: str | None = None, subject_id: str | None = None
) -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-ag", audience="nex-cx")
    headers = {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }
    if tenant_id is not None:
        headers["X-NEX-Tenant-ID"] = tenant_id
    if subject_id is not None:
        headers["X-NEX-Subject-ID"] = subject_id
    return headers


def add_run_pair(
    queue: InMemoryJobQueue,
    repository: InMemoryIngestionRunRepository,
    *,
    suffix: str = "1",
    running: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    job = queue.enqueue(
        build_common_job(
            job_id=f"job-{suffix}",
            job_type=CX_INGESTION_JOB_TYPE,
            trace_id=TRACE_ID,
            request_id=REQUEST_ID,
            subject_ref=build_subject_ref("cx.document", f"document-{suffix}"),
            idempotency_key=f"upload-{suffix}",
            max_attempts=3,
            retryable=True,
            created_at=NOW,
        )
    )
    run = repository.create(
        build_ingestion_run(
            document_id=f"document-{suffix}",
            job_id=f"job-{suffix}",
            idempotency_key=f"upload-{suffix}",
            tenant_ref={"type": "oa.tenant", "id": "tenant-a"},
            owner_subject_ref={"type": "oa.user", "id": "user-a"},
            trace_id=TRACE_ID,
            request_id=REQUEST_ID,
            created_at=NOW,
        )
    )
    if running:
        job = queue.start_job(job["job_id"], updated_at=NOW)
        run = repository.save(
            claim_ingestion_run(
                run,
                worker_id="worker-expired",
                lease_expires_at=EXPIRED,
                observed_at=NOW,
            ),
            expected_checkpoint_version=0,
        )
    return job, run


def build_client(
    *,
    queue: InMemoryJobQueue | None = None,
    repository: InMemoryIngestionRunRepository | None = None,
    emitter: OperationalEventEmitter | None = None,
) -> tuple[
    TestClient,
    InMemoryJobQueue,
    InMemoryIngestionRunRepository,
    InMemoryOperationalEventStore | None,
]:
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    selected_queue = queue or InMemoryJobQueue()
    selected_repository = repository or InMemoryIngestionRunRepository()
    event_store = None
    if emitter is None:
        event_store = InMemoryOperationalEventStore()
        emitter = OperationalEventEmitter(service_id="nex-cx", store=event_store)
    register_ingestion_operations_routes(
        app,
        job_queue=selected_queue,
        run_repository=selected_repository,
        event_emitter=emitter,
    )
    return TestClient(app), selected_queue, selected_repository, event_store


def test_owner_scoped_detail_and_document_history_hide_cross_owner() -> None:
    client, queue, repository, _ = build_client()
    _, run = add_run_pair(queue, repository)
    owner_headers = auth_headers(tenant_id="tenant-a", subject_id="user-a")

    detail = client.get(
        f"/api/v1/ingestion-runs/{run['run_id']}", headers=owner_headers
    )
    history = client.get(
        "/api/v1/documents/document-1/ingestion-runs", headers=owner_headers
    )
    denied = client.get(
        f"/api/v1/ingestion-runs/{run['run_id']}",
        headers=auth_headers(tenant_id="tenant-a", subject_id="user-b"),
    )
    hidden_history = client.get(
        "/api/v1/documents/document-1/ingestion-runs",
        headers=auth_headers(tenant_id="tenant-a", subject_id="user-b"),
    )

    assert detail.status_code == 200
    assert detail.json()["run_id"] == run["run_id"]
    assert history.json()["run_count"] == 1
    assert denied.status_code == 404
    assert denied.json()["error_code"] == "cx.ingestion_run.not_found"
    assert hidden_history.json()["runs"] == []
    assert client.get(f"/api/v1/ingestion-runs/{run['run_id']}").status_code == 401
    assert (
        client.get("/api/v1/documents/document-1/ingestion-runs").status_code
        == 401
    )


def test_internal_restart_plan_is_protected_read_only_and_bounded() -> None:
    client, queue, repository, _ = build_client()
    add_run_pair(queue, repository)

    assert client.get("/internal/v1/ingestion/restart-plan").status_code == 401
    invalid = client.get(
        "/internal/v1/ingestion/restart-plan?limit=invalid",
        headers=auth_headers(),
    )
    response = client.get(
        "/internal/v1/ingestion/restart-plan?limit=1",
        headers=auth_headers(),
    )

    assert invalid.status_code == 422
    assert invalid.json()["error_code"] == "cx.ingestion_restart.limit_invalid"
    assert response.status_code == 200
    assert response.json()["job_count"] == 1
    assert response.json()["mutation_performed"] is False
    assert repository.find_by_job_id("job-1")["checkpoint_version"] == 0


def test_expired_lease_recovery_emits_safe_operational_event() -> None:
    client, queue, repository, event_store = build_client()
    add_run_pair(queue, repository, running=True)

    response = client.post(
        "/internal/v1/ingestion/jobs/job-1/recover-expired-lease",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["recovery_schema_version"] == CX_INGESTION_RECOVERY_SCHEMA_VERSION
    assert payload["action"] == "RECOVER_EXPIRED_LEASE"
    assert payload["result"]["recovered"] is True
    assert payload["result"]["status"] == "RETRY_SCHEDULED"
    assert payload["observability"]["ok"] is True
    assert event_store is not None
    events = event_store.list_events(event_type=CX_INGESTION_LEASE_RECOVERED_EVENT)
    assert len(events) == 1
    assert events[0]["subject_ref"] == {"type": "job", "id": "job-1"}
    assert events[0]["details"]["checkpoint_version"] == 2
    serialized = str(events[0]).lower()
    assert "source_text" not in serialized
    assert "payload" not in serialized
    assert "authorization" not in serialized


class ExplodingEventStore:
    def append(self, event: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("event store unavailable")


def test_recovery_succeeds_when_observability_store_is_unavailable() -> None:
    emitter = OperationalEventEmitter(service_id="nex-cx", store=ExplodingEventStore())
    client, queue, repository, _ = build_client(emitter=emitter)
    add_run_pair(queue, repository, running=True)

    response = client.post(
        "/internal/v1/ingestion/jobs/job-1/recover-expired-lease",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert response.json()["observability"] == {
        "ok": False,
        "error_code": "operational_event.emit_failed",
        "detail": "operational event emission failed",
        "status_code": 503,
    }


def test_recovery_rejects_missing_and_non_running_jobs() -> None:
    client, queue, repository, _ = build_client()
    add_run_pair(queue, repository)

    missing = client.post(
        "/internal/v1/ingestion/jobs/missing/recover-expired-lease",
        headers=auth_headers(),
    )
    not_running = client.post(
        "/internal/v1/ingestion/jobs/job-1/recover-expired-lease",
        headers=auth_headers(),
    )

    assert missing.status_code == 404
    assert missing.json()["error_code"] == "cx.ingestion_worker.job_not_found"
    assert not_running.status_code == 409
    assert not_running.json()["error_code"] == "cx.ingestion_worker.job_not_running"
    assert (
        client.post(
            "/internal/v1/ingestion/jobs/job-1/recover-expired-lease"
        ).status_code
        == 401
    )


class FailingQueue(InMemoryJobQueue):
    def list_jobs(self, **_: object) -> list[dict[str, Any]]:
        raise JobQueueError("queue.unavailable", "queue unavailable", 503)


class FailingRepository(InMemoryIngestionRunRepository):
    def get(self, *args: object, **kwargs: object) -> dict[str, Any] | None:
        raise IngestionRunRepositoryError(
            "repository.unavailable", "repository unavailable", 503
        )

    def list_for_document(
        self, *args: object, **kwargs: object
    ) -> list[dict[str, Any]]:
        raise IngestionRunRepositoryError(
            "repository.unavailable", "repository unavailable", 503
        )


def test_dependency_errors_are_safe_problem_responses() -> None:
    restart_client, _, _, _ = build_client(queue=FailingQueue())
    restart = restart_client.get(
        "/internal/v1/ingestion/restart-plan", headers=auth_headers()
    )
    detail_client, _, _, _ = build_client(repository=FailingRepository())
    detail = detail_client.get(
        "/api/v1/ingestion-runs/run-1",
        headers=auth_headers(tenant_id="tenant-a", subject_id="user-a"),
    )
    history = detail_client.get(
        "/api/v1/documents/document-1/ingestion-runs",
        headers=auth_headers(tenant_id="tenant-a", subject_id="user-a"),
    )

    assert restart.status_code == 503
    assert restart.json()["retryable"] is True
    assert detail.status_code == 503
    assert detail.json()["error_code"] == "cx.ingestion_read_model.repository_unavailable"
    assert history.status_code == 503


def test_operations_helpers_are_deterministic() -> None:
    first = _recovery_event_id(job_id="job-1", checkpoint_version=2)
    second = _recovery_event_id(job_id="job-1", checkpoint_version=2)
    assert first == second
    assert first != _recovery_event_id(job_id="job-1", checkpoint_version=3)
    assert str(IngestionOperationsError("code", "safe detail")) == "safe detail"
