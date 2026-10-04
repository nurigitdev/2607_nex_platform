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

from nex_cx.chunking import build_and_store_chunk_set
from nex_cx.ingestion import (
    ContentIngestionStore,
    CxStorageConfig,
    build_upload_registration,
    run_text_extraction_job,
)
from nex_cx.ingestion_hydration import hydrate_ingestion_runtime
from nex_cx.ingestion_orchestration import build_ingestion_run
from nex_cx.lexical_index import build_and_store_lexical_index
from nex_cx.repository import InMemoryCxContentRepository


SCHEMA_VERSION = "cx_ingestion_worker_hydration_evidence.v1"
PRIVATE_SOURCE = "private-s135 restart-safe markdown with BM25 lexical terms"
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"


def run_cx_ingestion_worker_hydration() -> dict[str, Any]:
    with TemporaryDirectory(prefix="nex-s135-1346-") as data_root:
        config = _storage_config(Path(data_root))
        repository = InMemoryCxContentRepository()
        initial = ContentIngestionStore(content_repository=repository)
        registration = build_upload_registration(
            {
                "filename": "restart.md",
                "content_type": "text/markdown",
                "content_text": PRIVATE_SOURCE,
                "tenant_id": "tenant-1346",
                "owner_user_id": "owner-1346",
            },
            storage_config=config,
            request_id="request-1346",
            trace_id=TRACE_ID,
        )
        saved = initial.save_upload_registration(
            registration,
            source_text=PRIVATE_SOURCE,
        )
        extraction = run_text_extraction_job(
            saved["ingestion_job"]["job_id"],
            store=initial,
            storage_config=config,
            request_id="request-1346",
            trace_id=TRACE_ID,
        )
        chunk_set = build_and_store_chunk_set(
            saved["document_id"],
            store=initial,
            storage_config=config,
            request_id="request-1346",
            trace_id=TRACE_ID,
        )
        lexical = build_and_store_lexical_index(
            saved["document_id"],
            store=initial,
            storage_config=config,
            request_id="request-1346",
            trace_id=TRACE_ID,
        )
        run = build_ingestion_run(
            document_id=saved["document_id"],
            job_id=saved["ingestion_job"]["job_id"],
            idempotency_key=saved["upload_id"],
            tenant_ref={"type": "oa.tenant", "id": "tenant-1346"},
            owner_subject_ref={"type": "oa.user", "id": "owner-1346"},
            trace_id=TRACE_ID,
            request_id="request-1346",
            created_at=saved["created_at"],
        )
        restarted = ContentIngestionStore(content_repository=repository)
        hydration = hydrate_ingestion_runtime(
            run,
            store=restarted,
            storage_config=config,
        )
        reconstructed = [
            restarted.get_chunk_text(chunk["chunk_id"])
            for chunk in chunk_set["chunks"]
        ]
        evidence_text = json.dumps(hydration, sort_keys=True)

    checks = {
        "source_lineage_hydrated": hydration["source_file_hydrated"] is True,
        "extraction_hydrated": hydration["extraction_hydrated"] is True,
        "chunk_set_hydrated": hydration["chunk_set_hydrated"] is True,
        "chunk_count_matches": hydration["private_chunk_count"]
        == chunk_set["chunk_count"],
        "private_chunks_reconstructed": reconstructed
        == [initial.get_chunk_text(chunk["chunk_id"]) for chunk in chunk_set["chunks"]],
        "lexical_index_hydrated": hydration["lexical_index_hydrated"] is True,
        "lexical_postings_match": restarted.get_lexical_index(saved["document_id"])[
            "postings"
        ]
        == lexical["postings"],
        "markdown_hash_matches": restarted.get_extraction_result(saved["document_id"])[
            "extracted_markdown_sha256"
        ]
        == extraction["extracted_markdown_sha256"],
        "private_payload_absent_from_evidence": PRIVATE_SOURCE not in evidence_text,
        "database_private_chunk_absent": PRIVATE_SOURCE
        not in json.dumps(repository.chunk_sets, sort_keys=True),
    }
    issues = sorted(name for name, passed in checks.items() if not passed)
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1346",
        "requirement": "S135",
        "status": "PASS" if not issues else "FAIL",
        "checks": checks,
        "issues": issues,
        "hydration": hydration,
        "durable_stage_count": 3,
        "private_chunk_reconstruction": "markdown_offsets_and_sha256",
        "database_used": "in_memory_restart_regression",
        "actual_postgres_deferred_to": "1350",
        "next_slice": "1347",
    }


def _storage_config(data_root: Path) -> CxStorageConfig:
    return CxStorageConfig(
        data_root=data_root,
        source_root=data_root / "source-files",
        extracted_markdown_root=data_root / "extracted-markdown",
        extraction_temp_root=data_root / "temp",
        chunk_policy="chunk_20_5",
        chunk_size=20,
        chunk_overlap=5,
        bm25_tokenizer="korean_mixed_v1",
        bm25_tokenizer_fallback="korean_mixed_v1",
    )


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") != "PASS":
        return f"cx_ingestion_worker_hydration=fail issues={len(evidence.get('issues') or [])}"
    checks = evidence.get("checks") or {}
    hydration = evidence.get("hydration") or {}
    return (
        "cx_ingestion_worker_hydration=pass "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"chunks={hydration.get('private_chunk_count')} next={evidence.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_cx_ingestion_worker_hydration()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
