from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import time, timedelta
from typing import Any, Callable, Mapping
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_ae_api.artifacts import (
    ARTIFACT_RETENTION_SCHEDULER_TICK_LOCK_TTL_SECONDS,
    ARTIFACT_RETENTION_SCHEDULER_TICK_STALE_AFTER_SECONDS,
    ArtifactHandoffError,
    assert_artifact_retention_payload_safe,
    build_artifact_retention_scheduler_tick_plan,
    build_artifact_retention_scheduler_config,
    format_artifact_retention_timestamp,
    enqueue_artifact_retention_scheduler_tick_job,
    optional_text,
    parse_artifact_retention_timestamp,
    run_artifact_retention_scheduled_worker_once,
    sha256_json,
    validate_artifact_retention_batch_plan,
    validate_artifact_retention_scheduler_config,
    validate_artifact_retention_scheduler_tick_enqueue_result,
    validate_artifact_retention_scheduler_tick_plan,
)


AE_ARTIFACT_RETENTION_SCHEDULER_LEASE_REQUEST_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_lease_request.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_LEASE_RECORD_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_lease_record.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_LEASE_DECISION_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_lease_decision.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_TICK_ONCE_RESULT_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_tick_once_result.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONFIG_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_config.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONTROL_PLAN_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_control_plan.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_DISPATCH_RESULT_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_dispatch_result.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_START_STOP_GUARDRAIL_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_start_stop_guardrail.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUNTIME_CONFIG_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_runtime_config.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_LOOP_PLAN_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_loop_plan.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ONE_CYCLE_RESULT_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_one_cycle_result.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_BOUNDED_LOOP_RESULT_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_bounded_loop_result.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SHUTDOWN_TRANSITION_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_shutdown_transition.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUNTIME_OBSERVATION_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_runtime_observation.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUNTIME_STATE_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_runtime_state.v1"
)

DEFAULT_ARTIFACT_RETENTION_SCHEDULER_LEASE_OWNER_ID = (
    "ae-artifact-retention-scheduler-manual-once"
)
DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ONE_CYCLE_LEASE_OWNER_ID = (
    "ae-artifact-retention-scheduler-daemon-one-cycle"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_WORKER_TYPE = (
    "ae.artifact_retention.scheduler_daemon"
)
ARTIFACT_RETENTION_SCHEDULER_LEASE_OPERATION_MANUAL_TICK_ONCE = "manual_tick_once"
ARTIFACT_RETENTION_SCHEDULER_LEASE_OPERATIONS = (
    ARTIFACT_RETENTION_SCHEDULER_LEASE_OPERATION_MANUAL_TICK_ONCE,
)
ARTIFACT_RETENTION_SCHEDULER_LEASE_RECORD_STATUSES = (
    "HELD",
    "RELEASED",
    "EXPIRED",
)
ARTIFACT_RETENTION_SCHEDULER_LEASE_DECISION_STATUSES = (
    "ACQUIRED",
    "BUSY",
)
ARTIFACT_RETENTION_SCHEDULER_TICK_ONCE_RESULT_STATUSES = (
    "SUCCEEDED",
    "NOOP",
    "SKIPPED",
    "FAILED",
)
ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONTROL_ACTION_STATUS_PROBE = "status_probe"
ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONTROL_ACTION_MANUAL_TICK_ONCE = (
    ARTIFACT_RETENTION_SCHEDULER_LEASE_OPERATION_MANUAL_TICK_ONCE
)
ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONTROL_ACTION_START_DAEMON = "start_daemon"
ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONTROL_ACTION_STOP_DAEMON = "stop_daemon"
ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONTROL_ACTIONS = (
    ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONTROL_ACTION_STATUS_PROBE,
    ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONTROL_ACTION_MANUAL_TICK_ONCE,
    ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONTROL_ACTION_START_DAEMON,
    ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONTROL_ACTION_STOP_DAEMON,
)
ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONTROL_PLAN_STATUSES = (
    "READY",
    "BLOCKED",
    "NOOP",
)
ARTIFACT_RETENTION_SCHEDULER_DAEMON_DISPATCH_STATUSES = (
    "DISPATCHED",
    "BLOCKED",
    "NOOP",
)
ARTIFACT_RETENTION_SCHEDULER_DAEMON_START_STOP_GUARDRAIL_STATUSES = (
    "BLOCKED",
    "NOOP",
)
ARTIFACT_RETENTION_SCHEDULER_DAEMON_START_STOP_GUARDRAIL_REASONS = (
    "daemon_disabled_by_policy",
    "daemon_not_running",
)
ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONTROL_BLOCK_REASONS = (
    "daemon_disabled_by_policy",
    "operator_dispatch_admission_disabled",
    "scheduler_tick_admission_disabled",
    "lease_repository_unavailable",
    "job_queue_unavailable",
)
ARTIFACT_RETENTION_SCHEDULER_TICK_ONCE_SKIP_REASONS = (
    "lease_busy",
    "scheduler_tick_admission_disabled",
    "job_queue_unavailable",
    "outside_batch_window",
    "no_retention_candidates",
)
ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUNTIME_PROFILES = ("test",)
ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUNTIME_ENABLEMENT_STATUSES = (
    "DISABLED",
    "READY",
    "BLOCKED",
)
ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUNTIME_BLOCK_REASONS = (
    "explicit_opt_in_required",
)
ARTIFACT_RETENTION_SCHEDULER_DAEMON_LOOP_PLAN_DECISION_STATUSES = (
    "READY",
    "BLOCKED",
    "DISABLED",
    "NOOP",
)
ARTIFACT_RETENTION_SCHEDULER_DAEMON_LOOP_PLAN_DECISION_REASONS = (
    "runtime_disabled",
    "explicit_opt_in_required",
    "scheduler_tick_admission_disabled",
    "operator_dispatch_admission_disabled",
    "lease_repository_unavailable",
    "job_queue_unavailable",
    "outside_batch_window",
    "stop_requested",
)
ARTIFACT_RETENTION_SCHEDULER_DAEMON_ONE_CYCLE_RESULT_STATUSES = (
    "SUCCEEDED",
    "NOOP",
    "SKIPPED",
    "FAILED",
)
ARTIFACT_RETENTION_SCHEDULER_DAEMON_BOUNDED_LOOP_RESULT_STATUSES = (
    "SUCCEEDED",
    "SKIPPED",
    "STOPPED",
    "FAILED",
)
ARTIFACT_RETENTION_SCHEDULER_DAEMON_BOUNDED_LOOP_STOP_REASONS = (
    "max_cycles_reached",
    "runtime_disabled",
    "explicit_opt_in_required",
    "stop_requested",
    "cycle_failed",
)
ARTIFACT_RETENTION_SCHEDULER_DAEMON_SHUTDOWN_TRANSITION_DECISION_STATUSES = (
    "READY",
    "NOOP",
)
ARTIFACT_RETENTION_SCHEDULER_DAEMON_SHUTDOWN_TRANSITION_DECISION_REASONS = (
    "stop_requested",
    "stop_already_requested",
    "already_stopped",
    "runtime_disabled",
    "explicit_opt_in_required",
)
ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUNTIME_STATE_STATUSES = (
    "DISABLED",
    "STARTING",
    "RUNNING",
    "STOPPING",
    "STOPPED",
    "ERROR",
)
ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUNTIME_STATE_REASONS = (
    "runtime_disabled",
    "explicit_opt_in_required",
    "initialized",
    "start_requested",
    "bounded_loop_running",
    "stop_requested",
    "stopped",
    "cycle_failed",
)
DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_MAX_TICKS_PER_RUN = 1
MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_MAX_TICKS_PER_RUN = 1
DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_BACKOFF_SECONDS = 60
MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_INTERVAL_SECONDS = 86_400
MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_BACKOFF_SECONDS = 3_600
MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_BOUNDED_LOOP_CYCLES = 100
MIN_ARTIFACT_RETENTION_SCHEDULER_LEASE_TTL_SECONDS = 60
MAX_ARTIFACT_RETENTION_SCHEDULER_LEASE_TTL_SECONDS = (
    ARTIFACT_RETENTION_SCHEDULER_TICK_STALE_AFTER_SECONDS
)


def build_artifact_retention_scheduler_lease_request(
    *,
    scheduler_config: Mapping[str, Any] | None = None,
    scheduler_id: str | None = None,
    lease_owner_id: str = DEFAULT_ARTIFACT_RETENTION_SCHEDULER_LEASE_OWNER_ID,
    requested_at: str | None = None,
    lease_ttl_seconds: int | str | None = None,
    operation: str = ARTIFACT_RETENTION_SCHEDULER_LEASE_OPERATION_MANUAL_TICK_ONCE,
    tick_id: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    config = validate_artifact_retention_scheduler_config(
        dict(scheduler_config)
        if scheduler_config is not None
        else build_artifact_retention_scheduler_config()
    )
    normalized_scheduler_id = _required_text(
        scheduler_id or config["scheduler_id"],
        "scheduler_id",
        "ae.artifact_retention_scheduler_lease_request_invalid",
    )
    normalized_owner_id = _required_text(
        lease_owner_id,
        "lease_owner_id",
        "ae.artifact_retention_scheduler_lease_request_invalid",
    )
    ttl_seconds = normalize_artifact_retention_scheduler_lease_ttl_seconds(
        lease_ttl_seconds
    )
    requested_dt = parse_artifact_retention_timestamp(
        requested_at or _request_time_from_config(config),
        field_name="requested_at",
    )
    normalized_requested_at = format_artifact_retention_timestamp(requested_dt)
    expires_at = format_artifact_retention_timestamp(
        requested_dt + timedelta(seconds=ttl_seconds)
    )
    normalized_operation = normalize_artifact_retention_scheduler_lease_operation(
        operation
    )
    normalized_idempotency_key = optional_text(
        idempotency_key
    ) or artifact_retention_scheduler_lease_idempotency_key(
        scheduler_id=normalized_scheduler_id,
        lease_owner_id=normalized_owner_id,
        operation=normalized_operation,
        requested_at=normalized_requested_at,
    )
    request = {
        "lease_request_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_LEASE_REQUEST_SCHEMA_VERSION
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": normalized_scheduler_id,
        "lease_owner_id": normalized_owner_id,
        "operation": normalized_operation,
        "tick_id": optional_text(tick_id),
        "requested_at": normalized_requested_at,
        "expires_at": expires_at,
        "lease_ttl_seconds": ttl_seconds,
        "stale_after_seconds": ARTIFACT_RETENTION_SCHEDULER_TICK_STALE_AFTER_SECONDS,
        "idempotency_key": normalized_idempotency_key,
        "guardrails": {
            "lease_required_before_tick": True,
            "manual_once_runner": True,
            "daemon_auto_start_allowed": False,
            "scheduler_daemon_started": False,
            "continuous_loop_started": False,
            "continuous_loop_allowed_before_lease": False,
            "physical_delete_automation_enabled": False,
        },
        "metadata": _scheduler_lease_metadata(),
    }
    return validate_artifact_retention_scheduler_lease_request(request)


def validate_artifact_retention_scheduler_lease_request(
    request: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_request_invalid",
            detail="Artifact retention scheduler lease request must be an object.",
        )
    normalized = dict(request)
    if (
        normalized.get("lease_request_schema_version")
        != AE_ARTIFACT_RETENTION_SCHEDULER_LEASE_REQUEST_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_request_schema_invalid",
            detail="Artifact retention scheduler lease request schema version is invalid.",
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_request_invalid",
            detail="Artifact retention scheduler lease request service id is invalid.",
        )
    for field_name in ("scheduler_id", "lease_owner_id", "idempotency_key"):
        _required_text(
            normalized.get(field_name),
            field_name,
            "ae.artifact_retention_scheduler_lease_request_invalid",
        )
    operation = normalize_artifact_retention_scheduler_lease_operation(
        normalized.get("operation")
    )
    ttl_seconds = normalize_artifact_retention_scheduler_lease_ttl_seconds(
        normalized.get("lease_ttl_seconds")
    )
    requested_at = parse_artifact_retention_timestamp(
        normalized.get("requested_at"),
        field_name="requested_at",
    )
    expires_at = parse_artifact_retention_timestamp(
        normalized.get("expires_at"),
        field_name="expires_at",
    )
    expected_expires_at = format_artifact_retention_timestamp(
        requested_at + timedelta(seconds=ttl_seconds)
    )
    if format_artifact_retention_timestamp(expires_at) != expected_expires_at:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_request_invalid",
            detail="Artifact retention scheduler lease request expires_at is invalid.",
        )
    if normalized.get("stale_after_seconds") != (
        ARTIFACT_RETENTION_SCHEDULER_TICK_STALE_AFTER_SECONDS
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_request_invalid",
            detail="Artifact retention scheduler lease stale window is invalid.",
        )
    if optional_text(normalized.get("tick_id")) != normalized.get("tick_id"):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_request_invalid",
            detail="Artifact retention scheduler lease tick id is invalid.",
        )
    if normalized.get("guardrails") != _scheduler_lease_guardrails():
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_request_invalid",
            detail="Artifact retention scheduler lease request guardrails are invalid.",
        )
    if normalized.get("metadata") != _scheduler_lease_metadata():
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_request_invalid",
            detail="Artifact retention scheduler lease request metadata is invalid.",
        )
    normalized["operation"] = operation
    normalized["lease_ttl_seconds"] = ttl_seconds
    normalized["requested_at"] = format_artifact_retention_timestamp(requested_at)
    normalized["expires_at"] = expected_expires_at
    assert_artifact_retention_payload_safe(normalized)
    return normalized


def build_artifact_retention_scheduler_lease_record(
    request: Mapping[str, Any],
    *,
    lease_token: str | None = None,
    fencing_token: int | str = 1,
    lease_status: str = "HELD",
    acquired_at: str | None = None,
    expires_at: str | None = None,
    released_at: str | None = None,
    last_observed_at: str | None = None,
) -> dict[str, Any]:
    validated_request = validate_artifact_retention_scheduler_lease_request(request)
    normalized_fencing_token = _positive_int(
        fencing_token,
        "fencing_token",
        "ae.artifact_retention_scheduler_lease_record_invalid",
    )
    normalized_status = normalize_artifact_retention_scheduler_lease_record_status(
        lease_status
    )
    normalized_acquired_at = format_artifact_retention_timestamp(
        parse_artifact_retention_timestamp(
            acquired_at or validated_request["requested_at"],
            field_name="acquired_at",
        )
    )
    normalized_expires_at = format_artifact_retention_timestamp(
        parse_artifact_retention_timestamp(
            expires_at or validated_request["expires_at"],
            field_name="expires_at",
        )
    )
    normalized_released_at = (
        format_artifact_retention_timestamp(
            parse_artifact_retention_timestamp(released_at, field_name="released_at")
        )
        if released_at is not None
        else None
    )
    normalized_last_observed_at = format_artifact_retention_timestamp(
        parse_artifact_retention_timestamp(
            last_observed_at or normalized_acquired_at,
            field_name="last_observed_at",
        )
    )
    normalized_lease_token = optional_text(lease_token) or _lease_token(
        validated_request,
        fencing_token=normalized_fencing_token,
    )
    record = {
        "lease_record_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_LEASE_RECORD_SCHEMA_VERSION
        ),
        "lease_record_id": _lease_record_id(
            scheduler_id=validated_request["scheduler_id"],
            lease_token=normalized_lease_token,
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": validated_request["scheduler_id"],
        "lease_owner_id": validated_request["lease_owner_id"],
        "lease_token": normalized_lease_token,
        "lease_status": normalized_status,
        "fencing_token": normalized_fencing_token,
        "acquired_at": normalized_acquired_at,
        "expires_at": normalized_expires_at,
        "released_at": normalized_released_at,
        "last_observed_at": normalized_last_observed_at,
        "operation": validated_request["operation"],
        "tick_id": validated_request["tick_id"],
        "idempotency_key": validated_request["idempotency_key"],
        "guardrails": deepcopy(validated_request["guardrails"]),
        "metadata": _scheduler_lease_metadata(),
    }
    return validate_artifact_retention_scheduler_lease_record(record)


def validate_artifact_retention_scheduler_lease_record(
    record: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(record, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_record_invalid",
            detail="Artifact retention scheduler lease record must be an object.",
        )
    normalized = dict(record)
    if (
        normalized.get("lease_record_schema_version")
        != AE_ARTIFACT_RETENTION_SCHEDULER_LEASE_RECORD_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_record_schema_invalid",
            detail="Artifact retention scheduler lease record schema version is invalid.",
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_record_invalid",
            detail="Artifact retention scheduler lease record service id is invalid.",
        )
    for field_name in (
        "lease_record_id",
        "scheduler_id",
        "lease_owner_id",
        "lease_token",
        "idempotency_key",
    ):
        _required_text(
            normalized.get(field_name),
            field_name,
            "ae.artifact_retention_scheduler_lease_record_invalid",
        )
    normalized["operation"] = normalize_artifact_retention_scheduler_lease_operation(
        normalized.get("operation")
    )
    normalized["lease_status"] = normalize_artifact_retention_scheduler_lease_record_status(
        normalized.get("lease_status")
    )
    normalized["fencing_token"] = _positive_int(
        normalized.get("fencing_token"),
        "fencing_token",
        "ae.artifact_retention_scheduler_lease_record_invalid",
    )
    acquired_at = parse_artifact_retention_timestamp(
        normalized.get("acquired_at"),
        field_name="acquired_at",
    )
    expires_at = parse_artifact_retention_timestamp(
        normalized.get("expires_at"),
        field_name="expires_at",
    )
    last_observed_at = parse_artifact_retention_timestamp(
        normalized.get("last_observed_at"),
        field_name="last_observed_at",
    )
    if expires_at <= acquired_at:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_record_invalid",
            detail="Artifact retention scheduler lease expiry must follow acquisition.",
        )
    released_at = normalized.get("released_at")
    if normalized["lease_status"] == "RELEASED":
        if released_at is None:
            raise ArtifactHandoffError(
                status_code=422,
                error_code="ae.artifact_retention_scheduler_lease_record_invalid",
                detail="Released artifact retention scheduler lease requires released_at.",
            )
        released_dt = parse_artifact_retention_timestamp(
            released_at,
            field_name="released_at",
        )
        if released_dt < acquired_at:
            raise ArtifactHandoffError(
                status_code=422,
                error_code="ae.artifact_retention_scheduler_lease_record_invalid",
                detail="Artifact retention scheduler lease release precedes acquisition.",
            )
    elif released_at is not None:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_record_invalid",
            detail="Only released scheduler leases may carry released_at.",
        )
    if last_observed_at < acquired_at:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_record_invalid",
            detail="Artifact retention scheduler lease observation precedes acquisition.",
        )
    if optional_text(normalized.get("tick_id")) != normalized.get("tick_id"):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_record_invalid",
            detail="Artifact retention scheduler lease tick id is invalid.",
        )
    if normalized.get("guardrails") != _scheduler_lease_guardrails():
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_record_invalid",
            detail="Artifact retention scheduler lease record guardrails are invalid.",
        )
    if normalized.get("metadata") != _scheduler_lease_metadata():
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_record_invalid",
            detail="Artifact retention scheduler lease record metadata is invalid.",
        )
    normalized["acquired_at"] = format_artifact_retention_timestamp(acquired_at)
    normalized["expires_at"] = format_artifact_retention_timestamp(expires_at)
    normalized["last_observed_at"] = format_artifact_retention_timestamp(
        last_observed_at
    )
    assert_artifact_retention_payload_safe(normalized)
    return normalized


def release_artifact_retention_scheduler_lease(
    record: Mapping[str, Any],
    *,
    lease_token: str,
    released_at: str | None = None,
) -> dict[str, Any]:
    validated = validate_artifact_retention_scheduler_lease_record(record)
    normalized_token = _required_text(
        lease_token,
        "lease_token",
        "ae.artifact_retention_scheduler_lease_release_invalid",
    )
    if normalized_token != validated["lease_token"]:
        raise ArtifactHandoffError(
            status_code=409,
            error_code="ae.artifact_retention_scheduler_lease_token_mismatch",
            detail="Artifact retention scheduler lease token does not match.",
        )
    if validated["lease_status"] == "RELEASED":
        return validated
    released = {
        **validated,
        "lease_status": "RELEASED",
        "released_at": (
            released_at
            or format_artifact_retention_timestamp(
                parse_artifact_retention_timestamp(
                    validated["last_observed_at"],
                    field_name="released_at",
                )
            )
        ),
        "last_observed_at": released_at or validated["last_observed_at"],
    }
    return validate_artifact_retention_scheduler_lease_record(released)


def build_artifact_retention_scheduler_lease_decision(
    request: Mapping[str, Any],
    *,
    lease_record: Mapping[str, Any] | None = None,
    blocking_lease: Mapping[str, Any] | None = None,
    decision_at: str | None = None,
) -> dict[str, Any]:
    validated_request = validate_artifact_retention_scheduler_lease_request(request)
    acquired_record = (
        validate_artifact_retention_scheduler_lease_record(lease_record)
        if lease_record is not None
        else None
    )
    blocked_record = (
        validate_artifact_retention_scheduler_lease_record(blocking_lease)
        if blocking_lease is not None
        else None
    )
    if acquired_record is not None and blocked_record is not None:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_decision_invalid",
            detail="Lease decision cannot be both acquired and busy.",
        )
    decision_status = "ACQUIRED" if acquired_record is not None else "BUSY"
    if decision_status == "BUSY" and blocked_record is None:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_decision_invalid",
            detail="Busy scheduler lease decision requires a blocking lease.",
        )
    decision = {
        "lease_decision_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_LEASE_DECISION_SCHEMA_VERSION
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": validated_request["scheduler_id"],
        "lease_owner_id": validated_request["lease_owner_id"],
        "operation": validated_request["operation"],
        "decision_status": decision_status,
        "lease_acquired": decision_status == "ACQUIRED",
        "skip_reason": None if decision_status == "ACQUIRED" else "lease_busy",
        "decision_at": format_artifact_retention_timestamp(
            parse_artifact_retention_timestamp(
                decision_at or validated_request["requested_at"],
                field_name="decision_at",
            )
        ),
        "lease_record": deepcopy(acquired_record),
        "blocking_lease": deepcopy(blocked_record),
        "lease_token": acquired_record["lease_token"] if acquired_record else None,
        "fencing_token": acquired_record["fencing_token"] if acquired_record else None,
        "idempotency_key": validated_request["idempotency_key"],
        "guardrails": deepcopy(validated_request["guardrails"]),
        "metadata": _scheduler_lease_metadata(),
    }
    return validate_artifact_retention_scheduler_lease_decision(decision)


def validate_artifact_retention_scheduler_lease_decision(
    decision: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(decision, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_decision_invalid",
            detail="Artifact retention scheduler lease decision must be an object.",
        )
    normalized = dict(decision)
    if (
        normalized.get("lease_decision_schema_version")
        != AE_ARTIFACT_RETENTION_SCHEDULER_LEASE_DECISION_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_decision_schema_invalid",
            detail="Artifact retention scheduler lease decision schema version is invalid.",
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_decision_invalid",
            detail="Artifact retention scheduler lease decision service id is invalid.",
        )
    for field_name in ("scheduler_id", "lease_owner_id", "operation", "idempotency_key"):
        _required_text(
            normalized.get(field_name),
            field_name,
            "ae.artifact_retention_scheduler_lease_decision_invalid",
        )
    normalized["operation"] = normalize_artifact_retention_scheduler_lease_operation(
        normalized.get("operation")
    )
    parse_artifact_retention_timestamp(
        normalized.get("decision_at"),
        field_name="decision_at",
    )
    decision_status = normalized.get("decision_status")
    if decision_status not in ARTIFACT_RETENTION_SCHEDULER_LEASE_DECISION_STATUSES:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_decision_invalid",
            detail="Artifact retention scheduler lease decision status is invalid.",
        )
    if decision_status == "ACQUIRED":
        lease_record = validate_artifact_retention_scheduler_lease_record(
            normalized.get("lease_record")
        )
        if (
            normalized.get("lease_acquired") is not True
            or normalized.get("skip_reason") is not None
            or normalized.get("blocking_lease") is not None
            or normalized.get("lease_token") != lease_record["lease_token"]
            or normalized.get("fencing_token") != lease_record["fencing_token"]
            or lease_record["scheduler_id"] != normalized["scheduler_id"]
            or lease_record["lease_owner_id"] != normalized["lease_owner_id"]
        ):
            raise ArtifactHandoffError(
                status_code=422,
                error_code="ae.artifact_retention_scheduler_lease_decision_invalid",
                detail="Acquired artifact retention scheduler lease decision is invalid.",
            )
    else:
        blocking_lease = validate_artifact_retention_scheduler_lease_record(
            normalized.get("blocking_lease")
        )
        if (
            normalized.get("lease_acquired") is not False
            or normalized.get("skip_reason") != "lease_busy"
            or normalized.get("lease_record") is not None
            or normalized.get("lease_token") is not None
            or normalized.get("fencing_token") is not None
            or blocking_lease["scheduler_id"] != normalized["scheduler_id"]
        ):
            raise ArtifactHandoffError(
                status_code=422,
                error_code="ae.artifact_retention_scheduler_lease_decision_invalid",
                detail="Busy artifact retention scheduler lease decision is invalid.",
            )
    if normalized.get("guardrails") != _scheduler_lease_guardrails():
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_decision_invalid",
            detail="Artifact retention scheduler lease decision guardrails are invalid.",
        )
    if normalized.get("metadata") != _scheduler_lease_metadata():
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_decision_invalid",
            detail="Artifact retention scheduler lease decision metadata is invalid.",
        )
    assert_artifact_retention_payload_safe(normalized)
    return normalized


def summarize_artifact_retention_scheduler_lease_decision(
    decision: Mapping[str, Any],
) -> dict[str, Any]:
    validated = validate_artifact_retention_scheduler_lease_decision(decision)
    return {
        "scheduler_id": validated["scheduler_id"],
        "decision_status": validated["decision_status"],
        "lease_acquired": validated["lease_acquired"],
        "lease_owner_id": validated["lease_owner_id"],
        "operation": validated["operation"],
        "fencing_token": validated["fencing_token"],
        "skip_reason": validated["skip_reason"],
    }


def run_artifact_retention_scheduler_tick_once(
    *,
    artifact_store: Any,
    job_queue: Any | None,
    tenant_id: str,
    workspace_id: str,
    owner_user_id: str,
    lease_store: Any | None = None,
    history_store: Any | None = None,
    scheduler_config: Mapping[str, Any] | None = None,
    lease_owner_id: str = DEFAULT_ARTIFACT_RETENTION_SCHEDULER_LEASE_OWNER_ID,
    retention_days: int | str | None = None,
    as_of: str | None = None,
    scan_limit: int | str | None = None,
    max_delete_count: int | str | None = None,
    tick_at: str | None = None,
    trace_id: str | None = None,
    request_id: str | None = None,
    idempotency_key: str | None = None,
    run_worker: bool = False,
    worker_id: str | None = None,
    clock: Callable[[], str] | None = None,
) -> dict[str, Any]:
    config = validate_artifact_retention_scheduler_config(
        dict(scheduler_config)
        if scheduler_config is not None
        else build_artifact_retention_scheduler_config(job_queue=job_queue)
    )
    run_at = _scheduler_tick_once_run_at(
        tick_at=tick_at,
        scheduler_config=config,
        clock=clock,
    )
    active_lease_store = _scheduler_tick_once_lease_store(lease_store)
    active_lease_store.ensure_available()
    lease_request = build_artifact_retention_scheduler_lease_request(
        scheduler_config=config,
        lease_owner_id=lease_owner_id,
        requested_at=run_at,
        tick_id=None,
    )
    lease_decision = active_lease_store.acquire(lease_request)
    if not lease_decision["lease_acquired"]:
        return validate_artifact_retention_scheduler_tick_once_result(
            _build_artifact_retention_scheduler_tick_once_result(
                scheduler_config=config,
                run_at=run_at,
                lease_decision=lease_decision,
                lease_release=None,
                batch_plan=None,
                tick_plan=None,
                enqueue_result=None,
                worker_result=None,
            )
        )

    lease_release: dict[str, Any] | None = None
    release_attempted = False
    try:
        if artifact_store is None or not hasattr(artifact_store, "plan_retention_batch"):
            raise ArtifactHandoffError(
                status_code=500,
                error_code="ae.artifact_retention_scheduler_artifact_store_invalid",
                detail="Artifact retention scheduler artifact store is invalid.",
            )
        batch_plan = artifact_store.plan_retention_batch(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            retention_days=retention_days,
            as_of=as_of,
            scan_limit=scan_limit,
            max_delete_count=max_delete_count,
            checked_at=run_at,
            requested_by={
                "actor_type": "service",
                "actor_id": "nex-ae-api",
                "tenant_id": tenant_id,
            },
            idempotency_key=optional_text(idempotency_key),
        )
        tick_plan = build_artifact_retention_scheduler_tick_plan(
            validate_artifact_retention_batch_plan(batch_plan),
            scheduler_config=config,
            tick_at=run_at,
            trace_id=trace_id,
            request_id=request_id,
            idempotency_key=idempotency_key,
        )
        enqueue_result = enqueue_artifact_retention_scheduler_tick_job(
            job_queue,
            tick_plan,
            trace_id=trace_id,
            request_id=request_id,
        )
        worker_result = None
        if run_worker and enqueue_result["enqueue_status"] == "ENQUEUED":
            worker_execution = run_artifact_retention_scheduled_worker_once(
                job_queue=job_queue,
                artifact_store=artifact_store,
                history_store=history_store,
                worker_id=worker_id or "ae-artifact-retention-scheduler-tick-once",
                clock=clock,
            )
            worker_result = _scheduler_tick_once_worker_summary(worker_execution)
        release_attempted = True
        lease_release = active_lease_store.release(
            scheduler_id=lease_decision["scheduler_id"],
            lease_token=lease_decision["lease_token"],
            released_at=run_at,
        )
        return validate_artifact_retention_scheduler_tick_once_result(
            _build_artifact_retention_scheduler_tick_once_result(
                scheduler_config=config,
                run_at=run_at,
                lease_decision=lease_decision,
                lease_release=lease_release,
                batch_plan=batch_plan,
                tick_plan=tick_plan,
                enqueue_result=enqueue_result,
                worker_result=worker_result,
            )
        )
    finally:
        if lease_decision["lease_acquired"] and not release_attempted:
            active_lease_store.release(
                scheduler_id=lease_decision["scheduler_id"],
                lease_token=lease_decision["lease_token"],
                released_at=run_at,
            )


def validate_artifact_retention_scheduler_tick_once_result(
    result: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_tick_once_result_invalid",
            detail="Artifact retention scheduler tick-once result must be an object.",
        )
    normalized = dict(result)
    if (
        normalized.get("tick_once_result_schema_version")
        != AE_ARTIFACT_RETENTION_SCHEDULER_TICK_ONCE_RESULT_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_tick_once_result_schema_invalid",
            detail="Artifact retention scheduler tick-once result schema version is invalid.",
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_tick_once_result_invalid",
            detail="Artifact retention scheduler tick-once result service id is invalid.",
        )
    for field_name in ("tick_once_result_id", "scheduler_id", "lease_owner_id"):
        _required_text(
            normalized.get(field_name),
            field_name,
            "ae.artifact_retention_scheduler_tick_once_result_invalid",
        )
    parse_artifact_retention_timestamp(
        normalized.get("run_at"),
        field_name="run_at",
    )
    result_status = normalized.get("result_status")
    if result_status not in ARTIFACT_RETENTION_SCHEDULER_TICK_ONCE_RESULT_STATUSES:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_tick_once_result_invalid",
            detail="Artifact retention scheduler tick-once result status is invalid.",
        )
    skip_reason = normalized.get("skip_reason")
    if skip_reason is not None and skip_reason not in (
        ARTIFACT_RETENTION_SCHEDULER_TICK_ONCE_SKIP_REASONS
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_tick_once_result_invalid",
            detail="Artifact retention scheduler tick-once skip reason is invalid.",
        )
    lease_decision = validate_artifact_retention_scheduler_lease_decision(
        normalized.get("lease_decision")
    )
    if (
        lease_decision["scheduler_id"] != normalized["scheduler_id"]
        or lease_decision["lease_owner_id"] != normalized["lease_owner_id"]
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_tick_once_result_invalid",
            detail="Artifact retention scheduler tick-once lease scope is invalid.",
        )
    lease_release = normalized.get("lease_release")
    batch_plan = normalized.get("batch_plan")
    tick_plan = normalized.get("tick_plan")
    enqueue_result = normalized.get("enqueue_result")
    worker_result = normalized.get("worker_result")
    if lease_decision["decision_status"] == "BUSY":
        if (
            result_status != "SKIPPED"
            or skip_reason != "lease_busy"
            or lease_release is not None
            or batch_plan is not None
            or tick_plan is not None
            or enqueue_result is not None
            or worker_result is not None
        ):
            raise ArtifactHandoffError(
                status_code=422,
                error_code="ae.artifact_retention_scheduler_tick_once_result_invalid",
                detail="Busy scheduler tick-once result is invalid.",
            )
    else:
        released = validate_artifact_retention_scheduler_lease_record(lease_release)
        validated_plan = validate_artifact_retention_batch_plan(batch_plan)
        validated_tick = validate_artifact_retention_scheduler_tick_plan(tick_plan)
        validated_enqueue = validate_artifact_retention_scheduler_tick_enqueue_result(
            enqueue_result
        )
        if (
            released["lease_status"] != "RELEASED"
            or released["lease_token"] != lease_decision["lease_token"]
            or validated_tick["source_plan_id"] != validated_plan["plan_id"]
            or validated_enqueue["tick_id"] != validated_tick["tick_id"]
        ):
            raise ArtifactHandoffError(
                status_code=422,
                error_code="ae.artifact_retention_scheduler_tick_once_result_invalid",
                detail="Acquired scheduler tick-once result lineage is invalid.",
            )
        expected_status = _scheduler_tick_once_result_status(
            tick_plan=validated_tick,
            enqueue_result=validated_enqueue,
            worker_result=worker_result,
        )
        expected_skip_reason = _scheduler_tick_once_skip_reason(validated_tick)
        if result_status != expected_status or skip_reason != expected_skip_reason:
            raise ArtifactHandoffError(
                status_code=422,
                error_code="ae.artifact_retention_scheduler_tick_once_result_invalid",
                detail="Acquired scheduler tick-once result status is invalid.",
            )
        if worker_result is not None and not isinstance(worker_result, Mapping):
            raise ArtifactHandoffError(
                status_code=422,
                error_code="ae.artifact_retention_scheduler_tick_once_result_invalid",
                detail="Artifact retention scheduler tick-once worker result is invalid.",
            )
    if normalized.get("metadata") != _scheduler_tick_once_metadata(
        lease_decision=lease_decision,
        lease_release=lease_release,
        enqueue_result=enqueue_result,
        worker_result=worker_result,
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_tick_once_result_invalid",
            detail="Artifact retention scheduler tick-once metadata is invalid.",
        )
    if normalized.get("guardrails") != _scheduler_tick_once_guardrails(
        lease_released=lease_release is not None
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_tick_once_result_invalid",
            detail="Artifact retention scheduler tick-once guardrails are invalid.",
        )
    assert_artifact_retention_payload_safe(normalized)
    return normalized


def summarize_artifact_retention_scheduler_tick_once_result(
    result: Mapping[str, Any],
) -> dict[str, Any]:
    validated = validate_artifact_retention_scheduler_tick_once_result(result)
    return {
        "scheduler_id": validated["scheduler_id"],
        "result_status": validated["result_status"],
        "skip_reason": validated["skip_reason"],
        "lease_acquired": validated["lease_decision"]["lease_acquired"],
        "lease_released": validated["metadata"]["lease_released"],
        "job_enqueued": validated["metadata"]["job_enqueued"],
        "worker_executed": validated["metadata"]["worker_executed"],
    }


def build_artifact_retention_scheduler_daemon_config(
    *,
    scheduler_config: Mapping[str, Any] | None = None,
    lease_store: Any | None = None,
    checked_at: str | None = None,
) -> dict[str, Any]:
    config = validate_artifact_retention_scheduler_config(
        dict(scheduler_config)
        if scheduler_config is not None
        else build_artifact_retention_scheduler_config()
    )
    runtime = _scheduler_daemon_runtime_config(config["runtime"])
    lease_repository = _scheduler_daemon_lease_repository_summary(lease_store)
    daemon_config = {
        "daemon_config_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONFIG_SCHEMA_VERSION
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": config["scheduler_id"],
        "checked_at": _scheduler_daemon_checked_at(
            checked_at=checked_at,
            scheduler_config=config,
        ),
        "source_scheduler_config_schema_version": config[
            "artifact_retention_scheduler_config_schema_version"
        ],
        "runtime": runtime,
        "lease_repository": lease_repository,
        "supported_actions": _scheduler_daemon_supported_actions(
            runtime=runtime,
            lease_repository=lease_repository,
        ),
        "guardrails": _scheduler_daemon_guardrails(),
        "metadata": _scheduler_daemon_metadata(),
    }
    return validate_artifact_retention_scheduler_daemon_config(daemon_config)


def validate_artifact_retention_scheduler_daemon_config(
    config: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(config, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_config_invalid",
            detail="Artifact retention scheduler daemon config must be an object.",
        )
    normalized = dict(config)
    if (
        normalized.get("daemon_config_schema_version")
        != AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONFIG_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_config_schema_invalid",
            detail="Artifact retention scheduler daemon config schema version is invalid.",
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_config_invalid",
            detail="Artifact retention scheduler daemon config service id is invalid.",
        )
    _required_text(
        normalized.get("scheduler_id"),
        "scheduler_id",
        "ae.artifact_retention_scheduler_daemon_config_invalid",
    )
    parse_artifact_retention_timestamp(
        normalized.get("checked_at"),
        field_name="checked_at",
    )
    if normalized.get("source_scheduler_config_schema_version") != (
        "ae_artifact_retention_scheduler_config.v1"
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_config_invalid",
            detail="Artifact retention scheduler daemon source config is invalid.",
        )
    runtime = _validate_scheduler_daemon_runtime_config(normalized.get("runtime"))
    lease_repository = _validate_scheduler_daemon_lease_repository(
        normalized.get("lease_repository")
    )
    expected_actions = _scheduler_daemon_supported_actions(
        runtime=runtime,
        lease_repository=lease_repository,
    )
    if normalized.get("supported_actions") != expected_actions:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_config_invalid",
            detail="Artifact retention scheduler daemon supported actions are invalid.",
        )
    if normalized.get("guardrails") != _scheduler_daemon_guardrails():
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_config_invalid",
            detail="Artifact retention scheduler daemon guardrails are invalid.",
        )
    if normalized.get("metadata") != _scheduler_daemon_metadata():
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_config_invalid",
            detail="Artifact retention scheduler daemon metadata is invalid.",
        )
    assert_artifact_retention_payload_safe(normalized)
    return normalized


def summarize_artifact_retention_scheduler_daemon_config(
    config: Mapping[str, Any],
) -> dict[str, Any]:
    validated = validate_artifact_retention_scheduler_daemon_config(config)
    manual_action = _scheduler_daemon_action_item(
        validated,
        ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONTROL_ACTION_MANUAL_TICK_ONCE,
    )
    return {
        "scheduler_id": validated["scheduler_id"],
        "scheduler_daemon_enabled": validated["runtime"]["scheduler_daemon_enabled"],
        "scheduler_daemon_started": validated["runtime"]["scheduler_daemon_started"],
        "manual_tick_once_decision_status": manual_action["decision_status"],
        "manual_tick_once_block_reason": manual_action["block_reason"],
        "lease_repository_available": validated["lease_repository"]["available"],
        "job_queue_available": validated["runtime"]["job_queue_available"],
    }


def build_artifact_retention_scheduler_daemon_runtime_observation(
    *,
    scheduler_config: Mapping[str, Any] | None = None,
    daemon_config: Mapping[str, Any] | None = None,
    worker_heartbeat_store: Any | None = None,
    checked_at: str | None = None,
) -> dict[str, Any]:
    config = validate_artifact_retention_scheduler_config(
        dict(scheduler_config)
        if scheduler_config is not None
        else build_artifact_retention_scheduler_config()
    )
    daemon = validate_artifact_retention_scheduler_daemon_config(
        dict(daemon_config)
        if daemon_config is not None
        else build_artifact_retention_scheduler_daemon_config(
            scheduler_config=config,
        )
    )
    checked = _scheduler_daemon_checked_at(
        checked_at=checked_at,
        scheduler_config=config,
    )
    heartbeat_store, heartbeats = _scheduler_daemon_heartbeat_store_observation(
        worker_heartbeat_store
    )
    latest_heartbeat = _latest_scheduler_daemon_heartbeat(heartbeats)
    observation = {
        "runtime_observation_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUNTIME_OBSERVATION_SCHEMA_VERSION
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": daemon["scheduler_id"],
        "checked_at": checked,
        "worker_type": AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_WORKER_TYPE,
        "heartbeat_store": heartbeat_store,
        "heartbeat": _project_scheduler_daemon_runtime_heartbeat(latest_heartbeat),
        "heartbeat_count": len(heartbeats),
        "daemon_config_checked_at": daemon["checked_at"],
        "guardrails": {
            "metadata_only": True,
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
            "scheduler_daemon_started": False,
            "continuous_loop_started": False,
            "physical_delete_automation_enabled": False,
            "heartbeat_observation_read_only": True,
        },
        "metadata": {
            "metadata_only": True,
            "heartbeat_observed": latest_heartbeat is not None,
            "heartbeat_store_available": heartbeat_store["available"] is True,
            "database_url_included": False,
            "storage_path_included": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_included": False,
            "scheduler_daemon_started": False,
            "continuous_loop_started": False,
            "physical_delete_automation_enabled": False,
        },
    }
    assert_artifact_retention_payload_safe(observation)
    return observation


def build_artifact_retention_scheduler_daemon_runtime_config(
    *,
    scheduler_config: Mapping[str, Any] | None = None,
    profile: str = "test",
    enabled: bool = False,
    explicit_opt_in: bool = False,
    checked_at: str | None = None,
    interval_seconds: int | str | None = None,
    jitter_seconds: int | str | None = None,
    max_ticks_per_run: int | str | None = None,
    lease_ttl_seconds: int | str | None = None,
    backoff_seconds: int | str | None = None,
) -> dict[str, Any]:
    config = validate_artifact_retention_scheduler_config(
        dict(scheduler_config)
        if scheduler_config is not None
        else build_artifact_retention_scheduler_config()
    )
    runtime = dict(config["runtime"])
    schedule = dict(config["schedule"])
    normalized_profile = _normalize_scheduler_daemon_runtime_profile(profile)
    normalized_enabled = _required_bool(
        enabled,
        "enabled",
        "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
    )
    normalized_explicit_opt_in = _required_bool(
        explicit_opt_in,
        "explicit_opt_in",
        "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
    )
    normalized_interval = _bounded_positive_int(
        interval_seconds
        if interval_seconds is not None
        else runtime["scheduler_tick_interval_seconds"],
        "interval_seconds",
        "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
        max_value=MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_INTERVAL_SECONDS,
    )
    normalized_jitter = _non_negative_int(
        jitter_seconds
        if jitter_seconds is not None
        else runtime["scheduler_tick_jitter_seconds"],
        "jitter_seconds",
        "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
    )
    if normalized_jitter > normalized_interval:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            detail="Artifact retention scheduler daemon jitter cannot exceed interval.",
        )
    normalized_max_ticks = _bounded_positive_int(
        max_ticks_per_run
        if max_ticks_per_run is not None
        else DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_MAX_TICKS_PER_RUN,
        "max_ticks_per_run",
        "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
        max_value=MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_MAX_TICKS_PER_RUN,
    )
    normalized_lease_ttl = normalize_artifact_retention_scheduler_lease_ttl_seconds(
        lease_ttl_seconds
    )
    normalized_backoff = _bounded_positive_int(
        backoff_seconds
        if backoff_seconds is not None
        else DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_BACKOFF_SECONDS,
        "backoff_seconds",
        "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
        max_value=MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_BACKOFF_SECONDS,
    )
    enablement_status, block_reason = _scheduler_daemon_runtime_enablement_status(
        enabled=normalized_enabled,
        explicit_opt_in=normalized_explicit_opt_in,
    )
    runtime_config = {
        "daemon_runtime_config_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUNTIME_CONFIG_SCHEMA_VERSION
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": config["scheduler_id"],
        "checked_at": _scheduler_daemon_checked_at(
            checked_at=checked_at,
            scheduler_config=config,
        ),
        "source_scheduler_config_schema_version": config[
            "artifact_retention_scheduler_config_schema_version"
        ],
        "enablement": {
            "profile": normalized_profile,
            "enabled": normalized_enabled,
            "explicit_opt_in": normalized_explicit_opt_in,
            "enablement_status": enablement_status,
            "block_reason": block_reason,
        },
        "timing": {
            "interval_seconds": normalized_interval,
            "jitter_seconds": normalized_jitter,
            "backoff_seconds": normalized_backoff,
        },
        "runtime": {
            "scheduler_tick_admission_enabled": (
                runtime.get("scheduler_tick_admission_enabled") is True
            ),
            "operator_dispatch_admission_enabled": (
                runtime.get("operator_dispatch_admission_enabled") is True
            ),
            "default_execution_mode": runtime.get("default_execution_mode"),
            "job_queue_available": runtime.get("job_queue_available") is True,
            "job_queue_backend": runtime.get("job_queue_backend"),
            "worker_runner_available": runtime.get("worker_runner_available") is True,
            "physical_delete_automation_enabled": (
                runtime.get("physical_delete_automation_enabled") is True
            ),
        },
        "loop_policy": {
            "one_cycle_runner_required_before_loop": True,
            "max_ticks_per_run": normalized_max_ticks,
            "daemon_auto_start_allowed": False,
            "scheduler_daemon_started": False,
            "continuous_loop_enabled": False,
            "continuous_loop_started": False,
            "start_control_enabled": False,
            "stop_control_enabled": False,
        },
        "lease_policy": {
            "lease_required_before_tick": True,
            "fencing_token_required": True,
            "lease_repository_required": True,
            "lease_ttl_seconds": normalized_lease_ttl,
            "stale_after_seconds": runtime.get("scheduler_tick_stale_after_seconds"),
        },
        "batch_window": deepcopy(schedule["batch_window"]),
        "guardrails": _scheduler_daemon_runtime_config_guardrails(),
        "metadata": _scheduler_daemon_runtime_config_metadata(),
    }
    return validate_artifact_retention_scheduler_daemon_runtime_config(runtime_config)


def validate_artifact_retention_scheduler_daemon_runtime_config(
    config: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(config, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            detail="Artifact retention scheduler daemon runtime config must be an object.",
        )
    normalized = dict(config)
    if set(normalized) != {
        "daemon_runtime_config_schema_version",
        "service_id",
        "scheduler_id",
        "checked_at",
        "source_scheduler_config_schema_version",
        "enablement",
        "timing",
        "runtime",
        "loop_policy",
        "lease_policy",
        "batch_window",
        "guardrails",
        "metadata",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            detail="Artifact retention scheduler daemon runtime config keys are invalid.",
        )
    if (
        normalized.get("daemon_runtime_config_schema_version")
        != AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUNTIME_CONFIG_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_runtime_config_schema_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon runtime config schema version "
                "is invalid."
            ),
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            detail="Artifact retention scheduler daemon runtime config service id is invalid.",
        )
    _required_text(
        normalized.get("scheduler_id"),
        "scheduler_id",
        "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
    )
    normalized["checked_at"] = format_artifact_retention_timestamp(
        parse_artifact_retention_timestamp(
            normalized.get("checked_at"),
            field_name="checked_at",
        )
    )
    if normalized.get("source_scheduler_config_schema_version") != (
        "ae_artifact_retention_scheduler_config.v1"
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            detail="Artifact retention scheduler daemon runtime source config is invalid.",
        )
    enablement = _validate_scheduler_daemon_runtime_enablement(
        normalized.get("enablement")
    )
    timing = _validate_scheduler_daemon_runtime_timing(normalized.get("timing"))
    runtime = _validate_scheduler_daemon_runtime_enablement_runtime(
        normalized.get("runtime")
    )
    loop_policy = _validate_scheduler_daemon_runtime_loop_policy(
        normalized.get("loop_policy")
    )
    lease_policy = _validate_scheduler_daemon_runtime_lease_policy(
        normalized.get("lease_policy")
    )
    batch_window = _validate_scheduler_daemon_runtime_batch_window(
        normalized.get("batch_window")
    )
    if normalized.get("guardrails") != _scheduler_daemon_runtime_config_guardrails():
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            detail="Artifact retention scheduler daemon runtime guardrails are invalid.",
        )
    if normalized.get("metadata") != _scheduler_daemon_runtime_config_metadata():
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            detail="Artifact retention scheduler daemon runtime metadata is invalid.",
        )
    normalized["enablement"] = enablement
    normalized["timing"] = timing
    normalized["runtime"] = runtime
    normalized["loop_policy"] = loop_policy
    normalized["lease_policy"] = lease_policy
    normalized["batch_window"] = batch_window
    assert_artifact_retention_payload_safe(normalized)
    return normalized


def summarize_artifact_retention_scheduler_daemon_runtime_config(
    config: Mapping[str, Any],
) -> dict[str, Any]:
    validated = validate_artifact_retention_scheduler_daemon_runtime_config(config)
    return {
        "scheduler_id": validated["scheduler_id"],
        "profile": validated["enablement"]["profile"],
        "enabled": validated["enablement"]["enabled"],
        "explicit_opt_in": validated["enablement"]["explicit_opt_in"],
        "enablement_status": validated["enablement"]["enablement_status"],
        "block_reason": validated["enablement"]["block_reason"],
        "interval_seconds": validated["timing"]["interval_seconds"],
        "jitter_seconds": validated["timing"]["jitter_seconds"],
        "max_ticks_per_run": validated["loop_policy"]["max_ticks_per_run"],
        "lease_ttl_seconds": validated["lease_policy"]["lease_ttl_seconds"],
        "job_queue_available": validated["runtime"]["job_queue_available"],
        "scheduler_daemon_started": validated["loop_policy"][
            "scheduler_daemon_started"
        ],
        "continuous_loop_started": validated["loop_policy"][
            "continuous_loop_started"
        ],
        "physical_delete_automation_enabled": validated["runtime"][
            "physical_delete_automation_enabled"
        ],
    }


def build_artifact_retention_scheduler_daemon_loop_plan(
    *,
    scheduler_config: Mapping[str, Any] | None = None,
    runtime_config: Mapping[str, Any] | None = None,
    daemon_config: Mapping[str, Any] | None = None,
    lease_store: Any | None = None,
    job_queue: Any | None = None,
    requested_at: str | None = None,
    stop_requested: bool = False,
) -> dict[str, Any]:
    config = validate_artifact_retention_scheduler_config(
        dict(scheduler_config)
        if scheduler_config is not None
        else build_artifact_retention_scheduler_config(job_queue=job_queue)
    )
    normalized_runtime = validate_artifact_retention_scheduler_daemon_runtime_config(
        dict(runtime_config)
        if runtime_config is not None
        else build_artifact_retention_scheduler_daemon_runtime_config(
            scheduler_config=config,
            checked_at=requested_at,
        )
    )
    normalized_daemon = validate_artifact_retention_scheduler_daemon_config(
        dict(daemon_config)
        if daemon_config is not None
        else build_artifact_retention_scheduler_daemon_config(
            scheduler_config=config,
            lease_store=lease_store,
            checked_at=requested_at,
        )
    )
    _ensure_scheduler_daemon_runtime_scope(
        runtime_config=normalized_runtime,
        daemon_config=normalized_daemon,
    )
    requested = _scheduler_daemon_checked_at(
        checked_at=requested_at,
        scheduler_config=normalized_runtime,
    )
    normalized_stop_requested = _required_bool(
        stop_requested,
        "stop_requested",
        "ae.artifact_retention_scheduler_daemon_loop_plan_invalid",
    )
    in_batch_window = _scheduler_daemon_runtime_in_batch_window(
        requested_at=requested,
        runtime_config=normalized_runtime,
    )
    decision_status, decision_reason = _scheduler_daemon_loop_plan_decision(
        runtime_config=normalized_runtime,
        daemon_config=normalized_daemon,
        in_batch_window=in_batch_window,
        stop_requested=normalized_stop_requested,
    )
    execution_plan = _scheduler_daemon_loop_execution_plan(
        runtime_config=normalized_runtime,
        decision_status=decision_status,
        in_batch_window=in_batch_window,
    )
    loop_plan = {
        "daemon_loop_plan_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_LOOP_PLAN_SCHEMA_VERSION
        ),
        "daemon_loop_plan_id": _scheduler_daemon_loop_plan_id(
            scheduler_id=normalized_runtime["scheduler_id"],
            requested_at=requested,
            decision_status=decision_status,
            decision_reason=decision_reason,
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": normalized_runtime["scheduler_id"],
        "requested_at": requested,
        "stop_requested": normalized_stop_requested,
        "decision_status": decision_status,
        "decision_reason": decision_reason,
        "runtime_config": deepcopy(normalized_runtime),
        "daemon_config": deepcopy(normalized_daemon),
        "execution_plan": execution_plan,
        "guardrails": _scheduler_daemon_loop_plan_guardrails(),
        "metadata": _scheduler_daemon_loop_plan_metadata(
            decision_status=decision_status,
            decision_reason=decision_reason,
        ),
    }
    return validate_artifact_retention_scheduler_daemon_loop_plan(loop_plan)


def validate_artifact_retention_scheduler_daemon_loop_plan(
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(plan, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_loop_plan_invalid",
            detail="Artifact retention scheduler daemon loop plan must be an object.",
        )
    normalized = dict(plan)
    if set(normalized) != {
        "daemon_loop_plan_schema_version",
        "daemon_loop_plan_id",
        "service_id",
        "scheduler_id",
        "requested_at",
        "stop_requested",
        "decision_status",
        "decision_reason",
        "runtime_config",
        "daemon_config",
        "execution_plan",
        "guardrails",
        "metadata",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_loop_plan_invalid",
            detail="Artifact retention scheduler daemon loop plan keys are invalid.",
        )
    if (
        normalized.get("daemon_loop_plan_schema_version")
        != AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_LOOP_PLAN_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_loop_plan_schema_invalid",
            detail="Artifact retention scheduler daemon loop plan schema version is invalid.",
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_loop_plan_invalid",
            detail="Artifact retention scheduler daemon loop plan service id is invalid.",
        )
    _required_text(
        normalized.get("daemon_loop_plan_id"),
        "daemon_loop_plan_id",
        "ae.artifact_retention_scheduler_daemon_loop_plan_invalid",
    )
    _required_text(
        normalized.get("scheduler_id"),
        "scheduler_id",
        "ae.artifact_retention_scheduler_daemon_loop_plan_invalid",
    )
    requested_at = format_artifact_retention_timestamp(
        parse_artifact_retention_timestamp(
            normalized.get("requested_at"),
            field_name="requested_at",
        )
    )
    stop_requested = _required_bool(
        normalized.get("stop_requested"),
        "stop_requested",
        "ae.artifact_retention_scheduler_daemon_loop_plan_invalid",
    )
    runtime_config = validate_artifact_retention_scheduler_daemon_runtime_config(
        normalized.get("runtime_config")
    )
    daemon_config = validate_artifact_retention_scheduler_daemon_config(
        normalized.get("daemon_config")
    )
    _ensure_scheduler_daemon_runtime_scope(
        runtime_config=runtime_config,
        daemon_config=daemon_config,
    )
    if runtime_config["scheduler_id"] != normalized["scheduler_id"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_loop_plan_invalid",
            detail="Artifact retention scheduler daemon loop plan scope is invalid.",
        )
    in_batch_window = _scheduler_daemon_runtime_in_batch_window(
        requested_at=requested_at,
        runtime_config=runtime_config,
    )
    expected_status, expected_reason = _scheduler_daemon_loop_plan_decision(
        runtime_config=runtime_config,
        daemon_config=daemon_config,
        in_batch_window=in_batch_window,
        stop_requested=stop_requested,
    )
    if normalized.get("decision_status") != expected_status:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_loop_plan_invalid",
            detail="Artifact retention scheduler daemon loop plan decision is invalid.",
        )
    if normalized.get("decision_reason") != expected_reason:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_loop_plan_invalid",
            detail="Artifact retention scheduler daemon loop plan decision reason is invalid.",
        )
    expected_id = _scheduler_daemon_loop_plan_id(
        scheduler_id=runtime_config["scheduler_id"],
        requested_at=requested_at,
        decision_status=expected_status,
        decision_reason=expected_reason,
    )
    if normalized["daemon_loop_plan_id"] != expected_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_loop_plan_invalid",
            detail="Artifact retention scheduler daemon loop plan id is invalid.",
        )
    expected_execution_plan = _scheduler_daemon_loop_execution_plan(
        runtime_config=runtime_config,
        decision_status=expected_status,
        in_batch_window=in_batch_window,
    )
    if normalized.get("execution_plan") != expected_execution_plan:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_loop_plan_invalid",
            detail="Artifact retention scheduler daemon loop execution plan is invalid.",
        )
    if normalized.get("guardrails") != _scheduler_daemon_loop_plan_guardrails():
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_loop_plan_invalid",
            detail="Artifact retention scheduler daemon loop guardrails are invalid.",
        )
    if normalized.get("metadata") != _scheduler_daemon_loop_plan_metadata(
        decision_status=expected_status,
        decision_reason=expected_reason,
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_loop_plan_invalid",
            detail="Artifact retention scheduler daemon loop metadata is invalid.",
        )
    normalized["requested_at"] = requested_at
    normalized["stop_requested"] = stop_requested
    normalized["runtime_config"] = runtime_config
    normalized["daemon_config"] = daemon_config
    normalized["execution_plan"] = expected_execution_plan
    assert_artifact_retention_payload_safe(normalized)
    return normalized


def summarize_artifact_retention_scheduler_daemon_loop_plan(
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    validated = validate_artifact_retention_scheduler_daemon_loop_plan(plan)
    return {
        "scheduler_id": validated["scheduler_id"],
        "decision_status": validated["decision_status"],
        "decision_reason": validated["decision_reason"],
        "runs_tick_once": validated["execution_plan"]["runs_tick_once"],
        "in_batch_window": validated["execution_plan"]["in_batch_window"],
        "lease_repository_available": validated["daemon_config"][
            "lease_repository"
        ]["available"],
        "job_queue_available": validated["runtime_config"]["runtime"][
            "job_queue_available"
        ],
        "scheduler_daemon_started": validated["metadata"][
            "scheduler_daemon_started"
        ],
        "continuous_loop_started": validated["metadata"][
            "continuous_loop_started"
        ],
    }


def run_artifact_retention_scheduler_daemon_one_cycle(
    *,
    artifact_store: Any,
    job_queue: Any | None,
    tenant_id: str,
    workspace_id: str,
    owner_user_id: str,
    lease_store: Any | None = None,
    history_store: Any | None = None,
    scheduler_config: Mapping[str, Any] | None = None,
    runtime_config: Mapping[str, Any] | None = None,
    daemon_config: Mapping[str, Any] | None = None,
    lease_owner_id: str = (
        DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ONE_CYCLE_LEASE_OWNER_ID
    ),
    retention_days: int | str | None = None,
    as_of: str | None = None,
    scan_limit: int | str | None = None,
    max_delete_count: int | str | None = None,
    requested_at: str | None = None,
    tick_at: str | None = None,
    trace_id: str | None = None,
    request_id: str | None = None,
    idempotency_key: str | None = None,
    run_worker: bool = False,
    worker_id: str | None = None,
    stop_requested: bool = False,
    clock: Callable[[], str] | None = None,
    daemon_heartbeat_emitter: Any | None = None,
) -> dict[str, Any]:
    config = validate_artifact_retention_scheduler_config(
        dict(scheduler_config)
        if scheduler_config is not None
        else build_artifact_retention_scheduler_config(job_queue=job_queue)
    )
    observed_at = tick_at or requested_at or (clock() if clock is not None else None)
    loop_plan = build_artifact_retention_scheduler_daemon_loop_plan(
        scheduler_config=config,
        runtime_config=runtime_config,
        daemon_config=daemon_config,
        lease_store=lease_store,
        job_queue=job_queue,
        requested_at=observed_at,
        stop_requested=stop_requested,
    )
    daemon_heartbeat_results: list[dict[str, Any]] = []
    _append_scheduler_daemon_heartbeat_result(
        daemon_heartbeat_results,
        _emit_scheduler_daemon_heartbeat(
            daemon_heartbeat_emitter,
            status="STARTING",
            trace_id=trace_id,
            observed_at=loop_plan["requested_at"],
            metadata=_scheduler_daemon_heartbeat_metadata(
                loop_plan=loop_plan,
                phase="loop_plan_built",
            ),
        ),
    )
    tick_once_result = None
    try:
        if loop_plan["execution_plan"]["runs_tick_once"] is True:
            _append_scheduler_daemon_heartbeat_result(
                daemon_heartbeat_results,
                _emit_scheduler_daemon_heartbeat(
                    daemon_heartbeat_emitter,
                    status="BUSY",
                    active_job_id=loop_plan["daemon_loop_plan_id"],
                    trace_id=trace_id,
                    observed_at=loop_plan["requested_at"],
                    metadata=_scheduler_daemon_heartbeat_metadata(
                        loop_plan=loop_plan,
                        phase="tick_once_running",
                    ),
                ),
            )
            tick_once_result = run_artifact_retention_scheduler_tick_once(
                artifact_store=artifact_store,
                job_queue=job_queue,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                owner_user_id=owner_user_id,
                lease_store=lease_store,
                history_store=history_store,
                scheduler_config=config,
                lease_owner_id=lease_owner_id,
                retention_days=retention_days,
                as_of=as_of,
                scan_limit=scan_limit,
                max_delete_count=max_delete_count,
                tick_at=loop_plan["requested_at"],
                trace_id=trace_id,
                request_id=request_id,
                idempotency_key=idempotency_key,
                run_worker=run_worker,
                worker_id=worker_id,
                clock=clock,
            )
    except Exception:
        _append_scheduler_daemon_heartbeat_result(
            daemon_heartbeat_results,
            _emit_scheduler_daemon_heartbeat(
                daemon_heartbeat_emitter,
                status="ERROR",
                active_job_id=loop_plan["daemon_loop_plan_id"],
                trace_id=trace_id,
                observed_at=loop_plan["requested_at"],
                metadata=_scheduler_daemon_heartbeat_metadata(
                    loop_plan=loop_plan,
                    phase="tick_once_failed",
                    tick_once_result=tick_once_result,
                ),
            ),
        )
        raise
    final_status = _scheduler_daemon_one_cycle_heartbeat_final_status(
        loop_plan=loop_plan,
        tick_once_result=tick_once_result,
    )
    _append_scheduler_daemon_heartbeat_result(
        daemon_heartbeat_results,
        _emit_scheduler_daemon_heartbeat(
            daemon_heartbeat_emitter,
            status=final_status,
            trace_id=trace_id,
            observed_at=loop_plan["requested_at"],
            metadata=_scheduler_daemon_heartbeat_metadata(
                loop_plan=loop_plan,
                phase="one_cycle_finished",
                tick_once_result=tick_once_result,
            ),
        ),
    )
    return validate_artifact_retention_scheduler_daemon_one_cycle_result(
        _build_artifact_retention_scheduler_daemon_one_cycle_result(
            loop_plan=loop_plan,
            tick_once_result=tick_once_result,
            daemon_heartbeat_results=daemon_heartbeat_results,
        )
    )


def validate_artifact_retention_scheduler_daemon_one_cycle_result(
    result: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_one_cycle_result_invalid",
            detail="Artifact retention scheduler daemon one-cycle result must be an object.",
        )
    normalized = dict(result)
    if set(normalized) != {
        "daemon_one_cycle_result_schema_version",
        "daemon_one_cycle_result_id",
        "service_id",
        "scheduler_id",
        "run_at",
        "result_status",
        "skip_reason",
        "loop_plan",
        "tick_once_result",
        "daemon_heartbeat_results",
        "execution_plan",
        "guardrails",
        "metadata",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_one_cycle_result_invalid",
            detail="Artifact retention scheduler daemon one-cycle result keys are invalid.",
        )
    if (
        normalized.get("daemon_one_cycle_result_schema_version")
        != AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ONE_CYCLE_RESULT_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_one_cycle_result_schema_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon one-cycle result schema version "
                "is invalid."
            ),
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_one_cycle_result_invalid",
            detail="Artifact retention scheduler daemon one-cycle result service id is invalid.",
        )
    for field_name in ("daemon_one_cycle_result_id", "scheduler_id"):
        _required_text(
            normalized.get(field_name),
            field_name,
            "ae.artifact_retention_scheduler_daemon_one_cycle_result_invalid",
        )
    run_at = format_artifact_retention_timestamp(
        parse_artifact_retention_timestamp(
            normalized.get("run_at"),
            field_name="run_at",
        )
    )
    result_status = normalized.get("result_status")
    if result_status not in ARTIFACT_RETENTION_SCHEDULER_DAEMON_ONE_CYCLE_RESULT_STATUSES:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_one_cycle_result_invalid",
            detail="Artifact retention scheduler daemon one-cycle result status is invalid.",
        )
    loop_plan = validate_artifact_retention_scheduler_daemon_loop_plan(
        normalized.get("loop_plan")
    )
    if loop_plan["scheduler_id"] != normalized["scheduler_id"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_one_cycle_result_invalid",
            detail="Artifact retention scheduler daemon one-cycle result scope is invalid.",
        )
    if loop_plan["requested_at"] != run_at:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_one_cycle_result_invalid",
            detail="Artifact retention scheduler daemon one-cycle run time is invalid.",
        )
    tick_once_result = normalized.get("tick_once_result")
    if loop_plan["execution_plan"]["runs_tick_once"] is True:
        tick_once_result = validate_artifact_retention_scheduler_tick_once_result(
            tick_once_result
        )
        if tick_once_result["scheduler_id"] != normalized["scheduler_id"]:
            raise ArtifactHandoffError(
                status_code=422,
                error_code=(
                    "ae.artifact_retention_scheduler_daemon_one_cycle_result_invalid"
                ),
                detail=(
                    "Artifact retention scheduler daemon one-cycle tick scope is invalid."
                ),
            )
    elif tick_once_result is not None:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_one_cycle_result_invalid",
            detail="Blocked scheduler daemon one-cycle result cannot include a tick.",
        )
    expected_status = _scheduler_daemon_one_cycle_result_status(
        loop_plan=loop_plan,
        tick_once_result=tick_once_result,
    )
    expected_skip_reason = _scheduler_daemon_one_cycle_skip_reason(
        loop_plan=loop_plan,
        tick_once_result=tick_once_result,
    )
    daemon_heartbeat_results = _validate_scheduler_daemon_heartbeat_results(
        normalized.get("daemon_heartbeat_results")
    )
    if result_status != expected_status:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_one_cycle_result_invalid",
            detail="Artifact retention scheduler daemon one-cycle status is invalid.",
        )
    if normalized.get("skip_reason") != expected_skip_reason:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_one_cycle_result_invalid",
            detail="Artifact retention scheduler daemon one-cycle skip reason is invalid.",
        )
    expected_id = _scheduler_daemon_one_cycle_result_id(
        loop_plan=loop_plan,
        tick_once_result=tick_once_result,
        result_status=expected_status,
        skip_reason=expected_skip_reason,
    )
    if normalized["daemon_one_cycle_result_id"] != expected_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_one_cycle_result_invalid",
            detail="Artifact retention scheduler daemon one-cycle result id is invalid.",
        )
    if normalized.get("execution_plan") != loop_plan["execution_plan"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_one_cycle_result_invalid",
            detail="Artifact retention scheduler daemon one-cycle execution plan is invalid.",
        )
    if normalized.get("guardrails") != _scheduler_daemon_one_cycle_guardrails():
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_one_cycle_result_invalid",
            detail="Artifact retention scheduler daemon one-cycle guardrails are invalid.",
        )
    if normalized.get("metadata") != _scheduler_daemon_one_cycle_metadata(
        loop_plan=loop_plan,
        tick_once_result=tick_once_result,
        daemon_heartbeat_results=daemon_heartbeat_results,
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_one_cycle_result_invalid",
            detail="Artifact retention scheduler daemon one-cycle metadata is invalid.",
        )
    normalized["run_at"] = run_at
    normalized["loop_plan"] = loop_plan
    normalized["tick_once_result"] = tick_once_result
    normalized["daemon_heartbeat_results"] = daemon_heartbeat_results
    assert_artifact_retention_payload_safe(normalized)
    return normalized


def summarize_artifact_retention_scheduler_daemon_one_cycle_result(
    result: Mapping[str, Any],
) -> dict[str, Any]:
    validated = validate_artifact_retention_scheduler_daemon_one_cycle_result(result)
    return {
        "scheduler_id": validated["scheduler_id"],
        "result_status": validated["result_status"],
        "skip_reason": validated["skip_reason"],
        "loop_decision_status": validated["loop_plan"]["decision_status"],
        "loop_decision_reason": validated["loop_plan"]["decision_reason"],
        "tick_once_ran": validated["metadata"]["tick_once_ran"],
        "daemon_heartbeat_emitted": validated["metadata"][
            "daemon_heartbeat_emitted"
        ],
        "daemon_heartbeat_error_observed": validated["metadata"][
            "daemon_heartbeat_error_observed"
        ],
        "job_enqueued": validated["metadata"]["job_enqueued"],
        "lease_released": validated["metadata"]["lease_released"],
        "scheduler_daemon_started": validated["metadata"][
            "scheduler_daemon_started"
        ],
        "continuous_loop_started": validated["metadata"][
            "continuous_loop_started"
        ],
    }


def build_artifact_retention_scheduler_daemon_runtime_state(
    *,
    scheduler_config: Mapping[str, Any] | None = None,
    runtime_config: Mapping[str, Any] | None = None,
    daemon_config: Mapping[str, Any] | None = None,
    daemon_instance_id: str | None = None,
    lifecycle_status: str = "STOPPED",
    lifecycle_reason: str | None = "initialized",
    observed_at: str | None = None,
    stop_requested: bool = False,
    shutdown_requested_at: str | None = None,
    last_cycle_result: Mapping[str, Any] | None = None,
    next_tick_at: str | None = None,
    cycle_count: int | str = 0,
    consecutive_failure_count: int | str = 0,
    heartbeat_worker_id: str | None = None,
) -> dict[str, Any]:
    config = validate_artifact_retention_scheduler_config(
        dict(scheduler_config)
        if scheduler_config is not None
        else build_artifact_retention_scheduler_config()
    )
    runtime = validate_artifact_retention_scheduler_daemon_runtime_config(
        dict(runtime_config)
        if runtime_config is not None
        else build_artifact_retention_scheduler_daemon_runtime_config(
            scheduler_config=config
        )
    )
    daemon = validate_artifact_retention_scheduler_daemon_config(
        dict(daemon_config)
        if daemon_config is not None
        else build_artifact_retention_scheduler_daemon_config(
            scheduler_config=config
        )
    )
    _ensure_scheduler_daemon_runtime_scope(
        runtime_config=runtime,
        daemon_config=daemon,
    )
    observed = _scheduler_daemon_checked_at(
        checked_at=observed_at,
        scheduler_config=config,
    )
    status = _normalize_scheduler_daemon_runtime_state_status(lifecycle_status)
    reason = _normalize_scheduler_daemon_runtime_state_reason(
        lifecycle_reason,
        lifecycle_status=status,
        runtime_config=runtime,
        consecutive_failure_count=consecutive_failure_count,
    )
    normalized_stop_requested = _required_bool(
        stop_requested,
        "stop_requested",
        "ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
    )
    shutdown_at = _optional_artifact_retention_timestamp(
        shutdown_requested_at,
        field_name="shutdown_requested_at",
        error_code="ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
    )
    normalized_next_tick = _optional_artifact_retention_timestamp(
        next_tick_at,
        field_name="next_tick_at",
        error_code="ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
    )
    normalized_cycle_count = _non_negative_int(
        cycle_count,
        "cycle_count",
        "ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
    )
    normalized_failure_count = _non_negative_int(
        consecutive_failure_count,
        "consecutive_failure_count",
        "ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
    )
    normalized_instance_id = optional_text(daemon_instance_id) or (
        _scheduler_daemon_runtime_state_instance_id(
            scheduler_id=runtime["scheduler_id"],
            observed_at=observed,
        )
    )
    last_cycle = _scheduler_daemon_runtime_state_last_cycle(last_cycle_result)
    state = {
        "daemon_runtime_state_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUNTIME_STATE_SCHEMA_VERSION
        ),
        "daemon_runtime_state_id": _scheduler_daemon_runtime_state_id(
            scheduler_id=runtime["scheduler_id"],
            daemon_instance_id=normalized_instance_id,
            observed_at=observed,
            lifecycle_status=status,
            cycle_count=normalized_cycle_count,
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": runtime["scheduler_id"],
        "daemon_instance_id": normalized_instance_id,
        "observed_at": observed,
        "lifecycle_status": status,
        "lifecycle_reason": reason,
        "stop_requested": normalized_stop_requested,
        "shutdown_requested_at": shutdown_at,
        "last_cycle": last_cycle,
        "next_tick_at": normalized_next_tick,
        "cycle_count": normalized_cycle_count,
        "consecutive_failure_count": normalized_failure_count,
        "heartbeat_worker_id": optional_text(heartbeat_worker_id),
        "runtime_config": deepcopy(runtime),
        "daemon_config": deepcopy(daemon),
        "guardrails": _scheduler_daemon_runtime_state_guardrails(),
        "metadata": _scheduler_daemon_runtime_state_metadata(
            lifecycle_status=status,
            stop_requested=normalized_stop_requested,
            shutdown_requested_at=shutdown_at,
            last_cycle=last_cycle,
            next_tick_at=normalized_next_tick,
            consecutive_failure_count=normalized_failure_count,
        ),
    }
    return validate_artifact_retention_scheduler_daemon_runtime_state(state)


def validate_artifact_retention_scheduler_daemon_runtime_state(
    state: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(state, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
            detail="Artifact retention scheduler daemon runtime state must be an object.",
        )
    normalized = dict(state)
    if set(normalized) != {
        "daemon_runtime_state_schema_version",
        "daemon_runtime_state_id",
        "service_id",
        "scheduler_id",
        "daemon_instance_id",
        "observed_at",
        "lifecycle_status",
        "lifecycle_reason",
        "stop_requested",
        "shutdown_requested_at",
        "last_cycle",
        "next_tick_at",
        "cycle_count",
        "consecutive_failure_count",
        "heartbeat_worker_id",
        "runtime_config",
        "daemon_config",
        "guardrails",
        "metadata",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
            detail="Artifact retention scheduler daemon runtime state keys are invalid.",
        )
    if (
        normalized.get("daemon_runtime_state_schema_version")
        != AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUNTIME_STATE_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_runtime_state_schema_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon runtime state schema version "
                "is invalid."
            ),
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
            detail="Artifact retention scheduler daemon runtime state service id is invalid.",
        )
    _required_text(
        normalized.get("scheduler_id"),
        "scheduler_id",
        "ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
    )
    daemon_instance_id = _required_text(
        normalized.get("daemon_instance_id"),
        "daemon_instance_id",
        "ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
    )
    observed_at = format_artifact_retention_timestamp(
        parse_artifact_retention_timestamp(
            normalized.get("observed_at"),
            field_name="observed_at",
        )
    )
    lifecycle_status = _normalize_scheduler_daemon_runtime_state_status(
        normalized.get("lifecycle_status")
    )
    lifecycle_reason = _normalize_scheduler_daemon_runtime_state_reason(
        normalized.get("lifecycle_reason"),
        lifecycle_status=lifecycle_status,
        runtime_config=normalized.get("runtime_config"),
        consecutive_failure_count=normalized.get("consecutive_failure_count"),
    )
    stop_requested = _required_bool(
        normalized.get("stop_requested"),
        "stop_requested",
        "ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
    )
    shutdown_requested_at = _optional_artifact_retention_timestamp(
        normalized.get("shutdown_requested_at"),
        field_name="shutdown_requested_at",
        error_code="ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
    )
    last_cycle = _scheduler_daemon_runtime_state_last_cycle(
        normalized.get("last_cycle")
    )
    next_tick_at = _optional_artifact_retention_timestamp(
        normalized.get("next_tick_at"),
        field_name="next_tick_at",
        error_code="ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
    )
    cycle_count = _non_negative_int(
        normalized.get("cycle_count"),
        "cycle_count",
        "ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
    )
    failure_count = _non_negative_int(
        normalized.get("consecutive_failure_count"),
        "consecutive_failure_count",
        "ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
    )
    heartbeat_worker_id = optional_text(normalized.get("heartbeat_worker_id"))
    runtime = validate_artifact_retention_scheduler_daemon_runtime_config(
        normalized.get("runtime_config")
    )
    daemon = validate_artifact_retention_scheduler_daemon_config(
        normalized.get("daemon_config")
    )
    _ensure_scheduler_daemon_runtime_scope(
        runtime_config=runtime,
        daemon_config=daemon,
    )
    if normalized["scheduler_id"] != runtime["scheduler_id"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
            detail="Artifact retention scheduler daemon runtime state scope is invalid.",
        )
    _validate_scheduler_daemon_runtime_state_lifecycle(
        lifecycle_status=lifecycle_status,
        lifecycle_reason=lifecycle_reason,
        runtime_config=runtime,
        stop_requested=stop_requested,
        shutdown_requested_at=shutdown_requested_at,
        last_cycle=last_cycle,
        consecutive_failure_count=failure_count,
    )
    expected_id = _scheduler_daemon_runtime_state_id(
        scheduler_id=runtime["scheduler_id"],
        daemon_instance_id=daemon_instance_id,
        observed_at=observed_at,
        lifecycle_status=lifecycle_status,
        cycle_count=cycle_count,
    )
    if normalized.get("daemon_runtime_state_id") != expected_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
            detail="Artifact retention scheduler daemon runtime state id is invalid.",
        )
    if normalized.get("guardrails") != _scheduler_daemon_runtime_state_guardrails():
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
            detail="Artifact retention scheduler daemon runtime state guardrails are invalid.",
        )
    expected_metadata = _scheduler_daemon_runtime_state_metadata(
        lifecycle_status=lifecycle_status,
        stop_requested=stop_requested,
        shutdown_requested_at=shutdown_requested_at,
        last_cycle=last_cycle,
        next_tick_at=next_tick_at,
        consecutive_failure_count=failure_count,
    )
    if normalized.get("metadata") != expected_metadata:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
            detail="Artifact retention scheduler daemon runtime state metadata is invalid.",
        )
    normalized["observed_at"] = observed_at
    normalized["lifecycle_status"] = lifecycle_status
    normalized["lifecycle_reason"] = lifecycle_reason
    normalized["stop_requested"] = stop_requested
    normalized["shutdown_requested_at"] = shutdown_requested_at
    normalized["last_cycle"] = last_cycle
    normalized["next_tick_at"] = next_tick_at
    normalized["cycle_count"] = cycle_count
    normalized["consecutive_failure_count"] = failure_count
    normalized["heartbeat_worker_id"] = heartbeat_worker_id
    normalized["runtime_config"] = runtime
    normalized["daemon_config"] = daemon
    assert_artifact_retention_payload_safe(normalized)
    return normalized


def summarize_artifact_retention_scheduler_daemon_runtime_state(
    state: Mapping[str, Any],
) -> dict[str, Any]:
    validated = validate_artifact_retention_scheduler_daemon_runtime_state(state)
    return {
        "scheduler_id": validated["scheduler_id"],
        "daemon_instance_id": validated["daemon_instance_id"],
        "lifecycle_status": validated["lifecycle_status"],
        "lifecycle_reason": validated["lifecycle_reason"],
        "stop_requested": validated["stop_requested"],
        "shutdown_requested": validated["shutdown_requested_at"] is not None,
        "last_cycle_status": (
            validated["last_cycle"]["result_status"]
            if validated["last_cycle"] is not None
            else None
        ),
        "next_tick_at": validated["next_tick_at"],
        "cycle_count": validated["cycle_count"],
        "consecutive_failure_count": validated["consecutive_failure_count"],
        "heartbeat_worker_id": validated["heartbeat_worker_id"],
        "state_snapshot_only": validated["guardrails"]["state_snapshot_only"],
        "retention_work_uses_job_queue": validated["guardrails"][
            "retention_work_uses_job_queue"
        ],
        "continuous_loop_started_by_builder": validated["guardrails"][
            "continuous_loop_started_by_builder"
        ],
    }


def run_artifact_retention_scheduler_daemon_bounded_loop(
    *,
    artifact_store: Any,
    job_queue: Any | None,
    tenant_id: str,
    workspace_id: str,
    owner_user_id: str,
    lease_store: Any | None = None,
    history_store: Any | None = None,
    scheduler_config: Mapping[str, Any] | None = None,
    runtime_config: Mapping[str, Any] | None = None,
    daemon_config: Mapping[str, Any] | None = None,
    daemon_instance_id: str | None = None,
    max_cycles: int | str = 1,
    retention_days: int | str | None = None,
    as_of: str | None = None,
    scan_limit: int | str | None = None,
    max_delete_count: int | str | None = None,
    requested_at: str | None = None,
    trace_id: str | None = None,
    request_id: str | None = None,
    idempotency_key: str | None = None,
    run_worker: bool = False,
    worker_id: str | None = None,
    stop_requested: bool = False,
    stop_after_cycle: Callable[[int, Mapping[str, Any]], bool] | None = None,
    clock: Callable[[], str] | None = None,
    daemon_heartbeat_emitter: Any | None = None,
) -> dict[str, Any]:
    config = validate_artifact_retention_scheduler_config(
        dict(scheduler_config)
        if scheduler_config is not None
        else build_artifact_retention_scheduler_config(job_queue=job_queue)
    )
    started_at = _scheduler_daemon_bounded_loop_started_at(
        requested_at=requested_at,
        scheduler_config=config,
        clock=clock,
    )
    runtime = validate_artifact_retention_scheduler_daemon_runtime_config(
        dict(runtime_config)
        if runtime_config is not None
        else build_artifact_retention_scheduler_daemon_runtime_config(
            scheduler_config=config,
            checked_at=started_at,
        )
    )
    daemon = validate_artifact_retention_scheduler_daemon_config(
        dict(daemon_config)
        if daemon_config is not None
        else build_artifact_retention_scheduler_daemon_config(
            scheduler_config=config,
            lease_store=lease_store,
            checked_at=started_at,
        )
    )
    _ensure_scheduler_daemon_runtime_scope(
        runtime_config=runtime,
        daemon_config=daemon,
    )
    normalized_max_cycles = _bounded_positive_int(
        max_cycles,
        "max_cycles",
        "ae.artifact_retention_scheduler_daemon_bounded_loop_result_invalid",
        max_value=MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_BOUNDED_LOOP_CYCLES,
    )
    normalized_run_worker = _required_bool(
        run_worker,
        "run_worker",
        "ae.artifact_retention_scheduler_daemon_bounded_loop_result_invalid",
    )
    normalized_stop_requested = _required_bool(
        stop_requested,
        "stop_requested",
        "ae.artifact_retention_scheduler_daemon_bounded_loop_result_invalid",
    )
    if stop_after_cycle is not None and not callable(stop_after_cycle):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_bounded_loop_result_invalid",
            detail="Artifact retention scheduler daemon bounded loop stop callback is invalid.",
        )
    initial_status = (
        "STARTING" if runtime["enablement"]["enablement_status"] == "READY" else "DISABLED"
    )
    initial_state = build_artifact_retention_scheduler_daemon_runtime_state(
        scheduler_config=config,
        runtime_config=runtime,
        daemon_config=daemon,
        daemon_instance_id=daemon_instance_id,
        lifecycle_status=initial_status,
        lifecycle_reason=None,
        observed_at=started_at,
    )
    daemon_instance_id = initial_state["daemon_instance_id"]
    loop_trace_id = _scheduler_daemon_bounded_loop_trace_id(
        trace_id=trace_id,
        scheduler_id=runtime["scheduler_id"],
        daemon_instance_id=daemon_instance_id,
        started_at=started_at,
    )
    loop_request_id = _scheduler_daemon_bounded_loop_request_id(
        request_id=request_id,
        scheduler_id=runtime["scheduler_id"],
        daemon_instance_id=daemon_instance_id,
        started_at=started_at,
    )
    if runtime["enablement"]["enablement_status"] != "READY":
        final_state = build_artifact_retention_scheduler_daemon_runtime_state(
            scheduler_config=config,
            runtime_config=runtime,
            daemon_config=daemon,
            daemon_instance_id=daemon_instance_id,
            lifecycle_status="DISABLED",
            lifecycle_reason=None,
            observed_at=started_at,
        )
        return validate_artifact_retention_scheduler_daemon_bounded_loop_result(
            _build_artifact_retention_scheduler_daemon_bounded_loop_result(
                scheduler_id=runtime["scheduler_id"],
                daemon_instance_id=daemon_instance_id,
                started_at=started_at,
                finished_at=started_at,
                result_status="SKIPPED",
                stop_reason=_scheduler_daemon_bounded_loop_disabled_stop_reason(
                    runtime
                ),
                max_cycles=normalized_max_cycles,
                cycle_results=[],
                consecutive_failure_count=0,
                initial_state=initial_state,
                final_state=final_state,
                runtime_config=runtime,
                daemon_config=daemon,
                run_worker=normalized_run_worker,
            )
        )
    if normalized_stop_requested:
        final_state = build_artifact_retention_scheduler_daemon_runtime_state(
            scheduler_config=config,
            runtime_config=runtime,
            daemon_config=daemon,
            daemon_instance_id=daemon_instance_id,
            lifecycle_status="STOPPED",
            lifecycle_reason="stopped",
            observed_at=started_at,
            stop_requested=True,
            shutdown_requested_at=started_at,
        )
        return validate_artifact_retention_scheduler_daemon_bounded_loop_result(
            _build_artifact_retention_scheduler_daemon_bounded_loop_result(
                scheduler_id=runtime["scheduler_id"],
                daemon_instance_id=daemon_instance_id,
                started_at=started_at,
                finished_at=started_at,
                result_status="STOPPED",
                stop_reason="stop_requested",
                max_cycles=normalized_max_cycles,
                cycle_results=[],
                consecutive_failure_count=0,
                initial_state=initial_state,
                final_state=final_state,
                runtime_config=runtime,
                daemon_config=daemon,
                run_worker=normalized_run_worker,
            )
        )

    cycle_results: list[dict[str, Any]] = []
    consecutive_failure_count = 0
    final_status = "SUCCEEDED"
    stop_reason = "max_cycles_reached"
    finished_at = started_at
    for cycle_index in range(1, normalized_max_cycles + 1):
        cycle_requested_at = _scheduler_daemon_bounded_loop_cycle_requested_at(
            started_at=started_at,
            interval_seconds=runtime["timing"]["interval_seconds"],
            cycle_index=cycle_index,
        )
        try:
            one_cycle = run_artifact_retention_scheduler_daemon_one_cycle(
                artifact_store=artifact_store,
                job_queue=job_queue,
                lease_store=lease_store,
                history_store=history_store,
                scheduler_config=config,
                runtime_config=runtime,
                daemon_config=daemon,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                owner_user_id=owner_user_id,
                retention_days=retention_days,
                as_of=as_of,
                scan_limit=scan_limit,
                max_delete_count=max_delete_count,
                requested_at=cycle_requested_at,
                tick_at=cycle_requested_at,
                trace_id=loop_trace_id,
                request_id=_scheduler_daemon_bounded_loop_cycle_request_id(
                    request_id=loop_request_id,
                    cycle_index=cycle_index,
                ),
                idempotency_key=_scheduler_daemon_bounded_loop_cycle_idempotency_key(
                    idempotency_key=idempotency_key,
                    cycle_index=cycle_index,
                ),
                run_worker=normalized_run_worker,
                worker_id=worker_id,
                clock=clock,
                daemon_heartbeat_emitter=daemon_heartbeat_emitter,
            )
            one_cycle_summary = _scheduler_daemon_runtime_state_last_cycle(one_cycle)
            cycle_error = None
        except Exception:
            one_cycle_summary = _scheduler_daemon_bounded_loop_failure_cycle_summary(
                scheduler_id=runtime["scheduler_id"],
                run_at=cycle_requested_at,
                cycle_index=cycle_index,
            )
            cycle_error = {
                "error_code": (
                    "ae.artifact_retention_scheduler_daemon_bounded_loop_cycle_failed"
                ),
                "retryable": True,
            }
        cycle_record = _scheduler_daemon_bounded_loop_cycle_record(
            cycle_index=cycle_index,
            requested_at=cycle_requested_at,
            one_cycle_result=one_cycle_summary,
            error=cycle_error,
        )
        cycle_results.append(cycle_record)
        finished_at = cycle_requested_at
        if one_cycle_summary["result_status"] == "FAILED":
            consecutive_failure_count += 1
            final_status = "FAILED"
            stop_reason = "cycle_failed"
            break
        consecutive_failure_count = 0
        if stop_after_cycle is not None:
            stop_after = _required_bool(
                stop_after_cycle(cycle_index, deepcopy(cycle_record)),
                "stop_after_cycle_result",
                "ae.artifact_retention_scheduler_daemon_bounded_loop_result_invalid",
            )
        else:
            stop_after = False
        if stop_after:
            final_status = "STOPPED"
            stop_reason = "stop_requested"
            break

    last_cycle = cycle_results[-1]["one_cycle_result"] if cycle_results else None
    final_state = _scheduler_daemon_bounded_loop_final_state(
        scheduler_config=config,
        runtime_config=runtime,
        daemon_config=daemon,
        daemon_instance_id=daemon_instance_id,
        observed_at=finished_at,
        result_status=final_status,
        stop_reason=stop_reason,
        stop_requested=stop_reason == "stop_requested",
        last_cycle_result=last_cycle,
        cycle_count=len(cycle_results),
        consecutive_failure_count=consecutive_failure_count,
    )
    return validate_artifact_retention_scheduler_daemon_bounded_loop_result(
        _build_artifact_retention_scheduler_daemon_bounded_loop_result(
            scheduler_id=runtime["scheduler_id"],
            daemon_instance_id=daemon_instance_id,
            started_at=started_at,
            finished_at=finished_at,
            result_status=final_status,
            stop_reason=stop_reason,
            max_cycles=normalized_max_cycles,
            cycle_results=cycle_results,
            consecutive_failure_count=consecutive_failure_count,
            initial_state=initial_state,
            final_state=final_state,
            runtime_config=runtime,
            daemon_config=daemon,
            run_worker=normalized_run_worker,
        )
    )


def validate_artifact_retention_scheduler_daemon_bounded_loop_result(
    result: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_bounded_loop_result_invalid",
            detail="Artifact retention scheduler daemon bounded loop result must be an object.",
        )
    normalized = dict(result)
    if set(normalized) != {
        "daemon_bounded_loop_result_schema_version",
        "daemon_bounded_loop_result_id",
        "service_id",
        "scheduler_id",
        "daemon_instance_id",
        "started_at",
        "finished_at",
        "result_status",
        "stop_reason",
        "max_cycles",
        "worker_requested",
        "cycle_count",
        "consecutive_failure_count",
        "cycle_results",
        "initial_state",
        "final_state",
        "runtime_config",
        "daemon_config",
        "execution_plan",
        "guardrails",
        "metadata",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_bounded_loop_result_invalid",
            detail="Artifact retention scheduler daemon bounded loop result keys are invalid.",
        )
    if (
        normalized.get("daemon_bounded_loop_result_schema_version")
        != AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_BOUNDED_LOOP_RESULT_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_bounded_loop_result_schema_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon bounded loop result schema "
                "version is invalid."
            ),
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_bounded_loop_result_invalid",
            detail="Artifact retention scheduler daemon bounded loop service id is invalid.",
        )
    scheduler_id = _required_text(
        normalized.get("scheduler_id"),
        "scheduler_id",
        "ae.artifact_retention_scheduler_daemon_bounded_loop_result_invalid",
    )
    daemon_instance_id = _required_text(
        normalized.get("daemon_instance_id"),
        "daemon_instance_id",
        "ae.artifact_retention_scheduler_daemon_bounded_loop_result_invalid",
    )
    started_at = format_artifact_retention_timestamp(
        parse_artifact_retention_timestamp(
            normalized.get("started_at"),
            field_name="started_at",
        )
    )
    finished_at = format_artifact_retention_timestamp(
        parse_artifact_retention_timestamp(
            normalized.get("finished_at"),
            field_name="finished_at",
        )
    )
    result_status = _normalize_scheduler_daemon_bounded_loop_result_status(
        normalized.get("result_status")
    )
    stop_reason = _normalize_scheduler_daemon_bounded_loop_stop_reason(
        normalized.get("stop_reason")
    )
    max_cycles = _bounded_positive_int(
        normalized.get("max_cycles"),
        "max_cycles",
        "ae.artifact_retention_scheduler_daemon_bounded_loop_result_invalid",
        max_value=MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_BOUNDED_LOOP_CYCLES,
    )
    worker_requested = _required_bool(
        normalized.get("worker_requested"),
        "worker_requested",
        "ae.artifact_retention_scheduler_daemon_bounded_loop_result_invalid",
    )
    cycle_count = _non_negative_int(
        normalized.get("cycle_count"),
        "cycle_count",
        "ae.artifact_retention_scheduler_daemon_bounded_loop_result_invalid",
    )
    failure_count = _non_negative_int(
        normalized.get("consecutive_failure_count"),
        "consecutive_failure_count",
        "ae.artifact_retention_scheduler_daemon_bounded_loop_result_invalid",
    )
    cycle_results = _validate_scheduler_daemon_bounded_loop_cycle_results(
        normalized.get("cycle_results")
    )
    initial_state = validate_artifact_retention_scheduler_daemon_runtime_state(
        normalized.get("initial_state")
    )
    final_state = validate_artifact_retention_scheduler_daemon_runtime_state(
        normalized.get("final_state")
    )
    runtime_config = validate_artifact_retention_scheduler_daemon_runtime_config(
        normalized.get("runtime_config")
    )
    daemon_config = validate_artifact_retention_scheduler_daemon_config(
        normalized.get("daemon_config")
    )
    _ensure_scheduler_daemon_runtime_scope(
        runtime_config=runtime_config,
        daemon_config=daemon_config,
    )
    _validate_scheduler_daemon_bounded_loop_scope(
        scheduler_id=scheduler_id,
        daemon_instance_id=daemon_instance_id,
        runtime_config=runtime_config,
        daemon_config=daemon_config,
        initial_state=initial_state,
        final_state=final_state,
    )
    _validate_scheduler_daemon_bounded_loop_status(
        result_status=result_status,
        stop_reason=stop_reason,
        max_cycles=max_cycles,
        cycle_count=cycle_count,
        consecutive_failure_count=failure_count,
        cycle_results=cycle_results,
        initial_state=initial_state,
        final_state=final_state,
        runtime_config=runtime_config,
    )
    expected_execution_plan = _scheduler_daemon_bounded_loop_execution_plan(
        result_status=result_status,
        stop_reason=stop_reason,
        max_cycles=max_cycles,
        cycle_count=cycle_count,
        run_worker=worker_requested,
    )
    if normalized.get("execution_plan") != expected_execution_plan:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_bounded_loop_result_invalid",
            detail="Artifact retention scheduler daemon bounded loop execution plan is invalid.",
        )
    if normalized.get("guardrails") != _scheduler_daemon_bounded_loop_guardrails():
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_bounded_loop_result_invalid",
            detail="Artifact retention scheduler daemon bounded loop guardrails are invalid.",
        )
    expected_metadata = _scheduler_daemon_bounded_loop_metadata(
        result_status=result_status,
        stop_reason=stop_reason,
        cycle_results=cycle_results,
        final_state=final_state,
    )
    if normalized.get("metadata") != expected_metadata:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_bounded_loop_result_invalid",
            detail="Artifact retention scheduler daemon bounded loop metadata is invalid.",
        )
    expected_id = _scheduler_daemon_bounded_loop_result_id(
        scheduler_id=scheduler_id,
        daemon_instance_id=daemon_instance_id,
        started_at=started_at,
        finished_at=finished_at,
        result_status=result_status,
        stop_reason=stop_reason,
        cycle_results=cycle_results,
        final_state=final_state,
    )
    if normalized.get("daemon_bounded_loop_result_id") != expected_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_bounded_loop_result_invalid",
            detail="Artifact retention scheduler daemon bounded loop result id is invalid.",
        )
    normalized["started_at"] = started_at
    normalized["finished_at"] = finished_at
    normalized["result_status"] = result_status
    normalized["stop_reason"] = stop_reason
    normalized["max_cycles"] = max_cycles
    normalized["worker_requested"] = worker_requested
    normalized["cycle_count"] = cycle_count
    normalized["consecutive_failure_count"] = failure_count
    normalized["cycle_results"] = cycle_results
    normalized["initial_state"] = initial_state
    normalized["final_state"] = final_state
    normalized["runtime_config"] = runtime_config
    normalized["daemon_config"] = daemon_config
    assert_artifact_retention_payload_safe(normalized)
    return normalized


def summarize_artifact_retention_scheduler_daemon_bounded_loop_result(
    result: Mapping[str, Any],
) -> dict[str, Any]:
    validated = validate_artifact_retention_scheduler_daemon_bounded_loop_result(
        result
    )
    return {
        "scheduler_id": validated["scheduler_id"],
        "daemon_instance_id": validated["daemon_instance_id"],
        "result_status": validated["result_status"],
        "stop_reason": validated["stop_reason"],
        "started_at": validated["started_at"],
        "finished_at": validated["finished_at"],
        "max_cycles": validated["max_cycles"],
        "cycle_count": validated["cycle_count"],
        "consecutive_failure_count": validated["consecutive_failure_count"],
        "final_lifecycle_status": validated["final_state"]["lifecycle_status"],
        "final_lifecycle_reason": validated["final_state"]["lifecycle_reason"],
        "bounded_loop_started": validated["metadata"]["bounded_loop_started"],
        "tick_once_ran": validated["metadata"]["tick_once_ran"],
        "job_enqueued": validated["metadata"]["job_enqueued"],
        "worker_executed": validated["metadata"]["worker_executed"],
        "continuous_loop_started": validated["guardrails"][
            "continuous_loop_started"
        ],
    }


def build_artifact_retention_scheduler_daemon_shutdown_transition(
    *,
    current_state: Mapping[str, Any],
    requested_at: str | None = None,
    requested_by: Mapping[str, Any] | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    previous_state = validate_artifact_retention_scheduler_daemon_runtime_state(
        current_state
    )
    requested = _scheduler_daemon_checked_at(
        checked_at=requested_at or previous_state["observed_at"],
        scheduler_config=previous_state["runtime_config"],
    )
    decision_status, decision_reason, next_state = (
        _scheduler_daemon_shutdown_transition_next_state(
            previous_state=previous_state,
            requested_at=requested,
        )
    )
    requested_actor = _scheduler_daemon_shutdown_transition_requested_by(
        requested_by
    )
    transition = {
        "daemon_shutdown_transition_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SHUTDOWN_TRANSITION_SCHEMA_VERSION
        ),
        "daemon_shutdown_transition_id": (
            _scheduler_daemon_shutdown_transition_id(
                scheduler_id=previous_state["scheduler_id"],
                daemon_instance_id=previous_state["daemon_instance_id"],
                requested_at=requested,
                requested_by=requested_actor,
                reason=optional_text(reason),
                decision_status=decision_status,
                decision_reason=decision_reason,
                previous_state=previous_state,
                next_state=next_state,
            )
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": previous_state["scheduler_id"],
        "daemon_instance_id": previous_state["daemon_instance_id"],
        "requested_at": requested,
        "requested_by": requested_actor,
        "reason": optional_text(reason),
        "decision_status": decision_status,
        "decision_reason": decision_reason,
        "previous_state": deepcopy(previous_state),
        "next_state": deepcopy(next_state),
        "execution_plan": _scheduler_daemon_shutdown_transition_execution_plan(
            decision_status=decision_status,
            decision_reason=decision_reason,
            next_state=next_state,
        ),
        "guardrails": _scheduler_daemon_shutdown_transition_guardrails(),
        "metadata": _scheduler_daemon_shutdown_transition_metadata(
            decision_status=decision_status,
            decision_reason=decision_reason,
            previous_state=previous_state,
            next_state=next_state,
        ),
    }
    return validate_artifact_retention_scheduler_daemon_shutdown_transition(
        transition
    )


def validate_artifact_retention_scheduler_daemon_shutdown_transition(
    transition: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(transition, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_shutdown_transition_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon shutdown transition must be "
                "an object."
            ),
        )
    normalized = dict(transition)
    if set(normalized) != {
        "daemon_shutdown_transition_schema_version",
        "daemon_shutdown_transition_id",
        "service_id",
        "scheduler_id",
        "daemon_instance_id",
        "requested_at",
        "requested_by",
        "reason",
        "decision_status",
        "decision_reason",
        "previous_state",
        "next_state",
        "execution_plan",
        "guardrails",
        "metadata",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_shutdown_transition_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon shutdown transition keys are "
                "invalid."
            ),
        )
    if (
        normalized.get("daemon_shutdown_transition_schema_version")
        != AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SHUTDOWN_TRANSITION_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_shutdown_transition_schema_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon shutdown transition schema "
                "version is invalid."
            ),
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_shutdown_transition_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon shutdown transition service "
                "id is invalid."
            ),
        )
    scheduler_id = _required_text(
        normalized.get("scheduler_id"),
        "scheduler_id",
        "ae.artifact_retention_scheduler_daemon_shutdown_transition_invalid",
    )
    daemon_instance_id = _required_text(
        normalized.get("daemon_instance_id"),
        "daemon_instance_id",
        "ae.artifact_retention_scheduler_daemon_shutdown_transition_invalid",
    )
    requested_at = format_artifact_retention_timestamp(
        parse_artifact_retention_timestamp(
            normalized.get("requested_at"),
            field_name="requested_at",
        )
    )
    requested_by = _scheduler_daemon_shutdown_transition_requested_by(
        normalized.get("requested_by")
    )
    reason = optional_text(normalized.get("reason"))
    decision_status = _normalize_scheduler_daemon_shutdown_transition_status(
        normalized.get("decision_status")
    )
    decision_reason = _normalize_scheduler_daemon_shutdown_transition_reason(
        normalized.get("decision_reason")
    )
    previous_state = validate_artifact_retention_scheduler_daemon_runtime_state(
        normalized.get("previous_state")
    )
    next_state = validate_artifact_retention_scheduler_daemon_runtime_state(
        normalized.get("next_state")
    )
    _validate_scheduler_daemon_shutdown_transition_scope(
        scheduler_id=scheduler_id,
        daemon_instance_id=daemon_instance_id,
        previous_state=previous_state,
        next_state=next_state,
    )
    _validate_scheduler_daemon_shutdown_transition_decision(
        requested_at=requested_at,
        decision_status=decision_status,
        decision_reason=decision_reason,
        previous_state=previous_state,
        next_state=next_state,
    )
    expected_execution_plan = (
        _scheduler_daemon_shutdown_transition_execution_plan(
            decision_status=decision_status,
            decision_reason=decision_reason,
            next_state=next_state,
        )
    )
    if normalized.get("execution_plan") != expected_execution_plan:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_shutdown_transition_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon shutdown transition "
                "execution plan is invalid."
            ),
        )
    if (
        normalized.get("guardrails")
        != _scheduler_daemon_shutdown_transition_guardrails()
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_shutdown_transition_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon shutdown transition "
                "guardrails are invalid."
            ),
        )
    expected_metadata = _scheduler_daemon_shutdown_transition_metadata(
        decision_status=decision_status,
        decision_reason=decision_reason,
        previous_state=previous_state,
        next_state=next_state,
    )
    if normalized.get("metadata") != expected_metadata:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_shutdown_transition_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon shutdown transition metadata "
                "is invalid."
            ),
        )
    expected_id = _scheduler_daemon_shutdown_transition_id(
        scheduler_id=scheduler_id,
        daemon_instance_id=daemon_instance_id,
        requested_at=requested_at,
        requested_by=requested_by,
        reason=reason,
        decision_status=decision_status,
        decision_reason=decision_reason,
        previous_state=previous_state,
        next_state=next_state,
    )
    if normalized.get("daemon_shutdown_transition_id") != expected_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_shutdown_transition_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon shutdown transition id is "
                "invalid."
            ),
        )
    normalized["requested_at"] = requested_at
    normalized["requested_by"] = requested_by
    normalized["reason"] = reason
    normalized["decision_status"] = decision_status
    normalized["decision_reason"] = decision_reason
    normalized["previous_state"] = previous_state
    normalized["next_state"] = next_state
    assert_artifact_retention_payload_safe(normalized)
    return normalized


def summarize_artifact_retention_scheduler_daemon_shutdown_transition(
    transition: Mapping[str, Any],
) -> dict[str, Any]:
    validated = validate_artifact_retention_scheduler_daemon_shutdown_transition(
        transition
    )
    return {
        "scheduler_id": validated["scheduler_id"],
        "daemon_instance_id": validated["daemon_instance_id"],
        "requested_at": validated["requested_at"],
        "decision_status": validated["decision_status"],
        "decision_reason": validated["decision_reason"],
        "from_lifecycle_status": validated["previous_state"][
            "lifecycle_status"
        ],
        "to_lifecycle_status": validated["next_state"]["lifecycle_status"],
        "stop_requested": validated["next_state"]["stop_requested"],
        "shutdown_requested": validated["metadata"]["shutdown_requested"],
        "runtime_state_mutated": validated["guardrails"][
            "runtime_state_mutated"
        ],
        "continuous_loop_started": validated["guardrails"][
            "continuous_loop_started"
        ],
    }


def build_artifact_retention_scheduler_daemon_control_plan(
    *,
    action: str,
    daemon_config: Mapping[str, Any] | None = None,
    scheduler_config: Mapping[str, Any] | None = None,
    lease_store: Any | None = None,
    requested_at: str | None = None,
    requested_by: Mapping[str, Any] | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    normalized_action = normalize_artifact_retention_scheduler_daemon_control_action(
        action
    )
    config = validate_artifact_retention_scheduler_daemon_config(
        dict(daemon_config)
        if daemon_config is not None
        else build_artifact_retention_scheduler_daemon_config(
            scheduler_config=scheduler_config,
            lease_store=lease_store,
        )
    )
    requested = _scheduler_daemon_checked_at(
        checked_at=requested_at,
        scheduler_config=config,
    )
    action_item = _scheduler_daemon_action_item(config, normalized_action)
    plan = {
        "daemon_control_plan_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONTROL_PLAN_SCHEMA_VERSION
        ),
        "daemon_control_plan_id": _scheduler_daemon_control_plan_id(
            scheduler_id=config["scheduler_id"],
            action=normalized_action,
            requested_at=requested,
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": config["scheduler_id"],
        "action": normalized_action,
        "decision_status": action_item["decision_status"],
        "block_reason": action_item["block_reason"],
        "requested_at": requested,
        "requested_by": _scheduler_daemon_requested_by(requested_by),
        "reason": optional_text(reason),
        "daemon_config": deepcopy(config),
        "execution_plan": _scheduler_daemon_control_execution_plan(action_item),
        "guardrails": _scheduler_daemon_guardrails(),
        "metadata": _scheduler_daemon_control_metadata(action_item),
    }
    return validate_artifact_retention_scheduler_daemon_control_plan(plan)


def validate_artifact_retention_scheduler_daemon_control_plan(
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(plan, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_control_plan_invalid",
            detail="Artifact retention scheduler daemon control plan must be an object.",
        )
    normalized = dict(plan)
    if (
        normalized.get("daemon_control_plan_schema_version")
        != AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONTROL_PLAN_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_control_plan_schema_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon control plan schema version "
                "is invalid."
            ),
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_control_plan_invalid",
            detail="Artifact retention scheduler daemon control plan service id is invalid.",
        )
    for field_name in ("daemon_control_plan_id", "scheduler_id"):
        _required_text(
            normalized.get(field_name),
            field_name,
            "ae.artifact_retention_scheduler_daemon_control_plan_invalid",
        )
    action = normalize_artifact_retention_scheduler_daemon_control_action(
        normalized.get("action")
    )
    daemon_config = validate_artifact_retention_scheduler_daemon_config(
        normalized.get("daemon_config")
    )
    if daemon_config["scheduler_id"] != normalized["scheduler_id"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_control_plan_invalid",
            detail="Artifact retention scheduler daemon control plan scope is invalid.",
        )
    requested_at = format_artifact_retention_timestamp(
        parse_artifact_retention_timestamp(
            normalized.get("requested_at"),
            field_name="requested_at",
        )
    )
    expected_plan_id = _scheduler_daemon_control_plan_id(
        scheduler_id=normalized["scheduler_id"],
        action=action,
        requested_at=requested_at,
    )
    if normalized["daemon_control_plan_id"] != expected_plan_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_control_plan_invalid",
            detail="Artifact retention scheduler daemon control plan id is invalid.",
        )
    action_item = _scheduler_daemon_action_item(daemon_config, action)
    if normalized.get("decision_status") != action_item["decision_status"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_control_plan_invalid",
            detail="Artifact retention scheduler daemon control decision is invalid.",
        )
    if normalized.get("block_reason") != action_item["block_reason"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_control_plan_invalid",
            detail="Artifact retention scheduler daemon control block reason is invalid.",
        )
    if (
        action_item["decision_status"] == "BLOCKED"
        and action_item["block_reason"]
        not in ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONTROL_BLOCK_REASONS
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_control_plan_invalid",
            detail="Artifact retention scheduler daemon control block reason is invalid.",
        )
    if _scheduler_daemon_requested_by(normalized.get("requested_by")) != normalized.get(
        "requested_by"
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_control_plan_invalid",
            detail="Artifact retention scheduler daemon control requested_by is invalid.",
        )
    if optional_text(normalized.get("reason")) != normalized.get("reason"):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_control_plan_invalid",
            detail="Artifact retention scheduler daemon control reason is invalid.",
        )
    if normalized.get("execution_plan") != _scheduler_daemon_control_execution_plan(
        action_item
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_control_plan_invalid",
            detail="Artifact retention scheduler daemon control execution plan is invalid.",
        )
    if normalized.get("guardrails") != _scheduler_daemon_guardrails():
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_control_plan_invalid",
            detail="Artifact retention scheduler daemon control guardrails are invalid.",
        )
    if normalized.get("metadata") != _scheduler_daemon_control_metadata(action_item):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_control_plan_invalid",
            detail="Artifact retention scheduler daemon control metadata is invalid.",
        )
    normalized["action"] = action
    normalized["requested_at"] = requested_at
    assert_artifact_retention_payload_safe(normalized)
    return normalized


def summarize_artifact_retention_scheduler_daemon_control_plan(
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    validated = validate_artifact_retention_scheduler_daemon_control_plan(plan)
    return {
        "scheduler_id": validated["scheduler_id"],
        "action": validated["action"],
        "decision_status": validated["decision_status"],
        "block_reason": validated["block_reason"],
        "runs_tick_once": validated["execution_plan"]["runs_tick_once"],
        "scheduler_daemon_started": validated["metadata"]["scheduler_daemon_started"],
        "continuous_loop_started": validated["metadata"]["continuous_loop_started"],
    }


def build_artifact_retention_scheduler_daemon_start_stop_guardrail(
    *,
    action: str,
    daemon_config: Mapping[str, Any] | None = None,
    scheduler_config: Mapping[str, Any] | None = None,
    lease_store: Any | None = None,
    requested_at: str | None = None,
    requested_by: Mapping[str, Any] | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    normalized_action = _normalize_scheduler_daemon_start_stop_action(action)
    control_plan = build_artifact_retention_scheduler_daemon_control_plan(
        action=normalized_action,
        daemon_config=daemon_config,
        scheduler_config=scheduler_config,
        lease_store=lease_store,
        requested_at=requested_at,
        requested_by=requested_by,
        reason=reason,
    )
    return validate_artifact_retention_scheduler_daemon_start_stop_guardrail(
        _build_artifact_retention_scheduler_daemon_start_stop_guardrail(
            control_plan=control_plan
        )
    )


def validate_artifact_retention_scheduler_daemon_start_stop_guardrail(
    guardrail: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(guardrail, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_start_stop_guardrail_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon start/stop guardrail must be "
                "an object."
            ),
        )
    normalized = dict(guardrail)
    if set(normalized) != {
        "daemon_start_stop_guardrail_schema_version",
        "daemon_start_stop_guardrail_id",
        "service_id",
        "scheduler_id",
        "action",
        "guardrail_status",
        "guardrail_reason",
        "requested_at",
        "control_plan",
        "action_allowed",
        "runtime_state_transition",
        "execution_plan",
        "guardrails",
        "metadata",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_start_stop_guardrail_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon start/stop guardrail keys "
                "are invalid."
            ),
        )
    if normalized.get("daemon_start_stop_guardrail_schema_version") != (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_START_STOP_GUARDRAIL_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_start_stop_guardrail_schema_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon start/stop guardrail schema "
                "version is invalid."
            ),
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_start_stop_guardrail_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon start/stop guardrail service "
                "id is invalid."
            ),
        )
    _required_text(
        normalized.get("daemon_start_stop_guardrail_id"),
        "daemon_start_stop_guardrail_id",
        "ae.artifact_retention_scheduler_daemon_start_stop_guardrail_invalid",
    )
    _required_text(
        normalized.get("scheduler_id"),
        "scheduler_id",
        "ae.artifact_retention_scheduler_daemon_start_stop_guardrail_invalid",
    )
    action = _normalize_scheduler_daemon_start_stop_action(normalized.get("action"))
    requested_at = format_artifact_retention_timestamp(
        parse_artifact_retention_timestamp(
            normalized.get("requested_at"),
            field_name="requested_at",
        )
    )
    control_plan = validate_artifact_retention_scheduler_daemon_control_plan(
        normalized.get("control_plan")
    )
    if (
        control_plan["scheduler_id"] != normalized["scheduler_id"]
        or control_plan["action"] != action
        or control_plan["requested_at"] != requested_at
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_start_stop_guardrail_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon start/stop guardrail scope "
                "is invalid."
            ),
        )
    expected_status, expected_reason = _scheduler_daemon_start_stop_guardrail_decision(
        control_plan
    )
    if normalized.get("guardrail_status") not in (
        ARTIFACT_RETENTION_SCHEDULER_DAEMON_START_STOP_GUARDRAIL_STATUSES
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_start_stop_guardrail_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon start/stop guardrail status "
                "is invalid."
            ),
        )
    if normalized.get("guardrail_status") != expected_status:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_start_stop_guardrail_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon start/stop guardrail decision "
                "is invalid."
            ),
        )
    if normalized.get("guardrail_reason") not in (
        ARTIFACT_RETENTION_SCHEDULER_DAEMON_START_STOP_GUARDRAIL_REASONS
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_start_stop_guardrail_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon start/stop guardrail reason "
                "is invalid."
            ),
        )
    if normalized.get("guardrail_reason") != expected_reason:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_start_stop_guardrail_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon start/stop guardrail reason "
                "is invalid."
            ),
        )
    if _required_bool(
        normalized.get("action_allowed"),
        "action_allowed",
        "ae.artifact_retention_scheduler_daemon_start_stop_guardrail_invalid",
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_start_stop_guardrail_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon start/stop action is not "
                "allowed by policy."
            ),
        )
    if normalized.get("runtime_state_transition") != "NONE":
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_start_stop_guardrail_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon start/stop runtime state "
                "transition is invalid."
            ),
        )
    expected_execution_plan = _scheduler_daemon_start_stop_execution_plan(
        control_plan
    )
    if normalized.get("execution_plan") != expected_execution_plan:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_start_stop_guardrail_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon start/stop execution plan "
                "is invalid."
            ),
        )
    if normalized.get("guardrails") != _scheduler_daemon_start_stop_guardrails():
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_start_stop_guardrail_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon start/stop guardrails are "
                "invalid."
            ),
        )
    if normalized.get("metadata") != _scheduler_daemon_start_stop_metadata(
        control_plan=control_plan,
        guardrail_status=expected_status,
        guardrail_reason=expected_reason,
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_start_stop_guardrail_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon start/stop metadata is "
                "invalid."
            ),
        )
    expected_id = _scheduler_daemon_start_stop_guardrail_id(
        control_plan=control_plan,
        guardrail_status=expected_status,
        guardrail_reason=expected_reason,
    )
    if normalized["daemon_start_stop_guardrail_id"] != expected_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_start_stop_guardrail_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon start/stop guardrail id is "
                "invalid."
            ),
        )
    normalized["action"] = action
    normalized["requested_at"] = requested_at
    normalized["control_plan"] = control_plan
    normalized["execution_plan"] = expected_execution_plan
    assert_artifact_retention_payload_safe(normalized)
    return normalized


def summarize_artifact_retention_scheduler_daemon_start_stop_guardrail(
    guardrail: Mapping[str, Any],
) -> dict[str, Any]:
    validated = validate_artifact_retention_scheduler_daemon_start_stop_guardrail(
        guardrail
    )
    return {
        "scheduler_id": validated["scheduler_id"],
        "action": validated["action"],
        "guardrail_status": validated["guardrail_status"],
        "guardrail_reason": validated["guardrail_reason"],
        "action_allowed": validated["action_allowed"],
        "runtime_state_transition": validated["runtime_state_transition"],
        "scheduler_daemon_started": validated["metadata"][
            "scheduler_daemon_started"
        ],
        "continuous_loop_started": validated["metadata"][
            "continuous_loop_started"
        ],
        "stop_signal_sent": validated["metadata"]["stop_signal_sent"],
    }


def dispatch_artifact_retention_scheduler_daemon_control(
    *,
    action: str,
    artifact_store: Any,
    job_queue: Any | None,
    tenant_id: str,
    workspace_id: str,
    owner_user_id: str,
    lease_store: Any | None = None,
    history_store: Any | None = None,
    scheduler_config: Mapping[str, Any] | None = None,
    requested_at: str | None = None,
    requested_by: Mapping[str, Any] | None = None,
    reason: str | None = None,
    lease_owner_id: str = DEFAULT_ARTIFACT_RETENTION_SCHEDULER_LEASE_OWNER_ID,
    retention_days: int | str | None = None,
    as_of: str | None = None,
    scan_limit: int | str | None = None,
    max_delete_count: int | str | None = None,
    tick_at: str | None = None,
    trace_id: str | None = None,
    request_id: str | None = None,
    idempotency_key: str | None = None,
    run_worker: bool = False,
    worker_id: str | None = None,
    clock: Callable[[], str] | None = None,
) -> dict[str, Any]:
    config = validate_artifact_retention_scheduler_config(
        dict(scheduler_config)
        if scheduler_config is not None
        else build_artifact_retention_scheduler_config(job_queue=job_queue)
    )
    daemon_config = build_artifact_retention_scheduler_daemon_config(
        scheduler_config=config,
        lease_store=lease_store,
        checked_at=requested_at,
    )
    control_plan = build_artifact_retention_scheduler_daemon_control_plan(
        action=action,
        daemon_config=daemon_config,
        requested_at=requested_at,
        requested_by=requested_by,
        reason=reason,
    )
    start_stop_guardrail = (
        validate_artifact_retention_scheduler_daemon_start_stop_guardrail(
            _build_artifact_retention_scheduler_daemon_start_stop_guardrail(
                control_plan=control_plan
            )
        )
        if _is_scheduler_daemon_start_stop_action(control_plan["action"])
        else None
    )
    tick_once_result = None
    if control_plan["execution_plan"]["runs_tick_once"] is True:
        tick_once_result = run_artifact_retention_scheduler_tick_once(
            artifact_store=artifact_store,
            job_queue=job_queue,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            lease_store=lease_store,
            history_store=history_store,
            scheduler_config=config,
            lease_owner_id=lease_owner_id,
            retention_days=retention_days,
            as_of=as_of,
            scan_limit=scan_limit,
            max_delete_count=max_delete_count,
            tick_at=tick_at or control_plan["requested_at"],
            trace_id=trace_id,
            request_id=request_id,
            idempotency_key=idempotency_key,
            run_worker=run_worker,
            worker_id=worker_id,
            clock=clock,
        )
    return validate_artifact_retention_scheduler_daemon_dispatch_result(
        _build_artifact_retention_scheduler_daemon_dispatch_result(
            control_plan=control_plan,
            tick_once_result=tick_once_result,
            start_stop_guardrail=start_stop_guardrail,
        )
    )


def validate_artifact_retention_scheduler_daemon_dispatch_result(
    result: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_dispatch_result_invalid",
            detail="Artifact retention scheduler daemon dispatch result must be an object.",
        )
    normalized = dict(result)
    if set(normalized) != {
        "daemon_dispatch_result_schema_version",
        "daemon_dispatch_result_id",
        "service_id",
        "scheduler_id",
        "dispatch_status",
        "control_plan",
        "tick_once_result",
        "start_stop_guardrail",
        "guardrails",
        "metadata",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_dispatch_result_invalid",
            detail="Artifact retention scheduler daemon dispatch result keys are invalid.",
        )
    if (
        normalized.get("daemon_dispatch_result_schema_version")
        != AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_DISPATCH_RESULT_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_dispatch_result_schema_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon dispatch result schema version "
                "is invalid."
            ),
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_dispatch_result_invalid",
            detail="Artifact retention scheduler daemon dispatch result service id is invalid.",
        )
    for field_name in ("daemon_dispatch_result_id", "scheduler_id"):
        _required_text(
            normalized.get(field_name),
            field_name,
            "ae.artifact_retention_scheduler_daemon_dispatch_result_invalid",
        )
    dispatch_status = normalized.get("dispatch_status")
    if dispatch_status not in ARTIFACT_RETENTION_SCHEDULER_DAEMON_DISPATCH_STATUSES:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_dispatch_result_invalid",
            detail="Artifact retention scheduler daemon dispatch status is invalid.",
        )
    control_plan = validate_artifact_retention_scheduler_daemon_control_plan(
        normalized.get("control_plan")
    )
    if control_plan["scheduler_id"] != normalized["scheduler_id"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_dispatch_result_invalid",
            detail="Artifact retention scheduler daemon dispatch scope is invalid.",
        )
    start_stop_guardrail = normalized.get("start_stop_guardrail")
    if _is_scheduler_daemon_start_stop_action(control_plan["action"]):
        start_stop_guardrail = (
            validate_artifact_retention_scheduler_daemon_start_stop_guardrail(
                start_stop_guardrail
            )
        )
        if (
            start_stop_guardrail["scheduler_id"] != normalized["scheduler_id"]
            or start_stop_guardrail["action"] != control_plan["action"]
            or start_stop_guardrail["control_plan"] != control_plan
        ):
            raise ArtifactHandoffError(
                status_code=422,
                error_code=(
                    "ae.artifact_retention_scheduler_daemon_dispatch_result_invalid"
                ),
                detail=(
                    "Artifact retention scheduler daemon dispatch start/stop "
                    "guardrail is invalid."
                ),
            )
    elif start_stop_guardrail is not None:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_dispatch_result_invalid",
            detail=(
                "Non start/stop scheduler daemon dispatch result cannot include "
                "a start/stop guardrail."
            ),
        )
    tick_once_result = normalized.get("tick_once_result")
    if control_plan["decision_status"] == "READY":
        validated_tick = validate_artifact_retention_scheduler_tick_once_result(
            tick_once_result
        )
        if (
            dispatch_status != "DISPATCHED"
            or control_plan["action"]
            != ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONTROL_ACTION_MANUAL_TICK_ONCE
            or validated_tick["scheduler_id"] != normalized["scheduler_id"]
        ):
            raise ArtifactHandoffError(
                status_code=422,
                error_code=(
                    "ae.artifact_retention_scheduler_daemon_dispatch_result_invalid"
                ),
                detail="Ready scheduler daemon dispatch result is invalid.",
            )
    else:
        if dispatch_status != control_plan["decision_status"] or tick_once_result is not None:
            raise ArtifactHandoffError(
                status_code=422,
                error_code=(
                    "ae.artifact_retention_scheduler_daemon_dispatch_result_invalid"
                ),
                detail="Blocked scheduler daemon dispatch result is invalid.",
            )
    expected_id = _scheduler_daemon_dispatch_result_id(
        control_plan=control_plan,
        tick_once_result=tick_once_result,
        start_stop_guardrail=start_stop_guardrail,
    )
    if normalized["daemon_dispatch_result_id"] != expected_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_dispatch_result_invalid",
            detail="Artifact retention scheduler daemon dispatch result id is invalid.",
        )
    if normalized.get("guardrails") != _scheduler_daemon_dispatch_guardrails():
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_dispatch_result_invalid",
            detail="Artifact retention scheduler daemon dispatch guardrails are invalid.",
        )
    if normalized.get("metadata") != _scheduler_daemon_dispatch_metadata(
        control_plan=control_plan,
        tick_once_result=tick_once_result,
        start_stop_guardrail=start_stop_guardrail,
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_dispatch_result_invalid",
            detail="Artifact retention scheduler daemon dispatch metadata is invalid.",
        )
    assert_artifact_retention_payload_safe(normalized)
    normalized["start_stop_guardrail"] = start_stop_guardrail
    return normalized


def summarize_artifact_retention_scheduler_daemon_dispatch_result(
    result: Mapping[str, Any],
) -> dict[str, Any]:
    validated = validate_artifact_retention_scheduler_daemon_dispatch_result(result)
    return {
        "scheduler_id": validated["scheduler_id"],
        "action": validated["control_plan"]["action"],
        "dispatch_status": validated["dispatch_status"],
        "tick_once_result_status": (
            validated["tick_once_result"]["result_status"]
            if validated["tick_once_result"] is not None
            else None
        ),
        "start_stop_guardrail_status": (
            validated["start_stop_guardrail"]["guardrail_status"]
            if validated["start_stop_guardrail"] is not None
            else None
        ),
        "start_stop_guardrail_reason": (
            validated["start_stop_guardrail"]["guardrail_reason"]
            if validated["start_stop_guardrail"] is not None
            else None
        ),
        "job_enqueued": validated["metadata"]["job_enqueued"],
        "lease_released": validated["metadata"]["lease_released"],
        "scheduler_daemon_started": validated["metadata"]["scheduler_daemon_started"],
        "continuous_loop_started": validated["metadata"]["continuous_loop_started"],
    }


def _build_artifact_retention_scheduler_tick_once_result(
    *,
    scheduler_config: Mapping[str, Any],
    run_at: str,
    lease_decision: Mapping[str, Any],
    lease_release: Mapping[str, Any] | None,
    batch_plan: Mapping[str, Any] | None,
    tick_plan: Mapping[str, Any] | None,
    enqueue_result: Mapping[str, Any] | None,
    worker_result: Mapping[str, Any] | None,
) -> dict[str, Any]:
    validated_config = validate_artifact_retention_scheduler_config(
        dict(scheduler_config)
    )
    validated_decision = validate_artifact_retention_scheduler_lease_decision(
        lease_decision
    )
    result_status = (
        "SKIPPED"
        if not validated_decision["lease_acquired"]
        else _scheduler_tick_once_result_status(
            tick_plan=tick_plan,
            enqueue_result=enqueue_result,
            worker_result=worker_result,
        )
    )
    skip_reason = (
        "lease_busy"
        if not validated_decision["lease_acquired"]
        else _scheduler_tick_once_skip_reason(tick_plan)
    )
    result = {
        "tick_once_result_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_TICK_ONCE_RESULT_SCHEMA_VERSION
        ),
        "tick_once_result_id": _scheduler_tick_once_result_id(
            scheduler_id=validated_config["scheduler_id"],
            lease_decision=validated_decision,
            run_at=run_at,
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": validated_config["scheduler_id"],
        "lease_owner_id": validated_decision["lease_owner_id"],
        "run_at": run_at,
        "result_status": result_status,
        "skip_reason": skip_reason,
        "lease_decision": deepcopy(dict(validated_decision)),
        "lease_release": deepcopy(dict(lease_release)) if lease_release else None,
        "batch_plan": deepcopy(dict(batch_plan)) if batch_plan else None,
        "tick_plan": deepcopy(dict(tick_plan)) if tick_plan else None,
        "enqueue_result": deepcopy(dict(enqueue_result)) if enqueue_result else None,
        "worker_result": deepcopy(dict(worker_result)) if worker_result else None,
        "guardrails": {
            "manual_once_runner": True,
            "lease_required_before_tick": True,
            "lease_released_after_tick": lease_release is not None,
            "daemon_auto_start_allowed": False,
            "scheduler_daemon_started": False,
            "continuous_loop_started": False,
            "physical_delete_automation_enabled": False,
        },
        "metadata": _scheduler_tick_once_metadata(
            lease_decision=validated_decision,
            lease_release=lease_release,
            enqueue_result=enqueue_result,
            worker_result=worker_result,
        ),
    }
    return result


def _scheduler_tick_once_lease_store(lease_store: Any | None) -> Any:
    store = lease_store or DEFAULT_ARTIFACT_RETENTION_SCHEDULER_LEASE_STORE
    if not (
        hasattr(store, "ensure_available")
        and hasattr(store, "acquire")
        and hasattr(store, "release")
    ):
        raise ArtifactHandoffError(
            status_code=500,
            error_code="ae.artifact_retention_scheduler_lease_store_invalid",
            detail="Artifact retention scheduler lease store is invalid.",
        )
    return store


def _scheduler_tick_once_run_at(
    *,
    tick_at: str | None,
    scheduler_config: Mapping[str, Any],
    clock: Callable[[], str] | None,
) -> str:
    candidate = tick_at or (clock() if clock is not None else None)
    observed = candidate or _request_time_from_config(scheduler_config)
    return format_artifact_retention_timestamp(
        parse_artifact_retention_timestamp(observed, field_name="tick_at")
    )


def _scheduler_tick_once_result_status(
    *,
    tick_plan: Mapping[str, Any] | None,
    enqueue_result: Mapping[str, Any] | None,
    worker_result: Mapping[str, Any] | None,
) -> str:
    if tick_plan is None or enqueue_result is None:
        return "FAILED"
    if _scheduler_tick_once_worker_failed(worker_result):
        return "FAILED"
    if tick_plan.get("tick_status") == "NOOP":
        return "NOOP"
    if tick_plan.get("tick_status") == "SKIPPED":
        return "SKIPPED"
    if enqueue_result.get("enqueue_status") == "ENQUEUED":
        return "SUCCEEDED"
    return "SKIPPED"


def _scheduler_tick_once_skip_reason(
    tick_plan: Mapping[str, Any] | None,
) -> str | None:
    if tick_plan is None:
        return None
    return optional_text(tick_plan.get("skip_reason"))


def _scheduler_tick_once_worker_summary(worker_execution: Any) -> dict[str, Any]:
    if hasattr(worker_execution, "to_summary"):
        summary = worker_execution.to_summary()
    elif isinstance(worker_execution, Mapping):
        summary = dict(worker_execution)
    else:
        summary = {"status": str(worker_execution)}
    return deepcopy(summary)


def _scheduler_tick_once_worker_failed(
    worker_result: Mapping[str, Any] | None,
) -> bool:
    return isinstance(worker_result, Mapping) and worker_result.get("status") == "FAILED"


def _scheduler_tick_once_history_written(
    worker_result: Mapping[str, Any] | None,
) -> bool:
    if not isinstance(worker_result, Mapping):
        return False
    handler_result = worker_result.get("handler_result")
    if not isinstance(handler_result, Mapping):
        return False
    history = handler_result.get("history")
    return isinstance(history, Mapping) and history.get("history_written") is True


def _scheduler_tick_once_metadata(
    *,
    lease_decision: Mapping[str, Any],
    lease_release: Mapping[str, Any] | None,
    enqueue_result: Mapping[str, Any] | None,
    worker_result: Mapping[str, Any] | None,
) -> dict[str, bool]:
    return {
        "metadata_only": True,
        "lease_acquired_before_tick": lease_decision.get("lease_acquired") is True,
        "lease_released": lease_release is not None,
        "job_enqueued": (
            isinstance(enqueue_result, Mapping)
            and enqueue_result.get("job_enqueued") is True
        ),
        "admission_performed": (
            isinstance(enqueue_result, Mapping)
            and enqueue_result.get("admission_performed") is True
        ),
        "worker_executed": worker_result is not None,
        "history_write_executed": _scheduler_tick_once_history_written(worker_result),
        "daemon_auto_start_allowed": False,
        "scheduler_daemon_started": False,
        "continuous_loop_started": False,
        "physical_delete_automation_enabled": False,
        "dry_run": True,
    }


def _scheduler_tick_once_guardrails(*, lease_released: bool) -> dict[str, bool]:
    return {
        "manual_once_runner": True,
        "lease_required_before_tick": True,
        "lease_released_after_tick": lease_released,
        "daemon_auto_start_allowed": False,
        "scheduler_daemon_started": False,
        "continuous_loop_started": False,
        "physical_delete_automation_enabled": False,
    }


def _scheduler_tick_once_result_id(
    *,
    scheduler_id: str,
    lease_decision: Mapping[str, Any],
    run_at: str,
) -> str:
    basis = {
        "scheduler_id": scheduler_id,
        "lease_owner_id": lease_decision["lease_owner_id"],
        "lease_token": lease_decision.get("lease_token"),
        "idempotency_key": lease_decision.get("idempotency_key"),
        "run_at": run_at,
    }
    return str(
        uuid5(
            NAMESPACE_URL,
            f"ae-artifact-retention-scheduler-tick-once:{sha256_json(basis)}",
        )
    )


@dataclass
class ArtifactRetentionSchedulerLeaseStore:
    records: dict[str, dict[str, Any]] = field(default_factory=dict)

    def ensure_available(self) -> None:
        return None

    def get(self, scheduler_id: str) -> dict[str, Any] | None:
        normalized_scheduler_id = _required_text(
            scheduler_id,
            "scheduler_id",
            "ae.artifact_retention_scheduler_lease_store_invalid",
        )
        record = self.records.get(normalized_scheduler_id)
        return deepcopy(record) if record is not None else None

    def acquire(self, request: Mapping[str, Any]) -> dict[str, Any]:
        validated_request = validate_artifact_retention_scheduler_lease_request(request)
        current = self.records.get(validated_request["scheduler_id"])
        if current is not None and _lease_matches_request(current, validated_request):
            return build_artifact_retention_scheduler_lease_decision(
                validated_request,
                lease_record=current,
            )
        if current is not None and _lease_blocks_acquisition(
            current,
            requested_at=validated_request["requested_at"],
        ):
            return build_artifact_retention_scheduler_lease_decision(
                validated_request,
                blocking_lease=current,
            )
        record = build_artifact_retention_scheduler_lease_record(
            validated_request,
            fencing_token=_next_fencing_token(current),
            acquired_at=validated_request["requested_at"],
            last_observed_at=validated_request["requested_at"],
        )
        self.records[validated_request["scheduler_id"]] = deepcopy(record)
        return build_artifact_retention_scheduler_lease_decision(
            validated_request,
            lease_record=record,
        )

    def release(
        self,
        *,
        scheduler_id: str,
        lease_token: str,
        released_at: str | None = None,
    ) -> dict[str, Any]:
        normalized_scheduler_id = _required_text(
            scheduler_id,
            "scheduler_id",
            "ae.artifact_retention_scheduler_lease_store_invalid",
        )
        current = self.records.get(normalized_scheduler_id)
        if current is None:
            raise ArtifactHandoffError(
                status_code=404,
                error_code="ae.artifact_retention_scheduler_lease_not_found",
                detail="Artifact retention scheduler lease was not found.",
            )
        released = release_artifact_retention_scheduler_lease(
            current,
            lease_token=lease_token,
            released_at=released_at,
        )
        self.records[normalized_scheduler_id] = deepcopy(released)
        return released


class SqlAlchemyArtifactRetentionSchedulerLeaseStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def ensure_available(self) -> None:
        try:
            with self._session_factory() as session:
                session.execute(
                    text("SELECT 1 FROM ae_artifact_retention_scheduler_leases LIMIT 1")
                )
        except SQLAlchemyError as exc:
            raise _lease_store_unavailable() from exc

    def get(self, scheduler_id: str) -> dict[str, Any] | None:
        normalized_scheduler_id = _required_text(
            scheduler_id,
            "scheduler_id",
            "ae.artifact_retention_scheduler_lease_store_invalid",
        )
        try:
            with self._session_factory() as session:
                return _select_scheduler_lease(
                    session,
                    scheduler_id=normalized_scheduler_id,
                )
        except SQLAlchemyError as exc:
            raise _lease_store_unavailable() from exc

    def acquire(self, request: Mapping[str, Any]) -> dict[str, Any]:
        validated_request = validate_artifact_retention_scheduler_lease_request(request)
        try:
            with self._session_factory() as session:
                current = _select_scheduler_lease(
                    session,
                    scheduler_id=validated_request["scheduler_id"],
                    for_update=True,
                )
                if current is not None and _lease_matches_request(
                    current,
                    validated_request,
                ):
                    session.commit()
                    return build_artifact_retention_scheduler_lease_decision(
                        validated_request,
                        lease_record=current,
                    )
                if current is not None and _lease_blocks_acquisition(
                    current,
                    requested_at=validated_request["requested_at"],
                ):
                    session.commit()
                    return build_artifact_retention_scheduler_lease_decision(
                        validated_request,
                        blocking_lease=current,
                    )
                record = build_artifact_retention_scheduler_lease_record(
                    validated_request,
                    fencing_token=_next_fencing_token(current),
                    acquired_at=validated_request["requested_at"],
                    last_observed_at=validated_request["requested_at"],
                )
                _upsert_scheduler_lease(session, record)
                session.commit()
                stored = _select_scheduler_lease(
                    session,
                    scheduler_id=validated_request["scheduler_id"],
                )
                if stored is None:
                    raise ArtifactHandoffError(
                        status_code=503,
                        error_code=(
                            "ae.artifact_retention_scheduler_lease_store_unavailable"
                        ),
                        detail="AE artifact retention scheduler lease store is unavailable.",
                        retryable=True,
                    )
                return build_artifact_retention_scheduler_lease_decision(
                    validated_request,
                    lease_record=stored,
                )
        except ArtifactHandoffError:
            raise
        except SQLAlchemyError as exc:
            raise _lease_store_unavailable() from exc

    def release(
        self,
        *,
        scheduler_id: str,
        lease_token: str,
        released_at: str | None = None,
    ) -> dict[str, Any]:
        normalized_scheduler_id = _required_text(
            scheduler_id,
            "scheduler_id",
            "ae.artifact_retention_scheduler_lease_store_invalid",
        )
        try:
            with self._session_factory() as session:
                current = _select_scheduler_lease(
                    session,
                    scheduler_id=normalized_scheduler_id,
                    for_update=True,
                )
                if current is None:
                    raise ArtifactHandoffError(
                        status_code=404,
                        error_code="ae.artifact_retention_scheduler_lease_not_found",
                        detail="Artifact retention scheduler lease was not found.",
                    )
                released = release_artifact_retention_scheduler_lease(
                    current,
                    lease_token=lease_token,
                    released_at=released_at,
                )
                _upsert_scheduler_lease(session, released)
                session.commit()
                stored = _select_scheduler_lease(
                    session,
                    scheduler_id=normalized_scheduler_id,
                )
                return released if stored is None else stored
        except ArtifactHandoffError:
            raise
        except SQLAlchemyError as exc:
            raise _lease_store_unavailable() from exc


DEFAULT_ARTIFACT_RETENTION_SCHEDULER_LEASE_STORE = (
    ArtifactRetentionSchedulerLeaseStore()
)


def build_default_artifact_retention_scheduler_lease_store(app: Any) -> Any:
    persistence = getattr(app.state, "nex_persistence", None)
    session_factory = getattr(persistence, "api_session_factory", None)
    if session_factory is not None:
        return SqlAlchemyArtifactRetentionSchedulerLeaseStore(session_factory)
    return DEFAULT_ARTIFACT_RETENTION_SCHEDULER_LEASE_STORE


def artifact_retention_scheduler_lease_table_sql(dialect_name: str) -> str:
    timestamp_type = "TIMESTAMPTZ" if dialect_name == "postgresql" else "TEXT"
    json_type = "JSONB" if dialect_name == "postgresql" else "TEXT"
    json_default = "'{}'::jsonb" if dialect_name == "postgresql" else "'{}'"
    json_object_check = (
        "CHECK (jsonb_typeof({field}) = 'object')"
        if dialect_name == "postgresql"
        else ""
    )
    return f"""
        CREATE TABLE IF NOT EXISTS ae_artifact_retention_scheduler_leases (
            scheduler_id TEXT PRIMARY KEY,
            lease_record_id TEXT NOT NULL,
            lease_record_schema_version TEXT NOT NULL
                DEFAULT '{AE_ARTIFACT_RETENTION_SCHEDULER_LEASE_RECORD_SCHEMA_VERSION}'
                CHECK (
                    lease_record_schema_version =
                    '{AE_ARTIFACT_RETENTION_SCHEDULER_LEASE_RECORD_SCHEMA_VERSION}'
                ),
            service_id TEXT NOT NULL DEFAULT 'nex-ae-api'
                CHECK (service_id = 'nex-ae-api'),
            lease_owner_id TEXT NOT NULL,
            lease_token TEXT NOT NULL,
            lease_status TEXT NOT NULL
                CHECK (lease_status IN ('HELD', 'RELEASED', 'EXPIRED')),
            fencing_token INTEGER NOT NULL CHECK (fencing_token >= 1),
            acquired_at {timestamp_type} NOT NULL,
            expires_at {timestamp_type} NOT NULL,
            released_at {timestamp_type},
            last_observed_at {timestamp_type} NOT NULL,
            operation TEXT NOT NULL CHECK (operation IN ('manual_tick_once')),
            tick_id TEXT,
            idempotency_key TEXT NOT NULL,
            guardrails {json_type} NOT NULL DEFAULT {json_default}
                {json_object_check.format(field='guardrails')},
            metadata {json_type} NOT NULL DEFAULT {json_default}
                {json_object_check.format(field='metadata')},
            updated_at {timestamp_type} NOT NULL
        )
    """


def _select_scheduler_lease(
    session: Session,
    *,
    scheduler_id: str,
    for_update: bool = False,
) -> dict[str, Any] | None:
    dialect_name = _dialect_name(session)
    lock_sql = " FOR UPDATE" if for_update and dialect_name == "postgresql" else ""
    row = (
        session.execute(
            text(
                f"""
                SELECT
                    scheduler_id,
                    lease_record_id,
                    lease_record_schema_version,
                    service_id,
                    lease_owner_id,
                    lease_token,
                    lease_status,
                    fencing_token,
                    acquired_at,
                    expires_at,
                    released_at,
                    last_observed_at,
                    operation,
                    tick_id,
                    idempotency_key,
                    guardrails,
                    metadata,
                    updated_at
                FROM ae_artifact_retention_scheduler_leases
                WHERE scheduler_id = :scheduler_id
                {lock_sql}
                """
            ),
            {"scheduler_id": scheduler_id},
        )
        .mappings()
        .first()
    )
    return _scheduler_lease_from_row(row) if row is not None else None


def _upsert_scheduler_lease(session: Session, record: Mapping[str, Any]) -> None:
    validated = validate_artifact_retention_scheduler_lease_record(record)
    dialect_name = _dialect_name(session)
    session.execute(
        text(_scheduler_lease_upsert_sql(dialect_name)),
        _scheduler_lease_params(validated),
    )


def _scheduler_lease_upsert_sql(dialect_name: str) -> str:
    guardrails_expr = _json_sql_expression(dialect_name, "guardrails")
    metadata_expr = _json_sql_expression(dialect_name, "metadata")
    return f"""
        INSERT INTO ae_artifact_retention_scheduler_leases (
            scheduler_id,
            lease_record_id,
            lease_record_schema_version,
            service_id,
            lease_owner_id,
            lease_token,
            lease_status,
            fencing_token,
            acquired_at,
            expires_at,
            released_at,
            last_observed_at,
            operation,
            tick_id,
            idempotency_key,
            guardrails,
            metadata,
            updated_at
        )
        VALUES (
            :scheduler_id,
            :lease_record_id,
            :lease_record_schema_version,
            :service_id,
            :lease_owner_id,
            :lease_token,
            :lease_status,
            :fencing_token,
            :acquired_at,
            :expires_at,
            :released_at,
            :last_observed_at,
            :operation,
            :tick_id,
            :idempotency_key,
            {guardrails_expr},
            {metadata_expr},
            :updated_at
        )
        ON CONFLICT (scheduler_id) DO UPDATE SET
            lease_record_id = excluded.lease_record_id,
            lease_record_schema_version = excluded.lease_record_schema_version,
            service_id = excluded.service_id,
            lease_owner_id = excluded.lease_owner_id,
            lease_token = excluded.lease_token,
            lease_status = excluded.lease_status,
            fencing_token = excluded.fencing_token,
            acquired_at = excluded.acquired_at,
            expires_at = excluded.expires_at,
            released_at = excluded.released_at,
            last_observed_at = excluded.last_observed_at,
            operation = excluded.operation,
            tick_id = excluded.tick_id,
            idempotency_key = excluded.idempotency_key,
            guardrails = excluded.guardrails,
            metadata = excluded.metadata,
            updated_at = excluded.updated_at
    """


def _scheduler_lease_params(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "scheduler_id": record["scheduler_id"],
        "lease_record_id": record["lease_record_id"],
        "lease_record_schema_version": record["lease_record_schema_version"],
        "service_id": record["service_id"],
        "lease_owner_id": record["lease_owner_id"],
        "lease_token": record["lease_token"],
        "lease_status": record["lease_status"],
        "fencing_token": record["fencing_token"],
        "acquired_at": record["acquired_at"],
        "expires_at": record["expires_at"],
        "released_at": record["released_at"],
        "last_observed_at": record["last_observed_at"],
        "operation": record["operation"],
        "tick_id": record["tick_id"],
        "idempotency_key": record["idempotency_key"],
        "guardrails": json.dumps(record["guardrails"]),
        "metadata": json.dumps(record["metadata"]),
        "updated_at": record["last_observed_at"],
    }


def _scheduler_lease_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    data = dict(row)
    record = {
        "lease_record_schema_version": data["lease_record_schema_version"],
        "lease_record_id": data["lease_record_id"],
        "service_id": data["service_id"],
        "scheduler_id": data["scheduler_id"],
        "lease_owner_id": data["lease_owner_id"],
        "lease_token": data["lease_token"],
        "lease_status": data["lease_status"],
        "fencing_token": data["fencing_token"],
        "acquired_at": _datetime_value(data["acquired_at"]),
        "expires_at": _datetime_value(data["expires_at"]),
        "released_at": _datetime_value(data["released_at"]),
        "last_observed_at": _datetime_value(data["last_observed_at"]),
        "operation": data["operation"],
        "tick_id": data["tick_id"],
        "idempotency_key": data["idempotency_key"],
        "guardrails": _json_value(data["guardrails"], {}),
        "metadata": _json_value(data["metadata"], {}),
    }
    return validate_artifact_retention_scheduler_lease_record(record)


def _lease_matches_request(
    record: Mapping[str, Any],
    request: Mapping[str, Any],
) -> bool:
    validated_record = validate_artifact_retention_scheduler_lease_record(record)
    return (
        validated_record["lease_status"] == "HELD"
        and validated_record["scheduler_id"] == request["scheduler_id"]
        and validated_record["lease_owner_id"] == request["lease_owner_id"]
        and validated_record["operation"] == request["operation"]
        and validated_record["idempotency_key"] == request["idempotency_key"]
    )


def _lease_blocks_acquisition(
    record: Mapping[str, Any],
    *,
    requested_at: str,
) -> bool:
    validated_record = validate_artifact_retention_scheduler_lease_record(record)
    if validated_record["lease_status"] != "HELD":
        return False
    expires_at = parse_artifact_retention_timestamp(
        validated_record["expires_at"],
        field_name="expires_at",
    )
    requested_dt = parse_artifact_retention_timestamp(
        requested_at,
        field_name="requested_at",
    )
    return expires_at > requested_dt


def _next_fencing_token(record: Mapping[str, Any] | None) -> int:
    if record is None:
        return 1
    return validate_artifact_retention_scheduler_lease_record(record)["fencing_token"] + 1


def _json_sql_expression(dialect_name: str, field_name: str) -> str:
    if dialect_name == "postgresql":
        return f"CAST(:{field_name} AS JSONB)"
    return f":{field_name}"


def _json_value(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, Mapping):
        return deepcopy(dict(value))
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return fallback
        return decoded if decoded is not None else fallback
    return fallback


def _datetime_value(value: Any) -> str | None:
    if value is None:
        return None
    return format_artifact_retention_timestamp(
        parse_artifact_retention_timestamp(str(value), field_name="timestamp")
    )


def _dialect_name(session: Session) -> str:
    bind = session.get_bind()
    return bind.dialect.name if bind is not None else ""


def _lease_store_unavailable() -> ArtifactHandoffError:
    return ArtifactHandoffError(
        status_code=503,
        error_code="ae.artifact_retention_scheduler_lease_store_unavailable",
        detail="AE artifact retention scheduler lease store is unavailable.",
        retryable=True,
    )


def normalize_artifact_retention_scheduler_lease_operation(value: Any) -> str:
    normalized = optional_text(value)
    if normalized is None or normalized not in ARTIFACT_RETENTION_SCHEDULER_LEASE_OPERATIONS:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_operation_invalid",
            detail="Artifact retention scheduler lease operation is invalid.",
        )
    return normalized


def normalize_artifact_retention_scheduler_lease_record_status(value: Any) -> str:
    normalized = optional_text(value)
    if normalized is None:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_record_status_invalid",
            detail="Artifact retention scheduler lease status is required.",
        )
    normalized = normalized.upper()
    if normalized not in ARTIFACT_RETENTION_SCHEDULER_LEASE_RECORD_STATUSES:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_record_status_invalid",
            detail="Artifact retention scheduler lease status is invalid.",
        )
    return normalized


def normalize_artifact_retention_scheduler_lease_ttl_seconds(
    value: int | str | None,
) -> int:
    if value is None:
        return ARTIFACT_RETENTION_SCHEDULER_TICK_LOCK_TTL_SECONDS
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_ttl_invalid",
            detail="Artifact retention scheduler lease TTL must be an integer.",
        ) from exc
    if (
        normalized < MIN_ARTIFACT_RETENTION_SCHEDULER_LEASE_TTL_SECONDS
        or normalized > MAX_ARTIFACT_RETENTION_SCHEDULER_LEASE_TTL_SECONDS
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_ttl_invalid",
            detail="Artifact retention scheduler lease TTL is outside the supported range.",
        )
    return normalized


def artifact_retention_scheduler_lease_idempotency_key(
    *,
    scheduler_id: str,
    lease_owner_id: str,
    operation: str,
    requested_at: str,
) -> str:
    basis = {
        "scheduler_id": scheduler_id,
        "lease_owner_id": lease_owner_id,
        "operation": operation,
        "requested_at": requested_at,
    }
    return f"ae-artifact-retention-scheduler-lease:{sha256_json(basis)}"


def normalize_artifact_retention_scheduler_daemon_control_action(value: Any) -> str:
    normalized = optional_text(value)
    if normalized is None:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_control_action_invalid",
            detail="Artifact retention scheduler daemon control action is required.",
        )
    normalized = normalized.lower()
    if normalized not in ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONTROL_ACTIONS:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_control_action_invalid",
            detail="Artifact retention scheduler daemon control action is invalid.",
        )
    return normalized


def _normalize_scheduler_daemon_runtime_profile(value: Any) -> str:
    normalized = optional_text(value)
    if normalized is None:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            detail="Artifact retention scheduler daemon runtime profile is required.",
        )
    normalized = normalized.lower()
    if normalized not in ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUNTIME_PROFILES:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            detail="Artifact retention scheduler daemon runtime profile is invalid.",
        )
    return normalized


def _scheduler_daemon_runtime_enablement_status(
    *,
    enabled: bool,
    explicit_opt_in: bool,
) -> tuple[str, str | None]:
    if not enabled:
        return "DISABLED", None
    if not explicit_opt_in:
        return "BLOCKED", "explicit_opt_in_required"
    return "READY", None


def _validate_scheduler_daemon_runtime_enablement(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            detail="Artifact retention scheduler daemon runtime enablement is required.",
        )
    enablement = dict(value)
    if set(enablement) != {
        "profile",
        "enabled",
        "explicit_opt_in",
        "enablement_status",
        "block_reason",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            detail="Artifact retention scheduler daemon runtime enablement keys are invalid.",
        )
    profile = _normalize_scheduler_daemon_runtime_profile(enablement.get("profile"))
    enabled = _required_bool(
        enablement.get("enabled"),
        "enabled",
        "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
    )
    explicit_opt_in = _required_bool(
        enablement.get("explicit_opt_in"),
        "explicit_opt_in",
        "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
    )
    status = enablement.get("enablement_status")
    if status not in ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUNTIME_ENABLEMENT_STATUSES:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            detail="Artifact retention scheduler daemon runtime status is invalid.",
        )
    block_reason = enablement.get("block_reason")
    if (
        block_reason is not None
        and block_reason
        not in ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUNTIME_BLOCK_REASONS
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            detail="Artifact retention scheduler daemon runtime block reason is invalid.",
        )
    expected_status, expected_reason = _scheduler_daemon_runtime_enablement_status(
        enabled=enabled,
        explicit_opt_in=explicit_opt_in,
    )
    if status != expected_status or block_reason != expected_reason:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            detail="Artifact retention scheduler daemon runtime enablement decision is invalid.",
        )
    return {
        "profile": profile,
        "enabled": enabled,
        "explicit_opt_in": explicit_opt_in,
        "enablement_status": status,
        "block_reason": block_reason,
    }


def _validate_scheduler_daemon_runtime_timing(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            detail="Artifact retention scheduler daemon runtime timing is required.",
        )
    timing = dict(value)
    if set(timing) != {"interval_seconds", "jitter_seconds", "backoff_seconds"}:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            detail="Artifact retention scheduler daemon runtime timing keys are invalid.",
        )
    interval_seconds = _bounded_positive_int(
        timing.get("interval_seconds"),
        "interval_seconds",
        "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
        max_value=MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_INTERVAL_SECONDS,
    )
    jitter_seconds = _non_negative_int(
        timing.get("jitter_seconds"),
        "jitter_seconds",
        "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
    )
    if jitter_seconds > interval_seconds:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            detail="Artifact retention scheduler daemon jitter cannot exceed interval.",
        )
    backoff_seconds = _bounded_positive_int(
        timing.get("backoff_seconds"),
        "backoff_seconds",
        "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
        max_value=MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_BACKOFF_SECONDS,
    )
    return {
        "interval_seconds": interval_seconds,
        "jitter_seconds": jitter_seconds,
        "backoff_seconds": backoff_seconds,
    }


def _validate_scheduler_daemon_runtime_enablement_runtime(
    value: Any,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            detail="Artifact retention scheduler daemon runtime section is required.",
        )
    runtime = dict(value)
    if set(runtime) != {
        "scheduler_tick_admission_enabled",
        "operator_dispatch_admission_enabled",
        "default_execution_mode",
        "job_queue_available",
        "job_queue_backend",
        "worker_runner_available",
        "physical_delete_automation_enabled",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            detail="Artifact retention scheduler daemon runtime section keys are invalid.",
        )
    for field_name in (
        "scheduler_tick_admission_enabled",
        "operator_dispatch_admission_enabled",
        "job_queue_available",
        "worker_runner_available",
    ):
        runtime[field_name] = _required_bool(
            runtime.get(field_name),
            field_name,
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
        )
    if runtime.get("default_execution_mode") != "DRY_RUN":
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            detail="Artifact retention scheduler daemon runtime mode is invalid.",
        )
    _required_text(
        runtime.get("job_queue_backend"),
        "job_queue_backend",
        "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
    )
    if runtime.get("physical_delete_automation_enabled") is not False:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            detail="Artifact retention scheduler daemon physical delete automation is invalid.",
        )
    return runtime


def _validate_scheduler_daemon_runtime_loop_policy(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            detail="Artifact retention scheduler daemon loop policy is required.",
        )
    loop_policy = dict(value)
    if set(loop_policy) != {
        "one_cycle_runner_required_before_loop",
        "max_ticks_per_run",
        "daemon_auto_start_allowed",
        "scheduler_daemon_started",
        "continuous_loop_enabled",
        "continuous_loop_started",
        "start_control_enabled",
        "stop_control_enabled",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            detail="Artifact retention scheduler daemon loop policy keys are invalid.",
        )
    if loop_policy.get("one_cycle_runner_required_before_loop") is not True:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            detail="Artifact retention scheduler daemon loop policy is invalid.",
        )
    for field_name in (
        "daemon_auto_start_allowed",
        "scheduler_daemon_started",
        "continuous_loop_enabled",
        "continuous_loop_started",
        "start_control_enabled",
        "stop_control_enabled",
    ):
        if loop_policy.get(field_name) is not False:
            raise ArtifactHandoffError(
                status_code=422,
                error_code="ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
                detail="Artifact retention scheduler daemon loop policy is invalid.",
            )
    loop_policy["max_ticks_per_run"] = _bounded_positive_int(
        loop_policy.get("max_ticks_per_run"),
        "max_ticks_per_run",
        "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
        max_value=MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_MAX_TICKS_PER_RUN,
    )
    return loop_policy


def _validate_scheduler_daemon_runtime_lease_policy(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            detail="Artifact retention scheduler daemon lease policy is required.",
        )
    lease_policy = dict(value)
    if set(lease_policy) != {
        "lease_required_before_tick",
        "fencing_token_required",
        "lease_repository_required",
        "lease_ttl_seconds",
        "stale_after_seconds",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            detail="Artifact retention scheduler daemon lease policy keys are invalid.",
        )
    for field_name in (
        "lease_required_before_tick",
        "fencing_token_required",
        "lease_repository_required",
    ):
        if lease_policy.get(field_name) is not True:
            raise ArtifactHandoffError(
                status_code=422,
                error_code="ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
                detail="Artifact retention scheduler daemon lease policy is invalid.",
            )
    lease_ttl_seconds = normalize_artifact_retention_scheduler_lease_ttl_seconds(
        lease_policy.get("lease_ttl_seconds")
    )
    stale_after_seconds = _positive_int(
        lease_policy.get("stale_after_seconds"),
        "stale_after_seconds",
        "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
    )
    if stale_after_seconds < lease_ttl_seconds:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            detail="Artifact retention scheduler daemon stale window is invalid.",
        )
    return {
        "lease_required_before_tick": True,
        "fencing_token_required": True,
        "lease_repository_required": True,
        "lease_ttl_seconds": lease_ttl_seconds,
        "stale_after_seconds": stale_after_seconds,
    }


def _validate_scheduler_daemon_runtime_batch_window(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            detail="Artifact retention scheduler daemon batch window is required.",
        )
    batch_window = dict(value)
    if set(batch_window) != {"timezone", "start_local_time", "end_local_time"}:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            detail="Artifact retention scheduler daemon batch window keys are invalid.",
        )
    return {
        "timezone": _required_text(
            batch_window.get("timezone"),
            "timezone",
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
        ),
        "start_local_time": _required_text(
            batch_window.get("start_local_time"),
            "start_local_time",
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
        ),
        "end_local_time": _required_text(
            batch_window.get("end_local_time"),
            "end_local_time",
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
        ),
    }


def _ensure_scheduler_daemon_runtime_scope(
    *,
    runtime_config: Mapping[str, Any],
    daemon_config: Mapping[str, Any],
) -> None:
    if (
        runtime_config.get("service_id") != daemon_config.get("service_id")
        or runtime_config.get("scheduler_id") != daemon_config.get("scheduler_id")
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_loop_plan_invalid",
            detail="Artifact retention scheduler daemon loop plan scope is invalid.",
        )


def _scheduler_daemon_runtime_in_batch_window(
    *,
    requested_at: str,
    runtime_config: Mapping[str, Any],
) -> bool:
    batch_window = _validate_scheduler_daemon_runtime_batch_window(
        runtime_config.get("batch_window")
    )
    requested_dt = parse_artifact_retention_timestamp(
        requested_at,
        field_name="requested_at",
    )
    try:
        local_dt = requested_dt.astimezone(ZoneInfo(batch_window["timezone"]))
    except ZoneInfoNotFoundError as exc:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_loop_plan_invalid",
            detail="Artifact retention scheduler daemon batch window timezone is invalid.",
        ) from exc
    start = _scheduler_daemon_runtime_local_time(batch_window["start_local_time"])
    end = _scheduler_daemon_runtime_local_time(batch_window["end_local_time"])
    return start <= local_dt.time() < end


def _scheduler_daemon_runtime_local_time(value: str) -> time:
    try:
        hour_text, minute_text = value.split(":", 1)
        parsed = time(hour=int(hour_text), minute=int(minute_text))
    except (TypeError, ValueError) as exc:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_loop_plan_invalid",
            detail="Artifact retention scheduler daemon batch window time is invalid.",
        ) from exc
    return parsed


def _scheduler_daemon_loop_plan_decision(
    *,
    runtime_config: Mapping[str, Any],
    daemon_config: Mapping[str, Any],
    in_batch_window: bool,
    stop_requested: bool,
) -> tuple[str, str | None]:
    enablement = runtime_config["enablement"]
    runtime = runtime_config["runtime"]
    lease_repository = daemon_config["lease_repository"]
    if stop_requested:
        return "NOOP", "stop_requested"
    if enablement["enablement_status"] == "DISABLED":
        return "DISABLED", "runtime_disabled"
    if enablement["enablement_status"] == "BLOCKED":
        return "BLOCKED", enablement["block_reason"]
    if runtime["scheduler_tick_admission_enabled"] is not True:
        return "BLOCKED", "scheduler_tick_admission_disabled"
    if runtime["operator_dispatch_admission_enabled"] is not True:
        return "BLOCKED", "operator_dispatch_admission_disabled"
    if lease_repository["available"] is not True:
        return "BLOCKED", "lease_repository_unavailable"
    if runtime["job_queue_available"] is not True:
        return "BLOCKED", "job_queue_unavailable"
    if not in_batch_window:
        return "BLOCKED", "outside_batch_window"
    return "READY", None


def _scheduler_daemon_loop_execution_plan(
    *,
    runtime_config: Mapping[str, Any],
    decision_status: str,
    in_batch_window: bool,
) -> dict[str, Any]:
    ready = decision_status == "READY"
    return {
        "pure_planning_only": True,
        "evaluates_batch_window": True,
        "in_batch_window": in_batch_window,
        "acquires_lease": ready,
        "runs_tick_once": ready,
        "dispatches_job_queue": ready,
        "max_ticks_this_run": (
            runtime_config["loop_policy"]["max_ticks_per_run"] if ready else 0
        ),
        "starts_daemon": False,
        "starts_continuous_loop": False,
        "writes_history": False,
        "physical_delete_enabled": False,
    }


def _scheduler_daemon_loop_plan_id(
    *,
    scheduler_id: str,
    requested_at: str,
    decision_status: str,
    decision_reason: str | None,
) -> str:
    basis = {
        "scheduler_id": scheduler_id,
        "requested_at": requested_at,
        "decision_status": decision_status,
        "decision_reason": decision_reason,
    }
    return str(
        uuid5(
            NAMESPACE_URL,
            f"ae-artifact-retention-scheduler-daemon-loop:{sha256_json(basis)}",
        )
    )


def _scheduler_daemon_checked_at(
    *,
    checked_at: str | None,
    scheduler_config: Mapping[str, Any],
) -> str:
    candidate = checked_at or scheduler_config.get("checked_at")
    return format_artifact_retention_timestamp(
        parse_artifact_retention_timestamp(
            candidate or "2026-09-01T00:00:00Z",
            field_name="checked_at",
        )
    )


def _optional_artifact_retention_timestamp(
    value: Any,
    *,
    field_name: str,
    error_code: str,
) -> str | None:
    del error_code
    normalized = optional_text(value)
    if normalized is None:
        return None
    return format_artifact_retention_timestamp(
        parse_artifact_retention_timestamp(
            normalized,
            field_name=field_name,
        )
    )


def _scheduler_daemon_runtime_config(runtime: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "scheduler_daemon_enabled": False,
        "scheduler_daemon_started": False,
        "daemon_auto_start_allowed": False,
        "continuous_loop_enabled": False,
        "continuous_loop_started": False,
        "manual_tick_once_enabled": True,
        "manual_tick_once_requires_lease": True,
        "scheduler_tick_admission_enabled": (
            runtime.get("scheduler_tick_admission_enabled") is True
        ),
        "operator_dispatch_admission_enabled": (
            runtime.get("operator_dispatch_admission_enabled") is True
        ),
        "default_execution_mode": runtime.get("default_execution_mode"),
        "job_queue_available": runtime.get("job_queue_available") is True,
        "job_queue_backend": runtime.get("job_queue_backend"),
        "scheduler_tick_interval_seconds": runtime.get(
            "scheduler_tick_interval_seconds"
        ),
        "scheduler_tick_jitter_seconds": runtime.get("scheduler_tick_jitter_seconds"),
        "scheduler_tick_lock_ttl_seconds": runtime.get(
            "scheduler_tick_lock_ttl_seconds"
        ),
        "scheduler_tick_stale_after_seconds": runtime.get(
            "scheduler_tick_stale_after_seconds"
        ),
        "scheduler_tick_max_jobs_per_tick": runtime.get(
            "scheduler_tick_max_jobs_per_tick"
        ),
        "scheduler_tick_batch_window_enforced": (
            runtime.get("scheduler_tick_batch_window_enforced") is True
        ),
        "scheduler_tick_timezone": runtime.get("scheduler_tick_timezone"),
        "scheduler_tick_window_start": runtime.get("scheduler_tick_window_start"),
        "scheduler_tick_window_end": runtime.get("scheduler_tick_window_end"),
    }


def _validate_scheduler_daemon_runtime_config(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_config_invalid",
            detail="Artifact retention scheduler daemon runtime is required.",
        )
    runtime = dict(value)
    expected_keys = {
        "scheduler_daemon_enabled",
        "scheduler_daemon_started",
        "daemon_auto_start_allowed",
        "continuous_loop_enabled",
        "continuous_loop_started",
        "manual_tick_once_enabled",
        "manual_tick_once_requires_lease",
        "scheduler_tick_admission_enabled",
        "operator_dispatch_admission_enabled",
        "default_execution_mode",
        "job_queue_available",
        "job_queue_backend",
        "scheduler_tick_interval_seconds",
        "scheduler_tick_jitter_seconds",
        "scheduler_tick_lock_ttl_seconds",
        "scheduler_tick_stale_after_seconds",
        "scheduler_tick_max_jobs_per_tick",
        "scheduler_tick_batch_window_enforced",
        "scheduler_tick_timezone",
        "scheduler_tick_window_start",
        "scheduler_tick_window_end",
    }
    if set(runtime) != expected_keys:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_config_invalid",
            detail="Artifact retention scheduler daemon runtime keys are invalid.",
        )
    expected_false = (
        "scheduler_daemon_enabled",
        "scheduler_daemon_started",
        "daemon_auto_start_allowed",
        "continuous_loop_enabled",
        "continuous_loop_started",
    )
    for field_name in expected_false:
        if runtime[field_name] is not False:
            raise ArtifactHandoffError(
                status_code=422,
                error_code="ae.artifact_retention_scheduler_daemon_config_invalid",
                detail="Artifact retention scheduler daemon runtime is invalid.",
            )
    expected_true = (
        "manual_tick_once_enabled",
        "manual_tick_once_requires_lease",
        "scheduler_tick_batch_window_enforced",
    )
    for field_name in expected_true:
        if runtime[field_name] is not True:
            raise ArtifactHandoffError(
                status_code=422,
                error_code="ae.artifact_retention_scheduler_daemon_config_invalid",
                detail="Artifact retention scheduler daemon runtime is invalid.",
            )
    for field_name in (
        "scheduler_tick_admission_enabled",
        "operator_dispatch_admission_enabled",
        "job_queue_available",
    ):
        if not isinstance(runtime[field_name], bool):
            raise ArtifactHandoffError(
                status_code=422,
                error_code="ae.artifact_retention_scheduler_daemon_config_invalid",
                detail="Artifact retention scheduler daemon runtime boolean is invalid.",
            )
    if runtime["default_execution_mode"] != "DRY_RUN":
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_config_invalid",
            detail="Artifact retention scheduler daemon runtime mode is invalid.",
        )
    for field_name in (
        "job_queue_backend",
        "scheduler_tick_timezone",
        "scheduler_tick_window_start",
        "scheduler_tick_window_end",
    ):
        _required_text(
            runtime.get(field_name),
            field_name,
            "ae.artifact_retention_scheduler_daemon_config_invalid",
        )
    for field_name in (
        "scheduler_tick_interval_seconds",
        "scheduler_tick_lock_ttl_seconds",
        "scheduler_tick_stale_after_seconds",
        "scheduler_tick_max_jobs_per_tick",
    ):
        runtime[field_name] = _positive_int(
            runtime.get(field_name),
            field_name,
            "ae.artifact_retention_scheduler_daemon_config_invalid",
        )
    try:
        runtime["scheduler_tick_jitter_seconds"] = int(
            runtime["scheduler_tick_jitter_seconds"]
        )
    except (TypeError, ValueError) as exc:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_config_invalid",
            detail="Artifact retention scheduler daemon jitter is invalid.",
        ) from exc
    if runtime["scheduler_tick_jitter_seconds"] < 0:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_config_invalid",
            detail="Artifact retention scheduler daemon jitter is invalid.",
        )
    return runtime


def _scheduler_daemon_lease_repository_summary(
    lease_store: Any | None,
) -> dict[str, Any]:
    try:
        active_store = _scheduler_tick_once_lease_store(lease_store)
    except ArtifactHandoffError as exc:
        return _scheduler_daemon_lease_repository_unavailable(
            lease_store,
            failure_code=exc.error_code,
        )
    try:
        active_store.ensure_available()
    except ArtifactHandoffError as exc:
        return _scheduler_daemon_lease_repository_unavailable(
            active_store,
            failure_code=exc.error_code,
        )
    return {
        "required": True,
        "available": True,
        "backend": _scheduler_daemon_lease_store_backend_name(
            active_store,
            default_used=lease_store is None,
        ),
        "lease_record_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_LEASE_RECORD_SCHEMA_VERSION
        ),
        "failure_code": None,
    }


def _scheduler_daemon_lease_repository_unavailable(
    lease_store: Any | None,
    *,
    failure_code: str,
) -> dict[str, Any]:
    return {
        "required": True,
        "available": False,
        "backend": _scheduler_daemon_lease_store_backend_name(
            lease_store,
            default_used=False,
        ),
        "lease_record_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_LEASE_RECORD_SCHEMA_VERSION
        ),
        "failure_code": failure_code,
    }


def _validate_scheduler_daemon_lease_repository(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_config_invalid",
            detail="Artifact retention scheduler daemon lease repository is required.",
        )
    lease_repository = dict(value)
    if set(lease_repository) != {
        "required",
        "available",
        "backend",
        "lease_record_schema_version",
        "failure_code",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_config_invalid",
            detail="Artifact retention scheduler daemon lease repository keys are invalid.",
        )
    if lease_repository["required"] is not True or not isinstance(
        lease_repository["available"],
        bool,
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_config_invalid",
            detail="Artifact retention scheduler daemon lease repository is invalid.",
        )
    _required_text(
        lease_repository.get("backend"),
        "backend",
        "ae.artifact_retention_scheduler_daemon_config_invalid",
    )
    if lease_repository["lease_record_schema_version"] != (
        AE_ARTIFACT_RETENTION_SCHEDULER_LEASE_RECORD_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_config_invalid",
            detail="Artifact retention scheduler daemon lease schema is invalid.",
        )
    if lease_repository["available"] and lease_repository.get("failure_code") is not None:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_config_invalid",
            detail="Available scheduler daemon lease repository cannot include failure.",
        )
    if not lease_repository["available"]:
        _required_text(
            lease_repository.get("failure_code"),
            "failure_code",
            "ae.artifact_retention_scheduler_daemon_config_invalid",
        )
    return lease_repository


def _scheduler_daemon_lease_store_backend_name(
    lease_store: Any | None,
    *,
    default_used: bool,
) -> str:
    if default_used:
        return "in_memory_default"
    if lease_store is None:
        return "not_configured"
    if isinstance(lease_store, SqlAlchemyArtifactRetentionSchedulerLeaseStore):
        return "sqlalchemy"
    if isinstance(lease_store, ArtifactRetentionSchedulerLeaseStore):
        return "in_memory"
    return lease_store.__class__.__name__


def _scheduler_daemon_supported_actions(
    *,
    runtime: Mapping[str, Any],
    lease_repository: Mapping[str, Any],
) -> list[dict[str, Any]]:
    manual_status, manual_block_reason = _scheduler_daemon_manual_tick_decision(
        runtime=runtime,
        lease_repository=lease_repository,
    )
    manual_runs_tick = manual_status == "READY"
    return [
        {
            "action": ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONTROL_ACTION_STATUS_PROBE,
            "decision_status": "NOOP",
            "requires_lease": False,
            "runs_tick_once": False,
            "starts_daemon": False,
            "starts_continuous_loop": False,
            "block_reason": None,
        },
        {
            "action": ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONTROL_ACTION_MANUAL_TICK_ONCE,
            "decision_status": manual_status,
            "requires_lease": True,
            "runs_tick_once": manual_runs_tick,
            "starts_daemon": False,
            "starts_continuous_loop": False,
            "block_reason": manual_block_reason,
        },
        {
            "action": ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONTROL_ACTION_START_DAEMON,
            "decision_status": "BLOCKED",
            "requires_lease": False,
            "runs_tick_once": False,
            "starts_daemon": False,
            "starts_continuous_loop": False,
            "block_reason": "daemon_disabled_by_policy",
        },
        {
            "action": ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONTROL_ACTION_STOP_DAEMON,
            "decision_status": "NOOP",
            "requires_lease": False,
            "runs_tick_once": False,
            "starts_daemon": False,
            "starts_continuous_loop": False,
            "block_reason": None,
        },
    ]


def _scheduler_daemon_manual_tick_decision(
    *,
    runtime: Mapping[str, Any],
    lease_repository: Mapping[str, Any],
) -> tuple[str, str | None]:
    if runtime.get("operator_dispatch_admission_enabled") is not True:
        return "BLOCKED", "operator_dispatch_admission_disabled"
    if runtime.get("scheduler_tick_admission_enabled") is not True:
        return "BLOCKED", "scheduler_tick_admission_disabled"
    if lease_repository.get("available") is not True:
        return "BLOCKED", "lease_repository_unavailable"
    if runtime.get("job_queue_available") is not True:
        return "BLOCKED", "job_queue_unavailable"
    return "READY", None


def _scheduler_daemon_action_item(
    daemon_config: Mapping[str, Any],
    action: str,
) -> dict[str, Any]:
    normalized_action = normalize_artifact_retention_scheduler_daemon_control_action(
        action
    )
    actions = daemon_config.get("supported_actions")
    if not isinstance(actions, list):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_config_invalid",
            detail="Artifact retention scheduler daemon supported actions are required.",
        )
    for item in actions:
        if isinstance(item, Mapping) and item.get("action") == normalized_action:
            return dict(item)
    raise ArtifactHandoffError(
        status_code=422,
        error_code="ae.artifact_retention_scheduler_daemon_control_action_invalid",
        detail="Artifact retention scheduler daemon control action is unsupported.",
    )


def _scheduler_daemon_control_execution_plan(
    action_item: Mapping[str, Any],
) -> dict[str, Any]:
    runs_tick_once = action_item.get("runs_tick_once") is True
    return {
        "requires_lease": action_item.get("requires_lease") is True,
        "runs_tick_once": runs_tick_once,
        "dispatches_job_queue": runs_tick_once,
        "starts_daemon": False,
        "starts_continuous_loop": False,
        "writes_history": False,
        "physical_delete_enabled": False,
    }


def _scheduler_daemon_requested_by(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {"actor_type": "service", "actor_id": "nex-ae-api"}
    if not isinstance(value, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_control_plan_invalid",
            detail="Artifact retention scheduler daemon control requested_by is invalid.",
        )
    actor_type = _required_text(
        value.get("actor_type"),
        "actor_type",
        "ae.artifact_retention_scheduler_daemon_control_plan_invalid",
    )
    actor_id = _required_text(
        value.get("actor_id"),
        "actor_id",
        "ae.artifact_retention_scheduler_daemon_control_plan_invalid",
    )
    requested_by = {"actor_type": actor_type, "actor_id": actor_id}
    for field_name in ("tenant_id", "workspace_id", "request_id"):
        field_value = optional_text(value.get(field_name))
        if field_value is not None:
            requested_by[field_name] = field_value
    return requested_by


def _scheduler_daemon_control_plan_id(
    *,
    scheduler_id: str,
    action: str,
    requested_at: str,
) -> str:
    basis = {
        "scheduler_id": scheduler_id,
        "action": action,
        "requested_at": requested_at,
    }
    return str(
        uuid5(
            NAMESPACE_URL,
            f"ae-artifact-retention-scheduler-daemon-control:{sha256_json(basis)}",
        )
    )


def _build_artifact_retention_scheduler_daemon_dispatch_result(
    *,
    control_plan: Mapping[str, Any],
    tick_once_result: Mapping[str, Any] | None,
    start_stop_guardrail: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    validated_control = validate_artifact_retention_scheduler_daemon_control_plan(
        control_plan
    )
    validated_tick = (
        validate_artifact_retention_scheduler_tick_once_result(tick_once_result)
        if tick_once_result is not None
        else None
    )
    validated_start_stop = (
        validate_artifact_retention_scheduler_daemon_start_stop_guardrail(
            start_stop_guardrail
        )
        if start_stop_guardrail is not None
        else None
    )
    dispatch_status = (
        "DISPATCHED" if validated_tick is not None else validated_control["decision_status"]
    )
    result = {
        "daemon_dispatch_result_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_DISPATCH_RESULT_SCHEMA_VERSION
        ),
        "daemon_dispatch_result_id": _scheduler_daemon_dispatch_result_id(
            control_plan=validated_control,
            tick_once_result=validated_tick,
            start_stop_guardrail=validated_start_stop,
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": validated_control["scheduler_id"],
        "dispatch_status": dispatch_status,
        "control_plan": deepcopy(validated_control),
        "tick_once_result": deepcopy(validated_tick),
        "start_stop_guardrail": deepcopy(validated_start_stop),
        "guardrails": _scheduler_daemon_dispatch_guardrails(),
        "metadata": _scheduler_daemon_dispatch_metadata(
            control_plan=validated_control,
            tick_once_result=validated_tick,
            start_stop_guardrail=validated_start_stop,
        ),
    }
    return result


def _build_artifact_retention_scheduler_daemon_start_stop_guardrail(
    *,
    control_plan: Mapping[str, Any],
) -> dict[str, Any]:
    validated_control = validate_artifact_retention_scheduler_daemon_control_plan(
        control_plan
    )
    action = _normalize_scheduler_daemon_start_stop_action(
        validated_control["action"]
    )
    guardrail_status, guardrail_reason = _scheduler_daemon_start_stop_guardrail_decision(
        validated_control
    )
    return {
        "daemon_start_stop_guardrail_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_START_STOP_GUARDRAIL_SCHEMA_VERSION
        ),
        "daemon_start_stop_guardrail_id": _scheduler_daemon_start_stop_guardrail_id(
            control_plan=validated_control,
            guardrail_status=guardrail_status,
            guardrail_reason=guardrail_reason,
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": validated_control["scheduler_id"],
        "action": action,
        "guardrail_status": guardrail_status,
        "guardrail_reason": guardrail_reason,
        "requested_at": validated_control["requested_at"],
        "control_plan": deepcopy(validated_control),
        "action_allowed": False,
        "runtime_state_transition": "NONE",
        "execution_plan": _scheduler_daemon_start_stop_execution_plan(
            validated_control
        ),
        "guardrails": _scheduler_daemon_start_stop_guardrails(),
        "metadata": _scheduler_daemon_start_stop_metadata(
            control_plan=validated_control,
            guardrail_status=guardrail_status,
            guardrail_reason=guardrail_reason,
        ),
    }


def _build_artifact_retention_scheduler_daemon_one_cycle_result(
    *,
    loop_plan: Mapping[str, Any],
    tick_once_result: Mapping[str, Any] | None,
    daemon_heartbeat_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    validated_loop = validate_artifact_retention_scheduler_daemon_loop_plan(loop_plan)
    validated_tick = (
        validate_artifact_retention_scheduler_tick_once_result(tick_once_result)
        if tick_once_result is not None
        else None
    )
    result_status = _scheduler_daemon_one_cycle_result_status(
        loop_plan=validated_loop,
        tick_once_result=validated_tick,
    )
    skip_reason = _scheduler_daemon_one_cycle_skip_reason(
        loop_plan=validated_loop,
        tick_once_result=validated_tick,
    )
    validated_heartbeats = _validate_scheduler_daemon_heartbeat_results(
        daemon_heartbeat_results or []
    )
    return {
        "daemon_one_cycle_result_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ONE_CYCLE_RESULT_SCHEMA_VERSION
        ),
        "daemon_one_cycle_result_id": _scheduler_daemon_one_cycle_result_id(
            loop_plan=validated_loop,
            tick_once_result=validated_tick,
            result_status=result_status,
            skip_reason=skip_reason,
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": validated_loop["scheduler_id"],
        "run_at": validated_loop["requested_at"],
        "result_status": result_status,
        "skip_reason": skip_reason,
        "loop_plan": deepcopy(validated_loop),
        "tick_once_result": deepcopy(validated_tick),
        "daemon_heartbeat_results": deepcopy(validated_heartbeats),
        "execution_plan": deepcopy(validated_loop["execution_plan"]),
        "guardrails": _scheduler_daemon_one_cycle_guardrails(),
        "metadata": _scheduler_daemon_one_cycle_metadata(
            loop_plan=validated_loop,
            tick_once_result=validated_tick,
            daemon_heartbeat_results=validated_heartbeats,
        ),
    }


def _scheduler_daemon_dispatch_result_id(
    *,
    control_plan: Mapping[str, Any],
    tick_once_result: Mapping[str, Any] | None,
    start_stop_guardrail: Mapping[str, Any] | None,
) -> str:
    basis = {
        "daemon_control_plan_id": control_plan["daemon_control_plan_id"],
        "action": control_plan["action"],
        "decision_status": control_plan["decision_status"],
        "tick_once_result_id": (
            tick_once_result.get("tick_once_result_id")
            if isinstance(tick_once_result, Mapping)
            else None
        ),
        "start_stop_guardrail_id": (
            start_stop_guardrail.get("daemon_start_stop_guardrail_id")
            if isinstance(start_stop_guardrail, Mapping)
            else None
        ),
    }
    return str(
        uuid5(
            NAMESPACE_URL,
            f"ae-artifact-retention-scheduler-daemon-dispatch:{sha256_json(basis)}",
        )
    )


def _scheduler_daemon_start_stop_guardrail_id(
    *,
    control_plan: Mapping[str, Any],
    guardrail_status: str,
    guardrail_reason: str,
) -> str:
    basis = {
        "daemon_control_plan_id": control_plan["daemon_control_plan_id"],
        "action": control_plan["action"],
        "decision_status": control_plan["decision_status"],
        "guardrail_status": guardrail_status,
        "guardrail_reason": guardrail_reason,
    }
    return str(
        uuid5(
            NAMESPACE_URL,
            f"ae-artifact-retention-scheduler-daemon-start-stop:{sha256_json(basis)}",
        )
    )


def _normalize_scheduler_daemon_start_stop_action(value: Any) -> str:
    action = normalize_artifact_retention_scheduler_daemon_control_action(value)
    if not _is_scheduler_daemon_start_stop_action(action):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_start_stop_guardrail_action_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon start/stop guardrail action "
                "must be start_daemon or stop_daemon."
            ),
        )
    return action


def _is_scheduler_daemon_start_stop_action(action: Any) -> bool:
    return action in {
        ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONTROL_ACTION_START_DAEMON,
        ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONTROL_ACTION_STOP_DAEMON,
    }


def _scheduler_daemon_start_stop_guardrail_decision(
    control_plan: Mapping[str, Any],
) -> tuple[str, str]:
    action = _normalize_scheduler_daemon_start_stop_action(control_plan.get("action"))
    if action == ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONTROL_ACTION_START_DAEMON:
        if (
            control_plan.get("decision_status") != "BLOCKED"
            or control_plan.get("block_reason") != "daemon_disabled_by_policy"
        ):
            raise ArtifactHandoffError(
                status_code=422,
                error_code=(
                    "ae.artifact_retention_scheduler_daemon_start_stop_guardrail_invalid"
                ),
                detail=(
                    "Artifact retention scheduler daemon start guardrail decision "
                    "is invalid."
                ),
            )
        return "BLOCKED", "daemon_disabled_by_policy"
    if (
        control_plan.get("decision_status") != "NOOP"
        or control_plan.get("block_reason") is not None
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_start_stop_guardrail_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon stop guardrail decision is "
                "invalid."
            ),
        )
    return "NOOP", "daemon_not_running"


def _scheduler_daemon_start_stop_execution_plan(
    control_plan: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "requires_control_plan": True,
        "requires_lease": False,
        "runs_tick_once": False,
        "dispatches_job_queue": False,
        "starts_daemon": False,
        "stops_daemon": False,
        "sends_stop_signal": False,
        "starts_continuous_loop": False,
        "runtime_state_mutated": False,
        "writes_history": False,
        "physical_delete_enabled": False,
        "mirrors_control_action": _normalize_scheduler_daemon_start_stop_action(
            control_plan.get("action")
        ),
    }


def _scheduler_daemon_one_cycle_result_status(
    *,
    loop_plan: Mapping[str, Any],
    tick_once_result: Mapping[str, Any] | None,
) -> str:
    if isinstance(tick_once_result, Mapping):
        return str(tick_once_result["result_status"])
    if loop_plan["decision_status"] == "NOOP":
        return "NOOP"
    return "SKIPPED"


def _scheduler_daemon_one_cycle_skip_reason(
    *,
    loop_plan: Mapping[str, Any],
    tick_once_result: Mapping[str, Any] | None,
) -> str | None:
    if isinstance(tick_once_result, Mapping):
        return tick_once_result["skip_reason"]
    return loop_plan["decision_reason"]


def _scheduler_daemon_one_cycle_result_id(
    *,
    loop_plan: Mapping[str, Any],
    tick_once_result: Mapping[str, Any] | None,
    result_status: str,
    skip_reason: str | None,
) -> str:
    basis = {
        "daemon_loop_plan_id": loop_plan["daemon_loop_plan_id"],
        "tick_once_result_id": (
            tick_once_result.get("tick_once_result_id")
            if isinstance(tick_once_result, Mapping)
            else None
        ),
        "result_status": result_status,
        "skip_reason": skip_reason,
    }
    return str(
        uuid5(
            NAMESPACE_URL,
            f"ae-artifact-retention-scheduler-daemon-one-cycle:{sha256_json(basis)}",
        )
    )


def _scheduler_daemon_runtime_state_instance_id(
    *,
    scheduler_id: str,
    observed_at: str,
) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            f"ae-artifact-retention-scheduler-daemon-instance:{scheduler_id}:{observed_at}",
        )
    )


def _scheduler_daemon_runtime_state_id(
    *,
    scheduler_id: str,
    daemon_instance_id: str,
    observed_at: str,
    lifecycle_status: str,
    cycle_count: int,
) -> str:
    basis = {
        "scheduler_id": scheduler_id,
        "daemon_instance_id": daemon_instance_id,
        "observed_at": observed_at,
        "lifecycle_status": lifecycle_status,
        "cycle_count": cycle_count,
    }
    return str(
        uuid5(
            NAMESPACE_URL,
            f"ae-artifact-retention-scheduler-daemon-runtime-state:{sha256_json(basis)}",
        )
    )


def _normalize_scheduler_daemon_runtime_state_status(value: Any) -> str:
    status = optional_text(value)
    if status not in ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUNTIME_STATE_STATUSES:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
            detail="Artifact retention scheduler daemon runtime state status is invalid.",
        )
    return status


def _normalize_scheduler_daemon_runtime_state_reason(
    value: Any,
    *,
    lifecycle_status: str,
    runtime_config: Any,
    consecutive_failure_count: Any,
) -> str:
    reason = optional_text(value)
    if reason is None:
        if lifecycle_status == "DISABLED":
            return _scheduler_daemon_disabled_runtime_state_reason(runtime_config)
        if lifecycle_status == "ERROR":
            return "cycle_failed"
        if lifecycle_status == "RUNNING":
            return "bounded_loop_running"
        if lifecycle_status == "STOPPING":
            return "stop_requested"
        if lifecycle_status == "STARTING":
            return "start_requested"
        return "stopped"
    if reason not in ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUNTIME_STATE_REASONS:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
            detail="Artifact retention scheduler daemon runtime state reason is invalid.",
        )
    if lifecycle_status == "ERROR" and reason != "cycle_failed":
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
            detail="Artifact retention scheduler daemon runtime error reason is invalid.",
        )
    if lifecycle_status == "ERROR":
        _positive_int(
            consecutive_failure_count,
            "consecutive_failure_count",
            "ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
        )
    return reason


def _scheduler_daemon_disabled_runtime_state_reason(runtime_config: Any) -> str:
    if not isinstance(runtime_config, Mapping):
        return "runtime_disabled"
    enablement = runtime_config.get("enablement")
    if not isinstance(enablement, Mapping):
        return "runtime_disabled"
    if enablement.get("block_reason") == "explicit_opt_in_required":
        return "explicit_opt_in_required"
    return "runtime_disabled"


def _scheduler_daemon_runtime_state_last_cycle(
    value: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
            detail="Artifact retention scheduler daemon runtime state last cycle is invalid.",
        )
    if "daemon_one_cycle_result_schema_version" in value:
        validated = validate_artifact_retention_scheduler_daemon_one_cycle_result(value)
        return {
            "daemon_one_cycle_result_id": validated["daemon_one_cycle_result_id"],
            "run_at": validated["run_at"],
            "result_status": validated["result_status"],
            "skip_reason": validated["skip_reason"],
            "loop_decision_status": validated["loop_plan"]["decision_status"],
            "loop_decision_reason": validated["loop_plan"]["decision_reason"],
            "tick_once_ran": validated["metadata"]["tick_once_ran"],
            "job_enqueued": validated["metadata"]["job_enqueued"],
            "worker_executed": validated["metadata"]["worker_executed"],
            "history_write_executed": validated["metadata"][
                "history_write_executed"
            ],
        }
    if set(value) != {
        "daemon_one_cycle_result_id",
        "run_at",
        "result_status",
        "skip_reason",
        "loop_decision_status",
        "loop_decision_reason",
        "tick_once_ran",
        "job_enqueued",
        "worker_executed",
        "history_write_executed",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
            detail="Artifact retention scheduler daemon runtime state last cycle keys are invalid.",
        )
    result = dict(value)
    _required_text(
        result.get("daemon_one_cycle_result_id"),
        "daemon_one_cycle_result_id",
        "ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
    )
    result["run_at"] = format_artifact_retention_timestamp(
        parse_artifact_retention_timestamp(
            result.get("run_at"),
            field_name="run_at",
        )
    )
    if result.get("result_status") not in (
        ARTIFACT_RETENTION_SCHEDULER_DAEMON_ONE_CYCLE_RESULT_STATUSES
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
            detail="Artifact retention scheduler daemon runtime state last cycle status is invalid.",
        )
    _required_text(
        result.get("loop_decision_status"),
        "loop_decision_status",
        "ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
    )
    result["loop_decision_reason"] = optional_text(
        result.get("loop_decision_reason")
    )
    for field_name in (
        "tick_once_ran",
        "job_enqueued",
        "worker_executed",
        "history_write_executed",
    ):
        result[field_name] = _required_bool(
            result.get(field_name),
            field_name,
            "ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
        )
    result["skip_reason"] = optional_text(result.get("skip_reason"))
    return result


def _validate_scheduler_daemon_runtime_state_lifecycle(
    *,
    lifecycle_status: str,
    lifecycle_reason: str,
    runtime_config: Mapping[str, Any],
    stop_requested: bool,
    shutdown_requested_at: str | None,
    last_cycle: Mapping[str, Any] | None,
    consecutive_failure_count: int,
) -> None:
    enablement_status = runtime_config["enablement"]["enablement_status"]
    if lifecycle_status in {"STARTING", "RUNNING"} and enablement_status != "READY":
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
            detail="Artifact retention scheduler daemon runtime state requires ready enablement.",
        )
    if lifecycle_status == "DISABLED" and lifecycle_reason not in {
        "runtime_disabled",
        "explicit_opt_in_required",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
            detail="Artifact retention scheduler daemon disabled state reason is invalid.",
        )
    if lifecycle_status == "STOPPING" and not (
        stop_requested or shutdown_requested_at is not None
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
            detail="Artifact retention scheduler daemon stopping state requires a stop request.",
        )
    if lifecycle_status == "STOPPED" and lifecycle_reason not in {
        "initialized",
        "stopped",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
            detail="Artifact retention scheduler daemon stopped state reason is invalid.",
        )
    if lifecycle_status == "ERROR" and (
        consecutive_failure_count < 1
        or not isinstance(last_cycle, Mapping)
        or last_cycle.get("result_status") != "FAILED"
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
            detail="Artifact retention scheduler daemon error state requires a failed cycle.",
        )


def _scheduler_daemon_runtime_state_guardrails() -> dict[str, bool]:
    return {
        "metadata_only": True,
        "state_snapshot_only": True,
        "daemon_process_owner_ae": True,
        "daemon_as_jobqueue_job_allowed": False,
        "retention_work_uses_job_queue": True,
        "job_enqueue_performed": False,
        "worker_execution_performed": False,
        "runtime_state_persisted_by_builder": False,
        "continuous_loop_started_by_builder": False,
        "physical_delete_automation_enabled": False,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
    }


def _scheduler_daemon_runtime_state_metadata(
    *,
    lifecycle_status: str,
    stop_requested: bool,
    shutdown_requested_at: str | None,
    last_cycle: Mapping[str, Any] | None,
    next_tick_at: str | None,
    consecutive_failure_count: int,
) -> dict[str, bool]:
    return {
        "metadata_only": True,
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
        "safe_for_ag_projection": True,
        "state_snapshot_only": True,
        "lifecycle_running": lifecycle_status == "RUNNING",
        "lifecycle_stopped": lifecycle_status == "STOPPED",
        "lifecycle_error": lifecycle_status == "ERROR",
        "stop_requested": stop_requested,
        "shutdown_requested": shutdown_requested_at is not None,
        "last_cycle_present": last_cycle is not None,
        "last_cycle_failed": (
            isinstance(last_cycle, Mapping)
            and last_cycle.get("result_status") == "FAILED"
        ),
        "next_tick_scheduled": next_tick_at is not None,
        "consecutive_failures_present": consecutive_failure_count > 0,
        "job_enqueued": False,
        "worker_executed": False,
        "runtime_state_persisted": False,
        "continuous_loop_started": False,
        "physical_delete_automation_enabled": False,
    }


def _scheduler_daemon_shutdown_transition_next_state(
    *,
    previous_state: Mapping[str, Any],
    requested_at: str,
) -> tuple[str, str, dict[str, Any]]:
    lifecycle_status = previous_state["lifecycle_status"]
    if lifecycle_status in {"STARTING", "RUNNING", "ERROR"}:
        next_state = build_artifact_retention_scheduler_daemon_runtime_state(
            runtime_config=previous_state["runtime_config"],
            daemon_config=previous_state["daemon_config"],
            daemon_instance_id=previous_state["daemon_instance_id"],
            lifecycle_status="STOPPING",
            lifecycle_reason="stop_requested",
            observed_at=requested_at,
            stop_requested=True,
            shutdown_requested_at=requested_at,
            last_cycle_result=previous_state["last_cycle"],
            next_tick_at=None,
            cycle_count=previous_state["cycle_count"],
            consecutive_failure_count=previous_state[
                "consecutive_failure_count"
            ],
            heartbeat_worker_id=previous_state["heartbeat_worker_id"],
        )
        return "READY", "stop_requested", next_state
    if lifecycle_status == "STOPPING":
        return "NOOP", "stop_already_requested", deepcopy(dict(previous_state))
    if lifecycle_status == "DISABLED":
        return "NOOP", previous_state["lifecycle_reason"], deepcopy(
            dict(previous_state)
        )
    return "NOOP", "already_stopped", deepcopy(dict(previous_state))


def _scheduler_daemon_shutdown_transition_requested_by(
    value: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if value is None:
        return {"actor_type": "service", "actor_id": "nex-ae-api"}
    if not isinstance(value, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_shutdown_transition_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon shutdown transition "
                "requested_by is invalid."
            ),
        )
    actor_type = _required_text(
        value.get("actor_type"),
        "actor_type",
        "ae.artifact_retention_scheduler_daemon_shutdown_transition_invalid",
    )
    actor_id = _required_text(
        value.get("actor_id"),
        "actor_id",
        "ae.artifact_retention_scheduler_daemon_shutdown_transition_invalid",
    )
    requested_by = {"actor_type": actor_type, "actor_id": actor_id}
    for field_name in ("tenant_id", "workspace_id", "request_id"):
        field_value = optional_text(value.get(field_name))
        if field_value is not None:
            requested_by[field_name] = field_value
    return requested_by


def _normalize_scheduler_daemon_shutdown_transition_status(value: Any) -> str:
    status = optional_text(value)
    if (
        status
        not in ARTIFACT_RETENTION_SCHEDULER_DAEMON_SHUTDOWN_TRANSITION_DECISION_STATUSES
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_shutdown_transition_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon shutdown transition "
                "decision status is invalid."
            ),
        )
    return status


def _normalize_scheduler_daemon_shutdown_transition_reason(value: Any) -> str:
    reason = optional_text(value)
    if (
        reason
        not in ARTIFACT_RETENTION_SCHEDULER_DAEMON_SHUTDOWN_TRANSITION_DECISION_REASONS
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_shutdown_transition_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon shutdown transition "
                "decision reason is invalid."
            ),
        )
    return reason


def _validate_scheduler_daemon_shutdown_transition_scope(
    *,
    scheduler_id: str,
    daemon_instance_id: str,
    previous_state: Mapping[str, Any],
    next_state: Mapping[str, Any],
) -> None:
    for label, state in (("previous", previous_state), ("next", next_state)):
        if state["scheduler_id"] != scheduler_id:
            raise ArtifactHandoffError(
                status_code=422,
                error_code=(
                    "ae.artifact_retention_scheduler_daemon_shutdown_transition_invalid"
                ),
                detail=(
                    "Artifact retention scheduler daemon shutdown transition "
                    f"{label} state scope is invalid."
                ),
            )
        if state["daemon_instance_id"] != daemon_instance_id:
            raise ArtifactHandoffError(
                status_code=422,
                error_code=(
                    "ae.artifact_retention_scheduler_daemon_shutdown_transition_invalid"
                ),
                detail=(
                    "Artifact retention scheduler daemon shutdown transition "
                    f"{label} state instance is invalid."
                ),
            )
    if previous_state["runtime_config"] != next_state["runtime_config"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_shutdown_transition_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon shutdown transition runtime "
                "scope is invalid."
            ),
        )
    if previous_state["daemon_config"] != next_state["daemon_config"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_shutdown_transition_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon shutdown transition daemon "
                "scope is invalid."
            ),
        )


def _validate_scheduler_daemon_shutdown_transition_decision(
    *,
    requested_at: str,
    decision_status: str,
    decision_reason: str,
    previous_state: Mapping[str, Any],
    next_state: Mapping[str, Any],
) -> None:
    expected_status, expected_reason, expected_next_state = (
        _scheduler_daemon_shutdown_transition_next_state(
            previous_state=previous_state,
            requested_at=requested_at,
        )
    )
    if decision_status != expected_status or decision_reason != expected_reason:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_shutdown_transition_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon shutdown transition "
                "decision is invalid."
            ),
        )
    if next_state != expected_next_state:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_shutdown_transition_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon shutdown transition next "
                "state is invalid."
            ),
        )


def _scheduler_daemon_shutdown_transition_execution_plan(
    *,
    decision_status: str,
    decision_reason: str,
    next_state: Mapping[str, Any],
) -> dict[str, Any]:
    stop_signal_requested = decision_status == "READY"
    return {
        "requires_runtime_state": True,
        "validates_current_state": True,
        "projects_next_state": True,
        "next_state_lifecycle_status": next_state["lifecycle_status"],
        "stop_signal_requested": stop_signal_requested,
        "stop_already_requested": decision_reason == "stop_already_requested",
        "already_terminal": decision_reason in {
            "already_stopped",
            "runtime_disabled",
            "explicit_opt_in_required",
        },
        "bounded_loop_should_stop_before_next_cycle": stop_signal_requested,
        "starts_continuous_loop": False,
        "runs_tick_once": False,
        "enqueues_job_queue": False,
        "runs_worker": False,
        "writes_database": False,
        "physical_delete_enabled": False,
    }


def _scheduler_daemon_shutdown_transition_guardrails() -> dict[str, bool]:
    return {
        "metadata_only": True,
        "daemon_process_owner_ae": True,
        "state_transition_only": True,
        "runtime_state_mutated": False,
        "stop_signal_delivered": False,
        "continuous_loop_started": False,
        "retention_work_uses_job_queue": True,
        "job_enqueue_performed": False,
        "worker_execution_performed": False,
        "database_write_performed": False,
        "physical_delete_automation_enabled": False,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
    }


def _scheduler_daemon_shutdown_transition_metadata(
    *,
    decision_status: str,
    decision_reason: str,
    previous_state: Mapping[str, Any],
    next_state: Mapping[str, Any],
) -> dict[str, bool]:
    return {
        "metadata_only": True,
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
        "safe_for_ag_projection": True,
        "shutdown_requested": decision_status == "READY",
        "shutdown_noop": decision_status == "NOOP",
        "from_running": previous_state["lifecycle_status"] == "RUNNING",
        "from_starting": previous_state["lifecycle_status"] == "STARTING",
        "from_error": previous_state["lifecycle_status"] == "ERROR",
        "to_stopping": next_state["lifecycle_status"] == "STOPPING",
        "to_terminal": next_state["lifecycle_status"] in {
            "STOPPED",
            "DISABLED",
        },
        "stop_already_requested": decision_reason == "stop_already_requested",
        "runtime_state_mutated": False,
        "continuous_loop_started": False,
        "job_enqueued": False,
        "worker_executed": False,
        "physical_delete_automation_enabled": False,
    }


def _scheduler_daemon_shutdown_transition_id(
    *,
    scheduler_id: str,
    daemon_instance_id: str,
    requested_at: str,
    requested_by: Mapping[str, Any],
    reason: str | None,
    decision_status: str,
    decision_reason: str,
    previous_state: Mapping[str, Any],
    next_state: Mapping[str, Any],
) -> str:
    basis = {
        "scheduler_id": scheduler_id,
        "daemon_instance_id": daemon_instance_id,
        "requested_at": requested_at,
        "requested_by": dict(requested_by),
        "reason": reason,
        "decision_status": decision_status,
        "decision_reason": decision_reason,
        "previous_state_id": previous_state["daemon_runtime_state_id"],
        "next_state_id": next_state["daemon_runtime_state_id"],
    }
    return str(
        uuid5(
            NAMESPACE_URL,
            (
                "ae-artifact-retention-scheduler-daemon-shutdown-"
                f"transition:{sha256_json(basis)}"
            ),
        )
    )


def _scheduler_daemon_bounded_loop_started_at(
    *,
    requested_at: str | None,
    scheduler_config: Mapping[str, Any],
    clock: Callable[[], str] | None,
) -> str:
    candidate = requested_at or (clock() if clock is not None else None)
    return _scheduler_daemon_checked_at(
        checked_at=candidate,
        scheduler_config=scheduler_config,
    )


def _scheduler_daemon_bounded_loop_cycle_requested_at(
    *,
    started_at: str,
    interval_seconds: int,
    cycle_index: int,
) -> str:
    started = parse_artifact_retention_timestamp(
        started_at,
        field_name="started_at",
    )
    return format_artifact_retention_timestamp(
        started + timedelta(seconds=interval_seconds * (cycle_index - 1))
    )


def _scheduler_daemon_bounded_loop_cycle_idempotency_key(
    *,
    idempotency_key: str | None,
    cycle_index: int,
) -> str | None:
    normalized = optional_text(idempotency_key)
    if normalized is None:
        return None
    return f"{normalized}:cycle:{cycle_index}"


def _scheduler_daemon_bounded_loop_trace_id(
    *,
    trace_id: str | None,
    scheduler_id: str,
    daemon_instance_id: str,
    started_at: str,
) -> str:
    normalized = optional_text(trace_id)
    if normalized is not None:
        if len(normalized) == 32 and all(
            char in "0123456789abcdef" for char in normalized
        ):
            return normalized
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_bounded_loop_result_invalid",
            detail=(
                "Artifact retention scheduler daemon bounded loop trace_id "
                "must be 32 lowercase hex characters."
            ),
        )
    return sha256_json(
        {
            "scheduler_id": scheduler_id,
            "daemon_instance_id": daemon_instance_id,
            "started_at": started_at,
        }
    )[:32]


def _scheduler_daemon_bounded_loop_request_id(
    *,
    request_id: str | None,
    scheduler_id: str,
    daemon_instance_id: str,
    started_at: str,
) -> str:
    normalized = optional_text(request_id)
    if normalized is not None:
        return normalized
    fingerprint = sha256_json(
        {
            "scheduler_id": scheduler_id,
            "daemon_instance_id": daemon_instance_id,
            "started_at": started_at,
        }
    )[:24]
    return (
        "ae-retention-daemon-bounded-loop-"
        f"{fingerprint}"
    )


def _scheduler_daemon_bounded_loop_cycle_request_id(
    *,
    request_id: str,
    cycle_index: int,
) -> str:
    return f"{request_id}:cycle:{cycle_index}"


def _scheduler_daemon_bounded_loop_disabled_stop_reason(
    runtime_config: Mapping[str, Any],
) -> str:
    block_reason = runtime_config["enablement"]["block_reason"]
    return block_reason or "runtime_disabled"


def _scheduler_daemon_bounded_loop_failure_cycle_summary(
    *,
    scheduler_id: str,
    run_at: str,
    cycle_index: int,
) -> dict[str, Any]:
    basis = {
        "scheduler_id": scheduler_id,
        "run_at": run_at,
        "cycle_index": cycle_index,
    }
    return {
        "daemon_one_cycle_result_id": str(
            uuid5(
                NAMESPACE_URL,
                (
                    "ae-artifact-retention-scheduler-daemon-bounded-loop-"
                    f"failure:{sha256_json(basis)}"
                ),
            )
        ),
        "run_at": run_at,
        "result_status": "FAILED",
        "skip_reason": "tick_failed",
        "loop_decision_status": "ERROR",
        "loop_decision_reason": "cycle_exception",
        "tick_once_ran": False,
        "job_enqueued": False,
        "worker_executed": False,
        "history_write_executed": False,
    }


def _scheduler_daemon_bounded_loop_cycle_record(
    *,
    cycle_index: int,
    requested_at: str,
    one_cycle_result: Mapping[str, Any],
    error: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return _validate_scheduler_daemon_bounded_loop_cycle_record(
        {
            "cycle_index": cycle_index,
            "requested_at": requested_at,
            "one_cycle_result": dict(one_cycle_result),
            "error": None if error is None else dict(error),
        }
    )


def _scheduler_daemon_bounded_loop_final_state(
    *,
    scheduler_config: Mapping[str, Any],
    runtime_config: Mapping[str, Any],
    daemon_config: Mapping[str, Any],
    daemon_instance_id: str,
    observed_at: str,
    result_status: str,
    stop_reason: str,
    stop_requested: bool,
    last_cycle_result: Mapping[str, Any] | None,
    cycle_count: int,
    consecutive_failure_count: int,
) -> dict[str, Any]:
    if result_status == "FAILED":
        lifecycle_status = "ERROR"
        lifecycle_reason = "cycle_failed"
        shutdown_requested_at = None
    elif result_status == "STOPPED":
        lifecycle_status = "STOPPED"
        lifecycle_reason = "stopped"
        shutdown_requested_at = observed_at
    elif result_status == "SKIPPED":
        lifecycle_status = "DISABLED"
        lifecycle_reason = stop_reason
        shutdown_requested_at = None
    else:
        lifecycle_status = "STOPPED"
        lifecycle_reason = "stopped"
        shutdown_requested_at = None
    return build_artifact_retention_scheduler_daemon_runtime_state(
        scheduler_config=scheduler_config,
        runtime_config=runtime_config,
        daemon_config=daemon_config,
        daemon_instance_id=daemon_instance_id,
        lifecycle_status=lifecycle_status,
        lifecycle_reason=lifecycle_reason,
        observed_at=observed_at,
        stop_requested=stop_requested,
        shutdown_requested_at=shutdown_requested_at,
        last_cycle_result=last_cycle_result,
        cycle_count=cycle_count,
        consecutive_failure_count=consecutive_failure_count,
    )


def _build_artifact_retention_scheduler_daemon_bounded_loop_result(
    *,
    scheduler_id: str,
    daemon_instance_id: str,
    started_at: str,
    finished_at: str,
    result_status: str,
    stop_reason: str,
    max_cycles: int,
    cycle_results: list[dict[str, Any]],
    consecutive_failure_count: int,
    initial_state: Mapping[str, Any],
    final_state: Mapping[str, Any],
    runtime_config: Mapping[str, Any],
    daemon_config: Mapping[str, Any],
    run_worker: bool,
) -> dict[str, Any]:
    cycle_count = len(cycle_results)
    result = {
        "daemon_bounded_loop_result_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_BOUNDED_LOOP_RESULT_SCHEMA_VERSION
        ),
        "daemon_bounded_loop_result_id": _scheduler_daemon_bounded_loop_result_id(
            scheduler_id=scheduler_id,
            daemon_instance_id=daemon_instance_id,
            started_at=started_at,
            finished_at=finished_at,
            result_status=result_status,
            stop_reason=stop_reason,
            cycle_results=cycle_results,
            final_state=final_state,
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": scheduler_id,
        "daemon_instance_id": daemon_instance_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "result_status": result_status,
        "stop_reason": stop_reason,
        "max_cycles": max_cycles,
        "worker_requested": run_worker,
        "cycle_count": cycle_count,
        "consecutive_failure_count": consecutive_failure_count,
        "cycle_results": deepcopy(cycle_results),
        "initial_state": deepcopy(dict(initial_state)),
        "final_state": deepcopy(dict(final_state)),
        "runtime_config": deepcopy(dict(runtime_config)),
        "daemon_config": deepcopy(dict(daemon_config)),
        "execution_plan": _scheduler_daemon_bounded_loop_execution_plan(
            result_status=result_status,
            stop_reason=stop_reason,
            max_cycles=max_cycles,
            cycle_count=cycle_count,
            run_worker=run_worker,
        ),
        "guardrails": _scheduler_daemon_bounded_loop_guardrails(),
        "metadata": _scheduler_daemon_bounded_loop_metadata(
            result_status=result_status,
            stop_reason=stop_reason,
            cycle_results=cycle_results,
            final_state=final_state,
        ),
    }
    return result


def _validate_scheduler_daemon_bounded_loop_scope(
    *,
    scheduler_id: str,
    daemon_instance_id: str,
    runtime_config: Mapping[str, Any],
    daemon_config: Mapping[str, Any],
    initial_state: Mapping[str, Any],
    final_state: Mapping[str, Any],
) -> None:
    if runtime_config["scheduler_id"] != scheduler_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_bounded_loop_result_invalid",
            detail="Artifact retention scheduler daemon bounded loop runtime scope is invalid.",
        )
    if daemon_config["scheduler_id"] != scheduler_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_bounded_loop_result_invalid",
            detail="Artifact retention scheduler daemon bounded loop daemon scope is invalid.",
        )
    for state_name, state in (
        ("initial", initial_state),
        ("final", final_state),
    ):
        if state["scheduler_id"] != scheduler_id:
            raise ArtifactHandoffError(
                status_code=422,
                error_code=(
                    "ae.artifact_retention_scheduler_daemon_bounded_loop_result_invalid"
                ),
                detail=(
                    "Artifact retention scheduler daemon bounded loop "
                    f"{state_name} state scope is invalid."
                ),
            )
        if state["daemon_instance_id"] != daemon_instance_id:
            raise ArtifactHandoffError(
                status_code=422,
                error_code=(
                    "ae.artifact_retention_scheduler_daemon_bounded_loop_result_invalid"
                ),
                detail=(
                    "Artifact retention scheduler daemon bounded loop "
                    f"{state_name} state instance is invalid."
                ),
            )


def _validate_scheduler_daemon_bounded_loop_status(
    *,
    result_status: str,
    stop_reason: str,
    max_cycles: int,
    cycle_count: int,
    consecutive_failure_count: int,
    cycle_results: list[dict[str, Any]],
    initial_state: Mapping[str, Any],
    final_state: Mapping[str, Any],
    runtime_config: Mapping[str, Any],
) -> None:
    if cycle_count != len(cycle_results):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_bounded_loop_result_invalid",
            detail="Artifact retention scheduler daemon bounded loop cycle count is invalid.",
        )
    if cycle_count > max_cycles:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_bounded_loop_result_invalid",
            detail="Artifact retention scheduler daemon bounded loop exceeded max cycles.",
        )
    expected_initial = (
        "STARTING"
        if runtime_config["enablement"]["enablement_status"] == "READY"
        else "DISABLED"
    )
    if initial_state["lifecycle_status"] != expected_initial:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_bounded_loop_result_invalid",
            detail="Artifact retention scheduler daemon bounded loop initial state is invalid.",
        )
    if result_status == "SKIPPED":
        if (
            runtime_config["enablement"]["enablement_status"] == "READY"
            or cycle_count != 0
            or stop_reason not in {"runtime_disabled", "explicit_opt_in_required"}
            or final_state["lifecycle_status"] != "DISABLED"
        ):
            raise ArtifactHandoffError(
                status_code=422,
                error_code=(
                    "ae.artifact_retention_scheduler_daemon_bounded_loop_result_invalid"
                ),
                detail=(
                    "Artifact retention scheduler daemon bounded loop skipped state "
                    "is invalid."
                ),
            )
        return
    if result_status == "STOPPED":
        if (
            stop_reason != "stop_requested"
            or final_state["lifecycle_status"] != "STOPPED"
            or final_state["stop_requested"] is not True
        ):
            raise ArtifactHandoffError(
                status_code=422,
                error_code=(
                    "ae.artifact_retention_scheduler_daemon_bounded_loop_result_invalid"
                ),
                detail=(
                    "Artifact retention scheduler daemon bounded loop stopped state "
                    "is invalid."
                ),
            )
        return
    if result_status == "FAILED":
        if (
            stop_reason != "cycle_failed"
            or cycle_count < 1
            or consecutive_failure_count < 1
            or cycle_results[-1]["one_cycle_result"]["result_status"] != "FAILED"
            or final_state["lifecycle_status"] != "ERROR"
        ):
            raise ArtifactHandoffError(
                status_code=422,
                error_code=(
                    "ae.artifact_retention_scheduler_daemon_bounded_loop_result_invalid"
                ),
                detail=(
                    "Artifact retention scheduler daemon bounded loop failed state "
                    "is invalid."
                ),
            )
        return
    if (
        result_status != "SUCCEEDED"
        or stop_reason != "max_cycles_reached"
        or cycle_count != max_cycles
        or consecutive_failure_count != 0
        or final_state["lifecycle_status"] != "STOPPED"
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_bounded_loop_result_invalid",
            detail="Artifact retention scheduler daemon bounded loop success state is invalid.",
        )


def _validate_scheduler_daemon_bounded_loop_cycle_results(
    value: Any,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_bounded_loop_result_invalid",
            detail="Artifact retention scheduler daemon bounded loop cycles must be a list.",
        )
    return [
        _validate_scheduler_daemon_bounded_loop_cycle_record(item)
        for item in value
    ]


def _validate_scheduler_daemon_bounded_loop_cycle_record(
    value: Any,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_bounded_loop_result_invalid",
            detail="Artifact retention scheduler daemon bounded loop cycle must be an object.",
        )
    record = dict(value)
    if set(record) != {"cycle_index", "requested_at", "one_cycle_result", "error"}:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_bounded_loop_result_invalid",
            detail="Artifact retention scheduler daemon bounded loop cycle keys are invalid.",
        )
    record["cycle_index"] = _positive_int(
        record.get("cycle_index"),
        "cycle_index",
        "ae.artifact_retention_scheduler_daemon_bounded_loop_result_invalid",
    )
    record["requested_at"] = format_artifact_retention_timestamp(
        parse_artifact_retention_timestamp(
            record.get("requested_at"),
            field_name="requested_at",
        )
    )
    record["one_cycle_result"] = _scheduler_daemon_runtime_state_last_cycle(
        record.get("one_cycle_result")
    )
    if record["one_cycle_result"] is None:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_bounded_loop_result_invalid",
            detail="Artifact retention scheduler daemon bounded loop cycle result is required.",
        )
    if record["one_cycle_result"]["run_at"] != record["requested_at"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_bounded_loop_result_invalid",
            detail="Artifact retention scheduler daemon bounded loop cycle time is invalid.",
        )
    record["error"] = _validate_scheduler_daemon_bounded_loop_cycle_error(
        record.get("error"),
        failed=record["one_cycle_result"]["result_status"] == "FAILED",
    )
    return record


def _validate_scheduler_daemon_bounded_loop_cycle_error(
    value: Any,
    *,
    failed: bool,
) -> dict[str, Any] | None:
    if value is None:
        if failed:
            raise ArtifactHandoffError(
                status_code=422,
                error_code=(
                    "ae.artifact_retention_scheduler_daemon_bounded_loop_result_invalid"
                ),
                detail=(
                    "Artifact retention scheduler daemon bounded loop cycle error "
                    "is required."
                ),
            )
        return None
    if not isinstance(value, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_bounded_loop_result_invalid",
            detail="Artifact retention scheduler daemon bounded loop cycle error is invalid.",
        )
    error = dict(value)
    if set(error) != {"error_code", "retryable"}:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_bounded_loop_result_invalid",
            detail="Artifact retention scheduler daemon bounded loop cycle error keys are invalid.",
        )
    error["error_code"] = _required_text(
        error.get("error_code"),
        "error_code",
        "ae.artifact_retention_scheduler_daemon_bounded_loop_result_invalid",
    )
    error["retryable"] = _required_bool(
        error.get("retryable"),
        "retryable",
        "ae.artifact_retention_scheduler_daemon_bounded_loop_result_invalid",
    )
    if not failed:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_bounded_loop_result_invalid",
            detail="Artifact retention scheduler daemon bounded loop cycle error is unexpected.",
        )
    return error


def _normalize_scheduler_daemon_bounded_loop_result_status(value: Any) -> str:
    status = optional_text(value)
    if status not in ARTIFACT_RETENTION_SCHEDULER_DAEMON_BOUNDED_LOOP_RESULT_STATUSES:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_bounded_loop_result_invalid",
            detail="Artifact retention scheduler daemon bounded loop status is invalid.",
        )
    return status


def _normalize_scheduler_daemon_bounded_loop_stop_reason(value: Any) -> str:
    reason = optional_text(value)
    if reason not in ARTIFACT_RETENTION_SCHEDULER_DAEMON_BOUNDED_LOOP_STOP_REASONS:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_bounded_loop_result_invalid",
            detail="Artifact retention scheduler daemon bounded loop stop reason is invalid.",
        )
    return reason


def _scheduler_daemon_bounded_loop_execution_plan(
    *,
    result_status: str,
    stop_reason: str,
    max_cycles: int,
    cycle_count: int,
    run_worker: bool,
) -> dict[str, Any]:
    return {
        "requires_ready_runtime": True,
        "bounded_loop_adapter_used": True,
        "max_cycles_required": True,
        "max_cycles_enforced": True,
        "max_cycles": max_cycles,
        "cycles_executed": cycle_count,
        "worker_requested": run_worker,
        "starts_continuous_loop": False,
        "uses_one_cycle_runner": cycle_count > 0,
        "runs_tick_once": result_status in {"SUCCEEDED", "STOPPED", "FAILED"}
        and cycle_count > 0,
        "stopped_by_max_cycles": stop_reason == "max_cycles_reached",
        "stopped_by_request": stop_reason == "stop_requested",
        "stopped_by_failure": stop_reason == "cycle_failed",
        "writes_database_directly": False,
        "physical_delete_enabled": False,
    }


def _scheduler_daemon_bounded_loop_guardrails() -> dict[str, bool]:
    return {
        "daemon_process_owner_ae": True,
        "bounded_loop_is_finite": True,
        "max_cycles_required": True,
        "max_cycles_enforced": True,
        "continuous_loop_started": False,
        "uses_one_cycle_runner": True,
        "retention_work_uses_job_queue": True,
        "direct_database_write_allowed": False,
        "physical_delete_automation_enabled": False,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
    }


def _scheduler_daemon_bounded_loop_metadata(
    *,
    result_status: str,
    stop_reason: str,
    cycle_results: list[dict[str, Any]],
    final_state: Mapping[str, Any],
) -> dict[str, bool]:
    return {
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
        "safe_for_ag_projection": True,
        "bounded_loop_started": len(cycle_results) > 0,
        "bounded_loop_finished": True,
        "continuous_loop_started": False,
        "stopped_by_max_cycles": stop_reason == "max_cycles_reached",
        "stopped_by_request": stop_reason == "stop_requested",
        "stopped_by_failure": stop_reason == "cycle_failed",
        "skipped_before_cycle": result_status == "SKIPPED",
        "tick_once_ran": any(
            item["one_cycle_result"]["tick_once_ran"] is True
            for item in cycle_results
        ),
        "job_enqueued": any(
            item["one_cycle_result"]["job_enqueued"] is True
            for item in cycle_results
        ),
        "worker_executed": any(
            item["one_cycle_result"]["worker_executed"] is True
            for item in cycle_results
        ),
        "history_write_executed": any(
            item["one_cycle_result"]["history_write_executed"] is True
            for item in cycle_results
        ),
        "final_state_error": final_state["lifecycle_status"] == "ERROR",
        "final_state_stopped": final_state["lifecycle_status"] == "STOPPED",
        "final_state_disabled": final_state["lifecycle_status"] == "DISABLED",
    }


def _scheduler_daemon_bounded_loop_result_id(
    *,
    scheduler_id: str,
    daemon_instance_id: str,
    started_at: str,
    finished_at: str,
    result_status: str,
    stop_reason: str,
    cycle_results: list[dict[str, Any]],
    final_state: Mapping[str, Any],
) -> str:
    basis = {
        "scheduler_id": scheduler_id,
        "daemon_instance_id": daemon_instance_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "result_status": result_status,
        "stop_reason": stop_reason,
        "cycle_result_ids": [
            item["one_cycle_result"]["daemon_one_cycle_result_id"]
            for item in cycle_results
        ],
        "final_state_id": final_state["daemon_runtime_state_id"],
    }
    return str(
        uuid5(
            NAMESPACE_URL,
            f"ae-artifact-retention-scheduler-daemon-bounded-loop:{sha256_json(basis)}",
        )
    )


def _scheduler_daemon_dispatch_guardrails() -> dict[str, bool]:
    guardrails = _scheduler_daemon_guardrails()
    return {
        **guardrails,
        "daemon_control_plan_required": True,
        "tick_once_requires_ready_control_plan": True,
        "start_stop_guardrail_required_for_start_stop": True,
        "start_stop_runtime_mutation_allowed": False,
        "stop_signal_allowed": False,
    }


def _scheduler_daemon_dispatch_metadata(
    *,
    control_plan: Mapping[str, Any],
    tick_once_result: Mapping[str, Any] | None,
    start_stop_guardrail: Mapping[str, Any] | None,
) -> dict[str, bool]:
    tick_metadata = (
        tick_once_result.get("metadata")
        if isinstance(tick_once_result, Mapping)
        else None
    )
    tick_metadata = tick_metadata if isinstance(tick_metadata, Mapping) else {}
    return {
        "metadata_only": True,
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "control_plan_ready": control_plan.get("decision_status") == "READY",
        "tick_once_dispatched": tick_once_result is not None,
        "start_stop_guardrail_evaluated": start_stop_guardrail is not None,
        "lease_acquired_before_tick": (
            tick_metadata.get("lease_acquired_before_tick") is True
        ),
        "lease_released": tick_metadata.get("lease_released") is True,
        "job_enqueued": tick_metadata.get("job_enqueued") is True,
        "worker_executed": tick_metadata.get("worker_executed") is True,
        "runtime_state_mutated": False,
        "stop_signal_sent": False,
        "scheduler_daemon_started": False,
        "continuous_loop_started": False,
        "physical_delete_automation_enabled": False,
    }


def _scheduler_daemon_control_metadata(
    action_item: Mapping[str, Any],
) -> dict[str, bool]:
    return {
        "metadata_only": True,
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "tick_once_dispatched": action_item.get("runs_tick_once") is True,
        "scheduler_daemon_started": False,
        "continuous_loop_started": False,
        "physical_delete_automation_enabled": False,
    }


def _scheduler_daemon_guardrails() -> dict[str, bool]:
    return {
        "metadata_only": True,
        "manual_tick_once_only": True,
        "lease_required_before_tick": True,
        "daemon_auto_start_allowed": False,
        "scheduler_daemon_started": False,
        "continuous_loop_started": False,
        "continuous_loop_allowed_before_lease": False,
        "physical_delete_automation_enabled": False,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
    }


def _scheduler_daemon_metadata() -> dict[str, bool]:
    return {
        "metadata_only": True,
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "scheduler_daemon_started": False,
        "continuous_loop_started": False,
        "physical_delete_automation_enabled": False,
    }


def _scheduler_daemon_runtime_config_guardrails() -> dict[str, bool]:
    return {
        "metadata_only": True,
        "test_profile_only": True,
        "explicit_opt_in_required": True,
        "daemon_disabled_by_default": True,
        "one_cycle_runner_required_before_loop": True,
        "lease_required_before_tick": True,
        "fencing_token_required": True,
        "daemon_auto_start_allowed": False,
        "scheduler_daemon_started": False,
        "continuous_loop_started": False,
        "continuous_loop_allowed_before_lease": False,
        "physical_delete_automation_enabled": False,
        "storage_mutation_enabled": False,
        "database_row_delete_enabled": False,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
    }


def _scheduler_daemon_runtime_config_metadata() -> dict[str, bool]:
    return {
        "metadata_only": True,
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
        "safe_for_ag_projection": True,
        "scheduler_daemon_started": False,
        "continuous_loop_started": False,
        "physical_delete_automation_enabled": False,
    }


def _scheduler_daemon_loop_plan_guardrails() -> dict[str, bool]:
    return {
        **_scheduler_daemon_runtime_config_guardrails(),
        "pure_planning_only": True,
        "lease_acquisition_performed": False,
        "job_enqueue_performed": False,
        "worker_execution_performed": False,
    }


def _scheduler_daemon_loop_plan_metadata(
    *,
    decision_status: str,
    decision_reason: str | None,
) -> dict[str, bool]:
    return {
        "metadata_only": True,
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
        "safe_for_ag_projection": True,
        "decision_ready": decision_status == "READY",
        "decision_blocked": decision_status == "BLOCKED",
        "decision_disabled": decision_status == "DISABLED",
        "decision_noop": decision_status == "NOOP",
        "decision_has_reason": decision_reason is not None,
        "lease_acquired": False,
        "job_enqueued": False,
        "worker_executed": False,
        "history_written": False,
        "scheduler_daemon_started": False,
        "continuous_loop_started": False,
        "physical_delete_automation_enabled": False,
    }


def _scheduler_daemon_one_cycle_guardrails() -> dict[str, bool]:
    return {
        **_scheduler_daemon_loop_plan_guardrails(),
        "one_cycle_only": True,
        "loop_plan_required": True,
        "tick_once_requires_ready_loop_plan": True,
        "daemon_heartbeat_optional": True,
        "daemon_heartbeat_failure_non_blocking": True,
    }


def _scheduler_daemon_heartbeat_store_observation(
    worker_heartbeat_store: Any | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if worker_heartbeat_store is None:
        return (
            {
                "available": False,
                "backend": "not_configured",
                "failure_code": "heartbeat_store_not_configured",
            },
            [],
        )
    backend = worker_heartbeat_store.__class__.__name__
    list_heartbeats = getattr(worker_heartbeat_store, "list_heartbeats", None)
    if list_heartbeats is None:
        return (
            {
                "available": False,
                "backend": backend,
                "failure_code": "heartbeat_store_invalid",
            },
            [],
        )
    try:
        raw_heartbeats = list_heartbeats(
            service_id="nex-ae-api",
            worker_type=AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_WORKER_TYPE,
        )
    except Exception:
        return (
            {
                "available": False,
                "backend": backend,
                "failure_code": "heartbeat_store_unavailable",
            },
            [],
        )
    if not isinstance(raw_heartbeats, list):
        return (
            {
                "available": False,
                "backend": backend,
                "failure_code": "heartbeat_store_invalid",
            },
            [],
        )
    return (
        {"available": True, "backend": backend, "failure_code": None},
        [dict(item) for item in raw_heartbeats if isinstance(item, Mapping)],
    )


def _latest_scheduler_daemon_heartbeat(
    heartbeats: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not heartbeats:
        return None
    return sorted(
        heartbeats,
        key=lambda heartbeat: (
            optional_text(heartbeat.get("last_seen_at")) or "",
            optional_text(heartbeat.get("worker_id")) or "",
        ),
        reverse=True,
    )[0]


def _project_scheduler_daemon_runtime_heartbeat(
    heartbeat: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(heartbeat, Mapping):
        return None
    return {
        "heartbeat_schema_version": optional_text(
            heartbeat.get("heartbeat_schema_version")
        ),
        "service_id": optional_text(heartbeat.get("service_id")),
        "worker_id": optional_text(heartbeat.get("worker_id")),
        "worker_type": optional_text(heartbeat.get("worker_type")),
        "status": optional_text(heartbeat.get("status")),
        "active_job_id": optional_text(heartbeat.get("active_job_id")),
        "trace_id": optional_text(heartbeat.get("trace_id")),
        "started_at": optional_text(heartbeat.get("started_at")),
        "last_seen_at": optional_text(heartbeat.get("last_seen_at")),
        "metadata": _scheduler_daemon_runtime_heartbeat_metadata(
            heartbeat.get("metadata")
        ),
    }


def _scheduler_daemon_runtime_heartbeat_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {
        "scheduler_id": optional_text(value.get("scheduler_id")),
        "daemon_loop_plan_id": optional_text(value.get("daemon_loop_plan_id")),
        "phase": optional_text(value.get("phase")),
        "loop_decision_status": optional_text(value.get("loop_decision_status")),
        "loop_decision_reason": optional_text(value.get("loop_decision_reason")),
        "tick_once_result_status": optional_text(
            value.get("tick_once_result_status")
        ),
        "tick_once_skip_reason": optional_text(value.get("tick_once_skip_reason")),
        "one_cycle_only": value.get("one_cycle_only") is True,
        "scheduler_daemon_started": value.get("scheduler_daemon_started") is True,
        "continuous_loop_started": value.get("continuous_loop_started") is True,
        "physical_delete_automation_enabled": (
            value.get("physical_delete_automation_enabled") is True
        ),
    }


def _emit_scheduler_daemon_heartbeat(
    daemon_heartbeat_emitter: Any | None,
    *,
    status: str,
    active_job_id: str | None = None,
    trace_id: str | None = None,
    observed_at: str,
    metadata: Mapping[str, Any],
) -> dict[str, Any] | None:
    if daemon_heartbeat_emitter is None:
        return None
    safe_emit = getattr(daemon_heartbeat_emitter, "safe_emit", None)
    if safe_emit is None:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_heartbeat_invalid",
            detail="Artifact retention scheduler daemon heartbeat emitter is invalid.",
        )
    result = safe_emit(
        status=status,
        active_job_id=active_job_id,
        trace_id=trace_id,
        metadata=dict(metadata),
        observed_at=observed_at,
    )
    to_summary = getattr(result, "to_summary", None)
    if to_summary is None:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_heartbeat_invalid",
            detail="Artifact retention scheduler daemon heartbeat result is invalid.",
        )
    return _validate_scheduler_daemon_heartbeat_summary(to_summary())


def _append_scheduler_daemon_heartbeat_result(
    daemon_heartbeat_results: list[dict[str, Any]],
    result: dict[str, Any] | None,
) -> None:
    if result is not None:
        daemon_heartbeat_results.append(result)


def _scheduler_daemon_heartbeat_metadata(
    *,
    loop_plan: Mapping[str, Any],
    phase: str,
    tick_once_result: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = {
        "scheduler_id": loop_plan["scheduler_id"],
        "daemon_loop_plan_id": loop_plan["daemon_loop_plan_id"],
        "phase": phase,
        "loop_decision_status": loop_plan["decision_status"],
        "loop_decision_reason": loop_plan["decision_reason"],
        "one_cycle_only": True,
        "scheduler_daemon_started": False,
        "continuous_loop_started": False,
        "physical_delete_automation_enabled": False,
    }
    if isinstance(tick_once_result, Mapping):
        metadata["tick_once_result_status"] = tick_once_result.get("result_status")
        metadata["tick_once_skip_reason"] = tick_once_result.get("skip_reason")
    return metadata


def _scheduler_daemon_one_cycle_heartbeat_final_status(
    *,
    loop_plan: Mapping[str, Any],
    tick_once_result: Mapping[str, Any] | None,
) -> str:
    if isinstance(tick_once_result, Mapping):
        return "ERROR" if tick_once_result.get("result_status") == "FAILED" else "IDLE"
    return "IDLE" if loop_plan.get("decision_status") != "READY" else "ERROR"


def _validate_scheduler_daemon_heartbeat_results(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_heartbeat_invalid",
            detail="Artifact retention scheduler daemon heartbeat results must be a list.",
        )
    return [_validate_scheduler_daemon_heartbeat_summary(item) for item in value]


def _validate_scheduler_daemon_heartbeat_summary(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_heartbeat_invalid",
            detail="Artifact retention scheduler daemon heartbeat summary must be an object.",
        )
    summary = dict(value)
    ok = _required_bool(
        summary.get("ok"),
        "ok",
        "ae.artifact_retention_scheduler_daemon_heartbeat_invalid",
    )
    if ok:
        if set(summary) != {
            "ok",
            "service_id",
            "worker_id",
            "worker_type",
            "status",
            "active_job_id",
        }:
            raise ArtifactHandoffError(
                status_code=422,
                error_code="ae.artifact_retention_scheduler_daemon_heartbeat_invalid",
                detail="Artifact retention scheduler daemon heartbeat keys are invalid.",
            )
        if summary.get("service_id") != "nex-ae-api":
            raise ArtifactHandoffError(
                status_code=422,
                error_code="ae.artifact_retention_scheduler_daemon_heartbeat_invalid",
                detail="Artifact retention scheduler daemon heartbeat service is invalid.",
            )
        if (
            summary.get("worker_type")
            != AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_WORKER_TYPE
        ):
            raise ArtifactHandoffError(
                status_code=422,
                error_code="ae.artifact_retention_scheduler_daemon_heartbeat_invalid",
                detail="Artifact retention scheduler daemon heartbeat worker type is invalid.",
            )
        _required_text(
            summary.get("worker_id"),
            "worker_id",
            "ae.artifact_retention_scheduler_daemon_heartbeat_invalid",
        )
        if summary.get("status") not in {"STARTING", "BUSY", "IDLE", "ERROR"}:
            raise ArtifactHandoffError(
                status_code=422,
                error_code="ae.artifact_retention_scheduler_daemon_heartbeat_invalid",
                detail="Artifact retention scheduler daemon heartbeat status is invalid.",
            )
        active_job_id = summary.get("active_job_id")
        if active_job_id is not None:
            _required_text(
                active_job_id,
                "active_job_id",
                "ae.artifact_retention_scheduler_daemon_heartbeat_invalid",
            )
        return summary
    if set(summary) != {"ok", "error_code", "detail", "status_code"}:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_heartbeat_invalid",
            detail="Artifact retention scheduler daemon heartbeat failure keys are invalid.",
        )
    _required_text(
        summary.get("error_code"),
        "error_code",
        "ae.artifact_retention_scheduler_daemon_heartbeat_invalid",
    )
    _required_text(
        summary.get("detail"),
        "detail",
        "ae.artifact_retention_scheduler_daemon_heartbeat_invalid",
    )
    summary["status_code"] = _positive_int(
        summary.get("status_code"),
        "status_code",
        "ae.artifact_retention_scheduler_daemon_heartbeat_invalid",
    )
    return summary


def _scheduler_daemon_one_cycle_metadata(
    *,
    loop_plan: Mapping[str, Any],
    tick_once_result: Mapping[str, Any] | None,
    daemon_heartbeat_results: list[dict[str, Any]],
) -> dict[str, bool]:
    tick_metadata = (
        tick_once_result.get("metadata")
        if isinstance(tick_once_result, Mapping)
        else None
    )
    tick_metadata = tick_metadata if isinstance(tick_metadata, Mapping) else {}
    return {
        "metadata_only": True,
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
        "safe_for_ag_projection": True,
        "loop_plan_ready": loop_plan.get("decision_status") == "READY",
        "tick_once_ran": tick_once_result is not None,
        "daemon_heartbeat_emitted": bool(daemon_heartbeat_results),
        "daemon_heartbeat_failed": any(
            result.get("ok") is False for result in daemon_heartbeat_results
        ),
        "daemon_heartbeat_error_observed": any(
            result.get("status") == "ERROR" for result in daemon_heartbeat_results
        ),
        "skipped_before_tick": (
            tick_once_result is None and loop_plan.get("decision_status") != "READY"
        ),
        "lease_acquired_before_tick": (
            tick_metadata.get("lease_acquired_before_tick") is True
        ),
        "lease_released": tick_metadata.get("lease_released") is True,
        "job_enqueued": tick_metadata.get("job_enqueued") is True,
        "worker_executed": tick_metadata.get("worker_executed") is True,
        "history_write_executed": (
            tick_metadata.get("history_write_executed") is True
        ),
        "scheduler_daemon_started": False,
        "continuous_loop_started": False,
        "physical_delete_automation_enabled": False,
    }


def _scheduler_daemon_start_stop_guardrails() -> dict[str, bool]:
    return {
        **_scheduler_daemon_guardrails(),
        "start_stop_control_guardrail_required": True,
        "start_control_enabled": False,
        "stop_control_enabled": False,
        "start_daemon_allowed": False,
        "stop_runtime_mutation_allowed": False,
        "stop_signal_allowed": False,
        "runtime_state_mutation_allowed": False,
        "future_supervisor_required_before_start": True,
    }


def _scheduler_daemon_start_stop_metadata(
    *,
    control_plan: Mapping[str, Any],
    guardrail_status: str,
    guardrail_reason: str,
) -> dict[str, bool]:
    action = control_plan.get("action")
    return {
        "metadata_only": True,
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "safe_for_ag_projection": True,
        "start_stop_guardrail_evaluated": True,
        "start_action": (
            action == ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONTROL_ACTION_START_DAEMON
        ),
        "stop_action": (
            action == ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONTROL_ACTION_STOP_DAEMON
        ),
        "guardrail_blocked": guardrail_status == "BLOCKED",
        "guardrail_noop": guardrail_status == "NOOP",
        "policy_reason_present": bool(guardrail_reason),
        "action_allowed": False,
        "runtime_state_mutated": False,
        "stop_signal_sent": False,
        "tick_once_dispatched": False,
        "lease_acquired_before_tick": False,
        "lease_released": False,
        "job_enqueued": False,
        "worker_executed": False,
        "history_write_executed": False,
        "scheduler_daemon_started": False,
        "continuous_loop_started": False,
        "physical_delete_automation_enabled": False,
    }


def _scheduler_lease_guardrails() -> dict[str, bool]:
    return {
        "lease_required_before_tick": True,
        "manual_once_runner": True,
        "daemon_auto_start_allowed": False,
        "scheduler_daemon_started": False,
        "continuous_loop_started": False,
        "continuous_loop_allowed_before_lease": False,
        "physical_delete_automation_enabled": False,
    }


def _scheduler_lease_metadata() -> dict[str, bool]:
    return {
        "metadata_only": True,
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "job_enqueued": False,
        "worker_executed": False,
    }


def _request_time_from_config(config: Mapping[str, Any]) -> str:
    return str(config.get("checked_at") or "2026-09-01T00:00:00Z")


def _lease_token(request: Mapping[str, Any], *, fencing_token: int) -> str:
    basis = {
        "scheduler_id": request["scheduler_id"],
        "lease_owner_id": request["lease_owner_id"],
        "operation": request["operation"],
        "requested_at": request["requested_at"],
        "fencing_token": fencing_token,
        "idempotency_key": request["idempotency_key"],
    }
    return str(uuid5(NAMESPACE_URL, f"ae-artifact-retention-lease:{sha256_json(basis)}"))


def _lease_record_id(*, scheduler_id: str, lease_token: str) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            f"ae-artifact-retention-lease-record:{scheduler_id}:{lease_token}",
        )
    )


def _required_text(value: Any, field_name: str, error_code: str) -> str:
    normalized = optional_text(value)
    if normalized is None:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=f"{field_name} is required for artifact retention scheduler lease.",
        )
    return normalized


def _required_bool(value: Any, field_name: str, error_code: str) -> bool:
    if not isinstance(value, bool):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=f"{field_name} must be a boolean.",
        )
    return value


def _bounded_positive_int(
    value: Any,
    field_name: str,
    error_code: str,
    *,
    max_value: int,
) -> int:
    normalized = _positive_int(value, field_name, error_code)
    if normalized > max_value:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=f"{field_name} exceeds the supported maximum.",
        )
    return normalized


def _non_negative_int(value: Any, field_name: str, error_code: str) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=f"{field_name} must be a non-negative integer.",
        ) from exc
    if normalized < 0:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=f"{field_name} must be a non-negative integer.",
        )
    return normalized


def _positive_int(value: Any, field_name: str, error_code: str) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=f"{field_name} must be a positive integer.",
        ) from exc
    if normalized < 1:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=f"{field_name} must be a positive integer.",
        )
    return normalized
