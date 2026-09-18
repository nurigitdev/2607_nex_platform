#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "ag_ack_expiry_automation_boundary_audit.v1"
SLICE_ID = "0821"
REQUIREMENT = "S83"
BOUNDARY = "ag_owned_ack_expiry_bounded_run_once_automation"
ACK_STATE_TABLE = "ag_op_review_ack_state"
EVENT_TABLE = "service_operational_events"
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
        "s82_closure",
        "scripts/smoke/run_s82_ag_dispatch_liveness_ack_expiry_reconciliation_closure.py",
    ),
    RequiredPath(
        "reconciliation_worker",
        "services/nex-ag/nex_ag/liveness_ack_expiry_reconciliation.py",
    ),
    RequiredPath(
        "ack_state_store",
        "services/nex-ag/nex_ag/operator_review_liveness_ack.py",
    ),
    RequiredPath(
        "dispatch_daemon_cli_pattern",
        "services/nex-ag/nex_ag/operator_review_dispatch_daemon.py",
    ),
    RequiredPath("operations", "services/nex-ag/nex_ag/operations.py"),
    RequiredPath("quality_gate", "scripts/quality/run_quality_gate.sh"),
    RequiredPath("docs_index", "docs/README.md"),
    RequiredPath(
        "slice_doc",
        "docs/slices/0821_ag_ack_expiry_automation_boundary_audit.md",
    ),
)

TOKEN_REQUIREMENTS = (
    TokenRequirement(
        "s82_closed",
        "scripts/smoke/run_s82_ag_dispatch_liveness_ack_expiry_reconciliation_closure.py",
        "s82_ag_dispatch_liveness_ack_expiry_reconciliation_closure.v1",
    ),
    TokenRequirement(
        "bounded_worker",
        "services/nex-ag/nex_ag/liveness_ack_expiry_reconciliation.py",
        "def run_operator_review_liveness_ack_expiry_reconciliation",
    ),
    TokenRequirement(
        "candidate_store",
        "services/nex-ag/nex_ag/operator_review_liveness_ack.py",
        "def list_expiry_candidates",
    ),
    TokenRequirement(
        "cas_store",
        "services/nex-ag/nex_ag/operator_review_liveness_ack.py",
        "def apply_expiry_reconciliation",
    ),
    TokenRequirement(
        "operational_event_baseline",
        "services/nex-ag/nex_ag/operations.py",
        "OperationalEventEmitter",
    ),
    TokenRequirement(
        "cli_facade_pattern",
        "services/nex-ag/nex_ag/operator_review_dispatch_daemon.py",
        "def execute_dispatch_execution_daemon_cli",
    ),
)


def run_ag_ack_expiry_automation_boundary_audit(
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
    table_names = [
        {
            "name": name,
            "length": len(name),
            "within_limit": len(name) <= MAX_TABLE_NAME_LENGTH,
        }
        for name in (ACK_STATE_TABLE, EVENT_TABLE)
    ]
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "required_tokens_present": all(item["present"] for item in tokens),
        "s82_closed": _group_present(tokens, "s82_closed"),
        "bounded_worker_reused": _group_present(tokens, "bounded_worker"),
        "cas_store_reused": _group_present(tokens, "cas_store"),
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
        {"category": "table_name_too_long", "table_name": item["name"]}
        for item in table_names
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
        else "ag_ack_expiry_automation_boundary_failed",
        "boundary": {
            "boundary": BOUNDARY,
            "owner_service": "nex-ag",
            "source_table": ACK_STATE_TABLE,
            "event_table": EVENT_TABLE,
            "reconciliation_executor": (
                "run_operator_review_liveness_ack_expiry_reconciliation"
            ),
            "execution_mode": "externally_scheduled_bounded_run_once",
            "new_table_in_slice_0821": False,
            "new_route_in_slice_0821": False,
            "continuous_loop_in_s83": False,
            "subprocess_supervision_in_s83": False,
        },
        "decisions": {
            "disabled_by_default": True,
            "explicit_enable_required": True,
            "bounded_batch_required": True,
            "compare_and_set_reused": True,
            "operational_event_summary_required": True,
            "raw_payloads_forbidden": True,
            "scheduler_invocation_owned_outside_process": True,
            "retention_or_physical_delete_in_s83": False,
        },
        "slice_plan": [
            "Slice_0822_automation_policy",
            "Slice_0823_tick_plan",
            "Slice_0824_tick_execution",
            "Slice_0825_cli_facade",
            "Slice_0826_lifecycle_audit",
            "Slice_0827_operations_projection",
            "Slice_0828_postgresql_smoke",
            "Slice_0829_privacy_runbook",
            "Slice_0830_closure",
        ],
        "paths": paths,
        "source_tokens": tokens,
        "table_names": table_names,
        "checks": checks,
        "issues": issues,
    }


def summary_line(evidence: dict[str, Any]) -> str:
    boundary = evidence.get("boundary", {})
    plan = evidence.get("slice_plan", [])
    return (
        "ag_ack_expiry_automation_boundary="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"mode={boundary.get('execution_mode')} "
        f"new_table={boundary.get('new_table_in_slice_0821')} "
        f"continuous_loop={boundary.get('continuous_loop_in_s83')} "
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
    evidence = run_ag_ack_expiry_automation_boundary_audit()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
