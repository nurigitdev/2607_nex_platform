from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from fastapi import Body, FastAPI, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    InMemoryOperationalEventStore,
    OperationalEventEmitter,
    OperationalEventEmitResult,
    OperationalEventStore,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
    validate_authorization_header,
)


DISPOSITION_SCHEMA_VERSION = "ag_generation_quality_operator_disposition.v1"
DISPOSITION_LIST_SCHEMA_VERSION = "ag_generation_quality_operator_disposition_list.v1"
DISPOSITION_RECORDED_EVENT_TYPE = "ag.generation_quality.disposition_recorded"
MAX_OPERATOR_NOTE_PREVIEW_LENGTH = 240

ALLOWED_OPERATOR_ACTIONS = (
    "acknowledged",
    "false_positive",
    "needs_cx_repair",
    "needs_ae_followup",
    "escalated",
    "resolved",
)
ACTION_STATUS = {
    "acknowledged": "ACKNOWLEDGED",
    "false_positive": "DISMISSED",
    "needs_cx_repair": "IN_REPAIR",
    "needs_ae_followup": "IN_REPAIR",
    "escalated": "ESCALATED",
    "resolved": "RESOLVED",
}
ALLOWED_REASON_CODES = (
    "metadata_gap",
    "citation_quality",
    "retrieval_quality",
    "generation_quality",
    "user_feedback",
    "duplicate",
    "not_reproducible",
    "other",
)
ALLOWED_QUALITY_ISSUE_TYPES = (
    "retrieval_quality",
    "generation_quality",
    "citation_quality",
    "artifact_quality",
    "user_feedback",
    "operator_review",
)
ALLOWED_QUALITY_ISSUE_SOURCE_SERVICES = (
    "nex-ae-api",
    "nex-cx",
    "nex-ag",
)
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
class GenerationQualityDispositionStore:
    records: dict[str, dict[str, Any]] = field(default_factory=dict)
    disposition_ids_by_generation: dict[str, list[str]] = field(default_factory=dict)

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        disposition_id = record["disposition_id"]
        self.records[disposition_id] = record
        ids = self.disposition_ids_by_generation.setdefault(
            record["cx_generation_id"],
            [],
        )
        if disposition_id not in ids:
            ids.append(disposition_id)
        return record

    def get(self, disposition_id: str) -> dict[str, Any] | None:
        return self.records.get(disposition_id)

    def list_for_generation(self, cx_generation_id: str) -> list[dict[str, Any]]:
        return [
            self.records[disposition_id]
            for disposition_id in self.disposition_ids_by_generation.get(
                cx_generation_id,
                [],
            )
            if disposition_id in self.records
        ]

    def delete(self, disposition_id: str) -> int:
        record = self.records.pop(disposition_id, None)
        if record is None:
            return 0
        ids = self.disposition_ids_by_generation.get(record["cx_generation_id"], [])
        self.disposition_ids_by_generation[record["cx_generation_id"]] = [
            existing_id for existing_id in ids if existing_id != disposition_id
        ]
        return 1


class SqlAlchemyGenerationQualityDispositionStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        try:
            with self._session_factory() as session:
                session.execute(
                    text(_disposition_upsert_sql(_dialect_name(session))),
                    _disposition_record_params(record),
                )
                session.commit()
            return record
        except SQLAlchemyError as exc:
            raise _store_unavailable_error() from exc

    def get(self, disposition_id: str) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(
                        text(
                            _disposition_select_sql(
                                "disposition_id = :disposition_id"
                            )
                        ),
                        {"disposition_id": disposition_id},
                    )
                    .mappings()
                    .first()
                )
            return _disposition_record_from_row(row) if row is not None else None
        except SQLAlchemyError as exc:
            raise _store_unavailable_error() from exc

    def list_for_generation(self, cx_generation_id: str) -> list[dict[str, Any]]:
        try:
            with self._session_factory() as session:
                rows = (
                    session.execute(
                        text(
                            _disposition_select_sql(
                                "cx_generation_id = :cx_generation_id "
                                "ORDER BY updated_at DESC, disposition_id ASC"
                            )
                        ),
                        {"cx_generation_id": cx_generation_id},
                    )
                    .mappings()
                    .all()
                )
            return [_disposition_record_from_row(row) for row in rows]
        except SQLAlchemyError as exc:
            raise _store_unavailable_error() from exc

    def delete(self, disposition_id: str) -> int:
        try:
            with self._session_factory() as session:
                result = session.execute(
                    text(
                        "DELETE FROM ag_generation_quality_operator_dispositions "
                        "WHERE disposition_id = :disposition_id"
                    ),
                    {"disposition_id": disposition_id},
                )
                session.commit()
                return int(result.rowcount or 0)
        except SQLAlchemyError as exc:
            raise _store_unavailable_error() from exc


@dataclass(frozen=True)
class GenerationQualityDispositionError(Exception):
    status_code: int
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


DEFAULT_DISPOSITION_STORE = GenerationQualityDispositionStore()
DEFAULT_AUDIT_EVENT_STORE = InMemoryOperationalEventStore()


def default_generation_quality_disposition_store(app: FastAPI) -> Any:
    persistence = getattr(app.state, "nex_persistence", None)
    session_factory = getattr(persistence, "api_session_factory", None)
    if session_factory is not None:
        return SqlAlchemyGenerationQualityDispositionStore(session_factory)
    return DEFAULT_DISPOSITION_STORE


def register_generation_quality_disposition_routes(
    app: FastAPI,
    *,
    store: Any | None = None,
    audit_event_store: OperationalEventStore | None = None,
) -> None:
    selected_store = store or default_generation_quality_disposition_store(app)
    audit_emitter = OperationalEventEmitter(
        service_id="nex-ag",
        store=audit_event_store or DEFAULT_AUDIT_EVENT_STORE,
    )

    @app.post(
        "/admin/v1/generation-audit/generations/{cx_generation_id}/quality-dispositions",
        response_model=None,
    )
    def create_generation_quality_disposition(
        cx_generation_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
        payload: dict[str, Any] = Body(...),
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        request_id = request_id_from_headers(request)
        trace_id = trace_id_from_headers(request)
        try:
            record = build_generation_quality_disposition_record(
                payload,
                cx_generation_id=cx_generation_id,
                request_id=request_id,
                trace_id=trace_id,
            )
        except GenerationQualityDispositionError as exc:
            return _disposition_problem_response(request, exc)

        selected_store.save(record)
        emit_generation_quality_disposition_event(audit_emitter, record)
        return JSONResponse(status_code=202, content=record)

    @app.get(
        "/admin/v1/generation-audit/generations/{cx_generation_id}/quality-dispositions",
        response_model=None,
    )
    def list_generation_quality_dispositions(
        cx_generation_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        return build_generation_quality_disposition_list_response(
            selected_store.list_for_generation(cx_generation_id),
            cx_generation_id=cx_generation_id,
            request_id=request_id_from_headers(request),
            trace_id=trace_id_from_headers(request),
        )

    @app.get(
        (
            "/admin/v1/generation-audit/generations/{cx_generation_id}"
            "/quality-dispositions/{disposition_id}"
        ),
        response_model=None,
    )
    def get_generation_quality_disposition(
        cx_generation_id: str,
        disposition_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        record = selected_store.get(disposition_id)
        if record is None or record.get("cx_generation_id") != cx_generation_id:
            return problem_response(
                request,
                status_code=404,
                error_code="ag.generation_quality_disposition_not_found",
                title="Generation quality disposition not found",
                detail=f"Disposition was not found: {disposition_id}",
                type_uri=(
                    "https://nex-platform.local/problems/"
                    "generation-quality-disposition-not-found"
                ),
            )
        return record


def build_generation_quality_disposition_list_response(
    records: list[dict[str, Any]],
    *,
    cx_generation_id: str,
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    items = sorted(
        records,
        key=lambda record: (str(record.get("updated_at")), str(record.get("disposition_id"))),
        reverse=True,
    )
    by_status: dict[str, int] = {}
    for record in items:
        status = str(record.get("disposition_status") or "UNKNOWN")
        by_status[status] = by_status.get(status, 0) + 1
    return {
        "disposition_list_schema_version": DISPOSITION_LIST_SCHEMA_VERSION,
        "cx_generation_id": cx_generation_id,
        "trace_id": trace_id,
        "request_id": request_id,
        "items": items,
        "summary": {
            "count": len(items),
            "by_status": by_status,
            "latest_updated_at": items[0]["updated_at"] if items else None,
        },
    }


def emit_generation_quality_disposition_event(
    audit_emitter: OperationalEventEmitter,
    record: dict[str, Any],
) -> OperationalEventEmitResult:
    operator_ref = record.get("operator_ref") if isinstance(record.get("operator_ref"), dict) else {}
    return audit_emitter.safe_emit(
        event_type=DISPOSITION_RECORDED_EVENT_TYPE,
        severity="INFO",
        message="Generation quality operator disposition recorded.",
        trace_id=record.get("trace_id"),
        request_id=record.get("request_id"),
        subject_ref={
            "type": "generation_quality_disposition",
            "id": str(record["disposition_id"]),
        },
        details={
            "cx_generation_id": record.get("cx_generation_id"),
            "disposition_id": record.get("disposition_id"),
            "operator_action": record.get("operator_action"),
            "disposition_status": record.get("disposition_status"),
            "operator_type": operator_ref.get("operator_type"),
            "operator_id": operator_ref.get("operator_id"),
            "reason_count": len(record.get("reason_codes") or []),
            "quality_issue_ref_count": len(record.get("quality_issue_refs") or []),
        },
    )


def build_generation_quality_disposition_record(
    payload: dict[str, Any],
    *,
    cx_generation_id: str,
    request_id: str,
    trace_id: str,
    created_at: str | None = None,
) -> dict[str, Any]:
    assert_disposition_payload_redaction_safe(payload)
    generation_id = required_text({"cx_generation_id": cx_generation_id}, "cx_generation_id")
    operator_action = required_choice(
        payload,
        "operator_action",
        choices=ALLOWED_OPERATOR_ACTIONS,
    )
    operator = operator_ref(payload.get("operator_ref"))
    reason_codes = reason_code_list(payload.get("reason_codes"))
    note = optional_text(payload.get("operator_note"))
    note_hash = sha256_text(note) if note is not None else None
    now = created_at or _utc_now()
    disposition_id = optional_text(payload.get("disposition_id")) or str(
        uuid5(
            NAMESPACE_URL,
            (
                "ag-generation-quality-disposition:"
                f"{generation_id}:{operator['operator_id']}:{operator_action}:"
                f"{','.join(reason_codes)}:{note_hash or 'no-note'}:{request_id}"
            ),
        )
    )
    return {
        "disposition_schema_version": DISPOSITION_SCHEMA_VERSION,
        "disposition_id": disposition_id,
        "cx_generation_id": generation_id,
        "trace_id": trace_id,
        "request_id": request_id,
        "operator_ref": operator,
        "operator_action": operator_action,
        "disposition_status": ACTION_STATUS[operator_action],
        "reason_codes": reason_codes,
        "operator_note_hash": note_hash,
        "operator_note_preview": operator_note_preview(note),
        "quality_issue_refs": quality_issue_refs(payload.get("quality_issue_refs")),
        "metadata": {
            "raw_note_stored": False,
            "raw_prompt_stored": False,
            "raw_generation_output_stored": False,
            "operator_note_storage": "hash_and_short_preview_only",
        },
        "created_at": now,
        "updated_at": now,
    }


def operator_ref(value: Any) -> dict[str, str | None]:
    if not isinstance(value, dict):
        raise GenerationQualityDispositionError(
            status_code=422,
            error_code="ag.generation_quality_disposition_operator_ref_required",
            detail="operator_ref is required.",
        )
    return {
        "operator_type": required_choice(
            value,
            "operator_type",
            choices=("service", "user"),
        ),
        "operator_id": required_text(value, "operator_id"),
        "tenant_id": optional_text(value.get("tenant_id")),
    }


def reason_code_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise GenerationQualityDispositionError(
            status_code=422,
            error_code="ag.generation_quality_disposition_reasons_invalid",
            detail="reason_codes must be a list when supplied.",
        )
    reason_codes: list[str] = []
    for reason in value:
        if not isinstance(reason, str) or not reason.strip():
            raise GenerationQualityDispositionError(
                status_code=422,
                error_code="ag.generation_quality_disposition_reason_invalid",
                detail="reason code must be a non-empty string.",
            )
        normalized = reason.strip()
        if normalized not in ALLOWED_REASON_CODES:
            raise GenerationQualityDispositionError(
                status_code=422,
                error_code="ag.generation_quality_disposition_reason_unsupported",
                detail=f"unsupported reason code: {normalized}",
            )
        if normalized not in reason_codes:
            reason_codes.append(normalized)
    return reason_codes


def quality_issue_refs(value: Any) -> list[dict[str, str | None]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise GenerationQualityDispositionError(
            status_code=422,
            error_code="ag.generation_quality_disposition_quality_refs_invalid",
            detail="quality_issue_refs must be a list when supplied.",
        )
    refs: list[dict[str, str | None]] = []
    for item in value:
        if not isinstance(item, dict):
            raise GenerationQualityDispositionError(
                status_code=422,
                error_code="ag.generation_quality_disposition_quality_ref_invalid",
                detail="quality issue reference must be an object.",
            )
        refs.append(
            {
                "source_service": required_choice(
                    item,
                    "source_service",
                    choices=ALLOWED_QUALITY_ISSUE_SOURCE_SERVICES,
                ),
                "issue_type": required_choice(
                    item,
                    "issue_type",
                    choices=ALLOWED_QUALITY_ISSUE_TYPES,
                ),
                "issue_code": required_text(item, "issue_code"),
                "issue_ref_id": optional_text(item.get("issue_ref_id")),
            }
        )
    return refs


def operator_note_preview(note: str | None) -> str | None:
    if note is None:
        return None
    return note.strip()[:MAX_OPERATOR_NOTE_PREVIEW_LENGTH]


def required_choice(
    payload: dict[str, Any],
    key: str,
    *,
    choices: tuple[str, ...],
) -> str:
    value = required_text(payload, key)
    if value not in choices:
        raise GenerationQualityDispositionError(
            status_code=422,
            error_code=f"ag.generation_quality_disposition_{key}_unsupported",
            detail=f"unsupported {key}: {value}",
        )
    return value


def required_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise GenerationQualityDispositionError(
            status_code=422,
            error_code=f"ag.generation_quality_disposition_{key}_required",
            detail=f"{key} is required.",
        )
    return value.strip()


def optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def find_sensitive_disposition_keys(payload: Any) -> list[str]:
    matches: list[str] = []
    _collect_sensitive_keys(payload, path="", matches=matches)
    return matches


def assert_disposition_payload_redaction_safe(payload: dict[str, Any]) -> None:
    sensitive_keys = find_sensitive_disposition_keys(payload)
    if sensitive_keys:
        raise GenerationQualityDispositionError(
            status_code=422,
            error_code="ag.generation_quality_disposition_sensitive_payload",
            detail=f"Disposition payload contains sensitive keys: {', '.join(sensitive_keys)}",
        )


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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


def _disposition_upsert_sql(dialect_name: str) -> str:
    operator_ref_expr = _json_param_expr("operator_ref", dialect_name)
    reason_codes_expr = _json_param_expr("reason_codes", dialect_name)
    quality_issue_refs_expr = _json_param_expr("quality_issue_refs", dialect_name)
    metadata_expr = _json_param_expr("metadata", dialect_name)
    return f"""
        INSERT INTO ag_generation_quality_operator_dispositions (
            disposition_id,
            disposition_schema_version,
            cx_generation_id,
            trace_id,
            request_id,
            operator_type,
            operator_id,
            tenant_id,
            operator_ref,
            operator_action,
            disposition_status,
            reason_codes,
            operator_note_hash,
            operator_note_preview,
            quality_issue_refs,
            metadata,
            created_at,
            updated_at
        )
        VALUES (
            :disposition_id,
            :disposition_schema_version,
            :cx_generation_id,
            :trace_id,
            :request_id,
            :operator_type,
            :operator_id,
            :tenant_id,
            {operator_ref_expr},
            :operator_action,
            :disposition_status,
            {reason_codes_expr},
            :operator_note_hash,
            :operator_note_preview,
            {quality_issue_refs_expr},
            {metadata_expr},
            :created_at,
            :updated_at
        )
        ON CONFLICT (disposition_id) DO UPDATE SET
            trace_id = excluded.trace_id,
            request_id = excluded.request_id,
            operator_type = excluded.operator_type,
            operator_id = excluded.operator_id,
            tenant_id = excluded.tenant_id,
            operator_ref = excluded.operator_ref,
            operator_action = excluded.operator_action,
            disposition_status = excluded.disposition_status,
            reason_codes = excluded.reason_codes,
            operator_note_hash = excluded.operator_note_hash,
            operator_note_preview = excluded.operator_note_preview,
            quality_issue_refs = excluded.quality_issue_refs,
            metadata = excluded.metadata,
            updated_at = excluded.updated_at
    """


def _disposition_select_sql(where_clause: str) -> str:
    return f"""
        SELECT
            disposition_schema_version,
            disposition_id,
            cx_generation_id,
            trace_id,
            request_id,
            operator_ref,
            operator_action,
            disposition_status,
            reason_codes,
            operator_note_hash,
            operator_note_preview,
            quality_issue_refs,
            metadata,
            created_at,
            updated_at
        FROM ag_generation_quality_operator_dispositions
        WHERE {where_clause}
    """


def _disposition_record_params(record: dict[str, Any]) -> dict[str, Any]:
    operator = record["operator_ref"]
    return {
        **record,
        "operator_type": operator["operator_type"],
        "operator_id": operator["operator_id"],
        "tenant_id": operator.get("tenant_id"),
        "operator_ref": json.dumps(record["operator_ref"]),
        "reason_codes": json.dumps(record["reason_codes"]),
        "quality_issue_refs": json.dumps(record["quality_issue_refs"]),
        "metadata": json.dumps(record["metadata"]),
    }


def _disposition_record_from_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    return {
        "disposition_schema_version": data["disposition_schema_version"],
        "disposition_id": data["disposition_id"],
        "cx_generation_id": data["cx_generation_id"],
        "trace_id": data["trace_id"],
        "request_id": data["request_id"],
        "operator_ref": _json_value(data["operator_ref"], {}),
        "operator_action": data["operator_action"],
        "disposition_status": data["disposition_status"],
        "reason_codes": _json_value(data["reason_codes"], []),
        "operator_note_hash": data["operator_note_hash"],
        "operator_note_preview": data["operator_note_preview"],
        "quality_issue_refs": _json_value(data["quality_issue_refs"], []),
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


def _store_unavailable_error() -> GenerationQualityDispositionError:
    return GenerationQualityDispositionError(
        status_code=503,
        error_code="ag.generation_quality_disposition_store_unavailable",
        detail="Generation quality disposition store is unavailable.",
    )


def _authorize_ag_request(
    request: Request,
    authorization: str | None,
) -> JSONResponse | None:
    result = validate_authorization_header(
        authorization,
        expected_audience="nex-ag",
        required_scopes=[DEFAULT_SERVICE_SCOPE],
    )
    if result.ok:
        return None

    return problem_response(
        request,
        status_code=401,
        error_code=result.error_code or "SERVICE_CLAIM_INVALID",
        title="Authentication failed",
        detail=result.detail or "AG requires a valid service claim.",
        type_uri="https://nex-platform.local/problems/authentication-failed",
    )


def _disposition_problem_response(
    request: Request,
    exc: GenerationQualityDispositionError,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Generation quality disposition rejected",
        detail=exc.detail,
        type_uri=(
            "https://nex-platform.local/problems/"
            "generation-quality-disposition-rejected"
        ),
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
