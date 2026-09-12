#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s69_operator_review_case_sla_escalation_closure.v1"

REQUIRED_FILES = (
    "services/nex-ag/nex_ag/operator_review_cases.py",
    "services/nex-ag/nex_ag/operations.py",
    "services/nex-ag/README.md",
    "contracts/schemas/service/nex_ag/operator_review_case_workbench.v1.schema.json",
    "contracts/schemas/service/nex_ag/operations_projection.v1.schema.json",
    "contracts/examples/operations/ag_operator_review_case_sla_policy.mock_success.json",
    "contracts/examples/operations/ag_operator_review_case_aging.mock_success.json",
    "contracts/examples/operations/ag_operator_review_case_escalations.mock_success.json",
    "contracts/tests/negative/operations/ag_operator_review_case_sla_policy.raw_prompt_leak.json",
    "contracts/tests/negative/operations/ag_operator_review_case_aging.raw_case_comment_leak.json",
    "contracts/tests/negative/operations/ag_operator_review_case_escalations.notification_payload_leak.json",
    "contracts/openapi/nex-ag.openapi.yaml",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ag_operator_review_case_sla_escalation_boundary_audit.py",
    "scripts/smoke/run_ag_operator_review_case_sla_escalation_privacy_regression.py",
    "scripts/smoke/run_ag_operator_review_case_sla_escalation_postgres_smoke.py",
    "scripts/smoke/run_s69_operator_review_case_sla_escalation_closure.py",
    "tests/test_ag_operator_review_case_sla_escalation_boundary_audit.py",
    "tests/test_ag_operator_review_case_sla_escalation_privacy_regression.py",
    "tests/test_ag_operator_review_case_sla_escalation_postgres_smoke.py",
    "tests/test_s69_operator_review_case_sla_escalation_closure.py",
    "tests/test_nex_ag_operator_review_cases.py",
    "tests/test_nex_ag_operations.py",
    "docs/README.md",
    "docs/slices/0681_ag_operator_review_case_sla_escalation_boundary_audit.md",
    "docs/slices/0682_ag_operator_review_case_sla_policy_read_model.md",
    "docs/slices/0683_ag_operator_review_case_aging_stale_assignment.md",
    "docs/slices/0684_ag_operator_review_case_escalation_candidate_projection.md",
    "docs/slices/0685_ag_operator_review_case_sla_escalation_routes.md",
    "docs/slices/0686_ag_operator_review_case_sla_escalation_dashboard.md",
    "docs/slices/0687_ag_operator_review_case_sla_escalation_contract_openapi.md",
    "docs/slices/0688_ag_operator_review_case_sla_escalation_privacy_regression.md",
    "docs/slices/0689_ag_operator_review_case_sla_escalation_postgresql_smoke.md",
    "docs/slices/0690_s69_operator_review_case_sla_escalation_closure.md",
)

TOKEN_CHECKS = (
    (
        "quality_gate_boundary_audit",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_case_sla_escalation_boundary_audit.py",
    ),
    (
        "quality_gate_privacy_regression",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_case_sla_escalation_privacy_regression.py",
    ),
    (
        "quality_gate_postgres_smoke",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_case_sla_escalation_postgres_smoke.py",
    ),
    (
        "quality_gate_s69_closure",
        "scripts/quality/run_quality_gate.sh",
        "run_s69_operator_review_case_sla_escalation_closure.py",
    ),
    (
        "sla_policy_schema_version",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "ag_operator_review_case_sla_policy.v1",
    ),
    (
        "aging_schema_version",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "ag_operator_review_case_aging.v1",
    ),
    (
        "escalation_schema_version",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "ag_operator_review_case_escalations.v1",
    ),
    (
        "sla_policy_route",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "/admin/v1/operator-review/cases/sla-policy",
    ),
    (
        "aging_route",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "/admin/v1/operator-review/cases/aging",
    ),
    (
        "escalation_route",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "/admin/v1/operator-review/cases/escalations",
    ),
    (
        "dashboard_sla_aging",
        "services/nex-ag/nex_ag/operations.py",
        "sla_aging",
    ),
    (
        "dashboard_escalations",
        "services/nex-ag/nex_ag/operations.py",
        "escalations",
    ),
    (
        "contract_sla_policy_response",
        "contracts/schemas/service/nex_ag/operator_review_case_workbench.v1.schema.json",
        "case_sla_policy_response",
    ),
    (
        "contract_aging_response",
        "contracts/schemas/service/nex_ag/operator_review_case_workbench.v1.schema.json",
        "case_aging_response",
    ),
    (
        "contract_escalations_response",
        "contracts/schemas/service/nex_ag/operator_review_case_workbench.v1.schema.json",
        "case_escalations_response",
    ),
    (
        "openapi_sla_policy_route",
        "contracts/openapi/nex-ag.openapi.yaml",
        "/admin/v1/operator-review/cases/sla-policy",
    ),
    (
        "openapi_aging_route",
        "contracts/openapi/nex-ag.openapi.yaml",
        "/admin/v1/operator-review/cases/aging",
    ),
    (
        "openapi_escalations_route",
        "contracts/openapi/nex-ag.openapi.yaml",
        "/admin/v1/operator-review/cases/escalations",
    ),
    (
        "postgres_smoke_opt_in",
        "scripts/smoke/run_ag_operator_review_case_sla_escalation_postgres_smoke.py",
        "NEX_AG_OPERATOR_REVIEW_CASE_SLA_ESCALATION_POSTGRES_SMOKE",
    ),
    (
        "privacy_forbidden_values",
        "scripts/smoke/run_ag_operator_review_case_sla_escalation_privacy_regression.py",
        "FORBIDDEN_VALUES",
    ),
)


def run_s69_operator_review_case_sla_escalation_closure(
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
        "failure_code": None if passed else "s69_closure_failed",
        "slice_range": "0681-0690",
        "boundary": "ag_owned_operator_review_case_sla_escalation",
        "source_tables": ["ag_op_cases", "service_operational_events"],
        "sla_escalation_storage": "read_model_only_not_persisted",
        "notification_delivery": "deferred",
        "external_incident_sync": "deferred",
        "postgres_smoke": "test_db_protected",
        "privacy_regression": "route_surface_regression",
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
            "s69_operator_review_case_sla_escalation_closure=pass "
            f"slice_range={evidence['slice_range']} "
            f"required_files={evidence['summary']['required_file_count']} "
            f"boundary={evidence['boundary']} "
            f"storage={evidence['sla_escalation_storage']} "
            f"smoke={evidence['postgres_smoke']} "
            f"privacy={evidence['privacy_regression']}"
        )
    return (
        "s69_operator_review_case_sla_escalation_closure=fail "
        f"reason={evidence.get('failure_code')} "
        f"missing_files={evidence['summary']['missing_file_count']} "
        f"missing_tokens={evidence['summary']['missing_token_count']}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the S69 operator review case SLA/escalation closure."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_s69_operator_review_case_sla_escalation_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
