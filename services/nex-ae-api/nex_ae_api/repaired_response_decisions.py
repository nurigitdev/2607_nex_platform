from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
    validate_authorization_header,
)
from nex_ae_api.repaired_responses import (
    RepairedResponseHandoffError,
    default_repaired_response_handoff_store,
    optional_text,
    validate_repaired_response_handoff_record,
)


AE_REPAIRED_RESPONSE_DECISION_SCHEMA_VERSION = "ae_repaired_response_decision.v1"
AE_REPAIRED_RESPONSE_DECISION_COLLECTION_SCHEMA_VERSION = (
    "ae_repaired_response_decision_collection.v1"
)
DEFAULT_DECISION_STATUS = "RECORDED"
DECISION_ACTION_ACCEPT_REPAIR = "accept_repair"
DECISION_ACTION_KEEP_ORIGINAL = "keep_original"
SUPPORTED_DECISION_ACTIONS = (
    DECISION_ACTION_ACCEPT_REPAIR,
    DECISION_ACTION_KEEP_ORIGINAL,
)
SUPPORTED_DECISION_REASON_CODES = (
    "citation_fixed",
    "answer_improved",
    "prefer_repaired",
    "prefer_original",
    "repair_not_needed",
    "repair_unsatisfactory",
    "other",
)
DEFAULT_REASON_BY_ACTION = {
    DECISION_ACTION_ACCEPT_REPAIR: "prefer_repaired",
    DECISION_ACTION_KEEP_ORIGINAL: "prefer_original",
}
SUPPORTED_DECISION_SUBMITTERS = (
    "chat_review",
    "document_detail",
    "operator_replay",
)
MAX_DECISION_COMMENT_PREVIEW_LENGTH = 240
JSON_STORAGE_FIELDS = (
    "actor_claims_ref",
    "decision_reason_codes",
    "metadata",
)
SENSITIVE_DECISION_KEY_PARTS = (
    "access_token",
    "api_key",
    "authorization",
    "credential",
    "database_url",
    "messages",
    "model_path",
    "password",
    "passwd",
    "provider_endpoint",
    "provider_url",
    "raw_evidence",
    "raw_generation_output",
    "raw_output",
    "raw_prompt",
    "raw_source",
    "raw_text",
    "secret",
    "source_text",
    "storage_path",
    "token",
)
ALLOWED_FALSE_METADATA_FLAGS = {
    "raw_prompt_stored",
    "raw_generation_output_stored",
    "raw_source_text_stored",
    "raw_evidence_stored",
}


@dataclass
class RepairedResponseDecisionStore:
    records: dict[str, dict[str, Any]] = field(default_factory=dict)
    decision_ids_by_handoff: dict[str, list[str]] = field(default_factory=dict)
    decision_ids_by_interaction: dict[str, list[str]] = field(default_factory=dict)

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        validated = validate_repaired_response_decision_record(record)
        decision_id = validated["repaired_response_decision_id"]
        self.records[decision_id] = validated
        _append_unique(
            self.decision_ids_by_handoff.setdefault(
                validated["repaired_response_handoff_id"],
                [],
            ),
            decision_id,
        )
        _append_unique(
            self.decision_ids_by_interaction.setdefault(
                validated["interaction_id"],
                [],
            ),
            decision_id,
        )
        return validated

    def get(self, repaired_response_decision_id: str) -> dict[str, Any] | None:
        return self.records.get(repaired_response_decision_id)

    def list_for_handoff(self, repaired_response_handoff_id: str) -> list[dict[str, Any]]:
        return [
            self.records[decision_id]
            for decision_id in self.decision_ids_by_handoff.get(
                repaired_response_handoff_id,
                [],
            )
            if decision_id in self.records
        ]

    def list_for_interaction(self, interaction_id: str) -> list[dict[str, Any]]:
        return [
            self.records[decision_id]
            for decision_id in self.decision_ids_by_interaction.get(interaction_id, [])
            if decision_id in self.records
        ]


class SqlAlchemyRepairedResponseDecisionStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        validated = validate_repaired_response_decision_record(record)
        try:
            with self._session_factory() as session:
                session.execute(
                    text(_decision_upsert_sql(_dialect_name(session))),
                    _decision_record_params(validated),
                )
                session.commit()
            return validated
        except SQLAlchemyError as exc:
            raise RepairedResponseDecisionError(
                status_code=503,
                error_code="ae.repaired_response_decision_store_unavailable",
                detail="AE repaired response decision store is unavailable.",
                retryable=True,
            ) from exc

    def get(self, repaired_response_decision_id: str) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(
                        text(
                            _decision_select_sql(
                                "repaired_response_decision_id = "
                                ":repaired_response_decision_id"
                            )
                        ),
                        {
                            "repaired_response_decision_id": (
                                repaired_response_decision_id
                            )
                        },
                    )
                    .mappings()
                    .first()
                )
            return _decision_record_from_row(row) if row is not None else None
        except SQLAlchemyError as exc:
            raise RepairedResponseDecisionError(
                status_code=503,
                error_code="ae.repaired_response_decision_store_unavailable",
                detail="AE repaired response decision store is unavailable.",
                retryable=True,
            ) from exc

    def list_for_handoff(self, repaired_response_handoff_id: str) -> list[dict[str, Any]]:
        return self._list(
            "repaired_response_handoff_id = :repaired_response_handoff_id "
            "ORDER BY created_at DESC, repaired_response_decision_id ASC",
            {"repaired_response_handoff_id": repaired_response_handoff_id},
        )

    def list_for_interaction(self, interaction_id: str) -> list[dict[str, Any]]:
        return self._list(
            "interaction_id = :interaction_id "
            "ORDER BY created_at DESC, repaired_response_decision_id ASC",
            {"interaction_id": interaction_id},
        )

    def delete(self, repaired_response_decision_id: str) -> int:
        try:
            with self._session_factory() as session:
                result = session.execute(
                    text(
                        "DELETE FROM ae_repaired_response_decisions "
                        "WHERE repaired_response_decision_id = "
                        ":repaired_response_decision_id"
                    ),
                    {
                        "repaired_response_decision_id": (
                            repaired_response_decision_id
                        )
                    },
                )
                session.commit()
                return int(result.rowcount or 0)
        except SQLAlchemyError as exc:
            raise RepairedResponseDecisionError(
                status_code=503,
                error_code="ae.repaired_response_decision_store_unavailable",
                detail="AE repaired response decision store is unavailable.",
                retryable=True,
            ) from exc

    def _list(
        self,
        where_clause: str,
        params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        try:
            with self._session_factory() as session:
                rows = (
                    session.execute(text(_decision_select_sql(where_clause)), params)
                    .mappings()
                    .all()
                )
            return [_decision_record_from_row(row) for row in rows]
        except SQLAlchemyError as exc:
            raise RepairedResponseDecisionError(
                status_code=503,
                error_code="ae.repaired_response_decision_store_unavailable",
                detail="AE repaired response decision store is unavailable.",
                retryable=True,
            ) from exc


@dataclass
class RepairedResponseDecisionError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


DEFAULT_REPAIRED_RESPONSE_DECISION_STORE = RepairedResponseDecisionStore()


def default_repaired_response_decision_store(app: Any) -> Any:
    persistence = getattr(app.state, "nex_persistence", None)
    session_factory = getattr(persistence, "api_session_factory", None)
    if session_factory is not None:
        return SqlAlchemyRepairedResponseDecisionStore(session_factory)
    return DEFAULT_REPAIRED_RESPONSE_DECISION_STORE


def register_repaired_response_decision_routes(
    app: FastAPI,
    *,
    handoff_store: Any | None = None,
    decision_store: Any | None = None,
) -> None:
    selected_handoff_store = handoff_store or default_repaired_response_handoff_store(app)
    selected_decision_store = decision_store or default_repaired_response_decision_store(app)

    @app.post(
        "/api/v1/chat/interactions/{interaction_id}/repaired-response-handoffs/"
        "{repaired_response_handoff_id}/decisions",
        response_model=None,
        status_code=202,
    )
    def create_repaired_response_decision(
        interaction_id: str,
        repaired_response_handoff_id: str,
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_ae_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        try:
            handoff = _handoff_for_decision_route(
                selected_handoff_store,
                interaction_id=interaction_id,
                repaired_response_handoff_id=repaired_response_handoff_id,
            )
            record = build_repaired_response_decision_record(
                handoff_record=handoff,
                decision_payload=payload,
                request_id=request_id_from_headers(request),
                trace_id=payload.get("trace_id") or trace_id_from_headers(request),
            )
            return selected_decision_store.save(record)
        except (RepairedResponseDecisionError, RepairedResponseHandoffError) as exc:
            return _decision_problem_response(request, exc)

    @app.get(
        "/api/v1/chat/interactions/{interaction_id}/repaired-response-handoffs/"
        "{repaired_response_handoff_id}/decisions",
        response_model=None,
    )
    def list_repaired_response_decisions(
        interaction_id: str,
        repaired_response_handoff_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_ae_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        try:
            _handoff_for_decision_route(
                selected_handoff_store,
                interaction_id=interaction_id,
                repaired_response_handoff_id=repaired_response_handoff_id,
            )
            records = selected_decision_store.list_for_handoff(
                repaired_response_handoff_id
            )
            return build_repaired_response_decision_collection(
                records,
                interaction_id=interaction_id,
                repaired_response_handoff_id=repaired_response_handoff_id,
            )
        except (RepairedResponseDecisionError, RepairedResponseHandoffError) as exc:
            return _decision_problem_response(request, exc)

    @app.get(
        "/api/v1/chat/interactions/{interaction_id}/repaired-response-handoffs/"
        "{repaired_response_handoff_id}/decisions/{repaired_response_decision_id}",
        response_model=None,
    )
    def get_repaired_response_decision(
        interaction_id: str,
        repaired_response_handoff_id: str,
        repaired_response_decision_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_ae_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        try:
            _handoff_for_decision_route(
                selected_handoff_store,
                interaction_id=interaction_id,
                repaired_response_handoff_id=repaired_response_handoff_id,
            )
            record = selected_decision_store.get(repaired_response_decision_id)
            if (
                record is None
                or record["interaction_id"] != interaction_id
                or record["repaired_response_handoff_id"] != repaired_response_handoff_id
            ):
                raise RepairedResponseDecisionError(
                    status_code=404,
                    error_code="ae.repaired_response_decision_not_found",
                    detail=(
                        "Repaired response decision was not found: "
                        f"{repaired_response_decision_id}"
                    ),
                )
            return record
        except (RepairedResponseDecisionError, RepairedResponseHandoffError) as exc:
            return _decision_problem_response(request, exc)


def build_repaired_response_decision_record(
    *,
    handoff_record: Mapping[str, Any],
    decision_payload: Mapping[str, Any],
    request_id: str,
    trace_id: str,
    created_at: str | None = None,
) -> dict[str, Any]:
    try:
        handoff = validate_repaired_response_handoff_record(handoff_record)
    except RepairedResponseHandoffError as exc:
        raise RepairedResponseDecisionError(
            status_code=422,
            error_code="ae.repaired_response_decision_handoff_invalid",
            detail=str(exc),
        ) from exc
    assert_repaired_response_decision_payload_redaction_safe(decision_payload)
    _validate_decision_payload_scope(decision_payload, handoff)
    action = decision_action_from_payload(decision_payload)
    actor = actor_claims_ref_from_decision_payload(decision_payload, handoff)
    reason_codes = decision_reason_codes_from_payload(decision_payload, action=action)
    comment = optional_text(decision_payload.get("decision_comment"))
    comment_hash = sha256_text(comment) if comment is not None else None
    source = _mapping(handoff.get("source"))
    parent_generation_id = source["parent_cx_generation_id"]
    repair_generation_id = source["repair_cx_generation_id"]
    selected_generation_id = selected_cx_generation_id_for_action(
        action,
        parent_cx_generation_id=parent_generation_id,
        repair_cx_generation_id=repair_generation_id,
    )
    rejected_generation_id = (
        parent_generation_id
        if selected_generation_id == repair_generation_id
        else repair_generation_id
    )
    selected_request_id = optional_text(decision_payload.get("decision_request_id"))
    if selected_request_id is None:
        selected_request_id = str(
            uuid5(
                NAMESPACE_URL,
                (
                    "ae-repaired-response-decision-request:"
                    f"{handoff['repaired_response_handoff_id']}:{actor['actor_id']}:"
                    f"{action}:{request_id}"
                ),
            )
        )
    decision_id = optional_text(
        decision_payload.get("repaired_response_decision_id")
    ) or str(uuid5(NAMESPACE_URL, f"ae-repaired-response-decision:{selected_request_id}"))
    now = created_at or _utc_now()
    record = {
        "decision_schema_version": AE_REPAIRED_RESPONSE_DECISION_SCHEMA_VERSION,
        "repaired_response_decision_id": decision_id,
        "decision_request_id": selected_request_id,
        "decision_status": DEFAULT_DECISION_STATUS,
        "decision_action": action,
        "repaired_response_handoff_id": handoff["repaired_response_handoff_id"],
        "handoff_request_id": handoff["handoff_request_id"],
        "trace_id": _required_text({"trace_id": trace_id}, "trace_id", "ae.trace_id_required"),
        "request_id": _required_text(
            {"request_id": request_id},
            "request_id",
            "ae.request_id_required",
        ),
        "tenant_id": handoff["tenant_id"],
        "workspace_id": handoff["workspace_id"],
        "owner_user_id": handoff["owner_user_id"],
        "chat_document_id": handoff["chat_document_id"],
        "interaction_id": handoff["interaction_id"],
        "actor_claims_ref": actor,
        "parent_cx_generation_id": parent_generation_id,
        "repair_cx_generation_id": repair_generation_id,
        "selected_cx_generation_id": selected_generation_id,
        "rejected_cx_generation_id": rejected_generation_id,
        "remediation_action_id": source["remediation_action_id"],
        "decision_reason_codes": reason_codes,
        "decision_comment_hash": comment_hash,
        "decision_comment_preview": (
            comment[:MAX_DECISION_COMMENT_PREVIEW_LENGTH]
            if comment is not None
            else None
        ),
        "metadata": {
            "submitted_via": submitted_via_from_payload(decision_payload),
            "raw_prompt_stored": False,
            "raw_generation_output_stored": False,
            "raw_source_text_stored": False,
            "raw_evidence_stored": False,
            "free_text_comment_storage": "hash_and_short_preview_only",
            "parent_generation_mutated": False,
        },
        "created_at": now,
        "updated_at": now,
    }
    return validate_repaired_response_decision_record(record)


def build_repaired_response_decision_collection(
    records: list[Mapping[str, Any]],
    *,
    interaction_id: str,
    repaired_response_handoff_id: str,
    checked_at: str | None = None,
) -> dict[str, Any]:
    path_interaction_id = _required_text(
        {"interaction_id": interaction_id},
        "interaction_id",
        "ae.repaired_response_decision_interaction_id_required",
    )
    path_handoff_id = _required_text(
        {"repaired_response_handoff_id": repaired_response_handoff_id},
        "repaired_response_handoff_id",
        "ae.repaired_response_decision_handoff_id_required",
    )
    items = [
        validate_repaired_response_decision_record(record)
        for record in records
        if record.get("interaction_id") == path_interaction_id
        and record.get("repaired_response_handoff_id") == path_handoff_id
    ]
    items.sort(
        key=lambda item: (str(item.get("created_at", "")), item["repaired_response_decision_id"]),
        reverse=True,
    )
    return {
        "collection_schema_version": (
            AE_REPAIRED_RESPONSE_DECISION_COLLECTION_SCHEMA_VERSION
        ),
        "interaction_id": path_interaction_id,
        "repaired_response_handoff_id": path_handoff_id,
        "items": items,
        "item_count": len(items),
        "checked_at": checked_at or _utc_now(),
    }


def validate_repaired_response_decision_record(record: Mapping[str, Any]) -> dict[str, Any]:
    if record.get("decision_schema_version") != (
        AE_REPAIRED_RESPONSE_DECISION_SCHEMA_VERSION
    ):
        raise RepairedResponseDecisionError(
            status_code=422,
            error_code="ae.repaired_response_decision_schema_invalid",
            detail="AE repaired response decision schema version is invalid.",
        )
    if record.get("decision_status") != DEFAULT_DECISION_STATUS:
        raise RepairedResponseDecisionError(
            status_code=422,
            error_code="ae.repaired_response_decision_status_invalid",
            detail="AE repaired response decision status is invalid.",
        )
    action = _required_text(
        record,
        "decision_action",
        "ae.repaired_response_decision_action_required",
    )
    if action not in SUPPORTED_DECISION_ACTIONS:
        raise RepairedResponseDecisionError(
            status_code=422,
            error_code="ae.repaired_response_decision_action_invalid",
            detail=f"Unsupported repaired response decision action: {action}",
        )
    selected = _required_text(
        record,
        "selected_cx_generation_id",
        "ae.repaired_response_decision_generation_required",
    )
    expected_selected = selected_cx_generation_id_for_action(
        action,
        parent_cx_generation_id=_required_text(
            record,
            "parent_cx_generation_id",
            "ae.repaired_response_decision_generation_required",
        ),
        repair_cx_generation_id=_required_text(
            record,
            "repair_cx_generation_id",
            "ae.repaired_response_decision_generation_required",
        ),
    )
    if selected != expected_selected:
        raise RepairedResponseDecisionError(
            status_code=409,
            error_code="ae.repaired_response_decision_generation_mismatch",
            detail="AE repaired response decision selected generation is invalid.",
        )
    reason_codes = decision_reason_codes_from_payload(
        {"decision_reason_codes": record.get("decision_reason_codes")},
        action=action,
    )
    metadata = _mapping(record.get("metadata"))
    if metadata.get("submitted_via") not in SUPPORTED_DECISION_SUBMITTERS:
        raise RepairedResponseDecisionError(
            status_code=422,
            error_code="ae.repaired_response_decision_submitter_invalid",
            detail="AE repaired response decision submitter is invalid.",
        )
    for key in ALLOWED_FALSE_METADATA_FLAGS:
        if metadata.get(key) is not False:
            raise RepairedResponseDecisionError(
                status_code=422,
                error_code="ae.repaired_response_decision_metadata_invalid",
                detail="AE repaired response decision metadata flags must be false.",
            )
    if metadata.get("parent_generation_mutated") is not False:
        raise RepairedResponseDecisionError(
            status_code=422,
            error_code="ae.repaired_response_decision_parent_mutation_forbidden",
            detail="AE repaired response decision cannot mutate parent generation.",
        )
    sanitized = dict(record)
    sanitized["decision_reason_codes"] = reason_codes
    assert_repaired_response_decision_payload_redaction_safe(sanitized)
    return sanitized


def decision_action_from_payload(payload: Mapping[str, Any]) -> str:
    action = optional_text(payload.get("decision_action"))
    if action is None:
        raise RepairedResponseDecisionError(
            status_code=422,
            error_code="ae.repaired_response_decision_action_required",
            detail="decision_action is required.",
        )
    if action not in SUPPORTED_DECISION_ACTIONS:
        raise RepairedResponseDecisionError(
            status_code=422,
            error_code="ae.repaired_response_decision_action_invalid",
            detail=f"Unsupported repaired response decision action: {action}",
        )
    return action


def decision_reason_codes_from_payload(
    payload: Mapping[str, Any],
    *,
    action: str,
) -> list[str]:
    raw_codes = payload.get("decision_reason_codes")
    if raw_codes in (None, ""):
        return [DEFAULT_REASON_BY_ACTION[action]]
    if not isinstance(raw_codes, list):
        raise RepairedResponseDecisionError(
            status_code=422,
            error_code="ae.repaired_response_decision_reason_codes_invalid",
            detail="decision_reason_codes must be a list.",
        )
    result: list[str] = []
    for raw_code in raw_codes:
        code = optional_text(raw_code)
        if code is None:
            continue
        if code not in SUPPORTED_DECISION_REASON_CODES:
            raise RepairedResponseDecisionError(
                status_code=422,
                error_code="ae.repaired_response_decision_reason_code_invalid",
                detail=f"Unsupported repaired response decision reason code: {code}",
            )
        _append_unique(result, code)
    return result or [DEFAULT_REASON_BY_ACTION[action]]


def actor_claims_ref_from_decision_payload(
    payload: Mapping[str, Any],
    handoff: Mapping[str, Any],
) -> dict[str, str]:
    actor = _mapping(payload.get("actor_claims_ref")) or _mapping(
        handoff.get("actor_claims_ref")
    )
    actor_type = optional_text(actor.get("actor_type")) or "user"
    actor_id = optional_text(actor.get("actor_id")) or handoff["owner_user_id"]
    tenant_id = optional_text(actor.get("tenant_id")) or handoff["tenant_id"]
    if tenant_id != handoff["tenant_id"]:
        raise RepairedResponseDecisionError(
            status_code=409,
            error_code="ae.repaired_response_decision_actor_scope_mismatch",
            detail="Decision actor tenant does not match repaired response handoff.",
        )
    return {"actor_type": actor_type, "actor_id": actor_id, "tenant_id": tenant_id}


def selected_cx_generation_id_for_action(
    action: str,
    *,
    parent_cx_generation_id: str,
    repair_cx_generation_id: str,
) -> str:
    if action == DECISION_ACTION_ACCEPT_REPAIR:
        return repair_cx_generation_id
    if action == DECISION_ACTION_KEEP_ORIGINAL:
        return parent_cx_generation_id
    raise RepairedResponseDecisionError(
        status_code=422,
        error_code="ae.repaired_response_decision_action_invalid",
        detail=f"Unsupported repaired response decision action: {action}",
    )


def submitted_via_from_payload(payload: Mapping[str, Any]) -> str:
    submitted_via = optional_text(payload.get("submitted_via")) or "chat_review"
    if submitted_via not in SUPPORTED_DECISION_SUBMITTERS:
        raise RepairedResponseDecisionError(
            status_code=422,
            error_code="ae.repaired_response_decision_submitter_invalid",
            detail=f"Unsupported repaired response decision submitter: {submitted_via}",
        )
    return submitted_via


def assert_repaired_response_decision_payload_redaction_safe(payload: Any) -> None:
    sensitive_keys = find_sensitive_repaired_response_decision_keys(payload)
    if sensitive_keys:
        raise RepairedResponseDecisionError(
            status_code=422,
            error_code="ae.repaired_response_decision_sensitive_payload",
            detail=(
                "AE repaired response decision contains sensitive keys: "
                f"{', '.join(sensitive_keys)}"
            ),
        )


def find_sensitive_repaired_response_decision_keys(payload: Any) -> list[str]:
    found: set[str] = set()

    def visit(value: Any, path: str) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                key_text = str(key)
                child_path = f"{path}.{key_text}" if path else key_text
                if _sensitive_key_forbidden(key_text.lower(), child):
                    found.add(child_path)
                visit(child, child_path)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f"{path}[{index}]")

    visit(payload, "")
    return sorted(found)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _validate_decision_payload_scope(
    payload: Mapping[str, Any],
    handoff: Mapping[str, Any],
) -> None:
    for field_name in (
        "tenant_id",
        "workspace_id",
        "owner_user_id",
        "chat_document_id",
        "interaction_id",
        "repaired_response_handoff_id",
    ):
        payload_value = optional_text(payload.get(field_name))
        if payload_value is not None and payload_value != handoff[field_name]:
            raise RepairedResponseDecisionError(
                status_code=409,
                error_code="ae.repaired_response_decision_scope_mismatch",
                detail=f"{field_name} does not match repaired response handoff.",
            )


def _decision_upsert_sql(dialect_name: str) -> str:
    json_exprs = {
        field_name: _json_param_expr(field_name, dialect_name)
        for field_name in JSON_STORAGE_FIELDS
    }
    return f"""
        INSERT INTO ae_repaired_response_decisions (
            repaired_response_decision_id,
            decision_schema_version,
            decision_request_id,
            decision_status,
            decision_action,
            repaired_response_handoff_id,
            handoff_request_id,
            tenant_id,
            workspace_id,
            owner_user_id,
            chat_document_id,
            interaction_id,
            parent_cx_generation_id,
            repair_cx_generation_id,
            selected_cx_generation_id,
            rejected_cx_generation_id,
            remediation_action_id,
            trace_id,
            request_id,
            actor_claims_ref,
            decision_reason_codes,
            decision_comment_hash,
            decision_comment_preview,
            metadata,
            created_at,
            updated_at
        )
        VALUES (
            :repaired_response_decision_id,
            :decision_schema_version,
            :decision_request_id,
            :decision_status,
            :decision_action,
            :repaired_response_handoff_id,
            :handoff_request_id,
            :tenant_id,
            :workspace_id,
            :owner_user_id,
            :chat_document_id,
            :interaction_id,
            :parent_cx_generation_id,
            :repair_cx_generation_id,
            :selected_cx_generation_id,
            :rejected_cx_generation_id,
            :remediation_action_id,
            :trace_id,
            :request_id,
            {json_exprs["actor_claims_ref"]},
            {json_exprs["decision_reason_codes"]},
            :decision_comment_hash,
            :decision_comment_preview,
            {json_exprs["metadata"]},
            :created_at,
            :updated_at
        )
        ON CONFLICT (repaired_response_decision_id) DO UPDATE SET
            decision_status = excluded.decision_status,
            decision_action = excluded.decision_action,
            selected_cx_generation_id = excluded.selected_cx_generation_id,
            rejected_cx_generation_id = excluded.rejected_cx_generation_id,
            actor_claims_ref = excluded.actor_claims_ref,
            decision_reason_codes = excluded.decision_reason_codes,
            decision_comment_hash = excluded.decision_comment_hash,
            decision_comment_preview = excluded.decision_comment_preview,
            metadata = excluded.metadata,
            updated_at = excluded.updated_at
    """


def _decision_select_sql(where_clause: str) -> str:
    return f"""
        SELECT
            repaired_response_decision_id,
            decision_schema_version,
            decision_request_id,
            decision_status,
            decision_action,
            repaired_response_handoff_id,
            handoff_request_id,
            tenant_id,
            workspace_id,
            owner_user_id,
            chat_document_id,
            interaction_id,
            parent_cx_generation_id,
            repair_cx_generation_id,
            selected_cx_generation_id,
            rejected_cx_generation_id,
            remediation_action_id,
            trace_id,
            request_id,
            actor_claims_ref,
            decision_reason_codes,
            decision_comment_hash,
            decision_comment_preview,
            metadata,
            created_at,
            updated_at
        FROM ae_repaired_response_decisions
        WHERE {where_clause}
    """


def _decision_record_params(record: dict[str, Any]) -> dict[str, Any]:
    params = dict(record)
    for field_name in JSON_STORAGE_FIELDS:
        params[field_name] = json.dumps(record[field_name])
    return params


def _decision_record_from_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    return {
        "decision_schema_version": data["decision_schema_version"],
        "repaired_response_decision_id": data["repaired_response_decision_id"],
        "decision_request_id": data["decision_request_id"],
        "decision_status": data["decision_status"],
        "decision_action": data["decision_action"],
        "repaired_response_handoff_id": data["repaired_response_handoff_id"],
        "handoff_request_id": data["handoff_request_id"],
        "trace_id": data["trace_id"],
        "request_id": data["request_id"],
        "tenant_id": data["tenant_id"],
        "workspace_id": data["workspace_id"],
        "owner_user_id": data["owner_user_id"],
        "chat_document_id": data["chat_document_id"],
        "interaction_id": data["interaction_id"],
        "actor_claims_ref": _json_value(data["actor_claims_ref"], {}),
        "parent_cx_generation_id": data["parent_cx_generation_id"],
        "repair_cx_generation_id": data["repair_cx_generation_id"],
        "selected_cx_generation_id": data["selected_cx_generation_id"],
        "rejected_cx_generation_id": data["rejected_cx_generation_id"],
        "remediation_action_id": data["remediation_action_id"],
        "decision_reason_codes": _json_value(data["decision_reason_codes"], []),
        "decision_comment_hash": data["decision_comment_hash"],
        "decision_comment_preview": data["decision_comment_preview"],
        "metadata": _json_value(data["metadata"], {}),
        "created_at": _datetime_value(data["created_at"]),
        "updated_at": _datetime_value(data["updated_at"]),
    }


def _json_param_expr(name: str, dialect_name: str) -> str:
    if dialect_name == "postgresql":
        return f"CAST(:{name} AS jsonb)"
    return f":{name}"


def _json_value(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        return json.loads(value)
    return value


def _datetime_value(value: Any) -> str:
    if value is None:
        return _utc_now()
    if hasattr(value, "isoformat"):
        return value.isoformat().replace("+00:00", "Z")
    return str(value)


def _dialect_name(session: Session) -> str:
    return session.get_bind().dialect.name


def _required_text(
    payload: Mapping[str, Any],
    field_name: str,
    error_code: str,
) -> str:
    value = optional_text(payload.get(field_name))
    if value is None:
        raise RepairedResponseDecisionError(
            status_code=422,
            error_code=error_code,
            detail=f"{field_name} is required.",
        )
    return value


def _sensitive_key_forbidden(key_lower: str, value: Any) -> bool:
    if key_lower in ALLOWED_FALSE_METADATA_FLAGS and value is False:
        return False
    if key_lower in {
        "completion_tokens",
        "input_tokens",
        "output_tokens",
        "prompt_tokens",
        "total_tokens",
    }:
        return False
    return any(part in key_lower for part in SENSITIVE_DECISION_KEY_PARTS)


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _handoff_for_decision_route(
    handoff_store: Any,
    *,
    interaction_id: str,
    repaired_response_handoff_id: str,
) -> dict[str, Any]:
    path_interaction_id = _required_text(
        {"interaction_id": interaction_id},
        "interaction_id",
        "ae.repaired_response_decision_interaction_id_required",
    )
    path_handoff_id = _required_text(
        {"repaired_response_handoff_id": repaired_response_handoff_id},
        "repaired_response_handoff_id",
        "ae.repaired_response_decision_handoff_id_required",
    )
    record = handoff_store.get(path_handoff_id)
    if record is None or record["interaction_id"] != path_interaction_id:
        raise RepairedResponseDecisionError(
            status_code=404,
            error_code="ae.repaired_response_handoff_not_found",
            detail=f"Repaired response handoff was not found: {path_handoff_id}",
        )
    return validate_repaired_response_handoff_record(record)


def _authorize_ae_request(
    request: Request,
    authorization: str | None,
) -> JSONResponse | None:
    validation = validate_authorization_header(
        authorization,
        expected_audience="nex-ae-api",
        required_scopes=[DEFAULT_SERVICE_SCOPE],
    )
    if validation.ok:
        return None
    return problem_response(
        request,
        status_code=401,
        error_code=validation.error_code or "SERVICE_CLAIM_INVALID",
        title="Authentication failed",
        detail=validation.detail or "AE API requires a valid service claim.",
        type_uri="https://nex-platform.local/problems/authentication-failed",
    )


def _decision_problem_response(request: Request, exc: Any) -> JSONResponse:
    return problem_response(
        request,
        status_code=int(getattr(exc, "status_code", 500)),
        error_code=str(getattr(exc, "error_code", "ae.repaired_response_decision_error")),
        title="Repaired response decision failed",
        detail=str(getattr(exc, "detail", str(exc))),
        type_uri="https://nex-platform.local/problems/repaired-response-decision",
        retryable=bool(getattr(exc, "retryable", False)),
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
