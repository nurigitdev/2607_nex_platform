from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import jsonschema
import pytest
from mybee_ax.integrations.nex_skill_packs import (
    DEFAULT_SKILL_PACK_ROOT,
    SKILL_COMPILE_STATE,
    SKILL_PACK_SOURCE_STATE,
    SkillPackAdmissionError,
    calculate_skill_pack_bindings_digest,
    calculate_skill_pack_manifest_digest,
    load_skill_pack_manifests,
)

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_SCHEMA_PATH = ROOT / "domains/mybee/skills/skill_pack_manifest.schema.json"
BINDINGS_SCHEMA_PATH = ROOT / "domains/mybee/skills/skill_pack_bindings.schema.json"
PACK_DIRECTORIES = ("d04_accounting", "d12_project")


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _byte_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _copy_skill_root(tmp_path: Path) -> Path:
    target = tmp_path / "skills"
    shutil.copytree(DEFAULT_SKILL_PACK_ROOT, target)
    return target


def _manifest_path(root: Path, directory: str = "d04_accounting") -> Path:
    return root / directory / "manifest.v1.json"


def _catalog_path(root: Path, directory: str = "d04_accounting") -> Path:
    return root / directory / "tool_bindings.v1.json"


def _rehash_manifest(value: dict) -> dict:
    value["release_attestation"]["content_digest"] = (
        calculate_skill_pack_manifest_digest(value)
    )
    return value


def _rehash_catalog(value: dict) -> dict:
    value["release_attestation"]["content_digest"] = (
        calculate_skill_pack_bindings_digest(value)
    )
    return value


def _sync_catalog(root: Path, catalog: dict, directory: str = "d04_accounting") -> None:
    catalog_path = _catalog_path(root, directory)
    _write_json(catalog_path, _rehash_catalog(catalog))
    manifest_path = _manifest_path(root, directory)
    manifest = _json(manifest_path)
    sha = _byte_hash(catalog_path)
    manifest["binding_catalog"]["sha256"] = sha
    manifest["binding_catalog"]["content_digest"] = catalog["release_attestation"][
        "content_digest"
    ]
    manifest["source_files"] = [
        {"path": manifest["binding_catalog"]["path"], "sha256": sha}
    ]
    _write_json(manifest_path, _rehash_manifest(manifest))


def _error_for(root: Path, **kwargs) -> SkillPackAdmissionError:
    with pytest.raises(SkillPackAdmissionError) as raised:
        load_skill_pack_manifests(root, **kwargs)
    return raised.value


def test_w70_candidate_skill_packs_match_schemas_digests_and_partition() -> None:
    manifest_schema = _json(MANIFEST_SCHEMA_PATH)
    binding_schema = _json(BINDINGS_SCHEMA_PATH)
    for directory in PACK_DIRECTORIES:
        jsonschema.Draft202012Validator(manifest_schema).validate(
            _json(_manifest_path(DEFAULT_SKILL_PACK_ROOT, directory))
        )
        jsonschema.Draft202012Validator(binding_schema).validate(
            _json(_catalog_path(DEFAULT_SKILL_PACK_ROOT, directory))
        )

    d04, d12 = load_skill_pack_manifests()
    assert d04.pack_id == "MYBEE.D04.ACCOUNTING"
    assert d12.pack_id == "MYBEE.D12.PROJECT"
    assert len(d04.bindings) == 13
    assert len(d12.bindings) == 5
    assert (
        sum(item.contract_typing_state == "FULLY_TYPED" for item in d04.bindings) == 8
    )
    assert (
        sum(item.contract_typing_state == "FULLY_TYPED" for item in d12.bindings) == 3
    )
    assert (
        len(
            {
                item.canonical_operation_id
                for pack in (d04, d12)
                for item in pack.bindings
            }
        )
        == 18
    )

    for pack in (d04, d12):
        directory = (
            "d04_accounting" if pack.domain_code == "D04_ACCOUNTING" else "d12_project"
        )
        assert pack.activation_state == "CANDIDATE"
        assert pack.runtime_selectable is False
        assert pack.source_state == SKILL_PACK_SOURCE_STATE
        assert pack.binding_catalog_sha256 == _byte_hash(
            ROOT / pack.binding_catalog_path
        )
        assert pack.content_digest == calculate_skill_pack_manifest_digest(
            _json(_manifest_path(DEFAULT_SKILL_PACK_ROOT, directory))
        )
        assert pack.binding_catalog_digest == calculate_skill_pack_bindings_digest(
            _json(_catalog_path(DEFAULT_SKILL_PACK_ROOT, directory))
        )
        for binding in pack.bindings:
            assert binding.skill_id == binding.canonical_operation_id
            assert binding.compile_state == SKILL_COMPILE_STATE
            assert binding.runtime_selectable is False
            assert "AE_CAPABILITY_REGISTRY_RELEASE_REQUIRED" in (
                binding.activation_blockers
            )
            assert "PROTECTED_ACTIVATION_GATE_REQUIRED" in (binding.activation_blockers)


def test_w70_candidate_skill_pack_trust_and_contract_blockers_are_explicit() -> None:
    d04, d12 = load_skill_pack_manifests()
    assert d04.trust_policy_id == "policy://nex/ae/mybee/d04-accounting/v1"
    assert d12.trust_policy_id == "policy://nex/ae/mybee/d12-project/v1"

    fx = next(
        item
        for item in d04.bindings
        if item.canonical_operation_id == "FINANCE.FX_RATE.RESOLVE"
    )
    assert fx.contract_typing_state == "STATUS_ONLY"
    assert fx.execution_policy["idempotency"] == "NOT_APPLICABLE"
    assert fx.execution_policy["request_hash"] == "QUERY_HASH_REQUIRED"
    assert fx.activation_blockers[0] == "CANONICAL_SUCCESS_RESPONSE_SCHEMA_REQUIRED"

    candidate = next(
        item
        for item in d04.bindings
        if item.canonical_operation_id == "FINANCE.VOUCHER_CANDIDATE.GET_V2"
    )
    assert candidate.inventory_activation_state == "DEFERRED"
    assert candidate.activation_blockers[:2] == (
        "PROJECT_OA_READ_POLICY_REQUIRED",
        "CANONICAL_SUCCESS_RESPONSE_SCHEMA_REQUIRED",
    )

    posting = next(
        item
        for item in d04.bindings
        if item.canonical_operation_id == "FINANCE.VOUCHER.APPROVE_AND_POST"
    )
    assert posting.contract_typing_state == "FULLY_TYPED"
    assert posting.execution_policy == {
        "idempotency": "REQUIRED",
        "request_hash": "PAYLOAD_HASH_REQUIRED",
        "verification": "REQUIRED_BEFORE_ACTIVATION",
        "unknown_outcome": "RECONCILE_BEFORE_RETRY",
        "timeout_profile": "PENDING_ACTIVATION_SLICE",
    }


def test_w70_candidate_packs_preserve_deployed_capabilities_and_limit_nsl_sources() -> (
    None
):
    registry = _json(
        ROOT / "deployment/environments/ae-product-capability-registry.v1.json"
    )

    assert registry["registry_version"] == 1
    assert [
        item["capability"]["capability_id"] for item in registry["registrations"]
    ] == ["FINANCE.CREATE_VOUCHER_DRAFT"]
    assert {
        path.relative_to(DEFAULT_SKILL_PACK_ROOT).as_posix()
        for path in DEFAULT_SKILL_PACK_ROOT.glob("d*/*.ns")
    } == {
        "d04_accounting/journal_posting.v1.ns",
        "d04_accounting/journal_posting.v1_0_1.ns",
        "d12_project/work_code_context.v1.ns",
    }


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    (
        ("root_fields", "SKILL_PACK_MANIFEST_FIELDS_INVALID"),
        ("header", "SKILL_PACK_MANIFEST_HEADER_INVALID"),
        ("authority_fields", "SKILL_PACK_AUTHORITY_FIELDS_INVALID"),
        ("authority_ref_fields", "SKILL_PACK_AUTHORITY_REF_INVALID"),
        ("authority_ref", "SKILL_PACK_AUTHORITY_REF_MISMATCH"),
        ("wheel_fields", "SKILL_PACK_WHEEL_REF_INVALID"),
        ("wheel_ref", "SKILL_PACK_WHEEL_REF_MISMATCH"),
        ("runtime", "SKILL_PACK_RUNTIME_INVALID"),
        ("trust", "SKILL_PACK_TRUST_INVALID"),
        ("catalog_ref_fields", "SKILL_PACK_CATALOG_REF_INVALID"),
        ("catalog_path", "SKILL_PACK_CATALOG_PATH_INVALID"),
        ("catalog_sha", "SKILL_PACK_CATALOG_SHA_MISMATCH"),
        ("source_files", "SKILL_PACK_SOURCE_FILES_INVALID"),
        ("catalog_digest", "SKILL_PACK_CATALOG_DIGEST_MISMATCH"),
        ("attestation_fields", "SKILL_PACK_ATTESTATION_FIELDS_INVALID"),
        ("attestation", "SKILL_PACK_MANIFEST_DIGEST_MISMATCH"),
    ),
)
def test_w70_skill_pack_manifest_loader_fails_closed(
    tmp_path: Path, mutation: str, expected_code: str
) -> None:
    root = _copy_skill_root(tmp_path)
    path = _manifest_path(root)
    value = _json(path)
    if mutation == "root_fields":
        value["unexpected"] = True
    elif mutation == "header":
        value["runtime_selectable"] = True
    elif mutation == "authority_fields":
        value["authority"]["unexpected"] = True
    elif mutation == "authority_ref_fields":
        value["authority"]["tool_inventory"]["unexpected"] = True
    elif mutation == "authority_ref":
        value["authority"]["tool_inventory"]["content_digest"] = "sha256:" + "0" * 64
    elif mutation == "wheel_fields":
        value["authority"]["nsl_wheel_lock"]["unexpected"] = True
    elif mutation == "wheel_ref":
        value["authority"]["nsl_wheel_lock"]["package_version"] = "0.2.0"
    elif mutation == "runtime":
        value["runtime"]["backend_profile"] = "PROCESS_ISOLATED"
    elif mutation == "trust":
        value["trust"]["signature_status"] = "SIGNED"
    elif mutation == "catalog_ref_fields":
        value["binding_catalog"]["unexpected"] = True
    elif mutation == "catalog_path":
        value["binding_catalog"]["path"] = "other.json"
    elif mutation == "catalog_sha":
        value["binding_catalog"]["sha256"] = "sha256:" + "0" * 64
    elif mutation == "source_files":
        value["source_files"] = []
    elif mutation == "catalog_digest":
        value["binding_catalog"]["content_digest"] = "sha256:" + "0" * 64
    elif mutation == "attestation_fields":
        value["release_attestation"]["unexpected"] = True
    elif mutation == "attestation":
        value["release_attestation"]["content_digest"] = "sha256:" + "0" * 64
        _write_json(path, value)
        assert _error_for(root).code == expected_code
        return
    _write_json(path, _rehash_manifest(value))
    assert _error_for(root).code == expected_code


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    (
        ("root_fields", "SKILL_PACK_BINDINGS_FIELDS_INVALID"),
        ("header", "SKILL_PACK_BINDINGS_HEADER_INVALID"),
        ("count", "SKILL_PACK_BINDINGS_COUNT_INVALID"),
        ("binding_fields", "SKILL_PACK_BINDING_FIELDS_INVALID"),
        ("binding", "SKILL_PACK_BINDING_MISMATCH"),
        ("order", "SKILL_PACK_BINDING_MISMATCH"),
        ("attestation_fields", "SKILL_PACK_ATTESTATION_FIELDS_INVALID"),
        ("attestation", "SKILL_PACK_BINDINGS_DIGEST_MISMATCH"),
    ),
)
def test_w70_skill_pack_binding_loader_fails_closed(
    tmp_path: Path, mutation: str, expected_code: str
) -> None:
    root = _copy_skill_root(tmp_path)
    catalog = _json(_catalog_path(root))
    if mutation == "root_fields":
        catalog["unexpected"] = True
    elif mutation == "header":
        catalog["pack_version"] = "2.0.0"
    elif mutation == "count":
        catalog["bindings"].pop()
    elif mutation == "binding_fields":
        catalog["bindings"][0]["unexpected"] = True
    elif mutation == "binding":
        catalog["bindings"][0]["runtime_selectable"] = True
    elif mutation == "order":
        catalog["bindings"].reverse()
    elif mutation == "attestation_fields":
        catalog["release_attestation"]["unexpected"] = True
    elif mutation == "attestation":
        catalog["release_attestation"]["content_digest"] = "sha256:" + "0" * 64
        catalog_path = _catalog_path(root)
        _write_json(catalog_path, catalog)
        manifest_path = _manifest_path(root)
        manifest = _json(manifest_path)
        sha = _byte_hash(catalog_path)
        manifest["binding_catalog"]["sha256"] = sha
        manifest["source_files"][0]["sha256"] = sha
        _write_json(manifest_path, _rehash_manifest(manifest))
        assert _error_for(root).code == expected_code
        return
    _sync_catalog(root, catalog)
    assert _error_for(root).code == expected_code


def test_w70_skill_pack_loader_rejects_wheel_and_source_io_drift(
    tmp_path: Path,
) -> None:
    root = _copy_skill_root(tmp_path)
    wheel_path = tmp_path / "wheel-lock.json"
    wheel = _json(ROOT / "deployment/locks/nsl-v0.2.1-wheel.json")
    wheel["package_version"] = "0.2.0"
    _write_json(wheel_path, wheel)
    manifest_path = _manifest_path(root)
    manifest = _json(manifest_path)
    manifest["authority"]["nsl_wheel_lock"]["sha256"] = _byte_hash(wheel_path)
    _write_json(manifest_path, _rehash_manifest(manifest))
    assert (
        _error_for(root, wheel_lock_path=wheel_path).code
        == "SKILL_PACK_WHEEL_VERSION_MISMATCH"
    )

    missing_root = tmp_path / "missing"
    assert _error_for(missing_root).code == "SKILL_PACK_SOURCE_UNREADABLE"

    root = _copy_skill_root(tmp_path / "invalid")
    _manifest_path(root).write_text("{", encoding="utf-8")
    assert _error_for(root).code == "SKILL_PACK_SOURCE_INVALID_JSON"

    root = _copy_skill_root(tmp_path / "object")
    _write_json(_manifest_path(root), [])
    assert _error_for(root).code == "SKILL_PACK_OBJECT_REQUIRED"


def test_w70_skill_pack_structural_schema_rejects_activation_and_local_schema() -> None:
    manifest_schema = _json(MANIFEST_SCHEMA_PATH)
    binding_schema = _json(BINDINGS_SCHEMA_PATH)
    manifest = _json(_manifest_path(DEFAULT_SKILL_PACK_ROOT))
    binding_catalog = _json(_catalog_path(DEFAULT_SKILL_PACK_ROOT))

    manifest["runtime_selectable"] = True
    assert list(jsonschema.Draft202012Validator(manifest_schema).iter_errors(manifest))

    binding_catalog["bindings"][0]["input_contract_ref"] = (
        "domains/mybee/skills/local.schema.json"
    )
    assert list(
        jsonschema.Draft202012Validator(binding_schema).iter_errors(binding_catalog)
    )
