from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any

import pytest

from nex_cx.access_context import CxAccessContext
from nex_cx.hybrid_ranking import (
    HybridRankingError,
    HybridRankingPolicy,
    MAX_CHUNK_TEXT_LENGTH,
    MAX_QUERY_TEXT_LENGTH,
    rank_permission_filtered_candidates,
)


QUERY = "alpha query"
DOC_ID = "document-owner-one"
CHUNK_A = "chunk-alpha"
CHUNK_B = "chunk-beta"
CHUNK_C = "chunk-charlie"
TEXTS = {
    (DOC_ID, CHUNK_A): "authorized alpha text",
    (DOC_ID, CHUNK_B): "authorized beta text",
    (DOC_ID, CHUNK_C): "authorized charlie text",
}


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _text_record(chunk_id: str) -> dict[str, Any]:
    text = TEXTS.get((DOC_ID, chunk_id), "unexpected text")
    return {
        "content_object_id": DOC_ID,
        "chunk_id": chunk_id,
        "chunk_text": text,
        "text_sha256": _digest(text),
    }


class FakeTextLoader:
    def __init__(self, *, records: object | None = None, error: Exception | None = None) -> None:
        self.records = records
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def load_authorized_texts(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        if self.records is not None:
            return deepcopy(self.records)
        records = []
        for ref in reversed(kwargs["chunk_refs"]):
            key = (ref["content_object_id"], ref["chunk_id"])
            text = TEXTS[key]
            records.append(
                {
                    **ref,
                    "chunk_text": text,
                    "text_sha256": _digest(text),
                }
            )
        return records


class FakeReranker:
    def __init__(self, *, response: object | None = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def rerank_documents(self, query: str, documents: list[str], **kwargs: Any) -> Any:
        self.calls.append({"query": query, "documents": documents, **kwargs})
        if self.error is not None:
            raise self.error
        if self.response is not None:
            return deepcopy(self.response)
        return {
            "alias": "reranker-safe",
            "model_revision": "bf16",
            "deployment_id": "test-deployment",
            "results": [
                {"index": index, "score": round(0.9 - index * 0.1, 2)}
                for index in range(len(documents))
            ],
        }


def test_weighted_rrf_ranks_permission_filtered_channels_without_private_text() -> None:
    result = _rank()

    assert [item["chunk_id"] for item in result["candidates"]] == [
        CHUNK_B,
        CHUNK_C,
        CHUNK_A,
    ]
    first = result["candidates"][0]
    assert first["channel_presence"] == ["bm25", "vector"]
    assert first["scores"]["bm25_rank"] == 2
    assert first["scores"]["vector_rank"] == 1
    assert first["scores"]["final_score"] == first["scores"]["rrf_normalized_score"]
    assert result["ranking_policy"] == {
        "policy_id": "weighted_rrf_vector_bm25_v1",
        "vector_weight": 0.7,
        "bm25_weight": 0.3,
        "rrf_k": 60,
        "rerank_candidate_limit": 50,
    }
    assert result["rerank_state"] == "NOT_REQUESTED"
    serialized = json.dumps(result)
    assert QUERY not in serialized
    assert "authorized alpha text" not in serialized


def test_rerank_loads_only_authorized_window_and_returns_hashes_not_text() -> None:
    loader = FakeTextLoader()
    reranker = FakeReranker(
        response={
            "results": [
                {"index": 1, "score": 0.97},
                {"index": 0, "score": 0.82},
            ]
        }
    )

    result = _rank(
        policy=HybridRankingPolicy(rerank_candidate_limit=2),
        text_loader=loader,
        rerank_client=reranker,
    )

    assert [item["chunk_id"] for item in result["candidates"]] == [
        CHUNK_C,
        CHUNK_B,
        CHUNK_A,
    ]
    assert loader.calls[0]["access_context"] == _context()
    assert loader.calls[0]["chunk_refs"] == [
        {"content_object_id": DOC_ID, "chunk_id": CHUNK_B},
        {"content_object_id": DOC_ID, "chunk_id": CHUNK_C},
    ]
    assert reranker.calls[0]["documents"] == [TEXTS[(DOC_ID, CHUNK_B)], TEXTS[(DOC_ID, CHUNK_C)]]
    assert reranker.calls[0]["query"] == QUERY
    assert reranker.calls[0]["request_id"] == "request-0946"
    assert reranker.calls[0]["trace_id"] == "94600000000000000000000000000001"
    assert reranker.calls[0]["top_n"] == 2
    assert result["candidates"][0]["text_sha256"] == _digest(TEXTS[(DOC_ID, CHUNK_C)])
    assert result["candidates"][2]["scores"]["rerank_score"] is None
    assert result["reranker_profile"] == {
        "status": "APPLIED",
        "provider_alias": "mock-reranker-default",
        "model_revision": None,
        "deployment_id": None,
    }
    serialized = json.dumps(result)
    assert QUERY not in serialized
    assert all(text not in serialized for text in TEXTS.values())


def test_empty_candidate_set_does_not_call_rerank_dependencies() -> None:
    candidate_set = _candidate_set()
    candidate_set["lexical_candidates"]["candidate_count"] = 0
    candidate_set["lexical_candidates"]["candidates"] = []
    candidate_set["vector_candidates"]["candidate_count"] = 0
    candidate_set["vector_candidates"]["candidates"] = []
    loader = FakeTextLoader(error=AssertionError("must not load"))
    reranker = FakeReranker(error=AssertionError("must not rerank"))

    result = _rank(candidate_set=candidate_set, text_loader=loader, rerank_client=reranker)

    assert result["candidate_count"] == 0
    assert result["rerank_state"] == "NOT_REQUESTED"
    assert loader.calls == []
    assert reranker.calls == []


@pytest.mark.parametrize("query", [None, "   ", "x" * (MAX_QUERY_TEXT_LENGTH + 1)])
def test_query_validation_is_fail_closed(query: object) -> None:
    with pytest.raises(HybridRankingError) as exc:
        _rank(query_text=query)  # type: ignore[arg-type]

    assert exc.value.status_code == 422
    assert exc.value.error_code == "CX_HYBRID_RANKING_REQUEST_INVALID"


@pytest.mark.parametrize(
    "policy",
    [
        object(),
        HybridRankingPolicy(policy_id="other"),
        HybridRankingPolicy(rrf_k=True),
        HybridRankingPolicy(rrf_k=0),
        HybridRankingPolicy(rrf_k=10_001),
        HybridRankingPolicy(rerank_candidate_limit=True),
        HybridRankingPolicy(rerank_candidate_limit=0),
        HybridRankingPolicy(rerank_candidate_limit=101),
        HybridRankingPolicy(vector_weight=True),
        HybridRankingPolicy(vector_weight=float("nan")),
        HybridRankingPolicy(vector_weight=1.1, bm25_weight=-0.1),
        HybridRankingPolicy(vector_weight=0.5, bm25_weight=0.4),
    ],
)
def test_policy_validation_is_fail_closed(policy: object) -> None:
    with pytest.raises(HybridRankingError) as exc:
        _rank(policy=policy)  # type: ignore[arg-type]

    assert exc.value.error_code == "CX_HYBRID_RANKING_POLICY_INVALID"


def test_custom_valid_policy_is_applied() -> None:
    result = _rank(
        policy=HybridRankingPolicy(
            vector_weight=0.6,
            bm25_weight=0.4,
            rrf_k=30,
            rerank_candidate_limit=2,
        )
    )

    assert result["ranking_policy"]["vector_weight"] == 0.6
    assert result["ranking_policy"]["rrf_k"] == 30


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: "bad",
        lambda value: {**value, "hybrid_candidate_set_schema_version": "old"},
        lambda value: {**value, "permission_enforced_before_candidates": False},
        lambda value: {**value, "permission_policy": "other"},
        lambda value: {**value, "permission_snapshot": "bad"},
        lambda value: _mutate_snapshot(value, "permission_snapshot_schema_version", "old"),
        lambda value: _mutate_snapshot(value, "policy_version", "other"),
        lambda value: _mutate_snapshot(value, "actor_type", "service"),
        lambda value: _mutate_snapshot(value, "actor_id", "other-owner"),
        lambda value: _mutate_snapshot(value, "tenant_ref", "bad"),
        lambda value: _mutate_snapshot(value, "tenant_ref", {"type": "bad", "id": "tenant-one"}),
        lambda value: _mutate_snapshot(value, "tenant_ref", {"type": "oa.tenant", "id": "other"}),
        lambda value: _mutate_snapshot(value, "scope_applied", "bad"),
        lambda value: _mutate_snapshot(value, "scope_applied", {"type": "all", "document_ids": [DOC_ID]}),
        lambda value: _mutate_snapshot(value, "scope_applied", {"type": "document_ids", "document_ids": "bad"}),
        lambda value: _mutate_snapshot(value, "scope_applied", {"type": "document_ids", "document_ids": [""]}),
        lambda value: _mutate_snapshot(
            value,
            "scope_applied",
            {"type": "document_ids", "document_ids": [DOC_ID, DOC_ID]},
        ),
        lambda value: _mutate_snapshot(value, "visible_document_count", 2),
        lambda value: {**value, "query_sha256": "0" * 64},
    ],
)
def test_permission_continuity_rejects_drift(mutation) -> None:
    with pytest.raises(HybridRankingError) as exc:
        _rank(candidate_set=mutation(_candidate_set()))

    assert exc.value.error_code == "CX_RETRIEVAL_PERMISSION_CONTINUITY_INVALID"


@pytest.mark.parametrize(
    "target,mutation",
    [
        ("lexical_candidates", lambda value: "bad"),
        ("lexical_candidates", lambda value: {**value, "candidates": "bad"}),
        ("lexical_candidates", lambda value: {**value, "candidate_count": 99}),
        ("lexical_candidates", lambda value: {**value, "candidate_source": "bad"}),
        ("lexical_candidates", lambda value: {**value, "candidates": ["bad"], "candidate_count": 1}),
        ("lexical_candidates", lambda value: _mutate_first(value, "content_object_id", "")),
        ("lexical_candidates", lambda value: _mutate_first(value, "chunk_id", None)),
        ("lexical_candidates", lambda value: _mutate_first(value, "bm25_score", True)),
        ("lexical_candidates", lambda value: _mutate_first(value, "bm25_score", 0.0)),
        ("lexical_candidates", lambda value: _mutate_first(value, "lexical_candidate_schema_version", "old")),
        ("lexical_candidates", lambda value: _mutate_first(value, "candidate_source", "bad")),
        ("lexical_candidates", lambda value: _mutate_first(value, "content_object_id", "foreign")),
        ("lexical_candidates", lambda value: _duplicate_first(value)),
        ("lexical_candidates", lambda value: _mutate_first(value, "text_sha256", "bad")),
        ("vector_candidates", lambda value: _mutate_first(value, "vector_score", float("inf"))),
        ("vector_candidates", lambda value: _mutate_first(value, "vector_candidate_schema_version", "old")),
    ],
)
def test_candidate_channel_validation_rejects_malformed_results(target: str, mutation) -> None:
    candidate_set = _candidate_set()
    candidate_set[target] = mutation(candidate_set[target])

    with pytest.raises(HybridRankingError) as exc:
        _rank(candidate_set=candidate_set)

    assert exc.value.error_code == "CX_HYBRID_CANDIDATE_SET_INVALID"


def test_vector_channel_accepts_negative_similarity_rank() -> None:
    candidate_set = _candidate_set()
    candidate_set["vector_candidates"]["candidates"][1]["vector_score"] = -0.1

    result = _rank(candidate_set=candidate_set)

    assert result["candidate_count"] == 3


def test_candidate_merge_rejects_conflicting_text_hash() -> None:
    candidate_set = _candidate_set()
    candidate_set["vector_candidates"]["candidates"][0]["text_sha256"] = "f" * 64

    with pytest.raises(HybridRankingError) as exc:
        _rank(candidate_set=candidate_set)

    assert exc.value.error_code == "CX_HYBRID_CANDIDATE_SET_INVALID"


def test_candidate_merge_uses_vector_hash_when_lexical_hash_is_absent() -> None:
    candidate_set = _candidate_set()
    candidate_set["lexical_candidates"]["candidates"][1]["text_sha256"] = None
    candidate_set["vector_candidates"]["candidates"][0]["text_sha256"] = "f" * 64

    result = _rank(candidate_set=candidate_set)

    assert result["candidates"][0]["text_sha256"] == "f" * 64


def test_reranker_requires_authorized_text_loader_and_valid_alias() -> None:
    with pytest.raises(HybridRankingError) as missing:
        _rank(rerank_client=FakeReranker())
    with pytest.raises(HybridRankingError) as alias:
        _rank(text_loader=FakeTextLoader(), rerank_client=FakeReranker(), reranker_alias=" ")

    assert missing.value.error_code == "CX_AUTHORIZED_TEXT_LOADER_REQUIRED"
    assert alias.value.error_code == "CX_HYBRID_RANKING_REQUEST_INVALID"


def test_loader_and_reranker_failures_are_redacted_as_retryable() -> None:
    with pytest.raises(HybridRankingError) as loader_error:
        _rank(
            text_loader=FakeTextLoader(error=RuntimeError("SECRET_LOADER_DETAIL")),
            rerank_client=FakeReranker(),
        )
    with pytest.raises(HybridRankingError) as reranker_error:
        _rank(
            text_loader=FakeTextLoader(),
            rerank_client=FakeReranker(error=RuntimeError("SECRET_PROVIDER_DETAIL")),
        )

    assert loader_error.value.error_code == "CX_PRIVATE_CHUNK_TEXT_UNAVAILABLE"
    assert loader_error.value.retryable is True
    assert "SECRET_LOADER_DETAIL" not in loader_error.value.detail
    assert reranker_error.value.error_code == "CX_RERANKER_UNAVAILABLE"
    assert reranker_error.value.retryable is True
    assert "SECRET_PROVIDER_DETAIL" not in reranker_error.value.detail


@pytest.mark.parametrize(
    "records",
    [
        "bad",
        ["bad"],
        [{"content_object_id": "", "chunk_id": CHUNK_B, "chunk_text": "x", "text_sha256": _digest("x")}],
        [{"content_object_id": DOC_ID, "chunk_id": "", "chunk_text": "x", "text_sha256": _digest("x")}],
        [_text_record(CHUNK_B), _text_record(CHUNK_B)],
        [{**_text_record(CHUNK_B), "chunk_text": None}],
        [{**_text_record(CHUNK_B), "chunk_text": ""}],
        [
            {
                **_text_record(CHUNK_B),
                "chunk_text": "x" * (MAX_CHUNK_TEXT_LENGTH + 1),
                "text_sha256": _digest("x" * (MAX_CHUNK_TEXT_LENGTH + 1)),
            }
        ],
        [{**_text_record(CHUNK_B), "text_sha256": "bad"}],
        [{**_text_record(CHUNK_B), "text_sha256": "0" * 64}],
        [_text_record("unexpected")],
    ],
)
def test_private_text_lineage_rejects_malformed_loader_records(records: object) -> None:
    with pytest.raises(HybridRankingError) as exc:
        _rank(
            policy=HybridRankingPolicy(rerank_candidate_limit=1),
            text_loader=FakeTextLoader(records=records),
            rerank_client=FakeReranker(),
        )

    assert exc.value.error_code == "CX_PRIVATE_CHUNK_TEXT_LINEAGE_INVALID"


def test_private_text_lineage_rejects_candidate_hash_mismatch() -> None:
    candidate_set = _candidate_set()
    candidate_set["lexical_candidates"]["candidates"][1]["text_sha256"] = "a" * 64

    with pytest.raises(HybridRankingError) as exc:
        _rank(
            candidate_set=candidate_set,
            policy=HybridRankingPolicy(rerank_candidate_limit=1),
            text_loader=FakeTextLoader(),
            rerank_client=FakeReranker(),
        )

    assert exc.value.error_code == "CX_PRIVATE_CHUNK_TEXT_LINEAGE_INVALID"


@pytest.mark.parametrize(
    "response",
    [
        "bad",
        {"results": "bad"},
        {"results": []},
        {"results": ["bad"]},
        {"results": [{"index": True, "score": 0.5}]},
        {"results": [{"index": "0", "score": 0.5}]},
        {"results": [{"index": 1, "score": 0.5}]},
        {"results": [{"index": 0, "score": True}]},
        {"results": [{"index": 0, "score": float("nan")}]},
        {"results": [{"index": 0, "score": 1.1}]},
        {"results": [{"index": 0, "score": 0.5}], "alias": 3},
        {"results": [{"index": 0, "score": 0.5}], "model_revision": ""},
        {"results": [{"index": 0, "score": 0.5}], "deployment_id": "x" * 161},
    ],
)
def test_rerank_response_validation_is_fail_closed(response: object) -> None:
    with pytest.raises(HybridRankingError) as exc:
        _rank(
            policy=HybridRankingPolicy(rerank_candidate_limit=1),
            text_loader=FakeTextLoader(),
            rerank_client=FakeReranker(response=response),
        )

    assert exc.value.error_code == "CX_RERANK_RESPONSE_INVALID"
    assert exc.value.retryable is True


def test_rerank_response_rejects_duplicate_indexes() -> None:
    response = {
        "results": [
            {"index": 0, "score": 0.9},
            {"index": 0, "score": 0.8},
        ]
    }

    with pytest.raises(HybridRankingError) as exc:
        _rank(
            policy=HybridRankingPolicy(rerank_candidate_limit=2),
            text_loader=FakeTextLoader(),
            rerank_client=FakeReranker(response=response),
        )

    assert exc.value.error_code == "CX_RERANK_RESPONSE_INVALID"


def test_rerank_profile_uses_valid_provider_metadata() -> None:
    result = _rank(text_loader=FakeTextLoader(), rerank_client=FakeReranker())

    assert result["reranker_profile"] == {
        "status": "APPLIED",
        "provider_alias": "reranker-safe",
        "model_revision": "bf16",
        "deployment_id": "test-deployment",
    }


def _rank(**overrides: Any) -> dict[str, Any]:
    kwargs = {
        "access_context": _context(),
        "query_text": QUERY,
        "candidate_set": _candidate_set(),
    }
    kwargs.update(overrides)
    return rank_permission_filtered_candidates(**kwargs)


def _context() -> CxAccessContext:
    return CxAccessContext(
        caller_service_id="nex-cx",
        tenant_id="tenant-one",
        subject_id="owner-one",
        request_id="request-0946",
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
            "permission_snapshot_schema_version": "cx_retrieval_permission_snapshot.v1",
            "actor_type": "oa.user",
            "actor_id": "owner-one",
            "tenant_ref": {"type": "oa.tenant", "id": "tenant-one"},
            "scope_applied": {"type": "document_ids", "document_ids": [DOC_ID]},
            "visible_document_count": 1,
            "policy_version": "cx.private_owner_active.v1",
        },
        "lexical_candidates": {
            "candidate_source": "postgresql_bm25",
            "candidate_count": 2,
            "candidates": [
                _lexical(CHUNK_A, score=9.0),
                _lexical(CHUNK_B, score=8.0),
            ],
        },
        "vector_candidates": {
            "candidate_source": "postgresql_pgvector",
            "candidate_count": 2,
            "candidates": [
                _vector(CHUNK_B, score=0.95),
                _vector(CHUNK_C, score=0.9),
            ],
        },
    }


def _lexical(chunk_id: str, *, score: float) -> dict[str, Any]:
    return {
        "lexical_candidate_schema_version": "cx_lexical_candidate.v1",
        "candidate_source": "postgresql_bm25",
        "content_object_id": DOC_ID,
        "chunk_id": chunk_id,
        "text_sha256": _digest(TEXTS[(DOC_ID, chunk_id)]),
        "bm25_score": score,
    }


def _vector(chunk_id: str, *, score: float) -> dict[str, Any]:
    return {
        "vector_candidate_schema_version": "cx_vector_candidate.v1",
        "candidate_source": "postgresql_pgvector",
        "content_object_id": DOC_ID,
        "chunk_id": chunk_id,
        "vector_score": score,
    }


def _mutate_snapshot(value: dict[str, Any], key: str, replacement: object) -> dict[str, Any]:
    copied = deepcopy(value)
    copied["permission_snapshot"][key] = replacement
    return copied


def _mutate_first(value: dict[str, Any], key: str, replacement: object) -> dict[str, Any]:
    copied = deepcopy(value)
    copied["candidates"][0][key] = replacement
    return copied


def _duplicate_first(value: dict[str, Any]) -> dict[str, Any]:
    copied = deepcopy(value)
    copied["candidates"].append(deepcopy(copied["candidates"][0]))
    copied["candidate_count"] += 1
    return copied
