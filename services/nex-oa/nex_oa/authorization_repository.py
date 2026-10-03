from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_oa.authorization import (
    OaAuthorizationError,
    plan_group_member_upsert,
    plan_group_role_upsert,
    plan_group_upsert,
    plan_role_upsert,
)
from nex_oa.subjects import SubjectRegistryError, normalize_registry_id
from nex_oa.sessions import InMemoryOaSessionRegistry, build_revoked_session_record
from nex_runtime import PERSISTENCE_MODE_POSTGRES, ServicePersistenceRuntime


OA_AUTHORIZATION_EVENT_SCHEMA_VERSION = "oa_authz_event.v1"


class OaAuthorizationRepository(Protocol):
    def upsert_role(
        self, payload: Mapping[str, Any], *, context: Mapping[str, Any]
    ) -> dict[str, Any]: ...

    def upsert_group(
        self, payload: Mapping[str, Any], *, context: Mapping[str, Any]
    ) -> dict[str, Any]: ...

    def upsert_group_member(
        self, payload: Mapping[str, Any], *, context: Mapping[str, Any]
    ) -> dict[str, Any]: ...

    def upsert_group_role(
        self, payload: Mapping[str, Any], *, context: Mapping[str, Any]
    ) -> dict[str, Any]: ...

    def authorization_inputs(
        self, *, tenant_id: str, subject_id: str
    ) -> dict[str, list[dict[str, Any]]]: ...

    def list_events(self, *, tenant_id: str, limit: int = 100) -> list[dict[str, Any]]: ...


Planner = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class _EntityConfig:
    entity_type: str
    table: str
    keys: tuple[str, ...]
    columns: tuple[str, ...]
    mutable: tuple[str, ...]
    planner: Planner
    json_columns: tuple[str, ...] = ()


_CONFIGS = {
    "ROLE": _EntityConfig(
        "ROLE",
        "oa_roles",
        ("tenant_id", "role_id"),
        (
            "tenant_id",
            "role_id",
            "role_schema_version",
            "display_name",
            "description",
            "status",
            "revision",
            "scopes",
            "metadata",
        ),
        ("display_name", "description", "status", "revision", "scopes", "metadata"),
        plan_role_upsert,
        ("scopes", "metadata"),
    ),
    "GROUP": _EntityConfig(
        "GROUP",
        "oa_groups",
        ("tenant_id", "group_id"),
        (
            "tenant_id",
            "group_id",
            "group_schema_version",
            "display_name",
            "description",
            "status",
            "revision",
            "metadata",
        ),
        ("display_name", "description", "status", "revision", "metadata"),
        plan_group_upsert,
        ("metadata",),
    ),
    "GROUP_MEMBER": _EntityConfig(
        "GROUP_MEMBER",
        "oa_group_members",
        ("tenant_id", "group_id", "subject_id"),
        ("tenant_id", "group_id", "subject_ref_type", "subject_id", "status", "revision"),
        ("status", "revision"),
        plan_group_member_upsert,
    ),
    "GROUP_ROLE": _EntityConfig(
        "GROUP_ROLE",
        "oa_group_roles",
        ("tenant_id", "group_id", "role_id"),
        ("tenant_id", "group_id", "role_id", "status", "revision"),
        ("status", "revision"),
        plan_group_role_upsert,
    ),
}


@dataclass
class InMemoryOaAuthorizationRepository:
    roles: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    groups: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    group_members: dict[tuple[str, str, str], dict[str, Any]] = field(default_factory=dict)
    group_roles: dict[tuple[str, str, str], dict[str, Any]] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    session_registry: InMemoryOaSessionRegistry | None = None

    def upsert_role(
        self, payload: Mapping[str, Any], *, context: Mapping[str, Any]
    ) -> dict[str, Any]:
        return self._upsert("ROLE", payload, context=context)

    def upsert_group(
        self, payload: Mapping[str, Any], *, context: Mapping[str, Any]
    ) -> dict[str, Any]:
        return self._upsert("GROUP", payload, context=context)

    def upsert_group_member(
        self, payload: Mapping[str, Any], *, context: Mapping[str, Any]
    ) -> dict[str, Any]:
        self._require_group(payload)
        return self._upsert("GROUP_MEMBER", payload, context=context)

    def upsert_group_role(
        self, payload: Mapping[str, Any], *, context: Mapping[str, Any]
    ) -> dict[str, Any]:
        self._require_group(payload)
        tenant_id = str(payload.get("tenant_id") or "").strip()
        role_id = str(payload.get("role_id") or "").strip().lower()
        if (tenant_id, role_id) not in self.roles:
            raise _reference_not_found("role")
        return self._upsert("GROUP_ROLE", payload, context=context)

    def _require_group(self, payload: Mapping[str, Any]) -> None:
        tenant_id = str(payload.get("tenant_id") or "").strip()
        group_id = str(payload.get("group_id") or "").strip().lower()
        if (tenant_id, group_id) not in self.groups:
            raise _reference_not_found("group")

    def _upsert(
        self,
        entity_type: str,
        payload: Mapping[str, Any],
        *,
        context: Mapping[str, Any],
    ) -> dict[str, Any]:
        config = _CONFIGS[entity_type]
        store = self._store(entity_type)
        key = _payload_key(config, payload)
        current = store.get(key)
        planned = config.planner(payload, current=current)
        affected_subject_ids = self._affected_subject_ids(entity_type, planned)
        event = _build_event(config, planned, context=context)
        store[key] = deepcopy(planned)
        revoked_session_count = self._revoke_sessions(
            tenant_id=str(planned["tenant_id"]),
            subject_ids=affected_subject_ids,
        )
        event["details"]["revoked_session_count"] = revoked_session_count
        self.events.append(deepcopy(event))
        return _result(
            planned,
            event,
            revoked_session_count=revoked_session_count,
            affected_subject_ids=affected_subject_ids,
        )

    def _store(self, entity_type: str) -> dict[Any, dict[str, Any]]:
        return {
            "ROLE": self.roles,
            "GROUP": self.groups,
            "GROUP_MEMBER": self.group_members,
            "GROUP_ROLE": self.group_roles,
        }[entity_type]

    def _affected_subject_ids(
        self, entity_type: str, record: Mapping[str, Any]
    ) -> tuple[str, ...]:
        tenant_id = str(record["tenant_id"])
        if entity_type == "GROUP_MEMBER":
            return (str(record["subject_id"]),)
        group_ids: set[str]
        if entity_type in {"GROUP", "GROUP_ROLE"}:
            group_ids = {str(record["group_id"])}
        elif entity_type == "ROLE":
            role_id = str(record["role_id"])
            group_ids = {
                str(item["group_id"])
                for item in self.group_roles.values()
                if item["tenant_id"] == tenant_id and item["role_id"] == role_id
            }
        else:
            group_ids = set()
        return tuple(
            sorted(
                {
                    str(item["subject_id"])
                    for item in self.group_members.values()
                    if item["tenant_id"] == tenant_id
                    and item["group_id"] in group_ids
                }
            )
        )

    def _revoke_sessions(
        self, *, tenant_id: str, subject_ids: tuple[str, ...]
    ) -> int:
        if self.session_registry is None or not subject_ids:
            return 0
        revoked = 0
        subject_set = set(subject_ids)
        for session_id, record in tuple(self.session_registry.sessions.items()):
            tenant_ref = record.get("tenant_ref") or {}
            subject_ref = record.get("subject_ref") or {}
            if (
                record.get("status") == "ACTIVE"
                and tenant_ref.get("id") == tenant_id
                and subject_ref.get("id") in subject_set
            ):
                updated, _, _ = build_revoked_session_record(record)
                self.session_registry.sessions[session_id] = deepcopy(updated)
                revoked += 1
        return revoked

    def authorization_inputs(
        self, *, tenant_id: str, subject_id: str
    ) -> dict[str, list[dict[str, Any]]]:
        tenant = _normalize_ref(tenant_id, field_name="tenant_id")
        subject = _normalize_ref(subject_id, field_name="subject_id")
        return {
            "roles": _tenant_records(self.roles.values(), tenant),
            "groups": _tenant_records(self.groups.values(), tenant),
            "group_members": [
                deepcopy(item)
                for item in self.group_members.values()
                if item["tenant_id"] == tenant and item["subject_id"] == subject
            ],
            "group_roles": _tenant_records(self.group_roles.values(), tenant),
        }

    def list_events(self, *, tenant_id: str, limit: int = 100) -> list[dict[str, Any]]:
        tenant = _normalize_ref(tenant_id, field_name="tenant_id")
        normalized_limit = _event_limit(limit)
        return [
            _wire_event(item)
            for item in reversed(self.events)
            if item["tenant_id"] == tenant
        ][:normalized_limit]


class SqlAlchemyOaAuthorizationRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def upsert_role(
        self, payload: Mapping[str, Any], *, context: Mapping[str, Any]
    ) -> dict[str, Any]:
        return self._upsert("ROLE", payload, context=context)

    def upsert_group(
        self, payload: Mapping[str, Any], *, context: Mapping[str, Any]
    ) -> dict[str, Any]:
        return self._upsert("GROUP", payload, context=context)

    def upsert_group_member(
        self, payload: Mapping[str, Any], *, context: Mapping[str, Any]
    ) -> dict[str, Any]:
        return self._upsert("GROUP_MEMBER", payload, context=context)

    def upsert_group_role(
        self, payload: Mapping[str, Any], *, context: Mapping[str, Any]
    ) -> dict[str, Any]:
        return self._upsert("GROUP_ROLE", payload, context=context)

    def _upsert(
        self,
        entity_type: str,
        payload: Mapping[str, Any],
        *,
        context: Mapping[str, Any],
    ) -> dict[str, Any]:
        config = _CONFIGS[entity_type]
        session = self._session_factory()
        try:
            try:
                current = _select_record(session, config=config, payload=payload)
                planned = config.planner(payload, current=current)
                affected_subject_ids = _select_affected_subject_ids(
                    session,
                    entity_type=entity_type,
                    record=planned,
                )
                if current is None:
                    _insert_record(session, config=config, record=planned)
                else:
                    _update_record(session, config=config, record=planned)
                event = _build_event(config, planned, context=context)
                revoked_session_count = _revoke_sql_sessions(
                    session,
                    tenant_id=str(planned["tenant_id"]),
                    subject_ids=affected_subject_ids,
                )
                event["details"]["revoked_session_count"] = revoked_session_count
                _insert_event(session, event)
                session.commit()
                return _result(
                    planned,
                    event,
                    revoked_session_count=revoked_session_count,
                    affected_subject_ids=affected_subject_ids,
                )
            except Exception:
                session.rollback()
                raise
        except OaAuthorizationError:
            raise
        except IntegrityError as exc:
            raise _reference_not_found("authorization") from exc
        except SQLAlchemyError as exc:
            raise _repository_unavailable() from exc
        finally:
            session.close()

    def authorization_inputs(
        self, *, tenant_id: str, subject_id: str
    ) -> dict[str, list[dict[str, Any]]]:
        tenant = _normalize_ref(tenant_id, field_name="tenant_id")
        subject = _normalize_ref(subject_id, field_name="subject_id")
        try:
            with self._session_factory() as session:
                return {
                    "roles": _select_rows(
                        session,
                        "SELECT * FROM oa_roles WHERE tenant_id = :tenant_id",
                        {"tenant_id": tenant},
                        json_columns=("scopes", "metadata"),
                    ),
                    "groups": _select_rows(
                        session,
                        "SELECT * FROM oa_groups WHERE tenant_id = :tenant_id",
                        {"tenant_id": tenant},
                        json_columns=("metadata",),
                    ),
                    "group_members": _select_rows(
                        session,
                        "SELECT * FROM oa_group_members "
                        "WHERE tenant_id = :tenant_id AND subject_id = :subject_id",
                        {"tenant_id": tenant, "subject_id": subject},
                    ),
                    "group_roles": _select_rows(
                        session,
                        "SELECT * FROM oa_group_roles WHERE tenant_id = :tenant_id",
                        {"tenant_id": tenant},
                    ),
                }
        except SQLAlchemyError as exc:
            raise _repository_unavailable() from exc

    def list_events(self, *, tenant_id: str, limit: int = 100) -> list[dict[str, Any]]:
        tenant = _normalize_ref(tenant_id, field_name="tenant_id")
        normalized_limit = _event_limit(limit)
        try:
            with self._session_factory() as session:
                rows = _select_rows(
                    session,
                    "SELECT * FROM oa_authz_events WHERE tenant_id = :tenant_id "
                    "ORDER BY occurred_at DESC, event_id DESC LIMIT :limit",
                    {"tenant_id": tenant, "limit": normalized_limit},
                    json_columns=("details",),
                )
                return [_wire_event(item) for item in rows]
        except SQLAlchemyError as exc:
            raise _repository_unavailable() from exc


def build_authorization_repository_for_runtime(
    runtime: ServicePersistenceRuntime,
) -> OaAuthorizationRepository:
    if runtime.mode == PERSISTENCE_MODE_POSTGRES and runtime.api_session_factory is not None:
        return SqlAlchemyOaAuthorizationRepository(runtime.api_session_factory)
    return InMemoryOaAuthorizationRepository()


def bind_authorization_session_registry(
    repository: OaAuthorizationRepository,
    session_registry: object,
) -> None:
    if isinstance(repository, InMemoryOaAuthorizationRepository) and isinstance(
        session_registry, InMemoryOaSessionRegistry
    ):
        repository.session_registry = session_registry


def _payload_key(config: _EntityConfig, payload: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(str(payload.get(key) or "").strip().lower() for key in config.keys)


def _select_record(
    session: Session,
    *,
    config: _EntityConfig,
    payload: Mapping[str, Any],
) -> dict[str, Any] | None:
    where = " AND ".join(f"{key} = :{key}" for key in config.keys)
    params = {key: str(payload.get(key) or "").strip().lower() for key in config.keys}
    row = session.execute(
        text(f"SELECT * FROM {config.table} WHERE {where}"), params
    ).mappings().first()
    return _decode_row(row, config.json_columns) if row is not None else None


def _insert_record(
    session: Session,
    *,
    config: _EntityConfig,
    record: Mapping[str, Any],
) -> None:
    params = _record_params(config, record)
    columns = ", ".join(config.columns)
    values = ", ".join(
        _json_expression(session, column) if column in config.json_columns else f":{column}"
        for column in config.columns
    )
    session.execute(text(f"INSERT INTO {config.table} ({columns}) VALUES ({values})"), params)


def _update_record(
    session: Session,
    *,
    config: _EntityConfig,
    record: Mapping[str, Any],
) -> None:
    params = _record_params(config, record)
    params["expected_revision"] = int(record["previous_revision"])
    assignments = ", ".join(
        f"{column} = "
        + (_json_expression(session, column) if column in config.json_columns else f":{column}")
        for column in config.mutable
    )
    where = " AND ".join(f"{key} = :{key}" for key in config.keys)
    result = session.execute(
        text(
            f"UPDATE {config.table} SET {assignments}, updated_at = :updated_at "
            f"WHERE {where} AND revision = :expected_revision"
        ),
        {**params, "updated_at": _utc_now()},
    )
    if result.rowcount != 1:
        raise _revision_conflict()


def _record_params(config: _EntityConfig, record: Mapping[str, Any]) -> dict[str, Any]:
    params = {column: record.get(column) for column in config.columns}
    if "subject_ref_type" in params:
        params["subject_ref_type"] = "oa.user"
    for column in config.json_columns:
        params[column] = json.dumps(params[column], sort_keys=True, separators=(",", ":"))
    return params


def _insert_event(session: Session, event: Mapping[str, Any]) -> None:
    details_expression = _json_expression(session, "details")
    session.execute(
        text(
            "INSERT INTO oa_authz_events ("
            "event_id, event_schema_version, tenant_id, event_type, entity_type, "
            "entity_id, subject_id, previous_revision, next_revision, actor_ref, "
            "request_id, trace_id, details, occurred_at"
            ") VALUES ("
            ":event_id, :event_schema_version, :tenant_id, :event_type, :entity_type, "
            ":entity_id, :subject_id, :previous_revision, :next_revision, :actor_ref, "
            f":request_id, :trace_id, {details_expression}, :occurred_at)"
        ),
        {**event, "details": json.dumps(event["details"], sort_keys=True)},
    )


def _build_event(
    config: _EntityConfig,
    record: Mapping[str, Any],
    *,
    context: Mapping[str, Any],
) -> dict[str, Any]:
    entity_parts = [str(record[key]) for key in config.keys if key != "tenant_id"]
    return {
        "event_id": str(uuid4()),
        "event_schema_version": OA_AUTHORIZATION_EVENT_SCHEMA_VERSION,
        "tenant_id": str(record["tenant_id"]),
        "event_type": f"{config.entity_type}_UPSERTED",
        "entity_type": config.entity_type,
        "entity_id": ":".join(entity_parts),
        "subject_id": record.get("subject_id"),
        "previous_revision": int(record["previous_revision"]),
        "next_revision": int(record["revision"]),
        "actor_ref": _context_text(context, "actor_ref"),
        "request_id": _context_text(context, "request_id"),
        "trace_id": _context_text(context, "trace_id"),
        "details": {"status": str(record["status"])},
        "occurred_at": _utc_now(),
    }


def _select_affected_subject_ids(
    session: Session,
    *,
    entity_type: str,
    record: Mapping[str, Any],
) -> tuple[str, ...]:
    if entity_type == "GROUP_MEMBER":
        return (str(record["subject_id"]),)
    params = {"tenant_id": record["tenant_id"]}
    if entity_type in {"GROUP", "GROUP_ROLE"}:
        params["group_id"] = record["group_id"]
        sql = (
            "SELECT DISTINCT subject_id FROM oa_group_members "
            "WHERE tenant_id = :tenant_id AND group_id = :group_id"
        )
    elif entity_type == "ROLE":
        params["role_id"] = record["role_id"]
        sql = (
            "SELECT DISTINCT gm.subject_id FROM oa_group_members gm "
            "JOIN oa_group_roles gr ON gr.tenant_id = gm.tenant_id "
            "AND gr.group_id = gm.group_id "
            "WHERE gm.tenant_id = :tenant_id AND gr.role_id = :role_id"
        )
    else:
        return ()
    return tuple(
        sorted(
            str(row["subject_id"])
            for row in session.execute(text(sql), params).mappings()
        )
    )


def _revoke_sql_sessions(
    session: Session,
    *,
    tenant_id: str,
    subject_ids: tuple[str, ...],
) -> int:
    if not subject_ids:
        return 0
    now = _utc_now()
    revoked = 0
    for subject_id in subject_ids:
        result = session.execute(
            text(
                "UPDATE oa_user_sessions SET status = 'REVOKED', "
                "revoked_at = :revoked_at, updated_at = :updated_at "
                "WHERE tenant_id = :tenant_id AND subject_id = :subject_id "
                "AND status = 'ACTIVE'"
            ),
            {
                "tenant_id": tenant_id,
                "subject_id": subject_id,
                "revoked_at": now,
                "updated_at": now,
            },
        )
        revoked += int(result.rowcount or 0)
    return revoked


def _result(
    record: Mapping[str, Any],
    event: Mapping[str, Any],
    *,
    revoked_session_count: int,
    affected_subject_ids: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "record": deepcopy(dict(record)),
        "event": _wire_event(event),
        "affected_subject_ids": list(affected_subject_ids),
        "revoked_session_count": revoked_session_count,
    }


def _wire_event(event: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(event))
    occurred_at = result.get("occurred_at")
    if isinstance(occurred_at, datetime):
        normalized = occurred_at if occurred_at.tzinfo else occurred_at.replace(tzinfo=UTC)
        result["occurred_at"] = normalized.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return result


def _select_rows(
    session: Session,
    sql: str,
    params: Mapping[str, Any],
    *,
    json_columns: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    return [
        _decode_row(row, json_columns)
        for row in session.execute(text(sql), dict(params)).mappings()
    ]


def _decode_row(row: Mapping[str, Any], json_columns: tuple[str, ...]) -> dict[str, Any]:
    result = dict(row)
    for column in json_columns:
        value = result.get(column)
        if isinstance(value, str):
            result[column] = json.loads(value)
    return result


def _json_expression(session: Session, parameter: str) -> str:
    return f"CAST(:{parameter} AS JSONB)" if session.bind.dialect.name == "postgresql" else f":{parameter}"


def _tenant_records(records: Any, tenant_id: str) -> list[dict[str, Any]]:
    return [deepcopy(item) for item in records if item["tenant_id"] == tenant_id]


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


def _normalize_ref(value: object, *, field_name: str) -> str:
    try:
        return normalize_registry_id(value, field_name=field_name)
    except SubjectRegistryError as exc:
        raise OaAuthorizationError(
            status_code=400,
            error_code="oa.authorization_reference_invalid",
            detail=f"{field_name} must be a valid non-empty reference.",
        ) from exc


def _context_text(context: Mapping[str, Any], field_name: str) -> str:
    value = context.get(field_name)
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 128:
        raise OaAuthorizationError(
            status_code=400,
            error_code="oa.authorization_context_invalid",
            detail=f"{field_name} must be a non-empty string of at most 128 characters.",
        )
    return value.strip()


def _limit_error() -> OaAuthorizationError:
    return OaAuthorizationError(
        status_code=400,
        error_code="oa.authorization_event_limit_invalid",
        detail="limit must be an integer between 1 and 500.",
    )


def _reference_not_found(name: str) -> OaAuthorizationError:
    return OaAuthorizationError(
        status_code=409,
        error_code="oa.authorization_reference_not_found",
        detail=f"referenced {name} was not found.",
    )


def _revision_conflict() -> OaAuthorizationError:
    return OaAuthorizationError(
        status_code=409,
        error_code="oa.authorization_revision_conflict",
        detail="authorization state changed before this write could be applied.",
    )


def _repository_unavailable() -> OaAuthorizationError:
    return OaAuthorizationError(
        status_code=503,
        error_code="oa.authorization_repository_unavailable",
        detail="authorization persistence is temporarily unavailable.",
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
