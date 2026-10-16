from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from nex_ae_api.agent_runtime_worker import AgentRuntimeAssignment
from nex_ae_api.multi_step_engine import StepExecutionContext
from nex_ae_api.nsl_backend_profiles import normalize_nsl_backend_profile
from nex_ae_api.nsl_read_backends import NSLReadBackendError, NSLReadExecutionService
from nex_ae_api.nsl_result_integration import (
    NSLResultIntegrationError,
    NSLResultIntegrationService,
)
from nex_ae_api.nsl_step_executions import NSLStepExecutionError
from nex_ae_api.planning_capabilities import (
    LOCAL_SKILL_EXECUTOR_KIND,
    CapabilitySnapshotError,
    validate_local_skill_binding,
)
from nex_ae_api.skill_artifacts import SkillArtifactGatewayError
from nex_ae_api.step_executors import (
    LocalSkillExecutorDependencies,
    P5ExecutorOutcome,
    P5StepExecutionWorker,
    P5StepExecutorError,
)


@dataclass(frozen=True)
class LocalSkillInvocation:
    context_projection: Mapping[str, Any]
    compiled_inputs: Mapping[str, Any]
    input_provenance: Mapping[str, str]
    observed_at: str
    environment: str = "production"


class P6LocalSkillReadHandler:
    """Compose the verified artifact, durable request, backend, and result path."""

    def __init__(
        self,
        *,
        read_execution: NSLReadExecutionService,
        result_integration: NSLResultIntegrationService,
    ) -> None:
        if not callable(getattr(read_execution, "execute_bound", None)):
            raise _unavailable("LOCAL_SKILL READ execution service is unavailable.")
        if not callable(getattr(result_integration, "finalize_bound", None)):
            raise _unavailable("LOCAL_SKILL result integration is unavailable.")
        self._read_execution = read_execution
        self._result_integration = result_integration

    def __call__(
        self,
        context: StepExecutionContext,
        dependencies: LocalSkillExecutorDependencies,
    ) -> P5ExecutorOutcome:
        try:
            tenant_id = _required_text("tenant_id", context.job.get("tenant_id"), 128)
            step_id = _required_text(
                "executable_step_id",
                context.step.get("executable_step_id"),
                64,
            )
            attempt_no = _positive_int("attempt_no", context.attempt.get("attempt_no"))
            binding = validate_local_skill_binding(context.step.get("skill_binding"))
            invocation = dependencies.request_builder(context=context)
            if not isinstance(invocation, LocalSkillInvocation):
                raise _invalid(
                    "LOCAL_SKILL request builder must return LocalSkillInvocation."
                )
            artifact = dependencies.artifact_gateway.resolve_verified(
                tenant_id=tenant_id,
                skill_id=binding["skill_id"],
                exact_version=binding["exact_skill_version"],
                expected_semantic_hash=binding["skill_semantic_hash"],
                runtime_contract_ref=binding["runtime_contract_ref"],
                trust_policy_id=binding["trust_policy_id"],
                environment=invocation.environment,
                observed_at=invocation.observed_at,
            )
            dependencies.binding_repository.bind_request(
                tenant_id=tenant_id,
                executable_step_id=step_id,
                verified_artifact_ref=artifact["artifact_ref"],
                context_projection=invocation.context_projection,
                compiled_inputs=invocation.compiled_inputs,
                input_provenance=invocation.input_provenance,
                now=invocation.observed_at,
            )
            backend_run = self._read_execution.execute_bound(
                tenant_id=tenant_id,
                executable_step_id=step_id,
                attempt_no=attempt_no,
            )
            integration = self._result_integration.finalize_bound(
                tenant_id=tenant_id,
                executable_step_id=step_id,
                attempt_no=_positive_int(
                    "backend attempt_no", backend_run.get("attempt_no")
                ),
            )
            outcome = dependencies.result_mapper(integration.outcome)
            if not isinstance(outcome, P5ExecutorOutcome):
                raise _invalid("LOCAL_SKILL result mapper returned an invalid outcome.")
            return outcome
        except P5StepExecutorError:
            raise
        except (
            CapabilitySnapshotError,
            NSLReadBackendError,
            NSLResultIntegrationError,
            NSLStepExecutionError,
            SkillArtifactGatewayError,
        ) as exc:
            raise P5StepExecutorError(
                exc.error_code,
                exc.detail,
                exc.retryable,
            ) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise _invalid("LOCAL_SKILL READ composition is invalid.") from exc


class AgentRuntimeStepAssignmentHandler:
    """Consume one dispatcher assignment through the canonical step worker."""

    def __init__(self, worker: P5StepExecutionWorker) -> None:
        if not callable(getattr(worker, "run_claim", None)):
            raise _unavailable("Agent Runtime step worker is unavailable.")
        self._worker = worker

    def __call__(self, assignment: AgentRuntimeAssignment) -> Mapping[str, Any]:
        if not isinstance(assignment, AgentRuntimeAssignment):
            raise _invalid("Agent Runtime assignment is invalid.")
        if assignment.executor_kind != LOCAL_SKILL_EXECUTOR_KIND:
            raise _invalid("Agent Runtime assignment executor is unsupported.")
        try:
            normalize_nsl_backend_profile(assignment.backend_profile)
        except ValueError as exc:
            raise _invalid(
                "Agent Runtime assignment backend profile is unsupported."
            ) from exc
        execution = self._worker.run_claim(
            tenant_id=assignment.tenant_id,
            claim=assignment.claim,
        )
        step_result = execution.step_result or {}
        step = execution.step or {}
        return {
            "schema_version": "p6_ia_read_assignment.v1",
            "runtime_job_id": assignment.runtime_job_id,
            "executable_step_id": step.get("executable_step_id"),
            "disposition": execution.disposition,
            "runtime_job_state": execution.runtime_job.get("state"),
            "step_result_id": step_result.get("step_result_id"),
            "step_result_status": step_result.get("status"),
            "content_included": False,
        }


def _required_text(field: str, value: object, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise _invalid(f"{field} is invalid.")
    return value.strip()


def _positive_int(field: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _invalid(f"{field} is invalid.")
    return value


def _invalid(detail: str) -> P5StepExecutorError:
    return P5StepExecutorError("ae.p6_ia_read_invalid", detail)


def _unavailable(detail: str) -> P5StepExecutorError:
    return P5StepExecutorError("ae.p6_ia_read_unavailable", detail, True)
