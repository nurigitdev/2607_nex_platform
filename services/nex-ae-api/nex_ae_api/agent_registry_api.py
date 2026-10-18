from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse

from nex_runtime import DEFAULT_SERVICE_SCOPE, problem_response
from nex_runtime.auth import validate_authorization_header
from nex_ae_api.agent_identity import (
    AgentIdentityRepositoryError,
    SqlAlchemyAgentIdentityRegistry,
)


def register_agent_registry_routes(
    app: FastAPI, *, registry: SqlAlchemyAgentIdentityRegistry | None
) -> None:
    @app.post("/internal/v1/tenants/{tenant_id}/agents", response_model=None)
    def register_agent(
        tenant_id: str,
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        denied = _authorize(request, authorization, write=True)
        if denied is not None:
            return denied
        if registry is None:
            return _unavailable(request)
        try:
            identity = registry.register_agent(
                tenant_id=tenant_id,
                agent_type=payload.get("agent_type"),
                profile_ref=payload.get("profile_ref"),
                project_id=payload.get("project_id"),
            )
            return JSONResponse(identity, status_code=201)
        except AgentIdentityRepositoryError as exc:
            return _problem(request, exc)

    @app.get("/internal/v1/tenants/{tenant_id}/agents/{agent_id}", response_model=None)
    def get_agent(
        tenant_id: str,
        agent_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        denied = _authorize(request, authorization)
        if denied is not None:
            return denied
        if registry is None:
            return _unavailable(request)
        try:
            identity = registry.get_agent(tenant_id=tenant_id, agent_id=agent_id)
            if identity is None:
                raise AgentIdentityRepositoryError(
                    "ae.agent_identity_not_found", "AgentIdentity was not found."
                )
            return identity
        except AgentIdentityRepositoryError as exc:
            return _problem(request, exc)

    @app.get("/internal/v1/tenants/{tenant_id}/agents", response_model=None)
    def list_agents(
        tenant_id: str,
        request: Request,
        agent_type: str | None = Query(default=None),
        status: str | None = Query(default="ACTIVE"),
        project_id: str | None = Query(default=None),
        limit: int = Query(default=100),
        authorization: str | None = Header(default=None),
    ):
        denied = _authorize(request, authorization)
        if denied is not None:
            return denied
        if registry is None:
            return _unavailable(request)
        try:
            agents = registry.list_eligible_agents(
                tenant_id=tenant_id,
                agent_type=agent_type,
                status=status,
                project_id=project_id,
                limit=limit,
            )
            return {"schema_version": "ae_agent_registry.v1", "agents": agents}
        except AgentIdentityRepositoryError as exc:
            return _problem(request, exc)

    @app.patch(
        "/internal/v1/tenants/{tenant_id}/agents/{agent_id}/status",
        response_model=None,
    )
    def set_agent_status(
        tenant_id: str,
        agent_id: str,
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        denied = _authorize(request, authorization, write=True)
        if denied is not None:
            return denied
        if registry is None:
            return _unavailable(request)
        try:
            return registry.set_agent_status(
                tenant_id=tenant_id,
                agent_id=agent_id,
                status=payload.get("status"),
                expected_version=payload.get("expected_version"),
            )
        except AgentIdentityRepositoryError as exc:
            return _problem(request, exc)

    @app.get(
        "/internal/v1/tenants/{tenant_id}/projects/{project_id}/active-pa",
        response_model=None,
    )
    def get_active_pa(
        tenant_id: str,
        project_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        denied = _authorize(request, authorization)
        if denied is not None:
            return denied
        if registry is None:
            return _unavailable(request)
        try:
            identity = registry.resolve_active_pa(
                tenant_id=tenant_id, project_id=project_id
            )
            if identity is None:
                raise AgentIdentityRepositoryError(
                    "ae.active_pa_not_found", "An active PA was not found."
                )
            return identity
        except AgentIdentityRepositoryError as exc:
            return _problem(request, exc)


def _authorize(
    request: Request, authorization: str | None, *, write: bool = False
) -> JSONResponse | None:
    result = validate_authorization_header(
        authorization,
        expected_audience="nex-ae-api",
        required_scopes=(DEFAULT_SERVICE_SCOPE,),
    )
    if not result.ok or result.claims is None:
        return problem_response(
            request,
            status_code=401,
            error_code=result.error_code or "AE_AGENT_REGISTRY_AUTH_FAILED",
            title="AE Agent Registry authorization failed",
            detail=result.detail or "AE Agent Registry authorization failed.",
            retryable=False,
        )
    allowed = {"nex-ag"} if write else {"nex-ag", "nex-wc"}
    if result.claims.service_id not in allowed:
        return problem_response(
            request,
            status_code=403,
            error_code="AE_AGENT_REGISTRY_CALLER_DENIED",
            title="AE Agent Registry caller denied",
            detail="The calling service is not authorized for this registry operation.",
            retryable=False,
        )
    return None


def _problem(request: Request, exc: AgentIdentityRepositoryError) -> JSONResponse:
    status = 404 if exc.error_code.endswith("not_found") else 409
    if exc.error_code.endswith("input_invalid"):
        status = 400
    if exc.retryable:
        status = 503
    return problem_response(
        request,
        status_code=status,
        error_code=exc.error_code,
        title="AE Agent Registry request failed",
        detail=exc.detail,
        retryable=exc.retryable,
    )


def _unavailable(request: Request) -> JSONResponse:
    return problem_response(
        request,
        status_code=503,
        error_code="ae.agent_registry_persistence_required",
        title="AE Agent Registry unavailable",
        detail="AE PostgreSQL persistence is required for the Agent Registry.",
        retryable=True,
    )
