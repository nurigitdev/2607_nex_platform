from __future__ import annotations

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    admit_service_token_from_request,
    problem_response,
)

from .project_pnl_query import EosProjectPnlQueryError, EosProjectPnlQueryService

_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
}
_ALLOWED_QUERY_FIELDS = frozenset({"projection_version"})


def register_project_pnl_routes(app: FastAPI) -> None:
    @app.get(
        "/internal/v2/finance/projects/{project_id}/pnl/{period_id}",
        response_model=None,
        operation_id="FINANCE.PROJECT_PNL.GET",
    )
    def get_project_pnl(
        project_id: str,
        period_id: str,
        request: Request,
        projection_version: int | None = None,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        company_id: str = Header(alias="X-NeX-Company-Id"),
        requester_subject_id: str = Header(alias="X-NeX-Subject-Id"),
        correlation_id: str = Header(alias="X-NeX-Correlation-Id"),
        authorization: str | None = Header(default=None),
    ):
        admitted = admit_service_token_from_request(
            request,
            authorization,
            expected_audience="nex-eos",
            required_scopes=(DEFAULT_SERVICE_SCOPE,),
        )
        if isinstance(admitted, JSONResponse):
            admitted.headers.update(_NO_STORE_HEADERS)
            return admitted
        unknown_query_fields = set(request.query_params) - _ALLOWED_QUERY_FIELDS
        if unknown_query_fields:
            return _problem(
                request,
                EosProjectPnlQueryError(
                    "PROJECT_PNL_QUERY_SHAPE_DENIED",
                    "Project P&L supports only the canonical period query shape",
                    status_code=400,
                ),
            )
        service = _service(request)
        if isinstance(service, JSONResponse):
            return service
        try:
            projection = service.get(
                tenant_id=tenant_id,
                company_id=company_id,
                project_id=project_id,
                period_id=period_id,
                requester_subject_id=requester_subject_id,
                correlation_id=correlation_id,
                projection_version=projection_version,
            )
        except EosProjectPnlQueryError as exc:
            return _problem(request, exc)
        return JSONResponse(projection, headers=_NO_STORE_HEADERS)


def _service(request: Request):
    service: EosProjectPnlQueryService | None = getattr(
        request.app.state, "eos_project_pnl_query_service", None
    )
    if service is not None:
        return service
    return _problem(
        request,
        EosProjectPnlQueryError(
            "PROJECT_PNL_QUERY_UNAVAILABLE",
            "Project P&L query dependencies are not configured",
            status_code=503,
            retryable=True,
        ),
    )


def _problem(request: Request, exc: EosProjectPnlQueryError) -> JSONResponse:
    response = problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="EOS Project P&L query failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/eos-project-pnl-query-failed",
    )
    response.headers.update(_NO_STORE_HEADERS)
    return response
