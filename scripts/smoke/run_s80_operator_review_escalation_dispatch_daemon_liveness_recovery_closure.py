#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = (
    "s80_operator_review_escalation_dispatch_daemon_liveness_recovery_closure.v1"
)

REQUIRED_FILES = (
    "services/nex-ag/nex_ag/operations.py",
    "services/_shared/nex_runtime/worker_heartbeats.py",
    "contracts/openapi/nex-ag.openapi.yaml",
    "contracts/examples/operations/ag_operations_dashboard_snapshot.mock_success.json",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_boundary_audit.py",
    "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_postgres_smoke.py",
    "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_privacy_runbook_evidence.py",
    "scripts/smoke/run_s80_operator_review_escalation_dispatch_daemon_liveness_recovery_closure.py",
    "tests/test_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_boundary_audit.py",
    "tests/test_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_postgres_smoke.py",
    "tests/test_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_privacy_runbook_evidence.py",
    "tests/test_s80_operator_review_escalation_dispatch_daemon_liveness_recovery_closure.py",
    "tests/test_nex_ag_operations.py",
    "tests/test_contract_validation.py",
    "docs/README.md",
    "docs/slices/0791_ag_escalation_dispatch_daemon_liveness_recovery_boundary_audit.md",
    "docs/slices/0792_ag_escalation_dispatch_daemon_liveness_recovery_plan_contract.md",
    "docs/slices/0793_ag_escalation_dispatch_daemon_liveness_recovery_plan_route.md",
    "docs/slices/0794_ag_escalation_dispatch_daemon_liveness_recovery_audit_event.md",
    "docs/slices/0795_ag_escalation_dispatch_daemon_liveness_recovery_dashboard.md",
    "docs/slices/0796_ag_escalation_dispatch_daemon_liveness_ack_suppression_policy.md",
    "docs/slices/0797_ag_escalation_dispatch_daemon_liveness_recovery_postgres_smoke.md",
    "docs/slices/0798_ag_escalation_dispatch_daemon_liveness_recovery_privacy_runbook.md",
    "docs/slices/0799_ag_escalation_dispatch_daemon_liveness_recovery_openapi_hardening.md",
    "docs/slices/0800_s80_operator_review_escalation_dispatch_daemon_liveness_recovery_closure.md",
)

TOKEN_CHECKS = (
    (
        "quality_gate_recovery_boundary",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_boundary_audit.py",
    ),
    (
        "quality_gate_recovery_postgres_smoke",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_postgres_smoke.py",
    ),
    (
        "quality_gate_recovery_privacy_runbook",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_privacy_runbook_evidence.py",
    ),
    (
        "quality_gate_s80_closure",
        "scripts/quality/run_quality_gate.sh",
        "run_s80_operator_review_escalation_dispatch_daemon_liveness_recovery_closure.py",
    ),
    (
        "recovery_plan_builder",
        "services/nex-ag/nex_ag/operations.py",
        "def build_operator_review_escalation_dispatch_daemon_liveness_recovery_plan",
    ),
    (
        "ack_suppression_policy_builder",
        "services/nex-ag/nex_ag/operations.py",
        "def build_operator_review_escalation_dispatch_daemon_liveness_ack_suppression_policy",
    ),
    (
        "recovery_audit_event_builder",
        "services/nex-ag/nex_ag/operations.py",
        "def build_operator_review_escalation_dispatch_daemon_liveness_recovery_audit_event_details",
    ),
    (
        "recovery_audit_event_emitter",
        "services/nex-ag/nex_ag/operations.py",
        "def emit_operator_review_escalation_dispatch_daemon_liveness_recovery_audit_event",
    ),
    (
        "recovery_route_response",
        "services/nex-ag/nex_ag/operations.py",
        "def _dispatch_daemon_liveness_recovery_plan_route_response",
    ),
    (
        "recovery_dashboard_section",
        "services/nex-ag/nex_ag/operations.py",
        "def _dashboard_operator_review_dispatch_daemon_liveness_recovery_section",
    ),
    (
        "recovery_route_path",
        "services/nex-ag/nex_ag/operations.py",
        "/admin/v1/operator-review/dispatch-daemon/liveness/recovery-plan",
    ),
    (
        "process_control_guard_route",
        "services/nex-ag/nex_ag/operations.py",
        "/admin/v1/operator-review/dispatch-daemon/process-controls",
    ),
    (
        "openapi_recovery_operation",
        "contracts/openapi/nex-ag.openapi.yaml",
        "getAgOperatorReviewDispatchDaemonLivenessRecoveryPlan",
    ),
    (
        "openapi_recovery_projection_schema",
        "contracts/openapi/nex-ag.openapi.yaml",
        "AgOperatorReviewDispatchDaemonLivenessRecoveryPlanProjection",
    ),
    (
        "contract_validation_recovery_route",
        "tests/test_contract_validation.py",
        "getAgOperatorReviewDispatchDaemonLivenessRecoveryPlan",
    ),
    (
        "runtime_static_openapi_recovery_route",
        "tests/test_nex_ag_operations.py",
        "getAgOperatorReviewDispatchDaemonLivenessRecoveryPlan",
    ),
    (
        "dashboard_example_daemon_recovery",
        "contracts/examples/operations/ag_operations_dashboard_snapshot.mock_success.json",
        "daemon_recovery",
    ),
    (
        "postgres_smoke_opt_in",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_postgres_smoke.py",
        "NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_DAEMON_LIVENESS_RECOVERY_POSTGRES_SMOKE",
    ),
    (
        "postgres_smoke_real_test_db_doc",
        "docs/slices/0797_ag_escalation_dispatch_daemon_liveness_recovery_postgres_smoke.md",
        "nex_ag_test",
    ),
    (
        "privacy_runbook_ack_state_decision",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_privacy_runbook_evidence.py",
        "ag_op_review_ack_state",
    ),
    (
        "privacy_runbook_stale",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_privacy_runbook_evidence.py",
        "ag.operator_review_dispatch_daemon_liveness.stale_heartbeat.v1",
    ),
    (
        "privacy_runbook_missing",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_privacy_runbook_evidence.py",
        "ag.operator_review_dispatch_daemon_liveness.missing_heartbeat.v1",
    ),
    (
        "s80_docs_indexed",
        "docs/README.md",
        "0799_ag_escalation_dispatch_daemon_liveness_recovery_openapi_hardening.md",
    ),
)


def run_s80_operator_review_escalation_dispatch_daemon_liveness_recovery_closure(
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
        "failure_code": None if passed else "s80_closure_failed",
        "slice_range": "0791-0800",
        "boundary": (
            "ag_owned_operator_review_escalation_dispatch_daemon_liveness_recovery"
        ),
        "source_tables": ["service_worker_heartbeats", "service_operational_events"],
        "new_tables": [],
        "protected_routes": [
            "GET /admin/v1/operator-review/dispatch-daemon/liveness/recovery-plan",
            "POST /admin/v1/operator-review/dispatch-daemon/process-controls",
        ],
        "recovery_surfaces": [
            "boundary_audit",
            "recovery_action_plan_contract",
            "protected_recovery_plan_route",
            "safe_recovery_audit_event",
            "operations_dashboard_daemon_recovery",
            "liveness_issue_acknowledgement_suppression_policy",
            "test_db_postgres_recovery_smoke",
            "privacy_runbook_and_ack_state_decision_evidence",
            "static_openapi_schema_hardening",
        ],
        "postgres_smoke": (
            "test_db_service_worker_heartbeats_liveness_recovery_audit_dashboard_issue"
        ),
        "privacy_regression": (
            "no_raw_liveness_secret_token_database_url_storage_path_or_operator_comment"
        ),
        "runbook_evidence": "stale_and_missing_heartbeat_recovery_runbook_ids",
        "acknowledgement_suppression_state": {
            "current_state_persisted": False,
            "future_table_candidate": "ag_op_review_ack_state",
            "new_tables_in_s80": [],
        },
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
            "s80_operator_review_escalation_dispatch_daemon_liveness_recovery_closure=pass "
            f"slice_range={evidence['slice_range']} "
            f"required_files={evidence['summary']['required_file_count']} "
            f"boundary={evidence['boundary']} "
            f"route={evidence['protected_routes'][0]} "
            f"smoke={evidence['postgres_smoke']} "
            f"ack_state={evidence['acknowledgement_suppression_state']['future_table_candidate']}"
        )
    return (
        "s80_operator_review_escalation_dispatch_daemon_liveness_recovery_closure=fail "
        f"reason={evidence.get('failure_code')} "
        f"missing_files={evidence['summary']['missing_file_count']} "
        f"missing_tokens={evidence['summary']['missing_token_count']}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = (
        run_s80_operator_review_escalation_dispatch_daemon_liveness_recovery_closure()
    )
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
