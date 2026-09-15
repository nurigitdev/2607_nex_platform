#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = (
    "ag_operator_review_escalation_dispatch_daemon_liveness_boundary_audit.v1"
)

SLICE_ID = "0781"
S79_SURFACE = "AG operator review escalation dispatch daemon liveness and heartbeat runtime"
BOUNDARY = "ag_owned_operator_review_escalation_dispatch_daemon_liveness"
SOURCE_DISPATCH_TABLE = "ag_op_esc_dispatches"
SOURCE_EVENT_TABLE = "service_operational_events"
SOURCE_HEARTBEAT_TABLE = "service_worker_heartbeats"
MAX_TABLE_NAME_LENGTH = 30


@dataclass(frozen=True)
class RequiredPath:
    name: str
    relative_path: str
    purpose: str


@dataclass(frozen=True)
class TokenRequirement:
    group: str
    relative_path: str
    token_id: str
    token: str
    purpose: str


REQUIRED_PATHS = (
    RequiredPath(
        "s78_closure_script",
        "scripts/smoke/run_s78_operator_review_escalation_dispatch_daemon_process_closure.py",
        "S78 process closure must be complete before S79 liveness work.",
    ),
    RequiredPath(
        "s78_closure_doc",
        "docs/slices/0780_s78_operator_review_escalation_dispatch_daemon_process_closure.md",
        "S78 closure documentation.",
    ),
    RequiredPath(
        "dispatch_execution_runtime",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "Process metadata and runtime state already name the liveness source.",
    ),
    RequiredPath(
        "dispatch_daemon_cli",
        "services/nex-ag/nex_ag/operator_review_dispatch_daemon.py",
        "Executable daemon boundary for future heartbeat emission.",
    ),
    RequiredPath(
        "ag_operations_runtime",
        "services/nex-ag/nex_ag/operations.py",
        "AG operations dashboard exposes process and liveness source state.",
    ),
    RequiredPath(
        "operational_event_runtime",
        "services/_shared/nex_runtime/operational_events.py",
        "Lifecycle evidence remains separate from liveness heartbeats.",
    ),
    RequiredPath(
        "worker_heartbeat_runtime",
        "services/_shared/nex_runtime/worker_heartbeats.py",
        "Shared heartbeat contract, stale calculation, and PostgreSQL store.",
    ),
    RequiredPath(
        "quality_gate",
        "scripts/quality/run_quality_gate.sh",
        "Default regression gate.",
    ),
    RequiredPath("docs_index", "docs/README.md", "Slice documentation index."),
    RequiredPath(
        "slice_doc",
        "docs/slices/0781_ag_escalation_dispatch_daemon_liveness_boundary_audit.md",
        "Slice 0781 implementation note.",
    ),
)

TOKEN_REQUIREMENTS = (
    TokenRequirement(
        "s78_closed_baseline",
        "scripts/smoke/run_s78_operator_review_escalation_dispatch_daemon_process_closure.py",
        "s78_closure_schema",
        "s78_operator_review_escalation_dispatch_daemon_process_closure.v1",
        "S79 starts only after the S78 process closure.",
    ),
    TokenRequirement(
        "s78_closed_baseline",
        "scripts/smoke/run_s78_operator_review_escalation_dispatch_daemon_process_closure.py",
        "s78_no_new_tables",
        '"new_tables": []',
        "S79 liveness should begin from the no-new-table S78 baseline.",
    ),
    TokenRequirement(
        "s78_closed_baseline",
        "scripts/smoke/run_s78_operator_review_escalation_dispatch_daemon_process_closure.py",
        "s78_liveness_source",
        "service_worker_heartbeats",
        "S78 already selected the shared heartbeat table as the liveness source.",
    ),
    TokenRequirement(
        "heartbeat_runtime",
        "services/_shared/nex_runtime/worker_heartbeats.py",
        "heartbeat_schema_version",
        "WORKER_HEARTBEAT_SCHEMA_VERSION",
        "S79 should reuse the shared heartbeat schema version.",
    ),
    TokenRequirement(
        "heartbeat_runtime",
        "services/_shared/nex_runtime/worker_heartbeats.py",
        "worker_heartbeat_builder",
        "def build_worker_heartbeat",
        "Heartbeat emission should use the shared builder.",
    ),
    TokenRequirement(
        "heartbeat_runtime",
        "services/_shared/nex_runtime/worker_heartbeats.py",
        "worker_heartbeat_emitter",
        "class WorkerHeartbeatEmitter",
        "Daemon liveness emission should use the shared emitter.",
    ),
    TokenRequirement(
        "heartbeat_runtime",
        "services/_shared/nex_runtime/worker_heartbeats.py",
        "sqlalchemy_worker_heartbeat_store",
        "class SqlAlchemyWorkerHeartbeatStore",
        "PostgreSQL liveness smoke should use the shared heartbeat store.",
    ),
    TokenRequirement(
        "heartbeat_runtime",
        "services/_shared/nex_runtime/worker_heartbeats.py",
        "stale_calculator",
        "def worker_heartbeat_is_stale",
        "Operations liveness should use the shared stale calculation.",
    ),
    TokenRequirement(
        "heartbeat_runtime",
        "services/_shared/nex_runtime/worker_heartbeats.py",
        "default_stale_after_seconds",
        "DEFAULT_WORKER_STALE_AFTER_SECONDS",
        "S79 should document the default stale threshold.",
    ),
    TokenRequirement(
        "heartbeat_runtime",
        "services/_shared/nex_runtime/worker_heartbeats.py",
        "max_stale_after_seconds",
        "MAX_WORKER_STALE_AFTER_SECONDS",
        "S79 should retain the shared stale threshold upper bound.",
    ),
    TokenRequirement(
        "heartbeat_runtime",
        "services/_shared/nex_runtime/worker_heartbeats.py",
        "active_status_set",
        "ACTIVE_WORKER_HEARTBEAT_STATUSES",
        "Dashboard status should distinguish active daemon heartbeats.",
    ),
    TokenRequirement(
        "heartbeat_runtime",
        "services/_shared/nex_runtime/worker_heartbeats.py",
        "terminal_status_set",
        "TERMINAL_WORKER_HEARTBEAT_STATUSES",
        "Dashboard status should distinguish terminal daemon heartbeats.",
    ),
    TokenRequirement(
        "process_runtime",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "process_metadata_builder",
        "def build_dispatch_execution_daemon_process_metadata",
        "Liveness must remain tied to daemon process metadata.",
    ),
    TokenRequirement(
        "process_runtime",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "process_runtime_state_builder",
        "def build_dispatch_execution_daemon_process_runtime_state",
        "Operations liveness should extend the runtime state read model.",
    ),
    TokenRequirement(
        "process_runtime",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "liveness_source_token",
        '"liveness_source": "service_worker_heartbeats"',
        "Process metadata already points to the shared heartbeat table.",
    ),
    TokenRequirement(
        "daemon_cli",
        "services/nex-ag/nex_ag/operator_review_dispatch_daemon.py",
        "daemon_cli_executor",
        "def execute_dispatch_execution_daemon_cli",
        "Heartbeat emission will attach to the executable daemon boundary.",
    ),
    TokenRequirement(
        "operations_dashboard",
        "services/nex-ag/nex_ag/operations.py",
        "daemon_process_section",
        "daemon_process",
        "Operations dashboard must keep a daemon process surface.",
    ),
    TokenRequirement(
        "operations_dashboard",
        "services/nex-ag/nex_ag/operations.py",
        "dashboard_liveness_source",
        '"liveness_source": "service_worker_heartbeats"',
        "Dashboard process state already names the heartbeat liveness source.",
    ),
    TokenRequirement(
        "operational_event_foundation",
        "services/_shared/nex_runtime/operational_events.py",
        "operational_event_emitter",
        "class OperationalEventEmitter",
        "Lifecycle events stay in operational events, not heartbeat rows.",
    ),
    TokenRequirement(
        "quality_gate",
        "scripts/quality/run_quality_gate.sh",
        "s78_closure_quality_gate",
        "run_s78_operator_review_escalation_dispatch_daemon_process_closure.py",
        "The S78 closure remains in the default quality gate.",
    ),
    TokenRequirement(
        "quality_gate",
        "scripts/quality/run_quality_gate.sh",
        "s79_liveness_boundary_quality_gate",
        "run_ag_operator_review_escalation_dispatch_daemon_liveness_boundary_audit.py",
        "Slice 0781 liveness boundary audit must run in the quality gate.",
    ),
    TokenRequirement(
        "docs_index",
        "docs/README.md",
        "slice_0781_indexed",
        "0781_ag_escalation_dispatch_daemon_liveness_boundary_audit.md",
        "Slice 0781 documentation must be indexed.",
    ),
)

TABLE_NAMES_UNDER_REVIEW = (
    SOURCE_DISPATCH_TABLE,
    SOURCE_EVENT_TABLE,
    SOURCE_HEARTBEAT_TABLE,
)

NEXT_SLICES = (
    "Slice_0782",
    "Slice_0783",
    "Slice_0784",
    "Slice_0785",
    "Slice_0786",
    "Slice_0787",
    "Slice_0788",
    "Slice_0789",
    "Slice_0790",
)


def run_ag_operator_review_escalation_dispatch_daemon_liveness_boundary_audit(
    root: Path = ROOT,
) -> dict[str, Any]:
    paths = _required_path_results(root)
    tokens = _token_results(root)
    table_names = _table_name_results()
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "required_tokens_present": all(item["present"] for item in tokens),
        "table_names_within_limit": all(item["within_limit"] for item in table_names),
        "s78_closed_baseline_present": _group_present(tokens, "s78_closed_baseline"),
        "heartbeat_runtime_present": _group_present(tokens, "heartbeat_runtime"),
        "process_runtime_present": _group_present(tokens, "process_runtime"),
        "daemon_cli_present": _group_present(tokens, "daemon_cli"),
        "operations_dashboard_present": _group_present(tokens, "operations_dashboard"),
        "operational_event_foundation_present": _group_present(
            tokens,
            "operational_event_foundation",
        ),
        "quality_gate_present": _group_present(tokens, "quality_gate"),
        "docs_index_present": _group_present(tokens, "docs_index"),
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "status": "PASS" if passed else "FAIL",
        "failure_code": None
        if passed
        else "ag_operator_review_escalation_dispatch_daemon_liveness_boundary_failed",
        "slice": SLICE_ID,
        "surface": S79_SURFACE,
        "boundary": {
            "boundary": BOUNDARY,
            "source_dispatch_table": SOURCE_DISPATCH_TABLE,
            "source_event_table": SOURCE_EVENT_TABLE,
            "source_heartbeat_table": SOURCE_HEARTBEAT_TABLE,
            "new_table_in_slice_0781": False,
            "heartbeat_emission_in_slice_0781": False,
            "protected_liveness_route_in_slice_0781": False,
            "dashboard_liveness_mutation_in_slice_0781": False,
            "process_control_mutation_in_s79": False,
            "first_heartbeat_contract_slice": "Slice_0782",
            "first_heartbeat_emission_slice": "Slice_0783",
            "first_liveness_read_model_slice": "Slice_0784",
            "first_protected_liveness_route_slice": "Slice_0785",
            "first_dashboard_liveness_slice": "Slice_0786",
            "first_stale_daemon_issue_candidate_slice": "Slice_0787",
            "postgres_smoke_slice": "Slice_0788",
            "privacy_runbook_slice": "Slice_0789",
            "closure_slice": "Slice_0790",
        },
        "liveness_contract": {
            "service_id": "nex-ag",
            "worker_id": "ag-dispatch-execution-daemon",
            "worker_type": "operator_review_dispatch_daemon",
            "source_table": SOURCE_HEARTBEAT_TABLE,
            "heartbeat_schema_version": "worker_heartbeat.v1",
            "default_stale_after_seconds": 60,
            "max_stale_after_seconds": 86400,
            "statuses": [
                "STARTING",
                "IDLE",
                "BUSY",
                "STOPPING",
                "STOPPED",
                "ERROR",
            ],
            "active_statuses": ["STARTING", "IDLE", "BUSY"],
            "terminal_statuses": ["STOPPED", "ERROR"],
            "new_table_required": False,
            "mutation_in_slice_0781": False,
        },
        "separation_of_concerns": {
            "lifecycle_source": SOURCE_EVENT_TABLE,
            "liveness_source": SOURCE_HEARTBEAT_TABLE,
            "dispatch_source": SOURCE_DISPATCH_TABLE,
            "stale_daemon_issue_candidates": "derived_from_heartbeat_read_model",
            "start_stop_controls": "remain_contract_only_no_subprocess_mutation",
        },
        "refactoring_checkpoint": {
            "reuse_shared_worker_heartbeat_runtime": True,
            "keep_heartbeat_emission_optional_and_explicit": True,
            "keep_lifecycle_events_and_liveness_separate": True,
            "keep_dashboard_stale_state_read_only": True,
            "avoid_new_table_until_heartbeat_query_pressure_is_proven": True,
            "keep_postgres_smoke_real_test_db": True,
            "keep_sensitive_values_redacted": True,
        },
        "checks": checks,
        "paths": paths,
        "source_tokens": tokens,
        "table_names": table_names,
        "issues": _issues(paths, tokens, table_names),
        "next_slices": list(NEXT_SLICES),
    }


def _required_path_results(root: Path) -> list[dict[str, Any]]:
    return [
        {
            "name": item.name,
            "path": item.relative_path,
            "purpose": item.purpose,
            "present": (root / item.relative_path).is_file(),
        }
        for item in REQUIRED_PATHS
    ]


def _token_results(root: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in TOKEN_REQUIREMENTS:
        path = root / item.relative_path
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        results.append(
            {
                "group": item.group,
                "token_id": item.token_id,
                "path": item.relative_path,
                "purpose": item.purpose,
                "present": item.token in text,
            }
        )
    return results


def _table_name_results() -> list[dict[str, Any]]:
    return [
        {
            "table_name": table_name,
            "length": len(table_name),
            "max_length": MAX_TABLE_NAME_LENGTH,
            "within_limit": len(table_name) <= MAX_TABLE_NAME_LENGTH,
        }
        for table_name in TABLE_NAMES_UNDER_REVIEW
    ]


def _group_present(tokens: list[dict[str, Any]], group: str) -> bool:
    grouped = [item for item in tokens if item["group"] == group]
    return bool(grouped) and all(item["present"] for item in grouped)


def _issues(
    paths: list[dict[str, Any]],
    tokens: list[dict[str, Any]],
    table_names: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    issues.extend(
        {
            "category": "path_missing",
            "name": item["name"],
            "path": item["path"],
        }
        for item in paths
        if not item["present"]
    )
    issues.extend(
        {
            "category": "source_token_missing",
            "group": item["group"],
            "token_id": item["token_id"],
            "path": item["path"],
        }
        for item in tokens
        if not item["present"]
    )
    issues.extend(
        {
            "category": "table_name_too_long",
            "table_name": item["table_name"],
            "length": item["length"],
            "max_length": item["max_length"],
        }
        for item in table_names
        if not item["within_limit"]
    )
    return issues


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        boundary = evidence["boundary"]
        contract = evidence["liveness_contract"]
        return (
            "ag_operator_review_escalation_dispatch_daemon_liveness_boundary=pass "
            f"boundary={boundary['boundary']} "
            f"new_table={boundary['new_table_in_slice_0781']} "
            f"heartbeat_source={boundary['source_heartbeat_table']} "
            f"worker_id={contract['worker_id']} "
            f"contract={boundary['first_heartbeat_contract_slice']} "
            f"read_model={boundary['first_liveness_read_model_slice']}"
        )
    return (
        "ag_operator_review_escalation_dispatch_daemon_liveness_boundary=fail "
        f"reason={evidence.get('failure_code')} "
        f"issues={len(evidence.get('issues', []))}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the S79 AG operator review escalation dispatch daemon liveness "
            "and heartbeat boundary audit."
        )
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_ag_operator_review_escalation_dispatch_daemon_liveness_boundary_audit()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, default=str)
    )
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
