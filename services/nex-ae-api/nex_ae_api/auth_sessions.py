from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Mapping
from uuid import uuid5, NAMESPACE_URL

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_runtime import (
    DEFAULT_USER_SCOPE,
    UserClaims,
    issue_mock_user_token,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
    validate_mock_user_token,
    validate_user_authorization_header,
)
from nex_ae_api.auth_guard import (
    BrowserAuthError,
    OA_TENANT_REF_TYPE,
    OA_USER_SUBJECT_REF_TYPE,
    build_browser_user_auth_context,
)
from nex_ae_api.oa_session_client import (
    OaUserSessionClient,
    OaUserSessionClientError,
    build_default_oa_user_session_client,
)


AE_AUTH_SESSION_FACADE_SCHEMA_VERSION = "ae_auth_session_facade.v1"
OA_BROWSER_SESSION_SCHEMA_VERSION = "oa_browser_session.v1"
SESSION_COOKIE_NAME = "nex_ae_user_session"
AUTH_SESSION_MODE_ENV = "NEX_AE_AUTH_SESSION_MODE"
AUTH_SESSION_MODE_MOCK = "mock"
AUTH_SESSION_MODE_OA = "oa"
AUTH_SESSION_MODES = frozenset({AUTH_SESSION_MODE_MOCK, AUTH_SESSION_MODE_OA})
DEFAULT_LOGIN_TENANT_ID = "tenant-local"
DEFAULT_LOGIN_USER_ID = "user-local"
DEFAULT_LOGIN_ROLES = ("employee",)
DEFAULT_LOGIN_TTL_SECONDS = 3600
MAX_LOGIN_TTL_SECONDS = 86400

LOGIN_FIELDS = frozenset(
    {
        "tenant_id",
        "user_id",
        "login_hint",
        "scopes",
        "roles",
        "ttl_seconds",
    }
)
SENSITIVE_LOGIN_KEY_PARTS = (
    "access",
    "authorization",
    "credential",
    "passwd",
    "password",
    "secret",
    "token",
)


@dataclass(frozen=True)
class BrowserSessionFacadeError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


def register_auth_session_routes(
    app: FastAPI,
    *,
    oa_session_client: OaUserSessionClient | None = None,
    session_mode: str | None = None,
) -> None:
    resolved_session_mode = normalize_auth_session_mode(
        session_mode or os.getenv(AUTH_SESSION_MODE_ENV)
    )
    resolved_oa_session_client = (
        oa_session_client
        if oa_session_client is not None
        else (
            build_default_oa_user_session_client()
            if resolved_session_mode == AUTH_SESSION_MODE_OA
            else None
        )
    )

    @app.get("/api/v1/auth/session", response_model=None)
    def get_auth_session(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any] | JSONResponse:
        result = browser_session_from_request(
            request,
            authorization,
            oa_session_client=resolved_oa_session_client,
            session_mode=resolved_session_mode,
        )
        if isinstance(result, BrowserSessionFacadeError):
            return auth_session_problem_response(request, result)
        return result

    @app.post("/api/v1/auth/session/login", response_model=None)
    async def login_auth_session(request: Request) -> JSONResponse:
        try:
            payload = await _optional_json_object(request)
            login_request = normalize_login_request(payload)
            session, cookie_value = issue_browser_session(
                login_request,
                request=request,
                oa_session_client=resolved_oa_session_client,
                session_mode=resolved_session_mode,
            )
            response = JSONResponse(session)
            response.set_cookie(
                SESSION_COOKIE_NAME,
                cookie_value,
                httponly=True,
                samesite="lax",
                secure=False,
                max_age=login_request["ttl_seconds"],
                path="/",
            )
            return response
        except BrowserSessionFacadeError as exc:
            return auth_session_problem_response(request, exc)

    @app.post("/api/v1/auth/session/logout", response_model=None)
    def logout_auth_session(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        result = revoke_browser_session(
            request=request,
            authorization=authorization,
            cookie_token=request.cookies.get(SESSION_COOKIE_NAME),
            oa_session_client=resolved_oa_session_client,
            session_mode=resolved_session_mode,
        )
        if isinstance(result, BrowserSessionFacadeError):
            response = auth_session_problem_response(request, result)
        else:
            response = JSONResponse(result)
        response.delete_cookie(SESSION_COOKIE_NAME, path="/")
        return response


def browser_session_from_request(
    request: Request,
    authorization: str | None,
    *,
    oa_session_client: OaUserSessionClient | None = None,
    session_mode: str | None = None,
) -> dict[str, Any] | BrowserSessionFacadeError:
    resolved_mode = normalize_auth_session_mode(session_mode)
    cookie_token = request.cookies.get(SESSION_COOKIE_NAME)
    if resolved_mode == AUTH_SESSION_MODE_OA and cookie_token and not authorization:
        try:
            return active_oa_browser_session_from_cookie(
                cookie_token,
                request_id=request_id_from_headers(request),
                trace_id=trace_id_from_headers(request),
                oa_session_client=oa_session_client,
                required_scopes=(DEFAULT_USER_SCOPE,),
            )
        except BrowserSessionFacadeError as exc:
            return exc
    validation = validate_browser_session_credentials(
        authorization=authorization,
        cookie_token=cookie_token,
        request_id=request_id_from_headers(request),
        trace_id=trace_id_from_headers(request),
        oa_session_client=oa_session_client,
        session_mode=resolved_mode,
    )
    if isinstance(validation, BrowserSessionFacadeError):
        return validation
    return build_browser_session_snapshot(validation)


def validate_browser_session_credentials(
    *,
    authorization: str | None,
    cookie_token: str | None,
    required_scopes: tuple[str, ...] | list[str] = (DEFAULT_USER_SCOPE,),
    request_id: str = "ae-local-request",
    trace_id: str = "00000000000000000000000000000000",
    oa_session_client: OaUserSessionClient | None = None,
    session_mode: str | None = None,
) -> UserClaims | BrowserSessionFacadeError:
    resolved_mode = normalize_auth_session_mode(session_mode)
    if authorization:
        result = validate_user_authorization_header(
            authorization,
            expected_audience="nex-ae-api",
            required_scopes=required_scopes,
        )
    elif cookie_token:
        if resolved_mode == AUTH_SESSION_MODE_OA:
            try:
                session = active_oa_browser_session_from_cookie(
                    cookie_token,
                    request_id=request_id,
                    trace_id=trace_id,
                    oa_session_client=oa_session_client,
                    required_scopes=required_scopes,
                )
                return user_claims_from_oa_browser_session(
                    session,
                    required_scopes=required_scopes,
                )
            except BrowserSessionFacadeError as exc:
                return exc
        result = validate_mock_user_token(
            cookie_token,
            expected_audience="nex-ae-api",
            required_scopes=required_scopes,
        )
    else:
        return BrowserSessionFacadeError(
            status_code=401,
            error_code="AUTHORIZATION_HEADER_MISSING",
            detail="AE API requires a valid browser user session.",
        )

    if result.ok and result.claims is not None:
        return result.claims
    return BrowserSessionFacadeError(
        status_code=401,
        error_code=result.error_code or "USER_SESSION_INVALID",
        detail=result.detail or "AE API requires a valid browser user session.",
    )


def issue_browser_session(
    login_request: Mapping[str, Any],
    *,
    request: Request,
    oa_session_client: OaUserSessionClient | None = None,
    session_mode: str | None = None,
) -> tuple[dict[str, Any], str]:
    resolved_mode = normalize_auth_session_mode(session_mode)
    if resolved_mode == AUTH_SESSION_MODE_OA:
        client = required_oa_session_client(oa_session_client)
        try:
            issued = client.issue_session(
                login_request,
                request_id=request_id_from_headers(request),
                trace_id=trace_id_from_headers(request),
            )
        except OaUserSessionClientError as exc:
            raise browser_error_from_oa_client_error(exc) from exc
        session = required_oa_browser_session(
            issued.get("session"),
            error_code="ae.oa_session_issue_invalid",
        )
        user_claims_from_oa_browser_session(
            session,
            required_scopes=login_request.get("scopes", (DEFAULT_USER_SCOPE,)),
        )
        return session, _non_empty_session_text(session.get("session_id"), "session_id")

    issued = issue_mock_user_token(
        tenant_id=str(login_request["tenant_id"]),
        user_id=str(login_request["user_id"]),
        scopes=tuple(login_request["scopes"]),
        roles=tuple(login_request["roles"]),
        issued_at=datetime.now(UTC),
        ttl_seconds=int(login_request["ttl_seconds"]),
    )
    return build_browser_session_snapshot(issued.claims), issued.access_token


def revoke_browser_session(
    *,
    request: Request,
    authorization: str | None,
    cookie_token: str | None,
    oa_session_client: OaUserSessionClient | None = None,
    session_mode: str | None = None,
) -> dict[str, Any] | BrowserSessionFacadeError:
    resolved_mode = normalize_auth_session_mode(session_mode)
    if resolved_mode == AUTH_SESSION_MODE_OA and cookie_token and not authorization:
        client = required_oa_session_client(oa_session_client)
        try:
            revocation = client.revoke_session(
                cookie_token,
                request_id=request_id_from_headers(request),
                trace_id=trace_id_from_headers(request),
            )
        except OaUserSessionClientError as exc:
            return browser_error_from_oa_client_error(exc)
        if revocation.get("revoked") is True:
            session = required_oa_browser_session(
                revocation.get("session"),
                error_code="ae.oa_session_revoke_invalid",
            )
            return session
        return BrowserSessionFacadeError(
            status_code=401,
            error_code="ae.oa_session_inactive",
            detail="OA browser session is not active.",
        )

    validation = validate_browser_session_credentials(
        authorization=authorization,
        cookie_token=cookie_token,
        request_id=request_id_from_headers(request),
        trace_id=trace_id_from_headers(request),
        oa_session_client=oa_session_client,
        session_mode=resolved_mode,
    )
    if isinstance(validation, BrowserSessionFacadeError):
        return validation
    return build_browser_session_snapshot(validation, status="REVOKED")


def build_browser_session_snapshot(
    claims: UserClaims,
    *,
    status: str = "ACTIVE",
) -> dict[str, Any]:
    build_browser_user_auth_context(claims)
    return {
        "browser_session_schema_version": OA_BROWSER_SESSION_SCHEMA_VERSION,
        "session_id": stable_session_id(claims),
        "status": status,
        "issuer": claims.issuer,
        "audience": claims.audience,
        "token_use": claims.token_use,
        "tenant_ref": {"type": OA_TENANT_REF_TYPE, "id": claims.tenant_id},
        "subject_ref": {"type": OA_USER_SUBJECT_REF_TYPE, "id": claims.user_id},
        "scopes": list(claims.scopes),
        "roles": list(claims.roles),
        "issued_at": claims.issued_at,
        "expires_at": claims.expires_at,
        "auth_time": claims.issued_at,
        "metadata": safe_session_metadata(),
    }


def active_oa_browser_session_from_cookie(
    session_id: str,
    *,
    request_id: str,
    trace_id: str,
    oa_session_client: OaUserSessionClient | None = None,
    required_scopes: tuple[str, ...] | list[str] = (DEFAULT_USER_SCOPE,),
) -> dict[str, Any]:
    client = required_oa_session_client(oa_session_client)
    try:
        introspection = client.introspect_session(
            session_id,
            request_id=request_id,
            trace_id=trace_id,
        )
    except OaUserSessionClientError as exc:
        raise browser_error_from_oa_client_error(exc) from exc
    if introspection.get("active") is not True:
        reason = introspection.get("inactive_reason") or "unknown"
        raise BrowserSessionFacadeError(
            status_code=401,
            error_code="ae.oa_session_inactive",
            detail=f"OA browser session is inactive: {reason}.",
        )
    session = required_oa_browser_session(
        introspection.get("session"),
        error_code="ae.oa_session_introspection_invalid",
    )
    user_claims_from_oa_browser_session(session, required_scopes=required_scopes)
    return session


def user_claims_from_oa_browser_session(
    session: Mapping[str, Any],
    *,
    required_scopes: tuple[str, ...] | list[str] = (DEFAULT_USER_SCOPE,),
) -> UserClaims:
    tenant_ref = _required_session_ref(
        session.get("tenant_ref"),
        field_name="tenant_ref",
        expected_type=OA_TENANT_REF_TYPE,
    )
    subject_ref = _required_session_ref(
        session.get("subject_ref"),
        field_name="subject_ref",
        expected_type=OA_USER_SUBJECT_REF_TYPE,
    )
    scopes = _session_string_list(session.get("scopes"), field_name="scopes")
    missing_scope = sorted(set(required_scopes) - set(scopes))
    if missing_scope:
        raise BrowserSessionFacadeError(
            status_code=401,
            error_code="TOKEN_SCOPE_MISSING",
            detail=f"Token is missing required scope: {missing_scope[0]}",
        )
    roles = _session_string_list(
        session.get("roles", []),
        field_name="roles",
        allow_empty=True,
    )
    claims = UserClaims(
        issuer=_non_empty_session_text(session.get("issuer"), "issuer"),
        subject=subject_ref["id"],
        audience=_non_empty_session_text(session.get("audience"), "audience"),
        tenant_id=tenant_ref["id"],
        user_id=subject_ref["id"],
        scopes=scopes,
        roles=roles,
        issued_at=_non_empty_session_text(session.get("issued_at"), "issued_at"),
        expires_at=_non_empty_session_text(session.get("expires_at"), "expires_at"),
        token_use=_non_empty_session_text(session.get("token_use"), "token_use"),
    )
    try:
        build_browser_user_auth_context(claims)
    except BrowserAuthError as exc:
        raise BrowserSessionFacadeError(
            status_code=exc.status_code,
            error_code=exc.error_code,
            detail=exc.detail,
            retryable=exc.retryable,
        ) from exc
    return claims


def required_oa_browser_session(
    value: object,
    *,
    error_code: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise BrowserSessionFacadeError(
            status_code=502,
            error_code=error_code,
            detail="OA user-session response did not include a browser session.",
        )
    return dict(value)


def normalize_login_request(payload: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unsupported_or_sensitive_login_fields(payload)
    tenant_id = _text(payload.get("tenant_id")) or DEFAULT_LOGIN_TENANT_ID
    user_id = (
        _text(payload.get("user_id"))
        or _text(payload.get("login_hint"))
        or DEFAULT_LOGIN_USER_ID
    )
    scopes = _string_list(payload.get("scopes"), default=(DEFAULT_USER_SCOPE,))
    roles = _string_list(payload.get("roles"), default=DEFAULT_LOGIN_ROLES)
    ttl_seconds = _ttl_seconds(payload.get("ttl_seconds"))
    return {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "scopes": scopes,
        "roles": roles,
        "ttl_seconds": ttl_seconds,
    }


def normalize_auth_session_mode(value: str | None) -> str:
    mode = (value or AUTH_SESSION_MODE_MOCK).strip().lower()
    if mode not in AUTH_SESSION_MODES:
        raise BrowserSessionFacadeError(
            status_code=500,
            error_code="ae.auth_session_mode_invalid",
            detail=(
                f"{AUTH_SESSION_MODE_ENV} must be one of: "
                f"{', '.join(sorted(AUTH_SESSION_MODES))}."
            ),
        )
    return mode


def stable_session_id(claims: UserClaims) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            "|".join(
                [
                    "nex-platform",
                    "ae-browser-session",
                    claims.tenant_id,
                    claims.user_id,
                    claims.issued_at,
                    claims.expires_at,
                ]
            ),
        )
    )


def required_oa_session_client(
    oa_session_client: OaUserSessionClient | None,
) -> OaUserSessionClient:
    if oa_session_client is None:
        return build_default_oa_user_session_client()
    return oa_session_client


def browser_error_from_oa_client_error(
    exc: OaUserSessionClientError,
) -> BrowserSessionFacadeError:
    return BrowserSessionFacadeError(
        status_code=exc.status_code,
        error_code=exc.error_code,
        detail=exc.detail,
        retryable=exc.retryable,
    )


def safe_session_metadata() -> dict[str, bool]:
    return {
        "raw_token_included": False,
        "service_token_included": False,
        "password_included": False,
        "browser_payload_owner_authoritative": False,
        "claim_owner_authoritative": True,
    }


def auth_session_problem_response(
    request: Request,
    exc: BrowserSessionFacadeError,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Browser session failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/browser-session-failed",
    )


async def _optional_json_object(request: Request) -> dict[str, Any]:
    body = await request.body()
    if not body:
        return {}
    try:
        payload = await request.json()
    except ValueError as exc:
        raise BrowserSessionFacadeError(
            status_code=400,
            error_code="ae.auth_session_login_json_invalid",
            detail="Login request JSON is invalid.",
        ) from exc
    if not isinstance(payload, dict):
        raise BrowserSessionFacadeError(
            status_code=400,
            error_code="ae.auth_session_login_object_invalid",
            detail="Login request must be a JSON object.",
        )
    return payload


def _required_session_ref(
    value: object,
    *,
    field_name: str,
    expected_type: str,
) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise BrowserSessionFacadeError(
            status_code=502,
            error_code="ae.oa_session_ref_invalid",
            detail=f"{field_name} must be an object.",
        )
    ref_type = _non_empty_session_text(value.get("type"), f"{field_name}.type")
    if ref_type != expected_type:
        raise BrowserSessionFacadeError(
            status_code=502,
            error_code="ae.oa_session_ref_invalid",
            detail=f"{field_name}.type must be {expected_type}.",
        )
    return {
        "type": ref_type,
        "id": _non_empty_session_text(value.get("id"), f"{field_name}.id"),
    }


def _session_string_list(
    value: object,
    *,
    field_name: str,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise BrowserSessionFacadeError(
            status_code=502,
            error_code="ae.oa_session_list_invalid",
            detail=f"{field_name} must be a list of strings.",
        )
    normalized = tuple(
        item.strip() for item in value if isinstance(item, str) and item.strip()
    )
    if len(normalized) != len(value) or (not normalized and not allow_empty):
        raise BrowserSessionFacadeError(
            status_code=502,
            error_code="ae.oa_session_list_invalid",
            detail=f"{field_name} must be a list of strings.",
        )
    return normalized


def _non_empty_session_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BrowserSessionFacadeError(
            status_code=502,
            error_code="ae.oa_session_field_invalid",
            detail=f"{field_name} must be a non-empty string.",
        )
    return value.strip()


def _reject_unsupported_or_sensitive_login_fields(payload: Mapping[str, Any]) -> None:
    for key, value in payload.items():
        normalized_key = key.lower()
        if any(part in normalized_key for part in SENSITIVE_LOGIN_KEY_PARTS):
            raise BrowserSessionFacadeError(
                status_code=400,
                error_code="ae.auth_session_login_sensitive_field",
                detail="Login request must not include credential material.",
            )
        if key not in LOGIN_FIELDS:
            raise BrowserSessionFacadeError(
                status_code=400,
                error_code="ae.auth_session_login_field_unsupported",
                detail="Login request contains an unsupported field.",
            )
        if isinstance(value, Mapping):
            _reject_unsupported_or_sensitive_login_fields(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, Mapping):
                    _reject_unsupported_or_sensitive_login_fields(item)


def _text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if value is None:
        return None
    raise BrowserSessionFacadeError(
        status_code=400,
        error_code="ae.auth_session_login_text_invalid",
        detail="Login text fields must be non-empty strings.",
    )


def _string_list(
    value: Any,
    *,
    default: tuple[str, ...],
) -> tuple[str, ...]:
    if value is None:
        return default
    if not isinstance(value, list) or not value:
        raise BrowserSessionFacadeError(
            status_code=400,
            error_code="ae.auth_session_login_list_invalid",
            detail="Login list fields must be non-empty string lists.",
        )
    normalized = tuple(item.strip() for item in value if isinstance(item, str) and item.strip())
    if len(normalized) != len(value):
        raise BrowserSessionFacadeError(
            status_code=400,
            error_code="ae.auth_session_login_list_invalid",
            detail="Login list fields must be non-empty string lists.",
        )
    return normalized


def _ttl_seconds(value: Any) -> int:
    if value is None:
        return DEFAULT_LOGIN_TTL_SECONDS
    if not isinstance(value, int) or isinstance(value, bool):
        raise BrowserSessionFacadeError(
            status_code=400,
            error_code="ae.auth_session_login_ttl_invalid",
            detail="Login ttl_seconds must be an integer.",
        )
    if value <= 0 or value > MAX_LOGIN_TTL_SECONDS:
        raise BrowserSessionFacadeError(
            status_code=400,
            error_code="ae.auth_session_login_ttl_invalid",
            detail="Login ttl_seconds is outside the allowed range.",
        )
    return value
