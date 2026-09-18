from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid5

from .operator_review_liveness_ack import _parse_datetime
from .operator_reviews import _datetime_value


ACK_EXPIRY_AUTOMATION_POLICY_SCHEMA_VERSION = (
    "ag_ack_expiry_automation_policy.v1"
)
ACK_EXPIRY_AUTOMATION_TICK_PLAN_SCHEMA_VERSION = (
    "ag_ack_expiry_automation_tick_plan.v1"
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
