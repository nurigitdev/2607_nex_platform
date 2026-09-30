from __future__ import annotations

from typing import Any, Protocol


class ModelCatalogEntryView(Protocol):
    catalog_id: str
    provider_capability: str
    model_name: str
    model_revision: str
    deployment_id: str
    runtime_profile: str
    precision: str
    provider_type: str
    supports_response_formats: tuple[str, ...]
    max_input_tokens: int
    max_output_tokens: int
    embedding_dimensions: int | None
    catalog_state: str
    revision: int
    created_at: str
    updated_at: str


class AliasBindingView(Protocol):
    binding_id: str
    alias: str
    provider_capability: str
    catalog_id: str
    binding_revision: int
    binding_state: str
    change_reason: str
    created_at: str
    previous_binding_id: str | None


def project_model_catalog_entry(entry: ModelCatalogEntryView) -> dict[str, Any]:
    return {
        "catalog_entry_schema_version": "mo_model_catalog_entry.v1",
        "catalog_id": entry.catalog_id,
        "provider_capability": entry.provider_capability,
        "model_name": entry.model_name,
        "model_revision": entry.model_revision,
        "deployment_id": entry.deployment_id,
        "runtime_profile": entry.runtime_profile,
        "precision": entry.precision,
        "provider_type": entry.provider_type,
        "supports_response_formats": list(entry.supports_response_formats),
        "max_input_tokens": entry.max_input_tokens,
        "max_output_tokens": entry.max_output_tokens,
        "embedding_dimensions": entry.embedding_dimensions,
        "catalog_state": entry.catalog_state,
        "revision": entry.revision,
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
    }


def project_alias_binding(binding: AliasBindingView) -> dict[str, Any]:
    return {
        "alias_binding_schema_version": "mo_alias_binding.v1",
        "binding_id": binding.binding_id,
        "alias": binding.alias,
        "provider_capability": binding.provider_capability,
        "catalog_id": binding.catalog_id,
        "binding_revision": binding.binding_revision,
        "binding_state": binding.binding_state,
        "change_reason": binding.change_reason,
        "previous_binding_id": binding.previous_binding_id,
        "created_at": binding.created_at,
    }
