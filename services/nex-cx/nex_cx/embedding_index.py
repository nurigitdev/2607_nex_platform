from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    issue_mock_service_token,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
    validate_authorization_header,
)

from nex_cx.ingestion import ContentIngestionStore, sha256_text

DEFAULT_EMBEDDING_ALIAS = "mock-embedding-default"


class MoEmbeddingClient(Protocol):
    def create_embeddings(
        self,
        inputs: list[str],
        *,
        alias: str,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class HttpMoEmbeddingClient:
    base_url: str = "http://127.0.0.1:8105"
    service_token: str | None = None
    timeout_seconds: float = 5.0

    def create_embeddings(
        self,
        inputs: list[str],
        *,
        alias: str,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        token = self.service_token or issue_mock_service_token(
            service_id="nex-cx",
            audience="nex-mo",
        ).access_token
        response = httpx.post(
            f"{self.base_url}/api/v1/embeddings",
            json={"alias": alias, "inputs": inputs},
            headers={
                "Authorization": f"Bearer {token}",
                "X-Request-ID": request_id,
                "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
                "X-Service-ID": "nex-cx",
            },
            timeout=self.timeout_seconds,
        )
        if response.status_code >= 400:
            body = _safe_response_json(response)
            raise EmbeddingIndexError(
                status_code=response.status_code,
                error_code=body.get("error_code", "mo.embedding_request_failed"),
                detail=body.get("detail", "MO embedding request failed."),
                retryable=body.get("retryable", False),
            )
        return response.json()


@dataclass(frozen=True)
class EmbeddingIndexError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False


def build_default_mo_embedding_client() -> HttpMoEmbeddingClient:
    return HttpMoEmbeddingClient(
        base_url=os.getenv("NEX_MO_BASE_URL", "http://127.0.0.1:8105"),
        service_token=os.getenv("NEX_CX_TO_MO_SERVICE_TOKEN"),
    )


def register_embedding_index_routes(
    app: FastAPI,
    *,
    store: ContentIngestionStore,
    mo_client: MoEmbeddingClient | None = None,
    embedding_alias: str | None = None,
) -> None:
    client = mo_client or build_default_mo_embedding_client()
    alias = embedding_alias or os.getenv("NEX_CX_EMBEDDING_ALIAS", DEFAULT_EMBEDDING_ALIAS)

    @app.post("/api/v1/documents/{document_id}/embeddings/run", response_model=None)
    def run_embeddings(
        document_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_cx_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        try:
            return build_and_store_embedding_index(
                document_id,
                store=store,
                mo_client=client,
                embedding_alias=alias,
                request_id=request_id_from_headers(request),
                trace_id=trace_id_from_headers(request),
            )
        except EmbeddingIndexError as exc:
            return _embedding_problem_response(request, exc)

    @app.get("/api/v1/documents/{document_id}/embeddings", response_model=None)
    def get_embeddings(
        document_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_cx_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        embedding_index = store.get_embedding_index(document_id)
        if embedding_index is None:
            return _embedding_problem_response(
                request,
                EmbeddingIndexError(
                    status_code=404,
                    error_code="cx.embedding_index_not_found",
                    detail=f"Embedding index was not found: {document_id}",
                ),
            )
        return embedding_index


def build_and_store_embedding_index(
    document_id: str,
    *,
    store: ContentIngestionStore,
    mo_client: MoEmbeddingClient,
    embedding_alias: str,
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    chunk_set = store.get_chunk_set(document_id)
    if chunk_set is None:
        raise EmbeddingIndexError(
            status_code=404,
            error_code="cx.chunk_set_not_found",
            detail=f"Chunk set was not found: {document_id}",
        )

    chunk_texts = ordered_chunk_texts(chunk_set, store)
    mo_response = mo_client.create_embeddings(
        chunk_texts,
        alias=embedding_alias,
        request_id=request_id,
        trace_id=trace_id,
    )
    return store_embedding_index(
        document_id=document_id,
        chunk_set=chunk_set,
        mo_response=mo_response,
        store=store,
        request_id=request_id,
        trace_id=trace_id,
    )


def ordered_chunk_texts(
    chunk_set: dict[str, Any],
    store: ContentIngestionStore,
) -> list[str]:
    ordered_chunks = sorted(chunk_set["chunks"], key=lambda chunk: chunk["ordinal"])
    texts: list[str] = []
    for chunk in ordered_chunks:
        text = store.get_chunk_text(chunk["chunk_id"])
        if text is None:
            raise EmbeddingIndexError(
                status_code=409,
                error_code="cx.chunk_text_unavailable",
                detail=f"Chunk text was not found: {chunk['chunk_id']}",
                retryable=True,
            )
        texts.append(text)
    return texts


def store_embedding_index(
    *,
    document_id: str,
    chunk_set: dict[str, Any],
    mo_response: dict[str, Any],
    store: ContentIngestionStore,
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    response_items = mo_response.get("data", [])
    chunks = sorted(chunk_set["chunks"], key=lambda chunk: chunk["ordinal"])
    if not isinstance(response_items, list) or len(response_items) != len(chunks):
        raise EmbeddingIndexError(
            status_code=502,
            error_code="cx.embedding_response_invalid",
            detail="MO embedding response count did not match chunk count.",
            retryable=True,
        )

    now = _utc_now()
    public_embeddings: list[dict[str, Any]] = []
    private_vectors: dict[str, list[float]] = {}
    vector_dimension = 0
    for chunk, item in zip(chunks, response_items, strict=True):
        vector = _embedding_vector_from_item(item)
        vector_dimension = len(vector)
        chunk_id = chunk["chunk_id"]
        public_embeddings.append(
            {
                "chunk_id": chunk_id,
                "ordinal": chunk["ordinal"],
                "text_sha256": chunk["text_sha256"],
                "embedding_sha256": sha256_json({"embedding": vector}),
                "vector_dimension": vector_dimension,
            }
        )
        private_vectors[chunk_id] = vector

    embedding_index = {
        "embedding_index_schema_version": "cx_embedding_index.v1",
        "document_id": document_id,
        "trace_id": trace_id,
        "request_id": request_id,
        "provider_alias": mo_response["alias"],
        "model_revision": mo_response["model_revision"],
        "deployment_id": mo_response["deployment_id"],
        "chunk_count": len(public_embeddings),
        "vector_dimension": vector_dimension,
        "chunk_embeddings": public_embeddings,
        "usage": mo_response.get("usage", {}),
        "created_at": now,
        "updated_at": now,
    }
    return store.save_embedding_index(
        embedding_index,
        embedding_vectors=private_vectors,
    )


def sha256_json(value: dict[str, Any]) -> str:
    return sha256_text(json.dumps(value, sort_keys=True, separators=(",", ":")))


def _embedding_vector_from_item(item: Any) -> list[float]:
    if not isinstance(item, dict):
        raise EmbeddingIndexError(
            status_code=502,
            error_code="cx.embedding_response_invalid",
            detail="MO embedding item must be an object.",
            retryable=True,
        )
    vector = item.get("embedding")
    if not isinstance(vector, list) or not vector or not all(
        isinstance(value, int | float) and not isinstance(value, bool)
        for value in vector
    ):
        raise EmbeddingIndexError(
            status_code=502,
            error_code="cx.embedding_response_invalid",
            detail="MO embedding vector must be a non-empty numeric list.",
            retryable=True,
        )
    return [float(value) for value in vector]


def _authorize_cx_request(
    request: Request,
    authorization: str | None,
) -> JSONResponse | None:
    result = validate_authorization_header(
        authorization,
        expected_audience="nex-cx",
        required_scopes=[DEFAULT_SERVICE_SCOPE],
    )
    if result.ok:
        return None

    return problem_response(
        request,
        status_code=401,
        error_code=result.error_code or "SERVICE_CLAIM_INVALID",
        title="Authentication failed",
        detail=result.detail or "CX requires a valid service claim.",
        type_uri="https://nex-platform.local/problems/authentication-failed",
    )


def _embedding_problem_response(
    request: Request,
    exc: EmbeddingIndexError,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Embedding index request failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/embedding-index-failed",
    )


def _safe_response_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except json.JSONDecodeError:
        return {}
    if isinstance(payload, dict):
        return payload
    return {}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
