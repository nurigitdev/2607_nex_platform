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

from .legal_entities import EosLegalEntityError, EosLegalEntityService


def register_legal_entity_routes(app: FastAPI) -> None:
    @app.get(
        "/internal/v2/finance/legal-entities/{company_id}",
        response_model=None,
        operation_id="FINANCE.LEGAL_ENTITY.GET",
    )
    def get_legal_entity(
        company_id: str,
        request: Request,
        effective_on: date | None = None,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        requester_subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        return _invoke(
            request,
            authorization,
            lambda service: service.get_legal_entity(
                tenant_id=tenant_id,
                company_id=company_id,
                requester_subject_id=requester_subject_id,
                effective_on=effective_on,
            ),
        )

    @app.post(
        "/internal/v2/projects/{project_id}/company-bindings",
        response_model=None,
        operation_id="PROJECT.COMPANY_BINDING.CREATE",
    )
    def bind_project_company(
        project_id: str,
        payload: dict[str, Any],
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        requester_subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        result = _invoke(
            request,
            authorization,
            lambda service: service.bind_project(
                tenant_id=tenant_id,
                project_id=project_id,
                requester_subject_id=requester_subject_id,
                payload=payload,
            ),
            route_class="WRITE",
        )
        return result if isinstance(result, JSONResponse) else JSONResponse(result, 201)

    @app.get(
        "/internal/v2/projects/{project_id}/company-binding",
        response_model=None,
        operation_id="PROJECT.COMPANY_BINDING.GET",
    )
    def get_project_company_binding(
        project_id: str,
        effective_on: date,
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        requester_subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        return _invoke(
            request,
            authorization,
            lambda service: service.get_project_company_binding(
                tenant_id=tenant_id,
                project_id=project_id,
                requester_subject_id=requester_subject_id,
                effective_on=effective_on,
            ),
        )


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
    service: EosLegalEntityService | None = getattr(
        request.app.state, "eos_legal_entity_service", None
    )
    if service is None:
        return problem_response(
            request,
            status_code=503,
            error_code="EOS_LEGAL_ENTITY_SERVICE_UNAVAILABLE",
            title="EOS LegalEntity service unavailable",
            detail="LegalEntity persistence or OA authorization is not configured.",
            retryable=True,
            type_uri=(
                "https://nex-platform.local/problems/"
                "eos-legal-entity-service-unavailable"
            ),
        )
    try:
        return operation(service)
    except EosLegalEntityError as exc:
        return problem_response(
            request,
            status_code=exc.status_code,
            error_code=exc.error_code,
            title="EOS LegalEntity operation failed",
            detail=exc.detail,
            retryable=exc.retryable,
            type_uri=(
                "https://nex-platform.local/problems/eos-legal-entity-operation-failed"
            ),
        )
