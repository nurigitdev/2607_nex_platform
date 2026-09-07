from __future__ import annotations

import argparse
import json
import os
import sys
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Callable, Mapping, Sequence, TextIO
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
DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ENTRYPOINT = (
    "python -m nex_ae_api.artifact_retention_scheduler_daemon"
)
MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_MAX_CYCLES = 100
MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_PROCESS_ID = 2_147_483_647
MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_PROCESS_LOCK_STALE_AFTER_SECONDS = 86_400
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
