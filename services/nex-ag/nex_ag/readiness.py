from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    SERVICE_SPECS,
    issue_mock_service_token,
    problem_response,
    trace_id_from_headers,
    validate_authorization_header,
)


class ServiceStatusClient(Protocol):
    def fetch_status(self, service_id: str, base_url: str) -> dict[str, Any]:
        ...


class ProviderTelemetryClient(Protocol):
    def fetch_provider_telemetry(self, mo_base_url: str) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class HttpServiceStatusClient:
    timeout_seconds: float = 2.0

    def fetch_status(self, service_id: str, base_url: str) -> dict[str, Any]:
        try:
            health_status_code, health = self._get_json(f"{base_url}/health")
            ready_status_code, ready = self._get_json(f"{base_url}/ready")
            version_status_code, version = self._get_json(f"{base_url}/version")
        except (httpx.HTTPError, ValueError) as exc:
            return service_unavailable_projection(service_id, base_url, str(exc))

        failures = []
        for endpoint, status_code in {
            "health": health_status_code,
            "ready": ready_status_code,
            "version": version_status_code,
        }.items():
            if status_code >= 400 and not (endpoint == "ready" and status_code == 503):
                failures.append(
                    {
                        "endpoint": endpoint,
                        "error_code": "SERVICE_ENDPOINT_FAILED",
                        "status_code": status_code,
                    }
                )

        return normalize_service_projection(
            service_id=service_id,
            base_url=base_url,
            health=health,
            ready=ready,
            version=version,
            failures=failures,
        )

    def _get_json(self, url: str) -> tuple[int, dict[str, Any]]:
        response = httpx.get(url, timeout=self.timeout_seconds)
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError(f"{url} did not return a JSON object")
        return response.status_code, payload


@dataclass(frozen=True)
class HttpProviderTelemetryClient:
    timeout_seconds: float = 2.0
    service_token: str | None = None

    def fetch_provider_telemetry(self, mo_base_url: str) -> dict[str, Any]:
        try:
            status_code, payload = self._get_json(
                f"{mo_base_url.rstrip('/')}/api/v1/provider-telemetry"
            )
        except (httpx.HTTPError, ValueError) as exc:
            return provider_telemetry_unavailable_projection(mo_base_url, str(exc))

        if status_code >= 400:
            return provider_telemetry_unavailable_projection(
                mo_base_url,
                f"MO provider telemetry endpoint returned HTTP {status_code}.",
            )
        return normalize_provider_telemetry_projection(
            mo_base_url=mo_base_url,
            telemetry=payload,
        )

    def _get_json(self, url: str) -> tuple[int, dict[str, Any]]:
        token = self.service_token or issue_mock_service_token(
            service_id="nex-ag",
            audience="nex-mo",
        ).access_token
        response = httpx.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=self.timeout_seconds,
        )
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError(f"{url} did not return a JSON object")
        return response.status_code, payload


def register_readiness_routes(
    app: FastAPI,
    *,
    status_client: ServiceStatusClient | None = None,
    provider_client: ProviderTelemetryClient | None = None,
    service_endpoints: dict[str, str] | None = None,
) -> None:
    client = status_client or HttpServiceStatusClient()
    mo_provider_client = provider_client or HttpProviderTelemetryClient()
    endpoints = service_endpoints or build_service_endpoints()

    @app.get("/admin/v1/readiness/services", response_model=None)
    def get_service_readiness(
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        projection = build_readiness_projection(
            client,
            endpoints,
            trace_id=trace_id_from_headers(request),
        )
        return projection

    @app.get("/admin/v1/readiness/providers", response_model=None)
    def get_provider_readiness(
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        projection = build_provider_readiness_projection(
            mo_provider_client,
            mo_base_url=endpoints.get("nex-mo", build_service_endpoints()["nex-mo"]),
            trace_id=trace_id_from_headers(request),
        )
        return projection


def build_service_endpoints() -> dict[str, str]:
    return {
        service_id: os.getenv(
            f"{spec.package_name.upper()}_BASE_URL",
            f"http://127.0.0.1:{spec.default_port}",
        )
        for service_id, spec in SERVICE_SPECS.items()
    }


def build_readiness_projection(
    client: ServiceStatusClient,
    service_endpoints: dict[str, str],
    trace_id: str | None = None,
) -> dict[str, Any]:
    services = [
        client.fetch_status(service_id, base_url)
        for service_id, base_url in sorted(service_endpoints.items())
    ]
    projection = {
        "projection_schema_version": "ag_readiness_projection.v1",
        "checked_at": _utc_now(),
        "services": services,
        "summary": summarize_services(services),
    }
    if trace_id is not None:
        projection["trace_id"] = trace_id
    return projection


def build_provider_readiness_projection(
    client: ProviderTelemetryClient,
    *,
    mo_base_url: str,
    trace_id: str | None = None,
) -> dict[str, Any]:
    projection = client.fetch_provider_telemetry(mo_base_url)
    if trace_id is not None:
        projection["trace_id"] = trace_id
    return projection


def normalize_service_projection(
    *,
    service_id: str,
    base_url: str,
    health: dict[str, Any],
    ready: dict[str, Any],
    version: dict[str, Any],
    failures: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    health_status = health.get("health_status", "UNKNOWN")
    readiness_status = ready.get("readiness_status", "UNKNOWN")
    observed_status = "READY"
    if failures:
        observed_status = "DEGRADED"
    if health_status != "HEALTHY" or readiness_status != "READY":
        observed_status = "NOT_READY"

    return {
        "service_id": service_id,
        "base_url": base_url,
        "health_status": health_status,
        "readiness_status": readiness_status,
        "version": version.get("version", "unknown"),
        "contract_catalog_version": version.get("contract_catalog_version", "unknown"),
        "observed_status": observed_status,
        "failures": failures or [],
    }


def normalize_provider_telemetry_projection(
    *,
    mo_base_url: str,
    telemetry: dict[str, Any],
) -> dict[str, Any]:
    raw_items = telemetry.get("data")
    meta = telemetry.get("meta")
    if not isinstance(raw_items, list):
        return provider_telemetry_unavailable_projection(
            mo_base_url,
            "MO provider telemetry payload did not include a data list.",
        )
    provider_mode = _string_value(meta, "provider_mode", "unknown") if isinstance(meta, dict) else "unknown"

    providers: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for index, item in enumerate(raw_items):
        if not isinstance(item, dict):
            failures.append(
                {
                    "source": "mo_provider_telemetry",
                    "error_code": "PROVIDER_TELEMETRY_ITEM_INVALID",
                    "index": index,
                }
            )
            continue
        providers.append(normalize_provider_telemetry_item(item))

    summary = summarize_provider_telemetry(providers)
    return {
        "projection_schema_version": "ag_mo_provider_readiness_projection.v1",
        "checked_at": _utc_now(),
        "service_id": "nex-mo",
        "mo_base_url": mo_base_url,
        "provider_mode": provider_mode,
        "observed_status": provider_readiness_status(
            provider_mode=provider_mode,
            providers=providers,
            failures=failures,
        ),
        "providers": providers,
        "summary": summary,
        "failures": failures,
    }


def normalize_provider_telemetry_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "capability": _string_value(item, "capability", "unknown"),
        "endpoint_env": _string_value(item, "endpoint_env", "unknown"),
        "configured": _bool_value(item, "configured"),
        "request_shape": _string_value(item, "request_shape", "unknown"),
        "model_name": _string_value(item, "model_name", "unknown"),
        "model_revision": _string_value(item, "model_revision", "unknown"),
        "deployment_id": _string_value(item, "deployment_id", "unknown"),
        "request_count": _int_value(item, "request_count"),
        "success_count": _int_value(item, "success_count"),
        "failure_count": _int_value(item, "failure_count"),
        "retryable_failure_count": _int_value(item, "retryable_failure_count"),
        "degraded_count": _int_value(item, "degraded_count"),
        "last_outcome": _optional_string_value(item, "last_outcome"),
        "last_observed_at": _optional_string_value(item, "last_observed_at"),
        "last_latency_ms": _optional_int_value(item, "last_latency_ms"),
        "last_status_code": _optional_int_value(item, "last_status_code"),
        "last_error_code": _optional_string_value(item, "last_error_code"),
        "last_failure_kind": _optional_string_value(item, "last_failure_kind"),
        "last_upstream_status_code": _optional_int_value(
            item,
            "last_upstream_status_code",
        ),
    }


def summarize_provider_telemetry(providers: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(providers),
        "configured": sum(1 for provider in providers if provider["configured"]),
        "unconfigured": sum(1 for provider in providers if not provider["configured"]),
        "requests": sum(provider["request_count"] for provider in providers),
        "successes": sum(provider["success_count"] for provider in providers),
        "failures": sum(provider["failure_count"] for provider in providers),
        "retryable_failures": sum(
            provider["retryable_failure_count"] for provider in providers
        ),
        "degraded": sum(provider["degraded_count"] for provider in providers),
    }


def provider_readiness_status(
    *,
    provider_mode: str,
    providers: list[dict[str, Any]],
    failures: list[dict[str, Any]],
) -> str:
    if failures or any(provider["degraded_count"] > 0 for provider in providers):
        return "DEGRADED"
    if not providers:
        return "NOT_READY"
    if provider_mode == "live" and any(
        not provider["configured"] for provider in providers
    ):
        return "NOT_READY"
    if any(provider["failure_count"] > 0 for provider in providers):
        return "DEGRADED"
    return "READY"


def provider_telemetry_unavailable_projection(
    mo_base_url: str,
    detail: str,
) -> dict[str, Any]:
    return {
        "projection_schema_version": "ag_mo_provider_readiness_projection.v1",
        "checked_at": _utc_now(),
        "service_id": "nex-mo",
        "mo_base_url": mo_base_url,
        "provider_mode": "unknown",
        "observed_status": "UNAVAILABLE",
        "providers": [],
        "summary": {
            "total": 0,
            "configured": 0,
            "unconfigured": 0,
            "requests": 0,
            "successes": 0,
            "failures": 0,
            "retryable_failures": 0,
            "degraded": 0,
        },
        "failures": [
            {
                "source": "mo_provider_telemetry",
                "error_code": "MO_PROVIDER_TELEMETRY_UNAVAILABLE",
                "detail": detail,
            }
        ],
    }


def service_unavailable_projection(
    service_id: str,
    base_url: str,
    detail: str,
) -> dict[str, Any]:
    return {
        "service_id": service_id,
        "base_url": base_url,
        "health_status": "UNKNOWN",
        "readiness_status": "UNKNOWN",
        "version": "unknown",
        "contract_catalog_version": "unknown",
        "observed_status": "UNAVAILABLE",
        "failures": [
            {
                "endpoint": "service",
                "error_code": "SERVICE_STATUS_UNAVAILABLE",
                "detail": detail,
            }
        ],
    }


def summarize_services(services: list[dict[str, Any]]) -> dict[str, int]:
    statuses = [service["observed_status"] for service in services]
    return {
        "total": len(services),
        "ready": statuses.count("READY"),
        "not_ready": statuses.count("NOT_READY"),
        "degraded": statuses.count("DEGRADED"),
        "unavailable": statuses.count("UNAVAILABLE"),
    }


def _string_value(payload: dict[str, Any], key: str, default: str) -> str:
    value = payload.get(key)
    if isinstance(value, str) and value:
        return value
    return default


def _optional_string_value(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def _bool_value(payload: dict[str, Any], key: str) -> bool:
    value = payload.get(key)
    return value if isinstance(value, bool) else False


def _int_value(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return 0


def _optional_int_value(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _authorize_ag_request(
    request: Request,
    authorization: str | None,
) -> JSONResponse | None:
    result = validate_authorization_header(
        authorization,
        expected_audience="nex-ag",
        required_scopes=[DEFAULT_SERVICE_SCOPE],
    )
    if result.ok:
        return None

    return problem_response(
        request,
        status_code=401,
        error_code=result.error_code or "SERVICE_CLAIM_INVALID",
        title="Authentication failed",
        detail=result.detail or "AG requires a valid service claim.",
        type_uri="https://nex-platform.local/problems/authentication-failed",
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
