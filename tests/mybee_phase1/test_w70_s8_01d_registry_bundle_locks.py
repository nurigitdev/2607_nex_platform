from __future__ import annotations

import hashlib
import json
import shutil
from copy import deepcopy
from pathlib import Path

import pytest
from mybee_ax.integrations.nex_skill_pack_release import (
    build_w70_registry_release_artifacts,
    render_release_json,
)
from mybee_ax.integrations.nex_skill_packs import load_skill_pack_manifests
from mybee_ax.integrations.nex_tool_inventory import load_tool_inventory
from nex_ae_api.product_capabilities import (
    PRODUCT_CAPABILITY_REGISTRY_PATH_ENV,
    ProductCapabilityRegistryError,
    load_product_capability_registry,
)
from nex_ae_api.product_capability_releases import (
    ProductCapabilityRegistryReleaseError,
    load_product_capability_registry_release,
)
from nex_runtime.nsl_bundle_set import (
    NslBundleSetError,
    bundle_set_readiness,
    load_candidate_nsl_bundle,
    load_nsl_runtime_bundle_set,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

ROOT = Path(__file__).resolve().parents[2]
RELEASE_PATH = Path("deployment/environments/ae-product-capability-registry.v2.json")
BUNDLE_SET_PATH = Path("deployment/locks/ae-product-nsl-runtime-bundles.v2.json")
D04_LOCK_PATH = Path(
    "deployment/locks/ae-mybee-d04-accounting-candidate-bundle.v1.json"
)
D12_LOCK_PATH = Path("deployment/locks/ae-mybee-d12-project-candidate-bundle.v1.json")
RELEASE_TREE_FILES = (
    Path("deployment/environments/ae-product-capability-registry.v1.json"),
    RELEASE_PATH,
    Path("deployment/locks/ae-product-nsl-runtime-bundle.v1.json"),
    BUNDLE_SET_PATH,
    D04_LOCK_PATH,
    D12_LOCK_PATH,
    Path("deployment/locks/nsl-v0.2.1-wheel.json"),
    Path("domains/mybee/skills/d04_accounting/manifest.v1.json"),
    Path("domains/mybee/skills/d04_accounting/tool_bindings.v1.json"),
    Path("domains/mybee/skills/d12_project/manifest.v1.json"),
    Path("domains/mybee/skills/d12_project/tool_bindings.v1.json"),
)


def _json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _write(path: Path, value: dict) -> None:
    path.write_bytes(render_release_json(value))


def _byte_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _rehash(value: dict, field: str) -> None:
    value[field] = semantic_sha256_hash_ref(
        {key: item for key, item in value.items() if key != field}
    )


def _copy_release_tree(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    for relative in RELEASE_TREE_FILES:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    return root


def _load_release(root: Path):
    return load_product_capability_registry_release(
        root / RELEASE_PATH, repository_root=root
    )


def test_w70_registry_release_and_bundle_set_are_exact_and_non_selectable() -> None:
    release = _load_release(ROOT)
    readiness = bundle_set_readiness(release.bundle_set)

    assert release.registry_id == "ae-product-capabilities-mybee-w70"
    assert release.registry_version == 2
    assert len(release.active_registrations) == 1
    assert release.active_registrations[0].capability_id == (
        "FINANCE.CREATE_VOUCHER_DRAFT"
    )
    assert len(release.candidate_admissions) == 18
    assert all(not item.runtime_selectable for item in release.candidate_admissions)
    assert {item.admission_state for item in release.candidate_admissions} == {
        "CANDIDATE",
        "DEFERRED",
        "ACTIVE_COMPATIBILITY",
    }
    assert release.resolve_candidate("FINANCE.PROJECT_PNL.GET") is not None
    assert release.resolve_candidate("UNKNOWN.CAPABILITY") is None
    assert readiness == {
        "schema_version": "nex_nsl_runtime_bundle_set_readiness.v1",
        "status": "PASS",
        "bundle_set_id": "nex-ae-product-nsl-bundles-mybee-w70",
        "bundle_set_version": 2,
        "bundle_count": 3,
        "active_bundle_count": 1,
        "candidate_bundle_count": 2,
        "content_hash": release.bundle_set.content_hash,
    }


def test_w70_generated_release_artifacts_have_no_drift() -> None:
    artifacts = build_w70_registry_release_artifacts(ROOT)

    assert set(artifacts) == {
        D04_LOCK_PATH,
        D12_LOCK_PATH,
        BUNDLE_SET_PATH,
        RELEASE_PATH,
    }
    for relative, value in artifacts.items():
        assert (ROOT / relative).read_bytes() == render_release_json(value)


def test_w70_candidate_admissions_match_skill_packs_and_inventory() -> None:
    release = _load_release(ROOT)
    packs = load_skill_pack_manifests()
    inventory = load_tool_inventory()
    admissions = {item.capability_id: item for item in release.candidate_admissions}
    inventory_by_id = {item.canonical_operation_id: item for item in inventory.tools}

    for pack in packs:
        for binding in pack.bindings:
            admitted = admissions[binding.canonical_operation_id]
            identity = inventory_by_id[binding.canonical_operation_id]
            assert admitted.pack_id == pack.pack_id
            assert admitted.skill_id == binding.skill_id
            assert admitted.exact_skill_version == binding.skill_version
            assert admitted.source_manifest_digest == pack.content_digest
            assert admitted.binding_catalog_digest == pack.binding_catalog_digest
            assert admitted.contract_admission_ref == binding.contract_admission_ref
            assert admitted.admission_state == binding.inventory_activation_state
            assert admitted.operation_semantics == binding.invocation_semantics
            assert admitted.compatibility_aliases == identity.compatibility_aliases


def test_w70_deployed_runtime_still_points_to_v1_active_registry() -> None:
    compose = (ROOT / "deployment/compose/canonical-platform.override.yaml").read_text(
        encoding="utf-8"
    )
    containerfile = (
        ROOT / "deployment/oci/canonical-platform-ae-runtime.Containerfile"
    ).read_text(encoding="utf-8")

    expected = "/app/deployment/product/config/ae-product-capability-registry.v1.json"
    assert expected in compose
    assert expected in containerfile
    assert "ae-product-capability-registry.v2.json" not in compose
    assert "ae-product-capability-registry.v2.json" not in containerfile

    with pytest.raises(ProductCapabilityRegistryError) as raised:
        load_product_capability_registry(
            {PRODUCT_CAPABILITY_REGISTRY_PATH_ENV: str(ROOT / RELEASE_PATH)}
        )
    assert raised.value.error_code == "PRODUCT_CAPABILITY_REGISTRY_INVALID"


@pytest.mark.parametrize(
    "mutation",
    (
        "runtime_selectable",
        "signed",
        "compiled",
        "pack_digest",
        "catalog_digest",
        "wheel_version",
        "trust_policy",
        "fields",
    ),
)
def test_candidate_bundle_lock_drift_fails_closed(
    tmp_path: Path, mutation: str
) -> None:
    root = _copy_release_tree(tmp_path)
    path = root / D04_LOCK_PATH
    payload = _json(path)
    if mutation == "runtime_selectable":
        payload["runtime_selectable"] = True
    elif mutation == "signed":
        payload["trust"]["signing_key_id"] = "key-1"
        payload["trust"]["signature_status"] = "SIGNED"
    elif mutation == "compiled":
        payload["trust"]["compile_state"] = "COMPILED"
    elif mutation == "pack_digest":
        payload["pack"]["manifest_content_digest"] = "sha256:" + "1" * 64
    elif mutation == "catalog_digest":
        payload["pack"]["binding_catalog_content_digest"] = "sha256:" + "2" * 64
    elif mutation == "wheel_version":
        payload["wheel_lock"]["package_version"] = "9.9.9"
    elif mutation == "trust_policy":
        payload["trust"]["trust_policy_id"] = "policy://drift"
    elif mutation == "fields":
        payload["unexpected"] = True
    _rehash(payload, "content_hash")
    _write(path, payload)

    with pytest.raises(NslBundleSetError):
        load_candidate_nsl_bundle(path, repository_root=root)


@pytest.mark.parametrize(
    "mutation",
    ("order", "duplicate", "state", "active_pack", "manifest_digest", "hash"),
)
def test_bundle_set_drift_fails_closed(tmp_path: Path, mutation: str) -> None:
    root = _copy_release_tree(tmp_path)
    path = root / BUNDLE_SET_PATH
    payload = _json(path)
    if mutation == "order":
        payload["bundles"] = list(reversed(payload["bundles"]))
    elif mutation == "duplicate":
        payload["bundles"].append(deepcopy(payload["bundles"][0]))
        payload["bundles"].sort(key=lambda item: item["bundle_id"])
    elif mutation == "state":
        payload["bundles"][0]["state"] = "READY"
    elif mutation == "active_pack":
        active = next(item for item in payload["bundles"] if item["state"] == "ACTIVE")
        active["pack_id"] = "FORBIDDEN"
    elif mutation == "manifest_digest":
        payload["bundles"][0]["manifest_sha256"] = "sha256:" + "3" * 64
    elif mutation == "hash":
        payload["content_hash"] = "sha256:" + "4" * 64
    if mutation != "hash":
        _rehash(payload, "content_hash")
    _write(path, payload)

    with pytest.raises(NslBundleSetError):
        load_nsl_runtime_bundle_set(path, repository_root=root)


@pytest.mark.parametrize(
    "mutation",
    (
        "candidate_selectable",
        "candidate_hash",
        "candidate_duplicate",
        "alias_candidate_collision",
        "active_drift",
        "bundle_id",
        "predecessor_sha",
        "bundle_set_sha",
        "registry_hash",
        "fields",
    ),
)
def test_registry_release_drift_fails_closed(tmp_path: Path, mutation: str) -> None:
    root = _copy_release_tree(tmp_path)
    path = root / RELEASE_PATH
    payload = _json(path)
    first = payload["candidate_admissions"][0]
    if mutation == "candidate_selectable":
        first["runtime_selectable"] = True
        _rehash(first, "candidate_hash")
    elif mutation == "candidate_hash":
        first["candidate_hash"] = "sha256:" + "5" * 64
    elif mutation == "candidate_duplicate":
        duplicate = deepcopy(first)
        payload["candidate_admissions"].append(duplicate)
        payload["candidate_admissions"].sort(key=lambda item: item["capability_id"])
    elif mutation == "alias_candidate_collision":
        first["compatibility_aliases"].append(
            payload["candidate_admissions"][1]["capability_id"]
        )
        _rehash(first, "candidate_hash")
    elif mutation == "active_drift":
        payload["active_registrations"] = []
    elif mutation == "bundle_id":
        first["bundle_lock"]["bundle_id"] = "unknown-bundle"
        _rehash(first, "candidate_hash")
    elif mutation == "predecessor_sha":
        payload["predecessor_registry"]["sha256"] = "sha256:" + "6" * 64
    elif mutation == "bundle_set_sha":
        payload["bundle_set"]["sha256"] = "sha256:" + "7" * 64
    elif mutation == "registry_hash":
        payload["registry_hash"] = "sha256:" + "8" * 64
    elif mutation == "fields":
        payload["unexpected"] = True
    if mutation != "registry_hash":
        _rehash(payload, "registry_hash")
    _write(path, payload)

    with pytest.raises(ProductCapabilityRegistryReleaseError) as raised:
        _load_release(root)
    assert raised.value.error_code == "PRODUCT_CAPABILITY_REGISTRY_RELEASE_INVALID"


def test_registry_release_unreadable_and_non_object_fail_closed(
    tmp_path: Path,
) -> None:
    root = _copy_release_tree(tmp_path)
    path = root / RELEASE_PATH
    path.write_text("[]\n", encoding="utf-8")
    with pytest.raises(ProductCapabilityRegistryReleaseError):
        _load_release(root)

    path.unlink()
    with pytest.raises(ProductCapabilityRegistryReleaseError):
        _load_release(root)


def test_candidate_bundle_reference_byte_hashes_are_exact() -> None:
    for relative in (D04_LOCK_PATH, D12_LOCK_PATH):
        bundle = load_candidate_nsl_bundle(ROOT / relative, repository_root=ROOT)
        assert bundle.pack_manifest_sha256 == _byte_hash(
            ROOT / bundle.pack_manifest_ref
        )
        assert bundle.binding_catalog_sha256 == _byte_hash(
            ROOT / bundle.binding_catalog_ref
        )
        assert bundle.wheel_lock_sha256 == _byte_hash(ROOT / bundle.wheel_lock_ref)


@pytest.mark.parametrize(
    "mutation",
    (
        "schema",
        "version",
        "pack_fields",
        "wheel_fields",
        "trust_fields",
        "manifest_ref",
        "manifest_hash",
        "bundle_id",
        "content_hash",
        "non_object",
        "invalid_json",
    ),
)
def test_candidate_bundle_shape_and_reference_failures_are_rejected(
    tmp_path: Path, mutation: str
) -> None:
    root = _copy_release_tree(tmp_path)
    path = root / D04_LOCK_PATH
    payload: object = _json(path)
    assert isinstance(payload, dict)
    if mutation == "schema":
        payload["schema_version"] = "unsupported"
    elif mutation == "version":
        payload["bundle_version"] = 0
    elif mutation == "pack_fields":
        payload["pack"].pop("pack_version")
    elif mutation == "wheel_fields":
        payload["wheel_lock"] = []
    elif mutation == "trust_fields":
        payload["trust"].pop("publisher")
    elif mutation == "manifest_ref":
        payload["pack"]["manifest_ref"] = "../escape.json"
    elif mutation == "manifest_hash":
        payload["pack"]["manifest_sha256"] = "not-a-hash"
    elif mutation == "bundle_id":
        payload["bundle_id"] = " "
    elif mutation == "content_hash":
        payload["content_hash"] = "sha256:" + "9" * 64
    elif mutation == "non_object":
        payload = []
    elif mutation == "invalid_json":
        path.write_text("{", encoding="utf-8")
    if isinstance(payload, dict) and mutation not in {"content_hash"}:
        _rehash(payload, "content_hash")
    if mutation != "invalid_json":
        path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(NslBundleSetError):
        load_candidate_nsl_bundle(path, repository_root=root)


@pytest.mark.parametrize(
    "mutation",
    (
        "fields",
        "schema",
        "empty",
        "version",
        "entry_fields",
        "active_identity",
        "candidate_identity",
        "manifest_missing",
        "manifest_escape",
        "manifest_hash_invalid",
        "non_object",
        "invalid_json",
    ),
)
def test_bundle_set_shape_and_reference_failures_are_rejected(
    tmp_path: Path, mutation: str
) -> None:
    root = _copy_release_tree(tmp_path)
    path = root / BUNDLE_SET_PATH
    payload: object = _json(path)
    assert isinstance(payload, dict)
    if mutation == "fields":
        payload["unexpected"] = True
    elif mutation == "schema":
        payload["schema_version"] = "unsupported"
    elif mutation == "empty":
        payload["bundles"] = []
    elif mutation == "version":
        payload["bundle_set_version"] = False
    elif mutation == "entry_fields":
        payload["bundles"][0].pop("pack_id")
    elif mutation == "active_identity":
        active = next(item for item in payload["bundles"] if item["state"] == "ACTIVE")
        active["bundle_id"] = "different-active-id"
        payload["bundles"].sort(key=lambda item: item["bundle_id"])
    elif mutation == "candidate_identity":
        payload["bundles"][0]["pack_id"] = "DIFFERENT.PACK"
    elif mutation == "manifest_missing":
        payload["bundles"][0]["manifest_ref"] = "deployment/locks/missing.json"
    elif mutation == "manifest_escape":
        payload["bundles"][0]["manifest_ref"] = "../escape.json"
    elif mutation == "manifest_hash_invalid":
        payload["bundles"][0]["manifest_sha256"] = "invalid"
    elif mutation == "non_object":
        payload = []
    elif mutation == "invalid_json":
        path.write_text("{", encoding="utf-8")
    if isinstance(payload, dict):
        _rehash(payload, "content_hash")
    if mutation != "invalid_json":
        path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(NslBundleSetError):
        load_nsl_runtime_bundle_set(path, repository_root=root)


def _write_release_with_rehashed_candidate(
    root: Path, payload: dict, candidate: dict
) -> None:
    _rehash(candidate, "candidate_hash")
    _rehash(payload, "registry_hash")
    _write(root / RELEASE_PATH, payload)


@pytest.mark.parametrize(
    "mutation",
    (
        "schema",
        "version",
        "predecessor_fields",
        "predecessor_hash",
        "bundle_fields",
        "bundle_content_hash",
        "candidates_empty",
        "candidate_order",
        "active_conflict",
        "candidate_state",
        "candidate_semantics",
        "candidate_aliases",
        "compile_state",
        "source_fields",
        "bundle_fields_candidate",
        "candidate_relative",
        "candidate_digest",
        "alias_active_unauthorized",
        "alias_multi_owner",
    ),
)
def test_registry_release_shape_semantic_and_alias_failures_are_rejected(
    tmp_path: Path, mutation: str
) -> None:
    root = _copy_release_tree(tmp_path)
    path = root / RELEASE_PATH
    payload = _json(path)
    first = payload["candidate_admissions"][0]
    if mutation == "schema":
        payload["schema_version"] = "unsupported"
    elif mutation == "version":
        payload["registry_version"] = 0
    elif mutation == "predecessor_fields":
        payload["predecessor_registry"].pop("registry_hash")
    elif mutation == "predecessor_hash":
        payload["predecessor_registry"]["registry_hash"] = "sha256:" + "a" * 64
    elif mutation == "bundle_fields":
        payload["bundle_set"].pop("content_hash")
    elif mutation == "bundle_content_hash":
        payload["bundle_set"]["content_hash"] = "sha256:" + "b" * 64
    elif mutation == "candidates_empty":
        payload["candidate_admissions"] = []
    elif mutation == "candidate_order":
        payload["candidate_admissions"] = list(
            reversed(payload["candidate_admissions"])
        )
    elif mutation == "active_conflict":
        first["capability_id"] = "FINANCE.CREATE_VOUCHER_DRAFT"
        payload["candidate_admissions"].sort(key=lambda item: item["capability_id"])
        _rehash(first, "candidate_hash")
    elif mutation == "candidate_state":
        first["admission_state"] = "ACTIVE"
        _rehash(first, "candidate_hash")
    elif mutation == "candidate_semantics":
        first["operation_semantics"] = "GENERATE"
        _rehash(first, "candidate_hash")
    elif mutation == "candidate_aliases":
        first["compatibility_aliases"] = ["DUP", "DUP"]
        _rehash(first, "candidate_hash")
    elif mutation == "compile_state":
        first["skill_source"]["compile_state"] = "COMPILED"
        _rehash(first, "candidate_hash")
    elif mutation == "source_fields":
        first["skill_source"].pop("pack_id")
        _rehash(first, "candidate_hash")
    elif mutation == "bundle_fields_candidate":
        first["bundle_lock"].pop("bundle_id")
        _rehash(first, "candidate_hash")
    elif mutation == "candidate_relative":
        first["skill_source"]["source_manifest_ref"] = "../escape.json"
        _rehash(first, "candidate_hash")
    elif mutation == "candidate_digest":
        first["skill_source"]["source_manifest_digest"] = "invalid"
        _rehash(first, "candidate_hash")
    elif mutation == "alias_active_unauthorized":
        first["compatibility_aliases"] = ["FINANCE.CREATE_VOUCHER_DRAFT"]
        _rehash(first, "candidate_hash")
    elif mutation == "alias_multi_owner":
        first["compatibility_aliases"] = ["sharedAlias"]
        second = payload["candidate_admissions"][1]
        second["compatibility_aliases"] = ["sharedAlias"]
        _rehash(first, "candidate_hash")
        _rehash(second, "candidate_hash")
    _rehash(payload, "registry_hash")
    _write(path, payload)

    with pytest.raises(ProductCapabilityRegistryReleaseError) as raised:
        _load_release(root)
    assert str(raised.value)


def test_registry_release_rejects_invalid_predecessor_and_bundle_set(
    tmp_path: Path,
) -> None:
    root = _copy_release_tree(tmp_path)
    release_path = root / RELEASE_PATH
    payload = _json(release_path)
    predecessor_path = (
        root / "deployment/environments/ae-product-capability-registry.v1.json"
    )
    predecessor = _json(predecessor_path)
    predecessor["registry_hash"] = "sha256:" + "c" * 64
    _write(predecessor_path, predecessor)
    payload["predecessor_registry"]["sha256"] = _byte_hash(predecessor_path)
    _rehash(payload, "registry_hash")
    _write(release_path, payload)
    with pytest.raises(ProductCapabilityRegistryReleaseError):
        _load_release(root)

    root = _copy_release_tree(tmp_path / "bundle")
    release_path = root / RELEASE_PATH
    payload = _json(release_path)
    bundle_path = root / BUNDLE_SET_PATH
    bundle = _json(bundle_path)
    bundle["schema_version"] = "unsupported"
    _rehash(bundle, "content_hash")
    _write(bundle_path, bundle)
    payload["bundle_set"]["sha256"] = _byte_hash(bundle_path)
    payload["bundle_set"]["content_hash"] = bundle["content_hash"]
    _rehash(payload, "registry_hash")
    _write(release_path, payload)
    with pytest.raises(ProductCapabilityRegistryReleaseError):
        _load_release(root)


def test_registry_release_references_cannot_escape_or_disappear(
    tmp_path: Path,
) -> None:
    for mutation in ("escape", "missing"):
        root = _copy_release_tree(tmp_path / mutation)
        path = root / RELEASE_PATH
        payload = _json(path)
        payload["predecessor_registry"]["path"] = (
            "../escape.json"
            if mutation == "escape"
            else "deployment/environments/missing.json"
        )
        _rehash(payload, "registry_hash")
        _write(path, payload)
        with pytest.raises(ProductCapabilityRegistryReleaseError):
            _load_release(root)


def test_release_builder_rejects_non_object_source(tmp_path: Path) -> None:
    root = _copy_release_tree(tmp_path)
    path = root / "deployment/locks/nsl-v0.2.1-wheel.json"
    path.write_text("[]\n", encoding="utf-8")
    with pytest.raises(TypeError):
        build_w70_registry_release_artifacts(root)
