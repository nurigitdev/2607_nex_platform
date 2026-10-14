from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_ae_api.agent_results import (
    AgentResultAggregate,
    AgentResultError,
    SqlAlchemyAgentResultRepository,
    result_hash,
    validate_agent_result,
)
from nex_ae_api.executable_plans import (
    ExecutablePlanError,
    validate_executable_plan_contract,
)
from nex_ae_api.step_results import (
    StepResultError,
    load_step_results_for_plan,
    validate_step_result_contract,
)

_STATUS_PRECEDENCE = ("FAILED", "CANCELLED", "BLOCKED")


@dataclass(frozen=True)
class P5PlanFinalizationError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class P5CompletionVerification:
    status: str
    required_compiled_step_keys: tuple[str, ...]
    completion_verification_refs: tuple[str, ...]
    step_result_hashes: Mapping[str, str]
    input_result_set_hash: str


def verify_plan_completion(
    *,
    executable_plan: Mapping[str, Any],
    step_results: Sequence[Mapping[str, Any]],
) -> P5CompletionVerification:
    try:
        plan = validate_executable_plan_contract(executable_plan)
        results = [validate_step_result_contract(item) for item in step_results]
    except (ExecutablePlanError, StepResultError) as exc:
        raise _invalid(exc.detail) from exc
    steps = {item["compiled_step_key"]: item for item in plan["steps"]}
    by_key: dict[str, dict[str, Any]] = {}
    for item in results:
        key = item["compiled_step_key"]
        if key in by_key:
            raise _invalid("Plan finalization found duplicate StepResult keys.")
        expected = steps.get(key)
        if (
            expected is None
            or item["execution_id"] != plan["execution_id"]
            or item["executable_plan_id"] != plan["executable_plan_id"]
            or item["executable_step_id"] != expected["executable_step_id"]
            or item["logical_step_ref"] != expected["logical_step_ref"]
        ):
            raise _invalid("StepResult does not match the ExecutablePlan lineage.")
        by_key[key] = item
    if set(by_key) != set(steps):
        raise P5PlanFinalizationError(
            "ae.p5_plan_result_set_incomplete",
            "AgentResult requires the exact terminal StepResult set.",
        )

    required_criteria = [
        item for item in plan["completion_criteria"] if item["required"]
    ]
    if not required_criteria:
        raise _invalid("ExecutablePlan has no required completion criterion.")
    required_keys = {
        key
        for criterion in required_criteria
        for key in criterion["required_terminal_compiled_step_keys"]
    }
    ordered_keys = tuple(key for key in steps if key in required_keys)
    statuses = {by_key[key]["status"] for key in ordered_keys}
    status = next(
        (candidate for candidate in _STATUS_PRECEDENCE if candidate in statuses),
        "SUCCEEDED",
    )
    ordered_projection = [
        {
            "compiled_step_key": key,
            "step_result_id": by_key[key]["step_result_id"],
            "status": by_key[key]["status"],
            "result_contract_ref": by_key[key]["result_contract_ref"],
            "result_hash": by_key[key]["result_hash"],
        }
        for key in steps
    ]
    input_hash = semantic_sha256_hash_ref(ordered_projection)
    plan_id = plan["executable_plan_id"]
    criterion_refs = tuple(
        f"AE:PLAN_COMPLETION:{plan_id}:{item['criterion_id']}:{input_hash}"
        for item in required_criteria
    )
    return P5CompletionVerification(
        status=status,
        required_compiled_step_keys=ordered_keys,
        completion_verification_refs=criterion_refs,
        step_result_hashes={key: by_key[key]["result_hash"] for key in steps},
        input_result_set_hash=input_hash,
    )


def build_plan_agent_result(
    *,
    execution: Mapping[str, Any],
    executable_plan: Mapping[str, Any],
    step_results: Sequence[Mapping[str, Any]],
    verification: P5CompletionVerification,
    result_id: str,
    created_at: str,
) -> dict[str, Any]:
    plan = validate_executable_plan_contract(executable_plan)
    tenant_id = _required_text("tenant_id", execution.get("tenant_id"), 128)
    execution_id = _required_uuid(
        "agent_execution_id", execution.get("agent_execution_id")
    )
    if (
        execution.get("agent_type") != "IA"
        or execution.get("project_id") is not None
        or plan["execution_id"] != execution_id
    ):
        raise _invalid("P5 AgentResult requires a project-neutral IA plan lineage.")
    results = {
        item["compiled_step_key"]: validate_step_result_contract(item)
        for item in step_results
    }
    if verification.step_result_hashes != {
        key: item["result_hash"] for key, item in results.items()
    }:
        raise _invalid("Completion verification does not match StepResult inputs.")
    output_results = [
        {
            "compiled_step_key": key,
            "step_result_ref": f"AE:STEP_RESULT:{results[key]['step_result_id']}",
            "result_hash": results[key]["result_hash"],
            "result_contract_ref": results[key]["result_contract_ref"],
            "status": results[key]["status"],
        }
        for key in verification.required_compiled_step_keys
    ]
    artifact_refs = _union_result_refs(results.values(), "artifact_refs")
    external_refs = _union_result_refs(results.values(), "external_refs")
    evidence_refs = sorted(
        {
            *_union_result_refs(results.values(), "evidence_refs"),
            *(f"AE:STEP_RESULT:{item['step_result_id']}" for item in results.values()),
        }
    )
    output_contracts = {item["result_contract_ref"] for item in output_results}
    result: dict[str, Any] = {
        "schema_version": "2.1",
        "tenant_id": tenant_id,
        "result_id": _required_uuid("result_id", result_id),
        "agent_execution_id": execution_id,
        "agent_type": "IA",
        "agent_id": _required_uuid("agent_id", execution.get("agent_id")),
        "project_id": None,
        "work_intent_ref": _versioned_ref("WORK_INTENT", plan["work_intent_ref"]),
        "agent_context_ref": _versioned_ref("AGENT_CONTEXT", plan["agent_context_ref"]),
        "agent_plan_ref": _versioned_ref("AGENT_PLAN", plan["agent_plan_ref"]),
        "executable_plan_ref": _plan_ref(plan),
        "source_work_item_ref": None,
        "source_claim_ref": None,
        "source_claim_generation": None,
        "source_claimant_agent_id": None,
        "source_assignment_ref": None,
        "status": verification.status,
        "quality": "COMPLETE" if verification.status == "SUCCEEDED" else None,
        "completion_verification_refs": list(verification.completion_verification_refs),
        "structured_result_contract_ref": (
            next(iter(output_contracts))
            if len(output_contracts) == 1
            else "contract://nex/ae/p5-plan-result-set/v1.1"
        ),
        "structured_result": {
            "executable_plan_ref": _plan_ref(plan),
            "output_step_results": output_results,
            "external_refs": external_refs,
        },
        "business_refs": [],
        "child_work_result_refs": [],
        "artifact_refs": artifact_refs,
        "evidence_refs": evidence_refs,
        "citation_refs": [],
        "warnings": [],
        "conflicts": [],
        "control_summary": {
            "completion_status": "VERIFIED",
            "required_criteria_count": len(verification.completion_verification_refs),
            "step_result_count": len(results),
        },
        "provenance": {
            "result_assembler_version": "p5-plan-result/1.0",
            "executable_plan_id": plan["executable_plan_id"],
            "executable_plan_hash": plan["executable_plan_hash"],
            "input_result_set_hash": verification.input_result_set_hash,
        },
        "created_at": _timestamp("created_at", created_at),
    }
    result["result_hash"] = result_hash(result)
    validate_agent_result(result)
    return result


class SqlAlchemyP5PlanFinalizationService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        results: SqlAlchemyAgentResultRepository | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._results = results or SqlAlchemyAgentResultRepository(session_factory)

    def finalize(
        self,
        *,
        tenant_id: str,
        execution_id: str,
        created_at: str | None = None,
    ) -> AgentResultAggregate:
        tenant = _required_text("tenant_id", tenant_id, 128)
        execution_ref = _required_uuid("execution_id", execution_id)
        timestamp = _timestamp(
            "created_at",
            created_at or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        )
        try:
            with self._session_factory() as session:
                execution = _load_execution(session, tenant, execution_ref)
                if execution is None:
                    raise P5PlanFinalizationError(
                        "ae.p5_finalization_execution_not_found",
                        "P5 finalization requires an AgentExecution.",
                    )
                plan = _load_latest_plan(session, tenant, execution_ref)
                if plan is None:
                    raise P5PlanFinalizationError(
                        "ae.p5_finalization_plan_not_found",
                        "P5 finalization requires an ExecutablePlan.",
                    )
                step_results = load_step_results_for_plan(
                    session, tenant, plan["executable_plan_id"]
                )
        except P5PlanFinalizationError:
            raise
        except (SQLAlchemyError, StepResultError) as exc:
            raise _unavailable() from exc

        verification = verify_plan_completion(
            executable_plan=plan, step_results=step_results
        )
        result_id, delivery_id = derive_plan_result_ids(
            tenant_id=tenant,
            execution_id=execution_ref,
            input_result_set_hash=verification.input_result_set_hash,
        )
        result = build_plan_agent_result(
            execution=execution,
            executable_plan=plan,
            step_results=step_results,
            verification=verification,
            result_id=result_id,
            created_at=timestamp,
        )
        try:
            return self._results.persist_plan_with_pending_delivery(
                result=result,
                delivery_id=delivery_id,
                executable_plan_id=plan["executable_plan_id"],
                step_result_hashes=verification.step_result_hashes,
                input_result_set_hash=verification.input_result_set_hash,
            )
        except AgentResultError as exc:
            raise P5PlanFinalizationError(
                exc.error_code, exc.detail, exc.retryable
            ) from exc


def derive_plan_result_ids(
    *, tenant_id: str, execution_id: str, input_result_set_hash: str
) -> tuple[str, str]:
    identity = "|".join(
        (
            _required_text("tenant_id", tenant_id, 128),
            _required_uuid("execution_id", execution_id),
            _required_text("input_result_set_hash", input_result_set_hash, 80),
        )
    )
    result_id = str(uuid5(NAMESPACE_URL, f"nex:p5:agent-result:{identity}"))
    delivery_id = str(uuid5(NAMESPACE_URL, f"nex:p5:result-delivery:{result_id}"))
    return result_id, delivery_id


def _load_execution(
    session: Session, tenant_id: str, execution_id: str
) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                "SELECT tenant_id, agent_execution_id, agent_id, agent_type, project_id, "
                "workspace_id, state, phase, version, result_id, correlation_id, "
                "causation_id FROM ae_agent_execution WHERE tenant_id = :tenant_id "
                "AND agent_execution_id = :execution_id"
            ),
            {"tenant_id": tenant_id, "execution_id": execution_id},
        )
        .mappings()
        .first()
    )
    return None if row is None else _row_dict(row)


def _load_latest_plan(
    session: Session, tenant_id: str, execution_id: str
) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                "SELECT plan_json FROM ae_executable_plan WHERE tenant_id = :tenant_id "
                "AND agent_execution_id = :execution_id "
                "ORDER BY executable_plan_version DESC LIMIT 1"
            ),
            {"tenant_id": tenant_id, "execution_id": execution_id},
        )
        .mappings()
        .first()
    )
    return None if row is None else _json_object(row["plan_json"])


def _versioned_ref(kind: str, value: Mapping[str, Any]) -> str:
    return f"AE:{kind}:{value['id']}:v{value['version']}:" f"{value['hash']}"


def _plan_ref(plan: Mapping[str, Any]) -> str:
    return (
        f"AE:EXECUTABLE_PLAN:{plan['executable_plan_id']}:"
        f"v{plan['executable_plan_version']}:{plan['executable_plan_hash']}"
    )


def _union_result_refs(
    results: Sequence[Mapping[str, Any]] | Any, field: str
) -> list[str]:
    refs: set[str] = set()
    for item in results:
        value = item.get(field)
        if not isinstance(value, list):
            raise _invalid(f"StepResult {field} must be an array.")
        refs.update(_required_text(field, ref, 256) for ref in value)
    return sorted(refs)


def _row_dict(row: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for field in ("agent_execution_id", "agent_id", "workspace_id", "result_id"):
        if result.get(field) is not None:
            result[field] = str(result[field])
    return result


def _json_object(value: object) -> dict[str, Any]:
    try:
        decoded = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError as exc:
        raise _invalid("Stored ExecutablePlan is not valid JSON.") from exc
    if not isinstance(decoded, Mapping):
        raise _invalid("Stored ExecutablePlan is not an object.")
    return dict(decoded)


def _required_text(field: str, value: object, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise _invalid(f"{field} must be a non-empty bounded string.")
    return value.strip()


def _required_uuid(field: str, value: object) -> str:
    raw = _required_text(field, value, 64)
    try:
        parsed = UUID(raw)
    except ValueError as exc:
        raise _invalid(f"{field} must be a UUID.") from exc
    if str(parsed) != raw.lower():
        raise _invalid(f"{field} must be a canonical UUID.")
    return str(parsed)


def _timestamp(field: str, value: object) -> str:
    raw = _required_text(field, value, 64)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid(f"{field} must be an RFC 3339 timestamp.") from exc
    if parsed.tzinfo is None:
        raise _invalid(f"{field} must include a timezone.")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _invalid(detail: str) -> P5PlanFinalizationError:
    return P5PlanFinalizationError("ae.p5_plan_finalization_invalid", detail)


def _unavailable() -> P5PlanFinalizationError:
    return P5PlanFinalizationError(
        "ae.p5_plan_finalization_store_unavailable",
        "P5 plan finalization store is unavailable.",
        True,
    )
