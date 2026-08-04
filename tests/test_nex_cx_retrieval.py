from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import nex_cx.lexical_index as lexical_index
import nex_cx.retrieval as retrieval_module
from nex_cx.chunking import build_and_store_chunk_set, register_chunking_routes
from nex_cx.embedding_index import build_and_store_embedding_index, register_embedding_index_routes
from nex_cx.ingestion import (
    ContentIngestionStore,
    CxStorageConfig,
    build_upload_registration,
    register_ingestion_routes,
    run_text_extraction_job,
)
from nex_cx.lexical_index import (
    TokenizerUnavailable,
    build_and_store_lexical_index,
    register_lexical_index_routes,
)
from nex_cx.retrieval import (
    DEFAULT_RERANKER_ALIAS,
    DEFAULT_RETRIEVAL_QUALITY_POLICY,
    WEIGHTED_RRF_RANKER_MIX,
    RetrievalError,
    RetrievalQualityPolicy,
    active_retrieval_quality_policy,
    apply_rerank_scores,
    build_permission_snapshot,
    build_query_embedding_snapshot,
    build_reranker_profile,
    build_retrieval_context_package,
    build_retrieval_quality_policy,
    build_score_summary,
    build_source_summary,
    build_warnings,
    candidate_ranks,
    cosine_similarity,
    document_ids_from_scope,
    matched_counts_by_chunk,
    package_hash_for,
    query_embedding_from_payload,
    rank_retrieval_candidates,
    register_retrieval_routes,
    retrieval_quality_policy_snapshot,
    retrieval_policy_payload_from_registry_record,
    retrieval_quality_policy_from_registry_record,
    retrieval_status,
    terms_for_chunk,
    weighted_rrf_score,
)
from nex_runtime.retrieval_policies import (
    DEFAULT_RETRIEVAL_POLICIES,
    WEIGHTED_RRF_POLICY_ID,
    finalize_retrieval_policy,
)
from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


class FakeMoEmbeddingClient:
    def create_embeddings(
        self,
        inputs: list[str],
        *,
        alias: str,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        return {
            "object": "list",
            "alias": alias,
            "model_revision": "mock-embedding-v1",
            "deployment_id": "mock-embedding-local",
            "data": [
                {"object": "embedding", "index": index, "embedding": [0.1, 0.2, 0.3]}
                for index, _ in enumerate(inputs)
            ],
            "usage": {
                "input_tokens": len(inputs),
                "output_tokens": 0,
                "total_tokens": len(inputs),
            },
        }


class FakeMoRerankClient:
    def __init__(self, results: list[dict[str, Any]] | None = None) -> None:
        self.results = results or [{"index": 0, "score": 0.93}]
        self.calls: list[dict[str, Any]] = []

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
        self.calls.append(
            {
                "query": query,
                "documents": documents,
                "alias": alias,
                "top_n": top_n,
                "request_id": request_id,
                "trace_id": trace_id,
            }
        )
        return {
            "alias": alias,
            "model_revision": "mock-reranker-v1",
            "deployment_id": "mock-reranker-local",
            "results": self.results,
        }


def auth_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-ae-api", audience="nex-cx")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def storage_config(tmp_path: Path) -> CxStorageConfig:
    return CxStorageConfig(
        data_root=tmp_path,
        source_root=tmp_path / "cx" / "source-files",
        extracted_markdown_root=tmp_path / "cx" / "extracted-markdown",
        extraction_temp_root=tmp_path / "cx" / "extraction-temp",
        chunk_policy="chunk_1000_100",
        chunk_size=30,
        chunk_overlap=5,
        bm25_tokenizer="mecab_ko",
        bm25_tokenizer_fallback="korean_mixed_v1",
    )


def force_mecab_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_mecab(text: str) -> list[str]:
        raise TokenizerUnavailable("missing")

    monkeypatch.setattr(lexical_index, "_mecab_ko_tokens", fail_mecab)


def build_store_with_indexes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    text: str = "NeX trace evidence package. Retrieval trace quality.",
    with_embedding: bool = True,
) -> tuple[ContentIngestionStore, str]:
    force_mecab_fallback(monkeypatch)
    store = ContentIngestionStore()
    config = storage_config(tmp_path)
    document = build_upload_registration(
        {
            "filename": "source.txt",
            "content_type": "text/plain",
            "content_text": text,
        },
        storage_config=config,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    store.save_upload_registration(document, source_text=text)
    extraction = run_text_extraction_job(
        document["extraction"]["job_id"],
        store=store,
        storage_config=config,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    chunk_set = build_and_store_chunk_set(
        extraction["document_id"],
        store=store,
        storage_config=config,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    build_and_store_lexical_index(
        chunk_set["document_id"],
        store=store,
        storage_config=config,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    if with_embedding:
        build_and_store_embedding_index(
            chunk_set["document_id"],
            store=store,
            mo_client=FakeMoEmbeddingClient(),
            embedding_alias="mock-embedding-default",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    return store, chunk_set["document_id"]


def build_test_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, ContentIngestionStore]:
    force_mecab_fallback(monkeypatch)
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    store = ContentIngestionStore()
    config = storage_config(tmp_path)
    register_ingestion_routes(app, store=store, storage_config=config)
    register_chunking_routes(app, store=store, storage_config=config)
    register_lexical_index_routes(app, store=store, storage_config=config)
    register_embedding_index_routes(
        app,
        store=store,
        mo_client=FakeMoEmbeddingClient(),
        embedding_alias="mock-embedding-default",
    )
    register_retrieval_routes(app, store=store)
    return TestClient(app), store


def build_weighted_rrf_store() -> tuple[ContentIngestionStore, str]:
    store = ContentIngestionStore()
    document_id = "doc-weighted"
    chunks = [
        {
            "chunk_id": "chunk-vector",
            "ordinal": 0,
            "start_offset": 0,
            "end_offset": 16,
            "text_sha256": "sha-vector",
            "text_preview": "alpha vector",
        },
        {
            "chunk_id": "chunk-bm25",
            "ordinal": 1,
            "start_offset": 17,
            "end_offset": 32,
            "text_sha256": "sha-bm25",
            "text_preview": "alpha beta bm25",
        },
    ]
    store.save_chunk_set(
        {
            "document_id": document_id,
            "chunk_policy": "chunk_1000_100",
            "chunk_count": len(chunks),
            "chunks": chunks,
        },
        chunk_texts={
            "chunk-vector": "alpha vector",
            "chunk-bm25": "alpha beta bm25",
        },
    )
    store.save_lexical_index(
        {
            "document_id": document_id,
            "tokenizer_used": "korean_mixed_v1",
            "tokenizer_fallback": "korean_mixed_v1",
            "fallback_used": False,
            "tokenizer_profile": {
                "bm25_tokenizer": "korean_mixed_v1",
                "query_tokenizer_policy": "match_index_tokenizer_with_fallback",
            },
            "postings": [
                {
                    "term": "alpha",
                    "document_frequency": 2,
                    "occurrences": [
                        {"chunk_id": "chunk-vector", "ordinal": 0, "count": 1},
                        {"chunk_id": "chunk-bm25", "ordinal": 1, "count": 1},
                    ],
                },
                {
                    "term": "beta",
                    "document_frequency": 1,
                    "occurrences": [
                        {"chunk_id": "chunk-bm25", "ordinal": 1, "count": 1}
                    ],
                },
            ],
        }
    )
    store.save_embedding_index(
        {
            "document_id": document_id,
            "provider_alias": "mock-embedding-default",
            "vector_dimension": 2,
            "chunk_embeddings": [
                {"chunk_id": "chunk-vector"},
                {"chunk_id": "chunk-bm25"},
            ],
        },
        embedding_vectors={
            "chunk-vector": [1.0, 0.0],
            "chunk-bm25": [0.0, 1.0],
        },
    )
    return store, document_id


def weighted_rrf_policy(**overrides: object) -> RetrievalQualityPolicy:
    values = {
        "policy_id": WEIGHTED_RRF_RANKER_MIX,
        "ranker_mix": WEIGHTED_RRF_RANKER_MIX,
        "bm25_weight": 0.3,
        "vector_weight": 0.7,
        "rrf_k": 60,
        "vector_candidate_limit": 80,
        "bm25_candidate_limit": 80,
    }
    values.update(overrides)
    return RetrievalQualityPolicy(**values)


def test_document_ids_from_scope_defaults_to_all_chunk_sets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, document_id = build_store_with_indexes(tmp_path, monkeypatch)

    assert document_ids_from_scope(None, store) == [document_id]


def test_document_ids_from_scope_filters_missing_documents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, document_id = build_store_with_indexes(tmp_path, monkeypatch)

    assert document_ids_from_scope({"document_ids": [document_id, "missing"]}, store) == [
        document_id
    ]


@pytest.mark.parametrize("scope", ["bad", {"document_ids": "bad"}, {"document_ids": [None]}])
def test_document_ids_from_scope_rejects_invalid_scope(scope: object) -> None:
    with pytest.raises(RetrievalError):
        document_ids_from_scope(scope, ContentIngestionStore())


def test_matched_counts_and_terms_by_chunk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, document_id = build_store_with_indexes(tmp_path, monkeypatch)
    lexical = store.get_lexical_index(document_id)
    first_chunk_id = store.get_chunk_set(document_id)["chunks"][0]["chunk_id"]

    counts = matched_counts_by_chunk(lexical, {"trace"})

    assert counts[first_chunk_id] >= 1
    assert "trace" in terms_for_chunk(lexical, first_chunk_id)


def test_cosine_similarity_handles_matches_and_invalid_vectors() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert cosine_similarity([1.0], [1.0, 0.0]) is None
    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) is None


def test_candidate_ranks_honors_score_order_and_limit() -> None:
    candidates = [
        {"chunk": {"chunk_id": "a", "ordinal": 0}, "scores": {"bm25_score": 0.2}},
        {"chunk": {"chunk_id": "b", "ordinal": 1}, "scores": {"bm25_score": 0.9}},
        {"chunk": {"chunk_id": "c", "ordinal": 2}, "scores": {"bm25_score": 0.0}},
    ]

    assert candidate_ranks(candidates, score_key="bm25_score", limit=1) == {"b": 1}


def test_weighted_rrf_score_normalizes_best_possible_rank() -> None:
    raw_score, normalized_score = weighted_rrf_score(
        bm25_rank=1,
        vector_rank=1,
        quality_policy=weighted_rrf_policy(),
    )

    assert raw_score > 0.0
    assert normalized_score == 1.0
    assert weighted_rrf_score(
        bm25_rank=None,
        vector_rank=None,
        quality_policy=weighted_rrf_policy(bm25_weight=0.0, vector_weight=0.0),
    ) == (0.0, 0.0)


def test_rank_retrieval_candidates_scores_matches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, document_id = build_store_with_indexes(tmp_path, monkeypatch)

    candidates = rank_retrieval_candidates(
        query_text="trace quality",
        document_ids=[document_id],
        store=store,
        include_source_preview=True,
    )

    assert candidates
    assert candidates[0]["scores"]["final_score"] >= candidates[-1]["scores"]["final_score"]
    assert "trace" in candidates[0]["matched_terms"]
    assert "trace" in candidates[0]["text"].lower()


def test_rank_retrieval_candidates_applies_weighted_rrf_vector_and_bm25() -> None:
    store, document_id = build_weighted_rrf_store()

    candidates = rank_retrieval_candidates(
        query_text="alpha beta",
        query_embedding=[1.0, 0.0],
        document_ids=[document_id],
        store=store,
        include_source_preview=True,
        quality_policy=weighted_rrf_policy(),
    )

    assert [candidate["chunk"]["chunk_id"] for candidate in candidates] == [
        "chunk-vector",
        "chunk-bm25",
    ]
    assert candidates[0]["scores"]["vector_rank"] == 1
    assert candidates[0]["scores"]["bm25_rank"] == 2
    assert candidates[0]["scores"]["final_score"] > candidates[1]["scores"]["final_score"]
    assert candidates[0]["scores"]["rrf_score"] > 0.0


def test_rank_retrieval_candidates_weighted_rrf_degrades_to_bm25_without_query_vector() -> None:
    store, document_id = build_weighted_rrf_store()

    candidates = rank_retrieval_candidates(
        query_text="alpha beta",
        document_ids=[document_id],
        store=store,
        include_source_preview=True,
        quality_policy=weighted_rrf_policy(),
    )

    assert [candidate["chunk"]["chunk_id"] for candidate in candidates] == [
        "chunk-bm25",
        "chunk-vector",
    ]
    assert candidates[0]["scores"]["bm25_rank"] == 1
    assert candidates[0]["scores"]["vector_rank"] is None


def test_rank_retrieval_candidates_uses_index_tokenizer_for_query(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, document_id = build_store_with_indexes(
        tmp_path,
        monkeypatch,
        text="토큰 정합성 문서",
        with_embedding=False,
    )
    chunk = store.get_chunk_set(document_id)["chunks"][0]
    store.save_lexical_index(
        {
            "document_id": document_id,
            "tokenizer_used": "mecab_ko",
            "tokenizer_fallback": "korean_mixed_v1",
            "fallback_used": False,
            "postings": [
                {
                    "term": "mecab-query",
                    "document_frequency": 1,
                    "occurrences": [
                        {
                            "chunk_id": chunk["chunk_id"],
                            "ordinal": chunk["ordinal"],
                            "count": 1,
                        }
                    ],
                }
            ],
        }
    )
    monkeypatch.setattr(
        lexical_index,
        "_mecab_ko_tokens",
        lambda text: ["mecab-query"],
    )

    candidates = rank_retrieval_candidates(
        query_text="일반 질의",
        document_ids=[document_id],
        store=store,
        include_source_preview=True,
    )

    assert candidates[0]["matched_terms"] == ["mecab-query"]


def test_rank_retrieval_candidates_falls_back_to_index_tokenizer_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, document_id = build_store_with_indexes(
        tmp_path,
        monkeypatch,
        with_embedding=False,
    )
    lexical = store.get_lexical_index(document_id)
    assert lexical is not None
    store.save_lexical_index(
        {
            **lexical,
            "tokenizer_used": "mecab_ko",
            "tokenizer_fallback": "korean_mixed_v1",
            "fallback_used": False,
        }
    )

    def fail_mecab(text: str) -> list[str]:
        raise TokenizerUnavailable("missing")

    monkeypatch.setattr(lexical_index, "_mecab_ko_tokens", fail_mecab)

    candidates = rank_retrieval_candidates(
        query_text="trace quality",
        document_ids=[document_id],
        store=store,
        include_source_preview=True,
    )

    assert candidates
    assert "trace" in candidates[0]["matched_terms"]


def test_rank_retrieval_candidates_applies_reranker_scores(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, document_id = build_store_with_indexes(tmp_path, monkeypatch)
    rerank_client = FakeMoRerankClient()

    candidates = rank_retrieval_candidates(
        query_text="trace quality",
        document_ids=[document_id],
        store=store,
        include_source_preview=True,
        rerank_client=rerank_client,
        reranker_alias=DEFAULT_RERANKER_ALIAS,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert candidates[0]["scores"]["rerank_score"] == 0.93
    assert candidates[0]["scores"]["final_score"] == 0.93
    assert candidates[0]["reranker"]["status"] == "APPLIED"
    assert rerank_client.calls[0]["alias"] == DEFAULT_RERANKER_ALIAS
    assert rerank_client.calls[0]["top_n"] == len(candidates)


def test_rank_retrieval_candidates_honors_quality_policy_weights(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, document_id = build_store_with_indexes(tmp_path, monkeypatch)

    candidates = rank_retrieval_candidates(
        query_text="trace quality",
        document_ids=[document_id],
        store=store,
        include_source_preview=True,
        quality_policy=RetrievalQualityPolicy(
            bm25_weight=0.5,
            embedding_presence_weight=0.5,
            embedding_presence_score=1.0,
        ),
    )

    assert candidates[0]["scores"]["final_score"] == 1.0
    assert candidates[0]["scores"]["vector_score"] == 1.0


def test_rank_retrieval_candidates_can_use_preview_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, document_id = build_store_with_indexes(tmp_path, monkeypatch)

    candidate = rank_retrieval_candidates(
        query_text="trace",
        document_ids=[document_id],
        store=store,
        include_source_preview=False,
    )[0]

    assert candidate["text"] == candidate["chunk"]["text_preview"]


def test_rank_retrieval_candidates_returns_empty_for_no_terms(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, document_id = build_store_with_indexes(tmp_path, monkeypatch)

    assert rank_retrieval_candidates(
        query_text="!!!",
        document_ids=[document_id],
        store=store,
        include_source_preview=True,
    ) == []


def test_rank_retrieval_candidates_skips_unindexed_documents() -> None:
    assert (
        rank_retrieval_candidates(
            query_text="trace",
            document_ids=["missing"],
            store=ContentIngestionStore(),
            include_source_preview=True,
        )
        == []
    )


@pytest.mark.parametrize(
    "results",
    [
        ["bad"],
        [{"index": True, "score": 0.5}],
        [{"index": 0, "score": False}],
    ],
)
def test_apply_rerank_scores_rejects_invalid_results(results: list[Any]) -> None:
    candidate = {
        "chunk_text": "candidate text",
        "scores": {
            "bm25_score": 1.0,
            "hybrid_score": 1.0,
            "rerank_score": None,
            "final_score": 1.0,
        },
    }

    with pytest.raises(RetrievalError) as exc:
        apply_rerank_scores(
            query_text="candidate",
            candidates=[candidate],
            rerank_client=FakeMoRerankClient(results),
            reranker_alias=DEFAULT_RERANKER_ALIAS,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert exc.value.error_code == "cx.rerank_response_invalid"
    assert exc.value.retryable is True


def test_apply_rerank_scores_limits_candidate_window() -> None:
    candidates = [
        {
            "chunk_text": f"candidate {index}",
            "scores": {
                "bm25_score": 1.0,
                "hybrid_score": 1.0,
                "rerank_score": None,
                "final_score": 1.0,
            },
        }
        for index in range(4)
    ]
    rerank_client = FakeMoRerankClient(results=[{"index": 1, "score": 0.99}])

    reranked = apply_rerank_scores(
        query_text="candidate",
        candidates=candidates,
        rerank_client=rerank_client,
        reranker_alias=DEFAULT_RERANKER_ALIAS,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        quality_policy=RetrievalQualityPolicy(rerank_candidate_limit=2),
    )

    assert rerank_client.calls[0]["documents"] == ["candidate 0", "candidate 1"]
    assert rerank_client.calls[0]["top_n"] == 2
    assert reranked[0]["chunk_text"] == "candidate 1"
    assert reranked[0]["scores"]["final_score"] == 0.99
    assert reranked[-1]["chunk_text"] == "candidate 3"


def test_build_retrieval_quality_policy_defaults_and_snapshot() -> None:
    active_policy = build_retrieval_quality_policy({})
    null_override_policy = build_retrieval_quality_policy({"retrieval_policy": None})

    assert active_policy.policy_id == "retrieval_quality_v1"
    assert active_policy.policy_source == "ag_registry_active"
    assert active_policy.policy_version == "0001"
    assert len(active_policy.policy_hash or "") == 64
    assert null_override_policy == active_policy

    policy = build_retrieval_quality_policy(
        {
            "retrieval_policy": {
                "bm25_weight": 0.7,
                "embedding_presence_weight": 0.2,
                "embedding_presence_score": 0.8,
                "low_confidence_threshold": 0.4,
                "rerank_candidate_limit": 7,
            }
        }
    )
    snapshot = retrieval_quality_policy_snapshot(policy)

    assert snapshot["policy_id"] == "retrieval_quality_v1"
    assert snapshot["policy_source"] == "request_override"
    assert snapshot["bm25_weight"] == 0.7
    assert snapshot["embedding_presence_weight"] == 0.2
    assert snapshot["embedding_presence_score"] == 0.8
    assert snapshot["low_confidence_threshold"] == 0.4
    assert snapshot["rerank_candidate_limit"] == 7


def test_active_retrieval_quality_policy_maps_registry_defaults() -> None:
    policy = active_retrieval_quality_policy()
    snapshot = retrieval_quality_policy_snapshot(policy)

    assert policy == build_retrieval_quality_policy()
    assert snapshot["policy_id"] == "retrieval_quality_v1"
    assert snapshot["policy_source"] == "ag_registry_active"
    assert snapshot["bm25_weight"] == 0.85
    assert snapshot["embedding_presence_weight"] == 0.15
    assert snapshot["vector_weight"] == 0.0
    assert snapshot["vector_candidate_limit"] == 0
    assert snapshot["bm25_candidate_limit"] == 50


def test_registry_candidate_policy_maps_to_weighted_rrf_policy() -> None:
    registry_record = finalize_retrieval_policy(DEFAULT_RETRIEVAL_POLICIES[1])
    payload = retrieval_policy_payload_from_registry_record(
        registry_record,
        policy_source="ag_registry_candidate",
    )
    policy = retrieval_quality_policy_from_registry_record(
        registry_record,
        policy_source="ag_registry_candidate",
    )

    assert payload["policy_id"] == WEIGHTED_RRF_POLICY_ID
    assert policy.policy_id == WEIGHTED_RRF_POLICY_ID
    assert policy.policy_source == "ag_registry_candidate"
    assert policy.ranker_mix == WEIGHTED_RRF_RANKER_MIX
    assert policy.vector_weight == 0.7
    assert policy.bm25_weight == 0.3
    assert policy.vector_candidate_limit == 80
    assert len(policy.policy_hash or "") == 64


def test_active_retrieval_quality_policy_reports_registry_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_active_policy() -> dict[str, object]:
        raise retrieval_module.RegistryRetrievalPolicyError(
            status_code=500,
            error_code="retrieval_policy.active_policy_invalid",
            detail="broken registry",
        )

    monkeypatch.setattr(
        retrieval_module,
        "active_retrieval_policy_record",
        fail_active_policy,
    )

    with pytest.raises(RetrievalError) as exc:
        active_retrieval_quality_policy()

    assert exc.value.error_code == "cx.retrieval_policy_registry_invalid"
    assert exc.value.detail == "broken registry"


def test_registry_policy_mapping_rejects_bad_registry_records() -> None:
    with pytest.raises(RetrievalError) as missing:
        retrieval_policy_payload_from_registry_record(
            {"policy_id": "bad"},
            policy_source="ag_registry",
        )
    unsupported = finalize_retrieval_policy(DEFAULT_RETRIEVAL_POLICIES[0])
    unsupported["ranker"] = {**unsupported["ranker"], "method": "unsupported"}

    with pytest.raises(RetrievalError) as bad_method:
        retrieval_policy_payload_from_registry_record(
            unsupported,
            policy_source="ag_registry",
        )

    assert missing.value.error_code == "cx.retrieval_policy_registry_invalid"
    assert bad_method.value.detail == (
        "Unsupported registry retrieval ranker method: unsupported."
    )


def test_registry_policy_payload_for_request_reports_lookup_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_lookup(policy_id: str) -> dict[str, object]:
        raise retrieval_module.RegistryRetrievalPolicyError(
            status_code=404,
            error_code="retrieval_policy.not_found",
            detail=policy_id,
        )

    monkeypatch.setattr(retrieval_module, "retrieval_policy_by_id", fail_lookup)

    with pytest.raises(RetrievalError) as exc:
        retrieval_module.registry_policy_payload_for_request(
            {"policy_id": WEIGHTED_RRF_POLICY_ID}
        )

    assert exc.value.status_code == 404
    assert exc.value.error_code == "cx.retrieval_policy_registry_invalid"


def test_build_retrieval_quality_policy_enables_weighted_rrf_defaults() -> None:
    policy = build_retrieval_quality_policy(
        {"retrieval_policy": {"policy_id": WEIGHTED_RRF_RANKER_MIX}}
    )
    snapshot = retrieval_quality_policy_snapshot(policy)

    assert policy.policy_id == WEIGHTED_RRF_RANKER_MIX
    assert policy.policy_source == "request_override"
    assert policy.ranker_mix == WEIGHTED_RRF_RANKER_MIX
    assert policy.reranked_ranker_mix == "weighted_rrf_vector_bm25_with_rerank"
    assert policy.vector_weight == 0.7
    assert policy.bm25_weight == 0.3
    assert policy.rrf_k == 60
    assert snapshot["vector_candidate_limit"] == 80
    assert snapshot["bm25_candidate_limit"] == 80


@pytest.mark.parametrize(
    "retrieval_policy",
    [
        "bad",
        {"policy_id": ""},
        {"policy_version": ""},
        {"ranker_mix": "unsupported"},
        {"bm25_weight": True},
        {"embedding_presence_weight": -0.1},
        {"vector_weight": True},
        {"low_confidence_threshold": 1.1},
        {"bm25_weight": 0.8, "embedding_presence_weight": 0.3},
        {"bm25_weight": 0.0, "embedding_presence_weight": 0.0},
        {"ranker_mix": WEIGHTED_RRF_RANKER_MIX, "bm25_weight": 0.8, "vector_weight": 0.3},
        {"ranker_mix": WEIGHTED_RRF_RANKER_MIX, "bm25_weight": 0.0, "vector_weight": 0.0},
        {"rrf_k": 0},
        {"ranker_mix": WEIGHTED_RRF_RANKER_MIX, "vector_candidate_limit": 0},
        {"bm25_candidate_limit": 501},
        {"rerank_candidate_limit": 0},
        {"rerank_candidate_limit": 101},
        {"rerank_candidate_limit": 1.5},
    ],
)
def test_build_retrieval_quality_policy_rejects_invalid_policy(
    retrieval_policy: object,
) -> None:
    with pytest.raises(RetrievalError) as exc:
        build_retrieval_quality_policy({"retrieval_policy": retrieval_policy})

    assert exc.value.error_code == "cx.retrieval_policy_invalid"


def test_query_embedding_validation_and_snapshot() -> None:
    query_embedding = query_embedding_from_payload({"query_embedding": [1, 0.5]})
    snapshot = build_query_embedding_snapshot(query_embedding)

    assert query_embedding == [1.0, 0.5]
    assert snapshot["provided"] is True
    assert snapshot["vector_dimension"] == 2
    assert len(snapshot["embedding_sha256"]) == 64
    assert build_query_embedding_snapshot(None) == {
        "provided": False,
        "embedding_sha256": None,
        "vector_dimension": 0,
    }


@pytest.mark.parametrize("query_embedding", [[], "bad", [True], ["bad"]])
def test_query_embedding_from_payload_rejects_invalid_values(
    query_embedding: object,
) -> None:
    with pytest.raises(RetrievalError) as exc:
        query_embedding_from_payload({"query_embedding": query_embedding})

    assert exc.value.error_code == "cx.query_embedding_invalid"


def test_retrieval_status_handles_no_answer_low_confidence_and_ready() -> None:
    assert retrieval_status([]) == ("NO_ANSWER", "no_terms_matched")
    low_item = {"scores": {"final_score": 0.1}}
    ready_item = {"scores": {"final_score": 0.9}}

    assert retrieval_status([low_item]) == ("LOW_CONFIDENCE", "best_score_below_threshold")
    assert retrieval_status([ready_item]) == ("READY", None)


def test_retrieval_status_uses_quality_policy_threshold() -> None:
    item = {"scores": {"final_score": 0.9}}

    assert retrieval_status(
        [item],
        quality_policy=RetrievalQualityPolicy(low_confidence_threshold=0.95),
    ) == ("LOW_CONFIDENCE", "best_score_below_threshold")


def test_build_score_summary_handles_empty_and_ready_items() -> None:
    empty = build_score_summary([])
    ready = build_score_summary(
        [
            {"scores": {"final_score": 0.9}},
            {"scores": {"final_score": 0.5}},
        ]
    )

    assert empty["confidence_bucket"] == "NO_ANSWER"
    assert empty["quality_policy_id"] == DEFAULT_RETRIEVAL_QUALITY_POLICY.policy_id
    assert ready["best_score"] == 0.9
    assert ready["score_spread"] == 0.4
    assert ready["confidence_bucket"] == "READY"


def test_build_score_summary_reports_rerank_state() -> None:
    summary = build_score_summary(
        [
            {"scores": {"final_score": 0.93, "rerank_score": 0.93}},
            {"scores": {"final_score": 0.71, "rerank_score": None}},
        ]
    )

    assert summary["ranker_mix"] == "bm25_embedding_with_rerank"
    assert summary["rerank_state"] == "APPLIED"


def test_build_score_summary_uses_quality_policy_metadata() -> None:
    summary = build_score_summary(
        [{"scores": {"final_score": 0.3, "rerank_score": None}}],
        quality_policy=RetrievalQualityPolicy(low_confidence_threshold=0.4),
    )

    assert summary["confidence_bucket"] == "LOW_CONFIDENCE"
    assert summary["ranker_mix"] == "bm25_with_embedding_presence"
    assert summary["low_confidence_threshold"] == 0.4


def test_build_reranker_profile_reports_applied_metadata() -> None:
    profile = build_reranker_profile(
        [
            {
                "reranker": {
                    "provider_alias": DEFAULT_RERANKER_ALIAS,
                    "model_revision": "mock-reranker-v1",
                    "deployment_id": "mock-reranker-local",
                    "status": "APPLIED",
                }
            }
        ],
        configured_alias=DEFAULT_RERANKER_ALIAS,
    )

    assert profile["status"] == "APPLIED"
    assert profile["provider_alias"] == DEFAULT_RERANKER_ALIAS


def test_build_permission_snapshot_defaults_non_dict_actor() -> None:
    snapshot = build_permission_snapshot(
        actor_claims_ref="bad",
        document_scope=None,
        document_ids=["doc-1"],
    )

    assert snapshot["actor_type"] == "service"
    assert snapshot["visible_document_count"] == 1


def test_build_source_summary_counts_chunks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, document_id = build_store_with_indexes(tmp_path, monkeypatch)
    summary = build_source_summary([document_id, "missing"], store)

    assert summary["document_count"] == 2
    assert summary["chunk_count"] == store.get_chunk_set(document_id)["chunk_count"]


def test_build_warnings_reports_tokenizer_fallback_and_missing_embedding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, document_id = build_store_with_indexes(tmp_path, monkeypatch, with_embedding=False)

    warnings = build_warnings([document_id], store)

    assert f"tokenizer_fallback_used:{document_id}" in warnings
    assert f"embedding_index_missing:{document_id}" in warnings


def test_package_hash_is_stable() -> None:
    kwargs = {
        "query_text": "trace",
        "purpose": "search",
        "document_ids": ["doc-1"],
        "evidence_items": [
            {
                "evidence_id": "ev-1",
                "chunk_id": "chunk-1",
                "scores": {"final_score": 0.5},
                "matched_terms": ["trace"],
            }
        ],
    }

    assert package_hash_for(**kwargs) == package_hash_for(**kwargs)


def test_package_hash_changes_when_quality_policy_changes() -> None:
    kwargs = {
        "query_text": "trace",
        "purpose": "search",
        "document_ids": ["doc-1"],
        "evidence_items": [
            {
                "evidence_id": "ev-1",
                "chunk_id": "chunk-1",
                "scores": {"final_score": 0.5},
                "matched_terms": ["trace"],
            }
        ],
    }

    assert package_hash_for(**kwargs) != package_hash_for(
        **kwargs,
        quality_policy=RetrievalQualityPolicy(low_confidence_threshold=0.9),
    )


def test_build_retrieval_context_package_returns_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, document_id = build_store_with_indexes(tmp_path, monkeypatch)

    package = build_retrieval_context_package(
        {
            "query_text": "trace evidence",
            "purpose": "search",
            "document_scope": {"document_ids": [document_id]},
            "actor_claims_ref": {"actor_type": "user", "actor_id": "user-1"},
            "top_k": 2,
        },
        store=store,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert package["retrieval_package_schema_version"] == "cx_retrieval_context_package.v1"
    assert package["status"] == "READY"
    assert package["permission_snapshot"]["actor_id"] == "user-1"
    assert package["retrieval_profile"]["embedding_profile"]["index_status"] == "READY"
    assert package["retrieval_profile"]["bm25_tokenizer_profile"]["bm25_tokenizer"] == (
        "korean_mixed_v1"
    )
    assert package["retrieval_profile"]["quality_policy"]["policy_id"] == (
        "retrieval_quality_v1"
    )
    assert package["retrieval_profile"]["quality_policy"]["policy_source"] == (
        "ag_registry_active"
    )
    assert package["score_summary"]["quality_policy_id"] == "retrieval_quality_v1"
    assert len(package["evidence_items"]) <= 2


def test_build_retrieval_context_package_records_weighted_rrf_query_embedding() -> None:
    store, document_id = build_weighted_rrf_store()

    package = build_retrieval_context_package(
        {
            "query_text": "alpha beta",
            "purpose": "search",
            "document_scope": {"document_ids": [document_id]},
            "query_embedding": [1.0, 0.0],
            "retrieval_policy": {"policy_id": WEIGHTED_RRF_RANKER_MIX},
        },
        store=store,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert package["status"] == "READY"
    assert package["query_embedding_snapshot"]["provided"] is True
    assert "query_embedding': [1.0" not in str(package)
    assert package["evidence_items"][0]["chunk_id"] == "chunk-vector"
    assert package["evidence_items"][0]["scores"]["vector_rank"] == 1
    assert package["score_summary"]["ranker_mix"] == WEIGHTED_RRF_RANKER_MIX
    assert package["retrieval_profile"]["embedding_profile"][
        "query_embedding_sha256"
    ] == package["query_embedding_snapshot"]["embedding_sha256"]


def test_build_retrieval_context_package_applies_quality_policy_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, document_id = build_store_with_indexes(tmp_path, monkeypatch)

    package = build_retrieval_context_package(
        {
            "query_text": "trace evidence",
            "purpose": "search",
            "document_scope": {"document_ids": [document_id]},
            "retrieval_policy": {
                "low_confidence_threshold": 0.95,
                "rerank_candidate_limit": 3,
            },
        },
        store=store,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert package["status"] == "LOW_CONFIDENCE"
    assert package["score_summary"]["low_confidence_threshold"] == 0.95
    assert package["retrieval_profile"]["quality_policy"]["rerank_candidate_limit"] == 3


def test_build_retrieval_context_package_records_reranker_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, document_id = build_store_with_indexes(tmp_path, monkeypatch)

    package = build_retrieval_context_package(
        {
            "query_text": "trace evidence",
            "purpose": "search",
            "document_scope": {"document_ids": [document_id]},
            "top_k": 1,
        },
        store=store,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        rerank_client=FakeMoRerankClient(),
        reranker_alias=DEFAULT_RERANKER_ALIAS,
    )

    assert package["retrieval_profile"]["reranker_profile"]["status"] == "APPLIED"
    assert package["score_summary"]["rerank_state"] == "APPLIED"


def test_build_retrieval_context_package_returns_no_answer() -> None:
    package = build_retrieval_context_package(
        {"query_text": "missing", "purpose": "search"},
        store=ContentIngestionStore(),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert package["status"] == "NO_ANSWER"
    assert package["no_answer_reason"] == "no_terms_matched"
    assert package["source_summary"]["chunk_count"] == 0


@pytest.mark.parametrize(
    "payload",
    [
        {"purpose": "search"},
        {"query_text": "trace", "top_k": 0},
        {"query_text": "trace", "top_k": 21},
        {"query_text": "trace", "top_k": True},
        {"query_text": "trace", "include_neighbors": "yes"},
        {"query_text": "trace", "include_source_preview": "yes"},
        {"query_text": "trace", "purpose": ""},
        {"query_text": "trace", "purpose": "unsupported"},
    ],
)
def test_build_retrieval_context_package_rejects_invalid_payloads(
    payload: dict[str, object],
) -> None:
    with pytest.raises(RetrievalError):
        build_retrieval_context_package(
            payload,
            store=ContentIngestionStore(),
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )


def test_retrieval_endpoint_requires_service_claim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = build_test_client(tmp_path, monkeypatch)

    response = client.post("/api/v1/retrieval/context", json={"query_text": "trace"})

    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"


def test_retrieval_read_requires_service_claim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = build_test_client(tmp_path, monkeypatch)

    response = client.get("/api/v1/retrieval/context/missing")

    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"


def test_retrieval_endpoint_creates_and_reads_context_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, store = build_test_client(tmp_path, monkeypatch)
    created = client.post(
        "/api/v1/documents/uploads",
        json={
            "filename": "source.txt",
            "content_type": "text/plain",
            "content_text": "NeX trace evidence package. Retrieval trace quality.",
        },
        headers=auth_headers(),
    ).json()
    client.post(f"/api/v1/jobs/{created['extraction']['job_id']}/run", headers=auth_headers())
    client.post(f"/api/v1/documents/{created['document_id']}/chunks/run", headers=auth_headers())
    client.post(
        f"/api/v1/documents/{created['document_id']}/embeddings/run",
        headers=auth_headers(),
    )
    client.post(
        f"/api/v1/documents/{created['document_id']}/lexical-index/run",
        headers=auth_headers(),
    )

    create_response = client.post(
        "/api/v1/retrieval/context",
        json={
            "query_text": "trace evidence",
            "purpose": "grounded_answer",
            "document_scope": {"document_ids": [created["document_id"]]},
            "top_k": 1,
            "include_neighbors": True,
        },
        headers=auth_headers(),
    )

    assert create_response.status_code == 200
    package = create_response.json()
    assert package["status"] == "READY"
    assert package["purpose"] == "grounded_answer"
    assert package["evidence_items"][0]["neighbor_context"] == [
        {"policy": "not_loaded_in_slice_0017"}
    ]
    assert store.get_retrieval_package(package["retrieval_package_id"]) == package

    read_response = client.get(
        f"/api/v1/retrieval/context/{package['retrieval_package_id']}",
        headers=auth_headers(),
    )
    assert read_response.status_code == 200
    assert read_response.json()["package_hash"] == package["package_hash"]


def test_retrieval_endpoint_returns_problem_for_bad_top_k(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = build_test_client(tmp_path, monkeypatch)

    response = client.post(
        "/api/v1/retrieval/context",
        json={"query_text": "trace", "top_k": 100},
        headers=auth_headers(),
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "cx.top_k_invalid"


def test_retrieval_read_reports_not_found(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = build_test_client(tmp_path, monkeypatch)

    response = client.get(
        "/api/v1/retrieval/context/missing",
        headers=auth_headers(),
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "cx.retrieval_package_not_found"
