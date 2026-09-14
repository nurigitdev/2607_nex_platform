#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = (
    "ag_operator_review_escalation_dispatch_live_http_transport_boundary_audit.v1"
)

SLICE_ID = "0731"
S74_SURFACE = "AG operator review escalation dispatch live HTTP transport readiness"
BOUNDARY = "ag_owned_operator_review_escalation_dispatch_live_http_transport"
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
        "s73_closure_script",
        "scripts/smoke/run_s73_operator_review_escalation_dispatch_provider_closure.py",
        "S73 provider readiness must be closed before live HTTP transport readiness.",
    ),
    RequiredPath(
        "s73_closure_doc",
        "docs/slices/0730_s73_operator_review_escalation_dispatch_provider_closure.md",
        "S73 closure boundary and deferred live transport decision.",
    ),
    RequiredPath(
        "dispatch_execution_runtime",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "Provider config, request, mock adapter, HTTP client, and router runtime.",
    ),
    RequiredPath(
        "ag_operations",
        "services/nex-ag/nex_ag/operations.py",
        "Provider diagnostics dashboard projection surface.",
    ),
    RequiredPath(
        "operations_schema",
        "contracts/schemas/service/nex_ag/operations_projection.v1.schema.json",
        "Provider diagnostics operations contract.",
    ),
    RequiredPath(
        "privacy_regression",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_live_provider_privacy_regression.py",
        "Provider surface privacy regression baseline.",
    ),
    RequiredPath(
        "provider_postgres_smoke",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_provider_postgres_smoke.py",
        "Protected nex_ag_test provider router persistence smoke.",
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
        "docs/slices/0731_ag_escalation_dispatch_live_http_transport_boundary_audit.md",
        "Slice 0731 implementation note.",
    ),
)

TOKEN_REQUIREMENTS = (
    TokenRequirement(
        "s73_closed_baseline",
        "scripts/smoke/run_s73_operator_review_escalation_dispatch_provider_closure.py",
        "s73_closure_schema",
        "s73_operator_review_escalation_dispatch_provider_closure.v1",
        "Live HTTP transport readiness starts after S73 closure.",
    ),
    TokenRequirement(
        "s73_closed_baseline",
        "scripts/smoke/run_s73_operator_review_escalation_dispatch_provider_closure.py",
        "live_network_deferred",
        "deferred_until_protected_transport",
        "S74 must explicitly move transport from deferred to loopback-protected.",
    ),
    TokenRequirement(
        "runtime_baseline",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "provider_config_schema",
        "ag_operator_review_escalation_dispatch_provider_config.v1",
        "Live HTTP transport must reuse provider config.",
    ),
    TokenRequirement(
        "runtime_baseline",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "http_client_result_schema",
        "ag_operator_review_escalation_dispatch_provider_http_client_result.v1",
        "Live HTTP transport must preserve HTTP client result contract.",
    ),
    TokenRequirement(
        "runtime_baseline",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "injected_mock_transport",
        "MockDispatchProviderHttpTransport",
        "Real transport must remain injectable and testable with loopback transport.",
    ),
    TokenRequirement(
        "runtime_baseline",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "provider_router",
        "def execute_dispatch_with_provider_router",
        "Worker routing must stay centralized.",
    ),
    TokenRequirement(
        "runtime_baseline",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "live_enable_guard",
        "NEX_AG_DISPATCH_LIVE_PROVIDER_ENABLE",
        "Live outbound transport must require explicit opt-in.",
    ),
    TokenRequirement(
        "runtime_baseline",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "forbidden_result_keys",
        "FORBIDDEN_DISPATCH_EXECUTION_RESULT_KEYS",
        "Transport evidence must keep raw payloads and secrets forbidden.",
    ),
    TokenRequirement(
        "runtime_baseline",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "sensitive_value_patterns",
        "SENSITIVE_DISPATCH_EXECUTION_VALUE_PATTERNS",
        "Transport evidence must keep sensitive value scanning.",
    ),
    TokenRequirement(
        "privacy_baseline",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_live_provider_privacy_regression.py",
        "privacy_schema",
        "ag_operator_review_escalation_dispatch_live_provider_privacy_regression.v1",
        "Transport readiness must preserve provider privacy regression.",
    ),
    TokenRequirement(
        "postgres_baseline",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_provider_postgres_smoke.py",
        "provider_postgres_smoke_env",
        "NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_PROVIDER_POSTGRES_SMOKE",
        "Transport readiness must keep protected test DB evidence.",
    ),
    TokenRequirement(
        "operations_visibility",
        "services/nex-ag/nex_ag/operations.py",
        "provider_diagnostics",
        "by_http_status_code",
        "Transport diagnostics must remain visible in AG operations.",
    ),
    TokenRequirement(
        "operations_contract",
        "contracts/schemas/service/nex_ag/operations_projection.v1.schema.json",
        "provider_diagnostics_schema",
        "by_provider_category",
        "Operations contract must keep provider diagnostics.",
    ),
    TokenRequirement(
        "quality_gate",
        "scripts/quality/run_quality_gate.sh",
        "s73_closure_quality_gate",
        "run_s73_operator_review_escalation_dispatch_provider_closure.py",
        "S73 closure remains in the default quality gate.",
    ),
    TokenRequirement(
        "quality_gate",
        "scripts/quality/run_quality_gate.sh",
        "s74_boundary_quality_gate",
        "run_ag_operator_review_escalation_dispatch_live_http_transport_boundary_audit.py",
        "Slice 0731 audit must run in the default quality gate.",
    ),
)

TABLE_NAMES_UNDER_REVIEW = (
    SOURCE_TABLE,
)

NEXT_SLICES = (
    "Slice_0732",
    "Slice_0733",
    "Slice_0734",
    "Slice_0735",
    "Slice_0736",
    "Slice_0737",
    "Slice_0738",
    "Slice_0739",
    "Slice_0740",
)


def run_ag_operator_review_escalation_dispatch_live_http_transport_boundary_audit(
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
        "s73_closure_present": _group_present(tokens, "s73_closed_baseline"),
        "runtime_baseline_present": _group_present(tokens, "runtime_baseline"),
        "privacy_baseline_present": _group_present(tokens, "privacy_baseline"),
        "postgres_baseline_present": _group_present(tokens, "postgres_baseline"),
        "quality_gate_present": _group_present(tokens, "quality_gate"),
    }
    passed = all(checks.values())
    evidence = {
        "audit_schema_version": SCHEMA_VERSION,
        "status": "PASS" if passed else "FAIL",
        "failure_code": None
        if passed
        else "ag_operator_review_escalation_dispatch_live_http_transport_boundary_failed",
        "slice": SLICE_ID,
        "surface": S74_SURFACE,
        "boundary": _boundary(),
        "refactoring_checkpoint": _refactoring_checkpoint(),
        "paths": paths,
        "source_tokens": tokens,
        "table_name_results": table_name_results,
        "checks": checks,
        "next_slices": list(NEXT_SLICES),
        "issues": _issues(paths, tokens, table_name_results),
    }
    return evidence


def _boundary() -> dict[str, Any]:
    return {
        "boundary": BOUNDARY,
        "source_dispatch_table": SOURCE_TABLE,
        "create_table_in_slice_0731": False,
        "live_network_calls_in_slice_0731": False,
        "real_external_endpoint_available": False,
        "protected_smoke_strategy": "local_loopback_http_server",
        "real_endpoint_smoke_deferred_until_full_system": True,
        "first_transport_slice": "Slice_0732",
        "first_loopback_notification_smoke_slice": "Slice_0735",
        "first_loopback_incident_smoke_slice": "Slice_0736",
        "first_postgres_loopback_smoke_slice": "Slice_0738",
        "provider_modes_allowed_now": ["mock_first_only", "mock_http"],
        "guarded_live_mode_requires": [
            "NEX_AG_DISPATCH_LIVE_PROVIDER_ENABLE=1",
            "loopback_or_explicit_protected_live_smoke",
            "redacted_endpoint_hint_only",
            "no_raw_headers_or_payloads_in_evidence",
        ],
        "result_storage": "safe_hashes_statuses_counters_only",
        "raw_provider_payload_storage_allowed": False,
        "authorization_header_in_evidence_allowed": False,
        "webhook_url_path_in_evidence_allowed": False,
        "provider_token_in_evidence_allowed": False,
    }


def _refactoring_checkpoint() -> dict[str, Any]:
    return {
        "reuse_s73_provider_config_and_request_contracts": True,
        "keep_transport_injected_not_global": True,
        "start_with_local_loopback_http_server": True,
        "defer_real_external_endpoint_until_full_system": True,
        "require_live_enable_env_for_network": True,
        "preserve_mock_first_default": True,
        "route_state_changes_through_dispatch_action_state_machine": True,
        "persist_only_safe_hashes_statuses_and_diagnostics": True,
        "keep_authorization_headers_out_of_logs_and_evidence": True,
        "keep_raw_provider_payloads_out_of_db_logs_and_evidence": True,
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
    if evidence["status"] != "PASS":
        return (
            "ag_operator_review_escalation_dispatch_live_http_transport_boundary="
            f"{evidence['status'].lower()} "
            f"failure={evidence.get('failure_code') or 'unknown'}"
        )
    boundary = evidence["boundary"]
    return (
        "ag_operator_review_escalation_dispatch_live_http_transport_boundary=pass "
        f"boundary={boundary['boundary']} "
        f"network={'disabled' if not boundary['live_network_calls_in_slice_0731'] else 'enabled'} "
        f"smoke={boundary['protected_smoke_strategy']} "
        f"real_endpoint_deferred={boundary['real_endpoint_smoke_deferred_until_full_system']} "
        f"next={evidence['next_slices'][0]}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the AG dispatch live HTTP transport boundary audit."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_ag_operator_review_escalation_dispatch_live_http_transport_boundary_audit()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
