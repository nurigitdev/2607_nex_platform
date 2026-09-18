from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any, Mapping


RECOVERY_NOTIFICATION_POLICY_SCHEMA_VERSION = (
    "ag_recovery_notification_policy.v1"
)
RECOVERY_NOTIFICATION_DECISION_SCHEMA_VERSION = (
    "ag_recovery_notification_decision.v1"
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
RECOVERY_NOTIFICATION_SEVERITY_RANK = {
    severity: rank for rank, severity in enumerate(RECOVERY_NOTIFICATION_SEVERITIES)
}


class RecoveryNotificationPolicyError(ValueError):
    def __init__(self, detail: str, *, error_code: str) -> None:
        super().__init__(detail)
        self.detail = detail
        self.error_code = error_code
        self.status_code = 400


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


def evaluate_recovery_notification_eligibility(
    recovery_plan: Mapping[str, Any],
    *,
    policy: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
    evaluated_at: object | None = None,
) -> dict[str, Any]:
    if not isinstance(recovery_plan, Mapping):
        raise RecoveryNotificationPolicyError(
            "recovery_plan must be an object.",
            error_code="ag.recovery_notification_plan_invalid",
        )
    summary = recovery_plan.get("summary")
    if not isinstance(summary, Mapping):
        raise RecoveryNotificationPolicyError(
            "recovery_plan.summary must be an object.",
            error_code="ag.recovery_notification_summary_invalid",
        )
    actions = recovery_plan.get("recommended_actions", [])
    if not isinstance(actions, list) or any(
        not isinstance(item, Mapping) for item in actions
    ):
        raise RecoveryNotificationPolicyError(
            "recovery_plan.recommended_actions must be an array of objects.",
            error_code="ag.recovery_notification_actions_invalid",
        )
    resolved_policy = dict(
        policy
        if policy is not None
        else build_recovery_notification_policy(environ)
    )
    observed = _datetime_value(evaluated_at)
    highest_severity = _highest_action_severity(actions)
    overlay = recovery_plan.get("acknowledgement_state_overlay")
    overlay_map = overlay if isinstance(overlay, Mapping) else {}
    effective_state = str(
        overlay_map.get("effective_state_status") or "NONE"
    ).upper()
    minimum_severity = _severity(
        resolved_policy.get("minimum_severity"),
        default=DEFAULT_RECOVERY_NOTIFICATION_MIN_SEVERITY,
    )
    reason_codes: list[str] = []
    decision_status = "ELIGIBLE"
    if not bool(resolved_policy.get("enabled")):
        decision_status = "INELIGIBLE"
        reason_codes.append("policy_disabled")
    elif not actions:
        decision_status = "INELIGIBLE"
        reason_codes.append("no_recovery_action")
    elif RECOVERY_NOTIFICATION_SEVERITY_RANK[highest_severity] < (
        RECOVERY_NOTIFICATION_SEVERITY_RANK[minimum_severity]
    ):
        decision_status = "INELIGIBLE"
        reason_codes.append("below_minimum_severity")
    elif effective_state == "ACKNOWLEDGED":
        decision_status = "SUPPRESSED"
        reason_codes.append("acknowledged_repeat")
    elif effective_state == "SUPPRESSED" and not (
        highest_severity == "CRITICAL"
        and bool(resolved_policy.get("critical_bypass_suppression"))
    ):
        decision_status = "SUPPRESSED"
        reason_codes.append("active_suppression")
    else:
        reason_codes.append(
            "critical_bypass_suppression"
            if effective_state == "SUPPRESSED"
            else "eligible_recovery_signal"
        )
    eligible = decision_status == "ELIGIBLE"
    return {
        "notification_decision_schema_version": (
            RECOVERY_NOTIFICATION_DECISION_SCHEMA_VERSION
        ),
        "decision_status": decision_status,
        "eligible": eligible,
        "delivery_authorized_by_policy": eligible
        and bool(resolved_policy.get("delivery_enabled")),
        "provider_invocation_performed": False,
        "evaluated_at": observed,
        "liveness_status": str(summary.get("liveness_status") or "UNKNOWN"),
        "severity": highest_severity,
        "minimum_severity": minimum_severity,
        "effective_ack_state": effective_state,
        "action_count": len(actions),
        "reason_codes": reason_codes,
        "repeat_window_seconds": int(resolved_policy["repeat_window_seconds"]),
        "new_tables_required": False,
        "redaction": resolved_policy["redaction"],
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


def _highest_action_severity(actions: list[Mapping[str, Any]]) -> str:
    severities = [
        _severity(item.get("severity"), default="INFO") for item in actions
    ]
    return max(
        severities or ["INFO"],
        key=lambda severity: RECOVERY_NOTIFICATION_SEVERITY_RANK[severity],
    )


def _datetime_value(value: object | None) -> str:
    if value is None:
        parsed = datetime.now(UTC)
    elif isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise RecoveryNotificationPolicyError(
                "evaluated_at must be an ISO-8601 timestamp.",
                error_code="ag.recovery_notification_evaluated_at_invalid",
            ) from exc
    else:
        raise RecoveryNotificationPolicyError(
            "evaluated_at must be an ISO-8601 timestamp.",
            error_code="ag.recovery_notification_evaluated_at_invalid",
        )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
