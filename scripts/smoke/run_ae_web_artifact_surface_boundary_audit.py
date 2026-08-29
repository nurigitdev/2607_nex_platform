#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "ae_web_artifact_surface_boundary_audit.v1"

PROTECTED_ENV_KEYS = (
    "NEX_AE_DATABASE_URL",
    "NEX_AE_TEST_DATABASE_URL",
    "NEX_AE_ARTIFACT_STORAGE_ROOT",
    "NEX_SERVICE_TOKEN",
    "NEX_AE_TO_CX_SERVICE_TOKEN",
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


AE_WEB_INDEX = ROOT / "apps" / "nex-ae-web" / "index.html"
AE_WEB_MAIN = ROOT / "apps" / "nex-ae-web" / "src" / "main.js"
AE_WEB_STYLES = ROOT / "apps" / "nex-ae-web" / "src" / "styles.css"
AE_WEB_REGISTRY = ROOT / "apps" / "nex-ae-web" / "src" / "clientRegistry.js"
AE_WEB_DIAGNOSTICS = ROOT / "apps" / "nex-ae-web" / "src" / "runtimeDiagnostics.js"
AE_WEB_README = ROOT / "apps" / "nex-ae-web" / "README.md"
AE_API_ARTIFACTS = ROOT / "services" / "nex-ae-api" / "nex_ae_api" / "artifacts.py"
AE_API_CHAT = ROOT / "services" / "nex-ae-api" / "nex_ae_api" / "chat.py"
QUALITY_GATE = ROOT / "scripts" / "quality" / "run_quality_gate.sh"
SLICE_0045_DOC = ROOT / "docs" / "slices" / "0045_ae_web_artifact_card_integration.md"
SLICE_0401_DOC = (
    ROOT / "docs" / "slices" / "0401_ae_artifact_runtime_persistence_storage_boundary_audit.md"
)
SLICE_0410_DOC = ROOT / "docs" / "slices" / "0410_s41_artifact_runtime_closure.md"

REQUIRED_PATHS = (
    RequiredPath("ae_web_index", AE_WEB_INDEX, "AE Web static shell."),
    RequiredPath("ae_web_main", AE_WEB_MAIN, "Current AE Web workspace logic."),
    RequiredPath("ae_web_styles", AE_WEB_STYLES, "Current artifact card styles."),
    RequiredPath("ae_web_registry", AE_WEB_REGISTRY, "Runtime client composition."),
    RequiredPath("ae_web_diagnostics", AE_WEB_DIAGNOSTICS, "Safe runtime diagnostics."),
    RequiredPath("ae_web_readme", AE_WEB_README, "AE Web slice notes."),
    RequiredPath("ae_api_artifacts", AE_API_ARTIFACTS, "Persisted artifact API source."),
    RequiredPath("ae_api_chat", AE_API_CHAT, "Persisted chat artifact refs source."),
    RequiredPath("quality_gate", QUALITY_GATE, "Default regression gate."),
    RequiredPath("slice_0045_doc", SLICE_0045_DOC, "Legacy AE Web artifact card baseline."),
    RequiredPath("slice_0401_doc", SLICE_0401_DOC, "S41 artifact runtime boundary."),
    RequiredPath("slice_0410_doc", SLICE_0410_DOC, "S41 artifact runtime closure."),
)

REQUIRED_SOURCE_TOKENS = (
    TokenRequirement(
        "current_web_surface",
        AE_WEB_INDEX,
        "artifact_panel_anchor",
        'id="artifact-panel"',
        "Static shell keeps a visible artifact panel anchor.",
    ),
    TokenRequirement(
        "current_web_surface",
        AE_WEB_MAIN,
        "workspace_artifact_ref_state",
        "artifactRef:",
        "Workspace state has a chat artifact ref sample.",
    ),
    TokenRequirement(
        "current_web_surface",
        AE_WEB_MAIN,
        "artifact_ref_renderer",
        "function renderArtifactRefs",
        "Chat messages already render artifact refs.",
    ),
    TokenRequirement(
        "current_web_surface",
        AE_WEB_MAIN,
        "artifact_summary_renderer",
        "function renderArtifactSummary",
        "Side panel already renders artifact handoff summary metadata.",
    ),
    TokenRequirement(
        "current_web_surface",
        AE_WEB_MAIN,
        "preview_route_metadata",
        "previewRoute",
        "Current mock data exposes preview route metadata.",
    ),
    TokenRequirement(
        "current_web_surface",
        AE_WEB_MAIN,
        "download_route_metadata",
        "downloadRoutes",
        "Current mock data exposes download route metadata.",
    ),
    TokenRequirement(
        "current_web_surface",
        AE_WEB_STYLES,
        "artifact_link_styles",
        ".artifact-link",
        "Current card class has stable CSS coverage.",
    ),
    TokenRequirement(
        "runtime_boundary",
        AE_WEB_REGISTRY,
        "client_registry_schema",
        "AE_WEB_CLIENT_REGISTRY_SCHEMA_VERSION",
        "Fetch/mock clients are composed through one registry boundary.",
    ),
    TokenRequirement(
        "runtime_boundary",
        AE_WEB_DIAGNOSTICS,
        "diagnostics_schema",
        "AE_WEB_RUNTIME_DIAGNOSTICS_SCHEMA_VERSION",
        "Browser-safe diagnostics have a stable schema.",
    ),
    TokenRequirement(
        "backend_contract_boundary",
        AE_API_ARTIFACTS,
        "artifact_record_route",
        '@app.get("/api/v1/artifacts/{artifact_id}"',
        "AE API exposes persisted artifact readback.",
    ),
    TokenRequirement(
        "backend_contract_boundary",
        AE_API_ARTIFACTS,
        "artifact_file_preview_route",
        '@app.get("/api/v1/artifact-files/{artifact_file_id}/preview"',
        "AE API exposes artifact preview route metadata.",
    ),
    TokenRequirement(
        "backend_contract_boundary",
        AE_API_ARTIFACTS,
        "artifact_file_download_route",
        '@app.get("/api/v1/artifact-files/{artifact_file_id}/download"',
        "AE API exposes artifact download route metadata.",
    ),
    TokenRequirement(
        "backend_contract_boundary",
        AE_API_CHAT,
        "chat_artifact_ref_attach",
        "attach_artifact_ref",
        "AE chat can persist artifact refs after S41.",
    ),
    TokenRequirement(
        "safety_boundary",
        AE_WEB_MAIN,
        "escape_html",
        "function escapeHtml",
        "Current inline artifact rendering escapes display data.",
    ),
    TokenRequirement(
        "safety_boundary",
        AE_WEB_DIAGNOSTICS,
        "storage_location_redacted",
        "storageLocationIncluded: false",
        "Runtime diagnostics explicitly suppress storage locations.",
    ),
)

PLANNED_GAPS = (
    PlannedGap(
        "artifact_client_adapter",
        AE_WEB_REGISTRY,
        "artifactClient",
        "Slice_0412",
        "Add mock/fetch artifact client adapters to registry.",
    ),
    PlannedGap(
        "artifact_card_read_model",
        AE_WEB_MAIN,
        "buildArtifactCardViewModel",
        "Slice_0413",
        "Move artifact ref normalization into a tested UI-safe read model.",
    ),
    PlannedGap(
        "artifact_card_renderer_module",
        AE_WEB_MAIN,
        "renderArtifactCard",
        "Slice_0414",
        "Move chat card rendering into a dedicated tested module.",
    ),
    PlannedGap(
        "artifact_preview_download_panel",
        AE_WEB_INDEX,
        "artifact-preview-panel",
        "Slice_0415",
        "Add preview/download panel UI after adapter and card model exist.",
    ),
)

SENSITIVE_PATTERNS = (
    re.compile(r"postgresql\+?[^\"'\s]+", re.IGNORECASE),
    re.compile(r"nuri1004", re.IGNORECASE),
    re.compile(r"/data/nex-platform", re.IGNORECASE),
    re.compile(r"ed6@c496em", re.IGNORECASE),
    re.compile(r"service-token-[\w-]+", re.IGNORECASE),
)


def run_ae_web_artifact_surface_boundary_audit(
    env: Mapping[str, str] | None = None,
    *,
    root_dir: Path = ROOT,
) -> dict[str, object]:
    env = env or os.environ
    paths = build_path_results(root_dir)
    tokens = build_token_results(root_dir)
    gaps = build_gap_results(root_dir)
    group_status = grouped_token_status(tokens)
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "current_web_surface_present": group_status.get("current_web_surface") is True,
        "runtime_boundary_present": group_status.get("runtime_boundary") is True,
        "backend_contract_boundary_present": group_status.get(
            "backend_contract_boundary"
        )
        is True,
        "safety_boundary_present": group_status.get("safety_boundary") is True,
        "planned_gaps_non_blocking": all(item["blocking"] is False for item in gaps),
        "redacted_evidence_only": True,
    }
    issues = []
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
    status = "PASS" if all(checks.values()) and not issues else "FAIL"
    evidence: dict[str, object] = {
        "audit_schema_version": SCHEMA_VERSION,
        "status": status,
        "slice": "0411",
        "surface": "nex-ae-web artifact experience",
        "decisions": {
            "browser_surface_owner": "nex-ae-web",
            "artifact_system_of_record": "nex-ae-api",
            "current_web_surface": "mock_inline_artifact_refs",
            "target_web_surface": "client_adapter_read_model_card_preview_panel",
            "storage_path_policy": "never_render_storage_paths_in_browser",
            "live_network_default": "disabled",
        },
        "paths": paths,
        "source_tokens": tokens,
        "planned_gaps": gaps,
        "checks": checks,
        "issues": issues,
        "next_slices": ["Slice_0412", "Slice_0413", "Slice_0414", "Slice_0415"],
        "protected_env": summarize_protected_env(env),
    }
    assert_evidence_redacted(json.dumps(evidence, ensure_ascii=False), env)
    return evidence


def build_path_results(root_dir: Path) -> list[dict[str, object]]:
    return [
        {
            "name": item.name,
            "path": relative_label(item.path, root_dir),
            "purpose": item.purpose,
            "present": item.path.exists(),
        }
        for item in REQUIRED_PATHS
    ]


def build_token_results(root_dir: Path) -> list[dict[str, object]]:
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


def build_gap_results(root_dir: Path) -> list[dict[str, object]]:
    results = []
    for item in PLANNED_GAPS:
        present = item.token in read_text(root_dir, item.path)
        results.append(
            {
                "name": item.name,
                "path": relative_label(item.path, root_dir),
                "planned_slice": item.planned_slice,
                "purpose": item.purpose,
                "already_present": present,
                "blocking": False,
            }
        )
    return results


def summarize_protected_env(env: Mapping[str, str]) -> dict[str, bool]:
    return {key: bool(env.get(key)) for key in PROTECTED_ENV_KEYS}


def grouped_token_status(tokens: list[dict[str, object]]) -> dict[str, bool]:
    groups = sorted({str(item["group"]) for item in tokens})
    return {
        group: all(
            bool(item["present"]) for item in tokens if item["group"] == group
        )
        for group in groups
    }


def present_count(items: list[dict[str, object]]) -> int:
    return sum(1 for item in items if item.get("present"))


def gap_ready_count(items: list[dict[str, object]]) -> int:
    return sum(1 for item in items if item.get("already_present"))


def read_text(root_dir: Path, path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def relative_label(path: Path, root_dir: Path) -> str:
    try:
        return str(path.relative_to(root_dir))
    except ValueError:
        return path.name


def assert_evidence_redacted(serialized: str, env: Mapping[str, str]) -> None:
    for key in PROTECTED_ENV_KEYS:
        value = env.get(key)
        if value and value in serialized:
            raise ValueError(f"Protected value leaked in evidence: {key}")
    for pattern in SENSITIVE_PATTERNS:
        if pattern.search(serialized):
            raise ValueError("Sensitive value leaked in evidence.")


def write_audit_evidence(path: Path, evidence: Mapping[str, object]) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    assert_evidence_redacted(serialized, os.environ)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{serialized}\n", encoding="utf-8")


def summary_line(evidence: Mapping[str, object]) -> str:
    checks = evidence.get("checks", {})
    failing_checks = [
        key for key, passed in checks.items() if passed is not True
    ] if isinstance(checks, dict) else []
    suffix = (
        f"required_paths={present_count(evidence['paths'])}/{len(evidence['paths'])} "
        f"tokens={present_count(evidence['source_tokens'])}/{len(evidence['source_tokens'])} "
        f"gaps_ready={gap_ready_count(evidence['planned_gaps'])}/{len(evidence['planned_gaps'])} "
        f"next=Slice_0412"
    )
    if failing_checks:
        suffix += f" failing_checks={','.join(failing_checks)}"
    return (
        "ae_web_artifact_surface_boundary_audit="
        f"{str(evidence['status']).lower()} {suffix}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit the AE Web artifact surface before persisted client wiring."
    )
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    try:
        evidence = run_ae_web_artifact_surface_boundary_audit(os.environ)
        if args.output:
            write_audit_evidence(args.output, evidence)
    except Exception as exc:  # pragma: no cover - exercised by caller tests.
        print(f"ae_web_artifact_surface_boundary_audit=error error={type(exc).__name__}")
        return 1

    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
