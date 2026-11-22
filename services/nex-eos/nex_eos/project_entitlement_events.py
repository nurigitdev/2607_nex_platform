from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import select
from sqlalchemy.orm import Session

from .business_transactions import (
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_IDEMPOTENCY_TABLE,
    EOS_OUTBOX_TABLE,
)

PROJECT_ENTITLEMENT_EVENT_TYPE = "PROJECT_ENTITLEMENT_SNAPSHOT"
PROJECT_ENTITLEMENT_OPERATION = "PROJECT.PROJECT.ENTITLEMENT_SYNC"

_PROJECT_CODE = re.compile(r"^[A-Z0-9]{4}[DMSOIG][0-9]{6}$")
_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$")
_ROLES = frozenset({"OWNER", "MANAGER", "MEMBER", "VIEWER"})
_STATES = frozenset({"ACTIVE", "INACTIVE", "CLOSING", "CLOSED"})


class EosProjectEntitlementEventError(RuntimeError):
    pass


def append_project_entitlement_snapshot(
    session: Session,
    *,
    tenant_id: str,
    project_id: str,
    project_code: str,
    project_status: str,
    source_version: int,
    members: Iterable[Mapping[str, Any]],
    correlation_id: str,
    causation_id: str,
    occurred_at: datetime,
) -> dict[str, Any]:
    """Append one exact, deterministic OA entitlement snapshot."""

    tenant = _scoped("tenant_id", tenant_id, maximum=128)
    project = _uuid("project_id", project_id)
    code = _project_code(project_code)
    status = _choice("project_status", project_status, _STATES)
    version = _positive_int("source_version", source_version)
    correlation = _scoped("correlation_id", correlation_id, maximum=256)
    causation = _scoped("causation_id", causation_id, maximum=256)
    recorded_at = _aware_datetime(occurred_at)
    normalized_members = _members(members)
    namespace = f"{tenant}/{project}/v{version}"
    operation_id = str(
        uuid5(
            NAMESPACE_URL,
            f"https://nex-platform.local/eos/project-entitlement-operation/{namespace}",
        )
    )
    event_id = str(
        uuid5(
            NAMESPACE_URL,
            f"https://nex-platform.local/eos/project-entitlement-event/{namespace}",
        )
    )
    outbox_id = str(
        uuid5(
            NAMESPACE_URL,
            f"https://nex-platform.local/eos/project-entitlement-outbox/{namespace}",
        )
    )
    idempotency_key = f"project-entitlement:{project}:v{version}"
    payload = {
        "schema_version": "eos.project_entitlement_snapshot.v1",
        "tenant_id": tenant,
        "project_id": project,
        "project_code": code,
        "project_status": status,
        "source_version": version,
        "members": normalized_members,
        "correlation_id": correlation,
        "causation_id": causation,
        "occurred_at": recorded_at.isoformat().replace("+00:00", "Z"),
    }
    payload_hash = semantic_sha256_hash_ref(payload)
    existing = (
        session.execute(
            select(EOS_OUTBOX_TABLE).where(
                EOS_OUTBOX_TABLE.c.tenant_id == tenant,
                EOS_OUTBOX_TABLE.c.event_id == event_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if existing is not None:
        if (
            existing["event_type"] != PROJECT_ENTITLEMENT_EVENT_TYPE
            or existing["event_payload_hash"] != payload_hash
            or existing["event_payload"] != payload
        ):
            raise EosProjectEntitlementEventError(
                "Project entitlement event identity is bound to different semantics"
            )
        return dict(existing)

    result = {
        "business_result_ref": f"eos.project-entitlement:{project}:v{version}",
        "project_id": project,
        "project_code": code,
        "source_version": version,
    }
    session.execute(
        EOS_BUSINESS_OPERATION_TABLE.insert().values(
            tenant_id=tenant,
            business_operation_id=operation_id,
            idempotency_key=idempotency_key,
            operation=PROJECT_ENTITLEMENT_OPERATION,
            payload_hash=payload_hash,
            commit_state="COMMITTED",
            result_json=result,
            created_at=recorded_at,
            committed_at=recorded_at,
        )
    )
    session.execute(
        EOS_IDEMPOTENCY_TABLE.insert().values(
            tenant_id=tenant,
            idempotency_key=idempotency_key,
            business_operation_id=operation_id,
            operation=PROJECT_ENTITLEMENT_OPERATION,
            payload_hash=payload_hash,
            idempotency_state="COMPLETED",
            result_json=result,
            created_at=recorded_at,
            completed_at=recorded_at,
        )
    )
    outbox = {
        "outbox_id": outbox_id,
        "tenant_id": tenant,
        "event_id": event_id,
        "business_operation_id": operation_id,
        "event_type": PROJECT_ENTITLEMENT_EVENT_TYPE,
        "event_payload": payload,
        "event_payload_hash": payload_hash,
        "delivery_state": "PENDING",
        "attempt_count": 0,
        "created_at": recorded_at,
        "updated_at": recorded_at,
        "published_at": None,
    }
    session.execute(EOS_OUTBOX_TABLE.insert().values(**outbox))
    return outbox


def _members(values: Iterable[Mapping[str, Any]]) -> list[dict[str, str]]:
    normalized: dict[str, str] = {}
    for value in values:
        if not isinstance(value, Mapping) or set(value) != {
            "subject_id",
            "project_role",
        }:
            raise EosProjectEntitlementEventError("members contain an invalid record")
        subject = _scoped("subject_id", value["subject_id"], maximum=128)
        role = _choice("project_role", value["project_role"], _ROLES)
        if subject in normalized:
            raise EosProjectEntitlementEventError("members contain a duplicate subject")
        normalized[subject] = role
    if not normalized:
        raise EosProjectEntitlementEventError("members must not be empty")
    return [
        {"subject_id": subject, "project_role": normalized[subject]}
        for subject in sorted(normalized)
    ]


def _scoped(field: str, value: object, *, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
        or _SCOPED_ID.fullmatch(value) is None
    ):
        raise EosProjectEntitlementEventError(f"{field} is invalid")
    return value


def _project_code(value: object) -> str:
    if not isinstance(value, str) or _PROJECT_CODE.fullmatch(value) is None:
        raise EosProjectEntitlementEventError("project_code is invalid")
    return value


def _choice(field: str, value: object, allowed: frozenset[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise EosProjectEntitlementEventError(f"{field} is invalid")
    return value


def _uuid(field: str, value: object) -> str:
    try:
        return str(UUID(str(value)))
    except (AttributeError, TypeError, ValueError) as exc:
        raise EosProjectEntitlementEventError(f"{field} must be a UUID") from exc


def _positive_int(field: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise EosProjectEntitlementEventError(f"{field} must be positive")
    return value


def _aware_datetime(value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise EosProjectEntitlementEventError("occurred_at must be timezone-aware")
    return value.astimezone(UTC)
