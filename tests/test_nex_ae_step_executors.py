from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from nex_ae_api import step_executors
from nex_ae_api.multi_step_engine import (
    SqlAlchemyMultiStepEngine,
    StepExecutionContext,
    StepTerminalOutcome,
)
from nex_ae_api.runtime_jobs import SqlAlchemyRuntimeJobQueue
from nex_ae_api.step_executors import (
    P5CompatibilityChatExecutor,
    P5DeterministicProjectionExecutor,
    P5StepExecutionWorker,
    P5StepExecutorError,
    P5StepExecutorRegistry,
    default_p5_executor_registry,
)
from sqlalchemy import text
from starlette.responses import JSONResponse
from test_nex_ae_multi_step_engine import (
    ATTEMPT_1,
    ATTEMPT_2,
    BLOCKED_ID,
    EXECUTION_ID,
    JOB_1_ID,
    JOB_2_ID,
    LATER,
    LEASE_1,
    LEASE_2,
    NOW,
    RESULT_1_ID,
    RESULT_2_ID,
    STEP_1_ID,
    TENANT,
    _factory,
)

NOW_DT = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)


def _ids(values: Iterable[str]):
    items = iter(values)
    return lambda: next(items)


def _runtime(factory, *, engine_ids, queue_ids, callback):
    queue = SqlAlchemyRuntimeJobQueue(factory, id_factory=_ids(queue_ids))
    engine = SqlAlchemyMultiStepEngine(factory, queue, id_factory=_ids(engine_ids))
    worker = P5StepExecutionWorker(
        engine=engine,
        jobs=queue,
        executors=default_p5_executor_registry(callback),
        clock=lambda: NOW_DT,
    )
    return engine, queue, worker


def _claim(queue, now=NOW):
    claim = queue.claim(
        tenant_id=TENANT,
        worker_id="worker-s7",
        lease_seconds=60,
        now=now,
    )
    assert claim is not None
    return claim


def _sync_result(**overrides):
    value = {
        "interaction_id": "interaction-1",
        "status": "COMPLETED",
        "retrieval": {
            "cx_retrieval_package_id": "retrieval-1",
            "cx_package_hash": "sha256:" + "a" * 64,
        },
        "cx_generation_id": "generation-1",
        "generation": {
            "generated_response_ref": {"generated_response_id": "response-1"}
        },
        "artifact_refs": [
            {"artifact_id": "artifact-1", "artifact_version_id": "version-1"}
        ],
    }
    return {**value, **overrides}


def _async_result(status="PENDING", **overrides):
    value = {
        "interaction_id": "interaction-1",
        "status": status,
        "cx_generation_id": "generation-1",
        "generation": {
            "async_generation": {
                "job_id": "cx-job-1",
                "cx_generation_id": "generation-1",
            }
        },
        "retrieval": None,
        "artifact_refs": [],
    }
    return {**value, **overrides}


def _install_report_binding(factory) -> None:
    binding = (
        '[{"target_name":"source_result","binding_type":'
        '"COMPILED_STEP_OUTPUT","source_ref":"E1:$"}]'
    )
    with factory.begin() as session:
        session.execute(
            text(
                "UPDATE ae_executable_step SET input_binding_json = :binding "
                "WHERE compiled_step_key = 'E2'"
            ),
            {"binding": binding},
        )


def test_worker_executes_compatibility_then_deterministic_report_once() -> None:
    factory = _factory()
    _install_report_binding(factory)
    calls = 0

    def callback(_context):
        nonlocal calls
        calls += 1
        return _sync_result()

    engine, queue, worker = _runtime(
        factory,
        engine_ids=(JOB_1_ID, RESULT_1_ID, JOB_2_ID, RESULT_2_ID),
        queue_ids=(LEASE_1, ATTEMPT_1, LEASE_2, ATTEMPT_2),
        callback=callback,
    )
    engine.schedule_next(tenant_id=TENANT, execution_id=EXECUTION_ID, now=NOW)
    first = worker.run_claim(tenant_id=TENANT, claim=_claim(queue))
    assert first.disposition == "TERMINAL"
    assert first.step_result["compiled_step_key"] == "E1"
    assert first.step_result["artifact_refs"] == ["AE:ARTIFACT:version-1"]
    assert first.runtime_job["state"] == "DONE"

    engine.schedule_next(tenant_id=TENANT, execution_id=EXECUTION_ID, now=NOW)
    second = worker.run_claim(tenant_id=TENANT, claim=_claim(queue))

    assert calls == 1
    assert second.step_result["compiled_step_key"] == "E2"
    assert second.step_result["result_payload"]["projection_kind"] == "REPORT"
    source = second.step_result["result_payload"]["bindings"]["source_result"]
    assert source["source_step_result_ref"] == f"AE:STEP_RESULT:{RESULT_1_ID}"
    assert source["value"]["generated_response_ref"] == "response-1"


def test_worker_waits_then_continues_without_reinvoking_chat() -> None:
    factory = _factory()
    calls = 0

    def callback(_context):
        nonlocal calls
        calls += 1
        return _async_result()

    engine, queue, worker = _runtime(
        factory,
        engine_ids=(JOB_1_ID, JOB_2_ID, RESULT_1_ID),
        queue_ids=(LEASE_1, ATTEMPT_1, LEASE_2, ATTEMPT_2),
        callback=callback,
    )
    engine.schedule_next(tenant_id=TENANT, execution_id=EXECUTION_ID, now=NOW)
    waiting = worker.run_claim(tenant_id=TENANT, claim=_claim(queue))
    assert waiting.disposition == "WAITING"
    assert waiting.step["cx_job_id"] == "cx-job-1"
    assert waiting.step_result is None

    engine.enqueue_waiting_continuation(
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
    completed = worker.run_claim(
        tenant_id=TENANT,
        claim=_claim(queue, LATER),
        continuation_result=_async_result(
            status="COMPLETED",
            generation={
                "async_generation": {"job_id": "cx-job-1"},
                "generated_response_id": "response-1",
            },
        ),
    )

    assert calls == 1
    assert completed.disposition == "TERMINAL"
    assert completed.step_result["status"] == "SUCCEEDED"
    assert completed.step_result["result_payload"]["cx_job_ref"] == "cx-job-1"


def test_worker_terminalizes_unavailable_executor_and_callback_failure() -> None:
    factory = _factory()
    with factory.begin() as session:
        session.execute(
            text(
                "UPDATE ae_executable_step SET executor_kind = 'LOCAL_SKILL_UNAVAILABLE' "
                "WHERE compiled_step_key = 'E1'"
            )
        )
    engine, queue, worker = _runtime(
        factory,
        engine_ids=(JOB_1_ID, RESULT_1_ID, BLOCKED_ID),
        queue_ids=(LEASE_1, ATTEMPT_1),
        callback=lambda _context: _sync_result(),
    )
    engine.schedule_next(tenant_id=TENANT, execution_id=EXECUTION_ID, now=NOW)
    unavailable = worker.run_claim(tenant_id=TENANT, claim=_claim(queue))
    assert unavailable.step_result["status"] == "FAILED"
    assert unavailable.step_result["error_ref"] == "ae.p5_executor_unavailable"
    assert unavailable.runtime_job["state"] == "FAILED"

    factory = _factory()

    def fail(_context):
        raise RuntimeError("private failure detail")

    engine, queue, worker = _runtime(
        factory,
        engine_ids=(JOB_1_ID, RESULT_1_ID, BLOCKED_ID),
        queue_ids=(LEASE_1, ATTEMPT_1),
        callback=fail,
    )
    engine.schedule_next(tenant_id=TENANT, execution_id=EXECUTION_ID, now=NOW)
    failed = worker.run_claim(tenant_id=TENANT, claim=_claim(queue))
    assert failed.step_result["error_ref"] == "ae.p5_executor_callback_failed"
    assert "private failure detail" not in str(failed.step_result)


def test_worker_completes_recovered_job_without_reexecution() -> None:
    factory = _factory()
    queue = SqlAlchemyRuntimeJobQueue(factory, id_factory=_ids((LEASE_1, ATTEMPT_1)))
    engine = SqlAlchemyMultiStepEngine(
        factory, queue, id_factory=_ids((JOB_1_ID, RESULT_1_ID))
    )
    engine.schedule_next(tenant_id=TENANT, execution_id=EXECUTION_ID, now=NOW)
    claim = _claim(queue)
    engine.begin_claim(tenant_id=TENANT, claim=claim, now=NOW)
    result = engine.record_outcome(
        tenant_id=TENANT,
        claim=claim,
        outcome=StepTerminalOutcome(
            status="SUCCEEDED",
            result_contract_ref="contract://nex/ae/chat-result/v1",
            result_payload={"result_ref": "chat-1"},
            started_at=NOW,
            completed_at=NOW,
        ),
    )
    worker = P5StepExecutionWorker(
        engine=engine,
        jobs=queue,
        executors=default_p5_executor_registry(
            lambda _context: pytest.fail("executor must not be called")
        ),
        clock=lambda: NOW_DT,
    )

    recovered = worker.run_claim(tenant_id=TENANT, claim=claim)

    assert recovered.disposition == "ALREADY_TERMINAL"
    assert recovered.step_result == result
    assert recovered.runtime_job["state"] == "DONE"


def _context(step, dependencies=()):
    return StepExecutionContext(
        job={},
        attempt={},
        step=step,
        dependency_results=tuple(dependencies),
        existing_result=None,
    )


def test_compatibility_executor_accepts_json_response_and_maps_terminal_states() -> (
    None
):
    step = {
        "executor_kind": "P4_CHAT_RAG_COMPATIBILITY",
        "state": "RUNNING",
        "legacy_interaction_id": "interaction-1",
        "output_contract_ref": "contract://nex/ae/chat-result/v1",
    }
    executor = P5CompatibilityChatExecutor(
        lambda _context: JSONResponse(_sync_result(status="NO_ANSWER"))
    )

    outcome = executor.execute(_context(step))

    assert outcome.state == "BLOCKED"
    assert "CX:GENERATION:generation-1" in outcome.external_refs
    assert outcome.evidence_refs == ("ae-chat://interaction/interaction-1",)


def test_projection_supports_literal_resource_and_aggregate_bindings() -> None:
    dependency = {
        "step_result_id": RESULT_1_ID,
        "compiled_step_key": "E1",
        "status": "SUCCEEDED",
        "result_hash": "sha256:" + "a" * 64,
        "result_contract_ref": "contract://source",
        "result_payload": {"result_ref": "source"},
        "external_refs": ["external:1"],
        "artifact_refs": ["artifact:1"],
        "evidence_refs": ["evidence:1"],
    }
    step = {
        "executor_kind": "DETERMINISTIC_AGGREGATE",
        "output_contract_ref": "contract://aggregate",
        "compiled_input_bindings": [
            {
                "target_name": "source",
                "binding_type": "COMPILED_STEP_OUTPUT",
                "source_ref": "E1:$",
            },
            {"target_name": "literal", "binding_type": "LITERAL", "value": 3},
            {
                "target_name": "resource",
                "binding_type": "RESOURCE_REF",
                "source_ref": "AE:RESOURCE:1",
            },
        ],
    }

    outcome = P5DeterministicProjectionExecutor().execute(_context(step, (dependency,)))

    assert outcome.result_payload["projection_kind"] == "AGGREGATE"
    assert outcome.result_payload["bindings"]["literal"] == {"value": 3}
    assert outcome.external_refs == ("external:1",)
    assert outcome.artifact_refs == ("artifact:1",)


def test_registry_and_executor_contracts_fail_closed() -> None:
    with pytest.raises(P5StepExecutorError, match="unsupported"):
        P5StepExecutorRegistry({"UNKNOWN": P5DeterministicProjectionExecutor()})
    registry = P5StepExecutorRegistry({})
    with pytest.raises(P5StepExecutorError) as exc_info:
        registry.execute(_context({"executor_kind": "DELEGATE_WORK_UNAVAILABLE"}))
    assert exc_info.value.error_code == "ae.p5_executor_unavailable"

    executor = P5CompatibilityChatExecutor(lambda _context: _sync_result())
    with pytest.raises(P5StepExecutorError, match="does not match"):
        executor.execute(_context({"executor_kind": "DETERMINISTIC_REPORT"}))

    waiting = {
        "executor_kind": "P4_CHAT_RAG_COMPATIBILITY",
        "state": "WAITING",
        "legacy_interaction_id": "interaction-1",
        "output_contract_ref": "contract://chat",
    }
    with pytest.raises(P5StepExecutorError, match="requires"):
        executor.execute(_context(waiting))
    with pytest.raises(P5StepExecutorError, match="must be terminal"):
        executor.execute(_context(waiting), continuation_result=_async_result())


def test_compatibility_executor_rejects_fresh_continuation_and_bad_lineage() -> None:
    step = {
        "executor_kind": "P4_CHAT_RAG_COMPATIBILITY",
        "state": "RUNNING",
        "legacy_interaction_id": "interaction-1",
        "output_contract_ref": "contract://chat",
    }
    executor = P5CompatibilityChatExecutor(lambda _context: _sync_result())

    with pytest.raises(P5StepExecutorError, match="fresh compatibility"):
        executor.execute(_context(step), continuation_result=_sync_result())

    mismatched = P5CompatibilityChatExecutor(
        lambda _context: _sync_result(interaction_id="interaction-other")
    )
    with pytest.raises(P5StepExecutorError) as exc_info:
        mismatched.execute(_context(step))
    assert exc_info.value.error_code.startswith("ae.executable_step_")


@pytest.mark.parametrize(
    ("step", "dependencies", "continuation", "message"),
    [
        (
            {"executor_kind": "LOCAL_SKILL", "compiled_input_bindings": []},
            ({"compiled_step_key": "E1", "status": "SUCCEEDED"},),
            None,
            "kind is invalid",
        ),
        (
            {
                "executor_kind": "DETERMINISTIC_REPORT",
                "compiled_input_bindings": [],
            },
            ({"compiled_step_key": "E1", "status": "SUCCEEDED"},),
            {},
            "cannot consume",
        ),
        (
            {
                "executor_kind": "DETERMINISTIC_REPORT",
                "compiled_input_bindings": [],
            },
            (),
            None,
            "successful dependency",
        ),
        (
            {
                "executor_kind": "DETERMINISTIC_REPORT",
                "compiled_input_bindings": [],
            },
            ({"compiled_step_key": "E1", "status": "FAILED"},),
            None,
            "successful dependency",
        ),
        (
            {
                "executor_kind": "DETERMINISTIC_REPORT",
                "compiled_input_bindings": ["bad"],
            },
            ({"compiled_step_key": "E1", "status": "SUCCEEDED"},),
            None,
            "not an object",
        ),
        (
            {
                "executor_kind": "DETERMINISTIC_REPORT",
                "compiled_input_bindings": [
                    {"target_name": "same", "binding_type": "LITERAL"},
                    {"target_name": "same", "binding_type": "LITERAL"},
                ],
            },
            ({"compiled_step_key": "E1", "status": "SUCCEEDED"},),
            None,
            "duplicated",
        ),
        (
            {
                "executor_kind": "DETERMINISTIC_REPORT",
                "compiled_input_bindings": [],
            },
            ({"compiled_step_key": "E1", "status": "SUCCEEDED"},),
            None,
            "requires compiled input",
        ),
    ],
)
def test_projection_executor_rejects_invalid_contracts(
    step, dependencies, continuation, message
) -> None:
    with pytest.raises(P5StepExecutorError, match=message):
        P5DeterministicProjectionExecutor().execute(
            _context(step, dependencies), continuation_result=continuation
        )


def test_executor_reference_helpers_fail_closed() -> None:
    dependency = {
        "step_result_id": RESULT_1_ID,
        "result_hash": "sha256:" + "a" * 64,
        "result_contract_ref": "contract://source",
        "result_payload": {},
    }
    with pytest.raises(P5StepExecutorError, match="cannot be resolved"):
        step_executors._resolve_binding(
            {
                "binding_type": "COMPILED_STEP_OUTPUT",
                "source_ref": "E9:$",
            },
            {"E1": dependency},
        )
    with pytest.raises(P5StepExecutorError, match="unsupported"):
        step_executors._resolve_binding(
            {"binding_type": "SECRET", "source_ref": "secret"},
            {"E1": dependency},
        )

    assert step_executors._artifact_refs(["artifact-1"]) == ("AE:ARTIFACT:artifact-1",)
    with pytest.raises(P5StepExecutorError, match="must be an array"):
        step_executors._artifact_refs("artifact-1")
    with pytest.raises(P5StepExecutorError, match="invalid reference"):
        step_executors._artifact_refs([1])
    with pytest.raises(P5StepExecutorError, match="not an array"):
        step_executors._union_refs([{"external_refs": "bad"}], "external_refs")


def test_executor_response_and_text_helpers_fail_closed() -> None:
    with pytest.raises(P5StepExecutorError, match="valid JSON"):
        step_executors._result_record(SimpleNamespace(body=b"not-json"))
    with pytest.raises(P5StepExecutorError, match="structured record"):
        step_executors._result_record(JSONResponse(["not", "mapping"]))
    with pytest.raises(P5StepExecutorError, match="structured record"):
        step_executors._result_record(SimpleNamespace(body="not-bytes"))
    with pytest.raises(P5StepExecutorError, match="bounded string"):
        step_executors._required_text("field", "", 3)
