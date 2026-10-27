from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from nex_runtime import build_common_job
from nex_runtime.database import psycopg_database_url
from nex_runtime.postgres_targets import resolve_postgres_test_targets
from nex_wa import WA_JOB_OWNERSHIP_LOST, WaFencedJobQueue, WaJobRecoveryError
from nex_wa.persistence import build_wa_persistence_runtime
from run_migrations import run_service_migrations
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    os.getenv("NEX_WA_P9_S09_POSTGRES_SMOKE") != "1",
    reason="set NEX_WA_P9_S09_POSTGRES_SMOKE=1 for actual nex_wa_test smoke",
)


def _wire(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _job(suffix: str, created_at: str, *, max_attempts: int = 5):
    return build_common_job(
        job_id=f"p9-s09-{suffix}",
        job_type="WA_EVIDENCE_INGEST",
        trace_id="9" * 32,
        request_id=f"request-{suffix}",
        subject_ref={"type": "SERVICE", "id": "nex-ae-api"},
        idempotency_key=f"p9-s09-{suffix}",
        created_at=created_at,
        max_attempts=max_attempts,
    )


def test_actual_postgres_fenced_recovery_and_racing_recoverers() -> None:
    target = resolve_postgres_test_targets(os.environ, service_ids=("nex-wa",))[0]
    database_url = target.database_url
    with (
        psycopg.connect(psycopg_database_url(database_url), autocommit=True) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT current_database(), current_user")
        assert cursor.fetchone() == ("nex_wa_test", "nex_wa_user")
    run_service_migrations("nex-wa", database_url=database_url, profile="test")

    persistence = build_wa_persistence_runtime(
        environ={
            "NEX_PROFILE": "test",
            "NEX_WA_DATABASE_URL": database_url,
            "NEX_WA_DB_POOL_SIZE": "4",
            "NEX_WA_DB_MAX_OVERFLOW": "2",
            "NEX_WA_DB_WORKER_POOL_SIZE": "4",
            "NEX_WA_DB_WORKER_MAX_OVERFLOW": "2",
        }
    )
    queue = persistence.job_queue
    store = persistence.job_fence_store
    suffix = uuid4().hex
    now = datetime.now(UTC)
    now_wire = _wire(now)
    old_wire = _wire(now - timedelta(minutes=10))
    recent_wire = _wire(now - timedelta(seconds=30))
    job_ids: list[str] = []
    worker_ids: list[str] = []

    def enqueue(label: str, *, max_attempts: int = 5):
        job = _job(f"{label}-{suffix}", old_wire, max_attempts=max_attempts)
        job_ids.append(job["job_id"])
        return queue.enqueue(job)

    try:
        recent = enqueue("recent")
        queue.claim_next_job("p9-s09-recent", updated_at=recent_wire)
        assert store.recover_stale(observed_at=now_wire, stale_after_seconds=60) == ()
        assert queue.get_job(recent["job_id"])["status"] == "RUNNING"

        live = enqueue("live")
        queue.claim_next_job("p9-s09-live", updated_at=old_wire)
        worker_ids.append("p9-s09-live")
        persistence.worker_heartbeat_store.upsert_heartbeat(
            {
                "heartbeat_schema_version": "worker_heartbeat.v1",
                "service_id": "nex-wa",
                "worker_id": "p9-s09-live",
                "worker_type": "wa.evidence_consumer",
                "status": "BUSY",
                "active_job_id": live["job_id"],
                "trace_id": "9" * 32,
                "started_at": old_wire,
                "last_seen_at": now_wire,
                "metadata": {},
            }
        )
        assert store.recover_stale(observed_at=now_wire, stale_after_seconds=60) == ()

        recoverable = enqueue("recover")
        old_queue = WaFencedJobQueue(queue, store)
        old_queue.claim_next_job("p9-s09-old", updated_at=old_wire)
        recovered = store.recover_stale(observed_at=now_wire, stale_after_seconds=60)
        assert recovered == (
            {
                "job_id": recoverable["job_id"],
                "previous_worker_id": "p9-s09-old",
                "previous_locked_at": old_wire,
                "status": "QUEUED",
                "action": "REQUEUED",
            },
        )
        for operation in (
            lambda: old_queue.complete_job(recoverable["job_id"], updated_at=now_wire),
            lambda: old_queue.fail_job(recoverable["job_id"], updated_at=now_wire),
            lambda: old_queue.retry_job(recoverable["job_id"], failed_at=now_wire),
        ):
            with pytest.raises(WaJobRecoveryError) as caught:
                operation()
            assert caught.value.error_code == WA_JOB_OWNERSHIP_LOST
        new_queue = WaFencedJobQueue(queue, store)
        new_queue.claim_next_job("p9-s09-new", updated_at=now_wire)
        assert new_queue.complete_job(recoverable["job_id"], updated_at=now_wire)[
            "status"
        ] == "SUCCEEDED"

        exhausted = enqueue("exhausted", max_attempts=1)
        queue.claim_next_job("p9-s09-exhausted", updated_at=old_wire)
        exhausted_result = store.recover_stale(
            observed_at=now_wire, stale_after_seconds=60
        )
        assert exhausted_result[0]["action"] == "DEAD_LETTERED"
        assert queue.get_job(exhausted["job_id"])["status"] == "FAILED"

        racing = enqueue("racing")
        queue.claim_next_job("p9-s09-racing", updated_at=old_wire)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = tuple(
                executor.map(
                    lambda _: store.recover_stale(
                        observed_at=now_wire, stale_after_seconds=60, limit=1
                    ),
                    range(2),
                )
            )
        flattened = tuple(item for result in results for item in result)
        assert len(flattened) == 1
        assert flattened[0]["job_id"] == racing["job_id"]
        assert queue.get_job(racing["job_id"])["status"] == "QUEUED"
    finally:
        with persistence.worker_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM service_jobs WHERE job_id = ANY(:job_ids)"),
                {"job_ids": job_ids},
            )
            connection.execute(
                text(
                    "DELETE FROM service_worker_heartbeats "
                    "WHERE service_id='nex-wa' AND worker_id = ANY(:worker_ids)"
                ),
                {"worker_ids": worker_ids},
            )
        with persistence.worker_engine.connect() as connection:
            assert connection.execute(
                text("SELECT count(*) FROM service_jobs WHERE job_id = ANY(:job_ids)"),
                {"job_ids": job_ids},
            ).scalar_one() == 0
        persistence.dispose()
