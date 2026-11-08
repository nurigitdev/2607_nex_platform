from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from nex_ae_api.agent_runtime_worker import AgentRuntimeAssignment
from nex_ae_api.multi_step_engine import StepExecutionContext
from nex_ae_api.p6_ia_read_runtime import (
    AgentRuntimeStepAssignmentHandler,
    LocalSkillInvocation,
    P6LocalSkillReadHandler,
)
from nex_ae_api.runtime_jobs import RuntimeJobClaim
from nex_ae_api.step_executors import (
    LocalSkillExecutorDependencies,
    P5ExecutorOutcome,
    P5StepExecutorError,
    P5WorkerExecution,
)

TENANT = "tenant-p6-s7"
STEP_ID = "33333333-3333-4333-8333-333333333333"
JOB_ID = "44444444-4444-4444-8444-444444444444"
NOW = "2026-10-15T09:00:00Z"


class _Gateway:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.error = error

    def resolve_verified(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return {"artifact_ref": "AE:NSL_ARTIFACT:p6-s7"}


class _Bindings:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def bind_request(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"binding": {"state": "REQUEST_BOUND"}}


class _Backend:
    backend_profile = "NSL_V01_PROCESS_ISOLATED"

    def execute(self, **_kwargs: Any) -> dict[str, Any]:
        return {}


class _ReadExecution:
    def __init__(self, attempt_no: int = 1) -> None:
        self.attempt_no = attempt_no
        self.calls: list[dict[str, Any]] = []

    def execute_bound(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"attempt_no": self.attempt_no}


class _ResultIntegration:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def finalize_bound(self, **kwargs: Any) -> object:
        self.calls.append(kwargs)
        return SimpleNamespace(outcome={"state": "SUCCEEDED"})


def _binding() -> dict[str, str]:
    return {
        "skill_id": "FINANCE.PROJECT_BUDGET_CHECK",
        "exact_skill_version": "1.0.0",
        "skill_semantic_hash": "sha256:" + "1" * 64,
        "runtime_contract_ref": "contract://nex/nsl/read-runtime/v0.1",
        "trust_policy_id": "nsl.production.ed25519.v1",
        "backend_profile": "NSL_V01_PROCESS_ISOLATED",
        "package_requirement": "SIGNED_TRUSTED_ACTIVE",
    }


def _context(**overrides: Any) -> StepExecutionContext:
    values = {
        "job": {"tenant_id": TENANT, "runtime_job_id": JOB_ID},
        "attempt": {"attempt_no": 1},
        "step": {
            "executable_step_id": STEP_ID,
            "executor_kind": "LOCAL_SKILL",
            "skill_binding": _binding(),
        },
        "dependency_results": (),
        "existing_result": None,
    }
    values.update(overrides)
    return StepExecutionContext(**values)


def _invocation() -> LocalSkillInvocation:
    return LocalSkillInvocation(
        context_projection={"projection_hash": "sha256:" + "2" * 64},
        compiled_inputs={"year": 2026},
        input_provenance={"year": "USER"},
        observed_at=NOW,
    )


def _dependencies(**overrides: Any) -> LocalSkillExecutorDependencies:
    values = {
        "artifact_gateway": _Gateway(),
        "binding_repository": _Bindings(),
        "request_builder": lambda **_kwargs: _invocation(),
        "backend": _Backend(),
        "result_mapper": lambda _outcome: P5ExecutorOutcome(
            state="SUCCEEDED",
            result_contract_ref="contract://nex/p6/step-result/v1.2",
            result_payload={"nsl_result_summary_ref": "AE:NSL_RESULT_SUMMARY:p6-s7"},
        ),
    }
    values.update(overrides)
    return LocalSkillExecutorDependencies(**values)


def test_local_skill_read_handler_composes_exact_durable_path() -> None:
    read = _ReadExecution(attempt_no=3)
    results = _ResultIntegration()
    dependencies = _dependencies()
    handler = P6LocalSkillReadHandler(
        read_execution=read,  # type: ignore[arg-type]
        result_integration=results,  # type: ignore[arg-type]
    )

    outcome = handler(_context(attempt={"attempt_no": 3}), dependencies)

    assert outcome.state == "SUCCEEDED"
    assert dependencies.artifact_gateway.calls[0] == {
        "tenant_id": TENANT,
        "skill_id": "FINANCE.PROJECT_BUDGET_CHECK",
        "exact_version": "1.0.0",
        "expected_semantic_hash": "sha256:" + "1" * 64,
        "runtime_contract_ref": "contract://nex/nsl/read-runtime/v0.1",
        "trust_policy_id": "nsl.production.ed25519.v1",
        "environment": "production",
        "observed_at": NOW,
    }
    assert dependencies.binding_repository.calls[0]["compiled_inputs"] == {
        "year": 2026
    }
    assert read.calls == [
        {
            "tenant_id": TENANT,
            "executable_step_id": STEP_ID,
            "attempt_no": 3,
            "expected_backend_profile": "NSL_V01_PROCESS_ISOLATED",
        }
    ]
    assert results.calls[0]["attempt_no"] == 3


@pytest.mark.parametrize(
    "mutation",
    (
        lambda context, dependencies: (context, _dependencies(request_builder=lambda **_kwargs: {})),
        lambda context, dependencies: (_context(job={}), dependencies),
        lambda context, dependencies: (_context(attempt={"attempt_no": 0}), dependencies),
        lambda context, dependencies: (
            context,
            _dependencies(result_mapper=lambda _outcome: None),
        ),
    ),
)
def test_local_skill_read_handler_rejects_invalid_composition(mutation) -> None:
    context, dependencies = mutation(_context(), _dependencies())
    handler = P6LocalSkillReadHandler(
        read_execution=_ReadExecution(),  # type: ignore[arg-type]
        result_integration=_ResultIntegration(),  # type: ignore[arg-type]
    )

    with pytest.raises(P5StepExecutorError) as caught:
        handler(context, dependencies)

    assert caught.value.error_code == "ae.p6_ia_read_invalid"


def test_local_skill_read_handler_preserves_bounded_domain_failure() -> None:
    from nex_ae_api.skill_artifacts import SkillArtifactGatewayError

    error = SkillArtifactGatewayError("ae.skill.rejected", "Skill rejected.")
    handler = P6LocalSkillReadHandler(
        read_execution=_ReadExecution(),  # type: ignore[arg-type]
        result_integration=_ResultIntegration(),  # type: ignore[arg-type]
    )

    with pytest.raises(P5StepExecutorError) as caught:
        handler(_context(), _dependencies(artifact_gateway=_Gateway(error=error)))

    assert caught.value.error_code == "ae.skill.rejected"
    assert caught.value.detail == "Skill rejected."


def test_local_skill_read_handler_rejects_malformed_adapter_result() -> None:
    gateway = _Gateway()
    gateway.resolve_verified = lambda **_kwargs: {}  # type: ignore[method-assign]
    handler = P6LocalSkillReadHandler(
        read_execution=_ReadExecution(),  # type: ignore[arg-type]
        result_integration=_ResultIntegration(),  # type: ignore[arg-type]
    )

    with pytest.raises(P5StepExecutorError) as caught:
        handler(_context(), _dependencies(artifact_gateway=gateway))

    assert caught.value.error_code == "ae.p6_ia_read_invalid"


def test_local_skill_read_handler_requires_runtime_services() -> None:
    with pytest.raises(P5StepExecutorError, match="execution service"):
        P6LocalSkillReadHandler(
            read_execution=object(),  # type: ignore[arg-type]
            result_integration=_ResultIntegration(),  # type: ignore[arg-type]
        )
    with pytest.raises(P5StepExecutorError, match="result integration"):
        P6LocalSkillReadHandler(
            read_execution=_ReadExecution(),  # type: ignore[arg-type]
            result_integration=object(),  # type: ignore[arg-type]
        )


class _StepWorker:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def run_claim(self, **kwargs: Any) -> P5WorkerExecution:
        self.calls.append(kwargs)
        return P5WorkerExecution(
            disposition="TERMINAL",
            step={"executable_step_id": STEP_ID},
            step_result={"step_result_id": "result-p6-s7", "status": "SUCCEEDED"},
            runtime_job={"state": "DONE"},
        )


def _assignment(**overrides: Any) -> AgentRuntimeAssignment:
    claim = RuntimeJobClaim(
        job={
            "runtime_job_id": JOB_ID,
            "lease_owner": "worker-p6-s7",
            "lease_token": "lease-p6-s7",
        },
        attempt={"attempt_no": 1},
        executor_kind="LOCAL_SKILL",
    )
    values = {
        "tenant_id": TENANT,
        "executor_kind": "LOCAL_SKILL",
        "backend_profile": "NSL_V01_PROCESS_ISOLATED",
        "claim": claim,
    }
    values.update(overrides)
    return AgentRuntimeAssignment(**values)


def test_assignment_handler_consumes_dispatch_claim_without_content() -> None:
    worker = _StepWorker()
    handler = AgentRuntimeStepAssignmentHandler(worker)  # type: ignore[arg-type]

    result = handler(_assignment())

    assert worker.calls[0]["tenant_id"] == TENANT
    assert result == {
        "schema_version": "p6_ia_read_assignment.v1",
        "runtime_job_id": JOB_ID,
        "executable_step_id": STEP_ID,
        "disposition": "TERMINAL",
        "runtime_job_state": "DONE",
        "step_result_id": "result-p6-s7",
        "step_result_status": "SUCCEEDED",
        "content_included": False,
    }


@pytest.mark.parametrize(
    "assignment",
    (
        object(),
        _assignment(executor_kind="DETERMINISTIC_REPORT"),
        _assignment(backend_profile="IN_PROCESS"),
    ),
)
def test_assignment_handler_rejects_runtime_boundary_drift(assignment: object) -> None:
    handler = AgentRuntimeStepAssignmentHandler(_StepWorker())  # type: ignore[arg-type]

    with pytest.raises(P5StepExecutorError) as caught:
        handler(assignment)  # type: ignore[arg-type]

    assert caught.value.error_code == "ae.p6_ia_read_invalid"


def test_assignment_handler_requires_step_worker() -> None:
    with pytest.raises(P5StepExecutorError, match="worker"):
        AgentRuntimeStepAssignmentHandler(object())  # type: ignore[arg-type]
