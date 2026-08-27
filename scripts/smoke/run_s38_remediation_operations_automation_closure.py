#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s38_remediation_operations_automation_closure.v1"

REQUIRED_FILES = (
    "services/nex-ag/nex_ag/remediation_runtime_audit.py",
    "services/nex-ag/nex_ag/remediation_execution_operations.py",
    "services/nex-ag/nex_ag/operations.py",
    "services/nex-ag/nex_ag/main.py",
    "services/nex-ag/nex_ag/remediation_execution_status_sync_jobs.py",
    "services/nex-ag/nex_ag/remediation_execution_status_sync_worker.py",
    "services/nex-cx/nex_cx/remediation_execution.py",
    "services/nex-ae-api/nex_ae_api/repaired_responses.py",
    "contracts/openapi/nex-ag.openapi.yaml",
    "contracts/openapi/nex-cx.openapi.yaml",
    "contracts/openapi/nex-ae-api.openapi.yaml",
    "contracts/schemas/service/nex_ag/operations_projection.v1.schema.json",
    "contracts/schemas/service/nex_ae_api/repaired_response_handoff.v1.schema.json",
    "contracts/examples/generation/ae_repaired_response_handoff.ready_for_review.json",
    "contracts/tests/negative/generation/ae_repaired_response_handoff.raw_output_field.json",
    "contracts/tests/negative/index.json",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ag_remediation_execution_status_sync_worker_postgres_smoke.py",
    "scripts/smoke/run_postgres_test_smoke_suite.py",
    "scripts/smoke/run_s38_remediation_operations_automation_closure.py",
    "tests/test_nex_ag_remediation_runtime_audit.py",
    "tests/test_nex_ag_remediation_execution_operations.py",
    "tests/test_nex_ag_operations.py",
    "tests/test_nex_ag_remediation_execution_status_sync_jobs.py",
    "tests/test_nex_ag_remediation_execution_status_sync_worker.py",
    "tests/test_ag_remediation_execution_status_sync_worker_postgres_smoke.py",
    "tests/test_nex_cx_remediation_execution.py",
    "tests/test_nex_ae_repaired_responses.py",
    "tests/test_contract_validation.py",
    "tests/test_s38_remediation_operations_automation_closure.py",
    "docs/README.md",
    "docs/slices/0371_remediation_runtime_operations_gap_audit.md",
    "docs/slices/0372_ag_remediation_execution_operations_projection_foundation.md",
    "docs/slices/0373_ag_remediation_execution_operations_api_wiring.md",
    "docs/slices/0374_ag_remediation_execution_dashboard_issue_candidate_integration.md",
    "docs/slices/0375_ag_remediation_execution_status_sync_job_planning_foundation.md",
    "docs/slices/0376_ag_remediation_execution_status_sync_worker_mock_runtime.md",
    "docs/slices/0377_ag_remediation_execution_status_sync_postgresql_smoke_evidence.md",
    "docs/slices/0378_cx_repaired_generation_lineage_read_model_hardening.md",
    "docs/slices/0379_ae_repaired_response_handoff_contract_foundation.md",
    "docs/slices/0380_s38_remediation_operations_automation_closure.md",
)

TOKEN_CHECKS = (
    (
        "s38_closure_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_s38_remediation_operations_automation_closure.py",
    ),
    (
        "s37_closure_dependency_still_registered",
        "scripts/quality/run_quality_gate.sh",
        "run_s37_remediation_runtime_integration_closure.py",
    ),
    (
        "status_sync_worker_postgres_smoke_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_remediation_execution_status_sync_worker_postgres_smoke.py",
    ),
    (
        "postgres_suite_worker_stage",
        "scripts/smoke/run_postgres_test_smoke_suite.py",
        "ag_remediation_execution_status_sync_worker_postgres",
    ),
    (
        "s38_gap_audit_schema",
        "services/nex-ag/nex_ag/remediation_runtime_audit.py",
        "ag_remediation_runtime_operations_gap_audit.v1",
    ),
    (
        "ag_remediation_execution_operations_projection",
        "services/nex-ag/nex_ag/remediation_execution_operations.py",
        "AG_REMEDIATION_EXECUTION_OPERATIONS_PROJECTION_SCHEMA_VERSION",
    ),
    (
        "ag_remediation_execution_operations_openapi",
        "contracts/openapi/nex-ag.openapi.yaml",
        "getAgRemediationExecutionOperationsProjection",
    ),
    (
        "ag_dashboard_remediation_execution_section",
        "services/nex-ag/nex_ag/operations.py",
        "remediation_executions",
    ),
    (
        "ag_dashboard_issue_candidate_rule",
        "services/nex-ag/nex_ag/operations.py",
        "remediation_execution_attention_required.v1",
    ),
    (
        "ag_status_sync_job_plan_schema",
        "services/nex-ag/nex_ag/remediation_execution_status_sync_jobs.py",
        "AG_REMEDIATION_EXECUTION_STATUS_SYNC_JOB_PLAN_SCHEMA_VERSION",
    ),
    (
        "ag_status_sync_worker_runtime",
        "services/nex-ag/nex_ag/remediation_execution_status_sync_worker.py",
        "run_remediation_execution_status_sync_worker_once",
    ),
    (
        "ag_status_sync_worker_result_schema",
        "services/nex-ag/nex_ag/remediation_execution_status_sync_worker.py",
        "AG_REMEDIATION_EXECUTION_STATUS_SYNC_WORKER_RESULT_SCHEMA_VERSION",
    ),
    (
        "cx_repaired_generation_lineage_builder",
        "services/nex-cx/nex_cx/remediation_execution.py",
        "build_cx_repaired_generation_lineage",
    ),
    (
        "cx_repaired_generation_lineage_openapi",
        "contracts/openapi/nex-cx.openapi.yaml",
        "cx_repaired_generation_lineage.v1",
    ),
    (
        "ae_repaired_response_handoff_contract",
        "services/nex-ae-api/nex_ae_api/repaired_responses.py",
        "AE_REPAIRED_RESPONSE_HANDOFF_SCHEMA_VERSION",
    ),
    (
        "ae_repaired_response_handoff_openapi",
        "contracts/openapi/nex-ae-api.openapi.yaml",
        "createAeRepairedResponseHandoff",
    ),
    (
        "ae_repaired_response_handoff_negative_fixture",
        "contracts/tests/negative/index.json",
        "ae_repaired_response_handoff_raw_output_field",
    ),
    (
        "s38_slice_index",
        "docs/README.md",
        "Slice 0380",
    ),
)


def run_s38_remediation_operations_automation_closure(
    root: Path = ROOT,
) -> dict[str, Any]:
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
        "slice_range": "0371-0380",
        "required_file_count": len(REQUIRED_FILES),
        "missing_files": missing_files,
        "token_results": token_results,
        "checks": checks,
        "redaction_summary": {
            "database_url_included": False,
            "service_token_included": False,
            "provider_api_key_included": False,
            "raw_prompt_included": False,
            "raw_generation_output_included": False,
            "raw_source_document_text_included": False,
            "raw_evidence_included": False,
            "storage_path_included": False,
        },
    }


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        return (
            "s38_remediation_operations_automation_closure=pass "
            f"slice_range={evidence['slice_range']} "
            f"required_files={evidence['required_file_count']}"
        )
    failed_checks = [
        key for key, value in evidence.get("checks", {}).items() if value is not True
    ]
    return (
        "s38_remediation_operations_automation_closure=fail "
        f"reason={evidence.get('failure_code')} "
        f"checks={','.join(failed_checks)}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run S38 remediation operations automation closure checks."
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a short result line.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_s38_remediation_operations_automation_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence))
    return 1 if evidence["status"] == "FAIL" else 0


def _slice_docs_contiguous(root: Path) -> bool:
    docs_dir = root / "docs" / "slices"
    return all(
        any(docs_dir.glob(f"{slice_id:04d}_*.md"))
        for slice_id in range(371, 381)
    )


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
