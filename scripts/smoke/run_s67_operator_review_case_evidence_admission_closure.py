#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s67_operator_review_case_evidence_admission_closure.v1"

REQUIRED_FILES = (
    "services/nex-ag/nex_ag/operator_review_cases.py",
    "services/nex-ag/nex_ag/operator_reviews.py",
    "services/nex-ag/README.md",
    "database/nex-ag/migrations/0642_ag_operator_review_case_persistence.sql",
    "database/nex-ag/migrations/0622_ag_operator_review_note_persistence.sql",
    "database/nex-ag/migrations/0626_ag_redacted_evidence_export_persistence.sql",
    "contracts/schemas/service/nex_ag/operator_review_case_workbench.v1.schema.json",
    "contracts/examples/operations/ag_operator_review_case_workbench_detail.mock_success.json",
    "contracts/examples/operations/ag_operator_review_case_evidence_links.mock_success.json",
    "contracts/examples/operations/ag_operator_review_case_action_admission.mock_success.json",
    "contracts/openapi/nex-ag.openapi.yaml",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ag_operator_review_case_evidence_admission_boundary_audit.py",
    "scripts/smoke/run_ag_operator_review_case_evidence_admission_postgres_smoke.py",
    "scripts/smoke/run_ag_operator_review_case_evidence_admission_privacy_regression.py",
    "scripts/smoke/run_s67_operator_review_case_evidence_admission_closure.py",
    "tests/test_ag_operator_review_case_evidence_admission_boundary_audit.py",
    "tests/test_ag_operator_review_case_evidence_admission_postgres_smoke.py",
    "tests/test_ag_operator_review_case_evidence_admission_privacy_regression.py",
    "tests/test_nex_ag_operator_review_cases.py",
    "tests/test_contract_validation.py",
    "tests/test_s67_operator_review_case_evidence_admission_closure.py",
    "docs/README.md",
    "docs/slices/0661_ag_operator_review_case_evidence_admission_boundary_audit.md",
    "docs/slices/0662_ag_operator_review_case_evidence_link_read_model.md",
    "docs/slices/0663_ag_operator_review_case_evidence_link_routes.md",
    "docs/slices/0664_ag_operator_review_case_action_admission_model.md",
    "docs/slices/0665_ag_operator_review_case_action_admission_routes.md",
    "docs/slices/0666_ag_operator_review_case_detail_evidence_admission_integration.md",
    "docs/slices/0667_ag_operator_review_case_evidence_admission_contract_openapi.md",
    "docs/slices/0668_ag_operator_review_case_evidence_admission_postgresql_smoke.md",
    "docs/slices/0669_ag_operator_review_case_evidence_admission_privacy_regression.md",
    "docs/slices/0670_s67_operator_review_case_evidence_admission_closure.md",
)

TOKEN_CHECKS = (
    (
        "s67_boundary_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_case_evidence_admission_boundary_audit.py",
    ),
    (
        "s67_postgres_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_case_evidence_admission_postgres_smoke.py",
    ),
    (
        "s67_privacy_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_case_evidence_admission_privacy_regression.py",
    ),
    (
        "s67_closure_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_s67_operator_review_case_evidence_admission_closure.py",
    ),
    (
        "case_table_constant",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        'AG_OPERATOR_REVIEW_CASE_TABLE = "ag_op_cases"',
    ),
    (
        "note_table_constant",
        "services/nex-ag/nex_ag/operator_reviews.py",
        'AG_OPERATOR_NOTE_TABLE = "ag_op_notes"',
    ),
    (
        "export_table_constant",
        "services/nex-ag/nex_ag/operator_reviews.py",
        'AG_EVIDENCE_EXPORT_TABLE = "ag_ev_exports"',
    ),
    (
        "workbench_detail_route",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        '"/admin/v1/operator-review/cases/{case_id}/workbench-detail"',
    ),
    (
        "evidence_links_route",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        '"/admin/v1/operator-review/cases/{case_id}/evidence-links"',
    ),
    (
        "action_admission_route",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        '"/admin/v1/operator-review/cases/{case_id}/action-admission"',
    ),
    (
        "evidence_links_schema_version",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "ag_operator_review_case_evidence_links.v1",
    ),
    (
        "action_admission_schema_version",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "ag_operator_review_case_action_admission.v1",
    ),
    (
        "detail_evidence_summary",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "inline_items_included",
    ),
    (
        "admission_preflight_only",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "preflight_only",
    ),
    (
        "note_migration_table",
        "database/nex-ag/migrations/0622_ag_operator_review_note_persistence.sql",
        "CREATE TABLE IF NOT EXISTS ag_op_notes",
    ),
    (
        "export_migration_table",
        "database/nex-ag/migrations/0626_ag_redacted_evidence_export_persistence.sql",
        "CREATE TABLE IF NOT EXISTS ag_ev_exports",
    ),
    (
        "case_migration_table",
        "database/nex-ag/migrations/0642_ag_operator_review_case_persistence.sql",
        "CREATE TABLE IF NOT EXISTS ag_op_cases",
    ),
    (
        "contract_evidence_links",
        "contracts/schemas/service/nex_ag/operator_review_case_workbench.v1.schema.json",
        "ag_operator_review_case_evidence_links.v1",
    ),
    (
        "contract_action_admission",
        "contracts/schemas/service/nex_ag/operator_review_case_workbench.v1.schema.json",
        "ag_operator_review_case_action_admission.v1",
    ),
    (
        "contract_safe_redaction",
        "contracts/schemas/service/nex_ag/operator_review_case_workbench.v1.schema.json",
        "raw_evidence_body_included",
    ),
    (
        "openapi_evidence_links",
        "contracts/openapi/nex-ag.openapi.yaml",
        "/admin/v1/operator-review/cases/{case_id}/evidence-links",
    ),
    (
        "openapi_action_admission",
        "contracts/openapi/nex-ag.openapi.yaml",
        "/admin/v1/operator-review/cases/{case_id}/action-admission",
    ),
    (
        "postgres_opt_in",
        "scripts/smoke/run_ag_operator_review_case_evidence_admission_postgres_smoke.py",
        "NEX_AG_OPERATOR_REVIEW_CASE_EVIDENCE_ADMISSION_POSTGRES_SMOKE",
    ),
    (
        "postgres_case_table",
        "scripts/smoke/run_ag_operator_review_case_evidence_admission_postgres_smoke.py",
        "ag_op_cases",
    ),
    (
        "postgres_note_table",
        "scripts/smoke/run_ag_operator_review_case_evidence_admission_postgres_smoke.py",
        "ag_op_notes",
    ),
    (
        "postgres_export_table",
        "scripts/smoke/run_ag_operator_review_case_evidence_admission_postgres_smoke.py",
        "ag_ev_exports",
    ),
    (
        "privacy_forbidden_values",
        "scripts/smoke/run_ag_operator_review_case_evidence_admission_privacy_regression.py",
        "FORBIDDEN_VALUES",
    ),
    (
        "privacy_surface_count",
        "scripts/smoke/run_ag_operator_review_case_evidence_admission_privacy_regression.py",
        "surface_count",
    ),
    (
        "doc_index_0670",
        "docs/README.md",
        "Slice 0670",
    ),
)

REDACTION_SCAN_FILES = (
    "services/nex-ag/README.md",
    "docs/slices/0661_ag_operator_review_case_evidence_admission_boundary_audit.md",
    "docs/slices/0662_ag_operator_review_case_evidence_link_read_model.md",
    "docs/slices/0663_ag_operator_review_case_evidence_link_routes.md",
    "docs/slices/0664_ag_operator_review_case_action_admission_model.md",
    "docs/slices/0665_ag_operator_review_case_action_admission_routes.md",
    "docs/slices/0666_ag_operator_review_case_detail_evidence_admission_integration.md",
    "docs/slices/0667_ag_operator_review_case_evidence_admission_contract_openapi.md",
    "docs/slices/0668_ag_operator_review_case_evidence_admission_postgresql_smoke.md",
    "docs/slices/0669_ag_operator_review_case_evidence_admission_privacy_regression.md",
    "docs/slices/0670_s67_operator_review_case_evidence_admission_closure.md",
)


def run_s67_operator_review_case_evidence_admission_closure(
    root: Path = ROOT,
) -> dict[str, Any]:
    required_file_results = _required_file_results(root)
    token_results = _token_results(root)
    redaction_summary = _redaction_summary(root)
    table_lengths = {
        "ag_op_cases": len("ag_op_cases"),
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
        "slice_range": "0661-0670",
        "boundary": "ag_owned_operator_review_case_evidence_admission",
        "source_tables": table_lengths,
        "action_admission_policy": "preflight_only_authoritative_mutation_route",
        "evidence_payload_policy": "safe_refs_hashes_bounded_previews_only",
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
        for number in range(661, 671)
    )


def _experience_matrix(token_results: list[dict[str, Any]]) -> dict[str, bool]:
    present = {item["check_id"]: item["present"] for item in token_results}
    return {
        "boundary_audit": present.get("s67_boundary_quality_gate_hook", False),
        "evidence_link_routes": present.get("evidence_links_route", False)
        and present.get("evidence_links_schema_version", False),
        "action_admission_routes": present.get("action_admission_route", False)
        and present.get("action_admission_schema_version", False)
        and present.get("admission_preflight_only", False),
        "detail_integration": present.get("workbench_detail_route", False)
        and present.get("detail_evidence_summary", False),
        "persistence_sources": present.get("case_table_constant", False)
        and present.get("note_table_constant", False)
        and present.get("export_table_constant", False)
        and present.get("case_migration_table", False)
        and present.get("note_migration_table", False)
        and present.get("export_migration_table", False),
        "contracts_and_openapi": present.get("contract_evidence_links", False)
        and present.get("contract_action_admission", False)
        and present.get("contract_safe_redaction", False)
        and present.get("openapi_evidence_links", False)
        and present.get("openapi_action_admission", False),
        "postgres_smoke": present.get("s67_postgres_quality_gate_hook", False)
        and present.get("postgres_opt_in", False)
        and present.get("postgres_case_table", False)
        and present.get("postgres_note_table", False)
        and present.get("postgres_export_table", False),
        "privacy_regression": present.get("s67_privacy_quality_gate_hook", False)
        and present.get("privacy_forbidden_values", False)
        and present.get("privacy_surface_count", False),
        "closure_checkpoint": present.get("s67_closure_quality_gate_hook", False)
        and present.get("doc_index_0670", False),
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
            "RAW_OPERATOR_NOTE_SECRET_0669_SHOULD_NOT_LEAK" in text
        ),
        "raw_evidence_body_sentinel_included": (
            "RAW_EVIDENCE_BODY_SECRET_0669_SHOULD_NOT_LEAK" in text
        ),
        "raw_action_comment_sentinel_included": (
            "RAW_ACTION_SECRET_0669_SHOULD_NOT_LEAK" in text
        ),
        "raw_resolution_comment_sentinel_included": (
            "RAW_RESOLUTION_SECRET_0669_SHOULD_NOT_LEAK" in text
        ),
        "raw_prompt_sentinel_included": "RAW_PROMPT_SECRET_0669_SHOULD_NOT_LEAK" in text,
        "raw_idempotency_key_included": "idem-0669-secret-key" in text,
        "storage_path_included": (
            "/data/nex-platform/private/case-evidence-admission-0669.pdf" in text
        ),
        "postgres_smoke_documented": (
            "NEX_AG_OPERATOR_REVIEW_CASE_EVIDENCE_ADMISSION_POSTGRES_SMOKE=1" in text
            and "nex_ag_test" in text
        ),
        "privacy_regression_documented": (
            "privacy regression" in text.lower()
            and "forbidden_labels=11" in text
        ),
        "ag_owned_boundary_documented": (
            "ag_owned_operator_review_case_evidence_admission" in text
        ),
        "preflight_policy_documented": "preflight" in text.lower(),
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        return (
            "s67_operator_review_case_evidence_admission_closure=pass "
            f"slice_range={evidence['slice_range']} "
            f"required_files={evidence['required_file_count']} "
            f"boundary={evidence['boundary']} "
            "source_tables=ag_op_cases,ag_op_notes,ag_ev_exports "
            "smoke=test_db_evidence_admission privacy=route_surface_regression"
        )
    failed = ",".join(evidence.get("failed_checks", []))
    return (
        "s67_operator_review_case_evidence_admission_closure=fail "
        f"failed_checks={failed}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the S67 operator review case evidence/admission closure checkpoint."
        )
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_s67_operator_review_case_evidence_admission_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
