#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "nex-cx", ROOT / "services" / "_shared"):
    sys.path.insert(0, str(path))

from nex_cx.ingestion import (
    ContentIngestionStore,
    CxStorageConfig,
    build_upload_registration,
)
from nex_cx.ingestion_admission import admit_durable_ingestion
from nex_cx.ingestion_orchestration_repository import InMemoryIngestionRunRepository
from nex_cx.repository import InMemoryCxContentRepository
from nex_runtime import InMemoryJobQueue

SCHEMA_VERSION = "cx_upload_admission_lineage_evidence.v1"
SOURCE_TEXT = "private-s135-upload-source"


def run_cx_upload_admission_lineage() -> dict[str, Any]:
    content_repository = InMemoryCxContentRepository()
    queue = InMemoryJobQueue()
    run_repository = InMemoryIngestionRunRepository()
    with TemporaryDirectory(prefix="nex-s135-1345-") as data_root:
        config = _storage_config(Path(data_root))
        first = _register_and_admit(
            ContentIngestionStore(content_repository=content_repository),
            content_repository=content_repository,
            queue=queue,
            run_repository=run_repository,
            config=config,
            request_id="request-before-restart",
            trace_id="a" * 32,
            filename="private.md",
        )
        duplicate = _register_and_admit(
            ContentIngestionStore(content_repository=content_repository),
            content_repository=content_repository,
            queue=queue,
            run_repository=run_repository,
            config=config,
            request_id="request-after-restart",
            trace_id="b" * 32,
            filename="renamed.md",
        )
        other_owner = _build_registration(
            config,
            request_id="request-other-owner",
            trace_id="c" * 32,
            filename="private.md",
            owner_user_id="user-b",
        )
        other_saved = ContentIngestionStore(
            content_repository=content_repository
        ).save_upload_registration(other_owner, source_text=SOURCE_TEXT)

    persisted_json = json.dumps(
        {
            "content_objects": content_repository.content_objects,
            "jobs": queue.jobs,
            "runs": run_repository.records,
        },
        sort_keys=True,
    )
    checks = {
        "restart_duplicate_detected": duplicate["record"]["dedupe"]["status"]
        == "ALREADY_EXISTS",
        "document_lineage_stable": duplicate["record"]["document_id"]
        == first["record"]["document_id"],
        "upload_lineage_stable": duplicate["record"]["upload_id"]
        == first["record"]["upload_id"],
        "job_lineage_stable": duplicate["admission"]["job"]
        == first["admission"]["job"],
        "run_lineage_stable": duplicate["admission"]["ingestion_run"]
        == first["admission"]["ingestion_run"],
        "single_durable_job": len(queue.jobs) == 1,
        "single_durable_run": len(run_repository.records) == 1,
        "owner_scope_isolated": other_saved["document_id"]
        != first["record"]["document_id"],
        "private_payload_absent": SOURCE_TEXT not in persisted_json,
        "source_file_metadata_shared_only": len(content_repository.source_files) == 1,
    }
    issues = sorted(name for name, passed in checks.items() if not passed)
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1345",
        "requirement": "S135",
        "status": "PASS" if not issues else "FAIL",
        "checks": checks,
        "issues": issues,
        "durable_counts": {
            "source_files": len(content_repository.source_files),
            "content_objects": len(content_repository.content_objects),
            "ingestion_jobs": len(queue.jobs),
            "ingestion_runs": len(run_repository.records),
        },
        "database_used": "in_memory_restart_regression",
        "actual_postgres_deferred_to": "1350",
        "next_slice": "1346",
    }


def _register_and_admit(
    store: ContentIngestionStore,
    *,
    content_repository: InMemoryCxContentRepository,
    queue: InMemoryJobQueue,
    run_repository: InMemoryIngestionRunRepository,
    config: CxStorageConfig,
    request_id: str,
    trace_id: str,
    filename: str,
) -> dict[str, Any]:
    record = _build_registration(
        config,
        request_id=request_id,
        trace_id=trace_id,
        filename=filename,
    )
    saved = store.save_upload_registration(record, source_text=SOURCE_TEXT)
    admission = admit_durable_ingestion(
        saved,
        job_queue=queue,
        run_repository=run_repository,
    )
    return {
        "record": store.bind_durable_ingestion_admission(saved, admission),
        "admission": admission,
        "content_object_count": len(content_repository.content_objects),
    }


def _build_registration(
    config: CxStorageConfig,
    *,
    request_id: str,
    trace_id: str,
    filename: str,
    owner_user_id: str = "user-a",
) -> dict[str, Any]:
    return build_upload_registration(
        {
            "filename": filename,
            "content_type": "text/markdown",
            "content_text": SOURCE_TEXT,
            "tenant_id": "tenant-a",
            "owner_user_id": owner_user_id,
        },
        storage_config=config,
        request_id=request_id,
        trace_id=trace_id,
    )


def _storage_config(data_root: Path) -> CxStorageConfig:
    return CxStorageConfig(
        data_root=data_root,
        source_root=data_root / "source-files",
        extracted_markdown_root=data_root / "extracted-markdown",
        extraction_temp_root=data_root / "temp",
        chunk_policy="chunk_1000_100",
        chunk_size=1000,
        chunk_overlap=100,
        bm25_tokenizer="mecab_ko",
        bm25_tokenizer_fallback="korean_mixed_v1",
    )


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") != "PASS":
        return f"cx_upload_admission_lineage=fail issues={len(evidence.get('issues') or [])}"
    checks = evidence.get("checks") or {}
    counts = evidence.get("durable_counts") or {}
    return (
        "cx_upload_admission_lineage=pass "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"jobs={counts.get('ingestion_jobs')} runs={counts.get('ingestion_runs')} "
        f"next={evidence.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_cx_upload_admission_lineage()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
