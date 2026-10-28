from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Protocol

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref


class DomainIntentActivator(Protocol):
    def activate(
        self,
        *,
        candidate: Mapping[str, Any],
        work_intent: Mapping[str, Any],
        principal_id: str,
        resolved_at: str,
    ) -> Any: ...


@dataclass(frozen=True)
class DomainIntentActivatorRegistryError(Exception):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class DomainIntentActivatorRegistration:
    capability_id: str
    version: str
    source_identity: str
    activator: DomainIntentActivator = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        _required_text("capability_id", self.capability_id, maximum=160)
        _required_text("version", self.version, maximum=128)
        _required_text("source_identity", self.source_identity, maximum=256)
        if not callable(getattr(self.activator, "activate", None)):
            raise DomainIntentActivatorRegistryError(
                "DOMAIN_INTENT_ACTIVATOR_INVALID",
                "Domain intent activator must expose activate().",
            )

    def to_projection(self) -> dict[str, str]:
        projection = {
            "schema_version": "ae.domain_intent_activator_registration.v1",
            "capability_id": self.capability_id,
            "version": self.version,
            "source_identity": self.source_identity,
        }
        projection["registration_hash"] = semantic_sha256_hash_ref(projection)
        return projection


@dataclass(frozen=True)
class DomainIntentActivatorRegistry:
    registrations: tuple[DomainIntentActivatorRegistration, ...] = ()
    _by_capability: Mapping[str, DomainIntentActivatorRegistration] = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        supplied = tuple(self.registrations)
        if any(
            not isinstance(item, DomainIntentActivatorRegistration) for item in supplied
        ):
            raise DomainIntentActivatorRegistryError(
                "DOMAIN_INTENT_ACTIVATOR_REGISTRATION_INVALID",
                "Registry entries must be domain intent activator registrations.",
            )
        ordered = tuple(sorted(supplied, key=lambda item: item.capability_id))
        by_capability: dict[str, DomainIntentActivatorRegistration] = {}
        for registration in ordered:
            if registration.capability_id in by_capability:
                raise DomainIntentActivatorRegistryError(
                    "DOMAIN_INTENT_ACTIVATOR_DUPLICATE",
                    "Domain intent capability registration must be unique.",
                )
            by_capability[registration.capability_id] = registration
        object.__setattr__(self, "registrations", ordered)
        object.__setattr__(self, "_by_capability", MappingProxyType(by_capability))

    @classmethod
    def from_registrations(
        cls, registrations: Iterable[DomainIntentActivatorRegistration]
    ) -> DomainIntentActivatorRegistry:
        return cls(tuple(registrations))

    @classmethod
    def from_mapping(
        cls,
        activators: Mapping[str, DomainIntentActivator],
        *,
        version: str,
        source_identity: str,
    ) -> DomainIntentActivatorRegistry:
        return cls.from_registrations(
            DomainIntentActivatorRegistration(
                capability_id=capability_id,
                version=version,
                source_identity=source_identity,
                activator=activator,
            )
            for capability_id, activator in activators.items()
        )

    def resolve(
        self, capability_id: str, *, required: bool = False
    ) -> DomainIntentActivatorRegistration | None:
        normalized = _required_text("capability_id", capability_id, maximum=160)
        registration = self._by_capability.get(normalized)
        if registration is None and required:
            raise DomainIntentActivatorRegistryError(
                "DOMAIN_INTENT_ACTIVATOR_REQUIRED",
                "Required domain intent capability has no admitted activator.",
            )
        return registration

    def to_projection(self) -> dict[str, Any]:
        projection: dict[str, Any] = {
            "schema_version": "ae.domain_intent_activator_registry.v1",
            "registrations": [item.to_projection() for item in self.registrations],
        }
        projection["registry_hash"] = semantic_sha256_hash_ref(projection)
        return projection


def _required_text(field_name: str, value: object, *, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise DomainIntentActivatorRegistryError(
            "DOMAIN_INTENT_ACTIVATOR_REGISTRATION_INVALID",
            f"{field_name} is invalid.",
        )
    if value != value.strip():
        raise DomainIntentActivatorRegistryError(
            "DOMAIN_INTENT_ACTIVATOR_REGISTRATION_INVALID",
            f"{field_name} must be canonical text.",
        )
    return value
