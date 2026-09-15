#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = (
    "s77_operator_review_escalation_dispatch_daemon_operations_closure.v1"
)

REQUIRED_FILES = (
    "services/nex-ag/nex_ag/operations.py",
    "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
    "services/_shared/nex_runtime/operational_events.py",
    "contracts/openapi/nex-ag.openapi.yaml",
    "contracts/examples/operations/ag_operations_dashboard_snapshot.mock_success.json",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_operations_boundary_audit.py",
    "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_operations_postgres_smoke.py",
    "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_operations_privacy_runbook_evidence.py",
    "scripts/smoke/run_s77_operator_review_escalation_dispatch_daemon_operations_closure.py",
    "tests/test_ag_operator_review_escalation_dispatch_daemon_operations_boundary_audit.py",
    "tests/test_ag_operator_review_escalation_dispatch_daemon_operations_postgres_smoke.py",
    "tests/test_ag_operator_review_escalation_dispatch_daemon_operations_privacy_runbook_evidence.py",
    "tests/test_s77_operator_review_escalation_dispatch_daemon_operations_closure.py",
    "tests/test_nex_ag_operations.py",
    "tests/test_contract_validation.py",
    "docs/README.md",
    "docs/slices/0761_ag_escalation_dispatch_daemon_operations_boundary_audit.md",
    "docs/slices/0762_ag_escalation_dispatch_daemon_control_audit_events.md",
    "docs/slices/0763_ag_escalation_dispatch_daemon_control_history_read_model.md",
    "docs/slices/0764_ag_escalation_dispatch_daemon_control_history_route.md",
    "docs/slices/0765_ag_escalation_dispatch_daemon_dashboard_integration.md",
    "docs/slices/0766_ag_escalation_dispatch_daemon_issue_candidate_integration.md",
    "docs/slices/0767_ag_escalation_dispatch_daemon_contract_openapi_hardening.md",
    "docs/slices/0768_ag_escalation_dispatch_daemon_operations_postgres_smoke.md",
    "docs/slices/0769_ag_escalation_dispatch_daemon_operations_privacy_runbook_evidence.md",
    "docs/slices/0770_s77_operator_review_escalation_dispatch_daemon_operations_closure.md",
)

TOKEN_CHECKS = (
    (
        "quality_gate_operations_boundary",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_escalation_dispatch_daemon_operations_boundary_audit.py",
    ),
    (
        "quality_gate_operations_privacy_runbook",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_escalation_dispatch_daemon_operations_privacy_runbook_evidence.py",
    ),
    (
        "quality_gate_s77_closure",
        "scripts/quality/run_quality_gate.sh",
        "run_s77_operator_review_escalation_dispatch_daemon_operations_closure.py",
    ),
    (
        "control_audit_event_builder",
        "services/nex-ag/nex_ag/operations.py",
        "def build_operator_review_escalation_dispatch_daemon_control_audit_event_details",
    ),
    (
        "control_audit_event_emitter",
        "services/nex-ag/nex_ag/operations.py",
        "def emit_operator_review_escalation_dispatch_daemon_control_audit_event",
    ),
    (
        "control_history_projection",
        "services/nex-ag/nex_ag/operations.py",
        "def build_operator_review_escalation_dispatch_daemon_control_history_projection",
    ),
    (
        "control_history_route_operation_id",
        "services/nex-ag/nex_ag/operations.py",
        "listAgOperatorReviewDispatchDaemonControls",
    ),
    (
        "dashboard_daemon_controls",
        "services/nex-ag/nex_ag/operations.py",
        "daemon_controls",
    ),
    (
        "issue_candidate_rule",
        "services/nex-ag/nex_ag/operations.py",
        "operator_review_dispatch_daemon_control_attention_required.v1",
    ),
    (
        "operational_event_store_reused",
        "services/_shared/nex_runtime/operational_events.py",
        "class SqlAlchemyOperationalEventStore",
    ),
    (
        "openapi_controls_route",
        "contracts/openapi/nex-ag.openapi.yaml",
        "/admin/v1/operator-review/dispatch-daemon/controls",
    ),
    (
        "openapi_control_history_schema",
        "contracts/openapi/nex-ag.openapi.yaml",
        "AgOperatorReviewDispatchDaemonControlHistoryProjection",
    ),
    (
        "dashboard_example_daemon_controls",
        "contracts/examples/operations/ag_operations_dashboard_snapshot.mock_success.json",
        "daemon_controls",
    ),
    (
        "postgres_smoke_opt_in",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_operations_postgres_smoke.py",
        "NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_DAEMON_OPERATIONS_POSTGRES_SMOKE",
    ),
    (
        "postgres_smoke_real_test_db_doc",
        "docs/slices/0768_ag_escalation_dispatch_daemon_operations_postgres_smoke.md",
        "nex_ag_test",
    ),
    (
        "privacy_runbook_forbidden_absent",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_operations_privacy_runbook_evidence.py",
        "forbidden_values_absent",
    ),
    (
        "privacy_runbook_paths_ready",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_operations_privacy_runbook_evidence.py",
        "runbook_paths_ready",
    ),
    (
        "s77_docs_indexed",
        "docs/README.md",
        "0769_ag_escalation_dispatch_daemon_operations_privacy_runbook_evidence.md",
    ),
)


def run_s77_operator_review_escalation_dispatch_daemon_operations_closure(
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
        "failure_code": None if passed else "s77_closure_failed",
        "slice_range": "0761-0770",
        "boundary": "ag_owned_operator_review_escalation_dispatch_daemon_operations",
        "source_tables": ["ag_op_esc_dispatches", "service_operational_events"],
        "new_tables": [],
        "operations_surfaces": [
            "control_audit_event",
            "control_history_read_model",
            "protected_control_history_route",
            "dashboard_daemon_controls",
            "issue_candidate_attention_signal",
            "static_openapi_contract",
            "test_db_postgres_operations_smoke",
            "privacy_runbook_evidence",
        ],
        "control_history_route": (
            "GET /admin/v1/operator-review/dispatch-daemon/controls"
        ),
        "postgres_smoke": "test_db_control_events_history_dashboard_issue_candidate",
        "privacy_regression": "no_raw_control_payload_token_database_url_or_storage_path",
        "runbook_evidence": "dashboard_paths_and_issue_candidate_runbook_ids",
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
            "s77_operator_review_escalation_dispatch_daemon_operations_closure=pass "
            f"slice_range={evidence['slice_range']} "
            f"required_files={evidence['summary']['required_file_count']} "
            f"boundary={evidence['boundary']} "
            f"route={evidence['control_history_route']} "
            f"smoke={evidence['postgres_smoke']}"
        )
    return (
        "s77_operator_review_escalation_dispatch_daemon_operations_closure=fail "
        f"reason={evidence.get('failure_code')} "
        f"missing_files={evidence['summary']['missing_file_count']} "
        f"missing_tokens={evidence['summary']['missing_token_count']}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the S77 operator review escalation dispatch daemon operations closure."
        )
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_s77_operator_review_escalation_dispatch_daemon_operations_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
