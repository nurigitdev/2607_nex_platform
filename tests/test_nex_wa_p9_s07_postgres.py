from __future__ import annotations

import os
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from nex_runtime import DEFAULT_SERVICE_SCOPE, issue_mock_service_token
from nex_runtime.database import psycopg_database_url
from nex_runtime.postgres_targets import resolve_postgres_test_targets
from nex_wa import WA_EVIDENCE_INGEST_SCOPE
from nex_wa.app import create_wa_app
from run_migrations import run_service_migrations
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    os.getenv("NEX_WA_P9_S07_POSTGRES_SMOKE") != "1",
    reason="set NEX_WA_P9_S07_POSTGRES_SMOKE=1 for actual nex_wa_test smoke",
)


def test_actual_postgres_protected_durable_intake_and_zero_residue() -> None:
    target = resolve_postgres_test_targets(os.environ, service_ids=("nex-wa",))[0]
    database_url = target.database_url
    with (
        psycopg.connect(
            psycopg_database_url(database_url),
            autocommit=True,
        ) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT current_database(), current_user")
        assert cursor.fetchone() == ("nex_wa_test", "nex_wa_user")
    run_service_migrations("nex-wa", database_url=database_url, profile="test")

    app = create_wa_app(
        environ={
            "NEX_WA_SERVICE_ID": "nex-wa",
            "NEX_PROFILE": "test",
            "NEX_VERSION": "2.1.0-p9-s07",
            "NEX_BUILD_SHA": "p9s07postgres",
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
            "NEX_WA_DATABASE_URL": database_url,
            "NEX_WA_DB_POOL_SIZE": "2",
            "NEX_WA_DB_MAX_OVERFLOW": "0",
            "NEX_WA_DB_WORKER_POOL_SIZE": "2",
            "NEX_WA_DB_WORKER_MAX_OVERFLOW": "0",
        }
    )
    runtime = app.state.wa_persistence
    suffix = uuid4().hex
    source_ref = f"agent-execution-{suffix}"
    payload = {
        "schema_version": "wa_evidence_intake_request.v1",
        "tenant_id": f"P9S07-{suffix}",
        "source_type": "AE_AGENT_RESULT",
        "source_ref": source_ref,
        "source_revision_ref": "result-1",
        "source_hash": "sha256:" + "7" * 64,
        "occurred_at": "2026-10-27T10:00:00Z",
        "correlation_id": f"corr-{suffix}",
    }
    token = issue_mock_service_token(
        service_id="nex-ae-api",
        audience="nex-wa",
        scopes=(DEFAULT_SERVICE_SCOPE, WA_EVIDENCE_INGEST_SCOPE),
    ).access_token
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Request-ID": f"request-{suffix}",
        "traceparent": "00-11111111111111111111111111111111-2222222222222222-01",
    }
    job_id: str | None = None
    try:
        client = TestClient(app)
        created = client.post(
            "/internal/v1/evidence-intake",
            json=payload,
            headers=headers,
        )
        replay = client.post(
            "/internal/v1/evidence-intake",
            json=payload,
            headers={**headers, "X-Request-ID": f"request-replay-{suffix}"},
        )
        conflict = client.post(
            "/internal/v1/evidence-intake",
            json={**payload, "source_hash": "sha256:" + "8" * 64},
            headers={**headers, "X-Request-ID": f"request-conflict-{suffix}"},
        )

        assert created.status_code == 202
        job_id = created.json()["job_id"]
        assert replay.status_code == 202
        assert replay.json()["job_id"] == job_id
        assert replay.json()["idempotent_reuse"] is True
        assert conflict.status_code == 409
        assert conflict.json()["error_code"] == "WA_SOURCE_IDEMPOTENCY_CONFLICT"
        with runtime.api_engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT job_type, status, subject_id, payload->>'source_ref', "
                    "payload->>'source_hash' FROM service_jobs WHERE job_id=:job_id"
                ),
                {"job_id": job_id},
            ).one()
        assert tuple(row) == (
            "WA_EVIDENCE_INGEST",
            "QUEUED",
            "nex-ae-api",
            source_ref,
            payload["source_hash"],
        )
    finally:
        if job_id is not None:
            with runtime.api_engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM service_jobs WHERE job_id=:job_id"),
                    {"job_id": job_id},
                )
            with runtime.api_engine.connect() as connection:
                assert connection.execute(
                    text("SELECT count(*) FROM service_jobs WHERE job_id=:job_id"),
                    {"job_id": job_id},
                ).scalar_one() == 0
        runtime.dispose()
