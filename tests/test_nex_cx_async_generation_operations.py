from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from nex_runtime import (
    InMemoryJobQueue,
    JobQueueError,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
)

from nex_cx.async_generation_operations import (
    register_async_generation_operations_routes,
)
from nex_cx.generation_runtime import (
    GroundedGenerationRuntime,
    InMemoryGenerationAdmissionRepository,
)
from nex_cx.private_text_store import FileSystemCxPrivateTextStore


@dataclass
class ExecutionRepository:
    records: dict[str, dict] = field(default_factory=dict)

    def get(self, cx_generation_id, *, access_context):
        return deepcopy(self.records.get(cx_generation_id))

    def save(self, execution_record, *, access_context, private_output_metadata):
        stored = deepcopy(dict(execution_record))
        self.records[stored["cx_generation_id"]] = stored
        return stored


def _headers(subject="user-1"):
    token = issue_mock_service_token(service_id="nex-ae-api", audience="nex-cx")
    return {
        "Authorization": f"Bearer {token.access_token}",
        "X-Request-ID": "request-1",
        "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        "X-NEX-Tenant-ID": "tenant-1",
        "X-NEX-Subject-ID": subject,
        "Idempotency-Key": "idem-1",
    }


def _client(tmp_path, *, durable=True):
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    queue = InMemoryJobQueue()
    runtime = (
        GroundedGenerationRuntime(
            admission_repository=InMemoryGenerationAdmissionRepository(),
            execution_repository=ExecutionRepository(),
            private_output_store=FileSystemCxPrivateTextStore(tmp_path / "outputs"),
            clock=lambda: datetime(2026, 9, 24, 3, tzinfo=UTC),
        )
        if durable
        else None
    )
    register_async_generation_operations_routes(
        app,
        job_queue=queue,
        runtime=runtime,
        request_store=FileSystemCxPrivateTextStore(tmp_path / "requests"),
    )
    return TestClient(app), queue, runtime


def test_owner_can_admit_poll_and_idempotently_join(tmp_path) -> None:
    client, queue, _ = _client(tmp_path)
    first = client.post(
        "/api/v1/generation-jobs",
        json={"prompt": "private question"},
        headers=_headers(),
    )
    second = client.post(
        "/api/v1/generation-jobs",
        json={"prompt": "private question"},
        headers=_headers(),
    )
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["admission_status"] == "ENQUEUED"
    assert second.json()["admission_status"] == "JOINED"
    job_id = first.json()["job"]["job_id"]
    polled = client.get(f"/api/v1/generation-jobs/{job_id}", headers=_headers())
    assert polled.status_code == 200
    assert polled.json()["status"] == "QUEUED"
    assert len(queue.jobs) == 1


def test_cross_owner_poll_is_indistinguishable_from_missing(tmp_path) -> None:
    client, _, _ = _client(tmp_path)
    created = client.post(
        "/api/v1/generation-jobs", json={"prompt": "private"}, headers=_headers()
    )
    job_id = created.json()["job"]["job_id"]
    hidden = client.get(
        f"/api/v1/generation-jobs/{job_id}", headers=_headers("other")
    )
    missing = client.get(
        "/api/v1/generation-jobs/missing", headers=_headers()
    )
    assert hidden.status_code == missing.status_code == 404
    assert hidden.json() == missing.json()


def test_owner_cancels_queued_job_and_generation(tmp_path) -> None:
    client, queue, runtime = _client(tmp_path)
    created = client.post(
        "/api/v1/generation-jobs", json={"prompt": "private"}, headers=_headers()
    )
    job_id = created.json()["job"]["job_id"]
    cancelled = client.post(
        f"/api/v1/generation-jobs/{job_id}/cancel", headers=_headers()
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    assert queue.get_job(job_id)["status"] == "CANCELLED"
    assert next(iter(runtime.execution_repository.records.values()))["status"] == "FAILED"


def test_auth_runtime_and_invalid_request_fail_closed(tmp_path) -> None:
    client, _, _ = _client(tmp_path)
    assert client.post("/api/v1/generation-jobs", json={"prompt": "x"}).status_code == 401
    unavailable, _, _ = _client(tmp_path / "other", durable=False)
    response = unavailable.post(
        "/api/v1/generation-jobs", json={"prompt": "x"}, headers=_headers()
    )
    assert response.status_code == 503
    assert response.json()["retryable"] is True
    invalid = client.post(
        "/api/v1/generation-jobs",
        json={"prompt": "x", "api_key": "forbidden"},
        headers=_headers(),
    )
    assert invalid.status_code == 422


def test_cancel_missing_cross_owner_and_terminal_job(tmp_path) -> None:
    client, queue, _ = _client(tmp_path)
    assert client.post(
        "/api/v1/generation-jobs/missing/cancel", headers=_headers()
    ).status_code == 404
    created = client.post(
        "/api/v1/generation-jobs", json={"prompt": "private"}, headers=_headers()
    )
    job_id = created.json()["job"]["job_id"]
    assert client.post(
        f"/api/v1/generation-jobs/{job_id}/cancel", headers=_headers("other")
    ).status_code == 404
    queue.start_job(job_id)
    queue.complete_job(job_id)
    conflict = client.post(
        f"/api/v1/generation-jobs/{job_id}/cancel", headers=_headers()
    )
    assert conflict.status_code == 409


def test_get_cancel_auth_runtime_and_queue_failures(tmp_path, monkeypatch) -> None:
    client, queue, _ = _client(tmp_path)
    assert client.get("/api/v1/generation-jobs/missing").status_code == 401
    assert client.post("/api/v1/generation-jobs/missing/cancel").status_code == 401

    unavailable, _, _ = _client(tmp_path / "unavailable", durable=False)
    assert unavailable.post(
        "/api/v1/generation-jobs/missing/cancel", headers=_headers()
    ).status_code == 503

    def broken(job_id):
        raise JobQueueError("job.store_unavailable", "unavailable", 503)

    monkeypatch.setattr(queue, "get_job", broken)
    response = client.get("/api/v1/generation-jobs/job", headers=_headers())
    assert response.status_code == 503


def test_running_cancel_defers_generation_finalization_to_worker(tmp_path) -> None:
    client, queue, runtime = _client(tmp_path)
    created = client.post(
        "/api/v1/generation-jobs", json={"prompt": "private"}, headers=_headers()
    )
    job_id = created.json()["job"]["job_id"]
    queue.start_job(job_id)
    response = client.post(
        f"/api/v1/generation-jobs/{job_id}/cancel", headers=_headers()
    )
    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"
    assert runtime.execution_repository.records == {}


def test_cancel_fails_retryably_when_private_request_is_missing(tmp_path) -> None:
    client, _, _ = _client(tmp_path)
    created = client.post(
        "/api/v1/generation-jobs", json={"prompt": "private"}, headers=_headers()
    )
    for path in Path(tmp_path / "requests").rglob("*.utf8"):
        path.unlink()
    response = client.post(
        f"/api/v1/generation-jobs/{created.json()['job']['job_id']}/cancel",
        headers=_headers(),
    )
    assert response.status_code == 503
    assert response.json()["retryable"] is True


def test_malformed_job_is_hidden(tmp_path) -> None:
    client, queue, _ = _client(tmp_path)
    queue.jobs["malformed"] = {"job_id": "malformed"}
    response = client.get(
        "/api/v1/generation-jobs/malformed", headers=_headers()
    )
    assert response.status_code == 404


def test_terminal_replay_without_live_job_skips_job_event(
    tmp_path, monkeypatch
) -> None:
    from nex_cx import async_generation_operations as operations

    client, _, _ = _client(tmp_path)
    monkeypatch.setattr(
        operations,
        "admit_async_generation",
        lambda **kwargs: {
            "admission_status": "REPLAYED",
            "job": None,
            "generation": {"cx_generation_id": "generation-1"},
        },
    )

    response = client.post(
        "/api/v1/generation-jobs",
        json={"prompt": "private"},
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.json()["job"] is None


def test_terminal_postgres_replay_serializes_repository_datetimes(
    tmp_path, monkeypatch
) -> None:
    from nex_cx import async_generation_operations as operations

    client, _, _ = _client(tmp_path)
    replayed_at = datetime(2026, 9, 24, 4, tzinfo=UTC)
    monkeypatch.setattr(
        operations,
        "admit_async_generation",
        lambda **kwargs: {
            "admission_status": "REPLAYED",
            "job": None,
            "generation": {
                "cx_generation_id": "generation-1",
                "created_at": replayed_at,
                "updated_at": replayed_at,
            },
        },
    )

    response = client.post(
        "/api/v1/generation-jobs",
        json={"prompt": "private"},
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.json()["generation"]["created_at"] == (
        "2026-09-24T04:00:00+00:00"
    )
