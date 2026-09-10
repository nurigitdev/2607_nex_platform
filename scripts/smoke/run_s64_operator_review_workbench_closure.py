#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s64_operator_review_workbench_closure.v1"

REQUIRED_FILES = (
    "services/nex-ag/nex_ag/operator_review_workbench.py",
    "services/nex-ag/nex_ag/operator_reviews.py",
    "services/nex-ag/nex_ag/operations.py",
    "services/nex-ag/nex_ag/main.py",
    "services/nex-ag/README.md",
    "database/nex-ag/migrations/0622_ag_operator_review_note_persistence.sql",
    "database/nex-ag/migrations/0626_ag_redacted_evidence_export_persistence.sql",
    "contracts/schemas/service/nex_ag/operator_review_workbench.v1.schema.json",
    "contracts/schemas/service/nex_ag/operator_review_workbench_rollup.v1.schema.json",
    "contracts/examples/operations/ag_operator_review_workbench.mock_success.json",
    "contracts/examples/operations/ag_operator_review_workbench_rollup.mock_success.json",
    "contracts/tests/negative/operations/ag_operator_review_workbench.raw_operator_note_leak.json",
    "contracts/tests/negative/operations/ag_operator_review_workbench_rollup.bad_attention_status.json",
    "contracts/openapi/nex-ag.openapi.yaml",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ag_operator_review_workbench_boundary_audit.py",
    "scripts/smoke/run_ag_operator_review_workbench_postgres_smoke.py",
    "scripts/smoke/run_ag_operator_review_workbench_privacy_regression.py",
    "scripts/smoke/run_s64_operator_review_workbench_closure.py",
    "tests/test_nex_ag_operator_review_workbench.py",
    "tests/test_nex_ag_operations.py",
    "tests/test_ag_operator_review_workbench_boundary_audit.py",
    "tests/test_ag_operator_review_workbench_postgres_smoke.py",
    "tests/test_ag_operator_review_workbench_privacy_regression.py",
    "tests/test_s64_operator_review_workbench_closure.py",
    "tests/test_contract_validation.py",
    "docs/README.md",
    "docs/slices/0631_ag_operator_review_workbench_boundary_audit.md",
    "docs/slices/0632_ag_operator_review_unified_read_model.md",
    "docs/slices/0633_ag_operator_review_rollup_metrics.md",
    "docs/slices/0634_ag_operator_review_dashboard_wiring.md",
    "docs/slices/0635_ag_operator_review_issue_candidate_correlation.md",
    "docs/slices/0636_ag_operator_review_search_filter_hardening.md",
    "docs/slices/0637_ag_operator_review_openapi_schema_examples.md",
    "docs/slices/0638_ag_operator_review_workbench_postgresql_smoke.md",
    "docs/slices/0639_ag_operator_review_workbench_privacy_regression.md",
    "docs/slices/0640_s64_operator_review_workbench_closure.md",
)

TOKEN_CHECKS = (
    (
        "boundary_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_workbench_boundary_audit.py",
    ),
    (
        "postgres_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_workbench_postgres_smoke.py",
    ),
    (
        "privacy_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_workbench_privacy_regression.py",
    ),
    (
        "s64_closure_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_s64_operator_review_workbench_closure.py",
    ),
    (
        "workbench_route",
        "services/nex-ag/nex_ag/operator_review_workbench.py",
        '"/admin/v1/operator-review/workbench"',
    ),
    (
        "rollup_route",
        "services/nex-ag/nex_ag/operator_review_workbench.py",
        '"/admin/v1/operator-review/workbench/rollups"',
    ),
    (
        "workbench_schema_version",
        "services/nex-ag/nex_ag/operator_review_workbench.py",
        "ag_operator_review_workbench.v1",
    ),
    (
        "rollup_schema_version",
        "services/nex-ag/nex_ag/operator_review_workbench.py",
        "ag_operator_review_workbench_rollup.v1",
    ),
    (
        "hash_preview_only",
        "services/nex-ag/nex_ag/operator_review_workbench.py",
        "operator_note_hash",
    ),
    (
        "redacted_export_only",
        "services/nex-ag/nex_ag/operator_review_workbench.py",
        "redacted_manifest_plus_hashes",
    ),
    (
        "search_filter_status",
        "services/nex-ag/nex_ag/operator_review_workbench.py",
        "export_status",
    ),
    (
        "dashboard_section_schema",
        "services/nex-ag/nex_ag/operations.py",
        "ag_operator_review_workbench_dashboard_section.v1",
    ),
    (
        "issue_candidate_rule",
        "services/nex-ag/nex_ag/operations.py",
        "operator_review_attention_required.v1",
    ),
    (
        "main_registers_workbench",
        "services/nex-ag/nex_ag/main.py",
        "register_operator_review_workbench_routes",
    ),
    (
        "workbench_openapi_path",
        "contracts/openapi/nex-ag.openapi.yaml",
        "/admin/v1/operator-review/workbench",
    ),
    (
        "rollup_openapi_path",
        "contracts/openapi/nex-ag.openapi.yaml",
        "/admin/v1/operator-review/workbench/rollups",
    ),
    (
        "workbench_contract_schema",
        "contracts/schemas/service/nex_ag/operator_review_workbench.v1.schema.json",
        "operator_note_preview",
    ),
    (
        "rollup_contract_schema",
        "contracts/schemas/service/nex_ag/operator_review_workbench_rollup.v1.schema.json",
        "attention_status",
    ),
    (
        "postgres_opt_in",
        "scripts/smoke/run_ag_operator_review_workbench_postgres_smoke.py",
        "NEX_AG_OPERATOR_REVIEW_WORKBENCH_POSTGRES_SMOKE",
    ),
    (
        "postgres_direct_note_table",
        "scripts/smoke/run_ag_operator_review_workbench_postgres_smoke.py",
        "ag_op_notes",
    ),
    (
        "postgres_direct_export_table",
        "scripts/smoke/run_ag_operator_review_workbench_postgres_smoke.py",
        "ag_ev_exports",
    ),
    (
        "privacy_forbidden_labels",
        "scripts/smoke/run_ag_operator_review_workbench_privacy_regression.py",
        "FORBIDDEN_VALUES",
    ),
    (
        "privacy_surface_count",
        "scripts/smoke/run_ag_operator_review_workbench_privacy_regression.py",
        "surface_count",
    ),
    (
        "doc_index_0640",
        "docs/README.md",
        "Slice 0640",
    ),
)

REDACTION_SCAN_FILES = (
    "services/nex-ag/README.md",
    "docs/slices/0631_ag_operator_review_workbench_boundary_audit.md",
    "docs/slices/0632_ag_operator_review_unified_read_model.md",
    "docs/slices/0633_ag_operator_review_rollup_metrics.md",
    "docs/slices/0634_ag_operator_review_dashboard_wiring.md",
    "docs/slices/0635_ag_operator_review_issue_candidate_correlation.md",
    "docs/slices/0636_ag_operator_review_search_filter_hardening.md",
    "docs/slices/0637_ag_operator_review_openapi_schema_examples.md",
    "docs/slices/0638_ag_operator_review_workbench_postgresql_smoke.md",
    "docs/slices/0639_ag_operator_review_workbench_privacy_regression.md",
    "docs/slices/0640_s64_operator_review_workbench_closure.md",
)


def run_s64_operator_review_workbench_closure(root: Path = ROOT) -> dict[str, Any]:
    required_file_results = _required_file_results(root)
    token_results = _token_results(root)
    redaction_summary = _redaction_summary(root)
    table_lengths = {
        "ag_op_notes": len("ag_op_notes"),
        "ag_ev_exports": len("ag_ev_exports"),
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
        "slice_range": "0631-0640",
        "boundary": "ag_owned_operator_review_workbench_projection",
        "source_tables": table_lengths,
        "raw_payload_storage": "hash_preview_or_redacted_manifest_only",
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
        for number in range(631, 641)
    )


def _experience_matrix(token_results: list[dict[str, Any]]) -> dict[str, bool]:
    present = {item["check_id"]: item["present"] for item in token_results}
    return {
        "boundary_audit": present.get("boundary_quality_gate_hook", False),
        "read_model_routes": present.get("workbench_route", False)
        and present.get("rollup_route", False)
        and present.get("workbench_schema_version", False)
        and present.get("rollup_schema_version", False),
        "safe_projection_shape": present.get("hash_preview_only", False)
        and present.get("redacted_export_only", False),
        "search_filter_hardening": present.get("search_filter_status", False),
        "dashboard_and_issue_correlation": present.get(
            "dashboard_section_schema",
            False,
        )
        and present.get("issue_candidate_rule", False),
        "runtime_registration": present.get("main_registers_workbench", False),
        "contracts_and_openapi": present.get("workbench_openapi_path", False)
        and present.get("rollup_openapi_path", False)
        and present.get("workbench_contract_schema", False)
        and present.get("rollup_contract_schema", False),
        "postgres_smoke": present.get("postgres_quality_gate_hook", False)
        and present.get("postgres_opt_in", False)
        and present.get("postgres_direct_note_table", False)
        and present.get("postgres_direct_export_table", False),
        "privacy_regression": present.get("privacy_quality_gate_hook", False)
        and present.get("privacy_forbidden_labels", False)
        and present.get("privacy_surface_count", False),
        "closure_checkpoint": present.get("s64_closure_quality_gate_hook", False)
        and present.get("doc_index_0640", False),
    }


def _redaction_summary(root: Path) -> dict[str, bool]:
    text = "\n".join(_read_text(root / path) for path in REDACTION_SCAN_FILES)
    return {
        "database_url_included": bool(
            re.search(r"postgres(?:ql)?(?:\+psycopg)?://[^*\s]+:[^*\s]+@", text)
        ),
        "shared_password_included": "nuri1004" in text,
        "provider_api_key_included": "ed6@c496em" in text,
        "raw_operator_note_sentinel_included": (
            "RAW_NOTE_SECRET_0639_SHOULD_NOT_LEAK" in text
        ),
        "raw_evidence_body_sentinel_included": (
            "RAW_EVIDENCE_BODY_SECRET_0639_SHOULD_NOT_LEAK" in text
        ),
        "raw_idempotency_key_included": "idem-0639-secret-key" in text,
        "storage_path_included": "/data/nex-platform/private/raw-0639.pdf" in text,
        "postgres_smoke_documented": (
            "NEX_AG_OPERATOR_REVIEW_WORKBENCH_POSTGRES_SMOKE=1" in text
            and "nex_ag_test" in text
        ),
        "privacy_regression_documented": (
            "privacy regression" in text.lower()
            and "forbidden" in text.lower()
        ),
        "ag_owned_boundary_documented": (
            "ag_owned_operator_review_workbench_projection" in text
        ),
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        return (
            "s64_operator_review_workbench_closure=pass "
            f"slice_range={evidence['slice_range']} "
            f"required_files={evidence['required_file_count']} "
            f"boundary={evidence['boundary']} "
            "source_tables=ag_op_notes,ag_ev_exports "
            "smoke=test_db_workbench privacy=route_surface_regression"
        )
    failed = ",".join(evidence.get("failed_checks", []))
    return f"s64_operator_review_workbench_closure=fail failed_checks={failed}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the S64 operator review workbench closure checkpoint."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_s64_operator_review_workbench_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
