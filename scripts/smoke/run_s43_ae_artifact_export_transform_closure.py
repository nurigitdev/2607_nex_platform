#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s43_ae_artifact_export_transform_closure.v1"

REQUIRED_FILES = (
    "services/nex-ae-api/nex_ae_api/artifacts.py",
    "services/nex-ae-api/README.md",
    "apps/nex-ae-web/src/main.js",
    "apps/nex-ae-web/src/artifactClient.js",
    "apps/nex-ae-web/src/artifactPreviewPanel.js",
    "apps/nex-ae-web/scripts/runArtifactFetchModeSmoke.mjs",
    "apps/nex-ae-web/README.md",
    "apps/nex-ae-web/test/artifactClient.test.mjs",
    "apps/nex-ae-web/test/artifactPreviewPanel.test.mjs",
    "apps/nex-ae-web/test/artifactFetchModeSmoke.test.mjs",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ae_artifact_export_transform_boundary_audit.py",
    "scripts/smoke/run_ae_artifact_export_postgres_smoke.py",
    "scripts/smoke/run_s42_ae_web_artifact_experience_closure.py",
    "scripts/smoke/run_s43_ae_artifact_export_transform_closure.py",
    "tests/test_nex_ae_artifacts.py",
    "tests/test_ae_artifact_export_transform_boundary_audit.py",
    "tests/test_ae_artifact_export_postgres_smoke.py",
    "tests/test_s43_ae_artifact_export_transform_closure.py",
    "docs/README.md",
    "docs/slices/0421_ae_artifact_export_transform_boundary_audit.md",
    "docs/slices/0422_ae_export_transform_catalog_format_neutral_storage.md",
    "docs/slices/0423_ae_html_preview_materializer.md",
    "docs/slices/0424_ae_docx_export_adapter.md",
    "docs/slices/0425_ae_pdf_export_adapter_multi_format_stage_policy.md",
    "docs/slices/0426_ae_web_export_submit_adapter_postgres_smoke.md",
    "docs/slices/0427_ae_web_binary_artifact_download_surface.md",
    "docs/slices/0428_ae_web_export_fetch_mode_smoke_hardening.md",
    "docs/slices/0429_ae_artifact_export_read_model_postgres_smoke.md",
    "docs/slices/0430_s43_ae_artifact_export_transform_closure.md",
)

TOKEN_CHECKS = (
    (
        "s43_closure_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_s43_ae_artifact_export_transform_closure.py",
    ),
    (
        "s42_closure_dependency_still_registered",
        "scripts/quality/run_quality_gate.sh",
        "run_s42_ae_web_artifact_experience_closure.py",
    ),
    (
        "export_boundary_audit_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_artifact_export_transform_boundary_audit.py",
    ),
    (
        "export_postgres_smoke_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_artifact_export_postgres_smoke.py",
    ),
    (
        "transformer_catalog",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "ARTIFACT_TRANSFORMER_CATALOG",
    ),
    (
        "multi_format_stage_policy",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "MULTI_FORMAT_RENDER_STAGE_ORDER",
    ),
    (
        "html_preview_materializer",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "build_html_preview_artifact_file",
    ),
    (
        "docx_export_adapter",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "build_docx_export_artifact_file",
    ),
    (
        "pdf_export_adapter",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "render_pdf_export_from_markdown",
    ),
    (
        "binary_download_contract",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "rendered_download_fields_from_payload",
    ),
    (
        "web_export_submit_adapter",
        "apps/nex-ae-web/src/artifactClient.js",
        "submitArtifactExportRequest",
    ),
    (
        "web_binary_download_surface",
        "apps/nex-ae-web/src/artifactClient.js",
        "downloadPayloadKind",
    ),
    (
        "web_base64_payload_surface",
        "apps/nex-ae-web/src/artifactClient.js",
        "contentBase64",
    ),
    (
        "panel_binary_metadata_summary",
        "apps/nex-ae-web/src/artifactPreviewPanel.js",
        "download_payload_kind",
    ),
    (
        "panel_download_render_guard",
        "apps/nex-ae-web/src/artifactPreviewPanel.js",
        "downloadedContentRendered: false",
    ),
    (
        "fetch_mode_export_smoke",
        "apps/nex-ae-web/scripts/runArtifactFetchModeSmoke.mjs",
        "export_formats",
    ),
    (
        "fetch_mode_binary_redaction",
        "apps/nex-ae-web/scripts/runArtifactFetchModeSmoke.mjs",
        "binary_download_panel_metadata_only",
    ),
    (
        "postgres_smoke_read_models",
        "scripts/smoke/run_ae_artifact_export_postgres_smoke.py",
        "read_model_observations",
    ),
    (
        "postgres_smoke_summary_read_model_files",
        "scripts/smoke/run_ae_artifact_export_postgres_smoke.py",
        "read_model_files",
    ),
    (
        "slice_0429_doc_read_model_evidence",
        "docs/slices/0429_ae_artifact_export_read_model_postgres_smoke.md",
        "read_model_files=4",
    ),
    (
        "s43_slice_index",
        "docs/README.md",
        "Slice 0430",
    ),
    (
        "s43_web_readme_binary_note",
        "apps/nex-ae-web/README.md",
        "Slice 0428 hardens the fetch-mode export smoke",
    ),
    (
        "s43_api_readme_postgres_note",
        "services/nex-ae-api/README.md",
        "Slice 0429 hardens the protected multi-format export PostgreSQL smoke",
    ),
)


def run_s43_ae_artifact_export_transform_closure(
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
        "slice_range": "0421-0430",
        "required_file_count": len(REQUIRED_FILES),
        "missing_files": missing_files,
        "token_results": token_results,
        "checks": checks,
        "experience_matrix": {
            "boundary_audit": True,
            "transform_catalog": True,
            "html_preview_export": True,
            "docx_export": True,
            "pdf_export": True,
            "web_export_submit": True,
            "web_binary_download_surface": True,
            "fetch_mode_export_smoke": True,
            "postgres_read_model_smoke": True,
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
            "storage_path_included": False,
            "storage_ref_included": False,
        },
    }


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        return (
            "s43_ae_artifact_export_transform_closure=pass "
            f"slice_range={evidence['slice_range']} "
            f"required_files={evidence['required_file_count']}"
        )
    failed_checks = [
        key for key, value in evidence.get("checks", {}).items() if value is not True
    ]
    return (
        "s43_ae_artifact_export_transform_closure=fail "
        f"reason={evidence.get('failure_code')} "
        f"checks={','.join(failed_checks)}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run S43 AE artifact export/transform closure checks."
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a short result line.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_s43_ae_artifact_export_transform_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence))
    return 1 if evidence["status"] == "FAIL" else 0


def _slice_docs_contiguous(root: Path) -> bool:
    docs_dir = root / "docs" / "slices"
    return all(
        any(docs_dir.glob(f"{slice_id:04d}_*.md"))
        for slice_id in range(421, 431)
    )


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
