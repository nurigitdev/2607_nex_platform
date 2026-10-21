from __future__ import annotations

from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse
from nex_runtime import DEFAULT_SERVICE_SCOPE, problem_response
from nex_runtime.auth import validate_authorization_header

from nex_wc.approvals import ApprovalInboxError, ApprovalInboxService


def register_approval_routes(
    app: FastAPI, *, inbox_service: ApprovalInboxService
) -> None:
    @app.get("/api/v1/approval-gates", response_model=None)
    def list_approval_gates(
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        subject_id: str = Header(alias="X-NeX-Subject-Id"),
        limit: int = Query(default=50),
        authorization: str | None = Header(default=None),
    ):
        denied = _authorize(request, authorization)
        if denied is not None:
            return denied
        try:
            return inbox_service.list_pending(
                tenant_id=tenant_id,
                subject_id=subject_id,
                limit=limit,
            )
        except ApprovalInboxError as exc:
            return problem_response(
                request,
                status_code=exc.status_code,
                error_code=exc.error_code,
                title="WC approval inbox request failed",
                detail=exc.detail,
                retryable=exc.retryable,
                type_uri=(
                    "https://nex-platform.local/problems/"
                    "wc-approval-inbox-request-failed"
                ),
            )


def _authorize(request: Request, authorization: str | None) -> JSONResponse | None:
    result = validate_authorization_header(
        authorization,
        expected_audience="nex-wc",
        required_scopes=(DEFAULT_SERVICE_SCOPE,),
    )
    if result.ok:
        return None
    status = 403 if result.error_code == "SERVICE_SCOPE_MISSING" else 401
    return problem_response(
        request,
        status_code=status,
        error_code=result.error_code or "WC_AUTHORIZATION_FAILED",
        title="WC service authorization failed",
        detail=result.detail or "WC service authorization failed.",
        retryable=False,
        type_uri="https://nex-platform.local/problems/wc-service-authorization-failed",
    )
