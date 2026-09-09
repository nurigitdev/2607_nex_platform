from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from fastapi import Body, FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    DEFAULT_USER_SCOPE,
    InMemoryOperationalEventStore,
    OperationalEventEmitter,
    OperationalEventEmitResult,
    OperationalEventStore,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
    validate_authorization_header,
    validate_user_authorization_header,
)


OPERATOR_REVIEW_NOTE_SCHEMA_VERSION = "ag_operator_review_note.v1"
OPERATOR_REVIEW_NOTE_LIST_SCHEMA_VERSION = "ag_operator_review_note_list.v1"
OPERATOR_REVIEW_NOTE_MUTATION_SCHEMA_VERSION = "ag_operator_review_note_mutation.v1"
OPERATOR_REVIEW_NOTE_RECORDED_EVENT_TYPE = "ag.operator_review_note.recorded"
OPERATOR_EVIDENCE_EXPORT_SCHEMA_VERSION = "ag_redacted_evidence_export.v1"
OPERATOR_EVIDENCE_EXPORT_LIST_SCHEMA_VERSION = (
    "ag_redacted_evidence_export_list.v1"
)
AG_OPERATOR_NOTE_TABLE = "ag_op_notes"
AG_EVIDENCE_EXPORT_TABLE = "ag_ev_exports"
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
ALLOWED_IDEMPOTENCY_STATUSES = ("NEW", "REPLAYED", "CONFLICT")
ALLOWED_EXPORT_STATUSES = ("REQUESTED", "READY", "FAILED", "CANCELLED")
ALLOWED_EXPORT_FORMATS = ("json", "jsonl", "zip_manifest")
ALLOWED_EVIDENCE_TYPES = (
    "operator_note",
    "worker_result",
    "generation_quality",
    "retrieval_package",
    "artifact",
    "remediation_task",
    "processing_run",
    "service_log",
    "operational_event",
)
ALLOWED_EVIDENCE_REDACTION_STATUSES = (
    "METADATA_ONLY",
    "HASH_ONLY",
    "REDACTED",
    "OMITTED",
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
    "source_file_path",
    "source_text",
    "storage_path",
    "storage_uri",
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


@dataclass
class OperatorEvidenceExportStore:
    records: dict[str, dict[str, Any]] = field(default_factory=dict)

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        self.records[record["export_id"]] = record
        return record

    def get(self, export_id: str) -> dict[str, Any] | None:
        return self.records.get(export_id)

    def list_exports(
        self,
        *,
        target_service: str | None = None,
        target_kind: str | None = None,
        target_id: str | None = None,
        trace_id: str | None = None,
        export_status: str | None = None,
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
                note_status=None,
                operator_type=operator_type,
                operator_id=operator_id,
            )
            and (export_status is None or record.get("export_status") == export_status)
        ]
        selected.sort(
            key=lambda record: (
                str(record.get("updated_at") or ""),
                str(record.get("export_id") or ""),
            ),
            reverse=True,
        )
        return selected[:normalize_limit(limit)]

    def delete(self, export_id: str) -> int:
        return 1 if self.records.pop(export_id, None) is not None else 0


class SqlAlchemyOperatorEvidenceExportStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        try:
            with self._session_factory() as session:
                session.execute(
                    text(_evidence_export_upsert_sql(_dialect_name(session))),
                    _evidence_export_record_params(record),
                )
                session.commit()
            return record
        except SQLAlchemyError as exc:
            raise _export_store_unavailable_error() from exc

    def get(self, export_id: str) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(
                        text(_evidence_export_select_sql("export_id = :export_id")),
                        {"export_id": export_id},
                    )
                    .mappings()
                    .first()
                )
            return _evidence_export_record_from_row(row) if row is not None else None
        except SQLAlchemyError as exc:
            raise _export_store_unavailable_error() from exc

    def list_exports(
        self,
        *,
        target_service: str | None = None,
        target_kind: str | None = None,
        target_id: str | None = None,
        trace_id: str | None = None,
        export_status: str | None = None,
        operator_type: str | None = None,
        operator_id: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        where_clause, params = _evidence_export_filter_clause(
            target_service=target_service,
            target_kind=target_kind,
            target_id=target_id,
            trace_id=trace_id,
            export_status=export_status,
            operator_type=operator_type,
            operator_id=operator_id,
        )
        params["limit"] = normalize_limit(limit)
        try:
            with self._session_factory() as session:
                rows = (
                    session.execute(
                        text(
                            _evidence_export_select_sql(
                                where_clause
                                + " ORDER BY updated_at DESC, export_id ASC"
                                + " LIMIT :limit"
                            )
                        ),
                        params,
                    )
                    .mappings()
                    .all()
                )
            return [_evidence_export_record_from_row(row) for row in rows]
        except SQLAlchemyError as exc:
            raise _export_store_unavailable_error() from exc

    def delete(self, export_id: str) -> int:
        try:
            with self._session_factory() as session:
                result = session.execute(
                    text("DELETE FROM ag_ev_exports WHERE export_id = :export_id"),
                    {"export_id": export_id},
                )
                session.commit()
                return int(result.rowcount or 0)
        except SQLAlchemyError as exc:
            raise _export_store_unavailable_error() from exc


@dataclass(frozen=True)
class OperatorReviewNoteError(Exception):
    status_code: int
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


DEFAULT_OPERATOR_REVIEW_NOTE_STORE = OperatorReviewNoteStore()
DEFAULT_OPERATOR_EVIDENCE_EXPORT_STORE = OperatorEvidenceExportStore()
DEFAULT_OPERATOR_REVIEW_NOTE_AUDIT_EVENT_STORE = InMemoryOperationalEventStore()


class OperatorReviewNoteService:
    def __init__(self, store: Any) -> None:
        self._store = store

    def create_note(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str | None,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        normalized_idempotency_key = required_idempotency_key(idempotency_key)
        canonical_payload = dict(payload)
        canonical_payload.pop("operator_note_id", None)
        record = build_operator_review_note_record(
            canonical_payload,
            request_id=request_id,
            trace_id=trace_id,
            idempotency_key=normalized_idempotency_key,
        )
        existing = self._store.get(record["operator_note_id"])
        if existing is not None:
            if operator_note_idempotency_signature(existing) != (
                operator_note_idempotency_signature(record)
            ):
                raise OperatorReviewNoteError(
                    status_code=409,
                    error_code="ag.operator_review_note_idempotency_conflict",
                    detail=(
                        "Idempotency key already maps to a different "
                        "operator review note request."
                    ),
                )
            return build_operator_review_note_mutation_response(
                existing,
                idempotency_status="REPLAYED",
                request_id=request_id,
                trace_id=trace_id,
            )
        saved = self._store.save(record)
        return build_operator_review_note_mutation_response(
            saved,
            idempotency_status="NEW",
            request_id=request_id,
            trace_id=trace_id,
        )

    def list_notes(
        self,
        *,
        request_id: str,
        trace_id: str | None,
        target_service: str | None = None,
        target_kind: str | None = None,
        target_id: str | None = None,
        note_trace_id: str | None = None,
        note_status: str | None = None,
        operator_type: str | None = None,
        operator_id: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        normalized_target_service = optional_choice(
            target_service,
            key="target_service",
            choices=ALLOWED_TARGET_SERVICES,
            default="",
        )
        normalized_note_status = optional_choice(
            note_status,
            key="note_status",
            choices=ALLOWED_NOTE_STATUSES,
            default="",
        )
        normalized_operator_type = optional_choice(
            operator_type,
            key="operator_type",
            choices=ALLOWED_OPERATOR_TYPES,
            default="",
        )
        records = self._store.list_notes(
            target_service=normalized_target_service or None,
            target_kind=optional_text(target_kind),
            target_id=optional_text(target_id),
            trace_id=optional_text(note_trace_id),
            note_status=normalized_note_status or None,
            operator_type=normalized_operator_type or None,
            operator_id=optional_text(operator_id),
            limit=limit,
        )
        return build_operator_review_note_list_response(
            records,
            request_id=request_id,
            trace_id=trace_id,
        )

    def get_note(
        self,
        operator_note_id: str,
    ) -> dict[str, Any]:
        note_id = required_text(
            {"operator_note_id": operator_note_id},
            "operator_note_id",
        )
        record = self._store.get(note_id)
        if record is None:
            raise OperatorReviewNoteError(
                status_code=404,
                error_code="ag.operator_review_note_not_found",
                detail=f"Operator review note was not found: {note_id}",
            )
        return record


def default_operator_review_note_store(app: FastAPI) -> Any:
    persistence = getattr(app.state, "nex_persistence", None)
    session_factory = getattr(persistence, "api_session_factory", None)
    if session_factory is not None:
        return SqlAlchemyOperatorReviewNoteStore(session_factory)
    return DEFAULT_OPERATOR_REVIEW_NOTE_STORE


def default_operator_evidence_export_store(app: FastAPI) -> Any:
    persistence = getattr(app.state, "nex_persistence", None)
    session_factory = getattr(persistence, "api_session_factory", None)
    if session_factory is not None:
        return SqlAlchemyOperatorEvidenceExportStore(session_factory)
    return DEFAULT_OPERATOR_EVIDENCE_EXPORT_STORE


def register_operator_review_note_routes(
    app: FastAPI,
    *,
    store: Any | None = None,
    audit_event_store: OperationalEventStore | None = None,
) -> None:
    service = OperatorReviewNoteService(store or default_operator_review_note_store(app))
    audit_emitter = OperationalEventEmitter(
        service_id="nex-ag",
        store=audit_event_store or DEFAULT_OPERATOR_REVIEW_NOTE_AUDIT_EVENT_STORE,
    )

    @app.post("/admin/v1/operator-review/notes", response_model=None)
    def create_operator_review_note(
        request: Request,
        authorization: str | None = Header(default=None),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        payload: dict[str, Any] = Body(...),
    ):
        auth_problem = _authorize_ag_operator_review_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        try:
            response = service.create_note(
                payload,
                request_id=request_id_from_headers(request),
                trace_id=trace_id_from_headers(request),
                idempotency_key=idempotency_key,
            )
        except OperatorReviewNoteError as exc:
            return _operator_review_note_problem_response(request, exc)

        if response["idempotency_status"] == "NEW":
            emit_operator_review_note_event(audit_emitter, response["operator_note"])
        return JSONResponse(
            status_code=201 if response["idempotency_status"] == "NEW" else 200,
            content=response,
        )

    @app.get("/admin/v1/operator-review/notes", response_model=None)
    def list_operator_review_notes(
        request: Request,
        authorization: str | None = Header(default=None),
        target_service: str | None = None,
        target_kind: str | None = None,
        target_id: str | None = None,
        note_trace_id: str | None = Query(default=None, alias="trace_id"),
        note_status: str | None = None,
        operator_type: str | None = None,
        operator_id: str | None = None,
        limit: int | None = None,
    ):
        auth_problem = _authorize_ag_operator_review_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        try:
            return service.list_notes(
                request_id=request_id_from_headers(request),
                trace_id=trace_id_from_headers(request),
                target_service=target_service,
                target_kind=target_kind,
                target_id=target_id,
                note_trace_id=note_trace_id,
                note_status=note_status,
                operator_type=operator_type,
                operator_id=operator_id,
                limit=limit,
            )
        except OperatorReviewNoteError as exc:
            return _operator_review_note_problem_response(request, exc)

    @app.get("/admin/v1/operator-review/notes/{operator_note_id}", response_model=None)
    def get_operator_review_note(
        operator_note_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_ag_operator_review_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        try:
            return service.get_note(operator_note_id)
        except OperatorReviewNoteError as exc:
            return _operator_review_note_problem_response(request, exc)


def emit_operator_review_note_event(
    audit_emitter: OperationalEventEmitter,
    record: dict[str, Any],
) -> OperationalEventEmitResult:
    operator = record.get("operator_ref") if isinstance(record.get("operator_ref"), dict) else {}
    return audit_emitter.safe_emit(
        event_type=OPERATOR_REVIEW_NOTE_RECORDED_EVENT_TYPE,
        severity="INFO",
        message="AG operator review note recorded.",
        trace_id=record.get("trace_id"),
        request_id=record.get("request_id"),
        subject_ref={
            "type": "operator_review_note",
            "id": str(record["operator_note_id"]),
        },
        details={
            "operator_note_id": record.get("operator_note_id"),
            "target_service": record.get("target_service"),
            "target_kind": record.get("target_kind"),
            "target_id": record.get("target_id"),
            "note_status": record.get("note_status"),
            "note_type": record.get("note_type"),
            "severity": record.get("severity"),
            "operator_type": operator.get("operator_type"),
            "operator_id": operator.get("operator_id"),
            "reason_count": len(record.get("reason_codes") or []),
            "operator_note_hash": record.get("operator_note_hash"),
        },
    )


def build_operator_review_note_record(
    payload: dict[str, Any],
    *,
    request_id: str,
    trace_id: str | None,
    idempotency_key: str | None = None,
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
    normalized_idempotency_key = optional_text(idempotency_key)
    operator_note_id = optional_text(payload.get("operator_note_id")) or str(
        uuid5(
            NAMESPACE_URL,
            _operator_note_identity_seed(
                target=target,
                operator=operator,
                note_type=note_type,
                severity=severity,
                note_hash=note_hash,
                request_id=request_id,
                idempotency_key=normalized_idempotency_key,
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
        "metadata": operator_note_metadata(
            payload.get("metadata"),
            idempotency_key_hash=(
                sha256_text(normalized_idempotency_key)
                if normalized_idempotency_key is not None
                else None
            ),
        ),
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


def build_operator_review_note_mutation_response(
    record: dict[str, Any],
    *,
    idempotency_status: str,
    request_id: str,
    trace_id: str | None,
) -> dict[str, Any]:
    normalized_status = optional_choice(
        idempotency_status,
        key="idempotency_status",
        choices=ALLOWED_IDEMPOTENCY_STATUSES,
        default="NEW",
    )
    return {
        "operator_note_mutation_schema_version": (
            OPERATOR_REVIEW_NOTE_MUTATION_SCHEMA_VERSION
        ),
        "idempotency_status": normalized_status,
        "trace_id": optional_text(trace_id),
        "request_id": required_text({"request_id": request_id}, "request_id"),
        "operator_note": record,
        "summary": {
            "operator_note_id": record["operator_note_id"],
            "target_service": record["target_service"],
            "target_kind": record["target_kind"],
            "target_id": record["target_id"],
            "note_status": record["note_status"],
            "severity": record["severity"],
        },
    }


def build_operator_evidence_export_record(
    payload: dict[str, Any],
    *,
    request_id: str,
    trace_id: str | None,
    idempotency_key: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    assert_operator_review_note_payload_redaction_safe(payload)
    target = target_ref(payload.get("target_ref"))
    operator = operator_ref(payload.get("operator_ref"))
    export_status = optional_choice(
        payload.get("export_status"),
        key="export_status",
        choices=ALLOWED_EXPORT_STATUSES,
        default="READY",
    )
    export_format = optional_choice(
        payload.get("export_format"),
        key="export_format",
        choices=ALLOWED_EXPORT_FORMATS,
        default="json",
    )
    manifest = evidence_manifest(payload.get("evidence_refs"))
    evidence_hash = sha256_json(manifest)
    now = created_at or _utc_now()
    normalized_idempotency_key = optional_text(idempotency_key)
    export_id = optional_text(payload.get("export_id")) or str(
        uuid5(
            NAMESPACE_URL,
            _evidence_export_identity_seed(
                target=target,
                operator=operator,
                export_format=export_format,
                evidence_hash=evidence_hash,
                request_id=request_id,
                idempotency_key=normalized_idempotency_key,
            ),
        )
    )
    return {
        "export_schema_version": OPERATOR_EVIDENCE_EXPORT_SCHEMA_VERSION,
        "export_id": export_id,
        "target_service": target["target_service"],
        "target_kind": target["target_kind"],
        "target_id": target["target_id"],
        "trace_id": optional_text(trace_id),
        "request_id": required_text({"request_id": request_id}, "request_id"),
        "operator_ref": operator,
        "export_status": export_status,
        "export_format": export_format,
        "redaction_profile": "ag_redacted_manifest_v1",
        "evidence_manifest": manifest,
        "evidence_hash": evidence_hash,
        "evidence_item_count": len(manifest["items"]),
        "metadata": evidence_export_metadata(
            payload.get("metadata"),
            idempotency_key_hash=(
                sha256_text(normalized_idempotency_key)
                if normalized_idempotency_key is not None
                else None
            ),
        ),
        "created_at": now,
        "updated_at": now,
    }


def build_operator_evidence_export_list_response(
    records: list[dict[str, Any]],
    *,
    request_id: str,
    trace_id: str | None,
) -> dict[str, Any]:
    items = sorted(
        records,
        key=lambda record: (
            str(record.get("updated_at") or ""),
            str(record.get("export_id") or ""),
        ),
        reverse=True,
    )
    by_status: dict[str, int] = {}
    by_format: dict[str, int] = {}
    for record in items:
        status = str(record.get("export_status") or "UNKNOWN")
        export_format = str(record.get("export_format") or "UNKNOWN")
        by_status[status] = by_status.get(status, 0) + 1
        by_format[export_format] = by_format.get(export_format, 0) + 1
    return {
        "export_list_schema_version": OPERATOR_EVIDENCE_EXPORT_LIST_SCHEMA_VERSION,
        "trace_id": optional_text(trace_id),
        "request_id": required_text({"request_id": request_id}, "request_id"),
        "items": items,
        "summary": {
            "count": len(items),
            "by_status": by_status,
            "by_format": by_format,
            "latest_updated_at": items[0]["updated_at"] if items else None,
        },
    }


def operator_note_idempotency_signature(record: dict[str, Any]) -> dict[str, Any]:
    operator = record.get("operator_ref")
    operator_ref_value = operator if isinstance(operator, dict) else {}
    return {
        "target_service": record.get("target_service"),
        "target_kind": record.get("target_kind"),
        "target_id": record.get("target_id"),
        "operator_type": operator_ref_value.get("operator_type"),
        "operator_id": operator_ref_value.get("operator_id"),
        "note_status": record.get("note_status"),
        "note_type": record.get("note_type"),
        "severity": record.get("severity"),
        "operator_note_hash": record.get("operator_note_hash"),
        "reason_codes": list(record.get("reason_codes") or []),
        "metadata": dict(record.get("metadata") or {}),
    }


def evidence_export_idempotency_signature(record: dict[str, Any]) -> dict[str, Any]:
    operator = record.get("operator_ref")
    operator_ref_value = operator if isinstance(operator, dict) else {}
    return {
        "target_service": record.get("target_service"),
        "target_kind": record.get("target_kind"),
        "target_id": record.get("target_id"),
        "operator_type": operator_ref_value.get("operator_type"),
        "operator_id": operator_ref_value.get("operator_id"),
        "export_format": record.get("export_format"),
        "redaction_profile": record.get("redaction_profile"),
        "evidence_hash": record.get("evidence_hash"),
        "metadata": dict(record.get("metadata") or {}),
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


def operator_note_metadata(
    value: Any,
    *,
    idempotency_key_hash: str | None = None,
) -> dict[str, Any]:
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
    if idempotency_key_hash is not None:
        metadata["idempotency_key_hash"] = idempotency_key_hash
        metadata["idempotency_key_stored"] = False
    return json.loads(json.dumps(metadata))


def evidence_export_metadata(
    value: Any,
    *,
    idempotency_key_hash: str | None = None,
) -> dict[str, Any]:
    if value is None:
        metadata: dict[str, Any] = {}
    elif isinstance(value, dict):
        metadata = dict(value)
    else:
        raise OperatorReviewNoteError(
            status_code=422,
            error_code="ag.evidence_export_metadata_invalid",
            detail="metadata must be an object when supplied.",
        )
    metadata.update(
        {
            "raw_evidence_body_stored": False,
            "raw_prompt_stored": False,
            "raw_generation_output_stored": False,
            "raw_source_text_stored": False,
            "storage_paths_included": False,
            "export_storage": "redacted_manifest_plus_hashes",
        }
    )
    if idempotency_key_hash is not None:
        metadata["idempotency_key_hash"] = idempotency_key_hash
        metadata["idempotency_key_stored"] = False
    return json.loads(json.dumps(metadata))


def evidence_manifest(value: Any) -> dict[str, Any]:
    items = evidence_ref_list(value)
    return {
        "manifest_schema_version": "ag_redacted_evidence_manifest.v1",
        "redaction_profile": "ag_redacted_manifest_v1",
        "raw_payloads_included": False,
        "storage_paths_included": False,
        "items": items,
        "item_count": len(items),
    }


def evidence_ref_list(value: Any) -> list[dict[str, str | None]]:
    if value is None:
        raise OperatorReviewNoteError(
            status_code=422,
            error_code="ag.evidence_export_refs_required",
            detail="evidence_refs is required.",
        )
    if not isinstance(value, list):
        raise OperatorReviewNoteError(
            status_code=422,
            error_code="ag.evidence_export_refs_invalid",
            detail="evidence_refs must be a list.",
        )
    if not value:
        raise OperatorReviewNoteError(
            status_code=422,
            error_code="ag.evidence_export_refs_empty",
            detail="evidence_refs must contain at least one item.",
        )
    refs: list[dict[str, str | None]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in value:
        if not isinstance(item, dict):
            raise OperatorReviewNoteError(
                status_code=422,
                error_code="ag.evidence_export_ref_invalid",
                detail="evidence reference must be an object.",
            )
        ref = {
            "source_service": required_choice(
                item,
                "source_service",
                choices=ALLOWED_TARGET_SERVICES,
            ),
            "evidence_type": required_choice(
                item,
                "evidence_type",
                choices=ALLOWED_EVIDENCE_TYPES,
            ),
            "evidence_id": required_text(item, "evidence_id"),
            "relation": optional_text(item.get("relation")),
            "content_hash": optional_hex_hash(item.get("content_hash")),
            "redaction_status": optional_choice(
                item.get("redaction_status"),
                key="redaction_status",
                choices=ALLOWED_EVIDENCE_REDACTION_STATUSES,
                default="METADATA_ONLY",
            ),
        }
        dedupe_key = (
            ref["source_service"],
            ref["evidence_type"],
            ref["evidence_id"],
        )
        if dedupe_key not in seen:
            refs.append(ref)
            seen.add(dedupe_key)
    return refs


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


def required_idempotency_key(value: Any) -> str:
    normalized = optional_text(value)
    if normalized is None:
        raise OperatorReviewNoteError(
            status_code=422,
            error_code="ag.operator_review_note_idempotency_key_required",
            detail="Idempotency-Key is required for operator review note mutations.",
        )
    return normalized


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


def sha256_json(value: Any) -> str:
    return sha256_text(json.dumps(value, ensure_ascii=False, sort_keys=True))


def optional_hex_hash(value: Any) -> str | None:
    normalized = optional_text(value)
    if normalized is None:
        return None
    if len(normalized) != 64 or any(
        char not in "0123456789abcdef" for char in normalized
    ):
        raise OperatorReviewNoteError(
            status_code=422,
            error_code="ag.evidence_export_content_hash_invalid",
            detail="content_hash must be a lowercase SHA-256 hex string.",
        )
    return normalized


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


def _operator_note_identity_seed(
    *,
    target: dict[str, str],
    operator: dict[str, str | None],
    note_type: str,
    severity: str,
    note_hash: str,
    request_id: str,
    idempotency_key: str | None,
) -> str:
    if idempotency_key is not None:
        return (
            "ag-operator-review-note:idempotent:"
            f"{target['target_service']}:{target['target_kind']}:{target['target_id']}:"
            f"{operator['operator_type']}:{operator['operator_id']}:"
            f"{sha256_text(idempotency_key)}"
        )
    return (
        "ag-operator-review-note:content:"
        f"{target['target_service']}:{target['target_kind']}:{target['target_id']}:"
        f"{operator['operator_type']}:{operator['operator_id']}:"
        f"{note_type}:{severity}:{note_hash}:{request_id}"
    )


def _evidence_export_identity_seed(
    *,
    target: dict[str, str],
    operator: dict[str, str | None],
    export_format: str,
    evidence_hash: str,
    request_id: str,
    idempotency_key: str | None,
) -> str:
    if idempotency_key is not None:
        return (
            "ag-redacted-evidence-export:idempotent:"
            f"{target['target_service']}:{target['target_kind']}:{target['target_id']}:"
            f"{operator['operator_type']}:{operator['operator_id']}:"
            f"{sha256_text(idempotency_key)}"
        )
    return (
        "ag-redacted-evidence-export:content:"
        f"{target['target_service']}:{target['target_kind']}:{target['target_id']}:"
        f"{operator['operator_type']}:{operator['operator_id']}:"
        f"{export_format}:{evidence_hash}:{request_id}"
    )


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


def _evidence_export_filter_clause(
    *,
    target_service: str | None,
    target_kind: str | None,
    target_id: str | None,
    trace_id: str | None,
    export_status: str | None,
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
        ("export_status", export_status),
        ("operator_type", operator_type),
        ("operator_id", operator_id),
    ):
        if value is not None:
            clauses.append(f"{name} = :{name}")
            params[name] = value
    return " AND ".join(clauses), params


def _evidence_export_upsert_sql(dialect_name: str) -> str:
    operator_ref_expr = _json_param_expr("operator_ref", dialect_name)
    evidence_manifest_expr = _json_param_expr("evidence_manifest", dialect_name)
    metadata_expr = _json_param_expr("metadata", dialect_name)
    return f"""
        INSERT INTO ag_ev_exports (
            export_id,
            export_schema_version,
            target_service,
            target_kind,
            target_id,
            trace_id,
            request_id,
            operator_type,
            operator_id,
            tenant_id,
            operator_ref,
            export_status,
            export_format,
            redaction_profile,
            evidence_manifest,
            evidence_hash,
            evidence_item_count,
            metadata,
            created_at,
            updated_at
        )
        VALUES (
            :export_id,
            :export_schema_version,
            :target_service,
            :target_kind,
            :target_id,
            :trace_id,
            :request_id,
            :operator_type,
            :operator_id,
            :tenant_id,
            {operator_ref_expr},
            :export_status,
            :export_format,
            :redaction_profile,
            {evidence_manifest_expr},
            :evidence_hash,
            :evidence_item_count,
            {metadata_expr},
            :created_at,
            :updated_at
        )
        ON CONFLICT (export_id) DO UPDATE SET
            export_schema_version = excluded.export_schema_version,
            target_service = excluded.target_service,
            target_kind = excluded.target_kind,
            target_id = excluded.target_id,
            trace_id = excluded.trace_id,
            request_id = excluded.request_id,
            operator_type = excluded.operator_type,
            operator_id = excluded.operator_id,
            tenant_id = excluded.tenant_id,
            operator_ref = excluded.operator_ref,
            export_status = excluded.export_status,
            export_format = excluded.export_format,
            redaction_profile = excluded.redaction_profile,
            evidence_manifest = excluded.evidence_manifest,
            evidence_hash = excluded.evidence_hash,
            evidence_item_count = excluded.evidence_item_count,
            metadata = excluded.metadata,
            updated_at = excluded.updated_at
    """


def _evidence_export_select_sql(where_clause: str) -> str:
    return f"""
        SELECT
            export_schema_version,
            export_id,
            target_service,
            target_kind,
            target_id,
            trace_id,
            request_id,
            operator_ref,
            export_status,
            export_format,
            redaction_profile,
            evidence_manifest,
            evidence_hash,
            evidence_item_count,
            metadata,
            created_at,
            updated_at
        FROM ag_ev_exports
        WHERE {where_clause}
    """


def _evidence_export_record_params(record: dict[str, Any]) -> dict[str, Any]:
    operator = record["operator_ref"]
    return {
        **record,
        "operator_type": operator["operator_type"],
        "operator_id": operator["operator_id"],
        "tenant_id": operator.get("tenant_id"),
        "operator_ref": json.dumps(record["operator_ref"]),
        "evidence_manifest": json.dumps(record["evidence_manifest"]),
        "metadata": json.dumps(record["metadata"]),
    }


def _evidence_export_record_from_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    return {
        "export_schema_version": data["export_schema_version"],
        "export_id": data["export_id"],
        "target_service": data["target_service"],
        "target_kind": data["target_kind"],
        "target_id": data["target_id"],
        "trace_id": data["trace_id"],
        "request_id": data["request_id"],
        "operator_ref": _json_value(data["operator_ref"], {}),
        "export_status": data["export_status"],
        "export_format": data["export_format"],
        "redaction_profile": data["redaction_profile"],
        "evidence_manifest": _json_value(data["evidence_manifest"], {}),
        "evidence_hash": data["evidence_hash"],
        "evidence_item_count": int(data["evidence_item_count"]),
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


def _export_store_unavailable_error() -> OperatorReviewNoteError:
    return OperatorReviewNoteError(
        status_code=503,
        error_code="ag.evidence_export_store_unavailable",
        detail="Operator evidence export store is unavailable.",
    )


def _authorize_ag_operator_review_request(
    request: Request,
    authorization: str | None,
) -> JSONResponse | None:
    service_result = validate_authorization_header(
        authorization,
        expected_audience="nex-ag",
        required_scopes=[DEFAULT_SERVICE_SCOPE],
    )
    if service_result.ok:
        return None

    user_result = validate_user_authorization_header(
        authorization,
        expected_audience="nex-ag",
        required_scopes=[DEFAULT_USER_SCOPE],
    )
    if user_result.ok:
        roles = set(user_result.claims.roles if user_result.claims else ())
        if "admin" in roles:
            return None
        return problem_response(
            request,
            status_code=403,
            error_code="AG_OPERATOR_REVIEW_ADMIN_ROLE_REQUIRED",
            title="Authorization failed",
            detail="AG operator review note routes require an admin user role.",
            type_uri="https://nex-platform.local/problems/authorization-failed",
        )

    return problem_response(
        request,
        status_code=401,
        error_code=service_result.error_code or "SERVICE_CLAIM_INVALID",
        title="Authentication failed",
        detail=service_result.detail or "AG requires a valid service claim.",
        type_uri="https://nex-platform.local/problems/authentication-failed",
    )


def _operator_review_note_problem_response(
    request: Request,
    exc: OperatorReviewNoteError,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Operator review note request rejected",
        detail=exc.detail,
        type_uri="https://nex-platform.local/problems/operator-review-note-rejected",
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
