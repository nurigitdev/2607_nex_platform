from __future__ import annotations

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


AE_REPAIRED_RESPONSE_HANDOFF_SCHEMA_VERSION = "ae_repaired_response_handoff.v1"
CX_REMEDIATION_EXECUTION_DETAIL_SCHEMA_VERSION = "cx_remediation_execution_detail.v1"
CX_REPAIRED_GENERATION_LINEAGE_SCHEMA_VERSION = "cx_repaired_generation_lineage.v1"
CX_GENERATION_EXECUTION_RECORD_SCHEMA_VERSION = "cx_generation_execution_record.v1"
DEFAULT_HANDOFF_STATUS = "READY_FOR_USER_REVIEW"
DEFAULT_PRESENTATION_MODE = "side_by_side_review"
SUPPORTED_PRESENTATION_MODES = {
    "side_by_side_review",
    "replace_answer_candidate",
    "append_revision_note",
}
DEFAULT_USER_ACTIONS = [
    "view_original",
    "view_repaired",
    "accept_repair",
    "keep_original",
    "view_lineage",
]
SENSITIVE_KEY_PARTS = (
    "api_key",
    "access_token",
    "authorization",
    "credential",
    "messages",
    "model_path",
    "password",
    "provider_endpoint",
    "provider_url",
    "raw_evidence",
    "raw_generation_output",
    "raw_operator_note",
    "raw_output",
    "raw_prompt",
    "raw_source",
    "raw_text",
    "raw_user_message",
    "secret",
    "source_text",
    "storage_path",
    "refresh_token",
)
JSON_STORAGE_FIELDS = (
    "actor_claims_ref",
    "source",
    "repaired_response",
    "lineage",
    "user_surface",
    "links",
    "redaction_summary",
)


@dataclass
class RepairedResponseHandoffStore:
    records: dict[str, dict[str, Any]] = field(default_factory=dict)
    handoff_ids_by_interaction: dict[str, list[str]] = field(default_factory=dict)

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        validated = validate_repaired_response_handoff_record(record)
        handoff_id = validated["repaired_response_handoff_id"]
        self.records[handoff_id] = validated
        interaction_ids = self.handoff_ids_by_interaction.setdefault(
            validated["interaction_id"],
            [],
        )
        if handoff_id not in interaction_ids:
            interaction_ids.append(handoff_id)
        return validated

    def get(self, repaired_response_handoff_id: str) -> dict[str, Any] | None:
        return self.records.get(repaired_response_handoff_id)

    def list_for_interaction(self, interaction_id: str) -> list[dict[str, Any]]:
        return [
            self.records[handoff_id]
            for handoff_id in self.handoff_ids_by_interaction.get(interaction_id, [])
            if handoff_id in self.records
        ]


class SqlAlchemyRepairedResponseHandoffStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        validated = validate_repaired_response_handoff_record(record)
        try:
            with self._session_factory() as session:
                session.execute(
                    text(_handoff_upsert_sql(_dialect_name(session))),
                    _handoff_record_params(validated),
                )
                session.commit()
            return validated
        except SQLAlchemyError as exc:
            raise RepairedResponseHandoffError(
                status_code=503,
                error_code="ae.repaired_response_handoff_store_unavailable",
                detail="AE repaired response handoff store is unavailable.",
                retryable=True,
            ) from exc

    def get(self, repaired_response_handoff_id: str) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(
                        text(
                            _handoff_select_sql(
                                "repaired_response_handoff_id = "
                                ":repaired_response_handoff_id"
                            )
                        ),
                        {
                            "repaired_response_handoff_id": (
                                repaired_response_handoff_id
                            )
                        },
                    )
                    .mappings()
                    .first()
                )
            return _handoff_record_from_row(row) if row is not None else None
        except SQLAlchemyError as exc:
            raise RepairedResponseHandoffError(
                status_code=503,
                error_code="ae.repaired_response_handoff_store_unavailable",
                detail="AE repaired response handoff store is unavailable.",
                retryable=True,
            ) from exc

    def list_for_interaction(self, interaction_id: str) -> list[dict[str, Any]]:
        try:
            with self._session_factory() as session:
                rows = (
                    session.execute(
                        text(
                            _handoff_select_sql(
                                "interaction_id = :interaction_id "
                                "ORDER BY created_at DESC, "
                                "repaired_response_handoff_id ASC"
                            )
                        ),
                        {"interaction_id": interaction_id},
                    )
                    .mappings()
                    .all()
                )
            return [_handoff_record_from_row(row) for row in rows]
        except SQLAlchemyError as exc:
            raise RepairedResponseHandoffError(
                status_code=503,
                error_code="ae.repaired_response_handoff_store_unavailable",
                detail="AE repaired response handoff store is unavailable.",
                retryable=True,
            ) from exc

    def delete(self, repaired_response_handoff_id: str) -> int:
        try:
            with self._session_factory() as session:
                result = session.execute(
                    text(
                        "DELETE FROM ae_repaired_response_handoffs "
                        "WHERE repaired_response_handoff_id = "
                        ":repaired_response_handoff_id"
                    ),
                    {
                        "repaired_response_handoff_id": (
                            repaired_response_handoff_id
                        )
                    },
                )
                session.commit()
                return int(result.rowcount or 0)
        except SQLAlchemyError as exc:
            raise RepairedResponseHandoffError(
                status_code=503,
                error_code="ae.repaired_response_handoff_store_unavailable",
                detail="AE repaired response handoff store is unavailable.",
                retryable=True,
            ) from exc


@dataclass(frozen=True)
class RepairedResponseHandoffError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


DEFAULT_REPAIRED_RESPONSE_HANDOFF_STORE = RepairedResponseHandoffStore()


def default_repaired_response_handoff_store(app: Any) -> Any:
    persistence = getattr(app.state, "nex_persistence", None)
    session_factory = getattr(persistence, "api_session_factory", None)
    if session_factory is not None:
        return SqlAlchemyRepairedResponseHandoffStore(session_factory)
    return DEFAULT_REPAIRED_RESPONSE_HANDOFF_STORE


def register_repaired_response_handoff_routes(
    app: FastAPI,
    *,
    store: Any | None = None,
    cx_client: Any | None = None,
) -> None:
    from nex_ae_api.repaired_response_client import (
        CxRepairedResponseSourceClientError,
        build_default_cx_repaired_response_source_client,
        build_repaired_response_handoff_from_source_package,
        build_repaired_response_source_package,
    )
    from nex_ae_api.repaired_response_review import (
        RepairedResponseReviewProjectionError,
        build_repaired_response_review_collection,
        build_repaired_response_review_projection,
    )

    handoff_store = store or default_repaired_response_handoff_store(app)
    client = cx_client or build_default_cx_repaired_response_source_client()

    @app.post(
        "/api/v1/chat/interactions/{interaction_id}/repaired-response-handoffs",
        response_model=None,
        status_code=202,
    )
    def create_repaired_response_handoff(
        interaction_id: str,
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_ae_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        request_id = request_id_from_headers(request)
        trace_id = payload.get("trace_id") or trace_id_from_headers(request)
        try:
            source_payload = repaired_response_payload_with_path_interaction_id(
                payload,
                interaction_id,
            )
            source_package = build_repaired_response_source_package(
                source_payload=source_payload,
                client=client,
                request_id=request_id,
                trace_id=trace_id,
            )
            handoff = build_repaired_response_handoff_from_source_package(
                source_payload=source_payload,
                source_package=source_package,
                request_id=request_id,
                trace_id=trace_id,
                handoff_request_id=optional_text(payload.get("handoff_request_id")),
            )
            return handoff_store.save(handoff)
        except (RepairedResponseHandoffError, CxRepairedResponseSourceClientError) as exc:
            return _handoff_problem_response(request, exc)

    @app.get(
        "/api/v1/chat/interactions/{interaction_id}/repaired-response-handoffs/"
        "review",
        response_model=None,
    )
    def list_repaired_response_handoff_reviews(
        interaction_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_ae_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        try:
            return build_repaired_response_review_collection(
                handoff_store.list_for_interaction(interaction_id),
                interaction_id=interaction_id,
            )
        except RepairedResponseReviewProjectionError as exc:
            return _handoff_problem_response(
                request,
                RepairedResponseHandoffError(
                    status_code=422,
                    error_code=exc.error_code,
                    detail=exc.detail,
                ),
            )

    @app.get(
        "/api/v1/chat/interactions/{interaction_id}/repaired-response-handoffs/"
        "{repaired_response_handoff_id}",
        response_model=None,
    )
    def get_repaired_response_handoff(
        interaction_id: str,
        repaired_response_handoff_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_ae_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        record = handoff_store.get(repaired_response_handoff_id)
        if record is None or record["interaction_id"] != interaction_id:
            return _handoff_problem_response(
                request,
                RepairedResponseHandoffError(
                    status_code=404,
                    error_code="ae.repaired_response_handoff_not_found",
                    detail=(
                        "Repaired response handoff was not found: "
                        f"{repaired_response_handoff_id}"
                    ),
                ),
            )
        return record

    @app.get(
        "/api/v1/chat/interactions/{interaction_id}/repaired-response-handoffs/"
        "{repaired_response_handoff_id}/review",
        response_model=None,
    )
    def get_repaired_response_handoff_review(
        interaction_id: str,
        repaired_response_handoff_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_ae_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        record = handoff_store.get(repaired_response_handoff_id)
        if record is None or record["interaction_id"] != interaction_id:
            return _handoff_problem_response(
                request,
                RepairedResponseHandoffError(
                    status_code=404,
                    error_code="ae.repaired_response_handoff_not_found",
                    detail=(
                        "Repaired response handoff was not found: "
                        f"{repaired_response_handoff_id}"
                    ),
                ),
            )
        try:
            return build_repaired_response_review_projection(record)
        except RepairedResponseReviewProjectionError as exc:
            return _handoff_problem_response(
                request,
                RepairedResponseHandoffError(
                    status_code=422,
                    error_code=exc.error_code,
                    detail=exc.detail,
                ),
            )


def build_repaired_response_handoff_record(
    *,
    source_payload: Mapping[str, Any],
    cx_remediation_detail: Mapping[str, Any],
    repaired_generation_record: Mapping[str, Any],
    handoff_request_id: str | None = None,
    request_id: str,
    trace_id: str,
    created_at: str | None = None,
) -> dict[str, Any]:
    assert_repaired_response_handoff_redaction_safe(source_payload)
    detail = dict(cx_remediation_detail)
    lineage = _valid_repaired_generation_lineage(detail)
    generation = _valid_repaired_generation_record(
        repaired_generation_record,
        repair_cx_generation_id=required_text(
            lineage,
            "repair_cx_generation_id",
            "ae.repaired_response_lineage_invalid",
        ),
    )
    _validate_source_scope(source_payload, lineage)

    interaction_id = required_text(
        source_payload,
        "interaction_id",
        "ae.repaired_response_interaction_id_required",
    )
    chat_document_id = required_text(
        source_payload,
        "chat_document_id",
        "ae.repaired_response_chat_document_id_required",
    )
    selected_request_id = handoff_request_id or optional_text(
        source_payload.get("handoff_request_id")
    )
    if selected_request_id is None:
        selected_request_id = str(
            uuid5(
                NAMESPACE_URL,
                (
                    "ae-repaired-response-request:"
                    f"{interaction_id}:{lineage['remediation_action_id']}:"
                    f"{lineage['repair_cx_generation_id']}"
                ),
            )
        )
    handoff_id = optional_text(source_payload.get("repaired_response_handoff_id")) or str(
        uuid5(NAMESPACE_URL, f"ae-repaired-response-handoff:{selected_request_id}")
    )
    now = created_at or _utc_now()
    response_metadata = _mapping(generation.get("response_metadata"))
    request_metadata = _mapping(generation.get("request_metadata"))
    record = {
        "handoff_schema_version": AE_REPAIRED_RESPONSE_HANDOFF_SCHEMA_VERSION,
        "repaired_response_handoff_id": handoff_id,
        "handoff_request_id": selected_request_id,
        "handoff_status": DEFAULT_HANDOFF_STATUS,
        "trace_id": required_text({"trace_id": trace_id}, "trace_id", "ae.trace_id_required"),
        "request_id": required_text(
            {"request_id": request_id},
            "request_id",
            "ae.request_id_required",
        ),
        "tenant_id": required_text(
            source_payload,
            "tenant_id",
            "ae.repaired_response_tenant_id_required",
        ),
        "workspace_id": required_text(
            source_payload,
            "workspace_id",
            "ae.repaired_response_workspace_id_required",
        ),
        "owner_user_id": required_text(
            source_payload,
            "owner_user_id",
            "ae.repaired_response_owner_user_id_required",
        ),
        "chat_document_id": chat_document_id,
        "interaction_id": interaction_id,
        "actor_claims_ref": actor_claims_ref_from_payload(source_payload),
        "source": {
            "source_service": "nex-cx",
            "detail_schema_version": detail["detail_schema_version"],
            "remediation_action_id": lineage["remediation_action_id"],
            "parent_cx_generation_id": lineage["parent_cx_generation_id"],
            "root_cx_generation_id": lineage["root_cx_generation_id"],
            "repair_cx_generation_id": lineage["repair_cx_generation_id"],
            "result_ref": _safe_result_ref(lineage.get("result_ref")),
        },
        "repaired_response": {
            "cx_generation_id": generation["cx_generation_id"],
            "status": generation["status"],
            "alias": required_text(
                generation,
                "alias",
                "ae.repaired_response_generation_invalid",
            ),
            "provider_capability": required_text(
                generation,
                "provider_capability",
                "ae.repaired_response_generation_invalid",
            ),
            "mo_generation_id": optional_text(generation.get("mo_generation_id")),
            "finish_reason": required_text(
                response_metadata,
                "finish_reason",
                "ae.repaired_response_generation_invalid",
            ),
            "output_hash": optional_text(response_metadata.get("output_hash")),
            "output_preview": (
                optional_text(response_metadata.get("output_preview")) or ""
            )[:120],
            "usage": dict(_mapping(generation.get("usage"))),
            "quality_summary": {
                "grounding_required": bool(request_metadata.get("grounding_required")),
                "retrieval_package_id": optional_text(
                    request_metadata.get("retrieval_package_id")
                ),
                "retrieval_package_hash": optional_text(
                    request_metadata.get("retrieval_package_hash")
                ),
                "structured_draft_id": optional_text(
                    request_metadata.get("structured_draft_id")
                ),
                "draft_validation_status": optional_text(
                    request_metadata.get("draft_validation_status")
                ),
                "grounded_response_quality_status": optional_text(
                    request_metadata.get("grounded_response_quality_status")
                ),
                "grounded_response_quality_issue_count": _non_negative_int(
                    request_metadata.get("grounded_response_quality_issue_count")
                ),
            },
        },
        "lineage": {
            "source_lineage_schema_version": lineage["lineage_schema_version"],
            "lineage_status": lineage["lineage_status"],
            "parent_cx_generation_id": lineage["parent_cx_generation_id"],
            "root_cx_generation_id": lineage["root_cx_generation_id"],
            "repair_cx_generation_id": lineage["repair_cx_generation_id"],
            "remediation_action_id": lineage["remediation_action_id"],
            "action_type": lineage["action_type"],
            "lineage_type": lineage["lineage_type"],
            "attempt_no": lineage["attempt_no"],
            "parent_generation_mutated": False,
        },
        "user_surface": {
            "presentation_mode": presentation_mode_from_payload(source_payload),
            "default_action": "review_repair",
            "available_actions": list(DEFAULT_USER_ACTIONS),
        },
        "links": {
            "handoff": (
                f"/api/v1/chat/interactions/{interaction_id}/"
                f"repaired-response-handoffs/{handoff_id}"
            ),
            "original_generation": (
                f"/api/v1/generations/{lineage['parent_cx_generation_id']}"
            ),
            "repaired_generation": (
                f"/api/v1/generations/{lineage['repair_cx_generation_id']}"
            ),
            "remediation_execution": (
                f"/api/v1/generations/{lineage['parent_cx_generation_id']}/"
                f"remediation-executions/{lineage['remediation_action_id']}"
            ),
        },
        "redaction_summary": _redaction_summary(),
        "created_at": now,
        "updated_at": now,
    }
    validate_repaired_response_handoff_record(record)
    return record


def validate_repaired_response_handoff_record(record: Mapping[str, Any]) -> dict[str, Any]:
    if record.get("handoff_schema_version") != AE_REPAIRED_RESPONSE_HANDOFF_SCHEMA_VERSION:
        raise RepairedResponseHandoffError(
            status_code=422,
            error_code="ae.repaired_response_handoff_schema_invalid",
            detail="AE repaired response handoff schema version is invalid.",
        )
    if record.get("handoff_status") != DEFAULT_HANDOFF_STATUS:
        raise RepairedResponseHandoffError(
            status_code=422,
            error_code="ae.repaired_response_handoff_status_invalid",
            detail="AE repaired response handoff status is invalid.",
        )
    source = _mapping(record.get("source"))
    repaired_response = _mapping(record.get("repaired_response"))
    lineage = _mapping(record.get("lineage"))
    if (
        source.get("repair_cx_generation_id") != repaired_response.get("cx_generation_id")
        or lineage.get("repair_cx_generation_id") != repaired_response.get("cx_generation_id")
        or lineage.get("parent_cx_generation_id") != source.get("parent_cx_generation_id")
    ):
        raise RepairedResponseHandoffError(
            status_code=409,
            error_code="ae.repaired_response_lineage_mismatch",
            detail="AE repaired response handoff lineage is inconsistent.",
        )
    if lineage.get("parent_generation_mutated") is not False:
        raise RepairedResponseHandoffError(
            status_code=422,
            error_code="ae.repaired_response_parent_mutation_forbidden",
            detail="AE repaired response handoff cannot mutate the original generation.",
        )
    redaction = _mapping(record.get("redaction_summary"))
    if any(
        redaction.get(key) is not False
        for key in (
            "raw_output_included",
            "raw_prompt_included",
            "raw_source_text_included",
            "evidence_text_included",
            "provider_detail_included",
        )
    ):
        raise RepairedResponseHandoffError(
            status_code=422,
            error_code="ae.repaired_response_redaction_invalid",
            detail="AE repaired response handoff redaction flags must be false.",
        )
    assert_repaired_response_handoff_redaction_safe(record)
    return dict(record)


def repaired_response_payload_with_path_interaction_id(
    payload: Mapping[str, Any],
    interaction_id: str,
) -> dict[str, Any]:
    path_interaction_id = interaction_id.strip()
    if not path_interaction_id:
        raise RepairedResponseHandoffError(
            status_code=422,
            error_code="ae.repaired_response_interaction_id_required",
            detail="interaction_id is required.",
        )
    payload_interaction_id = optional_text(payload.get("interaction_id"))
    if (
        payload_interaction_id is not None
        and payload_interaction_id != path_interaction_id
    ):
        raise RepairedResponseHandoffError(
            status_code=409,
            error_code="ae.repaired_response_interaction_mismatch",
            detail="Repaired response interaction_id does not match the route.",
        )
    return {**dict(payload), "interaction_id": path_interaction_id}


def presentation_mode_from_payload(payload: Mapping[str, Any]) -> str:
    value = optional_text(payload.get("presentation_mode")) or DEFAULT_PRESENTATION_MODE
    if value not in SUPPORTED_PRESENTATION_MODES:
        raise RepairedResponseHandoffError(
            status_code=422,
            error_code="ae.repaired_response_presentation_mode_invalid",
            detail=f"Unsupported repaired response presentation mode: {value}",
        )
    return value


def actor_claims_ref_from_payload(payload: Mapping[str, Any]) -> dict[str, str]:
    actor = _mapping(payload.get("actor_claims_ref"))
    actor_type = optional_text(actor.get("actor_type")) or "user"
    actor_id = optional_text(actor.get("actor_id")) or required_text(
        payload,
        "owner_user_id",
        "ae.repaired_response_owner_user_id_required",
    )
    tenant_id = optional_text(actor.get("tenant_id")) or required_text(
        payload,
        "tenant_id",
        "ae.repaired_response_tenant_id_required",
    )
    return {
        "actor_type": actor_type,
        "actor_id": actor_id,
        "tenant_id": tenant_id,
    }


def assert_repaired_response_handoff_redaction_safe(payload: Any) -> None:
    sensitive_keys = find_sensitive_repaired_response_handoff_keys(payload)
    if sensitive_keys:
        raise RepairedResponseHandoffError(
            status_code=422,
            error_code="ae.repaired_response_sensitive_payload",
            detail=(
                "AE repaired response handoff contains sensitive keys: "
                f"{', '.join(sensitive_keys)}"
            ),
        )
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    forbidden_fragments = (
        "/data/nex-platform",
        "hidden prompt",
        "raw answer body",
        "provider_endpoint",
        "ed6@",
        "nuri1004",
    )
    if any(fragment in serialized for fragment in forbidden_fragments):
        raise RepairedResponseHandoffError(
            status_code=422,
            error_code="ae.repaired_response_sensitive_payload",
            detail="AE repaired response handoff contains sensitive payload content.",
        )


def find_sensitive_repaired_response_handoff_keys(payload: Any) -> list[str]:
    found: set[str] = set()

    def visit(value: Any, path: str) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                key_text = str(key)
                key_lower = key_text.lower()
                child_path = f"{path}.{key_text}" if path else key_text
                if _sensitive_key_forbidden(key_lower, child):
                    found.add(child_path)
                visit(child, child_path)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f"{path}[{index}]")

    visit(payload, "")
    return sorted(found)


def required_text(payload: Mapping[str, Any], field_name: str, error_code: str) -> str:
    value = optional_text(payload.get(field_name))
    if value is None:
        raise RepairedResponseHandoffError(
            status_code=422,
            error_code=error_code,
            detail=f"{field_name} is required.",
        )
    return value


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _valid_repaired_generation_lineage(detail: Mapping[str, Any]) -> dict[str, Any]:
    if detail.get("detail_schema_version") != CX_REMEDIATION_EXECUTION_DETAIL_SCHEMA_VERSION:
        raise RepairedResponseHandoffError(
            status_code=422,
            error_code="ae.repaired_response_cx_detail_invalid",
            detail="CX remediation execution detail schema version is invalid.",
        )
    if detail.get("execution_status") != "SUCCEEDED":
        raise RepairedResponseHandoffError(
            status_code=409,
            error_code="ae.repaired_response_execution_not_succeeded",
            detail="CX remediation execution must be SUCCEEDED before AE handoff.",
        )
    lineage = _mapping(detail.get("repaired_generation_lineage"))
    if (
        lineage.get("lineage_schema_version")
        != CX_REPAIRED_GENERATION_LINEAGE_SCHEMA_VERSION
        or lineage.get("lineage_status") != "LINKED"
    ):
        raise RepairedResponseHandoffError(
            status_code=409,
            error_code="ae.repaired_response_lineage_not_linked",
            detail="CX repaired generation lineage is not linked.",
        )
    diagnostics = _mapping(lineage.get("diagnostics"))
    if (
        diagnostics.get("lineage_consistent") is not True
        or diagnostics.get("parent_generation_mutated") is not False
    ):
        raise RepairedResponseHandoffError(
            status_code=409,
            error_code="ae.repaired_response_lineage_invalid",
            detail="CX repaired generation lineage diagnostics are invalid.",
        )
    return dict(lineage)


def _valid_repaired_generation_record(
    generation: Mapping[str, Any],
    *,
    repair_cx_generation_id: str,
) -> dict[str, Any]:
    record = dict(generation)
    if record.get("record_schema_version") != CX_GENERATION_EXECUTION_RECORD_SCHEMA_VERSION:
        raise RepairedResponseHandoffError(
            status_code=422,
            error_code="ae.repaired_response_generation_invalid",
            detail="CX repaired generation record schema version is invalid.",
        )
    if record.get("cx_generation_id") != repair_cx_generation_id:
        raise RepairedResponseHandoffError(
            status_code=409,
            error_code="ae.repaired_response_generation_mismatch",
            detail="CX repaired generation id does not match remediation lineage.",
        )
    if record.get("status") != "COMPLETED":
        raise RepairedResponseHandoffError(
            status_code=409,
            error_code="ae.repaired_response_generation_not_completed",
            detail="CX repaired generation must be COMPLETED before AE handoff.",
        )
    return record


def _validate_source_scope(
    source_payload: Mapping[str, Any],
    lineage: Mapping[str, Any],
) -> None:
    expected_original_id = optional_text(source_payload.get("original_cx_generation_id"))
    if (
        expected_original_id is not None
        and expected_original_id != lineage.get("parent_cx_generation_id")
    ):
        raise RepairedResponseHandoffError(
            status_code=409,
            error_code="ae.repaired_response_original_generation_mismatch",
            detail="Original CX generation id does not match repaired lineage.",
        )


def _safe_result_ref(value: Any) -> dict[str, str] | None:
    result_ref = _mapping(value)
    safe_ref = {
        key: optional_text(result_ref.get(key))
        for key in ("source_service", "ref_type", "ref_id", "relation")
    }
    if any(field is None for field in safe_ref.values()):
        return None
    if (
        safe_ref["source_service"] != "nex-cx"
        or safe_ref["ref_type"] != "repair_execution"
        or safe_ref["relation"] != "result_of"
    ):
        return None
    return {
        "source_service": safe_ref["source_service"] or "",
        "ref_type": safe_ref["ref_type"] or "",
        "ref_id": safe_ref["ref_id"] or "",
        "relation": safe_ref["relation"] or "",
    }


def _redaction_summary() -> dict[str, Any]:
    return {
        "raw_output_included": False,
        "raw_prompt_included": False,
        "raw_source_text_included": False,
        "evidence_text_included": False,
        "provider_detail_included": False,
        "storage_path_included": False,
        "free_text_storage": "hash_and_short_preview_only",
    }


def _handoff_upsert_sql(dialect_name: str) -> str:
    json_exprs = {
        field_name: _json_param_expr(field_name, dialect_name)
        for field_name in JSON_STORAGE_FIELDS
    }
    return f"""
        INSERT INTO ae_repaired_response_handoffs (
            repaired_response_handoff_id,
            handoff_schema_version,
            handoff_request_id,
            handoff_status,
            tenant_id,
            workspace_id,
            owner_user_id,
            chat_document_id,
            interaction_id,
            original_cx_generation_id,
            parent_cx_generation_id,
            root_cx_generation_id,
            repair_cx_generation_id,
            remediation_action_id,
            trace_id,
            request_id,
            actor_claims_ref,
            source,
            repaired_response,
            lineage,
            user_surface,
            links,
            redaction_summary,
            created_at,
            updated_at
        )
        VALUES (
            :repaired_response_handoff_id,
            :handoff_schema_version,
            :handoff_request_id,
            :handoff_status,
            :tenant_id,
            :workspace_id,
            :owner_user_id,
            :chat_document_id,
            :interaction_id,
            :original_cx_generation_id,
            :parent_cx_generation_id,
            :root_cx_generation_id,
            :repair_cx_generation_id,
            :remediation_action_id,
            :trace_id,
            :request_id,
            {json_exprs["actor_claims_ref"]},
            {json_exprs["source"]},
            {json_exprs["repaired_response"]},
            {json_exprs["lineage"]},
            {json_exprs["user_surface"]},
            {json_exprs["links"]},
            {json_exprs["redaction_summary"]},
            :created_at,
            :updated_at
        )
        ON CONFLICT (repaired_response_handoff_id) DO UPDATE SET
            handoff_status = excluded.handoff_status,
            actor_claims_ref = excluded.actor_claims_ref,
            source = excluded.source,
            repaired_response = excluded.repaired_response,
            lineage = excluded.lineage,
            user_surface = excluded.user_surface,
            links = excluded.links,
            redaction_summary = excluded.redaction_summary,
            updated_at = excluded.updated_at
    """


def _handoff_select_sql(where_clause: str) -> str:
    return f"""
        SELECT
            repaired_response_handoff_id,
            handoff_schema_version,
            handoff_request_id,
            handoff_status,
            tenant_id,
            workspace_id,
            owner_user_id,
            chat_document_id,
            interaction_id,
            original_cx_generation_id,
            parent_cx_generation_id,
            root_cx_generation_id,
            repair_cx_generation_id,
            remediation_action_id,
            trace_id,
            request_id,
            actor_claims_ref,
            source,
            repaired_response,
            lineage,
            user_surface,
            links,
            redaction_summary,
            created_at,
            updated_at
        FROM ae_repaired_response_handoffs
        WHERE {where_clause}
    """


def _handoff_record_params(record: dict[str, Any]) -> dict[str, Any]:
    source = _mapping(record.get("source"))
    lineage = _mapping(record.get("lineage"))
    params = {
        **record,
        "original_cx_generation_id": source.get("parent_cx_generation_id"),
        "parent_cx_generation_id": source.get("parent_cx_generation_id"),
        "root_cx_generation_id": source.get("root_cx_generation_id"),
        "repair_cx_generation_id": source.get("repair_cx_generation_id"),
        "remediation_action_id": (
            source.get("remediation_action_id")
            or lineage.get("remediation_action_id")
        ),
    }
    for field_name in JSON_STORAGE_FIELDS:
        params[field_name] = json.dumps(record[field_name])
    return params


def _handoff_record_from_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    return {
        "handoff_schema_version": data["handoff_schema_version"],
        "repaired_response_handoff_id": data["repaired_response_handoff_id"],
        "handoff_request_id": data["handoff_request_id"],
        "handoff_status": data["handoff_status"],
        "trace_id": data["trace_id"],
        "request_id": data["request_id"],
        "tenant_id": data["tenant_id"],
        "workspace_id": data["workspace_id"],
        "owner_user_id": data["owner_user_id"],
        "chat_document_id": data["chat_document_id"],
        "interaction_id": data["interaction_id"],
        "actor_claims_ref": _json_value(data["actor_claims_ref"], {}),
        "source": _json_value(data["source"], {}),
        "repaired_response": _json_value(data["repaired_response"], {}),
        "lineage": _json_value(data["lineage"], {}),
        "user_surface": _json_value(data["user_surface"], {}),
        "links": _json_value(data["links"], {}),
        "redaction_summary": _json_value(data["redaction_summary"], {}),
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


def _sensitive_key_forbidden(key_lower: str, value: Any) -> bool:
    if key_lower.endswith(("_included", "_stored")) and value is False:
        return False
    return any(part in key_lower for part in SENSITIVE_KEY_PARTS)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _non_negative_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(value, 0)


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


def _handoff_problem_response(request: Request, exc: Any) -> JSONResponse:
    return problem_response(
        request,
        status_code=int(getattr(exc, "status_code", 500)),
        error_code=str(getattr(exc, "error_code", "ae.repaired_response_error")),
        title="Repaired response handoff failed",
        detail=str(getattr(exc, "detail", str(exc))),
        type_uri="https://nex-platform.local/problems/repaired-response-handoff",
        retryable=bool(getattr(exc, "retryable", False)),
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
