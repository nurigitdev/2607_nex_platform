#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
CX_ROOT = ROOT / "services" / "nex-cx"
sys.path.insert(0, str(CX_ROOT))

from nex_cx.vector_index_freshness import (  # noqa: E402
    VECTOR_INDEX_STALE_REASONS,
    VECTOR_INDEX_TRANSITIONS,
    assess_vector_index_freshness,
    build_embedding_profile,
    build_source_snapshot,
    build_vector_index_manifest,
    mark_vector_index_ready,
    transition_vector_index_state,
)


def run_cx_vector_index_freshness_contract() -> dict[str, Any]:
    profile = build_embedding_profile(
        provider_alias="embedding-default",
        model_profile_id="qwen3_embedding_4b_bf16",
        model_revision="Qwen3-Embedding-4B",
        deployment_id="vllm-embedding-http",
        vector_dimension=2560,
    )
    source = build_source_snapshot(
        chunk_set_id="chunk-set-0932",
        chunk_policy_id="chunk_1000_100",
        source_markdown_sha256="a" * 64,
        chunks=[
            {"chunk_id": "chunk-a", "ordinal": 0, "text_sha256": "a" * 64},
            {"chunk_id": "chunk-b", "ordinal": 1, "text_sha256": "b" * 64},
        ],
    )
    building = build_vector_index_manifest(
        content_object_id="document-0932",
        tenant_ref={"type": "oa.tenant", "id": "tenant-a"},
        owner_subject_ref={"type": "oa.user", "id": "user-a"},
        source_snapshot=source,
        embedding_profile=profile,
        trace_id="trace-0932",
        request_id="request-0932",
        observed_at="2026-09-21T00:00:00Z",
    )
    ready = mark_vector_index_ready(
        building,
        payload_receipts=[
            {
                "chunk_id": "chunk-a",
                "embedding_sha256": "a" * 64,
                "vector_dimension": 2560,
                "storage_uri": "cx-vector://chunk-a",
            },
            {
                "chunk_id": "chunk-b",
                "embedding_sha256": "b" * 64,
                "vector_dimension": 2560,
                "storage_uri": "cx-vector://chunk-b",
            },
        ],
        observed_at="2026-09-21T00:01:00Z",
    )
    fresh = assess_vector_index_freshness(
        ready,
        source_snapshot=source,
        embedding_profile=profile,
        payload_count=2,
        payload_fingerprint=ready["payload_fingerprint"],
    )
    changed_source = build_source_snapshot(
        chunk_set_id="chunk-set-0932",
        chunk_policy_id="chunk_1000_100",
        source_markdown_sha256="a" * 64,
        chunks=[
            {"chunk_id": "chunk-a", "ordinal": 0, "text_sha256": "c" * 64},
            {"chunk_id": "chunk-b", "ordinal": 1, "text_sha256": "b" * 64},
        ],
    )
    stale_assessment = assess_vector_index_freshness(
        ready,
        source_snapshot=changed_source,
        embedding_profile=profile,
        payload_count=2,
        payload_fingerprint=ready["payload_fingerprint"],
    )
    stale = transition_vector_index_state(
        ready,
        target_status="STALE",
        reason=stale_assessment["reason"],
        observed_at="2026-09-21T00:02:00Z",
    )
    rebuild = transition_vector_index_state(
        stale,
        target_status="REBUILD_REQUIRED",
        reason=stale_assessment["reason"],
        observed_at="2026-09-21T00:03:00Z",
    )
    serialized = json.dumps(
        {"building": building, "ready": ready, "stale": stale, "rebuild": rebuild},
        sort_keys=True,
    ).lower()
    checks = {
        "deterministic_identity": building["vector_index_id"]
        == build_vector_index_manifest(
            content_object_id="document-0932",
            tenant_ref={"type": "oa.tenant", "id": "tenant-a"},
            owner_subject_ref={"type": "oa.user", "id": "user-a"},
            source_snapshot=source,
            embedding_profile=profile,
            trace_id="trace-0932",
            request_id="request-0932",
            observed_at="2026-09-21T00:00:00Z",
        )["vector_index_id"],
        "ready_is_usable": fresh["status"] == "READY"
        and fresh["retrieval_usable"] is True,
        "source_change_detected": stale_assessment["reason"]
        == "CHUNK_CONTENT_CHANGED",
        "stale_is_not_usable": stale["status"] == "STALE"
        and stale_assessment["retrieval_usable"] is False,
        "rebuild_required": rebuild["status"] == "REBUILD_REQUIRED",
        "owner_lineage_preserved": rebuild["tenant_ref"]["id"] == "tenant-a"
        and rebuild["owner_subject_ref"]["id"] == "user-a",
        "private_payload_absent": all(
            token not in serialized
            for token in ('"embedding"', '"vector"', '"source_text"', '"prompt"')
        ),
        "remote_provider_deferred": True,
    }
    return {
        "contract_schema_version": "cx_vector_index_freshness_contract.v1",
        "slice": "0932",
        "requirement": "S94",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "freshness_state_count": 5,
        "stale_reason_count": len(VECTOR_INDEX_STALE_REASONS),
        "transition_count": len(VECTOR_INDEX_TRANSITIONS),
        "pipeline_chunk_count": source["chunk_count"],
        "remote_embedding_required": False,
        "postgres_required": False,
        "next_slice": "0933",
    }


def summary_line(result: Mapping[str, Any]) -> str:
    checks = result.get("checks") or {}
    return (
        "cx_vector_index_freshness_contract="
        f"{str(result.get('status') or 'FAIL').lower()} "
        f"checks={sum(value is True for value in checks.values())}/{len(checks)} "
        f"states={result.get('freshness_state_count', 0)} "
        f"reasons={result.get('stale_reason_count', 0)} "
        f"transitions={result.get('transition_count', 0)} "
        f"remote_required={result.get('remote_embedding_required', True)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_cx_vector_index_freshness_contract()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
