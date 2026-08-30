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
SCHEMA_VERSION = "ae_web_artifact_delivery_boundary_audit.v1"

PROTECTED_ENV_KEYS = (
    "NEX_AE_DATABASE_URL",
    "NEX_AE_TEST_DATABASE_URL",
    "NEX_AE_ARTIFACT_STORAGE_ROOT",
    "NEX_SERVICE_TOKEN",
    "NEX_AE_TO_CX_SERVICE_TOKEN",
)

SENSITIVE_PATTERNS = (
    (
        re.compile(r"postgresql(?:\+\w+)?://[^\"'\s]+", re.IGNORECASE),
        "database_url",
    ),
    (re.compile(r"nuri1004", re.IGNORECASE), "database_password"),
    (re.compile(r"/data/nex-platform", re.IGNORECASE), "local_data_path"),
    (
        re.compile(
            r"(?:api[_-]?key|authorization)[=:\"]\s*[^\"'\s,}]+",
            re.IGNORECASE,
        ),
        "credential_value",
    ),
    (re.compile(r"service-token-[\w-]+", re.IGNORECASE), "service_token"),
    (re.compile(r"JVBERi0xLjQKJQ=="), "sample_base64_payload"),
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
class PlannedDeliveryGap:
    name: str
    path: Path
    token: str
    planned_slice: str
    purpose: str


AE_WEB_ARTIFACT_CLIENT = ROOT / "apps" / "nex-ae-web" / "src" / "artifactClient.js"
AE_WEB_PREVIEW_PANEL = (
    ROOT / "apps" / "nex-ae-web" / "src" / "artifactPreviewPanel.js"
)
AE_WEB_MAIN = ROOT / "apps" / "nex-ae-web" / "src" / "main.js"
AE_WEB_INDEX = ROOT / "apps" / "nex-ae-web" / "index.html"
AE_WEB_FETCH_SMOKE = (
    ROOT / "apps" / "nex-ae-web" / "scripts" / "runArtifactFetchModeSmoke.mjs"
)
AE_WEB_PLAYWRIGHT_SMOKE = (
    ROOT / "apps" / "nex-ae-web" / "scripts" / "runArtifactPlaywrightSmoke.mjs"
)
AE_WEB_README = ROOT / "apps" / "nex-ae-web" / "README.md"
QUALITY_GATE = ROOT / "scripts" / "quality" / "run_quality_gate.sh"
DOCS_README = ROOT / "docs" / "README.md"
SLICE_0427_DOC = (
    ROOT / "docs" / "slices" / "0427_ae_web_binary_artifact_download_surface.md"
)
SLICE_0428_DOC = (
    ROOT / "docs" / "slices" / "0428_ae_web_export_fetch_mode_smoke_hardening.md"
)
SLICE_0430_DOC = (
    ROOT / "docs" / "slices" / "0430_s43_ae_artifact_export_transform_closure.md"
)
SLICE_0431_DOC = (
    ROOT / "docs" / "slices" / "0431_ae_web_artifact_delivery_boundary_audit.md"
)

REQUIRED_PATHS = (
    RequiredPath(
        "ae_web_artifact_client",
        AE_WEB_ARTIFACT_CLIENT,
        "Browser artifact client owns normalized download payloads.",
    ),
    RequiredPath(
        "ae_web_preview_panel",
        AE_WEB_PREVIEW_PANEL,
        "Preview/download panel owns metadata-only rendering.",
    ),
    RequiredPath(
        "ae_web_main",
        AE_WEB_MAIN,
        "AE Web action wiring currently requests preview/download surfaces.",
    ),
    RequiredPath(
        "ae_web_index",
        AE_WEB_INDEX,
        "Static shell contains artifact preview/download anchors.",
    ),
    RequiredPath(
        "ae_web_fetch_smoke",
        AE_WEB_FETCH_SMOKE,
        "Deterministic fake-fetch smoke covers export binary downloads.",
    ),
    RequiredPath(
        "ae_web_playwright_smoke",
        AE_WEB_PLAYWRIGHT_SMOKE,
        "Protected browser smoke covers artifact fetch/download boundaries.",
    ),
    RequiredPath("ae_web_readme", AE_WEB_README, "AE Web artifact notes."),
    RequiredPath("quality_gate", QUALITY_GATE, "Default regression hook."),
    RequiredPath("docs_readme", DOCS_README, "Slice index."),
    RequiredPath("slice_0427_doc", SLICE_0427_DOC, "Binary download baseline."),
    RequiredPath("slice_0428_doc", SLICE_0428_DOC, "Fetch-mode export baseline."),
    RequiredPath("slice_0430_doc", SLICE_0430_DOC, "S43 closure baseline."),
    RequiredPath("slice_0431_doc", SLICE_0431_DOC, "This boundary audit record."),
)

REQUIRED_SOURCE_TOKENS = (
    TokenRequirement(
        "normalized_download_payload",
        AE_WEB_ARTIFACT_CLIENT,
        "download_payload_kind",
        "downloadPayloadKind",
        "Artifact client separates text and base64 download payloads.",
    ),
    TokenRequirement(
        "normalized_download_payload",
        AE_WEB_ARTIFACT_CLIENT,
        "base64_payload_surface",
        "contentBase64",
        "Base64 bytes are held only in the normalized download surface.",
    ),
    TokenRequirement(
        "normalized_download_payload",
        AE_WEB_ARTIFACT_CLIENT,
        "content_encoding",
        "contentEncoding",
        "Download surfaces expose explicit encoding metadata.",
    ),
    TokenRequirement(
        "normalized_download_payload",
        AE_WEB_ARTIFACT_CLIENT,
        "encoded_content_length",
        "encodedContentLength",
        "Base64 payloads report encoded and decoded lengths separately.",
    ),
    TokenRequirement(
        "metadata_only_panel",
        AE_WEB_PREVIEW_PANEL,
        "download_panel_builder",
        "buildArtifactPreviewPanelStateFromDownload",
        "Panel state is derived from download surfaces without raw bytes.",
    ),
    TokenRequirement(
        "metadata_only_panel",
        AE_WEB_PREVIEW_PANEL,
        "downloaded_content_render_guard",
        "downloadedContentRendered: false",
        "Rendered panel metadata explicitly refuses downloaded content.",
    ),
    TokenRequirement(
        "metadata_only_panel",
        AE_WEB_PREVIEW_PANEL,
        "download_payload_summary",
        "download_payload_kind",
        "Panel summary exposes payload kind metadata only.",
    ),
    TokenRequirement(
        "browser_action_boundary",
        AE_WEB_MAIN,
        "download_action_function",
        "async function submitArtifactDownloadAction",
        "Browser download clicks route through a dedicated action function.",
    ),
    TokenRequirement(
        "browser_action_boundary",
        AE_WEB_MAIN,
        "download_surface_fetch",
        "downloadArtifactFile",
        "Browser action fetches the normalized artifact download surface.",
    ),
    TokenRequirement(
        "browser_action_boundary",
        AE_WEB_MAIN,
        "download_panel_state",
        "buildArtifactPreviewPanelStateFromDownload",
        "Browser action updates metadata-only panel state after download fetch.",
    ),
    TokenRequirement(
        "smoke_evidence_boundary",
        AE_WEB_FETCH_SMOKE,
        "binary_panel_redaction_check",
        "binary_download_panel_metadata_only",
        "Fetch-mode evidence rejects raw base64 payloads.",
    ),
    TokenRequirement(
        "smoke_evidence_boundary",
        AE_WEB_FETCH_SMOKE,
        "no_live_postgres_fetch_smoke",
        "postgresql_not_used",
        "Default fetch-mode browser evidence remains PostgreSQL-free.",
    ),
    TokenRequirement(
        "smoke_evidence_boundary",
        AE_WEB_PLAYWRIGHT_SMOKE,
        "download_not_rendered_browser_check",
        "raw_download_retrieved_but_not_rendered",
        "Protected Playwright evidence checks raw downloads are not rendered.",
    ),
    TokenRequirement(
        "quality_gate_continuity",
        QUALITY_GATE,
        "s43_closure_still_registered",
        "run_s43_ae_artifact_export_transform_closure.py",
        "S43 export closure remains part of the default quality gate.",
    ),
    TokenRequirement(
        "quality_gate_continuity",
        DOCS_README,
        "slice_0431_indexed",
        "Slice 0431",
        "Slice index includes the delivery boundary audit.",
    ),
    TokenRequirement(
        "quality_gate_continuity",
        AE_WEB_README,
        "slice_0431_readme_note",
        "Slice 0431 audits the artifact delivery boundary",
        "AE Web README records the S44 delivery boundary decision.",
    ),
)

PLANNED_GAPS = (
    PlannedDeliveryGap(
        "browser_file_save_adapter",
        ROOT / "apps" / "nex-ae-web" / "src" / "artifactDownloadSaveAdapter.js",
        "AE_WEB_ARTIFACT_DOWNLOAD_SAVE_SCHEMA_VERSION",
        "Slice_0432",
        "Create the only browser module that may materialize download bytes.",
    ),
    PlannedDeliveryGap(
        "download_action_save_wiring",
        AE_WEB_MAIN,
        "saveArtifactDownload",
        "Slice_0433",
        "Wire successful download surfaces to the browser save adapter.",
    ),
    PlannedDeliveryGap(
        "export_result_delivery_read_model",
        AE_WEB_MAIN,
        "artifactExportResult",
        "Slice_0434",
        "Expose export result/download readiness without raw content.",
    ),
    PlannedDeliveryGap(
        "download_playwright_evidence",
        AE_WEB_PLAYWRIGHT_SMOKE,
        "browser_file_save_prepared",
        "Slice_0435",
        "Prove download materialization in protected browser evidence.",
    ),
)


def run_ae_web_artifact_delivery_boundary_audit(
    env: Mapping[str, str] | None = None,
    *,
    root_dir: Path = ROOT,
) -> dict[str, Any]:
    env = env or os.environ
    paths = build_path_results(root_dir)
    tokens = build_token_results(root_dir)
    gaps = build_gap_results(root_dir)
    group_status = grouped_token_status(tokens)
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "normalized_download_payload_present": group_status.get(
            "normalized_download_payload"
        )
        is True,
        "metadata_only_panel_present": group_status.get("metadata_only_panel")
        is True,
        "browser_action_boundary_present": group_status.get(
            "browser_action_boundary"
        )
        is True,
        "smoke_evidence_boundary_present": group_status.get(
            "smoke_evidence_boundary"
        )
        is True,
        "quality_gate_continuity_present": group_status.get(
            "quality_gate_continuity"
        )
        is True,
        "planned_delivery_gaps_non_blocking": all(
            item["blocking"] is False for item in gaps
        ),
        "redacted_evidence_only": True,
    }
    issues = build_issues(paths, tokens)
    status = "PASS" if all(checks.values()) and not issues else "FAIL"
    evidence: dict[str, Any] = {
        "audit_schema_version": SCHEMA_VERSION,
        "status": status,
        "slice": "0431",
        "surface": "nex-ae-web artifact delivery",
        "decisions": {
            "browser_surface_owner": "nex-ae-web",
            "artifact_system_of_record": "nex-ae-api",
            "download_authorization_owner": "nex-ae-api",
            "normalized_payload_owner": "artifactClient.downloadArtifactFile",
            "file_materialization_owner": "future_browser_save_adapter",
            "panel_and_evidence_policy": "metadata_only_no_raw_download_payloads",
            "live_network_default": "disabled",
            "protected_postgres_smoke_policy": "use_nex_ae_test_only_when_enabled",
        },
        "paths": paths,
        "source_tokens": tokens,
        "planned_gaps": gaps,
        "checks": checks,
        "issues": issues,
        "next_slices": [
            "Slice_0432",
            "Slice_0433",
            "Slice_0434",
            "Slice_0435",
        ],
        "protected_env": summarize_protected_env(env),
    }
    assert_evidence_redacted(json.dumps(evidence, ensure_ascii=False), env)
    return evidence


def build_path_results(root_dir: Path) -> list[dict[str, Any]]:
    return [
        {
            "name": item.name,
            "path": relative_label(item.path, root_dir),
            "purpose": item.purpose,
            "present": path_for(root_dir, item.path).is_file(),
        }
        for item in REQUIRED_PATHS
    ]


def build_token_results(root_dir: Path) -> list[dict[str, Any]]:
    return [
        {
            "group": item.group,
            "token_id": item.token_id,
            "path": relative_label(item.path, root_dir),
            "purpose": item.purpose,
            "present": item.token in read_text(root_dir, item.path),
        }
        for item in REQUIRED_SOURCE_TOKENS
    ]


def build_gap_results(root_dir: Path) -> list[dict[str, Any]]:
    results = []
    for item in PLANNED_GAPS:
        target_text = read_text(root_dir, item.path)
        target_path = path_for(root_dir, item.path)
        results.append(
            {
                "name": item.name,
                "path": relative_label(item.path, root_dir),
                "planned_slice": item.planned_slice,
                "purpose": item.purpose,
                "already_present": target_path.exists()
                and bool(target_text)
                and item.token in target_text,
                "blocking": False,
            }
        )
    return results


def build_issues(
    paths: list[dict[str, Any]],
    tokens: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    issues.extend(
        {
            "category": "path_missing",
            "name": item["name"],
            "path": item["path"],
            "purpose": item["purpose"],
        }
        for item in paths
        if not item["present"]
    )
    issues.extend(
        {
            "category": "source_token_missing",
            "group": item["group"],
            "token_id": item["token_id"],
            "path": item["path"],
            "purpose": item["purpose"],
        }
        for item in tokens
        if not item["present"]
    )
    return issues


def summarize_protected_env(env: Mapping[str, str]) -> dict[str, bool]:
    return {key: bool(env.get(key)) for key in PROTECTED_ENV_KEYS}


def grouped_token_status(tokens: list[dict[str, Any]]) -> dict[str, bool]:
    groups = sorted({str(item["group"]) for item in tokens})
    return {
        group: all(
            bool(item["present"]) for item in tokens if item["group"] == group
        )
        for group in groups
    }


def present_count(items: list[dict[str, Any]]) -> int:
    return sum(1 for item in items if item.get("present"))


def gap_ready_count(items: list[dict[str, Any]]) -> int:
    return sum(1 for item in items if item.get("already_present"))


def next_planned_slice(gaps: list[dict[str, Any]]) -> str:
    for item in gaps:
        if not item.get("already_present"):
            return str(item["planned_slice"])
    return "complete"


def token_is_present(tokens: list[dict[str, Any]], token_id: str) -> bool:
    return any(item["token_id"] == token_id and item["present"] for item in tokens)


def path_for(root_dir: Path, path: Path) -> Path:
    try:
        return root_dir / path.relative_to(ROOT)
    except ValueError:
        return path


def read_text(root_dir: Path, path: Path) -> str:
    try:
        return path_for(root_dir, path).read_text(encoding="utf-8")
    except OSError:
        return ""


def relative_label(path: Path, root_dir: Path) -> str:
    try:
        return str(path_for(root_dir, path).relative_to(root_dir))
    except ValueError:
        return path.name


def assert_evidence_redacted(serialized: str, env: Mapping[str, str]) -> None:
    for key in PROTECTED_ENV_KEYS:
        value = env.get(key)
        if value and value in serialized:
            raise ValueError(f"Protected value leaked in evidence: {key}")
    for pattern, label in SENSITIVE_PATTERNS:
        if pattern.search(serialized):
            raise ValueError(f"Sensitive value leaked in evidence: {label}")


def write_audit_evidence(path: Path, evidence: Mapping[str, Any]) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    assert_evidence_redacted(serialized, os.environ)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{serialized}\n", encoding="utf-8")


def summary_line(evidence: Mapping[str, Any]) -> str:
    checks = evidence.get("checks", {})
    failing_checks = [
        key for key, passed in checks.items() if passed is not True
    ] if isinstance(checks, dict) else []
    suffix = (
        f"required_paths={present_count(evidence['paths'])}/{len(evidence['paths'])} "
        f"tokens={present_count(evidence['source_tokens'])}/{len(evidence['source_tokens'])} "
        f"gaps_ready={gap_ready_count(evidence['planned_gaps'])}/{len(evidence['planned_gaps'])} "
        f"next={next_planned_slice(evidence['planned_gaps'])}"
    )
    if failing_checks:
        suffix += f" failing_checks={','.join(failing_checks)}"
    return (
        "ae_web_artifact_delivery_boundary_audit="
        f"{str(evidence['status']).lower()} {suffix}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit the AE Web artifact delivery/download boundary."
    )
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence = run_ae_web_artifact_delivery_boundary_audit(os.environ)
        if args.output:
            write_audit_evidence(args.output, evidence)
    except Exception as exc:  # pragma: no cover - exercised by caller tests.
        print(f"ae_web_artifact_delivery_boundary_audit=error error={type(exc).__name__}")
        return 1

    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
