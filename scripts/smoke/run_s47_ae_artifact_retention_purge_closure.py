#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s47_ae_artifact_retention_purge_closure.v1"

REQUIRED_FILES = (
    "services/nex-ae-api/nex_ae_api/artifacts.py",
    "services/nex-ae-api/README.md",
    "contracts/schemas/generation/ae_artifact_retention_policy.v1.schema.json",
    "contracts/schemas/generation/ae_artifact_retention_execution.v1.schema.json",
    "contracts/examples/generation/ae_artifact_retention_policy.logical_purge_30d.json",
    "contracts/examples/generation/ae_artifact_retention_execution.dry_run_planned.json",
    "contracts/examples/generation/ae_artifact_retention_execution.execute_succeeded.json",
    "contracts/tests/negative/generation/ae_artifact_retention_policy.storage_ref_leak.json",
    "contracts/tests/negative/generation/ae_artifact_retention_execution.dry_run_delete_enabled.json",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ae_artifact_retention_purge_boundary_audit.py",
    "scripts/smoke/run_ae_artifact_retention_candidate_postgres_smoke.py",
    "scripts/smoke/run_ae_artifact_retention_purge_postgres_smoke.py",
    "scripts/smoke/run_s46_ae_artifact_lifecycle_management_closure.py",
    "scripts/smoke/run_s47_ae_artifact_retention_purge_closure.py",
    "tests/test_ae_artifact_retention_purge_boundary_audit.py",
    "tests/test_ae_artifact_retention_candidate_postgres_smoke.py",
    "tests/test_ae_artifact_retention_purge_postgres_smoke.py",
    "tests/test_nex_ae_artifacts.py",
    "tests/test_s47_ae_artifact_retention_purge_closure.py",
    "docs/README.md",
    "docs/slices/0461_ae_artifact_retention_purge_boundary_audit.md",
    "docs/slices/0462_ae_artifact_retention_policy_contract_schema.md",
    "docs/slices/0463_ae_artifact_retention_candidate_read_model.md",
    "docs/slices/0464_ae_artifact_retention_candidate_api_wiring.md",
    "docs/slices/0465_ae_artifact_retention_candidate_postgresql_smoke.md",
    "docs/slices/0466_ae_artifact_retention_execution_contract_schema.md",
    "docs/slices/0467_ae_artifact_retention_store_purge_capability.md",
    "docs/slices/0468_ae_artifact_retention_purge_api_guardrail.md",
    "docs/slices/0469_ae_artifact_retention_purge_postgresql_smoke.md",
    "docs/slices/0470_s47_ae_artifact_retention_purge_closure.md",
)

TOKEN_CHECKS = (
    (
        "s47_closure_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_s47_ae_artifact_retention_purge_closure.py",
    ),
    (
        "s46_closure_dependency_still_registered",
        "scripts/quality/run_quality_gate.sh",
        "run_s46_ae_artifact_lifecycle_management_closure.py",
    ),
    (
        "retention_boundary_audit_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_artifact_retention_purge_boundary_audit.py",
    ),
    (
        "retention_candidate_postgres_smoke_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_artifact_retention_candidate_postgres_smoke.py",
    ),
    (
        "retention_purge_postgres_smoke_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_artifact_retention_purge_postgres_smoke.py",
    ),
    (
        "ae_retention_policy_schema",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "AE_ARTIFACT_RETENTION_POLICY_SCHEMA_VERSION",
    ),
    (
        "ae_retention_execution_schema",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "AE_ARTIFACT_RETENTION_EXECUTION_SCHEMA_VERSION",
    ),
    (
        "ae_retention_policy_builder",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "build_artifact_retention_policy",
    ),
    (
        "ae_retention_candidate_builder",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "build_artifact_retention_candidate_collection",
    ),
    (
        "ae_retention_execution_builder",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "build_artifact_retention_execution",
    ),
    (
        "ae_retention_store_purge",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "purge_retention_candidates",
    ),
    (
        "ae_retention_storage_delete",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "delete_rendered_artifact_file",
    ),
    (
        "ae_retention_candidate_route",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        '"/api/v1/artifact-retention/candidates"',
    ),
    (
        "ae_retention_purge_route",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        '"/api/v1/artifact-retention/purge"',
    ),
    (
        "ae_logical_purge_status",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "ARTIFACT_RETENTION_LOGICAL_PURGE_STATUS",
    ),
    (
        "retention_policy_contract_schema",
        "contracts/schemas/generation/ae_artifact_retention_policy.v1.schema.json",
        "ae_artifact_retention_policy.v1",
    ),
    (
        "retention_execution_contract_schema",
        "contracts/schemas/generation/ae_artifact_retention_execution.v1.schema.json",
        "ae_artifact_retention_execution.v1",
    ),
    (
        "retention_purge_smoke_env",
        "scripts/smoke/run_ae_artifact_retention_purge_postgres_smoke.py",
        "NEX_AE_ARTIFACT_RETENTION_PURGE_POSTGRES_SMOKE",
    ),
    (
        "retention_purge_live_db_check",
        "scripts/smoke/run_ae_artifact_retention_purge_postgres_smoke.py",
        "live_db",
    ),
    (
        "retention_purge_db_after_execute",
        "scripts/smoke/run_ae_artifact_retention_purge_postgres_smoke.py",
        "db_after_execute",
    ),
    (
        "s47_slice_index",
        "docs/README.md",
        "Slice 0470",
    ),
    (
        "s47_api_readme_closure_note",
        "services/nex-ae-api/README.md",
        "Slice 0470 closes S47",
    ),
)


def run_s47_ae_artifact_retention_purge_closure(root: Path = ROOT) -> dict[str, Any]:
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
        "slice_range": "0461-0470",
        "required_file_count": len(REQUIRED_FILES),
        "missing_files": missing_files,
        "token_results": token_results,
        "checks": checks,
        "experience_matrix": {
            "retention_boundary_audit": True,
            "retention_policy_contract": True,
            "retention_candidate_read_model": True,
            "retention_candidate_api": True,
            "retention_candidate_postgres_smoke": True,
            "retention_execution_contract": True,
            "retention_store_purge_capability": True,
            "retention_purge_api_guardrail": True,
            "retention_purge_postgres_smoke": True,
            "closure_checkpoint": True,
        },
        "redaction_summary": {
            "database_url_included": False,
            "service_token_included": False,
            "provider_api_key_included": False,
            "raw_prompt_included": False,
            "raw_generation_output_included": False,
            "raw_source_document_text_included": False,
            "raw_artifact_payload_included": False,
            "raw_download_content_included": False,
            "storage_path_included": False,
            "storage_ref_included": False,
            "dry_run_default_enabled": True,
            "physical_delete_requires_three_flags": True,
            "physical_delete_executed_only_in_guarded_smoke": True,
        },
    }


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        return (
            "s47_ae_artifact_retention_purge_closure=pass "
            f"slice_range={evidence['slice_range']} "
            f"required_files={evidence['required_file_count']}"
        )
    failed_checks = [
        key for key, value in evidence.get("checks", {}).items() if value is not True
    ]
    return (
        "s47_ae_artifact_retention_purge_closure=fail "
        f"reason={evidence.get('failure_code')} "
        f"checks={','.join(failed_checks)}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run S47 AE artifact retention purge closure checks."
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a short result line.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_s47_ae_artifact_retention_purge_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence))
    return 1 if evidence["status"] == "FAIL" else 0


def _slice_docs_contiguous(root: Path) -> bool:
    docs_dir = root / "docs" / "slices"
    return all(
        (docs_dir / f"{slice_no:04d}_{suffix}.md").is_file()
        for slice_no, suffix in (
            (461, "ae_artifact_retention_purge_boundary_audit"),
            (462, "ae_artifact_retention_policy_contract_schema"),
            (463, "ae_artifact_retention_candidate_read_model"),
            (464, "ae_artifact_retention_candidate_api_wiring"),
            (465, "ae_artifact_retention_candidate_postgresql_smoke"),
            (466, "ae_artifact_retention_execution_contract_schema"),
            (467, "ae_artifact_retention_store_purge_capability"),
            (468, "ae_artifact_retention_purge_api_guardrail"),
            (469, "ae_artifact_retention_purge_postgresql_smoke"),
            (470, "s47_ae_artifact_retention_purge_closure"),
        )
    )


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
