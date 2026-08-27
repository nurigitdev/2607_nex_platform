from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5


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


@dataclass(frozen=True)
class RepairedResponseHandoffError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


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


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
