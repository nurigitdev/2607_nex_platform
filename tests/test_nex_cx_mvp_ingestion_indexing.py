from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
from pathlib import Path

import pytest

from nex_cx.ingestion_coordinator import build_default_ingestion_step_handlers
from nex_cx.mvp_ingestion_indexing import (
    MvpIngestionIndexingError,
    MvpIngestionVectorIndexer,
    _embedding_vectors,
)
from nex_cx.private_content import build_private_payload_receipt
from nex_cx.private_text_store import FileSystemCxPrivateTextStore
from nex_cx.vector_index_repository import InMemoryVectorIndexRepository


TEXTS = ["첫 번째 청크", "두 번째 청크"]
CHUNKS = [
    {
        "chunk_id": f"chunk-{index}",
        "ordinal": index,
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }
    for index, text in enumerate(TEXTS)
]


class FakeChunkStore:
    def __init__(self):
        self.texts = {chunk["chunk_id"]: text for chunk, text in zip(CHUNKS, TEXTS)}
        self.public = {"document_id": "document-s100", "chunks": CHUNKS}
        self.persisted = {
            "content_object_id": "document-s100",
            "chunk_set_id": "chunk-set-s100",
            "chunk_policy_id": "chunk_1000_100",
            "source_markdown_sha256": "a" * 64,
            "chunks": CHUNKS,
        }

    def get_chunk_set(self, document_id):
        return self.public if document_id == "document-s100" else None

    def get_persisted_chunk_set(self, document_id):
        return self.persisted if document_id == "document-s100" else None

    def get_chunk_text(self, chunk_id):
        return self.texts.get(chunk_id)


class FakeEmbeddingClient:
    def __init__(self, response=None):
        self.response = response or {
            "alias": "embedding-primary",
            "model_revision": "Qwen3-Embedding-4B",
            "deployment_id": "dgx-embedding",
            "data": [
                {"embedding": [1.0, 0.0]},
                {"embedding": [0.0, 1.0]},
            ],
        }
        self.calls = 0

    def create_embeddings(self, inputs, **kwargs):
        self.calls += 1
        assert inputs == TEXTS
        return self.response


class BoundVectorStore:
    def __init__(self):
        self.rows = {}

    def put_vector(self, *, access_context, key, vector, expected_sha256):
        self.rows[key.content_id] = tuple(vector)
        return build_private_payload_receipt(
            key=key,
            storage_backend="postgresql-pgvector-v1",
            storage_uri=f"cx-private://pgvector/{key.content_id}",
            sha256=expected_sha256,
            size_bytes=8,
            vector_dimension=len(vector),
        )

    def delete_vector(self, *, access_context, key):
        return self.rows.pop(key.content_id, None) is not None


class FakeVectorStore:
    def __init__(self):
        self.bound = BoundVectorStore()

    def bind_index(self, manifest):
        return self.bound


class ConflictRepository:
    def get(self, *args, **kwargs):
        return {"status": "BUILDING"}


def _run(**overrides):
    value = {
        "document_id": "document-s100",
        "tenant_ref": {"type": "oa.tenant", "id": "tenant-s100"},
        "owner_subject_ref": {"type": "oa.user", "id": "owner-s100"},
        "request_id": "request-s100",
        "trace_id": "trace-s100",
        "updated_at": "2026-09-27T01:00:00Z",
    }
    value.update(overrides)
    return value


def _indexer(tmp_path: Path, *, store=None, client=None, repository=None):
    return MvpIngestionVectorIndexer(
        store=store or FakeChunkStore(),
        private_text_store=FileSystemCxPrivateTextStore(tmp_path / "private"),
        embedding_client=client or FakeEmbeddingClient(),
        embedding_alias="embedding-primary",
        vector_repository=repository or InMemoryVectorIndexRepository(),
        vector_store=FakeVectorStore(),
    )


def test_mvp_ingestion_persists_private_chunks_and_publishes_ready_index(tmp_path) -> None:
    indexer = _indexer(tmp_path)
    result = indexer(_run())

    assert result.output_ref.startswith("cx.vector_index:")
    assert result.skipped is False
    assert len(list((tmp_path / "private").rglob("*.utf8"))) == 2
    assert len(indexer.vector_store.bound.rows) == 2


def test_mvp_ingestion_hydrates_runtime_before_chunk_reads(tmp_path) -> None:
    hydrated = []
    indexer = replace(
        _indexer(tmp_path),
        runtime_hydrator=lambda run: hydrated.append(run["document_id"]) or {},
    )

    indexer(_run())

    assert hydrated == ["document-s100"]


def test_mvp_ingestion_reuses_ready_index_idempotently(tmp_path) -> None:
    client = FakeEmbeddingClient()
    repository = InMemoryVectorIndexRepository()
    indexer = _indexer(tmp_path, client=client, repository=repository)

    first = indexer(_run())
    replay = indexer(_run())

    assert replay.output_ref == first.output_ref
    assert replay.skipped is True
    assert client.calls == 2


def test_mvp_ingestion_handler_overrides_legacy_embedding_step(tmp_path) -> None:
    indexer = _indexer(tmp_path)
    handlers = build_default_ingestion_step_handlers(
        store=indexer.store,
        storage_config=object(),
        mo_client=indexer.embedding_client,
        embedding_alias="legacy",
        mvp_embedding_handler=indexer,
    )
    assert handlers["embedding_index"] is indexer


@pytest.mark.parametrize(
    "response",
    [
        None,
        {},
        {"data": []},
        {"data": [{"embedding": [1.0]}]},
        {"data": [{"embedding": []}, {"embedding": [1.0]}]},
        {"data": [{"embedding": [True]}, {"embedding": [1.0]}]},
        {"data": [{"embedding": [1.0]}, {"embedding": [1.0, 2.0]}]},
    ],
)
def test_embedding_vectors_fail_closed(response) -> None:
    with pytest.raises(MvpIngestionIndexingError) as exc_info:
        _embedding_vectors(response, expected_count=2)
    assert exc_info.value.error_code == "cx.mvp_ingestion.embedding_response_invalid"


def test_mvp_ingestion_rejects_missing_or_corrupt_chunk_text(tmp_path) -> None:
    missing = FakeChunkStore()
    missing.texts.pop("chunk-0")
    with pytest.raises(MvpIngestionIndexingError) as missing_error:
        _indexer(tmp_path, store=missing)(_run())
    assert missing_error.value.retryable is True

    corrupt = FakeChunkStore()
    corrupt.texts["chunk-0"] = "tampered"
    with pytest.raises(MvpIngestionIndexingError) as corrupt_error:
        _indexer(tmp_path / "other", store=corrupt)(_run())
    assert corrupt_error.value.error_code == "cx.mvp_ingestion.chunk_text_integrity_failed"


def test_mvp_ingestion_rejects_missing_metadata_and_non_ready_conflict(tmp_path) -> None:
    store = FakeChunkStore()
    store.persisted = None
    with pytest.raises(MvpIngestionIndexingError) as missing:
        _indexer(tmp_path, store=store)(_run())
    assert missing.value.error_code == "cx.mvp_ingestion.chunk_set_unavailable"

    with pytest.raises(MvpIngestionIndexingError) as invalid_owner:
        _indexer(tmp_path / "invalid")(_run(tenant_ref=None))
    assert invalid_owner.value.error_code == "cx.mvp_ingestion.owner_context_invalid"

    with pytest.raises(MvpIngestionIndexingError) as conflict:
        _indexer(
            tmp_path / "conflict",
            repository=ConflictRepository(),
        )(_run())
    assert conflict.value.error_code == "cx.mvp_ingestion.vector_index_conflict"


def test_mvp_ingestion_error_string_and_metadata_validation(tmp_path) -> None:
    with pytest.raises(MvpIngestionIndexingError) as exc_info:
        _indexer(tmp_path)(_run(request_id=""))
    assert str(exc_info.value)
    assert exc_info.value.error_code == "cx.mvp_ingestion.metadata_invalid"
