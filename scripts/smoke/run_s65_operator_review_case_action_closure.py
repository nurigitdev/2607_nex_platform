#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s65_operator_review_case_action_closure.v1"

REQUIRED_FILES = (
    "services/nex-ag/nex_ag/operator_review_cases.py",
    "services/nex-ag/nex_ag/operations.py",
    "services/nex-ag/nex_ag/main.py",
    "services/nex-ag/README.md",
    "database/nex-ag/migrations/0642_ag_operator_review_case_persistence.sql",
    "contracts/schemas/service/nex_ag/operator_review_case.v1.schema.json",
    "contracts/schemas/service/nex_ag/operator_review_case_rollup.v1.schema.json",
    "contracts/examples/operations/ag_operator_review_case_list.mock_success.json",
    "contracts/examples/operations/ag_operator_review_case_mutation.mock_success.json",
    "contracts/examples/operations/ag_operator_review_case_action_mutation.mock_success.json",
    "contracts/examples/operations/ag_operator_review_case_rollup.mock_success.json",
    "contracts/tests/negative/operations/ag_operator_review_case.raw_resolution_comment_leak.json",
    "contracts/tests/negative/operations/ag_operator_review_case_rollup.raw_action_comment_leak.json",
    "contracts/openapi/nex-ag.openapi.yaml",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ag_operator_review_case_action_boundary_audit.py",
    "scripts/smoke/run_ag_operator_review_case_postgres_smoke.py",
    "scripts/smoke/run_s65_operator_review_case_action_closure.py",
    "tests/test_ag_operator_review_case_action_boundary_audit.py",
    "tests/test_ag_operator_review_case_postgres_smoke.py",
    "tests/test_nex_ag_operator_review_cases.py",
    "tests/test_nex_ag_operations.py",
    "tests/test_s65_operator_review_case_action_closure.py",
    "tests/test_contract_validation.py",
    "docs/README.md",
    "docs/slices/0641_ag_operator_review_case_action_boundary_audit.md",
    "docs/slices/0642_ag_operator_review_case_persistence.md",
    "docs/slices/0643_ag_operator_review_case_routes.md",
    "docs/slices/0644_ag_operator_review_case_action_state_machine.md",
    "docs/slices/0645_ag_operator_review_case_action_routes.md",
    "docs/slices/0646_ag_operator_review_case_rollup_dashboard_correlation.md",
    "docs/slices/0647_ag_operator_review_case_operations_dashboard_wiring.md",
    "docs/slices/0648_ag_operator_review_case_openapi_schema_examples.md",
    "docs/slices/0649_ag_operator_review_case_postgresql_smoke.md",
    "docs/slices/0650_s65_operator_review_case_action_closure.md",
)

TOKEN_CHECKS = (
    (
        "s65_boundary_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_case_action_boundary_audit.py",
    ),
    (
        "case_postgres_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_case_postgres_smoke.py",
    ),
    (
        "s65_closure_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_s65_operator_review_case_action_closure.py",
    ),
    (
        "case_table_constant",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        'AG_OPERATOR_REVIEW_CASE_TABLE = "ag_op_cases"',
    ),
    (
        "case_sqlalchemy_store",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "SqlAlchemyOperatorReviewCaseStore",
    ),
    (
        "case_service",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "class OperatorReviewCaseService",
    ),
    (
        "case_create_route",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        '"/admin/v1/operator-review/cases"',
    ),
    (
        "case_rollup_route",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        '"/admin/v1/operator-review/cases/rollups"',
    ),
    (
        "case_action_route",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        '"/admin/v1/operator-review/cases/{case_id}/actions"',
    ),
    (
        "case_action_state_machine",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "CASE_ACTION_ALLOWED_FROM",
    ),
    (
        "case_action_event",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "ag.operator_review_case_action.recorded",
    ),
    (
        "case_idempotency_required",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "ag.operator_review_case_idempotency_key_required",
    ),
    (
        "case_action_idempotency_required",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "ag.operator_review_case_action_idempotency_key_required",
    ),
    (
        "hash_preview_only",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "hash_and_short_preview_only",
    ),
    (
        "operational_events_first",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "operational_events_first",
    ),
    (
        "case_migration_table",
        "database/nex-ag/migrations/0642_ag_operator_review_case_persistence.sql",
        "CREATE TABLE IF NOT EXISTS ag_op_cases",
    ),
    (
        "case_migration_index",
        "database/nex-ag/migrations/0642_ag_operator_review_case_persistence.sql",
        "idx_ag_op_cases_target_time",
    ),
    (
        "dashboard_section_schema",
        "services/nex-ag/nex_ag/operations.py",
        "ag_operator_review_case_dashboard_section.v1",
    ),
    (
        "main_registers_case_routes",
        "services/nex-ag/nex_ag/main.py",
        "register_operator_review_case_routes",
    ),
    (
        "main_wires_case_store",
        "services/nex-ag/nex_ag/main.py",
        "operator_review_case_store=OPERATOR_REVIEW_CASE_STORE",
    ),
    (
        "case_openapi_path",
        "contracts/openapi/nex-ag.openapi.yaml",
        "/admin/v1/operator-review/cases",
    ),
    (
        "case_action_openapi_path",
        "contracts/openapi/nex-ag.openapi.yaml",
        "/admin/v1/operator-review/cases/{case_id}/actions",
    ),
    (
        "case_contract_schema",
        "contracts/schemas/service/nex_ag/operator_review_case.v1.schema.json",
        "ag_operator_review_case_action_mutation.v1",
    ),
    (
        "case_rollup_contract_schema",
        "contracts/schemas/service/nex_ag/operator_review_case_rollup.v1.schema.json",
        "raw_action_comment_included",
    ),
    (
        "case_negative_resolution_leak",
        "contracts/tests/negative/operations/ag_operator_review_case.raw_resolution_comment_leak.json",
        "raw_resolution_comment",
    ),
    (
        "case_negative_rollup_comment_leak",
        "contracts/tests/negative/operations/ag_operator_review_case_rollup.raw_action_comment_leak.json",
        "action_comment_preview",
    ),
    (
        "postgres_opt_in",
        "scripts/smoke/run_ag_operator_review_case_postgres_smoke.py",
        "NEX_AG_OPERATOR_REVIEW_CASE_POSTGRES_SMOKE",
    ),
    (
        "postgres_direct_case_table",
        "scripts/smoke/run_ag_operator_review_case_postgres_smoke.py",
        "ag_op_cases",
    ),
    (
        "postgres_cleanup",
        "scripts/smoke/run_ag_operator_review_case_postgres_smoke.py",
        "_cleanup_case_rows",
    ),
    (
        "doc_index_0650",
        "docs/README.md",
        "Slice 0650",
    ),
)

REDACTION_SCAN_FILES = (
    "services/nex-ag/README.md",
    "docs/slices/0641_ag_operator_review_case_action_boundary_audit.md",
    "docs/slices/0642_ag_operator_review_case_persistence.md",
    "docs/slices/0643_ag_operator_review_case_routes.md",
    "docs/slices/0644_ag_operator_review_case_action_state_machine.md",
    "docs/slices/0645_ag_operator_review_case_action_routes.md",
    "docs/slices/0646_ag_operator_review_case_rollup_dashboard_correlation.md",
    "docs/slices/0647_ag_operator_review_case_operations_dashboard_wiring.md",
    "docs/slices/0648_ag_operator_review_case_openapi_schema_examples.md",
    "docs/slices/0649_ag_operator_review_case_postgresql_smoke.md",
    "docs/slices/0650_s65_operator_review_case_action_closure.md",
)


def run_s65_operator_review_case_action_closure(root: Path = ROOT) -> dict[str, Any]:
    required_file_results = _required_file_results(root)
    token_results = _token_results(root)
    redaction_summary = _redaction_summary(root)
    table_lengths = {"ag_op_cases": len("ag_op_cases")}
    checks = {
        "required_files_present": all(
            item["present"] for item in required_file_results
        ),
        "token_checks_present": all(item["present"] for item in token_results),
        "slice_docs_contiguous": _slice_docs_contiguous(root),
        "redaction_scan_safe": not any(
            value is True
            for key, value in redaction_summary.items()
            if key.endswith("_included")
        ),
        "table_names_short": all(length <= 30 for length in table_lengths.values()),
        "experience_matrix_closed": all(_experience_matrix(token_results).values()),
    }
    status = "PASS" if all(checks.values()) else "FAIL"
    evidence = {
        "closure_schema_version": SCHEMA_VERSION,
        "status": status,
        "slice_range": "0641-0650",
        "boundary": "ag_owned_operator_review_cases_actions",
        "owned_tables": table_lengths,
        "action_history_policy": "operational_events_first",
        "raw_payload_storage": "hash_and_short_preview_only",
        "required_file_count": len(REQUIRED_FILES),
        "token_check_count": len(TOKEN_CHECKS),
        "checks": checks,
        "experience_matrix": _experience_matrix(token_results),
        "redaction_summary": redaction_summary,
        "required_file_results": required_file_results,
        "token_results": token_results,
    }
    if status != "PASS":
        evidence["failure_code"] = "closure_checks_failed"
        evidence["failed_checks"] = [
            key for key, passed in checks.items() if not passed
        ]
    return evidence


def _required_file_results(root: Path) -> list[dict[str, Any]]:
    return [
        {"path": relative_path, "present": (root / relative_path).is_file()}
        for relative_path in REQUIRED_FILES
    ]


def _token_results(root: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for check_id, relative_path, token in TOKEN_CHECKS:
        text = _read_text(root / relative_path)
        results.append(
            {"check_id": check_id, "path": relative_path, "present": token in text}
        )
    return results


def _slice_docs_contiguous(root: Path) -> bool:
    docs_dir = root / "docs" / "slices"
    if not docs_dir.is_dir():
        return False
    existing = {path.name for path in docs_dir.glob("*.md")}
    return all(
        any(name.startswith(f"{number:04d}_") for name in existing)
        for number in range(641, 651)
    )


def _experience_matrix(token_results: list[dict[str, Any]]) -> dict[str, bool]:
    present = {item["check_id"]: item["present"] for item in token_results}
    return {
        "boundary_audit": present.get("s65_boundary_quality_gate_hook", False),
        "case_persistence": present.get("case_table_constant", False)
        and present.get("case_sqlalchemy_store", False)
        and present.get("case_migration_table", False)
        and present.get("case_migration_index", False),
        "case_routes_and_actions": present.get("case_create_route", False)
        and present.get("case_action_route", False)
        and present.get("case_action_state_machine", False)
        and present.get("case_action_event", False),
        "idempotency_and_redaction": present.get("case_idempotency_required", False)
        and present.get("case_action_idempotency_required", False)
        and present.get("hash_preview_only", False)
        and present.get("operational_events_first", False),
        "rollup_dashboard": present.get("case_rollup_route", False)
        and present.get("dashboard_section_schema", False)
        and present.get("main_wires_case_store", False),
        "contracts_and_openapi": present.get("case_openapi_path", False)
        and present.get("case_action_openapi_path", False)
        and present.get("case_contract_schema", False)
        and present.get("case_rollup_contract_schema", False)
        and present.get("case_negative_resolution_leak", False)
        and present.get("case_negative_rollup_comment_leak", False),
        "postgres_smoke": present.get("case_postgres_quality_gate_hook", False)
        and present.get("postgres_opt_in", False)
        and present.get("postgres_direct_case_table", False)
        and present.get("postgres_cleanup", False),
        "runtime_registration": present.get("main_registers_case_routes", False),
        "closure_checkpoint": present.get("s65_closure_quality_gate_hook", False)
        and present.get("doc_index_0650", False),
    }


def _redaction_summary(root: Path) -> dict[str, bool]:
    text = "\n".join(_read_text(root / path) for path in REDACTION_SCAN_FILES)
    return {
        "database_url_included": bool(
            re.search(r"postgres(?:ql)?(?:\+psycopg)?://[^*\s]+:[^*\s]+@", text)
        ),
        "shared_password_included": "nuri1004" in text,
        "provider_api_key_included": "ed6@c496em" in text,
        "raw_action_comment_sentinel_included": (
            "AG case smoke raw action comment must stay out of evidence." in text
        ),
        "raw_resolution_comment_sentinel_included": (
            "This raw resolution body must never leave the AG case boundary." in text
        ),
        "raw_idempotency_key_included": "ag-op-case-create-idem" in text
        or "ag-op-case-action-idem" in text,
        "storage_path_included": "/data/nex-platform/private/raw-0650.pdf" in text,
        "postgres_smoke_documented": (
            "NEX_AG_OPERATOR_REVIEW_CASE_POSTGRES_SMOKE=1" in text
            and "nex_ag_test" in text
        ),
        "ag_owned_boundary_documented": "ag_owned_operator_review_cases_actions" in text,
        "operational_events_first_documented": "operational_events_first" in text,
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        return (
            "s65_operator_review_case_action_closure=pass "
            f"slice_range={evidence['slice_range']} "
            f"required_files={evidence['required_file_count']} "
            f"boundary={evidence['boundary']} "
            "owned_tables=ag_op_cases "
            "smoke=test_db_case_action action_history=operational_events_first"
        )
    failed = ",".join(evidence.get("failed_checks", []))
    return f"s65_operator_review_case_action_closure=fail failed_checks={failed}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the S65 operator review case/action closure checkpoint."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_s65_operator_review_case_action_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
