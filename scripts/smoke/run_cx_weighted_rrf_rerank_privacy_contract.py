#!/usr/bin/env python3
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "_shared", ROOT / "services" / "nex-cx"):
    sys.path.insert(0, str(path))

from nex_cx.access_context import CxAccessContext  # noqa: E402
from nex_cx.hybrid_ranking import (  # noqa: E402
    HybridRankingError,
    HybridRankingPolicy,
    rank_permission_filtered_candidates,
)


SCHEMA_VERSION = "cx_weighted_rrf_rerank_privacy_contract.v1"
QUERY = "private retrieval query"
DOCUMENT_ID = "s95-owner-document"
CHUNK_ONE = "s95-owner-chunk-one"
CHUNK_TWO = "s95-owner-chunk-two"
PRIVATE_TEXTS = {
    CHUNK_ONE: "PRIVATE_S95_ONE",
    CHUNK_TWO: "PRIVATE_S95_TWO",
}


class _OwnerTextLoader:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def load_authorized_texts(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(deepcopy(kwargs))
        return [
            {
                **ref,
                "chunk_text": PRIVATE_TEXTS[ref["chunk_id"]],
                "text_sha256": _digest(PRIVATE_TEXTS[ref["chunk_id"]]),
            }
            for ref in reversed(kwargs["chunk_refs"])
        ]


class _Reranker:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def rerank_documents(
        self,
        query: str,
        documents: list[str],
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.calls.append({"query": query, "documents": list(documents), **kwargs})
        return {
            "alias": "mock-s95-reranker",
            "model_revision": "bf16",
            "deployment_id": "contract-local",
            "results": [
                {"index": 1, "score": 0.98},
                {"index": 0, "score": 0.81},
            ],
        }


def run_cx_weighted_rrf_rerank_privacy_contract() -> dict[str, Any]:
    context = _context()
    loader = _OwnerTextLoader()
    reranker = _Reranker()
    call = {
        "access_context": context,
        "query_text": QUERY,
        "candidate_set": _candidate_set(),
        "policy": HybridRankingPolicy(rerank_candidate_limit=2),
        "text_loader": loader,
        "rerank_client": reranker,
    }
    first = rank_permission_filtered_candidates(**call)
    second = rank_permission_filtered_candidates(**call)

    drift_rejected = False
    drifted = _candidate_set()
    drifted["permission_snapshot"]["actor_id"] = "other-owner"
    try:
        rank_permission_filtered_candidates(
            **{
                **call,
                "candidate_set": drifted,
                "text_loader": _OwnerTextLoader(),
                "rerank_client": _Reranker(),
            }
        )
    except HybridRankingError as exc:
        drift_rejected = (
            exc.error_code == "CX_RETRIEVAL_PERMISSION_CONTINUITY_INVALID"
        )

    serialized = json.dumps(first, sort_keys=True)
    expected_refs = [
        {"content_object_id": DOCUMENT_ID, "chunk_id": CHUNK_ONE},
        {"content_object_id": DOCUMENT_ID, "chunk_id": CHUNK_TWO},
    ]
    checks = {
        "schema_current": (
            first["ranked_candidate_set_schema_version"]
            == "cx_hybrid_ranked_candidate_set.v1"
        ),
        "permission_continuity_verified": (
            first["permission_continuity_verified"] is True
            and first["permission_snapshot"]["actor_id"] == context.subject_id
        ),
        "canonical_weighted_rrf": first["ranking_policy"]
        == {
            "policy_id": "weighted_rrf_vector_bm25_v1",
            "vector_weight": 0.7,
            "bm25_weight": 0.3,
            "rrf_k": 60,
            "rerank_candidate_limit": 2,
        },
        "authorized_refs_only": loader.calls[0]["chunk_refs"] == expected_refs,
        "authorized_text_only": reranker.calls[0]["documents"]
        == [PRIVATE_TEXTS[CHUNK_ONE], PRIVATE_TEXTS[CHUNK_TWO]],
        "rerank_applied": (
            first["rerank_state"] == "APPLIED"
            and first["candidates"][0]["chunk_id"] == CHUNK_TWO
            and first["candidates"][0]["scores"]["rerank_score"] == 0.98
        ),
        "query_hash_bound": first["query_sha256"] == _digest(QUERY),
        "private_payload_not_returned": (
            QUERY not in serialized
            and all(text not in serialized for text in PRIVATE_TEXTS.values())
        ),
        "permission_drift_rejected": drift_rejected,
        "deterministic_result": first == second,
    }
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "contract_schema_version": SCHEMA_VERSION,
        "status": "PASS" if not failed else "FAIL",
        "checks": checks,
        "passed_checks": sum(checks.values()),
        "failed_checks": failed,
        "policy_id": first["ranking_policy"]["policy_id"],
        "rerank_state": first["rerank_state"],
        "postgres_required": False,
        "remote_provider_required": False,
    }


def _context() -> CxAccessContext:
    return CxAccessContext(
        caller_service_id="nex-cx",
        tenant_id="s95-tenant",
        subject_id="s95-owner",
        request_id="s95-0946-request",
        trace_id="94600000000000000000000000000001",
        scopes=("service:call",),
    )


def _candidate_set() -> dict[str, Any]:
    return {
        "hybrid_candidate_set_schema_version": "cx_hybrid_candidate_set.v1",
        "permission_policy": "cx.private_owner_active.v1",
        "permission_enforced_before_candidates": True,
        "query_sha256": _digest(QUERY),
        "permission_snapshot": {
            "permission_snapshot_schema_version": (
                "cx_retrieval_permission_snapshot.v1"
            ),
            "actor_type": "oa.user",
            "actor_id": "s95-owner",
            "tenant_ref": {"type": "oa.tenant", "id": "s95-tenant"},
            "scope_applied": {
                "type": "document_ids",
                "document_ids": [DOCUMENT_ID],
            },
            "visible_document_count": 1,
            "policy_version": "cx.private_owner_active.v1",
        },
        "lexical_candidates": {
            "candidate_source": "postgresql_bm25",
            "candidate_count": 2,
            "candidates": [
                _lexical_candidate(CHUNK_ONE, 2.0),
                _lexical_candidate(CHUNK_TWO, 1.0),
            ],
        },
        "vector_candidates": {
            "candidate_source": "postgresql_pgvector",
            "candidate_count": 2,
            "candidates": [
                _vector_candidate(CHUNK_ONE, 0.9),
                _vector_candidate(CHUNK_TWO, 0.8),
            ],
        },
    }


def _lexical_candidate(chunk_id: str, score: float) -> dict[str, Any]:
    return {
        "lexical_candidate_schema_version": "cx_lexical_candidate.v1",
        "candidate_source": "postgresql_bm25",
        "content_object_id": DOCUMENT_ID,
        "chunk_id": chunk_id,
        "text_sha256": _digest(PRIVATE_TEXTS[chunk_id]),
        "bm25_score": score,
    }


def _vector_candidate(chunk_id: str, score: float) -> dict[str, Any]:
    return {
        "vector_candidate_schema_version": "cx_vector_candidate.v1",
        "candidate_source": "postgresql_pgvector",
        "content_object_id": DOCUMENT_ID,
        "chunk_id": chunk_id,
        "vector_score": score,
    }


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def summary_line(result: dict[str, Any]) -> str:
    checks = result.get("checks", {})
    return (
        "cx_weighted_rrf_rerank_privacy_contract="
        f"{str(result.get('status')).lower()} "
        f"checks={result.get('passed_checks', 0)}/{len(checks)} "
        "postgres_required=False remote_required=False"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_cx_weighted_rrf_rerank_privacy_contract()
    if args.summary:
        print(summary_line(result))
    else:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
