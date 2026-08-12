from __future__ import annotations

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
    validate_mock_user_token,
    validate_user_authorization_header,
)
from nex_ae_api.auth_guard import (
    OA_TENANT_REF_TYPE,
    OA_USER_SUBJECT_REF_TYPE,
    build_browser_user_auth_context,
)


AE_AUTH_SESSION_FACADE_SCHEMA_VERSION = "ae_auth_session_facade.v1"
OA_BROWSER_SESSION_SCHEMA_VERSION = "oa_browser_session.v1"
SESSION_COOKIE_NAME = "nex_ae_user_session"
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


def register_auth_session_routes(app: FastAPI) -> None:
    @app.get("/api/v1/auth/session", response_model=None)
    def get_auth_session(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any] | JSONResponse:
        result = browser_session_from_request(request, authorization)
        if isinstance(result, BrowserSessionFacadeError):
            return auth_session_problem_response(request, result)
        return result

    @app.post("/api/v1/auth/session/login", response_model=None)
    async def login_auth_session(request: Request) -> JSONResponse:
        try:
            payload = await _optional_json_object(request)
            login_request = normalize_login_request(payload)
            issued = issue_mock_user_token(
                tenant_id=login_request["tenant_id"],
                user_id=login_request["user_id"],
                scopes=login_request["scopes"],
                roles=login_request["roles"],
                issued_at=datetime.now(UTC),
                ttl_seconds=login_request["ttl_seconds"],
            )
            session = build_browser_session_snapshot(issued.claims)
            response = JSONResponse(session)
            response.set_cookie(
                SESSION_COOKIE_NAME,
                issued.access_token,
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
        validation = validate_browser_session_credentials(
            authorization=authorization,
            cookie_token=request.cookies.get(SESSION_COOKIE_NAME),
        )
        if isinstance(validation, BrowserSessionFacadeError):
            response = auth_session_problem_response(request, validation)
        else:
            response = JSONResponse(
                build_browser_session_snapshot(validation, status="REVOKED")
            )
        response.delete_cookie(SESSION_COOKIE_NAME, path="/")
        return response


def browser_session_from_request(
    request: Request,
    authorization: str | None,
) -> dict[str, Any] | BrowserSessionFacadeError:
    validation = validate_browser_session_credentials(
        authorization=authorization,
        cookie_token=request.cookies.get(SESSION_COOKIE_NAME),
    )
    if isinstance(validation, BrowserSessionFacadeError):
        return validation
    return build_browser_session_snapshot(validation)


def validate_browser_session_credentials(
    *,
    authorization: str | None,
    cookie_token: str | None,
    required_scopes: tuple[str, ...] | list[str] = (DEFAULT_USER_SCOPE,),
) -> UserClaims | BrowserSessionFacadeError:
    if authorization:
        result = validate_user_authorization_header(
            authorization,
            expected_audience="nex-ae-api",
            required_scopes=required_scopes,
        )
    elif cookie_token:
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
