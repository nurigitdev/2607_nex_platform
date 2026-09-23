from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text

from nex_runtime import (
    InMemoryJobQueue,
    JobQueueError,
    SqlAlchemyJobQueue,
    build_common_job,
    build_engine,
    build_session_factory,
    build_subject_ref,
)
from nex_cx.worker_leases import (
    CxWorkerLeaseError,
    CxWorkerLeasePolicy,
    SqlAlchemyCxWorkerLeaseStore,
    _lease_projection,
    _renewal_conflict,
    _timestamp,
    claim_next_worker_execution,
)
import nex_cx.worker_leases as worker_leases


NOW = "2026-09-23T01:00:00Z"
LATER = "2026-09-23T01:00:30Z"
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "09740000-0000-4000-8000-000000000001"


def _stores() -> tuple[SqlAlchemyJobQueue, SqlAlchemyCxWorkerLeaseStore]:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE service_jobs (
                    job_id TEXT PRIMARY KEY,
                    job_schema_version TEXT NOT NULL,
                    job_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    subject_type TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL,
                    max_attempts INTEGER NOT NULL,
                    retryable INTEGER NOT NULL,
                    links TEXT NOT NULL,
                    payload TEXT NOT NULL,
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
    factory = build_session_factory(engine)
    return SqlAlchemyJobQueue(factory), SqlAlchemyCxWorkerLeaseStore(factory)


def _job(**overrides: Any) -> dict[str, Any]:
    return build_common_job(
        job_id=overrides.get("job_id", "job-0974"),
        job_type=overrides.get("job_type", "cx.document_ingestion"),
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
        subject_ref=build_subject_ref("cx.document", "doc-0974"),
        idempotency_key=overrides.get("idempotency_key", "idem-0974"),
        created_at=NOW,
        max_attempts=3,
    )


def test_claims_one_durable_execution_and_excludes_competing_worker() -> None:
    queue, leases = _stores()
    queue.enqueue(_job())

    execution = claim_next_worker_execution(
        job_queue=queue,
        lease_store=leases,
        worker_id="worker-a",
        worker_type="cx.ingestion.worker",
        workload="document_ingestion",
        observed_at=NOW,
    )
    competing = claim_next_worker_execution(
        job_queue=queue,
        lease_store=leases,
        worker_id="worker-b",
        worker_type="cx.ingestion.worker",
        workload="document_ingestion",
        observed_at=NOW,
    )

    assert execution is not None
    assert execution["state"] == "CLAIMED"
    assert execution["worker_id"] == "worker-a"
    assert execution["lease_expires_at"] == "2026-09-23T01:02:00Z"
    assert competing is None
    assert leases.require_active(
        "job-0974", worker_id="worker-a", observed_at=LATER
    )["active"] is True


def test_renews_with_owner_and_compare_and_swap_timestamp() -> None:
    queue, leases = _stores()
    queue.enqueue(_job())
    claim_next_worker_execution(
        job_queue=queue,
        lease_store=leases,
        worker_id="worker-a",
        worker_type="cx.ingestion.worker",
        workload="document_ingestion",
        observed_at=NOW,
    )

    renewed = leases.renew(
        "job-0974",
        worker_id="worker-a",
        expected_locked_at=NOW,
        observed_at=LATER,
        policy=CxWorkerLeasePolicy(ttl_seconds=300),
    )

    assert renewed["locked_at"] == LATER
    assert renewed["expires_at"] == "2026-09-23T01:05:30Z"
    assert renewed["active"] is True
    with pytest.raises(CxWorkerLeaseError) as stale:
        leases.renew(
            "job-0974",
            worker_id="worker-a",
            expected_locked_at=NOW,
            observed_at="2026-09-23T01:00:40Z",
        )
    assert stale.value.error_code == "cx.worker_lease.changed"


def test_active_lease_rejects_wrong_owner_expiry_and_terminal_job() -> None:
    queue, leases = _stores()
    queue.enqueue(_job())
    claim_next_worker_execution(
        job_queue=queue,
        lease_store=leases,
        worker_id="worker-a",
        worker_type="cx.ingestion.worker",
        workload="document_ingestion",
        observed_at=NOW,
    )

    with pytest.raises(CxWorkerLeaseError) as wrong_owner:
        leases.require_active("job-0974", worker_id="worker-b", observed_at=LATER)
    assert wrong_owner.value.error_code == "cx.worker_lease.owner_mismatch"
    with pytest.raises(CxWorkerLeaseError) as expired:
        leases.require_active(
            "job-0974",
            worker_id="worker-a",
            observed_at="2026-09-23T01:02:00Z",
        )
    assert expired.value.error_code == "cx.worker_lease.expired"
    assert expired.value.retryable is True

    queue.complete_job("job-0974", updated_at=LATER)
    with pytest.raises(CxWorkerLeaseError) as terminal:
        leases.require_active("job-0974", worker_id="worker-a", observed_at=LATER)
    assert terminal.value.error_code == "cx.worker_lease.job_not_running"


def test_inspect_and_renewal_fail_closed_for_missing_or_unleased_jobs() -> None:
    queue, leases = _stores()
    assert leases.inspect("missing", observed_at=NOW) is None
    with pytest.raises(CxWorkerLeaseError) as missing:
        leases.require_active("missing", worker_id="worker-a", observed_at=NOW)
    assert missing.value.error_code == "cx.worker_lease.job_not_found"

    queue.enqueue(_job())
    pending = leases.inspect("job-0974", observed_at=NOW)
    assert pending is not None
    assert pending["active"] is False
    assert pending["locked_at"] is None
    with pytest.raises(CxWorkerLeaseError) as unowned:
        leases.require_active("job-0974", worker_id="worker-a", observed_at=NOW)
    assert unowned.value.error_code == "cx.worker_lease.job_not_running"
    with pytest.raises(CxWorkerLeaseError) as renew_missing:
        leases.renew(
            "missing",
            worker_id="worker-a",
            expected_locked_at=NOW,
            observed_at=LATER,
        )
    assert renew_missing.value.error_code == "cx.worker_lease.job_not_found"


def test_validation_and_claim_dependency_failures_are_typed() -> None:
    for ttl in (0, True, 86_401):
        with pytest.raises(CxWorkerLeaseError) as invalid_ttl:
            CxWorkerLeasePolicy(ttl_seconds=ttl)
        assert invalid_ttl.value.error_code == "cx.worker_lease.ttl_invalid"
    with pytest.raises(CxWorkerLeaseError) as invalid_field:
        CxWorkerLeasePolicy()
        _timestamp([], "observed_at")
    assert invalid_field.value.error_code == "cx.worker_lease.timestamp_invalid"
    with pytest.raises(CxWorkerLeaseError) as invalid_text:
        _timestamp("not-a-time", "observed_at")
    assert invalid_text.value.error_code == "cx.worker_lease.timestamp_invalid"

    queue, leases = _stores()
    with pytest.raises(CxWorkerLeaseError) as bad_workload:
        claim_next_worker_execution(
            job_queue=queue,
            lease_store=leases,
            worker_id="worker-a",
            worker_type="cx.worker",
            workload="unknown",
            observed_at=NOW,
        )
    assert bad_workload.value.error_code == "cx.worker_lease.workload_invalid"

    class BrokenQueue(InMemoryJobQueue):
        def claim_next_job(self, *args: Any, **kwargs: Any) -> None:
            raise JobQueueError("job.store_unavailable", "offline", 503)

    with pytest.raises(CxWorkerLeaseError) as unavailable:
        claim_next_worker_execution(
            job_queue=BrokenQueue(),
            lease_store=leases,
            worker_id="worker-a",
            worker_type="cx.worker",
            workload="document_ingestion",
            observed_at=NOW,
        )
    assert unavailable.value.error_code == "cx.worker_lease.claim_failed"
    assert unavailable.value.retryable is True


def test_renew_rejects_regression_owner_change_and_non_running_state() -> None:
    queue, leases = _stores()
    queue.enqueue(_job())
    claim_next_worker_execution(
        job_queue=queue,
        lease_store=leases,
        worker_id="worker-a",
        worker_type="cx.ingestion.worker",
        workload="document_ingestion",
        observed_at=NOW,
    )
    with pytest.raises(CxWorkerLeaseError) as regressed:
        leases.renew(
            "job-0974",
            worker_id="worker-a",
            expected_locked_at=LATER,
            observed_at=NOW,
        )
    assert regressed.value.error_code == "cx.worker_lease.time_regression"
    with pytest.raises(CxWorkerLeaseError) as owner:
        leases.renew(
            "job-0974",
            worker_id="worker-b",
            expected_locked_at=NOW,
            observed_at=LATER,
        )
    assert owner.value.error_code == "cx.worker_lease.owner_mismatch"

    queue.complete_job("job-0974", updated_at=LATER)
    with pytest.raises(CxWorkerLeaseError) as terminal:
        leases.renew(
            "job-0974",
            worker_id="worker-a",
            expected_locked_at=NOW,
            observed_at=LATER,
        )
    assert terminal.value.error_code == "cx.worker_lease.job_not_running"


def test_projection_and_conflict_helpers_cover_datetime_and_unleased_rows() -> None:
    projection = _lease_projection(
        {
            "job_id": "job-1",
            "job_type": "cx.document_processing",
            "status": "RUNNING",
            "locked_by": None,
            "locked_at": None,
        },
        policy=CxWorkerLeasePolicy(),
        observed_at=datetime(2026, 9, 23, 1, tzinfo=UTC),
    )
    assert projection["active"] is False
    assert projection["expires_at"] is None
    assert _timestamp(datetime(2026, 9, 23, 1), "at").tzinfo is UTC
    assert _renewal_conflict(
        {
            "status": "RUNNING",
            "locked_by": "worker-a",
        },
        "worker-a",
    ).error_code == "cx.worker_lease.changed"


def test_active_running_job_without_lock_is_rejected_as_not_acquired() -> None:
    queue, leases = _stores()
    queue.enqueue(_job())
    claim_next_worker_execution(
        job_queue=queue,
        lease_store=leases,
        worker_id="worker-a",
        worker_type="cx.ingestion.worker",
        workload="document_ingestion",
        observed_at=NOW,
    )
    with leases._session_factory.begin() as session:
        session.execute(
            text(
                "UPDATE service_jobs SET locked_at = NULL "
                "WHERE job_id = 'job-0974'"
            )
        )

    with pytest.raises(CxWorkerLeaseError) as unleased:
        leases.require_active("job-0974", worker_id="worker-a", observed_at=LATER)
    assert unleased.value.error_code == "cx.worker_lease.not_acquired"


def test_store_failures_contract_failure_defaults_and_error_string(monkeypatch) -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    broken = SqlAlchemyCxWorkerLeaseStore(build_session_factory(engine))
    with pytest.raises(CxWorkerLeaseError) as inspect_failure:
        broken.inspect("job", observed_at=NOW)
    assert inspect_failure.value.error_code == "cx.worker_lease.store_unavailable"
    assert str(inspect_failure.value) == inspect_failure.value.detail
    with pytest.raises(CxWorkerLeaseError) as renew_failure:
        broken.renew(
            "job",
            worker_id="worker-a",
            expected_locked_at=NOW,
            observed_at=LATER,
        )
    assert renew_failure.value.error_code == "cx.worker_lease.store_unavailable"

    queue, leases = _stores()
    queue.enqueue(_job())

    def reject_contract(*args: Any, **kwargs: Any) -> None:
        from nex_cx.worker_contracts import CxWorkerContractError

        raise CxWorkerContractError("contract.invalid", "invalid", 422)

    monkeypatch.setattr(worker_leases, "build_cx_worker_execution", reject_contract)
    with pytest.raises(CxWorkerLeaseError) as contract_failure:
        claim_next_worker_execution(
            job_queue=queue,
            lease_store=leases,
            worker_id="worker-a",
            worker_type="cx.worker",
            workload="document_ingestion",
            observed_at=NOW,
        )
    assert contract_failure.value.error_code == (
        "cx.worker_lease.execution_contract_invalid"
    )

    with pytest.raises(CxWorkerLeaseError) as blank:
        broken.inspect(" ", observed_at=NOW)
    assert blank.value.error_code == "cx.worker_lease.field_invalid"
    assert worker_leases._utc_now().endswith("Z")
