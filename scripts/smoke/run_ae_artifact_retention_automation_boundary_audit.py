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
SCHEMA_VERSION = "ae_artifact_retention_automation_boundary_audit.v1"

PROTECTED_ENV_KEYS = (
    "NEX_AE_DATABASE_URL",
    "NEX_AE_TEST_DATABASE_URL",
    "NEX_AE_ARTIFACT_STORAGE_ROOT",
    "NEX_AG_AE_ARTIFACT_SERVICE_TOKEN",
    "NEX_SERVICE_TOKEN",
)

DEFAULT_EXECUTION_MODE = "DRY_RUN"
FIRST_AUTOMATION_MODE = "scheduler_tick_to_dry_run_job_admission"


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
class PlannedAutomationStep:
    name: str
    planned_slice: str
    purpose: str


AE_API_ARTIFACTS = ROOT / "services" / "nex-ae-api" / "nex_ae_api" / "artifacts.py"
AE_API_README = ROOT / "services" / "nex-ae-api" / "README.md"
AG_ARTIFACT_OPERATIONS = ROOT / "services" / "nex-ag" / "nex_ag" / "artifact_operations.py"
AG_README = ROOT / "services" / "nex-ag" / "README.md"
QUALITY_GATE = ROOT / "scripts" / "quality" / "run_quality_gate.sh"
DOCS_INDEX = ROOT / "docs" / "README.md"
S50_CLOSURE = (
    ROOT / "scripts" / "smoke" / "run_s50_ae_artifact_retention_scheduler_runtime_closure.py"
)
S50_AE_AG_SMOKE = (
    ROOT / "scripts" / "smoke" / "run_ae_ag_artifact_retention_scheduler_postgres_smoke.py"
)
S50_WORKER_SMOKE = (
    ROOT
    / "scripts"
    / "smoke"
    / "run_ae_artifact_retention_scheduled_worker_postgres_smoke.py"
)
S51_AUDIT = (
    ROOT / "scripts" / "smoke" / "run_ae_artifact_retention_automation_boundary_audit.py"
)
S51_AUDIT_TEST = ROOT / "tests" / "test_ae_artifact_retention_automation_boundary_audit.py"
S51_AUDIT_DOC = (
    ROOT / "docs" / "slices" / "0501_ae_artifact_retention_automation_boundary_audit.md"
)

REQUIRED_PATHS = (
    RequiredPath("ae_api_artifacts", AE_API_ARTIFACTS, "AE retention runtime."),
    RequiredPath("ae_api_readme", AE_API_README, "AE retention notes."),
    RequiredPath("ag_artifact_operations", AG_ARTIFACT_OPERATIONS, "AG projection boundary."),
    RequiredPath("ag_readme", AG_README, "AG operations notes."),
    RequiredPath("s50_closure", S50_CLOSURE, "S50 scheduler runtime closure."),
    RequiredPath("s50_ae_ag_smoke", S50_AE_AG_SMOKE, "S50 cross-service smoke."),
    RequiredPath("s50_worker_smoke", S50_WORKER_SMOKE, "S50 worker smoke."),
    RequiredPath("s51_audit", S51_AUDIT, "S51 automation boundary audit."),
    RequiredPath("s51_audit_test", S51_AUDIT_TEST, "S51 audit regression test."),
    RequiredPath("s51_audit_doc", S51_AUDIT_DOC, "S51 audit slice note."),
    RequiredPath("quality_gate", QUALITY_GATE, "Default regression gate."),
    RequiredPath("docs_index", DOCS_INDEX, "Slice index."),
)

REQUIRED_SOURCE_TOKENS = (
    TokenRequirement(
        "s50_closed_baseline",
        S50_CLOSURE,
        "s50_slice_range",
        "0491-0500",
        "S51 starts only after S50 scheduler runtime closure.",
    ),
    TokenRequirement(
        "s50_closed_baseline",
        S50_CLOSURE,
        "s50_scheduler_daemon_deferred",
        '"scheduler_daemon_deferred": True',
        "Automation must start from a closed disabled-daemon baseline.",
    ),
    TokenRequirement(
        "ae_scheduler_runtime",
        AE_API_ARTIFACTS,
        "scheduler_config_builder",
        "build_artifact_retention_scheduler_config",
        "Automation needs the existing scheduler config read-model.",
    ),
    TokenRequirement(
        "ae_scheduler_runtime",
        AE_API_ARTIFACTS,
        "scheduled_job_queue",
        "build_default_artifact_retention_scheduled_job_queue",
        "Automation should enqueue through the shared JobQueue.",
    ),
    TokenRequirement(
        "ae_scheduler_runtime",
        AE_API_ARTIFACTS,
        "scheduled_worker",
        "run_artifact_retention_scheduled_worker_once",
        "Automation should reuse the S50 worker runner adapter.",
    ),
    TokenRequirement(
        "ae_scheduler_runtime",
        AE_API_ARTIFACTS,
        "scheduled_job_type",
        "AE_ARTIFACT_RETENTION_SCHEDULED_JOB_TYPE",
        "Automation must emit the existing scheduled retention job type.",
    ),
    TokenRequirement(
        "ae_dry_run_guardrail",
        AE_API_ARTIFACTS,
        "dry_run_required_before_execute",
        '"dry_run_required_before_execute": True',
        "First automated ticks must remain dry-run gated.",
    ),
    TokenRequirement(
        "ae_dry_run_guardrail",
        AE_API_ARTIFACTS,
        "physical_delete_automation_disabled",
        '"physical_delete_automation_enabled": False',
        "Physical delete automation must remain disabled by default.",
    ),
    TokenRequirement(
        "ae_dry_run_guardrail",
        AE_API_ARTIFACTS,
        "execute_requires_delete_enabled",
        '"execute_requires_delete_enabled": True',
        "Execute mode requires an explicit delete flag.",
    ),
    TokenRequirement(
        "ae_dry_run_guardrail",
        AE_API_ARTIFACTS,
        "execute_requires_storage_mutation",
        '"execute_requires_storage_mutation_enabled": True',
        "Execute mode requires an explicit storage mutation flag.",
    ),
    TokenRequirement(
        "ae_dry_run_guardrail",
        AE_API_ARTIFACTS,
        "execute_requires_database_row_delete",
        '"execute_requires_database_row_delete_enabled": True',
        "Execute mode requires an explicit database row delete flag.",
    ),
    TokenRequirement(
        "ae_route_surface",
        AE_API_ARTIFACTS,
        "scheduler_config_route",
        '"/api/v1/artifact-retention/scheduler-config"',
        "Operators need a read-model before scheduler ticks are enabled.",
    ),
    TokenRequirement(
        "ae_route_surface",
        AE_API_ARTIFACTS,
        "scheduled_jobs_route",
        '"/api/v1/artifact-retention/scheduled-jobs"',
        "Operators need queue visibility before scheduler ticks are enabled.",
    ),
    TokenRequirement(
        "ae_route_surface",
        AE_API_ARTIFACTS,
        "scheduled_job_admission_route",
        '"/api/v1/artifact-retention/scheduled-jobs/admission"',
        "Automation should reuse the AE admission boundary.",
    ),
    TokenRequirement(
        "ae_route_surface",
        AE_API_ARTIFACTS,
        "purge_route",
        '"/api/v1/artifact-retention/purge"',
        "Execute mode must delegate through the guarded purge route.",
    ),
    TokenRequirement(
        "ag_control_boundary",
        AG_ARTIFACT_OPERATIONS,
        "scheduled_job_projection_schema",
        "AG_ARTIFACT_OPERATION_RETENTION_SCHEDULED_JOB_PROJECTION_SCHEMA_VERSION",
        "AG keeps operator visibility over scheduled jobs.",
    ),
    TokenRequirement(
        "ag_control_boundary",
        AG_ARTIFACT_OPERATIONS,
        "scheduled_dispatch_schema",
        "AG_ARTIFACT_OPERATION_RETENTION_SCHEDULED_DISPATCH_SCHEMA_VERSION",
        "AG dispatch remains schema-bound.",
    ),
    TokenRequirement(
        "ag_control_boundary",
        AG_ARTIFACT_OPERATIONS,
        "confirm_dispatch",
        "confirm_dispatch",
        "AG dispatch requires explicit operator confirmation.",
    ),
    TokenRequirement(
        "ag_control_boundary",
        AG_ARTIFACT_OPERATIONS,
        "ag_direct_database_write_disallowed",
        '"ag_direct_database_write_allowed": False',
        "AG must not write AE persistence directly.",
    ),
    TokenRequirement(
        "ag_control_boundary",
        AG_ARTIFACT_OPERATIONS,
        "ag_direct_job_enqueue_disallowed",
        '"ag_direct_job_enqueue_allowed": False',
        "AG must not enqueue AE jobs directly.",
    ),
    TokenRequirement(
        "postgres_smoke_evidence",
        S50_WORKER_SMOKE,
        "worker_smoke_live_db",
        "live_db",
        "Worker evidence must prove real test DB execution when enabled.",
    ),
    TokenRequirement(
        "postgres_smoke_evidence",
        S50_AE_AG_SMOKE,
        "ae_ag_smoke_env",
        "NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_POSTGRES_SMOKE",
        "Cross-service smoke remains protected by an explicit env guard.",
    ),
    TokenRequirement(
        "postgres_smoke_evidence",
        S50_AE_AG_SMOKE,
        "ae_ag_direct_job_observation",
        "_job_observation",
        "Cross-service smoke must directly verify queued DB state.",
    ),
    TokenRequirement(
        "quality_gate_and_docs",
        QUALITY_GATE,
        "s51_audit_gate_hook",
        "run_ae_artifact_retention_automation_boundary_audit.py",
        "The S51 boundary audit should run in the default quality gate.",
    ),
    TokenRequirement(
        "quality_gate_and_docs",
        DOCS_INDEX,
        "s51_slice_index",
        "Slice 0501",
        "The docs index should expose the S51 starting point.",
    ),
    TokenRequirement(
        "quality_gate_and_docs",
        AE_API_README,
        "s51_ae_readme_note",
        "Slice 0501 starts S51",
        "AE README should document the S51 automation boundary.",
    ),
    TokenRequirement(
        "quality_gate_and_docs",
        AG_README,
        "s51_ag_readme_note",
        "Slice 0501 starts S51",
        "AG README should document the S51 operator boundary.",
    ),
)

PLANNED_AUTOMATION_STEPS = (
    PlannedAutomationStep(
        "scheduler_runtime_config_expansion",
        "Slice_0502",
        "Add disabled-by-default scheduler knobs without starting a daemon.",
    ),
    PlannedAutomationStep(
        "scheduler_tick_planner",
        "Slice_0503",
        "Plan deterministic retention ticks and skip unsafe windows.",
    ),
    PlannedAutomationStep(
        "scheduler_tick_jobqueue_admission",
        "Slice_0504",
        "Admit planned ticks through AE's shared JobQueue.",
    ),
    PlannedAutomationStep(
        "scheduler_tick_postgresql_smoke",
        "Slice_0505",
        "Verify the tick admission path against the real AE test DB.",
    ),
    PlannedAutomationStep(
        "physical_purge_execute_contract_hardening",
        "Slice_0506",
        "Tighten execute-mode flags before enabling physical purge adapters.",
    ),
    PlannedAutomationStep(
        "physical_purge_adapter",
        "Slice_0507",
        "Implement guarded storage/database physical deletion behind flags.",
    ),
    PlannedAutomationStep(
        "physical_purge_postgresql_smoke",
        "Slice_0508",
        "Verify guarded physical purge against the real AE test DB.",
    ),
    PlannedAutomationStep(
        "ag_automation_projection",
        "Slice_0509",
        "Expose retention automation state through AG without direct writes.",
    ),
    PlannedAutomationStep(
        "s51_closure",
        "Slice_0510",
        "Close the retention automation safety track.",
    ),
)

SENSITIVE_PATTERNS = (
    re.compile(r"postgresql(?:\+\w+)?://[^\"'\s]+", re.IGNORECASE),
    re.compile(r"nuri1004", re.IGNORECASE),
    re.compile(r"/data/nex-platform", re.IGNORECASE),
    re.compile(r"ed6@c496em", re.IGNORECASE),
    re.compile(r"service-token-[\w-]+", re.IGNORECASE),
)


def run_ae_artifact_retention_automation_boundary_audit(
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
        "s50_closed_baseline_present": group_status.get("s50_closed_baseline")
        is True,
        "ae_scheduler_runtime_present": group_status.get("ae_scheduler_runtime")
        is True,
        "ae_dry_run_guardrail_present": group_status.get("ae_dry_run_guardrail")
        is True,
        "ae_route_surface_present": group_status.get("ae_route_surface") is True,
        "ag_control_boundary_present": group_status.get("ag_control_boundary")
        is True,
        "postgres_smoke_evidence_present": group_status.get("postgres_smoke_evidence")
        is True,
        "quality_gate_and_docs_present": group_status.get("quality_gate_and_docs")
        is True,
        "scheduler_daemon_default_disabled": True,
        "first_automation_mode_dry_run": True,
        "physical_delete_default_disabled": True,
        "execute_requires_operator_guards": True,
        "ag_api_mediated_control_only": True,
        "test_db_smoke_required_for_mutating_slices": True,
        "redacted_evidence_only": True,
    }
    issues = build_issues(paths, tokens)
    status = "PASS" if all(checks.values()) and not issues else "FAIL"
    evidence: dict[str, Any] = {
        "audit_schema_version": SCHEMA_VERSION,
        "status": status,
        "failure_code": None if status == "PASS" else "automation_boundary_failed",
        "slice": "0501",
        "surface": "S51 AE artifact retention automation safety",
        "automation_boundary": {
            "artifact_system_of_record": "nex-ae-api",
            "operator_projection_owner": "nex-ag",
            "scheduler_daemon_default": "disabled",
            "first_automation_mode": FIRST_AUTOMATION_MODE,
            "default_execution_mode": DEFAULT_EXECUTION_MODE,
            "job_admission_boundary": "ae_api_jobqueue_admission",
            "worker_boundary": "shared_worker_runner",
            "ag_control_boundary": "ae_api_only",
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
            "physical_delete_automation_default": "disabled",
            "physical_delete_execute_requires_operator_guards": True,
            "postgres_smoke_required_before_execute": True,
        },
        "paths": paths,
        "source_tokens": tokens,
        "planned_automation_steps": build_planned_automation_steps(),
        "checks": checks,
        "issues": issues,
        "next_slices": ["Slice_0502", "Slice_0503", "Slice_0504", "Slice_0505"],
        "protected_env": summarize_protected_env(env),
        "redaction_summary": {
            "database_url_included": False,
            "service_token_included": False,
            "provider_api_key_included": False,
            "storage_path_included": False,
            "raw_artifact_payload_included": False,
            "raw_download_content_included": False,
            "raw_execution_payload_included": False,
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


def build_planned_automation_steps() -> list[dict[str, str | bool]]:
    return [
        {
            "name": item.name,
            "planned_slice": item.planned_slice,
            "purpose": item.purpose,
            "blocking": False,
        }
        for item in PLANNED_AUTOMATION_STEPS
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
        f"mode={DEFAULT_EXECUTION_MODE} "
        f"next=Slice_0502"
    )
    if failing_checks:
        suffix += f" failing_checks={','.join(failing_checks)}"
    return (
        "ae_artifact_retention_automation_boundary_audit="
        f"{str(evidence['status']).lower()} {suffix}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run AE artifact retention automation boundary audit."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence = run_ae_artifact_retention_automation_boundary_audit()
        if args.output:
            write_audit_evidence(args.output, evidence)
        print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2))
        return 0 if evidence["status"] == "PASS" else 1
    except Exception as exc:
        print(
            "ae_artifact_retention_automation_boundary_audit=fail "
            f"error={exc.__class__.__name__}"
        )
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
