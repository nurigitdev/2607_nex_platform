from __future__ import annotations

from typing import Any, Protocol


class ProviderRouteView(Protocol):
    alias: str
    provider_capability: str
    provider_type: str
    model_revision: str
    deployment_id: str
    route_id: str
    supports_response_formats: tuple[str, ...]
    max_input_tokens: int
    max_output_tokens: int
    status: str
    embedding_dimensions: int | None


class ModelProfileView(Protocol):
    profile_name: str
    provider_capability: str
    alias: str
    provider_mode: str
    model_name: str
    precision: str
    runtime_engine: str
    selected: bool
    status: str
    candidate_role: str
    selection_reason: str


class ProviderRouteHealthView(Protocol):
    provider_capability: str
    alias: str
    route_id: str
    deployment_id: str
    model_revision: str
    status: str
    source: str
    checked_at: str
    latency_ms: int | None
    failure_code: str | None
    retryable: bool
    degraded: bool


class ProviderReadinessSnapshotView(Protocol):
    provider_mode: str
    readiness_status: str
    checked_at: str
    expires_at: str
    cache_status: str
    required_capabilities: tuple[str, ...]
    routes: tuple[ProviderRouteHealthView, ...]
    failure_code: str | None


def project_provider_route(route: ProviderRouteView) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "alias": route.alias,
        "provider_capability": route.provider_capability,
        "provider_type": route.provider_type,
        "model_revision": route.model_revision,
        "deployment_id": route.deployment_id,
        "route_id": route.route_id,
        "supports_response_formats": list(route.supports_response_formats),
        "max_input_tokens": route.max_input_tokens,
        "max_output_tokens": route.max_output_tokens,
        "status": route.status,
    }
    if route.embedding_dimensions is not None:
        payload["embedding_dimensions"] = route.embedding_dimensions
    return payload


def project_model_profile(profile: ModelProfileView) -> dict[str, Any]:
    return {
        "profile_name": profile.profile_name,
        "provider_capability": profile.provider_capability,
        "alias": profile.alias,
        "provider_mode": profile.provider_mode,
        "model_name": profile.model_name,
        "precision": profile.precision,
        "runtime_engine": profile.runtime_engine,
        "selected": profile.selected,
        "status": profile.status,
        "candidate_role": profile.candidate_role,
        "selection_reason": profile.selection_reason,
    }


def project_provider_route_health(
    health: ProviderRouteHealthView,
) -> dict[str, Any]:
    return {
        "route_health_schema_version": "mo_provider_route_health.v1",
        "provider_capability": health.provider_capability,
        "alias": health.alias,
        "route_id": health.route_id,
        "deployment_id": health.deployment_id,
        "model_revision": health.model_revision,
        "status": health.status,
        "source": health.source,
        "ok": health.status == "READY",
        "checked_at": health.checked_at,
        "latency_ms": health.latency_ms,
        "failure_code": health.failure_code,
        "retryable": health.retryable,
        "degraded": health.degraded,
    }


def project_provider_readiness_snapshot(
    snapshot: ProviderReadinessSnapshotView,
) -> dict[str, Any]:
    status_counts = {
        status: sum(route.status == status for route in snapshot.routes)
        for status in ("READY", "DEGRADED", "UNAVAILABLE", "UNKNOWN")
    }
    return {
        "provider_readiness_schema_version": "mo_provider_readiness.v1",
        "provider_mode": snapshot.provider_mode,
        "readiness_status": snapshot.readiness_status,
        "checked_at": snapshot.checked_at,
        "expires_at": snapshot.expires_at,
        "cache_status": snapshot.cache_status,
        "required_capabilities": list(snapshot.required_capabilities),
        "summary": {
            "required_count": len(snapshot.required_capabilities),
            "route_count": len(snapshot.routes),
            "status_counts": status_counts,
        },
        "routes": [project_provider_route_health(route) for route in snapshot.routes],
        "failure_code": snapshot.failure_code,
    }
