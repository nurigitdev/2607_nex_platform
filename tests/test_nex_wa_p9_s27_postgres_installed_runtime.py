from __future__ import annotations

import os
from uuid import uuid4

import psycopg
import pytest
from nex_runtime.database import psycopg_database_url
from nex_runtime.postgres_targets import resolve_postgres_test_targets
from nex_wa import WA_REQUIRED_MIGRATIONS, build_installed_consumer_process
from run_migrations import run_service_migrations

pytestmark = pytest.mark.skipif(
    os.getenv("NEX_WA_P9_S27_POSTGRES_SMOKE") != "1",
    reason="set NEX_WA_P9_S27_POSTGRES_SMOKE=1 for actual nex_wa_test smoke",
)


def test_actual_postgres_installed_consumer_start_stop_restart_and_zero_residue() -> None:
    target = resolve_postgres_test_targets(os.environ, service_ids=("nex-wa",))[0]
    database_url = target.database_url
    worker_id = f"p9-s27-installed-{uuid4().hex}"
    connection_url = psycopg_database_url(database_url)
    with psycopg.connect(connection_url, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), current_user")
            assert cursor.fetchone() == ("nex_wa_test", "nex_wa_user")
            cursor.execute(
                "SELECT count(*) FROM service_jobs "
                "WHERE job_type='WA_EVIDENCE_INGEST' AND status IN ('QUEUED', 'RUNNING')"
            )
            assert cursor.fetchone()[0] == 0

    migration = run_service_migrations(
        "nex-wa",
        database_url=database_url,
        profile="test",
    )
    assert set(WA_REQUIRED_MIGRATIONS).issubset(
        set(migration.applied) | set(migration.skipped)
    )
    environ = {
        "NEX_PROFILE": "test",
        "NEX_VERSION": "2.1.0-p9-s27",
        "NEX_BUILD_SHA": "p9s27postgres",
        "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
        "NEX_WA_DATABASE_URL": database_url,
        "NEX_WA_WORKER_ID": worker_id,
        "NEX_WA_DB_POOL_SIZE": "2",
        "NEX_WA_DB_MAX_OVERFLOW": "0",
        "NEX_WA_DB_WORKER_POOL_SIZE": "2",
        "NEX_WA_DB_WORKER_MAX_OVERFLOW": "0",
    }

    first = build_installed_consumer_process(environ=environ)
    try:
        assert first.startup()["readiness_status"] == "READY"
        assert first.run_once()["status"] == "IDLE"
    finally:
        first.close()

    second = build_installed_consumer_process(environ=environ)
    try:
        assert second.startup()["readiness_status"] == "READY"
        assert second.run_once()["status"] == "IDLE"
    finally:
        second.close()

    with psycopg.connect(connection_url, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT status, worker_type FROM service_worker_heartbeats "
                "WHERE service_id='nex-wa' AND worker_id=%s",
                (worker_id,),
            )
            assert cursor.fetchone() == ("STOPPED", "wa.evidence_consumer")
            cursor.execute(
                "DELETE FROM service_log_entries "
                "WHERE service_id='nex-wa' AND attributes->>'worker_id'=%s",
                (worker_id,),
            )
            cursor.execute(
                "DELETE FROM service_worker_heartbeats "
                "WHERE service_id='nex-wa' AND worker_id=%s",
                (worker_id,),
            )
            cursor.execute(
                "SELECT count(*) FROM service_worker_heartbeats "
                "WHERE service_id='nex-wa' AND worker_id=%s",
                (worker_id,),
            )
            assert cursor.fetchone()[0] == 0
            cursor.execute(
                "SELECT count(*) FROM service_log_entries "
                "WHERE service_id='nex-wa' AND attributes->>'worker_id'=%s",
                (worker_id,),
            )
            assert cursor.fetchone()[0] == 0
