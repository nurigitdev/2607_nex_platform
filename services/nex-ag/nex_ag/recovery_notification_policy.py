from __future__ import annotations

import os
from datetime import UTC, datetime
from re import fullmatch
from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid5


RECOVERY_NOTIFICATION_POLICY_SCHEMA_VERSION = (
    "ag_recovery_notification_policy.v1"
)
RECOVERY_NOTIFICATION_DECISION_SCHEMA_VERSION = (
    "ag_recovery_notification_decision.v1"
)
RECOVERY_NOTIFICATION_PLAN_SCHEMA_VERSION = "ag_recovery_notification_plan.v1"
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
        "redaction": _redaction_contract(),
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
        "redaction": _redaction_contract(),
    }


def build_recovery_notification_plan(
    recovery_plan: Mapping[str, Any],
    *,
    policy: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
    evaluated_at: object | None = None,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    decision = evaluate_recovery_notification_eligibility(
        recovery_plan,
        policy=policy,
        environ=environ,
        evaluated_at=evaluated_at,
    )
    daemon_identity = recovery_plan.get("daemon_identity")
    identity = daemon_identity if isinstance(daemon_identity, Mapping) else {}
    service_id = _safe_identifier(identity.get("service_id"), default="nex-ag")
    worker_id = _safe_identifier(
        identity.get("worker_id"),
        default="ag-dispatch-execution-daemon",
    )
    trace_id = _safe_identifier(request_trace_id, default=None)
    plan_status = _notification_plan_status(decision)
    plan_id = str(
        uuid5(
            NAMESPACE_URL,
            "nex-ag:recovery-notification-plan:"
            f"{service_id}:{worker_id}:{decision['liveness_status']}:"
            f"{decision['severity']}:{decision['effective_ack_state']}:"
            f"{decision['evaluated_at']}",
        )
    )
    safe_payload = {
        "payload_schema_version": "ag_recovery_notification_preview_payload.v1",
        "title": _notification_title(
            decision["severity"],
            decision["liveness_status"],
        ),
        "summary": _notification_summary(decision),
        "service_id": service_id,
        "worker_id": worker_id,
        "liveness_status": decision["liveness_status"],
        "severity": decision["severity"],
        "action_count": decision["action_count"],
        "reason_codes": list(decision["reason_codes"]),
        "evaluated_at": decision["evaluated_at"],
        "recovery_plan_path": (
            "/admin/v1/operator-review/dispatch-daemon/liveness/recovery-plan"
        ),
    }
    return {
        "notification_plan_schema_version": RECOVERY_NOTIFICATION_PLAN_SCHEMA_VERSION,
        "notification_plan_id": plan_id,
        "plan_status": plan_status,
        "decision": {
            key: decision[key]
            for key in (
                "decision_status",
                "eligible",
                "delivery_authorized_by_policy",
                "severity",
                "minimum_severity",
                "effective_ack_state",
                "reason_codes",
            )
        },
        "audience": ["nex-ag-operators"],
        "preview_channels": ["operations_dashboard"],
        "safe_payload": safe_payload,
        "request_trace_id": trace_id,
        "delivery": {
            "authorized_by_policy": bool(
                decision["delivery_authorized_by_policy"]
            ),
            "performed": False,
            "provider_invocation_performed": False,
            "provider_profile_id": None,
            "provider_endpoint": None,
        },
        "source": {
            "kind": "derived_recovery_notification_policy",
            "recovery_plan_schema_version": recovery_plan.get(
                "projection_schema_version"
            ),
            "raw_recovery_plan_included": False,
        },
        "new_tables_required": False,
        "redaction": _redaction_contract(),
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


def _notification_plan_status(decision: Mapping[str, Any]) -> str:
    if decision.get("decision_status") == "SUPPRESSED":
        return "SUPPRESSED"
    if not bool(decision.get("eligible")):
        return "NOT_REQUIRED"
    if bool(decision.get("delivery_authorized_by_policy")):
        return "READY"
    return "PREVIEW_ONLY"


def _safe_identifier(value: object, *, default: str | None) -> str | None:
    if not isinstance(value, str):
        return default
    normalized = value.strip()
    if not normalized or len(normalized) > 64:
        return default
    return normalized if fullmatch(r"[A-Za-z0-9._:-]+", normalized) else default


def _notification_title(severity: str, liveness_status: str) -> str:
    return f"[{severity}] AG dispatch recovery attention: {liveness_status}"


def _notification_summary(decision: Mapping[str, Any]) -> str:
    return (
        "Dispatch recovery policy evaluated "
        f"{decision.get('action_count', 0)} action(s) as "
        f"{decision.get('decision_status', 'UNKNOWN')}."
    )


def _redaction_contract() -> dict[str, bool]:
    return {
        "raw_comments_included": False,
        "raw_idempotency_keys_included": False,
        "raw_payloads_included": False,
        "provider_endpoints_included": False,
        "provider_tokens_included": False,
        "database_urls_included": False,
    }
