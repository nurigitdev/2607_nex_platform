from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nex_runtime.demo_process_runtime import DemoProcessDatabaseResource

from nex_ae_api.agent_results import SqlAlchemyAgentResultRepository
from nex_ae_api.agent_runtime_dispatcher import (
    SqlAlchemyAgentRuntimeAssignmentSource,
    SqlAlchemyAgentRuntimeDispatcher,
    load_agent_runtime_dispatcher_config,
)
from nex_ae_api.agent_runtime_worker import (
    AgentRuntimeAssignment,
    AgentRuntimeWorkerLifecycle,
    load_agent_runtime_worker_config,
    run_bounded_agent_runtime_worker,
)
from nex_ae_api.multi_step_engine import SqlAlchemyMultiStepEngine
from nex_ae_api.nsl_approval_resume import SqlAlchemyNslApprovalResumeSource
from nex_ae_api.p8_demo_controlled_skill import (
    P8DemoControlledSkillConfig,
    P8DemoControlledSkillRuntime,
)
from nex_ae_api.runtime_jobs import SqlAlchemyRuntimeJobQueue
from nex_ae_api.step_executors import (
    P5StepExecutionWorker,
    default_p6_executor_registry,
)
from nex_ae_api.wa_completion_notifications import (
    build_ae_wa_post_completion_notifier,
)
from nex_ae_api.wa_source_projections import SqlAlchemyAgentResultWaProjectionSource
from nex_ae_api.workspace_result_publication import (
    SqlAlchemyInstalledIaResultCloser,
    SqlAlchemyWorkspaceResultPublisher,
)

ROOT = Path(__file__).resolve().parents[3]


class InstalledP8StepAssignmentHandler:
    """Run one admitted step and schedule its durable successor."""

    def __init__(
        self,
        worker: P5StepExecutionWorker,
        engine: SqlAlchemyMultiStepEngine,
    ) -> None:
        self._worker = worker
        self._engine = engine

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
                now=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            )
        step_result = execution.step_result or {}
        step = execution.step or {}
        return {
            "schema_version": "p8_demo_installed_step_assignment.v1",
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
class InstalledP8RuntimeComposition:
    controlled_skill: P8DemoControlledSkillRuntime
    assignment_source: SqlAlchemyAgentRuntimeAssignmentSource
    handler: InstalledP8StepAssignmentHandler
    worker_config: Any
    heartbeat_emitter: Any
    executor_kinds: tuple[str, ...]
    backend_profiles: tuple[str, ...]
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
            available_executor_kinds=self.executor_kinds,
            available_backend_profiles=self.backend_profiles,
            in_process_package_readiness=self.controlled_skill.package_readiness,
            max_cycles=1,
            stop_on_failure=False,
        )
        closure = self.result_closer.close_ready(limit=10)
        claimed_count = int(result["claimed_count"])
        closure_work = int(closure["finalized_count"]) + int(
            closure["published_count"]
        )
        failed_count = int(result["failed_count"]) + int(closure["failed_count"])
        return {
            "status": "WORK" if claimed_count or closure_work else "IDLE",
            "domain_claiming_enabled": True,
            "composition_mode": "EXISTING_COMPONENT_COMPOSITION",
            "execution_count": claimed_count,
            "succeeded_count": result["succeeded_count"],
            "failed_count": failed_count,
            "stop_reason": result["stop_reason"],
            "result_closure": closure,
        }


def build_installed_p8_runtime_composition(
    resource: DemoProcessDatabaseResource,
    environ: Mapping[str, str],
) -> InstalledP8RuntimeComposition:
    controlled = P8DemoControlledSkillRuntime(
        resource.sessions,
        _controlled_skill_config(environ),
    )
    jobs = SqlAlchemyRuntimeJobQueue(resource.sessions)
    engine = SqlAlchemyMultiStepEngine(resource.sessions, jobs)
    registry = default_p6_executor_registry(
        lambda _context: {},
        local_skill_dependencies=controlled.dependencies,
        local_skill_handler=controlled.initial,
        local_skill_continuation_handler=controlled.resume,
    )
    worker = P5StepExecutionWorker(
        engine=engine,
        jobs=jobs,
        executors=registry,
        continuation_source=SqlAlchemyNslApprovalResumeSource(resource.sessions),
    )
    executor_backends = {
        kind: controlled.backend_profile for kind in registry.registered_kinds
    }
    dispatcher = SqlAlchemyAgentRuntimeDispatcher(
        resource.sessions,
        config=load_agent_runtime_dispatcher_config(environ),
        queue=jobs,
        executor_backends=executor_backends,
    )
    worker_environ = {
        **environ,
        "NEX_AE_AGENT_WORKER_MODE": str(
            environ.get("NEX_AE_AGENT_WORKER_MODE") or "enabled"
        ),
        "NEX_AE_AGENT_WORKER_ID": str(
            environ.get("NEX_AE_AGENT_WORKER_ID") or resource.config.worker_id
        ),
        "NEX_AE_AGENT_WORKER_EXECUTOR_KINDS": str(
            environ.get("NEX_AE_AGENT_WORKER_EXECUTOR_KINDS")
            or ",".join(registry.registered_kinds)
        ),
        "NEX_AE_AGENT_WORKER_BACKEND_PROFILES": str(
            environ.get("NEX_AE_AGENT_WORKER_BACKEND_PROFILES") or "NSL_V02_IN_PROCESS"
        ),
    }
    worker_config = load_agent_runtime_worker_config(
        worker_environ,
        declared_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    )
    return InstalledP8RuntimeComposition(
        controlled_skill=controlled,
        assignment_source=SqlAlchemyAgentRuntimeAssignmentSource(dispatcher),
        handler=InstalledP8StepAssignmentHandler(worker, engine),
        worker_config=worker_config,
        heartbeat_emitter=resource.heartbeat,
        executor_kinds=registry.registered_kinds,
        backend_profiles=registry.backend_profiles,
        result_closer=SqlAlchemyInstalledIaResultCloser(
            resource.sessions,
            publisher=SqlAlchemyWorkspaceResultPublisher(
                resource.sessions,
                completion_notifier=_optional_wa_notifier(resource, environ),
            ),
        ),
    )


def _controlled_skill_config(
    environ: Mapping[str, str],
) -> P8DemoControlledSkillConfig:
    return P8DemoControlledSkillConfig(
        manifest_path=_path(
            environ,
            "NEX_AE_DEMO_NSL_BUNDLE_MANIFEST",
            ROOT / "deployment/locks/p8-demo-nsl-runtime-bundle.v1.json",
        ),
        wheel_path=_path(
            environ,
            "NEX_AE_DEMO_NSL_WHEEL",
            ROOT
            / "reports/deployment/p8-nsl-v0.2.1-wheel"
            / "nex_skill_language-0.2.1-py3-none-any.whl",
        ),
        platform_lock_path=_path(
            environ,
            "NEX_AE_DEMO_PLATFORM_LOCK",
            ROOT / "deployment/locks/python-production.lock",
        ),
        skill_root=_path(
            environ,
            "NEX_AE_DEMO_NSL_SKILL_ROOT",
            Path("/home/tprover/2608_nsl/examples/golden_a_voucher_draft"),
        ),
        demo_fixture_path=_path(
            environ,
            "NEX_AE_DEMO_FIXTURE",
            ROOT / "scripts/deployment/data/p8_demo_vo00_fixture.v1.json",
        ),
        base_fixture_path=_path(
            environ,
            "NEX_AE_DEMO_BASE_FIXTURE",
            ROOT / "scripts/smoke/data/p8_golden_a_fixture.v1.json",
        ),
        state_root=_path(
            environ,
            "NEX_AE_DEMO_NSL_STATE_ROOT",
            Path("/data/nex-platform/ae/nsl-runtime"),
            require_existing=False,
        ),
        oa_base_url=_text(environ, "NEX_OA_BASE_URL"),
        eos_base_url=_text(environ, "NEX_EOS_BASE_URL"),
        ae_to_oa_service_token=_text(environ, "NEX_AE_TO_OA_SERVICE_TOKEN"),
        ae_to_eos_service_token=_text(environ, "NEX_AE_TO_EOS_SERVICE_TOKEN"),
    )


def _optional_wa_notifier(
    resource: DemoProcessDatabaseResource,
    environ: Mapping[str, str],
):
    profile = str(
        environ.get("NEX_SERVICE_TOKEN_ROLLOUT_PROFILE") or "TEST_MOCK"
    ).strip().upper()
    if profile != "TEST_MOCK" and not str(
        environ.get("NEX_AE_TO_WA_SERVICE_TOKEN") or ""
    ).strip():
        return None
    return build_ae_wa_post_completion_notifier(
        agent_results=SqlAlchemyAgentResultWaProjectionSource(
            SqlAlchemyAgentResultRepository(resource.sessions)
        ),
        environ=environ,
    )


def _path(
    environ: Mapping[str, str],
    name: str,
    default: Path,
    *,
    require_existing: bool = True,
) -> Path:
    path = Path(str(environ.get(name) or default)).expanduser()
    if require_existing and not path.exists():
        raise ValueError(f"{name} is unavailable")
    return path


def _text(environ: Mapping[str, str], name: str) -> str:
    value = str(environ.get(name) or "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value
