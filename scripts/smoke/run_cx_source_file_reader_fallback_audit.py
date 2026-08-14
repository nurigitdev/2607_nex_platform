#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
CX_PATH = ROOT / "services" / "nex-cx"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(CX_PATH))

from nex_cx.ingestion import (  # noqa: E402
    ContentIngestionStore,
    CxStorageConfig,
    IngestionError,
    build_upload_registration,
    run_text_extraction_job,
    sha256_bytes,
)


SCHEMA_VERSION = "cx_source_file_reader_fallback_audit.v1"
SECRET_SOURCE = b"# Source Reader Fallback Audit\n\nKeep this body out of evidence.\n"

PROTECTED_ENV_KEYS = (
    "NEX_CX_TEST_DATABASE_URL",
    "NEX_CX_DATABASE_URL",
    "NEX_DATA_ROOT",
    "NEX_CX_SOURCE_STORAGE_ROOT",
    "NEX_CX_EXTRACTED_MARKDOWN_ROOT",
    "NEX_CX_EXTRACTION_TEMP_ROOT",
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


CX_INGESTION = ROOT / "services" / "nex-cx" / "nex_cx" / "ingestion.py"
CX_REPOSITORY = ROOT / "services" / "nex-cx" / "nex_cx" / "repository.py"
CX_README = ROOT / "services" / "nex-cx" / "README.md"
SLICE_0280_DOC = (
    ROOT
    / "docs"
    / "slices"
    / "0280_cx_uploaded_source_extraction_readiness_audit.md"
)

REQUIRED_PATHS = (
    RequiredPath("cx_ingestion", CX_INGESTION, "CX extraction runtime boundary."),
    RequiredPath("cx_repository", CX_REPOSITORY, "CX source-file metadata boundary."),
    RequiredPath("cx_readme", CX_README, "CX source-file reader decision notes."),
    RequiredPath(
        "slice_0280_doc",
        SLICE_0280_DOC,
        "Previous uploaded-source extraction readiness checkpoint.",
    ),
)

REQUIRED_SOURCE_TOKENS = (
    TokenRequirement(
        "current_memory_reader",
        CX_INGESTION,
        "memory_source_bytes_read",
        "source_bytes = store.get_source_bytes",
        "Current extraction reads source bytes from runtime memory first.",
    ),
    TokenRequirement(
        "current_memory_reader",
        CX_INGESTION,
        "memory_missing_error",
        "cx.source_content_unavailable",
        "Current extraction fails explicitly when source bytes are unavailable.",
    ),
    TokenRequirement(
        "materialized_source_metadata",
        CX_INGESTION,
        "source_storage_key",
        "source_storage_key",
        "Upload registration records safe local source storage keys.",
    ),
    TokenRequirement(
        "materialized_source_metadata",
        CX_INGESTION,
        "source_storage_path",
        "source_storage_path",
        "Local test mode still has an absolute materialization path for writes.",
    ),
    TokenRequirement(
        "repository_source_reader_inputs",
        CX_REPOSITORY,
        "get_source_file",
        "def get_source_file",
        "Repository can return source-file metadata by id.",
    ),
    TokenRequirement(
        "repository_source_reader_inputs",
        CX_REPOSITORY,
        "checksum_verified_at",
        "checksum_verified_at",
        "Repository records checksum verification before reader fallback is safe.",
    ),
    TokenRequirement(
        "previous_readiness",
        SLICE_0280_DOC,
        "uploaded_source_readiness",
        "CX Uploaded Source Extraction Readiness Audit",
        "Slice 0280 proved uploaded bytes can become an extraction artifact.",
    ),
    TokenRequirement(
        "fallback_decision",
        CX_README,
        "fallback_decision_note",
        "source-file reader fallback",
        "CX README records the source-file reader fallback decision.",
    ),
)

RuntimeProbe = Callable[[], dict[str, Any]]


def run_cx_source_file_reader_fallback_audit(
    environ: dict[str, str] | None = None,
    *,
    root_dir: Path = ROOT,
    runtime_probe_runner: RuntimeProbe | None = None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    paths = path_checks(root_dir)
    source_tokens = source_token_checks(root_dir)
    token_groups = grouped_token_status(source_tokens)
    runtime_probe = run_runtime_probe(runtime_probe_runner or run_gap_probe)
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
    if runtime_probe["status"] != "PASS":
        issues.append(
            issue(
                "runtime_probe_failed",
                str(runtime_probe.get("failure_code", "checks_failed")),
                "memory_eviction_source_file_reader_gap_probe",
            )
        )
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "current_memory_reader_identified": (
            token_groups.get("current_memory_reader") is True
        ),
        "materialized_source_metadata_ready": (
            token_groups.get("materialized_source_metadata") is True
        ),
        "repository_reader_inputs_ready": (
            token_groups.get("repository_source_reader_inputs") is True
        ),
        "previous_readiness_recorded": token_groups.get("previous_readiness") is True,
        "fallback_decision_recorded": token_groups.get("fallback_decision") is True,
        "runtime_gap_probe_passed": runtime_probe["status"] == "PASS",
        "redacted_evidence_only": True,
    }
    status = "PASS" if not issues and all(checks.values()) else "FAIL"
    evidence = {
        "audit_schema_version": SCHEMA_VERSION,
        "status": status,
        "scope": {
            "slice": "Slice 0281",
            "focus": "cx_source_file_reader_fallback",
            "from": "uploaded_source_extraction_readiness",
            "toward": "materialized_source_extraction_fallback",
        },
        "paths": paths,
        "source_tokens": source_tokens,
        "runtime_probe": runtime_probe,
        "checks": checks,
        "issues": issues,
        "decision": {
            "risk": "memory_only_extraction_loses_uploaded_bytes_after_runtime_restart",
            "target": "read_verified_local_source_file_when_runtime_source_bytes_are_missing",
            "next_slice": "Slice 0282",
            "raw_source_in_evidence": False,
            "local_path_in_evidence": False,
        },
    }
    assert_evidence_redacted(json.dumps(evidence, ensure_ascii=False, default=str), env)
    return evidence


def run_runtime_probe(runner: RuntimeProbe) -> dict[str, Any]:
    try:
        probe = runner()
    except Exception as exc:  # pragma: no cover - covered through injected runner
        return {
            "status": "FAIL",
            "failure_code": exc.__class__.__name__,
            "checks": {"redacted_evidence_only": True},
        }
    return probe if isinstance(probe, dict) else {"status": "FAIL", "failure_code": "invalid_probe"}


def run_gap_probe() -> dict[str, Any]:
    request_id = "slice-0281-request"
    trace_id = "1" * 32
    source_sha256 = sha256_bytes(SECRET_SOURCE)
    with tempfile.TemporaryDirectory(prefix="nex-cx-source-reader-fallback-") as tmp:
        root = Path(tmp)
        storage_config = CxStorageConfig(
            data_root=root,
            source_root=root / "cx" / "source-files",
            extracted_markdown_root=root / "cx" / "extracted-markdown",
            extraction_temp_root=root / "cx" / "extraction-temp",
            chunk_policy="chunk_1000_100",
            chunk_size=1000,
            chunk_overlap=100,
            bm25_tokenizer="mecab_ko",
            bm25_tokenizer_fallback="korean_mixed_v1",
        )
        store = ContentIngestionStore()
        record = build_upload_registration(
            {
                "filename": "slice-0281-source.md",
                "content_type": "text/markdown",
                "tenant_id": "tenant-slice-0281",
                "owner_user_id": "owner-slice-0281",
                "source_sha256": source_sha256,
                "size_bytes": len(SECRET_SOURCE),
            },
            storage_config=storage_config,
            request_id=request_id,
            trace_id=trace_id,
        )
        stored = store.save_upload_registration(record, source_bytes=SECRET_SOURCE)
        upload_id = stored["upload_id"]
        refs = store.get_content_ref(stored["document_id"])
        source_file = (
            store.content_repository.get_source_file(refs["source_file_id"])
            if refs is not None
            else None
        )
        source_path = Path(stored["storage"]["source_storage_path"])
        store.source_bytes.pop(upload_id, None)
        store.source_texts.pop(upload_id, None)

        extraction_unavailable = False
        extraction_error_code = None
        try:
            run_text_extraction_job(
                stored["extraction"]["job_id"],
                store=store,
                storage_config=storage_config,
                request_id=request_id,
                trace_id=trace_id,
            )
        except IngestionError as exc:
            extraction_error_code = exc.error_code
            extraction_unavailable = exc.error_code == "cx.source_content_unavailable"

        checks = {
            "materialized_source_exists": source_path.exists(),
            "materialized_source_checksum_matches": (
                source_path.exists() and sha256_bytes(source_path.read_bytes()) == source_sha256
            ),
            "source_file_checksum_verified": (
                isinstance(source_file, dict)
                and isinstance(source_file.get("checksum_verified_at"), str)
            ),
            "memory_source_bytes_evicted": not store.source_bytes_available(upload_id),
            "current_extraction_reports_gap": extraction_unavailable,
            "raw_source_not_serialized": True,
            "local_path_not_serialized": True,
        }
        return {
            "status": "PASS" if all(checks.values()) else "FAIL",
            "probe_schema_version": "cx_source_file_reader_gap_probe.v1",
            "observations": {
                "document_id_present": bool(stored.get("document_id")),
                "source_file_id_present": refs is not None,
                "storage_backend": (
                    source_file.get("storage_backend")
                    if isinstance(source_file, dict)
                    else None
                ),
                "memory_source_bytes_available_after_evict": store.source_bytes_available(
                    upload_id
                ),
                "extraction_error_code_after_evict": extraction_error_code,
                "fallback_state": "pending",
            },
            "checks": checks,
        }


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


def grouped_token_status(items: list[dict[str, object]]) -> dict[str, bool]:
    groups = {str(item["group"]) for item in items}
    return {
        group: all(item["present"] for item in items if item["group"] == group)
        for group in groups
    }


def issue(category: str, subject: str, detail: str) -> dict[str, str]:
    return {"category": category, "subject": subject, "detail": detail}


def assert_evidence_redacted(serialized_evidence: str, environ: Mapping[str, str]) -> None:
    for key in PROTECTED_ENV_KEYS:
        value = environ.get(key)
        if value and value not in {"1", "test"} and value in serialized_evidence:
            raise ValueError(
                "CX source-file reader fallback evidence contains "
                f"unredacted environment value: {key}"
            )
    if SECRET_SOURCE.decode("utf-8") in serialized_evidence:
        raise ValueError("CX source-file reader fallback evidence contains raw source.")
    if "/data/nex-platform" in serialized_evidence:
        raise ValueError("CX source-file reader fallback evidence contains a local path.")
    if "nex-cx-source-reader-fallback-" in serialized_evidence:
        raise ValueError("CX source-file reader fallback evidence contains a temp path.")


def write_audit_evidence(output_path: Path, evidence: dict[str, Any]) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, indent=2, default=str)
    assert_evidence_redacted(serialized, os.environ)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(f"{serialized}\n", encoding="utf-8")


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        token_groups = grouped_token_status(evidence["source_tokens"])
        probe = evidence["runtime_probe"]
        observations = probe.get("observations", {}) if isinstance(probe, dict) else {}
        return (
            "cx_source_file_reader_fallback_audit=pass "
            f"paths={present_count(evidence['paths'])}/{len(evidence['paths'])} "
            f"token_groups={present_count_bool(token_groups)}/{len(token_groups)} "
            f"fallback_state={observations.get('fallback_state')} "
            "next=Slice_0282"
        )
    failed_checks = ",".join(
        key for key, value in evidence["checks"].items() if not value
    )
    return f"cx_source_file_reader_fallback_audit=fail checks={failed_checks}"


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
        description="Audit CX source-file reader fallback readiness."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence = run_cx_source_file_reader_fallback_audit()
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
            "cx_source_file_reader_fallback_audit=fail "
            f"error={exc.__class__.__name__}"
        )
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
