from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from statistics import quantiles
from time import perf_counter
from typing import Any

import pytest
from fastapi.testclient import TestClient
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    InMemoryJobQueue,
    JobQueueError,
    SqlAlchemyJobQueue,
    build_engine,
    build_session_factory,
    issue_mock_service_token,
)
from nex_wa import (
    WA_EVIDENCE_INGEST_JOB_TYPE,
    WA_EVIDENCE_INGEST_MAX_ATTEMPTS,
    WA_EVIDENCE_INGEST_SCOPE,
    WaEvidenceIntakeService,
    WaIntakeContractError,
)
from nex_wa.app import create_wa_app
from sqlalchemy import text

NOW = datetime(2026, 10, 27, 10, 0, tzinfo=UTC)


def _payload(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "wa_evidence_intake_request.v1",
        "tenant_id": "VO00",
        "source_type": "AE_AGENT_RESULT",
        "source_ref": "agent-execution-9100",
        "source_revision_ref": "result-1",
        "source_hash": "sha256:" + "a" * 64,
        "occurred_at": "2026-10-27T10:00:00Z",
        "correlation_id": "corr-p9-s07-001",
    }
    value.update(overrides)
    return value


def _environment() -> dict[str, str]:
    return {
        "NEX_WA_SERVICE_ID": "nex-wa",
        "NEX_PROFILE": "test",
        "NEX_VERSION": "2.1.0-p9-s07",
        "NEX_BUILD_SHA": "p9s07test",
        "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
    }


def _token(
    *,
    service_id: str = "nex-ae-api",
    audience: str = "nex-wa",
    scopes: tuple[str, ...] = (
        DEFAULT_SERVICE_SCOPE,
        WA_EVIDENCE_INGEST_SCOPE,
    ),
) -> str:
    return issue_mock_service_token(
        service_id=service_id,
        audience=audience,
        scopes=scopes,
    ).access_token


def _headers(token: str, *, request_id: str = "req-p9-s07-001") -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Request-ID": request_id,
        "traceparent": "00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01",
    }


def _client(queue: Any | None = None) -> tuple[TestClient, Any]:
    selected = queue or InMemoryJobQueue()
    app = create_wa_app(environ=_environment())
    app.state.wa_evidence_intake_service = WaEvidenceIntakeService(
        selected,
        clock=lambda: NOW,
    )
    return TestClient(app), selected


def _sqlite_queue(database_path: Path) -> SqlAlchemyJobQueue:
    engine = build_engine(f"sqlite+pysqlite:///{database_path}")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE service_jobs (
                    job_id TEXT PRIMARY KEY,
                    job_schema_version TEXT NOT NULL DEFAULT 'common_job.v1',
                    job_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    subject_type TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 1,
                    retryable INTEGER NOT NULL DEFAULT 1,
                    links TEXT NOT NULL DEFAULT '{}',
                    payload TEXT NOT NULL DEFAULT '{}',
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
    return SqlAlchemyJobQueue(build_session_factory(engine))


def test_protected_api_durably_enqueues_reference_only_job(tmp_path: Path) -> None:
    queue = _sqlite_queue(tmp_path / "wa-p9-s07.sqlite3")
    client, _ = _client(queue)

    response = client.post(
        "/internal/v1/evidence-intake",
        json=_payload(),
        headers=_headers(_token()),
    )

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["schema_version"] == "wa_evidence_intake_admission.v1"
    assert body["job_type"] == WA_EVIDENCE_INGEST_JOB_TYPE
    assert body["status"] == "QUEUED"
    assert body["idempotent_reuse"] is False
    assert body["request_id"] == "req-p9-s07-001"
    assert body["trace_id"] == "a" * 32
    stored = queue.get_job(body["job_id"])
    assert stored is not None
    assert stored["max_attempts"] == WA_EVIDENCE_INGEST_MAX_ATTEMPTS
    assert stored["subject_ref"] == {"type": "SERVICE", "id": "nex-ae-api"}
    assert set(stored["payload"]) == {
        "schema_version",
        "tenant_id",
        "source_type",
        "source_ref",
        "source_revision_ref",
        "source_hash",
        "occurred_at",
        "correlation_id",
        "request_id",
        "trace_id",
    }


def test_duplicate_enqueue_reuses_job_and_hash_conflict_is_rejected() -> None:
    client, queue = _client()
    first = client.post(
        "/internal/v1/evidence-intake",
        json=_payload(),
        headers=_headers(_token(), request_id="req-first"),
    )
    replay = client.post(
        "/internal/v1/evidence-intake",
        json=_payload(),
        headers=_headers(_token(), request_id="req-replay"),
    )
    conflict = client.post(
        "/internal/v1/evidence-intake",
        json=_payload(source_hash="sha256:" + "b" * 64),
        headers=_headers(_token(), request_id="req-conflict"),
    )

    assert first.status_code == 202
    assert replay.status_code == 202
    assert replay.json()["job_id"] == first.json()["job_id"]
    assert replay.json()["idempotent_reuse"] is True
    assert conflict.status_code == 409
    assert conflict.json()["error_code"] == "WA_SOURCE_IDEMPOTENCY_CONFLICT"
    assert len(queue.jobs) == 1


@pytest.mark.parametrize(
    ("token", "expected_status", "expected_code"),
    [
        (
            _token(audience="nex-eos"),
            403,
            "nex.mock_token_audience_invalid",
        ),
        (
            _token(service_id="nex-cx"),
            403,
            "WA_INTAKE_CALLER_FORBIDDEN",
        ),
        (
            _token(scopes=(DEFAULT_SERVICE_SCOPE,)),
            403,
            "nex.mock_token_scope_missing",
        ),
    ],
)
def test_service_authorization_is_fail_closed(
    token: str,
    expected_status: int,
    expected_code: str,
) -> None:
    client, queue = _client()

    response = client.post(
        "/internal/v1/evidence-intake",
        json=_payload(),
        headers=_headers(token),
    )

    assert response.status_code == expected_status
    assert response.json()["error_code"] == expected_code
    assert not queue.jobs


def test_unconfigured_and_broken_persistence_return_redacted_503() -> None:
    unavailable_app = create_wa_app(environ=_environment())
    unavailable = TestClient(unavailable_app).post(
        "/internal/v1/evidence-intake",
        json=_payload(),
        headers=_headers(_token()),
    )

    class BrokenQueue(InMemoryJobQueue):
        def get_job(self, job_id: str) -> dict[str, Any] | None:
            raise JobQueueError("job.store_unavailable", "secret database URL", 503)

    broken, _ = _client(BrokenQueue())
    failed = broken.post(
        "/internal/v1/evidence-intake",
        json=_payload(),
        headers=_headers(_token()),
    )

    assert unavailable.status_code == 503
    assert unavailable.json()["error_code"] == "WA_INTAKE_UNAVAILABLE"
    assert failed.status_code == 503
    assert failed.json()["error_code"] == "WA_INTAKE_STORE_UNAVAILABLE"
    assert "secret" not in failed.text


@pytest.mark.parametrize(
    "stored_mutation",
    [
        {"job_type": "OTHER"},
        {"payload": "not-an-object"},
        {"payload": {"schema_version": "broken"}},
    ],
)
def test_corrupt_stored_jobs_fail_closed(stored_mutation: dict[str, object]) -> None:
    class CorruptQueue(InMemoryJobQueue):
        def get_job(self, job_id: str) -> dict[str, Any] | None:
            valid = super().get_job(job_id)
            if valid is not None:
                valid.update(stored_mutation)
            return valid

    queue = CorruptQueue()
    service = WaEvidenceIntakeService(queue, clock=lambda: NOW)
    service.admit(
        _payload(),
        caller_service_id="nex-ae-api",
        request_id="req-first",
        trace_id="trace-first",
    )

    with pytest.raises(WaIntakeContractError) as caught:
        service.admit(
            _payload(),
            caller_service_id="nex-ae-api",
            request_id="req-second",
            trace_id="trace-second",
        )

    assert caught.value.error_code == "WA_INTAKE_STORE_INVALID"
    assert caught.value.status_code == 503


def test_transport_refs_override_untrusted_body_refs() -> None:
    queue = InMemoryJobQueue()
    service = WaEvidenceIntakeService(queue, clock=lambda: NOW)

    admission = service.admit(
        _payload(request_id="spoofed-request", trace_id="spoofed-trace"),
        caller_service_id="nex-ae-api",
        request_id="trusted-request",
        trace_id="trusted-trace",
    )

    stored = queue.get_job(admission.job_id)
    assert stored is not None
    assert stored["payload"]["request_id"] == "trusted-request"
    assert stored["payload"]["trace_id"] == "trusted-trace"


def test_in_memory_admission_p95_baseline_is_bounded() -> None:
    queue = InMemoryJobQueue()
    service = WaEvidenceIntakeService(queue, clock=lambda: NOW)
    durations: list[float] = []

    for index in range(100):
        started = perf_counter()
        service.admit(
            _payload(source_ref=f"agent-execution-{index}"),
            caller_service_id="nex-ae-api",
            request_id=f"request-{index}",
            trace_id=f"trace-{index}",
        )
        durations.append((perf_counter() - started) * 1000)

    assert quantiles(durations, n=100)[94] < 20.0
    assert len(queue.jobs) == 100


def test_clock_must_be_timezone_aware() -> None:
    service = WaEvidenceIntakeService(
        InMemoryJobQueue(),
        clock=lambda: datetime(2026, 10, 27, 10, 0),
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        service.admit(
            _payload(),
            caller_service_id="nex-ae-api",
            request_id="request",
            trace_id="trace",
        )
