from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .operator_reviews import (
    ALLOWED_OPERATOR_TYPES,
    ALLOWED_TARGET_SERVICES,
    OperatorReviewNoteError,
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
AG_OPERATOR_REVIEW_CASE_TABLE = "ag_op_cases"
MAX_CASE_COMMENT_PREVIEW_LENGTH = 240

ALLOWED_CASE_STATUSES = (
    "OPEN",
    "ACKNOWLEDGED",
    "ASSIGNED",
    "RESOLVED",
    "DISMISSED",
    "REOPENED",
)
ALLOWED_CASE_PRIORITIES = ("LOW", "MEDIUM", "HIGH", "URGENT")


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


def default_operator_review_case_store(app: FastAPI) -> Any:
    persistence = getattr(app.state, "nex_persistence", None)
    session_factory = getattr(persistence, "api_session_factory", None)
    if session_factory is not None:
        return SqlAlchemyOperatorReviewCaseStore(session_factory)
    return DEFAULT_OPERATOR_REVIEW_CASE_STORE


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
