from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    InMemoryJobQueue,
    InMemoryOperationalEventStore,
    OperationalEventEmitter,
    issue_mock_service_token,
)
from nex_wa import (
    WA_OPERATIONS_READ_SCOPE,
    SqlAlchemyWaOperationsSource,
    WaEvidenceIntakeService,
    WaIntakeContractError,
    WaOperationsError,
    register_wa_operations_routes,
)
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

NOW = datetime(2026, 10, 28, 10, 0, tzinfo=UTC)


def _source():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE service_jobs (job_id TEXT, job_type TEXT, "
                "status TEXT, retryable BOOLEAN, available_at TEXT)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE service_worker_heartbeats (service_id TEXT, "
                "status TEXT, last_seen_at TEXT)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE service_operational_events (service_id TEXT, "
                "event_type TEXT)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO service_jobs VALUES "
                "('job-q','WA_EVIDENCE_INGEST','QUEUED',1,'2026-10-28T09:58:00Z'),"
                "('job-r','WA_EVIDENCE_INGEST','RUNNING',1,'2026-10-28T09:59:00Z'),"
                "('job-s','WA_EVIDENCE_INGEST','SUCCEEDED',1,'2026-10-28T09:57:00Z'),"
                "('job-f','WA_EVIDENCE_INGEST','FAILED',0,'2026-10-28T09:56:00Z')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO service_worker_heartbeats VALUES "
                "('nex-wa','IDLE','2026-10-28T09:59:30Z'),"
                "('nex-wa','ERROR','2026-10-28T09:50:00Z')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO service_operational_events VALUES "
                "('nex-wa','wa.source.conflict'),"
                "('nex-wa','wa.evidence.reused'),"
                "('nex-wa','wa.job.stale_recovered'),"
                "('nex-wa','wa.reconciliation.completed')"
            )
        )
    return engine, SqlAlchemyWaOperationsSource(
        sessionmaker(bind=engine),
        clock=lambda: NOW,
        heartbeat_stale_after_seconds=60,
    )


def _headers(*, service_id: str = "nex-ag", scopes=None):
    token = issue_mock_service_token(
        service_id=service_id,
        audience="nex-wa",
        scopes=scopes or (DEFAULT_SERVICE_SCOPE, WA_OPERATIONS_READ_SCOPE),
    ).access_token
    return {"Authorization": f"Bearer {token}"}


def test_operations_projection_is_bounded_and_has_no_high_cardinality_labels() -> None:
    engine, source = _source()
    snapshot = source.snapshot()
    assert snapshot["queue"] == {
        "queued": 1,
        "running": 1,
        "succeeded": 1,
        "failed": 1,
        "dead_lettered": 1,
        "oldest_runnable_age_seconds": 120.0,
    }
    assert snapshot["outcomes"] == {
        "ingest_success": 1,
        "ingest_failure": 1,
        "source_hash_conflict": 1,
        "evidence_reuse": 1,
        "stale_recovery": 1,
        "reconciliation_completed": 1,
    }
    assert snapshot["consumer"]["heartbeat_count"] == 2
    assert snapshot["consumer"]["stale_count"] == 1
    assert not ({"job_id", "subject_id", "artifact_id", "project_id"} & snapshot.keys())
    engine.dispose()


def test_operations_route_is_ag_only_scope_protected_and_reports_failure() -> None:
    engine, source = _source()
    app = FastAPI()
    register_wa_operations_routes(app, source=source)
    client = TestClient(app)
    path = "/internal/v1/operations/summary"
    assert client.get(path, headers=_headers()).status_code == 200
    assert client.get(path).status_code == 401
    assert client.get(
        path,
        headers=_headers(scopes=(DEFAULT_SERVICE_SCOPE,)),
    ).status_code == 401
    assert client.get(path, headers=_headers(service_id="nex-ae-api")).status_code == 403

    engine.dispose()
    unavailable = client.get(path, headers=_headers())
    assert unavailable.status_code == 503
    assert unavailable.json()["error_code"] == "WA_OPERATIONS_UNAVAILABLE"

    no_source = FastAPI()
    register_wa_operations_routes(no_source, source=None)
    assert TestClient(no_source).get(path, headers=_headers()).status_code == 503


def test_intake_emits_admission_reuse_and_conflict_without_source_content() -> None:
    events = InMemoryOperationalEventStore()
    service = WaEvidenceIntakeService(
        InMemoryJobQueue(),
        clock=lambda: NOW,
        event_emitter=OperationalEventEmitter(service_id="nex-wa", store=events),
    )
    payload = {
        "schema_version": "wa_evidence_intake_request.v1",
        "tenant_id": "VO00",
        "source_type": "AE_AGENT_RESULT",
        "source_ref": "execution-sensitive-001",
        "source_revision_ref": "result-001",
        "source_hash": "sha256:" + "a" * 64,
        "occurred_at": "2026-10-28T09:59:00Z",
        "correlation_id": "correlation-001",
    }
    service.admit(
        payload,
        caller_service_id="nex-ae-api",
        request_id="request-1",
        trace_id="trace-1",
    )
    service.admit(
        payload,
        caller_service_id="nex-ae-api",
        request_id="request-2",
        trace_id="trace-2",
    )
    with pytest.raises(WaIntakeContractError):
        service.admit(
            {**payload, "source_hash": "sha256:" + "b" * 64},
            caller_service_id="nex-ae-api",
            request_id="request-3",
            trace_id="trace-3",
        )

    event_types = [item["event_type"] for item in events.list_events(limit=10)]
    assert set(event_types) == {
        "wa.intake.admitted",
        "wa.evidence.reused",
        "wa.source.conflict",
    }
    serialized = str(events.list_events(limit=10))
    assert "source_hash" not in serialized
    assert "sha256:" not in serialized


def test_operations_source_rejects_invalid_stale_threshold() -> None:
    with pytest.raises(ValueError, match="positive"):
        SqlAlchemyWaOperationsSource(sessionmaker(), heartbeat_stale_after_seconds=0)


def test_operations_projection_supports_empty_state_and_naive_clock() -> None:
    engine, _ = _source()
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM service_jobs"))
        connection.execute(text("DELETE FROM service_worker_heartbeats"))
        connection.execute(text("DELETE FROM service_operational_events"))
    source = SqlAlchemyWaOperationsSource(
        sessionmaker(bind=engine),
        clock=lambda: NOW.replace(tzinfo=None),
    )

    snapshot = source.snapshot()

    assert snapshot["queue"]["oldest_runnable_age_seconds"] is None
    assert snapshot["consumer"] == {
        "heartbeat_count": 0,
        "stale_count": 0,
        "status_counts": {},
        "stale_after_seconds": 60,
    }
    assert set(snapshot["outcomes"].values()) == {0}
    engine.dispose()


def test_operations_projection_rejects_invalid_heartbeat_timestamp() -> None:
    engine, source = _source()
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE service_worker_heartbeats SET last_seen_at = NULL")
        )

    with pytest.raises(WaOperationsError) as exc_info:
        source.snapshot()

    assert exc_info.value.error_code == "WA_OPERATIONS_TIMESTAMP_INVALID"
    engine.dispose()
