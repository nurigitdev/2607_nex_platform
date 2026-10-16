from __future__ import annotations

from datetime import UTC, datetime

import pytest
from nex_ae_api.multi_step_engine import (
    MultiStepEngineError,
    SqlAlchemyMultiStepEngine,
    StepTerminalOutcome,
    StepWaitingOutcome,
)
from nex_ae_api.nsl_read_backends import V01InProcessReadBackendAdapter
from nex_ae_api.runtime_jobs import SqlAlchemyRuntimeJobQueue
from nex_ae_api.step_executors import (
    P5StepExecutionWorker,
    default_p5_executor_registry,
)
from nex_ae_api.step_results import SqlAlchemyStepResultRepository
from test_nex_ae_multi_step_engine import (
    ATTEMPT_1,
    ATTEMPT_2,
    EXECUTION_ID,
    JOB_1_ID,
    LEASE_1,
    LEASE_2,
    NOW,
    PLAN_ID,
    RESULT_1_ID,
    TENANT,
    _factory,
    _ids,
    _success,
)
from test_nex_ae_step_executors import _sync_result
from test_p6_s5_nsl_read_backend import (
    _IsolationResult,
    _adapter as _isolated_adapter,
    _execute as _execute_isolated,
)

EXPIRED = "2026-10-14T09:00:02Z"
RECOVERED = "2026-10-14T09:00:03Z"


def _claim(
    queue: SqlAlchemyRuntimeJobQueue,
    *,
    worker_id: str,
    lease_seconds: int,
    now: str,
):
    claim = queue.claim(
        tenant_id=TENANT,
        worker_id=worker_id,
        lease_seconds=lease_seconds,
        now=now,
    )
    assert claim is not None
    return claim


def test_expired_attempt_is_fenced_before_step_mutation_and_recovered() -> None:
    factory = _factory()
    queue = SqlAlchemyRuntimeJobQueue(
        factory, id_factory=_ids((LEASE_1, ATTEMPT_1, LEASE_2, ATTEMPT_2))
    )
    engine = SqlAlchemyMultiStepEngine(
        factory, queue, id_factory=_ids((JOB_1_ID, RESULT_1_ID))
    )
    engine.schedule_next(tenant_id=TENANT, execution_id=EXECUTION_ID, now=NOW)
    stale = _claim(queue, worker_id="worker-stale", lease_seconds=1, now=NOW)
    engine.begin_claim(tenant_id=TENANT, claim=stale, now=NOW)

    recovered = _claim(
        queue, worker_id="worker-recovered", lease_seconds=30, now=EXPIRED
    )
    with pytest.raises(MultiStepEngineError) as waiting_error:
        engine.record_waiting(
            tenant_id=TENANT,
            claim=stale,
            outcome=StepWaitingOutcome(cx_job_id="cx-job-stale"),
            now=EXPIRED,
        )
    assert waiting_error.value.error_code == "ae.multi_step_stale_runtime_job_lease"
    assert waiting_error.value.retryable is True

    with pytest.raises(MultiStepEngineError) as terminal_error:
        engine.record_outcome(
            tenant_id=TENANT,
            claim=stale,
            outcome=_success("contract://nex/ae/chat-result/v1", "stale"),
            observed_at=EXPIRED,
        )
    assert terminal_error.value.error_code == "ae.multi_step_stale_runtime_job_lease"
    assert (
        SqlAlchemyStepResultRepository(factory).list_for_plan(
            tenant_id=TENANT, executable_plan_id=PLAN_ID
        )
        == []
    )

    context = engine.begin_claim(tenant_id=TENANT, claim=recovered, now=EXPIRED)
    assert context.existing_result is None
    result = engine.record_outcome(
        tenant_id=TENANT,
        claim=recovered,
        outcome=StepTerminalOutcome(
            status="SUCCEEDED",
            result_contract_ref="contract://nex/ae/chat-result/v1",
            result_payload={"result_ref": "recovered"},
            started_at=EXPIRED,
            completed_at=RECOVERED,
        ),
        observed_at=RECOVERED,
    )
    done = queue.complete(
        tenant_id=TENANT,
        runtime_job_id=JOB_1_ID,
        worker_id="worker-recovered",
        lease_token=LEASE_2,
        now=RECOVERED,
    )

    assert result["attempt_no"] == 2
    assert done["state"] == "DONE"
    assert [item["outcome"] for item in queue.list_attempts(TENANT, JOB_1_ID)] == [
        "LEASE_EXPIRED",
        "DONE",
    ]


def test_worker_uses_post_execution_time_for_lease_fencing() -> None:
    factory = _factory()
    queue = SqlAlchemyRuntimeJobQueue(factory, id_factory=_ids((LEASE_1, ATTEMPT_1)))
    engine = SqlAlchemyMultiStepEngine(
        factory, queue, id_factory=_ids((JOB_1_ID, RESULT_1_ID))
    )
    engine.schedule_next(tenant_id=TENANT, execution_id=EXECUTION_ID, now=NOW)
    claim = _claim(queue, worker_id="worker-slow", lease_seconds=1, now=NOW)
    clock_values = iter(
        (
            datetime(2026, 10, 14, 9, 0, tzinfo=UTC),
            datetime(2026, 10, 14, 9, 0, 2, tzinfo=UTC),
        )
    )
    worker = P5StepExecutionWorker(
        engine=engine,
        jobs=queue,
        executors=default_p5_executor_registry(lambda _context: _sync_result()),
        clock=lambda: next(clock_values),
    )

    with pytest.raises(MultiStepEngineError) as exc_info:
        worker.run_claim(tenant_id=TENANT, claim=claim)

    assert exc_info.value.error_code == "ae.multi_step_stale_runtime_job_lease"
    assert (
        SqlAlchemyStepResultRepository(factory).list_for_plan(
            tenant_id=TENANT, executable_plan_id=PLAN_ID
        )
        == []
    )


@pytest.mark.parametrize(
    ("status", "exit_code", "error_code"),
    (
        ("TIMED_OUT", -15, "ISOLATED_RUNTIME_TIMEOUT"),
        ("CRASHED", 17, "ISOLATED_RUNTIME_CRASH"),
    ),
)
def test_hard_timeout_and_crash_remain_process_isolated_retryable_evidence(
    status: str, exit_code: int, error_code: str
) -> None:
    adapter, _ = _isolated_adapter(
        _IsolationResult(
            status=status,
            payload=None,
            exit_code=exit_code,
            error_code=error_code,
        )
    )

    record = _execute_isolated(adapter)

    assert record["isolation_status"] == status
    assert record["error_code"] == error_code
    assert record["retryable"] is True
    assert V01InProcessReadBackendAdapter.timeout_semantics == (
        "NSL_COOPERATIVE_DEADLINE"
    )
