from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Protocol

from nex_ae_api.agent_runtime_worker import AgentRuntimeAssignment
from nex_ae_api.runtime_jobs import RUNTIME_ASSIGNMENT_KINDS


@dataclass(frozen=True)
class RuntimeAssignmentHandlerError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class RuntimeAssignmentHandler(Protocol):
    def __call__(self, assignment: AgentRuntimeAssignment) -> Mapping[str, Any]: ...


class RuntimeAssignmentHandlerRegistry:
    """Routes runtime assignment kinds without extending the step registry."""

    def __init__(
        self,
        handlers: Mapping[str, RuntimeAssignmentHandler],
    ) -> None:
        if not isinstance(handlers, Mapping) or not handlers:
            raise _invalid("assignment handlers must be a non-empty object")
        normalized: dict[str, RuntimeAssignmentHandler] = {}
        for raw_kind, handler in handlers.items():
            kind = _assignment_kind(raw_kind)
            if not callable(handler):
                raise _invalid(f"{kind} assignment handler must be callable")
            if kind in normalized:
                raise _invalid(f"duplicate assignment handler: {kind}")
            normalized[kind] = handler
        self._handlers = MappingProxyType(normalized)

    @property
    def registered_kinds(self) -> tuple[str, ...]:
        return tuple(sorted(self._handlers))

    def handles(self, assignment_kind: str) -> bool:
        return _assignment_kind(assignment_kind) in self._handlers

    def __call__(self, assignment: AgentRuntimeAssignment) -> Mapping[str, Any]:
        if not isinstance(assignment, AgentRuntimeAssignment):
            raise _invalid("assignment must be an AgentRuntimeAssignment")
        kind = _assignment_kind(assignment.assignment_kind)
        handler = self._handlers.get(kind)
        if handler is None:
            raise RuntimeAssignmentHandlerError(
                "ae.runtime_assignment_handler_unavailable",
                f"No installed handler is registered for {kind}.",
                retryable=True,
            )
        result = handler(assignment)
        if not isinstance(result, Mapping):
            raise _invalid("assignment handler result must be an object")
        return result


def _assignment_kind(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid("assignment kind must be a non-empty string")
    normalized = value.strip().upper()
    if normalized not in RUNTIME_ASSIGNMENT_KINDS:
        raise _invalid(f"unknown runtime assignment kind: {normalized}")
    return normalized


def _invalid(detail: str) -> RuntimeAssignmentHandlerError:
    return RuntimeAssignmentHandlerError(
        "ae.runtime_assignment_handler_invalid",
        detail,
    )


__all__ = [
    "RuntimeAssignmentHandler",
    "RuntimeAssignmentHandlerError",
    "RuntimeAssignmentHandlerRegistry",
]
