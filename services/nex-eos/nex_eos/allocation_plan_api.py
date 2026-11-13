from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    admit_service_token_from_request,
    problem_response,
)

from .allocation_plans import EosAllocationPlanError, EosAllocationPlanService


def register_allocation_plan_routes(app: FastAPI) -> None:
    @app.post(
        "/internal/v2/finance/cost-allocation-plans/releases",
        response_model=None,
        operation_id="FINANCE.COST_ALLOCATION_PLAN.RELEASE",
    )
    def release_allocation_plan(
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
            result = service.release(
                tenant_id=tenant_id,
                company_id=company_id,
                payload=payload,
            )
        except EosAllocationPlanError as exc:
            return _problem(request, exc)
        return JSONResponse(
            result,
            status_code=(
                201 if result["idempotency_disposition"] == "CREATED" else 200
            ),
        )

    @app.get(
        "/internal/v2/finance/cost-allocation-plans/{plan_id}/revisions/{plan_revision}",
        response_model=None,
        operation_id="FINANCE.COST_ALLOCATION_PLAN.GET",
    )
    def get_allocation_plan(
        plan_id: str,
        plan_revision: int,
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
                plan_id=plan_id,
                plan_revision=plan_revision,
            )
        except EosAllocationPlanError as exc:
            return _problem(request, exc)


def _service(request: Request):
    service: EosAllocationPlanService | None = getattr(
        request.app.state, "eos_allocation_plan_service", None
    )
    if service is not None:
        return service
    return _problem(
        request,
        EosAllocationPlanError(
            "EOS_COST_ALLOCATION_PLAN_UNAVAILABLE",
            "Allocation plan dependencies are not configured",
            status_code=503,
            retryable=True,
        ),
    )


def _problem(request: Request, exc: EosAllocationPlanError):
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="EOS allocation plan release failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/eos-allocation-plan-failed",
    )
