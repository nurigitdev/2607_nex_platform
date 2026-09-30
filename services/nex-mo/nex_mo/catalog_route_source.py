from __future__ import annotations

from collections.abc import Sequence

from nex_mo.catalog_lifecycle_service import (
    CatalogLifecycleService,
    CatalogLifecycleServiceError,
)
from nex_mo.provider_registry import (
    DEFAULT_PROVIDER_ROUTES,
    ProviderRoute,
    ProviderRouteError,
)


_CAPABILITY_ORDER = {"embedding": 0, "reranking": 1, "generation": 2}


class CatalogProviderRouteSource:
    def __init__(self, service: CatalogLifecycleService) -> None:
        self._service = service

    def __call__(self) -> Sequence[ProviderRoute]:
        try:
            bindings = self._service.list_alias_bindings(state="ACTIVE")
            routes = [self._route(binding) for binding in bindings]
        except CatalogLifecycleServiceError as exc:
            raise _runtime_unavailable() from exc
        return tuple(
            sorted(
                routes,
                key=lambda route: (
                    _CAPABILITY_ORDER[route.provider_capability],
                    route.alias,
                ),
            )
        )

    def _route(self, binding) -> ProviderRoute:
        entry = self._service.get_catalog_entry(binding.catalog_id)
        if (
            entry.catalog_state != "ACTIVE"
            or entry.provider_capability != binding.provider_capability
        ):
            raise _runtime_unavailable()
        return ProviderRoute(
            alias=binding.alias,
            provider_capability=binding.provider_capability,
            provider_type=entry.provider_type,
            model_revision=entry.model_revision,
            deployment_id=entry.deployment_id,
            route_id=_route_id(binding, entry),
            supports_response_formats=entry.supports_response_formats,
            max_input_tokens=entry.max_input_tokens,
            max_output_tokens=entry.max_output_tokens,
            embedding_dimensions=entry.embedding_dimensions,
        )


def _route_id(binding, entry) -> str:
    static = next(
        (
            route
            for route in DEFAULT_PROVIDER_ROUTES
            if route.alias == binding.alias
            and route.provider_capability == binding.provider_capability
            and route.model_revision == entry.model_revision
            and route.deployment_id == entry.deployment_id
        ),
        None,
    )
    if static is not None:
        return static.route_id
    return f"route-{binding.binding_id.replace(':', '-')}"


def _runtime_unavailable() -> ProviderRouteError:
    return ProviderRouteError(
        503,
        "mo.catalog_runtime_unavailable",
        "Provider catalog runtime is unavailable.",
        retryable=True,
        degraded=True,
    )
