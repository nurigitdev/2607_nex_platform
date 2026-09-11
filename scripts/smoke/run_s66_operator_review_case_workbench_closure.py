#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s66_operator_review_case_workbench_closure.v1"

REQUIRED_FILES = (
    "services/nex-ag/nex_ag/operator_review_cases.py",
    "services/nex-ag/nex_ag/operations.py",
    "services/nex-ag/nex_ag/main.py",
    "services/nex-ag/README.md",
    "database/nex-ag/migrations/0642_ag_operator_review_case_persistence.sql",
    "database/nex-ag/migrations/0085_service_operational_events_foundation.sql",
    "contracts/schemas/service/nex_ag/operator_review_case_workbench.v1.schema.json",
    "contracts/examples/operations/ag_operator_review_case_queue.mock_success.json",
    "contracts/examples/operations/ag_operator_review_case_workbench_detail.mock_success.json",
    "contracts/examples/operations/ag_operator_review_case_timeline.mock_success.json",
    "contracts/tests/negative/operations/ag_operator_review_case_queue.raw_action_comment_leak.json",
    "contracts/tests/negative/operations/ag_operator_review_case_workbench_detail.raw_resolution_comment_leak.json",
    "contracts/tests/negative/operations/ag_operator_review_case_timeline.raw_action_comment_leak.json",
    "contracts/openapi/nex-ag.openapi.yaml",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ag_operator_review_case_workbench_boundary_audit.py",
    "scripts/smoke/run_ag_operator_review_case_workbench_postgres_smoke.py",
    "scripts/smoke/run_ag_operator_review_case_workbench_privacy_regression.py",
    "scripts/smoke/run_s66_operator_review_case_workbench_closure.py",
    "tests/test_ag_operator_review_case_workbench_boundary_audit.py",
    "tests/test_ag_operator_review_case_workbench_postgres_smoke.py",
    "tests/test_ag_operator_review_case_workbench_privacy_regression.py",
    "tests/test_nex_ag_operator_review_cases.py",
    "tests/test_nex_ag_operations.py",
    "tests/test_s66_operator_review_case_workbench_closure.py",
    "tests/test_contract_validation.py",
    "docs/README.md",
    "docs/slices/0651_ag_operator_review_case_workbench_boundary_audit.md",
    "docs/slices/0652_ag_operator_review_case_queue_read_model.md",
    "docs/slices/0653_ag_operator_review_case_queue_filter_search_sort.md",
    "docs/slices/0654_ag_operator_review_case_workbench_detail_projection.md",
    "docs/slices/0655_ag_operator_review_case_timeline_projection.md",
    "docs/slices/0656_ag_operator_review_case_dashboard_issue_signal.md",
    "docs/slices/0657_ag_operator_review_case_workbench_contract_openapi.md",
    "docs/slices/0658_ag_operator_review_case_workbench_postgresql_smoke.md",
    "docs/slices/0659_ag_operator_review_case_workbench_privacy_regression.md",
    "docs/slices/0660_s66_operator_review_case_workbench_closure.md",
)

TOKEN_CHECKS = (
    (
        "s66_boundary_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_case_workbench_boundary_audit.py",
    ),
    (
        "case_workbench_postgres_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_case_workbench_postgres_smoke.py",
    ),
    (
        "case_workbench_privacy_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_case_workbench_privacy_regression.py",
    ),
    (
        "s66_closure_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_s66_operator_review_case_workbench_closure.py",
    ),
    (
        "case_table_constant",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        'AG_OPERATOR_REVIEW_CASE_TABLE = "ag_op_cases"',
    ),
    (
        "case_queue_route",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        '"/admin/v1/operator-review/cases/queue"',
    ),
    (
        "case_workbench_detail_route",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        '"/admin/v1/operator-review/cases/{case_id}/workbench-detail"',
    ),
    (
        "case_timeline_route",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        '"/admin/v1/operator-review/cases/{case_id}/timeline"',
    ),
    (
        "case_queue_schema_version",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "ag_operator_review_case_queue.v1",
    ),
    (
        "case_workbench_detail_schema_version",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "ag_operator_review_case_workbench_detail.v1",
    ),
    (
        "case_timeline_schema_version",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "ag_operator_review_case_timeline.v1",
    ),
    (
        "case_recorded_event_type",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "ag.operator_review_case.recorded",
    ),
    (
        "case_action_recorded_event_type",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "ag.operator_review_case_action.recorded",
    ),
    (
        "operational_events_first",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "operational_events_first",
    ),
    (
        "safe_queue_payload_shape",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "safe_refs_hashes_and_bounded_previews_only",
    ),
    (
        "timeline_metadata_only",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "operational_event_metadata_only",
    ),
    (
        "dashboard_case_section_schema",
        "services/nex-ag/nex_ag/operations.py",
        "ag_operator_review_case_dashboard_section.v1",
    ),
    (
        "dashboard_case_queue_path",
        "services/nex-ag/nex_ag/operations.py",
        'case_queue_path": "/admin/v1/operator-review/cases/queue"',
    ),
    (
        "dashboard_case_workbench_detail_path_template",
        "services/nex-ag/nex_ag/operations.py",
        "case_workbench_detail_path_template",
    ),
    (
        "dashboard_case_timeline_path_template",
        "services/nex-ag/nex_ag/operations.py",
        "case_timeline_path_template",
    ),
    (
        "issue_candidate_rule",
        "services/nex-ag/nex_ag/operations.py",
        "operator_review_case_attention_required.v1",
    ),
    (
        "case_migration_table",
        "database/nex-ag/migrations/0642_ag_operator_review_case_persistence.sql",
        "CREATE TABLE IF NOT EXISTS ag_op_cases",
    ),
    (
        "event_migration_table",
        "database/nex-ag/migrations/0085_service_operational_events_foundation.sql",
        "CREATE TABLE IF NOT EXISTS service_operational_events",
    ),
    (
        "event_migration_type_index",
        "database/nex-ag/migrations/0085_service_operational_events_foundation.sql",
        "ix_service_operational_events_type",
    ),
    (
        "case_workbench_contract_queue",
        "contracts/schemas/service/nex_ag/operator_review_case_workbench.v1.schema.json",
        "ag_operator_review_case_queue.v1",
    ),
    (
        "case_workbench_contract_detail",
        "contracts/schemas/service/nex_ag/operator_review_case_workbench.v1.schema.json",
        "ag_operator_review_case_workbench_detail.v1",
    ),
    (
        "case_workbench_contract_timeline",
        "contracts/schemas/service/nex_ag/operator_review_case_workbench.v1.schema.json",
        "ag_operator_review_case_timeline.v1",
    ),
    (
        "case_workbench_contract_redaction",
        "contracts/schemas/service/nex_ag/operator_review_case_workbench.v1.schema.json",
        "raw_action_comment_included",
    ),
    (
        "case_workbench_openapi_queue",
        "contracts/openapi/nex-ag.openapi.yaml",
        "/admin/v1/operator-review/cases/queue",
    ),
    (
        "case_workbench_openapi_detail",
        "contracts/openapi/nex-ag.openapi.yaml",
        "/admin/v1/operator-review/cases/{case_id}/workbench-detail",
    ),
    (
        "case_workbench_openapi_timeline",
        "contracts/openapi/nex-ag.openapi.yaml",
        "/admin/v1/operator-review/cases/{case_id}/timeline",
    ),
    (
        "case_workbench_postgres_opt_in",
        "scripts/smoke/run_ag_operator_review_case_workbench_postgres_smoke.py",
        "NEX_AG_OPERATOR_REVIEW_CASE_WORKBENCH_POSTGRES_SMOKE",
    ),
    (
        "case_workbench_postgres_direct_case_table",
        "scripts/smoke/run_ag_operator_review_case_workbench_postgres_smoke.py",
        "ag_op_cases",
    ),
    (
        "case_workbench_postgres_direct_event_table",
        "scripts/smoke/run_ag_operator_review_case_workbench_postgres_smoke.py",
        "service_operational_events",
    ),
    (
        "case_workbench_privacy_forbidden_values",
        "scripts/smoke/run_ag_operator_review_case_workbench_privacy_regression.py",
        "FORBIDDEN_VALUES",
    ),
    (
        "case_workbench_privacy_surface_count",
        "scripts/smoke/run_ag_operator_review_case_workbench_privacy_regression.py",
        "surface_count",
    ),
    (
        "doc_index_0660",
        "docs/README.md",
        "Slice 0660",
    ),
)

REDACTION_SCAN_FILES = (
    "services/nex-ag/README.md",
    "docs/slices/0651_ag_operator_review_case_workbench_boundary_audit.md",
    "docs/slices/0652_ag_operator_review_case_queue_read_model.md",
    "docs/slices/0653_ag_operator_review_case_queue_filter_search_sort.md",
    "docs/slices/0654_ag_operator_review_case_workbench_detail_projection.md",
    "docs/slices/0655_ag_operator_review_case_timeline_projection.md",
    "docs/slices/0656_ag_operator_review_case_dashboard_issue_signal.md",
    "docs/slices/0657_ag_operator_review_case_workbench_contract_openapi.md",
    "docs/slices/0658_ag_operator_review_case_workbench_postgresql_smoke.md",
    "docs/slices/0659_ag_operator_review_case_workbench_privacy_regression.md",
    "docs/slices/0660_s66_operator_review_case_workbench_closure.md",
)


def run_s66_operator_review_case_workbench_closure(root: Path = ROOT) -> dict[str, Any]:
    required_file_results = _required_file_results(root)
    token_results = _token_results(root)
    redaction_summary = _redaction_summary(root)
    table_lengths = {
        "ag_op_cases": len("ag_op_cases"),
        "service_operational_events": len("service_operational_events"),
    }
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
        "slice_range": "0651-0660",
        "boundary": "ag_owned_operator_review_case_workbench_projection",
        "source_tables": table_lengths,
        "action_history_policy": "operational_events_first",
        "raw_payload_storage": "hash_preview_or_event_metadata_only",
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
        for number in range(651, 661)
    )


def _experience_matrix(token_results: list[dict[str, Any]]) -> dict[str, bool]:
    present = {item["check_id"]: item["present"] for item in token_results}
    return {
        "boundary_audit": present.get("s66_boundary_quality_gate_hook", False),
        "queue_read_model": present.get("case_queue_route", False)
        and present.get("case_queue_schema_version", False)
        and present.get("safe_queue_payload_shape", False),
        "workbench_detail": present.get("case_workbench_detail_route", False)
        and present.get("case_workbench_detail_schema_version", False),
        "timeline_projection": present.get("case_timeline_route", False)
        and present.get("case_timeline_schema_version", False)
        and present.get("case_recorded_event_type", False)
        and present.get("case_action_recorded_event_type", False)
        and present.get("operational_events_first", False)
        and present.get("timeline_metadata_only", False),
        "dashboard_and_issue_signal": present.get(
            "dashboard_case_section_schema",
            False,
        )
        and present.get("dashboard_case_queue_path", False)
        and present.get("dashboard_case_workbench_detail_path_template", False)
        and present.get("dashboard_case_timeline_path_template", False)
        and present.get("issue_candidate_rule", False),
        "persistence_sources": present.get("case_table_constant", False)
        and present.get("case_migration_table", False)
        and present.get("event_migration_table", False)
        and present.get("event_migration_type_index", False),
        "contracts_and_openapi": present.get("case_workbench_contract_queue", False)
        and present.get("case_workbench_contract_detail", False)
        and present.get("case_workbench_contract_timeline", False)
        and present.get("case_workbench_contract_redaction", False)
        and present.get("case_workbench_openapi_queue", False)
        and present.get("case_workbench_openapi_detail", False)
        and present.get("case_workbench_openapi_timeline", False),
        "postgres_smoke": present.get(
            "case_workbench_postgres_quality_gate_hook",
            False,
        )
        and present.get("case_workbench_postgres_opt_in", False)
        and present.get("case_workbench_postgres_direct_case_table", False)
        and present.get("case_workbench_postgres_direct_event_table", False),
        "privacy_regression": present.get(
            "case_workbench_privacy_quality_gate_hook",
            False,
        )
        and present.get("case_workbench_privacy_forbidden_values", False)
        and present.get("case_workbench_privacy_surface_count", False),
        "closure_checkpoint": present.get("s66_closure_quality_gate_hook", False)
        and present.get("doc_index_0660", False),
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
            "RAW_ACTION_SECRET_0659_SHOULD_NOT_LEAK" in text
        ),
        "raw_resolution_comment_sentinel_included": (
            "RAW_RESOLUTION_SECRET_0659_SHOULD_NOT_LEAK" in text
        ),
        "raw_prompt_sentinel_included": "RAW_PROMPT_SECRET_0659_SHOULD_NOT_LEAK" in text,
        "raw_source_text_sentinel_included": (
            "RAW_SOURCE_TEXT_SECRET_0659_SHOULD_NOT_LEAK" in text
        ),
        "raw_idempotency_key_included": "idem-0659-secret-key" in text
        or "ag-op-case-workbench-create-idem" in text,
        "storage_path_included": "/data/nex-platform/private/case-workbench-0659.pdf"
        in text,
        "postgres_smoke_documented": (
            "NEX_AG_OPERATOR_REVIEW_CASE_WORKBENCH_POSTGRES_SMOKE=1" in text
            and "nex_ag_test" in text
        ),
        "privacy_regression_documented": (
            "privacy regression" in text.lower()
            and "forbidden_labels=11" in text
        ),
        "ag_owned_boundary_documented": (
            "ag_owned_operator_review_case_workbench_projection" in text
        ),
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
            "s66_operator_review_case_workbench_closure=pass "
            f"slice_range={evidence['slice_range']} "
            f"required_files={evidence['required_file_count']} "
            f"boundary={evidence['boundary']} "
            "source_tables=ag_op_cases,service_operational_events "
            "smoke=test_db_case_workbench privacy=route_surface_regression"
        )
    failed = ",".join(evidence.get("failed_checks", []))
    return f"s66_operator_review_case_workbench_closure=fail failed_checks={failed}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the S66 operator review case workbench closure checkpoint."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_s66_operator_review_case_workbench_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
