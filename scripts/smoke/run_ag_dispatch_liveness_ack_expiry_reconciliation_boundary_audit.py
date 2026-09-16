#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "ag_dispatch_liveness_ack_expiry_reconciliation_boundary_audit.v1"
SLICE_ID = "0811"
BOUNDARY = "ag_owned_liveness_ack_expiry_reconciliation"
ACK_STATE_TABLE = "ag_op_review_ack_state"
MAX_TABLE_NAME_LENGTH = 30


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
        "s81_closure",
        "scripts/smoke/run_s81_operator_review_escalation_dispatch_daemon_liveness_ack_state_closure.py",
    ),
    RequiredPath(
        "ack_state_runtime",
        "services/nex-ag/nex_ag/operator_review_liveness_ack.py",
    ),
    RequiredPath("ag_operations", "services/nex-ag/nex_ag/operations.py"),
    RequiredPath(
        "ack_state_migration",
        "database/nex-ag/migrations/0802_ag_liveness_ack_state.sql",
    ),
    RequiredPath("quality_gate", "scripts/quality/run_quality_gate.sh"),
    RequiredPath("docs_index", "docs/README.md"),
    RequiredPath(
        "slice_doc",
        "docs/slices/0811_ag_dispatch_liveness_ack_expiry_reconciliation_boundary_audit.md",
    ),
)

TOKEN_REQUIREMENTS = (
    TokenRequirement(
        "s81_closed",
        "scripts/smoke/run_s81_operator_review_escalation_dispatch_daemon_liveness_ack_state_closure.py",
        "s81_operator_review_escalation_dispatch_daemon_liveness_ack_state_closure.v1",
    ),
    TokenRequirement(
        "existing_table",
        "services/nex-ag/nex_ag/operator_review_liveness_ack.py",
        'AG_OPERATOR_REVIEW_LIVENESS_ACK_STATE_TABLE = "ag_op_review_ack_state"',
    ),
    TokenRequirement(
        "read_time_expiry",
        "services/nex-ag/nex_ag/operator_review_liveness_ack.py",
        '"effective_state_status": "EXPIRED" if expired else stored_status',
    ),
    TokenRequirement(
        "stored_statuses",
        "services/nex-ag/nex_ag/operator_review_liveness_ack.py",
        'ACK_STATE_STATUSES = ("ACKNOWLEDGED", "SUPPRESSED", "EXPIRED", "CLEARED")',
    ),
    TokenRequirement(
        "suppression_deadline",
        "services/nex-ag/nex_ag/operator_review_liveness_ack.py",
        "suppressed_until",
    ),
    TokenRequirement(
        "source_projection_preserved",
        "services/nex-ag/nex_ag/operations.py",
        '"source_projection_suppressed": False',
    ),
)


def run_ag_dispatch_liveness_ack_expiry_reconciliation_boundary_audit(
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
    tokens = []
    for item in TOKEN_REQUIREMENTS:
        path = root / item.relative_path
        text = _read_text(path)
        tokens.append(
            {
                "group": item.group,
                "path": item.relative_path,
                "token": item.token,
                "present": item.token in text,
            }
        )
    table_names = [
        {
            "table_name": ACK_STATE_TABLE,
            "length": len(ACK_STATE_TABLE),
            "within_limit": len(ACK_STATE_TABLE) <= MAX_TABLE_NAME_LENGTH,
        }
    ]
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "required_tokens_present": all(item["present"] for item in tokens),
        "s81_closed": _group_present(tokens, "s81_closed"),
        "existing_table_reused": _group_present(tokens, "existing_table"),
        "read_time_expiry_baseline_present": _group_present(
            tokens, "read_time_expiry"
        ),
        "table_names_within_limit": all(
            item["within_limit"] for item in table_names
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
        {"category": "table_name_too_long", "table_name": item["table_name"]}
        for item in table_names
        if not item["within_limit"]
    )
    status = "PASS" if all(checks.values()) else "FAIL"
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": SLICE_ID,
        "requirement": "S82",
        "status": status,
        "failure_code": (
            None
            if status == "PASS"
            else "ag_dispatch_liveness_ack_expiry_reconciliation_boundary_failed"
        ),
        "boundary": {
            "boundary": BOUNDARY,
            "owner_service": "nex-ag",
            "source_table": ACK_STATE_TABLE,
            "new_table_in_slice_0811": False,
            "mutation_route_in_slice_0811": False,
            "source_liveness_projection_mutated": False,
            "stored_transition": "SUPPRESSED_TO_EXPIRED",
            "candidate_rule": "state_status_SUPPRESSED_and_suppressed_until_lte_observed_at",
        },
        "decisions": {
            "reuse_existing_ack_state_table": True,
            "compare_and_set_required": True,
            "idempotent_reconciliation_required": True,
            "bounded_batch_required": True,
            "safe_operational_event_required": True,
            "raw_comment_or_payload_access_required": False,
            "retention_or_physical_delete_in_s82": False,
            "retention_deferred_to_s89": True,
        },
        "slice_plan": [
            "Slice_0812_contract_and_transition",
            "Slice_0813_candidate_persistence_adapter",
            "Slice_0814_reconciliation_worker",
            "Slice_0815_protected_manual_api_and_audit",
            "Slice_0816_operations_overlay",
            "Slice_0817_openapi_schema_hardening",
            "Slice_0818_postgresql_smoke",
            "Slice_0819_privacy_concurrency_runbook",
            "Slice_0820_closure",
        ],
        "paths": paths,
        "source_tokens": tokens,
        "table_names": table_names,
        "checks": checks,
        "issues": issues,
    }


def summary_line(evidence: dict[str, Any]) -> str:
    boundary = evidence.get("boundary", {})
    status = str(evidence.get("status", "FAIL")).lower()
    plan = evidence.get("slice_plan", [])
    return (
        "ag_dispatch_liveness_ack_expiry_reconciliation_boundary="
        f"{status} table={boundary.get('source_table')} "
        f"new_table={boundary.get('new_table_in_slice_0811')} "
        f"transition={boundary.get('stored_transition')} "
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
    evidence = run_ag_dispatch_liveness_ack_expiry_reconciliation_boundary_audit()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
