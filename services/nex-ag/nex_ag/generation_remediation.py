from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from fastapi import Body, FastAPI, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from typing import Any, Iterable, Mapping
from uuid import NAMESPACE_URL, uuid5

from nex_ag.generation_remediation_boundary import (
    ALLOWED_REMEDIATION_INTENTS,
    REMEDIATION_STATUS_TRANSITIONS,
    GenerationRemediationBoundaryError,
    assert_generation_remediation_payload_redaction_safe,
    remediation_transition_allowed,
)
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


REMEDIATION_ACTION_SCHEMA_VERSION = "ag_generation_remediation_action.v1"
REMEDIATION_ACTION_LIST_SCHEMA_VERSION = "ag_generation_remediation_action_list.v1"
REMEDIATION_CANDIDATE_PROJECTION_SCHEMA_VERSION = (
    "ag_generation_remediation_candidate_projection.v1"
)
REMEDIATION_TASK_RECORDED_EVENT_TYPE = "ag.generation_remediation.task_recorded"
REMEDIATION_TASK_STATUS_UPDATED_EVENT_TYPE = (
    "ag.generation_remediation.task_status_updated"
)
MAX_EVIDENCE_PREVIEW_LENGTH = 240
MAX_CANDIDATE_ITEMS = 500
DEFAULT_CANDIDATE_ITEMS = 50

ALLOWED_ACTION_TYPES = ALLOWED_REMEDIATION_INTENTS
ALLOWED_ACTION_STATUSES = tuple(REMEDIATION_STATUS_TRANSITIONS)
ALLOWED_PRIORITIES = ("LOW", "NORMAL", "HIGH", "URGENT")
ALLOWED_REASON_CODES = (
    "negative_user_feedback",
    "operator_requested_repair",
    "retrieval_quality",
    "citation_quality",
    "generation_quality",
    "metadata_gap",
    "policy_review",
    "false_positive",
    "other",
)
ALLOWED_SOURCE_SERVICES = ("nex-ae-api", "nex-cx", "nex-ag")
ALLOWED_RESULT_SOURCE_SERVICES = ("nex-cx", "nex-ag")
ALLOWED_REF_TYPES = (
    "generation_quality",
    "feedback",
    "operator_disposition",
    "retrieval_package",
    "chat_interaction",
    "repair_execution",
)
ALLOWED_REF_RELATIONS = (
    "caused_by",
    "recommended_by",
    "blocks",
    "supersedes",
    "result_of",
)
ALLOWED_ACTION_SOURCES = (
    "manual",
    "candidate_projection",
    "operator_disposition",
    "system_policy",
)
ISSUE_CODE_ACTION_HINTS = (
    ("CITATION", "citation_repair"),
    ("RETRIEVAL", "retrieval_repair"),
    ("NO_ANSWER", "retrieval_repair"),
    ("LOW_CONFIDENCE", "retrieval_repair"),
    ("GROUNDING", "retrieval_repair"),
    ("METADATA", "retry_generation"),
    ("GENERATION", "retry_generation"),
)


@dataclass(frozen=True)
class GenerationRemediationError(Exception):
    status_code: int
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


@dataclass
class GenerationRemediationTaskStore:
    records: dict[str, dict[str, Any]] = field(default_factory=dict)
    action_ids_by_generation: dict[str, list[str]] = field(default_factory=dict)

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        action_id = record["remediation_action_id"]
        previous = self.records.get(action_id)
        if previous is not None and previous["cx_generation_id"] != record["cx_generation_id"]:
            self._remove_generation_index(previous["cx_generation_id"], action_id)
        self.records[action_id] = record
        ids = self.action_ids_by_generation.setdefault(record["cx_generation_id"], [])
        if action_id not in ids:
            ids.append(action_id)
        return record

    def get(self, remediation_action_id: str) -> dict[str, Any] | None:
        return self.records.get(remediation_action_id)

    def list_for_generation(self, cx_generation_id: str) -> list[dict[str, Any]]:
        return [
            self.records[action_id]
            for action_id in self.action_ids_by_generation.get(cx_generation_id, [])
            if action_id in self.records
        ]

    def delete(self, remediation_action_id: str) -> int:
        record = self.records.pop(remediation_action_id, None)
        if record is None:
            return 0
        self._remove_generation_index(record["cx_generation_id"], remediation_action_id)
        return 1

    def _remove_generation_index(self, cx_generation_id: str, action_id: str) -> None:
        ids = self.action_ids_by_generation.get(cx_generation_id, [])
        self.action_ids_by_generation[cx_generation_id] = [
            existing_id for existing_id in ids if existing_id != action_id
        ]


class SqlAlchemyGenerationRemediationTaskStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        try:
            with self._session_factory() as session:
                session.execute(
                    text(_remediation_upsert_sql(_dialect_name(session))),
                    _remediation_record_params(record),
                )
                session.commit()
            return record
        except SQLAlchemyError as exc:
            raise _store_unavailable_error() from exc

    def get(self, remediation_action_id: str) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(
                        text(
                            _remediation_select_sql(
                                "remediation_action_id = :remediation_action_id"
                            )
                        ),
                        {"remediation_action_id": remediation_action_id},
                    )
                    .mappings()
                    .first()
                )
            return _remediation_record_from_row(row) if row is not None else None
        except SQLAlchemyError as exc:
            raise _store_unavailable_error() from exc

    def list_for_generation(self, cx_generation_id: str) -> list[dict[str, Any]]:
        try:
            with self._session_factory() as session:
                rows = (
                    session.execute(
                        text(
                            _remediation_select_sql(
                                "cx_generation_id = :cx_generation_id "
                                "ORDER BY updated_at DESC, remediation_action_id ASC"
                            )
                        ),
                        {"cx_generation_id": cx_generation_id},
                    )
                    .mappings()
                    .all()
                )
            return [_remediation_record_from_row(row) for row in rows]
        except SQLAlchemyError as exc:
            raise _store_unavailable_error() from exc

    def delete(self, remediation_action_id: str) -> int:
        try:
            with self._session_factory() as session:
                result = session.execute(
                    text(
                        "DELETE FROM ag_generation_remediation_tasks "
                        "WHERE remediation_action_id = :remediation_action_id"
                    ),
                    {"remediation_action_id": remediation_action_id},
                )
                session.commit()
                return int(result.rowcount or 0)
        except SQLAlchemyError as exc:
            raise _store_unavailable_error() from exc


DEFAULT_REMEDIATION_TASK_STORE = GenerationRemediationTaskStore()
DEFAULT_REMEDIATION_AUDIT_EVENT_STORE = InMemoryOperationalEventStore()


def default_generation_remediation_task_store(app: FastAPI) -> Any:
    persistence = getattr(app.state, "nex_persistence", None)
    session_factory = getattr(persistence, "api_session_factory", None)
    if session_factory is not None:
        return SqlAlchemyGenerationRemediationTaskStore(session_factory)
    return DEFAULT_REMEDIATION_TASK_STORE


def register_generation_remediation_task_routes(
    app: FastAPI,
    *,
    store: Any | None = None,
    audit_event_store: OperationalEventStore | None = None,
) -> None:
    selected_store = store or default_generation_remediation_task_store(app)
    audit_emitter = OperationalEventEmitter(
        service_id="nex-ag",
        store=audit_event_store or DEFAULT_REMEDIATION_AUDIT_EVENT_STORE,
    )

    @app.post(
        "/admin/v1/generation-audit/generations/{cx_generation_id}/remediation-tasks",
        response_model=None,
    )
    def create_generation_remediation_task(
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
            record = build_generation_remediation_action(
                payload,
                cx_generation_id=cx_generation_id,
                request_id=request_id,
                trace_id=trace_id,
            )
            selected_store.save(record)
        except GenerationRemediationError as exc:
            return _remediation_problem_response(request, exc)

        emit_generation_remediation_task_event(
            audit_emitter,
            record,
            event_type=REMEDIATION_TASK_RECORDED_EVENT_TYPE,
        )
        return JSONResponse(status_code=202, content=record)

    @app.get(
        "/admin/v1/generation-audit/generations/{cx_generation_id}/remediation-tasks",
        response_model=None,
    )
    def list_generation_remediation_tasks(
        cx_generation_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        try:
            records = selected_store.list_for_generation(cx_generation_id)
        except GenerationRemediationError as exc:
            return _remediation_problem_response(request, exc)
        return build_generation_remediation_action_list_response(
            records,
            cx_generation_id=cx_generation_id,
            request_id=request_id_from_headers(request),
            trace_id=trace_id_from_headers(request),
        )

    @app.get(
        (
            "/admin/v1/generation-audit/generations/{cx_generation_id}"
            "/remediation-tasks/{remediation_action_id}"
        ),
        response_model=None,
    )
    def get_generation_remediation_task(
        cx_generation_id: str,
        remediation_action_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        try:
            record = selected_store.get(remediation_action_id)
        except GenerationRemediationError as exc:
            return _remediation_problem_response(request, exc)
        if record is None or record.get("cx_generation_id") != cx_generation_id:
            return _remediation_not_found_response(request, remediation_action_id)
        return record

    @app.patch(
        (
            "/admin/v1/generation-audit/generations/{cx_generation_id}"
            "/remediation-tasks/{remediation_action_id}"
        ),
        response_model=None,
    )
    def update_generation_remediation_task_status(
        cx_generation_id: str,
        remediation_action_id: str,
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
            record = selected_store.get(remediation_action_id)
            if record is None or record.get("cx_generation_id") != cx_generation_id:
                return _remediation_not_found_response(request, remediation_action_id)
            updated = update_generation_remediation_action_status(
                record,
                payload,
                request_id=request_id,
                trace_id=trace_id,
            )
            selected_store.save(updated)
        except GenerationRemediationError as exc:
            return _remediation_problem_response(request, exc)

        emit_generation_remediation_task_event(
            audit_emitter,
            updated,
            event_type=REMEDIATION_TASK_STATUS_UPDATED_EVENT_TYPE,
        )
        return updated


def build_generation_remediation_action_list_response(
    records: list[dict[str, Any]],
    *,
    cx_generation_id: str,
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    items = sorted(
        records,
        key=lambda record: (
            str(record.get("updated_at")),
            str(record.get("remediation_action_id")),
        ),
        reverse=True,
    )
    return {
        "action_list_schema_version": REMEDIATION_ACTION_LIST_SCHEMA_VERSION,
        "cx_generation_id": cx_generation_id,
        "trace_id": trace_id,
        "request_id": request_id,
        "items": items,
        "summary": {
            "count": len(items),
            "by_status": _record_count_by(items, "action_status"),
            "by_action_type": _record_count_by(items, "action_type"),
            "latest_updated_at": items[0]["updated_at"] if items else None,
        },
    }


def update_generation_remediation_action_status(
    record: dict[str, Any],
    payload: dict[str, Any],
    *,
    request_id: str,
    trace_id: str,
    updated_at: str | None = None,
) -> dict[str, Any]:
    try:
        assert_generation_remediation_payload_redaction_safe(payload)
    except GenerationRemediationBoundaryError as exc:
        raise GenerationRemediationError(
            status_code=422,
            error_code="ag.generation_remediation_sensitive_payload",
            detail=str(exc),
        ) from exc
    next_status = required_choice(
        payload,
        "action_status",
        choices=ALLOWED_ACTION_STATUSES,
    )
    current_status = str(record.get("action_status") or "")
    if next_status != current_status and not remediation_transition_allowed(
        current_status,
        next_status,
    ):
        raise GenerationRemediationError(
            status_code=409,
            error_code="ag.generation_remediation_status_transition_invalid",
            detail=f"Cannot move remediation action from {current_status} to {next_status}.",
        )
    updated = dict(record)
    updated["action_status"] = next_status
    updated["request_id"] = required_text({"request_id": request_id}, "request_id")
    updated["trace_id"] = required_text({"trace_id": trace_id}, "trace_id")
    if "result_ref" in payload:
        updated["result_ref"] = result_ref(payload.get("result_ref"))
    if "evidence_hashes" in payload or "evidence_previews" in payload:
        updated["evidence"] = evidence_summary(payload)
    updated["updated_at"] = updated_at or _utc_now()
    return updated


def emit_generation_remediation_task_event(
    audit_emitter: OperationalEventEmitter,
    record: dict[str, Any],
    *,
    event_type: str,
) -> OperationalEventEmitResult:
    owner = record.get("owner_ref") if isinstance(record.get("owner_ref"), dict) else {}
    return audit_emitter.safe_emit(
        event_type=event_type,
        severity="INFO",
        message="Generation remediation task state changed.",
        trace_id=record.get("trace_id"),
        request_id=record.get("request_id"),
        subject_ref={
            "type": "generation_remediation_task",
            "id": str(record["remediation_action_id"]),
        },
        details={
            "cx_generation_id": record.get("cx_generation_id"),
            "remediation_action_id": record.get("remediation_action_id"),
            "action_type": record.get("action_type"),
            "action_status": record.get("action_status"),
            "priority": record.get("priority"),
            "owner_type": owner.get("owner_type"),
            "owner_id": owner.get("owner_id"),
            "source_ref_count": len(record.get("source_refs") or []),
            "result_ref_present": record.get("result_ref") is not None,
        },
    )


def build_generation_remediation_action(
    payload: dict[str, Any],
    *,
    cx_generation_id: str,
    request_id: str,
    trace_id: str,
    created_at: str | None = None,
) -> dict[str, Any]:
    try:
        assert_generation_remediation_payload_redaction_safe(payload)
    except GenerationRemediationBoundaryError as exc:
        raise GenerationRemediationError(
            status_code=422,
            error_code="ag.generation_remediation_sensitive_payload",
            detail=str(exc),
        ) from exc
    generation_id = required_text({"cx_generation_id": cx_generation_id}, "cx_generation_id")
    action_type = required_choice(
        payload,
        "action_type",
        choices=ALLOWED_ACTION_TYPES,
    )
    action_status = optional_choice(
        payload.get("action_status"),
        choices=ALLOWED_ACTION_STATUSES,
        default="PROPOSED",
        key="action_status",
    )
    priority = optional_choice(
        payload.get("priority"),
        choices=ALLOWED_PRIORITIES,
        default="NORMAL",
        key="priority",
    )
    tenant_id = optional_text(payload.get("tenant_id"))
    owner = owner_ref(payload.get("owner_ref"), tenant_id=tenant_id)
    reasons = reason_code_list(payload.get("reason_codes"))
    refs = source_ref_list(payload.get("source_refs"))
    evidence = evidence_summary(payload)
    now = created_at or _utc_now()
    action_id = optional_text(payload.get("remediation_action_id")) or str(
        uuid5(
            NAMESPACE_URL,
            (
                "ag-generation-remediation-action:"
                f"{generation_id}:{action_type}:{priority}:{','.join(reasons)}:"
                f"{owner['owner_type']}:{owner['owner_id']}:{request_id}"
            ),
        )
    )
    return {
        "action_schema_version": REMEDIATION_ACTION_SCHEMA_VERSION,
        "remediation_action_id": action_id,
        "cx_generation_id": generation_id,
        "tenant_id": tenant_id,
        "trace_id": required_text({"trace_id": trace_id}, "trace_id"),
        "request_id": required_text({"request_id": request_id}, "request_id"),
        "action_type": action_type,
        "action_status": action_status,
        "priority": priority,
        "reason_codes": reasons,
        "owner_ref": owner,
        "source_refs": refs,
        "evidence": evidence,
        "result_ref": result_ref(payload.get("result_ref")),
        "metadata": {
            "action_source": optional_choice(
                payload.get("action_source"),
                choices=ALLOWED_ACTION_SOURCES,
                default="manual",
                key="action_source",
            ),
            "raw_prompt_stored": False,
            "raw_generation_output_stored": False,
            "raw_source_document_text_stored": False,
            "raw_feedback_comment_stored": False,
            "raw_operator_note_stored": False,
            "free_text_storage": "hash_and_short_preview_only",
        },
        "created_at": now,
        "updated_at": now,
    }


def build_generation_remediation_candidate_projection(
    *,
    rollup_items: Iterable[Mapping[str, Any]],
    request_id: str,
    trace_id: str,
    checked_at: str | None = None,
    limit: int = DEFAULT_CANDIDATE_ITEMS,
) -> dict[str, Any]:
    rollup_items_list = list(rollup_items)
    candidates = [
        candidate
        for item in rollup_items_list
        if (candidate := _candidate_from_rollup_item(item, request_id, trace_id))
        is not None
    ]
    candidates.sort(key=_candidate_sort_key)
    limited = candidates[:normalize_candidate_limit(limit)]
    return {
        "projection_schema_version": REMEDIATION_CANDIDATE_PROJECTION_SCHEMA_VERSION,
        "checked_at": checked_at or _utc_now(),
        "trace_id": required_text({"trace_id": trace_id}, "trace_id"),
        "request_id": required_text({"request_id": request_id}, "request_id"),
        "items": limited,
        "summary": {
            "candidate_count": len(candidates),
            "returned_count": len(limited),
            "by_action_type": _count_by(limited, ("action", "action_type")),
            "by_priority": _count_by(limited, ("action", "priority")),
            "skipped_count": max(0, len(rollup_items_list) - len(candidates)),
        },
        "redaction_summary": {
            "raw_prompt_included": False,
            "raw_generation_output_included": False,
            "raw_feedback_comment_included": False,
            "raw_operator_note_included": False,
        },
    }


def normalize_candidate_limit(limit: int) -> int:
    if not isinstance(limit, int):
        return DEFAULT_CANDIDATE_ITEMS
    return min(max(limit, 1), MAX_CANDIDATE_ITEMS)


def _candidate_from_rollup_item(
    item: Mapping[str, Any],
    request_id: str,
    trace_id: str,
) -> dict[str, Any] | None:
    cx_generation_id = optional_text(item.get("cx_generation_id"))
    if cx_generation_id is None:
        return None
    attention_status = str(item.get("attention_status") or "OK")
    if attention_status in {"OK", "CLOSED"}:
        return None

    quality = _safe_mapping(item.get("quality"))
    feedback = _safe_mapping(item.get("feedback"))
    disposition = _safe_mapping(item.get("disposition"))
    action_type, candidate_reason = _candidate_action_type(
        quality=quality,
        feedback=feedback,
        disposition=disposition,
        attention_status=attention_status,
    )
    priority = _candidate_priority(
        severity=str(item.get("severity") or "INFO"),
        feedback=feedback,
        disposition=disposition,
        attention_status=attention_status,
    )
    action = build_generation_remediation_action(
        {
            "tenant_id": _candidate_tenant_id(item),
            "action_type": action_type,
            "priority": priority,
            "reason_codes": _candidate_reason_codes(
                action_type=action_type,
                quality=quality,
                feedback=feedback,
                disposition=disposition,
            ),
            "source_refs": _candidate_source_refs(
                cx_generation_id=cx_generation_id,
                feedback=feedback,
                disposition=disposition,
                quality=quality,
            ),
            "evidence_previews": _candidate_evidence_previews(
                candidate_reason=candidate_reason,
                item=item,
            ),
            "action_source": _candidate_action_source(disposition),
        },
        cx_generation_id=cx_generation_id,
        request_id=request_id,
        trace_id=trace_id,
    )
    return {
        "candidate_schema_version": "ag_generation_remediation_candidate.v1",
        "candidate_id": action["remediation_action_id"],
        "cx_generation_id": cx_generation_id,
        "candidate_reason": candidate_reason,
        "action": action,
        "debug_paths": {
            "quality_issue_detail_path": (
                f"/admin/v1/generation-audit/generations/{cx_generation_id}"
                "/quality-issue-detail"
            ),
            "dispositions_path": (
                f"/admin/v1/generation-audit/generations/{cx_generation_id}"
                "/quality-dispositions"
            ),
            "remediation_tasks_path": (
                f"/admin/v1/generation-audit/generations/{cx_generation_id}"
                "/remediation-tasks"
            ),
        },
    }


def _candidate_action_type(
    *,
    quality: Mapping[str, Any],
    feedback: Mapping[str, Any],
    disposition: Mapping[str, Any],
    attention_status: str,
) -> tuple[str, str]:
    latest_action = optional_text(disposition.get("latest_action"))
    if latest_action == "needs_ae_followup":
        return "operator_followup", "operator_requested_ae_followup"
    quality_action = _action_type_from_quality(quality)
    if latest_action == "needs_cx_repair":
        return quality_action or "retry_generation", "operator_requested_cx_repair"
    if latest_action == "escalated":
        return "prompt_policy_review", "operator_escalated_generation_quality"
    if quality_action is not None:
        return quality_action, "quality_signal_requires_repair"
    if _int_value(feedback.get("negative_count")) > 0:
        return "operator_followup", "negative_feedback_needs_triage"
    if attention_status == "IN_PROGRESS":
        return "operator_followup", "open_operator_disposition_in_progress"
    return "operator_followup", "attention_signal_needs_triage"


def _action_type_from_quality(quality: Mapping[str, Any]) -> str | None:
    for value in (
        _list_texts(quality.get("issue_codes"))
        + _list_texts(quality.get("coverage_statuses"))
        + _list_texts(quality.get("boundary_statuses"))
        + _list_texts(quality.get("recommended_actions"))
    ):
        upper_value = value.upper()
        for token, action_type in ISSUE_CODE_ACTION_HINTS:
            if token in upper_value:
                return action_type
    if quality.get("attention_required") is True:
        return "retry_generation"
    return None


def _candidate_priority(
    *,
    severity: str,
    feedback: Mapping[str, Any],
    disposition: Mapping[str, Any],
    attention_status: str,
) -> str:
    latest_status = optional_text(disposition.get("latest_status"))
    if latest_status == "ESCALATED" or severity == "ERROR":
        return "URGENT"
    if _int_value(feedback.get("negative_count")) >= 2:
        return "HIGH"
    if attention_status == "IN_PROGRESS":
        return "HIGH"
    if severity == "WARNING":
        return "HIGH"
    return "NORMAL"


def _candidate_reason_codes(
    *,
    action_type: str,
    quality: Mapping[str, Any],
    feedback: Mapping[str, Any],
    disposition: Mapping[str, Any],
) -> list[str]:
    reasons: list[str] = []
    if _int_value(feedback.get("negative_count")) > 0:
        reasons.append("negative_user_feedback")
    if optional_text(disposition.get("latest_disposition_id")) is not None:
        reasons.append("operator_requested_repair")
    if action_type == "citation_repair":
        reasons.append("citation_quality")
    elif action_type == "retrieval_repair":
        reasons.append("retrieval_quality")
    elif action_type == "retry_generation":
        reasons.append("generation_quality")
    elif action_type == "prompt_policy_review":
        reasons.append("policy_review")
    if any("METADATA" in code.upper() for code in _list_texts(quality.get("issue_codes"))):
        reasons.append("metadata_gap")
    return list(dict.fromkeys(reasons or ["other"]))


def _candidate_source_refs(
    *,
    cx_generation_id: str,
    feedback: Mapping[str, Any],
    disposition: Mapping[str, Any],
    quality: Mapping[str, Any],
) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    if _int_value(quality.get("count")) > 0:
        refs.append(
            {
                "source_service": "nex-ag",
                "ref_type": "generation_quality",
                "ref_id": cx_generation_id,
                "relation": "caused_by",
            }
        )
    if (feedback_id := optional_text(feedback.get("latest_feedback_id"))) is not None:
        refs.append(
            {
                "source_service": "nex-ae-api",
                "ref_type": "feedback",
                "ref_id": feedback_id,
                "relation": "caused_by",
            }
        )
    if (
        disposition_id := optional_text(disposition.get("latest_disposition_id"))
    ) is not None:
        refs.append(
            {
                "source_service": "nex-ag",
                "ref_type": "operator_disposition",
                "ref_id": disposition_id,
                "relation": "recommended_by",
            }
        )
    return refs


def _candidate_evidence_previews(
    *,
    candidate_reason: str,
    item: Mapping[str, Any],
) -> list[str]:
    quality = _safe_mapping(item.get("quality"))
    feedback = _safe_mapping(item.get("feedback"))
    parts = [
        f"reason={candidate_reason}",
        f"attention={item.get('attention_status') or 'UNKNOWN'}",
        f"severity={item.get('severity') or 'INFO'}",
    ]
    issue_codes = _list_texts(quality.get("issue_codes"))
    if issue_codes:
        parts.append(f"issues={','.join(issue_codes[:3])}")
    negative_count = _int_value(feedback.get("negative_count"))
    if negative_count:
        parts.append(f"negative_feedback={negative_count}")
    return [" ".join(parts)]


def _candidate_action_source(disposition: Mapping[str, Any]) -> str:
    if optional_text(disposition.get("latest_disposition_id")) is not None:
        return "operator_disposition"
    return "candidate_projection"


def _candidate_tenant_id(item: Mapping[str, Any]) -> str | None:
    return optional_text(item.get("tenant_id"))


def _candidate_sort_key(candidate: Mapping[str, Any]) -> tuple[int, str, str]:
    action = _safe_mapping(candidate.get("action"))
    priority_order = {"URGENT": 0, "HIGH": 1, "NORMAL": 2, "LOW": 3}
    priority = str(action.get("priority") or "NORMAL")
    action_type = str(action.get("action_type") or "")
    generation_id = str(candidate.get("cx_generation_id") or "")
    return (priority_order.get(priority, 4), action_type, generation_id)


def _count_by(items: list[Mapping[str, Any]], path: tuple[str, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value: Any = item
        for key in path:
            value = value.get(key) if isinstance(value, Mapping) else None
        label = str(value or "unknown")
        counts[label] = counts.get(label, 0) + 1
    return dict(sorted(counts.items()))


def _safe_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list_texts(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _record_count_by(records: list[Mapping[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        label = str(record.get(key) or "UNKNOWN")
        counts[label] = counts.get(label, 0) + 1
    return dict(sorted(counts.items()))


def _remediation_upsert_sql(dialect_name: str) -> str:
    owner_ref_expr = _json_param_expr("owner_ref", dialect_name)
    reason_codes_expr = _json_param_expr("reason_codes", dialect_name)
    source_refs_expr = _json_param_expr("source_refs", dialect_name)
    evidence_expr = _json_param_expr("evidence", dialect_name)
    result_ref_expr = _json_param_expr("result_ref", dialect_name)
    metadata_expr = _json_param_expr("metadata", dialect_name)
    return f"""
        INSERT INTO ag_generation_remediation_tasks (
            remediation_action_id,
            action_schema_version,
            cx_generation_id,
            tenant_id,
            trace_id,
            request_id,
            action_type,
            action_status,
            priority,
            owner_type,
            owner_id,
            owner_tenant_id,
            owner_ref,
            reason_codes,
            source_refs,
            evidence,
            result_ref,
            metadata,
            created_at,
            updated_at
        )
        VALUES (
            :remediation_action_id,
            :action_schema_version,
            :cx_generation_id,
            :tenant_id,
            :trace_id,
            :request_id,
            :action_type,
            :action_status,
            :priority,
            :owner_type,
            :owner_id,
            :owner_tenant_id,
            {owner_ref_expr},
            {reason_codes_expr},
            {source_refs_expr},
            {evidence_expr},
            {result_ref_expr},
            {metadata_expr},
            :created_at,
            :updated_at
        )
        ON CONFLICT (remediation_action_id) DO UPDATE SET
            tenant_id = excluded.tenant_id,
            trace_id = excluded.trace_id,
            request_id = excluded.request_id,
            action_type = excluded.action_type,
            action_status = excluded.action_status,
            priority = excluded.priority,
            owner_type = excluded.owner_type,
            owner_id = excluded.owner_id,
            owner_tenant_id = excluded.owner_tenant_id,
            owner_ref = excluded.owner_ref,
            reason_codes = excluded.reason_codes,
            source_refs = excluded.source_refs,
            evidence = excluded.evidence,
            result_ref = excluded.result_ref,
            metadata = excluded.metadata,
            updated_at = excluded.updated_at
    """


def _remediation_select_sql(where_clause: str) -> str:
    return f"""
        SELECT
            action_schema_version,
            remediation_action_id,
            cx_generation_id,
            tenant_id,
            trace_id,
            request_id,
            action_type,
            action_status,
            priority,
            owner_ref,
            reason_codes,
            source_refs,
            evidence,
            result_ref,
            metadata,
            created_at,
            updated_at
        FROM ag_generation_remediation_tasks
        WHERE {where_clause}
    """


def _remediation_record_params(record: dict[str, Any]) -> dict[str, Any]:
    owner = record["owner_ref"]
    return {
        **record,
        "owner_type": owner["owner_type"],
        "owner_id": owner["owner_id"],
        "owner_tenant_id": owner.get("tenant_id"),
        "owner_ref": json.dumps(record["owner_ref"]),
        "reason_codes": json.dumps(record["reason_codes"]),
        "source_refs": json.dumps(record["source_refs"]),
        "evidence": json.dumps(record["evidence"]),
        "result_ref": (
            json.dumps(record["result_ref"])
            if record.get("result_ref") is not None
            else None
        ),
        "metadata": json.dumps(record["metadata"]),
    }


def _remediation_record_from_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    return {
        "action_schema_version": data["action_schema_version"],
        "remediation_action_id": data["remediation_action_id"],
        "cx_generation_id": data["cx_generation_id"],
        "tenant_id": data["tenant_id"],
        "trace_id": data["trace_id"],
        "request_id": data["request_id"],
        "action_type": data["action_type"],
        "action_status": data["action_status"],
        "priority": data["priority"],
        "owner_ref": _json_value(data["owner_ref"], {}),
        "reason_codes": _json_value(data["reason_codes"], []),
        "source_refs": _json_value(data["source_refs"], []),
        "evidence": _json_value(data["evidence"], {}),
        "result_ref": _json_value(data["result_ref"], None),
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


def _store_unavailable_error() -> GenerationRemediationError:
    return GenerationRemediationError(
        status_code=503,
        error_code="ag.generation_remediation_store_unavailable",
        detail="Generation remediation task store is unavailable.",
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


def _remediation_problem_response(
    request: Request,
    exc: GenerationRemediationError,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Generation remediation task error",
        detail=exc.detail,
        type_uri="https://nex-platform.local/problems/generation-remediation-task",
    )


def _remediation_not_found_response(
    request: Request,
    remediation_action_id: str,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=404,
        error_code="ag.generation_remediation_task_not_found",
        title="Generation remediation task not found",
        detail=f"Remediation task was not found: {remediation_action_id}",
        type_uri=(
            "https://nex-platform.local/problems/"
            "generation-remediation-task-not-found"
        ),
    )


def owner_ref(value: Any, *, tenant_id: str | None) -> dict[str, str | None]:
    if value is None:
        return {
            "owner_type": "service",
            "owner_id": "nex-ag",
            "tenant_id": tenant_id,
        }
    if not isinstance(value, dict):
        raise _error("owner_ref_invalid", "owner_ref must be an object when supplied.")
    return {
        "owner_type": required_choice(
            value,
            "owner_type",
            choices=("service", "user"),
        ),
        "owner_id": required_text(value, "owner_id"),
        "tenant_id": optional_text(value.get("tenant_id")) or tenant_id,
    }


def reason_code_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise _error("reason_codes_invalid", "reason_codes must be a list when supplied.")
    reasons: list[str] = []
    for reason in value:
        if not isinstance(reason, str) or not reason.strip():
            raise _error("reason_code_invalid", "reason code must be a non-empty string.")
        normalized = reason.strip()
        if normalized not in ALLOWED_REASON_CODES:
            raise _error("reason_code_unsupported", f"unsupported reason code: {normalized}")
        if normalized not in reasons:
            reasons.append(normalized)
    return reasons


def source_ref_list(value: Any) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise _error("source_refs_invalid", "source_refs must be a list when supplied.")
    refs: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            raise _error("source_ref_invalid", "source ref must be an object.")
        refs.append(
            {
                "source_service": required_choice(
                    item,
                    "source_service",
                    choices=ALLOWED_SOURCE_SERVICES,
                ),
                "ref_type": required_choice(
                    item,
                    "ref_type",
                    choices=ALLOWED_REF_TYPES,
                ),
                "ref_id": required_text(item, "ref_id"),
                "relation": required_choice(
                    item,
                    "relation",
                    choices=ALLOWED_REF_RELATIONS,
                ),
            }
        )
    return refs


def result_ref(value: Any) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise _error("result_ref_invalid", "result_ref must be an object when supplied.")
    return {
        "source_service": required_choice(
            value,
            "source_service",
            choices=ALLOWED_RESULT_SOURCE_SERVICES,
        ),
        "ref_type": required_choice(
            value,
            "ref_type",
            choices=("repair_execution", "generation_quality"),
        ),
        "ref_id": required_text(value, "ref_id"),
        "relation": "result_of",
    }


def evidence_summary(payload: dict[str, Any]) -> dict[str, Any]:
    previews = preview_list(payload.get("evidence_previews"))
    hashes = hash_list(payload.get("evidence_hashes"))
    if not hashes and previews:
        hashes = [sha256_text("|".join(previews))]
    return {
        "evidence_hashes": hashes,
        "evidence_previews": previews,
        "raw_evidence_stored": False,
    }


def hash_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise _error("evidence_hashes_invalid", "evidence_hashes must be a list.")
    hashes: list[str] = []
    for item in value:
        normalized = required_text({"evidence_hash": item}, "evidence_hash")
        if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
            raise _error(
                "evidence_hash_invalid",
                "evidence hash must be a lowercase SHA-256 hex digest.",
            )
        if normalized not in hashes:
            hashes.append(normalized)
    return hashes


def preview_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise _error("evidence_previews_invalid", "evidence_previews must be a list.")
    previews: list[str] = []
    for item in value:
        preview = required_text({"evidence_preview": item}, "evidence_preview")
        normalized = preview[:MAX_EVIDENCE_PREVIEW_LENGTH]
        if normalized not in previews:
            previews.append(normalized)
    return previews


def required_choice(
    payload: dict[str, Any],
    key: str,
    *,
    choices: tuple[str, ...],
) -> str:
    value = required_text(payload, key)
    if value not in choices:
        raise _error(f"{key}_unsupported", f"unsupported {key}: {value}")
    return value


def optional_choice(
    value: Any,
    *,
    choices: tuple[str, ...],
    default: str,
    key: str,
) -> str:
    if value is None:
        return default
    if not isinstance(value, str) or not value.strip():
        raise _error(f"{key}_invalid", f"{key} must be a non-empty string.")
    normalized = value.strip()
    if normalized not in choices:
        raise _error(f"{key}_unsupported", f"unsupported {key}: {normalized}")
    return normalized


def required_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _error(f"{key}_required", f"{key} is required.")
    return value.strip()


def optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _error(code: str, detail: str) -> GenerationRemediationError:
    return GenerationRemediationError(
        status_code=422,
        error_code=f"ag.generation_remediation_{code}",
        detail=detail,
    )
