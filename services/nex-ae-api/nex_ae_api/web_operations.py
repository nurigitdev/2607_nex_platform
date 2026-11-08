from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from nex_runtime import problem_response

from nex_ae_api.route_auth import (
    AeFacadeRouteAuthContext,
    authorize_ae_facade_route_request,
)


AE_WEB_OPERATIONS_SUMMARY_SCHEMA_VERSION = "ae_web_operations_summary.v1"
AE_WEB_OPERATIONS_SUMMARY_PATH = "/api/v1/web/operations/summary"
AE_WEB_OPERATIONS_ROLES = frozenset({"admin", "operator"})
_SERVICE_IDS = (
    "nex-oa",
    "nex-ag",
    "nex-ae-api",
    "nex-cx",
    "nex-mo",
    "nex-wc",
    "nex-eos",
    "nex-wa",
)
_SENSITIVE_KEYS = (
    "authorization",
    "credential",
    "database_url",
    "password",
    "provider_endpoint",
    "secret",
    "service_token",
    "storage_ref",
    "token",
)


class AeWebOperationsError(ValueError):
    pass


def build_ae_web_operations_summary(
    *,
    service_observations: Sequence[Mapping[str, Any]] | None = None,
    database_available: bool = False,
    agent_runtime_available: bool = False,
    provider_route_configured: bool = False,
) -> dict[str, Any]:
    observations = {
        _required_text(item.get("service_id"), "service_id"): item
        for item in (service_observations or ())
    }
    services = []
    for service_id in _SERVICE_IDS:
        item = observations.get(service_id, {})
        services.append(
            {
                "service_id": service_id,
                "health_status": _safe_status(item.get("health_status"), "UNKNOWN"),
                "readiness_status": _safe_status(
                    item.get("readiness_status"), "NOT_OBSERVED"
                ),
                "version": _safe_version(item.get("version")),
            }
        )
    if "nex-ae-api" not in observations:
        services[_SERVICE_IDS.index("nex-ae-api")].update(
            {
                "health_status": "HEALTHY",
                "readiness_status": "READY" if database_available else "DEGRADED",
            }
        )
    projection = {
        "operations_summary_schema_version": AE_WEB_OPERATIONS_SUMMARY_SCHEMA_VERSION,
        "overall_status": _overall_status(services),
        "services": services,
        "runtime": {
            "database_status": "AVAILABLE" if database_available else "UNAVAILABLE",
            "agent_runtime_status": (
                "AVAILABLE" if agent_runtime_available else "UNAVAILABLE"
            ),
            "provider_route_status": (
                "CONFIGURED" if provider_route_configured else "UNAVAILABLE"
            ),
        },
        "safe_routes": [
            {
                "route_id": "ae-web-operations-summary",
                "method": "GET",
                "path": AE_WEB_OPERATIONS_SUMMARY_PATH,
            }
        ],
        "metadata": {
            "read_only": True,
            "same_origin_required": True,
            "direct_service_requests_allowed": False,
            "protected_material_included": False,
            "private_content_included": False,
        },
    }
    validate_ae_web_operations_summary(projection)
    return projection


def validate_ae_web_operations_summary(payload: Mapping[str, Any]) -> None:
    if payload.get("operations_summary_schema_version") != (
        AE_WEB_OPERATIONS_SUMMARY_SCHEMA_VERSION
    ):
        raise AeWebOperationsError("Operations summary schema is invalid.")
    services = payload.get("services")
    if not isinstance(services, list) or not services:
        raise AeWebOperationsError("Operations service projection is invalid.")
    sensitive = _find_sensitive_keys(payload)
    if sensitive:
        raise AeWebOperationsError(
            f"Operations summary contains sensitive keys: {', '.join(sensitive)}"
        )
    serialized = repr(dict(payload)).lower()
    if "127.0.0.1:81" in serialized or "/data/nex-platform" in serialized:
        raise AeWebOperationsError("Operations summary contains private locations.")


def register_ae_web_operations_routes(
    app: FastAPI,
    *,
    source: Callable[[], Mapping[str, Any]] | None = None,
) -> None:
    projection_source = source or build_ae_web_operations_summary

    @app.get(AE_WEB_OPERATIONS_SUMMARY_PATH, response_model=None)
    def get_ae_web_operations_summary(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> Mapping[str, Any] | JSONResponse:
        auth = authorize_ae_facade_route_request(request, authorization)
        if isinstance(auth, JSONResponse):
            return auth
        denied = _authorize_operator(request, auth)
        if denied is not None:
            return denied
        try:
            projection = dict(projection_source())
            validate_ae_web_operations_summary(projection)
            return projection
        except Exception:
            return problem_response(
                request,
                status_code=503,
                error_code="AE_WEB_OPERATIONS_UNAVAILABLE",
                title="Operations projection unavailable",
                detail="The safe operations projection is temporarily unavailable.",
                retryable=True,
            )


def _authorize_operator(
    request: Request,
    auth: AeFacadeRouteAuthContext,
) -> JSONResponse | None:
    browser = auth.browser_context
    roles = {role.strip().lower() for role in browser.roles} if browser else set()
    if auth.is_browser_user and roles.intersection(AE_WEB_OPERATIONS_ROLES):
        return None
    return problem_response(
        request,
        status_code=403,
        error_code="AE_WEB_OPERATIONS_FORBIDDEN",
        title="Operations access denied",
        detail="AE operations are available only to admin or operator users.",
        retryable=False,
    )


def _overall_status(services: Sequence[Mapping[str, Any]]) -> str:
    observed = [item for item in services if item["readiness_status"] != "NOT_OBSERVED"]
    if any(item["readiness_status"] in {"NOT_READY", "UNAVAILABLE"} for item in observed):
        return "ATTENTION"
    if any(item["readiness_status"] == "DEGRADED" for item in observed):
        return "DEGRADED"
    return "READY" if observed else "UNKNOWN"


def _safe_status(value: Any, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    normalized = value.strip().upper()
    return normalized if normalized.replace("_", "").isalnum() else fallback


def _safe_version(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip()
    if len(normalized) > 48 or any(char in normalized for char in "/\\:@"):
        return None
    return normalized


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AeWebOperationsError(f"{field} is required.")
    return value.strip()


def _find_sensitive_keys(value: Any, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            normalized = str(key).lower()
            if any(part in normalized for part in _SENSITIVE_KEYS):
                found.append(child_path)
            found.extend(_find_sensitive_keys(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_find_sensitive_keys(child, f"{path}[{index}]"))
    return sorted(found)
