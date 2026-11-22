from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from nex_runtime import problem_response

from .project_agent_lifecycle import (
    ProjectAgentLifecycleError,
    SqlAlchemyProjectAgentLifecycleService,
)
from .route_auth import authorize_ae_internal_service_request


def register_project_agent_lifecycle_routes(
    app: FastAPI,
    *,
    service: SqlAlchemyProjectAgentLifecycleService | None,
) -> None:
    @app.post("/internal/v1/project-lifecycle-events", response_model=None)
    def ingest_project_lifecycle_event(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        admitted = authorize_ae_internal_service_request(
            request,
            authorization,
            allowed_service_ids=("nex-eos",),
            error_code="AE_PROJECT_LIFECYCLE_CALLER_DENIED",
            title="AE Project lifecycle caller denied",
            detail="Only nex-eos may publish Project lifecycle events.",
        )
        if isinstance(admitted, JSONResponse):
            return admitted
        if service is None:
            return problem_response(
                request,
                status_code=503,
                error_code="AE_PROJECT_AGENT_LIFECYCLE_UNAVAILABLE",
                title="AE Project Agent lifecycle unavailable",
                detail="Project Agent lifecycle persistence or policy is unavailable.",
                retryable=True,
            )
        try:
            receipt, created = service.ingest(payload)
        except ProjectAgentLifecycleError as exc:
            return problem_response(
                request,
                status_code=exc.status_code,
                error_code=exc.error_code,
                title="AE Project Agent lifecycle admission failed",
                detail=exc.detail,
                retryable=exc.retryable,
            )
        return JSONResponse(receipt, status_code=201 if created else 200)
