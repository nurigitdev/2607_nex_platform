from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from nex_cx.access_context import CxAccessContext
from nex_cx.embedding_index import MoEmbeddingClient
from nex_cx.hybrid_candidate_orchestration import (
    HybridCandidateOrchestrationError,
    LexicalCandidateSearcher,
    orchestrate_permission_filtered_candidates,
)
from nex_cx.hybrid_ranking import PermissionAwareRerankClient
from nex_cx.hybrid_retrieval_package import PermissionFilteredHybridPackageRuntime
from nex_cx.private_content import sha256_private_vector
from nex_cx.retrieval_permissions import filter_retrieval_document_scope
from nex_cx.vector_index_repository import VectorIndexRepository
from nex_cx.vector_retrieval_guard import VectorSearchAdapter


class HybridRetrievalSource(Protocol):
    def load_content_objects(
        self,
        document_ids: Sequence[str],
    ) -> Mapping[str, object]: ...

    def load_vector_targets(
        self,
        *,
        access_context: CxAccessContext,
        document_ids: Sequence[str],
    ) -> Mapping[str, Mapping[str, Any]]: ...

    def load_private_evidence(
        self,
        *,
        access_context: CxAccessContext,
        chunk_refs: Sequence[Mapping[str, str]],
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class ProductionHybridCandidateProvider:
    source: HybridRetrievalSource
    lexical_store: LexicalCandidateSearcher
    vector_repository: VectorIndexRepository
    vector_store: VectorSearchAdapter
    embedding_client: MoEmbeddingClient
    embedding_alias: str
    lexical_limit: int = 80
    vector_limit: int = 80

    def build_candidate_set(
        self,
        *,
        access_context: CxAccessContext,
        query_text: str,
        requested_document_ids: Sequence[str],
    ) -> dict[str, Any]:
        content_objects = self.source.load_content_objects(requested_document_ids)
        permission = filter_retrieval_document_scope(
            access_context=access_context,
            requested_document_ids=requested_document_ids,
            content_objects=content_objects,
            require_all_visible=True,
        )
        visible_ids = permission["visible_document_ids"]
        vector_targets = self.source.load_vector_targets(
            access_context=access_context,
            document_ids=visible_ids,
        )
        query_vector, query_embedding_profile = _query_embedding(
            self.embedding_client,
            query_text=query_text,
            embedding_alias=self.embedding_alias,
            access_context=access_context,
        )
        result = orchestrate_permission_filtered_candidates(
            access_context=access_context,
            query_text=query_text,
            requested_document_ids=visible_ids,
            content_objects=content_objects,
            lexical_store=self.lexical_store,
            vector_targets_by_document_id=vector_targets,
            query_vector=query_vector,
            vector_repository=self.vector_repository,
            vector_store=self.vector_store,
            lexical_limit=self.lexical_limit,
            vector_limit=self.vector_limit,
        )
        result["query_vector_sha256"] = sha256_private_vector(query_vector)
        result["query_embedding_profile"] = query_embedding_profile
        return result


@dataclass(frozen=True)
class ProductionAuthorizedEvidenceMaterializer:
    source: HybridRetrievalSource

    def load_authorized_texts(
        self,
        *,
        access_context: CxAccessContext,
        chunk_refs: Sequence[Mapping[str, str]],
    ) -> list[dict[str, Any]]:
        return self._load(access_context=access_context, chunk_refs=chunk_refs)

    def load_authorized_evidence(
        self,
        *,
        access_context: CxAccessContext,
        chunk_refs: Sequence[Mapping[str, str]],
    ) -> list[dict[str, Any]]:
        return self._load(access_context=access_context, chunk_refs=chunk_refs)

    def _load(
        self,
        *,
        access_context: CxAccessContext,
        chunk_refs: Sequence[Mapping[str, str]],
    ) -> list[dict[str, Any]]:
        document_ids = _document_ids(chunk_refs)
        content_objects = self.source.load_content_objects(document_ids)
        filter_retrieval_document_scope(
            access_context=access_context,
            requested_document_ids=document_ids,
            content_objects=content_objects,
            require_all_visible=True,
        )
        return self.source.load_private_evidence(
            access_context=access_context,
            chunk_refs=chunk_refs,
        )


def build_permission_hardened_hybrid_runtime(
    *,
    source: HybridRetrievalSource,
    lexical_store: LexicalCandidateSearcher,
    vector_repository: VectorIndexRepository,
    vector_store: VectorSearchAdapter,
    embedding_client: MoEmbeddingClient,
    embedding_alias: str,
    rerank_client: PermissionAwareRerankClient | None = None,
    reranker_alias: str = "mock-reranker-default",
) -> PermissionFilteredHybridPackageRuntime:
    return PermissionFilteredHybridPackageRuntime(
        candidate_provider=ProductionHybridCandidateProvider(
            source=source,
            lexical_store=lexical_store,
            vector_repository=vector_repository,
            vector_store=vector_store,
            embedding_client=embedding_client,
            embedding_alias=embedding_alias,
        ),
        evidence_materializer=ProductionAuthorizedEvidenceMaterializer(source),
        rerank_client=rerank_client,
        reranker_alias=reranker_alias,
    )


def _query_embedding(
    client: MoEmbeddingClient,
    *,
    query_text: str,
    embedding_alias: str,
    access_context: CxAccessContext,
) -> tuple[list[float], dict[str, str | None]]:
    try:
        response = client.create_embeddings(
            [query_text],
            alias=embedding_alias,
            request_id=access_context.request_id,
            trace_id=access_context.trace_id,
        )
        data = response.get("data") if isinstance(response, Mapping) else None
        item = data[0] if isinstance(data, list) and len(data) == 1 else None
        vector = item.get("embedding") if isinstance(item, Mapping) else None
        if (
            not isinstance(vector, list)
            or not vector
            or any(
                isinstance(value, bool) or not isinstance(value, int | float)
                for value in vector
            )
        ):
            raise ValueError("invalid embedding response")
        return [float(value) for value in vector], {
            "provider_alias": _optional_identity(response.get("alias"))
            or embedding_alias,
            "model_revision": _optional_identity(response.get("model_revision")),
            "deployment_id": _optional_identity(response.get("deployment_id")),
        }
    except HybridCandidateOrchestrationError:
        raise
    except Exception as exc:
        raise HybridCandidateOrchestrationError(
            status_code=503,
            error_code="CX_QUERY_EMBEDDING_UNAVAILABLE",
            detail="Owner-scoped hybrid retrieval query embedding is unavailable.",
            retryable=True,
        ) from exc


def _optional_identity(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized if normalized and len(normalized) <= 160 else None


def _document_ids(
    chunk_refs: Sequence[Mapping[str, str]],
) -> list[str]:
    if isinstance(chunk_refs, (str, bytes)):
        raise HybridCandidateOrchestrationError(
            status_code=422,
            error_code="CX_EVIDENCE_SCOPE_INVALID",
            detail="Evidence chunk references are invalid.",
        )
    result: list[str] = []
    seen: set[str] = set()
    for ref in chunk_refs:
        document_id = ref.get("content_object_id") if isinstance(ref, Mapping) else None
        if not isinstance(document_id, str) or not document_id:
            raise HybridCandidateOrchestrationError(
                status_code=422,
                error_code="CX_EVIDENCE_SCOPE_INVALID",
                detail="Evidence chunk references are invalid.",
            )
        if document_id not in seen:
            result.append(document_id)
            seen.add(document_id)
    return result
