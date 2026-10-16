from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from nex_ae_api.multi_step_engine import StepExecutionContext
from nex_ae_api.nsl_backend_profiles import (
    NSL_V01_IN_PROCESS_BACKEND,
    NSL_V01_PROCESS_ISOLATED_BACKEND,
)
from nex_ae_api.nsl_read_backends import (
    NSLReadBackendError,
    NSLReadBackendRouter,
    NSLReadExecutionService,
)
from nex_ae_api.step_executors import (
    LocalSkillExecutorDependencies,
    P5ExecutorOutcome,
    P5StepExecutorError,
    P5StepExecutorRegistry,
    P6LocalSkillExecutor,
)

TENANT = "tenant-p6-ca02-s4"
STEP_ID = "33333333-3333-4333-8333-333333333333"
NSL_ID = "66666666-6666-4666-8666-666666666666"
NOW = "2026-10-16T03:00:00Z"


class _Backend:
    def __init__(self, profile: str, *, result_profile: str | None = None) -> None:
        self.backend_profile = profile
        self.result_profile = result_profile or profile
        self.calls: list[dict[str, Any]] = []

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {
            "backend_profile": self.result_profile,
            "nsl_execution_id": NSL_ID,
            "attempt_no": kwargs["attempt_no"],
        }


class _Bindings:
    def __init__(self, profile: str) -> None:
        self.profile = profile
        self.started = 0

    def get(self, **_kwargs: Any) -> dict[str, Any]:
        return {
            "binding": {
                "backend_profile": self.profile,
                "nsl_execution_id": NSL_ID,
                "verified_artifact_ref": "AE:NSL_ARTIFACT:s4",
            }
        }

    def mark_invocation_started(self, **_kwargs: Any) -> dict[str, Any]:
        self.started += 1
        return {
            "binding": {"invocation_started_at": NOW},
            "request": {"nsl_execution_id": NSL_ID},
            "context_projection": {"projection_hash": "sha256:" + "2" * 64},
        }


class _Artifacts:
    def get(self, **_kwargs: Any) -> dict[str, Any]:
        return {"artifact_ref": "AE:NSL_ARTIFACT:s4"}


class _Runs:
    def __init__(self, existing: dict[str, Any] | None = None) -> None:
        self.existing = existing
        self.saved: list[dict[str, Any]] = []

    def get(self, **_kwargs: Any) -> dict[str, Any] | None:
        return self.existing

    def save(self, *, record: dict[str, Any]) -> dict[str, Any]:
        self.saved.append(record)
        return record


def _router(*profiles: str) -> NSLReadBackendRouter:
    return NSLReadBackendRouter(
        {profile: _Backend(profile) for profile in profiles}
    )


def _service(
    profile: str,
    router: NSLReadBackendRouter,
    *,
    runs: _Runs | None = None,
) -> NSLReadExecutionService:
    return NSLReadExecutionService(
        bindings=_Bindings(profile),  # type: ignore[arg-type]
        artifacts=_Artifacts(),
        backend=router,
        runs=runs or _Runs(),  # type: ignore[arg-type]
    )


def _binding(profile: str) -> dict[str, str]:
    return {
        "skill_id": "FINANCE.PROJECT_BUDGET_CHECK",
        "exact_skill_version": "1.0.0",
        "skill_semantic_hash": "sha256:" + "1" * 64,
        "runtime_contract_ref": "contract://nex/nsl/read-runtime/v0.1",
        "trust_policy_id": "nsl.production.ed25519.v1",
        "backend_profile": profile,
        "package_requirement": "SIGNED_TRUSTED_ACTIVE",
    }


def _context(profile: str) -> StepExecutionContext:
    return StepExecutionContext(
        job={"tenant_id": TENANT},
        attempt={"attempt_no": 1},
        step={
            "executable_step_id": STEP_ID,
            "executor_kind": "LOCAL_SKILL",
            "step_type": "LOCAL_SKILL",
            "skill_binding": _binding(profile),
        },
        dependency_results=(),
        existing_result=None,
    )


def _dependencies(router: object) -> LocalSkillExecutorDependencies:
    return LocalSkillExecutorDependencies(
        artifact_gateway=SimpleNamespace(resolve_verified=lambda **_kwargs: {}),
        binding_repository=SimpleNamespace(bind_request=lambda **_kwargs: {}),
        request_builder=lambda **_kwargs: {},
        backend=router,
        result_mapper=lambda _outcome: P5ExecutorOutcome(
            state="SUCCEEDED",
            result_contract_ref="contract://nex/p6/step-result/v1.2",
            result_payload={},
        ),
    )


def test_router_resolves_only_the_exact_configured_profile() -> None:
    in_process = _Backend(NSL_V01_IN_PROCESS_BACKEND)
    isolated = _Backend(NSL_V01_PROCESS_ISOLATED_BACKEND)
    router = NSLReadBackendRouter(
        {
            NSL_V01_PROCESS_ISOLATED_BACKEND: isolated,
            NSL_V01_IN_PROCESS_BACKEND: in_process,
        }
    )

    assert router.backend_profiles == (
        NSL_V01_IN_PROCESS_BACKEND,
        NSL_V01_PROCESS_ISOLATED_BACKEND,
    )
    assert router.resolve(NSL_V01_IN_PROCESS_BACKEND) is in_process
    assert router.resolve(NSL_V01_PROCESS_ISOLATED_BACKEND) is isolated


def test_router_fails_closed_for_unknown_or_unconfigured_profile() -> None:
    router = _router(NSL_V01_IN_PROCESS_BACKEND)

    with pytest.raises(NSLReadBackendError) as unavailable:
        router.resolve(NSL_V01_PROCESS_ISOLATED_BACKEND)
    assert unavailable.value.error_code == "ae.nsl_backend_profile_unavailable"
    assert unavailable.value.retryable is True

    with pytest.raises(NSLReadBackendError) as unsupported:
        router.resolve("NSL_V02_REMOTE")
    assert unsupported.value.error_code == "ae.nsl_backend_profile_unsupported"


@pytest.mark.parametrize(
    "backends",
    (
        {},
        {"NSL_V02_REMOTE": _Backend(NSL_V01_IN_PROCESS_BACKEND)},
        {NSL_V01_IN_PROCESS_BACKEND: object()},
        {
            NSL_V01_IN_PROCESS_BACKEND: _Backend(
                NSL_V01_PROCESS_ISOLATED_BACKEND
            )
        },
        {
            NSL_V01_IN_PROCESS_BACKEND: _Backend("NSL_V02_REMOTE")
        },
    ),
)
def test_router_rejects_invalid_configuration(backends: object) -> None:
    with pytest.raises(NSLReadBackendError) as caught:
        NSLReadBackendRouter(backends)  # type: ignore[arg-type]
    assert caught.value.error_code == "ae.nsl_read_backend_unavailable"


@pytest.mark.parametrize(
    "profile",
    (NSL_V01_IN_PROCESS_BACKEND, NSL_V01_PROCESS_ISOLATED_BACKEND),
)
def test_execution_service_routes_from_durable_binding(profile: str) -> None:
    router = _router(
        NSL_V01_IN_PROCESS_BACKEND,
        NSL_V01_PROCESS_ISOLATED_BACKEND,
    )
    backend = router.resolve(profile)

    service = _service(profile, router)
    result = service.execute_bound(
        tenant_id=TENANT,
        executable_step_id=STEP_ID,
        attempt_no=2,
        expected_backend_profile=profile,
    )

    assert result["backend_profile"] == profile
    assert len(backend.calls) == 1  # type: ignore[attr-defined]
    with pytest.raises(NSLReadBackendError, match="multiple configured"):
        _ = service.backend_profile


def test_single_backend_execution_service_preserves_profile_compatibility() -> None:
    backend = _Backend(NSL_V01_IN_PROCESS_BACKEND)
    service = NSLReadExecutionService(
        bindings=_Bindings(NSL_V01_IN_PROCESS_BACKEND),  # type: ignore[arg-type]
        artifacts=_Artifacts(),
        backend=backend,
        runs=_Runs(),  # type: ignore[arg-type]
    )

    assert service.backend_profile == NSL_V01_IN_PROCESS_BACKEND
    assert service.backend_profiles == (NSL_V01_IN_PROCESS_BACKEND,)


def test_execution_service_rejects_compiled_persisted_and_run_profile_drift() -> None:
    router = _router(
        NSL_V01_IN_PROCESS_BACKEND,
        NSL_V01_PROCESS_ISOLATED_BACKEND,
    )
    service = _service(NSL_V01_IN_PROCESS_BACKEND, router)
    with pytest.raises(NSLReadBackendError) as compiled_drift:
        service.execute_bound(
            tenant_id=TENANT,
            executable_step_id=STEP_ID,
            attempt_no=1,
            expected_backend_profile=NSL_V01_PROCESS_ISOLATED_BACKEND,
        )
    assert compiled_drift.value.error_code == "ae.nsl_backend_profile_mismatch"

    with pytest.raises(NSLReadBackendError) as invalid_expected:
        service.execute_bound(
            tenant_id=TENANT,
            executable_step_id=STEP_ID,
            attempt_no=1,
            expected_backend_profile="NSL_V02_REMOTE",
        )
    assert invalid_expected.value.error_code == "ae.nsl_backend_profile_unsupported"

    existing = {
        "backend_profile": NSL_V01_PROCESS_ISOLATED_BACKEND,
        "nsl_execution_id": NSL_ID,
    }
    with pytest.raises(NSLReadBackendError) as run_drift:
        _service(
            NSL_V01_IN_PROCESS_BACKEND,
            router,
            runs=_Runs(existing),
        ).execute_bound(
            tenant_id=TENANT,
            executable_step_id=STEP_ID,
            attempt_no=1,
        )
    assert run_drift.value.error_code == "ae.nsl_backend_profile_mismatch"


def test_execution_service_rejects_backend_result_profile_drift() -> None:
    backend = _Backend(
        NSL_V01_IN_PROCESS_BACKEND,
        result_profile=NSL_V01_PROCESS_ISOLATED_BACKEND,
    )
    router = NSLReadBackendRouter({NSL_V01_IN_PROCESS_BACKEND: backend})

    with pytest.raises(NSLReadBackendError) as caught:
        _service(NSL_V01_IN_PROCESS_BACKEND, router).execute_bound(
            tenant_id=TENANT,
            executable_step_id=STEP_ID,
            attempt_no=1,
        )

    assert caught.value.error_code == "ae.nsl_backend_profile_mismatch"


def test_local_skill_executor_and_registry_advertise_routed_profiles() -> None:
    router = _router(
        NSL_V01_IN_PROCESS_BACKEND,
        NSL_V01_PROCESS_ISOLATED_BACKEND,
    )
    seen: list[str] = []
    executor = P6LocalSkillExecutor(
        dependencies=_dependencies(router),
        handler=lambda context, _dependencies: (
            seen.append(context.step["skill_binding"]["backend_profile"])
            or P5ExecutorOutcome(
                state="SUCCEEDED",
                result_contract_ref="contract://nex/p6/step-result/v1.2",
                result_payload={},
            )
        ),
    )
    registry = P5StepExecutorRegistry({"LOCAL_SKILL": executor})

    registry.execute(_context(NSL_V01_IN_PROCESS_BACKEND))
    registry.execute(_context(NSL_V01_PROCESS_ISOLATED_BACKEND))

    assert registry.backend_profiles == router.backend_profiles
    assert seen == [
        NSL_V01_IN_PROCESS_BACKEND,
        NSL_V01_PROCESS_ISOLATED_BACKEND,
    ]
    with pytest.raises(P5StepExecutorError, match="multiple configured"):
        _ = executor.backend_profile


@pytest.mark.parametrize(
    "router",
    (
        SimpleNamespace(backend_profiles=(), resolve=lambda _profile: None),
        SimpleNamespace(
            backend_profiles=(NSL_V01_IN_PROCESS_BACKEND,), resolve=None
        ),
        SimpleNamespace(
            backend_profiles=(
                NSL_V01_IN_PROCESS_BACKEND,
                NSL_V01_IN_PROCESS_BACKEND,
            ),
            resolve=lambda _profile: None,
        ),
        SimpleNamespace(
            backend_profiles=("NSL_V02_REMOTE",),
            resolve=lambda _profile: None,
        ),
    ),
)
def test_local_skill_executor_rejects_invalid_router_contract(router: object) -> None:
    with pytest.raises(P5StepExecutorError) as caught:
        P6LocalSkillExecutor(
            dependencies=_dependencies(router),
            handler=lambda _context, _dependencies: None,
        )
    assert caught.value.error_code == "ae.local_skill_dependency_unavailable"


def test_local_skill_executor_does_not_fallback_to_another_profile() -> None:
    executor = P6LocalSkillExecutor(
        dependencies=_dependencies(_router(NSL_V01_IN_PROCESS_BACKEND)),
        handler=lambda _context, _dependencies: P5ExecutorOutcome(
            state="SUCCEEDED",
            result_contract_ref="contract://nex/p6/step-result/v1.2",
            result_payload={},
        ),
    )

    with pytest.raises(P5StepExecutorError) as caught:
        executor.execute(_context(NSL_V01_PROCESS_ISOLATED_BACKEND))

    assert caught.value.error_code == "ae.local_skill_dependency_unavailable"
