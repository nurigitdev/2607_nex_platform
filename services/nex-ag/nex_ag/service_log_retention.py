from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from nex_runtime import SERVICE_SPECS, issue_mock_service_token


AG_SERVICE_LOG_RETENTION_CLIENT_SCHEMA_VERSION = "ag_service_log_retention_client.v1"
AG_SERVICE_LOG_RETENTION_TIMEOUT_ENV = (
    "NEX_AG_SERVICE_LOG_RETENTION_TIMEOUT_SECONDS"
)


class AgServiceLogRetentionClient(Protocol):
    def purge_logs(
        self,
        service_id: str,
        *,
        request_id: str,
        trace_id: str,
        retention_cutoff: str,
        retention_days: int | None = None,
        checked_at: str | None = None,
        dry_run: bool = True,
        delete_enabled: bool = False,
        max_delete_count: int | None = None,
        requested_by: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class AgServiceLogRetentionError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class HttpAgServiceLogRetentionClient:
    service_base_urls: Mapping[str, str]
    service_tokens: Mapping[str, str] = field(default_factory=dict)
    timeout_seconds: float = 5.0

    def purge_logs(
        self,
        service_id: str,
        *,
        request_id: str,
        trace_id: str,
        retention_cutoff: str,
        retention_days: int | None = None,
        checked_at: str | None = None,
        dry_run: bool = True,
        delete_enabled: bool = False,
        max_delete_count: int | None = None,
        requested_by: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            service_id,
            "/internal/v1/service-logs/retention/purge",
            request_id=request_id,
            trace_id=trace_id,
            json=_compact_payload(
                {
                    "retention_cutoff": retention_cutoff,
                    "retention_days": retention_days,
                    "checked_at": checked_at,
                    "dry_run": dry_run,
                    "delete_enabled": delete_enabled,
                    "max_delete_count": max_delete_count,
                    "requested_by": requested_by,
                    "idempotency_key": idempotency_key,
                }
            ),
        )

    def _request(
        self,
        method: str,
        service_id: str,
        path: str,
        *,
        request_id: str,
        trace_id: str,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        base_url = self._base_url_for_service(service_id)
        token = self.service_tokens.get(service_id) or issue_mock_service_token(
            service_id="nex-ag",
            audience=service_id,
        ).access_token
        try:
            response = httpx.request(
                method,
                f"{base_url}{path}",
                json=json,
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Request-ID": request_id,
                    "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
                    "X-Service-ID": "nex-ag",
                },
                timeout=self.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise AgServiceLogRetentionError(
                status_code=503,
                error_code="ag.service_log_retention_request_unavailable",
                detail=str(exc),
                retryable=True,
            ) from exc

        body = _safe_response_json(response)
        if response.status_code >= 400:
            raise AgServiceLogRetentionError(
                status_code=response.status_code,
                error_code=str(
                    body.get(
                        "error_code",
                        "ag.service_log_retention_request_failed",
                    )
                ),
                detail=str(
                    body.get("detail", "Service log retention request failed.")
                ),
                retryable=bool(body.get("retryable", False)),
            )
        return body

    def _base_url_for_service(self, service_id: str) -> str:
        if service_id not in SERVICE_SPECS:
            raise AgServiceLogRetentionError(
                status_code=400,
                error_code="ag.service_log_retention_service_invalid",
                detail=f"Unsupported service log retention service: {service_id}",
                retryable=False,
            )
        base_url = self.service_base_urls.get(service_id, "").strip()
        if not base_url:
            raise AgServiceLogRetentionError(
                status_code=404,
                error_code="ag.service_log_retention_service_not_configured",
                detail=(
                    "AG has no service log retention endpoint configured for "
                    f"service: {service_id}"
                ),
                retryable=False,
            )
        return base_url.rstrip("/")


def build_default_ag_service_log_retention_client(
    environ: Mapping[str, str] | None = None,
) -> HttpAgServiceLogRetentionClient:
    env = environ or os.environ
    return HttpAgServiceLogRetentionClient(
        service_base_urls=build_ag_service_log_retention_base_urls(env),
        service_tokens=build_ag_service_log_retention_service_tokens(env),
        timeout_seconds=_float_env(
            env,
            AG_SERVICE_LOG_RETENTION_TIMEOUT_ENV,
            default=5.0,
        ),
    )


def build_ag_service_log_retention_base_urls(
    env: Mapping[str, str],
) -> dict[str, str]:
    return {
        service_id: env.get(
            ag_service_log_retention_base_url_env(service_id),
            f"http://127.0.0.1:{spec.default_port}",
        ).rstrip("/")
        for service_id, spec in SERVICE_SPECS.items()
    }


def build_ag_service_log_retention_service_tokens(
    env: Mapping[str, str],
) -> dict[str, str]:
    return {
        service_id: token
        for service_id in sorted(SERVICE_SPECS)
        if (token := env.get(ag_service_log_retention_token_env(service_id), ""))
    }


def ag_service_log_retention_base_url_env(service_id: str) -> str:
    spec = _service_spec_or_raise(service_id)
    return f"{spec.package_name.upper()}_BASE_URL"


def ag_service_log_retention_token_env(service_id: str) -> str:
    _service_spec_or_raise(service_id)
    suffix_by_service = {
        "nex-oa": "OA",
        "nex-ag": "AG",
        "nex-ae-api": "AE",
        "nex-cx": "CX",
        "nex-mo": "MO",
    }
    return f"NEX_AG_TO_{suffix_by_service[service_id]}_SERVICE_TOKEN"


def _service_spec_or_raise(service_id: str):
    try:
        return SERVICE_SPECS[service_id]
    except KeyError as exc:
        raise AgServiceLogRetentionError(
            status_code=400,
            error_code="ag.service_log_retention_service_invalid",
            detail=f"Unsupported service log retention service: {service_id}",
            retryable=False,
        ) from exc


def _safe_response_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise AgServiceLogRetentionError(
            status_code=response.status_code,
            error_code="ag.service_log_retention_response_invalid",
            detail="Service log retention endpoint did not return valid JSON.",
            retryable=response.status_code >= 500,
        ) from exc
    if not isinstance(payload, dict):
        raise AgServiceLogRetentionError(
            status_code=response.status_code,
            error_code="ag.service_log_retention_response_invalid",
            detail="Service log retention endpoint did not return a JSON object.",
            retryable=response.status_code >= 500,
        )
    return payload


def _compact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def _float_env(env: Mapping[str, str], key: str, *, default: float) -> float:
    raw_value = env.get(key)
    if raw_value is None or raw_value == "":
        return default
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise AgServiceLogRetentionError(
            status_code=422,
            error_code="ag.service_log_retention_timeout_invalid",
            detail=f"{key} must be a positive number.",
            retryable=False,
        ) from exc
    if value <= 0:
        raise AgServiceLogRetentionError(
            status_code=422,
            error_code="ag.service_log_retention_timeout_invalid",
            detail=f"{key} must be a positive number.",
            retryable=False,
        )
    return value
