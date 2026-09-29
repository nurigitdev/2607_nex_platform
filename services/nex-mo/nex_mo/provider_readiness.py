from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Sequence

from nex_mo.provider_projection import (
    project_provider_readiness_snapshot,
    project_provider_route_health,
)
from nex_mo.provider_registry import DEFAULT_PROVIDER_ROUTES, ProviderRoute


REQUIRED_PROVIDER_CAPABILITIES = ("embedding", "reranking", "generation")
ROUTE_HEALTH_STATUSES = {"READY", "DEGRADED", "UNAVAILABLE", "UNKNOWN"}
ROUTE_HEALTH_SOURCES = {"mock_registry", "active_preflight"}
CACHE_STATUSES = {"FRESH", "REFRESHED", "STALE"}


@dataclass(frozen=True)
class ProviderRouteHealth:
    provider_capability: str
    alias: str
    route_id: str
    deployment_id: str
    model_revision: str
    status: str
    source: str
    checked_at: str
    latency_ms: int | None = None
    failure_code: str | None = None
    retryable: bool = False
    degraded: bool = False

    def __post_init__(self) -> None:
        if self.provider_capability not in REQUIRED_PROVIDER_CAPABILITIES:
            raise ValueError("unsupported provider capability")
        if self.status not in ROUTE_HEALTH_STATUSES:
            raise ValueError("unsupported route health status")
        if self.source not in ROUTE_HEALTH_SOURCES:
            raise ValueError("unsupported route health source")
        if self.latency_ms is not None and self.latency_ms < 0:
            raise ValueError("latency_ms must not be negative")
        _parse_timestamp(self.checked_at)

    def to_wire(self) -> dict[str, Any]:
        return project_provider_route_health(self)


@dataclass(frozen=True)
class ProviderReadinessSnapshot:
    provider_mode: str
    readiness_status: str
    checked_at: str
    expires_at: str
    cache_status: str
    required_capabilities: tuple[str, ...]
    routes: tuple[ProviderRouteHealth, ...]
    failure_code: str | None

    def to_wire(self) -> dict[str, Any]:
        return project_provider_readiness_snapshot(self)


def build_mock_provider_readiness_snapshot(
    *,
    routes: Sequence[ProviderRoute] = DEFAULT_PROVIDER_ROUTES,
    checked_at: str | None = None,
    ttl_seconds: int = 30,
) -> ProviderReadinessSnapshot:
    observed_at = checked_at or utc_now()
    health = tuple(
        ProviderRouteHealth(
            provider_capability=route.provider_capability,
            alias=route.alias,
            route_id=route.route_id,
            deployment_id=route.deployment_id,
            model_revision=route.model_revision,
            status="READY" if route.status == "READY" else "UNAVAILABLE",
            source="mock_registry",
            checked_at=observed_at,
            failure_code=(
                None if route.status == "READY" else "mock_route_not_ready"
            ),
        )
        for route in routes
        if route.provider_capability in REQUIRED_PROVIDER_CAPABILITIES
    )
    return build_provider_readiness_snapshot(
        provider_mode="mock",
        routes=health,
        checked_at=observed_at,
        ttl_seconds=ttl_seconds,
        cache_status="FRESH",
    )


def build_provider_readiness_snapshot(
    *,
    provider_mode: str,
    routes: Sequence[ProviderRouteHealth],
    checked_at: str,
    ttl_seconds: int,
    cache_status: str,
    required_capabilities: tuple[str, ...] = REQUIRED_PROVIDER_CAPABILITIES,
) -> ProviderReadinessSnapshot:
    if provider_mode not in {"mock", "live"}:
        raise ValueError("provider_mode must be mock or live")
    if not required_capabilities or len(set(required_capabilities)) != len(
        required_capabilities
    ):
        raise ValueError("required capabilities must be unique and non-empty")
    if not 1 <= ttl_seconds <= 300:
        raise ValueError("ttl_seconds must be between 1 and 300")
    if cache_status not in CACHE_STATUSES:
        raise ValueError("unsupported cache status")
    checked = _parse_timestamp(checked_at)
    health_by_capability: dict[str, ProviderRouteHealth] = {}
    for route in routes:
        if route.provider_capability not in required_capabilities:
            raise ValueError("route capability is not required")
        if route.provider_capability in health_by_capability:
            raise ValueError("duplicate route health capability")
        health_by_capability[route.provider_capability] = route
    ready = cache_status != "STALE" and all(
        capability in health_by_capability
        and health_by_capability[capability].status == "READY"
        for capability in required_capabilities
    )
    return ProviderReadinessSnapshot(
        provider_mode=provider_mode,
        readiness_status="READY" if ready else "NOT_READY",
        checked_at=checked_at,
        expires_at=(checked + timedelta(seconds=ttl_seconds)).isoformat().replace(
            "+00:00", "Z"
        ),
        cache_status=cache_status,
        required_capabilities=required_capabilities,
        routes=tuple(routes),
        failure_code=None if ready else "provider_route_not_ready",
    )


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("timestamp must be ISO 8601") from exc
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(UTC)
