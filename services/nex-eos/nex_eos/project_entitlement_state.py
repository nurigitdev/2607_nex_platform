from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .project_entitlement_events import append_project_entitlement_snapshot
from .project_memberships import EOS_PROJECT_MEMBER_TABLE
from .projects import EOS_PROJECT_TABLE


class EosProjectEntitlementStateError(RuntimeError):
    error_code = "EOS_PROJECT_ENTITLEMENT_STATE_INVALID"
    status_code = 409
    retryable = False

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


def append_authoritative_project_entitlement_snapshot(
    session: Session,
    *,
    tenant_id: str,
    project_id: str,
    correlation_id: str,
    causation_id: str,
    occurred_at: datetime,
) -> dict[str, Any]:
    project = (
        session.execute(
            select(EOS_PROJECT_TABLE)
            .where(
                EOS_PROJECT_TABLE.c.tenant_id == tenant_id,
                EOS_PROJECT_TABLE.c.project_id == project_id,
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )
    if project is None:
        raise EosProjectEntitlementStateError(
            "Project entitlement source Project was not found"
        )
    if project["origin"] != "APPROVED_APPLICATION":
        raise EosProjectEntitlementStateError(
            "Legacy Project entitlement requires an explicit import boundary"
        )
    members = (
        session.execute(
            select(
                EOS_PROJECT_MEMBER_TABLE.c.subject_id,
                EOS_PROJECT_MEMBER_TABLE.c.member_role,
            )
            .where(
                EOS_PROJECT_MEMBER_TABLE.c.tenant_id == tenant_id,
                EOS_PROJECT_MEMBER_TABLE.c.project_id == project_id,
                EOS_PROJECT_MEMBER_TABLE.c.status == "ACTIVE",
            )
            .order_by(EOS_PROJECT_MEMBER_TABLE.c.subject_id)
        )
        .mappings()
        .all()
    )
    if not members:
        raise EosProjectEntitlementStateError(
            "Project entitlement source must retain an active membership"
        )
    source_version = int(project["authorization_version"]) + 1
    updated = session.execute(
        update(EOS_PROJECT_TABLE)
        .where(
            EOS_PROJECT_TABLE.c.tenant_id == tenant_id,
            EOS_PROJECT_TABLE.c.project_id == project_id,
            EOS_PROJECT_TABLE.c.authorization_version
            == project["authorization_version"],
        )
        .values(
            authorization_version=source_version,
            authorization_sync_state="PENDING",
        )
    )
    if int(updated.rowcount or 0) != 1:
        raise EosProjectEntitlementStateError(
            "Project authorization version changed concurrently"
        )
    event = append_project_entitlement_snapshot(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        project_code=str(project["project_code"]),
        project_status=str(project["status"]),
        source_version=source_version,
        members=(
            {
                "subject_id": str(member["subject_id"]),
                "project_role": str(member["member_role"]),
            }
            for member in members
        ),
        correlation_id=correlation_id,
        causation_id=causation_id,
        occurred_at=occurred_at,
    )
    return {
        "project_id": project_id,
        "project_code": str(project["project_code"]),
        "project_status": str(project["status"]),
        "source_version": source_version,
        "authorization_sync_state": "PENDING",
        "members": [
            {
                "subject_id": str(member["subject_id"]),
                "project_role": str(member["member_role"]),
            }
            for member in members
        ],
        "event_id": str(event["event_id"]),
        "event_payload_hash": str(event["event_payload_hash"]),
    }


def append_managed_project_entitlement_snapshot(
    session: Session,
    *,
    tenant_id: str,
    project_id: str,
    correlation_id: str,
    causation_id: str,
    occurred_at: datetime,
) -> dict[str, Any] | None:
    origin = session.execute(
        select(EOS_PROJECT_TABLE.c.origin).where(
            EOS_PROJECT_TABLE.c.tenant_id == tenant_id,
            EOS_PROJECT_TABLE.c.project_id == project_id,
        )
    ).scalar_one_or_none()
    if origin is None:
        raise EosProjectEntitlementStateError(
            "Project entitlement source Project was not found"
        )
    if origin != "APPROVED_APPLICATION":
        return None
    return append_authoritative_project_entitlement_snapshot(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        correlation_id=correlation_id,
        causation_id=causation_id,
        occurred_at=occurred_at,
    )


def authoritative_project_entitlement_projection(
    session: Session, *, tenant_id: str, project_id: str
) -> dict[str, Any] | None:
    project = (
        session.execute(
            select(EOS_PROJECT_TABLE).where(
                EOS_PROJECT_TABLE.c.tenant_id == tenant_id,
                EOS_PROJECT_TABLE.c.project_id == project_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if project is None:
        return None
    members = (
        session.execute(
            select(
                EOS_PROJECT_MEMBER_TABLE.c.subject_id,
                EOS_PROJECT_MEMBER_TABLE.c.member_role,
            )
            .where(
                EOS_PROJECT_MEMBER_TABLE.c.tenant_id == tenant_id,
                EOS_PROJECT_MEMBER_TABLE.c.project_id == project_id,
                EOS_PROJECT_MEMBER_TABLE.c.status == "ACTIVE",
            )
            .order_by(EOS_PROJECT_MEMBER_TABLE.c.subject_id)
        )
        .mappings()
        .all()
    )
    return {
        "tenant_id": str(project["tenant_id"]),
        "project_id": str(project["project_id"]),
        "project_code": str(project["project_code"]),
        "origin": str(project["origin"]),
        "project_status": str(project["status"]),
        "source_version": int(project["authorization_version"]),
        "authorization_sync_state": str(project["authorization_sync_state"]),
        "members": [
            {
                "subject_id": str(member["subject_id"]),
                "project_role": str(member["member_role"]),
            }
            for member in members
        ],
    }


def projection_semantics(value: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        value.get("project_id"),
        value.get("project_code"),
        value.get("project_status"),
        value.get("source_version"),
        tuple(
            (member.get("subject_id"), member.get("project_role"))
            for member in value.get("members", ())
            if isinstance(member, Mapping)
        ),
    )
