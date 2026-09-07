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
SCHEMA_VERSION = "ae_supervised_daemon_process_boundary_audit.v1"

S58_SURFACE = "S58 AE scheduler daemon supervised process execution"
SUPERVISED_PROCESS_BOUNDARY = "protected_subprocess_test_profile_only"
DEFAULT_PROCESS_MODE = "disabled"
DEFAULT_START_MODE = "blocked_until_subprocess_adapter"
FIRST_PROCESS_MODE = "bounded_loop_subprocess_test_only"
NEXT_SLICE = "Slice_0572"

PROTECTED_ENV_KEYS = (
    "NEX_AE_DATABASE_URL",
    "NEX_AE_TEST_DATABASE_URL",
    "NEX_AE_ARTIFACT_STORAGE_ROOT",
    "NEX_AE_SUPERVISED_DAEMON_PROCESS_SMOKE",
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
class PlannedSlice:
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
AE_ARTIFACTS = ROOT / "services" / "nex-ae-api" / "nex_ae_api" / "artifacts.py"
AE_README = ROOT / "services" / "nex-ae-api" / "README.md"
AG_ARTIFACT_OPERATIONS = ROOT / "services" / "nex-ag" / "nex_ag" / "artifact_operations.py"
AG_README = ROOT / "services" / "nex-ag" / "README.md"
DAEMON_SCRIPT = ROOT / "scripts" / "daemon" / "run_ae_artifact_retention_scheduler_daemon.py"
QUALITY_GATE = ROOT / "scripts" / "quality" / "run_quality_gate.sh"
DOCS_INDEX = ROOT / "docs" / "README.md"
S57_CLOSURE = (
    ROOT
    / "scripts"
    / "smoke"
    / "run_s57_ae_scheduler_daemon_supervisor_operations_closure.py"
)
S57_CLOSURE_DOC = (
    ROOT
    / "docs"
    / "slices"
    / "0570_s57_ae_scheduler_daemon_supervisor_operations_closure.md"
)
S58_AUDIT = ROOT / "scripts" / "smoke" / "run_ae_supervised_daemon_process_boundary_audit.py"
S58_AUDIT_TEST = ROOT / "tests" / "test_ae_supervised_daemon_process_boundary_audit.py"
S58_AUDIT_DOC = (
    ROOT
    / "docs"
    / "slices"
    / "0571_ae_supervised_daemon_process_activation_boundary_audit.md"
)

REQUIRED_PATHS = (
    RequiredPath("ae_daemon_runtime", AE_DAEMON, "AE daemon and supervisor runtime module."),
    RequiredPath("ae_artifacts_routes", AE_ARTIFACTS, "AE artifact and supervisor route surface."),
    RequiredPath("ag_artifact_operations", AG_ARTIFACT_OPERATIONS, "AG read-only operations projection."),
    RequiredPath("daemon_cli_script", DAEMON_SCRIPT, "Bounded daemon CLI entrypoint."),
    RequiredPath("s57_closure", S57_CLOSURE, "Closed S57 supervisor baseline."),
    RequiredPath("s57_closure_doc", S57_CLOSURE_DOC, "Closed S57 slice note."),
    RequiredPath("s58_audit", S58_AUDIT, "S58 supervised process boundary audit."),
    RequiredPath("s58_audit_test", S58_AUDIT_TEST, "S58 supervised process boundary tests."),
    RequiredPath("s58_audit_doc", S58_AUDIT_DOC, "S58 supervised process boundary slice note."),
    RequiredPath("quality_gate", QUALITY_GATE, "Default regression gate."),
    RequiredPath("docs_index", DOCS_INDEX, "Slice index."),
    RequiredPath("ae_readme", AE_README, "AE service implementation notes."),
    RequiredPath("ag_readme", AG_README, "AG service implementation notes."),
)

REQUIRED_SOURCE_TOKENS = (
    TokenRequirement(
        "s57_closed_baseline",
        S57_CLOSURE,
        "s57_slice_range",
        "0561-0570",
        "S58 starts only after the S57 supervisor operations closure.",
    ),
    TokenRequirement(
        "s57_closed_baseline",
        S57_CLOSURE,
        "s57_summary_boundary",
        "supervisor=ae_owned ag_projection=read_only start=blocked",
        "S58 inherits AE ownership and AG read-only projection.",
    ),
    TokenRequirement(
        "supervisor_contract",
        AE_DAEMON,
        "supervisor_command_schema",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_COMMAND_SCHEMA_VERSION",
        "Subprocess activation must stay inside schema-bound supervisor commands.",
    ),
    TokenRequirement(
        "supervisor_contract",
        AE_DAEMON,
        "supervisor_result_schema",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_RESULT_SCHEMA_VERSION",
        "Subprocess activation must emit schema-bound supervisor results.",
    ),
    TokenRequirement(
        "supervisor_contract",
        AE_DAEMON,
        "supervisor_actions",
        '"start_daemon"',
        "S58 will only open the existing start action under stricter guards.",
    ),
    TokenRequirement(
        "supervisor_contract",
        AE_DAEMON,
        "supervisor_stop_action",
        '"stop_daemon"',
        "S58 must include a graceful stop path before runtime enablement.",
    ),
    TokenRequirement(
        "supervisor_contract",
        AE_DAEMON,
        "fake_supervisor_adapter",
        "FakeArtifactRetentionSchedulerDaemonSupervisorAdapter",
        "The safe fake adapter remains the default baseline.",
    ),
    TokenRequirement(
        "process_guardrails",
        AE_DAEMON,
        "test_profile_required",
        "profile must be test.",
        "Supervised subprocess execution remains test-profile only.",
    ),
    TokenRequirement(
        "process_guardrails",
        AE_DAEMON,
        "explicit_opt_in_required",
        '"execution_requires_explicit_opt_in": True',
        "Supervised subprocess execution requires explicit opt-in.",
    ),
    TokenRequirement(
        "process_guardrails",
        AE_DAEMON,
        "bounded_max_cycles",
        "MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_MAX_CYCLES",
        "Subprocess execution must remain bounded.",
    ),
    TokenRequirement(
        "process_guardrails",
        AE_DAEMON,
        "process_lock_contract",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_PROCESS_LOCK_SCHEMA_VERSION",
        "A process lock is required before supervised start is enabled.",
    ),
    TokenRequirement(
        "process_guardrails",
        AE_DAEMON,
        "run_metadata_contract",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUN_METADATA_SCHEMA_VERSION",
        "PID and lifecycle evidence must remain metadata-only.",
    ),
    TokenRequirement(
        "process_guardrails",
        AE_DAEMON,
        "shutdown_signal_adapter",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SIGNAL_SHUTDOWN_ADAPTER_SCHEMA_VERSION",
        "Graceful stop must reuse the shutdown signal boundary.",
    ),
    TokenRequirement(
        "bounded_runtime",
        AE_DAEMON,
        "bounded_loop_cli_runner",
        "run_artifact_retention_scheduler_daemon_cli_execution",
        "Subprocess adapter should launch only the existing bounded CLI execution.",
    ),
    TokenRequirement(
        "bounded_runtime",
        DAEMON_SCRIPT,
        "daemon_cli_entrypoint",
        "nex_ae_api.artifact_retention_scheduler_daemon",
        "Process activation must use the existing AE daemon CLI entrypoint.",
    ),
    TokenRequirement(
        "ae_api_surface",
        AE_ARTIFACTS,
        "supervisor_control_route",
        '"/api/v1/artifact-retention/scheduler-daemon-supervisor-controls"',
        "AE already owns the supervisor control admission route.",
    ),
    TokenRequirement(
        "ae_api_surface",
        AE_ARTIFACTS,
        "supervisor_result_route",
        '"/api/v1/artifact-retention/scheduler-daemon-supervisor-results"',
        "AE already owns persisted supervisor readback.",
    ),
    TokenRequirement(
        "ag_operator_boundary",
        AG_ARTIFACT_OPERATIONS,
        "ag_supervisor_projection_schema",
        "AG_ARTIFACT_OPERATION_RETENTION_DAEMON_SUPERVISOR_COLLECTION_PROJECTION_SCHEMA_VERSION",
        "AG can observe supervisor evidence through read-only projections.",
    ),
    TokenRequirement(
        "ag_operator_boundary",
        AG_ARTIFACT_OPERATIONS,
        "ag_direct_process_control_disallowed",
        '"ag_direct_daemon_process_control_allowed": False',
        "AG must not directly start or stop AE processes.",
    ),
    TokenRequirement(
        "ag_operator_boundary",
        AG_ARTIFACT_OPERATIONS,
        "ag_direct_database_write_disallowed",
        '"ag_direct_database_write_allowed": False',
        "AG must not write AE supervisor persistence.",
    ),
    TokenRequirement(
        "quality_docs",
        QUALITY_GATE,
        "s58_audit_quality_gate_hook",
        "run_ae_supervised_daemon_process_boundary_audit.py",
        "The S58 boundary audit must be part of the default gate.",
    ),
    TokenRequirement(
        "quality_docs",
        DOCS_INDEX,
        "s58_audit_doc_indexed",
        "0571_ae_supervised_daemon_process_activation_boundary_audit.md",
        "The Slice 0571 note must be indexed.",
    ),
    TokenRequirement(
        "quality_docs",
        AE_README,
        "ae_s58_readme_note",
        "Slice 0571 starts S58",
        "AE service notes must record the supervised process boundary.",
    ),
    TokenRequirement(
        "quality_docs",
        AG_README,
        "ag_s58_readme_note",
        "Slice 0571 starts S58",
        "AG service notes must record the read-only supervised process boundary.",
    ),
)

PLANNED_SLICES = (
    PlannedSlice(
        "supervised_process_contract_schema",
        "Slice_0572",
        "Add the metadata-only supervised process contract before launching subprocesses.",
    ),
    PlannedSlice(
        "subprocess_supervisor_adapter_foundation",
        "Slice_0573",
        "Add an injectable subprocess adapter behind test-profile guards.",
    ),
    PlannedSlice(
        "supervised_start_guardrail_wiring",
        "Slice_0574",
        "Allow guarded start only for bounded test-profile execution.",
    ),
    PlannedSlice(
        "status_probe_stale_detection",
        "Slice_0575",
        "Classify running, stale, missing, and blocked process states.",
    ),
    PlannedSlice(
        "graceful_stop_wiring",
        "Slice_0576",
        "Wire SIGTERM-style stop before any broader enablement.",
    ),
    PlannedSlice(
        "ae_postgres_smoke",
        "Slice_0577",
        "Prove start/status/stop/readback/cleanup against the real AE test DB.",
    ),
    PlannedSlice(
        "ag_projection",
        "Slice_0578",
        "Expose read-only supervised process evidence to AG operators.",
    ),
    PlannedSlice(
        "ag_postgres_smoke",
        "Slice_0579",
        "Prove AG read-only projection against AE test DB evidence.",
    ),
    PlannedSlice(
        "closure_checkpoint",
        "Slice_0580",
        "Close S58 with a quality-gate checkpoint.",
    ),
)


def run_ae_supervised_daemon_process_boundary_audit(
    environ: Mapping[str, str] | None = None,
    *,
    root_dir: Path = ROOT,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    paths = _path_results(root_dir)
    tokens = _token_results(root_dir)
    token_groups = _grouped_token_status(tokens)
    issues = _issues(paths=paths, tokens=tokens)
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "s57_closed_baseline_present": token_groups.get("s57_closed_baseline", False),
        "supervisor_contract_present": token_groups.get("supervisor_contract", False),
        "process_guardrails_present": token_groups.get("process_guardrails", False),
        "bounded_runtime_present": token_groups.get("bounded_runtime", False),
        "ae_api_surface_present": token_groups.get("ae_api_surface", False),
        "ag_operator_boundary_present": token_groups.get("ag_operator_boundary", False),
        "quality_docs_present": token_groups.get("quality_docs", False),
        "default_process_disabled": True,
        "start_stays_blocked_until_adapter": True,
        "test_profile_required": True,
        "explicit_opt_in_required": True,
        "bounded_max_cycles_required": True,
        "process_lock_required_before_start": True,
        "pid_metadata_required_before_start": True,
        "graceful_stop_required_before_enablement": True,
        "ag_remains_read_only": True,
        "postgres_smoke_required_before_enablement": True,
        "redacted_evidence_only": True,
    }
    status = "PASS" if all(checks.values()) and not issues else "FAIL"
    evidence = {
        "audit_schema_version": SCHEMA_VERSION,
        "status": status,
        "failure_code": None
        if status == "PASS"
        else "ae_supervised_daemon_process_boundary_failed",
        "slice": "0571",
        "surface": S58_SURFACE,
        "supervised_process_boundary": _supervised_process_boundary(),
        "refactoring_checkpoint": _refactoring_checkpoint(),
        "checks": checks,
        "paths": paths,
        "source_tokens": tokens,
        "protected_env": _summarize_protected_env(env),
        "planned_slices": _planned_slices(),
        "next_slices": [item.planned_slice for item in PLANNED_SLICES],
        "issues": issues,
    }
    _assert_evidence_redacted(json.dumps(evidence, ensure_ascii=False), env)
    return evidence


def _path_results(root_dir: Path) -> list[dict[str, Any]]:
    return [
        {
            "name": item.name,
            "path": _relative_label(root_dir / item.path.relative_to(ROOT), root_dir),
            "purpose": item.purpose,
            "present": (root_dir / item.path.relative_to(ROOT)).is_file(),
        }
        for item in REQUIRED_PATHS
    ]


def _token_results(root_dir: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in REQUIRED_SOURCE_TOKENS:
        path = root_dir / item.path.relative_to(ROOT)
        results.append(
            {
                "group": item.group,
                "token_id": item.token_id,
                "path": _relative_label(path, root_dir),
                "purpose": item.purpose,
                "present": item.token in _read_text(path),
            }
        )
    return results


def _grouped_token_status(tokens: list[dict[str, Any]]) -> dict[str, bool]:
    groups = {str(item["group"]) for item in tokens}
    return {
        group: all(item["present"] for item in tokens if item["group"] == group)
        for group in sorted(groups)
    }


def _issues(
    *,
    paths: list[dict[str, Any]],
    tokens: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    issues.extend(
        {
            "category": "path_missing",
            "name": item["name"],
            "path": item["path"],
            "purpose": item["purpose"],
        }
        for item in paths
        if item["present"] is not True
    )
    issues.extend(
        {
            "category": "source_token_missing",
            "group": item["group"],
            "token_id": item["token_id"],
            "path": item["path"],
            "purpose": item["purpose"],
        }
        for item in tokens
        if item["present"] is not True
    )
    return issues


def _supervised_process_boundary() -> dict[str, Any]:
    return {
        "artifact_system_of_record": "nex-ae-api",
        "daemon_process_owner": "nex-ae-api",
        "supervisor_owner": "nex-ae-api",
        "operator_projection_owner": "nex-ag",
        "runtime_boundary": SUPERVISED_PROCESS_BOUNDARY,
        "default_process_mode": DEFAULT_PROCESS_MODE,
        "default_start_mode": DEFAULT_START_MODE,
        "first_process_mode": FIRST_PROCESS_MODE,
        "production_continuous_start_enabled": False,
        "test_profile_required": True,
        "explicit_opt_in_required": True,
        "bounded_max_cycles_required": True,
        "process_lock_required_before_start": True,
        "pid_metadata_required_before_start": True,
        "status_probe_required_before_start": True,
        "graceful_stop_required_before_runtime_enablement": True,
        "postgres_smoke_required_before_enablement": True,
        "retention_work_must_use_job_queue": True,
        "ag_direct_process_control_allowed": False,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
        "physical_delete_automation_enabled": False,
    }


def _refactoring_checkpoint() -> dict[str, bool]:
    return {
        "keep_subprocess_adapter_in_daemon_module": True,
        "keep_long_running_process_out_of_artifacts_module": True,
        "reuse_supervisor_command_result_contract": True,
        "reuse_cli_execute_command_for_bounded_runtime": True,
        "reuse_process_lock_run_metadata_and_shutdown_contracts": True,
        "keep_fake_dry_run_as_default_adapter": True,
        "do_not_run_daemon_as_jobqueue_worker_job": True,
        "keep_jobqueue_for_finite_retention_work": True,
        "metadata_only_ag_projection": True,
        "redacted_process_evidence_only": True,
    }


def _summarize_protected_env(env: Mapping[str, str]) -> dict[str, bool]:
    return {key: bool(env.get(key)) for key in PROTECTED_ENV_KEYS}


def _planned_slices() -> list[dict[str, Any]]:
    return [
        {
            "name": item.name,
            "planned_slice": item.planned_slice,
            "purpose": item.purpose,
            "blocking": False,
        }
        for item in PLANNED_SLICES
    ]


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _relative_label(path: Path, root_dir: Path = ROOT) -> str:
    try:
        return str(path.relative_to(root_dir))
    except ValueError:
        return path.name


def _assert_evidence_redacted(serialized: str, env: Mapping[str, str]) -> None:
    for key in PROTECTED_ENV_KEYS:
        value = env.get(key)
        if value and len(value) >= 8 and value in serialized:
            raise ValueError(f"{key} leaked into S58 boundary evidence.")
    sensitive_patterns = (
        re.compile(r"nuri1004", re.IGNORECASE),
        re.compile(r"ed6@c496em", re.IGNORECASE),
        re.compile(r"postgresql(?:\+\w+)?://[^\"'\s]+", re.IGNORECASE),
        re.compile(r"/data/nex-platform", re.IGNORECASE),
    )
    if any(pattern.search(serialized) for pattern in sensitive_patterns):
        raise ValueError("Sensitive value leaked into S58 boundary evidence.")


def summary_line(evidence: Mapping[str, Any]) -> str:
    checks = evidence.get("checks")
    failing_checks = [
        key
        for key, passed in (checks.items() if isinstance(checks, Mapping) else [])
        if passed is not True
    ]
    suffix = (
        f"paths={_present_count(evidence.get('paths'))}/"
        f"{len(evidence.get('paths') or [])} "
        f"token_groups={_present_count(evidence.get('source_tokens'))}/"
        f"{len(evidence.get('source_tokens') or [])} "
        f"boundary={SUPERVISED_PROCESS_BOUNDARY} "
        f"process={DEFAULT_PROCESS_MODE} "
        f"next={NEXT_SLICE}"
    )
    if failing_checks:
        suffix += f" failing_checks={','.join(failing_checks)}"
    return (
        "ae_supervised_daemon_process_boundary_audit="
        f"{str(evidence.get('status')).lower()} {suffix}"
    )


def _present_count(items: Any) -> int:
    if not isinstance(items, list):
        return 0
    return sum(1 for item in items if isinstance(item, Mapping) and item.get("present"))


def write_audit_evidence(path: Path, evidence: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit the S58 AE supervised daemon process boundary."
    )
    parser.add_argument(
        "--summary", action="store_true", help="Print a short result line."
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path for the redacted audit evidence JSON.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence = run_ae_supervised_daemon_process_boundary_audit(os.environ)
    except ValueError as exc:
        evidence = {
            "audit_schema_version": SCHEMA_VERSION,
            "status": "FAIL",
            "failure_code": "ae_supervised_daemon_process_boundary_redaction_failed",
            "error": str(exc),
        }
    if args.output is not None:
        write_audit_evidence(args.output, evidence)
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2))
    return 0 if evidence.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
