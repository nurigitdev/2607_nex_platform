from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from typing import Any, Mapping, Sequence, TextIO
from uuid import NAMESPACE_URL, uuid5

from nex_ae_api.artifact_retention_scheduler import (
    build_artifact_retention_scheduler_daemon_config,
    build_artifact_retention_scheduler_daemon_runtime_config,
    build_artifact_retention_scheduler_daemon_runtime_state,
    summarize_artifact_retention_scheduler_daemon_runtime_state,
    validate_artifact_retention_scheduler_daemon_config,
    validate_artifact_retention_scheduler_daemon_runtime_config,
    validate_artifact_retention_scheduler_daemon_runtime_state,
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
DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ENTRYPOINT = (
    "python -m nex_ae_api.artifact_retention_scheduler_daemon"
)
MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_MAX_CYCLES = 100
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_EXECUTE_MODE = "bounded_loop"


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


def main(argv: Sequence[str] | None = None, out: TextIO | None = None) -> int:
    stream = out if out is not None else sys.stdout
    args = build_parser().parse_args(argv)
    try:
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
    output = (
        summary_line(plan)
        if args.summary
        else json.dumps(plan, ensure_ascii=False, sort_keys=True)
    )
    print(output, file=stream)
    return 0


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
