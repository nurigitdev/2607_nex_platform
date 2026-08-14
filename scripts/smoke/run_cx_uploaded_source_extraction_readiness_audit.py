#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
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
    build_upload_registration,
    run_text_extraction_job,
    sha256_bytes,
)


SCHEMA_VERSION = "cx_uploaded_source_extraction_readiness_audit.v1"
SECRET_SOURCE = b"# Uploaded Source Readiness Secret\n\nDo not serialize this body.\n"

PROTECTED_ENV_KEYS = (
    "NEX_CX_TEST_DATABASE_URL",
    "NEX_CX_DATABASE_URL",
    "NEX_DATA_ROOT",
    "NEX_CX_SOURCE_STORAGE_ROOT",
    "NEX_CX_EXTRACTED_MARKDOWN_ROOT",
    "NEX_CX_EXTRACTION_TEMP_ROOT",
    "NEX_AE_WEB_AUTHENTICATED_UPLOAD_PLAYWRIGHT_SMOKE_PASSWORD",
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
CX_PROCESSING = ROOT / "services" / "nex-cx" / "nex_cx" / "processing.py"
CX_EXTRACTORS = ROOT / "services" / "nex-cx" / "nex_cx" / "extractors.py"
CX_REPOSITORY = ROOT / "services" / "nex-cx" / "nex_cx" / "repository.py"
CX_README = ROOT / "services" / "nex-cx" / "README.md"
SLICE_0279_DOC = (
    ROOT
    / "docs"
    / "slices"
    / "0279_ae_web_source_file_upload_playwright_postgresql_smoke.md"
)

REQUIRED_PATHS = (
    RequiredPath("cx_ingestion", CX_INGESTION, "CX upload and extraction runtime."),
    RequiredPath("cx_processing", CX_PROCESSING, "CX processing pipeline runtime."),
    RequiredPath("cx_extractors", CX_EXTRACTORS, "CX text extractor adapters."),
    RequiredPath("cx_repository", CX_REPOSITORY, "CX source/extraction persistence."),
    RequiredPath("cx_readme", CX_README, "CX storage and extraction documentation."),
    RequiredPath(
        "slice_0279_doc",
        SLICE_0279_DOC,
        "Verified source-file upload smoke decision record.",
    ),
)

REQUIRED_SOURCE_TOKENS = (
    TokenRequirement(
        "source_bytes_capture",
        CX_INGESTION,
        "source_bytes_available",
        "source_bytes_available",
        "CX can report whether source bytes were captured for an upload.",
    ),
    TokenRequirement(
        "source_bytes_capture",
        CX_INGESTION,
        "source_bytes_store",
        "self.source_bytes[record[\"upload_id\"]]",
        "CX keeps captured source bytes in the runtime store for extraction.",
    ),
    TokenRequirement(
        "extraction_job",
        CX_INGESTION,
        "get_source_bytes",
        "source_bytes = store.get_source_bytes",
        "Text extraction reads source bytes from the upload runtime state.",
    ),
    TokenRequirement(
        "extraction_job",
        CX_INGESTION,
        "missing_source_guard",
        "cx.source_content_unavailable",
        "Extraction fails safely when source bytes are unavailable.",
    ),
    TokenRequirement(
        "extraction_job",
        CX_INGESTION,
        "write_markdown",
        "write_extracted_markdown",
        "Extraction writes converted Markdown outside public evidence.",
    ),
    TokenRequirement(
        "extraction_persistence",
        CX_INGESTION,
        "save_extraction_result",
        "save_extraction_result",
        "Extraction results are saved through the ingestion store boundary.",
    ),
    TokenRequirement(
        "extraction_persistence",
        CX_REPOSITORY,
        "extraction_artifact_record",
        "build_extraction_artifact_record",
        "Extraction artifacts persist source/content lineage without raw bytes.",
    ),
    TokenRequirement(
        "processing_pipeline",
        CX_PROCESSING,
        "processing_uses_extraction_job",
        "run_text_extraction_job(",
        "The processing pipeline starts with the same extraction job boundary.",
    ),
    TokenRequirement(
        "processing_pipeline",
        CX_PROCESSING,
        "processing_job_lookup",
        "extraction_job_id_for_document",
        "The processing pipeline resolves the extraction job by document.",
    ),
    TokenRequirement(
        "extractor_adapter",
        CX_EXTRACTORS,
        "local_mock_extractor",
        "LocalMockTextExtractor",
        "A deterministic local extractor is available for regression paths.",
    ),
    TokenRequirement(
        "extractor_adapter",
        CX_EXTRACTORS,
        "unsupported_source_error",
        "ExtractionAdapterError",
        "Unsupported source types are surfaced as typed extraction errors.",
    ),
    TokenRequirement(
        "verified_upload_smoke",
        SLICE_0279_DOC,
        "verified_source_file_upload",
        "cx_checksum=verified",
        "The browser source-file upload smoke verifies CX checksum materialization.",
    ),
)

RuntimeProbe = Callable[[], dict[str, Any]]


def run_cx_uploaded_source_extraction_readiness_audit(
    environ: dict[str, str] | None = None,
    *,
    root_dir: Path = ROOT,
    runtime_probe_runner: RuntimeProbe | None = None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    paths = path_checks(root_dir)
    source_tokens = source_token_checks(root_dir)
    token_groups = grouped_token_status(source_tokens)
    runtime_probe = run_runtime_probe(runtime_probe_runner or run_in_memory_extraction_probe)
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
                "in_memory_upload_to_extraction_probe",
            )
        )
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "source_bytes_capture_ready": token_groups.get("source_bytes_capture") is True,
        "extraction_job_boundary_ready": token_groups.get("extraction_job") is True,
        "extraction_persistence_ready": (
            token_groups.get("extraction_persistence") is True
        ),
        "processing_pipeline_entry_ready": (
            token_groups.get("processing_pipeline") is True
        ),
        "extractor_adapter_ready": token_groups.get("extractor_adapter") is True,
        "verified_upload_smoke_ready": token_groups.get("verified_upload_smoke")
        is True,
        "runtime_probe_passed": runtime_probe["status"] == "PASS",
        "redacted_evidence_only": True,
    }
    status = "PASS" if not issues and all(checks.values()) else "FAIL"
    evidence = {
        "audit_schema_version": SCHEMA_VERSION,
        "status": status,
        "scope": {
            "slice": "Slice 0280",
            "focus": "cx_uploaded_source_extraction_readiness",
            "from": "verified_browser_source_file_upload",
            "toward": "cx_extraction_processing_pipeline",
        },
        "paths": paths,
        "source_tokens": source_tokens,
        "runtime_probe": runtime_probe,
        "checks": checks,
        "issues": issues,
        "redaction": {
            "raw_source_in_evidence": False,
            "local_path_in_evidence": False,
            "database_endpoint_in_evidence": False,
            "password_in_evidence": False,
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


def run_in_memory_extraction_probe() -> dict[str, Any]:
    request_id = "slice-0280-request"
    trace_id = "0" * 32
    source_sha256 = sha256_bytes(SECRET_SOURCE)
    with tempfile.TemporaryDirectory(prefix="nex-cx-uploaded-source-extraction-") as tmp:
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
                "filename": "slice-0280-source.md",
                "content_type": "text/markdown",
                "tenant_id": "tenant-slice-0280",
                "owner_user_id": "owner-slice-0280",
                "source_sha256": source_sha256,
                "size_bytes": len(SECRET_SOURCE),
                "content_base64": base64.b64encode(SECRET_SOURCE).decode("ascii"),
            },
            storage_config=storage_config,
            request_id=request_id,
            trace_id=trace_id,
        )
        stored = store.save_upload_registration(record, source_bytes=SECRET_SOURCE)
        result = run_text_extraction_job(
            stored["extraction"]["job_id"],
            store=store,
            storage_config=storage_config,
            request_id=request_id,
            trace_id=trace_id,
        )
        markdown_path = Path(result["extracted_markdown_path"])
        refs = store.get_content_ref(stored["document_id"])
        repository = store.content_repository
        artifact_count = len(getattr(repository, "extraction_artifacts", {}))
        source_file = (
            repository.get_source_file(refs["source_file_id"])
            if refs is not None
            else None
        )
        checks = {
            "source_bytes_available": store.source_bytes_available(stored["upload_id"]),
            "source_checksum_verified": (
                isinstance(source_file, dict)
                and isinstance(source_file.get("checksum_verified_at"), str)
            ),
            "markdown_written": markdown_path.exists(),
            "markdown_hash_recorded": isinstance(result["extracted_markdown_sha256"], str),
            "extraction_artifact_persisted": artifact_count == 1,
            "raw_source_not_serialized": True,
            "local_path_not_serialized": True,
        }
        return {
            "status": "PASS" if all(checks.values()) else "FAIL",
            "probe_schema_version": "cx_uploaded_source_extraction_probe.v1",
            "observations": {
                "document_id_present": bool(stored.get("document_id")),
                "source_file_id_present": refs is not None,
                "source_bytes_available": checks["source_bytes_available"],
                "source_checksum_verified": checks["source_checksum_verified"],
                "markdown_written": checks["markdown_written"],
                "extraction_artifact_count": artifact_count,
                "extractor_source_format": result["extractor"]["source_format"],
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
                "CX uploaded source extraction readiness evidence contains "
                f"unredacted environment value: {key}"
            )
    if SECRET_SOURCE.decode("utf-8") in serialized_evidence:
        raise ValueError("CX uploaded source extraction evidence contains raw source.")
    if "/data/nex-platform" in serialized_evidence:
        raise ValueError("CX uploaded source extraction evidence contains a local path.")
    if "nex-cx-uploaded-source-extraction-" in serialized_evidence:
        raise ValueError("CX uploaded source extraction evidence contains a temp path.")


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
            "cx_uploaded_source_extraction_readiness_audit=pass "
            f"paths={present_count(evidence['paths'])}/{len(evidence['paths'])} "
            f"token_groups={present_count_bool(token_groups)}/{len(token_groups)} "
            f"runtime_probe={probe.get('status')} "
            f"extraction_artifacts={observations.get('extraction_artifact_count')} "
            "next=Slice_0281"
        )
    failed_checks = ",".join(
        key for key, value in evidence["checks"].items() if not value
    )
    return f"cx_uploaded_source_extraction_readiness_audit=fail checks={failed_checks}"


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
        description="Audit CX uploaded source-file extraction readiness."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence = run_cx_uploaded_source_extraction_readiness_audit()
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
            "cx_uploaded_source_extraction_readiness_audit=fail "
            f"error={exc.__class__.__name__}"
        )
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
