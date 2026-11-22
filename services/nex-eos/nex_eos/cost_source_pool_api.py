from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    admit_service_token_from_request,
    problem_response,
)

from .cost_source_pools import EosCostSourcePoolError, EosCostSourcePoolService


def register_cost_source_pool_routes(app: FastAPI) -> None:
    @app.post(
        "/internal/v2/finance/journals/{journal_id}/lines/{journal_line_no}/cost-source-pool",
        response_model=None,
        operation_id="FINANCE.COST_SOURCE_POOL.ADMIT",
    )
    def admit_cost_source_pool(
        journal_id: str,
        journal_line_no: int,
        payload: dict[str, Any],
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        company_id: str = Header(alias="X-NeX-Company-Id"),
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
            return admitted
        service = _service(request)
        if isinstance(service, JSONResponse):
            return service
        try:
            result = service.admit(
                tenant_id=tenant_id,
                company_id=company_id,
                journal_id=journal_id,
                journal_line_no=journal_line_no,
                payload=payload,
            )
        except EosCostSourcePoolError as exc:
            return _problem(request, exc)
        return JSONResponse(
            result,
            status_code=(
                201 if result["idempotency_disposition"] == "CREATED" else 200
            ),
        )

    @app.get(
        "/internal/v2/finance/cost-source-pools/{pool_id}",
        response_model=None,
        operation_id="FINANCE.COST_SOURCE_POOL.GET",
    )
    def get_cost_source_pool(
        pool_id: str,
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        company_id: str = Header(alias="X-NeX-Company-Id"),
        authorization: str | None = Header(default=None),
    ):
        admitted = admit_service_token_from_request(
            request,
            authorization,
            expected_audience="nex-eos",
            required_scopes=(DEFAULT_SERVICE_SCOPE,),
        )
        if isinstance(admitted, JSONResponse):
            return admitted
        service = _service(request)
        if isinstance(service, JSONResponse):
            return service
        try:
            return service.get(
                tenant_id=tenant_id,
                company_id=company_id,
                pool_id=pool_id,
            )
        except EosCostSourcePoolError as exc:
            return _problem(request, exc)


def _service(request: Request):
    service: EosCostSourcePoolService | None = getattr(
        request.app.state, "eos_cost_source_pool_service", None
    )
    if service is not None:
        return service
    return _problem(
        request,
        EosCostSourcePoolError(
            "EOS_COST_SOURCE_POOL_UNAVAILABLE",
            "Cost SourcePool dependencies are not configured",
            status_code=503,
            retryable=True,
        ),
    )


def _problem(request: Request, exc: EosCostSourcePoolError):
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="EOS Cost SourcePool admission failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/eos-cost-source-pool-failed",
    )
