#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s74_operator_review_escalation_dispatch_live_http_closure.v1"

REQUIRED_FILES = (
    "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
    "services/nex-ag/nex_ag/operations.py",
    "services/nex-ag/README.md",
    "contracts/schemas/service/nex_ag/operations_projection.v1.schema.json",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ag_operator_review_escalation_dispatch_live_http_transport_boundary_audit.py",
    "scripts/smoke/run_ag_operator_review_escalation_dispatch_notification_loopback_smoke.py",
    "scripts/smoke/run_ag_operator_review_escalation_dispatch_incident_loopback_smoke.py",
    "scripts/smoke/run_ag_operator_review_escalation_dispatch_live_http_postgres_smoke.py",
    "scripts/smoke/run_s74_operator_review_escalation_dispatch_live_http_closure.py",
    "tests/test_ag_operator_review_escalation_dispatch_live_http_transport_boundary_audit.py",
    "tests/test_ag_operator_review_escalation_dispatch_notification_loopback_smoke.py",
    "tests/test_ag_operator_review_escalation_dispatch_incident_loopback_smoke.py",
    "tests/test_ag_operator_review_escalation_dispatch_live_http_postgres_smoke.py",
    "tests/test_s74_operator_review_escalation_dispatch_live_http_closure.py",
    "tests/test_nex_ag_operator_review_dispatch_execution.py",
    "tests/test_nex_ag_operations.py",
    "docs/README.md",
    "docs/slices/0731_ag_escalation_dispatch_live_http_transport_boundary_audit.md",
    "docs/slices/0732_ag_escalation_dispatch_live_http_transport_foundation.md",
    "docs/slices/0733_ag_escalation_dispatch_live_http_transport_request_guardrails.md",
    "docs/slices/0734_ag_escalation_dispatch_live_http_adapter.md",
    "docs/slices/0735_ag_escalation_dispatch_notification_loopback_smoke.md",
    "docs/slices/0736_ag_escalation_dispatch_incident_loopback_smoke.md",
    "docs/slices/0737_ag_escalation_dispatch_worker_live_http_opt_in.md",
    "docs/slices/0738_ag_escalation_dispatch_live_http_postgresql_smoke.md",
    "docs/slices/0739_ag_escalation_dispatch_live_http_operations_diagnostics.md",
    "docs/slices/0740_s74_operator_review_escalation_dispatch_live_http_closure.md",
)

TOKEN_CHECKS = (
    (
        "quality_gate_boundary",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_escalation_dispatch_live_http_transport_boundary_audit.py",
    ),
    (
        "quality_gate_notification_loopback",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_escalation_dispatch_notification_loopback_smoke.py",
    ),
    (
        "quality_gate_incident_loopback",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_escalation_dispatch_incident_loopback_smoke.py",
    ),
    (
        "quality_gate_live_http_postgres",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_escalation_dispatch_live_http_postgres_smoke.py",
    ),
    (
        "quality_gate_s74_closure",
        "scripts/quality/run_quality_gate.sh",
        "run_s74_operator_review_escalation_dispatch_live_http_closure.py",
    ),
    (
        "transport_envelope_schema",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "ag_operator_review_escalation_dispatch_live_http_transport_envelope.v1",
    ),
    (
        "transport_request_plan_schema",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "ag_operator_review_escalation_dispatch_live_http_transport_request_plan.v1",
    ),
    (
        "urllib_transport",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "class UrllibDispatchProviderHttpTransport",
    ),
    (
        "live_http_adapter",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "def execute_dispatch_with_live_http_transport",
    ),
    (
        "worker_live_http_transport_opt_in",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "live_http_transport",
    ),
    (
        "attempt_metadata",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        '"attempt_count": execution_result.get("attempt_count")',
    ),
    (
        "operations_provider_mode_summary",
        "services/nex-ag/nex_ag/operations.py",
        "by_provider_mode",
    ),
    (
        "operations_attempt_summary",
        "services/nex-ag/nex_ag/operations.py",
        "attempt_count_total",
    ),
    (
        "operations_schema_provider_mode",
        "contracts/schemas/service/nex_ag/operations_projection.v1.schema.json",
        "by_provider_mode",
    ),
    (
        "operations_schema_attempts",
        "contracts/schemas/service/nex_ag/operations_projection.v1.schema.json",
        "max_attempt_count",
    ),
    (
        "notification_loopback_opt_in",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_notification_loopback_smoke.py",
        "NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_NOTIFICATION_LOOPBACK_SMOKE",
    ),
    (
        "incident_loopback_opt_in",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_incident_loopback_smoke.py",
        "NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_INCIDENT_LOOPBACK_SMOKE",
    ),
    (
        "postgres_loopback_opt_in",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_live_http_postgres_smoke.py",
        "NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_LIVE_HTTP_POSTGRES_SMOKE",
    ),
    (
        "postgres_real_test_db_doc",
        "docs/slices/0738_ag_escalation_dispatch_live_http_postgresql_smoke.md",
        "nex_ag_test",
    ),
    (
        "s74_docs_indexed",
        "docs/README.md",
        "0739_ag_escalation_dispatch_live_http_operations_diagnostics.md",
    ),
)


def run_s74_operator_review_escalation_dispatch_live_http_closure(
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
        "failure_code": None if passed else "s74_closure_failed",
        "slice_range": "0731-0740",
        "boundary": "ag_owned_operator_review_escalation_dispatch_live_http_transport",
        "source_table": "ag_op_esc_dispatches",
        "new_tables": [],
        "provider_modes": ["mock_first_only", "mock_http", "guarded_live_http"],
        "live_network_delivery": "local_loopback_protected_smoke_only",
        "real_external_endpoint_delivery": "deferred_until_full_system",
        "transport_surfaces": [
            "live_http_boundary_audit",
            "urllib_transport",
            "request_plan_guardrails",
            "live_http_adapter",
            "worker_live_http_opt_in",
            "notification_loopback_smoke",
            "incident_loopback_smoke",
            "postgres_loopback_smoke",
            "operations_live_http_diagnostics",
        ],
        "privacy_regression": "no_raw_endpoint_headers_tokens_or_payloads",
        "postgres_smoke": "test_db_protected_live_http_loopback_worker",
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
            "s74_operator_review_escalation_dispatch_live_http_closure=pass "
            f"slice_range={evidence['slice_range']} "
            f"required_files={evidence['summary']['required_file_count']} "
            f"boundary={evidence['boundary']} "
            f"table={evidence['source_table']} "
            f"delivery={evidence['live_network_delivery']} "
            f"smoke={evidence['postgres_smoke']}"
        )
    return (
        "s74_operator_review_escalation_dispatch_live_http_closure=fail "
        f"reason={evidence.get('failure_code')} "
        f"missing_files={evidence['summary']['missing_file_count']} "
        f"missing_tokens={evidence['summary']['missing_token_count']}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the S74 operator review escalation dispatch live HTTP closure."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_s74_operator_review_escalation_dispatch_live_http_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
