from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from nex_runtime.nsl_bundle_set import (
    NSL_CANDIDATE_BUNDLE_SCHEMA_VERSION,
    NSL_RUNTIME_BUNDLE_SET_SCHEMA_VERSION,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

from .nex_skill_packs import load_skill_pack_manifests
from .nex_tool_inventory import load_tool_inventory

_ACTIVE_BUNDLE_PATH = Path("deployment/locks/ae-product-nsl-runtime-bundle.v1.json")
_ACTIVE_REGISTRY_PATH = Path(
    "deployment/environments/ae-product-capability-registry.v1.json"
)
_BUNDLE_SET_PATH = Path("deployment/locks/ae-product-nsl-runtime-bundles.v2.json")
_REGISTRY_RELEASE_PATH = Path(
    "deployment/environments/ae-product-capability-registry.v2.json"
)
_WHEEL_LOCK_PATH = Path("deployment/locks/nsl-v0.2.1-wheel.json")

_PACK_RELEASES: Mapping[str, Mapping[str, str]] = {
    "D04_ACCOUNTING": {
        "bundle_id": "nex-mybee-d04-accounting-candidate-v1",
        "bundle_path": (
            "deployment/locks/ae-mybee-d04-accounting-candidate-bundle.v1.json"
        ),
        "manifest_path": "domains/mybee/skills/d04_accounting/manifest.v1.json",
        "catalog_path": ("domains/mybee/skills/d04_accounting/tool_bindings.v1.json"),
    },
    "D12_PROJECT": {
        "bundle_id": "nex-mybee-d12-project-candidate-v1",
        "bundle_path": (
            "deployment/locks/ae-mybee-d12-project-candidate-bundle.v1.json"
        ),
        "manifest_path": "domains/mybee/skills/d12_project/manifest.v1.json",
        "catalog_path": "domains/mybee/skills/d12_project/tool_bindings.v1.json",
    },
}


def render_release_json(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def build_w70_registry_release_artifacts(
    root: Path,
) -> dict[Path, dict[str, Any]]:
    packs = load_skill_pack_manifests()
    inventory = load_tool_inventory()
    inventory_by_id = {item.canonical_operation_id: item for item in inventory.tools}
    wheel_lock = _json(root / _WHEEL_LOCK_PATH)
    wheel_sha = _byte_hash(root / _WHEEL_LOCK_PATH)

    artifacts: dict[Path, dict[str, Any]] = {}
    bundle_payloads: dict[str, dict[str, Any]] = {}
    for pack in packs:
        spec = _PACK_RELEASES[pack.domain_code]
        manifest_path = Path(spec["manifest_path"])
        catalog_path = Path(spec["catalog_path"])
        manifest = _json(root / manifest_path)
        payload: dict[str, Any] = {
            "schema_version": NSL_CANDIDATE_BUNDLE_SCHEMA_VERSION,
            "bundle_id": spec["bundle_id"],
            "bundle_version": 1,
            "bundle_state": "CANDIDATE_DESCRIPTOR_ONLY",
            "runtime_selectable": False,
            "pack": {
                "pack_id": pack.pack_id,
                "pack_version": pack.pack_version,
                "manifest_ref": manifest_path.as_posix(),
                "manifest_sha256": _byte_hash(root / manifest_path),
                "manifest_content_digest": pack.content_digest,
                "binding_catalog_ref": catalog_path.as_posix(),
                "binding_catalog_sha256": _byte_hash(root / catalog_path),
                "binding_catalog_content_digest": pack.binding_catalog_digest,
            },
            "wheel_lock": {
                "ref": _WHEEL_LOCK_PATH.as_posix(),
                "sha256": wheel_sha,
                "package_version": wheel_lock["package_version"],
            },
            "trust": {
                "trust_policy_id": pack.trust_policy_id,
                "publisher": manifest["trust"]["publisher"],
                "signing_key_id": None,
                "signature_status": "NOT_SIGNED",
                "compile_state": "PENDING_S8_01E",
                "activation_requires": "S8_01E_GATE",
            },
        }
        payload["content_hash"] = semantic_sha256_hash_ref(payload)
        bundle_path = Path(spec["bundle_path"])
        artifacts[bundle_path] = payload
        bundle_payloads[pack.domain_code] = payload

    active_bundle = _json(root / _ACTIVE_BUNDLE_PATH)
    bundle_entries = [
        {
            "bundle_id": active_bundle["bundle_id"],
            "state": "ACTIVE",
            "manifest_ref": _ACTIVE_BUNDLE_PATH.as_posix(),
            "manifest_sha256": _byte_hash(root / _ACTIVE_BUNDLE_PATH),
            "pack_id": None,
            "pack_manifest_digest": None,
        }
    ]
    for pack in packs:
        spec = _PACK_RELEASES[pack.domain_code]
        payload = bundle_payloads[pack.domain_code]
        bundle_path = Path(spec["bundle_path"])
        bundle_entries.append(
            {
                "bundle_id": payload["bundle_id"],
                "state": "CANDIDATE_DESCRIPTOR_ONLY",
                "manifest_ref": bundle_path.as_posix(),
                "manifest_sha256": _payload_hash(payload),
                "pack_id": pack.pack_id,
                "pack_manifest_digest": pack.content_digest,
            }
        )
    bundle_set: dict[str, Any] = {
        "schema_version": NSL_RUNTIME_BUNDLE_SET_SCHEMA_VERSION,
        "bundle_set_id": "nex-ae-product-nsl-bundles-mybee-w70",
        "bundle_set_version": 2,
        "bundles": sorted(bundle_entries, key=lambda item: item["bundle_id"]),
    }
    bundle_set["content_hash"] = semantic_sha256_hash_ref(bundle_set)
    artifacts[_BUNDLE_SET_PATH] = bundle_set

    candidates = []
    for pack in packs:
        spec = _PACK_RELEASES[pack.domain_code]
        bundle_payload = bundle_payloads[pack.domain_code]
        manifest_path = Path(spec["manifest_path"])
        catalog_path = Path(spec["catalog_path"])
        for binding in pack.bindings:
            identity = inventory_by_id[binding.canonical_operation_id]
            candidate: dict[str, Any] = {
                "capability_id": binding.canonical_operation_id,
                "capability_version": binding.skill_version,
                "admission_state": binding.inventory_activation_state,
                "runtime_selectable": False,
                "operation_semantics": binding.invocation_semantics,
                "approval_requirement": binding.approval_requirement,
                "compatibility_aliases": list(identity.compatibility_aliases),
                "skill_source": {
                    "pack_id": pack.pack_id,
                    "skill_id": binding.skill_id,
                    "exact_skill_version": binding.skill_version,
                    "source_manifest_ref": manifest_path.as_posix(),
                    "source_manifest_digest": pack.content_digest,
                    "binding_catalog_ref": catalog_path.as_posix(),
                    "binding_catalog_digest": pack.binding_catalog_digest,
                    "contract_admission_ref": binding.contract_admission_ref,
                    "compile_state": "PENDING_S8_01E",
                },
                "bundle_lock": {
                    "bundle_id": bundle_payload["bundle_id"],
                    "manifest_ref": spec["bundle_path"],
                    "manifest_sha256": _payload_hash(bundle_payload),
                },
            }
            candidate["candidate_hash"] = semantic_sha256_hash_ref(candidate)
            candidates.append(candidate)

    predecessor = _json(root / _ACTIVE_REGISTRY_PATH)
    release: dict[str, Any] = {
        "schema_version": "ae.product_capability_registry.v2",
        "registry_id": "ae-product-capabilities-mybee-w70",
        "registry_version": 2,
        "predecessor_registry": {
            "path": _ACTIVE_REGISTRY_PATH.as_posix(),
            "sha256": _byte_hash(root / _ACTIVE_REGISTRY_PATH),
            "registry_hash": predecessor["registry_hash"],
        },
        "bundle_set": {
            "path": _BUNDLE_SET_PATH.as_posix(),
            "sha256": _payload_hash(bundle_set),
            "content_hash": bundle_set["content_hash"],
        },
        "active_registrations": predecessor["registrations"],
        "candidate_admissions": sorted(
            candidates, key=lambda item: item["capability_id"]
        ),
    }
    release["registry_hash"] = semantic_sha256_hash_ref(release)
    artifacts[_REGISTRY_RELEASE_PATH] = release
    return artifacts


def _payload_hash(value: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(render_release_json(value)).hexdigest()


def _byte_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"Expected a JSON object: {path}")
    return value
