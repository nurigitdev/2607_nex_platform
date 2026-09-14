#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s76_operator_review_escalation_dispatch_daemon_api_closure.v1"

REQUIRED_FILES = (
    "services/nex-ag/nex_ag/operations.py",
    "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
    "contracts/openapi/nex-ag.openapi.yaml",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_api_boundary_audit.py",
    "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_api_postgres_smoke.py",
    "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_api_privacy_regression.py",
    "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_api_runbook_evidence.py",
    "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_api_admission_guard_evidence.py",
    "scripts/smoke/run_s76_operator_review_escalation_dispatch_daemon_api_closure.py",
    "tests/test_ag_operator_review_escalation_dispatch_daemon_api_boundary_audit.py",
    "tests/test_ag_operator_review_escalation_dispatch_daemon_api_postgres_smoke.py",
    "tests/test_ag_operator_review_escalation_dispatch_daemon_api_privacy_regression.py",
    "tests/test_ag_operator_review_escalation_dispatch_daemon_api_runbook_evidence.py",
    "tests/test_ag_operator_review_escalation_dispatch_daemon_api_admission_guard_evidence.py",
    "tests/test_s76_operator_review_escalation_dispatch_daemon_api_closure.py",
    "tests/test_nex_ag_operations.py",
    "docs/README.md",
    "docs/slices/0751_ag_escalation_dispatch_daemon_api_boundary_audit.md",
    "docs/slices/0752_ag_escalation_dispatch_daemon_tick_plan_api_route.md",
    "docs/slices/0753_ag_escalation_dispatch_daemon_tick_once_api_route.md",
    "docs/slices/0754_ag_escalation_dispatch_daemon_api_postgres_smoke.md",
    "docs/slices/0755_ag_escalation_dispatch_daemon_api_privacy_regression.md",
    "docs/slices/0756_ag_escalation_dispatch_daemon_api_contract_hardening.md",
    "docs/slices/0757_ag_escalation_dispatch_daemon_api_runtime_openapi_parity.md",
    "docs/slices/0758_ag_escalation_dispatch_daemon_api_runbook_evidence.md",
    "docs/slices/0759_ag_escalation_dispatch_daemon_api_admission_guard_evidence.md",
    "docs/slices/0760_s76_operator_review_escalation_dispatch_daemon_api_closure.md",
)

TOKEN_CHECKS = (
    (
        "quality_gate_api_boundary",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_escalation_dispatch_daemon_api_boundary_audit.py",
    ),
    (
        "quality_gate_api_postgres_smoke",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_escalation_dispatch_daemon_api_postgres_smoke.py",
    ),
    (
        "quality_gate_api_privacy_regression",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_escalation_dispatch_daemon_api_privacy_regression.py",
    ),
    (
        "quality_gate_api_runbook",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_escalation_dispatch_daemon_api_runbook_evidence.py",
    ),
    (
        "quality_gate_api_admission_guard",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_escalation_dispatch_daemon_api_admission_guard_evidence.py",
    ),
    (
        "quality_gate_s76_closure",
        "scripts/quality/run_quality_gate.sh",
        "run_s76_operator_review_escalation_dispatch_daemon_api_closure.py",
    ),
    (
        "operations_get_tick_plan_operation_id",
        "services/nex-ag/nex_ag/operations.py",
        "getAgOperatorReviewDispatchDaemonTickPlan",
    ),
    (
        "operations_post_tick_plan_operation_id",
        "services/nex-ag/nex_ag/operations.py",
        "postAgOperatorReviewDispatchDaemonTickPlan",
    ),
    (
        "operations_post_tick_once_operation_id",
        "services/nex-ag/nex_ag/operations.py",
        "postAgOperatorReviewDispatchDaemonTickOnce",
    ),
    (
        "operations_tick_plan_projection_builder",
        "services/nex-ag/nex_ag/operations.py",
        "def build_operator_review_escalation_dispatch_daemon_tick_plan_api_projection",
    ),
    (
        "operations_tick_once_projection_builder",
        "services/nex-ag/nex_ag/operations.py",
        "def build_operator_review_escalation_dispatch_daemon_tick_once_api_projection",
    ),
    (
        "daemon_control_confirm_guard",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "confirm_tick_required",
    ),
    (
        "openapi_tick_plan_path",
        "contracts/openapi/nex-ag.openapi.yaml",
        "/admin/v1/operator-review/dispatch-daemon/tick-plan",
    ),
    (
        "openapi_tick_once_path",
        "contracts/openapi/nex-ag.openapi.yaml",
        "/admin/v1/operator-review/dispatch-daemon/tick-once",
    ),
    (
        "openapi_control_request_schema",
        "contracts/openapi/nex-ag.openapi.yaml",
        "AgOperatorReviewDispatchDaemonControlRequest",
    ),
    (
        "openapi_tick_plan_projection_schema",
        "contracts/openapi/nex-ag.openapi.yaml",
        "AgOperatorReviewDispatchDaemonTickPlanProjection",
    ),
    (
        "openapi_tick_once_projection_schema",
        "contracts/openapi/nex-ag.openapi.yaml",
        "AgOperatorReviewDispatchDaemonTickOnceProjection",
    ),
    (
        "postgres_api_smoke_opt_in",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_api_postgres_smoke.py",
        "NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_DAEMON_API_POSTGRES_SMOKE",
    ),
    (
        "postgres_api_smoke_real_test_db_doc",
        "docs/slices/0754_ag_escalation_dispatch_daemon_api_postgres_smoke.md",
        "nex_ag_test",
    ),
    (
        "privacy_regression_summary",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_api_privacy_regression.py",
        "raw_fields_absent",
    ),
    (
        "runbook_runtime_route_evidence",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_api_runbook_evidence.py",
        "runtime_routes_ready",
    ),
    (
        "admission_guard_summary",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_api_admission_guard_evidence.py",
        "mutation_only_confirmed",
    ),
    (
        "s76_docs_indexed",
        "docs/README.md",
        "0759_ag_escalation_dispatch_daemon_api_admission_guard_evidence.md",
    ),
)


def run_s76_operator_review_escalation_dispatch_daemon_api_closure(
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
        "failure_code": None if passed else "s76_closure_failed",
        "slice_range": "0751-0760",
        "boundary": "ag_owned_operator_review_escalation_dispatch_daemon_protected_api",
        "source_table": "ag_op_esc_dispatches",
        "new_tables": [],
        "api_routes": [
            "GET /admin/v1/operator-review/dispatch-daemon/tick-plan",
            "POST /admin/v1/operator-review/dispatch-daemon/tick-plan",
            "POST /admin/v1/operator-review/dispatch-daemon/tick-once",
        ],
        "protected_control": (
            "service_token_auth_plus_confirmed_tick_once_admission"
        ),
        "runtime_surfaces": [
            "api_boundary_audit",
            "non_mutating_tick_plan_get_post",
            "confirmed_tick_once_post",
            "test_db_postgres_api_smoke",
            "privacy_regression",
            "static_openapi_contract",
            "runtime_openapi_parity",
            "operator_runbook_evidence",
            "admission_guard_matrix",
        ],
        "postgres_smoke": "test_db_protected_api_tick_plan_and_tick_once",
        "privacy_regression": "no_raw_provider_payload_token_database_url_or_storage_path",
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
            "s76_operator_review_escalation_dispatch_daemon_api_closure=pass "
            f"slice_range={evidence['slice_range']} "
            f"required_files={evidence['summary']['required_file_count']} "
            f"boundary={evidence['boundary']} "
            f"routes={len(evidence['api_routes'])} "
            f"smoke={evidence['postgres_smoke']}"
        )
    return (
        "s76_operator_review_escalation_dispatch_daemon_api_closure=fail "
        f"reason={evidence.get('failure_code')} "
        f"missing_files={evidence['summary']['missing_file_count']} "
        f"missing_tokens={evidence['summary']['missing_token_count']}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the S76 operator review escalation dispatch daemon API closure."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_s76_operator_review_escalation_dispatch_daemon_api_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
