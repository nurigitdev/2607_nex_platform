from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
    validate_authorization_header,
)
from nex_ae_api.generation_feedback_boundary import (
    ALLOWED_FEEDBACK_REASONS,
    ALLOWED_FEEDBACK_VALUES,
    GENERATION_FEEDBACK_CONTRACT_VERSION,
    assert_feedback_payload_redaction_safe,
)


MAX_FEEDBACK_COMMENT_PREVIEW_LENGTH = 240
DEFAULT_FEEDBACK_STATUS = "RECORDED"
DEFAULT_FEEDBACK_CHANNEL = "chat"
ALLOWED_QUALITY_ISSUE_TYPES = (
    "retrieval_quality",
    "generation_quality",
    "citation_quality",
    "artifact_quality",
    "user_reported",
)
ALLOWED_QUALITY_ISSUE_SOURCE_SERVICES = (
    "nex-ae-api",
    "nex-cx",
    "nex-ag",
)


@dataclass
class GenerationFeedbackStore:
    records: dict[str, dict[str, Any]] = field(default_factory=dict)
    feedback_ids_by_interaction: dict[str, list[str]] = field(default_factory=dict)

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        feedback_id = record["feedback_id"]
        self.records[feedback_id] = record
        interaction_ids = self.feedback_ids_by_interaction.setdefault(
            record["interaction_id"],
            [],
        )
        if feedback_id not in interaction_ids:
            interaction_ids.append(feedback_id)
        return record

    def get(self, feedback_id: str) -> dict[str, Any] | None:
        return self.records.get(feedback_id)

    def list_for_interaction(self, interaction_id: str) -> list[dict[str, Any]]:
        return [
            self.records[feedback_id]
            for feedback_id in self.feedback_ids_by_interaction.get(interaction_id, [])
            if feedback_id in self.records
        ]


@dataclass(frozen=True)
class GenerationFeedbackError(Exception):
    status_code: int
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


DEFAULT_GENERATION_FEEDBACK_STORE = GenerationFeedbackStore()


def register_generation_feedback_routes(
    app: FastAPI,
    *,
    store: GenerationFeedbackStore | None = None,
) -> None:
    feedback_store = store or DEFAULT_GENERATION_FEEDBACK_STORE

    @app.post(
        "/api/v1/chat/interactions/{interaction_id}/feedback",
        response_model=None,
        status_code=202,
    )
    def create_generation_feedback(
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
            source_payload = payload_with_path_interaction_id(payload, interaction_id)
            return feedback_store.save(
                build_generation_feedback_record(
                    source_payload,
                    request_id=request_id,
                    trace_id=trace_id,
                )
            )
        except GenerationFeedbackError as exc:
            return _feedback_problem_response(request, exc)

    @app.get(
        "/api/v1/chat/interactions/{interaction_id}/feedback",
        response_model=None,
    )
    def list_generation_feedback(
        interaction_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_ae_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        return {
            "feedback_schema_version": "ae_generation_feedback_list.v1",
            "interaction_id": interaction_id,
            "items": feedback_store.list_for_interaction(interaction_id),
        }

    @app.get(
        "/api/v1/chat/interactions/{interaction_id}/feedback/{feedback_id}",
        response_model=None,
    )
    def get_generation_feedback(
        interaction_id: str,
        feedback_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_ae_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        record = feedback_store.get(feedback_id)
        if record is None or record["interaction_id"] != interaction_id:
            return _feedback_problem_response(
                request,
                GenerationFeedbackError(
                    status_code=404,
                    error_code="ae.generation_feedback_not_found",
                    detail=f"Generation feedback was not found: {feedback_id}",
                ),
            )
        return record


def payload_with_path_interaction_id(
    payload: dict[str, Any],
    interaction_id: str,
) -> dict[str, Any]:
    path_interaction_id = interaction_id.strip()
    if not path_interaction_id:
        raise GenerationFeedbackError(
            status_code=422,
            error_code="ae.generation_feedback_interaction_id_required",
            detail="interaction_id is required.",
        )
    payload_interaction_id = optional_string(payload.get("interaction_id"))
    if payload_interaction_id is not None and payload_interaction_id != path_interaction_id:
        raise GenerationFeedbackError(
            status_code=409,
            error_code="ae.generation_feedback_interaction_mismatch",
            detail="Feedback interaction_id does not match the route interaction_id.",
        )
    return {**payload, "interaction_id": path_interaction_id}


def build_generation_feedback_record(
    payload: dict[str, Any],
    *,
    request_id: str,
    trace_id: str,
    created_at: str | None = None,
) -> dict[str, Any]:
    try:
        assert_feedback_payload_redaction_safe(payload)
    except Exception as exc:
        raise GenerationFeedbackError(
            status_code=422,
            error_code="ae.generation_feedback_sensitive_payload",
            detail=str(exc),
        ) from exc

    tenant_id = required_string(payload, "tenant_id")
    user_id = required_string(payload, "user_id")
    interaction_id = required_string(payload, "interaction_id")
    feedback_value = required_choice(
        payload,
        "feedback_value",
        choices=ALLOWED_FEEDBACK_VALUES,
    )
    feedback_reasons = feedback_reason_list(payload.get("feedback_reasons"))
    comment = optional_string(payload.get("feedback_comment"))
    comment_hash = sha256_text(comment) if comment is not None else None
    now = created_at or _utc_now()
    feedback_id = optional_string(payload.get("feedback_id")) or str(
        uuid5(
            NAMESPACE_URL,
            (
                "ae-generation-feedback:"
                f"{tenant_id}:{user_id}:{interaction_id}:"
                f"{feedback_value}:{','.join(feedback_reasons)}:"
                f"{comment_hash or 'no-comment'}:{request_id}"
            ),
        )
    )
    return {
        "feedback_schema_version": GENERATION_FEEDBACK_CONTRACT_VERSION,
        "feedback_id": feedback_id,
        "status": DEFAULT_FEEDBACK_STATUS,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "interaction_id": interaction_id,
        "chat_document_id": optional_string(payload.get("chat_document_id")),
        "cx_generation_id": optional_string(payload.get("cx_generation_id")),
        "trace_id": trace_id,
        "request_id": request_id,
        "feedback_value": feedback_value,
        "feedback_reasons": feedback_reasons,
        "feedback_comment_hash": comment_hash,
        "feedback_comment_preview": comment_preview(comment),
        "quality_issue_refs": quality_issue_refs(payload.get("quality_issue_refs")),
        "metadata": {
            "submitted_via": optional_string(payload.get("submitted_via"))
            or DEFAULT_FEEDBACK_CHANNEL,
            "raw_prompt_stored": False,
            "raw_generation_output_stored": False,
            "free_text_comment_storage": "hash_and_short_preview_only",
        },
        "created_at": now,
    }


def feedback_reason_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise GenerationFeedbackError(
            status_code=422,
            error_code="ae.generation_feedback_reasons_invalid",
            detail="feedback_reasons must be a list when supplied.",
        )
    reasons: list[str] = []
    for reason in value:
        if not isinstance(reason, str) or not reason.strip():
            raise GenerationFeedbackError(
                status_code=422,
                error_code="ae.generation_feedback_reason_invalid",
                detail="feedback reason must be a non-empty string.",
            )
        normalized = reason.strip()
        if normalized not in ALLOWED_FEEDBACK_REASONS:
            raise GenerationFeedbackError(
                status_code=422,
                error_code="ae.generation_feedback_reason_unsupported",
                detail=f"unsupported feedback reason: {normalized}",
            )
        if normalized not in reasons:
            reasons.append(normalized)
    return reasons


def quality_issue_refs(value: Any) -> list[dict[str, str | None]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise GenerationFeedbackError(
            status_code=422,
            error_code="ae.generation_feedback_quality_refs_invalid",
            detail="quality_issue_refs must be a list when supplied.",
        )
    refs: list[dict[str, str | None]] = []
    for item in value:
        if not isinstance(item, dict):
            raise GenerationFeedbackError(
                status_code=422,
                error_code="ae.generation_feedback_quality_ref_invalid",
                detail="quality issue reference must be an object.",
            )
        source_service = required_choice(
            item,
            "source_service",
            choices=ALLOWED_QUALITY_ISSUE_SOURCE_SERVICES,
        )
        issue_type = required_choice(
            item,
            "issue_type",
            choices=ALLOWED_QUALITY_ISSUE_TYPES,
        )
        issue_code = required_string(item, "issue_code")
        refs.append(
            {
                "source_service": source_service,
                "issue_type": issue_type,
                "issue_code": issue_code,
                "issue_ref_id": optional_string(item.get("issue_ref_id")),
            }
        )
    return refs


def comment_preview(comment: str | None) -> str | None:
    if comment is None:
        return None
    return comment.strip()[:MAX_FEEDBACK_COMMENT_PREVIEW_LENGTH]


def required_choice(
    payload: dict[str, Any],
    key: str,
    *,
    choices: tuple[str, ...],
) -> str:
    value = required_string(payload, key)
    if value not in choices:
        raise GenerationFeedbackError(
            status_code=422,
            error_code=f"ae.generation_feedback_{key}_unsupported",
            detail=f"unsupported {key}: {value}",
        )
    return value


def required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise GenerationFeedbackError(
            status_code=422,
            error_code=f"ae.generation_feedback_{key}_required",
            detail=f"{key} is required.",
        )
    return value.strip()


def optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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


def _feedback_problem_response(
    request: Request,
    error: GenerationFeedbackError,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=error.status_code,
        error_code=error.error_code,
        title="Generation feedback failed",
        detail=error.detail,
        type_uri="https://nex-platform.local/problems/generation-feedback-failed",
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
