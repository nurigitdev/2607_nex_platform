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
SCHEMA_VERSION = "cx_source_file_materialization_boundary_audit.v1"

PROTECTED_ENV_KEYS = (
    "NEX_AE_TEST_DATABASE_URL",
    "NEX_CX_TEST_DATABASE_URL",
    "NEX_OA_TEST_DATABASE_URL",
    "NEX_AE_DATABASE_URL",
    "NEX_CX_DATABASE_URL",
    "NEX_OA_DATABASE_URL",
    "NEX_DATA_ROOT",
    "NEX_CX_SOURCE_STORAGE_ROOT",
    "NEX_CX_EXTRACTED_MARKDOWN_ROOT",
    "NEX_CX_EXTRACTION_TEMP_ROOT",
    "NEX_AE_WEB_AUTHENTICATED_UPLOAD_PLAYWRIGHT_SMOKE_PASSWORD",
    "NEX_AE_WEB_CREDENTIAL_LOGIN_PLAYWRIGHT_SMOKE_PASSWORD",
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


CX_INGESTION = ROOT / "services" / "nex-cx" / "nex_cx" / "ingestion.py"
CX_REPOSITORY = ROOT / "services" / "nex-cx" / "nex_cx" / "repository.py"
CX_README = ROOT / "services" / "nex-cx" / "README.md"
AE_UPLOADS = ROOT / "services" / "nex-ae-api" / "nex_ae_api" / "uploads.py"
AE_WEB_UPLOAD_CLIENT = ROOT / "apps" / "nex-ae-web" / "src" / "uploadClient.js"
AE_WEB_UPLOAD_SURFACE = ROOT / "apps" / "nex-ae-web" / "src" / "uploadSurface.js"
SLICE_0274_DOC = (
    ROOT / "docs" / "slices" / "0274_ae_web_authenticated_upload_playwright_postgresql_smoke.md"
)
SLICE_0279_DOC = (
    ROOT
    / "docs"
    / "slices"
    / "0279_ae_web_source_file_upload_playwright_postgresql_smoke.md"
)
AE_WEB_UPLOAD_PLAYWRIGHT_SMOKE = (
    ROOT
    / "scripts"
    / "smoke"
    / "run_ae_web_authenticated_upload_playwright_postgres_smoke.py"
)

REQUIRED_PATHS = (
    RequiredPath("cx_ingestion", CX_INGESTION, "CX upload intake and materialization."),
    RequiredPath("cx_repository", CX_REPOSITORY, "CX source/content metadata repository."),
    RequiredPath("cx_readme", CX_README, "CX storage boundary documentation."),
    RequiredPath("ae_upload_facade", AE_UPLOADS, "AE facade that delegates upload registration."),
    RequiredPath(
        "ae_web_upload_client",
        AE_WEB_UPLOAD_CLIENT,
        "Browser upload handoff client.",
    ),
    RequiredPath(
        "ae_web_upload_surface",
        AE_WEB_UPLOAD_SURFACE,
        "Browser upload metadata/ownership surface.",
    ),
    RequiredPath(
        "slice_0274_doc",
        SLICE_0274_DOC,
        "Previous protected upload smoke decision record.",
    ),
    RequiredPath(
        "slice_0279_doc",
        SLICE_0279_DOC,
        "Current source-file upload smoke decision record.",
    ),
)

REQUIRED_SOURCE_TOKENS = (
    TokenRequirement(
        "cx_storage_config",
        CX_INGESTION,
        "source_root_env",
        "NEX_CX_SOURCE_STORAGE_ROOT",
        "CX source-file storage root is environment-configurable.",
    ),
    TokenRequirement(
        "cx_storage_config",
        CX_INGESTION,
        "max_upload_size",
        "NEX_CX_MAX_UPLOAD_SIZE_BYTES",
        "CX owns upload size limits before materialization.",
    ),
    TokenRequirement(
        "cx_payload_modes",
        CX_INGESTION,
        "content_base64_mode",
        "content_base64",
        "CX can accept binary bytes through the existing JSON payload boundary.",
    ),
    TokenRequirement(
        "cx_payload_modes",
        CX_INGESTION,
        "precomputed_hash_mode",
        "precomputed_hash",
        "CX still supports metadata-only registrations before bytes arrive.",
    ),
    TokenRequirement(
        "cx_materialization",
        CX_INGESTION,
        "materialize_bytes",
        "materialize_local_source_bytes",
        "CX materializes source bytes behind the ingestion store.",
    ),
    TokenRequirement(
        "cx_materialization",
        CX_INGESTION,
        "checksum_mismatch_guard",
        "cx.source_checksum_mismatch",
        "CX rejects bytes whose SHA-256 does not match the registration.",
    ),
    TokenRequirement(
        "cx_materialization",
        CX_INGESTION,
        "storage_key_traversal_guard",
        "source_storage_key must be a relative safe storage key.",
        "CX rejects absolute or traversal storage keys.",
    ),
    TokenRequirement(
        "cx_materialization",
        CX_INGESTION,
        "absolute_source_path_guard",
        "source_storage_path must be absolute for local materialization.",
        "CX validates local materialization paths before writing.",
    ),
    TokenRequirement(
        "cx_materialization",
        CX_INGESTION,
        "collision_guard",
        "cx.source_file_collision",
        "CX rejects existing files with conflicting bytes.",
    ),
    TokenRequirement(
        "cx_materialization",
        CX_INGESTION,
        "checksum_verified",
        "mark_source_file_checksum_verified",
        "CX records checksum verification after bytes are materialized.",
    ),
    TokenRequirement(
        "cx_storage_key",
        CX_INGESTION,
        "date_partition",
        "storage_date_partition(created_at)",
        "Local source-file keys are date partitioned.",
    ),
    TokenRequirement(
        "cx_storage_key",
        CX_INGESTION,
        "hash_shard_one",
        "source_sha256[:2]",
        "Local source-file keys are hash sharded.",
    ),
    TokenRequirement(
        "cx_storage_key",
        CX_INGESTION,
        "hash_shard_two",
        "source_sha256[2:4]",
        "Local source-file keys include a second hash shard.",
    ),
    TokenRequirement(
        "cx_repository_boundary",
        CX_REPOSITORY,
        "source_metadata_table",
        "cx_source_files",
        "PostgreSQL stores source metadata and storage links.",
    ),
    TokenRequirement(
        "cx_repository_boundary",
        CX_REPOSITORY,
        "storage_uri_metadata",
        "storage_uri",
        "Repository records storage URI metadata instead of source bytes.",
    ),
    TokenRequirement(
        "ae_facade_boundary",
        AE_UPLOADS,
        "ae_delegates_to_cx",
        "client.register_upload",
        "AE upload facade delegates persistence to CX.",
    ),
    TokenRequirement(
        "ae_facade_boundary",
        AE_UPLOADS,
        "ae_metadata_hash_forward",
        "source_sha256",
        "AE forwards source checksum metadata to CX.",
    ),
    TokenRequirement(
        "ae_web_boundary",
        AE_WEB_UPLOAD_SURFACE,
        "browser_multipart_route",
        "AE_MULTIPART_UPLOAD_ROUTE",
        "Browser upload surface exposes the AE multipart facade route.",
    ),
    TokenRequirement(
        "slice_0274_boundary",
        SLICE_0274_DOC,
        "source_file_upgrade_documented",
        "Slice 0279 upgrades the same runner",
        "Slice 0274 documents that the protected smoke was upgraded later.",
    ),
    TokenRequirement(
        "slice_0279_boundary",
        SLICE_0279_DOC,
        "verified_source_file_smoke_documented",
        "cx_checksum=verified",
        "Slice 0279 documents verified CX source-file materialization evidence.",
    ),
)

PLANNED_GAPS = (
    PlannedGap(
        "ae_multipart_facade",
        AE_UPLOADS,
        "UploadFile",
        "Slice 0277",
        "AE should receive browser multipart files without long-term local storage.",
    ),
    PlannedGap(
        "ae_web_formdata_upload",
        AE_WEB_UPLOAD_CLIENT,
        "FormData",
        "Slice 0278",
        "AE Web should submit selected source files as multipart form data.",
    ),
    PlannedGap(
        "source_file_playwright_postgres_smoke",
        AE_WEB_UPLOAD_PLAYWRIGHT_SMOKE,
        "cx_checksum=verified",
        "Slice 0279",
        "Protected browser smoke should verify materialized source bytes in CX.",
    ),
    PlannedGap(
        "object_storage_adapter",
        CX_INGESTION,
        "object_storage",
        "Future storage slice",
        "CX storage adapter should later swap local filesystem for object storage.",
    ),
)


def run_cx_source_file_materialization_boundary_audit(
    environ: dict[str, str] | None = None,
    *,
    root_dir: Path = ROOT,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    paths = path_checks(root_dir)
    source_tokens = source_token_checks(root_dir)
    gaps = planned_gap_checks(root_dir)
    decisions = build_decisions()
    groups = grouped_token_status(source_tokens)
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
        "cx_storage_config_present": groups.get("cx_storage_config") is True,
        "cx_payload_modes_present": groups.get("cx_payload_modes") is True,
        "cx_materialization_guardrails_present": groups.get("cx_materialization")
        is True,
        "cx_storage_key_partitioning_present": groups.get("cx_storage_key") is True,
        "cx_repository_metadata_boundary_present": groups.get("cx_repository_boundary")
        is True,
        "ae_facade_delegates_persistence_to_cx": groups.get("ae_facade_boundary")
        is True,
        "browser_source_file_route_available": groups.get("ae_web_boundary") is True,
        "previous_slice_upgrade_documented": groups.get("slice_0274_boundary") is True,
        "source_file_smoke_documented": groups.get("slice_0279_boundary") is True,
        "planned_gaps_are_non_blocking": all(item["blocking"] is False for item in gaps),
        "cx_is_source_file_system_of_record": decisions["source_file_system_of_record"]
        == "nex-cx",
        "ae_long_term_source_storage_forbidden": decisions[
            "ae_long_term_source_storage"
        ]
        == "forbidden",
        "redacted_evidence_only": True,
    }
    status = "PASS" if not issues and all(checks.values()) else "FAIL"
    evidence = {
        "audit_schema_version": SCHEMA_VERSION,
        "status": status,
        "scope": {
            "slice": "Slice 0275",
            "focus": "cx_source_file_materialization_boundary",
            "from": "metadata_only_authenticated_upload",
            "toward": [
                "cx_source_file_byte_persistence_adapter",
                "ae_upload_multipart_facade_contract",
                "source_file_upload_playwright_postgresql_smoke",
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
            "cookie_material_in_evidence": False,
            "token_material_in_evidence": False,
            "source_bytes_in_evidence": False,
            "local_source_path_in_evidence": False,
            "provider_endpoint_in_evidence": False,
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
        "source_file_system_of_record": "nex-cx",
        "ae_role": "transient_browser_file_facade",
        "ae_long_term_source_storage": "forbidden",
        "browser_to_ae_transport_next": "multipart_form_data",
        "ae_to_cx_transport_near_term": "service_authenticated_content_base64_json",
        "cx_storage_backend_now": "local_filesystem_adapter",
        "cx_storage_backend_future": "object_storage_adapter",
        "source_file_key_shape": "YYYYMMDD/sha2/sha2/source_file_id_extension",
        "dedupe_boundary": "global_source_sha256_metadata_plus_owner_scoped_content",
        "checksum_policy": "cx_verifies_bytes_against_source_sha256_before_marking_verified",
        "metadata_only_policy": "supported_for_no_file_uploads_but_verified_when_bytes_are_available",
        "raw_evidence_policy": "never_include_raw_source_bytes_or_local_paths",
        "next_slices": ["Slice 0280"],
    }


def issue(category: str, subject: str, detail: str) -> dict[str, str]:
    return {"category": category, "subject": subject, "detail": detail}


def assert_evidence_redacted(serialized_evidence: str, environ: Mapping[str, str]) -> None:
    for key in PROTECTED_ENV_KEYS:
        value = environ.get(key)
        if value and value not in {"1", "test"} and value in serialized_evidence:
            raise ValueError(
                "CX source-file materialization audit evidence contains "
                f"unredacted environment value: {key}"
            )
    if "/data/nex-platform" in serialized_evidence:
        raise ValueError(
            "CX source-file materialization audit evidence contains a local data path."
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
            "cx_source_file_materialization_boundary_audit=pass "
            f"paths={present_count(evidence['paths'])}/{len(evidence['paths'])} "
            f"token_groups={present_count_bool(token_groups)}/{len(token_groups)} "
            f"gaps_ready={ready_gaps}/{len(evidence['planned_gaps'])} "
            "next=Slice_0280"
        )
    failed_checks = ",".join(
        key for key, value in evidence["checks"].items() if not value
    )
    return f"cx_source_file_materialization_boundary_audit=fail checks={failed_checks}"


def present_count(items: list[dict[str, object]]) -> int:
    return sum(1 for item in items if item["present"])


def present_count_bool(items: Mapping[str, bool]) -> int:
    return sum(1 for value in items.values() if value)


def read_text(root_dir: Path, absolute_path: Path) -> str:
    path = path_for(root_dir, absolute_path)
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
        description="Audit CX source-file materialization boundary readiness."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence = run_cx_source_file_materialization_boundary_audit()
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
            "cx_source_file_materialization_boundary_audit=fail "
            f"error={exc.__class__.__name__}"
        )
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
