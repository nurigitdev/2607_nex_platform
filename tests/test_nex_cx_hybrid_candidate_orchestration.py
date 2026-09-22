from __future__ import annotations

from typing import Any

import pytest

from nex_cx.access_context import CxAccessContext
from nex_cx.hybrid_candidate_orchestration import (
    HybridCandidateOrchestrationError,
    orchestrate_permission_filtered_candidates,
)
from nex_cx.lexical_candidates import LexicalCandidateStoreError
from nex_cx.lexical_index import TokenizerUnavailable
from nex_cx.retrieval_permissions import RetrievalPermissionError
from nex_cx.vector_candidates import VectorCandidateError
from nex_cx.vector_index_repository import InMemoryVectorIndexRepository


def _context() -> CxAccessContext:
    return CxAccessContext(
        caller_service_id="nex-cx",
        tenant_id="tenant-a",
        subject_id="owner-a",
        request_id="request-0945",
        trace_id="94500000000000000000000000000001",
        scopes=("service:call",),
    )


def _content(document_id: str, *, owner: str = "owner-a", status: str = "ACTIVE"):
    return {
        "content_object_id": document_id,
        "tenant_ref": {"type": "oa.tenant", "id": "tenant-a"},
        "owner_subject_ref": {"type": "oa.user", "id": owner},
        "lifecycle_status": status,
    }


def _target(document_id: str) -> dict[str, Any]:
    return {
        "content_object_id": document_id,
        "vector_index_id": f"index-{document_id}",
        "source_snapshot": {"chunk_refs": [{"chunk_id": f"chunk-{document_id}"}]},
        "embedding_profile": {"vector_dimension": 2},
        "permission_decision": {
            "visible": True,
            "policy_version": "cx.private_owner_active.v1",
        },
    }


def _lexical(document_id: str) -> dict[str, Any]:
    return {
        "content_object_id": document_id,
        "chunk_id": f"chunk-{document_id}",
        "bm25_score": 1.25,
        "text_preview": "authorized preview",
    }


class _LexicalStore:
    def __init__(
        self,
        candidates: list[dict[str, Any]] | None = None,
        error: Exception | None = None,
        events: list[str] | None = None,
    ) -> None:
        self.candidates = candidates or []
        self.error = error
        self.events = events
        self.calls: list[dict[str, Any]] = []

    def search(self, **kwargs):
        if self.events is not None:
            self.events.append("lexical")
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.candidates


def _run(
    *,
    documents: dict[str, object] | None = None,
    requested: list[str] | None = None,
    lexical_store: _LexicalStore | None = None,
    vector_targets: dict[str, dict[str, Any]] | None = None,
    query_vector: list[float] | None = None,
    tokenizer_requested: str = "korean_mixed_v1",
    tokenizer_fallback: str = "korean_mixed_v1",
    **overrides,
):
    return orchestrate_permission_filtered_candidates(
        access_context=_context(),
        query_text="alpha beta",
        requested_document_ids=requested if requested is not None else ["doc-a"],
        content_objects=(
            documents if documents is not None else {"doc-a": _content("doc-a")}
        ),
        lexical_store=lexical_store or _LexicalStore([_lexical("doc-a")]),
        vector_targets_by_document_id=(
            vector_targets if vector_targets is not None else {}
        ),
        query_vector=query_vector,
        vector_repository=InMemoryVectorIndexRepository(),
        vector_store=object(),  # type: ignore[arg-type]
        tokenizer_requested=tokenizer_requested,
        tokenizer_fallback=tokenizer_fallback,
        **overrides,
    )


def test_permission_precedes_lexical_and_vector_candidate_generation(monkeypatch) -> None:
    events: list[str] = []
    lexical = _LexicalStore([_lexical("doc-a")], events=events)

    def fake_tokenize(tokenizer, text):
        events.append("tokenize")
        return ["alpha", "beta", "alpha"]

    def fake_vector(**kwargs):
        events.append("vector")
        assert [target["content_object_id"] for target in kwargs["targets"]] == ["doc-a"]
        return {
            "vector_candidate_result_schema_version": "cx_vector_candidate_result.v1",
            "candidate_source": "postgresql_pgvector",
            "query_dimension": 2,
            "requested_index_count": 1,
            "admitted_index_count": 1,
            "excluded_index_count": 0,
            "exclusion_counts": {},
            "candidate_count": 1,
            "candidates": [
                {"content_object_id": "doc-a", "chunk_id": "chunk-doc-a"}
            ],
        }

    monkeypatch.setattr(
        "nex_cx.hybrid_candidate_orchestration.tokenize_with",
        fake_tokenize,
    )
    monkeypatch.setattr(
        "nex_cx.hybrid_candidate_orchestration.collect_fresh_vector_candidates",
        fake_vector,
    )

    result = _run(
        lexical_store=lexical,
        vector_targets={"doc-a": _target("doc-a")},
        query_vector=[1.0, 0.0],
    )

    assert events == ["tokenize", "lexical", "vector"]
    assert lexical.calls[0]["content_object_ids"] == ["doc-a"]
    assert lexical.calls[0]["query_terms"] == ["alpha", "beta"]
    assert result["permission_enforced_before_candidates"] is True
    assert result["permission_snapshot"]["visible_document_count"] == 1
    assert result["lexical_candidates"]["candidate_count"] == 1
    assert result["vector_candidates"]["status"] == "READY"
    assert result["query_sha256"] != "alpha beta"


@pytest.mark.parametrize("visibility", ["foreign", "inactive", "missing"])
def test_denied_explicit_scope_stops_before_private_candidate_access(
    monkeypatch,
    visibility,
) -> None:
    lexical = _LexicalStore([_lexical("doc-a")])
    documents = {}
    if visibility == "foreign":
        documents["doc-a"] = _content("doc-a", owner="owner-b")
    elif visibility == "inactive":
        documents["doc-a"] = _content("doc-a", status="DELETED")
    tokenize_calls = 0

    def forbidden_tokenize(*_args):
        nonlocal tokenize_calls
        tokenize_calls += 1
        return []

    monkeypatch.setattr(
        "nex_cx.hybrid_candidate_orchestration.tokenize_with",
        forbidden_tokenize,
    )

    with pytest.raises(RetrievalPermissionError) as captured:
        _run(documents=documents, lexical_store=lexical)

    assert captured.value.status_code == 404
    assert tokenize_calls == 0
    assert lexical.calls == []


def test_tokenizer_falls_back_without_changing_permission_scope(monkeypatch) -> None:
    calls: list[str] = []

    def tokenize(tokenizer, _text):
        calls.append(tokenizer)
        if tokenizer == "mecab_ko":
            raise TokenizerUnavailable("missing")
        return ["Beta", "alpha", "beta"]

    monkeypatch.setattr(
        "nex_cx.hybrid_candidate_orchestration.tokenize_with",
        tokenize,
    )
    lexical = _LexicalStore([_lexical("doc-a")])

    result = _run(
        lexical_store=lexical,
        tokenizer_requested="mecab_ko",
        tokenizer_fallback="korean_mixed_v1",
    )

    assert calls == ["mecab_ko", "korean_mixed_v1"]
    assert lexical.calls[0]["query_terms"] == ["alpha", "beta"]
    assert result["tokenizer_profile"]["fallback_used"] is True
    assert result["tokenizer_profile"]["bm25_tokenizer"] == "korean_mixed_v1"


def test_both_tokenizers_unavailable_is_redacted(monkeypatch) -> None:
    def unavailable(*_args):
        raise TokenizerUnavailable("private tokenizer detail")

    monkeypatch.setattr(
        "nex_cx.hybrid_candidate_orchestration.tokenize_with",
        unavailable,
    )

    with pytest.raises(HybridCandidateOrchestrationError) as captured:
        _run(tokenizer_requested="mecab_ko")

    assert captured.value.status_code == 503
    assert captured.value.error_code == "CX_QUERY_TOKENIZER_UNAVAILABLE"
    assert "private" not in captured.value.detail


@pytest.mark.parametrize(
    "candidate",
    [
        None,
        {"content_object_id": "doc-b", "chunk_id": "chunk", "bm25_score": 1.0},
        {"content_object_id": "doc-a", "chunk_id": "", "bm25_score": 1.0},
        {"content_object_id": "doc-a", "chunk_id": "chunk", "bm25_score": True},
        {"content_object_id": "doc-a", "chunk_id": "chunk", "bm25_score": -1.0},
        {"content_object_id": "doc-a", "chunk_id": "chunk", "bm25_score": float("nan")},
    ],
)
def test_lexical_candidates_are_rechecked_against_visible_scope(candidate) -> None:
    lexical = _LexicalStore([candidate])

    with pytest.raises(HybridCandidateOrchestrationError) as captured:
        _run(lexical_store=lexical)

    assert captured.value.error_code == "CX_HYBRID_CANDIDATE_RESULT_INVALID"


@pytest.mark.parametrize("candidates", ["wrong", [_lexical("doc-a"), _lexical("doc-a")]])
def test_lexical_result_shape_and_bound_are_enforced(candidates) -> None:
    lexical = _LexicalStore(candidates)  # type: ignore[arg-type]

    with pytest.raises(HybridCandidateOrchestrationError) as captured:
        _run(lexical_store=lexical, lexical_limit=1)

    assert captured.value.status_code == 500


def test_lexical_store_failures_are_redacted() -> None:
    lexical = _LexicalStore(
        error=LexicalCandidateStoreError(
            error_code="CX_LEXICAL_SEARCH_UNAVAILABLE",
            detail="private database detail",
        )
    )

    with pytest.raises(HybridCandidateOrchestrationError) as captured:
        _run(lexical_store=lexical)

    assert captured.value.status_code == 503
    assert captured.value.retryable is True
    assert "private" not in captured.value.detail


def test_unexpected_lexical_failure_is_redacted() -> None:
    lexical = _LexicalStore(error=RuntimeError("private database detail"))

    with pytest.raises(HybridCandidateOrchestrationError) as captured:
        _run(lexical_store=lexical)

    assert captured.value.error_code == "CX_HYBRID_CANDIDATE_SEARCH_UNAVAILABLE"
    assert "private" not in captured.value.detail


def test_missing_query_vector_produces_explicit_lexical_only_state() -> None:
    result = _run(vector_targets={"doc-a": _target("doc-a")})

    vector = result["vector_candidates"]
    assert vector["status"] == "QUERY_VECTOR_NOT_PROVIDED"
    assert vector["candidate_count"] == 0
    assert vector["missing_target_count"] == 0


def test_missing_vector_target_produces_bm25_only_state() -> None:
    result = _run(query_vector=[1.0, 0.0])

    vector = result["vector_candidates"]
    assert vector["status"] == "BM25_ONLY"
    assert vector["missing_target_count"] == 1
    assert vector["requested_index_count"] == 0


def test_vector_target_must_match_visible_document_key() -> None:
    with pytest.raises(HybridCandidateOrchestrationError) as captured:
        _run(
            vector_targets={"doc-a": _target("doc-b")},
            query_vector=[1.0, 0.0],
        )

    assert captured.value.error_code == "CX_HYBRID_CANDIDATE_RESULT_INVALID"


def test_foreign_vector_candidate_from_adapter_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr(
        "nex_cx.hybrid_candidate_orchestration.collect_fresh_vector_candidates",
        lambda **_kwargs: {"candidates": [{"content_object_id": "doc-b"}]},
    )

    with pytest.raises(HybridCandidateOrchestrationError) as captured:
        _run(
            vector_targets={"doc-a": _target("doc-a")},
            query_vector=[1.0, 0.0],
        )

    assert captured.value.error_code == "CX_HYBRID_CANDIDATE_RESULT_INVALID"


@pytest.mark.parametrize("result", [None, {"candidates": "wrong"}])
def test_malformed_vector_result_fails_closed(monkeypatch, result) -> None:
    monkeypatch.setattr(
        "nex_cx.hybrid_candidate_orchestration.collect_fresh_vector_candidates",
        lambda **_kwargs: result,
    )

    with pytest.raises(HybridCandidateOrchestrationError) as captured:
        _run(
            vector_targets={"doc-a": _target("doc-a")},
            query_vector=[1.0, 0.0],
        )

    assert captured.value.error_code == "CX_HYBRID_CANDIDATE_RESULT_INVALID"


@pytest.mark.parametrize(
    ("error_code", "status_code", "expected_code"),
    [
        ("CX_VECTOR_QUERY_INVALID", 422, "CX_HYBRID_CANDIDATE_REQUEST_INVALID"),
        ("CX_VECTOR_CANDIDATE_LIMIT_INVALID", 422, "CX_HYBRID_CANDIDATE_REQUEST_INVALID"),
        ("CX_VECTOR_CANDIDATE_SEARCH_UNAVAILABLE", 503, "CX_HYBRID_CANDIDATE_SEARCH_UNAVAILABLE"),
        ("CX_VECTOR_TARGETS_INVALID", 500, "CX_HYBRID_CANDIDATE_RESULT_INVALID"),
    ],
)
def test_vector_errors_are_mapped_to_orchestration_boundary(
    monkeypatch,
    error_code,
    status_code,
    expected_code,
) -> None:
    def fail(**_kwargs):
        raise VectorCandidateError(error_code=error_code, detail="safe detail")

    monkeypatch.setattr(
        "nex_cx.hybrid_candidate_orchestration.collect_fresh_vector_candidates",
        fail,
    )

    with pytest.raises(HybridCandidateOrchestrationError) as captured:
        _run(
            vector_targets={"doc-a": _target("doc-a")},
            query_vector=[1.0, 0.0],
        )

    assert captured.value.status_code == status_code
    assert captured.value.error_code == expected_code


@pytest.mark.parametrize(
    "overrides",
    [
        {"query_text": None},
        {"query_text": ""},
        {"query_text": "x" * 16_001},
        {"lexical_limit": True},
        {"lexical_limit": 501},
        {"vector_limit": 0},
        {"vector_limit": 101},
        {"content_objects": []},
        {"vector_targets_by_document_id": []},
    ],
)
def test_invalid_requests_are_rejected(overrides) -> None:
    kwargs = {
        "access_context": _context(),
        "query_text": "alpha",
        "requested_document_ids": ["doc-a"],
        "content_objects": {"doc-a": _content("doc-a")},
        "lexical_store": _LexicalStore(),
        "vector_targets_by_document_id": {},
        "query_vector": None,
        "vector_repository": InMemoryVectorIndexRepository(),
        "vector_store": object(),
        "tokenizer_requested": "korean_mixed_v1",
    }
    kwargs.update(overrides)

    with pytest.raises(HybridCandidateOrchestrationError) as captured:
        orchestrate_permission_filtered_candidates(**kwargs)  # type: ignore[arg-type]

    assert captured.value.status_code == 422


@pytest.mark.parametrize(
    ("result", "missing", "status"),
    [
        ({"admitted_index_count": 1, "excluded_index_count": 1}, 0, "DEGRADED"),
        ({"admitted_index_count": 1, "excluded_index_count": 0}, 1, "DEGRADED"),
        ({"admitted_index_count": 0, "excluded_index_count": 1}, 0, "BM25_ONLY"),
    ],
)
def test_vector_status_reports_degradation(monkeypatch, result, missing, status) -> None:
    payload = {**result, "candidates": []}
    monkeypatch.setattr(
        "nex_cx.hybrid_candidate_orchestration.collect_fresh_vector_candidates",
        lambda **_kwargs: payload,
    )
    targets = {"doc-a": _target("doc-a")} if missing == 0 else {}

    value = _run(vector_targets=targets, query_vector=[1.0, 0.0])

    assert value["vector_candidates"]["status"] == status
