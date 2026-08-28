#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "ae_artifact_runtime_persistence_storage_boundary_audit.v1"

PROTECTED_ENV_KEYS = (
    "NEX_AE_DATABASE_URL",
    "NEX_AE_TEST_DATABASE_URL",
    "NEX_DATA_ROOT",
    "NEX_AE_ARTIFACT_STORAGE_ROOT",
    "NEX_AE_TO_CX_SERVICE_TOKEN",
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


AE_ARTIFACTS = ROOT / "services" / "nex-ae-api" / "nex_ae_api" / "artifacts.py"
AE_MAIN = ROOT / "services" / "nex-ae-api" / "nex_ae_api" / "main.py"
AE_README = ROOT / "services" / "nex-ae-api" / "README.md"
AE_WEB_MAIN = ROOT / "apps" / "nex-ae-web" / "src" / "main.js"
AE_WEB_README = ROOT / "apps" / "nex-ae-web" / "README.md"
QUALITY_GATE = ROOT / "scripts" / "quality" / "run_quality_gate.sh"
AE_MIGRATIONS = ROOT / "database" / "nex-ae-api" / "migrations"
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
ARTIFACT_READY_EXAMPLE = (
    ROOT
    / "contracts"
    / "examples"
    / "generation"
    / "ae_artifact_record.markdown_file_ready.json"
)
ARTIFACT_STORAGE_LEAK_NEGATIVE = (
    ROOT
    / "contracts"
    / "tests"
    / "negative"
    / "generation"
    / "ae_artifact_record.storage_path_leak.json"
)
SLICE_0041_DOC = (
    ROOT / "docs" / "slices" / "0041_ae_artifact_record_family_foundation.md"
)
SLICE_0042_DOC = (
    ROOT / "docs" / "slices" / "0042_ae_markdown_artifact_renderer_mvp.md"
)
SLICE_0043_DOC = (
    ROOT / "docs" / "slices" / "0043_ae_artifact_file_preview_download_metadata.md"
)
SLICE_0044_DOC = (
    ROOT / "docs" / "slices" / "0044_ae_chat_artifact_link_contract.md"
)
SLICE_0045_DOC = (
    ROOT / "docs" / "slices" / "0045_ae_web_artifact_card_integration.md"
)

REQUIRED_PATHS = (
    RequiredPath("ae_artifacts", AE_ARTIFACTS, "AE artifact route/runtime module."),
    RequiredPath("ae_main", AE_MAIN, "AE artifact route registration boundary."),
    RequiredPath("ae_readme", AE_README, "AE API artifact boundary documentation."),
    RequiredPath("ae_web_main", AE_WEB_MAIN, "AE Web artifact reference surface."),
    RequiredPath("ae_web_readme", AE_WEB_README, "AE Web boundary documentation."),
    RequiredPath("quality_gate", QUALITY_GATE, "Default regression audit hook."),
    RequiredPath("ae_migrations", AE_MIGRATIONS, "AE PostgreSQL migration root."),
    RequiredPath(
        "artifact_record_schema",
        ARTIFACT_RECORD_SCHEMA,
        "Artifact record contract schema.",
    ),
    RequiredPath(
        "artifact_handoff_schema",
        ARTIFACT_HANDOFF_SCHEMA,
        "Artifact handoff contract schema.",
    ),
    RequiredPath(
        "artifact_ready_example",
        ARTIFACT_READY_EXAMPLE,
        "Rendered artifact file/link example.",
    ),
    RequiredPath(
        "artifact_storage_leak_negative",
        ARTIFACT_STORAGE_LEAK_NEGATIVE,
        "Storage path leak negative contract fixture.",
    ),
    RequiredPath("slice_0041_doc", SLICE_0041_DOC, "Artifact record decision."),
    RequiredPath("slice_0042_doc", SLICE_0042_DOC, "Markdown renderer decision."),
    RequiredPath("slice_0043_doc", SLICE_0043_DOC, "Preview/download decision."),
    RequiredPath("slice_0044_doc", SLICE_0044_DOC, "Chat artifact link decision."),
    RequiredPath("slice_0045_doc", SLICE_0045_DOC, "AE Web artifact card decision."),
)

REQUIRED_SOURCE_TOKENS = (
    TokenRequirement(
        "artifact_route_surface",
        AE_ARTIFACTS,
        "route_registration",
        "register_artifact_handoff_routes",
        "Artifact routes are registered behind a single AE API boundary.",
    ),
    TokenRequirement(
        "artifact_route_surface",
        AE_ARTIFACTS,
        "artifact_create_route",
        '@app.post("/api/v1/artifacts"',
        "AE API exposes artifact shell creation.",
    ),
    TokenRequirement(
        "artifact_route_surface",
        AE_ARTIFACTS,
        "render_job_route",
        '@app.post("/api/v1/artifacts/{artifact_id}/render-jobs"',
        "AE API exposes artifact render job creation.",
    ),
    TokenRequirement(
        "artifact_route_surface",
        AE_ARTIFACTS,
        "preview_route",
        '@app.get("/api/v1/artifact-files/{artifact_file_id}/preview"',
        "AE API exposes owner-checked preview payloads.",
    ),
    TokenRequirement(
        "artifact_route_surface",
        AE_ARTIFACTS,
        "download_route",
        '@app.get("/api/v1/artifact-files/{artifact_file_id}/download"',
        "AE API exposes owner-checked download payloads.",
    ),
    TokenRequirement(
        "runtime_memory_boundary",
        AE_ARTIFACTS,
        "record_store_class",
        "class ArtifactRecordStore",
        "Current artifact runtime persistence is isolated in a store object.",
    ),
    TokenRequirement(
        "runtime_memory_boundary",
        AE_ARTIFACTS,
        "in_memory_records",
        "records: dict[str, dict[str, Any]]",
        "Artifact records are currently in-memory.",
    ),
    TokenRequirement(
        "runtime_memory_boundary",
        AE_ARTIFACTS,
        "in_memory_markdown_payload",
        "rendered_markdown: dict[str, str]",
        "Rendered Markdown payloads are currently in-memory.",
    ),
    TokenRequirement(
        "runtime_memory_boundary",
        AE_ARTIFACTS,
        "default_store",
        "DEFAULT_ARTIFACT_RECORD_STORE",
        "The default runtime store is process-local.",
    ),
    TokenRequirement(
        "safe_metadata_boundary",
        AE_ARTIFACTS,
        "artifact_storage_ref_scheme",
        "ae://artifacts/",
        "Public metadata uses logical AE storage refs, not local paths.",
    ),
    TokenRequirement(
        "safe_metadata_boundary",
        AE_ARTIFACTS,
        "artifact_hashes",
        "file_hash",
        "Artifact file payloads carry hashes for durable storage verification.",
    ),
    TokenRequirement(
        "safe_metadata_boundary",
        AE_ARTIFACTS,
        "owner_only_links",
        '"access_policy": "owner_only"',
        "Preview/download links remain owner-scoped.",
    ),
    TokenRequirement(
        "safe_metadata_boundary",
        AE_ARTIFACTS,
        "link_route_only",
        '"link_route": f"/api/v1/artifact-files/{artifact_file_id}/{link_type}"',
        "Clients receive AE route links, not filesystem/object-storage paths.",
    ),
    TokenRequirement(
        "auth_redaction_boundary",
        AE_ARTIFACTS,
        "authorize_request",
        "validate_authorization_header",
        "Artifact routes require AE service/browser auth checks.",
    ),
    TokenRequirement(
        "auth_redaction_boundary",
        AE_ARTIFACTS,
        "problem_response",
        "problem_response(",
        "Artifact route failures use the shared safe problem envelope.",
    ),
    TokenRequirement(
        "contract_boundary",
        ARTIFACT_RECORD_SCHEMA,
        "record_schema",
        "ae_artifact_record.v1",
        "Artifact record contract remains versioned.",
    ),
    TokenRequirement(
        "contract_boundary",
        ARTIFACT_RECORD_SCHEMA,
        "storage_ref_contract",
        "storage_ref",
        "Artifact file metadata includes logical storage references.",
    ),
    TokenRequirement(
        "contract_boundary",
        ARTIFACT_READY_EXAMPLE,
        "ready_file_example",
        '"storage_ref": "ae://artifacts/',
        "Ready artifact examples use logical storage references.",
    ),
    TokenRequirement(
        "contract_boundary",
        ARTIFACT_STORAGE_LEAK_NEGATIVE,
        "storage_path_negative",
        "/data/nex-platform",
        "Contract tests still reject local storage path leakage.",
    ),
    TokenRequirement(
        "web_artifact_surface",
        AE_WEB_MAIN,
        "artifact_ref_renderer",
        "renderArtifactRef",
        "AE Web renders artifact references through a bounded helper.",
    ),
    TokenRequirement(
        "web_artifact_surface",
        AE_WEB_MAIN,
        "preview_route_anchor",
        "previewRoute",
        "AE Web mock state already carries preview routes.",
    ),
    TokenRequirement(
        "web_artifact_surface",
        AE_WEB_MAIN,
        "download_route_anchor",
        "downloadRoutes",
        "AE Web mock state already carries download routes.",
    ),
    TokenRequirement(
        "web_artifact_surface",
        AE_WEB_MAIN,
        "artifact_panel_anchor",
        "renderArtifactSummary",
        "AE Web already has an artifact side-panel surface.",
    ),
    TokenRequirement(
        "prior_slice_decisions",
        SLICE_0041_DOC,
        "artifact_family_foundation",
        "AE-owned artifact record family",
        "Slice 0041 captured the initial artifact record decision.",
    ),
    TokenRequirement(
        "prior_slice_decisions",
        SLICE_0042_DOC,
        "markdown_renderer_foundation",
        "synchronous AE render path",
        "Slice 0042 captured the Markdown renderer decision.",
    ),
    TokenRequirement(
        "prior_slice_decisions",
        SLICE_0043_DOC,
        "preview_download_foundation",
        "preview and download metadata",
        "Slice 0043 captured the preview/download decision.",
    ),
    TokenRequirement(
        "prior_slice_decisions",
        SLICE_0044_DOC,
        "chat_artifact_link_foundation",
        "artifact_refs",
        "Slice 0044 captured the chat artifact link decision.",
    ),
    TokenRequirement(
        "prior_slice_decisions",
        SLICE_0045_DOC,
        "web_artifact_card_foundation",
        "Artifact side panel metadata",
        "Slice 0045 captured the AE Web artifact card decision.",
    ),
    TokenRequirement(
        "service_docs",
        AE_README,
        "artifact_handoff_section",
        "Artifact handoff:",
        "AE README exposes the artifact handoff boundary.",
    ),
    TokenRequirement(
        "service_docs",
        AE_README,
        "artifact_records_section",
        "Artifact records:",
        "AE README exposes the artifact record boundary.",
    ),
)

PLANNED_GAPS = (
    PlannedGap(
        "artifact_postgres_migrations",
        AE_MIGRATIONS,
        "ae_artifacts",
        "Slice 0402",
        "Add durable AE tables for handoffs, artifacts, versions, jobs, files, and links.",
    ),
    PlannedGap(
        "artifact_sqlalchemy_repository",
        AE_ARTIFACTS,
        "SqlAlchemyArtifact",
        "Slice 0403",
        "Move runtime persistence behind a SQLAlchemy repository with SQLite regression.",
    ),
    PlannedGap(
        "artifact_storage_root_adapter",
        AE_ARTIFACTS,
        "NEX_AE_ARTIFACT_STORAGE_ROOT",
        "Slice 0404",
        "Persist rendered Markdown payloads under a configured AE artifact storage root.",
    ),
    PlannedGap(
        "persisted_route_wiring",
        AE_ARTIFACTS,
        "build_default_artifact_record_store",
        "Slice 0405",
        "Wire route defaults to repository/storage adapters instead of process-local stores.",
    ),
    PlannedGap(
        "artifact_postgres_smoke",
        QUALITY_GATE,
        "run_ae_artifact_postgres_smoke.py",
        "Slice 0406",
        "Prove migration, write/read, preview/download, and cleanup against nex_ae_test.",
    ),
    PlannedGap(
        "artifact_web_client_adapter",
        AE_WEB_MAIN,
        "artifactPreviewClient",
        "Slice 0407",
        "Promote AE Web artifact links from plain anchors to safe preview/download clients.",
    ),
)


def run_ae_artifact_runtime_persistence_storage_boundary_audit(
    environ: dict[str, str] | None = None,
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
            if not item["present"]
        ],
        *[
            issue("source_token_missing", item["token_id"], item["path"])
            for item in source_tokens
            if not item["present"]
        ],
    ]
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "artifact_route_surface_present": token_groups.get("artifact_route_surface")
        is True,
        "runtime_memory_boundary_identified": token_groups.get(
            "runtime_memory_boundary"
        )
        is True,
        "safe_metadata_boundary_present": token_groups.get("safe_metadata_boundary")
        is True,
        "auth_redaction_boundary_present": token_groups.get("auth_redaction_boundary")
        is True,
        "contract_boundary_present": token_groups.get("contract_boundary") is True,
        "web_artifact_surface_present": token_groups.get("web_artifact_surface")
        is True,
        "prior_slice_decisions_present": token_groups.get("prior_slice_decisions")
        is True,
        "service_docs_present": token_groups.get("service_docs") is True,
        "planned_gaps_are_non_blocking": all(item["blocking"] is False for item in gaps),
        "artifact_system_of_record_is_ae": decisions["artifact_system_of_record"]
        == "nex-ae-api",
        "render_payload_storage_is_not_durable_yet": decisions[
            "current_render_payload_storage"
        ]
        == "process_local_memory",
        "redacted_evidence_only": True,
    }
    status = "PASS" if not issues and all(checks.values()) else "FAIL"
    evidence = {
        "audit_schema_version": SCHEMA_VERSION,
        "status": status,
        "scope": {
            "slice": "Slice 0401",
            "focus": "ae_artifact_runtime_persistence_storage_boundary",
            "from": "in_memory_artifact_runtime",
            "toward": [
                "ae_artifact_postgresql_schema",
                "ae_artifact_sqlalchemy_repository",
                "ae_rendered_artifact_local_storage_adapter",
                "ae_web_artifact_preview_download_clients",
            ],
        },
        "paths": paths,
        "source_tokens": source_tokens,
        "planned_gaps": gaps,
        "decisions": decisions,
        "checks": checks,
        "issues": issues,
        "redaction": {
            "database_endpoint_in_evidence": False,
            "password_in_evidence": False,
            "service_token_in_evidence": False,
            "provider_endpoint_in_evidence": False,
            "raw_prompt_in_evidence": False,
            "raw_generation_output_in_evidence": False,
            "raw_source_text_in_evidence": False,
            "artifact_payload_in_evidence": False,
            "local_artifact_path_in_evidence": False,
        },
    }
    assert_evidence_redacted(json.dumps(evidence, ensure_ascii=False, default=str), env)
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
            "present": item.token in read_text(root_dir, item.path),
            "planned_slice": item.planned_slice,
            "purpose": item.purpose,
            "blocking": False,
        }
        for item in PLANNED_GAPS
    ]


def grouped_token_status(items: list[dict[str, object]]) -> dict[str, bool]:
    groups = {str(item["group"]) for item in items}
    return {
        group: all(item["present"] for item in items if item["group"] == group)
        for group in groups
    }


def build_decisions() -> dict[str, object]:
    return {
        "artifact_system_of_record": "nex-ae-api",
        "cx_role": "source_generation_and_structured_draft_system_of_record",
        "ae_role": "artifact_handoff_record_render_file_and_link_system_of_record",
        "ag_role": "redacted_artifact_audit_consumer",
        "current_record_persistence": "process_local_memory",
        "current_render_payload_storage": "process_local_memory",
        "current_public_file_storage_ref": "logical_ae_uri_only",
        "durable_record_persistence_target": "nex_ae_database",
        "durable_payload_storage_target": "NEX_AE_ARTIFACT_STORAGE_ROOT_then_object_storage",
        "download_payload_policy_now": "authorized_route_returns_markdown_from_private_runtime_store",
        "download_payload_policy_next": "authorized_route_streams_from_private_storage_adapter",
        "preview_payload_policy": "bounded_text_preview_only",
        "raw_evidence_policy": "never_include_raw_prompts_source_text_provider_details_or_local_paths",
        "postgres_smoke_policy": "protected_test_profile_only",
        "next_slices": [
            "Slice 0402",
            "Slice 0403",
            "Slice 0404",
            "Slice 0405",
            "Slice 0406",
        ],
    }


def issue(category: str, subject: str, detail: str) -> dict[str, str]:
    return {"category": category, "subject": subject, "detail": detail}


def assert_evidence_redacted(
    serialized_evidence: str,
    environ: Mapping[str, str],
) -> None:
    for key in PROTECTED_ENV_KEYS:
        value = environ.get(key)
        if value and value not in {"1", "test"} and value in serialized_evidence:
            raise ValueError(
                "AE artifact runtime/storage audit evidence contains "
                f"unredacted environment value: {key}"
            )
    if "/data/nex-platform" in serialized_evidence:
        raise ValueError(
            "AE artifact runtime/storage audit evidence contains a local data path."
        )
    if "nuri1004" in serialized_evidence:
        raise ValueError(
            "AE artifact runtime/storage audit evidence contains a database password."
        )


def write_audit_evidence(output_path: Path, evidence: dict[str, Any]) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, indent=2, default=str)
    assert_evidence_redacted(serialized, os.environ)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(f"{serialized}\n", encoding="utf-8")


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        ready_gaps = sum(1 for item in evidence["planned_gaps"] if item["present"])
        token_groups = grouped_token_status(evidence["source_tokens"])
        return (
            "ae_artifact_runtime_persistence_storage_boundary_audit=pass "
            f"paths={present_count(evidence['paths'])}/{len(evidence['paths'])} "
            f"token_groups={present_count_bool(token_groups)}/{len(token_groups)} "
            f"gaps_ready={ready_gaps}/{len(evidence['planned_gaps'])} "
            "next=Slice_0402"
        )
    failed_checks = ",".join(
        key for key, value in evidence["checks"].items() if not value
    )
    return (
        "ae_artifact_runtime_persistence_storage_boundary_audit=fail "
        f"checks={failed_checks}"
    )


def present_count(items: list[dict[str, object]]) -> int:
    return sum(1 for item in items if item["present"])


def present_count_bool(items: Mapping[str, bool]) -> int:
    return sum(1 for value in items.values() if value)


def read_text(root_dir: Path, absolute_path: Path) -> str:
    path = path_for(root_dir, absolute_path)
    if path.is_dir():
        return "\n".join(sorted(item.name for item in path.iterdir()))
    return path.read_text(encoding="utf-8") if path.exists() else ""


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit AE artifact runtime persistence and storage boundary."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence = run_ae_artifact_runtime_persistence_storage_boundary_audit()
        if args.output:
            write_audit_evidence(args.output, evidence)
        print(
            summary_line(evidence)
            if args.summary
            else json.dumps(evidence, ensure_ascii=False, indent=2)
        )
        return 0 if evidence["status"] == "PASS" else 1
    except ValueError as exc:
        print(
            "ae_artifact_runtime_persistence_storage_boundary_audit=fail "
            f"error={exc.__class__.__name__}"
        )
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
