from __future__ import annotations

from typing import Any, Mapping

from nex_runtime import OperationalEventStore, normalize_operational_event_limit

from .liveness_ack_expiry_automation import (
    ACK_EXPIRY_AUTOMATION_EVENT_BLOCKED,
    ACK_EXPIRY_AUTOMATION_EVENT_COMPLETED,
    ACK_EXPIRY_AUTOMATION_EVENT_FAILED,
    ACK_EXPIRY_AUTOMATION_EVENT_STARTED,
    build_liveness_ack_expiry_automation_policy,
)


ACK_EXPIRY_AUTOMATION_OPERATIONS_SCHEMA_VERSION = (
    "ag_ack_expiry_automation_operations_projection.v1"
)
ACK_EXPIRY_AUTOMATION_EVENT_TYPES = (
    ACK_EXPIRY_AUTOMATION_EVENT_STARTED,
    ACK_EXPIRY_AUTOMATION_EVENT_COMPLETED,
    ACK_EXPIRY_AUTOMATION_EVENT_BLOCKED,
    ACK_EXPIRY_AUTOMATION_EVENT_FAILED,
)
ACK_EXPIRY_AUTOMATION_CLI_ENTRYPOINT = (
    "python -m nex_ag.liveness_ack_expiry_automation_cli"
)
ACK_EXPIRY_AUTOMATION_EVENT_QUERY_PATH = (
    "/admin/v1/operations/events?service_id=nex-ag"
)


def build_liveness_ack_expiry_automation_operations_projection(
    event_store: OperationalEventStore | None,
    *,
    environ: Mapping[str, str] | None = None,
    event_limit: int = 20,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    policy = build_liveness_ack_expiry_automation_policy(environ)
    normalized_limit = normalize_operational_event_limit(event_limit)
    events, source_status = _automation_events(event_store, normalized_limit)
    projected_events = [_project_event(event) for event in events]
    latest_event = projected_events[0] if projected_events else None
    automation_status = _automation_status(
        enabled=bool(policy["enabled"]),
        source_status=str(source_status["status"]),
        latest_event=latest_event,
    )
    projection_status = (
        "DEGRADED"
        if automation_status in {"DEGRADED", "SOURCE_UNAVAILABLE"}
        else "READY"
    )
    projection = {
        "projection_schema_version": (
            ACK_EXPIRY_AUTOMATION_OPERATIONS_SCHEMA_VERSION
        ),
        "projection_status": projection_status,
        "automation_status": automation_status,
        "policy": policy,
        "summary": {
            "enabled": bool(policy["enabled"]),
            "execution_mode": policy["execution_mode"],
            "batch_limit": int(policy["batch_limit"]),
            "cadence_seconds": int(policy["cadence_seconds"]),
            "event_count": len(projected_events),
            "by_lifecycle": _event_counts(projected_events),
            "latest_event_type": latest_event.get("event_type")
            if latest_event
            else None,
            "latest_event_at": latest_event.get("created_at")
            if latest_event
            else None,
            "requires_operator_action": automation_status
            in {"ATTENTION", "DEGRADED", "SOURCE_UNAVAILABLE"},
            "new_tables_required": False,
        },
        "recent_events": projected_events,
        "source_statuses": {"nex-ag": source_status},
        "scheduler": {
            "owner": "external_scheduler",
            "cadence_seconds": int(policy["cadence_seconds"]),
            "cli_entrypoint": ACK_EXPIRY_AUTOMATION_CLI_ENTRYPOINT,
            "arguments": ["--run-once", "--confirm-tick", "--summary"],
            "continuous_loop_started": False,
            "subprocess_started": False,
        },
        "event_query_path": ACK_EXPIRY_AUTOMATION_EVENT_QUERY_PATH,
        "new_tables_required": False,
        "redaction": {
            "raw_comments_included": False,
            "raw_idempotency_keys_included": False,
            "raw_payloads_included": False,
            "database_urls_included": False,
            "tokens_included": False,
            "exception_details_included": False,
        },
    }
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    return projection


def _automation_events(
    event_store: OperationalEventStore | None,
    limit: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if event_store is None:
        return [], _source_status("NOT_CONFIGURED", event_count=0)
    try:
        events_by_id: dict[str, dict[str, Any]] = {}
        for event_type in ACK_EXPIRY_AUTOMATION_EVENT_TYPES:
            for event in event_store.list_events(
                service_id="nex-ag",
                event_type=event_type,
                limit=limit,
            ):
                events_by_id[str(event.get("event_id") or "")] = dict(event)
        events = sorted(
            events_by_id.values(),
            key=lambda event: (
                str(event.get("created_at") or ""),
                str(event.get("event_id") or ""),
            ),
            reverse=True,
        )[:limit]
    except Exception as exc:
        return [], _source_status(
            "UNAVAILABLE",
            event_count=0,
            error_code=str(
                getattr(
                    exc,
                    "error_code",
                    "ag.ack_expiry_automation_event_source_unavailable",
                )
            ),
        )
    return events, _source_status("READY", event_count=len(events))


def _source_status(
    status: str,
    *,
    event_count: int,
    error_code: str | None = None,
) -> dict[str, Any]:
    result = {
        "status": status,
        "service_id": "nex-ag",
        "source_kind": "operational_events",
        "source_table": "service_operational_events",
        "event_count": event_count,
        "new_tables_required": False,
    }
    if error_code is not None:
        result["error_code"] = error_code
        result["detail"] = "Acknowledgement expiry automation events unavailable."
    return result


def _project_event(event: Mapping[str, Any]) -> dict[str, Any]:
    details = event.get("details") if isinstance(event.get("details"), Mapping) else {}
    return {
        "event_id": event.get("event_id"),
        "event_type": event.get("event_type"),
        "severity": event.get("severity"),
        "created_at": event.get("created_at"),
        "request_id": event.get("request_id"),
        "trace_id": event.get("trace_id"),
        "tick_id": details.get("tick_id"),
        "tick_status": details.get("tick_status"),
        "blocked_reason": details.get("blocked_reason"),
        "failure_code": details.get("failure_code"),
        "candidate_count": _non_negative_int(details.get("candidate_count")),
        "applied_count": _non_negative_int(details.get("applied_count")),
        "conflict_count": _non_negative_int(details.get("conflict_count")),
        "mutation_performed": bool(details.get("mutation_performed")),
        "raw_payload_included": False,
    }


def _automation_status(
    *,
    enabled: bool,
    source_status: str,
    latest_event: Mapping[str, Any] | None,
) -> str:
    if not enabled:
        return "DISABLED"
    if source_status == "UNAVAILABLE":
        return "SOURCE_UNAVAILABLE"
    if latest_event is None:
        return "WAITING_FIRST_RUN"
    event_type = str(latest_event.get("event_type") or "")
    if event_type == ACK_EXPIRY_AUTOMATION_EVENT_FAILED:
        return "DEGRADED"
    if event_type == ACK_EXPIRY_AUTOMATION_EVENT_BLOCKED:
        return "ATTENTION"
    if event_type == ACK_EXPIRY_AUTOMATION_EVENT_STARTED:
        return "RUNNING"
    return "HEALTHY"


def _event_counts(events: list[dict[str, Any]]) -> dict[str, int]:
    counts = {name: 0 for name in ("started", "completed", "blocked", "failed")}
    for event in events:
        lifecycle = str(event.get("event_type") or "").rsplit(".", 1)[-1]
        if lifecycle in counts:
            counts[lifecycle] += 1
    return counts


def _non_negative_int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
