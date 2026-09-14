#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = (
    "ag_operator_review_escalation_dispatch_daemon_boundary_audit.v1"
)

SLICE_ID = "0741"
S75_SURFACE = "AG operator review escalation dispatch execution daemon readiness"
BOUNDARY = "ag_owned_operator_review_escalation_dispatch_execution_daemon"
SOURCE_TABLE = "ag_op_esc_dispatches"
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
        "s74_closure_script",
        "scripts/smoke/run_s74_operator_review_escalation_dispatch_live_http_closure.py",
        "S74 live HTTP transport must be closed before daemon readiness.",
    ),
    RequiredPath(
        "s74_closure_doc",
        "docs/slices/0740_s74_operator_review_escalation_dispatch_live_http_closure.md",
        "S74 closure documentation.",
    ),
    RequiredPath(
        "s72_worker_boundary",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_execution_worker_boundary_audit.py",
        "Original bounded run-once worker boundary.",
    ),
    RequiredPath(
        "dispatch_execution_runtime",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "Run-once worker, provider router, transition planning, and result metadata.",
    ),
    RequiredPath(
        "ag_operations",
        "services/nex-ag/nex_ag/operations.py",
        "Operations dashboard visibility for dispatch execution.",
    ),
    RequiredPath(
        "operations_schema",
        "contracts/schemas/service/nex_ag/operations_projection.v1.schema.json",
        "Operations dashboard contract.",
    ),
    RequiredPath(
        "live_http_postgres_smoke",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_live_http_postgres_smoke.py",
        "Protected nex_ag_test live HTTP loopback persistence smoke.",
    ),
    RequiredPath(
        "quality_gate",
        "scripts/quality/run_quality_gate.sh",
        "Default regression gate.",
    ),
    RequiredPath("docs_index", "docs/README.md", "Slice documentation index."),
    RequiredPath("ag_readme", "services/nex-ag/README.md", "AG implementation notes."),
    RequiredPath(
        "slice_doc",
        "docs/slices/0741_ag_escalation_dispatch_daemon_boundary_audit.md",
        "Slice 0741 implementation note.",
    ),
)

TOKEN_REQUIREMENTS = (
    TokenRequirement(
        "s74_closed_baseline",
        "scripts/smoke/run_s74_operator_review_escalation_dispatch_live_http_closure.py",
        "s74_closure_schema",
        "s74_operator_review_escalation_dispatch_live_http_closure.v1",
        "Daemon readiness starts after S74 closure.",
    ),
    TokenRequirement(
        "s74_closed_baseline",
        "scripts/smoke/run_s74_operator_review_escalation_dispatch_live_http_closure.py",
        "real_endpoint_deferred",
        "deferred_until_full_system",
        "S75 must not accidentally promote real external endpoint delivery.",
    ),
    TokenRequirement(
        "s72_worker_boundary",
        "docs/slices/0716_ag_escalation_dispatch_execution_worker_run_once.md",
        "run_once_not_daemon",
        "does not introduce a daemon loop",
        "Daemon work must explicitly move beyond the bounded run-once baseline.",
    ),
    TokenRequirement(
        "worker_runtime",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "worker_run_schema",
        "ag_operator_review_escalation_dispatch_execution_worker_run.v1",
        "Daemon ticks must reuse the worker run result contract.",
    ),
    TokenRequirement(
        "worker_runtime",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "run_once_worker",
        "def run_dispatch_execution_worker_once",
        "Daemon ticks should invoke the bounded run-once worker.",
    ),
    TokenRequirement(
        "worker_runtime",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "confirm_guard",
        "confirm_run_required",
        "Execution must remain explicit and guardrailed.",
    ),
    TokenRequirement(
        "worker_runtime",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "dry_run_support",
        "dry_run",
        "Daemon planning must support non-mutating dry-runs.",
    ),
    TokenRequirement(
        "worker_runtime",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "batch_limit_guard",
        "MAX_DISPATCH_EXECUTION_BATCH_LIMIT",
        "Daemon cycles must remain bounded.",
    ),
    TokenRequirement(
        "worker_runtime",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "candidate_selector",
        "def _worker_candidate_dispatches",
        "Daemon ticks must use a centralized eligible-dispatch selector.",
    ),
    TokenRequirement(
        "worker_runtime",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "provider_router",
        "def execute_dispatch_with_provider_router",
        "Provider routing must remain centralized.",
    ),
    TokenRequirement(
        "worker_runtime",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "live_http_transport_injection",
        "live_http_transport",
        "Live HTTP execution must remain injected and opt-in.",
    ),
    TokenRequirement(
        "worker_runtime",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "metadata_persistence",
        "def _persist_worker_result_metadata",
        "Daemon ticks must persist only safe worker result metadata.",
    ),
    TokenRequirement(
        "operations_visibility",
        "services/nex-ag/nex_ag/operations.py",
        "execution_summary",
        "execution_summary",
        "Daemon results must stay visible through AG operations.",
    ),
    TokenRequirement(
        "operations_visibility",
        "services/nex-ag/nex_ag/operations.py",
        "attempt_diagnostics",
        "attempt_count_total",
        "S75 must keep attempt diagnostics visible.",
    ),
    TokenRequirement(
        "operations_contract",
        "contracts/schemas/service/nex_ag/operations_projection.v1.schema.json",
        "provider_mode_summary_schema",
        "by_provider_mode",
        "Operations schema must include live/mock mode diagnostics.",
    ),
    TokenRequirement(
        "postgres_baseline",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_live_http_postgres_smoke.py",
        "postgres_smoke_env",
        "NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_LIVE_HTTP_POSTGRES_SMOKE",
        "S75 must keep protected nex_ag_test evidence.",
    ),
    TokenRequirement(
        "quality_gate",
        "scripts/quality/run_quality_gate.sh",
        "s74_closure_quality_gate",
        "run_s74_operator_review_escalation_dispatch_live_http_closure.py",
        "S74 closure remains in the default quality gate.",
    ),
    TokenRequirement(
        "quality_gate",
        "scripts/quality/run_quality_gate.sh",
        "s75_boundary_quality_gate",
        "run_ag_operator_review_escalation_dispatch_daemon_boundary_audit.py",
        "Slice 0741 audit must run in the default quality gate.",
    ),
)

TABLE_NAMES_UNDER_REVIEW = (
    SOURCE_TABLE,
)

NEXT_SLICES = (
    "Slice_0742",
    "Slice_0743",
    "Slice_0744",
    "Slice_0745",
    "Slice_0746",
    "Slice_0747",
    "Slice_0748",
    "Slice_0749",
    "Slice_0750",
)


def run_ag_operator_review_escalation_dispatch_daemon_boundary_audit(
    root: Path = ROOT,
) -> dict[str, Any]:
    paths = _required_path_results(root)
    tokens = _token_results(root)
    table_name_results = _table_name_results()
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "required_tokens_present": all(item["present"] for item in tokens),
        "table_names_within_limit": all(
            item["within_limit"] for item in table_name_results
        ),
        "s74_closed_baseline_present": _group_present(tokens, "s74_closed_baseline"),
        "s72_worker_boundary_present": _group_present(tokens, "s72_worker_boundary"),
        "worker_runtime_present": _group_present(tokens, "worker_runtime"),
        "operations_visibility_present": _group_present(tokens, "operations_visibility"),
        "operations_contract_present": _group_present(tokens, "operations_contract"),
        "postgres_baseline_present": _group_present(tokens, "postgres_baseline"),
        "quality_gate_present": _group_present(tokens, "quality_gate"),
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "status": "PASS" if passed else "FAIL",
        "failure_code": None
        if passed
        else "ag_operator_review_escalation_dispatch_daemon_boundary_failed",
        "slice": SLICE_ID,
        "surface": S75_SURFACE,
        "boundary": _boundary(),
        "refactoring_checkpoint": _refactoring_checkpoint(),
        "paths": paths,
        "source_tokens": tokens,
        "table_name_results": table_name_results,
        "checks": checks,
        "next_slices": list(NEXT_SLICES),
        "issues": _issues(paths, tokens, table_name_results),
    }


def _boundary() -> dict[str, Any]:
    return {
        "boundary": BOUNDARY,
        "source_dispatch_table": SOURCE_TABLE,
        "create_table_in_slice_0741": False,
        "daemon_loop_in_slice_0741": False,
        "background_process_in_slice_0741": False,
        "real_external_endpoint_delivery": "deferred_until_full_system",
        "execution_source_of_record": "ag_op_esc_dispatches",
        "first_policy_slice": "Slice_0742",
        "first_tick_plan_slice": "Slice_0743",
        "first_tick_execution_slice": "Slice_0744",
        "first_postgres_tick_smoke_slice": "Slice_0748",
        "allowed_execution_modes_now": [
            "confirmed_run_once",
            "dry_run",
            "injected_loopback_live_http",
        ],
        "future_daemon_requires": [
            "bounded_cycle_limit",
            "explicit_confirm_or_protected_operator_control",
            "dry_run_plan_before_mutation",
            "central_worker_candidate_selector",
            "state_machine_only_mutations",
            "safe_operational_events_and_service_logs",
            "no_raw_headers_tokens_payloads_or_idempotency_keys",
        ],
        "job_queue_decision": "defer_until_control_api_slice",
        "result_storage": "ag_op_esc_dispatches.metadata.last_execution_result",
    }


def _refactoring_checkpoint() -> dict[str, Any]:
    return {
        "reuse_run_dispatch_execution_worker_once": True,
        "keep_worker_candidate_selection_centralized": True,
        "keep_dispatch_mutations_in_state_machine": True,
        "keep_live_http_transport_injected": True,
        "require_explicit_confirmation": True,
        "support_dry_run_before_execution": True,
        "bound_batch_and_cycle_limits": True,
        "emit_safe_logs_and_events_later": True,
        "avoid_new_table_in_boundary_slice": True,
        "keep_table_names_short": True,
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
            "table": table,
            "length": len(table),
            "within_limit": len(table) <= MAX_TABLE_NAME_LENGTH,
        }
        for table in TABLE_NAMES_UNDER_REVIEW
    ]


def _group_present(items: list[dict[str, Any]], group: str) -> bool:
    group_items = [item for item in items if item["group"] == group]
    return bool(group_items) and all(item["present"] for item in group_items)


def _issues(
    paths: list[dict[str, Any]],
    tokens: list[dict[str, Any]],
    table_names: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    issues.extend(
        {"category": "path_missing", "path": item["path"], "name": item["name"]}
        for item in paths
        if not item["present"]
    )
    issues.extend(
        {
            "category": "source_token_missing",
            "path": item["path"],
            "token_id": item["token_id"],
            "group": item["group"],
        }
        for item in tokens
        if not item["present"]
    )
    issues.extend(
        {
            "category": "table_name_too_long",
            "table": item["table"],
            "length": item["length"],
            "limit": MAX_TABLE_NAME_LENGTH,
        }
        for item in table_names
        if not item["within_limit"]
    )
    return issues


def summary_line(evidence: dict[str, Any]) -> str:
    status = str(evidence.get("status") or "FAIL").lower()
    boundary = evidence.get("boundary") or {}
    if status == "pass":
        return (
            "ag_operator_review_escalation_dispatch_daemon_boundary=pass "
            f"boundary={boundary.get('boundary')} "
            f"daemon_loop={boundary.get('daemon_loop_in_slice_0741')} "
            f"source={boundary.get('execution_source_of_record')} "
            f"next={boundary.get('first_policy_slice')}"
        )
    return (
        "ag_operator_review_escalation_dispatch_daemon_boundary=fail "
        f"failure={evidence.get('failure_code') or 'unknown'} "
        f"issues={len(evidence.get('issues') or [])}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_ag_operator_review_escalation_dispatch_daemon_boundary_audit()
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
