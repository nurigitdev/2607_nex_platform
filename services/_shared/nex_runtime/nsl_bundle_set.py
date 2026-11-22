from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .nsl_runtime_bundle import load_nsl_runtime_bundle
from .semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

NSL_CANDIDATE_BUNDLE_SCHEMA_VERSION = "nex_nsl_candidate_bundle.v1"
NSL_RUNTIME_BUNDLE_SET_SCHEMA_VERSION = "nex_nsl_runtime_bundle_set.v1"


class NslBundleSetError(ValueError):
    pass


@dataclass(frozen=True)
class CandidateNslBundle:
    bundle_id: str
    bundle_version: int
    pack_id: str
    pack_version: str
    pack_manifest_ref: str
    pack_manifest_sha256: str
    pack_manifest_digest: str
    binding_catalog_ref: str
    binding_catalog_sha256: str
    binding_catalog_digest: str
    wheel_lock_ref: str
    wheel_lock_sha256: str
    wheel_package_version: str
    trust_policy_id: str
    publisher: str
    content_hash: str


@dataclass(frozen=True)
class NslBundleSetEntry:
    bundle_id: str
    state: str
    manifest_ref: str
    manifest_sha256: str
    pack_id: str | None
    pack_manifest_digest: str | None


@dataclass(frozen=True)
class NslRuntimeBundleSet:
    bundle_set_id: str
    bundle_set_version: int
    bundles: tuple[NslBundleSetEntry, ...]
    content_hash: str


def load_candidate_nsl_bundle(
    path: Path, *, repository_root: Path
) -> CandidateNslBundle:
    value = _json_object(path, "Candidate NSL bundle lock")
    if set(value) != {
        "schema_version",
        "bundle_id",
        "bundle_version",
        "bundle_state",
        "runtime_selectable",
        "pack",
        "wheel_lock",
        "trust",
        "content_hash",
    }:
        raise NslBundleSetError("Candidate NSL bundle lock fields are invalid.")
    if value.get("schema_version") != NSL_CANDIDATE_BUNDLE_SCHEMA_VERSION:
        raise NslBundleSetError("Candidate NSL bundle schema is unsupported.")
    if (
        value.get("bundle_state") != "CANDIDATE_DESCRIPTOR_ONLY"
        or value.get("runtime_selectable") is not False
    ):
        raise NslBundleSetError("Candidate NSL bundle must remain non-selectable.")
    content_hash = _content_hash(value, "Candidate NSL bundle")
    bundle_version = _positive_int(value.get("bundle_version"), "bundle_version")
    pack = _exact_mapping(
        value.get("pack"),
        {
            "pack_id",
            "pack_version",
            "manifest_ref",
            "manifest_sha256",
            "manifest_content_digest",
            "binding_catalog_ref",
            "binding_catalog_sha256",
            "binding_catalog_content_digest",
        },
        "pack",
    )
    wheel = _exact_mapping(
        value.get("wheel_lock"),
        {"ref", "sha256", "package_version"},
        "wheel_lock",
    )
    trust = _exact_mapping(
        value.get("trust"),
        {
            "trust_policy_id",
            "publisher",
            "signing_key_id",
            "signature_status",
            "compile_state",
            "activation_requires",
        },
        "trust",
    )
    if (
        trust.get("signing_key_id") is not None
        or trust.get("signature_status") != "NOT_SIGNED"
        or trust.get("compile_state") != "PENDING_S8_01E"
        or trust.get("activation_requires") != "S8_01E_GATE"
    ):
        raise NslBundleSetError("Candidate NSL bundle trust state is invalid.")

    manifest_ref = _relative(pack.get("manifest_ref"), "pack.manifest_ref")
    catalog_ref = _relative(pack.get("binding_catalog_ref"), "pack.binding_catalog_ref")
    wheel_ref = _relative(wheel.get("ref"), "wheel_lock.ref")
    manifest = _verified_json_ref(
        repository_root,
        manifest_ref,
        _digest_ref(pack.get("manifest_sha256"), "pack.manifest_sha256"),
        "Skill-Pack manifest",
    )
    catalog = _verified_json_ref(
        repository_root,
        catalog_ref,
        _digest_ref(pack.get("binding_catalog_sha256"), "pack.binding_catalog_sha256"),
        "Skill-Pack binding catalog",
    )
    wheel_lock = _verified_json_ref(
        repository_root,
        wheel_ref,
        _digest_ref(wheel.get("sha256"), "wheel_lock.sha256"),
        "NSL wheel lock",
    )
    manifest_digest = _digest_ref(
        pack.get("manifest_content_digest"), "pack.manifest_content_digest"
    )
    catalog_digest = _digest_ref(
        pack.get("binding_catalog_content_digest"),
        "pack.binding_catalog_content_digest",
    )
    if (
        manifest.get("pack_id") != pack.get("pack_id")
        or manifest.get("pack_version") != pack.get("pack_version")
        or _attested_digest(manifest, "Skill-Pack manifest") != manifest_digest
    ):
        raise NslBundleSetError("Candidate NSL bundle pack identity differs.")
    if (
        manifest.get("runtime_selectable") is not False
        or manifest.get("source_state") != "DESCRIPTOR_ONLY_NOT_COMPILED"
        or manifest.get("binding_catalog", {}).get("path") != catalog_ref
        or manifest.get("binding_catalog", {}).get("content_digest") != catalog_digest
        or _attested_digest(catalog, "Skill-Pack catalog") != catalog_digest
    ):
        raise NslBundleSetError("Candidate NSL bundle source authority differs.")
    manifest_trust = _mapping(manifest.get("trust"), "manifest.trust")
    if (
        manifest_trust.get("trust_policy_id") != trust.get("trust_policy_id")
        or manifest_trust.get("publisher") != trust.get("publisher")
        or manifest_trust.get("signature_status") != "NOT_SIGNED"
    ):
        raise NslBundleSetError("Candidate NSL bundle trust authority differs.")
    if wheel_lock.get("package_version") != wheel.get("package_version"):
        raise NslBundleSetError("Candidate NSL bundle wheel version differs.")

    return CandidateNslBundle(
        bundle_id=_text(value.get("bundle_id"), "bundle_id"),
        bundle_version=bundle_version,
        pack_id=_text(pack.get("pack_id"), "pack.pack_id"),
        pack_version=_text(pack.get("pack_version"), "pack.pack_version"),
        pack_manifest_ref=manifest_ref,
        pack_manifest_sha256=_digest_ref(
            pack.get("manifest_sha256"), "pack.manifest_sha256"
        ),
        pack_manifest_digest=manifest_digest,
        binding_catalog_ref=catalog_ref,
        binding_catalog_sha256=_digest_ref(
            pack.get("binding_catalog_sha256"), "pack.binding_catalog_sha256"
        ),
        binding_catalog_digest=catalog_digest,
        wheel_lock_ref=wheel_ref,
        wheel_lock_sha256=_digest_ref(wheel.get("sha256"), "wheel_lock.sha256"),
        wheel_package_version=_text(
            wheel.get("package_version"), "wheel_lock.package_version"
        ),
        trust_policy_id=_text(trust.get("trust_policy_id"), "trust.trust_policy_id"),
        publisher=_text(trust.get("publisher"), "trust.publisher"),
        content_hash=content_hash,
    )


def load_nsl_runtime_bundle_set(
    path: Path, *, repository_root: Path
) -> NslRuntimeBundleSet:
    value = _json_object(path, "NSL runtime bundle set")
    if set(value) != {
        "schema_version",
        "bundle_set_id",
        "bundle_set_version",
        "bundles",
        "content_hash",
    }:
        raise NslBundleSetError("NSL runtime bundle-set fields are invalid.")
    if value.get("schema_version") != NSL_RUNTIME_BUNDLE_SET_SCHEMA_VERSION:
        raise NslBundleSetError("NSL runtime bundle-set schema is unsupported.")
    content_hash = _content_hash(value, "NSL runtime bundle set")
    raw_entries = value.get("bundles")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise NslBundleSetError("NSL runtime bundle set must contain bundles.")
    entries = tuple(
        _bundle_set_entry(item, repository_root=repository_root) for item in raw_entries
    )
    if list(entries) != sorted(entries, key=lambda item: item.bundle_id):
        raise NslBundleSetError("NSL runtime bundles must be canonically ordered.")
    identities = [entry.bundle_id for entry in entries]
    if len(identities) != len(set(identities)):
        raise NslBundleSetError("NSL runtime bundle IDs must be unique.")
    return NslRuntimeBundleSet(
        bundle_set_id=_text(value.get("bundle_set_id"), "bundle_set_id"),
        bundle_set_version=_positive_int(
            value.get("bundle_set_version"), "bundle_set_version"
        ),
        bundles=entries,
        content_hash=content_hash,
    )


def bundle_set_readiness(bundle_set: NslRuntimeBundleSet) -> dict[str, Any]:
    return {
        "schema_version": "nex_nsl_runtime_bundle_set_readiness.v1",
        "status": "PASS",
        "bundle_set_id": bundle_set.bundle_set_id,
        "bundle_set_version": bundle_set.bundle_set_version,
        "bundle_count": len(bundle_set.bundles),
        "active_bundle_count": sum(
            entry.state == "ACTIVE" for entry in bundle_set.bundles
        ),
        "candidate_bundle_count": sum(
            entry.state == "CANDIDATE_DESCRIPTOR_ONLY" for entry in bundle_set.bundles
        ),
        "content_hash": bundle_set.content_hash,
    }


def _bundle_set_entry(value: object, *, repository_root: Path) -> NslBundleSetEntry:
    entry = _exact_mapping(
        value,
        {
            "bundle_id",
            "state",
            "manifest_ref",
            "manifest_sha256",
            "pack_id",
            "pack_manifest_digest",
        },
        "bundle entry",
    )
    bundle_id = _text(entry.get("bundle_id"), "bundle_id")
    state = entry.get("state")
    if state not in {"ACTIVE", "CANDIDATE_DESCRIPTOR_ONLY"}:
        raise NslBundleSetError("NSL runtime bundle state is invalid.")
    manifest_ref = _relative(entry.get("manifest_ref"), "manifest_ref")
    manifest_sha256 = _digest_ref(entry.get("manifest_sha256"), "manifest_sha256")
    manifest_path = _contained(repository_root, manifest_ref)
    _require_digest(manifest_path, manifest_sha256, "NSL bundle manifest")
    pack_id = entry.get("pack_id")
    pack_digest = entry.get("pack_manifest_digest")
    if state == "ACTIVE":
        if pack_id is not None or pack_digest is not None:
            raise NslBundleSetError("Active historical bundle cannot claim a pack.")
        if load_nsl_runtime_bundle(manifest_path).bundle_id != bundle_id:
            raise NslBundleSetError("Active NSL bundle identity differs.")
    else:
        candidate = load_candidate_nsl_bundle(
            manifest_path, repository_root=repository_root
        )
        if (
            candidate.bundle_id != bundle_id
            or candidate.pack_id != pack_id
            or candidate.pack_manifest_digest != pack_digest
        ):
            raise NslBundleSetError("Candidate NSL bundle identity differs.")
        pack_id = candidate.pack_id
        pack_digest = candidate.pack_manifest_digest
    return NslBundleSetEntry(
        bundle_id=bundle_id,
        state=str(state),
        manifest_ref=manifest_ref,
        manifest_sha256=manifest_sha256,
        pack_id=None if pack_id is None else _text(pack_id, "pack_id"),
        pack_manifest_digest=(
            None
            if pack_digest is None
            else _digest_ref(pack_digest, "pack_manifest_digest")
        ),
    )


def _content_hash(value: Mapping[str, Any], label: str) -> str:
    supplied = _digest_ref(value.get("content_hash"), f"{label}.content_hash")
    expected = semantic_sha256_hash_ref(
        {key: item for key, item in value.items() if key != "content_hash"}
    )
    if supplied != expected:
        raise NslBundleSetError(f"{label} content hash differs.")
    return supplied


def _attested_digest(value: Mapping[str, Any], label: str) -> str:
    attestation = _mapping(value.get("release_attestation"), f"{label}.attestation")
    return _digest_ref(attestation.get("content_digest"), f"{label}.digest")


def _verified_json_ref(
    root: Path, reference: str, expected_sha256: str, label: str
) -> dict[str, Any]:
    path = _contained(root, reference)
    _require_digest(path, expected_sha256, label)
    return _json_object(path, label)


def _require_digest(path: Path, expected: str, label: str) -> None:
    try:
        observed = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise NslBundleSetError(f"{label} is unavailable.") from exc
    if observed != expected:
        raise NslBundleSetError(f"{label} digest differs.")


def _contained(root: Path, reference: str) -> Path:
    candidate = (root / reference).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise NslBundleSetError("NSL bundle reference escapes the repository root.")
    return candidate


def _json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NslBundleSetError(f"{label} is unreadable.") from exc
    return _mapping(value, label)


def _exact_mapping(value: object, fields: set[str], label: str) -> dict[str, Any]:
    result = _mapping(value, label)
    if set(result) != fields:
        raise NslBundleSetError(f"{label} fields are invalid.")
    return result


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise NslBundleSetError(f"{label} must be an object.")
    return dict(value)


def _text(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > 512
    ):
        raise NslBundleSetError(f"{field} must be a bounded non-empty string.")
    return value


def _relative(value: object, field: str) -> str:
    result = _text(value, field)
    path = Path(result)
    if path.is_absolute() or ".." in path.parts:
        raise NslBundleSetError(f"{field} must be a contained relative path.")
    return result


def _digest_ref(value: object, field: str) -> str:
    try:
        return validate_hash_ref(value)
    except ValueError as exc:
        raise NslBundleSetError(f"{field} must be a SHA-256 reference.") from exc


def _positive_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise NslBundleSetError(f"{field} must be a positive integer.")
    return value
