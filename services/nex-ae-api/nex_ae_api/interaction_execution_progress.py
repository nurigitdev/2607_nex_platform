from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from nex_runtime import problem_response
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_ae_api.route_auth import authorize_ae_facade_route_request
from nex_ae_api.workspace import build_workspace_activity
from nex_ae_api.workspace_persistence import WorkspaceRepositoryError

PROGRESS_SCHEMA_VERSION = "ae_interaction_execution_progress.v1"
PROGRESS_ACTIVITY_TYPE = "agent.execution.progress"
LOGGER = logging.getLogger(__name__)
TERMINAL_EXECUTION_STATES = frozenset(
    {"SUCCEEDED", "FAILED", "BLOCKED", "CANCELLED"}
)
TERMINAL_EVENT_CODES = frozenset(
    {
        "INTERACTION_COMPLETED",
        "INTERACTION_FAILED",
        "INTERACTION_NO_ANSWER",
        "RESULT_PUBLISHED",
    }
)

_ACTIVITY_EVENT_CODES = {
    "chat.interaction.started": "CHAT_REQUEST_ACCEPTED",
    "chat.agent-runtime.admitted": "RUNTIME_EXECUTION_ADMITTED",
    "chat.interaction.completed": "INTERACTION_COMPLETED",
    "chat.interaction.failed": "INTERACTION_FAILED",
    "chat.interaction.no_answer": "INTERACTION_NO_ANSWER",
    "agent.result.published": "RESULT_PUBLISHED",
}
_EVENT_PHASE_ORDER = {
    "CHAT_REQUEST_ACCEPTED": 10,
    "IA_INTENT_STARTED": 20,
    "IA_INTENT_COMPLETED": 21,
    "IA_CONTEXT_STARTED": 30,
    "IA_CONTEXT_COMPLETED": 31,
    "IA_PLAN_STARTED": 40,
    "IA_PLAN_COMPLETED": 41,
    "WC_DELEGATION_CREATED": 50,
    "WC_WORK_CLAIMED": 60,
    "PA_ASSIGNED": 70,
    "CA_ASSIGNED": 70,
    "EA_ASSIGNED": 70,
    "PA_INTENT_STARTED": 80,
    "PA_INTENT_COMPLETED": 81,
    "PA_CONTEXT_STARTED": 90,
    "PA_CONTEXT_COMPLETED": 91,
    "PA_PLAN_STARTED": 100,
    "PA_PLAN_COMPLETED": 101,
    "CA_INTENT_STARTED": 80,
    "CA_INTENT_COMPLETED": 81,
    "CA_CONTEXT_STARTED": 90,
    "CA_CONTEXT_COMPLETED": 91,
    "CA_PLAN_STARTED": 100,
    "CA_PLAN_COMPLETED": 101,
    "EA_INTENT_STARTED": 80,
    "EA_INTENT_COMPLETED": 81,
    "EA_CONTEXT_STARTED": 90,
    "EA_CONTEXT_COMPLETED": 91,
    "EA_PLAN_STARTED": 100,
    "EA_PLAN_COMPLETED": 101,
    "RUNTIME_EXECUTION_STARTED": 110,
    "RUNTIME_EXECUTION_ADMITTED": 111,
    "RESULT_PUBLISHED": 200,
    "INTERACTION_COMPLETED": 210,
    "INTERACTION_NO_ANSWER": 210,
    "INTERACTION_FAILED": 210,
}


@dataclass(frozen=True)
class InteractionExecutionProgressError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class InteractionExecutionProgressSource(Protocol):
    def project_owner_progress(
        self,
        *,
        tenant_id: str,
        owner_user_id: str,
        interaction_id: str,
        after_sequence: int = 0,
    ) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class InteractionProgressRecorder:
    workspace_store: Any
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    def append(
        self,
        *,
        workspace_id: str,
        interaction_id: str,
        event_code: str,
        state: str,
        request_id: str,
        trace_id: str,
        agent_type: str | None = None,
        source_ref: str | None = None,
        terminal: bool = False,
    ) -> dict[str, Any]:
        code = _bounded_text("event_code", event_code, 96).upper()
        source = source_ref or f"AE:CHAT_INTERACTION:{interaction_id}"
        timestamp = _timestamp(self.clock())
        activity_id = str(
            uuid5(
                NAMESPACE_URL,
                "nex:interaction-progress:"
                f"{workspace_id}:{interaction_id}:{code}:{source}",
            )
        )
        activity = build_workspace_activity(
            workspace_id=workspace_id,
            activity_type=PROGRESS_ACTIVITY_TYPE,
            request_id=request_id,
            trace_id=trace_id,
            summary=f"Agent execution progress: {code}.",
            metadata={
                "interaction_id": interaction_id,
                "event_code": code,
                "state": _bounded_text("state", state, 48).upper(),
                "agent_type": (
                    None
                    if agent_type is None
                    else _bounded_text("agent_type", agent_type, 8).upper()
                ),
                "source_ref": _bounded_text("source_ref", source, 256),
                "terminal": bool(terminal),
                "private_payload_included": False,
            },
            created_at=timestamp,
            activity_id=activity_id,
        )
        try:
            saved = self.workspace_store.append_activity_record(activity)
        except WorkspaceRepositoryError as exc:
            raise InteractionExecutionProgressError(
                exc.error_code, exc.detail, exc.retryable
            ) from exc
        if saved is None:
            raise InteractionExecutionProgressError(
                "ae.interaction_progress_workspace_missing",
                "Interaction progress workspace was not found.",
            )
        return saved

    def semantic_sink(
        self,
        *,
        workspace_id: str,
        interaction_id: str,
        agent_type: str,
        request_id: str,
        trace_id: str,
        source_ref: str,
    ) -> Callable[[str, str], None]:
        prefix = _bounded_text("agent_type", agent_type, 8).upper()

        def emit(stage: str, state: str) -> None:
            event_state = _bounded_text("state", state, 48).upper()
            self.append_observation(
                workspace_id=workspace_id,
                interaction_id=interaction_id,
                event_code=f"{prefix}_{stage.upper()}_{event_state}",
                state=event_state,
                request_id=request_id,
                trace_id=trace_id,
                agent_type=prefix,
                source_ref=f"{source_ref}:{stage.upper()}:{event_state}",
            )

        return emit

    def append_observation(self, **values: Any) -> dict[str, Any] | None:
        try:
            return self.append(**values)
        except InteractionExecutionProgressError as exc:
            LOGGER.warning(
                "interaction progress observation was not persisted",
                extra={
                    "error_code": exc.error_code,
                    "retryable": exc.retryable,
                    "interaction_id": values.get("interaction_id"),
                    "event_code": values.get("event_code"),
                },
            )
            return None


class SqlAlchemyInteractionExecutionProgressSource:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def project_owner_progress(
        self,
        *,
        tenant_id: str,
        owner_user_id: str,
        interaction_id: str,
        after_sequence: int = 0,
    ) -> dict[str, Any] | None:
        if after_sequence < 0:
            raise InteractionExecutionProgressError(
                "ae.interaction_progress_cursor_invalid",
                "after_sequence must be zero or greater.",
            )
        canonical_interaction_id = _uuid_text("interaction_id", interaction_id)
        params = {
            "tenant_id": _bounded_text("tenant_id", tenant_id, 128),
            "owner_user_id": _bounded_text("owner_user_id", owner_user_id, 160),
            "interaction_id": canonical_interaction_id,
        }
        try:
            with self._session_factory() as session:
                interaction = _load_owner_interaction(session, params)
                if interaction is None:
                    return None
                activities = _load_workspace_activities(
                    session, str(interaction["workspace_id"])
                )
                execution = _load_owner_execution(session, params)
        except SQLAlchemyError as exc:
            raise InteractionExecutionProgressError(
                "ae.interaction_progress_store_unavailable",
                "Interaction execution progress store is unavailable.",
                True,
            ) from exc
        return project_interaction_execution_progress(
            interaction_id=params["interaction_id"],
            workspace_id=str(interaction["workspace_id"]),
            activities=activities,
            execution=execution,
            after_sequence=after_sequence,
        )


def project_interaction_execution_progress(
    *,
    interaction_id: str,
    workspace_id: str,
    activities: Sequence[Mapping[str, Any]],
    execution: Mapping[str, Any] | None = None,
    after_sequence: int = 0,
) -> dict[str, Any]:
    events = [
        projected
        for activity in activities
        if (projected := _project_activity(activity, interaction_id)) is not None
    ]
    events.sort(
        key=lambda event: (
            event["occurred_at"],
            _EVENT_PHASE_ORDER.get(event["event_code"], 150),
            event["event_id"],
        )
    )
    sequenced = [
        {**event, "sequence": index}
        for index, event in enumerate(events, start=1)
    ]
    execution_state = (
        str(execution.get("state")) if execution is not None else None
    )
    terminal = any(event["terminal"] for event in sequenced) or (
        execution_state in TERMINAL_EXECUTION_STATES
    )
    status = _progress_status(sequenced, execution_state, terminal)
    visible = [event for event in sequenced if event["sequence"] > after_sequence]
    return {
        "schema_version": PROGRESS_SCHEMA_VERSION,
        "interaction_id": interaction_id,
        "workspace_id": workspace_id,
        "status": status,
        "terminal": terminal,
        "next_sequence": len(sequenced),
        "events": visible,
        "metadata": {
            "owner_scoped": True,
            "ordered_projection": True,
            "raw_prompt_included": False,
            "private_payload_included": False,
            "debug_time_available": True,
        },
    }


def register_interaction_execution_progress_routes(
    app: FastAPI,
    *,
    source: InteractionExecutionProgressSource | None,
) -> None:
    app.state.ae_interaction_execution_progress_source = source

    @app.get(
        "/api/v1/chat/interactions/{interaction_id}/execution-progress",
        response_model=None,
    )
    def get_interaction_execution_progress(
        interaction_id: str,
        request: Request,
        after_sequence: int = 0,
        authorization: str | None = Header(default=None),
    ):
        auth = authorize_ae_facade_route_request(request, authorization)
        if isinstance(auth, JSONResponse):
            return auth
        if auth.browser_context is None:
            return problem_response(
                request,
                status_code=403,
                error_code="ae.interaction_progress_browser_required",
                title="Interaction progress access denied",
                detail="Interaction progress requires an authenticated browser owner.",
                retryable=False,
            )
        if source is None:
            return problem_response(
                request,
                status_code=503,
                error_code="ae.interaction_progress_unavailable",
                title="Interaction progress unavailable",
                detail="The durable interaction progress source is unavailable.",
                retryable=True,
            )
        try:
            projection = source.project_owner_progress(
                tenant_id=auth.browser_context.tenant_id,
                owner_user_id=auth.browser_context.user_id,
                interaction_id=interaction_id,
                after_sequence=after_sequence,
            )
        except InteractionExecutionProgressError as exc:
            return problem_response(
                request,
                status_code=(503 if exc.retryable else 400),
                error_code=exc.error_code,
                title="Interaction progress unavailable",
                detail=exc.detail,
                retryable=exc.retryable,
            )
        if projection is None:
            return problem_response(
                request,
                status_code=404,
                error_code="ae.interaction_progress_not_found",
                title="Interaction progress not found",
                detail="The interaction was not found in this owner scope.",
                retryable=False,
            )
        return projection


def _load_owner_interaction(
    session: Session, params: Mapping[str, Any]
) -> Mapping[str, Any] | None:
    return (
        session.execute(
            text(
                "SELECT chat.workspace_id FROM ae_chat_interactions AS chat "
                "JOIN ae_workspaces AS workspace "
                "ON workspace.workspace_id = chat.workspace_id "
                "AND workspace.tenant_id = chat.tenant_id "
                "WHERE chat.chat_interaction_id = :interaction_id "
                "AND chat.tenant_id = :tenant_id "
                "AND chat.user_id = :owner_user_id "
                "AND workspace.owner_user_id = :owner_user_id"
            ),
            params,
        )
        .mappings()
        .first()
    )


def _load_workspace_activities(
    session: Session, workspace_id: str
) -> list[dict[str, Any]]:
    rows = (
        session.execute(
            text(
                "SELECT activity_id, activity_type, summary, metadata, created_at "
                "FROM ae_workspace_activities WHERE workspace_id = :workspace_id"
            ),
            {"workspace_id": workspace_id},
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def _load_owner_execution(
    session: Session, params: Mapping[str, Any]
) -> Mapping[str, Any] | None:
    return (
        session.execute(
            text(
                "SELECT state, phase, updated_at FROM ae_agent_execution "
                "WHERE tenant_id = :tenant_id "
                "AND legacy_interaction_id = :interaction_id "
                "AND principal_id = :owner_user_id"
            ),
            params,
        )
        .mappings()
        .first()
    )


def _project_activity(
    activity: Mapping[str, Any], interaction_id: str
) -> dict[str, Any] | None:
    metadata = _json_mapping(activity.get("metadata"))
    interaction_ref = str(metadata.get("interaction_ref") or "")
    if (
        str(metadata.get("interaction_id") or "") != interaction_id
        and interaction_ref != f"AE:CHAT_INTERACTION:{interaction_id}"
    ):
        return None
    activity_type = str(activity.get("activity_type") or "")
    event_code = str(metadata.get("event_code") or "")
    if not event_code:
        event_code = _ACTIVITY_EVENT_CODES.get(activity_type, "")
    if not event_code:
        return None
    state = str(metadata.get("state") or metadata.get("status") or "RECORDED")
    terminal = bool(metadata.get("terminal")) or event_code in TERMINAL_EVENT_CODES
    return {
        "event_id": str(activity["activity_id"]),
        "sequence": 0,
        "event_code": event_code,
        "state": state,
        "agent_type": metadata.get("agent_type"),
        "source_ref": metadata.get("source_ref") or interaction_ref or None,
        "occurred_at": _timestamp(activity["created_at"]),
        "terminal": terminal,
    }


def _progress_status(
    events: Sequence[Mapping[str, Any]],
    execution_state: str | None,
    terminal: bool,
) -> str:
    if execution_state in TERMINAL_EXECUTION_STATES:
        return execution_state
    if events:
        last = events[-1]
        if last["event_code"] == "INTERACTION_NO_ANSWER":
            return "NO_ANSWER"
        if last["event_code"] == "INTERACTION_FAILED":
            return "FAILED"
        if terminal:
            return "COMPLETED"
    return "IN_PROGRESS"


def _json_mapping(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        import json

        decoded = json.loads(value)
        return dict(decoded) if isinstance(decoded, Mapping) else {}
    return {}


def _timestamp(value: object) -> str:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _bounded_text(field: str, value: object, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise InteractionExecutionProgressError(
            "ae.interaction_progress_field_invalid",
            f"{field} must be a bounded non-empty string.",
        )
    return value.strip()


def _uuid_text(field: str, value: object) -> str:
    text_value = _bounded_text(field, value, 64)
    try:
        return str(UUID(text_value))
    except ValueError as exc:
        raise InteractionExecutionProgressError(
            "ae.interaction_progress_field_invalid",
            f"{field} must be a UUID.",
        ) from exc
