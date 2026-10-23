from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from nex_runtime.semantic_hashes import (
    canonical_json,
    semantic_sha256_hash_ref,
    validate_hash_ref,
)
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_ae_api.agent_plans import validate_agent_plan_contract
from nex_ae_api.plan_validation import validate_plan_validation_result
from nex_ae_api.planning_capabilities import (
    LOCAL_SKILL_EXECUTOR_KIND,
    REPORT_CAPABILITY_ID,
    validate_capability_snapshot_contract,
    validate_local_skill_binding,
)

EXECUTABLE_PLAN_SCHEMA_VERSION = "1.1"
P6_EXECUTABLE_PLAN_SCHEMA_VERSION = "1.2"
P7_EXECUTABLE_PLAN_SCHEMA_VERSION = "1.3"
COMPILER_VERSION = "p5.1"
P6_COMPILER_VERSION = "p6.1"
P7_COMPILER_VERSION = "p7.1"
WC_DELEGATE_WORK_EXECUTOR_KIND = "WC_DELEGATE_WORK"
_LOGICAL_STEP_ID = re.compile(r"^S[0-9]{1,3}$")
_COMPILED_STEP_KEY = re.compile(r"^E[0-9]{1,3}$")


@dataclass(frozen=True)
class ExecutablePlanError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


def compile_executable_plan(
    *,
    agent_plan: Mapping[str, Any],
    validation_result: Mapping[str, Any],
    agent_context: Mapping[str, Any],
    capability_snapshot: Mapping[str, Any],
    executable_plan_id: str | None = None,
    executable_plan_version: int = 1,
    compiled_at: str | None = None,
    compiler_version: str | None = None,
    id_factory: Callable[[], str] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    plan = validate_agent_plan_contract(agent_plan)
    validation = validate_plan_validation_result(validation_result)
    snapshot = validate_capability_snapshot_contract(capability_snapshot)
    context = _validate_context_lineage(agent_context)
    _require_compile_inputs(plan, validation, context, snapshot)

    ids = id_factory or (lambda: str(uuid4()))
    order = list(validation["topological_step_order"])
    logical_steps = {step["step_id"]: step for step in plan["steps"]}
    if len(order) != len(logical_steps) or set(order) != set(logical_steps):
        raise _invalid("Validation order does not cover the exact AgentPlan steps.")
    key_by_logical = {
        logical_step_id: f"E{index}"
        for index, logical_step_id in enumerate(order, start=1)
    }

    compiled_steps = [
        _compile_step(
            logical_steps[logical_step_id],
            step_index=index,
            compiled_step_key=key_by_logical[logical_step_id],
            key_by_logical=key_by_logical,
            capability_snapshot=snapshot,
            executable_step_id=ids(),
            execution_id=plan["execution_id"],
            agent_plan_version=plan["agent_plan_version"],
        )
        for index, logical_step_id in enumerate(order)
    ]
    has_local_skill = any(
        step["executor_kind"] == LOCAL_SKILL_EXECUTOR_KIND for step in compiled_steps
    )
    has_delegate_work = any(
        step["executor_kind"] == WC_DELEGATE_WORK_EXECUTOR_KIND
        for step in compiled_steps
    )
    plan_id = _required_uuid("executable_plan_id", executable_plan_id or ids())
    compiled_time = _required_datetime(
        "compiled_at",
        compiled_at
        or (clock or (lambda: datetime.now(UTC)))()
        .astimezone(UTC)
        .isoformat()
        .replace("+00:00", "Z"),
    )
    executable_plan: dict[str, Any] = {
        "schema_version": (
            P7_EXECUTABLE_PLAN_SCHEMA_VERSION
            if has_delegate_work
            else (
                P6_EXECUTABLE_PLAN_SCHEMA_VERSION
                if has_local_skill
                else EXECUTABLE_PLAN_SCHEMA_VERSION
            )
        ),
        "executable_plan_id": plan_id,
        "executable_plan_version": _bounded_int(
            "executable_plan_version", executable_plan_version, 1, 99
        ),
        "execution_id": plan["execution_id"],
        "agent_plan_ref": _versioned_ref(
            plan["agent_plan_id"], plan["agent_plan_version"], plan["plan_hash"]
        ),
        "work_intent_ref": dict(plan["work_intent_ref"]),
        "agent_context_ref": dict(plan["agent_context_ref"]),
        "capability_snapshot_ref": dict(plan["capability_snapshot_ref"]),
        "validation_result_ref": _versioned_ref(
            validation["validation_result_id"], 1, validation["result_hash"]
        ),
        "compiler_version": _required_text(
            "compiler_version",
            compiler_version
            or (
                P7_COMPILER_VERSION
                if has_delegate_work
                else (P6_COMPILER_VERSION if has_local_skill else COMPILER_VERSION)
            ),
            64,
        ),
        "policy_snapshot_ref": _policy_snapshot_ref(context),
        "authority_snapshot_ref": _optional_text(
            "authority_snapshot_ref", context.get("authority_ref"), 256
        ),
        "steps": compiled_steps,
        "completion_criteria": [
            {
                "criterion_id": criterion["criterion_id"],
                "required": criterion["required"],
                "required_terminal_compiled_step_keys": [
                    key_by_logical[logical_id]
                    for logical_id in criterion["required_terminal_step_refs"]
                ],
            }
            for criterion in plan["completion_criteria"]
        ],
        "logical_step_mapping": [
            {
                "logical_step_id": step["logical_step_ref"],
                "compiled_step_keys": [step["compiled_step_key"]],
                "executable_step_ids": [step["executable_step_id"]],
            }
            for step in compiled_steps
        ],
        "runtime_constraints": {
            "max_parallel_steps": 1,
            "max_auto_replan": 0,
            "max_steps_per_run_slice": 1,
        },
        "compiled_at": compiled_time,
    }
    executable_plan["executable_plan_hash"] = semantic_sha256_hash_ref(
        executable_plan_semantic_projection(executable_plan)
    )
    return validate_executable_plan_contract(executable_plan)


def executable_plan_semantic_projection(
    executable_plan: Mapping[str, Any],
) -> dict[str, Any]:
    projection = {
        key: value
        for key, value in executable_plan.items()
        if key not in {"executable_plan_id", "compiled_at", "executable_plan_hash"}
    }
    projection["steps"] = [
        {key: value for key, value in step.items() if key != "executable_step_id"}
        for step in executable_plan.get("steps", [])
    ]
    projection["logical_step_mapping"] = [
        {key: value for key, value in item.items() if key != "executable_step_ids"}
        for item in executable_plan.get("logical_step_mapping", [])
    ]
    return projection


def validate_executable_plan_contract(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        record = json.loads(canonical_json(dict(value)))
    except (TypeError, ValueError) as exc:
        raise _invalid("ExecutablePlan must be canonical JSON.") from exc
    required = {
        "schema_version",
        "executable_plan_id",
        "executable_plan_version",
        "execution_id",
        "agent_plan_ref",
        "work_intent_ref",
        "agent_context_ref",
        "capability_snapshot_ref",
        "validation_result_ref",
        "compiler_version",
        "steps",
        "completion_criteria",
        "logical_step_mapping",
        "runtime_constraints",
        "compiled_at",
        "executable_plan_hash",
    }
    optional = {"policy_snapshot_ref", "authority_snapshot_ref"}
    if (
        not required.issubset(record)
        or not set(record).issubset(required | optional)
        or record["schema_version"]
        not in {
            EXECUTABLE_PLAN_SCHEMA_VERSION,
            P6_EXECUTABLE_PLAN_SCHEMA_VERSION,
            P7_EXECUTABLE_PLAN_SCHEMA_VERSION,
        }
    ):
        raise _invalid("ExecutablePlan fields or schema version are invalid.")
    _required_uuid("executable_plan_id", record["executable_plan_id"])
    _bounded_int("executable_plan_version", record["executable_plan_version"], 1, 99)
    _required_uuid("execution_id", record["execution_id"])
    for field in (
        "agent_plan_ref",
        "work_intent_ref",
        "agent_context_ref",
        "capability_snapshot_ref",
        "validation_result_ref",
    ):
        _validate_versioned_ref(field, record[field])
    _required_text("compiler_version", record["compiler_version"], 64)
    for field in optional:
        _optional_text(field, record.get(field), 256)
    _validate_compiled_steps(record["steps"])
    has_local_skill = any(
        step["executor_kind"] == LOCAL_SKILL_EXECUTOR_KIND for step in record["steps"]
    )
    has_delegate_work = any(
        step["executor_kind"] == WC_DELEGATE_WORK_EXECUTOR_KIND
        for step in record["steps"]
    )
    expected_version = (
        P7_EXECUTABLE_PLAN_SCHEMA_VERSION
        if has_delegate_work
        else (
            P6_EXECUTABLE_PLAN_SCHEMA_VERSION
            if has_local_skill
            else EXECUTABLE_PLAN_SCHEMA_VERSION
        )
    )
    if record["schema_version"] != expected_version:
        raise _invalid("ExecutablePlan version does not match its executor content.")
    _validate_completion_criteria(record["completion_criteria"], record["steps"])
    _validate_logical_mapping(record["logical_step_mapping"], record["steps"])
    if record["runtime_constraints"] != {
        "max_parallel_steps": 1,
        "max_auto_replan": 0,
        "max_steps_per_run_slice": 1,
    }:
        raise _invalid("ExecutablePlan runtime constraints are invalid.")
    _required_datetime("compiled_at", record["compiled_at"])
    try:
        validate_hash_ref(record["executable_plan_hash"])
    except ValueError as exc:
        raise _invalid("ExecutablePlan semantic hash is invalid.") from exc
    expected = semantic_sha256_hash_ref(executable_plan_semantic_projection(record))
    if record["executable_plan_hash"] != expected:
        raise _invalid("ExecutablePlan hash does not match semantic content.")
    return record


class SqlAlchemyExecutablePlanRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(
        self, *, tenant_id: str, executable_plan: Mapping[str, Any]
    ) -> dict[str, Any]:
        tenant_id = _required_text("tenant_id", tenant_id, 128)
        normalized = validate_executable_plan_contract(executable_plan)
        try:
            with self._session_factory() as session:
                runtime = _require_compile_authority(session, tenant_id, normalized)
                inserted = session.execute(
                    text(_plan_insert_sql(_dialect_name(session))),
                    _plan_params(tenant_id, normalized),
                )
                for step in normalized["steps"]:
                    session.execute(
                        text(_step_insert_sql(_dialect_name(session))),
                        _step_params(tenant_id, normalized, step, runtime),
                    )
                saved = _load_plan(session, tenant_id, normalized["executable_plan_id"])
                if saved is None:
                    conflict = _load_plan_by_version(
                        session,
                        tenant_id,
                        normalized["execution_id"],
                        normalized["executable_plan_version"],
                    )
                    if conflict is not None:
                        raise ExecutablePlanError(
                            "ae.executable_plan_version_conflict",
                            "A different ExecutablePlan owns this execution version.",
                        )
                    raise ExecutablePlanError(
                        "ae.executable_plan_write_conflict",
                        "ExecutablePlan could not be reloaded.",
                        True,
                    )
                if saved != normalized:
                    raise ExecutablePlanError(
                        "ae.executable_plan_immutable_conflict",
                        "ExecutablePlan identity exists with different content.",
                    )
                persisted_steps = _load_steps(
                    session, tenant_id, normalized["executable_plan_id"]
                )
                _require_persisted_steps(normalized, persisted_steps)
                if int(inserted.rowcount or 0) == 0:
                    _require_same_execution_version(session, tenant_id, normalized)
                session.commit()
                return saved
        except ExecutablePlanError:
            raise
        except SQLAlchemyError as exc:
            raise ExecutablePlanError(
                "ae.executable_plan_store_unavailable",
                "AE ExecutablePlan store is unavailable.",
                True,
            ) from exc

    def get(self, *, tenant_id: str, executable_plan_id: str) -> dict[str, Any] | None:
        tenant_id = _required_text("tenant_id", tenant_id, 128)
        executable_plan_id = _required_uuid("executable_plan_id", executable_plan_id)
        try:
            with self._session_factory() as session:
                return _load_plan(session, tenant_id, executable_plan_id)
        except SQLAlchemyError as exc:
            raise ExecutablePlanError(
                "ae.executable_plan_store_unavailable",
                "AE ExecutablePlan store is unavailable.",
                True,
            ) from exc

    def list_steps(
        self, *, tenant_id: str, executable_plan_id: str
    ) -> list[dict[str, Any]]:
        tenant_id = _required_text("tenant_id", tenant_id, 128)
        executable_plan_id = _required_uuid("executable_plan_id", executable_plan_id)
        try:
            with self._session_factory() as session:
                return _load_steps(session, tenant_id, executable_plan_id)
        except SQLAlchemyError as exc:
            raise ExecutablePlanError(
                "ae.executable_plan_store_unavailable",
                "AE ExecutablePlan store is unavailable.",
                True,
            ) from exc


def _compile_step(
    logical_step: Mapping[str, Any],
    *,
    step_index: int,
    compiled_step_key: str,
    key_by_logical: Mapping[str, str],
    capability_snapshot: Mapping[str, Any],
    executable_step_id: str,
    execution_id: str,
    agent_plan_version: int,
) -> dict[str, Any]:
    logical_id = str(logical_step["step_id"])
    capability = _resolve_capability(logical_step, capability_snapshot)
    dependencies = []
    for dependency in logical_step["depends_on"]:
        try:
            dependencies.append(key_by_logical[str(dependency)])
        except KeyError as exc:
            raise _invalid(
                "AgentPlan dependency is absent from validation order."
            ) from exc
    if any(int(item[1:]) >= int(compiled_step_key[1:]) for item in dependencies):
        raise _invalid("Compiled dependencies must precede their dependent step.")
    semantic_step: dict[str, Any] = {
        "compiled_step_key": compiled_step_key,
        "step_index": step_index,
        "logical_step_ref": logical_id,
        "injected_for_logical_step_ref": None,
        "step_type": capability["executable_step_type"],
        "executor_kind": capability["executor_kind"],
        "title": logical_step["title"],
        "depends_on_compiled_step_keys": dependencies,
        "required_capability": capability["capability_id"],
        "capability_version": capability["capability_version"],
        "compiled_input_bindings": [
            _compile_binding(binding, key_by_logical)
            for binding in logical_step["input_bindings"]
        ],
        "output_contract_ref": capability["output_contract_ref"],
        "timeout_policy_ref": (
            "policy://nex/ae/chat-timeout/v1"
            if capability["executor_kind"] == "P4_CHAT_RAG_COMPATIBILITY"
            else None
        ),
        "retry_policy_ref": (
            "policy://nex/ae/chat-retry/v1"
            if capability["executor_kind"] == "P4_CHAT_RAG_COMPATIBILITY"
            else None
        ),
    }
    if capability["executor_kind"] == LOCAL_SKILL_EXECUTOR_KIND:
        semantic_step["skill_binding"] = dict(capability["local_skill_binding"])
        semantic_step["timeout_policy_ref"] = "policy://nex/ae/local-skill-timeout/v1"
        semantic_step["retry_policy_ref"] = "policy://nex/ae/local-skill-retry/v1"
    if capability["executor_kind"] == WC_DELEGATE_WORK_EXECUTOR_KIND:
        semantic_step["delegation"] = _compile_delegation(
            logical_step,
            execution_id=execution_id,
            agent_plan_version=agent_plan_version,
        )
        semantic_step["timeout_policy_ref"] = "policy://nex/ae/wc-delegate-timeout/v1"
        semantic_step["retry_policy_ref"] = "policy://nex/ae/wc-delegate-retry/v1"
    if logical_step["output_contract_ref"] != semantic_step["output_contract_ref"]:
        raise _invalid("AgentPlan output contract differs from exact capability.")
    step = {
        **semantic_step,
        "executable_step_id": _required_uuid("executable_step_id", executable_step_id),
    }
    step["step_contract_hash"] = semantic_sha256_hash_ref(semantic_step)
    return step


def _resolve_capability(
    logical_step: Mapping[str, Any], snapshot: Mapping[str, Any]
) -> Mapping[str, Any]:
    logical_type = str(logical_step["step_type"])
    if logical_type == "DELEGATE_WORK":
        delegation = logical_step.get("delegation")
        if not isinstance(delegation, Mapping):
            raise _invalid("DELEGATE_WORK metadata is unavailable.")
        return {
            "capability_id": logical_step["required_capability"],
            "capability_version": "delegation.v1",
            "executable_step_type": "DELEGATE_WORK",
            "executor_kind": WC_DELEGATE_WORK_EXECUTOR_KIND,
            "output_contract_ref": delegation["result_contract_ref"],
        }
    capability_id = logical_step.get("required_capability")
    version = logical_step.get("capability_version_constraint")
    if capability_id is None and logical_type == "REPORT":
        capability_id = REPORT_CAPABILITY_ID
    matches = [
        item
        for item in snapshot["capabilities"]
        if logical_type in item["allowed_logical_step_types"]
        and (capability_id is None or item["capability_id"] == capability_id)
        and (version is None or item["capability_version"] == version)
    ]
    if len(matches) != 1:
        raise _invalid("Exact executable capability is unavailable or ambiguous.")
    return matches[0]


def _compile_delegation(
    logical_step: Mapping[str, Any],
    *,
    execution_id: str,
    agent_plan_version: int,
) -> dict[str, Any]:
    metadata = logical_step["delegation"]
    identity = (
        "https://nex-platform.local/ae/delegations/"
        f"{execution_id}/{agent_plan_version}/{logical_step['step_id']}"
    )
    return {
        "schema_version": "1.0",
        "delegation_id": str(uuid5(NAMESPACE_URL, identity)),
        "delegation_revision": agent_plan_version,
        "goal": logical_step["objective"],
        "work_class": metadata["work_class"],
        "required_agent_type": metadata["required_agent_type"],
        "required_capability": logical_step["required_capability"],
        "project_ref": {
            "entity_type": "PROJECT",
            "entity_id": metadata["project_scope_ref"],
        },
        "project_scope_ref": metadata["project_scope_ref"],
        "result_contract_ref": metadata["result_contract_ref"],
        "completion_policy": metadata["completion_policy"],
    }


def _compile_binding(
    binding: Mapping[str, Any], key_by_logical: Mapping[str, str]
) -> dict[str, Any]:
    source_type = str(binding["source_type"])
    target_name = str(binding["target_name"])
    if source_type == "STEP_OUTPUT":
        source_ref = binding.get("source_ref")
        if source_ref not in key_by_logical:
            raise _invalid("STEP_OUTPUT binding references an unknown logical step.")
        pointer = binding.get("json_pointer") or "$"
        compiled: dict[str, Any] = {
            "target_name": target_name,
            "binding_type": "COMPILED_STEP_OUTPUT",
            "source_ref": f"{key_by_logical[str(source_ref)]}:{pointer}",
        }
    elif source_type == "LITERAL":
        if "literal_value" not in binding:
            raise _invalid("LITERAL binding requires literal_value.")
        compiled = {
            "target_name": target_name,
            "binding_type": "LITERAL",
            "value": binding["literal_value"],
            "source_ref": None,
        }
    elif source_type in {"WORK_INTENT_PARAMETER", "ENTITY_SELECTOR"}:
        source_ref = _required_text("source_ref", binding.get("source_ref"), 160)
        compiled = {
            "target_name": target_name,
            "binding_type": "RESOURCE_REF",
            "source_ref": source_ref,
        }
    else:
        raise _invalid("AgentPlan input binding source type is unsupported.")
    compiled["binding_hash"] = semantic_sha256_hash_ref(compiled)
    return compiled


def _require_compile_inputs(
    plan: Mapping[str, Any],
    validation: Mapping[str, Any],
    context: Mapping[str, Any],
    snapshot: Mapping[str, Any],
) -> None:
    if (
        validation["status"] != "VALID"
        or validation["runtime_directive"] != "PROCEED_TO_COMPILE"
        or validation["issues"]
    ):
        raise _invalid("Only an issue-free VALID result grants compile authority.")
    expected_plan_ref = _versioned_ref(
        plan["agent_plan_id"], plan["agent_plan_version"], plan["plan_hash"]
    )
    if validation["agent_plan_ref"] != expected_plan_ref:
        raise _invalid("Validation result does not reference the exact AgentPlan.")
    if validation["execution_id"] != plan["execution_id"]:
        raise _invalid("Validation execution does not match the AgentPlan.")
    if validation["validated_context_ref"] != plan["agent_context_ref"]:
        raise _invalid("Validation context does not match the AgentPlan.")
    context_ref = _versioned_ref(
        context["context_id"],
        context["context_generation"],
        context["context_hash"],
    )
    if context_ref != plan["agent_context_ref"]:
        raise _invalid("AgentContext does not match the AgentPlan.")
    snapshot_ref = _versioned_ref(
        snapshot["capability_snapshot_id"],
        snapshot["snapshot_version"],
        snapshot["snapshot_hash"],
    )
    if snapshot_ref != plan["capability_snapshot_ref"]:
        raise _invalid("Capability snapshot does not match the AgentPlan.")


def _validate_context_lineage(value: Mapping[str, Any]) -> dict[str, Any]:
    try:
        context = json.loads(canonical_json(dict(value)))
        _required_uuid("context_id", context.get("context_id"))
        _bounded_int("context_generation", context.get("context_generation"), 1, 9999)
        _required_uuid("execution_id", context.get("execution_id"))
        validate_hash_ref(context.get("context_hash"))
    except (KeyError, TypeError, ValueError) as exc:
        raise _invalid("AgentContext lineage is invalid.") from exc
    expected = semantic_sha256_hash_ref(
        {key: item for key, item in context.items() if key != "context_hash"}
    )
    if context["context_hash"] != expected:
        raise _invalid("AgentContext hash does not match its content.")
    return context


def _policy_snapshot_ref(context: Mapping[str, Any]) -> str | None:
    policy = context.get("runtime_policy_ref")
    if not isinstance(policy, Mapping):
        return None
    try:
        hash_ref = validate_hash_ref(policy.get("rule_hash"))
    except ValueError as exc:
        raise _invalid("AgentContext runtime policy hash is invalid.") from exc
    return f"policy-snapshot:{hash_ref}"


def validate_compiled_delegation(value: object) -> dict[str, Any]:
    fields = {
        "schema_version",
        "delegation_id",
        "delegation_revision",
        "goal",
        "work_class",
        "required_agent_type",
        "required_capability",
        "project_ref",
        "project_scope_ref",
        "result_contract_ref",
        "completion_policy",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise _invalid("Compiled delegation fields are invalid.")
    record = json.loads(canonical_json(dict(value)))
    if record["schema_version"] != "1.0":
        raise _invalid("Compiled delegation schema version is invalid.")
    _required_uuid("delegation_id", record["delegation_id"])
    _bounded_int("delegation_revision", record["delegation_revision"], 1, 99)
    for field, maximum in (
        ("goal", 700),
        ("required_capability", 160),
        ("project_scope_ref", 160),
        ("result_contract_ref", 256),
    ):
        _required_text(field, record[field], maximum)
    if record["work_class"] not in {
        "QUERY",
        "ANALYSIS",
        "DOCUMENT",
        "BUSINESS_TRANSACTION",
        "COORDINATION",
        "EXPERT_REVIEW",
        "REPORTING",
        "OPERATIONAL",
    }:
        raise _invalid("Compiled delegation work class is invalid.")
    if record["required_agent_type"] not in {"CA", "PA", "EA"}:
        raise _invalid("Compiled delegation agent type is invalid.")
    if record["completion_policy"] not in {
        "OWNER_SUBMITS",
        "ALL_ASSIGNEES_SUBMIT",
        "ANY_ASSIGNEE_SUBMITS",
        "ALL_REQUIRED_CHILDREN",
        "MANUAL",
    }:
        raise _invalid("Compiled delegation completion policy is invalid.")
    project = record["project_ref"]
    if (
        not isinstance(project, Mapping)
        or set(project) != {"entity_type", "entity_id"}
        or project["entity_type"] != "PROJECT"
        or project["entity_id"] != record["project_scope_ref"]
    ):
        raise _invalid("Compiled delegation project lineage is invalid.")
    return record


def _validate_compiled_delegation(step: Mapping[str, Any], value: object) -> None:
    delegation = validate_compiled_delegation(value)
    if (
        step["step_type"] != "DELEGATE_WORK"
        or step.get("required_capability") != delegation["required_capability"]
        or step.get("capability_version") != "delegation.v1"
        or step["output_contract_ref"] != delegation["result_contract_ref"]
    ):
        raise _invalid("ExecutableStep delegation selector is inconsistent.")


def _validate_compiled_steps(value: object) -> None:
    if not isinstance(value, list) or not 1 <= len(value) <= 12:
        raise _invalid("ExecutablePlan steps are invalid.")
    compiled_keys: list[str] = []
    logical_ids: list[str] = []
    runtime_ids: list[str] = []
    for index, step in enumerate(value):
        required = {
            "compiled_step_key",
            "executable_step_id",
            "step_index",
            "logical_step_ref",
            "step_type",
            "executor_kind",
            "title",
            "depends_on_compiled_step_keys",
            "compiled_input_bindings",
            "output_contract_ref",
            "step_contract_hash",
        }
        optional = {
            "injected_for_logical_step_ref",
            "required_capability",
            "capability_version",
            "timeout_policy_ref",
            "retry_policy_ref",
            "skill_binding",
            "delegation",
        }
        if (
            not isinstance(step, Mapping)
            or not required.issubset(step)
            or not set(step).issubset(required | optional)
        ):
            raise _invalid("ExecutableStep fields are invalid.")
        expected_key = f"E{index + 1}"
        if step["compiled_step_key"] != expected_key or step["step_index"] != index:
            raise _invalid("Compiled step keys and indices must be sequential.")
        _required_uuid("executable_step_id", step["executable_step_id"])
        logical_id = str(step["logical_step_ref"])
        if _LOGICAL_STEP_ID.fullmatch(logical_id) is None:
            raise _invalid("ExecutableStep logical reference is invalid.")
        if step.get("injected_for_logical_step_ref") is not None and (
            _LOGICAL_STEP_ID.fullmatch(str(step["injected_for_logical_step_ref"]))
            is None
        ):
            raise _invalid("ExecutableStep injected logical reference is invalid.")
        if step["step_type"] not in {
            "LOCAL_SKILL",
            "CANONICAL_CAPABILITY",
            "DELEGATE_WORK",
            "HUMAN_CONFIRMATION",
            "FORMAL_APPROVAL",
            "AGGREGATE",
            "REPORT",
        }:
            raise _invalid("ExecutableStep type is invalid.")
        if step["executor_kind"] not in {
            "P4_CHAT_RAG_COMPATIBILITY",
            "DETERMINISTIC_AGGREGATE",
            "DETERMINISTIC_REPORT",
            LOCAL_SKILL_EXECUTOR_KIND,
            "LOCAL_SKILL_UNAVAILABLE",
            "DELEGATE_WORK_UNAVAILABLE",
            WC_DELEGATE_WORK_EXECUTOR_KIND,
        }:
            raise _invalid("ExecutableStep executor kind is invalid.")
        _required_text("title", step["title"], 160)
        dependencies = step["depends_on_compiled_step_keys"]
        if (
            not isinstance(dependencies, list)
            or len(dependencies) > 12
            or len(set(dependencies)) != len(dependencies)
            or any(item not in compiled_keys for item in dependencies)
        ):
            raise _invalid("ExecutableStep dependencies are invalid.")
        _validate_compiled_bindings(step["compiled_input_bindings"], compiled_keys)
        for field, maximum in (
            ("required_capability", 160),
            ("capability_version", 64),
            ("output_contract_ref", 256),
            ("timeout_policy_ref", 256),
            ("retry_policy_ref", 256),
        ):
            if field == "output_contract_ref":
                _required_text(field, step[field], maximum)
            else:
                _optional_text(field, step.get(field), maximum)
        local_binding = step.get("skill_binding")
        if step["executor_kind"] == LOCAL_SKILL_EXECUTOR_KIND:
            if step["step_type"] != "LOCAL_SKILL":
                raise _invalid("LOCAL_SKILL executor requires LOCAL_SKILL step type.")
            try:
                normalized_binding = validate_local_skill_binding(local_binding)
            except Exception as exc:
                raise _invalid(
                    "ExecutableStep LOCAL_SKILL binding is invalid."
                ) from exc
            if (
                normalized_binding != local_binding
                or normalized_binding.get(
                    "capability_id", normalized_binding["skill_id"]
                )
                != step.get("required_capability")
                or normalized_binding["exact_skill_version"]
                != step.get("capability_version")
            ):
                raise _invalid("ExecutableStep LOCAL_SKILL selector is inconsistent.")
        elif local_binding is not None:
            raise _invalid("Non-LOCAL_SKILL step cannot carry a Skill binding.")
        delegation = step.get("delegation")
        if step["executor_kind"] == WC_DELEGATE_WORK_EXECUTOR_KIND:
            _validate_compiled_delegation(step, delegation)
        elif delegation is not None:
            raise _invalid("Only WC_DELEGATE_WORK may carry delegation metadata.")
        try:
            validate_hash_ref(step["step_contract_hash"])
        except ValueError as exc:
            raise _invalid("ExecutableStep contract hash is invalid.") from exc
        semantic_step = {
            key: item
            for key, item in step.items()
            if key not in {"executable_step_id", "step_contract_hash"}
        }
        if step["step_contract_hash"] != semantic_sha256_hash_ref(semantic_step):
            raise _invalid("ExecutableStep hash does not match semantic content.")
        compiled_keys.append(expected_key)
        logical_ids.append(logical_id)
        runtime_ids.append(str(step["executable_step_id"]))
    if len(set(logical_ids)) != len(logical_ids) or len(set(runtime_ids)) != len(
        runtime_ids
    ):
        raise _invalid("ExecutableStep identities must be unique.")


def _validate_compiled_bindings(value: object, prior_keys: Sequence[str]) -> None:
    if not isinstance(value, list) or len(value) > 32:
        raise _invalid("Compiled input bindings are invalid.")
    for binding in value:
        required = {"target_name", "binding_type", "binding_hash"}
        optional = {"value", "source_ref"}
        if (
            not isinstance(binding, Mapping)
            or not required.issubset(binding)
            or not set(binding).issubset(required | optional)
            or re.fullmatch(r"^[a-z][a-z0-9_]{0,63}$", str(binding["target_name"]))
            is None
            or binding["binding_type"]
            not in {"TYPED_VALUE", "RESOURCE_REF", "COMPILED_STEP_OUTPUT", "LITERAL"}
        ):
            raise _invalid("Compiled input binding is invalid.")
        source_ref = binding.get("source_ref")
        if binding["binding_type"] == "COMPILED_STEP_OUTPUT":
            if (
                not isinstance(source_ref, str)
                or source_ref.split(":", 1)[0] not in prior_keys
            ):
                raise _invalid(
                    "Compiled step output binding must reference a prior E-key."
                )
        elif source_ref is not None:
            _required_text("source_ref", source_ref, 256)
        try:
            validate_hash_ref(binding["binding_hash"])
        except ValueError as exc:
            raise _invalid("Compiled input binding hash is invalid.") from exc
        projection = {
            key: item for key, item in binding.items() if key != "binding_hash"
        }
        if binding["binding_hash"] != semantic_sha256_hash_ref(projection):
            raise _invalid("Compiled input binding hash does not match content.")


def _validate_completion_criteria(
    value: object, steps: Sequence[Mapping[str, Any]]
) -> None:
    if not isinstance(value, list) or not 1 <= len(value) <= 16:
        raise _invalid("ExecutablePlan completion criteria are invalid.")
    keys = {step["compiled_step_key"] for step in steps}
    seen: set[str] = set()
    for criterion in value:
        if not isinstance(criterion, Mapping) or set(criterion) != {
            "criterion_id",
            "required",
            "required_terminal_compiled_step_keys",
        }:
            raise _invalid("ExecutablePlan completion criterion is invalid.")
        criterion_id = str(criterion["criterion_id"])
        refs = criterion["required_terminal_compiled_step_keys"]
        if (
            re.fullmatch(r"^C[0-9]{1,3}$", criterion_id) is None
            or criterion_id in seen
            or not isinstance(criterion["required"], bool)
            or not isinstance(refs, list)
            or not refs
            or len(set(refs)) != len(refs)
            or any(ref not in keys for ref in refs)
        ):
            raise _invalid("ExecutablePlan completion criterion is invalid.")
        seen.add(criterion_id)


def _validate_logical_mapping(
    value: object, steps: Sequence[Mapping[str, Any]]
) -> None:
    expected = [
        {
            "logical_step_id": step["logical_step_ref"],
            "compiled_step_keys": [step["compiled_step_key"]],
            "executable_step_ids": [step["executable_step_id"]],
        }
        for step in steps
    ]
    if value != expected:
        raise _invalid("ExecutablePlan logical step mapping is inconsistent.")


def _require_compile_authority(
    session: Session, tenant_id: str, plan: Mapping[str, Any]
) -> dict[str, Any]:
    execution = (
        session.execute(
            text("""
            SELECT *
            FROM ae_agent_execution
            WHERE tenant_id = :tenant_id AND agent_execution_id = :execution_id
            """),
            {"tenant_id": tenant_id, "execution_id": plan["execution_id"]},
        )
        .mappings()
        .first()
    )
    source_type = None if execution is None else execution.get("source_type")
    if source_type is None and execution is not None:
        source_type = (
            "PROMPT" if execution.get("legacy_interaction_id") is not None else None
        )
    if (
        execution is None
        or execution["state"] != "RUNNING"
        or execution["phase"] != "PLAN_COMPILE"
        or (source_type == "PROMPT" and execution["legacy_interaction_id"] is None)
        or (
            source_type == "CLAIMED_WORKITEM" and execution.get("work_item_ref") is None
        )
        or source_type not in {"PROMPT", "CLAIMED_WORKITEM"}
    ):
        raise ExecutablePlanError(
            "ae.executable_plan_authority_missing",
            "ExecutablePlan requires RUNNING / PLAN_COMPILE execution authority.",
        )
    checks = (
        (
            "ae_agent_plan",
            "agent_plan_id",
            "agent_plan_version",
            "plan_hash",
            plan["agent_plan_ref"],
        ),
        (
            "ae_work_intent",
            "work_intent_id",
            "intent_revision",
            "intent_hash",
            plan["work_intent_ref"],
        ),
        (
            "ae_agent_context",
            "context_id",
            "context_generation",
            "context_hash",
            plan["agent_context_ref"],
        ),
        (
            "ae_capability_snapshot",
            "capability_snapshot_id",
            "snapshot_version",
            "snapshot_hash",
            plan["capability_snapshot_ref"],
        ),
    )
    for table, id_column, version_column, hash_column, reference in checks:
        row = (
            session.execute(
                text(
                    f"SELECT {version_column}, {hash_column} FROM {table} "
                    f"WHERE tenant_id = :tenant_id AND {id_column} = :record_id"
                ),
                {"tenant_id": tenant_id, "record_id": reference["id"]},
            )
            .mappings()
            .first()
        )
        if (
            row is None
            or int(row[version_column]) != reference["version"]
            or row[hash_column] != reference["hash"]
        ):
            raise ExecutablePlanError(
                "ae.executable_plan_lineage_mismatch",
                "ExecutablePlan does not reference exact persisted planning inputs.",
            )
    validation = (
        session.execute(
            text("""
            SELECT agent_plan_id, agent_plan_version, agent_execution_id,
                   status, runtime_directive, result_hash
            FROM ae_plan_validation
            WHERE tenant_id = :tenant_id
              AND validation_result_id = :validation_result_id
            """),
            {
                "tenant_id": tenant_id,
                "validation_result_id": plan["validation_result_ref"]["id"],
            },
        )
        .mappings()
        .first()
    )
    if (
        validation is None
        or str(validation["agent_plan_id"]) != plan["agent_plan_ref"]["id"]
        or int(validation["agent_plan_version"]) != plan["agent_plan_ref"]["version"]
        or str(validation["agent_execution_id"]) != plan["execution_id"]
        or validation["status"] != "VALID"
        or validation["runtime_directive"] != "PROCEED_TO_COMPILE"
        or validation["result_hash"] != plan["validation_result_ref"]["hash"]
    ):
        raise ExecutablePlanError(
            "ae.executable_plan_validation_mismatch",
            "ExecutablePlan lacks exact persisted VALID compile authority.",
        )
    return dict(execution)


def _plan_params(tenant_id: str, plan: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "tenant_id": tenant_id,
        "executable_plan_id": plan["executable_plan_id"],
        "executable_plan_version": plan["executable_plan_version"],
        "agent_execution_id": plan["execution_id"],
        "agent_plan_id": plan["agent_plan_ref"]["id"],
        "agent_plan_version": plan["agent_plan_ref"]["version"],
        "validation_result_id": plan["validation_result_ref"]["id"],
        "compiler_version": plan["compiler_version"],
        "plan_hash": plan["executable_plan_hash"],
        "plan_json": canonical_json(plan),
        "compiled_at": plan["compiled_at"],
    }


def _step_params(
    tenant_id: str,
    plan: Mapping[str, Any],
    step: Mapping[str, Any],
    runtime: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "tenant_id": tenant_id,
        "executable_step_id": step["executable_step_id"],
        "agent_execution_id": plan["execution_id"],
        "step_kind": step["executor_kind"],
        "state": "READY" if not step["depends_on_compiled_step_keys"] else "PENDING",
        "legacy_interaction_id": str(
            runtime["legacy_interaction_id"] or runtime["work_item_ref"]
        ),
        "correlation_id": runtime["correlation_id"],
        "causation_id": runtime["causation_id"],
        "executable_plan_id": plan["executable_plan_id"],
        "logical_step_id": step["logical_step_ref"],
        "compiled_step_key": step["compiled_step_key"],
        "step_index": step["step_index"],
        "step_type": step["step_type"],
        "executor_kind": step["executor_kind"],
        "required_capability": step.get("required_capability"),
        "capability_version": step.get("capability_version"),
        "dependency_json": canonical_json(step["depends_on_compiled_step_keys"]),
        "input_binding_json": canonical_json(step["compiled_input_bindings"]),
        "skill_binding_json": (
            canonical_json(step["skill_binding"])
            if step.get("skill_binding") is not None
            else None
        ),
        "output_contract_ref": step["output_contract_ref"],
        "step_contract_hash": step["step_contract_hash"],
        "now": plan["compiled_at"],
    }


def _plan_insert_sql(dialect_name: str) -> str:
    payload = (
        "CAST(:plan_json AS jsonb)" if dialect_name == "postgresql" else ":plan_json"
    )
    return f"""
        INSERT INTO ae_executable_plan (
            tenant_id, executable_plan_id, executable_plan_version,
            agent_execution_id, agent_plan_id, agent_plan_version,
            validation_result_id, compiler_version, plan_hash, plan_json, compiled_at
        ) VALUES (
            :tenant_id, :executable_plan_id, :executable_plan_version,
            :agent_execution_id, :agent_plan_id, :agent_plan_version,
            :validation_result_id, :compiler_version, :plan_hash, {payload}, :compiled_at
        ) ON CONFLICT DO NOTHING
    """


def _step_insert_sql(dialect_name: str) -> str:
    dependencies = (
        "CAST(:dependency_json AS jsonb)"
        if dialect_name == "postgresql"
        else ":dependency_json"
    )
    bindings = (
        "CAST(:input_binding_json AS jsonb)"
        if dialect_name == "postgresql"
        else ":input_binding_json"
    )
    skill_binding = (
        "CAST(:skill_binding_json AS jsonb)"
        if dialect_name == "postgresql"
        else ":skill_binding_json"
    )
    return f"""
        INSERT INTO ae_executable_step (
            tenant_id, executable_step_id, agent_execution_id, step_kind, state,
            version, legacy_interaction_id, correlation_id, causation_id,
            executable_plan_id, logical_step_id, compiled_step_key, step_index,
            step_type, executor_kind, required_capability, capability_version,
            dependency_json, input_binding_json, skill_binding_json, output_contract_ref,
            step_contract_hash, created_at, updated_at
        ) VALUES (
            :tenant_id, :executable_step_id, :agent_execution_id, :step_kind, :state,
            1, :legacy_interaction_id, :correlation_id, :causation_id,
            :executable_plan_id, :logical_step_id, :compiled_step_key, :step_index,
            :step_type, :executor_kind, :required_capability, :capability_version,
            {dependencies}, {bindings}, {skill_binding}, :output_contract_ref,
            :step_contract_hash, :now, :now
        ) ON CONFLICT DO NOTHING
    """


def _load_plan(
    session: Session, tenant_id: str, executable_plan_id: str
) -> dict[str, Any] | None:
    row = (
        session.execute(
            text("""
            SELECT plan_json FROM ae_executable_plan
            WHERE tenant_id = :tenant_id AND executable_plan_id = :plan_id
            """),
            {"tenant_id": tenant_id, "plan_id": executable_plan_id},
        )
        .mappings()
        .first()
    )
    return None if row is None else _json_value(row["plan_json"])


def _load_plan_by_version(
    session: Session, tenant_id: str, execution_id: str, version: int
) -> dict[str, Any] | None:
    row = (
        session.execute(
            text("""
            SELECT plan_json FROM ae_executable_plan
            WHERE tenant_id = :tenant_id AND agent_execution_id = :execution_id
              AND executable_plan_version = :version
            """),
            {"tenant_id": tenant_id, "execution_id": execution_id, "version": version},
        )
        .mappings()
        .first()
    )
    return None if row is None else _json_value(row["plan_json"])


def _load_steps(
    session: Session, tenant_id: str, executable_plan_id: str
) -> list[dict[str, Any]]:
    rows = (
        session.execute(
            text("""
            SELECT executable_step_id, agent_execution_id, state, version,
                   executable_plan_id, logical_step_id, compiled_step_key,
                   step_index, step_type, executor_kind, required_capability,
                   capability_version, dependency_json, input_binding_json,
                   skill_binding_json,
                   output_contract_ref, step_contract_hash
            FROM ae_executable_step
            WHERE tenant_id = :tenant_id AND executable_plan_id = :plan_id
            ORDER BY step_index
            """),
            {"tenant_id": tenant_id, "plan_id": executable_plan_id},
        )
        .mappings()
        .all()
    )
    return [
        {
            "executable_step_id": str(row["executable_step_id"]),
            "agent_execution_id": str(row["agent_execution_id"]),
            "state": row["state"],
            "version": int(row["version"]),
            "executable_plan_id": str(row["executable_plan_id"]),
            "logical_step_id": row["logical_step_id"],
            "compiled_step_key": row["compiled_step_key"],
            "step_index": int(row["step_index"]),
            "step_type": row["step_type"],
            "executor_kind": row["executor_kind"],
            "required_capability": row["required_capability"],
            "capability_version": row["capability_version"],
            "dependencies": _json_list(row["dependency_json"]),
            "compiled_input_bindings": _json_list(row["input_binding_json"]),
            "skill_binding": _json_optional_object(row["skill_binding_json"]),
            "output_contract_ref": row["output_contract_ref"],
            "step_contract_hash": row["step_contract_hash"],
        }
        for row in rows
    ]


def _require_persisted_steps(
    plan: Mapping[str, Any], persisted: Sequence[Mapping[str, Any]]
) -> None:
    if len(persisted) != len(plan["steps"]):
        raise ExecutablePlanError(
            "ae.executable_plan_step_conflict",
            "ExecutablePlan steps were not materialized exactly once.",
        )
    for expected, actual in zip(plan["steps"], persisted, strict=True):
        checks = {
            "executable_step_id": expected["executable_step_id"],
            "agent_execution_id": plan["execution_id"],
            "executable_plan_id": plan["executable_plan_id"],
            "logical_step_id": expected["logical_step_ref"],
            "compiled_step_key": expected["compiled_step_key"],
            "step_index": expected["step_index"],
            "step_type": expected["step_type"],
            "executor_kind": expected["executor_kind"],
            "required_capability": expected.get("required_capability"),
            "capability_version": expected.get("capability_version"),
            "dependencies": expected["depends_on_compiled_step_keys"],
            "compiled_input_bindings": expected["compiled_input_bindings"],
            "skill_binding": expected.get("skill_binding"),
            "output_contract_ref": expected["output_contract_ref"],
            "step_contract_hash": expected["step_contract_hash"],
        }
        if any(actual.get(key) != value for key, value in checks.items()):
            raise ExecutablePlanError(
                "ae.executable_plan_step_conflict",
                "Persisted ExecutableStep differs from compiled semantics.",
            )


def _require_same_execution_version(
    session: Session, tenant_id: str, plan: Mapping[str, Any]
) -> None:
    existing = _load_plan_by_version(
        session,
        tenant_id,
        plan["execution_id"],
        plan["executable_plan_version"],
    )
    if existing != plan:
        raise ExecutablePlanError(
            "ae.executable_plan_version_conflict",
            "A different ExecutablePlan owns this execution version.",
        )


def _validate_versioned_ref(field: str, value: object) -> None:
    if not isinstance(value, Mapping) or set(value) != {"id", "version", "hash"}:
        raise _invalid(f"{field} must be a versioned hash reference.")
    _required_uuid(f"{field}.id", value["id"])
    _bounded_int(f"{field}.version", value["version"], 1, 9999)
    try:
        validate_hash_ref(value["hash"])
    except ValueError as exc:
        raise _invalid(f"{field}.hash is invalid.") from exc


def _versioned_ref(
    record_id: object, version: object, hash_ref: object
) -> dict[str, Any]:
    try:
        normalized_hash = validate_hash_ref(hash_ref)
    except ValueError as exc:
        raise _invalid("Versioned hash reference is invalid.") from exc
    return {
        "id": _required_uuid("reference.id", record_id),
        "version": _bounded_int("reference.version", version, 1, 9999),
        "hash": normalized_hash,
    }


def _required_uuid(field: str, value: object) -> str:
    if not isinstance(value, str):
        raise _invalid(f"{field} must be a UUID string.")
    try:
        UUID(value)
    except ValueError as exc:
        raise _invalid(f"{field} must be a UUID string.") from exc
    return value


def _bounded_int(field: str, value: object, minimum: int, maximum: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise _invalid(f"{field} must be between {minimum} and {maximum}.")
    return value


def _required_text(field: str, value: object, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise _invalid(f"{field} must be a non-empty bounded string.")
    return value.strip()


def _optional_text(field: str, value: object, maximum: int) -> str | None:
    return None if value is None else _required_text(field, value, maximum)


def _required_datetime(field: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"{field} must be an RFC 3339 date-time string.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid(f"{field} must be an RFC 3339 date-time string.") from exc
    if parsed.tzinfo is None:
        raise _invalid(f"{field} must include a timezone offset.")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _json_value(value: Any) -> dict[str, Any]:
    return json.loads(value) if isinstance(value, str) else dict(value)


def _json_list(value: Any) -> list[Any]:
    decoded = json.loads(value) if isinstance(value, str) else value
    return list(decoded)


def _json_optional_object(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    decoded = json.loads(value) if isinstance(value, str) else value
    return dict(decoded)


def _dialect_name(session: Session) -> str:
    return session.get_bind().dialect.name


def _invalid(detail: str) -> ExecutablePlanError:
    return ExecutablePlanError("ae.executable_plan_invalid", detail)
