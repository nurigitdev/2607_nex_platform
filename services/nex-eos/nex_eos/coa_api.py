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

from .coa_operations import EosCoaOperationError, EosCoaOperationsService


def register_coa_routes(app: FastAPI) -> None:
    @app.post(
        "/internal/v2/finance/coa/releases/{definition_release_id}/publish",
        response_model=None,
        operation_id="FINANCE.COA.PUBLISH_APPROVED",
    )
    def publish_approved_coa(
        definition_release_id: str,
        payload: dict[str, Any],
        request: Request,
        actor_tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        requester_subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        command = {**payload, "definition_release_id": definition_release_id}
        result = _invoke(
            request,
            authorization,
            lambda service: service.publish_approved(
                actor_tenant_id=actor_tenant_id,
                requester_subject_id=requester_subject_id,
                payload=command,
            ),
        )
        if isinstance(result, JSONResponse):
            return result
        return JSONResponse(result, 201 if result.get("created") else 200)

    @app.post(
        "/internal/v2/finance/coa/adoptions",
        response_model=None,
        operation_id="FINANCE.COA.ADOPT_APPROVED",
    )
    def adopt_approved_coa(
        payload: dict[str, Any],
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        requester_subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        result = _invoke(
            request,
            authorization,
            lambda service: service.adopt_approved(
                tenant_id=tenant_id,
                requester_subject_id=requester_subject_id,
                payload=payload,
            ),
        )
        if isinstance(result, JSONResponse):
            return result
        return JSONResponse(result, 201 if result.get("created") else 200)

    @app.post(
        "/internal/v2/finance/coa/extensions/{definition_release_id}/publish",
        response_model=None,
        operation_id="FINANCE.COA.EXTENSION_PUBLISH_APPROVED",
    )
    def publish_approved_extension(
        definition_release_id: str,
        payload: dict[str, Any],
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        requester_subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        command = {**payload, "definition_release_id": definition_release_id}
        result = _invoke(
            request,
            authorization,
            lambda service: service.publish_extension_approved(
                tenant_id=tenant_id,
                requester_subject_id=requester_subject_id,
                payload=command,
            ),
        )
        if isinstance(result, JSONResponse):
            return result
        return JSONResponse(result, 201 if result.get("created") else 200)

    @app.get(
        "/internal/v2/finance/accounts/resolve-semantic",
        response_model=None,
        operation_id="FINANCE.COA.RESOLVE_SEMANTIC",
    )
    def resolve_semantic_account(
        request: Request,
        company_id: str,
        semantic_key: str,
        effective_on: date,
        currency: str,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        requester_subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        return _invoke(
            request,
            authorization,
            lambda service: service.resolve_semantic_account(
                tenant_id=tenant_id,
                requester_subject_id=requester_subject_id,
                company_id=company_id,
                semantic_key=semantic_key,
                effective_on=effective_on,
                currency=currency,
            ),
            route_class=None,
        )


def _invoke(
    request: Request,
    authorization: str | None,
    operation,
    *,
    route_class: str | None = "WRITE",
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
    service: EosCoaOperationsService | None = getattr(
        request.app.state, "eos_coa_operations_service", None
    )
    if service is None:
        return problem_response(
            request,
            status_code=503,
            error_code="EOS_COA_SERVICE_UNAVAILABLE",
            title="EOS COA service unavailable",
            detail=(
                "COA persistence, OA authorization, or publication admission "
                "is not configured."
            ),
            retryable=True,
            type_uri="https://nex-platform.local/problems/eos-coa-service-unavailable",
        )
    try:
        return operation(service)
    except EosCoaOperationError as exc:
        return problem_response(
            request,
            status_code=exc.status_code,
            error_code=exc.error_code,
            title="EOS COA operation failed",
            detail=exc.detail,
            retryable=exc.retryable,
            type_uri="https://nex-platform.local/problems/eos-coa-operation-failed",
        )
