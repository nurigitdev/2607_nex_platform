#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = (
    "ag_operator_review_escalation_dispatch_daemon_liveness_recovery_boundary_audit.v1"
)

SLICE_ID = "0791"
S80_SURFACE = "AG operator review escalation dispatch daemon liveness recovery planning"
BOUNDARY = "ag_owned_operator_review_escalation_dispatch_daemon_liveness_recovery"
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
        "s79_closure_script",
        "scripts/smoke/run_s79_operator_review_escalation_dispatch_daemon_liveness_closure.py",
        "S79 liveness closure must be complete before recovery planning.",
    ),
    RequiredPath(
        "s79_closure_doc",
        "docs/slices/0790_s79_operator_review_escalation_dispatch_daemon_liveness_closure.md",
        "S79 closure documentation.",
    ),
    RequiredPath(
        "ag_operations_runtime",
        "services/nex-ag/nex_ag/operations.py",
        "AG operations routes, liveness projection, issue candidates, and dashboard.",
    ),
    RequiredPath(
        "dispatch_execution_runtime",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "Daemon process-control request, admission, and projection builders.",
    ),
    RequiredPath(
        "dispatch_daemon_cli",
        "services/nex-ag/nex_ag/operator_review_dispatch_daemon.py",
        "Executable daemon boundary used by later guarded process-control work.",
    ),
    RequiredPath(
        "operational_event_runtime",
        "services/_shared/nex_runtime/operational_events.py",
        "Shared operational event emitter and stores for recovery audit evidence.",
    ),
    RequiredPath(
        "worker_heartbeat_runtime",
        "services/_shared/nex_runtime/worker_heartbeats.py",
        "Shared heartbeat runtime that remains the liveness source.",
    ),
    RequiredPath(
        "quality_gate",
        "scripts/quality/run_quality_gate.sh",
        "Default regression gate.",
    ),
    RequiredPath("docs_index", "docs/README.md", "Slice documentation index."),
    RequiredPath(
        "slice_doc",
        "docs/slices/0791_ag_escalation_dispatch_daemon_liveness_recovery_boundary_audit.md",
        "Slice 0791 implementation note.",
    ),
)


TOKEN_REQUIREMENTS = (
    TokenRequirement(
        "s79_closed_baseline",
        "scripts/smoke/run_s79_operator_review_escalation_dispatch_daemon_liveness_closure.py",
        "s79_closure_schema",
        "s79_operator_review_escalation_dispatch_daemon_liveness_closure.v1",
        "S80 recovery planning starts after S79 liveness closure.",
    ),
    TokenRequirement(
        "s79_closed_baseline",
        "scripts/smoke/run_s79_operator_review_escalation_dispatch_daemon_liveness_closure.py",
        "s79_boundary",
        "ag_owned_operator_review_escalation_dispatch_daemon_liveness",
        "The S79 liveness boundary is the direct predecessor.",
    ),
    TokenRequirement(
        "s79_closed_baseline",
        "scripts/smoke/run_s79_operator_review_escalation_dispatch_daemon_liveness_closure.py",
        "s79_liveness_route",
        "GET /admin/v1/operator-review/dispatch-daemon/liveness",
        "Recovery planning must be derived from the protected liveness route.",
    ),
    TokenRequirement(
        "s79_closed_baseline",
        "scripts/smoke/run_s79_operator_review_escalation_dispatch_daemon_liveness_closure.py",
        "s79_no_new_tables",
        '"new_tables": []',
        "Slice 0791 should inherit the no-new-table S79 baseline.",
    ),
    TokenRequirement(
        "liveness_runtime",
        "services/nex-ag/nex_ag/operations.py",
        "liveness_projection_builder",
        "def build_operator_review_escalation_dispatch_daemon_liveness_projection",
        "Recovery planning must start from the liveness read model.",
    ),
    TokenRequirement(
        "liveness_runtime",
        "services/nex-ag/nex_ag/operations.py",
        "liveness_route_path",
        "/admin/v1/operator-review/dispatch-daemon/liveness",
        "Recovery planning should keep the liveness path as the evidence source.",
    ),
    TokenRequirement(
        "liveness_runtime",
        "services/nex-ag/nex_ag/operations.py",
        "liveness_status_function",
        "def _dispatch_daemon_liveness_status",
        "Recovery actions depend on stable liveness status vocabulary.",
    ),
    TokenRequirement(
        "liveness_runtime",
        "services/nex-ag/nex_ag/operations.py",
        "liveness_attention_rule",
        "operator_review_dispatch_daemon_liveness_attention_required.v1",
        "Recovery planning follows the liveness issue-candidate rule.",
    ),
    TokenRequirement(
        "liveness_runtime",
        "services/nex-ag/nex_ag/operations.py",
        "stale_recommended_action",
        "inspect_stale_dispatch_daemon_heartbeat",
        "Stale heartbeat recovery should begin with inspection, not mutation.",
    ),
    TokenRequirement(
        "liveness_runtime",
        "services/nex-ag/nex_ag/operations.py",
        "missing_recommended_action",
        "start_or_inspect_dispatch_daemon_process",
        "Missing heartbeat recovery needs guarded process-control planning.",
    ),
    TokenRequirement(
        "process_control_runtime",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "process_control_request_builder",
        "def build_dispatch_execution_daemon_process_control_request",
        "Recovery planning may reference normalized process-control requests.",
    ),
    TokenRequirement(
        "process_control_runtime",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "process_control_admission_builder",
        "def build_dispatch_execution_daemon_process_control_admission",
        "Recovery planning must preserve protected admission before mutation.",
    ),
    TokenRequirement(
        "process_control_runtime",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "process_control_projection_builder",
        "def build_dispatch_execution_daemon_process_control_projection",
        "Recovery planning can later wrap the existing process-control projection.",
    ),
    TokenRequirement(
        "process_control_runtime",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "contract_only_mutation_mode",
        '"mutation_mode": "contract_only_no_subprocess"',
        "Slice 0791 keeps recovery planning contract-only.",
    ),
    TokenRequirement(
        "process_control_runtime",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "no_subprocess_mutation_performed",
        '"subprocess_mutation_performed": False',
        "Recovery planning must not perform daemon subprocess mutation.",
    ),
    TokenRequirement(
        "process_control_route",
        "services/nex-ag/nex_ag/operations.py",
        "process_control_route_path",
        "/admin/v1/operator-review/dispatch-daemon/process-controls",
        "Recovery planning should reference the existing protected process-control route.",
    ),
    TokenRequirement(
        "process_control_route",
        "services/nex-ag/nex_ag/operations.py",
        "process_control_route_builder",
        "build_operator_review_escalation_dispatch_daemon_process_control_api_projection",
        "Recovery planning should reuse the existing process-control API projection.",
    ),
    TokenRequirement(
        "control_history",
        "services/nex-ag/nex_ag/operations.py",
        "control_history_builder",
        "def build_operator_review_escalation_dispatch_daemon_control_history_projection",
        "Recovery evidence should correlate with existing control history.",
    ),
    TokenRequirement(
        "control_history",
        "services/nex-ag/nex_ag/operations.py",
        "control_history_route_path",
        "/admin/v1/operator-review/dispatch-daemon/controls",
        "Recovery evidence should not invent a separate control history source.",
    ),
    TokenRequirement(
        "operational_event_foundation",
        "services/_shared/nex_runtime/operational_events.py",
        "operational_event_emitter",
        "class OperationalEventEmitter",
        "Recovery audit evidence should reuse shared operational events.",
    ),
    TokenRequirement(
        "heartbeat_runtime",
        "services/_shared/nex_runtime/worker_heartbeats.py",
        "heartbeat_source_store",
        "class SqlAlchemyWorkerHeartbeatStore",
        "Recovery planning keeps heartbeat persistence as the liveness source.",
    ),
    TokenRequirement(
        "quality_gate",
        "scripts/quality/run_quality_gate.sh",
        "s79_closure_quality_gate",
        "run_s79_operator_review_escalation_dispatch_daemon_liveness_closure.py",
        "S79 closure remains in the default quality gate.",
    ),
    TokenRequirement(
        "quality_gate",
        "scripts/quality/run_quality_gate.sh",
        "s80_boundary_quality_gate",
        "run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_boundary_audit.py",
        "Slice 0791 audit must run in the default quality gate.",
    ),
    TokenRequirement(
        "docs_index",
        "docs/README.md",
        "slice_0791_indexed",
        "0791_ag_escalation_dispatch_daemon_liveness_recovery_boundary_audit.md",
        "Slice 0791 documentation must be indexed.",
    ),
)


TABLE_NAMES_UNDER_REVIEW = (
    SOURCE_DISPATCH_TABLE,
    SOURCE_EVENT_TABLE,
    SOURCE_HEARTBEAT_TABLE,
)

NEXT_SLICES = (
    "Slice_0792",
    "Slice_0793",
    "Slice_0794",
    "Slice_0795",
    "Slice_0796",
    "Slice_0797",
    "Slice_0798",
    "Slice_0799",
    "Slice_0800",
)


def run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_boundary_audit(
    root: Path = ROOT,
) -> dict[str, Any]:
    paths = _required_path_results(root)
    tokens = _token_results(root)
    table_names = _table_name_results()
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "required_tokens_present": all(item["present"] for item in tokens),
        "table_names_within_limit": all(item["within_limit"] for item in table_names),
        "s79_closed_baseline_present": _group_present(tokens, "s79_closed_baseline"),
        "liveness_runtime_present": _group_present(tokens, "liveness_runtime"),
        "process_control_runtime_present": _group_present(
            tokens,
            "process_control_runtime",
        ),
        "process_control_route_present": _group_present(tokens, "process_control_route"),
        "control_history_present": _group_present(tokens, "control_history"),
        "operational_event_foundation_present": _group_present(
            tokens,
            "operational_event_foundation",
        ),
        "heartbeat_runtime_present": _group_present(tokens, "heartbeat_runtime"),
        "quality_gate_present": _group_present(tokens, "quality_gate"),
        "docs_index_present": _group_present(tokens, "docs_index"),
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "status": "PASS" if passed else "FAIL",
        "failure_code": None
        if passed
        else (
            "ag_operator_review_escalation_dispatch_daemon_"
            "liveness_recovery_boundary_failed"
        ),
        "slice": SLICE_ID,
        "surface": S80_SURFACE,
        "boundary": {
            "boundary": BOUNDARY,
            "source_dispatch_table": SOURCE_DISPATCH_TABLE,
            "source_event_table": SOURCE_EVENT_TABLE,
            "source_heartbeat_table": SOURCE_HEARTBEAT_TABLE,
            "new_table_in_slice_0791": False,
            "recovery_plan_route_in_slice_0791": False,
            "recovery_plan_mutation_in_slice_0791": False,
            "subprocess_mutation_in_slice_0791": False,
            "first_recovery_action_plan_slice": "Slice_0792",
            "first_protected_recovery_plan_route_slice": "Slice_0793",
            "first_recovery_audit_event_slice": "Slice_0794",
            "first_dashboard_recovery_integration_slice": "Slice_0795",
            "first_ack_suppression_policy_slice": "Slice_0796",
            "postgres_smoke_slice": "Slice_0797",
            "privacy_runbook_slice": "Slice_0798",
            "contract_openapi_slice": "Slice_0799",
            "closure_slice": "Slice_0800",
        },
        "recovery_contract": {
            "owner_service": "nex-ag",
            "liveness_source": SOURCE_HEARTBEAT_TABLE,
            "dispatch_source": SOURCE_DISPATCH_TABLE,
            "audit_source": SOURCE_EVENT_TABLE,
            "existing_liveness_route": (
                "GET /admin/v1/operator-review/dispatch-daemon/liveness"
            ),
            "existing_process_control_route": (
                "POST /admin/v1/operator-review/dispatch-daemon/process-controls"
            ),
            "planned_recovery_plan_route": (
                "GET /admin/v1/operator-review/dispatch-daemon/liveness/recovery-plan"
            ),
            "planned_route_mutation": False,
            "subprocess_mutation_allowed": False,
            "supported_liveness_inputs": [
                "FRESH",
                "MISSING",
                "STALE",
                "SOURCE_NOT_CONFIGURED",
                "SOURCE_UNAVAILABLE",
            ],
            "initial_recovery_actions": {
                "STALE": ["inspect_stale_dispatch_daemon_heartbeat"],
                "MISSING": ["start_or_inspect_dispatch_daemon_process"],
                "SOURCE_NOT_CONFIGURED": ["configure_dispatch_daemon_heartbeat_store"],
                "SOURCE_UNAVAILABLE": ["inspect_dispatch_daemon_heartbeat_store"],
                "FRESH": [],
            },
        },
        "separation_of_concerns": {
            "liveness_status": "derived_from_service_worker_heartbeats",
            "issue_candidate": "derived_from_liveness_projection_when_daemon_enabled",
            "recovery_plan": "pure_read_model_before_any_control_mutation",
            "process_control": "existing_contract_only_guarded_projection",
            "audit_events": "service_operational_events_safe_summary_only",
            "acknowledgement_suppression": "deferred_to_slice_0796",
        },
        "refactoring_checkpoint": {
            "reuse_s79_liveness_projection": True,
            "reuse_s78_process_control_projection": True,
            "keep_recovery_plan_pure_and_read_only": True,
            "keep_route_handlers_thin": True,
            "emit_recovery_audit_after_contract_freeze": True,
            "avoid_new_table_until_ack_suppression_policy_is_defined": True,
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
        contract = evidence["recovery_contract"]
        return (
            "ag_operator_review_escalation_dispatch_daemon_"
            "liveness_recovery_boundary=pass "
            f"boundary={boundary['boundary']} "
            f"new_table={boundary['new_table_in_slice_0791']} "
            f"mutation={boundary['recovery_plan_mutation_in_slice_0791']} "
            f"liveness_source={contract['liveness_source']} "
            f"plan={boundary['first_recovery_action_plan_slice']} "
            f"route={boundary['first_protected_recovery_plan_route_slice']}"
        )
    return (
        "ag_operator_review_escalation_dispatch_daemon_"
        "liveness_recovery_boundary=fail "
        f"reason={evidence.get('failure_code')} "
        f"issues={len(evidence.get('issues', []))}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the S80 AG operator review escalation dispatch daemon liveness "
            "recovery boundary audit."
        )
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = (
        run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_boundary_audit()
    )
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, default=str)
    )
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
