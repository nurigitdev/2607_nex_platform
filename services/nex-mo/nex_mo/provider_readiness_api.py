from __future__ import annotations

from fastapi import FastAPI, Header, Request

from nex_mo.provider_auth import authorize_mo_service_request
from nex_mo.provider_readiness_service import ProviderReadinessService


def register_provider_readiness_routes(
    app: FastAPI,
    *,
    service: ProviderReadinessService,
) -> None:
    @app.get("/api/v1/provider-route-health", response_model=None)
    def get_provider_route_health(
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = authorize_mo_service_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        return service.check()
