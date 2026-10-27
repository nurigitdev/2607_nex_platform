from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from nex_runtime import (
    OperationalEventEmitter,
    ServiceLogEmitter,
    WorkerHeartbeatEmitter,
    build_common_job,
)
from nex_runtime.postgres_targets import resolve_postgres_test_targets
from nex_wa import SqlAlchemyWaOperationsSource, build_wa_persistence_runtime
from run_migrations import run_service_migrations
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    os.getenv("NEX_WA_P9_S24_POSTGRES_SMOKE") != "1",
    reason="set NEX_WA_P9_S24_POSTGRES_SMOKE=1 for actual nex_wa_test smoke",
)


def test_actual_postgres_operations_storage_projection_and_zero_residue() -> None:
    resolved = resolve_postgres_test_targets(
        os.environ,
        service_ids=("nex-wa",),
    )[0]
    database_url = resolved.database_url
    run_service_migrations("nex-wa", database_url=database_url, profile="test")
    runtime = build_wa_persistence_runtime(
        environ={"NEX_WA_TEST_DATABASE_URL": database_url},
        database_env="NEX_WA_TEST_DATABASE_URL",
    )
    suffix = uuid4().hex
    job_id = f"p9-s24-job-{suffix}"
    worker_id = f"p9-s24-worker-{suffix}"
    observed_at = datetime.now(UTC).isoformat()
    event = None
    log = None
    try:
        runtime.job_queue.enqueue(
            build_common_job(
                job_id=job_id,
                job_type="WA_EVIDENCE_INGEST",
                trace_id=f"trace-{suffix}",
                request_id=f"request-{suffix}",
                subject_ref={"type": "WORK_EVIDENCE", "id": suffix},
                idempotency_key=f"p9-s24:{suffix}",
                created_at=observed_at,
            )
        )
        WorkerHeartbeatEmitter(
            service_id="nex-wa",
            worker_id=worker_id,
            worker_type="wa.evidence_consumer",
            store=runtime.worker_heartbeat_store,
            started_at=observed_at,
        ).idle(observed_at=observed_at)
        event = OperationalEventEmitter(
            service_id="nex-wa",
            store=runtime.operational_event_store,
        ).emit(
            event_type="wa.source.conflict",
            severity="WARNING",
            message="P9-S24 PostgreSQL protected smoke event.",
            details={"source_type": "AE_AGENT_RESULT"},
            created_at=observed_at,
        )
        log = ServiceLogEmitter(
            service_id="nex-wa",
            logger_name="p9-s24-postgres-smoke",
            store=runtime.service_log_store,
        ).emit(
            severity="INFO",
            message="P9-S24 PostgreSQL protected smoke log.",
            job_id=job_id,
            observed_at=observed_at,
        )

        snapshot = SqlAlchemyWaOperationsSource(
            runtime.api_session_factory,
            clock=lambda: datetime.now(UTC),
        ).snapshot()

        assert snapshot["queue"]["queued"] >= 1
        assert snapshot["outcomes"]["source_hash_conflict"] >= 1
        assert snapshot["consumer"]["heartbeat_count"] >= 1
        assert runtime.operational_event_store.get_event(event["event_id"]) is not None
        assert runtime.service_log_store.get_log(log["log_id"]) is not None
    finally:
        with runtime.api_engine.begin() as connection:
            if log is not None:
                connection.execute(
                    text("DELETE FROM service_log_entries WHERE log_id = :log_id"),
                    {"log_id": log["log_id"]},
                )
            if event is not None:
                connection.execute(
                    text(
                        "DELETE FROM service_operational_events "
                        "WHERE event_id = :event_id"
                    ),
                    {"event_id": event["event_id"]},
                )
            connection.execute(
                text(
                    "DELETE FROM service_worker_heartbeats "
                    "WHERE service_id = 'nex-wa' AND worker_id = :worker_id"
                ),
                {"worker_id": worker_id},
            )
            connection.execute(
                text("DELETE FROM service_jobs WHERE job_id = :job_id"),
                {"job_id": job_id},
            )
        with runtime.api_engine.connect() as connection:
            assert connection.execute(
                text("SELECT count(*) FROM service_jobs WHERE job_id = :job_id"),
                {"job_id": job_id},
            ).scalar_one() == 0
            assert connection.execute(
                text(
                    "SELECT count(*) FROM service_worker_heartbeats "
                    "WHERE service_id = 'nex-wa' AND worker_id = :worker_id"
                ),
                {"worker_id": worker_id},
            ).scalar_one() == 0
        runtime.dispose()
