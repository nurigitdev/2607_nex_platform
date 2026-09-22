from __future__ import annotations

"""Regression coverage for document-intelligence runtime orchestration."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

import nex_cx.main as cx_main
from nex_cx.access_context import CxAccessContext
from nex_cx.document_intelligence_orchestration import (
    DocumentIntelligenceError,
    register_document_intelligence_routes,
    run_document_intelligence,
    search_similar_document_summaries,
)
from nex_cx.document_intelligence_observability import (
    CX_DOCUMENT_INTELLIGENCE_FAILED_EVENT,
    CX_DOCUMENT_INTELLIGENCE_READY_EVENT,
    CX_DOCUMENT_INTELLIGENCE_SIMILARITY_EVENT,
)
from nex_cx.generation import GenerationFacadeError
from nex_cx.ingestion import (
    ContentIngestionStore,
    CxStorageConfig,
    build_upload_registration,
    run_text_extraction_job,
)
from nex_cx.private_content import build_private_payload_receipt
from nex_cx.summaries import build_and_store_document_summary
from nex_cx.summary_embeddings import SummaryEmbeddingError
from nex_cx.summary_similarity import SummarySimilarityError
from nex_runtime import (
    InMemoryOperationalEventStore,
    OperationalEventEmitter,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
)


REQUEST_ID = "request-0957"
TRACE_ID = "95700000000000000000000000000001"
TENANT_ID = "tenant-0957"
SUBJECT_ID = "user-0957"
EMBEDDING_ALIAS = "qwen3-embedding-4b"


class FakeGenerationClient:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.calls: list[dict[str, Any]] = []

    def create_generation(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        self.calls.append(
            {"payload": payload, "request_id": request_id, "trace_id": trace_id}
        )
        if self.failure is not None:
            raise self.failure
        return {
            "mo_generation_id": "mo-summary-0957",
            "alias": "general-llm-default",
            "model_revision": "Qwen3.5-4B",
            "deployment_id": "mock-generation-0957",
            "provider_type": "mock-generation",
            "output": {
                "type": "text",
                "text": "The approved deployment date is 2026-10-01.",
            },
            "finish_reason": "STOP",
            "usage": {"input_tokens": 20, "output_tokens": 9, "total_tokens": 29},
        }


class FakeEmbeddingClient:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.calls: list[dict[str, Any]] = []

    def create_embeddings(
        self,
        inputs: list[str],
        *,
        alias: str,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "inputs": inputs,
                "alias": alias,
                "request_id": request_id,
                "trace_id": trace_id,
            }
        )
        if self.failure is not None:
            raise self.failure
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


class MemoryBoundSummaryVectorStore:
    def __init__(self, parent: MemorySummaryVectorStore, binding: Any) -> None:
        self.parent = parent
        self.binding = binding

    def put_vector(
        self,
        *,
        access_context: CxAccessContext,
        key: Any,
        vector: list[float],
        expected_sha256: str,
    ) -> Any:
        values = tuple(float(value) for value in vector)
        self.parent.vectors[str(self.binding.document_summary_id)] = values
        return build_private_payload_receipt(
            key=key,
            storage_backend="memory-summary-pgvector-v1",
            storage_uri=f"cx-private://memory/{self.binding.summary_vector_id}",
            sha256=expected_sha256,
            size_bytes=len(values) * 4,
            vector_dimension=len(values),
        )

    def get_vector(
        self,
        *,
        access_context: CxAccessContext,
        key: Any,
        expected_sha256: str,
        expected_dimension: int,
    ) -> tuple[float, ...] | None:
        if self.parent.return_missing:
            return None
        return self.parent.vectors.get(str(self.binding.document_summary_id))

    def freshness(self, *, access_context: CxAccessContext) -> dict[str, Any]:
        return {
            "freshness_schema_version": "cx_summary_vector_freshness.v1",
            "state": "READY" if self.parent.fresh else "STALE",
            "usable": self.parent.fresh,
            "reasons": [] if self.parent.fresh else ["VECTOR_MISSING"],
            "document_summary_id": str(self.binding.document_summary_id),
            "summary_embedding_id": str(self.binding.summary_embedding_id),
            "profile_fingerprint": self.binding.profile_fingerprint,
        }


class MemorySummaryVectorStore:
    def __init__(self) -> None:
        self.vectors: dict[str, tuple[float, ...]] = {}
        self.fresh = True
        self.return_missing = False

    def bind_summary(self, binding: Any) -> MemoryBoundSummaryVectorStore:
        return MemoryBoundSummaryVectorStore(self, binding)


class FakeSimilarityStore:
    def __init__(self, *, failure: SummarySimilarityError | None = None) -> None:
        self.failure = failure
        self.calls: list[dict[str, Any]] = []

    def search(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self.failure is not None:
            raise self.failure
        return {
            "summary_similarity_result_schema_version": (
                "cx_summary_similarity_result.v1"
            ),
            "candidate_count": 1,
            "candidates": [
                {
                    "content_object_id": "00000000-0000-0000-0000-000000000002",
                    "similarity_score": 0.91,
                }
            ],
        }


def _config(tmp_path: Path) -> CxStorageConfig:
    return CxStorageConfig(
        data_root=tmp_path,
        source_root=tmp_path / "source",
        extracted_markdown_root=tmp_path / "markdown",
        extraction_temp_root=tmp_path / "temp",
        chunk_policy="chunk_1000_100",
        chunk_size=1000,
        chunk_overlap=100,
        bm25_tokenizer="mecab_ko",
        bm25_tokenizer_fallback="korean_mixed_v1",
    )


def _store_with_extraction(tmp_path: Path) -> tuple[ContentIngestionStore, str]:
    text = "# Deployment\n\nThe approved deployment date is 2026-10-01."
    store = ContentIngestionStore()
    config = _config(tmp_path)
    document = build_upload_registration(
        {
            "filename": "deployment.md",
            "content_type": "text/markdown",
            "content_text": text,
            "tenant_ref": {"type": "oa.tenant", "id": TENANT_ID},
            "owner_subject_ref": {"type": "oa.user", "id": SUBJECT_ID},
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
    return store, str(extraction["document_id"])


def _access_context(
    *, tenant_id: str = TENANT_ID, subject_id: str = SUBJECT_ID
) -> CxAccessContext:
    return CxAccessContext(
        caller_service_id="nex-ae-api",
        tenant_id=tenant_id,
        subject_id=subject_id,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        scopes=("service:call",),
    )


def _headers(
    *, tenant_id: str = TENANT_ID, subject_id: str = SUBJECT_ID
) -> dict[str, str]:
    token = issue_mock_service_token(service_id="nex-ae-api", audience="nex-cx")
    return {
        "Authorization": f"Bearer {token.access_token}",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
        "X-NEX-Tenant-ID": tenant_id,
        "X-NEX-Subject-ID": subject_id,
    }


def _run_ready_intelligence(
    tmp_path: Path,
) -> tuple[ContentIngestionStore, str, MemorySummaryVectorStore, dict[str, Any]]:
    store, document_id = _store_with_extraction(tmp_path)
    vectors = MemorySummaryVectorStore()
    result = run_document_intelligence(
        access_context=_access_context(),
        document_id=document_id,
        store=store,
        generation_client=FakeGenerationClient(),
        embedding_client=FakeEmbeddingClient(),
        embedding_alias=EMBEDDING_ALIAS,
        summary_vector_store=vectors,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    return store, document_id, vectors, result


def test_run_document_intelligence_publishes_safe_fresh_vector(tmp_path: Path) -> None:
    store, document_id = _store_with_extraction(tmp_path)
    generation = FakeGenerationClient()
    embedding = FakeEmbeddingClient()
    vectors = MemorySummaryVectorStore()

    result = run_document_intelligence(
        access_context=_access_context(),
        document_id=document_id,
        store=store,
        generation_client=generation,
        embedding_client=embedding,
        embedding_alias=EMBEDDING_ALIAS,
        summary_vector_store=vectors,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert result["status"] == "READY"
    assert result["summary"]["summary_char_count"] < 1000
    assert result["summary_embedding"]["model_revision"] == "Qwen3-Embedding-4B"
    assert result["summary_vector"]["freshness"]["usable"] is True
    assert result["raw_summary_included"] is False
    assert result["raw_vector_included"] is False
    assert "embedding" not in result["summary_vector"]
    assert generation.calls[0]["trace_id"] == TRACE_ID
    assert embedding.calls[0]["alias"] == EMBEDDING_ALIAS


def test_similarity_reuses_persisted_source_vector_and_excludes_self(
    tmp_path: Path,
) -> None:
    store, document_id, vectors, _ = _run_ready_intelligence(tmp_path)
    similarity = FakeSimilarityStore()

    result = search_similar_document_summaries(
        access_context=_access_context(),
        document_id=document_id,
        store=store,
        summary_vector_store=vectors,
        summary_similarity_store=similarity,
        limit=7,
        minimum_score=0.4,
    )

    call = similarity.calls[0]
    assert call["query_vector"] == (0.1, 0.2, 0.3)
    assert call["exclude_content_object_id"] == document_id
    assert call["limit"] == 7
    assert call["minimum_score"] == 0.4
    assert result["result"]["candidate_count"] == 1
    assert result["raw_vector_included"] is False


def test_similarity_rejects_stale_and_missing_vectors(tmp_path: Path) -> None:
    store, document_id, vectors, _ = _run_ready_intelligence(tmp_path)
    vectors.fresh = False
    with pytest.raises(DocumentIntelligenceError) as stale:
        search_similar_document_summaries(
            access_context=_access_context(),
            document_id=document_id,
            store=store,
            summary_vector_store=vectors,
            summary_similarity_store=FakeSimilarityStore(),
        )
    assert stale.value.error_code == "CX_DOCUMENT_INTELLIGENCE_VECTOR_STALE"

    vectors.fresh = True
    vectors.return_missing = True
    with pytest.raises(DocumentIntelligenceError) as missing:
        search_similar_document_summaries(
            access_context=_access_context(),
            document_id=document_id,
            store=store,
            summary_vector_store=vectors,
            summary_similarity_store=FakeSimilarityStore(),
        )
    assert missing.value.error_code == "CX_DOCUMENT_INTELLIGENCE_VECTOR_MISSING"


def test_run_translates_generation_and_embedding_failures(tmp_path: Path) -> None:
    store, document_id = _store_with_extraction(tmp_path)
    generation_failure = GenerationFacadeError(
        status_code=504,
        error_code="mo.provider_timeout",
        detail="Generation provider timed out.",
        retryable=True,
    )
    with pytest.raises(DocumentIntelligenceError) as generation_error:
        run_document_intelligence(
            access_context=_access_context(),
            document_id=document_id,
            store=store,
            generation_client=FakeGenerationClient(failure=generation_failure),
            embedding_client=FakeEmbeddingClient(),
            embedding_alias=EMBEDDING_ALIAS,
            summary_vector_store=MemorySummaryVectorStore(),
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    assert generation_error.value.status_code == 504
    assert generation_error.value.retryable is True

    embedding_failure = SummaryEmbeddingError(
        status_code=503,
        error_code="mo.embedding_unavailable",
        detail="Embedding provider unavailable.",
        retryable=True,
    )
    with pytest.raises(DocumentIntelligenceError) as embedding_error:
        run_document_intelligence(
            access_context=_access_context(),
            document_id=document_id,
            store=store,
            generation_client=FakeGenerationClient(),
            embedding_client=FakeEmbeddingClient(failure=embedding_failure),
            embedding_alias=EMBEDDING_ALIAS,
            summary_vector_store=MemorySummaryVectorStore(),
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    assert embedding_error.value.error_code == "mo.embedding_unavailable"


def test_similarity_translates_adapter_failure(tmp_path: Path) -> None:
    store, document_id, vectors, _ = _run_ready_intelligence(tmp_path)
    adapter_error = SummarySimilarityError(
        status_code=503,
        error_code="CX_SUMMARY_SIMILARITY_UNAVAILABLE",
        detail="Unavailable.",
        retryable=True,
    )

    with pytest.raises(DocumentIntelligenceError) as exc:
        search_similar_document_summaries(
            access_context=_access_context(),
            document_id=document_id,
            store=store,
            summary_vector_store=vectors,
            summary_similarity_store=FakeSimilarityStore(failure=adapter_error),
        )

    assert exc.value.error_code == "CX_SUMMARY_SIMILARITY_UNAVAILABLE"
    assert exc.value.retryable is True


def test_document_intelligence_routes_enforce_auth_owner_and_dependencies(
    tmp_path: Path,
) -> None:
    store, document_id = _store_with_extraction(tmp_path)
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    events = InMemoryOperationalEventStore()
    register_document_intelligence_routes(
        app,
        store=store,
        generation_client=FakeGenerationClient(),
        embedding_client=FakeEmbeddingClient(),
        embedding_alias=EMBEDDING_ALIAS,
        summary_vector_store=None,
        summary_similarity_store=None,
        event_emitter=OperationalEventEmitter(service_id="nex-cx", store=events),
    )
    client = TestClient(app)

    assert client.post(f"/api/v1/documents/{document_id}/intelligence/run").status_code == 401
    hidden = client.post(
        f"/api/v1/documents/{document_id}/intelligence/run",
        headers=_headers(subject_id="different-user"),
    )
    unavailable = client.post(
        f"/api/v1/documents/{document_id}/intelligence/run",
        headers=_headers(),
    )
    missing = client.post(
        "/api/v1/documents/00000000-0000-0000-0000-000000000099/intelligence/similar",
        headers=_headers(),
        json={},
    )

    assert hidden.status_code == 404
    assert hidden.json()["error_code"] == "CX_DOCUMENT_INTELLIGENCE_NOT_FOUND"
    assert unavailable.status_code == 503
    assert unavailable.json()["retryable"] is True
    assert missing.status_code == 404
    failures = events.list_events(event_type=CX_DOCUMENT_INTELLIGENCE_FAILED_EVENT)
    assert len(failures) == 1
    assert failures[0]["details"]["operation"] == "run"
    assert failures[0]["details"]["error_code"] == (
        "CX_DOCUMENT_INTELLIGENCE_RUNTIME_UNAVAILABLE"
    )


def test_document_intelligence_routes_run_and_search_with_defaults(
    tmp_path: Path,
) -> None:
    store, document_id = _store_with_extraction(tmp_path)
    vectors = MemorySummaryVectorStore()
    similarity = FakeSimilarityStore()
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    events = InMemoryOperationalEventStore()
    register_document_intelligence_routes(
        app,
        store=store,
        generation_client=FakeGenerationClient(),
        embedding_client=FakeEmbeddingClient(),
        embedding_alias=EMBEDDING_ALIAS,
        summary_vector_store=vectors,
        summary_similarity_store=similarity,
        event_emitter=OperationalEventEmitter(service_id="nex-cx", store=events),
    )
    client = TestClient(app)

    run_response = client.post(
        f"/api/v1/documents/{document_id}/intelligence/run",
        headers=_headers(),
    )
    search_response = client.post(
        f"/api/v1/documents/{document_id}/intelligence/similar",
        headers=_headers(),
        json={},
    )

    assert run_response.status_code == 200
    assert search_response.status_code == 200
    assert run_response.json()["observability"]["ok"] is True
    assert search_response.json()["observability"]["ok"] is True
    assert similarity.calls[0]["limit"] == 10
    assert similarity.calls[0]["minimum_score"] == 0.0
    assert len(
        events.list_events(event_type=CX_DOCUMENT_INTELLIGENCE_READY_EVENT)
    ) == 1
    assert len(
        events.list_events(event_type=CX_DOCUMENT_INTELLIGENCE_SIMILARITY_EVENT)
    ) == 1


def test_run_rejects_unfresh_publication(tmp_path: Path) -> None:
    store, document_id = _store_with_extraction(tmp_path)
    vectors = MemorySummaryVectorStore()
    vectors.fresh = False

    with pytest.raises(DocumentIntelligenceError) as exc:
        run_document_intelligence(
            access_context=_access_context(),
            document_id=document_id,
            store=store,
            generation_client=FakeGenerationClient(),
            embedding_client=FakeEmbeddingClient(),
            embedding_alias=EMBEDDING_ALIAS,
            summary_vector_store=vectors,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert exc.value.error_code == "CX_DOCUMENT_INTELLIGENCE_VECTOR_STALE"


def test_run_rejects_missing_generated_vector(tmp_path: Path) -> None:
    store, document_id = _store_with_extraction(tmp_path)
    store.get_summary_embedding_vector = lambda _summary_id: None  # type: ignore[method-assign]

    with pytest.raises(DocumentIntelligenceError) as exc:
        run_document_intelligence(
            access_context=_access_context(),
            document_id=document_id,
            store=store,
            generation_client=FakeGenerationClient(),
            embedding_client=FakeEmbeddingClient(),
            embedding_alias=EMBEDDING_ALIAS,
            summary_vector_store=MemorySummaryVectorStore(),
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert exc.value.error_code == "CX_DOCUMENT_INTELLIGENCE_VECTOR_MISSING"


def test_current_lineage_requires_content_summary_and_embedding(tmp_path: Path) -> None:
    with pytest.raises(DocumentIntelligenceError) as content_missing:
        search_similar_document_summaries(
            access_context=_access_context(),
            document_id="00000000-0000-0000-0000-000000000099",
            store=ContentIngestionStore(),
            summary_vector_store=MemorySummaryVectorStore(),
            summary_similarity_store=FakeSimilarityStore(),
        )
    assert content_missing.value.status_code == 404

    store, document_id = _store_with_extraction(tmp_path)
    with pytest.raises(DocumentIntelligenceError) as summary_missing:
        search_similar_document_summaries(
            access_context=_access_context(),
            document_id=document_id,
            store=store,
            summary_vector_store=MemorySummaryVectorStore(),
            summary_similarity_store=FakeSimilarityStore(),
        )
    assert summary_missing.value.error_code == "CX_DOCUMENT_INTELLIGENCE_SUMMARY_MISSING"

    build_and_store_document_summary(
        document_id,
        store=store,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    with pytest.raises(DocumentIntelligenceError) as embedding_missing:
        search_similar_document_summaries(
            access_context=_access_context(),
            document_id=document_id,
            store=store,
            summary_vector_store=MemorySummaryVectorStore(),
            summary_similarity_store=FakeSimilarityStore(),
        )
    assert embedding_missing.value.error_code == (
        "CX_DOCUMENT_INTELLIGENCE_EMBEDDING_MISSING"
    )


def test_similarity_route_covers_auth_runtime_and_adapter_errors(
    tmp_path: Path,
) -> None:
    store, document_id, vectors, _ = _run_ready_intelligence(tmp_path)
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    register_document_intelligence_routes(
        app,
        store=store,
        generation_client=FakeGenerationClient(),
        embedding_client=FakeEmbeddingClient(),
        embedding_alias=EMBEDDING_ALIAS,
        summary_vector_store=vectors,
        summary_similarity_store=None,
    )
    client = TestClient(app)

    unauthorized = client.post(
        f"/api/v1/documents/{document_id}/intelligence/similar",
        json={},
    )
    unavailable = client.post(
        f"/api/v1/documents/{document_id}/intelligence/similar",
        headers=_headers(),
        json={},
    )

    assert unauthorized.status_code == 401
    assert unavailable.status_code == 503
    assert unavailable.json()["error_code"] == (
        "CX_DOCUMENT_INTELLIGENCE_RUNTIME_UNAVAILABLE"
    )

    failing_app = build_service_app(SERVICE_SPECS["nex-cx"])
    register_document_intelligence_routes(
        failing_app,
        store=store,
        generation_client=FakeGenerationClient(),
        embedding_client=FakeEmbeddingClient(),
        embedding_alias=EMBEDDING_ALIAS,
        summary_vector_store=vectors,
        summary_similarity_store=FakeSimilarityStore(
            failure=SummarySimilarityError(
                status_code=503,
                error_code="CX_SUMMARY_SIMILARITY_UNAVAILABLE",
                detail="Unavailable.",
                retryable=True,
            )
        ),
    )
    failed = TestClient(failing_app).post(
        f"/api/v1/documents/{document_id}/intelligence/similar",
        headers=_headers(),
        json={},
    )

    assert failed.status_code == 503
    assert failed.json()["error_code"] == "CX_SUMMARY_SIMILARITY_UNAVAILABLE"


def test_main_document_intelligence_dependencies_are_postgres_only(
    monkeypatch,
) -> None:
    assert cx_main.build_cx_document_intelligence_dependencies(
        SimpleNamespace(mode="memory", api_session_factory=None)
    ) == (None, None, None)

    private_store = object()
    vector_store = object()
    similarity_store = object()
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(cx_main, "build_private_text_store", lambda: private_store)
    monkeypatch.setattr(
        cx_main,
        "build_summary_pgvector_store",
        lambda **kwargs: calls.append(("vector", kwargs)) or vector_store,
    )
    monkeypatch.setattr(
        cx_main,
        "build_summary_similarity_store",
        lambda **kwargs: calls.append(("similarity", kwargs)) or similarity_store,
    )

    dependencies = cx_main.build_cx_document_intelligence_dependencies(
        SimpleNamespace(
            mode="postgres",
            api_session_factory=object(),
            database_env="NEX_CX_TEST_DATABASE_URL",
        )
    )

    assert dependencies == (private_store, vector_store, similarity_store)
    assert calls == [
        (
            "vector",
            {"database_env": "NEX_CX_TEST_DATABASE_URL", "workload": "worker"},
        ),
        (
            "similarity",
            {"database_env": "NEX_CX_TEST_DATABASE_URL", "workload": "api"},
        ),
    ]
