from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_runtime import DEFAULT_SERVICE_SCOPE, problem_response
from nex_runtime.auth import validate_authorization_header
from nex_wc.coordination import CoordinationError, WorkCoordinationService


def register_coordination_routes(
    app: FastAPI, *, service: WorkCoordinationService
) -> None:
    @app.post("/api/v1/work-items/{work_item_id}/route", response_model=None)
    def route_work_item(
        work_item_id: str,
        payload: dict[str, Any],
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        authorization: str | None = Header(default=None),
    ):
        denied = _authorize(request, authorization)
        if denied is not None:
            return denied
        try:
            return service.route(
                tenant_id=tenant_id,
                work_item_id=work_item_id,
                expected_version=payload.get("expected_version"),
            )
        except CoordinationError as exc:
            return _problem(request, exc)

    @app.post("/api/v1/work-items/{work_item_id}/claim", response_model=None)
    def claim_work_item(
        work_item_id: str,
        payload: dict[str, Any],
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        authorization: str | None = Header(default=None),
    ):
        denied = _authorize(request, authorization)
        if denied is not None:
            return denied
        try:
            return service.claim(
                tenant_id=tenant_id,
                work_item_id=work_item_id,
                expected_version=payload.get("expected_version"),
            )
        except CoordinationError as exc:
            return _problem(request, exc)


def _authorize(request: Request, authorization: str | None) -> JSONResponse | None:
    result = validate_authorization_header(
        authorization,
        expected_audience="nex-wc",
        required_scopes=(DEFAULT_SERVICE_SCOPE,),
    )
    if result.ok:
        return None
    return problem_response(
        request,
        status_code=401,
        error_code=result.error_code or "WC_COORDINATION_AUTH_FAILED",
        title="WC coordination authorization failed",
        detail=result.detail or "WC coordination authorization failed.",
        retryable=False,
    )


def _problem(request: Request, exc: CoordinationError) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="WC coordination request failed",
        detail=exc.detail,
        retryable=exc.retryable,
    )
