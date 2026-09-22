from __future__ import annotations

"""Runtime orchestration for owner-scoped document intelligence."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_runtime import (
    OperationalEventEmitter,
    operational_event_emitter_from_app,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
)

from nex_cx.access_context import CxAccessContext
from nex_cx.api_ownership import document_visible_to_owner
from nex_cx.authorization import (
    CX_SUBJECT_HEADER,
    CX_TENANT_HEADER,
    authorize_cx_owner_request,
)
from nex_cx.document_intelligence_observability import (
    observe_document_intelligence_failure,
    observe_document_intelligence_ready,
    observe_document_intelligence_similarity,
)
from nex_cx.embedding_index import EmbeddingIndexError, MoEmbeddingClient
from nex_cx.generation import MoGenerationClient
from nex_cx.ingestion import ContentIngestionStore
from nex_cx.private_content import CxPrivateContentError, build_private_payload_key
from nex_cx.repository import CxContentRepositoryError
from nex_cx.summaries import SummaryError, build_and_store_document_summary
from nex_cx.summary_embeddings import (
    SummaryEmbeddingError,
    build_and_store_summary_embedding_index,
)
from nex_cx.summary_pgvector_store import (
    SummaryVectorBinding,
    build_summary_vector_binding,
)
from nex_cx.summary_similarity import SummarySimilarityError


DOCUMENT_INTELLIGENCE_RUN_SCHEMA_VERSION = "cx_document_intelligence_run.v1"
DOCUMENT_INTELLIGENCE_SIMILARITY_SCHEMA_VERSION = (
    "cx_document_intelligence_similarity.v1"
)
DEFAULT_SUMMARY_SIMILARITY_LIMIT = 10
DEFAULT_SUMMARY_SIMILARITY_MINIMUM_SCORE = 0.0


class BoundSummaryVectorStore(Protocol):
    def put_vector(
        self,
        *,
        access_context: CxAccessContext,
        key: Any,
        vector: Sequence[float],
        expected_sha256: str,
    ) -> Any:
        ...

    def get_vector(
        self,
        *,
        access_context: CxAccessContext,
        key: Any,
        expected_sha256: str,
        expected_dimension: int,
    ) -> tuple[float, ...] | None:
        ...

    def freshness(self, *, access_context: CxAccessContext) -> dict[str, Any]:
        ...


class SummaryVectorStore(Protocol):
    def bind_summary(self, binding: SummaryVectorBinding) -> BoundSummaryVectorStore:
        ...


class SummarySimilarityStore(Protocol):
    def search(
        self,
        *,
        access_context: CxAccessContext,
        query_vector: Sequence[float],
        profile_fingerprint: str,
        limit: int,
        minimum_score: float = -1.0,
        exclude_content_object_id: str | None = None,
    ) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class DocumentIntelligenceError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False


def register_document_intelligence_routes(
    app: FastAPI,
    *,
    store: ContentIngestionStore,
    generation_client: MoGenerationClient,
    embedding_client: MoEmbeddingClient,
    embedding_alias: str,
    summary_vector_store: SummaryVectorStore | None,
    summary_similarity_store: SummarySimilarityStore | None,
    event_emitter: OperationalEventEmitter | None = None,
) -> None:
    emitter = event_emitter or operational_event_emitter_from_app(
        app,
        service_id="nex-cx",
    )

    @app.post(
        "/api/v1/documents/{document_id}/intelligence/run",
        response_model=None,
    )
    def run_document_intelligence_route(
        document_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
        cx_tenant_id: str | None = Header(default=None, alias=CX_TENANT_HEADER),
        cx_subject_id: str | None = Header(default=None, alias=CX_SUBJECT_HEADER),
    ):
        access_context = authorize_cx_owner_request(
            request,
            authorization,
            tenant_id=cx_tenant_id,
            subject_id=cx_subject_id,
        )
        if isinstance(access_context, JSONResponse):
            return access_context
        if not document_visible_to_owner(access_context, store, document_id):
            return _problem_response(request, _not_found())
        request_id = request_id_from_headers(request)
        trace_id = trace_id_from_headers(request)
        try:
            result = run_document_intelligence(
                access_context=access_context,
                document_id=document_id,
                store=store,
                generation_client=generation_client,
                embedding_client=embedding_client,
                embedding_alias=embedding_alias,
                summary_vector_store=_required_vector_store(summary_vector_store),
                request_id=request_id,
                trace_id=trace_id,
            )
        except DocumentIntelligenceError as exc:
            observe_document_intelligence_failure(
                emitter,
                document_id=document_id,
                operation="run",
                error_code=exc.error_code,
                status_code=exc.status_code,
                retryable=exc.retryable,
                trace_id=trace_id,
                request_id=request_id,
            )
            return _problem_response(request, exc)
        observability = observe_document_intelligence_ready(
            emitter,
            document_id=document_id,
            result=result,
            trace_id=trace_id,
            request_id=request_id,
        )
        return {**result, "observability": observability.to_summary()}

    @app.post(
        "/api/v1/documents/{document_id}/intelligence/similar",
        response_model=None,
    )
    def search_similar_document_summaries_route(
        document_id: str,
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
        cx_tenant_id: str | None = Header(default=None, alias=CX_TENANT_HEADER),
        cx_subject_id: str | None = Header(default=None, alias=CX_SUBJECT_HEADER),
    ):
        access_context = authorize_cx_owner_request(
            request,
            authorization,
            tenant_id=cx_tenant_id,
            subject_id=cx_subject_id,
        )
        if isinstance(access_context, JSONResponse):
            return access_context
        if not document_visible_to_owner(access_context, store, document_id):
            return _problem_response(request, _not_found())
        request_id = request_id_from_headers(request)
        trace_id = trace_id_from_headers(request)
        try:
            result = search_similar_document_summaries(
                access_context=access_context,
                document_id=document_id,
                store=store,
                summary_vector_store=_required_vector_store(summary_vector_store),
                summary_similarity_store=_required_similarity_store(
                    summary_similarity_store
                ),
                limit=payload.get("limit", DEFAULT_SUMMARY_SIMILARITY_LIMIT),
                minimum_score=payload.get(
                    "minimum_score",
                    DEFAULT_SUMMARY_SIMILARITY_MINIMUM_SCORE,
                ),
            )
        except DocumentIntelligenceError as exc:
            observe_document_intelligence_failure(
                emitter,
                document_id=document_id,
                operation="similarity",
                error_code=exc.error_code,
                status_code=exc.status_code,
                retryable=exc.retryable,
                trace_id=trace_id,
                request_id=request_id,
            )
            return _problem_response(request, exc)
        observability = observe_document_intelligence_similarity(
            emitter,
            document_id=document_id,
            result=result,
            trace_id=trace_id,
            request_id=request_id,
        )
        return {**result, "observability": observability.to_summary()}


def run_document_intelligence(
    *,
    access_context: CxAccessContext,
    document_id: str,
    store: ContentIngestionStore,
    generation_client: MoGenerationClient,
    embedding_client: MoEmbeddingClient,
    embedding_alias: str,
    summary_vector_store: SummaryVectorStore,
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    try:
        generated_summary = build_and_store_document_summary(
            document_id,
            store=store,
            generation_client=generation_client,
            request_id=request_id,
            trace_id=trace_id,
        )
        build_and_store_summary_embedding_index(
            document_id,
            store=store,
            mo_client=embedding_client,
            embedding_alias=embedding_alias,
            request_id=request_id,
            trace_id=trace_id,
        )
        binding = _current_binding(access_context, document_id, store)
        vector = store.get_summary_embedding_vector(str(binding.document_summary_id))
        if vector is None:
            raise DocumentIntelligenceError(
                status_code=409,
                error_code="CX_DOCUMENT_INTELLIGENCE_VECTOR_MISSING",
                detail="Generated summary vector was not available for publication.",
                retryable=True,
            )
        key = _summary_vector_key(access_context, binding)
        bound_store = summary_vector_store.bind_summary(binding)
        receipt = bound_store.put_vector(
            access_context=access_context,
            key=key,
            vector=vector,
            expected_sha256=binding.embedding_sha256,
        )
        freshness = bound_store.freshness(access_context=access_context)
        if freshness.get("usable") is not True:
            raise DocumentIntelligenceError(
                status_code=409,
                error_code="CX_DOCUMENT_INTELLIGENCE_VECTOR_STALE",
                detail="Published summary vector did not pass freshness verification.",
                retryable=True,
            )
    except DocumentIntelligenceError:
        raise
    except (
        SummaryError,
        SummaryEmbeddingError,
        EmbeddingIndexError,
        CxPrivateContentError,
        CxContentRepositoryError,
    ) as exc:
        raise _dependency_error(exc) from exc

    return {
        "document_intelligence_run_schema_version": (
            DOCUMENT_INTELLIGENCE_RUN_SCHEMA_VERSION
        ),
        "document_id": document_id,
        "status": "READY",
        "summary": _summary_projection(generated_summary),
        "summary_embedding": _embedding_projection(binding),
        "summary_vector": {
            "summary_vector_id": str(binding.summary_vector_id),
            "storage_backend": receipt.storage_backend,
            "storage_uri": receipt.storage_uri,
            "embedding_sha256": receipt.sha256,
            "vector_dimension": receipt.vector_dimension,
            "profile_fingerprint": binding.profile_fingerprint,
            "freshness": freshness,
        },
        "raw_summary_included": False,
        "raw_vector_included": False,
    }


def search_similar_document_summaries(
    *,
    access_context: CxAccessContext,
    document_id: str,
    store: ContentIngestionStore,
    summary_vector_store: SummaryVectorStore,
    summary_similarity_store: SummarySimilarityStore,
    limit: int = DEFAULT_SUMMARY_SIMILARITY_LIMIT,
    minimum_score: float = DEFAULT_SUMMARY_SIMILARITY_MINIMUM_SCORE,
) -> dict[str, Any]:
    try:
        binding = _current_binding(access_context, document_id, store)
        key = _summary_vector_key(access_context, binding)
        bound_store = summary_vector_store.bind_summary(binding)
        freshness = bound_store.freshness(access_context=access_context)
        if freshness.get("usable") is not True:
            raise DocumentIntelligenceError(
                status_code=409,
                error_code="CX_DOCUMENT_INTELLIGENCE_VECTOR_STALE",
                detail="Source summary vector is missing or stale.",
                retryable=True,
            )
        query_vector = bound_store.get_vector(
            access_context=access_context,
            key=key,
            expected_sha256=binding.embedding_sha256,
            expected_dimension=binding.vector_dimension,
        )
        if query_vector is None:
            raise DocumentIntelligenceError(
                status_code=409,
                error_code="CX_DOCUMENT_INTELLIGENCE_VECTOR_MISSING",
                detail="Source summary vector was not found.",
                retryable=True,
            )
        result = summary_similarity_store.search(
            access_context=access_context,
            query_vector=query_vector,
            profile_fingerprint=binding.profile_fingerprint,
            limit=limit,
            minimum_score=minimum_score,
            exclude_content_object_id=str(binding.content_object_id),
        )
    except DocumentIntelligenceError:
        raise
    except (
        CxPrivateContentError,
        CxContentRepositoryError,
        SummarySimilarityError,
    ) as exc:
        raise _dependency_error(exc) from exc

    return {
        "document_intelligence_similarity_schema_version": (
            DOCUMENT_INTELLIGENCE_SIMILARITY_SCHEMA_VERSION
        ),
        "source_document": {
            "content_object_id": str(binding.content_object_id),
            "document_summary_id": str(binding.document_summary_id),
            "summary_embedding_id": str(binding.summary_embedding_id),
            "profile_fingerprint": binding.profile_fingerprint,
        },
        "freshness": freshness,
        "result": result,
        "raw_summary_included": False,
        "raw_vector_included": False,
    }


def _current_binding(
    access_context: CxAccessContext,
    document_id: str,
    store: ContentIngestionStore,
) -> SummaryVectorBinding:
    repository = store.content_repository
    content = repository.get_content_object(document_id)
    if content is None:
        raise _not_found()
    summary = repository.get_latest_document_summary_record(document_id)
    if summary is None:
        raise DocumentIntelligenceError(
            status_code=409,
            error_code="CX_DOCUMENT_INTELLIGENCE_SUMMARY_MISSING",
            detail="A persisted document summary is required.",
            retryable=True,
        )
    embedding = repository.get_latest_summary_embedding_record(
        str(summary["document_summary_id"])
    )
    if embedding is None:
        raise DocumentIntelligenceError(
            status_code=409,
            error_code="CX_DOCUMENT_INTELLIGENCE_EMBEDDING_MISSING",
            detail="A persisted summary embedding is required.",
            retryable=True,
        )
    return build_summary_vector_binding(
        access_context=access_context,
        content_object=content,
        summary=summary,
        embedding=embedding,
    )


def _summary_vector_key(
    access_context: CxAccessContext,
    binding: SummaryVectorBinding,
) -> Any:
    return build_private_payload_key(
        access_context,
        payload_kind="summary_embedding",
        content_id=str(binding.document_summary_id),
    )


def _summary_projection(summary: Mapping[str, Any]) -> dict[str, Any]:
    return {
        field: summary.get(field)
        for field in (
            "document_summary_id",
            "status",
            "summary_text_sha256",
            "summary_char_count",
            "summary_preview",
            "summary_storage_uri",
            "source_markdown_sha256",
            "summarizer",
            "updated_at",
        )
    }


def _embedding_projection(binding: SummaryVectorBinding) -> dict[str, Any]:
    return {
        "summary_embedding_id": str(binding.summary_embedding_id),
        "document_summary_id": str(binding.document_summary_id),
        "provider_alias": binding.provider_alias,
        "model_profile_id": binding.model_profile_id,
        "model_revision": binding.model_revision,
        "deployment_id": binding.deployment_id,
        "embedding_sha256": binding.embedding_sha256,
        "vector_dimension": binding.vector_dimension,
    }


def _required_vector_store(value: SummaryVectorStore | None) -> SummaryVectorStore:
    if value is None:
        raise _runtime_unavailable()
    return value


def _required_similarity_store(
    value: SummarySimilarityStore | None,
) -> SummarySimilarityStore:
    if value is None:
        raise _runtime_unavailable()
    return value


def _runtime_unavailable() -> DocumentIntelligenceError:
    return DocumentIntelligenceError(
        status_code=503,
        error_code="CX_DOCUMENT_INTELLIGENCE_RUNTIME_UNAVAILABLE",
        detail="Document intelligence persistence is unavailable.",
        retryable=True,
    )


def _not_found() -> DocumentIntelligenceError:
    return DocumentIntelligenceError(
        status_code=404,
        error_code="CX_DOCUMENT_INTELLIGENCE_NOT_FOUND",
        detail="Document intelligence resource was not found for the owner scope.",
    )


def _dependency_error(exc: Exception) -> DocumentIntelligenceError:
    return DocumentIntelligenceError(
        status_code=int(getattr(exc, "status_code", 503)),
        error_code=str(
            getattr(exc, "error_code", "CX_DOCUMENT_INTELLIGENCE_UNAVAILABLE")
        ),
        detail=str(getattr(exc, "detail", "Document intelligence is unavailable.")),
        retryable=bool(getattr(exc, "retryable", True)),
    )


def _problem_response(
    request: Request,
    exc: DocumentIntelligenceError,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Document intelligence request failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/document-intelligence-failed",
    )
