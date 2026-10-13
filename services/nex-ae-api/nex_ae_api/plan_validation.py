from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_ae_api.agent_plans import validate_agent_plan_contract
from nex_ae_api.planning_capabilities import (
    CAPABILITY_VERSION,
    REPORT_CAPABILITY_ID,
    CapabilitySnapshotError,
    capability_by_exact_version,
    validate_capability_snapshot_contract,
)

PLAN_VALIDATION_SCHEMA_VERSION = "1.1"
VALIDATOR_VERSION = "p5.1"
MAX_AUTO_REPLAN = 0
_STEP_ID = re.compile(r"^S[0-9]{1,3}$")
_ISSUE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{2,127}$")


@dataclass(frozen=True)
class ValidationRuntimeOutcome:
    runtime_directive: str
    agent_execution_state: str
    agent_execution_phase: str
    compile_allowed: bool
    auto_replan_allowed: bool = False


RUNTIME_OUTCOMES: dict[str, ValidationRuntimeOutcome] = {
    "VALID": ValidationRuntimeOutcome(
        "PROCEED_TO_COMPILE", "RUNNING", "PLAN_COMPILE", True
    ),
    "CLARIFICATION_REQUIRED": ValidationRuntimeOutcome(
        "WAIT_FOR_INPUT", "WAITING_INPUT", "PLAN_VALIDATE", False
    ),
    "REPLAN_REQUIRED": ValidationRuntimeOutcome(
        "BLOCK_REPLAN_REQUIRED", "BLOCKED", "PLAN_VALIDATE", False
    ),
    "CONTEXT_REFRESH_REQUIRED": ValidationRuntimeOutcome(
        "BLOCK_CONTEXT_REFRESH_REQUIRED", "BLOCKED", "PLAN_VALIDATE", False
    ),
    "BLOCKED": ValidationRuntimeOutcome(
        "BLOCK_EXECUTION", "BLOCKED", "PLAN_VALIDATE", False
    ),
    "INVALID_TERMINAL": ValidationRuntimeOutcome(
        "FAIL_VALIDATION", "FAILED", "PLAN_VALIDATE", False
    ),
    "RETRYABLE_VALIDATION_FAILURE": ValidationRuntimeOutcome(
        "RETRY_VALIDATION_BOUNDED", "RUNNING", "PLAN_VALIDATE", False
    ),
}


@dataclass(frozen=True)
class PlanValidationError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


def runtime_outcome_for_status(status: str) -> ValidationRuntimeOutcome:
    try:
        return RUNTIME_OUTCOMES[status]
    except KeyError as exc:
        raise _invalid("PlanValidation status is unsupported.") from exc


def validate_agent_plan(
    *,
    agent_plan: Mapping[str, Any],
    work_intent: Mapping[str, Any],
    agent_context: Mapping[str, Any],
    capability_snapshot: Mapping[str, Any],
    validation_result_id: str | None = None,
    validated_at: str | None = None,
    id_factory: Callable[[], str] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    plan = validate_agent_plan_contract(agent_plan)
    snapshot = validate_capability_snapshot_contract(capability_snapshot)
    now = _required_datetime(
        "validated_at",
        validated_at
        or (clock or (lambda: datetime.now(UTC)))()
        .astimezone(UTC)
        .isoformat()
        .replace("+00:00", "Z"),
    )

    status, issues, order = _evaluate_plan(
        plan=plan,
        work_intent=work_intent,
        agent_context=agent_context,
        capability_snapshot=snapshot,
    )
    return build_plan_validation_result(
        agent_plan=plan,
        agent_context=agent_context,
        status=status,
        issues=issues,
        topological_step_order=order,
        validation_result_id=validation_result_id
        or (id_factory or (lambda: str(uuid4())))(),
        validated_at=now,
    )


def build_plan_validation_result(
    *,
    agent_plan: Mapping[str, Any],
    agent_context: Mapping[str, Any],
    status: str,
    issues: Sequence[Mapping[str, Any]],
    topological_step_order: Sequence[str],
    validation_result_id: str,
    validated_at: str,
    validator_version: str = VALIDATOR_VERSION,
) -> dict[str, Any]:
    outcome = runtime_outcome_for_status(status)
    result: dict[str, Any] = {
        "schema_version": PLAN_VALIDATION_SCHEMA_VERSION,
        "validation_result_id": _required_uuid(
            "validation_result_id", validation_result_id
        ),
        "agent_plan_ref": _versioned_ref(
            agent_plan.get("agent_plan_id"),
            agent_plan.get("agent_plan_version"),
            agent_plan.get("plan_hash"),
        ),
        "execution_id": _required_uuid(
            "execution_id", agent_plan.get("execution_id")
        ),
        "validator_version": _required_text(
            "validator_version", validator_version, 64
        ),
        "status": status,
        "runtime_directive": outcome.runtime_directive,
        "validated_context_ref": _versioned_ref(
            agent_context.get("context_id"),
            agent_context.get("context_generation"),
            agent_context.get("context_hash"),
        ),
        "issues": [_normalize_issue(item) for item in issues],
        "topological_step_order": _normalize_step_order(topological_step_order),
        "validated_at": _required_datetime("validated_at", validated_at),
    }
    if status == "VALID" and result["issues"] and any(
        item["severity"] == "ERROR" for item in result["issues"]
    ):
        raise _invalid("VALID result cannot contain ERROR issues.")
    if status != "VALID" and not result["issues"]:
        raise _invalid("Non-VALID result requires at least one issue.")
    result["result_hash"] = semantic_sha256_hash_ref(result)
    return result


class SqlAlchemyPlanValidationRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save_and_apply_runtime(
        self,
        *,
        tenant_id: str,
        result: Mapping[str, Any],
        expected_execution_version: int,
    ) -> dict[str, Any]:
        tenant_id = _required_text("tenant_id", tenant_id, 128)
        normalized = validate_plan_validation_result(result)
        expected_execution_version = _bounded_int(
            "expected_execution_version", expected_execution_version, 1, 2**31 - 1
        )
        outcome = runtime_outcome_for_status(normalized["status"])
        params = {
            "tenant_id": tenant_id,
            "validation_result_id": normalized["validation_result_id"],
            "agent_plan_id": normalized["agent_plan_ref"]["id"],
            "agent_plan_version": normalized["agent_plan_ref"]["version"],
            "agent_execution_id": normalized["execution_id"],
            "status": normalized["status"],
            "runtime_directive": normalized["runtime_directive"],
            "result_hash": normalized["result_hash"],
            "result_json": _canonical_json(normalized),
            "validated_at": normalized["validated_at"],
            "expected_execution_version": expected_execution_version,
            "execution_state": outcome.agent_execution_state,
            "execution_phase": outcome.agent_execution_phase,
        }
        try:
            with self._session_factory() as session:
                _require_exact_persisted_lineage(session, tenant_id, normalized)
                inserted = session.execute(
                    text(_validation_insert_sql(_dialect_name(session))), params
                )
                saved = _load_validation(
                    session, tenant_id, normalized["validation_result_id"]
                )
                if saved is None:
                    raise PlanValidationError(
                        "ae.plan_validation_write_conflict",
                        "PlanValidationResult could not be reloaded.",
                        True,
                    )
                if saved != normalized:
                    raise PlanValidationError(
                        "ae.plan_validation_immutable_conflict",
                        "PlanValidationResult identity exists with different content.",
                    )
                if int(inserted.rowcount or 0) > 0:
                    updated = session.execute(text(_EXECUTION_TRANSITION_SQL), params)
                    if int(updated.rowcount or 0) == 0:
                        exists = session.execute(
                            text(
                                "SELECT 1 FROM ae_agent_execution "
                                "WHERE tenant_id = :tenant_id "
                                "AND agent_execution_id = :agent_execution_id"
                            ),
                            params,
                        ).first()
                        if exists is None:
                            raise PlanValidationError(
                                "ae.plan_validation_execution_not_found",
                                "AgentExecution was not found.",
                            )
                        raise PlanValidationError(
                            "ae.plan_validation_execution_version_conflict",
                            "AgentExecution version changed before validation transition.",
                            True,
                        )
                session.commit()
                return saved
        except PlanValidationError:
            raise
        except SQLAlchemyError as exc:
            raise PlanValidationError(
                "ae.plan_validation_store_unavailable",
                "AE PlanValidation store is unavailable.",
                True,
            ) from exc

    def get(
        self, *, tenant_id: str, validation_result_id: str
    ) -> dict[str, Any] | None:
        tenant_id = _required_text("tenant_id", tenant_id, 128)
        validation_result_id = _required_uuid(
            "validation_result_id", validation_result_id
        )
        try:
            with self._session_factory() as session:
                return _load_validation(session, tenant_id, validation_result_id)
        except SQLAlchemyError as exc:
            raise PlanValidationError(
                "ae.plan_validation_store_unavailable",
                "AE PlanValidation store is unavailable.",
                True,
            ) from exc


def validate_plan_validation_result(value: Mapping[str, Any]) -> dict[str, Any]:
    try:
        record = json.loads(_canonical_json(dict(value)))
    except (TypeError, ValueError) as exc:
        raise _invalid("PlanValidationResult must be canonical JSON.") from exc
    fields = {
        "schema_version",
        "validation_result_id",
        "agent_plan_ref",
        "execution_id",
        "validator_version",
        "status",
        "runtime_directive",
        "validated_context_ref",
        "issues",
        "topological_step_order",
        "validated_at",
        "result_hash",
    }
    if set(record) != fields or record["schema_version"] != PLAN_VALIDATION_SCHEMA_VERSION:
        raise _invalid("PlanValidationResult fields or schema version are invalid.")
    _required_uuid("validation_result_id", record["validation_result_id"])
    _validate_versioned_ref("agent_plan_ref", record["agent_plan_ref"])
    _required_uuid("execution_id", record["execution_id"])
    _required_text("validator_version", record["validator_version"], 64)
    outcome = runtime_outcome_for_status(record["status"])
    if record["runtime_directive"] != outcome.runtime_directive:
        raise _invalid("PlanValidation status/runtime directive mapping is invalid.")
    _validate_versioned_ref("validated_context_ref", record["validated_context_ref"])
    issues = record["issues"]
    if not isinstance(issues, list) or len(issues) > 128:
        raise _invalid("PlanValidation issues are invalid.")
    for issue in issues:
        _normalize_issue(issue)
    order = _normalize_step_order(record["topological_step_order"])
    if order != record["topological_step_order"]:
        raise _invalid("PlanValidation topological order is not canonical.")
    _required_datetime("validated_at", record["validated_at"])
    if record["status"] == "VALID" and any(
        item["severity"] == "ERROR" for item in issues
    ):
        raise _invalid("VALID result cannot contain ERROR issues.")
    if record["status"] != "VALID" and not issues:
        raise _invalid("Non-VALID result requires at least one issue.")
    try:
        validate_hash_ref(record["result_hash"])
    except ValueError as exc:
        raise _invalid("PlanValidation result hash is invalid.") from exc
    expected = semantic_sha256_hash_ref(
        {key: item for key, item in record.items() if key != "result_hash"}
    )
    if record["result_hash"] != expected:
        raise _invalid("PlanValidation result hash does not match its content.")
    return record


def _evaluate_plan(
    *,
    plan: Mapping[str, Any],
    work_intent: Mapping[str, Any],
    agent_context: Mapping[str, Any],
    capability_snapshot: Mapping[str, Any],
) -> tuple[str, list[dict[str, Any]], list[str]]:
    if plan["execution_id"] != work_intent.get("execution_id"):
        return _decision(
            "INVALID_TERMINAL",
            "EXECUTION_LINEAGE_MISMATCH",
            "AgentPlan and WorkIntent execution identities differ.",
            field_path="execution_id",
        )
    clarification = work_intent.get("clarification")
    if isinstance(clarification, Mapping) and clarification.get("status") == "REQUIRED":
        questions = clarification.get("questions")
        message = (
            str(questions[0])
            if isinstance(questions, list) and questions
            else "Required input must be clarified before compilation."
        )
        return _decision(
            "CLARIFICATION_REQUIRED",
            "CLARIFICATION_REQUIRED",
            message,
            field_path="work_intent.clarification",
        )
    if not _reference_matches(
        plan["work_intent_ref"],
        work_intent,
        id_field="work_intent_id",
        version_field="intent_revision",
        hash_field="intent_hash",
    ):
        return _decision(
            "REPLAN_REQUIRED",
            "WORK_INTENT_REVISION_CHANGED",
            "AgentPlan does not reference the current exact WorkIntent.",
            field_path="work_intent_ref",
        )
    if plan["execution_id"] != agent_context.get("execution_id"):
        return _decision(
            "INVALID_TERMINAL",
            "CONTEXT_EXECUTION_MISMATCH",
            "AgentContext belongs to a different execution.",
            field_path="agent_context.execution_id",
        )
    if not _reference_matches(
        plan["agent_context_ref"],
        agent_context,
        id_field="context_id",
        version_field="context_generation",
        hash_field="context_hash",
    ):
        return _decision(
            "CONTEXT_REFRESH_REQUIRED",
            "AGENT_CONTEXT_CHANGED",
            "AgentPlan context is not the current exact AgentContext generation.",
            field_path="agent_context_ref",
        )
    if not _reference_matches(
        plan["capability_snapshot_ref"],
        capability_snapshot,
        id_field="capability_snapshot_id",
        version_field="snapshot_version",
        hash_field="snapshot_hash",
    ):
        return _decision(
            "REPLAN_REQUIRED",
            "CAPABILITY_SNAPSHOT_CHANGED",
            "AgentPlan capability snapshot is not the supplied exact snapshot.",
            field_path="capability_snapshot_ref",
        )
    conflicts = agent_context.get("conflicts")
    if isinstance(conflicts, list) and conflicts:
        return _decision(
            "BLOCKED",
            "CONTEXT_CONFLICT",
            "AgentContext contains unresolved authoritative conflicts.",
            field_path="agent_context.conflicts",
        )
    missing_selectors = _missing_required_selectors(work_intent, agent_context)
    if missing_selectors:
        return _decision(
            "CONTEXT_REFRESH_REQUIRED",
            "REQUIRED_ENTITY_UNRESOLVED",
            "Required entity selectors are unresolved: "
            + ", ".join(missing_selectors),
            field_path="agent_context.resolved_entities",
        )
    if plan["plan_kind"] not in {"DIRECT", "KNOWN_TEMPLATE"}:
        return _decision(
            "BLOCKED",
            "PLANNER_PROFILE_UNAVAILABLE",
            "This AgentPlan kind is unavailable in the P5 deterministic runtime.",
            field_path="plan_kind",
        )
    order, graph_issue = _topological_order(plan["steps"])
    if graph_issue is not None:
        return "INVALID_TERMINAL", [graph_issue], []
    semantic_issue = _validate_plan_semantics(plan, order)
    if semantic_issue is not None:
        status = (
            "BLOCKED"
            if semantic_issue["code"] == "EXECUTOR_NOT_AVAILABLE"
            else "INVALID_TERMINAL"
        )
        return status, [semantic_issue], order
    capability_issue = _validate_capabilities(plan, capability_snapshot)
    if capability_issue is not None:
        status = (
            "BLOCKED"
            if capability_issue["code"] == "EXECUTOR_NOT_AVAILABLE"
            else "REPLAN_REQUIRED"
        )
        return status, [capability_issue], order
    warnings = [
        _issue(
            "CONTEXT_DEGRADED",
            "WARNING",
            str(message),
            field_path="agent_context.degradations",
        )
        for message in agent_context.get("degradations", [])
    ]
    return "VALID", warnings, order


def _topological_order(
    steps: Sequence[Mapping[str, Any]],
) -> tuple[list[str], dict[str, Any] | None]:
    ids = [str(step.get("step_id")) for step in steps]
    if len(ids) != len(set(ids)):
        return [], _issue(
            "DUPLICATE_STEP_ID", "ERROR", "AgentPlan step IDs must be unique."
        )
    known = set(ids)
    incoming: dict[str, set[str]] = {}
    dependents: dict[str, set[str]] = defaultdict(set)
    for step in steps:
        step_id = str(step["step_id"])
        dependencies = {str(item) for item in step.get("depends_on", [])}
        if step_id in dependencies or not dependencies.issubset(known):
            return [], _issue(
                "INVALID_STEP_DEPENDENCY",
                "ERROR",
                "AgentPlan contains a self or missing step dependency.",
                step_id=step_id,
                field_path="steps.depends_on",
            )
        incoming[step_id] = dependencies
        for dependency in dependencies:
            dependents[dependency].add(step_id)
    ready = sorted(step_id for step_id in ids if not incoming[step_id])
    order: list[str] = []
    while ready:
        current = ready.pop(0)
        order.append(current)
        for dependent in sorted(dependents[current]):
            incoming[dependent].discard(current)
            if not incoming[dependent] and dependent not in order and dependent not in ready:
                ready.append(dependent)
        ready.sort()
    if len(order) != len(ids):
        return [], _issue(
            "PLAN_DEPENDENCY_CYCLE",
            "ERROR",
            "AgentPlan dependency graph contains a cycle.",
            field_path="steps.depends_on",
        )
    return order, None


def _validate_plan_semantics(
    plan: Mapping[str, Any], order: Sequence[str]
) -> dict[str, Any] | None:
    steps = {str(step["step_id"]): step for step in plan["steps"]}
    order_index = {step_id: index for index, step_id in enumerate(order)}
    dependent_ids = {
        str(dependency)
        for step in plan["steps"]
        for dependency in step.get("depends_on", [])
    }
    terminals = set(steps) - dependent_ids
    for criterion in plan["completion_criteria"]:
        refs = {str(item) for item in criterion["required_terminal_step_refs"]}
        if not refs.issubset(terminals):
            return _issue(
                "INVALID_TERMINAL_STEP_REF",
                "ERROR",
                "Completion criterion references a missing or non-terminal step.",
                field_path="completion_criteria.required_terminal_step_refs",
            )
    for step_id, step in steps.items():
        if step["step_type"] == "DELEGATE_WORK":
            return _issue(
                "EXECUTOR_NOT_AVAILABLE",
                "ERROR",
                "DELEGATE_WORK is unavailable in P5.",
                step_id=step_id,
                field_path="steps.step_type",
            )
        for binding in step["input_bindings"]:
            if binding["source_type"] != "STEP_OUTPUT":
                continue
            source = binding.get("source_ref")
            if source not in steps or order_index[source] >= order_index[step_id]:
                return _issue(
                    "INVALID_STEP_OUTPUT_BINDING",
                    "ERROR",
                    "STEP_OUTPUT binding must reference an earlier plan step.",
                    step_id=step_id,
                    field_path="steps.input_bindings.source_ref",
                )
        report = step.get("report")
        if step["step_type"] == "REPORT" and not isinstance(report, Mapping):
            return _issue(
                "REPORT_CONTRACT_MISSING",
                "ERROR",
                "REPORT step requires deterministic report metadata.",
                step_id=step_id,
                field_path="steps.report",
            )
        if isinstance(report, Mapping) and not set(report["source_step_refs"]).issubset(
            steps
        ):
            return _issue(
                "REPORT_SOURCE_MISSING",
                "ERROR",
                "Report references a missing source step.",
                step_id=step_id,
                field_path="steps.report.source_step_refs",
            )
    return None


def _validate_capabilities(
    plan: Mapping[str, Any], snapshot: Mapping[str, Any]
) -> dict[str, Any] | None:
    for step in plan["steps"]:
        step_id = str(step["step_id"])
        if step["step_type"] == "LOCAL_CAPABILITY":
            capability_id = step.get("required_capability")
            version = step.get("capability_version_constraint")
            if capability_id is None or version is None:
                return _issue(
                    "CAPABILITY_BINDING_MISSING",
                    "ERROR",
                    "LOCAL_CAPABILITY requires an exact capability version.",
                    step_id=step_id,
                )
            try:
                capability = capability_by_exact_version(
                    snapshot, str(capability_id), str(version)
                )
            except CapabilitySnapshotError:
                return _issue(
                    "CAPABILITY_VERSION_UNAVAILABLE",
                    "ERROR",
                    "The exact required capability version is unavailable.",
                    step_id=step_id,
                )
            expected_type = "LOCAL_CAPABILITY"
        elif step["step_type"] == "REPORT":
            try:
                capability = capability_by_exact_version(
                    snapshot, REPORT_CAPABILITY_ID, CAPABILITY_VERSION
                )
            except CapabilitySnapshotError:
                return _issue(
                    "CAPABILITY_VERSION_UNAVAILABLE",
                    "ERROR",
                    "The exact report capability version is unavailable.",
                    step_id=step_id,
                )
            expected_type = "REPORT"
        elif step["step_type"] == "AGGREGATE":
            return _issue(
                "CAPABILITY_VERSION_UNAVAILABLE",
                "ERROR",
                "No deterministic aggregate capability is registered in P5.",
                step_id=step_id,
            )
        else:
            return _issue(
                "EXECUTOR_NOT_AVAILABLE",
                "ERROR",
                "The requested executor is unavailable in P5.",
                step_id=step_id,
            )
        if expected_type not in capability["allowed_logical_step_types"]:
            return _issue(
                "CAPABILITY_STEP_TYPE_MISMATCH",
                "ERROR",
                "Capability does not allow the logical step type.",
                step_id=step_id,
            )
        if capability["output_contract_ref"] != step["output_contract_ref"]:
            return _issue(
                "CAPABILITY_OUTPUT_CONTRACT_MISMATCH",
                "ERROR",
                "Step output contract differs from the exact capability contract.",
                step_id=step_id,
            )
    return None


def _missing_required_selectors(
    work_intent: Mapping[str, Any], agent_context: Mapping[str, Any]
) -> list[str]:
    required = {
        str(item.get("selector_id"))
        for item in work_intent.get("entity_selectors", [])
        if isinstance(item, Mapping) and item.get("required") is True
    }
    resolved = {
        str(item.get("selector_id"))
        for item in agent_context.get("resolved_entities", [])
        if isinstance(item, Mapping)
    }
    return sorted(required - resolved)


def _decision(
    status: str,
    code: str,
    message: str,
    *,
    step_id: str | None = None,
    field_path: str | None = None,
) -> tuple[str, list[dict[str, Any]], list[str]]:
    outcome = runtime_outcome_for_status(status)
    return (
        status,
        [
            _issue(
                code,
                "ERROR" if status == "INVALID_TERMINAL" else "WARNING",
                message,
                step_id=step_id,
                field_path=field_path,
                recommended_runtime_directive=outcome.runtime_directive,
            )
        ],
        [],
    )


def _issue(
    code: str,
    severity: str,
    message: str,
    *,
    step_id: str | None = None,
    field_path: str | None = None,
    recommended_runtime_directive: str | None = None,
) -> dict[str, Any]:
    issue: dict[str, Any] = {
        "code": code,
        "severity": severity,
        "message": message,
    }
    if step_id is not None:
        issue["step_id"] = step_id
    if field_path is not None:
        issue["field_path"] = field_path
    if recommended_runtime_directive is not None:
        issue["recommended_runtime_directive"] = recommended_runtime_directive
    return issue


def _normalize_issue(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {"code", "severity", "message"}
    optional = {"step_id", "field_path", "recommended_runtime_directive"}
    if (
        not isinstance(value, Mapping)
        or not required.issubset(value)
        or not set(value).issubset(required | optional)
    ):
        raise _invalid("PlanValidation issue fields are invalid.")
    code = _required_text("issue.code", value["code"], 128)
    if _ISSUE_CODE.fullmatch(code) is None:
        raise _invalid("PlanValidation issue code is invalid.")
    if value["severity"] not in {"INFO", "WARNING", "ERROR"}:
        raise _invalid("PlanValidation issue severity is invalid.")
    issue: dict[str, Any] = {
        "code": code,
        "severity": value["severity"],
        "message": _required_text("issue.message", value["message"], 700),
    }
    step_id = value.get("step_id")
    if step_id is not None:
        if not isinstance(step_id, str) or _STEP_ID.fullmatch(step_id) is None:
            raise _invalid("PlanValidation issue step_id is invalid.")
        issue["step_id"] = step_id
    for field, maximum in (
        ("field_path", 256),
        ("recommended_runtime_directive", 64),
    ):
        item = value.get(field)
        if item is not None:
            issue[field] = _required_text(f"issue.{field}", item, maximum)
    return issue


def _normalize_step_order(value: Sequence[str]) -> list[str]:
    if (
        not isinstance(value, list | tuple)
        or len(value) > 12
        or len(set(value)) != len(value)
        or any(not isinstance(item, str) or _STEP_ID.fullmatch(item) is None for item in value)
    ):
        raise _invalid("PlanValidation topological step order is invalid.")
    return list(value)


def _reference_matches(
    reference: Mapping[str, Any],
    value: Mapping[str, Any],
    *,
    id_field: str,
    version_field: str,
    hash_field: str,
) -> bool:
    return reference == {
        "id": value.get(id_field),
        "version": value.get(version_field),
        "hash": value.get(hash_field),
    }


def _require_exact_persisted_lineage(
    session: Session, tenant_id: str, result: Mapping[str, Any]
) -> None:
    plan_ref = result["agent_plan_ref"]
    plan = session.execute(
        text(
            "SELECT agent_plan_version, agent_execution_id, agent_context_id, "
            "plan_hash FROM ae_agent_plan WHERE tenant_id = :tenant_id "
            "AND agent_plan_id = :plan_id"
        ),
        {"tenant_id": tenant_id, "plan_id": plan_ref["id"]},
    ).mappings().first()
    context_ref = result["validated_context_ref"]
    context = session.execute(
        text(
            "SELECT context_generation, agent_execution_id, context_hash "
            "FROM ae_agent_context WHERE tenant_id = :tenant_id "
            "AND context_id = :context_id"
        ),
        {"tenant_id": tenant_id, "context_id": context_ref["id"]},
    ).mappings().first()
    if (
        plan is None
        or int(plan["agent_plan_version"]) != plan_ref["version"]
        or str(plan["agent_execution_id"]) != result["execution_id"]
        or str(plan["agent_context_id"]) != context_ref["id"]
        or plan["plan_hash"] != plan_ref["hash"]
        or context is None
        or int(context["context_generation"]) != context_ref["version"]
        or str(context["agent_execution_id"]) != result["execution_id"]
        or context["context_hash"] != context_ref["hash"]
    ):
        raise PlanValidationError(
            "ae.plan_validation_lineage_mismatch",
            "PlanValidationResult does not reference exact persisted lineage.",
        )


def _validation_insert_sql(dialect_name: str) -> str:
    result_json = (
        "CAST(:result_json AS jsonb)"
        if dialect_name == "postgresql"
        else ":result_json"
    )
    return f"""
        INSERT INTO ae_plan_validation (
            tenant_id, validation_result_id, agent_plan_id,
            agent_plan_version, agent_execution_id, status,
            runtime_directive, result_hash, result_json, validated_at
        ) VALUES (
            :tenant_id, :validation_result_id, :agent_plan_id,
            :agent_plan_version, :agent_execution_id, :status,
            :runtime_directive, :result_hash, {result_json}, :validated_at
        ) ON CONFLICT DO NOTHING
    """


_EXECUTION_TRANSITION_SQL = """
    UPDATE ae_agent_execution
    SET state = :execution_state,
        phase = :execution_phase,
        version = version + 1,
        updated_at = :validated_at
    WHERE tenant_id = :tenant_id
      AND agent_execution_id = :agent_execution_id
      AND version = :expected_execution_version
"""


def _load_validation(
    session: Session, tenant_id: str, validation_result_id: str
) -> dict[str, Any] | None:
    row = session.execute(
        text(
            "SELECT result_json FROM ae_plan_validation "
            "WHERE tenant_id = :tenant_id "
            "AND validation_result_id = :validation_result_id"
        ),
        {
            "tenant_id": tenant_id,
            "validation_result_id": validation_result_id,
        },
    ).mappings().first()
    return None if row is None else _json_value(row["result_json"])


def _versioned_ref(record_id: object, version: object, hash_ref: object) -> dict[str, Any]:
    value = {"id": record_id, "version": version, "hash": hash_ref}
    _validate_versioned_ref("reference", value)
    return value


def _validate_versioned_ref(field: str, value: object) -> None:
    if not isinstance(value, Mapping) or set(value) != {"id", "version", "hash"}:
        raise _invalid(f"{field} must be an exact versioned hash reference.")
    _required_uuid(f"{field}.id", value["id"])
    _bounded_int(f"{field}.version", value["version"], 1, 2**31 - 1)
    try:
        validate_hash_ref(value["hash"])
    except ValueError as exc:
        raise _invalid(f"{field}.hash is invalid.") from exc


def _required_uuid(field: str, value: object) -> str:
    if not isinstance(value, str):
        raise _invalid(f"{field} must be a UUID string.")
    try:
        UUID(value)
    except ValueError as exc:
        raise _invalid(f"{field} must be a UUID string.") from exc
    return value


def _required_text(field: str, value: object, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise _invalid(f"{field} must be a non-empty string up to {maximum} characters.")
    return value.strip()


def _bounded_int(field: str, value: object, minimum: int, maximum: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise _invalid(f"{field} must be between {minimum} and {maximum}.")
    return value


def _required_datetime(field: str, value: object) -> str:
    if not isinstance(value, str):
        raise _invalid(f"{field} must be an RFC 3339 date-time string.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid(f"{field} must be an RFC 3339 date-time string.") from exc
    if parsed.tzinfo is None:
        raise _invalid(f"{field} must include a timezone offset.")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _json_value(value: Any) -> dict[str, Any]:
    return json.loads(value) if isinstance(value, str) else dict(value)


def _dialect_name(session: Session) -> str:
    return session.get_bind().dialect.name


def _invalid(detail: str) -> PlanValidationError:
    return PlanValidationError("ae.plan_validation_invalid", detail)
