#!/usr/bin/env python3
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from typing import Any
from uuid import NAMESPACE_URL, uuid5


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "_shared", ROOT / "services" / "nex-cx"):
    sys.path.insert(0, str(path))

from nex_cx.access_context import CxAccessContext  # noqa: E402
from nex_cx.hybrid_candidate_orchestration import (  # noqa: E402
    orchestrate_permission_filtered_candidates,
)
from nex_cx.retrieval_permissions import RetrievalPermissionError  # noqa: E402
from nex_cx.vector_index_freshness import (  # noqa: E402
    build_embedding_profile,
    build_source_snapshot,
    build_vector_index_manifest,
    build_vector_payload_snapshot,
    mark_vector_index_ready,
)
from nex_cx.vector_index_repository import (  # noqa: E402
    InMemoryVectorIndexRepository,
)


SCHEMA_VERSION = "cx_permission_first_hybrid_orchestration.v1"


class _LexicalStore:
    def __init__(self, candidate: dict[str, Any]) -> None:
        self._candidate = candidate
        self.calls = 0

    def search(self, **_kwargs: Any) -> list[dict[str, Any]]:
        self.calls += 1
        return [deepcopy(self._candidate)]


class _BoundVectorStore:
    def __init__(
        self,
        snapshot: dict[str, Any],
        match: dict[str, Any],
    ) -> None:
        self._snapshot = snapshot
        self._match = match
        self.search_calls = 0

    def payload_snapshot(self, **_kwargs: Any) -> dict[str, Any]:
        return deepcopy(self._snapshot)

    def search(self, **_kwargs: Any) -> list[dict[str, Any]]:
        self.search_calls += 1
        return [deepcopy(self._match)]


class _VectorStore:
    def __init__(self, index_id: str, bound: _BoundVectorStore) -> None:
        self._index_id = index_id
        self._bound = bound

    def bind_index(self, manifest: dict[str, Any]) -> _BoundVectorStore:
        if manifest["vector_index_id"] != self._index_id:
            raise KeyError("unexpected vector index")
        return self._bound


def run_cx_permission_first_hybrid_orchestration() -> dict[str, Any]:
    fixture = _fixture()
    lexical = _LexicalStore(fixture["lexical_candidate"])
    repository = InMemoryVectorIndexRepository()
    repository.create(fixture["manifest"])
    bound = _BoundVectorStore(fixture["payload_snapshot"], fixture["vector_match"])
    vector_store = _VectorStore(fixture["manifest"]["vector_index_id"], bound)
    context = _context()
    call_args = {
        "access_context": context,
        "query_text": "alpha beta",
        "requested_document_ids": [fixture["document_id"]],
        "content_objects": {
            fixture["document_id"]: _content(fixture["document_id"])
        },
        "lexical_store": lexical,
        "vector_targets_by_document_id": {
            fixture["document_id"]: fixture["vector_target"]
        },
        "query_vector": (1.0, 0.0),
        "vector_repository": repository,
        "vector_store": vector_store,
    }
    first = orchestrate_permission_filtered_candidates(**call_args)
    second = orchestrate_permission_filtered_candidates(**call_args)

    denied_lexical = _LexicalStore(fixture["lexical_candidate"])
    denied_before_candidates = False
    try:
        orchestrate_permission_filtered_candidates(
            **{
                **call_args,
                "requested_document_ids": ["foreign-document"],
                "content_objects": {
                    "foreign-document": _content(
                        "foreign-document",
                        owner="other-owner",
                    )
                },
                "lexical_store": denied_lexical,
            }
        )
    except RetrievalPermissionError as exc:
        denied_before_candidates = exc.status_code == 404 and denied_lexical.calls == 0

    forbidden_keys = {"query_text", "query_vector", "embedding", "vector"}
    checks = {
        "schema_current": (
            first["hybrid_candidate_set_schema_version"]
            == "cx_hybrid_candidate_set.v1"
        ),
        "permission_first_order": first["stage_order"][0] == "permission_filter",
        "permission_snapshot_measured": (
            first["permission_snapshot"]["visible_document_count"] == 1
            and first["permission_snapshot"]["filtered_document_count"] == 0
        ),
        "owner_bm25_candidate_generated": (
            first["lexical_candidates"]["candidate_count"] == 1
        ),
        "fresh_vector_candidate_generated": (
            first["vector_candidates"]["candidate_count"] == 1
            and first["vector_candidates"]["status"] == "READY"
        ),
        "denied_scope_stops_before_candidates": denied_before_candidates,
        "query_is_hash_bound": (
            first["query_sha256"]
            == hashlib.sha256(b"alpha beta").hexdigest()
        ),
        "private_payload_not_returned": forbidden_keys.isdisjoint(
            set(_all_keys(first))
        ),
        "deterministic_result": first == second,
    }
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "contract_schema_version": SCHEMA_VERSION,
        "status": "PASS" if not failed else "FAIL",
        "checks": checks,
        "passed_checks": sum(checks.values()),
        "failed_checks": failed,
        "permission_policy": first["permission_policy"],
        "tokenizer_used": first["tokenizer_profile"]["bm25_tokenizer"],
        "tokenizer_fallback_used": first["tokenizer_profile"]["fallback_used"],
        "postgres_required": False,
        "remote_provider_required": False,
    }


def _fixture() -> dict[str, Any]:
    document_id = str(uuid5(NAMESPACE_URL, "s95:0945:document"))
    chunk_id = str(uuid5(NAMESPACE_URL, "s95:0945:chunk"))
    source = build_source_snapshot(
        chunk_set_id=str(uuid5(NAMESPACE_URL, "s95:0945:chunk-set")),
        chunk_policy_id="1000_100",
        source_markdown_sha256=_digest("source"),
        chunks=[
            {
                "chunk_id": chunk_id,
                "ordinal": 0,
                "text_sha256": _digest("chunk"),
            }
        ],
    )
    profile = build_embedding_profile(
        provider_alias="mock-s95",
        model_profile_id="Qwen3-Embedding-4B",
        model_revision="bf16",
        deployment_id="contract-local",
        vector_dimension=2,
    )
    manifest = build_vector_index_manifest(
        content_object_id=document_id,
        tenant_ref={"type": "oa.tenant", "id": "s95-tenant"},
        owner_subject_ref={"type": "oa.user", "id": "s95-owner"},
        source_snapshot=source,
        embedding_profile=profile,
        trace_id="s95-0945-trace",
        request_id="s95-0945-request",
        observed_at="2026-09-22T03:00:00Z",
    )
    receipt = {
        "chunk_id": chunk_id,
        "embedding_sha256": _digest("embedding"),
        "vector_dimension": 2,
        "storage_uri": f"cx-private://pgvector/{manifest['vector_index_id']}/{chunk_id}",
    }
    manifest = mark_vector_index_ready(
        manifest,
        payload_receipts=[receipt],
        observed_at="2026-09-22T03:01:00Z",
    )
    return {
        "document_id": document_id,
        "manifest": manifest,
        "payload_snapshot": build_vector_payload_snapshot([receipt]),
        "vector_match": {"chunk_id": chunk_id, "score": 1.0, "distance": 0.0},
        "vector_target": {
            "content_object_id": document_id,
            "vector_index_id": manifest["vector_index_id"],
            "source_snapshot": source,
            "embedding_profile": profile,
            "permission_decision": {
                "visible": True,
                "policy_version": "cx.private_owner_active.v1",
            },
        },
        "lexical_candidate": {
            "lexical_candidate_schema_version": "cx_lexical_candidate.v1",
            "candidate_source": "postgresql_bm25",
            "content_object_id": document_id,
            "chunk_id": chunk_id,
            "bm25_score": 1.25,
            "text_preview": "authorized alpha beta preview",
        },
    }


def _context() -> CxAccessContext:
    return CxAccessContext(
        caller_service_id="nex-cx",
        tenant_id="s95-tenant",
        subject_id="s95-owner",
        request_id="s95-0945-request",
        trace_id="94500000000000000000000000000001",
        scopes=("service:call",),
    )


def _content(document_id: str, *, owner: str = "s95-owner") -> dict[str, Any]:
    return {
        "content_object_id": document_id,
        "tenant_ref": {"type": "oa.tenant", "id": "s95-tenant"},
        "owner_subject_ref": {"type": "oa.user", "id": owner},
        "lifecycle_status": "ACTIVE",
    }


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _all_keys(value: object) -> list[str]:
    if isinstance(value, dict):
        keys: list[str] = []
        for key, item in value.items():
            keys.append(str(key))
            keys.extend(_all_keys(item))
        return keys
    if isinstance(value, list):
        keys = []
        for item in value:
            keys.extend(_all_keys(item))
        return keys
    return []


def summary_line(result: dict[str, Any]) -> str:
    checks = result.get("checks", {})
    return (
        "cx_permission_first_hybrid_orchestration="
        f"{str(result.get('status')).lower()} "
        f"checks={result.get('passed_checks', 0)}/{len(checks)} "
        "postgres_required=False remote_required=False"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_cx_permission_first_hybrid_orchestration()
    if args.summary:
        print(summary_line(result))
    else:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
