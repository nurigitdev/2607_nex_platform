from __future__ import annotations

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_runtime import problem_response
from nex_ae_api.route_auth import authorize_ae_facade_route_request
from nex_ae_api.workspace_result_publication import (
    SqlAlchemyInteractionAgentResultSource,
    WorkspaceResultPublicationError,
)


def register_interaction_agent_result_routes(
    app: FastAPI,
    *,
    source: SqlAlchemyInteractionAgentResultSource | None,
) -> None:
    app.state.ae_interaction_agent_result_source = source

    @app.get(
        "/api/v1/chat/interactions/{interaction_id}/agent-result",
        response_model=None,
    )
    def get_interaction_agent_result(
        interaction_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth = authorize_ae_facade_route_request(request, authorization)
        if isinstance(auth, JSONResponse):
            return auth
        if auth.browser_context is None:
            return problem_response(
                request,
                status_code=403,
                error_code="ae.interaction_agent_result_browser_required",
                title="Interaction result access denied",
                detail="Interaction results require an authenticated browser owner.",
                retryable=False,
            )
        if source is None:
            return problem_response(
                request,
                status_code=503,
                error_code="ae.interaction_agent_result_unavailable",
                title="Interaction result unavailable",
                detail="The durable interaction result source is unavailable.",
                retryable=True,
            )
        try:
            projection = source.get_owner_result(
                tenant_id=auth.browser_context.tenant_id,
                owner_user_id=auth.browser_context.user_id,
                interaction_id=interaction_id,
            )
        except WorkspaceResultPublicationError as exc:
            return problem_response(
                request,
                status_code=503 if exc.retryable else 400,
                error_code=exc.error_code,
                title="Interaction result unavailable",
                detail=exc.detail,
                retryable=exc.retryable,
            )
        if projection is None:
            return problem_response(
                request,
                status_code=404,
                error_code="ae.interaction_agent_result_not_found",
                title="Interaction result not found",
                detail="The interaction result was not found in this owner scope.",
                retryable=False,
            )
        return projection
