from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from fastapi import Body, FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_runtime import (
    InMemoryOperationalEventStore,
    OperationalEventEmitter,
    OperationalEventEmitResult,
    OperationalEventStore,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
)

from .operator_reviews import (
    ALLOWED_OPERATOR_TYPES,
    ALLOWED_TARGET_SERVICES,
    OperatorReviewNoteError,
    _authorize_ag_operator_review_request,
    _datetime_value,
    _dialect_name,
    _json_param_expr,
    _json_value,
    _utc_now,
    assert_operator_review_note_payload_redaction_safe,
    normalize_limit,
    operator_note_preview,
    operator_ref,
    optional_choice,
    optional_text,
    reason_code_list,
    required_text,
    sha256_text,
    target_ref,
)


OPERATOR_REVIEW_CASE_SCHEMA_VERSION = "ag_operator_review_case.v1"
OPERATOR_REVIEW_CASE_LIST_SCHEMA_VERSION = "ag_operator_review_case_list.v1"
OPERATOR_REVIEW_CASE_MUTATION_SCHEMA_VERSION = "ag_operator_review_case_mutation.v1"
OPERATOR_REVIEW_CASE_ACTION_SCHEMA_VERSION = "ag_operator_review_case_action.v1"
OPERATOR_REVIEW_CASE_ACTION_MUTATION_SCHEMA_VERSION = (
    "ag_operator_review_case_action_mutation.v1"
)
OPERATOR_REVIEW_CASE_RECORDED_EVENT_TYPE = "ag.operator_review_case.recorded"
OPERATOR_REVIEW_CASE_ACTION_RECORDED_EVENT_TYPE = (
    "ag.operator_review_case_action.recorded"
)
AG_OPERATOR_REVIEW_CASE_TABLE = "ag_op_cases"
MAX_CASE_COMMENT_PREVIEW_LENGTH = 240

ALLOWED_CASE_ACTIONS = (
    "CREATE_CASE",
    "ACKNOWLEDGE",
    "ASSIGN",
    "RESOLVE",
    "DISMISS",
    "REOPEN",
)
ALLOWED_CASE_STATUSES = (
    "OPEN",
    "ACKNOWLEDGED",
    "ASSIGNED",
    "RESOLVED",
    "DISMISSED",
    "REOPENED",
)
ALLOWED_CASE_PRIORITIES = ("LOW", "MEDIUM", "HIGH", "URGENT")
CASE_ACTION_TARGET_STATUSES = {
    "ACKNOWLEDGE": "ACKNOWLEDGED",
    "ASSIGN": "ASSIGNED",
    "RESOLVE": "RESOLVED",
    "DISMISS": "DISMISSED",
    "REOPEN": "REOPENED",
}
CASE_ACTION_ALLOWED_FROM = {
    "ACKNOWLEDGE": ("OPEN", "REOPENED"),
    "ASSIGN": ("OPEN", "ACKNOWLEDGED", "ASSIGNED", "REOPENED"),
    "RESOLVE": ("OPEN", "ACKNOWLEDGED", "ASSIGNED", "REOPENED"),
    "DISMISS": ("OPEN", "ACKNOWLEDGED", "ASSIGNED", "REOPENED"),
    "REOPEN": ("RESOLVED", "DISMISSED"),
}


@dataclass
class OperatorReviewCaseStore:
    records: dict[str, dict[str, Any]] = field(default_factory=dict)

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        self.records[record["case_id"]] = record
        return record

    def get(self, case_id: str) -> dict[str, Any] | None:
        return self.records.get(case_id)

    def list_cases(
        self,
        *,
        target_service: str | None = None,
        target_kind: str | None = None,
        target_id: str | None = None,
        trace_id: str | None = None,
        case_status: str | None = None,
        case_priority: str | None = None,
        operator_type: str | None = None,
        operator_id: str | None = None,
        assignee_id: str | None = None,
        updated_from: str | None = None,
        updated_to: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        selected = [
            record
            for record in self.records.values()
            if _case_matches_filter(
                record,
                target_service=target_service,
                target_kind=target_kind,
                target_id=target_id,
                trace_id=trace_id,
                case_status=case_status,
                case_priority=case_priority,
                operator_type=operator_type,
                operator_id=operator_id,
                assignee_id=assignee_id,
                updated_from=updated_from,
                updated_to=updated_to,
            )
        ]
        selected.sort(
            key=lambda record: (
                str(record.get("updated_at") or ""),
                str(record.get("case_id") or ""),
            ),
            reverse=True,
        )
        return selected[:normalize_limit(limit)]

    def delete(self, case_id: str) -> int:
        return 1 if self.records.pop(case_id, None) is not None else 0


class SqlAlchemyOperatorReviewCaseStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        try:
            with self._session_factory() as session:
                session.execute(
                    text(_operator_review_case_upsert_sql(_dialect_name(session))),
                    _operator_review_case_record_params(record),
                )
                session.commit()
            return record
        except SQLAlchemyError as exc:
            raise _case_store_unavailable_error() from exc

    def get(self, case_id: str) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(
                        text(_operator_review_case_select_sql("case_id = :case_id")),
                        {"case_id": case_id},
                    )
                    .mappings()
                    .first()
                )
            return _operator_review_case_record_from_row(row) if row else None
        except SQLAlchemyError as exc:
            raise _case_store_unavailable_error() from exc

    def list_cases(
        self,
        *,
        target_service: str | None = None,
        target_kind: str | None = None,
        target_id: str | None = None,
        trace_id: str | None = None,
        case_status: str | None = None,
        case_priority: str | None = None,
        operator_type: str | None = None,
        operator_id: str | None = None,
        assignee_id: str | None = None,
        updated_from: str | None = None,
        updated_to: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        where_clause, params = _operator_review_case_filter_clause(
            target_service=target_service,
            target_kind=target_kind,
            target_id=target_id,
            trace_id=trace_id,
            case_status=case_status,
            case_priority=case_priority,
            operator_type=operator_type,
            operator_id=operator_id,
            assignee_id=assignee_id,
            updated_from=updated_from,
            updated_to=updated_to,
        )
        params["limit"] = normalize_limit(limit)
        try:
            with self._session_factory() as session:
                rows = (
                    session.execute(
                        text(
                            _operator_review_case_select_sql(
                                where_clause
                                + " ORDER BY updated_at DESC, case_id ASC"
                                + " LIMIT :limit"
                            )
                        ),
                        params,
                    )
                    .mappings()
                    .all()
                )
            return [_operator_review_case_record_from_row(row) for row in rows]
        except SQLAlchemyError as exc:
            raise _case_store_unavailable_error() from exc

    def delete(self, case_id: str) -> int:
        try:
            with self._session_factory() as session:
                result = session.execute(
                    text("DELETE FROM ag_op_cases WHERE case_id = :case_id"),
                    {"case_id": case_id},
                )
                session.commit()
                return int(result.rowcount or 0)
        except SQLAlchemyError as exc:
            raise _case_store_unavailable_error() from exc


DEFAULT_OPERATOR_REVIEW_CASE_STORE = OperatorReviewCaseStore()
DEFAULT_OPERATOR_REVIEW_CASE_AUDIT_EVENT_STORE = InMemoryOperationalEventStore()


class OperatorReviewCaseService:
    def __init__(self, store: Any) -> None:
        self._store = store

    def create_case(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str | None,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        normalized_idempotency_key = required_case_idempotency_key(idempotency_key)
        canonical_payload = dict(payload)
        canonical_payload.pop("case_id", None)
        record = build_operator_review_case_record(
            canonical_payload,
            request_id=request_id,
            trace_id=trace_id,
            idempotency_key=normalized_idempotency_key,
        )
        existing = self._store.get(record["case_id"])
        if existing is not None:
            if operator_review_case_idempotency_signature(existing) != (
                operator_review_case_idempotency_signature(record)
            ):
                raise OperatorReviewNoteError(
                    status_code=409,
                    error_code="ag.operator_review_case_idempotency_conflict",
                    detail=(
                        "Idempotency key already maps to a different "
                        "operator review case request."
                    ),
                )
            return build_operator_review_case_mutation_response(
                existing,
                idempotency_status="REPLAYED",
                request_id=request_id,
                trace_id=trace_id,
            )
        saved = self._store.save(record)
        return build_operator_review_case_mutation_response(
            saved,
            idempotency_status="NEW",
            request_id=request_id,
            trace_id=trace_id,
        )

    def list_cases(
        self,
        *,
        request_id: str,
        trace_id: str | None,
        target_service: str | None = None,
        target_kind: str | None = None,
        target_id: str | None = None,
        case_trace_id: str | None = None,
        case_status: str | None = None,
        case_priority: str | None = None,
        operator_type: str | None = None,
        operator_id: str | None = None,
        assignee_id: str | None = None,
        updated_from: str | None = None,
        updated_to: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        normalized_target_service = optional_choice(
            target_service,
            key="target_service",
            choices=ALLOWED_TARGET_SERVICES,
            default="",
        )
        normalized_case_status = optional_choice(
            case_status,
            key="case_status",
            choices=ALLOWED_CASE_STATUSES,
            default="",
        )
        normalized_case_priority = optional_choice(
            case_priority,
            key="case_priority",
            choices=ALLOWED_CASE_PRIORITIES,
            default="",
        )
        normalized_operator_type = optional_choice(
            operator_type,
            key="operator_type",
            choices=ALLOWED_OPERATOR_TYPES,
            default="",
        )
        records = self._store.list_cases(
            target_service=normalized_target_service or None,
            target_kind=optional_text(target_kind),
            target_id=optional_text(target_id),
            trace_id=optional_text(case_trace_id),
            case_status=normalized_case_status or None,
            case_priority=normalized_case_priority or None,
            operator_type=normalized_operator_type or None,
            operator_id=optional_text(operator_id),
            assignee_id=optional_text(assignee_id),
            updated_from=optional_text(updated_from),
            updated_to=optional_text(updated_to),
            limit=limit,
        )
        return build_operator_review_case_list_response(
            records,
            request_id=request_id,
            trace_id=trace_id,
        )

    def get_case(self, case_id: str) -> dict[str, Any]:
        normalized_case_id = required_case_id(case_id)
        record = self._store.get(normalized_case_id)
        if record is None:
            raise OperatorReviewNoteError(
                status_code=404,
                error_code="ag.operator_review_case_not_found",
                detail=f"Operator review case was not found: {case_id}",
            )
        return record

    def apply_action(
        self,
        case_id: str,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str | None,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        normalized_case_id = required_case_id(case_id)
        normalized_idempotency_key = required_case_action_idempotency_key(
            idempotency_key
        )
        record = self.get_case(normalized_case_id)
        action_id = operator_review_case_action_id(
            normalized_case_id,
            normalized_idempotency_key,
        )
        request_signature = operator_review_case_action_request_signature(
            normalized_case_id,
            payload,
        )
        previous_action = _latest_case_action_summary(record)
        if previous_action is not None and previous_action.get("action_id") == action_id:
            if previous_action.get("request_signature") != request_signature:
                raise OperatorReviewNoteError(
                    status_code=409,
                    error_code="ag.operator_review_case_action_idempotency_conflict",
                    detail=(
                        "Idempotency key already maps to a different "
                        "operator review case action."
                    ),
                )
            return build_operator_review_case_action_mutation_response(
                record,
                previous_action["record"],
                idempotency_status="REPLAYED",
                request_id=request_id,
                trace_id=trace_id,
            )
        updated, action = apply_operator_review_case_action(
            record,
            payload,
            request_id=request_id,
            trace_id=trace_id,
            idempotency_key=normalized_idempotency_key,
        )
        updated["metadata"]["last_action"] = {
            "action_id": action["action_id"],
            "action_type": action["action_type"],
            "request_signature": request_signature,
            "record": action,
        }
        saved = self._store.save(updated)
        return build_operator_review_case_action_mutation_response(
            saved,
            action,
            idempotency_status="NEW",
            request_id=request_id,
            trace_id=trace_id,
        )


def default_operator_review_case_store(app: FastAPI) -> Any:
    persistence = getattr(app.state, "nex_persistence", None)
    session_factory = getattr(persistence, "api_session_factory", None)
    if session_factory is not None:
        return SqlAlchemyOperatorReviewCaseStore(session_factory)
    return DEFAULT_OPERATOR_REVIEW_CASE_STORE


def register_operator_review_case_routes(
    app: FastAPI,
    *,
    store: Any | None = None,
    audit_event_store: OperationalEventStore | None = None,
) -> None:
    service = OperatorReviewCaseService(store or default_operator_review_case_store(app))
    audit_emitter = OperationalEventEmitter(
        service_id="nex-ag",
        store=audit_event_store or DEFAULT_OPERATOR_REVIEW_CASE_AUDIT_EVENT_STORE,
    )

    @app.post("/admin/v1/operator-review/cases", response_model=None)
    def create_operator_review_case(
        request: Request,
        authorization: str | None = Header(default=None),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        payload: dict[str, Any] = Body(...),
    ):
        auth_problem = _authorize_ag_operator_review_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        try:
            response = service.create_case(
                payload,
                request_id=request_id_from_headers(request),
                trace_id=trace_id_from_headers(request),
                idempotency_key=idempotency_key,
            )
        except OperatorReviewNoteError as exc:
            return _operator_review_case_problem_response(request, exc)

        if response["idempotency_status"] == "NEW":
            emit_operator_review_case_event(audit_emitter, response["case"])
        return JSONResponse(
            status_code=201 if response["idempotency_status"] == "NEW" else 200,
            content=response,
        )

    @app.get("/admin/v1/operator-review/cases", response_model=None)
    def list_operator_review_cases(
        request: Request,
        authorization: str | None = Header(default=None),
        target_service: str | None = None,
        target_kind: str | None = None,
        target_id: str | None = None,
        case_trace_id: str | None = Query(default=None, alias="trace_id"),
        case_status: str | None = None,
        case_priority: str | None = None,
        operator_type: str | None = None,
        operator_id: str | None = None,
        assignee_id: str | None = None,
        updated_from: str | None = None,
        updated_to: str | None = None,
        limit: int | None = None,
    ):
        auth_problem = _authorize_ag_operator_review_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        try:
            return service.list_cases(
                request_id=request_id_from_headers(request),
                trace_id=trace_id_from_headers(request),
                target_service=target_service,
                target_kind=target_kind,
                target_id=target_id,
                case_trace_id=case_trace_id,
                case_status=case_status,
                case_priority=case_priority,
                operator_type=operator_type,
                operator_id=operator_id,
                assignee_id=assignee_id,
                updated_from=updated_from,
                updated_to=updated_to,
                limit=limit,
            )
        except OperatorReviewNoteError as exc:
            return _operator_review_case_problem_response(request, exc)

    @app.get("/admin/v1/operator-review/cases/{case_id}", response_model=None)
    def get_operator_review_case(
        case_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_ag_operator_review_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        try:
            return service.get_case(case_id)
        except OperatorReviewNoteError as exc:
            return _operator_review_case_problem_response(request, exc)

    @app.post(
        "/admin/v1/operator-review/cases/{case_id}/actions",
        response_model=None,
    )
    def apply_operator_review_case_action_route(
        case_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        payload: dict[str, Any] = Body(...),
    ):
        auth_problem = _authorize_ag_operator_review_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        try:
            response = service.apply_action(
                case_id,
                payload,
                request_id=request_id_from_headers(request),
                trace_id=trace_id_from_headers(request),
                idempotency_key=idempotency_key,
            )
        except OperatorReviewNoteError as exc:
            return _operator_review_case_problem_response(request, exc)

        if response["idempotency_status"] == "NEW":
            emit_operator_review_case_action_event(
                audit_emitter,
                response["action"],
                response["case"],
            )
        return JSONResponse(
            status_code=201 if response["idempotency_status"] == "NEW" else 200,
            content=response,
        )


def emit_operator_review_case_event(
    audit_emitter: OperationalEventEmitter,
    record: dict[str, Any],
) -> OperationalEventEmitResult:
    operator = record.get("operator_ref")
    operator_ref_value = operator if isinstance(operator, dict) else {}
    assignment = record.get("assignment_ref")
    assignment_ref_value = assignment if isinstance(assignment, dict) else {}
    return audit_emitter.safe_emit(
        event_type=OPERATOR_REVIEW_CASE_RECORDED_EVENT_TYPE,
        severity="INFO",
        message="AG operator review case recorded.",
        trace_id=record.get("trace_id"),
        request_id=record.get("request_id"),
        subject_ref={
            "type": "operator_review_case",
            "id": str(record["case_id"]),
        },
        details={
            "case_id": record.get("case_id"),
            "target_service": record.get("target_service"),
            "target_kind": record.get("target_kind"),
            "target_id": record.get("target_id"),
            "case_status": record.get("case_status"),
            "case_priority": record.get("case_priority"),
            "operator_type": operator_ref_value.get("operator_type"),
            "operator_id": operator_ref_value.get("operator_id"),
            "assignee_id": assignment_ref_value.get("assignee_id"),
            "reason_count": len(record.get("reason_codes") or []),
            "resolution_hash": record.get("resolution_hash"),
        },
    )


def emit_operator_review_case_action_event(
    audit_emitter: OperationalEventEmitter,
    action: dict[str, Any],
    record: dict[str, Any],
) -> OperationalEventEmitResult:
    operator = action.get("operator_ref")
    operator_ref_value = operator if isinstance(operator, dict) else {}
    assignment = action.get("assignment_ref")
    assignment_ref_value = assignment if isinstance(assignment, dict) else {}
    return audit_emitter.safe_emit(
        event_type=OPERATOR_REVIEW_CASE_ACTION_RECORDED_EVENT_TYPE,
        severity="INFO",
        message="AG operator review case action recorded.",
        trace_id=action.get("trace_id"),
        request_id=action.get("request_id"),
        subject_ref={
            "type": "operator_review_case_action",
            "id": str(action["action_id"]),
        },
        details={
            "case_id": action.get("case_id"),
            "action_id": action.get("action_id"),
            "action_type": action.get("action_type"),
            "from_status": action.get("from_status"),
            "to_status": action.get("to_status"),
            "case_status": record.get("case_status"),
            "target_service": action.get("target_service"),
            "target_kind": action.get("target_kind"),
            "target_id": action.get("target_id"),
            "operator_type": operator_ref_value.get("operator_type"),
            "operator_id": operator_ref_value.get("operator_id"),
            "assignee_id": assignment_ref_value.get("assignee_id"),
            "reason_count": len(action.get("reason_codes") or []),
            "action_comment_hash": action.get("action_comment_hash"),
            "resolution_hash": action.get("resolution_hash"),
        },
    )


def build_operator_review_case_record(
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
    source_ref = operator_review_case_source_ref(payload.get("source_ref"))
    assignment_ref = operator_review_case_assignment_ref(payload.get("assignment_ref"))
    case_status = optional_choice(
        payload.get("case_status"),
        key="case_status",
        choices=ALLOWED_CASE_STATUSES,
        default="OPEN",
    )
    case_priority = optional_choice(
        payload.get("case_priority"),
        key="case_priority",
        choices=ALLOWED_CASE_PRIORITIES,
        default="MEDIUM",
    )
    reason_codes = reason_code_list(payload.get("reason_codes"))
    resolution_text = optional_text(payload.get("resolution_comment"))
    now = created_at or _utc_now()
    normalized_idempotency_key = optional_text(idempotency_key)
    case_id = optional_text(payload.get("case_id")) or str(
        uuid5(
            NAMESPACE_URL,
            _operator_review_case_identity_seed(
                target=target,
                source_ref=source_ref,
                operator=operator,
                request_id=request_id,
                idempotency_key=normalized_idempotency_key,
            ),
        )
    )
    closed_at = optional_text(payload.get("closed_at"))
    if case_status in {"RESOLVED", "DISMISSED"} and closed_at is None:
        closed_at = now
    if case_status not in {"RESOLVED", "DISMISSED"}:
        closed_at = None
    return {
        "case_schema_version": OPERATOR_REVIEW_CASE_SCHEMA_VERSION,
        "case_id": case_id,
        "target_service": target["target_service"],
        "target_kind": target["target_kind"],
        "target_id": target["target_id"],
        "trace_id": optional_text(trace_id),
        "request_id": required_text({"request_id": request_id}, "request_id"),
        "operator_ref": operator,
        "case_status": case_status,
        "case_priority": case_priority,
        "source_ref": source_ref,
        "assignment_ref": assignment_ref,
        "reason_codes": reason_codes,
        "resolution_hash": sha256_text(resolution_text) if resolution_text else None,
        "resolution_preview": operator_note_preview(resolution_text),
        "metadata": operator_review_case_metadata(
            payload.get("metadata"),
            idempotency_key_hash=(
                sha256_text(normalized_idempotency_key)
                if normalized_idempotency_key is not None
                else None
            ),
        ),
        "created_at": now,
        "updated_at": now,
        "closed_at": closed_at,
    }


def build_operator_review_case_list_response(
    records: list[dict[str, Any]],
    *,
    request_id: str,
    trace_id: str | None,
) -> dict[str, Any]:
    items = sorted(
        records,
        key=lambda record: (
            str(record.get("updated_at") or ""),
            str(record.get("case_id") or ""),
        ),
        reverse=True,
    )
    return {
        "case_list_schema_version": OPERATOR_REVIEW_CASE_LIST_SCHEMA_VERSION,
        "trace_id": optional_text(trace_id),
        "request_id": required_text({"request_id": request_id}, "request_id"),
        "items": items,
        "summary": {
            "count": len(items),
            "by_status": _count_by(items, "case_status"),
            "by_priority": _count_by(items, "case_priority"),
            "open_count": sum(
                1
                for item in items
                if item.get("case_status")
                in {"OPEN", "ACKNOWLEDGED", "ASSIGNED", "REOPENED"}
            ),
            "closed_count": sum(
                1 for item in items if item.get("case_status") in {"RESOLVED", "DISMISSED"}
            ),
            "latest_updated_at": items[0]["updated_at"] if items else None,
        },
    }


def build_operator_review_case_mutation_response(
    record: dict[str, Any],
    *,
    idempotency_status: str,
    request_id: str,
    trace_id: str | None,
) -> dict[str, Any]:
    normalized_status = optional_choice(
        idempotency_status,
        key="idempotency_status",
        choices=("NEW", "REPLAYED", "CONFLICT"),
        default="NEW",
    )
    return {
        "case_mutation_schema_version": OPERATOR_REVIEW_CASE_MUTATION_SCHEMA_VERSION,
        "idempotency_status": normalized_status,
        "trace_id": optional_text(trace_id),
        "request_id": required_text({"request_id": request_id}, "request_id"),
        "case": record,
        "summary": {
            "case_id": record["case_id"],
            "target_service": record["target_service"],
            "target_kind": record["target_kind"],
            "target_id": record["target_id"],
            "case_status": record["case_status"],
            "case_priority": record["case_priority"],
        },
    }


def build_operator_review_case_action_mutation_response(
    record: dict[str, Any],
    action: dict[str, Any],
    *,
    idempotency_status: str,
    request_id: str,
    trace_id: str | None,
) -> dict[str, Any]:
    normalized_status = optional_choice(
        idempotency_status,
        key="idempotency_status",
        choices=("NEW", "REPLAYED", "CONFLICT"),
        default="NEW",
    )
    return {
        "case_action_mutation_schema_version": (
            OPERATOR_REVIEW_CASE_ACTION_MUTATION_SCHEMA_VERSION
        ),
        "idempotency_status": normalized_status,
        "trace_id": optional_text(trace_id),
        "request_id": required_text({"request_id": request_id}, "request_id"),
        "case": record,
        "action": action,
        "summary": {
            "case_id": record["case_id"],
            "action_id": action["action_id"],
            "action_type": action["action_type"],
            "from_status": action["from_status"],
            "to_status": action["to_status"],
            "case_status": record["case_status"],
            "case_priority": record["case_priority"],
        },
    }


def apply_operator_review_case_action(
    record: dict[str, Any],
    payload: dict[str, Any],
    *,
    request_id: str,
    trace_id: str | None,
    idempotency_key: str,
    acted_at: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    action = build_operator_review_case_action_record(
        record,
        payload,
        request_id=request_id,
        trace_id=trace_id,
        idempotency_key=idempotency_key,
        acted_at=acted_at,
    )
    updated = dict(record)
    updated["case_status"] = action["to_status"]
    updated["updated_at"] = action["acted_at"]
    if action["action_type"] == "ASSIGN":
        updated["assignment_ref"] = dict(action["assignment_ref"])
    if action["action_type"] in {"RESOLVE", "DISMISS"}:
        updated["closed_at"] = action["acted_at"]
        updated["resolution_hash"] = action["resolution_hash"]
        updated["resolution_preview"] = action["resolution_preview"]
    if action["action_type"] == "REOPEN":
        updated["closed_at"] = None
    existing_metadata = (
        updated.get("metadata") if isinstance(updated.get("metadata"), dict) else {}
    )
    updated["metadata"] = operator_review_case_metadata(
        existing_metadata,
        idempotency_key_hash=existing_metadata.get("idempotency_key_hash"),
    )
    updated["metadata"].update(
        {
            "last_action_id": action["action_id"],
            "last_action_type": action["action_type"],
            "last_action_at": action["acted_at"],
        }
    )
    return updated, action


def build_operator_review_case_action_record(
    record: dict[str, Any],
    payload: dict[str, Any],
    *,
    request_id: str,
    trace_id: str | None,
    idempotency_key: str,
    acted_at: str | None = None,
) -> dict[str, Any]:
    assert_operator_review_note_payload_redaction_safe(payload)
    action_type = required_case_action_type(payload.get("action_type"))
    if action_type == "CREATE_CASE":
        raise OperatorReviewNoteError(
            status_code=422,
            error_code="ag.operator_review_case_action_create_case_unsupported",
            detail="CREATE_CASE is represented by the case create route.",
        )
    from_status = str(record.get("case_status") or "")
    to_status = _target_status_for_case_action(action_type, from_status)
    operator = operator_ref(payload.get("operator_ref"))
    assignment = _assignment_ref_for_case_action(action_type, payload, record)
    reason_codes = reason_code_list(payload.get("reason_codes"))
    action_comment = optional_text(payload.get("action_comment"))
    resolution_comment = optional_text(payload.get("resolution_comment"))
    effective_resolution = resolution_comment or action_comment
    if action_type in {"RESOLVE", "DISMISS"} and effective_resolution is None:
        raise OperatorReviewNoteError(
            status_code=422,
            error_code="ag.operator_review_case_resolution_comment_required",
            detail="resolution_comment or action_comment is required.",
        )
    now = acted_at or _utc_now()
    action_id = operator_review_case_action_id(record["case_id"], idempotency_key)
    return {
        "case_action_schema_version": OPERATOR_REVIEW_CASE_ACTION_SCHEMA_VERSION,
        "action_id": action_id,
        "case_id": record["case_id"],
        "action_type": action_type,
        "from_status": from_status,
        "to_status": to_status,
        "target_service": record["target_service"],
        "target_kind": record["target_kind"],
        "target_id": record["target_id"],
        "trace_id": optional_text(trace_id),
        "request_id": required_text({"request_id": request_id}, "request_id"),
        "operator_ref": operator,
        "assignment_ref": assignment,
        "reason_codes": reason_codes,
        "action_comment_hash": sha256_text(action_comment) if action_comment else None,
        "action_comment_preview": operator_note_preview(action_comment),
        "resolution_hash": (
            sha256_text(effective_resolution) if effective_resolution else None
        ),
        "resolution_preview": operator_note_preview(effective_resolution),
        "metadata": operator_review_case_action_metadata(
            payload.get("metadata"),
            idempotency_key_hash=sha256_text(idempotency_key),
        ),
        "acted_at": now,
    }


def operator_review_case_action_request_signature(
    case_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    assert_operator_review_note_payload_redaction_safe(payload)
    action_type = required_case_action_type(payload.get("action_type"))
    operator = operator_ref(payload.get("operator_ref"))
    assignment = operator_review_case_assignment_ref(payload.get("assignment_ref"))
    action_comment = optional_text(payload.get("action_comment"))
    resolution_comment = optional_text(payload.get("resolution_comment"))
    return {
        "case_id": required_case_id(case_id),
        "action_type": action_type,
        "operator_ref": operator,
        "assignment_ref": assignment,
        "reason_codes": reason_code_list(payload.get("reason_codes")),
        "action_comment_hash": sha256_text(action_comment) if action_comment else None,
        "resolution_hash": (
            sha256_text(resolution_comment) if resolution_comment else None
        ),
        "metadata": operator_review_case_action_metadata(payload.get("metadata")),
    }


def operator_review_case_idempotency_signature(record: dict[str, Any]) -> dict[str, Any]:
    operator = record.get("operator_ref")
    operator_ref_value = operator if isinstance(operator, dict) else {}
    return {
        "target_service": record.get("target_service"),
        "target_kind": record.get("target_kind"),
        "target_id": record.get("target_id"),
        "operator_type": operator_ref_value.get("operator_type"),
        "operator_id": operator_ref_value.get("operator_id"),
        "case_status": record.get("case_status"),
        "case_priority": record.get("case_priority"),
        "source_ref": dict(record.get("source_ref") or {}),
        "assignment_ref": dict(record.get("assignment_ref") or {}),
        "reason_codes": list(record.get("reason_codes") or []),
        "resolution_hash": record.get("resolution_hash"),
        "metadata": dict(record.get("metadata") or {}),
    }


def operator_review_case_source_ref(value: Any) -> dict[str, str | None]:
    if value is None:
        return {
            "source_type": "manual",
            "source_id": None,
            "source_service": None,
            "workbench_path": "/admin/v1/operator-review/workbench",
        }
    if not isinstance(value, dict):
        raise OperatorReviewNoteError(
            status_code=422,
            error_code="ag.operator_review_case_source_ref_invalid",
            detail="source_ref must be an object when supplied.",
        )
    source_service = optional_choice(
        value.get("source_service"),
        key="source_service",
        choices=ALLOWED_TARGET_SERVICES,
        default="",
    )
    return {
        "source_type": optional_choice(
            value.get("source_type"),
            key="source_type",
            choices=(
                "manual",
                "operator_review_workbench",
                "operator_review_issue_candidate",
                "operator_review_note",
                "redacted_evidence_export",
            ),
            default="manual",
        ),
        "source_id": optional_text(value.get("source_id")),
        "source_service": source_service or None,
        "workbench_path": optional_text(value.get("workbench_path"))
        or "/admin/v1/operator-review/workbench",
    }


def operator_review_case_assignment_ref(value: Any) -> dict[str, str | None]:
    if value is None:
        return {"assignee_type": None, "assignee_id": None, "tenant_id": None}
    if not isinstance(value, dict):
        raise OperatorReviewNoteError(
            status_code=422,
            error_code="ag.operator_review_case_assignment_ref_invalid",
            detail="assignment_ref must be an object when supplied.",
        )
    assignee_type = optional_choice(
        value.get("assignee_type"),
        key="assignee_type",
        choices=ALLOWED_OPERATOR_TYPES,
        default="",
    )
    assignee_id = optional_text(value.get("assignee_id"))
    if bool(assignee_type) != bool(assignee_id):
        raise OperatorReviewNoteError(
            status_code=422,
            error_code="ag.operator_review_case_assignment_ref_incomplete",
            detail="assignment_ref requires both assignee_type and assignee_id.",
        )
    return {
        "assignee_type": assignee_type or None,
        "assignee_id": assignee_id,
        "tenant_id": optional_text(value.get("tenant_id")),
    }


def operator_review_case_metadata(
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
            error_code="ag.operator_review_case_metadata_invalid",
            detail="metadata must be an object when supplied.",
        )
    metadata.update(
        {
            "raw_operator_note_stored": False,
            "raw_evidence_body_stored": False,
            "raw_prompt_stored": False,
            "raw_generation_output_stored": False,
            "raw_source_text_stored": False,
            "storage_paths_included": False,
            "case_comment_storage": "hash_and_short_preview_only",
            "action_history_storage": "operational_events_first",
            "notification_delivery_deferred": True,
            "external_incident_sync_deferred": True,
        }
    )
    if idempotency_key_hash is not None:
        metadata["idempotency_key_hash"] = idempotency_key_hash
        metadata["idempotency_key_stored"] = False
    return json.loads(json.dumps(metadata))


def operator_review_case_action_metadata(
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
            error_code="ag.operator_review_case_action_metadata_invalid",
            detail="metadata must be an object when supplied.",
        )
    metadata.update(
        {
            "raw_action_comment_stored": False,
            "raw_resolution_comment_stored": False,
            "raw_prompt_stored": False,
            "raw_generation_output_stored": False,
            "raw_source_text_stored": False,
            "storage_paths_included": False,
            "action_comment_storage": "hash_and_short_preview_only",
            "action_history_storage": "operational_events_first",
            "notification_delivery_deferred": True,
            "external_incident_sync_deferred": True,
        }
    )
    if idempotency_key_hash is not None:
        metadata["idempotency_key_hash"] = idempotency_key_hash
        metadata["idempotency_key_stored"] = False
    return json.loads(json.dumps(metadata))


def required_case_idempotency_key(value: Any) -> str:
    normalized = optional_text(value)
    if normalized is None:
        raise OperatorReviewNoteError(
            status_code=422,
            error_code="ag.operator_review_case_idempotency_key_required",
            detail="Idempotency-Key is required for operator review case mutations.",
        )
    return normalized


def required_case_action_idempotency_key(value: Any) -> str:
    normalized = optional_text(value)
    if normalized is None:
        raise OperatorReviewNoteError(
            status_code=422,
            error_code="ag.operator_review_case_action_idempotency_key_required",
            detail="Idempotency-Key is required for operator review case actions.",
        )
    return normalized


def required_case_id(value: Any) -> str:
    normalized = optional_text(value)
    if normalized is None:
        raise OperatorReviewNoteError(
            status_code=422,
            error_code="ag.operator_review_case_case_id_required",
            detail="case_id is required.",
        )
    return normalized


def required_case_action_type(value: Any) -> str:
    normalized = optional_text(value)
    if normalized is None:
        raise OperatorReviewNoteError(
            status_code=422,
            error_code="ag.operator_review_case_action_type_required",
            detail="action_type is required.",
        )
    if normalized not in ALLOWED_CASE_ACTIONS:
        raise OperatorReviewNoteError(
            status_code=422,
            error_code="ag.operator_review_case_action_type_unsupported",
            detail=f"unsupported action_type: {normalized}",
        )
    return normalized


def operator_review_case_action_id(case_id: str, idempotency_key: str) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            "ag-operator-review-case-action:"
            f"{required_case_id(case_id)}:{sha256_text(idempotency_key)}",
        )
    )


def _target_status_for_case_action(action_type: str, from_status: str) -> str:
    allowed_from = CASE_ACTION_ALLOWED_FROM.get(action_type)
    if allowed_from is None or action_type not in CASE_ACTION_TARGET_STATUSES:
        raise OperatorReviewNoteError(
            status_code=422,
            error_code="ag.operator_review_case_action_type_unsupported",
            detail=f"unsupported action_type: {action_type}",
        )
    if from_status not in allowed_from:
        raise OperatorReviewNoteError(
            status_code=409,
            error_code="ag.operator_review_case_action_transition_invalid",
            detail=f"{action_type} cannot transition case status {from_status}.",
        )
    return CASE_ACTION_TARGET_STATUSES[action_type]


def _assignment_ref_for_case_action(
    action_type: str,
    payload: dict[str, Any],
    record: dict[str, Any],
) -> dict[str, str | None]:
    supplied = operator_review_case_assignment_ref(payload.get("assignment_ref"))
    if action_type == "ASSIGN":
        if supplied.get("assignee_id") is None:
            raise OperatorReviewNoteError(
                status_code=422,
                error_code="ag.operator_review_case_assignment_required",
                detail="ASSIGN requires assignment_ref with assignee_type and assignee_id.",
            )
        return supplied
    existing = record.get("assignment_ref")
    return dict(existing) if isinstance(existing, dict) else supplied


def _latest_case_action_summary(record: dict[str, Any]) -> dict[str, Any] | None:
    metadata = record.get("metadata")
    if not isinstance(metadata, dict):
        return None
    action = metadata.get("last_action")
    if not isinstance(action, dict):
        return None
    if not isinstance(action.get("record"), dict):
        return None
    if not isinstance(action.get("request_signature"), dict):
        return None
    return action


def _operator_review_case_identity_seed(
    *,
    target: dict[str, str],
    source_ref: dict[str, str | None],
    operator: dict[str, str | None],
    request_id: str,
    idempotency_key: str | None,
) -> str:
    if idempotency_key is not None:
        return (
            "ag-operator-review-case:idempotent:"
            f"{target['target_service']}:{target['target_kind']}:{target['target_id']}:"
            f"{operator['operator_type']}:{operator['operator_id']}:"
            f"{sha256_text(idempotency_key)}"
        )
    return (
        "ag-operator-review-case:content:"
        f"{target['target_service']}:{target['target_kind']}:{target['target_id']}:"
        f"{source_ref.get('source_type')}:{source_ref.get('source_id')}:{request_id}"
    )


def _case_matches_filter(
    record: dict[str, Any],
    *,
    target_service: str | None,
    target_kind: str | None,
    target_id: str | None,
    trace_id: str | None,
    case_status: str | None,
    case_priority: str | None,
    operator_type: str | None,
    operator_id: str | None,
    assignee_id: str | None,
    updated_from: str | None = None,
    updated_to: str | None = None,
) -> bool:
    operator = record.get("operator_ref")
    operator_ref_value = operator if isinstance(operator, dict) else {}
    assignment = record.get("assignment_ref")
    assignment_ref_value = assignment if isinstance(assignment, dict) else {}
    updated_at = str(record.get("updated_at") or "")
    return all(
        (
            target_service is None or record.get("target_service") == target_service,
            target_kind is None or record.get("target_kind") == target_kind,
            target_id is None or record.get("target_id") == target_id,
            trace_id is None or record.get("trace_id") == trace_id,
            case_status is None or record.get("case_status") == case_status,
            case_priority is None or record.get("case_priority") == case_priority,
            operator_type is None
            or operator_ref_value.get("operator_type") == operator_type,
            operator_id is None or operator_ref_value.get("operator_id") == operator_id,
            assignee_id is None
            or assignment_ref_value.get("assignee_id") == assignee_id,
            updated_from is None or updated_at >= updated_from,
            updated_to is None or updated_at <= updated_to,
        )
    )


def _operator_review_case_filter_clause(
    *,
    target_service: str | None,
    target_kind: str | None,
    target_id: str | None,
    trace_id: str | None,
    case_status: str | None,
    case_priority: str | None,
    operator_type: str | None,
    operator_id: str | None,
    assignee_id: str | None,
    updated_from: str | None = None,
    updated_to: str | None = None,
) -> tuple[str, dict[str, Any]]:
    clauses = ["1 = 1"]
    params: dict[str, Any] = {}
    for name, value in (
        ("target_service", target_service),
        ("target_kind", target_kind),
        ("target_id", target_id),
        ("trace_id", trace_id),
        ("case_status", case_status),
        ("case_priority", case_priority),
        ("operator_type", operator_type),
        ("operator_id", operator_id),
        ("assignee_id", assignee_id),
    ):
        if value is not None:
            clauses.append(f"{name} = :{name}")
            params[name] = value
    if updated_from is not None:
        clauses.append("updated_at >= :updated_from")
        params["updated_from"] = updated_from
    if updated_to is not None:
        clauses.append("updated_at <= :updated_to")
        params["updated_to"] = updated_to
    return " AND ".join(clauses), params


def _operator_review_case_upsert_sql(dialect_name: str) -> str:
    operator_ref_expr = _json_param_expr("operator_ref", dialect_name)
    source_ref_expr = _json_param_expr("source_ref", dialect_name)
    assignment_ref_expr = _json_param_expr("assignment_ref", dialect_name)
    reason_codes_expr = _json_param_expr("reason_codes", dialect_name)
    metadata_expr = _json_param_expr("metadata", dialect_name)
    return f"""
        INSERT INTO ag_op_cases (
            case_id,
            case_schema_version,
            target_service,
            target_kind,
            target_id,
            trace_id,
            request_id,
            operator_type,
            operator_id,
            tenant_id,
            operator_ref,
            case_status,
            case_priority,
            source_ref,
            assignment_ref,
            assignee_id,
            reason_codes,
            resolution_hash,
            resolution_preview,
            metadata,
            created_at,
            updated_at,
            closed_at
        )
        VALUES (
            :case_id,
            :case_schema_version,
            :target_service,
            :target_kind,
            :target_id,
            :trace_id,
            :request_id,
            :operator_type,
            :operator_id,
            :tenant_id,
            {operator_ref_expr},
            :case_status,
            :case_priority,
            {source_ref_expr},
            {assignment_ref_expr},
            :assignee_id,
            {reason_codes_expr},
            :resolution_hash,
            :resolution_preview,
            {metadata_expr},
            :created_at,
            :updated_at,
            :closed_at
        )
        ON CONFLICT (case_id) DO UPDATE SET
            case_schema_version = excluded.case_schema_version,
            target_service = excluded.target_service,
            target_kind = excluded.target_kind,
            target_id = excluded.target_id,
            trace_id = excluded.trace_id,
            request_id = excluded.request_id,
            operator_type = excluded.operator_type,
            operator_id = excluded.operator_id,
            tenant_id = excluded.tenant_id,
            operator_ref = excluded.operator_ref,
            case_status = excluded.case_status,
            case_priority = excluded.case_priority,
            source_ref = excluded.source_ref,
            assignment_ref = excluded.assignment_ref,
            assignee_id = excluded.assignee_id,
            reason_codes = excluded.reason_codes,
            resolution_hash = excluded.resolution_hash,
            resolution_preview = excluded.resolution_preview,
            metadata = excluded.metadata,
            updated_at = excluded.updated_at,
            closed_at = excluded.closed_at
    """


def _operator_review_case_select_sql(where_clause: str) -> str:
    return f"""
        SELECT
            case_schema_version,
            case_id,
            target_service,
            target_kind,
            target_id,
            trace_id,
            request_id,
            operator_ref,
            case_status,
            case_priority,
            source_ref,
            assignment_ref,
            reason_codes,
            resolution_hash,
            resolution_preview,
            metadata,
            created_at,
            updated_at,
            closed_at
        FROM ag_op_cases
        WHERE {where_clause}
    """


def _operator_review_case_record_params(record: dict[str, Any]) -> dict[str, Any]:
    operator = record["operator_ref"]
    assignment = record["assignment_ref"]
    return {
        **record,
        "operator_type": operator["operator_type"],
        "operator_id": operator["operator_id"],
        "tenant_id": operator.get("tenant_id"),
        "operator_ref": json.dumps(record["operator_ref"]),
        "source_ref": json.dumps(record["source_ref"]),
        "assignment_ref": json.dumps(record["assignment_ref"]),
        "assignee_id": assignment.get("assignee_id"),
        "reason_codes": json.dumps(record["reason_codes"]),
        "metadata": json.dumps(record["metadata"]),
    }


def _operator_review_case_record_from_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    return {
        "case_schema_version": data["case_schema_version"],
        "case_id": data["case_id"],
        "target_service": data["target_service"],
        "target_kind": data["target_kind"],
        "target_id": data["target_id"],
        "trace_id": data["trace_id"],
        "request_id": data["request_id"],
        "operator_ref": _json_value(data["operator_ref"], {}),
        "case_status": data["case_status"],
        "case_priority": data["case_priority"],
        "source_ref": _json_value(data["source_ref"], {}),
        "assignment_ref": _json_value(data["assignment_ref"], {}),
        "reason_codes": _json_value(data["reason_codes"], []),
        "resolution_hash": data["resolution_hash"],
        "resolution_preview": data["resolution_preview"],
        "metadata": _json_value(data["metadata"], {}),
        "created_at": _datetime_value(data["created_at"]),
        "updated_at": _datetime_value(data["updated_at"]),
        "closed_at": _datetime_value(data["closed_at"]) if data["closed_at"] else None,
    }


def _count_by(records: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        value = str(record.get(key) or "UNKNOWN")
        counts[value] = counts.get(value, 0) + 1
    return counts


def _case_store_unavailable_error() -> OperatorReviewNoteError:
    return OperatorReviewNoteError(
        status_code=503,
        error_code="ag.operator_review_case_store_unavailable",
        detail="Operator review case store is unavailable.",
    )


def _operator_review_case_problem_response(
    request: Request,
    exc: OperatorReviewNoteError,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Operator review case request rejected",
        detail=exc.detail,
        type_uri="https://nex-platform.local/problems/operator-review-case-rejected",
    )
