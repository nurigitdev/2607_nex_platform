from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from nex_ae_api.agent_context import (
    TrustedContextResolution,
    build_agent_context,
    runtime_policy_ref_from_compatibility_policy,
)
from nex_ae_api.executable_plans import compile_executable_plan
from nex_ae_api.golden_a_planning import (
    GOLDEN_A_CAPABILITY_ID,
    GOLDEN_A_NSL_SKILL_ID,
    activate_golden_a_work_intent,
    bind_golden_a_planning_candidate,
    build_golden_a_capability_snapshot,
)
from nex_ae_api.intent_candidate_generation import LiveIntentCandidateService
from nex_ae_api.plan_candidate_generation import LivePlanCandidateService
from nex_ae_api.plan_validation import validate_agent_plan
from nex_ae_api.runtime_policy import resolve_runtime_policy


@dataclass(frozen=True)
class GoldenAApprovalJourneyError(RuntimeError):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class GoldenAPlanningJourneyResult:
    intent_stage: Any = field(repr=False)
    activation: Mapping[str, Any] = field(repr=False)
    work_intent: Mapping[str, Any] = field(repr=False)
    agent_context: Mapping[str, Any] = field(repr=False)
    capability_snapshot: Mapping[str, Any] = field(repr=False)
    plan_stage: Any = field(repr=False)
    validation: Mapping[str, Any] = field(repr=False)
    executable_plan: Mapping[str, Any] = field(repr=False)


@dataclass(frozen=True)
class GoldenAPlanningJourneyService:
    intent_service: LiveIntentCandidateService = field(repr=False)
    plan_service: LivePlanCandidateService = field(repr=False)

    def plan(
        self,
        *,
        fixture: Mapping[str, Any],
        user_prompt: str,
        tenant_id: str,
        principal_id: str,
        agent_id: str,
        execution_id: str,
        workspace_id: str,
        conversation_id: str,
        interaction_id: str,
        received_at: str,
        request_id: str,
        trace_id: str,
        authority_ref: str,
        snapshot_version: int = 1,
    ) -> GoldenAPlanningJourneyResult:
        fixture_tenant = _fixture_tenant(fixture)
        if tenant_id != fixture_tenant:
            raise _invalid(
                "P8_GOLDEN_A_TENANT_MISMATCH",
                "Golden A planning tenant does not match its protected fixture.",
            )

        intent_stage = self.intent_service.generate_and_resolve(
            user_prompt=user_prompt,
            execution_id=execution_id,
            source_ref=f"AE:INTERACTION:{interaction_id}",
            actor_ref=f"OA:SUBJECT:{principal_id}",
            received_at=received_at,
            request_id=request_id,
            trace_id=trace_id,
            planning_mode="required",
            trusted_execution_mode="GENERAL_ANSWER",
            retrieval_enabled=False,
            authorized_resource_context_available=True,
        )
        if intent_stage.directive != "CONTINUE" or intent_stage.work_intent is None:
            raise _invalid(
                intent_stage.failure_code or "P8_GOLDEN_A_INTENT_NOT_ADMITTED",
                "Live Golden A intent candidate did not pass required admission.",
            )

        activation = bind_golden_a_planning_candidate(
            fixture=fixture,
            candidate=intent_stage.candidate,
        )
        if activation["directive"] != "CONTINUE":
            raise _invalid(
                str(
                    activation.get("failure_code")
                    or "P8_GOLDEN_A_CLARIFICATION_REQUIRED"
                ),
                "Golden A deterministic business binding requires clarification.",
            )
        work_intent = activate_golden_a_work_intent(
            intent_stage.work_intent,
            candidate=intent_stage.candidate,
            activation=activation,
        )
        resolver = _GoldenAContextResolver(
            activation=activation,
            authority_ref=authority_ref,
            resolved_at=received_at,
        )
        agent_context = build_agent_context(
            tenant_id=tenant_id,
            principal_id=principal_id,
            agent_id=agent_id,
            execution_id=execution_id,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            interaction_id=interaction_id,
            work_intent=work_intent,
            runtime_policy_ref=runtime_policy_ref_from_compatibility_policy(
                resolve_runtime_policy(
                    {
                        "user_message": user_prompt,
                        "generation": {"execution_mode": "GENERAL_ANSWER"},
                    }
                )
            ),
            resolver=resolver,
            built_at=received_at,
        )
        snapshot = build_golden_a_capability_snapshot(
            fixture,
            capability_snapshot_id=_new_uuid(),
            snapshot_version=snapshot_version,
            created_at=received_at,
        )
        plan_stage = self.plan_service.generate_and_bind(
            work_intent=work_intent,
            agent_context=agent_context,
            capability_snapshot=snapshot,
            request_id=request_id,
            trace_id=trace_id,
            planning_mode="required",
            agent_plan_id=_new_uuid(),
        )
        if plan_stage.directive != "CONTINUE" or plan_stage.agent_plan is None:
            raise _invalid(
                plan_stage.failure_code or "P8_GOLDEN_A_PLAN_NOT_ADMITTED",
                "Live Golden A plan candidate did not pass required admission.",
            )
        validation = validate_agent_plan(
            agent_plan=plan_stage.agent_plan,
            work_intent=work_intent,
            agent_context=agent_context,
            capability_snapshot=snapshot,
            validated_at=received_at,
        )
        if validation["status"] != "VALID":
            raise _invalid(
                "P8_GOLDEN_A_PLAN_INVALID",
                "Golden A deterministic PlanValidation rejected the live plan.",
            )
        executable_plan = compile_executable_plan(
            agent_plan=plan_stage.agent_plan,
            validation_result=validation,
            agent_context=agent_context,
            capability_snapshot=snapshot,
            compiled_at=received_at,
        )
        _require_exact_local_skill(executable_plan, activation)
        return GoldenAPlanningJourneyResult(
            intent_stage=intent_stage,
            activation=activation,
            work_intent=work_intent,
            agent_context=agent_context,
            capability_snapshot=snapshot,
            plan_stage=plan_stage,
            validation=validation,
            executable_plan=executable_plan,
        )


@dataclass(frozen=True)
class _GoldenAContextResolver:
    activation: Mapping[str, Any] = field(repr=False)
    authority_ref: str
    resolved_at: str

    def resolve(self, _request: Any) -> TrustedContextResolution:
        binding = self.activation["authoritative_binding"]
        project_ref = dict(binding["project_ref"])
        return TrustedContextResolution(
            # IA remains project-neutral. The resolved entity scopes only this
            # interaction and does not turn the IA itself into a Project Agent.
            project_ref=None,
            authority_ref=self.authority_ref,
            resolved_entities=(
                {
                    "selector_id": "E1",
                    "resource_ref": project_ref,
                    "source_ref": (
                        "golden-a-project:" + str(project_ref["resource_id"])
                    ),
                    "resolved_at": self.resolved_at,
                },
            ),
            retrieval_refs=(),
            evidence_refs=(),
            conflicts=(),
            degradations=(),
            context_manifest=(
                {
                    "kind": "GOLDEN_A_FIXTURE",
                    "source_ref": (
                        "golden-a-fixture:"
                        + str(self.activation["fixture_ref"]["fixture_id"])
                    ),
                    "source_version": "1",
                    "content_hash": self.activation["fixture_ref"]["fixture_hash"],
                    "as_of": self.resolved_at,
                },
            ),
            budget_tokens=2048,
            estimated_used_tokens=256,
        )


def _require_exact_local_skill(
    executable_plan: Mapping[str, Any], activation: Mapping[str, Any]
) -> None:
    local_steps = [
        step
        for step in executable_plan["steps"]
        if step["executor_kind"] == "LOCAL_SKILL"
    ]
    if len(local_steps) != 1:
        raise _invalid(
            "P8_GOLDEN_A_LOCAL_SKILL_CARDINALITY",
            "Golden A requires exactly one LOCAL_SKILL execution step.",
        )
    step = local_steps[0]
    binding = step["skill_binding"]
    authoritative = activation["authoritative_binding"]["capability_ref"]
    if (
        step["required_capability"] != GOLDEN_A_CAPABILITY_ID
        or binding["skill_id"] != GOLDEN_A_NSL_SKILL_ID
        or binding.get("capability_id") != GOLDEN_A_CAPABILITY_ID
        or binding["exact_skill_version"] != authoritative["skill_version"]
        or binding["skill_semantic_hash"] != authoritative["skill_semantic_hash"]
        or authoritative["tool_id"] != GOLDEN_A_CAPABILITY_ID
    ):
        raise _invalid(
            "P8_GOLDEN_A_SKILL_BINDING_MISMATCH",
            "Golden A executable capability does not match the admitted NSL Skill.",
        )


def _fixture_tenant(fixture: Mapping[str, Any]) -> str:
    try:
        tenant_id = fixture["tenant"]["tenant_id"]
    except (KeyError, TypeError) as exc:
        raise _invalid(
            "P8_GOLDEN_A_FIXTURE_INVALID",
            "Golden A fixture tenant is unavailable.",
        ) from exc
    if not isinstance(tenant_id, str) or not tenant_id:
        raise _invalid(
            "P8_GOLDEN_A_FIXTURE_INVALID",
            "Golden A fixture tenant is invalid.",
        )
    return tenant_id


def _new_uuid() -> str:
    from uuid import uuid4

    return str(uuid4())


def _invalid(code: str, detail: str) -> GoldenAApprovalJourneyError:
    return GoldenAApprovalJourneyError(code, detail)
