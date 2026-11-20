from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from mybee_ax.integrations import M1_D04_CAPABILITY_ID, M1_D12_CAPABILITY_ID
from nex_runtime.business_context import (
    BusinessContextValidationError,
    validate_business_request_context,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

from nex_ae_api.executable_plans import compile_executable_plan
from nex_ae_api.plan_validation import validate_agent_plan
from nex_ae_api.planning_capabilities import (
    CapabilitySnapshotError,
    capability_by_exact_version,
    validate_capability_snapshot_contract,
)
from nex_ae_api.product_planning_proposals import (
    validate_product_planning_proposal_reference,
)

M1_PLAN_MATERIALIZATION_SCHEMA_VERSION = "ae.m1_plan_materialization.v1"
M1_PLAN_MATERIALIZATION_ERROR_FAMILY = "M1_PLAN_MATERIALIZATION_INVALID"
M1_PREPARATION_SCHEMA_VERSION = "nex.mybee.m1-transaction-preparation.v1"
M1_D04_COMMAND_SCHEMA_VERSION = "eos.journal_posting_command.v1"
_CAPABILITY_IDS = (M1_D12_CAPABILITY_ID, M1_D04_CAPABILITY_ID)
_D04_REFERENCE_FIELDS = {
    "candidate_id",
    "candidate_version",
    "candidate_revision",
    "candidate_hash",
    "accounting_approval_evidence_id",
    "accounting_proof_hash",
    "posting_admission_id",
    "posting_admission_hash",
    "posting_admission_expires_at",
}
_M1_PREPARATION_INPUT = "m1_preparation_checkpoint"


@dataclass(frozen=True)
class M1PlanMaterializationError(ValueError):
    error_code: str
    detail: str
    error_family: str = M1_PLAN_MATERIALIZATION_ERROR_FAMILY

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class M1MaterializedPlan:
    agent_plan: Mapping[str, Any]
    validation_result: Mapping[str, Any]
    executable_plan: Mapping[str, Any]

    def projection(self) -> dict[str, Any]:
        value = {
            "schema_version": M1_PLAN_MATERIALIZATION_SCHEMA_VERSION,
            "agent_plan_id": self.agent_plan["agent_plan_id"],
            "agent_plan_hash": self.agent_plan["plan_hash"],
            "validation_result_id": self.validation_result["validation_result_id"],
            "validation_result_hash": self.validation_result["result_hash"],
            "executable_plan_id": self.executable_plan["executable_plan_id"],
            "executable_plan_hash": self.executable_plan["executable_plan_hash"],
            "compiled_step_keys": [
                item["compiled_step_key"] for item in self.executable_plan["steps"]
            ],
        }
        value["materialization_hash"] = semantic_sha256_hash_ref(value)
        return value


def materialize_m1_transaction_plan(
    *,
    work_intent: Mapping[str, Any],
    agent_context: Mapping[str, Any],
    capability_snapshot: Mapping[str, Any],
    preparation_checkpoint: Mapping[str, Any],
    installed_capabilities: Mapping[str, Mapping[str, Any]],
    product_planning_proposal_ref: Mapping[str, Any] | None = None,
) -> M1MaterializedPlan:
    context = _work_intent_context(work_intent)
    preparation = _preparation(preparation_checkpoint)
    authority = preparation["authority"]
    try:
        snapshot = validate_capability_snapshot_contract(capability_snapshot)
    except CapabilitySnapshotError as exc:
        raise _invalid("M1_PLAN_CAPABILITY_SNAPSHOT_INVALID", exc.detail) from exc
    capabilities = _capabilities(snapshot, installed_capabilities)
    proposal_ref = (
        None
        if product_planning_proposal_ref is None
        else validate_product_planning_proposal_reference(product_planning_proposal_ref)
    )
    _require_lineage(
        work_intent=work_intent,
        agent_context=agent_context,
        context=context,
        preparation=preparation,
    )

    execution_id = _uuid("execution_id", work_intent.get("execution_id"))
    prepared_at = _timestamp(authority.get("authority_effective_at"))
    identities = {
        name: str(
            uuid5(
                NAMESPACE_URL,
                "https://nex-platform.local/ae/m1-plan/"
                f"{execution_id}/{preparation['preparation_hash']}/{name}",
            )
        )
        for name in (
            "agent-plan",
            "validation-result",
            "executable-plan",
            "d12-step",
            "d04-step",
        )
    }
    plan = _agent_plan(
        work_intent=work_intent,
        agent_context=agent_context,
        capability_snapshot=snapshot,
        context=context,
        preparation=preparation,
        capabilities=capabilities,
        proposal_ref=proposal_ref,
        agent_plan_id=identities["agent-plan"],
    )
    validation = validate_agent_plan(
        agent_plan=plan,
        work_intent=work_intent,
        agent_context=agent_context,
        capability_snapshot=snapshot,
        validation_result_id=identities["validation-result"],
        validated_at=prepared_at,
    )
    if validation["status"] != "VALID" or validation["issues"]:
        raise _invalid(
            "M1_PLAN_VALIDATION_REJECTED",
            "M1 AgentPlan did not receive issue-free compile authority.",
        )
    step_ids = iter((identities["d12-step"], identities["d04-step"]))
    executable = compile_executable_plan(
        agent_plan=plan,
        validation_result=validation,
        agent_context=agent_context,
        capability_snapshot=snapshot,
        executable_plan_id=identities["executable-plan"],
        compiled_at=prepared_at,
        id_factory=lambda: next(step_ids),
    )
    return M1MaterializedPlan(plan, validation, executable)


def _agent_plan(
    *,
    work_intent: Mapping[str, Any],
    agent_context: Mapping[str, Any],
    capability_snapshot: Mapping[str, Any],
    context: Mapping[str, Any],
    preparation: Mapping[str, Any],
    capabilities: Mapping[str, Mapping[str, Any]],
    proposal_ref: Mapping[str, Any] | None,
    agent_plan_id: str,
) -> dict[str, Any]:
    authority = preparation["authority"]
    references = preparation["references"]
    transaction = context["transaction"]
    d12_inputs = {
        "tenant_id": authority["tenant_id"],
        "requester_subject_id": authority["requester_subject_id"],
        "project_id": authority["primary_project_id"],
        "effective_on": transaction["recognition_date"],
    }
    d04_inputs = {
        "schema_version": M1_D04_COMMAND_SCHEMA_VERSION,
        "tenant_id": authority["tenant_id"],
        "company_id": authority["company_id"],
        "candidate_id": references["candidate_id"],
        "expected_candidate_version": references["candidate_version"],
        "expected_candidate_revision": references["candidate_revision"],
        "expected_candidate_hash": references["candidate_hash"],
        "accounting_approval_evidence_id": references[
            "accounting_approval_evidence_id"
        ],
        # Durable runtime lineage only. The installed executor removes this
        # value before constructing the canonical NSL/EOS WRITE payload.
        _M1_PREPARATION_INPUT: preparation,
    }
    plan: dict[str, Any] = {
        "schema_version": "1.1",
        "agent_plan_id": agent_plan_id,
        "agent_plan_version": 1,
        "execution_id": work_intent["execution_id"],
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
                "description": "D12 authority is read before governed D04 posting.",
                "required": True,
                "required_terminal_step_refs": ["S2"],
            }
        ],
        "planning_constraints": {
            "max_plan_steps": 12,
            "max_delegation_depth": 0,
            "max_parallel_steps": 1,
        },
        "steps": [
            _step(
                step_id="S1",
                title="Read current Project WorkCode authority",
                objective="Execute the exact signed D12 Project context Skill.",
                depends_on=[],
                capability=capabilities[M1_D12_CAPABILITY_ID],
                inputs=d12_inputs,
            ),
            _step(
                step_id="S2",
                title="Post the approved accounting candidate",
                objective="Execute the exact signed D04 governed WRITE Skill.",
                depends_on=["S1"],
                capability=capabilities[M1_D04_CAPABILITY_ID],
                inputs=d04_inputs,
            ),
        ],
        "planner_provenance": {
            "builder_type": "CERTIFIED_BINDER",
            "route_decision_ref": (
                "plan-profile://ae/mybee-m1-authoritative/p5.1"
                if proposal_ref is None
                else f"product-planning-proposal://{proposal_ref['proposal_hash']}"
            ),
            "template_ref": "plan-template://ae/mybee-m1-d12-d04/v1",
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


def _step(
    *,
    step_id: str,
    title: str,
    objective: str,
    depends_on: list[str],
    capability: Mapping[str, Any],
    inputs: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "step_id": step_id,
        "step_type": "LOCAL_CAPABILITY",
        "title": title,
        "objective": objective,
        "depends_on": depends_on,
        "required_capability": capability["capability_id"],
        "capability_version_constraint": capability["capability_version"],
        "input_bindings": [
            {
                "target_name": name,
                "source_type": "LITERAL",
                "literal_value": value,
            }
            for name, value in inputs.items()
        ],
        "output_contract_ref": capability["output_contract_ref"],
        "completion_criteria": ["The exact signed Skill reaches a terminal state."],
        "aggregation": None,
        "report": None,
    }


def _work_intent_context(value: Mapping[str, Any]) -> Mapping[str, Any]:
    try:
        context = validate_business_request_context(
            value.get("business_request_context")
        )
    except BusinessContextValidationError as exc:
        raise _invalid("M1_PLAN_WORK_INTENT_INVALID", exc.detail) from exc
    if (
        value.get("schema_version") != "1.2"
        or value.get("intent_label") != "FINANCE.VOUCHER.APPROVE_AND_POST"
        or value.get("business_context_hash") != context["context_hash"]
        or value.get("intent_hash")
        != semantic_sha256_hash_ref(
            {key: item for key, item in value.items() if key != "intent_hash"}
        )
    ):
        raise _invalid(
            "M1_PLAN_WORK_INTENT_INVALID",
            "M1 WorkIntent authority is invalid or stale.",
        )
    return context


def _preparation(value: Mapping[str, Any]) -> Mapping[str, Any]:
    required = {
        "schema_version",
        "stage",
        "business_context_hash",
        "authority_hash",
        "authority",
        "adapter_identity",
        "identities",
        "references",
        "preparation_hash",
    }
    if (
        not isinstance(value, Mapping)
        or set(value) != required
        or value.get("schema_version") != M1_PREPARATION_SCHEMA_VERSION
        or value.get("stage") != "READY_FOR_D04"
    ):
        raise _invalid(
            "M1_PLAN_READY_CHECKPOINT_REQUIRED",
            "M1 READY_FOR_D04 checkpoint is required.",
        )
    record = dict(value)
    expected = semantic_sha256_hash_ref(
        {key: item for key, item in record.items() if key != "preparation_hash"}
    )
    authority = record.get("authority")
    references = record.get("references")
    if (
        record.get("preparation_hash") != expected
        or not isinstance(authority, Mapping)
        or not isinstance(references, Mapping)
        or not _D04_REFERENCE_FIELDS.issubset(references)
    ):
        raise _invalid(
            "M1_PLAN_PREPARATION_INTEGRITY_INVALID",
            "M1 preparation checkpoint integrity is invalid.",
        )
    expected_authority = semantic_sha256_hash_ref(
        {key: item for key, item in authority.items() if key != "authority_hash"}
    )
    if (
        authority.get("authority_hash") != expected_authority
        or record.get("authority_hash") != expected_authority
    ):
        raise _invalid(
            "M1_PLAN_AUTHORITY_INTEGRITY_INVALID",
            "M1 preparation authority integrity is invalid.",
        )
    for field in (
        "candidate_hash",
        "accounting_proof_hash",
        "posting_admission_hash",
    ):
        try:
            validate_hash_ref(references[field])
        except (TypeError, ValueError) as exc:
            raise _invalid(
                "M1_PLAN_REFERENCE_INVALID",
                f"M1 preparation {field} is invalid.",
            ) from exc
    return record


def _capabilities(
    snapshot: Mapping[str, Any],
    installed: Mapping[str, Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    if set(installed) != set(_CAPABILITY_IDS):
        raise _invalid(
            "M1_PLAN_CAPABILITY_SET_INCOMPLETE",
            "Installed M1 capability set is incomplete.",
        )
    resolved: dict[str, Mapping[str, Any]] = {}
    for capability_id in _CAPABILITY_IDS:
        expected = dict(installed[capability_id])
        try:
            observed = capability_by_exact_version(
                snapshot,
                capability_id,
                str(expected.get("capability_version") or ""),
            )
        except CapabilitySnapshotError as exc:
            raise _invalid("M1_PLAN_CAPABILITY_SNAPSHOT_INVALID", exc.detail) from exc
        if observed != expected:
            raise _invalid(
                "M1_PLAN_CAPABILITY_DRIFT",
                "M1 capability snapshot differs from the installed release.",
            )
        resolved[capability_id] = observed
    return resolved


def _require_lineage(
    *,
    work_intent: Mapping[str, Any],
    agent_context: Mapping[str, Any],
    context: Mapping[str, Any],
    preparation: Mapping[str, Any],
) -> None:
    authority = preparation["authority"]
    identity = agent_context.get("identity")
    entities = agent_context.get("resolved_entities")
    project_ids = {
        str(resource.get("resource_id"))
        for item in entities or ()
        if isinstance(item, Mapping)
        and isinstance((resource := item.get("resource_ref")), Mapping)
        and resource.get("resource_type") == "PROJECT"
    }
    if preparation["business_context_hash"] != context["context_hash"]:
        raise _invalid(
            "M1_PLAN_BUSINESS_CONTEXT_MISMATCH",
            "M1 preparation business context differs from WorkIntent.",
        )
    if (
        not isinstance(identity, Mapping)
        or identity.get("tenant_id") != authority.get("tenant_id")
        or identity.get("principal_id") != authority.get("requester_subject_id")
    ):
        raise _invalid(
            "M1_PLAN_IDENTITY_MISMATCH",
            "M1 preparation requester differs from AgentContext identity.",
        )
    if authority.get("primary_project_id") not in project_ids:
        raise _invalid(
            "M1_PLAN_PRIMARY_PROJECT_MISSING",
            "M1 primary Project is absent from AgentContext authority.",
        )
    if agent_context.get("execution_id") != work_intent.get("execution_id"):
        raise _invalid(
            "M1_PLAN_EXECUTION_MISMATCH",
            "M1 WorkIntent and AgentContext executions differ.",
        )
    if agent_context.get("conflicts"):
        raise _invalid(
            "M1_PLAN_CONTEXT_CONFLICT",
            "M1 AgentContext contains unresolved conflicts.",
        )
    if agent_context.get("degradations"):
        raise _invalid(
            "M1_PLAN_CONTEXT_DEGRADED",
            "M1 AgentContext contains unresolved degradations.",
        )


def _versioned_ref(
    value: Mapping[str, Any], id_field: str, version_field: str, hash_field: str
) -> dict[str, Any]:
    return {
        "id": value[id_field],
        "version": value[version_field],
        "hash": value[hash_field],
    }


def _uuid(field: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _invalid(
            "M1_PLAN_EXECUTION_ID_INVALID", f"M1 {field} is invalid."
        ) from exc


def _timestamp(value: object) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise _invalid(
            "M1_PLAN_EFFECTIVE_TIMESTAMP_INVALID",
            "M1 preparation effective timestamp is invalid.",
        )
    return value


def _invalid(error_code: str, detail: str) -> M1PlanMaterializationError:
    return M1PlanMaterializationError(error_code, detail)
