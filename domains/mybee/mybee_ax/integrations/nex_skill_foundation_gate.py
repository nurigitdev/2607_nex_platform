"""Deterministic W70 S8-01 compile, admission, alias, and trust Gate."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from nex_runtime.nsl_bundle_set import (
    bundle_set_readiness,
    load_candidate_nsl_bundle,
    load_nsl_runtime_bundle_set,
)
from nex_runtime.nsl_package_admission import inspect_installed_nsl_package
from nex_runtime.operation_names import DEFAULT_OPERATION_REGISTRY
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from nsl.cli_config import load_tool_catalog
from nsl.compiler import NslCompiler
from nsl.diagnostics import CompileError

from .nex_skill_packs import load_skill_pack_manifests
from .nex_tool_contracts import load_tool_contract_catalog
from .nex_tool_inventory import load_tool_inventory

FOUNDATION_GATE_SCHEMA_VERSION = "nex.mybee.w70-s8-01-foundation-gate.v1"
FOUNDATION_GATE_ID = "mybee.phase1.w70.s8-01.foundation"

_INVENTORY = Path("domains/mybee/skills/tool_inventory.v1.json")
_CONTRACTS = Path(
    "contracts/admissions/nex_eos/w70_tool_contract_admission.v1.json"
)
_OPENAPI = Path("contracts/openapi/nex-eos.openapi.yaml")
_SKILL_ROOT = Path("domains/mybee/skills")
_FIXTURE_ROOT = _SKILL_ROOT / "foundation_gate"
_TOOL_CATALOG = _FIXTURE_ROOT / "tool_catalog.v1.json"
_WHEEL_LOCK = Path("deployment/locks/nsl-v0.2.1-wheel.json")
_PLATFORM_LOCK = Path("deployment/locks/python-production.lock")
_REGISTRY_RELEASE = Path(
    "deployment/environments/ae-product-capability-registry.v2.json"
)
_BUNDLE_SET = Path("deployment/locks/ae-product-nsl-runtime-bundles.v2.json")
_ACTIVE_REGISTRY = Path(
    "deployment/environments/ae-product-capability-registry.v1.json"
)
_ACTIVE_BUNDLE = Path("deployment/locks/ae-product-nsl-runtime-bundle.v1.json")
_CANDIDATE_BUNDLES = {
    "D04_ACCOUNTING": Path(
        "deployment/locks/ae-mybee-d04-accounting-candidate-bundle.v1.json"
    ),
    "D12_PROJECT": Path(
        "deployment/locks/ae-mybee-d12-project-candidate-bundle.v1.json"
    ),
}
_POSITIVE_PROFILES = (
    {
        "profile_id": "D04_READ",
        "source": _FIXTURE_ROOT / "d04_read_profile.ns",
        "skill_id": "W70.FOUNDATION.D04_READ_PROFILE",
        "domain_code": "D04_ACCOUNTING",
        "semantics": "READ",
    },
    {
        "profile_id": "D04_GOVERNED_WRITE",
        "source": _FIXTURE_ROOT / "d04_write_profile.ns",
        "skill_id": "W70.FOUNDATION.D04_WRITE_PROFILE",
        "domain_code": "D04_ACCOUNTING",
        "semantics": "GOVERNED_WRITE",
    },
    {
        "profile_id": "D12_READ",
        "source": _FIXTURE_ROOT / "d12_read_profile.ns",
        "skill_id": "W70.FOUNDATION.D12_READ_PROFILE",
        "domain_code": "D12_PROJECT",
        "semantics": "READ",
    },
)
_NEGATIVE_SOURCE = _FIXTURE_ROOT / "status_only_negative.ns"
_ERROR_CODE = re.compile(r"\[(NSL-E\d{4})\]")


class W70FoundationGateError(ValueError):
    """Raised when the immutable S8-01 Foundation Gate receipt drifts."""


def render_foundation_gate_json(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def build_w70_foundation_gate_receipt(root: Path) -> dict[str, Any]:
    inventory = load_tool_inventory(root / _INVENTORY)
    contracts = load_tool_contract_catalog(
        root / _CONTRACTS,
        openapi_path=root / _OPENAPI,
        inventory=inventory,
    )
    packs = load_skill_pack_manifests(
        root / _SKILL_ROOT,
        inventory=inventory,
        contracts=contracts,
        wheel_lock_path=root / _WHEEL_LOCK,
    )
    wheel_lock = _json(root / _WHEEL_LOCK)
    runtime_readiness = inspect_installed_nsl_package(
        wheel_lock,
        platform_lock_path=root / _PLATFORM_LOCK,
    )
    catalog = load_tool_catalog(root / _TOOL_CATALOG)

    compile_profiles = []
    profile_ids: set[tuple[str, str]] = set()
    for spec in _POSITIVE_PROFILES:
        source = (root / spec["source"]).read_text(encoding="utf-8")
        first = NslCompiler(catalog).compile(source)
        second = NslCompiler(catalog).compile(source)
        if (
            first.skill.skill_id != spec["skill_id"]
            or first.skill.semantic_hash != second.skill.semantic_hash
            or first.nso_bytes != second.nso_bytes
        ):
            raise W70FoundationGateError(
                f"non-deterministic compiler profile: {spec['profile_id']}"
            )
        profile_ids.add((str(spec["domain_code"]), str(spec["semantics"])))
        compile_profiles.append(
            {
                "profile_id": spec["profile_id"],
                "domain_code": spec["domain_code"],
                "operation_semantics": spec["semantics"],
                "source_ref": spec["source"].as_posix(),
                "source_sha256": _byte_hash(root / spec["source"]),
                "tool_catalog_ref": _TOOL_CATALOG.as_posix(),
                "tool_catalog_sha256": _byte_hash(root / _TOOL_CATALOG),
                "skill_id": first.skill.skill_id,
                "skill_version": first.skill.skill_version,
                "semantic_hash": first.skill.semantic_hash,
                "nso_sha256": "sha256:"
                + hashlib.sha256(first.nso_bytes).hexdigest(),
                "admission_state": "PROFILE_COMPILE_ADMITTED",
                "product_skill": False,
            }
        )

    negative_source = (root / _NEGATIVE_SOURCE).read_text(encoding="utf-8")
    try:
        NslCompiler(catalog).compile(negative_source)
    except CompileError as exc:
        match = _ERROR_CODE.search(str(exc))
        observed_code = match.group(1) if match else "UNKNOWN"
    else:
        raise W70FoundationGateError("status-only compiler profile was admitted")
    if observed_code != "NSL-E4001":
        raise W70FoundationGateError(
            f"unexpected status-only rejection: {observed_code}"
        )

    admissions = []
    fully_typed = 0
    status_only = 0
    for pack in packs:
        for binding in pack.bindings:
            typed = binding.contract_typing_state == "FULLY_TYPED"
            profile_key = (pack.domain_code, binding.invocation_semantics)
            if typed and profile_key not in profile_ids:
                raise W70FoundationGateError(
                    "missing compiler profile for "
                    f"{binding.canonical_operation_id}: {profile_key}"
                )
            if typed:
                fully_typed += 1
                state = "PROFILE_COMPILE_ADMITTED_SKILL_SOURCE_PENDING"
                blocker = "SIGNED_PRODUCT_SKILL_REQUIRED"
            else:
                status_only += 1
                state = "BLOCKED_STATUS_ONLY_CONTRACT"
                blocker = "CANONICAL_SUCCESS_RESPONSE_SCHEMA_REQUIRED"
            admissions.append(
                {
                    "capability_id": binding.canonical_operation_id,
                    "pack_id": pack.pack_id,
                    "contract_typing_state": binding.contract_typing_state,
                    "compile_admission_state": state,
                    "runtime_selectable": False,
                    "activation_blocker": blocker,
                }
            )

    aliases = []
    alias_pairs = sorted(
        (alias, item.canonical_operation_id)
        for item in inventory.tools
        for alias in item.compatibility_aliases
    )
    for requested, canonical in alias_pairs:
        resolved = DEFAULT_OPERATION_REGISTRY.resolve(requested)
        if resolved.canonical_operation != canonical or not resolved.alias_applied:
            raise W70FoundationGateError(f"alias resolution drift: {requested}")
        aliases.append(resolved.to_projection())
    for item in inventory.tools:
        resolved = DEFAULT_OPERATION_REGISTRY.resolve(item.canonical_operation_id)
        if resolved.alias_applied:
            raise W70FoundationGateError(
                f"canonical operation resolved as alias: {item.canonical_operation_id}"
            )

    candidate_bundles = []
    for domain_code, relative in sorted(_CANDIDATE_BUNDLES.items()):
        bundle = load_candidate_nsl_bundle(
            root / relative, repository_root=root
        )
        raw = _json(root / relative)
        candidate_bundles.append(
            {
                "domain_code": domain_code,
                "bundle_id": bundle.bundle_id,
                "bundle_ref": relative.as_posix(),
                "bundle_sha256": _byte_hash(root / relative),
                "content_hash": bundle.content_hash,
                "trust_policy_id": bundle.trust_policy_id,
                "signature_status": raw["trust"]["signature_status"],
                "runtime_selectable": raw["runtime_selectable"],
                "admission_state": "BLOCKED_UNSIGNED",
            }
        )

    bundle_set = load_nsl_runtime_bundle_set(
        root / _BUNDLE_SET, repository_root=root
    )
    release = _json(root / _REGISTRY_RELEASE)
    active_registry = _json(root / _ACTIVE_REGISTRY)
    active_bundle = _json(root / _ACTIVE_BUNDLE)
    receipt: dict[str, Any] = {
        "schema_version": FOUNDATION_GATE_SCHEMA_VERSION,
        "gate_id": FOUNDATION_GATE_ID,
        "gate_state": "PASS",
        "runtime_wheel": {
            "lock_ref": _WHEEL_LOCK.as_posix(),
            "lock_sha256": _byte_hash(root / _WHEEL_LOCK),
            "package_version": runtime_readiness["package_version"],
            "wheel_sha256": runtime_readiness["wheel_sha256"],
            "release_admission_hash": runtime_readiness[
                "release_admission_hash"
            ],
            "public_api_complete": runtime_readiness["public_api_complete"],
            "runtime_import_origin": runtime_readiness["runtime_import_origin"],
        },
        "compile_profiles": compile_profiles,
        "negative_compile_cases": [
            {
                "case_id": "STATUS_ONLY_TOOL_NOT_IN_ADMITTED_COMPILER_CATALOG",
                "source_ref": _NEGATIVE_SOURCE.as_posix(),
                "source_sha256": _byte_hash(root / _NEGATIVE_SOURCE),
                "expected_error_code": "NSL-E4001",
                "observed_error_code": observed_code,
                "outcome": "REJECTED_AS_EXPECTED",
            }
        ],
        "candidate_admission": {
            "total": len(admissions),
            "fully_typed": fully_typed,
            "status_only": status_only,
            "runtime_selectable": 0,
            "admissions": sorted(admissions, key=lambda item: item["capability_id"]),
        },
        "alias_admission": {
            "registry_version": inventory.registry_version,
            "aliases": aliases,
        },
        "trust_admission": {
            "candidate_bundles": candidate_bundles,
            "unsigned_runtime_activation": "FAIL_CLOSED",
            "cross_tenant_artifact_resolution": "TENANT_SCOPED_FAIL_CLOSED",
        },
        "registry_continuity": {
            "candidate_registry_ref": _REGISTRY_RELEASE.as_posix(),
            "candidate_registry_sha256": _byte_hash(root / _REGISTRY_RELEASE),
            "candidate_registry_hash": release["registry_hash"],
            "candidate_registry_version": release["registry_version"],
            "bundle_set_ref": _BUNDLE_SET.as_posix(),
            "bundle_set_sha256": _byte_hash(root / _BUNDLE_SET),
            "bundle_set_readiness": bundle_set_readiness(bundle_set),
            "active_registry_ref": _ACTIVE_REGISTRY.as_posix(),
            "active_registry_sha256": _byte_hash(root / _ACTIVE_REGISTRY),
            "active_registry_hash": active_registry["registry_hash"],
            "active_bundle_ref": _ACTIVE_BUNDLE.as_posix(),
            "active_bundle_sha256": _byte_hash(root / _ACTIVE_BUNDLE),
            "active_bundle_id": active_bundle["bundle_id"],
            "golden_a_runtime_unchanged": True,
        },
        "activation_decision": {
            "foundation_gate": "PASS",
            "candidate_product_skills": "NOT_ACTIVATED",
            "signed_minimal_skill_owner": "CP-M1-MB8-01",
            "remote_provider_required": False,
        },
    }
    receipt["content_hash"] = semantic_sha256_hash_ref(receipt)
    return receipt


def verify_w70_foundation_gate_receipt(path: Path, *, root: Path) -> dict[str, Any]:
    actual = _json(path)
    expected = build_w70_foundation_gate_receipt(root)
    if actual != expected:
        raise W70FoundationGateError("foundation Gate receipt drift")
    return actual


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise W70FoundationGateError(f"unreadable JSON: {path}") from exc
    if not isinstance(value, dict):
        raise W70FoundationGateError(f"expected JSON object: {path}")
    return value


def _byte_hash(path: Path) -> str:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise W70FoundationGateError(f"unreadable artifact: {path}") from exc
    return "sha256:" + hashlib.sha256(payload).hexdigest()
