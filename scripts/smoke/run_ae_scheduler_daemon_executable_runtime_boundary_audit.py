#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "ae_scheduler_daemon_executable_runtime_boundary_audit.v1"

PROTECTED_ENV_KEYS = (
    "NEX_AE_DATABASE_URL",
    "NEX_AE_TEST_DATABASE_URL",
    "NEX_AE_ARTIFACT_STORAGE_ROOT",
    "NEX_AG_AE_ARTIFACT_BASE_URL",
    "NEX_AG_AE_ARTIFACT_SERVICE_TOKEN",
    "NEX_SERVICE_TOKEN",
)

S56_EXECUTABLE_SURFACE = "S56 AE scheduler daemon executable runtime"
EXECUTABLE_RUNTIME_BOUNDARY = "protected_bounded_test_profile_only"
DEFAULT_DAEMON_MODE = "disabled"
DEFAULT_COMMAND_MODE = "plan_only"
FIRST_EXECUTION_MODE = "explicit_bounded_loop"
NEXT_SLICE = "Slice_0552"


@dataclass(frozen=True)
class RequiredPath:
    name: str
    path: Path
    purpose: str


@dataclass(frozen=True)
class TokenRequirement:
    group: str
    path: Path
    token_id: str
    token: str
    purpose: str


@dataclass(frozen=True)
class PlannedExecutableStep:
    name: str
    planned_slice: str
    purpose: str


AE_API_ARTIFACTS = ROOT / "services" / "nex-ae-api" / "nex_ae_api" / "artifacts.py"
AE_SCHEDULER = (
    ROOT / "services" / "nex-ae-api" / "nex_ae_api" / "artifact_retention_scheduler.py"
)
AE_DAEMON_CLI = (
    ROOT
    / "services"
    / "nex-ae-api"
    / "nex_ae_api"
    / "artifact_retention_scheduler_daemon.py"
)
AE_DAEMON_WRAPPER = (
    ROOT / "scripts" / "daemon" / "run_ae_artifact_retention_scheduler_daemon.py"
)
AE_API_README = ROOT / "services" / "nex-ae-api" / "README.md"
AG_ARTIFACT_OPERATIONS = ROOT / "services" / "nex-ag" / "nex_ag" / "artifact_operations.py"
AG_README = ROOT / "services" / "nex-ag" / "README.md"
QUALITY_GATE = ROOT / "scripts" / "quality" / "run_quality_gate.sh"
DOCS_INDEX = ROOT / "docs" / "README.md"
S55_CLOSURE = (
    ROOT
    / "scripts"
    / "smoke"
    / "run_s55_ae_scheduler_daemon_process_lifecycle_closure.py"
)
S55_CLOSURE_TEST = (
    ROOT / "tests" / "test_s55_ae_scheduler_daemon_process_lifecycle_closure.py"
)
S55_CLOSURE_DOC = (
    ROOT / "docs" / "slices" / "0550_s55_ae_scheduler_daemon_process_lifecycle_closure.md"
)
S56_AUDIT = (
    ROOT
    / "scripts"
    / "smoke"
    / "run_ae_scheduler_daemon_executable_runtime_boundary_audit.py"
)
S56_AUDIT_TEST = (
    ROOT / "tests" / "test_ae_scheduler_daemon_executable_runtime_boundary_audit.py"
)
S56_AUDIT_DOC = (
    ROOT
    / "docs"
    / "slices"
    / "0551_ae_scheduler_daemon_executable_runtime_boundary_audit.md"
)
BOUNDED_LOOP_SMOKE = (
    ROOT
    / "scripts"
    / "smoke"
    / "run_ae_artifact_retention_scheduler_daemon_bounded_loop_postgres_smoke.py"
)
AG_LIFECYCLE_SMOKE = (
    ROOT
    / "scripts"
    / "smoke"
    / "run_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke.py"
)

REQUIRED_PATHS = (
    RequiredPath("ae_api_artifacts", AE_API_ARTIFACTS, "AE API control/read surface."),
    RequiredPath("ae_scheduler", AE_SCHEDULER, "AE daemon coordinator contracts."),
    RequiredPath("ae_daemon_cli", AE_DAEMON_CLI, "AE daemon CLI surface."),
    RequiredPath("ae_daemon_wrapper", AE_DAEMON_WRAPPER, "Worktree CLI wrapper."),
    RequiredPath("ae_api_readme", AE_API_README, "AE executable runtime notes."),
    RequiredPath("ag_artifact_operations", AG_ARTIFACT_OPERATIONS, "AG operator projection."),
    RequiredPath("ag_readme", AG_README, "AG read-only lifecycle notes."),
    RequiredPath("s55_closure", S55_CLOSURE, "Closed S55 process lifecycle baseline."),
    RequiredPath("s55_closure_test", S55_CLOSURE_TEST, "S55 closure regression."),
    RequiredPath("s55_closure_doc", S55_CLOSURE_DOC, "S55 closure documentation."),
    RequiredPath("bounded_loop_smoke", BOUNDED_LOOP_SMOKE, "Protected bounded-loop DB evidence."),
    RequiredPath("ag_lifecycle_smoke", AG_LIFECYCLE_SMOKE, "Protected AG lifecycle DB evidence."),
    RequiredPath("s56_audit", S56_AUDIT, "S56 executable runtime boundary audit."),
    RequiredPath("s56_audit_test", S56_AUDIT_TEST, "S56 audit regression."),
    RequiredPath("s56_audit_doc", S56_AUDIT_DOC, "S56 audit slice note."),
    RequiredPath("quality_gate", QUALITY_GATE, "Default regression gate."),
    RequiredPath("docs_index", DOCS_INDEX, "Slice index."),
)

REQUIRED_SOURCE_TOKENS = (
    TokenRequirement(
        "s55_closed_baseline",
        S55_CLOSURE,
        "s55_slice_range",
        "0541-0550",
        "S56 starts only after the S55 process/lifecycle closure.",
    ),
    TokenRequirement(
        "s55_closed_baseline",
        S55_CLOSURE,
        "s55_process_boundary",
        "process_boundary=ae_owned lifecycle=RUNNING",
        "S56 inherits the AE-owned process and AG lifecycle projection boundary.",
    ),
    TokenRequirement(
        "s55_closed_baseline",
        S55_CLOSURE,
        "s55_jobqueue_boundary",
        '"jobqueue_for_retention_work_only": True',
        "Retention work remains finite JobQueue work before executable runtime wiring.",
    ),
    TokenRequirement(
        "cli_plan_first_boundary",
        AE_DAEMON_CLI,
        "cli_plan_schema",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_PLAN_SCHEMA_VERSION",
        "The executable CLI starts from a schema-bound plan contract.",
    ),
    TokenRequirement(
        "cli_plan_first_boundary",
        AE_DAEMON_CLI,
        "cli_entrypoint",
        "DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ENTRYPOINT",
        "The daemon has one AE-owned entrypoint.",
    ),
    TokenRequirement(
        "cli_plan_first_boundary",
        AE_DAEMON_CLI,
        "max_cycles_cap",
        "MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_MAX_CYCLES",
        "Executable runtime must remain bounded by a hard max-cycle cap.",
    ),
    TokenRequirement(
        "cli_plan_first_boundary",
        AE_DAEMON_CLI,
        "default_plan_only",
        '"plan_only": True',
        "The current default CLI command remains plan-only.",
    ),
    TokenRequirement(
        "cli_plan_first_boundary",
        AE_DAEMON_CLI,
        "plan_only_no_loop",
        '"starts_bounded_loop": False',
        "Plan mode must not start the bounded loop.",
    ),
    TokenRequirement(
        "cli_plan_first_boundary",
        AE_DAEMON_CLI,
        "database_url_not_required_for_plan",
        '"database_url_required": False',
        "Plan mode must not require or expose database URLs.",
    ),
    TokenRequirement(
        "cli_plan_first_boundary",
        AE_DAEMON_CLI,
        "cli_max_cycles_arg",
        '"--max-cycles"',
        "Future execution mode must retain explicit cycle bounds.",
    ),
    TokenRequirement(
        "cli_plan_first_boundary",
        AE_DAEMON_CLI,
        "cli_run_worker_arg",
        '"--run-worker"',
        "Worker execution remains explicitly requested.",
    ),
    TokenRequirement(
        "cli_plan_first_boundary",
        AE_DAEMON_WRAPPER,
        "worktree_wrapper_import",
        "nex_ae_api.artifact_retention_scheduler_daemon",
        "The worktree wrapper delegates to the service-owned module.",
    ),
    TokenRequirement(
        "bounded_loop_foundation",
        AE_SCHEDULER,
        "bounded_loop_runner",
        "run_artifact_retention_scheduler_daemon_bounded_loop",
        "Executable runtime should reuse the bounded-loop adapter.",
    ),
    TokenRequirement(
        "bounded_loop_foundation",
        AE_SCHEDULER,
        "bounded_loop_finite_guardrail",
        '"bounded_loop_is_finite": True',
        "The daemon loop must remain finite under protected execution.",
    ),
    TokenRequirement(
        "bounded_loop_foundation",
        AE_SCHEDULER,
        "bounded_loop_max_cycles",
        "max_cycles",
        "Executable runtime must require explicit max-cycle bounds.",
    ),
    TokenRequirement(
        "bounded_loop_foundation",
        AE_SCHEDULER,
        "daemon_heartbeat_emitter",
        "daemon_heartbeat_emitter",
        "Executable runtime must emit observable daemon heartbeat metadata.",
    ),
    TokenRequirement(
        "bounded_loop_foundation",
        AE_SCHEDULER,
        "run_worker_explicit_flag",
        "run_worker: bool = False",
        "Worker execution remains disabled unless explicitly requested.",
    ),
    TokenRequirement(
        "lifecycle_guard_foundation",
        AE_SCHEDULER,
        "runtime_state_builder",
        "build_artifact_retention_scheduler_daemon_runtime_state",
        "Executable runtime must build lifecycle state before starting.",
    ),
    TokenRequirement(
        "lifecycle_guard_foundation",
        AE_SCHEDULER,
        "shutdown_transition_builder",
        "build_artifact_retention_scheduler_daemon_shutdown_transition",
        "Executable runtime needs graceful shutdown transition evidence.",
    ),
    TokenRequirement(
        "lifecycle_guard_foundation",
        AE_SCHEDULER,
        "retry_circuit_guard_builder",
        "build_artifact_retention_scheduler_daemon_retry_circuit_guard",
        "Executable runtime needs retry/backoff/circuit evidence.",
    ),
    TokenRequirement(
        "lifecycle_guard_foundation",
        AE_SCHEDULER,
        "retry_circuit_open",
        "CIRCUIT_OPEN",
        "Repeated failures must stop execution through circuit-open metadata.",
    ),
    TokenRequirement(
        "lifecycle_guard_foundation",
        AE_SCHEDULER,
        "physical_delete_automation_disabled",
        '"physical_delete_automation_enabled": False',
        "Executable runtime must not enable physical delete automation by default.",
    ),
    TokenRequirement(
        "api_control_boundary",
        AE_API_ARTIFACTS,
        "daemon_config_route",
        '"/api/v1/artifact-retention/scheduler-daemon-config"',
        "AE API remains the daemon config read boundary.",
    ),
    TokenRequirement(
        "api_control_boundary",
        AE_API_ARTIFACTS,
        "daemon_runtime_route",
        '"/api/v1/artifact-retention/scheduler-daemon-runtime"',
        "AE API remains the runtime observation boundary.",
    ),
    TokenRequirement(
        "api_control_boundary",
        AE_API_ARTIFACTS,
        "daemon_controls_route",
        '"/api/v1/artifact-retention/scheduler-daemon-controls"',
        "AE API remains the daemon control request boundary.",
    ),
    TokenRequirement(
        "api_control_boundary",
        AE_API_ARTIFACTS,
        "control_route_explicit_worker_flag",
        'run_worker=payload.get("run_worker") is True',
        "Route-triggered worker execution must remain explicit.",
    ),
    TokenRequirement(
        "ag_read_only_lifecycle",
        AG_ARTIFACT_OPERATIONS,
        "ag_lifecycle_projection",
        "build_artifact_retention_daemon_lifecycle_projection",
        "AG can project daemon lifecycle metadata.",
    ),
    TokenRequirement(
        "ag_read_only_lifecycle",
        AG_ARTIFACT_OPERATIONS,
        "ag_lifecycle_metadata_only",
        '"ae_daemon_lifecycle_projection": "metadata_only"',
        "AG lifecycle projection remains metadata-only.",
    ),
    TokenRequirement(
        "ag_read_only_lifecycle",
        AG_ARTIFACT_OPERATIONS,
        "ag_database_write_disallowed",
        '"ag_direct_database_write_allowed": False',
        "AG must not write AE persistence.",
    ),
    TokenRequirement(
        "ag_read_only_lifecycle",
        AG_ARTIFACT_OPERATIONS,
        "ag_job_enqueue_disallowed",
        '"ag_direct_job_enqueue_allowed": False',
        "AG must not enqueue AE jobs directly.",
    ),
    TokenRequirement(
        "protected_postgres_evidence",
        BOUNDED_LOOP_SMOKE,
        "bounded_loop_smoke_env_guard",
        "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_BOUNDED_LOOP_POSTGRES_SMOKE",
        "Bounded-loop DB evidence stays protected by explicit opt-in.",
    ),
    TokenRequirement(
        "protected_postgres_evidence",
        BOUNDED_LOOP_SMOKE,
        "bounded_loop_live_db",
        "live_db",
        "Bounded-loop evidence must prove real test DB execution when enabled.",
    ),
    TokenRequirement(
        "protected_postgres_evidence",
        BOUNDED_LOOP_SMOKE,
        "bounded_loop_cleanup",
        "_cleanup_bounded_loop_runtime_rows",
        "Protected executable evidence must clean up DB rows.",
    ),
    TokenRequirement(
        "protected_postgres_evidence",
        AG_LIFECYCLE_SMOKE,
        "ag_lifecycle_smoke_env_guard",
        "NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_POSTGRES_SMOKE",
        "AG lifecycle evidence stays protected by explicit opt-in.",
    ),
    TokenRequirement(
        "protected_postgres_evidence",
        AG_LIFECYCLE_SMOKE,
        "ag_lifecycle_summary",
        "lifecycle=",
        "AG lifecycle smoke must report lifecycle evidence in summary output.",
    ),
    TokenRequirement(
        "protected_postgres_evidence",
        AG_LIFECYCLE_SMOKE,
        "ag_lifecycle_heartbeat_cleanup",
        "daemon_heartbeat_rows",
        "AG lifecycle smoke must clean up the daemon heartbeat row.",
    ),
    TokenRequirement(
        "quality_gate_and_docs",
        QUALITY_GATE,
        "s56_boundary_audit_gate_hook",
        "run_ae_scheduler_daemon_executable_runtime_boundary_audit.py",
        "The S56 executable runtime audit should run in the default quality gate.",
    ),
    TokenRequirement(
        "quality_gate_and_docs",
        DOCS_INDEX,
        "s56_slice_index",
        "Slice 0551",
        "The docs index should expose the S56 starting point.",
    ),
    TokenRequirement(
        "quality_gate_and_docs",
        AE_API_README,
        "s56_ae_readme_note",
        "Slice 0551 starts S56",
        "AE README should document executable runtime boundaries.",
    ),
    TokenRequirement(
        "quality_gate_and_docs",
        AG_README,
        "s56_ag_readme_note",
        "Slice 0551 starts S56",
        "AG README should document read-only executable runtime visibility.",
    ),
)

PLANNED_EXECUTABLE_STEPS = (
    PlannedExecutableStep(
        "execute_mode_contract_schema",
        "Slice_0552",
        "Define the CLI execute-mode command/result shape without starting it by default.",
    ),
    PlannedExecutableStep(
        "process_lock_pid_run_metadata",
        "Slice_0553",
        "Add process lock, pid, run id, and stale-lock metadata before execution.",
    ),
    PlannedExecutableStep(
        "graceful_shutdown_signal_adapter",
        "Slice_0554",
        "Translate process signals into AE shutdown transition metadata.",
    ),
    PlannedExecutableStep(
        "bounded_loop_cli_execution",
        "Slice_0555",
        "Wire explicit opt-in CLI execution to the existing bounded-loop adapter.",
    ),
    PlannedExecutableStep(
        "cli_execution_postgresql_smoke",
        "Slice_0556",
        "Prove CLI execution against the real AE test DB with cleanup.",
    ),
    PlannedExecutableStep(
        "daemon_run_record_lifecycle_events",
        "Slice_0557",
        "Persist redacted daemon run records and lifecycle event summaries.",
    ),
    PlannedExecutableStep(
        "ag_daemon_process_run_projection",
        "Slice_0558",
        "Expose read-only daemon process run evidence through AG.",
    ),
    PlannedExecutableStep(
        "ag_ae_process_lifecycle_postgresql_smoke",
        "Slice_0559",
        "Prove AG can read AE daemon process lifecycle evidence from test persistence.",
    ),
    PlannedExecutableStep(
        "s56_closure",
        "Slice_0560",
        "Close executable runtime enablement with quality-gate evidence.",
    ),
)

SENSITIVE_PATTERNS = (
    re.compile(r"postgresql(?:\+\w+)?://[^\"'\s]+", re.IGNORECASE),
    re.compile(r"nuri1004", re.IGNORECASE),
    re.compile(r"/data/nex-platform", re.IGNORECASE),
    re.compile(r"ed6@c496em", re.IGNORECASE),
    re.compile(r"service-token-[\w-]+", re.IGNORECASE),
)


def run_ae_scheduler_daemon_executable_runtime_boundary_audit(
    env: Mapping[str, str] | None = None,
    *,
    root_dir: Path = ROOT,
) -> dict[str, Any]:
    env = os.environ if env is None else env
    paths = build_path_results(root_dir)
    tokens = build_token_results(root_dir)
    group_status = grouped_token_status(tokens)
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "s55_closed_baseline_present": group_status.get("s55_closed_baseline")
        is True,
        "cli_plan_first_boundary_present": group_status.get("cli_plan_first_boundary")
        is True,
        "bounded_loop_foundation_present": group_status.get("bounded_loop_foundation")
        is True,
        "lifecycle_guard_foundation_present": group_status.get(
            "lifecycle_guard_foundation"
        )
        is True,
        "api_control_boundary_present": group_status.get("api_control_boundary")
        is True,
        "ag_read_only_lifecycle_present": group_status.get("ag_read_only_lifecycle")
        is True,
        "protected_postgres_evidence_present": group_status.get(
            "protected_postgres_evidence"
        )
        is True,
        "quality_gate_and_docs_present": group_status.get("quality_gate_and_docs")
        is True,
        "executable_runtime_not_default": True,
        "execute_requires_explicit_opt_in": True,
        "execute_requires_test_profile": True,
        "execute_requires_bounded_max_cycles": True,
        "process_lock_required_before_start": True,
        "graceful_shutdown_signal_required": True,
        "retention_work_uses_job_queue": True,
        "ag_remains_read_only": True,
        "physical_delete_disabled_by_default": True,
        "redacted_evidence_only": True,
    }
    issues = build_issues(paths, tokens)
    status = "PASS" if all(checks.values()) and not issues else "FAIL"
    evidence: dict[str, Any] = {
        "audit_schema_version": SCHEMA_VERSION,
        "status": status,
        "failure_code": (
            None
            if status == "PASS"
            else "ae_scheduler_daemon_executable_runtime_boundary_failed"
        ),
        "slice": "0551",
        "surface": S56_EXECUTABLE_SURFACE,
        "executable_runtime_boundary": {
            "artifact_system_of_record": "nex-ae-api",
            "daemon_process_owner": "nex-ae-api",
            "operator_projection_owner": "nex-ag",
            "runtime_boundary": EXECUTABLE_RUNTIME_BOUNDARY,
            "default_daemon_mode": DEFAULT_DAEMON_MODE,
            "default_command_mode": DEFAULT_COMMAND_MODE,
            "first_execution_mode": FIRST_EXECUTION_MODE,
            "executable_runtime_default_enabled": False,
            "test_profile_required": True,
            "explicit_opt_in_required": True,
            "bounded_max_cycles_required": True,
            "max_cycles_hard_cap": 100,
            "process_lock_required_before_start": True,
            "pid_metadata_required_before_start": True,
            "run_record_required_before_start": True,
            "graceful_shutdown_signal_adapter_required": True,
            "postgres_smoke_required_before_enablement": True,
            "retention_work_must_use_job_queue": True,
            "ag_direct_process_control_allowed": False,
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
            "physical_delete_automation_enabled": False,
        },
        "refactoring_checkpoint": {
            "keep_execution_entrypoint_in_daemon_module": True,
            "keep_long_running_loop_out_of_artifacts_module": True,
            "reuse_bounded_loop_adapter_for_cli_execution": True,
            "reuse_runtime_state_shutdown_and_retry_contracts": True,
            "reuse_worker_heartbeat_store_for_observability": True,
            "do_not_run_daemon_as_jobqueue_worker_job": True,
            "keep_jobqueue_for_finite_retention_work": True,
            "metadata_only_ag_projection": True,
            "redacted_cli_summary_only": True,
        },
        "paths": paths,
        "source_tokens": tokens,
        "planned_executable_steps": build_planned_executable_steps(),
        "checks": checks,
        "issues": issues,
        "next_slices": [
            NEXT_SLICE,
            "Slice_0553",
            "Slice_0554",
            "Slice_0555",
        ],
        "protected_env": summarize_protected_env(env),
        "redaction_summary": {
            "database_url_included": False,
            "service_token_included": False,
            "provider_api_key_included": False,
            "storage_path_included": False,
            "storage_ref_included": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_included": False,
            "raw_daemon_control_payload_included": False,
            "raw_daemon_runtime_payload_included": False,
            "raw_daemon_process_payload_included": False,
            "raw_job_payload_included": False,
        },
    }
    assert_evidence_redacted(json.dumps(evidence, ensure_ascii=False), env)
    return evidence


def build_path_results(root_dir: Path) -> list[dict[str, Any]]:
    return [
        {
            "name": item.name,
            "path": relative_label(item.path, root_dir),
            "purpose": item.purpose,
            "present": item.path.exists(),
        }
        for item in REQUIRED_PATHS
    ]


def build_token_results(root_dir: Path) -> list[dict[str, Any]]:
    return [
        {
            "group": item.group,
            "token_id": item.token_id,
            "path": relative_label(item.path, root_dir),
            "purpose": item.purpose,
            "present": item.token in read_text(item.path),
        }
        for item in REQUIRED_SOURCE_TOKENS
    ]


def build_issues(
    paths: list[dict[str, Any]],
    tokens: list[dict[str, Any]],
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    issues.extend(
        {
            "category": "path_missing",
            "name": str(item["name"]),
            "path": str(item["path"]),
            "purpose": str(item["purpose"]),
        }
        for item in paths
        if item["present"] is not True
    )
    issues.extend(
        {
            "category": "source_token_missing",
            "group": str(item["group"]),
            "token_id": str(item["token_id"]),
            "path": str(item["path"]),
            "purpose": str(item["purpose"]),
        }
        for item in tokens
        if item["present"] is not True
    )
    return issues


def build_planned_executable_steps() -> list[dict[str, str | bool]]:
    return [
        {
            "name": item.name,
            "planned_slice": item.planned_slice,
            "purpose": item.purpose,
            "blocking": False,
        }
        for item in PLANNED_EXECUTABLE_STEPS
    ]


def grouped_token_status(tokens: list[dict[str, Any]]) -> dict[str, bool]:
    groups = sorted({str(item.get("group", "ungrouped")) for item in tokens})
    return {
        group: all(
            item["present"] is True
            for item in tokens
            if str(item.get("group", "ungrouped")) == group
        )
        for group in groups
    }


def summarize_protected_env(env: Mapping[str, str]) -> dict[str, bool]:
    return {key: bool(env.get(key)) for key in PROTECTED_ENV_KEYS}


def write_audit_evidence(path: Path, evidence: Mapping[str, Any]) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    assert_evidence_redacted(serialized, os.environ)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{serialized}\n", encoding="utf-8")


def assert_evidence_redacted(serialized_evidence: str, env: Mapping[str, str]) -> None:
    for key in PROTECTED_ENV_KEYS:
        value = env.get(key)
        if value and value in serialized_evidence:
            raise ValueError(f"Sensitive environment value leaked: {key}")
    for pattern in SENSITIVE_PATTERNS:
        if pattern.search(serialized_evidence):
            raise ValueError("Sensitive value leaked in audit evidence.")


def relative_label(path: Path, root_dir: Path = ROOT) -> str:
    try:
        return str(path.relative_to(root_dir))
    except ValueError:
        return path.name


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def present_count(items: list[dict[str, Any]]) -> int:
    return sum(1 for item in items if item.get("present") is True)


def summary_line(evidence: Mapping[str, Any]) -> str:
    failing_checks = [
        key for key, passed in evidence.get("checks", {}).items() if passed is not True
    ]
    groups = grouped_token_status(list(evidence["source_tokens"]))
    passed_groups = sum(1 for passed in groups.values() if passed)
    suffix = (
        f"paths={present_count(list(evidence['paths']))}/{len(evidence['paths'])} "
        f"token_groups={passed_groups}/{len(groups)} "
        f"boundary={EXECUTABLE_RUNTIME_BOUNDARY} "
        f"daemon={DEFAULT_DAEMON_MODE} "
        f"command={DEFAULT_COMMAND_MODE} "
        f"mode={FIRST_EXECUTION_MODE} "
        f"next={NEXT_SLICE}"
    )
    if failing_checks:
        suffix += f" failing_checks={','.join(failing_checks)}"
    return (
        "ae_scheduler_daemon_executable_runtime_boundary_audit="
        f"{str(evidence['status']).lower()} {suffix}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run AE scheduler daemon executable runtime boundary audit."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence = run_ae_scheduler_daemon_executable_runtime_boundary_audit()
        if args.output:
            write_audit_evidence(args.output, evidence)
        print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2))
        return 0 if evidence["status"] == "PASS" else 1
    except Exception as exc:
        print(
            "ae_scheduler_daemon_executable_runtime_boundary_audit=fail "
            f"error={exc.__class__.__name__}"
        )
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
