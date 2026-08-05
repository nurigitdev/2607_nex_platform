from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable, Protocol
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

OPERATIONAL_EVENT_SCHEMA_VERSION = "operational_event.v1"
OPERATIONAL_EVENT_SEVERITIES = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
DEFAULT_OPERATIONAL_EVENT_LIMIT = 50
MAX_OPERATIONAL_EVENT_LIMIT = 500

SENSITIVE_DETAIL_KEY_PARTS = (
    "api_key",
    "authorization",
    "credential",
    "password",
    "passwd",
    "raw_prompt",
    "raw_user_message",
    "secret",
    "source_text",
    "token",
)


@dataclass(frozen=True)
class OperationalEventError(Exception):
    error_code: str
    detail: str
    status_code: int = 422

    def __str__(self) -> str:
        return self.detail


class OperationalEventStore(Protocol):
    def append(self, event: dict[str, Any]) -> dict[str, Any]:
        ...

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        ...

    def list_events(
        self,
        *,
        service_id: str | None = None,
        severity: str | None = None,
        event_type: str | None = None,
        trace_id: str | None = None,
        limit: int = DEFAULT_OPERATIONAL_EVENT_LIMIT,
    ) -> list[dict[str, Any]]:
        ...


def build_operational_event(
    *,
    service_id: str,
    event_type: str,
    severity: str,
    message: str,
    trace_id: str | None = None,
    request_id: str | None = None,
    subject_ref: dict[str, str] | None = None,
    details: dict[str, Any] | None = None,
    created_at: str | None = None,
    event_id: str | None = None,
) -> dict[str, Any]:
    observed_at = created_at or _utc_now()
    normalized_severity = severity.upper()
    event = {
        "event_schema_version": OPERATIONAL_EVENT_SCHEMA_VERSION,
        "event_id": event_id
        or _event_id(
            service_id=service_id,
            event_type=event_type,
            severity=normalized_severity,
            trace_id=trace_id,
            request_id=request_id,
            subject_ref=subject_ref,
            created_at=observed_at,
        ),
        "service_id": service_id,
        "event_type": event_type,
        "severity": normalized_severity,
        "message": message,
        "trace_id": trace_id,
        "request_id": request_id,
        "subject_ref": subject_ref,
        "details": redact_operational_details(details or {}),
        "created_at": observed_at,
    }
    return validate_operational_event(event)


def validate_operational_event(event: dict[str, Any]) -> dict[str, Any]:
    for field_name in (
        "event_schema_version",
        "event_id",
        "service_id",
        "event_type",
        "severity",
        "message",
        "details",
        "created_at",
    ):
        if field_name not in event:
            raise OperationalEventError(
                error_code="operational_event.invalid",
                detail=f"missing event field: {field_name}",
            )
    if event["event_schema_version"] != OPERATIONAL_EVENT_SCHEMA_VERSION:
        raise OperationalEventError(
            error_code="operational_event.schema_version_invalid",
            detail="event_schema_version must be operational_event.v1",
        )
    for field_name in ("event_id", "service_id", "event_type", "message", "created_at"):
        _required_string(event[field_name], field_name)
    if len(event["message"]) > 512:
        raise OperationalEventError(
            error_code="operational_event.message_too_long",
            detail="message must be 512 characters or fewer",
        )
    if event["severity"] not in OPERATIONAL_EVENT_SEVERITIES:
        raise OperationalEventError(
            error_code="operational_event.severity_invalid",
            detail=f"unsupported operational event severity: {event['severity']}",
        )
    if event.get("trace_id") is not None:
        _required_string(event["trace_id"], "trace_id")
    if event.get("request_id") is not None:
        _required_string(event["request_id"], "request_id")
    subject_ref = event.get("subject_ref")
    if subject_ref is not None:
        if not isinstance(subject_ref, dict):
            raise OperationalEventError(
                error_code="operational_event.subject_ref_invalid",
                detail="subject_ref must be an object",
            )
        _required_string(subject_ref.get("type"), "subject_ref.type")
        _required_string(subject_ref.get("id"), "subject_ref.id")
    if not isinstance(event["details"], dict):
        raise OperationalEventError(
            error_code="operational_event.details_invalid",
            detail="details must be an object",
        )
    return event


def redact_operational_details(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if _is_sensitive_detail_key(str(key)):
                redacted[str(key)] = "<redacted>"
            else:
                redacted[str(key)] = redact_operational_details(item)
        return redacted
    if isinstance(value, list):
        return [redact_operational_details(item) for item in value]
    return value


def summarize_operational_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {severity: 0 for severity in OPERATIONAL_EVENT_SEVERITIES}
    service_counts: dict[str, int] = {}
    for event in events:
        severity = str(event.get("severity", ""))
        if severity in counts:
            counts[severity] += 1
        service_id = str(event.get("service_id", "unknown"))
        service_counts[service_id] = service_counts.get(service_id, 0) + 1
    return {
        "total": len(events),
        "by_severity": counts,
        "by_service": service_counts,
    }


@dataclass
class InMemoryOperationalEventStore:
    events: dict[str, dict[str, Any]] = field(default_factory=dict)

    def append(self, event: dict[str, Any]) -> dict[str, Any]:
        validate_operational_event(event)
        event_id = str(event["event_id"])
        if event_id not in self.events:
            self.events[event_id] = deepcopy(event)
        return deepcopy(self.events[event_id])

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        event = self.events.get(event_id)
        return deepcopy(event) if event is not None else None

    def list_events(
        self,
        *,
        service_id: str | None = None,
        severity: str | None = None,
        event_type: str | None = None,
        trace_id: str | None = None,
        limit: int = DEFAULT_OPERATIONAL_EVENT_LIMIT,
    ) -> list[dict[str, Any]]:
        normalized_severity = severity.upper() if severity is not None else None
        normalized_limit = normalize_operational_event_limit(limit)
        events = [
            deepcopy(event)
            for event in self.events.values()
            if (service_id is None or event["service_id"] == service_id)
            and (normalized_severity is None or event["severity"] == normalized_severity)
            and (event_type is None or event["event_type"] == event_type)
            and (trace_id is None or event.get("trace_id") == trace_id)
        ]
        events.sort(key=lambda event: (event["created_at"], event["event_id"]), reverse=True)
        return events[:normalized_limit]

    def summary(self) -> dict[str, Any]:
        return summarize_operational_events(self.list_events(limit=MAX_OPERATIONAL_EVENT_LIMIT))


class SqlAlchemyOperationalEventStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def append(self, event: dict[str, Any]) -> dict[str, Any]:
        event_to_store = deepcopy(validate_operational_event(event))
        try:
            return self._run_in_transaction(
                lambda session: self._append_event(session, event_to_store)
            )
        except IntegrityError as exc:
            existing = self.get_event(str(event_to_store["event_id"]))
            if existing is not None:
                return existing
            raise _event_store_unavailable() from exc
        except SQLAlchemyError as exc:
            raise _event_store_unavailable() from exc

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                return self._select_event(session, event_id)
        except SQLAlchemyError as exc:
            raise _event_store_unavailable() from exc

    def list_events(
        self,
        *,
        service_id: str | None = None,
        severity: str | None = None,
        event_type: str | None = None,
        trace_id: str | None = None,
        limit: int = DEFAULT_OPERATIONAL_EVENT_LIMIT,
    ) -> list[dict[str, Any]]:
        normalized_limit = normalize_operational_event_limit(limit)
        normalized_severity = severity.upper() if severity is not None else None
        where_clauses: list[str] = []
        params: dict[str, Any] = {"limit": normalized_limit}
        if service_id is not None:
            where_clauses.append("service_id = :service_id")
            params["service_id"] = service_id
        if normalized_severity is not None:
            where_clauses.append("severity = :severity")
            params["severity"] = normalized_severity
        if event_type is not None:
            where_clauses.append("event_type = :event_type")
            params["event_type"] = event_type
        if trace_id is not None:
            where_clauses.append("trace_id = :trace_id")
            params["trace_id"] = trace_id
        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        try:
            with self._session_factory() as session:
                rows = session.execute(
                    text(
                        f"""
                        SELECT {_EVENT_SELECT_COLUMNS}
                        FROM service_operational_events
                        {where_sql}
                        ORDER BY created_at DESC, event_id DESC
                        LIMIT :limit
                        """
                    ),
                    params,
                ).mappings()
                return [_event_from_row(row) for row in rows]
        except SQLAlchemyError as exc:
            raise _event_store_unavailable() from exc

    def summary(self) -> dict[str, Any]:
        return summarize_operational_events(
            self.list_events(limit=MAX_OPERATIONAL_EVENT_LIMIT)
        )

    def _run_in_transaction(self, operation: Callable[[Session], Any]) -> Any:
        session = self._session_factory()
        try:
            try:
                result = operation(session)
                session.commit()
                return result
            except Exception:
                session.rollback()
                raise
        finally:
            session.close()

    def _append_event(self, session: Session, event: dict[str, Any]) -> dict[str, Any]:
        existing = self._select_event(session, str(event["event_id"]))
        if existing is not None:
            return existing
        self._insert_event(session, event)
        stored = self._select_event(session, str(event["event_id"]))
        assert stored is not None
        return stored

    def _select_event(
        self,
        session: Session,
        event_id: str,
    ) -> dict[str, Any] | None:
        row = session.execute(
            text(
                f"""
                SELECT {_EVENT_SELECT_COLUMNS}
                FROM service_operational_events
                WHERE event_id = :event_id
                """
            ),
            {"event_id": event_id},
        ).mappings().first()
        return _event_from_row(row) if row is not None else None

    def _insert_event(self, session: Session, event: dict[str, Any]) -> None:
        details_expression = _details_sql_expression(session)
        session.execute(
            text(
                f"""
                INSERT INTO service_operational_events (
                    event_id,
                    event_schema_version,
                    service_id,
                    event_type,
                    severity,
                    trace_id,
                    request_id,
                    subject_type,
                    subject_id,
                    message,
                    details,
                    created_at
                )
                VALUES (
                    :event_id,
                    :event_schema_version,
                    :service_id,
                    :event_type,
                    :severity,
                    :trace_id,
                    :request_id,
                    :subject_type,
                    :subject_id,
                    :message,
                    {details_expression},
                    :created_at
                )
                """
            ),
            _event_insert_params(event),
        )


def normalize_operational_event_limit(limit: int) -> int:
    if limit < 1:
        return 1
    if limit > MAX_OPERATIONAL_EVENT_LIMIT:
        return MAX_OPERATIONAL_EVENT_LIMIT
    return limit


def _event_id(
    *,
    service_id: str,
    event_type: str,
    severity: str,
    trace_id: str | None,
    request_id: str | None,
    subject_ref: dict[str, str] | None,
    created_at: str,
) -> str:
    subject_type = subject_ref["type"] if subject_ref is not None else "unscoped"
    subject_id = subject_ref["id"] if subject_ref is not None else "unscoped"
    seed = (
        f"operational-event:{service_id}:{event_type}:{severity}:"
        f"{trace_id or 'no-trace'}:{request_id or 'no-request'}:"
        f"{subject_type}:{subject_id}:{created_at}"
    )
    return str(uuid5(NAMESPACE_URL, seed))


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise OperationalEventError(
            error_code="operational_event.field_invalid",
            detail=f"{field_name} must be a non-empty string",
        )
    return value


def _is_sensitive_detail_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in SENSITIVE_DETAIL_KEY_PARTS)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


_EVENT_SELECT_COLUMNS = """
    event_id,
    event_schema_version,
    service_id,
    event_type,
    severity,
    trace_id,
    request_id,
    subject_type,
    subject_id,
    message,
    details,
    created_at
"""


def _event_insert_params(event: dict[str, Any]) -> dict[str, Any]:
    subject_ref = event.get("subject_ref")
    subject_type = subject_ref["type"] if subject_ref is not None else None
    subject_id = subject_ref["id"] if subject_ref is not None else None
    return {
        "event_id": event["event_id"],
        "event_schema_version": event["event_schema_version"],
        "service_id": event["service_id"],
        "event_type": event["event_type"],
        "severity": event["severity"],
        "trace_id": event.get("trace_id"),
        "request_id": event.get("request_id"),
        "subject_type": subject_type,
        "subject_id": subject_id,
        "message": event["message"],
        "details": _json_dumps(event["details"]),
        "created_at": event["created_at"],
    }


def _event_from_row(row: Any) -> dict[str, Any]:
    subject_ref = None
    if row["subject_type"] is not None or row["subject_id"] is not None:
        subject_ref = {
            "type": row["subject_type"],
            "id": row["subject_id"],
        }
    return validate_operational_event(
        {
            "event_schema_version": row["event_schema_version"],
            "event_id": row["event_id"],
            "service_id": row["service_id"],
            "event_type": row["event_type"],
            "severity": row["severity"],
            "message": row["message"],
            "trace_id": row["trace_id"],
            "request_id": row["request_id"],
            "subject_ref": subject_ref,
            "details": _json_loads(row["details"], default={}),
            "created_at": _timestamp_to_wire(row["created_at"]),
        }
    )


def _details_sql_expression(session: Session) -> str:
    if _dialect_name(session) == "postgresql":
        return "CAST(:details AS JSONB)"
    return ":details"


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_loads(value: Any, *, default: Any) -> Any:
    if value is None:
        return deepcopy(default)
    if isinstance(value, (dict, list)):
        return deepcopy(value)
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        return json.loads(value)
    return deepcopy(default)


def _timestamp_to_wire(value: Any) -> str:
    if isinstance(value, datetime):
        observed = value
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=UTC)
        return observed.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return str(value)


def _dialect_name(session: Session) -> str:
    return session.get_bind().dialect.name


def _event_store_unavailable() -> OperationalEventError:
    return OperationalEventError(
        error_code="operational_event.store_unavailable",
        detail="operational event store is unavailable",
        status_code=503,
    )
