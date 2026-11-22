from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    admit_service_token_from_request,
    problem_response,
)

from .budgets import EosBudgetError, EosBudgetService
from .project_budget_bindings import (
    EosProjectBudgetBindingError,
    EosProjectBudgetBindingService,
)


def register_budget_routes(app: FastAPI) -> None:
    @app.post(
        "/internal/v2/finance/budgets",
        response_model=None,
        operation_id="FINANCE.BUDGET.COMMIT",
    )
    def commit_budget(
        payload: dict[str, Any],
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        company_id: str = Header(alias="X-NeX-Company-Id"),
        authorization: str | None = Header(default=None),
    ):
        admitted = _admit(request, authorization, write=True)
        if isinstance(admitted, JSONResponse):
            return admitted
        service = _budget_service(request)
        if isinstance(service, JSONResponse):
            return service
        try:
            result = service.commit(
                tenant_id=tenant_id, company_id=company_id, payload=payload
            )
        except EosBudgetError as exc:
            return _problem(request, exc)
        return JSONResponse(
            result,
            status_code=(
                201 if result["idempotency_disposition"] == "CREATED" else 200
            ),
        )

    @app.get(
        "/internal/v2/finance/budgets/{budget_id}/versions/{budget_version}",
        response_model=None,
        operation_id="FINANCE.BUDGET.GET",
    )
    def get_budget(
        budget_id: str,
        budget_version: int,
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        company_id: str = Header(alias="X-NeX-Company-Id"),
        authorization: str | None = Header(default=None),
    ):
        admitted = _admit(request, authorization)
        if isinstance(admitted, JSONResponse):
            return admitted
        service = _budget_service(request)
        if isinstance(service, JSONResponse):
            return service
        try:
            return service.get(
                tenant_id=tenant_id,
                company_id=company_id,
                budget_id=budget_id,
                budget_version=budget_version,
            )
        except EosBudgetError as exc:
            return _problem(request, exc)

    @app.post(
        "/internal/v2/finance/project-budget-bindings",
        response_model=None,
        operation_id="PROJECT.BUDGET_BINDING.COMMIT",
    )
    def commit_project_budget_binding(
        payload: dict[str, Any],
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        company_id: str = Header(alias="X-NeX-Company-Id"),
        authorization: str | None = Header(default=None),
    ):
        admitted = _admit(request, authorization, write=True)
        if isinstance(admitted, JSONResponse):
            return admitted
        service = _binding_service(request)
        if isinstance(service, JSONResponse):
            return service
        try:
            result = service.commit(
                tenant_id=tenant_id, company_id=company_id, payload=payload
            )
        except EosProjectBudgetBindingError as exc:
            return _problem(request, exc)
        return JSONResponse(
            result,
            status_code=(
                201 if result["idempotency_disposition"] == "CREATED" else 200
            ),
        )

    @app.get(
        "/internal/v2/projects/{project_id}/budget-bindings",
        response_model=None,
        operation_id="PROJECT.BUDGET_BINDING.LIST",
    )
    def list_project_budget_bindings(
        project_id: str,
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        company_id: str = Header(alias="X-NeX-Company-Id"),
        authorization: str | None = Header(default=None),
    ):
        admitted = _admit(request, authorization)
        if isinstance(admitted, JSONResponse):
            return admitted
        service = _binding_service(request)
        if isinstance(service, JSONResponse):
            return service
        try:
            return service.list_for_project(
                tenant_id=tenant_id,
                company_id=company_id,
                project_id=project_id,
            )
        except EosProjectBudgetBindingError as exc:
            return _problem(request, exc)


def _admit(request: Request, authorization: str | None, *, write: bool = False):
    kwargs = {
        "expected_audience": "nex-eos",
        "required_scopes": (DEFAULT_SERVICE_SCOPE,),
    }
    if write:
        kwargs["route_class"] = "WRITE"
    return admit_service_token_from_request(request, authorization, **kwargs)


def _budget_service(request: Request):
    service: EosBudgetService | None = getattr(
        request.app.state, "eos_budget_service", None
    )
    if service is not None:
        return service
    return _problem(
        request,
        EosBudgetError(
            "EOS_BUDGET_UNAVAILABLE",
            "Budget dependencies are not configured",
            status_code=503,
            retryable=True,
        ),
    )


def _binding_service(request: Request):
    service: EosProjectBudgetBindingService | None = getattr(
        request.app.state, "eos_project_budget_binding_service", None
    )
    if service is not None:
        return service
    return _problem(
        request,
        EosProjectBudgetBindingError(
            "EOS_PROJECT_BUDGET_BINDING_UNAVAILABLE",
            "Project Budget binding dependencies are not configured",
            status_code=503,
            retryable=True,
        ),
    )


def _problem(request: Request, exc):
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="EOS governed Budget operation failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/eos-budget-operation-failed",
    )
