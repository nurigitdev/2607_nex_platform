#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "ag_recovery_notification_policy_boundary_audit.v1"
SLICE_ID = "0831"
REQUIREMENT = "S84"
BOUNDARY = "ag_owned_recovery_notification_policy_preview"
ACK_STATE_TABLE = "ag_op_review_ack_state"
EVENT_TABLE = "service_operational_events"
MAX_IDENTIFIER_LENGTH = 30


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
        "s83_closure",
        "scripts/smoke/run_s83_ag_ack_expiry_automation_closure.py",
    ),
    RequiredPath("operations", "services/nex-ag/nex_ag/operations.py"),
    RequiredPath(
        "ack_state_store",
        "services/nex-ag/nex_ag/operator_review_liveness_ack.py",
    ),
    RequiredPath(
        "existing_provider_adapter",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
    ),
    RequiredPath("quality_gate", "scripts/quality/run_quality_gate.sh"),
    RequiredPath("docs_index", "docs/README.md"),
    RequiredPath(
        "slice_doc",
        "docs/slices/0831_ag_recovery_notification_policy_boundary_audit.md",
    ),
)

TOKEN_REQUIREMENTS = (
    TokenRequirement(
        "s83_closed",
        "scripts/smoke/run_s83_ag_ack_expiry_automation_closure.py",
        "s83_ag_ack_expiry_automation_closure.v1",
    ),
    TokenRequirement(
        "recovery_plan",
        "services/nex-ag/nex_ag/operations.py",
        "def build_operator_review_escalation_dispatch_daemon_liveness_recovery_plan",
    ),
    TokenRequirement(
        "ack_suppression_policy",
        "services/nex-ag/nex_ag/operations.py",
        "def build_operator_review_escalation_dispatch_daemon_liveness_ack_suppression_policy",
    ),
    TokenRequirement(
        "ack_state_overlay",
        "services/nex-ag/nex_ag/operator_review_liveness_ack.py",
        "def project_operator_review_liveness_ack_state_effective_status",
    ),
    TokenRequirement(
        "provider_adapter_deferred",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "def build_notification_dispatch_provider_request",
    ),
    TokenRequirement(
        "boundary_quality_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_recovery_notification_policy_boundary_audit.py",
    ),
    TokenRequirement(
        "docs_index_0831",
        "docs/README.md",
        "0831_ag_recovery_notification_policy_boundary_audit.md",
    ),
)


def run_ag_recovery_notification_policy_boundary_audit(
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
            "name": name,
            "length": len(name),
            "within_limit": len(name) <= MAX_IDENTIFIER_LENGTH,
        }
        for name in (ACK_STATE_TABLE, EVENT_TABLE)
    ]
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "required_tokens_present": all(item["present"] for item in tokens),
        "s83_closed": _group_present(tokens, "s83_closed"),
        "recovery_plan_reused": _group_present(tokens, "recovery_plan"),
        "ack_state_overlay_reused": _group_present(tokens, "ack_state_overlay"),
        "provider_invocation_deferred": _group_present(
            tokens, "provider_adapter_deferred"
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
        else "ag_recovery_notification_policy_boundary_failed",
        "boundary": {
            "boundary": BOUNDARY,
            "owner_service": "nex-ag",
            "input_surfaces": [
                "dispatch_daemon_liveness_recovery_plan",
                "acknowledgement_suppression_state_overlay",
            ],
            "output_surfaces": [
                "notification_policy",
                "notification_decision",
                "redacted_notification_preview",
            ],
            "source_tables": [ACK_STATE_TABLE, EVENT_TABLE],
            "new_table_in_slice_0831": False,
            "new_route_in_slice_0831": False,
            "outbound_provider_call_in_s84": False,
            "dispatch_persistence_in_s84": False,
        },
        "decisions": {
            "policy_evaluation_is_deterministic": True,
            "delivery_is_disabled_by_default": True,
            "active_suppression_is_policy_input": True,
            "severity_mapping_is_explicit": True,
            "raw_payloads_forbidden": True,
            "tokens_and_database_urls_forbidden": True,
            "existing_notification_adapter_reserved_for_later_requirement": True,
            "retention_or_physical_delete_in_s84": False,
        },
        "slice_plan": [
            "Slice_0832_policy_configuration_contract",
            "Slice_0833_notification_eligibility_evaluation",
            "Slice_0834_redacted_notification_plan",
            "Slice_0835_protected_policy_preview_api",
            "Slice_0836_operations_policy_projection",
            "Slice_0837_openapi_schema_hardening",
            "Slice_0838_postgresql_smoke",
            "Slice_0839_privacy_runbook",
            "Slice_0840_closure",
        ],
        "paths": paths,
        "source_tokens": tokens,
        "identifiers": identifiers,
        "checks": checks,
        "issues": issues,
    }


def summary_line(evidence: dict[str, Any]) -> str:
    boundary = evidence.get("boundary", {})
    plan = evidence.get("slice_plan", [])
    return (
        "ag_recovery_notification_policy_boundary="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"owner={boundary.get('owner_service')} "
        f"provider_call={boundary.get('outbound_provider_call_in_s84')} "
        f"new_table={boundary.get('new_table_in_slice_0831')} "
        f"next={plan[0] if plan else None}"
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
    evidence = run_ag_recovery_notification_policy_boundary_audit()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
