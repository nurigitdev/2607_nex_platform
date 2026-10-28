from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from nex_runtime.demo_process_runtime import DemoProcessDatabaseResource

from nex_ae_api.agent_results import SqlAlchemyAgentResultRepository
from nex_ae_api.p8_demo_controlled_skill import (
    P8DemoControlledSkillConfig,
    P8DemoControlledSkillRuntime,
)
from nex_ae_api.runtime_composition import (
    InstalledRuntimeComposition,
    InstalledStepAssignmentHandler,
    RuntimeExecutorProfile,
    build_installed_runtime_composition,
)
from nex_ae_api.step_executors import (
    default_p6_executor_registry,
)
from nex_ae_api.wa_completion_notifications import (
    build_ae_wa_post_completion_notifier,
)
from nex_ae_api.wa_source_projections import SqlAlchemyAgentResultWaProjectionSource

ROOT = Path(__file__).resolve().parents[3]

InstalledP8StepAssignmentHandler = InstalledStepAssignmentHandler


@dataclass(frozen=True)
class InstalledP8RuntimeComposition:
    controlled_skill: P8DemoControlledSkillRuntime
    installed_runtime: InstalledRuntimeComposition

    @property
    def assignment_source(self):
        return self.installed_runtime.assignment_source

    @property
    def handler(self):
        return self.installed_runtime.handler

    @property
    def worker_config(self):
        return self.installed_runtime.worker_config

    @property
    def heartbeat_emitter(self):
        return self.installed_runtime.heartbeat_emitter

    @property
    def executor_kinds(self) -> tuple[str, ...]:
        return self.installed_runtime.executor_profile.executor_kinds

    @property
    def backend_profiles(self) -> tuple[str, ...]:
        return self.installed_runtime.executor_profile.backend_profiles

    @property
    def result_closer(self):
        return self.installed_runtime.result_closer

    def run_cycle(self) -> dict[str, object]:
        result = dict(self.installed_runtime.run_cycle())
        result["composition_mode"] = "EXISTING_COMPONENT_COMPOSITION"
        return result


def build_installed_p8_runtime_composition(
    resource: DemoProcessDatabaseResource,
    environ: Mapping[str, str],
) -> InstalledP8RuntimeComposition:
    controlled = P8DemoControlledSkillRuntime(
        resource.sessions,
        _controlled_skill_config(environ),
    )
    registry = default_p6_executor_registry(
        lambda _context: {},
        local_skill_dependencies=controlled.dependencies,
        local_skill_handler=controlled.initial,
        local_skill_continuation_handler=controlled.resume,
    )
    executor_profile = RuntimeExecutorProfile(
        registry=registry,
        executor_backends={
            kind: controlled.backend_profile for kind in registry.registered_kinds
        },
        package_readiness=controlled.package_readiness,
    )
    return InstalledP8RuntimeComposition(
        controlled_skill=controlled,
        installed_runtime=build_installed_runtime_composition(
            sessions=resource.sessions,
            heartbeat_emitter=resource.heartbeat,
            worker_id=resource.config.worker_id,
            environ=environ,
            executor_profile=executor_profile,
            completion_notifier=_optional_wa_notifier(resource, environ),
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
    profile = (
        str(environ.get("NEX_SERVICE_TOKEN_ROLLOUT_PROFILE") or "TEST_MOCK")
        .strip()
        .upper()
    )
    if (
        profile != "TEST_MOCK"
        and not str(environ.get("NEX_AE_TO_WA_SERVICE_TOKEN") or "").strip()
    ):
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
