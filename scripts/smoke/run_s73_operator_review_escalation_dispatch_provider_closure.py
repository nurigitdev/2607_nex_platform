#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s73_operator_review_escalation_dispatch_provider_closure.v1"

REQUIRED_FILES = (
    "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
    "services/nex-ag/nex_ag/operations.py",
    "services/nex-ag/README.md",
    "contracts/schemas/service/nex_ag/operations_projection.v1.schema.json",
    "contracts/examples/operations/ag_operations_dashboard_snapshot.mock_success.json",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ag_operator_review_escalation_dispatch_live_provider_boundary_audit.py",
    "scripts/smoke/run_ag_operator_review_escalation_dispatch_live_provider_privacy_regression.py",
    "scripts/smoke/run_ag_operator_review_escalation_dispatch_provider_postgres_smoke.py",
    "scripts/smoke/run_s73_operator_review_escalation_dispatch_provider_closure.py",
    "tests/test_ag_operator_review_escalation_dispatch_live_provider_boundary_audit.py",
    "tests/test_ag_operator_review_escalation_dispatch_live_provider_privacy_regression.py",
    "tests/test_ag_operator_review_escalation_dispatch_provider_postgres_smoke.py",
    "tests/test_s73_operator_review_escalation_dispatch_provider_closure.py",
    "tests/test_nex_ag_operator_review_dispatch_execution.py",
    "tests/test_nex_ag_operations.py",
    "docs/README.md",
    "docs/slices/0721_ag_escalation_dispatch_live_provider_boundary_audit.md",
    "docs/slices/0722_ag_escalation_dispatch_provider_config_registry.md",
    "docs/slices/0723_ag_escalation_dispatch_notification_provider_adapter.md",
    "docs/slices/0724_ag_escalation_dispatch_external_incident_provider_adapter.md",
    "docs/slices/0725_ag_escalation_dispatch_provider_http_client_foundation.md",
    "docs/slices/0726_ag_escalation_dispatch_worker_provider_routing.md",
    "docs/slices/0727_ag_escalation_dispatch_provider_diagnostics_dashboard.md",
    "docs/slices/0728_ag_escalation_dispatch_live_provider_privacy_regression.md",
    "docs/slices/0729_ag_escalation_dispatch_provider_postgresql_smoke.md",
    "docs/slices/0730_s73_operator_review_escalation_dispatch_provider_closure.md",
)

TOKEN_CHECKS = (
    (
        "quality_gate_live_provider_boundary",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_escalation_dispatch_live_provider_boundary_audit.py",
    ),
    (
        "quality_gate_live_provider_privacy",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_escalation_dispatch_live_provider_privacy_regression.py",
    ),
    (
        "quality_gate_provider_postgres_smoke",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_escalation_dispatch_provider_postgres_smoke.py",
    ),
    (
        "quality_gate_s73_closure",
        "scripts/quality/run_quality_gate.sh",
        "run_s73_operator_review_escalation_dispatch_provider_closure.py",
    ),
    (
        "provider_config_schema",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "ag_operator_review_escalation_dispatch_provider_config.v1",
    ),
    (
        "notification_request_schema",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "ag_operator_review_escalation_dispatch_notification_request.v1",
    ),
    (
        "external_incident_request_schema",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "ag_operator_review_escalation_dispatch_external_incident_request.v1",
    ),
    (
        "http_client_result_schema",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "ag_operator_review_escalation_dispatch_provider_http_client_result.v1",
    ),
    (
        "notification_provider_adapter",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "MockNotificationDispatchProvider",
    ),
    (
        "external_incident_provider_adapter",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "MockExternalIncidentDispatchProvider",
    ),
    (
        "provider_http_transport",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "MockDispatchProviderHttpTransport",
    ),
    (
        "provider_router",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "def execute_dispatch_with_provider_router",
    ),
    (
        "provider_diagnostics_metadata",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "provider_request_hash",
    ),
    (
        "provider_diagnostics_dashboard",
        "services/nex-ag/nex_ag/operations.py",
        "by_provider_category",
    ),
    (
        "operations_contract_provider_diagnostics",
        "contracts/schemas/service/nex_ag/operations_projection.v1.schema.json",
        "by_http_status_code",
    ),
    (
        "privacy_regression_schema",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_live_provider_privacy_regression.py",
        "ag_operator_review_escalation_dispatch_live_provider_privacy_regression.v1",
    ),
    (
        "provider_postgres_smoke_opt_in",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_provider_postgres_smoke.py",
        "NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_PROVIDER_POSTGRES_SMOKE",
    ),
    (
        "provider_postgres_smoke_real_test_db",
        "docs/slices/0729_ag_escalation_dispatch_provider_postgresql_smoke.md",
        "nex_ag_test",
    ),
    (
        "s73_docs_indexed",
        "docs/README.md",
        "0729_ag_escalation_dispatch_provider_postgresql_smoke.md",
    ),
)


def run_s73_operator_review_escalation_dispatch_provider_closure(
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
        "failure_code": None if passed else "s73_closure_failed",
        "slice_range": "0721-0730",
        "boundary": "ag_owned_operator_review_escalation_dispatch_provider_readiness",
        "source_table": "ag_op_esc_dispatches",
        "new_tables": [],
        "provider_modes": ["mock_first_only", "mock_http", "guarded_live_http"],
        "live_network_delivery": "deferred_until_protected_transport",
        "provider_surfaces": [
            "provider_config_registry",
            "notification_request_contract",
            "external_incident_request_contract",
            "http_client_result_contract",
            "worker_provider_router",
            "operations_provider_diagnostics",
        ],
        "privacy_regression": "provider_surfaces_redacted",
        "postgres_smoke": "test_db_protected_provider_router",
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
            "s73_operator_review_escalation_dispatch_provider_closure=pass "
            f"slice_range={evidence['slice_range']} "
            f"required_files={evidence['summary']['required_file_count']} "
            f"boundary={evidence['boundary']} "
            f"table={evidence['source_table']} "
            f"modes={','.join(evidence['provider_modes'])} "
            f"privacy={evidence['privacy_regression']} "
            f"smoke={evidence['postgres_smoke']}"
        )
    return (
        "s73_operator_review_escalation_dispatch_provider_closure=fail "
        f"reason={evidence.get('failure_code')} "
        f"missing_files={evidence['summary']['missing_file_count']} "
        f"missing_tokens={evidence['summary']['missing_token_count']}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the S73 operator review escalation dispatch provider closure."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_s73_operator_review_escalation_dispatch_provider_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
