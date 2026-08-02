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
    problem_response,
    trace_id_from_headers,
    validate_authorization_header,
)


class ServiceStatusClient(Protocol):
    def fetch_status(self, service_id: str, base_url: str) -> dict[str, Any]:
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


def register_readiness_routes(
    app: FastAPI,
    *,
    status_client: ServiceStatusClient | None = None,
    service_endpoints: dict[str, str] | None = None,
) -> None:
    client = status_client or HttpServiceStatusClient()
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
