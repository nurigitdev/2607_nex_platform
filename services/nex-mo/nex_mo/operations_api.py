from __future__ import annotations

from fastapi import FastAPI, Header, Request

from nex_mo.operations_service import MOOperationsService
from nex_mo.provider_auth import authorize_mo_service_request
from nex_runtime import problem_response


def register_operations_routes(
    app: FastAPI,
    *,
    service: MOOperationsService,
) -> None:
    @app.get("/api/v1/operations-snapshot", response_model=None)
    def get_operations_snapshot(
        request: Request,
        force_refresh: bool = False,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = authorize_mo_service_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        try:
            return service.snapshot(force_refresh=force_refresh)
        except Exception:
            return problem_response(
                request,
                status_code=503,
                error_code="MO_OPERATIONS_SNAPSHOT_UNAVAILABLE",
                title="MO operations snapshot unavailable",
                detail="The operations snapshot is temporarily unavailable.",
                type_uri=(
                    "https://nex-platform.local/problems/"
                    "mo-operations-snapshot-unavailable"
                ),
            )
