from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from nex_runtime import issue_mock_service_token


AE_OA_SESSION_CLIENT_SCHEMA_VERSION = "ae_oa_session_client.v1"
OA_SESSION_CLIENT_BASE_URL_ENV = "NEX_OA_BASE_URL"
OA_SESSION_CLIENT_TOKEN_ENV = "NEX_AE_TO_OA_SERVICE_TOKEN"
OA_SESSION_CLIENT_TIMEOUT_ENV = "NEX_AE_OA_SESSION_TIMEOUT_SECONDS"
DEFAULT_OA_BASE_URL = "http://127.0.0.1:8101"
DEFAULT_OA_SESSION_TIMEOUT_SECONDS = 5.0

HttpRequester = Callable[..., httpx.Response]


class OaUserSessionClient(Protocol):
    def login_with_credentials(
        self,
        login_request: Mapping[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        ...

    def issue_session(
        self,
        login_request: Mapping[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        ...

    def introspect_session(
        self,
        session_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        ...

    def revoke_session(
        self,
        session_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class OaUserSessionClientError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class HttpOaUserSessionClient:
    base_url: str = DEFAULT_OA_BASE_URL
    service_token: str | None = None
    timeout_seconds: float = DEFAULT_OA_SESSION_TIMEOUT_SECONDS
    requester: HttpRequester = httpx.request

    def login_with_credentials(
        self,
        login_request: Mapping[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/internal/v1/auth/user-login",
            request_id=request_id,
            trace_id=trace_id,
            json=oa_user_login_payload(login_request),
            failure_namespace="user_login",
            failure_label="OA user-login",
        )

    def issue_session(
        self,
        login_request: Mapping[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/internal/v1/auth/user-sessions/issue",
            request_id=request_id,
            trace_id=trace_id,
            json=oa_session_issue_payload(login_request),
        )

    def introspect_session(
        self,
        session_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/internal/v1/auth/user-sessions/introspect",
            request_id=request_id,
            trace_id=trace_id,
            json={"session_id": _non_empty_session_id(session_id)},
        )

    def revoke_session(
        self,
        session_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/internal/v1/auth/user-sessions/{_quote_session_id(session_id)}/revoke",
            request_id=request_id,
            trace_id=trace_id,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        request_id: str,
        trace_id: str,
        json: dict[str, Any] | None = None,
        failure_namespace: str = "session",
        failure_label: str = "OA user-session",
    ) -> dict[str, Any]:
        token = self.service_token or issue_mock_service_token(
            service_id="nex-ae-api",
            audience="nex-oa",
        ).access_token
        try:
            response = self.requester(
                method,
                f"{self.base_url.rstrip('/')}{path}",
                json=json,
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Request-ID": request_id,
                    "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
                    "X-Service-ID": "nex-ae-api",
                },
                timeout=self.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise OaUserSessionClientError(
                status_code=504,
                error_code=f"oa.{failure_namespace}_client_timeout",
                detail=f"{failure_label} request timed out.",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise OaUserSessionClientError(
                status_code=503,
                error_code=f"oa.{failure_namespace}_client_unavailable",
                detail=f"{failure_label} endpoint is unavailable.",
                retryable=True,
            ) from exc

        body = _safe_response_json(
            response,
            failure_namespace=failure_namespace,
            failure_label=failure_label,
        )
        if response.status_code >= 400:
            raise OaUserSessionClientError(
                status_code=response.status_code,
                error_code=str(
                    body.get("error_code", f"oa.{failure_namespace}_client_failed")
                ),
                detail=str(body.get("detail", f"{failure_label} request failed.")),
                retryable=bool(body.get("retryable", response.status_code >= 500)),
            )
        return body


def build_default_oa_user_session_client(
    environ: Mapping[str, str] | None = None,
) -> HttpOaUserSessionClient:
    env = environ or os.environ
    return HttpOaUserSessionClient(
        base_url=env.get(OA_SESSION_CLIENT_BASE_URL_ENV, DEFAULT_OA_BASE_URL),
        service_token=env.get(OA_SESSION_CLIENT_TOKEN_ENV),
        timeout_seconds=_positive_float_env(
            env,
            OA_SESSION_CLIENT_TIMEOUT_ENV,
            default=DEFAULT_OA_SESSION_TIMEOUT_SECONDS,
        ),
    )


def oa_session_issue_payload(login_request: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "tenant_id": _non_empty_text(login_request.get("tenant_id"), "tenant_id"),
        "subject_id": _non_empty_text(login_request.get("user_id"), "user_id"),
        "requested_scopes": list(
            _non_empty_string_sequence(
                login_request.get("scopes"),
                field_name="scopes",
            )
        ),
        "ttl_seconds": _positive_int(
            login_request.get("ttl_seconds"),
            field_name="ttl_seconds",
        ),
    }


def oa_user_login_payload(login_request: Mapping[str, Any]) -> dict[str, Any]:
    scopes = login_request.get("requested_scopes")
    if scopes is None:
        scopes = login_request.get("scopes")
    employee_id = login_request.get("employee_id")
    if employee_id is None:
        employee_id = login_request.get("login_identifier")
    payload: dict[str, Any] = {
        "tenant_id": _non_empty_text(login_request.get("tenant_id"), "tenant_id"),
        "employee_id": _non_empty_text(employee_id, "employee_id"),
        "password": _non_empty_text(login_request.get("password"), "password"),
    }
    if scopes is not None:
        payload["requested_scopes"] = list(
            _non_empty_string_sequence(scopes, field_name="requested_scopes")
        )
    if "ttl_seconds" in login_request:
        payload["ttl_seconds"] = _positive_int(
            login_request.get("ttl_seconds"),
            field_name="ttl_seconds",
        )
    return payload


def _safe_response_json(
    response: httpx.Response,
    *,
    failure_namespace: str = "session",
    failure_label: str = "OA user-session",
) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise OaUserSessionClientError(
            status_code=response.status_code,
            error_code=f"oa.{failure_namespace}_client_response_invalid",
            detail=f"{failure_label} endpoint did not return valid JSON.",
            retryable=response.status_code >= 500,
        ) from exc
    if not isinstance(payload, dict):
        raise OaUserSessionClientError(
            status_code=response.status_code,
            error_code=f"oa.{failure_namespace}_client_response_invalid",
            detail=f"{failure_label} endpoint did not return a JSON object.",
            retryable=response.status_code >= 500,
        )
    return payload


def _positive_float_env(
    env: Mapping[str, str],
    key: str,
    *,
    default: float,
) -> float:
    raw_value = env.get(key)
    if raw_value is None or raw_value == "":
        return default
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise OaUserSessionClientError(
            status_code=422,
            error_code="oa.session_client_timeout_invalid",
            detail=f"{key} must be a positive number.",
        ) from exc
    if value <= 0:
        raise OaUserSessionClientError(
            status_code=422,
            error_code="oa.session_client_timeout_invalid",
            detail=f"{key} must be a positive number.",
        )
    return value


def _non_empty_session_id(value: object) -> str:
    return _non_empty_text(value, "session_id")


def _quote_session_id(value: object) -> str:
    return quote(_non_empty_session_id(value), safe="")


def _non_empty_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OaUserSessionClientError(
            status_code=422,
            error_code="oa.session_client_request_invalid",
            detail=f"{field_name} must be a non-empty string.",
        )
    return value.strip()


def _non_empty_string_sequence(value: object, *, field_name: str) -> tuple[str, ...]:
    if (
        not isinstance(value, (list, tuple))
        or not value
        or not all(isinstance(item, str) and item.strip() for item in value)
    ):
        raise OaUserSessionClientError(
            status_code=422,
            error_code="oa.session_client_request_invalid",
            detail=f"{field_name} must be a non-empty string list.",
        )
    return tuple(item.strip() for item in value)


def _positive_int(value: object, *, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise OaUserSessionClientError(
            status_code=422,
            error_code="oa.session_client_request_invalid",
            detail=f"{field_name} must be a positive integer.",
        )
    return value
