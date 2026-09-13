from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid5

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
DISPATCH_EXECUTION_TRANSITION_PLAN_SCHEMA_VERSION = (
    "ag_operator_review_escalation_dispatch_execution_transition_plan.v1"
)
DISPATCH_EXECUTION_WORKER_RUN_SCHEMA_VERSION = (
    "ag_operator_review_escalation_dispatch_execution_worker_run.v1"
)
DISPATCH_EXECUTION_RESULT_METADATA_SCHEMA_VERSION = (
    "ag_operator_review_escalation_dispatch_execution_result_metadata.v1"
)
DISPATCH_EXECUTION_DEFAULT_PROVIDER_PROFILE = "mock-default"
DISPATCH_EXECUTION_PROVIDER_MODE = "mock_first_only"
DISPATCH_EXECUTION_RESULT_STORAGE = "safe_hashes_statuses_counters_only"
DEFAULT_DISPATCH_EXECUTION_RETRY_DELAY_SECONDS = 300
DEFAULT_DISPATCH_EXECUTION_MAX_ATTEMPTS = 3
DEFAULT_DISPATCH_EXECUTION_BATCH_LIMIT = 10
MAX_DISPATCH_EXECUTION_BATCH_LIMIT = 50

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
    channel_type = optional_text(dispatch.get("channel_type"))
    if normalized_status == "SKIPPED" and channel_type != "MOCK":
        profile = dict(
            DISPATCH_EXECUTION_PROVIDER_PROFILES[
                DISPATCH_EXECUTION_DEFAULT_PROVIDER_PROFILE
            ]
        )
        profile["profile_id"] = (
            optional_text(provider_profile)
            or DISPATCH_EXECUTION_DEFAULT_PROVIDER_PROFILE
        )
    else:
        profile = normalize_dispatch_execution_provider_profile(
            provider_profile or optional_text(dispatch.get("provider_profile")),
            channel_type=channel_type,
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
        "retryable": bool(profile.get("retryable"))
        if normalized_status in {"FAILED", "RETRY_WAIT"}
        else False,
        "last_error_code": optional_text(last_error_code),
        "next_attempt_at": optional_text(next_attempt_at),
        "executed_at": executed_at or _utc_now(),
        "redaction": _dispatch_execution_redaction_flags(),
    }
    assert_dispatch_execution_result_redacted(result)
    return result


@dataclass(frozen=True)
class MockDispatchExecutionProvider:
    profile_id: str = DISPATCH_EXECUTION_DEFAULT_PROVIDER_PROFILE

    def execute(
        self,
        dispatch: Mapping[str, Any],
        *,
        executed_at: str | None = None,
    ) -> dict[str, Any]:
        channel_type = optional_text(dispatch.get("channel_type"))
        if channel_type != "MOCK":
            return build_dispatch_execution_result(
                dispatch,
                execution_status="SKIPPED",
                provider_profile=self.profile_id,
                provider_result_ref=_mock_provider_result_ref(dispatch, self.profile_id),
                safe_result_message=(
                    "Dispatch execution skipped because live outbound delivery "
                    "is deferred in S72."
                ),
                executed_at=executed_at,
            )
        profile = normalize_dispatch_execution_provider_profile(
            self.profile_id,
            channel_type=channel_type,
        )
        status = str(profile["result_status"])
        return build_dispatch_execution_result(
            dispatch,
            execution_status=status,
            provider_profile=profile["profile_id"],
            provider_result_ref=_mock_provider_result_ref(dispatch, profile["profile_id"]),
            safe_result_message=str(profile["safe_result_template"]),
            last_error_code=profile.get("default_error_code") if status == "FAILED" else None,
            executed_at=executed_at,
        )


def build_mock_dispatch_execution_provider(
    profile_id: str | None = None,
) -> MockDispatchExecutionProvider:
    normalized = normalize_dispatch_execution_provider_profile(
        profile_id,
        channel_type="MOCK",
    )
    return MockDispatchExecutionProvider(profile_id=str(normalized["profile_id"]))


def execute_dispatch_with_mock_provider(
    dispatch: Mapping[str, Any],
    *,
    profile_id: str | None = None,
    executed_at: str | None = None,
) -> dict[str, Any]:
    provider = build_mock_dispatch_execution_provider(profile_id)
    return provider.execute(dispatch, executed_at=executed_at)


def build_dispatch_execution_transition_plan(
    dispatch: Mapping[str, Any],
    execution_result: Mapping[str, Any] | None = None,
    *,
    planned_at: str | None = None,
    max_attempts: int = DEFAULT_DISPATCH_EXECUTION_MAX_ATTEMPTS,
    retry_delay_seconds: int = DEFAULT_DISPATCH_EXECUTION_RETRY_DELAY_SECONDS,
) -> dict[str, Any]:
    status = str(dispatch.get("dispatch_status") or "")
    attempt_count = _non_negative_int(dispatch.get("attempt_count"))
    now = planned_at or _utc_now()
    result = execution_result or execute_dispatch_with_mock_provider(
        dispatch,
        executed_at=now,
    )
    assert_dispatch_execution_result_redacted(result)
    plan_id = str(
        uuid5(
            NAMESPACE_URL,
            "ag-operator-review-escalation-dispatch-execution-plan:"
            f"{dispatch.get('dispatch_id') or 'unknown'}:"
            f"{attempt_count}:{result.get('provider_result_hash') or ''}",
        )
    )
    skip_reason = _transition_skip_reason(status)
    if skip_reason is not None:
        return _transition_plan(
            dispatch,
            result,
            plan_id=plan_id,
            plan_status="SKIPPED",
            planned_at=now,
            actions=[],
            skip_reason=skip_reason,
            max_attempts=max_attempts,
            retry_delay_seconds=retry_delay_seconds,
        )
    if status == "FAILED":
        if attempt_count >= max_attempts:
            return _transition_plan(
                dispatch,
                result,
                plan_id=plan_id,
                plan_status="BLOCKED",
                planned_at=now,
                actions=[],
                skip_reason="max_attempts_exhausted",
                max_attempts=max_attempts,
                retry_delay_seconds=retry_delay_seconds,
            )
        actions = [
            _worker_action_payload(
                "RETRY",
                result,
                next_attempt_at=_iso_after_seconds(now, retry_delay_seconds),
            )
        ]
        return _transition_plan(
            dispatch,
            result,
            plan_id=plan_id,
            plan_status="READY",
            planned_at=now,
            actions=actions,
            skip_reason=None,
            max_attempts=max_attempts,
            retry_delay_seconds=retry_delay_seconds,
        )
    actions = [_worker_action_payload("START", result)]
    result_status = str(result.get("execution_status") or "")
    if result_status == "SUCCEEDED":
        actions.append(_worker_action_payload("SUCCEED", result))
    elif result_status == "FAILED":
        actions.append(_worker_action_payload("FAIL", result))
        if bool(result.get("retryable")) and attempt_count + 1 < max_attempts:
            actions.append(
                _worker_action_payload(
                    "RETRY",
                    result,
                    next_attempt_at=_iso_after_seconds(now, retry_delay_seconds),
                )
            )
    elif result_status == "RETRY_WAIT":
        actions.append(
            _worker_action_payload(
                "FAIL",
                {
                    **result,
                    "last_error_code": result.get("last_error_code")
                    or "mock_dispatch_retry_wait",
                },
            )
        )
        actions.append(
            _worker_action_payload(
                "RETRY",
                result,
                next_attempt_at=str(result.get("next_attempt_at")),
            )
        )
    elif result_status == "SKIPPED":
        actions = []
    else:
        raise OperatorReviewNoteError(
            status_code=422,
            error_code=(
                "ag.operator_review_escalation_dispatch_execution_result_status_"
                "unsupported"
            ),
            detail=f"unsupported execution result status: {result_status}",
        )
    return _transition_plan(
        dispatch,
        result,
        plan_id=plan_id,
        plan_status="READY" if actions else "SKIPPED",
        planned_at=now,
        actions=actions,
        skip_reason=None if actions else "provider_execution_skipped",
        max_attempts=max_attempts,
        retry_delay_seconds=retry_delay_seconds,
    )


def run_dispatch_execution_worker_once(
    service: Any,
    *,
    request_id: str,
    trace_id: str | None = None,
    worker_id: str = "ag-dispatch-execution-worker",
    batch_limit: int | None = None,
    provider_profile: str | None = None,
    confirm_run: bool = False,
    dry_run: bool = False,
    executed_at: str | None = None,
) -> dict[str, Any]:
    now = executed_at or _utc_now()
    limit = _bounded_batch_limit(batch_limit)
    run_id = str(
        uuid5(
            NAMESPACE_URL,
            "ag-operator-review-escalation-dispatch-execution-worker-run:"
            f"{worker_id}:{request_id}:{now}:{limit}:{dry_run}",
        )
    )
    if not confirm_run:
        return _worker_run_summary(
            run_id=run_id,
            worker_id=worker_id,
            run_status="BLOCKED",
            request_id=request_id,
            trace_id=trace_id,
            executed_at=now,
            batch_limit=limit,
            items=[],
            blocked_reason="confirm_run_required",
            dry_run=dry_run,
        )
    candidates = _worker_candidate_dispatches(
        service,
        request_id=request_id,
        trace_id=trace_id,
        limit=limit,
    )
    items: list[dict[str, Any]] = []
    for dispatch in candidates[:limit]:
        items.append(
        _execute_worker_item(
                service,
                dispatch,
                run_id=run_id,
                request_id=request_id,
                trace_id=trace_id,
                worker_id=worker_id,
                provider_profile=provider_profile,
                dry_run=dry_run,
                executed_at=now,
            )
        )
    return _worker_run_summary(
        run_id=run_id,
        worker_id=worker_id,
        run_status="COMPLETED",
        request_id=request_id,
        trace_id=trace_id,
        executed_at=now,
        batch_limit=limit,
        items=items,
        blocked_reason=None,
        dry_run=dry_run,
    )


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


def build_dispatch_execution_result_metadata(
    execution_result: Mapping[str, Any],
    *,
    run_id: str,
    worker_id: str,
) -> dict[str, Any]:
    metadata = {
        "execution_result_metadata_schema_version": (
            DISPATCH_EXECUTION_RESULT_METADATA_SCHEMA_VERSION
        ),
        "run_id": run_id,
        "worker_id": worker_id,
        "execution_result_schema_version": execution_result.get(
            "execution_result_schema_version"
        ),
        "execution_status": execution_result.get("execution_status"),
        "recommended_action": execution_result.get("recommended_action"),
        "provider_mode": execution_result.get("provider_mode"),
        "provider_profile": execution_result.get("provider_profile"),
        "provider_result_hash": execution_result.get("provider_result_hash"),
        "safe_result_preview": execution_result.get("safe_result_preview"),
        "retryable": bool(execution_result.get("retryable")),
        "last_error_code": execution_result.get("last_error_code"),
        "next_attempt_at": execution_result.get("next_attempt_at"),
        "executed_at": execution_result.get("executed_at"),
        "result_storage": DISPATCH_EXECUTION_RESULT_STORAGE,
        "redaction": _dispatch_execution_redaction_flags(),
    }
    assert_dispatch_execution_result_redacted(metadata)
    return metadata


def record_dispatch_execution_result_metadata(
    dispatch: Mapping[str, Any],
    execution_result: Mapping[str, Any],
    *,
    run_id: str,
    worker_id: str,
) -> dict[str, Any]:
    metadata = dict(dispatch.get("metadata") or {})
    metadata["last_execution_result"] = build_dispatch_execution_result_metadata(
        execution_result,
        run_id=run_id,
        worker_id=worker_id,
    )
    metadata["last_execution_result_recorded"] = True
    updated = dict(dispatch)
    updated["metadata"] = json.loads(json.dumps(metadata, default=str))
    assert_dispatch_execution_result_redacted(updated["metadata"])
    return updated


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


def _transition_plan(
    dispatch: Mapping[str, Any],
    execution_result: Mapping[str, Any],
    *,
    plan_id: str,
    plan_status: str,
    planned_at: str,
    actions: list[dict[str, Any]],
    skip_reason: str | None,
    max_attempts: int,
    retry_delay_seconds: int,
) -> dict[str, Any]:
    return {
        "transition_plan_schema_version": (
            DISPATCH_EXECUTION_TRANSITION_PLAN_SCHEMA_VERSION
        ),
        "transition_plan_id": plan_id,
        "dispatch_id": str(dispatch.get("dispatch_id") or ""),
        "dispatch_status": str(dispatch.get("dispatch_status") or ""),
        "attempt_count": _non_negative_int(dispatch.get("attempt_count")),
        "execution_result_schema_version": execution_result.get(
            "execution_result_schema_version"
        ),
        "execution_status": execution_result.get("execution_status"),
        "plan_status": plan_status,
        "skip_reason": skip_reason,
        "actions": actions,
        "max_attempts": max_attempts,
        "retry_delay_seconds": retry_delay_seconds,
        "planned_at": planned_at,
        "redaction": _dispatch_execution_redaction_flags(),
    }


def _worker_candidate_dispatches(
    service: Any,
    *,
    request_id: str,
    trace_id: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for status in ("PENDING", "RETRY_WAIT", "FAILED"):
        response = service.list_escalation_dispatches(
            request_id=request_id,
            trace_id=trace_id,
            dispatch_status=status,
            limit=limit,
        )
        for item in response.get("items") or []:
            dispatch_id = str(item.get("dispatch_id") or "")
            if dispatch_id and dispatch_id not in seen:
                seen.add(dispatch_id)
                selected.append(item)
            if len(selected) >= limit:
                return selected
    return selected


def _execute_worker_item(
    service: Any,
    dispatch: Mapping[str, Any],
    *,
    run_id: str,
    request_id: str,
    trace_id: str | None,
    worker_id: str,
    provider_profile: str | None,
    dry_run: bool,
    executed_at: str,
) -> dict[str, Any]:
    result = execute_dispatch_with_mock_provider(
        dispatch,
        profile_id=provider_profile,
        executed_at=executed_at,
    )
    plan = build_dispatch_execution_transition_plan(
        dispatch,
        result,
        planned_at=executed_at,
    )
    final_status = str(dispatch.get("dispatch_status") or "")
    mutations: list[dict[str, Any]] = []
    result_metadata_persisted = False
    if not dry_run:
        for index, action in enumerate(plan["actions"]):
            mutation = service.apply_escalation_dispatch_action(
                str(dispatch.get("dispatch_id") or ""),
                action,
                request_id=request_id,
                trace_id=trace_id,
                idempotency_key=_worker_action_idempotency_key(
                    worker_id,
                    dispatch,
                    action,
                    index,
                    result,
                ),
            )
            mutations.append(
                {
                    "action_type": mutation.get("action", {}).get("action_type"),
                    "to_status": mutation.get("action", {}).get("to_status"),
                    "idempotency_status": mutation.get("idempotency_status"),
                }
            )
            final_status = str(mutation.get("dispatch", {}).get("dispatch_status") or "")
        result_metadata_persisted = _persist_worker_result_metadata(
            service,
            str(dispatch.get("dispatch_id") or ""),
            result,
            run_id=run_id,
            worker_id=worker_id,
        )
    item = {
        "dispatch_id": str(dispatch.get("dispatch_id") or ""),
        "initial_status": str(dispatch.get("dispatch_status") or ""),
        "final_status": final_status,
        "execution_status": result.get("execution_status"),
        "provider_profile": result.get("provider_profile"),
        "provider_result_hash": result.get("provider_result_hash"),
        "plan_status": plan.get("plan_status"),
        "skip_reason": plan.get("skip_reason"),
        "action_count": len(plan["actions"]),
        "actions": mutations if not dry_run else [],
        "dry_run": dry_run,
        "result_metadata_persisted": result_metadata_persisted,
        "redaction": _dispatch_execution_redaction_flags(),
    }
    assert_dispatch_execution_result_redacted(item)
    return item


def _persist_worker_result_metadata(
    service: Any,
    dispatch_id: str,
    execution_result: Mapping[str, Any],
    *,
    run_id: str,
    worker_id: str,
) -> bool:
    if not dispatch_id:
        return False
    store = getattr(service, "_dispatch_store", None)
    if store is None or not hasattr(store, "save"):
        return False
    current = service.get_escalation_dispatch(dispatch_id)
    updated = record_dispatch_execution_result_metadata(
        current,
        execution_result,
        run_id=run_id,
        worker_id=worker_id,
    )
    store.save(updated)
    return True


def _worker_run_summary(
    *,
    run_id: str,
    worker_id: str,
    run_status: str,
    request_id: str,
    trace_id: str | None,
    executed_at: str,
    batch_limit: int,
    items: list[dict[str, Any]],
    blocked_reason: str | None,
    dry_run: bool,
) -> dict[str, Any]:
    summary = {
        "worker_run_schema_version": DISPATCH_EXECUTION_WORKER_RUN_SCHEMA_VERSION,
        "run_id": run_id,
        "worker_id": worker_id,
        "run_status": run_status,
        "blocked_reason": blocked_reason,
        "request_id": request_id,
        "trace_id": trace_id,
        "executed_at": executed_at,
        "batch_limit": batch_limit,
        "candidate_count": len(items),
        "processed_count": sum(
            1 for item in items if item.get("plan_status") == "READY"
        ),
        "succeeded_count": sum(
            1 for item in items if item.get("final_status") == "SUCCEEDED"
        ),
        "failed_count": sum(
            1 for item in items if item.get("final_status") == "FAILED"
        ),
        "retry_wait_count": sum(
            1 for item in items if item.get("final_status") == "RETRY_WAIT"
        ),
        "skipped_count": sum(
            1 for item in items if item.get("plan_status") == "SKIPPED"
        ),
        "blocked_count": sum(
            1 for item in items if item.get("plan_status") == "BLOCKED"
        ),
        "dry_run": dry_run,
        "items": items,
        "redaction": _dispatch_execution_redaction_flags(),
    }
    assert_dispatch_execution_result_redacted(summary)
    return summary


def _worker_action_payload(
    action_type: str,
    execution_result: Mapping[str, Any],
    *,
    next_attempt_at: str | None = None,
) -> dict[str, Any]:
    payload = {
        "action_type": action_type,
        "operator_ref": {"operator_type": "service", "operator_id": "nex-ag"},
        "reason_codes": [f"dispatch_execution_{action_type.lower()}"],
        "metadata": {
            "execution_result_schema_version": execution_result.get(
                "execution_result_schema_version"
            ),
            "execution_status": execution_result.get("execution_status"),
            "provider_profile": execution_result.get("provider_profile"),
            "provider_result_hash": execution_result.get("provider_result_hash"),
            "safe_result_preview": execution_result.get("safe_result_preview"),
            "worker_result_storage": DISPATCH_EXECUTION_RESULT_STORAGE,
            "sensitive_material_storage": "omitted",
        },
    }
    if action_type == "FAIL":
        payload["last_error_code"] = (
            optional_text(execution_result.get("last_error_code"))
            or "mock_dispatch_execution_failed"
        )
        payload["last_error"] = (
            "Dispatch execution failed. See safe provider result hash."
        )
    if action_type == "RETRY":
        payload["next_attempt_at"] = next_attempt_at
    assert_dispatch_execution_result_redacted(payload)
    return payload


def _worker_action_idempotency_key(
    worker_id: str,
    dispatch: Mapping[str, Any],
    action: Mapping[str, Any],
    index: int,
    execution_result: Mapping[str, Any],
) -> str:
    return (
        "ag-dispatch-execution-worker:"
        f"{worker_id}:"
        f"{dispatch.get('dispatch_id') or 'unknown'}:"
        f"{action.get('action_type') or 'action'}:"
        f"{index}:"
        f"{execution_result.get('provider_result_hash') or 'result'}"
    )


def _bounded_batch_limit(value: int | None) -> int:
    if value is None:
        return DEFAULT_DISPATCH_EXECUTION_BATCH_LIMIT
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return DEFAULT_DISPATCH_EXECUTION_BATCH_LIMIT
    return max(1, min(parsed, MAX_DISPATCH_EXECUTION_BATCH_LIMIT))


def _transition_skip_reason(dispatch_status: str) -> str | None:
    if dispatch_status in {"SUCCEEDED", "CANCELLED"}:
        return "terminal_dispatch_status"
    if dispatch_status == "DISPATCHING":
        return "dispatch_already_in_progress"
    if dispatch_status in {"PENDING", "RETRY_WAIT", "FAILED"}:
        return None
    return "unsupported_dispatch_status"


def _non_negative_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(parsed, 0)


def _iso_after_seconds(value: str, seconds: int) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (parsed + timedelta(seconds=max(int(seconds), 0))).isoformat().replace(
        "+00:00",
        "Z",
    )


def _mock_provider_result_ref(dispatch: Mapping[str, Any], profile_id: str) -> str:
    return (
        "mock-dispatch-execution:"
        f"{dispatch.get('dispatch_id') or 'unknown'}:"
        f"{profile_id}:"
        f"{dispatch.get('attempt_count') or 0}"
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
