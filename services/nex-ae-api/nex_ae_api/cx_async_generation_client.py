from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol
from urllib.parse import quote

import httpx

from nex_ae_api.cx_owner_context import cx_owner_headers, cx_owner_scope_from_payload
from nex_ae_api.service_auth import resolve_ae_outbound_service_token


class CxAsyncGenerationClient(Protocol):
    def admit_generation(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]: ...

    def get_job(
        self,
        job_id: str,
        *,
        tenant_id: str,
        subject_id: str,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]: ...

    def get_handoff(
        self,
        job_id: str,
        *,
        tenant_id: str,
        subject_id: str,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]: ...

    def cancel_job(
        self,
        job_id: str,
        *,
        tenant_id: str,
        subject_id: str,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class CxAsyncGenerationClientError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class HttpCxAsyncGenerationClient:
    base_url: str = "http://127.0.0.1:8104"
    service_token: str | None = None
    timeout_seconds: float = 10.0

    def admit_generation(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        tenant_id, subject_id = cx_owner_scope_from_payload(payload)
        headers = self._headers(
            tenant_id=tenant_id,
            subject_id=subject_id,
            request_id=request_id,
            trace_id=trace_id,
        )
        headers["Idempotency-Key"] = _required_text(
            idempotency_key, "idempotency_key"
        )
        return self._request(
            "POST",
            "/api/v1/generation-jobs",
            headers=headers,
            payload=payload,
        )

    def get_job(
        self,
        job_id: str,
        *,
        tenant_id: str,
        subject_id: str,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        return self._owner_job_request(
            "GET",
            job_id,
            suffix="",
            tenant_id=tenant_id,
            subject_id=subject_id,
            request_id=request_id,
            trace_id=trace_id,
        )

    def get_handoff(
        self,
        job_id: str,
        *,
        tenant_id: str,
        subject_id: str,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        return self._owner_job_request(
            "GET",
            job_id,
            suffix="/handoff",
            tenant_id=tenant_id,
            subject_id=subject_id,
            request_id=request_id,
            trace_id=trace_id,
        )

    def cancel_job(
        self,
        job_id: str,
        *,
        tenant_id: str,
        subject_id: str,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        return self._owner_job_request(
            "POST",
            job_id,
            suffix="/cancel",
            tenant_id=tenant_id,
            subject_id=subject_id,
            request_id=request_id,
            trace_id=trace_id,
        )

    def _owner_job_request(
        self,
        method: str,
        job_id: str,
        *,
        suffix: str,
        tenant_id: str,
        subject_id: str,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        normalized_job_id = _required_text(job_id, "job_id")
        return self._request(
            method,
            f"/api/v1/generation-jobs/{quote(normalized_job_id, safe='')}{suffix}",
            headers=self._headers(
                tenant_id=tenant_id,
                subject_id=subject_id,
                request_id=request_id,
                trace_id=trace_id,
            ),
        )

    def _headers(
        self,
        *,
        tenant_id: str,
        subject_id: str,
        request_id: str,
        trace_id: str,
    ) -> dict[str, str]:
        token = resolve_ae_outbound_service_token(
            self.service_token, audience="nex-cx"
        )
        return {
            "Authorization": f"Bearer {token}",
            "X-Request-ID": _required_text(request_id, "request_id"),
            "traceparent": (
                f"00-{_required_text(trace_id, 'trace_id')}-00f067aa0ba902b7-01"
            ),
            "X-Service-ID": "nex-ae-api",
            **cx_owner_headers(tenant_id, subject_id),
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = httpx.request(
                method,
                f"{self.base_url.rstrip('/')}{path}",
                headers=dict(headers),
                json=dict(payload) if payload is not None else None,
                timeout=self.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise CxAsyncGenerationClientError(
                status_code=504,
                error_code="ae.cx_async_generation.timeout",
                detail="CX asynchronous generation request timed out.",
                retryable=True,
            ) from exc
        except httpx.RequestError as exc:
            raise CxAsyncGenerationClientError(
                status_code=503,
                error_code="ae.cx_async_generation.unavailable",
                detail="CX asynchronous generation service is unavailable.",
                retryable=True,
            ) from exc
        body = _safe_response_json(response)
        if response.status_code >= 400:
            raise CxAsyncGenerationClientError(
                status_code=response.status_code,
                error_code=_optional_text(body.get("error_code"))
                or "cx.async_generation.request_failed",
                detail=_optional_text(body.get("detail"))
                or "CX asynchronous generation request failed.",
                retryable=body.get("retryable") is True,
            )
        if not isinstance(body, dict):
            raise CxAsyncGenerationClientError(
                status_code=502,
                error_code="ae.cx_async_generation.response_invalid",
                detail="CX asynchronous generation response is invalid.",
                retryable=True,
            )
        return body


def _safe_response_json(response: httpx.Response) -> object:
    try:
        return response.json()
    except (ValueError, TypeError):
        return {}


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CxAsyncGenerationClientError(
            status_code=400,
            error_code="ae.cx_async_generation.request_invalid",
            detail=f"{field_name} must be a non-empty string.",
        )
    return value.strip()


def _optional_text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
