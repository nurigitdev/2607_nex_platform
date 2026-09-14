#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = (
    "ag_operator_review_escalation_dispatch_daemon_api_boundary_audit.v1"
)

SLICE_ID = "0751"
BOUNDARY = "ag_owned_operator_review_escalation_dispatch_daemon_protected_api"
SOURCE_TABLE = "ag_op_esc_dispatches"


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
        "s75_closure_script",
        "scripts/smoke/run_s75_operator_review_escalation_dispatch_daemon_closure.py",
        "S75 daemon foundation must be closed before protected API route work.",
    ),
    RequiredPath(
        "s75_closure_doc",
        "docs/slices/0750_s75_operator_review_escalation_dispatch_daemon_closure.md",
        "S75 closure documentation.",
    ),
    RequiredPath(
        "dispatch_execution_runtime",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "Daemon policy, tick planning, tick execution, control admission.",
    ),
    RequiredPath(
        "ag_operations_runtime",
        "services/nex-ag/nex_ag/operations.py",
        "AG operations routes, auth helpers, and daemon runtime projection.",
    ),
    RequiredPath(
        "daemon_postgres_smoke",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_postgres_smoke.py",
        "Protected nex_ag_test daemon tick loopback smoke.",
    ),
    RequiredPath(
        "daemon_privacy_regression",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_privacy_regression.py",
        "Daemon public surface privacy regression.",
    ),
    RequiredPath(
        "quality_gate",
        "scripts/quality/run_quality_gate.sh",
        "Default regression gate.",
    ),
    RequiredPath("docs_index", "docs/README.md", "Slice documentation index."),
    RequiredPath(
        "slice_doc",
        "docs/slices/0751_ag_escalation_dispatch_daemon_api_boundary_audit.md",
        "Slice 0751 implementation note.",
    ),
)

TOKEN_REQUIREMENTS = (
    TokenRequirement(
        "s75_closed_baseline",
        "scripts/smoke/run_s75_operator_review_escalation_dispatch_daemon_closure.py",
        "s75_closure_schema",
        "s75_operator_review_escalation_dispatch_daemon_closure.v1",
        "Protected API work starts after S75 closure.",
    ),
    TokenRequirement(
        "s75_closed_baseline",
        "scripts/smoke/run_s75_operator_review_escalation_dispatch_daemon_closure.py",
        "bounded_tick_runtime",
        "bounded_confirmed_tick_once_no_background_loop",
        "Route work must not silently introduce a background loop.",
    ),
    TokenRequirement(
        "control_foundation",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "control_actions",
        "ALLOWED_DISPATCH_EXECUTION_DAEMON_CONTROL_ACTIONS",
        "API actions must remain centralized and limited.",
    ),
    TokenRequirement(
        "control_foundation",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "control_request_schema",
        "ag_operator_review_escalation_dispatch_execution_daemon_control_request.v1",
        "Route payloads must be normalized into safe control requests.",
    ),
    TokenRequirement(
        "control_foundation",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "control_admission_schema",
        "ag_operator_review_escalation_dispatch_execution_daemon_control_admission.v1",
        "Route execution must pass control admission.",
    ),
    TokenRequirement(
        "control_foundation",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "control_request_function",
        "def build_dispatch_execution_daemon_control_request",
        "Route handlers should use the safe control request builder.",
    ),
    TokenRequirement(
        "control_foundation",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "control_admission_function",
        "def build_dispatch_execution_daemon_control_admission",
        "Route handlers should use the protected admission builder.",
    ),
    TokenRequirement(
        "control_foundation",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "tick_execution_function",
        "def run_dispatch_execution_daemon_tick_once",
        "Tick-once API must reuse the bounded tick executor.",
    ),
    TokenRequirement(
        "control_foundation",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "confirm_tick_guard",
        "confirm_tick_required",
        "Mutation must require explicit confirmation.",
    ),
    TokenRequirement(
        "operations_api_boundary",
        "services/nex-ag/nex_ag/operations.py",
        "authorization_helper_available",
        "validate_authorization_header",
        "Protected routes should reuse runtime auth validation.",
    ),
    TokenRequirement(
        "operations_api_boundary",
        "services/nex-ag/nex_ag/operations.py",
        "tick_plan_path",
        "/admin/v1/operator-review/dispatch-daemon/tick-plan",
        "Tick-plan API path is reserved as the non-mutating first route.",
    ),
    TokenRequirement(
        "operations_api_boundary",
        "services/nex-ag/nex_ag/operations.py",
        "tick_once_path",
        "/admin/v1/operator-review/dispatch-daemon/tick-once",
        "Tick-once API path is reserved for protected execution.",
    ),
    TokenRequirement(
        "operations_api_boundary",
        "services/nex-ag/nex_ag/operations.py",
        "runtime_projection",
        "build_operator_review_escalation_dispatch_daemon_runtime_projection",
        "AG operations must expose daemon runtime status safely.",
    ),
    TokenRequirement(
        "postgres_baseline",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_postgres_smoke.py",
        "postgres_smoke_env",
        "NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_DAEMON_POSTGRES_SMOKE",
        "Protected API route smoke must build on real test DB evidence.",
    ),
    TokenRequirement(
        "privacy_baseline",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_privacy_regression.py",
        "privacy_forbidden_absent",
        "forbidden_absent",
        "API output must preserve daemon privacy guarantees.",
    ),
    TokenRequirement(
        "quality_gate",
        "scripts/quality/run_quality_gate.sh",
        "s75_closure_quality_gate",
        "run_s75_operator_review_escalation_dispatch_daemon_closure.py",
        "S75 closure must remain in the default quality gate.",
    ),
    TokenRequirement(
        "quality_gate",
        "scripts/quality/run_quality_gate.sh",
        "s75_postgres_quality_gate",
        "run_ag_operator_review_escalation_dispatch_daemon_postgres_smoke.py",
        "S75 PostgreSQL smoke must remain in the default quality gate.",
    ),
    TokenRequirement(
        "quality_gate",
        "scripts/quality/run_quality_gate.sh",
        "s76_api_boundary_quality_gate",
        "run_ag_operator_review_escalation_dispatch_daemon_api_boundary_audit.py",
        "Slice 0751 protected API boundary audit must run in the default quality gate.",
    ),
)

NEXT_SLICES = (
    "Slice_0752",
    "Slice_0753",
    "Slice_0754",
    "Slice_0755",
    "Slice_0756",
    "Slice_0757",
    "Slice_0758",
    "Slice_0759",
    "Slice_0760",
)


def run_ag_operator_review_escalation_dispatch_daemon_api_boundary_audit(
    root: Path = ROOT,
) -> dict[str, Any]:
    paths = _required_path_results(root)
    tokens = _token_results(root)
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "required_tokens_present": all(item["present"] for item in tokens),
        "s75_closed_baseline_present": _group_present(tokens, "s75_closed_baseline"),
        "control_foundation_present": _group_present(tokens, "control_foundation"),
        "operations_api_boundary_present": _group_present(
            tokens,
            "operations_api_boundary",
        ),
        "postgres_baseline_present": _group_present(tokens, "postgres_baseline"),
        "privacy_baseline_present": _group_present(tokens, "privacy_baseline"),
        "quality_gate_present": _group_present(tokens, "quality_gate"),
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "status": "PASS" if passed else "FAIL",
        "failure_code": None
        if passed
        else "ag_operator_review_escalation_dispatch_daemon_api_boundary_failed",
        "slice": SLICE_ID,
        "boundary": {
            "boundary": BOUNDARY,
            "source_dispatch_table": SOURCE_TABLE,
            "route_implementation_in_slice_0751": False,
            "background_loop_in_slice_0751": False,
            "new_table_in_slice_0751": False,
            "first_tick_plan_route_slice": "Slice_0752",
            "first_tick_once_route_slice": "Slice_0753",
            "first_route_postgres_smoke_slice": "Slice_0754",
            "allowed_actions": ["tick_plan", "tick_once"],
            "tick_plan_mutates": False,
            "mutation_allowed_without_confirm": False,
            "tick_once_requires": [
                "authenticated_operator",
                "control_admission_ACCEPTED",
                "daemon_enabled",
                "confirm_tick_true",
                "bounded_batch_limit",
                "dry_run_policy_respected",
            ],
            "auth_boundary": "reuse_nex_runtime_validate_authorization_header",
            "real_external_endpoint_delivery": "deferred_until_full_system",
        },
        "api_surface_contract": {
            "tick_plan_route": {
                "path": "/admin/v1/operator-review/dispatch-daemon/tick-plan",
                "method": "GET_OR_POST",
                "mutation": False,
                "uses": "build_dispatch_execution_daemon_tick_plan",
            },
            "tick_once_route": {
                "path": "/admin/v1/operator-review/dispatch-daemon/tick-once",
                "method": "POST",
                "mutation": True,
                "uses": "build_dispatch_execution_daemon_control_admission",
                "execution": "run_dispatch_execution_daemon_tick_once",
            },
        },
        "refactoring_checkpoint": {
            "route_handlers_should_be_thin": True,
            "reuse_control_request_builder": True,
            "reuse_control_admission_builder": True,
            "reuse_tick_plan_builder": True,
            "reuse_tick_once_executor": True,
            "reuse_operations_runtime_projection": True,
            "keep_provider_transport_injected": True,
            "keep_route_outputs_redacted": True,
            "keep_postgres_smoke_real_test_db": True,
        },
        "checks": checks,
        "paths": paths,
        "source_tokens": tokens,
        "issues": _issues(paths, tokens),
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


def _group_present(tokens: list[dict[str, Any]], group: str) -> bool:
    grouped = [item for item in tokens if item["group"] == group]
    return bool(grouped) and all(item["present"] for item in grouped)


def _issues(paths: list[dict[str, Any]], tokens: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
    return issues


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        boundary = evidence["boundary"]
        return (
            "ag_operator_review_escalation_dispatch_daemon_api_boundary=pass "
            f"boundary={boundary['boundary']} "
            f"routes_in_slice_0751={boundary['route_implementation_in_slice_0751']} "
            f"tick_plan={boundary['first_tick_plan_route_slice']} "
            f"tick_once={boundary['first_tick_once_route_slice']} "
            f"source={boundary['source_dispatch_table']}"
        )
    return (
        "ag_operator_review_escalation_dispatch_daemon_api_boundary=fail "
        f"reason={evidence.get('failure_code')} "
        f"issues={len(evidence.get('issues', []))}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the AG dispatch daemon protected API boundary audit."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_ag_operator_review_escalation_dispatch_daemon_api_boundary_audit()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
