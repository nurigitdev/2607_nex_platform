from __future__ import annotations

import json
import re
import socket
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
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
DISPATCH_EXECUTION_DAEMON_POLICY_SCHEMA_VERSION = (
    "ag_operator_review_escalation_dispatch_execution_daemon_policy.v1"
)
DISPATCH_EXECUTION_DAEMON_TICK_PLAN_SCHEMA_VERSION = (
    "ag_operator_review_escalation_dispatch_execution_daemon_tick_plan.v1"
)
DISPATCH_EXECUTION_DAEMON_TICK_RESULT_SCHEMA_VERSION = (
    "ag_operator_review_escalation_dispatch_execution_daemon_tick_result.v1"
)
DISPATCH_EXECUTION_DAEMON_TICK_EVENT_SCHEMA_VERSION = (
    "ag_operator_review_escalation_dispatch_execution_daemon_tick_event.v1"
)
DISPATCH_EXECUTION_DAEMON_TICK_LOG_SCHEMA_VERSION = (
    "ag_operator_review_escalation_dispatch_execution_daemon_tick_log.v1"
)
DISPATCH_EXECUTION_DAEMON_CONTROL_REQUEST_SCHEMA_VERSION = (
    "ag_operator_review_escalation_dispatch_execution_daemon_control_request.v1"
)
DISPATCH_EXECUTION_DAEMON_CONTROL_ADMISSION_SCHEMA_VERSION = (
    "ag_operator_review_escalation_dispatch_execution_daemon_control_admission.v1"
)
DISPATCH_EXECUTION_RESULT_METADATA_SCHEMA_VERSION = (
    "ag_operator_review_escalation_dispatch_execution_result_metadata.v1"
)
DISPATCH_EXECUTION_PROVIDER_CONFIG_SCHEMA_VERSION = (
    "ag_operator_review_escalation_dispatch_provider_config.v1"
)
DISPATCH_NOTIFICATION_PROVIDER_REQUEST_SCHEMA_VERSION = (
    "ag_operator_review_escalation_dispatch_notification_request.v1"
)
DISPATCH_EXTERNAL_INCIDENT_PROVIDER_REQUEST_SCHEMA_VERSION = (
    "ag_operator_review_escalation_dispatch_external_incident_request.v1"
)
DISPATCH_LIVE_HTTP_TRANSPORT_ENVELOPE_SCHEMA_VERSION = (
    "ag_operator_review_escalation_dispatch_live_http_transport_envelope.v1"
)
DISPATCH_LIVE_HTTP_TRANSPORT_REQUEST_PLAN_SCHEMA_VERSION = (
    "ag_operator_review_escalation_dispatch_live_http_transport_request_plan.v1"
)
DISPATCH_PROVIDER_HTTP_CLIENT_RESULT_SCHEMA_VERSION = (
    "ag_operator_review_escalation_dispatch_provider_http_client_result.v1"
)
DISPATCH_EXECUTION_DEFAULT_PROVIDER_PROFILE = "mock-default"
DISPATCH_EXECUTION_PROVIDER_MODE = "mock_first_only"
DISPATCH_EXECUTION_RESULT_STORAGE = "safe_hashes_statuses_counters_only"
DEFAULT_DISPATCH_EXECUTION_RETRY_DELAY_SECONDS = 300
DEFAULT_DISPATCH_EXECUTION_MAX_ATTEMPTS = 3
DEFAULT_DISPATCH_EXECUTION_BATCH_LIMIT = 10
MAX_DISPATCH_EXECUTION_BATCH_LIMIT = 50
DEFAULT_DISPATCH_EXECUTION_DAEMON_CYCLE_LIMIT = 1
MAX_DISPATCH_EXECUTION_DAEMON_CYCLE_LIMIT = 10
DEFAULT_DISPATCH_EXECUTION_DAEMON_INTERVAL_SECONDS = 60
MIN_DISPATCH_EXECUTION_DAEMON_INTERVAL_SECONDS = 1
MAX_DISPATCH_EXECUTION_DAEMON_INTERVAL_SECONDS = 3600
DEFAULT_DISPATCH_HTTP_TIMEOUT_SECONDS = 15.0
DEFAULT_DISPATCH_HTTP_CONNECT_TIMEOUT_SECONDS = 5.0
DEFAULT_DISPATCH_HTTP_READ_TIMEOUT_SECONDS = 15.0
DEFAULT_DISPATCH_HTTP_MAX_RETRIES = 2
DEFAULT_DISPATCH_HTTP_BACKOFF_SECONDS = 1.0
MAX_DISPATCH_HTTP_TIMEOUT_SECONDS = 120.0
MAX_DISPATCH_HTTP_MAX_RETRIES = 5
DISPATCH_LIVE_HTTP_TRANSPORT_USER_AGENT = (
    "nex-ag-dispatch-live-http-transport/1.0"
)

DISPATCH_EXECUTION_PROVIDER_MODE_ENV = "NEX_AG_DISPATCH_EXECUTION_PROVIDER_MODE"
DISPATCH_EXECUTION_PROVIDER_PROFILE_ENV = (
    "NEX_AG_DISPATCH_EXECUTION_PROVIDER_PROFILE"
)
DISPATCH_LIVE_PROVIDER_MODE_ENV = "NEX_AG_DISPATCH_LIVE_PROVIDER_MODE"
DISPATCH_LIVE_PROVIDER_PROFILE_ENV = "NEX_AG_DISPATCH_LIVE_PROVIDER_PROFILE"
DISPATCH_LIVE_PROVIDER_ENABLE_ENV = "NEX_AG_DISPATCH_LIVE_PROVIDER_ENABLE"
DISPATCH_HTTP_TIMEOUT_SECONDS_ENV = "NEX_AG_DISPATCH_HTTP_TIMEOUT_SECONDS"
DISPATCH_HTTP_CONNECT_TIMEOUT_SECONDS_ENV = (
    "NEX_AG_DISPATCH_HTTP_CONNECT_TIMEOUT_SECONDS"
)
DISPATCH_HTTP_READ_TIMEOUT_SECONDS_ENV = "NEX_AG_DISPATCH_HTTP_READ_TIMEOUT_SECONDS"
DISPATCH_HTTP_MAX_RETRIES_ENV = "NEX_AG_DISPATCH_HTTP_MAX_RETRIES"
DISPATCH_HTTP_BACKOFF_SECONDS_ENV = "NEX_AG_DISPATCH_HTTP_BACKOFF_SECONDS"
DISPATCH_NOTIFICATION_WEBHOOK_URL_ENV = "NEX_AG_NOTIFICATION_WEBHOOK_URL"
DISPATCH_NOTIFICATION_SERVICE_TOKEN_ENV = "NEX_AG_NOTIFICATION_SERVICE_TOKEN"
DISPATCH_EXTERNAL_INCIDENT_BASE_URL_ENV = "NEX_AG_EXTERNAL_INCIDENT_BASE_URL"
DISPATCH_EXTERNAL_INCIDENT_TOKEN_ENV = "NEX_AG_EXTERNAL_INCIDENT_TOKEN"
DISPATCH_EXECUTION_DAEMON_ENABLED_ENV = "NEX_AG_DISPATCH_DAEMON_ENABLED"
DISPATCH_EXECUTION_DAEMON_DRY_RUN_ENV = "NEX_AG_DISPATCH_DAEMON_DRY_RUN"
DISPATCH_EXECUTION_DAEMON_BATCH_LIMIT_ENV = "NEX_AG_DISPATCH_DAEMON_BATCH_LIMIT"
DISPATCH_EXECUTION_DAEMON_CYCLE_LIMIT_ENV = "NEX_AG_DISPATCH_DAEMON_CYCLE_LIMIT"
DISPATCH_EXECUTION_DAEMON_INTERVAL_SECONDS_ENV = (
    "NEX_AG_DISPATCH_DAEMON_INTERVAL_SECONDS"
)
DISPATCH_EXECUTION_DAEMON_PROVIDER_MODE_ENV = (
    "NEX_AG_DISPATCH_DAEMON_PROVIDER_MODE"
)

ALLOWED_DISPATCH_EXECUTION_RESULT_STATUSES = (
    "SUCCEEDED",
    "FAILED",
    "RETRY_WAIT",
    "SKIPPED",
)
ALLOWED_DISPATCH_EXECUTION_PROVIDER_MODES = (
    "mock_first_only",
    "mock_http",
    "live_http",
)
ALLOWED_DISPATCH_EXECUTION_DAEMON_CONTROL_ACTIONS = (
    "tick_plan",
    "tick_once",
)
NOTIFICATION_DISPATCH_CHANNEL_TYPES = ("NOTIFICATION", "EMAIL", "WEBHOOK")
EXTERNAL_INCIDENT_DISPATCH_CHANNEL_TYPES = ("INCIDENT",)
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
DISPATCH_LIVE_PROVIDER_PROFILES = {
    "notification-webhook-default": {
        "profile_id": "notification-webhook-default",
        "provider_type": "notification_webhook",
        "channel_types": ["NOTIFICATION", "WEBHOOK"],
        "endpoint_env": DISPATCH_NOTIFICATION_WEBHOOK_URL_ENV,
        "token_env": DISPATCH_NOTIFICATION_SERVICE_TOKEN_ENV,
        "network_required": True,
        "mock_transport_supported": True,
    },
    "email-notification-default": {
        "profile_id": "email-notification-default",
        "provider_type": "email_notification",
        "channel_types": ["EMAIL"],
        "endpoint_env": DISPATCH_NOTIFICATION_WEBHOOK_URL_ENV,
        "token_env": DISPATCH_NOTIFICATION_SERVICE_TOKEN_ENV,
        "network_required": True,
        "mock_transport_supported": True,
    },
    "external-incident-default": {
        "profile_id": "external-incident-default",
        "provider_type": "external_incident",
        "channel_types": ["INCIDENT"],
        "endpoint_env": DISPATCH_EXTERNAL_INCIDENT_BASE_URL_ENV,
        "token_env": DISPATCH_EXTERNAL_INCIDENT_TOKEN_ENV,
        "network_required": True,
        "mock_transport_supported": True,
    },
}
FORBIDDEN_DISPATCH_EXECUTION_RESULT_KEYS = {
    "action_comment",
    "api_key",
    "artifact_binary_payload",
    "authorization",
    "bearer_token",
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
    "webhook_url",
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
        "live_provider_profiles": {
            profile_id: dict(profile)
            for profile_id, profile in DISPATCH_LIVE_PROVIDER_PROFILES.items()
        },
        "result_contract": {
            "schema_version": DISPATCH_EXECUTION_RESULT_SCHEMA_VERSION,
            "storage": DISPATCH_EXECUTION_RESULT_STORAGE,
            "allowed_statuses": list(ALLOWED_DISPATCH_EXECUTION_RESULT_STATUSES),
            "recommended_actions": dict(DISPATCH_EXECUTION_RESULT_ACTIONS),
        },
        "redaction": _dispatch_execution_redaction_flags(),
    }


def build_dispatch_execution_provider_config(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = environ or {}
    configured_mode = normalize_dispatch_execution_provider_mode(
        _env_text(env, DISPATCH_EXECUTION_PROVIDER_MODE_ENV)
        or _env_text(env, DISPATCH_LIVE_PROVIDER_MODE_ENV)
        or DISPATCH_EXECUTION_PROVIDER_MODE
    )
    live_enabled = env.get(DISPATCH_LIVE_PROVIDER_ENABLE_ENV) == "1"
    effective_mode = (
        configured_mode
        if configured_mode != "live_http" or live_enabled
        else "mock_http"
    )
    execution_profile = (
        _env_text(env, DISPATCH_EXECUTION_PROVIDER_PROFILE_ENV)
        or DISPATCH_EXECUTION_DEFAULT_PROVIDER_PROFILE
    )
    live_profile = (
        _env_text(env, DISPATCH_LIVE_PROVIDER_PROFILE_ENV)
        or "notification-webhook-default"
    )
    config = {
        "provider_config_schema_version": (
            DISPATCH_EXECUTION_PROVIDER_CONFIG_SCHEMA_VERSION
        ),
        "configured_provider_mode": configured_mode,
        "effective_provider_mode": effective_mode,
        "live_provider_enable_env": DISPATCH_LIVE_PROVIDER_ENABLE_ENV,
        "live_network_calls_enabled": configured_mode == "live_http" and live_enabled,
        "default_provider_profile": DISPATCH_EXECUTION_DEFAULT_PROVIDER_PROFILE,
        "execution_provider_profile": execution_profile,
        "live_provider_profile": live_profile,
        "known_provider_modes": list(ALLOWED_DISPATCH_EXECUTION_PROVIDER_MODES),
        "known_channel_types": [
            "MOCK",
            "NOTIFICATION",
            "EMAIL",
            "WEBHOOK",
            "INCIDENT",
        ],
        "http": _dispatch_provider_http_settings(env),
        "endpoints": {
            "notification": _provider_endpoint_status(
                _env_text(env, DISPATCH_NOTIFICATION_WEBHOOK_URL_ENV),
                token=_env_text(env, DISPATCH_NOTIFICATION_SERVICE_TOKEN_ENV),
            ),
            "external_incident": _provider_endpoint_status(
                _env_text(env, DISPATCH_EXTERNAL_INCIDENT_BASE_URL_ENV),
                token=_env_text(env, DISPATCH_EXTERNAL_INCIDENT_TOKEN_ENV),
            ),
        },
        "profiles": {
            "mock": {
                profile_id: dict(profile)
                for profile_id, profile in DISPATCH_EXECUTION_PROVIDER_PROFILES.items()
            },
            "live_readiness": {
                profile_id: dict(profile)
                for profile_id, profile in DISPATCH_LIVE_PROVIDER_PROFILES.items()
            },
        },
        "activation_guard": {
            "live_http_requires_enable_env": DISPATCH_LIVE_PROVIDER_ENABLE_ENV,
            "live_http_requires_protected_smoke": True,
            "live_http_default_effective_mode_without_enable": "mock_http",
        },
        "redaction": _dispatch_execution_redaction_flags(),
    }
    assert_dispatch_execution_result_redacted(config)
    return config


def build_dispatch_execution_daemon_policy(
    environ: Mapping[str, str] | None = None,
    *,
    provider_config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    env = environ or {}
    config = (
        dict(provider_config)
        if provider_config is not None
        else build_dispatch_execution_provider_config(env)
    )
    configured_provider_mode = normalize_dispatch_execution_provider_mode(
        _env_text(env, DISPATCH_EXECUTION_DAEMON_PROVIDER_MODE_ENV)
        or str(config.get("configured_provider_mode") or DISPATCH_EXECUTION_PROVIDER_MODE)
    )
    live_http_enabled = bool(config.get("live_network_calls_enabled")) or (
        env.get(DISPATCH_LIVE_PROVIDER_ENABLE_ENV) == "1"
    )
    effective_provider_mode = (
        configured_provider_mode
        if configured_provider_mode != "live_http" or live_http_enabled
        else "mock_http"
    )
    batch_limit = _bounded_int_env(
        env,
        DISPATCH_EXECUTION_DAEMON_BATCH_LIMIT_ENV,
        default=DEFAULT_DISPATCH_EXECUTION_BATCH_LIMIT,
        minimum=1,
        maximum=MAX_DISPATCH_EXECUTION_BATCH_LIMIT,
    )
    cycle_limit = _bounded_int_env(
        env,
        DISPATCH_EXECUTION_DAEMON_CYCLE_LIMIT_ENV,
        default=DEFAULT_DISPATCH_EXECUTION_DAEMON_CYCLE_LIMIT,
        minimum=1,
        maximum=MAX_DISPATCH_EXECUTION_DAEMON_CYCLE_LIMIT,
    )
    interval_seconds = _bounded_int_env(
        env,
        DISPATCH_EXECUTION_DAEMON_INTERVAL_SECONDS_ENV,
        default=DEFAULT_DISPATCH_EXECUTION_DAEMON_INTERVAL_SECONDS,
        minimum=MIN_DISPATCH_EXECUTION_DAEMON_INTERVAL_SECONDS,
        maximum=MAX_DISPATCH_EXECUTION_DAEMON_INTERVAL_SECONDS,
    )
    policy = {
        "daemon_policy_schema_version": (
            DISPATCH_EXECUTION_DAEMON_POLICY_SCHEMA_VERSION
        ),
        "enabled": _env_bool(env, DISPATCH_EXECUTION_DAEMON_ENABLED_ENV),
        "dry_run": _env_bool(
            env,
            DISPATCH_EXECUTION_DAEMON_DRY_RUN_ENV,
            default=True,
        ),
        "batch_limit": batch_limit,
        "cycle_limit": cycle_limit,
        "interval_seconds": interval_seconds,
        "source_table": "ag_op_esc_dispatches",
        "result_storage": DISPATCH_EXECUTION_RESULT_STORAGE,
        "configured_provider_mode": configured_provider_mode,
        "effective_provider_mode": effective_provider_mode,
        "provider_config_schema_version": config.get(
            "provider_config_schema_version"
        ),
        "live_network_calls_enabled": configured_provider_mode == "live_http"
        and live_http_enabled
        and effective_provider_mode == "live_http",
        "requires_confirm_tick": True,
        "requires_protected_control": True,
        "job_queue_control": "deferred_until_control_api_slice",
        "new_tables_required": False,
        "allowed_runtime_modes": [
            "dry_run_plan",
            "confirmed_run_once",
            "injected_loopback_live_http",
        ],
        "bounds": {
            "batch_limit_min": 1,
            "batch_limit_max": MAX_DISPATCH_EXECUTION_BATCH_LIMIT,
            "cycle_limit_min": 1,
            "cycle_limit_max": MAX_DISPATCH_EXECUTION_DAEMON_CYCLE_LIMIT,
            "interval_seconds_min": MIN_DISPATCH_EXECUTION_DAEMON_INTERVAL_SECONDS,
            "interval_seconds_max": MAX_DISPATCH_EXECUTION_DAEMON_INTERVAL_SECONDS,
        },
        "env": {
            "enabled": DISPATCH_EXECUTION_DAEMON_ENABLED_ENV,
            "dry_run": DISPATCH_EXECUTION_DAEMON_DRY_RUN_ENV,
            "batch_limit": DISPATCH_EXECUTION_DAEMON_BATCH_LIMIT_ENV,
            "cycle_limit": DISPATCH_EXECUTION_DAEMON_CYCLE_LIMIT_ENV,
            "interval_seconds": DISPATCH_EXECUTION_DAEMON_INTERVAL_SECONDS_ENV,
            "provider_mode": DISPATCH_EXECUTION_DAEMON_PROVIDER_MODE_ENV,
            "live_provider_enable": DISPATCH_LIVE_PROVIDER_ENABLE_ENV,
        },
        "redaction": _dispatch_execution_redaction_flags(),
    }
    assert_dispatch_execution_result_redacted(policy)
    return policy


def build_dispatch_execution_daemon_tick_plan(
    service: Any,
    *,
    request_id: str,
    trace_id: str | None = None,
    policy: Mapping[str, Any] | None = None,
    provider_config: Mapping[str, Any] | None = None,
    planned_at: str | None = None,
) -> dict[str, Any]:
    resolved_policy = (
        dict(policy)
        if policy is not None
        else build_dispatch_execution_daemon_policy(
            {},
            provider_config=provider_config,
        )
    )
    now = planned_at or _utc_now()
    batch_limit = _bounded_batch_limit(resolved_policy.get("batch_limit"))
    candidates = _worker_candidate_dispatches(
        service,
        request_id=request_id,
        trace_id=trace_id,
        limit=batch_limit,
    )
    plan_status = "READY"
    if not bool(resolved_policy.get("enabled")):
        plan_status = "DISABLED"
    elif not candidates:
        plan_status = "IDLE"
    plan_id = str(
        uuid5(
            NAMESPACE_URL,
            "ag-operator-review-escalation-dispatch-execution-daemon-tick-plan:"
            f"{request_id}:{now}:{batch_limit}:"
            f"{resolved_policy.get('effective_provider_mode')}:{len(candidates)}",
        )
    )
    plan = {
        "daemon_tick_plan_schema_version": (
            DISPATCH_EXECUTION_DAEMON_TICK_PLAN_SCHEMA_VERSION
        ),
        "tick_plan_id": plan_id,
        "plan_status": plan_status,
        "request_id": request_id,
        "trace_id": trace_id,
        "planned_at": now,
        "source_table": resolved_policy.get("source_table", "ag_op_esc_dispatches"),
        "batch_limit": batch_limit,
        "candidate_count": len(candidates),
        "candidate_dispatch_ids": [
            str(candidate.get("dispatch_id") or "") for candidate in candidates
        ],
        "candidate_summaries": [
            _dispatch_daemon_candidate_summary(candidate) for candidate in candidates
        ],
        "candidate_status_counts": _count_by_key(candidates, "dispatch_status"),
        "candidate_channel_counts": _count_by_key(candidates, "channel_type"),
        "configured_provider_mode": resolved_policy.get("configured_provider_mode"),
        "effective_provider_mode": resolved_policy.get("effective_provider_mode"),
        "live_network_calls_enabled": bool(
            resolved_policy.get("live_network_calls_enabled")
        ),
        "dry_run": bool(resolved_policy.get("dry_run")),
        "requires_confirm_tick": bool(
            resolved_policy.get("requires_confirm_tick", True)
        ),
        "will_mutate_without_confirm": False,
        "new_tables_required": False,
        "redaction": _dispatch_execution_redaction_flags(),
    }
    assert_dispatch_execution_result_redacted(plan)
    return plan


def run_dispatch_execution_daemon_tick_once(
    service: Any,
    *,
    request_id: str,
    trace_id: str | None = None,
    worker_id: str = "ag-dispatch-execution-daemon",
    policy: Mapping[str, Any] | None = None,
    provider_config: Mapping[str, Any] | None = None,
    provider_profile: str | None = None,
    notification_status_code: int | None = None,
    external_incident_status_code: int | None = None,
    live_http_transport: Any | None = None,
    confirm_tick: bool = False,
    dry_run: bool | None = None,
    executed_at: str | None = None,
) -> dict[str, Any]:
    resolved_policy = (
        dict(policy)
        if policy is not None
        else build_dispatch_execution_daemon_policy(
            {},
            provider_config=provider_config,
        )
    )
    now = executed_at or _utc_now()
    plan = build_dispatch_execution_daemon_tick_plan(
        service,
        request_id=request_id,
        trace_id=trace_id,
        policy=resolved_policy,
        provider_config=provider_config,
        planned_at=now,
    )
    resolved_dry_run = bool(resolved_policy.get("dry_run")) if dry_run is None else dry_run
    tick_id = str(
        uuid5(
            NAMESPACE_URL,
            "ag-operator-review-escalation-dispatch-execution-daemon-tick:"
            f"{worker_id}:{request_id}:{now}:{plan['tick_plan_id']}:{resolved_dry_run}",
        )
    )
    blocked_reason = None
    worker_run = None
    if not bool(resolved_policy.get("enabled")):
        blocked_reason = "daemon_disabled"
    elif not confirm_tick:
        blocked_reason = "confirm_tick_required"
    if blocked_reason is None:
        worker_run = run_dispatch_execution_worker_once(
            service,
            request_id=request_id,
            trace_id=trace_id,
            worker_id=worker_id,
            batch_limit=int(plan["batch_limit"]),
            provider_profile=provider_profile,
            provider_mode=str(resolved_policy.get("effective_provider_mode") or ""),
            provider_config=provider_config,
            notification_status_code=notification_status_code,
            external_incident_status_code=external_incident_status_code,
            live_http_transport=live_http_transport,
            confirm_run=True,
            dry_run=resolved_dry_run,
            executed_at=now,
        )
    result = {
        "daemon_tick_result_schema_version": (
            DISPATCH_EXECUTION_DAEMON_TICK_RESULT_SCHEMA_VERSION
        ),
        "tick_id": tick_id,
        "tick_status": "BLOCKED" if blocked_reason else "COMPLETED",
        "blocked_reason": blocked_reason,
        "request_id": request_id,
        "trace_id": trace_id,
        "worker_id": worker_id,
        "executed_at": now,
        "dry_run": resolved_dry_run,
        "plan": plan,
        "worker_run": worker_run,
        "candidate_count": plan["candidate_count"],
        "processed_count": int((worker_run or {}).get("processed_count") or 0),
        "succeeded_count": int((worker_run or {}).get("succeeded_count") or 0),
        "failed_count": int((worker_run or {}).get("failed_count") or 0),
        "retry_wait_count": int((worker_run or {}).get("retry_wait_count") or 0),
        "skipped_count": int((worker_run or {}).get("skipped_count") or 0),
        "effective_provider_mode": resolved_policy.get("effective_provider_mode"),
        "new_tables_required": False,
        "redaction": _dispatch_execution_redaction_flags(),
    }
    assert_dispatch_execution_result_redacted(result)
    return result


def build_dispatch_execution_daemon_tick_event(
    tick_result: Mapping[str, Any],
    *,
    service_id: str = "nex-ag",
    event_id: str | None = None,
    occurred_at: str | None = None,
) -> dict[str, Any]:
    tick_id = str(tick_result.get("tick_id") or "")
    status = str(tick_result.get("tick_status") or "UNKNOWN")
    severity = _dispatch_daemon_tick_severity(tick_result)
    event = {
        "daemon_tick_event_schema_version": (
            DISPATCH_EXECUTION_DAEMON_TICK_EVENT_SCHEMA_VERSION
        ),
        "event_id": event_id
        or str(
            uuid5(
                NAMESPACE_URL,
                "ag-dispatch-execution-daemon-tick-event:"
                f"{service_id}:{tick_id}:{status}",
            )
        ),
        "service_id": service_id,
        "event_type": (
            "ag.operator_review.escalation_dispatch.daemon_tick."
            f"{status.lower()}"
        ),
        "severity": severity,
        "occurred_at": occurred_at or str(tick_result.get("executed_at") or _utc_now()),
        "tick_id": tick_id,
        "request_id": tick_result.get("request_id"),
        "trace_id": tick_result.get("trace_id"),
        "summary": _dispatch_daemon_tick_safe_summary(tick_result),
        "redaction": _dispatch_execution_redaction_flags(),
    }
    assert_dispatch_execution_result_redacted(event)
    return event


def build_dispatch_execution_daemon_tick_log_entry(
    tick_result: Mapping[str, Any],
    *,
    service_id: str = "nex-ag",
    logger_name: str = "nex_ag.operator_review_dispatch_execution.daemon",
    log_id: str | None = None,
    emitted_at: str | None = None,
) -> dict[str, Any]:
    tick_id = str(tick_result.get("tick_id") or "")
    status = str(tick_result.get("tick_status") or "UNKNOWN")
    severity = _dispatch_daemon_tick_severity(tick_result)
    summary = _dispatch_daemon_tick_safe_summary(tick_result)
    log_entry = {
        "daemon_tick_log_schema_version": (
            DISPATCH_EXECUTION_DAEMON_TICK_LOG_SCHEMA_VERSION
        ),
        "log_id": log_id
        or str(
            uuid5(
                NAMESPACE_URL,
                "ag-dispatch-execution-daemon-tick-log:"
                f"{service_id}:{tick_id}:{status}",
            )
        ),
        "service_id": service_id,
        "logger_name": logger_name,
        "severity": severity,
        "message": (
            "AG dispatch daemon tick "
            f"{status.lower()} processed={summary['processed_count']} "
            f"succeeded={summary['succeeded_count']} "
            f"failed={summary['failed_count']} "
            f"retry_wait={summary['retry_wait_count']}"
        ),
        "emitted_at": emitted_at or str(tick_result.get("executed_at") or _utc_now()),
        "tick_id": tick_id,
        "context": summary,
        "redaction": _dispatch_execution_redaction_flags(),
    }
    assert_dispatch_execution_result_redacted(log_entry)
    return log_entry


def build_dispatch_execution_daemon_control_request(
    payload: Mapping[str, Any] | None,
    *,
    request_id: str,
    trace_id: str | None = None,
    requested_at: str | None = None,
) -> dict[str, Any]:
    body = dict(payload or {})
    action = optional_text(body.get("action")) or "tick_plan"
    if action not in ALLOWED_DISPATCH_EXECUTION_DAEMON_CONTROL_ACTIONS:
        raise OperatorReviewNoteError(
            status_code=422,
            error_code=(
                "ag.operator_review_escalation_dispatch_daemon_control_action_"
                "unsupported"
            ),
            detail=f"Unsupported dispatch daemon control action: {action}",
        )
    safe_request = {
        "daemon_control_request_schema_version": (
            DISPATCH_EXECUTION_DAEMON_CONTROL_REQUEST_SCHEMA_VERSION
        ),
        "action": action,
        "request_id": request_id,
        "trace_id": trace_id,
        "confirm_tick": _payload_bool(body, "confirm_tick"),
        "dry_run": _payload_bool(body, "dry_run", default=True),
        "batch_limit": _bounded_batch_limit(body.get("batch_limit")),
        "provider_mode": (
            normalize_dispatch_execution_provider_mode(
                optional_text(body.get("provider_mode"))
            )
            if optional_text(body.get("provider_mode")) is not None
            else None
        ),
        "operator_ref": _dispatch_daemon_control_operator_ref(body.get("operator_ref")),
        "reason_codes": _safe_text_list(body.get("reason_codes")),
        "requested_at": requested_at or _utc_now(),
        "redaction": _dispatch_execution_redaction_flags(),
    }
    safe_request["control_request_hash"] = sha256_text(
        json.dumps(safe_request, sort_keys=True, default=str)
    )
    assert_dispatch_execution_result_redacted(safe_request)
    return safe_request


def build_dispatch_execution_daemon_control_admission(
    control_request: Mapping[str, Any],
    *,
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    action = str(control_request.get("action") or "")
    if action not in ALLOWED_DISPATCH_EXECUTION_DAEMON_CONTROL_ACTIONS:
        raise OperatorReviewNoteError(
            status_code=422,
            error_code=(
                "ag.operator_review_escalation_dispatch_daemon_control_action_"
                "unsupported"
            ),
            detail=f"Unsupported dispatch daemon control action: {action}",
        )
    resolved_policy = dict(policy or build_dispatch_execution_daemon_policy({}))
    rejection_reason = None
    if action == "tick_once" and not bool(resolved_policy.get("enabled")):
        rejection_reason = "daemon_disabled"
    elif action == "tick_once" and not bool(control_request.get("confirm_tick")):
        rejection_reason = "confirm_tick_required"
    admission = {
        "daemon_control_admission_schema_version": (
            DISPATCH_EXECUTION_DAEMON_CONTROL_ADMISSION_SCHEMA_VERSION
        ),
        "admission_status": "REJECTED" if rejection_reason else "ACCEPTED",
        "rejection_reason": rejection_reason,
        "action": action,
        "control_request_hash": control_request.get("control_request_hash"),
        "request_id": control_request.get("request_id"),
        "trace_id": control_request.get("trace_id"),
        "confirm_tick": bool(control_request.get("confirm_tick")),
        "dry_run": bool(control_request.get("dry_run")),
        "batch_limit": _bounded_batch_limit(control_request.get("batch_limit")),
        "effective_provider_mode": (
            control_request.get("provider_mode")
            or resolved_policy.get("effective_provider_mode")
        ),
        "policy": {
            "enabled": bool(resolved_policy.get("enabled")),
            "dry_run": bool(resolved_policy.get("dry_run")),
            "requires_confirm_tick": bool(
                resolved_policy.get("requires_confirm_tick", True)
            ),
            "requires_protected_control": bool(
                resolved_policy.get("requires_protected_control", True)
            ),
            "source_table": resolved_policy.get("source_table", "ag_op_esc_dispatches"),
            "new_tables_required": bool(resolved_policy.get("new_tables_required")),
        },
        "redaction": _dispatch_execution_redaction_flags(),
    }
    assert_dispatch_execution_result_redacted(admission)
    return admission


def normalize_dispatch_execution_provider_mode(value: str | None) -> str:
    normalized = optional_text(value) or DISPATCH_EXECUTION_PROVIDER_MODE
    if normalized not in ALLOWED_DISPATCH_EXECUTION_PROVIDER_MODES:
        raise OperatorReviewNoteError(
            status_code=422,
            error_code=(
                "ag.operator_review_escalation_dispatch_execution_provider_mode_"
                "unsupported"
            ),
            detail=f"Unsupported dispatch execution provider mode: {normalized}",
        )
    return normalized


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


def build_notification_dispatch_provider_request(
    dispatch: Mapping[str, Any],
    *,
    provider_config: Mapping[str, Any] | None = None,
    request_id: str | None = None,
    trace_id: str | None = None,
    requested_at: str | None = None,
) -> dict[str, Any]:
    channel_type = str(dispatch.get("channel_type") or "")
    if channel_type not in NOTIFICATION_DISPATCH_CHANNEL_TYPES:
        raise OperatorReviewNoteError(
            status_code=422,
            error_code=(
                "ag.operator_review_escalation_dispatch_notification_channel_"
                "unsupported"
            ),
            detail=f"Unsupported notification dispatch channel_type: {channel_type}",
        )
    config = (
        dict(provider_config)
        if provider_config is not None
        else build_dispatch_execution_provider_config({})
    )
    profile = _notification_provider_profile_for_channel(channel_type, config)
    endpoint = _provider_config_endpoint(config, "notification")
    http_settings = _provider_config_http_settings(config)
    safe_payload = {
        "safe_subject": optional_text(dispatch.get("safe_subject")),
        "safe_body_preview": optional_text(dispatch.get("safe_body_preview")),
        "safe_body_hash": optional_text(dispatch.get("safe_body_hash")),
        "reason_codes": _safe_text_list(dispatch.get("reason_codes")),
        "provider_payload_hash": optional_text(dispatch.get("provider_payload_hash")),
    }
    request_ref = {
        "request_id_hash": sha256_text(request_id) if optional_text(request_id) else None,
        "trace_id": optional_text(trace_id),
    }
    idempotency_hash = sha256_text(
        json.dumps(
            {
                "dispatch_id": dispatch.get("dispatch_id"),
                "request_id": request_id,
                "provider_profile": profile["profile_id"],
                "channel_type": channel_type,
            },
            sort_keys=True,
        )
    )
    payload_hash = sha256_text(json.dumps(safe_payload, sort_keys=True))
    request_hash = sha256_text(
        json.dumps(
            {
                "dispatch_id": dispatch.get("dispatch_id"),
                "channel_type": channel_type,
                "provider_profile": profile["profile_id"],
                "payload_hash": payload_hash,
                "idempotency_hash": idempotency_hash,
            },
            sort_keys=True,
        )
    )
    provider_ref = dispatch.get("provider_ref") or {}
    request = {
        "provider_request_schema_version": (
            DISPATCH_NOTIFICATION_PROVIDER_REQUEST_SCHEMA_VERSION
        ),
        "provider_category": "notification",
        "provider_type": profile["provider_type"],
        "provider_profile": profile["profile_id"],
        "provider_mode": str(config.get("effective_provider_mode") or "mock_http"),
        "dispatch_id": str(dispatch.get("dispatch_id") or ""),
        "escalation_id": str(dispatch.get("escalation_id") or ""),
        "case_id": str(dispatch.get("case_id") or ""),
        "dispatch_intent": str(dispatch.get("dispatch_intent") or ""),
        "channel_type": channel_type,
        "provider_id": str(
            provider_ref.get("provider_id")
            if isinstance(provider_ref, Mapping)
            else "notification-provider"
        ),
        "safe_payload": safe_payload,
        "safe_payload_hash": payload_hash,
        "provider_request_hash": request_hash,
        "idempotency_hash": idempotency_hash,
        "request_ref": request_ref,
        "http": {
            "method": "POST",
            "endpoint_hint": endpoint.get("endpoint_hint"),
            "endpoint_configured": bool(endpoint.get("configured")),
            "token_configured": bool(endpoint.get("token_configured")),
            "timeout_seconds": http_settings["timeout_seconds"],
            "connect_timeout_seconds": http_settings["connect_timeout_seconds"],
            "read_timeout_seconds": http_settings["read_timeout_seconds"],
            "max_retries": http_settings["max_retries"],
            "backoff_seconds": http_settings["backoff_seconds"],
        },
        "activation": {
            "configured_provider_mode": config.get("configured_provider_mode"),
            "effective_provider_mode": config.get("effective_provider_mode"),
            "live_network_calls_enabled": bool(
                config.get("live_network_calls_enabled")
            ),
        },
        "requested_at": requested_at or _utc_now(),
        "redaction": _dispatch_execution_redaction_flags(),
    }
    assert_dispatch_execution_result_redacted(request)
    return request


def build_external_incident_dispatch_provider_request(
    dispatch: Mapping[str, Any],
    *,
    provider_config: Mapping[str, Any] | None = None,
    request_id: str | None = None,
    trace_id: str | None = None,
    requested_at: str | None = None,
) -> dict[str, Any]:
    channel_type = str(dispatch.get("channel_type") or "")
    if channel_type not in EXTERNAL_INCIDENT_DISPATCH_CHANNEL_TYPES:
        raise OperatorReviewNoteError(
            status_code=422,
            error_code=(
                "ag.operator_review_escalation_dispatch_external_incident_"
                "channel_unsupported"
            ),
            detail=(
                "Unsupported external incident dispatch channel_type: "
                f"{channel_type}"
            ),
        )
    config = (
        dict(provider_config)
        if provider_config is not None
        else build_dispatch_execution_provider_config({})
    )
    profile = dict(DISPATCH_LIVE_PROVIDER_PROFILES["external-incident-default"])
    endpoint = _provider_config_endpoint(config, "external_incident")
    http_settings = _provider_config_http_settings(config)
    incident_payload = {
        "safe_subject": optional_text(dispatch.get("safe_subject")),
        "safe_body_preview": optional_text(dispatch.get("safe_body_preview")),
        "safe_body_hash": optional_text(dispatch.get("safe_body_hash")),
        "reason_codes": _safe_text_list(dispatch.get("reason_codes")),
        "target_ref": {
            "target_service": str(dispatch.get("target_service") or ""),
            "target_kind": str(dispatch.get("target_kind") or ""),
            "target_id_hash": sha256_text(str(dispatch.get("target_id") or "")),
        },
        "provider_payload_hash": optional_text(dispatch.get("provider_payload_hash")),
    }
    request_ref = {
        "request_id_hash": sha256_text(request_id) if optional_text(request_id) else None,
        "trace_id": optional_text(trace_id),
    }
    idempotency_hash = sha256_text(
        json.dumps(
            {
                "dispatch_id": dispatch.get("dispatch_id"),
                "request_id": request_id,
                "provider_profile": profile["profile_id"],
                "channel_type": channel_type,
                "target_id": dispatch.get("target_id"),
            },
            sort_keys=True,
        )
    )
    payload_hash = sha256_text(json.dumps(incident_payload, sort_keys=True))
    request_hash = sha256_text(
        json.dumps(
            {
                "dispatch_id": dispatch.get("dispatch_id"),
                "channel_type": channel_type,
                "provider_profile": profile["profile_id"],
                "payload_hash": payload_hash,
                "idempotency_hash": idempotency_hash,
            },
            sort_keys=True,
        )
    )
    provider_ref = dispatch.get("provider_ref") or {}
    request = {
        "provider_request_schema_version": (
            DISPATCH_EXTERNAL_INCIDENT_PROVIDER_REQUEST_SCHEMA_VERSION
        ),
        "provider_category": "external_incident",
        "provider_type": profile["provider_type"],
        "provider_profile": profile["profile_id"],
        "provider_mode": str(config.get("effective_provider_mode") or "mock_http"),
        "dispatch_id": str(dispatch.get("dispatch_id") or ""),
        "escalation_id": str(dispatch.get("escalation_id") or ""),
        "case_id": str(dispatch.get("case_id") or ""),
        "dispatch_intent": str(dispatch.get("dispatch_intent") or ""),
        "channel_type": channel_type,
        "provider_id": str(
            provider_ref.get("provider_id")
            if isinstance(provider_ref, Mapping)
            else "external-incident-provider"
        ),
        "incident_payload": incident_payload,
        "incident_payload_hash": payload_hash,
        "provider_request_hash": request_hash,
        "idempotency_hash": idempotency_hash,
        "request_ref": request_ref,
        "http": {
            "method": "POST",
            "endpoint_hint": endpoint.get("endpoint_hint"),
            "endpoint_configured": bool(endpoint.get("configured")),
            "token_configured": bool(endpoint.get("token_configured")),
            "timeout_seconds": http_settings["timeout_seconds"],
            "connect_timeout_seconds": http_settings["connect_timeout_seconds"],
            "read_timeout_seconds": http_settings["read_timeout_seconds"],
            "max_retries": http_settings["max_retries"],
            "backoff_seconds": http_settings["backoff_seconds"],
        },
        "activation": {
            "configured_provider_mode": config.get("configured_provider_mode"),
            "effective_provider_mode": config.get("effective_provider_mode"),
            "live_network_calls_enabled": bool(
                config.get("live_network_calls_enabled")
            ),
        },
        "requested_at": requested_at or _utc_now(),
        "redaction": _dispatch_execution_redaction_flags(),
    }
    assert_dispatch_execution_result_redacted(request)
    return request


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


@dataclass(frozen=True)
class MockNotificationDispatchProvider:
    default_status_code: int = 202

    def execute(
        self,
        dispatch: Mapping[str, Any],
        *,
        provider_config: Mapping[str, Any] | None = None,
        request_id: str | None = None,
        trace_id: str | None = None,
        status_code: int | None = None,
        executed_at: str | None = None,
    ) -> dict[str, Any]:
        now = executed_at or _utc_now()
        request = build_notification_dispatch_provider_request(
            dispatch,
            provider_config=provider_config,
            request_id=request_id,
            trace_id=trace_id,
            requested_at=now,
        )
        code = int(status_code if status_code is not None else self.default_status_code)
        if 200 <= code < 300:
            return _build_provider_adapter_execution_result(
                dispatch,
                request,
                execution_status="SUCCEEDED",
                safe_result_message="Mock notification provider accepted dispatch.",
                http_status_code=code,
                executed_at=now,
            )
        if code in {408, 425, 429} or code >= 500:
            return _build_provider_adapter_execution_result(
                dispatch,
                request,
                execution_status="RETRY_WAIT",
                safe_result_message=(
                    "Mock notification provider returned a retryable status."
                ),
                last_error_code="notification_provider_retryable_status",
                next_attempt_at=_iso_after_seconds(
                    now,
                    DEFAULT_DISPATCH_EXECUTION_RETRY_DELAY_SECONDS,
                ),
                retryable=True,
                http_status_code=code,
                executed_at=now,
            )
        return _build_provider_adapter_execution_result(
            dispatch,
            request,
            execution_status="FAILED",
            safe_result_message="Mock notification provider rejected dispatch.",
            last_error_code="notification_provider_rejected",
            retryable=False,
            http_status_code=code,
            executed_at=now,
        )


def execute_dispatch_with_mock_notification_provider(
    dispatch: Mapping[str, Any],
    *,
    provider_config: Mapping[str, Any] | None = None,
    request_id: str | None = None,
    trace_id: str | None = None,
    status_code: int | None = None,
    executed_at: str | None = None,
) -> dict[str, Any]:
    provider = MockNotificationDispatchProvider()
    return provider.execute(
        dispatch,
        provider_config=provider_config,
        request_id=request_id,
        trace_id=trace_id,
        status_code=status_code,
        executed_at=executed_at,
    )


@dataclass(frozen=True)
class MockExternalIncidentDispatchProvider:
    default_status_code: int = 201

    def execute(
        self,
        dispatch: Mapping[str, Any],
        *,
        provider_config: Mapping[str, Any] | None = None,
        request_id: str | None = None,
        trace_id: str | None = None,
        status_code: int | None = None,
        executed_at: str | None = None,
    ) -> dict[str, Any]:
        now = executed_at or _utc_now()
        request = build_external_incident_dispatch_provider_request(
            dispatch,
            provider_config=provider_config,
            request_id=request_id,
            trace_id=trace_id,
            requested_at=now,
        )
        code = int(status_code if status_code is not None else self.default_status_code)
        if 200 <= code < 300 or code == 409:
            return _build_provider_adapter_execution_result(
                dispatch,
                request,
                execution_status="SUCCEEDED",
                safe_result_message=(
                    "Mock external incident provider accepted dispatch."
                ),
                http_status_code=code,
                executed_at=now,
            )
        if code in {408, 425, 429} or code >= 500:
            return _build_provider_adapter_execution_result(
                dispatch,
                request,
                execution_status="RETRY_WAIT",
                safe_result_message=(
                    "Mock external incident provider returned a retryable status."
                ),
                last_error_code="external_incident_provider_retryable_status",
                next_attempt_at=_iso_after_seconds(
                    now,
                    DEFAULT_DISPATCH_EXECUTION_RETRY_DELAY_SECONDS,
                ),
                retryable=True,
                http_status_code=code,
                executed_at=now,
            )
        return _build_provider_adapter_execution_result(
            dispatch,
            request,
            execution_status="FAILED",
            safe_result_message="Mock external incident provider rejected dispatch.",
            last_error_code="external_incident_provider_rejected",
            retryable=False,
            http_status_code=code,
            executed_at=now,
        )


def execute_dispatch_with_mock_external_incident_provider(
    dispatch: Mapping[str, Any],
    *,
    provider_config: Mapping[str, Any] | None = None,
    request_id: str | None = None,
    trace_id: str | None = None,
    status_code: int | None = None,
    executed_at: str | None = None,
) -> dict[str, Any]:
    provider = MockExternalIncidentDispatchProvider()
    return provider.execute(
        dispatch,
        provider_config=provider_config,
        request_id=request_id,
        trace_id=trace_id,
        status_code=status_code,
        executed_at=executed_at,
    )


@dataclass
class MockDispatchProviderHttpTransport:
    status_codes: tuple[int, ...] = (202,)
    timeout_attempts: tuple[int, ...] = ()

    def send(
        self,
        provider_request: Mapping[str, Any],
        *,
        attempt_number: int,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        if attempt_number in self.timeout_attempts:
            raise TimeoutError("mock dispatch provider HTTP timeout")
        index = min(max(attempt_number - 1, 0), len(self.status_codes) - 1)
        status_code = int(self.status_codes[index])
        body_hash = sha256_text(
            json.dumps(
                {
                    "provider_request_hash": provider_request.get(
                        "provider_request_hash"
                    ),
                    "attempt_number": attempt_number,
                    "status_code": status_code,
                    "timeout_seconds": timeout_seconds,
                },
                sort_keys=True,
            )
        )
        return {
            "status_code": status_code,
            "response_body_hash": body_hash,
        }


@dataclass(frozen=True)
class UrllibDispatchProviderHttpTransport:
    endpoint_url: str
    bearer_token: str | None = None
    user_agent: str = DISPATCH_LIVE_HTTP_TRANSPORT_USER_AGENT

    def send(
        self,
        provider_request: Mapping[str, Any],
        *,
        attempt_number: int,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        endpoint_url = _required_live_http_endpoint(self.endpoint_url)
        envelope = build_dispatch_live_http_transport_envelope(
            provider_request,
            attempt_number=attempt_number,
        )
        body = json.dumps(envelope, ensure_ascii=False, sort_keys=True).encode("utf-8")
        request = Request(
            endpoint_url,
            data=body,
            headers=build_dispatch_live_http_transport_headers(
                provider_request,
                attempt_number=attempt_number,
                bearer_token=self.bearer_token,
                user_agent=self.user_agent,
            ),
            method=str(provider_request.get("http", {}).get("method") or "POST"),
        )
        try:
            with urlopen(request, timeout=max(0.1, float(timeout_seconds))) as response:
                return _live_http_transport_response(
                    int(response.getcode() or 0),
                    response.read(4096),
                )
        except HTTPError as exc:
            return _live_http_transport_response(
                int(exc.code or 0),
                exc.read(4096),
            )
        except (TimeoutError, socket.timeout) as exc:
            raise TimeoutError("dispatch provider live HTTP timeout") from exc
        except URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise TimeoutError("dispatch provider live HTTP timeout") from exc
            return _live_http_transport_response(
                0,
                str(type(exc.reason).__name__).encode("utf-8"),
            )


def build_dispatch_live_http_transport(
    provider_request: Mapping[str, Any],
    *,
    endpoint_url: str,
    bearer_token: str | None = None,
) -> UrllibDispatchProviderHttpTransport:
    endpoint = _required_live_http_endpoint(endpoint_url)
    category = str(provider_request.get("provider_category") or "")
    if category not in {"notification", "external_incident"}:
        raise OperatorReviewNoteError(
            status_code=422,
            error_code=(
                "ag.operator_review_escalation_dispatch_live_http_transport_"
                "category_unsupported"
            ),
            detail=f"Unsupported live HTTP provider category: {category}",
        )
    transport = UrllibDispatchProviderHttpTransport(
        endpoint_url=endpoint,
        bearer_token=optional_text(bearer_token),
    )
    assert_dispatch_execution_result_redacted(
        {
            "transport": "urllib",
            "provider_category": category,
            "endpoint_hint": _redacted_endpoint_hint(endpoint),
            "token_configured": optional_text(bearer_token) is not None,
            "redaction": _dispatch_execution_redaction_flags(),
        }
    )
    return transport


def build_dispatch_live_http_transport_envelope(
    provider_request: Mapping[str, Any],
    *,
    attempt_number: int,
) -> dict[str, Any]:
    category = str(provider_request.get("provider_category") or "")
    safe_payload_key = (
        "incident_payload" if category == "external_incident" else "safe_payload"
    )
    safe_payload = provider_request.get(safe_payload_key)
    envelope = {
        "transport_envelope_schema_version": (
            DISPATCH_LIVE_HTTP_TRANSPORT_ENVELOPE_SCHEMA_VERSION
        ),
        "provider_request_schema_version": provider_request.get(
            "provider_request_schema_version"
        ),
        "provider_category": category,
        "provider_type": provider_request.get("provider_type"),
        "provider_profile": provider_request.get("provider_profile"),
        "provider_mode": provider_request.get("provider_mode"),
        "dispatch_id": provider_request.get("dispatch_id"),
        "escalation_id": provider_request.get("escalation_id"),
        "case_id": provider_request.get("case_id"),
        "dispatch_intent": provider_request.get("dispatch_intent"),
        "channel_type": provider_request.get("channel_type"),
        "provider_id": provider_request.get("provider_id"),
        "provider_request_hash": provider_request.get("provider_request_hash"),
        "idempotency_hash": provider_request.get("idempotency_hash"),
        "attempt_number": max(1, int(attempt_number)),
        safe_payload_key: safe_payload if isinstance(safe_payload, Mapping) else {},
        "request_ref": {
            "request_id_hash": (provider_request.get("request_ref") or {}).get(
                "request_id_hash"
            )
            if isinstance(provider_request.get("request_ref"), Mapping)
            else None,
            "trace_id": (provider_request.get("request_ref") or {}).get("trace_id")
            if isinstance(provider_request.get("request_ref"), Mapping)
            else None,
        },
        "redaction": _dispatch_execution_redaction_flags(),
    }
    assert_dispatch_execution_result_redacted(envelope)
    return envelope


def build_dispatch_live_http_transport_headers(
    provider_request: Mapping[str, Any],
    *,
    attempt_number: int,
    bearer_token: str | None = None,
    user_agent: str | None = None,
) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": optional_text(user_agent)
        or DISPATCH_LIVE_HTTP_TRANSPORT_USER_AGENT,
        "X-NEX-Dispatch-Request-Hash": str(
            provider_request.get("provider_request_hash") or ""
        ),
        "X-NEX-Dispatch-Attempt": str(max(1, int(attempt_number))),
    }
    request_ref = provider_request.get("request_ref")
    if isinstance(request_ref, Mapping) and optional_text(request_ref.get("trace_id")):
        headers["X-NEX-Trace-Id"] = str(request_ref["trace_id"])
    token = optional_text(bearer_token)
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def build_dispatch_live_http_transport_request_plan(
    provider_request: Mapping[str, Any],
    *,
    endpoint_url: str,
    attempt_number: int,
    bearer_token_configured: bool = False,
) -> dict[str, Any]:
    endpoint = _required_live_http_endpoint(endpoint_url)
    envelope = build_dispatch_live_http_transport_envelope(
        provider_request,
        attempt_number=attempt_number,
    )
    safe_headers = build_dispatch_live_http_transport_headers(
        provider_request,
        attempt_number=attempt_number,
        bearer_token="configured" if bearer_token_configured else None,
    )
    evidence_headers = sorted(
        header for header in safe_headers if header.lower() != "authorization"
    )
    plan = {
        "transport_request_plan_schema_version": (
            DISPATCH_LIVE_HTTP_TRANSPORT_REQUEST_PLAN_SCHEMA_VERSION
        ),
        "provider_category": provider_request.get("provider_category"),
        "provider_profile": provider_request.get("provider_profile"),
        "provider_request_hash": provider_request.get("provider_request_hash"),
        "endpoint_hint": _redacted_endpoint_hint(endpoint),
        "method": str(provider_request.get("http", {}).get("method") or "POST"),
        "attempt_number": max(1, int(attempt_number)),
        "envelope_schema_version": envelope[
            "transport_envelope_schema_version"
        ],
        "envelope_hash": sha256_text(
            json.dumps(envelope, ensure_ascii=False, sort_keys=True)
        ),
        "evidence_header_names": evidence_headers,
        "withheld_header_names": ["Authorization"]
        if bearer_token_configured
        else [],
        "authorization_header_configured": bool(bearer_token_configured),
        "raw_header_values_in_evidence_allowed": False,
        "raw_endpoint_in_evidence_allowed": False,
        "raw_payload_in_evidence_allowed": False,
        "redaction": _dispatch_execution_redaction_flags(),
    }
    assert_dispatch_execution_result_redacted(plan)
    return plan


def execute_dispatch_provider_http_request(
    provider_request: Mapping[str, Any],
    *,
    transport: Any,
    provider_config: Mapping[str, Any] | None = None,
    executed_at: str | None = None,
) -> dict[str, Any]:
    if transport is None or not hasattr(transport, "send"):
        raise OperatorReviewNoteError(
            status_code=422,
            error_code=(
                "ag.operator_review_escalation_dispatch_provider_http_transport_"
                "required"
            ),
            detail="Dispatch provider HTTP execution requires an injected transport.",
    )
    now = executed_at or _utc_now()
    http_settings = _provider_config_http_settings(provider_config or provider_request)
    max_attempts = max(1, int(http_settings["max_retries"]) + 1)
    attempt_number = 0
    last_status_code: int | None = None
    last_error_code: str | None = None
    response_body_hash: str | None = None
    for attempt_number in range(1, max_attempts + 1):  # pragma: no branch
        try:
            response = transport.send(
                provider_request,
                attempt_number=attempt_number,
                timeout_seconds=float(http_settings["timeout_seconds"]),
            )
        except TimeoutError:
            last_error_code = "dispatch_provider_http_timeout"
            if attempt_number < max_attempts:
                continue
            return _build_dispatch_provider_http_client_result(
                provider_request,
                http_settings=http_settings,
                execution_status="RETRY_WAIT",
                attempt_count=attempt_number,
                http_status_code=last_status_code,
                response_body_hash=response_body_hash,
                last_error_code=last_error_code,
                next_attempt_at=_iso_after_seconds(
                    now,
                    DEFAULT_DISPATCH_EXECUTION_RETRY_DELAY_SECONDS,
                ),
                retryable=True,
                executed_at=now,
            )
        last_status_code = _http_response_status_code(response)
        response_body_hash = optional_text(response.get("response_body_hash"))
        if _http_status_success(last_status_code):
            return _build_dispatch_provider_http_client_result(
                provider_request,
                http_settings=http_settings,
                execution_status="SUCCEEDED",
                attempt_count=attempt_number,
                http_status_code=last_status_code,
                response_body_hash=response_body_hash,
                executed_at=now,
            )
        if _http_status_retryable(last_status_code):
            last_error_code = "dispatch_provider_http_retryable_status"
            if attempt_number < max_attempts:
                continue
            return _build_dispatch_provider_http_client_result(
                provider_request,
                http_settings=http_settings,
                execution_status="RETRY_WAIT",
                attempt_count=attempt_number,
                http_status_code=last_status_code,
                response_body_hash=response_body_hash,
                last_error_code=last_error_code,
                next_attempt_at=_iso_after_seconds(
                    now,
                    DEFAULT_DISPATCH_EXECUTION_RETRY_DELAY_SECONDS,
                ),
                retryable=True,
                executed_at=now,
            )
        return _build_dispatch_provider_http_client_result(
            provider_request,
            http_settings=http_settings,
            execution_status="FAILED",
            attempt_count=attempt_number,
            http_status_code=last_status_code,
            response_body_hash=response_body_hash,
            last_error_code="dispatch_provider_http_rejected",
        retryable=False,
        executed_at=now,
    )


def execute_dispatch_with_live_http_transport(
    dispatch: Mapping[str, Any],
    *,
    transport: Any,
    provider_config: Mapping[str, Any] | None = None,
    request_id: str | None = None,
    trace_id: str | None = None,
    executed_at: str | None = None,
) -> dict[str, Any]:
    now = executed_at or _utc_now()
    config = (
        dict(provider_config)
        if provider_config is not None
        else build_dispatch_execution_provider_config({})
    )
    channel_type = str(dispatch.get("channel_type") or "")
    if channel_type in NOTIFICATION_DISPATCH_CHANNEL_TYPES:
        provider_request = build_notification_dispatch_provider_request(
            dispatch,
            provider_config={**config, "effective_provider_mode": "live_http"},
            request_id=request_id,
            trace_id=trace_id,
            requested_at=now,
        )
    elif channel_type in EXTERNAL_INCIDENT_DISPATCH_CHANNEL_TYPES:
        provider_request = build_external_incident_dispatch_provider_request(
            dispatch,
            provider_config={**config, "effective_provider_mode": "live_http"},
            request_id=request_id,
            trace_id=trace_id,
            requested_at=now,
        )
    else:
        raise OperatorReviewNoteError(
            status_code=422,
            error_code=(
                "ag.operator_review_escalation_dispatch_live_http_channel_"
                "unsupported"
            ),
            detail=f"Unsupported live HTTP dispatch channel_type: {channel_type}",
        )
    http_result = execute_dispatch_provider_http_request(
        provider_request,
        transport=transport,
        provider_config=config,
        executed_at=now,
    )
    execution_status = str(http_result.get("execution_status") or "")
    return _build_provider_adapter_execution_result(
        dispatch,
        provider_request,
        execution_status=execution_status,
        safe_result_message=_live_http_safe_result_message(
            provider_request,
            execution_status,
        ),
        last_error_code=optional_text(http_result.get("last_error_code")),
        next_attempt_at=optional_text(http_result.get("next_attempt_at")),
        retryable=bool(http_result.get("retryable")),
        http_status_code=http_result.get("http_status_code"),
        response_body_hash=optional_text(http_result.get("response_body_hash")),
        attempt_count=int(http_result.get("attempt_count") or 0),
        executed_at=now,
    )


def execute_dispatch_with_provider_router(
    dispatch: Mapping[str, Any],
    *,
    provider_mode: str | None = None,
    provider_config: Mapping[str, Any] | None = None,
    provider_profile: str | None = None,
    request_id: str | None = None,
    trace_id: str | None = None,
    notification_status_code: int | None = None,
    external_incident_status_code: int | None = None,
    live_http_transport: Any | None = None,
    executed_at: str | None = None,
) -> dict[str, Any]:
    config = (
        dict(provider_config)
        if provider_config is not None
        else build_dispatch_execution_provider_config({})
    )
    mode = normalize_dispatch_execution_provider_mode(
        provider_mode
        or optional_text(config.get("effective_provider_mode"))
        or DISPATCH_EXECUTION_PROVIDER_MODE
    )
    routed_config = {**config, "effective_provider_mode": mode}
    channel_type = str(dispatch.get("channel_type") or "")
    if channel_type == "MOCK" or mode == "mock_first_only":
        return execute_dispatch_with_mock_provider(
            dispatch,
            profile_id=provider_profile,
            executed_at=executed_at,
        )
    if mode == "live_http":
        return execute_dispatch_with_live_http_transport(
            dispatch,
            transport=live_http_transport,
            provider_config=routed_config,
            request_id=request_id,
            trace_id=trace_id,
            executed_at=executed_at,
        )
    if channel_type in NOTIFICATION_DISPATCH_CHANNEL_TYPES:
        return execute_dispatch_with_mock_notification_provider(
            dispatch,
            provider_config=routed_config,
            request_id=request_id,
            trace_id=trace_id,
            status_code=notification_status_code,
            executed_at=executed_at,
        )
    if channel_type in EXTERNAL_INCIDENT_DISPATCH_CHANNEL_TYPES:
        return execute_dispatch_with_mock_external_incident_provider(
            dispatch,
            provider_config=routed_config,
            request_id=request_id,
            trace_id=trace_id,
            status_code=external_incident_status_code,
            executed_at=executed_at,
        )
    raise OperatorReviewNoteError(
        status_code=422,
        error_code=(
            "ag.operator_review_escalation_dispatch_execution_router_channel_"
            "unsupported"
        ),
        detail=f"Unsupported dispatch execution router channel_type: {channel_type}",
    )


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
    provider_mode: str | None = None,
    provider_config: Mapping[str, Any] | None = None,
    notification_status_code: int | None = None,
    external_incident_status_code: int | None = None,
    live_http_transport: Any | None = None,
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
                provider_mode=provider_mode,
                provider_config=provider_config,
                notification_status_code=notification_status_code,
                external_incident_status_code=external_incident_status_code,
                live_http_transport=live_http_transport,
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
        "provider_category": execution_result.get("provider_category"),
        "provider_profile": execution_result.get("provider_profile"),
        "provider_request_hash": execution_result.get("provider_request_hash"),
        "provider_result_hash": execution_result.get("provider_result_hash"),
        "http_status_code": execution_result.get("http_status_code"),
        "response_body_hash": execution_result.get("response_body_hash"),
        "attempt_count": execution_result.get("attempt_count"),
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


def _dispatch_daemon_candidate_summary(
    dispatch: Mapping[str, Any],
) -> dict[str, Any]:
    summary = {
        "dispatch_id": str(dispatch.get("dispatch_id") or ""),
        "case_id": str(dispatch.get("case_id") or ""),
        "escalation_id": str(dispatch.get("escalation_id") or ""),
        "dispatch_status": str(dispatch.get("dispatch_status") or ""),
        "dispatch_intent": str(dispatch.get("dispatch_intent") or ""),
        "channel_type": str(dispatch.get("channel_type") or ""),
        "provider_profile": optional_text(dispatch.get("provider_profile")),
        "attempt_count": _non_negative_int(dispatch.get("attempt_count")),
        "last_error_code": optional_text(dispatch.get("last_error_code")),
        "next_attempt_at": optional_text(dispatch.get("next_attempt_at")),
        "redaction": _dispatch_execution_redaction_flags(),
    }
    assert_dispatch_execution_result_redacted(summary)
    return summary


def _dispatch_daemon_tick_safe_summary(
    tick_result: Mapping[str, Any],
) -> dict[str, Any]:
    plan = tick_result.get("plan")
    source_table = (
        plan.get("source_table")
        if isinstance(plan, Mapping)
        else "ag_op_esc_dispatches"
    )
    summary = {
        "tick_status": str(tick_result.get("tick_status") or "UNKNOWN"),
        "blocked_reason": optional_text(tick_result.get("blocked_reason")),
        "worker_id": str(tick_result.get("worker_id") or ""),
        "source_table": source_table,
        "dry_run": bool(tick_result.get("dry_run")),
        "effective_provider_mode": optional_text(
            tick_result.get("effective_provider_mode")
        ),
        "candidate_count": _non_negative_int(tick_result.get("candidate_count")),
        "processed_count": _non_negative_int(tick_result.get("processed_count")),
        "succeeded_count": _non_negative_int(tick_result.get("succeeded_count")),
        "failed_count": _non_negative_int(tick_result.get("failed_count")),
        "retry_wait_count": _non_negative_int(tick_result.get("retry_wait_count")),
        "skipped_count": _non_negative_int(tick_result.get("skipped_count")),
        "new_tables_required": bool(tick_result.get("new_tables_required")),
        "redaction": _dispatch_execution_redaction_flags(),
    }
    assert_dispatch_execution_result_redacted(summary)
    return summary


def _dispatch_daemon_tick_severity(tick_result: Mapping[str, Any]) -> str:
    if str(tick_result.get("tick_status") or "") == "BLOCKED":
        return "WARNING"
    if _non_negative_int(tick_result.get("failed_count")) > 0:
        return "ERROR"
    if _non_negative_int(tick_result.get("retry_wait_count")) > 0:
        return "WARNING"
    return "INFO"


def _count_by_key(
    items: list[dict[str, Any]],
    key: str,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(key) or "UNKNOWN")
        counts[value] = counts.get(value, 0) + 1
    return counts


def _execute_worker_item(
    service: Any,
    dispatch: Mapping[str, Any],
    *,
    run_id: str,
    request_id: str,
    trace_id: str | None,
    worker_id: str,
    provider_profile: str | None,
    provider_mode: str | None,
    provider_config: Mapping[str, Any] | None,
    notification_status_code: int | None,
    external_incident_status_code: int | None,
    live_http_transport: Any | None,
    dry_run: bool,
    executed_at: str,
) -> dict[str, Any]:
    result = execute_dispatch_with_provider_router(
        dispatch,
        provider_mode=provider_mode,
        provider_config=provider_config,
        provider_profile=provider_profile,
        request_id=request_id,
        trace_id=trace_id,
        notification_status_code=notification_status_code,
        external_incident_status_code=external_incident_status_code,
        live_http_transport=live_http_transport,
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


def _notification_provider_profile_for_channel(
    channel_type: str,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    preferred_profile_id = optional_text(config.get("live_provider_profile"))
    preferred = DISPATCH_LIVE_PROVIDER_PROFILES.get(preferred_profile_id or "")
    if preferred is not None and channel_type in preferred.get("channel_types", []):
        return dict(preferred)
    if channel_type == "EMAIL":
        return dict(DISPATCH_LIVE_PROVIDER_PROFILES["email-notification-default"])
    return dict(DISPATCH_LIVE_PROVIDER_PROFILES["notification-webhook-default"])


def _provider_config_endpoint(
    config: Mapping[str, Any],
    endpoint_key: str,
) -> dict[str, Any]:
    endpoints = config.get("endpoints")
    if isinstance(endpoints, Mapping):
        endpoint = endpoints.get(endpoint_key)
        if isinstance(endpoint, Mapping):
            return dict(endpoint)
    return {
        "configured": False,
        "endpoint_hint": None,
        "token_configured": False,
        "secret_storage": "env_only",
    }


def _required_live_http_endpoint(endpoint_url: str | None) -> str:
    endpoint = optional_text(endpoint_url)
    parsed = urlsplit(endpoint or "")
    if endpoint is None or parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise OperatorReviewNoteError(
            status_code=422,
            error_code=(
                "ag.operator_review_escalation_dispatch_live_http_endpoint_invalid"
            ),
            detail="Dispatch live HTTP transport requires an http(s) endpoint.",
        )
    return endpoint


def _live_http_transport_response(
    status_code: int,
    response_body: bytes,
) -> dict[str, Any]:
    body_sample = response_body[:4096]
    return {
        "status_code": status_code,
        "response_body_hash": sha256_text(body_sample.decode("utf-8", "replace")),
    }


def _provider_config_http_settings(config: Mapping[str, Any]) -> dict[str, Any]:
    http = config.get("http")
    if isinstance(http, Mapping):
        return {
            "timeout_seconds": float(
                http.get("timeout_seconds", DEFAULT_DISPATCH_HTTP_TIMEOUT_SECONDS)
            ),
            "connect_timeout_seconds": float(
                http.get(
                    "connect_timeout_seconds",
                    DEFAULT_DISPATCH_HTTP_CONNECT_TIMEOUT_SECONDS,
                )
            ),
            "read_timeout_seconds": float(
                http.get(
                    "read_timeout_seconds",
                    DEFAULT_DISPATCH_HTTP_READ_TIMEOUT_SECONDS,
                )
            ),
            "max_retries": int(
                http.get("max_retries", DEFAULT_DISPATCH_HTTP_MAX_RETRIES)
            ),
            "backoff_seconds": float(
                http.get("backoff_seconds", DEFAULT_DISPATCH_HTTP_BACKOFF_SECONDS)
            ),
        }
    return {
        "timeout_seconds": DEFAULT_DISPATCH_HTTP_TIMEOUT_SECONDS,
        "connect_timeout_seconds": DEFAULT_DISPATCH_HTTP_CONNECT_TIMEOUT_SECONDS,
        "read_timeout_seconds": DEFAULT_DISPATCH_HTTP_READ_TIMEOUT_SECONDS,
        "max_retries": DEFAULT_DISPATCH_HTTP_MAX_RETRIES,
        "backoff_seconds": DEFAULT_DISPATCH_HTTP_BACKOFF_SECONDS,
    }


def _build_provider_adapter_execution_result(
    dispatch: Mapping[str, Any],
    provider_request: Mapping[str, Any],
    *,
    execution_status: str,
    safe_result_message: str,
    last_error_code: str | None = None,
    next_attempt_at: str | None = None,
    retryable: bool = False,
    http_status_code: int | None = None,
    response_body_hash: str | None = None,
    attempt_count: int | None = None,
    executed_at: str | None = None,
) -> dict[str, Any]:
    normalized_status = _required_execution_status(execution_status)
    if normalized_status == "FAILED" and optional_text(last_error_code) is None:
        raise OperatorReviewNoteError(
            status_code=422,
            error_code=(
                "ag.operator_review_escalation_dispatch_execution_error_code_required"
            ),
            detail="FAILED provider adapter results require last_error_code.",
        )
    if normalized_status == "RETRY_WAIT" and optional_text(next_attempt_at) is None:
        raise OperatorReviewNoteError(
            status_code=422,
            error_code=(
                "ag.operator_review_escalation_dispatch_execution_retry_at_required"
            ),
            detail="RETRY_WAIT provider adapter results require next_attempt_at.",
        )
    ref = json.dumps(
        {
            "provider_request_hash": provider_request.get("provider_request_hash"),
            "execution_status": normalized_status,
            "http_status_code": http_status_code,
            "last_error_code": last_error_code,
        },
        sort_keys=True,
    )
    safe_message = operator_note_preview(safe_result_message)
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
        "provider_mode": provider_request.get("provider_mode"),
        "provider_category": provider_request.get("provider_category"),
        "provider_profile": provider_request.get("provider_profile"),
        "provider_request_hash": provider_request.get("provider_request_hash"),
        "http_status_code": http_status_code,
        "response_body_hash": optional_text(response_body_hash),
        "attempt_count": attempt_count,
        "provider_result_ref": {
            "provider_type": provider_request.get("provider_type"),
            "provider_id": provider_request.get("provider_id"),
            "provider_profile": provider_request.get("provider_profile"),
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
        "safe_result_preview": safe_message,
        "retryable": bool(retryable),
        "last_error_code": optional_text(last_error_code),
        "next_attempt_at": optional_text(next_attempt_at),
        "executed_at": executed_at or _utc_now(),
        "redaction": _dispatch_execution_redaction_flags(),
    }
    assert_dispatch_execution_result_redacted(result)
    return result


def _live_http_safe_result_message(
    provider_request: Mapping[str, Any],
    execution_status: str,
) -> str:
    category = str(provider_request.get("provider_category") or "provider")
    if execution_status == "SUCCEEDED":
        return f"Live HTTP {category} provider accepted dispatch."
    if execution_status == "RETRY_WAIT":
        return f"Live HTTP {category} provider returned a retryable result."
    return f"Live HTTP {category} provider rejected dispatch."


def _build_dispatch_provider_http_client_result(
    provider_request: Mapping[str, Any],
    *,
    http_settings: Mapping[str, Any],
    execution_status: str,
    attempt_count: int,
    http_status_code: int | None,
    response_body_hash: str | None,
    last_error_code: str | None = None,
    next_attempt_at: str | None = None,
    retryable: bool = False,
    executed_at: str | None = None,
) -> dict[str, Any]:
    normalized_status = _required_execution_status(execution_status)
    if normalized_status == "FAILED" and optional_text(last_error_code) is None:
        raise OperatorReviewNoteError(
            status_code=422,
            error_code=(
                "ag.operator_review_escalation_dispatch_execution_error_code_required"
            ),
            detail="FAILED HTTP client results require last_error_code.",
        )
    if normalized_status == "RETRY_WAIT" and optional_text(next_attempt_at) is None:
        raise OperatorReviewNoteError(
            status_code=422,
            error_code=(
                "ag.operator_review_escalation_dispatch_execution_retry_at_required"
            ),
            detail="RETRY_WAIT HTTP client results require next_attempt_at.",
        )
    result_hash = sha256_text(
        json.dumps(
            {
                "provider_request_hash": provider_request.get(
                    "provider_request_hash"
                ),
                "execution_status": normalized_status,
                "attempt_count": attempt_count,
                "http_status_code": http_status_code,
                "response_body_hash": response_body_hash,
                "last_error_code": last_error_code,
            },
            sort_keys=True,
        )
    )
    result = {
        "http_client_result_schema_version": (
            DISPATCH_PROVIDER_HTTP_CLIENT_RESULT_SCHEMA_VERSION
        ),
        "provider_request_schema_version": provider_request.get(
            "provider_request_schema_version"
        ),
        "provider_category": provider_request.get("provider_category"),
        "provider_type": provider_request.get("provider_type"),
        "provider_profile": provider_request.get("provider_profile"),
        "provider_mode": provider_request.get("provider_mode"),
        "provider_request_hash": provider_request.get("provider_request_hash"),
        "execution_status": normalized_status,
        "recommended_action": DISPATCH_EXECUTION_RESULT_ACTIONS[normalized_status],
        "attempt_count": attempt_count,
        "max_attempts": int(http_settings["max_retries"]) + 1,
        "http_status_code": http_status_code,
        "response_body_hash": optional_text(response_body_hash),
        "provider_result_hash": result_hash,
        "retryable": bool(retryable),
        "last_error_code": optional_text(last_error_code),
        "next_attempt_at": optional_text(next_attempt_at),
        "timeout_seconds": float(http_settings["timeout_seconds"]),
        "connect_timeout_seconds": float(http_settings["connect_timeout_seconds"]),
        "read_timeout_seconds": float(http_settings["read_timeout_seconds"]),
        "backoff_seconds": float(http_settings["backoff_seconds"]),
        "executed_at": executed_at or _utc_now(),
        "redaction": _dispatch_execution_redaction_flags(),
    }
    assert_dispatch_execution_result_redacted(result)
    return result


def _http_response_status_code(response: Mapping[str, Any]) -> int:
    try:
        return int(response.get("status_code"))
    except (TypeError, ValueError):
        return 0


def _http_status_success(status_code: int) -> bool:
    return 200 <= status_code < 300


def _http_status_retryable(status_code: int) -> bool:
    return status_code in {408, 425, 429} or status_code >= 500


def _safe_text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        text
        for item in value
        if (text := optional_text(item)) is not None
    ]


def _dispatch_provider_http_settings(env: Mapping[str, str]) -> dict[str, Any]:
    return {
        "timeout_seconds": _bounded_float_env(
            env,
            DISPATCH_HTTP_TIMEOUT_SECONDS_ENV,
            default=DEFAULT_DISPATCH_HTTP_TIMEOUT_SECONDS,
            minimum=0.1,
            maximum=MAX_DISPATCH_HTTP_TIMEOUT_SECONDS,
        ),
        "connect_timeout_seconds": _bounded_float_env(
            env,
            DISPATCH_HTTP_CONNECT_TIMEOUT_SECONDS_ENV,
            default=DEFAULT_DISPATCH_HTTP_CONNECT_TIMEOUT_SECONDS,
            minimum=0.1,
            maximum=MAX_DISPATCH_HTTP_TIMEOUT_SECONDS,
        ),
        "read_timeout_seconds": _bounded_float_env(
            env,
            DISPATCH_HTTP_READ_TIMEOUT_SECONDS_ENV,
            default=DEFAULT_DISPATCH_HTTP_READ_TIMEOUT_SECONDS,
            minimum=0.1,
            maximum=MAX_DISPATCH_HTTP_TIMEOUT_SECONDS,
        ),
        "max_retries": _bounded_int_env(
            env,
            DISPATCH_HTTP_MAX_RETRIES_ENV,
            default=DEFAULT_DISPATCH_HTTP_MAX_RETRIES,
            minimum=0,
            maximum=MAX_DISPATCH_HTTP_MAX_RETRIES,
        ),
        "backoff_seconds": _bounded_float_env(
            env,
            DISPATCH_HTTP_BACKOFF_SECONDS_ENV,
            default=DEFAULT_DISPATCH_HTTP_BACKOFF_SECONDS,
            minimum=0.0,
            maximum=30.0,
        ),
    }


def _provider_endpoint_status(endpoint: str | None, *, token: str | None) -> dict[str, Any]:
    return {
        "configured": endpoint is not None,
        "endpoint_hint": _redacted_endpoint_hint(endpoint),
        "token_configured": token is not None,
        "secret_storage": "env_only",
    }


def _redacted_endpoint_hint(endpoint: str | None) -> str | None:
    value = optional_text(endpoint)
    if value is None:
        return None
    parsed = urlsplit(value)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}/<redacted>"
    return "<configured-endpoint>"


def _bounded_float_env(
    env: Mapping[str, str],
    key: str,
    *,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    value = _env_text(env, key)
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    return max(minimum, min(parsed, maximum))


def _bounded_int_env(
    env: Mapping[str, str],
    key: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    value = _env_text(env, key)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return max(minimum, min(parsed, maximum))


def _env_bool(
    env: Mapping[str, str],
    key: str,
    *,
    default: bool = False,
) -> bool:
    value = _env_text(env, key)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _payload_bool(
    payload: Mapping[str, Any],
    key: str,
    *,
    default: bool = False,
) -> bool:
    value = payload.get(key)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes", "on"}


def _dispatch_daemon_control_operator_ref(value: Any) -> dict[str, str] | None:
    if not isinstance(value, Mapping):
        return None
    operator_type = optional_text(value.get("operator_type"))
    operator_id = optional_text(value.get("operator_id"))
    if operator_type is None or operator_id is None:
        return None
    return {
        "operator_type": operator_type,
        "operator_id": operator_id,
    }


def _env_text(env: Mapping[str, str], key: str) -> str | None:
    return optional_text(env.get(key))


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
