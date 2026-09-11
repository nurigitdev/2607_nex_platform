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
    OperationalEventError,
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
    default_operator_evidence_export_store,
    default_operator_review_note_store,
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
OPERATOR_REVIEW_CASE_QUEUE_SCHEMA_VERSION = "ag_operator_review_case_queue.v1"
OPERATOR_REVIEW_CASE_WORKBENCH_DETAIL_SCHEMA_VERSION = (
    "ag_operator_review_case_workbench_detail.v1"
)
OPERATOR_REVIEW_CASE_TIMELINE_SCHEMA_VERSION = (
    "ag_operator_review_case_timeline.v1"
)
OPERATOR_REVIEW_CASE_EVIDENCE_LINKS_SCHEMA_VERSION = (
    "ag_operator_review_case_evidence_links.v1"
)
OPERATOR_REVIEW_CASE_ACTION_ADMISSION_SCHEMA_VERSION = (
    "ag_operator_review_case_action_admission.v1"
)
OPERATOR_REVIEW_CASE_MUTATION_SCHEMA_VERSION = "ag_operator_review_case_mutation.v1"
OPERATOR_REVIEW_CASE_ACTION_SCHEMA_VERSION = "ag_operator_review_case_action.v1"
OPERATOR_REVIEW_CASE_ACTION_MUTATION_SCHEMA_VERSION = (
    "ag_operator_review_case_action_mutation.v1"
)
OPERATOR_REVIEW_CASE_ROLLUP_SCHEMA_VERSION = "ag_operator_review_case_rollup.v1"
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
ALLOWED_CASE_QUEUE_ATTENTION_STATUSES = ("BLOCKED", "ATTENTION", "OPEN", "OK")
ALLOWED_CASE_QUEUE_SORT_FIELDS = (
    "attention",
    "updated_at",
    "priority",
    "status",
    "case_id",
)
ALLOWED_CASE_QUEUE_SORT_DIRECTIONS = ("asc", "desc")
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

    def get_case_workbench_detail(
        self,
        case_id: str,
        *,
        note_store: Any | None = None,
        export_store: Any | None = None,
        request_id: str,
        trace_id: str | None,
        evidence_limit: int | None = 5,
    ) -> dict[str, Any]:
        record = self.get_case(case_id)
        evidence_sources = _case_evidence_source_records(
            record,
            note_store=note_store,
            export_store=export_store,
            limit=evidence_limit,
        )
        return build_operator_review_case_workbench_detail_projection(
            record,
            operator_note_records=evidence_sources["operator_note_records"],
            evidence_export_records=evidence_sources["evidence_export_records"],
            request_id=request_id,
            trace_id=trace_id,
            evidence_limit=evidence_sources["limit"],
            evidence_source_status=evidence_sources["source_status"],
        )

    def get_case_evidence_links(
        self,
        case_id: str,
        *,
        note_store: Any | None = None,
        export_store: Any | None = None,
        request_id: str,
        trace_id: str | None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        record = self.get_case(case_id)
        evidence_sources = _case_evidence_source_records(
            record,
            note_store=note_store,
            export_store=export_store,
            limit=limit,
        )
        return build_operator_review_case_evidence_links_projection(
            record,
            operator_note_records=evidence_sources["operator_note_records"],
            evidence_export_records=evidence_sources["evidence_export_records"],
            request_id=request_id,
            trace_id=trace_id,
            limit=evidence_sources["limit"],
            source_status=evidence_sources["source_status"],
        )

    def get_case_action_admission(
        self,
        case_id: str,
        *,
        request_id: str,
        trace_id: str | None,
        action_type: str | None = None,
    ) -> dict[str, Any]:
        record = self.get_case(case_id)
        return build_operator_review_case_action_admission_projection(
            record,
            request_id=request_id,
            trace_id=trace_id,
            action_type=action_type,
        )

    def rollup_cases(
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
        case_list = self.list_cases(
            request_id=request_id,
            trace_id=trace_id,
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
        return build_operator_review_case_rollup_metrics(case_list)

    def queue_cases(
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
        latest_action_type: str | None = None,
        attention_status: str | None = None,
        search: str | None = None,
        sort_by: str | None = None,
        sort_direction: str | None = None,
        updated_from: str | None = None,
        updated_to: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        case_list = self.list_cases(
            request_id=request_id,
            trace_id=trace_id,
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
        return build_operator_review_case_queue_projection(
            case_list,
            latest_action_type=latest_action_type,
            attention_status=attention_status,
            search=search,
            sort_by=sort_by,
            sort_direction=sort_direction,
        )

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
    note_store: Any | None = None,
    export_store: Any | None = None,
    audit_event_store: OperationalEventStore | None = None,
) -> None:
    service = OperatorReviewCaseService(store or default_operator_review_case_store(app))
    selected_note_store = note_store or default_operator_review_note_store(app)
    selected_export_store = export_store or default_operator_evidence_export_store(app)
    selected_audit_event_store = (
        audit_event_store or DEFAULT_OPERATOR_REVIEW_CASE_AUDIT_EVENT_STORE
    )
    audit_emitter = OperationalEventEmitter(
        service_id="nex-ag",
        store=selected_audit_event_store,
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

    @app.get("/admin/v1/operator-review/cases/rollups", response_model=None)
    def get_operator_review_case_rollups(
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
            return service.rollup_cases(
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

    @app.get("/admin/v1/operator-review/cases/queue", response_model=None)
    def get_operator_review_case_queue(
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
        latest_action_type: str | None = None,
        attention_status: str | None = None,
        search: str | None = Query(default=None, alias="q"),
        sort_by: str | None = None,
        sort_direction: str | None = None,
        updated_from: str | None = None,
        updated_to: str | None = None,
        limit: int | None = None,
    ):
        auth_problem = _authorize_ag_operator_review_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        try:
            return service.queue_cases(
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
                latest_action_type=latest_action_type,
                attention_status=attention_status,
                search=search,
                sort_by=sort_by,
                sort_direction=sort_direction,
                updated_from=updated_from,
                updated_to=updated_to,
                limit=limit,
            )
        except OperatorReviewNoteError as exc:
            return _operator_review_case_problem_response(request, exc)

    @app.get(
        "/admin/v1/operator-review/cases/{case_id}/workbench-detail",
        response_model=None,
    )
    def get_operator_review_case_workbench_detail(
        case_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_ag_operator_review_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        try:
            return service.get_case_workbench_detail(
                case_id,
                note_store=selected_note_store,
                export_store=selected_export_store,
                request_id=request_id_from_headers(request),
                trace_id=trace_id_from_headers(request),
            )
        except OperatorReviewNoteError as exc:
            return _operator_review_case_problem_response(request, exc)

    @app.get(
        "/admin/v1/operator-review/cases/{case_id}/evidence-links",
        response_model=None,
    )
    def get_operator_review_case_evidence_links(
        case_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
        limit: int | None = None,
    ):
        auth_problem = _authorize_ag_operator_review_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        try:
            return service.get_case_evidence_links(
                case_id,
                note_store=selected_note_store,
                export_store=selected_export_store,
                request_id=request_id_from_headers(request),
                trace_id=trace_id_from_headers(request),
                limit=limit,
            )
        except OperatorReviewNoteError as exc:
            return _operator_review_case_problem_response(request, exc)

    @app.get(
        "/admin/v1/operator-review/cases/{case_id}/action-admission",
        response_model=None,
    )
    def get_operator_review_case_action_admission(
        case_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
        action_type: str | None = None,
    ):
        auth_problem = _authorize_ag_operator_review_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        try:
            return service.get_case_action_admission(
                case_id,
                request_id=request_id_from_headers(request),
                trace_id=trace_id_from_headers(request),
                action_type=action_type,
            )
        except OperatorReviewNoteError as exc:
            return _operator_review_case_problem_response(request, exc)

    @app.get(
        "/admin/v1/operator-review/cases/{case_id}/timeline",
        response_model=None,
    )
    def get_operator_review_case_timeline(
        case_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
        limit: int | None = None,
    ):
        auth_problem = _authorize_ag_operator_review_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        try:
            record = service.get_case(case_id)
            return build_operator_review_case_timeline_projection(
                record,
                event_store=selected_audit_event_store,
                request_id=request_id_from_headers(request),
                trace_id=trace_id_from_headers(request),
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


def build_operator_review_case_queue_projection(
    case_list: dict[str, Any],
    *,
    latest_action_type: str | None = None,
    attention_status: str | None = None,
    search: str | None = None,
    sort_by: str | None = None,
    sort_direction: str | None = None,
) -> dict[str, Any]:
    normalized_latest_action_type = optional_choice(
        latest_action_type,
        key="latest_action_type",
        choices=ALLOWED_CASE_ACTIONS,
        default="",
    )
    normalized_attention_status = optional_choice(
        attention_status,
        key="attention_status",
        choices=ALLOWED_CASE_QUEUE_ATTENTION_STATUSES,
        default="",
    )
    normalized_sort_by = optional_choice(
        sort_by,
        key="sort_by",
        choices=ALLOWED_CASE_QUEUE_SORT_FIELDS,
        default="attention",
    )
    normalized_sort_direction = optional_choice(
        sort_direction,
        key="sort_direction",
        choices=ALLOWED_CASE_QUEUE_SORT_DIRECTIONS,
        default="asc",
    )
    normalized_search = optional_text(search)
    cases = list(case_list.get("items") or [])
    items = [_case_queue_item(record) for record in cases]
    items = _filter_case_queue_items(
        items,
        latest_action_type=normalized_latest_action_type or None,
        attention_status=normalized_attention_status or None,
        search=normalized_search,
    )
    items = _sort_case_queue_items(
        items,
        sort_by=normalized_sort_by,
        sort_direction=normalized_sort_direction,
    )
    return {
        "case_queue_schema_version": OPERATOR_REVIEW_CASE_QUEUE_SCHEMA_VERSION,
        "trace_id": case_list.get("trace_id"),
        "request_id": case_list.get("request_id"),
        "filters": {
            "latest_action_type": normalized_latest_action_type or None,
            "attention_status": normalized_attention_status or None,
            "q": normalized_search,
        },
        "sort": {
            "sort_by": normalized_sort_by,
            "sort_direction": normalized_sort_direction,
        },
        "items": items,
        "summary": _case_queue_summary(items),
        "paths": {
            "case_list_path": "/admin/v1/operator-review/cases",
            "case_queue_path": "/admin/v1/operator-review/cases/queue",
            "case_detail_path_template": "/admin/v1/operator-review/cases/{case_id}",
            "case_action_path_template": (
                "/admin/v1/operator-review/cases/{case_id}/actions"
            ),
            "case_rollup_path": "/admin/v1/operator-review/cases/rollups",
        },
        "redaction": {
            "raw_case_comment_included": False,
            "raw_action_comment_included": False,
            "raw_resolution_comment_included": False,
            "raw_prompt_included": False,
            "raw_generation_output_included": False,
            "raw_source_text_included": False,
            "storage_paths_included": False,
            "idempotency_keys_included": False,
            "queue_payload_shape": "safe_refs_hashes_and_bounded_previews_only",
            "action_history_shape": "operational_events_first",
        },
    }


def _case_evidence_source_records(
    record: dict[str, Any],
    *,
    note_store: Any | None,
    export_store: Any | None,
    limit: int | None,
) -> dict[str, Any]:
    normalized_limit = normalize_limit(limit)
    note_records = (
        note_store.list_notes(
            target_service=record.get("target_service"),
            target_kind=record.get("target_kind"),
            target_id=record.get("target_id"),
            limit=normalized_limit,
        )
        if note_store is not None
        else []
    )
    export_records = (
        export_store.list_exports(
            target_service=record.get("target_service"),
            target_kind=record.get("target_kind"),
            target_id=record.get("target_id"),
            limit=normalized_limit,
        )
        if export_store is not None
        else []
    )
    if note_store is not None and export_store is not None:
        source_status = "READY"
    elif note_store is not None or export_store is not None:
        source_status = "PARTIAL"
    else:
        source_status = "NOT_CONFIGURED"
    return {
        "operator_note_records": note_records,
        "evidence_export_records": export_records,
        "limit": normalized_limit,
        "source_status": source_status,
    }


def build_operator_review_case_workbench_detail_projection(
    record: dict[str, Any],
    *,
    operator_note_records: list[dict[str, Any]] | None = None,
    evidence_export_records: list[dict[str, Any]] | None = None,
    request_id: str,
    trace_id: str | None,
    evidence_limit: int | None = 5,
    evidence_source_status: str = "NOT_CONFIGURED",
) -> dict[str, Any]:
    queue_item = _case_queue_item(record)
    action_controls = _case_workbench_action_controls(record)
    evidence_links = build_operator_review_case_evidence_links_projection(
        record,
        operator_note_records=operator_note_records or [],
        evidence_export_records=evidence_export_records or [],
        request_id=request_id,
        trace_id=trace_id,
        limit=evidence_limit,
        source_status=evidence_source_status,
    )
    action_admission = build_operator_review_case_action_admission_projection(
        record,
        request_id=request_id,
        trace_id=trace_id,
    )
    return {
        "case_workbench_detail_schema_version": (
            OPERATOR_REVIEW_CASE_WORKBENCH_DETAIL_SCHEMA_VERSION
        ),
        "trace_id": optional_text(trace_id),
        "request_id": required_text({"request_id": request_id}, "request_id"),
        "case": {
            "case_id": record.get("case_id"),
            "target_ref": dict(queue_item["target_ref"]),
            "case_status": record.get("case_status"),
            "case_priority": record.get("case_priority"),
            "attention_status": queue_item["attention_status"],
            "attention_reason_codes": list(queue_item["attention_reason_codes"]),
            "recommended_actions": list(queue_item["recommended_actions"]),
            "operator_ref": dict(queue_item["operator_ref"]),
            "assignment_ref": dict(queue_item["assignment_ref"]),
            "source_ref": _case_workbench_source_ref(record),
            "reason_count": queue_item["reason_count"],
            "created_at": record.get("created_at"),
            "updated_at": record.get("updated_at"),
            "closed_at": record.get("closed_at"),
        },
        "resolution": {
            "resolution_hash": record.get("resolution_hash"),
            "resolution_preview": record.get("resolution_preview"),
            "raw_resolution_comment_included": False,
        },
        "latest_action": queue_item["latest_action"],
        "action_controls": action_controls,
        "evidence_links": {
            "planned_schema_version": OPERATOR_REVIEW_CASE_EVIDENCE_LINKS_SCHEMA_VERSION,
            "inline_items_included": False,
            "summary": dict(evidence_links["summary"]),
            "links": {
                "case_evidence_links_path": evidence_links["links"][
                    "case_evidence_links_path"
                ],
                "case_timeline_path": evidence_links["links"]["case_timeline_path"],
            },
        },
        "action_admission": {
            "planned_schema_version": OPERATOR_REVIEW_CASE_ACTION_ADMISSION_SCHEMA_VERSION,
            "inline_items_included": False,
            "summary": dict(action_admission["summary"]),
            "links": {
                "case_action_admission_path": action_admission["links"][
                    "case_action_admission_path"
                ],
                "case_action_path": action_admission["links"]["case_action_path"],
            },
        },
        "timeline": {
            "timeline_path": (
                f"/admin/v1/operator-review/cases/{record.get('case_id')}/timeline"
            ),
            "action_history_shape": "operational_events_first",
            "inline_events_included": False,
            "planned_schema_version": "ag_operator_review_case_timeline.v1",
        },
        "links": {
            "case_detail_path": (
                f"/admin/v1/operator-review/cases/{record.get('case_id')}"
            ),
            "case_action_path": (
                f"/admin/v1/operator-review/cases/{record.get('case_id')}/actions"
            ),
            "case_evidence_links_path": (
                f"/admin/v1/operator-review/cases/{record.get('case_id')}"
                "/evidence-links"
            ),
            "case_action_admission_path": (
                f"/admin/v1/operator-review/cases/{record.get('case_id')}"
                "/action-admission"
            ),
            "case_queue_path": "/admin/v1/operator-review/cases/queue",
            "operator_review_workbench_path": "/admin/v1/operator-review/workbench",
        },
        "redaction": {
            "raw_case_comment_included": False,
            "raw_action_comment_included": False,
            "raw_resolution_comment_included": False,
            "raw_prompt_included": False,
            "raw_generation_output_included": False,
            "raw_source_text_included": False,
            "storage_paths_included": False,
            "provider_payloads_included": False,
            "database_urls_included": False,
            "tokens_included": False,
            "idempotency_keys_included": False,
            "metadata_payload_included": False,
            "detail_payload_shape": "safe_refs_hashes_and_bounded_previews_only",
        },
    }


def build_operator_review_case_evidence_links_projection(
    record: dict[str, Any],
    *,
    operator_note_records: list[dict[str, Any]],
    evidence_export_records: list[dict[str, Any]],
    request_id: str,
    trace_id: str | None,
    limit: int | None = None,
    source_status: str = "READY",
) -> dict[str, Any]:
    normalized_limit = normalize_limit(limit)
    note_links = [
        _case_evidence_note_link(note)
        for note in operator_note_records
        if _record_targets_case(record, note)
    ]
    export_links = [
        _case_evidence_export_link(export)
        for export in evidence_export_records
        if _record_targets_case(record, export)
    ]
    items = sorted(
        [*note_links, *export_links],
        key=lambda item: (
            str(item.get("updated_at") or ""),
            str(item.get("link_type") or ""),
            str(item.get("link_id") or ""),
        ),
        reverse=True,
    )[:normalized_limit]
    return {
        "case_evidence_links_schema_version": (
            OPERATOR_REVIEW_CASE_EVIDENCE_LINKS_SCHEMA_VERSION
        ),
        "trace_id": optional_text(trace_id),
        "request_id": required_text({"request_id": request_id}, "request_id"),
        "case": {
            "case_id": record.get("case_id"),
            "target_ref": _case_target_ref(record),
            "case_status": record.get("case_status"),
            "case_priority": record.get("case_priority"),
            "source_ref": _case_workbench_source_ref(record),
            "updated_at": record.get("updated_at"),
        },
        "items": items,
        "summary": {
            "evidence_source_status": source_status,
            "operator_note_count": len(note_links),
            "redacted_evidence_export_count": len(export_links),
            "total_link_count": len(note_links) + len(export_links),
            "returned_link_count": len(items),
            "latest_updated_at": items[0]["updated_at"] if items else None,
        },
        "links": {
            "case_detail_path": (
                f"/admin/v1/operator-review/cases/{record.get('case_id')}"
            ),
            "case_workbench_detail_path": (
                f"/admin/v1/operator-review/cases/{record.get('case_id')}"
                "/workbench-detail"
            ),
            "case_timeline_path": (
                f"/admin/v1/operator-review/cases/{record.get('case_id')}/timeline"
            ),
            "case_evidence_links_path": (
                f"/admin/v1/operator-review/cases/{record.get('case_id')}"
                "/evidence-links"
            ),
            "case_action_admission_path": (
                f"/admin/v1/operator-review/cases/{record.get('case_id')}"
                "/action-admission"
            ),
            "operator_review_workbench_path": "/admin/v1/operator-review/workbench",
        },
        "redaction": {
            "raw_operator_note_included": False,
            "raw_evidence_body_included": False,
            "raw_case_comment_included": False,
            "raw_action_comment_included": False,
            "raw_prompt_included": False,
            "raw_generation_output_included": False,
            "raw_source_text_included": False,
            "storage_paths_included": False,
            "provider_payloads_included": False,
            "database_urls_included": False,
            "tokens_included": False,
            "idempotency_keys_included": False,
            "metadata_payload_included": False,
            "evidence_payload_shape": "safe_refs_hashes_and_bounded_previews_only",
        },
    }


def build_operator_review_case_action_admission_projection(
    record: dict[str, Any],
    *,
    request_id: str,
    trace_id: str | None,
    action_type: str | None = None,
) -> dict[str, Any]:
    normalized_action_type = (
        required_case_action_type(action_type)
        if optional_text(action_type) is not None
        else None
    )
    admission_items = [
        _case_action_admission_item(record, candidate_action_type)
        for candidate_action_type in (
            "ACKNOWLEDGE",
            "ASSIGN",
            "RESOLVE",
            "DISMISS",
            "REOPEN",
        )
        if normalized_action_type is None
        or candidate_action_type == normalized_action_type
    ]
    admitted_count = sum(1 for item in admission_items if item["admitted"] is True)
    blocked_count = len(admission_items) - admitted_count
    requested_item = admission_items[0] if normalized_action_type is not None else None
    return {
        "case_action_admission_schema_version": (
            OPERATOR_REVIEW_CASE_ACTION_ADMISSION_SCHEMA_VERSION
        ),
        "trace_id": optional_text(trace_id),
        "request_id": required_text({"request_id": request_id}, "request_id"),
        "case": {
            "case_id": record.get("case_id"),
            "target_ref": _case_target_ref(record),
            "case_status": record.get("case_status"),
            "case_priority": record.get("case_priority"),
            "assignment_ref": {
                "assignee_id": _case_assignment_ref(record).get("assignee_id"),
                "assignee_type": _case_assignment_ref(record).get("assignee_type"),
                "tenant_id": _case_assignment_ref(record).get("tenant_id"),
            },
            "updated_at": record.get("updated_at"),
        },
        "requested_action": requested_item,
        "items": admission_items,
        "summary": {
            "current_status": str(record.get("case_status") or ""),
            "requested_action_type": normalized_action_type,
            "requested_action_admitted": (
                requested_item.get("admitted") if requested_item is not None else None
            ),
            "admitted_action_count": admitted_count,
            "blocked_action_count": blocked_count,
            "preflight_only": True,
            "mutation_route_authoritative": True,
            "admission_source": "operator_review_case_action_state_machine",
        },
        "links": {
            "case_detail_path": (
                f"/admin/v1/operator-review/cases/{record.get('case_id')}"
            ),
            "case_workbench_detail_path": (
                f"/admin/v1/operator-review/cases/{record.get('case_id')}"
                "/workbench-detail"
            ),
            "case_action_path": (
                f"/admin/v1/operator-review/cases/{record.get('case_id')}/actions"
            ),
            "case_action_admission_path": (
                f"/admin/v1/operator-review/cases/{record.get('case_id')}"
                "/action-admission"
            ),
        },
        "redaction": {
            "raw_case_comment_included": False,
            "raw_action_comment_included": False,
            "raw_resolution_comment_included": False,
            "raw_prompt_included": False,
            "raw_generation_output_included": False,
            "raw_source_text_included": False,
            "storage_paths_included": False,
            "provider_payloads_included": False,
            "database_urls_included": False,
            "tokens_included": False,
            "idempotency_keys_included": False,
            "metadata_payload_included": False,
            "admission_payload_shape": "case_state_machine_preflight_only",
        },
    }


def build_operator_review_case_timeline_projection(
    record: dict[str, Any],
    *,
    event_store: OperationalEventStore,
    request_id: str,
    trace_id: str | None,
    limit: int | None = None,
) -> dict[str, Any]:
    normalized_limit = normalize_limit(limit)
    source_status = "READY"
    source_error: dict[str, Any] | None = None
    try:
        events = event_store.list_events(
            service_id="nex-ag",
            trace_id=record.get("trace_id"),
            limit=normalized_limit,
        )
    except OperationalEventError as exc:
        source_status = "UNAVAILABLE"
        source_error = {
            "error_code": exc.error_code,
            "detail": exc.detail,
            "status_code": exc.status_code,
        }
        events = []
    except Exception:
        source_status = "UNAVAILABLE"
        source_error = {
            "error_code": "ag.operator_review_case_timeline_unavailable",
            "detail": "Operator review case timeline source is unavailable.",
            "status_code": 503,
        }
        events = []

    items = _case_timeline_items(record, events, limit=normalized_limit)
    return {
        "case_timeline_schema_version": OPERATOR_REVIEW_CASE_TIMELINE_SCHEMA_VERSION,
        "trace_id": optional_text(trace_id),
        "request_id": required_text({"request_id": request_id}, "request_id"),
        "case_id": record.get("case_id"),
        "target_ref": {
            "target_service": record.get("target_service"),
            "target_kind": record.get("target_kind"),
            "target_id": record.get("target_id"),
        },
        "items": items,
        "summary": {
            "timeline_status": source_status,
            "event_count": len(items),
            "case_recorded_event_count": sum(
                1
                for item in items
                if item.get("event_type") == OPERATOR_REVIEW_CASE_RECORDED_EVENT_TYPE
            ),
            "case_action_event_count": sum(
                1
                for item in items
                if item.get("event_type")
                == OPERATOR_REVIEW_CASE_ACTION_RECORDED_EVENT_TYPE
            ),
            "latest_event_at": items[-1]["created_at"] if items else None,
            "source_error": source_error,
        },
        "paths": {
            "case_detail_path": (
                f"/admin/v1/operator-review/cases/{record.get('case_id')}"
            ),
            "case_workbench_detail_path": (
                f"/admin/v1/operator-review/cases/{record.get('case_id')}"
                "/workbench-detail"
            ),
            "case_timeline_path": (
                f"/admin/v1/operator-review/cases/{record.get('case_id')}/timeline"
            ),
        },
        "redaction": {
            "raw_case_comment_included": False,
            "raw_action_comment_included": False,
            "raw_resolution_comment_included": False,
            "raw_prompt_included": False,
            "raw_generation_output_included": False,
            "raw_source_text_included": False,
            "storage_paths_included": False,
            "idempotency_keys_included": False,
            "timeline_payload_shape": "operational_event_metadata_only",
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


def build_operator_review_case_rollup_metrics(
    case_list: dict[str, Any],
) -> dict[str, Any]:
    cases = list(case_list.get("items") or [])
    last_actions = [_safe_case_last_action_ref(record) for record in cases]
    last_actions = [action for action in last_actions if action is not None]
    attention_items = [_case_attention_item(record) for record in cases]
    attention_items = [
        item for item in attention_items if item["attention_status"] != "OK"
    ]
    attention_items.sort(
        key=lambda item: (
            _case_attention_sort_rank(item["attention_status"]),
            str(item.get("latest_updated_at") or ""),
            str(item.get("case_id") or ""),
        )
    )
    return {
        "rollup_schema_version": OPERATOR_REVIEW_CASE_ROLLUP_SCHEMA_VERSION,
        "trace_id": case_list.get("trace_id"),
        "request_id": case_list.get("request_id"),
        "summary": {
            "case_count": len(cases),
            "open_case_count": sum(
                1
                for record in cases
                if record.get("case_status")
                in {"OPEN", "ACKNOWLEDGED", "ASSIGNED", "REOPENED"}
            ),
            "closed_case_count": sum(
                1
                for record in cases
                if record.get("case_status") in {"RESOLVED", "DISMISSED"}
            ),
            "assigned_case_count": sum(
                1 for record in cases if record.get("case_status") == "ASSIGNED"
            ),
            "urgent_case_count": sum(
                1 for record in cases if record.get("case_priority") == "URGENT"
            ),
            "unassigned_open_case_count": sum(
                1 for record in cases if _case_is_unassigned_open(record)
            ),
            "actioned_case_count": len(last_actions),
            "attention_case_count": len(attention_items),
            "latest_updated_at": case_list.get("summary", {}).get(
                "latest_updated_at"
            ),
        },
        "by_target_service": _count_by(cases, "target_service"),
        "by_target_kind": _count_by(cases, "target_kind"),
        "by_case_status": _count_by(cases, "case_status"),
        "by_case_priority": _count_by(cases, "case_priority"),
        "by_last_action_type": _count_by(last_actions, "action_type"),
        "attention": {
            "items": attention_items,
            "by_status": _count_by(attention_items, "attention_status"),
        },
        "redaction": {
            "raw_case_comment_included": False,
            "raw_action_comment_included": False,
            "raw_resolution_comment_included": False,
            "raw_prompt_included": False,
            "raw_generation_output_included": False,
            "raw_source_text_included": False,
            "storage_paths_included": False,
            "idempotency_keys_included": False,
            "case_comment_shape": "hash_and_short_preview_only",
            "action_history_shape": "operational_events_first",
        },
        "paths": {
            "case_list_path": "/admin/v1/operator-review/cases",
            "case_rollup_path": "/admin/v1/operator-review/cases/rollups",
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


def _safe_case_last_action_ref(record: dict[str, Any]) -> dict[str, Any] | None:
    action_summary = _latest_case_action_summary(record)
    if action_summary is None:
        return None
    action = action_summary["record"]
    assignment = action.get("assignment_ref")
    assignment_ref_value = assignment if isinstance(assignment, dict) else {}
    return {
        "case_id": record.get("case_id"),
        "action_id": action.get("action_id"),
        "action_type": action.get("action_type"),
        "from_status": action.get("from_status"),
        "to_status": action.get("to_status"),
        "acted_at": action.get("acted_at"),
        "operator_ref": _case_operator_ref(action),
        "assignee_id": assignment_ref_value.get("assignee_id"),
        "reason_count": len(action.get("reason_codes") or []),
        "action_comment_hash": action.get("action_comment_hash"),
        "resolution_hash": action.get("resolution_hash"),
    }


def _case_queue_item(record: dict[str, Any]) -> dict[str, Any]:
    assignment = record.get("assignment_ref")
    assignment_ref_value = assignment if isinstance(assignment, dict) else {}
    source = record.get("source_ref")
    source_ref_value = source if isinstance(source, dict) else {}
    attention = _case_attention_item(record)
    return {
        "queue_item_schema_version": "ag_operator_review_case_queue_item.v1",
        "case_id": record.get("case_id"),
        "target_ref": dict(attention["target_ref"]),
        "case_status": record.get("case_status"),
        "case_priority": record.get("case_priority"),
        "attention_status": attention["attention_status"],
        "attention_reason_codes": list(attention["reason_codes"]),
        "recommended_actions": list(attention["recommended_actions"]),
        "operator_ref": _case_operator_ref(record),
        "assignment_ref": {
            "assignee_type": optional_text(assignment_ref_value.get("assignee_type")),
            "assignee_id": optional_text(assignment_ref_value.get("assignee_id")),
            "tenant_id": optional_text(assignment_ref_value.get("tenant_id")),
        },
        "source_ref": {
            "source_type": optional_text(source_ref_value.get("source_type")),
            "source_id": optional_text(source_ref_value.get("source_id")),
            "source_service": optional_text(source_ref_value.get("source_service")),
            "workbench_path": optional_text(source_ref_value.get("workbench_path")),
        },
        "reason_count": len(record.get("reason_codes") or []),
        "resolution_hash": record.get("resolution_hash"),
        "resolution_preview": record.get("resolution_preview"),
        "latest_action": _safe_case_last_action_ref(record),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "closed_at": record.get("closed_at"),
        "links": {
            "case_detail_path": (
                f"/admin/v1/operator-review/cases/{record.get('case_id')}"
            ),
            "case_action_path": (
                f"/admin/v1/operator-review/cases/{record.get('case_id')}/actions"
            ),
        },
        "redaction": {
            "raw_case_comment_included": False,
            "raw_action_comment_included": False,
            "raw_resolution_comment_included": False,
            "idempotency_keys_included": False,
            "storage_paths_included": False,
        },
    }


def _case_workbench_source_ref(record: dict[str, Any]) -> dict[str, str | None]:
    source = record.get("source_ref")
    source_ref_value = source if isinstance(source, dict) else {}
    return {
        "source_type": optional_text(source_ref_value.get("source_type")),
        "source_id": optional_text(source_ref_value.get("source_id")),
        "source_service": optional_text(source_ref_value.get("source_service")),
        "workbench_path": optional_text(source_ref_value.get("workbench_path")),
    }


def _case_target_ref(record: dict[str, Any]) -> dict[str, str | None]:
    return {
        "target_service": optional_text(record.get("target_service")),
        "target_kind": optional_text(record.get("target_kind")),
        "target_id": optional_text(record.get("target_id")),
    }


def _case_assignment_ref(record: dict[str, Any]) -> dict[str, str | None]:
    assignment = record.get("assignment_ref")
    assignment_ref_value = assignment if isinstance(assignment, dict) else {}
    return {
        "assignee_type": optional_text(assignment_ref_value.get("assignee_type")),
        "assignee_id": optional_text(assignment_ref_value.get("assignee_id")),
        "tenant_id": optional_text(assignment_ref_value.get("tenant_id")),
    }


def _record_targets_case(
    case_record: dict[str, Any],
    candidate_record: dict[str, Any],
) -> bool:
    case_target = _case_target_ref(case_record)
    candidate_target = _case_target_ref(candidate_record)
    return (
        case_target["target_service"] == candidate_target["target_service"]
        and case_target["target_kind"] == candidate_target["target_kind"]
        and case_target["target_id"] == candidate_target["target_id"]
    )


def _case_evidence_note_link(record: dict[str, Any]) -> dict[str, Any]:
    operator_note_id = optional_text(record.get("operator_note_id"))
    return {
        "case_evidence_link_schema_version": "ag_operator_review_case_evidence_link.v1",
        "link_type": "operator_review_note",
        "link_id": operator_note_id,
        "target_ref": _case_target_ref(record),
        "operator_ref": _case_operator_ref(record),
        "note_status": optional_text(record.get("note_status")),
        "note_type": optional_text(record.get("note_type")),
        "severity": optional_text(record.get("severity")),
        "operator_note_hash": optional_text(record.get("operator_note_hash")),
        "operator_note_preview": optional_text(record.get("operator_note_preview")),
        "reason_count": len(record.get("reason_codes") or []),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "detail_path": (
            f"/admin/v1/operator-review/notes/{operator_note_id}"
            if operator_note_id is not None
            else None
        ),
        "redaction": {
            "raw_operator_note_included": False,
            "raw_prompt_included": False,
            "storage_paths_included": False,
            "idempotency_keys_included": False,
        },
    }


def _case_evidence_export_link(record: dict[str, Any]) -> dict[str, Any]:
    export_id = optional_text(record.get("export_id"))
    return {
        "case_evidence_link_schema_version": "ag_operator_review_case_evidence_link.v1",
        "link_type": "redacted_evidence_export",
        "link_id": export_id,
        "target_ref": _case_target_ref(record),
        "operator_ref": _case_operator_ref(record),
        "export_status": optional_text(record.get("export_status")),
        "export_format": optional_text(record.get("export_format")),
        "redaction_profile": optional_text(record.get("redaction_profile")),
        "evidence_hash": optional_text(record.get("evidence_hash")),
        "evidence_item_count": int(record.get("evidence_item_count") or 0),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "detail_path": (
            f"/admin/v1/operator-review/evidence-exports/{export_id}"
            if export_id is not None
            else None
        ),
        "redaction": {
            "raw_evidence_body_included": False,
            "raw_prompt_included": False,
            "storage_paths_included": False,
            "idempotency_keys_included": False,
        },
    }


def _case_action_admission_item(
    record: dict[str, Any],
    action_type: str,
) -> dict[str, Any]:
    current_status = str(record.get("case_status") or "")
    allowed_from = CASE_ACTION_ALLOWED_FROM[action_type]
    target_status = CASE_ACTION_TARGET_STATUSES[action_type]
    admitted = current_status in allowed_from
    return {
        "case_action_admission_item_schema_version": (
            "ag_operator_review_case_action_admission_item.v1"
        ),
        "action_type": action_type,
        "current_status": current_status,
        "target_status": target_status,
        "admitted": admitted,
        "blocked_reason": (
            None
            if admitted
            else f"{action_type} cannot transition from {current_status}."
        ),
        "requires_idempotency_key": True,
        "requires_assignment_ref": action_type == "ASSIGN",
        "requires_resolution_comment": action_type == "RESOLVE",
        "mutation_method": "POST",
        "mutation_path": (
            f"/admin/v1/operator-review/cases/{record.get('case_id')}/actions"
        ),
        "mutation_route_authoritative": True,
        "preflight_only": True,
    }


def _case_workbench_action_controls(record: dict[str, Any]) -> dict[str, Any]:
    status = str(record.get("case_status") or "")
    available_actions: list[dict[str, Any]] = []
    blocked_actions: list[dict[str, Any]] = []
    for action_type in (
        "ACKNOWLEDGE",
        "ASSIGN",
        "RESOLVE",
        "DISMISS",
        "REOPEN",
    ):
        allowed_from = CASE_ACTION_ALLOWED_FROM[action_type]
        if status in allowed_from:
            available_actions.append(
                _case_workbench_action_control_item(
                    action_type=action_type,
                    available=True,
                    current_status=status,
                )
            )
        else:
            blocked_actions.append(
                _case_workbench_action_control_item(
                    action_type=action_type,
                    available=False,
                    current_status=status,
                )
            )
    return {
        "current_status": status,
        "available_actions": available_actions,
        "blocked_actions": blocked_actions,
        "available_action_count": len(available_actions),
        "blocked_action_count": len(blocked_actions),
        "requires_idempotency_key": True,
    }


def _case_workbench_action_control_item(
    *,
    action_type: str,
    available: bool,
    current_status: str,
) -> dict[str, Any]:
    target_status = CASE_ACTION_TARGET_STATUSES[action_type]
    return {
        "action_type": action_type,
        "target_status": target_status,
        "available": available,
        "blocked_reason": (
            None
            if available
            else f"{action_type} cannot transition from {current_status or 'UNKNOWN'}."
        ),
        "requires_assignment_ref": action_type == "ASSIGN",
        "requires_resolution_comment": action_type in {"RESOLVE", "DISMISS"},
        "method": "POST",
        "idempotency_key_required": True,
    }


def _case_timeline_items(
    record: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    selected = [
        _case_timeline_item(event)
        for event in events
        if _event_matches_operator_review_case(record, event)
    ]
    selected.sort(
        key=lambda item: (
            str(item.get("created_at") or ""),
            str(item.get("event_id") or ""),
        )
    )
    return selected[:limit]


def _event_matches_operator_review_case(
    record: dict[str, Any],
    event: dict[str, Any],
) -> bool:
    if event.get("event_type") not in {
        OPERATOR_REVIEW_CASE_RECORDED_EVENT_TYPE,
        OPERATOR_REVIEW_CASE_ACTION_RECORDED_EVENT_TYPE,
    }:
        return False
    case_id = str(record.get("case_id") or "")
    details = event.get("details")
    if isinstance(details, dict) and str(details.get("case_id") or "") == case_id:
        return True
    subject_ref = event.get("subject_ref")
    if not isinstance(subject_ref, dict):
        return False
    return (
        subject_ref.get("type") == "operator_review_case"
        and str(subject_ref.get("id") or "") == case_id
    )


def _case_timeline_item(event: dict[str, Any]) -> dict[str, Any]:
    details = event.get("details") if isinstance(event.get("details"), dict) else {}
    subject_ref = (
        event.get("subject_ref") if isinstance(event.get("subject_ref"), dict) else {}
    )
    return {
        "timeline_item_schema_version": "ag_operator_review_case_timeline_item.v1",
        "event_id": event.get("event_id"),
        "event_type": event.get("event_type"),
        "severity": event.get("severity"),
        "message": event.get("message"),
        "trace_id": event.get("trace_id"),
        "request_id": event.get("request_id"),
        "created_at": event.get("created_at"),
        "subject_ref": {
            "type": optional_text(subject_ref.get("type")),
            "id": optional_text(subject_ref.get("id")),
        },
        "details": {
            "case_id": optional_text(details.get("case_id")),
            "action_id": optional_text(details.get("action_id")),
            "action_type": optional_text(details.get("action_type")),
            "from_status": optional_text(details.get("from_status")),
            "to_status": optional_text(details.get("to_status")),
            "case_status": optional_text(details.get("case_status")),
            "case_priority": optional_text(details.get("case_priority")),
            "target_service": optional_text(details.get("target_service")),
            "target_kind": optional_text(details.get("target_kind")),
            "target_id": optional_text(details.get("target_id")),
            "operator_type": optional_text(details.get("operator_type")),
            "operator_id": optional_text(details.get("operator_id")),
            "assignee_id": optional_text(details.get("assignee_id")),
            "reason_count": details.get("reason_count"),
            "action_comment_hash": optional_text(details.get("action_comment_hash")),
            "resolution_hash": optional_text(details.get("resolution_hash")),
        },
    }


def _case_queue_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "case_count": len(items),
        "open_case_count": sum(
            1
            for item in items
            if item.get("case_status")
            in {"OPEN", "ACKNOWLEDGED", "ASSIGNED", "REOPENED"}
        ),
        "closed_case_count": sum(
            1
            for item in items
            if item.get("case_status") in {"RESOLVED", "DISMISSED"}
        ),
        "assigned_case_count": sum(
            1 for item in items if item.get("case_status") == "ASSIGNED"
        ),
        "urgent_case_count": sum(
            1 for item in items if item.get("case_priority") == "URGENT"
        ),
        "attention_case_count": sum(
            1 for item in items if item.get("attention_status") != "OK"
        ),
        "unassigned_open_case_count": sum(
            1
            for item in items
            if item.get("case_status") in {"OPEN", "ACKNOWLEDGED", "REOPENED"}
            and item.get("assignment_ref", {}).get("assignee_id") is None
        ),
        "by_attention_status": _count_by(items, "attention_status"),
        "by_case_status": _count_by(items, "case_status"),
        "by_case_priority": _count_by(items, "case_priority"),
        "latest_updated_at": max(
            (str(item.get("updated_at") or "") for item in items),
            default=None,
        ),
    }


def _filter_case_queue_items(
    items: list[dict[str, Any]],
    *,
    latest_action_type: str | None,
    attention_status: str | None,
    search: str | None,
) -> list[dict[str, Any]]:
    selected = list(items)
    if latest_action_type is not None:
        selected = [
            item
            for item in selected
            if (item.get("latest_action") or {}).get("action_type")
            == latest_action_type
        ]
    if attention_status is not None:
        selected = [
            item
            for item in selected
            if item.get("attention_status") == attention_status
        ]
    if search is not None:
        selected = [
            item for item in selected if _case_queue_item_matches_query(item, search)
        ]
    return selected


def _sort_case_queue_items(
    items: list[dict[str, Any]],
    *,
    sort_by: str,
    sort_direction: str,
) -> list[dict[str, Any]]:
    reverse = sort_direction == "desc"
    return sorted(
        items,
        key=lambda item: _case_queue_sort_key(item, sort_by),
        reverse=reverse,
    )


def _case_queue_sort_key(item: dict[str, Any], sort_by: str) -> tuple[Any, ...]:
    if sort_by == "attention":
        return (
            _case_attention_sort_rank(str(item.get("attention_status") or "")),
            _reverse_text_sort_token(item.get("updated_at")),
            str(item.get("case_id") or ""),
        )
    if sort_by == "updated_at":
        return (str(item.get("updated_at") or ""), str(item.get("case_id") or ""))
    if sort_by == "priority":
        return (
            _case_priority_sort_rank(str(item.get("case_priority") or "")),
            str(item.get("case_id") or ""),
        )
    if sort_by == "status":
        return (str(item.get("case_status") or ""), str(item.get("case_id") or ""))
    return (str(item.get("case_id") or ""),)


def _case_queue_item_matches_query(item: dict[str, Any], query: str) -> bool:
    needle = query.strip().lower()
    if not needle:
        return True
    searchable_values = [
        item.get("case_id"),
        item.get("case_status"),
        item.get("case_priority"),
        item.get("attention_status"),
        item.get("resolution_hash"),
        item.get("resolution_preview"),
    ]
    searchable_values.extend((item.get("target_ref") or {}).values())
    searchable_values.extend((item.get("operator_ref") or {}).values())
    searchable_values.extend((item.get("assignment_ref") or {}).values())
    searchable_values.extend((item.get("source_ref") or {}).values())
    searchable_values.extend(item.get("attention_reason_codes") or [])
    searchable_values.extend(item.get("recommended_actions") or [])
    latest_action = item.get("latest_action") or {}
    if isinstance(latest_action, dict):
        searchable_values.extend(
            value
            for key, value in latest_action.items()
            if key not in {"action_comment_hash", "resolution_hash"}
        )
    return any(needle in str(value).lower() for value in searchable_values if value)


def _case_attention_item(record: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    status = str(record.get("case_status") or "")
    priority = str(record.get("case_priority") or "")
    if status == "REOPENED":
        reasons.append("reopened_case_requires_review")
    if status == "OPEN":
        reasons.append("open_case_requires_triage")
    if _case_is_unassigned_open(record):
        reasons.append("open_case_unassigned")
    if priority == "URGENT" and status not in {"RESOLVED", "DISMISSED"}:
        reasons.append("urgent_case_not_closed")
    if status == "ASSIGNED":
        reasons.append("assigned_case_in_progress")

    if "urgent_case_not_closed" in reasons:
        attention_status = "BLOCKED"
    elif "reopened_case_requires_review" in reasons:
        attention_status = "ATTENTION"
    elif reasons:
        attention_status = "OPEN"
    else:
        attention_status = "OK"

    assignment = record.get("assignment_ref")
    assignment_ref_value = assignment if isinstance(assignment, dict) else {}
    last_action = _safe_case_last_action_ref(record)
    recommended_actions = _case_recommended_actions(record, reasons)
    return {
        "case_id": record.get("case_id"),
        "target_ref": {
            "target_service": record.get("target_service"),
            "target_kind": record.get("target_kind"),
            "target_id": record.get("target_id"),
        },
        "case_status": status,
        "case_priority": priority,
        "attention_status": attention_status,
        "reason_codes": reasons,
        "recommended_actions": recommended_actions,
        "assignee_id": assignment_ref_value.get("assignee_id"),
        "last_action_type": (
            last_action.get("action_type") if last_action is not None else None
        ),
        "last_action_at": (
            last_action.get("acted_at") if last_action is not None else None
        ),
        "latest_updated_at": record.get("updated_at"),
    }


def _case_recommended_actions(
    record: dict[str, Any],
    reasons: list[str],
) -> list[str]:
    status = str(record.get("case_status") or "")
    actions: set[str] = set()
    if "open_case_requires_triage" in reasons:
        actions.add("acknowledge_or_assign_case")
    if "open_case_unassigned" in reasons:
        actions.add("assign_case_owner")
    if "urgent_case_not_closed" in reasons:
        actions.add("prioritize_urgent_operator_review_case")
    if "reopened_case_requires_review" in reasons:
        actions.add("review_reopened_case")
    if status == "ASSIGNED":
        actions.add("resolve_or_dismiss_after_review")
    return sorted(actions)


def _case_is_unassigned_open(record: dict[str, Any]) -> bool:
    if record.get("case_status") not in {"OPEN", "ACKNOWLEDGED", "REOPENED"}:
        return False
    assignment = record.get("assignment_ref")
    assignment_ref_value = assignment if isinstance(assignment, dict) else {}
    return assignment_ref_value.get("assignee_id") is None


def _case_operator_ref(record: dict[str, Any]) -> dict[str, str | None]:
    operator = record.get("operator_ref")
    if not isinstance(operator, dict):
        return {"operator_type": None, "operator_id": None, "tenant_id": None}
    return {
        "operator_type": optional_text(operator.get("operator_type")),
        "operator_id": optional_text(operator.get("operator_id")),
        "tenant_id": optional_text(operator.get("tenant_id")),
    }


def _case_attention_sort_rank(status: str) -> int:
    return {"BLOCKED": 0, "ATTENTION": 1, "OPEN": 2}.get(status, 3)


def _case_priority_sort_rank(priority: str) -> int:
    return {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "URGENT": 3}.get(priority, 4)


def _reverse_text_sort_token(value: Any) -> str:
    return "".join(chr(0x10FFFF - ord(character)) for character in str(value or ""))


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
