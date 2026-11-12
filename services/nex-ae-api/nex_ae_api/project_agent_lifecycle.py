from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref
from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Uuid,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

PROJECT_LIFECYCLE_EVENT_TYPE = "PROJECT_LIFECYCLE_CHANGED"
PROJECT_AGENT_PROFILE_POLICY_PATH_ENV = "NEX_AE_PROJECT_AGENT_PROFILE_POLICY_PATH"

_STATES = frozenset({"ACTIVE", "INACTIVE", "CLOSING", "CLOSED"})
_TRANSITIONS = {
    "ACTIVE": frozenset({"INACTIVE", "CLOSING"}),
    "INACTIVE": frozenset({"ACTIVE"}),
    "CLOSING": frozenset({"ACTIVE", "CLOSED"}),
    "CLOSED": frozenset(),
}
_STATE_PROJECTION = {
    "ACTIVE": ("ACTIVE", "ORDINARY"),
    "INACTIVE": ("SUSPENDED", "SUSPENDED"),
    "CLOSING": ("ACTIVE", "CLOSURE"),
    "CLOSED": ("RETIRED", "RETIRED"),
}

AE_PROJECT_AGENT_METADATA = MetaData()
AE_PROJECT_LIFECYCLE_INBOX_TABLE = Table(
    "ae_project_lifecycle_inbox",
    AE_PROJECT_AGENT_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("event_id", Uuid(as_uuid=False), primary_key=True),
    Column("business_operation_id", Uuid(as_uuid=False), nullable=False),
    Column("project_id", Uuid(as_uuid=False), nullable=False),
    Column("project_code", String(64), nullable=False),
    Column("project_state", String(16), nullable=False),
    Column("project_version", Integer, nullable=False),
    Column("profile_policy_ref", String(256), nullable=False),
    Column("event_payload_hash", String(71), nullable=False),
    Column("event_payload", JSON, nullable=False),
    Column("agent_id", Uuid(as_uuid=False), nullable=False),
    Column("received_at", DateTime(timezone=True), nullable=False),
)
AE_PROJECT_AGENT_SYNC_TABLE = Table(
    "ae_project_agent_sync",
    AE_PROJECT_AGENT_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("project_id", Uuid(as_uuid=False), primary_key=True),
    Column("project_code", String(64), nullable=False),
    Column("project_state", String(16), nullable=False),
    Column("project_version", Integer, nullable=False),
    Column("profile_policy_ref", String(256), nullable=False),
    Column("profile_policy_hash", String(71), nullable=False),
    Column("agent_id", Uuid(as_uuid=False), nullable=False),
    Column("agent_status", String(16), nullable=False),
    Column("capability_mode", String(16), nullable=False),
    Column("last_event_id", Uuid(as_uuid=False), nullable=False),
    Column("last_event_payload_hash", String(71), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)


class ProjectAgentLifecycleError(RuntimeError):
    def __init__(
        self,
        error_code: str,
        detail: str,
        *,
        status_code: int,
        retryable: bool = False,
    ) -> None:
        self.error_code = error_code
        self.detail = detail
        self.status_code = status_code
        self.retryable = retryable
        super().__init__(detail)


@dataclass(frozen=True)
class AdmittedProjectAgentProfilePolicy:
    policy_ref: str
    profile_ref: str
    policy_hash: str

    @classmethod
    def from_path(cls, path: str | Path) -> AdmittedProjectAgentProfilePolicy:
        try:
            value = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProjectAgentLifecycleError(
                "AE_PROJECT_AGENT_POLICY_UNAVAILABLE",
                "Project Agent profile policy cannot be loaded",
                status_code=503,
                retryable=True,
            ) from exc
        if not isinstance(value, dict) or set(value) != {
            "schema_version",
            "policy_ref",
            "profile_ref",
            "state_capability_modes",
            "policy_hash",
        }:
            raise _invalid("Project Agent profile policy has invalid fields")
        semantic = {key: value[key] for key in value if key != "policy_hash"}
        expected_hash = semantic_sha256_hash_ref(semantic)
        try:
            policy_hash = validate_hash_ref(value["policy_hash"])
        except (TypeError, ValueError) as exc:
            raise _invalid("Project Agent profile policy hash is invalid") from exc
        if policy_hash != expected_hash:
            raise _invalid("Project Agent profile policy hash has drifted")
        if value["schema_version"] != "ae.project_agent_profile_policy.v1":
            raise _invalid("Project Agent profile policy schema is unsupported")
        if value["state_capability_modes"] != {
            "ACTIVE": "ORDINARY",
            "INACTIVE": "SUSPENDED",
            "CLOSING": "CLOSURE",
            "CLOSED": "RETIRED",
        }:
            raise _invalid("Project Agent lifecycle capability policy has drifted")
        return cls(
            policy_ref=_required_text("policy_ref", value["policy_ref"], 256),
            profile_ref=_required_text("profile_ref", value["profile_ref"], 256),
            policy_hash=policy_hash,
        )


class SqlAlchemyProjectAgentLifecycleService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        profile_policy: AdmittedProjectAgentProfilePolicy,
        clock=None,
    ) -> None:
        self._session_factory = session_factory
        self._profile_policy = profile_policy
        self._clock = clock or (lambda: datetime.now(UTC))

    def ingest(self, envelope: object) -> tuple[dict[str, Any], bool]:
        event = _normalize_envelope(envelope)
        payload = event["event_payload"]
        if payload["profile_policy_ref"] != self._profile_policy.policy_ref:
            raise ProjectAgentLifecycleError(
                "AE_PROJECT_AGENT_POLICY_NOT_ADMITTED",
                "EOS Project lifecycle event references an unadmitted profile policy",
                status_code=409,
            )
        now = _aware_datetime(self._clock())
        try:
            with self._session_factory.begin() as session:
                existing_event = (
                    session.execute(
                        select(AE_PROJECT_LIFECYCLE_INBOX_TABLE).where(
                            AE_PROJECT_LIFECYCLE_INBOX_TABLE.c.tenant_id
                            == event["tenant_id"],
                            AE_PROJECT_LIFECYCLE_INBOX_TABLE.c.event_id
                            == event["event_id"],
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing_event is not None:
                    if (
                        existing_event["event_payload_hash"]
                        != event["event_payload_hash"]
                        or existing_event["event_payload"] != payload
                    ):
                        raise _conflict(
                            "Project lifecycle event identity changed immutable semantics"
                        )
                    return _receipt(event, str(existing_event["agent_id"])), False

                projection = (
                    session.execute(
                        select(AE_PROJECT_AGENT_SYNC_TABLE)
                        .where(
                            AE_PROJECT_AGENT_SYNC_TABLE.c.tenant_id
                            == event["tenant_id"],
                            AE_PROJECT_AGENT_SYNC_TABLE.c.project_id
                            == payload["project_id"],
                        )
                        .with_for_update()
                    )
                    .mappings()
                    .one_or_none()
                )
                _require_transition(projection, payload)
                agent_id = self._synchronize_agent(session, event, now=now)
                agent_status, capability_mode = _STATE_PROJECTION[
                    payload["current_state"]
                ]
                projection_values = {
                    "tenant_id": event["tenant_id"],
                    "project_id": payload["project_id"],
                    "project_code": payload["project_code"],
                    "project_state": payload["current_state"],
                    "project_version": payload["project_version"],
                    "profile_policy_ref": self._profile_policy.policy_ref,
                    "profile_policy_hash": self._profile_policy.policy_hash,
                    "agent_id": agent_id,
                    "agent_status": agent_status,
                    "capability_mode": capability_mode,
                    "last_event_id": event["event_id"],
                    "last_event_payload_hash": event["event_payload_hash"],
                    "updated_at": now,
                }
                if projection is None:
                    session.execute(
                        AE_PROJECT_AGENT_SYNC_TABLE.insert().values(
                            **projection_values, created_at=now
                        )
                    )
                else:
                    result = session.execute(
                        AE_PROJECT_AGENT_SYNC_TABLE.update()
                        .where(
                            AE_PROJECT_AGENT_SYNC_TABLE.c.tenant_id
                            == event["tenant_id"],
                            AE_PROJECT_AGENT_SYNC_TABLE.c.project_id
                            == payload["project_id"],
                            AE_PROJECT_AGENT_SYNC_TABLE.c.project_version
                            == projection["project_version"],
                        )
                        .values(**projection_values)
                    )
                    if int(result.rowcount or 0) != 1:
                        raise _conflict(
                            "Project Agent lifecycle projection changed concurrently"
                        )
                session.execute(
                    AE_PROJECT_LIFECYCLE_INBOX_TABLE.insert().values(
                        tenant_id=event["tenant_id"],
                        event_id=event["event_id"],
                        business_operation_id=event["business_operation_id"],
                        project_id=payload["project_id"],
                        project_code=payload["project_code"],
                        project_state=payload["current_state"],
                        project_version=payload["project_version"],
                        profile_policy_ref=payload["profile_policy_ref"],
                        event_payload_hash=event["event_payload_hash"],
                        event_payload=payload,
                        agent_id=agent_id,
                        received_at=now,
                    )
                )
            return _receipt(event, agent_id), True
        except ProjectAgentLifecycleError:
            raise
        except IntegrityError as exc:
            raise _conflict("Project Agent lifecycle changed concurrently") from exc
        except SQLAlchemyError as exc:
            raise ProjectAgentLifecycleError(
                "AE_PROJECT_AGENT_STORE_UNAVAILABLE",
                "Project Agent lifecycle persistence is unavailable",
                status_code=503,
                retryable=True,
            ) from exc

    def _synchronize_agent(
        self,
        session: Session,
        event: Mapping[str, Any],
        *,
        now: datetime,
    ) -> str:
        payload = event["event_payload"]
        rows = (
            session.execute(
                text(
                    """
                    SELECT tenant_id, agent_id, profile_ref, status, project_id, version
                    FROM ae_agent_identity
                    WHERE tenant_id = :tenant_id
                      AND agent_type = 'PA'
                      AND project_id = :project_id
                    ORDER BY created_at, agent_id
                    """
                ),
                {
                    "tenant_id": event["tenant_id"],
                    "project_id": payload["project_id"],
                },
            )
            .mappings()
            .all()
        )
        if len(rows) > 1:
            raise _conflict("More than one Project Agent is bound to the Project")
        target_status = _STATE_PROJECTION[payload["current_state"]][0]
        if not rows:
            if payload["current_state"] != "ACTIVE":
                raise _conflict("Project Agent must be initialized by an ACTIVE event")
            agent_id = str(
                uuid5(
                    NAMESPACE_URL,
                    "https://nex-platform.local/ae/project-agent/"
                    f"{event['tenant_id']}/{payload['project_id']}",
                )
            )
            session.execute(
                text(
                    """
                    INSERT INTO ae_agent_identity
                        (tenant_id, agent_id, schema_version, agent_type, profile_ref,
                         status, project_id, created_at, version)
                    VALUES
                        (:tenant_id, :agent_id, '2.1', 'PA', :profile_ref,
                         'ACTIVE', :project_id, :created_at, 1)
                    """
                ),
                {
                    "tenant_id": event["tenant_id"],
                    "agent_id": agent_id,
                    "profile_ref": self._profile_policy.profile_ref,
                    "project_id": payload["project_id"],
                    "created_at": now,
                },
            )
            return agent_id

        row = rows[0]
        if row["status"] == "RETIRED" and target_status != "RETIRED":
            raise _conflict("A retired Project Agent cannot be reactivated")
        if row["profile_ref"] != self._profile_policy.profile_ref:
            raise _conflict("Project Agent profile binding has drifted")
        if row["status"] != target_status:
            result = session.execute(
                text(
                    """
                    UPDATE ae_agent_identity
                    SET status = :status, version = version + 1
                    WHERE tenant_id = :tenant_id AND agent_id = :agent_id
                      AND version = :expected_version
                    """
                ),
                {
                    "status": target_status,
                    "tenant_id": event["tenant_id"],
                    "agent_id": str(row["agent_id"]),
                    "expected_version": int(row["version"]),
                },
            )
            if int(result.rowcount or 0) != 1:
                raise _conflict("Project Agent status changed concurrently")
        return str(row["agent_id"])


def _normalize_envelope(value: object) -> dict[str, Any]:
    expected = {
        "event_id",
        "tenant_id",
        "business_operation_id",
        "event_type",
        "event_payload_hash",
        "event_payload",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise _invalid("Project lifecycle event envelope is invalid")
    event_type = _required_text("event_type", value["event_type"], 128)
    if event_type != PROJECT_LIFECYCLE_EVENT_TYPE:
        raise _invalid("Project lifecycle event type is unsupported")
    payload = _normalize_payload(value["event_payload"])
    tenant_id = _required_text("tenant_id", value["tenant_id"], 128)
    if payload["tenant_id"] != tenant_id:
        raise _invalid("Project lifecycle tenant binding is invalid")
    try:
        payload_hash = validate_hash_ref(value["event_payload_hash"])
    except (TypeError, ValueError) as exc:
        raise _invalid("Project lifecycle event payload hash is invalid") from exc
    if semantic_sha256_hash_ref(payload) != payload_hash:
        raise _invalid("Project lifecycle event payload hash has drifted")
    return {
        "event_id": _uuid("event_id", value["event_id"]),
        "tenant_id": tenant_id,
        "business_operation_id": _uuid(
            "business_operation_id", value["business_operation_id"]
        ),
        "event_type": event_type,
        "event_payload_hash": payload_hash,
        "event_payload": payload,
    }


def _normalize_payload(value: object) -> dict[str, Any]:
    expected = {
        "schema_version",
        "tenant_id",
        "project_id",
        "project_code",
        "previous_state",
        "current_state",
        "project_version",
        "profile_policy_ref",
        "correlation_id",
        "causation_id",
        "occurred_at",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise _invalid("Project lifecycle event payload is invalid")
    if value["schema_version"] != "eos.project_lifecycle_event.v1":
        raise _invalid("Project lifecycle event schema is unsupported")
    current = _state("current_state", value["current_state"])
    previous = str(value["previous_state"])
    if previous not in {"SUBMITTED", *_STATES}:
        raise _invalid("Project lifecycle previous_state is invalid")
    occurred_at = _timestamp(value["occurred_at"])
    return {
        "schema_version": "eos.project_lifecycle_event.v1",
        "tenant_id": _required_text("tenant_id", value["tenant_id"], 128),
        "project_id": _uuid("project_id", value["project_id"]),
        "project_code": _required_text("project_code", value["project_code"], 64),
        "previous_state": previous,
        "current_state": current,
        "project_version": _positive_int("project_version", value["project_version"]),
        "profile_policy_ref": _required_text(
            "profile_policy_ref", value["profile_policy_ref"], 256
        ),
        "correlation_id": _required_text(
            "correlation_id", value["correlation_id"], 256
        ),
        "causation_id": _required_text("causation_id", value["causation_id"], 256),
        "occurred_at": occurred_at.isoformat().replace("+00:00", "Z"),
    }


def _require_transition(
    projection: Mapping[str, Any] | None, payload: Mapping[str, Any]
) -> None:
    if projection is None:
        if (
            payload["previous_state"] != "SUBMITTED"
            or payload["current_state"] != "ACTIVE"
            or payload["project_version"] != 1
        ):
            raise _conflict("Project Agent lifecycle must start with initial ACTIVE v1")
        return
    previous = str(projection["project_state"])
    if payload["project_code"] != projection["project_code"]:
        raise _conflict("Project code changed across lifecycle events")
    if payload["previous_state"] != previous:
        raise _conflict("Project lifecycle previous state does not match AE state")
    if payload["project_version"] != int(projection["project_version"]) + 1:
        raise _conflict("Project lifecycle version is not contiguous")
    if payload["current_state"] not in _TRANSITIONS[previous]:
        raise _conflict("Project lifecycle transition is not allowed")


def _receipt(event: Mapping[str, Any], agent_id: str) -> dict[str, Any]:
    payload = event["event_payload"]
    agent_status, capability_mode = _STATE_PROJECTION[payload["current_state"]]
    return {
        "schema_version": "ae.project_agent_lifecycle_receipt.v1",
        "event_id": event["event_id"],
        "event_payload_hash": event["event_payload_hash"],
        "receipt_ref": f"AE:PROJECT_AGENT:{agent_id}:v{payload['project_version']}",
        "project_id": payload["project_id"],
        "project_code": payload["project_code"],
        "project_version": payload["project_version"],
        "agent_id": agent_id,
        "agent_status": agent_status,
        "capability_mode": capability_mode,
    }


def _required_text(field: str, value: object, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
        or not value.isprintable()
    ):
        raise _invalid(f"{field} is invalid")
    return value


def _uuid(field: str, value: object) -> str:
    try:
        return str(UUID(str(value)))
    except (AttributeError, TypeError, ValueError) as exc:
        raise _invalid(f"{field} must be a UUID") from exc


def _state(field: str, value: object) -> str:
    if not isinstance(value, str) or value not in _STATES:
        raise _invalid(f"{field} is invalid")
    return value


def _positive_int(field: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _invalid(f"{field} must be a positive integer")
    return value


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise _invalid("occurred_at must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid("occurred_at must be an ISO-8601 timestamp") from exc
    return _aware_datetime(parsed)


def _aware_datetime(value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise _invalid("timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _invalid(detail: str) -> ProjectAgentLifecycleError:
    return ProjectAgentLifecycleError(
        "AE_PROJECT_AGENT_LIFECYCLE_INVALID", detail, status_code=422
    )


def _conflict(detail: str) -> ProjectAgentLifecycleError:
    return ProjectAgentLifecycleError(
        "AE_PROJECT_AGENT_LIFECYCLE_CONFLICT", detail, status_code=409
    )
