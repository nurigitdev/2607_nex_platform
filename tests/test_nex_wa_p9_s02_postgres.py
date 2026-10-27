from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest
from nex_runtime import WorkerHeartbeatEmitter, build_common_job
from nex_runtime.database import psycopg_database_url
from nex_runtime.postgres_targets import resolve_postgres_test_targets
from nex_wa import WA_FOUNDATION_MIGRATIONS, build_wa_persistence_runtime
from run_migrations import run_service_migrations
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    os.getenv("NEX_WA_P9_S02_POSTGRES_SMOKE") != "1",
    reason="set NEX_WA_P9_S02_POSTGRES_SMOKE=1 for actual nex_wa_test smoke",
)


def test_actual_wa_postgres_bootstrap_queue_heartbeat_and_zero_residue() -> None:
    resolved = resolve_postgres_test_targets(
        os.environ,
        service_ids=("nex-wa",),
    )[0]
    database_url = resolved.database_url
    connection_url = psycopg_database_url(database_url)

    with (
        psycopg.connect(connection_url, autocommit=True) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT current_database(), current_user")
        assert cursor.fetchone() == ("nex_wa_test", "nex_wa_user")

    first = run_service_migrations(
        "nex-wa",
        database_url=database_url,
        profile="test",
    )
    repeat = run_service_migrations(
        "nex-wa",
        database_url=database_url,
        profile="test",
    )
    assert first.planned == WA_FOUNDATION_MIGRATIONS
    assert {*first.applied, *first.skipped} == set(WA_FOUNDATION_MIGRATIONS)
    assert repeat.applied == ()
    assert repeat.skipped == WA_FOUNDATION_MIGRATIONS

    runtime = build_wa_persistence_runtime(
        environ={
            "NEX_WA_TEST_DATABASE_URL": database_url,
            "NEX_WA_DB_POOL_SIZE": "2",
            "NEX_WA_DB_MAX_OVERFLOW": "0",
            "NEX_WA_DB_WORKER_POOL_SIZE": "2",
            "NEX_WA_DB_WORKER_MAX_OVERFLOW": "0",
        },
        database_env="NEX_WA_TEST_DATABASE_URL",
    )
    suffix = uuid4().hex
    job_id = f"p9-s02-job-{suffix}"
    worker_id = f"p9-s02-worker-{suffix}"
    observed_at = datetime.now(UTC).isoformat()
    try:
        stored = runtime.job_queue.enqueue(
            build_common_job(
                job_id=job_id,
                job_type="WA_EVIDENCE_INGEST",
                trace_id=f"trace-{suffix}",
                request_id=f"request-{suffix}",
                subject_ref={"type": "WORK_EVIDENCE", "id": suffix},
                idempotency_key=f"p9-s02:{suffix}",
                created_at=observed_at,
            )
        )
        assert stored["job_id"] == job_id
        assert runtime.job_queue.get_job(job_id)["status"] == "QUEUED"

        heartbeat = WorkerHeartbeatEmitter(
            service_id="nex-wa",
            worker_id=worker_id,
            worker_type="wa.evidence_consumer",
            store=runtime.worker_heartbeat_store,
            started_at=observed_at,
        ).idle(observed_at=observed_at)
        assert heartbeat["status"] == "IDLE"
        assert runtime.worker_heartbeat_store.get_heartbeat(
            "nex-wa", worker_id
        )["worker_type"] == "wa.evidence_consumer"

        with runtime.api_engine.connect() as connection:
            versions = tuple(
                connection.execute(
                    text("SELECT version FROM schema_migrations ORDER BY version")
                ).scalars()
            )
            tables = set(
                connection.execute(
                    text(
                        "SELECT tablename FROM pg_catalog.pg_tables "
                        "WHERE schemaname = 'public'"
                    )
                ).scalars()
            )
        assert versions == WA_FOUNDATION_MIGRATIONS
        assert {"schema_migrations", "service_jobs", "service_worker_heartbeats"} <= tables
        assert not any(name.startswith("wa_work_") for name in tables)
        assert runtime.migration_readiness()["ok"] is True
    finally:
        with runtime.api_engine.begin() as connection:
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
