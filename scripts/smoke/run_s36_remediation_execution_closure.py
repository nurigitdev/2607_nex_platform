#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s36_remediation_execution_closure.v1"

REQUIRED_FILES = (
    "services/nex-cx/nex_cx/remediation_execution_boundary.py",
    "services/nex-cx/nex_cx/remediation_execution.py",
    "services/nex-cx/nex_cx/remediation_execution_planning.py",
    "services/nex-cx/nex_cx/remediation_execution_worker.py",
    "services/nex-ag/nex_ag/generation_remediation_handoff.py",
    "services/nex-cx/nex_cx/main.py",
    "contracts/openapi/nex-cx.openapi.yaml",
    "contracts/schemas/generation/cx_remediation_execution_request.v1.schema.json",
    "contracts/schemas/generation/cx_remediation_execution_result.v1.schema.json",
    "contracts/examples/generation/cx_remediation_execution_request.citation_repair.json",
    "contracts/examples/generation/cx_remediation_execution_result.succeeded.json",
    "contracts/tests/negative/generation/cx_remediation_execution_request.raw_prompt_leak.json",
    "contracts/tests/negative/generation/cx_remediation_execution_result.provider_endpoint_leak.json",
    "database/nex-cx/migrations/0355_cx_repair_attempt_lineage_persistence_foundation.sql",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_s36_remediation_execution_closure.py",
    "tests/test_nex_cx_remediation_execution_boundary.py",
    "tests/test_contract_validation.py",
    "tests/test_nex_ag_generation_remediation_handoff.py",
    "tests/test_nex_cx_remediation_execution.py",
    "tests/test_nex_cx_remediation_execution_planning.py",
    "tests/test_nex_cx_remediation_execution_worker.py",
    "tests/test_s36_remediation_execution_closure.py",
    "docs/slices/0351_cx_remediation_execution_boundary_audit_refactoring_checkpoint.md",
    "docs/slices/0352_cx_remediation_execution_contract_schema_foundation.md",
    "docs/slices/0353_ag_to_cx_remediation_handoff_client_foundation.md",
    "docs/slices/0354_cx_remediation_execution_service_api_foundation.md",
    "docs/slices/0355_cx_repair_attempt_lineage_persistence_foundation.md",
    "docs/slices/0356_cx_remediation_execution_worker_planning_state_machine.md",
    "docs/slices/0357_cx_remediation_execution_job_admission_wiring.md",
    "docs/slices/0358_cx_remediation_execution_worker_mock_pipeline.md",
    "docs/slices/0359_cx_remediation_execution_runner_integration.md",
    "docs/slices/0360_s36_remediation_execution_closure_checkpoint.md",
)

TOKEN_CHECKS = (
    (
        "cx_boundary_executable_actions",
        "services/nex-cx/nex_cx/remediation_execution_boundary.py",
        "CX_EXECUTABLE_REMEDIATION_ACTION_TYPES",
    ),
    (
        "cx_request_schema",
        "contracts/schemas/generation/cx_remediation_execution_request.v1.schema.json",
        "cx_remediation_execution_request.v1",
    ),
    (
        "cx_result_schema",
        "contracts/schemas/generation/cx_remediation_execution_result.v1.schema.json",
        "cx_remediation_execution_result.v1",
    ),
    (
        "ag_to_cx_handoff_client",
        "services/nex-ag/nex_ag/generation_remediation_handoff.py",
        "HttpCxRemediationExecutionClient",
    ),
    (
        "cx_service_api_route",
        "services/nex-cx/nex_cx/remediation_execution.py",
        "/api/v1/generations/{cx_generation_id}/remediation-executions",
    ),
    (
        "cx_lineage_sql_store",
        "services/nex-cx/nex_cx/remediation_execution.py",
        "SqlAlchemyRemediationExecutionStore",
    ),
    (
        "cx_job_admission",
        "services/nex-cx/nex_cx/remediation_execution.py",
        "CX_REMEDIATION_EXECUTION_JOB_TYPE",
    ),
    (
        "cx_worker_state_machine",
        "services/nex-cx/nex_cx/remediation_execution_planning.py",
        "CX_REMEDIATION_EXECUTION_STATUS_TRANSITIONS",
    ),
    (
        "cx_worker_mock_pipeline",
        "services/nex-cx/nex_cx/remediation_execution_worker.py",
        "build_mock_repair_generation_record",
    ),
    (
        "cx_worker_runner_batch",
        "services/nex-cx/nex_cx/remediation_execution_worker.py",
        "run_cx_remediation_execution_worker_batch",
    ),
    (
        "cx_main_job_queue_wiring",
        "services/nex-cx/nex_cx/main.py",
        "job_queue=SERVICE_PERSISTENCE.job_queue",
    ),
    (
        "quality_gate_closure_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_s36_remediation_execution_closure.py",
    ),
)


def run_s36_remediation_execution_closure(root: Path = ROOT) -> dict[str, Any]:
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
        "slice_range": "0351-0360",
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
        },
    }


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        return (
            "s36_remediation_execution_closure=pass "
            f"slice_range={evidence['slice_range']} "
            f"required_files={evidence['required_file_count']}"
        )
    failed_checks = [
        key for key, value in evidence.get("checks", {}).items() if value is not True
    ]
    return (
        "s36_remediation_execution_closure=fail "
        f"reason={evidence.get('failure_code')} "
        f"checks={','.join(failed_checks)}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run S36 remediation execution closure checks."
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a short result line.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_s36_remediation_execution_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence))
    return 1 if evidence["status"] == "FAIL" else 0


def _slice_docs_contiguous(root: Path) -> bool:
    docs_dir = root / "docs" / "slices"
    return all(
        any(docs_dir.glob(f"{slice_id:04d}_*.md"))
        for slice_id in range(351, 361)
    )


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
