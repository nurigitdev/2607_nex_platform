#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s44_ae_web_artifact_delivery_closure.v1"

REQUIRED_FILES = (
    "apps/nex-ae-web/src/main.js",
    "apps/nex-ae-web/src/artifactClient.js",
    "apps/nex-ae-web/src/artifactCard.js",
    "apps/nex-ae-web/src/artifactPreviewPanel.js",
    "apps/nex-ae-web/src/artifactVersionPanel.js",
    "apps/nex-ae-web/src/artifactDownloadSaveAdapter.js",
    "apps/nex-ae-web/src/artifactDeliveryActionState.js",
    "apps/nex-ae-web/src/artifactExportResultReadModel.js",
    "apps/nex-ae-web/src/artifactDownloadFormatSelector.js",
    "apps/nex-ae-web/scripts/runArtifactPlaywrightSmoke.mjs",
    "apps/nex-ae-web/scripts/runArtifactDeliveryAccessibilitySmoke.mjs",
    "apps/nex-ae-web/package.json",
    "apps/nex-ae-web/README.md",
    "apps/nex-ae-web/test/artifactDownloadSaveAdapter.test.mjs",
    "apps/nex-ae-web/test/artifactDeliveryActionState.test.mjs",
    "apps/nex-ae-web/test/artifactExportResultReadModel.test.mjs",
    "apps/nex-ae-web/test/artifactDownloadFormatSelector.test.mjs",
    "apps/nex-ae-web/test/artifactDeliveryAccessibilitySmoke.test.mjs",
    "apps/nex-ae-web/test/artifactPlaywrightSmoke.test.mjs",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ae_web_artifact_delivery_boundary_audit.py",
    "scripts/smoke/run_ae_web_artifact_playwright_postgres_smoke.py",
    "scripts/smoke/run_ae_web_artifact_multiformat_playwright_postgres_smoke.py",
    "scripts/smoke/run_s44_ae_web_artifact_delivery_closure.py",
    "tests/test_ae_web_artifact_delivery_boundary_audit.py",
    "tests/test_ae_web_artifact_playwright_postgres_smoke.py",
    "tests/test_ae_web_artifact_multiformat_playwright_postgres_smoke.py",
    "tests/test_s44_ae_web_artifact_delivery_closure.py",
    "docs/README.md",
    "docs/slices/0431_ae_web_artifact_delivery_boundary_audit.md",
    "docs/slices/0432_ae_web_browser_file_save_adapter_foundation.md",
    "docs/slices/0433_ae_web_artifact_download_action_wiring.md",
    "docs/slices/0434_ae_web_export_result_ux_read_model.md",
    "docs/slices/0435_ae_web_artifact_download_playwright_postgresql_smoke.md",
    "docs/slices/0436_ae_web_artifact_delivery_action_state.md",
    "docs/slices/0437_ae_web_artifact_download_format_selector.md",
    "docs/slices/0438_ae_web_artifact_delivery_accessibility_smoke.md",
    "docs/slices/0439_ae_web_multiformat_artifact_playwright_postgresql_smoke.md",
    "docs/slices/0440_s44_ae_web_artifact_delivery_closure.md",
)

TOKEN_CHECKS = (
    (
        "s44_closure_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_s44_ae_web_artifact_delivery_closure.py",
    ),
    (
        "s43_closure_dependency_still_registered",
        "scripts/quality/run_quality_gate.sh",
        "run_s43_ae_artifact_export_transform_closure.py",
    ),
    (
        "delivery_boundary_audit_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_web_artifact_delivery_boundary_audit.py",
    ),
    (
        "artifact_playwright_postgres_smoke_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_web_artifact_playwright_postgres_smoke.py",
    ),
    (
        "artifact_multiformat_playwright_postgres_smoke_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_web_artifact_multiformat_playwright_postgres_smoke.py",
    ),
    (
        "artifact_accessibility_smoke_gate",
        "scripts/quality/run_quality_gate.sh",
        "runArtifactDeliveryAccessibilitySmoke.mjs",
    ),
    (
        "download_save_adapter_schema",
        "apps/nex-ae-web/src/artifactDownloadSaveAdapter.js",
        "AE_WEB_ARTIFACT_DOWNLOAD_SAVE_SCHEMA_VERSION",
    ),
    (
        "download_save_adapter_materializer",
        "apps/nex-ae-web/src/artifactDownloadSaveAdapter.js",
        "saveArtifactDownload",
    ),
    (
        "delivery_action_state_schema",
        "apps/nex-ae-web/src/artifactDeliveryActionState.js",
        "AE_WEB_ARTIFACT_DELIVERY_ACTION_STATE_SCHEMA_VERSION",
    ),
    (
        "delivery_action_summary",
        "apps/nex-ae-web/src/artifactDeliveryActionState.js",
        "buildArtifactDeliveryActionSummary",
    ),
    (
        "delivery_action_save_wiring",
        "apps/nex-ae-web/src/artifactDeliveryActionState.js",
        "downloadSaveSummary",
    ),
    (
        "export_result_read_model_schema",
        "apps/nex-ae-web/src/artifactExportResultReadModel.js",
        "AE_WEB_ARTIFACT_EXPORT_RESULT_READ_MODEL_SCHEMA_VERSION",
    ),
    (
        "export_result_main_surface",
        "apps/nex-ae-web/src/main.js",
        "artifactExportResult",
    ),
    (
        "download_format_selector_schema",
        "apps/nex-ae-web/src/artifactDownloadFormatSelector.js",
        "AE_WEB_ARTIFACT_DOWNLOAD_FORMAT_SELECTOR_SCHEMA_VERSION",
    ),
    (
        "download_format_selector_renderer",
        "apps/nex-ae-web/src/artifactDownloadFormatSelector.js",
        "renderArtifactDownloadFormatSelector",
    ),
    (
        "selector_action_route_wiring",
        "apps/nex-ae-web/src/main.js",
        "data-artifact-download-route",
    ),
    (
        "playwright_file_save_evidence",
        "apps/nex-ae-web/scripts/runArtifactPlaywrightSmoke.mjs",
        "browser_file_save_prepared",
    ),
    (
        "playwright_export_result_evidence",
        "apps/nex-ae-web/scripts/runArtifactPlaywrightSmoke.mjs",
        "browser_export_result_saved",
    ),
    (
        "playwright_selector_evidence",
        "apps/nex-ae-web/scripts/runArtifactPlaywrightSmoke.mjs",
        "artifact_download_selector_ready",
    ),
    (
        "accessibility_selector_evidence",
        "apps/nex-ae-web/scripts/runArtifactDeliveryAccessibilitySmoke.mjs",
        "selector_selected_state_visible",
    ),
    (
        "accessibility_keyboard_evidence",
        "apps/nex-ae-web/scripts/runArtifactDeliveryAccessibilitySmoke.mjs",
        "download_anchor_keyboard_reachable",
    ),
    (
        "multiformat_protected_env",
        "scripts/smoke/run_ae_web_artifact_multiformat_playwright_postgres_smoke.py",
        "NEX_AE_WEB_ARTIFACT_MULTIFORMAT_PLAYWRIGHT_POSTGRES_SMOKE",
    ),
    (
        "multiformat_selector_check",
        "scripts/smoke/run_ae_web_artifact_multiformat_playwright_postgres_smoke.py",
        "browser_download_selector_multiformat",
    ),
    (
        "multiformat_summary_shape",
        "docs/slices/0439_ae_web_multiformat_artifact_playwright_postgresql_smoke.md",
        "enabled=4 formats=4 files=4 links=8 rows=17",
    ),
    (
        "s44_slice_index",
        "docs/README.md",
        "Slice 0440",
    ),
    (
        "s44_web_readme_closure_note",
        "apps/nex-ae-web/README.md",
        "Slice 0440 closes S44",
    ),
)


def run_s44_ae_web_artifact_delivery_closure(
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
        "slice_range": "0431-0440",
        "required_file_count": len(REQUIRED_FILES),
        "missing_files": missing_files,
        "token_results": token_results,
        "checks": checks,
        "experience_matrix": {
            "delivery_boundary_audit": True,
            "browser_file_save_adapter": True,
            "download_action_wiring": True,
            "export_result_read_model": True,
            "download_playwright_postgres_smoke": True,
            "delivery_action_state": True,
            "download_format_selector": True,
            "delivery_accessibility_smoke": True,
            "multiformat_playwright_postgres_smoke": True,
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
            "raw_binary_download_content_included": False,
            "browser_secret_header_included": False,
            "storage_path_included": False,
            "storage_ref_included": False,
        },
    }


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        return (
            "s44_ae_web_artifact_delivery_closure=pass "
            f"slice_range={evidence['slice_range']} "
            f"required_files={evidence['required_file_count']}"
        )
    failed_checks = [
        key for key, value in evidence.get("checks", {}).items() if value is not True
    ]
    return (
        "s44_ae_web_artifact_delivery_closure=fail "
        f"reason={evidence.get('failure_code')} "
        f"checks={','.join(failed_checks)}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run S44 AE Web artifact delivery closure checks."
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a short result line.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_s44_ae_web_artifact_delivery_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence))
    return 1 if evidence["status"] == "FAIL" else 0


def _slice_docs_contiguous(root: Path) -> bool:
    docs_dir = root / "docs" / "slices"
    return all(
        (docs_dir / f"{slice_no:04d}_{suffix}.md").is_file()
        for slice_no, suffix in (
            (431, "ae_web_artifact_delivery_boundary_audit"),
            (432, "ae_web_browser_file_save_adapter_foundation"),
            (433, "ae_web_artifact_download_action_wiring"),
            (434, "ae_web_export_result_ux_read_model"),
            (435, "ae_web_artifact_download_playwright_postgresql_smoke"),
            (436, "ae_web_artifact_delivery_action_state"),
            (437, "ae_web_artifact_download_format_selector"),
            (438, "ae_web_artifact_delivery_accessibility_smoke"),
            (439, "ae_web_multiformat_artifact_playwright_postgresql_smoke"),
            (440, "s44_ae_web_artifact_delivery_closure"),
        )
    )


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
