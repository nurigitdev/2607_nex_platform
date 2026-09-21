from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from nex_cx.access_context import CxAccessContext
from nex_cx.vector_index_freshness import assess_vector_index_freshness
from nex_cx.vector_index_repository import VectorIndexRepository


class VectorRetrievalError(RuntimeError):
    def __init__(
        self,
        *,
        status_code: int,
        error_code: str,
        detail: str,
        retryable: bool = False,
        freshness: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.error_code = error_code
        self.detail = detail
        self.retryable = retryable
        self.freshness = dict(freshness) if freshness is not None else None


class BoundVectorSearch(Protocol):
    def payload_snapshot(
        self,
        *,
        access_context: CxAccessContext,
    ) -> dict[str, Any]: ...

    def search(
        self,
        *,
        access_context: CxAccessContext,
        query_vector: Sequence[float],
        limit: int,
    ) -> list[dict[str, Any]]: ...


class VectorSearchAdapter(Protocol):
    def bind_index(self, manifest: Mapping[str, Any]) -> BoundVectorSearch: ...


def search_fresh_vector_index(
    *,
    access_context: CxAccessContext,
    vector_index_id: str,
    source_snapshot: Mapping[str, Any],
    embedding_profile: Mapping[str, Any],
    query_vector: Sequence[float],
    limit: int,
    repository: VectorIndexRepository,
    vector_store: VectorSearchAdapter,
) -> dict[str, Any]:
    manifest = repository.get(
        vector_index_id,
        tenant_id=access_context.tenant_id,
        owner_subject_id=access_context.subject_id,
    )
    if manifest is None:
        raise VectorRetrievalError(
            status_code=404,
            error_code="CX_VECTOR_INDEX_NOT_FOUND",
            detail="Vector index was not found for the owner scope.",
        )

    bound_store = vector_store.bind_index(manifest)
    payload = bound_store.payload_snapshot(access_context=access_context)
    freshness = assess_vector_index_freshness(
        manifest,
        source_snapshot=source_snapshot,
        embedding_profile=embedding_profile,
        payload_count=payload["payload_count"],
        payload_fingerprint=payload["payload_fingerprint"],
    )
    if not freshness["retrieval_usable"]:
        reason = freshness.get("reason") or "INDEX_NOT_READY"
        raise VectorRetrievalError(
            status_code=409,
            error_code="CX_VECTOR_INDEX_NOT_READY",
            detail=f"Vector retrieval is unavailable: {reason}.",
            retryable=freshness["status"] == "BUILDING",
            freshness=freshness,
        )

    matches = bound_store.search(
        access_context=access_context,
        query_vector=query_vector,
        limit=limit,
    )
    return {
        "retrieval_schema_version": "cx_vector_retrieval.v1",
        "vector_index_id": manifest["vector_index_id"],
        "content_object_id": manifest["content_object_id"],
        "freshness": freshness,
        "matches": matches,
    }
