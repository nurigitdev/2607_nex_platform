from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from nex_cx.access_context import CxAccessContext
from nex_cx.ingestion import ContentIngestionStore, CxStorageConfig
from nex_cx.main import build_cx_mvp_runtime_composition
from nex_cx.mvp_runtime import (
    CxMvpRuntimeError,
    PostgresHybridRetrievalSource,
    _chunk_references,
    _identifiers,
    build_cx_mvp_runtime,
)


TENANT_ID = "tenant-s100"
OWNER_ID = "owner-s100"
DOCUMENT_ID = "10000000-0000-0000-0000-000000000001"
CHUNK_ID = "20000000-0000-0000-0000-000000000001"
CHUNK_SET_ID = "30000000-0000-0000-0000-000000000001"
VECTOR_INDEX_OLD = "40000000-0000-0000-0000-000000000001"
VECTOR_INDEX_NEW = "40000000-0000-0000-0000-000000000002"
CHUNK_TEXT = "S100 owner-private retrieval evidence"
CHUNK_SHA256 = hashlib.sha256(CHUNK_TEXT.encode("utf-8")).hexdigest()
CONTEXT = CxAccessContext(
    caller_service_id="nex-ae-api",
    tenant_id=TENANT_ID,
    subject_id=OWNER_ID,
    request_id="request-s100",
    trace_id="trace-s100",
    scopes=("service.invoke",),
)


def _content() -> dict[str, Any]:
    return {
        "content_object_id": DOCUMENT_ID,
        "tenant_ref": {"type": "oa.tenant", "id": TENANT_ID},
        "owner_subject_ref": {"type": "oa.user", "id": OWNER_ID},
        "lifecycle_status": "ACTIVE",
    }


def _manifest(vector_index_id: str) -> dict[str, Any]:
    return {
        "vector_index_id": vector_index_id,
        "content_object_id": DOCUMENT_ID,
        "status": "READY",
        "source_snapshot": {
            "chunk_set_id": CHUNK_SET_ID,
            "chunk_policy_id": "chunk_1000_100",
            "source_markdown_sha256": "a" * 64,
            "chunk_count": 1,
            "chunk_refs": [
                {"chunk_id": CHUNK_ID, "ordinal": 0, "text_sha256": CHUNK_SHA256}
            ],
            "source_fingerprint": "b" * 64,
        },
        "embedding_profile": {
            "provider_alias": "mock-embedding-default",
            "model_profile_id": "Qwen3-Embedding-4B",
            "model_revision": "main",
            "deployment_id": "dgx-spark",
            "vector_dimension": 2,
            "profile_fingerprint": "c" * 64,
        },
    }


@dataclass
class FakeContentRepository:
    content: dict[str, Any] | None = field(default_factory=_content)
    chunk_sets: dict[str, dict[str, Any]] = field(
        default_factory=lambda: {
            CHUNK_SET_ID: {
                "chunk_set_id": CHUNK_SET_ID,
                "chunk_policy_id": "chunk_1000_100",
                "source_markdown_sha256": "a" * 64,
                "chunks": [
                    {
                        "chunk_id": CHUNK_ID,
                        "ordinal": 0,
                        "text_sha256": CHUNK_SHA256,
                    }
                ],
            }
        }
    )

    def get_content_object(self, content_object_id: str):
        return self.content if content_object_id == DOCUMENT_ID else None

    def get_chunk_set(self, chunk_set_id: str):
        return self.chunk_sets.get(chunk_set_id)


@dataclass
class FakeVectorRepository:
    manifests: dict[str, dict[str, Any]] = field(
        default_factory=lambda: {
            VECTOR_INDEX_OLD: _manifest(VECTOR_INDEX_OLD),
            VECTOR_INDEX_NEW: _manifest(VECTOR_INDEX_NEW),
        }
    )

    def get(self, vector_index_id: str, **kwargs):
        return self.manifests.get(vector_index_id)


@dataclass
class FakePrivateTextStore:
    text_value: str | None = CHUNK_TEXT
    calls: list[Any] = field(default_factory=list)

    def get_text(self, **kwargs):
        self.calls.append(kwargs)
        return self.text_value

    def put_text(self, **kwargs):
        self.calls.append(kwargs)
        return object()

    def delete_text(self, **kwargs):
        return False


class FakeEmbeddingClient:
    def create_embeddings(self, inputs, **kwargs):
        return {"data": [{"embedding": [0.1, 0.2]} for _ in inputs]}


class FailingContentRepository:
    def get_content_object(self, content_object_id: str):
        raise RuntimeError("database URL and private details must not escape")

    def get_chunk_set(self, chunk_set_id: str):
        raise RuntimeError("database URL and private details must not escape")


class FailingPrivateTextStore(FakePrivateTextStore):
    def get_text(self, **kwargs):
        raise RuntimeError("private path must not escape")


def _session_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE cx_vector_indexes (
                    vector_index_id TEXT PRIMARY KEY,
                    content_object_id TEXT NOT NULL,
                    tenant_ref_type TEXT NOT NULL,
                    tenant_ref_id TEXT NOT NULL,
                    owner_subject_ref_type TEXT NOT NULL,
                    owner_subject_ref_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    ready_at TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE cx_content_objects (
                    content_object_id TEXT PRIMARY KEY,
                    tenant_ref_type TEXT NOT NULL,
                    tenant_ref_id TEXT NOT NULL,
                    owner_subject_ref_type TEXT NOT NULL,
                    owner_subject_ref_id TEXT NOT NULL,
                    lifecycle_status TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE cx_chunk_sets (
                    chunk_set_id TEXT PRIMARY KEY,
                    content_object_id TEXT NOT NULL,
                    chunk_policy_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE cx_chunks (
                    chunk_id TEXT PRIMARY KEY,
                    chunk_set_id TEXT NOT NULL,
                    content_object_id TEXT NOT NULL,
                    start_offset INTEGER NOT NULL,
                    end_offset INTEGER NOT NULL,
                    text_sha256 TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO cx_content_objects VALUES (
                    :document_id, 'oa.tenant', :tenant_id,
                    'oa.user', :owner_id, 'ACTIVE'
                )
                """
            ),
            {
                "document_id": DOCUMENT_ID,
                "tenant_id": TENANT_ID,
                "owner_id": OWNER_ID,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO cx_chunk_sets VALUES (
                    :chunk_set_id, :document_id, 'chunk_1000_100',
                    '2026-09-27T01:00:00+00:00'
                )
                """
            ),
            {"chunk_set_id": CHUNK_SET_ID, "document_id": DOCUMENT_ID},
        )
        connection.execute(
            text(
                """
                INSERT INTO cx_chunks VALUES (
                    :chunk_id, :chunk_set_id, :document_id, 0, 37, :text_sha256
                )
                """
            ),
            {
                "chunk_id": CHUNK_ID,
                "chunk_set_id": CHUNK_SET_ID,
                "document_id": DOCUMENT_ID,
                "text_sha256": CHUNK_SHA256,
            },
        )
        for vector_index_id, ready_at in (
            (VECTOR_INDEX_OLD, "2026-09-27T01:00:00+00:00"),
            (VECTOR_INDEX_NEW, "2026-09-27T02:00:00+00:00"),
        ):
            connection.execute(
                text(
                    """
                    INSERT INTO cx_vector_indexes VALUES (
                        :vector_index_id, :document_id, 'oa.tenant', :tenant_id,
                        'oa.user', :owner_id, 'READY', :ready_at, :ready_at
                    )
                    """
                ),
                {
                    "vector_index_id": vector_index_id,
                    "document_id": DOCUMENT_ID,
                    "tenant_id": TENANT_ID,
                    "owner_id": OWNER_ID,
                    "ready_at": ready_at,
                },
            )
    return sessionmaker(bind=engine), engine


def _source(*, private_text: str | None = CHUNK_TEXT):
    sessions, engine = _session_factory()
    private_store = FakePrivateTextStore(private_text)
    return (
        PostgresHybridRetrievalSource(
            session_factory=sessions,
            content_repository=FakeContentRepository(),
            vector_repository=FakeVectorRepository(),
            private_text_store=private_store,
        ),
        private_store,
        engine,
    )


def test_postgres_source_loads_content_and_latest_ready_vector() -> None:
    source, _private, engine = _source()
    try:
        content = source.load_content_objects([DOCUMENT_ID, DOCUMENT_ID, "missing"])
        targets = source.load_vector_targets(
            access_context=CONTEXT,
            document_ids=[DOCUMENT_ID],
        )
    finally:
        engine.dispose()

    assert list(content) == [DOCUMENT_ID]
    assert targets[DOCUMENT_ID]["vector_index_id"] == VECTOR_INDEX_NEW
    assert targets[DOCUMENT_ID]["permission_decision"]["visible"] is True
    assert targets[DOCUMENT_ID]["source_snapshot"]["chunk_set_id"] == CHUNK_SET_ID


def test_postgres_source_uses_current_chunk_set_for_freshness() -> None:
    sessions, engine = _session_factory()
    current_chunk_set_id = "30000000-0000-0000-0000-000000000002"
    current_chunk_id = "20000000-0000-0000-0000-000000000002"
    current_text_sha256 = "d" * 64
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO cx_chunk_sets VALUES (
                    :chunk_set_id, :document_id, 'chunk_1000_100',
                    '2026-09-27T03:00:00+00:00'
                )
                """
            ),
            {"chunk_set_id": current_chunk_set_id, "document_id": DOCUMENT_ID},
        )
    repository = FakeContentRepository(
        chunk_sets={
            current_chunk_set_id: {
                "chunk_set_id": current_chunk_set_id,
                "chunk_policy_id": "chunk_1000_100",
                "source_markdown_sha256": "e" * 64,
                "chunks": [
                    {
                        "chunk_id": current_chunk_id,
                        "ordinal": 0,
                        "text_sha256": current_text_sha256,
                    }
                ],
            }
        }
    )
    source = PostgresHybridRetrievalSource(
        session_factory=sessions,
        content_repository=repository,
        vector_repository=FakeVectorRepository(),
        private_text_store=FakePrivateTextStore(),
    )
    try:
        target = source.load_vector_targets(
            access_context=CONTEXT,
            document_ids=[DOCUMENT_ID],
        )[DOCUMENT_ID]
    finally:
        engine.dispose()

    assert target["source_snapshot"]["chunk_set_id"] == current_chunk_set_id
    assert target["source_snapshot"]["chunk_set_id"] != (
        _manifest(VECTOR_INDEX_NEW)["source_snapshot"]["chunk_set_id"]
    )


def test_postgres_source_returns_empty_results_for_empty_scope() -> None:
    source, _private, engine = _source()
    try:
        assert source.load_content_objects([]) == {}
        assert source.load_vector_targets(
            access_context=CONTEXT,
            document_ids=[],
        ) == {}
        assert source.load_private_evidence(
            access_context=CONTEXT,
            chunk_refs=[],
        ) == []
    finally:
        engine.dispose()


def test_postgres_source_redacts_content_repository_failure() -> None:
    sessions, engine = _session_factory()
    source = PostgresHybridRetrievalSource(
        session_factory=sessions,
        content_repository=FailingContentRepository(),
        vector_repository=FakeVectorRepository(),
        private_text_store=FakePrivateTextStore(),
    )
    try:
        with pytest.raises(CxMvpRuntimeError) as exc_info:
            source.load_content_objects([DOCUMENT_ID])
        with pytest.raises(CxMvpRuntimeError) as vector_exc:
            source.load_vector_targets(
                access_context=CONTEXT,
                document_ids=[DOCUMENT_ID],
            )
    finally:
        engine.dispose()

    assert exc_info.value.error_code == "cx.mvp_runtime.dependency_unavailable"
    assert exc_info.value.detail == "CX MVP content metadata is unavailable."
    assert vector_exc.value.detail == "CX MVP content metadata is unavailable."


def test_postgres_source_redacts_vector_database_failure() -> None:
    sessions, engine = _session_factory()
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE cx_vector_indexes"))
    source = PostgresHybridRetrievalSource(
        session_factory=sessions,
        content_repository=FakeContentRepository(),
        vector_repository=FakeVectorRepository(),
        private_text_store=FakePrivateTextStore(),
    )
    try:
        with pytest.raises(CxMvpRuntimeError) as exc_info:
            source.load_vector_targets(
                access_context=CONTEXT,
                document_ids=[DOCUMENT_ID],
            )
    finally:
        engine.dispose()

    assert exc_info.value.detail == "CX MVP vector metadata is unavailable."
    assert "cx_vector_indexes" not in exc_info.value.detail


def test_postgres_source_skips_permission_race_and_nonready_manifest() -> None:
    sessions, engine = _session_factory()
    denied_source = PostgresHybridRetrievalSource(
        session_factory=sessions,
        content_repository=FakeContentRepository(
            {
                **_content(),
                "owner_subject_ref": {"type": "oa.user", "id": "other-owner"},
            }
        ),
        vector_repository=FakeVectorRepository(),
        private_text_store=FakePrivateTextStore(),
    )
    unavailable_source = PostgresHybridRetrievalSource(
        session_factory=sessions,
        content_repository=FakeContentRepository(),
        vector_repository=FakeVectorRepository(
            {VECTOR_INDEX_NEW: {**_manifest(VECTOR_INDEX_NEW), "status": "BUILDING"}}
        ),
        private_text_store=FakePrivateTextStore(),
    )
    missing_source = PostgresHybridRetrievalSource(
        session_factory=sessions,
        content_repository=FakeContentRepository(),
        vector_repository=FakeVectorRepository({}),
        private_text_store=FakePrivateTextStore(),
    )
    missing_chunk_set_source = PostgresHybridRetrievalSource(
        session_factory=sessions,
        content_repository=FakeContentRepository(chunk_sets={}),
        vector_repository=FakeVectorRepository(),
        private_text_store=FakePrivateTextStore(),
    )
    try:
        assert denied_source.load_vector_targets(
            access_context=CONTEXT,
            document_ids=[DOCUMENT_ID],
        ) == {}
        assert unavailable_source.load_vector_targets(
            access_context=CONTEXT,
            document_ids=[DOCUMENT_ID],
        ) == {}
        assert missing_source.load_vector_targets(
            access_context=CONTEXT,
            document_ids=[DOCUMENT_ID],
        ) == {}
        assert missing_chunk_set_source.load_vector_targets(
            access_context=CONTEXT,
            document_ids=[DOCUMENT_ID],
        ) == {}
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM cx_chunk_sets"))
        no_current_chunk_set_source = PostgresHybridRetrievalSource(
            session_factory=sessions,
            content_repository=FakeContentRepository(),
            vector_repository=FakeVectorRepository(),
            private_text_store=FakePrivateTextStore(),
        )
        assert no_current_chunk_set_source.load_vector_targets(
            access_context=CONTEXT,
            document_ids=[DOCUMENT_ID],
        ) == {}
    finally:
        engine.dispose()


def test_postgres_source_materializes_owner_private_evidence() -> None:
    source, private_store, engine = _source()
    try:
        records = source.load_private_evidence(
            access_context=CONTEXT,
            chunk_refs=[
                {"content_object_id": DOCUMENT_ID, "chunk_id": CHUNK_ID}
            ],
        )
    finally:
        engine.dispose()

    assert records == [
        {
            "content_object_id": DOCUMENT_ID,
            "chunk_id": CHUNK_ID,
            "chunk_policy_id": "chunk_1000_100",
            "chunk_text": CHUNK_TEXT,
            "text_sha256": CHUNK_SHA256,
            "start_offset": 0,
            "end_offset": 37,
            "matched_terms": [],
        }
    ]
    assert private_store.calls[0]["key"].subject_id == OWNER_ID


def test_postgres_source_fails_closed_for_missing_private_payload() -> None:
    source, _private, engine = _source(private_text=None)
    try:
        with pytest.raises(CxMvpRuntimeError) as exc_info:
            source.load_private_evidence(
                access_context=CONTEXT,
                chunk_refs=[
                    {"content_object_id": DOCUMENT_ID, "chunk_id": CHUNK_ID}
                ],
            )
    finally:
        engine.dispose()

    assert exc_info.value.error_code == "cx.mvp_runtime.private_text_unavailable"
    assert exc_info.value.retryable is True
    assert str(exc_info.value) == "Private retrieval evidence is unavailable."


def test_postgres_source_redacts_private_store_failure() -> None:
    sessions, engine = _session_factory()
    source = PostgresHybridRetrievalSource(
        session_factory=sessions,
        content_repository=FakeContentRepository(),
        vector_repository=FakeVectorRepository(),
        private_text_store=FailingPrivateTextStore(),
    )
    try:
        with pytest.raises(CxMvpRuntimeError) as exc_info:
            source.load_private_evidence(
                access_context=CONTEXT,
                chunk_refs=[
                    {"content_object_id": DOCUMENT_ID, "chunk_id": CHUNK_ID}
                ],
            )
    finally:
        engine.dispose()

    assert exc_info.value.detail == "CX MVP private evidence is unavailable."
    assert "private path" not in exc_info.value.detail


def test_postgres_source_hides_foreign_owner_vector_and_evidence() -> None:
    source, _private, engine = _source()
    foreign = CxAccessContext(
        caller_service_id="nex-ae-api",
        tenant_id=TENANT_ID,
        subject_id="other-owner",
        request_id="request-other",
        trace_id="trace-other",
        scopes=("service.invoke",),
    )
    try:
        assert source.load_vector_targets(
            access_context=foreign,
            document_ids=[DOCUMENT_ID],
        ) == {}
        with pytest.raises(CxMvpRuntimeError) as exc_info:
            source.load_private_evidence(
                access_context=foreign,
                chunk_refs=[
                    {"content_object_id": DOCUMENT_ID, "chunk_id": CHUNK_ID}
                ],
            )
    finally:
        engine.dispose()

    assert exc_info.value.error_code == "cx.mvp_runtime.evidence_not_found"


@pytest.mark.parametrize(
    "value",
    ["bad", [""], [None]],
)
def test_runtime_identifiers_reject_invalid_values(value) -> None:
    with pytest.raises(CxMvpRuntimeError):
        _identifiers(value, field="document_ids")


@pytest.mark.parametrize(
    "value",
    ["bad", [None], [{}], [{"content_object_id": "doc", "chunk_id": ""}]],
)
def test_runtime_chunk_refs_reject_invalid_values(value) -> None:
    with pytest.raises(CxMvpRuntimeError):
        _chunk_references(value)


def test_runtime_chunk_refs_reject_duplicates() -> None:
    ref = {"content_object_id": DOCUMENT_ID, "chunk_id": CHUNK_ID}
    with pytest.raises(CxMvpRuntimeError):
        _chunk_references([ref, ref])


def test_runtime_composes_retrieval_and_durable_ingestion(tmp_path: Path) -> None:
    sessions, engine = _session_factory()
    repository = FakeContentRepository()
    store = ContentIngestionStore(content_repository=repository)
    private_store = FakePrivateTextStore()
    vector_repository = FakeVectorRepository()
    try:
        composition = build_cx_mvp_runtime(
            session_factory=sessions,
            store=store,
            storage_config=_storage_config(tmp_path),
            content_repository=repository,
            vector_repository=vector_repository,
            retrieval_vector_store=object(),
            ingestion_vector_store=object(),
            private_text_store=private_store,
            embedding_client=FakeEmbeddingClient(),
            embedding_alias="embedding-primary",
            rerank_client=None,
            reranker_alias="reranker-primary",
        )
    finally:
        engine.dispose()

    assert composition.hybrid_retrieval_runtime.candidate_provider.source is (
        composition.source
    )
    assert composition.ingestion_step_handlers["embedding_index"] is (
        composition.ingestion_vector_indexer
    )
    assert composition.to_safe_summary() == {
        "runtime": "cx_mvp_postgres",
        "retrieval": "permission_hardened_hybrid",
        "vector_publish": "fresh_owner_scoped_pgvector",
        "private_text": "owner_scoped_external_payload",
        "ingestion_step_count": 6,
    }


def test_main_composition_builder_is_postgres_only(monkeypatch, tmp_path: Path) -> None:
    kwargs = {
        "storage_config": _storage_config(tmp_path),
        "content_repository": FakeContentRepository(),
        "vector_repository": FakeVectorRepository(),
        "retrieval_vector_store": object(),
        "private_text_store": FakePrivateTextStore(),
        "embedding_client": FakeEmbeddingClient(),
        "embedding_alias": "embedding-primary",
        "rerank_client": None,
        "reranker_alias": "reranker-primary",
    }
    assert build_cx_mvp_runtime_composition(
        SimpleNamespace(mode="memory", api_session_factory=None),
        **kwargs,
    ) is None

    sessions, engine = _session_factory()
    worker_store = object()
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        "nex_cx.main.build_pgvector_cx_vector_store",
        lambda **values: captured.update(values) or worker_store,
    )
    try:
        composition = build_cx_mvp_runtime_composition(
            SimpleNamespace(
                mode="postgres",
                api_session_factory=sessions,
                database_env="NEX_CX_TEST_DATABASE_URL",
            ),
            **kwargs,
        )
    finally:
        engine.dispose()

    assert composition is not None
    assert composition.ingestion_vector_indexer.vector_store is worker_store
    assert captured == {
        "database_env": "NEX_CX_TEST_DATABASE_URL",
        "workload": "worker",
    }


def _storage_config(root: Path) -> CxStorageConfig:
    return CxStorageConfig(
        data_root=root,
        source_root=root / "source",
        extracted_markdown_root=root / "markdown",
        extraction_temp_root=root / "temp",
        chunk_policy="chunk_1000_100",
        chunk_size=1000,
        chunk_overlap=100,
        bm25_tokenizer="mecab_ko",
        bm25_tokenizer_fallback="korean_mixed_v1",
    )
