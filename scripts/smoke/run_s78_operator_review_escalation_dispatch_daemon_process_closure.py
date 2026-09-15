#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = (
    "s78_operator_review_escalation_dispatch_daemon_process_closure.v1"
)

REQUIRED_FILES = (
    "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
    "services/nex-ag/nex_ag/operator_review_dispatch_daemon.py",
    "services/nex-ag/nex_ag/operations.py",
    "services/_shared/nex_runtime/operational_events.py",
    "services/_shared/nex_runtime/worker_heartbeats.py",
    "contracts/openapi/nex-ag.openapi.yaml",
    "contracts/schemas/service/nex_ag/operations_projection.v1.schema.json",
    "contracts/examples/operations/ag_operations_dashboard_snapshot.mock_success.json",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_process_boundary_audit.py",
    "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_process_postgres_smoke.py",
    "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_process_privacy_runbook_evidence.py",
    "scripts/smoke/run_s78_operator_review_escalation_dispatch_daemon_process_closure.py",
    "tests/test_ag_operator_review_escalation_dispatch_daemon_process_boundary_audit.py",
    "tests/test_ag_operator_review_escalation_dispatch_daemon_process_postgres_smoke.py",
    "tests/test_ag_operator_review_escalation_dispatch_daemon_process_privacy_runbook_evidence.py",
    "tests/test_s78_operator_review_escalation_dispatch_daemon_process_closure.py",
    "tests/test_nex_ag_operator_review_dispatch_execution.py",
    "tests/test_nex_ag_operator_review_dispatch_daemon_cli.py",
    "tests/test_nex_ag_operations.py",
    "tests/test_contract_validation.py",
    "docs/README.md",
    "docs/slices/0771_ag_escalation_dispatch_daemon_process_boundary_audit.md",
    "docs/slices/0772_ag_escalation_dispatch_daemon_runtime_loop_policy.md",
    "docs/slices/0773_ag_escalation_dispatch_daemon_process_metadata_contract.md",
    "docs/slices/0774_ag_escalation_dispatch_daemon_executable_cli.md",
    "docs/slices/0775_ag_escalation_dispatch_daemon_lifecycle_event_persistence.md",
    "docs/slices/0776_ag_escalation_dispatch_daemon_process_control_api.md",
    "docs/slices/0777_ag_escalation_dispatch_daemon_process_dashboard.md",
    "docs/slices/0778_ag_escalation_dispatch_daemon_process_postgres_smoke.md",
    "docs/slices/0779_ag_escalation_dispatch_daemon_process_privacy_runbook_evidence.md",
    "docs/slices/0780_s78_operator_review_escalation_dispatch_daemon_process_closure.md",
)

TOKEN_CHECKS = (
    (
        "quality_gate_process_boundary",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_escalation_dispatch_daemon_process_boundary_audit.py",
    ),
    (
        "quality_gate_process_postgres_smoke",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_escalation_dispatch_daemon_process_postgres_smoke.py",
    ),
    (
        "quality_gate_process_privacy_runbook",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_escalation_dispatch_daemon_process_privacy_runbook_evidence.py",
    ),
    (
        "quality_gate_s78_closure",
        "scripts/quality/run_quality_gate.sh",
        "run_s78_operator_review_escalation_dispatch_daemon_process_closure.py",
    ),
    (
        "runtime_loop_policy_builder",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "def build_dispatch_execution_daemon_loop_policy",
    ),
    (
        "runtime_bounded_loop_runner",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "def run_dispatch_execution_daemon_bounded_loop",
    ),
    (
        "process_metadata_contract",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "def build_dispatch_execution_daemon_process_metadata",
    ),
    (
        "process_runtime_state_contract",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "def build_dispatch_execution_daemon_process_runtime_state",
    ),
    (
        "lifecycle_event_emitter",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "def emit_dispatch_execution_daemon_lifecycle_event",
    ),
    (
        "process_control_request_contract",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "def build_dispatch_execution_daemon_process_control_request",
    ),
    (
        "process_control_projection_contract",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "def build_dispatch_execution_daemon_process_control_projection",
    ),
    (
        "executable_cli_entrypoint",
        "services/nex-ag/nex_ag/operator_review_dispatch_daemon.py",
        "def execute_dispatch_execution_daemon_cli",
    ),
    (
        "cli_lifecycle_emitter",
        "services/nex-ag/nex_ag/operator_review_dispatch_daemon.py",
        "lifecycle_emitter",
    ),
    (
        "operations_process_control_api",
        "services/nex-ag/nex_ag/operations.py",
        "def build_operator_review_escalation_dispatch_daemon_process_control_api_projection",
    ),
    (
        "operations_dashboard_daemon_process",
        "services/nex-ag/nex_ag/operations.py",
        "daemon_process",
    ),
    (
        "process_control_route_path",
        "services/nex-ag/nex_ag/operations.py",
        "/admin/v1/operator-review/dispatch-daemon/process-controls",
    ),
    (
        "openapi_process_control_route",
        "contracts/openapi/nex-ag.openapi.yaml",
        "postAgOperatorReviewDispatchDaemonProcessControl",
    ),
    (
        "schema_dashboard_daemon_process",
        "contracts/schemas/service/nex_ag/operations_projection.v1.schema.json",
        "dashboard_operator_review_dispatch_daemon_process",
    ),
    (
        "dashboard_example_daemon_process",
        "contracts/examples/operations/ag_operations_dashboard_snapshot.mock_success.json",
        "daemon_process",
    ),
    (
        "postgres_smoke_opt_in",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_process_postgres_smoke.py",
        "NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_DAEMON_PROCESS_POSTGRES_SMOKE",
    ),
    (
        "postgres_smoke_real_test_db_doc",
        "docs/slices/0778_ag_escalation_dispatch_daemon_process_postgres_smoke.md",
        "nex_ag_test",
    ),
    (
        "privacy_runbook_forbidden_absent",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_process_privacy_runbook_evidence.py",
        "forbidden_values_absent",
    ),
    (
        "privacy_runbook_ids_ready",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_process_privacy_runbook_evidence.py",
        "runbook_ids_ready",
    ),
    (
        "s78_docs_indexed",
        "docs/README.md",
        "0779_ag_escalation_dispatch_daemon_process_privacy_runbook_evidence.md",
    ),
)


def run_s78_operator_review_escalation_dispatch_daemon_process_closure(
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
        "failure_code": None if passed else "s78_closure_failed",
        "slice_range": "0771-0780",
        "boundary": "ag_owned_operator_review_escalation_dispatch_daemon_process",
        "source_tables": ["ag_op_esc_dispatches", "service_operational_events"],
        "liveness_sources": ["service_worker_heartbeats"],
        "new_tables": [],
        "process_surfaces": [
            "runtime_loop_policy",
            "process_metadata_contract",
            "executable_cli",
            "lifecycle_event_persistence",
            "protected_process_control_api",
            "dashboard_daemon_process",
            "test_db_postgres_process_smoke",
            "privacy_runbook_evidence",
        ],
        "process_control_route": (
            "POST /admin/v1/operator-review/dispatch-daemon/process-controls"
        ),
        "postgres_smoke": "test_db_lifecycle_events_dashboard_process_control",
        "privacy_regression": "no_raw_process_secret_token_database_url_or_storage_path",
        "runbook_evidence": "process_control_path_lifecycle_runbook_ids",
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
            "s78_operator_review_escalation_dispatch_daemon_process_closure=pass "
            f"slice_range={evidence['slice_range']} "
            f"required_files={evidence['summary']['required_file_count']} "
            f"boundary={evidence['boundary']} "
            f"route={evidence['process_control_route']} "
            f"smoke={evidence['postgres_smoke']}"
        )
    return (
        "s78_operator_review_escalation_dispatch_daemon_process_closure=fail "
        f"reason={evidence.get('failure_code')} "
        f"missing_files={evidence['summary']['missing_file_count']} "
        f"missing_tokens={evidence['summary']['missing_token_count']}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the S78 operator review escalation dispatch daemon process closure."
        )
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_s78_operator_review_escalation_dispatch_daemon_process_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
