from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    admit_service_token_from_request,
    problem_response,
)

from .project_applications import (
    EosProjectApplicationError,
    ProjectApplicationDraft,
)


def register_project_application_routes(app: FastAPI) -> None:
    @app.post(
        "/internal/v2/project-applications",
        response_model=None,
        operation_id="PROJECT.APPLICATION.CREATE",
    )
    def create_project_application(
        payload: dict[str, Any],
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        requester_subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        return _call(
            request,
            authorization,
            lambda service: service.create_draft(
                _draft(tenant_id, requester_subject_id, payload),
                requester_subject_id=requester_subject_id,
            ),
            created_status=201,
        )

    @app.patch(
        "/internal/v2/project-applications/{project_request_code}",
        response_model=None,
        operation_id="PROJECT.APPLICATION.REVISE",
    )
    def revise_project_application(
        project_request_code: str,
        payload: dict[str, Any],
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        requester_subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        return _call(
            request,
            authorization,
            lambda service: _revise(
                service,
                tenant_id=tenant_id,
                requester_subject_id=requester_subject_id,
                project_request_code=project_request_code,
                payload=payload,
            ),
        )

    @app.post(
        "/internal/v2/project-applications/{project_request_code}:submit",
        response_model=None,
        operation_id="PROJECT.APPLICATION.SUBMIT",
    )
    def submit_project_application(
        project_request_code: str,
        payload: dict[str, Any],
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        requester_subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        return _call(
            request,
            authorization,
            lambda service: service.submit(
                tenant_id=tenant_id,
                project_request_code=project_request_code,
                expected_version=_positive_int(
                    "expected_version", payload.get("expected_version")
                ),
                requester_subject_id=requester_subject_id,
            ),
        )

    @app.get(
        "/internal/v2/project-applications/{project_request_code}",
        response_model=None,
        operation_id="PROJECT.APPLICATION.GET",
    )
    def get_project_application(
        project_request_code: str,
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        requester_subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        return _call(
            request,
            authorization,
            lambda service: service.get_application(
                tenant_id=tenant_id,
                project_request_code=project_request_code,
                requester_subject_id=requester_subject_id,
            ),
        )

    @app.get(
        "/internal/v2/projects:resolve",
        response_model=None,
        operation_id="PROJECT.PROJECT.RESOLVE",
    )
    def resolve_project_code(
        project_code: str,
        request: Request,
        active_only: bool = False,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        requester_subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        return _call(
            request,
            authorization,
            lambda service: service.resolve_project(
                tenant_id=tenant_id,
                project_code=project_code,
                requester_subject_id=requester_subject_id,
                active_only=active_only,
            ),
        )


def _revise(
    service,
    *,
    tenant_id: str,
    requester_subject_id: str,
    project_request_code: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    current = service.get_application(
        tenant_id=tenant_id,
        project_request_code=project_request_code,
        requester_subject_id=requester_subject_id,
    )
    application_id = current["application_id"]
    return service.revise_draft(
        _draft(
            tenant_id,
            requester_subject_id,
            {**payload, "application_id": application_id},
        ),
        expected_version=_positive_int(
            "expected_version", payload.get("expected_version")
        ),
        requester_subject_id=requester_subject_id,
    )


def _draft(
    tenant_id: str, requester_subject_id: str, payload: dict[str, Any]
) -> ProjectApplicationDraft:
    return ProjectApplicationDraft(
        tenant_id=tenant_id,
        application_id=str(payload.get("application_id", "")),
        purpose_type=str(payload.get("purpose_type", "")),
        applicant_subject_id=requester_subject_id,
        name=str(payload.get("name", "")),
        parent_project_id=_optional_string(payload.get("parent_project_id")),
        nvt_project_id=_optional_string(payload.get("nvt_project_id")),
        company_id=_optional_string(payload.get("company_id")),
        start_date=_optional_date("start_date", payload.get("start_date")),
        end_date=_optional_date("end_date", payload.get("end_date")),
        currency=str(payload.get("currency", "KRW")),
    )


def _call(
    request: Request,
    authorization: str | None,
    operation: Callable,
    *,
    created_status: int | None = None,
):
    admitted = admit_service_token_from_request(
        request,
        authorization,
        expected_audience="nex-eos",
        required_scopes=(DEFAULT_SERVICE_SCOPE,),
    )
    if isinstance(admitted, JSONResponse):
        return admitted
    service = getattr(request.app.state, "eos_project_application_service", None)
    if service is None:
        return problem_response(
            request,
            status_code=503,
            error_code="EOS_PROJECT_APPLICATION_UNAVAILABLE",
            title="EOS Project application unavailable",
            detail="Project application dependencies are not configured",
            retryable=True,
            type_uri=(
                "https://nex-platform.local/problems/"
                "eos-project-application-unavailable"
            ),
        )
    try:
        result = operation(service)
    except EosProjectApplicationError as exc:
        return problem_response(
            request,
            status_code=exc.status_code,
            error_code=exc.error_code,
            title="EOS Project application failed",
            detail=exc.detail,
            retryable=exc.retryable,
            type_uri=(
                "https://nex-platform.local/problems/eos-project-application-failed"
            ),
        )
    status = created_status if created_status is not None else 200
    return JSONResponse(result, status_code=status)


def _optional_string(value: object) -> str | None:
    return None if value is None else str(value)


def _optional_date(field_name: str, value: object) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise EosProjectApplicationError(
            "EOS_PROJECT_APPLICATION_INVALID",
            f"{field_name} must be an ISO date",
            status_code=422,
        )
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise EosProjectApplicationError(
            "EOS_PROJECT_APPLICATION_INVALID",
            f"{field_name} must be an ISO date",
            status_code=422,
        ) from exc


def _positive_int(field_name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise EosProjectApplicationError(
            "EOS_PROJECT_APPLICATION_INVALID",
            f"{field_name} must be a positive integer",
            status_code=422,
        )
    return value
