from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import nex_ae_api.runtime_jobs as runtime_module
import pytest
from jsonschema import Draft202012Validator, FormatChecker
from nex_ae_api.runtime_jobs import (
    P4_RUNTIME_JOB_TYPES,
    RUNTIME_ATTEMPT_OUTCOMES,
    RUNTIME_JOB_STATES,
    RuntimeJobError,
    SqlAlchemyRuntimeJobQueue,
)
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "database/nex-ae-api/migrations/2004_ae_runtime_job.sql"
FROZEN_ROOT = ROOT / (
    "docs/frozen/v2.1/10_PLATFORM_v2.1/03_NORMATIVE_V2_1_CONTRACTS/"
    "NeX_Platform_v2.1_Controlled_Amendment_Batch02_CP02_CP06/AE"
)
JOB_SCHEMA = FROZEN_ROOT / "runtime-job-v2.1.schema.json"
ATTEMPT_SCHEMA = FROZEN_ROOT / "runtime-job-attempt-v2.1.schema.json"

TENANT = "tenant-a"
EXECUTION_ID = "11111111-1111-4111-8111-111111111111"
JOB_ID = "22222222-2222-4222-8222-222222222222"
CONTINUE_JOB_ID = "33333333-3333-4333-8333-333333333333"
NOW = "2026-10-13T03:00:00Z"
LATER = "2026-10-13T03:01:00Z"


def _session_factory(*, with_schema: bool = True):
    engine = create_engine("sqlite+pysqlite://", future=True)
    if with_schema:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE ae_agent_execution (
                        tenant_id TEXT NOT NULL,
                        agent_execution_id TEXT NOT NULL,
                        PRIMARY KEY (tenant_id, agent_execution_id)
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE ae_runtime_job (
                        tenant_id TEXT NOT NULL, runtime_job_id TEXT NOT NULL,
                        job_type TEXT NOT NULL, execution_id TEXT NOT NULL,
                        executable_step_id TEXT, wait_id TEXT,
                        reconciliation_id TEXT, result_delivery_id TEXT,
                        publication_reconciliation_id TEXT, state TEXT NOT NULL,
                        dedup_key TEXT NOT NULL, attempt_no INTEGER NOT NULL,
                        run_after TEXT NOT NULL, lease_owner TEXT,
                        lease_token TEXT, lease_until TEXT, payload_json TEXT NOT NULL,
                        correlation_id TEXT NOT NULL, causation_id TEXT,
                        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                        PRIMARY KEY (tenant_id, runtime_job_id),
                        UNIQUE (tenant_id, dedup_key)
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE ae_runtime_job_attempt (
                        attempt_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
                        runtime_job_id TEXT NOT NULL, attempt_no INTEGER NOT NULL,
                        worker_id TEXT NOT NULL, lease_token TEXT NOT NULL,
                        started_at TEXT NOT NULL, ended_at TEXT, outcome TEXT NOT NULL,
                        error_ref TEXT, retry_disposition_ref TEXT,
                        UNIQUE (tenant_id, runtime_job_id, attempt_no)
                    )
                    """
                )
            )
            connection.execute(
                text("INSERT INTO ae_agent_execution VALUES (:tenant, :execution)"),
                {"tenant": TENANT, "execution": EXECUTION_ID},
            )
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _ids(*values: str):
    items = iter(values)
    return lambda: next(items)


def _queue(*, sessions=None, ids=()):
    return SqlAlchemyRuntimeJobQueue(
        sessions or _session_factory(),
        id_factory=_ids(*ids) if ids else None,
    )


def _enqueue(queue, **overrides):
    values = {
        "tenant_id": TENANT,
        "runtime_job_id": JOB_ID,
        "job_type": "START_EXECUTION",
        "execution_id": EXECUTION_ID,
        "dedup_key": f"start:{EXECUTION_ID}",
        "run_after": NOW,
        "correlation_id": "correlation-a",
        "now": NOW,
        "payload": {"interaction_ref": "interaction-a"},
    }
    return queue.enqueue_unique(**{**values, **overrides})


def _claim(queue, **overrides):
    values = {
        "tenant_id": TENANT,
        "worker_id": "worker-a",
        "lease_seconds": 30,
        "now": NOW,
    }
    return queue.claim(**{**values, **overrides})


def _validator(path: Path):
    return Draft202012Validator(
        json.loads(path.read_text(encoding="utf-8")),
        format_checker=FormatChecker(),
    )


def test_enqueue_is_frozen_compatible_project_neutral_and_idempotent() -> None:
    queue = _queue()
    created = _enqueue(queue)
    duplicate = _enqueue(
        queue,
        runtime_job_id="99999999-9999-4999-8999-999999999999",
    )

    assert duplicate == created
    assert created["schema_version"] == "2.1"
    assert created["state"] == "QUEUED"
    assert created["attempt_no"] == 0
    assert created["execution_id"] == EXECUTION_ID
    assert created["payload"] == {"interaction_ref": "interaction-a"}
    assert created["lease_owner"] is None
    assert not list(_validator(JOB_SCHEMA).iter_errors(created))
    assert queue.get(TENANT, JOB_ID) == created


def test_continue_job_uses_same_execution_and_stable_step_reference() -> None:
    queue = _queue()
    continued = _enqueue(
        queue,
        runtime_job_id=CONTINUE_JOB_ID,
        job_type="CONTINUE_EXECUTION",
        dedup_key=f"continue:{EXECUTION_ID}:step-a:completion-a",
        executable_step_id="step-a",
        causation_id="provider-completion-a",
        payload={"completion_ref": "completion-a"},
    )

    assert continued["job_type"] == "CONTINUE_EXECUTION"
    assert continued["execution_id"] == EXECUTION_ID
    assert continued["executable_step_id"] == "step-a"
    assert continued["causation_id"] == "provider-completion-a"


def test_enqueue_rejects_orphan_reserved_type_private_payload_and_conflict() -> None:
    queue = _queue()
    with pytest.raises(RuntimeJobError) as orphan:
        _enqueue(queue, execution_id="missing")
    assert orphan.value.error_code == "ae.runtime_job_execution_not_found"

    with pytest.raises(RuntimeJobError) as reserved:
        _enqueue(queue, job_type="RETRY_EXECUTION")
    assert reserved.value.error_code == "ae.runtime_job_invalid"

    for payload in (
        {"prompt": "private"},
        {"nested": [{"response": "private"}]},
        {"reference": {1, 2}},
    ):
        with pytest.raises(RuntimeJobError) as invalid:
            _enqueue(queue, payload=payload)
        assert invalid.value.error_code == "ae.runtime_job_invalid"

    created = _enqueue(queue)
    with pytest.raises(RuntimeJobError) as conflict:
        _enqueue(queue, correlation_id="correlation-b")
    assert conflict.value.error_code == "ae.runtime_job_dedup_conflict"
    assert queue.get(TENANT, JOB_ID) == created


def test_claim_and_complete_record_valid_attempt_and_clear_lease() -> None:
    queue = _queue(ids=("lease-a", "attempt-a"))
    _enqueue(queue)
    claim = _claim(queue)

    assert claim is not None
    assert claim.job["state"] == "RUNNING"
    assert claim.job["lease_owner"] == "worker-a"
    assert claim.job["lease_token"] == "lease-a"
    assert claim.job["lease_until"] == "2026-10-13T03:00:30Z"
    assert claim.attempt["outcome"] == "RUNNING"
    assert not list(_validator(JOB_SCHEMA).iter_errors(claim.job))
    assert not list(_validator(ATTEMPT_SCHEMA).iter_errors(claim.attempt))

    done = queue.complete(
        tenant_id=TENANT,
        runtime_job_id=JOB_ID,
        worker_id="worker-a",
        lease_token="lease-a",
        now="2026-10-13T03:00:20Z",
    )
    assert done["state"] == "DONE"
    assert done["lease_token"] is None
    attempts = queue.list_attempts(TENANT, JOB_ID)
    assert attempts[0]["outcome"] == "DONE"
    assert attempts[0]["ended_at"] == "2026-10-13T03:00:20Z"
    assert not list(_validator(ATTEMPT_SCHEMA).iter_errors(attempts[0]))


def test_claim_respects_schedule_tenant_and_input_boundaries() -> None:
    queue = _queue()
    _enqueue(queue, run_after=LATER)
    assert _claim(queue) is None
    assert _claim(queue, tenant_id="tenant-b", now=LATER) is None

    for lease_seconds in (0, True, 1.5):
        with pytest.raises(RuntimeJobError) as invalid:
            _claim(queue, lease_seconds=lease_seconds)
        assert invalid.value.error_code == "ae.runtime_job_invalid"


def test_expired_lease_is_reclaimed_and_stale_worker_is_rejected() -> None:
    queue = _queue(ids=("lease-a", "attempt-a", "lease-b", "attempt-b"))
    _enqueue(queue)
    first = _claim(queue, lease_seconds=10)
    assert first is not None

    second = _claim(queue, worker_id="worker-b", now="2026-10-13T03:00:11Z")
    assert second is not None
    assert second.job["attempt_no"] == 2
    assert second.job["execution_id"] == first.job["execution_id"]
    assert [item["outcome"] for item in queue.list_attempts(TENANT, JOB_ID)] == [
        "LEASE_EXPIRED",
        "RUNNING",
    ]

    with pytest.raises(RuntimeJobError) as stale:
        queue.complete(
            tenant_id=TENANT,
            runtime_job_id=JOB_ID,
            worker_id="worker-a",
            lease_token="lease-a",
            now="2026-10-13T03:00:12Z",
        )
    assert stale.value.error_code == "ae.runtime_job_stale_lease"
    assert stale.value.retryable is True

    completed = queue.complete(
        tenant_id=TENANT,
        runtime_job_id=JOB_ID,
        worker_id="worker-b",
        lease_token="lease-b",
        now="2026-10-13T03:00:20Z",
    )
    assert completed["state"] == "DONE"


def test_retry_and_dead_letter_keep_same_job_and_execution() -> None:
    queue = _queue(ids=("lease-a", "attempt-a", "lease-b", "attempt-b"))
    _enqueue(queue)
    first = _claim(queue)
    assert first is not None
    queued = queue.fail(
        tenant_id=TENANT,
        runtime_job_id=JOB_ID,
        worker_id="worker-a",
        lease_token="lease-a",
        now="2026-10-13T03:00:10Z",
        error_ref="error-a",
        retry_at="2026-10-13T03:01:00Z",
        retry_disposition_ref="retry-safe",
        max_attempts=2,
    )
    assert queued["state"] == "QUEUED"
    assert queued["runtime_job_id"] == JOB_ID
    assert queued["execution_id"] == EXECUTION_ID
    assert _claim(queue, now="2026-10-13T03:00:59Z") is None

    second = _claim(queue, worker_id="worker-b", now=LATER)
    assert second is not None
    dead = queue.fail(
        tenant_id=TENANT,
        runtime_job_id=JOB_ID,
        worker_id="worker-b",
        lease_token="lease-b",
        now="2026-10-13T03:01:10Z",
        error_ref="error-b",
        retry_at="2026-10-13T03:02:00Z",
        max_attempts=2,
    )
    assert dead["state"] == "DEAD_LETTER"
    attempts = queue.list_attempts(TENANT, JOB_ID)
    assert [item["outcome"] for item in attempts] == ["FAILED", "FAILED"]
    assert attempts[0]["retry_disposition_ref"] == "retry-safe"


def test_non_retry_failure_and_missing_job_are_typed() -> None:
    queue = _queue(ids=("lease-a", "attempt-a"))
    with pytest.raises(RuntimeJobError) as missing:
        queue.fail(
            tenant_id=TENANT,
            runtime_job_id=JOB_ID,
            worker_id="worker-a",
            lease_token="lease-a",
            now=NOW,
            error_ref="error-a",
        )
    assert missing.value.error_code == "ae.runtime_job_not_found"

    _enqueue(queue)
    assert _claim(queue) is not None
    failed = queue.fail(
        tenant_id=TENANT,
        runtime_job_id=JOB_ID,
        worker_id="worker-a",
        lease_token="lease-a",
        now="2026-10-13T03:00:10Z",
        error_ref="error-a",
    )
    assert failed["state"] == "FAILED"
    with pytest.raises(RuntimeJobError) as terminal:
        queue.cancel(tenant_id=TENANT, runtime_job_id=JOB_ID, now=LATER)
    assert terminal.value.error_code == "ae.runtime_job_terminal"


def test_cancel_is_idempotent_for_queued_and_closes_running_attempt() -> None:
    queued = _queue()
    _enqueue(queued)
    cancelled = queued.cancel(tenant_id=TENANT, runtime_job_id=JOB_ID, now=NOW)
    assert cancelled["state"] == "CANCELLED"
    assert queued.cancel(tenant_id=TENANT, runtime_job_id=JOB_ID, now=NOW) == cancelled

    running = _queue(ids=("lease-a", "attempt-a"))
    _enqueue(running)
    assert _claim(running) is not None
    with pytest.raises(RuntimeJobError) as stale:
        running.cancel(
            tenant_id=TENANT,
            runtime_job_id=JOB_ID,
            worker_id="wrong-worker",
            lease_token="lease-a",
            now="2026-10-13T03:00:10Z",
        )
    assert stale.value.error_code == "ae.runtime_job_stale_lease"
    cancelled_running = running.cancel(
        tenant_id=TENANT,
        runtime_job_id=JOB_ID,
        worker_id="worker-a",
        lease_token="lease-a",
        now="2026-10-13T03:00:10Z",
    )
    assert cancelled_running["state"] == "CANCELLED"
    assert running.list_attempts(TENANT, JOB_ID)[0]["outcome"] == "CANCELLED"


@pytest.mark.parametrize(
    "operation",
    (
        lambda queue: _enqueue(queue, runtime_job_id=""),
        lambda queue: _enqueue(queue, run_after="not-a-time"),
        lambda queue: _enqueue(queue, now="2026-10-13T03:00:00"),
        lambda queue: queue.fail(
            tenant_id=TENANT,
            runtime_job_id=JOB_ID,
            worker_id="worker-a",
            lease_token="lease-a",
            now=NOW,
            error_ref="error-a",
            max_attempts=True,
        ),
    ),
)
def test_invalid_inputs_fail_before_database_mutation(operation) -> None:
    queue = _queue()
    with pytest.raises(RuntimeJobError) as invalid:
        operation(queue)
    assert invalid.value.error_code == "ae.runtime_job_invalid"


def test_repository_wraps_database_failures() -> None:
    queue = _queue(sessions=_session_factory(with_schema=False))
    with pytest.raises(RuntimeJobError) as read_failure:
        queue.get(TENANT, JOB_ID)
    assert read_failure.value.error_code == "ae.runtime_job_store_unavailable"
    assert read_failure.value.retryable is True
    assert str(read_failure.value) == "AE RuntimeJob store is unavailable."
    with pytest.raises(RuntimeJobError):
        _enqueue(queue)
    with pytest.raises(RuntimeJobError):
        _claim(queue)
    with pytest.raises(RuntimeJobError):
        queue.list_attempts(TENANT, JOB_ID)


def test_reload_and_attempt_conflicts_are_fail_closed(monkeypatch) -> None:
    queue = _queue(ids=("lease-a", "attempt-a"))
    monkeypatch.setattr(runtime_module, "_load_by_dedup", lambda *args: None)
    with pytest.raises(RuntimeJobError) as enqueue_failure:
        _enqueue(queue)
    assert enqueue_failure.value.error_code == "ae.runtime_job_write_conflict"

    monkeypatch.undo()
    sessions = _session_factory()
    queue = _queue(sessions=sessions, ids=("lease-a", "attempt-a"))
    _enqueue(queue)
    with sessions.begin() as session:
        session.execute(
            text(
                """
                UPDATE ae_runtime_job
                SET state='RUNNING', attempt_no=1, lease_owner='worker-a',
                    lease_token='lease-a', lease_until='2026-10-13T02:59:00Z'
                WHERE tenant_id=:tenant AND runtime_job_id=:job
                """
            ),
            {"tenant": TENANT, "job": JOB_ID},
        )
    with pytest.raises(RuntimeJobError) as missing_attempt:
        _claim(queue, worker_id="worker-b")
    assert missing_attempt.value.error_code == "ae.runtime_job_attempt_conflict"


def test_claim_race_and_post_claim_reload_fail_closed(monkeypatch) -> None:
    queue = _queue(ids=("lease-a", "attempt-a"))
    _enqueue(queue)
    candidate = queue.get(TENANT, JOB_ID)
    assert candidate is not None
    with queue._session_factory.begin() as session:
        session.execute(text("DELETE FROM ae_runtime_job"))
    monkeypatch.setattr(runtime_module, "_select_runnable", lambda *args: candidate)
    assert _claim(queue) is None

    monkeypatch.undo()
    queue = _queue(ids=("lease-a", "attempt-a"))
    _enqueue(queue)
    monkeypatch.setattr(runtime_module, "_load_attempt", lambda *args: None)
    with pytest.raises(RuntimeJobError) as reload_failure:
        _claim(queue)
    assert reload_failure.value.error_code == "ae.runtime_job_write_conflict"


def test_cancel_missing_reload_and_store_failures_are_typed(monkeypatch) -> None:
    queue = _queue()
    with pytest.raises(RuntimeJobError) as missing:
        queue.cancel(tenant_id=TENANT, runtime_job_id=JOB_ID, now=NOW)
    assert missing.value.error_code == "ae.runtime_job_not_found"

    _enqueue(queue)
    monkeypatch.setattr(runtime_module, "_load_job", lambda *args: None)
    with pytest.raises(RuntimeJobError) as reload_failure:
        queue.cancel(tenant_id=TENANT, runtime_job_id=JOB_ID, now=NOW)
    assert reload_failure.value.error_code == "ae.runtime_job_write_conflict"

    unavailable = _queue(sessions=_session_factory(with_schema=False))
    with pytest.raises(RuntimeJobError) as store_failure:
        unavailable.cancel(tenant_id=TENANT, runtime_job_id=JOB_ID, now=NOW)
    assert store_failure.value.error_code == "ae.runtime_job_store_unavailable"

    monkeypatch.undo()
    queue = _queue(ids=("lease-a", "attempt-a"))
    _enqueue(queue)
    assert _claim(queue) is not None
    monkeypatch.setattr(
        runtime_module,
        "_ATTEMPT_FINISH_SQL",
        "UPDATE ae_runtime_job_attempt SET outcome='CANCELLED' WHERE 1=0",
    )
    with pytest.raises(RuntimeJobError) as attempt_conflict:
        queue.cancel(
            tenant_id=TENANT,
            runtime_job_id=JOB_ID,
            worker_id="worker-a",
            lease_token="lease-a",
            now="2026-10-13T03:00:10Z",
        )
    assert attempt_conflict.value.error_code == "ae.runtime_job_write_conflict"


def test_finish_missing_conflict_reload_and_store_failures_are_typed(monkeypatch) -> None:
    queue = _queue()
    with pytest.raises(RuntimeJobError) as missing:
        queue.complete(
            tenant_id=TENANT,
            runtime_job_id=JOB_ID,
            worker_id="worker-a",
            lease_token="lease-a",
            now=NOW,
        )
    assert missing.value.error_code == "ae.runtime_job_not_found"

    queue = _queue(ids=("lease-a", "attempt-a"))
    _enqueue(queue)
    assert _claim(queue) is not None
    monkeypatch.setattr(
        runtime_module,
        "_ATTEMPT_FINISH_SQL",
        "UPDATE ae_runtime_job_attempt SET outcome='DONE' WHERE 1=0",
    )
    with pytest.raises(RuntimeJobError) as write_conflict:
        queue.complete(
            tenant_id=TENANT,
            runtime_job_id=JOB_ID,
            worker_id="worker-a",
            lease_token="lease-a",
            now="2026-10-13T03:00:10Z",
        )
    assert write_conflict.value.error_code == "ae.runtime_job_write_conflict"

    monkeypatch.undo()
    queue = _queue(ids=("lease-a", "attempt-a"))
    _enqueue(queue)
    assert _claim(queue) is not None
    monkeypatch.setattr(runtime_module, "_load_job", lambda *args: None)
    with pytest.raises(RuntimeJobError) as reload_failure:
        queue.complete(
            tenant_id=TENANT,
            runtime_job_id=JOB_ID,
            worker_id="worker-a",
            lease_token="lease-a",
            now="2026-10-13T03:00:10Z",
        )
    assert reload_failure.value.error_code == "ae.runtime_job_write_conflict"

    unavailable = _queue(sessions=_session_factory(with_schema=False))
    with pytest.raises(RuntimeJobError) as store_failure:
        unavailable.complete(
            tenant_id=TENANT,
            runtime_job_id=JOB_ID,
            worker_id="worker-a",
            lease_token="lease-a",
            now=NOW,
        )
    assert store_failure.value.error_code == "ae.runtime_job_store_unavailable"


def test_validation_and_list_runtime_error_branches(monkeypatch) -> None:
    queue = _queue(ids=("lease-a", "attempt-a"))
    with pytest.raises(RuntimeJobError):
        queue.get("", JOB_ID)
    with pytest.raises(RuntimeJobError):
        _enqueue(queue, now=None)

    _enqueue(queue, payload={"refs": [], "tuple_refs": ("a",)})
    assert _claim(queue) is not None

    def fail_mapping(row):
        raise RuntimeJobError("ae.runtime_job_mapping_failed", "mapping failed")

    monkeypatch.setattr(runtime_module, "_attempt_from_row", fail_mapping)
    with pytest.raises(RuntimeJobError) as mapping_failure:
        queue.list_attempts(TENANT, JOB_ID)
    assert mapping_failure.value.error_code == "ae.runtime_job_mapping_failed"


def test_frozen_vocab_and_migration_are_canonical_and_compact() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS ae_runtime_job (" in sql
    assert "CREATE TABLE IF NOT EXISTS ae_runtime_job_attempt (" in sql
    assert "FOR UPDATE SKIP LOCKED" in Path(runtime_module.__file__).read_text(
        encoding="utf-8"
    )
    assert "UNIQUE (tenant_id, dedup_key)" in sql
    assert "2004_ae_runtime_job" in sql
    assert P4_RUNTIME_JOB_TYPES == {"START_EXECUTION", "CONTINUE_EXECUTION"}
    for value in RUNTIME_JOB_STATES | RUNTIME_ATTEMPT_OUTCOMES:
        assert f"'{value}'" in sql
    for table in ("ae_runtime_job", "ae_runtime_job_attempt"):
        assert len(table) <= 30


def test_timestamp_helper_accepts_offsets_and_default_uuid_factories() -> None:
    queue = _queue()
    created = _enqueue(
        queue,
        run_after="2026-10-13T12:00:00+09:00",
        now="2026-10-13T12:00:00+09:00",
    )
    assert created["run_after"] == NOW
    claimed = _claim(queue)
    assert claimed is not None
    UUID(claimed.job["lease_token"])
