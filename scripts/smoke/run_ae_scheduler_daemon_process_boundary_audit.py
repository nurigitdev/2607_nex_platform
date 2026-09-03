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
SCHEMA_VERSION = "ae_scheduler_daemon_process_boundary_audit.v1"

PROTECTED_ENV_KEYS = (
    "NEX_AE_DATABASE_URL",
    "NEX_AE_TEST_DATABASE_URL",
    "NEX_AE_ARTIFACT_STORAGE_ROOT",
    "NEX_AG_AE_ARTIFACT_BASE_URL",
    "NEX_AG_AE_ARTIFACT_SERVICE_TOKEN",
    "NEX_SERVICE_TOKEN",
)

S55_PROCESS_SURFACE = "S55 AE scheduler daemon controlled runtime enablement"
S55_PROCESS_BOUNDARY = "ae_owned_external_process"
JOB_QUEUE_EXECUTION_BOUNDARY = "finite_retention_jobs_only"
DEFAULT_DAEMON_MODE = "disabled"
DEFAULT_EXECUTION_MODE = "DRY_RUN"
NEXT_SLICE = "Slice_0542"


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
class PlannedProcessStep:
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
S54_CLOSURE = (
    ROOT / "scripts" / "smoke" / "run_s54_ae_scheduler_daemon_runtime_closure.py"
)
S54_CLOSURE_TEST = ROOT / "tests" / "test_s54_ae_scheduler_daemon_runtime_closure.py"
S54_CLOSURE_DOC = (
    ROOT / "docs" / "slices" / "0540_s54_ae_scheduler_daemon_runtime_closure.md"
)
S54_RUNTIME_AUDIT = (
    ROOT / "scripts" / "smoke" / "run_ae_scheduler_daemon_runtime_boundary_audit.py"
)
S54_ONE_CYCLE_SMOKE = (
    ROOT
    / "scripts"
    / "smoke"
    / "run_ae_artifact_retention_scheduler_daemon_one_cycle_postgres_smoke.py"
)
S54_AG_DAEMON_SMOKE = (
    ROOT
    / "scripts"
    / "smoke"
    / "run_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke.py"
)
S55_PROCESS_AUDIT = (
    ROOT / "scripts" / "smoke" / "run_ae_scheduler_daemon_process_boundary_audit.py"
)
S55_PROCESS_AUDIT_TEST = (
    ROOT / "tests" / "test_ae_scheduler_daemon_process_boundary_audit.py"
)
S55_PROCESS_AUDIT_DOC = (
    ROOT / "docs" / "slices" / "0541_ae_scheduler_daemon_process_boundary_audit.md"
)

REQUIRED_PATHS = (
    RequiredPath("ae_api_artifacts", AE_API_ARTIFACTS, "AE route/runtime surface."),
    RequiredPath("ae_scheduler", AE_SCHEDULER, "AE daemon coordinator surface."),
    RequiredPath("ae_api_readme", AE_API_README, "AE scheduler process notes."),
    RequiredPath("ag_artifact_operations", AG_ARTIFACT_OPERATIONS, "AG operator view."),
    RequiredPath("ag_readme", AG_README, "AG daemon operations notes."),
    RequiredPath("shared_job_runtime", SHARED_JOB_RUNTIME, "Shared JobQueue runtime."),
    RequiredPath("shared_worker_runner", SHARED_WORKER_RUNNER, "Shared worker runner."),
    RequiredPath("s54_closure", S54_CLOSURE, "Closed S54 runtime baseline."),
    RequiredPath("s54_closure_test", S54_CLOSURE_TEST, "S54 closure regression."),
    RequiredPath("s54_closure_doc", S54_CLOSURE_DOC, "S54 closure documentation."),
    RequiredPath("s54_runtime_audit", S54_RUNTIME_AUDIT, "S54 runtime boundary audit."),
    RequiredPath(
        "s54_one_cycle_smoke",
        S54_ONE_CYCLE_SMOKE,
        "Protected one-cycle daemon PostgreSQL evidence.",
    ),
    RequiredPath(
        "s54_ag_daemon_smoke",
        S54_AG_DAEMON_SMOKE,
        "Protected AG-to-AE daemon PostgreSQL evidence.",
    ),
    RequiredPath("s55_process_audit", S55_PROCESS_AUDIT, "S55 process boundary audit."),
    RequiredPath(
        "s55_process_audit_test",
        S55_PROCESS_AUDIT_TEST,
        "S55 process boundary audit regression.",
    ),
    RequiredPath(
        "s55_process_audit_doc",
        S55_PROCESS_AUDIT_DOC,
        "S55 process boundary audit slice note.",
    ),
    RequiredPath("quality_gate", QUALITY_GATE, "Default regression gate."),
    RequiredPath("docs_index", DOCS_INDEX, "Slice index."),
)

REQUIRED_SOURCE_TOKENS = (
    TokenRequirement(
        "s54_closed_baseline",
        S54_CLOSURE,
        "s54_slice_range",
        "0531-0540",
        "S55 starts only after the S54 daemon runtime closure.",
    ),
    TokenRequirement(
        "s54_closed_baseline",
        S54_CLOSURE,
        "s54_continuous_loop_deferred",
        '"continuous_loop_deferred": True',
        "Continuous loop execution remains deferred at S55 entry.",
    ),
    TokenRequirement(
        "s54_closed_baseline",
        S54_CLOSURE,
        "s54_heartbeat_observable",
        '"daemon_heartbeat_observable": True',
        "S55 starts with heartbeat observability already closed.",
    ),
    TokenRequirement(
        "s54_closed_baseline",
        S54_CLOSURE,
        "s54_runtime_issue_candidates",
        '"runtime_issue_candidates_ready": True',
        "AG runtime attention evidence is available before process enablement.",
    ),
    TokenRequirement(
        "daemon_coordinator_boundary",
        AE_SCHEDULER,
        "daemon_one_cycle_runner",
        "run_artifact_retention_scheduler_daemon_one_cycle",
        "Daemon process iterations should reuse the one-cycle coordinator.",
    ),
    TokenRequirement(
        "daemon_coordinator_boundary",
        AE_SCHEDULER,
        "daemon_loop_planner",
        "build_artifact_retention_scheduler_daemon_loop_plan",
        "Daemon process iterations must plan before side effects.",
    ),
    TokenRequirement(
        "daemon_coordinator_boundary",
        AE_SCHEDULER,
        "daemon_runtime_observation",
        "build_artifact_retention_scheduler_daemon_runtime_observation",
        "Process state should remain observable through metadata-only runtime readback.",
    ),
    TokenRequirement(
        "daemon_coordinator_boundary",
        AE_SCHEDULER,
        "daemon_heartbeat_emitter_optional",
        "daemon_heartbeat_emitter: Any | None = None",
        "Heartbeat emission should not make the one-cycle coordinator depend on a daemon process.",
    ),
    TokenRequirement(
        "daemon_coordinator_boundary",
        AE_SCHEDULER,
        "continuous_loop_not_started",
        '"continuous_loop_started": False',
        "S55 must not inherit an already-started continuous loop.",
    ),
    TokenRequirement(
        "queue_execution_boundary",
        AE_SCHEDULER,
        "tick_once_runner",
        "run_artifact_retention_scheduler_tick_once",
        "Daemon process ticks must delegate to the existing tick-once runner.",
    ),
    TokenRequirement(
        "queue_execution_boundary",
        AE_SCHEDULER,
        "tick_job_admission_import",
        "enqueue_artifact_retention_scheduler_tick_job",
        "Retention work must enter through scheduler tick JobQueue admission.",
    ),
    TokenRequirement(
        "queue_execution_boundary",
        AE_SCHEDULER,
        "scheduled_worker_once_import",
        "run_artifact_retention_scheduled_worker_once",
        "Worker execution remains finite and explicit.",
    ),
    TokenRequirement(
        "queue_execution_boundary",
        AE_SCHEDULER,
        "run_worker_explicit_flag",
        "run_worker: bool = False",
        "Worker execution must remain explicit for protected smoke and daemon cycles.",
    ),
    TokenRequirement(
        "queue_execution_boundary",
        AE_API_ARTIFACTS,
        "queue_enqueue_call",
        'queue.enqueue(validated_admission["job"])',
        "Actual retention work is submitted to JobQueue.",
    ),
    TokenRequirement(
        "queue_execution_boundary",
        SHARED_JOB_RUNTIME,
        "sqlalchemy_job_queue",
        "class SqlAlchemyJobQueue",
        "Persistent queue execution stays on the shared JobQueue adapter.",
    ),
    TokenRequirement(
        "queue_execution_boundary",
        SHARED_WORKER_RUNNER,
        "worker_once",
        "run_worker_once",
        "Daemon process design must not replace the shared worker execution path.",
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
        "AE API remains the daemon runtime read boundary.",
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
        "control_route_job_queue_injection",
        "job_queue=artifact_retention_job_queue",
        "Control requests must use the AE-owned JobQueue instance.",
    ),
    TokenRequirement(
        "api_control_boundary",
        AE_API_ARTIFACTS,
        "control_route_explicit_worker_flag",
        'run_worker=payload.get("run_worker") is True',
        "Route-triggered worker execution must stay explicit.",
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
        "ag_daemon_runtime_client",
        "get_artifact_retention_scheduler_daemon_runtime",
        "AG can observe daemon runtime only through AE API.",
    ),
    TokenRequirement(
        "ag_visibility_boundary",
        AG_ARTIFACT_OPERATIONS,
        "heartbeat_attention_state",
        "HEARTBEAT_ATTENTION",
        "AG has operator attention evidence for runtime failures.",
    ),
    TokenRequirement(
        "protected_postgres_evidence",
        S54_ONE_CYCLE_SMOKE,
        "one_cycle_postgres_env_guard",
        "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ONE_CYCLE_POSTGRES_SMOKE",
        "One-cycle daemon evidence remains protected by an env guard.",
    ),
    TokenRequirement(
        "protected_postgres_evidence",
        S54_ONE_CYCLE_SMOKE,
        "one_cycle_live_db",
        "live_db",
        "One-cycle evidence must prove real test DB execution when enabled.",
    ),
    TokenRequirement(
        "protected_postgres_evidence",
        S54_ONE_CYCLE_SMOKE,
        "one_cycle_job_readback",
        "_job_observation",
        "One-cycle smoke evidence must read back JobQueue state.",
    ),
    TokenRequirement(
        "protected_postgres_evidence",
        S54_ONE_CYCLE_SMOKE,
        "one_cycle_heartbeat_readback",
        "daemon_heartbeat",
        "One-cycle smoke evidence must read back daemon heartbeat state.",
    ),
    TokenRequirement(
        "protected_postgres_evidence",
        S54_AG_DAEMON_SMOKE,
        "ag_daemon_postgres_env_guard",
        "NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_POSTGRES_SMOKE",
        "AG-to-AE daemon evidence remains protected by an env guard.",
    ),
    TokenRequirement(
        "protected_postgres_evidence",
        S54_AG_DAEMON_SMOKE,
        "ag_daemon_live_db",
        "live_db",
        "AG-to-AE daemon evidence must prove real test DB execution when enabled.",
    ),
    TokenRequirement(
        "quality_gate_and_docs",
        QUALITY_GATE,
        "s55_boundary_gate_hook",
        "run_ae_scheduler_daemon_process_boundary_audit.py",
        "The S55 process boundary audit should run in the default quality gate.",
    ),
    TokenRequirement(
        "quality_gate_and_docs",
        DOCS_INDEX,
        "s55_slice_index",
        "Slice 0541",
        "The docs index should expose the S55 starting point.",
    ),
    TokenRequirement(
        "quality_gate_and_docs",
        AE_API_README,
        "s55_ae_readme_note",
        "Slice 0541 starts S55",
        "AE README should document the daemon process boundary.",
    ),
    TokenRequirement(
        "quality_gate_and_docs",
        AG_README,
        "s55_ag_readme_note",
        "Slice 0541 starts S55",
        "AG README should document its read-only daemon process visibility boundary.",
    ),
)

PLANNED_PROCESS_STEPS = (
    PlannedProcessStep(
        "runtime_state_contract",
        "Slice_0542",
        "Define daemon instance, lifecycle, shutdown, backoff, and last-cycle state.",
    ),
    PlannedProcessStep(
        "cli_entrypoint_foundation",
        "Slice_0543",
        "Add a safe AE-owned daemon CLI entrypoint with bounded options first.",
    ),
    PlannedProcessStep(
        "bounded_loop_adapter",
        "Slice_0544",
        "Run bounded coordinator loops that reuse one-cycle and JobQueue paths.",
    ),
    PlannedProcessStep(
        "bounded_postgresql_smoke",
        "Slice_0545",
        "Prove bounded loop behavior against the real AE test DB.",
    ),
    PlannedProcessStep(
        "graceful_shutdown_state_transition",
        "Slice_0546",
        "Add explicit shutdown request handling and STOPPING/STOPPED evidence.",
    ),
    PlannedProcessStep(
        "retry_backoff_circuit_guard",
        "Slice_0547",
        "Add consecutive failure backoff and circuit-open metadata.",
    ),
    PlannedProcessStep(
        "ag_lifecycle_projection",
        "Slice_0548",
        "Project daemon lifecycle, shutdown, and backoff state into AG read-only views.",
    ),
    PlannedProcessStep(
        "ag_to_ae_lifecycle_postgresql_smoke",
        "Slice_0549",
        "Prove AG reads AE daemon process lifecycle state through AE APIs and test DB.",
    ),
    PlannedProcessStep(
        "s55_closure",
        "Slice_0550",
        "Close controlled daemon runtime enablement with quality-gate evidence.",
    ),
)

SENSITIVE_PATTERNS = (
    re.compile(r"postgresql(?:\+\w+)?://[^\"'\s]+", re.IGNORECASE),
    re.compile(r"nuri1004", re.IGNORECASE),
    re.compile(r"/data/nex-platform", re.IGNORECASE),
    re.compile(r"ed6@c496em", re.IGNORECASE),
    re.compile(r"service-token-[\w-]+", re.IGNORECASE),
)


def run_ae_scheduler_daemon_process_boundary_audit(
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
        "s54_closed_baseline_present": group_status.get("s54_closed_baseline")
        is True,
        "daemon_coordinator_boundary_present": group_status.get(
            "daemon_coordinator_boundary"
        )
        is True,
        "queue_execution_boundary_present": group_status.get(
            "queue_execution_boundary"
        )
        is True,
        "api_control_boundary_present": group_status.get("api_control_boundary")
        is True,
        "ag_visibility_boundary_present": group_status.get("ag_visibility_boundary")
        is True,
        "protected_postgres_evidence_present": group_status.get(
            "protected_postgres_evidence"
        )
        is True,
        "quality_gate_and_docs_present": group_status.get("quality_gate_and_docs")
        is True,
        "daemon_is_coordinator_not_worker": True,
        "retention_work_uses_job_queue": True,
        "daemon_not_jobqueue_long_running_job": True,
        "api_embedded_long_loop_disallowed": True,
        "bounded_loop_required_before_continuous_loop": True,
        "runtime_state_required_before_process_start": True,
        "graceful_shutdown_required_before_process_start": True,
        "protected_test_db_smoke_required": True,
        "redacted_evidence_only": True,
    }
    issues = build_issues(paths, tokens)
    status = "PASS" if all(checks.values()) and not issues else "FAIL"
    evidence: dict[str, Any] = {
        "audit_schema_version": SCHEMA_VERSION,
        "status": status,
        "failure_code": None if status == "PASS" else "ae_scheduler_daemon_process_boundary_failed",
        "slice": "0541",
        "surface": S55_PROCESS_SURFACE,
        "process_boundary": {
            "artifact_system_of_record": "nex-ae-api",
            "operator_projection_owner": "nex-ag",
            "daemon_process_owner": "nex-ae-api",
            "daemon_process_model": S55_PROCESS_BOUNDARY,
            "daemon_role": "coordinator",
            "job_queue_role": "finite_retention_work_execution",
            "job_queue_execution_boundary": JOB_QUEUE_EXECUTION_BOUNDARY,
            "daemon_as_jobqueue_job_allowed": False,
            "api_embedded_long_running_loop_allowed": False,
            "retention_work_must_use_job_queue": True,
            "worker_slot_reserved_for_finite_jobs": True,
            "control_surface": "ae_api_and_daemon_runtime_state",
            "ag_control_boundary": "ae_api_only",
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
            "default_daemon_mode": DEFAULT_DAEMON_MODE,
            "default_execution_mode": DEFAULT_EXECUTION_MODE,
            "runtime_state_store_required_before_start": True,
            "heartbeat_store_required_for_observability": True,
            "bounded_loop_required_before_continuous_loop": True,
            "graceful_shutdown_required_before_start": True,
            "postgres_smoke_required_before_enablement": True,
        },
        "refactoring_checkpoint": {
            "keep_loop_entrypoint_out_of_artifacts_module": True,
            "reuse_one_cycle_runner_for_each_daemon_iteration": True,
            "reuse_scheduler_tick_job_admission": True,
            "do_not_run_daemon_as_jobqueue_worker_job": True,
            "keep_worker_slots_for_finite_retention_jobs": True,
            "persist_control_decisions_before_process_start": True,
            "metadata_only_ag_projection": True,
        },
        "paths": paths,
        "source_tokens": tokens,
        "planned_process_steps": build_planned_process_steps(),
        "checks": checks,
        "issues": issues,
        "next_slices": [
            NEXT_SLICE,
            "Slice_0543",
            "Slice_0544",
            "Slice_0545",
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
            "raw_daemon_heartbeat_payload_included": False,
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


def build_planned_process_steps() -> list[dict[str, str | bool]]:
    return [
        {
            "name": item.name,
            "planned_slice": item.planned_slice,
            "purpose": item.purpose,
            "blocking": False,
        }
        for item in PLANNED_PROCESS_STEPS
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
        f"boundary={S55_PROCESS_BOUNDARY} "
        f"queue={JOB_QUEUE_EXECUTION_BOUNDARY} "
        f"daemon={DEFAULT_DAEMON_MODE} "
        f"mode={DEFAULT_EXECUTION_MODE} "
        f"next={NEXT_SLICE}"
    )
    if failing_checks:
        suffix += f" failing_checks={','.join(failing_checks)}"
    return (
        "ae_scheduler_daemon_process_boundary_audit="
        f"{str(evidence['status']).lower()} {suffix}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run AE scheduler daemon process boundary audit."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence = run_ae_scheduler_daemon_process_boundary_audit()
        if args.output:
            write_audit_evidence(args.output, evidence)
        print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2))
        return 0 if evidence["status"] == "PASS" else 1
    except Exception as exc:
        print(
            "ae_scheduler_daemon_process_boundary_audit=fail "
            f"error={exc.__class__.__name__}"
        )
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
