from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


GENERATION_FEEDBACK_BOUNDARY_DECISION_VERSION = (
    "ae_generation_feedback_boundary_decision.v1"
)
GENERATION_FEEDBACK_CONTRACT_VERSION = "ae_generation_feedback.v1"

AE_FEEDBACK_OWNER_SERVICE = "nex-ae-api"
CX_GENERATION_LINEAGE_OWNER_SERVICE = "nex-cx"
AG_OPERATOR_DISPOSITION_OWNER_SERVICE = "nex-ag"

ALLOWED_FEEDBACK_VALUES = ("positive", "negative", "neutral")
ALLOWED_FEEDBACK_REASONS = (
    "helpful",
    "not_helpful",
    "incorrect",
    "citation_issue",
    "irrelevant",
    "incomplete",
    "unsafe",
    "slow",
    "other",
)

SAFE_FEEDBACK_STORAGE_FIELDS = (
    "feedback_id",
    "tenant_id",
    "user_id",
    "interaction_id",
    "chat_document_id",
    "cx_generation_id",
    "trace_id",
    "request_id",
    "feedback_value",
    "feedback_reasons",
    "feedback_comment_hash",
    "feedback_comment_preview",
    "quality_issue_refs",
    "metadata",
    "created_at",
)

RAW_CONTENT_POLICY = {
    "raw_user_prompt_stored": False,
    "raw_generation_output_stored": False,
    "raw_source_document_text_stored": False,
    "credential_material_stored": False,
    "free_text_comment_storage": "hash_and_short_preview_only",
}

SENSITIVE_KEY_PARTS = (
    "api_key",
    "authorization",
    "credential",
    "password",
    "passwd",
    "raw_generation_output",
    "raw_output",
    "raw_prompt",
    "raw_source",
    "raw_text",
    "raw_user_message",
    "secret",
    "source_text",
    "token",
)


@dataclass(frozen=True)
class GenerationFeedbackBoundaryError(ValueError):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


def build_generation_feedback_boundary_decision() -> dict[str, Any]:
    return {
        "decision_schema_version": GENERATION_FEEDBACK_BOUNDARY_DECISION_VERSION,
        "decision_id": "s34.generation_feedback_disposition_boundary.v1",
        "slice_id": "0331",
        "status": "accepted",
        "owner_services": {
            "user_feedback_intake": AE_FEEDBACK_OWNER_SERVICE,
            "generation_lineage": CX_GENERATION_LINEAGE_OWNER_SERVICE,
            "operator_disposition": AG_OPERATOR_DISPOSITION_OWNER_SERVICE,
        },
        "storage_contract": {
            "feedback_contract_version": GENERATION_FEEDBACK_CONTRACT_VERSION,
            "safe_fields": list(SAFE_FEEDBACK_STORAGE_FIELDS),
            "raw_content_policy": dict(RAW_CONTENT_POLICY),
            "allowed_feedback_values": list(ALLOWED_FEEDBACK_VALUES),
            "allowed_feedback_reasons": list(ALLOWED_FEEDBACK_REASONS),
        },
        "cross_service_refs": {
            "required": [
                "tenant_id",
                "user_id",
                "interaction_id",
                "trace_id",
                "request_id",
            ],
            "optional": [
                "chat_document_id",
                "cx_generation_id",
                "quality_issue_refs",
            ],
        },
        "next_slices": {
            "0332": "freeze AE feedback contract/schema",
            "0333": "wire AE feedback intake API with regression",
            "0334": "prove AE feedback persistence with nex_ae_test PostgreSQL smoke",
        },
    }


def validate_generation_feedback_boundary_decision(
    decision: Mapping[str, Any],
) -> dict[str, Any]:
    if decision.get("decision_schema_version") != GENERATION_FEEDBACK_BOUNDARY_DECISION_VERSION:
        raise GenerationFeedbackBoundaryError(
            error_code="ae.feedback_boundary.schema_version_invalid",
            detail="Generation feedback boundary decision schema version is invalid.",
        )

    owners = _mapping(decision.get("owner_services"))
    expected_owners = {
        "user_feedback_intake": AE_FEEDBACK_OWNER_SERVICE,
        "generation_lineage": CX_GENERATION_LINEAGE_OWNER_SERVICE,
        "operator_disposition": AG_OPERATOR_DISPOSITION_OWNER_SERVICE,
    }
    if owners != expected_owners:
        raise GenerationFeedbackBoundaryError(
            error_code="ae.feedback_boundary.owner_services_invalid",
            detail="Generation feedback boundary owner services are not canonical.",
        )

    storage_contract = _mapping(decision.get("storage_contract"))
    raw_policy = _mapping(storage_contract.get("raw_content_policy"))
    if any(raw_policy.get(key) is not False for key in RAW_CONTENT_POLICY if key.endswith("_stored")):
        raise GenerationFeedbackBoundaryError(
            error_code="ae.feedback_boundary.raw_content_policy_invalid",
            detail="Generation feedback boundary must not store raw prompt/output/source content.",
        )

    sensitive_fields = find_sensitive_feedback_keys(
        {field: True for field in storage_contract.get("safe_fields", [])}
    )
    if sensitive_fields:
        raise GenerationFeedbackBoundaryError(
            error_code="ae.feedback_boundary.safe_field_sensitive",
            detail=f"Feedback safe fields contain sensitive keys: {', '.join(sensitive_fields)}",
        )

    return dict(decision)


def find_sensitive_feedback_keys(payload: Mapping[str, Any]) -> list[str]:
    matches: list[str] = []
    _collect_sensitive_keys(payload, path="", matches=matches)
    return matches


def assert_feedback_payload_redaction_safe(payload: Mapping[str, Any]) -> None:
    sensitive_keys = find_sensitive_feedback_keys(payload)
    if sensitive_keys:
        raise GenerationFeedbackBoundaryError(
            error_code="ae.feedback_payload.sensitive_key",
            detail=f"Feedback payload contains sensitive keys: {', '.join(sensitive_keys)}",
        )


def _collect_sensitive_keys(
    value: Any,
    *,
    path: str,
    matches: list[str],
) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}" if path else key_text
            if _is_sensitive_key(key_text):
                matches.append(child_path)
            _collect_sensitive_keys(child, path=child_path, matches=matches)
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _collect_sensitive_keys(child, path=f"{path}[{index}]", matches=matches)


def _is_sensitive_key(key: str) -> bool:
    normalized = key.strip().lower()
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}
