from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import re
from typing import Any, Sequence
from uuid import NAMESPACE_URL, uuid5

from nex_mo.provider_catalog import build_model_profile_catalog
from nex_mo.provider_registry import DEFAULT_PROVIDER_ROUTES
from nex_mo.catalog_lifecycle_projection import (
    project_alias_binding,
    project_model_catalog_entry,
)


CATALOG_CAPABILITIES = frozenset({"embedding", "reranking", "generation"})
CATALOG_STATES = frozenset({"DRAFT", "ACTIVE", "RETIRED"})
ALIAS_BINDING_STATES = frozenset({"ACTIVE", "SUPERSEDED", "ROLLED_BACK"})
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")


class CatalogLifecycleError(ValueError):
    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


@dataclass(frozen=True)
class ModelCatalogEntry:
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
    catalog_state: str
    revision: int
    created_at: str
    updated_at: str
    embedding_dimensions: int | None = None

    def __post_init__(self) -> None:
        _identifier(self.catalog_id, "catalog_id")
        if self.provider_capability not in CATALOG_CAPABILITIES:
            raise CatalogLifecycleError(
                "mo.catalog_capability_invalid",
                "unsupported catalog capability",
            )
        for field_name in (
            "model_name",
            "model_revision",
            "deployment_id",
            "runtime_profile",
            "precision",
            "provider_type",
        ):
            _required_string(getattr(self, field_name), field_name)
        if self.catalog_state not in CATALOG_STATES:
            raise CatalogLifecycleError(
                "mo.catalog_state_invalid",
                "unsupported catalog state",
            )
        if self.revision < 1:
            raise CatalogLifecycleError(
                "mo.catalog_revision_invalid",
                "catalog revision must be positive",
            )
        if not self.supports_response_formats or any(
            not isinstance(value, str) or not value.strip()
            for value in self.supports_response_formats
        ):
            raise CatalogLifecycleError(
                "mo.catalog_response_formats_invalid",
                "response formats must be non-empty strings",
            )
        if len(set(self.supports_response_formats)) != len(
            self.supports_response_formats
        ):
            raise CatalogLifecycleError(
                "mo.catalog_response_formats_invalid",
                "response formats must be unique",
            )
        if self.max_input_tokens <= 0 or self.max_output_tokens < 0:
            raise CatalogLifecycleError(
                "mo.catalog_token_limits_invalid",
                "catalog token limits are invalid",
            )
        if self.provider_capability == "embedding":
            if self.embedding_dimensions is None or self.embedding_dimensions <= 0:
                raise CatalogLifecycleError(
                    "mo.catalog_embedding_dimensions_invalid",
                    "embedding dimensions must be positive",
                )
        elif self.embedding_dimensions is not None:
            raise CatalogLifecycleError(
                "mo.catalog_embedding_dimensions_invalid",
                "embedding dimensions are only valid for embedding",
            )
        created = _timestamp(self.created_at, "created_at")
        updated = _timestamp(self.updated_at, "updated_at")
        if updated < created:
            raise CatalogLifecycleError(
                "mo.catalog_timestamp_invalid",
                "updated_at must not precede created_at",
            )

    def to_wire(self) -> dict[str, Any]:
        return project_model_catalog_entry(self)


@dataclass(frozen=True)
class AliasBinding:
    binding_id: str
    alias: str
    provider_capability: str
    catalog_id: str
    binding_revision: int
    binding_state: str
    change_reason: str
    changed_by: str
    created_at: str
    previous_binding_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("binding_id", "alias", "catalog_id", "changed_by"):
            _identifier(getattr(self, field_name), field_name)
        if self.previous_binding_id is not None:
            _identifier(self.previous_binding_id, "previous_binding_id")
            if self.previous_binding_id == self.binding_id:
                raise CatalogLifecycleError(
                    "mo.alias_lineage_invalid",
                    "previous binding must differ from binding",
                )
        if self.provider_capability not in CATALOG_CAPABILITIES:
            raise CatalogLifecycleError(
                "mo.alias_capability_invalid",
                "unsupported alias capability",
            )
        if self.binding_revision < 1:
            raise CatalogLifecycleError(
                "mo.alias_revision_invalid",
                "alias binding revision must be positive",
            )
        if self.binding_state not in ALIAS_BINDING_STATES:
            raise CatalogLifecycleError(
                "mo.alias_state_invalid",
                "unsupported alias binding state",
            )
        reason = _required_string(self.change_reason, "change_reason")
        if len(reason) > 500:
            raise CatalogLifecycleError(
                "mo.alias_change_reason_invalid",
                "change reason must be at most 500 characters",
            )
        _timestamp(self.created_at, "created_at")

    def to_wire(self) -> dict[str, Any]:
        return project_alias_binding(self)


def build_bootstrap_catalog(
    *,
    observed_at: str = "2026-10-01T00:00:00Z",
) -> tuple[tuple[ModelCatalogEntry, ...], tuple[AliasBinding, ...]]:
    _timestamp(observed_at, "observed_at")
    profiles = {
        profile.provider_capability: profile
        for profile in build_model_profile_catalog({})
        if profile.selected
    }
    entries: list[ModelCatalogEntry] = []
    bindings: list[AliasBinding] = []
    for route in DEFAULT_PROVIDER_ROUTES:
        profile = profiles[route.provider_capability]
        catalog_id = _stable_id(
            "catalog",
            route.provider_capability,
            route.model_revision,
            route.deployment_id,
        )
        entry = ModelCatalogEntry(
            catalog_id=catalog_id,
            provider_capability=route.provider_capability,
            model_name=profile.model_name,
            model_revision=route.model_revision,
            deployment_id=route.deployment_id,
            runtime_profile=profile.profile_name,
            precision=profile.precision,
            provider_type=route.provider_type,
            supports_response_formats=route.supports_response_formats,
            max_input_tokens=route.max_input_tokens,
            max_output_tokens=route.max_output_tokens,
            embedding_dimensions=route.embedding_dimensions,
            catalog_state="ACTIVE",
            revision=1,
            created_at=observed_at,
            updated_at=observed_at,
        )
        entries.append(entry)
        bindings.append(
            AliasBinding(
                binding_id=_stable_id("binding", route.alias, "1"),
                alias=route.alias,
                provider_capability=route.provider_capability,
                catalog_id=catalog_id,
                binding_revision=1,
                binding_state="ACTIVE",
                change_reason="Static route bootstrap",
                changed_by="nex-mo-bootstrap",
                created_at=observed_at,
            )
        )
    return tuple(entries), tuple(bindings)


def validate_active_bindings(
    entries: Sequence[ModelCatalogEntry],
    bindings: Sequence[AliasBinding],
) -> None:
    entry_by_id = {entry.catalog_id: entry for entry in entries}
    if len(entry_by_id) != len(entries):
        raise CatalogLifecycleError(
            "mo.catalog_identity_conflict",
            "catalog identities must be unique",
        )
    active_keys: set[tuple[str, str]] = set()
    for binding in bindings:
        entry = entry_by_id.get(binding.catalog_id)
        if entry is None:
            raise CatalogLifecycleError(
                "mo.alias_catalog_not_found",
                "alias binding references an unknown catalog entry",
            )
        if binding.provider_capability != entry.provider_capability:
            raise CatalogLifecycleError(
                "mo.alias_capability_mismatch",
                "alias and catalog capabilities must match",
            )
        if binding.binding_state != "ACTIVE":
            continue
        if entry.catalog_state != "ACTIVE":
            raise CatalogLifecycleError(
                "mo.alias_catalog_inactive",
                "active alias must reference an active catalog entry",
            )
        key = (binding.alias, binding.provider_capability)
        if key in active_keys:
            raise CatalogLifecycleError(
                "mo.alias_active_conflict",
                "only one active binding is allowed per alias and capability",
            )
        active_keys.add(key)


def _stable_id(prefix: str, *values: str) -> str:
    return f"{prefix}:{uuid5(NAMESPACE_URL, ':'.join(values)).hex}"


def _identifier(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise CatalogLifecycleError(
            f"mo.{field_name}_invalid",
            f"{field_name} must be a stable identifier",
        )
    return value


def _required_string(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CatalogLifecycleError(
            f"mo.{field_name}_invalid",
            f"{field_name} is required",
        )
    return value.strip()


def _timestamp(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise CatalogLifecycleError(
            f"mo.{field_name}_invalid",
            f"{field_name} must be ISO 8601",
        ) from exc
    if parsed.tzinfo is None:
        raise CatalogLifecycleError(
            f"mo.{field_name}_invalid",
            f"{field_name} must include a timezone",
        )
    return parsed.astimezone(UTC)
