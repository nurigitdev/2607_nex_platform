from __future__ import annotations

import os
from typing import Any, Mapping


RECOVERY_NOTIFICATION_POLICY_SCHEMA_VERSION = (
    "ag_recovery_notification_policy.v1"
)
RECOVERY_NOTIFICATION_POLICY_ENABLED_ENV = (
    "NEX_AG_RECOVERY_NOTIFICATION_POLICY_ENABLED"
)
RECOVERY_NOTIFICATION_DELIVERY_ENABLED_ENV = (
    "NEX_AG_RECOVERY_NOTIFICATION_DELIVERY_ENABLED"
)
RECOVERY_NOTIFICATION_MIN_SEVERITY_ENV = (
    "NEX_AG_RECOVERY_NOTIFICATION_MIN_SEVERITY"
)
RECOVERY_NOTIFICATION_REPEAT_WINDOW_SECONDS_ENV = (
    "NEX_AG_RECOVERY_NOTIFICATION_REPEAT_WINDOW_SECONDS"
)
RECOVERY_NOTIFICATION_CRITICAL_BYPASS_SUPPRESSION_ENV = (
    "NEX_AG_RECOVERY_NOTIFICATION_CRITICAL_BYPASS_SUPPRESSION"
)
RECOVERY_NOTIFICATION_SEVERITIES = ("INFO", "WARNING", "ERROR", "CRITICAL")
DEFAULT_RECOVERY_NOTIFICATION_MIN_SEVERITY = "WARNING"
DEFAULT_RECOVERY_NOTIFICATION_REPEAT_WINDOW_SECONDS = 900
MIN_RECOVERY_NOTIFICATION_REPEAT_WINDOW_SECONDS = 60
MAX_RECOVERY_NOTIFICATION_REPEAT_WINDOW_SECONDS = 86400


def build_recovery_notification_policy(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = os.environ if environ is None else environ
    enabled = _env_flag(
        env.get(RECOVERY_NOTIFICATION_POLICY_ENABLED_ENV),
        default=True,
    )
    delivery_enabled = _env_flag(
        env.get(RECOVERY_NOTIFICATION_DELIVERY_ENABLED_ENV),
        default=False,
    )
    minimum_severity = _severity(
        env.get(RECOVERY_NOTIFICATION_MIN_SEVERITY_ENV),
        default=DEFAULT_RECOVERY_NOTIFICATION_MIN_SEVERITY,
    )
    repeat_window_seconds = _bounded_int(
        env.get(RECOVERY_NOTIFICATION_REPEAT_WINDOW_SECONDS_ENV),
        default=DEFAULT_RECOVERY_NOTIFICATION_REPEAT_WINDOW_SECONDS,
        minimum=MIN_RECOVERY_NOTIFICATION_REPEAT_WINDOW_SECONDS,
        maximum=MAX_RECOVERY_NOTIFICATION_REPEAT_WINDOW_SECONDS,
    )
    critical_bypass = _env_flag(
        env.get(RECOVERY_NOTIFICATION_CRITICAL_BYPASS_SUPPRESSION_ENV),
        default=True,
    )
    return {
        "notification_policy_schema_version": (
            RECOVERY_NOTIFICATION_POLICY_SCHEMA_VERSION
        ),
        "policy_status": "ENABLED" if enabled else "DISABLED",
        "enabled": enabled,
        "delivery_enabled": delivery_enabled,
        "evaluation_mode": "deterministic_preview_only",
        "minimum_severity": minimum_severity,
        "severity_order": list(RECOVERY_NOTIFICATION_SEVERITIES),
        "repeat_window_seconds": repeat_window_seconds,
        "critical_bypass_suppression": critical_bypass,
        "preview_channels": ["operations_dashboard"],
        "source_surfaces": [
            "dispatch_daemon_liveness_recovery_plan",
            "acknowledgement_suppression_state_overlay",
        ],
        "source_tables": [
            "ag_op_review_ack_state",
            "service_operational_events",
        ],
        "new_tables_required": False,
        "guardrails": {
            "delivery_disabled_by_default": True,
            "external_provider_invocation_allowed": False,
            "dispatch_persistence_allowed": False,
            "active_suppression_evaluated": True,
            "acknowledgement_repeat_suppression_evaluated": True,
            "severity_escalation_may_bypass_acknowledgement": True,
            "retention_or_physical_delete_performed": False,
        },
        "redaction": {
            "raw_comments_included": False,
            "raw_idempotency_keys_included": False,
            "raw_payloads_included": False,
            "provider_endpoints_included": False,
            "provider_tokens_included": False,
            "database_urls_included": False,
        },
    }


def _env_flag(value: object, *, default: bool) -> bool:
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _severity(value: object, *, default: str) -> str:
    normalized = str(value or "").strip().upper()
    return normalized if normalized in RECOVERY_NOTIFICATION_SEVERITIES else default


def _bounded_int(
    value: object,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))
