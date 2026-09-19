#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "ag_recovery_notification_delivery_boundary_audit.v1"
SLICE_ID = "0841"
REQUIREMENT = "S85"
EXISTING_DISPATCH_TABLE = "ag_op_esc_dispatches"
MAX_IDENTIFIER_LENGTH = 30
RECOMMENDED_OPTION = (
    "reuse_existing_dispatch_outbox_with_explicit_case_escalation_context"
)


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
        "s84_closure",
        "scripts/smoke/run_s84_ag_recovery_notification_policy_closure.py",
    ),
    RequiredPath(
        "dispatch_migration",
        "database/nex-ag/migrations/0702_ag_operator_review_escalation_dispatch.sql",
    ),
    RequiredPath(
        "dispatch_store",
        "services/nex-ag/nex_ag/operator_review_cases.py",
    ),
    RequiredPath(
        "dispatch_provider",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
    ),
    RequiredPath(
        "recovery_policy",
        "services/nex-ag/nex_ag/recovery_notification_policy.py",
    ),
    RequiredPath("quality_gate", "scripts/quality/run_quality_gate.sh"),
    RequiredPath("docs_index", "docs/README.md"),
    RequiredPath(
        "slice_doc",
        "docs/slices/0841_ag_recovery_notification_delivery_boundary_audit.md",
    ),
)

TOKEN_REQUIREMENTS = (
    TokenRequirement(
        "s84_closed",
        "scripts/smoke/run_s84_ag_recovery_notification_policy_closure.py",
        "s84_ag_recovery_notification_policy_closure.v1",
    ),
    TokenRequirement(
        "existing_dispatch_table",
        "database/nex-ag/migrations/0702_ag_operator_review_escalation_dispatch.sql",
        "CREATE TABLE IF NOT EXISTS ag_op_esc_dispatches",
    ),
    TokenRequirement(
        "mandatory_escalation_context",
        "database/nex-ag/migrations/0702_ag_operator_review_escalation_dispatch.sql",
        "escalation_id TEXT NOT NULL REFERENCES ag_op_escalations",
    ),
    TokenRequirement(
        "mandatory_case_context",
        "database/nex-ag/migrations/0702_ag_operator_review_escalation_dispatch.sql",
        "case_id TEXT NOT NULL REFERENCES ag_op_cases",
    ),
    TokenRequirement(
        "sql_dispatch_store",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "class SqlAlchemyOperatorReviewEscalationDispatchStore",
    ),
    TokenRequirement(
        "notification_provider",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "class MockNotificationDispatchProvider",
    ),
    TokenRequirement(
        "provider_request_builder",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "def build_notification_dispatch_provider_request",
    ),
    TokenRequirement(
        "s84_provider_guardrail",
        "services/nex-ag/nex_ag/recovery_notification_policy.py",
        '"external_provider_invocation_allowed": False',
    ),
    TokenRequirement(
        "s84_persistence_guardrail",
        "services/nex-ag/nex_ag/recovery_notification_policy.py",
        '"dispatch_persistence_allowed": False',
    ),
    TokenRequirement(
        "boundary_quality_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_recovery_notification_delivery_boundary_audit.py",
    ),
    TokenRequirement(
        "docs_index_0841",
        "docs/README.md",
        "0841_ag_recovery_notification_delivery_boundary_audit.md",
    ),
)


def run_ag_recovery_notification_delivery_boundary_audit(
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
        "s84_closed": _group_present(tokens, "s84_closed"),
        "existing_outbox_is_reusable": all(
            _group_present(tokens, group)
            for group in (
                "existing_dispatch_table",
                "sql_dispatch_store",
                "notification_provider",
                "provider_request_builder",
            )
        ),
        "existing_outbox_requires_case_and_escalation": all(
            _group_present(tokens, group)
            for group in (
                "mandatory_escalation_context",
                "mandatory_case_context",
            )
        ),
        "s84_delivery_guardrails_remain_closed": all(
            _group_present(tokens, group)
            for group in (
                "s84_provider_guardrail",
                "s84_persistence_guardrail",
            )
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
        else "ag_recovery_notification_delivery_boundary_failed",
        "decision": {
            "status": "REQUIRED_BEFORE_IMPLEMENTATION",
            "recommended_option": RECOMMENDED_OPTION,
            "safe_to_implement_next_slice": False,
            "reason": (
                "The reusable dispatch outbox requires existing case_id and "
                "escalation_id foreign-key context, while S84 recovery "
                "notification previews do not create that context."
            ),
            "options": [
                {
                    "option": RECOMMENDED_OPTION,
                    "new_table_required": False,
                    "description": (
                        "Require explicit existing case_id and escalation_id, "
                        "then reuse the dispatch outbox, store, worker, and provider."
                    ),
                },
                {
                    "option": "create_dedicated_recovery_notification_outbox",
                    "new_table_required": True,
                    "description": (
                        "Persist recovery notifications independently and adapt "
                        "the existing delivery execution components."
                    ),
                },
                {
                    "option": "record_operational_event_without_delivery",
                    "new_table_required": False,
                    "description": (
                        "Keep recovery notifications internal and do not provide "
                        "external delivery in S85."
                    ),
                },
            ],
        },
        "boundary": {
            "owner_service": "nex-ag",
            "existing_dispatch_table": EXISTING_DISPATCH_TABLE,
            "mandatory_existing_context": ["case_id", "escalation_id"],
            "reusable_components": [
                "SqlAlchemyOperatorReviewEscalationDispatchStore",
                "MockNotificationDispatchProvider",
                "notification_dispatch_provider_request",
            ],
            "new_table_in_slice_0841": False,
            "new_route_in_slice_0841": False,
            "dispatch_persistence_in_slice_0841": False,
            "provider_invocation_in_slice_0841": False,
        },
        "provisional_slice_plan": [
            "Slice_0842_delivery_admission_contract",
            "Slice_0843_dispatch_handoff_planner",
            "Slice_0844_protected_delivery_request_api",
            "Slice_0845_delivery_operations_projection",
            "Slice_0846_contract_hardening",
            "Slice_0847_mock_execution_integration",
            "Slice_0848_postgresql_smoke",
            "Slice_0849_privacy_runbook",
            "Slice_0850_closure",
        ],
        "paths": paths,
        "source_tokens": tokens,
        "identifiers": identifiers,
        "checks": checks,
        "issues": issues,
    }


def summary_line(evidence: dict[str, Any]) -> str:
    decision = evidence.get("decision", {})
    return (
        "ag_recovery_notification_delivery_boundary="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"decision={decision.get('status')} "
        f"recommended={decision.get('recommended_option')} "
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
    evidence = run_ag_recovery_notification_delivery_boundary_audit()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
