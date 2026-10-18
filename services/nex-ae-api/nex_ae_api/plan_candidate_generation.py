from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from nex_runtime.prompts import PromptRegistryError, render_prompt_from_binding
from nex_runtime.semantic_hashes import (
    canonical_json,
    semantic_sha256_hash_ref,
    validate_hash_ref,
    validate_sha256_digest,
)

from nex_ae_api.agent_plans import AgentPlanError, validate_agent_plan_contract
from nex_ae_api.mo_generation_client import (
    AeMoGenerationClient,
    AeMoGenerationReadiness,
    AeMoGenerationResult,
)
from nex_ae_api.planning_capabilities import (
    CAPABILITY_VERSION,
    REPORT_CAPABILITY_ID,
    CapabilitySnapshotError,
    capability_by_exact_version,
    validate_capability_snapshot_contract,
)
from nex_ae_api.prompts import AE_PLAN_BUILDER_BINDING
from nex_ae_api.semantic_candidates import (
    SemanticCalibrationPolicy,
    SemanticCalibrationRegistry,
    SemanticCandidateStageError,
)

PLAN_CANDIDATE_SCHEMA_VERSION = "p65.plan_candidate.v1"
P7_PLAN_CANDIDATE_SCHEMA_VERSION = "p7.plan_candidate.v1"
PLAN_GENERATION_INPUT_SCHEMA_VERSION = "p65.plan_generation_input.v1"

_TOP_LEVEL_KEYS = {
    "schema_version",
    "suggested_plan_kind",
    "goal",
    "logical_steps",
    "completion_mapping",
    "confidence",
}
_STEP_REQUIRED_KEYS = {
    "step_id",
    "step_type",
    "title",
    "objective",
    "depends_on",
    "capability_hint",
    "completion_criteria",
}
_STEP_OPTIONAL_KEYS = {"delegation"}
_COMPLETION_KEYS = {"criterion_id", "terminal_step_refs"}
_PLAN_KINDS = {"DIRECT", "KNOWN_TEMPLATE", "DYNAMIC"}
_STEP_TYPES = {"LOCAL_CAPABILITY", "AGGREGATE", "REPORT"}
_P7_STEP_TYPES = {*_STEP_TYPES, "DELEGATE_WORK"}
_ACTIVE_PLAN_KINDS = {"DIRECT", "KNOWN_TEMPLATE"}
_CAPABILITY_ID = re.compile(r"^[A-Z][A-Z0-9_]*(\.[A-Z][A-Z0-9_]*)+$")
_STEP_ID = re.compile(r"^S[0-9]{1,3}$")
_CRITERION_ID = re.compile(r"^C[0-9]{1,3}$")
_TRACE_ID = re.compile(r"^[0-9a-f]{32}$")
_EXECUTION_MODES = {
    "GENERAL_ANSWER",
    "GROUNDED_ANSWER",
    "DOCUMENT_SUMMARY",
    "DOCUMENT_GENERATION",
}
_DELEGATION_KEYS = {
    "work_class",
    "required_agent_type",
    "project_scope_ref",
    "result_contract_ref",
    "completion_policy",
}
_DELEGATION_WORK_CLASSES = {
    "QUERY",
    "ANALYSIS",
    "DOCUMENT",
    "BUSINESS_TRANSACTION",
    "COORDINATION",
    "EXPERT_REVIEW",
    "REPORTING",
    "OPERATIONAL",
}
_DELEGATION_AGENT_TYPES = {"CA", "PA", "EA"}
_DELEGATION_COMPLETION_POLICIES = {
    "OWNER_SUBMITS",
    "ALL_ASSIGNEES_SUBMIT",
    "ANY_ASSIGNEE_SUBMITS",
    "ALL_REQUIRED_CHILDREN",
    "MANUAL",
}
_AUTHORITY_KEYS = {
    "approval",
    "approval_authority",
    "authority",
    "authority_ref",
    "capability_version",
    "capability_version_constraint",
    "classification",
    "classification_authority",
    "data_classification",
    "data_classification_authority",
    "exact_capability_version",
    "exact_skill_version",
    "executor_kind",
    "owner",
    "owner_id",
    "owner_subject_id",
    "package_requirement",
    "package_trust",
    "permission",
    "permission_grants",
    "permissions",
    "principal",
    "principal_authority",
    "principal_id",
    "project",
    "project_authority",
    "project_id",
    "project_ref",
    "role",
    "role_bindings",
    "roles",
    "skill_semantic_hash",
    "tenant",
    "tenant_authority",
    "tenant_id",
    "write_authority",
}
_PRIVATE_KEYS = {
    "api_key",
    "credential",
    "hidden_reasoning",
    "model_path",
    "provider_endpoint",
    "provider_url",
    "raw_prompt",
    "secret",
}
_INJECTION_MARKERS = (
    "ignore previous instruction",
    "ignore all previous",
    "ignore the system",
    "reveal system prompt",
    "developer message",
    "jailbreak",
    "이전 지시를 무시",
    "시스템 프롬프트를 공개",
    "개발자 메시지",
)

PlanCandidateStageError = SemanticCandidateStageError
PlanCalibrationPolicy = SemanticCalibrationPolicy
PlanCalibrationRegistry = SemanticCalibrationRegistry


@dataclass(frozen=True)
class PlanCandidateStageResult:
    directive: str
    failure_code: str | None
    candidate_hash: str
    provider_output_sha256: str
    input_context_hash: str
    prompt_provenance: Mapping[str, Any]
    model_provenance: Mapping[str, Any]
    admission_policy_ref: str | None
    selected_threshold: float | None
    candidate: Mapping[str, Any] = field(repr=False)
    agent_plan: Mapping[str, Any] | None = field(default=None, repr=False)


@dataclass(frozen=True)
class LivePlanCandidateService:
    client: AeMoGenerationClient = field(repr=False)
    prompt_store: Any = field(repr=False)
    calibration_registry: PlanCalibrationRegistry = field(
        default_factory=PlanCalibrationRegistry,
        repr=False,
    )

    def generate_and_bind(
        self,
        *,
        work_intent: Mapping[str, Any],
        agent_context: Mapping[str, Any],
        capability_snapshot: Mapping[str, Any],
        request_id: str,
        trace_id: str,
        planning_mode: str,
        agent_plan_id: str,
        agent_plan_version: int = 1,
    ) -> PlanCandidateStageResult:
        selected_mode = _planning_mode(planning_mode)
        selected_request_id = _bounded_text(request_id, "request_id", 200)
        selected_trace_id = _trace_id_value(trace_id)
        normalized_snapshot = _capability_snapshot(capability_snapshot)
        work_projection = _work_intent_projection(work_intent)
        context_projection = _agent_context_projection(
            agent_context,
            work_intent=work_intent,
        )
        if normalized_snapshot["tenant_id"] != context_projection["tenant_id"]:
            raise _request_error(
                "Capability snapshot tenant does not match AgentContext."
            )
        generation_input = {
            "schema_version": PLAN_GENERATION_INPUT_SCHEMA_VERSION,
            "work_intent": work_projection,
            "agent_context_summary": context_projection["summary"],
            "capability_catalog": _capability_catalog(normalized_snapshot),
        }
        input_context_hash = semantic_sha256_hash_ref(generation_input)
        prompt_snapshot = _resolve_prompt_snapshot(
            self.prompt_store,
            user_prompt=canonical_json(generation_input),
            request_id=selected_request_id,
            trace_id=selected_trace_id,
        )

        readiness = self.client.check_required_mode_readiness(
            request_id=selected_request_id,
            trace_id=selected_trace_id,
        )
        policy = self.calibration_registry.select(
            semantic_stage="PLAN",
            model_profile=readiness.model_profile,
            model_ref=readiness.model_ref,
        )
        if selected_mode == "required" and policy is None:
            raise PlanCandidateStageError(
                503,
                "SEMANTIC_CALIBRATION_REQUIRED",
                "Required PLAN mode needs an exact active model calibration policy.",
                retryable=False,
            )

        generation = self.client.generate_candidate(
            semantic_stage="PLAN",
            messages=(
                {"role": "system", "content": prompt_snapshot["rendered_prompt"]},
                {"role": "user", "content": canonical_json(generation_input)},
            ),
            request_id=selected_request_id,
            trace_id=selected_trace_id,
        )
        _require_matching_model(readiness, generation)
        candidate = parse_plan_candidate(generation.output_text)
        candidate_hash = semantic_sha256_hash_ref(candidate)
        prompt_provenance = {
            **prompt_snapshot["provenance"],
            "input_context_hash": input_context_hash,
        }
        model_provenance = {
            "model_profile": generation.model_profile,
            "model_ref": generation.model_ref,
            "deployment_id": generation.deployment_id,
            "mo_generation_id": generation.mo_generation_id,
            "route_id": generation.route_id,
        }
        threshold = policy.minimum_confidence if policy is not None else None
        if threshold is not None and float(candidate["confidence"]) < threshold:
            return _result(
                directive="REPLAN_REQUIRED",
                failure_code="CANDIDATE_LOW_CONFIDENCE",
                candidate=candidate,
                candidate_hash=candidate_hash,
                generation=generation,
                input_context_hash=input_context_hash,
                prompt_provenance=prompt_provenance,
                model_provenance=model_provenance,
                policy=policy,
            )
        if selected_mode == "shadow":
            return _result(
                directive="SHADOW_ONLY",
                failure_code=None,
                candidate=candidate,
                candidate_hash=candidate_hash,
                generation=generation,
                input_context_hash=input_context_hash,
                prompt_provenance=prompt_provenance,
                model_provenance=model_provenance,
                policy=policy,
            )

        agent_plan = bind_plan_candidate(
            candidate=candidate,
            candidate_hash=candidate_hash,
            work_intent=work_intent,
            agent_context=agent_context,
            capability_snapshot=normalized_snapshot,
            prompt_provenance=prompt_provenance,
            model_provenance=model_provenance,
            agent_plan_id=agent_plan_id,
            agent_plan_version=agent_plan_version,
        )
        return _result(
            directive="CONTINUE",
            failure_code=None,
            candidate=candidate,
            candidate_hash=candidate_hash,
            generation=generation,
            input_context_hash=input_context_hash,
            prompt_provenance=prompt_provenance,
            model_provenance=model_provenance,
            policy=policy,
            agent_plan=agent_plan,
        )


def parse_plan_candidate(output_text: str) -> dict[str, Any]:
    try:
        value = json.loads(
            output_text,
            parse_constant=lambda constant: (_raise_json_constant(constant)),
        )
    except (TypeError, ValueError) as exc:
        raise PlanCandidateStageError(
            422,
            "CANDIDATE_JSON_INVALID",
            "PLAN provider output is not strict JSON.",
        ) from exc
    if not isinstance(value, dict):
        raise _schema_error("PLAN candidate must be a JSON object.")
    _reject_authority_and_private_fields(value)
    if set(value) != _TOP_LEVEL_KEYS:
        raise _schema_error("PLAN candidate fields do not match the contract.")
    schema_version = value.get("schema_version")
    if schema_version not in {
        PLAN_CANDIDATE_SCHEMA_VERSION,
        P7_PLAN_CANDIDATE_SCHEMA_VERSION,
    }:
        raise _schema_error("PLAN candidate schema version is unsupported.")
    plan_kind = value.get("suggested_plan_kind")
    if plan_kind not in _PLAN_KINDS:
        raise _schema_error("PLAN candidate plan kind is invalid.")
    normalized = {
        "schema_version": schema_version,
        "suggested_plan_kind": plan_kind,
        "goal": _candidate_text(value.get("goal"), "goal", 1000),
        "logical_steps": _logical_steps(
            value.get("logical_steps"), schema_version=str(schema_version)
        ),
        "completion_mapping": _completion_mapping(
            value.get("completion_mapping")
        ),
        "confidence": _confidence(value.get("confidence"), "confidence"),
    }
    _validate_dependency_graph(normalized)
    _reject_prompt_injection(normalized)
    return normalized


def bind_plan_candidate(
    *,
    candidate: Mapping[str, Any],
    candidate_hash: str,
    work_intent: Mapping[str, Any],
    agent_context: Mapping[str, Any],
    capability_snapshot: Mapping[str, Any],
    prompt_provenance: Mapping[str, Any],
    model_provenance: Mapping[str, Any],
    agent_plan_id: str,
    agent_plan_version: int = 1,
) -> dict[str, Any]:
    normalized_candidate = parse_plan_candidate(canonical_json(candidate))
    try:
        normalized_candidate_hash = validate_hash_ref(candidate_hash)
    except ValueError as exc:
        raise _request_error("PLAN candidate hash is invalid.") from exc
    if normalized_candidate_hash != semantic_sha256_hash_ref(normalized_candidate):
        raise _request_error("PLAN candidate hash does not match its content.")
    snapshot = _capability_snapshot(capability_snapshot)
    work_projection = _work_intent_projection(work_intent)
    context_projection = _agent_context_projection(
        agent_context,
        work_intent=work_intent,
    )
    if snapshot["tenant_id"] != context_projection["tenant_id"]:
        raise _request_error("Capability snapshot tenant does not match AgentContext.")
    if normalized_candidate["goal"] != work_projection["goal"]:
        raise _schema_error("PLAN candidate goal must match the canonical WorkIntent.")
    plan_kind = normalized_candidate["suggested_plan_kind"]
    if plan_kind not in _ACTIVE_PLAN_KINDS:
        raise _schema_error("PLAN candidate kind is not active in the P6.5 runtime.")
    if plan_kind == "DIRECT" and len(normalized_candidate["logical_steps"]) != 1:
        raise _schema_error("DIRECT PLAN candidate must contain exactly one step.")

    expected_criteria = {
        item["criterion_id"]: item for item in work_projection["completion_criteria"]
    }
    completion_mapping = {
        item["criterion_id"]: item["terminal_step_refs"]
        for item in normalized_candidate["completion_mapping"]
    }
    if set(completion_mapping) != set(expected_criteria):
        raise _dependency_error(
            "PLAN completion mapping must cover the exact WorkIntent criteria."
        )

    steps = [
        _bind_step(
            step,
            capability_snapshot=snapshot,
            work_intent=work_intent,
            agent_context=agent_context,
        )
        for step in normalized_candidate["logical_steps"]
    ]
    plan = {
        "schema_version": "1.1",
        "agent_plan_id": _uuid_text(agent_plan_id, "agent_plan_id"),
        "agent_plan_version": _bounded_int(
            agent_plan_version, "agent_plan_version", 1, 99
        ),
        "execution_id": work_projection["execution_id"],
        "work_intent_ref": _versioned_ref(
            work_intent.get("work_intent_id"),
            work_intent.get("intent_revision"),
            work_intent.get("intent_hash"),
        ),
        "agent_context_ref": _versioned_ref(
            agent_context.get("context_id"),
            agent_context.get("context_generation"),
            agent_context.get("context_hash"),
        ),
        "capability_snapshot_ref": _versioned_ref(
            snapshot.get("capability_snapshot_id"),
            snapshot.get("snapshot_version"),
            snapshot.get("snapshot_hash"),
        ),
        "plan_kind": plan_kind,
        "goal": work_projection["goal"],
        "completion_criteria": [
            {
                "criterion_id": criterion_id,
                "description": criterion["description"],
                "required": criterion["required"],
                "required_terminal_step_refs": completion_mapping[criterion_id],
            }
            for criterion_id, criterion in expected_criteria.items()
        ],
        "planning_constraints": {
            "max_plan_steps": 12,
            "max_delegation_depth": (
                1
                if any(
                    step["step_type"] == "DELEGATE_WORK" for step in steps
                )
                else 0
            ),
            "max_parallel_steps": 1,
        },
        "steps": steps,
        "planner_provenance": {
            "builder_type": "DYNAMIC_BUILDER",
            "route_decision_ref": (
                f"semantic-candidate://plan/{normalized_candidate_hash}"
            ),
            "template_ref": None,
            "input_context_hash": context_projection["context_hash"],
            "prompt_binding_key": _provenance_text(
                prompt_provenance, "prompt_binding_key", 200
            ),
            "prompt_template_version_id": _uuid_text(
                prompt_provenance.get("prompt_template_version_id"),
                "prompt_template_version_id",
            ),
            "prompt_content_sha256": _provenance_digest(
                prompt_provenance, "prompt_content_sha256"
            ),
            "rendered_prompt_hash": _provenance_digest(
                prompt_provenance, "rendered_prompt_hash"
            ),
            "model_profile": _provenance_text(
                model_provenance, "model_profile", 128
            ),
            "model_ref": _provenance_text(model_provenance, "model_ref", 256),
        },
    }
    plan["plan_hash"] = semantic_sha256_hash_ref(plan)
    try:
        return validate_agent_plan_contract(plan)
    except AgentPlanError as exc:
        raise _schema_error("Bound PLAN candidate is not a canonical AgentPlan.") from exc


def _logical_steps(
    value: object, *, schema_version: str
) -> list[dict[str, Any]]:
    records = _bounded_list(value, "logical_steps", 12, require_one=True)
    normalized: list[dict[str, Any]] = []
    step_ids: set[str] = set()
    for record in records:
        if (
            not isinstance(record, dict)
            or not _STEP_REQUIRED_KEYS.issubset(record)
            or not set(record).issubset(_STEP_REQUIRED_KEYS | _STEP_OPTIONAL_KEYS)
        ):
            raise _schema_error("PLAN logical step fields are invalid.")
        step_id = record.get("step_id")
        if not isinstance(step_id, str) or _STEP_ID.fullmatch(step_id) is None:
            raise _schema_error("PLAN logical step ID is invalid.")
        if step_id in step_ids:
            raise _schema_error("PLAN logical step IDs must be unique.")
        step_ids.add(step_id)
        step_type = record.get("step_type")
        allowed_types = (
            _P7_STEP_TYPES
            if schema_version == P7_PLAN_CANDIDATE_SCHEMA_VERSION
            else _STEP_TYPES
        )
        if step_type not in allowed_types:
            raise _schema_error("PLAN logical step type is invalid.")
        capability_hint = record.get("capability_hint")
        if step_type in {"LOCAL_CAPABILITY", "DELEGATE_WORK"}:
            if (
                not isinstance(capability_hint, str)
                or len(capability_hint) > 160
                or _CAPABILITY_ID.fullmatch(capability_hint) is None
            ):
                raise _schema_error(
                    f"PLAN {step_type} requires a valid capability hint."
                )
        elif capability_hint is not None:
            raise _schema_error(
                "PLAN REPORT and AGGREGATE cannot carry capability hints."
            )
        delegation = record.get("delegation")
        if step_type == "DELEGATE_WORK":
            delegation = _candidate_delegation(delegation)
        elif delegation is not None:
            raise _schema_error("Only DELEGATE_WORK may carry delegation metadata.")
        normalized.append(
            {
                "step_id": step_id,
                "step_type": step_type,
                "title": _candidate_text(record.get("title"), "step title", 160),
                "objective": _candidate_text(
                    record.get("objective"), "step objective", 700
                ),
                "depends_on": _step_ref_list(
                    record.get("depends_on"), "step dependencies", 11, False
                ),
                "capability_hint": capability_hint,
                "completion_criteria": _text_list(
                    record.get("completion_criteria"),
                    "step completion criteria",
                    maximum=8,
                    text_maximum=500,
                    require_one=True,
                ),
                **({"delegation": delegation} if delegation is not None else {}),
            }
        )
    return normalized


def _completion_mapping(value: object) -> list[dict[str, Any]]:
    records = _bounded_list(value, "completion_mapping", 16, require_one=True)
    normalized: list[dict[str, Any]] = []
    criterion_ids: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or set(record) != _COMPLETION_KEYS:
            raise _schema_error("PLAN completion mapping fields are invalid.")
        criterion_id = record.get("criterion_id")
        if (
            not isinstance(criterion_id, str)
            or _CRITERION_ID.fullmatch(criterion_id) is None
            or criterion_id in criterion_ids
        ):
            raise _schema_error("PLAN completion criterion ID is invalid or duplicate.")
        criterion_ids.add(criterion_id)
        normalized.append(
            {
                "criterion_id": criterion_id,
                "terminal_step_refs": _step_ref_list(
                    record.get("terminal_step_refs"),
                    "completion terminal refs",
                    12,
                    True,
                ),
            }
        )
    return normalized


def _validate_dependency_graph(candidate: Mapping[str, Any]) -> None:
    steps = candidate["logical_steps"]
    step_ids = {step["step_id"] for step in steps}
    incoming: dict[str, set[str]] = {}
    dependents: dict[str, set[str]] = {step_id: set() for step_id in step_ids}
    for step in steps:
        step_id = step["step_id"]
        dependencies = set(step["depends_on"])
        if step_id in dependencies or not dependencies.issubset(step_ids):
            raise _dependency_error(
                "PLAN dependencies must reference other existing steps."
            )
        incoming[step_id] = dependencies
        for dependency in dependencies:
            dependents[dependency].add(step_id)
        if step["step_type"] == "REPORT" and not dependencies:
            raise _dependency_error("PLAN REPORT requires an earlier source step.")
    ready = sorted(step_id for step_id, deps in incoming.items() if not deps)
    order: list[str] = []
    while ready:
        if len(ready) != 1:
            raise _dependency_error("PLAN parallel width exceeds one.")
        current = ready.pop()
        order.append(current)
        for dependent in sorted(dependents[current]):
            incoming[dependent].discard(current)
            if not incoming[dependent]:
                ready.append(dependent)
        ready.sort()
    if len(order) != len(step_ids):
        raise _dependency_error("PLAN dependency graph contains a cycle.")
    if [step["step_id"] for step in steps] != order:
        raise _dependency_error("PLAN logical steps must be topologically ordered.")
    terminals = step_ids - {
        dependency for step in steps for dependency in step["depends_on"]
    }
    for step in steps:
        if step["step_type"] == "REPORT" and step["step_id"] not in terminals:
            raise _dependency_error("PLAN REPORT must be terminal.")
    for mapping in candidate["completion_mapping"]:
        if not set(mapping["terminal_step_refs"]).issubset(terminals):
            raise _dependency_error(
                "PLAN completion mapping must reference actual terminal steps."
            )


def _bind_step(
    step: Mapping[str, Any],
    *,
    capability_snapshot: Mapping[str, Any],
    work_intent: Mapping[str, Any],
    agent_context: Mapping[str, Any],
) -> dict[str, Any]:
    step_type = step["step_type"]
    if step_type == "AGGREGATE":
        raise _capability_error(
            "AGGREGATE is not registered in the current P5 PlanValidation profile."
        )
    if step_type == "LOCAL_CAPABILITY":
        matches = [
            item
            for item in capability_snapshot["capabilities"]
            if item["capability_id"] == step["capability_hint"]
            and "LOCAL_CAPABILITY" in item["allowed_logical_step_types"]
        ]
        if len(matches) != 1:
            raise _capability_error(
                "PLAN capability hint is unavailable or exact-version ambiguous."
            )
        capability = matches[0]
        required_capability = capability["capability_id"]
        version = capability["capability_version"]
        aggregation = None
        report = None
        delegation = None
        output_contract_ref = capability["output_contract_ref"]
    elif step_type == "DELEGATE_WORK":
        metadata = _candidate_delegation(step.get("delegation"))
        _require_project_scope(agent_context, metadata["project_scope_ref"])
        required_capability = step["capability_hint"]
        version = None
        aggregation = None
        report = None
        delegation = metadata
        output_contract_ref = metadata["result_contract_ref"]
    else:
        try:
            capability = capability_by_exact_version(
                capability_snapshot,
                REPORT_CAPABILITY_ID,
                CAPABILITY_VERSION,
            )
        except CapabilitySnapshotError as exc:
            raise _capability_error(
                "The exact deterministic report capability is unavailable."
            ) from exc
        if "REPORT" not in capability["allowed_logical_step_types"]:
            raise _capability_error(
                "The exact report capability does not admit REPORT steps."
            )
        required_capability = None
        version = None
        aggregation = None
        report = {
            "report_kind": _report_kind(work_intent),
            "source_step_refs": list(step["depends_on"]),
        }
        delegation = None
        output_contract_ref = capability["output_contract_ref"]
    input_bindings = [
        {
            "target_name": f"source_{index}",
            "source_type": "STEP_OUTPUT",
            "source_ref": dependency,
            "json_pointer": "$",
        }
        for index, dependency in enumerate(step["depends_on"], start=1)
    ]
    return {
        "step_id": step["step_id"],
        "step_type": step_type,
        "title": step["title"],
        "objective": step["objective"],
        "depends_on": list(step["depends_on"]),
        "required_capability": required_capability,
        "capability_version_constraint": version,
        "input_bindings": input_bindings,
        "output_contract_ref": output_contract_ref,
        "completion_criteria": list(step["completion_criteria"]),
        "aggregation": aggregation,
        "report": report,
        **({"delegation": delegation} if delegation is not None else {}),
    }


def _candidate_delegation(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _DELEGATION_KEYS:
        raise _schema_error("PLAN delegation metadata is invalid.")
    work_class = value.get("work_class")
    agent_type = value.get("required_agent_type")
    completion_policy = value.get("completion_policy")
    if work_class not in _DELEGATION_WORK_CLASSES:
        raise _schema_error("PLAN delegation work class is invalid.")
    if agent_type not in _DELEGATION_AGENT_TYPES:
        raise _schema_error("PLAN delegation agent type is invalid.")
    if completion_policy not in _DELEGATION_COMPLETION_POLICIES:
        raise _schema_error("PLAN delegation completion policy is invalid.")
    return {
        "work_class": work_class,
        "required_agent_type": agent_type,
        "project_scope_ref": _candidate_text(
            value.get("project_scope_ref"), "project_scope_ref", 160
        ),
        "result_contract_ref": _candidate_text(
            value.get("result_contract_ref"), "result_contract_ref", 256
        ),
        "completion_policy": completion_policy,
    }


def _require_project_scope(
    agent_context: Mapping[str, Any], project_scope_ref: str
) -> None:
    project = agent_context.get("project_ref")
    if (
        not isinstance(project, Mapping)
        or project.get("resource_type") != "PROJECT"
        or project.get("resource_id") != project_scope_ref
    ):
        raise _schema_error(
            "PLAN delegation project must match the trusted AgentContext project."
        )


def _work_intent_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("schema_version") != "1.1":
        raise _request_error("work_intent must use schema version 1.1.")
    execution_id = _uuid_text(value.get("execution_id"), "work_intent.execution_id")
    _uuid_text(value.get("work_intent_id"), "work_intent.work_intent_id")
    revision = _bounded_int(value.get("intent_revision"), "intent_revision", 1, 99)
    try:
        intent_hash = validate_hash_ref(value.get("intent_hash"))
    except ValueError as exc:
        raise _request_error("work_intent intent_hash is invalid.") from exc
    mode = value.get("compatibility_execution_mode")
    if mode not in _EXECUTION_MODES:
        raise _request_error("work_intent execution mode is unsupported.")
    criteria = value.get("completion_criteria")
    if not isinstance(criteria, list) or not 1 <= len(criteria) <= 16:
        raise _request_error("work_intent completion criteria are invalid.")
    normalized_criteria: list[dict[str, Any]] = []
    criterion_ids: set[str] = set()
    for item in criteria:
        if not isinstance(item, Mapping):
            raise _request_error("work_intent completion criterion is invalid.")
        criterion_id = item.get("criterion_id")
        if (
            not isinstance(criterion_id, str)
            or _CRITERION_ID.fullmatch(criterion_id) is None
            or criterion_id in criterion_ids
        ):
            raise _request_error("work_intent completion criterion ID is invalid.")
        criterion_ids.add(criterion_id)
        if not isinstance(item.get("required"), bool):
            raise _request_error("work_intent completion required flag is invalid.")
        normalized_criteria.append(
            {
                "criterion_id": criterion_id,
                "description": _bounded_text(
                    item.get("description"), "completion description", 500
                ),
                "required": item["required"],
            }
        )
    return {
        "execution_id": execution_id,
        "intent_revision": revision,
        "intent_hash": intent_hash,
        "intent_label": _bounded_text(
            value.get("intent_label"), "intent_label", 160
        ),
        "execution_mode": mode,
        "goal": _bounded_text(value.get("goal"), "goal", 1000),
        "work_class": _bounded_text(value.get("work_class"), "work_class", 64),
        "completion_criteria": normalized_criteria,
    }


def _agent_context_projection(
    value: Mapping[str, Any],
    *,
    work_intent: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("schema_version") != "1.1":
        raise _request_error("agent_context must use schema version 1.1.")
    execution_id = _uuid_text(value.get("execution_id"), "agent_context.execution_id")
    if execution_id != work_intent.get("execution_id"):
        raise _request_error("AgentContext execution does not match WorkIntent.")
    expected_work_ref = _versioned_ref(
        work_intent.get("work_intent_id"),
        work_intent.get("intent_revision"),
        work_intent.get("intent_hash"),
    )
    if value.get("work_intent_ref") != expected_work_ref:
        raise _request_error("AgentContext does not reference the exact WorkIntent.")
    _uuid_text(value.get("context_id"), "agent_context.context_id")
    _bounded_int(value.get("context_generation"), "context_generation", 1, 9999)
    try:
        context_hash = validate_hash_ref(value.get("context_hash"))
    except ValueError as exc:
        raise _request_error("agent_context context_hash is invalid.") from exc
    identity = value.get("identity")
    if not isinstance(identity, Mapping):
        raise _request_error("agent_context identity is invalid.")
    tenant_id = _bounded_text(identity.get("tenant_id"), "tenant_id", 128)
    resolved_entities = value.get("resolved_entities")
    retrieval_refs = value.get("retrieval_refs")
    evidence_refs = value.get("evidence_refs")
    conflicts = value.get("conflicts")
    degradations = value.get("degradations")
    for field_name, records, maximum in (
        ("resolved_entities", resolved_entities, 32),
        ("retrieval_refs", retrieval_refs, 64),
        ("evidence_refs", evidence_refs, 64),
        ("conflicts", conflicts, 32),
        ("degradations", degradations, 32),
    ):
        if not isinstance(records, list) or len(records) > maximum:
            raise _request_error(f"agent_context {field_name} is invalid.")
    entity_types = sorted(
        {
            str(item.get("entity_type"))
            for item in resolved_entities
            if isinstance(item, Mapping) and item.get("entity_type")
        }
    )
    project = value.get("project_ref")
    project_scope_ref = None
    if isinstance(project, Mapping) and project.get("resource_type") == "PROJECT":
        project_scope_ref = _bounded_text(
            project.get("resource_id"), "project_scope_ref", 160
        )
    return {
        "tenant_id": tenant_id,
        "context_hash": context_hash,
        "summary": {
            "context_hash": context_hash,
            "resolved_entity_types": entity_types,
            "retrieval_available": bool(retrieval_refs),
            "evidence_available": bool(evidence_refs),
            "conflict_count": len(conflicts),
            "degradation_count": len(degradations),
            **(
                {"project_scope_ref": project_scope_ref}
                if project_scope_ref is not None
                else {}
            ),
        },
    }


def _capability_snapshot(value: Mapping[str, Any]) -> dict[str, Any]:
    try:
        return validate_capability_snapshot_contract(value)
    except (CapabilitySnapshotError, TypeError, ValueError) as exc:
        raise _request_error("capability_snapshot is invalid.") from exc


def _capability_catalog(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for capability in snapshot["capabilities"]:
        capability_id = capability["capability_id"]
        existing = records.setdefault(
            capability_id,
            {
                "capability_id": capability_id,
                "allowed_logical_step_types": [],
                "operation_semantics": [],
            },
        )
        existing["allowed_logical_step_types"] = sorted(
            set(existing["allowed_logical_step_types"])
            | set(capability["allowed_logical_step_types"])
        )
        existing["operation_semantics"] = sorted(
            set(existing["operation_semantics"])
            | {capability["operation_semantics"]}
        )
    return [records[key] for key in sorted(records)]


def _resolve_prompt_snapshot(
    store: Any,
    *,
    user_prompt: str,
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    try:
        rendered = render_prompt_from_binding(
            store,
            binding_key=AE_PLAN_BUILDER_BINDING,
            variables={},
            request_id=request_id,
            trace_id=trace_id,
            user_prompt=user_prompt,
        )
        event = rendered["render_event"]
        version = store.get_template_version(event["prompt_template_version_id"])
    except (AttributeError, KeyError, PromptRegistryError) as exc:
        raise PlanCandidateStageError(
            503,
            "PROVIDER_NOT_READY",
            "The exact PLAN prompt binding is not ready.",
        ) from exc
    if not isinstance(version, dict) or version.get("status") != "ACTIVE":
        raise PlanCandidateStageError(
            503,
            "PROVIDER_NOT_READY",
            "The captured PLAN prompt version is not active.",
        )
    if (
        event.get("binding_key") != AE_PLAN_BUILDER_BINDING
        or event.get("purpose") != "plan_builder"
        or version.get("purpose") != "plan_builder"
        or version.get("role") != "system"
        or version.get("model_capability") != "generation"
    ):
        raise _schema_error("The captured PLAN prompt binding is incompatible.")
    try:
        content_sha256 = validate_sha256_digest(version.get("content_sha256"))
        rendered_hash = validate_sha256_digest(event.get("rendered_prompt_hash"))
    except ValueError as exc:
        raise _schema_error("The captured PLAN prompt provenance digest is invalid.") from exc
    return {
        "rendered_prompt": _bounded_text(
            rendered.get("rendered_prompt"), "rendered_prompt", 16_384
        ),
        "provenance": {
            "prompt_binding_id": _bounded_text(
                event.get("prompt_binding_id"), "prompt_binding_id", 64
            ),
            "prompt_binding_key": AE_PLAN_BUILDER_BINDING,
            "prompt_template_version_id": _bounded_text(
                event.get("prompt_template_version_id"),
                "prompt_template_version_id",
                64,
            ),
            "prompt_template_version": _bounded_text(
                version.get("version"), "prompt_template_version", 64
            ),
            "prompt_content_sha256": content_sha256,
            "rendered_prompt_hash": rendered_hash,
        },
    }


def _require_matching_model(
    readiness: AeMoGenerationReadiness,
    generation: AeMoGenerationResult,
) -> None:
    if (
        generation.model_profile != readiness.model_profile
        or generation.model_ref != readiness.model_ref
        or generation.deployment_id != readiness.deployment_id
        or generation.route_id != readiness.route_id
    ):
        raise PlanCandidateStageError(
            502,
            "PROVIDER_RESPONSE_INVALID",
            "MO generation lineage changed after PLAN readiness selection.",
        )


def _result(
    *,
    directive: str,
    failure_code: str | None,
    candidate: Mapping[str, Any],
    candidate_hash: str,
    generation: AeMoGenerationResult,
    input_context_hash: str,
    prompt_provenance: Mapping[str, Any],
    model_provenance: Mapping[str, Any],
    policy: SemanticCalibrationPolicy | None,
    agent_plan: Mapping[str, Any] | None = None,
) -> PlanCandidateStageResult:
    return PlanCandidateStageResult(
        directive=directive,
        failure_code=failure_code,
        candidate_hash=candidate_hash,
        provider_output_sha256=generation.provider_output_sha256,
        input_context_hash=input_context_hash,
        prompt_provenance=dict(prompt_provenance),
        model_provenance=dict(model_provenance),
        admission_policy_ref=policy.policy_ref if policy is not None else None,
        selected_threshold=policy.minimum_confidence if policy is not None else None,
        candidate=dict(candidate),
        agent_plan=dict(agent_plan) if agent_plan is not None else None,
    )


def _report_kind(work_intent: Mapping[str, Any]) -> str:
    return (
        "ARTIFACT"
        if work_intent.get("compatibility_execution_mode") == "DOCUMENT_GENERATION"
        else "INTERACTIVE_RESPONSE"
    )


def _versioned_ref(identity: object, version: object, hash_ref: object) -> dict[str, Any]:
    try:
        normalized_hash = validate_hash_ref(hash_ref)
    except ValueError as exc:
        raise _request_error("Versioned source hash is invalid.") from exc
    return {
        "id": _uuid_text(identity, "versioned_ref.id"),
        "version": _bounded_int(version, "versioned_ref.version", 1, 9999),
        "hash": normalized_hash,
    }


def _provenance_text(
    value: Mapping[str, Any], field_name: str, maximum: int
) -> str:
    return _bounded_text(value.get(field_name), field_name, maximum)


def _provenance_digest(value: Mapping[str, Any], field_name: str) -> str:
    try:
        return validate_sha256_digest(value.get(field_name))
    except ValueError as exc:
        raise _request_error(f"{field_name} is invalid.") from exc


def _step_ref_list(
    value: object,
    field_name: str,
    maximum: int,
    require_one: bool,
) -> list[str]:
    records = _bounded_list(value, field_name, maximum, require_one=require_one)
    if (
        any(not isinstance(item, str) or _STEP_ID.fullmatch(item) is None for item in records)
        or len(set(records)) != len(records)
    ):
        raise _schema_error(f"PLAN {field_name} is invalid.")
    return list(records)


def _text_list(
    value: object,
    field_name: str,
    *,
    maximum: int,
    text_maximum: int,
    require_one: bool,
) -> list[str]:
    records = _bounded_list(value, field_name, maximum, require_one=require_one)
    normalized = [
        _candidate_text(item, field_name, text_maximum) for item in records
    ]
    if len(set(normalized)) != len(normalized):
        raise _schema_error(f"PLAN {field_name} must be unique.")
    return normalized


def _bounded_list(
    value: object,
    field_name: str,
    maximum: int,
    *,
    require_one: bool,
) -> list[Any]:
    if not isinstance(value, list):
        raise _schema_error(f"PLAN {field_name} must be an array.")
    if (require_one and not value) or len(value) > maximum:
        raise _bounds_error(f"PLAN {field_name} item count is invalid.")
    return value


def _confidence(value: object, field_name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not 0.0 <= float(value) <= 1.0
    ):
        raise _schema_error(f"PLAN {field_name} must be between zero and one.")
    return float(value)


def _reject_authority_and_private_fields(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).casefold()
            if normalized in _AUTHORITY_KEYS:
                raise PlanCandidateStageError(
                    422,
                    "CANDIDATE_AUTHORITY_VIOLATION",
                    "PLAN candidate contains an authority-bearing field.",
                )
            if normalized in _PRIVATE_KEYS:
                raise PlanCandidateStageError(
                    422,
                    "CANDIDATE_PRIVATE_DATA_VIOLATION",
                    "PLAN candidate contains a private configuration field.",
                )
            _reject_authority_and_private_fields(item)
    elif isinstance(value, list):
        for item in value:
            _reject_authority_and_private_fields(item)


def _reject_prompt_injection(value: object) -> None:
    if isinstance(value, Mapping):
        values = value.values()
    elif isinstance(value, list):
        values = value
    else:
        values = ()
        if isinstance(value, str):
            normalized = value.casefold()
            if any(marker in normalized for marker in _INJECTION_MARKERS):
                raise PlanCandidateStageError(
                    422,
                    "PROMPT_INJECTION_OR_POLICY_BLOCK",
                    "PLAN candidate contains prompt-control language.",
                )
    for item in values:
        _reject_prompt_injection(item)


def _planning_mode(value: object) -> str:
    if not isinstance(value, str) or value.casefold() not in {"shadow", "required"}:
        raise _request_error("PLAN candidate stage requires shadow or required mode.")
    return value.casefold()


def _trace_id_value(value: object) -> str:
    if not isinstance(value, str) or _TRACE_ID.fullmatch(value) is None:
        raise _request_error("trace_id must be 32 lowercase hexadecimal characters.")
    return value


def _uuid_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise _request_error(f"{field_name} must be a UUID string.")
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise _request_error(f"{field_name} must be a UUID string.") from exc
    if str(parsed) != value:
        raise _request_error(f"{field_name} must be a canonical UUID string.")
    return value


def _bounded_int(value: object, field_name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise _request_error(f"{field_name} is outside its supported range.")
    return value


def _bounded_text(value: object, field_name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise _request_error(f"{field_name} must be a bounded non-empty string.")
    return value.strip()


def _candidate_text(value: object, field_name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _schema_error(f"PLAN {field_name} must be non-empty text.")
    if len(value) > maximum:
        raise _bounds_error(f"PLAN {field_name} exceeds its bound.")
    return value.strip()


def _raise_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _schema_error(detail: str) -> PlanCandidateStageError:
    return PlanCandidateStageError(422, "CANDIDATE_SCHEMA_INVALID", detail)


def _capability_error(detail: str) -> PlanCandidateStageError:
    return PlanCandidateStageError(422, "CANDIDATE_CAPABILITY_UNKNOWN", detail)


def _dependency_error(detail: str) -> PlanCandidateStageError:
    return PlanCandidateStageError(422, "CANDIDATE_DEPENDENCY_INVALID", detail)


def _bounds_error(detail: str) -> PlanCandidateStageError:
    return PlanCandidateStageError(422, "CANDIDATE_BOUNDS_EXCEEDED", detail)


def _request_error(detail: str) -> PlanCandidateStageError:
    return PlanCandidateStageError(400, "PLAN_STAGE_REQUEST_INVALID", detail)
