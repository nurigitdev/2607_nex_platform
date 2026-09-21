from __future__ import annotations

from datetime import datetime

from fastapi import Request
from fastapi.responses import JSONResponse

from nex_runtime import problem_response
from nex_cx.access_context import (
    CX_ACCESS_CONTEXT_ALLOWED_CALLERS,
    CxAccessContextError,
    authenticate_cx_service_claim,
)


CX_CALLER_SERVICE_STATE_KEY = "cx_caller_service_id"
CX_CALLER_SCOPES_STATE_KEY = "cx_caller_scopes"


def authorize_cx_request(
    request: Request,
    authorization: str | None,
    *,
    now: datetime | None = None,
) -> JSONResponse | None:
    try:
        claims = authenticate_cx_service_claim(
            authorization=authorization,
            now=now,
        )
    except CxAccessContextError as exc:
        return _authorization_problem_response(request, exc)

    setattr(request.state, CX_CALLER_SERVICE_STATE_KEY, claims.service_id)
    setattr(request.state, CX_CALLER_SCOPES_STATE_KEY, claims.scopes)
    return None


def _authorization_problem_response(
    request: Request,
    exc: CxAccessContextError,
) -> JSONResponse:
    authentication_failure = exc.status_code == 401
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title=(
            "Authentication failed"
            if authentication_failure
            else "Authorization failed"
        ),
        detail=exc.detail,
        type_uri=(
            "https://nex-platform.local/problems/authentication-failed"
            if authentication_failure
            else "https://nex-platform.local/problems/authorization-failed"
        ),
        details={
            "allowed_caller_services": sorted(CX_ACCESS_CONTEXT_ALLOWED_CALLERS)
        }
        if not authentication_failure
        else None,
    )
