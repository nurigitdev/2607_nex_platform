#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = (
    "ag_operator_review_escalation_dispatch_daemon_process_boundary_audit.v1"
)

SLICE_ID = "0771"
S78_SURFACE = "AG operator review escalation dispatch daemon executable process runtime"
BOUNDARY = "ag_owned_operator_review_escalation_dispatch_daemon_process"
SOURCE_DISPATCH_TABLE = "ag_op_esc_dispatches"
SOURCE_EVENT_TABLE = "service_operational_events"
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
        "s77_closure_script",
        "scripts/smoke/run_s77_operator_review_escalation_dispatch_daemon_operations_closure.py",
        "S77 operations visibility closure must be complete before S78 process work.",
    ),
    RequiredPath(
        "s77_closure_doc",
        "docs/slices/0770_s77_operator_review_escalation_dispatch_daemon_operations_closure.md",
        "S77 closure documentation.",
    ),
    RequiredPath(
        "dispatch_execution_runtime",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "Daemon policy, tick planning, control admission, and tick-once execution.",
    ),
    RequiredPath(
        "ag_operations_runtime",
        "services/nex-ag/nex_ag/operations.py",
        "AG operations routes, dashboard projections, and protected controls.",
    ),
    RequiredPath(
        "operational_event_runtime",
        "services/_shared/nex_runtime/operational_events.py",
        "Shared operational event emitter and PostgreSQL store.",
    ),
    RequiredPath(
        "worker_heartbeat_runtime",
        "services/_shared/nex_runtime/worker_heartbeats.py",
        "Shared heartbeat store available for daemon liveness before new tables.",
    ),
    RequiredPath(
        "quality_gate",
        "scripts/quality/run_quality_gate.sh",
        "Default regression gate.",
    ),
    RequiredPath("docs_index", "docs/README.md", "Slice documentation index."),
    RequiredPath(
        "slice_doc",
        "docs/slices/0771_ag_escalation_dispatch_daemon_process_boundary_audit.md",
        "Slice 0771 implementation note.",
    ),
)

TOKEN_REQUIREMENTS = (
    TokenRequirement(
        "s77_closed_baseline",
        "scripts/smoke/run_s77_operator_review_escalation_dispatch_daemon_operations_closure.py",
        "s77_closure_schema",
        "s77_operator_review_escalation_dispatch_daemon_operations_closure.v1",
        "S78 starts only after the S77 operations closure.",
    ),
    TokenRequirement(
        "s77_closed_baseline",
        "scripts/smoke/run_s77_operator_review_escalation_dispatch_daemon_operations_closure.py",
        "s77_no_new_tables",
        '"new_tables": []',
        "S78 process planning should begin from the no-new-table S77 baseline.",
    ),
    TokenRequirement(
        "s77_closed_baseline",
        "scripts/smoke/run_s77_operator_review_escalation_dispatch_daemon_operations_closure.py",
        "s77_real_test_db_smoke",
        "test_db_control_events_history_dashboard_issue_candidate",
        "S78 PostgreSQL evidence must continue to mean a real nex_ag_test smoke.",
    ),
    TokenRequirement(
        "tick_execution_baseline",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "daemon_policy_builder",
        "def build_dispatch_execution_daemon_policy",
        "Process runtime policy must reuse the established daemon policy builder.",
    ),
    TokenRequirement(
        "tick_execution_baseline",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "daemon_tick_plan_builder",
        "def build_dispatch_execution_daemon_tick_plan",
        "A process loop must plan finite work before executing side effects.",
    ),
    TokenRequirement(
        "tick_execution_baseline",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "daemon_tick_once_executor",
        "def run_dispatch_execution_daemon_tick_once",
        "A process loop must delegate to the bounded tick-once executor.",
    ),
    TokenRequirement(
        "tick_execution_baseline",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "daemon_tick_event_builder",
        "def build_dispatch_execution_daemon_tick_event",
        "Process lifecycle observability should align with the tick event contract.",
    ),
    TokenRequirement(
        "operations_baseline",
        "services/nex-ag/nex_ag/operations.py",
        "runtime_projection",
        "def build_operator_review_escalation_dispatch_daemon_runtime_projection",
        "Process state must remain visible through the existing runtime projection.",
    ),
    TokenRequirement(
        "operations_baseline",
        "services/nex-ag/nex_ag/operations.py",
        "control_history_route",
        "/admin/v1/operator-review/dispatch-daemon/controls",
        "Process control evidence should stay connected to the protected controls route.",
    ),
    TokenRequirement(
        "operations_baseline",
        "services/nex-ag/nex_ag/operations.py",
        "control_history_operation",
        "listAgOperatorReviewDispatchDaemonControls",
        "OpenAPI/runtime route parity is the baseline for future process controls.",
    ),
    TokenRequirement(
        "operational_event_foundation",
        "services/_shared/nex_runtime/operational_events.py",
        "operational_event_emitter",
        "class OperationalEventEmitter",
        "Process lifecycle events should reuse the shared operational event emitter.",
    ),
    TokenRequirement(
        "operational_event_foundation",
        "services/_shared/nex_runtime/operational_events.py",
        "sqlalchemy_event_store",
        "class SqlAlchemyOperationalEventStore",
        "PostgreSQL process evidence should reuse the shared event store.",
    ),
    TokenRequirement(
        "heartbeat_foundation",
        "services/_shared/nex_runtime/worker_heartbeats.py",
        "worker_heartbeat_store",
        "class WorkerHeartbeatStore",
        "Process liveness should reuse shared heartbeat semantics before new tables.",
    ),
    TokenRequirement(
        "heartbeat_foundation",
        "services/_shared/nex_runtime/worker_heartbeats.py",
        "sqlalchemy_worker_heartbeat_store",
        "class SqlAlchemyWorkerHeartbeatStore",
        "The real PostgreSQL smoke path already has a shared heartbeat adapter.",
    ),
    TokenRequirement(
        "heartbeat_foundation",
        "services/_shared/nex_runtime/worker_heartbeats.py",
        "worker_heartbeat_emitter",
        "class WorkerHeartbeatEmitter",
        "Daemon process liveness emission should stay optional and explicit.",
    ),
    TokenRequirement(
        "quality_gate",
        "scripts/quality/run_quality_gate.sh",
        "s77_closure_quality_gate",
        "run_s77_operator_review_escalation_dispatch_daemon_operations_closure.py",
        "The S77 closure remains in the default quality gate.",
    ),
    TokenRequirement(
        "quality_gate",
        "scripts/quality/run_quality_gate.sh",
        "s78_boundary_quality_gate",
        "run_ag_operator_review_escalation_dispatch_daemon_process_boundary_audit.py",
        "Slice 0771 audit must run in the default quality gate.",
    ),
    TokenRequirement(
        "docs_index",
        "docs/README.md",
        "slice_0771_indexed",
        "0771_ag_escalation_dispatch_daemon_process_boundary_audit.md",
        "Slice 0771 documentation must be indexed.",
    ),
)

TABLE_NAMES_UNDER_REVIEW = (
    SOURCE_DISPATCH_TABLE,
    SOURCE_EVENT_TABLE,
)

NEXT_SLICES = (
    "Slice_0772",
    "Slice_0773",
    "Slice_0774",
    "Slice_0775",
    "Slice_0776",
    "Slice_0777",
    "Slice_0778",
    "Slice_0779",
    "Slice_0780",
)


def run_ag_operator_review_escalation_dispatch_daemon_process_boundary_audit(
    root: Path = ROOT,
) -> dict[str, Any]:
    paths = _required_path_results(root)
    tokens = _token_results(root)
    table_names = _table_name_results()
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "required_tokens_present": all(item["present"] for item in tokens),
        "table_names_within_limit": all(item["within_limit"] for item in table_names),
        "s77_closed_baseline_present": _group_present(tokens, "s77_closed_baseline"),
        "tick_execution_baseline_present": _group_present(
            tokens,
            "tick_execution_baseline",
        ),
        "operations_baseline_present": _group_present(tokens, "operations_baseline"),
        "operational_event_foundation_present": _group_present(
            tokens,
            "operational_event_foundation",
        ),
        "heartbeat_foundation_present": _group_present(
            tokens,
            "heartbeat_foundation",
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
        else "ag_operator_review_escalation_dispatch_daemon_process_boundary_failed",
        "slice": SLICE_ID,
        "surface": S78_SURFACE,
        "boundary": {
            "boundary": BOUNDARY,
            "source_dispatch_table": SOURCE_DISPATCH_TABLE,
            "source_event_table": SOURCE_EVENT_TABLE,
            "new_table_in_slice_0771": False,
            "daemon_loop_implementation_in_slice_0771": False,
            "subprocess_execution_in_slice_0771": False,
            "protected_process_control_route_in_slice_0771": False,
            "dashboard_mutation_in_slice_0771": False,
            "first_runtime_loop_policy_slice": "Slice_0772",
            "first_process_metadata_contract_slice": "Slice_0773",
            "first_executable_cli_slice": "Slice_0774",
            "first_lifecycle_event_persistence_slice": "Slice_0775",
            "first_protected_process_control_api_slice": "Slice_0776",
            "first_process_dashboard_slice": "Slice_0777",
            "postgres_smoke_slice": "Slice_0778",
            "privacy_runbook_slice": "Slice_0779",
            "closure_slice": "Slice_0780",
            "real_external_endpoint_delivery": "deferred_until_full_system",
        },
        "process_contract": {
            "daemon_loop": {
                "owner": "nex-ag",
                "entrypoint": "future_executable_cli",
                "tick_executor": "run_dispatch_execution_daemon_tick_once",
                "new_table_required": False,
                "mutation_in_slice_0771": False,
            },
            "process_state": {
                "primary_source": "service_operational_events",
                "liveness_source": "service_worker_heartbeats",
                "worker_heartbeat_reuse": "preferred_before_new_table",
                "new_table_required": False,
            },
            "dispatch_execution": {
                "source_table": SOURCE_DISPATCH_TABLE,
                "executor": "run_dispatch_execution_daemon_tick_once",
                "external_endpoint_delivery": "deferred_until_full_system",
            },
            "operator_control": {
                "protected_api_family": (
                    "/admin/v1/operator-review/dispatch-daemon/controls"
                ),
                "protected_api_reuse": True,
                "start_stop_mutation_in_slice_0771": False,
            },
        },
        "refactoring_checkpoint": {
            "keep_tick_execution_pure": True,
            "isolate_process_loop_from_tick_once_executor": True,
            "keep_cli_thin": True,
            "reuse_operational_event_emitter": True,
            "prefer_worker_heartbeat_store_for_liveness": True,
            "keep_postgres_smoke_real_test_db": True,
            "keep_sensitive_values_redacted": True,
            "avoid_new_table_until_process_query_pressure_is_proven": True,
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
        return (
            "ag_operator_review_escalation_dispatch_daemon_process_boundary=pass "
            f"boundary={boundary['boundary']} "
            f"new_table={boundary['new_table_in_slice_0771']} "
            f"loop_policy={boundary['first_runtime_loop_policy_slice']} "
            f"metadata={boundary['first_process_metadata_contract_slice']} "
            f"cli={boundary['first_executable_cli_slice']} "
            f"source={boundary['source_dispatch_table']}"
        )
    return (
        "ag_operator_review_escalation_dispatch_daemon_process_boundary=fail "
        f"reason={evidence.get('failure_code')} "
        f"issues={len(evidence.get('issues', []))}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the S78 AG operator review escalation dispatch daemon process "
            "boundary audit."
        )
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_ag_operator_review_escalation_dispatch_daemon_process_boundary_audit()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, default=str)
    )
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
