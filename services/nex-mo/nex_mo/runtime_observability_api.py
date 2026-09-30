from __future__ import annotations

from fastapi import FastAPI, Header, Request

from nex_mo.provider_auth import authorize_mo_service_request
from nex_mo.runtime_observability_service import RuntimeObservabilityService


def register_runtime_observability_routes(
    app: FastAPI,
    *,
    service: RuntimeObservabilityService,
) -> None:
    @app.get("/api/v1/model-runtime-observability", response_model=None)
    def get_model_runtime_observability(
        request: Request,
        force_refresh: bool = False,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = authorize_mo_service_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        return service.observe(force_refresh=force_refresh)
