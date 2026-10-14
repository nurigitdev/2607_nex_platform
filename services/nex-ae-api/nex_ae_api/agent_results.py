from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

AGENT_RESULT_STATUSES = frozenset(
    {"SUCCEEDED", "PARTIAL", "BLOCKED", "FAILED", "CANCELLED"}
)
SET_LIKE_RESULT_FIELDS = frozenset(
    {
        "completion_verification_refs",
        "business_refs",
        "child_work_result_refs",
        "artifact_refs",
        "evidence_refs",
        "citation_refs",
    }
)
_FORBIDDEN_PRIVATE_KEYS = frozenset(
    {
        "content",
        "evidence_text",
        "generated_response",
        "generated_text",
        "message_text",
        "output_preview",
        "prompt",
        "raw_output",
        "response_body",
        "user_message",
    }
)
_TERMINAL_STEP_BY_RESULT = {
    "SUCCEEDED": "SUCCEEDED",
    "PARTIAL": "SUCCEEDED",
    "BLOCKED": "BLOCKED",
    "FAILED": "FAILED",
    "CANCELLED": "CANCELLED",
}


@dataclass(frozen=True)
class AgentResultError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class AgentResultAggregate:
    result: dict[str, Any]
    delivery: dict[str, Any]
    execution: dict[str, Any]


def build_agent_result(
    *,
    execution: Mapping[str, Any],
    step: Mapping[str, Any],
    legacy_result: Mapping[str, Any],
    result_id: str,
    created_at: str,
    structured_result_contract_ref: str | None = None,
    completion_verification_refs: Iterable[str] = (),
    business_refs: Iterable[str] = (),
    evidence_refs: Iterable[str] = (),
    citation_refs: Iterable[str] = (),
) -> dict[str, Any]:
    tenant_id = _required("tenant_id", execution.get("tenant_id"))
    execution_id = _required("agent_execution_id", execution.get("agent_execution_id"))
    if execution.get("agent_type") != "IA" or execution.get("project_id") is not None:
        raise _invalid(
            "P4 AgentResult assembly requires a project-neutral IA execution."
        )
    if (
        str(step.get("tenant_id")) != tenant_id
        or str(step.get("agent_execution_id")) != execution_id
    ):
        raise _invalid("ExecutableStep is outside the AgentExecution lineage.")
    interaction_id = _required(
        "legacy_interaction_id", step.get("legacy_interaction_id")
    )
    if (
        _required("interaction_id", legacy_result.get("interaction_id"))
        != interaction_id
    ):
        raise _invalid("Legacy result does not match the compatibility step.")

    status, quality, warnings = _legacy_status_quality(legacy_result)
    if step.get("state") != _TERMINAL_STEP_BY_RESULT[status]:
        raise _invalid(
            "AgentResult status does not match terminal ExecutableStep state."
        )

    structured_result = _structured_result_refs(step)
    artifact_refs = _artifact_references(legacy_result.get("artifact_refs", ()))
    envelope: dict[str, Any] = {
        "schema_version": "2.1",
        "tenant_id": tenant_id,
        "result_id": _required("result_id", result_id),
        "agent_execution_id": execution_id,
        "agent_type": "IA",
        "agent_id": _required("agent_id", execution.get("agent_id")),
        "project_id": None,
        "work_intent_ref": None,
        "agent_context_ref": None,
        "agent_plan_ref": None,
        "executable_plan_ref": None,
        "source_work_item_ref": None,
        "source_claim_ref": None,
        "source_claim_generation": None,
        "source_claimant_agent_id": None,
        "source_assignment_ref": None,
        "status": status,
        "quality": quality,
        "completion_verification_refs": _reference_list(
            "completion_verification_refs", completion_verification_refs
        ),
        "structured_result_contract_ref": _optional(
            "structured_result_contract_ref", structured_result_contract_ref
        ),
        "structured_result": structured_result,
        "business_refs": _reference_list("business_refs", business_refs),
        "child_work_result_refs": [],
        "artifact_refs": artifact_refs,
        "evidence_refs": _reference_list("evidence_refs", evidence_refs),
        "citation_refs": _reference_list("citation_refs", citation_refs),
        "warnings": warnings,
        "conflicts": [],
        "control_summary": {},
        "provenance": {
            "result_assembler_version": "p4-agent-result/1.0",
            "compatibility_step_ref": _required(
                "executable_step_id", step.get("executable_step_id")
            ),
            "input_result_set_hash": _input_result_set_hash(step),
        },
        "created_at": _timestamp("created_at", created_at),
    }
    envelope["result_hash"] = result_hash(envelope)
    validate_agent_result(envelope)
    return envelope


def result_hash(result: Mapping[str, Any]) -> str:
    projection = {
        key: value
        for key, value in result.items()
        if key not in {"result_hash", "result_id", "created_at"}
    }
    for field_name in SET_LIKE_RESULT_FIELDS:
        value = projection.get(field_name)
        if isinstance(value, list):
            projection[field_name] = sorted(value)
    digest = hashlib.sha256(_canonical_json(projection).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def derive_publication_identity(
    *, result_id: str, target_type: str, target_ref: str, result_hash_value: str
) -> tuple[str, str]:
    semantic = "|".join(
        (
            _required("result_id", result_id),
            _required("target_type", target_type),
            _required("target_ref", target_ref),
            _required("result_hash", result_hash_value),
        )
    ).encode("utf-8")
    digest = hashlib.sha256(semantic).hexdigest()
    return f"PUBOP:{digest}", f"PUBIDEMP:{digest}"


def execution_destination(result_status: str) -> tuple[str, str, bool]:
    if result_status in {"SUCCEEDED", "PARTIAL"}:
        return "RUNNING", "RESULT_PUBLISH", False
    if result_status in {"BLOCKED", "FAILED", "CANCELLED"}:
        return result_status, "FINALIZE", True
    raise _invalid("AgentResult status is outside the Frozen vocabulary.")


def validate_agent_result(result: Mapping[str, Any]) -> None:
    required = {
        "schema_version",
        "tenant_id",
        "result_id",
        "agent_execution_id",
        "agent_type",
        "status",
        "structured_result",
        "business_refs",
        "artifact_refs",
        "evidence_refs",
        "warnings",
        "conflicts",
        "provenance",
        "created_at",
        "result_hash",
    }
    if not required.issubset(result):
        raise _invalid("AgentResult is missing a Frozen-required field.")
    if result.get("schema_version") != "2.1" or result.get("agent_type") != "IA":
        raise _invalid("P4 requires the Frozen v2.1 IA AgentResult contract.")
    if result.get("status") not in AGENT_RESULT_STATUSES:
        raise _invalid("AgentResult status is outside the Frozen vocabulary.")
    if any(
        result.get(field) is not None
        for field in (
            "source_work_item_ref",
            "source_claim_ref",
            "source_claim_generation",
            "source_claimant_agent_id",
            "source_assignment_ref",
        )
    ):
        raise _invalid("P4 IA AgentResult cannot contain WC claim lineage.")
    if _contains_private_content(result):
        raise AgentResultError(
            "ae.agent_result_private_content_forbidden",
            "AgentResult stores references and hashes, not raw private content.",
        )
    if result.get("result_hash") != result_hash(result):
        raise AgentResultError(
            "ae.agent_result_hash_mismatch",
            "AgentResult hash does not match its semantic projection.",
        )


class SqlAlchemyAgentResultRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def persist_with_pending_delivery(
        self,
        *,
        result: Mapping[str, Any],
        delivery_id: str,
    ) -> AgentResultAggregate:
        return self._persist_with_pending_delivery(
            result=result,
            delivery_id=delivery_id,
            plan_authority=None,
        )

    def persist_plan_with_pending_delivery(
        self,
        *,
        result: Mapping[str, Any],
        delivery_id: str,
        executable_plan_id: str,
        step_result_hashes: Mapping[str, str],
        input_result_set_hash: str,
    ) -> AgentResultAggregate:
        return self._persist_with_pending_delivery(
            result=result,
            delivery_id=delivery_id,
            plan_authority={
                "executable_plan_id": _required(
                    "executable_plan_id", executable_plan_id
                ),
                "step_result_hashes": dict(step_result_hashes),
                "input_result_set_hash": _required(
                    "input_result_set_hash", input_result_set_hash
                ),
            },
        )

    def _persist_with_pending_delivery(
        self,
        *,
        result: Mapping[str, Any],
        delivery_id: str,
        plan_authority: Mapping[str, Any] | None,
    ) -> AgentResultAggregate:
        validate_agent_result(result)
        params = _result_params(result)
        params["delivery_id"] = _required("delivery_id", delivery_id)
        try:
            with self._session_factory() as session:
                execution = _load_execution_for_update(
                    session, params["tenant_id"], params["agent_execution_id"]
                )
                _require_execution_lineage(execution, result)
                existing = _load_result_by_execution(
                    session, params["tenant_id"], params["agent_execution_id"]
                )
                if existing is not None:
                    aggregate = _existing_aggregate(
                        session, execution, existing, result
                    )
                    session.commit()
                    return aggregate

                if plan_authority is None:
                    step = _load_terminal_step(
                        session, params["tenant_id"], params["agent_execution_id"]
                    )
                    _require_step_status(step, params["status"])
                else:
                    _require_plan_authority(
                        session,
                        execution=execution,
                        result=result,
                        authority=plan_authority,
                    )
                delivery = _pending_delivery(result, execution, params["delivery_id"])
                session.execute(
                    text(_result_insert_sql(_dialect_name(session))), params
                )
                self._insert_delivery(session, delivery)
                destination = execution_destination(params["status"])
                updated = session.execute(
                    text(_EXECUTION_RESULT_UPDATE_SQL),
                    {
                        "tenant_id": params["tenant_id"],
                        "agent_execution_id": params["agent_execution_id"],
                        "expected_version": execution["version"],
                        "result_id": params["result_id"],
                        "state": destination[0],
                        "phase": destination[1],
                        "completed_at": (
                            params["created_at"] if destination[2] else None
                        ),
                        "updated_at": params["created_at"],
                    },
                )
                if int(updated.rowcount or 0) != 1:
                    raise AgentResultError(
                        "ae.agent_result_execution_conflict",
                        "AgentExecution changed before AgentResult finalization.",
                        True,
                    )
                saved_execution = _load_execution_for_update(
                    session, params["tenant_id"], params["agent_execution_id"]
                )
                session.commit()
                return AgentResultAggregate(
                    result=dict(result),
                    delivery=delivery,
                    execution=saved_execution,
                )
        except AgentResultError:
            raise
        except SQLAlchemyError as exc:
            raise AgentResultError(
                "ae.agent_result_store_unavailable",
                "AE AgentResult store is unavailable.",
                True,
            ) from exc

    def get(self, tenant_id: str, result_id: str) -> AgentResultAggregate | None:
        try:
            with self._session_factory() as session:
                result = _load_result(session, tenant_id, result_id)
                if result is None:
                    return None
                delivery = _load_delivery(session, tenant_id, result_id)
                execution = _load_execution_for_update(
                    session, tenant_id, result["agent_execution_id"]
                )
                if delivery is None:
                    raise AgentResultError(
                        "ae.agent_result_delivery_missing",
                        "Canonical AgentResult is missing its required delivery.",
                    )
                return AgentResultAggregate(result, delivery, execution)
        except AgentResultError:
            raise
        except SQLAlchemyError as exc:
            raise AgentResultError(
                "ae.agent_result_store_unavailable",
                "AE AgentResult store is unavailable.",
                True,
            ) from exc

    def _insert_delivery(self, session: Session, delivery: Mapping[str, Any]) -> None:
        session.execute(text(_DELIVERY_INSERT_SQL), delivery)


def _legacy_status_quality(
    legacy_result: Mapping[str, Any],
) -> tuple[str, str | None, list[str]]:
    legacy_status = _required("status", legacy_result.get("status")).upper()
    if legacy_status == "NO_ANSWER":
        return "BLOCKED", None, []
    if legacy_status in {"FAILED", "CANCELLED"}:
        return legacy_status, None, []
    if legacy_status != "COMPLETED":
        raise _invalid("Legacy result is not terminal.")

    generation = _mapping(legacy_result.get("generation"))
    quality = _mapping(generation.get("grounded_response_quality"))
    boundary = str(quality.get("boundary_status") or "NOT_REQUIRED").upper()
    issue_count = quality.get("issue_count", 0)
    degraded = boundary in {"WARN", "UNKNOWN", "FAIL"} or (
        isinstance(issue_count, int)
        and not isinstance(issue_count, bool)
        and issue_count > 0
    )
    warnings: list[str] = []
    if degraded:
        warnings.append(f"ae.grounded_response_quality:{boundary.lower()}")
    retrieval = _mapping(legacy_result.get("retrieval"))
    quality_warnings = _mapping(retrieval.get("quality_warnings"))
    action = str(quality_warnings.get("recommended_action") or "proceed")
    if action != "proceed":
        degraded = True
        warnings.append(f"ae.retrieval_quality:{action}")
    if degraded:
        return "PARTIAL", "COMPLETE_WITH_WARNINGS", sorted(set(warnings))
    return "SUCCEEDED", "COMPLETE", []


def _structured_result_refs(step: Mapping[str, Any]) -> dict[str, Any]:
    values = {
        "compatibility_step_ref": step.get("executable_step_id"),
        "legacy_interaction_ref": step.get("result_ref")
        or f"ae-chat://interaction/{step.get('legacy_interaction_id')}",
        "retrieval_package_ref": step.get("retrieval_package_ref"),
        "retrieval_package_hash": step.get("retrieval_package_hash"),
        "cx_generation_ref": step.get("cx_generation_id"),
        "cx_job_ref": step.get("cx_job_id"),
        "generated_response_ref": step.get("generated_response_id"),
        "error_ref": step.get("error_ref"),
    }
    return {key: value for key, value in values.items() if value is not None}


def _artifact_references(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)):
        raise _invalid("artifact_refs must be an array.")
    refs: list[str] = []
    for item in value:
        if isinstance(item, str):
            refs.append(_required("artifact_ref", item))
            continue
        if isinstance(item, Mapping):
            ref = item.get("artifact_version_id") or item.get("artifact_id")
            refs.append(_required("artifact_ref", ref))
            continue
        raise _invalid("artifact_refs contains an invalid reference.")
    return sorted(set(refs))


def _reference_list(field: str, values: Iterable[str]) -> list[str]:
    if isinstance(values, (str, bytes)):
        raise _invalid(f"{field} must be an iterable of references.")
    return sorted({_required(field, value) for value in values})


def _input_result_set_hash(step: Mapping[str, Any]) -> str:
    projection = {
        key: step.get(key)
        for key in (
            "executable_step_id",
            "legacy_interaction_id",
            "retrieval_package_hash",
            "cx_generation_id",
            "cx_job_id",
            "generated_response_id",
            "result_ref",
            "error_ref",
            "state",
        )
    }
    return (
        "sha256:"
        + hashlib.sha256(_canonical_json(projection).encode("utf-8")).hexdigest()
    )


def _pending_delivery(
    result: Mapping[str, Any], execution: Mapping[str, Any], delivery_id: str
) -> dict[str, Any]:
    target_ref = _required("workspace_id", execution.get("workspace_id"))
    publication_operation_id, idempotency_key_ref = derive_publication_identity(
        result_id=str(result["result_id"]),
        target_type="WORKSPACE_RESULT",
        target_ref=target_ref,
        result_hash_value=str(result["result_hash"]),
    )
    created_at = str(result["created_at"])
    return {
        "schema_version": "2.1",
        "tenant_id": str(result["tenant_id"]),
        "delivery_id": delivery_id,
        "result_id": str(result["result_id"]),
        "agent_execution_id": str(result["agent_execution_id"]),
        "target_type": "WORKSPACE_RESULT",
        "target_ref": target_ref,
        "required": True,
        "state": "PENDING",
        "publication_operation_id": publication_operation_id,
        "idempotency_key_ref": idempotency_key_ref,
        "attempt_no": 0,
        "external_delivery_ref": None,
        "latest_preflight_ref": None,
        "publication_reconciliation_ref": None,
        "correlation_id": _required("correlation_id", execution.get("correlation_id")),
        "causation_id": execution.get("causation_id"),
        "created_at": created_at,
        "updated_at": created_at,
        "acknowledged_at": None,
    }


def _require_execution_lineage(
    execution: Mapping[str, Any], result: Mapping[str, Any]
) -> None:
    if not execution:
        raise AgentResultError(
            "ae.agent_result_execution_not_found", "AgentExecution was not found."
        )
    if (
        execution.get("agent_type") != "IA"
        or str(execution.get("agent_id")) != str(result.get("agent_id"))
        or execution.get("project_id") is not None
    ):
        raise _invalid("AgentResult does not match a project-neutral IA execution.")
    if execution.get("state") == "SUCCEEDED":
        raise AgentResultError(
            "ae.agent_result_delivery_ack_required",
            "P4 cannot create a result for an already succeeded execution.",
        )


def _require_step_status(step: Mapping[str, Any], result_status: str) -> None:
    if not step:
        raise AgentResultError(
            "ae.agent_result_step_not_found",
            "AgentResult requires its terminal compatibility step.",
        )
    if step.get("state") != _TERMINAL_STEP_BY_RESULT[result_status]:
        raise _invalid(
            "AgentResult status does not match terminal ExecutableStep state."
        )


def _require_plan_authority(
    session: Session,
    *,
    execution: Mapping[str, Any],
    result: Mapping[str, Any],
    authority: Mapping[str, Any],
) -> None:
    if execution.get("state") != "RUNNING" or execution.get("phase") != "RESULT_VERIFY":
        raise AgentResultError(
            "ae.agent_result_plan_not_ready",
            "P5 AgentResult requires RUNNING / RESULT_VERIFY authority.",
        )
    plan_id = _required("executable_plan_id", authority.get("executable_plan_id"))
    plan_exists = session.execute(
        text(
            "SELECT 1 FROM ae_executable_plan WHERE tenant_id = :tenant_id "
            "AND executable_plan_id = :plan_id "
            "AND agent_execution_id = :execution_id "
            "AND NOT EXISTS (SELECT 1 FROM ae_executable_plan newer "
            "WHERE newer.tenant_id = :tenant_id "
            "AND newer.agent_execution_id = :execution_id "
            "AND newer.executable_plan_version > "
            "ae_executable_plan.executable_plan_version)"
        ),
        {
            "tenant_id": result["tenant_id"],
            "plan_id": plan_id,
            "execution_id": result["agent_execution_id"],
        },
    ).first()
    if plan_exists is None:
        raise AgentResultError(
            "ae.agent_result_plan_not_found",
            "P5 AgentResult requires its exact persisted ExecutablePlan.",
        )
    expected_hashes = authority.get("step_result_hashes")
    if not isinstance(expected_hashes, Mapping) or not expected_hashes:
        raise _invalid("P5 AgentResult requires a StepResult hash set.")
    rows = (
        session.execute(
            text(
                "SELECT compiled_step_key, result_hash FROM ae_step_result "
                "WHERE tenant_id = :tenant_id AND executable_plan_id = :plan_id"
            ),
            {"tenant_id": result["tenant_id"], "plan_id": plan_id},
        )
        .mappings()
        .all()
    )
    stored_hashes = {str(row["compiled_step_key"]): row["result_hash"] for row in rows}
    if stored_hashes != dict(expected_hashes):
        raise AgentResultError(
            "ae.agent_result_step_set_conflict",
            "Persisted StepResult set changed before AgentResult finalization.",
            True,
        )
    provenance_value = result.get("provenance")
    provenance = provenance_value if isinstance(provenance_value, Mapping) else {}
    input_hash = provenance.get("input_result_set_hash")
    if (
        input_hash != authority.get("input_result_set_hash")
        or provenance.get("executable_plan_id") != plan_id
    ):
        raise _invalid(
            "P5 AgentResult provenance does not match finalization authority."
        )


def _existing_aggregate(
    session: Session,
    execution: Mapping[str, Any],
    existing: dict[str, Any],
    candidate: Mapping[str, Any],
) -> AgentResultAggregate:
    if existing["result_id"] != str(candidate.get("result_id")) or existing[
        "result_hash"
    ] != candidate.get("result_hash"):
        raise AgentResultError(
            "ae.agent_result_semantic_conflict",
            "AgentExecution already has a different immutable AgentResult.",
        )
    delivery = _load_delivery(session, existing["tenant_id"], existing["result_id"])
    if delivery is None:
        raise AgentResultError(
            "ae.agent_result_delivery_missing",
            "Canonical AgentResult is missing its required delivery.",
        )
    return AgentResultAggregate(existing, delivery, dict(execution))


def _result_params(result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "tenant_id": _required("tenant_id", result.get("tenant_id")),
        "result_id": _required("result_id", result.get("result_id")),
        "agent_execution_id": _required(
            "agent_execution_id", result.get("agent_execution_id")
        ),
        "agent_type": result.get("agent_type"),
        "agent_id": _optional("agent_id", result.get("agent_id")),
        "project_id": _optional("project_id", result.get("project_id")),
        "status": result.get("status"),
        "quality": _optional("quality", result.get("quality")),
        "structured_result_json": _canonical_json(result["structured_result"]),
        "result_envelope_json": _canonical_json(result),
        "result_hash": result.get("result_hash"),
        "source_work_item_ref": result.get("source_work_item_ref"),
        "source_claim_ref": result.get("source_claim_ref"),
        "source_claim_generation": result.get("source_claim_generation"),
        "source_claimant_agent_id": result.get("source_claimant_agent_id"),
        "source_assignment_ref": result.get("source_assignment_ref"),
        "created_at": _timestamp("created_at", result.get("created_at")),
    }


def _result_insert_sql(dialect_name: str) -> str:
    structured = (
        "CAST(:structured_result_json AS JSONB)"
        if dialect_name == "postgresql"
        else ":structured_result_json"
    )
    envelope = (
        "CAST(:result_envelope_json AS JSONB)"
        if dialect_name == "postgresql"
        else ":result_envelope_json"
    )
    return f"""
        INSERT INTO ae_agent_result (
            tenant_id, result_id, agent_execution_id, agent_type, agent_id,
            project_id, status, quality, structured_result_json,
            result_envelope_json, result_hash, source_work_item_ref,
            source_claim_ref, source_claim_generation,
            source_claimant_agent_id, source_assignment_ref, created_at
        ) VALUES (
            :tenant_id, :result_id, :agent_execution_id, :agent_type, :agent_id,
            :project_id, :status, :quality, {structured}, {envelope},
            :result_hash, :source_work_item_ref, :source_claim_ref,
            :source_claim_generation, :source_claimant_agent_id,
            :source_assignment_ref, :created_at
        )
    """


_DELIVERY_INSERT_SQL = """
    INSERT INTO ae_result_delivery (
        tenant_id, delivery_id, result_id, agent_execution_id, target_type,
        target_ref, required, state, publication_operation_id,
        idempotency_key_ref, attempt_no, external_delivery_ref,
        latest_preflight_ref, publication_reconciliation_ref, correlation_id,
        causation_id, created_at, updated_at, acknowledged_at
    ) VALUES (
        :tenant_id, :delivery_id, :result_id, :agent_execution_id, :target_type,
        :target_ref, :required, :state, :publication_operation_id,
        :idempotency_key_ref, :attempt_no, :external_delivery_ref,
        :latest_preflight_ref, :publication_reconciliation_ref, :correlation_id,
        :causation_id, :created_at, :updated_at, :acknowledged_at
    )
"""

_EXECUTION_RESULT_UPDATE_SQL = """
    UPDATE ae_agent_execution
    SET state = :state, phase = :phase, result_id = :result_id,
        completed_at = :completed_at, version = version + 1,
        updated_at = :updated_at
    WHERE tenant_id = :tenant_id
      AND agent_execution_id = :agent_execution_id
      AND version = :expected_version
      AND result_id IS NULL
      AND state <> 'SUCCEEDED'
"""


def _load_execution_for_update(
    session: Session, tenant_id: str, execution_id: str
) -> dict[str, Any]:
    suffix = " FOR UPDATE" if _dialect_name(session) == "postgresql" else ""
    row = (
        session.execute(
            text("""
            SELECT tenant_id, agent_execution_id, agent_id, agent_type,
                   project_id, workspace_id, state, phase, version, result_id,
                   correlation_id, causation_id, completed_at
            FROM ae_agent_execution
            WHERE tenant_id = :tenant_id
              AND agent_execution_id = :agent_execution_id
            """ + suffix),
            {"tenant_id": tenant_id, "agent_execution_id": execution_id},
        )
        .mappings()
        .first()
    )
    return {} if row is None else _row_dict(row)


def _load_terminal_step(
    session: Session, tenant_id: str, execution_id: str
) -> dict[str, Any]:
    row = (
        session.execute(
            text("""
            SELECT tenant_id, executable_step_id, agent_execution_id, state
            FROM ae_executable_step
            WHERE tenant_id = :tenant_id
              AND agent_execution_id = :agent_execution_id
              AND step_kind = 'P4_CHAT_RAG_COMPATIBILITY'
            """),
            {"tenant_id": tenant_id, "agent_execution_id": execution_id},
        )
        .mappings()
        .first()
    )
    return {} if row is None else _row_dict(row)


def _load_result_by_execution(
    session: Session, tenant_id: str, execution_id: str
) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                _RESULT_SELECT_SQL
                + " WHERE tenant_id = :tenant_id AND agent_execution_id = :execution_id"
            ),
            {"tenant_id": tenant_id, "execution_id": execution_id},
        )
        .mappings()
        .first()
    )
    return None if row is None else _result_from_row(row)


def _load_result(
    session: Session, tenant_id: str, result_id: str
) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                _RESULT_SELECT_SQL
                + " WHERE tenant_id = :tenant_id AND result_id = :result_id"
            ),
            {"tenant_id": tenant_id, "result_id": result_id},
        )
        .mappings()
        .first()
    )
    return None if row is None else _result_from_row(row)


_RESULT_SELECT_SQL = """
    SELECT tenant_id, result_id, agent_execution_id, result_envelope_json,
           result_hash
    FROM ae_agent_result
"""


def _result_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    envelope = _json_value(row["result_envelope_json"])
    envelope["tenant_id"] = row["tenant_id"]
    envelope["result_id"] = str(row["result_id"])
    envelope["agent_execution_id"] = str(row["agent_execution_id"])
    envelope["result_hash"] = row["result_hash"]
    return envelope


def _load_delivery(
    session: Session, tenant_id: str, result_id: str
) -> dict[str, Any] | None:
    row = (
        session.execute(
            text("""
            SELECT tenant_id, delivery_id, result_id, agent_execution_id,
                   target_type, target_ref, required, state,
                   publication_operation_id, idempotency_key_ref, attempt_no,
                   external_delivery_ref, latest_preflight_ref,
                   publication_reconciliation_ref, correlation_id,
                   causation_id, created_at, updated_at, acknowledged_at
            FROM ae_result_delivery
            WHERE tenant_id = :tenant_id AND result_id = :result_id
              AND target_type = 'WORKSPACE_RESULT'
            """),
            {"tenant_id": tenant_id, "result_id": result_id},
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    delivery = _row_dict(row)
    delivery["schema_version"] = "2.1"
    return delivery


def _row_dict(row: Mapping[str, Any]) -> dict[str, Any]:
    result = {key: value for key, value in row.items()}
    for key in (
        "agent_execution_id",
        "agent_id",
        "workspace_id",
        "result_id",
        "delivery_id",
        "executable_step_id",
    ):
        if key in result and result[key] is not None:
            result[key] = str(result[key])
    for key in ("created_at", "updated_at", "completed_at", "acknowledged_at"):
        if key in result and result[key] is not None:
            result[key] = _datetime_value(result[key])
    if "required" in result:
        result["required"] = bool(result["required"])
    if "version" in result:
        result["version"] = int(result["version"])
    if "attempt_no" in result:
        result["attempt_no"] = int(result["attempt_no"])
    return result


def _contains_private_content(value: object) -> bool:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).lower() in _FORBIDDEN_PRIVATE_KEYS:
                return True
            if _contains_private_content(child):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_contains_private_content(item) for item in value)
    return False


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise _invalid("AgentResult contains a non-canonical JSON value.") from exc


def _json_value(value: object) -> dict[str, Any]:
    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, dict):
        raise AgentResultError(
            "ae.agent_result_envelope_invalid",
            "Stored AgentResult envelope is not an object.",
        )
    return dict(decoded)


def _required(field: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"{field} must be a non-empty string.")
    return value.strip()


def _optional(field: str, value: object) -> str | None:
    if value is None:
        return None
    return _required(field, value)


def _timestamp(field: str, value: object) -> str:
    raw = _required(field, value)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid(f"{field} must be an RFC 3339 timestamp.") from exc
    if parsed.tzinfo is None:
        raise _invalid(f"{field} must include a timezone.")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _datetime_value(value: object) -> str:
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if hasattr(value, "isoformat"):
        return value.isoformat().replace("+00:00", "Z")  # type: ignore[union-attr]
    return str(value)


def _dialect_name(session: Session) -> str:
    return session.get_bind().dialect.name


def _invalid(detail: str) -> AgentResultError:
    return AgentResultError("ae.agent_result_invalid", detail)
