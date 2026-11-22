from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nex_runtime.semantic_hashes import (
    canonical_json,
    semantic_sha256_hash_ref,
    validate_hash_ref,
)

from nex_ae_api.product_capabilities import ProductCapabilityRegistry

PRODUCT_CAPABILITY_RETIREMENT_PATH_ENV = (
    "NEX_AE_PRODUCT_CAPABILITY_RETIREMENT_PATH"
)
PRODUCT_CAPABILITY_RETIREMENT_SCHEMA_VERSION = (
    "ae.product_capability_retirement_projection.v1"
)
GOLDEN_A_RETIRED_CAPABILITY_ID = "FINANCE.CREATE_VOUCHER_DRAFT"


@dataclass(frozen=True)
class ProductCapabilityRetirementError(ValueError):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class CoveredRegistry:
    registry_id: str
    registry_version: int
    registry_hash: str


@dataclass(frozen=True)
class ProductCapabilityRetirement:
    capability_id: str
    capability_version: str
    compatibility_aliases: tuple[str, ...]
    retirement_state: str
    new_selection: str
    in_flight_policy: str
    active_asset_policy: str
    reason_code: str
    retirement_hash: str

    @property
    def selection_identities(self) -> frozenset[str]:
        return frozenset((self.capability_id, *self.compatibility_aliases))


@dataclass(frozen=True)
class ProductCapabilityRetirementProjection:
    projection_id: str = "empty"
    projection_version: int = 0
    effective_at: str | None = None
    covered_registries: tuple[CoveredRegistry, ...] = ()
    retirements: tuple[ProductCapabilityRetirement, ...] = ()
    inventory_ref: Mapping[str, str] = field(default_factory=dict, repr=False)
    rollback_receipt_ref: Mapping[str, str] = field(
        default_factory=dict, repr=False
    )
    projection_hash: str | None = None

    @property
    def blocked_identities(self) -> frozenset[str]:
        return frozenset(
            identity
            for retirement in self.retirements
            if retirement.new_selection == "DENY"
            for identity in retirement.selection_identities
        )

    def is_new_selection_denied(self, capability_id: object) -> bool:
        return (
            isinstance(capability_id, str)
            and capability_id in self.blocked_identities
        )

    def retirement_for(
        self, capability_id: object
    ) -> ProductCapabilityRetirement | None:
        if not isinstance(capability_id, str):
            return None
        return next(
            (
                retirement
                for retirement in self.retirements
                if capability_id in retirement.selection_identities
            ),
            None,
        )

    def selectable_registry(
        self, registry: ProductCapabilityRegistry
    ) -> ProductCapabilityRegistry:
        blocked = tuple(
            registration
            for registration in registry.registrations
            if self.is_new_selection_denied(registration.capability_id)
        )
        if not blocked:
            return registry
        self._require_covered_registry(registry)
        selected = tuple(
            registration
            for registration in registry.registrations
            if registration not in blocked
        )
        return ProductCapabilityRegistry(
            selected,
            registry_id=f"{registry.registry_id}:retirement-selection-view",
            registry_version=registry.registry_version,
        )

    def _require_covered_registry(
        self, registry: ProductCapabilityRegistry
    ) -> None:
        identity = (
            registry.registry_id,
            registry.registry_version,
            registry.registry_hash,
        )
        covered = {
            (
                item.registry_id,
                item.registry_version,
                item.registry_hash,
            )
            for item in self.covered_registries
        }
        if identity not in covered:
            raise _error(
                "PRODUCT_CAPABILITY_RETIREMENT_REGISTRY_UNCOVERED",
                "Product capability retirement does not cover the active registry.",
            )


def load_product_capability_retirement_projection(
    environ: Mapping[str, str],
    *,
    required: bool = False,
) -> ProductCapabilityRetirementProjection:
    value = str(
        environ.get(PRODUCT_CAPABILITY_RETIREMENT_PATH_ENV) or ""
    ).strip()
    if not value:
        if required:
            raise _error(
                "PRODUCT_CAPABILITY_RETIREMENT_REQUIRED",
                "Canonical product selection requires a retirement projection.",
            )
        return ProductCapabilityRetirementProjection()
    try:
        payload = json.loads(Path(value).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _error(
            "PRODUCT_CAPABILITY_RETIREMENT_UNAVAILABLE",
            "Product capability retirement projection is unavailable.",
        ) from exc
    return _validate_projection(payload)


def _validate_projection(value: object) -> ProductCapabilityRetirementProjection:
    if not isinstance(value, Mapping):
        raise _invalid("Product capability retirement projection must be an object.")
    try:
        record = json.loads(canonical_json(dict(value)))
    except (TypeError, ValueError) as exc:
        raise _invalid(
            "Product capability retirement projection must be canonical JSON."
        ) from exc
    expected_fields = {
        "schema_version",
        "projection_id",
        "projection_version",
        "effective_at",
        "covered_registries",
        "retirements",
        "inventory_ref",
        "rollback_receipt_ref",
        "projection_hash",
    }
    if set(record) != expected_fields:
        raise _invalid("Product capability retirement fields are invalid.")
    if record["schema_version"] != PRODUCT_CAPABILITY_RETIREMENT_SCHEMA_VERSION:
        raise _invalid("Product capability retirement schema is unsupported.")
    projection_id = _text(record["projection_id"], "projection_id", 160)
    projection_version = _positive_int(
        record["projection_version"], "projection_version"
    )
    effective_at = _text(record["effective_at"], "effective_at", 64)
    covered = _covered_registries(record["covered_registries"])
    retirements = _retirements(record["retirements"])
    inventory_ref = _artifact_ref(record["inventory_ref"], "inventory_ref")
    rollback_ref = _artifact_ref(
        record["rollback_receipt_ref"], "rollback_receipt_ref"
    )
    supplied_hash = _hash_ref(record["projection_hash"], "projection_hash")
    expected_hash = semantic_sha256_hash_ref(
        {key: item for key, item in record.items() if key != "projection_hash"}
    )
    if supplied_hash != expected_hash:
        raise _invalid("Product capability retirement hash does not match content.")
    return ProductCapabilityRetirementProjection(
        projection_id=projection_id,
        projection_version=projection_version,
        effective_at=effective_at,
        covered_registries=covered,
        retirements=retirements,
        inventory_ref=inventory_ref,
        rollback_receipt_ref=rollback_ref,
        projection_hash=supplied_hash,
    )


def _covered_registries(value: object) -> tuple[CoveredRegistry, ...]:
    if not isinstance(value, list) or not value:
        raise _invalid("Product capability retirement needs covered registries.")
    records: list[CoveredRegistry] = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {
            "registry_id",
            "registry_version",
            "registry_hash",
        }:
            raise _invalid("Covered product capability registry is invalid.")
        records.append(
            CoveredRegistry(
                registry_id=_text(item["registry_id"], "registry_id", 160),
                registry_version=_positive_int(
                    item["registry_version"], "registry_version"
                ),
                registry_hash=_hash_ref(
                    item["registry_hash"], "registry_hash"
                ),
            )
        )
    identities = [
        (item.registry_id, item.registry_version, item.registry_hash)
        for item in records
    ]
    if len(identities) != len(set(identities)) or identities != sorted(identities):
        raise _invalid("Covered product capability registries are not canonical.")
    return tuple(records)


def _retirements(value: object) -> tuple[ProductCapabilityRetirement, ...]:
    if not isinstance(value, list) or not value:
        raise _invalid("Product capability retirement needs at least one entry.")
    records = tuple(_retirement(item) for item in value)
    if list(records) != sorted(records, key=lambda item: item.capability_id):
        raise _invalid("Product capability retirements must be canonically ordered.")
    identities: set[str] = set()
    for item in records:
        if identities.intersection(item.selection_identities):
            raise _invalid("Product capability retirement identities overlap.")
        identities.update(item.selection_identities)
    return records


def _retirement(value: object) -> ProductCapabilityRetirement:
    fields = {
        "capability_id",
        "capability_version",
        "compatibility_aliases",
        "retirement_state",
        "new_selection",
        "in_flight_policy",
        "active_asset_policy",
        "reason_code",
        "retirement_hash",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise _invalid("Product capability retirement entry is invalid.")
    aliases = value["compatibility_aliases"]
    if (
        not isinstance(aliases, list)
        or not aliases
        or any(not isinstance(item, str) for item in aliases)
        or aliases != sorted(set(aliases))
    ):
        raise _invalid("Product capability retirement aliases are not canonical.")
    state = value["retirement_state"]
    if state not in {"DEPRECATED", "REPLAY_ONLY"}:
        raise _invalid("Product capability retirement state is invalid.")
    if value["new_selection"] != "DENY":
        raise _invalid("Retired product capability must deny new selection.")
    if value["in_flight_policy"] != "DRAIN_OR_RECONCILE":
        raise _invalid("Product capability in-flight policy is invalid.")
    if value["active_asset_policy"] != "RETAIN_UNTIL_RET_02":
        raise _invalid("Product capability active-asset policy is invalid.")
    supplied_hash = _hash_ref(value["retirement_hash"], "retirement_hash")
    projection = {key: item for key, item in value.items() if key != "retirement_hash"}
    if supplied_hash != semantic_sha256_hash_ref(projection):
        raise _invalid("Product capability retirement entry hash differs.")
    return ProductCapabilityRetirement(
        capability_id=_text(value["capability_id"], "capability_id", 160),
        capability_version=_text(
            value["capability_version"], "capability_version", 64
        ),
        compatibility_aliases=tuple(aliases),
        retirement_state=str(state),
        new_selection="DENY",
        in_flight_policy="DRAIN_OR_RECONCILE",
        active_asset_policy="RETAIN_UNTIL_RET_02",
        reason_code=_text(value["reason_code"], "reason_code", 160),
        retirement_hash=supplied_hash,
    )


def _artifact_ref(value: object, field: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != {"path", "sha256"}:
        raise _invalid(f"Product capability retirement {field} is invalid.")
    return {
        "path": _text(value["path"], f"{field}.path", 512),
        "sha256": _hash_ref(value["sha256"], f"{field}.sha256"),
    }


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _invalid(f"Product capability retirement {field} is invalid.")
    return value


def _text(value: object, field: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > maximum
    ):
        raise _invalid(f"Product capability retirement {field} is invalid.")
    return value


def _hash_ref(value: object, field: str) -> str:
    try:
        return validate_hash_ref(value)
    except ValueError as exc:
        raise _invalid(
            f"Product capability retirement {field} is invalid."
        ) from exc


def _invalid(detail: str) -> ProductCapabilityRetirementError:
    return _error("PRODUCT_CAPABILITY_RETIREMENT_INVALID", detail)


def _error(code: str, detail: str) -> ProductCapabilityRetirementError:
    return ProductCapabilityRetirementError(code, detail)
