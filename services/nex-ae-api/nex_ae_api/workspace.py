from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
    validate_authorization_header,
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
        self.workspaces[workspace["workspace_id"]] = workspace
        self.append_activity(
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

        created_at = _utc_now()
        activity_id = str(
            uuid5(
                NAMESPACE_URL,
                f"ae-workspace-activity:{workspace_id}:{activity_type}:{request_id}:{created_at}",
            )
        )
        activity = {
            "activity_schema_version": "ae_workspace_activity.v1",
            "activity_id": activity_id,
            "workspace_id": workspace_id,
            "activity_type": activity_type,
            "trace_id": trace_id,
            "request_id": request_id,
            "summary": summary,
            "metadata": metadata or {},
            "created_at": created_at,
        }
        self.activities_by_workspace.setdefault(workspace_id, []).append(activity)
        return activity

    def list_activities(self, workspace_id: str) -> list[dict[str, Any]] | None:
        if workspace_id not in self.workspaces:
            return None
        return list(self.activities_by_workspace.get(workspace_id, []))


DEFAULT_WORKSPACE_STORE = WorkspaceStateStore()


def register_workspace_routes(
    app: FastAPI,
    *,
    store: WorkspaceStateStore | None = None,
) -> None:
    workspace_store = store or DEFAULT_WORKSPACE_STORE

    @app.post("/api/v1/workspaces", response_model=None)
    def create_workspace(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_ae_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        request_id = request_id_from_headers(request)
        trace_id = payload.get("trace_id") or trace_id_from_headers(request)
        try:
            return workspace_store.create_workspace(
                payload=payload,
                request_id=request_id,
                trace_id=trace_id,
            )
        except WorkspaceError as exc:
            return _workspace_problem_response(request, exc)

    @app.get("/api/v1/workspaces/{workspace_id}", response_model=None)
    def get_workspace(
        workspace_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_ae_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        workspace = workspace_store.get_workspace(workspace_id)
        if workspace is None:
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
        auth_problem = _authorize_ae_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        activities = workspace_store.list_activities(workspace_id)
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


def _authorize_ae_request(
    request: Request,
    authorization: str | None,
) -> JSONResponse | None:
    result = validate_authorization_header(
        authorization,
        expected_audience="nex-ae-api",
        required_scopes=[DEFAULT_SERVICE_SCOPE],
    )
    if result.ok:
        return None

    return problem_response(
        request,
        status_code=401,
        error_code=result.error_code or "SERVICE_CLAIM_INVALID",
        title="Authentication failed",
        detail=result.detail or "AE API requires a valid service claim.",
        type_uri="https://nex-platform.local/problems/authentication-failed",
    )


def _workspace_problem_response(
    request: Request,
    exc: WorkspaceError,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Workspace request failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/workspace-request-failed",
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
