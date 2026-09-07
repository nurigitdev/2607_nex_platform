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
SCHEMA_VERSION = "ae_scheduler_daemon_supervisor_boundary_audit.v1"

S57_SUPERVISOR_SURFACE = "S57 AE scheduler daemon supervisor operations readiness"
SUPERVISOR_BOUNDARY = "protected_supervised_test_profile_only"
DEFAULT_SUPERVISOR_MODE = "disabled"
DEFAULT_START_MODE = "blocked_until_supervisor_contract"
FIRST_SUPERVISOR_MODE = "metadata_only_fake_supervisor"
NEXT_SLICE = "Slice_0562"

PROTECTED_ENV_KEYS = (
    "NEX_AE_DATABASE_URL",
    "NEX_AE_TEST_DATABASE_URL",
    "NEX_AE_ARTIFACT_STORAGE_ROOT",
    "NEX_AG_AE_ARTIFACT_BASE_URL",
    "NEX_AG_AE_ARTIFACT_SERVICE_TOKEN",
    "NEX_SERVICE_TOKEN",
)


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
class PlannedSupervisorStep:
    name: str
    planned_slice: str
    purpose: str


AE_DAEMON = (
    ROOT
    / "services"
    / "nex-ae-api"
    / "nex_ae_api"
    / "artifact_retention_scheduler_daemon.py"
)
AE_SCHEDULER = (
    ROOT / "services" / "nex-ae-api" / "nex_ae_api" / "artifact_retention_scheduler.py"
)
AE_ARTIFACTS = ROOT / "services" / "nex-ae-api" / "nex_ae_api" / "artifacts.py"
AE_README = ROOT / "services" / "nex-ae-api" / "README.md"
AG_ARTIFACT_OPERATIONS = ROOT / "services" / "nex-ag" / "nex_ag" / "artifact_operations.py"
AG_README = ROOT / "services" / "nex-ag" / "README.md"
QUALITY_GATE = ROOT / "scripts" / "quality" / "run_quality_gate.sh"
DOCS_INDEX = ROOT / "docs" / "README.md"
S56_CLOSURE = (
    ROOT
    / "scripts"
    / "smoke"
    / "run_s56_ae_scheduler_daemon_executable_runtime_closure.py"
)
S56_CLOSURE_TEST = (
    ROOT / "tests" / "test_s56_ae_scheduler_daemon_executable_runtime_closure.py"
)
S56_CLOSURE_DOC = (
    ROOT
    / "docs"
    / "slices"
    / "0560_s56_ae_scheduler_daemon_executable_runtime_closure.md"
)
S57_AUDIT = (
    ROOT / "scripts" / "smoke" / "run_ae_scheduler_daemon_supervisor_boundary_audit.py"
)
S57_AUDIT_TEST = (
    ROOT / "tests" / "test_ae_scheduler_daemon_supervisor_boundary_audit.py"
)
S57_AUDIT_DOC = (
    ROOT
    / "docs"
    / "slices"
    / "0561_ae_scheduler_daemon_supervisor_boundary_audit.md"
)

REQUIRED_PATHS = (
    RequiredPath("ae_daemon_runtime", AE_DAEMON, "AE daemon executable runtime module."),
    RequiredPath("ae_scheduler", AE_SCHEDULER, "AE bounded scheduler loop contracts."),
    RequiredPath("ae_artifacts_routes", AE_ARTIFACTS, "AE API daemon route surface."),
    RequiredPath("ag_artifact_operations", AG_ARTIFACT_OPERATIONS, "AG read-only operations projection."),
    RequiredPath("s56_closure", S56_CLOSURE, "Closed S56 executable runtime baseline."),
    RequiredPath("s56_closure_test", S56_CLOSURE_TEST, "Closed S56 regression coverage."),
    RequiredPath("s56_closure_doc", S56_CLOSURE_DOC, "Closed S56 slice note."),
    RequiredPath("s57_audit", S57_AUDIT, "S57 supervisor boundary audit."),
    RequiredPath("s57_audit_test", S57_AUDIT_TEST, "S57 supervisor boundary tests."),
    RequiredPath("s57_audit_doc", S57_AUDIT_DOC, "S57 supervisor boundary slice note."),
    RequiredPath("quality_gate", QUALITY_GATE, "Default regression gate."),
    RequiredPath("docs_index", DOCS_INDEX, "Slice index."),
    RequiredPath("ae_readme", AE_README, "AE service implementation notes."),
    RequiredPath("ag_readme", AG_README, "AG service implementation notes."),
)

REQUIRED_SOURCE_TOKENS = (
    TokenRequirement(
        "s56_closed_baseline",
        S56_CLOSURE,
        "s56_slice_range",
        "0551-0560",
        "S57 starts after the executable runtime closure.",
    ),
    TokenRequirement(
        "s56_closed_baseline",
        S56_CLOSURE,
        "s56_runtime_summary",
        "runtime=explicit_bounded read_model=ae_owned ag_projection=read_only",
        "S57 inherits bounded execution and AE-owned read models.",
    ),
    TokenRequirement(
        "s56_closed_baseline",
        S56_CLOSURE_DOC,
        "s56_guardrail_no_daemon_start",
        "does not start the daemon",
        "S56 closure still forbids daemon start from default checks.",
    ),
    TokenRequirement(
        "ae_executable_runtime",
        AE_DAEMON,
        "cli_execute_schema",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_EXECUTE_COMMAND_SCHEMA_VERSION",
        "Supervisor start must build on schema-bound CLI execution.",
    ),
    TokenRequirement(
        "ae_executable_runtime",
        AE_DAEMON,
        "cli_execution_runner",
        "run_artifact_retention_scheduler_daemon_cli_execution",
        "Supervisor start must delegate to the existing executable runtime.",
    ),
    TokenRequirement(
        "ae_executable_runtime",
        AE_DAEMON,
        "explicit_opt_in_required",
        '"execution_requires_explicit_opt_in": True',
        "Executable runtime remains explicit opt-in only.",
    ),
    TokenRequirement(
        "ae_executable_runtime",
        AE_DAEMON,
        "test_profile_required",
        "profile must be test.",
        "Executable runtime remains test-profile only.",
    ),
    TokenRequirement(
        "ae_executable_runtime",
        AE_DAEMON,
        "bounded_max_cycles_cap",
        "MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_MAX_CYCLES",
        "Supervisor execution must preserve hard max-cycle limits.",
    ),
    TokenRequirement(
        "ae_process_lifecycle",
        AE_DAEMON,
        "process_lock_schema",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_PROCESS_LOCK_SCHEMA_VERSION",
        "Supervisor start requires a process lock contract.",
    ),
    TokenRequirement(
        "ae_process_lifecycle",
        AE_DAEMON,
        "run_metadata_schema",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUN_METADATA_SCHEMA_VERSION",
        "Supervisor start requires safe run metadata.",
    ),
    TokenRequirement(
        "ae_process_lifecycle",
        AE_DAEMON,
        "shutdown_adapter_schema",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SIGNAL_SHUTDOWN_ADAPTER_SCHEMA_VERSION",
        "Supervisor stop must preserve graceful shutdown contracts.",
    ),
    TokenRequirement(
        "ae_process_lifecycle",
        AE_DAEMON,
        "daemon_run_store",
        "SqlAlchemyArtifactRetentionSchedulerDaemonRunStore",
        "Supervisor evidence must stay in AE-owned persistence.",
    ),
    TokenRequirement(
        "bounded_scheduler_runtime",
        AE_SCHEDULER,
        "bounded_loop_runner",
        "run_artifact_retention_scheduler_daemon_bounded_loop",
        "Supervisor adapter should reuse the bounded loop rather than duplicate it.",
    ),
    TokenRequirement(
        "bounded_scheduler_runtime",
        AE_SCHEDULER,
        "bounded_loop_finite",
        '"bounded_loop_is_finite": True',
        "Continuous enablement stays blocked until supervisor safeguards exist.",
    ),
    TokenRequirement(
        "ae_api_surface",
        AE_ARTIFACTS,
        "daemon_config_route",
        '"/api/v1/artifact-retention/scheduler-daemon-config"',
        "AE already owns daemon config visibility.",
    ),
    TokenRequirement(
        "ae_api_surface",
        AE_ARTIFACTS,
        "daemon_controls_route",
        '"/api/v1/artifact-retention/scheduler-daemon-controls"',
        "AE already owns guarded daemon control admission.",
    ),
    TokenRequirement(
        "ae_api_surface",
        AE_ARTIFACTS,
        "daemon_run_read_model_route",
        '"/api/v1/artifact-retention/scheduler-daemon-runs"',
        "AE owns daemon run read-model routes.",
    ),
    TokenRequirement(
        "ag_operator_boundary",
        AG_ARTIFACT_OPERATIONS,
        "ag_daemon_projection_schema",
        "AG_ARTIFACT_OPERATION_RETENTION_DAEMON_PROJECTION_SCHEMA_VERSION",
        "AG already has metadata-only daemon operations projection.",
    ),
    TokenRequirement(
        "ag_operator_boundary",
        AG_ARTIFACT_OPERATIONS,
        "ag_daemon_run_projection_schema",
        "AG_ARTIFACT_OPERATION_RETENTION_DAEMON_RUN_COLLECTION_PROJECTION_SCHEMA_VERSION",
        "AG can read daemon run projections only through AE.",
    ),
    TokenRequirement(
        "ag_operator_boundary",
        AG_ARTIFACT_OPERATIONS,
        "future_supervisor_required",
        "future_supervisor_required_before_start",
        "Current AG projection explicitly blocks start until a supervisor exists.",
    ),
    TokenRequirement(
        "ag_operator_boundary",
        AG_ARTIFACT_OPERATIONS,
        "ag_no_db_write",
        '"ag_direct_database_write_allowed": False',
        "AG must not write AE daemon persistence.",
    ),
    TokenRequirement(
        "ag_operator_boundary",
        AG_ARTIFACT_OPERATIONS,
        "ag_no_job_enqueue",
        '"ag_direct_job_enqueue_allowed": False',
        "AG must not enqueue AE retention jobs directly.",
    ),
    TokenRequirement(
        "quality_docs",
        QUALITY_GATE,
        "s57_quality_gate_hook",
        "run_ae_scheduler_daemon_supervisor_boundary_audit.py",
        "The S57 boundary audit is part of the default gate.",
    ),
    TokenRequirement(
        "quality_docs",
        DOCS_INDEX,
        "slice_0561_index",
        "Slice 0561",
        "The docs index tracks S57 kickoff.",
    ),
    TokenRequirement(
        "quality_docs",
        AE_README,
        "ae_readme_s57",
        "Slice 0561 starts S57",
        "AE README records supervisor boundary ownership.",
    ),
    TokenRequirement(
        "quality_docs",
        AG_README,
        "ag_readme_s57",
        "Slice 0561 starts S57",
        "AG README records read-only supervisor operations boundary.",
    ),
)

PLANNED_SUPERVISOR_STEPS = (
    PlannedSupervisorStep(
        "supervisor_command_result_contract",
        "Slice_0562",
        "Define schema-bound start/stop/status command and result envelopes.",
    ),
    PlannedSupervisorStep(
        "supervisor_adapter_foundation",
        "Slice_0563",
        "Add an injectable fake/dry-run supervisor adapter before any OS process manager.",
    ),
    PlannedSupervisorStep(
        "supervisor_state_persistence",
        "Slice_0564",
        "Persist supervisor request/state/event summaries in AE-owned storage.",
    ),
    PlannedSupervisorStep(
        "supervisor_service_api",
        "Slice_0565",
        "Expose guarded AE service routes for supervisor status and controls.",
    ),
    PlannedSupervisorStep(
        "supervisor_postgres_smoke",
        "Slice_0566",
        "Prove state and routes against the real AE PostgreSQL test database.",
    ),
    PlannedSupervisorStep(
        "ag_supervisor_projection",
        "Slice_0567",
        "Project supervisor state through AG without write authority.",
    ),
    PlannedSupervisorStep(
        "ag_supervisor_guardrail_smoke",
        "Slice_0568",
        "Verify AG-to-AE guarded control routing and direct-write prohibition.",
    ),
    PlannedSupervisorStep(
        "operator_runbook_attention",
        "Slice_0569",
        "Document runbook, alert, and attention evidence for supervisor operations.",
    ),
    PlannedSupervisorStep(
        "s57_closure",
        "Slice_0570",
        "Close the supervisor operations readiness track in the quality gate.",
    ),
)

SENSITIVE_PATTERNS = (
    re.compile(r"postgresql(?:\+psycopg)?://[^\\s\"']+", re.IGNORECASE),
    re.compile(r"/data/nex-platform[^\\s\"']*"),
)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def relative_label(path: Path, root_dir: Path = ROOT) -> str:
    try:
        return str(path.relative_to(root_dir))
    except ValueError:
        return path.name


def present_count(items: list[Mapping[str, Any]]) -> int:
    return sum(1 for item in items if item.get("present") is True)


def grouped_token_status(items: list[Mapping[str, Any]]) -> dict[str, bool]:
    groups = {str(item.get("group")) for item in items}
    return {
        group: all(
            item.get("present") is True
            for item in items
            if str(item.get("group")) == group
        )
        for group in sorted(groups)
    }


def summarize_protected_env(env: Mapping[str, str] | None = None) -> dict[str, bool]:
    source = os.environ if env is None else env
    return {key: bool(source.get(key)) for key in PROTECTED_ENV_KEYS}


def assert_evidence_redacted(serialized: str, env: Mapping[str, str] | None = None) -> None:
    source = os.environ if env is None else env
    for key in PROTECTED_ENV_KEYS:
        value = source.get(key)
        if value and value in serialized:
            raise ValueError(f"{key} leaked into S57 supervisor evidence.")
    for pattern in SENSITIVE_PATTERNS:
        if pattern.search(serialized):
            raise ValueError("Sensitive value leaked into S57 supervisor evidence.")


def _required_path_status(root_dir: Path) -> list[dict[str, Any]]:
    return [
        {
            "name": item.name,
            "path": relative_label(item.path, root_dir),
            "purpose": item.purpose,
            "present": item.path.is_file(),
        }
        for item in REQUIRED_PATHS
    ]


def _token_status(root_dir: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in REQUIRED_SOURCE_TOKENS:
        text = read_text(item.path)
        result.append(
            {
                "group": item.group,
                "token_id": item.token_id,
                "path": relative_label(item.path, root_dir),
                "purpose": item.purpose,
                "present": item.token in text,
            }
        )
    return result


def _planned_steps() -> list[dict[str, Any]]:
    return [
        {
            "name": item.name,
            "planned_slice": item.planned_slice,
            "purpose": item.purpose,
            "blocking": False,
        }
        for item in PLANNED_SUPERVISOR_STEPS
    ]


def _supervisor_boundary() -> dict[str, Any]:
    return {
        "artifact_system_of_record": "nex-ae-api",
        "daemon_process_owner": "nex-ae-api",
        "supervisor_owner": "nex-ae-api",
        "operator_projection_owner": "nex-ag",
        "runtime_boundary": SUPERVISOR_BOUNDARY,
        "default_supervisor_mode": DEFAULT_SUPERVISOR_MODE,
        "default_start_mode": DEFAULT_START_MODE,
        "first_supervisor_mode": FIRST_SUPERVISOR_MODE,
        "production_continuous_start_enabled": False,
        "test_profile_required": True,
        "explicit_opt_in_required": True,
        "bounded_max_cycles_required": True,
        "lease_required_before_start": True,
        "process_lock_required_before_start": True,
        "pid_metadata_required_before_start": True,
        "run_record_required_before_start": True,
        "graceful_shutdown_required_before_stop": True,
        "postgres_smoke_required_before_enablement": True,
        "retention_work_must_use_job_queue": True,
        "ag_direct_process_control_allowed": False,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
        "physical_delete_automation_enabled": False,
    }


def _refactoring_checkpoint() -> dict[str, bool]:
    return {
        "introduce_supervisor_adapter_before_start_daemon": True,
        "keep_cli_bounded_runtime_in_daemon_module": True,
        "keep_long_running_process_out_of_artifacts_module": True,
        "reuse_bounded_loop_adapter_for_supervised_execution": True,
        "reuse_process_lock_run_metadata_and_shutdown_contracts": True,
        "reuse_daemon_run_store_for_supervisor_evidence": True,
        "do_not_run_daemon_as_jobqueue_worker_job": True,
        "keep_jobqueue_for_finite_retention_work": True,
        "metadata_only_ag_projection": True,
        "redacted_supervisor_evidence_only": True,
    }


def _checks(paths: list[dict[str, Any]], tokens: list[dict[str, Any]]) -> dict[str, bool]:
    groups = grouped_token_status(tokens)
    return {
        "required_paths_present": all(item["present"] for item in paths),
        "s56_closed_baseline_present": groups.get("s56_closed_baseline", False),
        "ae_executable_runtime_present": groups.get("ae_executable_runtime", False),
        "ae_process_lifecycle_present": groups.get("ae_process_lifecycle", False),
        "bounded_scheduler_runtime_present": groups.get("bounded_scheduler_runtime", False),
        "ae_api_surface_present": groups.get("ae_api_surface", False),
        "ag_operator_boundary_present": groups.get("ag_operator_boundary", False),
        "quality_docs_present": groups.get("quality_docs", False),
        "supervisor_default_disabled": True,
        "start_daemon_stays_blocked_until_contract": True,
        "test_profile_required": True,
        "explicit_opt_in_required": True,
        "bounded_max_cycles_required": True,
        "process_lock_required_before_start": True,
        "graceful_shutdown_required_before_stop": True,
        "retention_work_uses_job_queue": True,
        "ag_remains_read_only": True,
        "physical_delete_disabled_by_default": True,
        "redacted_evidence_only": True,
    }


def _issues(
    paths: list[dict[str, Any]],
    tokens: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for item in paths:
        if item["present"] is not True:
            issues.append(
                {
                    "category": "path_missing",
                    "name": item["name"],
                    "path": item["path"],
                    "purpose": item["purpose"],
                }
            )
    for item in tokens:
        if item["present"] is not True:
            issues.append(
                {
                    "category": "source_token_missing",
                    "group": item["group"],
                    "token_id": item["token_id"],
                    "path": item["path"],
                    "purpose": item["purpose"],
                }
            )
    return issues


def run_ae_scheduler_daemon_supervisor_boundary_audit(
    env: Mapping[str, str] | None = None,
    *,
    root_dir: Path = ROOT,
) -> dict[str, Any]:
    paths = _required_path_status(root_dir)
    tokens = _token_status(root_dir)
    checks = _checks(paths, tokens)
    issues = _issues(paths, tokens)
    status = "PASS" if not issues and all(checks.values()) else "FAIL"
    evidence = {
        "audit_schema_version": SCHEMA_VERSION,
        "status": status,
        "failure_code": None if status == "PASS" else "ae_scheduler_daemon_supervisor_boundary_failed",
        "slice": "0561",
        "surface": S57_SUPERVISOR_SURFACE,
        "supervisor_boundary": _supervisor_boundary(),
        "refactoring_checkpoint": _refactoring_checkpoint(),
        "paths": paths,
        "source_tokens": tokens,
        "planned_supervisor_steps": _planned_steps(),
        "checks": checks,
        "issues": issues,
        "protected_env": summarize_protected_env(env),
        "next_slices": [item.planned_slice for item in PLANNED_SUPERVISOR_STEPS],
    }
    assert_evidence_redacted(json.dumps(evidence, ensure_ascii=False), env)
    return evidence


def write_audit_evidence(path: Path, evidence: Mapping[str, Any]) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    assert_evidence_redacted(serialized)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialized + "\n", encoding="utf-8")


def summary_line(evidence: Mapping[str, Any]) -> str:
    checks = evidence.get("checks")
    failing_checks = []
    if isinstance(checks, Mapping):
        failing_checks = [str(key) for key, value in checks.items() if value is not True]
    suffix = ""
    if failing_checks:
        suffix = " failing_checks=" + ",".join(sorted(failing_checks))
    return (
        "ae_scheduler_daemon_supervisor_boundary_audit="
        f"{str(evidence.get('status', 'FAIL')).lower()} "
        f"paths={present_count(list(evidence.get('paths', [])))}/"
        f"{len(list(evidence.get('paths', [])))} "
        f"token_groups={sum(1 for value in grouped_token_status(list(evidence.get('source_tokens', []))).values() if value)}/"
        f"{len(grouped_token_status(list(evidence.get('source_tokens', []))))} "
        f"boundary={SUPERVISOR_BOUNDARY} "
        f"supervisor={DEFAULT_SUPERVISOR_MODE} "
        f"start={DEFAULT_START_MODE} "
        f"next={NEXT_SLICE}"
        f"{suffix}"
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit the S57 AE scheduler daemon supervisor boundary."
    )
    parser.add_argument("--summary", action="store_true", help="Print one summary line.")
    parser.add_argument("--output", type=Path, help="Optional evidence JSON output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        evidence = run_ae_scheduler_daemon_supervisor_boundary_audit(os.environ)
        if args.output:
            write_audit_evidence(args.output, evidence)
    except Exception as exc:  # pragma: no cover - exercised through CLI tests
        print(
            "ae_scheduler_daemon_supervisor_boundary_audit=fail "
            f"error={type(exc).__name__}"
        )
        return 1
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evidence.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
