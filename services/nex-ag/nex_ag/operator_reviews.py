from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker


OPERATOR_REVIEW_NOTE_SCHEMA_VERSION = "ag_operator_review_note.v1"
OPERATOR_REVIEW_NOTE_LIST_SCHEMA_VERSION = "ag_operator_review_note_list.v1"
AG_OPERATOR_NOTE_TABLE = "ag_op_notes"
MAX_OPERATOR_NOTE_PREVIEW_LENGTH = 240
DEFAULT_NOTE_LIMIT = 50
MAX_NOTE_LIMIT = 500

ALLOWED_TARGET_SERVICES = (
    "nex-ae-api",
    "nex-cx",
    "nex-mo",
    "nex-oa",
    "nex-ag",
)
ALLOWED_OPERATOR_TYPES = ("service", "user")
ALLOWED_NOTE_STATUSES = ("ACTIVE", "SUPERSEDED", "RESOLVED", "DELETED")
ALLOWED_NOTE_TYPES = (
    "OBSERVATION",
    "ACTION",
    "FOLLOW_UP",
    "ESCALATION",
    "RESOLUTION",
)
ALLOWED_NOTE_SEVERITIES = ("INFO", "LOW", "MEDIUM", "HIGH", "URGENT")
SENSITIVE_KEY_PARTS = (
    "api_key",
    "authorization",
    "credential",
    "password",
    "passwd",
    "raw_generation_output",
    "raw_note",
    "raw_operator_note",
    "raw_output",
    "raw_prompt",
    "raw_source",
    "raw_text",
    "raw_user_message",
    "secret",
    "source_text",
    "token",
)


@dataclass
class OperatorReviewNoteStore:
    records: dict[str, dict[str, Any]] = field(default_factory=dict)

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        self.records[record["operator_note_id"]] = record
        return record

    def get(self, operator_note_id: str) -> dict[str, Any] | None:
        return self.records.get(operator_note_id)

    def list_notes(
        self,
        *,
        target_service: str | None = None,
        target_kind: str | None = None,
        target_id: str | None = None,
        trace_id: str | None = None,
        note_status: str | None = None,
        operator_type: str | None = None,
        operator_id: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        selected = [
            record
            for record in self.records.values()
            if _record_matches_filter(
                record,
                target_service=target_service,
                target_kind=target_kind,
                target_id=target_id,
                trace_id=trace_id,
                note_status=note_status,
                operator_type=operator_type,
                operator_id=operator_id,
            )
        ]
        selected.sort(
            key=lambda record: (
                str(record.get("updated_at") or ""),
                str(record.get("operator_note_id") or ""),
            ),
            reverse=True,
        )
        return selected[:normalize_limit(limit)]

    def delete(self, operator_note_id: str) -> int:
        return 1 if self.records.pop(operator_note_id, None) is not None else 0


class SqlAlchemyOperatorReviewNoteStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        try:
            with self._session_factory() as session:
                session.execute(
                    text(_operator_note_upsert_sql(_dialect_name(session))),
                    _operator_note_record_params(record),
                )
                session.commit()
            return record
        except SQLAlchemyError as exc:
            raise _store_unavailable_error() from exc

    def get(self, operator_note_id: str) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(
                        text(
                            _operator_note_select_sql(
                                "operator_note_id = :operator_note_id"
                            )
                        ),
                        {"operator_note_id": operator_note_id},
                    )
                    .mappings()
                    .first()
                )
            return _operator_note_record_from_row(row) if row is not None else None
        except SQLAlchemyError as exc:
            raise _store_unavailable_error() from exc

    def list_notes(
        self,
        *,
        target_service: str | None = None,
        target_kind: str | None = None,
        target_id: str | None = None,
        trace_id: str | None = None,
        note_status: str | None = None,
        operator_type: str | None = None,
        operator_id: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        where_clause, params = _operator_note_filter_clause(
            target_service=target_service,
            target_kind=target_kind,
            target_id=target_id,
            trace_id=trace_id,
            note_status=note_status,
            operator_type=operator_type,
            operator_id=operator_id,
        )
        params["limit"] = normalize_limit(limit)
        try:
            with self._session_factory() as session:
                rows = (
                    session.execute(
                        text(
                            _operator_note_select_sql(
                                where_clause
                                + " ORDER BY updated_at DESC, operator_note_id ASC"
                                + " LIMIT :limit"
                            )
                        ),
                        params,
                    )
                    .mappings()
                    .all()
                )
            return [_operator_note_record_from_row(row) for row in rows]
        except SQLAlchemyError as exc:
            raise _store_unavailable_error() from exc

    def delete(self, operator_note_id: str) -> int:
        try:
            with self._session_factory() as session:
                result = session.execute(
                    text("DELETE FROM ag_op_notes WHERE operator_note_id = :operator_note_id"),
                    {"operator_note_id": operator_note_id},
                )
                session.commit()
                return int(result.rowcount or 0)
        except SQLAlchemyError as exc:
            raise _store_unavailable_error() from exc


@dataclass(frozen=True)
class OperatorReviewNoteError(Exception):
    status_code: int
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


DEFAULT_OPERATOR_REVIEW_NOTE_STORE = OperatorReviewNoteStore()


def default_operator_review_note_store(app: FastAPI) -> Any:
    persistence = getattr(app.state, "nex_persistence", None)
    session_factory = getattr(persistence, "api_session_factory", None)
    if session_factory is not None:
        return SqlAlchemyOperatorReviewNoteStore(session_factory)
    return DEFAULT_OPERATOR_REVIEW_NOTE_STORE


def build_operator_review_note_record(
    payload: dict[str, Any],
    *,
    request_id: str,
    trace_id: str | None,
    created_at: str | None = None,
) -> dict[str, Any]:
    assert_operator_review_note_payload_redaction_safe(payload)
    target = target_ref(payload.get("target_ref"))
    operator = operator_ref(payload.get("operator_ref"))
    note = required_text(payload, "operator_note")
    note_hash = sha256_text(note)
    note_status = optional_choice(
        payload.get("note_status"),
        key="note_status",
        choices=ALLOWED_NOTE_STATUSES,
        default="ACTIVE",
    )
    note_type = optional_choice(
        payload.get("note_type"),
        key="note_type",
        choices=ALLOWED_NOTE_TYPES,
        default="OBSERVATION",
    )
    severity = optional_choice(
        payload.get("severity"),
        key="severity",
        choices=ALLOWED_NOTE_SEVERITIES,
        default="INFO",
    )
    reason_codes = reason_code_list(payload.get("reason_codes"))
    now = created_at or _utc_now()
    operator_note_id = optional_text(payload.get("operator_note_id")) or str(
        uuid5(
            NAMESPACE_URL,
            (
                "ag-operator-review-note:"
                f"{target['target_service']}:{target['target_kind']}:{target['target_id']}:"
                f"{operator['operator_type']}:{operator['operator_id']}:"
                f"{note_type}:{severity}:{note_hash}:{request_id}"
            ),
        )
    )
    return {
        "operator_note_schema_version": OPERATOR_REVIEW_NOTE_SCHEMA_VERSION,
        "operator_note_id": operator_note_id,
        "target_service": target["target_service"],
        "target_kind": target["target_kind"],
        "target_id": target["target_id"],
        "trace_id": optional_text(trace_id),
        "request_id": required_text({"request_id": request_id}, "request_id"),
        "operator_ref": operator,
        "note_status": note_status,
        "note_type": note_type,
        "severity": severity,
        "operator_note_hash": note_hash,
        "operator_note_preview": operator_note_preview(note),
        "reason_codes": reason_codes,
        "metadata": operator_note_metadata(payload.get("metadata")),
        "created_at": now,
        "updated_at": now,
    }


def build_operator_review_note_list_response(
    records: list[dict[str, Any]],
    *,
    request_id: str,
    trace_id: str | None,
) -> dict[str, Any]:
    items = sorted(
        records,
        key=lambda record: (
            str(record.get("updated_at") or ""),
            str(record.get("operator_note_id") or ""),
        ),
        reverse=True,
    )
    by_status: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for record in items:
        status = str(record.get("note_status") or "UNKNOWN")
        severity = str(record.get("severity") or "UNKNOWN")
        by_status[status] = by_status.get(status, 0) + 1
        by_severity[severity] = by_severity.get(severity, 0) + 1
    return {
        "operator_note_list_schema_version": OPERATOR_REVIEW_NOTE_LIST_SCHEMA_VERSION,
        "trace_id": optional_text(trace_id),
        "request_id": required_text({"request_id": request_id}, "request_id"),
        "items": items,
        "summary": {
            "count": len(items),
            "by_status": by_status,
            "by_severity": by_severity,
            "latest_updated_at": items[0]["updated_at"] if items else None,
        },
    }


def target_ref(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise OperatorReviewNoteError(
            status_code=422,
            error_code="ag.operator_review_note_target_ref_required",
            detail="target_ref is required.",
        )
    return {
        "target_service": required_choice(
            value,
            "target_service",
            choices=ALLOWED_TARGET_SERVICES,
        ),
        "target_kind": required_text(value, "target_kind"),
        "target_id": required_text(value, "target_id"),
    }


def operator_ref(value: Any) -> dict[str, str | None]:
    if not isinstance(value, dict):
        raise OperatorReviewNoteError(
            status_code=422,
            error_code="ag.operator_review_note_operator_ref_required",
            detail="operator_ref is required.",
        )
    return {
        "operator_type": required_choice(
            value,
            "operator_type",
            choices=ALLOWED_OPERATOR_TYPES,
        ),
        "operator_id": required_text(value, "operator_id"),
        "tenant_id": optional_text(value.get("tenant_id")),
    }


def operator_note_metadata(value: Any) -> dict[str, Any]:
    if value is None:
        metadata: dict[str, Any] = {}
    elif isinstance(value, dict):
        metadata = dict(value)
    else:
        raise OperatorReviewNoteError(
            status_code=422,
            error_code="ag.operator_review_note_metadata_invalid",
            detail="metadata must be an object when supplied.",
        )
    metadata.update(
        {
            "raw_operator_note_stored": False,
            "operator_note_storage": "hash_and_short_preview_only",
        }
    )
    return json.loads(json.dumps(metadata))


def reason_code_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise OperatorReviewNoteError(
            status_code=422,
            error_code="ag.operator_review_note_reasons_invalid",
            detail="reason_codes must be a list when supplied.",
        )
    reason_codes: list[str] = []
    for reason in value:
        if not isinstance(reason, str) or not reason.strip():
            raise OperatorReviewNoteError(
                status_code=422,
                error_code="ag.operator_review_note_reason_invalid",
                detail="reason code must be a non-empty string.",
            )
        normalized = reason.strip()
        if normalized not in reason_codes:
            reason_codes.append(normalized)
    return reason_codes


def operator_note_preview(note: str | None) -> str | None:
    if note is None:
        return None
    return note.strip()[:MAX_OPERATOR_NOTE_PREVIEW_LENGTH]


def normalize_limit(value: int | None) -> int:
    if value is None:
        return DEFAULT_NOTE_LIMIT
    return min(max(int(value), 1), MAX_NOTE_LIMIT)


def required_choice(
    payload: dict[str, Any],
    key: str,
    *,
    choices: tuple[str, ...],
) -> str:
    value = required_text(payload, key)
    if value not in choices:
        raise OperatorReviewNoteError(
            status_code=422,
            error_code=f"ag.operator_review_note_{key}_unsupported",
            detail=f"unsupported {key}: {value}",
        )
    return value


def optional_choice(
    value: Any,
    *,
    key: str,
    choices: tuple[str, ...],
    default: str,
) -> str:
    normalized = optional_text(value)
    if normalized is None:
        return default
    if normalized not in choices:
        raise OperatorReviewNoteError(
            status_code=422,
            error_code=f"ag.operator_review_note_{key}_unsupported",
            detail=f"unsupported {key}: {normalized}",
        )
    return normalized


def required_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise OperatorReviewNoteError(
            status_code=422,
            error_code=f"ag.operator_review_note_{key}_required",
            detail=f"{key} is required.",
        )
    return value.strip()


def optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def find_sensitive_operator_review_note_keys(payload: Any) -> list[str]:
    matches: list[str] = []
    _collect_sensitive_keys(payload, path="", matches=matches)
    return matches


def assert_operator_review_note_payload_redaction_safe(payload: dict[str, Any]) -> None:
    sensitive_keys = find_sensitive_operator_review_note_keys(payload)
    if sensitive_keys:
        raise OperatorReviewNoteError(
            status_code=422,
            error_code="ag.operator_review_note_sensitive_payload",
            detail=(
                "Operator review note payload contains sensitive keys: "
                f"{', '.join(sensitive_keys)}"
            ),
        )


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _record_matches_filter(
    record: dict[str, Any],
    *,
    target_service: str | None,
    target_kind: str | None,
    target_id: str | None,
    trace_id: str | None,
    note_status: str | None,
    operator_type: str | None,
    operator_id: str | None,
) -> bool:
    operator = record.get("operator_ref")
    operator_ref_value = operator if isinstance(operator, dict) else {}
    return all(
        (
            target_service is None or record.get("target_service") == target_service,
            target_kind is None or record.get("target_kind") == target_kind,
            target_id is None or record.get("target_id") == target_id,
            trace_id is None or record.get("trace_id") == trace_id,
            note_status is None or record.get("note_status") == note_status,
            operator_type is None
            or operator_ref_value.get("operator_type") == operator_type,
            operator_id is None or operator_ref_value.get("operator_id") == operator_id,
        )
    )


def _operator_note_filter_clause(
    *,
    target_service: str | None,
    target_kind: str | None,
    target_id: str | None,
    trace_id: str | None,
    note_status: str | None,
    operator_type: str | None,
    operator_id: str | None,
) -> tuple[str, dict[str, Any]]:
    clauses = ["1 = 1"]
    params: dict[str, Any] = {}
    for name, value in (
        ("target_service", target_service),
        ("target_kind", target_kind),
        ("target_id", target_id),
        ("trace_id", trace_id),
        ("note_status", note_status),
        ("operator_type", operator_type),
        ("operator_id", operator_id),
    ):
        if value is not None:
            clauses.append(f"{name} = :{name}")
            params[name] = value
    return " AND ".join(clauses), params


def _operator_note_upsert_sql(dialect_name: str) -> str:
    operator_ref_expr = _json_param_expr("operator_ref", dialect_name)
    reason_codes_expr = _json_param_expr("reason_codes", dialect_name)
    metadata_expr = _json_param_expr("metadata", dialect_name)
    return f"""
        INSERT INTO ag_op_notes (
            operator_note_id,
            operator_note_schema_version,
            target_service,
            target_kind,
            target_id,
            trace_id,
            request_id,
            operator_type,
            operator_id,
            tenant_id,
            operator_ref,
            note_status,
            note_type,
            severity,
            operator_note_hash,
            operator_note_preview,
            reason_codes,
            metadata,
            created_at,
            updated_at
        )
        VALUES (
            :operator_note_id,
            :operator_note_schema_version,
            :target_service,
            :target_kind,
            :target_id,
            :trace_id,
            :request_id,
            :operator_type,
            :operator_id,
            :tenant_id,
            {operator_ref_expr},
            :note_status,
            :note_type,
            :severity,
            :operator_note_hash,
            :operator_note_preview,
            {reason_codes_expr},
            {metadata_expr},
            :created_at,
            :updated_at
        )
        ON CONFLICT (operator_note_id) DO UPDATE SET
            operator_note_schema_version = excluded.operator_note_schema_version,
            target_service = excluded.target_service,
            target_kind = excluded.target_kind,
            target_id = excluded.target_id,
            trace_id = excluded.trace_id,
            request_id = excluded.request_id,
            operator_type = excluded.operator_type,
            operator_id = excluded.operator_id,
            tenant_id = excluded.tenant_id,
            operator_ref = excluded.operator_ref,
            note_status = excluded.note_status,
            note_type = excluded.note_type,
            severity = excluded.severity,
            operator_note_hash = excluded.operator_note_hash,
            operator_note_preview = excluded.operator_note_preview,
            reason_codes = excluded.reason_codes,
            metadata = excluded.metadata,
            updated_at = excluded.updated_at
    """


def _operator_note_select_sql(where_clause: str) -> str:
    return f"""
        SELECT
            operator_note_schema_version,
            operator_note_id,
            target_service,
            target_kind,
            target_id,
            trace_id,
            request_id,
            operator_ref,
            note_status,
            note_type,
            severity,
            operator_note_hash,
            operator_note_preview,
            reason_codes,
            metadata,
            created_at,
            updated_at
        FROM ag_op_notes
        WHERE {where_clause}
    """


def _operator_note_record_params(record: dict[str, Any]) -> dict[str, Any]:
    operator = record["operator_ref"]
    return {
        **record,
        "operator_type": operator["operator_type"],
        "operator_id": operator["operator_id"],
        "tenant_id": operator.get("tenant_id"),
        "operator_ref": json.dumps(record["operator_ref"]),
        "reason_codes": json.dumps(record["reason_codes"]),
        "metadata": json.dumps(record["metadata"]),
    }


def _operator_note_record_from_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    return {
        "operator_note_schema_version": data["operator_note_schema_version"],
        "operator_note_id": data["operator_note_id"],
        "target_service": data["target_service"],
        "target_kind": data["target_kind"],
        "target_id": data["target_id"],
        "trace_id": data["trace_id"],
        "request_id": data["request_id"],
        "operator_ref": _json_value(data["operator_ref"], {}),
        "note_status": data["note_status"],
        "note_type": data["note_type"],
        "severity": data["severity"],
        "operator_note_hash": data["operator_note_hash"],
        "operator_note_preview": data["operator_note_preview"],
        "reason_codes": _json_value(data["reason_codes"], []),
        "metadata": _json_value(data["metadata"], {}),
        "created_at": _datetime_value(data["created_at"]),
        "updated_at": _datetime_value(data["updated_at"]),
    }


def _json_param_expr(name: str, dialect_name: str) -> str:
    if dialect_name == "postgresql":
        return f"CAST(:{name} AS jsonb)"
    return f":{name}"


def _dialect_name(session: Session) -> str:
    return session.get_bind().dialect.name


def _json_value(value: Any, default: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    if value is None:
        return default
    return value


def _datetime_value(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if hasattr(value, "isoformat"):
        return value.isoformat().replace("+00:00", "Z")
    return str(value)


def _store_unavailable_error() -> OperatorReviewNoteError:
    return OperatorReviewNoteError(
        status_code=503,
        error_code="ag.operator_review_note_store_unavailable",
        detail="Operator review note store is unavailable.",
    )


def _collect_sensitive_keys(value: Any, *, path: str, matches: list[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}" if path else key_text
            if _is_sensitive_key(key_text):
                matches.append(child_path)
            _collect_sensitive_keys(child, path=child_path, matches=matches)
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _collect_sensitive_keys(child, path=f"{path}[{index}]", matches=matches)


def _is_sensitive_key(key: str) -> bool:
    normalized = key.strip().lower()
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
