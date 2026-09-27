from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_runtime import problem_response, request_id_from_headers, trace_id_from_headers
from nex_ae_api.route_auth import (
    AeFacadeRouteAuthContext,
    authorize_ae_facade_route_request,
)
from nex_ae_api.workspace_chat_auth import (
    WorkspaceChatOwnerError,
    browser_owner_scope,
    owner_scoped_payload,
    record_matches_owner,
)
from nex_ae_api.workspace_persistence import (
    SqlAlchemyWorkspaceRepository,
    WorkspaceRepositoryError,
)


DEFAULT_TENANT_ID = "local-tenant"
DEFAULT_USER_ID = "local-user"


@dataclass(frozen=True)
class WorkspaceError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False


@dataclass
class WorkspaceStateStore:
    workspaces: dict[str, dict[str, Any]] = field(default_factory=dict)
    activities_by_workspace: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def create_workspace(
        self,
        *,
        payload: dict[str, Any],
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        workspace = build_workspace_state(
            payload,
            request_id=request_id,
            trace_id=trace_id,
        )
        activity = build_workspace_activity(
            workspace_id=workspace["workspace_id"],
            activity_type="workspace.created",
            request_id=request_id,
            trace_id=trace_id,
            summary="Workspace created.",
            metadata={
                "tenant_id": workspace["tenant_id"],
                "owner_user_id": workspace["owner_user_id"],
            },
        )
        return self.save_workspace(workspace, activity)

    def save_workspace(
        self,
        workspace: dict[str, Any],
        initial_activity: dict[str, Any],
    ) -> dict[str, Any]:
        existing = self.workspaces.get(workspace["workspace_id"])
        if existing is not None:
            if (
                existing["tenant_id"],
                existing["owner_user_id"],
            ) != (workspace["tenant_id"], workspace["owner_user_id"]):
                raise WorkspaceError(
                    status_code=409,
                    error_code="ae.workspace_owner_conflict",
                    detail="Workspace identifier is already owned by another subject.",
                )
            return existing
        self.workspaces[workspace["workspace_id"]] = workspace
        self.append_activity_record(initial_activity)
        return workspace

    def get_workspace(self, workspace_id: str) -> dict[str, Any] | None:
        return self.workspaces.get(workspace_id)

    def append_activity(
        self,
        *,
        workspace_id: str,
        activity_type: str,
        request_id: str,
        trace_id: str,
        summary: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if workspace_id not in self.workspaces:
            raise WorkspaceError(
                status_code=404,
                error_code="ae.workspace_not_found",
                detail=f"Workspace was not found: {workspace_id}",
            )

        activity = build_workspace_activity(
            workspace_id=workspace_id,
            activity_type=activity_type,
            request_id=request_id,
            trace_id=trace_id,
            summary=summary,
            metadata=metadata,
        )
        return self.append_activity_record(activity)

    def append_activity_record(self, activity: dict[str, Any]) -> dict[str, Any]:
        workspace_id = activity["workspace_id"]
        if workspace_id not in self.workspaces:
            raise WorkspaceError(
                status_code=404,
                error_code="ae.workspace_not_found",
                detail=f"Workspace was not found: {workspace_id}",
            )
        existing = self.activities_by_workspace.setdefault(workspace_id, [])
        if any(item["activity_id"] == activity["activity_id"] for item in existing):
            return activity
        existing.append(activity)
        workspace = self.workspaces[workspace_id]
        workspace["activity_summary"] = {
            "last_activity_type": activity["activity_type"],
            "activity_count": len(existing),
        }
        workspace["updated_at"] = activity["created_at"]
        return activity

    def list_activities(self, workspace_id: str) -> list[dict[str, Any]] | None:
        if workspace_id not in self.workspaces:
            return None
        return list(self.activities_by_workspace.get(workspace_id, []))


DEFAULT_WORKSPACE_STORE = WorkspaceStateStore()


def build_default_workspace_store(app: Any) -> Any:
    persistence = getattr(app.state, "nex_persistence", None)
    session_factory = getattr(persistence, "api_session_factory", None)
    if session_factory is not None:
        return SqlAlchemyWorkspaceRepository(session_factory)
    return DEFAULT_WORKSPACE_STORE


def register_workspace_routes(
    app: FastAPI,
    *,
    store: Any | None = None,
) -> None:
    workspace_store = store or build_default_workspace_store(app)
    app.state.ae_workspace_store = workspace_store

    @app.post("/api/v1/workspaces", response_model=None)
    def create_workspace(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_context = authorize_ae_facade_route_request(request, authorization)
        if isinstance(auth_context, JSONResponse):
            return auth_context

        request_id = request_id_from_headers(request)
        trace_id = payload.get("trace_id") or trace_id_from_headers(request)
        try:
            normalized_payload = _owner_scoped_workspace_payload(payload, auth_context)
            workspace = build_workspace_state(
                normalized_payload,
                request_id=request_id,
                trace_id=trace_id,
            )
            initial_activity = build_workspace_activity(
                workspace_id=workspace["workspace_id"],
                activity_type="workspace.created",
                request_id=request_id,
                trace_id=trace_id,
                summary="Workspace created.",
                metadata={
                    "tenant_id": workspace["tenant_id"],
                    "owner_user_id": workspace["owner_user_id"],
                },
            )
            return workspace_store.save_workspace(workspace, initial_activity)
        except (WorkspaceError, WorkspaceChatOwnerError, WorkspaceRepositoryError) as exc:
            return _workspace_problem_response(request, exc)

    @app.get("/api/v1/workspaces/{workspace_id}", response_model=None)
    def get_workspace(
        workspace_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_context = authorize_ae_facade_route_request(request, authorization)
        if isinstance(auth_context, JSONResponse):
            return auth_context

        try:
            workspace = workspace_store.get_workspace(workspace_id)
        except WorkspaceRepositoryError as exc:
            return _workspace_problem_response(request, exc)
        if not _workspace_visible(workspace, auth_context):
            return _workspace_problem_response(
                request,
                WorkspaceError(
                    status_code=404,
                    error_code="ae.workspace_not_found",
                    detail=f"Workspace was not found: {workspace_id}",
                ),
            )
        return workspace

    @app.get("/api/v1/workspaces/{workspace_id}/activity", response_model=None)
    def list_workspace_activity(
        workspace_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_context = authorize_ae_facade_route_request(request, authorization)
        if isinstance(auth_context, JSONResponse):
            return auth_context

        try:
            workspace = workspace_store.get_workspace(workspace_id)
            activities = (
                workspace_store.list_activities(workspace_id)
                if _workspace_visible(workspace, auth_context)
                else None
            )
        except WorkspaceRepositoryError as exc:
            return _workspace_problem_response(request, exc)
        if activities is None:
            return _workspace_problem_response(
                request,
                WorkspaceError(
                    status_code=404,
                    error_code="ae.workspace_not_found",
                    detail=f"Workspace was not found: {workspace_id}",
                ),
            )
        return {
            "workspace_id": workspace_id,
            "activities": activities,
        }


def build_workspace_state(
    payload: dict[str, Any],
    *,
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    tenant_id, owner_user_id = owner_scope_from_payload(payload)
    title = workspace_title_from_payload(payload)
    runtime_defaults = runtime_defaults_from_payload(payload)
    workspace_id = payload.get("workspace_id") or str(
        uuid5(NAMESPACE_URL, f"ae-workspace:{tenant_id}:{owner_user_id}:{title}")
    )
    chat_document_id = payload.get("chat_document_id") or str(
        uuid5(NAMESPACE_URL, f"ae-chat-document:{workspace_id}")
    )
    now = _utc_now()
    return {
        "workspace_schema_version": "ae_workspace_state.v1",
        "workspace_id": workspace_id,
        "tenant_id": tenant_id,
        "owner_user_id": owner_user_id,
        "title": title,
        "locale": runtime_defaults["locale"],
        "chat_document_id": chat_document_id,
        "runtime_defaults": runtime_defaults,
        "activity_summary": {
            "last_activity_type": "workspace.created",
            "activity_count": 1,
        },
        "trace_id": trace_id,
        "request_id": request_id,
        "created_at": now,
        "updated_at": now,
    }


def build_workspace_activity(
    *,
    workspace_id: str,
    activity_type: str,
    request_id: str,
    trace_id: str,
    summary: str,
    metadata: dict[str, Any] | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    timestamp = created_at or _utc_now()
    activity_id = str(
        uuid5(
            NAMESPACE_URL,
            f"ae-workspace-activity:{workspace_id}:{activity_type}:{request_id}:{timestamp}",
        )
    )
    return {
        "activity_schema_version": "ae_workspace_activity.v1",
        "activity_id": activity_id,
        "workspace_id": workspace_id,
        "activity_type": activity_type,
        "trace_id": trace_id,
        "request_id": request_id,
        "summary": summary,
        "metadata": metadata or {},
        "created_at": timestamp,
    }


def owner_scope_from_payload(payload: dict[str, Any]) -> tuple[str, str]:
    tenant_id = payload.get("tenant_id", DEFAULT_TENANT_ID)
    owner_user_id = payload.get("owner_user_id", payload.get("user_id", DEFAULT_USER_ID))
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise WorkspaceError(
            status_code=400,
            error_code="ae.workspace_owner_invalid",
            detail="tenant_id must be a non-empty string.",
        )
    if not isinstance(owner_user_id, str) or not owner_user_id.strip():
        raise WorkspaceError(
            status_code=400,
            error_code="ae.workspace_owner_invalid",
            detail="owner_user_id must be a non-empty string.",
        )
    return tenant_id.strip(), owner_user_id.strip()


def workspace_title_from_payload(payload: dict[str, Any]) -> str:
    title = payload.get("title", "새 작업공간")
    if not isinstance(title, str) or not title.strip():
        raise WorkspaceError(
            status_code=400,
            error_code="ae.workspace_title_invalid",
            detail="title must be a non-empty string.",
        )
    return title.strip()[:120]


def runtime_defaults_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    runtime = payload.get("runtime_defaults", {})
    if runtime is None:
        runtime = {}
    if not isinstance(runtime, dict):
        raise WorkspaceError(
            status_code=400,
            error_code="ae.workspace_runtime_invalid",
            detail="runtime_defaults must be an object when supplied.",
        )

    locale = runtime.get("locale", payload.get("locale", "ko-KR"))
    if not isinstance(locale, str) or not locale.strip():
        raise WorkspaceError(
            status_code=400,
            error_code="ae.workspace_runtime_invalid",
            detail="locale must be a non-empty string.",
        )

    return {
        "locale": locale.strip(),
        "execution_mode": runtime.get("execution_mode", "GROUNDED_ANSWER"),
        "template_id": runtime.get("template_id", "none"),
        "prompt_binding_id": runtime.get(
            "prompt_binding_id",
            "ae.grounded_chat.default",
        ),
        "output_contract_id": runtime.get("output_contract_id", "text_answer_v1"),
        "retrieval_profile": runtime.get(
            "retrieval_profile",
            {"search_strategy": "hybrid"},
        ),
        "generation_alias": runtime.get("generation_alias", "general-llm-default"),
    }


def _owner_scoped_workspace_payload(
    payload: dict[str, Any],
    auth_context: AeFacadeRouteAuthContext,
) -> dict[str, Any]:
    if auth_context.browser_context is not None:
        return owner_scoped_payload(payload, auth_context)[0]
    explicit_tenant = isinstance(payload.get("tenant_id"), str) and bool(
        payload["tenant_id"].strip()
    )
    explicit_owner = any(
        isinstance(payload.get(key), str) and bool(payload[key].strip())
        for key in ("owner_user_id", "user_id")
    )
    if isinstance(payload.get("ownership_ref"), dict) or (
        explicit_tenant and explicit_owner
    ):
        return owner_scoped_payload(payload, auth_context)[0]
    return dict(payload)


def _workspace_visible(
    workspace: dict[str, Any] | None,
    auth_context: AeFacadeRouteAuthContext,
) -> bool:
    if workspace is None:
        return False
    scope = browser_owner_scope(auth_context)
    return scope is None or record_matches_owner(workspace, scope)


def _workspace_problem_response(
    request: Request,
    exc: WorkspaceError | WorkspaceChatOwnerError | WorkspaceRepositoryError,
) -> JSONResponse:
    status_code = getattr(exc, "status_code", None)
    if status_code is None:
        status_code = 503 if exc.retryable else 409
    return problem_response(
        request,
        status_code=status_code,
        error_code=exc.error_code,
        title="Workspace request failed",
        detail=exc.detail,
        retryable=getattr(exc, "retryable", False),
        type_uri="https://nex-platform.local/problems/workspace-request-failed",
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
