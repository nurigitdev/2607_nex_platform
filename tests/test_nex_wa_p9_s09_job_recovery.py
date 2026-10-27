from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from nex_runtime import (
    InMemoryWorkerHeartbeatStore,
    JobRetryPolicy,
    ServiceLogEmitter,
    SqlAlchemyJobQueue,
    WorkerHeartbeatEmitter,
    build_common_job,
)
from nex_runtime.service_logs import InMemoryServiceLogStore
from nex_wa import (
    WA_JOB_OWNERSHIP_LOST,
    SqlAlchemyWaJobFenceStore,
    WaConfigurationError,
    WaFencedJobQueue,
    WaJobRecoveryError,
    load_wa_settings,
    normalize_stale_job_seconds,
    run_wa_evidence_consumer_once,
)
from nex_wa.source_adapters import (
    ControlledWaEvidenceSourceAdapter,
    WaEvidenceSourceAdapterRegistry,
)
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
NOW_WIRE = "2026-10-27T12:00:00Z"
OLD_WIRE = "2026-10-27T11:50:00Z"


def _stores(tmp_path: Path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'wa-recovery.db'}")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE service_jobs (
                    job_id TEXT PRIMARY KEY, job_schema_version TEXT NOT NULL,
                    job_type TEXT NOT NULL, status TEXT NOT NULL, trace_id TEXT NOT NULL,
                    request_id TEXT NOT NULL, subject_type TEXT NOT NULL,
                    subject_id TEXT NOT NULL, idempotency_key TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL, max_attempts INTEGER NOT NULL,
                    retryable BOOLEAN NOT NULL, links TEXT NOT NULL, payload TEXT NOT NULL,
                    error TEXT, replay_lineage TEXT, available_at TEXT NOT NULL,
                    locked_at TEXT, locked_by TEXT, started_at TEXT, completed_at TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(job_type, idempotency_key)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE service_worker_heartbeats (
                    service_id TEXT NOT NULL, worker_id TEXT NOT NULL,
                    heartbeat_schema_version TEXT NOT NULL, worker_type TEXT NOT NULL,
                    status TEXT NOT NULL, active_job_id TEXT, trace_id TEXT,
                    started_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
                    metadata TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY(service_id, worker_id)
                )
                """
            )
        )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return engine, SqlAlchemyJobQueue(factory), SqlAlchemyWaJobFenceStore(factory)


def _enqueue(queue: SqlAlchemyJobQueue, *, suffix: str, max_attempts: int = 5):
    job = build_common_job(
        job_id=f"job-{suffix}",
        job_type="WA_EVIDENCE_INGEST",
        trace_id="a" * 32,
        request_id=f"request-{suffix}",
        subject_ref={"type": "WA_EVIDENCE_SOURCE", "id": suffix},
        idempotency_key=f"idem-{suffix}",
        max_attempts=max_attempts,
        created_at=OLD_WIRE,
    )
    job["payload"] = {
        "schema_version": "wa_evidence_intake_request.v1",
        "tenant_id": "VO00",
        "source_type": "AE_AGENT_RESULT",
        "source_ref": suffix,
        "source_revision_ref": "result-1",
        "source_hash": "sha256:" + "9" * 64,
        "occurred_at": NOW_WIRE,
        "correlation_id": f"corr-{suffix}",
    }
    return queue.enqueue(job)


def _heartbeat_and_log(worker_id: str):
    heartbeat = WorkerHeartbeatEmitter(
        service_id="nex-wa",
        worker_id=worker_id,
        worker_type="wa.evidence_consumer",
        store=InMemoryWorkerHeartbeatStore(),
        started_at=NOW_WIRE,
    )
    logger = ServiceLogEmitter(
        service_id="nex-wa",
        logger_name="nex-wa-evidence-consumer",
        store=InMemoryServiceLogStore(),
    )
    return heartbeat, logger


def _registry():
    return WaEvidenceSourceAdapterRegistry(
        {
            name: ControlledWaEvidenceSourceAdapter(name)
            for name in ("AE_AGENT_RESULT", "AE_ARTIFACT")
        }
    )


def test_stale_job_configuration_is_bounded() -> None:
    assert normalize_stale_job_seconds(60) == 60
    assert normalize_stale_job_seconds(3600) == 3600
    assert load_wa_settings({"NEX_WA_STALE_JOB_SECONDS": "600"}).stale_job_seconds == 600
    for value in (True, 59, 3601):
        with pytest.raises(WaJobRecoveryError) as caught:
            normalize_stale_job_seconds(value)  # type: ignore[arg-type]
        assert caught.value.error_code == "WA_STALE_JOB_SECONDS_INVALID"
    with pytest.raises(WaConfigurationError):
        load_wa_settings({"NEX_WA_STALE_JOB_SECONDS": "not-an-int"})
    with pytest.raises(WaConfigurationError):
        load_wa_settings({"NEX_WA_STALE_JOB_SECONDS": "59"})


def test_false_stale_is_refused_for_recent_lock_or_live_heartbeat(tmp_path: Path) -> None:
    engine, queue, store = _stores(tmp_path)
    recent = _enqueue(queue, suffix="recent")
    queue.claim_next_job("recent-worker", updated_at="2026-10-27T11:59:30Z")
    old = _enqueue(queue, suffix="live-heartbeat")
    queue.claim_next_job("live-worker", updated_at=OLD_WIRE)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO service_worker_heartbeats
                (service_id, worker_id, heartbeat_schema_version, worker_type, status,
                 active_job_id, trace_id, started_at, last_seen_at, metadata,
                 created_at, updated_at)
                VALUES ('nex-wa', 'live-worker', 'worker_heartbeat.v1',
                        'wa.evidence_consumer', 'BUSY', :job_id, :trace_id,
                        :now, :now, '{}', :now, :now)
                """
            ),
            {"job_id": old["job_id"], "trace_id": "a" * 32, "now": NOW_WIRE},
        )

    assert store.recover_stale(observed_at=NOW_WIRE, stale_after_seconds=60) == ()
    assert queue.get_job(recent["job_id"])["status"] == "RUNNING"
    assert queue.get_job(old["job_id"])["status"] == "RUNNING"
    with pytest.raises(WaJobRecoveryError):
        store.recover_stale(observed_at=NOW_WIRE, limit=0)
    engine.dispose()


def test_stale_requeue_fences_old_worker_and_new_owner_completes(tmp_path: Path) -> None:
    engine, queue, store = _stores(tmp_path)
    job = _enqueue(queue, suffix="requeue")
    old_queue = WaFencedJobQueue(queue, store)
    assert old_queue.claim_next_job("old-worker", updated_at=OLD_WIRE) is not None

    recovered = store.recover_stale(observed_at=NOW_WIRE, stale_after_seconds=60)
    assert recovered[0]["action"] == "REQUEUED"
    assert queue.get_job(job["job_id"])["status"] == "QUEUED"
    for operation in (
        lambda: old_queue.complete_job(job["job_id"], updated_at=NOW_WIRE),
        lambda: old_queue.fail_job(job["job_id"], updated_at=NOW_WIRE),
        lambda: old_queue.retry_job(job["job_id"], failed_at=NOW_WIRE),
    ):
        with pytest.raises(WaJobRecoveryError) as caught:
            operation()
        assert caught.value.error_code == WA_JOB_OWNERSHIP_LOST

    new_queue = WaFencedJobQueue(queue, store)
    assert new_queue.claim_next_job("new-worker", updated_at=NOW_WIRE) is not None
    assert new_queue.complete_job(job["job_id"], updated_at=NOW_WIRE)["status"] == "SUCCEEDED"
    engine.dispose()


def test_exhausted_stale_job_is_dead_lettered(tmp_path: Path) -> None:
    engine, queue, store = _stores(tmp_path)
    job = _enqueue(queue, suffix="exhausted", max_attempts=1)
    queue.claim_next_job("lost-worker", updated_at=OLD_WIRE)

    recovered = store.recover_stale(observed_at=NOW_WIRE, stale_after_seconds=60)
    current = queue.get_job(job["job_id"])
    assert recovered[0]["action"] == "DEAD_LETTERED"
    assert current["status"] == "FAILED"
    assert current["retryable"] is False
    assert current["error"]["dead_lettered"] is True
    engine.dispose()


def test_fenced_queue_retry_dead_letter_and_consumer_success(tmp_path: Path) -> None:
    engine, queue, store = _stores(tmp_path)
    fenced = WaFencedJobQueue(queue, store)
    retry_job = _enqueue(queue, suffix="retry")
    fenced.claim_next_job("retry-worker", updated_at=OLD_WIRE)
    retried = fenced.retry_job(
        retry_job["job_id"],
        failed_at=NOW_WIRE,
        policy=JobRetryPolicy(initial_delay_seconds=0, max_delay_seconds=0),
    )
    assert retried["status"] == "QUEUED"

    dead_job = _enqueue(queue, suffix="dead")
    fenced.claim_next_job("dead-worker", updated_at=NOW_WIRE)
    assert fenced.dead_letter_job(dead_job["job_id"], failed_at=NOW_WIRE)["status"] == "FAILED"

    success = _enqueue(queue, suffix="consumer")
    heartbeat, logger = _heartbeat_and_log("consumer-worker")
    result = run_wa_evidence_consumer_once(
        queue=WaFencedJobQueue(queue, store),
        registry=_registry(),
        heartbeat_emitter=heartbeat,
        service_log_emitter=logger,
        worker_id="consumer-worker",
        clock=lambda: NOW_WIRE,
    )
    assert result.status == "SUCCEEDED"
    assert queue.get_job(success["job_id"])["status"] == "SUCCEEDED"
    with pytest.raises(WaJobRecoveryError):
        fenced.complete_job("not-claimed", updated_at=NOW_WIRE)
    engine.dispose()


def test_claim_capture_and_recovery_inputs_fail_closed(tmp_path: Path) -> None:
    engine, queue, store = _stores(tmp_path)
    fenced = WaFencedJobQueue(queue, store)
    assert fenced.claim_next_job("idle-worker", updated_at=NOW_WIRE) is None
    with pytest.raises(WaJobRecoveryError) as missing:
        store.capture_claim("missing", worker_id="worker")
    assert missing.value.error_code == WA_JOB_OWNERSHIP_LOST

    queued = _enqueue(queue, suffix="capture")
    with pytest.raises(WaJobRecoveryError):
        store.capture_claim(queued["job_id"], worker_id="worker")
    queue.claim_next_job("owner", updated_at=OLD_WIRE)
    with pytest.raises(WaJobRecoveryError):
        store.capture_claim(queued["job_id"], worker_id="other")
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE service_jobs SET locked_at=NULL WHERE job_id=:job_id"),
            {"job_id": queued["job_id"]},
        )
    with pytest.raises(WaJobRecoveryError):
        store.capture_claim(queued["job_id"], worker_id="owner")

    for kwargs in (
        {"observed_at": "invalid"},
        {"observed_at": NOW_WIRE, "limit": True},
        {"observed_at": NOW_WIRE, "limit": 501},
    ):
        with pytest.raises(WaJobRecoveryError):
            store.recover_stale(**kwargs)  # type: ignore[arg-type]
    assert store.recover_stale(observed_at=NOW, stale_after_seconds=60) == ()
    engine.dispose()


def test_fenced_queue_fail_and_delegate_surface(tmp_path: Path) -> None:
    engine, queue, store = _stores(tmp_path)
    fenced = WaFencedJobQueue(queue, store)
    job = _enqueue(queue, suffix="failed")
    assert fenced.get_job(job["job_id"])["status"] == "QUEUED"
    assert len(fenced.list_jobs(status="QUEUED")) == 1
    fenced.claim_next_job("failure-worker", updated_at=OLD_WIRE)
    assert fenced.fail_job(job["job_id"], updated_at=NOW_WIRE)["status"] == "FAILED"

    cancelled = _enqueue(queue, suffix="cancelled")
    assert fenced.cancel_job(cancelled["job_id"], updated_at=NOW_WIRE)[
        "status"
    ] == "CANCELLED"
    engine.dispose()
