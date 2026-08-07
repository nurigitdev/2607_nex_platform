from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from nex_runtime import SERVICE_SPECS, issue_mock_service_token


AG_JOB_CONTROL_CLIENT_SCHEMA_VERSION = "ag_job_control_client.v1"
AG_JOB_CONTROL_TIMEOUT_ENV = "NEX_AG_JOB_CONTROL_TIMEOUT_SECONDS"


class AgJobControlClient(Protocol):
    def get_job(
        self,
        service_id: str,
        job_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        ...

    def cancel_job(
        self,
        service_id: str,
        job_id: str,
        *,
        request_id: str,
        trace_id: str,
        observed_at: str | None = None,
    ) -> dict[str, Any]:
        ...

    def retry_job(
        self,
        service_id: str,
        job_id: str,
        *,
        request_id: str,
        trace_id: str,
        error_code: str | None = None,
        detail: str | None = None,
        observed_at: str | None = None,
    ) -> dict[str, Any]:
        ...

    def replay_job(
        self,
        service_id: str,
        job_id: str,
        *,
        request_id: str,
        trace_id: str,
        replay_job_id: str,
        idempotency_key: str,
        requested_by: str,
        reason: str,
        observed_at: str | None = None,
    ) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class AgJobControlError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class HttpAgJobControlClient:
    service_base_urls: Mapping[str, str]
    service_tokens: Mapping[str, str] = field(default_factory=dict)
    timeout_seconds: float = 5.0

    def get_job(
        self,
        service_id: str,
        job_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            service_id,
            f"/internal/v1/jobs/{_quote_path_value(job_id)}",
            request_id=request_id,
            trace_id=trace_id,
        )

    def cancel_job(
        self,
        service_id: str,
        job_id: str,
        *,
        request_id: str,
        trace_id: str,
        observed_at: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            service_id,
            f"/internal/v1/jobs/{_quote_path_value(job_id)}/cancel",
            request_id=request_id,
            trace_id=trace_id,
            json=_compact_payload({"observed_at": observed_at}),
        )

    def retry_job(
        self,
        service_id: str,
        job_id: str,
        *,
        request_id: str,
        trace_id: str,
        error_code: str | None = None,
        detail: str | None = None,
        observed_at: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            service_id,
            f"/internal/v1/jobs/{_quote_path_value(job_id)}/retry",
            request_id=request_id,
            trace_id=trace_id,
            json=_compact_payload(
                {
                    "error_code": error_code,
                    "detail": detail,
                    "observed_at": observed_at,
                }
            ),
        )

    def replay_job(
        self,
        service_id: str,
        job_id: str,
        *,
        request_id: str,
        trace_id: str,
        replay_job_id: str,
        idempotency_key: str,
        requested_by: str,
        reason: str,
        observed_at: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            service_id,
            f"/internal/v1/jobs/{_quote_path_value(job_id)}/replay",
            request_id=request_id,
            trace_id=trace_id,
            json=_compact_payload(
                {
                    "replay_job_id": replay_job_id,
                    "idempotency_key": idempotency_key,
                    "requested_by": requested_by,
                    "reason": reason,
                    "observed_at": observed_at,
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
            raise AgJobControlError(
                status_code=503,
                error_code="ag.job_control_request_unavailable",
                detail=str(exc),
                retryable=True,
            ) from exc

        body = _safe_response_json(response)
        if response.status_code >= 400:
            raise AgJobControlError(
                status_code=response.status_code,
                error_code=str(body.get("error_code", "ag.job_control_request_failed")),
                detail=str(body.get("detail", "Job control request failed.")),
                retryable=bool(body.get("retryable", False)),
            )
        return body

    def _base_url_for_service(self, service_id: str) -> str:
        if service_id not in SERVICE_SPECS:
            raise AgJobControlError(
                status_code=400,
                error_code="ag.job_control_service_invalid",
                detail=f"Unsupported job control service: {service_id}",
                retryable=False,
            )
        base_url = self.service_base_urls.get(service_id, "").strip()
        if not base_url:
            raise AgJobControlError(
                status_code=404,
                error_code="ag.job_control_service_not_configured",
                detail=f"AG has no job control endpoint configured for service: {service_id}",
                retryable=False,
            )
        return base_url.rstrip("/")


def build_default_ag_job_control_client(
    environ: Mapping[str, str] | None = None,
) -> HttpAgJobControlClient:
    env = environ or os.environ
    return HttpAgJobControlClient(
        service_base_urls=build_ag_job_control_base_urls(env),
        service_tokens=build_ag_job_control_service_tokens(env),
        timeout_seconds=_float_env(
            env,
            AG_JOB_CONTROL_TIMEOUT_ENV,
            default=5.0,
        ),
    )


def build_ag_job_control_base_urls(env: Mapping[str, str]) -> dict[str, str]:
    return {
        service_id: env.get(
            ag_job_control_base_url_env(service_id),
            f"http://127.0.0.1:{spec.default_port}",
        ).rstrip("/")
        for service_id, spec in SERVICE_SPECS.items()
    }


def build_ag_job_control_service_tokens(env: Mapping[str, str]) -> dict[str, str]:
    return {
        service_id: token
        for service_id in sorted(SERVICE_SPECS)
        if (token := env.get(ag_job_control_token_env(service_id), ""))
    }


def ag_job_control_base_url_env(service_id: str) -> str:
    spec = _service_spec_or_raise(service_id)
    return f"{spec.package_name.upper()}_BASE_URL"


def ag_job_control_token_env(service_id: str) -> str:
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
        raise AgJobControlError(
            status_code=400,
            error_code="ag.job_control_service_invalid",
            detail=f"Unsupported job control service: {service_id}",
            retryable=False,
        ) from exc


def _safe_response_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise AgJobControlError(
            status_code=response.status_code,
            error_code="ag.job_control_response_invalid",
            detail="Job control endpoint did not return valid JSON.",
            retryable=response.status_code >= 500,
        ) from exc
    if not isinstance(payload, dict):
        raise AgJobControlError(
            status_code=response.status_code,
            error_code="ag.job_control_response_invalid",
            detail="Job control endpoint did not return a JSON object.",
            retryable=response.status_code >= 500,
        )
    return payload


def _compact_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    compacted = {key: value for key, value in payload.items() if value is not None}
    return compacted or None


def _quote_path_value(value: str) -> str:
    return quote(value, safe="")


def _float_env(env: Mapping[str, str], key: str, *, default: float) -> float:
    raw_value = env.get(key)
    if raw_value is None or raw_value == "":
        return default
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise AgJobControlError(
            status_code=422,
            error_code="ag.job_control_timeout_invalid",
            detail=f"{key} must be a positive number.",
            retryable=False,
        ) from exc
    if value <= 0:
        raise AgJobControlError(
            status_code=422,
            error_code="ag.job_control_timeout_invalid",
            detail=f"{key} must be a positive number.",
            retryable=False,
        )
    return value
