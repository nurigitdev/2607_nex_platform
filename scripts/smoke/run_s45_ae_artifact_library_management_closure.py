#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s45_ae_artifact_library_management_closure.v1"

REQUIRED_FILES = (
    "services/nex-ae-api/nex_ae_api/artifacts.py",
    "services/nex-ae-api/README.md",
    "services/nex-ag/nex_ag/artifact_operations.py",
    "services/nex-ag/README.md",
    "apps/nex-ae-web/index.html",
    "apps/nex-ae-web/src/main.js",
    "apps/nex-ae-web/src/artifactClient.js",
    "apps/nex-ae-web/src/artifactLibraryPanel.js",
    "apps/nex-ae-web/src/artifactMockRecord.js",
    "apps/nex-ae-web/scripts/runArtifactLibraryPlaywrightSmoke.mjs",
    "apps/nex-ae-web/package.json",
    "apps/nex-ae-web/README.md",
    "apps/nex-ae-web/test/artifactClient.test.mjs",
    "apps/nex-ae-web/test/artifactLibraryPanel.test.mjs",
    "apps/nex-ae-web/test/artifactLibraryWiring.test.mjs",
    "apps/nex-ae-web/test/artifactLibraryPlaywrightSmoke.test.mjs",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ae_artifact_library_management_boundary_audit.py",
    "scripts/smoke/run_ae_artifact_collection_postgres_smoke.py",
    "scripts/smoke/run_ae_web_artifact_library_playwright_postgres_smoke.py",
    "scripts/smoke/run_s44_ae_web_artifact_delivery_closure.py",
    "scripts/smoke/run_s45_ae_artifact_library_management_closure.py",
    "tests/test_ae_artifact_library_management_boundary_audit.py",
    "tests/test_ae_artifact_collection_postgres_smoke.py",
    "tests/test_ae_web_artifact_library_playwright_postgres_smoke.py",
    "tests/test_nex_ae_artifacts.py",
    "tests/test_nex_ae_web_static.py",
    "tests/test_nex_ag_artifact_operations.py",
    "tests/test_s45_ae_artifact_library_management_closure.py",
    "docs/README.md",
    "docs/slices/0441_ae_artifact_library_management_boundary_audit.md",
    "docs/slices/0442_ae_artifact_collection_read_model_foundation.md",
    "docs/slices/0443_ae_artifact_collection_api_wiring.md",
    "docs/slices/0444_ae_artifact_collection_postgresql_smoke_evidence.md",
    "docs/slices/0445_ae_web_artifact_collection_client_adapter.md",
    "docs/slices/0446_ae_web_artifact_library_panel_read_model.md",
    "docs/slices/0447_ae_web_artifact_library_ux_wiring.md",
    "docs/slices/0448_ae_web_artifact_library_playwright_postgresql_smoke.md",
    "docs/slices/0449_ag_artifact_collection_operations_projection.md",
    "docs/slices/0450_s45_ae_artifact_library_management_closure.md",
)

TOKEN_CHECKS = (
    (
        "s45_closure_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_s45_ae_artifact_library_management_closure.py",
    ),
    (
        "s44_closure_dependency_still_registered",
        "scripts/quality/run_quality_gate.sh",
        "run_s44_ae_web_artifact_delivery_closure.py",
    ),
    (
        "library_boundary_audit_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_artifact_library_management_boundary_audit.py",
    ),
    (
        "collection_postgres_smoke_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_artifact_collection_postgres_smoke.py",
    ),
    (
        "web_library_playwright_postgres_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_web_artifact_library_playwright_postgres_smoke.py",
    ),
    (
        "ae_collection_schema",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "ARTIFACT_COLLECTION_SCHEMA_VERSION",
    ),
    (
        "ae_collection_item_builder",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "build_artifact_collection_item",
    ),
    (
        "ae_collection_owner_scope",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "owner_user_id",
    ),
    (
        "ae_collection_route",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        '@app.get("/api/v1/artifacts"',
    ),
    (
        "web_collection_client",
        "apps/nex-ae-web/src/artifactClient.js",
        "listArtifacts",
    ),
    (
        "web_library_panel_schema",
        "apps/nex-ae-web/src/artifactLibraryPanel.js",
        "AE_WEB_ARTIFACT_LIBRARY_PANEL_SCHEMA_VERSION",
    ),
    (
        "web_library_renderer",
        "apps/nex-ae-web/src/artifactLibraryPanel.js",
        "renderArtifactLibraryPanel",
    ),
    (
        "web_library_main_state",
        "apps/nex-ae-web/src/main.js",
        "artifactLibraryPanel",
    ),
    (
        "web_library_dom_anchor",
        "apps/nex-ae-web/index.html",
        "artifact-library-list",
    ),
    (
        "web_library_playwright_runner",
        "apps/nex-ae-web/scripts/runArtifactLibraryPlaywrightSmoke.mjs",
        "runArtifactLibraryPlaywrightSmoke",
    ),
    (
        "ag_collection_projection_schema",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "AG_ARTIFACT_OPERATION_COLLECTION_PROJECTION_SCHEMA_VERSION",
    ),
    (
        "ag_collection_route",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '@app.get("/admin/v1/operations/artifacts"',
    ),
    (
        "ag_collection_client_method",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "def list_artifacts",
    ),
    (
        "ag_collection_projection_builder",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "build_artifact_operation_collection_projection",
    ),
    (
        "ag_collection_summary",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "summarize_artifact_operation_collection",
    ),
    (
        "s45_slice_index",
        "docs/README.md",
        "Slice 0450",
    ),
    (
        "s45_web_readme_closure_note",
        "apps/nex-ae-web/README.md",
        "Slice 0450 closes S45",
    ),
    (
        "s45_api_readme_closure_note",
        "services/nex-ae-api/README.md",
        "Slice 0450 closes S45",
    ),
    (
        "s45_ag_readme_collection_note",
        "services/nex-ag/README.md",
        "ag_artifact_operation_collection_projection.v1",
    ),
)


def run_s45_ae_artifact_library_management_closure(
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
        "slice_range": "0441-0450",
        "required_file_count": len(REQUIRED_FILES),
        "missing_files": missing_files,
        "token_results": token_results,
        "checks": checks,
        "experience_matrix": {
            "artifact_library_boundary_audit": True,
            "ae_collection_read_model": True,
            "ae_collection_api": True,
            "ae_collection_postgres_smoke": True,
            "web_collection_client_adapter": True,
            "web_library_panel_read_model": True,
            "web_library_ux_wiring": True,
            "web_library_playwright_postgres_smoke": True,
            "ag_collection_operations_projection": True,
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
            "browser_secret_header_included": False,
            "storage_path_included": False,
            "storage_ref_included": False,
        },
    }


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        return (
            "s45_ae_artifact_library_management_closure=pass "
            f"slice_range={evidence['slice_range']} "
            f"required_files={evidence['required_file_count']}"
        )
    failed_checks = [
        key for key, value in evidence.get("checks", {}).items() if value is not True
    ]
    return (
        "s45_ae_artifact_library_management_closure=fail "
        f"reason={evidence.get('failure_code')} "
        f"checks={','.join(failed_checks)}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run S45 AE artifact library management closure checks."
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a short result line.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_s45_ae_artifact_library_management_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence))
    return 1 if evidence["status"] == "FAIL" else 0


def _slice_docs_contiguous(root: Path) -> bool:
    docs_dir = root / "docs" / "slices"
    return all(
        (docs_dir / f"{slice_no:04d}_{suffix}.md").is_file()
        for slice_no, suffix in (
            (441, "ae_artifact_library_management_boundary_audit"),
            (442, "ae_artifact_collection_read_model_foundation"),
            (443, "ae_artifact_collection_api_wiring"),
            (444, "ae_artifact_collection_postgresql_smoke_evidence"),
            (445, "ae_web_artifact_collection_client_adapter"),
            (446, "ae_web_artifact_library_panel_read_model"),
            (447, "ae_web_artifact_library_ux_wiring"),
            (448, "ae_web_artifact_library_playwright_postgresql_smoke"),
            (449, "ag_artifact_collection_operations_projection"),
            (450, "s45_ae_artifact_library_management_closure"),
        )
    )


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
