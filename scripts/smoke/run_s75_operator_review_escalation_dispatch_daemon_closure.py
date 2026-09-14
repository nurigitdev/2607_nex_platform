#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s75_operator_review_escalation_dispatch_daemon_closure.v1"

REQUIRED_FILES = (
    "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
    "services/nex-ag/nex_ag/operations.py",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_boundary_audit.py",
    "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_postgres_smoke.py",
    "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_privacy_regression.py",
    "scripts/smoke/run_s75_operator_review_escalation_dispatch_daemon_closure.py",
    "tests/test_ag_operator_review_escalation_dispatch_daemon_boundary_audit.py",
    "tests/test_ag_operator_review_escalation_dispatch_daemon_postgres_smoke.py",
    "tests/test_ag_operator_review_escalation_dispatch_daemon_privacy_regression.py",
    "tests/test_s75_operator_review_escalation_dispatch_daemon_closure.py",
    "tests/test_nex_ag_operator_review_dispatch_execution.py",
    "tests/test_nex_ag_operations.py",
    "docs/README.md",
    "docs/slices/0741_ag_escalation_dispatch_daemon_boundary_audit.md",
    "docs/slices/0742_ag_escalation_dispatch_daemon_policy_foundation.md",
    "docs/slices/0743_ag_escalation_dispatch_daemon_tick_planner.md",
    "docs/slices/0744_ag_escalation_dispatch_daemon_tick_execution.md",
    "docs/slices/0745_ag_escalation_dispatch_daemon_tick_observability.md",
    "docs/slices/0746_ag_escalation_dispatch_daemon_runtime_projection.md",
    "docs/slices/0747_ag_escalation_dispatch_daemon_control_foundation.md",
    "docs/slices/0748_ag_escalation_dispatch_daemon_postgres_smoke.md",
    "docs/slices/0749_ag_escalation_dispatch_daemon_privacy_regression.md",
    "docs/slices/0750_s75_operator_review_escalation_dispatch_daemon_closure.md",
)

TOKEN_CHECKS = (
    (
        "quality_gate_daemon_boundary",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_escalation_dispatch_daemon_boundary_audit.py",
    ),
    (
        "quality_gate_daemon_postgres_smoke",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_escalation_dispatch_daemon_postgres_smoke.py",
    ),
    (
        "quality_gate_daemon_privacy_regression",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_escalation_dispatch_daemon_privacy_regression.py",
    ),
    (
        "quality_gate_s75_closure",
        "scripts/quality/run_quality_gate.sh",
        "run_s75_operator_review_escalation_dispatch_daemon_closure.py",
    ),
    (
        "daemon_policy_schema",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "ag_operator_review_escalation_dispatch_execution_daemon_policy.v1",
    ),
    (
        "daemon_tick_plan_schema",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "ag_operator_review_escalation_dispatch_execution_daemon_tick_plan.v1",
    ),
    (
        "daemon_tick_result_schema",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "ag_operator_review_escalation_dispatch_execution_daemon_tick_result.v1",
    ),
    (
        "daemon_observability_schemas",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "ag_operator_review_escalation_dispatch_execution_daemon_tick_event.v1",
    ),
    (
        "daemon_control_request_schema",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "ag_operator_review_escalation_dispatch_execution_daemon_control_request.v1",
    ),
    (
        "daemon_control_admission_schema",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "ag_operator_review_escalation_dispatch_execution_daemon_control_admission.v1",
    ),
    (
        "daemon_tick_execution_function",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "def run_dispatch_execution_daemon_tick_once",
    ),
    (
        "daemon_control_admission_function",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "def build_dispatch_execution_daemon_control_admission",
    ),
    (
        "operations_daemon_runtime_projection",
        "services/nex-ag/nex_ag/operations.py",
        "build_operator_review_escalation_dispatch_daemon_runtime_projection",
    ),
    (
        "postgres_smoke_opt_in",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_postgres_smoke.py",
        "NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_DAEMON_POSTGRES_SMOKE",
    ),
    (
        "postgres_smoke_real_test_db_doc",
        "docs/slices/0748_ag_escalation_dispatch_daemon_postgres_smoke.md",
        "nex_ag_test",
    ),
    (
        "privacy_regression_summary",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_privacy_regression.py",
        "forbidden_absent",
    ),
    (
        "s75_docs_indexed",
        "docs/README.md",
        "0749_ag_escalation_dispatch_daemon_privacy_regression.md",
    ),
)


def run_s75_operator_review_escalation_dispatch_daemon_closure(
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
        "failure_code": None if passed else "s75_closure_failed",
        "slice_range": "0741-0750",
        "boundary": "ag_owned_operator_review_escalation_dispatch_execution_daemon",
        "source_table": "ag_op_esc_dispatches",
        "new_tables": [],
        "daemon_runtime": "bounded_confirmed_tick_once_no_background_loop",
        "protected_control": "control_request_and_admission_foundation",
        "live_network_delivery": "local_loopback_protected_smoke_only",
        "real_external_endpoint_delivery": "deferred_until_full_system",
        "runtime_surfaces": [
            "daemon_boundary_audit",
            "daemon_policy",
            "tick_planner",
            "tick_execution",
            "tick_event_log_projection",
            "operations_runtime_projection",
            "protected_control_admission",
            "postgres_loopback_smoke",
            "privacy_regression",
        ],
        "postgres_smoke": "test_db_protected_daemon_tick_loopback",
        "privacy_regression": "no_raw_payload_token_database_url_or_storage_path",
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
            "s75_operator_review_escalation_dispatch_daemon_closure=pass "
            f"slice_range={evidence['slice_range']} "
            f"required_files={evidence['summary']['required_file_count']} "
            f"boundary={evidence['boundary']} "
            f"table={evidence['source_table']} "
            f"runtime={evidence['daemon_runtime']} "
            f"smoke={evidence['postgres_smoke']}"
        )
    return (
        "s75_operator_review_escalation_dispatch_daemon_closure=fail "
        f"reason={evidence.get('failure_code')} "
        f"missing_files={evidence['summary']['missing_file_count']} "
        f"missing_tokens={evidence['summary']['missing_token_count']}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the S75 operator review escalation dispatch daemon closure."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_s75_operator_review_escalation_dispatch_daemon_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
