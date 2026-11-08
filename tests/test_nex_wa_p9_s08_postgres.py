from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from nex_runtime.database import psycopg_database_url
from nex_runtime.postgres_targets import resolve_postgres_test_targets
from nex_wa import (
    ControlledWaEvidenceSourceAdapter,
    WaEvidenceSourceAdapterRegistry,
    build_wa_evidence_consumer_runtime,
)
from nex_wa.app import create_wa_app
from run_migrations import run_service_migrations
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    os.getenv("NEX_WA_P9_S08_POSTGRES_SMOKE") != "1",
    reason="set NEX_WA_P9_S08_POSTGRES_SMOKE=1 for actual nex_wa_test smoke",
)


def test_actual_postgres_consumer_claim_complete_heartbeat_and_zero_residue() -> None:
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
            "NEX_VERSION": "2.1.0-p9-s08",
            "NEX_BUILD_SHA": "p9s08postgres",
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
            "NEX_WA_DATABASE_URL": database_url,
            "NEX_WA_DB_POOL_SIZE": "2",
            "NEX_WA_DB_MAX_OVERFLOW": "0",
            "NEX_WA_DB_WORKER_POOL_SIZE": "2",
            "NEX_WA_DB_WORKER_MAX_OVERFLOW": "0",
        }
    )
    persistence = app.state.wa_persistence
    suffix = uuid4().hex
    worker_id = f"p9-s08-worker-{suffix}"
    now = datetime.now(UTC)
    now_wire = now.isoformat().replace("+00:00", "Z")
    claim_wire = (now + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    admission = app.state.wa_evidence_intake_service.admit(
        {
            "schema_version": "wa_evidence_intake_request.v1",
            "tenant_id": f"P9S08-{suffix}",
            "source_type": "AE_AGENT_RESULT",
            "source_ref": f"agent-execution-{suffix}",
            "source_revision_ref": "result-1",
            "source_hash": "sha256:" + "8" * 64,
            "occurred_at": now_wire,
            "correlation_id": f"corr-{suffix}",
        },
        caller_service_id="nex-ae-api",
        request_id=f"request-{suffix}",
        trace_id="3" * 32,
    )
    consumer = build_wa_evidence_consumer_runtime(
        persistence=persistence,
        registry=WaEvidenceSourceAdapterRegistry(
            {
                source_type: ControlledWaEvidenceSourceAdapter(source_type)
                for source_type in ("AE_AGENT_RESULT", "AE_ARTIFACT")
            }
        ),
        worker_id=worker_id,
    )
    try:
        assert consumer.readiness()["domain_processing_enabled"] is True
        result = consumer.run_once(clock=lambda: claim_wire)
        assert result.status == "SUCCEEDED"
        assert result.handler_result["source_inspection"] == "VERIFIED"
        consumer.stop(observed_at=claim_wire)

        with persistence.worker_engine.connect() as connection:
            job_row = connection.execute(
                text(
                    "SELECT status, attempt_count, locked_by FROM service_jobs "
                    "WHERE job_id=:job_id"
                ),
                {"job_id": admission.job_id},
            ).one()
            heartbeat_row = connection.execute(
                text(
                    "SELECT status, worker_type FROM service_worker_heartbeats "
                    "WHERE service_id='nex-wa' AND worker_id=:worker_id"
                ),
                {"worker_id": worker_id},
            ).one()
        assert tuple(job_row) == ("SUCCEEDED", 1, None)
        assert tuple(heartbeat_row) == ("STOPPED", "wa.evidence_consumer")
    finally:
        with persistence.worker_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM service_jobs WHERE job_id=:job_id"),
                {"job_id": admission.job_id},
            )
            connection.execute(
                text(
                    "DELETE FROM service_worker_heartbeats "
                    "WHERE service_id='nex-wa' AND worker_id=:worker_id"
                ),
                {"worker_id": worker_id},
            )
        with persistence.worker_engine.connect() as connection:
            assert connection.execute(
                text("SELECT count(*) FROM service_jobs WHERE job_id=:job_id"),
                {"job_id": admission.job_id},
            ).scalar_one() == 0
            assert connection.execute(
                text(
                    "SELECT count(*) FROM service_worker_heartbeats "
                    "WHERE service_id='nex-wa' AND worker_id=:worker_id"
                ),
                {"worker_id": worker_id},
            ).scalar_one() == 0
        persistence.dispose()
