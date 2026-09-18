from __future__ import annotations

from typing import Any, Mapping

from .recovery_notification_policy import (
    RecoveryNotificationPolicyError,
    build_recovery_notification_plan,
    build_recovery_notification_policy,
)


RECOVERY_NOTIFICATION_OPERATIONS_SCHEMA_VERSION = (
    "ag_recovery_notification_operations_projection.v1"
)
RECOVERY_NOTIFICATION_PREVIEW_PATH = (
    "/admin/v1/operator-review/dispatch-daemon/liveness/"
    "recovery-notification-preview"
)


def build_recovery_notification_operations_projection(
    recovery_section: Mapping[str, Any] | None,
    *,
    environ: Mapping[str, str] | None = None,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    policy = build_recovery_notification_policy(environ)
    if not isinstance(recovery_section, Mapping) or (
        recovery_section.get("projection_status") != "READY"
    ):
        return _degraded_projection(
            policy,
            error_code="ag.recovery_notification_recovery_source_unavailable",
            request_trace_id=request_trace_id,
        )
    recovery_plan = {
        "projection_schema_version": recovery_section.get(
            "projection_schema_version"
        ),
        "summary": recovery_section.get("summary"),
        "recommended_actions": recovery_section.get("recommended_actions", []),
        "acknowledgement_state_overlay": recovery_section.get(
            "acknowledgement_state_overlay"
        ),
        "daemon_identity": _daemon_identity(recovery_section),
    }
    try:
        preview = build_recovery_notification_plan(
            recovery_plan,
            policy=policy,
            request_trace_id=request_trace_id,
        )
    except (RecoveryNotificationPolicyError, KeyError, TypeError, ValueError) as exc:
        return _degraded_projection(
            policy,
            error_code=str(
                getattr(
                    exc,
                    "error_code",
                    "ag.recovery_notification_projection_failed",
                )
            ),
            request_trace_id=request_trace_id,
        )
    projection = {
        "projection_schema_version": (
            RECOVERY_NOTIFICATION_OPERATIONS_SCHEMA_VERSION
        ),
        "projection_status": "READY",
        "notification_status": preview["plan_status"],
        "policy": policy,
        "summary": {
            "enabled": bool(policy["enabled"]),
            "delivery_enabled": bool(policy["delivery_enabled"]),
            "minimum_severity": policy["minimum_severity"],
            "repeat_window_seconds": int(policy["repeat_window_seconds"]),
            "critical_bypass_suppression": bool(
                policy["critical_bypass_suppression"]
            ),
            "decision_status": preview["decision"]["decision_status"],
            "severity": preview["decision"]["severity"],
            "eligible": bool(preview["decision"]["eligible"]),
            "provider_invocation_performed": False,
            "new_tables_required": False,
        },
        "preview": preview,
        "preview_path": RECOVERY_NOTIFICATION_PREVIEW_PATH,
        "source_statuses": {
            "nex-ag": {
                "status": "READY",
                "service_id": "nex-ag",
                "source_kind": "derived_recovery_notification_policy",
                "source_table": "ag_op_review_ack_state",
                "new_tables_required": False,
            }
        },
        "new_tables_required": False,
        "redaction": _redaction_contract(),
    }
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    return projection


def _degraded_projection(
    policy: Mapping[str, Any],
    *,
    error_code: str,
    request_trace_id: str | None,
) -> dict[str, Any]:
    projection = {
        "projection_schema_version": (
            RECOVERY_NOTIFICATION_OPERATIONS_SCHEMA_VERSION
        ),
        "projection_status": "DEGRADED",
        "notification_status": "SOURCE_UNAVAILABLE",
        "policy": dict(policy),
        "summary": {
            "enabled": bool(policy["enabled"]),
            "delivery_enabled": bool(policy["delivery_enabled"]),
            "minimum_severity": policy["minimum_severity"],
            "repeat_window_seconds": int(policy["repeat_window_seconds"]),
            "critical_bypass_suppression": bool(
                policy["critical_bypass_suppression"]
            ),
            "decision_status": None,
            "severity": None,
            "eligible": False,
            "provider_invocation_performed": False,
            "new_tables_required": False,
        },
        "preview": None,
        "preview_path": RECOVERY_NOTIFICATION_PREVIEW_PATH,
        "source_statuses": {
            "nex-ag": {
                "status": "UNAVAILABLE",
                "service_id": "nex-ag",
                "source_kind": "derived_recovery_notification_policy",
                "source_table": "ag_op_review_ack_state",
                "error_code": error_code,
                "new_tables_required": False,
            }
        },
        "new_tables_required": False,
        "redaction": _redaction_contract(),
    }
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    return projection


def _daemon_identity(recovery_section: Mapping[str, Any]) -> dict[str, str]:
    source = recovery_section.get("source_evidence")
    source_map = source if isinstance(source, Mapping) else {}
    return {
        "service_id": str(source_map.get("service_id") or "nex-ag"),
        "worker_id": str(
            source_map.get("worker_id") or "ag-dispatch-execution-daemon"
        ),
    }


def _redaction_contract() -> dict[str, bool]:
    return {
        "raw_recovery_plan_included": False,
        "raw_comments_included": False,
        "raw_idempotency_keys_included": False,
        "provider_payloads_included": False,
        "provider_endpoints_included": False,
        "provider_tokens_included": False,
        "database_urls_included": False,
    }
