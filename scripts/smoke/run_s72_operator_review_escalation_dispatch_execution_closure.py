#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s72_operator_review_escalation_dispatch_execution_closure.v1"

REQUIRED_FILES = (
    "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
    "services/nex-ag/nex_ag/operator_review_cases.py",
    "services/nex-ag/nex_ag/operations.py",
    "services/nex-ag/README.md",
    "contracts/schemas/service/nex_ag/operations_projection.v1.schema.json",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ag_operator_review_escalation_dispatch_execution_worker_boundary_audit.py",
    "scripts/smoke/run_ag_operator_review_escalation_dispatch_execution_postgres_smoke.py",
    "scripts/smoke/run_s72_operator_review_escalation_dispatch_execution_closure.py",
    "tests/test_ag_operator_review_escalation_dispatch_execution_worker_boundary_audit.py",
    "tests/test_ag_operator_review_escalation_dispatch_execution_postgres_smoke.py",
    "tests/test_s72_operator_review_escalation_dispatch_execution_closure.py",
    "tests/test_nex_ag_operator_review_dispatch_execution.py",
    "tests/test_nex_ag_operations.py",
    "docs/README.md",
    "docs/slices/0712_ag_operator_review_escalation_dispatch_execution_worker_boundary_audit.md",
    "docs/slices/0713_ag_escalation_dispatch_execution_provider_result_contract.md",
    "docs/slices/0714_ag_escalation_dispatch_mock_provider_adapter.md",
    "docs/slices/0715_ag_escalation_dispatch_execution_transition_planner.md",
    "docs/slices/0716_ag_escalation_dispatch_execution_worker_run_once.md",
    "docs/slices/0717_ag_escalation_dispatch_execution_result_persistence.md",
    "docs/slices/0718_ag_escalation_dispatch_execution_operations_dashboard.md",
    "docs/slices/0719_ag_escalation_dispatch_execution_postgresql_smoke.md",
    "docs/slices/0720_s72_operator_review_escalation_dispatch_execution_closure.md",
)

TOKEN_CHECKS = (
    (
        "quality_gate_boundary_audit",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_escalation_dispatch_execution_worker_boundary_audit.py",
    ),
    (
        "quality_gate_postgres_smoke",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_escalation_dispatch_execution_postgres_smoke.py",
    ),
    (
        "quality_gate_s72_closure",
        "scripts/quality/run_quality_gate.sh",
        "run_s72_operator_review_escalation_dispatch_execution_closure.py",
    ),
    (
        "provider_catalog_schema",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "ag_operator_review_escalation_dispatch_execution_provider_catalog.v1",
    ),
    (
        "execution_result_schema",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "ag_operator_review_escalation_dispatch_execution_result.v1",
    ),
    (
        "transition_plan_schema",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "ag_operator_review_escalation_dispatch_execution_transition_plan.v1",
    ),
    (
        "worker_run_schema",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "ag_operator_review_escalation_dispatch_execution_worker_run.v1",
    ),
    (
        "result_metadata_schema",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "ag_operator_review_escalation_dispatch_execution_result_metadata.v1",
    ),
    (
        "mock_provider_adapter",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "MockDispatchExecutionProvider",
    ),
    (
        "transition_planner",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "def build_dispatch_execution_transition_plan",
    ),
    (
        "run_once_worker",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "def run_dispatch_execution_worker_once",
    ),
    (
        "result_metadata_persistence",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "def record_dispatch_execution_result_metadata",
    ),
    (
        "existing_dispatch_table",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        'AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_TABLE = "ag_op_esc_dispatches"',
    ),
    (
        "existing_dispatch_state_machine",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "def apply_operator_review_escalation_dispatch_action",
    ),
    (
        "dashboard_execution_summary",
        "services/nex-ag/nex_ag/operations.py",
        "execution_summary",
    ),
    (
        "dashboard_last_execution_result",
        "services/nex-ag/nex_ag/operations.py",
        "last_execution_result",
    ),
    (
        "operations_contract_execution_summary",
        "contracts/schemas/service/nex_ag/operations_projection.v1.schema.json",
        "execution_summary",
    ),
    (
        "postgres_smoke_opt_in",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_execution_postgres_smoke.py",
        "NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_EXECUTION_POSTGRES_SMOKE",
    ),
    (
        "postgres_smoke_real_test_db_env",
        "docs/slices/0719_ag_escalation_dispatch_execution_postgresql_smoke.md",
        "nex_ag_test",
    ),
    (
        "s72_docs_indexed",
        "docs/README.md",
        "0720_s72_operator_review_escalation_dispatch_execution_closure.md",
    ),
)


def run_s72_operator_review_escalation_dispatch_execution_closure(
    root: Path = ROOT,
) -> dict[str, Any]:
    required_file_results = _required_file_results(root)
    token_results = _token_results(root)
    passed = all(item["present"] for item in required_file_results) and all(
        item["present"] for item in token_results
    )
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "s72_closure_failed",
        "slice_range": "0712-0720",
        "boundary": "ag_owned_operator_review_escalation_dispatch_execution_worker",
        "source_tables": [
            "ag_op_cases",
            "ag_op_escalations",
            "ag_op_esc_dispatches",
            "service_operational_events",
        ],
        "persisted_table": "ag_op_esc_dispatches",
        "worker_mode": "bounded_run_once",
        "provider_execution": "mock_first_only",
        "live_notification_delivery": "deferred",
        "external_incident_sync": "deferred",
        "result_storage": "safe_hashes_statuses_counters_only",
        "dashboard_visibility": "execution_summary_and_item_result_projection",
        "postgres_smoke": "test_db_protected",
        "required_files": required_file_results,
        "token_checks": token_results,
        "summary": {
            "required_file_count": len(required_file_results),
            "missing_file_count": sum(
                1 for item in required_file_results if not item["present"]
            ),
            "token_check_count": len(token_results),
            "missing_token_count": sum(
                1 for item in token_results if not item["present"]
            ),
        },
    }


def _required_file_results(root: Path) -> list[dict[str, Any]]:
    return [
        {"path": path, "present": (root / path).is_file()} for path in REQUIRED_FILES
    ]


def _token_results(root: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for check_id, relative_path, token in TOKEN_CHECKS:
        path = root / relative_path
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        results.append(
            {
                "check_id": check_id,
                "path": relative_path,
                "present": token in text,
            }
        )
    return results


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        return (
            "s72_operator_review_escalation_dispatch_execution_closure=pass "
            f"slice_range={evidence['slice_range']} "
            f"required_files={evidence['summary']['required_file_count']} "
            f"boundary={evidence['boundary']} "
            f"table={evidence['persisted_table']} "
            f"worker={evidence['worker_mode']} "
            f"provider={evidence['provider_execution']} "
            f"smoke={evidence['postgres_smoke']}"
        )
    return (
        "s72_operator_review_escalation_dispatch_execution_closure=fail "
        f"reason={evidence.get('failure_code')} "
        f"missing_files={evidence['summary']['missing_file_count']} "
        f"missing_tokens={evidence['summary']['missing_token_count']}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the S72 operator review escalation dispatch execution closure."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_s72_operator_review_escalation_dispatch_execution_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
