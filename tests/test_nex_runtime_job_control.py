from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from nex_runtime import (
    CANCELLED,
    FAILED,
    QUEUED,
    RUNNING,
    SERVICE_JOB_CONTROL_SCHEMA_VERSION,
    SERVICE_SPECS,
    SUCCEEDED,
    InMemoryJobQueue,
    JobRetryPolicy,
    build_common_job,
    build_job_error,
    build_service_app,
    build_service_job_control_response,
    build_subject_ref,
    issue_mock_service_token,
    project_service_job_control_job,
    register_service_job_control_routes,
)


NOW = "2026-08-05T00:00:00Z"
LATER = "2026-08-05T00:00:01Z"
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


def sample_job(**overrides: Any) -> dict[str, Any]:
    job = build_common_job(
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
    return {**job, **overrides}


def build_client(
    queue: InMemoryJobQueue,
    *,
    service_id: str = "nex-cx",
    retry_policy: JobRetryPolicy | None = None,
) -> TestClient:
    app = build_service_app(SERVICE_SPECS[service_id])
    register_service_job_control_routes(
        app,
        service_id=service_id,
        job_queue=queue,
        retry_policy=retry_policy,
    )
    return TestClient(app)


def auth_headers(*, audience: str = "nex-cx", service_id: str = "nex-ag") -> dict[str, str]:
    issued = issue_mock_service_token(service_id=service_id, audience=audience)
    return {"Authorization": f"Bearer {issued.access_token}"}


def test_project_service_job_control_job_omits_payload_and_returns_copies() -> None:
    job = sample_job(payload={"storage_path": "/data/nex-platform/cx/source-files/private.pdf"})

    projected = project_service_job_control_job(service_id="nex-cx", job=job)
    response = build_service_job_control_response(
        service_id="nex-cx",
        action="read",
        job=job,
    )
    projected["subject_ref"]["id"] = "mutated"

    assert "payload" not in projected
    assert job["subject_ref"]["id"] == "doc-001"
    assert response["job_control_schema_version"] == SERVICE_JOB_CONTROL_SCHEMA_VERSION
    assert response["controls"] == {
        "can_cancel": True,
        "can_retry": False,
        "can_replay": False,
        "terminal": False,
        "dead_lettered": False,
        "allowed_actions": ["read", "cancel"],
    }


def test_service_job_control_gets_job_and_requires_matching_service_claim() -> None:
    queue = InMemoryJobQueue()
    queue.enqueue(sample_job())
    client = build_client(queue)

    response = client.get("/internal/v1/jobs/job-001", headers=auth_headers())
    missing_auth = client.get("/internal/v1/jobs/job-001")
    wrong_audience = client.get(
        "/internal/v1/jobs/job-001",
        headers=auth_headers(audience="nex-ae-api"),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "read"
    assert payload["job"]["service_id"] == "nex-cx"
    assert payload["job"]["status"] == QUEUED
    assert payload["controls"]["allowed_actions"] == ["read", "cancel"]
    assert missing_auth.status_code == 401
    assert missing_auth.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"
    assert wrong_audience.status_code == 401
    assert wrong_audience.json()["error_code"] == "TOKEN_AUDIENCE_INVALID"


def test_service_job_control_reports_missing_job() -> None:
    client = build_client(InMemoryJobQueue())

    response = client.get("/internal/v1/jobs/missing", headers=auth_headers())

    assert response.status_code == 404
    assert response.json()["error_code"] == "job.not_found"


def test_service_job_control_cancels_active_jobs_and_rejects_terminal_jobs() -> None:
    queue = InMemoryJobQueue()
    queue.enqueue(sample_job(job_id="queued", idempotency_key="queued"))
    queue.enqueue(sample_job(job_id="done", idempotency_key="done"))
    queue.start_job("done", updated_at=NOW)
    queue.complete_job("done", updated_at=LATER)
    client = build_client(queue)

    cancelled = client.post(
        "/internal/v1/jobs/queued/cancel",
        json={"observed_at": LATER},
        headers=auth_headers(),
    )
    invalid = client.post(
        "/internal/v1/jobs/done/cancel",
        json={"observed_at": LATER},
        headers=auth_headers(),
    )
    bad_timestamp = client.post(
        "/internal/v1/jobs/queued/cancel",
        json={"observed_at": ""},
        headers=auth_headers(),
    )

    assert cancelled.status_code == 200
    assert cancelled.json()["job"]["status"] == CANCELLED
    assert cancelled.json()["controls"]["terminal"] is True
    assert queue.get_job("queued")["updated_at"] == LATER
    assert invalid.status_code == 409
    assert invalid.json()["error_code"] == "job.transition_invalid"
    assert bad_timestamp.status_code == 422
    assert bad_timestamp.json()["error_code"] == "job_control.observed_at_invalid"


def test_service_job_control_cancel_and_retry_require_service_claim() -> None:
    queue = InMemoryJobQueue()
    queue.enqueue(sample_job())
    queue.start_job("job-001", updated_at=NOW)
    client = build_client(queue)

    cancel = client.post("/internal/v1/jobs/job-001/cancel")
    retry = client.post("/internal/v1/jobs/job-001/retry")

    assert cancel.status_code == 401
    assert cancel.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"
    assert retry.status_code == 401
    assert retry.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"


def test_service_job_control_retries_running_jobs_with_policy_backoff() -> None:
    queue = InMemoryJobQueue()
    queue.enqueue(sample_job(max_attempts=3))
    queue.start_job("job-001", updated_at=NOW)
    client = build_client(
        queue,
        retry_policy=JobRetryPolicy(
            initial_delay_seconds=5,
            max_delay_seconds=30,
            backoff_multiplier=2,
        ),
    )

    response = client.post(
        "/internal/v1/jobs/job-001/retry",
        json={
            "error_code": "cx.processing_step_failed",
            "detail": "Document processing step failed.",
            "observed_at": NOW,
        },
        headers=auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "retry"
    assert payload["job"]["status"] == QUEUED
    assert payload["job"]["error"]["error_code"] == "cx.processing_step_failed"
    assert payload["job"]["available_at"] == "2026-08-05T00:00:05Z"
    assert payload["controls"]["allowed_actions"] == ["read", "cancel"]


def test_service_job_control_retries_exhausted_running_jobs_to_dead_letter() -> None:
    queue = InMemoryJobQueue()
    queue.enqueue(sample_job(max_attempts=1))
    queue.start_job("job-001", updated_at=NOW)
    client = build_client(queue)

    response = client.post(
        "/internal/v1/jobs/job-001/retry",
        json={"observed_at": LATER},
        headers=auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["job"]["status"] == FAILED
    assert payload["job"]["retryable"] is False
    assert payload["job"]["error"]["dead_lettered"] is True
    assert payload["controls"]["dead_lettered"] is True
    assert payload["controls"]["can_replay"] is True
    assert payload["controls"]["allowed_actions"] == ["read", "replay"]


def test_service_job_control_replays_dead_lettered_job_as_new_queued_job() -> None:
    queue = InMemoryJobQueue()
    queue.enqueue(
        sample_job(
            max_attempts=1,
            payload={"source_file_id": "source-001"},
        )
    )
    queue.start_job("job-001", updated_at=NOW)
    source = queue.retry_job(
        "job-001",
        error=build_job_error(
            error_code="cx.processing_step_failed",
            detail="Private parser detail must stay off replay response.",
            retryable=False,
            dead_lettered=True,
        ),
        failed_at=LATER,
    )
    client = build_client(queue)

    response = client.post(
        "/internal/v1/jobs/job-001/replay",
        json={
            "replay_job_id": "job-001-replay-001",
            "idempotency_key": "idem-001-replay-001",
            "requested_by": "operator-001",
            "reason": "fixed parser config",
            "observed_at": "2026-08-05T00:00:02Z",
        },
        headers=auth_headers(),
    )
    duplicate = client.post(
        "/internal/v1/jobs/job-001/replay",
        json={
            "replay_job_id": "job-001-replay-duplicate",
            "idempotency_key": "idem-001-replay-001",
            "requested_by": "operator-001",
            "reason": "fixed parser config",
            "observed_at": "2026-08-05T00:00:02Z",
        },
        headers=auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "replay"
    assert payload["job"]["job_id"] == "job-001-replay-001"
    assert payload["job"]["status"] == QUEUED
    assert payload["job"]["attempt_count"] == 0
    assert payload["job"]["retryable"] is True
    assert payload["controls"]["allowed_actions"] == ["read", "cancel"]
    assert payload["replay"]["source_job_id"] == source["job_id"]
    assert payload["replay"]["replay_job_id"] == "job-001-replay-001"
    assert payload["replay"]["source_job"] == {
        "service_id": "nex-cx",
        "job_id": "job-001",
        "job_type": "cx.document_processing",
        "status": FAILED,
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "subject_ref": {"type": "cx.document", "id": "doc-001"},
        "attempt_count": 1,
        "max_attempts": 1,
        "retryable": False,
        "source_error_code": "cx.processing_step_failed",
        "dead_lettered": True,
    }
    assert payload["replay"]["lineage"]["reason"] == "fixed parser config"
    assert "payload" not in str(payload)
    assert "Private parser detail" not in str(payload)
    assert queue.get_job("job-001")["status"] == FAILED
    assert queue.get_job("job-001-replay-001")["payload"] == {
        "source_file_id": "source-001"
    }
    assert duplicate.status_code == 200
    assert duplicate.json()["job"]["job_id"] == "job-001-replay-001"


def test_service_job_control_replay_requires_dead_letter_and_valid_payload() -> None:
    queue = InMemoryJobQueue()
    queue.enqueue(sample_job(job_id="queued", idempotency_key="queued"))
    queue.enqueue(sample_job(job_id="failed", idempotency_key="failed"))
    failed = queue.fail_job(
        queue.start_job("failed", updated_at=NOW)["job_id"],
        updated_at=LATER,
    )
    queue.jobs["failed"] = {
        **failed,
        "retryable": False,
        "error": build_job_error(
            error_code="cx.failed",
            detail="failed without dead-letter",
            retryable=False,
            dead_lettered=False,
        ),
    }
    client = build_client(queue)
    valid_payload = {
        "replay_job_id": "job-replay-001",
        "idempotency_key": "idem-replay-001",
        "requested_by": "operator-001",
        "reason": "retry",
    }

    missing_auth = client.post("/internal/v1/jobs/queued/replay", json=valid_payload)
    missing_job = client.post(
        "/internal/v1/jobs/missing/replay",
        json=valid_payload,
        headers=auth_headers(),
    )
    queued = client.post(
        "/internal/v1/jobs/queued/replay",
        json=valid_payload,
        headers=auth_headers(),
    )
    not_dead_letter = client.post(
        "/internal/v1/jobs/failed/replay",
        json=valid_payload,
        headers=auth_headers(),
    )
    bad_payload = client.post(
        "/internal/v1/jobs/queued/replay",
        json={"replay_job_id": ""},
        headers=auth_headers(),
    )
    bad_timestamp = client.post(
        "/internal/v1/jobs/queued/replay",
        json={**valid_payload, "observed_at": ""},
        headers=auth_headers(),
    )

    assert missing_auth.status_code == 401
    assert missing_auth.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"
    assert missing_job.status_code == 404
    assert missing_job.json()["error_code"] == "job.not_found"
    assert queued.status_code == 409
    assert queued.json()["error_code"] == "job_replay.status_invalid"
    assert not_dead_letter.status_code == 409
    assert not_dead_letter.json()["error_code"] == "job_replay.dead_letter_required"
    assert bad_payload.status_code == 422
    assert bad_payload.json()["error_code"] == "job_control.replay_payload_invalid"
    assert bad_timestamp.status_code == 422
    assert bad_timestamp.json()["error_code"] == "job_control.observed_at_invalid"


def test_service_job_control_rejects_retry_for_non_running_and_bad_payload() -> None:
    queue = InMemoryJobQueue()
    queue.enqueue(sample_job(job_id="queued", idempotency_key="queued"))
    queue.enqueue(sample_job(job_id="done", idempotency_key="done"))
    queue.start_job("done", updated_at=NOW)
    queue.complete_job("done", updated_at=LATER)
    client = build_client(queue)

    queued = client.post(
        "/internal/v1/jobs/queued/retry",
        headers=auth_headers(),
    )
    done = client.post(
        "/internal/v1/jobs/done/retry",
        headers=auth_headers(),
    )
    bad_error = client.post(
        "/internal/v1/jobs/done/retry",
        json={"error_code": "", "detail": ""},
        headers=auth_headers(),
    )

    assert queued.status_code == 409
    assert queued.json()["error_code"] == "job.retry_status_invalid"
    assert done.status_code == 409
    assert done.json()["error_code"] == "job.retry_status_invalid"
    assert bad_error.status_code == 422
    assert bad_error.json()["error_code"] == "job.field_invalid"


def test_service_job_control_can_target_other_service_audience() -> None:
    queue = InMemoryJobQueue()
    queue.enqueue(sample_job(job_type="mo.provider_live_smoke"))
    client = build_client(queue, service_id="nex-mo")

    response = client.get(
        "/internal/v1/jobs/job-001",
        headers=auth_headers(audience="nex-mo"),
    )

    assert response.status_code == 200
    assert response.json()["job"]["service_id"] == "nex-mo"
    assert response.json()["job"]["job_type"] == "mo.provider_live_smoke"


def test_service_job_control_projects_completed_status_without_actions() -> None:
    job = sample_job(status=SUCCEEDED)

    response = build_service_job_control_response(
        service_id="nex-cx",
        action="read",
        job=job,
    )

    assert response["job"]["status"] == SUCCEEDED
    assert response["controls"] == {
        "can_cancel": False,
        "can_retry": False,
        "can_replay": False,
        "terminal": True,
        "dead_lettered": False,
        "allowed_actions": ["read"],
    }


def test_service_job_control_projects_running_status_with_retry_action() -> None:
    response = build_service_job_control_response(
        service_id="nex-cx",
        action="read",
        job=sample_job(status=RUNNING, attempt_count=1),
    )

    assert response["controls"]["can_cancel"] is True
    assert response["controls"]["can_retry"] is True
    assert response["controls"]["can_replay"] is False
    assert response["controls"]["allowed_actions"] == ["read", "cancel", "retry"]
