#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "ag_recovery_notification_live_delivery_boundary_audit.v1"
SLICE_ID = "0851"
REQUIREMENT = "S86"
EXISTING_DISPATCH_TABLE = "ag_op_esc_dispatches"
MAX_IDENTIFIER_LENGTH = 30
BOUNDARY = "recovery_notification_explicit_live_http_opt_in"


@dataclass(frozen=True)
class RequiredPath:
    name: str
    relative_path: str


@dataclass(frozen=True)
class TokenRequirement:
    group: str
    relative_path: str
    token: str


REQUIRED_PATHS = (
    RequiredPath(
        "s85_closure",
        "scripts/smoke/run_s85_ag_recovery_notification_delivery_closure.py",
    ),
    RequiredPath(
        "recovery_delivery",
        "services/nex-ag/nex_ag/recovery_notification_delivery.py",
    ),
    RequiredPath(
        "dispatch_planner",
        "services/nex-ag/nex_ag/operator_review_cases.py",
    ),
    RequiredPath(
        "live_http_runtime",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
    ),
    RequiredPath(
        "notification_loopback",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_notification_loopback_smoke.py",
    ),
    RequiredPath("quality_gate", "scripts/quality/run_quality_gate.sh"),
    RequiredPath("docs_index", "docs/README.md"),
    RequiredPath(
        "slice_doc",
        "docs/slices/0851_ag_recovery_notification_live_delivery_boundary_audit.md",
    ),
)

TOKEN_REQUIREMENTS = (
    TokenRequirement(
        "s85_closed",
        "scripts/smoke/run_s85_ag_recovery_notification_delivery_closure.py",
        "s85_ag_recovery_notification_delivery_closure.v1",
    ),
    TokenRequirement(
        "recovery_handoff",
        "services/nex-ag/nex_ag/recovery_notification_delivery.py",
        "def build_recovery_notification_dispatch_handoff",
    ),
    TokenRequirement(
        "recovery_mock_guard",
        "services/nex-ag/nex_ag/recovery_notification_delivery.py",
        "ag.recovery_notification_delivery_execution_mock_only",
    ),
    TokenRequirement(
        "planner_live_guard",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        'reasons.append("live_channel_deferred")',
    ),
    TokenRequirement(
        "live_enable_guard",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        'DISPATCH_LIVE_PROVIDER_ENABLE_ENV = "NEX_AG_DISPATCH_LIVE_PROVIDER_ENABLE"',
    ),
    TokenRequirement(
        "live_transport",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "class UrllibDispatchProviderHttpTransport",
    ),
    TokenRequirement(
        "live_router",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "def execute_dispatch_with_live_http_transport",
    ),
    TokenRequirement(
        "loopback_baseline",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_notification_loopback_smoke.py",
        "ThreadingHTTPServer",
    ),
    TokenRequirement(
        "quality_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_recovery_notification_live_delivery_boundary_audit.py",
    ),
    TokenRequirement(
        "docs_index",
        "docs/README.md",
        "0851_ag_recovery_notification_live_delivery_boundary_audit.md",
    ),
)


def run_ag_recovery_notification_live_delivery_boundary_audit(
    root: Path = ROOT,
) -> dict[str, Any]:
    paths = [
        {
            "name": item.name,
            "path": item.relative_path,
            "present": (root / item.relative_path).is_file(),
        }
        for item in REQUIRED_PATHS
    ]
    tokens = [
        {
            "group": item.group,
            "path": item.relative_path,
            "present": item.token in _read_text(root / item.relative_path),
        }
        for item in TOKEN_REQUIREMENTS
    ]
    identifiers = [
        {
            "name": EXISTING_DISPATCH_TABLE,
            "length": len(EXISTING_DISPATCH_TABLE),
            "within_limit": len(EXISTING_DISPATCH_TABLE) <= MAX_IDENTIFIER_LENGTH,
        }
    ]
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "required_tokens_present": all(item["present"] for item in tokens),
        "s85_closed": _group_present(tokens, "s85_closed"),
        "recovery_handoff_reusable": _group_present(tokens, "recovery_handoff"),
        "current_live_guard_identified": all(
            _group_present(tokens, group)
            for group in ("recovery_mock_guard", "planner_live_guard")
        ),
        "existing_live_runtime_reusable": all(
            _group_present(tokens, group)
            for group in ("live_enable_guard", "live_transport", "live_router")
        ),
        "loopback_smoke_baseline_present": _group_present(
            tokens, "loopback_baseline"
        ),
        "identifier_lengths_safe": all(
            item["within_limit"] for item in identifiers
        ),
    }
    issues = [
        {"category": "path_missing", "path": item["path"]}
        for item in paths
        if not item["present"]
    ]
    issues.extend(
        {
            "category": "source_token_missing",
            "path": item["path"],
            "group": item["group"],
        }
        for item in tokens
        if not item["present"]
    )
    issues.extend(
        {"category": "identifier_too_long", "identifier": item["name"]}
        for item in identifiers
        if not item["within_limit"]
    )
    passed = all(checks.values())
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": SLICE_ID,
        "requirement": REQUIREMENT,
        "status": "PASS" if passed else "FAIL",
        "failure_code": None
        if passed
        else "ag_recovery_notification_live_delivery_boundary_failed",
        "decision": {
            "status": "APPROVED_BOUNDARY",
            "boundary": BOUNDARY,
            "safe_to_implement_next_slice": passed,
            "planner_change": "explicit_allow_live_channel_flag_default_false",
            "execution_change": "targeted_live_http_worker_adapter",
            "external_endpoint_strategy": "local_loopback_until_full_system",
        },
        "boundary": {
            "owner_service": "nex-ag",
            "existing_dispatch_table": EXISTING_DISPATCH_TABLE,
            "new_table_in_slice_0851": False,
            "new_route_in_slice_0851": False,
            "provider_invocation_in_slice_0851": False,
            "default_live_delivery_enabled": False,
            "explicit_live_enable_required": True,
            "real_external_endpoint_available": False,
            "protected_smoke_strategy": "local_loopback_http_server",
            "real_endpoint_smoke_deferred_until_full_system": True,
            "eligible_live_channels": ["NOTIFICATION", "EMAIL", "WEBHOOK"],
            "incident_channel_in_s86": False,
            "raw_payload_storage_allowed": False,
            "provider_secret_persistence_allowed": False,
        },
        "refactoring_checkpoint": {
            "reuse_s85_recovery_dispatch_handoff": True,
            "reuse_s74_live_http_transport_and_router": True,
            "keep_generic_planner_live_guard_default_closed": True,
            "open_live_planning_only_with_explicit_internal_flag": True,
            "keep_mock_execution_adapter_unchanged": True,
            "add_separate_targeted_live_execution_adapter": True,
            "require_live_enable_env_and_injected_transport": True,
            "route_mutations_through_existing_dispatch_state_machine": True,
            "persist_only_safe_hashes_statuses_and_diagnostics": True,
            "add_no_table": True,
        },
        "planned_slices": [
            "Slice_0852_live_delivery_admission_configuration",
            "Slice_0853_live_dispatch_handoff_wiring",
            "Slice_0854_protected_live_delivery_api_guardrails",
            "Slice_0855_targeted_live_execution_projection",
            "Slice_0856_contract_operations_hardening",
            "Slice_0857_loopback_transport_smoke",
            "Slice_0858_postgresql_loopback_smoke",
            "Slice_0859_privacy_failure_runbook",
            "Slice_0860_closure",
        ],
        "paths": paths,
        "source_tokens": tokens,
        "identifiers": identifiers,
        "checks": checks,
        "issues": issues,
    }


def summary_line(evidence: dict[str, Any]) -> str:
    decision = evidence.get("decision", {})
    boundary = evidence.get("boundary", {})
    return (
        "ag_recovery_notification_live_delivery_boundary="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"boundary={decision.get('boundary')} "
        f"network={'disabled' if not boundary.get('default_live_delivery_enabled') else 'enabled'} "
        f"smoke={boundary.get('protected_smoke_strategy')} "
        f"safe_next={decision.get('safe_to_implement_next_slice')}"
    )


def _group_present(tokens: list[dict[str, Any]], group: str) -> bool:
    selected = [item for item in tokens if item["group"] == group]
    return bool(selected) and all(item["present"] for item in selected)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_ag_recovery_notification_live_delivery_boundary_audit()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
