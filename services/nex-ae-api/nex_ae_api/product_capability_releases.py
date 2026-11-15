from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nex_runtime.nsl_bundle_set import (
    NslBundleSetError,
    NslRuntimeBundleSet,
    load_nsl_runtime_bundle_set,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

from nex_ae_api.product_capabilities import (
    PRODUCT_CAPABILITY_REGISTRY_PATH_ENV,
    ProductCapabilityRegistration,
    ProductCapabilityRegistry,
    ProductCapabilityRegistryError,
    load_product_capability_registry,
)

PRODUCT_CAPABILITY_REGISTRY_RELEASE_SCHEMA_VERSION = "ae.product_capability_registry.v2"


@dataclass(frozen=True)
class ProductCapabilityRegistryReleaseError(ValueError):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class ProductCapabilityCandidateAdmission:
    capability_id: str
    capability_version: str
    admission_state: str
    operation_semantics: str
    approval_requirement: str
    compatibility_aliases: tuple[str, ...]
    pack_id: str
    skill_id: str
    exact_skill_version: str
    source_manifest_ref: str
    source_manifest_digest: str
    binding_catalog_ref: str
    binding_catalog_digest: str
    contract_admission_ref: str
    bundle_id: str
    bundle_manifest_ref: str
    bundle_manifest_sha256: str
    candidate_hash: str
    runtime_selectable: bool = False


@dataclass(frozen=True)
class ProductCapabilityRegistryRelease:
    registry_id: str
    registry_version: int
    active_registry: ProductCapabilityRegistry
    candidate_admissions: tuple[ProductCapabilityCandidateAdmission, ...]
    bundle_set: NslRuntimeBundleSet
    registry_hash: str

    @property
    def active_registrations(self) -> tuple[ProductCapabilityRegistration, ...]:
        return self.active_registry.registrations

    def resolve_candidate(
        self, capability_id: str
    ) -> ProductCapabilityCandidateAdmission | None:
        return next(
            (
                item
                for item in self.candidate_admissions
                if item.capability_id == capability_id
            ),
            None,
        )


def load_product_capability_registry_release(
    path: Path, *, repository_root: Path
) -> ProductCapabilityRegistryRelease:
    record = _json_object(path, "Product capability registry release")
    if set(record) != {
        "schema_version",
        "registry_id",
        "registry_version",
        "predecessor_registry",
        "bundle_set",
        "active_registrations",
        "candidate_admissions",
        "registry_hash",
    }:
        raise _invalid("Product capability registry release fields are invalid.")
    if record.get("schema_version") != (
        PRODUCT_CAPABILITY_REGISTRY_RELEASE_SCHEMA_VERSION
    ):
        raise _invalid("Product capability registry release schema is unsupported.")
    registry_hash = _content_hash(record)
    registry_id = _text(record.get("registry_id"), "registry_id", 160)
    registry_version = _positive_int(record.get("registry_version"), "registry_version")

    predecessor_ref = _exact_mapping(
        record.get("predecessor_registry"),
        {"path", "sha256", "registry_hash"},
        "predecessor_registry",
    )
    predecessor_path = _verified_ref(
        repository_root,
        predecessor_ref.get("path"),
        predecessor_ref.get("sha256"),
        "Predecessor product capability registry",
    )
    try:
        active_registry = load_product_capability_registry(
            {PRODUCT_CAPABILITY_REGISTRY_PATH_ENV: str(predecessor_path)}
        )
    except ProductCapabilityRegistryError as exc:
        raise _invalid("Predecessor product capability registry is invalid.") from exc
    if active_registry.registry_hash != _hash_ref(
        predecessor_ref.get("registry_hash"), "predecessor_registry.registry_hash"
    ):
        raise _invalid("Predecessor product capability registry hash differs.")
    raw_active = record.get("active_registrations")
    expected_active = [item.to_projection() for item in active_registry.registrations]
    if raw_active != expected_active:
        raise _invalid("Active registrations differ from the immutable predecessor.")

    bundle_ref = _exact_mapping(
        record.get("bundle_set"),
        {"path", "sha256", "content_hash"},
        "bundle_set",
    )
    bundle_path = _verified_ref(
        repository_root,
        bundle_ref.get("path"),
        bundle_ref.get("sha256"),
        "NSL runtime bundle set",
    )
    try:
        bundle_set = load_nsl_runtime_bundle_set(
            bundle_path, repository_root=repository_root
        )
    except NslBundleSetError as exc:
        raise _invalid("NSL runtime bundle set is invalid.") from exc
    if bundle_set.content_hash != _hash_ref(
        bundle_ref.get("content_hash"), "bundle_set.content_hash"
    ):
        raise _invalid("NSL runtime bundle-set content hash differs.")

    raw_candidates = record.get("candidate_admissions")
    if not isinstance(raw_candidates, list) or not 1 <= len(raw_candidates) <= 64:
        raise _invalid("Product capability release requires 1..64 candidates.")
    candidates = tuple(_candidate(item) for item in raw_candidates)
    if list(candidates) != sorted(candidates, key=lambda item: item.capability_id):
        raise _invalid("Product capability candidates must be canonically ordered.")
    identities = [item.capability_id for item in candidates]
    if len(identities) != len(set(identities)):
        raise _invalid("Product capability candidate IDs must be unique.")
    active_ids = {item.capability_id for item in active_registry.registrations}
    if active_ids.intersection(identities):
        raise _invalid("Candidate capability IDs conflict with active registrations.")
    _validate_aliases(candidates, active_ids=active_ids)
    _validate_candidate_bundles(candidates, bundle_set=bundle_set)

    return ProductCapabilityRegistryRelease(
        registry_id=registry_id,
        registry_version=registry_version,
        active_registry=active_registry,
        candidate_admissions=candidates,
        bundle_set=bundle_set,
        registry_hash=registry_hash,
    )


def _candidate(value: object) -> ProductCapabilityCandidateAdmission:
    record = _exact_mapping(
        value,
        {
            "capability_id",
            "capability_version",
            "admission_state",
            "runtime_selectable",
            "operation_semantics",
            "approval_requirement",
            "compatibility_aliases",
            "skill_source",
            "bundle_lock",
            "candidate_hash",
        },
        "candidate admission",
    )
    supplied_hash = _hash_ref(record.get("candidate_hash"), "candidate_hash")
    expected_hash = semantic_sha256_hash_ref(
        {key: item for key, item in record.items() if key != "candidate_hash"}
    )
    if supplied_hash != expected_hash:
        raise _invalid("Product capability candidate hash differs.")
    state = record.get("admission_state")
    if state not in {"CANDIDATE", "DEFERRED", "ACTIVE_COMPATIBILITY"}:
        raise _invalid("Product capability candidate admission state is invalid.")
    if record.get("runtime_selectable") is not False:
        raise _invalid("Product capability candidate must remain non-selectable.")
    semantics = record.get("operation_semantics")
    if semantics not in {"READ", "GOVERNED_WRITE"}:
        raise _invalid("Product capability candidate semantics are invalid.")
    aliases = record.get("compatibility_aliases")
    if (
        not isinstance(aliases, list)
        or any(not isinstance(item, str) or not item.strip() for item in aliases)
        or len(aliases) != len(set(aliases))
    ):
        raise _invalid("Product capability candidate aliases are invalid.")
    source = _exact_mapping(
        record.get("skill_source"),
        {
            "pack_id",
            "skill_id",
            "exact_skill_version",
            "source_manifest_ref",
            "source_manifest_digest",
            "binding_catalog_ref",
            "binding_catalog_digest",
            "contract_admission_ref",
            "compile_state",
        },
        "skill_source",
    )
    if source.get("compile_state") != "PENDING_S8_01E":
        raise _invalid("Product capability candidate compile state is invalid.")
    bundle = _exact_mapping(
        record.get("bundle_lock"),
        {"bundle_id", "manifest_ref", "manifest_sha256"},
        "bundle_lock",
    )
    return ProductCapabilityCandidateAdmission(
        capability_id=_text(record.get("capability_id"), "capability_id", 160),
        capability_version=_text(
            record.get("capability_version"), "capability_version", 64
        ),
        admission_state=str(state),
        operation_semantics=str(semantics),
        approval_requirement=_text(
            record.get("approval_requirement"), "approval_requirement", 128
        ),
        compatibility_aliases=tuple(str(item) for item in aliases),
        pack_id=_text(source.get("pack_id"), "skill_source.pack_id", 160),
        skill_id=_text(source.get("skill_id"), "skill_source.skill_id", 160),
        exact_skill_version=_text(
            source.get("exact_skill_version"),
            "skill_source.exact_skill_version",
            64,
        ),
        source_manifest_ref=_relative(
            source.get("source_manifest_ref"), "skill_source.source_manifest_ref"
        ),
        source_manifest_digest=_hash_ref(
            source.get("source_manifest_digest"),
            "skill_source.source_manifest_digest",
        ),
        binding_catalog_ref=_relative(
            source.get("binding_catalog_ref"), "skill_source.binding_catalog_ref"
        ),
        binding_catalog_digest=_hash_ref(
            source.get("binding_catalog_digest"),
            "skill_source.binding_catalog_digest",
        ),
        contract_admission_ref=_text(
            source.get("contract_admission_ref"),
            "skill_source.contract_admission_ref",
            512,
        ),
        bundle_id=_text(bundle.get("bundle_id"), "bundle_lock.bundle_id", 160),
        bundle_manifest_ref=_relative(
            bundle.get("manifest_ref"), "bundle_lock.manifest_ref"
        ),
        bundle_manifest_sha256=_hash_ref(
            bundle.get("manifest_sha256"), "bundle_lock.manifest_sha256"
        ),
        candidate_hash=supplied_hash,
    )


def _validate_aliases(
    candidates: tuple[ProductCapabilityCandidateAdmission, ...],
    *,
    active_ids: set[str],
) -> None:
    candidate_ids = {item.capability_id for item in candidates}
    owners: dict[str, str] = {}
    for candidate in candidates:
        for alias in candidate.compatibility_aliases:
            if alias in candidate_ids:
                raise _invalid("A compatibility alias conflicts with a candidate ID.")
            previous = owners.setdefault(alias, candidate.capability_id)
            if previous != candidate.capability_id:
                raise _invalid("A compatibility alias has multiple owners.")
            if (
                alias in active_ids
                and candidate.admission_state != "ACTIVE_COMPATIBILITY"
            ):
                raise _invalid(
                    "Only an active-compatibility candidate may alias active."
                )


def _validate_candidate_bundles(
    candidates: tuple[ProductCapabilityCandidateAdmission, ...],
    *,
    bundle_set: NslRuntimeBundleSet,
) -> None:
    bundles = {item.bundle_id: item for item in bundle_set.bundles}
    for candidate in candidates:
        bundle = bundles.get(candidate.bundle_id)
        if (
            bundle is None
            or bundle.state != "CANDIDATE_DESCRIPTOR_ONLY"
            or bundle.manifest_ref != candidate.bundle_manifest_ref
            or bundle.manifest_sha256 != candidate.bundle_manifest_sha256
            or bundle.pack_id != candidate.pack_id
            or bundle.pack_manifest_digest != candidate.source_manifest_digest
        ):
            raise _invalid("Candidate admission differs from its immutable bundle.")


def _content_hash(value: Mapping[str, Any]) -> str:
    supplied = _hash_ref(value.get("registry_hash"), "registry_hash")
    expected = semantic_sha256_hash_ref(
        {key: item for key, item in value.items() if key != "registry_hash"}
    )
    if supplied != expected:
        raise _invalid("Product capability registry release hash differs.")
    return supplied


def _verified_ref(root: Path, reference: object, digest: object, label: str) -> Path:
    relative = _relative(reference, f"{label}.path")
    expected = _hash_ref(digest, f"{label}.sha256")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise _invalid(f"{label} escapes the repository root.")
    try:
        observed = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise _invalid(f"{label} is unavailable.") from exc
    if observed != expected:
        raise _invalid(f"{label} digest differs.")
    return path


def _json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _invalid(f"{label} is unavailable.") from exc
    if not isinstance(value, Mapping):
        raise _invalid(f"{label} must be an object.")
    return dict(value)


def _exact_mapping(value: object, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise _invalid(f"{label} fields are invalid.")
    return dict(value)


def _text(value: object, field: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > maximum
    ):
        raise _invalid(f"Product capability {field} is invalid.")
    return value


def _relative(value: object, field: str) -> str:
    result = _text(value, field, 512)
    path = Path(result)
    if path.is_absolute() or ".." in path.parts:
        raise _invalid(f"Product capability {field} must be repository-relative.")
    return result


def _hash_ref(value: object, field: str) -> str:
    try:
        return validate_hash_ref(value)
    except ValueError as exc:
        raise _invalid(f"Product capability {field} is invalid.") from exc


def _positive_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise _invalid(f"Product capability {field} is invalid.")
    return value


def _invalid(detail: str) -> ProductCapabilityRegistryReleaseError:
    return ProductCapabilityRegistryReleaseError(
        "PRODUCT_CAPABILITY_REGISTRY_RELEASE_INVALID", detail
    )
