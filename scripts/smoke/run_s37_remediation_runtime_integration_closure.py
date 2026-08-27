#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s37_remediation_runtime_integration_closure.v1"

REQUIRED_FILES = (
    "services/nex-cx/nex_cx/remediation_execution.py",
    "services/nex-cx/nex_cx/remediation_execution_worker.py",
    "services/nex-ag/nex_ag/generation_remediation_execution.py",
    "services/nex-ag/nex_ag/generation_remediation_handoff.py",
    "contracts/openapi/nex-cx.openapi.yaml",
    "contracts/openapi/nex-ag.openapi.yaml",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_cx_remediation_execution_postgres_smoke.py",
    "scripts/smoke/run_ag_remediation_execution_dispatch_postgres_smoke.py",
    "scripts/smoke/run_cx_remediation_execution_read_model_postgres_smoke.py",
    "scripts/smoke/run_ag_remediation_execution_status_sync_postgres_smoke.py",
    "scripts/smoke/run_postgres_test_smoke_suite.py",
    "scripts/smoke/run_s37_remediation_runtime_integration_closure.py",
    "tests/test_cx_remediation_execution_postgres_smoke.py",
    "tests/test_ag_remediation_execution_dispatch_postgres_smoke.py",
    "tests/test_cx_remediation_execution_read_model_postgres_smoke.py",
    "tests/test_ag_remediation_execution_status_sync_postgres_smoke.py",
    "tests/test_nex_cx_remediation_execution.py",
    "tests/test_nex_ag_generation_remediation_execution.py",
    "tests/test_nex_ag_generation_remediation_handoff.py",
    "tests/test_s37_remediation_runtime_integration_closure.py",
    "docs/slices/0361_cx_remediation_execution_postgresql_smoke_evidence.md",
    "docs/slices/0362_ag_remediation_execution_handoff_state_planner.md",
    "docs/slices/0363_ag_remediation_execution_dispatch_service.md",
    "docs/slices/0364_ag_remediation_execution_dispatch_api.md",
    "docs/slices/0365_ag_remediation_execution_dispatch_postgresql_smoke.md",
    "docs/slices/0366_cx_remediation_execution_read_model_api_foundation.md",
    "docs/slices/0367_cx_remediation_execution_read_model_postgresql_smoke.md",
    "docs/slices/0368_ag_remediation_execution_status_sync_client_facade.md",
    "docs/slices/0369_ag_remediation_execution_status_sync_api_evidence.md",
    "docs/slices/0370_s37_remediation_runtime_integration_closure.md",
)

TOKEN_CHECKS = (
    (
        "cx_execution_postgres_smoke_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_cx_remediation_execution_postgres_smoke.py",
    ),
    (
        "cx_read_model_postgres_smoke_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_cx_remediation_execution_read_model_postgres_smoke.py",
    ),
    (
        "ag_dispatch_postgres_smoke_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_remediation_execution_dispatch_postgres_smoke.py",
    ),
    (
        "ag_status_sync_postgres_smoke_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_remediation_execution_status_sync_postgres_smoke.py",
    ),
    (
        "s37_closure_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_s37_remediation_runtime_integration_closure.py",
    ),
    (
        "postgres_suite_status_sync_stage",
        "scripts/smoke/run_postgres_test_smoke_suite.py",
        "ag_remediation_execution_status_sync_postgres",
    ),
    (
        "cx_remediation_execution_route_contract",
        "contracts/openapi/nex-cx.openapi.yaml",
        "/api/v1/generations/{cx_generation_id}/remediation-executions",
    ),
    (
        "cx_remediation_execution_detail_schema",
        "services/nex-cx/nex_cx/remediation_execution.py",
        "CX_REMEDIATION_EXECUTION_DETAIL_SCHEMA_VERSION",
    ),
    (
        "cx_remediation_execution_job_admission",
        "services/nex-cx/nex_cx/remediation_execution.py",
        "enqueue_remediation_execution_job",
    ),
    (
        "cx_remediation_worker_batch_runtime",
        "services/nex-cx/nex_cx/remediation_execution_worker.py",
        "run_cx_remediation_execution_worker_batch",
    ),
    (
        "ag_dispatch_route_contract",
        "contracts/openapi/nex-ag.openapi.yaml",
        "executeAgGenerationRemediationTask",
    ),
    (
        "ag_status_sync_route_contract",
        "contracts/openapi/nex-ag.openapi.yaml",
        "syncAgGenerationRemediationExecutionStatus",
    ),
    (
        "ag_status_sync_schema",
        "services/nex-ag/nex_ag/generation_remediation_execution.py",
        "AG_REMEDIATION_EXECUTION_STATUS_SYNC_SCHEMA_VERSION",
    ),
    (
        "ag_cx_execution_detail_client",
        "services/nex-ag/nex_ag/generation_remediation_handoff.py",
        "get_remediation_execution_detail",
    ),
    (
        "status_sync_live_postgres_evidence_doc",
        "docs/slices/0369_ag_remediation_execution_status_sync_api_evidence.md",
        "ag_remediation_execution_status_sync_postgres_smoke=pass",
    ),
)


def run_s37_remediation_runtime_integration_closure(
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
        "slice_range": "0361-0370",
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
            "s37_remediation_runtime_integration_closure=pass "
            f"slice_range={evidence['slice_range']} "
            f"required_files={evidence['required_file_count']}"
        )
    failed_checks = [
        key for key, value in evidence.get("checks", {}).items() if value is not True
    ]
    return (
        "s37_remediation_runtime_integration_closure=fail "
        f"reason={evidence.get('failure_code')} "
        f"checks={','.join(failed_checks)}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run S37 remediation runtime integration closure checks."
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a short result line.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_s37_remediation_runtime_integration_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence))
    return 1 if evidence["status"] == "FAIL" else 0


def _slice_docs_contiguous(root: Path) -> bool:
    docs_dir = root / "docs" / "slices"
    return all(
        any(docs_dir.glob(f"{slice_id:04d}_*.md"))
        for slice_id in range(361, 371)
    )


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
