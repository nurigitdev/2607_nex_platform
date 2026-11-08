from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    InMemoryJobQueue,
    build_common_job,
    build_job_error,
    build_subject_ref,
    issue_mock_service_token,
)
from nex_wa.app import create_wa_app

NOW = "2026-10-28T09:00:00Z"


def _environment() -> dict[str, str]:
    return {
        "NEX_PROFILE": "test",
        "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
        "NEX_WA_DATABASE_URL": "sqlite+pysqlite:///:memory:",
    }


def _persistence(queue: InMemoryJobQueue) -> SimpleNamespace:
    return SimpleNamespace(
        migration_readiness=lambda: {"name": "wa_migrations", "ok": True},
        work_evidence_repository=None,
        work_asset_repository=None,
        evidence_admission_service=None,
        job_queue=queue,
    )


def _client(queue: InMemoryJobQueue) -> TestClient:
    return TestClient(
        create_wa_app(
            environ=_environment(),
            persistence_builder=lambda **_: _persistence(queue),
        )
    )


def _headers() -> dict[str, str]:
    token = issue_mock_service_token(
        service_id="nex-ag",
        audience="nex-wa",
        scopes=(DEFAULT_SERVICE_SCOPE,),
    ).access_token
    return {"Authorization": f"Bearer {token}"}


def _dead_letter(queue: InMemoryJobQueue) -> dict:
    job = build_common_job(
        job_id="wa-job-dead-001",
        job_type="WA_EVIDENCE_INGEST",
        trace_id="a" * 32,
        request_id="request-dead-001",
        subject_ref=build_subject_ref("SERVICE", "nex-ae-api"),
        idempotency_key="wa-dead-001",
        created_at=NOW,
        max_attempts=1,
    )
    job["payload"] = {
        "tenant_id": "VO00",
        "source_ref": "private-source-ref",
        "private_body": "must-not-leak",
    }
    queue.enqueue(job)
    queue.start_job(job["job_id"], updated_at=NOW)
    return queue.retry_job(
        job["job_id"],
        error=build_job_error(
            error_code="WA_SOURCE_REJECTED",
            detail="private upstream detail must not leak",
            retryable=False,
            dead_lettered=True,
        ),
        failed_at=NOW,
    )


def test_wa_operator_replay_creates_new_job_and_keeps_source_immutable() -> None:
    queue = InMemoryJobQueue()
    source = _dead_letter(queue)
    response = _client(queue).post(
        f"/internal/v1/jobs/{source['job_id']}/replay",
        headers=_headers(),
        json={
            "replay_job_id": "wa-job-replay-001",
            "idempotency_key": "wa-replay-001",
            "requested_by": "operator-001",
            "reason": "source authority restored",
            "observed_at": "2026-10-28T09:01:00Z",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["job"]["job_id"] == "wa-job-replay-001"
    assert body["job"]["status"] == "QUEUED"
    assert body["replay"]["lineage"]["requested_by"] == "operator-001"
    assert body["replay"]["lineage"]["reason"] == "source authority restored"
    assert queue.get_job(source["job_id"]) == source
    assert queue.get_job("wa-job-replay-001")["payload"]["source_ref"] == (
        "private-source-ref"
    )
    assert "must-not-leak" not in response.text
    assert "private upstream detail" not in response.text


def test_wa_operator_replay_requires_dead_letter_reason_and_service_claim() -> None:
    queue = InMemoryJobQueue()
    source = _dead_letter(queue)
    client = _client(queue)
    path = f"/internal/v1/jobs/{source['job_id']}/replay"
    base = {
        "replay_job_id": "wa-job-replay-002",
        "idempotency_key": "wa-replay-002",
        "requested_by": "operator-001",
        "reason": "retry after repair",
    }

    assert client.post(path, json=base).status_code == 401
    missing_reason = client.post(
        path,
        headers=_headers(),
        json={key: value for key, value in base.items() if key != "reason"},
    )
    assert missing_reason.status_code == 422
    assert missing_reason.json()["error_code"] == "job_control.replay_payload_invalid"


def test_wa_operator_read_projection_omits_payload_and_error_detail() -> None:
    queue = InMemoryJobQueue()
    source = _dead_letter(queue)
    response = _client(queue).get(
        f"/internal/v1/jobs/{source['job_id']}",
        headers=_headers(),
    )
    assert response.status_code == 200
    assert "payload" not in response.json()["job"]
    assert "private upstream detail" not in response.text
    assert response.json()["controls"]["can_replay"] is True


def test_wa_app_without_persistence_does_not_expose_job_control() -> None:
    app = create_wa_app(
        environ={
            "NEX_PROFILE": "test",
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
        }
    )
    paths = {route.path for route in app.routes}
    assert "/internal/v1/jobs/{job_id}" not in paths
