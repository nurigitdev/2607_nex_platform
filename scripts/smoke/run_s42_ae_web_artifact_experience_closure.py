#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s42_ae_web_artifact_experience_closure.v1"

REQUIRED_FILES = (
    "apps/nex-ae-web/src/clientRegistry.js",
    "apps/nex-ae-web/src/main.js",
    "apps/nex-ae-web/src/artifactClient.js",
    "apps/nex-ae-web/src/artifactCardReadModel.js",
    "apps/nex-ae-web/src/artifactCard.js",
    "apps/nex-ae-web/src/artifactPreviewPanel.js",
    "apps/nex-ae-web/src/artifactVersionPanel.js",
    "apps/nex-ae-web/src/artifactMockRecord.js",
    "apps/nex-ae-web/src/runtimeDiagnostics.js",
    "apps/nex-ae-web/scripts/runArtifactFetchModeSmoke.mjs",
    "apps/nex-ae-web/scripts/runArtifactPlaywrightSmoke.mjs",
    "apps/nex-ae-web/package.json",
    "apps/nex-ae-web/README.md",
    "apps/nex-ae-web/test/artifactClient.test.mjs",
    "apps/nex-ae-web/test/artifactCardReadModel.test.mjs",
    "apps/nex-ae-web/test/artifactCard.test.mjs",
    "apps/nex-ae-web/test/artifactPreviewPanel.test.mjs",
    "apps/nex-ae-web/test/artifactVersionPanel.test.mjs",
    "apps/nex-ae-web/test/artifactFetchModeSmoke.test.mjs",
    "apps/nex-ae-web/test/artifactPlaywrightSmoke.test.mjs",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ae_web_artifact_surface_boundary_audit.py",
    "scripts/smoke/run_ae_web_artifact_postgres_smoke.py",
    "scripts/smoke/run_ae_web_artifact_playwright_postgres_smoke.py",
    "scripts/smoke/run_s41_artifact_runtime_closure.py",
    "scripts/smoke/run_s42_ae_web_artifact_experience_closure.py",
    "tests/test_ae_web_artifact_surface_boundary_audit.py",
    "tests/test_ae_web_artifact_postgres_smoke.py",
    "tests/test_ae_web_artifact_playwright_postgres_smoke.py",
    "tests/test_s42_ae_web_artifact_experience_closure.py",
    "docs/README.md",
    "docs/slices/0411_ae_web_artifact_surface_boundary_audit.md",
    "docs/slices/0412_ae_web_artifact_client_adapter_foundation.md",
    "docs/slices/0413_ae_web_artifact_card_read_model.md",
    "docs/slices/0414_ae_web_artifact_card_rendering.md",
    "docs/slices/0415_ae_web_artifact_preview_download_panel.md",
    "docs/slices/0416_ae_web_artifact_versions_files_panel.md",
    "docs/slices/0417_ae_web_artifact_fetch_mode_smoke_boundary.md",
    "docs/slices/0418_ae_web_artifact_postgresql_smoke_evidence.md",
    "docs/slices/0419_ae_web_artifact_playwright_postgresql_smoke.md",
    "docs/slices/0420_s42_ae_web_artifact_experience_closure.md",
)

TOKEN_CHECKS = (
    (
        "s42_closure_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_s42_ae_web_artifact_experience_closure.py",
    ),
    (
        "s41_closure_dependency_still_registered",
        "scripts/quality/run_quality_gate.sh",
        "run_s41_artifact_runtime_closure.py",
    ),
    (
        "artifact_surface_audit_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_web_artifact_surface_boundary_audit.py",
    ),
    (
        "web_artifact_postgres_smoke_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_web_artifact_postgres_smoke.py",
    ),
    (
        "web_artifact_playwright_postgres_smoke_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_web_artifact_playwright_postgres_smoke.py",
    ),
    (
        "artifact_fetch_smoke_alias",
        "apps/nex-ae-web/package.json",
        "smoke:artifact-fetch",
    ),
    (
        "artifact_playwright_smoke_alias",
        "apps/nex-ae-web/package.json",
        "smoke:artifact-playwright",
    ),
    (
        "client_registry_artifact_client",
        "apps/nex-ae-web/src/clientRegistry.js",
        "artifactClient",
    ),
    (
        "artifact_fetch_client_adapter",
        "apps/nex-ae-web/src/artifactClient.js",
        "createFetchArtifactClient",
    ),
    (
        "artifact_mock_client_adapter",
        "apps/nex-ae-web/src/artifactClient.js",
        "createMockArtifactClient",
    ),
    (
        "artifact_summary_content_guard",
        "apps/nex-ae-web/src/artifactClient.js",
        "content_included",
    ),
    (
        "artifact_card_read_model_schema",
        "apps/nex-ae-web/src/artifactCardReadModel.js",
        "ae_web_artifact_card_read_model.v1",
    ),
    (
        "artifact_card_collection_builder",
        "apps/nex-ae-web/src/artifactCardReadModel.js",
        "buildArtifactCardCollectionReadModel",
    ),
    (
        "artifact_card_renderer",
        "apps/nex-ae-web/src/artifactCard.js",
        "renderArtifactCard",
    ),
    (
        "artifact_preview_anchor",
        "apps/nex-ae-web/src/artifactCard.js",
        "data-artifact-preview-route",
    ),
    (
        "artifact_download_anchor",
        "apps/nex-ae-web/src/artifactCard.js",
        "data-artifact-download-route",
    ),
    (
        "artifact_preview_panel_schema",
        "apps/nex-ae-web/src/artifactPreviewPanel.js",
        "ae_web_artifact_preview_panel.v1",
    ),
    (
        "artifact_download_body_render_guard",
        "apps/nex-ae-web/src/artifactPreviewPanel.js",
        "downloadedContentRendered: false",
    ),
    (
        "artifact_version_panel_schema",
        "apps/nex-ae-web/src/artifactVersionPanel.js",
        "ae_web_artifact_version_panel.v1",
    ),
    (
        "artifact_version_panel_renderer",
        "apps/nex-ae-web/src/artifactVersionPanel.js",
        "export function renderArtifactVersionPanel(",
    ),
    (
        "main_artifact_preview_click_wiring",
        "apps/nex-ae-web/src/main.js",
        "data-artifact-preview-route",
    ),
    (
        "main_artifact_versions_refresh_wiring",
        "apps/nex-ae-web/src/main.js",
        "refreshArtifactVersionPanel",
    ),
    (
        "main_artifact_version_operation_state",
        "apps/nex-ae-web/src/main.js",
        'operationId: "artifact_versions"',
    ),
    (
        "artifact_fetch_mode_smoke_schema",
        "apps/nex-ae-web/scripts/runArtifactFetchModeSmoke.mjs",
        "ae_web_artifact_fetch_mode_smoke.v1",
    ),
    (
        "artifact_playwright_smoke_schema",
        "apps/nex-ae-web/scripts/runArtifactPlaywrightSmoke.mjs",
        "ae_web_artifact_playwright_smoke.v1",
    ),
    (
        "artifact_playwright_postgres_protected_env",
        "scripts/smoke/run_ae_web_artifact_playwright_postgres_smoke.py",
        "NEX_AE_WEB_ARTIFACT_PLAYWRIGHT_POSTGRES_SMOKE",
    ),
    (
        "artifact_playwright_doc_pass_shape",
        "docs/slices/0419_ae_web_artifact_playwright_postgresql_smoke.md",
        "ae_web_artifact_playwright_postgres_smoke=pass",
    ),
    (
        "s42_slice_index",
        "docs/README.md",
        "Slice 0420",
    ),
    (
        "s42_web_readme_closure_note",
        "apps/nex-ae-web/README.md",
        "Slice 0420 closes S42",
    ),
)


def run_s42_ae_web_artifact_experience_closure(
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
        "slice_range": "0411-0420",
        "required_file_count": len(REQUIRED_FILES),
        "missing_files": missing_files,
        "token_results": token_results,
        "checks": checks,
        "experience_matrix": {
            "boundary_audit": True,
            "client_adapter": True,
            "card_read_model": True,
            "card_renderer": True,
            "preview_download_panel": True,
            "versions_files_panel": True,
            "fetch_mode_smoke": True,
            "postgres_smoke": True,
            "playwright_postgres_smoke": True,
            "closure_checkpoint": True,
        },
        "redaction_summary": {
            "database_url_included": False,
            "service_token_included": False,
            "provider_api_key_included": False,
            "raw_prompt_included": False,
            "raw_generation_output_included": False,
            "raw_source_document_text_included": False,
            "raw_download_content_included": False,
            "browser_secret_header_included": False,
            "storage_path_included": False,
            "storage_ref_included": False,
        },
    }


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        return (
            "s42_ae_web_artifact_experience_closure=pass "
            f"slice_range={evidence['slice_range']} "
            f"required_files={evidence['required_file_count']}"
        )
    failed_checks = [
        key for key, value in evidence.get("checks", {}).items() if value is not True
    ]
    return (
        "s42_ae_web_artifact_experience_closure=fail "
        f"reason={evidence.get('failure_code')} "
        f"checks={','.join(failed_checks)}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run S42 AE Web artifact experience closure checks."
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a short result line.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_s42_ae_web_artifact_experience_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence))
    return 1 if evidence["status"] == "FAIL" else 0


def _slice_docs_contiguous(root: Path) -> bool:
    docs_dir = root / "docs" / "slices"
    return all(
        any(docs_dir.glob(f"{slice_id:04d}_*.md"))
        for slice_id in range(411, 421)
    )


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
