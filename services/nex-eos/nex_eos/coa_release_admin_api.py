from __future__ import annotations

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    admit_service_token_from_request,
    problem_response,
)

from .coa_release_admin import EosCoaReleaseAdminError, EosCoaReleaseAdminService


def register_coa_release_admin_routes(app: FastAPI) -> None:
    @app.get(
        "/internal/v2/finance/coa/releases/diff",
        response_model=None,
        operation_id="FINANCE.COA.RELEASE_DIFF_PREVIEW",
    )
    def preview_release_diff(
        request: Request,
        base_release_id: str,
        target_release_id: str,
        actor_tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        requester_subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        admitted = _admit(request, authorization)
        if admitted is not None:
            return admitted
        service = _service(request)
        if service is None:
            return _unavailable(request)
        try:
            return service.preview_diff(
                actor_tenant_id=actor_tenant_id,
                requester_subject_id=requester_subject_id,
                base_release_id=base_release_id,
                target_release_id=target_release_id,
            )
        except EosCoaReleaseAdminError as exc:
            return _problem(request, exc)

    @app.get(
        "/internal/v2/finance/coa/operations",
        response_model=None,
        operation_id="FINANCE.COA.OPERATIONS_SNAPSHOT",
    )
    def coa_operations_snapshot(
        request: Request,
        actor_tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        requester_subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        admitted = _admit(request, authorization)
        if admitted is not None:
            return admitted
        service = _service(request)
        if service is None:
            return _unavailable(request)
        try:
            return service.operations_snapshot(
                actor_tenant_id=actor_tenant_id,
                requester_subject_id=requester_subject_id,
            )
        except EosCoaReleaseAdminError as exc:
            return _problem(request, exc)


def _admit(request: Request, authorization: str | None) -> JSONResponse | None:
    admitted = admit_service_token_from_request(
        request,
        authorization,
        expected_audience="nex-eos",
        required_scopes=(DEFAULT_SERVICE_SCOPE,),
    )
    return admitted if isinstance(admitted, JSONResponse) else None


def _service(request: Request) -> EosCoaReleaseAdminService | None:
    return getattr(request.app.state, "eos_coa_release_admin_service", None)


def _unavailable(request: Request) -> JSONResponse:
    return problem_response(
        request,
        status_code=503,
        error_code="EOS_COA_ADMIN_SERVICE_UNAVAILABLE",
        title="EOS COA administration unavailable",
        detail="COA persistence or OA authorization is not configured.",
        retryable=True,
        type_uri="https://nex-platform.local/problems/eos-coa-admin-unavailable",
    )


def _problem(request: Request, exc: EosCoaReleaseAdminError) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="EOS COA administration failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/eos-coa-admin-failed",
    )
