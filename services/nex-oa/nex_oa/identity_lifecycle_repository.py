from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_oa.identity_lifecycle import OaIdentityLifecycleError
from nex_oa.memberships import InMemoryOaTenantMembershipRegistry
from nex_oa.subjects import InMemoryOaSubjectRegistry, normalize_registry_id
from nex_runtime import PERSISTENCE_MODE_POSTGRES, ServicePersistenceRuntime


OA_IDENTITY_LIFECYCLE_EVENT_SCHEMA_VERSION = "oa_identity_lifecycle_event.v1"


class OaIdentityLifecycleRepository(Protocol):
    def transition_subject(
        self, plan: Mapping[str, Any], *, context: Mapping[str, Any]
    ) -> dict[str, Any]: ...

    def transition_membership(
        self, plan: Mapping[str, Any], *, context: Mapping[str, Any]
    ) -> dict[str, Any]: ...

    def list_events(
        self, *, tenant_id: str, subject_id: str, limit: int = 100
    ) -> list[dict[str, Any]]: ...


@dataclass
class InMemoryOaIdentityLifecycleRepository:
    subject_registry: InMemoryOaSubjectRegistry
    membership_registry: InMemoryOaTenantMembershipRegistry
    events: list[dict[str, Any]] = field(default_factory=list)

    def transition_subject(
        self, plan: Mapping[str, Any], *, context: Mapping[str, Any]
    ) -> dict[str, Any]:
        key = (str(plan["tenant_id"]), str(plan["subject_id"]))
        return self._transition(
            self.subject_registry.subjects.get(key), plan=plan, context=context
        )

    def transition_membership(
        self, plan: Mapping[str, Any], *, context: Mapping[str, Any]
    ) -> dict[str, Any]:
        key = (str(plan["tenant_id"]), str(plan["subject_id"]))
        return self._transition(
            self.membership_registry.memberships.get(key), plan=plan, context=context
        )

    def _transition(
        self,
        record: dict[str, Any] | None,
        *,
        plan: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> dict[str, Any]:
        if record is None:
            raise _not_found(str(plan["entity_type"]))
        _guard_record(record, plan)
        event = None
        if bool(plan["changed"]):
            record["status"] = str(plan["target_status"])
            record["revision"] = int(plan["next_revision"])
            record["updated_at"] = _utc_now()
            event = _build_event(plan, context=context)
            self.events.append(deepcopy(event))
        return _transition_result(plan, event=event)

    def list_events(
        self, *, tenant_id: str, subject_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        normalized_tenant = normalize_registry_id(tenant_id, field_name="tenant_id")
        normalized_subject = normalize_registry_id(subject_id, field_name="subject_id")
        normalized_limit = _event_limit(limit)
        return [
            _wire_event(event)
            for event in reversed(self.events)
            if event["tenant_id"] == normalized_tenant
            and event["subject_id"] == normalized_subject
        ][:normalized_limit]


class SqlAlchemyOaIdentityLifecycleRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def transition_subject(
        self, plan: Mapping[str, Any], *, context: Mapping[str, Any]
    ) -> dict[str, Any]:
        return self._run_transition(
            plan, context=context, table="oa_subjects"
        )

    def transition_membership(
        self, plan: Mapping[str, Any], *, context: Mapping[str, Any]
    ) -> dict[str, Any]:
        return self._run_transition(
            plan, context=context, table="oa_tenant_memberships"
        )

    def _run_transition(
        self,
        plan: Mapping[str, Any],
        *,
        context: Mapping[str, Any],
        table: str,
    ) -> dict[str, Any]:
        session = self._session_factory()
        try:
            try:
                event = self._apply_transition(
                    session, plan=plan, context=context, table=table
                )
                session.commit()
                return _transition_result(plan, event=event)
            except Exception:
                session.rollback()
                raise
        except OaIdentityLifecycleError:
            raise
        except SQLAlchemyError as exc:
            raise _repository_unavailable() from exc
        finally:
            session.close()

    def _apply_transition(
        self,
        session: Session,
        *,
        plan: Mapping[str, Any],
        context: Mapping[str, Any],
        table: str,
    ) -> dict[str, Any] | None:
        if not bool(plan["changed"]):
            row = _select_state(session, table=table, plan=plan)
            if row is None:
                raise _not_found(str(plan["entity_type"]))
            _guard_record(row, plan)
            return None
        result = session.execute(
            text(
                f"""
                UPDATE {table}
                SET status = :target_status,
                    revision = :next_revision,
                    updated_at = :updated_at
                WHERE tenant_id = :tenant_id
                  AND subject_id = :subject_id
                  AND subject_ref_type = 'oa.user'
                  AND status = :previous_status
                  AND revision = :expected_revision
                """
            ),
            {**_plan_params(plan), "updated_at": _utc_now()},
        )
        if result.rowcount != 1:
            raise _revision_conflict()
        event = _build_event(plan, context=context)
        session.execute(
            text(
                """
                INSERT INTO oa_id_lifecycle_events (
                    event_id, tenant_id, subject_id, entity_type,
                    previous_status, target_status,
                    previous_revision, next_revision, reason_code,
                    actor_ref_type, actor_ref_id, request_id, trace_id, occurred_at
                ) VALUES (
                    :event_id, :tenant_id, :subject_id, :entity_type,
                    :previous_status, :target_status,
                    :previous_revision, :next_revision, :reason_code,
                    :actor_ref_type, :actor_ref_id, :request_id, :trace_id, :occurred_at
                )
                """
            ),
            event,
        )
        return event

    def list_events(
        self, *, tenant_id: str, subject_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        normalized_tenant = normalize_registry_id(tenant_id, field_name="tenant_id")
        normalized_subject = normalize_registry_id(subject_id, field_name="subject_id")
        normalized_limit = _event_limit(limit)
        try:
            with self._session_factory() as session:
                rows = session.execute(
                    text(
                        """
                        SELECT event_id, tenant_id, subject_id, entity_type,
                               previous_status, target_status,
                               previous_revision, next_revision, reason_code,
                               actor_ref_type, actor_ref_id, request_id, trace_id,
                               occurred_at
                        FROM oa_id_lifecycle_events
                        WHERE tenant_id = :tenant_id AND subject_id = :subject_id
                        ORDER BY occurred_at DESC, event_id DESC
                        LIMIT :limit
                        """
                    ),
                    {
                        "tenant_id": normalized_tenant,
                        "subject_id": normalized_subject,
                        "limit": normalized_limit,
                    },
                ).mappings()
                return [_event_from_row(row) for row in rows]
        except SQLAlchemyError as exc:
            raise _repository_unavailable() from exc


def build_identity_lifecycle_repository_for_runtime(
    runtime: ServicePersistenceRuntime,
    *,
    subject_registry: InMemoryOaSubjectRegistry,
    membership_registry: InMemoryOaTenantMembershipRegistry,
) -> OaIdentityLifecycleRepository:
    if (
        runtime.mode == PERSISTENCE_MODE_POSTGRES
        and runtime.api_session_factory is not None
    ):
        return SqlAlchemyOaIdentityLifecycleRepository(runtime.api_session_factory)
    return InMemoryOaIdentityLifecycleRepository(
        subject_registry=subject_registry,
        membership_registry=membership_registry,
    )


def _select_state(
    session: Session, *, table: str, plan: Mapping[str, Any]
) -> Mapping[str, Any] | None:
    return session.execute(
        text(
            f"""
            SELECT status, revision
            FROM {table}
            WHERE tenant_id = :tenant_id
              AND subject_id = :subject_id
              AND subject_ref_type = 'oa.user'
            """
        ),
        _plan_params(plan),
    ).mappings().first()


def _guard_record(record: Mapping[str, Any], plan: Mapping[str, Any]) -> None:
    if (
        str(record.get("status")) != str(plan["previous_status"])
        or int(record.get("revision", 1)) != int(plan["expected_revision"])
    ):
        raise _revision_conflict()


def _build_event(
    plan: Mapping[str, Any], *, context: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "event_id": str(uuid4()),
        "tenant_id": normalize_registry_id(plan.get("tenant_id"), field_name="tenant_id"),
        "subject_id": normalize_registry_id(plan.get("subject_id"), field_name="subject_id"),
        "entity_type": str(plan["entity_type"]),
        "previous_status": str(plan["previous_status"]),
        "target_status": str(plan["target_status"]),
        "previous_revision": int(plan["expected_revision"]),
        "next_revision": int(plan["next_revision"]),
        "reason_code": str(plan["reason_code"]),
        "actor_ref_type": _context_text(context, "actor_ref_type"),
        "actor_ref_id": normalize_registry_id(
            context.get("actor_ref_id"), field_name="actor_ref_id"
        ),
        "request_id": normalize_registry_id(
            context.get("request_id"), field_name="request_id"
        ),
        "trace_id": normalize_registry_id(context.get("trace_id"), field_name="trace_id"),
        "occurred_at": _utc_now(),
    }


def _transition_result(
    plan: Mapping[str, Any], *, event: Mapping[str, Any] | None
) -> dict[str, Any]:
    return {
        "lifecycle_schema_version": str(plan["lifecycle_schema_version"]),
        "entity_type": str(plan["entity_type"]),
        "tenant_id": str(plan["tenant_id"]),
        "subject_id": str(plan["subject_id"]),
        "status": str(plan["target_status"]),
        "revision": int(plan["next_revision"]),
        "changed": bool(plan["changed"]),
        "event": _wire_event(event) if event is not None else None,
    }


def _wire_event(event: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "event_schema_version": OA_IDENTITY_LIFECYCLE_EVENT_SCHEMA_VERSION,
        **deepcopy(dict(event)),
    }


def _event_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    event = {
        key: str(row[key])
        for key in (
            "event_id",
            "tenant_id",
            "subject_id",
            "entity_type",
            "previous_status",
            "target_status",
            "reason_code",
            "actor_ref_type",
            "actor_ref_id",
            "request_id",
            "trace_id",
        )
    }
    event.update(
        previous_revision=int(row["previous_revision"]),
        next_revision=int(row["next_revision"]),
        occurred_at=_timestamp_to_wire(row["occurred_at"]),
    )
    return _wire_event(event)


def _plan_params(plan: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "tenant_id": str(plan["tenant_id"]),
        "subject_id": str(plan["subject_id"]),
        "previous_status": str(plan["previous_status"]),
        "target_status": str(plan["target_status"]),
        "expected_revision": int(plan["expected_revision"]),
        "next_revision": int(plan["next_revision"]),
    }


def _event_limit(value: object) -> int:
    if isinstance(value, bool):
        raise _limit_error()
    try:
        limit = int(value)
    except (TypeError, ValueError) as exc:
        raise _limit_error() from exc
    if limit < 1 or limit > 500 or str(value) != str(limit):
        raise _limit_error()
    return limit


def _context_text(context: Mapping[str, Any], field_name: str) -> str:
    value = context.get(field_name)
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 128:
        raise OaIdentityLifecycleError(
            status_code=400,
            error_code="oa.lifecycle_context_invalid",
            detail=f"{field_name} must be a non-empty string of at most 128 characters.",
        )
    return value.strip()


def _limit_error() -> OaIdentityLifecycleError:
    return OaIdentityLifecycleError(
        status_code=400,
        error_code="oa.lifecycle_event_limit_invalid",
        detail="limit must be an integer between 1 and 500.",
    )


def _not_found(entity_type: str) -> OaIdentityLifecycleError:
    return OaIdentityLifecycleError(
        status_code=404,
        error_code="oa.lifecycle_target_not_found",
        detail=f"{entity_type.lower()} lifecycle target was not found.",
    )


def _revision_conflict() -> OaIdentityLifecycleError:
    return OaIdentityLifecycleError(
        status_code=409,
        error_code="oa.lifecycle_revision_conflict",
        detail="lifecycle state changed before this write could be applied.",
    )


def _repository_unavailable() -> OaIdentityLifecycleError:
    return OaIdentityLifecycleError(
        status_code=503,
        error_code="oa.lifecycle_repository_unavailable",
        detail="identity lifecycle persistence is temporarily unavailable.",
    )


def _timestamp_to_wire(value: Any) -> str:
    if isinstance(value, datetime):
        normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return normalized.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return str(value)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
