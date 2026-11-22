"""Fail-closed admission for W70 candidate D04/D12 Skill-Pack sources."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

from .nex_tool_contracts import (
    ToolContractCatalog,
    load_tool_contract_catalog,
)
from .nex_tool_inventory import ToolIdentity, ToolInventory, load_tool_inventory

SKILL_PACK_MANIFEST_SCHEMA_VERSION = "nex.mybee.skill-pack-manifest.v1"
SKILL_PACK_BINDINGS_SCHEMA_VERSION = "nex.mybee.skill-pack-bindings.v1"
SKILL_PACK_VERSION = "1.0.0"
SKILL_VERSION = "1.0.0"
SKILL_PACK_ACTIVATION_STATE = "CANDIDATE"
SKILL_PACK_SOURCE_STATE = "DESCRIPTOR_ONLY_NOT_COMPILED"
SKILL_COMPILE_STATE = "PENDING_S8_01E"

_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_SKILL_PACK_ROOT = _ROOT / "domains/mybee/skills"
_INVENTORY_PATH = "domains/mybee/skills/tool_inventory.v1.json"
_CONTRACT_ADMISSION_PATH = (
    "contracts/admissions/nex_eos/w70_tool_contract_admission.v1.json"
)
_WHEEL_LOCK_PATH = "deployment/locks/nsl-v0.2.1-wheel.json"

_PACK_SPECS = MappingProxyType(
    {
        "D04_ACCOUNTING": {
            "directory": "d04_accounting",
            "pack_id": "MYBEE.D04.ACCOUNTING",
            "trust_policy_id": "policy://nex/ae/mybee/d04-accounting/v1",
            "tool_count": 13,
        },
        "D12_PROJECT": {
            "directory": "d12_project",
            "pack_id": "MYBEE.D12.PROJECT",
            "trust_policy_id": "policy://nex/ae/mybee/d12-project/v1",
            "tool_count": 5,
        },
    }
)

_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "pack_id",
        "pack_version",
        "domain_code",
        "activation_state",
        "runtime_selectable",
        "source_state",
        "authority",
        "runtime",
        "trust",
        "binding_catalog",
        "source_files",
        "release_attestation",
    }
)
_BINDING_ROOT_FIELDS = frozenset(
    {
        "schema_version",
        "pack_id",
        "pack_version",
        "domain_code",
        "bindings",
        "release_attestation",
    }
)
_BINDING_FIELDS = frozenset(
    {
        "skill_id",
        "skill_version",
        "canonical_operation_id",
        "provider_operation_id",
        "invocation_semantics",
        "approval_requirement",
        "inventory_activation_state",
        "service_scope",
        "oa_action",
        "contract_admission_ref",
        "contract_typing_state",
        "input_contract_ref",
        "output_contract_refs",
        "compile_state",
        "runtime_selectable",
        "execution_policy",
        "activation_blockers",
    }
)


class SkillPackAdmissionError(ValueError):
    """Raised when a candidate Skill-Pack no longer matches admitted sources."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


@dataclass(frozen=True)
class SkillPackBinding:
    skill_id: str
    skill_version: str
    canonical_operation_id: str
    provider_operation_id: str
    invocation_semantics: str
    approval_requirement: str
    inventory_activation_state: str
    service_scope: str
    oa_action: str
    contract_admission_ref: str
    contract_typing_state: str
    input_contract_ref: str
    output_contract_refs: tuple[str, ...]
    compile_state: str
    runtime_selectable: bool
    execution_policy: Mapping[str, str]
    activation_blockers: tuple[str, ...]


@dataclass(frozen=True)
class SkillPackManifest:
    pack_id: str
    pack_version: str
    domain_code: str
    activation_state: str
    runtime_selectable: bool
    source_state: str
    trust_policy_id: str
    binding_catalog_path: str
    binding_catalog_sha256: str
    binding_catalog_digest: str
    content_digest: str
    bindings: tuple[SkillPackBinding, ...]


def calculate_skill_pack_manifest_digest(manifest: Mapping[str, Any]) -> str:
    return semantic_sha256_hash_ref(
        {key: value for key, value in manifest.items() if key != "release_attestation"}
    )


def calculate_skill_pack_bindings_digest(catalog: Mapping[str, Any]) -> str:
    return semantic_sha256_hash_ref(
        {key: value for key, value in catalog.items() if key != "release_attestation"}
    )


def load_skill_pack_manifests(
    root: Path = DEFAULT_SKILL_PACK_ROOT,
    *,
    inventory: ToolInventory | None = None,
    contracts: ToolContractCatalog | None = None,
    wheel_lock_path: Path | None = None,
) -> tuple[SkillPackManifest, ...]:
    admitted_inventory = inventory or load_tool_inventory()
    admitted_contracts = contracts or load_tool_contract_catalog()
    resolved_wheel_lock = wheel_lock_path or (_ROOT / _WHEEL_LOCK_PATH)
    manifests = tuple(
        _load_pack(
            root=root,
            domain_code=domain_code,
            spec=spec,
            inventory=admitted_inventory,
            contracts=admitted_contracts,
            wheel_lock_path=resolved_wheel_lock,
        )
        for domain_code, spec in _PACK_SPECS.items()
    )
    operation_ids = [
        binding.canonical_operation_id
        for manifest in manifests
        for binding in manifest.bindings
    ]
    inventory_ids = [item.canonical_operation_id for item in admitted_inventory.tools]
    if len(operation_ids) != len(set(operation_ids)) or set(operation_ids) != set(
        inventory_ids
    ):
        raise SkillPackAdmissionError(
            "SKILL_PACK_INVENTORY_PARTITION_INVALID",
            str(sorted(set(operation_ids) ^ set(inventory_ids))),
        )
    return manifests


def _load_pack(
    *,
    root: Path,
    domain_code: str,
    spec: Mapping[str, object],
    inventory: ToolInventory,
    contracts: ToolContractCatalog,
    wheel_lock_path: Path,
) -> SkillPackManifest:
    directory = str(spec["directory"])
    path = root / directory / "manifest.v1.json"
    manifest = _mapping(_load_json(path), "manifest")
    if set(manifest) != _MANIFEST_FIELDS:
        raise SkillPackAdmissionError(
            "SKILL_PACK_MANIFEST_FIELDS_INVALID", str(sorted(manifest))
        )
    _require_manifest_header(manifest, domain_code=domain_code, spec=spec)
    _require_authority(
        manifest.get("authority"),
        inventory=inventory,
        contracts=contracts,
        wheel_lock_path=wheel_lock_path,
    )
    _require_runtime(manifest.get("runtime"))
    trust_policy_id = _require_trust(manifest.get("trust"), spec=spec)

    catalog_ref = _mapping(manifest.get("binding_catalog"), "binding_catalog")
    expected_catalog_path = f"domains/mybee/skills/{directory}/tool_bindings.v1.json"
    if set(catalog_ref) != {"path", "sha256", "content_digest"}:
        raise SkillPackAdmissionError(
            "SKILL_PACK_CATALOG_REF_INVALID", str(sorted(catalog_ref))
        )
    if catalog_ref.get("path") != expected_catalog_path:
        raise SkillPackAdmissionError(
            "SKILL_PACK_CATALOG_PATH_INVALID", str(catalog_ref.get("path"))
        )
    catalog_path = root / directory / "tool_bindings.v1.json"
    observed_catalog_sha = _byte_hash_ref(catalog_path)
    if catalog_ref.get("sha256") != observed_catalog_sha:
        raise SkillPackAdmissionError(
            "SKILL_PACK_CATALOG_SHA_MISMATCH", expected_catalog_path
        )
    source_files = manifest.get("source_files")
    if source_files != [
        {"path": expected_catalog_path, "sha256": observed_catalog_sha}
    ]:
        raise SkillPackAdmissionError(
            "SKILL_PACK_SOURCE_FILES_INVALID", str(source_files)
        )

    catalog = _mapping(_load_json(catalog_path), "binding_catalog")
    bindings, catalog_digest = _load_bindings(
        catalog,
        domain_code=domain_code,
        spec=spec,
        inventory=inventory,
        contracts=contracts,
    )
    if catalog_ref.get("content_digest") != catalog_digest:
        raise SkillPackAdmissionError(
            "SKILL_PACK_CATALOG_DIGEST_MISMATCH", expected_catalog_path
        )
    content_digest = _require_attestation(
        manifest,
        calculator=calculate_skill_pack_manifest_digest,
        code="SKILL_PACK_MANIFEST_DIGEST_MISMATCH",
    )
    return SkillPackManifest(
        pack_id=str(spec["pack_id"]),
        pack_version=SKILL_PACK_VERSION,
        domain_code=domain_code,
        activation_state=SKILL_PACK_ACTIVATION_STATE,
        runtime_selectable=False,
        source_state=SKILL_PACK_SOURCE_STATE,
        trust_policy_id=trust_policy_id,
        binding_catalog_path=expected_catalog_path,
        binding_catalog_sha256=observed_catalog_sha,
        binding_catalog_digest=catalog_digest,
        content_digest=content_digest,
        bindings=bindings,
    )


def _require_manifest_header(
    manifest: Mapping[str, Any], *, domain_code: str, spec: Mapping[str, object]
) -> None:
    expected = {
        "schema_version": SKILL_PACK_MANIFEST_SCHEMA_VERSION,
        "pack_id": spec["pack_id"],
        "pack_version": SKILL_PACK_VERSION,
        "domain_code": domain_code,
        "activation_state": SKILL_PACK_ACTIVATION_STATE,
        "runtime_selectable": False,
        "source_state": SKILL_PACK_SOURCE_STATE,
    }
    for field, value in expected.items():
        if manifest.get(field) != value:
            raise SkillPackAdmissionError(
                "SKILL_PACK_MANIFEST_HEADER_INVALID",
                f"{field}={manifest.get(field)!r}",
            )


def _require_authority(
    value: object,
    *,
    inventory: ToolInventory,
    contracts: ToolContractCatalog,
    wheel_lock_path: Path,
) -> None:
    authority = _mapping(value, "authority")
    if set(authority) != {
        "tool_inventory",
        "tool_contract_admission",
        "nsl_wheel_lock",
    }:
        raise SkillPackAdmissionError(
            "SKILL_PACK_AUTHORITY_FIELDS_INVALID", str(sorted(authority))
        )
    _require_content_ref(
        authority["tool_inventory"],
        expected_path=_INVENTORY_PATH,
        expected_digest=inventory.content_digest,
        label="tool_inventory",
    )
    _require_content_ref(
        authority["tool_contract_admission"],
        expected_path=_CONTRACT_ADMISSION_PATH,
        expected_digest=contracts.content_digest,
        label="tool_contract_admission",
    )
    wheel = _mapping(authority["nsl_wheel_lock"], "nsl_wheel_lock")
    if set(wheel) != {"path", "sha256", "package_version"}:
        raise SkillPackAdmissionError(
            "SKILL_PACK_WHEEL_REF_INVALID", str(sorted(wheel))
        )
    if (
        wheel.get("path") != _WHEEL_LOCK_PATH
        or wheel.get("sha256") != _byte_hash_ref(wheel_lock_path)
        or wheel.get("package_version") != "0.2.1"
    ):
        raise SkillPackAdmissionError(
            "SKILL_PACK_WHEEL_REF_MISMATCH", str(wheel.get("path"))
        )
    wheel_lock = _mapping(_load_json(wheel_lock_path), "nsl_wheel_lock")
    if wheel_lock.get("package_version") != "0.2.1":
        raise SkillPackAdmissionError(
            "SKILL_PACK_WHEEL_VERSION_MISMATCH",
            str(wheel_lock.get("package_version")),
        )


def _require_content_ref(
    value: object, *, expected_path: str, expected_digest: str, label: str
) -> None:
    reference = _mapping(value, label)
    if set(reference) != {"path", "content_digest"}:
        raise SkillPackAdmissionError("SKILL_PACK_AUTHORITY_REF_INVALID", label)
    if (
        reference.get("path") != expected_path
        or reference.get("content_digest") != expected_digest
    ):
        raise SkillPackAdmissionError("SKILL_PACK_AUTHORITY_REF_MISMATCH", label)


def _require_runtime(value: object) -> None:
    runtime = _mapping(value, "runtime")
    expected = {
        "language_version": "0.2",
        "package_version": "0.2.1",
        "backend_profile": "NSL_V02_IN_PROCESS",
        "package_requirement": "SIGNED_TRUSTED_ACTIVE",
    }
    if dict(runtime) != expected:
        raise SkillPackAdmissionError("SKILL_PACK_RUNTIME_INVALID", str(runtime))


def _require_trust(value: object, *, spec: Mapping[str, object]) -> str:
    trust = _mapping(value, "trust")
    expected = {
        "publisher": "nex-mybee-ax",
        "trust_policy_id": spec["trust_policy_id"],
        "signing_key_id": None,
        "signature_status": "NOT_SIGNED",
        "governance_status": "CANDIDATE",
        "activation_requires": "S8_01D_REGISTRY_AND_S8_01E_GATE",
    }
    if dict(trust) != expected:
        raise SkillPackAdmissionError("SKILL_PACK_TRUST_INVALID", str(trust))
    return str(trust["trust_policy_id"])


def _load_bindings(
    catalog: Mapping[str, Any],
    *,
    domain_code: str,
    spec: Mapping[str, object],
    inventory: ToolInventory,
    contracts: ToolContractCatalog,
) -> tuple[tuple[SkillPackBinding, ...], str]:
    if set(catalog) != _BINDING_ROOT_FIELDS:
        raise SkillPackAdmissionError(
            "SKILL_PACK_BINDINGS_FIELDS_INVALID", str(sorted(catalog))
        )
    expected_header = {
        "schema_version": SKILL_PACK_BINDINGS_SCHEMA_VERSION,
        "pack_id": spec["pack_id"],
        "pack_version": SKILL_PACK_VERSION,
        "domain_code": domain_code,
    }
    if any(catalog.get(key) != value for key, value in expected_header.items()):
        raise SkillPackAdmissionError("SKILL_PACK_BINDINGS_HEADER_INVALID", domain_code)
    raw_bindings = catalog.get("bindings")
    expected_tools = tuple(
        item for item in inventory.tools if item.domain_pack == domain_code
    )
    if not isinstance(raw_bindings, list) or len(raw_bindings) != int(
        spec["tool_count"]
    ):
        raise SkillPackAdmissionError("SKILL_PACK_BINDINGS_COUNT_INVALID", domain_code)
    contract_index = {
        item.canonical_operation_id: (index, item)
        for index, item in enumerate(contracts.contracts)
    }
    bindings = tuple(
        _parse_binding(
            raw,
            identity=identity,
            contract_index=contract_index,
        )
        for raw, identity in zip(raw_bindings, expected_tools, strict=True)
    )
    operation_ids = [item.canonical_operation_id for item in bindings]
    expected_ids = [item.canonical_operation_id for item in expected_tools]
    if operation_ids != expected_ids or operation_ids != sorted(operation_ids):
        raise SkillPackAdmissionError(
            "SKILL_PACK_BINDINGS_ORDER_INVALID", str(operation_ids)
        )
    digest = _require_attestation(
        catalog,
        calculator=calculate_skill_pack_bindings_digest,
        code="SKILL_PACK_BINDINGS_DIGEST_MISMATCH",
    )
    return bindings, digest


def _parse_binding(
    value: object,
    *,
    identity: ToolIdentity,
    contract_index: Mapping[str, tuple[int, Any]],
) -> SkillPackBinding:
    binding = _mapping(value, "binding")
    if set(binding) != _BINDING_FIELDS:
        raise SkillPackAdmissionError(
            "SKILL_PACK_BINDING_FIELDS_INVALID", str(sorted(binding))
        )
    index, contract = contract_index[identity.canonical_operation_id]
    expected = _expected_binding(identity, contract=contract, contract_index=index)
    if dict(binding) != expected:
        raise SkillPackAdmissionError(
            "SKILL_PACK_BINDING_MISMATCH", identity.canonical_operation_id
        )
    return SkillPackBinding(
        skill_id=str(binding["skill_id"]),
        skill_version=str(binding["skill_version"]),
        canonical_operation_id=identity.canonical_operation_id,
        provider_operation_id=identity.provider_operation_id,
        invocation_semantics=identity.invocation_semantics,
        approval_requirement=identity.approval_requirement,
        inventory_activation_state=identity.activation_state,
        service_scope=identity.service_scope,
        oa_action=identity.oa_action,
        contract_admission_ref=str(binding["contract_admission_ref"]),
        contract_typing_state=str(binding["contract_typing_state"]),
        input_contract_ref=str(binding["input_contract_ref"]),
        output_contract_refs=tuple(binding["output_contract_refs"]),
        compile_state=SKILL_COMPILE_STATE,
        runtime_selectable=False,
        execution_policy=MappingProxyType(dict(binding["execution_policy"])),
        activation_blockers=tuple(binding["activation_blockers"]),
    )


def _expected_binding(
    identity: ToolIdentity, *, contract: Any, contract_index: int
) -> dict:
    fully_typed = contract.fully_typed
    request_ref = contract.request.canonical_schema_ref or (
        f"{_CONTRACT_ADMISSION_PATH}{contract.openapi_operation_ref}#parameters"
    )
    output_refs = sorted(
        {
            item.canonical_schema_ref
            for item in contract.success_responses
            if item.canonical_schema_ref is not None
        }
    )
    blockers = [
        "NSL_SOURCE_AND_COMPILE_REQUIRED",
        "SIGNED_BUNDLE_AND_TRUST_ADMISSION_REQUIRED",
        "AE_CAPABILITY_REGISTRY_RELEASE_REQUIRED",
        "PROTECTED_ACTIVATION_GATE_REQUIRED",
    ]
    if not fully_typed:
        blockers.insert(0, "CANONICAL_SUCCESS_RESPONSE_SCHEMA_REQUIRED")
    if identity.activation_state == "DEFERRED":
        blockers.insert(0, "PROJECT_OA_READ_POLICY_REQUIRED")
    is_write = identity.invocation_semantics == "GOVERNED_WRITE"
    return {
        "skill_id": identity.canonical_operation_id,
        "skill_version": SKILL_VERSION,
        "canonical_operation_id": identity.canonical_operation_id,
        "provider_operation_id": identity.provider_operation_id,
        "invocation_semantics": identity.invocation_semantics,
        "approval_requirement": identity.approval_requirement,
        "inventory_activation_state": identity.activation_state,
        "service_scope": identity.service_scope,
        "oa_action": identity.oa_action,
        "contract_admission_ref": (
            f"{_CONTRACT_ADMISSION_PATH}#/contracts/{contract_index}"
        ),
        "contract_typing_state": "FULLY_TYPED" if fully_typed else "STATUS_ONLY",
        "input_contract_ref": request_ref,
        "output_contract_refs": output_refs,
        "compile_state": SKILL_COMPILE_STATE,
        "runtime_selectable": False,
        "execution_policy": {
            "idempotency": "REQUIRED" if is_write else "NOT_APPLICABLE",
            "request_hash": "PAYLOAD_HASH_REQUIRED"
            if is_write
            else "QUERY_HASH_REQUIRED",
            "verification": (
                "REQUIRED_BEFORE_ACTIVATION" if is_write else "RESULT_HASH_REQUIRED"
            ),
            "unknown_outcome": (
                "RECONCILE_BEFORE_RETRY" if is_write else "NOT_APPLICABLE"
            ),
            "timeout_profile": "PENDING_ACTIVATION_SLICE",
        },
        "activation_blockers": blockers,
    }


def _require_attestation(value: Mapping[str, Any], *, calculator, code: str) -> str:
    attestation = _mapping(value.get("release_attestation"), "release_attestation")
    if set(attestation) != {"content_digest"}:
        raise SkillPackAdmissionError(
            "SKILL_PACK_ATTESTATION_FIELDS_INVALID", str(sorted(attestation))
        )
    expected = calculator(value)
    if attestation.get("content_digest") != expected:
        raise SkillPackAdmissionError(code, str(attestation.get("content_digest")))
    return expected


def _byte_hash_ref(path: Path) -> str:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise SkillPackAdmissionError(
            "SKILL_PACK_SOURCE_UNREADABLE", str(path)
        ) from exc
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SkillPackAdmissionError(
            "SKILL_PACK_SOURCE_UNREADABLE", str(path)
        ) from exc
    except json.JSONDecodeError as exc:
        raise SkillPackAdmissionError(
            "SKILL_PACK_SOURCE_INVALID_JSON", str(path)
        ) from exc


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SkillPackAdmissionError("SKILL_PACK_OBJECT_REQUIRED", field)
    return value
