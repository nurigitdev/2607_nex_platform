from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from nex_runtime import (
    AdmittedServiceClaims,
    DEFAULT_SERVICE_SCOPE,
    DEFAULT_USER_SCOPE,
    admit_service_token_from_request,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
)
from nex_ae_api.auth_guard import (
    BrowserAuthError,
    BrowserUserAuthContext,
    build_browser_user_auth_context,
)
from nex_ae_api.auth_sessions import (
    BrowserSessionFacadeError,
    SESSION_COOKIE_NAME,
    validate_browser_session_credentials,
)
from nex_ae_api.oa_session_client import OaUserSessionClient

AE_FACADE_ROUTE_AUTH_SCHEMA_VERSION = "ae_facade_route_auth.v1"
AE_FACADE_ROUTE_AUTH_MODE_SERVICE = "service"
AE_FACADE_ROUTE_AUTH_MODE_BROWSER_USER = "browser_user"
AE_OPERATIONS_READ_SCOPE = "operations:read"


@dataclass(frozen=True)
class AeFacadeRouteAuthContext:
    auth_mode: str
    service_claims: AdmittedServiceClaims | None = None
    browser_context: BrowserUserAuthContext | None = None

    @property
    def is_browser_user(self) -> bool:
        return self.auth_mode == AE_FACADE_ROUTE_AUTH_MODE_BROWSER_USER

    def to_wire(self) -> dict[str, Any]:
        if self.browser_context is not None:
            return {
                "auth_schema_version": AE_FACADE_ROUTE_AUTH_SCHEMA_VERSION,
                "auth_mode": self.auth_mode,
                "tenant_ref": {
                    "type": "oa.tenant",
                    "id": self.browser_context.tenant_id,
                },
                "subject_ref": {
                    "type": "oa.user",
                    "id": self.browser_context.user_id,
                },
                "owner_scope_authority": "claim",
                "metadata": {
                    "service_token_accepted": False,
                    "raw_token_included": False,
                },
            }
        return {
            "auth_schema_version": AE_FACADE_ROUTE_AUTH_SCHEMA_VERSION,
            "auth_mode": self.auth_mode,
            "service_id": (
                self.service_claims.service_id
                if self.service_claims is not None
                else None
            ),
            "owner_scope_authority": "payload",
            "metadata": {
                "service_token_accepted": True,
                "raw_token_included": False,
            },
        }


def authorize_ae_facade_route_request(
    request: Request,
    authorization: str | None,
    *,
    required_user_scopes: tuple[str, ...] | list[str] = (DEFAULT_USER_SCOPE,),
    oa_session_client: OaUserSessionClient | None = None,
    session_mode: str | None = None,
) -> AeFacadeRouteAuthContext | JSONResponse:
    service_result = admit_service_token_from_request(
        request,
        authorization,
        expected_audience="nex-ae-api",
        required_scopes=(DEFAULT_SERVICE_SCOPE,),
    )
    if isinstance(service_result, AdmittedServiceClaims):
        return AeFacadeRouteAuthContext(
            auth_mode=AE_FACADE_ROUTE_AUTH_MODE_SERVICE,
            service_claims=service_result,
        )
    if _looks_like_service_authorization(authorization):
        return service_result

    user_result = validate_browser_session_credentials(
        authorization=authorization,
        cookie_token=request.cookies.get(SESSION_COOKIE_NAME),
        required_scopes=required_user_scopes,
        request_id=request_id_from_headers(request),
        trace_id=trace_id_from_headers(request),
        oa_session_client=oa_session_client,
        session_mode=session_mode,
    )
    if not isinstance(user_result, BrowserSessionFacadeError):
        try:
            return AeFacadeRouteAuthContext(
                auth_mode=AE_FACADE_ROUTE_AUTH_MODE_BROWSER_USER,
                browser_context=build_browser_user_auth_context(user_result),
            )
        except BrowserAuthError as exc:
            return _facade_auth_problem_response(
                request,
                status_code=exc.status_code,
                error_code=exc.error_code,
                detail=exc.detail,
                retryable=exc.retryable,
            )

    if authorization or request.cookies.get(SESSION_COOKIE_NAME):
        return _facade_auth_problem_response(
            request,
            status_code=user_result.status_code,
            error_code=user_result.error_code,
            detail=user_result.detail,
            retryable=user_result.retryable,
        )

    return service_result


def authorize_ae_operations_request(
    request: Request,
    authorization: str | None,
) -> JSONResponse | None:
    admitted = admit_service_token_from_request(
        request,
        authorization,
        expected_audience="nex-ae-api",
        required_scopes=(DEFAULT_SERVICE_SCOPE, AE_OPERATIONS_READ_SCOPE),
        route_class="ADMIN",
    )
    if isinstance(admitted, JSONResponse):
        return admitted
    if admitted.service_id != "nex-ag":
        return problem_response(
            request,
            status_code=403,
            error_code="AE_OPERATIONS_CALLER_FORBIDDEN",
            title="Authorization failed",
            detail="AE trace operations are available only to NeX-AG.",
            type_uri="https://nex-platform.local/problems/authorization-failed",
        )
    return None


def _looks_like_service_authorization(authorization: str | None) -> bool:
    if not authorization or not authorization.startswith("Bearer "):
        return False
    token = authorization[7:]
    return token.startswith("nex-mock-service.") or token.count(".") == 2


def _facade_auth_problem_response(
    request: Request,
    *,
    status_code: int,
    error_code: str,
    detail: str,
    retryable: bool = False,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=status_code,
        error_code=error_code,
        title="AE route authentication failed",
        detail=detail,
        retryable=retryable,
        type_uri="https://nex-platform.local/problems/ae-route-authentication-failed",
    )
