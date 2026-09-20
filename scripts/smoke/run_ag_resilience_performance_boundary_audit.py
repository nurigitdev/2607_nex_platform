#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "ag_resilience_performance_boundary_audit.v1"
SLICE_ID = "0871"
REQUIREMENT = "S88"
BOUNDARY = "ag_admin_read_resilience_and_bounded_performance_hardening"
MAX_IDENTIFIER_LENGTH = 30
SOURCE_TABLES = ("service_operational_events", "ag_ev_exports")


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
        "s87_closure",
        "scripts/smoke/run_s87_ag_audit_integrity_evidence_closure.py",
    ),
    RequiredPath("database_runtime", "services/_shared/nex_runtime/database.py"),
    RequiredPath(
        "persistence_runtime",
        "services/_shared/nex_runtime/persistence.py",
    ),
    RequiredPath("operations_runtime", "services/nex-ag/nex_ag/operations.py"),
    RequiredPath(
        "audit_api_runtime",
        "services/nex-ag/nex_ag/audit_evidence_api.py",
    ),
    RequiredPath(
        "event_store_runtime",
        "services/_shared/nex_runtime/operational_events.py",
    ),
    RequiredPath(
        "export_store_runtime",
        "services/nex-ag/nex_ag/operator_reviews.py",
    ),
    RequiredPath("quality_gate", "scripts/quality/run_quality_gate.sh"),
    RequiredPath("docs_index", "docs/README.md"),
    RequiredPath(
        "slice_doc",
        "docs/slices/0871_ag_resilience_performance_boundary_audit.md",
    ),
)

TOKEN_REQUIREMENTS = (
    TokenRequirement(
        "s87_closed",
        "scripts/smoke/run_s87_ag_audit_integrity_evidence_closure.py",
        "s87_ag_audit_integrity_evidence_closure.v1",
    ),
    TokenRequirement(
        "pool_settings",
        "services/_shared/nex_runtime/database.py",
        "class DatabasePoolSettings",
    ),
    TokenRequirement(
        "api_pool_default",
        "services/_shared/nex_runtime/database.py",
        "pool_size: int = 5",
    ),
    TokenRequirement(
        "pool_timeout",
        "services/_shared/nex_runtime/database.py",
        "pool_timeout_seconds: float = 30.0",
    ),
    TokenRequirement(
        "statement_timeout",
        "services/_shared/nex_runtime/database.py",
        "statement_timeout_ms: int = 30000",
    ),
    TokenRequirement(
        "workload_split",
        "services/_shared/nex_runtime/persistence.py",
        'workload="worker"',
    ),
    TokenRequirement(
        "query_options",
        "services/nex-ag/nex_ag/operations.py",
        "class OperationQueryOptions",
    ),
    TokenRequirement(
        "bounded_query_limit",
        "services/nex-ag/nex_ag/operations.py",
        "normalized_limit = normalize_job_limit(limit)",
    ),
    TokenRequirement(
        "cursor_validation",
        "services/nex-ag/nex_ag/operations.py",
        "def normalize_operation_cursor",
    ),
    TokenRequirement(
        "audit_server_selection",
        "services/nex-ag/nex_ag/audit_evidence_api.py",
        '"server_selected": True',
    ),
    TokenRequirement(
        "event_sql_limit",
        "services/_shared/nex_runtime/operational_events.py",
        "LIMIT :limit",
    ),
    TokenRequirement(
        "quality_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_resilience_performance_boundary_audit.py",
    ),
    TokenRequirement(
        "docs_index",
        "docs/README.md",
        "0871_ag_resilience_performance_boundary_audit.md",
    ),
)


def run_ag_resilience_performance_boundary_audit(
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
        for name in SOURCE_TABLES
    ]
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "required_tokens_present": all(item["present"] for item in tokens),
        "s87_closed": _group_present(tokens, "s87_closed"),
        "pool_foundation_reusable": all(
            _group_present(tokens, group)
            for group in (
                "pool_settings",
                "api_pool_default",
                "pool_timeout",
                "statement_timeout",
                "workload_split",
            )
        ),
        "bounded_query_foundation_reusable": all(
            _group_present(tokens, group)
            for group in (
                "query_options",
                "bounded_query_limit",
                "cursor_validation",
                "event_sql_limit",
            )
        ),
        "server_side_selection_preserved": _group_present(
            tokens, "audit_server_selection"
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
        else "ag_resilience_performance_boundary_failed",
        "boundary": BOUNDARY,
        "decision": {
            "owner": "nex-ag",
            "target_surface": "admin_read_and_evidence_operations",
            "new_table_required": False,
            "targeted_index_migration_allowed": True,
            "api_pool_size_default": 5,
            "api_max_overflow_default": 10,
            "pool_timeout_seconds_default": 30.0,
            "api_statement_timeout_ms_default": 30000,
            "worker_pool_size_default": 3,
            "worker_max_overflow_default": 3,
            "worker_statement_timeout_ms_default": 60000,
            "default_page_size": 50,
            "max_page_size": 500,
            "load_test_mode": "bounded_non_destructive",
        },
        "implementation_gaps": [
            "explicit_performance_budget_contract",
            "stable_bounded_pagination",
            "concurrency_admission_and_load_shedding",
            "source_timeout_and_failure_isolation",
            "pool_and_latency_operations_projection",
            "query_index_contract_hardening",
            "postgres_bounded_load_smoke",
        ],
        "deferred_scope": [
            "distributed_load_test_cluster",
            "automatic_pool_autoscaling",
            "cross_service_transaction_coordination",
            "retention_archive_and_physical_purge_s89",
            "ag_mvp_acceptance_and_cx_transition_s90",
        ],
        "required_paths": paths,
        "required_tokens": tokens,
        "identifiers": identifiers,
        "checks": checks,
        "issues": issues,
    }


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _group_present(items: list[dict[str, Any]], group: str) -> bool:
    return any(
        item.get("group") == group and item.get("present") is True
        for item in items
    )


def summary_line(evidence: Mapping[str, Any]) -> str:
    status = str(evidence.get("status") or "FAIL").lower()
    if status != "pass":
        return (
            "ag_resilience_performance_boundary=fail "
            f"issues={len(evidence.get('issues') or [])}"
        )
    decision = evidence.get("decision") or {}
    return (
        "ag_resilience_performance_boundary=pass "
        f"page_max={decision.get('max_page_size')} "
        f"pool={decision.get('api_pool_size_default')}+"
        f"{decision.get('api_max_overflow_default')} "
        f"new_table={decision.get('new_table_required')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_ag_resilience_performance_boundary_audit()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
