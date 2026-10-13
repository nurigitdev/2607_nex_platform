from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_ae_api.planning_capabilities import (
    CAPABILITY_VERSION,
    CHAT_CAPABILITY_ID,
    REPORT_CAPABILITY_ID,
    capability_by_exact_version,
)

AGENT_PLAN_SCHEMA_VERSION = "1.1"
_STEP_ID = re.compile(r"^S[0-9]{1,3}$")
_PROFILE = {
    "GENERAL_ANSWER": ("DIRECT", None),
    "GROUNDED_ANSWER": ("KNOWN_TEMPLATE", "INTERACTIVE_RESPONSE"),
    "DOCUMENT_SUMMARY": ("KNOWN_TEMPLATE", "INTERACTIVE_RESPONSE"),
    "DOCUMENT_GENERATION": ("KNOWN_TEMPLATE", "ARTIFACT"),
}


@dataclass(frozen=True)
class AgentPlanError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


def build_deterministic_agent_plan(
    *,
    work_intent: Mapping[str, Any],
    agent_context: Mapping[str, Any],
    capability_snapshot: Mapping[str, Any],
    agent_plan_id: str,
    agent_plan_version: int = 1,
) -> dict[str, Any]:
    execution_id = _required_uuid("execution_id", work_intent.get("execution_id"))
    if agent_context.get("execution_id") != execution_id:
        raise _invalid("AgentContext execution does not match WorkIntent.")
    identity = agent_context.get("identity")
    if not isinstance(identity, Mapping):
        raise _invalid("AgentContext identity is invalid.")
    tenant_id = _required_text("tenant_id", identity.get("tenant_id"), 128)
    if capability_snapshot.get("tenant_id") != tenant_id:
        raise _invalid("Capability snapshot tenant does not match AgentContext.")
    mode = work_intent.get("compatibility_execution_mode")
    if mode not in _PROFILE:
        raise _invalid("WorkIntent compatibility mode is unsupported.")
    plan_kind, report_kind = _PROFILE[str(mode)]
    chat = capability_by_exact_version(
        capability_snapshot, CHAT_CAPABILITY_ID, CAPABILITY_VERSION
    )
    report = (
        capability_by_exact_version(
            capability_snapshot, REPORT_CAPABILITY_ID, CAPABILITY_VERSION
        )
        if report_kind is not None
        else None
    )
    first_step = {
        "step_id": "S1",
        "step_type": "LOCAL_CAPABILITY",
        "title": "Run compatibility chat",
        "objective": "Use the existing owner-scoped Chat/RAG path.",
        "depends_on": [],
        "required_capability": CHAT_CAPABILITY_ID,
        "capability_version_constraint": CAPABILITY_VERSION,
        "input_bindings": [],
        "output_contract_ref": chat["output_contract_ref"],
        "completion_criteria": ["Compatibility execution is terminal."],
        "aggregation": None,
        "report": None,
    }
    steps = [first_step]
    terminal_step = "S1"
    if report is not None:
        steps.append(
            {
                "step_id": "S2",
                "step_type": "REPORT",
                "title": "Project compatibility result",
                "objective": "Project the verified compatibility result.",
                "depends_on": ["S1"],
                "required_capability": None,
                "capability_version_constraint": None,
                "input_bindings": [
                    {
                        "target_name": "source_result",
                        "source_type": "STEP_OUTPUT",
                        "source_ref": "S1",
                        "json_pointer": "$",
                    }
                ],
                "output_contract_ref": report["output_contract_ref"],
                "completion_criteria": ["A deterministic projection is available."],
                "aggregation": None,
                "report": {
                    "report_kind": report_kind,
                    "source_step_refs": ["S1"],
                },
            }
        )
        terminal_step = "S2"
    criteria = work_intent.get("completion_criteria")
    if not isinstance(criteria, list) or not criteria:
        raise _invalid("WorkIntent completion criteria are required.")
    plan: dict[str, Any] = {
        "schema_version": AGENT_PLAN_SCHEMA_VERSION,
        "agent_plan_id": _required_uuid("agent_plan_id", agent_plan_id),
        "agent_plan_version": _bounded_int(
            "agent_plan_version", agent_plan_version, 1, 99
        ),
        "execution_id": execution_id,
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
            capability_snapshot.get("capability_snapshot_id"),
            capability_snapshot.get("snapshot_version"),
            capability_snapshot.get("snapshot_hash"),
        ),
        "plan_kind": plan_kind,
        "goal": _required_text("goal", work_intent.get("goal"), 1000),
        "completion_criteria": [
            {
                "criterion_id": _required_text(
                    "criterion_id", item.get("criterion_id"), 4
                ),
                "description": _required_text(
                    "description", item.get("description"), 500
                ),
                "required": _required_bool("required", item.get("required")),
                "required_terminal_step_refs": [terminal_step],
            }
            for item in criteria
            if isinstance(item, Mapping)
        ],
        "planning_constraints": {
            "max_plan_steps": 12,
            "max_delegation_depth": 0,
            "max_parallel_steps": 1,
        },
        "steps": steps,
        "planner_provenance": {
            "builder_type": (
                "DIRECT_BINDER" if plan_kind == "DIRECT" else "TEMPLATE_BINDER"
            ),
            "route_decision_ref": f"plan-profile://ae/{str(mode).lower()}/p5.1",
            "template_ref": (
                None
                if plan_kind == "DIRECT"
                else f"plan-template://ae/{str(mode).lower()}/p5.1"
            ),
            "input_context_hash": agent_context.get("context_hash"),
            "prompt_binding_key": None,
            "prompt_template_version_id": None,
            "prompt_content_sha256": None,
            "rendered_prompt_hash": None,
            "model_profile": None,
            "model_ref": None,
        },
    }
    if len(plan["completion_criteria"]) != len(criteria):
        raise _invalid("WorkIntent completion criteria are malformed.")
    plan["plan_hash"] = semantic_sha256_hash_ref(plan)
    return plan


class SqlAlchemyAgentPlanRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(
        self, *, tenant_id: str, agent_plan: Mapping[str, Any], created_at: str
    ) -> dict[str, Any]:
        tenant_id = _required_text("tenant_id", tenant_id, 128)
        normalized = _validate_plan(agent_plan)
        created_at = _required_datetime("created_at", created_at)
        params = {
            "tenant_id": tenant_id,
            "agent_plan_id": normalized["agent_plan_id"],
            "agent_plan_version": normalized["agent_plan_version"],
            "agent_execution_id": normalized["execution_id"],
            "work_intent_id": normalized["work_intent_ref"]["id"],
            "agent_context_id": normalized["agent_context_ref"]["id"],
            "capability_snapshot_id": normalized["capability_snapshot_ref"]["id"],
            "plan_kind": normalized["plan_kind"],
            "plan_hash": normalized["plan_hash"],
            "plan_json": _canonical_json(normalized),
            "created_at": created_at,
        }
        try:
            with self._session_factory() as session:
                _require_exact_lineage(session, tenant_id, normalized)
                _require_previous_plan_version(session, params)
                session.execute(text(_plan_insert_sql(_dialect_name(session))), params)
                saved = _load_plan(
                    session, tenant_id, normalized["agent_plan_id"]
                )
                if saved is None:
                    conflict = _load_plan_by_version(
                        session,
                        tenant_id,
                        normalized["execution_id"],
                        normalized["agent_plan_version"],
                    )
                    if conflict is not None:
                        raise AgentPlanError(
                            "ae.agent_plan_version_conflict",
                            "A different AgentPlan owns this execution version.",
                        )
                    raise AgentPlanError(
                        "ae.agent_plan_write_conflict",
                        "AgentPlan could not be reloaded.",
                        True,
                    )
                if saved != normalized:
                    raise AgentPlanError(
                        "ae.agent_plan_immutable_conflict",
                        "AgentPlan identity exists with different content.",
                    )
                session.commit()
                return saved
        except AgentPlanError:
            raise
        except SQLAlchemyError as exc:
            raise AgentPlanError(
                "ae.agent_plan_store_unavailable",
                "AE AgentPlan store is unavailable.",
                True,
            ) from exc

    def get(
        self, *, tenant_id: str, agent_plan_id: str
    ) -> dict[str, Any] | None:
        tenant_id = _required_text("tenant_id", tenant_id, 128)
        agent_plan_id = _required_uuid("agent_plan_id", agent_plan_id)
        try:
            with self._session_factory() as session:
                return _load_plan(session, tenant_id, agent_plan_id)
        except SQLAlchemyError as exc:
            raise AgentPlanError(
                "ae.agent_plan_store_unavailable",
                "AE AgentPlan store is unavailable.",
                True,
            ) from exc


def validate_agent_plan_contract(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return a canonical contract-valid plan without granting execution authority."""
    return _validate_plan(value)


def _validate_plan(value: Mapping[str, Any]) -> dict[str, Any]:
    try:
        record = json.loads(_canonical_json(dict(value)))
    except (TypeError, ValueError) as exc:
        raise _invalid("AgentPlan must be canonical JSON.") from exc
    fields = {
        "schema_version",
        "agent_plan_id",
        "agent_plan_version",
        "execution_id",
        "work_intent_ref",
        "agent_context_ref",
        "capability_snapshot_ref",
        "plan_kind",
        "goal",
        "completion_criteria",
        "planning_constraints",
        "steps",
        "planner_provenance",
        "plan_hash",
    }
    if set(record) != fields or record["schema_version"] != AGENT_PLAN_SCHEMA_VERSION:
        raise _invalid("AgentPlan fields or schema version are invalid.")
    _required_uuid("agent_plan_id", record["agent_plan_id"])
    _bounded_int("agent_plan_version", record["agent_plan_version"], 1, 99)
    _required_uuid("execution_id", record["execution_id"])
    for field in (
        "work_intent_ref",
        "agent_context_ref",
        "capability_snapshot_ref",
    ):
        _validate_versioned_ref(field, record[field])
    if record["plan_kind"] not in {
        "DIRECT",
        "CERTIFIED_BINDING",
        "KNOWN_TEMPLATE",
        "DYNAMIC",
    }:
        raise _invalid("AgentPlan kind is invalid.")
    _required_text("goal", record["goal"], 1000)
    criteria = record["completion_criteria"]
    steps = record["steps"]
    if not isinstance(criteria, list) or not 1 <= len(criteria) <= 16:
        raise _invalid("AgentPlan completion criteria are invalid.")
    if not isinstance(steps, list) or not 1 <= len(steps) <= 12:
        raise _invalid("AgentPlan steps are invalid.")
    for item in criteria:
        _validate_completion_criterion(item)
    for item in steps:
        _validate_step(item)
    constraints = record["planning_constraints"]
    if constraints != {
        "max_plan_steps": 12,
        "max_delegation_depth": 0,
        "max_parallel_steps": 1,
    }:
        raise _invalid("AgentPlan planning constraints are invalid.")
    provenance = record["planner_provenance"]
    _validate_provenance(provenance)
    try:
        validate_hash_ref(provenance.get("input_context_hash"))
        validate_hash_ref(record["plan_hash"])
    except ValueError as exc:
        raise _invalid("AgentPlan semantic hash is invalid.") from exc
    expected = semantic_sha256_hash_ref(
        {key: item for key, item in record.items() if key != "plan_hash"}
    )
    if record["plan_hash"] != expected:
        raise _invalid("AgentPlan hash does not match its content.")
    return record


def _validate_completion_criterion(value: object) -> None:
    fields = {
        "criterion_id",
        "description",
        "required",
        "required_terminal_step_refs",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise _invalid("AgentPlan completion criterion is invalid.")
    criterion_id = _required_text("criterion_id", value["criterion_id"], 4)
    if not re.fullmatch(r"^C[0-9]{1,3}$", criterion_id):
        raise _invalid("AgentPlan criterion ID is invalid.")
    _required_text("description", value["description"], 500)
    if not isinstance(value["required"], bool):
        raise _invalid("AgentPlan criterion required flag is invalid.")
    refs = value["required_terminal_step_refs"]
    if (
        not isinstance(refs, list)
        or not 1 <= len(refs) <= 12
        or len(set(refs)) != len(refs)
        or any(_STEP_ID.fullmatch(str(ref)) is None for ref in refs)
    ):
        raise _invalid("AgentPlan terminal step references are invalid.")


def _validate_step(value: object) -> None:
    required = {
        "step_id",
        "step_type",
        "title",
        "objective",
        "depends_on",
        "required_capability",
        "capability_version_constraint",
        "input_bindings",
        "output_contract_ref",
        "completion_criteria",
    }
    optional = {"aggregation", "report"}
    if (
        not isinstance(value, Mapping)
        or not required.issubset(value)
        or not set(value).issubset(required | optional)
    ):
        raise _invalid("AgentPlan step fields are invalid.")
    if _STEP_ID.fullmatch(str(value["step_id"])) is None:
        raise _invalid("AgentPlan step ID is invalid.")
    if value["step_type"] not in {
        "LOCAL_CAPABILITY",
        "DELEGATE_WORK",
        "AGGREGATE",
        "REPORT",
    }:
        raise _invalid("AgentPlan step type is invalid.")
    _required_text("title", value["title"], 160)
    _required_text("objective", value["objective"], 700)
    for field in ("depends_on", "input_bindings", "completion_criteria"):
        if not isinstance(value[field], list):
            raise _invalid(f"AgentPlan step {field} must be an array.")
    if (
        len(value["depends_on"]) > 12
        or len(set(value["depends_on"])) != len(value["depends_on"])
        or any(_STEP_ID.fullmatch(str(ref)) is None for ref in value["depends_on"])
    ):
        raise _invalid("AgentPlan step dependency is invalid.")
    required_capability = value["required_capability"]
    version_constraint = value["capability_version_constraint"]
    if required_capability is not None:
        required_capability = _required_text(
            "required_capability", required_capability, 160
        )
        if re.fullmatch(
            r"^[A-Z][A-Z0-9_]*(\.[A-Z][A-Z0-9_]*)+$", required_capability
        ) is None:
            raise _invalid("AgentPlan required capability is invalid.")
    if version_constraint is not None:
        _required_text("capability_version_constraint", version_constraint, 64)
    bindings = value["input_bindings"]
    if len(bindings) > 32:
        raise _invalid("AgentPlan step input bindings exceed the limit.")
    for binding in bindings:
        _validate_input_binding(binding)
    _required_text("output_contract_ref", value["output_contract_ref"], 256)
    completion = value["completion_criteria"]
    if not 1 <= len(completion) <= 8:
        raise _invalid("AgentPlan step completion criteria are required.")
    for criterion in completion:
        _required_text("step completion criterion", criterion, 500)
    _validate_aggregation(value.get("aggregation"))
    _validate_report(value.get("report"))


def _validate_input_binding(value: object) -> None:
    required = {"target_name", "source_type"}
    optional = {"source_ref", "json_pointer", "literal_value"}
    if (
        not isinstance(value, Mapping)
        or not required.issubset(value)
        or not set(value).issubset(required | optional)
    ):
        raise _invalid("AgentPlan input binding is invalid.")
    if re.fullmatch(r"^[a-z][a-z0-9_]{0,63}$", str(value["target_name"])) is None:
        raise _invalid("AgentPlan input binding target is invalid.")
    if value["source_type"] not in {
        "WORK_INTENT_PARAMETER",
        "ENTITY_SELECTOR",
        "STEP_OUTPUT",
        "LITERAL",
    }:
        raise _invalid("AgentPlan input binding source type is invalid.")
    for field, maximum in (("source_ref", 160), ("json_pointer", 512)):
        if field in value and value[field] is not None:
            _required_text(field, value[field], maximum)


def _validate_aggregation(value: object) -> None:
    if value is None:
        return
    if not isinstance(value, Mapping) or set(value) != {"mode", "source_step_refs"}:
        raise _invalid("AgentPlan aggregation is invalid.")
    if value["mode"] not in {"DETERMINISTIC", "STRUCTURED", "LLM_SYNTHESIS"}:
        raise _invalid("AgentPlan aggregation mode is invalid.")
    _validate_step_refs("aggregation", value["source_step_refs"])


def _validate_report(value: object) -> None:
    if value is None:
        return
    if not isinstance(value, Mapping) or set(value) != {
        "report_kind",
        "source_step_refs",
    }:
        raise _invalid("AgentPlan report is invalid.")
    if value["report_kind"] not in {
        "INTERACTIVE_RESPONSE",
        "WORK_RESULT",
        "ARTIFACT",
    }:
        raise _invalid("AgentPlan report kind is invalid.")
    _validate_step_refs("report", value["source_step_refs"])


def _validate_step_refs(field: str, value: object) -> None:
    if (
        not isinstance(value, list)
        or not 1 <= len(value) <= 12
        or len(set(value)) != len(value)
        or any(_STEP_ID.fullmatch(str(ref)) is None for ref in value)
    ):
        raise _invalid(f"AgentPlan {field} source step references are invalid.")


def _validate_provenance(value: object) -> None:
    required = {"builder_type", "route_decision_ref", "input_context_hash"}
    optional = {
        "template_ref",
        "prompt_binding_key",
        "prompt_template_version_id",
        "prompt_content_sha256",
        "rendered_prompt_hash",
        "model_profile",
        "model_ref",
    }
    if (
        not isinstance(value, Mapping)
        or not required.issubset(value)
        or not set(value).issubset(required | optional)
    ):
        raise _invalid("AgentPlan planner provenance is invalid.")
    if value["builder_type"] not in {
        "DIRECT_BINDER",
        "CERTIFIED_BINDER",
        "TEMPLATE_BINDER",
        "DYNAMIC_BUILDER",
    }:
        raise _invalid("AgentPlan builder type is invalid.")
    _required_text("route_decision_ref", value["route_decision_ref"], 256)
    for field, maximum in (
        ("template_ref", 256),
        ("prompt_binding_key", 200),
        ("model_profile", 128),
        ("model_ref", 256),
    ):
        if field in value and value[field] is not None:
            _required_text(field, value[field], maximum)
    version_id = value.get("prompt_template_version_id")
    if version_id is not None:
        _required_uuid("prompt_template_version_id", version_id)
    for field in ("prompt_content_sha256", "rendered_prompt_hash"):
        digest = value.get(field)
        if digest is not None and re.fullmatch(r"[0-9a-f]{64}", str(digest)) is None:
            raise _invalid(f"AgentPlan {field} is invalid.")


def _require_exact_lineage(
    session: Session, tenant_id: str, plan: Mapping[str, Any]
) -> None:
    checks = (
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
        row = session.execute(
            text(
                f"SELECT {version_column}, {hash_column} FROM {table} "
                f"WHERE tenant_id = :tenant_id AND {id_column} = :record_id"
            ),
            {"tenant_id": tenant_id, "record_id": reference["id"]},
        ).mappings().first()
        if (
            row is None
            or int(row[version_column]) != reference["version"]
            or row[hash_column] != reference["hash"]
        ):
            raise AgentPlanError(
                "ae.agent_plan_lineage_mismatch",
                "AgentPlan does not reference exact persisted planning inputs.",
            )


def _require_previous_plan_version(session: Session, params: Mapping[str, Any]) -> None:
    version = int(params["agent_plan_version"])
    if version == 1:
        return
    previous = _load_plan_by_version(
        session,
        str(params["tenant_id"]),
        str(params["agent_execution_id"]),
        version - 1,
    )
    if previous is None:
        raise AgentPlanError(
            "ae.agent_plan_version_chain_invalid",
            "AgentPlan version must follow the preceding execution version.",
        )


def _plan_insert_sql(dialect_name: str) -> str:
    plan_json = (
        "CAST(:plan_json AS jsonb)" if dialect_name == "postgresql" else ":plan_json"
    )
    return f"""
        INSERT INTO ae_agent_plan (
            tenant_id, agent_plan_id, agent_plan_version, agent_execution_id,
            work_intent_id, agent_context_id, capability_snapshot_id,
            plan_kind, plan_hash, plan_json, created_at
        ) VALUES (
            :tenant_id, :agent_plan_id, :agent_plan_version, :agent_execution_id,
            :work_intent_id, :agent_context_id, :capability_snapshot_id,
            :plan_kind, :plan_hash, {plan_json}, :created_at
        ) ON CONFLICT DO NOTHING
    """


def _load_plan(
    session: Session, tenant_id: str, agent_plan_id: str
) -> dict[str, Any] | None:
    row = session.execute(
        text(
            """
            SELECT plan_json FROM ae_agent_plan
            WHERE tenant_id = :tenant_id AND agent_plan_id = :agent_plan_id
            """
        ),
        {"tenant_id": tenant_id, "agent_plan_id": agent_plan_id},
    ).mappings().first()
    return None if row is None else _json_value(row["plan_json"])


def _load_plan_by_version(
    session: Session, tenant_id: str, execution_id: str, version: int
) -> dict[str, Any] | None:
    row = session.execute(
        text(
            """
            SELECT plan_json FROM ae_agent_plan
            WHERE tenant_id = :tenant_id
              AND agent_execution_id = :execution_id
              AND agent_plan_version = :version
            """
        ),
        {"tenant_id": tenant_id, "execution_id": execution_id, "version": version},
    ).mappings().first()
    return None if row is None else _json_value(row["plan_json"])


def _versioned_ref(record_id: object, version: object, hash_ref: object) -> dict[str, Any]:
    reference = {"id": record_id, "version": version, "hash": hash_ref}
    _validate_versioned_ref("reference", reference)
    return reference


def _validate_versioned_ref(field: str, value: object) -> None:
    if not isinstance(value, Mapping) or set(value) != {"id", "version", "hash"}:
        raise _invalid(f"{field} must be an exact versioned hash reference.")
    _required_uuid(f"{field}.id", value["id"])
    if (
        isinstance(value["version"], bool)
        or not isinstance(value["version"], int)
        or value["version"] < 1
    ):
        raise _invalid(f"{field}.version is invalid.")
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


def _required_bool(field: str, value: object) -> bool:
    if not isinstance(value, bool):
        raise _invalid(f"{field} must be a boolean.")
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


def _invalid(detail: str) -> AgentPlanError:
    return AgentPlanError("ae.agent_plan_invalid", detail)
