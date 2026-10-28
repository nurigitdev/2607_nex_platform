from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nex_runtime.semantic_hashes import (
    canonical_json,
    semantic_sha256_hash_ref,
    validate_hash_ref,
)

from nex_ae_api.planning_capabilities import validate_capability_contract

PRODUCT_CAPABILITY_REGISTRY_PATH_ENV = "NEX_AE_PRODUCT_CAPABILITY_REGISTRY_PATH"
PRODUCT_CAPABILITY_REGISTRY_SCHEMA_VERSION = "ae.product_capability_registry.v1"


@dataclass
class ProductCapabilityRegistryError(ValueError):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class ProductCapabilityRegistration:
    capability: Mapping[str, Any] = field(repr=False)
    skill_artifact: Mapping[str, str] = field(repr=False)
    source_identity: str
    registration_hash: str

    @property
    def capability_id(self) -> str:
        return str(self.capability["capability_id"])

    @property
    def capability_version(self) -> str:
        return str(self.capability["capability_version"])

    def to_projection(self) -> dict[str, Any]:
        return {
            "capability": dict(self.capability),
            "skill_artifact": dict(self.skill_artifact),
            "registration_hash": self.registration_hash,
        }


class ProductCapabilityRegistry:
    """Immutable exact-version product capability and Skill registration set."""

    def __init__(
        self,
        registrations: Sequence[ProductCapabilityRegistration] = (),
        *,
        registry_id: str = "empty",
        registry_version: int = 0,
        registry_hash: str | None = None,
    ) -> None:
        normalized = tuple(registrations)
        if any(
            not isinstance(item, ProductCapabilityRegistration) for item in normalized
        ):
            raise _error(
                "PRODUCT_CAPABILITY_REGISTRATION_INVALID",
                "Product capability registration entries are invalid.",
            )
        identities = [item.capability_id for item in normalized]
        if len(set(identities)) != len(identities):
            raise _error(
                "PRODUCT_CAPABILITY_DUPLICATE",
                "Product capability IDs must be unique in one registry.",
            )
        self._registrations = tuple(
            sorted(normalized, key=lambda item: item.capability_id)
        )
        self.registry_id = registry_id
        self.registry_version = registry_version
        self.registry_hash = registry_hash or semantic_sha256_hash_ref(
            {
                "schema_version": PRODUCT_CAPABILITY_REGISTRY_SCHEMA_VERSION,
                "registry_id": registry_id,
                "registry_version": registry_version,
                "registrations": [item.to_projection() for item in self._registrations],
            }
        )

    @property
    def registrations(self) -> tuple[ProductCapabilityRegistration, ...]:
        return self._registrations

    @property
    def source_identity(self) -> str:
        return (
            "nex-ae:product-capability-registry:"
            f"{self.registry_id}:v{self.registry_version}:{self.registry_hash}"
        )

    def resolve(
        self, capability_id: str, *, required: bool = False
    ) -> ProductCapabilityRegistration | None:
        match = next(
            (
                item
                for item in self._registrations
                if item.capability_id == capability_id
            ),
            None,
        )
        if match is None and required:
            raise _error(
                "PRODUCT_CAPABILITY_REQUIRED",
                "Required product capability is not registered.",
            )
        return match

    def merge_capabilities(
        self, baseline: Sequence[Mapping[str, Any]]
    ) -> tuple[dict[str, Any], ...]:
        merged = [validate_capability_contract(item) for item in baseline]
        merged.extend(dict(item.capability) for item in self._registrations)
        identities = [
            (item["capability_id"], item["capability_version"]) for item in merged
        ]
        if len(set(identities)) != len(identities):
            raise _error(
                "PRODUCT_CAPABILITY_BASELINE_CONFLICT",
                "Product capability registration conflicts with the baseline.",
            )
        return tuple(
            sorted(
                merged,
                key=lambda item: (item["capability_id"], item["capability_version"]),
            )
        )


def load_product_capability_registry(
    environ: Mapping[str, str],
) -> ProductCapabilityRegistry:
    value = str(environ.get(PRODUCT_CAPABILITY_REGISTRY_PATH_ENV) or "").strip()
    if not value:
        return ProductCapabilityRegistry()
    try:
        payload = json.loads(Path(value).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _error(
            "PRODUCT_CAPABILITY_REGISTRY_UNAVAILABLE",
            "Product capability registry is unavailable.",
        ) from exc
    return _validate_registry(payload)


def _validate_registry(value: object) -> ProductCapabilityRegistry:
    if not isinstance(value, Mapping):
        raise _invalid("Product capability registry must be an object.")
    try:
        record = json.loads(canonical_json(dict(value)))
    except (TypeError, ValueError) as exc:
        raise _invalid("Product capability registry must be canonical JSON.") from exc
    if set(record) != {
        "schema_version",
        "registry_id",
        "registry_version",
        "registrations",
        "registry_hash",
    }:
        raise _invalid("Product capability registry fields are invalid.")
    if record["schema_version"] != PRODUCT_CAPABILITY_REGISTRY_SCHEMA_VERSION:
        raise _invalid("Product capability registry schema is unsupported.")
    registry_id = _text(record["registry_id"], "registry_id", 160)
    registry_version = record["registry_version"]
    if (
        not isinstance(registry_version, int)
        or isinstance(registry_version, bool)
        or registry_version < 1
    ):
        raise _invalid("Product capability registry version is invalid.")
    registrations = record["registrations"]
    if not isinstance(registrations, list) or not 1 <= len(registrations) <= 64:
        raise _invalid("Product capability registry must contain 1..64 entries.")
    try:
        supplied_hash = validate_hash_ref(record["registry_hash"])
    except ValueError as exc:
        raise _invalid("Product capability registry hash is invalid.") from exc
    expected_hash = semantic_sha256_hash_ref(
        {key: item for key, item in record.items() if key != "registry_hash"}
    )
    if supplied_hash != expected_hash:
        raise _invalid("Product capability registry hash does not match its content.")
    source_identity = (
        "nex-ae:product-capability-registry:"
        f"{registry_id}:v{registry_version}:{supplied_hash}"
    )
    normalized = tuple(
        _validate_registration(item, source_identity=source_identity)
        for item in registrations
    )
    if list(normalized) != sorted(normalized, key=lambda item: item.capability_id):
        raise _invalid("Product capability registrations must be canonically ordered.")
    return ProductCapabilityRegistry(
        normalized,
        registry_id=registry_id,
        registry_version=registry_version,
        registry_hash=supplied_hash,
    )


def _validate_registration(
    value: object, *, source_identity: str
) -> ProductCapabilityRegistration:
    if not isinstance(value, Mapping) or set(value) != {
        "capability",
        "skill_artifact",
        "registration_hash",
    }:
        raise _invalid("Product capability registration fields are invalid.")
    capability = validate_capability_contract(value["capability"])
    binding = capability.get("local_skill_binding")
    if not isinstance(binding, Mapping):
        raise _invalid("Product capability registration requires LOCAL_SKILL.")
    artifact = value["skill_artifact"]
    fields = {
        "bundle_manifest_ref",
        "bundle_id",
        "skill_id",
        "exact_skill_version",
        "skill_semantic_hash",
    }
    if not isinstance(artifact, Mapping) or set(artifact) != fields:
        raise _invalid("Product Skill artifact metadata is invalid.")
    normalized_artifact = {
        field: _text(
            artifact[field], field, 512 if field == "bundle_manifest_ref" else 160
        )
        for field in fields
    }
    try:
        normalized_artifact["skill_semantic_hash"] = validate_hash_ref(
            normalized_artifact["skill_semantic_hash"]
        )
    except ValueError as exc:
        raise _invalid("Product Skill semantic hash is invalid.") from exc
    if (
        normalized_artifact["skill_id"] != binding["skill_id"]
        or normalized_artifact["exact_skill_version"] != binding["exact_skill_version"]
        or normalized_artifact["skill_semantic_hash"] != binding["skill_semantic_hash"]
    ):
        raise _invalid("Product Skill artifact does not match capability binding.")
    try:
        supplied_hash = validate_hash_ref(value["registration_hash"])
    except ValueError as exc:
        raise _invalid("Product capability registration hash is invalid.") from exc
    projection = {
        "capability": capability,
        "skill_artifact": normalized_artifact,
    }
    if supplied_hash != semantic_sha256_hash_ref(projection):
        raise _invalid("Product capability registration hash does not match content.")
    return ProductCapabilityRegistration(
        capability=capability,
        skill_artifact=normalized_artifact,
        source_identity=source_identity,
        registration_hash=supplied_hash,
    )


def _text(value: object, field: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > maximum
    ):
        raise _invalid(f"Product capability {field} is invalid.")
    return value


def _invalid(detail: str) -> ProductCapabilityRegistryError:
    return _error("PRODUCT_CAPABILITY_REGISTRY_INVALID", detail)


def _error(error_code: str, detail: str) -> ProductCapabilityRegistryError:
    return ProductCapabilityRegistryError(error_code, detail)
