#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "platform_private_object_storage_boundary.v1"
CANONICAL_PATH = "docs/54_platform_private_object_storage.md"
READINESS_PATH = "docs/48_platform_production_readiness_plan.md"


@dataclass(frozen=True)
class PrivatePayloadFamily:
    owner: str
    family: str
    current_anchor: str
    target_prefix: str


PAYLOAD_FAMILIES = (
    PrivatePayloadFamily("nex-cx", "source", "NEX_CX_SOURCE_STORAGE_ROOT", "source"),
    PrivatePayloadFamily("nex-cx", "extracted", "NEX_CX_EXTRACTED_MARKDOWN_ROOT", "extracted"),
    PrivatePayloadFamily("nex-cx", "text", "NEX_CX_PRIVATE_TEXT_STORAGE_ROOT", "text"),
    PrivatePayloadFamily("nex-cx", "generation_request", "NEX_CX_GENERATION_REQUEST_STORAGE_ROOT", "generation-request"),
    PrivatePayloadFamily("nex-cx", "generation_output", "NEX_CX_GENERATION_OUTPUT_STORAGE_ROOT", "generation-output"),
    PrivatePayloadFamily("nex-ae-api", "chat_response", "NEX_AE_CHAT_RESPONSE_STORAGE_ROOT", "chat-response"),
    PrivatePayloadFamily("nex-ae-api", "artifact", "NEX_AE_ARTIFACT_STORAGE_ROOT", "artifact"),
)

REQUIRED_PATHS = (
    READINESS_PATH,
    CANONICAL_PATH,
    "docs/slices/1453_s146_private_object_storage_boundary.md",
    "services/nex-cx/nex_cx/ingestion.py",
    "services/nex-cx/nex_cx/private_text_store.py",
    "services/nex-cx/nex_cx/private_content.py",
    "services/nex-cx/nex_cx/generation_request_store.py",
    "services/nex-cx/nex_cx/generation_private_output.py",
    "services/nex-ae-api/nex_ae_api/generated_response_storage.py",
    "services/nex-ae-api/nex_ae_api/artifacts.py",
    "deployment/compose/s143-staging.compose.yaml",
)


def run_private_object_storage_boundary(root: Path = ROOT) -> dict[str, Any]:
    paths = {path: (root / path).is_file() for path in REQUIRED_PATHS}
    canonical = " ".join(_read_text(root / CANONICAL_PATH).split())
    readiness = " ".join(_read_text(root / READINESS_PATH).split())
    source = "\n".join(
        _read_text(root / path)
        for path in REQUIRED_PATHS
        if path.startswith("services/")
    )
    checks = {
        "required_paths_present": all(paths.values()),
        "seven_private_payload_families_inventoried": (
            len(PAYLOAD_FAMILIES) == 7
            and all(item.current_anchor in source for item in PAYLOAD_FAMILIES)
            and all(item.target_prefix in canonical for item in PAYLOAD_FAMILIES)
        ),
        "rustfs_selected_behind_s3_port": all(
            token in canonical for token in ("RustFS", "S3-compatible API boundary", "No RustFS-specific SDK")
        ),
        "service_bucket_isolation_frozen": all(
            token in canonical for token in ("nex-cx-private", "nex-ae-private", "separate service credentials")
        ),
        "encryption_versioning_retention_frozen": all(
            token in canonical for token in ("SSE-S3", "versioning enabled", "30 days", "7 days")
        ),
        "owner_opaque_key_contract_frozen": all(
            token in canonical for token in ("owner-digest", "no raw tenant ID", "one-way SHA-256 digests")
        ),
        "migration_rollback_contract_frozen": all(
            token in canonical for token in ("inventory, copy, integrity verification, dual-read", "Rollback changes the read preference only")
        ),
        "database_vector_and_backup_exclusions_frozen": all(
            token in canonical for token in ("PostgreSQL continues to own", "Vectors remain", "PostgreSQL backups")
        ),
        "ten_slice_gate_sequence_frozen": (
            all(f"`{slice_id}`" in canonical for slice_id in range(1453, 1463))
            and "Checkpoint Gate runs at Slice 1457" in canonical
            and "Full Gate at Slice 1462" in canonical
        ),
        "production_deferral_remains_open": (
            "production_object_storage_lifecycle" in readiness
            and "object_storage_lifecycle" in readiness
            and "production deployment remains unapproved" in canonical.lower()
        ),
        "privacy_and_fail_closed_rules_frozen": all(
            token in canonical for token in ("forbidden in protected", "silent in staging/production", "source-controlled evidence")
        ),
    }
    issues = [
        {"category": "path_missing", "path": path}
        for path, present in paths.items()
        if not present
    ]
    issues.extend(
        {"category": "check_failed", "check": name}
        for name, passed in checks.items()
        if not passed
    )
    passed = not issues
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1453",
        "requirement": "S146",
        "status": "PASS" if passed else "FAIL",
        "boundary_readiness": "BOUNDARY_FROZEN" if passed else "AUDIT_FAILED",
        "checks": checks,
        "issues": issues,
        "required_paths": paths,
        "payload_families": [
            {
                "owner": item.owner,
                "family": item.family,
                "target_prefix": item.target_prefix,
                "state": "LOCAL_TO_OBJECT_MIGRATION_REQUIRED",
            }
            for item in PAYLOAD_FAMILIES
        ],
        "summary": {
            "required_path_count": sum(paths.values()),
            "check_count": len(checks),
            "payload_family_count": len(PAYLOAD_FAMILIES),
            "bucket_count": 2,
            "slice_count": 10,
            "missing_path_count": sum(not value for value in paths.values()),
        },
        "decision": {
            "deployment_product": "RUSTFS",
            "application_protocol": "S3_COMPATIBLE",
            "cx_bucket": "nex-cx-private",
            "ae_bucket": "nex-ae-private",
            "server_side_encryption": "AES256",
            "versioning_required": True,
            "local_storage_production_allowed": False,
            "vector_migration_in_scope": False,
            "production_deployment_approved": False,
            "next_slice": "1454" if passed else "blocked",
        },
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return f"private_object_storage_boundary=fail issues={len(result.get('issues') or [])}"
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "private_object_storage_boundary=pass "
        f"checks={summary.get('check_count', 0)}/11 "
        f"payloads={summary.get('payload_family_count', 0)} "
        f"buckets={summary.get('bucket_count', 0)} "
        f"product={str(decision.get('deployment_product') or '').lower()} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_private_object_storage_boundary()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
