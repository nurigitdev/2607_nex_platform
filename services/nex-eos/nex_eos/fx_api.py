from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    admit_service_token_from_request,
    problem_response,
)

from .fx_rates import EosFxRateError, EosFxRateService


def register_fx_rate_routes(app: FastAPI) -> None:
    @app.post(
        "/internal/v2/finance/fx-rate-policies/approved",
        response_model=None,
        operation_id="FINANCE.FX_POLICY.CREATE_APPROVED",
    )
    def create_approved_fx_policy(
        payload: dict[str, Any],
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        requester_subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        result = _invoke(
            request,
            authorization,
            lambda service: service.create_approved_policy(
                tenant_id=tenant_id,
                requester_subject_id=requester_subject_id,
                payload=payload,
            ),
            route_class="WRITE",
        )
        return result if isinstance(result, JSONResponse) else JSONResponse(result, 201)

    @app.post(
        "/internal/v2/finance/fx-rate-batches",
        response_model=None,
        operation_id="FINANCE.FX_RATE.IMPORT",
    )
    def import_fx_rates(
        payload: dict[str, Any],
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        requester_subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        result = _invoke(
            request,
            authorization,
            lambda service: service.import_rates(
                tenant_id=tenant_id,
                requester_subject_id=requester_subject_id,
                payload=payload,
            ),
            route_class="WRITE",
        )
        return result if isinstance(result, JSONResponse) else JSONResponse(result, 201)

    @app.get(
        "/internal/v2/finance/fx-rates:resolve",
        response_model=None,
        operation_id="FINANCE.FX_RATE.RESOLVE",
    )
    def resolve_fx_rate(
        request: Request,
        company_id: str,
        purpose: str,
        base_currency: str,
        quote_currency: str,
        desired_rate_date: date,
        as_of: datetime | None = None,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        requester_subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        return _invoke(
            request,
            authorization,
            lambda service: service.resolve_rate(
                tenant_id=tenant_id,
                requester_subject_id=requester_subject_id,
                company_id=company_id,
                purpose=purpose,
                base_currency=base_currency,
                quote_currency=quote_currency,
                desired_rate_date=desired_rate_date,
                as_of=as_of,
            ),
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
    service: EosFxRateService | None = getattr(
        request.app.state, "eos_fx_rate_service", None
    )
    if service is None:
        return problem_response(
            request,
            status_code=503,
            error_code="EOS_FX_RATE_SERVICE_UNAVAILABLE",
            title="EOS FX rate service unavailable",
            detail="FX policy persistence or OA authorization is not configured.",
            retryable=True,
            type_uri="https://nex-platform.local/problems/eos-fx-rate-service-unavailable",
        )
    try:
        return operation(service)
    except EosFxRateError as exc:
        return problem_response(
            request,
            status_code=exc.status_code,
            error_code=exc.error_code,
            title="EOS FX rate operation failed",
            detail=exc.detail,
            retryable=exc.retryable,
            type_uri="https://nex-platform.local/problems/eos-fx-rate-operation-failed",
        )
