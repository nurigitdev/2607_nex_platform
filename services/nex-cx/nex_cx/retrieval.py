from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import NAMESPACE_URL, uuid5

import httpx
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    issue_mock_service_token,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
    validate_authorization_header,
)

from nex_cx.ingestion import ContentIngestionStore
from nex_cx.lexical_index import query_terms_for_lexical_index

DEFAULT_TOP_K = 5
MAX_TOP_K = 20
LOW_CONFIDENCE_THRESHOLD = 0.2
DEFAULT_RERANK_CANDIDATE_LIMIT = 50
DEFAULT_RERANKER_ALIAS = "mock-reranker-default"
ALLOWED_PURPOSES = {
    "search",
    "grounded_answer",
    "summary",
    "document_generation",
    "confidence_probe",
}


@dataclass(frozen=True)
class RetrievalError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False


@dataclass(frozen=True)
class RetrievalQualityPolicy:
    policy_id: str = "retrieval_quality_v1"
    bm25_weight: float = 0.85
    embedding_presence_weight: float = 0.15
    embedding_presence_score: float = 0.5
    low_confidence_threshold: float = LOW_CONFIDENCE_THRESHOLD
    rerank_candidate_limit: int = DEFAULT_RERANK_CANDIDATE_LIMIT
    ranker_mix: str = "bm25_with_embedding_presence"
    reranked_ranker_mix: str = "bm25_embedding_with_rerank"
    neighbor_policy: str = "not_loaded_in_slice_0017"


DEFAULT_RETRIEVAL_QUALITY_POLICY = RetrievalQualityPolicy()


class MoRerankClient(Protocol):
    def rerank_documents(
        self,
        query: str,
        documents: list[str],
        *,
        alias: str,
        top_n: int,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class HttpMoRerankClient:
    base_url: str = "http://127.0.0.1:8105"
    service_token: str | None = None
    timeout_seconds: float = 5.0

    def rerank_documents(
        self,
        query: str,
        documents: list[str],
        *,
        alias: str,
        top_n: int,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        token = self.service_token or issue_mock_service_token(
            service_id="nex-cx",
            audience="nex-mo",
        ).access_token
        response = httpx.post(
            f"{self.base_url}/api/v1/rerank",
            json={
                "alias": alias,
                "query": query,
                "documents": documents,
                "top_n": top_n,
            },
            headers={
                "Authorization": f"Bearer {token}",
                "X-Request-ID": request_id,
                "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
                "X-Service-ID": "nex-cx",
            },
            timeout=self.timeout_seconds,
        )
        if response.status_code >= 400:
            body = _safe_response_json(response)
            raise RetrievalError(
                status_code=response.status_code,
                error_code=body.get("error_code", "mo.rerank_request_failed"),
                detail=body.get("detail", "MO rerank request failed."),
                retryable=body.get("retryable", False),
            )
        return response.json()


def build_default_mo_rerank_client() -> HttpMoRerankClient:
    return HttpMoRerankClient(
        base_url=os.getenv("NEX_MO_BASE_URL", "http://127.0.0.1:8105"),
        service_token=os.getenv("NEX_CX_TO_MO_SERVICE_TOKEN"),
    )


def register_retrieval_routes(
    app: FastAPI,
    *,
    store: ContentIngestionStore,
    rerank_client: MoRerankClient | None = None,
    reranker_alias: str | None = None,
) -> None:
    client = rerank_client
    if client is None and _env_flag("NEX_CX_RERANKER_ENABLED"):
        client = build_default_mo_rerank_client()
    alias = reranker_alias or os.getenv("NEX_CX_RERANKER_ALIAS", DEFAULT_RERANKER_ALIAS)

    @app.post("/api/v1/retrieval/context", response_model=None)
    def create_retrieval_context(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_cx_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        try:
            package = build_retrieval_context_package(
                payload,
                store=store,
                request_id=request_id_from_headers(request),
                trace_id=payload.get("trace_id") or trace_id_from_headers(request),
                rerank_client=client,
                reranker_alias=alias,
            )
        except RetrievalError as exc:
            return _retrieval_problem_response(request, exc)
        return store.save_retrieval_package(package)

    @app.get("/api/v1/retrieval/context/{retrieval_package_id}", response_model=None)
    def get_retrieval_context(
        retrieval_package_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_cx_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        package = store.get_retrieval_package(retrieval_package_id)
        if package is None:
            return _retrieval_problem_response(
                request,
                RetrievalError(
                    status_code=404,
                    error_code="cx.retrieval_package_not_found",
                    detail=f"Retrieval package was not found: {retrieval_package_id}",
                ),
            )
        return package


def build_retrieval_context_package(
    payload: dict[str, Any],
    *,
    store: ContentIngestionStore,
    request_id: str,
    trace_id: str,
    rerank_client: MoRerankClient | None = None,
    reranker_alias: str = DEFAULT_RERANKER_ALIAS,
) -> dict[str, Any]:
    query_text = _query_text(payload)
    top_k = _top_k(payload)
    include_source_preview = _bool_field(payload, "include_source_preview", True)
    include_neighbors = _bool_field(payload, "include_neighbors", False)
    purpose = _purpose_field(payload)
    quality_policy = build_retrieval_quality_policy(payload)
    actor_claims_ref = payload.get("actor_claims_ref", {"actor_type": "service", "actor_id": "local_mock"})
    document_ids = document_ids_from_scope(payload.get("document_scope"), store)
    candidates = rank_retrieval_candidates(
        query_text=query_text,
        document_ids=document_ids,
        store=store,
        include_source_preview=include_source_preview,
        rerank_client=rerank_client,
        reranker_alias=reranker_alias,
        request_id=request_id,
        trace_id=trace_id,
        quality_policy=quality_policy,
    )
    evidence_items = [
        build_evidence_item(
            candidate,
            rank=index + 1,
            include_neighbors=include_neighbors,
            quality_policy=quality_policy,
        )
        for index, candidate in enumerate(candidates[:top_k])
    ]
    status, no_answer_reason = retrieval_status(evidence_items, quality_policy=quality_policy)
    package_hash = package_hash_for(
        query_text=query_text,
        purpose=purpose,
        document_ids=document_ids,
        evidence_items=evidence_items,
        quality_policy=quality_policy,
    )
    now = _utc_now()
    package_id = str(uuid5(NAMESPACE_URL, f"cx-retrieval:{package_hash}"))
    package = {
        "retrieval_package_schema_version": "cx_retrieval_context_package.v1",
        "retrieval_package_id": package_id,
        "package_hash": package_hash,
        "status": status,
        "trace_id": trace_id,
        "request_id": request_id,
        "query_text": query_text,
        "purpose": purpose,
        "retrieval_profile": build_retrieval_profile(
            store,
            document_ids,
            reranker_profile=build_reranker_profile(
                candidates,
                configured_alias=reranker_alias if rerank_client is not None else None,
            ),
            quality_policy=quality_policy,
        ),
        "permission_snapshot": build_permission_snapshot(
            actor_claims_ref=actor_claims_ref,
            document_scope=payload.get("document_scope"),
            document_ids=document_ids,
        ),
        "evidence_items": evidence_items,
        "source_summary": build_source_summary(document_ids, store),
        "score_summary": build_score_summary(evidence_items, quality_policy=quality_policy),
        "no_answer_reason": no_answer_reason,
        "warnings": build_warnings(document_ids, store),
        "created_at": now,
        "updated_at": now,
    }
    return package


def rank_retrieval_candidates(
    *,
    query_text: str,
    document_ids: list[str],
    store: ContentIngestionStore,
    include_source_preview: bool,
    rerank_client: MoRerankClient | None = None,
    reranker_alias: str = DEFAULT_RERANKER_ALIAS,
    request_id: str = "",
    trace_id: str = "",
    quality_policy: RetrievalQualityPolicy = DEFAULT_RETRIEVAL_QUALITY_POLICY,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for document_id in document_ids:
        chunk_set = store.get_chunk_set(document_id)
        lexical_index = store.get_lexical_index(document_id)
        if chunk_set is None or lexical_index is None:
            continue
        query_terms = query_terms_for_lexical_index(lexical_index, query_text)
        if not query_terms:
            continue
        embedding_index = store.get_embedding_index(document_id)
        counts_by_chunk = matched_counts_by_chunk(lexical_index, query_terms)
        for chunk in chunk_set["chunks"]:
            matched_count = counts_by_chunk.get(chunk["chunk_id"], 0)
            if matched_count == 0:
                continue
            bm25_score = min(1.0, matched_count / max(1, len(query_terms)))
            vector_score = quality_policy.embedding_presence_score if embedding_index else 0.0
            hybrid_score = min(
                1.0,
                bm25_score * quality_policy.bm25_weight
                + vector_score * quality_policy.embedding_presence_weight,
            )
            chunk_text = store.get_chunk_text(chunk["chunk_id"])
            candidates.append(
                {
                    "document_id": document_id,
                    "chunk": chunk,
                    "chunk_text": chunk_text or chunk["text_preview"],
                    "text": chunk_text if include_source_preview and chunk_text else chunk["text_preview"],
                    "matched_terms": sorted(query_terms & terms_for_chunk(lexical_index, chunk["chunk_id"])),
                    "scores": {
                        "vector_score": round(vector_score, 6),
                        "bm25_score": round(bm25_score, 6),
                        "hybrid_score": round(hybrid_score, 6),
                        "rerank_score": None,
                        "final_score": round(hybrid_score, 6),
                    },
                }
            )
    ranked = sorted(
        candidates,
        key=lambda item: (
            item["scores"]["final_score"],
            item["scores"]["bm25_score"],
            -item["chunk"]["ordinal"],
        ),
        reverse=True,
    )
    if rerank_client is None or not ranked:
        return ranked
    return apply_rerank_scores(
        query_text=query_text,
        candidates=ranked,
        rerank_client=rerank_client,
        reranker_alias=reranker_alias,
        request_id=request_id,
        trace_id=trace_id,
        quality_policy=quality_policy,
    )


def apply_rerank_scores(
    *,
    query_text: str,
    candidates: list[dict[str, Any]],
    rerank_client: MoRerankClient,
    reranker_alias: str,
    request_id: str,
    trace_id: str,
    quality_policy: RetrievalQualityPolicy = DEFAULT_RETRIEVAL_QUALITY_POLICY,
) -> list[dict[str, Any]]:
    rerank_candidates = candidates[: quality_policy.rerank_candidate_limit]
    documents = [candidate["chunk_text"] for candidate in rerank_candidates]
    response = rerank_client.rerank_documents(
        query_text,
        documents,
        alias=reranker_alias,
        top_n=len(documents),
        request_id=request_id,
        trace_id=trace_id,
    )
    results = response.get("results")
    if not isinstance(results, list):
        raise RetrievalError(
            status_code=502,
            error_code="cx.rerank_response_invalid",
            detail="MO rerank response must include results.",
            retryable=True,
        )

    seen_indexes: set[int] = set()
    reranked: list[dict[str, Any]] = []
    for result in results:
        index = _rerank_result_index(result, candidate_count=len(rerank_candidates))
        if index in seen_indexes:
            continue
        seen_indexes.add(index)
        score = _rerank_result_score(result)
        candidate = dict(rerank_candidates[index])
        candidate["scores"] = {
            **candidate["scores"],
            "rerank_score": score,
            "final_score": score,
        }
        candidate["reranker"] = {
            "provider_alias": response.get("alias", reranker_alias),
            "model_revision": response.get("model_revision"),
            "deployment_id": response.get("deployment_id"),
            "status": "APPLIED",
        }
        reranked.append(candidate)

    for index, candidate in enumerate(rerank_candidates):
        if index not in seen_indexes:
            reranked.append(candidate)
    reranked.extend(candidates[len(rerank_candidates) :])
    return reranked


def matched_counts_by_chunk(
    lexical_index: dict[str, Any],
    query_terms: set[str],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for posting in lexical_index["postings"]:
        if posting["term"] not in query_terms:
            continue
        for occurrence in posting["occurrences"]:
            chunk_id = occurrence["chunk_id"]
            counts[chunk_id] = counts.get(chunk_id, 0) + occurrence["count"]
    return counts


def terms_for_chunk(
    lexical_index: dict[str, Any],
    chunk_id: str,
) -> set[str]:
    terms = set()
    for posting in lexical_index["postings"]:
        if any(occurrence["chunk_id"] == chunk_id for occurrence in posting["occurrences"]):
            terms.add(posting["term"])
    return terms


def build_evidence_item(
    candidate: dict[str, Any],
    *,
    rank: int,
    include_neighbors: bool,
    quality_policy: RetrievalQualityPolicy = DEFAULT_RETRIEVAL_QUALITY_POLICY,
) -> dict[str, Any]:
    document_id = candidate["document_id"]
    chunk = candidate["chunk"]
    evidence_id = str(uuid5(NAMESPACE_URL, f"cx-evidence:{document_id}:{chunk['chunk_id']}:{rank}"))
    item = {
        "evidence_id": evidence_id,
        "rank": rank,
        "content_object_id": document_id,
        "content_version_id": chunk["text_sha256"],
        "chunk_id": chunk["chunk_id"],
        "chunk_policy_id": "chunk_1000_100",
        "source_anchor": {
            "type": "character_range",
            "start_offset": chunk["start_offset"],
            "end_offset": chunk["end_offset"],
        },
        "citation_label": f"[{rank}]",
        "text": candidate["text"],
        "neighbor_context": [],
        "scores": candidate["scores"],
        "matched_terms": candidate["matched_terms"],
        "permission_result": {
            "visible": True,
            "reason": "local_mock_service_scope",
            "policy_version": "local_mock_v1",
        },
        "quality_flags": [],
    }
    if include_neighbors:
        item["neighbor_context"] = [{"policy": quality_policy.neighbor_policy}]
    return item


def retrieval_status(
    evidence_items: list[dict[str, Any]],
    *,
    quality_policy: RetrievalQualityPolicy = DEFAULT_RETRIEVAL_QUALITY_POLICY,
) -> tuple[str, str | None]:
    if not evidence_items:
        return "NO_ANSWER", "no_terms_matched"
    best_score = evidence_items[0]["scores"]["final_score"]
    if best_score < quality_policy.low_confidence_threshold:
        return "LOW_CONFIDENCE", "best_score_below_threshold"
    return "READY", None


def build_retrieval_profile(
    store: ContentIngestionStore,
    document_ids: list[str],
    *,
    reranker_profile: dict[str, Any] | None = None,
    quality_policy: RetrievalQualityPolicy = DEFAULT_RETRIEVAL_QUALITY_POLICY,
) -> dict[str, Any]:
    first_document_id = document_ids[0] if document_ids else None
    chunk_set = store.get_chunk_set(first_document_id) if first_document_id else None
    lexical_index = store.get_lexical_index(first_document_id) if first_document_id else None
    embedding_index = store.get_embedding_index(first_document_id) if first_document_id else None
    return {
        "search_strategy": "hybrid",
        "embedding_profile": {
            "provider_alias": embedding_index.get("provider_alias") if embedding_index else None,
            "vector_dimension": embedding_index.get("vector_dimension") if embedding_index else 0,
            "index_status": "READY" if embedding_index else "MISSING",
        },
        "bm25_tokenizer": lexical_index.get("tokenizer_used") if lexical_index else None,
        "bm25_tokenizer_profile": (
            lexical_index.get("tokenizer_profile") if lexical_index else None
        ),
        "reranker_profile": reranker_profile or build_reranker_profile([], configured_alias=None),
        "chunk_policy": chunk_set.get("chunk_policy") if chunk_set else "chunk_1000_100",
        "source_context_policy": {
            "include_neighbors_supported": False,
            "neighbor_policy": quality_policy.neighbor_policy,
        },
        "confidence_policy": {
            "low_confidence_threshold": quality_policy.low_confidence_threshold,
        },
        "quality_policy": retrieval_quality_policy_snapshot(quality_policy),
    }


def build_reranker_profile(
    candidates: list[dict[str, Any]],
    *,
    configured_alias: str | None,
) -> dict[str, Any]:
    for candidate in candidates:
        reranker = candidate.get("reranker")
        if isinstance(reranker, dict):
            return {
                "provider_alias": reranker.get("provider_alias", configured_alias),
                "model_revision": reranker.get("model_revision"),
                "deployment_id": reranker.get("deployment_id"),
                "status": "APPLIED",
            }
    return {
        "provider_alias": configured_alias,
        "status": "NOT_APPLIED",
    }


def build_permission_snapshot(
    *,
    actor_claims_ref: Any,
    document_scope: Any,
    document_ids: list[str],
) -> dict[str, Any]:
    actor = actor_claims_ref if isinstance(actor_claims_ref, dict) else {}
    return {
        "actor_type": actor.get("actor_type", "service"),
        "actor_id": actor.get("actor_id", "local_mock"),
        "scope_requested": document_scope or {"type": "all_local_mock"},
        "scope_applied": {
            "type": "document_ids",
            "document_ids": document_ids,
        },
        "classification_filter": ["internal"],
        "visible_document_count": len(document_ids),
        "filtered_document_count": 0,
        "filtered_chunk_count": 0,
        "policy_version": "local_mock_v1",
    }


def build_source_summary(
    document_ids: list[str],
    store: ContentIngestionStore,
) -> dict[str, Any]:
    chunk_count = 0
    for document_id in document_ids:
        chunk_set = store.get_chunk_set(document_id)
        if chunk_set is not None:
            chunk_count += chunk_set["chunk_count"]
    return {
        "source_count": len(document_ids),
        "document_count": len(document_ids),
        "chunk_count": chunk_count,
        "source_types": ["cx.document"] if document_ids else [],
    }


def build_retrieval_quality_policy(
    payload: dict[str, Any] | None = None,
) -> RetrievalQualityPolicy:
    if payload is None or "retrieval_policy" not in payload:
        return DEFAULT_RETRIEVAL_QUALITY_POLICY
    policy_payload = payload.get("retrieval_policy")
    if policy_payload is None:
        return DEFAULT_RETRIEVAL_QUALITY_POLICY
    if not isinstance(policy_payload, dict):
        raise RetrievalError(
            status_code=422,
            error_code="cx.retrieval_policy_invalid",
            detail="retrieval_policy must be an object when provided.",
        )

    bm25_weight = _optional_policy_float(
        policy_payload,
        "bm25_weight",
        DEFAULT_RETRIEVAL_QUALITY_POLICY.bm25_weight,
    )
    embedding_presence_weight = _optional_policy_float(
        policy_payload,
        "embedding_presence_weight",
        DEFAULT_RETRIEVAL_QUALITY_POLICY.embedding_presence_weight,
    )
    if bm25_weight + embedding_presence_weight <= 0.0:
        raise RetrievalError(
            status_code=422,
            error_code="cx.retrieval_policy_invalid",
            detail="retrieval_policy score weights must have a positive sum.",
        )
    if bm25_weight + embedding_presence_weight > 1.0:
        raise RetrievalError(
            status_code=422,
            error_code="cx.retrieval_policy_invalid",
            detail="retrieval_policy score weights must not exceed 1.0 in total.",
        )

    return RetrievalQualityPolicy(
        bm25_weight=bm25_weight,
        embedding_presence_weight=embedding_presence_weight,
        embedding_presence_score=_optional_policy_float(
            policy_payload,
            "embedding_presence_score",
            DEFAULT_RETRIEVAL_QUALITY_POLICY.embedding_presence_score,
        ),
        low_confidence_threshold=_optional_policy_float(
            policy_payload,
            "low_confidence_threshold",
            DEFAULT_RETRIEVAL_QUALITY_POLICY.low_confidence_threshold,
        ),
        rerank_candidate_limit=_optional_policy_int(
            policy_payload,
            "rerank_candidate_limit",
            DEFAULT_RETRIEVAL_QUALITY_POLICY.rerank_candidate_limit,
            minimum=1,
            maximum=100,
        ),
    )


def retrieval_quality_policy_snapshot(
    quality_policy: RetrievalQualityPolicy = DEFAULT_RETRIEVAL_QUALITY_POLICY,
) -> dict[str, Any]:
    return {
        "policy_id": quality_policy.policy_id,
        "bm25_weight": quality_policy.bm25_weight,
        "embedding_presence_weight": quality_policy.embedding_presence_weight,
        "embedding_presence_score": quality_policy.embedding_presence_score,
        "low_confidence_threshold": quality_policy.low_confidence_threshold,
        "rerank_candidate_limit": quality_policy.rerank_candidate_limit,
        "ranker_mix": quality_policy.ranker_mix,
        "reranked_ranker_mix": quality_policy.reranked_ranker_mix,
        "neighbor_policy": quality_policy.neighbor_policy,
    }


def build_score_summary(
    evidence_items: list[dict[str, Any]],
    *,
    quality_policy: RetrievalQualityPolicy = DEFAULT_RETRIEVAL_QUALITY_POLICY,
) -> dict[str, Any]:
    rerank_applied = any(
        item["scores"].get("rerank_score") is not None for item in evidence_items
    )
    if not evidence_items:
        return {
            "best_score": 0.0,
            "score_spread": 0.0,
            "ranker_mix": quality_policy.ranker_mix,
            "rerank_state": "NOT_APPLIED",
            "confidence_bucket": "NO_ANSWER",
            "quality_policy_id": quality_policy.policy_id,
            "low_confidence_threshold": quality_policy.low_confidence_threshold,
        }
    scores = [item["scores"]["final_score"] for item in evidence_items]
    best = max(scores)
    worst = min(scores)
    return {
        "best_score": best,
        "score_spread": round(best - worst, 6),
        "ranker_mix": (
            quality_policy.reranked_ranker_mix
            if rerank_applied
            else quality_policy.ranker_mix
        ),
        "rerank_state": "APPLIED" if rerank_applied else "NOT_APPLIED",
        "confidence_bucket": (
            "READY"
            if best >= quality_policy.low_confidence_threshold
            else "LOW_CONFIDENCE"
        ),
        "quality_policy_id": quality_policy.policy_id,
        "low_confidence_threshold": quality_policy.low_confidence_threshold,
    }


def build_warnings(
    document_ids: list[str],
    store: ContentIngestionStore,
) -> list[str]:
    warnings: list[str] = []
    for document_id in document_ids:
        lexical_index = store.get_lexical_index(document_id)
        if lexical_index and lexical_index.get("fallback_used"):
            warnings.append(f"tokenizer_fallback_used:{document_id}")
        if store.get_embedding_index(document_id) is None:
            warnings.append(f"embedding_index_missing:{document_id}")
    return warnings


def document_ids_from_scope(
    document_scope: Any,
    store: ContentIngestionStore,
) -> list[str]:
    if document_scope is None:
        return sorted(store.chunk_sets)
    if not isinstance(document_scope, dict):
        raise RetrievalError(
            status_code=422,
            error_code="cx.document_scope_invalid",
            detail="document_scope must be an object when provided.",
        )
    document_ids = document_scope.get("document_ids")
    if document_ids is None:
        return sorted(store.chunk_sets)
    if not isinstance(document_ids, list) or not all(
        isinstance(document_id, str) and document_id for document_id in document_ids
    ):
        raise RetrievalError(
            status_code=422,
            error_code="cx.document_scope_invalid",
            detail="document_scope.document_ids must be a list of strings.",
        )
    return [document_id for document_id in document_ids if document_id in store.chunk_sets]


def package_hash_for(
    *,
    query_text: str,
    purpose: str,
    document_ids: list[str],
    evidence_items: list[dict[str, Any]],
    quality_policy: RetrievalQualityPolicy = DEFAULT_RETRIEVAL_QUALITY_POLICY,
) -> str:
    return sha256_json(
        {
            "query_text": query_text,
            "purpose": purpose,
            "document_ids": document_ids,
            "retrieval_policy": retrieval_quality_policy_snapshot(quality_policy),
            "evidence": [
                {
                    "evidence_id": item["evidence_id"],
                    "chunk_id": item["chunk_id"],
                    "final_score": item["scores"]["final_score"],
                    "matched_terms": item["matched_terms"],
                }
                for item in evidence_items
            ],
        }
    )


def sha256_json(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _query_text(payload: dict[str, Any]) -> str:
    query_text = payload.get("query_text") or payload.get("user_prompt")
    if not isinstance(query_text, str) or not query_text.strip():
        raise RetrievalError(
            status_code=422,
            error_code="cx.query_text_required",
            detail="query_text or user_prompt must be a non-empty string.",
        )
    return query_text.strip()


def _top_k(payload: dict[str, Any]) -> int:
    value = payload.get("top_k", DEFAULT_TOP_K)
    if isinstance(value, bool) or not isinstance(value, int):
        raise RetrievalError(
            status_code=422,
            error_code="cx.top_k_invalid",
            detail="top_k must be an integer.",
        )
    if value < 1 or value > MAX_TOP_K:
        raise RetrievalError(
            status_code=422,
            error_code="cx.top_k_invalid",
            detail=f"top_k must be between 1 and {MAX_TOP_K}.",
        )
    return value


def _bool_field(payload: dict[str, Any], key: str, default: bool) -> bool:
    value = payload.get(key, default)
    if not isinstance(value, bool):
        raise RetrievalError(
            status_code=422,
            error_code=f"cx.{key}_invalid",
            detail=f"{key} must be a boolean.",
        )
    return value


def _purpose_field(payload: dict[str, Any]) -> str:
    value = payload.get("purpose", "search")
    if not isinstance(value, str) or not value:
        raise RetrievalError(
            status_code=422,
            error_code="cx.purpose_invalid",
            detail="purpose must be a non-empty string.",
        )
    if value not in ALLOWED_PURPOSES:
        raise RetrievalError(
            status_code=422,
            error_code="cx.purpose_invalid",
            detail=f"purpose must be one of: {', '.join(sorted(ALLOWED_PURPOSES))}.",
        )
    return value


def _optional_policy_float(
    policy_payload: dict[str, Any],
    key: str,
    default: float,
) -> float:
    value = policy_payload.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise RetrievalError(
            status_code=422,
            error_code="cx.retrieval_policy_invalid",
            detail=f"retrieval_policy.{key} must be numeric.",
        )
    numeric_value = float(value)
    if numeric_value < 0.0 or numeric_value > 1.0:
        raise RetrievalError(
            status_code=422,
            error_code="cx.retrieval_policy_invalid",
            detail=f"retrieval_policy.{key} must be between 0.0 and 1.0.",
        )
    return round(numeric_value, 6)


def _optional_policy_int(
    policy_payload: dict[str, Any],
    key: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    value = policy_payload.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise RetrievalError(
            status_code=422,
            error_code="cx.retrieval_policy_invalid",
            detail=f"retrieval_policy.{key} must be an integer.",
        )
    if value < minimum or value > maximum:
        raise RetrievalError(
            status_code=422,
            error_code="cx.retrieval_policy_invalid",
            detail=f"retrieval_policy.{key} must be between {minimum} and {maximum}.",
        )
    return value


def _authorize_cx_request(
    request: Request,
    authorization: str | None,
) -> JSONResponse | None:
    result = validate_authorization_header(
        authorization,
        expected_audience="nex-cx",
        required_scopes=[DEFAULT_SERVICE_SCOPE],
    )
    if result.ok:
        return None

    return problem_response(
        request,
        status_code=401,
        error_code=result.error_code or "SERVICE_CLAIM_INVALID",
        title="Authentication failed",
        detail=result.detail or "CX requires a valid service claim.",
        type_uri="https://nex-platform.local/problems/authentication-failed",
    )


def _retrieval_problem_response(
    request: Request,
    exc: RetrievalError,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Retrieval context request failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/retrieval-context-failed",
    )


def _rerank_result_index(result: Any, *, candidate_count: int) -> int:
    if not isinstance(result, dict):
        raise RetrievalError(
            status_code=502,
            error_code="cx.rerank_response_invalid",
            detail="MO rerank result must be an object.",
            retryable=True,
        )
    value = result.get("index")
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
        or value >= candidate_count
    ):
        raise RetrievalError(
            status_code=502,
            error_code="cx.rerank_response_invalid",
            detail="MO rerank result index is out of range.",
            retryable=True,
        )
    return value


def _rerank_result_score(result: Any) -> float:
    value = result.get("score") if isinstance(result, dict) else None
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise RetrievalError(
            status_code=502,
            error_code="cx.rerank_response_invalid",
            detail="MO rerank result score must be numeric.",
            retryable=True,
        )
    return round(float(value), 6)


def _safe_response_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _env_flag(name: str) -> bool:
    value = os.getenv(name, "")
    return value.lower() in {"1", "true", "yes", "on"}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
