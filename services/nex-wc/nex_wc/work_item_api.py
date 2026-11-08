from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_runtime import DEFAULT_SERVICE_SCOPE, problem_response
from nex_runtime.auth import validate_authorization_header

from nex_wc.work_items import WorkItemError, WorkItemService


def register_work_item_routes(app: FastAPI, *, service: WorkItemService) -> None:
    @app.post("/api/v1/work-items", response_model=None)
    def create_work_item(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        denied = _authorize(request, authorization)
        if denied is not None:
            return denied
        try:
            result = service.create(payload)
        except WorkItemError as exc:
            return _problem(request, exc)
        return JSONResponse(result, status_code=201 if result["created"] else 200)

    @app.get("/api/v1/work-items/{work_item_id}", response_model=None)
    def get_work_item(
        work_item_id: str,
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        authorization: str | None = Header(default=None),
    ):
        denied = _authorize(request, authorization)
        if denied is not None:
            return denied
        try:
            return service.get(tenant_id=tenant_id, work_item_id=work_item_id)
        except WorkItemError as exc:
            return _problem(request, exc)

    @app.get("/api/v1/work-items/{work_item_id}/status", response_model=None)
    def get_work_item_status(
        work_item_id: str,
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        authorization: str | None = Header(default=None),
    ):
        denied = _authorize(request, authorization)
        if denied is not None:
            return denied
        try:
            return service.status(tenant_id=tenant_id, work_item_id=work_item_id)
        except WorkItemError as exc:
            return _problem(request, exc)


def _authorize(request: Request, authorization: str | None) -> JSONResponse | None:
    result = validate_authorization_header(
        authorization,
        expected_audience="nex-wc",
        required_scopes=(DEFAULT_SERVICE_SCOPE,),
    )
    if result.ok:
        return None
    status = 403 if result.error_code == "SERVICE_SCOPE_MISSING" else 401
    return problem_response(
        request,
        status_code=status,
        error_code=result.error_code or "WC_AUTHORIZATION_FAILED",
        title="WC service authorization failed",
        detail=result.detail or "WC service authorization failed.",
        retryable=False,
        type_uri="https://nex-platform.local/problems/wc-service-authorization-failed",
    )


def _problem(request: Request, exc: WorkItemError) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="WC WorkItem request failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/wc-work-item-request-failed",
    )
