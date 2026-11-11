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

from .project_work_codes import EosProjectBusinessService, EosProjectWorkCodeError
from .voucher_commands import EosServiceCaller


def register_project_business_routes(app: FastAPI) -> None:
    @app.post(
        "/internal/v2/projects/{project_id}/work-code-sets:approve",
        response_model=None,
        operation_id="PROJECT.WORK_CODE_SET.APPROVE",
    )
    def approve_work_code_set(
        project_id: str,
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        admitted = _admit(request, authorization, route_class="WRITE")
        if isinstance(admitted, JSONResponse):
            return admitted
        service = _service(request)
        if isinstance(service, JSONResponse):
            return service
        try:
            result = service.approve_work_code_set(
                {**payload, "project_id": project_id},
                caller=EosServiceCaller(
                    admitted.subject, admitted.audience, admitted.scopes
                ),
            )
        except EosProjectWorkCodeError as exc:
            return _problem(request, exc)
        return JSONResponse(result, status_code=201 if result["created"] else 200)

    @app.get(
        "/internal/v2/projects/{project_id}/work-code-set",
        response_model=None,
        operation_id="PROJECT.WORK_CODE_SET.GET",
    )
    def get_work_code_set(
        project_id: str,
        request: Request,
        effective_on: date | None = None,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        requester_subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        return _read(
            request,
            authorization,
            lambda service: service.get_work_code_set(
                tenant_id=tenant_id,
                project_id=project_id,
                requester_subject_id=requester_subject_id,
                effective_on=effective_on,
            ),
        )

    @app.get(
        "/internal/v2/projects/{project_id}/business-readiness",
        response_model=None,
        operation_id="PROJECT.BUSINESS_READINESS.GET",
    )
    def get_business_readiness(
        project_id: str,
        request: Request,
        effective_on: date | None = None,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        requester_subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        return _read(
            request,
            authorization,
            lambda service: service.get_business_readiness(
                tenant_id=tenant_id,
                project_id=project_id,
                requester_subject_id=requester_subject_id,
                effective_on=effective_on,
            ),
        )


def _read(request: Request, authorization: str | None, operation):
    admitted = _admit(request, authorization)
    if isinstance(admitted, JSONResponse):
        return admitted
    service = _service(request)
    if isinstance(service, JSONResponse):
        return service
    try:
        return operation(service)
    except EosProjectWorkCodeError as exc:
        return _problem(request, exc)


def _admit(
    request: Request, authorization: str | None, *, route_class: str | None = None
):
    options: dict[str, Any] = {
        "expected_audience": "nex-eos",
        "required_scopes": (DEFAULT_SERVICE_SCOPE,),
    }
    if route_class is not None:
        options["route_class"] = route_class
    return admit_service_token_from_request(request, authorization, **options)


def _service(request: Request):
    service: EosProjectBusinessService | None = getattr(
        request.app.state, "eos_project_business_service", None
    )
    if service is not None:
        return service
    return problem_response(
        request,
        status_code=503,
        error_code="EOS_PROJECT_BUSINESS_SERVICE_UNAVAILABLE",
        title="EOS Project business service unavailable",
        detail="Project WorkCodeSet persistence or OA authorization is not configured.",
        retryable=True,
        type_uri=(
            "https://nex-platform.local/problems/"
            "eos-project-business-service-unavailable"
        ),
    )


def _problem(request: Request, exc: EosProjectWorkCodeError) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="EOS Project WorkCodeSet operation failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri=(
            "https://nex-platform.local/problems/eos-project-work-code-operation-failed"
        ),
    )
