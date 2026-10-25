from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

CANONICAL_OPERATION_PATTERN: Final = re.compile(
    r"^[A-Z][A-Z0-9_]*\.[A-Z][A-Z0-9_]*\.[A-Z][A-Z0-9_]*$"
)
LEGACY_OPERATION_PATTERN: Final = re.compile(r"^[A-Z][A-Z0-9_.]*$")
OPERATION_ALIAS_REGISTRY_VERSION: Final = "p8-s105.v1"

P8_CANONICAL_OPERATIONS: Final = frozenset(
    {
        "PROJECT.PROJECT.CREATE",
        "PROJECT.PROJECT.GET",
        "PROJECT.PROJECT.LIST",
        "PROJECT.PROJECT.DEACTIVATE",
        "PROJECT.NVT_PROJECT.CREATE",
        "PROJECT.NVT_PROJECT.GET",
        "PROJECT.NVT_PROJECT.LIST",
        "PROJECT.NVT_PROJECT.UPDATE",
        "PROJECT.MEMBERSHIP.ADD",
        "PROJECT.MEMBERSHIP.REMOVE",
        "PROJECT.MEMBERSHIP.LIST",
        "FINANCE.VOUCHER_DRAFT.CREATE",
        "FINANCE.VOUCHER_DRAFT.GET",
        "FINANCE.VOUCHER_DRAFT.LIST",
        "FINANCE.VOUCHER_DRAFT.RESOLVE_COMMAND",
    }
)

P8_OPERATION_ALIASES: Final = MappingProxyType(
    {
        "FINANCE.CREATE_VOUCHER_DRAFT": "FINANCE.VOUCHER_DRAFT.CREATE",
        "FINANCE.GET_VOUCHER_DRAFT": "FINANCE.VOUCHER_DRAFT.GET",
        "FINANCE.RESOLVE_VOUCHER_DRAFT_COMMAND": (
            "FINANCE.VOUCHER_DRAFT.RESOLVE_COMMAND"
        ),
        "PROJECT.GET_PROJECT": "PROJECT.PROJECT.GET",
    }
)


class OperationNameError(ValueError):
    pass


@dataclass(frozen=True)
class ResolvedOperationName:
    requested_operation: str
    canonical_operation: str
    registry_version: str
    alias_applied: bool

    def to_projection(self) -> dict[str, object]:
        return {
            "requested_operation": self.requested_operation,
            "canonical_operation": self.canonical_operation,
            "registry_version": self.registry_version,
            "alias_applied": self.alias_applied,
        }


class CanonicalOperationRegistry:
    def __init__(
        self,
        *,
        canonical_operations=frozenset(P8_CANONICAL_OPERATIONS),
        aliases=P8_OPERATION_ALIASES,
        version: str = OPERATION_ALIAS_REGISTRY_VERSION,
    ) -> None:
        canonical = frozenset(canonical_operations)
        if not canonical or any(
            CANONICAL_OPERATION_PATTERN.fullmatch(item) is None for item in canonical
        ):
            raise OperationNameError("canonical operations must use three segments")
        if not isinstance(version, str) or not version.strip():
            raise OperationNameError("registry version must be non-empty")
        normalized_aliases: dict[str, str] = {}
        for requested, target in dict(aliases).items():
            if (
                not isinstance(requested, str)
                or LEGACY_OPERATION_PATTERN.fullmatch(requested) is None
                or requested in canonical
            ):
                raise OperationNameError("alias source is invalid or canonical")
            if target not in canonical:
                raise OperationNameError("alias target is not canonical")
            normalized_aliases[requested] = target
        self._canonical = canonical
        self._aliases = MappingProxyType(normalized_aliases)
        self.version = version

    @property
    def canonical_operations(self) -> frozenset[str]:
        return self._canonical

    @property
    def aliases(self):
        return self._aliases

    def resolve(self, requested_operation: object) -> ResolvedOperationName:
        if not isinstance(requested_operation, str):
            raise OperationNameError("requested operation must be a string")
        if requested_operation in self._canonical:
            canonical = requested_operation
        else:
            canonical = self._aliases.get(requested_operation)
            if canonical is None:
                raise OperationNameError("operation is not admitted")
        return ResolvedOperationName(
            requested_operation=requested_operation,
            canonical_operation=canonical,
            registry_version=self.version,
            alias_applied=requested_operation != canonical,
        )


DEFAULT_OPERATION_REGISTRY: Final = CanonicalOperationRegistry()
