from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_ae_api.agent_identity import (
    AgentIdentityRepositoryError,
    SqlAlchemyAgentIdentityRegistry,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

AGENT_RUNTIME_MODE_ENV = "NEX_AE_AGENT_RUNTIME_MODE"
AGENT_RUNTIME_MODES = frozenset({"disabled", "shadow", "required"})
AGENT_EXECUTION_STATES = frozenset(
    {
        "QUEUED",
        "RUNNING",
        "WAITING_INPUT",
        "WAITING_CONFIRMATION",
        "WAITING_APPROVAL",
        "WAITING_DEPENDENCY",
        "RECONCILIATION_REQUIRED",
        "SUCCEEDED",
        "FAILED",
        "BLOCKED",
        "ESCALATED",
        "CANCELLED",
    }
)
AGENT_EXECUTION_PHASES = frozenset(
    {
        "INTAKE",
        "BASE_CONTEXT",
        "INTENT_RESOLUTION",
        "CONTEXT_EXPANSION",
        "PLAN_BUILD",
        "PLAN_VALIDATE",
        "PLAN_COMPILE",
        "STEP_EXECUTION",
        "RESULT_VERIFY",
        "RESULT_SYNTHESIS",
        "RESULT_PUBLISH",
        "FINALIZE",
    }
)


@dataclass(frozen=True)
class AgentExecutionError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class ExecutionTriggerV21:
    trigger_id: str
    source_type: Literal["PROMPT", "CLAIMED_WORKITEM"]
    source_ref: str
    tenant_id: str
    agent_type: Literal["IA", "CA", "PA", "EA"]
    agent_id: str
    project_id: str | None
    correlation_id: str
    received_at: str
    work_item_ref: str | None = None
    claim_ref: str | None = None
    claim_generation: int | None = None
    assignment_ref: str | None = None
    requester_ref: str | None = None
    causation_id: str | None = None
    schema_version: str = "2.1"

    def __post_init__(self) -> None:
        if self.schema_version != "2.1":
            raise _invalid("ExecutionTrigger schema_version must be 2.1.")
        for field_name in (
            "trigger_id",
            "source_ref",
            "tenant_id",
            "agent_id",
            "correlation_id",
            "received_at",
        ):
            _required_text(field_name, getattr(self, field_name))
        _optional_non_empty("project_id", self.project_id)
        _optional_non_empty("causation_id", self.causation_id)
        if self.claim_generation is not None and (
            isinstance(self.claim_generation, bool)
            or not isinstance(self.claim_generation, int)
            or self.claim_generation < 1
        ):
            raise _invalid("claim_generation must be at least 1 when present.")
        if self.source_type == "PROMPT":
            if self.agent_type != "IA":
                raise _invalid("PROMPT requires agent_type=IA.")
            return
        if self.source_type != "CLAIMED_WORKITEM":
            raise _invalid("ExecutionTrigger source_type is unsupported.")
        if self.agent_type not in {"CA", "PA", "EA"}:
            raise _invalid("CLAIMED_WORKITEM requires agent_type=CA|PA|EA.")
        for field_name in (
            "project_id",
            "work_item_ref",
            "claim_ref",
            "assignment_ref",
        ):
            _required_text(field_name, getattr(self, field_name))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AgentRuntimeAdmission:
    mode: str
    execution: dict[str, Any] | None
    shadow_error_code: str | None = None


def agent_runtime_mode(environ: Mapping[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    mode = str(env.get(AGENT_RUNTIME_MODE_ENV, "disabled")).strip().lower()
    if mode not in AGENT_RUNTIME_MODES:
        raise AgentExecutionError(
            "ae.agent_runtime_mode_invalid",
            "AE Agent Runtime mode must be disabled, shadow, or required.",
        )
    return mode


class SqlAlchemyAgentExecutionRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def admit_prompt(
        self,
        *,
        trigger: ExecutionTriggerV21,
        principal_id: str,
        agent_execution_id: str,
        workspace_id: str | None,
        conversation_id: str | None,
        legacy_interaction_id: str | None,
        now: str,
    ) -> dict[str, Any]:
        if trigger.source_type != "PROMPT" or trigger.agent_type != "IA":
            raise _invalid("P4 admits only PROMPT triggers for IA.")
        params = {
            **trigger.to_dict(),
            "principal_id": _required_text("principal_id", principal_id),
            "agent_execution_id": _required_text(
                "agent_execution_id", agent_execution_id
            ),
            "workspace_id": _optional_non_empty("workspace_id", workspace_id),
            "conversation_id": _optional_non_empty(
                "conversation_id", conversation_id
            ),
            "legacy_interaction_id": _optional_non_empty(
                "legacy_interaction_id", legacy_interaction_id
            ),
            "now": _required_text("now", now),
        }
        try:
            with self._session_factory() as session:
                _require_admission_scope(session, params)
                inserted = session.execute(text(_EXECUTION_INSERT_SQL), params)
                saved = _load_by_trigger(session, trigger.tenant_id, trigger.trigger_id)
                if saved is None:
                    raise AgentExecutionError(
                        "ae.agent_execution_write_conflict",
                        "AgentExecution could not be reloaded after admission.",
                        True,
                    )
                if int(inserted.rowcount or 0) == 0:
                    _require_same_admission(saved, params)
                session.commit()
                return saved
        except AgentExecutionError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def admit_claimed_work(
        self,
        *,
        event_id: str,
        handoff_semantic_hash: str,
        trigger: ExecutionTriggerV21,
        principal_id: str,
        agent_execution_id: str,
        now: str,
    ) -> dict[str, Any]:
        if trigger.source_type != "CLAIMED_WORKITEM" or trigger.agent_type not in {
            "CA",
            "PA",
            "EA",
        }:
            raise _invalid("P7 claimed-work admission requires a background Agent.")
        params = {
            **trigger.to_dict(),
            "event_id": _required_text("event_id", event_id),
            "handoff_semantic_hash": _required_text(
                "handoff_semantic_hash", handoff_semantic_hash
            ),
            "principal_id": _required_text("principal_id", principal_id),
            "agent_execution_id": _required_text(
                "agent_execution_id", agent_execution_id
            ),
            "workspace_id": None,
            "conversation_id": None,
            "legacy_interaction_id": None,
            "now": _required_text("now", now),
        }
        try:
            with self._session_factory() as session:
                _require_claimed_work_scope(session, params)
                inserted = session.execute(text(_EXECUTION_INSERT_SQL), params)
                saved = _load_by_trigger(session, trigger.tenant_id, trigger.trigger_id)
                if saved is None:
                    raise AgentExecutionError(
                        "ae.agent_execution_write_conflict",
                        "AgentExecution could not be reloaded after admission.",
                        True,
                    )
                if int(inserted.rowcount or 0) == 0:
                    _require_same_admission(saved, params)
                session.execute(text(_CLAIM_HANDOFF_INBOX_INSERT_SQL), params)
                receipt = _load_claim_handoff_receipt(
                    session,
                    tenant_id=trigger.tenant_id,
                    event_id=event_id,
                    handoff_id=trigger.trigger_id,
                )
                _require_same_handoff_receipt(receipt, params, saved)
                session.commit()
                return saved
        except AgentExecutionError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def get(self, tenant_id: str, agent_execution_id: str) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                return _load_execution(session, tenant_id, agent_execution_id)
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def transition(
        self,
        *,
        tenant_id: str,
        agent_execution_id: str,
        expected_version: int,
        state: str,
        phase: str,
        updated_at: str,
        result_id: str | None = None,
    ) -> dict[str, Any]:
        if state not in AGENT_EXECUTION_STATES:
            raise _invalid("AgentExecution state is outside the Frozen vocabulary.")
        if phase not in AGENT_EXECUTION_PHASES:
            raise _invalid("AgentExecution phase is outside the Frozen vocabulary.")
        if state == "SUCCEEDED":
            raise AgentExecutionError(
                "ae.agent_execution_delivery_ack_required",
                "P4 cannot succeed AgentExecution before durable delivery ACK exists.",
            )
        if (
            isinstance(expected_version, bool)
            or not isinstance(expected_version, int)
            or expected_version < 1
        ):
            raise _invalid("AgentExecution expected_version is invalid.")
        params = {
            "tenant_id": _required_text("tenant_id", tenant_id),
            "agent_execution_id": _required_text(
                "agent_execution_id", agent_execution_id
            ),
            "expected_version": expected_version,
            "state": state,
            "phase": phase,
            "result_id": _optional_non_empty("result_id", result_id),
            "updated_at": _required_text("updated_at", updated_at),
        }
        try:
            with self._session_factory() as session:
                updated = session.execute(text(_EXECUTION_TRANSITION_SQL), params)
                if int(updated.rowcount or 0) == 0:
                    existing = _load_execution(session, tenant_id, agent_execution_id)
                    if existing is None:
                        raise AgentExecutionError(
                            "ae.agent_execution_not_found",
                            "AgentExecution was not found.",
                        )
                    raise AgentExecutionError(
                        "ae.agent_execution_version_conflict",
                        "AgentExecution version changed before transition.",
                        True,
                    )
                saved = _load_execution(session, tenant_id, agent_execution_id)
                if saved is None:
                    raise AgentExecutionError(
                        "ae.agent_execution_write_conflict",
                        "AgentExecution disappeared after transition.",
                        True,
                    )
                session.commit()
                return saved
        except AgentExecutionError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc


class AgentExecutionAdmissionService:
    def __init__(
        self,
        *,
        identities: SqlAlchemyAgentIdentityRegistry,
        executions: SqlAlchemyAgentExecutionRepository,
        mode: str = "disabled",
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if mode not in AGENT_RUNTIME_MODES:
            raise AgentExecutionError(
                "ae.agent_runtime_mode_invalid",
                "AE Agent Runtime mode must be disabled, shadow, or required.",
            )
        self._identities = identities
        self._executions = executions
        self._mode = mode
        self._id_factory = id_factory or (lambda: str(uuid4()))
        self._clock = clock or (lambda: datetime.now(UTC))

    def admit_prompt(
        self,
        *,
        tenant_id: str,
        principal_id: str,
        profile_ref: str,
        trigger_id: str,
        interaction_id: str,
        workspace_id: str | None,
        conversation_id: str | None,
        correlation_id: str,
        causation_id: str | None = None,
        project_id: str | None = None,
    ) -> AgentRuntimeAdmission:
        if self._mode == "disabled":
            return AgentRuntimeAdmission(mode="disabled", execution=None)
        try:
            resolved = self._identities.resolve_or_provision_ia(
                tenant_id=tenant_id,
                principal_id=principal_id,
                profile_ref=profile_ref,
            )
            now = self._clock().astimezone(UTC).isoformat().replace("+00:00", "Z")
            trigger = ExecutionTriggerV21(
                trigger_id=trigger_id,
                source_type="PROMPT",
                source_ref=interaction_id,
                tenant_id=tenant_id,
                agent_type="IA",
                agent_id=str(resolved.identity["agent_id"]),
                project_id=project_id,
                correlation_id=correlation_id,
                causation_id=causation_id,
                received_at=now,
                requester_ref=principal_id,
            )
            execution = self._executions.admit_prompt(
                trigger=trigger,
                principal_id=principal_id,
                agent_execution_id=self._id_factory(),
                workspace_id=workspace_id,
                conversation_id=conversation_id,
                legacy_interaction_id=interaction_id,
                now=now,
            )
            return AgentRuntimeAdmission(mode=self._mode, execution=execution)
        except (AgentIdentityRepositoryError, AgentExecutionError) as exc:
            if self._mode == "shadow":
                return AgentRuntimeAdmission(
                    mode="shadow",
                    execution=None,
                    shadow_error_code=exc.error_code,
                )
            raise

    def admit_claimed_work(
        self,
        *,
        event_id: str,
        requester_ref: str,
        handoff: Mapping[str, Any],
    ) -> AgentRuntimeAdmission:
        if self._mode != "required":
            raise AgentExecutionError(
                "ae.background_agent_runtime_disabled",
                "Claimed WorkItem admission requires required Agent Runtime mode.",
            )
        normalized = _validate_claim_handoff(handoff)
        try:
            identity = self._identities.get_agent(
                tenant_id=normalized["tenant_id"],
                agent_id=normalized["claimant_agent_ref"],
            )
            if identity is None or (
                identity.get("status"),
                identity.get("agent_type"),
                identity.get("project_id"),
            ) != (
                "ACTIVE",
                normalized["claimant_agent_type"],
                normalized["project_id"],
            ):
                raise AgentExecutionError(
                    "ae.claimed_work_identity_forbidden",
                    "Claimed work requires the exact active tenant/project Agent.",
                )
            now = self._clock().astimezone(UTC).isoformat().replace("+00:00", "Z")
            trigger = ExecutionTriggerV21(
                trigger_id=normalized["handoff_id"],
                source_type="CLAIMED_WORKITEM",
                source_ref=normalized["work_item_ref"],
                tenant_id=normalized["tenant_id"],
                agent_type=normalized["claimant_agent_type"],
                agent_id=normalized["claimant_agent_ref"],
                project_id=normalized["project_id"],
                correlation_id=normalized["correlation_id"],
                causation_id=normalized.get("causation_id"),
                received_at=normalized["occurred_at"],
                work_item_ref=normalized["work_item_ref"],
                claim_ref=normalized["claim_ref"],
                claim_generation=normalized["claim_generation"],
                assignment_ref=normalized["assignment_ref"],
                requester_ref=_required_text("requester_ref", requester_ref),
            )
            execution = self._executions.admit_claimed_work(
                event_id=_required_text("event_id", event_id),
                handoff_semantic_hash=semantic_sha256_hash_ref(normalized),
                trigger=trigger,
                principal_id=requester_ref,
                agent_execution_id=self._id_factory(),
                now=now,
            )
            return AgentRuntimeAdmission(mode=self._mode, execution=execution)
        except (AgentIdentityRepositoryError, AgentExecutionError):
            raise


_EXECUTION_INSERT_SQL = """
    INSERT INTO ae_agent_execution (
        tenant_id, agent_execution_id, agent_id, agent_type, principal_id,
        trigger_schema_version, trigger_id, source_type, source_ref, project_id,
        workspace_id, conversation_id, legacy_interaction_id, state, phase,
        version, result_id, correlation_id, causation_id, received_at,
        work_item_ref, claim_ref, claim_generation, assignment_ref,
        requester_ref, created_at, updated_at
    ) VALUES (
        :tenant_id, :agent_execution_id, :agent_id, :agent_type, :principal_id,
        :schema_version, :trigger_id, :source_type, :source_ref, :project_id,
        :workspace_id, :conversation_id, :legacy_interaction_id,
        'QUEUED', 'INTAKE', 1, NULL, :correlation_id, :causation_id,
        :received_at, :work_item_ref, :claim_ref, :claim_generation,
        :assignment_ref, :requester_ref, :now, :now
    ) ON CONFLICT (tenant_id, trigger_id) DO NOTHING
"""

_CLAIM_HANDOFF_INBOX_INSERT_SQL = """
    INSERT INTO ae_claim_handoff_inbox (
        tenant_id, event_id, handoff_id, handoff_semantic_hash,
        agent_execution_id, received_at
    ) VALUES (
        :tenant_id, :event_id, :trigger_id, :handoff_semantic_hash,
        :agent_execution_id, :now
    ) ON CONFLICT DO NOTHING
"""

_EXECUTION_TRANSITION_SQL = """
    UPDATE ae_agent_execution
    SET state = :state,
        phase = :phase,
        result_id = COALESCE(:result_id, result_id),
        version = version + 1,
        updated_at = :updated_at
    WHERE tenant_id = :tenant_id
      AND agent_execution_id = :agent_execution_id
      AND version = :expected_version
"""


def _require_admission_scope(session: Session, params: Mapping[str, Any]) -> None:
    identity = session.execute(
        text(
            """
            SELECT i.agent_type, i.status, i.project_id, a.status AS assignment_status
            FROM ae_agent_identity AS i
            JOIN ae_ia_principal_assignment AS a
              ON a.tenant_id = i.tenant_id AND a.agent_id = i.agent_id
            WHERE i.tenant_id = :tenant_id AND i.agent_id = :agent_id
              AND a.principal_id = :principal_id
            """
        ),
        params,
    ).mappings().first()
    if identity is None or (
        identity["agent_type"],
        identity["status"],
        identity["project_id"],
        identity["assignment_status"],
    ) != ("IA", "ACTIVE", None, "ACTIVE"):
        raise AgentExecutionError(
            "ae.agent_execution_identity_forbidden",
            "Prompt admission requires the principal's active project-neutral IA.",
        )
    if params["conversation_id"] is None:
        return
    conversation = session.execute(
        text(
            """
            SELECT workspace_id, tenant_id, owner_user_id
            FROM ae_conversations WHERE conversation_id = :conversation_id
            """
        ),
        params,
    ).mappings().first()
    if conversation is None or (
        str(conversation["workspace_id"]),
        conversation["tenant_id"],
        conversation["owner_user_id"],
    ) != (
        str(params["workspace_id"]),
        params["tenant_id"],
        params["principal_id"],
    ):
        raise AgentExecutionError(
            "ae.agent_execution_conversation_forbidden",
            "Prompt admission Conversation is outside the principal scope.",
        )


def _require_claimed_work_scope(
    session: Session, params: Mapping[str, Any]
) -> None:
    identity = session.execute(
        text(
            """
            SELECT agent_type, status, project_id
            FROM ae_agent_identity
            WHERE tenant_id = :tenant_id AND agent_id = :agent_id
            """
        ),
        params,
    ).mappings().first()
    if identity is None or (
        identity["agent_type"],
        identity["status"],
        identity["project_id"],
    ) != (
        params["agent_type"],
        "ACTIVE",
        params["project_id"],
    ):
        raise AgentExecutionError(
            "ae.claimed_work_identity_forbidden",
            "Claimed work requires the exact active tenant/project Agent.",
        )


def _load_by_trigger(
    session: Session,
    tenant_id: str,
    trigger_id: str,
) -> dict[str, Any] | None:
    row = session.execute(
        text(_EXECUTION_SELECT_SQL + " WHERE tenant_id = :tenant_id AND trigger_id = :trigger_id"),
        {"tenant_id": tenant_id, "trigger_id": trigger_id},
    ).mappings().first()
    return None if row is None else _execution_from_row(row)


def _load_execution(
    session: Session,
    tenant_id: str,
    agent_execution_id: str,
) -> dict[str, Any] | None:
    row = session.execute(
        text(
            _EXECUTION_SELECT_SQL
            + " WHERE tenant_id = :tenant_id AND agent_execution_id = :agent_execution_id"
        ),
        {"tenant_id": tenant_id, "agent_execution_id": agent_execution_id},
    ).mappings().first()
    return None if row is None else _execution_from_row(row)


def _load_claim_handoff_receipt(
    session: Session,
    *,
    tenant_id: str,
    event_id: str,
    handoff_id: str,
) -> dict[str, Any] | None:
    row = session.execute(
        text(
            """
            SELECT tenant_id, event_id, handoff_id, handoff_semantic_hash,
                   agent_execution_id, received_at
            FROM ae_claim_handoff_inbox
            WHERE tenant_id = :tenant_id
              AND (event_id = :event_id OR handoff_id = :handoff_id)
            ORDER BY CASE WHEN event_id = :event_id THEN 0 ELSE 1 END
            LIMIT 1
            """
        ),
        {
            "tenant_id": tenant_id,
            "event_id": event_id,
            "handoff_id": handoff_id,
        },
    ).mappings().first()
    if row is None:
        return None
    return {
        "tenant_id": row["tenant_id"],
        "event_id": str(row["event_id"]),
        "handoff_id": str(row["handoff_id"]),
        "handoff_semantic_hash": row["handoff_semantic_hash"],
        "agent_execution_id": str(row["agent_execution_id"]),
        "received_at": _datetime_value(row["received_at"]),
    }


_EXECUTION_SELECT_SQL = """
    SELECT tenant_id, agent_execution_id, agent_id, agent_type, principal_id,
           trigger_schema_version, trigger_id, source_type, source_ref,
           project_id, workspace_id, conversation_id, legacy_interaction_id,
           state, phase, version, result_id, correlation_id, causation_id,
           received_at, work_item_ref, claim_ref, claim_generation,
           assignment_ref, requester_ref, created_at, updated_at
    FROM ae_agent_execution
"""


def _execution_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "tenant_id": row["tenant_id"],
        "agent_execution_id": str(row["agent_execution_id"]),
        "agent_id": str(row["agent_id"]),
        "agent_type": row["agent_type"],
        "principal_id": row["principal_id"],
        "trigger_schema_version": row["trigger_schema_version"],
        "trigger_id": str(row["trigger_id"]),
        "source_type": row["source_type"],
        "source_ref": row["source_ref"],
        "project_id": row["project_id"],
        "workspace_id": _string_or_none(row["workspace_id"]),
        "conversation_id": _string_or_none(row["conversation_id"]),
        "legacy_interaction_id": _string_or_none(row["legacy_interaction_id"]),
        "state": row["state"],
        "phase": row["phase"],
        "version": int(row["version"]),
        "result_id": _string_or_none(row["result_id"]),
        "correlation_id": row["correlation_id"],
        "causation_id": row["causation_id"],
        "received_at": _datetime_value(row["received_at"]),
        "work_item_ref": _string_or_none(row["work_item_ref"]),
        "claim_ref": _string_or_none(row["claim_ref"]),
        "claim_generation": (
            None if row["claim_generation"] is None else int(row["claim_generation"])
        ),
        "assignment_ref": _string_or_none(row["assignment_ref"]),
        "requester_ref": _string_or_none(row["requester_ref"]),
        "created_at": _datetime_value(row["created_at"]),
        "updated_at": _datetime_value(row["updated_at"]),
    }


def _require_same_admission(
    existing: Mapping[str, Any],
    params: Mapping[str, Any],
) -> None:
    keys = (
        "agent_id",
        "principal_id",
        "source_type",
        "source_ref",
        "project_id",
        "workspace_id",
        "conversation_id",
        "legacy_interaction_id",
        "correlation_id",
        "causation_id",
        "work_item_ref",
        "claim_ref",
        "claim_generation",
        "assignment_ref",
        "requester_ref",
    )
    if any(_comparable(existing[key]) != _comparable(params[key]) for key in keys):
        raise AgentExecutionError(
            "ae.agent_execution_trigger_conflict",
            "ExecutionTrigger identity was reused with different semantics.",
        )


def _require_same_handoff_receipt(
    receipt: Mapping[str, Any] | None,
    params: Mapping[str, Any],
    execution: Mapping[str, Any],
) -> None:
    if receipt is None:
        raise AgentExecutionError(
            "ae.claim_handoff_write_conflict",
            "Claim handoff receipt could not be reloaded after admission.",
            True,
        )
    expected = {
        "event_id": params["event_id"],
        "handoff_id": params["trigger_id"],
        "handoff_semantic_hash": params["handoff_semantic_hash"],
        "agent_execution_id": execution["agent_execution_id"],
    }
    if any(
        _comparable(receipt[key]) != _comparable(value)
        for key, value in expected.items()
    ):
        raise AgentExecutionError(
            "ae.claim_handoff_conflict",
            "Claim handoff identity was reused with different semantics.",
        )


_CLAIM_HANDOFF_FIELDS = frozenset(
    {
        "schema_version",
        "handoff_id",
        "tenant_id",
        "work_item_ref",
        "claim_ref",
        "claim_generation",
        "claimant_agent_ref",
        "claimant_agent_type",
        "project_id",
        "assignment_ref",
        "correlation_id",
        "causation_id",
        "occurred_at",
    }
)


def _validate_claim_handoff(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid("ClaimExecutionHandoff must be an object.")
    if set(value) - _CLAIM_HANDOFF_FIELDS:
        raise _invalid("ClaimExecutionHandoff contains unsupported fields.")
    normalized = dict(value)
    if normalized.get("schema_version") != "2.1":
        raise _invalid("ClaimExecutionHandoff schema_version must be 2.1.")
    for field in (
        "handoff_id",
        "tenant_id",
        "work_item_ref",
        "claim_ref",
        "claimant_agent_ref",
        "project_id",
        "assignment_ref",
        "correlation_id",
        "occurred_at",
    ):
        normalized[field] = _required_text(field, normalized.get(field))
    if normalized.get("claimant_agent_type") not in {"CA", "PA", "EA"}:
        raise _invalid("ClaimExecutionHandoff claimant_agent_type is invalid.")
    generation = normalized.get("claim_generation")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
        raise _invalid("ClaimExecutionHandoff claim_generation is invalid.")
    normalized["causation_id"] = _optional_non_empty(
        "causation_id", normalized.get("causation_id")
    )
    return normalized


def _comparable(value: Any) -> Any:
    return None if value is None else str(value)


def _required_text(field: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"{field} must be a non-empty string.")
    return value.strip()


def _optional_non_empty(field: str, value: object) -> str | None:
    if value is None:
        return None
    return _required_text(field, value)


def _datetime_value(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat().replace("+00:00", "Z")
    return str(value)


def _string_or_none(value: Any) -> str | None:
    return None if value is None else str(value)


def _invalid(detail: str) -> AgentExecutionError:
    return AgentExecutionError("ae.agent_execution_invalid", detail)


def _unavailable() -> AgentExecutionError:
    return AgentExecutionError(
        "ae.agent_execution_store_unavailable",
        "AE AgentExecution store is unavailable.",
        True,
    )
