#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = (
    "s79_operator_review_escalation_dispatch_daemon_liveness_closure.v1"
)

REQUIRED_FILES = (
    "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
    "services/nex-ag/nex_ag/operator_review_dispatch_daemon.py",
    "services/nex-ag/nex_ag/operations.py",
    "services/_shared/nex_runtime/worker_heartbeats.py",
    "contracts/openapi/nex-ag.openapi.yaml",
    "contracts/schemas/service/nex_ag/operations_projection.v1.schema.json",
    "contracts/examples/operations/ag_operations_dashboard_snapshot.mock_success.json",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_liveness_boundary_audit.py",
    "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_liveness_postgres_smoke.py",
    "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_liveness_privacy_runbook_evidence.py",
    "scripts/smoke/run_s79_operator_review_escalation_dispatch_daemon_liveness_closure.py",
    "tests/test_ag_operator_review_escalation_dispatch_daemon_liveness_boundary_audit.py",
    "tests/test_ag_operator_review_escalation_dispatch_daemon_liveness_postgres_smoke.py",
    "tests/test_ag_operator_review_escalation_dispatch_daemon_liveness_privacy_runbook_evidence.py",
    "tests/test_s79_operator_review_escalation_dispatch_daemon_liveness_closure.py",
    "tests/test_nex_ag_operator_review_dispatch_execution.py",
    "tests/test_nex_ag_operator_review_dispatch_daemon_cli.py",
    "tests/test_nex_ag_operations.py",
    "tests/test_contract_validation.py",
    "docs/README.md",
    "docs/slices/0781_ag_escalation_dispatch_daemon_liveness_boundary_audit.md",
    "docs/slices/0782_ag_escalation_dispatch_daemon_heartbeat_contract.md",
    "docs/slices/0783_ag_escalation_dispatch_daemon_heartbeat_emission.md",
    "docs/slices/0784_ag_escalation_dispatch_daemon_liveness_read_model.md",
    "docs/slices/0785_ag_escalation_dispatch_daemon_liveness_route.md",
    "docs/slices/0786_ag_escalation_dispatch_daemon_liveness_dashboard.md",
    "docs/slices/0787_ag_escalation_dispatch_daemon_liveness_issue_candidate.md",
    "docs/slices/0788_ag_escalation_dispatch_daemon_liveness_postgres_smoke.md",
    "docs/slices/0789_ag_escalation_dispatch_daemon_liveness_privacy_runbook_evidence.md",
    "docs/slices/0790_s79_operator_review_escalation_dispatch_daemon_liveness_closure.md",
)

TOKEN_CHECKS = (
    (
        "quality_gate_liveness_boundary",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_escalation_dispatch_daemon_liveness_boundary_audit.py",
    ),
    (
        "quality_gate_liveness_postgres_smoke",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_escalation_dispatch_daemon_liveness_postgres_smoke.py",
    ),
    (
        "quality_gate_liveness_privacy_runbook",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_escalation_dispatch_daemon_liveness_privacy_runbook_evidence.py",
    ),
    (
        "quality_gate_s79_closure",
        "scripts/quality/run_quality_gate.sh",
        "run_s79_operator_review_escalation_dispatch_daemon_liveness_closure.py",
    ),
    (
        "heartbeat_contract_builder",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "def build_dispatch_execution_daemon_heartbeat_contract",
    ),
    (
        "heartbeat_wire_builder",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "def build_dispatch_execution_daemon_heartbeat",
    ),
    (
        "daemon_cli_heartbeat_emitter",
        "services/nex-ag/nex_ag/operator_review_dispatch_daemon.py",
        "heartbeat_emitter",
    ),
    (
        "liveness_projection_builder",
        "services/nex-ag/nex_ag/operations.py",
        "def build_operator_review_escalation_dispatch_daemon_liveness_projection",
    ),
    (
        "liveness_route_path",
        "services/nex-ag/nex_ag/operations.py",
        "/admin/v1/operator-review/dispatch-daemon/liveness",
    ),
    (
        "liveness_issue_candidate_rule",
        "services/nex-ag/nex_ag/operations.py",
        "operator_review_dispatch_daemon_liveness_attention_required.v1",
    ),
    (
        "openapi_liveness_route",
        "contracts/openapi/nex-ag.openapi.yaml",
        "getAgOperatorReviewDispatchDaemonLiveness",
    ),
    (
        "schema_dashboard_daemon_liveness",
        "contracts/schemas/service/nex_ag/operations_projection.v1.schema.json",
        "dashboard_operator_review_dispatch_daemon_liveness",
    ),
    (
        "dashboard_example_daemon_liveness",
        "contracts/examples/operations/ag_operations_dashboard_snapshot.mock_success.json",
        "daemon_liveness",
    ),
    (
        "postgres_smoke_opt_in",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_liveness_postgres_smoke.py",
        "NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_DAEMON_LIVENESS_POSTGRES_SMOKE",
    ),
    (
        "postgres_smoke_real_test_db_doc",
        "docs/slices/0788_ag_escalation_dispatch_daemon_liveness_postgres_smoke.md",
        "nex_ag_test",
    ),
    (
        "privacy_runbook_stale",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_liveness_privacy_runbook_evidence.py",
        "ag.operator_review_dispatch_daemon_liveness.stale_heartbeat.v1",
    ),
    (
        "privacy_runbook_missing",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_liveness_privacy_runbook_evidence.py",
        "ag.operator_review_dispatch_daemon_liveness.missing_heartbeat.v1",
    ),
    (
        "s79_docs_indexed",
        "docs/README.md",
        "0789_ag_escalation_dispatch_daemon_liveness_privacy_runbook_evidence.md",
    ),
)


def run_s79_operator_review_escalation_dispatch_daemon_liveness_closure(
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
        "failure_code": None if passed else "s79_closure_failed",
        "slice_range": "0781-0790",
        "boundary": "ag_owned_operator_review_escalation_dispatch_daemon_liveness",
        "source_tables": ["service_worker_heartbeats"],
        "new_tables": [],
        "liveness_route": "GET /admin/v1/operator-review/dispatch-daemon/liveness",
        "liveness_surfaces": [
            "heartbeat_contract",
            "daemon_heartbeat_emission",
            "liveness_read_model",
            "protected_liveness_route",
            "operations_dashboard_daemon_liveness",
            "liveness_issue_candidate",
            "test_db_postgres_liveness_smoke",
            "privacy_runbook_evidence",
        ],
        "postgres_smoke": "test_db_service_worker_heartbeats_liveness_dashboard_issue",
        "privacy_regression": "no_raw_liveness_secret_token_database_url_or_storage_path",
        "runbook_evidence": "stale_and_missing_heartbeat_runbook_ids",
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
            "s79_operator_review_escalation_dispatch_daemon_liveness_closure=pass "
            f"slice_range={evidence['slice_range']} "
            f"required_files={evidence['summary']['required_file_count']} "
            f"boundary={evidence['boundary']} "
            f"route={evidence['liveness_route']} "
            f"smoke={evidence['postgres_smoke']}"
        )
    return (
        "s79_operator_review_escalation_dispatch_daemon_liveness_closure=fail "
        f"reason={evidence.get('failure_code')} "
        f"missing_files={evidence['summary']['missing_file_count']} "
        f"missing_tokens={evidence['summary']['missing_token_count']}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s79_operator_review_escalation_dispatch_daemon_liveness_closure()
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
