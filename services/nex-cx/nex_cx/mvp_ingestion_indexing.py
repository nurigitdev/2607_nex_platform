from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from nex_cx.access_context import CxAccessContext
from nex_cx.embedding_index import MoEmbeddingClient
from nex_cx.ingestion_coordinator import IngestionStepResult
from nex_cx.private_content import (
    CxPrivateTextStore,
    build_private_payload_key,
    sha256_private_text,
)
from nex_cx.vector_index_freshness import (
    build_embedding_profile,
    build_source_snapshot,
    build_vector_index_manifest,
)
from nex_cx.vector_index_publish import publish_vector_index
from nex_cx.vector_index_repository import VectorIndexRepository


class IngestionChunkStore(Protocol):
    def get_chunk_set(self, document_id: str) -> dict[str, Any] | None: ...

    def get_chunk_text(self, chunk_id: str) -> str | None: ...

    def get_persisted_chunk_set(
        self, document_id: str
    ) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class MvpIngestionIndexingError(Exception):
    error_code: str
    detail: str
    status_code: int = 500
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class MvpIngestionVectorIndexer:
    store: IngestionChunkStore
    private_text_store: CxPrivateTextStore
    embedding_client: MoEmbeddingClient
    embedding_alias: str
    vector_repository: VectorIndexRepository
    vector_store: Any
    runtime_hydrator: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None

    def __call__(self, run: Mapping[str, Any]) -> IngestionStepResult:
        if self.runtime_hydrator is not None:
            self.runtime_hydrator(run)
        context = _access_context(run)
        document_id = _required(run.get("document_id"), "document_id")
        public_chunk_set = self.store.get_chunk_set(document_id)
        persisted_chunk_set = self.store.get_persisted_chunk_set(document_id)
        if public_chunk_set is None or persisted_chunk_set is None:
            raise MvpIngestionIndexingError(
                error_code="cx.mvp_ingestion.chunk_set_unavailable",
                detail="Durable ingestion chunk metadata is unavailable.",
                status_code=409,
                retryable=True,
            )
        chunks = sorted(
            persisted_chunk_set["chunks"], key=lambda item: item["ordinal"]
        )
        private_texts = self._persist_private_chunk_texts(context, chunks)
        response = self.embedding_client.create_embeddings(
            private_texts,
            alias=self.embedding_alias,
            request_id=context.request_id,
            trace_id=context.trace_id,
        )
        vectors = _embedding_vectors(response, expected_count=len(chunks))
        profile = build_embedding_profile(
            provider_alias=_required(response.get("alias"), "alias"),
            model_profile_id=_required(
                response.get("model_profile_id") or response.get("model_revision"),
                "model_profile_id",
            ),
            model_revision=_required(
                response.get("model_revision"), "model_revision"
            ),
            deployment_id=_required(
                response.get("deployment_id"), "deployment_id"
            ),
            vector_dimension=len(vectors[0]),
        )
        source = build_source_snapshot(
            chunk_set_id=_required(
                persisted_chunk_set.get("chunk_set_id"), "chunk_set_id"
            ),
            chunk_policy_id=_required(
                persisted_chunk_set.get("chunk_policy_id"), "chunk_policy_id"
            ),
            source_markdown_sha256=_required(
                persisted_chunk_set.get("source_markdown_sha256"),
                "source_markdown_sha256",
            ),
            chunks=chunks,
        )
        manifest = build_vector_index_manifest(
            content_object_id=_required(
                persisted_chunk_set.get("content_object_id"), "content_object_id"
            ),
            tenant_ref={"type": "oa.tenant", "id": context.tenant_id},
            owner_subject_ref={"type": "oa.user", "id": context.subject_id},
            source_snapshot=source,
            embedding_profile=profile,
            trace_id=context.trace_id,
            request_id=context.request_id,
            observed_at=_required(run.get("updated_at"), "updated_at"),
        )
        existing = self.vector_repository.get(
            manifest["vector_index_id"],
            tenant_id=context.tenant_id,
            owner_subject_id=context.subject_id,
        )
        if existing is not None:
            if existing["status"] != "READY":
                raise MvpIngestionIndexingError(
                    error_code="cx.mvp_ingestion.vector_index_conflict",
                    detail="Existing vector index is not ready for idempotent reuse.",
                    status_code=409,
                    retryable=True,
                )
            return IngestionStepResult(
                output_ref=f"cx.vector_index:{existing['vector_index_id']}",
                skipped=True,
            )
        ready = publish_vector_index(
            access_context=context,
            manifest=manifest,
            vectors_by_chunk_id={
                chunk["chunk_id"]: vector
                for chunk, vector in zip(chunks, vectors, strict=True)
            },
            vector_store=self.vector_store,
            repository=self.vector_repository,
            observed_at=_required(run.get("updated_at"), "updated_at"),
        )
        return IngestionStepResult(
            output_ref=f"cx.vector_index:{ready['vector_index_id']}"
        )

    def _persist_private_chunk_texts(
        self,
        context: CxAccessContext,
        chunks: list[Mapping[str, Any]],
    ) -> list[str]:
        texts: list[str] = []
        for chunk in chunks:
            chunk_id = _required(chunk.get("chunk_id"), "chunk_id")
            text = self.store.get_chunk_text(chunk_id)
            if text is None:
                raise MvpIngestionIndexingError(
                    error_code="cx.mvp_ingestion.chunk_text_unavailable",
                    detail="Private chunk text is unavailable for indexing.",
                    status_code=409,
                    retryable=True,
                )
            expected_sha256 = _required(chunk.get("text_sha256"), "text_sha256")
            if sha256_private_text(text) != expected_sha256:
                raise MvpIngestionIndexingError(
                    error_code="cx.mvp_ingestion.chunk_text_integrity_failed",
                    detail="Private chunk text failed integrity validation.",
                    status_code=409,
                )
            self.private_text_store.put_text(
                access_context=context,
                key=build_private_payload_key(
                    context,
                    payload_kind="chunk_text",
                    content_id=chunk_id,
                ),
                text=text,
                expected_sha256=expected_sha256,
            )
            texts.append(text)
        return texts


def _embedding_vectors(
    response: object,
    *,
    expected_count: int,
) -> list[list[float]]:
    data = response.get("data") if isinstance(response, Mapping) else None
    if not isinstance(data, list) or len(data) != expected_count or not data:
        raise _embedding_invalid()
    vectors: list[list[float]] = []
    dimension: int | None = None
    for item in data:
        vector = item.get("embedding") if isinstance(item, Mapping) else None
        if (
            not isinstance(vector, list)
            or not vector
            or any(
                isinstance(value, bool) or not isinstance(value, int | float)
                for value in vector
            )
        ):
            raise _embedding_invalid()
        normalized = [float(value) for value in vector]
        if dimension is None:
            dimension = len(normalized)
        elif len(normalized) != dimension:
            raise _embedding_invalid()
        vectors.append(normalized)
    return vectors


def _access_context(run: Mapping[str, Any]) -> CxAccessContext:
    tenant = run.get("tenant_ref")
    owner = run.get("owner_subject_ref")
    if not isinstance(tenant, Mapping) or not isinstance(owner, Mapping):
        raise MvpIngestionIndexingError(
            error_code="cx.mvp_ingestion.owner_context_invalid",
            detail="Durable ingestion owner context is invalid.",
            status_code=422,
        )
    return CxAccessContext(
        caller_service_id="nex-cx",
        tenant_id=_required(tenant.get("id"), "tenant_ref.id"),
        subject_id=_required(owner.get("id"), "owner_subject_ref.id"),
        request_id=_required(run.get("request_id"), "request_id"),
        trace_id=_required(run.get("trace_id"), "trace_id"),
        scopes=("service.invoke",),
    )


def _required(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MvpIngestionIndexingError(
            error_code="cx.mvp_ingestion.metadata_invalid",
            detail=f"{field} must be a non-empty string.",
            status_code=422,
        )
    return value.strip()


def _embedding_invalid() -> MvpIngestionIndexingError:
    return MvpIngestionIndexingError(
        error_code="cx.mvp_ingestion.embedding_response_invalid",
        detail="Embedding response does not match the durable chunk set.",
        status_code=502,
        retryable=True,
    )
