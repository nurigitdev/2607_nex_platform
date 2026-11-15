"""Fail-closed reader for the W70 canonical Tool identity inventory."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from nex_runtime import (
    DEFAULT_OPERATION_REGISTRY,
    OPERATION_ALIAS_REGISTRY_VERSION,
    OperationNameError,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

TOOL_INVENTORY_SCHEMA_VERSION = "nex.mybee.tool-inventory.v1"
TOOL_INVENTORY_ID = "mybee.phase1.w70.canonical-tools"
TOOL_INVENTORY_VERSION = "1.0.0"
TOOL_INVENTORY_STATUS = "SOURCE_ADMITTED_RUNTIME_UNCHANGED"

DOMAIN_PACKS = frozenset({"D04_ACCOUNTING", "D12_PROJECT"})
INVOCATION_SEMANTICS = frozenset({"READ", "GOVERNED_WRITE"})
APPROVAL_REQUIREMENTS = frozenset(
    {"NONE", "NSL_WRITE", "BUSINESS_FORMAL", "ACCOUNTING_POSTING"}
)
ACTIVATION_STATES = frozenset(
    {"CANDIDATE", "ACTIVE_COMPATIBILITY", "DEFERRED"}
)

DEFAULT_TOOL_INVENTORY_PATH = (
    Path(__file__).resolve().parents[2] / "skills/tool_inventory.v1.json"
)

_ROOT_FIELDS = frozenset(
    {
        "schema_version",
        "inventory_id",
        "inventory_version",
        "revision",
        "status",
        "owner",
        "alias_registry",
        "tools",
        "release_attestation",
    }
)
_TOOL_FIELDS = frozenset(
    {
        "canonical_operation_id",
        "provider_operation_id",
        "domain_pack",
        "owner_service",
        "invocation_semantics",
        "approval_requirement",
        "activation_state",
        "service_scope",
        "oa_action",
        "side_effect_free",
        "compatibility_aliases",
    }
)
_OWNER = {
    "domain_policy": "nex-mybee-ax",
    "operation_registry": "nex-runtime",
    "business_state": "nex-eos",
    "runtime_execution": "nex-ae-api",
    "authorization": "nex-oa",
    "approval_workflow": "nex-wc",
}
_OA_ACTION = re.compile(
    r"^(?:[a-z][a-z0-9-]*(?::[a-z][a-z0-9-]*)+|NONE_SERVICE_TRUST_ONLY)$"
)


class ToolInventoryError(ValueError):
    """Raised when the source-admitted Tool identity inventory drifts."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


@dataclass(frozen=True)
class ToolIdentity:
    canonical_operation_id: str
    provider_operation_id: str
    domain_pack: str
    owner_service: str
    invocation_semantics: str
    approval_requirement: str
    activation_state: str
    service_scope: str
    oa_action: str
    side_effect_free: bool
    compatibility_aliases: tuple[str, ...]


@dataclass(frozen=True)
class ToolInventory:
    inventory_id: str
    inventory_version: str
    revision: int
    status: str
    registry_version: str
    content_digest: str
    tools: tuple[ToolIdentity, ...]
    _by_operation: Mapping[str, ToolIdentity]

    def get(self, canonical_operation_id: str) -> ToolIdentity:
        try:
            return self._by_operation[canonical_operation_id]
        except KeyError as exc:
            raise ToolInventoryError(
                "TOOL_NOT_ADMITTED", str(canonical_operation_id)
            ) from exc

    def resolve(self, requested_operation: object) -> ToolIdentity:
        try:
            resolved = DEFAULT_OPERATION_REGISTRY.resolve(requested_operation)
        except OperationNameError as exc:
            raise ToolInventoryError(
                "OPERATION_NOT_ADMITTED", str(requested_operation)
            ) from exc
        return self.get(resolved.canonical_operation)


def calculate_tool_inventory_digest(inventory: Mapping[str, Any]) -> str:
    """Return the shared semantic digest over the attested inventory payload."""

    return semantic_sha256_hash_ref(
        {key: value for key, value in inventory.items() if key != "release_attestation"}
    )


def load_tool_inventory(
    path: Path = DEFAULT_TOOL_INVENTORY_PATH,
) -> ToolInventory:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ToolInventoryError("INVENTORY_UNREADABLE", str(path)) from exc
    except json.JSONDecodeError as exc:
        raise ToolInventoryError("INVENTORY_INVALID_JSON", str(path)) from exc
    inventory = _object(raw, "$")
    if set(inventory) != _ROOT_FIELDS:
        raise ToolInventoryError("INVENTORY_FIELDS_INVALID", str(sorted(inventory)))
    if inventory.get("schema_version") != TOOL_INVENTORY_SCHEMA_VERSION:
        raise ToolInventoryError(
            "SCHEMA_UNSUPPORTED", str(inventory.get("schema_version"))
        )
    if inventory.get("inventory_id") != TOOL_INVENTORY_ID:
        raise ToolInventoryError(
            "INVENTORY_ID_INVALID", str(inventory.get("inventory_id"))
        )
    if inventory.get("inventory_version") != TOOL_INVENTORY_VERSION:
        raise ToolInventoryError(
            "INVENTORY_VERSION_INVALID", str(inventory.get("inventory_version"))
        )
    if inventory.get("revision") != 1 or isinstance(inventory.get("revision"), bool):
        raise ToolInventoryError(
            "INVENTORY_REVISION_INVALID", str(inventory.get("revision"))
        )
    if inventory.get("status") != TOOL_INVENTORY_STATUS:
        raise ToolInventoryError(
            "INVENTORY_STATUS_INVALID", str(inventory.get("status"))
        )
    if dict(_object(inventory.get("owner"), "owner")) != _OWNER:
        raise ToolInventoryError("INVENTORY_OWNER_INVALID", str(inventory.get("owner")))

    aliases = _parse_alias_registry(inventory.get("alias_registry"))
    tools = _parse_tools(inventory.get("tools"))
    _require_alias_consistency(aliases, tools)
    content_digest = _parse_attestation(
        inventory.get("release_attestation"), inventory
    )
    by_operation = MappingProxyType(
        {item.canonical_operation_id: item for item in tools}
    )
    return ToolInventory(
        inventory_id=TOOL_INVENTORY_ID,
        inventory_version=TOOL_INVENTORY_VERSION,
        revision=1,
        status=TOOL_INVENTORY_STATUS,
        registry_version=OPERATION_ALIAS_REGISTRY_VERSION,
        content_digest=content_digest,
        tools=tools,
        _by_operation=by_operation,
    )


def _parse_alias_registry(value: object) -> tuple[tuple[str, str], ...]:
    registry = _object(value, "alias_registry")
    if set(registry) != {"registry_version", "aliases"}:
        raise ToolInventoryError("ALIAS_REGISTRY_FIELDS_INVALID", str(registry))
    if registry.get("registry_version") != OPERATION_ALIAS_REGISTRY_VERSION:
        raise ToolInventoryError(
            "ALIAS_REGISTRY_VERSION_INVALID", str(registry.get("registry_version"))
        )
    raw_aliases = registry.get("aliases")
    if not isinstance(raw_aliases, list) or not raw_aliases:
        raise ToolInventoryError("ALIASES_INVALID", "non-empty array required")
    aliases: list[tuple[str, str]] = []
    for index, raw_alias in enumerate(raw_aliases):
        item = _object(raw_alias, f"aliases[{index}]")
        if set(item) != {"requested_operation", "canonical_operation"}:
            raise ToolInventoryError("ALIAS_FIELDS_INVALID", str(item))
        requested = _text(item.get("requested_operation"), f"aliases[{index}].source")
        canonical = _text(
            item.get("canonical_operation"), f"aliases[{index}].target"
        )
        try:
            resolved = DEFAULT_OPERATION_REGISTRY.resolve(requested)
        except OperationNameError as exc:
            raise ToolInventoryError("ALIAS_NOT_ADMITTED", requested) from exc
        if not resolved.alias_applied or resolved.canonical_operation != canonical:
            raise ToolInventoryError("ALIAS_TARGET_INVALID", requested)
        aliases.append((requested, canonical))
    if aliases != sorted(aliases) or len(set(aliases)) != len(aliases):
        raise ToolInventoryError("ALIAS_ORDER_OR_DUPLICATE_INVALID", str(aliases))
    return tuple(aliases)


def _parse_tools(value: object) -> tuple[ToolIdentity, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= 64:
        raise ToolInventoryError("TOOLS_INVALID", "1..64 entries required")
    tools = tuple(_parse_tool(item, index=index) for index, item in enumerate(value))
    identities = [item.canonical_operation_id for item in tools]
    if identities != sorted(identities) or len(set(identities)) != len(identities):
        raise ToolInventoryError("TOOL_ORDER_OR_DUPLICATE_INVALID", str(identities))
    return tools


def _parse_tool(value: object, *, index: int) -> ToolIdentity:
    item = _object(value, f"tools[{index}]")
    if set(item) != _TOOL_FIELDS:
        raise ToolInventoryError("TOOL_FIELDS_INVALID", str(sorted(item)))
    canonical = _text(item.get("canonical_operation_id"), "canonical_operation_id")
    provider = _text(item.get("provider_operation_id"), "provider_operation_id")
    try:
        canonical_resolution = DEFAULT_OPERATION_REGISTRY.resolve(canonical)
        provider_resolution = DEFAULT_OPERATION_REGISTRY.resolve(provider)
    except OperationNameError as exc:
        raise ToolInventoryError("TOOL_OPERATION_NOT_ADMITTED", canonical) from exc
    if canonical_resolution.alias_applied:
        raise ToolInventoryError("TOOL_CANONICAL_IS_ALIAS", canonical)
    if provider_resolution.canonical_operation != canonical:
        raise ToolInventoryError("TOOL_PROVIDER_OPERATION_MISMATCH", provider)

    domain_pack = _choice("domain_pack", item.get("domain_pack"), DOMAIN_PACKS)
    semantics = _choice(
        "invocation_semantics", item.get("invocation_semantics"), INVOCATION_SEMANTICS
    )
    approval = _choice(
        "approval_requirement", item.get("approval_requirement"), APPROVAL_REQUIREMENTS
    )
    activation = _choice(
        "activation_state", item.get("activation_state"), ACTIVATION_STATES
    )
    if item.get("owner_service") != "nex-eos" or item.get("service_scope") != "service:call":
        raise ToolInventoryError("TOOL_OWNER_OR_SERVICE_SCOPE_INVALID", canonical)
    side_effect_free = item.get("side_effect_free")
    if not isinstance(side_effect_free, bool) or side_effect_free != (
        semantics == "READ"
    ):
        raise ToolInventoryError("TOOL_SEMANTICS_INVALID", canonical)
    if semantics == "READ" and approval in {"NSL_WRITE", "BUSINESS_FORMAL"}:
        raise ToolInventoryError("TOOL_APPROVAL_INVALID", canonical)
    action = _text(item.get("oa_action"), "oa_action")
    if _OA_ACTION.fullmatch(action) is None:
        raise ToolInventoryError("TOOL_OA_ACTION_INVALID", canonical)

    raw_aliases = item.get("compatibility_aliases")
    if not isinstance(raw_aliases, list):
        raise ToolInventoryError("TOOL_ALIASES_INVALID", canonical)
    aliases = tuple(_text(alias, "compatibility_alias") for alias in raw_aliases)
    if list(aliases) != sorted(aliases) or len(set(aliases)) != len(aliases):
        raise ToolInventoryError("TOOL_ALIASES_INVALID", canonical)
    for alias in aliases:
        try:
            resolution = DEFAULT_OPERATION_REGISTRY.resolve(alias)
        except OperationNameError as exc:
            raise ToolInventoryError("TOOL_ALIAS_NOT_ADMITTED", alias) from exc
        if not resolution.alias_applied or resolution.canonical_operation != canonical:
            raise ToolInventoryError("TOOL_ALIAS_TARGET_INVALID", alias)
    if provider != canonical and provider not in aliases:
        raise ToolInventoryError("TOOL_PROVIDER_ALIAS_MISSING", provider)
    if activation == "ACTIVE_COMPATIBILITY" and not aliases:
        raise ToolInventoryError("TOOL_COMPATIBILITY_ALIAS_REQUIRED", canonical)

    return ToolIdentity(
        canonical_operation_id=canonical,
        provider_operation_id=provider,
        domain_pack=domain_pack,
        owner_service="nex-eos",
        invocation_semantics=semantics,
        approval_requirement=approval,
        activation_state=activation,
        service_scope="service:call",
        oa_action=action,
        side_effect_free=side_effect_free,
        compatibility_aliases=aliases,
    )


def _require_alias_consistency(
    aliases: tuple[tuple[str, str], ...], tools: tuple[ToolIdentity, ...]
) -> None:
    declared = tuple(
        sorted(
            (alias, item.canonical_operation_id)
            for item in tools
            for alias in item.compatibility_aliases
        )
    )
    if aliases != declared:
        raise ToolInventoryError("ALIAS_INVENTORY_MISMATCH", str(declared))


def _parse_attestation(value: object, inventory: Mapping[str, Any]) -> str:
    attestation = _object(value, "release_attestation")
    if set(attestation) != {"profile", "authority", "evidence_ref", "content_digest"}:
        raise ToolInventoryError("ATTESTATION_FIELDS_INVALID", str(attestation))
    if (
        attestation.get("profile") != "SOURCE_AUTHORITY_CONTENT_DIGEST_V1"
        or attestation.get("authority") != "NEX_MYBEE_W70_S8_01A"
        or attestation.get("evidence_ref")
        != "docs/slices/mybee_phase1_w70_s8_01a_tool_inventory.md"
    ):
        raise ToolInventoryError("ATTESTATION_INVALID", str(attestation))
    expected = _text(attestation.get("content_digest"), "content_digest")
    actual = calculate_tool_inventory_digest(inventory)
    if expected != actual:
        raise ToolInventoryError("INVENTORY_DIGEST_MISMATCH", actual)
    return actual


def _object(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ToolInventoryError("INVENTORY_FIELD_INVALID", f"{path} must be object")
    return value


def _text(value: object, path: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ToolInventoryError("INVENTORY_FIELD_INVALID", f"{path} must be text")
    return value


def _choice(path: str, value: object, choices: frozenset[str]) -> str:
    text = _text(value, path)
    if text not in choices:
        raise ToolInventoryError("INVENTORY_CHOICE_INVALID", f"{path}: {text}")
    return text
