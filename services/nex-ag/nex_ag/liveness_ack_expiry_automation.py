from __future__ import annotations

import os
from typing import Any, Mapping


ACK_EXPIRY_AUTOMATION_POLICY_SCHEMA_VERSION = (
    "ag_ack_expiry_automation_policy.v1"
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
