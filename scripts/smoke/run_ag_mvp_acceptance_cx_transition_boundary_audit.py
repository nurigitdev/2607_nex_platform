#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "ag_mvp_acceptance_cx_transition_boundary_audit.v1"
SLICE_ID = "0891"
REQUIREMENT = "S90"
BOUNDARY = "ag_service_mvp_acceptance_and_cx_transition"


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
        "s89_closure",
        "scripts/smoke/run_s89_ag_audit_retention_closure.py",
    ),
    RequiredPath("ag_runtime", "services/nex-ag/nex_ag/main.py"),
    RequiredPath("ag_readiness", "services/nex-ag/nex_ag/readiness.py"),
    RequiredPath(
        "ag_operations",
        "services/nex-ag/nex_ag/operations.py",
    ),
    RequiredPath(
        "contract_validator",
        "scripts/quality/validate_contracts.py",
    ),
    RequiredPath(
        "postgres_smoke_suite",
        "scripts/smoke/run_postgres_test_smoke_suite.py",
    ),
    RequiredPath("testing_strategy", "docs/34_testing_strategy_v0_1_detail.md"),
    RequiredPath("quality_gate", "scripts/quality/run_quality_gate.sh"),
    RequiredPath("docs_index", "docs/README.md"),
    RequiredPath(
        "slice_doc",
        "docs/slices/0891_ag_mvp_acceptance_cx_transition_boundary_audit.md",
    ),
)

TOKEN_REQUIREMENTS = (
    TokenRequirement(
        "s89_closed",
        "scripts/smoke/run_s89_ag_audit_retention_closure.py",
        "s89_ag_audit_retention_closure.v1",
    ),
    TokenRequirement(
        "ag_app",
        "services/nex-ag/nex_ag/main.py",
        "app = build_service_app(SERVICE_SPEC)",
    ),
    TokenRequirement(
        "readiness",
        "services/nex-ag/nex_ag/readiness.py",
        "def build_readiness_projection",
    ),
    TokenRequirement(
        "operations",
        "services/nex-ag/nex_ag/operations.py",
        "class OperationQueryOptions",
    ),
    TokenRequirement(
        "contracts",
        "scripts/quality/validate_contracts.py",
        "def validate_contract_tree",
    ),
    TokenRequirement(
        "postgres_protection",
        "scripts/smoke/run_postgres_test_smoke_suite.py",
        'SMOKE_ENV = "NEX_POSTGRES_TEST_SMOKE_SUITE"',
    ),
    TokenRequirement(
        "coverage_policy",
        "docs/34_testing_strategy_v0_1_detail.md",
        "Branch coverage",
    ),
    TokenRequirement(
        "quality_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_mvp_acceptance_cx_transition_boundary_audit.py",
    ),
    TokenRequirement(
        "docs_index",
        "docs/README.md",
        "0891_ag_mvp_acceptance_cx_transition_boundary_audit.md",
    ),
)


def run_ag_mvp_acceptance_cx_transition_boundary_audit(
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
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "required_tokens_present": all(item["present"] for item in tokens),
        "s89_closed": _group_present(tokens, "s89_closed"),
        "ag_runtime_reusable": all(
            _group_present(tokens, group)
            for group in ("ag_app", "readiness", "operations")
        ),
        "acceptance_tooling_reusable": all(
            _group_present(tokens, group)
            for group in (
                "contracts",
                "postgres_protection",
                "coverage_policy",
            )
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
    passed = all(checks.values())
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": SLICE_ID,
        "requirement": REQUIREMENT,
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None if passed else "ag_mvp_acceptance_cx_transition_boundary_failed"
        ),
        "boundary": BOUNDARY,
        "decision": {
            "owner": "nex-ag",
            "acceptance_scope": "nex_ag_service_mvp",
            "product_wide_release_approval": False,
            "evidence_is_server_derived": True,
            "actual_test_database_evidence_required": True,
            "full_regression_and_branch_coverage_required": True,
            "new_table_required": False,
            "existing_ag_records_mutated": False,
            "cx_transition_requires_all_blocking_gates_pass": True,
            "transition_target": "nex-cx",
            "decision_status": "FROZEN",
        },
        "blocking_gate_families": [
            "ag_requirement_closures",
            "contract_validation",
            "unit_and_regression_tests",
            "statement_and_branch_coverage",
            "actual_nex_ag_test_smoke",
            "privacy_and_failure_runbooks",
            "cx_handoff_readiness",
        ],
        "deferred_scope": [
            "product_wide_mvp_release_approval",
            "production_deployment_certification",
            "production_identity_and_external_notification_integration",
            "distributed_load_and_disaster_recovery_certification",
            "nex_cx_feature_implementation_after_transition",
        ],
        "slice_plan": [
            "0891_boundary_audit",
            "0892_acceptance_policy",
            "0893_evidence_inventory",
            "0894_acceptance_evaluator",
            "0895_protected_acceptance_api",
            "0896_contract_and_operations_hardening",
            "0897_transition_handoff_package",
            "0898_actual_postgresql_acceptance_smoke",
            "0899_privacy_failure_transition_runbook",
            "0900_s90_closure",
        ],
        "required_paths": paths,
        "required_tokens": tokens,
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
            "ag_mvp_acceptance_cx_transition_boundary=fail "
            f"issues={len(evidence.get('issues') or [])}"
        )
    decision = evidence.get("decision") or {}
    return (
        "ag_mvp_acceptance_cx_transition_boundary=pass "
        f"scope={decision.get('acceptance_scope')} "
        f"target={decision.get('transition_target')} "
        f"new_table={decision.get('new_table_required')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_ag_mvp_acceptance_cx_transition_boundary_audit()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
