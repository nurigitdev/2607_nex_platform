from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    admit_service_token_from_request,
    problem_response,
)

from .project_operations import EosGovernedProjectError
from .voucher_commands import EosServiceCaller


def register_project_routes(app: FastAPI) -> None:
    @app.post(
        "/internal/v1/projects",
        response_model=None,
        operation_id="PROJECT.PROJECT.CREATE",
    )
    def create_project(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        return _write(request, authorization, lambda service, caller: service.create_project(payload, caller=caller))

    @app.post(
        "/internal/v1/projects/{project_id}:deactivate",
        response_model=None,
        operation_id="PROJECT.PROJECT.DEACTIVATE",
    )
    def deactivate_project(
        project_id: str,
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        return _write(
            request,
            authorization,
            lambda service, caller: service.deactivate_project(
                {**payload, "project_id": project_id}, caller=caller
            ),
        )

    @app.post(
        "/internal/v1/projects/{project_id}/memberships",
        response_model=None,
        operation_id="PROJECT.MEMBERSHIP.ADD",
    )
    def add_membership(
        project_id: str,
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        return _write(
            request,
            authorization,
            lambda service, caller: service.add_membership(
                {**payload, "project_id": project_id}, caller=caller
            ),
        )

    @app.post(
        "/internal/v1/projects/{project_id}/memberships/{subject_id}:remove",
        response_model=None,
        operation_id="PROJECT.MEMBERSHIP.REMOVE",
    )
    def remove_membership(
        project_id: str,
        subject_id: str,
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        return _write(
            request,
            authorization,
            lambda service, caller: service.remove_membership(
                {**payload, "project_id": project_id, "target_subject_id": subject_id},
                caller=caller,
            ),
        )

    @app.get(
        "/internal/v1/projects/{project_id}",
        response_model=None,
        operation_id="PROJECT.PROJECT.GET",
    )
    def get_project(
        project_id: str,
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        requester_subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        return _read(
            request,
            authorization,
            lambda service: service.get_project(
                tenant_id=tenant_id,
                project_id=project_id,
                requester_subject_id=requester_subject_id,
            ),
        )

    @app.get(
        "/internal/v1/projects",
        response_model=None,
        operation_id="PROJECT.PROJECT.LIST",
    )
    def list_projects(
        request: Request,
        limit: int = 100,
        offset: int = 0,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        requester_subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        return _read(
            request,
            authorization,
            lambda service: {
                "items": service.list_projects(
                    tenant_id=tenant_id,
                    requester_subject_id=requester_subject_id,
                    limit=limit,
                    offset=offset,
                ),
                "limit": limit,
                "offset": offset,
            },
        )

    @app.get(
        "/internal/v1/projects/{project_id}/memberships",
        response_model=None,
        operation_id="PROJECT.MEMBERSHIP.LIST",
    )
    def list_memberships(
        project_id: str,
        request: Request,
        limit: int = 100,
        offset: int = 0,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        requester_subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        return _read(
            request,
            authorization,
            lambda service: {
                "items": service.list_memberships(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    requester_subject_id=requester_subject_id,
                    limit=limit,
                    offset=offset,
                ),
                "limit": limit,
                "offset": offset,
            },
        )


def _write(request: Request, authorization: str | None, operation: Callable):
    admitted = _admit(request, authorization, route_class="WRITE")
    if isinstance(admitted, JSONResponse):
        return admitted
    service = _service(request)
    if isinstance(service, JSONResponse):
        return service
    try:
        result = operation(
            service,
            EosServiceCaller(admitted.subject, admitted.audience, admitted.scopes),
        )
    except EosGovernedProjectError as exc:
        return _problem(request, exc)
    return JSONResponse(result, status_code=201 if result["created"] else 200)


def _read(request: Request, authorization: str | None, operation: Callable):
    admitted = _admit(request, authorization)
    if isinstance(admitted, JSONResponse):
        return admitted
    service = _service(request)
    if isinstance(service, JSONResponse):
        return service
    try:
        return operation(service)
    except EosGovernedProjectError as exc:
        return _problem(request, exc)


def _admit(request: Request, authorization: str | None, *, route_class=None):
    kwargs = {
        "expected_audience": "nex-eos",
        "required_scopes": (DEFAULT_SERVICE_SCOPE,),
    }
    if route_class is not None:
        kwargs["route_class"] = route_class
    return admit_service_token_from_request(request, authorization, **kwargs)


def _service(request: Request):
    service = getattr(request.app.state, "eos_project_operations", None)
    if service is not None:
        return service
    return problem_response(
        request,
        status_code=503,
        error_code="EOS_PROJECT_OPERATIONS_UNAVAILABLE",
        title="EOS Project operations unavailable",
        detail="EOS Project operation dependencies are not configured",
        retryable=True,
        type_uri="https://nex-platform.local/problems/eos-project-operations-unavailable",
    )


def _problem(request: Request, exc: EosGovernedProjectError) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="EOS governed Project operation failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/eos-project-operation-failed",
    )
