#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = (
    "ag_operator_review_escalation_dispatch_daemon_operations_boundary_audit.v1"
)

SLICE_ID = "0761"
S77_SURFACE = "AG operator review escalation dispatch daemon operations visibility"
BOUNDARY = "ag_owned_operator_review_escalation_dispatch_daemon_operations"
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
        "s76_closure_script",
        "scripts/smoke/run_s76_operator_review_escalation_dispatch_daemon_api_closure.py",
        "S76 protected API closure must be complete before operations visibility.",
    ),
    RequiredPath(
        "s76_closure_doc",
        "docs/slices/0760_s76_operator_review_escalation_dispatch_daemon_api_closure.md",
        "S76 closure documentation.",
    ),
    RequiredPath(
        "ag_operations_runtime",
        "services/nex-ag/nex_ag/operations.py",
        "AG operations routes, dashboard, issue candidates, and API projections.",
    ),
    RequiredPath(
        "dispatch_execution_runtime",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "Daemon policy, control admission, tick planning, and execution runtime.",
    ),
    RequiredPath(
        "operational_event_runtime",
        "services/_shared/nex_runtime/operational_events.py",
        "Shared operational event emitter and stores.",
    ),
    RequiredPath(
        "api_postgres_smoke",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_api_postgres_smoke.py",
        "Protected nex_ag_test S76 API smoke baseline.",
    ),
    RequiredPath(
        "api_privacy_regression",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_api_privacy_regression.py",
        "S76 route privacy baseline.",
    ),
    RequiredPath(
        "api_runbook_evidence",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_api_runbook_evidence.py",
        "S76 route/runbook evidence baseline.",
    ),
    RequiredPath(
        "api_admission_guard",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_api_admission_guard_evidence.py",
        "S76 admission and mutation-boundary evidence baseline.",
    ),
    RequiredPath(
        "quality_gate",
        "scripts/quality/run_quality_gate.sh",
        "Default regression gate.",
    ),
    RequiredPath("docs_index", "docs/README.md", "Slice documentation index."),
    RequiredPath(
        "slice_doc",
        "docs/slices/0761_ag_escalation_dispatch_daemon_operations_boundary_audit.md",
        "Slice 0761 implementation note.",
    ),
)

TOKEN_REQUIREMENTS = (
    TokenRequirement(
        "s76_closed_baseline",
        "scripts/smoke/run_s76_operator_review_escalation_dispatch_daemon_api_closure.py",
        "s76_closure_schema",
        "s76_operator_review_escalation_dispatch_daemon_api_closure.v1",
        "Operations visibility starts after S76 protected API closure.",
    ),
    TokenRequirement(
        "s76_closed_baseline",
        "scripts/smoke/run_s76_operator_review_escalation_dispatch_daemon_api_closure.py",
        "confirmed_tick_once_admission",
        "service_token_auth_plus_confirmed_tick_once_admission",
        "S77 must keep protected tick-once admission unchanged.",
    ),
    TokenRequirement(
        "s76_closed_baseline",
        "scripts/smoke/run_s76_operator_review_escalation_dispatch_daemon_api_closure.py",
        "no_new_tables_in_s76",
        '"new_tables": []',
        "S77 should begin from the no-new-table S76 baseline.",
    ),
    TokenRequirement(
        "api_surface_baseline",
        "services/nex-ag/nex_ag/operations.py",
        "tick_plan_path",
        "/admin/v1/operator-review/dispatch-daemon/tick-plan",
        "Operations visibility must reference the protected tick-plan API.",
    ),
    TokenRequirement(
        "api_surface_baseline",
        "services/nex-ag/nex_ag/operations.py",
        "tick_once_path",
        "/admin/v1/operator-review/dispatch-daemon/tick-once",
        "Operations visibility must reference the protected tick-once API.",
    ),
    TokenRequirement(
        "api_surface_baseline",
        "services/nex-ag/nex_ag/operations.py",
        "runtime_projection",
        "build_operator_review_escalation_dispatch_daemon_runtime_projection",
        "S77 should reuse the existing daemon runtime projection.",
    ),
    TokenRequirement(
        "control_runtime_baseline",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "control_request_builder",
        "def build_dispatch_execution_daemon_control_request",
        "Control history must derive from the safe normalized request.",
    ),
    TokenRequirement(
        "control_runtime_baseline",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "control_admission_builder",
        "def build_dispatch_execution_daemon_control_admission",
        "Control history must capture admission result, not raw payloads.",
    ),
    TokenRequirement(
        "control_runtime_baseline",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "tick_once_executor",
        "def run_dispatch_execution_daemon_tick_once",
        "Operations visibility must not bypass the bounded tick-once executor.",
    ),
    TokenRequirement(
        "operational_event_foundation",
        "services/_shared/nex_runtime/operational_events.py",
        "operational_event_emitter",
        "class OperationalEventEmitter",
        "S77 audit events should reuse the shared emitter.",
    ),
    TokenRequirement(
        "operational_event_foundation",
        "services/_shared/nex_runtime/operational_events.py",
        "operational_event_builder",
        "def build_operational_event",
        "S77 audit events should reuse the shared event contract.",
    ),
    TokenRequirement(
        "operational_event_foundation",
        "services/_shared/nex_runtime/operational_events.py",
        "sqlalchemy_event_store",
        "class SqlAlchemyOperationalEventStore",
        "PostgreSQL smoke should use the shared event persistence adapter.",
    ),
    TokenRequirement(
        "operations_visibility_baseline",
        "services/nex-ag/nex_ag/operations.py",
        "dashboard_projection",
        "def build_operations_dashboard_snapshot_projection",
        "S77 dashboard integration should extend the existing dashboard builder.",
    ),
    TokenRequirement(
        "operations_visibility_baseline",
        "services/nex-ag/nex_ag/operations.py",
        "issue_candidate_projection",
        "def build_operations_issue_candidate_projection",
        "S77 attention signals should extend the existing issue candidate builder.",
    ),
    TokenRequirement(
        "postgres_baseline",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_api_postgres_smoke.py",
        "api_postgres_smoke_env",
        "NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_DAEMON_API_POSTGRES_SMOKE",
        "S77 PostgreSQL smoke should remain opt-in and use the real test DB.",
    ),
    TokenRequirement(
        "postgres_baseline",
        "docs/slices/0754_ag_escalation_dispatch_daemon_api_postgres_smoke.md",
        "real_test_db_doc",
        "nex_ag_test",
        "S77 smoke documentation should keep the real test DB expectation.",
    ),
    TokenRequirement(
        "privacy_baseline",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_api_privacy_regression.py",
        "privacy_raw_fields_absent",
        "raw_fields_absent",
        "Operations views must not reintroduce raw or secret fields.",
    ),
    TokenRequirement(
        "runbook_baseline",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_api_runbook_evidence.py",
        "runtime_routes_ready",
        "runtime_routes_ready",
        "S77 runbooks should refer to the runtime API surface.",
    ),
    TokenRequirement(
        "admission_baseline",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_api_admission_guard_evidence.py",
        "mutation_only_confirmed",
        "mutation_only_confirmed",
        "Operations history must distinguish rejected, dry-run, and confirmed controls.",
    ),
    TokenRequirement(
        "quality_gate",
        "scripts/quality/run_quality_gate.sh",
        "s76_closure_quality_gate",
        "run_s76_operator_review_escalation_dispatch_daemon_api_closure.py",
        "S76 closure remains in the default quality gate.",
    ),
    TokenRequirement(
        "quality_gate",
        "scripts/quality/run_quality_gate.sh",
        "s77_boundary_quality_gate",
        "run_ag_operator_review_escalation_dispatch_daemon_operations_boundary_audit.py",
        "Slice 0761 audit must run in the default quality gate.",
    ),
)

TABLE_NAMES_UNDER_REVIEW = (
    SOURCE_TABLE,
)

NEXT_SLICES = (
    "Slice_0762",
    "Slice_0763",
    "Slice_0764",
    "Slice_0765",
    "Slice_0766",
    "Slice_0767",
    "Slice_0768",
    "Slice_0769",
    "Slice_0770",
)


def run_ag_operator_review_escalation_dispatch_daemon_operations_boundary_audit(
    root: Path = ROOT,
) -> dict[str, Any]:
    paths = _required_path_results(root)
    tokens = _token_results(root)
    table_names = _table_name_results()
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "required_tokens_present": all(item["present"] for item in tokens),
        "table_names_within_limit": all(item["within_limit"] for item in table_names),
        "s76_closed_baseline_present": _group_present(tokens, "s76_closed_baseline"),
        "api_surface_baseline_present": _group_present(tokens, "api_surface_baseline"),
        "control_runtime_baseline_present": _group_present(
            tokens,
            "control_runtime_baseline",
        ),
        "operational_event_foundation_present": _group_present(
            tokens,
            "operational_event_foundation",
        ),
        "operations_visibility_baseline_present": _group_present(
            tokens,
            "operations_visibility_baseline",
        ),
        "postgres_baseline_present": _group_present(tokens, "postgres_baseline"),
        "privacy_baseline_present": _group_present(tokens, "privacy_baseline"),
        "runbook_baseline_present": _group_present(tokens, "runbook_baseline"),
        "admission_baseline_present": _group_present(tokens, "admission_baseline"),
        "quality_gate_present": _group_present(tokens, "quality_gate"),
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "status": "PASS" if passed else "FAIL",
        "failure_code": None
        if passed
        else "ag_operator_review_escalation_dispatch_daemon_operations_boundary_failed",
        "slice": SLICE_ID,
        "surface": S77_SURFACE,
        "boundary": {
            "boundary": BOUNDARY,
            "source_dispatch_table": SOURCE_TABLE,
            "new_table_in_slice_0761": False,
            "route_implementation_in_slice_0761": False,
            "dashboard_mutation_in_slice_0761": False,
            "background_loop_in_slice_0761": False,
            "first_audit_event_slice": "Slice_0762",
            "first_control_history_read_model_slice": "Slice_0763",
            "first_control_history_route_slice": "Slice_0764",
            "first_dashboard_integration_slice": "Slice_0765",
            "first_issue_candidate_slice": "Slice_0766",
            "contract_openapi_slice": "Slice_0767",
            "postgres_smoke_slice": "Slice_0768",
            "privacy_runbook_slice": "Slice_0769",
            "closure_slice": "Slice_0770",
            "real_external_endpoint_delivery": "deferred_until_full_system",
        },
        "operations_contract": {
            "control_audit_event": {
                "owner": "nex-ag",
                "store": "OperationalEventStore",
                "persistence_adapter": "SqlAlchemyOperationalEventStore",
                "raw_request_payloads_allowed": False,
                "raw_provider_payloads_allowed": False,
            },
            "control_history": {
                "route_family": "/admin/v1/operator-review/dispatch-daemon/controls",
                "read_only": True,
                "source": "operational_events_plus_dispatch_metadata",
                "new_table_required": False,
            },
            "dashboard": {
                "source": "build_operations_dashboard_snapshot_projection",
                "section": "operator_review_escalation_dispatch_daemon",
                "mutation": False,
            },
            "issue_candidates": {
                "source": "build_operations_issue_candidate_projection",
                "candidate_family": (
                    "operator_review_escalation_dispatch_daemon_attention"
                ),
                "mutation": False,
            },
        },
        "refactoring_checkpoint": {
            "keep_route_handlers_thin": True,
            "extract_control_event_builder_before_route_wiring": True,
            "reuse_operational_event_emitter": True,
            "reuse_existing_dashboard_projection": True,
            "reuse_existing_issue_candidate_projection": True,
            "keep_history_read_model_query_pure": True,
            "keep_postgres_smoke_real_test_db": True,
            "keep_sensitive_values_redacted": True,
            "avoid_new_table_until_query_pressure_is_proven": True,
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
            "ag_operator_review_escalation_dispatch_daemon_operations_boundary=pass "
            f"boundary={boundary['boundary']} "
            f"new_table={boundary['new_table_in_slice_0761']} "
            f"audit_event={boundary['first_audit_event_slice']} "
            f"history={boundary['first_control_history_read_model_slice']} "
            f"dashboard={boundary['first_dashboard_integration_slice']} "
            f"source={boundary['source_dispatch_table']}"
        )
    return (
        "ag_operator_review_escalation_dispatch_daemon_operations_boundary=fail "
        f"reason={evidence.get('failure_code')} "
        f"issues={len(evidence.get('issues', []))}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the S77 AG operator review escalation dispatch daemon operations "
            "boundary audit."
        )
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = (
        run_ag_operator_review_escalation_dispatch_daemon_operations_boundary_audit()
    )
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, default=str)
    )
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
