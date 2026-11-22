from __future__ import annotations

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    admit_service_token_from_request,
    problem_response,
)

from .project_pnl_refresh import (
    PROJECT_PNL_REFRESH_OPERATION,
    EosProjectPnlRefreshError,
    EosProjectPnlRefreshService,
)

_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
}


def register_project_pnl_refresh_routes(app: FastAPI) -> None:
    @app.post(
        "/internal/v2/finance/cost-allocation-batches/{batch_id}:refresh-project-pnl",
        response_model=None,
        operation_id=PROJECT_PNL_REFRESH_OPERATION,
    )
    def refresh_project_pnl_from_allocation(
        batch_id: str,
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        company_id: str = Header(alias="X-NeX-Company-Id"),
        correlation_id: str = Header(alias="X-NeX-Correlation-Id"),
        authorization: str | None = Header(default=None),
    ):
        admitted = admit_service_token_from_request(
            request,
            authorization,
            expected_audience="nex-eos",
            required_scopes=(DEFAULT_SERVICE_SCOPE,),
            route_class="WRITE",
        )
        if isinstance(admitted, JSONResponse):
            admitted.headers.update(_NO_STORE_HEADERS)
            return admitted
        if request.query_params or _has_request_body(request):
            return _problem(
                request,
                EosProjectPnlRefreshError(
                    "EOS_PROJECT_PNL_REFRESH_SHAPE_DENIED",
                    "Project P&L refresh accepts only the Batch path selector",
                    status_code=400,
                ),
            )
        service = _service(request)
        if isinstance(service, JSONResponse):
            return service
        _ = correlation_id
        try:
            result = service.refresh(
                tenant_id=tenant_id,
                company_id=company_id,
                batch_id=batch_id,
            )
        except EosProjectPnlRefreshError as exc:
            return _problem(request, exc)
        return JSONResponse(
            result,
            status_code=201 if result["disposition"] == "CREATED" else 200,
            headers=_NO_STORE_HEADERS,
        )


def _has_request_body(request: Request) -> bool:
    transfer_encoding = request.headers.get("transfer-encoding")
    content_length = request.headers.get("content-length")
    if transfer_encoding is not None:
        return True
    if content_length is None:
        return False
    try:
        return int(content_length) > 0
    except ValueError:
        return True


def _service(request: Request):
    service: EosProjectPnlRefreshService | None = getattr(
        request.app.state, "eos_project_pnl_refresh_service", None
    )
    if service is not None:
        return service
    return _problem(
        request,
        EosProjectPnlRefreshError(
            "EOS_PROJECT_PNL_REFRESH_UNAVAILABLE",
            "Project P&L refresh dependencies are not configured",
            status_code=503,
            retryable=True,
        ),
    )


def _problem(request: Request, exc: EosProjectPnlRefreshError) -> JSONResponse:
    response = problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="EOS Project P&L refresh failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/eos-project-pnl-refresh-failed",
    )
    response.headers.update(_NO_STORE_HEADERS)
    return response
