from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any, Mapping

from nex_ag.operator_reviews import (
    OperatorReviewNoteError,
    operator_note_preview,
    optional_text,
    sha256_text,
)


DISPATCH_EXECUTION_PROVIDER_CATALOG_SCHEMA_VERSION = (
    "ag_operator_review_escalation_dispatch_execution_provider_catalog.v1"
)
DISPATCH_EXECUTION_RESULT_SCHEMA_VERSION = (
    "ag_operator_review_escalation_dispatch_execution_result.v1"
)
DISPATCH_EXECUTION_DEFAULT_PROVIDER_PROFILE = "mock-default"
DISPATCH_EXECUTION_PROVIDER_MODE = "mock_first_only"
DISPATCH_EXECUTION_RESULT_STORAGE = "safe_hashes_statuses_counters_only"

ALLOWED_DISPATCH_EXECUTION_RESULT_STATUSES = (
    "SUCCEEDED",
    "FAILED",
    "RETRY_WAIT",
    "SKIPPED",
)
DISPATCH_EXECUTION_RESULT_ACTIONS = {
    "SUCCEEDED": "SUCCEED",
    "FAILED": "FAIL",
    "RETRY_WAIT": "RETRY",
    "SKIPPED": None,
}
DISPATCH_EXECUTION_PROVIDER_PROFILES = {
    "mock-default": {
        "profile_id": "mock-default",
        "provider_type": "mock",
        "channel_type": "MOCK",
        "result_status": "SUCCEEDED",
        "retryable": False,
        "live_delivery": False,
        "external_network": False,
        "safe_result_template": "Mock dispatch delivered.",
    },
    "mock-failure": {
        "profile_id": "mock-failure",
        "provider_type": "mock",
        "channel_type": "MOCK",
        "result_status": "FAILED",
        "retryable": True,
        "live_delivery": False,
        "external_network": False,
        "safe_result_template": "Mock dispatch failed.",
        "default_error_code": "mock_dispatch_failed",
    },
}
FORBIDDEN_DISPATCH_EXECUTION_RESULT_KEYS = {
    "action_comment",
    "artifact_binary_payload",
    "database_url",
    "external_incident_payload",
    "external_incident_token",
    "idempotency_key",
    "notification_payload",
    "notification_secret",
    "provider_api_key",
    "provider_payload",
    "raw_action_comment",
    "raw_case_comment",
    "raw_evidence_body",
    "raw_external_incident_payload",
    "raw_generation_output_text",
    "raw_notification_payload",
    "raw_operator_note_text",
    "raw_prompt_text",
    "raw_provider_payload",
    "raw_source_document_text",
    "secret",
    "service_token",
    "storage_path",
    "storage_uri",
}
SENSITIVE_DISPATCH_EXECUTION_REDACTION_FLAGS = {
    "database_urls_included",
    "external_incident_payload_included",
    "idempotency_keys_included",
    "notification_payload_included",
    "provider_payloads_included",
    "provider_secrets_included",
    "raw_action_comment_included",
    "raw_external_incident_payload_included",
    "raw_notification_payload_included",
    "raw_operator_comments_included",
    "raw_provider_error_included",
    "raw_provider_payload_included",
    "raw_prompt_included",
    "raw_source_text_included",
    "storage_paths_included",
    "tokens_included",
}
SENSITIVE_DISPATCH_EXECUTION_VALUE_PATTERNS = (
    re.compile(r"postgresql(?:\+psycopg)?://[^*\s]+:[^*\s]+@"),
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=@-]+"),
    re.compile(r"ed6@c496em"),
    re.compile(r"nuri1004"),
    re.compile(r"/data/nex-platform"),
)


def build_dispatch_execution_provider_catalog() -> dict[str, Any]:
    return {
        "provider_catalog_schema_version": (
            DISPATCH_EXECUTION_PROVIDER_CATALOG_SCHEMA_VERSION
        ),
        "provider_mode": DISPATCH_EXECUTION_PROVIDER_MODE,
        "default_provider_profile": DISPATCH_EXECUTION_DEFAULT_PROVIDER_PROFILE,
        "live_provider_execution": False,
        "outbound_network_delivery": False,
        "eligible_channel_types": ["MOCK"],
        "profiles": {
            profile_id: dict(profile)
            for profile_id, profile in DISPATCH_EXECUTION_PROVIDER_PROFILES.items()
        },
        "result_contract": {
            "schema_version": DISPATCH_EXECUTION_RESULT_SCHEMA_VERSION,
            "storage": DISPATCH_EXECUTION_RESULT_STORAGE,
            "allowed_statuses": list(ALLOWED_DISPATCH_EXECUTION_RESULT_STATUSES),
            "recommended_actions": dict(DISPATCH_EXECUTION_RESULT_ACTIONS),
        },
        "redaction": _dispatch_execution_redaction_flags(),
    }


def normalize_dispatch_execution_provider_profile(
    provider_profile: str | None,
    *,
    channel_type: str | None,
) -> dict[str, Any]:
    profile_id = optional_text(provider_profile) or DISPATCH_EXECUTION_DEFAULT_PROVIDER_PROFILE
    profile = DISPATCH_EXECUTION_PROVIDER_PROFILES.get(profile_id)
    if profile is None:
        raise OperatorReviewNoteError(
            status_code=422,
            error_code=(
                "ag.operator_review_escalation_dispatch_execution_provider_"
                "profile_unsupported"
            ),
            detail=f"Unsupported dispatch execution provider_profile: {profile_id}",
        )
    if channel_type is not None and channel_type != profile["channel_type"]:
        raise OperatorReviewNoteError(
            status_code=409,
            error_code=(
                "ag.operator_review_escalation_dispatch_execution_provider_"
                "channel_deferred"
            ),
            detail=(
                "S72 dispatch execution starts with MOCK channel profiles only."
            ),
        )
    return dict(profile)


def build_dispatch_execution_result(
    dispatch: Mapping[str, Any],
    *,
    execution_status: str = "SUCCEEDED",
    provider_profile: str | None = None,
    provider_result_ref: str | None = None,
    safe_result_message: str | None = None,
    last_error_code: str | None = None,
    next_attempt_at: str | None = None,
    executed_at: str | None = None,
) -> dict[str, Any]:
    normalized_status = _required_execution_status(execution_status)
    profile = normalize_dispatch_execution_provider_profile(
        provider_profile or optional_text(dispatch.get("provider_profile")),
        channel_type=optional_text(dispatch.get("channel_type")),
    )
    if normalized_status == "FAILED" and optional_text(last_error_code) is None:
        raise OperatorReviewNoteError(
            status_code=422,
            error_code=(
                "ag.operator_review_escalation_dispatch_execution_error_code_required"
            ),
            detail="FAILED execution results require last_error_code.",
        )
    if normalized_status == "RETRY_WAIT" and optional_text(next_attempt_at) is None:
        raise OperatorReviewNoteError(
            status_code=422,
            error_code=(
                "ag.operator_review_escalation_dispatch_execution_retry_at_required"
            ),
            detail="RETRY_WAIT execution results require next_attempt_at.",
        )
    ref = optional_text(provider_result_ref) or _default_provider_result_ref(
        dispatch,
        normalized_status,
    )
    safe_message = optional_text(safe_result_message) or profile["safe_result_template"]
    result = {
        "execution_result_schema_version": DISPATCH_EXECUTION_RESULT_SCHEMA_VERSION,
        "dispatch_id": str(dispatch.get("dispatch_id") or ""),
        "escalation_id": str(dispatch.get("escalation_id") or ""),
        "case_id": str(dispatch.get("case_id") or ""),
        "dispatch_status_before": str(dispatch.get("dispatch_status") or ""),
        "dispatch_intent": str(dispatch.get("dispatch_intent") or ""),
        "channel_type": str(dispatch.get("channel_type") or ""),
        "execution_status": normalized_status,
        "recommended_action": DISPATCH_EXECUTION_RESULT_ACTIONS[normalized_status],
        "provider_mode": DISPATCH_EXECUTION_PROVIDER_MODE,
        "provider_profile": profile["profile_id"],
        "provider_result_ref": {
            "provider_type": profile["provider_type"],
            "provider_id": str(
                (dispatch.get("provider_ref") or {}).get("provider_id")
                if isinstance(dispatch.get("provider_ref"), dict)
                else "mock-escalation-dispatch"
            ),
            "provider_profile": profile["profile_id"],
            "provider_result_hash": sha256_text(ref),
        },
        "provider_result_hash": sha256_text(
            json.dumps(
                {
                    "dispatch_id": dispatch.get("dispatch_id"),
                    "status": normalized_status,
                    "ref": ref,
                    "message": safe_message,
                },
                sort_keys=True,
            )
        ),
        "safe_result_preview": operator_note_preview(safe_message),
        "last_error_code": optional_text(last_error_code),
        "next_attempt_at": optional_text(next_attempt_at),
        "executed_at": executed_at or _utc_now(),
        "redaction": _dispatch_execution_redaction_flags(),
    }
    assert_dispatch_execution_result_redacted(result)
    return result


def assert_dispatch_execution_result_redacted(payload: Any) -> None:
    leaks = _forbidden_result_key_paths(payload)
    if leaks:
        raise OperatorReviewNoteError(
            status_code=422,
            error_code="ag.operator_review_escalation_dispatch_execution_result_leak",
            detail=f"Unsafe dispatch execution result keys: {', '.join(leaks)}",
        )
    unsafe_flags = _unsafe_redaction_flag_paths(payload)
    if unsafe_flags:
        raise OperatorReviewNoteError(
            status_code=422,
            error_code=(
                "ag.operator_review_escalation_dispatch_execution_redaction_flag_leak"
            ),
            detail=f"Unsafe dispatch execution redaction flags: {', '.join(unsafe_flags)}",
        )
    serialized = json.dumps(payload, ensure_ascii=False, default=str)
    for pattern in SENSITIVE_DISPATCH_EXECUTION_VALUE_PATTERNS:
        if pattern.search(serialized):
            raise OperatorReviewNoteError(
                status_code=422,
                error_code=(
                    "ag.operator_review_escalation_dispatch_execution_sensitive_"
                    "value_leak"
                ),
                detail="Dispatch execution result contains a sensitive value.",
            )


def _required_execution_status(value: str | None) -> str:
    normalized = optional_text(value)
    if normalized not in ALLOWED_DISPATCH_EXECUTION_RESULT_STATUSES:
        raise OperatorReviewNoteError(
            status_code=422,
            error_code=(
                "ag.operator_review_escalation_dispatch_execution_status_unsupported"
            ),
            detail=f"unsupported execution_status: {value}",
        )
    return normalized


def _dispatch_execution_redaction_flags() -> dict[str, Any]:
    return {
        "raw_notification_payload_included": False,
        "raw_external_incident_payload_included": False,
        "raw_provider_payload_included": False,
        "raw_provider_error_included": False,
        "raw_action_comment_included": False,
        "raw_source_text_included": False,
        "provider_secrets_included": False,
        "database_urls_included": False,
        "tokens_included": False,
        "idempotency_keys_included": False,
        "result_storage": DISPATCH_EXECUTION_RESULT_STORAGE,
    }


def _forbidden_result_key_paths(payload: Any, prefix: str = "") -> list[str]:
    if isinstance(payload, Mapping):
        paths: list[str] = []
        for key, value in payload.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            if key_text in FORBIDDEN_DISPATCH_EXECUTION_RESULT_KEYS:
                paths.append(path)
            paths.extend(_forbidden_result_key_paths(value, path))
        return paths
    if isinstance(payload, list):
        paths = []
        for index, value in enumerate(payload):
            path = f"{prefix}[{index}]" if prefix else f"[{index}]"
            paths.extend(_forbidden_result_key_paths(value, path))
        return paths
    return []


def _unsafe_redaction_flag_paths(payload: Any, prefix: str = "") -> list[str]:
    if isinstance(payload, Mapping):
        paths: list[str] = []
        for key, value in payload.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            if key_text in SENSITIVE_DISPATCH_EXECUTION_REDACTION_FLAGS and value is True:
                paths.append(path)
            paths.extend(_unsafe_redaction_flag_paths(value, path))
        return paths
    if isinstance(payload, list):
        paths = []
        for index, value in enumerate(payload):
            path = f"{prefix}[{index}]" if prefix else f"[{index}]"
            paths.extend(_unsafe_redaction_flag_paths(value, path))
        return paths
    return []


def _default_provider_result_ref(
    dispatch: Mapping[str, Any],
    execution_status: str,
) -> str:
    return (
        "ag-dispatch-execution:"
        f"{dispatch.get('dispatch_id') or 'unknown'}:"
        f"{execution_status}:"
        f"{dispatch.get('attempt_count') or 0}"
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
