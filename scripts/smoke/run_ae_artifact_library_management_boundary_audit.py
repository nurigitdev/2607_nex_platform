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
SCHEMA_VERSION = "ae_artifact_library_management_boundary_audit.v1"

PROTECTED_ENV_KEYS = (
    "NEX_AE_DATABASE_URL",
    "NEX_AE_TEST_DATABASE_URL",
    "NEX_AE_ARTIFACT_STORAGE_ROOT",
    "NEX_AG_AE_ARTIFACT_SERVICE_TOKEN",
    "NEX_SERVICE_TOKEN",
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


AE_API_ARTIFACTS = ROOT / "services" / "nex-ae-api" / "nex_ae_api" / "artifacts.py"
AE_API_README = ROOT / "services" / "nex-ae-api" / "README.md"
AE_WEB_MAIN = ROOT / "apps" / "nex-ae-web" / "src" / "main.js"
AE_WEB_ARTIFACT_CLIENT = ROOT / "apps" / "nex-ae-web" / "src" / "artifactClient.js"
AE_WEB_ARTIFACT_CARD_MODEL = (
    ROOT / "apps" / "nex-ae-web" / "src" / "artifactCardReadModel.js"
)
AE_WEB_EXPORT_RESULT_MODEL = (
    ROOT / "apps" / "nex-ae-web" / "src" / "artifactExportResultReadModel.js"
)
AE_WEB_DOWNLOAD_SELECTOR = (
    ROOT / "apps" / "nex-ae-web" / "src" / "artifactDownloadFormatSelector.js"
)
AE_WEB_README = ROOT / "apps" / "nex-ae-web" / "README.md"
AG_ARTIFACT_OPERATIONS = ROOT / "services" / "nex-ag" / "nex_ag" / "artifact_operations.py"
QUALITY_GATE = ROOT / "scripts" / "quality" / "run_quality_gate.sh"
SLICE_0409_DOC = (
    ROOT / "docs" / "slices" / "0409_ag_artifact_operations_read_model_foundation.md"
)
SLICE_0430_DOC = (
    ROOT / "docs" / "slices" / "0430_s43_ae_artifact_export_transform_closure.md"
)
SLICE_0440_DOC = (
    ROOT / "docs" / "slices" / "0440_s44_ae_web_artifact_delivery_closure.md"
)

REQUIRED_PATHS = (
    RequiredPath("ae_api_artifacts", AE_API_ARTIFACTS, "AE artifact system of record."),
    RequiredPath("ae_api_readme", AE_API_README, "AE API artifact boundary notes."),
    RequiredPath("ae_web_main", AE_WEB_MAIN, "AE Web artifact workspace surface."),
    RequiredPath(
        "ae_web_artifact_client",
        AE_WEB_ARTIFACT_CLIENT,
        "AE Web artifact fetch/mock client.",
    ),
    RequiredPath(
        "ae_web_artifact_card_model",
        AE_WEB_ARTIFACT_CARD_MODEL,
        "Browser-safe artifact card read-model.",
    ),
    RequiredPath(
        "ae_web_export_result_model",
        AE_WEB_EXPORT_RESULT_MODEL,
        "Browser-safe artifact export result read-model.",
    ),
    RequiredPath(
        "ae_web_download_selector",
        AE_WEB_DOWNLOAD_SELECTOR,
        "Browser-safe artifact format selector.",
    ),
    RequiredPath("ae_web_readme", AE_WEB_README, "AE Web artifact surface notes."),
    RequiredPath(
        "ag_artifact_operations",
        AG_ARTIFACT_OPERATIONS,
        "AG artifact operations detail projection.",
    ),
    RequiredPath("quality_gate", QUALITY_GATE, "Default regression gate."),
    RequiredPath("slice_0409_doc", SLICE_0409_DOC, "AG artifact operations baseline."),
    RequiredPath("slice_0430_doc", SLICE_0430_DOC, "Export/transform closure baseline."),
    RequiredPath("slice_0440_doc", SLICE_0440_DOC, "Delivery closure baseline."),
)

REQUIRED_SOURCE_TOKENS = (
    TokenRequirement(
        "api_metadata_boundary",
        AE_API_ARTIFACTS,
        "sqlalchemy_artifact_store",
        "class SqlAlchemyArtifactRecordStore",
        "Persisted artifact metadata is behind the AE store boundary.",
    ),
    TokenRequirement(
        "api_metadata_boundary",
        AE_API_ARTIFACTS,
        "artifact_detail_route",
        '@app.get("/api/v1/artifacts/{artifact_id}"',
        "AE API exposes artifact detail before list APIs are added.",
    ),
    TokenRequirement(
        "api_metadata_boundary",
        AE_API_ARTIFACTS,
        "owner_scope_column",
        "owner_user_id",
        "Artifact metadata carries owner scope for future collection filters.",
    ),
    TokenRequirement(
        "api_metadata_boundary",
        AE_API_ARTIFACTS,
        "route_link_only",
        '"link_route": f"/api/v1/artifact-files/{artifact_file_id}/{link_type}"',
        "Clients receive route metadata instead of storage paths.",
    ),
    TokenRequirement(
        "web_management_boundary",
        AE_WEB_ARTIFACT_CLIENT,
        "artifact_client_schema",
        "AE_WEB_ARTIFACT_CLIENT_SCHEMA_VERSION",
        "Browser calls artifact APIs through a tested client boundary.",
    ),
    TokenRequirement(
        "web_management_boundary",
        AE_WEB_ARTIFACT_CARD_MODEL,
        "artifact_card_schema",
        "AE_WEB_ARTIFACT_CARD_READ_MODEL_SCHEMA_VERSION",
        "Artifact card state is normalized before rendering.",
    ),
    TokenRequirement(
        "web_management_boundary",
        AE_WEB_EXPORT_RESULT_MODEL,
        "export_result_schema",
        "AE_WEB_ARTIFACT_EXPORT_RESULT_READ_MODEL_SCHEMA_VERSION",
        "Export status is summarized without download payloads.",
    ),
    TokenRequirement(
        "web_management_boundary",
        AE_WEB_DOWNLOAD_SELECTOR,
        "download_selector_schema",
        "AE_WEB_ARTIFACT_DOWNLOAD_FORMAT_SELECTOR_SCHEMA_VERSION",
        "Format selection stays inside browser-safe metadata.",
    ),
    TokenRequirement(
        "operator_boundary",
        AG_ARTIFACT_OPERATIONS,
        "ag_detail_projection_schema",
        "AG_ARTIFACT_OPERATION_DETAIL_PROJECTION_SCHEMA_VERSION",
        "AG already owns operator-facing artifact detail projection.",
    ),
    TokenRequirement(
        "operator_boundary",
        AG_ARTIFACT_OPERATIONS,
        "ag_ae_client_boundary",
        "class HttpAeArtifactOperationsClient",
        "AG reads AE artifact metadata through an AE client boundary.",
    ),
    TokenRequirement(
        "redaction_boundary",
        AG_ARTIFACT_OPERATIONS,
        "private_data_guard",
        "AG artifact operation projection contains private data.",
        "AG artifact projections have a private-data guard.",
    ),
    TokenRequirement(
        "redaction_boundary",
        AE_WEB_MAIN,
        "escape_html",
        "function escapeHtml",
        "Browser rendering escapes artifact display text.",
    ),
)

PLANNED_GAPS = (
    PlannedGap(
        "artifact_collection_store_query",
        AE_API_ARTIFACTS,
        "def list_artifacts",
        "Slice_0442",
        "Add owner-scoped artifact collection query/read-model support.",
    ),
    PlannedGap(
        "artifact_collection_item_builder",
        AE_API_ARTIFACTS,
        "build_artifact_collection_item",
        "Slice_0442",
        "Normalize list rows into payload-safe collection items.",
    ),
    PlannedGap(
        "artifact_collection_api_route",
        AE_API_ARTIFACTS,
        '@app.get("/api/v1/artifacts"',
        "Slice_0443",
        "Expose an authenticated artifact collection route.",
    ),
    PlannedGap(
        "artifact_library_web_panel",
        AE_WEB_MAIN,
        "artifactLibrary",
        "Slice_0446",
        "Add the browser artifact library panel after API wiring.",
    ),
    PlannedGap(
        "artifact_operations_collection",
        AG_ARTIFACT_OPERATIONS,
        "AG_ARTIFACT_OPERATION_COLLECTION_PROJECTION_SCHEMA_VERSION",
        "Slice_0449",
        "Add AG artifact collection operations after AE collection stabilizes.",
    ),
)

SENSITIVE_PATTERNS = (
    re.compile(r"postgresql\+?[^\"'\s]+", re.IGNORECASE),
    re.compile(r"nuri1004", re.IGNORECASE),
    re.compile(r"/data/nex-platform", re.IGNORECASE),
    re.compile(r"ed6@c496em", re.IGNORECASE),
    re.compile(r"service-token-[\w-]+", re.IGNORECASE),
)


def run_ae_artifact_library_management_boundary_audit(
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
        "api_metadata_boundary_present": group_status.get("api_metadata_boundary")
        is True,
        "web_management_boundary_present": group_status.get("web_management_boundary")
        is True,
        "operator_boundary_present": group_status.get("operator_boundary") is True,
        "redaction_boundary_present": group_status.get("redaction_boundary") is True,
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
        "slice": "0441",
        "surface": "S45 AE artifact library and operations",
        "decisions": {
            "artifact_system_of_record": "nex-ae-api",
            "browser_library_owner": "nex-ae-web",
            "operator_projection_owner": "nex-ag",
            "collection_scope": "tenant_workspace_owner",
            "collection_payload_policy": "metadata_only_no_rendered_payloads",
            "storage_path_policy": "never_expose_storage_paths_or_storage_roots",
            "postgres_smoke_target": "nex_ae_test_for_protected_s45_smokes",
        },
        "paths": paths,
        "source_tokens": tokens,
        "planned_gaps": gaps,
        "checks": checks,
        "issues": issues,
        "next_slices": ["Slice_0442", "Slice_0443", "Slice_0444"],
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
            "present": item.token in read_text(item.path),
        }
        for item in REQUIRED_SOURCE_TOKENS
    ]


def build_gap_results(root_dir: Path) -> list[dict[str, object]]:
    results = []
    for item in PLANNED_GAPS:
        present = item.token in read_text(item.path)
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
        group: all(bool(item["present"]) for item in tokens if item["group"] == group)
        for group in groups
    }


def present_count(items: list[dict[str, object]]) -> int:
    return sum(1 for item in items if item.get("present"))


def gap_ready_count(items: list[dict[str, object]]) -> int:
    return sum(1 for item in items if item.get("already_present"))


def read_text(path: Path) -> str:
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
        "next=Slice_0442"
    )
    if failing_checks:
        suffix += f" failing_checks={','.join(failing_checks)}"
    return (
        "ae_artifact_library_management_boundary_audit="
        f"{str(evidence['status']).lower()} {suffix}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit the S45 AE artifact library and operations boundary."
    )
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    try:
        evidence = run_ae_artifact_library_management_boundary_audit(os.environ)
        if args.output:
            write_audit_evidence(args.output, evidence)
    except Exception as exc:  # pragma: no cover - exercised by caller tests.
        print(
            "ae_artifact_library_management_boundary_audit="
            f"error error={type(exc).__name__}"
        )
        return 1

    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
