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
SCHEMA_VERSION = "ae_artifact_retention_scheduler_daemon_boundary_audit.v1"

PROTECTED_ENV_KEYS = (
    "NEX_AE_DATABASE_URL",
    "NEX_AE_TEST_DATABASE_URL",
    "NEX_AE_ARTIFACT_STORAGE_ROOT",
    "NEX_AG_AE_ARTIFACT_SERVICE_TOKEN",
    "NEX_SERVICE_TOKEN",
)

DEFAULT_EXECUTION_MODE = "DRY_RUN"
SCHEDULER_DAEMON_DEFAULT = "disabled"
FIRST_S52_RUNTIME_MODE = "manual_once_dry_run_tick_runner"


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
class PlannedDaemonStep:
    name: str
    planned_slice: str
    purpose: str


AE_API_ARTIFACTS = ROOT / "services" / "nex-ae-api" / "nex_ae_api" / "artifacts.py"
AE_API_README = ROOT / "services" / "nex-ae-api" / "README.md"
AG_ARTIFACT_OPERATIONS = ROOT / "services" / "nex-ag" / "nex_ag" / "artifact_operations.py"
AG_README = ROOT / "services" / "nex-ag" / "README.md"
SHARED_JOB_RUNTIME = ROOT / "services" / "_shared" / "nex_runtime" / "jobs.py"
QUALITY_GATE = ROOT / "scripts" / "quality" / "run_quality_gate.sh"
DOCS_INDEX = ROOT / "docs" / "README.md"
S51_CLOSURE = (
    ROOT / "scripts" / "smoke" / "run_s51_ae_artifact_retention_automation_closure.py"
)
S51_CLOSURE_TEST = (
    ROOT / "tests" / "test_s51_ae_artifact_retention_automation_closure.py"
)
S51_CLOSURE_DOC = (
    ROOT / "docs" / "slices" / "0510_s51_ae_artifact_retention_automation_closure.md"
)
S52_AUDIT = (
    ROOT
    / "scripts"
    / "smoke"
    / "run_ae_artifact_retention_scheduler_daemon_boundary_audit.py"
)
S52_AUDIT_TEST = (
    ROOT / "tests" / "test_ae_artifact_retention_scheduler_daemon_boundary_audit.py"
)
S52_AUDIT_DOC = (
    ROOT
    / "docs"
    / "slices"
    / "0511_ae_scheduler_daemon_boundary_audit_refactoring_checkpoint.md"
)
S51_TICK_SMOKE = (
    ROOT / "scripts" / "smoke" / "run_ae_artifact_retention_scheduler_tick_postgres_smoke.py"
)
S51_PHYSICAL_PURGE_SMOKE = (
    ROOT
    / "scripts"
    / "smoke"
    / "run_ae_artifact_retention_physical_purge_postgres_smoke.py"
)
S51_AE_AG_SMOKE = (
    ROOT / "scripts" / "smoke" / "run_ae_ag_artifact_retention_scheduler_postgres_smoke.py"
)

REQUIRED_PATHS = (
    RequiredPath("ae_api_artifacts", AE_API_ARTIFACTS, "AE retention runtime."),
    RequiredPath("ae_api_readme", AE_API_README, "AE scheduler notes."),
    RequiredPath("ag_artifact_operations", AG_ARTIFACT_OPERATIONS, "AG operator view."),
    RequiredPath("ag_readme", AG_README, "AG scheduler notes."),
    RequiredPath("shared_job_runtime", SHARED_JOB_RUNTIME, "Shared JobQueue runtime."),
    RequiredPath("s51_closure", S51_CLOSURE, "Closed S51 safety baseline."),
    RequiredPath("s51_closure_test", S51_CLOSURE_TEST, "S51 closure regression."),
    RequiredPath("s51_closure_doc", S51_CLOSURE_DOC, "S51 closure documentation."),
    RequiredPath("s51_tick_smoke", S51_TICK_SMOKE, "Scheduler tick DB evidence."),
    RequiredPath(
        "s51_physical_purge_smoke",
        S51_PHYSICAL_PURGE_SMOKE,
        "Physical purge DB evidence.",
    ),
    RequiredPath("s51_ae_ag_smoke", S51_AE_AG_SMOKE, "AE/AG DB evidence."),
    RequiredPath("s52_audit", S52_AUDIT, "S52 daemon boundary audit."),
    RequiredPath("s52_audit_test", S52_AUDIT_TEST, "S52 audit regression."),
    RequiredPath("s52_audit_doc", S52_AUDIT_DOC, "S52 audit slice note."),
    RequiredPath("quality_gate", QUALITY_GATE, "Default regression gate."),
    RequiredPath("docs_index", DOCS_INDEX, "Slice index."),
)

REQUIRED_SOURCE_TOKENS = (
    TokenRequirement(
        "s51_closed_baseline",
        S51_CLOSURE,
        "s51_slice_range",
        "0501-0510",
        "S52 starts only after S51 retention automation closure.",
    ),
    TokenRequirement(
        "s51_closed_baseline",
        S51_CLOSURE,
        "s51_daemon_default_disabled",
        '"scheduler_daemon_default_disabled": True',
        "S52 must keep daemon auto-start disabled at entry.",
    ),
    TokenRequirement(
        "s51_closed_baseline",
        S51_CLOSURE,
        "s51_physical_delete_disabled",
        '"physical_delete_automation_disabled": True',
        "S52 must not loosen physical delete automation.",
    ),
    TokenRequirement(
        "ae_scheduler_daemon_guard",
        AE_API_ARTIFACTS,
        "scheduler_daemon_disabled",
        '"scheduler_daemon_enabled": False',
        "Scheduler daemon is disabled by default.",
    ),
    TokenRequirement(
        "ae_scheduler_daemon_guard",
        AE_API_ARTIFACTS,
        "scheduler_daemon_not_started",
        '"scheduler_daemon_started": False',
        "Runtime evidence must show daemon startup did not happen.",
    ),
    TokenRequirement(
        "ae_scheduler_daemon_guard",
        AE_API_ARTIFACTS,
        "scheduler_tick_admission_enabled",
        '"scheduler_tick_admission_enabled": True',
        "Manual ticks can still use the existing admission path.",
    ),
    TokenRequirement(
        "ae_scheduler_daemon_guard",
        AE_API_ARTIFACTS,
        "scheduler_tick_lock_ttl",
        "ARTIFACT_RETENTION_SCHEDULER_TICK_LOCK_TTL_SECONDS = 600",
        "Lease work should inherit the frozen lock TTL.",
    ),
    TokenRequirement(
        "ae_scheduler_daemon_guard",
        AE_API_ARTIFACTS,
        "scheduler_tick_stale_after",
        "ARTIFACT_RETENTION_SCHEDULER_TICK_STALE_AFTER_SECONDS = 3600",
        "Lease work should retain stale tick protection.",
    ),
    TokenRequirement(
        "ae_tick_runtime",
        AE_API_ARTIFACTS,
        "scheduler_config_builder",
        "build_artifact_retention_scheduler_config",
        "The daemon boundary needs the existing config read-model.",
    ),
    TokenRequirement(
        "ae_tick_runtime",
        AE_API_ARTIFACTS,
        "scheduler_tick_planner",
        "build_artifact_retention_scheduler_tick_plan",
        "The manual once runner should plan before admission.",
    ),
    TokenRequirement(
        "ae_tick_runtime",
        AE_API_ARTIFACTS,
        "scheduler_tick_admission",
        "enqueue_artifact_retention_scheduler_tick_job",
        "The manual once runner should reuse JobQueue admission.",
    ),
    TokenRequirement(
        "ae_tick_runtime",
        AE_API_ARTIFACTS,
        "scheduled_job_queue",
        "build_default_artifact_retention_scheduled_job_queue",
        "Job persistence stays behind the shared queue adapter.",
    ),
    TokenRequirement(
        "ae_tick_runtime",
        AE_API_ARTIFACTS,
        "scheduled_worker_once",
        "run_artifact_retention_scheduled_worker_once",
        "Worker execution remains explicit and one-shot.",
    ),
    TokenRequirement(
        "ae_tick_runtime",
        SHARED_JOB_RUNTIME,
        "sqlalchemy_job_queue",
        "class SqlAlchemyJobQueue",
        "PostgreSQL smoke should continue through the shared JobQueue.",
    ),
    TokenRequirement(
        "ae_delete_safety",
        AE_API_ARTIFACTS,
        "operator_approval_required_reason",
        'ARTIFACT_RETENTION_OPERATOR_APPROVAL_REQUIRED_REASON = "operator_approval_required"',
        "Physical purge still requires an operator approval blocker.",
    ),
    TokenRequirement(
        "ae_delete_safety",
        AE_API_ARTIFACTS,
        "execute_requires_operator_approval",
        '"execute_requires_operator_approval": True',
        "Execute mode must require operator approval.",
    ),
    TokenRequirement(
        "ae_delete_safety",
        AE_API_ARTIFACTS,
        "physical_delete_disabled",
        '"physical_delete_automation_enabled": False',
        "Physical delete automation must stay disabled.",
    ),
    TokenRequirement(
        "ae_delete_safety",
        AE_API_ARTIFACTS,
        "physical_purge_adapter",
        "delete_artifact_retention_physical_records",
        "Physical purge remains behind an explicit adapter.",
    ),
    TokenRequirement(
        "ag_operator_boundary",
        AG_ARTIFACT_OPERATIONS,
        "ag_automation_projection_schema",
        "AG_ARTIFACT_OPERATION_RETENTION_AUTOMATION_PROJECTION_SCHEMA_VERSION",
        "AG already has automation observability.",
    ),
    TokenRequirement(
        "ag_operator_boundary",
        AG_ARTIFACT_OPERATIONS,
        "ag_automation_route",
        '"/admin/v1/operations/artifact-retention/automation"',
        "AG exposes the operator-facing automation route.",
    ),
    TokenRequirement(
        "ag_operator_boundary",
        AG_ARTIFACT_OPERATIONS,
        "ag_direct_database_write_disallowed",
        '"ag_direct_database_write_allowed": False',
        "AG must not write AE persistence directly.",
    ),
    TokenRequirement(
        "ag_operator_boundary",
        AG_ARTIFACT_OPERATIONS,
        "ag_direct_job_enqueue_disallowed",
        '"ag_direct_job_enqueue_allowed": False',
        "AG must not enqueue AE jobs directly.",
    ),
    TokenRequirement(
        "postgres_smoke_evidence",
        S51_TICK_SMOKE,
        "tick_smoke_env",
        "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_TICK_POSTGRES_SMOKE",
        "Mutating tick evidence remains opt-in.",
    ),
    TokenRequirement(
        "postgres_smoke_evidence",
        S51_TICK_SMOKE,
        "tick_smoke_live_db",
        "live_db",
        "Tick evidence must prove real test DB execution when enabled.",
    ),
    TokenRequirement(
        "postgres_smoke_evidence",
        S51_PHYSICAL_PURGE_SMOKE,
        "physical_purge_smoke_env",
        "NEX_AE_ARTIFACT_RETENTION_PHYSICAL_PURGE_POSTGRES_SMOKE",
        "Physical purge evidence remains opt-in.",
    ),
    TokenRequirement(
        "postgres_smoke_evidence",
        S51_PHYSICAL_PURGE_SMOKE,
        "physical_purge_operator_approval",
        "operator_approval_required",
        "Physical purge evidence covers the approval blocker.",
    ),
    TokenRequirement(
        "postgres_smoke_evidence",
        S51_AE_AG_SMOKE,
        "ae_ag_smoke_env",
        "NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_POSTGRES_SMOKE",
        "Cross-service evidence remains opt-in.",
    ),
    TokenRequirement(
        "postgres_smoke_evidence",
        S51_AE_AG_SMOKE,
        "ae_ag_automation_projection",
        '"ag_automation"',
        "Cross-service evidence includes the AG automation projection.",
    ),
    TokenRequirement(
        "quality_gate_and_docs",
        QUALITY_GATE,
        "s52_audit_gate_hook",
        "run_ae_artifact_retention_scheduler_daemon_boundary_audit.py",
        "The S52 boundary audit should run in the default quality gate.",
    ),
    TokenRequirement(
        "quality_gate_and_docs",
        QUALITY_GATE,
        "s51_closure_gate_hook",
        "run_s51_ae_artifact_retention_automation_closure.py",
        "S51 closure remains registered before S52 work.",
    ),
    TokenRequirement(
        "quality_gate_and_docs",
        DOCS_INDEX,
        "s52_slice_index",
        "Slice 0511",
        "The docs index should expose the S52 starting point.",
    ),
    TokenRequirement(
        "quality_gate_and_docs",
        AE_API_README,
        "s52_ae_readme_note",
        "Slice 0511 starts S52",
        "AE README should document the S52 daemon boundary.",
    ),
    TokenRequirement(
        "quality_gate_and_docs",
        AG_README,
        "s52_ag_readme_note",
        "Slice 0511 starts S52",
        "AG README should document the S52 operator boundary.",
    ),
    TokenRequirement(
        "refactoring_checkpoint",
        S52_AUDIT_DOC,
        "manual_once_runner_before_daemon",
        "manual once runner",
        "Long-running scheduler behavior should not be introduced first.",
    ),
    TokenRequirement(
        "refactoring_checkpoint",
        S52_AUDIT_DOC,
        "lease_before_daemon",
        "lease/lock repository before daemon execution",
        "Duplicate tick prevention should arrive before daemon execution.",
    ),
    TokenRequirement(
        "refactoring_checkpoint",
        S52_AUDIT_DOC,
        "module_boundary",
        "nex_ae_api.artifacts",
        "The daemon code should be separated before it grows.",
    ),
)

PLANNED_DAEMON_STEPS = (
    PlannedDaemonStep(
        "scheduler_lease_lock_contract",
        "Slice_0512",
        "Define the lease/lock contract before any daemon execution.",
    ),
    PlannedDaemonStep(
        "scheduler_lease_repository_adapter",
        "Slice_0513",
        "Persist scheduler lease state with SQLite regression and PostgreSQL compatibility.",
    ),
    PlannedDaemonStep(
        "scheduler_tick_once_runner",
        "Slice_0514",
        "Run one guarded dry-run tick without starting a continuous daemon.",
    ),
    PlannedDaemonStep(
        "scheduler_tick_once_postgresql_smoke",
        "Slice_0515",
        "Verify lock acquisition, tick admission, DB select, and cleanup in the AE test DB.",
    ),
    PlannedDaemonStep(
        "scheduler_dry_run_loop_planner",
        "Slice_0516",
        "Plan interval, jitter, and batch-window behavior without starting a daemon.",
    ),
    PlannedDaemonStep(
        "scheduler_loop_cli_worker_harness",
        "Slice_0517",
        "Expose a manual dry-run or once CLI harness for operator-driven execution.",
    ),
    PlannedDaemonStep(
        "ag_scheduler_runtime_operations_projection",
        "Slice_0518",
        "Expose lease, last tick, and queue posture through AG without direct writes.",
    ),
    PlannedDaemonStep(
        "ae_ag_scheduler_runtime_postgresql_smoke",
        "Slice_0519",
        "Verify AE runner and AG projection against the real AE test DB.",
    ),
    PlannedDaemonStep(
        "s52_closure",
        "Slice_0520",
        "Close the scheduler daemon dry-run operations track.",
    ),
)

SENSITIVE_PATTERNS = (
    re.compile(r"postgresql(?:\+\w+)?://[^\"'\s]+", re.IGNORECASE),
    re.compile(r"(?:password|passwd|api[-_ ]?key|secret|token)=[^\"'\s,}]+", re.IGNORECASE),
    re.compile(r"/data/nex-platform", re.IGNORECASE),
    re.compile(r"service-token-[\w-]+", re.IGNORECASE),
)


def run_ae_artifact_retention_scheduler_daemon_boundary_audit(
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
        "s51_closed_baseline_present": group_status.get("s51_closed_baseline")
        is True,
        "ae_scheduler_daemon_guard_present": group_status.get(
            "ae_scheduler_daemon_guard"
        )
        is True,
        "ae_tick_runtime_present": group_status.get("ae_tick_runtime") is True,
        "ae_delete_safety_present": group_status.get("ae_delete_safety") is True,
        "ag_operator_boundary_present": group_status.get("ag_operator_boundary")
        is True,
        "postgres_smoke_evidence_present": group_status.get("postgres_smoke_evidence")
        is True,
        "quality_gate_and_docs_present": group_status.get("quality_gate_and_docs")
        is True,
        "refactoring_checkpoint_present": group_status.get("refactoring_checkpoint")
        is True,
        "daemon_auto_start_deferred": True,
        "first_runtime_mode_manual_once": True,
        "lease_required_before_continuous_loop": True,
        "physical_delete_automation_remains_disabled": True,
        "test_db_smoke_required_for_mutating_runner": True,
        "redacted_evidence_only": True,
    }
    issues = build_issues(paths, tokens)
    status = "PASS" if all(checks.values()) and not issues else "FAIL"
    evidence: dict[str, Any] = {
        "audit_schema_version": SCHEMA_VERSION,
        "status": status,
        "failure_code": None if status == "PASS" else "scheduler_daemon_boundary_failed",
        "slice": "0511",
        "surface": "S52 AE artifact retention scheduler daemon dry-run operations",
        "daemon_boundary": {
            "artifact_system_of_record": "nex-ae-api",
            "operator_projection_owner": "nex-ag",
            "scheduler_daemon_default": SCHEDULER_DAEMON_DEFAULT,
            "daemon_auto_start_allowed": False,
            "continuous_loop_allowed_before_lease": False,
            "first_runtime_mode": FIRST_S52_RUNTIME_MODE,
            "default_execution_mode": DEFAULT_EXECUTION_MODE,
            "job_admission_boundary": "ae_api_jobqueue_admission",
            "lease_lock_boundary": "required_before_continuous_loop",
            "ag_control_boundary": "ae_api_only",
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
            "physical_delete_automation_default": "disabled",
            "postgres_smoke_required_for_mutating_runner": True,
        },
        "refactoring_checkpoint": {
            "keep_long_running_scheduler_code_out_of_artifacts_module": True,
            "introduce_lease_repository_before_daemon_loop": True,
            "prefer_manual_once_runner_before_continuous_loop": True,
            "reuse_existing_tick_planner_and_jobqueue_admission": True,
            "reuse_existing_worker_once_adapter": True,
        },
        "paths": paths,
        "source_tokens": tokens,
        "planned_daemon_steps": build_planned_daemon_steps(),
        "checks": checks,
        "issues": issues,
        "next_slices": ["Slice_0512", "Slice_0513", "Slice_0514", "Slice_0515"],
        "protected_env": summarize_protected_env(env),
        "redaction_summary": {
            "database_url_included": False,
            "service_token_included": False,
            "provider_api_key_included": False,
            "storage_path_included": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_included": False,
            "raw_download_content_included": False,
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


def build_planned_daemon_steps() -> list[dict[str, str | bool]]:
    return [
        {
            "name": item.name,
            "planned_slice": item.planned_slice,
            "purpose": item.purpose,
            "blocking": False,
        }
        for item in PLANNED_DAEMON_STEPS
    ]


def grouped_token_status(tokens: list[dict[str, Any]]) -> dict[str, bool]:
    groups = sorted({str(item["group"]) for item in tokens})
    return {
        group: all(item["present"] is True for item in tokens if item["group"] == group)
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
        f"paths={present_count(evidence['paths'])}/{len(evidence['paths'])} "
        f"tokens={present_count(evidence['source_tokens'])}/"
        f"{len(evidence['source_tokens'])} "
        f"daemon={SCHEDULER_DAEMON_DEFAULT} "
        f"mode={FIRST_S52_RUNTIME_MODE} "
        f"next=Slice_0512"
    )
    if failing_checks:
        suffix += f" failing_checks={','.join(failing_checks)}"
    return (
        "ae_artifact_retention_scheduler_daemon_boundary_audit="
        f"{str(evidence['status']).lower()} {suffix}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run AE artifact retention scheduler daemon boundary audit."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence = run_ae_artifact_retention_scheduler_daemon_boundary_audit()
        if args.output:
            write_audit_evidence(args.output, evidence)
        print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2))
        return 0 if evidence["status"] == "PASS" else 1
    except Exception as exc:
        print(
            "ae_artifact_retention_scheduler_daemon_boundary_audit=fail "
            f"error={exc.__class__.__name__}"
        )
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
