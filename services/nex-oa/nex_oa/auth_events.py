from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
import logging
from typing import Any, Protocol
from uuid import uuid4

from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_oa.subjects import SubjectRegistryError, normalize_registry_id
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    PERSISTENCE_MODE_POSTGRES,
    ServicePersistenceRuntime,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
    validate_authorization_header,
)

LOGGER = logging.getLogger(__name__)
OA_AUTH_EVENT_SCHEMA_VERSION = "oa_auth_event.v1"
OA_AUTH_EVENT_LIST_SCHEMA_VERSION = "oa_auth_event_list.v1"
OA_CREDENTIAL_SECURITY_READ_SCOPE = "credential:security:read"
AUTH_EVENT_TYPES = frozenset(
    {
        "LOGIN_SUCCEEDED",
        "LOGIN_FAILED",
        "FEDERATED_LOGIN_SUCCEEDED",
        "FEDERATED_LOGIN_FAILED",
        "PASSWORD_CHANGED",
        "PASSWORD_RESET",
        "SESSION_ISSUED",
        "SESSION_INTROSPECTED",
        "SESSION_REVOKED",
        "TOKEN_VALIDATION_FAILED",
        "SERVICE_AUTH_FAILED",
    }
)
AUTH_EVENT_OUTCOMES = frozenset({"SUCCEEDED", "FAILED", "BLOCKED"})
SAFE_DETAIL_FIELDS = frozenset(
    {
        "active",
        "already_revoked",
        "credential_status",
        "error_code",
        "inactive_reason",
        "operation",
        "auth_method",
        "provider_id",
        "revoked",
        "revoked_session_count",
    }
)


@dataclass(frozen=True)
class OaAuthEventError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class OaAuthEventRepository(Protocol):
    def record_event(self, payload: Mapping[str, Any]) -> dict[str, Any]: ...

    def list_events(
        self,
        *,
        tenant_id: str,
        subject_id: str | None = None,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]: ...

    def list_events_by_trace(
        self,
        trace_id: str,
        *,
        limit: int = 500,
    ) -> list[dict[str, Any]]: ...


@dataclass
class InMemoryOaAuthEventRepository:
    events: list[dict[str, Any]] = field(default_factory=list)

    def record_event(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        event = build_auth_event(payload)
        self.events.append(deepcopy(event))
        return project_auth_event(event)

    def list_events(
        self,
        *,
        tenant_id: str,
        subject_id: str | None = None,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        query = normalize_event_query(
            tenant_id=tenant_id,
            subject_id=subject_id,
            event_type=event_type,
            limit=limit,
        )
        return [
            project_auth_event(event)
            for event in reversed(self.events)
            if _event_matches(event, query)
        ][: query["limit"]]

    def list_events_by_trace(
        self,
        trace_id: str,
        *,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        return [
            project_auth_event(event)
            for event in reversed(self.events)
            if event.get("trace_id") == trace_id
        ][:limit]


class SqlAlchemyOaAuthEventRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def record_event(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        event = build_auth_event(payload)
        session = self._session_factory()
        try:
            try:
                details_expression = _json_sql_expression(session, "details")
                session.execute(
                    text(f"""
                        INSERT INTO oa_auth_events (
                            event_id, event_schema_version, event_type, outcome,
                            tenant_id, subject_id, credential_id, actor_ref,
                            request_id, trace_id, details, occurred_at, created_at
                        ) VALUES (
                            :event_id, :event_schema_version, :event_type, :outcome,
                            :tenant_id, :subject_id, :credential_id, :actor_ref,
                            :request_id, :trace_id, {details_expression},
                            :occurred_at, :created_at
                        )
                        """),
                    {**event, "details": json.dumps(event["details"], sort_keys=True)},
                )
                session.commit()
            except Exception:
                session.rollback()
                raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc
        finally:
            session.close()
        return project_auth_event(event)

    def list_events(
        self,
        *,
        tenant_id: str,
        subject_id: str | None = None,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        query = normalize_event_query(
            tenant_id=tenant_id,
            subject_id=subject_id,
            event_type=event_type,
            limit=limit,
        )
        clauses = ["tenant_id = :tenant_id"]
        if query["subject_id"] is not None:
            clauses.append("subject_id = :subject_id")
        if query["event_type"] is not None:
            clauses.append("event_type = :event_type")
        try:
            with self._session_factory() as session:
                rows = session.execute(
                    text(
                        """
                        SELECT event_id, event_schema_version, event_type, outcome,
                               tenant_id, subject_id, credential_id, actor_ref,
                               request_id, trace_id, details, occurred_at, created_at
                        FROM oa_auth_events
                        WHERE """
                        + " AND ".join(clauses)
                        + " ORDER BY occurred_at DESC, event_id DESC LIMIT :limit"
                    ),
                    query,
                ).mappings()
                return [project_auth_event(_event_from_row(row)) for row in rows]
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def list_events_by_trace(
        self,
        trace_id: str,
        *,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        try:
            with self._session_factory() as session:
                rows = session.execute(
                    text("""
                        SELECT event_id, event_schema_version, event_type, outcome,
                               tenant_id, subject_id, credential_id, actor_ref,
                               request_id, trace_id, details, occurred_at, created_at
                        FROM oa_auth_events
                        WHERE trace_id = :trace_id
                        ORDER BY occurred_at DESC, event_id DESC
                        LIMIT :limit
                        """),
                    {"trace_id": trace_id, "limit": limit},
                ).mappings()
                return [project_auth_event(_event_from_row(row)) for row in rows]
        except SQLAlchemyError as exc:
            raise _unavailable() from exc


def build_auth_event_repository_for_runtime(
    runtime: ServicePersistenceRuntime,
) -> OaAuthEventRepository:
    if (
        runtime.mode == PERSISTENCE_MODE_POSTGRES
        and runtime.api_session_factory is not None
    ):
        return SqlAlchemyOaAuthEventRepository(runtime.api_session_factory)
    return InMemoryOaAuthEventRepository()


def register_auth_event_routes(
    app: FastAPI, *, repository: OaAuthEventRepository
) -> None:
    @app.get("/internal/v1/auth/security-events", response_model=None)
    def list_auth_security_events(
        request: Request,
        tenant_id: str,
        subject_id: str | None = None,
        event_type: str | None = None,
        limit: int = Query(default=100, ge=1, le=200),
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any] | JSONResponse:
        auth_problem = _authorize_read(request, authorization)
        if auth_problem is not None:
            return auth_problem
        try:
            events = repository.list_events(
                tenant_id=tenant_id,
                subject_id=subject_id,
                event_type=event_type,
                limit=limit,
            )
        except OaAuthEventError as exc:
            return _problem(request, exc)
        return {
            "auth_event_list_schema_version": OA_AUTH_EVENT_LIST_SCHEMA_VERSION,
            "service_id": "nex-oa",
            "tenant_ref": {"type": "oa.tenant", "id": tenant_id},
            "events": events,
            "count": len(events),
            "request_id": request_id_from_headers(request),
            "trace_id": trace_id_from_headers(request),
        }


def record_auth_event_safely(
    repository: OaAuthEventRepository | None,
    *,
    event_type: str,
    outcome: str,
    request: Request,
    authorization: str | None,
    tenant_id: object = None,
    subject_id: object = None,
    credential_id: object = None,
    details: Mapping[str, Any] | None = None,
) -> bool:
    if repository is None:
        return False
    actor_ref = _service_actor_ref(authorization)
    try:
        repository.record_event(
            {
                "event_type": event_type,
                "outcome": outcome,
                "tenant_id": tenant_id,
                "subject_id": subject_id,
                "credential_id": credential_id,
                "actor_ref": actor_ref,
                "request_id": request_id_from_headers(request),
                "trace_id": trace_id_from_headers(request),
                "details": details or {},
            }
        )
    except OaAuthEventError:
        LOGGER.error(
            "OA authentication event persistence failed",
            extra={"auth_event_type": event_type, "auth_event_outcome": outcome},
        )
        return False
    return True


def auth_event_target(payload: Mapping[str, Any]) -> dict[str, str | None]:
    tenant_ref = payload.get("tenant_ref")
    subject_ref = payload.get("subject_ref")
    tenant_id = (
        tenant_ref.get("id")
        if isinstance(tenant_ref, Mapping)
        else payload.get("tenant_id")
    )
    subject_id = (
        subject_ref.get("id")
        if isinstance(subject_ref, Mapping)
        else payload.get("subject_id")
    )
    credential_id = payload.get("credential_id")
    return {
        "tenant_id": str(tenant_id) if tenant_id else None,
        "subject_id": str(subject_id) if subject_id else None,
        "credential_id": str(credential_id) if credential_id else None,
    }


def build_auth_event(payload: Mapping[str, Any]) -> dict[str, Any]:
    event_type = _event_type(payload.get("event_type"))
    outcome = _outcome(payload.get("outcome"))
    now = _utc_now()
    return {
        "event_id": str(uuid4()),
        "event_schema_version": OA_AUTH_EVENT_SCHEMA_VERSION,
        "event_type": event_type,
        "outcome": outcome,
        "tenant_id": _optional_id(payload.get("tenant_id"), field_name="tenant_id"),
        "subject_id": _optional_id(payload.get("subject_id"), field_name="subject_id"),
        "credential_id": _optional_text(
            payload.get("credential_id"), field_name="credential_id"
        ),
        "actor_ref": _required_text(payload.get("actor_ref"), field_name="actor_ref"),
        "request_id": _optional_text(
            payload.get("request_id"), field_name="request_id"
        ),
        "trace_id": _optional_text(payload.get("trace_id"), field_name="trace_id"),
        "details": _safe_details(payload.get("details", {})),
        "occurred_at": now,
        "created_at": now,
    }


def project_auth_event(event: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "event_schema_version": OA_AUTH_EVENT_SCHEMA_VERSION,
        "event_id": str(event["event_id"]),
        "event_type": str(event["event_type"]),
        "outcome": str(event["outcome"]),
        "tenant_ref": _ref("oa.tenant", event.get("tenant_id")),
        "subject_ref": _ref("oa.user", event.get("subject_id")),
        "credential_id": event.get("credential_id"),
        "actor_ref": str(event["actor_ref"]),
        "request_id": event.get("request_id"),
        "trace_id": event.get("trace_id"),
        "details": deepcopy(dict(event.get("details") or {})),
        "occurred_at": _timestamp_to_wire(event["occurred_at"]),
    }


def normalize_event_query(
    *,
    tenant_id: object,
    subject_id: object = None,
    event_type: object = None,
    limit: object = 100,
) -> dict[str, Any]:
    try:
        normalized_tenant = normalize_registry_id(tenant_id, field_name="tenant_id")
        normalized_subject = (
            normalize_registry_id(subject_id, field_name="subject_id")
            if subject_id is not None
            else None
        )
    except SubjectRegistryError as exc:
        raise OaAuthEventError(exc.status_code, exc.error_code, exc.detail) from exc
    normalized_type = _event_type(event_type) if event_type is not None else None
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200:
        raise OaAuthEventError(
            400, "oa.auth_event_query_invalid", "limit must be between 1 and 200."
        )
    return {
        "tenant_id": normalized_tenant,
        "subject_id": normalized_subject,
        "event_type": normalized_type,
        "limit": limit,
    }


def _event_matches(event: Mapping[str, Any], query: Mapping[str, Any]) -> bool:
    return (
        event.get("tenant_id") == query["tenant_id"]
        and (
            query["subject_id"] is None
            or event.get("subject_id") == query["subject_id"]
        )
        and (
            query["event_type"] is None
            or event.get("event_type") == query["event_type"]
        )
    )


def _event_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **dict(row),
        "details": _json_loads(row.get("details")),
        "occurred_at": _timestamp_to_wire(row["occurred_at"]),
        "created_at": _timestamp_to_wire(row["created_at"]),
    }


def _safe_details(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise OaAuthEventError(
            400, "oa.auth_event_details_invalid", "details must be an object."
        )
    unexpected = sorted(set(value) - SAFE_DETAIL_FIELDS)
    if unexpected:
        raise OaAuthEventError(
            400,
            "oa.auth_event_details_invalid",
            f"Unsupported detail field: {unexpected[0]}",
        )
    safe = {}
    for key, item in value.items():
        if item is not None and not isinstance(item, (str, bool, int, float)):
            raise OaAuthEventError(
                400,
                "oa.auth_event_details_invalid",
                f"Detail field must be scalar: {key}",
            )
        safe[str(key)] = item
    return safe


def _event_type(value: object) -> str:
    normalized = _required_text(value, field_name="event_type").upper()
    if normalized not in AUTH_EVENT_TYPES:
        raise OaAuthEventError(
            400, "oa.auth_event_type_invalid", "event_type is unsupported."
        )
    return normalized


def _outcome(value: object) -> str:
    normalized = _required_text(value, field_name="outcome").upper()
    if normalized not in AUTH_EVENT_OUTCOMES:
        raise OaAuthEventError(
            400, "oa.auth_event_outcome_invalid", "outcome is unsupported."
        )
    return normalized


def _optional_id(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    try:
        return normalize_registry_id(value, field_name=field_name)
    except SubjectRegistryError as exc:
        raise OaAuthEventError(exc.status_code, exc.error_code, exc.detail) from exc


def _required_text(value: object, *, field_name: str) -> str:
    normalized = _optional_text(value, field_name=field_name)
    if normalized is None:
        raise OaAuthEventError(
            400,
            "oa.auth_event_field_invalid",
            f"{field_name} must be a non-empty string.",
        )
    return normalized


def _optional_text(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise OaAuthEventError(
            400,
            "oa.auth_event_field_invalid",
            f"{field_name} must be a non-empty string.",
        )
    return value.strip()


def _service_actor_ref(authorization: str | None) -> str:
    result = validate_authorization_header(
        authorization,
        expected_audience="nex-oa",
        required_scopes=[DEFAULT_SERVICE_SCOPE],
    )
    service_id = getattr(result.claims, "service_id", None) if result.ok else None
    return f"nex.service:{service_id or 'unknown'}"


def _authorize_read(request: Request, authorization: str | None) -> JSONResponse | None:
    result = validate_authorization_header(
        authorization,
        expected_audience="nex-oa",
        required_scopes=[DEFAULT_SERVICE_SCOPE, OA_CREDENTIAL_SECURITY_READ_SCOPE],
    )
    if result.ok:
        return None
    status = 403 if result.error_code == "TOKEN_SCOPE_MISSING" else 401
    return problem_response(
        request,
        status_code=status,
        error_code=result.error_code or "SERVICE_CLAIM_INVALID",
        title="Authorization failed" if status == 403 else "Authentication failed",
        detail=result.detail
        or "OA authentication events require a valid service claim.",
        type_uri="https://nex-platform.local/problems/oa-auth-event-authorization",
    )


def _problem(request: Request, exc: OaAuthEventError) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="OA authentication event request failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/oa-auth-event-failed",
    )


def _json_sql_expression(session: Session, bind_name: str) -> str:
    return (
        f"CAST(:{bind_name} AS JSONB)"
        if session.get_bind().dialect.name == "postgresql"
        else f":{bind_name}"
    )


def _json_loads(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str):
        return {}
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return dict(loaded) if isinstance(loaded, Mapping) else {}


def _ref(ref_type: str, value: object) -> dict[str, str] | None:
    return {"type": ref_type, "id": str(value)} if value is not None else None


def _timestamp_to_wire(value: object) -> str:
    if isinstance(value, datetime):
        parsed = value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC)
        return parsed.isoformat().replace("+00:00", "Z")
    return str(value)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _unavailable() -> OaAuthEventError:
    return OaAuthEventError(
        503,
        "oa.auth_event_repository_unavailable",
        "Authentication event persistence is unavailable.",
        True,
    )
