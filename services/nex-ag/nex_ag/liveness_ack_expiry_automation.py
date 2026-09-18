from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid5

from nex_runtime import OperationalEventEmitter, OperationalEventEmitResult

from .liveness_ack_expiry_reconciliation import (
    run_operator_review_liveness_ack_expiry_reconciliation,
)
from .operator_review_liveness_ack import _parse_datetime
from .operator_reviews import _datetime_value


ACK_EXPIRY_AUTOMATION_POLICY_SCHEMA_VERSION = (
    "ag_ack_expiry_automation_policy.v1"
)
ACK_EXPIRY_AUTOMATION_TICK_PLAN_SCHEMA_VERSION = (
    "ag_ack_expiry_automation_tick_plan.v1"
)
ACK_EXPIRY_AUTOMATION_TICK_RESULT_SCHEMA_VERSION = (
    "ag_ack_expiry_automation_tick_result.v1"
)
ACK_EXPIRY_AUTOMATION_EVENT_DETAILS_SCHEMA_VERSION = (
    "ag_ack_expiry_automation_event_details.v1"
)
ACK_EXPIRY_AUTOMATION_EVENT_STARTED = (
    "ag.operator_review_escalation_dispatch_daemon."
    "liveness_ack_expiry_automation.started"
)
ACK_EXPIRY_AUTOMATION_EVENT_COMPLETED = (
    "ag.operator_review_escalation_dispatch_daemon."
    "liveness_ack_expiry_automation.completed"
)
ACK_EXPIRY_AUTOMATION_EVENT_BLOCKED = (
    "ag.operator_review_escalation_dispatch_daemon."
    "liveness_ack_expiry_automation.blocked"
)
ACK_EXPIRY_AUTOMATION_EVENT_FAILED = (
    "ag.operator_review_escalation_dispatch_daemon."
    "liveness_ack_expiry_automation.failed"
)
ACK_EXPIRY_AUTOMATION_ENABLED_ENV = "NEX_AG_ACK_EXPIRY_AUTOMATION_ENABLED"
ACK_EXPIRY_AUTOMATION_BATCH_LIMIT_ENV = (
    "NEX_AG_ACK_EXPIRY_AUTOMATION_BATCH_LIMIT"
)
ACK_EXPIRY_AUTOMATION_CADENCE_SECONDS_ENV = (
    "NEX_AG_ACK_EXPIRY_AUTOMATION_CADENCE_SECONDS"
)
DEFAULT_ACK_EXPIRY_AUTOMATION_BATCH_LIMIT = 50
MAX_ACK_EXPIRY_AUTOMATION_BATCH_LIMIT = 200
DEFAULT_ACK_EXPIRY_AUTOMATION_CADENCE_SECONDS = 60
MIN_ACK_EXPIRY_AUTOMATION_CADENCE_SECONDS = 10
MAX_ACK_EXPIRY_AUTOMATION_CADENCE_SECONDS = 3600


def build_liveness_ack_expiry_automation_policy(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    enabled = _env_flag(env.get(ACK_EXPIRY_AUTOMATION_ENABLED_ENV), default=False)
    batch_limit = _bounded_int(
        env.get(ACK_EXPIRY_AUTOMATION_BATCH_LIMIT_ENV),
        default=DEFAULT_ACK_EXPIRY_AUTOMATION_BATCH_LIMIT,
        minimum=1,
        maximum=MAX_ACK_EXPIRY_AUTOMATION_BATCH_LIMIT,
    )
    cadence_seconds = _bounded_int(
        env.get(ACK_EXPIRY_AUTOMATION_CADENCE_SECONDS_ENV),
        default=DEFAULT_ACK_EXPIRY_AUTOMATION_CADENCE_SECONDS,
        minimum=MIN_ACK_EXPIRY_AUTOMATION_CADENCE_SECONDS,
        maximum=MAX_ACK_EXPIRY_AUTOMATION_CADENCE_SECONDS,
    )
    return {
        "automation_policy_schema_version": (
            ACK_EXPIRY_AUTOMATION_POLICY_SCHEMA_VERSION
        ),
        "policy_status": "ENABLED" if enabled else "DISABLED",
        "enabled": enabled,
        "execution_mode": "externally_scheduled_bounded_run_once",
        "batch_limit": batch_limit,
        "cadence_seconds": cadence_seconds,
        "requires_confirm_tick": True,
        "source_table": "ag_op_review_ack_state",
        "event_table": "service_operational_events",
        "tick_executor": (
            "run_operator_review_liveness_ack_expiry_reconciliation"
        ),
        "new_tables_required": False,
        "continuous_loop_started": False,
        "subprocess_started": False,
        "guardrails": {
            "disabled_by_default": True,
            "bounded_batch": True,
            "compare_and_set": True,
            "external_scheduler_owns_cadence": True,
            "source_liveness_projection_mutated": False,
            "retention_or_physical_delete_performed": False,
        },
        "redaction": {
            "raw_comments_included": False,
            "raw_idempotency_keys_included": False,
            "raw_payloads_included": False,
            "database_urls_included": False,
            "tokens_included": False,
        },
    }


def build_liveness_ack_expiry_automation_tick_plan(
    state_store: Any,
    *,
    request_id: str,
    trace_id: str | None = None,
    policy: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
    planned_at: object | None = None,
) -> dict[str, Any]:
    resolved_policy = dict(
        policy
        if policy is not None
        else build_liveness_ack_expiry_automation_policy(environ)
    )
    observed = _datetime_value(
        _parse_datetime(planned_at if planned_at is not None else datetime.now(UTC))
    )
    candidates = (
        state_store.list_expiry_candidates(
            observed_at=observed,
            limit=int(resolved_policy["batch_limit"]),
        )
        if bool(resolved_policy.get("enabled"))
        else []
    )
    plan_status = (
        "DISABLED"
        if not bool(resolved_policy.get("enabled"))
        else "READY" if candidates else "IDLE"
    )
    plan_id = str(
        uuid5(
            NAMESPACE_URL,
            "nex-ag:ack-expiry-automation-plan:"
            f"{request_id}:{observed}:{resolved_policy['batch_limit']}:"
            f"{len(candidates)}",
        )
    )
    return {
        "tick_plan_schema_version": (
            ACK_EXPIRY_AUTOMATION_TICK_PLAN_SCHEMA_VERSION
        ),
        "tick_plan_id": plan_id,
        "plan_status": plan_status,
        "request_id": str(request_id),
        "trace_id": str(trace_id) if trace_id is not None else None,
        "planned_at": observed,
        "batch_limit": int(resolved_policy["batch_limit"]),
        "candidate_count": len(candidates),
        "candidate_summaries": [
            _automation_candidate_summary(candidate) for candidate in candidates
        ],
        "policy": resolved_policy,
        "will_mutate": False,
        "source_table": "ag_op_review_ack_state",
        "new_tables_required": False,
        "redaction": resolved_policy["redaction"],
    }


def run_liveness_ack_expiry_automation_tick_once(
    state_store: Any,
    *,
    request_id: str,
    trace_id: str | None = None,
    policy: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
    confirm_tick: bool = False,
    executed_at: object | None = None,
) -> dict[str, Any]:
    resolved_policy = dict(
        policy
        if policy is not None
        else build_liveness_ack_expiry_automation_policy(environ)
    )
    observed = _datetime_value(
        _parse_datetime(executed_at if executed_at is not None else datetime.now(UTC))
    )
    plan = build_liveness_ack_expiry_automation_tick_plan(
        state_store,
        request_id=request_id,
        trace_id=trace_id,
        policy=resolved_policy,
        planned_at=observed,
    )
    blocked_reason = None
    if not bool(resolved_policy.get("enabled")):
        blocked_reason = "automation_disabled"
    elif not confirm_tick:
        blocked_reason = "confirm_tick_required"
    worker_run = (
        run_operator_review_liveness_ack_expiry_reconciliation(
            state_store,
            observed_at=observed,
            limit=int(resolved_policy["batch_limit"]),
        )
        if blocked_reason is None
        else None
    )
    tick_status = (
        "BLOCKED"
        if blocked_reason is not None
        else (
            "COMPLETED_WITH_CONFLICTS"
            if int((worker_run or {}).get("conflict_count") or 0) > 0
            else "COMPLETED"
        )
    )
    tick_id = str(
        uuid5(
            NAMESPACE_URL,
            "nex-ag:ack-expiry-automation-tick:"
            f"{request_id}:{observed}:{plan['tick_plan_id']}:{confirm_tick}",
        )
    )
    return {
        "tick_result_schema_version": (
            ACK_EXPIRY_AUTOMATION_TICK_RESULT_SCHEMA_VERSION
        ),
        "tick_id": tick_id,
        "tick_status": tick_status,
        "blocked_reason": blocked_reason,
        "request_id": str(request_id),
        "trace_id": str(trace_id) if trace_id is not None else None,
        "executed_at": observed,
        "confirm_tick": bool(confirm_tick),
        "plan": plan,
        "worker_run": worker_run,
        "planned_candidate_count": int(plan["candidate_count"]),
        "candidate_count": int((worker_run or {}).get("candidate_count") or 0),
        "applied_count": int((worker_run or {}).get("applied_count") or 0),
        "conflict_count": int((worker_run or {}).get("conflict_count") or 0),
        "skipped_count": int((worker_run or {}).get("skipped_count") or 0),
        "mutation_performed": int((worker_run or {}).get("applied_count") or 0)
        > 0,
        "new_tables_required": False,
        "guardrails": {
            "enabled_required": True,
            "confirm_tick_required": True,
            "execution_requeries_candidates": True,
            "compare_and_set": True,
            "continuous_loop_started": False,
            "subprocess_started": False,
        },
        "redaction": resolved_policy["redaction"],
    }


def build_liveness_ack_expiry_automation_event_details(
    *,
    result: Mapping[str, Any] | None = None,
    error_code: str | None = None,
) -> dict[str, Any]:
    tick = result if isinstance(result, Mapping) else {}
    plan = tick.get("plan") if isinstance(tick.get("plan"), Mapping) else {}
    return {
        "automation_event_details_schema_version": (
            ACK_EXPIRY_AUTOMATION_EVENT_DETAILS_SCHEMA_VERSION
        ),
        "tick_id": tick.get("tick_id"),
        "tick_status": tick.get("tick_status"),
        "blocked_reason": tick.get("blocked_reason"),
        "plan_status": plan.get("plan_status"),
        "batch_limit": int(plan.get("batch_limit") or 0),
        "planned_candidate_count": int(
            tick.get("planned_candidate_count") or 0
        ),
        "candidate_count": int(tick.get("candidate_count") or 0),
        "applied_count": int(tick.get("applied_count") or 0),
        "conflict_count": int(tick.get("conflict_count") or 0),
        "skipped_count": int(tick.get("skipped_count") or 0),
        "mutation_performed": bool(tick.get("mutation_performed")),
        "failure_code": str(error_code) if error_code else None,
        "source_table": "ag_op_review_ack_state",
        "event_table": "service_operational_events",
        "new_tables_required": False,
        "raw_comments_included": False,
        "raw_idempotency_keys_included": False,
        "raw_payloads_included": False,
        "sensitive_values_included": False,
    }


def emit_liveness_ack_expiry_automation_event(
    emitter: OperationalEventEmitter | None,
    *,
    event_name: str,
    request_id: str,
    trace_id: str | None = None,
    result: Mapping[str, Any] | None = None,
    error_code: str | None = None,
    occurred_at: str | None = None,
) -> OperationalEventEmitResult:
    if emitter is None:
        return OperationalEventEmitResult.failed(
            error_code="ag.ack_expiry_automation_event_emitter_not_configured",
            detail="Acknowledgement expiry automation event emitter is not configured.",
            status_code=503,
        )
    event_type, severity, message = _automation_event_envelope(event_name)
    tick_id = (
        str(result.get("tick_id"))
        if isinstance(result, Mapping) and result.get("tick_id")
        else str(request_id)
    )
    return emitter.safe_emit(
        event_type=event_type,
        severity=severity,
        message=message,
        trace_id=trace_id,
        request_id=request_id,
        subject_ref={
            "type": "ag_ack_expiry_automation_tick",
            "id": tick_id,
        },
        details=build_liveness_ack_expiry_automation_event_details(
            result=result,
            error_code=error_code,
        ),
        created_at=occurred_at,
    )


def _automation_candidate_summary(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "ack_state_id": candidate.get("ack_state_id"),
        "service_id": candidate.get("service_id"),
        "worker_id": candidate.get("worker_id"),
        "liveness_status": candidate.get("liveness_status"),
        "state_status": candidate.get("state_status"),
        "suppressed_until": candidate.get("suppressed_until"),
        "raw_comment_included": False,
        "raw_idempotency_key_included": False,
    }


def _env_flag(value: object, *, default: bool) -> bool:
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    return default


def _bounded_int(
    value: object,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        parsed = int(value) if value is not None else default
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _automation_event_envelope(event_name: str) -> tuple[str, str, str]:
    normalized = str(event_name or "").replace("-", "_")
    envelopes = {
        "started": (
            ACK_EXPIRY_AUTOMATION_EVENT_STARTED,
            "INFO",
            "AG acknowledgement expiry automation tick started.",
        ),
        "completed": (
            ACK_EXPIRY_AUTOMATION_EVENT_COMPLETED,
            "INFO",
            "AG acknowledgement expiry automation tick completed.",
        ),
        "blocked": (
            ACK_EXPIRY_AUTOMATION_EVENT_BLOCKED,
            "WARNING",
            "AG acknowledgement expiry automation tick blocked.",
        ),
        "failed": (
            ACK_EXPIRY_AUTOMATION_EVENT_FAILED,
            "ERROR",
            "AG acknowledgement expiry automation tick failed.",
        ),
    }
    if normalized not in envelopes:
        raise ValueError(f"Unsupported acknowledgement expiry event: {event_name}")
    return envelopes[normalized]
