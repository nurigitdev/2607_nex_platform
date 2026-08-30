#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "ae_artifact_export_transform_boundary_audit.v1"

PROTECTED_ENV_KEYS = (
    "NEX_AE_DATABASE_URL",
    "NEX_AE_TEST_DATABASE_URL",
    "NEX_AE_ARTIFACT_STORAGE_ROOT",
    "NEX_DATA_ROOT",
    "NEX_SERVICE_TOKEN",
    "NEX_AE_TO_CX_SERVICE_TOKEN",
)

SENSITIVE_PATTERNS = (
    (re.compile(r"postgresql\+?[^\"'\s]+", re.IGNORECASE), "database_url"),
    (re.compile(r"nuri1004", re.IGNORECASE), "database_password"),
    (re.compile(r"/data/nex-platform", re.IGNORECASE), "local_data_path"),
    (
        re.compile(
            r"(?:api[_-]?key|provider_api_key|authorization)[=:\"]\s*[^\"'\s,}]+",
            re.IGNORECASE,
        ),
        "provider_api_key",
    ),
    (re.compile(r"service-token-[\w-]+", re.IGNORECASE), "service_token"),
)


@dataclass(frozen=True)
class RequiredPath:
    name: str
    path: Path
    purpose: str


@dataclass(frozen=True)
class TokenRequirement:
    group: str
    path: Path
    token_id: str
    token: str
    purpose: str


@dataclass(frozen=True)
class PlannedGap:
    name: str
    path: Path
    token: str
    planned_slice: str
    purpose: str


AE_ARTIFACTS = ROOT / "services" / "nex-ae-api" / "nex_ae_api" / "artifacts.py"
AE_README = ROOT / "services" / "nex-ae-api" / "README.md"
AE_WEB_INDEX = ROOT / "apps" / "nex-ae-web" / "index.html"
AE_WEB_MAIN = ROOT / "apps" / "nex-ae-web" / "src" / "main.js"
AE_WEB_ARTIFACT_CLIENT = ROOT / "apps" / "nex-ae-web" / "src" / "artifactClient.js"
AE_WEB_ARTIFACT_MOCK_RECORD = (
    ROOT / "apps" / "nex-ae-web" / "src" / "artifactMockRecord.js"
)
AE_WEB_README = ROOT / "apps" / "nex-ae-web" / "README.md"
OPENAPI = ROOT / "contracts" / "openapi" / "nex-ae-api.openapi.yaml"
ARTIFACT_RECORD_SCHEMA = (
    ROOT / "contracts" / "schemas" / "generation" / "ae_artifact_record.v1.schema.json"
)
ARTIFACT_HANDOFF_SCHEMA = (
    ROOT
    / "contracts"
    / "schemas"
    / "generation"
    / "ae_artifact_handoff.v1.schema.json"
)
AE_ORCHESTRATION_DOC = ROOT / "docs" / "13_ae_agent_orchestration_contract.md"
AE_CX_GENERATION_DOC = (
    ROOT / "docs" / "16_ae_cx_generation_request_package_contract.md"
)
AE_ARTIFACT_ARCHIVE_DOC = (
    ROOT / "docs" / "archive" / "planning" / "20_ae_artifact_rendering_handoff_contract.md"
)
TESTING_STRATEGY_DOC = ROOT / "docs" / "34_testing_strategy_v0_1_detail.md"
DOCS_README = ROOT / "docs" / "README.md"
QUALITY_GATE = ROOT / "scripts" / "quality" / "run_quality_gate.sh"
SLICE_0420_DOC = (
    ROOT / "docs" / "slices" / "0420_s42_ae_web_artifact_experience_closure.md"
)
SLICE_0421_DOC = (
    ROOT / "docs" / "slices" / "0421_ae_artifact_export_transform_boundary_audit.md"
)

REQUIRED_PATHS = (
    RequiredPath("ae_artifacts", AE_ARTIFACTS, "AE artifact render route module."),
    RequiredPath("ae_readme", AE_README, "AE API artifact boundary notes."),
    RequiredPath("ae_web_index", AE_WEB_INDEX, "AE Web format selection surface."),
    RequiredPath("ae_web_main", AE_WEB_MAIN, "AE Web chat artifact request wiring."),
    RequiredPath(
        "ae_web_artifact_client",
        AE_WEB_ARTIFACT_CLIENT,
        "AE Web artifact fetch/mock adapter.",
    ),
    RequiredPath(
        "ae_web_artifact_mock_record",
        AE_WEB_ARTIFACT_MOCK_RECORD,
        "AE Web mock format metadata builder.",
    ),
    RequiredPath("ae_web_readme", AE_WEB_README, "AE Web artifact surface notes."),
    RequiredPath("openapi", OPENAPI, "AE API artifact route contract."),
    RequiredPath(
        "artifact_record_schema",
        ARTIFACT_RECORD_SCHEMA,
        "Artifact record format/stage contract.",
    ),
    RequiredPath(
        "artifact_handoff_schema",
        ARTIFACT_HANDOFF_SCHEMA,
        "Artifact handoff target format contract.",
    ),
    RequiredPath(
        "ae_orchestration_doc",
        AE_ORCHESTRATION_DOC,
        "AE orchestration mode contract.",
    ),
    RequiredPath(
        "ae_cx_generation_doc",
        AE_CX_GENERATION_DOC,
        "AE/CX generation request package contract.",
    ),
    RequiredPath(
        "ae_artifact_archive_doc",
        AE_ARTIFACT_ARCHIVE_DOC,
        "Archived artifact rendering handoff details.",
    ),
    RequiredPath(
        "testing_strategy_doc",
        TESTING_STRATEGY_DOC,
        "Artifact handoff regression strategy.",
    ),
    RequiredPath("docs_readme", DOCS_README, "Slice index."),
    RequiredPath("quality_gate", QUALITY_GATE, "Default regression hook."),
    RequiredPath("slice_0420_doc", SLICE_0420_DOC, "S42 closure baseline."),
    RequiredPath("slice_0421_doc", SLICE_0421_DOC, "This boundary audit record."),
)

REQUIRED_SOURCE_TOKENS = (
    TokenRequirement(
        "contract_format_surface",
        AE_ARTIFACTS,
        "runtime_allowlist_declares_future_formats",
        'SUPPORTED_TARGET_FORMATS = {"MD", "HTML_PREVIEW", "DOCX", "PDF"}',
        "Runtime intake already names the future export formats.",
    ),
    TokenRequirement(
        "contract_format_surface",
        ARTIFACT_HANDOFF_SCHEMA,
        "handoff_target_format_docx",
        '"DOCX"',
        "Handoff contract allows DOCX target format requests.",
    ),
    TokenRequirement(
        "contract_format_surface",
        ARTIFACT_RECORD_SCHEMA,
        "record_target_format_pdf",
        '"PDF"',
        "Artifact record contract allows PDF file records and render stages.",
    ),
    TokenRequirement(
        "contract_format_surface",
        OPENAPI,
        "render_job_route_contract",
        "operationId: createAeArtifactRenderJob",
        "OpenAPI exposes the render job route to own export execution.",
    ),
    TokenRequirement(
        "current_runtime_boundary",
        AE_ARTIFACTS,
        "markdown_render_result",
        "build_markdown_render_result",
        "Current materialization path builds a Markdown render result.",
    ),
    TokenRequirement(
        "current_runtime_boundary",
        AE_ARTIFACTS,
        "markdown_artifact_files",
        "build_markdown_artifact_files",
        "Current file builder only creates Markdown artifact files.",
    ),
    TokenRequirement(
        "current_runtime_boundary",
        AE_ARTIFACTS,
        "markdown_only_guard",
        "Slice 0042 supports Markdown rendering only.",
        "Current render route rejects non-Markdown render requests.",
    ),
    TokenRequirement(
        "current_runtime_boundary",
        AE_ARTIFACTS,
        "markdown_result_schema",
        "ae_markdown_render_result.v1",
        "Current render response remains Markdown-specific.",
    ),
    TokenRequirement(
        "storage_payload_boundary",
        AE_ARTIFACTS,
        "storage_protocol",
        "class RenderedArtifactStorage",
        "Rendered payload storage is isolated behind an adapter protocol.",
    ),
    TokenRequirement(
        "storage_payload_boundary",
        AE_ARTIFACTS,
        "local_storage_adapter",
        "class LocalRenderedArtifactStorage",
        "Local rendered artifact payloads stay behind a private storage adapter.",
    ),
    TokenRequirement(
        "storage_payload_boundary",
        AE_ARTIFACTS,
        "markdown_payload_methods",
        "save_markdown",
        "The current adapter method name is Markdown-specific.",
    ),
    TokenRequirement(
        "storage_payload_boundary",
        AE_ARTIFACTS,
        "logical_storage_ref",
        "ae://artifacts/",
        "Public metadata uses logical refs instead of local filesystem paths.",
    ),
    TokenRequirement(
        "web_request_surface",
        AE_WEB_INDEX,
        "format_select_anchor",
        'id="format-select"',
        "AE Web has a user-facing output format selector.",
    ),
    TokenRequirement(
        "web_request_surface",
        AE_WEB_INDEX,
        "pdf_option_visible",
        '<option value="PDF">PDF</option>',
        "AE Web currently exposes PDF as a selectable future format.",
    ),
    TokenRequirement(
        "web_request_surface",
        AE_WEB_MAIN,
        "mock_artifact_ref_format",
        "function buildMockArtifactRef(format",
        "Current web flow turns selected format into mock artifact refs.",
    ),
    TokenRequirement(
        "web_request_surface",
        AE_WEB_ARTIFACT_MOCK_RECORD,
        "mime_type_for_format",
        "mimeTypeForArtifactFormat(format)",
        "Mock artifact records already map requested formats to MIME metadata.",
    ),
    TokenRequirement(
        "web_request_surface",
        AE_WEB_ARTIFACT_CLIENT,
        "download_adapter_surface",
        "downloadArtifactFile",
        "AE Web already has a browser-safe artifact download adapter method.",
    ),
    TokenRequirement(
        "canonical_docs",
        AE_ORCHESTRATION_DOC,
        "artifact_transform_mode",
        "ARTIFACT_TRANSFORM",
        "AE orchestration docs reserve an artifact transform mode.",
    ),
    TokenRequirement(
        "canonical_docs",
        AE_CX_GENERATION_DOC,
        "preferred_export_format",
        "preferred_export_format",
        "AE/CX request package docs carry preferred export format intent.",
    ),
    TokenRequirement(
        "canonical_docs",
        AE_CX_GENERATION_DOC,
        "create_and_export_intent",
        "create_and_export",
        "Generation package docs name create-and-export artifact intent.",
    ),
    TokenRequirement(
        "canonical_docs",
        AE_ARTIFACT_ARCHIVE_DOC,
        "multi_stage_rendering_contract",
        "DOCX_RENDERING",
        "Archived detailed contract names multi-format render stages.",
    ),
    TokenRequirement(
        "canonical_docs",
        TESTING_STRATEGY_DOC,
        "artifact_handoff_docx_case",
        "Valid DOCX target",
        "Testing strategy already expects export-format handoff coverage.",
    ),
    TokenRequirement(
        "slice_wiring",
        QUALITY_GATE,
        "quality_gate_hook",
        "run_ae_artifact_export_transform_boundary_audit.py --summary",
        "Default quality gate runs this boundary audit.",
    ),
    TokenRequirement(
        "slice_wiring",
        DOCS_README,
        "docs_index",
        "0421_ae_artifact_export_transform_boundary_audit.md",
        "Slice index points to the audit document.",
    ),
    TokenRequirement(
        "slice_wiring",
        AE_README,
        "ae_readme_note",
        "Slice 0421 audits the export/transform boundary",
        "AE API README records the current Markdown-only runtime boundary.",
    ),
    TokenRequirement(
        "slice_wiring",
        AE_WEB_README,
        "ae_web_readme_note",
        "Slice 0421 starts S43",
        "AE Web README records that format selection is request-surface only.",
    ),
    TokenRequirement(
        "slice_wiring",
        SLICE_0421_DOC,
        "slice_doc_title",
        "Slice 0421: AE Artifact Export/Transform Boundary Audit",
        "Slice documentation exists with the expected title.",
    ),
)

PLANNED_GAPS = (
    PlannedGap(
        "transform_catalog_and_policy",
        AE_ARTIFACTS,
        "ARTIFACT_TRANSFORMER_CATALOG",
        "Slice 0422",
        "Add an explicit AE-owned transform catalog and format policy matrix.",
    ),
    PlannedGap(
        "format_neutral_storage_adapter",
        AE_ARTIFACTS,
        "save_rendered_artifact_file",
        "Slice 0422",
        "Generalize storage from Markdown payloads to typed rendered files.",
    ),
    PlannedGap(
        "html_preview_materializer",
        AE_ARTIFACTS,
        "build_html_preview_artifact_file",
        "Slice 0423",
        "Materialize safe HTML preview output behind the artifact route boundary.",
    ),
    PlannedGap(
        "docx_export_adapter",
        AE_ARTIFACTS,
        "build_docx_export_artifact_file",
        "Slice 0424",
        "Add a DOCX export adapter and file metadata builder.",
    ),
    PlannedGap(
        "pdf_export_adapter",
        AE_ARTIFACTS,
        "build_pdf_export_artifact_file",
        "Slice 0425",
        "Add a PDF export adapter and file metadata builder.",
    ),
    PlannedGap(
        "multi_format_render_job_state",
        AE_ARTIFACTS,
        "MULTI_FORMAT_RENDER_STAGE_ORDER",
        "Slice 0425",
        "Move render job progress beyond the current Markdown-only stage.",
    ),
    PlannedGap(
        "web_export_submit_adapter",
        AE_WEB_MAIN,
        "submitArtifactExportRequest",
        "Slice 0426",
        "Wire AE Web format selection to real export job requests.",
    ),
    PlannedGap(
        "postgres_export_smoke",
        QUALITY_GATE,
        "run_ae_artifact_export_postgres_smoke.py",
        "Slice 0426",
        "Prove multi-format artifact files against nex_ae_test when implemented.",
    ),
)


def run_ae_artifact_export_transform_boundary_audit(
    environ: Mapping[str, str] | None = None,
    *,
    root_dir: Path = ROOT,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    paths = path_checks(root_dir)
    source_tokens = source_token_checks(root_dir)
    token_groups = grouped_token_status(source_tokens)
    gaps = planned_gap_checks(root_dir)
    decisions = build_decisions()
    issues = [
        *[
            issue("path_missing", item["name"], item["path"])
            for item in paths
            if item["present"] is not True
        ],
        *[
            issue("source_token_missing", item["token_id"], item["path"])
            for item in source_tokens
            if item["present"] is not True
        ],
    ]
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "contract_format_surface_present": token_groups.get(
            "contract_format_surface"
        )
        is True,
        "current_runtime_boundary_present": token_groups.get(
            "current_runtime_boundary"
        )
        is True,
        "storage_payload_boundary_present": token_groups.get("storage_payload_boundary")
        is True,
        "web_request_surface_present": token_groups.get("web_request_surface") is True,
        "canonical_docs_present": token_groups.get("canonical_docs") is True,
        "slice_wiring_present": token_groups.get("slice_wiring") is True,
        "current_runtime_is_markdown_only": all(
            token_is_present(source_tokens, token_id)
            for token_id in (
                "markdown_render_result",
                "markdown_artifact_files",
                "markdown_only_guard",
                "markdown_result_schema",
            )
        ),
        "future_export_formats_are_declared": all(
            token_is_present(source_tokens, token_id)
            for token_id in (
                "runtime_allowlist_declares_future_formats",
                "handoff_target_format_docx",
                "record_target_format_pdf",
                "pdf_option_visible",
            )
        ),
        "planned_gaps_are_non_blocking": all(
            item["blocking"] is False for item in gaps
        ),
        "transform_owner_is_ae": decisions["artifact_transform_owner"]
        == "nex-ae-api",
        "redacted_evidence_only": True,
    }
    status = "PASS" if not issues and all(checks.values()) else "FAIL"
    evidence = {
        "audit_schema_version": SCHEMA_VERSION,
        "status": status,
        "scope": {
            "slice": "Slice 0421",
            "focus": "ae_artifact_export_transform_boundary",
            "from": "markdown_only_artifact_materialization",
            "toward": "multi_format_export_transform_runtime",
        },
        "paths": paths,
        "source_tokens": source_tokens,
        "planned_gaps": gaps,
        "decisions": decisions,
        "checks": checks,
        "issues": issues,
        "protected_env": summarize_protected_env(env),
        "redaction": {
            "database_url_included": False,
            "service_token_included": False,
            "provider_api_key_included": False,
            "raw_prompt_included": False,
            "raw_generation_output_included": False,
            "raw_source_document_text_included": False,
            "raw_download_content_included": False,
            "local_storage_path_included": False,
            "physical_storage_ref_included": False,
        },
    }
    assert_evidence_redacted(json.dumps(evidence, ensure_ascii=False), env)
    return evidence


def path_checks(root_dir: Path) -> list[dict[str, object]]:
    return [
        {
            "name": item.name,
            "path": relative_label(item.path, root_dir),
            "present": path_for(root_dir, item.path).exists(),
            "purpose": item.purpose,
        }
        for item in REQUIRED_PATHS
    ]


def source_token_checks(root_dir: Path) -> list[dict[str, object]]:
    return [
        {
            "group": item.group,
            "path": relative_label(item.path, root_dir),
            "token_id": item.token_id,
            "present": item.token in read_text(root_dir, item.path),
            "purpose": item.purpose,
        }
        for item in REQUIRED_SOURCE_TOKENS
    ]


def planned_gap_checks(root_dir: Path) -> list[dict[str, object]]:
    return [
        {
            "name": item.name,
            "path": relative_label(item.path, root_dir),
            "planned_slice": item.planned_slice,
            "purpose": item.purpose,
            "already_present": item.token in read_text(root_dir, item.path),
            "blocking": False,
        }
        for item in PLANNED_GAPS
    ]


def build_decisions() -> dict[str, object]:
    return {
        "artifact_transform_owner": "nex-ae-api",
        "browser_request_surface_owner": "nex-ae-web",
        "source_generation_owner": "nex-cx",
        "operations_observer": "nex-ag",
        "current_runtime_materialization": "markdown_only_synchronous_renderer",
        "current_storage_adapter_shape": "markdown_payload_methods",
        "declared_target_formats": ["MD", "HTML_PREVIEW", "DOCX", "PDF"],
        "implemented_materialized_format": "MD",
        "future_materialized_formats": ["HTML_PREVIEW", "DOCX", "PDF"],
        "storage_policy": "logical_artifact_refs_public_private_payload_storage",
        "web_policy": "format_selector_is_request_intent_until_export_jobs_are_wired",
        "postgres_smoke_policy": "protected_test_profile_when_export_files_are_persisted",
        "next_slices": [
            "Slice 0422",
            "Slice 0423",
            "Slice 0424",
            "Slice 0425",
            "Slice 0426",
        ],
    }


def grouped_token_status(items: list[dict[str, object]]) -> dict[str, bool]:
    groups = sorted({str(item["group"]) for item in items})
    return {
        group: all(
            item["present"] is True for item in items if item["group"] == group
        )
        for group in groups
    }


def token_is_present(items: list[dict[str, object]], token_id: str) -> bool:
    return any(
        item["token_id"] == token_id and item["present"] is True for item in items
    )


def summarize_protected_env(env: Mapping[str, str]) -> dict[str, bool]:
    return {key: bool(env.get(key)) for key in PROTECTED_ENV_KEYS}


def issue(category: str, subject: object, detail: object) -> dict[str, str]:
    return {"category": category, "subject": str(subject), "detail": str(detail)}


def present_count(items: list[dict[str, object]]) -> int:
    return sum(1 for item in items if item.get("present") is True)


def present_count_bool(items: Mapping[str, bool]) -> int:
    return sum(1 for value in items.values() if value is True)


def gap_ready_count(items: list[dict[str, object]]) -> int:
    return sum(1 for item in items if item.get("already_present") is True)


def next_planned_slice(items: list[dict[str, object]]) -> str:
    for item in items:
        if item.get("already_present") is not True:
            return str(item["planned_slice"])
    return "complete"


def read_text(root_dir: Path, absolute_path: Path) -> str:
    path = path_for(root_dir, absolute_path)
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def path_for(root_dir: Path, absolute_path: Path) -> Path:
    try:
        return root_dir / absolute_path.relative_to(ROOT)
    except ValueError:
        return absolute_path


def relative_label(path: Path, root_dir: Path = ROOT) -> str:
    try:
        return str(path.relative_to(root_dir))
    except ValueError:
        try:
            return str(path.relative_to(ROOT))
        except ValueError:
            return path.name


def assert_evidence_redacted(
    serialized_evidence: str,
    environ: Mapping[str, str],
) -> None:
    for key in PROTECTED_ENV_KEYS:
        value = environ.get(key)
        if value and value not in {"1", "test", "true"} and value in serialized_evidence:
            raise ValueError(
                "AE artifact export/transform audit evidence contains "
                f"unredacted environment value: {key}"
            )
    for pattern, label in SENSITIVE_PATTERNS:
        if pattern.search(serialized_evidence):
            raise ValueError(
                "AE artifact export/transform audit evidence contains "
                f"sensitive {label}."
            )


def write_audit_evidence(output_path: Path, evidence: dict[str, Any]) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    assert_evidence_redacted(serialized, os.environ)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(f"{serialized}\n", encoding="utf-8")


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        token_groups = grouped_token_status(evidence["source_tokens"])
        return (
            "ae_artifact_export_transform_boundary_audit=pass "
            f"paths={present_count(evidence['paths'])}/{len(evidence['paths'])} "
            f"token_groups={present_count_bool(token_groups)}/{len(token_groups)} "
            f"gaps_ready={gap_ready_count(evidence['planned_gaps'])}/"
            f"{len(evidence['planned_gaps'])} "
            f"next={next_planned_slice(evidence['planned_gaps'])}"
        )
    failed_checks = ",".join(
        key for key, value in evidence["checks"].items() if value is not True
    )
    return f"ae_artifact_export_transform_boundary_audit=fail checks={failed_checks}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit the AE artifact export/transform runtime boundary."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence = run_ae_artifact_export_transform_boundary_audit()
        if args.output:
            write_audit_evidence(args.output, evidence)
        print(
            summary_line(evidence)
            if args.summary
            else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
        )
        return 0 if evidence["status"] == "PASS" else 1
    except ValueError as exc:
        print(
            "ae_artifact_export_transform_boundary_audit=fail "
            f"error={exc.__class__.__name__}"
        )
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
