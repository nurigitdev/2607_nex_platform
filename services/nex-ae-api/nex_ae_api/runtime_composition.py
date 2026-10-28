from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

from nex_runtime import WorkerHeartbeatEmitter
from sqlalchemy.orm import Session, sessionmaker

from nex_ae_api.agent_runtime_dispatcher import (
    SqlAlchemyAgentRuntimeAssignmentSource,
    SqlAlchemyAgentRuntimeDispatcher,
    load_agent_runtime_dispatcher_config,
)
from nex_ae_api.agent_runtime_worker import (
    AgentRuntimeAssignment,
    AgentRuntimeWorkerConfig,
    AgentRuntimeWorkerLifecycle,
    load_agent_runtime_worker_config,
    run_bounded_agent_runtime_worker,
)
from nex_ae_api.multi_step_engine import SqlAlchemyMultiStepEngine
from nex_ae_api.nsl_approval_resume import SqlAlchemyNslApprovalResumeSource
from nex_ae_api.runtime_jobs import SqlAlchemyRuntimeJobQueue
from nex_ae_api.step_executors import (
    P5StepExecutionWorker,
    P5StepExecutorRegistry,
)
from nex_ae_api.workspace_result_publication import (
    AgentResultCompletionNotifier,
    SqlAlchemyInstalledIaResultCloser,
    SqlAlchemyWorkspaceResultPublisher,
)

AE_INSTALLED_STEP_ASSIGNMENT_SCHEMA_VERSION = "ae_installed_step_assignment.v1"


@dataclass(frozen=True)
class RuntimeExecutorProfile:
    """Domain-provided executor capabilities admitted by the installed runtime."""

    registry: P5StepExecutorRegistry
    executor_backends: Mapping[str, str]
    package_readiness: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.registry, P5StepExecutorRegistry):
            raise TypeError("executor registry is required")
        registered = set(self.registry.registered_kinds)
        if not registered:
            raise ValueError("executor registry must not be empty")
        if not isinstance(self.executor_backends, Mapping):
            raise TypeError("executor_backends must be an object")
        normalized = {
            _required_text(kind, "executor kind"): _required_text(
                backend, "backend profile"
            )
            for kind, backend in self.executor_backends.items()
        }
        if set(normalized) != registered:
            raise ValueError(
                "executor_backends must cover exactly the registered executor kinds"
            )
        if self.package_readiness is not None and not isinstance(
            self.package_readiness, Mapping
        ):
            raise TypeError("package_readiness must be an object")
        object.__setattr__(
            self, "executor_backends", MappingProxyType(dict(normalized))
        )
        if self.package_readiness is not None:
            object.__setattr__(
                self,
                "package_readiness",
                MappingProxyType(dict(self.package_readiness)),
            )

    @property
    def executor_kinds(self) -> tuple[str, ...]:
        return self.registry.registered_kinds

    @property
    def backend_profiles(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.executor_backends.values())))


class InstalledStepAssignmentHandler:
    """Execute one admitted RuntimeJob and schedule its durable successor."""

    def __init__(
        self,
        worker: P5StepExecutionWorker,
        engine: SqlAlchemyMultiStepEngine,
        *,
        clock: Callable[[], str] | None = None,
    ) -> None:
        self._worker = worker
        self._engine = engine
        self._clock = clock or _utc_now

    def __call__(self, assignment: AgentRuntimeAssignment) -> Mapping[str, Any]:
        execution = self._worker.run_claim(
            tenant_id=assignment.tenant_id,
            claim=assignment.claim,
        )
        scheduled = None
        if execution.disposition != "WAITING":
            scheduled = self._engine.schedule_next(
                tenant_id=assignment.tenant_id,
                execution_id=str(assignment.claim.job["execution_id"]),
                now=self._clock(),
            )
        step_result = execution.step_result or {}
        step = execution.step or {}
        return {
            "schema_version": AE_INSTALLED_STEP_ASSIGNMENT_SCHEMA_VERSION,
            "runtime_job_id": assignment.runtime_job_id,
            "executable_step_id": step.get("executable_step_id"),
            "disposition": execution.disposition,
            "runtime_job_state": execution.runtime_job.get("state"),
            "step_result_id": step_result.get("step_result_id"),
            "step_result_status": step_result.get("status"),
            "successor_scheduled": scheduled is not None,
            "content_included": False,
        }


@dataclass(frozen=True)
class InstalledRuntimeComposition:
    runtime_jobs: SqlAlchemyRuntimeJobQueue
    engine: SqlAlchemyMultiStepEngine
    dispatcher: SqlAlchemyAgentRuntimeDispatcher
    continuation_source: SqlAlchemyNslApprovalResumeSource
    worker: P5StepExecutionWorker
    assignment_source: SqlAlchemyAgentRuntimeAssignmentSource
    handler: InstalledStepAssignmentHandler
    worker_config: AgentRuntimeWorkerConfig
    heartbeat_emitter: WorkerHeartbeatEmitter
    executor_profile: RuntimeExecutorProfile
    result_publisher: SqlAlchemyWorkspaceResultPublisher
    result_closer: SqlAlchemyInstalledIaResultCloser

    def run_cycle(self) -> dict[str, Any]:
        lifecycle = AgentRuntimeWorkerLifecycle(
            profile=self.worker_config.profile,
            emitter=self.heartbeat_emitter,
            store=self.heartbeat_emitter.store,
        )
        result = run_bounded_agent_runtime_worker(
            config=self.worker_config,
            assignment_source=self.assignment_source,
            handler=self.handler,
            lifecycle=lifecycle,
            available_executor_kinds=self.executor_profile.executor_kinds,
            available_backend_profiles=self.executor_profile.backend_profiles,
            in_process_package_readiness=self.executor_profile.package_readiness,
            max_cycles=1,
            stop_on_failure=False,
        )
        closure = self.result_closer.close_ready(limit=10)
        claimed_count = int(result["claimed_count"])
        closure_work = int(closure["finalized_count"]) + int(closure["published_count"])
        failed_count = int(result["failed_count"]) + int(closure["failed_count"])
        return {
            "status": "WORK" if claimed_count or closure_work else "IDLE",
            "domain_claiming_enabled": True,
            "composition_mode": "GENERIC_INSTALLED_RUNTIME",
            "execution_count": claimed_count,
            "succeeded_count": result["succeeded_count"],
            "failed_count": failed_count,
            "stop_reason": result["stop_reason"],
            "result_closure": closure,
        }


def build_installed_runtime_composition(
    *,
    sessions: sessionmaker[Session],
    heartbeat_emitter: WorkerHeartbeatEmitter,
    worker_id: str,
    environ: Mapping[str, str],
    executor_profile: RuntimeExecutorProfile | None,
    completion_notifier: AgentResultCompletionNotifier | None = None,
    declared_at: str | None = None,
) -> InstalledRuntimeComposition:
    if executor_profile is None:
        raise ValueError("executor_profile is required")
    identity = _required_text(worker_id, "worker_id")
    runtime_jobs = SqlAlchemyRuntimeJobQueue(sessions)
    engine = SqlAlchemyMultiStepEngine(sessions, runtime_jobs)
    continuation_source = SqlAlchemyNslApprovalResumeSource(sessions)
    worker = P5StepExecutionWorker(
        engine=engine,
        jobs=runtime_jobs,
        executors=executor_profile.registry,
        continuation_source=continuation_source,
    )
    dispatcher = SqlAlchemyAgentRuntimeDispatcher(
        sessions,
        config=load_agent_runtime_dispatcher_config(environ),
        queue=runtime_jobs,
        executor_backends=executor_profile.executor_backends,
    )
    worker_config = load_agent_runtime_worker_config(
        _worker_environment(environ, worker_id=identity, profile=executor_profile),
        declared_at=declared_at or _utc_now(),
    )
    publisher = SqlAlchemyWorkspaceResultPublisher(
        sessions,
        completion_notifier=completion_notifier,
    )
    return InstalledRuntimeComposition(
        runtime_jobs=runtime_jobs,
        engine=engine,
        dispatcher=dispatcher,
        continuation_source=continuation_source,
        worker=worker,
        assignment_source=SqlAlchemyAgentRuntimeAssignmentSource(dispatcher),
        handler=InstalledStepAssignmentHandler(worker, engine),
        worker_config=worker_config,
        heartbeat_emitter=heartbeat_emitter,
        executor_profile=executor_profile,
        result_publisher=publisher,
        result_closer=SqlAlchemyInstalledIaResultCloser(
            sessions,
            publisher=publisher,
        ),
    )


def _worker_environment(
    environ: Mapping[str, str],
    *,
    worker_id: str,
    profile: RuntimeExecutorProfile,
) -> dict[str, str]:
    return {
        **environ,
        "NEX_AE_AGENT_WORKER_MODE": str(
            environ.get("NEX_AE_AGENT_WORKER_MODE") or "enabled"
        ),
        "NEX_AE_AGENT_WORKER_ID": str(
            environ.get("NEX_AE_AGENT_WORKER_ID") or worker_id
        ),
        "NEX_AE_AGENT_WORKER_EXECUTOR_KINDS": str(
            environ.get("NEX_AE_AGENT_WORKER_EXECUTOR_KINDS")
            or ",".join(profile.executor_kinds)
        ),
        "NEX_AE_AGENT_WORKER_BACKEND_PROFILES": str(
            environ.get("NEX_AE_AGENT_WORKER_BACKEND_PROFILES")
            or ",".join(profile.backend_profiles)
        ),
    }


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
