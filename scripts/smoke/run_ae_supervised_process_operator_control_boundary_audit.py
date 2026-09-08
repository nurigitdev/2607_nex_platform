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
SCHEMA_VERSION = "ae_supervised_process_operator_control_boundary_audit.v1"

S59_SURFACE = "S59 AE supervised scheduler daemon operator control"
OPERATOR_CONTROL_BOUNDARY = "ae_owned_guarded_operator_control_test_profile_only"
DEFAULT_OPERATOR_CONTROL_MODE = "blocked_until_policy_contract"
FIRST_OPERATOR_CONTROL_MODE = "explicit_operator_test_profile_bounded_subprocess"
NEXT_SLICE = "Slice_0582"

PROTECTED_ENV_KEYS = (
    "NEX_AE_DATABASE_URL",
    "NEX_AE_TEST_DATABASE_URL",
    "NEX_AE_SUPERVISED_PROCESS_OPERATOR_CONTROL_SMOKE",
    "NEX_AE_SCHEDULER_DAEMON_ENABLE_SUPERVISED_PROCESS",
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
S58_CLOSURE = (
    ROOT
    / "scripts"
    / "smoke"
    / "run_s58_ae_scheduler_daemon_supervised_process_activation_closure.py"
)
S58_CLOSURE_DOC = (
    ROOT
    / "docs"
    / "slices"
    / "0580_s58_ae_scheduler_daemon_supervised_process_activation_closure.md"
)
S59_AUDIT = (
    ROOT
    / "scripts"
    / "smoke"
    / "run_ae_supervised_process_operator_control_boundary_audit.py"
)
S59_AUDIT_TEST = (
    ROOT
    / "tests"
    / "test_ae_supervised_process_operator_control_boundary_audit.py"
)
S59_AUDIT_DOC = (
    ROOT
    / "docs"
    / "slices"
    / "0581_ae_supervised_process_operator_control_boundary_audit.md"
)

REQUIRED_PATHS = (
    RequiredPath("ae_daemon_runtime", AE_DAEMON, "AE daemon runtime and supervisor module."),
    RequiredPath("ae_artifacts_routes", AE_ARTIFACTS, "AE artifact retention control routes."),
    RequiredPath("ag_artifact_operations", AG_ARTIFACT_OPERATIONS, "AG read-only operator surface."),
    RequiredPath("daemon_cli_script", DAEMON_SCRIPT, "Bounded AE daemon CLI entrypoint."),
    RequiredPath("s58_closure", S58_CLOSURE, "Closed S58 supervised process baseline."),
    RequiredPath("s58_closure_doc", S58_CLOSURE_DOC, "Closed S58 slice note."),
    RequiredPath("s59_audit", S59_AUDIT, "S59 operator-control boundary audit."),
    RequiredPath("s59_audit_test", S59_AUDIT_TEST, "S59 boundary regression tests."),
    RequiredPath("s59_audit_doc", S59_AUDIT_DOC, "S59 Slice 0581 note."),
    RequiredPath("quality_gate", QUALITY_GATE, "Default regression gate."),
    RequiredPath("docs_index", DOCS_INDEX, "Slice index."),
    RequiredPath("ae_readme", AE_README, "AE service implementation notes."),
    RequiredPath("ag_readme", AG_README, "AG service implementation notes."),
)

REQUIRED_SOURCE_TOKENS = (
    TokenRequirement(
        "s58_closed_baseline",
        S58_CLOSURE,
        "s58_closure_schema",
        "s58_ae_scheduler_daemon_supervised_process_activation_closure.v1",
        "S59 starts after S58 supervised process closure.",
    ),
    TokenRequirement(
        "s58_closed_baseline",
        S58_CLOSURE_DOC,
        "s58_next_operator_control",
        "controlled operator-facing activation, restart, or runtime policy work",
        "S58 explicitly points to guarded operator-control work.",
    ),
    TokenRequirement(
        "ae_supervisor_surface",
        AE_DAEMON,
        "supervisor_command_schema",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_COMMAND_SCHEMA_VERSION",
        "Operator control must reuse AE supervisor commands.",
    ),
    TokenRequirement(
        "ae_supervisor_surface",
        AE_DAEMON,
        "supervisor_result_schema",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_RESULT_SCHEMA_VERSION",
        "Operator control must persist AE supervisor results.",
    ),
    TokenRequirement(
        "ae_supervisor_surface",
        AE_DAEMON,
        "supervisor_actions",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_ACTIONS",
        "Allowed process actions stay schema-bound.",
    ),
    TokenRequirement(
        "ae_supervised_process_surface",
        AE_DAEMON,
        "supervised_process_schema",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_SCHEMA_VERSION",
        "Operator control must emit supervised process evidence.",
    ),
    TokenRequirement(
        "ae_supervised_process_surface",
        AE_DAEMON,
        "supervised_process_store",
        "SqlAlchemyArtifactRetentionSchedulerDaemonSupervisedProcessStore",
        "Process evidence remains AE-owned and persistent.",
    ),
    TokenRequirement(
        "ae_guardrails",
        AE_DAEMON,
        "test_profile_required",
        "profile must be test.",
        "Real subprocess execution remains test-profile only.",
    ),
    TokenRequirement(
        "ae_guardrails",
        AE_DAEMON,
        "explicit_opt_in_required",
        '"execution_requires_explicit_opt_in": True',
        "Operator control requires explicit opt-in.",
    ),
    TokenRequirement(
        "ae_guardrails",
        AE_DAEMON,
        "bounded_max_cycles",
        "MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_MAX_CYCLES",
        "Operator-started subprocess execution remains bounded.",
    ),
    TokenRequirement(
        "ae_guardrails",
        AE_DAEMON,
        "process_lock_contract",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_PROCESS_LOCK_SCHEMA_VERSION",
        "Start admission must be lock-aware.",
    ),
    TokenRequirement(
        "ae_guardrails",
        AE_DAEMON,
        "shutdown_signal_adapter",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SIGNAL_SHUTDOWN_ADAPTER_SCHEMA_VERSION",
        "Stop admission must use the shutdown boundary.",
    ),
    TokenRequirement(
        "ae_api_surface",
        AE_ARTIFACTS,
        "supervisor_control_route",
        '"/api/v1/artifact-retention/scheduler-daemon-supervisor-controls"',
        "Existing AE supervisor route remains the internal control primitive.",
    ),
    TokenRequirement(
        "ae_api_surface",
        AE_ARTIFACTS,
        "supervised_process_snapshot_route",
        '"/api/v1/artifact-retention/scheduler-daemon-process-snapshots"',
        "Operator control must keep process readback metadata-only.",
    ),
    TokenRequirement(
        "ag_operator_boundary",
        AG_ARTIFACT_OPERATIONS,
        "ag_dispatch_route",
        '"/admin/v1/operations/artifact-retention/scheduler-daemon/manual-tick-once"',
        "AG already owns operator-facing dispatch patterns.",
    ),
    TokenRequirement(
        "ag_operator_boundary",
        AG_ARTIFACT_OPERATIONS,
        "ag_direct_process_control_disallowed",
        '"ag_direct_daemon_process_control_allowed": False',
        "AG must not directly control AE subprocesses.",
    ),
    TokenRequirement(
        "ag_operator_boundary",
        AG_ARTIFACT_OPERATIONS,
        "ag_direct_database_write_disallowed",
        '"ag_direct_database_write_allowed": False',
        "AG must not write AE persistence.",
    ),
    TokenRequirement(
        "quality_docs",
        QUALITY_GATE,
        "s59_audit_quality_gate_hook",
        "run_ae_supervised_process_operator_control_boundary_audit.py",
        "Slice 0581 audit must run in the default quality gate.",
    ),
    TokenRequirement(
        "quality_docs",
        DOCS_INDEX,
        "s59_doc_indexed",
        "0581_ae_supervised_process_operator_control_boundary_audit.md",
        "Slice 0581 must be indexed.",
    ),
    TokenRequirement(
        "quality_docs",
        AE_README,
        "ae_s59_readme_note",
        "Slice 0581 starts S59",
        "AE notes must record the operator-control boundary.",
    ),
    TokenRequirement(
        "quality_docs",
        AG_README,
        "ag_s59_readme_note",
        "Slice 0581 starts S59",
        "AG notes must record the operator-control boundary.",
    ),
)

PLANNED_SLICES = (
    PlannedSlice(
        "control_policy_contract_schema",
        "Slice_0582",
        "Define operator action, subject, idempotency, reason, approval, and profile policy.",
    ),
    PlannedSlice(
        "admission_decision_state_machine",
        "Slice_0583",
        "Decide start, stop, restart, and status_probe from policy and process state.",
    ),
    PlannedSlice(
        "ae_guarded_operator_control_api",
        "Slice_0584",
        "Expose AE-owned guarded operator control without production enablement.",
    ),
    PlannedSlice(
        "execution_adapter_hardening",
        "Slice_0585",
        "Bind allowed controls to protected test-profile bounded subprocess execution.",
    ),
    PlannedSlice(
        "ae_postgres_smoke",
        "Slice_0586",
        "Prove AE operator-control read/write evidence against the real AE test DB.",
    ),
    PlannedSlice(
        "ag_projection",
        "Slice_0587",
        "Project AE control admission and result state into AG as read-only metadata.",
    ),
    PlannedSlice(
        "ag_dispatch_route",
        "Slice_0588",
        "Let AG request AE guarded control while keeping AE as process owner.",
    ),
    PlannedSlice(
        "ag_to_ae_postgres_smoke",
        "Slice_0589",
        "Prove AG-to-AE operator-control evidence against real test DBs.",
    ),
    PlannedSlice(
        "closure_checkpoint",
        "Slice_0590",
        "Close S59 with quality-gate and redaction checks.",
    ),
)


def run_ae_supervised_process_operator_control_boundary_audit(
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
        "s58_closed_baseline_present": token_groups.get("s58_closed_baseline", False),
        "ae_supervisor_surface_present": token_groups.get("ae_supervisor_surface", False),
        "ae_supervised_process_surface_present": token_groups.get(
            "ae_supervised_process_surface", False
        ),
        "ae_guardrails_present": token_groups.get("ae_guardrails", False),
        "ae_api_surface_present": token_groups.get("ae_api_surface", False),
        "ag_operator_boundary_present": token_groups.get("ag_operator_boundary", False),
        "quality_docs_present": token_groups.get("quality_docs", False),
        "operator_subject_required": True,
        "idempotency_required": True,
        "operator_reason_required": True,
        "restart_decomposes_to_stop_then_start": True,
        "test_profile_required": True,
        "bounded_execution_required": True,
        "status_probe_before_mutation_required": True,
        "postgres_smoke_required_before_enablement": True,
        "production_enablement_blocked": True,
        "ag_remains_read_only_dispatcher": True,
        "redacted_evidence_only": True,
    }
    status = "PASS" if all(checks.values()) and not issues else "FAIL"
    evidence = {
        "audit_schema_version": SCHEMA_VERSION,
        "status": status,
        "failure_code": None
        if status == "PASS"
        else "ae_supervised_process_operator_control_boundary_failed",
        "slice": "0581",
        "surface": S59_SURFACE,
        "operator_control_boundary": _operator_control_boundary(),
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


def _operator_control_boundary() -> dict[str, Any]:
    return {
        "artifact_system_of_record": "nex-ae-api",
        "daemon_process_owner": "nex-ae-api",
        "operator_projection_owner": "nex-ag",
        "operator_dispatch_owner": "nex-ag",
        "runtime_boundary": OPERATOR_CONTROL_BOUNDARY,
        "default_operator_control_mode": DEFAULT_OPERATOR_CONTROL_MODE,
        "first_operator_control_mode": FIRST_OPERATOR_CONTROL_MODE,
        "supported_operator_actions": ["status_probe", "start_daemon", "stop_daemon", "restart_daemon"],
        "restart_semantics": "stop_then_start_with_distinct_evidence",
        "operator_subject_required": True,
        "idempotency_key_required": True,
        "operator_reason_required": True,
        "operator_approval_required_for_start_restart": True,
        "test_profile_required": True,
        "explicit_opt_in_required": True,
        "bounded_max_cycles_required": True,
        "status_probe_required_before_mutation": True,
        "process_lock_required_before_start": True,
        "pid_metadata_required_before_stop": True,
        "postgres_smoke_required_before_enablement": True,
        "production_continuous_start_enabled": False,
        "ag_direct_process_control_allowed": False,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
        "physical_delete_automation_enabled": False,
    }


def _refactoring_checkpoint() -> dict[str, bool]:
    return {
        "keep_policy_contract_in_daemon_module": True,
        "keep_route_validation_in_artifacts_module": True,
        "keep_execution_adapter_in_daemon_module": True,
        "reuse_supervisor_command_result_contract": True,
        "reuse_supervised_process_snapshot_store": True,
        "reuse_bounded_cli_entrypoint_for_start": True,
        "reuse_shutdown_signal_boundary_for_stop": True,
        "keep_ag_as_read_only_operator_dispatcher": True,
        "do_not_use_jobqueue_for_long_running_daemon_process": True,
        "keep_jobqueue_for_finite_retention_work": True,
        "metadata_only_operator_evidence": True,
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
            raise ValueError(f"{key} leaked into S59 boundary evidence.")
    sensitive_patterns = (
        re.compile(r"nuri1004", re.IGNORECASE),
        re.compile(r"ed6@c496em", re.IGNORECASE),
        re.compile(r"postgresql(?:\+\w+)?://[^\"'\s]+", re.IGNORECASE),
        re.compile(r"/data/nex-platform", re.IGNORECASE),
    )
    if any(pattern.search(serialized) for pattern in sensitive_patterns):
        raise ValueError("Sensitive value leaked into S59 boundary evidence.")


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
        f"boundary={OPERATOR_CONTROL_BOUNDARY} "
        f"control={DEFAULT_OPERATOR_CONTROL_MODE} "
        f"next={NEXT_SLICE}"
    )
    if failing_checks:
        suffix += f" failing_checks={','.join(failing_checks)}"
    return (
        "ae_supervised_process_operator_control_boundary_audit="
        f"{str(evidence.get('status')).lower()} {suffix}"
    )


def _present_count(items: Any) -> int:
    if not isinstance(items, list):
        return 0
    return sum(1 for item in items if isinstance(item, Mapping) and item.get("present"))


def write_audit_evidence(path: Path, evidence: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit the S59 AE supervised process operator-control boundary."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path for the redacted audit evidence JSON.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence = run_ae_supervised_process_operator_control_boundary_audit(os.environ)
    except ValueError as exc:
        evidence = {
            "audit_schema_version": SCHEMA_VERSION,
            "status": "FAIL",
            "failure_code": "ae_supervised_process_operator_control_boundary_redaction_failed",
            "error": str(exc),
        }
    if args.output is not None:
        write_audit_evidence(args.output, evidence)
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2))
    return 0 if evidence.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
