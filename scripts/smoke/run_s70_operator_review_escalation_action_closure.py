#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s70_operator_review_escalation_action_closure.v1"

REQUIRED_FILES = (
    "services/nex-ag/nex_ag/operator_review_cases.py",
    "services/nex-ag/nex_ag/operations.py",
    "services/nex-ag/README.md",
    "database/nex-ag/migrations/0692_ag_operator_review_escalation_persistence.sql",
    "contracts/schemas/service/nex_ag/operator_review_case.v1.schema.json",
    "contracts/schemas/service/nex_ag/operations_projection.v1.schema.json",
    "contracts/examples/operations/ag_operator_review_escalation_list.mock_success.json",
    (
        "contracts/examples/operations/"
        "ag_operator_review_escalation_action_mutation.mock_success.json"
    ),
    (
        "contracts/tests/negative/operations/"
        "ag_operator_review_escalation.notification_payload_leak.json"
    ),
    "contracts/openapi/nex-ag.openapi.yaml",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ag_operator_review_escalation_action_boundary_audit.py",
    "scripts/smoke/run_ag_operator_review_escalation_privacy_regression.py",
    "scripts/smoke/run_ag_operator_review_escalation_postgres_smoke.py",
    "scripts/smoke/run_s70_operator_review_escalation_action_closure.py",
    "tests/test_ag_operator_review_escalation_action_boundary_audit.py",
    "tests/test_ag_operator_review_escalation_privacy_regression.py",
    "tests/test_ag_operator_review_escalation_postgres_smoke.py",
    "tests/test_s70_operator_review_escalation_action_closure.py",
    "tests/test_nex_ag_operator_review_cases.py",
    "tests/test_nex_ag_operations.py",
    "docs/README.md",
    "docs/slices/0691_ag_operator_review_escalation_action_boundary_audit.md",
    "docs/slices/0692_ag_operator_review_escalation_persistence.md",
    "docs/slices/0693_ag_operator_review_escalation_action_state_machine.md",
    "docs/slices/0694_ag_operator_review_escalation_action_route_wiring.md",
    "docs/slices/0695_ag_operator_review_escalation_read_model_routes.md",
    "docs/slices/0696_ag_operator_review_escalation_operations_dashboard.md",
    "docs/slices/0697_ag_operator_review_escalation_contract_openapi.md",
    "docs/slices/0698_ag_operator_review_escalation_privacy_regression.md",
    "docs/slices/0699_ag_operator_review_escalation_postgresql_smoke.md",
    "docs/slices/0700_s70_operator_review_escalation_action_closure.md",
)

TOKEN_CHECKS = (
    (
        "quality_gate_boundary_audit",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_escalation_action_boundary_audit.py",
    ),
    (
        "quality_gate_privacy_regression",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_escalation_privacy_regression.py",
    ),
    (
        "quality_gate_postgres_smoke",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_escalation_postgres_smoke.py",
    ),
    (
        "quality_gate_s70_closure",
        "scripts/quality/run_quality_gate.sh",
        "run_s70_operator_review_escalation_action_closure.py",
    ),
    (
        "migration_table",
        "database/nex-ag/migrations/0692_ag_operator_review_escalation_persistence.sql",
        "CREATE TABLE IF NOT EXISTS ag_op_escalations",
    ),
    (
        "store_table_constant",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        'AG_OPERATOR_REVIEW_ESCALATION_TABLE = "ag_op_escalations"',
    ),
    (
        "escalation_record_schema_version",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "ag_operator_review_escalation.v1",
    ),
    (
        "escalation_list_schema_version",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "ag_operator_review_escalation_list.v1",
    ),
    (
        "escalation_action_schema_version",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "ag_operator_review_escalation_action.v1",
    ),
    (
        "escalation_action_mutation_schema_version",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "ag_operator_review_escalation_action_mutation.v1",
    ),
    (
        "escalation_event_type",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "ag.operator_review_escalation_action.recorded",
    ),
    (
        "escalation_list_route",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "/admin/v1/operator-review/escalations",
    ),
    (
        "escalation_action_route",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "/admin/v1/operator-review/escalations/{escalation_id}/actions",
    ),
    (
        "escalation_action_state_machine",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "def apply_operator_review_escalation_action",
    ),
    (
        "escalation_idempotency_guard",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "required_escalation_action_idempotency_key",
    ),
    (
        "dashboard_section",
        "services/nex-ag/nex_ag/operations.py",
        "operator_review_escalations",
    ),
    (
        "issue_candidate_rule",
        "services/nex-ag/nex_ag/operations.py",
        "operator_review_escalation_action_required.v1",
    ),
    (
        "contract_list_response",
        "contracts/schemas/service/nex_ag/operator_review_case.v1.schema.json",
        "escalation_list_response",
    ),
    (
        "contract_action_mutation",
        "contracts/schemas/service/nex_ag/operator_review_case.v1.schema.json",
        "escalation_action_mutation_response",
    ),
    (
        "operations_dashboard_section",
        "contracts/schemas/service/nex_ag/operations_projection.v1.schema.json",
        "ag_operator_review_escalation_dashboard_section.v1",
    ),
    (
        "openapi_list_route",
        "contracts/openapi/nex-ag.openapi.yaml",
        "/admin/v1/operator-review/escalations:",
    ),
    (
        "openapi_action_route",
        "contracts/openapi/nex-ag.openapi.yaml",
        "/admin/v1/operator-review/escalations/{escalation_id}/actions:",
    ),
    (
        "privacy_forbidden_values",
        "scripts/smoke/run_ag_operator_review_escalation_privacy_regression.py",
        "FORBIDDEN_VALUES",
    ),
    (
        "postgres_smoke_opt_in",
        "scripts/smoke/run_ag_operator_review_escalation_postgres_smoke.py",
        "NEX_AG_OPERATOR_REVIEW_ESCALATION_POSTGRES_SMOKE",
    ),
    (
        "postgres_smoke_real_test_db_env",
        "docs/slices/0699_ag_operator_review_escalation_postgresql_smoke.md",
        "nex_ag_test",
    ),
)


def run_s70_operator_review_escalation_action_closure(
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
        "failure_code": None if passed else "s70_closure_failed",
        "slice_range": "0691-0700",
        "boundary": "ag_owned_operator_review_escalation_action_loop",
        "source_tables": [
            "ag_op_cases",
            "ag_op_escalations",
            "service_operational_events",
        ],
        "persisted_table": "ag_op_escalations",
        "action_history": "service_operational_events_first",
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
            "s70_operator_review_escalation_action_closure=pass "
            f"slice_range={evidence['slice_range']} "
            f"required_files={evidence['summary']['required_file_count']} "
            f"boundary={evidence['boundary']} "
            f"table={evidence['persisted_table']} "
            f"action_history={evidence['action_history']} "
            f"smoke={evidence['postgres_smoke']} "
            f"privacy={evidence['privacy_regression']}"
        )
    return (
        "s70_operator_review_escalation_action_closure=fail "
        f"reason={evidence.get('failure_code')} "
        f"missing_files={evidence['summary']['missing_file_count']} "
        f"missing_tokens={evidence['summary']['missing_token_count']}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the S70 operator review escalation action closure."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_s70_operator_review_escalation_action_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
