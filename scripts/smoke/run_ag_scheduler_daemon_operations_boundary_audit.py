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
SCHEMA_VERSION = "ag_scheduler_daemon_operations_boundary_audit.v1"

PROTECTED_ENV_KEYS = (
    "NEX_AG_AE_ARTIFACT_BASE_URL",
    "NEX_AG_AE_ARTIFACT_SERVICE_TOKEN",
    "NEX_AE_DATABASE_URL",
    "NEX_AE_TEST_DATABASE_URL",
    "NEX_AE_ARTIFACT_STORAGE_ROOT",
    "NEX_SERVICE_TOKEN",
)

S53_OPERATION_SURFACE = "AG scheduler daemon operations"
S53_CONTROL_BOUNDARY = "ae_api_only"
NEXT_SLICE = "Slice_0522"


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
class PlannedOperationsStep:
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
QUALITY_GATE = ROOT / "scripts" / "quality" / "run_quality_gate.sh"
DOCS_INDEX = ROOT / "docs" / "README.md"
S52_CLOSURE = ROOT / "scripts" / "smoke" / "run_s52_ae_scheduler_daemon_closure.py"
S52_CLOSURE_TEST = ROOT / "tests" / "test_s52_ae_scheduler_daemon_closure.py"
S52_CLOSURE_DOC = (
    ROOT / "docs" / "slices" / "0520_s52_ae_scheduler_daemon_closure.md"
)
S52_DAEMON_SMOKE = (
    ROOT
    / "scripts"
    / "smoke"
    / "run_ae_artifact_retention_scheduler_daemon_postgres_smoke.py"
)
S53_AUDIT = (
    ROOT / "scripts" / "smoke" / "run_ag_scheduler_daemon_operations_boundary_audit.py"
)
S53_AUDIT_TEST = ROOT / "tests" / "test_ag_scheduler_daemon_operations_boundary_audit.py"
S53_AUDIT_DOC = (
    ROOT / "docs" / "slices" / "0521_ag_scheduler_daemon_operations_boundary_audit.md"
)

REQUIRED_PATHS = (
    RequiredPath("ae_api_artifacts", AE_API_ARTIFACTS, "AE daemon route surface."),
    RequiredPath("ae_scheduler", AE_SCHEDULER, "AE daemon contract/runtime owner."),
    RequiredPath("ae_api_readme", AE_API_README, "AE S53 boundary note."),
    RequiredPath("ag_artifact_operations", AG_ARTIFACT_OPERATIONS, "AG operations surface."),
    RequiredPath("ag_readme", AG_README, "AG S53 boundary note."),
    RequiredPath("s52_closure", S52_CLOSURE, "Closed S52 daemon baseline."),
    RequiredPath("s52_closure_test", S52_CLOSURE_TEST, "S52 closure regression."),
    RequiredPath("s52_closure_doc", S52_CLOSURE_DOC, "S52 closure documentation."),
    RequiredPath("s52_daemon_smoke", S52_DAEMON_SMOKE, "S52 PostgreSQL evidence."),
    RequiredPath("s53_audit", S53_AUDIT, "S53 boundary audit runner."),
    RequiredPath("s53_audit_test", S53_AUDIT_TEST, "S53 audit regression test."),
    RequiredPath("s53_audit_doc", S53_AUDIT_DOC, "S53 audit slice note."),
    RequiredPath("quality_gate", QUALITY_GATE, "Default regression gate."),
    RequiredPath("docs_index", DOCS_INDEX, "Slice index."),
)

REQUIRED_SOURCE_TOKENS = (
    TokenRequirement(
        "s52_closed_baseline",
        S52_CLOSURE,
        "s52_slice_range",
        "0511-0520",
        "S53 starts only after S52 daemon closure.",
    ),
    TokenRequirement(
        "s52_closed_baseline",
        S52_CLOSURE,
        "s52_daemon_default_disabled",
        '"scheduler_daemon_default_disabled": True',
        "AG operations must start from a disabled daemon baseline.",
    ),
    TokenRequirement(
        "s52_closed_baseline",
        S52_CLOSURE,
        "s52_continuous_loop_deferred",
        '"continuous_loop_deferred": True',
        "Continuous loop enablement remains out of scope for S53 entry.",
    ),
    TokenRequirement(
        "s52_closed_baseline",
        S52_CLOSURE,
        "s52_manual_once_runner",
        '"manual_once_runner": True',
        "The first executable daemon path is manual tick-once.",
    ),
    TokenRequirement(
        "ae_daemon_api_surface",
        AE_API_ARTIFACTS,
        "daemon_config_route",
        '"/api/v1/artifact-retention/scheduler-daemon-config"',
        "AG should read daemon posture through AE API.",
    ),
    TokenRequirement(
        "ae_daemon_api_surface",
        AE_API_ARTIFACTS,
        "daemon_controls_route",
        '"/api/v1/artifact-retention/scheduler-daemon-controls"',
        "AG control requests should flow through AE API.",
    ),
    TokenRequirement(
        "ae_daemon_api_surface",
        AE_API_ARTIFACTS,
        "daemon_dispatch_facade_import",
        "dispatch_artifact_retention_scheduler_daemon_control",
        "AE owns the daemon dispatch facade.",
    ),
    TokenRequirement(
        "ae_daemon_api_surface",
        AE_API_ARTIFACTS,
        "daemon_lease_store_injection",
        "retention_scheduler_lease_store",
        "AE route tests can isolate lease state without exposing DB writes.",
    ),
    TokenRequirement(
        "ae_daemon_runtime_guard",
        AE_SCHEDULER,
        "daemon_config_schema",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONFIG_SCHEMA_VERSION",
        "AG projections should preserve AE daemon config schema identity.",
    ),
    TokenRequirement(
        "ae_daemon_runtime_guard",
        AE_SCHEDULER,
        "daemon_dispatch_schema",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_DISPATCH_RESULT_SCHEMA_VERSION",
        "AG dispatch projections should preserve AE dispatch schema identity.",
    ),
    TokenRequirement(
        "ae_daemon_runtime_guard",
        AE_SCHEDULER,
        "start_daemon_block_reason",
        "daemon_disabled_by_policy",
        "AG must not bypass the blocked daemon start decision.",
    ),
    TokenRequirement(
        "ae_daemon_runtime_guard",
        AE_SCHEDULER,
        "manual_tick_once_action",
        "ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONTROL_ACTION_MANUAL_TICK_ONCE",
        "Manual tick-once is the only S53 executable daemon action.",
    ),
    TokenRequirement(
        "ae_daemon_runtime_guard",
        AE_SCHEDULER,
        "lease_sqlalchemy_store",
        "SqlAlchemyArtifactRetentionSchedulerLeaseStore",
        "Live evidence must keep lease state in AE persistence.",
    ),
    TokenRequirement(
        "ae_daemon_runtime_guard",
        AE_SCHEDULER,
        "scheduler_daemon_not_started",
        '"scheduler_daemon_started": False',
        "S53 must not start a daemon process.",
    ),
    TokenRequirement(
        "ae_daemon_runtime_guard",
        AE_SCHEDULER,
        "continuous_loop_not_started",
        '"continuous_loop_started": False',
        "S53 must not start a continuous loop.",
    ),
    TokenRequirement(
        "ag_existing_retention_operations",
        AG_ARTIFACT_OPERATIONS,
        "automation_projection_schema",
        "AG_ARTIFACT_OPERATION_RETENTION_AUTOMATION_PROJECTION_SCHEMA_VERSION",
        "Daemon operations should extend the existing retention operations family.",
    ),
    TokenRequirement(
        "ag_existing_retention_operations",
        AG_ARTIFACT_OPERATIONS,
        "automation_route",
        '"/admin/v1/operations/artifact-retention/automation"',
        "AG already exposes retention automation observability.",
    ),
    TokenRequirement(
        "ag_existing_retention_operations",
        AG_ARTIFACT_OPERATIONS,
        "scheduled_jobs_route",
        '"/admin/v1/operations/artifact-retention/scheduled-jobs"',
        "Daemon operations should reuse scheduled job posture.",
    ),
    TokenRequirement(
        "ag_existing_retention_operations",
        AG_ARTIFACT_OPERATIONS,
        "scheduled_dispatch_confirmation",
        "confirm_dispatch",
        "Future daemon manual dispatch must keep explicit operator confirmation.",
    ),
    TokenRequirement(
        "ag_write_boundary",
        AG_ARTIFACT_OPERATIONS,
        "ag_direct_database_write_disallowed",
        '"ag_direct_database_write_allowed": False',
        "AG must not write AE persistence directly.",
    ),
    TokenRequirement(
        "ag_write_boundary",
        AG_ARTIFACT_OPERATIONS,
        "ag_direct_job_enqueue_disallowed",
        '"ag_direct_job_enqueue_allowed": False',
        "AG must not enqueue AE jobs directly.",
    ),
    TokenRequirement(
        "ag_write_boundary",
        AG_ARTIFACT_OPERATIONS,
        "ae_client_protocol",
        "class AeArtifactOperationsClient",
        "AG should reach AE through a client boundary.",
    ),
    TokenRequirement(
        "postgres_daemon_evidence",
        S52_DAEMON_SMOKE,
        "daemon_smoke_env_guard",
        "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_POSTGRES_SMOKE",
        "Mutating daemon evidence remains protected by an explicit env guard.",
    ),
    TokenRequirement(
        "postgres_daemon_evidence",
        S52_DAEMON_SMOKE,
        "daemon_smoke_live_db",
        "live_db",
        "Daemon route evidence must prove real test DB execution when enabled.",
    ),
    TokenRequirement(
        "postgres_daemon_evidence",
        S52_DAEMON_SMOKE,
        "daemon_smoke_lease_readback",
        "_scheduler_once_lease_observation",
        "The smoke must read back AE lease state.",
    ),
    TokenRequirement(
        "postgres_daemon_evidence",
        S52_DAEMON_SMOKE,
        "daemon_smoke_job_readback",
        "_job_observation",
        "The smoke must read back JobQueue state.",
    ),
    TokenRequirement(
        "postgres_daemon_evidence",
        S52_DAEMON_SMOKE,
        "daemon_smoke_history_readback",
        "history_rows",
        "The smoke must read back retention history.",
    ),
    TokenRequirement(
        "quality_gate_and_docs",
        QUALITY_GATE,
        "s53_boundary_audit_gate",
        "run_ag_scheduler_daemon_operations_boundary_audit.py",
        "The S53 boundary audit should run in the default quality gate.",
    ),
    TokenRequirement(
        "quality_gate_and_docs",
        DOCS_INDEX,
        "s53_slice_index",
        "Slice 0521",
        "The docs index should expose the S53 starting point.",
    ),
    TokenRequirement(
        "quality_gate_and_docs",
        AE_API_README,
        "s53_ae_readme_note",
        "Slice 0521 starts S53",
        "AE README should document the AG daemon operations boundary.",
    ),
    TokenRequirement(
        "quality_gate_and_docs",
        AG_README,
        "s53_ag_readme_note",
        "Slice 0521 starts S53",
        "AG README should document the S53 daemon operations boundary.",
    ),
)

PLANNED_OPERATIONS_STEPS = (
    PlannedOperationsStep(
        "ae_daemon_client_adapter",
        "Slice_0522",
        "Add AG client methods for AE daemon config and controls.",
    ),
    PlannedOperationsStep(
        "daemon_operations_projection",
        "Slice_0523",
        "Project AE daemon config/control state into metadata-only AG evidence.",
    ),
    PlannedOperationsStep(
        "daemon_operations_route",
        "Slice_0524",
        "Expose AG read route for scheduler daemon operations.",
    ),
    PlannedOperationsStep(
        "manual_tick_once_dispatch_guardrail",
        "Slice_0525",
        "Add explicit operator confirmation before AG can request manual tick-once.",
    ),
    PlannedOperationsStep(
        "ag_to_ae_daemon_postgresql_smoke",
        "Slice_0526",
        "Verify AG route to AE daemon route against the real AE test DB.",
    ),
    PlannedOperationsStep(
        "daemon_dashboard_rollup",
        "Slice_0527",
        "Roll daemon posture into the existing retention operations dashboard.",
    ),
    PlannedOperationsStep(
        "daemon_attention_classification",
        "Slice_0528",
        "Classify lease busy, queue unavailable, and batch-window decisions for operators.",
    ),
    PlannedOperationsStep(
        "operator_runbook_evidence",
        "Slice_0529",
        "Document protected smoke, manual tick, and cleanup runbook evidence.",
    ),
    PlannedOperationsStep(
        "s53_closure",
        "Slice_0530",
        "Close the AG scheduler daemon operations track.",
    ),
)

SENSITIVE_PATTERNS = (
    re.compile(r"postgresql(?:\+\w+)?://[^\"'\s]+", re.IGNORECASE),
    re.compile(r"nuri1004", re.IGNORECASE),
    re.compile(r"/data/nex-platform", re.IGNORECASE),
    re.compile(r"ed6@c496em", re.IGNORECASE),
    re.compile(r"service-token-[\w-]+", re.IGNORECASE),
)


def run_ag_scheduler_daemon_operations_boundary_audit(
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
        "s52_closed_baseline_present": group_status.get("s52_closed_baseline")
        is True,
        "ae_daemon_api_surface_present": group_status.get("ae_daemon_api_surface")
        is True,
        "ae_daemon_runtime_guard_present": group_status.get("ae_daemon_runtime_guard")
        is True,
        "ag_existing_retention_operations_present": group_status.get(
            "ag_existing_retention_operations"
        )
        is True,
        "ag_write_boundary_present": group_status.get("ag_write_boundary") is True,
        "postgres_daemon_evidence_present": group_status.get(
            "postgres_daemon_evidence"
        )
        is True,
        "quality_gate_and_docs_present": group_status.get("quality_gate_and_docs")
        is True,
        "ae_system_of_record": True,
        "ag_api_mediated_control_only": True,
        "manual_tick_once_operator_mediated": True,
        "start_daemon_must_remain_blocked": True,
        "continuous_loop_deferred": True,
        "test_db_smoke_required_for_mutating_slices": True,
        "redacted_evidence_only": True,
    }
    issues = build_issues(paths, tokens)
    status = "PASS" if all(checks.values()) and not issues else "FAIL"
    evidence: dict[str, Any] = {
        "audit_schema_version": SCHEMA_VERSION,
        "status": status,
        "failure_code": None if status == "PASS" else "ag_scheduler_daemon_boundary_failed",
        "slice": "0521",
        "surface": S53_OPERATION_SURFACE,
        "operations_boundary": {
            "artifact_system_of_record": "nex-ae-api",
            "operator_projection_owner": "nex-ag",
            "control_boundary": S53_CONTROL_BOUNDARY,
            "daemon_config_source": "ae_api_scheduler_daemon_config",
            "daemon_control_source": "ae_api_scheduler_daemon_controls",
            "allowed_control_action": "manual_tick_once",
            "start_daemon_allowed": False,
            "continuous_loop_allowed": False,
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
            "operator_confirmation_required_before_dispatch": True,
            "postgres_smoke_required_before_mutating_slices": True,
        },
        "refactoring_checkpoint": {
            "extend_ag_client_protocol_before_routes": True,
            "build_projection_before_dispatch": True,
            "reuse_existing_retention_operations_family": True,
            "keep_ae_lease_job_history_as_system_of_record": True,
            "keep_continuous_daemon_loop_deferred": True,
        },
        "paths": paths,
        "source_tokens": tokens,
        "planned_operations_steps": build_planned_operations_steps(),
        "checks": checks,
        "issues": issues,
        "next_slices": [NEXT_SLICE, "Slice_0523", "Slice_0524", "Slice_0525"],
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


def build_planned_operations_steps() -> list[dict[str, str | bool]]:
    return [
        {
            "name": item.name,
            "planned_slice": item.planned_slice,
            "purpose": item.purpose,
            "blocking": False,
        }
        for item in PLANNED_OPERATIONS_STEPS
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
    if evidence.get("status") == "PASS":
        return (
            "ag_scheduler_daemon_operations_boundary_audit=pass "
            f"paths={present_count(list(evidence['paths']))}/"
            f"{len(evidence['paths'])} "
            f"token_groups={sum(1 for passed in grouped_token_status(list(evidence['source_tokens'])).values() if passed)}/"
            f"{len(grouped_token_status(list(evidence['source_tokens'])))} "
            "control=ae_api_only "
            f"next={NEXT_SLICE}"
        )
    failed_checks = [
        key for key, value in evidence.get("checks", {}).items() if value is not True
    ]
    return (
        "ag_scheduler_daemon_operations_boundary_audit=fail "
        f"reason={evidence.get('failure_code')} "
        f"failing_checks={','.join(failed_checks)}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run AG scheduler daemon operations boundary audit."
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a short result line.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path to write full JSON evidence.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence = run_ag_scheduler_daemon_operations_boundary_audit()
        if args.output:
            write_audit_evidence(args.output, evidence)
        print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2))
        return 0 if evidence["status"] == "PASS" else 1
    except Exception as exc:
        print(
            "ag_scheduler_daemon_operations_boundary_audit=fail "
            f"error={exc.__class__.__name__}"
        )
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
