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
