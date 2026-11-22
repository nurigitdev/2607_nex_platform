from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

from nex_ae_api.product_capabilities import (
    ProductCapabilityRegistration,
    ProductCapabilityRegistry,
)


@dataclass
class ProductSkillCatalogError(ValueError):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class ProductOperationAdapterSet:
    tool_handlers: Mapping[str, Callable[[Mapping[str, Any]], Any]] = field(
        default_factory=dict, repr=False
    )
    write_port: Any | None = field(default=None, repr=False)
    verification_port: Any | None = field(default=None, repr=False)
    reconciliation_port: Any | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        handlers = dict(self.tool_handlers)
        if any(not callable(handler) for handler in handlers.values()):
            raise _error(
                "PRODUCT_OPERATION_HANDLER_INVALID",
                "Product Tool handlers must be callable.",
            )
        object.__setattr__(self, "tool_handlers", MappingProxyType(handlers))


@dataclass(frozen=True)
class ProductOperationAdapterContext:
    environ: Mapping[str, str] = field(repr=False)
    public_api: Any | None = field(default=None, repr=False)
    result_type: Any | None = field(default=None, repr=False)
    result_classification: Any | None = field(default=None, repr=False)


@dataclass(frozen=True)
class ProductOperationAdapterRegistration:
    capability_id: str
    operation_semantics: str
    backend_profile: str
    adapter_id: str
    operation_ids: tuple[str, ...]
    factory: Callable[[ProductOperationAdapterContext], ProductOperationAdapterSet] = (
        field(repr=False, compare=False)
    )

    def __post_init__(self) -> None:
        for name, value in (
            ("capability_id", self.capability_id),
            ("operation_semantics", self.operation_semantics),
            ("backend_profile", self.backend_profile),
            ("adapter_id", self.adapter_id),
        ):
            if not isinstance(value, str) or not value.strip():
                raise _error(
                    "PRODUCT_OPERATION_REGISTRATION_INVALID",
                    f"{name} must be a non-empty string.",
                )
        operations = tuple(self.operation_ids)
        if not operations or len(set(operations)) != len(operations):
            raise _error(
                "PRODUCT_OPERATION_REGISTRATION_INVALID",
                "Operation IDs must be non-empty and unique.",
            )
        if any(not isinstance(item, str) or not item.strip() for item in operations):
            raise _error(
                "PRODUCT_OPERATION_REGISTRATION_INVALID",
                "Operation IDs must be non-empty strings.",
            )
        if not callable(self.factory):
            raise _error(
                "PRODUCT_OPERATION_REGISTRATION_INVALID",
                "Operation adapter factory must be callable.",
            )

    def to_projection(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "operation_semantics": self.operation_semantics,
            "backend_profile": self.backend_profile,
            "adapter_id": self.adapter_id,
            "operation_ids": list(self.operation_ids),
        }


class ProductOperationAdapterRegistry:
    def __init__(
        self, registrations: Sequence[ProductOperationAdapterRegistration]
    ) -> None:
        values = tuple(registrations)
        if any(
            not isinstance(item, ProductOperationAdapterRegistration) for item in values
        ):
            raise _error(
                "PRODUCT_OPERATION_REGISTRATION_INVALID",
                "Operation adapter registry entries are invalid.",
            )
        capabilities = [item.capability_id for item in values]
        operations = [operation for item in values for operation in item.operation_ids]
        if len(set(capabilities)) != len(capabilities):
            raise _error(
                "PRODUCT_OPERATION_CAPABILITY_DUPLICATE",
                "Operation adapter capability IDs must be unique.",
            )
        if len(set(operations)) != len(operations):
            raise _error(
                "PRODUCT_OPERATION_ID_DUPLICATE",
                "Operation IDs must have exactly one adapter owner.",
            )
        self._registrations = tuple(sorted(values, key=lambda item: item.capability_id))
        self.registry_hash = semantic_sha256_hash_ref(self.to_projection())

    @property
    def registrations(self) -> tuple[ProductOperationAdapterRegistration, ...]:
        return self._registrations

    def resolve(
        self, capability_id: str, *, required: bool = False
    ) -> ProductOperationAdapterRegistration | None:
        found = next(
            (
                item
                for item in self._registrations
                if item.capability_id == capability_id
            ),
            None,
        )
        if found is None and required:
            raise _error(
                "PRODUCT_OPERATION_ADAPTER_REQUIRED",
                "Required product operation adapter is not registered.",
            )
        return found

    def to_projection(self) -> dict[str, Any]:
        return {
            "schema_version": "ae.product_operation_adapter_registry.v1",
            "registrations": [item.to_projection() for item in self._registrations],
        }


@dataclass(frozen=True)
class ProductSkillSelection:
    capability: ProductCapabilityRegistration
    release_skill: Any = field(repr=False)
    verified_skill: Any = field(repr=False)
    operation_adapter: ProductOperationAdapterRegistration = field(repr=False)
    release_id: str
    release_hash: str

    def build_adapters(
        self, context: ProductOperationAdapterContext
    ) -> ProductOperationAdapterSet:
        return self.operation_adapter.factory(context)

    def to_projection(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability.capability_id,
            "capability_version": self.capability.capability_version,
            "skill_id": self.release_skill.skill_id,
            "skill_version": self.release_skill.skill_version,
            "skill_semantic_hash": self.release_skill.semantic_hash,
            "skill_artifact_hash": self.release_skill.artifact_hash,
            "release_id": self.release_id,
            "release_hash": self.release_hash,
            "operation_adapter": self.operation_adapter.to_projection(),
        }


class VerifiedProductSkillCatalog:
    """Exact capability-to-signed-Skill selection above one-Skill execution."""

    def __init__(
        self,
        *,
        release: Any,
        capability_registry: ProductCapabilityRegistry,
        operation_registry: ProductOperationAdapterRegistry,
    ) -> None:
        selections = tuple(
            _selection(
                release=release,
                release_skill=skill,
                capability_registry=capability_registry,
                operation_registry=operation_registry,
            )
            for skill in release.skills
        )
        identities = [item.capability.capability_id for item in selections]
        if len(set(identities)) != len(identities):
            raise _error(
                "PRODUCT_SKILL_SELECTOR_DUPLICATE",
                "Verified product Skill selectors must be unique.",
            )
        self._selections = tuple(
            sorted(selections, key=lambda item: item.capability.capability_id)
        )
        self.release_id = str(release.release_id)
        self.release_hash = str(release.content_hash)
        self.package_hash = str(release.package_hash)
        self.signing_key_id = str(release.signing_key_id)
        self.admitted_at = str(release.admitted_at)
        self.catalog_hash = semantic_sha256_hash_ref(self.to_projection())

    @property
    def selections(self) -> tuple[ProductSkillSelection, ...]:
        return self._selections

    def select(self, capability_id: str) -> ProductSkillSelection:
        found = next(
            (
                item
                for item in self._selections
                if item.capability.capability_id == capability_id
            ),
            None,
        )
        if found is None:
            raise _error(
                "PRODUCT_SKILL_CAPABILITY_NOT_ADMITTED",
                "Requested capability is outside the verified product release.",
            )
        return found

    def to_projection(self) -> dict[str, Any]:
        return {
            "schema_version": "ae.verified_product_skill_catalog.v1",
            "release_id": self.release_id,
            "release_hash": self.release_hash,
            "package_hash": self.package_hash,
            "signing_key_id": self.signing_key_id,
            "admitted_at": self.admitted_at,
            "selections": [item.to_projection() for item in self._selections],
        }


def _selection(
    *,
    release: Any,
    release_skill: Any,
    capability_registry: ProductCapabilityRegistry,
    operation_registry: ProductOperationAdapterRegistry,
) -> ProductSkillSelection:
    registration = capability_registry.resolve(
        release_skill.capability_id, required=True
    )
    assert registration is not None
    binding = registration.capability["local_skill_binding"]
    artifact = registration.skill_artifact
    expected_semantics = (
        "WRITE"
        if release_skill.operation_semantics == "GOVERNED_WRITE"
        else release_skill.operation_semantics
    )
    expected = (
        release_skill.skill_id,
        release_skill.skill_version,
        release_skill.semantic_hash,
        release_skill.trust_policy_id,
        expected_semantics,
    )
    observed = (
        artifact["skill_id"],
        artifact["exact_skill_version"],
        artifact["skill_semantic_hash"],
        binding["trust_policy_id"],
        registration.capability["operation_semantics"],
    )
    if observed != expected:
        raise _error(
            "PRODUCT_SKILL_REGISTRATION_DRIFT",
            "Product capability registration differs from the signed release.",
        )
    adapter = operation_registry.resolve(release_skill.capability_id, required=True)
    assert adapter is not None
    if adapter.operation_semantics != expected_semantics:
        raise _error(
            "PRODUCT_OPERATION_SEMANTICS_DRIFT",
            "Product operation adapter semantics differ from the capability.",
        )
    try:
        verified = release.verified_skill_for_capability(release_skill.capability_id)
    except Exception as exc:
        raise _error(
            "PRODUCT_VERIFIED_SKILL_REQUIRED",
            "Signed release has no exact verified Skill identity.",
        ) from exc
    return ProductSkillSelection(
        capability=registration,
        release_skill=release_skill,
        verified_skill=verified,
        operation_adapter=adapter,
        release_id=str(release.release_id),
        release_hash=str(release.content_hash),
    )


def _error(code: str, detail: str) -> ProductSkillCatalogError:
    return ProductSkillCatalogError(code, detail)
