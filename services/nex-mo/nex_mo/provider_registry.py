from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nex_mo.provider_projection import project_provider_route


@dataclass(frozen=True)
class ProviderRoute:
    alias: str
    provider_capability: str
    provider_type: str
    model_revision: str
    deployment_id: str
    route_id: str
    supports_response_formats: tuple[str, ...]
    max_input_tokens: int
    max_output_tokens: int
    status: str = "READY"
    embedding_dimensions: int | None = None

    def to_wire(self) -> dict[str, Any]:
        return project_provider_route(self)


@dataclass(frozen=True)
class ProviderRouteError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False
    degraded: bool = False
    failure_kind: str | None = None
    upstream_status_code: int | None = None
    retry_after_seconds: float | None = None


DEFAULT_PROVIDER_ROUTES: tuple[ProviderRoute, ...] = (
    ProviderRoute(
        alias="mock-embedding-default",
        provider_capability="embedding",
        provider_type="mock-embedding",
        model_revision="mock-embedding-v1",
        deployment_id="mock-embedding-local",
        route_id="route-mock-embedding-default",
        supports_response_formats=("vector",),
        max_input_tokens=4096,
        max_output_tokens=0,
        embedding_dimensions=8,
    ),
    ProviderRoute(
        alias="mock-reranker-default",
        provider_capability="reranking",
        provider_type="mock-reranker",
        model_revision="mock-reranker-v1",
        deployment_id="mock-reranker-local",
        route_id="route-mock-reranker-default",
        supports_response_formats=("score",),
        max_input_tokens=4096,
        max_output_tokens=0,
    ),
    ProviderRoute(
        alias="general-llm-default",
        provider_capability="generation",
        provider_type="mock-generation",
        model_revision="mock-llm-v1",
        deployment_id="mock-generation-local",
        route_id="route-general-llm-default",
        supports_response_formats=("text", "json_object"),
        max_input_tokens=8192,
        max_output_tokens=1024,
    ),
)


def list_provider_routes(
    capability: str | None = None,
    routes: tuple[ProviderRoute, ...] = DEFAULT_PROVIDER_ROUTES,
) -> list[ProviderRoute]:
    if capability is None:
        return list(routes)
    return [route for route in routes if route.provider_capability == capability]


def resolve_provider_route(
    alias: str,
    provider_capability: str,
    routes: tuple[ProviderRoute, ...] = DEFAULT_PROVIDER_ROUTES,
) -> ProviderRoute:
    matches = [route for route in routes if route.alias == alias]
    if not matches:
        raise ProviderRouteError(
            404,
            "mo.alias_not_found",
            f"Unknown provider alias: {alias}",
        )
    route = matches[0]
    if route.provider_capability != provider_capability:
        raise ProviderRouteError(
            422,
            "mo.capability_not_supported",
            f"Alias {alias} does not support {provider_capability}.",
        )
    if route.status != "READY":
        raise ProviderRouteError(
            503,
            "mo.deployment_unavailable",
            f"Alias {alias} is not ready.",
            retryable=True,
        )
    return route
