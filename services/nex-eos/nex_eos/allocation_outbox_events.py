from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from nex_runtime.semantic_hashes import validate_hash_ref

ALLOCATION_COMMITTED_EVENT_SCHEMA = "eos_cost_allocation_committed_event.v1"

_FIELDS = frozenset(
    {
        "schema_version",
        "tenant_id",
        "business_operation_id",
        "operation",
        "company_id",
        "batch_id",
        "plan_id",
        "plan_revision",
        "period_id",
        "source_set_hash",
        "reconciliation_hash",
        "commit_state",
        "committed_at",
    }
)
_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$")
_OPERATION = re.compile(r"^[A-Z][A-Z0-9_.]{0,127}$")


class EosAllocationOutboxEventError(ValueError):
    pass


def build_allocation_committed_event_payload(
    *,
    tenant_id: object,
    business_operation_id: object,
    operation: object,
    result: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        raise EosAllocationOutboxEventError("Cost Allocation result must be an object")
    return admit_allocation_committed_event(
        {
            "schema_version": ALLOCATION_COMMITTED_EVENT_SCHEMA,
            "tenant_id": tenant_id,
            "business_operation_id": business_operation_id,
            "operation": operation,
            "company_id": result.get("company_id"),
            "batch_id": result.get("batch_id"),
            "plan_id": result.get("plan_id"),
            "plan_revision": result.get("plan_revision"),
            "period_id": result.get("period_id"),
            "source_set_hash": result.get("source_set_hash"),
            "reconciliation_hash": result.get("reconciliation_hash"),
            "commit_state": "COMMITTED",
            "committed_at": result.get("committed_at"),
        }
    )


def admit_allocation_committed_event(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _FIELDS:
        raise EosAllocationOutboxEventError(
            "Cost Allocation event fields do not match the canonical contract"
        )
    if value.get("schema_version") != ALLOCATION_COMMITTED_EVENT_SCHEMA:
        raise EosAllocationOutboxEventError("Cost Allocation event schema is invalid")
    if value.get("commit_state") != "COMMITTED":
        raise EosAllocationOutboxEventError("Cost Allocation event must be committed")
    plan_revision = value.get("plan_revision")
    if (
        isinstance(plan_revision, bool)
        or not isinstance(plan_revision, int)
        or plan_revision < 1
    ):
        raise EosAllocationOutboxEventError("plan_revision must be positive")
    return {
        "schema_version": ALLOCATION_COMMITTED_EVENT_SCHEMA,
        "tenant_id": _pattern("tenant_id", value.get("tenant_id"), _SCOPED_ID),
        "business_operation_id": _uuid(
            "business_operation_id", value.get("business_operation_id")
        ),
        "operation": _pattern("operation", value.get("operation"), _OPERATION),
        "company_id": _uuid("company_id", value.get("company_id")),
        "batch_id": _uuid("batch_id", value.get("batch_id")),
        "plan_id": _uuid("plan_id", value.get("plan_id")),
        "plan_revision": plan_revision,
        "period_id": _uuid("period_id", value.get("period_id")),
        "source_set_hash": _hash("source_set_hash", value.get("source_set_hash")),
        "reconciliation_hash": _hash(
            "reconciliation_hash", value.get("reconciliation_hash")
        ),
        "commit_state": "COMMITTED",
        "committed_at": _timestamp("committed_at", value.get("committed_at")),
    }


def _pattern(field_name: str, value: object, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise EosAllocationOutboxEventError(f"{field_name} has an invalid format")
    return value


def _uuid(field_name: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise EosAllocationOutboxEventError(f"{field_name} must be a UUID") from exc


def _hash(field_name: str, value: object) -> str:
    try:
        return validate_hash_ref(value)
    except (TypeError, ValueError, AttributeError) as exc:
        raise EosAllocationOutboxEventError(
            f"{field_name} must be a sha256 hash reference"
        ) from exc


def _timestamp(field_name: str, value: object) -> str:
    if not isinstance(value, str):
        raise EosAllocationOutboxEventError(f"{field_name} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EosAllocationOutboxEventError(
            f"{field_name} must be an ISO timestamp"
        ) from exc
    if parsed.tzinfo is None:
        raise EosAllocationOutboxEventError(f"{field_name} must include a timezone")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
