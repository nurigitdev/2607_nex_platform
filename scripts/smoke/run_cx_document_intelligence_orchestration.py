#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "_shared", ROOT / "services" / "nex-cx"):
    sys.path.insert(0, str(path))

from nex_cx.access_context import CxAccessContext  # noqa: E402
from nex_cx.document_intelligence_orchestration import (  # noqa: E402
    run_document_intelligence,
    search_similar_document_summaries,
)
from nex_cx.ingestion import (  # noqa: E402
    ContentIngestionStore,
    CxStorageConfig,
    build_upload_registration,
    run_text_extraction_job,
)
from nex_cx.private_content import build_private_payload_receipt  # noqa: E402
from nex_cx.private_text_store import FileSystemCxPrivateTextStore  # noqa: E402


REQUEST_ID = "request-0957-evidence"
TRACE_ID = "95700000000000000000000000000002"
TENANT_ID = "tenant-0957"
OWNER_ID = "owner-0957"


class _GenerationClient:
    def create_generation(self, payload, *, request_id, trace_id):
        return {
            "mo_generation_id": "mo-summary-0957-evidence",
            "alias": "general-llm-default",
            "model_revision": "Qwen3.5-122B-A10B-NVFP4",
            "deployment_id": "mock-generation-0957",
            "provider_type": "mock-generation",
            "output": {
                "type": "text",
                "text": "Production launch is approved for 2026-10-01.",
            },
            "finish_reason": "STOP",
            "usage": {"input_tokens": 20, "output_tokens": 9, "total_tokens": 29},
        }


class _EmbeddingClient:
    def create_embeddings(self, inputs, *, alias, request_id, trace_id):
        return {
            "object": "list",
            "alias": alias,
            "model_revision": "Qwen3-Embedding-4B",
            "deployment_id": "mock-embedding-0957",
            "data": [
                {"object": "embedding", "index": 0, "embedding": [0.1, 0.2, 0.3]}
            ],
            "usage": {"input_tokens": 9, "output_tokens": 0, "total_tokens": 9},
        }


class _BoundVectorStore:
    def __init__(self, parent, binding):
        self.parent = parent
        self.binding = binding

    def put_vector(
        self, *, access_context, key, vector, expected_sha256
    ):
        values = tuple(float(value) for value in vector)
        self.parent.vectors[str(self.binding.document_summary_id)] = values
        return build_private_payload_receipt(
            key=key,
            storage_backend="deterministic-summary-vector-v1",
            storage_uri=f"cx-private://deterministic/{self.binding.summary_vector_id}",
            sha256=expected_sha256,
            size_bytes=len(values) * 4,
            vector_dimension=len(values),
        )

    def get_vector(
        self,
        *,
        access_context,
        key,
        expected_sha256,
        expected_dimension,
    ):
        return self.parent.vectors.get(str(self.binding.document_summary_id))

    def freshness(self, *, access_context):
        return {
            "freshness_schema_version": "cx_summary_vector_freshness.v1",
            "state": "READY",
            "usable": True,
            "reasons": [],
            "document_summary_id": str(self.binding.document_summary_id),
            "summary_embedding_id": str(self.binding.summary_embedding_id),
            "profile_fingerprint": self.binding.profile_fingerprint,
        }


class _VectorStore:
    def __init__(self):
        self.vectors = {}

    def bind_summary(self, binding):
        return _BoundVectorStore(self, binding)


class _SimilarityStore:
    def __init__(self):
        self.call: dict[str, Any] = {}

    def search(self, **kwargs):
        self.call = kwargs
        return {
            "summary_similarity_result_schema_version": (
                "cx_summary_similarity_result.v1"
            ),
            "candidate_count": 1,
            "candidates": [
                {
                    "content_object_id": "00000000-0000-0000-0000-000000000002",
                    "similarity_score": 0.92,
                }
            ],
        }


def run_cx_document_intelligence_orchestration(
    work_root: Path | None = None,
) -> dict[str, object]:
    if work_root is None:
        with TemporaryDirectory(prefix="nex-cx-0957-") as temporary_root:
            return _run(Path(temporary_root))
    return _run(work_root)


def _run(work_root: Path) -> dict[str, object]:
    config = CxStorageConfig(
        data_root=work_root,
        source_root=work_root / "source",
        extracted_markdown_root=work_root / "markdown",
        extraction_temp_root=work_root / "temp",
        chunk_policy="chunk_1000_100",
        chunk_size=1000,
        chunk_overlap=100,
        bm25_tokenizer="mecab_ko",
        bm25_tokenizer_fallback="korean_mixed_v1",
    )
    store = ContentIngestionStore(
        private_summary_text_store=FileSystemCxPrivateTextStore(
            work_root / "private-summary"
        )
    )
    source_text = "# Release\n\nProduction launch is approved for 2026-10-01."
    document = build_upload_registration(
        {
            "filename": "release.md",
            "content_type": "text/markdown",
            "content_text": source_text,
            "tenant_ref": {"type": "oa.tenant", "id": TENANT_ID},
            "owner_subject_ref": {"type": "oa.user", "id": OWNER_ID},
        },
        storage_config=config,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    store.save_upload_registration(document, source_text=source_text)
    extraction = run_text_extraction_job(
        document["extraction"]["job_id"],
        store=store,
        storage_config=config,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    document_id = str(extraction["document_id"])
    context = CxAccessContext(
        caller_service_id="nex-cx",
        tenant_id=TENANT_ID,
        subject_id=OWNER_ID,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        scopes=("service:call",),
    )
    vectors = _VectorStore()
    run_result = run_document_intelligence(
        access_context=context,
        document_id=document_id,
        store=store,
        generation_client=_GenerationClient(),
        embedding_client=_EmbeddingClient(),
        embedding_alias="qwen3-embedding-4b",
        summary_vector_store=vectors,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    similarity_store = _SimilarityStore()
    similarity_result = search_similar_document_summaries(
        access_context=context,
        document_id=document_id,
        store=store,
        summary_vector_store=vectors,
        summary_similarity_store=similarity_store,
        limit=5,
        minimum_score=0.5,
    )
    checks = {
        "run_ready": run_result["status"] == "READY",
        "summary_bounded": run_result["summary"]["summary_char_count"] < 1000,
        "summary_private_uri": str(
            run_result["summary"]["summary_storage_uri"]
        ).startswith("cx-private://filesystem-text-v1/"),
        "generation_profile": run_result["summary"]["summarizer"][
            "model_revision"
        ]
        == "Qwen3.5-122B-A10B-NVFP4",
        "embedding_profile": run_result["summary_embedding"]["model_revision"]
        == "Qwen3-Embedding-4B",
        "vector_fresh": run_result["summary_vector"]["freshness"]["usable"]
        is True,
        "raw_payload_absent": run_result["raw_summary_included"] is False
        and run_result["raw_vector_included"] is False,
        "similar_candidate": similarity_result["result"]["candidate_count"] == 1,
        "source_excluded": similarity_store.call["exclude_content_object_id"]
        == document_id,
        "owner_propagated": similarity_store.call["access_context"].tenant_id
        == TENANT_ID
        and similarity_store.call["access_context"].subject_id == OWNER_ID,
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "check_count": len(checks),
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "candidate_count": similarity_result["result"]["candidate_count"],
        "postgres_required": False,
        "remote_required": False,
    }


def _format_summary(result: dict[str, object]) -> str:
    return (
        f"cx_document_intelligence_orchestration={str(result['status']).lower()} "
        f"checks={result['check_count'] - len(result['failed_checks'])}/"
        f"{result['check_count']} candidates={result['candidate_count']} "
        "postgres_required=False remote_required=False"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    result = run_cx_document_intelligence_orchestration()
    print(_format_summary(result) if args.summary else json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
