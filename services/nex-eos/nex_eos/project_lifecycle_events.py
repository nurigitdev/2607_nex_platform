from __future__ import annotations

import re
from collections.abc import Mapping
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

PROJECT_LIFECYCLE_EVENT_TYPE = "PROJECT_LIFECYCLE_CHANGED"
PROJECT_LIFECYCLE_OPERATION = "PROJECT.PROJECT.LIFECYCLE_SYNC"
PROJECT_AGENT_PROFILE_POLICY_REF_ENV = "NEX_EOS_PROJECT_AGENT_PROFILE_POLICY_REF"

_PROJECT_STATES = frozenset({"ACTIVE", "INACTIVE", "CLOSING", "CLOSED"})
_PREVIOUS_STATES = frozenset({"SUBMITTED", *_PROJECT_STATES})
_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$")


class EosProjectLifecycleEventError(RuntimeError):
    pass


def append_project_lifecycle_event(
    session: Session,
    *,
    tenant_id: str,
    project_id: str,
    project_code: str,
    previous_state: str,
    current_state: str,
    project_version: int,
    profile_policy_ref: str,
    correlation_id: str,
    causation_id: str,
    occurred_at: datetime,
) -> dict[str, Any]:
    """Append one deterministic Project lifecycle event in the caller transaction."""

    tenant = _text("tenant_id", tenant_id, maximum=128)
    project = _uuid("project_id", project_id)
    code = _text("project_code", project_code, maximum=64)
    previous = _state("previous_state", previous_state, allowed=_PREVIOUS_STATES)
    current = _state("current_state", current_state, allowed=_PROJECT_STATES)
    version = _positive_int("project_version", project_version)
    policy_ref = _text("profile_policy_ref", profile_policy_ref, maximum=256)
    correlation = _text("correlation_id", correlation_id, maximum=256)
    causation = _text("causation_id", causation_id, maximum=256)
    recorded_at = _aware_datetime(occurred_at)
    namespace = f"{tenant}/{project}/v{version}/{current}"
    business_operation_id = str(
        uuid5(
            NAMESPACE_URL,
            f"https://nex-platform.local/eos/project-lifecycle/{namespace}",
        )
    )
    event_id = str(
        uuid5(
            NAMESPACE_URL, f"https://nex-platform.local/eos/project-event/{namespace}"
        )
    )
    outbox_id = str(
        uuid5(
            NAMESPACE_URL, f"https://nex-platform.local/eos/project-outbox/{namespace}"
        )
    )
    idempotency_key = f"project-lifecycle:{project}:v{version}:{current}"
    payload = {
        "schema_version": "eos.project_lifecycle_event.v1",
        "tenant_id": tenant,
        "project_id": project,
        "project_code": code,
        "previous_state": previous,
        "current_state": current,
        "project_version": version,
        "profile_policy_ref": policy_ref,
        "correlation_id": correlation,
        "causation_id": causation,
        "occurred_at": recorded_at.isoformat().replace("+00:00", "Z"),
    }
    payload_hash = semantic_sha256_hash_ref(payload)
    result = {
        "business_result_ref": f"eos.project:{project}",
        "project_id": project,
        "project_code": code,
        "project_state": current,
        "project_version": version,
    }
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
            existing["event_type"] != PROJECT_LIFECYCLE_EVENT_TYPE
            or existing["event_payload_hash"] != payload_hash
            or existing["event_payload"] != payload
        ):
            raise EosProjectLifecycleEventError(
                "Project lifecycle event identity is bound to different semantics"
            )
        return dict(existing)

    operation = {
        "tenant_id": tenant,
        "business_operation_id": business_operation_id,
        "idempotency_key": idempotency_key,
        "operation": PROJECT_LIFECYCLE_OPERATION,
        "payload_hash": payload_hash,
        "commit_state": "COMMITTED",
        "result_json": result,
        "created_at": recorded_at,
        "committed_at": recorded_at,
    }
    session.execute(EOS_BUSINESS_OPERATION_TABLE.insert().values(**operation))
    session.execute(
        EOS_IDEMPOTENCY_TABLE.insert().values(
            tenant_id=tenant,
            idempotency_key=idempotency_key,
            business_operation_id=business_operation_id,
            operation=PROJECT_LIFECYCLE_OPERATION,
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
        "business_operation_id": business_operation_id,
        "event_type": PROJECT_LIFECYCLE_EVENT_TYPE,
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


def project_lifecycle_event_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = value.get("event_payload")
    if not isinstance(payload, dict):
        raise EosProjectLifecycleEventError("Project lifecycle event payload is absent")
    return dict(payload)


def _text(field: str, value: object, *, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
        or _SCOPED_ID.fullmatch(value) is None
    ):
        raise EosProjectLifecycleEventError(f"{field} is invalid")
    return value


def _uuid(field: str, value: object) -> str:
    try:
        return str(UUID(str(value)))
    except (AttributeError, TypeError, ValueError) as exc:
        raise EosProjectLifecycleEventError(f"{field} must be a UUID") from exc


def _state(field: str, value: object, *, allowed: frozenset[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise EosProjectLifecycleEventError(f"{field} is invalid")
    return value


def _positive_int(field: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise EosProjectLifecycleEventError(f"{field} must be a positive integer")
    return value


def _aware_datetime(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise EosProjectLifecycleEventError("occurred_at must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise EosProjectLifecycleEventError("occurred_at must be timezone-aware")
    return value.astimezone(UTC)
