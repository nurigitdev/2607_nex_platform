#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s46_ae_artifact_lifecycle_management_closure.v1"

REQUIRED_FILES = (
    "services/nex-ae-api/nex_ae_api/artifacts.py",
    "services/nex-ae-api/README.md",
    "services/nex-ag/nex_ag/artifact_operations.py",
    "services/nex-ag/README.md",
    "apps/nex-ae-web/src/main.js",
    "apps/nex-ae-web/src/artifactClient.js",
    "apps/nex-ae-web/src/artifactLifecycleActionState.js",
    "apps/nex-ae-web/scripts/runArtifactLifecyclePlaywrightSmoke.mjs",
    "apps/nex-ae-web/package.json",
    "apps/nex-ae-web/README.md",
    "apps/nex-ae-web/test/artifactClient.test.mjs",
    "apps/nex-ae-web/test/artifactLifecycleActionState.test.mjs",
    "apps/nex-ae-web/test/artifactLifecycleUxWiring.test.mjs",
    "apps/nex-ae-web/test/artifactLifecyclePlaywrightSmoke.test.mjs",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ae_artifact_lifecycle_boundary_audit.py",
    "scripts/smoke/run_ae_artifact_lifecycle_postgres_smoke.py",
    "scripts/smoke/run_ae_web_artifact_lifecycle_playwright_postgres_smoke.py",
    "scripts/smoke/run_s45_ae_artifact_library_management_closure.py",
    "scripts/smoke/run_s46_ae_artifact_lifecycle_management_closure.py",
    "tests/test_ae_artifact_lifecycle_boundary_audit.py",
    "tests/test_ae_artifact_lifecycle_postgres_smoke.py",
    "tests/test_ae_web_artifact_lifecycle_playwright_postgres_smoke.py",
    "tests/test_nex_ae_artifacts.py",
    "tests/test_nex_ag_artifact_operations.py",
    "tests/test_s46_ae_artifact_lifecycle_management_closure.py",
    "docs/README.md",
    "docs/slices/0451_ae_artifact_lifecycle_boundary_audit.md",
    "docs/slices/0452_ae_artifact_lifecycle_command_contract_schema.md",
    "docs/slices/0453_ae_artifact_lifecycle_repository_api_wiring.md",
    "docs/slices/0454_ae_artifact_lifecycle_postgresql_smoke_evidence.md",
    "docs/slices/0455_ae_web_artifact_lifecycle_client_adapter.md",
    "docs/slices/0456_ae_web_artifact_lifecycle_action_state.md",
    "docs/slices/0457_ae_web_artifact_lifecycle_ux_wiring.md",
    "docs/slices/0458_ae_web_artifact_lifecycle_playwright_postgresql_smoke.md",
    "docs/slices/0459_ag_artifact_lifecycle_operations_projection.md",
    "docs/slices/0460_s46_ae_artifact_lifecycle_management_closure.md",
)

TOKEN_CHECKS = (
    (
        "s46_closure_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_s46_ae_artifact_lifecycle_management_closure.py",
    ),
    (
        "s45_closure_dependency_still_registered",
        "scripts/quality/run_quality_gate.sh",
        "run_s45_ae_artifact_library_management_closure.py",
    ),
    (
        "lifecycle_boundary_audit_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_artifact_lifecycle_boundary_audit.py",
    ),
    (
        "lifecycle_postgres_smoke_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_artifact_lifecycle_postgres_smoke.py",
    ),
    (
        "web_lifecycle_playwright_postgres_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_web_artifact_lifecycle_playwright_postgres_smoke.py",
    ),
    (
        "ae_lifecycle_action_schema",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "AE_ARTIFACT_LIFECYCLE_ACTION_SCHEMA_VERSION",
    ),
    (
        "ae_lifecycle_action_result_schema",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "AE_ARTIFACT_LIFECYCLE_ACTION_RESULT_SCHEMA_VERSION",
    ),
    (
        "ae_lifecycle_action_builder",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "build_artifact_lifecycle_action_request",
    ),
    (
        "ae_lifecycle_result_builder",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "build_artifact_lifecycle_action_result",
    ),
    (
        "ae_lifecycle_store_apply",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "apply_lifecycle_action",
    ),
    (
        "ae_lifecycle_route",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        '"/api/v1/artifacts/{artifact_id}/lifecycle-actions"',
    ),
    (
        "web_lifecycle_client_submit",
        "apps/nex-ae-web/src/artifactClient.js",
        "submitArtifactLifecycleAction",
    ),
    (
        "web_lifecycle_action_state_schema",
        "apps/nex-ae-web/src/artifactLifecycleActionState.js",
        "AE_WEB_ARTIFACT_LIFECYCLE_ACTION_STATE_SCHEMA_VERSION",
    ),
    (
        "web_lifecycle_action_set_schema",
        "apps/nex-ae-web/src/artifactLifecycleActionState.js",
        "AE_WEB_ARTIFACT_LIFECYCLE_ACTION_SET_SCHEMA_VERSION",
    ),
    (
        "web_lifecycle_main_operation",
        "apps/nex-ae-web/src/main.js",
        "artifact_lifecycle",
    ),
    (
        "web_lifecycle_dom_action_anchor",
        "apps/nex-ae-web/src/main.js",
        "data-artifact-lifecycle-action",
    ),
    (
        "web_lifecycle_playwright_runner",
        "apps/nex-ae-web/scripts/runArtifactLifecyclePlaywrightSmoke.mjs",
        "runArtifactLifecyclePlaywrightSmoke",
    ),
    (
        "ag_lifecycle_projection_schema",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "AG_ARTIFACT_OPERATION_LIFECYCLE_PROJECTION_SCHEMA_VERSION",
    ),
    (
        "ag_lifecycle_route",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"/admin/v1/operations/artifacts/{artifact_id}/lifecycle"',
    ),
    (
        "ag_lifecycle_projection_builder",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "build_artifact_operation_lifecycle_projection",
    ),
    (
        "ag_lifecycle_summary",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "summarize_artifact_operation_lifecycle",
    ),
    (
        "s46_slice_index",
        "docs/README.md",
        "Slice 0460",
    ),
    (
        "s46_web_readme_closure_note",
        "apps/nex-ae-web/README.md",
        "Slice 0460 closes S46",
    ),
    (
        "s46_api_readme_closure_note",
        "services/nex-ae-api/README.md",
        "Slice 0460 closes S46",
    ),
    (
        "s46_ag_readme_closure_note",
        "services/nex-ag/README.md",
        "Slice 0460 closes S46",
    ),
)


def run_s46_ae_artifact_lifecycle_management_closure(
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
        "slice_range": "0451-0460",
        "required_file_count": len(REQUIRED_FILES),
        "missing_files": missing_files,
        "token_results": token_results,
        "checks": checks,
        "experience_matrix": {
            "artifact_lifecycle_boundary_audit": True,
            "ae_lifecycle_command_contract": True,
            "ae_lifecycle_repository_api": True,
            "ae_lifecycle_postgres_smoke": True,
            "web_lifecycle_client_adapter": True,
            "web_lifecycle_action_state": True,
            "web_lifecycle_ux_wiring": True,
            "web_lifecycle_playwright_postgres_smoke": True,
            "ag_lifecycle_operations_projection": True,
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
            "raw_lifecycle_comment_included": False,
            "browser_secret_header_included": False,
            "storage_path_included": False,
            "storage_ref_included": False,
            "physical_delete_executed": False,
        },
    }


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        return (
            "s46_ae_artifact_lifecycle_management_closure=pass "
            f"slice_range={evidence['slice_range']} "
            f"required_files={evidence['required_file_count']}"
        )
    failed_checks = [
        key for key, value in evidence.get("checks", {}).items() if value is not True
    ]
    return (
        "s46_ae_artifact_lifecycle_management_closure=fail "
        f"reason={evidence.get('failure_code')} "
        f"checks={','.join(failed_checks)}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run S46 AE artifact lifecycle management closure checks."
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a short result line.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_s46_ae_artifact_lifecycle_management_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence))
    return 1 if evidence["status"] == "FAIL" else 0


def _slice_docs_contiguous(root: Path) -> bool:
    docs_dir = root / "docs" / "slices"
    return all(
        (docs_dir / f"{slice_no:04d}_{suffix}.md").is_file()
        for slice_no, suffix in (
            (451, "ae_artifact_lifecycle_boundary_audit"),
            (452, "ae_artifact_lifecycle_command_contract_schema"),
            (453, "ae_artifact_lifecycle_repository_api_wiring"),
            (454, "ae_artifact_lifecycle_postgresql_smoke_evidence"),
            (455, "ae_web_artifact_lifecycle_client_adapter"),
            (456, "ae_web_artifact_lifecycle_action_state"),
            (457, "ae_web_artifact_lifecycle_ux_wiring"),
            (458, "ae_web_artifact_lifecycle_playwright_postgresql_smoke"),
            (459, "ag_artifact_lifecycle_operations_projection"),
            (460, "s46_ae_artifact_lifecycle_management_closure"),
        )
    )


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
