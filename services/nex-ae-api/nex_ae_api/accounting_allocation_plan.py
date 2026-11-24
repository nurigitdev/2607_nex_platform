from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from mybee_ax.integrations import M1_ALLOCATION_CAPABILITY_ID
from nex_runtime.semantic_hashes import canonical_json, semantic_sha256_hash_ref
from sqlalchemy.orm import Session, sessionmaker

from nex_ae_api.accounting_allocation_authority import (
    AccountingAllocationAuthorityError,
    validate_accounting_allocation_work_intent,
)
from nex_ae_api.executable_plans import compile_executable_plan
from nex_ae_api.plan_validation import validate_agent_plan
from nex_ae_api.planning_capabilities import (
    CapabilitySnapshotError,
    capability_by_exact_version,
    validate_capability_snapshot_contract,
)
from nex_ae_api.work_intent import WorkIntentError, validate_work_intent

ACCOUNTING_ALLOCATION_PLAN_SCHEMA = "ae.accounting_allocation_plan.v1"


@dataclass(frozen=True)
class AccountingAllocationPlanError(ValueError):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class AccountingAllocationMaterializedPlan:
    agent_plan: Mapping[str, Any]
    validation_result: Mapping[str, Any]
    executable_plan: Mapping[str, Any]


class InstalledAccountingAllocationPlanActivation:
    """Materialize and schedule one independently authorized allocation intent."""

    def __init__(self, *, materializer: Any, activation: Any) -> None:
        if not callable(
            getattr(materializer, "materialize_accounting_allocation_plan", None)
        ) or not callable(getattr(activation, "activate", None)):
            raise _invalid("Accounting allocation activation dependencies are invalid.")
        self._materializer = materializer
        self._activation = activation

    def activate(
        self,
        *,
        work_intent: Mapping[str, Any],
        allocation_work_intent: Mapping[str, Any],
        agent_context: Mapping[str, Any],
        capability_snapshot: Mapping[str, Any],
    ) -> dict[str, Any]:
        allocation = validate_accounting_allocation_work_intent(allocation_work_intent)
        materialized = self._materializer.materialize_accounting_allocation_plan(
            work_intent=work_intent,
            allocation_work_intent=allocation,
            agent_context=agent_context,
            capability_snapshot=capability_snapshot,
        )
        return self._activation.activate(
            tenant_id=allocation["tenant_id"],
            execution_id=allocation["execution_id"],
            activation_ref=f"accounting-allocation:{allocation['intent_hash']}",
            materialized=materialized,
        )


def build_installed_accounting_allocation_plan_activation(
    sessions: sessionmaker[Session], *, materializer: Any
) -> InstalledAccountingAllocationPlanActivation:
    from nex_ae_api.agent_execution import SqlAlchemyAgentExecutionRepository
    from nex_ae_api.agent_plans import SqlAlchemyAgentPlanRepository
    from nex_ae_api.executable_plans import SqlAlchemyExecutablePlanRepository
    from nex_ae_api.multi_step_engine import SqlAlchemyMultiStepEngine
    from nex_ae_api.plan_validation import SqlAlchemyPlanValidationRepository
    from nex_ae_api.product_plan_activation import InstalledProductPlanActivation
    from nex_ae_api.runtime_jobs import SqlAlchemyRuntimeJobQueue

    jobs = SqlAlchemyRuntimeJobQueue(sessions)
    activation = InstalledProductPlanActivation(
        agent_plans=SqlAlchemyAgentPlanRepository(sessions),
        validations=SqlAlchemyPlanValidationRepository(sessions),
        executable_plans=SqlAlchemyExecutablePlanRepository(sessions),
        executions=SqlAlchemyAgentExecutionRepository(sessions),
        scheduler=SqlAlchemyMultiStepEngine(sessions, jobs),
    )
    return InstalledAccountingAllocationPlanActivation(
        materializer=materializer,
        activation=activation,
    )


def build_accounting_allocation_runtime_work_intent(
    allocation_work_intent: Mapping[str, Any],
) -> dict[str, Any]:
    """Project the typed allocation authority into the common AE WorkIntent SoR."""

    try:
        allocation = validate_accounting_allocation_work_intent(allocation_work_intent)
    except AccountingAllocationAuthorityError as exc:
        raise _invalid("Accounting allocation WorkIntent is invalid.") from exc
    result: dict[str, Any] = {
        "schema_version": "1.1",
        "work_intent_id": allocation["work_intent_id"],
        "intent_revision": 1,
        "supersedes_work_intent_id": None,
        "execution_id": allocation["execution_id"],
        "source": {
            "source_type": "PROMPT",
            "source_ref": allocation["source_ref"],
            "actor_ref": allocation["subject_id"],
            "received_at": allocation["requested_at"],
        },
        "execution_mode": "INTERACTIVE",
        "compatibility_execution_mode": "GENERAL_ANSWER",
        "project_ref": None,
        "intent_label": M1_ALLOCATION_CAPABILITY_ID,
        "goal": "Allocate an authorized posted accounting source to Projects.",
        "work_class": "BUSINESS_TRANSACTION",
        "required_capability_hints": [M1_ALLOCATION_CAPABILITY_ID],
        "entity_selectors": [],
        "parameter_candidates": [],
        "constraints": [
            {
                "constraint_type": "INDEPENDENT_ACCOUNTING_AUTHORITY",
                "description": (
                    "Resolve current OA and EOS authority before allocation."
                ),
            }
        ],
        "completion_criteria": [
            {
                "criterion_id": "C1",
                "description": "Allocation and P&L refresh are published.",
                "required": True,
                "result_contract_ref": (
                    "contract://nex/mybee/finance/accounting-allocation-result/v1"
                ),
            }
        ],
        "clarification": {
            "status": "NOT_REQUIRED",
            "reasons": [],
            "questions": [],
        },
        "confidence": {
            "overall": 1.0,
            "intent": 1.0,
            "entities": 1.0,
            "parameters": 1.0,
        },
        "provenance": {
            "resolver_type": "DETERMINISTIC_POLICY",
            "intent_decision_schema_version": (
                "ae.accounting_allocation_work_intent.v1"
            ),
            "intent_decision_hash": allocation["intent_hash"].removeprefix("sha256:"),
            "input_context_hash": allocation["intent_hash"],
            "prompt_binding_key": None,
            "prompt_template_version_id": None,
            "prompt_content_sha256": None,
            "rendered_prompt_hash": None,
            "model_profile": None,
            "model_ref": None,
        },
    }
    result["intent_hash"] = semantic_sha256_hash_ref(result)
    try:
        return validate_work_intent(result)
    except WorkIntentError as exc:
        raise _invalid("Accounting allocation runtime WorkIntent is invalid.") from exc


def materialize_accounting_allocation_plan(
    *,
    work_intent: Mapping[str, Any],
    allocation_work_intent: Mapping[str, Any],
    agent_context: Mapping[str, Any],
    capability_snapshot: Mapping[str, Any],
    installed_capability: Mapping[str, Any],
) -> AccountingAllocationMaterializedPlan:
    try:
        persisted_intent = validate_work_intent(work_intent)
        allocation_intent = validate_accounting_allocation_work_intent(
            allocation_work_intent
        )
        snapshot = validate_capability_snapshot_contract(capability_snapshot)
    except (
        WorkIntentError,
        AccountingAllocationAuthorityError,
        CapabilitySnapshotError,
        ValueError,
    ) as exc:
        raise _invalid("Allocation planning input is invalid.") from exc
    capability = _capability(snapshot, installed_capability)
    _require_lineage(
        work_intent=persisted_intent,
        allocation_intent=allocation_intent,
        agent_context=agent_context,
    )
    identities = {
        name: str(
            uuid5(
                NAMESPACE_URL,
                "https://nex-platform.local/ae/accounting-allocation/"
                f"{allocation_intent['execution_id']}/"
                f"{allocation_intent['intent_hash']}/{name}",
            )
        )
        for name in (
            "agent-plan",
            "validation-result",
            "executable-plan",
            "allocation-step",
        )
    }
    plan = _agent_plan(
        work_intent=persisted_intent,
        allocation_intent=allocation_intent,
        agent_context=agent_context,
        capability_snapshot=snapshot,
        capability=capability,
        agent_plan_id=identities["agent-plan"],
    )
    validation = validate_agent_plan(
        agent_plan=plan,
        work_intent=persisted_intent,
        agent_context=agent_context,
        capability_snapshot=snapshot,
        validation_result_id=identities["validation-result"],
        validated_at=allocation_intent["requested_at"],
    )
    if validation["status"] != "VALID" or validation["issues"]:
        raise _invalid("Allocation AgentPlan did not receive compile authority.")
    executable = compile_executable_plan(
        agent_plan=plan,
        validation_result=validation,
        agent_context=agent_context,
        capability_snapshot=snapshot,
        executable_plan_id=identities["executable-plan"],
        compiled_at=allocation_intent["requested_at"],
        id_factory=lambda: identities["allocation-step"],
    )
    return AccountingAllocationMaterializedPlan(plan, validation, executable)


def _agent_plan(
    *,
    work_intent: Mapping[str, Any],
    allocation_intent: Mapping[str, Any],
    agent_context: Mapping[str, Any],
    capability_snapshot: Mapping[str, Any],
    capability: Mapping[str, Any],
    agent_plan_id: str,
) -> dict[str, Any]:
    step = {
        "step_id": "S1",
        "step_type": "LOCAL_CAPABILITY",
        "title": "Run the authorized accounting allocation",
        "objective": "Execute the exact signed allocation capability.",
        "depends_on": [],
        "required_capability": M1_ALLOCATION_CAPABILITY_ID,
        "capability_version_constraint": capability["capability_version"],
        "input_bindings": [
            {
                "target_name": "allocation_work_intent_json",
                "source_type": "LITERAL",
                "literal_value": canonical_json(dict(allocation_intent)),
            }
        ],
        "output_contract_ref": capability["output_contract_ref"],
        "completion_criteria": [
            "Allocation, P&L refresh, and result publication reach a terminal state."
        ],
        "aggregation": None,
        "report": None,
    }
    plan: dict[str, Any] = {
        "schema_version": "1.1",
        "agent_plan_id": agent_plan_id,
        "agent_plan_version": 1,
        "execution_id": allocation_intent["execution_id"],
        "work_intent_ref": _versioned_ref(
            work_intent, "work_intent_id", "intent_revision", "intent_hash"
        ),
        "agent_context_ref": _versioned_ref(
            agent_context, "context_id", "context_generation", "context_hash"
        ),
        "capability_snapshot_ref": _versioned_ref(
            capability_snapshot,
            "capability_snapshot_id",
            "snapshot_version",
            "snapshot_hash",
        ),
        "plan_kind": "KNOWN_TEMPLATE",
        "goal": str(work_intent["goal"]),
        "completion_criteria": [
            {
                "criterion_id": "C1",
                "description": "The independently authorized allocation is published.",
                "required": True,
                "required_terminal_step_refs": ["S1"],
            }
        ],
        "planning_constraints": {
            "max_plan_steps": 12,
            "max_delegation_depth": 0,
            "max_parallel_steps": 1,
        },
        "steps": [step],
        "planner_provenance": {
            "builder_type": "CERTIFIED_BINDER",
            "route_decision_ref": (
                "plan-profile://ae/accounting-allocation-authoritative/v1"
            ),
            "template_ref": "plan-template://ae/accounting-allocation/v1",
            "input_context_hash": agent_context["context_hash"],
            "prompt_binding_key": None,
            "prompt_template_version_id": None,
            "prompt_content_sha256": None,
            "rendered_prompt_hash": None,
            "model_profile": None,
            "model_ref": None,
        },
    }
    plan["plan_hash"] = semantic_sha256_hash_ref(plan)
    return plan


def _capability(
    snapshot: Mapping[str, Any], installed: Mapping[str, Any]
) -> Mapping[str, Any]:
    if installed.get("capability_id") != M1_ALLOCATION_CAPABILITY_ID:
        raise _invalid("Installed allocation capability identity differs.")
    try:
        observed = capability_by_exact_version(
            snapshot,
            M1_ALLOCATION_CAPABILITY_ID,
            str(installed.get("capability_version") or ""),
        )
    except CapabilitySnapshotError as exc:
        raise _invalid("Allocation capability snapshot is unavailable.") from exc
    if observed != dict(installed):
        raise _invalid("Allocation capability snapshot differs from the release.")
    return observed


def _require_lineage(
    *,
    work_intent: Mapping[str, Any],
    allocation_intent: Mapping[str, Any],
    agent_context: Mapping[str, Any],
) -> None:
    identity = agent_context.get("identity")
    hints = work_intent.get("required_capability_hints")
    if (
        work_intent.get("work_intent_id") != allocation_intent["work_intent_id"]
        or work_intent.get("execution_id") != allocation_intent["execution_id"]
        or not isinstance(identity, Mapping)
        or agent_context.get("execution_id") != allocation_intent["execution_id"]
        or identity.get("tenant_id") != allocation_intent["tenant_id"]
        or identity.get("principal_id") != allocation_intent["subject_id"]
        or not isinstance(hints, list)
        or M1_ALLOCATION_CAPABILITY_ID not in hints
    ):
        raise _invalid("Allocation planning lineage differs.")


def _versioned_ref(
    value: Mapping[str, Any], id_field: str, version_field: str, hash_field: str
) -> dict[str, Any]:
    return {
        "id": value[id_field],
        "version": value[version_field],
        "hash": value[hash_field],
    }


def _invalid(detail: str) -> AccountingAllocationPlanError:
    return AccountingAllocationPlanError("ACCOUNTING_ALLOCATION_PLAN_INVALID", detail)
