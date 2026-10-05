from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from typing import Any

import pytest

from nex_cx.access_context import CxAccessContext
from nex_cx.hybrid_candidate_orchestration import HybridCandidateOrchestrationError
from nex_cx.hybrid_retrieval_runtime import (
    ProductionAuthorizedEvidenceMaterializer,
    ProductionHybridCandidateProvider,
    _optional_identity,
    _document_ids,
    build_permission_hardened_hybrid_runtime,
)
from nex_cx.retrieval_permissions import RetrievalPermissionError


CONTEXT = CxAccessContext(
    caller_service_id="nex-ae-api",
    tenant_id="tenant-s100",
    subject_id="owner-s100",
    request_id="request-s100",
    trace_id="trace-s100",
    scopes=("service.invoke",),
)
CHUNK_TEXT = "권한 기반 검색 결과"
CHUNK_SHA256 = hashlib.sha256(CHUNK_TEXT.encode("utf-8")).hexdigest()


def _content(owner: str = "owner-s100") -> dict[str, Any]:
    return {
        "content_object_id": "document-s100",
        "tenant_ref": {"type": "oa.tenant", "id": "tenant-s100"},
        "owner_subject_ref": {"type": "oa.user", "id": owner},
        "lifecycle_status": "ACTIVE",
    }


@dataclass
class FakeSource:
    content: dict[str, Any] = field(default_factory=_content)
    calls: list[str] = field(default_factory=list)

    def load_content_objects(self, document_ids):
        self.calls.append("content")
        return {document_id: self.content for document_id in document_ids}

    def load_vector_targets(self, *, access_context, document_ids):
        self.calls.append("vectors")
        return {}

    def load_private_evidence(self, *, access_context, chunk_refs):
        self.calls.append("evidence")
        return [
            {
                **ref,
                "chunk_text": CHUNK_TEXT,
                "text_sha256": CHUNK_SHA256,
                "chunk_policy_id": "chunk_1000_100",
                "start_offset": 0,
                "end_offset": 11,
                "matched_terms": ["권한", "검색"],
            }
            for ref in chunk_refs
        ]


class FakeLexicalStore:
    def __init__(self):
        self.calls = 0

    def search(self, **kwargs):
        self.calls += 1
        return [
            {
                "lexical_candidate_schema_version": "cx_lexical_candidate.v1",
                "candidate_source": "postgresql_bm25",
                "content_object_id": "document-s100",
                "chunk_id": "chunk-s100",
                "bm25_score": 2.5,
                "text_sha256": CHUNK_SHA256,
                "matched_terms": ["권한", "검색"],
            }
        ]


@dataclass
class FakeEmbeddingClient:
    response: object = field(
        default_factory=lambda: {"data": [{"embedding": [0.1, 0.2]}]}
    )
    calls: int = 0

    def create_embeddings(self, inputs, **kwargs):
        self.calls += 1
        return self.response


class RaisingEmbeddingClient:
    def create_embeddings(self, inputs, **kwargs):
        raise HybridCandidateOrchestrationError(
            status_code=429,
            error_code="CX_EMBEDDING_THROTTLED",
            detail="throttled",
            retryable=True,
        )


def _provider(source=None, embedding=None):
    return ProductionHybridCandidateProvider(
        source=source or FakeSource(),
        lexical_store=FakeLexicalStore(),
        vector_repository=object(),
        vector_store=object(),
        embedding_client=embedding or FakeEmbeddingClient(),
        embedding_alias="embedding-primary",
    )


def test_candidate_provider_enforces_permission_before_embedding() -> None:
    source = FakeSource()
    embedding = FakeEmbeddingClient()
    result = _provider(source, embedding).build_candidate_set(
        access_context=CONTEXT,
        query_text="권한 검색",
        requested_document_ids=["document-s100"],
    )

    assert source.calls == ["content", "vectors"]
    assert embedding.calls == 1
    assert result["permission_enforced_before_candidates"] is True
    assert result["lexical_candidates"]["candidate_count"] == 1
    assert result["vector_candidates"]["status"] == "BM25_ONLY"
    assert len(result["query_vector_sha256"]) == 64
    assert result["query_embedding_profile"] == {
        "provider_alias": "embedding-primary",
        "model_revision": None,
        "deployment_id": None,
    }


def test_candidate_provider_preserves_safe_embedding_identity() -> None:
    embedding = FakeEmbeddingClient(
        {
            "alias": "embedding-default",
            "model_revision": "Qwen3-Embedding-4B",
            "deployment_id": "dgx-embedding-9112",
            "data": [{"embedding": [0.1, 0.2]}],
        }
    )

    result = _provider(embedding=embedding).build_candidate_set(
        access_context=CONTEXT,
        query_text="권한 검색",
        requested_document_ids=["document-s100"],
    )

    assert result["query_embedding_profile"] == {
        "provider_alias": "embedding-default",
        "model_revision": "Qwen3-Embedding-4B",
        "deployment_id": "dgx-embedding-9112",
    }


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, None), ("", None), (" " * 3, None), ("x" * 161, None), (" model ", "model")],
)
def test_optional_embedding_identity_is_bounded(value, expected) -> None:
    assert _optional_identity(value) == expected


def test_candidate_provider_hides_foreign_document_before_provider_call() -> None:
    source = FakeSource(content=_content("owner-other"))
    embedding = FakeEmbeddingClient()

    with pytest.raises(RetrievalPermissionError) as exc_info:
        _provider(source, embedding).build_candidate_set(
            access_context=CONTEXT,
            query_text="권한 검색",
            requested_document_ids=["document-s100"],
        )
    assert exc_info.value.status_code == 404
    assert embedding.calls == 0
    assert source.calls == ["content"]


def test_candidate_provider_rejects_mixed_owner_scope_before_all_candidates() -> None:
    class MixedOwnerSource(FakeSource):
        def load_content_objects(self, document_ids):
            self.calls.append("content")
            return {
                document_id: _content(
                    "owner-s100" if document_id == "document-s100" else "owner-other"
                )
                for document_id in document_ids
            }

    source = MixedOwnerSource()
    embedding = FakeEmbeddingClient()
    lexical = FakeLexicalStore()
    provider = ProductionHybridCandidateProvider(
        source=source,
        lexical_store=lexical,
        vector_repository=object(),
        vector_store=object(),
        embedding_client=embedding,
        embedding_alias="embedding-primary",
    )

    with pytest.raises(RetrievalPermissionError) as captured:
        provider.build_candidate_set(
            access_context=CONTEXT,
            query_text="권한 검색",
            requested_document_ids=["document-s100", "document-foreign"],
        )

    assert captured.value.status_code == 404
    assert "document-foreign" not in captured.value.detail
    assert source.calls == ["content"]
    assert embedding.calls == 0
    assert lexical.calls == 0


@pytest.mark.parametrize(
    "response",
    [None, {}, {"data": []}, {"data": [{"embedding": []}]}, {"data": [{"embedding": [True]}]}],
)
def test_candidate_provider_fails_closed_for_bad_embedding(response) -> None:
    with pytest.raises(HybridCandidateOrchestrationError) as exc_info:
        _provider(embedding=FakeEmbeddingClient(response)).build_candidate_set(
            access_context=CONTEXT,
            query_text="권한 검색",
            requested_document_ids=["document-s100"],
        )
    assert exc_info.value.error_code == "CX_QUERY_EMBEDDING_UNAVAILABLE"
    assert exc_info.value.retryable is True


def test_candidate_provider_preserves_classified_embedding_error() -> None:
    with pytest.raises(HybridCandidateOrchestrationError) as exc_info:
        _provider(embedding=RaisingEmbeddingClient()).build_candidate_set(
            access_context=CONTEXT,
            query_text="권한 검색",
            requested_document_ids=["document-s100"],
        )
    assert exc_info.value.error_code == "CX_EMBEDDING_THROTTLED"


def test_authorized_materializer_checks_scope_before_private_text() -> None:
    source = FakeSource()
    materializer = ProductionAuthorizedEvidenceMaterializer(source)
    refs = [{"content_object_id": "document-s100", "chunk_id": "chunk-s100"}]

    texts = materializer.load_authorized_texts(
        access_context=CONTEXT,
        chunk_refs=refs,
    )
    evidence = materializer.load_authorized_evidence(
        access_context=CONTEXT,
        chunk_refs=refs,
    )

    assert texts == evidence
    assert source.calls == ["content", "evidence", "content", "evidence"]


@pytest.mark.parametrize("refs", ["bad", [{"chunk_id": "chunk"}], [None]])
def test_authorized_materializer_rejects_invalid_scope(refs) -> None:
    with pytest.raises(HybridCandidateOrchestrationError) as exc_info:
        ProductionAuthorizedEvidenceMaterializer(FakeSource()).load_authorized_texts(
            access_context=CONTEXT,
            chunk_refs=refs,
        )
    assert exc_info.value.error_code == "CX_EVIDENCE_SCOPE_INVALID"


def test_evidence_scope_deduplicates_document_ids() -> None:
    assert _document_ids(
        [
            {"content_object_id": "document-s100", "chunk_id": "chunk-1"},
            {"content_object_id": "document-s100", "chunk_id": "chunk-2"},
        ]
    ) == ["document-s100"]


def test_runtime_builder_composes_permission_hardened_package() -> None:
    source = FakeSource()
    runtime = build_permission_hardened_hybrid_runtime(
        source=source,
        lexical_store=FakeLexicalStore(),
        vector_repository=object(),
        vector_store=object(),
        embedding_client=FakeEmbeddingClient(),
        embedding_alias="embedding-primary",
        reranker_alias="reranker-primary",
    )

    package = runtime.build_package(
        {
            "query_text": "권한 검색",
            "document_scope": {"document_ids": ["document-s100"]},
            "top_k": 1,
            "purpose": "grounded_answer",
        },
        access_context=CONTEXT,
    )

    assert package["status"] == "READY"
    assert package["permission_snapshot"]["visible_document_count"] == 1
    assert package["evidence_items"][0]["content_object_id"] == "document-s100"
    assert runtime.reranker_alias == "reranker-primary"
    assert package["score_summary"]["rerank_state"] == "NOT_APPLIED"
