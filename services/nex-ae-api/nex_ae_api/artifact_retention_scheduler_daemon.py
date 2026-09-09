from __future__ import annotations

import argparse
import json
import os
import sys
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Callable, Mapping, Protocol, Sequence, TextIO
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from nex_ae_api.artifact_retention_scheduler import (
    build_artifact_retention_scheduler_daemon_config,
    build_artifact_retention_scheduler_daemon_runtime_config,
    build_artifact_retention_scheduler_daemon_runtime_state,
    build_artifact_retention_scheduler_daemon_shutdown_transition,
    run_artifact_retention_scheduler_daemon_bounded_loop,
    summarize_artifact_retention_scheduler_daemon_bounded_loop_result,
    summarize_artifact_retention_scheduler_daemon_runtime_state,
    summarize_artifact_retention_scheduler_daemon_shutdown_transition,
    validate_artifact_retention_scheduler_daemon_config,
    validate_artifact_retention_scheduler_daemon_bounded_loop_result,
    validate_artifact_retention_scheduler_daemon_runtime_config,
    validate_artifact_retention_scheduler_daemon_runtime_state,
    validate_artifact_retention_scheduler_daemon_shutdown_transition,
)
from nex_ae_api.artifacts import (
    ArtifactHandoffError,
    assert_artifact_retention_payload_safe,
    build_artifact_retention_scheduler_config,
    optional_text,
    sha256_json,
)


AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_PLAN_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_cli_plan.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_EXECUTE_COMMAND_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_cli_execute_command.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_PROCESS_LOCK_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_process_lock.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUN_METADATA_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_run_metadata.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SIGNAL_SHUTDOWN_ADAPTER_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_signal_shutdown_adapter.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_EXECUTION_RESULT_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_cli_execution_result.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUN_RECORD_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_run_record.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_LIFECYCLE_EVENT_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_lifecycle_event.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUN_COLLECTION_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_run_collection.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUN_DETAIL_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_run_detail.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_COMMAND_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_supervisor_command.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_RESULT_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_supervisor_result.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_RECORD_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_supervisor_record.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_EVENT_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_supervisor_event.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_DISPATCH_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_supervisor_dispatch.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_COLLECTION_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_supervisor_collection.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_DETAIL_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_supervisor_detail.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_supervised_process.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_RECORD_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_supervised_process_record.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_EVENT_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_supervised_process_event.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_DISPATCH_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_supervised_process_dispatch.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_COLLECTION_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_supervised_process_collection.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_DETAIL_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_supervised_process_detail.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_POLICY_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_operator_control_policy.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_REQUEST_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_operator_control_request.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_ADMISSION_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_operator_control_admission.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_COMMAND_PREVIEW_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_operator_control_command_preview.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_FACADE_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_operator_control_facade.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_REQUEST_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_operator_control_execution_request.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_RESULT_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_operator_control_execution_result.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_STATE_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_operator_control_execution_state.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_STATE_TRANSITION_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_operator_control_execution_state_transition.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_COLLECTION_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_operator_control_execution_collection.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_DETAIL_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_operator_control_execution_detail.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_PLAN_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_plan.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_COMMAND_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_command.v1"
)
DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ENTRYPOINT = (
    "python -m nex_ae_api.artifact_retention_scheduler_daemon"
)
MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_MAX_CYCLES = 100
MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_PROCESS_ID = 2_147_483_647
MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_PROCESS_LOCK_STALE_AFTER_SECONDS = 86_400
MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUN_COLLECTION_LIMIT = 100
MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_RECORD_LIMIT = 100
MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_RECORD_LIMIT = 100
MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_STATE_LIMIT = 100
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_EXECUTE_MODE = "bounded_loop"
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_PROCESS_LOCK_SCOPE = (
    "ae_artifact_retention_scheduler_daemon"
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_PROCESS_LOCK_STATUS = "READY_TO_ACQUIRE"
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUN_STATUSES = frozenset(
    {"PENDING", "RUNNING", "STOPPING", "SUCCEEDED", "FAILED"}
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RESULT_STATUSES = frozenset(
    {"SUCCEEDED", "FAILED", "STOPPED", "SKIPPED"}
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_LIFECYCLE_EVENT_TYPES = frozenset(
    {"RUN_STARTED", "RUN_COMPLETED"}
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SHUTDOWN_SIGNALS = frozenset(
    {"SIGINT", "SIGTERM"}
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_ACTIONS = frozenset(
    {"status_probe", "start_daemon", "stop_daemon"}
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_RESULT_STATUSES = frozenset(
    {"READY", "BLOCKED", "NOOP", "FAILED"}
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_STATUSES = frozenset(
    {
        "MISSING",
        "START_REQUESTED",
        "RUNNING",
        "STOP_REQUESTED",
        "STOPPED",
        "EXITED",
        "STALE",
        "FAILED",
        "BLOCKED",
    }
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_ACTIONS = frozenset(
    {"status_probe", "start_daemon", "stop_daemon", "restart_daemon"}
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_MUTATING_ACTIONS = frozenset(
    {"start_daemon", "stop_daemon", "restart_daemon"}
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_ADMISSION_STATUSES = frozenset(
    {"READY", "BLOCKED", "NOOP"}
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_MODES = frozenset(
    {"contract_only", "fake_dry_run_supervisor_persistent_dispatch"}
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_STATUSES = frozenset(
    {"READY", "BLOCKED", "NOOP"}
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_STATE_STATUSES = (
    frozenset({"ADMITTED", "EXECUTING", "SUCCEEDED", "FAILED", "BLOCKED", "NOOP"})
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_IDEMPOTENCY_STATUSES = (
    frozenset({"NEW", "REPLAYED", "CONFLICT"})
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_PLAN_STATUSES = (
    frozenset({"READY", "BLOCKED"})
)
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_COMMAND_STATUSES = (
    frozenset({"READY", "BLOCKED"})
)
DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_MODE = "fake_dry_run"
DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_ADAPTER_NAME = (
    "fake_dry_run_supervisor"
)
DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_START_BLOCK_REASON = (
    "supervisor_adapter_not_configured"
)
DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_MODE = (
    "bounded_loop_subprocess_test_only"
)


class ArtifactRetentionSchedulerDaemonSupervisorAdapter(Protocol):
    adapter_name: str

    def execute_supervisor_command(
        self,
        supervisor_command: Mapping[str, Any],
        *,
        observed_at: str | None = None,
    ) -> dict[str, Any]: ...


def build_artifact_retention_scheduler_daemon_cli_plan(
    *,
    scheduler_config: Mapping[str, Any] | None = None,
    profile: str = "test",
    enabled: bool = False,
    explicit_opt_in: bool = False,
    checked_at: str | None = None,
    interval_seconds: int | str | None = None,
    jitter_seconds: int | str | None = None,
    backoff_seconds: int | str | None = None,
    max_cycles: int | str = 1,
    run_worker: bool = False,
    output_format: str = "json",
) -> dict[str, Any]:
    config = (
        dict(scheduler_config)
        if scheduler_config is not None
        else build_artifact_retention_scheduler_config()
    )
    normalized_max_cycles = _bounded_positive_int(
        max_cycles,
        "max_cycles",
        max_value=MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_MAX_CYCLES,
    )
    normalized_run_worker = _required_bool(run_worker, "run_worker")
    normalized_output_format = _normalize_output_format(output_format)
    runtime_config = build_artifact_retention_scheduler_daemon_runtime_config(
        scheduler_config=config,
        profile=profile,
        enabled=enabled,
        explicit_opt_in=explicit_opt_in,
        checked_at=checked_at,
        interval_seconds=interval_seconds,
        jitter_seconds=jitter_seconds,
        backoff_seconds=backoff_seconds,
    )
    daemon_config = build_artifact_retention_scheduler_daemon_config(
        scheduler_config=config,
        checked_at=runtime_config["checked_at"],
    )
    lifecycle_status = (
        "STARTING"
        if runtime_config["enablement"]["enablement_status"] == "READY"
        else "DISABLED"
    )
    runtime_state = build_artifact_retention_scheduler_daemon_runtime_state(
        scheduler_config=config,
        runtime_config=runtime_config,
        daemon_config=daemon_config,
        lifecycle_status=lifecycle_status,
        lifecycle_reason=None,
        observed_at=runtime_config["checked_at"],
    )
    command = {
        "entrypoint": DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ENTRYPOINT,
        "profile": runtime_config["enablement"]["profile"],
        "enabled": runtime_config["enablement"]["enabled"],
        "explicit_opt_in": runtime_config["enablement"]["explicit_opt_in"],
        "checked_at": runtime_config["checked_at"],
        "max_cycles": normalized_max_cycles,
        "run_worker": normalized_run_worker,
        "output_format": normalized_output_format,
        "plan_only": True,
    }
    plan = {
        "daemon_cli_plan_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_PLAN_SCHEMA_VERSION
        ),
        "daemon_cli_plan_id": _daemon_cli_plan_id(
            scheduler_id=runtime_config["scheduler_id"],
            command=command,
            runtime_state=runtime_state,
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": runtime_config["scheduler_id"],
        "command": command,
        "runtime_config": deepcopy(runtime_config),
        "daemon_config": deepcopy(daemon_config),
        "runtime_state": deepcopy(runtime_state),
        "execution_plan": _daemon_cli_execution_plan(
            run_worker=normalized_run_worker,
            ready_to_start=runtime_config["enablement"]["enablement_status"] == "READY",
        ),
        "guardrails": _daemon_cli_guardrails(),
        "metadata": _daemon_cli_metadata(
            runtime_config=runtime_config,
            runtime_state=runtime_state,
            command=command,
        ),
    }
    return validate_artifact_retention_scheduler_daemon_cli_plan(plan)


def validate_artifact_retention_scheduler_daemon_cli_plan(
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(plan, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
            detail="Artifact retention scheduler daemon CLI plan must be an object.",
        )
    normalized = dict(plan)
    if set(normalized) != {
        "daemon_cli_plan_schema_version",
        "daemon_cli_plan_id",
        "service_id",
        "scheduler_id",
        "command",
        "runtime_config",
        "daemon_config",
        "runtime_state",
        "execution_plan",
        "guardrails",
        "metadata",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
            detail="Artifact retention scheduler daemon CLI plan keys are invalid.",
        )
    if (
        normalized.get("daemon_cli_plan_schema_version")
        != AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_PLAN_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_cli_plan_schema_invalid",
            detail="Artifact retention scheduler daemon CLI plan schema is invalid.",
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
            detail="Artifact retention scheduler daemon CLI plan service id is invalid.",
        )
    scheduler_id = _required_text(normalized.get("scheduler_id"), "scheduler_id")
    command = _validate_daemon_cli_command(normalized.get("command"))
    runtime_config = validate_artifact_retention_scheduler_daemon_runtime_config(
        normalized.get("runtime_config")
    )
    daemon_config = validate_artifact_retention_scheduler_daemon_config(
        normalized.get("daemon_config")
    )
    runtime_state = validate_artifact_retention_scheduler_daemon_runtime_state(
        normalized.get("runtime_state")
    )
    if scheduler_id != runtime_config["scheduler_id"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
            detail="Artifact retention scheduler daemon CLI plan scope is invalid.",
        )
    if daemon_config["scheduler_id"] != scheduler_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
            detail="Artifact retention scheduler daemon CLI plan daemon scope is invalid.",
        )
    if runtime_state["scheduler_id"] != scheduler_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
            detail="Artifact retention scheduler daemon CLI plan state scope is invalid.",
        )
    _validate_daemon_cli_command_matches_runtime(
        command=command,
        runtime_config=runtime_config,
    )
    expected_lifecycle_status = (
        "STARTING"
        if runtime_config["enablement"]["enablement_status"] == "READY"
        else "DISABLED"
    )
    if runtime_state["lifecycle_status"] != expected_lifecycle_status:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
            detail="Artifact retention scheduler daemon CLI plan state lifecycle is invalid.",
        )
    expected_execution_plan = _daemon_cli_execution_plan(
        run_worker=command["run_worker"],
        ready_to_start=runtime_config["enablement"]["enablement_status"] == "READY",
    )
    if normalized.get("execution_plan") != expected_execution_plan:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
            detail="Artifact retention scheduler daemon CLI execution plan is invalid.",
        )
    if normalized.get("guardrails") != _daemon_cli_guardrails():
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
            detail="Artifact retention scheduler daemon CLI guardrails are invalid.",
        )
    expected_metadata = _daemon_cli_metadata(
        runtime_config=runtime_config,
        runtime_state=runtime_state,
        command=command,
    )
    if normalized.get("metadata") != expected_metadata:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
            detail="Artifact retention scheduler daemon CLI metadata is invalid.",
        )
    expected_id = _daemon_cli_plan_id(
        scheduler_id=scheduler_id,
        command=command,
        runtime_state=runtime_state,
    )
    if normalized.get("daemon_cli_plan_id") != expected_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
            detail="Artifact retention scheduler daemon CLI plan id is invalid.",
        )
    normalized["command"] = command
    normalized["runtime_config"] = runtime_config
    normalized["daemon_config"] = daemon_config
    normalized["runtime_state"] = runtime_state
    assert_artifact_retention_payload_safe(normalized)
    return normalized


def build_artifact_retention_scheduler_daemon_cli_execute_command(
    *,
    scheduler_config: Mapping[str, Any] | None = None,
    profile: str = "test",
    enabled: bool = False,
    explicit_opt_in: bool = False,
    checked_at: str | None = None,
    interval_seconds: int | str | None = None,
    jitter_seconds: int | str | None = None,
    backoff_seconds: int | str | None = None,
    max_cycles: int | str = 1,
    run_worker: bool = False,
    output_format: str = "json",
) -> dict[str, Any]:
    config = (
        dict(scheduler_config)
        if scheduler_config is not None
        else build_artifact_retention_scheduler_config()
    )
    normalized_max_cycles = _bounded_positive_int(
        max_cycles,
        "max_cycles",
        max_value=MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_MAX_CYCLES,
        error_code="ae.artifact_retention_scheduler_daemon_cli_execute_command_invalid",
    )
    normalized_run_worker = _required_bool(
        run_worker,
        "run_worker",
        error_code="ae.artifact_retention_scheduler_daemon_cli_execute_command_invalid",
    )
    normalized_output_format = _normalize_output_format(
        output_format,
        error_code="ae.artifact_retention_scheduler_daemon_cli_execute_command_invalid",
    )
    runtime_config = build_artifact_retention_scheduler_daemon_runtime_config(
        scheduler_config=config,
        profile=profile,
        enabled=enabled,
        explicit_opt_in=explicit_opt_in,
        checked_at=checked_at,
        interval_seconds=interval_seconds,
        jitter_seconds=jitter_seconds,
        backoff_seconds=backoff_seconds,
    )
    if runtime_config["enablement"]["enablement_status"] != "READY":
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_cli_execute_command_invalid",
            detail=(
                "Artifact retention scheduler daemon CLI execute command requires "
                "test profile, enabled runtime, and explicit opt-in."
            ),
        )
    daemon_config = build_artifact_retention_scheduler_daemon_config(
        scheduler_config=config,
        checked_at=runtime_config["checked_at"],
    )
    runtime_state = build_artifact_retention_scheduler_daemon_runtime_state(
        scheduler_config=config,
        runtime_config=runtime_config,
        daemon_config=daemon_config,
        lifecycle_status="STARTING",
        lifecycle_reason=None,
        observed_at=runtime_config["checked_at"],
    )
    command = {
        "entrypoint": DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ENTRYPOINT,
        "mode": AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_EXECUTE_MODE,
        "profile": runtime_config["enablement"]["profile"],
        "enabled": runtime_config["enablement"]["enabled"],
        "explicit_opt_in": runtime_config["enablement"]["explicit_opt_in"],
        "checked_at": runtime_config["checked_at"],
        "max_cycles": normalized_max_cycles,
        "run_worker": normalized_run_worker,
        "output_format": normalized_output_format,
        "plan_only": False,
    }
    execute_command = {
        "daemon_cli_execute_command_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_EXECUTE_COMMAND_SCHEMA_VERSION
        ),
        "daemon_cli_execute_command_id": _daemon_cli_execute_command_id(
            scheduler_id=runtime_config["scheduler_id"],
            command=command,
            runtime_state=runtime_state,
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": runtime_config["scheduler_id"],
        "command": command,
        "runtime_config": deepcopy(runtime_config),
        "daemon_config": deepcopy(daemon_config),
        "runtime_state": deepcopy(runtime_state),
        "execution_plan": _daemon_cli_execute_command_execution_plan(
            run_worker=normalized_run_worker
        ),
        "guardrails": _daemon_cli_execute_command_guardrails(),
        "metadata": _daemon_cli_execute_command_metadata(
            runtime_config=runtime_config,
            runtime_state=runtime_state,
            command=command,
        ),
    }
    return validate_artifact_retention_scheduler_daemon_cli_execute_command(
        execute_command
    )


def validate_artifact_retention_scheduler_daemon_cli_execute_command(
    execute_command: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(execute_command, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_cli_execute_command_invalid",
            detail=(
                "Artifact retention scheduler daemon CLI execute command must be "
                "an object."
            ),
        )
    normalized = dict(execute_command)
    if set(normalized) != {
        "daemon_cli_execute_command_schema_version",
        "daemon_cli_execute_command_id",
        "service_id",
        "scheduler_id",
        "command",
        "runtime_config",
        "daemon_config",
        "runtime_state",
        "execution_plan",
        "guardrails",
        "metadata",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_cli_execute_command_invalid",
            detail=(
                "Artifact retention scheduler daemon CLI execute command keys "
                "are invalid."
            ),
        )
    if (
        normalized.get("daemon_cli_execute_command_schema_version")
        != AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_EXECUTE_COMMAND_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_cli_execute_command_schema_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon CLI execute command schema "
                "is invalid."
            ),
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_cli_execute_command_invalid",
            detail=(
                "Artifact retention scheduler daemon CLI execute command service "
                "id is invalid."
            ),
        )
    scheduler_id = _required_text(
        normalized.get("scheduler_id"),
        "scheduler_id",
        error_code="ae.artifact_retention_scheduler_daemon_cli_execute_command_invalid",
    )
    command = _validate_daemon_cli_execute_command(normalized.get("command"))
    runtime_config = validate_artifact_retention_scheduler_daemon_runtime_config(
        normalized.get("runtime_config")
    )
    daemon_config = validate_artifact_retention_scheduler_daemon_config(
        normalized.get("daemon_config")
    )
    runtime_state = validate_artifact_retention_scheduler_daemon_runtime_state(
        normalized.get("runtime_state")
    )
    if scheduler_id != runtime_config["scheduler_id"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_cli_execute_command_invalid",
            detail=(
                "Artifact retention scheduler daemon CLI execute command scope "
                "is invalid."
            ),
        )
    if daemon_config["scheduler_id"] != scheduler_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_cli_execute_command_invalid",
            detail=(
                "Artifact retention scheduler daemon CLI execute command daemon "
                "scope is invalid."
            ),
        )
    if runtime_state["scheduler_id"] != scheduler_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_cli_execute_command_invalid",
            detail=(
                "Artifact retention scheduler daemon CLI execute command state "
                "scope is invalid."
            ),
        )
    _validate_daemon_cli_command_matches_runtime(
        command=command,
        runtime_config=runtime_config,
        error_code="ae.artifact_retention_scheduler_daemon_cli_execute_command_invalid",
        detail_prefix="Artifact retention scheduler daemon CLI execute command",
    )
    if runtime_state["lifecycle_status"] != "STARTING":
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_cli_execute_command_invalid",
            detail=(
                "Artifact retention scheduler daemon CLI execute command state "
                "lifecycle is invalid."
            ),
        )
    expected_execution_plan = _daemon_cli_execute_command_execution_plan(
        run_worker=command["run_worker"]
    )
    if normalized.get("execution_plan") != expected_execution_plan:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_cli_execute_command_invalid",
            detail=(
                "Artifact retention scheduler daemon CLI execute command "
                "execution plan is invalid."
            ),
        )
    if normalized.get("guardrails") != _daemon_cli_execute_command_guardrails():
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_cli_execute_command_invalid",
            detail=(
                "Artifact retention scheduler daemon CLI execute command "
                "guardrails are invalid."
            ),
        )
    expected_metadata = _daemon_cli_execute_command_metadata(
        runtime_config=runtime_config,
        runtime_state=runtime_state,
        command=command,
    )
    if normalized.get("metadata") != expected_metadata:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_cli_execute_command_invalid",
            detail=(
                "Artifact retention scheduler daemon CLI execute command "
                "metadata is invalid."
            ),
        )
    expected_id = _daemon_cli_execute_command_id(
        scheduler_id=scheduler_id,
        command=command,
        runtime_state=runtime_state,
    )
    if normalized.get("daemon_cli_execute_command_id") != expected_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_cli_execute_command_invalid",
            detail=(
                "Artifact retention scheduler daemon CLI execute command id "
                "is invalid."
            ),
        )
    normalized["command"] = command
    normalized["runtime_config"] = runtime_config
    normalized["daemon_config"] = daemon_config
    normalized["runtime_state"] = runtime_state
    assert_artifact_retention_payload_safe(normalized)
    return normalized


def summarize_artifact_retention_scheduler_daemon_cli_execute_command(
    execute_command: Mapping[str, Any],
) -> dict[str, Any]:
    validated = validate_artifact_retention_scheduler_daemon_cli_execute_command(
        execute_command
    )
    state_summary = summarize_artifact_retention_scheduler_daemon_runtime_state(
        validated["runtime_state"]
    )
    return {
        "scheduler_id": validated["scheduler_id"],
        "entrypoint": validated["command"]["entrypoint"],
        "mode": validated["command"]["mode"],
        "profile": validated["command"]["profile"],
        "max_cycles": validated["command"]["max_cycles"],
        "run_worker": validated["command"]["run_worker"],
        "output_format": validated["command"]["output_format"],
        "plan_only": validated["command"]["plan_only"],
        "ready_to_start": validated["metadata"]["ready_to_start"],
        "lifecycle_status": state_summary["lifecycle_status"],
        "lifecycle_reason": state_summary["lifecycle_reason"],
        "bounded_loop_requested": validated["execution_plan"][
            "starts_bounded_loop"
        ],
        "database_url_required": validated["guardrails"]["database_url_required"],
        "database_url_included": validated["metadata"]["database_url_included"],
        "process_lock_required": validated["guardrails"]["process_lock_required"],
        "shutdown_signal_adapter_required": validated["guardrails"][
            "shutdown_signal_adapter_required"
        ],
        "physical_delete_automation_enabled": validated["guardrails"][
            "physical_delete_automation_enabled"
        ],
    }


def execute_command_summary_line(execute_command: Mapping[str, Any]) -> str:
    summary = summarize_artifact_retention_scheduler_daemon_cli_execute_command(
        execute_command
    )
    return (
        "ae_scheduler_daemon_cli_execute_command=pass "
        f"scheduler_id={summary['scheduler_id']} "
        f"profile={summary['profile']} "
        f"mode={summary['mode']} "
        f"lifecycle={summary['lifecycle_status']} "
        f"reason={summary['lifecycle_reason']} "
        f"max_cycles={summary['max_cycles']} "
        f"plan_only={int(summary['plan_only'])} "
        f"bounded_loop_requested={int(summary['bounded_loop_requested'])}"
    )


def build_artifact_retention_scheduler_daemon_operator_control_policy(
    *,
    scheduler_config: Mapping[str, Any] | None = None,
    checked_at: str | None = None,
) -> dict[str, Any]:
    config = (
        dict(scheduler_config)
        if scheduler_config is not None
        else build_artifact_retention_scheduler_config()
    )
    daemon_config = build_artifact_retention_scheduler_daemon_config(
        scheduler_config=config,
        checked_at=checked_at,
    )
    normalized_checked_at = _required_text(
        daemon_config.get("checked_at"),
        "checked_at",
        error_code="ae.artifact_retention_scheduler_daemon_operator_control_policy_invalid",
    )
    scheduler_id = _required_text(
        daemon_config.get("scheduler_id"),
        "scheduler_id",
        error_code="ae.artifact_retention_scheduler_daemon_operator_control_policy_invalid",
    )
    policy = {
        "operator_control_policy_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_POLICY_SCHEMA_VERSION
        ),
        "operator_control_policy_id": _operator_control_policy_id(
            scheduler_id=scheduler_id,
            checked_at=normalized_checked_at,
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": scheduler_id,
        "checked_at": normalized_checked_at,
        "supported_actions": _operator_control_supported_actions(),
        "required_fields": {
            "operator_subject": True,
            "idempotency_key": True,
            "reason": True,
            "approval_required_for_start": True,
            "approval_required_for_restart": True,
            "profile": True,
            "max_cycles": True,
        },
        "profile_policy": {
            "default_profile": "test",
            "allowed_profiles": ["test"],
            "production_profiles_allowed": False,
            "production_continuous_start_enabled": False,
        },
        "restart_policy": {
            "restart_daemon_supported": True,
            "restart_semantics": "stop_then_start",
            "requires_distinct_stop_evidence": True,
            "requires_distinct_start_evidence": True,
        },
        "guardrails": _operator_control_policy_guardrails(),
        "metadata": _operator_control_policy_metadata(),
    }
    return validate_artifact_retention_scheduler_daemon_operator_control_policy(
        policy
    )


def validate_artifact_retention_scheduler_daemon_operator_control_policy(
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    error_code = "ae.artifact_retention_scheduler_daemon_operator_control_policy_invalid"
    if not isinstance(policy, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control policy "
                "must be an object."
            ),
        )
    normalized = dict(policy)
    if set(normalized) != {
        "operator_control_policy_schema_version",
        "operator_control_policy_id",
        "service_id",
        "scheduler_id",
        "checked_at",
        "supported_actions",
        "required_fields",
        "profile_policy",
        "restart_policy",
        "guardrails",
        "metadata",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control policy "
                "keys are invalid."
            ),
        )
    if (
        normalized.get("operator_control_policy_schema_version")
        != AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_POLICY_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_operator_control_policy_schema_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon operator control policy "
                "schema is invalid."
            ),
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control policy "
                "service id is invalid."
            ),
        )
    scheduler_id = _required_text(
        normalized.get("scheduler_id"),
        "scheduler_id",
        error_code=error_code,
    )
    checked_at = _required_text(
        normalized.get("checked_at"),
        "checked_at",
        error_code=error_code,
    )
    if normalized.get("supported_actions") != _operator_control_supported_actions():
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control policy "
                "actions are invalid."
            ),
        )
    if normalized.get("required_fields") != {
        "operator_subject": True,
        "idempotency_key": True,
        "reason": True,
        "approval_required_for_start": True,
        "approval_required_for_restart": True,
        "profile": True,
        "max_cycles": True,
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control policy "
                "required fields are invalid."
            ),
        )
    if normalized.get("profile_policy") != {
        "default_profile": "test",
        "allowed_profiles": ["test"],
        "production_profiles_allowed": False,
        "production_continuous_start_enabled": False,
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control policy "
                "profile policy is invalid."
            ),
        )
    if normalized.get("restart_policy") != {
        "restart_daemon_supported": True,
        "restart_semantics": "stop_then_start",
        "requires_distinct_stop_evidence": True,
        "requires_distinct_start_evidence": True,
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control policy "
                "restart policy is invalid."
            ),
        )
    if normalized.get("guardrails") != _operator_control_policy_guardrails():
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control policy "
                "guardrails are invalid."
            ),
        )
    if normalized.get("metadata") != _operator_control_policy_metadata():
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control policy "
                "metadata is invalid."
            ),
        )
    expected_id = _operator_control_policy_id(
        scheduler_id=scheduler_id,
        checked_at=checked_at,
    )
    if normalized.get("operator_control_policy_id") != expected_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control policy "
                "id is invalid."
            ),
        )
    assert_artifact_retention_payload_safe(normalized)
    return normalized


def build_artifact_retention_scheduler_daemon_operator_control_request(
    *,
    action: str = "status_probe",
    operator_subject: Mapping[str, Any],
    idempotency_key: str,
    reason: str,
    scheduler_config: Mapping[str, Any] | None = None,
    requested_at: str | None = None,
    profile: str = "test",
    enabled: bool = False,
    explicit_opt_in: bool = False,
    max_cycles: int | str = 1,
    run_worker: bool = False,
    approval: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    error_code = "ae.artifact_retention_scheduler_daemon_operator_control_request_invalid"
    normalized_action = _normalize_daemon_operator_control_action(action)
    config = (
        dict(scheduler_config)
        if scheduler_config is not None
        else build_artifact_retention_scheduler_config()
    )
    daemon_config = build_artifact_retention_scheduler_daemon_config(
        scheduler_config=config,
        checked_at=requested_at,
    )
    scheduler_id = _required_text(
        daemon_config.get("scheduler_id"),
        "scheduler_id",
        error_code=error_code,
    )
    normalized_requested_at = _required_text(
        requested_at or daemon_config.get("checked_at"),
        "requested_at",
        error_code=error_code,
    )
    normalized_subject = _safe_operator_subject(operator_subject, error_code=error_code)
    normalized_idempotency_key = _required_text(
        idempotency_key,
        "idempotency_key",
        error_code=error_code,
    )
    normalized_reason = _required_text(reason, "reason", error_code=error_code)
    normalized_profile = _normalize_daemon_operator_control_profile(
        profile,
        error_code=error_code,
    )
    normalized_enabled = _required_bool(enabled, "enabled", error_code=error_code)
    normalized_explicit_opt_in = _required_bool(
        explicit_opt_in,
        "explicit_opt_in",
        error_code=error_code,
    )
    normalized_max_cycles = _bounded_positive_int(
        max_cycles,
        "max_cycles",
        max_value=MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_MAX_CYCLES,
        error_code=error_code,
    )
    normalized_run_worker = _required_bool(
        run_worker,
        "run_worker",
        error_code=error_code,
    )
    normalized_approval = _normalize_operator_control_approval(
        approval,
        action=normalized_action,
        operator_subject=normalized_subject,
        requested_at=normalized_requested_at,
        reason=normalized_reason,
        error_code=error_code,
    )
    request = {
        "operator_control_request_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_REQUEST_SCHEMA_VERSION
        ),
        "operator_control_request_id": _operator_control_request_id(
            scheduler_id=scheduler_id,
            action=normalized_action,
            idempotency_key=normalized_idempotency_key,
            requested_at=normalized_requested_at,
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": scheduler_id,
        "action": normalized_action,
        "operator_subject": normalized_subject,
        "idempotency_key": normalized_idempotency_key,
        "reason": normalized_reason,
        "requested_at": normalized_requested_at,
        "profile": normalized_profile,
        "enabled": normalized_enabled,
        "explicit_opt_in": normalized_explicit_opt_in,
        "max_cycles": normalized_max_cycles,
        "run_worker": normalized_run_worker,
        "approval": normalized_approval,
        "execution_intent": _operator_control_execution_intent(
            action=normalized_action
        ),
        "guardrails": _operator_control_request_guardrails(
            action=normalized_action
        ),
        "metadata": _operator_control_request_metadata(
            action=normalized_action,
            approval=normalized_approval,
        ),
    }
    return validate_artifact_retention_scheduler_daemon_operator_control_request(
        request
    )


def validate_artifact_retention_scheduler_daemon_operator_control_request(
    request: Mapping[str, Any],
) -> dict[str, Any]:
    error_code = "ae.artifact_retention_scheduler_daemon_operator_control_request_invalid"
    if not isinstance(request, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control request "
                "must be an object."
            ),
        )
    normalized = dict(request)
    if set(normalized) != {
        "operator_control_request_schema_version",
        "operator_control_request_id",
        "service_id",
        "scheduler_id",
        "action",
        "operator_subject",
        "idempotency_key",
        "reason",
        "requested_at",
        "profile",
        "enabled",
        "explicit_opt_in",
        "max_cycles",
        "run_worker",
        "approval",
        "execution_intent",
        "guardrails",
        "metadata",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control request "
                "keys are invalid."
            ),
        )
    if (
        normalized.get("operator_control_request_schema_version")
        != AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_REQUEST_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_operator_control_request_schema_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon operator control request "
                "schema is invalid."
            ),
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control request "
                "service id is invalid."
            ),
        )
    scheduler_id = _required_text(
        normalized.get("scheduler_id"),
        "scheduler_id",
        error_code=error_code,
    )
    action = _normalize_daemon_operator_control_action(normalized.get("action"))
    operator_subject = _safe_operator_subject(
        normalized.get("operator_subject"),
        error_code=error_code,
    )
    idempotency_key = _required_text(
        normalized.get("idempotency_key"),
        "idempotency_key",
        error_code=error_code,
    )
    reason = _required_text(normalized.get("reason"), "reason", error_code=error_code)
    requested_at = _required_text(
        normalized.get("requested_at"),
        "requested_at",
        error_code=error_code,
    )
    profile = _normalize_daemon_operator_control_profile(
        normalized.get("profile"),
        error_code=error_code,
    )
    enabled = _required_bool(
        normalized.get("enabled"),
        "enabled",
        error_code=error_code,
    )
    explicit_opt_in = _required_bool(
        normalized.get("explicit_opt_in"),
        "explicit_opt_in",
        error_code=error_code,
    )
    max_cycles = _bounded_positive_int(
        normalized.get("max_cycles"),
        "max_cycles",
        max_value=MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_MAX_CYCLES,
        error_code=error_code,
    )
    run_worker = _required_bool(
        normalized.get("run_worker"),
        "run_worker",
        error_code=error_code,
    )
    approval = _normalize_operator_control_approval(
        normalized.get("approval"),
        action=action,
        operator_subject=operator_subject,
        requested_at=requested_at,
        reason=reason,
        error_code=error_code,
    )
    if action in {"start_daemon", "restart_daemon"} and (
        enabled is not True or explicit_opt_in is not True
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control request "
                "start or restart requires enabled runtime and explicit opt-in."
            ),
        )
    if normalized.get("execution_intent") != _operator_control_execution_intent(
        action=action
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control request "
                "execution intent is invalid."
            ),
        )
    if normalized.get("guardrails") != _operator_control_request_guardrails(
        action=action
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control request "
                "guardrails are invalid."
            ),
        )
    if normalized.get("metadata") != _operator_control_request_metadata(
        action=action,
        approval=approval,
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control request "
                "metadata is invalid."
            ),
        )
    expected_id = _operator_control_request_id(
        scheduler_id=scheduler_id,
        action=action,
        idempotency_key=idempotency_key,
        requested_at=requested_at,
    )
    if normalized.get("operator_control_request_id") != expected_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control request "
                "id is invalid."
            ),
        )
    normalized["action"] = action
    normalized["operator_subject"] = operator_subject
    normalized["idempotency_key"] = idempotency_key
    normalized["reason"] = reason
    normalized["requested_at"] = requested_at
    normalized["profile"] = profile
    normalized["enabled"] = enabled
    normalized["explicit_opt_in"] = explicit_opt_in
    normalized["max_cycles"] = max_cycles
    normalized["run_worker"] = run_worker
    normalized["approval"] = approval
    assert_artifact_retention_payload_safe(normalized)
    return normalized


def summarize_artifact_retention_scheduler_daemon_operator_control_request(
    request: Mapping[str, Any],
) -> dict[str, Any]:
    validated = validate_artifact_retention_scheduler_daemon_operator_control_request(
        request
    )
    return {
        "scheduler_id": validated["scheduler_id"],
        "action": validated["action"],
        "operator_actor_id": validated["operator_subject"]["actor_id"],
        "idempotency_key": validated["idempotency_key"],
        "profile": validated["profile"],
        "enabled": validated["enabled"],
        "explicit_opt_in": validated["explicit_opt_in"],
        "max_cycles": validated["max_cycles"],
        "run_worker": validated["run_worker"],
        "mutates_process": validated["execution_intent"]["mutates_process"],
        "approval_required": validated["metadata"]["approval_required"],
        "approval_granted": validated["metadata"]["approval_granted"],
        "safe_for_ag_projection": validated["metadata"]["safe_for_ag_projection"],
    }


def operator_control_request_summary_line(request: Mapping[str, Any]) -> str:
    summary = summarize_artifact_retention_scheduler_daemon_operator_control_request(
        request
    )
    return (
        "ae_scheduler_daemon_operator_control_request=pass "
        f"scheduler_id={summary['scheduler_id']} "
        f"action={summary['action']} "
        f"profile={summary['profile']} "
        f"mutates={int(summary['mutates_process'])} "
        f"approved={int(summary['approval_granted'])} "
        f"max_cycles={summary['max_cycles']}"
    )


def build_artifact_retention_scheduler_daemon_operator_control_admission(
    *,
    operator_control_request: Mapping[str, Any],
    current_process: Mapping[str, Any] | None = None,
    checked_at: str | None = None,
) -> dict[str, Any]:
    request = validate_artifact_retention_scheduler_daemon_operator_control_request(
        operator_control_request
    )
    process = _operator_control_current_process(
        current_process,
        requested_at=request["requested_at"],
        error_code="ae.artifact_retention_scheduler_daemon_operator_control_admission_invalid",
    )
    normalized_checked_at = _required_text(
        checked_at or process["observed_at"] or request["requested_at"],
        "checked_at",
        error_code="ae.artifact_retention_scheduler_daemon_operator_control_admission_invalid",
    )
    decision = _operator_control_admission_decision(
        action=request["action"],
        process_status=process["process_status"],
    )
    next_actions = _operator_control_admission_next_supervisor_actions(
        action=request["action"],
        admission_status=decision["admission_status"],
    )
    admission = {
        "operator_control_admission_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_ADMISSION_SCHEMA_VERSION
        ),
        "operator_control_admission_id": _operator_control_admission_id(
            scheduler_id=request["scheduler_id"],
            operator_control_request_id=request["operator_control_request_id"],
            current_process=process,
            checked_at=normalized_checked_at,
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": request["scheduler_id"],
        "operator_control_request_id": request["operator_control_request_id"],
        "action": request["action"],
        "admission_status": decision["admission_status"],
        "decision_reason": decision["decision_reason"],
        "checked_at": normalized_checked_at,
        "operator_control_request": deepcopy(request),
        "current_process": process,
        "next_supervisor_actions": next_actions,
        "execution_intent": dict(request["execution_intent"]),
        "guardrails": _operator_control_admission_guardrails(
            action=request["action"],
            admission_status=decision["admission_status"],
        ),
        "metadata": _operator_control_admission_metadata(
            request=request,
            current_process=process,
            admission_status=decision["admission_status"],
            next_supervisor_actions=next_actions,
        ),
    }
    return validate_artifact_retention_scheduler_daemon_operator_control_admission(
        admission
    )


def validate_artifact_retention_scheduler_daemon_operator_control_admission(
    admission: Mapping[str, Any],
) -> dict[str, Any]:
    error_code = "ae.artifact_retention_scheduler_daemon_operator_control_admission_invalid"
    if not isinstance(admission, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control "
                "admission must be an object."
            ),
        )
    normalized = dict(admission)
    if set(normalized) != {
        "operator_control_admission_schema_version",
        "operator_control_admission_id",
        "service_id",
        "scheduler_id",
        "operator_control_request_id",
        "action",
        "admission_status",
        "decision_reason",
        "checked_at",
        "operator_control_request",
        "current_process",
        "next_supervisor_actions",
        "execution_intent",
        "guardrails",
        "metadata",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control "
                "admission keys are invalid."
            ),
        )
    if (
        normalized.get("operator_control_admission_schema_version")
        != AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_ADMISSION_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_operator_control_admission_schema_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon operator control "
                "admission schema is invalid."
            ),
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control "
                "admission service id is invalid."
            ),
        )
    request = validate_artifact_retention_scheduler_daemon_operator_control_request(
        normalized.get("operator_control_request")
    )
    scheduler_id = _required_text(
        normalized.get("scheduler_id"),
        "scheduler_id",
        error_code=error_code,
    )
    if scheduler_id != request["scheduler_id"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control "
                "admission scheduler scope is invalid."
            ),
        )
    request_id = _required_text(
        normalized.get("operator_control_request_id"),
        "operator_control_request_id",
        error_code=error_code,
    )
    if request_id != request["operator_control_request_id"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control "
                "admission request scope is invalid."
            ),
        )
    action = _normalize_daemon_operator_control_action(normalized.get("action"))
    if action != request["action"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control "
                "admission action scope is invalid."
            ),
        )
    checked_at = _required_text(
        normalized.get("checked_at"),
        "checked_at",
        error_code=error_code,
    )
    process = _operator_control_current_process(
        normalized.get("current_process"),
        requested_at=request["requested_at"],
        error_code=error_code,
    )
    admission_status = _normalize_operator_control_admission_status(
        normalized.get("admission_status"),
        error_code=error_code,
    )
    expected_decision = _operator_control_admission_decision(
        action=action,
        process_status=process["process_status"],
    )
    if admission_status != expected_decision["admission_status"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control "
                "admission status is invalid."
            ),
        )
    if normalized.get("decision_reason") != expected_decision["decision_reason"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control "
                "admission decision reason is invalid."
            ),
        )
    expected_actions = _operator_control_admission_next_supervisor_actions(
        action=action,
        admission_status=admission_status,
    )
    next_actions = _validate_operator_control_admission_next_supervisor_actions(
        normalized.get("next_supervisor_actions"),
        error_code=error_code,
    )
    if next_actions != expected_actions:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control "
                "admission supervisor actions are invalid."
            ),
        )
    if normalized.get("execution_intent") != request["execution_intent"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control "
                "admission execution intent is invalid."
            ),
        )
    expected_guardrails = _operator_control_admission_guardrails(
        action=action,
        admission_status=admission_status,
    )
    if normalized.get("guardrails") != expected_guardrails:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control "
                "admission guardrails are invalid."
            ),
        )
    expected_metadata = _operator_control_admission_metadata(
        request=request,
        current_process=process,
        admission_status=admission_status,
        next_supervisor_actions=next_actions,
    )
    if normalized.get("metadata") != expected_metadata:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control "
                "admission metadata is invalid."
            ),
        )
    expected_id = _operator_control_admission_id(
        scheduler_id=scheduler_id,
        operator_control_request_id=request_id,
        current_process=process,
        checked_at=checked_at,
    )
    if normalized.get("operator_control_admission_id") != expected_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control "
                "admission id is invalid."
            ),
        )
    normalized["action"] = action
    normalized["admission_status"] = admission_status
    normalized["operator_control_request"] = request
    normalized["current_process"] = process
    normalized["next_supervisor_actions"] = next_actions
    assert_artifact_retention_payload_safe(normalized)
    return normalized


def summarize_artifact_retention_scheduler_daemon_operator_control_admission(
    admission: Mapping[str, Any],
) -> dict[str, Any]:
    validated = (
        validate_artifact_retention_scheduler_daemon_operator_control_admission(
            admission
        )
    )
    return {
        "scheduler_id": validated["scheduler_id"],
        "operator_control_admission_id": validated[
            "operator_control_admission_id"
        ],
        "operator_control_request_id": validated["operator_control_request_id"],
        "action": validated["action"],
        "admission_status": validated["admission_status"],
        "decision_reason": validated["decision_reason"],
        "checked_at": validated["checked_at"],
        "process_status": validated["current_process"]["process_status"],
        "process_running": validated["current_process"]["process_running"],
        "next_supervisor_actions": [
            item["action"] for item in validated["next_supervisor_actions"]
        ],
        "ready_for_dispatch": validated["metadata"]["ready_for_dispatch"],
        "safe_for_ag_projection": validated["metadata"]["safe_for_ag_projection"],
    }


def operator_control_admission_summary_line(admission: Mapping[str, Any]) -> str:
    summary = summarize_artifact_retention_scheduler_daemon_operator_control_admission(
        admission
    )
    actions = ",".join(summary["next_supervisor_actions"]) or "none"
    return (
        "ae_scheduler_daemon_operator_control_admission=pass "
        f"scheduler_id={summary['scheduler_id']} "
        f"action={summary['action']} "
        f"status={summary['admission_status']} "
        f"reason={summary['decision_reason']} "
        f"process={summary['process_status']} "
        f"next={actions}"
    )


def build_artifact_retention_scheduler_daemon_operator_control_command_preview(
    *,
    operator_control_admission: Mapping[str, Any],
    checked_at: str | None = None,
) -> dict[str, Any]:
    admission = (
        validate_artifact_retention_scheduler_daemon_operator_control_admission(
            operator_control_admission
        )
    )
    request = admission["operator_control_request"]
    normalized_checked_at = _required_text(
        checked_at or admission["checked_at"],
        "checked_at",
        error_code=(
            "ae.artifact_retention_scheduler_daemon_operator_control_command_preview_invalid"
        ),
    )
    command_previews = _operator_control_supervisor_command_previews(
        admission=admission,
        checked_at=normalized_checked_at,
    )
    preview = {
        "operator_control_command_preview_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_COMMAND_PREVIEW_SCHEMA_VERSION
        ),
        "operator_control_command_preview_id": _operator_control_command_preview_id(
            scheduler_id=admission["scheduler_id"],
            operator_control_admission_id=admission[
                "operator_control_admission_id"
            ],
            command_previews=command_previews,
            checked_at=normalized_checked_at,
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": admission["scheduler_id"],
        "operator_control_admission_id": admission[
            "operator_control_admission_id"
        ],
        "operator_control_request_id": request["operator_control_request_id"],
        "action": admission["action"],
        "preview_status": admission["admission_status"],
        "checked_at": normalized_checked_at,
        "operator_control_admission": deepcopy(admission),
        "supervisor_command_previews": command_previews,
        "guardrails": _operator_control_command_preview_guardrails(
            admission=admission,
            command_previews=command_previews,
        ),
        "metadata": _operator_control_command_preview_metadata(
            admission=admission,
            command_previews=command_previews,
        ),
    }
    return validate_artifact_retention_scheduler_daemon_operator_control_command_preview(
        preview
    )


def validate_artifact_retention_scheduler_daemon_operator_control_command_preview(
    preview: Mapping[str, Any],
) -> dict[str, Any]:
    error_code = (
        "ae.artifact_retention_scheduler_daemon_operator_control_command_preview_invalid"
    )
    if not isinstance(preview, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control command "
                "preview must be an object."
            ),
        )
    normalized = dict(preview)
    if set(normalized) != {
        "operator_control_command_preview_schema_version",
        "operator_control_command_preview_id",
        "service_id",
        "scheduler_id",
        "operator_control_admission_id",
        "operator_control_request_id",
        "action",
        "preview_status",
        "checked_at",
        "operator_control_admission",
        "supervisor_command_previews",
        "guardrails",
        "metadata",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control command "
                "preview keys are invalid."
            ),
        )
    if (
        normalized.get("operator_control_command_preview_schema_version")
        != AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_COMMAND_PREVIEW_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_operator_control_command_preview_schema_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon operator control command "
                "preview schema is invalid."
            ),
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control command "
                "preview service id is invalid."
            ),
        )
    admission = (
        validate_artifact_retention_scheduler_daemon_operator_control_admission(
            normalized.get("operator_control_admission")
        )
    )
    scheduler_id = _required_text(
        normalized.get("scheduler_id"),
        "scheduler_id",
        error_code=error_code,
    )
    if scheduler_id != admission["scheduler_id"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control command "
                "preview scheduler scope is invalid."
            ),
        )
    admission_id = _required_text(
        normalized.get("operator_control_admission_id"),
        "operator_control_admission_id",
        error_code=error_code,
    )
    if admission_id != admission["operator_control_admission_id"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control command "
                "preview admission scope is invalid."
            ),
        )
    request_id = _required_text(
        normalized.get("operator_control_request_id"),
        "operator_control_request_id",
        error_code=error_code,
    )
    if request_id != admission["operator_control_request_id"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control command "
                "preview request scope is invalid."
            ),
        )
    action = _normalize_daemon_operator_control_action(normalized.get("action"))
    if action != admission["action"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control command "
                "preview action scope is invalid."
            ),
        )
    preview_status = _normalize_operator_control_admission_status(
        normalized.get("preview_status"),
        error_code=error_code,
    )
    if preview_status != admission["admission_status"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control command "
                "preview status is invalid."
            ),
        )
    checked_at = _required_text(
        normalized.get("checked_at"),
        "checked_at",
        error_code=error_code,
    )
    command_previews = _validate_operator_control_supervisor_command_previews(
        normalized.get("supervisor_command_previews"),
        admission=admission,
        error_code=error_code,
    )
    expected_previews = _operator_control_supervisor_command_previews(
        admission=admission,
        checked_at=checked_at,
    )
    if command_previews != expected_previews:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control command "
                "preview supervisor commands are invalid."
            ),
        )
    expected_guardrails = _operator_control_command_preview_guardrails(
        admission=admission,
        command_previews=command_previews,
    )
    if normalized.get("guardrails") != expected_guardrails:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control command "
                "preview guardrails are invalid."
            ),
        )
    expected_metadata = _operator_control_command_preview_metadata(
        admission=admission,
        command_previews=command_previews,
    )
    if normalized.get("metadata") != expected_metadata:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control command "
                "preview metadata is invalid."
            ),
        )
    expected_id = _operator_control_command_preview_id(
        scheduler_id=scheduler_id,
        operator_control_admission_id=admission_id,
        command_previews=command_previews,
        checked_at=checked_at,
    )
    if normalized.get("operator_control_command_preview_id") != expected_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control command "
                "preview id is invalid."
            ),
        )
    normalized["action"] = action
    normalized["preview_status"] = preview_status
    normalized["operator_control_admission"] = admission
    normalized["supervisor_command_previews"] = command_previews
    assert_artifact_retention_payload_safe(normalized)
    return normalized


def summarize_artifact_retention_scheduler_daemon_operator_control_command_preview(
    preview: Mapping[str, Any],
) -> dict[str, Any]:
    validated = (
        validate_artifact_retention_scheduler_daemon_operator_control_command_preview(
            preview
        )
    )
    return {
        "scheduler_id": validated["scheduler_id"],
        "operator_control_command_preview_id": validated[
            "operator_control_command_preview_id"
        ],
        "operator_control_admission_id": validated[
            "operator_control_admission_id"
        ],
        "operator_control_request_id": validated["operator_control_request_id"],
        "action": validated["action"],
        "preview_status": validated["preview_status"],
        "checked_at": validated["checked_at"],
        "command_count": validated["metadata"]["command_preview_count"],
        "supervisor_actions": validated["metadata"]["supervisor_actions"],
        "ready_for_dispatch": validated["metadata"]["ready_for_dispatch"],
        "safe_for_ag_projection": validated["metadata"]["safe_for_ag_projection"],
    }


def operator_control_command_preview_summary_line(
    preview: Mapping[str, Any],
) -> str:
    summary = (
        summarize_artifact_retention_scheduler_daemon_operator_control_command_preview(
            preview
        )
    )
    actions = ",".join(summary["supervisor_actions"]) or "none"
    return (
        "ae_scheduler_daemon_operator_control_command_preview=pass "
        f"scheduler_id={summary['scheduler_id']} "
        f"action={summary['action']} "
        f"status={summary['preview_status']} "
        f"commands={summary['command_count']} "
        f"next={actions}"
    )


def build_artifact_retention_scheduler_daemon_operator_control_facade(
    *,
    operator_control_policy: Mapping[str, Any],
    operator_control_command_preview: Mapping[str, Any],
    checked_at: str | None = None,
) -> dict[str, Any]:
    policy = validate_artifact_retention_scheduler_daemon_operator_control_policy(
        operator_control_policy
    )
    preview = (
        validate_artifact_retention_scheduler_daemon_operator_control_command_preview(
            operator_control_command_preview
        )
    )
    admission = preview["operator_control_admission"]
    request = admission["operator_control_request"]
    normalized_checked_at = _required_text(
        checked_at or preview["checked_at"],
        "checked_at",
        error_code=(
            "ae.artifact_retention_scheduler_daemon_operator_control_facade_invalid"
        ),
    )
    if policy["scheduler_id"] != preview["scheduler_id"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_operator_control_facade_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon operator control facade "
                "scheduler scope is invalid."
            ),
        )
    facade = {
        "operator_control_facade_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_FACADE_SCHEMA_VERSION
        ),
        "operator_control_facade_id": _operator_control_facade_id(
            scheduler_id=preview["scheduler_id"],
            operator_control_policy_id=policy["operator_control_policy_id"],
            operator_control_request_id=request["operator_control_request_id"],
            operator_control_admission_id=admission[
                "operator_control_admission_id"
            ],
            operator_control_command_preview_id=preview[
                "operator_control_command_preview_id"
            ],
            checked_at=normalized_checked_at,
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": preview["scheduler_id"],
        "operator_control_policy_id": policy["operator_control_policy_id"],
        "operator_control_request_id": request["operator_control_request_id"],
        "operator_control_admission_id": admission[
            "operator_control_admission_id"
        ],
        "operator_control_command_preview_id": preview[
            "operator_control_command_preview_id"
        ],
        "action": preview["action"],
        "facade_status": preview["preview_status"],
        "checked_at": normalized_checked_at,
        "operator_control_policy": deepcopy(policy),
        "operator_control_request": deepcopy(request),
        "operator_control_admission": deepcopy(admission),
        "operator_control_command_preview": deepcopy(preview),
        "guardrails": _operator_control_facade_guardrails(preview=preview),
        "metadata": _operator_control_facade_metadata(
            policy=policy,
            request=request,
            admission=admission,
            preview=preview,
        ),
    }
    return validate_artifact_retention_scheduler_daemon_operator_control_facade(
        facade
    )


def validate_artifact_retention_scheduler_daemon_operator_control_facade(
    facade: Mapping[str, Any],
) -> dict[str, Any]:
    error_code = (
        "ae.artifact_retention_scheduler_daemon_operator_control_facade_invalid"
    )
    if not isinstance(facade, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control facade "
                "must be an object."
            ),
        )
    normalized = dict(facade)
    if set(normalized) != {
        "operator_control_facade_schema_version",
        "operator_control_facade_id",
        "service_id",
        "scheduler_id",
        "operator_control_policy_id",
        "operator_control_request_id",
        "operator_control_admission_id",
        "operator_control_command_preview_id",
        "action",
        "facade_status",
        "checked_at",
        "operator_control_policy",
        "operator_control_request",
        "operator_control_admission",
        "operator_control_command_preview",
        "guardrails",
        "metadata",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control facade "
                "keys are invalid."
            ),
        )
    if (
        normalized.get("operator_control_facade_schema_version")
        != AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_FACADE_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_operator_control_facade_schema_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon operator control facade "
                "schema is invalid."
            ),
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control facade "
                "service id is invalid."
            ),
        )
    policy = validate_artifact_retention_scheduler_daemon_operator_control_policy(
        normalized.get("operator_control_policy")
    )
    request = validate_artifact_retention_scheduler_daemon_operator_control_request(
        normalized.get("operator_control_request")
    )
    admission = (
        validate_artifact_retention_scheduler_daemon_operator_control_admission(
            normalized.get("operator_control_admission")
        )
    )
    preview = (
        validate_artifact_retention_scheduler_daemon_operator_control_command_preview(
            normalized.get("operator_control_command_preview")
        )
    )
    scheduler_id = _required_text(
        normalized.get("scheduler_id"),
        "scheduler_id",
        error_code=error_code,
    )
    if scheduler_id != policy["scheduler_id"] or scheduler_id != preview[
        "scheduler_id"
    ]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control facade "
                "scheduler scope is invalid."
            ),
        )
    if (
        normalized.get("operator_control_policy_id")
        != policy["operator_control_policy_id"]
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control facade "
                "policy scope is invalid."
            ),
        )
    if (
        normalized.get("operator_control_request_id")
        != request["operator_control_request_id"]
        or admission["operator_control_request_id"]
        != request["operator_control_request_id"]
        or preview["operator_control_request_id"] != request["operator_control_request_id"]
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control facade "
                "request scope is invalid."
            ),
        )
    if (
        normalized.get("operator_control_admission_id")
        != admission["operator_control_admission_id"]
        or preview["operator_control_admission_id"]
        != admission["operator_control_admission_id"]
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control facade "
                "admission scope is invalid."
            ),
        )
    if (
        normalized.get("operator_control_command_preview_id")
        != preview["operator_control_command_preview_id"]
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control facade "
                "preview scope is invalid."
            ),
        )
    action = _normalize_daemon_operator_control_action(normalized.get("action"))
    if action != request["action"] or action != admission["action"] or action != preview[
        "action"
    ]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control facade "
                "action scope is invalid."
            ),
        )
    facade_status = _normalize_operator_control_admission_status(
        normalized.get("facade_status"),
        error_code=error_code,
    )
    if facade_status != admission["admission_status"] or facade_status != preview[
        "preview_status"
    ]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control facade "
                "status is invalid."
            ),
        )
    checked_at = _required_text(
        normalized.get("checked_at"),
        "checked_at",
        error_code=error_code,
    )
    if normalized.get("guardrails") != _operator_control_facade_guardrails(
        preview=preview
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control facade "
                "guardrails are invalid."
            ),
        )
    expected_metadata = _operator_control_facade_metadata(
        policy=policy,
        request=request,
        admission=admission,
        preview=preview,
    )
    if normalized.get("metadata") != expected_metadata:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control facade "
                "metadata is invalid."
            ),
        )
    expected_id = _operator_control_facade_id(
        scheduler_id=scheduler_id,
        operator_control_policy_id=policy["operator_control_policy_id"],
        operator_control_request_id=request["operator_control_request_id"],
        operator_control_admission_id=admission["operator_control_admission_id"],
        operator_control_command_preview_id=preview[
            "operator_control_command_preview_id"
        ],
        checked_at=checked_at,
    )
    if normalized.get("operator_control_facade_id") != expected_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control facade "
                "id is invalid."
            ),
        )
    normalized["action"] = action
    normalized["facade_status"] = facade_status
    normalized["operator_control_policy"] = policy
    normalized["operator_control_request"] = request
    normalized["operator_control_admission"] = admission
    normalized["operator_control_command_preview"] = preview
    assert_artifact_retention_payload_safe(normalized)
    return normalized


def summarize_artifact_retention_scheduler_daemon_operator_control_facade(
    facade: Mapping[str, Any],
) -> dict[str, Any]:
    validated = validate_artifact_retention_scheduler_daemon_operator_control_facade(
        facade
    )
    return {
        "scheduler_id": validated["scheduler_id"],
        "operator_control_facade_id": validated["operator_control_facade_id"],
        "operator_control_request_id": validated["operator_control_request_id"],
        "operator_control_admission_id": validated[
            "operator_control_admission_id"
        ],
        "operator_control_command_preview_id": validated[
            "operator_control_command_preview_id"
        ],
        "action": validated["action"],
        "facade_status": validated["facade_status"],
        "checked_at": validated["checked_at"],
        "decision_reason": validated["operator_control_admission"][
            "decision_reason"
        ],
        "command_count": validated["metadata"]["command_preview_count"],
        "supervisor_actions": validated["metadata"]["supervisor_actions"],
        "ready_for_dispatch": validated["metadata"]["ready_for_dispatch"],
        "safe_for_ag_projection": validated["metadata"]["safe_for_ag_projection"],
    }


def operator_control_facade_summary_line(facade: Mapping[str, Any]) -> str:
    summary = summarize_artifact_retention_scheduler_daemon_operator_control_facade(
        facade
    )
    actions = ",".join(summary["supervisor_actions"]) or "none"
    return (
        "ae_scheduler_daemon_operator_control_facade=pass "
        f"scheduler_id={summary['scheduler_id']} "
        f"action={summary['action']} "
        f"status={summary['facade_status']} "
        f"reason={summary['decision_reason']} "
        f"commands={summary['command_count']} "
        f"next={actions}"
    )


def build_artifact_retention_scheduler_daemon_operator_control_execution_request(
    *,
    operator_control_facade: Mapping[str, Any],
    execution_mode: str = "contract_only",
    requested_at: str | None = None,
) -> dict[str, Any]:
    facade = validate_artifact_retention_scheduler_daemon_operator_control_facade(
        operator_control_facade
    )
    mode = _normalize_operator_control_execution_mode(
        execution_mode,
        error_code=(
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_request_invalid"
        ),
    )
    normalized_requested_at = _required_text(
        requested_at or facade["checked_at"],
        "requested_at",
        error_code=(
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_request_invalid"
        ),
    )
    request = facade["operator_control_request"]
    admission = facade["operator_control_admission"]
    preview = facade["operator_control_command_preview"]
    command_previews = preview["supervisor_command_previews"]
    execution_request = {
        "operator_control_execution_request_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_REQUEST_SCHEMA_VERSION
        ),
        "operator_control_execution_request_id": (
            _operator_control_execution_request_id(
                scheduler_id=facade["scheduler_id"],
                operator_control_facade_id=facade["operator_control_facade_id"],
                execution_mode=mode,
                requested_at=normalized_requested_at,
            )
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": facade["scheduler_id"],
        "operator_control_facade_id": facade["operator_control_facade_id"],
        "operator_control_request_id": facade["operator_control_request_id"],
        "operator_control_admission_id": facade["operator_control_admission_id"],
        "operator_control_command_preview_id": facade[
            "operator_control_command_preview_id"
        ],
        "action": facade["action"],
        "facade_status": facade["facade_status"],
        "execution_mode": mode,
        "requested_at": normalized_requested_at,
        "operator_subject": deepcopy(request["operator_subject"]),
        "idempotency_key": request["idempotency_key"],
        "reason_hash": sha256_json(request["reason"]),
        "operator_control_facade": deepcopy(facade),
        "supervisor_command_count": len(command_previews),
        "supervisor_actions": [item["action"] for item in command_previews],
        "guardrails": _operator_control_execution_request_guardrails(
            facade=facade,
            execution_mode=mode,
        ),
        "metadata": _operator_control_execution_request_metadata(
            facade=facade,
            execution_mode=mode,
            requested_at=normalized_requested_at,
        ),
    }
    return validate_artifact_retention_scheduler_daemon_operator_control_execution_request(
        execution_request
    )


def validate_artifact_retention_scheduler_daemon_operator_control_execution_request(
    execution_request: Mapping[str, Any],
) -> dict[str, Any]:
    error_code = (
        "ae.artifact_retention_scheduler_daemon_operator_control_execution_request_invalid"
    )
    if not isinstance(execution_request, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "request must be an object."
            ),
        )
    normalized = dict(execution_request)
    if set(normalized) != {
        "operator_control_execution_request_schema_version",
        "operator_control_execution_request_id",
        "service_id",
        "scheduler_id",
        "operator_control_facade_id",
        "operator_control_request_id",
        "operator_control_admission_id",
        "operator_control_command_preview_id",
        "action",
        "facade_status",
        "execution_mode",
        "requested_at",
        "operator_subject",
        "idempotency_key",
        "reason_hash",
        "operator_control_facade",
        "supervisor_command_count",
        "supervisor_actions",
        "guardrails",
        "metadata",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "request keys are invalid."
            ),
        )
    if (
        normalized.get("operator_control_execution_request_schema_version")
        != AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_REQUEST_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_operator_control_execution_request_schema_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "request schema is invalid."
            ),
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "request service id is invalid."
            ),
        )
    facade = validate_artifact_retention_scheduler_daemon_operator_control_facade(
        normalized.get("operator_control_facade")
    )
    scheduler_id = _required_text(
        normalized.get("scheduler_id"),
        "scheduler_id",
        error_code=error_code,
    )
    if scheduler_id != facade["scheduler_id"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "request scheduler scope is invalid."
            ),
        )
    _ensure_operator_control_execution_source_scope(
        payload=normalized,
        facade=facade,
        error_code=error_code,
        label="request",
    )
    action = _normalize_daemon_operator_control_action(normalized.get("action"))
    if action != facade["action"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "request action scope is invalid."
            ),
        )
    facade_status = _normalize_operator_control_admission_status(
        normalized.get("facade_status"),
        error_code=error_code,
    )
    if facade_status != facade["facade_status"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "request facade status is invalid."
            ),
        )
    execution_mode = _normalize_operator_control_execution_mode(
        normalized.get("execution_mode"),
        error_code=error_code,
    )
    requested_at = _required_text(
        normalized.get("requested_at"),
        "requested_at",
        error_code=error_code,
    )
    operator_subject = _safe_operator_subject(
        normalized.get("operator_subject"),
        error_code=error_code,
    )
    request = facade["operator_control_request"]
    if operator_subject != request["operator_subject"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "request operator subject is invalid."
            ),
        )
    idempotency_key = _required_text(
        normalized.get("idempotency_key"),
        "idempotency_key",
        error_code=error_code,
    )
    if idempotency_key != request["idempotency_key"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "request idempotency scope is invalid."
            ),
        )
    if normalized.get("reason_hash") != sha256_json(request["reason"]):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "request reason hash is invalid."
            ),
        )
    command_previews = facade["operator_control_command_preview"][
        "supervisor_command_previews"
    ]
    supervisor_actions = [item["action"] for item in command_previews]
    command_count = _bounded_non_negative_operator_control_count(
        normalized.get("supervisor_command_count"),
        "supervisor_command_count",
        error_code=error_code,
    )
    if command_count != len(command_previews):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "request command count is invalid."
            ),
        )
    if normalized.get("supervisor_actions") != supervisor_actions:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "request supervisor actions are invalid."
            ),
        )
    if normalized.get("guardrails") != _operator_control_execution_request_guardrails(
        facade=facade,
        execution_mode=execution_mode,
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "request guardrails are invalid."
            ),
        )
    expected_metadata = _operator_control_execution_request_metadata(
        facade=facade,
        execution_mode=execution_mode,
        requested_at=requested_at,
    )
    if normalized.get("metadata") != expected_metadata:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "request metadata is invalid."
            ),
        )
    expected_id = _operator_control_execution_request_id(
        scheduler_id=scheduler_id,
        operator_control_facade_id=facade["operator_control_facade_id"],
        execution_mode=execution_mode,
        requested_at=requested_at,
    )
    if normalized.get("operator_control_execution_request_id") != expected_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "request id is invalid."
            ),
        )
    normalized["action"] = action
    normalized["facade_status"] = facade_status
    normalized["execution_mode"] = execution_mode
    normalized["operator_subject"] = operator_subject
    normalized["idempotency_key"] = idempotency_key
    normalized["operator_control_facade"] = facade
    assert_artifact_retention_payload_safe(normalized)
    return normalized


def summarize_artifact_retention_scheduler_daemon_operator_control_execution_request(
    execution_request: Mapping[str, Any],
) -> dict[str, Any]:
    validated = (
        validate_artifact_retention_scheduler_daemon_operator_control_execution_request(
            execution_request
        )
    )
    return {
        "scheduler_id": validated["scheduler_id"],
        "operator_control_execution_request_id": validated[
            "operator_control_execution_request_id"
        ],
        "operator_control_facade_id": validated["operator_control_facade_id"],
        "action": validated["action"],
        "facade_status": validated["facade_status"],
        "execution_mode": validated["execution_mode"],
        "requested_at": validated["requested_at"],
        "operator_actor_id": validated["operator_subject"]["actor_id"],
        "idempotency_key": validated["idempotency_key"],
        "supervisor_command_count": validated["supervisor_command_count"],
        "supervisor_actions": list(validated["supervisor_actions"]),
        "ready_for_execution": validated["metadata"]["ready_for_execution"],
        "safe_for_ag_projection": validated["metadata"]["safe_for_ag_projection"],
    }


def operator_control_execution_request_summary_line(
    execution_request: Mapping[str, Any],
) -> str:
    summary = (
        summarize_artifact_retention_scheduler_daemon_operator_control_execution_request(
            execution_request
        )
    )
    actions = ",".join(summary["supervisor_actions"]) or "none"
    return (
        "ae_scheduler_daemon_operator_control_execution_request=pass "
        f"scheduler_id={summary['scheduler_id']} "
        f"action={summary['action']} "
        f"facade_status={summary['facade_status']} "
        f"mode={summary['execution_mode']} "
        f"ready={int(summary['ready_for_execution'])} "
        f"commands={summary['supervisor_command_count']} "
        f"next={actions}"
    )


def build_artifact_retention_scheduler_daemon_operator_control_execution_result(
    *,
    operator_control_execution_request: Mapping[str, Any],
    observed_at: str | None = None,
) -> dict[str, Any]:
    execution_request = (
        validate_artifact_retention_scheduler_daemon_operator_control_execution_request(
            operator_control_execution_request
        )
    )
    normalized_observed_at = _required_text(
        observed_at or execution_request["requested_at"],
        "observed_at",
        error_code=(
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_result_invalid"
        ),
    )
    decision = _operator_control_execution_result_decision(
        execution_request=execution_request
    )
    result = {
        "operator_control_execution_result_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_RESULT_SCHEMA_VERSION
        ),
        "operator_control_execution_result_id": (
            _operator_control_execution_result_id(
                scheduler_id=execution_request["scheduler_id"],
                operator_control_execution_request_id=execution_request[
                    "operator_control_execution_request_id"
                ],
                execution_status=decision["execution_status"],
                observed_at=normalized_observed_at,
            )
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": execution_request["scheduler_id"],
        "operator_control_execution_request_id": execution_request[
            "operator_control_execution_request_id"
        ],
        "operator_control_facade_id": execution_request["operator_control_facade_id"],
        "operator_control_request_id": execution_request["operator_control_request_id"],
        "operator_control_admission_id": execution_request[
            "operator_control_admission_id"
        ],
        "operator_control_command_preview_id": execution_request[
            "operator_control_command_preview_id"
        ],
        "action": execution_request["action"],
        "execution_mode": execution_request["execution_mode"],
        "execution_status": decision["execution_status"],
        "decision_reason": decision["decision_reason"],
        "observed_at": normalized_observed_at,
        "operator_control_execution_request": deepcopy(execution_request),
        "supervisor_dispatch_results": [],
        "guardrails": _operator_control_execution_result_guardrails(
            execution_request=execution_request,
            execution_status=decision["execution_status"],
        ),
        "metadata": _operator_control_execution_result_metadata(
            execution_request=execution_request,
            execution_status=decision["execution_status"],
            observed_at=normalized_observed_at,
        ),
    }
    return validate_artifact_retention_scheduler_daemon_operator_control_execution_result(
        result
    )


def validate_artifact_retention_scheduler_daemon_operator_control_execution_result(
    execution_result: Mapping[str, Any],
) -> dict[str, Any]:
    error_code = (
        "ae.artifact_retention_scheduler_daemon_operator_control_execution_result_invalid"
    )
    if not isinstance(execution_result, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "result must be an object."
            ),
        )
    normalized = dict(execution_result)
    if set(normalized) != {
        "operator_control_execution_result_schema_version",
        "operator_control_execution_result_id",
        "service_id",
        "scheduler_id",
        "operator_control_execution_request_id",
        "operator_control_facade_id",
        "operator_control_request_id",
        "operator_control_admission_id",
        "operator_control_command_preview_id",
        "action",
        "execution_mode",
        "execution_status",
        "decision_reason",
        "observed_at",
        "operator_control_execution_request",
        "supervisor_dispatch_results",
        "guardrails",
        "metadata",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "result keys are invalid."
            ),
        )
    if (
        normalized.get("operator_control_execution_result_schema_version")
        != AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_RESULT_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_operator_control_execution_result_schema_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "result schema is invalid."
            ),
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "result service id is invalid."
            ),
        )
    execution_request = (
        validate_artifact_retention_scheduler_daemon_operator_control_execution_request(
            normalized.get("operator_control_execution_request")
        )
    )
    scheduler_id = _required_text(
        normalized.get("scheduler_id"),
        "scheduler_id",
        error_code=error_code,
    )
    if scheduler_id != execution_request["scheduler_id"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "result scheduler scope is invalid."
            ),
        )
    _ensure_operator_control_execution_source_scope(
        payload=normalized,
        facade=execution_request["operator_control_facade"],
        error_code=error_code,
        label="result",
    )
    if (
        normalized.get("operator_control_execution_request_id")
        != execution_request["operator_control_execution_request_id"]
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "result request scope is invalid."
            ),
        )
    action = _normalize_daemon_operator_control_action(normalized.get("action"))
    if action != execution_request["action"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "result action scope is invalid."
            ),
        )
    execution_mode = _normalize_operator_control_execution_mode(
        normalized.get("execution_mode"),
        error_code=error_code,
    )
    if execution_mode != execution_request["execution_mode"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "result mode scope is invalid."
            ),
        )
    execution_status = _normalize_operator_control_execution_status(
        normalized.get("execution_status"),
        error_code=error_code,
    )
    expected_decision = _operator_control_execution_result_decision(
        execution_request=execution_request
    )
    if execution_status != expected_decision["execution_status"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "result status is invalid."
            ),
        )
    if normalized.get("decision_reason") != expected_decision["decision_reason"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "result decision reason is invalid."
            ),
        )
    observed_at = _required_text(
        normalized.get("observed_at"),
        "observed_at",
        error_code=error_code,
    )
    dispatch_results = _operator_control_execution_result_dispatch_results(
        normalized.get("supervisor_dispatch_results"),
        error_code=error_code,
    )
    if normalized.get("guardrails") != _operator_control_execution_result_guardrails(
        execution_request=execution_request,
        execution_status=execution_status,
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "result guardrails are invalid."
            ),
        )
    expected_metadata = _operator_control_execution_result_metadata(
        execution_request=execution_request,
        execution_status=execution_status,
        observed_at=observed_at,
    )
    if normalized.get("metadata") != expected_metadata:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "result metadata is invalid."
            ),
        )
    expected_id = _operator_control_execution_result_id(
        scheduler_id=scheduler_id,
        operator_control_execution_request_id=execution_request[
            "operator_control_execution_request_id"
        ],
        execution_status=execution_status,
        observed_at=observed_at,
    )
    if normalized.get("operator_control_execution_result_id") != expected_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "result id is invalid."
            ),
        )
    normalized["action"] = action
    normalized["execution_mode"] = execution_mode
    normalized["execution_status"] = execution_status
    normalized["operator_control_execution_request"] = execution_request
    normalized["supervisor_dispatch_results"] = dispatch_results
    assert_artifact_retention_payload_safe(normalized)
    return normalized


def summarize_artifact_retention_scheduler_daemon_operator_control_execution_result(
    execution_result: Mapping[str, Any],
) -> dict[str, Any]:
    validated = (
        validate_artifact_retention_scheduler_daemon_operator_control_execution_result(
            execution_result
        )
    )
    return {
        "scheduler_id": validated["scheduler_id"],
        "operator_control_execution_result_id": validated[
            "operator_control_execution_result_id"
        ],
        "operator_control_execution_request_id": validated[
            "operator_control_execution_request_id"
        ],
        "action": validated["action"],
        "execution_mode": validated["execution_mode"],
        "execution_status": validated["execution_status"],
        "decision_reason": validated["decision_reason"],
        "observed_at": validated["observed_at"],
        "dispatch_count": validated["metadata"]["dispatch_count"],
        "supervisor_actions": list(validated["metadata"]["supervisor_actions"]),
        "ready_for_execution": validated["metadata"]["ready_for_execution"],
        "safe_for_ag_projection": validated["metadata"]["safe_for_ag_projection"],
    }


def operator_control_execution_result_summary_line(
    execution_result: Mapping[str, Any],
) -> str:
    summary = (
        summarize_artifact_retention_scheduler_daemon_operator_control_execution_result(
            execution_result
        )
    )
    actions = ",".join(summary["supervisor_actions"]) or "none"
    return (
        "ae_scheduler_daemon_operator_control_execution_result=pass "
        f"scheduler_id={summary['scheduler_id']} "
        f"action={summary['action']} "
        f"status={summary['execution_status']} "
        f"reason={summary['decision_reason']} "
        f"dispatches={summary['dispatch_count']} "
        f"next={actions}"
    )


def build_artifact_retention_scheduler_daemon_operator_control_execution_state(
    *,
    operator_control_execution_request: Mapping[str, Any],
    existing_execution_state: Mapping[str, Any] | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    execution_request = (
        validate_artifact_retention_scheduler_daemon_operator_control_execution_request(
            operator_control_execution_request
        )
    )
    existing_state = (
        validate_artifact_retention_scheduler_daemon_operator_control_execution_state(
            existing_execution_state
        )
        if existing_execution_state is not None
        else None
    )
    normalized_observed_at = _required_text(
        observed_at or execution_request["requested_at"],
        "observed_at",
        error_code=(
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_invalid"
        ),
    )
    decision = _operator_control_execution_state_decision(
        execution_request=execution_request,
        existing_state=existing_state,
    )
    request_hash = sha256_json(dict(execution_request))
    prior_state_id = (
        existing_state["operator_control_execution_state_id"]
        if existing_state is not None
        else None
    )
    execution_state = {
        "operator_control_execution_state_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_STATE_SCHEMA_VERSION
        ),
        "operator_control_execution_state_id": _operator_control_execution_state_id(
            scheduler_id=execution_request["scheduler_id"],
            operator_control_execution_request_id=execution_request[
                "operator_control_execution_request_id"
            ],
            execution_status=decision["execution_status"],
            idempotency_status=decision["idempotency_status"],
            observed_at=normalized_observed_at,
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": execution_request["scheduler_id"],
        "operator_control_execution_request_id": execution_request[
            "operator_control_execution_request_id"
        ],
        "operator_control_facade_id": execution_request["operator_control_facade_id"],
        "operator_control_request_id": execution_request["operator_control_request_id"],
        "operator_control_admission_id": execution_request[
            "operator_control_admission_id"
        ],
        "operator_control_command_preview_id": execution_request[
            "operator_control_command_preview_id"
        ],
        "action": execution_request["action"],
        "execution_mode": execution_request["execution_mode"],
        "execution_status": decision["execution_status"],
        "idempotency_key": execution_request["idempotency_key"],
        "idempotency_status": decision["idempotency_status"],
        "decision_reason": decision["decision_reason"],
        "observed_at": normalized_observed_at,
        "prior_execution_state_id": prior_state_id,
        "operator_control_execution_request_hash": request_hash,
        "operator_control_execution_request": deepcopy(execution_request),
        "allowed_next_statuses": _operator_control_execution_allowed_next_statuses(
            decision["execution_status"]
        ),
        "guardrails": _operator_control_execution_state_guardrails(
            execution_request=execution_request,
            execution_status=decision["execution_status"],
            idempotency_status=decision["idempotency_status"],
        ),
        "metadata": _operator_control_execution_state_metadata(
            execution_request=execution_request,
            execution_status=decision["execution_status"],
            idempotency_status=decision["idempotency_status"],
            observed_at=normalized_observed_at,
            existing_state=existing_state,
        ),
    }
    return validate_artifact_retention_scheduler_daemon_operator_control_execution_state(
        execution_state
    )


def validate_artifact_retention_scheduler_daemon_operator_control_execution_state(
    execution_state: Mapping[str, Any],
) -> dict[str, Any]:
    error_code = (
        "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_invalid"
    )
    if not isinstance(execution_state, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "state must be an object."
            ),
        )
    normalized = dict(execution_state)
    if set(normalized) != {
        "operator_control_execution_state_schema_version",
        "operator_control_execution_state_id",
        "service_id",
        "scheduler_id",
        "operator_control_execution_request_id",
        "operator_control_facade_id",
        "operator_control_request_id",
        "operator_control_admission_id",
        "operator_control_command_preview_id",
        "action",
        "execution_mode",
        "execution_status",
        "idempotency_key",
        "idempotency_status",
        "decision_reason",
        "observed_at",
        "prior_execution_state_id",
        "operator_control_execution_request_hash",
        "operator_control_execution_request",
        "allowed_next_statuses",
        "guardrails",
        "metadata",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "state keys are invalid."
            ),
        )
    if (
        normalized.get("operator_control_execution_state_schema_version")
        != AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_STATE_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_schema_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "state schema is invalid."
            ),
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "state service id is invalid."
            ),
        )
    execution_request = (
        validate_artifact_retention_scheduler_daemon_operator_control_execution_request(
            normalized.get("operator_control_execution_request")
        )
    )
    scheduler_id = _required_text(
        normalized.get("scheduler_id"),
        "scheduler_id",
        error_code=error_code,
    )
    if scheduler_id != execution_request["scheduler_id"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "state scheduler scope is invalid."
            ),
        )
    _ensure_operator_control_execution_source_scope(
        payload=normalized,
        facade=execution_request["operator_control_facade"],
        error_code=error_code,
        label="state",
    )
    if (
        normalized.get("operator_control_execution_request_id")
        != execution_request["operator_control_execution_request_id"]
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "state request scope is invalid."
            ),
        )
    action = _normalize_daemon_operator_control_action(normalized.get("action"))
    if action != execution_request["action"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "state action scope is invalid."
            ),
        )
    execution_mode = _normalize_operator_control_execution_mode(
        normalized.get("execution_mode"),
        error_code=error_code,
    )
    if execution_mode != execution_request["execution_mode"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "state mode scope is invalid."
            ),
        )
    execution_status = _normalize_operator_control_execution_state_status(
        normalized.get("execution_status"),
        error_code=error_code,
    )
    idempotency_key = _required_text(
        normalized.get("idempotency_key"),
        "idempotency_key",
        error_code=error_code,
    )
    if idempotency_key != execution_request["idempotency_key"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "state idempotency scope is invalid."
            ),
        )
    idempotency_status = _normalize_operator_control_idempotency_status(
        normalized.get("idempotency_status"),
        error_code=error_code,
    )
    decision = _operator_control_execution_state_decision(
        execution_request=execution_request,
        existing_state=None,
        idempotency_status=idempotency_status,
    )
    if execution_status != decision["execution_status"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "state status is invalid."
            ),
        )
    if normalized.get("decision_reason") != decision["decision_reason"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "state decision reason is invalid."
            ),
        )
    observed_at = _required_text(
        normalized.get("observed_at"),
        "observed_at",
        error_code=error_code,
    )
    prior_state_id = optional_text(normalized.get("prior_execution_state_id"))
    request_hash = sha256_json(dict(execution_request))
    if normalized.get("operator_control_execution_request_hash") != request_hash:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "state request hash is invalid."
            ),
        )
    expected_allowed = _operator_control_execution_allowed_next_statuses(
        execution_status
    )
    if normalized.get("allowed_next_statuses") != expected_allowed:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "state next statuses are invalid."
            ),
        )
    if normalized.get("guardrails") != _operator_control_execution_state_guardrails(
        execution_request=execution_request,
        execution_status=execution_status,
        idempotency_status=idempotency_status,
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "state guardrails are invalid."
            ),
        )
    expected_metadata = _operator_control_execution_state_metadata(
        execution_request=execution_request,
        execution_status=execution_status,
        idempotency_status=idempotency_status,
        observed_at=observed_at,
        existing_state=None,
        prior_state_id=prior_state_id,
    )
    if normalized.get("metadata") != expected_metadata:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "state metadata is invalid."
            ),
        )
    expected_id = _operator_control_execution_state_id(
        scheduler_id=scheduler_id,
        operator_control_execution_request_id=execution_request[
            "operator_control_execution_request_id"
        ],
        execution_status=execution_status,
        idempotency_status=idempotency_status,
        observed_at=observed_at,
    )
    if normalized.get("operator_control_execution_state_id") != expected_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "state id is invalid."
            ),
        )
    normalized["action"] = action
    normalized["execution_mode"] = execution_mode
    normalized["execution_status"] = execution_status
    normalized["idempotency_key"] = idempotency_key
    normalized["idempotency_status"] = idempotency_status
    normalized["prior_execution_state_id"] = prior_state_id
    normalized["operator_control_execution_request"] = execution_request
    assert_artifact_retention_payload_safe(normalized)
    return normalized


def build_artifact_retention_scheduler_daemon_operator_control_execution_state_transition(
    *,
    operator_control_execution_state: Mapping[str, Any],
    target_status: str,
    decision_reason: str,
    transitioned_at: str | None = None,
) -> dict[str, Any]:
    state = validate_artifact_retention_scheduler_daemon_operator_control_execution_state(
        operator_control_execution_state
    )
    to_status = _normalize_operator_control_execution_state_status(
        target_status,
        error_code=(
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_transition_invalid"
        ),
    )
    normalized_transitioned_at = _required_text(
        transitioned_at or state["observed_at"],
        "transitioned_at",
        error_code=(
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_transition_invalid"
        ),
    )
    normalized_reason = _required_text(
        decision_reason,
        "decision_reason",
        error_code=(
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_transition_invalid"
        ),
    )
    _ensure_operator_control_execution_transition_allowed(
        from_status=state["execution_status"],
        to_status=to_status,
    )
    transition = {
        "operator_control_execution_state_transition_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_STATE_TRANSITION_SCHEMA_VERSION
        ),
        "operator_control_execution_state_transition_id": (
            _operator_control_execution_state_transition_id(
                scheduler_id=state["scheduler_id"],
                operator_control_execution_state_id=state[
                    "operator_control_execution_state_id"
                ],
                from_status=state["execution_status"],
                to_status=to_status,
                transitioned_at=normalized_transitioned_at,
            )
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": state["scheduler_id"],
        "operator_control_execution_state_id": state[
            "operator_control_execution_state_id"
        ],
        "operator_control_execution_request_id": state[
            "operator_control_execution_request_id"
        ],
        "from_status": state["execution_status"],
        "to_status": to_status,
        "decision_reason": normalized_reason,
        "transitioned_at": normalized_transitioned_at,
        "operator_control_execution_state": deepcopy(state),
        "guardrails": _operator_control_execution_transition_guardrails(
            state=state,
            to_status=to_status,
        ),
        "metadata": _operator_control_execution_transition_metadata(
            state=state,
            to_status=to_status,
            transitioned_at=normalized_transitioned_at,
        ),
    }
    return validate_artifact_retention_scheduler_daemon_operator_control_execution_state_transition(
        transition
    )


def validate_artifact_retention_scheduler_daemon_operator_control_execution_state_transition(
    transition: Mapping[str, Any],
) -> dict[str, Any]:
    error_code = (
        "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_transition_invalid"
    )
    if not isinstance(transition, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "state transition must be an object."
            ),
        )
    normalized = dict(transition)
    if set(normalized) != {
        "operator_control_execution_state_transition_schema_version",
        "operator_control_execution_state_transition_id",
        "service_id",
        "scheduler_id",
        "operator_control_execution_state_id",
        "operator_control_execution_request_id",
        "from_status",
        "to_status",
        "decision_reason",
        "transitioned_at",
        "operator_control_execution_state",
        "guardrails",
        "metadata",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "state transition keys are invalid."
            ),
        )
    if (
        normalized.get("operator_control_execution_state_transition_schema_version")
        != AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_STATE_TRANSITION_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_transition_schema_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "state transition schema is invalid."
            ),
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "state transition service id is invalid."
            ),
        )
    state = validate_artifact_retention_scheduler_daemon_operator_control_execution_state(
        normalized.get("operator_control_execution_state")
    )
    scheduler_id = _required_text(
        normalized.get("scheduler_id"),
        "scheduler_id",
        error_code=error_code,
    )
    if scheduler_id != state["scheduler_id"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "state transition scheduler scope is invalid."
            ),
        )
    if normalized.get("operator_control_execution_state_id") != state[
        "operator_control_execution_state_id"
    ]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "state transition state scope is invalid."
            ),
        )
    if normalized.get("operator_control_execution_request_id") != state[
        "operator_control_execution_request_id"
    ]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "state transition request scope is invalid."
            ),
        )
    from_status = _normalize_operator_control_execution_state_status(
        normalized.get("from_status"),
        error_code=error_code,
    )
    if from_status != state["execution_status"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "state transition from status is invalid."
            ),
        )
    to_status = _normalize_operator_control_execution_state_status(
        normalized.get("to_status"),
        error_code=error_code,
    )
    _ensure_operator_control_execution_transition_allowed(
        from_status=from_status,
        to_status=to_status,
    )
    transitioned_at = _required_text(
        normalized.get("transitioned_at"),
        "transitioned_at",
        error_code=error_code,
    )
    decision_reason = _required_text(
        normalized.get("decision_reason"),
        "decision_reason",
        error_code=error_code,
    )
    if normalized.get("guardrails") != _operator_control_execution_transition_guardrails(
        state=state,
        to_status=to_status,
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "state transition guardrails are invalid."
            ),
        )
    expected_metadata = _operator_control_execution_transition_metadata(
        state=state,
        to_status=to_status,
        transitioned_at=transitioned_at,
    )
    if normalized.get("metadata") != expected_metadata:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "state transition metadata is invalid."
            ),
        )
    expected_id = _operator_control_execution_state_transition_id(
        scheduler_id=scheduler_id,
        operator_control_execution_state_id=state[
            "operator_control_execution_state_id"
        ],
        from_status=from_status,
        to_status=to_status,
        transitioned_at=transitioned_at,
    )
    if normalized.get("operator_control_execution_state_transition_id") != expected_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "state transition id is invalid."
            ),
        )
    normalized["from_status"] = from_status
    normalized["to_status"] = to_status
    normalized["decision_reason"] = decision_reason
    normalized["operator_control_execution_state"] = state
    assert_artifact_retention_payload_safe(normalized)
    return normalized


def summarize_artifact_retention_scheduler_daemon_operator_control_execution_state(
    execution_state: Mapping[str, Any],
) -> dict[str, Any]:
    validated = (
        validate_artifact_retention_scheduler_daemon_operator_control_execution_state(
            execution_state
        )
    )
    return {
        "scheduler_id": validated["scheduler_id"],
        "operator_control_execution_state_id": validated[
            "operator_control_execution_state_id"
        ],
        "operator_control_execution_request_id": validated[
            "operator_control_execution_request_id"
        ],
        "action": validated["action"],
        "execution_status": validated["execution_status"],
        "idempotency_status": validated["idempotency_status"],
        "decision_reason": validated["decision_reason"],
        "allowed_next_statuses": list(validated["allowed_next_statuses"]),
        "safe_for_ag_projection": validated["metadata"]["safe_for_ag_projection"],
    }


def operator_control_execution_state_summary_line(
    execution_state: Mapping[str, Any],
) -> str:
    summary = (
        summarize_artifact_retention_scheduler_daemon_operator_control_execution_state(
            execution_state
        )
    )
    next_statuses = ",".join(summary["allowed_next_statuses"]) or "terminal"
    return (
        "ae_scheduler_daemon_operator_control_execution_state=pass "
        f"scheduler_id={summary['scheduler_id']} "
        f"action={summary['action']} "
        f"status={summary['execution_status']} "
        f"idempotency={summary['idempotency_status']} "
        f"reason={summary['decision_reason']} "
        f"next={next_statuses}"
    )


def summarize_artifact_retention_scheduler_daemon_operator_control_execution_state_transition(
    transition: Mapping[str, Any],
) -> dict[str, Any]:
    validated = (
        validate_artifact_retention_scheduler_daemon_operator_control_execution_state_transition(
            transition
        )
    )
    return {
        "scheduler_id": validated["scheduler_id"],
        "operator_control_execution_state_transition_id": validated[
            "operator_control_execution_state_transition_id"
        ],
        "operator_control_execution_state_id": validated[
            "operator_control_execution_state_id"
        ],
        "from_status": validated["from_status"],
        "to_status": validated["to_status"],
        "decision_reason": validated["decision_reason"],
        "transitioned_at": validated["transitioned_at"],
        "safe_for_ag_projection": validated["metadata"]["safe_for_ag_projection"],
    }


def operator_control_execution_state_transition_summary_line(
    transition: Mapping[str, Any],
) -> str:
    summary = (
        summarize_artifact_retention_scheduler_daemon_operator_control_execution_state_transition(
            transition
        )
    )
    return (
        "ae_scheduler_daemon_operator_control_execution_state_transition=pass "
        f"scheduler_id={summary['scheduler_id']} "
        f"from={summary['from_status']} "
        f"to={summary['to_status']} "
        f"reason={summary['decision_reason']}"
    )


def build_artifact_retention_scheduler_daemon_operator_control_execution_worker_plan(
    *,
    operator_control_execution_state: Mapping[str, Any],
    planned_at: str | None = None,
) -> dict[str, Any]:
    state = validate_artifact_retention_scheduler_daemon_operator_control_execution_state(
        operator_control_execution_state
    )
    normalized_planned_at = _required_text(
        planned_at or state["observed_at"],
        "planned_at",
        error_code=(
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_worker_plan_invalid"
        ),
    )
    supervisor_commands = _operator_control_execution_worker_supervisor_commands(
        state
    )
    decision = _operator_control_execution_worker_plan_decision(
        state=state,
        supervisor_commands=supervisor_commands,
    )
    plan = {
        "operator_control_execution_worker_plan_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_PLAN_SCHEMA_VERSION
        ),
        "operator_control_execution_worker_plan_id": (
            _operator_control_execution_worker_plan_id(
                scheduler_id=state["scheduler_id"],
                operator_control_execution_state_id=state[
                    "operator_control_execution_state_id"
                ],
                plan_status=decision["plan_status"],
                planned_at=normalized_planned_at,
            )
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": state["scheduler_id"],
        "operator_control_execution_state_id": state[
            "operator_control_execution_state_id"
        ],
        "operator_control_execution_request_id": state[
            "operator_control_execution_request_id"
        ],
        "action": state["action"],
        "execution_mode": state["execution_mode"],
        "plan_status": decision["plan_status"],
        "decision_reason": decision["decision_reason"],
        "planned_at": normalized_planned_at,
        "operator_control_execution_state": deepcopy(state),
        "supervisor_command_count": len(supervisor_commands),
        "supervisor_actions": [command["command"]["action"] for command in supervisor_commands],
        "supervisor_command_ids": [
            command["daemon_supervisor_command_id"] for command in supervisor_commands
        ],
        "guardrails": _operator_control_execution_worker_plan_guardrails(
            state=state,
            supervisor_commands=supervisor_commands,
            plan_status=decision["plan_status"],
        ),
        "metadata": _operator_control_execution_worker_plan_metadata(
            state=state,
            supervisor_commands=supervisor_commands,
            plan_status=decision["plan_status"],
            planned_at=normalized_planned_at,
        ),
    }
    return validate_artifact_retention_scheduler_daemon_operator_control_execution_worker_plan(
        plan
    )


def validate_artifact_retention_scheduler_daemon_operator_control_execution_worker_plan(
    worker_plan: Mapping[str, Any],
) -> dict[str, Any]:
    error_code = (
        "ae.artifact_retention_scheduler_daemon_operator_control_execution_worker_plan_invalid"
    )
    if not isinstance(worker_plan, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "worker plan must be an object."
            ),
        )
    normalized = dict(worker_plan)
    if set(normalized) != {
        "operator_control_execution_worker_plan_schema_version",
        "operator_control_execution_worker_plan_id",
        "service_id",
        "scheduler_id",
        "operator_control_execution_state_id",
        "operator_control_execution_request_id",
        "action",
        "execution_mode",
        "plan_status",
        "decision_reason",
        "planned_at",
        "operator_control_execution_state",
        "supervisor_command_count",
        "supervisor_actions",
        "supervisor_command_ids",
        "guardrails",
        "metadata",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "worker plan keys are invalid."
            ),
        )
    if (
        normalized.get("operator_control_execution_worker_plan_schema_version")
        != AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_PLAN_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_operator_control_execution_worker_plan_schema_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "worker plan schema is invalid."
            ),
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "worker plan service id is invalid."
            ),
        )
    state = validate_artifact_retention_scheduler_daemon_operator_control_execution_state(
        normalized.get("operator_control_execution_state")
    )
    scheduler_id = _required_text(
        normalized.get("scheduler_id"),
        "scheduler_id",
        error_code=error_code,
    )
    if scheduler_id != state["scheduler_id"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "worker plan scheduler scope is invalid."
            ),
        )
    if normalized.get("operator_control_execution_state_id") != state[
        "operator_control_execution_state_id"
    ]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "worker plan state scope is invalid."
            ),
        )
    if normalized.get("operator_control_execution_request_id") != state[
        "operator_control_execution_request_id"
    ]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "worker plan request scope is invalid."
            ),
        )
    action = _normalize_daemon_operator_control_action(normalized.get("action"))
    if action != state["action"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "worker plan action scope is invalid."
            ),
        )
    execution_mode = _normalize_operator_control_execution_mode(
        normalized.get("execution_mode"),
        error_code=error_code,
    )
    if execution_mode != state["execution_mode"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "worker plan mode scope is invalid."
            ),
        )
    plan_status = _normalize_operator_control_execution_worker_plan_status(
        normalized.get("plan_status"),
        error_code=error_code,
    )
    planned_at = _required_text(
        normalized.get("planned_at"),
        "planned_at",
        error_code=error_code,
    )
    supervisor_commands = _operator_control_execution_worker_supervisor_commands(
        state
    )
    decision = _operator_control_execution_worker_plan_decision(
        state=state,
        supervisor_commands=supervisor_commands,
    )
    if plan_status != decision["plan_status"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "worker plan status is invalid."
            ),
        )
    if normalized.get("decision_reason") != decision["decision_reason"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "worker plan decision reason is invalid."
            ),
        )
    command_count = _bounded_non_negative_operator_control_count(
        normalized.get("supervisor_command_count"),
        "supervisor_command_count",
        error_code=error_code,
    )
    if command_count != len(supervisor_commands):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "worker plan command count is invalid."
            ),
        )
    supervisor_actions = [command["command"]["action"] for command in supervisor_commands]
    if normalized.get("supervisor_actions") != supervisor_actions:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "worker plan actions are invalid."
            ),
        )
    supervisor_command_ids = [
        command["daemon_supervisor_command_id"] for command in supervisor_commands
    ]
    if normalized.get("supervisor_command_ids") != supervisor_command_ids:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "worker plan command ids are invalid."
            ),
        )
    expected_guardrails = _operator_control_execution_worker_plan_guardrails(
        state=state,
        supervisor_commands=supervisor_commands,
        plan_status=plan_status,
    )
    if normalized.get("guardrails") != expected_guardrails:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "worker plan guardrails are invalid."
            ),
        )
    expected_metadata = _operator_control_execution_worker_plan_metadata(
        state=state,
        supervisor_commands=supervisor_commands,
        plan_status=plan_status,
        planned_at=planned_at,
    )
    if normalized.get("metadata") != expected_metadata:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "worker plan metadata is invalid."
            ),
        )
    expected_id = _operator_control_execution_worker_plan_id(
        scheduler_id=scheduler_id,
        operator_control_execution_state_id=state[
            "operator_control_execution_state_id"
        ],
        plan_status=plan_status,
        planned_at=planned_at,
    )
    if normalized.get("operator_control_execution_worker_plan_id") != expected_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "worker plan id is invalid."
            ),
        )
    normalized["action"] = action
    normalized["execution_mode"] = execution_mode
    normalized["plan_status"] = plan_status
    normalized["operator_control_execution_state"] = state
    assert_artifact_retention_payload_safe(normalized)
    return normalized


def summarize_artifact_retention_scheduler_daemon_operator_control_execution_worker_plan(
    worker_plan: Mapping[str, Any],
) -> dict[str, Any]:
    validated = (
        validate_artifact_retention_scheduler_daemon_operator_control_execution_worker_plan(
            worker_plan
        )
    )
    return {
        "scheduler_id": validated["scheduler_id"],
        "operator_control_execution_worker_plan_id": validated[
            "operator_control_execution_worker_plan_id"
        ],
        "operator_control_execution_state_id": validated[
            "operator_control_execution_state_id"
        ],
        "operator_control_execution_request_id": validated[
            "operator_control_execution_request_id"
        ],
        "action": validated["action"],
        "execution_mode": validated["execution_mode"],
        "plan_status": validated["plan_status"],
        "decision_reason": validated["decision_reason"],
        "supervisor_command_count": validated["supervisor_command_count"],
        "supervisor_actions": list(validated["supervisor_actions"]),
        "ready_for_worker": validated["metadata"]["ready_for_worker"],
        "safe_for_ag_projection": validated["metadata"]["safe_for_ag_projection"],
    }


def operator_control_execution_worker_plan_summary_line(
    worker_plan: Mapping[str, Any],
) -> str:
    summary = (
        summarize_artifact_retention_scheduler_daemon_operator_control_execution_worker_plan(
            worker_plan
        )
    )
    actions = ",".join(summary["supervisor_actions"]) or "none"
    return (
        "ae_scheduler_daemon_operator_control_execution_worker_plan=pass "
        f"scheduler_id={summary['scheduler_id']} "
        f"action={summary['action']} "
        f"status={summary['plan_status']} "
        f"reason={summary['decision_reason']} "
        f"commands={summary['supervisor_command_count']} "
        f"next={actions}"
    )


def build_artifact_retention_scheduler_daemon_operator_control_execution_worker_command(
    *,
    operator_control_execution_worker_plan: Mapping[str, Any],
    commanded_at: str | None = None,
) -> dict[str, Any]:
    plan = validate_artifact_retention_scheduler_daemon_operator_control_execution_worker_plan(
        operator_control_execution_worker_plan
    )
    normalized_commanded_at = _required_text(
        commanded_at or plan["planned_at"],
        "commanded_at",
        error_code=(
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_worker_command_invalid"
        ),
    )
    supervisor_commands = _operator_control_execution_worker_supervisor_commands(
        plan["operator_control_execution_state"]
    )
    command_status = (
        "READY"
        if plan["plan_status"] == "READY" and len(supervisor_commands) > 0
        else "BLOCKED"
    )
    worker_command = {
        "operator_control_execution_worker_command_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_COMMAND_SCHEMA_VERSION
        ),
        "operator_control_execution_worker_command_id": (
            _operator_control_execution_worker_command_id(
                scheduler_id=plan["scheduler_id"],
                operator_control_execution_worker_plan_id=plan[
                    "operator_control_execution_worker_plan_id"
                ],
                command_status=command_status,
                commanded_at=normalized_commanded_at,
            )
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": plan["scheduler_id"],
        "operator_control_execution_worker_plan_id": plan[
            "operator_control_execution_worker_plan_id"
        ],
        "operator_control_execution_state_id": plan[
            "operator_control_execution_state_id"
        ],
        "operator_control_execution_request_id": plan[
            "operator_control_execution_request_id"
        ],
        "action": plan["action"],
        "execution_mode": plan["execution_mode"],
        "worker_mode": "fake_dry_run_supervisor_persistent_dispatch_worker",
        "command_status": command_status,
        "decision_reason": (
            "worker_command_ready_for_fake_dry_run_supervisor_dispatch"
            if command_status == "READY"
            else plan["decision_reason"]
        ),
        "commanded_at": normalized_commanded_at,
        "operator_control_execution_worker_plan": deepcopy(plan),
        "supervisor_command_count": (
            len(supervisor_commands) if command_status == "READY" else 0
        ),
        "supervisor_commands": (
            [deepcopy(command) for command in supervisor_commands]
            if command_status == "READY"
            else []
        ),
        "guardrails": _operator_control_execution_worker_command_guardrails(
            plan=plan,
            command_status=command_status,
        ),
        "metadata": _operator_control_execution_worker_command_metadata(
            plan=plan,
            command_status=command_status,
            commanded_at=normalized_commanded_at,
        ),
    }
    return validate_artifact_retention_scheduler_daemon_operator_control_execution_worker_command(
        worker_command
    )


def validate_artifact_retention_scheduler_daemon_operator_control_execution_worker_command(
    worker_command: Mapping[str, Any],
) -> dict[str, Any]:
    error_code = (
        "ae.artifact_retention_scheduler_daemon_operator_control_execution_worker_command_invalid"
    )
    if not isinstance(worker_command, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "worker command must be an object."
            ),
        )
    normalized = dict(worker_command)
    if set(normalized) != {
        "operator_control_execution_worker_command_schema_version",
        "operator_control_execution_worker_command_id",
        "service_id",
        "scheduler_id",
        "operator_control_execution_worker_plan_id",
        "operator_control_execution_state_id",
        "operator_control_execution_request_id",
        "action",
        "execution_mode",
        "worker_mode",
        "command_status",
        "decision_reason",
        "commanded_at",
        "operator_control_execution_worker_plan",
        "supervisor_command_count",
        "supervisor_commands",
        "guardrails",
        "metadata",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "worker command keys are invalid."
            ),
        )
    if (
        normalized.get("operator_control_execution_worker_command_schema_version")
        != AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_COMMAND_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_operator_control_execution_worker_command_schema_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "worker command schema is invalid."
            ),
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "worker command service id is invalid."
            ),
        )
    plan = validate_artifact_retention_scheduler_daemon_operator_control_execution_worker_plan(
        normalized.get("operator_control_execution_worker_plan")
    )
    scheduler_id = _required_text(
        normalized.get("scheduler_id"),
        "scheduler_id",
        error_code=error_code,
    )
    if scheduler_id != plan["scheduler_id"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "worker command scheduler scope is invalid."
            ),
        )
    if normalized.get("operator_control_execution_worker_plan_id") != plan[
        "operator_control_execution_worker_plan_id"
    ]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "worker command plan scope is invalid."
            ),
        )
    for field_name in (
        "operator_control_execution_state_id",
        "operator_control_execution_request_id",
    ):
        if normalized.get(field_name) != plan[field_name]:
            raise ArtifactHandoffError(
                status_code=422,
                error_code=error_code,
                detail=(
                    "Artifact retention scheduler daemon operator control "
                    "execution worker command source scope is invalid."
                ),
            )
    action = _normalize_daemon_operator_control_action(normalized.get("action"))
    if action != plan["action"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "worker command action scope is invalid."
            ),
        )
    execution_mode = _normalize_operator_control_execution_mode(
        normalized.get("execution_mode"),
        error_code=error_code,
    )
    if execution_mode != plan["execution_mode"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "worker command mode scope is invalid."
            ),
        )
    if normalized.get("worker_mode") != "fake_dry_run_supervisor_persistent_dispatch_worker":
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "worker command mode is invalid."
            ),
        )
    command_status = _normalize_operator_control_execution_worker_command_status(
        normalized.get("command_status"),
        error_code=error_code,
    )
    expected_status = "READY" if plan["plan_status"] == "READY" else "BLOCKED"
    if command_status != expected_status:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "worker command status is invalid."
            ),
        )
    commanded_at = _required_text(
        normalized.get("commanded_at"),
        "commanded_at",
        error_code=error_code,
    )
    expected_reason = (
        "worker_command_ready_for_fake_dry_run_supervisor_dispatch"
        if command_status == "READY"
        else plan["decision_reason"]
    )
    if normalized.get("decision_reason") != expected_reason:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "worker command decision reason is invalid."
            ),
        )
    supervisor_commands = _validate_operator_control_execution_worker_supervisor_commands(
        normalized.get("supervisor_commands"),
        error_code=error_code,
    )
    expected_commands = (
        _operator_control_execution_worker_supervisor_commands(
            plan["operator_control_execution_state"]
        )
        if command_status == "READY"
        else []
    )
    command_count = _bounded_non_negative_operator_control_count(
        normalized.get("supervisor_command_count"),
        "supervisor_command_count",
        error_code=error_code,
    )
    if command_count != len(expected_commands) or supervisor_commands != expected_commands:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "worker command supervisor commands are invalid."
            ),
        )
    expected_guardrails = _operator_control_execution_worker_command_guardrails(
        plan=plan,
        command_status=command_status,
    )
    if normalized.get("guardrails") != expected_guardrails:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "worker command guardrails are invalid."
            ),
        )
    expected_metadata = _operator_control_execution_worker_command_metadata(
        plan=plan,
        command_status=command_status,
        commanded_at=commanded_at,
    )
    if normalized.get("metadata") != expected_metadata:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "worker command metadata is invalid."
            ),
        )
    expected_id = _operator_control_execution_worker_command_id(
        scheduler_id=scheduler_id,
        operator_control_execution_worker_plan_id=plan[
            "operator_control_execution_worker_plan_id"
        ],
        command_status=command_status,
        commanded_at=commanded_at,
    )
    if normalized.get("operator_control_execution_worker_command_id") != expected_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "worker command id is invalid."
            ),
        )
    normalized["action"] = action
    normalized["execution_mode"] = execution_mode
    normalized["command_status"] = command_status
    normalized["operator_control_execution_worker_plan"] = plan
    normalized["supervisor_commands"] = supervisor_commands
    assert_artifact_retention_payload_safe(normalized)
    return normalized


def summarize_artifact_retention_scheduler_daemon_operator_control_execution_worker_command(
    worker_command: Mapping[str, Any],
) -> dict[str, Any]:
    validated = (
        validate_artifact_retention_scheduler_daemon_operator_control_execution_worker_command(
            worker_command
        )
    )
    return {
        "scheduler_id": validated["scheduler_id"],
        "operator_control_execution_worker_command_id": validated[
            "operator_control_execution_worker_command_id"
        ],
        "operator_control_execution_worker_plan_id": validated[
            "operator_control_execution_worker_plan_id"
        ],
        "operator_control_execution_state_id": validated[
            "operator_control_execution_state_id"
        ],
        "action": validated["action"],
        "execution_mode": validated["execution_mode"],
        "worker_mode": validated["worker_mode"],
        "command_status": validated["command_status"],
        "decision_reason": validated["decision_reason"],
        "supervisor_command_count": validated["supervisor_command_count"],
        "supervisor_actions": [
            command["command"]["action"] for command in validated["supervisor_commands"]
        ],
        "ready_for_worker_execution": validated["metadata"][
            "ready_for_worker_execution"
        ],
        "safe_for_ag_projection": validated["metadata"]["safe_for_ag_projection"],
    }


def operator_control_execution_worker_command_summary_line(
    worker_command: Mapping[str, Any],
) -> str:
    summary = (
        summarize_artifact_retention_scheduler_daemon_operator_control_execution_worker_command(
            worker_command
        )
    )
    actions = ",".join(summary["supervisor_actions"]) or "none"
    return (
        "ae_scheduler_daemon_operator_control_execution_worker_command=pass "
        f"scheduler_id={summary['scheduler_id']} "
        f"action={summary['action']} "
        f"status={summary['command_status']} "
        f"reason={summary['decision_reason']} "
        f"commands={summary['supervisor_command_count']} "
        f"next={actions}"
    )


def normalize_artifact_retention_scheduler_daemon_operator_control_execution_limit(
    limit: int | str | None,
) -> int:
    if limit is None:
        return 20
    return _bounded_positive_int(
        limit,
        "limit",
        max_value=(
            MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_STATE_LIMIT
        ),
        error_code=(
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_collection_invalid"
        ),
    )


def build_artifact_retention_scheduler_daemon_operator_control_execution_collection(
    records: Sequence[Mapping[str, Any]],
    *,
    scheduler_id: str | None = None,
    action: str | None = None,
    execution_status: str | None = None,
    idempotency_status: str | None = None,
    limit: int | str | None = None,
) -> dict[str, Any]:
    normalized_limit = (
        normalize_artifact_retention_scheduler_daemon_operator_control_execution_limit(
            limit
        )
    )
    normalized_scheduler_id = optional_text(scheduler_id)
    normalized_action = _optional_operator_control_execution_action(
        action,
        error_code=(
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_collection_invalid"
        ),
    )
    normalized_execution_status = (
        _optional_operator_control_execution_state_status(
            execution_status,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_operator_control_execution_collection_invalid"
            ),
        )
    )
    normalized_idempotency_status = (
        _optional_operator_control_execution_idempotency_status(
            idempotency_status,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_operator_control_execution_collection_invalid"
            ),
        )
    )
    normalized_records = [
        validate_artifact_retention_scheduler_daemon_operator_control_execution_state(
            record
        )
        for record in records
    ]
    collection = {
        "operator_control_execution_collection_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_COLLECTION_SCHEMA_VERSION
        ),
        "service_id": "nex-ae-api",
        "filter": {
            "scheduler_id": normalized_scheduler_id,
            "action": normalized_action,
            "execution_status": normalized_execution_status,
            "idempotency_status": normalized_idempotency_status,
        },
        "count": len(normalized_records),
        "limit": normalized_limit,
        "items": [
            _operator_control_execution_collection_item(record)
            for record in normalized_records
        ],
        "guardrails": _operator_control_execution_read_model_guardrails(
            read_only=True
        ),
        "metadata": _operator_control_execution_collection_metadata(
            records=normalized_records,
            limit=normalized_limit,
        ),
    }
    assert_artifact_retention_payload_safe(collection)
    return collection


def build_artifact_retention_scheduler_daemon_operator_control_execution_detail(
    *,
    execution_state: Mapping[str, Any],
    transitions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    state = (
        validate_artifact_retention_scheduler_daemon_operator_control_execution_state(
            execution_state
        )
    )
    normalized_transitions = [
        validate_artifact_retention_scheduler_daemon_operator_control_execution_state_transition(
            transition
        )
        for transition in transitions
    ]
    for transition in normalized_transitions:
        if transition["operator_control_execution_state_id"] != state[
            "operator_control_execution_state_id"
        ]:
            raise ArtifactHandoffError(
                status_code=422,
                error_code=(
                    "ae.artifact_retention_scheduler_daemon_operator_control_execution_detail_invalid"
                ),
                detail=(
                    "Artifact retention scheduler daemon operator control "
                    "execution detail transition scope is invalid."
                ),
            )
    detail = {
        "operator_control_execution_detail_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_DETAIL_SCHEMA_VERSION
        ),
        "service_id": "nex-ae-api",
        "operator_control_execution_state_id": state[
            "operator_control_execution_state_id"
        ],
        "execution_state": state,
        "transition_count": len(normalized_transitions),
        "transitions": normalized_transitions,
        "guardrails": _operator_control_execution_read_model_guardrails(
            read_only=True
        ),
        "metadata": _operator_control_execution_detail_metadata(
            execution_state=state,
            transitions=normalized_transitions,
        ),
    }
    assert_artifact_retention_payload_safe(detail)
    return detail


def build_artifact_retention_scheduler_daemon_supervisor_command(
    *,
    action: str = "status_probe",
    scheduler_config: Mapping[str, Any] | None = None,
    profile: str = "test",
    enabled: bool = False,
    explicit_opt_in: bool = False,
    checked_at: str | None = None,
    interval_seconds: int | str | None = None,
    jitter_seconds: int | str | None = None,
    backoff_seconds: int | str | None = None,
    max_cycles: int | str = 1,
    run_worker: bool = False,
    requested_by: Mapping[str, Any] | None = None,
    reason: str | None = None,
    supervisor_mode: str = DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_MODE,
    output_format: str = "json",
) -> dict[str, Any]:
    error_code = "ae.artifact_retention_scheduler_daemon_supervisor_command_invalid"
    normalized_action = _normalize_daemon_supervisor_action(action)
    normalized_supervisor_mode = _normalize_daemon_supervisor_mode(supervisor_mode)
    normalized_max_cycles = _bounded_positive_int(
        max_cycles,
        "max_cycles",
        max_value=MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_MAX_CYCLES,
        error_code=error_code,
    )
    normalized_run_worker = _required_bool(
        run_worker,
        "run_worker",
        error_code=error_code,
    )
    normalized_output_format = _normalize_output_format(
        output_format,
        error_code=error_code,
    )
    config = (
        dict(scheduler_config)
        if scheduler_config is not None
        else build_artifact_retention_scheduler_config()
    )
    runtime_config = build_artifact_retention_scheduler_daemon_runtime_config(
        scheduler_config=config,
        profile=profile,
        enabled=enabled,
        explicit_opt_in=explicit_opt_in,
        checked_at=checked_at,
        interval_seconds=interval_seconds,
        jitter_seconds=jitter_seconds,
        backoff_seconds=backoff_seconds,
    )
    _ensure_daemon_supervisor_command_enablement(
        action=normalized_action,
        runtime_config=runtime_config,
        error_code=error_code,
    )
    daemon_config = build_artifact_retention_scheduler_daemon_config(
        scheduler_config=config,
        checked_at=runtime_config["checked_at"],
    )
    lifecycle_status = (
        "STARTING"
        if normalized_action == "start_daemon"
        and runtime_config["enablement"]["enablement_status"] == "READY"
        else "DISABLED"
    )
    runtime_state = build_artifact_retention_scheduler_daemon_runtime_state(
        scheduler_config=config,
        runtime_config=runtime_config,
        daemon_config=daemon_config,
        lifecycle_status=lifecycle_status,
        lifecycle_reason=None,
        observed_at=runtime_config["checked_at"],
    )
    command = {
        "action": normalized_action,
        "entrypoint": DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ENTRYPOINT,
        "profile": runtime_config["enablement"]["profile"],
        "enabled": runtime_config["enablement"]["enabled"],
        "explicit_opt_in": runtime_config["enablement"]["explicit_opt_in"],
        "checked_at": runtime_config["checked_at"],
        "max_cycles": normalized_max_cycles,
        "run_worker": normalized_run_worker,
        "output_format": normalized_output_format,
        "supervisor_mode": normalized_supervisor_mode,
    }
    supervisor_command = {
        "daemon_supervisor_command_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_COMMAND_SCHEMA_VERSION
        ),
        "daemon_supervisor_command_id": _daemon_supervisor_command_id(
            scheduler_id=runtime_config["scheduler_id"],
            command=command,
            runtime_state=runtime_state,
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": runtime_config["scheduler_id"],
        "command": command,
        "runtime_config": deepcopy(runtime_config),
        "daemon_config": deepcopy(daemon_config),
        "runtime_state": deepcopy(runtime_state),
        "execution_plan": _daemon_supervisor_command_execution_plan(
            action=normalized_action,
            runtime_config=runtime_config,
        ),
        "guardrails": _daemon_supervisor_command_guardrails(action=normalized_action),
        "metadata": _daemon_supervisor_command_metadata(
            action=normalized_action,
            runtime_config=runtime_config,
            runtime_state=runtime_state,
            command=command,
            requested_by=requested_by,
            reason=reason,
        ),
    }
    return validate_artifact_retention_scheduler_daemon_supervisor_command(
        supervisor_command
    )


def validate_artifact_retention_scheduler_daemon_supervisor_command(
    supervisor_command: Mapping[str, Any],
) -> dict[str, Any]:
    error_code = "ae.artifact_retention_scheduler_daemon_supervisor_command_invalid"
    if not isinstance(supervisor_command, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor command must be "
                "an object."
            ),
        )
    normalized = dict(supervisor_command)
    if set(normalized) != {
        "daemon_supervisor_command_schema_version",
        "daemon_supervisor_command_id",
        "service_id",
        "scheduler_id",
        "command",
        "runtime_config",
        "daemon_config",
        "runtime_state",
        "execution_plan",
        "guardrails",
        "metadata",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor command keys "
                "are invalid."
            ),
        )
    if (
        normalized.get("daemon_supervisor_command_schema_version")
        != AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_COMMAND_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_supervisor_command_schema_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon supervisor command schema "
                "is invalid."
            ),
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor command service "
                "id is invalid."
            ),
        )
    scheduler_id = _required_text(
        normalized.get("scheduler_id"),
        "scheduler_id",
        error_code=error_code,
    )
    command = _validate_daemon_supervisor_command_payload(
        normalized.get("command")
    )
    runtime_config = validate_artifact_retention_scheduler_daemon_runtime_config(
        normalized.get("runtime_config")
    )
    daemon_config = validate_artifact_retention_scheduler_daemon_config(
        normalized.get("daemon_config")
    )
    runtime_state = validate_artifact_retention_scheduler_daemon_runtime_state(
        normalized.get("runtime_state")
    )
    _ensure_daemon_supervisor_command_scope(
        scheduler_id=scheduler_id,
        command=command,
        runtime_config=runtime_config,
        daemon_config=daemon_config,
        runtime_state=runtime_state,
        error_code=error_code,
    )
    _ensure_daemon_supervisor_command_enablement(
        action=command["action"],
        runtime_config=runtime_config,
        error_code=error_code,
    )
    expected_plan = _daemon_supervisor_command_execution_plan(
        action=command["action"],
        runtime_config=runtime_config,
    )
    if normalized.get("execution_plan") != expected_plan:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor command "
                "execution plan is invalid."
            ),
        )
    if normalized.get("guardrails") != _daemon_supervisor_command_guardrails(
        action=command["action"]
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor command "
                "guardrails are invalid."
            ),
        )
    metadata_value = normalized.get("metadata")
    metadata_mapping = metadata_value if isinstance(metadata_value, Mapping) else {}
    expected_metadata = _daemon_supervisor_command_metadata(
        action=command["action"],
        runtime_config=runtime_config,
        runtime_state=runtime_state,
        command=command,
        requested_by=metadata_mapping.get("requested_by"),
        reason=metadata_mapping.get("reason"),
    )
    if normalized.get("metadata") != expected_metadata:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor command "
                "metadata is invalid."
            ),
        )
    expected_id = _daemon_supervisor_command_id(
        scheduler_id=scheduler_id,
        command=command,
        runtime_state=runtime_state,
    )
    if normalized.get("daemon_supervisor_command_id") != expected_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor command id is "
                "invalid."
            ),
        )
    normalized["command"] = command
    normalized["runtime_config"] = runtime_config
    normalized["daemon_config"] = daemon_config
    normalized["runtime_state"] = runtime_state
    assert_artifact_retention_payload_safe(normalized)
    return normalized


def summarize_artifact_retention_scheduler_daemon_supervisor_command(
    supervisor_command: Mapping[str, Any],
) -> dict[str, Any]:
    validated = validate_artifact_retention_scheduler_daemon_supervisor_command(
        supervisor_command
    )
    return {
        "scheduler_id": validated["scheduler_id"],
        "action": validated["command"]["action"],
        "profile": validated["command"]["profile"],
        "enabled": validated["command"]["enabled"],
        "explicit_opt_in": validated["command"]["explicit_opt_in"],
        "supervisor_mode": validated["command"]["supervisor_mode"],
        "max_cycles": validated["command"]["max_cycles"],
        "run_worker": validated["command"]["run_worker"],
        "output_format": validated["command"]["output_format"],
        "runtime_ready": validated["metadata"]["runtime_ready"],
        "supervisor_adapter_required": validated["guardrails"][
            "supervisor_adapter_required"
        ],
        "supervisor_adapter_invoked": validated["metadata"][
            "supervisor_adapter_invoked"
        ],
        "starts_process": validated["execution_plan"]["starts_process"],
        "stops_process": validated["execution_plan"]["stops_process"],
        "safe_for_ag_projection": validated["metadata"]["safe_for_ag_projection"],
    }


def supervisor_command_summary_line(
    supervisor_command: Mapping[str, Any],
) -> str:
    summary = summarize_artifact_retention_scheduler_daemon_supervisor_command(
        supervisor_command
    )
    return (
        "ae_scheduler_daemon_supervisor_command=pass "
        f"scheduler_id={summary['scheduler_id']} "
        f"action={summary['action']} "
        f"profile={summary['profile']} "
        f"ready={int(summary['runtime_ready'])} "
        f"adapter_required={int(summary['supervisor_adapter_required'])} "
        f"adapter_invoked={int(summary['supervisor_adapter_invoked'])} "
        f"starts_process={int(summary['starts_process'])} "
        f"stops_process={int(summary['stops_process'])}"
    )


def build_artifact_retention_scheduler_daemon_supervisor_result(
    *,
    supervisor_command: Mapping[str, Any],
    result_status: str | None = None,
    observed_at: str | None = None,
    message: str | None = None,
    supervisor_adapter_available: bool = False,
    supervisor_adapter_invoked: bool = False,
    adapter_name: str | None = None,
    process_started: bool = False,
    process_stopped: bool = False,
) -> dict[str, Any]:
    command = validate_artifact_retention_scheduler_daemon_supervisor_command(
        supervisor_command
    )
    adapter_state = _daemon_supervisor_adapter_state(
        supervisor_adapter_available=supervisor_adapter_available,
        supervisor_adapter_invoked=supervisor_adapter_invoked,
        adapter_name=adapter_name,
        process_started=process_started,
        process_stopped=process_stopped,
    )
    normalized_observed_at = _required_text(
        observed_at or _daemon_datetime_value(datetime.now(UTC)),
        "observed_at",
        error_code="ae.artifact_retention_scheduler_daemon_supervisor_result_invalid",
    )
    normalized_status = _normalize_daemon_supervisor_result_status(
        result_status
        or _default_daemon_supervisor_result_status(command["command"]["action"])
    )
    decision_reason = _daemon_supervisor_result_decision_reason(
        action=command["command"]["action"],
        result_status=normalized_status,
        supervisor_adapter_invoked=adapter_state["supervisor_adapter_invoked"],
    )
    result = {
        "daemon_supervisor_result_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_RESULT_SCHEMA_VERSION
        ),
        "daemon_supervisor_result_id": _daemon_supervisor_result_id(
            supervisor_command=command,
            result_status=normalized_status,
            observed_at=normalized_observed_at,
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": command["scheduler_id"],
        "action": command["command"]["action"],
        "result_status": normalized_status,
        "decision_reason": decision_reason,
        "observed_at": normalized_observed_at,
        "message": optional_text(message),
        "supervisor_command": deepcopy(command),
        "runtime_state": deepcopy(command["runtime_state"]),
        "execution_plan": _daemon_supervisor_result_execution_plan(
            action=command["command"]["action"],
            result_status=normalized_status,
            adapter_state=adapter_state,
        ),
        "guardrails": _daemon_supervisor_result_guardrails(
            action=command["command"]["action"],
            result_status=normalized_status,
            adapter_state=adapter_state,
        ),
        "metadata": _daemon_supervisor_result_metadata(
            command=command,
            result_status=normalized_status,
            decision_reason=decision_reason,
            observed_at=normalized_observed_at,
            message=message,
            adapter_state=adapter_state,
        ),
    }
    return validate_artifact_retention_scheduler_daemon_supervisor_result(result)


def validate_artifact_retention_scheduler_daemon_supervisor_result(
    supervisor_result: Mapping[str, Any],
) -> dict[str, Any]:
    error_code = "ae.artifact_retention_scheduler_daemon_supervisor_result_invalid"
    if not isinstance(supervisor_result, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor result must be "
                "an object."
            ),
        )
    normalized = dict(supervisor_result)
    if set(normalized) != {
        "daemon_supervisor_result_schema_version",
        "daemon_supervisor_result_id",
        "service_id",
        "scheduler_id",
        "action",
        "result_status",
        "decision_reason",
        "observed_at",
        "message",
        "supervisor_command",
        "runtime_state",
        "execution_plan",
        "guardrails",
        "metadata",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor result keys "
                "are invalid."
            ),
        )
    if (
        normalized.get("daemon_supervisor_result_schema_version")
        != AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_RESULT_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_supervisor_result_schema_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon supervisor result schema "
                "is invalid."
            ),
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor result service "
                "id is invalid."
            ),
        )
    scheduler_id = _required_text(
        normalized.get("scheduler_id"),
        "scheduler_id",
        error_code=error_code,
    )
    action = _daemon_supervisor_action_for_context(
        normalized.get("action"),
        error_code=error_code,
    )
    result_status = _normalize_daemon_supervisor_result_status(
        normalized.get("result_status")
    )
    decision_reason = _required_text(
        normalized.get("decision_reason"),
        "decision_reason",
        error_code=error_code,
    )
    observed_at = _required_text(
        normalized.get("observed_at"),
        "observed_at",
        error_code=error_code,
    )
    command = validate_artifact_retention_scheduler_daemon_supervisor_command(
        normalized.get("supervisor_command")
    )
    runtime_state = validate_artifact_retention_scheduler_daemon_runtime_state(
        normalized.get("runtime_state")
    )
    if command["scheduler_id"] != scheduler_id or command["command"]["action"] != action:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor result command "
                "scope is invalid."
            ),
        )
    if runtime_state != command["runtime_state"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor result runtime "
                "state is invalid."
            ),
        )
    adapter_state = _daemon_supervisor_adapter_state_from_result(normalized)
    expected_reason = _daemon_supervisor_result_decision_reason(
        action=action,
        result_status=result_status,
        supervisor_adapter_invoked=adapter_state["supervisor_adapter_invoked"],
    )
    if decision_reason != expected_reason:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor result decision "
                "reason is invalid."
            ),
        )
    expected_plan = _daemon_supervisor_result_execution_plan(
        action=action,
        result_status=result_status,
        adapter_state=adapter_state,
    )
    if normalized.get("execution_plan") != expected_plan:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor result execution "
                "plan is invalid."
            ),
        )
    expected_guardrails = _daemon_supervisor_result_guardrails(
        action=action,
        result_status=result_status,
        adapter_state=adapter_state,
    )
    if normalized.get("guardrails") != expected_guardrails:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor result guardrails "
                "are invalid."
            ),
        )
    expected_metadata = _daemon_supervisor_result_metadata(
        command=command,
        result_status=result_status,
        decision_reason=decision_reason,
        observed_at=observed_at,
        message=normalized.get("message"),
        adapter_state=adapter_state,
    )
    if normalized.get("metadata") != expected_metadata:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor result metadata "
                "is invalid."
            ),
        )
    expected_id = _daemon_supervisor_result_id(
        supervisor_command=command,
        result_status=result_status,
        observed_at=observed_at,
    )
    if normalized.get("daemon_supervisor_result_id") != expected_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor result id is "
                "invalid."
            ),
        )
    normalized["action"] = action
    normalized["result_status"] = result_status
    normalized["message"] = optional_text(normalized.get("message"))
    normalized["supervisor_command"] = command
    normalized["runtime_state"] = runtime_state
    assert_artifact_retention_payload_safe(normalized)
    return normalized


def summarize_artifact_retention_scheduler_daemon_supervisor_result(
    supervisor_result: Mapping[str, Any],
) -> dict[str, Any]:
    validated = validate_artifact_retention_scheduler_daemon_supervisor_result(
        supervisor_result
    )
    return {
        "scheduler_id": validated["scheduler_id"],
        "action": validated["action"],
        "result_status": validated["result_status"],
        "decision_reason": validated["decision_reason"],
        "observed_at": validated["observed_at"],
        "supervisor_adapter_invoked": validated["metadata"][
            "supervisor_adapter_invoked"
        ],
        "process_started": validated["metadata"]["process_started"],
        "process_stopped": validated["metadata"]["process_stopped"],
        "database_write_performed": validated["metadata"][
            "database_write_performed"
        ],
        "safe_for_ag_projection": validated["metadata"]["safe_for_ag_projection"],
    }


def supervisor_result_summary_line(supervisor_result: Mapping[str, Any]) -> str:
    summary = summarize_artifact_retention_scheduler_daemon_supervisor_result(
        supervisor_result
    )
    return (
        "ae_scheduler_daemon_supervisor_result=pass "
        f"scheduler_id={summary['scheduler_id']} "
        f"action={summary['action']} "
        f"status={summary['result_status']} "
        f"reason={summary['decision_reason']} "
        f"adapter_invoked={int(summary['supervisor_adapter_invoked'])} "
        f"process_started={int(summary['process_started'])} "
        f"process_stopped={int(summary['process_stopped'])}"
    )


def run_artifact_retention_scheduler_daemon_supervisor_command(
    *,
    supervisor_command: Mapping[str, Any],
    supervisor_adapter: ArtifactRetentionSchedulerDaemonSupervisorAdapter | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    command = validate_artifact_retention_scheduler_daemon_supervisor_command(
        supervisor_command
    )
    if supervisor_adapter is None:
        return build_artifact_retention_scheduler_daemon_supervisor_result(
            supervisor_command=command,
            observed_at=observed_at,
        )
    return supervisor_adapter.execute_supervisor_command(
        command,
        observed_at=observed_at,
    )


class FakeArtifactRetentionSchedulerDaemonSupervisorAdapter:
    adapter_name = DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_ADAPTER_NAME

    def execute_supervisor_command(
        self,
        supervisor_command: Mapping[str, Any],
        *,
        observed_at: str | None = None,
    ) -> dict[str, Any]:
        command = validate_artifact_retention_scheduler_daemon_supervisor_command(
            supervisor_command
        )
        return build_artifact_retention_scheduler_daemon_supervisor_result(
            supervisor_command=command,
            observed_at=observed_at,
            supervisor_adapter_available=True,
            supervisor_adapter_invoked=True,
            adapter_name=self.adapter_name,
            process_started=False,
            process_stopped=False,
        )


def build_artifact_retention_scheduler_daemon_supervised_process_snapshot(
    *,
    supervisor_command: Mapping[str, Any],
    process_status: str | None = None,
    process_id: int | str | None = None,
    host_id: str = "localhost",
    observed_at: str | None = None,
    started_at: str | None = None,
    completed_at: str | None = None,
    exit_code: int | str | None = None,
    termination_signal: str | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    command = validate_artifact_retention_scheduler_daemon_supervisor_command(
        supervisor_command
    )
    status = _normalize_daemon_supervised_process_status(
        process_status
        or _default_daemon_supervised_process_status(command["command"]["action"])
    )
    process = _daemon_supervised_process_process(
        command=command,
        process_id=process_id,
        host_id=host_id,
    )
    lifecycle = _daemon_supervised_process_lifecycle(
        process_status=status,
        observed_at=observed_at or command["command"]["checked_at"],
        started_at=started_at,
        completed_at=completed_at,
        exit_code=exit_code,
        termination_signal=termination_signal,
    )
    snapshot = {
        "daemon_supervised_process_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_SCHEMA_VERSION
        ),
        "daemon_supervised_process_id": _daemon_supervised_process_id(
            scheduler_id=command["scheduler_id"],
            command_id=command["daemon_supervisor_command_id"],
            process=process,
            lifecycle=lifecycle,
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": command["scheduler_id"],
        "daemon_supervisor_command_id": command["daemon_supervisor_command_id"],
        "action": command["command"]["action"],
        "process_mode": (
            DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_MODE
        ),
        "process": process,
        "lifecycle": lifecycle,
        "guardrails": _daemon_supervised_process_guardrails(
            command=command,
            lifecycle=lifecycle,
        ),
        "metadata": _daemon_supervised_process_metadata(
            command=command,
            process=process,
            lifecycle=lifecycle,
            message=message,
        ),
    }
    return validate_artifact_retention_scheduler_daemon_supervised_process_snapshot(
        snapshot
    )


def validate_artifact_retention_scheduler_daemon_supervised_process_snapshot(
    snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    error_code = "ae.artifact_retention_scheduler_daemon_supervised_process_invalid"
    if not isinstance(snapshot, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervised process snapshot "
                "must be an object."
            ),
        )
    normalized = dict(snapshot)
    if set(normalized) != {
        "daemon_supervised_process_schema_version",
        "daemon_supervised_process_id",
        "service_id",
        "scheduler_id",
        "daemon_supervisor_command_id",
        "action",
        "process_mode",
        "process",
        "lifecycle",
        "guardrails",
        "metadata",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervised process snapshot "
                "keys are invalid."
            ),
        )
    if (
        normalized.get("daemon_supervised_process_schema_version")
        != AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_supervised_process_schema_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon supervised process snapshot "
                "schema is invalid."
            ),
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervised process snapshot "
                "service id is invalid."
            ),
        )
    scheduler_id = _required_text(
        normalized.get("scheduler_id"),
        "scheduler_id",
        error_code=error_code,
    )
    command_id = _required_text(
        normalized.get("daemon_supervisor_command_id"),
        "daemon_supervisor_command_id",
        error_code=error_code,
    )
    action = _daemon_supervisor_action_for_context(
        normalized.get("action"),
        error_code=error_code,
    )
    if normalized.get("process_mode") != (
        DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_MODE
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervised process snapshot "
                "mode is invalid."
            ),
        )
    process = _validate_daemon_supervised_process_process(
        normalized.get("process"),
        error_code=error_code,
    )
    lifecycle = _validate_daemon_supervised_process_lifecycle(
        normalized.get("lifecycle"),
        error_code=error_code,
    )
    _ensure_daemon_supervised_process_consistency(
        action=action,
        scheduler_id=scheduler_id,
        command_id=command_id,
        process=process,
        lifecycle=lifecycle,
        error_code=error_code,
    )
    expected_guardrails = _daemon_supervised_process_guardrails(
        command={
            "scheduler_id": scheduler_id,
            "daemon_supervisor_command_id": command_id,
            "command": {"action": action},
        },
        lifecycle=lifecycle,
    )
    if normalized.get("guardrails") != expected_guardrails:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervised process snapshot "
                "guardrails are invalid."
            ),
        )
    metadata_value = normalized.get("metadata")
    metadata_mapping = metadata_value if isinstance(metadata_value, Mapping) else {}
    expected_metadata = _daemon_supervised_process_metadata(
        command={
            "scheduler_id": scheduler_id,
            "daemon_supervisor_command_id": command_id,
            "command": {"action": action},
        },
        process=process,
        lifecycle=lifecycle,
        message=metadata_mapping.get("message"),
    )
    if normalized.get("metadata") != expected_metadata:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervised process snapshot "
                "metadata is invalid."
            ),
        )
    expected_id = _daemon_supervised_process_id(
        scheduler_id=scheduler_id,
        command_id=command_id,
        process=process,
        lifecycle=lifecycle,
    )
    if normalized.get("daemon_supervised_process_id") != expected_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervised process snapshot "
                "id is invalid."
            ),
        )
    normalized["action"] = action
    normalized["process"] = process
    normalized["lifecycle"] = lifecycle
    assert_artifact_retention_payload_safe(normalized)
    return normalized


def summarize_artifact_retention_scheduler_daemon_supervised_process_snapshot(
    snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    validated = validate_artifact_retention_scheduler_daemon_supervised_process_snapshot(
        snapshot
    )
    return {
        "scheduler_id": validated["scheduler_id"],
        "daemon_supervised_process_id": validated["daemon_supervised_process_id"],
        "daemon_supervisor_command_id": validated["daemon_supervisor_command_id"],
        "action": validated["action"],
        "process_mode": validated["process_mode"],
        "process_status": validated["lifecycle"]["process_status"],
        "process_id": validated["process"]["process_id"],
        "host_id": validated["process"]["host_id"],
        "observed_at": validated["lifecycle"]["observed_at"],
        "started_at": validated["lifecycle"]["started_at"],
        "completed_at": validated["lifecycle"]["completed_at"],
        "exit_code": validated["lifecycle"]["exit_code"],
        "termination_signal": validated["lifecycle"]["termination_signal"],
        "process_running": validated["metadata"]["process_running"],
        "process_started_observed": validated["metadata"][
            "process_started_observed"
        ],
        "process_stopped_observed": validated["metadata"][
            "process_stopped_observed"
        ],
        "subprocess_adapter_required": validated["guardrails"][
            "subprocess_adapter_required"
        ],
        "safe_for_ag_projection": validated["metadata"]["safe_for_ag_projection"],
    }


def supervised_process_snapshot_summary_line(snapshot: Mapping[str, Any]) -> str:
    summary = summarize_artifact_retention_scheduler_daemon_supervised_process_snapshot(
        snapshot
    )
    process_id = summary["process_id"] if summary["process_id"] is not None else "none"
    return (
        "ae_scheduler_daemon_supervised_process_snapshot=pass "
        f"scheduler_id={summary['scheduler_id']} "
        f"action={summary['action']} "
        f"status={summary['process_status']} "
        f"process_id={process_id} "
        f"running={int(summary['process_running'])}"
    )


def build_artifact_retention_scheduler_daemon_process_lock(
    *,
    execute_command: Mapping[str, Any],
    process_id: int | str | None = None,
    host_id: str = "localhost",
    requested_at: str | None = None,
    stale_after_seconds: int | str = 600,
) -> dict[str, Any]:
    validated_command = validate_artifact_retention_scheduler_daemon_cli_execute_command(
        execute_command
    )
    error_code = "ae.artifact_retention_scheduler_daemon_process_lock_invalid"
    normalized_process_id = _bounded_positive_int(
        os.getpid() if process_id is None else process_id,
        "process_id",
        max_value=MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_PROCESS_ID,
        error_code=error_code,
    )
    normalized_host_id = _required_text(
        host_id,
        "host_id",
        error_code=error_code,
    )
    normalized_requested_at = _required_text(
        requested_at or validated_command["command"]["checked_at"],
        "requested_at",
        error_code=error_code,
    )
    normalized_stale_after = _bounded_positive_int(
        stale_after_seconds,
        "stale_after_seconds",
        max_value=(
            MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_PROCESS_LOCK_STALE_AFTER_SECONDS
        ),
        error_code=error_code,
    )
    process = {
        "process_id": normalized_process_id,
        "host_id": normalized_host_id,
        "lock_owner": _daemon_process_lock_owner(
            scheduler_id=validated_command["scheduler_id"],
            process_id=normalized_process_id,
            host_id=normalized_host_id,
        ),
        "entrypoint": validated_command["command"]["entrypoint"],
    }
    command_summary = _daemon_execute_command_summary(validated_command)
    process_lock = {
        "daemon_process_lock_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_PROCESS_LOCK_SCHEMA_VERSION
        ),
        "daemon_process_lock_id": _daemon_process_lock_id(
            scheduler_id=validated_command["scheduler_id"],
            command_id=validated_command["daemon_cli_execute_command_id"],
            process=process,
            requested_at=normalized_requested_at,
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": validated_command["scheduler_id"],
        "daemon_cli_execute_command_id": (
            validated_command["daemon_cli_execute_command_id"]
        ),
        "lock_scope": AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_PROCESS_LOCK_SCOPE,
        "lock_status": AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_PROCESS_LOCK_STATUS,
        "process": process,
        "timing": {
            "requested_at": normalized_requested_at,
            "stale_after_seconds": normalized_stale_after,
        },
        "command_summary": command_summary,
        "guardrails": _daemon_process_lock_guardrails(),
        "metadata": _daemon_process_lock_metadata(
            process=process,
            timing={
                "requested_at": normalized_requested_at,
                "stale_after_seconds": normalized_stale_after,
            },
            command_summary=command_summary,
        ),
    }
    return validate_artifact_retention_scheduler_daemon_process_lock(process_lock)


def validate_artifact_retention_scheduler_daemon_process_lock(
    process_lock: Mapping[str, Any],
) -> dict[str, Any]:
    error_code = "ae.artifact_retention_scheduler_daemon_process_lock_invalid"
    if not isinstance(process_lock, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail="Artifact retention scheduler daemon process lock must be an object.",
        )
    normalized = dict(process_lock)
    if set(normalized) != {
        "daemon_process_lock_schema_version",
        "daemon_process_lock_id",
        "service_id",
        "scheduler_id",
        "daemon_cli_execute_command_id",
        "lock_scope",
        "lock_status",
        "process",
        "timing",
        "command_summary",
        "guardrails",
        "metadata",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail="Artifact retention scheduler daemon process lock keys are invalid.",
        )
    if (
        normalized.get("daemon_process_lock_schema_version")
        != AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_PROCESS_LOCK_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_process_lock_schema_invalid",
            detail="Artifact retention scheduler daemon process lock schema is invalid.",
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail="Artifact retention scheduler daemon process lock service id is invalid.",
        )
    scheduler_id = _required_text(
        normalized.get("scheduler_id"),
        "scheduler_id",
        error_code=error_code,
    )
    command_id = _required_text(
        normalized.get("daemon_cli_execute_command_id"),
        "daemon_cli_execute_command_id",
        error_code=error_code,
    )
    if normalized.get("lock_scope") != (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_PROCESS_LOCK_SCOPE
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail="Artifact retention scheduler daemon process lock scope is invalid.",
        )
    if normalized.get("lock_status") != (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_PROCESS_LOCK_STATUS
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail="Artifact retention scheduler daemon process lock status is invalid.",
        )
    process = _validate_daemon_process_lock_process(normalized.get("process"))
    timing = _validate_daemon_process_lock_timing(normalized.get("timing"))
    if process["lock_owner"] != _daemon_process_lock_owner(
        scheduler_id=scheduler_id,
        process_id=process["process_id"],
        host_id=process["host_id"],
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail="Artifact retention scheduler daemon process lock owner is invalid.",
        )
    command_summary = _validate_daemon_execute_command_summary(
        normalized.get("command_summary"),
        error_code=error_code,
    )
    if normalized.get("guardrails") != _daemon_process_lock_guardrails():
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail="Artifact retention scheduler daemon process lock guardrails are invalid.",
        )
    expected_metadata = _daemon_process_lock_metadata(
        process=process,
        timing=timing,
        command_summary=command_summary,
    )
    if normalized.get("metadata") != expected_metadata:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail="Artifact retention scheduler daemon process lock metadata is invalid.",
        )
    expected_id = _daemon_process_lock_id(
        scheduler_id=scheduler_id,
        command_id=command_id,
        process=process,
        requested_at=timing["requested_at"],
    )
    if normalized.get("daemon_process_lock_id") != expected_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail="Artifact retention scheduler daemon process lock id is invalid.",
        )
    normalized["process"] = process
    normalized["timing"] = timing
    normalized["command_summary"] = command_summary
    assert_artifact_retention_payload_safe(normalized)
    return normalized


def summarize_artifact_retention_scheduler_daemon_process_lock(
    process_lock: Mapping[str, Any],
) -> dict[str, Any]:
    validated = validate_artifact_retention_scheduler_daemon_process_lock(process_lock)
    return {
        "scheduler_id": validated["scheduler_id"],
        "daemon_cli_execute_command_id": validated["daemon_cli_execute_command_id"],
        "daemon_process_lock_id": validated["daemon_process_lock_id"],
        "lock_status": validated["lock_status"],
        "process_id": validated["process"]["process_id"],
        "host_id": validated["process"]["host_id"],
        "requested_at": validated["timing"]["requested_at"],
        "stale_after_seconds": validated["timing"]["stale_after_seconds"],
        "process_lock_required": validated["guardrails"]["process_lock_required"],
        "process_lock_acquired": validated["guardrails"]["process_lock_acquired"],
        "database_write_performed": validated["guardrails"][
            "database_write_performed"
        ],
    }


def process_lock_summary_line(process_lock: Mapping[str, Any]) -> str:
    summary = summarize_artifact_retention_scheduler_daemon_process_lock(
        process_lock
    )
    return (
        "ae_scheduler_daemon_process_lock=pass "
        f"scheduler_id={summary['scheduler_id']} "
        f"lock_status={summary['lock_status']} "
        f"process_id={summary['process_id']} "
        f"stale_after_seconds={summary['stale_after_seconds']} "
        f"acquired={int(summary['process_lock_acquired'])}"
    )


def build_artifact_retention_scheduler_daemon_run_metadata(
    *,
    execute_command: Mapping[str, Any],
    process_lock: Mapping[str, Any],
    run_status: str = "PENDING",
    requested_at: str | None = None,
    started_at: str | None = None,
    completed_at: str | None = None,
) -> dict[str, Any]:
    validated_command = validate_artifact_retention_scheduler_daemon_cli_execute_command(
        execute_command
    )
    validated_lock = validate_artifact_retention_scheduler_daemon_process_lock(
        process_lock
    )
    _ensure_daemon_run_metadata_scope(
        execute_command=validated_command,
        process_lock=validated_lock,
    )
    lifecycle = _validate_daemon_run_metadata_lifecycle(
        {
            "run_status": run_status,
            "requested_at": requested_at or validated_lock["timing"]["requested_at"],
            "started_at": started_at,
            "completed_at": completed_at,
        }
    )
    command_summary = _daemon_execute_command_summary(validated_command)
    run_metadata = {
        "daemon_run_metadata_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUN_METADATA_SCHEMA_VERSION
        ),
        "daemon_run_id": _daemon_run_metadata_id(
            scheduler_id=validated_command["scheduler_id"],
            command_id=validated_command["daemon_cli_execute_command_id"],
            process_lock_id=validated_lock["daemon_process_lock_id"],
            process=validated_lock["process"],
            lifecycle=lifecycle,
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": validated_command["scheduler_id"],
        "daemon_cli_execute_command_id": (
            validated_command["daemon_cli_execute_command_id"]
        ),
        "daemon_process_lock_id": validated_lock["daemon_process_lock_id"],
        "process": deepcopy(validated_lock["process"]),
        "command_summary": command_summary,
        "lifecycle": lifecycle,
        "guardrails": _daemon_run_metadata_guardrails(),
        "metadata": _daemon_run_metadata_metadata(
            process=validated_lock["process"],
            command_summary=command_summary,
            lifecycle=lifecycle,
        ),
    }
    return validate_artifact_retention_scheduler_daemon_run_metadata(run_metadata)


def validate_artifact_retention_scheduler_daemon_run_metadata(
    run_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    error_code = "ae.artifact_retention_scheduler_daemon_run_metadata_invalid"
    if not isinstance(run_metadata, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail="Artifact retention scheduler daemon run metadata must be an object.",
        )
    normalized = dict(run_metadata)
    if set(normalized) != {
        "daemon_run_metadata_schema_version",
        "daemon_run_id",
        "service_id",
        "scheduler_id",
        "daemon_cli_execute_command_id",
        "daemon_process_lock_id",
        "process",
        "command_summary",
        "lifecycle",
        "guardrails",
        "metadata",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail="Artifact retention scheduler daemon run metadata keys are invalid.",
        )
    if (
        normalized.get("daemon_run_metadata_schema_version")
        != AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUN_METADATA_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_run_metadata_schema_invalid",
            detail="Artifact retention scheduler daemon run metadata schema is invalid.",
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail="Artifact retention scheduler daemon run metadata service id is invalid.",
        )
    scheduler_id = _required_text(
        normalized.get("scheduler_id"),
        "scheduler_id",
        error_code=error_code,
    )
    command_id = _required_text(
        normalized.get("daemon_cli_execute_command_id"),
        "daemon_cli_execute_command_id",
        error_code=error_code,
    )
    process_lock_id = _required_text(
        normalized.get("daemon_process_lock_id"),
        "daemon_process_lock_id",
        error_code=error_code,
    )
    process = _validate_daemon_process_lock_process(
        normalized.get("process"),
        error_code=error_code,
    )
    command_summary = _validate_daemon_execute_command_summary(
        normalized.get("command_summary"),
        error_code=error_code,
    )
    lifecycle = _validate_daemon_run_metadata_lifecycle(normalized.get("lifecycle"))
    if normalized.get("guardrails") != _daemon_run_metadata_guardrails():
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail="Artifact retention scheduler daemon run metadata guardrails are invalid.",
        )
    expected_metadata = _daemon_run_metadata_metadata(
        process=process,
        command_summary=command_summary,
        lifecycle=lifecycle,
    )
    if normalized.get("metadata") != expected_metadata:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail="Artifact retention scheduler daemon run metadata metadata is invalid.",
        )
    expected_id = _daemon_run_metadata_id(
        scheduler_id=scheduler_id,
        command_id=command_id,
        process_lock_id=process_lock_id,
        process=process,
        lifecycle=lifecycle,
    )
    if normalized.get("daemon_run_id") != expected_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail="Artifact retention scheduler daemon run metadata id is invalid.",
        )
    normalized["process"] = process
    normalized["command_summary"] = command_summary
    normalized["lifecycle"] = lifecycle
    assert_artifact_retention_payload_safe(normalized)
    return normalized


def summarize_artifact_retention_scheduler_daemon_run_metadata(
    run_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    validated = validate_artifact_retention_scheduler_daemon_run_metadata(
        run_metadata
    )
    return {
        "scheduler_id": validated["scheduler_id"],
        "daemon_run_id": validated["daemon_run_id"],
        "daemon_process_lock_id": validated["daemon_process_lock_id"],
        "daemon_cli_execute_command_id": validated["daemon_cli_execute_command_id"],
        "run_status": validated["lifecycle"]["run_status"],
        "process_id": validated["process"]["process_id"],
        "host_id": validated["process"]["host_id"],
        "requested_at": validated["lifecycle"]["requested_at"],
        "run_record_persisted": validated["guardrails"]["run_record_persisted"],
        "lifecycle_event_persisted": validated["guardrails"][
            "lifecycle_event_persisted"
        ],
        "database_write_performed": validated["guardrails"][
            "database_write_performed"
        ],
    }


def run_metadata_summary_line(run_metadata: Mapping[str, Any]) -> str:
    summary = summarize_artifact_retention_scheduler_daemon_run_metadata(
        run_metadata
    )
    return (
        "ae_scheduler_daemon_run_metadata=pass "
        f"scheduler_id={summary['scheduler_id']} "
        f"run_status={summary['run_status']} "
        f"process_id={summary['process_id']} "
        f"persisted={int(summary['run_record_persisted'])}"
    )


def build_artifact_retention_scheduler_daemon_signal_shutdown_adapter(
    *,
    current_state: Mapping[str, Any],
    process_lock: Mapping[str, Any],
    run_metadata: Mapping[str, Any],
    signal_name: str = "SIGTERM",
    received_at: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    state = validate_artifact_retention_scheduler_daemon_runtime_state(current_state)
    lock = validate_artifact_retention_scheduler_daemon_process_lock(process_lock)
    run = validate_artifact_retention_scheduler_daemon_run_metadata(run_metadata)
    normalized_signal = _normalize_daemon_shutdown_signal_name(signal_name)
    normalized_received_at = _required_text(
        received_at or state["observed_at"],
        "received_at",
        error_code="ae.artifact_retention_scheduler_daemon_signal_shutdown_adapter_invalid",
    )
    _ensure_daemon_signal_shutdown_adapter_scope(
        current_state=state,
        process_lock=lock,
        run_metadata=run,
    )
    transition = build_artifact_retention_scheduler_daemon_shutdown_transition(
        current_state=state,
        requested_at=normalized_received_at,
        requested_by={
            "actor_type": "service",
            "actor_id": "nex-ae-api-daemon-signal-adapter",
            "request_id": run["daemon_run_id"],
        },
        reason=reason or f"received_{normalized_signal.lower()}",
    )
    signal = {
        "signal_name": normalized_signal,
        "received_at": normalized_received_at,
        "handler": "deferred_cli_signal_adapter",
    }
    adapter = {
        "daemon_signal_shutdown_adapter_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SIGNAL_SHUTDOWN_ADAPTER_SCHEMA_VERSION
        ),
        "daemon_signal_shutdown_adapter_id": _daemon_signal_shutdown_adapter_id(
            scheduler_id=state["scheduler_id"],
            daemon_run_id=run["daemon_run_id"],
            signal=signal,
            shutdown_transition=transition,
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": state["scheduler_id"],
        "daemon_run_id": run["daemon_run_id"],
        "daemon_process_lock_id": lock["daemon_process_lock_id"],
        "daemon_cli_execute_command_id": run["daemon_cli_execute_command_id"],
        "signal": signal,
        "process": deepcopy(lock["process"]),
        "run_lifecycle": deepcopy(run["lifecycle"]),
        "shutdown_transition": transition,
        "execution_plan": _daemon_signal_shutdown_adapter_execution_plan(
            shutdown_transition=transition
        ),
        "guardrails": _daemon_signal_shutdown_adapter_guardrails(),
        "metadata": _daemon_signal_shutdown_adapter_metadata(
            signal=signal,
            process=lock["process"],
            run_lifecycle=run["lifecycle"],
            shutdown_transition=transition,
        ),
    }
    return validate_artifact_retention_scheduler_daemon_signal_shutdown_adapter(
        adapter
    )


def validate_artifact_retention_scheduler_daemon_signal_shutdown_adapter(
    adapter: Mapping[str, Any],
) -> dict[str, Any]:
    error_code = "ae.artifact_retention_scheduler_daemon_signal_shutdown_adapter_invalid"
    if not isinstance(adapter, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon signal shutdown adapter "
                "must be an object."
            ),
        )
    normalized = dict(adapter)
    if set(normalized) != {
        "daemon_signal_shutdown_adapter_schema_version",
        "daemon_signal_shutdown_adapter_id",
        "service_id",
        "scheduler_id",
        "daemon_run_id",
        "daemon_process_lock_id",
        "daemon_cli_execute_command_id",
        "signal",
        "process",
        "run_lifecycle",
        "shutdown_transition",
        "execution_plan",
        "guardrails",
        "metadata",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon signal shutdown adapter "
                "keys are invalid."
            ),
        )
    if (
        normalized.get("daemon_signal_shutdown_adapter_schema_version")
        != AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SIGNAL_SHUTDOWN_ADAPTER_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_signal_shutdown_adapter_schema_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon signal shutdown adapter "
                "schema is invalid."
            ),
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon signal shutdown adapter "
                "service id is invalid."
            ),
        )
    scheduler_id = _required_text(
        normalized.get("scheduler_id"),
        "scheduler_id",
        error_code=error_code,
    )
    daemon_run_id = _required_text(
        normalized.get("daemon_run_id"),
        "daemon_run_id",
        error_code=error_code,
    )
    process_lock_id = _required_text(
        normalized.get("daemon_process_lock_id"),
        "daemon_process_lock_id",
        error_code=error_code,
    )
    command_id = _required_text(
        normalized.get("daemon_cli_execute_command_id"),
        "daemon_cli_execute_command_id",
        error_code=error_code,
    )
    signal = _validate_daemon_signal_shutdown_adapter_signal(
        normalized.get("signal")
    )
    process = _validate_daemon_process_lock_process(
        normalized.get("process"),
        error_code=error_code,
    )
    run_lifecycle = _validate_daemon_run_metadata_lifecycle(
        normalized.get("run_lifecycle"),
        error_code=error_code,
    )
    shutdown_transition = (
        validate_artifact_retention_scheduler_daemon_shutdown_transition(
            normalized.get("shutdown_transition")
        )
    )
    if shutdown_transition["scheduler_id"] != scheduler_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon signal shutdown adapter "
                "transition scope is invalid."
            ),
        )
    expected_execution_plan = _daemon_signal_shutdown_adapter_execution_plan(
        shutdown_transition=shutdown_transition
    )
    if normalized.get("execution_plan") != expected_execution_plan:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon signal shutdown adapter "
                "execution plan is invalid."
            ),
        )
    if normalized.get("guardrails") != _daemon_signal_shutdown_adapter_guardrails():
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon signal shutdown adapter "
                "guardrails are invalid."
            ),
        )
    expected_metadata = _daemon_signal_shutdown_adapter_metadata(
        signal=signal,
        process=process,
        run_lifecycle=run_lifecycle,
        shutdown_transition=shutdown_transition,
    )
    if normalized.get("metadata") != expected_metadata:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon signal shutdown adapter "
                "metadata is invalid."
            ),
        )
    expected_id = _daemon_signal_shutdown_adapter_id(
        scheduler_id=scheduler_id,
        daemon_run_id=daemon_run_id,
        signal=signal,
        shutdown_transition=shutdown_transition,
    )
    if normalized.get("daemon_signal_shutdown_adapter_id") != expected_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon signal shutdown adapter id "
                "is invalid."
            ),
        )
    normalized["daemon_run_id"] = daemon_run_id
    normalized["daemon_process_lock_id"] = process_lock_id
    normalized["daemon_cli_execute_command_id"] = command_id
    normalized["signal"] = signal
    normalized["process"] = process
    normalized["run_lifecycle"] = run_lifecycle
    normalized["shutdown_transition"] = shutdown_transition
    assert_artifact_retention_payload_safe(normalized)
    return normalized


def summarize_artifact_retention_scheduler_daemon_signal_shutdown_adapter(
    adapter: Mapping[str, Any],
) -> dict[str, Any]:
    validated = validate_artifact_retention_scheduler_daemon_signal_shutdown_adapter(
        adapter
    )
    transition_summary = (
        summarize_artifact_retention_scheduler_daemon_shutdown_transition(
            validated["shutdown_transition"]
        )
    )
    return {
        "scheduler_id": validated["scheduler_id"],
        "daemon_run_id": validated["daemon_run_id"],
        "signal_name": validated["signal"]["signal_name"],
        "received_at": validated["signal"]["received_at"],
        "process_id": validated["process"]["process_id"],
        "run_status": validated["run_lifecycle"]["run_status"],
        "decision_status": transition_summary["decision_status"],
        "decision_reason": transition_summary["decision_reason"],
        "to_lifecycle_status": transition_summary["to_lifecycle_status"],
        "shutdown_requested": transition_summary["shutdown_requested"],
        "signal_handler_installed": validated["guardrails"][
            "signal_handler_installed"
        ],
        "stop_signal_delivered": validated["guardrails"]["stop_signal_delivered"],
        "database_write_performed": validated["guardrails"][
            "database_write_performed"
        ],
    }


def signal_shutdown_adapter_summary_line(adapter: Mapping[str, Any]) -> str:
    summary = summarize_artifact_retention_scheduler_daemon_signal_shutdown_adapter(
        adapter
    )
    return (
        "ae_scheduler_daemon_signal_shutdown_adapter=pass "
        f"scheduler_id={summary['scheduler_id']} "
        f"signal={summary['signal_name']} "
        f"decision={summary['decision_status']} "
        f"to={summary['to_lifecycle_status']} "
        f"delivered={int(summary['stop_signal_delivered'])}"
    )


def run_artifact_retention_scheduler_daemon_cli_execution(
    *,
    artifact_store: Any,
    job_queue: Any | None,
    tenant_id: str,
    workspace_id: str,
    owner_user_id: str,
    lease_store: Any | None = None,
    history_store: Any | None = None,
    run_store: Any | None = None,
    scheduler_config: Mapping[str, Any] | None = None,
    profile: str = "test",
    enabled: bool = True,
    explicit_opt_in: bool = True,
    checked_at: str | None = None,
    interval_seconds: int | str | None = None,
    jitter_seconds: int | str | None = None,
    backoff_seconds: int | str | None = None,
    max_cycles: int | str = 1,
    run_worker: bool = False,
    output_format: str = "json",
    process_id: int | str | None = None,
    host_id: str = "localhost",
    stale_after_seconds: int | str = 600,
    retention_days: int | str | None = None,
    as_of: str | None = None,
    scan_limit: int | str | None = None,
    max_delete_count: int | str | None = None,
    trace_id: str | None = None,
    request_id: str | None = None,
    idempotency_key: str | None = None,
    worker_id: str | None = None,
    stop_requested: bool = False,
    stop_after_cycle: Callable[[int, Mapping[str, Any]], bool] | None = None,
    shutdown_signal_name: str | None = None,
    shutdown_received_at: str | None = None,
    clock: Callable[[], str] | None = None,
    daemon_heartbeat_emitter: Any | None = None,
) -> dict[str, Any]:
    config = (
        dict(scheduler_config)
        if scheduler_config is not None
        else build_artifact_retention_scheduler_config(job_queue=job_queue)
    )
    execute_command = build_artifact_retention_scheduler_daemon_cli_execute_command(
        scheduler_config=config,
        profile=profile,
        enabled=enabled,
        explicit_opt_in=explicit_opt_in,
        checked_at=checked_at,
        interval_seconds=interval_seconds,
        jitter_seconds=jitter_seconds,
        backoff_seconds=backoff_seconds,
        max_cycles=max_cycles,
        run_worker=run_worker,
        output_format=output_format,
    )
    command = execute_command["command"]
    process_lock = build_artifact_retention_scheduler_daemon_process_lock(
        execute_command=execute_command,
        process_id=process_id,
        host_id=host_id,
        requested_at=command["checked_at"],
        stale_after_seconds=stale_after_seconds,
    )
    started_run_metadata = build_artifact_retention_scheduler_daemon_run_metadata(
        execute_command=execute_command,
        process_lock=process_lock,
        run_status="RUNNING",
        requested_at=process_lock["timing"]["requested_at"],
        started_at=command["checked_at"],
    )
    shutdown_signal_adapter = None
    signal_stop_requested = False
    if shutdown_signal_name is not None:
        shutdown_signal_adapter = (
            build_artifact_retention_scheduler_daemon_signal_shutdown_adapter(
                current_state=execute_command["runtime_state"],
                process_lock=process_lock,
                run_metadata=started_run_metadata,
                signal_name=shutdown_signal_name,
                received_at=shutdown_received_at,
            )
        )
        signal_stop_requested = shutdown_signal_adapter["execution_plan"][
            "stop_signal_requested"
        ]
    live_daemon_config = build_artifact_retention_scheduler_daemon_config(
        scheduler_config=config,
        lease_store=lease_store,
        checked_at=command["checked_at"],
    )
    bounded_loop_result = run_artifact_retention_scheduler_daemon_bounded_loop(
        artifact_store=artifact_store,
        job_queue=job_queue,
        lease_store=lease_store,
        history_store=history_store,
        scheduler_config=config,
        runtime_config=execute_command["runtime_config"],
        daemon_config=live_daemon_config,
        daemon_instance_id=execute_command["runtime_state"]["daemon_instance_id"],
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        retention_days=retention_days,
        as_of=as_of,
        scan_limit=scan_limit,
        max_delete_count=max_delete_count,
        requested_at=command["checked_at"],
        trace_id=trace_id,
        request_id=request_id,
        idempotency_key=idempotency_key,
        max_cycles=command["max_cycles"],
        run_worker=command["run_worker"],
        worker_id=worker_id,
        stop_requested=(
            _required_bool(
                stop_requested,
                "stop_requested",
                error_code="ae.artifact_retention_scheduler_daemon_cli_execution_result_invalid",
            )
            or signal_stop_requested
        ),
        stop_after_cycle=stop_after_cycle,
        clock=clock,
        daemon_heartbeat_emitter=daemon_heartbeat_emitter,
    )
    completed_run_metadata = build_artifact_retention_scheduler_daemon_run_metadata(
        execute_command=execute_command,
        process_lock=process_lock,
        run_status=_daemon_cli_execution_completed_run_status(bounded_loop_result),
        requested_at=process_lock["timing"]["requested_at"],
        started_at=command["checked_at"],
        completed_at=bounded_loop_result["finished_at"],
    )
    run_record_persisted = run_store is not None
    lifecycle_event_persisted = run_store is not None
    execution_result = {
        "daemon_cli_execution_result_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_EXECUTION_RESULT_SCHEMA_VERSION
        ),
        "daemon_cli_execution_result_id": _daemon_cli_execution_result_id(
            execute_command=execute_command,
            process_lock=process_lock,
            started_run_metadata=started_run_metadata,
            completed_run_metadata=completed_run_metadata,
            bounded_loop_result=bounded_loop_result,
            shutdown_signal_adapter=shutdown_signal_adapter,
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": execute_command["scheduler_id"],
        "daemon_cli_execute_command_id": (
            execute_command["daemon_cli_execute_command_id"]
        ),
        "daemon_process_lock_id": process_lock["daemon_process_lock_id"],
        "started_daemon_run_id": started_run_metadata["daemon_run_id"],
        "completed_daemon_run_id": completed_run_metadata["daemon_run_id"],
        "result_status": bounded_loop_result["result_status"],
        "stop_reason": bounded_loop_result["stop_reason"],
        "execute_command": execute_command,
        "process_lock": process_lock,
        "started_run_metadata": started_run_metadata,
        "completed_run_metadata": completed_run_metadata,
        "bounded_loop_result": bounded_loop_result,
        "shutdown_signal_adapter": shutdown_signal_adapter,
        "execution_plan": _daemon_cli_execution_result_execution_plan(
            bounded_loop_result=bounded_loop_result,
            shutdown_signal_adapter=shutdown_signal_adapter,
            run_record_persisted=run_record_persisted,
            lifecycle_event_persisted=lifecycle_event_persisted,
        ),
        "guardrails": _daemon_cli_execution_result_guardrails(
            run_record_persisted=run_record_persisted,
            lifecycle_event_persisted=lifecycle_event_persisted,
        ),
        "metadata": _daemon_cli_execution_result_metadata(
            process_lock=process_lock,
            started_run_metadata=started_run_metadata,
            completed_run_metadata=completed_run_metadata,
            bounded_loop_result=bounded_loop_result,
            shutdown_signal_adapter=shutdown_signal_adapter,
            run_record_persisted=run_record_persisted,
            lifecycle_event_persisted=lifecycle_event_persisted,
        ),
    }
    validated_result = validate_artifact_retention_scheduler_daemon_cli_execution_result(
        execution_result
    )
    if run_store is not None:
        run_store.record_cli_execution(validated_result)
    return validated_result


def validate_artifact_retention_scheduler_daemon_cli_execution_result(
    result: Mapping[str, Any],
) -> dict[str, Any]:
    error_code = "ae.artifact_retention_scheduler_daemon_cli_execution_result_invalid"
    if not isinstance(result, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon CLI execution result must "
                "be an object."
            ),
        )
    normalized = dict(result)
    if set(normalized) != {
        "daemon_cli_execution_result_schema_version",
        "daemon_cli_execution_result_id",
        "service_id",
        "scheduler_id",
        "daemon_cli_execute_command_id",
        "daemon_process_lock_id",
        "started_daemon_run_id",
        "completed_daemon_run_id",
        "result_status",
        "stop_reason",
        "execute_command",
        "process_lock",
        "started_run_metadata",
        "completed_run_metadata",
        "bounded_loop_result",
        "shutdown_signal_adapter",
        "execution_plan",
        "guardrails",
        "metadata",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon CLI execution result keys "
                "are invalid."
            ),
        )
    if (
        normalized.get("daemon_cli_execution_result_schema_version")
        != AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_EXECUTION_RESULT_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_cli_execution_result_schema_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon CLI execution result schema "
                "is invalid."
            ),
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon CLI execution result service "
                "id is invalid."
            ),
        )
    scheduler_id = _required_text(
        normalized.get("scheduler_id"),
        "scheduler_id",
        error_code=error_code,
    )
    command_id = _required_text(
        normalized.get("daemon_cli_execute_command_id"),
        "daemon_cli_execute_command_id",
        error_code=error_code,
    )
    process_lock_id = _required_text(
        normalized.get("daemon_process_lock_id"),
        "daemon_process_lock_id",
        error_code=error_code,
    )
    started_run_id = _required_text(
        normalized.get("started_daemon_run_id"),
        "started_daemon_run_id",
        error_code=error_code,
    )
    completed_run_id = _required_text(
        normalized.get("completed_daemon_run_id"),
        "completed_daemon_run_id",
        error_code=error_code,
    )
    execute_command = validate_artifact_retention_scheduler_daemon_cli_execute_command(
        normalized.get("execute_command")
    )
    process_lock = validate_artifact_retention_scheduler_daemon_process_lock(
        normalized.get("process_lock")
    )
    started_run_metadata = validate_artifact_retention_scheduler_daemon_run_metadata(
        normalized.get("started_run_metadata")
    )
    completed_run_metadata = validate_artifact_retention_scheduler_daemon_run_metadata(
        normalized.get("completed_run_metadata")
    )
    bounded_loop_result = validate_artifact_retention_scheduler_daemon_bounded_loop_result(
        normalized.get("bounded_loop_result")
    )
    shutdown_signal_adapter = _validate_optional_daemon_signal_shutdown_adapter(
        normalized.get("shutdown_signal_adapter")
    )
    if normalized.get("result_status") != bounded_loop_result["result_status"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon CLI execution result status "
                "is invalid."
            ),
        )
    if normalized.get("stop_reason") != bounded_loop_result["stop_reason"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon CLI execution result stop "
                "reason is invalid."
            ),
        )
    _ensure_daemon_cli_execution_result_scope(
        scheduler_id=scheduler_id,
        command_id=command_id,
        process_lock_id=process_lock_id,
        started_run_id=started_run_id,
        completed_run_id=completed_run_id,
        execute_command=execute_command,
        process_lock=process_lock,
        started_run_metadata=started_run_metadata,
        completed_run_metadata=completed_run_metadata,
        bounded_loop_result=bounded_loop_result,
        shutdown_signal_adapter=shutdown_signal_adapter,
    )
    metadata_value = normalized.get("metadata")
    metadata = dict(metadata_value) if isinstance(metadata_value, Mapping) else {}
    run_record_persisted = _required_bool(
        metadata.get("run_record_persisted"),
        "run_record_persisted",
        error_code=error_code,
    )
    lifecycle_event_persisted = _required_bool(
        metadata.get("lifecycle_event_persisted"),
        "lifecycle_event_persisted",
        error_code=error_code,
    )
    expected_execution_plan = _daemon_cli_execution_result_execution_plan(
        bounded_loop_result=bounded_loop_result,
        shutdown_signal_adapter=shutdown_signal_adapter,
        run_record_persisted=run_record_persisted,
        lifecycle_event_persisted=lifecycle_event_persisted,
    )
    if normalized.get("execution_plan") != expected_execution_plan:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon CLI execution result "
                "execution plan is invalid."
            ),
        )
    if normalized.get("guardrails") != _daemon_cli_execution_result_guardrails(
        run_record_persisted=run_record_persisted,
        lifecycle_event_persisted=lifecycle_event_persisted,
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon CLI execution result "
                "guardrails are invalid."
            ),
        )
    expected_metadata = _daemon_cli_execution_result_metadata(
        process_lock=process_lock,
        started_run_metadata=started_run_metadata,
        completed_run_metadata=completed_run_metadata,
        bounded_loop_result=bounded_loop_result,
        shutdown_signal_adapter=shutdown_signal_adapter,
        run_record_persisted=run_record_persisted,
        lifecycle_event_persisted=lifecycle_event_persisted,
    )
    if normalized.get("metadata") != expected_metadata:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon CLI execution result "
                "metadata is invalid."
            ),
        )
    expected_id = _daemon_cli_execution_result_id(
        execute_command=execute_command,
        process_lock=process_lock,
        started_run_metadata=started_run_metadata,
        completed_run_metadata=completed_run_metadata,
        bounded_loop_result=bounded_loop_result,
        shutdown_signal_adapter=shutdown_signal_adapter,
    )
    if normalized.get("daemon_cli_execution_result_id") != expected_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon CLI execution result id is "
                "invalid."
            ),
        )
    normalized["execute_command"] = execute_command
    normalized["process_lock"] = process_lock
    normalized["started_run_metadata"] = started_run_metadata
    normalized["completed_run_metadata"] = completed_run_metadata
    normalized["bounded_loop_result"] = bounded_loop_result
    normalized["shutdown_signal_adapter"] = shutdown_signal_adapter
    assert_artifact_retention_payload_safe(normalized)
    return normalized


def summarize_artifact_retention_scheduler_daemon_cli_execution_result(
    result: Mapping[str, Any],
) -> dict[str, Any]:
    validated = validate_artifact_retention_scheduler_daemon_cli_execution_result(
        result
    )
    bounded_summary = summarize_artifact_retention_scheduler_daemon_bounded_loop_result(
        validated["bounded_loop_result"]
    )
    return {
        "scheduler_id": validated["scheduler_id"],
        "daemon_cli_execute_command_id": validated[
            "daemon_cli_execute_command_id"
        ],
        "daemon_process_lock_id": validated["daemon_process_lock_id"],
        "started_daemon_run_id": validated["started_daemon_run_id"],
        "completed_daemon_run_id": validated["completed_daemon_run_id"],
        "result_status": validated["result_status"],
        "stop_reason": validated["stop_reason"],
        "max_cycles": bounded_summary["max_cycles"],
        "cycle_count": bounded_summary["cycle_count"],
        "process_id": validated["process_lock"]["process"]["process_id"],
        "host_id": validated["process_lock"]["process"]["host_id"],
        "completed_run_status": validated["completed_run_metadata"]["lifecycle"][
            "run_status"
        ],
        "bounded_loop_started": bounded_summary["bounded_loop_started"],
        "job_enqueued": bounded_summary["job_enqueued"],
        "worker_executed": bounded_summary["worker_executed"],
        "shutdown_signal_adapter_invoked": validated["metadata"][
            "shutdown_signal_adapter_invoked"
        ],
        "run_record_persisted": validated["guardrails"]["run_record_persisted"],
    }


def execution_result_summary_line(result: Mapping[str, Any]) -> str:
    summary = summarize_artifact_retention_scheduler_daemon_cli_execution_result(
        result
    )
    return (
        "ae_scheduler_daemon_cli_execution=pass "
        f"scheduler_id={summary['scheduler_id']} "
        f"result={summary['result_status']} "
        f"stop_reason={summary['stop_reason']} "
        f"max_cycles={summary['max_cycles']} "
        f"cycles={summary['cycle_count']} "
        f"job_enqueued={int(summary['job_enqueued'])} "
        f"persisted={int(summary['run_record_persisted'])}"
    )


class SqlAlchemyArtifactRetentionSchedulerDaemonRunStore:
    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

    def ensure_schema(self) -> None:
        try:
            with self._session_factory() as session:
                _ensure_daemon_run_store_schema(session)
                session.commit()
        except SQLAlchemyError as exc:
            raise _daemon_run_store_unavailable() from exc

    def ensure_available(self) -> None:
        try:
            with self._session_factory() as session:
                session.execute(
                    text(
                        "SELECT 1 FROM "
                        "ae_artifact_retention_scheduler_daemon_runs LIMIT 1"
                    )
                )
        except SQLAlchemyError as exc:
            raise _daemon_run_store_unavailable() from exc

    def record_cli_execution(
        self,
        result: Mapping[str, Any],
    ) -> dict[str, Any]:
        record = build_artifact_retention_scheduler_daemon_run_record(result)
        events = build_artifact_retention_scheduler_daemon_lifecycle_events(
            run_record=record,
            execution_result=result,
        )
        try:
            with self._session_factory() as session:
                _ensure_daemon_run_store_schema(session)
                dialect_name = _daemon_store_dialect_name(session)
                session.execute(
                    text(_daemon_run_record_upsert_sql(dialect_name)),
                    _daemon_run_record_params(record),
                )
                for event in events:
                    session.execute(
                        text(_daemon_lifecycle_event_upsert_sql(dialect_name)),
                        _daemon_lifecycle_event_params(event),
                    )
                session.commit()
            return {
                "run_record": record,
                "lifecycle_events": events,
            }
        except SQLAlchemyError as exc:
            raise _daemon_run_store_unavailable() from exc

    def get_run_record(self, daemon_run_record_id: str) -> dict[str, Any] | None:
        normalized_id = _required_text(
            daemon_run_record_id,
            "daemon_run_record_id",
            error_code="ae.artifact_retention_scheduler_daemon_run_record_invalid",
        )
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(
                        text(
                            _daemon_run_record_select_sql(
                                "daemon_run_record_id = :daemon_run_record_id"
                            )
                        ),
                        {"daemon_run_record_id": normalized_id},
                    )
                    .mappings()
                    .first()
                )
            return _daemon_run_record_from_row(row) if row is not None else None
        except SQLAlchemyError as exc:
            raise _daemon_run_store_unavailable() from exc

    def get_run_record_by_execution_result_id(
        self,
        daemon_cli_execution_result_id: str,
    ) -> dict[str, Any] | None:
        normalized_id = _required_text(
            daemon_cli_execution_result_id,
            "daemon_cli_execution_result_id",
            error_code="ae.artifact_retention_scheduler_daemon_run_record_invalid",
        )
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(
                        text(
                            _daemon_run_record_select_sql(
                                "daemon_cli_execution_result_id = "
                                ":daemon_cli_execution_result_id"
                            )
                        ),
                        {"daemon_cli_execution_result_id": normalized_id},
                    )
                    .mappings()
                    .first()
                )
            return _daemon_run_record_from_row(row) if row is not None else None
        except SQLAlchemyError as exc:
            raise _daemon_run_store_unavailable() from exc

    def list_run_records(
        self,
        *,
        scheduler_id: str | None = None,
        result_status: str | None = None,
        limit: int | str | None = None,
    ) -> list[dict[str, Any]]:
        normalized_scheduler_id = optional_text(scheduler_id)
        normalized_result_status = _optional_daemon_result_status(
            result_status,
            error_code="ae.artifact_retention_scheduler_daemon_run_collection_invalid",
        )
        normalized_limit = normalize_artifact_retention_scheduler_daemon_run_limit(
            limit
        )
        where_clauses = ["service_id = 'nex-ae-api'"]
        params: dict[str, Any] = {"limit": normalized_limit}
        if normalized_scheduler_id is not None:
            where_clauses.append("scheduler_id = :scheduler_id")
            params["scheduler_id"] = normalized_scheduler_id
        if normalized_result_status is not None:
            where_clauses.append("result_status = :result_status")
            params["result_status"] = normalized_result_status
        try:
            with self._session_factory() as session:
                rows = (
                    session.execute(
                        text(
                            _daemon_run_record_select_sql(
                                " AND ".join(where_clauses)
                            )
                            + """
                            ORDER BY completed_at DESC,
                                     created_at DESC,
                                     daemon_run_record_id ASC
                            LIMIT :limit
                            """
                        ),
                        params,
                    )
                    .mappings()
                    .all()
                )
            return [_daemon_run_record_from_row(row) for row in rows]
        except SQLAlchemyError as exc:
            raise _daemon_run_store_unavailable() from exc

    def list_lifecycle_events(
        self,
        daemon_run_record_id: str,
    ) -> list[dict[str, Any]]:
        normalized_id = _required_text(
            daemon_run_record_id,
            "daemon_run_record_id",
            error_code=(
                "ae.artifact_retention_scheduler_daemon_lifecycle_event_invalid"
            ),
        )
        try:
            with self._session_factory() as session:
                rows = (
                    session.execute(
                        text(
                            _daemon_lifecycle_event_select_sql(
                                "daemon_run_record_id = :daemon_run_record_id"
                            )
                            + """
                            ORDER BY occurred_at ASC, event_type ASC
                            """
                        ),
                        {"daemon_run_record_id": normalized_id},
                    )
                    .mappings()
                    .all()
                )
            return [_daemon_lifecycle_event_from_row(row) for row in rows]
        except SQLAlchemyError as exc:
            raise _daemon_run_store_unavailable() from exc

    def delete_run_record(self, daemon_run_record_id: str) -> dict[str, int]:
        normalized_id = _required_text(
            daemon_run_record_id,
            "daemon_run_record_id",
            error_code="ae.artifact_retention_scheduler_daemon_run_record_invalid",
        )
        deleted = {"daemon_lifecycle_events": 0, "daemon_run_records": 0}
        try:
            with self._session_factory() as session:
                event_result = session.execute(
                    text(
                        """
                        DELETE FROM
                            ae_artifact_retention_scheduler_daemon_lifecycle_events
                        WHERE daemon_run_record_id = :daemon_run_record_id
                        """
                    ),
                    {"daemon_run_record_id": normalized_id},
                )
                run_result = session.execute(
                    text(
                        """
                        DELETE FROM ae_artifact_retention_scheduler_daemon_runs
                        WHERE daemon_run_record_id = :daemon_run_record_id
                        """
                    ),
                    {"daemon_run_record_id": normalized_id},
                )
                session.commit()
            deleted["daemon_lifecycle_events"] = int(event_result.rowcount or 0)
            deleted["daemon_run_records"] = int(run_result.rowcount or 0)
            return deleted
        except SQLAlchemyError as exc:
            raise _daemon_run_store_unavailable() from exc


class SqlAlchemyArtifactRetentionSchedulerDaemonSupervisorStore:
    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

    def ensure_schema(self) -> None:
        try:
            with self._session_factory() as session:
                _ensure_daemon_supervisor_store_schema(session)
                session.commit()
        except SQLAlchemyError as exc:
            raise _daemon_supervisor_store_unavailable() from exc

    def ensure_available(self) -> None:
        try:
            with self._session_factory() as session:
                session.execute(
                    text(
                        "SELECT 1 FROM "
                        "ae_artifact_retention_scheduler_daemon_supervisor_results "
                        "LIMIT 1"
                    )
                )
        except SQLAlchemyError as exc:
            raise _daemon_supervisor_store_unavailable() from exc

    def record_supervisor_result(
        self,
        supervisor_result: Mapping[str, Any],
    ) -> dict[str, Any]:
        record = build_artifact_retention_scheduler_daemon_supervisor_record(
            supervisor_result
        )
        event = build_artifact_retention_scheduler_daemon_supervisor_event(
            supervisor_record=record,
            supervisor_result=supervisor_result,
        )
        try:
            with self._session_factory() as session:
                _ensure_daemon_supervisor_store_schema(session)
                dialect_name = _daemon_store_dialect_name(session)
                session.execute(
                    text(_daemon_supervisor_record_upsert_sql(dialect_name)),
                    _daemon_supervisor_record_params(record),
                )
                session.execute(
                    text(_daemon_supervisor_event_upsert_sql(dialect_name)),
                    _daemon_supervisor_event_params(event),
                )
                session.commit()
            return {
                "supervisor_record": record,
                "supervisor_event": event,
            }
        except SQLAlchemyError as exc:
            raise _daemon_supervisor_store_unavailable() from exc

    def get_supervisor_record(
        self,
        daemon_supervisor_record_id: str,
    ) -> dict[str, Any] | None:
        normalized_id = _required_text(
            daemon_supervisor_record_id,
            "daemon_supervisor_record_id",
            error_code=(
                "ae.artifact_retention_scheduler_daemon_supervisor_record_invalid"
            ),
        )
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(
                        text(
                            _daemon_supervisor_record_select_sql(
                                "daemon_supervisor_record_id = "
                                ":daemon_supervisor_record_id"
                            )
                        ),
                        {"daemon_supervisor_record_id": normalized_id},
                    )
                    .mappings()
                    .first()
                )
            return (
                _daemon_supervisor_record_from_row(row)
                if row is not None
                else None
            )
        except SQLAlchemyError as exc:
            raise _daemon_supervisor_store_unavailable() from exc

    def get_supervisor_record_by_result_id(
        self,
        daemon_supervisor_result_id: str,
    ) -> dict[str, Any] | None:
        normalized_id = _required_text(
            daemon_supervisor_result_id,
            "daemon_supervisor_result_id",
            error_code=(
                "ae.artifact_retention_scheduler_daemon_supervisor_record_invalid"
            ),
        )
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(
                        text(
                            _daemon_supervisor_record_select_sql(
                                "daemon_supervisor_result_id = "
                                ":daemon_supervisor_result_id"
                            )
                        ),
                        {"daemon_supervisor_result_id": normalized_id},
                    )
                    .mappings()
                    .first()
                )
            return (
                _daemon_supervisor_record_from_row(row)
                if row is not None
                else None
            )
        except SQLAlchemyError as exc:
            raise _daemon_supervisor_store_unavailable() from exc

    def list_supervisor_records(
        self,
        *,
        scheduler_id: str | None = None,
        action: str | None = None,
        result_status: str | None = None,
        limit: int | str | None = None,
    ) -> list[dict[str, Any]]:
        normalized_scheduler_id = optional_text(scheduler_id)
        normalized_action = _optional_daemon_supervisor_action(
            action,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_supervisor_collection_invalid"
            ),
        )
        normalized_result_status = _optional_daemon_supervisor_result_status(
            result_status,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_supervisor_collection_invalid"
            ),
        )
        normalized_limit = normalize_artifact_retention_scheduler_daemon_supervisor_limit(
            limit
        )
        where_clauses = ["service_id = 'nex-ae-api'"]
        params: dict[str, Any] = {"limit": normalized_limit}
        if normalized_scheduler_id is not None:
            where_clauses.append("scheduler_id = :scheduler_id")
            params["scheduler_id"] = normalized_scheduler_id
        if normalized_action is not None:
            where_clauses.append("action = :action")
            params["action"] = normalized_action
        if normalized_result_status is not None:
            where_clauses.append("result_status = :result_status")
            params["result_status"] = normalized_result_status
        try:
            with self._session_factory() as session:
                rows = (
                    session.execute(
                        text(
                            _daemon_supervisor_record_select_sql(
                                " AND ".join(where_clauses)
                            )
                            + """
                            ORDER BY observed_at DESC,
                                     created_at DESC,
                                     daemon_supervisor_record_id ASC
                            LIMIT :limit
                            """
                        ),
                        params,
                    )
                    .mappings()
                    .all()
                )
            return [_daemon_supervisor_record_from_row(row) for row in rows]
        except SQLAlchemyError as exc:
            raise _daemon_supervisor_store_unavailable() from exc

    def list_supervisor_events(
        self,
        daemon_supervisor_record_id: str,
    ) -> list[dict[str, Any]]:
        normalized_id = _required_text(
            daemon_supervisor_record_id,
            "daemon_supervisor_record_id",
            error_code=(
                "ae.artifact_retention_scheduler_daemon_supervisor_event_invalid"
            ),
        )
        try:
            with self._session_factory() as session:
                rows = (
                    session.execute(
                        text(
                            _daemon_supervisor_event_select_sql(
                                "daemon_supervisor_record_id = "
                                ":daemon_supervisor_record_id"
                            )
                            + """
                            ORDER BY occurred_at ASC,
                                     daemon_supervisor_event_id ASC
                            """
                        ),
                        {"daemon_supervisor_record_id": normalized_id},
                    )
                    .mappings()
                    .all()
                )
            return [_daemon_supervisor_event_from_row(row) for row in rows]
        except SQLAlchemyError as exc:
            raise _daemon_supervisor_store_unavailable() from exc

    def delete_supervisor_record(
        self,
        daemon_supervisor_record_id: str,
    ) -> dict[str, int]:
        normalized_id = _required_text(
            daemon_supervisor_record_id,
            "daemon_supervisor_record_id",
            error_code=(
                "ae.artifact_retention_scheduler_daemon_supervisor_record_invalid"
            ),
        )
        deleted = {"daemon_supervisor_events": 0, "daemon_supervisor_records": 0}
        try:
            with self._session_factory() as session:
                event_result = session.execute(
                    text(
                        """
                        DELETE FROM
                            ae_artifact_retention_scheduler_daemon_supervisor_events
                        WHERE daemon_supervisor_record_id =
                              :daemon_supervisor_record_id
                        """
                    ),
                    {"daemon_supervisor_record_id": normalized_id},
                )
                record_result = session.execute(
                    text(
                        """
                        DELETE FROM
                            ae_artifact_retention_scheduler_daemon_supervisor_results
                        WHERE daemon_supervisor_record_id =
                              :daemon_supervisor_record_id
                        """
                    ),
                    {"daemon_supervisor_record_id": normalized_id},
                )
                session.commit()
            deleted["daemon_supervisor_events"] = int(event_result.rowcount or 0)
            deleted["daemon_supervisor_records"] = int(record_result.rowcount or 0)
            return deleted
        except SQLAlchemyError as exc:
            raise _daemon_supervisor_store_unavailable() from exc


class SqlAlchemyArtifactRetentionSchedulerDaemonSupervisedProcessStore:
    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

    def ensure_schema(self) -> None:
        try:
            with self._session_factory() as session:
                _ensure_daemon_supervised_process_store_schema(session)
                session.commit()
        except SQLAlchemyError as exc:
            raise _daemon_supervised_process_store_unavailable() from exc

    def ensure_available(self) -> None:
        try:
            with self._session_factory() as session:
                session.execute(
                    text(
                        "SELECT 1 FROM "
                        "ae_artifact_retention_scheduler_daemon_process_snapshots "
                        "LIMIT 1"
                    )
                )
        except SQLAlchemyError as exc:
            raise _daemon_supervised_process_store_unavailable() from exc

    def record_supervised_process_snapshot(
        self,
        supervised_process_snapshot: Mapping[str, Any],
    ) -> dict[str, Any]:
        record = build_artifact_retention_scheduler_daemon_supervised_process_record(
            supervised_process_snapshot
        )
        event = build_artifact_retention_scheduler_daemon_supervised_process_event(
            supervised_process_record=record,
            supervised_process_snapshot=supervised_process_snapshot,
        )
        try:
            with self._session_factory() as session:
                _ensure_daemon_supervised_process_store_schema(session)
                dialect_name = _daemon_store_dialect_name(session)
                session.execute(
                    text(_daemon_supervised_process_record_upsert_sql(dialect_name)),
                    _daemon_supervised_process_record_params(record),
                )
                session.execute(
                    text(_daemon_supervised_process_event_upsert_sql(dialect_name)),
                    _daemon_supervised_process_event_params(event),
                )
                session.commit()
            return {
                "supervised_process_record": record,
                "supervised_process_event": event,
            }
        except SQLAlchemyError as exc:
            raise _daemon_supervised_process_store_unavailable() from exc

    def get_supervised_process_record(
        self,
        daemon_supervised_process_record_id: str,
    ) -> dict[str, Any] | None:
        normalized_id = _required_text(
            daemon_supervised_process_record_id,
            "daemon_supervised_process_record_id",
            error_code=(
                "ae.artifact_retention_scheduler_daemon_supervised_process_record_invalid"
            ),
        )
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(
                        text(
                            _daemon_supervised_process_record_select_sql(
                                "daemon_supervised_process_record_id = "
                                ":daemon_supervised_process_record_id"
                            )
                        ),
                        {
                            "daemon_supervised_process_record_id": (
                                normalized_id
                            )
                        },
                    )
                    .mappings()
                    .first()
                )
            return (
                _daemon_supervised_process_record_from_row(row)
                if row is not None
                else None
            )
        except SQLAlchemyError as exc:
            raise _daemon_supervised_process_store_unavailable() from exc

    def get_supervised_process_record_by_snapshot_id(
        self,
        daemon_supervised_process_id: str,
    ) -> dict[str, Any] | None:
        normalized_id = _required_text(
            daemon_supervised_process_id,
            "daemon_supervised_process_id",
            error_code=(
                "ae.artifact_retention_scheduler_daemon_supervised_process_record_invalid"
            ),
        )
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(
                        text(
                            _daemon_supervised_process_record_select_sql(
                                "daemon_supervised_process_id = "
                                ":daemon_supervised_process_id"
                            )
                        ),
                        {"daemon_supervised_process_id": normalized_id},
                    )
                    .mappings()
                    .first()
                )
            return (
                _daemon_supervised_process_record_from_row(row)
                if row is not None
                else None
            )
        except SQLAlchemyError as exc:
            raise _daemon_supervised_process_store_unavailable() from exc

    def list_supervised_process_records(
        self,
        *,
        scheduler_id: str | None = None,
        action: str | None = None,
        process_status: str | None = None,
        limit: int | str | None = None,
    ) -> list[dict[str, Any]]:
        normalized_scheduler_id = optional_text(scheduler_id)
        normalized_action = _optional_daemon_supervisor_action(
            action,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_supervised_process_collection_invalid"
            ),
        )
        normalized_process_status = _optional_daemon_supervised_process_status(
            process_status,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_supervised_process_collection_invalid"
            ),
        )
        normalized_limit = (
            normalize_artifact_retention_scheduler_daemon_supervised_process_limit(
                limit
            )
        )
        where_clauses = ["service_id = 'nex-ae-api'"]
        params: dict[str, Any] = {"limit": normalized_limit}
        if normalized_scheduler_id is not None:
            where_clauses.append("scheduler_id = :scheduler_id")
            params["scheduler_id"] = normalized_scheduler_id
        if normalized_action is not None:
            where_clauses.append("action = :action")
            params["action"] = normalized_action
        if normalized_process_status is not None:
            where_clauses.append("process_status = :process_status")
            params["process_status"] = normalized_process_status
        try:
            with self._session_factory() as session:
                rows = (
                    session.execute(
                        text(
                            _daemon_supervised_process_record_select_sql(
                                " AND ".join(where_clauses)
                            )
                            + """
                            ORDER BY observed_at DESC,
                                     created_at DESC,
                                     daemon_supervised_process_record_id ASC
                            LIMIT :limit
                            """
                        ),
                        params,
                    )
                    .mappings()
                    .all()
                )
            return [_daemon_supervised_process_record_from_row(row) for row in rows]
        except SQLAlchemyError as exc:
            raise _daemon_supervised_process_store_unavailable() from exc

    def list_supervised_process_events(
        self,
        daemon_supervised_process_record_id: str,
    ) -> list[dict[str, Any]]:
        normalized_id = _required_text(
            daemon_supervised_process_record_id,
            "daemon_supervised_process_record_id",
            error_code=(
                "ae.artifact_retention_scheduler_daemon_supervised_process_event_invalid"
            ),
        )
        try:
            with self._session_factory() as session:
                rows = (
                    session.execute(
                        text(
                            _daemon_supervised_process_event_select_sql(
                                "daemon_supervised_process_record_id = "
                                ":daemon_supervised_process_record_id"
                            )
                            + """
                            ORDER BY occurred_at ASC,
                                     daemon_supervised_process_event_id ASC
                            """
                        ),
                        {
                            "daemon_supervised_process_record_id": (
                                normalized_id
                            )
                        },
                    )
                    .mappings()
                    .all()
                )
            return [_daemon_supervised_process_event_from_row(row) for row in rows]
        except SQLAlchemyError as exc:
            raise _daemon_supervised_process_store_unavailable() from exc

    def delete_supervised_process_record(
        self,
        daemon_supervised_process_record_id: str,
    ) -> dict[str, int]:
        normalized_id = _required_text(
            daemon_supervised_process_record_id,
            "daemon_supervised_process_record_id",
            error_code=(
                "ae.artifact_retention_scheduler_daemon_supervised_process_record_invalid"
            ),
        )
        deleted = {
            "daemon_supervised_process_events": 0,
            "daemon_supervised_process_records": 0,
        }
        try:
            with self._session_factory() as session:
                event_result = session.execute(
                    text(
                        """
                        DELETE FROM
                            ae_artifact_retention_scheduler_daemon_process_events
                        WHERE daemon_supervised_process_record_id =
                              :daemon_supervised_process_record_id
                        """
                    ),
                    {
                        "daemon_supervised_process_record_id": normalized_id,
                    },
                )
                record_result = session.execute(
                    text(
                        """
                        DELETE FROM
                            ae_artifact_retention_scheduler_daemon_process_snapshots
                        WHERE daemon_supervised_process_record_id =
                              :daemon_supervised_process_record_id
                        """
                    ),
                    {
                        "daemon_supervised_process_record_id": normalized_id,
                    },
                )
                session.commit()
            deleted["daemon_supervised_process_events"] = int(
                event_result.rowcount or 0
            )
            deleted["daemon_supervised_process_records"] = int(
                record_result.rowcount or 0
            )
            return deleted
        except SQLAlchemyError as exc:
            raise _daemon_supervised_process_store_unavailable() from exc


class SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionStore:
    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

    def ensure_schema(self) -> None:
        try:
            with self._session_factory() as session:
                _ensure_operator_control_execution_store_schema(session)
                session.commit()
        except SQLAlchemyError as exc:
            raise _operator_control_execution_store_unavailable() from exc

    def ensure_available(self) -> None:
        try:
            with self._session_factory() as session:
                session.execute(
                    text(
                        "SELECT 1 FROM "
                        "ae_daemon_operator_control_execution_states "
                        "LIMIT 1"
                    )
                )
        except SQLAlchemyError as exc:
            raise _operator_control_execution_store_unavailable() from exc

    def record_execution_state(
        self,
        execution_state: Mapping[str, Any],
    ) -> dict[str, Any]:
        state = (
            validate_artifact_retention_scheduler_daemon_operator_control_execution_state(
                execution_state
            )
        )
        try:
            with self._session_factory() as session:
                _ensure_operator_control_execution_store_schema(session)
                dialect_name = _daemon_store_dialect_name(session)
                session.execute(
                    text(_operator_control_execution_state_upsert_sql(dialect_name)),
                    _operator_control_execution_state_params(state),
                )
                session.commit()
            return state
        except SQLAlchemyError as exc:
            raise _operator_control_execution_store_unavailable() from exc

    def record_execution_state_transition(
        self,
        transition: Mapping[str, Any],
    ) -> dict[str, Any]:
        normalized = validate_artifact_retention_scheduler_daemon_operator_control_execution_state_transition(
            transition
        )
        try:
            with self._session_factory() as session:
                _ensure_operator_control_execution_store_schema(session)
                dialect_name = _daemon_store_dialect_name(session)
                session.execute(
                    text(
                        _operator_control_execution_state_transition_upsert_sql(
                            dialect_name
                        )
                    ),
                    _operator_control_execution_state_transition_params(
                        normalized
                    ),
                )
                session.commit()
            return normalized
        except SQLAlchemyError as exc:
            raise _operator_control_execution_store_unavailable() from exc

    def get_execution_state(
        self,
        operator_control_execution_state_id: str,
    ) -> dict[str, Any] | None:
        normalized_id = _required_text(
            operator_control_execution_state_id,
            "operator_control_execution_state_id",
            error_code=(
                "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_invalid"
            ),
        )
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(
                        text(
                            _operator_control_execution_state_select_sql(
                                "operator_control_execution_state_id = "
                                ":operator_control_execution_state_id"
                            )
                        ),
                        {
                            "operator_control_execution_state_id": normalized_id,
                        },
                    )
                    .mappings()
                    .first()
                )
            return (
                _operator_control_execution_state_from_row(row)
                if row is not None
                else None
            )
        except SQLAlchemyError as exc:
            raise _operator_control_execution_store_unavailable() from exc

    def get_execution_state_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        normalized_key = _required_text(
            idempotency_key,
            "idempotency_key",
            error_code=(
                "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_invalid"
            ),
        )
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(
                        text(
                            _operator_control_execution_state_select_sql(
                                "idempotency_key = :idempotency_key"
                            )
                            + """
                            ORDER BY observed_at DESC,
                                     created_at DESC,
                                     operator_control_execution_state_id ASC
                            LIMIT 1
                            """
                        ),
                        {"idempotency_key": normalized_key},
                    )
                    .mappings()
                    .first()
                )
            return (
                _operator_control_execution_state_from_row(row)
                if row is not None
                else None
            )
        except SQLAlchemyError as exc:
            raise _operator_control_execution_store_unavailable() from exc

    def list_execution_states(
        self,
        *,
        scheduler_id: str | None = None,
        action: str | None = None,
        execution_status: str | None = None,
        idempotency_status: str | None = None,
        limit: int | str | None = None,
    ) -> list[dict[str, Any]]:
        normalized_scheduler_id = optional_text(scheduler_id)
        normalized_action = _optional_operator_control_execution_action(
            action,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_operator_control_execution_collection_invalid"
            ),
        )
        normalized_execution_status = (
            _optional_operator_control_execution_state_status(
                execution_status,
                error_code=(
                    "ae.artifact_retention_scheduler_daemon_operator_control_execution_collection_invalid"
                ),
            )
        )
        normalized_idempotency_status = (
            _optional_operator_control_execution_idempotency_status(
                idempotency_status,
                error_code=(
                    "ae.artifact_retention_scheduler_daemon_operator_control_execution_collection_invalid"
                ),
            )
        )
        normalized_limit = (
            normalize_artifact_retention_scheduler_daemon_operator_control_execution_limit(
                limit
            )
        )
        where_clauses = ["service_id = 'nex-ae-api'"]
        params: dict[str, Any] = {"limit": normalized_limit}
        if normalized_scheduler_id is not None:
            where_clauses.append("scheduler_id = :scheduler_id")
            params["scheduler_id"] = normalized_scheduler_id
        if normalized_action is not None:
            where_clauses.append("action = :action")
            params["action"] = normalized_action
        if normalized_execution_status is not None:
            where_clauses.append("execution_status = :execution_status")
            params["execution_status"] = normalized_execution_status
        if normalized_idempotency_status is not None:
            where_clauses.append("idempotency_status = :idempotency_status")
            params["idempotency_status"] = normalized_idempotency_status
        try:
            with self._session_factory() as session:
                rows = (
                    session.execute(
                        text(
                            _operator_control_execution_state_select_sql(
                                " AND ".join(where_clauses)
                            )
                            + """
                            ORDER BY observed_at DESC,
                                     created_at DESC,
                                     operator_control_execution_state_id ASC
                            LIMIT :limit
                            """
                        ),
                        params,
                    )
                    .mappings()
                    .all()
                )
            return [_operator_control_execution_state_from_row(row) for row in rows]
        except SQLAlchemyError as exc:
            raise _operator_control_execution_store_unavailable() from exc

    def list_execution_state_transitions(
        self,
        operator_control_execution_state_id: str,
    ) -> list[dict[str, Any]]:
        normalized_id = _required_text(
            operator_control_execution_state_id,
            "operator_control_execution_state_id",
            error_code=(
                "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_transition_invalid"
            ),
        )
        try:
            with self._session_factory() as session:
                rows = (
                    session.execute(
                        text(
                            _operator_control_execution_state_transition_select_sql(
                                "operator_control_execution_state_id = "
                                ":operator_control_execution_state_id"
                            )
                            + """
                            ORDER BY transitioned_at ASC,
                                     operator_control_execution_state_transition_id ASC
                            """
                        ),
                        {"operator_control_execution_state_id": normalized_id},
                    )
                    .mappings()
                    .all()
                )
            return [
                _operator_control_execution_state_transition_from_row(row)
                for row in rows
            ]
        except SQLAlchemyError as exc:
            raise _operator_control_execution_store_unavailable() from exc

    def delete_execution_state(
        self,
        operator_control_execution_state_id: str,
    ) -> dict[str, int]:
        normalized_id = _required_text(
            operator_control_execution_state_id,
            "operator_control_execution_state_id",
            error_code=(
                "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_invalid"
            ),
        )
        deleted = {"execution_state_transitions": 0, "execution_states": 0}
        try:
            with self._session_factory() as session:
                transition_result = session.execute(
                    text(
                        """
                        DELETE FROM
                            ae_daemon_operator_control_execution_transitions
                        WHERE operator_control_execution_state_id =
                              :operator_control_execution_state_id
                        """
                    ),
                    {"operator_control_execution_state_id": normalized_id},
                )
                state_result = session.execute(
                    text(
                        """
                        DELETE FROM
                            ae_daemon_operator_control_execution_states
                        WHERE operator_control_execution_state_id =
                              :operator_control_execution_state_id
                        """
                    ),
                    {"operator_control_execution_state_id": normalized_id},
                )
                session.commit()
            deleted["execution_state_transitions"] = int(
                transition_result.rowcount or 0
            )
            deleted["execution_states"] = int(state_result.rowcount or 0)
            return deleted
        except SQLAlchemyError as exc:
            raise _operator_control_execution_store_unavailable() from exc


def build_artifact_retention_scheduler_daemon_supervised_process_record(
    supervised_process_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    snapshot = validate_artifact_retention_scheduler_daemon_supervised_process_snapshot(
        supervised_process_snapshot
    )
    summary = summarize_artifact_retention_scheduler_daemon_supervised_process_snapshot(
        snapshot
    )
    lifecycle = snapshot["lifecycle"]
    process = snapshot["process"]
    metadata = snapshot["metadata"]
    record = {
        "daemon_supervised_process_record_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_RECORD_SCHEMA_VERSION
        ),
        "daemon_supervised_process_record_id": (
            _daemon_supervised_process_record_id(snapshot)
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": snapshot["scheduler_id"],
        "daemon_supervisor_command_id": snapshot["daemon_supervisor_command_id"],
        "daemon_supervised_process_id": snapshot["daemon_supervised_process_id"],
        "action": snapshot["action"],
        "process_status": lifecycle["process_status"],
        "process_mode": snapshot["process_mode"],
        "process_id": process["process_id"],
        "host_id": process["host_id"],
        "observed_at": lifecycle["observed_at"],
        "started_at": lifecycle["started_at"],
        "completed_at": lifecycle["completed_at"],
        "exit_code": lifecycle["exit_code"],
        "termination_signal": lifecycle["termination_signal"],
        "process_running": metadata["process_running"],
        "process_started_observed": metadata["process_started_observed"],
        "process_stopped_observed": metadata["process_stopped_observed"],
        "subprocess_adapter_required": snapshot["guardrails"][
            "subprocess_adapter_required"
        ],
        "message": metadata["message"],
        "summary": summary,
        "metadata": _daemon_supervised_process_record_metadata(snapshot),
        "supervised_process_snapshot": deepcopy(snapshot),
        "supervised_process_snapshot_hash": sha256_json(dict(snapshot)),
        "created_at": lifecycle["observed_at"],
    }
    return validate_artifact_retention_scheduler_daemon_supervised_process_record(
        record
    )


def validate_artifact_retention_scheduler_daemon_supervised_process_record(
    supervised_process_record: Mapping[str, Any],
) -> dict[str, Any]:
    error_code = (
        "ae.artifact_retention_scheduler_daemon_supervised_process_record_invalid"
    )
    if not isinstance(supervised_process_record, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervised process record "
                "must be an object."
            ),
        )
    normalized = dict(supervised_process_record)
    if set(normalized) != {
        "daemon_supervised_process_record_schema_version",
        "daemon_supervised_process_record_id",
        "service_id",
        "scheduler_id",
        "daemon_supervisor_command_id",
        "daemon_supervised_process_id",
        "action",
        "process_status",
        "process_mode",
        "process_id",
        "host_id",
        "observed_at",
        "started_at",
        "completed_at",
        "exit_code",
        "termination_signal",
        "process_running",
        "process_started_observed",
        "process_stopped_observed",
        "subprocess_adapter_required",
        "message",
        "summary",
        "metadata",
        "supervised_process_snapshot",
        "supervised_process_snapshot_hash",
        "created_at",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervised process record "
                "keys are invalid."
            ),
        )
    if (
        normalized.get("daemon_supervised_process_record_schema_version")
        != AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_RECORD_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervised process record "
                "schema is invalid."
            ),
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervised process record "
                "service is invalid."
            ),
        )
    for field_name in (
        "daemon_supervised_process_record_id",
        "scheduler_id",
        "daemon_supervisor_command_id",
        "daemon_supervised_process_id",
        "observed_at",
        "host_id",
        "created_at",
    ):
        normalized[field_name] = _required_text(
            normalized.get(field_name),
            field_name,
            error_code=error_code,
        )
    normalized["action"] = _daemon_supervisor_action_for_context(
        normalized.get("action"),
        error_code=error_code,
    )
    normalized["process_status"] = _optional_daemon_supervised_process_status(
        normalized.get("process_status"),
        error_code=error_code,
    )
    normalized["process_id"] = _optional_daemon_supervised_process_id(
        normalized.get("process_id"),
        error_code=error_code,
    )
    normalized["started_at"] = optional_text(normalized.get("started_at"))
    normalized["completed_at"] = optional_text(normalized.get("completed_at"))
    normalized["exit_code"] = _optional_daemon_supervised_exit_code(
        normalized.get("exit_code"),
        error_code=error_code,
    )
    normalized["termination_signal"] = optional_text(
        normalized.get("termination_signal")
    )
    if normalized.get("process_mode") != (
        DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_MODE
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervised process record "
                "mode is invalid."
            ),
        )
    for field_name in (
        "process_running",
        "process_started_observed",
        "process_stopped_observed",
        "subprocess_adapter_required",
    ):
        normalized[field_name] = _required_bool(
            normalized.get(field_name),
            field_name,
            error_code=error_code,
        )
    normalized["message"] = optional_text(normalized.get("message"))
    if not isinstance(normalized.get("summary"), Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervised process record "
                "summary is invalid."
            ),
        )
    if not isinstance(normalized.get("metadata"), Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervised process record "
                "metadata is invalid."
            ),
        )
    snapshot = validate_artifact_retention_scheduler_daemon_supervised_process_snapshot(
        normalized.get("supervised_process_snapshot")
    )
    normalized["summary"] = dict(normalized["summary"])
    normalized["metadata"] = dict(normalized["metadata"])
    normalized["supervised_process_snapshot"] = snapshot
    _ensure_daemon_supervised_process_record_scope(
        normalized,
        error_code=error_code,
    )
    expected_summary = (
        summarize_artifact_retention_scheduler_daemon_supervised_process_snapshot(
            snapshot
        )
    )
    if normalized["summary"] != expected_summary:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervised process record "
                "summary is invalid."
            ),
        )
    expected_metadata = _daemon_supervised_process_record_metadata(snapshot)
    if normalized["metadata"] != expected_metadata:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervised process record "
                "metadata is invalid."
            ),
        )
    if normalized["daemon_supervised_process_record_id"] != (
        _daemon_supervised_process_record_id(snapshot)
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervised process record "
                "id is invalid."
            ),
        )
    if normalized["supervised_process_snapshot_hash"] != sha256_json(dict(snapshot)):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervised process record "
                "hash is invalid."
            ),
        )
    assert_artifact_retention_payload_safe(normalized)
    return normalized


def build_artifact_retention_scheduler_daemon_supervised_process_event(
    *,
    supervised_process_record: Mapping[str, Any],
    supervised_process_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    record = validate_artifact_retention_scheduler_daemon_supervised_process_record(
        supervised_process_record
    )
    snapshot = validate_artifact_retention_scheduler_daemon_supervised_process_snapshot(
        supervised_process_snapshot
    )
    if record["daemon_supervised_process_id"] != snapshot[
        "daemon_supervised_process_id"
    ]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_supervised_process_event_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon supervised process event "
                "scope is invalid."
            ),
        )
    event = {
        "daemon_supervised_process_event_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_EVENT_SCHEMA_VERSION
        ),
        "daemon_supervised_process_event_id": (
            _daemon_supervised_process_event_id(record)
        ),
        "daemon_supervised_process_record_id": record[
            "daemon_supervised_process_record_id"
        ],
        "daemon_supervised_process_id": record["daemon_supervised_process_id"],
        "daemon_supervisor_command_id": record["daemon_supervisor_command_id"],
        "service_id": "nex-ae-api",
        "scheduler_id": record["scheduler_id"],
        "action": record["action"],
        "process_status": record["process_status"],
        "event_type": "SUPERVISED_PROCESS_SNAPSHOT_RECORDED",
        "occurred_at": record["observed_at"],
        "summary": {
            "scheduler_id": record["scheduler_id"],
            "action": record["action"],
            "process_status": record["process_status"],
            "process_id": record["process_id"],
            "host_id": record["host_id"],
            "process_running": record["process_running"],
        },
        "metadata": _daemon_supervised_process_event_metadata(
            supervised_process_record=record,
            supervised_process_snapshot=snapshot,
        ),
        "created_at": record["created_at"],
    }
    return validate_artifact_retention_scheduler_daemon_supervised_process_event(
        event
    )


def validate_artifact_retention_scheduler_daemon_supervised_process_event(
    supervised_process_event: Mapping[str, Any],
) -> dict[str, Any]:
    error_code = (
        "ae.artifact_retention_scheduler_daemon_supervised_process_event_invalid"
    )
    if not isinstance(supervised_process_event, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervised process event "
                "must be an object."
            ),
        )
    normalized = dict(supervised_process_event)
    if set(normalized) != {
        "daemon_supervised_process_event_schema_version",
        "daemon_supervised_process_event_id",
        "daemon_supervised_process_record_id",
        "daemon_supervised_process_id",
        "daemon_supervisor_command_id",
        "service_id",
        "scheduler_id",
        "action",
        "process_status",
        "event_type",
        "occurred_at",
        "summary",
        "metadata",
        "created_at",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervised process event "
                "keys are invalid."
            ),
        )
    if (
        normalized.get("daemon_supervised_process_event_schema_version")
        != AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_EVENT_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervised process event "
                "schema is invalid."
            ),
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervised process event "
                "service is invalid."
            ),
        )
    for field_name in (
        "daemon_supervised_process_event_id",
        "daemon_supervised_process_record_id",
        "daemon_supervised_process_id",
        "daemon_supervisor_command_id",
        "scheduler_id",
        "event_type",
        "occurred_at",
        "created_at",
    ):
        normalized[field_name] = _required_text(
            normalized.get(field_name),
            field_name,
            error_code=error_code,
        )
    if normalized["event_type"] != "SUPERVISED_PROCESS_SNAPSHOT_RECORDED":
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervised process event "
                "type is invalid."
            ),
        )
    normalized["action"] = _daemon_supervisor_action_for_context(
        normalized.get("action"),
        error_code=error_code,
    )
    normalized["process_status"] = _optional_daemon_supervised_process_status(
        normalized.get("process_status"),
        error_code=error_code,
    )
    if not isinstance(normalized.get("summary"), Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervised process event "
                "summary is invalid."
            ),
        )
    if not isinstance(normalized.get("metadata"), Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervised process event "
                "metadata is invalid."
            ),
        )
    normalized["summary"] = dict(normalized["summary"])
    normalized["metadata"] = dict(normalized["metadata"])
    if normalized["daemon_supervised_process_event_id"] != (
        _daemon_supervised_process_event_id(normalized)
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervised process event "
                "id is invalid."
            ),
        )
    assert_artifact_retention_payload_safe(normalized)
    return normalized


def normalize_artifact_retention_scheduler_daemon_supervised_process_limit(
    limit: int | str | None,
) -> int:
    if limit is None:
        return 20
    return _bounded_positive_int(
        limit,
        "limit",
        max_value=MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_RECORD_LIMIT,
        error_code=(
            "ae.artifact_retention_scheduler_daemon_supervised_process_collection_invalid"
        ),
    )


def build_artifact_retention_scheduler_daemon_supervised_process_dispatch(
    *,
    supervised_process_snapshot: Mapping[str, Any],
    supervised_process_record: Mapping[str, Any],
    supervised_process_event: Mapping[str, Any],
) -> dict[str, Any]:
    snapshot = validate_artifact_retention_scheduler_daemon_supervised_process_snapshot(
        supervised_process_snapshot
    )
    record = validate_artifact_retention_scheduler_daemon_supervised_process_record(
        supervised_process_record
    )
    event = validate_artifact_retention_scheduler_daemon_supervised_process_event(
        supervised_process_event
    )
    if (
        record["daemon_supervised_process_id"]
        != snapshot["daemon_supervised_process_id"]
        or event["daemon_supervised_process_record_id"]
        != record["daemon_supervised_process_record_id"]
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_supervised_process_dispatch_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon supervised process dispatch "
                "scope is invalid."
            ),
        )
    dispatch = {
        "daemon_supervised_process_dispatch_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_DISPATCH_SCHEMA_VERSION
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": snapshot["scheduler_id"],
        "action": snapshot["action"],
        "process_status": snapshot["lifecycle"]["process_status"],
        "supervised_process_snapshot": snapshot,
        "supervised_process_record": record,
        "supervised_process_event": event,
        "guardrails": _daemon_supervised_process_route_guardrails(
            read_only=False,
            process_control_allowed=False,
        ),
        "metadata": {
            "safe_for_ag_projection": True,
            "persistence_performed": True,
            "supervised_process_record_persisted": True,
            "supervised_process_event_persisted": True,
            "process_control_allowed": False,
            "process_started": False,
            "process_stopped": False,
            "database_url_included": False,
            "storage_path_included": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_included": False,
            "raw_daemon_runtime_payload_included": False,
        },
    }
    assert_artifact_retention_payload_safe(dispatch)
    return dispatch


def build_artifact_retention_scheduler_daemon_supervised_process_collection(
    records: Sequence[Mapping[str, Any]],
    *,
    scheduler_id: str | None = None,
    action: str | None = None,
    process_status: str | None = None,
    limit: int | str | None = None,
) -> dict[str, Any]:
    normalized_limit = (
        normalize_artifact_retention_scheduler_daemon_supervised_process_limit(
            limit
        )
    )
    normalized_scheduler_id = optional_text(scheduler_id)
    normalized_action = _optional_daemon_supervisor_action(
        action,
        error_code=(
            "ae.artifact_retention_scheduler_daemon_supervised_process_collection_invalid"
        ),
    )
    normalized_process_status = _optional_daemon_supervised_process_status(
        process_status,
        error_code=(
            "ae.artifact_retention_scheduler_daemon_supervised_process_collection_invalid"
        ),
    )
    normalized_records = [
        validate_artifact_retention_scheduler_daemon_supervised_process_record(
            record
        )
        for record in records
    ]
    collection = {
        "daemon_supervised_process_collection_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_COLLECTION_SCHEMA_VERSION
        ),
        "service_id": "nex-ae-api",
        "filter": {
            "scheduler_id": normalized_scheduler_id,
            "action": normalized_action,
            "process_status": normalized_process_status,
        },
        "count": len(normalized_records),
        "limit": normalized_limit,
        "items": [
            _daemon_supervised_process_collection_item(record)
            for record in normalized_records
        ],
        "guardrails": _daemon_supervised_process_route_guardrails(
            read_only=True,
            process_control_allowed=False,
        ),
        "metadata": _daemon_supervised_process_collection_metadata(
            records=normalized_records,
            limit=normalized_limit,
        ),
    }
    assert_artifact_retention_payload_safe(collection)
    return collection


def build_artifact_retention_scheduler_daemon_supervised_process_detail(
    *,
    supervised_process_record: Mapping[str, Any],
    supervised_process_events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    record = validate_artifact_retention_scheduler_daemon_supervised_process_record(
        supervised_process_record
    )
    events = [
        validate_artifact_retention_scheduler_daemon_supervised_process_event(
            event
        )
        for event in supervised_process_events
    ]
    for event in events:
        if event["daemon_supervised_process_record_id"] != record[
            "daemon_supervised_process_record_id"
        ]:
            raise ArtifactHandoffError(
                status_code=422,
                error_code=(
                    "ae.artifact_retention_scheduler_daemon_supervised_process_detail_invalid"
                ),
                detail=(
                    "Artifact retention scheduler daemon supervised process "
                    "detail event scope is invalid."
                ),
            )
    detail = {
        "daemon_supervised_process_detail_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_DETAIL_SCHEMA_VERSION
        ),
        "service_id": "nex-ae-api",
        "daemon_supervised_process_record_id": record[
            "daemon_supervised_process_record_id"
        ],
        "supervised_process_record": record,
        "supervised_process_event_count": len(events),
        "supervised_process_events": events,
        "guardrails": _daemon_supervised_process_route_guardrails(
            read_only=True,
            process_control_allowed=False,
        ),
        "metadata": _daemon_supervised_process_detail_metadata(
            supervised_process_record=record,
            supervised_process_events=events,
        ),
    }
    assert_artifact_retention_payload_safe(detail)
    return detail


def build_artifact_retention_scheduler_daemon_supervisor_record(
    supervisor_result: Mapping[str, Any],
) -> dict[str, Any]:
    validated = validate_artifact_retention_scheduler_daemon_supervisor_result(
        supervisor_result
    )
    command = validated["supervisor_command"]
    command_payload = command["command"]
    metadata = validated["metadata"]
    summary = summarize_artifact_retention_scheduler_daemon_supervisor_result(
        validated
    )
    record = {
        "daemon_supervisor_record_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_RECORD_SCHEMA_VERSION
        ),
        "daemon_supervisor_record_id": _daemon_supervisor_record_id(validated),
        "service_id": "nex-ae-api",
        "scheduler_id": validated["scheduler_id"],
        "daemon_supervisor_command_id": command["daemon_supervisor_command_id"],
        "daemon_supervisor_result_id": validated["daemon_supervisor_result_id"],
        "action": validated["action"],
        "result_status": validated["result_status"],
        "decision_reason": validated["decision_reason"],
        "observed_at": validated["observed_at"],
        "checked_at": command_payload["checked_at"],
        "runtime_ready": metadata["runtime_ready"],
        "supervisor_adapter_available": metadata["supervisor_adapter_available"],
        "supervisor_adapter_invoked": metadata["supervisor_adapter_invoked"],
        "adapter_name": metadata["adapter_name"],
        "process_started": metadata["process_started"],
        "process_stopped": metadata["process_stopped"],
        "message": validated["message"],
        "summary": summary,
        "metadata": _daemon_supervisor_record_metadata(validated),
        "supervisor_command": deepcopy(command),
        "supervisor_result": deepcopy(validated),
        "supervisor_result_hash": sha256_json(dict(validated)),
        "created_at": validated["observed_at"],
    }
    return validate_artifact_retention_scheduler_daemon_supervisor_record(record)


def validate_artifact_retention_scheduler_daemon_supervisor_record(
    supervisor_record: Mapping[str, Any],
) -> dict[str, Any]:
    error_code = "ae.artifact_retention_scheduler_daemon_supervisor_record_invalid"
    if not isinstance(supervisor_record, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor record must be "
                "an object."
            ),
        )
    normalized = dict(supervisor_record)
    if set(normalized) != {
        "daemon_supervisor_record_schema_version",
        "daemon_supervisor_record_id",
        "service_id",
        "scheduler_id",
        "daemon_supervisor_command_id",
        "daemon_supervisor_result_id",
        "action",
        "result_status",
        "decision_reason",
        "observed_at",
        "checked_at",
        "runtime_ready",
        "supervisor_adapter_available",
        "supervisor_adapter_invoked",
        "adapter_name",
        "process_started",
        "process_stopped",
        "message",
        "summary",
        "metadata",
        "supervisor_command",
        "supervisor_result",
        "supervisor_result_hash",
        "created_at",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor record keys are "
                "invalid."
            ),
        )
    if (
        normalized.get("daemon_supervisor_record_schema_version")
        != AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_RECORD_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor record schema is "
                "invalid."
            ),
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor record service "
                "is invalid."
            ),
        )
    for field_name in (
        "daemon_supervisor_record_id",
        "scheduler_id",
        "daemon_supervisor_command_id",
        "daemon_supervisor_result_id",
        "decision_reason",
        "observed_at",
        "checked_at",
        "created_at",
    ):
        normalized[field_name] = _required_text(
            normalized.get(field_name),
            field_name,
            error_code=error_code,
        )
    normalized["action"] = _daemon_supervisor_action_for_context(
        normalized.get("action"),
        error_code=error_code,
    )
    normalized["result_status"] = _daemon_supervisor_result_status_for_context(
        normalized.get("result_status"),
        error_code=error_code,
    )
    for field_name in (
        "runtime_ready",
        "supervisor_adapter_available",
        "supervisor_adapter_invoked",
        "process_started",
        "process_stopped",
    ):
        normalized[field_name] = _required_bool(
            normalized.get(field_name),
            field_name,
            error_code=error_code,
        )
    normalized["adapter_name"] = optional_text(normalized.get("adapter_name"))
    normalized["message"] = optional_text(normalized.get("message"))
    if not isinstance(normalized.get("summary"), Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor record summary "
                "is invalid."
            ),
        )
    if not isinstance(normalized.get("metadata"), Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor record metadata "
                "is invalid."
            ),
        )
    normalized["summary"] = dict(normalized["summary"])
    normalized["metadata"] = dict(normalized["metadata"])
    normalized["supervisor_command"] = (
        validate_artifact_retention_scheduler_daemon_supervisor_command(
            normalized.get("supervisor_command")
        )
    )
    normalized["supervisor_result"] = (
        validate_artifact_retention_scheduler_daemon_supervisor_result(
            normalized.get("supervisor_result")
        )
    )
    _ensure_daemon_supervisor_record_scope(normalized, error_code=error_code)
    if normalized["metadata"] != _daemon_supervisor_record_metadata(
        normalized["supervisor_result"]
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor record metadata "
                "is invalid."
            ),
        )
    if normalized["summary"] != summarize_artifact_retention_scheduler_daemon_supervisor_result(
        normalized["supervisor_result"]
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor record summary "
                "is invalid."
            ),
        )
    if normalized["daemon_supervisor_record_id"] != _daemon_supervisor_record_id(
        normalized["supervisor_result"]
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor record id is "
                "invalid."
            ),
        )
    if normalized["supervisor_result_hash"] != sha256_json(
        dict(normalized["supervisor_result"])
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor record hash is "
                "invalid."
            ),
        )
    assert_artifact_retention_payload_safe(normalized)
    return normalized


def build_artifact_retention_scheduler_daemon_supervisor_event(
    *,
    supervisor_record: Mapping[str, Any],
    supervisor_result: Mapping[str, Any],
) -> dict[str, Any]:
    record = validate_artifact_retention_scheduler_daemon_supervisor_record(
        supervisor_record
    )
    result = validate_artifact_retention_scheduler_daemon_supervisor_result(
        supervisor_result
    )
    if result["daemon_supervisor_result_id"] != record["daemon_supervisor_result_id"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_supervisor_event_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon supervisor event scope is "
                "invalid."
            ),
        )
    event = {
        "daemon_supervisor_event_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_EVENT_SCHEMA_VERSION
        ),
        "daemon_supervisor_event_id": _daemon_supervisor_event_id(record),
        "daemon_supervisor_record_id": record["daemon_supervisor_record_id"],
        "daemon_supervisor_command_id": record["daemon_supervisor_command_id"],
        "daemon_supervisor_result_id": record["daemon_supervisor_result_id"],
        "service_id": "nex-ae-api",
        "scheduler_id": record["scheduler_id"],
        "action": record["action"],
        "result_status": record["result_status"],
        "decision_reason": record["decision_reason"],
        "event_type": "SUPERVISOR_RESULT_RECORDED",
        "occurred_at": record["observed_at"],
        "summary": {
            "scheduler_id": record["scheduler_id"],
            "action": record["action"],
            "result_status": record["result_status"],
            "decision_reason": record["decision_reason"],
            "supervisor_adapter_invoked": record[
                "supervisor_adapter_invoked"
            ],
            "process_started": False,
            "process_stopped": False,
        },
        "metadata": _daemon_supervisor_event_metadata(
            supervisor_record=record,
            supervisor_result=result,
        ),
        "created_at": record["created_at"],
    }
    return validate_artifact_retention_scheduler_daemon_supervisor_event(event)


def validate_artifact_retention_scheduler_daemon_supervisor_event(
    supervisor_event: Mapping[str, Any],
) -> dict[str, Any]:
    error_code = "ae.artifact_retention_scheduler_daemon_supervisor_event_invalid"
    if not isinstance(supervisor_event, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor event must be "
                "an object."
            ),
        )
    normalized = dict(supervisor_event)
    if set(normalized) != {
        "daemon_supervisor_event_schema_version",
        "daemon_supervisor_event_id",
        "daemon_supervisor_record_id",
        "daemon_supervisor_command_id",
        "daemon_supervisor_result_id",
        "service_id",
        "scheduler_id",
        "action",
        "result_status",
        "decision_reason",
        "event_type",
        "occurred_at",
        "summary",
        "metadata",
        "created_at",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor event keys are "
                "invalid."
            ),
        )
    if (
        normalized.get("daemon_supervisor_event_schema_version")
        != AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_EVENT_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor event schema is "
                "invalid."
            ),
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor event service is "
                "invalid."
            ),
        )
    for field_name in (
        "daemon_supervisor_event_id",
        "daemon_supervisor_record_id",
        "daemon_supervisor_command_id",
        "daemon_supervisor_result_id",
        "scheduler_id",
        "decision_reason",
        "event_type",
        "occurred_at",
        "created_at",
    ):
        normalized[field_name] = _required_text(
            normalized.get(field_name),
            field_name,
            error_code=error_code,
        )
    if normalized["event_type"] != "SUPERVISOR_RESULT_RECORDED":
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor event type is "
                "invalid."
            ),
        )
    normalized["action"] = _daemon_supervisor_action_for_context(
        normalized.get("action"),
        error_code=error_code,
    )
    normalized["result_status"] = _daemon_supervisor_result_status_for_context(
        normalized.get("result_status"),
        error_code=error_code,
    )
    if not isinstance(normalized.get("summary"), Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor event summary is "
                "invalid."
            ),
        )
    if not isinstance(normalized.get("metadata"), Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor event metadata "
                "is invalid."
            ),
        )
    normalized["summary"] = dict(normalized["summary"])
    normalized["metadata"] = dict(normalized["metadata"])
    if normalized["daemon_supervisor_event_id"] != _daemon_supervisor_event_id(
        normalized
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor event id is "
                "invalid."
            ),
        )
    assert_artifact_retention_payload_safe(normalized)
    return normalized


def normalize_artifact_retention_scheduler_daemon_supervisor_limit(
    limit: int | str | None,
) -> int:
    if limit is None:
        return 20
    return _bounded_positive_int(
        limit,
        "limit",
        max_value=MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_RECORD_LIMIT,
        error_code=(
            "ae.artifact_retention_scheduler_daemon_supervisor_collection_invalid"
        ),
    )


def build_artifact_retention_scheduler_daemon_supervisor_dispatch(
    *,
    supervisor_result: Mapping[str, Any],
    supervisor_record: Mapping[str, Any],
    supervisor_event: Mapping[str, Any],
) -> dict[str, Any]:
    result = validate_artifact_retention_scheduler_daemon_supervisor_result(
        supervisor_result
    )
    record = validate_artifact_retention_scheduler_daemon_supervisor_record(
        supervisor_record
    )
    event = validate_artifact_retention_scheduler_daemon_supervisor_event(
        supervisor_event
    )
    if (
        record["daemon_supervisor_result_id"]
        != result["daemon_supervisor_result_id"]
        or event["daemon_supervisor_record_id"]
        != record["daemon_supervisor_record_id"]
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_supervisor_dispatch_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon supervisor dispatch scope "
                "is invalid."
            ),
        )
    dispatch = {
        "daemon_supervisor_dispatch_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_DISPATCH_SCHEMA_VERSION
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": result["scheduler_id"],
        "action": result["action"],
        "result_status": result["result_status"],
        "decision_reason": result["decision_reason"],
        "supervisor_result": result,
        "supervisor_record": record,
        "supervisor_event": event,
        "guardrails": _daemon_supervisor_route_guardrails(
            read_only=False,
            process_control_allowed=False,
        ),
        "metadata": {
            "safe_for_ag_projection": True,
            "persistence_performed": True,
            "supervisor_record_persisted": True,
            "supervisor_event_persisted": True,
            "database_url_included": False,
            "storage_path_included": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_included": False,
            "raw_daemon_runtime_payload_included": False,
            "process_started": False,
            "process_stopped": False,
        },
    }
    assert_artifact_retention_payload_safe(dispatch)
    return dispatch


def build_artifact_retention_scheduler_daemon_supervisor_collection(
    records: Sequence[Mapping[str, Any]],
    *,
    scheduler_id: str | None = None,
    action: str | None = None,
    result_status: str | None = None,
    limit: int | str | None = None,
) -> dict[str, Any]:
    normalized_limit = normalize_artifact_retention_scheduler_daemon_supervisor_limit(
        limit
    )
    normalized_scheduler_id = optional_text(scheduler_id)
    normalized_action = _optional_daemon_supervisor_action(
        action,
        error_code=(
            "ae.artifact_retention_scheduler_daemon_supervisor_collection_invalid"
        ),
    )
    normalized_result_status = _optional_daemon_supervisor_result_status(
        result_status,
        error_code=(
            "ae.artifact_retention_scheduler_daemon_supervisor_collection_invalid"
        ),
    )
    normalized_records = [
        validate_artifact_retention_scheduler_daemon_supervisor_record(record)
        for record in records
    ]
    collection = {
        "daemon_supervisor_collection_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_COLLECTION_SCHEMA_VERSION
        ),
        "service_id": "nex-ae-api",
        "filter": {
            "scheduler_id": normalized_scheduler_id,
            "action": normalized_action,
            "result_status": normalized_result_status,
        },
        "count": len(normalized_records),
        "limit": normalized_limit,
        "items": [
            _daemon_supervisor_collection_item(record)
            for record in normalized_records
        ],
        "guardrails": _daemon_supervisor_route_guardrails(
            read_only=True,
            process_control_allowed=False,
        ),
        "metadata": _daemon_supervisor_collection_metadata(
            records=normalized_records,
            limit=normalized_limit,
        ),
    }
    assert_artifact_retention_payload_safe(collection)
    return collection


def build_artifact_retention_scheduler_daemon_supervisor_detail(
    *,
    supervisor_record: Mapping[str, Any],
    supervisor_events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    record = validate_artifact_retention_scheduler_daemon_supervisor_record(
        supervisor_record
    )
    events = [
        validate_artifact_retention_scheduler_daemon_supervisor_event(event)
        for event in supervisor_events
    ]
    for event in events:
        if event["daemon_supervisor_record_id"] != record[
            "daemon_supervisor_record_id"
        ]:
            raise ArtifactHandoffError(
                status_code=422,
                error_code=(
                    "ae.artifact_retention_scheduler_daemon_supervisor_detail_invalid"
                ),
                detail=(
                    "Artifact retention scheduler daemon supervisor detail event "
                    "scope is invalid."
                ),
            )
    detail = {
        "daemon_supervisor_detail_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_DETAIL_SCHEMA_VERSION
        ),
        "service_id": "nex-ae-api",
        "daemon_supervisor_record_id": record["daemon_supervisor_record_id"],
        "supervisor_record": record,
        "supervisor_event_count": len(events),
        "supervisor_events": events,
        "guardrails": _daemon_supervisor_route_guardrails(
            read_only=True,
            process_control_allowed=False,
        ),
        "metadata": _daemon_supervisor_detail_metadata(
            supervisor_record=record,
            supervisor_events=events,
        ),
    }
    assert_artifact_retention_payload_safe(detail)
    return detail


def build_artifact_retention_scheduler_daemon_run_record(
    result: Mapping[str, Any],
) -> dict[str, Any]:
    validated = validate_artifact_retention_scheduler_daemon_cli_execution_result(
        result
    )
    bounded_loop = validated["bounded_loop_result"]
    process = validated["process_lock"]["process"]
    started_lifecycle = validated["started_run_metadata"]["lifecycle"]
    completed_lifecycle = validated["completed_run_metadata"]["lifecycle"]
    summary = summarize_artifact_retention_scheduler_daemon_cli_execution_result(
        validated
    )
    record = {
        "daemon_run_record_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUN_RECORD_SCHEMA_VERSION
        ),
        "daemon_run_record_id": _daemon_run_record_id(validated),
        "service_id": "nex-ae-api",
        "scheduler_id": validated["scheduler_id"],
        "daemon_instance_id": bounded_loop["daemon_instance_id"],
        "daemon_cli_execution_result_id": validated[
            "daemon_cli_execution_result_id"
        ],
        "daemon_cli_execute_command_id": validated[
            "daemon_cli_execute_command_id"
        ],
        "daemon_process_lock_id": validated["daemon_process_lock_id"],
        "started_daemon_run_id": validated["started_daemon_run_id"],
        "completed_daemon_run_id": validated["completed_daemon_run_id"],
        "process_id": process["process_id"],
        "host_id": process["host_id"],
        "run_status": completed_lifecycle["run_status"],
        "result_status": validated["result_status"],
        "stop_reason": validated["stop_reason"],
        "max_cycles": bounded_loop["max_cycles"],
        "cycle_count": bounded_loop["cycle_count"],
        "worker_requested": bounded_loop["worker_requested"],
        "job_enqueued": validated["metadata"]["job_enqueued"],
        "worker_executed": validated["metadata"]["worker_executed"],
        "started_at": started_lifecycle["started_at"],
        "completed_at": completed_lifecycle["completed_at"],
        "checked_at": validated["execute_command"]["command"]["checked_at"],
        "summary": summary,
        "metadata": _daemon_run_record_metadata(validated),
        "execution_result_hash": sha256_json(dict(validated)),
        "created_at": completed_lifecycle["completed_at"],
    }
    return validate_artifact_retention_scheduler_daemon_run_record(record)


def build_artifact_retention_scheduler_daemon_run_collection(
    records: Sequence[Mapping[str, Any]],
    *,
    scheduler_id: str | None = None,
    result_status: str | None = None,
    limit: int | str | None = None,
) -> dict[str, Any]:
    normalized_limit = normalize_artifact_retention_scheduler_daemon_run_limit(limit)
    normalized_scheduler_id = optional_text(scheduler_id)
    normalized_result_status = _optional_daemon_result_status(
        result_status,
        error_code="ae.artifact_retention_scheduler_daemon_run_collection_invalid",
    )
    normalized_records = [
        validate_artifact_retention_scheduler_daemon_run_record(record)
        for record in records
    ]
    collection = {
        "daemon_run_collection_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUN_COLLECTION_SCHEMA_VERSION
        ),
        "service_id": "nex-ae-api",
        "filter": {
            "scheduler_id": normalized_scheduler_id,
            "result_status": normalized_result_status,
        },
        "count": len(normalized_records),
        "limit": normalized_limit,
        "items": [
            _daemon_run_collection_item(record) for record in normalized_records
        ],
        "guardrails": _daemon_run_read_model_guardrails(),
        "metadata": _daemon_run_collection_metadata(
            records=normalized_records,
            limit=normalized_limit,
        ),
    }
    return validate_artifact_retention_scheduler_daemon_run_collection(collection)


def validate_artifact_retention_scheduler_daemon_run_collection(
    collection: Mapping[str, Any],
) -> dict[str, Any]:
    error_code = "ae.artifact_retention_scheduler_daemon_run_collection_invalid"
    if not isinstance(collection, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon run collection must be an "
                "object."
            ),
        )
    normalized = dict(collection)
    if set(normalized) != {
        "daemon_run_collection_schema_version",
        "service_id",
        "filter",
        "count",
        "limit",
        "items",
        "guardrails",
        "metadata",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon run collection keys are "
                "invalid."
            ),
        )
    if (
        normalized.get("daemon_run_collection_schema_version")
        != AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUN_COLLECTION_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon run collection schema is "
                "invalid."
            ),
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon run collection service is "
                "invalid."
            ),
        )
    normalized_filter = normalized.get("filter")
    if not isinstance(normalized_filter, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon run collection filter is "
                "invalid."
            ),
        )
    if set(normalized_filter) != {"scheduler_id", "result_status"}:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon run collection filter is "
                "invalid."
            ),
        )
    normalized["filter"] = {
        "scheduler_id": optional_text(normalized_filter.get("scheduler_id")),
        "result_status": _optional_daemon_result_status(
            normalized_filter.get("result_status"),
            error_code=error_code,
        ),
    }
    normalized["limit"] = normalize_artifact_retention_scheduler_daemon_run_limit(
        normalized.get("limit")
    )
    normalized["count"] = _non_negative_int(
        normalized.get("count"),
        "count",
        error_code=error_code,
    )
    items = normalized.get("items")
    if not isinstance(items, list):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon run collection items are "
                "invalid."
            ),
        )
    normalized["items"] = [
        _validate_daemon_run_collection_item(item) for item in items
    ]
    if normalized["count"] != len(normalized["items"]):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon run collection count is "
                "invalid."
            ),
        )
    if normalized["guardrails"] != _daemon_run_read_model_guardrails():
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon run collection guardrails are "
                "invalid."
            ),
        )
    if not isinstance(normalized.get("metadata"), Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon run collection metadata is "
                "invalid."
            ),
        )
    normalized["metadata"] = dict(normalized["metadata"])
    assert_artifact_retention_payload_safe(normalized)
    return normalized


def build_artifact_retention_scheduler_daemon_run_detail(
    *,
    run_record: Mapping[str, Any],
    lifecycle_events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    record = validate_artifact_retention_scheduler_daemon_run_record(run_record)
    events = [
        validate_artifact_retention_scheduler_daemon_lifecycle_event(event)
        for event in lifecycle_events
    ]
    detail = {
        "daemon_run_detail_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUN_DETAIL_SCHEMA_VERSION
        ),
        "service_id": "nex-ae-api",
        "daemon_run_record_id": record["daemon_run_record_id"],
        "run_record": record,
        "lifecycle_event_count": len(events),
        "lifecycle_events": events,
        "guardrails": _daemon_run_read_model_guardrails(),
        "metadata": _daemon_run_detail_metadata(
            run_record=record,
            lifecycle_events=events,
        ),
    }
    return validate_artifact_retention_scheduler_daemon_run_detail(detail)


def validate_artifact_retention_scheduler_daemon_run_detail(
    detail: Mapping[str, Any],
) -> dict[str, Any]:
    error_code = "ae.artifact_retention_scheduler_daemon_run_detail_invalid"
    if not isinstance(detail, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail="Artifact retention scheduler daemon run detail must be an object.",
        )
    normalized = dict(detail)
    if set(normalized) != {
        "daemon_run_detail_schema_version",
        "service_id",
        "daemon_run_record_id",
        "run_record",
        "lifecycle_event_count",
        "lifecycle_events",
        "guardrails",
        "metadata",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail="Artifact retention scheduler daemon run detail keys are invalid.",
        )
    if (
        normalized.get("daemon_run_detail_schema_version")
        != AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUN_DETAIL_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail="Artifact retention scheduler daemon run detail schema is invalid.",
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail="Artifact retention scheduler daemon run detail service is invalid.",
        )
    record = validate_artifact_retention_scheduler_daemon_run_record(
        normalized.get("run_record")
    )
    normalized_id = _required_text(
        normalized.get("daemon_run_record_id"),
        "daemon_run_record_id",
        error_code=error_code,
    )
    if normalized_id != record["daemon_run_record_id"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail="Artifact retention scheduler daemon run detail scope is invalid.",
        )
    lifecycle_events = normalized.get("lifecycle_events")
    if not isinstance(lifecycle_events, list):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon run detail lifecycle events "
                "are invalid."
            ),
        )
    normalized["lifecycle_events"] = [
        validate_artifact_retention_scheduler_daemon_lifecycle_event(event)
        for event in lifecycle_events
    ]
    for event in normalized["lifecycle_events"]:
        if event["daemon_run_record_id"] != record["daemon_run_record_id"]:
            raise ArtifactHandoffError(
                status_code=422,
                error_code=error_code,
                detail=(
                    "Artifact retention scheduler daemon run detail event scope "
                    "is invalid."
                ),
            )
    normalized["lifecycle_event_count"] = _non_negative_int(
        normalized.get("lifecycle_event_count"),
        "lifecycle_event_count",
        error_code=error_code,
    )
    if normalized["lifecycle_event_count"] != len(normalized["lifecycle_events"]):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon run detail event count is "
                "invalid."
            ),
        )
    if normalized["guardrails"] != _daemon_run_read_model_guardrails():
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon run detail guardrails are "
                "invalid."
            ),
        )
    if not isinstance(normalized.get("metadata"), Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail="Artifact retention scheduler daemon run detail metadata is invalid.",
        )
    normalized["daemon_run_record_id"] = normalized_id
    normalized["run_record"] = record
    normalized["metadata"] = dict(normalized["metadata"])
    assert_artifact_retention_payload_safe(normalized)
    return normalized


def normalize_artifact_retention_scheduler_daemon_run_limit(
    limit: int | str | None,
) -> int:
    if limit is None:
        return 20
    return _bounded_positive_int(
        limit,
        "limit",
        max_value=MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUN_COLLECTION_LIMIT,
        error_code="ae.artifact_retention_scheduler_daemon_run_collection_invalid",
    )


def validate_artifact_retention_scheduler_daemon_run_record(
    record: Mapping[str, Any],
) -> dict[str, Any]:
    error_code = "ae.artifact_retention_scheduler_daemon_run_record_invalid"
    if not isinstance(record, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail="Artifact retention scheduler daemon run record must be an object.",
        )
    normalized = dict(record)
    if set(normalized) != {
        "daemon_run_record_schema_version",
        "daemon_run_record_id",
        "service_id",
        "scheduler_id",
        "daemon_instance_id",
        "daemon_cli_execution_result_id",
        "daemon_cli_execute_command_id",
        "daemon_process_lock_id",
        "started_daemon_run_id",
        "completed_daemon_run_id",
        "process_id",
        "host_id",
        "run_status",
        "result_status",
        "stop_reason",
        "max_cycles",
        "cycle_count",
        "worker_requested",
        "job_enqueued",
        "worker_executed",
        "started_at",
        "completed_at",
        "checked_at",
        "summary",
        "metadata",
        "execution_result_hash",
        "created_at",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail="Artifact retention scheduler daemon run record keys are invalid.",
        )
    if (
        normalized.get("daemon_run_record_schema_version")
        != AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUN_RECORD_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail="Artifact retention scheduler daemon run record schema is invalid.",
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail="Artifact retention scheduler daemon run record service is invalid.",
        )
    for field_name in (
        "daemon_run_record_id",
        "scheduler_id",
        "daemon_instance_id",
        "daemon_cli_execution_result_id",
        "daemon_cli_execute_command_id",
        "daemon_process_lock_id",
        "started_daemon_run_id",
        "completed_daemon_run_id",
        "host_id",
        "stop_reason",
        "started_at",
        "completed_at",
        "checked_at",
        "created_at",
    ):
        normalized[field_name] = _required_text(
            normalized.get(field_name),
            field_name,
            error_code=error_code,
        )
    normalized["process_id"] = _positive_int(
        normalized.get("process_id"),
        "process_id",
        error_code=error_code,
    )
    normalized["run_status"] = _daemon_run_status(
        normalized.get("run_status"),
        error_code=error_code,
    )
    normalized["result_status"] = _daemon_result_status(
        normalized.get("result_status"),
        error_code=error_code,
    )
    normalized["max_cycles"] = _bounded_positive_int(
        normalized.get("max_cycles"),
        "max_cycles",
        max_value=MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_MAX_CYCLES,
        error_code=error_code,
    )
    normalized["cycle_count"] = _non_negative_int(
        normalized.get("cycle_count"),
        "cycle_count",
        error_code=error_code,
    )
    if normalized["cycle_count"] > normalized["max_cycles"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail="Artifact retention scheduler daemon run record cycle count is invalid.",
        )
    for field_name in ("worker_requested", "job_enqueued", "worker_executed"):
        normalized[field_name] = _required_bool(
            normalized.get(field_name),
            field_name,
            error_code=error_code,
        )
    if not isinstance(normalized.get("summary"), Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail="Artifact retention scheduler daemon run record summary is invalid.",
        )
    normalized["summary"] = dict(normalized["summary"])
    if not isinstance(normalized.get("metadata"), Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail="Artifact retention scheduler daemon run record metadata is invalid.",
        )
    normalized["metadata"] = dict(normalized["metadata"])
    if (
        _required_text(
            normalized.get("execution_result_hash"),
            "execution_result_hash",
            error_code=error_code,
        )
        != normalized["execution_result_hash"]
        or len(normalized["execution_result_hash"]) != 64
        or any(char not in "0123456789abcdef" for char in normalized["execution_result_hash"])
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail="Artifact retention scheduler daemon run record hash is invalid.",
        )
    assert_artifact_retention_payload_safe(
        {
            "summary": normalized["summary"],
            "metadata": normalized["metadata"],
        }
    )
    return normalized


def build_artifact_retention_scheduler_daemon_lifecycle_events(
    *,
    run_record: Mapping[str, Any],
    execution_result: Mapping[str, Any],
) -> list[dict[str, Any]]:
    record = validate_artifact_retention_scheduler_daemon_run_record(run_record)
    result = validate_artifact_retention_scheduler_daemon_cli_execution_result(
        execution_result
    )
    events = [
        _daemon_lifecycle_event(
            run_record=record,
            execution_result=result,
            event_type="RUN_STARTED",
            daemon_run_metadata_id=record["started_daemon_run_id"],
            run_status="RUNNING",
            occurred_at=record["started_at"],
            result_status=None,
            stop_reason=None,
            cycle_count=0,
        ),
        _daemon_lifecycle_event(
            run_record=record,
            execution_result=result,
            event_type="RUN_COMPLETED",
            daemon_run_metadata_id=record["completed_daemon_run_id"],
            run_status=record["run_status"],
            occurred_at=record["completed_at"],
            result_status=record["result_status"],
            stop_reason=record["stop_reason"],
            cycle_count=record["cycle_count"],
        ),
    ]
    return [
        validate_artifact_retention_scheduler_daemon_lifecycle_event(event)
        for event in events
    ]


def validate_artifact_retention_scheduler_daemon_lifecycle_event(
    event: Mapping[str, Any],
) -> dict[str, Any]:
    error_code = "ae.artifact_retention_scheduler_daemon_lifecycle_event_invalid"
    if not isinstance(event, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon lifecycle event must be an "
                "object."
            ),
        )
    normalized = dict(event)
    if set(normalized) != {
        "daemon_lifecycle_event_schema_version",
        "daemon_lifecycle_event_id",
        "daemon_run_record_id",
        "daemon_cli_execution_result_id",
        "daemon_run_metadata_id",
        "service_id",
        "scheduler_id",
        "daemon_instance_id",
        "event_type",
        "run_status",
        "result_status",
        "stop_reason",
        "cycle_count",
        "occurred_at",
        "process_id",
        "host_id",
        "summary",
        "metadata",
        "created_at",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon lifecycle event keys are "
                "invalid."
            ),
        )
    if (
        normalized.get("daemon_lifecycle_event_schema_version")
        != AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_LIFECYCLE_EVENT_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon lifecycle event schema is "
                "invalid."
            ),
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon lifecycle event service is "
                "invalid."
            ),
        )
    for field_name in (
        "daemon_lifecycle_event_id",
        "daemon_run_record_id",
        "daemon_cli_execution_result_id",
        "daemon_run_metadata_id",
        "scheduler_id",
        "daemon_instance_id",
        "event_type",
        "run_status",
        "occurred_at",
        "host_id",
        "created_at",
    ):
        normalized[field_name] = _required_text(
            normalized.get(field_name),
            field_name,
            error_code=error_code,
        )
    if normalized["event_type"] not in AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_LIFECYCLE_EVENT_TYPES:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon lifecycle event type is "
                "invalid."
            ),
        )
    normalized["run_status"] = _daemon_run_status(
        normalized["run_status"],
        error_code=error_code,
    )
    if normalized.get("result_status") is not None:
        normalized["result_status"] = _daemon_result_status(
            normalized.get("result_status"),
            error_code=error_code,
        )
    if normalized.get("stop_reason") is not None:
        normalized["stop_reason"] = _required_text(
            normalized.get("stop_reason"),
            "stop_reason",
            error_code=error_code,
        )
    normalized["cycle_count"] = _non_negative_int(
        normalized.get("cycle_count"),
        "cycle_count",
        error_code=error_code,
    )
    normalized["process_id"] = _positive_int(
        normalized.get("process_id"),
        "process_id",
        error_code=error_code,
    )
    if normalized["event_type"] == "RUN_STARTED":
        if (
            normalized["run_status"] != "RUNNING"
            or normalized["result_status"] is not None
            or normalized["stop_reason"] is not None
            or normalized["cycle_count"] != 0
        ):
            raise ArtifactHandoffError(
                status_code=422,
                error_code=error_code,
                detail=(
                    "Artifact retention scheduler daemon lifecycle start event "
                    "is invalid."
                ),
            )
    if normalized["event_type"] == "RUN_COMPLETED":
        if normalized["result_status"] is None or normalized["stop_reason"] is None:
            raise ArtifactHandoffError(
                status_code=422,
                error_code=error_code,
                detail=(
                    "Artifact retention scheduler daemon lifecycle completion "
                    "event is invalid."
                ),
            )
    if not isinstance(normalized.get("summary"), Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon lifecycle event summary is "
                "invalid."
            ),
        )
    normalized["summary"] = dict(normalized["summary"])
    if not isinstance(normalized.get("metadata"), Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon lifecycle event metadata is "
                "invalid."
            ),
        )
    normalized["metadata"] = dict(normalized["metadata"])
    assert_artifact_retention_payload_safe(
        {
            "summary": normalized["summary"],
            "metadata": normalized["metadata"],
        }
    )
    return normalized


def _daemon_lifecycle_event(
    *,
    run_record: Mapping[str, Any],
    execution_result: Mapping[str, Any],
    event_type: str,
    daemon_run_metadata_id: str,
    run_status: str,
    occurred_at: str,
    result_status: str | None,
    stop_reason: str | None,
    cycle_count: int,
) -> dict[str, Any]:
    event = {
        "daemon_lifecycle_event_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_LIFECYCLE_EVENT_SCHEMA_VERSION
        ),
        "daemon_lifecycle_event_id": _daemon_lifecycle_event_id(
            run_record=run_record,
            event_type=event_type,
            daemon_run_metadata_id=daemon_run_metadata_id,
        ),
        "daemon_run_record_id": run_record["daemon_run_record_id"],
        "daemon_cli_execution_result_id": run_record[
            "daemon_cli_execution_result_id"
        ],
        "daemon_run_metadata_id": daemon_run_metadata_id,
        "service_id": "nex-ae-api",
        "scheduler_id": run_record["scheduler_id"],
        "daemon_instance_id": run_record["daemon_instance_id"],
        "event_type": event_type,
        "run_status": run_status,
        "result_status": result_status,
        "stop_reason": stop_reason,
        "cycle_count": cycle_count,
        "occurred_at": occurred_at,
        "process_id": run_record["process_id"],
        "host_id": run_record["host_id"],
        "summary": {
            "scheduler_id": run_record["scheduler_id"],
            "event_type": event_type,
            "run_status": run_status,
            "result_status": result_status,
            "stop_reason": stop_reason,
            "cycle_count": cycle_count,
        },
        "metadata": {
            "safe_for_ag_projection": True,
            "source_execution_result_hash": sha256_json(dict(execution_result)),
            "database_url_included": False,
            "storage_path_included": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_included": False,
            "raw_daemon_runtime_payload_included": False,
            "runtime_state_persisted": False,
            "physical_delete_automation_enabled": False,
        },
        "created_at": run_record["created_at"],
    }
    return event


def _daemon_run_collection_item(record: Mapping[str, Any]) -> dict[str, Any]:
    validated = validate_artifact_retention_scheduler_daemon_run_record(record)
    return {
        "daemon_run_record_id": validated["daemon_run_record_id"],
        "scheduler_id": validated["scheduler_id"],
        "daemon_instance_id": validated["daemon_instance_id"],
        "daemon_cli_execution_result_id": validated[
            "daemon_cli_execution_result_id"
        ],
        "process_id": validated["process_id"],
        "host_id": validated["host_id"],
        "run_status": validated["run_status"],
        "result_status": validated["result_status"],
        "stop_reason": validated["stop_reason"],
        "max_cycles": validated["max_cycles"],
        "cycle_count": validated["cycle_count"],
        "worker_requested": validated["worker_requested"],
        "job_enqueued": validated["job_enqueued"],
        "worker_executed": validated["worker_executed"],
        "started_at": validated["started_at"],
        "completed_at": validated["completed_at"],
        "checked_at": validated["checked_at"],
        "summary": dict(validated["summary"]),
        "metadata": {
            "safe_for_ag_projection": (
                validated["metadata"].get("safe_for_ag_projection") is True
            ),
            "database_url_included": False,
            "storage_path_included": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_included": False,
            "raw_daemon_runtime_payload_included": False,
            "physical_delete_automation_enabled": False,
        },
    }


def _validate_daemon_run_collection_item(item: Any) -> dict[str, Any]:
    error_code = "ae.artifact_retention_scheduler_daemon_run_collection_invalid"
    if not isinstance(item, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon run collection item must be "
                "an object."
            ),
        )
    normalized = dict(item)
    if set(normalized) != {
        "daemon_run_record_id",
        "scheduler_id",
        "daemon_instance_id",
        "daemon_cli_execution_result_id",
        "process_id",
        "host_id",
        "run_status",
        "result_status",
        "stop_reason",
        "max_cycles",
        "cycle_count",
        "worker_requested",
        "job_enqueued",
        "worker_executed",
        "started_at",
        "completed_at",
        "checked_at",
        "summary",
        "metadata",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon run collection item keys are "
                "invalid."
            ),
        )
    for field_name in (
        "daemon_run_record_id",
        "scheduler_id",
        "daemon_instance_id",
        "daemon_cli_execution_result_id",
        "host_id",
        "stop_reason",
        "started_at",
        "completed_at",
        "checked_at",
    ):
        normalized[field_name] = _required_text(
            normalized.get(field_name),
            field_name,
            error_code=error_code,
        )
    normalized["process_id"] = _positive_int(
        normalized.get("process_id"),
        "process_id",
        error_code=error_code,
    )
    normalized["run_status"] = _daemon_run_status(
        normalized.get("run_status"),
        error_code=error_code,
    )
    normalized["result_status"] = _daemon_result_status(
        normalized.get("result_status"),
        error_code=error_code,
    )
    normalized["max_cycles"] = _bounded_positive_int(
        normalized.get("max_cycles"),
        "max_cycles",
        max_value=MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_MAX_CYCLES,
        error_code=error_code,
    )
    normalized["cycle_count"] = _non_negative_int(
        normalized.get("cycle_count"),
        "cycle_count",
        error_code=error_code,
    )
    for field_name in ("worker_requested", "job_enqueued", "worker_executed"):
        normalized[field_name] = _required_bool(
            normalized.get(field_name),
            field_name,
            error_code=error_code,
        )
    if not isinstance(normalized.get("summary"), Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon run collection item summary "
                "is invalid."
            ),
        )
    if not isinstance(normalized.get("metadata"), Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon run collection item metadata "
                "is invalid."
            ),
        )
    normalized["summary"] = dict(normalized["summary"])
    normalized["metadata"] = dict(normalized["metadata"])
    if normalized["metadata"] != {
        "safe_for_ag_projection": True,
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
        "physical_delete_automation_enabled": False,
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon run collection item metadata "
                "is invalid."
            ),
        )
    assert_artifact_retention_payload_safe(normalized)
    return normalized


def _daemon_run_read_model_guardrails() -> dict[str, bool]:
    return {
        "read_only": True,
        "ae_owned_persistence": True,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
        "process_control_allowed": False,
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
        "physical_delete_automation_enabled": False,
    }


def _daemon_run_collection_metadata(
    *,
    records: Sequence[Mapping[str, Any]],
    limit: int,
) -> dict[str, Any]:
    newest_completed_at = records[0]["completed_at"] if records else None
    return {
        "safe_for_ag_projection": True,
        "read_model": "ae_artifact_retention_scheduler_daemon_runs",
        "item_count": len(records),
        "limit": limit,
        "has_more": len(records) == limit,
        "newest_completed_at": newest_completed_at,
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
    }


def _daemon_run_detail_metadata(
    *,
    run_record: Mapping[str, Any],
    lifecycle_events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "safe_for_ag_projection": True,
        "read_model": "ae_artifact_retention_scheduler_daemon_run_detail",
        "daemon_run_record_id": run_record["daemon_run_record_id"],
        "lifecycle_event_count": len(lifecycle_events),
        "event_types": [event["event_type"] for event in lifecycle_events],
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
    }


def summarize_artifact_retention_scheduler_daemon_cli_plan(
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    validated = validate_artifact_retention_scheduler_daemon_cli_plan(plan)
    state_summary = summarize_artifact_retention_scheduler_daemon_runtime_state(
        validated["runtime_state"]
    )
    return {
        "scheduler_id": validated["scheduler_id"],
        "entrypoint": validated["command"]["entrypoint"],
        "profile": validated["command"]["profile"],
        "max_cycles": validated["command"]["max_cycles"],
        "run_worker": validated["command"]["run_worker"],
        "output_format": validated["command"]["output_format"],
        "plan_only": validated["command"]["plan_only"],
        "ready_to_start": validated["metadata"]["ready_to_start"],
        "blocked_by_runtime": validated["metadata"]["blocked_by_runtime"],
        "lifecycle_status": state_summary["lifecycle_status"],
        "lifecycle_reason": state_summary["lifecycle_reason"],
        "bounded_loop_started": validated["guardrails"]["bounded_loop_started"],
        "database_write_performed": validated["guardrails"][
            "database_write_performed"
        ],
        "job_queue_enqueue_performed": validated["guardrails"][
            "job_queue_enqueue_performed"
        ],
    }


def summary_line(plan: Mapping[str, Any]) -> str:
    summary = summarize_artifact_retention_scheduler_daemon_cli_plan(plan)
    return (
        "ae_scheduler_daemon_cli_plan=pass "
        f"scheduler_id={summary['scheduler_id']} "
        f"profile={summary['profile']} "
        f"lifecycle={summary['lifecycle_status']} "
        f"reason={summary['lifecycle_reason']} "
        f"max_cycles={summary['max_cycles']} "
        f"plan_only={int(summary['plan_only'])} "
        f"bounded_loop_started={int(summary['bounded_loop_started'])}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build an AE artifact retention scheduler daemon CLI plan."
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--profile", default="test")
    parser.add_argument("--enabled", action="store_true")
    parser.add_argument("--explicit-opt-in", action="store_true")
    parser.add_argument("--checked-at")
    parser.add_argument("--interval-seconds")
    parser.add_argument("--jitter-seconds")
    parser.add_argument("--backoff-seconds")
    parser.add_argument("--max-cycles", default="1")
    parser.add_argument("--run-worker", action="store_true")
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(
    argv: Sequence[str] | None = None,
    out: TextIO | None = None,
    *,
    execution_context: Mapping[str, Any] | None = None,
) -> int:
    stream = out if out is not None else sys.stdout
    args = build_parser().parse_args(argv)
    try:
        if args.execute:
            result = _run_daemon_cli_execution_from_context(
                args=args,
                execution_context=execution_context,
            )
            output = (
                execution_result_summary_line(result)
                if args.summary
                else json.dumps(result, ensure_ascii=False, sort_keys=True)
            )
        else:
            plan = build_artifact_retention_scheduler_daemon_cli_plan(
                profile=args.profile,
                enabled=args.enabled,
                explicit_opt_in=args.explicit_opt_in,
                checked_at=args.checked_at,
                interval_seconds=args.interval_seconds,
                jitter_seconds=args.jitter_seconds,
                backoff_seconds=args.backoff_seconds,
                max_cycles=args.max_cycles,
                run_worker=args.run_worker,
                output_format="summary" if args.summary else "json",
            )
            output = (
                summary_line(plan)
                if args.summary
                else json.dumps(plan, ensure_ascii=False, sort_keys=True)
            )
    except ArtifactHandoffError as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error_code": exc.error_code,
                    "detail": exc.detail,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=stream,
        )
        return 1
    print(output, file=stream)
    return 0


def _run_daemon_cli_execution_from_context(
    *,
    args: argparse.Namespace,
    execution_context: Mapping[str, Any] | None,
) -> dict[str, Any]:
    context = _daemon_cli_execution_context(execution_context)
    return run_artifact_retention_scheduler_daemon_cli_execution(
        artifact_store=_required_daemon_cli_execution_context_value(
            context,
            "artifact_store",
        ),
        job_queue=_required_daemon_cli_execution_context_value(
            context,
            "job_queue",
        ),
        tenant_id=_required_daemon_cli_execution_context_value(
            context,
            "tenant_id",
        ),
        workspace_id=_required_daemon_cli_execution_context_value(
            context,
            "workspace_id",
        ),
        owner_user_id=_required_daemon_cli_execution_context_value(
            context,
            "owner_user_id",
        ),
        lease_store=context.get("lease_store"),
        history_store=context.get("history_store"),
        run_store=context.get("run_store"),
        scheduler_config=context.get("scheduler_config"),
        profile=args.profile,
        enabled=args.enabled,
        explicit_opt_in=args.explicit_opt_in,
        checked_at=args.checked_at,
        interval_seconds=args.interval_seconds,
        jitter_seconds=args.jitter_seconds,
        backoff_seconds=args.backoff_seconds,
        max_cycles=args.max_cycles,
        run_worker=args.run_worker,
        output_format="summary" if args.summary else "json",
        process_id=context.get("process_id"),
        host_id=context.get("host_id", "localhost"),
        stale_after_seconds=context.get("stale_after_seconds", 600),
        retention_days=context.get("retention_days"),
        as_of=context.get("as_of"),
        scan_limit=context.get("scan_limit"),
        max_delete_count=context.get("max_delete_count"),
        trace_id=context.get("trace_id"),
        request_id=context.get("request_id"),
        idempotency_key=context.get("idempotency_key"),
        worker_id=context.get("worker_id"),
        stop_requested=context.get("stop_requested", False),
        stop_after_cycle=context.get("stop_after_cycle"),
        shutdown_signal_name=context.get("shutdown_signal_name"),
        shutdown_received_at=context.get("shutdown_received_at"),
        clock=context.get("clock"),
        daemon_heartbeat_emitter=context.get("daemon_heartbeat_emitter"),
    )


def _daemon_cli_execution_context(
    execution_context: Mapping[str, Any] | None,
) -> Mapping[str, Any]:
    if not isinstance(execution_context, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_cli_execution_result_invalid",
            detail=(
                "Artifact retention scheduler daemon CLI execution context is "
                "required."
            ),
        )
    return execution_context


def _required_daemon_cli_execution_context_value(
    context: Mapping[str, Any],
    field_name: str,
) -> Any:
    if field_name not in context or context.get(field_name) is None:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_cli_execution_result_invalid",
            detail=(
                "Artifact retention scheduler daemon CLI execution context "
                f"{field_name} is required."
            ),
        )
    return context[field_name]


def _validate_daemon_cli_command(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
            detail="Artifact retention scheduler daemon CLI command is invalid.",
        )
    command = dict(value)
    if set(command) != {
        "entrypoint",
        "profile",
        "enabled",
        "explicit_opt_in",
        "checked_at",
        "max_cycles",
        "run_worker",
        "output_format",
        "plan_only",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
            detail="Artifact retention scheduler daemon CLI command keys are invalid.",
        )
    command["entrypoint"] = _required_text(command.get("entrypoint"), "entrypoint")
    if command["entrypoint"] != DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ENTRYPOINT:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
            detail="Artifact retention scheduler daemon CLI entrypoint is invalid.",
        )
    command["profile"] = _required_text(command.get("profile"), "profile").lower()
    command["enabled"] = _required_bool(command.get("enabled"), "enabled")
    command["explicit_opt_in"] = _required_bool(
        command.get("explicit_opt_in"),
        "explicit_opt_in",
    )
    command["checked_at"] = _required_text(command.get("checked_at"), "checked_at")
    command["max_cycles"] = _bounded_positive_int(
        command.get("max_cycles"),
        "max_cycles",
        max_value=MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_MAX_CYCLES,
    )
    command["run_worker"] = _required_bool(command.get("run_worker"), "run_worker")
    command["output_format"] = _normalize_output_format(command.get("output_format"))
    command["plan_only"] = _required_bool(command.get("plan_only"), "plan_only")
    if command["plan_only"] is not True:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
            detail="Artifact retention scheduler daemon CLI plan-only mode is required.",
        )
    return command


def _validate_daemon_cli_command_matches_runtime(
    *,
    command: Mapping[str, Any],
    runtime_config: Mapping[str, Any],
    error_code: str = "ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
    detail_prefix: str = "Artifact retention scheduler daemon CLI",
) -> None:
    enablement = runtime_config["enablement"]
    if command["profile"] != enablement["profile"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=f"{detail_prefix} profile is invalid.",
        )
    if command["enabled"] != enablement["enabled"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=f"{detail_prefix} enabled flag is invalid.",
        )
    if command["explicit_opt_in"] != enablement["explicit_opt_in"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=f"{detail_prefix} explicit opt-in is invalid.",
        )
    if command["checked_at"] != runtime_config["checked_at"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=f"{detail_prefix} checked_at is invalid.",
        )


def _daemon_cli_execution_plan(
    *,
    run_worker: bool,
    ready_to_start: bool,
) -> dict[str, bool]:
    return {
        "loads_runtime_config": True,
        "validates_daemon_config": True,
        "builds_runtime_state": True,
        "ready_to_start": ready_to_start,
        "plan_only": True,
        "starts_bounded_loop": False,
        "runs_tick_once": False,
        "enqueues_job_queue": False,
        "runs_worker": False,
        "worker_requested_for_future_loop": run_worker,
        "writes_database": False,
        "physical_delete_enabled": False,
    }


def _daemon_cli_guardrails() -> dict[str, bool]:
    return {
        "metadata_only": True,
        "plan_only": True,
        "daemon_process_owner_ae": True,
        "bounded_loop_available": False,
        "bounded_loop_started": False,
        "database_url_required": False,
        "database_write_performed": False,
        "job_queue_enqueue_performed": False,
        "worker_execution_performed": False,
        "runtime_state_persisted": False,
        "physical_delete_automation_enabled": False,
        "secrets_redacted": True,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
    }


def _validate_daemon_cli_execute_command(value: Any) -> dict[str, Any]:
    error_code = "ae.artifact_retention_scheduler_daemon_cli_execute_command_invalid"
    if not isinstance(value, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon CLI execute command "
                "command is invalid."
            ),
        )
    command = dict(value)
    if set(command) != {
        "entrypoint",
        "mode",
        "profile",
        "enabled",
        "explicit_opt_in",
        "checked_at",
        "max_cycles",
        "run_worker",
        "output_format",
        "plan_only",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon CLI execute command "
                "command keys are invalid."
            ),
        )
    command["entrypoint"] = _required_text(
        command.get("entrypoint"),
        "entrypoint",
        error_code=error_code,
    )
    if command["entrypoint"] != DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ENTRYPOINT:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon CLI execute command "
                "entrypoint is invalid."
            ),
        )
    command["mode"] = _required_text(
        command.get("mode"),
        "mode",
        error_code=error_code,
    )
    if command["mode"] != AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_EXECUTE_MODE:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon CLI execute command "
                "mode is invalid."
            ),
        )
    command["profile"] = _required_text(
        command.get("profile"),
        "profile",
        error_code=error_code,
    ).lower()
    if command["profile"] != "test":
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon CLI execute command "
                "profile must be test."
            ),
        )
    command["enabled"] = _required_bool(
        command.get("enabled"),
        "enabled",
        error_code=error_code,
    )
    command["explicit_opt_in"] = _required_bool(
        command.get("explicit_opt_in"),
        "explicit_opt_in",
        error_code=error_code,
    )
    if command["enabled"] is not True or command["explicit_opt_in"] is not True:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon CLI execute command "
                "requires enabled runtime and explicit opt-in."
            ),
        )
    command["checked_at"] = _required_text(
        command.get("checked_at"),
        "checked_at",
        error_code=error_code,
    )
    command["max_cycles"] = _bounded_positive_int(
        command.get("max_cycles"),
        "max_cycles",
        max_value=MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_MAX_CYCLES,
        error_code=error_code,
    )
    command["run_worker"] = _required_bool(
        command.get("run_worker"),
        "run_worker",
        error_code=error_code,
    )
    command["output_format"] = _normalize_output_format(
        command.get("output_format"),
        error_code=error_code,
    )
    command["plan_only"] = _required_bool(
        command.get("plan_only"),
        "plan_only",
        error_code=error_code,
    )
    if command["plan_only"] is not False:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon CLI execute command "
                "requires execute mode."
            ),
        )
    return command


def _daemon_cli_execute_command_execution_plan(
    *,
    run_worker: bool,
) -> dict[str, bool]:
    return {
        "loads_runtime_config": True,
        "validates_daemon_config": True,
        "builds_runtime_state": True,
        "ready_to_start": True,
        "plan_only": False,
        "starts_bounded_loop": True,
        "bounded_loop_is_finite": True,
        "runs_tick_once": True,
        "may_enqueue_job_queue": True,
        "runs_worker": run_worker,
        "worker_execution_requires_flag": True,
        "writes_database": True,
        "database_url_required": True,
        "process_lock_required": True,
        "shutdown_signal_adapter_required": True,
        "physical_delete_enabled": False,
    }


def _daemon_cli_execute_command_guardrails() -> dict[str, bool]:
    return {
        "metadata_only": True,
        "plan_only": False,
        "daemon_process_owner_ae": True,
        "bounded_loop_available": True,
        "bounded_loop_started": False,
        "execution_requires_test_profile": True,
        "execution_requires_explicit_opt_in": True,
        "database_url_required": True,
        "database_url_included": False,
        "database_write_performed": False,
        "job_queue_enqueue_performed": False,
        "worker_execution_performed": False,
        "runtime_state_persisted": False,
        "process_lock_required": True,
        "process_lock_acquired": False,
        "shutdown_signal_adapter_required": True,
        "physical_delete_automation_enabled": False,
        "secrets_redacted": True,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
    }


def _daemon_cli_execute_command_metadata(
    *,
    runtime_config: Mapping[str, Any],
    runtime_state: Mapping[str, Any],
    command: Mapping[str, Any],
) -> dict[str, bool | str]:
    return {
        "metadata_only": True,
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
        "safe_for_ag_projection": True,
        "cli_entrypoint_defined": True,
        "command_mode": command["mode"],
        "runtime_config_validated": True,
        "daemon_config_validated": True,
        "runtime_state_built": True,
        "ready_to_start": runtime_config["enablement"]["enablement_status"] == "READY",
        "blocked_by_runtime": False,
        "plan_only": command["plan_only"] is True,
        "execute_mode": command["plan_only"] is False,
        "summary_requested": command["output_format"] == "summary",
        "bounded_loop_requested": True,
        "bounded_loop_started": False,
        "tick_once_ran": False,
        "job_enqueued": False,
        "worker_executed": False,
        "runtime_state_persisted": False,
        "process_lock_required": True,
        "process_lock_acquired": False,
        "shutdown_signal_adapter_required": True,
        "lifecycle_starting": runtime_state["lifecycle_status"] == "STARTING",
        "lifecycle_disabled": runtime_state["lifecycle_status"] == "DISABLED",
    }


def _validate_daemon_process_lock_process(
    value: Any,
    *,
    error_code: str = "ae.artifact_retention_scheduler_daemon_process_lock_invalid",
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail="Artifact retention scheduler daemon process lock process is invalid.",
        )
    process = dict(value)
    if set(process) != {"process_id", "host_id", "lock_owner", "entrypoint"}:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon process lock process keys "
                "are invalid."
            ),
        )
    process["process_id"] = _bounded_positive_int(
        process.get("process_id"),
        "process_id",
        max_value=MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_PROCESS_ID,
        error_code=error_code,
    )
    process["host_id"] = _required_text(
        process.get("host_id"),
        "host_id",
        error_code=error_code,
    )
    process["lock_owner"] = _required_text(
        process.get("lock_owner"),
        "lock_owner",
        error_code=error_code,
    )
    process["entrypoint"] = _required_text(
        process.get("entrypoint"),
        "entrypoint",
        error_code=error_code,
    )
    if process["entrypoint"] != DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ENTRYPOINT:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon process lock entrypoint "
                "is invalid."
            ),
        )
    return process


def _validate_daemon_process_lock_timing(value: Any) -> dict[str, Any]:
    error_code = "ae.artifact_retention_scheduler_daemon_process_lock_invalid"
    if not isinstance(value, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail="Artifact retention scheduler daemon process lock timing is invalid.",
        )
    timing = dict(value)
    if set(timing) != {"requested_at", "stale_after_seconds"}:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon process lock timing keys "
                "are invalid."
            ),
        )
    timing["requested_at"] = _required_text(
        timing.get("requested_at"),
        "requested_at",
        error_code=error_code,
    )
    timing["stale_after_seconds"] = _bounded_positive_int(
        timing.get("stale_after_seconds"),
        "stale_after_seconds",
        max_value=(
            MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_PROCESS_LOCK_STALE_AFTER_SECONDS
        ),
        error_code=error_code,
    )
    return timing


def _validate_daemon_execute_command_summary(
    value: Any,
    *,
    error_code: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail="Artifact retention scheduler daemon command summary is invalid.",
        )
    summary = dict(value)
    if set(summary) != {"mode", "max_cycles", "run_worker", "plan_only"}:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon command summary keys are "
                "invalid."
            ),
        )
    summary["mode"] = _required_text(
        summary.get("mode"),
        "mode",
        error_code=error_code,
    )
    if summary["mode"] != AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_EXECUTE_MODE:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail="Artifact retention scheduler daemon command summary mode is invalid.",
        )
    summary["max_cycles"] = _bounded_positive_int(
        summary.get("max_cycles"),
        "max_cycles",
        max_value=MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_MAX_CYCLES,
        error_code=error_code,
    )
    summary["run_worker"] = _required_bool(
        summary.get("run_worker"),
        "run_worker",
        error_code=error_code,
    )
    summary["plan_only"] = _required_bool(
        summary.get("plan_only"),
        "plan_only",
        error_code=error_code,
    )
    if summary["plan_only"] is not False:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon command summary execute "
                "mode is invalid."
            ),
        )
    return summary


def _validate_daemon_run_metadata_lifecycle(
    value: Any,
    *,
    error_code: str = "ae.artifact_retention_scheduler_daemon_run_metadata_invalid",
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail="Artifact retention scheduler daemon run lifecycle is invalid.",
        )
    lifecycle = dict(value)
    if set(lifecycle) != {"run_status", "requested_at", "started_at", "completed_at"}:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon run lifecycle keys are "
                "invalid."
            ),
        )
    status = _required_text(
        lifecycle.get("run_status"),
        "run_status",
        error_code=error_code,
    ).upper()
    if status not in AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUN_STATUSES:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail="Artifact retention scheduler daemon run status is invalid.",
        )
    requested_at = _required_text(
        lifecycle.get("requested_at"),
        "requested_at",
        error_code=error_code,
    )
    started_at = optional_text(lifecycle.get("started_at"))
    completed_at = optional_text(lifecycle.get("completed_at"))
    if status == "PENDING" and (started_at is not None or completed_at is not None):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail="Artifact retention scheduler daemon pending run timestamps are invalid.",
        )
    if status in {"RUNNING", "STOPPING"} and (
        started_at is None or completed_at is not None
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon active run timestamps are "
                "invalid."
            ),
        )
    if status in {"SUCCEEDED", "FAILED"} and (
        started_at is None or completed_at is None
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon completed run timestamps "
                "are invalid."
            ),
        )
    return {
        "run_status": status,
        "requested_at": requested_at,
        "started_at": started_at,
        "completed_at": completed_at,
    }


def _ensure_daemon_run_metadata_scope(
    *,
    execute_command: Mapping[str, Any],
    process_lock: Mapping[str, Any],
) -> None:
    if execute_command["scheduler_id"] != process_lock["scheduler_id"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_run_metadata_invalid",
            detail="Artifact retention scheduler daemon run metadata scope is invalid.",
        )
    if (
        execute_command["daemon_cli_execute_command_id"]
        != process_lock["daemon_cli_execute_command_id"]
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_run_metadata_invalid",
            detail=(
                "Artifact retention scheduler daemon run metadata command scope "
                "is invalid."
            ),
        )


def _ensure_daemon_signal_shutdown_adapter_scope(
    *,
    current_state: Mapping[str, Any],
    process_lock: Mapping[str, Any],
    run_metadata: Mapping[str, Any],
) -> None:
    if current_state["scheduler_id"] != process_lock["scheduler_id"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_signal_shutdown_adapter_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon signal shutdown adapter lock "
                "scope is invalid."
            ),
        )
    if current_state["scheduler_id"] != run_metadata["scheduler_id"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_signal_shutdown_adapter_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon signal shutdown adapter run "
                "scope is invalid."
            ),
        )
    if process_lock["daemon_process_lock_id"] != run_metadata["daemon_process_lock_id"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_signal_shutdown_adapter_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon signal shutdown adapter "
                "process lock scope is invalid."
            ),
        )
    if (
        process_lock["daemon_cli_execute_command_id"]
        != run_metadata["daemon_cli_execute_command_id"]
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_signal_shutdown_adapter_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon signal shutdown adapter "
                "command scope is invalid."
            ),
        )


def _daemon_execute_command_summary(
    execute_command: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "mode": execute_command["command"]["mode"],
        "max_cycles": execute_command["command"]["max_cycles"],
        "run_worker": execute_command["command"]["run_worker"],
        "plan_only": execute_command["command"]["plan_only"],
    }


def _normalize_daemon_shutdown_signal_name(value: Any) -> str:
    signal_name = _required_text(
        value,
        "signal_name",
        error_code="ae.artifact_retention_scheduler_daemon_signal_shutdown_adapter_invalid",
    ).upper()
    if signal_name not in AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SHUTDOWN_SIGNALS:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_signal_shutdown_adapter_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon signal shutdown adapter "
                "signal is invalid."
            ),
        )
    return signal_name


def _validate_daemon_signal_shutdown_adapter_signal(value: Any) -> dict[str, Any]:
    error_code = "ae.artifact_retention_scheduler_daemon_signal_shutdown_adapter_invalid"
    if not isinstance(value, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon signal shutdown adapter "
                "signal is invalid."
            ),
        )
    signal = dict(value)
    if set(signal) != {"signal_name", "received_at", "handler"}:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon signal shutdown adapter "
                "signal keys are invalid."
            ),
        )
    signal["signal_name"] = _normalize_daemon_shutdown_signal_name(
        signal.get("signal_name")
    )
    signal["received_at"] = _required_text(
        signal.get("received_at"),
        "received_at",
        error_code=error_code,
    )
    signal["handler"] = _required_text(
        signal.get("handler"),
        "handler",
        error_code=error_code,
    )
    if signal["handler"] != "deferred_cli_signal_adapter":
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon signal shutdown adapter "
                "handler is invalid."
            ),
        )
    return signal


def _daemon_signal_shutdown_adapter_execution_plan(
    *,
    shutdown_transition: Mapping[str, Any],
) -> dict[str, bool]:
    transition_plan = shutdown_transition["execution_plan"]
    return {
        "signal_observed": True,
        "signal_handler_installed": False,
        "builds_shutdown_transition": True,
        "stop_signal_requested": transition_plan["stop_signal_requested"],
        "bounded_loop_should_stop_before_next_cycle": transition_plan[
            "bounded_loop_should_stop_before_next_cycle"
        ],
        "stop_signal_delivered": False,
        "writes_database": False,
        "enqueues_job_queue": False,
        "runs_worker": False,
        "physical_delete_enabled": False,
    }


def _daemon_signal_shutdown_adapter_guardrails() -> dict[str, bool]:
    return {
        "metadata_only": True,
        "signal_handler_installed": False,
        "stop_signal_delivered": False,
        "process_terminated": False,
        "database_url_included": False,
        "database_write_performed": False,
        "job_queue_enqueue_performed": False,
        "worker_execution_performed": False,
        "runtime_state_persisted": False,
        "physical_delete_automation_enabled": False,
        "secrets_redacted": True,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
    }


def _daemon_signal_shutdown_adapter_metadata(
    *,
    signal: Mapping[str, Any],
    process: Mapping[str, Any],
    run_lifecycle: Mapping[str, Any],
    shutdown_transition: Mapping[str, Any],
) -> dict[str, bool | int | str]:
    return {
        "safe_for_ag_projection": True,
        "metadata_only": True,
        "signal_name": signal["signal_name"],
        "process_id": process["process_id"],
        "host_id": process["host_id"],
        "run_status": run_lifecycle["run_status"],
        "transition_decision_status": shutdown_transition["decision_status"],
        "transition_decision_reason": shutdown_transition["decision_reason"],
        "shutdown_requested": shutdown_transition["metadata"]["shutdown_requested"],
        "stop_signal_requested": shutdown_transition["execution_plan"][
            "stop_signal_requested"
        ],
        "signal_handler_installed": False,
        "stop_signal_delivered": False,
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
        "runtime_state_persisted": False,
    }


def _validate_optional_daemon_signal_shutdown_adapter(
    value: Any,
) -> dict[str, Any] | None:
    if value is None:
        return None
    return validate_artifact_retention_scheduler_daemon_signal_shutdown_adapter(value)


def _ensure_daemon_cli_execution_result_scope(
    *,
    scheduler_id: str,
    command_id: str,
    process_lock_id: str,
    started_run_id: str,
    completed_run_id: str,
    execute_command: Mapping[str, Any],
    process_lock: Mapping[str, Any],
    started_run_metadata: Mapping[str, Any],
    completed_run_metadata: Mapping[str, Any],
    bounded_loop_result: Mapping[str, Any],
    shutdown_signal_adapter: Mapping[str, Any] | None,
) -> None:
    error_code = "ae.artifact_retention_scheduler_daemon_cli_execution_result_invalid"
    if execute_command["scheduler_id"] != scheduler_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon CLI execution result command "
                "scope is invalid."
            ),
        )
    if execute_command["daemon_cli_execute_command_id"] != command_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon CLI execution result command "
                "id is invalid."
            ),
        )
    if process_lock["scheduler_id"] != scheduler_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon CLI execution result process "
                "scope is invalid."
            ),
        )
    if process_lock["daemon_process_lock_id"] != process_lock_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon CLI execution result process "
                "lock id is invalid."
            ),
        )
    if process_lock["daemon_cli_execute_command_id"] != command_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon CLI execution result process "
                "command scope is invalid."
            ),
        )
    _ensure_daemon_cli_execution_run_scope(
        label="started",
        scheduler_id=scheduler_id,
        command_id=command_id,
        process_lock_id=process_lock_id,
        expected_run_id=started_run_id,
        run_metadata=started_run_metadata,
    )
    _ensure_daemon_cli_execution_run_scope(
        label="completed",
        scheduler_id=scheduler_id,
        command_id=command_id,
        process_lock_id=process_lock_id,
        expected_run_id=completed_run_id,
        run_metadata=completed_run_metadata,
    )
    started_lifecycle = started_run_metadata["lifecycle"]
    completed_lifecycle = completed_run_metadata["lifecycle"]
    if started_lifecycle["run_status"] != "RUNNING":
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon CLI execution result started "
                "run status is invalid."
            ),
        )
    expected_completed_status = _daemon_cli_execution_completed_run_status(
        bounded_loop_result
    )
    if completed_lifecycle["run_status"] != expected_completed_status:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon CLI execution result completed "
                "run status is invalid."
            ),
        )
    if completed_lifecycle["requested_at"] != started_lifecycle["requested_at"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon CLI execution result lifecycle "
                "request scope is invalid."
            ),
        )
    if completed_lifecycle["started_at"] != started_lifecycle["started_at"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon CLI execution result lifecycle "
                "start scope is invalid."
            ),
        )
    if completed_lifecycle["completed_at"] != bounded_loop_result["finished_at"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon CLI execution result lifecycle "
                "completion time is invalid."
            ),
        )
    command = execute_command["command"]
    if bounded_loop_result["scheduler_id"] != scheduler_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon CLI execution result bounded "
                "loop scope is invalid."
            ),
        )
    if bounded_loop_result["started_at"] != command["checked_at"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon CLI execution result bounded "
                "loop start time is invalid."
            ),
        )
    if bounded_loop_result["max_cycles"] != command["max_cycles"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon CLI execution result bounded "
                "loop max_cycles is invalid."
            ),
        )
    if bounded_loop_result["worker_requested"] != command["run_worker"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon CLI execution result bounded "
                "loop worker flag is invalid."
            ),
        )
    if shutdown_signal_adapter is not None:
        if shutdown_signal_adapter["scheduler_id"] != scheduler_id:
            raise ArtifactHandoffError(
                status_code=422,
                error_code=error_code,
                detail=(
                    "Artifact retention scheduler daemon CLI execution result "
                    "shutdown signal scope is invalid."
                ),
            )
        if shutdown_signal_adapter["daemon_run_id"] != started_run_id:
            raise ArtifactHandoffError(
                status_code=422,
                error_code=error_code,
                detail=(
                    "Artifact retention scheduler daemon CLI execution result "
                    "shutdown signal run scope is invalid."
                ),
            )
        if bounded_loop_result["stop_reason"] != "stop_requested":
            raise ArtifactHandoffError(
                status_code=422,
                error_code=error_code,
                detail=(
                    "Artifact retention scheduler daemon CLI execution result "
                    "shutdown signal stop reason is invalid."
                ),
            )


def _ensure_daemon_cli_execution_run_scope(
    *,
    label: str,
    scheduler_id: str,
    command_id: str,
    process_lock_id: str,
    expected_run_id: str,
    run_metadata: Mapping[str, Any],
) -> None:
    error_code = "ae.artifact_retention_scheduler_daemon_cli_execution_result_invalid"
    if run_metadata["scheduler_id"] != scheduler_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon CLI execution result "
                f"{label} run scope is invalid."
            ),
        )
    if run_metadata["daemon_cli_execute_command_id"] != command_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon CLI execution result "
                f"{label} run command scope is invalid."
            ),
        )
    if run_metadata["daemon_process_lock_id"] != process_lock_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon CLI execution result "
                f"{label} run process scope is invalid."
            ),
        )
    if run_metadata["daemon_run_id"] != expected_run_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon CLI execution result "
                f"{label} run id is invalid."
            ),
        )


def _daemon_cli_execution_completed_run_status(
    bounded_loop_result: Mapping[str, Any],
) -> str:
    if bounded_loop_result["result_status"] == "FAILED":
        return "FAILED"
    return "SUCCEEDED"


def _daemon_cli_execution_result_execution_plan(
    *,
    bounded_loop_result: Mapping[str, Any],
    shutdown_signal_adapter: Mapping[str, Any] | None,
    run_record_persisted: bool = False,
    lifecycle_event_persisted: bool = False,
) -> dict[str, bool | int]:
    bounded_plan = bounded_loop_result["execution_plan"]
    bounded_metadata = bounded_loop_result["metadata"]
    normalized_run_record_persisted = _required_bool(
        run_record_persisted,
        "run_record_persisted",
        error_code="ae.artifact_retention_scheduler_daemon_cli_execution_result_invalid",
    )
    normalized_lifecycle_event_persisted = _required_bool(
        lifecycle_event_persisted,
        "lifecycle_event_persisted",
        error_code="ae.artifact_retention_scheduler_daemon_cli_execution_result_invalid",
    )
    return {
        "loads_execute_command": True,
        "builds_process_lock_metadata": True,
        "builds_started_run_metadata": True,
        "runs_existing_bounded_loop_adapter": True,
        "max_cycles_enforced": bounded_plan["max_cycles_enforced"],
        "cycles_executed": bounded_loop_result["cycle_count"],
        "stop_after_cycle_supported": True,
        "shutdown_signal_adapter_available": True,
        "shutdown_signal_adapter_invoked": shutdown_signal_adapter is not None,
        "job_queue_enqueue_performed": bounded_metadata["job_enqueued"],
        "worker_execution_performed": bounded_metadata["worker_executed"],
        "writes_run_record": normalized_run_record_persisted,
        "writes_lifecycle_event": normalized_lifecycle_event_persisted,
        "runtime_state_persisted": False,
        "physical_delete_enabled": False,
    }


def _daemon_cli_execution_result_guardrails(
    *,
    run_record_persisted: bool = False,
    lifecycle_event_persisted: bool = False,
) -> dict[str, bool]:
    normalized_run_record_persisted = _required_bool(
        run_record_persisted,
        "run_record_persisted",
        error_code="ae.artifact_retention_scheduler_daemon_cli_execution_result_invalid",
    )
    normalized_lifecycle_event_persisted = _required_bool(
        lifecycle_event_persisted,
        "lifecycle_event_persisted",
        error_code="ae.artifact_retention_scheduler_daemon_cli_execution_result_invalid",
    )
    return {
        "daemon_process_owner_ae": True,
        "execute_requires_test_profile": True,
        "execute_requires_explicit_opt_in": True,
        "bounded_loop_is_finite": True,
        "max_cycles_hard_cap_enforced": True,
        "process_lock_required": True,
        "process_lock_acquired": False,
        "run_metadata_required": True,
        "run_record_persisted": normalized_run_record_persisted,
        "lifecycle_event_persisted": normalized_lifecycle_event_persisted,
        "shutdown_signal_adapter_available": True,
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
        "runtime_state_persisted": False,
        "physical_delete_automation_enabled": False,
        "secrets_redacted": True,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
    }


def _daemon_cli_execution_result_metadata(
    *,
    process_lock: Mapping[str, Any],
    started_run_metadata: Mapping[str, Any],
    completed_run_metadata: Mapping[str, Any],
    bounded_loop_result: Mapping[str, Any],
    shutdown_signal_adapter: Mapping[str, Any] | None,
    run_record_persisted: bool = False,
    lifecycle_event_persisted: bool = False,
) -> dict[str, bool | int | str]:
    bounded_metadata = bounded_loop_result["metadata"]
    normalized_run_record_persisted = _required_bool(
        run_record_persisted,
        "run_record_persisted",
        error_code="ae.artifact_retention_scheduler_daemon_cli_execution_result_invalid",
    )
    normalized_lifecycle_event_persisted = _required_bool(
        lifecycle_event_persisted,
        "lifecycle_event_persisted",
        error_code="ae.artifact_retention_scheduler_daemon_cli_execution_result_invalid",
    )
    return {
        "safe_for_ag_projection": True,
        "execute_mode": True,
        "bounded_loop_started": bounded_metadata["bounded_loop_started"],
        "bounded_loop_result_status": bounded_loop_result["result_status"],
        "bounded_loop_stop_reason": bounded_loop_result["stop_reason"],
        "cycle_count": bounded_loop_result["cycle_count"],
        "max_cycles": bounded_loop_result["max_cycles"],
        "job_enqueued": bounded_metadata["job_enqueued"],
        "worker_executed": bounded_metadata["worker_executed"],
        "run_started": started_run_metadata["lifecycle"]["started_at"] is not None,
        "run_completed": completed_run_metadata["lifecycle"]["completed_at"] is not None,
        "completed_run_status": completed_run_metadata["lifecycle"]["run_status"],
        "process_id": process_lock["process"]["process_id"],
        "host_id": process_lock["process"]["host_id"],
        "shutdown_signal_adapter_invoked": shutdown_signal_adapter is not None,
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
        "run_record_persisted": normalized_run_record_persisted,
        "lifecycle_event_persisted": normalized_lifecycle_event_persisted,
        "runtime_state_persisted": False,
    }


def _normalize_daemon_supervisor_action(value: Any) -> str:
    action = _required_text(
        value,
        "action",
        error_code="ae.artifact_retention_scheduler_daemon_supervisor_command_invalid",
    ).lower()
    if action not in AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_ACTIONS:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_supervisor_command_invalid",
            detail=(
                "Artifact retention scheduler daemon supervisor command action "
                "is invalid."
            ),
        )
    return action


def _normalize_daemon_operator_control_action(value: Any) -> str:
    action = _required_text(
        value,
        "action",
        error_code="ae.artifact_retention_scheduler_daemon_operator_control_request_invalid",
    ).lower()
    if action not in AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_ACTIONS:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_operator_control_request_invalid",
            detail=(
                "Artifact retention scheduler daemon operator control request "
                "action is invalid."
            ),
        )
    return action


def _normalize_daemon_operator_control_profile(
    value: Any,
    *,
    error_code: str,
) -> str:
    profile = _required_text(value, "profile", error_code=error_code).lower()
    if profile != "test":
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control request "
                "profile must be test."
            ),
        )
    return profile


def _operator_control_supported_actions() -> list[dict[str, Any]]:
    return [
        {
            "action": "status_probe",
            "mutates_process": False,
            "requires_approval": False,
            "requires_running_process": False,
            "starts_process": False,
            "stops_process": False,
        },
        {
            "action": "start_daemon",
            "mutates_process": True,
            "requires_approval": True,
            "requires_running_process": False,
            "starts_process": True,
            "stops_process": False,
        },
        {
            "action": "stop_daemon",
            "mutates_process": True,
            "requires_approval": False,
            "requires_running_process": True,
            "starts_process": False,
            "stops_process": True,
        },
        {
            "action": "restart_daemon",
            "mutates_process": True,
            "requires_approval": True,
            "requires_running_process": True,
            "starts_process": True,
            "stops_process": True,
        },
    ]


def _operator_control_policy_guardrails() -> dict[str, bool]:
    return {
        "metadata_only": True,
        "operator_subject_required": True,
        "idempotency_key_required": True,
        "operator_reason_required": True,
        "approval_required_for_start_restart": True,
        "test_profile_required": True,
        "explicit_opt_in_required_for_start_restart": True,
        "bounded_max_cycles_required": True,
        "status_probe_before_mutation_required": True,
        "restart_is_stop_then_start": True,
        "production_continuous_start_enabled": False,
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
        "raw_supervised_process_snapshot_included": False,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
        "ag_direct_process_control_allowed": False,
        "physical_delete_automation_enabled": False,
    }


def _operator_control_policy_metadata() -> dict[str, bool]:
    return {
        "safe_for_ag_projection": True,
        "metadata_only": True,
        "policy_contract_only": True,
        "subprocess_started": False,
        "subprocess_stopped": False,
        "database_write_performed": False,
        "job_queue_enqueue_performed": False,
        "worker_execution_performed": False,
        "secrets_redacted": True,
    }


def _operator_control_execution_intent(*, action: str) -> dict[str, bool | str]:
    mutates = action in AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_MUTATING_ACTIONS
    return {
        "action": action,
        "mutates_process": mutates,
        "reads_status": action == "status_probe",
        "requests_start": action in {"start_daemon", "restart_daemon"},
        "requests_stop": action in {"stop_daemon", "restart_daemon"},
        "restart_decomposes_to_stop_then_start": action == "restart_daemon",
        "requires_running_process": action in {"stop_daemon", "restart_daemon"},
        "requires_bounded_subprocess_adapter": action
        in {"start_daemon", "restart_daemon"},
        "starts_continuous_loop": False,
        "enqueues_job_queue": False,
        "runs_worker": False,
        "physical_delete_enabled": False,
    }


def _operator_control_request_guardrails(*, action: str) -> dict[str, bool]:
    return {
        "metadata_only": True,
        "operator_subject_required": True,
        "idempotency_key_required": True,
        "operator_reason_required": True,
        "approval_required": action in {"start_daemon", "restart_daemon"},
        "test_profile_required": True,
        "explicit_opt_in_required": action in {"start_daemon", "restart_daemon"},
        "bounded_max_cycles_required": True,
        "status_probe_before_mutation_required": action
        in AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_MUTATING_ACTIONS,
        "restart_is_stop_then_start": action == "restart_daemon",
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
        "raw_supervised_process_snapshot_included": False,
        "subprocess_started": False,
        "subprocess_stopped": False,
        "production_continuous_start_enabled": False,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
        "ag_direct_process_control_allowed": False,
        "physical_delete_automation_enabled": False,
    }


def _operator_control_request_metadata(
    *,
    action: str,
    approval: Mapping[str, Any] | None,
) -> dict[str, bool]:
    approval_required = action in {"start_daemon", "restart_daemon"}
    return {
        "safe_for_ag_projection": True,
        "metadata_only": True,
        "policy_contract_only": True,
        "approval_required": approval_required,
        "approval_granted": bool(approval and approval.get("approved") is True),
        "mutating_action": action
        in AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_MUTATING_ACTIONS,
        "restart_requested": action == "restart_daemon",
        "subprocess_started": False,
        "subprocess_stopped": False,
        "database_write_performed": False,
        "job_queue_enqueue_performed": False,
        "worker_execution_performed": False,
        "secrets_redacted": True,
    }


def _normalize_operator_control_admission_status(
    value: Any,
    *,
    error_code: str,
) -> str:
    status = _required_text(
        value,
        "admission_status",
        error_code=error_code,
    ).upper()
    if (
        status
        not in AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_ADMISSION_STATUSES
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control "
                "admission status is invalid."
            ),
        )
    return status


def _operator_control_current_process(
    value: Any,
    *,
    requested_at: str,
    error_code: str,
) -> dict[str, Any]:
    if value is None:
        return _operator_control_current_process_from_parts(
            process_source="none",
            process_status="MISSING",
            daemon_supervised_process_id=None,
            daemon_supervisor_command_id=None,
            process_id=None,
            host_id=None,
            observed_at=requested_at,
            error_code=error_code,
        )
    if not isinstance(value, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control "
                "admission current process is invalid."
            ),
        )
    process = dict(value)
    if "daemon_supervised_process_schema_version" in process:
        return _operator_control_current_process_from_snapshot(
            process,
            process_source="snapshot",
            error_code=error_code,
        )
    nested_snapshot = process.get("supervised_process_snapshot")
    if isinstance(nested_snapshot, Mapping):
        return _operator_control_current_process_from_snapshot(
            nested_snapshot,
            process_source="record",
            error_code=error_code,
        )
    expected_keys = {
        "process_source",
        "process_status",
        "process_running",
        "daemon_supervised_process_id",
        "daemon_supervisor_command_id",
        "process_id",
        "host_id",
        "observed_at",
    }
    if set(process) == expected_keys:
        return _operator_control_current_process_from_parts(
            process_source=process.get("process_source"),
            process_status=process.get("process_status"),
            daemon_supervised_process_id=process.get("daemon_supervised_process_id"),
            daemon_supervisor_command_id=process.get("daemon_supervisor_command_id"),
            process_id=process.get("process_id"),
            host_id=process.get("host_id"),
            observed_at=process.get("observed_at"),
            expected_process_running=process.get("process_running"),
            error_code=error_code,
        )
    if "process_source" in process:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control "
                "admission current process keys are invalid."
            ),
        )
    if "process_status" in process:
        return _operator_control_current_process_from_parts(
            process_source="read_model",
            process_status=process.get("process_status"),
            daemon_supervised_process_id=process.get("daemon_supervised_process_id"),
            daemon_supervisor_command_id=process.get("daemon_supervisor_command_id"),
            process_id=process.get("process_id"),
            host_id=process.get("host_id"),
            observed_at=process.get("observed_at") or requested_at,
            error_code=error_code,
        )
    raise ArtifactHandoffError(
        status_code=422,
        error_code=error_code,
        detail=(
            "Artifact retention scheduler daemon operator control admission "
            "current process keys are invalid."
        ),
    )


def _operator_control_current_process_from_snapshot(
    snapshot: Mapping[str, Any],
    *,
    process_source: str,
    error_code: str,
) -> dict[str, Any]:
    try:
        validated = (
            validate_artifact_retention_scheduler_daemon_supervised_process_snapshot(
                snapshot
            )
        )
    except ArtifactHandoffError as exc:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control "
                "admission current process snapshot is invalid."
            ),
        ) from exc
    return _operator_control_current_process_from_parts(
        process_source=process_source,
        process_status=validated["lifecycle"]["process_status"],
        daemon_supervised_process_id=validated["daemon_supervised_process_id"],
        daemon_supervisor_command_id=validated["daemon_supervisor_command_id"],
        process_id=validated["process"]["process_id"],
        host_id=validated["process"]["host_id"],
        observed_at=validated["lifecycle"]["observed_at"],
        error_code=error_code,
    )


def _operator_control_current_process_from_parts(
    *,
    process_source: Any,
    process_status: Any,
    daemon_supervised_process_id: Any,
    daemon_supervisor_command_id: Any,
    process_id: Any,
    host_id: Any,
    observed_at: Any,
    error_code: str,
    expected_process_running: Any = None,
) -> dict[str, Any]:
    source = _required_text(
        process_source,
        "process_source",
        error_code=error_code,
    )
    if source not in {"none", "snapshot", "record", "read_model"}:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control "
                "admission current process source is invalid."
            ),
        )
    status = _normalize_daemon_supervised_process_status(
        process_status,
        error_code=error_code,
    )
    normalized_process_id = _optional_daemon_supervised_process_id(
        process_id,
        error_code=error_code,
    )
    process_running = status in {"RUNNING", "STOP_REQUESTED", "STALE"}
    if expected_process_running is not None and (
        _required_bool(
            expected_process_running,
            "process_running",
            error_code=error_code,
        )
        is not process_running
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control "
                "admission current process running flag is invalid."
            ),
        )
    if source == "none" and (
        status != "MISSING"
        or daemon_supervised_process_id is not None
        or daemon_supervisor_command_id is not None
        or normalized_process_id is not None
        or host_id is not None
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control "
                "admission empty current process is invalid."
            ),
        )
    if status in {"RUNNING", "STOP_REQUESTED", "STOPPED", "EXITED", "STALE", "FAILED"}:
        if normalized_process_id is None:
            raise ArtifactHandoffError(
                status_code=422,
                error_code=error_code,
                detail=(
                    "Artifact retention scheduler daemon operator control "
                    "admission current process id is required."
                ),
            )
    return {
        "process_source": source,
        "process_status": status,
        "process_running": process_running,
        "daemon_supervised_process_id": optional_text(daemon_supervised_process_id),
        "daemon_supervisor_command_id": optional_text(daemon_supervisor_command_id),
        "process_id": normalized_process_id,
        "host_id": optional_text(host_id),
        "observed_at": _required_text(
            observed_at,
            "observed_at",
            error_code=error_code,
        ),
    }


def _operator_control_admission_decision(
    *,
    action: str,
    process_status: str,
) -> dict[str, str]:
    if action == "status_probe":
        return {
            "admission_status": "READY",
            "decision_reason": "status_probe_allowed",
        }
    if action == "start_daemon":
        return _operator_control_start_admission_decision(process_status)
    if action == "stop_daemon":
        return _operator_control_stop_admission_decision(process_status)
    if action == "restart_daemon":
        return _operator_control_restart_admission_decision(process_status)
    raise ArtifactHandoffError(
        status_code=422,
        error_code="ae.artifact_retention_scheduler_daemon_operator_control_admission_invalid",
        detail=(
            "Artifact retention scheduler daemon operator control admission "
            "action is invalid."
        ),
    )


def _operator_control_start_admission_decision(process_status: str) -> dict[str, str]:
    if process_status in {"MISSING", "STOPPED", "EXITED"}:
        return {
            "admission_status": "READY",
            "decision_reason": "start_allowed_no_running_process",
        }
    if process_status == "RUNNING":
        return {
            "admission_status": "NOOP",
            "decision_reason": "daemon_already_running",
        }
    if process_status == "STALE":
        return {
            "admission_status": "BLOCKED",
            "decision_reason": "stale_process_requires_stop_or_review",
        }
    if process_status == "START_REQUESTED":
        return {
            "admission_status": "BLOCKED",
            "decision_reason": "start_already_requested",
        }
    if process_status == "STOP_REQUESTED":
        return {
            "admission_status": "BLOCKED",
            "decision_reason": "stop_in_progress",
        }
    return {
        "admission_status": "BLOCKED",
        "decision_reason": "process_state_requires_review",
    }


def _operator_control_stop_admission_decision(process_status: str) -> dict[str, str]:
    if process_status in {"RUNNING", "STALE", "START_REQUESTED"}:
        return {
            "admission_status": "READY",
            "decision_reason": "stop_allowed_for_observed_process",
        }
    if process_status == "STOP_REQUESTED":
        return {
            "admission_status": "BLOCKED",
            "decision_reason": "stop_already_requested",
        }
    if process_status in {"MISSING", "STOPPED", "EXITED"}:
        return {
            "admission_status": "NOOP",
            "decision_reason": "daemon_not_running",
        }
    return {
        "admission_status": "BLOCKED",
        "decision_reason": "process_state_requires_review",
    }


def _operator_control_restart_admission_decision(
    process_status: str,
) -> dict[str, str]:
    if process_status in {"RUNNING", "STALE"}:
        return {
            "admission_status": "READY",
            "decision_reason": "restart_allowed_stop_then_start",
        }
    if process_status == "START_REQUESTED":
        return {
            "admission_status": "BLOCKED",
            "decision_reason": "start_in_progress",
        }
    if process_status == "STOP_REQUESTED":
        return {
            "admission_status": "BLOCKED",
            "decision_reason": "stop_in_progress",
        }
    if process_status in {"MISSING", "STOPPED", "EXITED"}:
        return {
            "admission_status": "BLOCKED",
            "decision_reason": "restart_requires_running_process",
        }
    return {
        "admission_status": "BLOCKED",
        "decision_reason": "process_state_requires_review",
    }


def _operator_control_admission_next_supervisor_actions(
    *,
    action: str,
    admission_status: str,
) -> list[dict[str, Any]]:
    if admission_status != "READY":
        return []
    if action == "status_probe":
        return [
            _operator_control_next_supervisor_action(
                sequence=1,
                action="status_probe",
                requires_distinct_evidence=False,
                requires_follow_up_admission=False,
            )
        ]
    if action == "start_daemon":
        return [
            _operator_control_next_supervisor_action(
                sequence=1,
                action="start_daemon",
                requires_distinct_evidence=True,
                requires_follow_up_admission=False,
            )
        ]
    if action == "stop_daemon":
        return [
            _operator_control_next_supervisor_action(
                sequence=1,
                action="stop_daemon",
                requires_distinct_evidence=True,
                requires_follow_up_admission=False,
            )
        ]
    if action == "restart_daemon":
        return [
            _operator_control_next_supervisor_action(
                sequence=1,
                action="stop_daemon",
                requires_distinct_evidence=True,
                requires_follow_up_admission=False,
            ),
            _operator_control_next_supervisor_action(
                sequence=2,
                action="start_daemon",
                requires_distinct_evidence=True,
                requires_follow_up_admission=True,
            ),
        ]
    return []


def _operator_control_next_supervisor_action(
    *,
    sequence: int,
    action: str,
    requires_distinct_evidence: bool,
    requires_follow_up_admission: bool,
) -> dict[str, Any]:
    return {
        "sequence": sequence,
        "action": action,
        "mutates_process": action in {"start_daemon", "stop_daemon"},
        "requires_distinct_evidence": requires_distinct_evidence,
        "requires_follow_up_admission": requires_follow_up_admission,
    }


def _validate_operator_control_admission_next_supervisor_actions(
    value: Any,
    *,
    error_code: str,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control "
                "admission supervisor actions must be a list."
            ),
        )
    actions: list[dict[str, Any]] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, Mapping) or set(item) != {
            "sequence",
            "action",
            "mutates_process",
            "requires_distinct_evidence",
            "requires_follow_up_admission",
        }:
            raise ArtifactHandoffError(
                status_code=422,
                error_code=error_code,
                detail=(
                    "Artifact retention scheduler daemon operator control "
                    "admission supervisor action keys are invalid."
                ),
            )
        action = _daemon_supervisor_action_for_context(
            item.get("action"),
            error_code=error_code,
        )
        normalized = _operator_control_next_supervisor_action(
            sequence=_bounded_positive_int(
                item.get("sequence"),
                "sequence",
                max_value=2,
                error_code=error_code,
            ),
            action=action,
            requires_distinct_evidence=_required_bool(
                item.get("requires_distinct_evidence"),
                "requires_distinct_evidence",
                error_code=error_code,
            ),
            requires_follow_up_admission=_required_bool(
                item.get("requires_follow_up_admission"),
                "requires_follow_up_admission",
                error_code=error_code,
            ),
        )
        if normalized["sequence"] != index:
            raise ArtifactHandoffError(
                status_code=422,
                error_code=error_code,
                detail=(
                    "Artifact retention scheduler daemon operator control "
                    "admission supervisor action sequence is invalid."
                ),
            )
        if normalized["mutates_process"] != item.get("mutates_process"):
            raise ArtifactHandoffError(
                status_code=422,
                error_code=error_code,
                detail=(
                    "Artifact retention scheduler daemon operator control "
                    "admission supervisor action mutation flag is invalid."
                ),
            )
        actions.append(normalized)
    return actions


def _operator_control_admission_guardrails(
    *,
    action: str,
    admission_status: str,
) -> dict[str, bool]:
    mutating = (
        action
        in AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_MUTATING_ACTIONS
    )
    ready = admission_status == "READY"
    return {
        "metadata_only": True,
        "admission_only": True,
        "operator_request_validated": True,
        "current_process_metadata_only": True,
        "ready_allows_supervisor_dispatch": ready,
        "supervisor_adapter_required": ready and mutating,
        "restart_decomposes_to_stop_then_start": action == "restart_daemon",
        "restart_requires_follow_up_admission": action == "restart_daemon",
        "contract_starts_process": False,
        "contract_stops_process": False,
        "subprocess_started": False,
        "subprocess_stopped": False,
        "database_write_performed": False,
        "job_queue_enqueue_performed": False,
        "worker_execution_performed": False,
        "physical_delete_automation_enabled": False,
        "test_profile_required": True,
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
        "raw_supervised_process_snapshot_included": False,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
        "ag_direct_process_control_allowed": False,
    }


def _operator_control_admission_metadata(
    *,
    request: Mapping[str, Any],
    current_process: Mapping[str, Any],
    admission_status: str,
    next_supervisor_actions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "safe_for_ag_projection": True,
        "metadata_only": True,
        "admission_contract_only": True,
        "operator_control_request_hash": sha256_json(dict(request)),
        "current_process_hash": sha256_json(dict(current_process)),
        "mutating_action": request["action"]
        in AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_MUTATING_ACTIONS,
        "approval_required": request["metadata"]["approval_required"],
        "approval_granted": request["metadata"]["approval_granted"],
        "ready_for_dispatch": admission_status == "READY",
        "blocked": admission_status == "BLOCKED",
        "noop": admission_status == "NOOP",
        "next_supervisor_action_count": len(next_supervisor_actions),
        "subprocess_started": False,
        "subprocess_stopped": False,
        "database_write_performed": False,
        "job_queue_enqueue_performed": False,
        "worker_execution_performed": False,
        "secrets_redacted": True,
    }


def _operator_control_admission_id(
    *,
    scheduler_id: str,
    operator_control_request_id: str,
    current_process: Mapping[str, Any],
    checked_at: str,
) -> str:
    basis = {
        "scheduler_id": scheduler_id,
        "operator_control_request_id": operator_control_request_id,
        "current_process_hash": sha256_json(dict(current_process)),
        "checked_at": checked_at,
    }
    return str(
        uuid5(
            NAMESPACE_URL,
            (
                "nex-ae-api:artifact-retention:operator-control-admission:"
                f"{sha256_json(basis)}"
            ),
        )
    )


def _operator_control_supervisor_command_previews(
    *,
    admission: Mapping[str, Any],
    checked_at: str,
) -> list[dict[str, Any]]:
    if admission["admission_status"] != "READY":
        return []
    request = admission["operator_control_request"]
    previews: list[dict[str, Any]] = []
    for next_action in admission["next_supervisor_actions"]:
        action = next_action["action"]
        command = build_artifact_retention_scheduler_daemon_supervisor_command(
            action=action,
            checked_at=checked_at,
            enabled=action == "start_daemon",
            explicit_opt_in=action == "start_daemon"
            and request["explicit_opt_in"] is True,
            max_cycles=request["max_cycles"],
            run_worker=request["run_worker"],
            requested_by=request["operator_subject"],
            reason=request["reason"],
        )
        previews.append(
            _operator_control_supervisor_command_preview_item(
                next_action=next_action,
                supervisor_command=command,
            )
        )
    return previews


def _operator_control_supervisor_command_preview_item(
    *,
    next_action: Mapping[str, Any],
    supervisor_command: Mapping[str, Any],
) -> dict[str, Any]:
    command = validate_artifact_retention_scheduler_daemon_supervisor_command(
        supervisor_command
    )
    return {
        "sequence": next_action["sequence"],
        "action": next_action["action"],
        "requires_distinct_evidence": next_action["requires_distinct_evidence"],
        "requires_follow_up_admission": next_action[
            "requires_follow_up_admission"
        ],
        "supervisor_command": command,
    }


def _validate_operator_control_supervisor_command_previews(
    value: Any,
    *,
    admission: Mapping[str, Any],
    error_code: str,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control command "
                "preview supervisor commands must be a list."
            ),
        )
    previews: list[dict[str, Any]] = []
    expected_next_actions = admission["next_supervisor_actions"]
    if len(value) != len(expected_next_actions):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control command "
                "preview supervisor command count is invalid."
            ),
        )
    for index, item in enumerate(value):
        if not isinstance(item, Mapping) or set(item) != {
            "sequence",
            "action",
            "requires_distinct_evidence",
            "requires_follow_up_admission",
            "supervisor_command",
        }:
            raise ArtifactHandoffError(
                status_code=422,
                error_code=error_code,
                detail=(
                    "Artifact retention scheduler daemon operator control "
                    "command preview supervisor command keys are invalid."
                ),
            )
        next_action = expected_next_actions[index]
        if item.get("sequence") != next_action["sequence"]:
            raise ArtifactHandoffError(
                status_code=422,
                error_code=error_code,
                detail=(
                    "Artifact retention scheduler daemon operator control "
                    "command preview supervisor command sequence is invalid."
                ),
            )
        action = _daemon_supervisor_action_for_context(
            item.get("action"),
            error_code=error_code,
        )
        if action != next_action["action"]:
            raise ArtifactHandoffError(
                status_code=422,
                error_code=error_code,
                detail=(
                    "Artifact retention scheduler daemon operator control "
                    "command preview supervisor command action is invalid."
                ),
            )
        if item.get("requires_distinct_evidence") != next_action[
            "requires_distinct_evidence"
        ]:
            raise ArtifactHandoffError(
                status_code=422,
                error_code=error_code,
                detail=(
                    "Artifact retention scheduler daemon operator control "
                    "command preview evidence flag is invalid."
                ),
            )
        if item.get("requires_follow_up_admission") != next_action[
            "requires_follow_up_admission"
        ]:
            raise ArtifactHandoffError(
                status_code=422,
                error_code=error_code,
                detail=(
                    "Artifact retention scheduler daemon operator control "
                    "command preview follow-up flag is invalid."
                ),
            )
        command = validate_artifact_retention_scheduler_daemon_supervisor_command(
            item.get("supervisor_command")
        )
        if command["scheduler_id"] != admission["scheduler_id"]:
            raise ArtifactHandoffError(
                status_code=422,
                error_code=error_code,
                detail=(
                    "Artifact retention scheduler daemon operator control "
                    "command preview scheduler scope is invalid."
                ),
            )
        if command["command"]["action"] != action:
            raise ArtifactHandoffError(
                status_code=422,
                error_code=error_code,
                detail=(
                    "Artifact retention scheduler daemon operator control "
                    "command preview command action is invalid."
                ),
            )
        previews.append(
            _operator_control_supervisor_command_preview_item(
                next_action=next_action,
                supervisor_command=command,
            )
        )
    return previews


def _operator_control_command_preview_guardrails(
    *,
    admission: Mapping[str, Any],
    command_previews: Sequence[Mapping[str, Any]],
) -> dict[str, bool]:
    return {
        "metadata_only": True,
        "preview_only": True,
        "operator_admission_validated": True,
        "supervisor_commands_validated": True,
        "ready_admission_required_for_commands": bool(command_previews)
        == (admission["admission_status"] == "READY"),
        "contract_starts_process": False,
        "contract_stops_process": False,
        "supervisor_adapter_invoked": False,
        "subprocess_started": False,
        "subprocess_stopped": False,
        "database_write_performed": False,
        "job_queue_enqueue_performed": False,
        "worker_execution_performed": False,
        "physical_delete_automation_enabled": False,
        "test_profile_required": True,
        "restart_decomposes_to_stop_then_start": admission["action"]
        == "restart_daemon",
        "restart_requires_follow_up_admission": admission["action"]
        == "restart_daemon",
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
        "raw_supervised_process_snapshot_included": False,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
        "ag_direct_process_control_allowed": False,
    }


def _operator_control_command_preview_metadata(
    *,
    admission: Mapping[str, Any],
    command_previews: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    actions = [item["action"] for item in command_previews]
    return {
        "safe_for_ag_projection": True,
        "metadata_only": True,
        "command_preview_contract_only": True,
        "operator_control_admission_hash": sha256_json(dict(admission)),
        "command_preview_count": len(command_previews),
        "supervisor_actions": actions,
        "ready_for_dispatch": admission["admission_status"] == "READY",
        "blocked": admission["admission_status"] == "BLOCKED",
        "noop": admission["admission_status"] == "NOOP",
        "start_preview_count": actions.count("start_daemon"),
        "stop_preview_count": actions.count("stop_daemon"),
        "status_probe_preview_count": actions.count("status_probe"),
        "restart_preview": admission["action"] == "restart_daemon",
        "supervisor_adapter_invoked": False,
        "subprocess_started": False,
        "subprocess_stopped": False,
        "database_write_performed": False,
        "job_queue_enqueue_performed": False,
        "worker_execution_performed": False,
        "secrets_redacted": True,
    }


def _operator_control_command_preview_id(
    *,
    scheduler_id: str,
    operator_control_admission_id: str,
    command_previews: Sequence[Mapping[str, Any]],
    checked_at: str,
) -> str:
    basis = {
        "scheduler_id": scheduler_id,
        "operator_control_admission_id": operator_control_admission_id,
        "command_previews_hash": sha256_json(list(command_previews)),
        "checked_at": checked_at,
    }
    return str(
        uuid5(
            NAMESPACE_URL,
            (
                "nex-ae-api:artifact-retention:operator-control-command-preview:"
                f"{sha256_json(basis)}"
            ),
        )
    )


def _operator_control_facade_guardrails(
    *,
    preview: Mapping[str, Any],
) -> dict[str, bool]:
    return {
        "metadata_only": True,
        "policy_evaluated": True,
        "request_validated": True,
        "admission_evaluated": True,
        "command_preview_evaluated": True,
        "preview_only": True,
        "process_control_allowed": False,
        "supervisor_dispatch_performed": False,
        "supervisor_adapter_invoked": False,
        "subprocess_started": False,
        "subprocess_stopped": False,
        "database_write_performed": False,
        "job_queue_enqueue_performed": False,
        "worker_execution_performed": False,
        "test_profile_required": True,
        "restart_decomposes_to_stop_then_start": preview["action"]
        == "restart_daemon",
        "raw_supervised_process_snapshot_included": False,
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
        "ag_direct_process_control_allowed": False,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
        "physical_delete_automation_enabled": False,
    }


def _operator_control_facade_metadata(
    *,
    policy: Mapping[str, Any],
    request: Mapping[str, Any],
    admission: Mapping[str, Any],
    preview: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "safe_for_ag_projection": True,
        "metadata_only": True,
        "route_facade": True,
        "policy_contract_only": True,
        "preview_only": True,
        "scheduler_id": preview["scheduler_id"],
        "action": preview["action"],
        "admission_status": admission["admission_status"],
        "decision_reason": admission["decision_reason"],
        "ready_for_dispatch": preview["metadata"]["ready_for_dispatch"],
        "command_preview_count": preview["metadata"]["command_preview_count"],
        "supervisor_actions": list(preview["metadata"]["supervisor_actions"]),
        "policy_hash": sha256_json(dict(policy)),
        "request_hash": sha256_json(dict(request)),
        "admission_hash": sha256_json(dict(admission)),
        "command_preview_hash": sha256_json(dict(preview)),
        "subprocess_started": False,
        "subprocess_stopped": False,
        "database_write_performed": False,
        "job_queue_enqueue_performed": False,
        "worker_execution_performed": False,
        "secrets_redacted": True,
    }


def _operator_control_facade_id(
    *,
    scheduler_id: str,
    operator_control_policy_id: str,
    operator_control_request_id: str,
    operator_control_admission_id: str,
    operator_control_command_preview_id: str,
    checked_at: str,
) -> str:
    basis = {
        "scheduler_id": scheduler_id,
        "operator_control_policy_id": operator_control_policy_id,
        "operator_control_request_id": operator_control_request_id,
        "operator_control_admission_id": operator_control_admission_id,
        "operator_control_command_preview_id": operator_control_command_preview_id,
        "checked_at": checked_at,
    }
    return str(
        uuid5(
            NAMESPACE_URL,
            (
                "nex-ae-api:artifact-retention:operator-control-facade:"
                f"{sha256_json(basis)}"
            ),
        )
    )


def _normalize_operator_control_execution_mode(value: Any, *, error_code: str) -> str:
    mode = _required_text(
        value,
        "execution_mode",
        error_code=error_code,
    ).lower()
    if (
        mode
        not in AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_MODES
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "mode is invalid."
            ),
        )
    return mode


def _normalize_operator_control_execution_status(
    value: Any,
    *,
    error_code: str,
) -> str:
    status = _required_text(
        value,
        "execution_status",
        error_code=error_code,
    ).upper()
    if (
        status
        not in AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_STATUSES
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "status is invalid."
            ),
        )
    return status


def _normalize_operator_control_execution_state_status(
    value: Any,
    *,
    error_code: str,
) -> str:
    status = _required_text(
        value,
        "execution_status",
        error_code=error_code,
    ).upper()
    if (
        status
        not in AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_STATE_STATUSES
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "state status is invalid."
            ),
        )
    return status


def _normalize_operator_control_idempotency_status(
    value: Any,
    *,
    error_code: str,
) -> str:
    status = _required_text(
        value,
        "idempotency_status",
        error_code=error_code,
    ).upper()
    if (
        status
        not in AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_IDEMPOTENCY_STATUSES
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "idempotency status is invalid."
            ),
        )
    return status


def _normalize_operator_control_execution_worker_plan_status(
    value: Any,
    *,
    error_code: str,
) -> str:
    status = _required_text(
        value,
        "plan_status",
        error_code=error_code,
    ).upper()
    if (
        status
        not in AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_PLAN_STATUSES
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "worker plan status is invalid."
            ),
        )
    return status


def _normalize_operator_control_execution_worker_command_status(
    value: Any,
    *,
    error_code: str,
) -> str:
    status = _required_text(
        value,
        "command_status",
        error_code=error_code,
    ).upper()
    if (
        status
        not in AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_COMMAND_STATUSES
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "worker command status is invalid."
            ),
        )
    return status


def _operator_control_execution_request_id(
    *,
    scheduler_id: str,
    operator_control_facade_id: str,
    execution_mode: str,
    requested_at: str,
) -> str:
    basis = {
        "scheduler_id": scheduler_id,
        "operator_control_facade_id": operator_control_facade_id,
        "execution_mode": execution_mode,
        "requested_at": requested_at,
    }
    return str(
        uuid5(
            NAMESPACE_URL,
            (
                "nex-ae-api:artifact-retention:operator-control-execution-request:"
                f"{sha256_json(basis)}"
            ),
        )
    )


def _operator_control_execution_result_id(
    *,
    scheduler_id: str,
    operator_control_execution_request_id: str,
    execution_status: str,
    observed_at: str,
) -> str:
    basis = {
        "scheduler_id": scheduler_id,
        "operator_control_execution_request_id": operator_control_execution_request_id,
        "execution_status": execution_status,
        "observed_at": observed_at,
    }
    return str(
        uuid5(
            NAMESPACE_URL,
            (
                "nex-ae-api:artifact-retention:operator-control-execution-result:"
                f"{sha256_json(basis)}"
            ),
        )
    )


def _operator_control_execution_state_id(
    *,
    scheduler_id: str,
    operator_control_execution_request_id: str,
    execution_status: str,
    idempotency_status: str,
    observed_at: str,
) -> str:
    basis = {
        "scheduler_id": scheduler_id,
        "operator_control_execution_request_id": operator_control_execution_request_id,
        "execution_status": execution_status,
        "idempotency_status": idempotency_status,
        "observed_at": observed_at,
    }
    return str(
        uuid5(
            NAMESPACE_URL,
            (
                "nex-ae-api:artifact-retention:operator-control-execution-state:"
                f"{sha256_json(basis)}"
            ),
        )
    )


def _operator_control_execution_state_transition_id(
    *,
    scheduler_id: str,
    operator_control_execution_state_id: str,
    from_status: str,
    to_status: str,
    transitioned_at: str,
) -> str:
    basis = {
        "scheduler_id": scheduler_id,
        "operator_control_execution_state_id": operator_control_execution_state_id,
        "from_status": from_status,
        "to_status": to_status,
        "transitioned_at": transitioned_at,
    }
    return str(
        uuid5(
            NAMESPACE_URL,
            (
                "nex-ae-api:artifact-retention:operator-control-execution-"
                f"state-transition:{sha256_json(basis)}"
            ),
        )
    )


def _operator_control_execution_worker_plan_id(
    *,
    scheduler_id: str,
    operator_control_execution_state_id: str,
    plan_status: str,
    planned_at: str,
) -> str:
    basis = {
        "scheduler_id": scheduler_id,
        "operator_control_execution_state_id": operator_control_execution_state_id,
        "plan_status": plan_status,
        "planned_at": planned_at,
    }
    return str(
        uuid5(
            NAMESPACE_URL,
            (
                "nex-ae-api:artifact-retention:operator-control-"
                f"execution-worker-plan:{sha256_json(basis)}"
            ),
        )
    )


def _operator_control_execution_worker_command_id(
    *,
    scheduler_id: str,
    operator_control_execution_worker_plan_id: str,
    command_status: str,
    commanded_at: str,
) -> str:
    basis = {
        "scheduler_id": scheduler_id,
        "operator_control_execution_worker_plan_id": (
            operator_control_execution_worker_plan_id
        ),
        "command_status": command_status,
        "commanded_at": commanded_at,
    }
    return str(
        uuid5(
            NAMESPACE_URL,
            (
                "nex-ae-api:artifact-retention:operator-control-"
                f"execution-worker-command:{sha256_json(basis)}"
            ),
        )
    )


def _ensure_operator_control_execution_source_scope(
    *,
    payload: Mapping[str, Any],
    facade: Mapping[str, Any],
    error_code: str,
    label: str,
) -> None:
    for field_name in (
        "operator_control_facade_id",
        "operator_control_request_id",
        "operator_control_admission_id",
        "operator_control_command_preview_id",
    ):
        if payload.get(field_name) != facade[field_name]:
            raise ArtifactHandoffError(
                status_code=422,
                error_code=error_code,
                detail=(
                    "Artifact retention scheduler daemon operator control "
                    f"execution {label} source scope is invalid."
                ),
            )


def _bounded_non_negative_operator_control_count(
    value: Any,
    field_name: str,
    *,
    error_code: str,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 2:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                f"{field_name} is invalid."
            ),
        )
    return value


def _operator_control_execution_request_guardrails(
    *,
    facade: Mapping[str, Any],
    execution_mode: str,
) -> dict[str, bool]:
    ready = facade["facade_status"] == "READY"
    return {
        "metadata_only": True,
        "execution_request_only": True,
        "operator_control_facade_validated": True,
        "requires_ready_facade": True,
        "ready_facade": ready,
        "requires_supervisor_command_preview": True,
        "has_supervisor_command_preview": (
            facade["metadata"]["command_preview_count"] > 0
        ),
        "contract_only_mode": execution_mode == "contract_only",
        "fake_dry_run_supervisor_dispatch_mode": (
            execution_mode == "fake_dry_run_supervisor_persistent_dispatch"
        ),
        "supervisor_dispatch_performed": False,
        "supervisor_adapter_invoked": False,
        "supervisor_result_persisted": False,
        "supervisor_event_persisted": False,
        "subprocess_started": False,
        "subprocess_stopped": False,
        "database_write_performed": False,
        "job_queue_enqueue_performed": False,
        "worker_execution_performed": False,
        "test_profile_required": True,
        "bounded_max_cycles_required": True,
        "restart_decomposes_to_stop_then_start": facade["action"]
        == "restart_daemon",
        "restart_requires_follow_up_admission": facade["action"]
        == "restart_daemon",
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
        "raw_supervised_process_snapshot_included": False,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
        "ag_direct_process_control_allowed": False,
        "physical_delete_automation_enabled": False,
        "secrets_redacted": True,
    }


def _operator_control_execution_request_metadata(
    *,
    facade: Mapping[str, Any],
    execution_mode: str,
    requested_at: str,
) -> dict[str, Any]:
    command_count = facade["metadata"]["command_preview_count"]
    return {
        "safe_for_ag_projection": True,
        "metadata_only": True,
        "execution_contract_only": True,
        "operator_control_facade_hash": sha256_json(dict(facade)),
        "requested_at": requested_at,
        "source_facade_status": facade["facade_status"],
        "ready_facade": facade["facade_status"] == "READY",
        "blocked_facade": facade["facade_status"] == "BLOCKED",
        "noop_facade": facade["facade_status"] == "NOOP",
        "ready_for_execution": (
            facade["facade_status"] == "READY"
            and command_count > 0
            and execution_mode != "contract_only"
        ),
        "supervisor_command_count": command_count,
        "supervisor_actions": list(facade["metadata"]["supervisor_actions"]),
        "supervisor_dispatch_performed": False,
        "supervisor_adapter_invoked": False,
        "supervisor_result_persisted": False,
        "supervisor_event_persisted": False,
        "subprocess_started": False,
        "subprocess_stopped": False,
        "database_write_performed": False,
        "job_queue_enqueue_performed": False,
        "worker_execution_performed": False,
        "secrets_redacted": True,
    }


def _operator_control_execution_result_decision(
    *,
    execution_request: Mapping[str, Any],
) -> dict[str, str]:
    if execution_request["facade_status"] == "BLOCKED":
        return {
            "execution_status": "BLOCKED",
            "decision_reason": execution_request["operator_control_facade"][
                "operator_control_admission"
            ]["decision_reason"],
        }
    if execution_request["facade_status"] == "NOOP":
        return {
            "execution_status": "NOOP",
            "decision_reason": execution_request["operator_control_facade"][
                "operator_control_admission"
            ]["decision_reason"],
        }
    if execution_request["execution_mode"] == "contract_only":
        return {
            "execution_status": "BLOCKED",
            "decision_reason": "execution_contract_only",
        }
    return {
        "execution_status": "READY",
        "decision_reason": "ready_for_fake_dry_run_supervisor_dispatch",
    }


def _operator_control_execution_result_dispatch_results(
    value: Any,
    *,
    error_code: str,
) -> list[dict[str, Any]]:
    if value != []:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "result dispatch results must be empty before execution wiring."
            ),
        )
    return []


def _operator_control_execution_state_decision(
    *,
    execution_request: Mapping[str, Any],
    existing_state: Mapping[str, Any] | None = None,
    idempotency_status: str | None = None,
) -> dict[str, str]:
    if idempotency_status == "REPLAYED":
        return {
            "execution_status": "BLOCKED",
            "idempotency_status": "REPLAYED",
            "decision_reason": "idempotency_replay_returns_existing_state",
        }
    if idempotency_status == "CONFLICT":
        return {
            "execution_status": "BLOCKED",
            "idempotency_status": "CONFLICT",
            "decision_reason": "idempotency_key_conflict",
        }
    if existing_state is not None:
        if existing_state["idempotency_key"] != execution_request["idempotency_key"]:
            return {
                "execution_status": "BLOCKED",
                "idempotency_status": "CONFLICT",
                "decision_reason": "idempotency_key_conflict",
            }
        if existing_state["operator_control_execution_request_hash"] == sha256_json(
            dict(execution_request)
        ):
            return {
                "execution_status": "BLOCKED",
                "idempotency_status": "REPLAYED",
                "decision_reason": "idempotency_replay_returns_existing_state",
            }
        return {
            "execution_status": "BLOCKED",
            "idempotency_status": "CONFLICT",
            "decision_reason": "idempotency_key_conflict",
        }
    if execution_request["facade_status"] == "BLOCKED":
        return {
            "execution_status": "BLOCKED",
            "idempotency_status": "NEW",
            "decision_reason": execution_request["operator_control_facade"][
                "operator_control_admission"
            ]["decision_reason"],
        }
    if execution_request["facade_status"] == "NOOP":
        return {
            "execution_status": "NOOP",
            "idempotency_status": "NEW",
            "decision_reason": execution_request["operator_control_facade"][
                "operator_control_admission"
            ]["decision_reason"],
        }
    if execution_request["execution_mode"] == "contract_only":
        return {
            "execution_status": "BLOCKED",
            "idempotency_status": "NEW",
            "decision_reason": "execution_contract_only",
        }
    return {
        "execution_status": "ADMITTED",
        "idempotency_status": "NEW",
        "decision_reason": "admitted_for_fake_dry_run_supervisor_dispatch",
    }


def _operator_control_execution_allowed_next_statuses(status: str) -> list[str]:
    return {
        "ADMITTED": ["EXECUTING", "BLOCKED"],
        "EXECUTING": ["SUCCEEDED", "FAILED"],
        "SUCCEEDED": [],
        "FAILED": [],
        "BLOCKED": [],
        "NOOP": [],
    }[status]


def _ensure_operator_control_execution_transition_allowed(
    *,
    from_status: str,
    to_status: str,
) -> None:
    if to_status not in _operator_control_execution_allowed_next_statuses(
        from_status
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_transition_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "state transition is not allowed."
            ),
        )


def _operator_control_execution_state_guardrails(
    *,
    execution_request: Mapping[str, Any],
    execution_status: str,
    idempotency_status: str,
) -> dict[str, bool]:
    return {
        "metadata_only": True,
        "state_machine_only": True,
        "operator_control_execution_request_validated": True,
        "idempotency_key_required": True,
        "idempotency_key_scoped_to_request": True,
        "idempotency_replay_blocks_duplicate_dispatch": idempotency_status
        == "REPLAYED",
        "idempotency_conflict_blocks_dispatch": idempotency_status == "CONFLICT",
        "admitted_allows_execution_transition": execution_status == "ADMITTED",
        "executing_allows_terminal_transition": execution_status == "EXECUTING",
        "terminal_state": execution_status in {"SUCCEEDED", "FAILED", "BLOCKED", "NOOP"},
        "supervisor_dispatch_performed": False,
        "supervisor_adapter_invoked": False,
        "supervisor_result_persisted": False,
        "supervisor_event_persisted": False,
        "subprocess_started": False,
        "subprocess_stopped": False,
        "database_write_performed": False,
        "job_queue_enqueue_performed": False,
        "worker_execution_performed": False,
        "test_profile_required": True,
        "bounded_max_cycles_required": True,
        "restart_decomposes_to_stop_then_start": execution_request["action"]
        == "restart_daemon",
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
        "raw_supervised_process_snapshot_included": False,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
        "ag_direct_process_control_allowed": False,
        "physical_delete_automation_enabled": False,
        "secrets_redacted": True,
    }


def _operator_control_execution_state_metadata(
    *,
    execution_request: Mapping[str, Any],
    execution_status: str,
    idempotency_status: str,
    observed_at: str,
    existing_state: Mapping[str, Any] | None = None,
    prior_state_id: str | None = None,
) -> dict[str, Any]:
    replayed = idempotency_status == "REPLAYED"
    conflict = idempotency_status == "CONFLICT"
    return {
        "safe_for_ag_projection": True,
        "metadata_only": True,
        "execution_state_machine_only": True,
        "operator_control_execution_request_hash": sha256_json(
            dict(execution_request)
        ),
        "observed_at": observed_at,
        "source_facade_status": execution_request["facade_status"],
        "execution_mode": execution_request["execution_mode"],
        "execution_status": execution_status,
        "idempotency_status": idempotency_status,
        "idempotency_replayed": replayed,
        "idempotency_conflict": conflict,
        "prior_execution_state_id": (
            prior_state_id
            if prior_state_id is not None
            else (
                existing_state["operator_control_execution_state_id"]
                if existing_state is not None
                else None
            )
        ),
        "allowed_next_statuses": _operator_control_execution_allowed_next_statuses(
            execution_status
        ),
        "supervisor_command_count": execution_request["supervisor_command_count"],
        "supervisor_actions": list(execution_request["supervisor_actions"]),
        "supervisor_dispatch_performed": False,
        "supervisor_adapter_invoked": False,
        "supervisor_result_persisted": False,
        "supervisor_event_persisted": False,
        "subprocess_started": False,
        "subprocess_stopped": False,
        "database_write_performed": False,
        "job_queue_enqueue_performed": False,
        "worker_execution_performed": False,
        "secrets_redacted": True,
    }


def _operator_control_execution_transition_guardrails(
    *,
    state: Mapping[str, Any],
    to_status: str,
) -> dict[str, bool]:
    return {
        "metadata_only": True,
        "state_transition_only": True,
        "source_state_validated": True,
        "transition_allowed": to_status in state["allowed_next_statuses"],
        "admitted_to_executing": state["execution_status"] == "ADMITTED"
        and to_status == "EXECUTING",
        "admitted_to_blocked": state["execution_status"] == "ADMITTED"
        and to_status == "BLOCKED",
        "executing_to_succeeded": state["execution_status"] == "EXECUTING"
        and to_status == "SUCCEEDED",
        "executing_to_failed": state["execution_status"] == "EXECUTING"
        and to_status == "FAILED",
        "supervisor_dispatch_performed": False,
        "supervisor_adapter_invoked": False,
        "supervisor_result_persisted": False,
        "supervisor_event_persisted": False,
        "subprocess_started": False,
        "subprocess_stopped": False,
        "database_write_performed": False,
        "job_queue_enqueue_performed": False,
        "worker_execution_performed": False,
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
        "raw_supervised_process_snapshot_included": False,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
        "ag_direct_process_control_allowed": False,
        "physical_delete_automation_enabled": False,
        "secrets_redacted": True,
    }


def _operator_control_execution_transition_metadata(
    *,
    state: Mapping[str, Any],
    to_status: str,
    transitioned_at: str,
) -> dict[str, Any]:
    return {
        "safe_for_ag_projection": True,
        "metadata_only": True,
        "execution_state_transition_only": True,
        "operator_control_execution_state_hash": sha256_json(dict(state)),
        "transitioned_at": transitioned_at,
        "from_status": state["execution_status"],
        "to_status": to_status,
        "source_idempotency_status": state["idempotency_status"],
        "to_terminal": to_status in {"SUCCEEDED", "FAILED", "BLOCKED"},
        "supervisor_dispatch_performed": False,
        "supervisor_adapter_invoked": False,
        "supervisor_result_persisted": False,
        "supervisor_event_persisted": False,
        "subprocess_started": False,
        "subprocess_stopped": False,
        "database_write_performed": False,
        "job_queue_enqueue_performed": False,
        "worker_execution_performed": False,
        "secrets_redacted": True,
    }


def _operator_control_execution_result_guardrails(
    *,
    execution_request: Mapping[str, Any],
    execution_status: str,
) -> dict[str, bool]:
    return {
        "metadata_only": True,
        "execution_result_only": True,
        "operator_control_execution_request_validated": True,
        "ready_status_reserved_for_fake_dry_run_dispatch": (
            execution_status == "READY"
        ),
        "blocked_until_dispatch_wiring": execution_status == "BLOCKED",
        "noop_without_dispatch": execution_status == "NOOP",
        "supervisor_dispatch_performed": False,
        "supervisor_adapter_invoked": False,
        "supervisor_result_persisted": False,
        "supervisor_event_persisted": False,
        "subprocess_started": False,
        "subprocess_stopped": False,
        "database_write_performed": False,
        "job_queue_enqueue_performed": False,
        "worker_execution_performed": False,
        "test_profile_required": True,
        "bounded_max_cycles_required": True,
        "restart_decomposes_to_stop_then_start": execution_request["action"]
        == "restart_daemon",
        "restart_requires_follow_up_admission": execution_request["action"]
        == "restart_daemon",
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
        "raw_supervised_process_snapshot_included": False,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
        "ag_direct_process_control_allowed": False,
        "physical_delete_automation_enabled": False,
        "secrets_redacted": True,
    }


def _operator_control_execution_result_metadata(
    *,
    execution_request: Mapping[str, Any],
    execution_status: str,
    observed_at: str,
) -> dict[str, Any]:
    return {
        "safe_for_ag_projection": True,
        "metadata_only": True,
        "execution_contract_only": True,
        "operator_control_execution_request_hash": sha256_json(
            dict(execution_request)
        ),
        "observed_at": observed_at,
        "source_facade_status": execution_request["facade_status"],
        "execution_mode": execution_request["execution_mode"],
        "execution_status": execution_status,
        "ready_for_execution": execution_status == "READY",
        "blocked": execution_status == "BLOCKED",
        "noop": execution_status == "NOOP",
        "dispatch_count": 0,
        "supervisor_command_count": execution_request["supervisor_command_count"],
        "supervisor_actions": list(execution_request["supervisor_actions"]),
        "supervisor_dispatch_performed": False,
        "supervisor_adapter_invoked": False,
        "supervisor_result_persisted": False,
        "supervisor_event_persisted": False,
        "subprocess_started": False,
        "subprocess_stopped": False,
        "database_write_performed": False,
        "job_queue_enqueue_performed": False,
        "worker_execution_performed": False,
        "secrets_redacted": True,
    }


def _operator_control_execution_worker_supervisor_commands(
    state: Mapping[str, Any],
) -> list[dict[str, Any]]:
    execution_request = state["operator_control_execution_request"]
    facade = execution_request["operator_control_facade"]
    command_preview = facade["operator_control_command_preview"]
    commands: list[dict[str, Any]] = []
    for item in command_preview["supervisor_command_previews"]:
        commands.append(
            validate_artifact_retention_scheduler_daemon_supervisor_command(
                item["supervisor_command"]
            )
        )
    return commands


def _validate_operator_control_execution_worker_supervisor_commands(
    value: Any,
    *,
    error_code: str,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control execution "
                "worker supervisor commands are invalid."
            ),
        )
    return [
        validate_artifact_retention_scheduler_daemon_supervisor_command(item)
        for item in value
    ]


def _operator_control_execution_worker_plan_decision(
    *,
    state: Mapping[str, Any],
    supervisor_commands: Sequence[Mapping[str, Any]],
) -> dict[str, str]:
    if state["execution_status"] != "ADMITTED":
        return {
            "plan_status": "BLOCKED",
            "decision_reason": "source_execution_state_not_admitted",
        }
    if state["execution_mode"] != "fake_dry_run_supervisor_persistent_dispatch":
        return {
            "plan_status": "BLOCKED",
            "decision_reason": "execution_mode_not_worker_enabled",
        }
    if len(supervisor_commands) == 0:
        return {
            "plan_status": "BLOCKED",
            "decision_reason": "supervisor_command_preview_missing",
        }
    return {
        "plan_status": "READY",
        "decision_reason": "ready_for_fake_dry_run_supervisor_worker",
    }


def _operator_control_execution_worker_plan_guardrails(
    *,
    state: Mapping[str, Any],
    supervisor_commands: Sequence[Mapping[str, Any]],
    plan_status: str,
) -> dict[str, bool]:
    source_admitted = state["execution_status"] == "ADMITTED"
    fake_mode = state["execution_mode"] == "fake_dry_run_supervisor_persistent_dispatch"
    return {
        "worker_plan_only": True,
        "source_execution_state_validated": True,
        "requires_admitted_state": True,
        "source_execution_state_admitted": source_admitted,
        "requires_fake_dry_run_supervisor_dispatch_mode": True,
        "fake_dry_run_supervisor_dispatch_mode": fake_mode,
        "requires_supervisor_command_preview": True,
        "has_supervisor_command_preview": len(supervisor_commands) > 0,
        "ready_for_worker": plan_status == "READY",
        "uses_existing_supervisor_runner": True,
        "uses_fake_supervisor_adapter_first": True,
        "persists_execution_state": True,
        "persists_execution_transition": True,
        "supervisor_dispatch_performed": False,
        "supervisor_adapter_invoked": False,
        "supervisor_result_persisted": False,
        "supervisor_event_persisted": False,
        "subprocess_started": False,
        "subprocess_stopped": False,
        "database_write_performed": False,
        "job_queue_enqueue_performed": False,
        "worker_execution_performed": False,
        "test_profile_required": True,
        "bounded_max_cycles_required": True,
        "restart_decomposes_to_stop_then_start": state["action"] == "restart_daemon",
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
        "raw_supervised_process_snapshot_included": False,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
        "ag_direct_process_control_allowed": False,
        "physical_delete_automation_enabled": False,
        "secrets_redacted": True,
    }


def _operator_control_execution_worker_plan_metadata(
    *,
    state: Mapping[str, Any],
    supervisor_commands: Sequence[Mapping[str, Any]],
    plan_status: str,
    planned_at: str,
) -> dict[str, Any]:
    return {
        "safe_for_ag_projection": True,
        "worker_plan_only": True,
        "operator_control_execution_state_hash": sha256_json(dict(state)),
        "planned_at": planned_at,
        "source_execution_status": state["execution_status"],
        "source_idempotency_status": state["idempotency_status"],
        "execution_mode": state["execution_mode"],
        "plan_status": plan_status,
        "ready_for_worker": plan_status == "READY",
        "supervisor_command_count": len(supervisor_commands),
        "supervisor_actions": [command["command"]["action"] for command in supervisor_commands],
        "supervisor_dispatch_performed": False,
        "supervisor_adapter_invoked": False,
        "supervisor_result_persisted": False,
        "supervisor_event_persisted": False,
        "subprocess_started": False,
        "subprocess_stopped": False,
        "database_write_performed": False,
        "job_queue_enqueue_performed": False,
        "worker_execution_performed": False,
        "secrets_redacted": True,
    }


def _operator_control_execution_worker_command_guardrails(
    *,
    plan: Mapping[str, Any],
    command_status: str,
) -> dict[str, bool]:
    return {
        "worker_command_only": True,
        "source_worker_plan_validated": True,
        "requires_ready_worker_plan": True,
        "source_worker_plan_ready": plan["plan_status"] == "READY",
        "ready_for_worker_execution": command_status == "READY",
        "uses_existing_supervisor_runner": True,
        "uses_fake_supervisor_adapter_first": True,
        "requires_explicit_state_persistence": True,
        "requires_explicit_transition_persistence": True,
        "supervisor_dispatch_performed": False,
        "supervisor_adapter_invoked": False,
        "supervisor_result_persisted": False,
        "supervisor_event_persisted": False,
        "subprocess_started": False,
        "subprocess_stopped": False,
        "database_write_performed": False,
        "job_queue_enqueue_performed": False,
        "worker_execution_performed": False,
        "test_profile_required": True,
        "bounded_max_cycles_required": True,
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
        "raw_supervised_process_snapshot_included": False,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
        "ag_direct_process_control_allowed": False,
        "physical_delete_automation_enabled": False,
        "secrets_redacted": True,
    }


def _operator_control_execution_worker_command_metadata(
    *,
    plan: Mapping[str, Any],
    command_status: str,
    commanded_at: str,
) -> dict[str, Any]:
    return {
        "safe_for_ag_projection": True,
        "worker_command_only": True,
        "operator_control_execution_worker_plan_hash": sha256_json(dict(plan)),
        "commanded_at": commanded_at,
        "plan_status": plan["plan_status"],
        "execution_mode": plan["execution_mode"],
        "worker_mode": "fake_dry_run_supervisor_persistent_dispatch_worker",
        "command_status": command_status,
        "ready_for_worker_execution": command_status == "READY",
        "supervisor_command_count": (
            plan["supervisor_command_count"] if command_status == "READY" else 0
        ),
        "supervisor_actions": (
            list(plan["supervisor_actions"]) if command_status == "READY" else []
        ),
        "supervisor_dispatch_performed": False,
        "supervisor_adapter_invoked": False,
        "supervisor_result_persisted": False,
        "supervisor_event_persisted": False,
        "subprocess_started": False,
        "subprocess_stopped": False,
        "database_write_performed": False,
        "job_queue_enqueue_performed": False,
        "worker_execution_performed": False,
        "secrets_redacted": True,
    }


def _safe_operator_subject(value: Any, *, error_code: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control request "
                "operator subject is invalid."
            ),
        )
    subject = {
        "actor_type": _required_text(
            value.get("actor_type"),
            "actor_type",
            error_code=error_code,
        ),
        "actor_id": _required_text(
            value.get("actor_id"),
            "actor_id",
            error_code=error_code,
        ),
    }
    for field_name in ("tenant_id", "workspace_id", "service_id"):
        field_value = optional_text(value.get(field_name))
        if field_value is not None:
            subject[field_name] = field_value
    allowed_keys = {"actor_type", "actor_id", "tenant_id", "workspace_id", "service_id"}
    if any(key not in allowed_keys for key in value):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control request "
                "operator subject keys are invalid."
            ),
        )
    return subject


def _normalize_operator_control_approval(
    value: Any,
    *,
    action: str,
    operator_subject: Mapping[str, str],
    requested_at: str,
    reason: str,
    error_code: str,
) -> dict[str, Any] | None:
    approval_required = action in {"start_daemon", "restart_daemon"}
    if value is None:
        if not approval_required:
            return None
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control request "
                "approval is required for start or restart."
            ),
        )
    if not isinstance(value, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control request "
                "approval is invalid."
            ),
        )
    if set(value) != {"approved", "approved_by", "approved_at", "reason"}:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control request "
                "approval keys are invalid."
            ),
        )
    approved = _required_bool(value.get("approved"), "approved", error_code=error_code)
    approved_by = _safe_operator_subject(
        value.get("approved_by"),
        error_code=error_code,
    )
    approved_at = _required_text(
        value.get("approved_at"),
        "approved_at",
        error_code=error_code,
    )
    approval_reason = _required_text(
        value.get("reason"),
        "reason",
        error_code=error_code,
    )
    if approval_required and approved is not True:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control request "
                "approval must be granted for start or restart."
            ),
        )
    if approval_required and approved_by.get("actor_id") != operator_subject.get(
        "actor_id"
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control request "
                "approval subject is invalid."
            ),
        )
    if approval_required and approved_at != requested_at:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control request "
                "approval time is invalid."
            ),
        )
    if approval_required and approval_reason != reason:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control request "
                "approval reason is invalid."
            ),
        )
    return {
        "approved": approved,
        "approved_by": approved_by,
        "approved_at": approved_at,
        "reason": approval_reason,
    }


def _operator_control_policy_id(*, scheduler_id: str, checked_at: str) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            "nex-ae-api:artifact-retention:operator-control-policy:"
            f"{scheduler_id}:{checked_at}",
        )
    )


def _operator_control_request_id(
    *,
    scheduler_id: str,
    action: str,
    idempotency_key: str,
    requested_at: str,
) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            "nex-ae-api:artifact-retention:operator-control-request:"
            f"{scheduler_id}:{action}:{idempotency_key}:{requested_at}",
        )
    )


def _normalize_daemon_supervisor_mode(value: Any) -> str:
    mode = _required_text(
        value,
        "supervisor_mode",
        error_code="ae.artifact_retention_scheduler_daemon_supervisor_command_invalid",
    ).lower()
    if mode != DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_MODE:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_supervisor_command_invalid",
            detail=(
                "Artifact retention scheduler daemon supervisor command mode "
                "is invalid."
            ),
        )
    return mode


def _normalize_daemon_supervisor_result_status(value: Any) -> str:
    status = _required_text(
        value,
        "result_status",
        error_code="ae.artifact_retention_scheduler_daemon_supervisor_result_invalid",
    ).upper()
    if status not in AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_RESULT_STATUSES:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_supervisor_result_invalid",
            detail=(
                "Artifact retention scheduler daemon supervisor result status "
                "is invalid."
            ),
        )
    return status


def _ensure_daemon_supervisor_command_enablement(
    *,
    action: str,
    runtime_config: Mapping[str, Any],
    error_code: str,
) -> None:
    if runtime_config["enablement"]["profile"] != "test":
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor command profile "
                "must be test."
            ),
        )
    if action == "start_daemon" and (
        runtime_config["enablement"]["enabled"] is not True
        or runtime_config["enablement"]["explicit_opt_in"] is not True
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor command start "
                "requires enabled runtime and explicit opt-in."
            ),
        )


def _validate_daemon_supervisor_command_payload(value: Any) -> dict[str, Any]:
    error_code = "ae.artifact_retention_scheduler_daemon_supervisor_command_invalid"
    if not isinstance(value, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor command command "
                "is invalid."
            ),
        )
    command = dict(value)
    if set(command) != {
        "action",
        "entrypoint",
        "profile",
        "enabled",
        "explicit_opt_in",
        "checked_at",
        "max_cycles",
        "run_worker",
        "output_format",
        "supervisor_mode",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor command command "
                "keys are invalid."
            ),
        )
    command["action"] = _normalize_daemon_supervisor_action(command.get("action"))
    command["entrypoint"] = _required_text(
        command.get("entrypoint"),
        "entrypoint",
        error_code=error_code,
    )
    if command["entrypoint"] != DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ENTRYPOINT:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor command "
                "entrypoint is invalid."
            ),
        )
    command["profile"] = _required_text(
        command.get("profile"),
        "profile",
        error_code=error_code,
    ).lower()
    command["enabled"] = _required_bool(
        command.get("enabled"),
        "enabled",
        error_code=error_code,
    )
    command["explicit_opt_in"] = _required_bool(
        command.get("explicit_opt_in"),
        "explicit_opt_in",
        error_code=error_code,
    )
    command["checked_at"] = _required_text(
        command.get("checked_at"),
        "checked_at",
        error_code=error_code,
    )
    command["max_cycles"] = _bounded_positive_int(
        command.get("max_cycles"),
        "max_cycles",
        max_value=MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_MAX_CYCLES,
        error_code=error_code,
    )
    command["run_worker"] = _required_bool(
        command.get("run_worker"),
        "run_worker",
        error_code=error_code,
    )
    command["output_format"] = _normalize_output_format(
        command.get("output_format"),
        error_code=error_code,
    )
    command["supervisor_mode"] = _normalize_daemon_supervisor_mode(
        command.get("supervisor_mode")
    )
    return command


def _ensure_daemon_supervisor_command_scope(
    *,
    scheduler_id: str,
    command: Mapping[str, Any],
    runtime_config: Mapping[str, Any],
    daemon_config: Mapping[str, Any],
    runtime_state: Mapping[str, Any],
    error_code: str,
) -> None:
    if scheduler_id != runtime_config["scheduler_id"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor command scope "
                "is invalid."
            ),
        )
    if daemon_config["scheduler_id"] != scheduler_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor command daemon "
                "scope is invalid."
            ),
        )
    if runtime_state["scheduler_id"] != scheduler_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor command state "
                "scope is invalid."
            ),
        )
    if command["profile"] != runtime_config["enablement"]["profile"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor command profile "
                "is invalid."
            ),
        )
    if command["enabled"] != runtime_config["enablement"]["enabled"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor command enabled "
                "flag is invalid."
            ),
        )
    if command["explicit_opt_in"] != runtime_config["enablement"]["explicit_opt_in"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor command explicit "
                "opt-in is invalid."
            ),
        )
    if command["checked_at"] != runtime_config["checked_at"]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor command "
                "checked_at is invalid."
            ),
        )
    expected_lifecycle = (
        "STARTING"
        if command["action"] == "start_daemon"
        and runtime_config["enablement"]["enablement_status"] == "READY"
        else "DISABLED"
    )
    if runtime_state["lifecycle_status"] != expected_lifecycle:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor command runtime "
                "state lifecycle is invalid."
            ),
        )


def _daemon_supervisor_command_execution_plan(
    *,
    action: str,
    runtime_config: Mapping[str, Any],
) -> dict[str, bool]:
    runtime_ready = runtime_config["enablement"]["enablement_status"] == "READY"
    return {
        "loads_runtime_config": True,
        "validates_daemon_config": True,
        "builds_runtime_state": True,
        "reads_status": action == "status_probe",
        "requests_start": action == "start_daemon",
        "requests_stop": action == "stop_daemon",
        "runtime_ready": runtime_ready,
        "supervisor_adapter_required": action in {"start_daemon", "stop_daemon"},
        "supervisor_adapter_available": False,
        "supervisor_adapter_invoked": False,
        "starts_process": False,
        "stops_process": False,
        "delegates_cli_execution": False,
        "bounded_loop_is_finite": True,
        "writes_database": False,
        "enqueues_job_queue": False,
        "runs_worker": False,
        "physical_delete_enabled": False,
    }


def _daemon_supervisor_command_guardrails(*, action: str) -> dict[str, bool]:
    return {
        "metadata_only": True,
        "daemon_process_owner_ae": True,
        "supervisor_owner_ae": True,
        "default_supervisor_disabled": True,
        "production_continuous_start_enabled": False,
        "start_daemon_requires_supervisor_adapter": action == "start_daemon",
        "stop_daemon_requires_supervisor_adapter": action == "stop_daemon",
        "supervisor_adapter_required": action in {"start_daemon", "stop_daemon"},
        "supervisor_adapter_invoked": False,
        "execution_requires_test_profile": True,
        "execution_requires_explicit_opt_in": action == "start_daemon",
        "bounded_max_cycles_required": True,
        "database_url_included": False,
        "database_write_performed": False,
        "job_queue_enqueue_performed": False,
        "worker_execution_performed": False,
        "runtime_state_persisted": False,
        "process_started": False,
        "process_stopped": False,
        "physical_delete_automation_enabled": False,
        "secrets_redacted": True,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
        "ag_direct_process_control_allowed": False,
    }


def _daemon_supervisor_command_metadata(
    *,
    action: str,
    runtime_config: Mapping[str, Any],
    runtime_state: Mapping[str, Any],
    command: Mapping[str, Any],
    requested_by: Any,
    reason: Any,
) -> dict[str, Any]:
    runtime_ready = runtime_config["enablement"]["enablement_status"] == "READY"
    return {
        "safe_for_ag_projection": True,
        "metadata_only": True,
        "requested_by": _safe_optional_actor(requested_by),
        "reason": optional_text(reason),
        "action": action,
        "supervisor_mode": command["supervisor_mode"],
        "runtime_ready": runtime_ready,
        "runtime_block_reason": runtime_config["enablement"]["block_reason"],
        "lifecycle_status": runtime_state["lifecycle_status"],
        "lifecycle_reason": runtime_state["lifecycle_reason"],
        "bounded_loop_requested": action == "start_daemon",
        "bounded_loop_started": False,
        "supervisor_adapter_required": action in {"start_daemon", "stop_daemon"},
        "supervisor_adapter_invoked": False,
        "process_started": False,
        "process_stopped": False,
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
        "database_write_performed": False,
        "job_queue_enqueue_performed": False,
        "worker_execution_performed": False,
        "runtime_state_persisted": False,
    }


def _safe_optional_actor(value: Any) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_supervisor_command_invalid",
            detail=(
                "Artifact retention scheduler daemon supervisor command actor "
                "is invalid."
            ),
        )
    actor_type = _required_text(
        value.get("actor_type"),
        "actor_type",
        error_code="ae.artifact_retention_scheduler_daemon_supervisor_command_invalid",
    )
    actor_id = _required_text(
        value.get("actor_id"),
        "actor_id",
        error_code="ae.artifact_retention_scheduler_daemon_supervisor_command_invalid",
    )
    return {"actor_type": actor_type, "actor_id": actor_id}


def _default_daemon_supervisor_result_status(action: str) -> str:
    if action == "start_daemon":
        return "BLOCKED"
    if action == "stop_daemon":
        return "NOOP"
    return "READY"


def _daemon_supervisor_adapter_state(
    *,
    supervisor_adapter_available: bool,
    supervisor_adapter_invoked: bool,
    adapter_name: str | None,
    process_started: bool,
    process_stopped: bool,
) -> dict[str, Any]:
    error_code = "ae.artifact_retention_scheduler_daemon_supervisor_result_invalid"
    available = _required_bool(
        supervisor_adapter_available,
        "supervisor_adapter_available",
        error_code=error_code,
    )
    invoked = _required_bool(
        supervisor_adapter_invoked,
        "supervisor_adapter_invoked",
        error_code=error_code,
    )
    started = _required_bool(
        process_started,
        "process_started",
        error_code=error_code,
    )
    stopped = _required_bool(
        process_stopped,
        "process_stopped",
        error_code=error_code,
    )
    normalized_adapter_name = optional_text(adapter_name)
    if invoked and not available:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor result adapter "
                "availability is invalid."
            ),
        )
    if available and normalized_adapter_name is None:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor result adapter "
                "name is required."
            ),
        )
    if not available and normalized_adapter_name is not None:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor result adapter "
                "name is invalid."
            ),
        )
    if started or stopped:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor result process "
                "side effect is invalid."
            ),
        )
    return {
        "supervisor_adapter_available": available,
        "supervisor_adapter_invoked": invoked,
        "adapter_name": normalized_adapter_name,
        "process_started": started,
        "process_stopped": stopped,
    }


def _daemon_supervisor_adapter_state_from_result(
    result: Mapping[str, Any],
) -> dict[str, Any]:
    execution_plan = result.get("execution_plan")
    guardrails = result.get("guardrails")
    metadata = result.get("metadata")
    if not isinstance(execution_plan, Mapping):
        execution_plan = {}
    if not isinstance(guardrails, Mapping):
        guardrails = {}
    if not isinstance(metadata, Mapping):
        metadata = {}
    available = execution_plan.get("supervisor_adapter_available") is True
    invoked = execution_plan.get("supervisor_adapter_invoked") is True
    adapter_name = metadata.get("adapter_name")
    process_started = (
        execution_plan.get("starts_process") is True
        or guardrails.get("process_started") is True
        or metadata.get("process_started") is True
    )
    process_stopped = (
        execution_plan.get("stops_process") is True
        or guardrails.get("process_stopped") is True
        or metadata.get("process_stopped") is True
    )
    state = _daemon_supervisor_adapter_state(
        supervisor_adapter_available=available,
        supervisor_adapter_invoked=invoked,
        adapter_name=adapter_name,
        process_started=process_started,
        process_stopped=process_stopped,
    )
    if (
        guardrails.get("supervisor_adapter_invoked") is not invoked
        or metadata.get("supervisor_adapter_invoked") is not invoked
        or guardrails.get("supervisor_adapter_available") is not available
        or metadata.get("supervisor_adapter_available") is not available
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_daemon_supervisor_result_invalid",
            detail=(
                "Artifact retention scheduler daemon supervisor result adapter "
                "state is invalid."
            ),
        )
    return state


def _daemon_supervisor_result_decision_reason(
    *,
    action: str,
    result_status: str,
    supervisor_adapter_invoked: bool = False,
) -> str:
    if result_status == "FAILED":
        return "supervisor_result_failed"
    if supervisor_adapter_invoked and action == "status_probe":
        return "fake_supervisor_status_probe"
    if supervisor_adapter_invoked and action == "start_daemon":
        return "fake_supervisor_dry_run_start_blocked"
    if supervisor_adapter_invoked and action == "stop_daemon":
        return "fake_supervisor_dry_run_stop_noop"
    if action == "start_daemon":
        return DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_START_BLOCK_REASON
    if action == "stop_daemon":
        return "daemon_not_running"
    return "status_probe_metadata_only"


def _daemon_supervisor_result_execution_plan(
    *,
    action: str,
    result_status: str,
    adapter_state: Mapping[str, Any] | None = None,
) -> dict[str, bool]:
    state = adapter_state or _daemon_supervisor_adapter_state(
        supervisor_adapter_available=False,
        supervisor_adapter_invoked=False,
        adapter_name=None,
        process_started=False,
        process_stopped=False,
    )
    return {
        "loads_supervisor_command": True,
        "reads_runtime_state": True,
        "supervisor_adapter_required": action in {"start_daemon", "stop_daemon"},
        "supervisor_adapter_available": state["supervisor_adapter_available"],
        "supervisor_adapter_invoked": state["supervisor_adapter_invoked"],
        "start_blocked_by_missing_supervisor_adapter": (
            action == "start_daemon"
            and result_status == "BLOCKED"
            and state["supervisor_adapter_invoked"] is False
        ),
        "start_blocked_by_fake_supervisor": (
            action == "start_daemon"
            and result_status == "BLOCKED"
            and state["supervisor_adapter_invoked"] is True
        ),
        "stop_noop_without_running_process": (
            action == "stop_daemon"
            and result_status == "NOOP"
            and state["supervisor_adapter_invoked"] is False
        ),
        "stop_noop_by_fake_supervisor": (
            action == "stop_daemon"
            and result_status == "NOOP"
            and state["supervisor_adapter_invoked"] is True
        ),
        "status_probe_metadata_only": action == "status_probe",
        "starts_process": state["process_started"],
        "stops_process": state["process_stopped"],
        "delegates_cli_execution": False,
        "writes_database": False,
        "enqueues_job_queue": False,
        "runs_worker": False,
        "physical_delete_enabled": False,
    }


def _daemon_supervisor_result_guardrails(
    *,
    action: str,
    result_status: str,
    adapter_state: Mapping[str, Any] | None = None,
) -> dict[str, bool]:
    state = adapter_state or _daemon_supervisor_adapter_state(
        supervisor_adapter_available=False,
        supervisor_adapter_invoked=False,
        adapter_name=None,
        process_started=False,
        process_stopped=False,
    )
    return {
        "metadata_only": True,
        "daemon_process_owner_ae": True,
        "supervisor_owner_ae": True,
        "result_status_terminal": result_status
        in {"READY", "BLOCKED", "NOOP", "FAILED"},
        "start_daemon_requires_supervisor_adapter": action == "start_daemon",
        "stop_daemon_requires_supervisor_adapter": action == "stop_daemon",
        "supervisor_adapter_available": state["supervisor_adapter_available"],
        "supervisor_adapter_invoked": state["supervisor_adapter_invoked"],
        "fake_supervisor_adapter_only": state["supervisor_adapter_available"],
        "process_started": state["process_started"],
        "process_stopped": state["process_stopped"],
        "database_url_included": False,
        "database_write_performed": False,
        "job_queue_enqueue_performed": False,
        "worker_execution_performed": False,
        "runtime_state_persisted": False,
        "physical_delete_automation_enabled": False,
        "secrets_redacted": True,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
        "ag_direct_process_control_allowed": False,
    }


def _daemon_supervisor_result_metadata(
    *,
    command: Mapping[str, Any],
    result_status: str,
    decision_reason: str,
    observed_at: str,
    message: Any,
    adapter_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    command_metadata = command["metadata"]
    state = adapter_state or _daemon_supervisor_adapter_state(
        supervisor_adapter_available=False,
        supervisor_adapter_invoked=False,
        adapter_name=None,
        process_started=False,
        process_stopped=False,
    )
    return {
        "safe_for_ag_projection": True,
        "metadata_only": True,
        "action": command["command"]["action"],
        "result_status": result_status,
        "decision_reason": decision_reason,
        "observed_at": observed_at,
        "message": optional_text(message),
        "runtime_ready": command_metadata["runtime_ready"],
        "supervisor_mode": command_metadata["supervisor_mode"],
        "supervisor_adapter_available": state["supervisor_adapter_available"],
        "supervisor_adapter_invoked": state["supervisor_adapter_invoked"],
        "adapter_name": state["adapter_name"],
        "process_started": state["process_started"],
        "process_stopped": state["process_stopped"],
        "bounded_loop_started": False,
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
        "database_write_performed": False,
        "job_queue_enqueue_performed": False,
        "worker_execution_performed": False,
        "runtime_state_persisted": False,
    }


def _daemon_supervisor_command_id(
    *,
    scheduler_id: str,
    command: Mapping[str, Any],
    runtime_state: Mapping[str, Any],
) -> str:
    basis = {
        "scheduler_id": scheduler_id,
        "command": dict(command),
        "runtime_state_id": runtime_state["daemon_runtime_state_id"],
    }
    return str(
        uuid5(
            NAMESPACE_URL,
            f"ae-artifact-retention-scheduler-daemon-supervisor-command:{sha256_json(basis)}",
        )
    )


def _daemon_supervisor_result_id(
    *,
    supervisor_command: Mapping[str, Any],
    result_status: str,
    observed_at: str,
) -> str:
    basis = {
        "scheduler_id": supervisor_command["scheduler_id"],
        "daemon_supervisor_command_id": supervisor_command[
            "daemon_supervisor_command_id"
        ],
        "result_status": result_status,
        "observed_at": observed_at,
    }
    return str(
        uuid5(
            NAMESPACE_URL,
            f"ae-artifact-retention-scheduler-daemon-supervisor-result:{sha256_json(basis)}",
        )
    )


def _daemon_process_lock_guardrails() -> dict[str, bool]:
    return {
        "metadata_only": True,
        "process_lock_required": True,
        "process_lock_acquired": False,
        "pid_recorded": True,
        "host_id_recorded": True,
        "database_url_included": False,
        "database_write_performed": False,
        "job_queue_enqueue_performed": False,
        "worker_execution_performed": False,
        "runtime_state_persisted": False,
        "physical_delete_automation_enabled": False,
        "secrets_redacted": True,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
    }


def _daemon_process_lock_metadata(
    *,
    process: Mapping[str, Any],
    timing: Mapping[str, Any],
    command_summary: Mapping[str, Any],
) -> dict[str, bool | int | str]:
    return {
        "safe_for_ag_projection": True,
        "metadata_only": True,
        "process_id": process["process_id"],
        "host_id": process["host_id"],
        "lock_owner": process["lock_owner"],
        "stale_after_seconds": timing["stale_after_seconds"],
        "execute_mode": command_summary["plan_only"] is False,
        "bounded_loop_requested": command_summary["mode"]
        == AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_EXECUTE_MODE,
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
        "process_lock_acquired": False,
        "runtime_state_persisted": False,
    }


def _daemon_run_metadata_guardrails() -> dict[str, bool]:
    return {
        "metadata_only": True,
        "process_lock_required": True,
        "process_lock_acquired": False,
        "run_record_required": True,
        "run_record_persisted": False,
        "lifecycle_event_required": True,
        "lifecycle_event_persisted": False,
        "database_url_included": False,
        "database_write_performed": False,
        "job_queue_enqueue_performed": False,
        "worker_execution_performed": False,
        "runtime_state_persisted": False,
        "physical_delete_automation_enabled": False,
        "secrets_redacted": True,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
    }


def _daemon_run_metadata_metadata(
    *,
    process: Mapping[str, Any],
    command_summary: Mapping[str, Any],
    lifecycle: Mapping[str, Any],
) -> dict[str, bool | int | str]:
    return {
        "safe_for_ag_projection": True,
        "metadata_only": True,
        "process_id": process["process_id"],
        "host_id": process["host_id"],
        "run_status": lifecycle["run_status"],
        "execute_mode": command_summary["plan_only"] is False,
        "bounded_loop_requested": command_summary["mode"]
        == AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_EXECUTE_MODE,
        "run_started": lifecycle["started_at"] is not None,
        "run_completed": lifecycle["completed_at"] is not None,
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
        "run_record_persisted": False,
        "lifecycle_event_persisted": False,
    }


def _daemon_cli_metadata(
    *,
    runtime_config: Mapping[str, Any],
    runtime_state: Mapping[str, Any],
    command: Mapping[str, Any],
) -> dict[str, bool]:
    ready_to_start = runtime_config["enablement"]["enablement_status"] == "READY"
    return {
        "metadata_only": True,
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
        "safe_for_ag_projection": True,
        "cli_entrypoint_defined": True,
        "runtime_config_validated": True,
        "daemon_config_validated": True,
        "runtime_state_built": True,
        "ready_to_start": ready_to_start,
        "blocked_by_runtime": not ready_to_start,
        "plan_only": command["plan_only"] is True,
        "summary_requested": command["output_format"] == "summary",
        "bounded_loop_started": False,
        "tick_once_ran": False,
        "job_enqueued": False,
        "worker_executed": False,
        "runtime_state_persisted": False,
        "lifecycle_starting": runtime_state["lifecycle_status"] == "STARTING",
        "lifecycle_disabled": runtime_state["lifecycle_status"] == "DISABLED",
    }


def _daemon_cli_plan_id(
    *,
    scheduler_id: str,
    command: Mapping[str, Any],
    runtime_state: Mapping[str, Any],
) -> str:
    basis = {
        "scheduler_id": scheduler_id,
        "command": dict(command),
        "runtime_state_id": runtime_state["daemon_runtime_state_id"],
    }
    return str(
        uuid5(
            NAMESPACE_URL,
            f"ae-artifact-retention-scheduler-daemon-cli:{sha256_json(basis)}",
        )
    )


def _daemon_cli_execute_command_id(
    *,
    scheduler_id: str,
    command: Mapping[str, Any],
    runtime_state: Mapping[str, Any],
) -> str:
    basis = {
        "scheduler_id": scheduler_id,
        "command": dict(command),
        "runtime_state_id": runtime_state["daemon_runtime_state_id"],
    }
    return str(
        uuid5(
            NAMESPACE_URL,
            "ae-artifact-retention-scheduler-daemon-cli-execute:"
            f"{sha256_json(basis)}",
        )
    )


def _daemon_process_lock_id(
    *,
    scheduler_id: str,
    command_id: str,
    process: Mapping[str, Any],
    requested_at: str,
) -> str:
    basis = {
        "scheduler_id": scheduler_id,
        "command_id": command_id,
        "process_id": process["process_id"],
        "host_id": process["host_id"],
        "lock_owner": process["lock_owner"],
        "requested_at": requested_at,
    }
    return str(
        uuid5(
            NAMESPACE_URL,
            f"ae-artifact-retention-scheduler-daemon-process-lock:{sha256_json(basis)}",
        )
    )


def _daemon_run_metadata_id(
    *,
    scheduler_id: str,
    command_id: str,
    process_lock_id: str,
    process: Mapping[str, Any],
    lifecycle: Mapping[str, Any],
) -> str:
    basis = {
        "scheduler_id": scheduler_id,
        "command_id": command_id,
        "process_lock_id": process_lock_id,
        "process_id": process["process_id"],
        "host_id": process["host_id"],
        "run_status": lifecycle["run_status"],
        "requested_at": lifecycle["requested_at"],
        "started_at": lifecycle["started_at"],
        "completed_at": lifecycle["completed_at"],
    }
    return str(
        uuid5(
            NAMESPACE_URL,
            f"ae-artifact-retention-scheduler-daemon-run-metadata:{sha256_json(basis)}",
        )
    )


def _daemon_signal_shutdown_adapter_id(
    *,
    scheduler_id: str,
    daemon_run_id: str,
    signal: Mapping[str, Any],
    shutdown_transition: Mapping[str, Any],
) -> str:
    basis = {
        "scheduler_id": scheduler_id,
        "daemon_run_id": daemon_run_id,
        "signal_name": signal["signal_name"],
        "received_at": signal["received_at"],
        "transition_id": shutdown_transition["daemon_shutdown_transition_id"],
    }
    return str(
        uuid5(
            NAMESPACE_URL,
            f"ae-artifact-retention-scheduler-daemon-signal-adapter:{sha256_json(basis)}",
        )
    )


def _daemon_cli_execution_result_id(
    *,
    execute_command: Mapping[str, Any],
    process_lock: Mapping[str, Any],
    started_run_metadata: Mapping[str, Any],
    completed_run_metadata: Mapping[str, Any],
    bounded_loop_result: Mapping[str, Any],
    shutdown_signal_adapter: Mapping[str, Any] | None,
) -> str:
    basis = {
        "command_id": execute_command["daemon_cli_execute_command_id"],
        "process_lock_id": process_lock["daemon_process_lock_id"],
        "started_run_id": started_run_metadata["daemon_run_id"],
        "completed_run_id": completed_run_metadata["daemon_run_id"],
        "bounded_loop_result_id": bounded_loop_result[
            "daemon_bounded_loop_result_id"
        ],
        "shutdown_signal_adapter_id": (
            shutdown_signal_adapter["daemon_signal_shutdown_adapter_id"]
            if shutdown_signal_adapter is not None
            else None
        ),
    }
    return str(
        uuid5(
            NAMESPACE_URL,
            f"ae-artifact-retention-scheduler-daemon-cli-execution:{sha256_json(basis)}",
        )
    )


def _ensure_daemon_run_store_schema(session: Any) -> None:
    dialect_name = _daemon_store_dialect_name(session)
    json_type = "JSONB" if dialect_name == "postgresql" else "TEXT"
    session.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS ae_artifact_retention_scheduler_daemon_runs (
                daemon_run_record_id TEXT PRIMARY KEY,
                daemon_run_record_schema_version TEXT NOT NULL,
                service_id TEXT NOT NULL,
                scheduler_id TEXT NOT NULL,
                daemon_instance_id TEXT NOT NULL,
                daemon_cli_execution_result_id TEXT NOT NULL UNIQUE,
                daemon_cli_execute_command_id TEXT NOT NULL,
                daemon_process_lock_id TEXT NOT NULL,
                started_daemon_run_id TEXT NOT NULL,
                completed_daemon_run_id TEXT NOT NULL,
                process_id INTEGER NOT NULL,
                host_id TEXT NOT NULL,
                run_status TEXT NOT NULL,
                result_status TEXT NOT NULL,
                stop_reason TEXT NOT NULL,
                max_cycles INTEGER NOT NULL,
                cycle_count INTEGER NOT NULL,
                worker_requested BOOLEAN NOT NULL,
                job_enqueued BOOLEAN NOT NULL,
                worker_executed BOOLEAN NOT NULL,
                started_at TIMESTAMPTZ NOT NULL,
                completed_at TIMESTAMPTZ NOT NULL,
                checked_at TIMESTAMPTZ NOT NULL,
                summary {json_type} NOT NULL,
                metadata {json_type} NOT NULL,
                execution_result_hash TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL
            )
            """
        )
    )
    session.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS ae_artifact_retention_scheduler_daemon_lifecycle_events (
                daemon_lifecycle_event_id TEXT PRIMARY KEY,
                daemon_lifecycle_event_schema_version TEXT NOT NULL,
                daemon_run_record_id TEXT NOT NULL,
                daemon_cli_execution_result_id TEXT NOT NULL,
                daemon_run_metadata_id TEXT NOT NULL,
                service_id TEXT NOT NULL,
                scheduler_id TEXT NOT NULL,
                daemon_instance_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                run_status TEXT NOT NULL,
                result_status TEXT,
                stop_reason TEXT,
                cycle_count INTEGER NOT NULL,
                occurred_at TIMESTAMPTZ NOT NULL,
                process_id INTEGER NOT NULL,
                host_id TEXT NOT NULL,
                summary {json_type} NOT NULL,
                metadata {json_type} NOT NULL,
                created_at TIMESTAMPTZ NOT NULL
            )
            """
        )
    )
    for statement in (
        """
        CREATE INDEX IF NOT EXISTS
            idx_ae_artifact_retention_scheduler_daemon_runs_scheduler_completed
        ON ae_artifact_retention_scheduler_daemon_runs
            (scheduler_id, completed_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS
            idx_ae_artifact_retention_scheduler_daemon_runs_status_completed
        ON ae_artifact_retention_scheduler_daemon_runs
            (result_status, completed_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS
            idx_ae_artifact_retention_scheduler_daemon_lifecycle_events_run
        ON ae_artifact_retention_scheduler_daemon_lifecycle_events
            (daemon_run_record_id, occurred_at ASC)
        """,
        """
        CREATE INDEX IF NOT EXISTS
            idx_ae_artifact_retention_scheduler_daemon_lifecycle_events_scheduler
        ON ae_artifact_retention_scheduler_daemon_lifecycle_events
            (scheduler_id, occurred_at DESC)
        """,
    ):
        session.execute(text(statement))


def _daemon_run_record_upsert_sql(dialect_name: str) -> str:
    summary_expr = _daemon_json_param_expr("summary", dialect_name)
    metadata_expr = _daemon_json_param_expr("metadata", dialect_name)
    return f"""
        INSERT INTO ae_artifact_retention_scheduler_daemon_runs (
            daemon_run_record_id,
            daemon_run_record_schema_version,
            service_id,
            scheduler_id,
            daemon_instance_id,
            daemon_cli_execution_result_id,
            daemon_cli_execute_command_id,
            daemon_process_lock_id,
            started_daemon_run_id,
            completed_daemon_run_id,
            process_id,
            host_id,
            run_status,
            result_status,
            stop_reason,
            max_cycles,
            cycle_count,
            worker_requested,
            job_enqueued,
            worker_executed,
            started_at,
            completed_at,
            checked_at,
            summary,
            metadata,
            execution_result_hash,
            created_at
        )
        VALUES (
            :daemon_run_record_id,
            :daemon_run_record_schema_version,
            :service_id,
            :scheduler_id,
            :daemon_instance_id,
            :daemon_cli_execution_result_id,
            :daemon_cli_execute_command_id,
            :daemon_process_lock_id,
            :started_daemon_run_id,
            :completed_daemon_run_id,
            :process_id,
            :host_id,
            :run_status,
            :result_status,
            :stop_reason,
            :max_cycles,
            :cycle_count,
            :worker_requested,
            :job_enqueued,
            :worker_executed,
            :started_at,
            :completed_at,
            :checked_at,
            {summary_expr},
            {metadata_expr},
            :execution_result_hash,
            :created_at
        )
        ON CONFLICT (daemon_run_record_id) DO UPDATE SET
            run_status = excluded.run_status,
            result_status = excluded.result_status,
            stop_reason = excluded.stop_reason,
            max_cycles = excluded.max_cycles,
            cycle_count = excluded.cycle_count,
            worker_requested = excluded.worker_requested,
            job_enqueued = excluded.job_enqueued,
            worker_executed = excluded.worker_executed,
            completed_at = excluded.completed_at,
            summary = excluded.summary,
            metadata = excluded.metadata,
            execution_result_hash = excluded.execution_result_hash,
            created_at = excluded.created_at
    """


def _daemon_lifecycle_event_upsert_sql(dialect_name: str) -> str:
    summary_expr = _daemon_json_param_expr("summary", dialect_name)
    metadata_expr = _daemon_json_param_expr("metadata", dialect_name)
    return f"""
        INSERT INTO ae_artifact_retention_scheduler_daemon_lifecycle_events (
            daemon_lifecycle_event_id,
            daemon_lifecycle_event_schema_version,
            daemon_run_record_id,
            daemon_cli_execution_result_id,
            daemon_run_metadata_id,
            service_id,
            scheduler_id,
            daemon_instance_id,
            event_type,
            run_status,
            result_status,
            stop_reason,
            cycle_count,
            occurred_at,
            process_id,
            host_id,
            summary,
            metadata,
            created_at
        )
        VALUES (
            :daemon_lifecycle_event_id,
            :daemon_lifecycle_event_schema_version,
            :daemon_run_record_id,
            :daemon_cli_execution_result_id,
            :daemon_run_metadata_id,
            :service_id,
            :scheduler_id,
            :daemon_instance_id,
            :event_type,
            :run_status,
            :result_status,
            :stop_reason,
            :cycle_count,
            :occurred_at,
            :process_id,
            :host_id,
            {summary_expr},
            {metadata_expr},
            :created_at
        )
        ON CONFLICT (daemon_lifecycle_event_id) DO UPDATE SET
            run_status = excluded.run_status,
            result_status = excluded.result_status,
            stop_reason = excluded.stop_reason,
            cycle_count = excluded.cycle_count,
            occurred_at = excluded.occurred_at,
            summary = excluded.summary,
            metadata = excluded.metadata,
            created_at = excluded.created_at
    """


def _daemon_run_record_select_sql(where_clause: str) -> str:
    return f"""
        SELECT
            daemon_run_record_id,
            daemon_run_record_schema_version,
            service_id,
            scheduler_id,
            daemon_instance_id,
            daemon_cli_execution_result_id,
            daemon_cli_execute_command_id,
            daemon_process_lock_id,
            started_daemon_run_id,
            completed_daemon_run_id,
            process_id,
            host_id,
            run_status,
            result_status,
            stop_reason,
            max_cycles,
            cycle_count,
            worker_requested,
            job_enqueued,
            worker_executed,
            started_at,
            completed_at,
            checked_at,
            summary,
            metadata,
            execution_result_hash,
            created_at
        FROM ae_artifact_retention_scheduler_daemon_runs
        WHERE {where_clause}
    """


def _daemon_lifecycle_event_select_sql(where_clause: str) -> str:
    return f"""
        SELECT
            daemon_lifecycle_event_id,
            daemon_lifecycle_event_schema_version,
            daemon_run_record_id,
            daemon_cli_execution_result_id,
            daemon_run_metadata_id,
            service_id,
            scheduler_id,
            daemon_instance_id,
            event_type,
            run_status,
            result_status,
            stop_reason,
            cycle_count,
            occurred_at,
            process_id,
            host_id,
            summary,
            metadata,
            created_at
        FROM ae_artifact_retention_scheduler_daemon_lifecycle_events
        WHERE {where_clause}
    """


def _daemon_run_record_params(record: Mapping[str, Any]) -> dict[str, Any]:
    params = validate_artifact_retention_scheduler_daemon_run_record(record)
    params["summary"] = json.dumps(params["summary"])
    params["metadata"] = json.dumps(params["metadata"])
    return params


def _daemon_lifecycle_event_params(event: Mapping[str, Any]) -> dict[str, Any]:
    params = validate_artifact_retention_scheduler_daemon_lifecycle_event(event)
    params["summary"] = json.dumps(params["summary"])
    params["metadata"] = json.dumps(params["metadata"])
    return params


def _daemon_run_record_from_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    return validate_artifact_retention_scheduler_daemon_run_record(
        {
            "daemon_run_record_id": data["daemon_run_record_id"],
            "daemon_run_record_schema_version": data[
                "daemon_run_record_schema_version"
            ],
            "service_id": data["service_id"],
            "scheduler_id": data["scheduler_id"],
            "daemon_instance_id": data["daemon_instance_id"],
            "daemon_cli_execution_result_id": data[
                "daemon_cli_execution_result_id"
            ],
            "daemon_cli_execute_command_id": data[
                "daemon_cli_execute_command_id"
            ],
            "daemon_process_lock_id": data["daemon_process_lock_id"],
            "started_daemon_run_id": data["started_daemon_run_id"],
            "completed_daemon_run_id": data["completed_daemon_run_id"],
            "process_id": data["process_id"],
            "host_id": data["host_id"],
            "run_status": data["run_status"],
            "result_status": data["result_status"],
            "stop_reason": data["stop_reason"],
            "max_cycles": data["max_cycles"],
            "cycle_count": data["cycle_count"],
            "worker_requested": bool(data["worker_requested"]),
            "job_enqueued": bool(data["job_enqueued"]),
            "worker_executed": bool(data["worker_executed"]),
            "started_at": _daemon_datetime_value(data["started_at"]),
            "completed_at": _daemon_datetime_value(data["completed_at"]),
            "checked_at": _daemon_datetime_value(data["checked_at"]),
            "summary": _daemon_json_value(data["summary"], {}),
            "metadata": _daemon_json_value(data["metadata"], {}),
            "execution_result_hash": data["execution_result_hash"],
            "created_at": _daemon_datetime_value(data["created_at"]),
        }
    )


def _daemon_lifecycle_event_from_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    return validate_artifact_retention_scheduler_daemon_lifecycle_event(
        {
            "daemon_lifecycle_event_id": data["daemon_lifecycle_event_id"],
            "daemon_lifecycle_event_schema_version": data[
                "daemon_lifecycle_event_schema_version"
            ],
            "daemon_run_record_id": data["daemon_run_record_id"],
            "daemon_cli_execution_result_id": data[
                "daemon_cli_execution_result_id"
            ],
            "daemon_run_metadata_id": data["daemon_run_metadata_id"],
            "service_id": data["service_id"],
            "scheduler_id": data["scheduler_id"],
            "daemon_instance_id": data["daemon_instance_id"],
            "event_type": data["event_type"],
            "run_status": data["run_status"],
            "result_status": data["result_status"],
            "stop_reason": data["stop_reason"],
            "cycle_count": data["cycle_count"],
            "occurred_at": _daemon_datetime_value(data["occurred_at"]),
            "process_id": data["process_id"],
            "host_id": data["host_id"],
            "summary": _daemon_json_value(data["summary"], {}),
            "metadata": _daemon_json_value(data["metadata"], {}),
            "created_at": _daemon_datetime_value(data["created_at"]),
        }
    )


def _ensure_daemon_supervised_process_record_scope(
    record: Mapping[str, Any],
    *,
    error_code: str,
) -> None:
    snapshot = record["supervised_process_snapshot"]
    lifecycle = snapshot["lifecycle"]
    process = snapshot["process"]
    metadata = snapshot["metadata"]
    expected_values = {
        "scheduler_id": snapshot["scheduler_id"],
        "daemon_supervisor_command_id": snapshot[
            "daemon_supervisor_command_id"
        ],
        "daemon_supervised_process_id": snapshot[
            "daemon_supervised_process_id"
        ],
        "action": snapshot["action"],
        "process_status": lifecycle["process_status"],
        "process_mode": snapshot["process_mode"],
        "process_id": process["process_id"],
        "host_id": process["host_id"],
        "observed_at": lifecycle["observed_at"],
        "started_at": lifecycle["started_at"],
        "completed_at": lifecycle["completed_at"],
        "exit_code": lifecycle["exit_code"],
        "termination_signal": lifecycle["termination_signal"],
        "process_running": metadata["process_running"],
        "process_started_observed": metadata["process_started_observed"],
        "process_stopped_observed": metadata["process_stopped_observed"],
        "subprocess_adapter_required": snapshot["guardrails"][
            "subprocess_adapter_required"
        ],
        "message": metadata["message"],
        "created_at": lifecycle["observed_at"],
    }
    for field_name, expected_value in expected_values.items():
        if record[field_name] != expected_value:
            raise ArtifactHandoffError(
                status_code=422,
                error_code=error_code,
                detail=(
                    "Artifact retention scheduler daemon supervised process "
                    f"record {field_name} is invalid."
                ),
            )


def _daemon_supervised_process_record_metadata(
    supervised_process_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    snapshot = validate_artifact_retention_scheduler_daemon_supervised_process_snapshot(
        supervised_process_snapshot
    )
    return {
        "safe_for_ag_projection": True,
        "read_model": (
            "ae_artifact_retention_scheduler_daemon_process_snapshots"
        ),
        "source_supervised_process_hash": sha256_json(dict(snapshot)),
        "supervised_process_record_persisted": True,
        "supervised_process_event_persisted": True,
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
        "database_write_performed": True,
        "job_queue_enqueue_performed": False,
        "worker_execution_performed": False,
        "runtime_state_persisted": False,
        "process_started": False,
        "process_stopped": False,
        "physical_delete_automation_enabled": False,
        "secrets_redacted": True,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
        "ag_direct_process_control_allowed": False,
    }


def _daemon_supervised_process_event_metadata(
    *,
    supervised_process_record: Mapping[str, Any],
    supervised_process_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    record = validate_artifact_retention_scheduler_daemon_supervised_process_record(
        supervised_process_record
    )
    snapshot = validate_artifact_retention_scheduler_daemon_supervised_process_snapshot(
        supervised_process_snapshot
    )
    return {
        "safe_for_ag_projection": True,
        "read_model": (
            "ae_artifact_retention_scheduler_daemon_process_events"
        ),
        "daemon_supervised_process_record_id": record[
            "daemon_supervised_process_record_id"
        ],
        "source_supervised_process_hash": sha256_json(dict(snapshot)),
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
        "database_write_performed": True,
        "job_queue_enqueue_performed": False,
        "worker_execution_performed": False,
        "runtime_state_persisted": False,
        "process_started": False,
        "process_stopped": False,
        "physical_delete_automation_enabled": False,
        "secrets_redacted": True,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
        "ag_direct_process_control_allowed": False,
    }


def _daemon_supervised_process_record_id(
    supervised_process_snapshot: Mapping[str, Any],
) -> str:
    snapshot = validate_artifact_retention_scheduler_daemon_supervised_process_snapshot(
        supervised_process_snapshot
    )
    return str(
        uuid5(
            NAMESPACE_URL,
            (
                "ae-artifact-retention-scheduler-daemon-supervised-process-record:"
                f"{snapshot['daemon_supervised_process_id']}"
            ),
        )
    )


def _daemon_supervised_process_event_id(
    supervised_process_record: Mapping[str, Any],
) -> str:
    event_type = supervised_process_record.get(
        "event_type",
        "SUPERVISED_PROCESS_SNAPSHOT_RECORDED",
    )
    basis = {
        "daemon_supervised_process_record_id": supervised_process_record[
            "daemon_supervised_process_record_id"
        ],
        "daemon_supervised_process_id": supervised_process_record[
            "daemon_supervised_process_id"
        ],
        "event_type": event_type,
    }
    return str(
        uuid5(
            NAMESPACE_URL,
            (
                "ae-artifact-retention-scheduler-daemon-supervised-process-event:"
                f"{sha256_json(basis)}"
            ),
        )
    )


def _daemon_supervised_process_route_guardrails(
    *,
    read_only: bool,
    process_control_allowed: bool,
) -> dict[str, bool]:
    return {
        "read_only": read_only,
        "ae_owned_process": True,
        "ae_owned_persistence": True,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
        "ag_direct_process_control_allowed": False,
        "process_control_allowed": process_control_allowed,
        "job_queue_enqueue_performed": False,
        "worker_execution_performed": False,
        "physical_delete_automation_enabled": False,
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
        "secrets_redacted": True,
    }


def _daemon_supervised_process_collection_item(
    supervised_process_record: Mapping[str, Any],
) -> dict[str, Any]:
    record = validate_artifact_retention_scheduler_daemon_supervised_process_record(
        supervised_process_record
    )
    return {
        "daemon_supervised_process_record_id": record[
            "daemon_supervised_process_record_id"
        ],
        "scheduler_id": record["scheduler_id"],
        "daemon_supervisor_command_id": record[
            "daemon_supervisor_command_id"
        ],
        "daemon_supervised_process_id": record["daemon_supervised_process_id"],
        "action": record["action"],
        "process_status": record["process_status"],
        "process_mode": record["process_mode"],
        "process_id": record["process_id"],
        "host_id": record["host_id"],
        "observed_at": record["observed_at"],
        "started_at": record["started_at"],
        "completed_at": record["completed_at"],
        "exit_code": record["exit_code"],
        "termination_signal": record["termination_signal"],
        "process_running": record["process_running"],
        "process_started_observed": record["process_started_observed"],
        "process_stopped_observed": record["process_stopped_observed"],
        "subprocess_adapter_required": record["subprocess_adapter_required"],
        "message": record["message"],
        "summary": dict(record["summary"]),
        "metadata": {
            "safe_for_ag_projection": True,
            "read_model": (
                "ae_artifact_retention_scheduler_daemon_process_snapshots"
            ),
            "database_url_included": False,
            "storage_path_included": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_included": False,
            "raw_daemon_runtime_payload_included": False,
            "process_started": False,
            "process_stopped": False,
        },
    }


def _daemon_supervised_process_collection_metadata(
    *,
    records: Sequence[Mapping[str, Any]],
    limit: int,
) -> dict[str, Any]:
    newest_observed_at = records[0]["observed_at"] if records else None
    return {
        "safe_for_ag_projection": True,
        "read_model": (
            "ae_artifact_retention_scheduler_daemon_process_snapshots"
        ),
        "item_count": len(records),
        "limit": limit,
        "has_more": len(records) == limit,
        "newest_observed_at": newest_observed_at,
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
    }


def _daemon_supervised_process_detail_metadata(
    *,
    supervised_process_record: Mapping[str, Any],
    supervised_process_events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "safe_for_ag_projection": True,
        "read_model": (
            "ae_artifact_retention_scheduler_daemon_process_detail"
        ),
        "daemon_supervised_process_record_id": supervised_process_record[
            "daemon_supervised_process_record_id"
        ],
        "supervised_process_event_count": len(supervised_process_events),
        "event_types": [event["event_type"] for event in supervised_process_events],
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
    }


def _daemon_run_record_metadata(result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "safe_for_ag_projection": True,
        "source_execution_result_hash": sha256_json(dict(result)),
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
        "process_lock_acquired": result["process_lock"]["guardrails"][
            "process_lock_acquired"
        ],
        "run_record_persisted": True,
        "lifecycle_event_persisted": True,
        "runtime_state_persisted": False,
        "physical_delete_automation_enabled": False,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
    }


def _daemon_run_record_id(result: Mapping[str, Any]) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            (
                "ae-artifact-retention-scheduler-daemon-run-record:"
                f"{result['daemon_cli_execution_result_id']}"
            ),
        )
    )


def _daemon_lifecycle_event_id(
    *,
    run_record: Mapping[str, Any],
    event_type: str,
    daemon_run_metadata_id: str,
) -> str:
    basis = {
        "daemon_run_record_id": run_record["daemon_run_record_id"],
        "event_type": event_type,
        "daemon_run_metadata_id": daemon_run_metadata_id,
    }
    return str(
        uuid5(
            NAMESPACE_URL,
            (
                "ae-artifact-retention-scheduler-daemon-lifecycle-event:"
                f"{sha256_json(basis)}"
            ),
        )
    )


def _ensure_daemon_supervisor_record_scope(
    record: Mapping[str, Any],
    *,
    error_code: str,
) -> None:
    command = record["supervisor_command"]
    result = record["supervisor_result"]
    if command["daemon_supervisor_command_id"] != record[
        "daemon_supervisor_command_id"
    ]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor record command "
                "scope is invalid."
            ),
        )
    if result["daemon_supervisor_result_id"] != record[
        "daemon_supervisor_result_id"
    ]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor record result "
                "scope is invalid."
            ),
        )
    expected_values = {
        "scheduler_id": result["scheduler_id"],
        "action": result["action"],
        "result_status": result["result_status"],
        "decision_reason": result["decision_reason"],
        "observed_at": result["observed_at"],
        "checked_at": command["command"]["checked_at"],
        "runtime_ready": result["metadata"]["runtime_ready"],
        "supervisor_adapter_available": result["metadata"][
            "supervisor_adapter_available"
        ],
        "supervisor_adapter_invoked": result["metadata"][
            "supervisor_adapter_invoked"
        ],
        "adapter_name": result["metadata"]["adapter_name"],
        "process_started": False,
        "process_stopped": False,
        "message": result["message"],
        "created_at": result["observed_at"],
    }
    for field_name, expected_value in expected_values.items():
        if record[field_name] != expected_value:
            raise ArtifactHandoffError(
                status_code=422,
                error_code=error_code,
                detail=(
                    "Artifact retention scheduler daemon supervisor record "
                    f"{field_name} is invalid."
                ),
            )


def _daemon_supervisor_record_metadata(
    supervisor_result: Mapping[str, Any],
) -> dict[str, Any]:
    result = validate_artifact_retention_scheduler_daemon_supervisor_result(
        supervisor_result
    )
    return {
        "safe_for_ag_projection": True,
        "read_model": "ae_artifact_retention_scheduler_daemon_supervisor_results",
        "source_supervisor_result_hash": sha256_json(dict(result)),
        "supervisor_result_persisted": True,
        "supervisor_event_persisted": True,
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
        "database_write_performed": True,
        "job_queue_enqueue_performed": False,
        "worker_execution_performed": False,
        "runtime_state_persisted": False,
        "process_started": False,
        "process_stopped": False,
        "physical_delete_automation_enabled": False,
        "secrets_redacted": True,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
        "ag_direct_process_control_allowed": False,
    }


def _daemon_supervisor_event_metadata(
    *,
    supervisor_record: Mapping[str, Any],
    supervisor_result: Mapping[str, Any],
) -> dict[str, Any]:
    record = validate_artifact_retention_scheduler_daemon_supervisor_record(
        supervisor_record
    )
    result = validate_artifact_retention_scheduler_daemon_supervisor_result(
        supervisor_result
    )
    return {
        "safe_for_ag_projection": True,
        "read_model": "ae_artifact_retention_scheduler_daemon_supervisor_events",
        "daemon_supervisor_record_id": record["daemon_supervisor_record_id"],
        "source_supervisor_result_hash": sha256_json(dict(result)),
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
        "database_write_performed": True,
        "job_queue_enqueue_performed": False,
        "worker_execution_performed": False,
        "runtime_state_persisted": False,
        "process_started": False,
        "process_stopped": False,
        "physical_delete_automation_enabled": False,
        "secrets_redacted": True,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
        "ag_direct_process_control_allowed": False,
    }


def _daemon_supervisor_route_guardrails(
    *,
    read_only: bool,
    process_control_allowed: bool,
) -> dict[str, bool]:
    return {
        "read_only": read_only,
        "ae_owned_supervisor": True,
        "ae_owned_persistence": True,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
        "ag_direct_process_control_allowed": False,
        "process_control_allowed": process_control_allowed,
        "job_queue_enqueue_performed": False,
        "worker_execution_performed": False,
        "physical_delete_automation_enabled": False,
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
        "secrets_redacted": True,
    }


def _daemon_supervisor_collection_item(
    supervisor_record: Mapping[str, Any],
) -> dict[str, Any]:
    record = validate_artifact_retention_scheduler_daemon_supervisor_record(
        supervisor_record
    )
    return {
        "daemon_supervisor_record_id": record["daemon_supervisor_record_id"],
        "scheduler_id": record["scheduler_id"],
        "daemon_supervisor_command_id": record[
            "daemon_supervisor_command_id"
        ],
        "daemon_supervisor_result_id": record["daemon_supervisor_result_id"],
        "action": record["action"],
        "result_status": record["result_status"],
        "decision_reason": record["decision_reason"],
        "observed_at": record["observed_at"],
        "checked_at": record["checked_at"],
        "runtime_ready": record["runtime_ready"],
        "supervisor_adapter_available": record[
            "supervisor_adapter_available"
        ],
        "supervisor_adapter_invoked": record["supervisor_adapter_invoked"],
        "adapter_name": record["adapter_name"],
        "process_started": False,
        "process_stopped": False,
        "message": record["message"],
        "summary": dict(record["summary"]),
        "metadata": {
            "safe_for_ag_projection": True,
            "read_model": (
                "ae_artifact_retention_scheduler_daemon_supervisor_results"
            ),
            "database_url_included": False,
            "storage_path_included": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_included": False,
            "raw_daemon_runtime_payload_included": False,
            "process_started": False,
            "process_stopped": False,
        },
    }


def _daemon_supervisor_collection_metadata(
    *,
    records: Sequence[Mapping[str, Any]],
    limit: int,
) -> dict[str, Any]:
    newest_observed_at = records[0]["observed_at"] if records else None
    return {
        "safe_for_ag_projection": True,
        "read_model": "ae_artifact_retention_scheduler_daemon_supervisor_results",
        "item_count": len(records),
        "limit": limit,
        "has_more": len(records) == limit,
        "newest_observed_at": newest_observed_at,
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
    }


def _daemon_supervisor_detail_metadata(
    *,
    supervisor_record: Mapping[str, Any],
    supervisor_events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "safe_for_ag_projection": True,
        "read_model": (
            "ae_artifact_retention_scheduler_daemon_supervisor_detail"
        ),
        "daemon_supervisor_record_id": supervisor_record[
            "daemon_supervisor_record_id"
        ],
        "supervisor_event_count": len(supervisor_events),
        "event_types": [event["event_type"] for event in supervisor_events],
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
    }


def _daemon_supervisor_record_id(supervisor_result: Mapping[str, Any]) -> str:
    result = validate_artifact_retention_scheduler_daemon_supervisor_result(
        supervisor_result
    )
    return str(
        uuid5(
            NAMESPACE_URL,
            (
                "ae-artifact-retention-scheduler-daemon-supervisor-record:"
                f"{result['daemon_supervisor_result_id']}"
            ),
        )
    )


def _daemon_supervisor_event_id(supervisor_record: Mapping[str, Any]) -> str:
    event_type = supervisor_record.get(
        "event_type",
        "SUPERVISOR_RESULT_RECORDED",
    )
    basis = {
        "daemon_supervisor_record_id": supervisor_record[
            "daemon_supervisor_record_id"
        ],
        "daemon_supervisor_result_id": supervisor_record[
            "daemon_supervisor_result_id"
        ],
        "event_type": event_type,
    }
    return str(
        uuid5(
            NAMESPACE_URL,
            (
                "ae-artifact-retention-scheduler-daemon-supervisor-event:"
                f"{sha256_json(basis)}"
            ),
        )
    )


def _ensure_daemon_supervised_process_store_schema(session: Any) -> None:
    dialect_name = _daemon_store_dialect_name(session)
    json_type = "JSONB" if dialect_name == "postgresql" else "TEXT"
    session.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS
                ae_artifact_retention_scheduler_daemon_process_snapshots (
                    daemon_supervised_process_record_id TEXT PRIMARY KEY,
                    daemon_supervised_process_record_schema_version TEXT NOT NULL,
                    service_id TEXT NOT NULL,
                    scheduler_id TEXT NOT NULL,
                    daemon_supervisor_command_id TEXT NOT NULL,
                    daemon_supervised_process_id TEXT NOT NULL UNIQUE,
                    action TEXT NOT NULL,
                    process_status TEXT NOT NULL,
                    process_mode TEXT NOT NULL,
                    process_id INTEGER,
                    host_id TEXT NOT NULL,
                    observed_at TIMESTAMPTZ NOT NULL,
                    started_at TIMESTAMPTZ,
                    completed_at TIMESTAMPTZ,
                    exit_code INTEGER,
                    termination_signal TEXT,
                    process_running BOOLEAN NOT NULL,
                    process_started_observed BOOLEAN NOT NULL,
                    process_stopped_observed BOOLEAN NOT NULL,
                    subprocess_adapter_required BOOLEAN NOT NULL,
                    message TEXT,
                    summary {json_type} NOT NULL,
                    metadata {json_type} NOT NULL,
                    supervised_process_snapshot {json_type} NOT NULL,
                    supervised_process_snapshot_hash TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                )
            """
        )
    )
    session.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS
                ae_artifact_retention_scheduler_daemon_process_events (
                    daemon_supervised_process_event_id TEXT PRIMARY KEY,
                    daemon_supervised_process_event_schema_version TEXT NOT NULL,
                    daemon_supervised_process_record_id TEXT NOT NULL,
                    daemon_supervised_process_id TEXT NOT NULL,
                    daemon_supervisor_command_id TEXT NOT NULL,
                    service_id TEXT NOT NULL,
                    scheduler_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    process_status TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    occurred_at TIMESTAMPTZ NOT NULL,
                    summary {json_type} NOT NULL,
                    metadata {json_type} NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                )
            """
        )
    )
    for statement in (
        """
        CREATE INDEX IF NOT EXISTS
            idx_ae_daemon_process_snapshots_observed
        ON ae_artifact_retention_scheduler_daemon_process_snapshots
            (scheduler_id, observed_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS
            idx_ae_daemon_process_snapshots_action_status
        ON ae_artifact_retention_scheduler_daemon_process_snapshots
            (action, process_status, observed_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS
            idx_ae_daemon_process_snapshots_pid
        ON ae_artifact_retention_scheduler_daemon_process_snapshots
            (host_id, process_id, observed_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS
            idx_ae_daemon_process_events_record
        ON ae_artifact_retention_scheduler_daemon_process_events
            (daemon_supervised_process_record_id, occurred_at ASC)
        """,
        """
        CREATE INDEX IF NOT EXISTS
            idx_ae_daemon_process_events_scheduler
        ON ae_artifact_retention_scheduler_daemon_process_events
            (scheduler_id, occurred_at DESC)
        """,
    ):
        session.execute(text(statement))


def _daemon_supervised_process_record_upsert_sql(dialect_name: str) -> str:
    json_exprs = {
        field_name: _daemon_json_param_expr(field_name, dialect_name)
        for field_name in (
            "summary",
            "metadata",
            "supervised_process_snapshot",
        )
    }
    return f"""
        INSERT INTO ae_artifact_retention_scheduler_daemon_process_snapshots (
            daemon_supervised_process_record_id,
            daemon_supervised_process_record_schema_version,
            service_id,
            scheduler_id,
            daemon_supervisor_command_id,
            daemon_supervised_process_id,
            action,
            process_status,
            process_mode,
            process_id,
            host_id,
            observed_at,
            started_at,
            completed_at,
            exit_code,
            termination_signal,
            process_running,
            process_started_observed,
            process_stopped_observed,
            subprocess_adapter_required,
            message,
            summary,
            metadata,
            supervised_process_snapshot,
            supervised_process_snapshot_hash,
            created_at
        )
        VALUES (
            :daemon_supervised_process_record_id,
            :daemon_supervised_process_record_schema_version,
            :service_id,
            :scheduler_id,
            :daemon_supervisor_command_id,
            :daemon_supervised_process_id,
            :action,
            :process_status,
            :process_mode,
            :process_id,
            :host_id,
            :observed_at,
            :started_at,
            :completed_at,
            :exit_code,
            :termination_signal,
            :process_running,
            :process_started_observed,
            :process_stopped_observed,
            :subprocess_adapter_required,
            :message,
            {json_exprs['summary']},
            {json_exprs['metadata']},
            {json_exprs['supervised_process_snapshot']},
            :supervised_process_snapshot_hash,
            :created_at
        )
        ON CONFLICT (daemon_supervised_process_record_id) DO UPDATE SET
            process_status = excluded.process_status,
            process_id = excluded.process_id,
            host_id = excluded.host_id,
            observed_at = excluded.observed_at,
            started_at = excluded.started_at,
            completed_at = excluded.completed_at,
            exit_code = excluded.exit_code,
            termination_signal = excluded.termination_signal,
            process_running = excluded.process_running,
            process_started_observed = excluded.process_started_observed,
            process_stopped_observed = excluded.process_stopped_observed,
            subprocess_adapter_required = excluded.subprocess_adapter_required,
            message = excluded.message,
            summary = excluded.summary,
            metadata = excluded.metadata,
            supervised_process_snapshot = excluded.supervised_process_snapshot,
            supervised_process_snapshot_hash =
                excluded.supervised_process_snapshot_hash,
            created_at = excluded.created_at
    """


def _daemon_supervised_process_event_upsert_sql(dialect_name: str) -> str:
    summary_expr = _daemon_json_param_expr("summary", dialect_name)
    metadata_expr = _daemon_json_param_expr("metadata", dialect_name)
    return f"""
        INSERT INTO ae_artifact_retention_scheduler_daemon_process_events (
            daemon_supervised_process_event_id,
            daemon_supervised_process_event_schema_version,
            daemon_supervised_process_record_id,
            daemon_supervised_process_id,
            daemon_supervisor_command_id,
            service_id,
            scheduler_id,
            action,
            process_status,
            event_type,
            occurred_at,
            summary,
            metadata,
            created_at
        )
        VALUES (
            :daemon_supervised_process_event_id,
            :daemon_supervised_process_event_schema_version,
            :daemon_supervised_process_record_id,
            :daemon_supervised_process_id,
            :daemon_supervisor_command_id,
            :service_id,
            :scheduler_id,
            :action,
            :process_status,
            :event_type,
            :occurred_at,
            {summary_expr},
            {metadata_expr},
            :created_at
        )
        ON CONFLICT (daemon_supervised_process_event_id) DO UPDATE SET
            process_status = excluded.process_status,
            occurred_at = excluded.occurred_at,
            summary = excluded.summary,
            metadata = excluded.metadata,
            created_at = excluded.created_at
    """


def _daemon_supervised_process_record_select_sql(where_clause: str) -> str:
    return f"""
        SELECT
            daemon_supervised_process_record_id,
            daemon_supervised_process_record_schema_version,
            service_id,
            scheduler_id,
            daemon_supervisor_command_id,
            daemon_supervised_process_id,
            action,
            process_status,
            process_mode,
            process_id,
            host_id,
            observed_at,
            started_at,
            completed_at,
            exit_code,
            termination_signal,
            process_running,
            process_started_observed,
            process_stopped_observed,
            subprocess_adapter_required,
            message,
            summary,
            metadata,
            supervised_process_snapshot,
            supervised_process_snapshot_hash,
            created_at
        FROM ae_artifact_retention_scheduler_daemon_process_snapshots
        WHERE {where_clause}
    """


def _daemon_supervised_process_event_select_sql(where_clause: str) -> str:
    return f"""
        SELECT
            daemon_supervised_process_event_id,
            daemon_supervised_process_event_schema_version,
            daemon_supervised_process_record_id,
            daemon_supervised_process_id,
            daemon_supervisor_command_id,
            service_id,
            scheduler_id,
            action,
            process_status,
            event_type,
            occurred_at,
            summary,
            metadata,
            created_at
        FROM ae_artifact_retention_scheduler_daemon_process_events
        WHERE {where_clause}
    """


def _daemon_supervised_process_record_params(
    record: Mapping[str, Any],
) -> dict[str, Any]:
    params = validate_artifact_retention_scheduler_daemon_supervised_process_record(
        record
    )
    for field_name in ("summary", "metadata", "supervised_process_snapshot"):
        params[field_name] = json.dumps(params[field_name])
    return params


def _daemon_supervised_process_event_params(
    event: Mapping[str, Any],
) -> dict[str, Any]:
    params = validate_artifact_retention_scheduler_daemon_supervised_process_event(
        event
    )
    params["summary"] = json.dumps(params["summary"])
    params["metadata"] = json.dumps(params["metadata"])
    return params


def _daemon_supervised_process_record_from_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    return validate_artifact_retention_scheduler_daemon_supervised_process_record(
        {
            "daemon_supervised_process_record_id": data[
                "daemon_supervised_process_record_id"
            ],
            "daemon_supervised_process_record_schema_version": data[
                "daemon_supervised_process_record_schema_version"
            ],
            "service_id": data["service_id"],
            "scheduler_id": data["scheduler_id"],
            "daemon_supervisor_command_id": data[
                "daemon_supervisor_command_id"
            ],
            "daemon_supervised_process_id": data[
                "daemon_supervised_process_id"
            ],
            "action": data["action"],
            "process_status": data["process_status"],
            "process_mode": data["process_mode"],
            "process_id": data["process_id"],
            "host_id": data["host_id"],
            "observed_at": _daemon_datetime_value(data["observed_at"]),
            "started_at": (
                _daemon_datetime_value(data["started_at"])
                if data["started_at"] is not None
                else None
            ),
            "completed_at": (
                _daemon_datetime_value(data["completed_at"])
                if data["completed_at"] is not None
                else None
            ),
            "exit_code": data["exit_code"],
            "termination_signal": data["termination_signal"],
            "process_running": bool(data["process_running"]),
            "process_started_observed": bool(
                data["process_started_observed"]
            ),
            "process_stopped_observed": bool(
                data["process_stopped_observed"]
            ),
            "subprocess_adapter_required": bool(
                data["subprocess_adapter_required"]
            ),
            "message": data["message"],
            "summary": _daemon_json_value(data["summary"], {}),
            "metadata": _daemon_json_value(data["metadata"], {}),
            "supervised_process_snapshot": _daemon_json_value(
                data["supervised_process_snapshot"],
                {},
            ),
            "supervised_process_snapshot_hash": data[
                "supervised_process_snapshot_hash"
            ],
            "created_at": _daemon_datetime_value(data["created_at"]),
        }
    )


def _daemon_supervised_process_event_from_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    return validate_artifact_retention_scheduler_daemon_supervised_process_event(
        {
            "daemon_supervised_process_event_id": data[
                "daemon_supervised_process_event_id"
            ],
            "daemon_supervised_process_event_schema_version": data[
                "daemon_supervised_process_event_schema_version"
            ],
            "daemon_supervised_process_record_id": data[
                "daemon_supervised_process_record_id"
            ],
            "daemon_supervised_process_id": data[
                "daemon_supervised_process_id"
            ],
            "daemon_supervisor_command_id": data[
                "daemon_supervisor_command_id"
            ],
            "service_id": data["service_id"],
            "scheduler_id": data["scheduler_id"],
            "action": data["action"],
            "process_status": data["process_status"],
            "event_type": data["event_type"],
            "occurred_at": _daemon_datetime_value(data["occurred_at"]),
            "summary": _daemon_json_value(data["summary"], {}),
            "metadata": _daemon_json_value(data["metadata"], {}),
            "created_at": _daemon_datetime_value(data["created_at"]),
        }
    )


def _ensure_daemon_supervisor_store_schema(session: Any) -> None:
    dialect_name = _daemon_store_dialect_name(session)
    json_type = "JSONB" if dialect_name == "postgresql" else "TEXT"
    session.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS
                ae_artifact_retention_scheduler_daemon_supervisor_results (
                    daemon_supervisor_record_id TEXT PRIMARY KEY,
                    daemon_supervisor_record_schema_version TEXT NOT NULL,
                    service_id TEXT NOT NULL,
                    scheduler_id TEXT NOT NULL,
                    daemon_supervisor_command_id TEXT NOT NULL,
                    daemon_supervisor_result_id TEXT NOT NULL UNIQUE,
                    action TEXT NOT NULL,
                    result_status TEXT NOT NULL,
                    decision_reason TEXT NOT NULL,
                    observed_at TIMESTAMPTZ NOT NULL,
                    checked_at TIMESTAMPTZ NOT NULL,
                    runtime_ready BOOLEAN NOT NULL,
                    supervisor_adapter_available BOOLEAN NOT NULL,
                    supervisor_adapter_invoked BOOLEAN NOT NULL,
                    adapter_name TEXT,
                    process_started BOOLEAN NOT NULL,
                    process_stopped BOOLEAN NOT NULL,
                    message TEXT,
                    summary {json_type} NOT NULL,
                    metadata {json_type} NOT NULL,
                    supervisor_command {json_type} NOT NULL,
                    supervisor_result {json_type} NOT NULL,
                    supervisor_result_hash TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                )
            """
        )
    )
    session.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS
                ae_artifact_retention_scheduler_daemon_supervisor_events (
                    daemon_supervisor_event_id TEXT PRIMARY KEY,
                    daemon_supervisor_event_schema_version TEXT NOT NULL,
                    daemon_supervisor_record_id TEXT NOT NULL,
                    daemon_supervisor_command_id TEXT NOT NULL,
                    daemon_supervisor_result_id TEXT NOT NULL,
                    service_id TEXT NOT NULL,
                    scheduler_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    result_status TEXT NOT NULL,
                    decision_reason TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    occurred_at TIMESTAMPTZ NOT NULL,
                    summary {json_type} NOT NULL,
                    metadata {json_type} NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                )
            """
        )
    )
    for statement in (
        """
        CREATE INDEX IF NOT EXISTS
            idx_ae_daemon_supervisor_results_observed
        ON ae_artifact_retention_scheduler_daemon_supervisor_results
            (scheduler_id, observed_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS
            idx_ae_daemon_supervisor_results_action
        ON ae_artifact_retention_scheduler_daemon_supervisor_results
            (action, result_status, observed_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS
            idx_ae_daemon_supervisor_events_record
        ON ae_artifact_retention_scheduler_daemon_supervisor_events
            (daemon_supervisor_record_id, occurred_at ASC)
        """,
        """
        CREATE INDEX IF NOT EXISTS
            idx_ae_daemon_supervisor_events_scheduler
        ON ae_artifact_retention_scheduler_daemon_supervisor_events
            (scheduler_id, occurred_at DESC)
        """,
    ):
        session.execute(text(statement))


def _daemon_supervisor_record_upsert_sql(dialect_name: str) -> str:
    json_exprs = {
        field_name: _daemon_json_param_expr(field_name, dialect_name)
        for field_name in (
            "summary",
            "metadata",
            "supervisor_command",
            "supervisor_result",
        )
    }
    return f"""
        INSERT INTO ae_artifact_retention_scheduler_daemon_supervisor_results (
            daemon_supervisor_record_id,
            daemon_supervisor_record_schema_version,
            service_id,
            scheduler_id,
            daemon_supervisor_command_id,
            daemon_supervisor_result_id,
            action,
            result_status,
            decision_reason,
            observed_at,
            checked_at,
            runtime_ready,
            supervisor_adapter_available,
            supervisor_adapter_invoked,
            adapter_name,
            process_started,
            process_stopped,
            message,
            summary,
            metadata,
            supervisor_command,
            supervisor_result,
            supervisor_result_hash,
            created_at
        )
        VALUES (
            :daemon_supervisor_record_id,
            :daemon_supervisor_record_schema_version,
            :service_id,
            :scheduler_id,
            :daemon_supervisor_command_id,
            :daemon_supervisor_result_id,
            :action,
            :result_status,
            :decision_reason,
            :observed_at,
            :checked_at,
            :runtime_ready,
            :supervisor_adapter_available,
            :supervisor_adapter_invoked,
            :adapter_name,
            :process_started,
            :process_stopped,
            :message,
            {json_exprs['summary']},
            {json_exprs['metadata']},
            {json_exprs['supervisor_command']},
            {json_exprs['supervisor_result']},
            :supervisor_result_hash,
            :created_at
        )
        ON CONFLICT (daemon_supervisor_record_id) DO UPDATE SET
            result_status = excluded.result_status,
            decision_reason = excluded.decision_reason,
            runtime_ready = excluded.runtime_ready,
            supervisor_adapter_available =
                excluded.supervisor_adapter_available,
            supervisor_adapter_invoked = excluded.supervisor_adapter_invoked,
            adapter_name = excluded.adapter_name,
            process_started = excluded.process_started,
            process_stopped = excluded.process_stopped,
            message = excluded.message,
            summary = excluded.summary,
            metadata = excluded.metadata,
            supervisor_command = excluded.supervisor_command,
            supervisor_result = excluded.supervisor_result,
            supervisor_result_hash = excluded.supervisor_result_hash,
            created_at = excluded.created_at
    """


def _daemon_supervisor_event_upsert_sql(dialect_name: str) -> str:
    summary_expr = _daemon_json_param_expr("summary", dialect_name)
    metadata_expr = _daemon_json_param_expr("metadata", dialect_name)
    return f"""
        INSERT INTO ae_artifact_retention_scheduler_daemon_supervisor_events (
            daemon_supervisor_event_id,
            daemon_supervisor_event_schema_version,
            daemon_supervisor_record_id,
            daemon_supervisor_command_id,
            daemon_supervisor_result_id,
            service_id,
            scheduler_id,
            action,
            result_status,
            decision_reason,
            event_type,
            occurred_at,
            summary,
            metadata,
            created_at
        )
        VALUES (
            :daemon_supervisor_event_id,
            :daemon_supervisor_event_schema_version,
            :daemon_supervisor_record_id,
            :daemon_supervisor_command_id,
            :daemon_supervisor_result_id,
            :service_id,
            :scheduler_id,
            :action,
            :result_status,
            :decision_reason,
            :event_type,
            :occurred_at,
            {summary_expr},
            {metadata_expr},
            :created_at
        )
        ON CONFLICT (daemon_supervisor_event_id) DO UPDATE SET
            result_status = excluded.result_status,
            decision_reason = excluded.decision_reason,
            occurred_at = excluded.occurred_at,
            summary = excluded.summary,
            metadata = excluded.metadata,
            created_at = excluded.created_at
    """


def _daemon_supervisor_record_select_sql(where_clause: str) -> str:
    return f"""
        SELECT
            daemon_supervisor_record_id,
            daemon_supervisor_record_schema_version,
            service_id,
            scheduler_id,
            daemon_supervisor_command_id,
            daemon_supervisor_result_id,
            action,
            result_status,
            decision_reason,
            observed_at,
            checked_at,
            runtime_ready,
            supervisor_adapter_available,
            supervisor_adapter_invoked,
            adapter_name,
            process_started,
            process_stopped,
            message,
            summary,
            metadata,
            supervisor_command,
            supervisor_result,
            supervisor_result_hash,
            created_at
        FROM ae_artifact_retention_scheduler_daemon_supervisor_results
        WHERE {where_clause}
    """


def _daemon_supervisor_event_select_sql(where_clause: str) -> str:
    return f"""
        SELECT
            daemon_supervisor_event_id,
            daemon_supervisor_event_schema_version,
            daemon_supervisor_record_id,
            daemon_supervisor_command_id,
            daemon_supervisor_result_id,
            service_id,
            scheduler_id,
            action,
            result_status,
            decision_reason,
            event_type,
            occurred_at,
            summary,
            metadata,
            created_at
        FROM ae_artifact_retention_scheduler_daemon_supervisor_events
        WHERE {where_clause}
    """


def _daemon_supervisor_record_params(record: Mapping[str, Any]) -> dict[str, Any]:
    params = validate_artifact_retention_scheduler_daemon_supervisor_record(
        record
    )
    for field_name in (
        "summary",
        "metadata",
        "supervisor_command",
        "supervisor_result",
    ):
        params[field_name] = json.dumps(params[field_name])
    return params


def _daemon_supervisor_event_params(event: Mapping[str, Any]) -> dict[str, Any]:
    params = validate_artifact_retention_scheduler_daemon_supervisor_event(event)
    params["summary"] = json.dumps(params["summary"])
    params["metadata"] = json.dumps(params["metadata"])
    return params


def _daemon_supervisor_record_from_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    return validate_artifact_retention_scheduler_daemon_supervisor_record(
        {
            "daemon_supervisor_record_id": data[
                "daemon_supervisor_record_id"
            ],
            "daemon_supervisor_record_schema_version": data[
                "daemon_supervisor_record_schema_version"
            ],
            "service_id": data["service_id"],
            "scheduler_id": data["scheduler_id"],
            "daemon_supervisor_command_id": data[
                "daemon_supervisor_command_id"
            ],
            "daemon_supervisor_result_id": data["daemon_supervisor_result_id"],
            "action": data["action"],
            "result_status": data["result_status"],
            "decision_reason": data["decision_reason"],
            "observed_at": _daemon_datetime_value(data["observed_at"]),
            "checked_at": _daemon_datetime_value(data["checked_at"]),
            "runtime_ready": bool(data["runtime_ready"]),
            "supervisor_adapter_available": bool(
                data["supervisor_adapter_available"]
            ),
            "supervisor_adapter_invoked": bool(data["supervisor_adapter_invoked"]),
            "adapter_name": data["adapter_name"],
            "process_started": bool(data["process_started"]),
            "process_stopped": bool(data["process_stopped"]),
            "message": data["message"],
            "summary": _daemon_json_value(data["summary"], {}),
            "metadata": _daemon_json_value(data["metadata"], {}),
            "supervisor_command": _daemon_json_value(
                data["supervisor_command"],
                {},
            ),
            "supervisor_result": _daemon_json_value(
                data["supervisor_result"],
                {},
            ),
            "supervisor_result_hash": data["supervisor_result_hash"],
            "created_at": _daemon_datetime_value(data["created_at"]),
        }
    )


def _daemon_supervisor_event_from_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    return validate_artifact_retention_scheduler_daemon_supervisor_event(
        {
            "daemon_supervisor_event_id": data["daemon_supervisor_event_id"],
            "daemon_supervisor_event_schema_version": data[
                "daemon_supervisor_event_schema_version"
            ],
            "daemon_supervisor_record_id": data[
                "daemon_supervisor_record_id"
            ],
            "daemon_supervisor_command_id": data[
                "daemon_supervisor_command_id"
            ],
            "daemon_supervisor_result_id": data["daemon_supervisor_result_id"],
            "service_id": data["service_id"],
            "scheduler_id": data["scheduler_id"],
            "action": data["action"],
            "result_status": data["result_status"],
            "decision_reason": data["decision_reason"],
            "event_type": data["event_type"],
            "occurred_at": _daemon_datetime_value(data["occurred_at"]),
            "summary": _daemon_json_value(data["summary"], {}),
            "metadata": _daemon_json_value(data["metadata"], {}),
            "created_at": _daemon_datetime_value(data["created_at"]),
        }
    )


def _operator_control_execution_read_model_guardrails(
    *,
    read_only: bool,
) -> dict[str, bool]:
    return {
        "read_only": read_only,
        "ae_owned_persistence": True,
        "ae_owned_execution_state": True,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
        "ag_direct_process_control_allowed": False,
        "supervisor_adapter_invoked": False,
        "subprocess_started": False,
        "subprocess_stopped": False,
        "job_queue_enqueue_performed": False,
        "worker_execution_performed": False,
        "physical_delete_automation_enabled": False,
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
        "raw_supervised_process_snapshot_included": False,
        "secrets_redacted": True,
    }


def _operator_control_execution_collection_item(
    execution_state: Mapping[str, Any],
) -> dict[str, Any]:
    state = validate_artifact_retention_scheduler_daemon_operator_control_execution_state(
        execution_state
    )
    return {
        "operator_control_execution_state_id": state[
            "operator_control_execution_state_id"
        ],
        "operator_control_execution_request_id": state[
            "operator_control_execution_request_id"
        ],
        "operator_control_facade_id": state["operator_control_facade_id"],
        "scheduler_id": state["scheduler_id"],
        "action": state["action"],
        "execution_mode": state["execution_mode"],
        "execution_status": state["execution_status"],
        "idempotency_status": state["idempotency_status"],
        "decision_reason": state["decision_reason"],
        "observed_at": state["observed_at"],
        "prior_execution_state_id": state["prior_execution_state_id"],
        "allowed_next_statuses": list(state["allowed_next_statuses"]),
        "summary": (
            summarize_artifact_retention_scheduler_daemon_operator_control_execution_state(
                state
            )
        ),
        "metadata": {
            "safe_for_ag_projection": True,
            "read_model": (
                "ae_daemon_operator_control_execution_states"
            ),
            "database_url_included": False,
            "storage_path_included": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_included": False,
            "raw_daemon_runtime_payload_included": False,
            "raw_supervised_process_snapshot_included": False,
        },
    }


def _operator_control_execution_collection_metadata(
    *,
    records: Sequence[Mapping[str, Any]],
    limit: int,
) -> dict[str, Any]:
    newest_observed_at = records[0]["observed_at"] if records else None
    return {
        "safe_for_ag_projection": True,
        "read_model": (
            "ae_daemon_operator_control_execution_states"
        ),
        "item_count": len(records),
        "limit": limit,
        "has_more": len(records) == limit,
        "newest_observed_at": newest_observed_at,
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
        "raw_supervised_process_snapshot_included": False,
    }


def _operator_control_execution_detail_metadata(
    *,
    execution_state: Mapping[str, Any],
    transitions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "safe_for_ag_projection": True,
        "read_model": (
            "ae_artifact_retention_scheduler_daemon_operator_control_execution_detail"
        ),
        "operator_control_execution_state_id": execution_state[
            "operator_control_execution_state_id"
        ],
        "transition_count": len(transitions),
        "transition_statuses": [
            f"{transition['from_status']}->{transition['to_status']}"
            for transition in transitions
        ],
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
        "raw_supervised_process_snapshot_included": False,
    }


def _ensure_operator_control_execution_store_schema(session: Any) -> None:
    dialect_name = _daemon_store_dialect_name(session)
    json_type = "JSONB" if dialect_name == "postgresql" else "TEXT"
    session.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS
                ae_daemon_operator_control_execution_states (
                    operator_control_execution_state_id TEXT PRIMARY KEY,
                    operator_control_execution_state_schema_version TEXT NOT NULL,
                    service_id TEXT NOT NULL,
                    scheduler_id TEXT NOT NULL,
                    operator_control_execution_request_id TEXT NOT NULL,
                    operator_control_facade_id TEXT NOT NULL,
                    operator_control_request_id TEXT NOT NULL,
                    operator_control_admission_id TEXT NOT NULL,
                    operator_control_command_preview_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    execution_mode TEXT NOT NULL,
                    execution_status TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    idempotency_status TEXT NOT NULL,
                    decision_reason TEXT NOT NULL,
                    observed_at TIMESTAMPTZ NOT NULL,
                    prior_execution_state_id TEXT,
                    operator_control_execution_request_hash TEXT NOT NULL,
                    allowed_next_statuses {json_type} NOT NULL,
                    guardrails {json_type} NOT NULL,
                    metadata {json_type} NOT NULL,
                    operator_control_execution_request {json_type} NOT NULL,
                    execution_state_hash TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                )
            """
        )
    )
    session.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS
                ae_daemon_operator_control_execution_transitions (
                    operator_control_execution_state_transition_id TEXT PRIMARY KEY,
                    operator_control_execution_state_transition_schema_version TEXT NOT NULL,
                    service_id TEXT NOT NULL,
                    scheduler_id TEXT NOT NULL,
                    operator_control_execution_state_id TEXT NOT NULL,
                    operator_control_execution_request_id TEXT NOT NULL,
                    from_status TEXT NOT NULL,
                    to_status TEXT NOT NULL,
                    decision_reason TEXT NOT NULL,
                    transitioned_at TIMESTAMPTZ NOT NULL,
                    operator_control_execution_state {json_type} NOT NULL,
                    guardrails {json_type} NOT NULL,
                    metadata {json_type} NOT NULL,
                    transition_hash TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                )
            """
        )
    )
    for statement in (
        """
        CREATE INDEX IF NOT EXISTS
            idx_ae_operator_control_execution_states_observed
        ON ae_daemon_operator_control_execution_states
            (scheduler_id, observed_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS
            idx_ae_operator_control_execution_states_status
        ON ae_daemon_operator_control_execution_states
            (execution_status, idempotency_status, observed_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS
            idx_ae_operator_control_execution_states_idempotency
        ON ae_daemon_operator_control_execution_states
            (idempotency_key, observed_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS
            idx_ae_operator_control_execution_states_request
        ON ae_daemon_operator_control_execution_states
            (operator_control_execution_request_id, observed_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS
            idx_ae_operator_control_execution_transitions_state
        ON ae_daemon_operator_control_execution_transitions
            (operator_control_execution_state_id, transitioned_at ASC)
        """,
        """
        CREATE INDEX IF NOT EXISTS
            idx_ae_operator_control_execution_transitions_scheduler
        ON ae_daemon_operator_control_execution_transitions
            (scheduler_id, transitioned_at DESC)
        """,
    ):
        session.execute(text(statement))


def _operator_control_execution_state_upsert_sql(dialect_name: str) -> str:
    json_exprs = {
        field_name: _daemon_json_param_expr(field_name, dialect_name)
        for field_name in (
            "allowed_next_statuses",
            "guardrails",
            "metadata",
            "operator_control_execution_request",
        )
    }
    return f"""
        INSERT INTO
            ae_daemon_operator_control_execution_states (
                operator_control_execution_state_id,
                operator_control_execution_state_schema_version,
                service_id,
                scheduler_id,
                operator_control_execution_request_id,
                operator_control_facade_id,
                operator_control_request_id,
                operator_control_admission_id,
                operator_control_command_preview_id,
                action,
                execution_mode,
                execution_status,
                idempotency_key,
                idempotency_status,
                decision_reason,
                observed_at,
                prior_execution_state_id,
                operator_control_execution_request_hash,
                allowed_next_statuses,
                guardrails,
                metadata,
                operator_control_execution_request,
                execution_state_hash,
                created_at
            )
        VALUES (
            :operator_control_execution_state_id,
            :operator_control_execution_state_schema_version,
            :service_id,
            :scheduler_id,
            :operator_control_execution_request_id,
            :operator_control_facade_id,
            :operator_control_request_id,
            :operator_control_admission_id,
            :operator_control_command_preview_id,
            :action,
            :execution_mode,
            :execution_status,
            :idempotency_key,
            :idempotency_status,
            :decision_reason,
            :observed_at,
            :prior_execution_state_id,
            :operator_control_execution_request_hash,
            {json_exprs['allowed_next_statuses']},
            {json_exprs['guardrails']},
            {json_exprs['metadata']},
            {json_exprs['operator_control_execution_request']},
            :execution_state_hash,
            :created_at
        )
        ON CONFLICT (operator_control_execution_state_id) DO UPDATE SET
            execution_status = excluded.execution_status,
            idempotency_status = excluded.idempotency_status,
            decision_reason = excluded.decision_reason,
            observed_at = excluded.observed_at,
            prior_execution_state_id = excluded.prior_execution_state_id,
            operator_control_execution_request_hash =
                excluded.operator_control_execution_request_hash,
            allowed_next_statuses = excluded.allowed_next_statuses,
            guardrails = excluded.guardrails,
            metadata = excluded.metadata,
            operator_control_execution_request =
                excluded.operator_control_execution_request,
            execution_state_hash = excluded.execution_state_hash,
            created_at = excluded.created_at
    """


def _operator_control_execution_state_transition_upsert_sql(
    dialect_name: str,
) -> str:
    json_exprs = {
        field_name: _daemon_json_param_expr(field_name, dialect_name)
        for field_name in (
            "operator_control_execution_state",
            "guardrails",
            "metadata",
        )
    }
    return f"""
        INSERT INTO
            ae_daemon_operator_control_execution_transitions (
                operator_control_execution_state_transition_id,
                operator_control_execution_state_transition_schema_version,
                service_id,
                scheduler_id,
                operator_control_execution_state_id,
                operator_control_execution_request_id,
                from_status,
                to_status,
                decision_reason,
                transitioned_at,
                operator_control_execution_state,
                guardrails,
                metadata,
                transition_hash,
                created_at
            )
        VALUES (
            :operator_control_execution_state_transition_id,
            :operator_control_execution_state_transition_schema_version,
            :service_id,
            :scheduler_id,
            :operator_control_execution_state_id,
            :operator_control_execution_request_id,
            :from_status,
            :to_status,
            :decision_reason,
            :transitioned_at,
            {json_exprs['operator_control_execution_state']},
            {json_exprs['guardrails']},
            {json_exprs['metadata']},
            :transition_hash,
            :created_at
        )
        ON CONFLICT (operator_control_execution_state_transition_id) DO UPDATE SET
            to_status = excluded.to_status,
            decision_reason = excluded.decision_reason,
            transitioned_at = excluded.transitioned_at,
            operator_control_execution_state =
                excluded.operator_control_execution_state,
            guardrails = excluded.guardrails,
            metadata = excluded.metadata,
            transition_hash = excluded.transition_hash,
            created_at = excluded.created_at
    """


def _operator_control_execution_state_select_sql(where_clause: str) -> str:
    return f"""
        SELECT
            operator_control_execution_state_id,
            operator_control_execution_state_schema_version,
            service_id,
            scheduler_id,
            operator_control_execution_request_id,
            operator_control_facade_id,
            operator_control_request_id,
            operator_control_admission_id,
            operator_control_command_preview_id,
            action,
            execution_mode,
            execution_status,
            idempotency_key,
            idempotency_status,
            decision_reason,
            observed_at,
            prior_execution_state_id,
            operator_control_execution_request_hash,
            allowed_next_statuses,
            guardrails,
            metadata,
            operator_control_execution_request,
            execution_state_hash,
            created_at
        FROM
            ae_daemon_operator_control_execution_states
        WHERE {where_clause}
    """


def _operator_control_execution_state_transition_select_sql(
    where_clause: str,
) -> str:
    return f"""
        SELECT
            operator_control_execution_state_transition_id,
            operator_control_execution_state_transition_schema_version,
            service_id,
            scheduler_id,
            operator_control_execution_state_id,
            operator_control_execution_request_id,
            from_status,
            to_status,
            decision_reason,
            transitioned_at,
            operator_control_execution_state,
            guardrails,
            metadata,
            transition_hash,
            created_at
        FROM
            ae_daemon_operator_control_execution_transitions
        WHERE {where_clause}
    """


def _operator_control_execution_state_params(
    execution_state: Mapping[str, Any],
) -> dict[str, Any]:
    params = validate_artifact_retention_scheduler_daemon_operator_control_execution_state(
        execution_state
    )
    for field_name in (
        "allowed_next_statuses",
        "guardrails",
        "metadata",
        "operator_control_execution_request",
    ):
        params[field_name] = json.dumps(params[field_name])
    params["execution_state_hash"] = sha256_json(dict(execution_state))
    params["created_at"] = params["observed_at"]
    return params


def _operator_control_execution_state_transition_params(
    transition: Mapping[str, Any],
) -> dict[str, Any]:
    params = validate_artifact_retention_scheduler_daemon_operator_control_execution_state_transition(
        transition
    )
    for field_name in (
        "operator_control_execution_state",
        "guardrails",
        "metadata",
    ):
        params[field_name] = json.dumps(params[field_name])
    params["transition_hash"] = sha256_json(dict(transition))
    params["created_at"] = params["transitioned_at"]
    return params


def _operator_control_execution_state_from_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    state = {
        "operator_control_execution_state_schema_version": data[
            "operator_control_execution_state_schema_version"
        ],
        "operator_control_execution_state_id": data[
            "operator_control_execution_state_id"
        ],
        "service_id": data["service_id"],
        "scheduler_id": data["scheduler_id"],
        "operator_control_execution_request_id": data[
            "operator_control_execution_request_id"
        ],
        "operator_control_facade_id": data["operator_control_facade_id"],
        "operator_control_request_id": data["operator_control_request_id"],
        "operator_control_admission_id": data["operator_control_admission_id"],
        "operator_control_command_preview_id": data[
            "operator_control_command_preview_id"
        ],
        "action": data["action"],
        "execution_mode": data["execution_mode"],
        "execution_status": data["execution_status"],
        "idempotency_key": data["idempotency_key"],
        "idempotency_status": data["idempotency_status"],
        "decision_reason": data["decision_reason"],
        "observed_at": _daemon_datetime_value(data["observed_at"]),
        "prior_execution_state_id": data["prior_execution_state_id"],
        "operator_control_execution_request_hash": data[
            "operator_control_execution_request_hash"
        ],
        "operator_control_execution_request": _daemon_json_value(
            data["operator_control_execution_request"],
            {},
        ),
        "allowed_next_statuses": _daemon_json_value(
            data["allowed_next_statuses"],
            [],
        ),
        "guardrails": _daemon_json_value(data["guardrails"], {}),
        "metadata": _daemon_json_value(data["metadata"], {}),
    }
    normalized = (
        validate_artifact_retention_scheduler_daemon_operator_control_execution_state(
            state
        )
    )
    if data["execution_state_hash"] != sha256_json(dict(normalized)):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon operator control "
                "execution state hash is invalid."
            ),
        )
    return normalized


def _operator_control_execution_state_transition_from_row(
    row: Any,
) -> dict[str, Any]:
    data = dict(row)
    transition = {
        "operator_control_execution_state_transition_schema_version": data[
            "operator_control_execution_state_transition_schema_version"
        ],
        "operator_control_execution_state_transition_id": data[
            "operator_control_execution_state_transition_id"
        ],
        "service_id": data["service_id"],
        "scheduler_id": data["scheduler_id"],
        "operator_control_execution_state_id": data[
            "operator_control_execution_state_id"
        ],
        "operator_control_execution_request_id": data[
            "operator_control_execution_request_id"
        ],
        "from_status": data["from_status"],
        "to_status": data["to_status"],
        "decision_reason": data["decision_reason"],
        "transitioned_at": _daemon_datetime_value(data["transitioned_at"]),
        "operator_control_execution_state": _daemon_json_value(
            data["operator_control_execution_state"],
            {},
        ),
        "guardrails": _daemon_json_value(data["guardrails"], {}),
        "metadata": _daemon_json_value(data["metadata"], {}),
    }
    normalized = validate_artifact_retention_scheduler_daemon_operator_control_execution_state_transition(
        transition
    )
    if data["transition_hash"] != sha256_json(dict(normalized)):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=(
                "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_transition_invalid"
            ),
            detail=(
                "Artifact retention scheduler daemon operator control "
                "execution state transition hash is invalid."
            ),
        )
    return normalized


def _optional_operator_control_execution_action(
    value: Any,
    *,
    error_code: str,
) -> str | None:
    action = optional_text(value)
    if action is None:
        return None
    try:
        return _normalize_daemon_operator_control_action(action)
    except ArtifactHandoffError as exc:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon operator control "
                "execution collection action is invalid."
            ),
        ) from exc


def _optional_operator_control_execution_state_status(
    value: Any,
    *,
    error_code: str,
) -> str | None:
    status = optional_text(value)
    if status is None:
        return None
    return _normalize_operator_control_execution_state_status(
        status,
        error_code=error_code,
    )


def _optional_operator_control_execution_idempotency_status(
    value: Any,
    *,
    error_code: str,
) -> str | None:
    status = optional_text(value)
    if status is None:
        return None
    return _normalize_operator_control_idempotency_status(
        status,
        error_code=error_code,
    )


def _daemon_supervisor_action_for_context(
    value: Any,
    *,
    error_code: str,
) -> str:
    action = _required_text(value, "action", error_code=error_code).lower()
    if action not in AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_ACTIONS:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor action is "
                "invalid."
            ),
        )
    return action


def _optional_daemon_supervisor_action(
    value: Any,
    *,
    error_code: str,
) -> str | None:
    action = optional_text(value)
    if action is None:
        return None
    return _daemon_supervisor_action_for_context(action, error_code=error_code)


def _daemon_supervisor_result_status_for_context(
    value: Any,
    *,
    error_code: str,
) -> str:
    status = _required_text(value, "result_status", error_code=error_code).upper()
    if status not in AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_RESULT_STATUSES:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervisor result status "
                "is invalid."
            ),
        )
    return status


def _optional_daemon_supervisor_result_status(
    value: Any,
    *,
    error_code: str,
) -> str | None:
    status = optional_text(value)
    if status is None:
        return None
    return _daemon_supervisor_result_status_for_context(
        status,
        error_code=error_code,
    )


def _default_daemon_supervised_process_status(action: str) -> str:
    if action == "start_daemon":
        return "START_REQUESTED"
    if action == "stop_daemon":
        return "STOP_REQUESTED"
    return "MISSING"


def _normalize_daemon_supervised_process_status(
    value: Any,
    *,
    error_code: str = (
        "ae.artifact_retention_scheduler_daemon_supervised_process_invalid"
    ),
) -> str:
    status = _required_text(
        value,
        "process_status",
        error_code=error_code,
    ).upper()
    if status not in AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_STATUSES:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervised process status "
                "is invalid."
            ),
        )
    return status


def _optional_daemon_supervised_process_status(
    value: Any,
    *,
    error_code: str,
) -> str | None:
    status = optional_text(value)
    if status is None:
        return None
    return _normalize_daemon_supervised_process_status(
        status,
        error_code=error_code,
    )


def _optional_daemon_supervised_process_id(
    value: Any,
    *,
    error_code: str,
) -> int | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    return _bounded_positive_int(
        value,
        "process_id",
        max_value=MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_PROCESS_ID,
        error_code=error_code,
    )


def _optional_daemon_supervised_exit_code(
    value: Any,
    *,
    error_code: str,
) -> int | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    if isinstance(value, bool):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervised process exit "
                "code must be an integer."
            ),
        )
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervised process exit "
                "code must be an integer."
            ),
        ) from exc
    if normalized < -255 or normalized > 255:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervised process exit "
                "code exceeds supported range."
            ),
        )
    return normalized


def _daemon_supervised_process_process(
    *,
    command: Mapping[str, Any],
    process_id: int | str | None,
    host_id: str,
) -> dict[str, Any]:
    error_code = "ae.artifact_retention_scheduler_daemon_supervised_process_invalid"
    supervisor_command = command["command"]
    return {
        "process_id": _optional_daemon_supervised_process_id(
            process_id,
            error_code=error_code,
        ),
        "host_id": _required_text(host_id, "host_id", error_code=error_code),
        "entrypoint": supervisor_command["entrypoint"],
        "supervisor_mode": supervisor_command["supervisor_mode"],
        "max_cycles": supervisor_command["max_cycles"],
        "run_worker": supervisor_command["run_worker"],
        "output_format": supervisor_command["output_format"],
    }


def _validate_daemon_supervised_process_process(
    value: Any,
    *,
    error_code: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervised process payload "
                "is invalid."
            ),
        )
    process = dict(value)
    if set(process) != {
        "process_id",
        "host_id",
        "entrypoint",
        "supervisor_mode",
        "max_cycles",
        "run_worker",
        "output_format",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervised process payload "
                "keys are invalid."
            ),
        )
    return {
        "process_id": _optional_daemon_supervised_process_id(
            process.get("process_id"),
            error_code=error_code,
        ),
        "host_id": _required_text(
            process.get("host_id"),
            "host_id",
            error_code=error_code,
        ),
        "entrypoint": _required_text(
            process.get("entrypoint"),
            "entrypoint",
            error_code=error_code,
        ),
        "supervisor_mode": _required_text(
            process.get("supervisor_mode"),
            "supervisor_mode",
            error_code=error_code,
        ),
        "max_cycles": _bounded_positive_int(
            process.get("max_cycles"),
            "max_cycles",
            max_value=MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_MAX_CYCLES,
            error_code=error_code,
        ),
        "run_worker": _required_bool(
            process.get("run_worker"),
            "run_worker",
            error_code=error_code,
        ),
        "output_format": _normalize_output_format(
            process.get("output_format"),
            error_code=error_code,
        ),
    }


def _daemon_supervised_process_lifecycle(
    *,
    process_status: str,
    observed_at: str,
    started_at: str | None,
    completed_at: str | None,
    exit_code: int | str | None,
    termination_signal: str | None,
) -> dict[str, Any]:
    error_code = "ae.artifact_retention_scheduler_daemon_supervised_process_invalid"
    return {
        "process_status": process_status,
        "observed_at": _required_text(
            observed_at,
            "observed_at",
            error_code=error_code,
        ),
        "started_at": optional_text(started_at),
        "completed_at": optional_text(completed_at),
        "exit_code": _optional_daemon_supervised_exit_code(
            exit_code,
            error_code=error_code,
        ),
        "termination_signal": optional_text(termination_signal),
    }


def _validate_daemon_supervised_process_lifecycle(
    value: Any,
    *,
    error_code: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervised process "
                "lifecycle is invalid."
            ),
        )
    lifecycle = dict(value)
    if set(lifecycle) != {
        "process_status",
        "observed_at",
        "started_at",
        "completed_at",
        "exit_code",
        "termination_signal",
    }:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervised process "
                "lifecycle keys are invalid."
            ),
        )
    return {
        "process_status": _normalize_daemon_supervised_process_status(
            lifecycle.get("process_status")
        ),
        "observed_at": _required_text(
            lifecycle.get("observed_at"),
            "observed_at",
            error_code=error_code,
        ),
        "started_at": optional_text(lifecycle.get("started_at")),
        "completed_at": optional_text(lifecycle.get("completed_at")),
        "exit_code": _optional_daemon_supervised_exit_code(
            lifecycle.get("exit_code"),
            error_code=error_code,
        ),
        "termination_signal": optional_text(lifecycle.get("termination_signal")),
    }


def _ensure_daemon_supervised_process_consistency(
    *,
    action: str,
    scheduler_id: str,
    command_id: str,
    process: Mapping[str, Any],
    lifecycle: Mapping[str, Any],
    error_code: str,
) -> None:
    if not scheduler_id or not command_id:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervised process scope "
                "is invalid."
            ),
        )
    status = lifecycle["process_status"]
    process_id = process["process_id"]
    started_at = lifecycle["started_at"]
    completed_at = lifecycle["completed_at"]
    exit_code = lifecycle["exit_code"]
    termination_signal = lifecycle["termination_signal"]
    allowed_by_action = {
        "status_probe": {"MISSING", "RUNNING", "STALE", "EXITED", "FAILED"},
        "start_daemon": {"START_REQUESTED", "RUNNING", "BLOCKED", "FAILED"},
        "stop_daemon": {"STOP_REQUESTED", "STOPPED", "MISSING", "FAILED"},
    }
    if status not in allowed_by_action[action]:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervised process action "
                "and status are inconsistent."
            ),
        )
    if status in {"RUNNING", "STOP_REQUESTED", "STOPPED", "EXITED", "STALE", "FAILED"}:
        if process_id is None:
            raise ArtifactHandoffError(
                status_code=422,
                error_code=error_code,
                detail=(
                    "Artifact retention scheduler daemon supervised process id "
                    "is required for observed processes."
                ),
            )
    elif process_id is not None:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervised process id must "
                "not be present before process creation."
            ),
        )
    if status in {"RUNNING", "STOP_REQUESTED", "STALE"} and (
        started_at is None or completed_at is not None
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon active supervised process "
                "timestamps are invalid."
            ),
        )
    if status == "STOPPED" and (
        started_at is None or completed_at is None or termination_signal is None
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon stopped supervised process "
                "metadata is invalid."
            ),
        )
    if status == "EXITED" and (
        started_at is None or completed_at is None or exit_code is None
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon exited supervised process "
                "metadata is invalid."
            ),
        )
    if status in {"MISSING", "START_REQUESTED", "BLOCKED"} and (
        started_at is not None or completed_at is not None
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon inactive supervised "
                "process timestamps are invalid."
            ),
        )
    if status not in {"STOPPED"} and termination_signal is not None:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervised process "
                "termination signal is invalid."
            ),
        )
    if status != "EXITED" and exit_code is not None:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon supervised process exit "
                "code is invalid."
            ),
        )


def _daemon_supervised_process_guardrails(
    *,
    command: Mapping[str, Any],
    lifecycle: Mapping[str, Any],
) -> dict[str, bool]:
    action = command["command"]["action"]
    return {
        "metadata_only": True,
        "daemon_process_owner_ae": True,
        "supervisor_owner_ae": True,
        "subprocess_adapter_required": action in {"start_daemon", "stop_daemon"},
        "contract_starts_process": False,
        "contract_stops_process": False,
        "process_lock_required": True,
        "pid_metadata_required": True,
        "test_profile_required": True,
        "explicit_opt_in_required": action == "start_daemon",
        "bounded_max_cycles_required": True,
        "postgres_smoke_required_before_enablement": True,
        "production_continuous_start_enabled": False,
        "database_url_included": False,
        "local_storage_path_included": False,
        "execution_payload_included": False,
        "secrets_redacted": True,
        "ag_direct_process_control_allowed": False,
        "ag_direct_database_write_allowed": False,
        "process_running_observed": lifecycle["process_status"]
        in {"RUNNING", "STOP_REQUESTED"},
    }


def _daemon_supervised_process_metadata(
    *,
    command: Mapping[str, Any],
    process: Mapping[str, Any],
    lifecycle: Mapping[str, Any],
    message: Any,
) -> dict[str, Any]:
    status = lifecycle["process_status"]
    started_observed = lifecycle["started_at"] is not None
    stopped_observed = status in {"STOPPED", "EXITED"}
    return {
        "safe_for_ag_projection": True,
        "metadata_only": True,
        "message": optional_text(message),
        "scheduler_id": command["scheduler_id"],
        "daemon_supervisor_command_id": command["daemon_supervisor_command_id"],
        "action": command["command"]["action"],
        "process_status": status,
        "process_running": status in {"RUNNING", "STOP_REQUESTED"},
        "process_started_observed": started_observed,
        "process_stopped_observed": stopped_observed,
        "process_exit_observed": lifecycle["exit_code"] is not None,
        "termination_signal_observed": lifecycle["termination_signal"] is not None,
        "host_id_recorded": process["host_id"] is not None,
        "process_id_recorded": process["process_id"] is not None,
        "database_url_included": False,
        "local_storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "secrets_redacted": True,
    }


def _daemon_supervised_process_id(
    *,
    scheduler_id: str,
    command_id: str,
    process: Mapping[str, Any],
    lifecycle: Mapping[str, Any],
) -> str:
    basis = {
        "scheduler_id": scheduler_id,
        "daemon_supervisor_command_id": command_id,
        "process_id": process["process_id"],
        "host_id": process["host_id"],
        "process_status": lifecycle["process_status"],
        "observed_at": lifecycle["observed_at"],
        "started_at": lifecycle["started_at"],
        "completed_at": lifecycle["completed_at"],
        "exit_code": lifecycle["exit_code"],
        "termination_signal": lifecycle["termination_signal"],
    }
    return str(
        uuid5(
            NAMESPACE_URL,
            f"ae-artifact-retention-scheduler-daemon-supervised-process:{sha256_json(basis)}",
        )
    )


def _daemon_supervisor_store_unavailable() -> ArtifactHandoffError:
    return ArtifactHandoffError(
        status_code=503,
        error_code=(
            "ae.artifact_retention_scheduler_daemon_supervisor_store_unavailable"
        ),
        detail=(
            "AE artifact retention scheduler daemon supervisor store is "
            "unavailable."
        ),
        retryable=True,
    )


def _daemon_supervised_process_store_unavailable() -> ArtifactHandoffError:
    return ArtifactHandoffError(
        status_code=503,
        error_code=(
            "ae.artifact_retention_scheduler_daemon_supervised_process_store_unavailable"
        ),
        detail=(
            "AE artifact retention scheduler daemon supervised process store "
            "is unavailable."
        ),
        retryable=True,
    )


def _operator_control_execution_store_unavailable() -> ArtifactHandoffError:
    return ArtifactHandoffError(
        status_code=503,
        error_code=(
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_store_unavailable"
        ),
        detail=(
            "AE artifact retention scheduler daemon operator control execution "
            "store is unavailable."
        ),
        retryable=True,
    )


def _daemon_run_status(
    value: Any,
    *,
    error_code: str,
) -> str:
    status = _required_text(value, "run_status", error_code=error_code)
    if status not in AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUN_STATUSES:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail="Artifact retention scheduler daemon run status is invalid.",
        )
    return status


def _daemon_result_status(
    value: Any,
    *,
    error_code: str,
) -> str:
    status = _required_text(value, "result_status", error_code=error_code)
    if status not in AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RESULT_STATUSES:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail="Artifact retention scheduler daemon result status is invalid.",
        )
    return status


def _optional_daemon_result_status(
    value: Any,
    *,
    error_code: str,
) -> str | None:
    status = optional_text(value)
    if status is None:
        return None
    return _daemon_result_status(status, error_code=error_code)


def _non_negative_int(
    value: Any,
    field_name: str,
    *,
    error_code: str,
) -> int:
    if isinstance(value, bool):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon CLI "
                f"{field_name} must be a non-negative integer."
            ),
        )
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon CLI "
                f"{field_name} must be a non-negative integer."
            ),
        ) from exc
    if normalized < 0:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon CLI "
                f"{field_name} must be a non-negative integer."
            ),
        )
    return normalized


def _daemon_store_dialect_name(session: Any) -> str:
    bind = getattr(session, "bind", None)
    dialect = getattr(bind, "dialect", None)
    name = getattr(dialect, "name", "")
    return str(name)


def _daemon_json_param_expr(field_name: str, dialect_name: str) -> str:
    if dialect_name == "postgresql":
        return f"CAST(:{field_name} AS jsonb)"
    return f":{field_name}"


def _daemon_json_value(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        return json.loads(value)
    return value


def _daemon_datetime_value(value: Any) -> str:
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if hasattr(value, "isoformat"):
        return value.isoformat().replace("+00:00", "Z")
    return str(value)


def _daemon_run_store_unavailable() -> ArtifactHandoffError:
    return ArtifactHandoffError(
        status_code=503,
        error_code="ae.artifact_retention_scheduler_daemon_run_store_unavailable",
        detail="AE artifact retention scheduler daemon run store is unavailable.",
        retryable=True,
    )


def _daemon_process_lock_owner(
    *,
    scheduler_id: str,
    process_id: int,
    host_id: str,
) -> str:
    return f"{scheduler_id}:{host_id}:{process_id}"


def _normalize_output_format(
    value: Any,
    *,
    error_code: str = "ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
) -> str:
    output_format = optional_text(value)
    if output_format not in {"json", "summary"}:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail="Artifact retention scheduler daemon CLI output format is invalid.",
        )
    return output_format


def _bounded_positive_int(
    value: Any,
    field_name: str,
    *,
    max_value: int,
    error_code: str = "ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
) -> int:
    normalized = _positive_int(value, field_name, error_code=error_code)
    if normalized > max_value:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon CLI "
                f"{field_name} exceeds supported maximum."
            ),
        )
    return normalized


def _positive_int(
    value: Any,
    field_name: str,
    *,
    error_code: str = "ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
) -> int:
    if isinstance(value, bool):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon CLI "
                f"{field_name} must be a positive integer."
            ),
        )
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon CLI "
                f"{field_name} must be a positive integer."
            ),
        ) from exc
    if normalized < 1:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon CLI "
                f"{field_name} must be a positive integer."
            ),
        )
    return normalized


def _required_bool(
    value: Any,
    field_name: str,
    *,
    error_code: str = "ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
) -> bool:
    if not isinstance(value, bool):
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon CLI "
                f"{field_name} must be a boolean."
            ),
        )
    return value


def _required_text(
    value: Any,
    field_name: str,
    *,
    error_code: str = "ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
) -> str:
    text = optional_text(value)
    if text is None:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=(
                "Artifact retention scheduler daemon CLI "
                f"{field_name} is required."
            ),
        )
    return text


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
