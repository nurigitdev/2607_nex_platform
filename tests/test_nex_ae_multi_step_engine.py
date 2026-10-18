from __future__ import annotations

from collections.abc import Iterable

import nex_ae_api.multi_step_engine as multi_step
import pytest
from nex_ae_api.multi_step_engine import (
    MultiStepEngineError,
    SqlAlchemyMultiStepEngine,
    StepTerminalOutcome,
    StepWaitingOutcome,
)
from nex_ae_api.runtime_jobs import RuntimeJobClaim, SqlAlchemyRuntimeJobQueue
from nex_ae_api.step_results import (
    SqlAlchemyStepResultRepository,
    StepResultError,
    build_step_result,
)
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

TENANT = "tenant-p5-s6"
EXECUTION_ID = "11111111-1111-4111-8111-111111111111"
PLAN_ID = "22222222-2222-4222-8222-222222222222"
STEP_1_ID = "33333333-3333-4333-8333-333333333333"
STEP_2_ID = "44444444-4444-4444-8444-444444444444"
JOB_1_ID = "55555555-5555-4555-8555-555555555555"
RESULT_1_ID = "66666666-6666-4666-8666-666666666666"
JOB_2_ID = "77777777-7777-4777-8777-777777777777"
RESULT_2_ID = "88888888-8888-4888-8888-888888888888"
BLOCKED_ID = "99999999-9999-4999-8999-999999999999"
LEASE_1 = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
ATTEMPT_1 = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
LEASE_2 = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
ATTEMPT_2 = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
NOW = "2026-10-14T09:00:00Z"
LATER = "2026-10-14T09:00:01Z"
LAST = "2026-10-14T09:00:02Z"


def _ids(values: Iterable[str]):
    items = iter(values)
    return lambda: next(items)


def _factory(*, seed=True):
    engine = create_engine("sqlite+pysqlite://", future=True)
    with engine.begin() as connection:
        for ddl in (
            """CREATE TABLE ae_agent_execution (
                tenant_id TEXT NOT NULL, agent_execution_id TEXT NOT NULL,
                state TEXT NOT NULL, phase TEXT NOT NULL, version INTEGER NOT NULL,
                correlation_id TEXT NOT NULL, causation_id TEXT, updated_at TEXT,
                PRIMARY KEY (tenant_id, agent_execution_id))""",
            """CREATE TABLE ae_executable_plan (
                tenant_id TEXT NOT NULL, executable_plan_id TEXT NOT NULL,
                executable_plan_version INTEGER NOT NULL, agent_execution_id TEXT NOT NULL,
                plan_hash TEXT NOT NULL, PRIMARY KEY (tenant_id, executable_plan_id))""",
            """CREATE TABLE ae_executable_step (
                tenant_id TEXT NOT NULL, executable_step_id TEXT NOT NULL,
                agent_execution_id TEXT NOT NULL, executable_plan_id TEXT,
                logical_step_id TEXT, compiled_step_key TEXT, step_index INTEGER,
                step_type TEXT, executor_kind TEXT, state TEXT NOT NULL,
                version INTEGER NOT NULL, dependency_json TEXT, input_binding_json TEXT,
                skill_binding_json TEXT,
                output_contract_ref TEXT, step_contract_hash TEXT,
                legacy_interaction_id TEXT, retrieval_package_ref TEXT,
                retrieval_package_hash TEXT, cx_generation_id TEXT, cx_job_id TEXT,
                generated_response_id TEXT,
                invocation_started_at TEXT, completed_at TEXT, result_ref TEXT,
                error_ref TEXT, updated_at TEXT, PRIMARY KEY (tenant_id, executable_step_id))""",
            """CREATE TABLE ae_step_result (
                tenant_id TEXT NOT NULL, step_result_id TEXT NOT NULL,
                agent_execution_id TEXT NOT NULL, executable_plan_id TEXT NOT NULL,
                executable_step_id TEXT NOT NULL, compiled_step_key TEXT NOT NULL,
                logical_step_id TEXT NOT NULL, attempt_no INTEGER NOT NULL,
                status TEXT NOT NULL, result_contract_ref TEXT NOT NULL,
                result_payload TEXT NOT NULL, external_refs TEXT NOT NULL,
                artifact_refs TEXT NOT NULL, evidence_refs TEXT NOT NULL,
                error_ref TEXT, business_operation_id TEXT, operation_fingerprint TEXT,
                executor_kind TEXT,
                started_at TEXT NOT NULL, completed_at TEXT NOT NULL,
                result_hash TEXT NOT NULL, result_json TEXT NOT NULL, created_at TEXT,
                PRIMARY KEY (tenant_id, step_result_id),
                UNIQUE (tenant_id, executable_step_id))""",
            """CREATE TABLE ae_runtime_job (
                tenant_id TEXT NOT NULL, runtime_job_id TEXT NOT NULL,
                job_type TEXT NOT NULL, execution_id TEXT NOT NULL,
                executable_step_id TEXT, wait_id TEXT, reconciliation_id TEXT,
                result_delivery_id TEXT, publication_reconciliation_id TEXT,
                state TEXT NOT NULL, dedup_key TEXT NOT NULL, attempt_no INTEGER NOT NULL,
                run_after TEXT NOT NULL, lease_owner TEXT, lease_token TEXT,
                lease_until TEXT, payload_json TEXT NOT NULL, correlation_id TEXT NOT NULL,
                causation_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, runtime_job_id), UNIQUE (tenant_id, dedup_key))""",
            """CREATE TABLE ae_runtime_job_attempt (
                attempt_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
                runtime_job_id TEXT NOT NULL, attempt_no INTEGER NOT NULL,
                worker_id TEXT NOT NULL, lease_token TEXT NOT NULL,
                started_at TEXT NOT NULL, ended_at TEXT, outcome TEXT NOT NULL,
                error_ref TEXT, retry_disposition_ref TEXT,
                UNIQUE (tenant_id, runtime_job_id, attempt_no))""",
            """CREATE TABLE ae_wait_registration (
                wait_id TEXT NOT NULL, tenant_id TEXT NOT NULL,
                agent_execution_id TEXT NOT NULL, executable_step_id TEXT NOT NULL,
                wait_type TEXT NOT NULL, external_ref TEXT NOT NULL,
                result_contract_ref TEXT NOT NULL, state TEXT NOT NULL,
                version INTEGER NOT NULL, created_at TEXT NOT NULL,
                satisfied_at TEXT,
                PRIMARY KEY (tenant_id, wait_id),
                UNIQUE (tenant_id, agent_execution_id, executable_step_id, wait_type))""",
        ):
            connection.execute(text(ddl))
        if seed:
            connection.execute(
                text(
                    "INSERT INTO ae_agent_execution VALUES "
                    "(:t, :e, 'RUNNING', 'PLAN_COMPILE', 5, 'corr', 'cause', :now)"
                ),
                {"t": TENANT, "e": EXECUTION_ID, "now": NOW},
            )
            connection.execute(
                text("INSERT INTO ae_executable_plan VALUES (:t, :p, 1, :e, :h)"),
                {
                    "t": TENANT,
                    "p": PLAN_ID,
                    "e": EXECUTION_ID,
                    "h": "sha256:" + "a" * 64,
                },
            )
            connection.execute(
                text("""INSERT INTO ae_executable_step (
                        tenant_id, executable_step_id, agent_execution_id,
                        executable_plan_id, logical_step_id, compiled_step_key,
                        step_index, step_type, executor_kind, state, version,
                        dependency_json, input_binding_json, output_contract_ref,
                        step_contract_hash, legacy_interaction_id, updated_at
                    ) VALUES
                    (:t, :s1, :e, :p, 'S1', 'E1', 0, 'CANONICAL_CAPABILITY',
                     'P4_CHAT_RAG_COMPATIBILITY', 'READY', 1, '[]', '[]',
                     'contract://nex/ae/chat-result/v1', :h1, 'interaction-1', :now),
                    (:t, :s2, :e, :p, 'S2', 'E2', 1, 'REPORT',
                     'DETERMINISTIC_REPORT', 'PENDING', 1, '[\"E1\"]', '[]',
                     'contract://nex/ae/interactive-response/v1', :h2,
                     'interaction-1', :now)"""),
                {
                    "t": TENANT,
                    "e": EXECUTION_ID,
                    "p": PLAN_ID,
                    "s1": STEP_1_ID,
                    "s2": STEP_2_ID,
                    "h1": "sha256:" + "b" * 64,
                    "h2": "sha256:" + "c" * 64,
                    "now": NOW,
                },
            )
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _runtime(factory, *, engine_ids, queue_ids):
    queue = SqlAlchemyRuntimeJobQueue(factory, id_factory=_ids(queue_ids))
    engine = SqlAlchemyMultiStepEngine(factory, queue, id_factory=_ids(engine_ids))
    return engine, queue


def _claim(queue, now=NOW):
    claim = queue.claim(
        tenant_id=TENANT, worker_id="worker-1", lease_seconds=60, now=now
    )
    assert claim is not None
    return claim


def _success(contract, ref, started=NOW, completed=LATER):
    return StepTerminalOutcome(
        status="SUCCEEDED",
        result_contract_ref=contract,
        result_payload={"result_ref": ref},
        started_at=started,
        completed_at=completed,
        evidence_refs=(f"evidence:{ref}",),
    )


def test_engine_executes_two_steps_in_persisted_dependency_order() -> None:
    factory = _factory()
    engine, queue = _runtime(
        factory,
        engine_ids=(JOB_1_ID, RESULT_1_ID, JOB_2_ID, RESULT_2_ID),
        queue_ids=(LEASE_1, ATTEMPT_1, LEASE_2, ATTEMPT_2),
    )

    first_job = engine.schedule_next(
        tenant_id=TENANT, execution_id=EXECUTION_ID, now=NOW
    )
    assert first_job["job_type"] == "START_EXECUTION"
    assert first_job["executable_step_id"] == STEP_1_ID
    first_claim = _claim(queue)
    first_context = engine.begin_claim(tenant_id=TENANT, claim=first_claim, now=NOW)
    assert first_context.step["compiled_step_key"] == "E1"
    assert first_context.dependency_results == ()
    first_result = engine.record_outcome(
        tenant_id=TENANT,
        claim=first_claim,
        outcome=_success("contract://nex/ae/chat-result/v1", "chat-1"),
    )
    queue.complete(
        tenant_id=TENANT,
        runtime_job_id=first_claim.job["runtime_job_id"],
        worker_id="worker-1",
        lease_token=first_claim.job["lease_token"],
        now=LATER,
    )

    second_job = engine.schedule_next(
        tenant_id=TENANT, execution_id=EXECUTION_ID, now=LATER
    )
    assert second_job["job_type"] == "CONTINUE_EXECUTION"
    assert second_job["executable_step_id"] == STEP_2_ID
    second_claim = _claim(queue, now=LATER)
    second_context = engine.begin_claim(tenant_id=TENANT, claim=second_claim, now=LATER)
    assert second_context.dependency_results == (first_result,)
    engine.record_outcome(
        tenant_id=TENANT,
        claim=second_claim,
        outcome=_success(
            "contract://nex/ae/interactive-response/v1",
            "response-1",
            started=LATER,
            completed=LAST,
        ),
    )
    queue.complete(
        tenant_id=TENANT,
        runtime_job_id=second_claim.job["runtime_job_id"],
        worker_id="worker-1",
        lease_token=second_claim.job["lease_token"],
        now=LAST,
    )

    assert (
        engine.schedule_next(tenant_id=TENANT, execution_id=EXECUTION_ID, now=LAST)
        is None
    )
    results = SqlAlchemyStepResultRepository(factory).list_for_plan(
        tenant_id=TENANT, executable_plan_id=PLAN_ID
    )
    assert [item["compiled_step_key"] for item in results] == ["E1", "E2"]
    assert all(item["business_operation_id"] is None for item in results)
    with factory() as session:
        phase = session.execute(
            text("SELECT phase FROM ae_agent_execution WHERE tenant_id = :t"),
            {"t": TENANT},
        ).scalar_one()
    assert phase == "RESULT_VERIFY"


def test_engine_persists_local_skill_outcome_as_step_result_v12() -> None:
    factory = _factory()
    with factory.begin() as session:
        session.execute(
            text(
                "UPDATE ae_executable_step SET step_type = 'LOCAL_SKILL', "
                "executor_kind = 'LOCAL_SKILL' WHERE tenant_id = :tenant_id "
                "AND executable_step_id = :step_id"
            ),
            {"tenant_id": TENANT, "step_id": STEP_1_ID},
        )
    engine, queue = _runtime(
        factory,
        engine_ids=(JOB_1_ID, RESULT_1_ID, JOB_2_ID),
        queue_ids=(LEASE_1, ATTEMPT_1),
    )
    engine.schedule_next(tenant_id=TENANT, execution_id=EXECUTION_ID, now=NOW)
    claim = _claim(queue)
    engine.begin_claim(tenant_id=TENANT, claim=claim, now=NOW)

    result = engine.record_outcome(
        tenant_id=TENANT,
        claim=claim,
        outcome=StepTerminalOutcome(
            status="SUCCEEDED",
            result_contract_ref="contract://nex/ae/nsl-read-result/v1",
            result_payload={
                "nsl_result_summary_ref": "AE:NSL_RESULT_SUMMARY:test",
                "nsl_execution_id": "66666666-6666-4666-8666-666666666666",
                "execution_status": "COMPLETED",
            },
            executor_kind="LOCAL_SKILL",
            business_operation_id="77777777-7777-4777-8777-777777777777",
            started_at=NOW,
            completed_at=LATER,
        ),
    )

    assert result["schema_version"] == "1.2"
    assert result["executor_kind"] == "LOCAL_SKILL"
    assert result["business_operation_id"] == ("77777777-7777-4777-8777-777777777777")
    assert result["operation_fingerprint"] is None


def test_engine_propagates_failed_dependency_without_running_downstream() -> None:
    factory = _factory()
    engine, queue = _runtime(
        factory,
        engine_ids=(JOB_1_ID, RESULT_1_ID, BLOCKED_ID),
        queue_ids=(LEASE_1, ATTEMPT_1),
    )
    engine.schedule_next(tenant_id=TENANT, execution_id=EXECUTION_ID, now=NOW)
    claim = _claim(queue)
    engine.begin_claim(tenant_id=TENANT, claim=claim, now=NOW)

    engine.record_outcome(
        tenant_id=TENANT,
        claim=claim,
        outcome=StepTerminalOutcome(
            status="FAILED",
            result_contract_ref="contract://nex/ae/chat-result/v1",
            result_payload={"reason": "provider-failed"},
            error_ref="provider://failed",
            started_at=NOW,
            completed_at=LATER,
        ),
    )

    results = SqlAlchemyStepResultRepository(factory).list_for_plan(
        tenant_id=TENANT, executable_plan_id=PLAN_ID
    )
    assert [item["status"] for item in results] == ["FAILED", "BLOCKED"]
    assert results[1]["result_payload"]["blocked_by_compiled_step_keys"] == ["E1"]
    assert (
        engine.schedule_next(tenant_id=TENANT, execution_id=EXECUTION_ID, now=LATER)
        is None
    )


def test_restart_detects_existing_terminal_result_without_reexecution() -> None:
    factory = _factory()
    engine, queue = _runtime(
        factory,
        engine_ids=(JOB_1_ID, RESULT_1_ID),
        queue_ids=(LEASE_1, ATTEMPT_1),
    )
    engine.schedule_next(tenant_id=TENANT, execution_id=EXECUTION_ID, now=NOW)
    claim = _claim(queue)
    engine.begin_claim(tenant_id=TENANT, claim=claim, now=NOW)
    result = engine.record_outcome(
        tenant_id=TENANT,
        claim=claim,
        outcome=_success("contract://nex/ae/chat-result/v1", "chat-1"),
    )

    restarted = SqlAlchemyMultiStepEngine(factory, queue)
    context = restarted.begin_claim(tenant_id=TENANT, claim=claim, now=LATER)

    assert context.already_terminal is True
    assert context.existing_result == result


def test_engine_rejects_parallel_or_unauthorized_runtime_state() -> None:
    factory = _factory()
    engine, _ = _runtime(
        factory, engine_ids=(JOB_1_ID,), queue_ids=(LEASE_1, ATTEMPT_1)
    )
    with factory.begin() as session:
        session.execute(
            text(
                "UPDATE ae_executable_step SET state = 'READY' WHERE compiled_step_key = 'E2'"
            )
        )
    with pytest.raises(MultiStepEngineError) as exc_info:
        engine.schedule_next(tenant_id=TENANT, execution_id=EXECUTION_ID, now=NOW)
    assert exc_info.value.error_code == "ae.multi_step_parallelism_violation"

    with factory.begin() as session:
        session.execute(
            text(
                "UPDATE ae_agent_execution SET state = 'BLOCKED' WHERE tenant_id = :t"
            ),
            {"t": TENANT},
        )
    with pytest.raises(MultiStepEngineError) as exc_info:
        engine.schedule_next(tenant_id=TENANT, execution_id=EXECUTION_ID, now=NOW)
    assert exc_info.value.error_code == "ae.multi_step_authority_missing"


def test_schedule_guards_missing_plan_empty_order_running_and_deadlock() -> None:
    engine, _ = _runtime(
        _factory(seed=False), engine_ids=(JOB_1_ID,), queue_ids=(LEASE_1, ATTEMPT_1)
    )
    with pytest.raises(MultiStepEngineError) as exc_info:
        engine.schedule_next(tenant_id=TENANT, execution_id=EXECUTION_ID, now=NOW)
    assert exc_info.value.error_code == "ae.multi_step_execution_not_found"

    factory = _factory()
    engine, _ = _runtime(
        factory, engine_ids=(JOB_1_ID,), queue_ids=(LEASE_1, ATTEMPT_1)
    )
    with factory.begin() as session:
        session.execute(text("DELETE FROM ae_executable_plan"))
    with pytest.raises(MultiStepEngineError) as exc_info:
        engine.schedule_next(tenant_id=TENANT, execution_id=EXECUTION_ID, now=NOW)
    assert exc_info.value.error_code == "ae.multi_step_plan_not_found"

    factory = _factory()
    engine, _ = _runtime(
        factory, engine_ids=(JOB_1_ID,), queue_ids=(LEASE_1, ATTEMPT_1)
    )
    with factory.begin() as session:
        session.execute(text("DELETE FROM ae_executable_step"))
    with pytest.raises(MultiStepEngineError) as exc_info:
        engine.schedule_next(tenant_id=TENANT, execution_id=EXECUTION_ID, now=NOW)
    assert exc_info.value.error_code == "ae.multi_step_empty_plan"

    factory = _factory()
    engine, _ = _runtime(
        factory, engine_ids=(JOB_1_ID,), queue_ids=(LEASE_1, ATTEMPT_1)
    )
    with factory.begin() as session:
        session.execute(
            text(
                "UPDATE ae_executable_step SET step_index = 3 WHERE compiled_step_key = 'E2'"
            )
        )
    with pytest.raises(MultiStepEngineError) as exc_info:
        engine.schedule_next(tenant_id=TENANT, execution_id=EXECUTION_ID, now=NOW)
    assert exc_info.value.error_code == "ae.multi_step_order_invalid"

    factory = _factory()
    engine, _ = _runtime(
        factory, engine_ids=(JOB_1_ID,), queue_ids=(LEASE_1, ATTEMPT_1)
    )
    with factory.begin() as session:
        session.execute(
            text(
                "UPDATE ae_executable_step SET state = 'RUNNING' WHERE compiled_step_key = 'E1'"
            )
        )
    assert (
        engine.schedule_next(tenant_id=TENANT, execution_id=EXECUTION_ID, now=NOW)
        is None
    )

    factory = _factory()
    engine, _ = _runtime(
        factory, engine_ids=(JOB_1_ID,), queue_ids=(LEASE_1, ATTEMPT_1)
    )
    with factory.begin() as session:
        session.execute(
            text(
                "UPDATE ae_executable_step SET state = 'PENDING', "
                "dependency_json = '[\"E9\"]' WHERE compiled_step_key = 'E1'"
            )
        )
    with pytest.raises(MultiStepEngineError) as exc_info:
        engine.schedule_next(tenant_id=TENANT, execution_id=EXECUTION_ID, now=NOW)
    assert exc_info.value.error_code == "ae.multi_step_dependency_deadlock"


def test_schedule_promotes_dependency_free_pending_step() -> None:
    factory = _factory()
    engine, _ = _runtime(
        factory, engine_ids=(JOB_1_ID,), queue_ids=(LEASE_1, ATTEMPT_1)
    )
    with factory.begin() as session:
        session.execute(
            text(
                "UPDATE ae_executable_step SET state = 'PENDING' WHERE compiled_step_key = 'E1'"
            )
        )

    job = engine.schedule_next(tenant_id=TENANT, execution_id=EXECUTION_ID, now=NOW)

    assert job is not None
    assert job["executable_step_id"] == STEP_1_ID


def _manual_claim(factory, step_id=STEP_1_ID):
    queue = SqlAlchemyRuntimeJobQueue(factory, id_factory=_ids((LEASE_1, ATTEMPT_1)))
    queue.enqueue_unique(
        tenant_id=TENANT,
        runtime_job_id=JOB_1_ID,
        job_type="START_EXECUTION",
        execution_id=EXECUTION_ID,
        executable_step_id=step_id,
        dedup_key=f"manual:{step_id}",
        run_after=NOW,
        payload={},
        correlation_id="corr",
        causation_id="cause",
        now=NOW,
    )
    return queue, _claim(queue)


def test_begin_claim_rejects_missing_mismatched_and_nonrunnable_steps() -> None:
    factory = _factory()
    queue, claim = _manual_claim(factory)
    engine = SqlAlchemyMultiStepEngine(factory, queue)
    with factory.begin() as session:
        session.execute(
            text("DELETE FROM ae_executable_step WHERE compiled_step_key = 'E1'")
        )
    with pytest.raises(MultiStepEngineError) as exc_info:
        engine.begin_claim(tenant_id=TENANT, claim=claim, now=NOW)
    assert exc_info.value.error_code == "ae.multi_step_step_not_found"

    factory = _factory()
    queue, claim = _manual_claim(factory)
    engine = SqlAlchemyMultiStepEngine(factory, queue)
    with factory.begin() as session:
        session.execute(
            text(
                "UPDATE ae_executable_step SET agent_execution_id = :other "
                "WHERE compiled_step_key = 'E1'"
            ),
            {"other": "00000000-0000-4000-8000-000000000000"},
        )
    with pytest.raises(MultiStepEngineError) as exc_info:
        engine.begin_claim(tenant_id=TENANT, claim=claim, now=NOW)
    assert exc_info.value.error_code == "ae.multi_step_claim_mismatch"

    factory = _factory()
    queue, claim = _manual_claim(factory)
    engine = SqlAlchemyMultiStepEngine(factory, queue)
    with factory.begin() as session:
        session.execute(
            text(
                "UPDATE ae_executable_step SET state = 'BLOCKED' WHERE compiled_step_key = 'E1'"
            )
        )
    with pytest.raises(MultiStepEngineError) as exc_info:
        engine.begin_claim(tenant_id=TENANT, claim=claim, now=NOW)
    assert exc_info.value.error_code == "ae.multi_step_step_not_runnable"


def test_begin_claim_rejects_missing_or_failed_dependency_result() -> None:
    factory = _factory()
    with factory.begin() as session:
        session.execute(
            text(
                "UPDATE ae_executable_step SET state = 'READY' WHERE compiled_step_key = 'E2'"
            )
        )
    queue, claim = _manual_claim(factory, STEP_2_ID)
    engine = SqlAlchemyMultiStepEngine(factory, queue)
    with pytest.raises(MultiStepEngineError) as exc_info:
        engine.begin_claim(tenant_id=TENANT, claim=claim, now=NOW)
    assert exc_info.value.error_code == "ae.multi_step_dependency_missing"

    with factory.begin() as session:
        session.execute(
            text(
                "UPDATE ae_executable_step SET state = 'FAILED' WHERE compiled_step_key = 'E1'"
            )
        )
    failed = build_step_result(
        step_result_id=RESULT_1_ID,
        execution_id=EXECUTION_ID,
        executable_plan_id=PLAN_ID,
        executable_step_id=STEP_1_ID,
        compiled_step_key="E1",
        logical_step_ref="S1",
        attempt_no=1,
        status="FAILED",
        result_contract_ref="contract://nex/ae/chat-result/v1",
        result_payload={"reason": "failed"},
        error_ref="provider://failed",
        started_at=NOW,
        completed_at=LATER,
    )
    SqlAlchemyStepResultRepository(factory).save(tenant_id=TENANT, step_result=failed)
    with pytest.raises(MultiStepEngineError) as exc_info:
        engine.begin_claim(tenant_id=TENANT, claim=claim, now=LATER)
    assert exc_info.value.error_code == "ae.multi_step_dependency_not_satisfied"


def test_record_outcome_replay_conflict_and_state_guards() -> None:
    factory = _factory()
    engine, queue = _runtime(
        factory,
        engine_ids=(RESULT_1_ID, RESULT_2_ID, BLOCKED_ID),
        queue_ids=(LEASE_1, ATTEMPT_1),
    )
    _, claim = _manual_claim(factory)
    engine.begin_claim(tenant_id=TENANT, claim=claim, now=NOW)
    outcome = _success("contract://nex/ae/chat-result/v1", "chat-1")
    first = engine.record_outcome(tenant_id=TENANT, claim=claim, outcome=outcome)
    assert (
        engine.record_outcome(tenant_id=TENANT, claim=claim, outcome=outcome) == first
    )
    with pytest.raises(MultiStepEngineError) as exc_info:
        engine.record_outcome(
            tenant_id=TENANT,
            claim=claim,
            outcome=_success("contract://nex/ae/chat-result/v1", "different"),
        )
    assert exc_info.value.error_code == "ae.multi_step_terminal_conflict"

    factory = _factory()
    queue, claim = _manual_claim(factory)
    engine = SqlAlchemyMultiStepEngine(factory, queue, id_factory=lambda: RESULT_1_ID)
    with pytest.raises(MultiStepEngineError) as exc_info:
        engine.record_outcome(
            tenant_id=TENANT,
            claim=claim,
            outcome=_success("contract://nex/ae/chat-result/v1", "chat-1"),
        )
    assert exc_info.value.error_code == "ae.multi_step_step_not_running"


def test_record_outcome_rejects_missing_and_mismatched_steps() -> None:
    factory = _factory()
    queue, claim = _manual_claim(factory)
    engine = SqlAlchemyMultiStepEngine(factory, queue, id_factory=lambda: RESULT_1_ID)
    with factory.begin() as session:
        session.execute(
            text("DELETE FROM ae_executable_step WHERE compiled_step_key = 'E1'")
        )
    with pytest.raises(MultiStepEngineError) as exc_info:
        engine.record_outcome(
            tenant_id=TENANT,
            claim=claim,
            outcome=_success("contract://nex/ae/chat-result/v1", "chat-1"),
        )
    assert exc_info.value.error_code == "ae.multi_step_step_not_found"

    factory = _factory()
    queue, claim = _manual_claim(factory)
    engine = SqlAlchemyMultiStepEngine(factory, queue, id_factory=lambda: RESULT_1_ID)
    with factory.begin() as session:
        session.execute(
            text(
                "UPDATE ae_executable_step SET agent_execution_id = :other "
                "WHERE compiled_step_key = 'E1'"
            ),
            {"other": "00000000-0000-4000-8000-000000000000"},
        )
    with pytest.raises(MultiStepEngineError) as exc_info:
        engine.record_outcome(
            tenant_id=TENANT,
            claim=claim,
            outcome=_success("contract://nex/ae/chat-result/v1", "chat-1"),
        )
    assert exc_info.value.error_code == "ae.multi_step_claim_mismatch"


def test_engine_validates_claim_and_maps_store_errors(monkeypatch) -> None:
    factory = _factory()
    queue = SqlAlchemyRuntimeJobQueue(factory)
    engine = SqlAlchemyMultiStepEngine(factory, queue)
    with pytest.raises(MultiStepEngineError, match="RuntimeJobClaim"):
        engine.begin_claim(tenant_id=TENANT, claim=None, now=NOW)

    invalid = RuntimeJobClaim(job={"tenant_id": "other"}, attempt={"outcome": "DONE"})
    with pytest.raises(MultiStepEngineError, match="invalid"):
        engine.begin_claim(tenant_id=TENANT, claim=invalid, now=NOW)

    unavailable = SqlAlchemyMultiStepEngine(
        _factory(seed=False), SqlAlchemyRuntimeJobQueue(_factory(seed=False))
    )
    with pytest.raises(MultiStepEngineError) as exc_info:
        unavailable.schedule_next(tenant_id=TENANT, execution_id=EXECUTION_ID, now=NOW)
    assert exc_info.value.error_code == "ae.multi_step_execution_not_found"

    monkeypatch.setattr(
        multi_step,
        "load_step_results_for_plan",
        lambda *a, **k: (_ for _ in ()).throw(
            StepResultError("ae.step_result_corrupt", "corrupt")
        ),
    )
    with pytest.raises(MultiStepEngineError) as exc_info:
        engine.schedule_next(tenant_id=TENANT, execution_id=EXECUTION_ID, now=NOW)
    assert exc_info.value.error_code == "ae.step_result_corrupt"


class _RowCount:
    def __init__(self, rowcount=0):
        self.rowcount = rowcount


class _ZeroSession:
    def execute(self, *_args, **_kwargs):
        return _RowCount()


def test_internal_cas_and_terminal_transition_guards(monkeypatch) -> None:
    pending = {
        "tenant_id": TENANT,
        "executable_step_id": STEP_2_ID,
        "agent_execution_id": EXECUTION_ID,
        "executable_plan_id": PLAN_ID,
        "logical_step_id": "S2",
        "compiled_step_key": "E2",
        "version": 1,
        "state": "PENDING",
        "dependencies": ["E1"],
        "output_contract_ref": "contract://result",
    }
    with pytest.raises(MultiStepEngineError) as exc_info:
        multi_step._materialize_dependency_block(
            _ZeroSession(),
            tenant_id=TENANT,
            step=pending,
            blockers=["E1"],
            completed_at=LATER,
            id_factory=lambda: BLOCKED_ID,
        )
    assert exc_info.value.error_code == "ae.multi_step_dependency_conflict"

    with pytest.raises(MultiStepEngineError) as exc_info:
        multi_step._promote_next_ready(
            _ZeroSession(),
            [pending],
            [{"compiled_step_key": "E1", "status": "SUCCEEDED"}],
            NOW,
        )
    assert exc_info.value.error_code == "ae.multi_step_ready_conflict"

    runtime = {
        "tenant_id": TENANT,
        "agent_execution_id": EXECUTION_ID,
        "state": "RUNNING",
        "phase": "PLAN_COMPILE",
        "version": 1,
    }
    with pytest.raises(MultiStepEngineError) as exc_info:
        multi_step._enter_step_execution(_ZeroSession(), runtime, NOW)
    assert exc_info.value.error_code == "ae.multi_step_execution_conflict"

    blocked_runtime = {**runtime, "state": "BLOCKED"}
    with pytest.raises(MultiStepEngineError) as exc_info:
        multi_step._move_to_result_verify(_ZeroSession(), blocked_runtime, NOW)
    assert exc_info.value.error_code == "ae.multi_step_result_verify_conflict"

    with pytest.raises(MultiStepEngineError) as exc_info:
        multi_step._move_to_result_verify(_ZeroSession(), runtime, NOW)
    assert exc_info.value.error_code == "ae.multi_step_execution_conflict"


def test_internal_advance_and_primitive_guards(monkeypatch) -> None:
    terminal = [{"state": "SUCCEEDED", "compiled_step_key": "E1"}]
    monkeypatch.setattr(multi_step, "_load_steps", lambda *a: terminal)
    monkeypatch.setattr(multi_step, "load_step_results_for_plan", lambda *a: [])
    monkeypatch.setattr(multi_step, "_load_runtime", lambda *a, **k: None)
    with pytest.raises(MultiStepEngineError) as exc_info:
        multi_step._advance_plan_after_result(
            object(),
            tenant_id=TENANT,
            execution_id=EXECUTION_ID,
            executable_plan_id=PLAN_ID,
            completed_at=NOW,
            id_factory=lambda: RESULT_1_ID,
        )
    assert exc_info.value.error_code == "ae.multi_step_execution_not_found"

    assert multi_step._all_terminal([]) is False
    assert multi_step._json_list("[]") == []
    with pytest.raises(MultiStepEngineError, match="not an array"):
        multi_step._json_list("{}")
    with pytest.raises(MultiStepEngineError, match="UUID"):
        multi_step._required_uuid("id", None)
    with pytest.raises(MultiStepEngineError, match="UUID"):
        multi_step._required_uuid("id", "bad")
    with pytest.raises(MultiStepEngineError, match="bounded"):
        multi_step._required_text("tenant_id", "", 10)


def test_begin_claim_accepts_already_running_step_and_requires_runtime() -> None:
    factory = _factory()
    queue, claim = _manual_claim(factory)
    engine = SqlAlchemyMultiStepEngine(factory, queue)
    with factory.begin() as session:
        session.execute(
            text(
                "UPDATE ae_executable_step SET state = 'RUNNING' WHERE compiled_step_key = 'E1'"
            )
        )
    context = engine.begin_claim(tenant_id=TENANT, claim=claim, now=NOW)
    assert context.step["state"] == "RUNNING"

    factory = _factory()
    queue, claim = _manual_claim(factory)
    engine = SqlAlchemyMultiStepEngine(factory, queue)
    with factory.begin() as session:
        session.execute(text("DELETE FROM ae_agent_execution"))
    with pytest.raises(MultiStepEngineError) as exc_info:
        engine.begin_claim(tenant_id=TENANT, claim=claim, now=NOW)
    assert exc_info.value.error_code == "ae.multi_step_execution_not_found"


class _FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, *_args, **_kwargs):
        return _RowCount()

    def commit(self):
        return None

    def get_bind(self):
        return type(
            "Bind", (), {"dialect": type("Dialect", (), {"name": "sqlite"})()}
        )()


def _running_claim() -> RuntimeJobClaim:
    return RuntimeJobClaim(
        job={
            "tenant_id": TENANT,
            "runtime_job_id": JOB_1_ID,
            "job_type": "START_EXECUTION",
            "execution_id": EXECUTION_ID,
            "executable_step_id": STEP_1_ID,
            "state": "RUNNING",
            "lease_owner": "worker-1",
            "lease_token": LEASE_1,
        },
        attempt={
            "attempt_id": ATTEMPT_1,
            "runtime_job_id": JOB_1_ID,
            "attempt_no": 1,
            "worker_id": "worker-1",
            "outcome": "RUNNING",
            "lease_token": LEASE_1,
        },
    )


def _step(state="READY"):
    return {
        "tenant_id": TENANT,
        "executable_step_id": STEP_1_ID,
        "agent_execution_id": EXECUTION_ID,
        "executable_plan_id": PLAN_ID,
        "logical_step_id": "S1",
        "compiled_step_key": "E1",
        "version": 1,
        "state": state,
        "dependencies": [],
        "output_contract_ref": "contract://nex/ae/chat-result/v1",
    }


def test_begin_and_record_detect_compare_and_swap_conflicts(monkeypatch) -> None:
    factory = lambda: _FakeSession()
    queue = object()
    engine = SqlAlchemyMultiStepEngine(factory, queue, id_factory=lambda: RESULT_1_ID)
    monkeypatch.setattr(multi_step, "_load_step", lambda *a, **k: _step())
    monkeypatch.setattr(multi_step, "_require_claim_authority", lambda *a: None)
    monkeypatch.setattr(multi_step, "load_step_result_by_step", lambda *a: None)
    monkeypatch.setattr(multi_step, "_dependency_results", lambda *a: [])
    with pytest.raises(MultiStepEngineError) as exc_info:
        engine.begin_claim(tenant_id=TENANT, claim=_running_claim(), now=NOW)
    assert exc_info.value.error_code == "ae.multi_step_claim_conflict"

    monkeypatch.setattr(
        multi_step, "_load_step", lambda *a, **k: _step(state="RUNNING")
    )
    with pytest.raises(MultiStepEngineError) as exc_info:
        engine.record_outcome(
            tenant_id=TENANT,
            claim=_running_claim(),
            outcome=_success("contract://nex/ae/chat-result/v1", "chat-1"),
        )
    assert exc_info.value.error_code == "ae.multi_step_terminal_conflict"


@pytest.mark.parametrize("method", ["schedule", "begin", "record"])
def test_engine_maps_sqlalchemy_store_failures(monkeypatch, method) -> None:
    factory = _factory()
    engine = SqlAlchemyMultiStepEngine(factory, SqlAlchemyRuntimeJobQueue(factory))
    if method != "schedule":
        monkeypatch.setattr(multi_step, "_require_claim_authority", lambda *a: None)
    if method == "schedule":
        monkeypatch.setattr(
            multi_step,
            "_load_runtime",
            lambda *a, **k: (_ for _ in ()).throw(SQLAlchemyError("store")),
        )
        action = lambda: engine.schedule_next(
            tenant_id=TENANT, execution_id=EXECUTION_ID, now=NOW
        )
    elif method == "begin":
        monkeypatch.setattr(
            multi_step,
            "_load_step",
            lambda *a, **k: (_ for _ in ()).throw(SQLAlchemyError("store")),
        )
        action = lambda: engine.begin_claim(
            tenant_id=TENANT, claim=_running_claim(), now=NOW
        )
    else:
        monkeypatch.setattr(
            multi_step,
            "_load_step",
            lambda *a, **k: (_ for _ in ()).throw(SQLAlchemyError("store")),
        )
        action = lambda: engine.record_outcome(
            tenant_id=TENANT,
            claim=_running_claim(),
            outcome=_success("contract://nex/ae/chat-result/v1", "chat-1"),
        )

    with pytest.raises(MultiStepEngineError) as exc_info:
        action()
    assert exc_info.value.error_code == "ae.multi_step_store_unavailable"
    assert exc_info.value.retryable is True


@pytest.mark.parametrize("method", ["begin", "record"])
def test_engine_preserves_step_result_errors(monkeypatch, method) -> None:
    factory = _factory()
    engine = SqlAlchemyMultiStepEngine(factory, SqlAlchemyRuntimeJobQueue(factory))
    monkeypatch.setattr(multi_step, "_require_claim_authority", lambda *a: None)
    if method == "begin":
        monkeypatch.setattr(
            multi_step,
            "load_step_result_by_step",
            lambda *a: (_ for _ in ()).throw(
                StepResultError("ae.step_result_corrupt", "corrupt", True)
            ),
        )
        action = lambda: engine.begin_claim(
            tenant_id=TENANT, claim=_running_claim(), now=NOW
        )
    else:
        monkeypatch.setattr(
            multi_step,
            "build_step_result",
            lambda **_kwargs: (_ for _ in ()).throw(
                StepResultError("ae.step_result_invalid", "invalid")
            ),
        )
        action = lambda: engine.record_outcome(
            tenant_id=TENANT,
            claim=_running_claim(),
            outcome=_success("contract://nex/ae/chat-result/v1", "chat-1"),
        )

    with pytest.raises(MultiStepEngineError) as exc_info:
        action()
    assert exc_info.value.error_code.startswith("ae.step_result_")
    assert exc_info.value.retryable is (method == "begin")


def test_advance_returns_for_active_step_and_rejects_deadlock(monkeypatch) -> None:
    monkeypatch.setattr(
        multi_step,
        "_load_steps",
        lambda *a: [{"state": "READY", "compiled_step_key": "E1"}],
    )
    monkeypatch.setattr(multi_step, "load_step_results_for_plan", lambda *a: [])
    multi_step._advance_plan_after_result(
        object(),
        tenant_id=TENANT,
        execution_id=EXECUTION_ID,
        executable_plan_id=PLAN_ID,
        completed_at=NOW,
        id_factory=lambda: RESULT_1_ID,
    )

    pending = {
        "state": "PENDING",
        "compiled_step_key": "E1",
        "dependencies": ["E9"],
    }
    monkeypatch.setattr(multi_step, "_load_steps", lambda *a: [pending])
    with pytest.raises(MultiStepEngineError) as exc_info:
        multi_step._advance_plan_after_result(
            object(),
            tenant_id=TENANT,
            execution_id=EXECUTION_ID,
            executable_plan_id=PLAN_ID,
            completed_at=NOW,
            id_factory=lambda: RESULT_1_ID,
        )
    assert exc_info.value.error_code == "ae.multi_step_dependency_deadlock"


def test_waiting_step_resumes_without_rescheduling_or_reexecution() -> None:
    factory = _factory()
    engine, queue = _runtime(
        factory,
        engine_ids=(JOB_1_ID, JOB_2_ID, RESULT_1_ID),
        queue_ids=(LEASE_1, ATTEMPT_1, LEASE_2, ATTEMPT_2),
    )
    engine.schedule_next(tenant_id=TENANT, execution_id=EXECUTION_ID, now=NOW)
    start_claim = _claim(queue)
    engine.begin_claim(tenant_id=TENANT, claim=start_claim, now=NOW)
    waiting = engine.record_waiting(
        tenant_id=TENANT,
        claim=start_claim,
        outcome=StepWaitingOutcome(
            retrieval_package_ref="retrieval-1",
            retrieval_package_hash="sha256:" + "d" * 64,
            cx_generation_id="generation-1",
            cx_job_id="cx-job-1",
        ),
        now=LATER,
    )
    queue.complete(
        tenant_id=TENANT,
        runtime_job_id=start_claim.job["runtime_job_id"],
        worker_id="worker-1",
        lease_token=start_claim.job["lease_token"],
        now=LATER,
    )
    assert waiting["state"] == "WAITING"
    assert (
        engine.schedule_next(tenant_id=TENANT, execution_id=EXECUTION_ID, now=LATER)
        is None
    )
    continuation = engine.enqueue_waiting_continuation(
        tenant_id=TENANT,
        execution_id=EXECUTION_ID,
        executable_step_id=STEP_1_ID,
        continuation_refs={
            "cx_job_ref": "cx-job-1",
            "cx_generation_ref": "generation-1",
            "generated_response_ref": "response-1",
            "status": "COMPLETED",
        },
        now=LATER,
    )
    assert continuation["job_type"] == "CONTINUE_EXECUTION"
    continue_claim = _claim(queue, now=LATER)
    resumed = engine.begin_claim(tenant_id=TENANT, claim=continue_claim, now=LATER)
    assert resumed.step["state"] == "WAITING"
    result = engine.record_outcome(
        tenant_id=TENANT,
        claim=continue_claim,
        outcome=_success(
            "contract://nex/ae/chat-result/v1",
            "chat-1",
            started=LATER,
            completed=LAST,
        ),
    )
    queue.complete(
        tenant_id=TENANT,
        runtime_job_id=continue_claim.job["runtime_job_id"],
        worker_id="worker-1",
        lease_token=continue_claim.job["lease_token"],
        now=LAST,
    )

    assert result["status"] == "SUCCEEDED"
    with factory() as session:
        state = session.execute(
            text(
                "SELECT state FROM ae_executable_step "
                "WHERE executable_step_id = :step_id"
            ),
            {"step_id": STEP_2_ID},
        ).scalar_one()
    assert state == "READY"


def test_delegate_wait_atomically_moves_parent_to_waiting_dependency() -> None:
    factory = _factory()
    with factory() as session:
        session.execute(
            text(
                "UPDATE ae_executable_step SET step_type = 'DELEGATE_WORK', "
                "executor_kind = 'WC_DELEGATE_WORK' "
                "WHERE tenant_id = :tenant_id AND executable_step_id = :step_id"
            ),
            {"tenant_id": TENANT, "step_id": STEP_1_ID},
        )
        session.commit()
    engine, queue = _runtime(
        factory,
        engine_ids=(JOB_1_ID,),
        queue_ids=(LEASE_1, ATTEMPT_1),
    )
    engine.schedule_next(tenant_id=TENANT, execution_id=EXECUTION_ID, now=NOW)
    claim = _claim(queue)
    engine.begin_claim(tenant_id=TENANT, claim=claim, now=NOW)
    with factory() as session:
        session.execute(
            text(
                "INSERT INTO ae_wait_registration VALUES "
                "(:wait_id, :tenant_id, :execution_id, :step_id, "
                "'WORK_RESULT', :external_ref, :contract_ref, 'PENDING', 1, :now, NULL)"
            ),
            {
                "wait_id": RESULT_1_ID,
                "tenant_id": TENANT,
                "execution_id": EXECUTION_ID,
                "step_id": STEP_1_ID,
                "external_ref": BLOCKED_ID,
                "contract_ref": "contract://nex/wc/work-result/v1",
                "now": NOW,
            },
        )
        session.commit()

    waiting = engine.record_waiting(
        tenant_id=TENANT,
        claim=claim,
        outcome=StepWaitingOutcome(
            wait_id=RESULT_1_ID,
            external_ref=BLOCKED_ID,
            result_contract_ref="contract://nex/wc/work-result/v1",
        ),
        now=LATER,
    )

    with factory() as session:
        runtime = session.execute(
            text(
                "SELECT state, phase FROM ae_agent_execution "
                "WHERE tenant_id = :tenant_id AND agent_execution_id = :execution_id"
            ),
            {"tenant_id": TENANT, "execution_id": EXECUTION_ID},
        ).one()
    assert waiting["state"] == "WAITING"
    assert tuple(runtime) == ("WAITING_DEPENDENCY", "STEP_EXECUTION")


def test_waiting_and_continuation_guards() -> None:
    factory = _factory()
    engine, queue = _runtime(
        factory,
        engine_ids=(JOB_1_ID, JOB_2_ID),
        queue_ids=(LEASE_1, ATTEMPT_1),
    )
    engine.schedule_next(tenant_id=TENANT, execution_id=EXECUTION_ID, now=NOW)
    claim = _claim(queue)
    engine.begin_claim(tenant_id=TENANT, claim=claim, now=NOW)

    with pytest.raises(MultiStepEngineError, match="cx_job_id"):
        engine.record_waiting(
            tenant_id=TENANT,
            claim=claim,
            outcome=StepWaitingOutcome(),
            now=NOW,
        )
    with factory.begin() as session:
        session.execute(
            text(
                "UPDATE ae_executable_step SET state = 'WAITING', cx_job_id = 'cx-job-1' "
                "WHERE executable_step_id = :step_id"
            ),
            {"step_id": STEP_1_ID},
        )
    with pytest.raises(MultiStepEngineError) as exc_info:
        engine.enqueue_waiting_continuation(
            tenant_id=TENANT,
            execution_id=EXECUTION_ID,
            executable_step_id=STEP_1_ID,
            continuation_refs={"cx_job_ref": "other"},
            now=NOW,
        )
    assert exc_info.value.error_code == "ae.multi_step_continuation_lineage_mismatch"

    with pytest.raises(MultiStepEngineError, match="requires cx_job_ref"):
        engine.enqueue_waiting_continuation(
            tenant_id=TENANT,
            execution_id=EXECUTION_ID,
            executable_step_id=STEP_1_ID,
            continuation_refs={"status": "COMPLETED"},
            now=NOW,
        )


def test_waiting_step_requires_continuation_job() -> None:
    factory = _factory()
    queue, claim = _manual_claim(factory)
    with factory.begin() as session:
        session.execute(
            text(
                "UPDATE ae_executable_step SET state = 'WAITING', "
                "cx_job_id = 'cx-job-1' WHERE executable_step_id = :step_id"
            ),
            {"step_id": STEP_1_ID},
        )
    engine = SqlAlchemyMultiStepEngine(factory, queue)

    with pytest.raises(MultiStepEngineError) as exc_info:
        engine.begin_claim(tenant_id=TENANT, claim=claim, now=NOW)
    assert exc_info.value.error_code == "ae.multi_step_continuation_required"


def test_record_waiting_rejects_missing_and_mismatched_steps() -> None:
    factory = _factory()
    queue, claim = _manual_claim(factory)
    engine = SqlAlchemyMultiStepEngine(factory, queue)
    with factory.begin() as session:
        session.execute(
            text("DELETE FROM ae_executable_step WHERE executable_step_id = :step_id"),
            {"step_id": STEP_1_ID},
        )
    with pytest.raises(MultiStepEngineError) as exc_info:
        engine.record_waiting(
            tenant_id=TENANT,
            claim=claim,
            outcome=StepWaitingOutcome(cx_job_id="cx-job-1"),
            now=NOW,
        )
    assert exc_info.value.error_code == "ae.multi_step_step_not_found"

    factory = _factory()
    queue, claim = _manual_claim(factory)
    engine = SqlAlchemyMultiStepEngine(factory, queue)
    with pytest.raises(MultiStepEngineError) as exc_info:
        engine.record_waiting(
            tenant_id=TENANT,
            claim=claim,
            outcome=StepWaitingOutcome(cx_job_id="cx-job-1"),
            now=NOW,
        )
    assert exc_info.value.error_code == "ae.multi_step_waiting_mismatch"


def test_waiting_transition_detects_conflict_and_disappearance(monkeypatch) -> None:
    running = {
        **_step(state="RUNNING"),
        "executor_kind": "P4_CHAT_RAG_COMPATIBILITY",
    }
    engine = SqlAlchemyMultiStepEngine(
        lambda: _FakeSession(), object(), id_factory=lambda: RESULT_1_ID
    )
    monkeypatch.setattr(multi_step, "_require_claim_authority", lambda *a: None)
    monkeypatch.setattr(multi_step, "_load_step", lambda *a, **k: running)
    with pytest.raises(MultiStepEngineError) as exc_info:
        engine.record_waiting(
            tenant_id=TENANT,
            claim=_running_claim(),
            outcome=StepWaitingOutcome(cx_job_id="cx-job-1"),
            now=NOW,
        )
    assert exc_info.value.error_code == "ae.multi_step_waiting_conflict"

    class _OneSession(_FakeSession):
        def execute(self, *_args, **_kwargs):
            return _RowCount(1)

    loads = iter((running, None))
    monkeypatch.setattr(multi_step, "_load_step", lambda *a, **k: next(loads))
    disappeared = SqlAlchemyMultiStepEngine(lambda: _OneSession(), object())
    with pytest.raises(MultiStepEngineError) as exc_info:
        disappeared.record_waiting(
            tenant_id=TENANT,
            claim=_running_claim(),
            outcome=StepWaitingOutcome(cx_job_id="cx-job-1"),
            now=NOW,
        )
    assert exc_info.value.error_code == "ae.multi_step_step_not_found"
    assert exc_info.value.retryable is True


@pytest.mark.parametrize("method", ["waiting", "continuation"])
def test_waiting_methods_map_store_failures(monkeypatch, method) -> None:
    factory = _factory()
    engine = SqlAlchemyMultiStepEngine(factory, SqlAlchemyRuntimeJobQueue(factory))
    if method == "waiting":
        monkeypatch.setattr(multi_step, "_require_claim_authority", lambda *a: None)
    monkeypatch.setattr(
        multi_step,
        "_load_step",
        lambda *a, **k: (_ for _ in ()).throw(SQLAlchemyError("store")),
    )
    if method == "waiting":
        action = lambda: engine.record_waiting(
            tenant_id=TENANT,
            claim=_running_claim(),
            outcome=StepWaitingOutcome(cx_job_id="cx-job-1"),
            now=NOW,
        )
    else:
        action = lambda: engine.enqueue_waiting_continuation(
            tenant_id=TENANT,
            execution_id=EXECUTION_ID,
            executable_step_id=STEP_1_ID,
            continuation_refs={"cx_job_ref": "cx-job-1"},
            now=NOW,
        )
    with pytest.raises(MultiStepEngineError) as exc_info:
        action()
    assert exc_info.value.error_code == "ae.multi_step_store_unavailable"


def test_continuation_rejects_nonwaiting_step_and_invalid_ref_shapes() -> None:
    factory = _factory()
    engine = SqlAlchemyMultiStepEngine(factory, SqlAlchemyRuntimeJobQueue(factory))
    with pytest.raises(MultiStepEngineError) as exc_info:
        engine.enqueue_waiting_continuation(
            tenant_id=TENANT,
            execution_id=EXECUTION_ID,
            executable_step_id=STEP_1_ID,
            continuation_refs={"cx_job_ref": "cx-job-1"},
            now=NOW,
        )
    assert exc_info.value.error_code == "ae.multi_step_continuation_mismatch"

    with pytest.raises(MultiStepEngineError, match="must be an object"):
        engine.enqueue_waiting_continuation(
            tenant_id=TENANT,
            execution_id=EXECUTION_ID,
            executable_step_id=STEP_1_ID,
            continuation_refs=[],
            now=NOW,
        )
    with pytest.raises(MultiStepEngineError, match="fields are invalid"):
        engine.enqueue_waiting_continuation(
            tenant_id=TENANT,
            execution_id=EXECUTION_ID,
            executable_step_id=STEP_1_ID,
            continuation_refs={"unknown": "value"},
            now=NOW,
        )
