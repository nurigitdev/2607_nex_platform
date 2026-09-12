#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s68_operator_review_case_decision_lifecycle_closure.v1"

REQUIRED_FILES = (
    "services/nex-ag/nex_ag/operator_review_cases.py",
    "services/nex-ag/nex_ag/operations.py",
    "services/nex-ag/README.md",
    "contracts/schemas/service/nex_ag/operator_review_case_workbench.v1.schema.json",
    "contracts/schemas/service/nex_ag/operations_projection.v1.schema.json",
    "contracts/examples/operations/ag_operator_review_case_action_outcomes.mock_success.json",
    "contracts/examples/operations/ag_operator_review_case_assignment_workload.mock_success.json",
    "contracts/examples/operations/ag_operator_review_case_closure_packet.mock_success.json",
    "contracts/openapi/nex-ag.openapi.yaml",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ag_operator_review_case_decision_lifecycle_boundary_audit.py",
    "scripts/smoke/run_ag_operator_review_case_lifecycle_postgres_smoke.py",
    "scripts/smoke/run_s68_operator_review_case_decision_lifecycle_closure.py",
    "tests/test_ag_operator_review_case_decision_lifecycle_boundary_audit.py",
    "tests/test_ag_operator_review_case_lifecycle_postgres_smoke.py",
    "tests/test_nex_ag_operator_review_cases.py",
    "tests/test_nex_ag_operations.py",
    "docs/README.md",
    "docs/slices/0671_ag_operator_review_case_decision_lifecycle_boundary_audit.md",
    "docs/slices/0672_ag_operator_review_case_action_timeline_projection_hardening.md",
    "docs/slices/0673_ag_operator_review_case_action_outcome_read_model.md",
    "docs/slices/0674_ag_operator_review_case_assignment_workload_projection.md",
    "docs/slices/0675_ag_operator_review_case_closure_packet_foundation.md",
    "docs/slices/0676_ag_operator_review_case_closure_packet_route_wiring.md",
    "docs/slices/0677_ag_operator_review_case_lifecycle_dashboard_integration.md",
    "docs/slices/0678_ag_operator_review_case_lifecycle_contract_openapi.md",
    "docs/slices/0679_ag_operator_review_case_lifecycle_postgresql_smoke.md",
    "docs/slices/0680_s68_operator_review_case_decision_lifecycle_closure.md",
)

TOKEN_CHECKS = (
    (
        "quality_gate_lifecycle_postgres_smoke",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_case_lifecycle_postgres_smoke.py",
    ),
    (
        "quality_gate_s68_closure",
        "scripts/quality/run_quality_gate.sh",
        "run_s68_operator_review_case_decision_lifecycle_closure.py",
    ),
    (
        "action_outcomes_schema_version",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "ag_operator_review_case_action_outcomes.v1",
    ),
    (
        "assignment_workload_schema_version",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "ag_operator_review_case_assignment_workload.v1",
    ),
    (
        "closure_packet_schema_version",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "ag_operator_review_case_closure_packet.v1",
    ),
    (
        "closure_packet_route",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "/admin/v1/operator-review/cases/{case_id}/closure-packet",
    ),
    (
        "dashboard_assignment_workload",
        "services/nex-ag/nex_ag/operations.py",
        "assignment_workload",
    ),
    (
        "contract_action_outcomes",
        "contracts/schemas/service/nex_ag/operator_review_case_workbench.v1.schema.json",
        "case_action_outcomes_response",
    ),
    (
        "contract_assignment_workload",
        "contracts/schemas/service/nex_ag/operator_review_case_workbench.v1.schema.json",
        "case_assignment_workload_response",
    ),
    (
        "contract_closure_packet",
        "contracts/schemas/service/nex_ag/operator_review_case_workbench.v1.schema.json",
        "case_closure_packet_response",
    ),
    (
        "openapi_closure_packet_route",
        "contracts/openapi/nex-ag.openapi.yaml",
        "/admin/v1/operator-review/cases/{case_id}/closure-packet",
    ),
    (
        "postgres_smoke_opt_in",
        "scripts/smoke/run_ag_operator_review_case_lifecycle_postgres_smoke.py",
        "NEX_AG_OPERATOR_REVIEW_CASE_LIFECYCLE_POSTGRES_SMOKE",
    ),
)


def run_s68_operator_review_case_decision_lifecycle_closure(
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
        "failure_code": None if passed else "s68_closure_failed",
        "slice_range": "0671-0680",
        "boundary": "ag_owned_operator_review_case_decision_lifecycle",
        "source_tables": [
            "ag_op_cases",
            "service_operational_events",
            "ag_op_notes",
            "ag_ev_exports",
        ],
        "closure_packet_storage": "read_model_only_not_persisted",
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
            "s68_operator_review_case_decision_lifecycle_closure=pass "
            f"slice_range={evidence['slice_range']} "
            f"required_files={evidence['summary']['required_file_count']} "
            f"boundary={evidence['boundary']} "
            f"closure_packet_storage={evidence['closure_packet_storage']} "
            f"smoke={evidence['postgres_smoke']}"
        )
    return (
        "s68_operator_review_case_decision_lifecycle_closure=fail "
        f"reason={evidence.get('failure_code')} "
        f"missing_files={evidence['summary']['missing_file_count']} "
        f"missing_tokens={evidence['summary']['missing_token_count']}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the S68 operator review case decision lifecycle closure."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_s68_operator_review_case_decision_lifecycle_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
