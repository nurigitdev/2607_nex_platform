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
RECOVERY_NOTIFICATION_DELIVERY_OPERATIONS_SCHEMA_VERSION = (
    "ag_recovery_notification_delivery_operations_projection.v1"
)
RECOVERY_NOTIFICATION_DELIVERY_PATH = (
    "/admin/v1/operator-review/dispatch-daemon/liveness/"
    "recovery-notification-deliveries"
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
        "delivery": build_recovery_notification_delivery_operations_projection([]),
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
        "delivery": build_recovery_notification_delivery_operations_projection([]),
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


def build_recovery_notification_delivery_operations_projection(
    dispatch_records: list[Mapping[str, Any]] | None,
    *,
    limit: int = 5,
    error_code: str | None = None,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    if dispatch_records is None:
        projection = _degraded_delivery_projection(
            error_code=error_code
            or "ag.recovery_notification_delivery_source_unavailable",
        )
    else:
        bounded_limit = max(1, min(50, int(limit)))
        selected = [
            record
            for record in dispatch_records
            if _is_recovery_notification_dispatch(record)
        ]
        selected.sort(
            key=lambda record: (
                str(record.get("updated_at") or ""),
                str(record.get("dispatch_id") or ""),
            ),
            reverse=True,
        )
        by_status: dict[str, int] = {}
        for record in selected:
            status = str(record.get("dispatch_status") or "UNKNOWN")
            by_status[status] = by_status.get(status, 0) + 1
        projection = {
            "projection_schema_version": (
                RECOVERY_NOTIFICATION_DELIVERY_OPERATIONS_SCHEMA_VERSION
            ),
            "projection_status": "READY",
            "delivery_status": "ACTIVE" if selected else "EMPTY",
            "summary": {
                "total": len(selected),
                "pending": by_status.get("PENDING", 0),
                "dispatching": by_status.get("DISPATCHING", 0),
                "succeeded": by_status.get("SUCCEEDED", 0),
                "failed": by_status.get("FAILED", 0),
                "retry_wait": by_status.get("RETRY_WAIT", 0),
                "cancelled": by_status.get("CANCELLED", 0),
                "provider_invocation_performed": any(
                    int(record.get("attempt_count") or 0) > 0
                    for record in selected
                ),
            },
            "by_status": dict(sorted(by_status.items())),
            "recent": [
                _delivery_projection_item(record)
                for record in selected[:bounded_limit]
            ],
            "source_statuses": {
                "nex-ag": {
                    "status": "READY",
                    "service_id": "nex-ag",
                    "source_kind": "existing_escalation_dispatch_outbox",
                    "source_table": "ag_op_esc_dispatches",
                    "new_tables_required": False,
                }
            },
            "delivery_path": RECOVERY_NOTIFICATION_DELIVERY_PATH,
            "new_tables_required": False,
            "redaction": _delivery_redaction_contract(),
        }
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    return projection


def _degraded_delivery_projection(*, error_code: str) -> dict[str, Any]:
    return {
        "projection_schema_version": (
            RECOVERY_NOTIFICATION_DELIVERY_OPERATIONS_SCHEMA_VERSION
        ),
        "projection_status": "DEGRADED",
        "delivery_status": "SOURCE_UNAVAILABLE",
        "summary": {
            "total": 0,
            "pending": 0,
            "dispatching": 0,
            "succeeded": 0,
            "failed": 0,
            "retry_wait": 0,
            "cancelled": 0,
            "provider_invocation_performed": False,
        },
        "by_status": {},
        "recent": [],
        "source_statuses": {
            "nex-ag": {
                "status": "UNAVAILABLE",
                "service_id": "nex-ag",
                "source_kind": "existing_escalation_dispatch_outbox",
                "source_table": "ag_op_esc_dispatches",
                "error_code": error_code,
                "new_tables_required": False,
            }
        },
        "delivery_path": RECOVERY_NOTIFICATION_DELIVERY_PATH,
        "new_tables_required": False,
        "redaction": _delivery_redaction_contract(),
    }


def _is_recovery_notification_dispatch(record: Mapping[str, Any]) -> bool:
    metadata = record.get("metadata")
    if not isinstance(metadata, Mapping):
        return False
    delivery = metadata.get("recovery_notification_delivery")
    return isinstance(delivery, Mapping)


def _delivery_projection_item(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "dispatch_id": record.get("dispatch_id"),
        "case_id": record.get("case_id"),
        "escalation_id": record.get("escalation_id"),
        "dispatch_status": record.get("dispatch_status"),
        "dispatch_intent": record.get("dispatch_intent"),
        "channel_type": record.get("channel_type"),
        "provider_profile": record.get("provider_profile"),
        "target_service": record.get("target_service"),
        "target_kind": record.get("target_kind"),
        "target_id": record.get("target_id"),
        "safe_subject": record.get("safe_subject"),
        "safe_body_preview": record.get("safe_body_preview"),
        "attempt_count": int(record.get("attempt_count") or 0),
        "last_error_code": record.get("last_error_code"),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "completed_at": record.get("completed_at"),
        "execution": _delivery_execution_projection(record),
        "detail_path": (
            "/admin/v1/operator-review/dispatches/"
            f"{record.get('dispatch_id')}"
        ),
    }


def _delivery_execution_projection(record: Mapping[str, Any]) -> dict[str, Any] | None:
    metadata = record.get("metadata")
    if not isinstance(metadata, Mapping):
        return None
    result = metadata.get("last_execution_result")
    if not isinstance(result, Mapping):
        return None
    return {
        "execution_status": result.get("execution_status"),
        "provider_mode": result.get("provider_mode"),
        "provider_category": result.get("provider_category"),
        "provider_profile": result.get("provider_profile"),
        "provider_result_hash": result.get("provider_result_hash"),
        "http_status_code": result.get("http_status_code"),
        "response_body_hash": result.get("response_body_hash"),
        "attempt_count": int(result.get("attempt_count") or 0),
        "safe_result_preview": result.get("safe_result_preview"),
        "retryable": bool(result.get("retryable")),
        "last_error_code": result.get("last_error_code"),
        "executed_at": result.get("executed_at"),
    }


def _delivery_redaction_contract() -> dict[str, bool]:
    return {
        "raw_recovery_plan_included": False,
        "raw_notification_payload_included": False,
        "provider_payload_hashes_included": False,
        "safe_body_hashes_included": False,
        "request_signatures_included": False,
        "provider_endpoints_included": False,
        "provider_tokens_included": False,
        "database_urls_included": False,
        "idempotency_keys_included": False,
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
