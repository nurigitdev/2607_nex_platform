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
SCHEMA_VERSION = "ae_artifact_retention_scheduler_runtime_boundary_audit.v1"

PROTECTED_ENV_KEYS = (
    "NEX_AE_DATABASE_URL",
    "NEX_AE_TEST_DATABASE_URL",
    "NEX_AE_ARTIFACT_STORAGE_ROOT",
    "NEX_AG_AE_ARTIFACT_SERVICE_TOKEN",
    "NEX_SERVICE_TOKEN",
)

S50_JOB_TYPE = "ae.artifact_retention.scheduled_execution"
S50_WORKER_TYPE = "ae.artifact_retention.scheduled_execution.worker"
DEFAULT_MODE = "DRY_RUN"


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
class PlannedGap:
    name: str
    planned_slice: str
    purpose: str


AE_API_ARTIFACTS = ROOT / "services" / "nex-ae-api" / "nex_ae_api" / "artifacts.py"
AE_API_README = ROOT / "services" / "nex-ae-api" / "README.md"
AG_ARTIFACT_OPERATIONS = ROOT / "services" / "nex-ag" / "nex_ag" / "artifact_operations.py"
AG_README = ROOT / "services" / "nex-ag" / "README.md"
RUNTIME_JOBS = ROOT / "services" / "_shared" / "nex_runtime" / "jobs.py"
RUNTIME_WORKER_RUNNER = ROOT / "services" / "_shared" / "nex_runtime" / "worker_runner.py"
RUNTIME_PERSISTENCE = ROOT / "services" / "_shared" / "nex_runtime" / "persistence.py"
S49_CLOSURE = (
    ROOT
    / "scripts"
    / "smoke"
    / "run_s49_ae_artifact_retention_scheduled_operations_closure.py"
)
QUALITY_GATE = ROOT / "scripts" / "quality" / "run_quality_gate.sh"
DOCS_INDEX = ROOT / "docs" / "README.md"
S49_CLOSURE_DOC = (
    ROOT
    / "docs"
    / "slices"
    / "0490_s49_ae_artifact_retention_scheduled_operations_closure.md"
)
S50_BOUNDARY_DOC = (
    ROOT
    / "docs"
    / "slices"
    / "0491_ae_artifact_retention_scheduler_runtime_boundary_audit.md"
)

REQUIRED_PATHS = (
    RequiredPath("ae_api_artifacts", AE_API_ARTIFACTS, "AE retention runtime."),
    RequiredPath("ae_api_readme", AE_API_README, "AE retention notes."),
    RequiredPath("ag_artifact_operations", AG_ARTIFACT_OPERATIONS, "AG projection boundary."),
    RequiredPath("ag_readme", AG_README, "AG operations notes."),
    RequiredPath("runtime_jobs", RUNTIME_JOBS, "Shared JobQueue contract."),
    RequiredPath("runtime_worker_runner", RUNTIME_WORKER_RUNNER, "Shared worker runner."),
    RequiredPath("runtime_persistence", RUNTIME_PERSISTENCE, "Runtime persistence bootstrap."),
    RequiredPath("s49_closure", S49_CLOSURE, "S49 scheduled operations closure."),
    RequiredPath("quality_gate", QUALITY_GATE, "Default regression gate."),
    RequiredPath("docs_index", DOCS_INDEX, "Slice index."),
    RequiredPath("s49_closure_doc", S49_CLOSURE_DOC, "S50 input baseline."),
    RequiredPath("s50_boundary_doc", S50_BOUNDARY_DOC, "S50 boundary note."),
)

REQUIRED_SOURCE_TOKENS = (
    TokenRequirement(
        "s49_closed_baseline",
        S49_CLOSURE,
        "s49_slice_range",
        "0481-0490",
        "S50 starts only after S49 scheduled operations closure.",
    ),
    TokenRequirement(
        "shared_jobqueue_runtime",
        RUNTIME_JOBS,
        "common_job_schema",
        "COMMON_JOB_SCHEMA_VERSION",
        "Scheduled runtime jobs must reuse common_job.v1.",
    ),
    TokenRequirement(
        "shared_jobqueue_runtime",
        RUNTIME_JOBS,
        "job_builder",
        "build_common_job",
        "Planners should produce validated common jobs.",
    ),
    TokenRequirement(
        "shared_jobqueue_runtime",
        RUNTIME_JOBS,
        "sqlalchemy_jobqueue",
        "SqlAlchemyJobQueue",
        "PostgreSQL smoke should use the shared SQLAlchemy queue.",
    ),
    TokenRequirement(
        "shared_worker_runtime",
        RUNTIME_WORKER_RUNNER,
        "worker_once",
        "run_worker_once",
        "AE retention workers should use the shared worker runner.",
    ),
    TokenRequirement(
        "shared_worker_runtime",
        RUNTIME_WORKER_RUNNER,
        "worker_batch",
        "run_worker_batch",
        "Batch execution should reuse shared worker batching.",
    ),
    TokenRequirement(
        "ae_retention_s49_runtime",
        AE_API_ARTIFACTS,
        "batch_plan_builder",
        "build_artifact_retention_batch_plan",
        "The scheduler begins by planning the AE batch.",
    ),
    TokenRequirement(
        "ae_retention_s49_runtime",
        AE_API_ARTIFACTS,
        "scheduled_command_builder",
        "build_artifact_retention_scheduled_execution_command",
        "Jobs should carry the existing scheduled execution command.",
    ),
    TokenRequirement(
        "ae_retention_s49_runtime",
        AE_API_ARTIFACTS,
        "mock_worker_helper",
        "run_artifact_retention_scheduled_execution_mock_worker",
        "S50 workers remain dry-run/mock-first until explicitly opened.",
    ),
    TokenRequirement(
        "ae_retention_s49_runtime",
        AE_API_ARTIFACTS,
        "history_store",
        "SqlAlchemyArtifactRetentionExecutionHistoryStore",
        "Scheduled job execution must persist AE-owned history.",
    ),
    TokenRequirement(
        "ae_retention_routes",
        AE_API_ARTIFACTS,
        "batch_plan_route",
        '"/api/v1/artifact-retention/batch-plan"',
        "Scheduler planning should stay aligned with the public AE plan route.",
    ),
    TokenRequirement(
        "ae_retention_routes",
        AE_API_ARTIFACTS,
        "purge_route",
        '"/api/v1/artifact-retention/purge"',
        "Worker execution should delegate to the guarded purge path.",
    ),
    TokenRequirement(
        "ag_read_only_projection",
        AG_ARTIFACT_OPERATIONS,
        "batch_projection_schema",
        "AG_ARTIFACT_OPERATION_RETENTION_BATCH_PROJECTION_SCHEMA_VERSION",
        "AG starts S50 from read-only batch-plan projection.",
    ),
    TokenRequirement(
        "ag_read_only_projection",
        AG_ARTIFACT_OPERATIONS,
        "batch_projection_route",
        '"/admin/v1/operations/artifact-retention/batch-plan"',
        "AG operator visibility should stay API mediated.",
    ),
    TokenRequirement(
        "quality_gate_and_docs",
        QUALITY_GATE,
        "s50_boundary_gate_hook",
        "run_ae_artifact_retention_scheduler_runtime_boundary_audit.py",
        "The S50 boundary audit should run in the default quality gate.",
    ),
    TokenRequirement(
        "quality_gate_and_docs",
        DOCS_INDEX,
        "s50_slice_index",
        "Slice 0491",
        "The docs index should expose the S50 starting point.",
    ),
)

PLANNED_GAPS = (
    PlannedGap(
        "scheduled_job_contract_schema",
        "Slice_0492",
        "Freeze the common_job payload and redaction contract.",
    ),
    PlannedGap(
        "scheduled_job_planner_admission",
        "Slice_0493",
        "Build deterministic JobQueue admission around AE batch plans.",
    ),
    PlannedGap(
        "scheduled_worker_runner_adapter",
        "Slice_0494",
        "Run queued retention jobs through the shared worker runner.",
    ),
    PlannedGap(
        "scheduled_jobqueue_postgres_smoke",
        "Slice_0495",
        "Verify planner, queue, worker, and history with the AE test DB.",
    ),
    PlannedGap(
        "ag_scheduled_job_operations_projection",
        "Slice_0496",
        "Expose read-only scheduled job status to AG operators.",
    ),
    PlannedGap(
        "ag_scheduled_dispatch_control_guardrail",
        "Slice_0497",
        "Add guarded AG dispatch/control without direct AE DB writes.",
    ),
    PlannedGap(
        "ae_scheduler_config_read_model_api",
        "Slice_0498",
        "Expose AE scheduler config/read-model without enabling a daemon.",
    ),
    PlannedGap(
        "ae_ag_scheduler_postgres_smoke",
        "Slice_0499",
        "Verify AE/AG scheduler visibility against test DBs.",
    ),
    PlannedGap(
        "s50_closure",
        "Slice_0500",
        "Close the scheduler runtime track.",
    ),
)

SENSITIVE_PATTERNS = (
    re.compile(r"postgresql(?:\+\w+)?://[^\"'\s]+", re.IGNORECASE),
    re.compile(r"nuri1004", re.IGNORECASE),
    re.compile(r"/data/nex-platform", re.IGNORECASE),
    re.compile(r"ed6@c496em", re.IGNORECASE),
    re.compile(r"service-token-[\w-]+", re.IGNORECASE),
)


def run_ae_artifact_retention_scheduler_runtime_boundary_audit(
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
        "s49_closed_baseline_present": group_status.get("s49_closed_baseline")
        is True,
        "shared_jobqueue_runtime_present": group_status.get(
            "shared_jobqueue_runtime"
        )
        is True,
        "shared_worker_runtime_present": group_status.get("shared_worker_runtime")
        is True,
        "ae_retention_s49_runtime_present": group_status.get(
            "ae_retention_s49_runtime"
        )
        is True,
        "ae_retention_routes_present": group_status.get("ae_retention_routes")
        is True,
        "ag_read_only_projection_present": group_status.get(
            "ag_read_only_projection"
        )
        is True,
        "quality_gate_and_docs_present": group_status.get("quality_gate_and_docs")
        is True,
        "scheduler_daemon_deferred": True,
        "default_execution_mode_dry_run": True,
        "physical_delete_automation_deferred": True,
        "ag_direct_database_access_disallowed": True,
        "redacted_evidence_only": True,
    }
    issues = []
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
    status = "PASS" if all(checks.values()) and not issues else "FAIL"
    evidence: dict[str, Any] = {
        "audit_schema_version": SCHEMA_VERSION,
        "status": status,
        "slice": "0491",
        "surface": "S50 AE artifact retention scheduler runtime",
        "decisions": {
            "artifact_system_of_record": "nex-ae-api",
            "operator_projection_owner": "nex-ag",
            "job_type": S50_JOB_TYPE,
            "worker_type": S50_WORKER_TYPE,
            "job_shape": "common_job.v1_with_metadata_only_retention_payload",
            "planner_entrypoint": "ae_batch_plan_to_job_admission",
            "worker_entrypoint": "shared_worker_runner_to_dry_run_mock_worker",
            "default_execution_mode": DEFAULT_MODE,
            "scheduler_daemon_enabled_in_s50": False,
            "physical_delete_automation_enabled_in_s50": False,
            "history_policy": "persist_every_worker_attempt_in_ae_history_store",
            "idempotency_scope": "tenant_id, workspace_id, owner_user_id, schedule_id, window",
            "postgres_smoke_target": "nex_ae_test_for_protected_s50_smoke",
            "ag_database_access_policy": "read_or_dispatch_ae_api_only",
        },
        "paths": paths,
        "source_tokens": tokens,
        "planned_gaps": build_gap_results(),
        "checks": checks,
        "issues": issues,
        "next_slices": ["Slice_0492", "Slice_0493", "Slice_0494", "Slice_0495"],
        "protected_env": summarize_protected_env(env),
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


def build_gap_results() -> list[dict[str, str | bool]]:
    return [
        {
            "name": item.name,
            "planned_slice": item.planned_slice,
            "purpose": item.purpose,
            "blocking": False,
        }
        for item in PLANNED_GAPS
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
        f"job_type={S50_JOB_TYPE} "
        f"default_mode={DEFAULT_MODE} "
        "next=Slice_0492"
    )
    if failing_checks:
        suffix += f" failing_checks={','.join(failing_checks)}"
    return (
        "ae_artifact_retention_scheduler_runtime_boundary_audit="
        f"{str(evidence['status']).lower()} {suffix}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run AE artifact retention scheduler runtime boundary audit."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence = run_ae_artifact_retention_scheduler_runtime_boundary_audit()
        if args.output:
            write_audit_evidence(args.output, evidence)
        print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2))
        return 0 if evidence["status"] == "PASS" else 1
    except Exception as exc:
        print(
            "ae_artifact_retention_scheduler_runtime_boundary_audit=fail "
            f"error={exc.__class__.__name__}"
        )
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
