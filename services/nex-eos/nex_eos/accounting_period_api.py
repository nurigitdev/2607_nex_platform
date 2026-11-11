from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    admit_service_token_from_request,
    problem_response,
)

from .accounting_periods import EosAccountingPeriodError, EosAccountingPeriodService


def register_accounting_period_routes(app: FastAPI) -> None:
    @app.get(
        "/internal/v2/finance/periods/{period_id}",
        response_model=None,
        operation_id="FINANCE.PERIOD.GET",
    )
    def get_accounting_period(
        period_id: str,
        request: Request,
        company_id: str,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        requester_subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        return _invoke(
            request,
            authorization,
            lambda service: service.get_period(
                tenant_id=tenant_id,
                requester_subject_id=requester_subject_id,
                company_id=company_id,
                period_id=period_id,
            ),
        )

    @app.post(
        "/internal/v2/finance/periods/{period_id}:close",
        response_model=None,
        operation_id="FINANCE.PERIOD.CLOSE",
    )
    def advance_accounting_period_close(
        period_id: str,
        payload: dict[str, Any],
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        requester_subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        return _invoke(
            request,
            authorization,
            lambda service: service.advance_close(
                tenant_id=tenant_id,
                requester_subject_id=requester_subject_id,
                period_id=period_id,
                payload=payload,
            ),
            route_class="WRITE",
        )


def _invoke(
    request: Request,
    authorization: str | None,
    operation,
    *,
    route_class: str | None = None,
):
    options: dict[str, Any] = {
        "expected_audience": "nex-eos",
        "required_scopes": (DEFAULT_SERVICE_SCOPE,),
    }
    if route_class is not None:
        options["route_class"] = route_class
    admitted = admit_service_token_from_request(request, authorization, **options)
    if isinstance(admitted, JSONResponse):
        return admitted
    service: EosAccountingPeriodService | None = getattr(
        request.app.state, "eos_accounting_period_service", None
    )
    if service is None:
        return problem_response(
            request,
            status_code=503,
            error_code="EOS_ACCOUNTING_PERIOD_SERVICE_UNAVAILABLE",
            title="EOS AccountingPeriod service unavailable",
            detail="AccountingPeriod persistence or OA authorization is not configured.",
            retryable=True,
            type_uri=(
                "https://nex-platform.local/problems/"
                "eos-accounting-period-service-unavailable"
            ),
        )
    try:
        return operation(service)
    except EosAccountingPeriodError as exc:
        return problem_response(
            request,
            status_code=exc.status_code,
            error_code=exc.error_code,
            title="EOS AccountingPeriod operation failed",
            detail=exc.detail,
            retryable=exc.retryable,
            type_uri=(
                "https://nex-platform.local/problems/"
                "eos-accounting-period-operation-failed"
            ),
        )
