from __future__ import annotations

from datetime import datetime

from fastapi import Request
from fastapi.responses import JSONResponse

from nex_runtime import problem_response
from nex_cx.access_context import (
    CX_ACCESS_CONTEXT_ALLOWED_CALLERS,
    CxAccessContext,
    CxAccessContextError,
    authenticate_cx_service_claim,
    resolve_cx_access_context,
)


CX_CALLER_SERVICE_STATE_KEY = "cx_caller_service_id"
CX_CALLER_SCOPES_STATE_KEY = "cx_caller_scopes"
CX_ACCESS_CONTEXT_STATE_KEY = "cx_access_context"
CX_TENANT_HEADER = "X-NEX-Tenant-ID"
CX_SUBJECT_HEADER = "X-NEX-Subject-ID"


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


def authorize_cx_owner_request(
    request: Request,
    authorization: str | None,
    *,
    tenant_id: object,
    subject_id: object,
    now: datetime | None = None,
) -> CxAccessContext | JSONResponse:
    try:
        context = resolve_cx_access_context(
            authorization=authorization,
            tenant_id=tenant_id,
            subject_id=subject_id,
            request_id=request.headers.get("X-Request-ID"),
            trace_id=_trace_id_from_request(request),
            now=now,
        )
    except CxAccessContextError as exc:
        return _authorization_problem_response(request, exc)

    setattr(request.state, CX_CALLER_SERVICE_STATE_KEY, context.caller_service_id)
    setattr(request.state, CX_CALLER_SCOPES_STATE_KEY, context.scopes)
    setattr(request.state, CX_ACCESS_CONTEXT_STATE_KEY, context)
    return context


def _trace_id_from_request(request: Request) -> str | None:
    traceparent = request.headers.get("traceparent")
    if traceparent:
        parts = traceparent.split("-")
        if len(parts) == 4:
            return parts[1]
    return request.headers.get("X-Trace-ID")


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
