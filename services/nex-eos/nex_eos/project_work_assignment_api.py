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

from .project_work_assignments import (
    EosProjectWorkAssignmentError,
    EosProjectWorkAssignmentService,
)
from .voucher_commands import EosServiceCaller


def register_project_work_assignment_routes(app: FastAPI) -> None:
    @app.post(
        "/internal/v2/projects/{project_id}/work-assignments:assign",
        response_model=None,
        operation_id="PROJECT.WORK_ASSIGNMENT.ASSIGN",
    )
    def assign_project_work(
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
            result = service.assign(
                {**payload, "project_id": project_id},
                caller=EosServiceCaller(
                    admitted.subject, admitted.audience, admitted.scopes
                ),
            )
        except EosProjectWorkAssignmentError as exc:
            return _problem(request, exc)
        return JSONResponse(result, status_code=201 if result["created"] else 200)

    @app.get(
        "/internal/v2/projects/{project_id}/work-assignments",
        response_model=None,
        operation_id="PROJECT.WORK_ASSIGNMENT.LIST",
    )
    def list_project_work_assignments(
        project_id: str,
        request: Request,
        effective_on: date | None = None,
        work_code_id: str | None = None,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        requester_subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        admitted = _admit(request, authorization)
        if isinstance(admitted, JSONResponse):
            return admitted
        service = _service(request)
        if isinstance(service, JSONResponse):
            return service
        try:
            return service.list_assignments(
                tenant_id=tenant_id,
                project_id=project_id,
                requester_subject_id=requester_subject_id,
                effective_on=effective_on,
                work_code_id=work_code_id,
            )
        except EosProjectWorkAssignmentError as exc:
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
    service: EosProjectWorkAssignmentService | None = getattr(
        request.app.state, "eos_project_work_assignment_service", None
    )
    if service is not None:
        return service
    return problem_response(
        request,
        status_code=503,
        error_code="EOS_PROJECT_WORK_ASSIGNMENT_SERVICE_UNAVAILABLE",
        title="EOS Project WorkAssignment service unavailable",
        detail="WorkAssignment persistence or OA authorization is not configured.",
        retryable=True,
        type_uri=(
            "https://nex-platform.local/problems/"
            "eos-project-work-assignment-service-unavailable"
        ),
    )


def _problem(request: Request, exc: EosProjectWorkAssignmentError) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="EOS Project WorkAssignment operation failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri=(
            "https://nex-platform.local/problems/"
            "eos-project-work-assignment-operation-failed"
        ),
    )
