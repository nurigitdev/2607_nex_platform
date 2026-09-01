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
SCHEMA_VERSION = "ae_artifact_retention_scheduled_operations_boundary_audit.v1"

PROTECTED_ENV_KEYS = (
    "NEX_AE_DATABASE_URL",
    "NEX_AE_TEST_DATABASE_URL",
    "NEX_AE_ARTIFACT_STORAGE_ROOT",
    "NEX_AG_AE_ARTIFACT_SERVICE_TOKEN",
    "NEX_SERVICE_TOKEN",
)

DEFAULT_RETENTION_DAYS = 30
SUPPORTED_RETENTION_DAY_PRESETS = (15, 30)
SCHEDULED_BATCH_TIMEZONE = "Asia/Seoul"
SCHEDULED_BATCH_WINDOW = "02:00-05:00"
SCHEDULED_BATCH_WINDOW_START = "02:00"
SCHEDULED_BATCH_WINDOW_END = "05:00"


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
S47_BOUNDARY_AUDIT = (
    ROOT / "scripts" / "smoke" / "run_ae_artifact_retention_purge_boundary_audit.py"
)
S47_CLOSURE = ROOT / "scripts" / "smoke" / "run_s47_ae_artifact_retention_purge_closure.py"
S48_CLOSURE = (
    ROOT / "scripts" / "smoke" / "run_s48_ae_artifact_retention_history_closure.py"
)
RETENTION_HISTORY_SMOKE = (
    ROOT / "scripts" / "smoke" / "run_ae_artifact_retention_history_postgres_smoke.py"
)
RETENTION_HISTORY_QUERY_SMOKE = (
    ROOT
    / "scripts"
    / "smoke"
    / "run_ae_artifact_retention_history_query_postgres_smoke.py"
)
QUALITY_GATE = ROOT / "scripts" / "quality" / "run_quality_gate.sh"
DOCS_INDEX = ROOT / "docs" / "README.md"
S48_CLOSURE_DOC = (
    ROOT / "docs" / "slices" / "0480_s48_ae_artifact_retention_history_closure.md"
)
S49_BOUNDARY_DOC = (
    ROOT
    / "docs"
    / "slices"
    / "0481_ae_artifact_retention_scheduled_operations_boundary_audit.md"
)

REQUIRED_PATHS = (
    RequiredPath("ae_api_artifacts", AE_API_ARTIFACTS, "AE artifact retention runtime."),
    RequiredPath("ae_api_readme", AE_API_README, "AE API retention operations notes."),
    RequiredPath(
        "ag_artifact_operations",
        AG_ARTIFACT_OPERATIONS,
        "AG artifact operations projection boundary.",
    ),
    RequiredPath("ag_readme", AG_README, "AG artifact operations notes."),
    RequiredPath(
        "s47_boundary_audit",
        S47_BOUNDARY_AUDIT,
        "S47 logical purge and guarded purge boundary baseline.",
    ),
    RequiredPath("s47_closure", S47_CLOSURE, "S47 guarded purge closure baseline."),
    RequiredPath("s48_closure", S48_CLOSURE, "S48 retention history closure baseline."),
    RequiredPath(
        "retention_history_smoke",
        RETENTION_HISTORY_SMOKE,
        "Protected retention history writer smoke evidence.",
    ),
    RequiredPath(
        "retention_history_query_smoke",
        RETENTION_HISTORY_QUERY_SMOKE,
        "Protected retention history query smoke evidence.",
    ),
    RequiredPath("quality_gate", QUALITY_GATE, "Default regression gate."),
    RequiredPath("docs_index", DOCS_INDEX, "Slice index."),
    RequiredPath("s48_closure_doc", S48_CLOSURE_DOC, "S49 input baseline."),
    RequiredPath("s49_boundary_doc", S49_BOUNDARY_DOC, "S49 boundary audit note."),
)

REQUIRED_SOURCE_TOKENS = (
    TokenRequirement(
        "s48_closed_baseline",
        S48_CLOSURE,
        "s48_slice_range",
        "0471-0480",
        "Scheduled operations start only after S48 retention history is closed.",
    ),
    TokenRequirement(
        "schedule_policy_baseline",
        AE_API_ARTIFACTS,
        "retention_policy_schema",
        "AE_ARTIFACT_RETENTION_POLICY_SCHEMA_VERSION",
        "Scheduled operations should extend the existing AE retention policy.",
    ),
    TokenRequirement(
        "schedule_policy_baseline",
        AE_API_ARTIFACTS,
        "scheduled_execution_mode",
        "scheduled_batch_after_retention",
        "The current policy already names the planned scheduled batch mode.",
    ),
    TokenRequirement(
        "schedule_policy_baseline",
        AE_API_ARTIFACTS,
        "default_retention_days",
        "DEFAULT_ARTIFACT_RETENTION_DAYS_AFTER_LOGICAL_PURGE",
        "The first scheduled window uses the existing 30-day default.",
    ),
    TokenRequirement(
        "schedule_policy_baseline",
        AE_API_ARTIFACTS,
        "retention_day_presets",
        "SUPPORTED_ARTIFACT_RETENTION_DAY_PRESETS",
        "The early operator presets remain 15 and 30 days.",
    ),
    TokenRequirement(
        "batch_window_baseline",
        AE_API_ARTIFACTS,
        "batch_timezone",
        "ARTIFACT_RETENTION_BATCH_TIMEZONE",
        "Scheduled decisions must stay explicit about local timezone.",
    ),
    TokenRequirement(
        "batch_window_baseline",
        AE_API_ARTIFACTS,
        "batch_window_start",
        "ARTIFACT_RETENTION_BATCH_WINDOW_START",
        "Scheduled decisions must keep a stable local start time.",
    ),
    TokenRequirement(
        "batch_window_baseline",
        AE_API_ARTIFACTS,
        "batch_window_end",
        "ARTIFACT_RETENTION_BATCH_WINDOW_END",
        "Scheduled decisions must keep a stable local end time.",
    ),
    TokenRequirement(
        "dry_run_and_execute_guardrail",
        AE_API_ARTIFACTS,
        "dry_run_required",
        '"dry_run_required": True',
        "Scheduled execution must be preceded by dry-run planning.",
    ),
    TokenRequirement(
        "dry_run_and_execute_guardrail",
        AE_API_ARTIFACTS,
        "delete_enabled_guard",
        "delete_enabled",
        "Execute mode still requires an explicit delete flag.",
    ),
    TokenRequirement(
        "dry_run_and_execute_guardrail",
        AE_API_ARTIFACTS,
        "storage_mutation_guard",
        "storage_mutation_enabled",
        "Execute mode still requires an explicit storage mutation flag.",
    ),
    TokenRequirement(
        "dry_run_and_execute_guardrail",
        AE_API_ARTIFACTS,
        "database_row_delete_guard",
        "database_row_delete_enabled",
        "Execute mode still requires an explicit row deletion flag.",
    ),
    TokenRequirement(
        "ae_retention_routes",
        AE_API_ARTIFACTS,
        "candidate_route",
        '"/api/v1/artifact-retention/candidates"',
        "Batch planning should reuse the metadata-only candidate surface.",
    ),
    TokenRequirement(
        "ae_retention_routes",
        AE_API_ARTIFACTS,
        "purge_route",
        '"/api/v1/artifact-retention/purge"',
        "Scheduled execution should reuse the guarded purge surface.",
    ),
    TokenRequirement(
        "ae_retention_routes",
        AE_API_ARTIFACTS,
        "history_query_route",
        '"/api/v1/artifact-retention/executions"',
        "Operators need queryable execution history after scheduled runs.",
    ),
    TokenRequirement(
        "history_and_idempotency",
        AE_API_ARTIFACTS,
        "history_store",
        "SqlAlchemyArtifactRetentionExecutionHistoryStore",
        "Scheduled execution must persist the same AE-owned history record.",
    ),
    TokenRequirement(
        "history_and_idempotency",
        AE_API_ARTIFACTS,
        "idempotency_lookup",
        "get_by_idempotency_key",
        "Scheduled commands must be idempotent by scoped key.",
    ),
    TokenRequirement(
        "history_and_idempotency",
        AE_API_ARTIFACTS,
        "execution_payload_hash",
        "execution_payload_hash",
        "History projections expose hashes for debug correlation.",
    ),
    TokenRequirement(
        "postgres_smoke_baseline",
        RETENTION_HISTORY_SMOKE,
        "history_writer_live_db",
        "live_db",
        "S49 smoke work must keep direct test DB evidence available.",
    ),
    TokenRequirement(
        "postgres_smoke_baseline",
        RETENTION_HISTORY_QUERY_SMOKE,
        "history_query_live_db",
        "live_db",
        "S49 query smoke should remain live-test-DB capable.",
    ),
    TokenRequirement(
        "ag_read_only_ops_baseline",
        AG_ARTIFACT_OPERATIONS,
        "ag_retention_history_projection",
        "AG_ARTIFACT_OPERATION_RETENTION_HISTORY_PROJECTION_SCHEMA_VERSION",
        "AG starts S49 from a read-only history operations projection.",
    ),
    TokenRequirement(
        "ag_read_only_ops_baseline",
        AG_ARTIFACT_OPERATIONS,
        "ag_retention_history_route",
        '"/admin/v1/operations/artifact-retention/executions"',
        "AG already has an operator-visible retention history route.",
    ),
    TokenRequirement(
        "quality_gate_and_docs",
        QUALITY_GATE,
        "s49_boundary_gate_hook",
        "run_ae_artifact_retention_scheduled_operations_boundary_audit.py",
        "The S49 boundary audit should run in the default quality gate.",
    ),
    TokenRequirement(
        "quality_gate_and_docs",
        DOCS_INDEX,
        "s49_slice_index",
        "Slice 0481",
        "The slice index should expose the S49 starting point.",
    ),
    TokenRequirement(
        "quality_gate_and_docs",
        AE_API_README,
        "ae_readme_s49_note",
        "Slice 0481",
        "AE API notes should record the scheduled operations boundary.",
    ),
    TokenRequirement(
        "quality_gate_and_docs",
        AG_README,
        "ag_readme_s49_note",
        "Slice 0481",
        "AG notes should record the read-only operations boundary.",
    ),
)

PLANNED_GAPS = (
    PlannedGap(
        "retention_schedule_contract_schema",
        "Slice_0482",
        "Freeze schedule policy, window, timezone, and safe execution controls.",
    ),
    PlannedGap(
        "retention_batch_plan_read_model",
        "Slice_0483",
        "Project a metadata-only next-window batch plan before API exposure.",
    ),
    PlannedGap(
        "retention_batch_plan_api",
        "Slice_0484",
        "Expose authenticated AE batch-plan lookup without mutation.",
    ),
    PlannedGap(
        "retention_batch_plan_postgres_smoke",
        "Slice_0485",
        "Prove batch-plan calculations against the real AE test DB.",
    ),
    PlannedGap(
        "scheduled_execution_command",
        "Slice_0486",
        "Build the deterministic command payload used by workers and AG dispatch.",
    ),
    PlannedGap(
        "scheduled_execution_worker_mock_pipeline",
        "Slice_0487",
        "Exercise scheduled dry-run/execute through a mock worker pipeline.",
    ),
    PlannedGap(
        "ag_batch_operations_projection",
        "Slice_0488",
        "Add AG's operator projection without direct AE database access.",
    ),
    PlannedGap(
        "scheduled_execution_postgres_smoke",
        "Slice_0489",
        "Prove plan, guarded execute, history, and AG projection through test DB smoke.",
    ),
    PlannedGap(
        "s49_closure",
        "Slice_0490",
        "Close the scheduled artifact retention operations track.",
    ),
)

SENSITIVE_PATTERNS = (
    re.compile(r"postgresql(?:\+\w+)?://[^\"'\s]+", re.IGNORECASE),
    re.compile(r"nuri1004", re.IGNORECASE),
    re.compile(r"/data/nex-platform", re.IGNORECASE),
    re.compile(r"ed6@c496em", re.IGNORECASE),
    re.compile(r"service-token-[\w-]+", re.IGNORECASE),
)


def run_ae_artifact_retention_scheduled_operations_boundary_audit(
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
        "s48_closed_baseline_present": group_status.get("s48_closed_baseline")
        is True,
        "schedule_policy_baseline_present": group_status.get(
            "schedule_policy_baseline"
        )
        is True,
        "batch_window_baseline_present": group_status.get("batch_window_baseline")
        is True,
        "dry_run_and_execute_guardrail_present": group_status.get(
            "dry_run_and_execute_guardrail"
        )
        is True,
        "ae_retention_routes_present": group_status.get("ae_retention_routes") is True,
        "history_and_idempotency_present": group_status.get("history_and_idempotency")
        is True,
        "postgres_smoke_baseline_present": group_status.get("postgres_smoke_baseline")
        is True,
        "ag_read_only_ops_baseline_present": group_status.get(
            "ag_read_only_ops_baseline"
        )
        is True,
        "quality_gate_and_docs_present": group_status.get("quality_gate_and_docs")
        is True,
        "batch_mutation_deferred": True,
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
        "slice": "0481",
        "surface": "S49 AE artifact retention scheduled operations",
        "decisions": {
            "artifact_system_of_record": "nex-ae-api",
            "operator_projection_owner": "nex-ag",
            "ag_database_access_policy": "dispatch_or_read_ae_api_only",
            "default_retention_days_after_logical_purge": DEFAULT_RETENTION_DAYS,
            "supported_retention_day_presets": list(SUPPORTED_RETENTION_DAY_PRESETS),
            "scheduled_batch_timezone": SCHEDULED_BATCH_TIMEZONE,
            "scheduled_batch_window_local_time": SCHEDULED_BATCH_WINDOW,
            "scheduled_batch_window": {
                "start_local_time": SCHEDULED_BATCH_WINDOW_START,
                "end_local_time": SCHEDULED_BATCH_WINDOW_END,
            },
            "default_batch_mode": "DRY_RUN",
            "execute_requires_delete_enabled": True,
            "execute_requires_storage_mutation_enabled": True,
            "execute_requires_database_row_delete_enabled": True,
            "candidate_query_policy": "metadata_only_dry_run_before_execute",
            "history_policy": "persist_every_scheduled_attempt_in_ae_history_store",
            "idempotency_scope": "tenant_id, workspace_id, owner_user_id, idempotency_key",
            "worker_boundary": "deterministic_command_first_no_daemon_in_0481",
            "postgres_smoke_target": "nex_ae_test_for_protected_s49_smoke",
        },
        "paths": paths,
        "source_tokens": tokens,
        "planned_gaps": build_gap_results(),
        "checks": checks,
        "issues": issues,
        "next_slices": ["Slice_0482", "Slice_0483", "Slice_0484", "Slice_0485"],
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
        f"retention_days={DEFAULT_RETENTION_DAYS} "
        f"batch_window={SCHEDULED_BATCH_WINDOW} "
        f"timezone={SCHEDULED_BATCH_TIMEZONE} "
        "next=Slice_0482"
    )
    if failing_checks:
        suffix += f" failing_checks={','.join(failing_checks)}"
    return (
        "ae_artifact_retention_scheduled_operations_boundary_audit="
        f"{str(evidence['status']).lower()} {suffix}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run AE artifact retention scheduled operations boundary audit."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence = run_ae_artifact_retention_scheduled_operations_boundary_audit()
        if args.output:
            write_audit_evidence(args.output, evidence)
        print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2))
        return 0 if evidence["status"] == "PASS" else 1
    except Exception as exc:
        print(
            "ae_artifact_retention_scheduled_operations_boundary_audit=fail "
            f"error={exc.__class__.__name__}"
        )
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
