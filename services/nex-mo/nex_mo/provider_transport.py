from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol

import httpx

from nex_mo.provider_registry import ProviderRouteError
from nex_mo.provider_retry_after import parse_retry_after_seconds


class RemoteRequestConfigView(Protocol):
    method: str
    url: str
    timeout_seconds: float

    def headers(self) -> dict[str, str]: ...


HttpRequester = Callable[..., httpx.Response]


@dataclass(frozen=True)
class RemoteProviderFailureDecision:
    failure_kind: str
    error_code: str
    status_code: int
    detail: str
    retryable: bool
    degraded: bool
    upstream_status_code: int | None = None
    retry_after_seconds: float | None = None

    def to_route_error(self) -> ProviderRouteError:
        return ProviderRouteError(
            status_code=self.status_code,
            error_code=self.error_code,
            detail=self.detail,
            retryable=self.retryable,
            degraded=self.degraded,
            failure_kind=self.failure_kind,
            upstream_status_code=self.upstream_status_code,
            retry_after_seconds=self.retry_after_seconds,
        )

    def to_safe_summary(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "failure_kind": self.failure_kind,
            "error_code": self.error_code,
            "status_code": self.status_code,
            "retryable": self.retryable,
            "degraded": self.degraded,
        }
        if self.upstream_status_code is not None:
            payload["upstream_status_code"] = self.upstream_status_code
        if self.retry_after_seconds is not None:
            payload["retry_after_seconds"] = self.retry_after_seconds
        return payload


def execute_remote_json_request(
    config: RemoteRequestConfigView,
    *,
    json_payload: dict[str, Any],
    requester: HttpRequester | None,
    error_code_prefix: str,
) -> Any:
    selected_requester = requester or httpx.request
    try:
        response = selected_requester(
            config.method,
            config.url,
            headers=config.headers(),
            json=json_payload,
            timeout=config.timeout_seconds,
        )
    except httpx.TimeoutException as exc:
        raise classify_remote_provider_exception(
            exc,
            error_code_prefix=error_code_prefix,
        ).to_route_error() from exc
    except httpx.HTTPError as exc:
        raise classify_remote_provider_exception(
            exc,
            error_code_prefix=error_code_prefix,
        ).to_route_error() from exc

    if response.is_error:
        raise classify_remote_provider_http_status(
            response.status_code,
            error_code_prefix=error_code_prefix,
            retry_after_seconds=parse_retry_after_seconds(
                response.headers.get("Retry-After")
            ),
        ).to_route_error()
    try:
        return response.json()
    except ValueError as exc:
        raise remote_provider_response_invalid_decision(
            error_code_prefix=error_code_prefix,
            detail="Remote provider response was not valid JSON.",
        ).to_route_error() from exc


def classify_remote_provider_exception(
    exc: httpx.HTTPError,
    *,
    error_code_prefix: str,
) -> RemoteProviderFailureDecision:
    if isinstance(exc, httpx.ConnectTimeout):
        return _timeout_failure(
            "connect_timeout",
            "Remote provider connection timed out.",
            error_code_prefix=error_code_prefix,
        )
    if isinstance(exc, httpx.ReadTimeout):
        return _timeout_failure(
            "read_timeout",
            "Remote provider response timed out.",
            error_code_prefix=error_code_prefix,
        )
    if isinstance(exc, httpx.WriteTimeout):
        return _timeout_failure(
            "write_timeout",
            "Remote provider request write timed out.",
            error_code_prefix=error_code_prefix,
        )
    if isinstance(exc, httpx.PoolTimeout):
        return _timeout_failure(
            "pool_timeout",
            "Remote provider connection pool timed out.",
            error_code_prefix=error_code_prefix,
        )
    if isinstance(exc, httpx.TimeoutException):
        return _timeout_failure(
            "timeout",
            "Remote provider request timed out.",
            error_code_prefix=error_code_prefix,
        )
    return RemoteProviderFailureDecision(
        failure_kind="connection_error",
        error_code=f"{error_code_prefix}_unavailable",
        status_code=503,
        detail="Remote provider request failed before a valid response was received.",
        retryable=True,
        degraded=True,
    )


def _timeout_failure(
    failure_kind: str,
    detail: str,
    *,
    error_code_prefix: str,
) -> RemoteProviderFailureDecision:
    return RemoteProviderFailureDecision(
        failure_kind=failure_kind,
        error_code=f"{error_code_prefix}_timeout",
        status_code=504,
        detail=detail,
        retryable=True,
        degraded=True,
    )


def classify_remote_provider_http_status(
    status_code: int,
    *,
    error_code_prefix: str,
    retry_after_seconds: float | None = None,
) -> RemoteProviderFailureDecision:
    if status_code == 429:
        return RemoteProviderFailureDecision(
            failure_kind="throttled",
            error_code=f"{error_code_prefix}_throttled",
            status_code=429,
            detail="Remote provider throttled the request.",
            retryable=True,
            degraded=True,
            upstream_status_code=status_code,
            retry_after_seconds=retry_after_seconds,
        )
    if status_code >= 500:
        return RemoteProviderFailureDecision(
            failure_kind="upstream_5xx",
            error_code=f"{error_code_prefix}_http_error",
            status_code=503,
            detail=f"Remote provider returned HTTP {status_code}.",
            retryable=True,
            degraded=True,
            upstream_status_code=status_code,
            retry_after_seconds=retry_after_seconds,
        )
    return RemoteProviderFailureDecision(
        failure_kind="upstream_4xx",
        error_code=f"{error_code_prefix}_http_error",
        status_code=502,
        detail=f"Remote provider returned HTTP {status_code}.",
        retryable=False,
        degraded=False,
        upstream_status_code=status_code,
    )


def remote_provider_response_invalid_decision(
    *,
    error_code_prefix: str,
    detail: str,
) -> RemoteProviderFailureDecision:
    return RemoteProviderFailureDecision(
        failure_kind="malformed_response",
        error_code=f"{error_code_prefix}_response_invalid",
        status_code=502,
        detail=detail,
        retryable=True,
        degraded=True,
    )
