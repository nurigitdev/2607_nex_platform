from __future__ import annotations

import inspect
from types import SimpleNamespace

import nex_ae_api.runtime_composition as composition
import pytest
from nex_ae_api.agent_runtime_dispatcher import (
    SqlAlchemyAgentRuntimeAssignmentSource,
    SqlAlchemyAgentRuntimeDispatcher,
)
from nex_ae_api.agent_runtime_worker import AgentRuntimeAssignment
from nex_ae_api.multi_step_engine import SqlAlchemyMultiStepEngine
from nex_ae_api.nsl_approval_resume import SqlAlchemyNslApprovalResumeSource
from nex_ae_api.runtime_jobs import RuntimeJobClaim, SqlAlchemyRuntimeJobQueue
from nex_ae_api.step_executors import (
    P5StepExecutionWorker,
    P5StepExecutorRegistry,
    P5WorkerExecution,
)
from nex_ae_api.workspace_result_publication import (
    SqlAlchemyInstalledIaResultCloser,
    SqlAlchemyWorkspaceResultPublisher,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


class _FakeExecutor:
    def execute(
        self, _context: object, *, continuation_result: object = None
    ) -> object:
        return continuation_result


def _executor_profile() -> composition.RuntimeExecutorProfile:
    return composition.RuntimeExecutorProfile(
        registry=P5StepExecutorRegistry({"DETERMINISTIC_REPORT": _FakeExecutor()}),
        executor_backends={"DETERMINISTIC_REPORT": "NSL_V02_IN_PROCESS"},
        package_readiness={"status": "PASS"},
    )


def _claim() -> RuntimeJobClaim:
    return RuntimeJobClaim(
        job={
            "tenant_id": "VO00",
            "runtime_job_id": "job-1",
            "execution_id": "execution-1",
            "state": "RUNNING",
            "lease_owner": "worker-1",
            "lease_token": "lease-1",
        },
        attempt={"attempt_no": 1},
        executor_kind="DETERMINISTIC_REPORT",
        backend_profile="NSL_V02_IN_PROCESS",
    )


def _runtime(
    *, result_closer: object, executor_profile: composition.RuntimeExecutorProfile
) -> composition.InstalledRuntimeComposition:
    placeholder = object()
    return composition.InstalledRuntimeComposition(
        runtime_jobs=placeholder,
        engine=placeholder,
        dispatcher=placeholder,
        continuation_source=placeholder,
        worker=placeholder,
        assignment_source=placeholder,
        handler=placeholder,
        worker_config=SimpleNamespace(profile=object()),
        heartbeat_emitter=SimpleNamespace(store=object()),
        executor_profile=executor_profile,
        result_publisher=placeholder,
        result_closer=result_closer,
    )


def test_generic_composition_builds_from_non_demo_executor_profile() -> None:
    sessions = sessionmaker(create_engine("sqlite+pysqlite:///:memory:"))
    notifier = SimpleNamespace(notify_agent_result=lambda **_values: None)
    heartbeat = SimpleNamespace(store=object())

    runtime = composition.build_installed_runtime_composition(
        sessions=sessions,
        heartbeat_emitter=heartbeat,
        worker_id="ae-runtime-worker-test",
        environ={},
        executor_profile=_executor_profile(),
        completion_notifier=notifier,
        declared_at="2026-10-28T00:00:00Z",
    )

    assert isinstance(runtime.runtime_jobs, SqlAlchemyRuntimeJobQueue)
    assert isinstance(runtime.engine, SqlAlchemyMultiStepEngine)
    assert isinstance(runtime.dispatcher, SqlAlchemyAgentRuntimeDispatcher)
    assert isinstance(runtime.continuation_source, SqlAlchemyNslApprovalResumeSource)
    assert isinstance(runtime.worker, P5StepExecutionWorker)
    assert isinstance(runtime.assignment_source, SqlAlchemyAgentRuntimeAssignmentSource)
    assert isinstance(runtime.handler, composition.InstalledStepAssignmentHandler)
    assert isinstance(runtime.result_publisher, SqlAlchemyWorkspaceResultPublisher)
    assert isinstance(runtime.result_closer, SqlAlchemyInstalledIaResultCloser)
    assert runtime.worker_config.mode == "enabled"
    assert runtime.worker_config.profile.worker_id == "ae-runtime-worker-test"
    assert runtime.worker_config.profile.supported_executor_kinds == (
        "DETERMINISTIC_REPORT",
    )
    assert runtime.worker_config.profile.supported_backend_profiles == (
        "NSL_V02_IN_PROCESS",
    )
    assert runtime.result_publisher._completion_notifier is notifier


def test_generic_composition_rejects_missing_executor_profile() -> None:
    sessions = sessionmaker(create_engine("sqlite+pysqlite:///:memory:"))

    with pytest.raises(ValueError, match="executor_profile is required"):
        composition.build_installed_runtime_composition(
            sessions=sessions,
            heartbeat_emitter=SimpleNamespace(store=object()),
            worker_id="worker-1",
            environ={},
            executor_profile=None,
        )


@pytest.mark.parametrize(
    ("registry", "backends", "readiness", "error_type", "message"),
    (
        (object(), {}, None, TypeError, "executor registry is required"),
        (P5StepExecutorRegistry({}), {}, None, ValueError, "must not be empty"),
        (
            P5StepExecutorRegistry({"DETERMINISTIC_REPORT": _FakeExecutor()}),
            [],
            None,
            TypeError,
            "must be an object",
        ),
        (
            P5StepExecutorRegistry({"DETERMINISTIC_REPORT": _FakeExecutor()}),
            {},
            None,
            ValueError,
            "cover exactly",
        ),
        (
            P5StepExecutorRegistry({"DETERMINISTIC_REPORT": _FakeExecutor()}),
            {"DETERMINISTIC_REPORT": "NSL_V02_IN_PROCESS"},
            [],
            TypeError,
            "package_readiness must be an object",
        ),
    ),
)
def test_executor_profile_fails_closed(
    registry: object,
    backends: object,
    readiness: object,
    error_type: type[Exception],
    message: str,
) -> None:
    with pytest.raises(error_type, match=message):
        composition.RuntimeExecutorProfile(
            registry=registry,
            executor_backends=backends,
            package_readiness=readiness,
        )


@pytest.mark.parametrize(
    "backends",
    (
        {"": "NSL_V02_IN_PROCESS"},
        {"DETERMINISTIC_REPORT": ""},
        {1: "NSL_V02_IN_PROCESS"},
    ),
)
def test_executor_profile_rejects_blank_or_non_text_capability(
    backends: object,
) -> None:
    with pytest.raises(ValueError, match="must be a non-empty string"):
        composition.RuntimeExecutorProfile(
            registry=P5StepExecutorRegistry({"DETERMINISTIC_REPORT": _FakeExecutor()}),
            executor_backends=backends,
        )


def test_executor_profile_accepts_no_package_readiness() -> None:
    profile = composition.RuntimeExecutorProfile(
        registry=P5StepExecutorRegistry({"DETERMINISTIC_REPORT": _FakeExecutor()}),
        executor_backends={"DETERMINISTIC_REPORT": "NSL_V02_IN_PROCESS"},
    )

    assert profile.package_readiness is None


def test_worker_environment_preserves_explicit_runtime_configuration() -> None:
    profile = _executor_profile()
    values = composition._worker_environment(
        {
            "NEX_AE_AGENT_WORKER_MODE": "disabled",
            "NEX_AE_AGENT_WORKER_ID": "configured-worker",
            "NEX_AE_AGENT_WORKER_EXECUTOR_KINDS": "DETERMINISTIC_REPORT",
            "NEX_AE_AGENT_WORKER_BACKEND_PROFILES": "NSL_V02_IN_PROCESS",
        },
        worker_id="default-worker",
        profile=profile,
    )

    assert values == {
        "NEX_AE_AGENT_WORKER_MODE": "disabled",
        "NEX_AE_AGENT_WORKER_ID": "configured-worker",
        "NEX_AE_AGENT_WORKER_EXECUTOR_KINDS": "DETERMINISTIC_REPORT",
        "NEX_AE_AGENT_WORKER_BACKEND_PROFILES": "NSL_V02_IN_PROCESS",
    }


@pytest.mark.parametrize("worker_id", ("", "   ", None))
def test_builder_rejects_invalid_worker_identity(worker_id: object) -> None:
    sessions = sessionmaker(create_engine("sqlite+pysqlite:///:memory:"))

    with pytest.raises(ValueError, match="worker_id must be a non-empty string"):
        composition.build_installed_runtime_composition(
            sessions=sessions,
            heartbeat_emitter=SimpleNamespace(store=object()),
            worker_id=worker_id,
            environ={},
            executor_profile=_executor_profile(),
        )


def test_non_waiting_assignment_schedules_successor() -> None:
    scheduled: list[dict[str, str]] = []
    worker = SimpleNamespace(
        run_claim=lambda **_values: P5WorkerExecution(
            disposition="TERMINAL",
            step={"executable_step_id": "step-1"},
            step_result={"step_result_id": "result-1", "status": "SUCCEEDED"},
            runtime_job={"state": "DONE"},
        )
    )
    engine = SimpleNamespace(
        schedule_next=lambda **values: (
            scheduled.append(values) or {"runtime_job_id": "job-2"}
        )
    )
    assignment = AgentRuntimeAssignment(
        tenant_id="VO00",
        executor_kind="DETERMINISTIC_REPORT",
        backend_profile="NSL_V02_IN_PROCESS",
        claim=_claim(),
    )

    result = composition.InstalledStepAssignmentHandler(
        worker,
        engine,
        clock=lambda: "2026-10-28T00:00:00Z",
    )(assignment)

    assert result == {
        "schema_version": "ae_installed_step_assignment.v1",
        "runtime_job_id": "job-1",
        "executable_step_id": "step-1",
        "disposition": "TERMINAL",
        "runtime_job_state": "DONE",
        "step_result_id": "result-1",
        "step_result_status": "SUCCEEDED",
        "successor_scheduled": True,
        "content_included": False,
    }
    assert scheduled == [
        {
            "tenant_id": "VO00",
            "execution_id": "execution-1",
            "now": "2026-10-28T00:00:00Z",
        }
    ]


def test_waiting_assignment_does_not_schedule_successor() -> None:
    worker = SimpleNamespace(
        run_claim=lambda **_values: P5WorkerExecution(
            disposition="WAITING",
            step=None,
            step_result=None,
            runtime_job={"state": "DONE"},
        )
    )
    engine = SimpleNamespace(
        schedule_next=lambda **_values: pytest.fail(
            "WAITING assignment must not schedule a successor"
        )
    )
    assignment = AgentRuntimeAssignment(
        tenant_id="VO00",
        executor_kind="DETERMINISTIC_REPORT",
        backend_profile="NSL_V02_IN_PROCESS",
        claim=_claim(),
    )

    result = composition.InstalledStepAssignmentHandler(worker, engine)(assignment)

    assert result["successor_scheduled"] is False
    assert result["executable_step_id"] is None
    assert result["step_result_id"] is None


@pytest.mark.parametrize(
    ("worker_result", "closure", "expected_status", "expected_failed"),
    (
        (
            {
                "claimed_count": 1,
                "succeeded_count": 1,
                "failed_count": 0,
                "stop_reason": "MAX_CYCLES",
            },
            {
                "finalized_count": 0,
                "published_count": 0,
                "failed_count": 0,
            },
            "WORK",
            0,
        ),
        (
            {
                "claimed_count": 0,
                "succeeded_count": 0,
                "failed_count": 0,
                "stop_reason": "MAX_CYCLES",
            },
            {
                "finalized_count": 1,
                "published_count": 0,
                "failed_count": 1,
            },
            "WORK",
            1,
        ),
        (
            {
                "claimed_count": 0,
                "succeeded_count": 0,
                "failed_count": 1,
                "stop_reason": "MAX_CYCLES",
            },
            {
                "finalized_count": 0,
                "published_count": 0,
                "failed_count": 1,
            },
            "IDLE",
            2,
        ),
    ),
)
def test_runtime_cycle_uses_canonical_claim_counter_and_closes_results(
    monkeypatch: pytest.MonkeyPatch,
    worker_result: dict[str, object],
    closure: dict[str, int],
    expected_status: str,
    expected_failed: int,
) -> None:
    captured: dict[str, object] = {}
    close_calls: list[dict[str, int]] = []

    def run_worker(**values: object) -> dict[str, object]:
        captured.update(values)
        return worker_result

    monkeypatch.setattr(
        composition,
        "AgentRuntimeWorkerLifecycle",
        lambda **values: SimpleNamespace(**values),
    )
    monkeypatch.setattr(composition, "run_bounded_agent_runtime_worker", run_worker)
    closer = SimpleNamespace(
        close_ready=lambda **values: close_calls.append(values) or closure
    )

    result = _runtime(
        result_closer=closer,
        executor_profile=_executor_profile(),
    ).run_cycle()

    assert result["status"] == expected_status
    assert result["execution_count"] == worker_result["claimed_count"]
    assert result["failed_count"] == expected_failed
    assert result["composition_mode"] == "GENERIC_INSTALLED_RUNTIME"
    assert close_calls == [{"limit": 10}]
    assert captured["max_cycles"] == 1
    assert captured["stop_on_failure"] is False
    assert captured["in_process_package_readiness"] == {"status": "PASS"}


def test_generic_module_has_no_demo_dependency() -> None:
    source = inspect.getsource(composition)

    assert "p8_demo" not in source
    assert "demo_fixture" not in source
    assert "/home/" not in source
    assert composition._utc_now().endswith("Z")
