from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    admit_service_token_from_request,
    problem_response,
)

from .account_catalog import EosAccountCatalogError, EosAccountCatalogService


def register_account_policy_routes(app: FastAPI) -> None:
    @app.get(
        "/internal/v2/finance/account-catalog",
        response_model=None,
        operation_id="FINANCE.ACCOUNT.CATALOG_GET",
    )
    def get_account_catalog(
        request: Request,
        company_id: str,
        effective_on: date,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        requester_subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        return _invoke(
            request,
            authorization,
            lambda service: service.get_catalog(
                tenant_id=tenant_id,
                company_id=company_id,
                requester_subject_id=requester_subject_id,
                effective_on=effective_on,
            ),
        )

    @app.post(
        "/internal/v2/finance/accounts/approved",
        response_model=None,
        operation_id="FINANCE.ACCOUNT.CREATE_APPROVED",
    )
    def create_approved_account(
        payload: dict[str, Any],
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        requester_subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        result = _invoke(
            request,
            authorization,
            lambda service: service.create_approved_account(
                tenant_id=tenant_id,
                requester_subject_id=requester_subject_id,
                payload=payload,
            ),
            route_class="WRITE",
        )
        return result if isinstance(result, JSONResponse) else JSONResponse(result, 201)


def _invoke(
    request: Request,
    authorization: str | None,
    operation,
    *,
    route_class: str | None = None,
):
    admission_options: dict[str, Any] = {
        "expected_audience": "nex-eos",
        "required_scopes": (DEFAULT_SERVICE_SCOPE,),
    }
    if route_class is not None:
        admission_options["route_class"] = route_class
    admitted = admit_service_token_from_request(
        request,
        authorization,
        **admission_options,
    )
    if isinstance(admitted, JSONResponse):
        return admitted
    service: EosAccountCatalogService | None = getattr(
        request.app.state, "eos_account_catalog_service", None
    )
    if service is None:
        return problem_response(
            request,
            status_code=503,
            error_code="EOS_ACCOUNT_CATALOG_SERVICE_UNAVAILABLE",
            title="EOS Account catalog service unavailable",
            detail="Account catalog persistence or OA authorization is not configured.",
            retryable=True,
            type_uri=(
                "https://nex-platform.local/problems/"
                "eos-account-catalog-service-unavailable"
            ),
        )
    try:
        return operation(service)
    except EosAccountCatalogError as exc:
        return problem_response(
            request,
            status_code=exc.status_code,
            error_code=exc.error_code,
            title="EOS Account catalog operation failed",
            detail=exc.detail,
            retryable=exc.retryable,
            type_uri=(
                "https://nex-platform.local/problems/"
                "eos-account-catalog-operation-failed"
            ),
        )
