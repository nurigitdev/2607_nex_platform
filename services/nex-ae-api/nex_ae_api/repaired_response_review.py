from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from nex_ae_api.repaired_responses import (
    RepairedResponseHandoffError,
    optional_text,
    validate_repaired_response_handoff_record,
)


AE_REPAIRED_RESPONSE_REVIEW_PROJECTION_SCHEMA_VERSION = (
    "ae_repaired_response_review_projection.v1"
)
DEFAULT_REVIEW_STATUS = "READY_FOR_DECISION"
PRIMARY_REVIEW_ACTIONS = ("accept_repair", "keep_original")
SECONDARY_REVIEW_ACTIONS = ("view_original", "view_repaired", "view_lineage")
SUPPORTED_REVIEW_ACTIONS = PRIMARY_REVIEW_ACTIONS + SECONDARY_REVIEW_ACTIONS
SAFE_DECISION_PATH_SUFFIX = "/decisions"
SENSITIVE_REVIEW_KEY_PARTS = (
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
ALLOWED_FALSE_REDACTION_KEYS = {
    "raw_output_included",
    "raw_prompt_included",
    "raw_source_text_included",
    "evidence_text_included",
    "provider_detail_included",
    "storage_path_included",
}


SAFE_USAGE_TOKEN_KEYS = {
    "completion_tokens",
    "input_tokens",
    "output_tokens",
    "prompt_tokens",
    "total_tokens",
}


@dataclass
class RepairedResponseReviewProjectionError(ValueError):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


def build_repaired_response_review_projection(
    handoff_record: Mapping[str, Any],
    *,
    checked_at: str | None = None,
) -> dict[str, Any]:
    try:
        handoff = validate_repaired_response_handoff_record(handoff_record)
    except RepairedResponseHandoffError as exc:
        raise RepairedResponseReviewProjectionError(
            error_code="ae.repaired_response_review.handoff_invalid",
            detail=str(exc),
        ) from exc

    source = _mapping(handoff.get("source"))
    repaired = _mapping(handoff.get("repaired_response"))
    lineage = _mapping(handoff.get("lineage"))
    surface = _mapping(handoff.get("user_surface"))
    links = _mapping(handoff.get("links"))
    available_actions = _review_actions_from_handoff(surface.get("available_actions"))
    projection = {
        "projection_schema_version": (
            AE_REPAIRED_RESPONSE_REVIEW_PROJECTION_SCHEMA_VERSION
        ),
        "projection_status": DEFAULT_REVIEW_STATUS,
        "repaired_response_handoff_id": handoff["repaired_response_handoff_id"],
        "handoff_request_id": handoff["handoff_request_id"],
        "trace_id": handoff["trace_id"],
        "request_id": handoff["request_id"],
        "owner_scope": {
            "tenant_id": handoff["tenant_id"],
            "workspace_id": handoff["workspace_id"],
            "owner_user_id": handoff["owner_user_id"],
        },
        "conversation_scope": {
            "chat_document_id": handoff["chat_document_id"],
            "interaction_id": handoff["interaction_id"],
        },
        "review_card": {
            "title": "Repaired response ready for review",
            "presentation_mode": surface["presentation_mode"],
            "default_action": surface["default_action"],
        },
        "original_response_ref": {
            "cx_generation_id": source["parent_cx_generation_id"],
            "link": links["original_generation"],
            "parent_generation_mutated": False,
        },
        "repaired_response_summary": {
            "cx_generation_id": repaired["cx_generation_id"],
            "status": repaired["status"],
            "alias": repaired["alias"],
            "provider_capability": repaired["provider_capability"],
            "finish_reason": repaired["finish_reason"],
            "output_hash": repaired.get("output_hash"),
            "output_preview": repaired.get("output_preview") or "",
            "usage": dict(_mapping(repaired.get("usage"))),
            "quality_summary": dict(_mapping(repaired.get("quality_summary"))),
        },
        "lineage_summary": {
            "remediation_action_id": lineage["remediation_action_id"],
            "lineage_status": lineage["lineage_status"],
            "action_type": lineage["action_type"],
            "lineage_type": lineage["lineage_type"],
            "attempt_no": lineage["attempt_no"],
            "result_ref": source.get("result_ref"),
        },
        "decision_controls": {
            "available_actions": available_actions,
            "primary_actions": list(PRIMARY_REVIEW_ACTIONS),
            "secondary_actions": [
                action
                for action in SECONDARY_REVIEW_ACTIONS
                if action in available_actions
            ],
            "decision_submit_path": decision_submit_path_for_handoff(handoff),
            "idempotency_key_hint": handoff["handoff_request_id"],
        },
        "links": {
            "handoff": links["handoff"],
            "original_generation": links["original_generation"],
            "repaired_generation": links["repaired_generation"],
            "remediation_execution": links["remediation_execution"],
        },
        "redaction_summary": dict(_mapping(handoff.get("redaction_summary"))),
        "created_at": handoff["created_at"],
        "updated_at": handoff["updated_at"],
        "checked_at": checked_at or _utc_now(),
    }
    return validate_repaired_response_review_projection(projection)


def build_repaired_response_review_collection(
    handoff_records: Iterable[Mapping[str, Any]],
    *,
    interaction_id: str,
    checked_at: str | None = None,
) -> dict[str, Any]:
    selected_interaction_id = _required_text(
        {"interaction_id": interaction_id},
        "interaction_id",
        "ae.repaired_response_review.interaction_id_required",
    )
    projections = [
        build_repaired_response_review_projection(record, checked_at=checked_at)
        for record in handoff_records
        if optional_text(record.get("interaction_id")) == selected_interaction_id
    ]
    projections.sort(
        key=lambda item: (
            str(item.get("created_at") or ""),
            str(item.get("repaired_response_handoff_id") or ""),
        ),
        reverse=True,
    )
    return {
        "collection_schema_version": "ae_repaired_response_review_collection.v1",
        "interaction_id": selected_interaction_id,
        "items": projections,
        "item_count": len(projections),
        "checked_at": checked_at or _utc_now(),
    }


def validate_repaired_response_review_projection(
    projection: Mapping[str, Any],
) -> dict[str, Any]:
    if projection.get("projection_schema_version") != (
        AE_REPAIRED_RESPONSE_REVIEW_PROJECTION_SCHEMA_VERSION
    ):
        raise RepairedResponseReviewProjectionError(
            error_code="ae.repaired_response_review.schema_version_invalid",
            detail="AE repaired response review projection schema version is invalid.",
        )
    if projection.get("projection_status") != DEFAULT_REVIEW_STATUS:
        raise RepairedResponseReviewProjectionError(
            error_code="ae.repaired_response_review.status_invalid",
            detail="AE repaired response review projection status is invalid.",
        )
    owner_scope = _mapping(projection.get("owner_scope"))
    conversation_scope = _mapping(projection.get("conversation_scope"))
    for field_name in ("tenant_id", "workspace_id", "owner_user_id"):
        _required_text(
            owner_scope,
            field_name,
            "ae.repaired_response_review.owner_scope_invalid",
        )
    for field_name in ("chat_document_id", "interaction_id"):
        _required_text(
            conversation_scope,
            field_name,
            "ae.repaired_response_review.conversation_scope_invalid",
        )
    controls = _mapping(projection.get("decision_controls"))
    available_actions = _string_list(controls.get("available_actions"))
    primary_actions = _string_list(controls.get("primary_actions"))
    secondary_actions = _string_list(controls.get("secondary_actions"))
    if primary_actions != list(PRIMARY_REVIEW_ACTIONS):
        raise RepairedResponseReviewProjectionError(
            error_code="ae.repaired_response_review.primary_actions_invalid",
            detail="AE repaired response review primary actions are invalid.",
        )
    unknown_actions = sorted(
        set(available_actions + secondary_actions) - set(SUPPORTED_REVIEW_ACTIONS)
    )
    if unknown_actions or not set(PRIMARY_REVIEW_ACTIONS).issubset(available_actions):
        raise RepairedResponseReviewProjectionError(
            error_code="ae.repaired_response_review.available_actions_invalid",
            detail="AE repaired response review actions are invalid.",
        )
    decision_path = _required_text(
        controls,
        "decision_submit_path",
        "ae.repaired_response_review.decision_path_invalid",
    )
    if (
        not decision_path.startswith("/api/v1/chat/interactions/")
        or not decision_path.endswith(SAFE_DECISION_PATH_SUFFIX)
    ):
        raise RepairedResponseReviewProjectionError(
            error_code="ae.repaired_response_review.decision_path_invalid",
            detail="AE repaired response review decision path is invalid.",
        )
    redaction = _mapping(projection.get("redaction_summary"))
    for key in ALLOWED_FALSE_REDACTION_KEYS:
        if redaction.get(key) is not False:
            raise RepairedResponseReviewProjectionError(
                error_code="ae.repaired_response_review.redaction_invalid",
                detail="AE repaired response review redaction flags must be false.",
            )
    assert_repaired_response_review_projection_redaction_safe(projection)
    return dict(projection)


def decision_submit_path_for_handoff(handoff_record: Mapping[str, Any]) -> str:
    links = _mapping(handoff_record.get("links"))
    handoff_path = _required_text(
        links,
        "handoff",
        "ae.repaired_response_review.handoff_path_invalid",
    )
    if not handoff_path.startswith("/api/v1/chat/interactions/"):
        raise RepairedResponseReviewProjectionError(
            error_code="ae.repaired_response_review.handoff_path_invalid",
            detail="AE repaired response handoff path is invalid.",
        )
    return f"{handoff_path.rstrip('/')}{SAFE_DECISION_PATH_SUFFIX}"


def assert_repaired_response_review_projection_redaction_safe(payload: Any) -> None:
    sensitive_keys = find_sensitive_repaired_response_review_projection_keys(payload)
    if sensitive_keys:
        raise RepairedResponseReviewProjectionError(
            error_code="ae.repaired_response_review.sensitive_key",
            detail=(
                "AE repaired response review projection contains sensitive keys: "
                f"{', '.join(sensitive_keys)}"
            ),
        )


def find_sensitive_repaired_response_review_projection_keys(payload: Any) -> list[str]:
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


def _review_actions_from_handoff(value: Any) -> list[str]:
    actions = _string_list(value)
    selected = [action for action in actions if action in SUPPORTED_REVIEW_ACTIONS]
    for action in PRIMARY_REVIEW_ACTIONS:
        if action not in selected:
            selected.append(action)
    return selected


def _sensitive_key_forbidden(key_lower: str, value: Any) -> bool:
    if key_lower in SAFE_USAGE_TOKEN_KEYS:
        return False
    if key_lower in ALLOWED_FALSE_REDACTION_KEYS and value is False:
        return False
    return any(part in key_lower for part in SENSITIVE_REVIEW_KEY_PARTS)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = optional_text(item)
        if text is not None and text not in result:
            result.append(text)
    return result


def _required_text(
    payload: Mapping[str, Any],
    field_name: str,
    error_code: str,
) -> str:
    value = optional_text(payload.get(field_name))
    if value is None:
        raise RepairedResponseReviewProjectionError(
            error_code=error_code,
            detail=f"{field_name} is required.",
        )
    return value


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
