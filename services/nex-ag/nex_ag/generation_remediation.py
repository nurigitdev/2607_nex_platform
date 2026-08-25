from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from nex_ag.generation_remediation_boundary import (
    ALLOWED_REMEDIATION_INTENTS,
    REMEDIATION_STATUS_TRANSITIONS,
    GenerationRemediationBoundaryError,
    assert_generation_remediation_payload_redaction_safe,
)


REMEDIATION_ACTION_SCHEMA_VERSION = "ag_generation_remediation_action.v1"
MAX_EVIDENCE_PREVIEW_LENGTH = 240

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


@dataclass(frozen=True)
class GenerationRemediationError(Exception):
    status_code: int
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


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
