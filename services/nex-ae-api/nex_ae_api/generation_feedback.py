from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

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


@dataclass(frozen=True)
class GenerationFeedbackError(Exception):
    status_code: int
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


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


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
