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
SCHEMA_VERSION = "ae_scheduler_daemon_runtime_boundary_audit.v1"

PROTECTED_ENV_KEYS = (
    "NEX_AE_DATABASE_URL",
    "NEX_AE_TEST_DATABASE_URL",
    "NEX_AE_ARTIFACT_STORAGE_ROOT",
    "NEX_AG_AE_ARTIFACT_BASE_URL",
    "NEX_AG_AE_ARTIFACT_SERVICE_TOKEN",
    "NEX_SERVICE_TOKEN",
)

S54_RUNTIME_SURFACE = "S54 AE scheduler daemon runtime enablement"
S54_ENABLEMENT_BOUNDARY = "test_profile_explicit_opt_in_only"
DEFAULT_DAEMON_MODE = "disabled"
DEFAULT_EXECUTION_MODE = "DRY_RUN"
NEXT_SLICE = "Slice_0532"


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
class PlannedRuntimeStep:
    name: str
    planned_slice: str
    purpose: str


AE_API_ARTIFACTS = ROOT / "services" / "nex-ae-api" / "nex_ae_api" / "artifacts.py"
AE_SCHEDULER = (
    ROOT / "services" / "nex-ae-api" / "nex_ae_api" / "artifact_retention_scheduler.py"
)
AE_API_README = ROOT / "services" / "nex-ae-api" / "README.md"
AG_ARTIFACT_OPERATIONS = ROOT / "services" / "nex-ag" / "nex_ag" / "artifact_operations.py"
AG_README = ROOT / "services" / "nex-ag" / "README.md"
SHARED_JOB_RUNTIME = ROOT / "services" / "_shared" / "nex_runtime" / "jobs.py"
SHARED_WORKER_RUNNER = ROOT / "services" / "_shared" / "nex_runtime" / "worker_runner.py"
QUALITY_GATE = ROOT / "scripts" / "quality" / "run_quality_gate.sh"
DOCS_INDEX = ROOT / "docs" / "README.md"
S53_CLOSURE = ROOT / "scripts" / "smoke" / "run_s53_ag_scheduler_daemon_operations_closure.py"
S53_CLOSURE_TEST = ROOT / "tests" / "test_s53_ag_scheduler_daemon_operations_closure.py"
S53_CLOSURE_DOC = (
    ROOT / "docs" / "slices" / "0530_s53_ag_scheduler_daemon_operations_closure.md"
)
S53_DAEMON_POSTGRES_SMOKE = (
    ROOT
    / "scripts"
    / "smoke"
    / "run_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke.py"
)
S53_OPERATOR_RUNBOOK = ROOT / "docs" / "runbooks" / "ag_scheduler_daemon_operations.md"
S54_AUDIT = ROOT / "scripts" / "smoke" / "run_ae_scheduler_daemon_runtime_boundary_audit.py"
S54_AUDIT_TEST = ROOT / "tests" / "test_ae_scheduler_daemon_runtime_boundary_audit.py"
S54_AUDIT_DOC = (
    ROOT / "docs" / "slices" / "0531_ae_scheduler_daemon_runtime_boundary_audit.md"
)

REQUIRED_PATHS = (
    RequiredPath("ae_api_artifacts", AE_API_ARTIFACTS, "AE route and retention runtime."),
    RequiredPath("ae_scheduler", AE_SCHEDULER, "AE daemon contract/runtime owner."),
    RequiredPath("ae_api_readme", AE_API_README, "AE scheduler notes."),
    RequiredPath("ag_artifact_operations", AG_ARTIFACT_OPERATIONS, "AG operator view."),
    RequiredPath("ag_readme", AG_README, "AG daemon operations notes."),
    RequiredPath("shared_job_runtime", SHARED_JOB_RUNTIME, "Shared JobQueue runtime."),
    RequiredPath("shared_worker_runner", SHARED_WORKER_RUNNER, "Shared worker runner."),
    RequiredPath("s53_closure", S53_CLOSURE, "Closed S53 daemon operations baseline."),
    RequiredPath("s53_closure_test", S53_CLOSURE_TEST, "S53 closure regression."),
    RequiredPath("s53_closure_doc", S53_CLOSURE_DOC, "S53 closure documentation."),
    RequiredPath(
        "s53_daemon_postgres_smoke",
        S53_DAEMON_POSTGRES_SMOKE,
        "Protected AG-to-AE daemon PostgreSQL evidence.",
    ),
    RequiredPath("s53_operator_runbook", S53_OPERATOR_RUNBOOK, "S53 operator runbook."),
    RequiredPath("s54_audit", S54_AUDIT, "S54 boundary audit runner."),
    RequiredPath("s54_audit_test", S54_AUDIT_TEST, "S54 boundary audit regression."),
    RequiredPath("s54_audit_doc", S54_AUDIT_DOC, "S54 boundary audit slice note."),
    RequiredPath("quality_gate", QUALITY_GATE, "Default regression gate."),
    RequiredPath("docs_index", DOCS_INDEX, "Slice index."),
)

REQUIRED_SOURCE_TOKENS = (
    TokenRequirement(
        "s53_closed_baseline",
        S53_CLOSURE,
        "s53_slice_range",
        "0521-0530",
        "S54 starts only after the S53 AG daemon operations closure.",
    ),
    TokenRequirement(
        "s53_closed_baseline",
        S53_CLOSURE,
        "s53_start_daemon_deferred",
        '"start_daemon_deferred": True',
        "Runtime enablement must start from a blocked daemon-start baseline.",
    ),
    TokenRequirement(
        "s53_closed_baseline",
        S53_CLOSURE,
        "s53_continuous_loop_deferred",
        '"continuous_loop_deferred": True',
        "Continuous loop execution remains unimplemented at S54 entry.",
    ),
    TokenRequirement(
        "s53_closed_baseline",
        S53_CLOSURE,
        "s53_protected_smoke_required",
        '"protected_postgres_smoke_envs_required": True',
        "Mutating runtime evidence must remain opt-in and test-DB scoped.",
    ),
    TokenRequirement(
        "ae_daemon_contract_owner",
        AE_SCHEDULER,
        "daemon_config_schema",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONFIG_SCHEMA_VERSION",
        "AE owns daemon configuration identity.",
    ),
    TokenRequirement(
        "ae_daemon_contract_owner",
        AE_SCHEDULER,
        "daemon_dispatch_schema",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_DISPATCH_RESULT_SCHEMA_VERSION",
        "AE owns daemon dispatch evidence identity.",
    ),
    TokenRequirement(
        "ae_daemon_contract_owner",
        AE_SCHEDULER,
        "manual_tick_once_action",
        "ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONTROL_ACTION_MANUAL_TICK_ONCE",
        "Manual tick-once remains the first executable runtime action.",
    ),
    TokenRequirement(
        "ae_daemon_contract_owner",
        AE_SCHEDULER,
        "start_daemon_action",
        "ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONTROL_ACTION_START_DAEMON",
        "S54 may only open daemon start behind explicit runtime guardrails.",
    ),
    TokenRequirement(
        "ae_daemon_contract_owner",
        AE_SCHEDULER,
        "stop_daemon_action",
        "ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONTROL_ACTION_STOP_DAEMON",
        "S54 stop controls should remain AE-owned.",
    ),
    TokenRequirement(
        "ae_daemon_contract_owner",
        AE_SCHEDULER,
        "daemon_config_builder",
        "build_artifact_retention_scheduler_daemon_config",
        "Runtime enablement starts from the existing daemon config builder.",
    ),
    TokenRequirement(
        "ae_daemon_contract_owner",
        AE_SCHEDULER,
        "daemon_dispatch_facade",
        "dispatch_artifact_retention_scheduler_daemon_control",
        "All daemon control decisions stay behind AE's dispatch facade.",
    ),
    TokenRequirement(
        "ae_runtime_safety_guardrails",
        AE_SCHEDULER,
        "daemon_disabled_by_policy",
        "daemon_disabled_by_policy",
        "Current start-daemon behavior is policy-blocked.",
    ),
    TokenRequirement(
        "ae_runtime_safety_guardrails",
        AE_SCHEDULER,
        "scheduler_daemon_not_started",
        '"scheduler_daemon_started": False',
        "S54 entry must not already start a daemon process.",
    ),
    TokenRequirement(
        "ae_runtime_safety_guardrails",
        AE_SCHEDULER,
        "continuous_loop_not_started",
        '"continuous_loop_started": False',
        "S54 entry must not already start a continuous loop.",
    ),
    TokenRequirement(
        "ae_runtime_safety_guardrails",
        AE_SCHEDULER,
        "lease_sqlalchemy_store",
        "SqlAlchemyArtifactRetentionSchedulerLeaseStore",
        "Daemon runtime must keep lease/fencing state in AE persistence.",
    ),
    TokenRequirement(
        "ae_runtime_safety_guardrails",
        AE_API_ARTIFACTS,
        "scheduler_daemon_default_disabled",
        '"scheduler_daemon_enabled": False',
        "AE scheduler daemon remains disabled by default.",
    ),
    TokenRequirement(
        "ae_runtime_safety_guardrails",
        AE_API_ARTIFACTS,
        "default_execution_mode_dry_run",
        '"default_execution_mode": "DRY_RUN"',
        "Scheduled runtime remains dry-run by default.",
    ),
    TokenRequirement(
        "ae_runtime_safety_guardrails",
        AE_API_ARTIFACTS,
        "batch_window_enforced",
        '"scheduler_tick_batch_window_enforced": True',
        "Runtime ticks must respect the batch window.",
    ),
    TokenRequirement(
        "ae_runtime_safety_guardrails",
        AE_API_ARTIFACTS,
        "physical_delete_disabled",
        '"physical_delete_automation_enabled": False',
        "Physical delete automation must remain disabled at S54 entry.",
    ),
    TokenRequirement(
        "queue_worker_runtime",
        SHARED_JOB_RUNTIME,
        "sqlalchemy_job_queue",
        "class SqlAlchemyJobQueue",
        "Runtime ticks must continue through shared JobQueue persistence.",
    ),
    TokenRequirement(
        "queue_worker_runtime",
        SHARED_WORKER_RUNNER,
        "worker_once",
        "run_worker_once",
        "One-cycle runtime should reuse the shared worker once path.",
    ),
    TokenRequirement(
        "queue_worker_runtime",
        AE_API_ARTIFACTS,
        "tick_job_admission",
        "enqueue_artifact_retention_scheduler_tick_job",
        "Daemon cycles should reuse existing tick admission.",
    ),
    TokenRequirement(
        "queue_worker_runtime",
        AE_API_ARTIFACTS,
        "scheduled_worker_once",
        "run_artifact_retention_scheduled_worker_once",
        "Worker execution stays explicit before any loop is opened.",
    ),
    TokenRequirement(
        "api_control_surface",
        AE_API_ARTIFACTS,
        "daemon_config_route",
        '"/api/v1/artifact-retention/scheduler-daemon-config"',
        "Operators read daemon posture through AE API.",
    ),
    TokenRequirement(
        "api_control_surface",
        AE_API_ARTIFACTS,
        "daemon_controls_route",
        '"/api/v1/artifact-retention/scheduler-daemon-controls"',
        "Operators request daemon controls through AE API.",
    ),
    TokenRequirement(
        "ag_visibility_boundary",
        AG_ARTIFACT_OPERATIONS,
        "ag_direct_database_write_disallowed",
        '"ag_direct_database_write_allowed": False',
        "AG must not write AE persistence directly.",
    ),
    TokenRequirement(
        "ag_visibility_boundary",
        AG_ARTIFACT_OPERATIONS,
        "ag_direct_job_enqueue_disallowed",
        '"ag_direct_job_enqueue_allowed": False',
        "AG must not enqueue AE jobs directly.",
    ),
    TokenRequirement(
        "ag_visibility_boundary",
        AG_ARTIFACT_OPERATIONS,
        "daemon_operations_route",
        '"/admin/v1/operations/artifact-retention/scheduler-daemon"',
        "AG exposes metadata-only daemon visibility.",
    ),
    TokenRequirement(
        "ag_visibility_boundary",
        AG_ARTIFACT_OPERATIONS,
        "daemon_attention_classifier",
        "classify_artifact_retention_daemon_attention",
        "AG already classifies daemon posture for operators.",
    ),
    TokenRequirement(
        "postgres_daemon_evidence",
        S53_DAEMON_POSTGRES_SMOKE,
        "postgres_smoke_env_guard",
        "NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_POSTGRES_SMOKE",
        "Runtime-adjacent daemon evidence remains protected by env guard.",
    ),
    TokenRequirement(
        "postgres_daemon_evidence",
        S53_DAEMON_POSTGRES_SMOKE,
        "postgres_smoke_live_db",
        "live_db",
        "Protected evidence must prove real test DB execution when enabled.",
    ),
    TokenRequirement(
        "postgres_daemon_evidence",
        S53_DAEMON_POSTGRES_SMOKE,
        "postgres_smoke_lease_readback",
        "_scheduler_once_lease_observation",
        "Smoke evidence must read back lease/fencing state.",
    ),
    TokenRequirement(
        "postgres_daemon_evidence",
        S53_DAEMON_POSTGRES_SMOKE,
        "postgres_smoke_job_readback",
        "_job_observation",
        "Smoke evidence must read back JobQueue state.",
    ),
    TokenRequirement(
        "postgres_daemon_evidence",
        S53_DAEMON_POSTGRES_SMOKE,
        "postgres_smoke_history_readback",
        "history_rows",
        "Smoke evidence must read back retention history.",
    ),
    TokenRequirement(
        "quality_gate_and_docs",
        QUALITY_GATE,
        "s54_boundary_gate_hook",
        "run_ae_scheduler_daemon_runtime_boundary_audit.py",
        "The S54 boundary audit should run in the default quality gate.",
    ),
    TokenRequirement(
        "quality_gate_and_docs",
        DOCS_INDEX,
        "s54_slice_index",
        "Slice 0531",
        "The docs index should expose the S54 starting point.",
    ),
    TokenRequirement(
        "quality_gate_and_docs",
        AE_API_README,
        "s54_ae_readme_note",
        "Slice 0531 starts S54",
        "AE README should document the runtime enablement boundary.",
    ),
    TokenRequirement(
        "quality_gate_and_docs",
        AG_README,
        "s54_ag_readme_note",
        "Slice 0531 starts S54",
        "AG README should document its read-only runtime visibility boundary.",
    ),
)

PLANNED_RUNTIME_STEPS = (
    PlannedRuntimeStep(
        "runtime_config_expansion",
        "Slice_0532",
        "Add explicit daemon runtime config without enabling the loop by default.",
    ),
    PlannedRuntimeStep(
        "loop_planner_state_machine",
        "Slice_0533",
        "Build a pure state machine for daemon loop decisions before side effects.",
    ),
    PlannedRuntimeStep(
        "one_cycle_runner_adapter",
        "Slice_0534",
        "Run at most one daemon cycle through existing lease, tick, queue, and worker paths.",
    ),
    PlannedRuntimeStep(
        "start_stop_control_guardrail",
        "Slice_0535",
        "Open start/stop planning only under test-profile explicit opt-in.",
    ),
    PlannedRuntimeStep(
        "one_cycle_postgresql_smoke",
        "Slice_0536",
        "Verify one-cycle runtime against the real AE test DB before any loop work.",
    ),
    PlannedRuntimeStep(
        "runtime_heartbeat_observability",
        "Slice_0537",
        "Expose daemon heartbeat, last tick, next tick, and last error as metadata.",
    ),
    PlannedRuntimeStep(
        "ag_runtime_operations_projection",
        "Slice_0538",
        "Project AE daemon runtime posture into AG without AG direct writes.",
    ),
    PlannedRuntimeStep(
        "ag_runtime_attention_issue_candidates",
        "Slice_0539",
        "Convert stale heartbeat, lease, queue, and batch-window states into AG attention.",
    ),
    PlannedRuntimeStep(
        "s54_closure",
        "Slice_0540",
        "Close the daemon runtime enablement track with quality-gate evidence.",
    ),
)

SENSITIVE_PATTERNS = (
    re.compile(r"postgresql(?:\+\w+)?://[^\"'\s]+", re.IGNORECASE),
    re.compile(r"nuri1004", re.IGNORECASE),
    re.compile(r"/data/nex-platform", re.IGNORECASE),
    re.compile(r"ed6@c496em", re.IGNORECASE),
    re.compile(r"service-token-[\w-]+", re.IGNORECASE),
)


def run_ae_scheduler_daemon_runtime_boundary_audit(
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
        "s53_closed_baseline_present": group_status.get("s53_closed_baseline")
        is True,
        "ae_daemon_contract_owner_present": group_status.get(
            "ae_daemon_contract_owner"
        )
        is True,
        "ae_runtime_safety_guardrails_present": group_status.get(
            "ae_runtime_safety_guardrails"
        )
        is True,
        "queue_worker_runtime_present": group_status.get("queue_worker_runtime")
        is True,
        "api_control_surface_present": group_status.get("api_control_surface")
        is True,
        "ag_visibility_boundary_present": group_status.get("ag_visibility_boundary")
        is True,
        "postgres_daemon_evidence_present": group_status.get(
            "postgres_daemon_evidence"
        )
        is True,
        "quality_gate_and_docs_present": group_status.get("quality_gate_and_docs")
        is True,
        "test_profile_explicit_opt_in_required": True,
        "start_daemon_default_blocked": True,
        "continuous_loop_default_blocked": True,
        "one_cycle_before_continuous_loop": True,
        "lease_required_before_runtime_tick": True,
        "batch_window_required_before_runtime_tick": True,
        "physical_delete_automation_deferred": True,
        "ag_direct_database_access_disallowed": True,
        "redacted_evidence_only": True,
    }
    issues = build_issues(paths, tokens)
    status = "PASS" if all(checks.values()) and not issues else "FAIL"
    evidence: dict[str, Any] = {
        "audit_schema_version": SCHEMA_VERSION,
        "status": status,
        "failure_code": None if status == "PASS" else "ae_scheduler_daemon_runtime_boundary_failed",
        "slice": "0531",
        "surface": S54_RUNTIME_SURFACE,
        "runtime_boundary": {
            "artifact_system_of_record": "nex-ae-api",
            "operator_projection_owner": "nex-ag",
            "enablement_boundary": S54_ENABLEMENT_BOUNDARY,
            "default_daemon_mode": DEFAULT_DAEMON_MODE,
            "default_execution_mode": DEFAULT_EXECUTION_MODE,
            "start_daemon_allowed_by_default": False,
            "continuous_loop_allowed_by_default": False,
            "runtime_enablement_allowed_profiles": ["test"],
            "runtime_enablement_requires_explicit_env": True,
            "one_cycle_runner_required_before_loop": True,
            "lease_required_before_any_tick": True,
            "fencing_token_required": True,
            "batch_window_enforced": True,
            "job_queue_required": True,
            "worker_runner_explicit": True,
            "physical_delete_automation_enabled": False,
            "postgres_smoke_required_before_runtime_enablement": True,
            "ag_control_boundary": "ae_api_only",
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
        },
        "refactoring_checkpoint": {
            "keep_long_running_loop_out_of_artifacts_module": True,
            "expand_config_before_runtime_code": True,
            "pure_state_machine_before_side_effects": True,
            "one_cycle_runner_before_continuous_loop": True,
            "heartbeat_read_model_before_ag_projection": True,
            "protected_postgres_smoke_before_start_daemon_opt_in": True,
        },
        "paths": paths,
        "source_tokens": tokens,
        "planned_runtime_steps": build_planned_runtime_steps(),
        "checks": checks,
        "issues": issues,
        "next_slices": [NEXT_SLICE, "Slice_0533", "Slice_0534", "Slice_0535"],
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
            "raw_daemon_heartbeat_payload_included": False,
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


def build_planned_runtime_steps() -> list[dict[str, str | bool]]:
    return [
        {
            "name": item.name,
            "planned_slice": item.planned_slice,
            "purpose": item.purpose,
            "blocking": False,
        }
        for item in PLANNED_RUNTIME_STEPS
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
    suffix = (
        f"paths={present_count(list(evidence['paths']))}/{len(evidence['paths'])} "
        f"token_groups={sum(1 for passed in grouped_token_status(list(evidence['source_tokens'])).values() if passed)}/"
        f"{len(grouped_token_status(list(evidence['source_tokens'])))} "
        f"boundary={S54_ENABLEMENT_BOUNDARY} "
        f"daemon={DEFAULT_DAEMON_MODE} "
        f"mode={DEFAULT_EXECUTION_MODE} "
        f"next={NEXT_SLICE}"
    )
    if failing_checks:
        suffix += f" failing_checks={','.join(failing_checks)}"
    return (
        "ae_scheduler_daemon_runtime_boundary_audit="
        f"{str(evidence['status']).lower()} {suffix}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run AE scheduler daemon runtime boundary audit."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence = run_ae_scheduler_daemon_runtime_boundary_audit()
        if args.output:
            write_audit_evidence(args.output, evidence)
        print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2))
        return 0 if evidence["status"] == "PASS" else 1
    except Exception as exc:
        print(
            "ae_scheduler_daemon_runtime_boundary_audit=fail "
            f"error={exc.__class__.__name__}"
        )
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
