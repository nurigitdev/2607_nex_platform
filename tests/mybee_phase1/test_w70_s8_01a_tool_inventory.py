from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema
import pytest
import yaml
from mybee_ax.integrations.nex_tool_inventory import (
    TOOL_INVENTORY_STATUS,
    ToolInventoryError,
    calculate_tool_inventory_digest,
    load_tool_inventory,
)
from nex_runtime import (
    DEFAULT_OPERATION_REGISTRY,
    OPERATION_ALIAS_REGISTRY_VERSION,
    PLATFORM_CANONICAL_OPERATIONS,
    W70_CANONICAL_OPERATIONS,
    W70_OPERATION_ALIASES,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

ROOT = Path(__file__).resolve().parents[2]
INVENTORY_PATH = ROOT / "domains/mybee/skills/tool_inventory.v1.json"
SCHEMA_PATH = ROOT / "domains/mybee/skills/tool_inventory.schema.json"
OPENAPI_PATH = ROOT / "contracts/openapi/nex-eos.openapi.yaml"


def _inventory_json() -> dict:
    return json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))


def _rehash(value: dict) -> dict:
    value["release_attestation"]["content_digest"] = (
        calculate_tool_inventory_digest(value)
    )
    return value


def _write_inventory(tmp_path: Path, value: object) -> Path:
    path = tmp_path / "tool-inventory.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _error_for(tmp_path: Path, value: object) -> ToolInventoryError:
    with pytest.raises(ToolInventoryError) as raised:
        load_tool_inventory(_write_inventory(tmp_path, value))
    return raised.value


def _openapi_operations() -> dict[str, tuple[str, dict]]:
    document = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    operations: dict[str, tuple[str, dict]] = {}
    for methods in document["paths"].values():
        for method, operation in methods.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            operation_id = operation.get("operationId")
            if operation_id:
                assert operation_id not in operations
                operations[operation_id] = (method, operation)
    return operations


def test_w70_inventory_matches_schema_digest_and_source_admission() -> None:
    raw = _inventory_json()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    jsonschema.Draft202012Validator(schema).validate(raw)
    inventory = load_tool_inventory()

    assert inventory.inventory_id == "mybee.phase1.w70.canonical-tools"
    assert inventory.inventory_version == "1.0.0"
    assert inventory.revision == 1
    assert inventory.status == TOOL_INVENTORY_STATUS
    assert inventory.registry_version == OPERATION_ALIAS_REGISTRY_VERSION
    assert inventory.content_digest == calculate_tool_inventory_digest(raw)
    assert inventory.content_digest == raw["release_attestation"]["content_digest"]
    assert len(inventory.tools) == 18
    assert sum(item.domain_pack == "D04_ACCOUNTING" for item in inventory.tools) == 13
    assert sum(item.domain_pack == "D12_PROJECT" for item in inventory.tools) == 5
    assert sum(item.activation_state == "ACTIVE_COMPATIBILITY" for item in inventory.tools) == 1
    assert sum(item.activation_state == "DEFERRED" for item in inventory.tools) == 1
    assert sum(item.activation_state == "CANDIDATE" for item in inventory.tools) == 16


def test_w70_shared_registry_resolves_canonical_and_compatibility_identities() -> None:
    inventory = load_tool_inventory()

    assert OPERATION_ALIAS_REGISTRY_VERSION == "mybee-w70-s8-01a.v1"
    assert W70_CANONICAL_OPERATIONS <= PLATFORM_CANONICAL_OPERATIONS
    assert DEFAULT_OPERATION_REGISTRY.canonical_operations == (
        PLATFORM_CANONICAL_OPERATIONS
    )
    assert DEFAULT_OPERATION_REGISTRY.aliases["createEosVoucherDraft"] == (
        "FINANCE.VOUCHER_DRAFT.CREATE"
    )
    assert dict(W70_OPERATION_ALIASES) == {
        "FINANCE.VOUCHER.APPROVE_AND_POST.ADMISSION": (
            "FINANCE.VOUCHER_POSTING.ADMIT"
        ),
        "createEosVoucherDraft": "FINANCE.VOUCHER_DRAFT.CREATE",
    }
    assert inventory.resolve("FINANCE.CREATE_VOUCHER_DRAFT").canonical_operation_id == (
        "FINANCE.VOUCHER_DRAFT.CREATE"
    )
    assert inventory.resolve("createEosVoucherDraft").canonical_operation_id == (
        "FINANCE.VOUCHER_DRAFT.CREATE"
    )
    assert inventory.resolve(
        "FINANCE.VOUCHER.APPROVE_AND_POST.ADMISSION"
    ).canonical_operation_id == "FINANCE.VOUCHER_POSTING.ADMIT"
    assert DEFAULT_OPERATION_REGISTRY.resolve(
        "FINANCE.PROJECT_PNL.GET"
    ).alias_applied is False

    with pytest.raises(ToolInventoryError) as missing:
        inventory.get("FINANCE.NOT_ADMITTED.GET")
    assert missing.value.code == "TOOL_NOT_ADMITTED"
    with pytest.raises(ToolInventoryError) as unknown:
        inventory.resolve("FINANCE.NOT_ADMITTED.GET")
    assert unknown.value.code == "OPERATION_NOT_ADMITTED"


def test_w70_inventory_is_backed_by_current_eos_openapi_metadata() -> None:
    operations = _openapi_operations()
    inventory = load_tool_inventory()

    for tool in inventory.tools:
        method, operation = operations[tool.provider_operation_id]
        assert operation["x-nex-required-scopes"] == [tool.service_scope]
        if tool.oa_action == "NONE_SERVICE_TRUST_ONLY":
            assert "x-nex-business-scope" not in operation
        else:
            assert operation["x-nex-business-scope"] == tool.oa_action
        if tool.invocation_semantics == "READ":
            assert operation["x-nex-side-effect-free"] is True
        else:
            assert method != "get"
            assert operation.get("x-nex-side-effect-free") is not True


def test_w70_activation_and_approval_boundaries_are_explicit() -> None:
    inventory = load_tool_inventory()

    legacy = inventory.get("FINANCE.VOUCHER_DRAFT.CREATE")
    assert legacy.activation_state == "ACTIVE_COMPATIBILITY"
    assert legacy.approval_requirement == "NSL_WRITE"
    assert legacy.compatibility_aliases == (
        "FINANCE.CREATE_VOUCHER_DRAFT",
        "createEosVoucherDraft",
    )

    candidate_read = inventory.get("FINANCE.VOUCHER_CANDIDATE.GET_V2")
    assert candidate_read.activation_state == "DEFERRED"
    assert candidate_read.oa_action == "NONE_SERVICE_TRUST_ONLY"

    posting = inventory.get("FINANCE.VOUCHER.APPROVE_AND_POST")
    admission = inventory.get("FINANCE.VOUCHER_POSTING.ADMIT")
    assert posting.approval_requirement == "ACCOUNTING_POSTING"
    assert admission.approval_requirement == "ACCOUNTING_POSTING"
    assert posting.invocation_semantics == "GOVERNED_WRITE"
    assert admission.invocation_semantics == "READ"

    pnl = inventory.get("FINANCE.PROJECT_PNL.GET")
    assert pnl.oa_action == "project:pnl:read"
    assert pnl.side_effect_free is True

    for operation in (
        "PROJECT.WORK_CODE_SET.APPROVE",
        "PROJECT.WORK_ASSIGNMENT.ASSIGN",
    ):
        tool = inventory.get(operation)
        assert tool.domain_pack == "D12_PROJECT"
        assert tool.approval_requirement == "BUSINESS_FORMAL"


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    (
        ("root_fields", "INVENTORY_FIELDS_INVALID"),
        ("schema", "SCHEMA_UNSUPPORTED"),
        ("inventory_id", "INVENTORY_ID_INVALID"),
        ("version", "INVENTORY_VERSION_INVALID"),
        ("revision_bool", "INVENTORY_REVISION_INVALID"),
        ("status", "INVENTORY_STATUS_INVALID"),
        ("owner", "INVENTORY_OWNER_INVALID"),
        ("alias_fields", "ALIAS_REGISTRY_FIELDS_INVALID"),
        ("alias_item_fields", "ALIAS_FIELDS_INVALID"),
        ("alias_version", "ALIAS_REGISTRY_VERSION_INVALID"),
        ("aliases_empty", "ALIASES_INVALID"),
        ("alias_not_admitted", "ALIAS_NOT_ADMITTED"),
        ("alias_target", "ALIAS_TARGET_INVALID"),
        ("alias_order", "ALIAS_ORDER_OR_DUPLICATE_INVALID"),
        ("tools_type", "TOOLS_INVALID"),
        ("tool_fields", "TOOL_FIELDS_INVALID"),
        ("canonical_alias", "TOOL_CANONICAL_IS_ALIAS"),
        ("operation_not_admitted", "TOOL_OPERATION_NOT_ADMITTED"),
        ("provider_mismatch", "TOOL_PROVIDER_OPERATION_MISMATCH"),
        ("domain_pack", "INVENTORY_CHOICE_INVALID"),
        ("owner_service", "TOOL_OWNER_OR_SERVICE_SCOPE_INVALID"),
        ("semantics", "TOOL_SEMANTICS_INVALID"),
        ("approval", "TOOL_APPROVAL_INVALID"),
        ("oa_action", "TOOL_OA_ACTION_INVALID"),
        ("tool_aliases_type", "TOOL_ALIASES_INVALID"),
        ("tool_aliases_duplicate", "TOOL_ALIASES_INVALID"),
        ("tool_alias_not_admitted", "TOOL_ALIAS_NOT_ADMITTED"),
        ("tool_alias_target", "TOOL_ALIAS_TARGET_INVALID"),
        ("provider_alias_missing", "TOOL_PROVIDER_ALIAS_MISSING"),
        ("compatibility_alias_required", "TOOL_COMPATIBILITY_ALIAS_REQUIRED"),
        ("tool_order", "TOOL_ORDER_OR_DUPLICATE_INVALID"),
        ("alias_inventory", "ALIAS_INVENTORY_MISMATCH"),
        ("attestation_fields", "ATTESTATION_FIELDS_INVALID"),
        ("attestation", "ATTESTATION_INVALID"),
        ("blank_text", "INVENTORY_FIELD_INVALID"),
    ),
)
def test_w70_inventory_loader_fails_closed_for_semantic_drift(
    tmp_path: Path, mutation: str, expected_code: str
) -> None:
    value = copy.deepcopy(_inventory_json())
    if mutation == "root_fields":
        value["unexpected"] = True
    elif mutation == "schema":
        value["schema_version"] = "future"
    elif mutation == "inventory_id":
        value["inventory_id"] = "other"
    elif mutation == "version":
        value["inventory_version"] = "2.0.0"
    elif mutation == "revision_bool":
        value["revision"] = True
    elif mutation == "status":
        value["status"] = "ACTIVE"
    elif mutation == "owner":
        value["owner"]["business_state"] = "nex-ae-api"
    elif mutation == "alias_fields":
        value["alias_registry"]["unexpected"] = True
    elif mutation == "alias_item_fields":
        value["alias_registry"]["aliases"][0]["unexpected"] = True
    elif mutation == "alias_version":
        value["alias_registry"]["registry_version"] = "old"
    elif mutation == "aliases_empty":
        value["alias_registry"]["aliases"] = []
    elif mutation == "alias_not_admitted":
        value["alias_registry"]["aliases"][0]["requested_operation"] = (
            "FINANCE.NOT_ADMITTED.GET"
        )
    elif mutation == "alias_target":
        value["alias_registry"]["aliases"][0]["canonical_operation"] = (
            "FINANCE.FX_RATE.HISTORY"
        )
    elif mutation == "alias_order":
        value["alias_registry"]["aliases"].reverse()
    elif mutation == "tools_type":
        value["tools"] = {}
    elif mutation == "tool_fields":
        value["tools"][0]["unexpected"] = True
    elif mutation == "canonical_alias":
        value["tools"][0]["canonical_operation_id"] = (
            "FINANCE.CREATE_VOUCHER_DRAFT"
        )
    elif mutation == "operation_not_admitted":
        value["tools"][0]["canonical_operation_id"] = "FINANCE.NOT_ADMITTED.GET"
    elif mutation == "provider_mismatch":
        value["tools"][0]["provider_operation_id"] = "FINANCE.FX_RATE.IMPORT"
    elif mutation == "domain_pack":
        value["tools"][0]["domain_pack"] = "OTHER"
    elif mutation == "owner_service":
        value["tools"][0]["owner_service"] = "nex-ae-api"
    elif mutation == "semantics":
        value["tools"][0]["invocation_semantics"] = "READ"
    elif mutation == "approval":
        value["tools"][1]["approval_requirement"] = "BUSINESS_FORMAL"
    elif mutation == "oa_action":
        value["tools"][0]["oa_action"] = "BAD"
    elif mutation == "tool_aliases_type":
        value["tools"][0]["compatibility_aliases"] = {}
    elif mutation == "tool_aliases_duplicate":
        value["tools"][11]["compatibility_aliases"] = [
            "FINANCE.CREATE_VOUCHER_DRAFT",
            "FINANCE.CREATE_VOUCHER_DRAFT",
        ]
    elif mutation == "tool_alias_not_admitted":
        value["tools"][0]["compatibility_aliases"] = [
            "FINANCE.NOT_ADMITTED.GET"
        ]
    elif mutation == "tool_alias_target":
        value["tools"][0]["compatibility_aliases"] = [
            "FINANCE.GET_VOUCHER_DRAFT"
        ]
    elif mutation == "provider_alias_missing":
        value["tools"][11]["compatibility_aliases"] = [
            "FINANCE.CREATE_VOUCHER_DRAFT"
        ]
    elif mutation == "compatibility_alias_required":
        value["tools"][11]["provider_operation_id"] = (
            "FINANCE.VOUCHER_DRAFT.CREATE"
        )
        value["tools"][11]["compatibility_aliases"] = []
    elif mutation == "tool_order":
        value["tools"].reverse()
    elif mutation == "alias_inventory":
        value["tools"][11]["compatibility_aliases"].remove(
            "FINANCE.CREATE_VOUCHER_DRAFT"
        )
    elif mutation == "attestation_fields":
        value["release_attestation"]["unexpected"] = True
    elif mutation == "attestation":
        value["release_attestation"]["authority"] = "OTHER"
    elif mutation == "blank_text":
        value["tools"][0]["oa_action"] = " "
    error = _error_for(tmp_path, _rehash(value))
    assert error.code == expected_code


def test_w70_inventory_loader_rejects_digest_io_and_root_failures(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(ToolInventoryError) as unreadable:
        load_tool_inventory(missing)
    assert unreadable.value.code == "INVENTORY_UNREADABLE"

    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    with pytest.raises(ToolInventoryError) as invalid_json:
        load_tool_inventory(malformed)
    assert invalid_json.value.code == "INVENTORY_INVALID_JSON"

    assert _error_for(tmp_path, []).code == "INVENTORY_FIELD_INVALID"

    damaged = _inventory_json()
    damaged["tools"][0]["oa_action"] = "finance:changed:scope"
    assert _error_for(tmp_path, damaged).code == "INVENTORY_DIGEST_MISMATCH"

    expected = semantic_sha256_hash_ref(
        {key: value for key, value in _inventory_json().items() if key != "release_attestation"}
    )
    assert expected == load_tool_inventory().content_digest
