#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s35_remediation_observability_closure.v1"

REQUIRED_FILES = (
    "services/nex-ag/nex_ag/generation_remediation_boundary.py",
    "services/nex-ag/nex_ag/generation_remediation.py",
    "services/nex-ag/nex_ag/operations.py",
    "services/nex-ag/nex_ag/main.py",
    "scripts/smoke/run_ag_generation_remediation_postgres_smoke.py",
    "scripts/smoke/run_ag_generation_remediation_dashboard_postgres_smoke.py",
    "scripts/quality/run_quality_gate.sh",
    "contracts/openapi/nex-ag.openapi.yaml",
    "contracts/schemas/generation/ag_generation_remediation_action.v1.schema.json",
    "contracts/schemas/generation/ag_generation_remediation_task_detail.v1.schema.json",
    "contracts/examples/generation/ag_generation_remediation_action.citation_repair.json",
    "contracts/examples/generation/ag_generation_remediation_task_detail.waiting_on_cx.json",
    "tests/test_nex_ag_generation_remediation.py",
    "tests/test_nex_ag_operations.py",
    "tests/test_ag_generation_remediation_postgres_smoke.py",
    "tests/test_ag_generation_remediation_dashboard_postgres_smoke.py",
    "docs/slices/0341_generation_quality_repair_boundary_audit_refactoring_checkpoint.md",
    "docs/slices/0342_generation_remediation_action_contract_schema_foundation.md",
    "docs/slices/0343_ag_remediation_candidate_projection_rules.md",
    "docs/slices/0344_ag_remediation_task_api_repository_foundation.md",
    "docs/slices/0345_ag_generation_remediation_postgresql_smoke_evidence.md",
    "docs/slices/0346_ag_remediation_operations_dashboard_projection.md",
    "docs/slices/0347_ag_remediation_issue_candidate_runbook_projection.md",
    "docs/slices/0348_ag_remediation_detail_api_contract_hardening.md",
    "docs/slices/0349_ag_remediation_dashboard_postgresql_smoke_evidence.md",
    "docs/slices/0350_s35_remediation_observability_closure_checkpoint.md",
)

TOKEN_CHECKS = (
    (
        "remediation_boundary_transitions",
        "services/nex-ag/nex_ag/generation_remediation_boundary.py",
        "REMEDIATION_STATUS_TRANSITIONS",
    ),
    (
        "remediation_action_builder",
        "services/nex-ag/nex_ag/generation_remediation.py",
        "build_generation_remediation_action",
    ),
    (
        "remediation_sql_store",
        "services/nex-ag/nex_ag/generation_remediation.py",
        "SqlAlchemyGenerationRemediationTaskStore",
    ),
    (
        "remediation_task_routes",
        "services/nex-ag/nex_ag/generation_remediation.py",
        "register_generation_remediation_task_routes",
    ),
    (
        "remediation_detail_projection",
        "services/nex-ag/nex_ag/generation_remediation.py",
        "ag_generation_remediation_task_detail.v1",
    ),
    (
        "operations_dashboard_store_wiring",
        "services/nex-ag/nex_ag/operations.py",
        "generation_remediation_task_stores",
    ),
    (
        "operations_issue_candidate_rule",
        "services/nex-ag/nex_ag/operations.py",
        "generation_remediation_attention_required.v1",
    ),
    (
        "app_store_singleton_wiring",
        "services/nex-ag/nex_ag/main.py",
        "GENERATION_REMEDIATION_TASK_STORES",
    ),
    (
        "postgres_persistence_smoke_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_generation_remediation_postgres_smoke.py",
    ),
    (
        "postgres_dashboard_smoke_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_generation_remediation_dashboard_postgres_smoke.py",
    ),
    (
        "openapi_detail_contract",
        "contracts/openapi/nex-ag.openapi.yaml",
        "AgGenerationRemediationTaskDetail",
    ),
    (
        "dashboard_postgres_live_evidence_doc",
        "docs/slices/0349_ag_remediation_dashboard_postgresql_smoke_evidence.md",
        "ag_generation_remediation_dashboard_postgres_smoke=pass",
    ),
)


def run_s35_remediation_observability_closure(root: Path = ROOT) -> dict[str, Any]:
    missing_files = [
        relative_path
        for relative_path in REQUIRED_FILES
        if not (root / relative_path).is_file()
    ]
    token_results = [
        {
            "check_id": check_id,
            "path": relative_path,
            "present": token in _read_text(root / relative_path),
        }
        for check_id, relative_path, token in TOKEN_CHECKS
    ]
    checks = {
        "required_files_present": not missing_files,
        "token_checks_present": all(item["present"] for item in token_results),
        "slice_docs_contiguous": _slice_docs_contiguous(root),
    }
    status = "PASS" if all(checks.values()) else "FAIL"
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "status": status,
        "failure_code": None if status == "PASS" else "closure_checks_failed",
        "slice_range": "0341-0350",
        "required_file_count": len(REQUIRED_FILES),
        "missing_files": missing_files,
        "token_results": token_results,
        "checks": checks,
        "redaction_summary": {
            "database_url_included": False,
            "service_token_included": False,
            "raw_prompt_included": False,
            "raw_generation_output_included": False,
            "raw_source_document_text_included": False,
        },
    }


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        return (
            "s35_remediation_observability_closure=pass "
            f"slice_range={evidence['slice_range']} "
            f"required_files={evidence['required_file_count']}"
        )
    failed_checks = [
        key for key, value in evidence.get("checks", {}).items() if value is not True
    ]
    return (
        "s35_remediation_observability_closure=fail "
        f"reason={evidence.get('failure_code')} "
        f"checks={','.join(failed_checks)}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run S35 remediation observability closure checks."
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a short result line.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_s35_remediation_observability_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence))
    return 1 if evidence["status"] == "FAIL" else 0


def _slice_docs_contiguous(root: Path) -> bool:
    docs_dir = root / "docs" / "slices"
    return all(
        any(docs_dir.glob(f"{slice_id:04d}_*.md"))
        for slice_id in range(341, 351)
    )


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
