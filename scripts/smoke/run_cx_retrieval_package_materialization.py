#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "_shared", ROOT / "services" / "nex-cx"):
    sys.path.insert(0, str(path))

from nex_cx.access_context import CxAccessContext  # noqa: E402
from nex_cx.repository import (
    InMemoryCxContentRepository,
    build_retrieval_package_persistence_record,
)  # noqa: E402
from nex_cx.retrieval_materialization import (  # noqa: E402
    RestartSafeRetrievalPackageStore,
)


PACKAGE_ID = "13630000-0000-4000-8000-000000000001"
CONTENT_ID = "13630000-0000-4000-8000-000000000002"
CHUNK_ID = "13630000-0000-4000-8000-000000000003"
EVIDENCE_TEXT = "S137 restart-safe private evidence"


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _context(subject_id: str = "slice-1363-owner") -> CxAccessContext:
    return CxAccessContext(
        caller_service_id="nex-ae-api",
        tenant_id="slice-1363-tenant",
        subject_id=subject_id,
        request_id="slice-1363-request",
        trace_id="1363" * 8,
        scopes=("service.invoke",),
    )


def _package() -> dict[str, Any]:
    permission_snapshot = {
        "permission_snapshot_schema_version": "cx_retrieval_permission_snapshot.v1",
        "actor_type": "oa.user",
        "actor_id": "slice-1363-owner",
        "tenant_ref": {"type": "oa.tenant", "id": "slice-1363-tenant"},
        "scope_applied": {"type": "document_ids", "document_ids": [CONTENT_ID]},
        "policy_version": "cx.private_owner_active.v1",
    }
    return {
        "retrieval_package_schema_version": "cx_retrieval_context_package.v1",
        "retrieval_runtime_schema_version": "cx_permission_hybrid_runtime.v1",
        "retrieval_package_id": PACKAGE_ID,
        "package_hash": "a" * 64,
        "status": "READY",
        "tenant_ref_type": "oa.tenant",
        "tenant_ref_id": "slice-1363-tenant",
        "owner_subject_ref_type": "oa.user",
        "owner_subject_ref_id": "slice-1363-owner",
        "trace_id": "1363" * 8,
        "request_id": "slice-1363-request",
        "query_text": "private query excluded from metadata",
        "persistence_payload_policy": "hash_only_private_owner",
        "query_embedding_snapshot": {
            "provided": True,
            "embedding_sha256": "b" * 64,
            "vector_dimension": 3,
        },
        "purpose": "grounded_answer",
        "retrieval_profile": {
            "search_strategy": "permission_filtered_hybrid",
            "confidence_policy": {"low_confidence_threshold": 0.4},
            "quality_policy": {
                "policy_id": "weighted_rrf_vector_bm25_v1",
                "policy_version": "0001",
                "policy_hash": "c" * 64,
                "policy_source": "cx_permission_filtered_hybrid_runtime",
                "ranker_mix": "weighted_rrf_vector_bm25_v1",
            },
        },
        "permission_snapshot": permission_snapshot,
        "evidence_items": [
            {
                "evidence_id": "13630000-0000-4000-8000-000000000004",
                "rank": 1,
                "content_object_id": CONTENT_ID,
                "content_version_id": _sha256(EVIDENCE_TEXT),
                "chunk_id": CHUNK_ID,
                "chunk_policy_id": "chunk_1000_100",
                "source_anchor": {"type": "character_range", "start_offset": 0, "end_offset": 34},
                "citation_label": "[1]",
                "text": EVIDENCE_TEXT,
                "scores": {"final_score": 0.9},
                "matched_terms": ["restart"],
                "permission_result": {"visible": True},
                "neighbor_context": [],
                "quality_flags": [],
            }
        ],
        "source_summary": {"source_count": 1, "document_count": 1, "chunk_count": 1},
        "score_summary": {
            "best_score": 0.9,
            "ranker_mix": "weighted_rrf_vector_bm25_v1",
            "rerank_state": "APPLIED",
        },
        "warnings": [],
        "no_answer_reason": None,
        "created_at": "2026-10-05T00:00:00Z",
        "updated_at": "2026-10-05T00:00:00Z",
    }


class DeterministicPrivateEvidenceSource:
    def __init__(self) -> None:
        self.read_count = 0

    def load_private_evidence(
        self,
        *,
        access_context: CxAccessContext,
        chunk_refs: Sequence[Mapping[str, str]],
    ) -> list[dict[str, Any]]:
        self.read_count += 1
        return [
            {
                **dict(chunk_refs[0]),
                "chunk_text": EVIDENCE_TEXT,
                "text_sha256": _sha256(EVIDENCE_TEXT),
            }
        ]


def run_cx_retrieval_package_materialization(
    root: Path = ROOT,
) -> dict[str, Any]:
    record = build_retrieval_package_persistence_record(_package())
    repository = InMemoryCxContentRepository()
    repository.save_retrieval_package_record(record)
    source = DeterministicPrivateEvidenceSource()
    store = RestartSafeRetrievalPackageStore(repository, source)

    owner_package = store.get_retrieval_package(
        PACKAGE_ID,
        access_context=_context(),
    )
    denied_package = store.get_retrieval_package(
        PACKAGE_ID,
        access_context=_context("slice-1363-other"),
    )
    migration = root / "database/nex-cx/migrations/1363_cx_retrieval_materialization.sql"
    migration_text = migration.read_text(encoding="utf-8") if migration.is_file() else ""
    checks = {
        "metadata_excludes_private_text": EVIDENCE_TEXT not in str(record),
        "owner_materialization_ready": (
            owner_package is not None
            and owner_package["status"] == "READY"
            and owner_package["evidence_items"][0]["text"] == EVIDENCE_TEXT
        ),
        "cross_owner_hidden_before_read": denied_package is None and source.read_count == 1,
        "evidence_hash_verified": (
            owner_package is not None
            and owner_package["evidence_items"][0]["evidence_text_sha256"]
            == _sha256(EVIDENCE_TEXT)
        ),
        "migration_owner_index_present": "idx_cx_ret_pkg_owner_created" in migration_text,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "cx_retrieval_materialization_evidence.v1",
        "slice": "1363",
        "requirement": "S137",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "summary": {
            "check_count": len(checks),
            "passed_count": sum(checks.values()),
            "private_read_count": source.read_count,
            "materialized_evidence_count": (
                len(owner_package["evidence_items"])
                if owner_package is not None
                else 0
            ),
        },
        "decision": {
            "private_payload_in_postgres": False,
            "owner_check_before_private_read": True,
            "remote_provider_required": False,
            "next_slice": "1364" if passed else "blocked",
        },
    }


def summary_line(result: Mapping[str, Any]) -> str:
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "cx_retrieval_materialization="
        f"{str(result.get('status', 'FAIL')).lower()} "
        f"checks={summary.get('passed_count', 0)}/{summary.get('check_count', 0)} "
        f"private_reads={summary.get('private_read_count', 0)} "
        f"next={decision.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_cx_retrieval_package_materialization()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
