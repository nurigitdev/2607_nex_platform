from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    admit_service_token_from_request,
    problem_response,
)

from .allocation_reconciliation import (
    EosAllocationReconciliationError,
    EosAllocationReconciliationService,
)
from .cost_allocations import EosCostAllocationError, EosCostAllocationService


def register_cost_allocation_routes(app: FastAPI) -> None:
    @app.post(
        "/internal/v2/finance/cost-allocation-batches",
        response_model=None,
        operation_id="FINANCE.COST_ALLOCATION.RUN",
    )
    def run_cost_allocation(
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
        service = _run_service(request)
        if isinstance(service, JSONResponse):
            return service
        try:
            result = service.run(
                tenant_id=tenant_id, company_id=company_id, payload=payload
            )
        except EosCostAllocationError as exc:
            return _problem(request, exc)
        return JSONResponse(
            result,
            status_code=(
                201 if result["idempotency_disposition"] == "CREATED" else 200
            ),
        )

    @app.get(
        "/internal/v2/finance/cost-allocation-batches/{batch_id}/verification",
        response_model=None,
        operation_id="FINANCE.COST_ALLOCATION.VERIFY",
    )
    def verify_cost_allocation(
        batch_id: str,
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
        service = _verification_service(request)
        if isinstance(service, JSONResponse):
            return service
        try:
            return service.verify_batch(
                tenant_id=tenant_id,
                company_id=company_id,
                batch_id=batch_id,
            )
        except EosAllocationReconciliationError as exc:
            return _problem(request, exc)


def _run_service(request: Request):
    service: EosCostAllocationService | None = getattr(
        request.app.state, "eos_cost_allocation_service", None
    )
    if service is not None:
        return service
    return _problem(
        request,
        EosCostAllocationError(
            "EOS_COST_ALLOCATION_UNAVAILABLE",
            "Cost Allocation dependencies are not configured",
            status_code=503,
            retryable=True,
        ),
    )


def _verification_service(request: Request):
    service: EosAllocationReconciliationService | None = getattr(
        request.app.state, "eos_allocation_reconciliation_service", None
    )
    if service is not None:
        return service
    return _problem(
        request,
        EosAllocationReconciliationError(
            "EOS_COST_ALLOCATION_RECONCILIATION_UNAVAILABLE",
            "Cost Allocation reconciliation dependencies are not configured",
            status_code=503,
            retryable=True,
        ),
    )


def _problem(request: Request, exc):
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="EOS Cost Allocation operation failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/eos-cost-allocation-failed",
    )
