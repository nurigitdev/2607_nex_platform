from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
    validate_authorization_header,
)

from nex_cx.embedding_index import (
    DEFAULT_EMBEDDING_ALIAS,
    MoEmbeddingClient,
    build_default_mo_embedding_client,
)
from nex_cx.ingestion import ContentIngestionStore, sha256_text


@dataclass(frozen=True)
class SummaryEmbeddingError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False


def register_summary_embedding_routes(
    app: FastAPI,
    *,
    store: ContentIngestionStore,
    mo_client: MoEmbeddingClient | None = None,
    embedding_alias: str | None = None,
) -> None:
    client = mo_client or build_default_mo_embedding_client()
    alias = embedding_alias or DEFAULT_EMBEDDING_ALIAS

    @app.post("/api/v1/documents/{document_id}/summary-embedding/run", response_model=None)
    def run_summary_embedding(
        document_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_cx_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        try:
            return build_and_store_summary_embedding_index(
                document_id,
                store=store,
                mo_client=client,
                embedding_alias=alias,
                request_id=request_id_from_headers(request),
                trace_id=trace_id_from_headers(request),
            )
        except SummaryEmbeddingError as exc:
            return _summary_embedding_problem_response(request, exc)

    @app.get("/api/v1/documents/{document_id}/summary-embedding", response_model=None)
    def get_summary_embedding(
        document_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_cx_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        record = store.get_summary_embedding_index(document_id)
        if record is None:
            return _summary_embedding_problem_response(
                request,
                SummaryEmbeddingError(
                    status_code=404,
                    error_code="cx.summary_embedding_not_found",
                    detail=f"Document summary embedding was not found: {document_id}",
                ),
            )
        return record


def build_and_store_summary_embedding_index(
    document_id: str,
    *,
    store: ContentIngestionStore,
    mo_client: MoEmbeddingClient,
    embedding_alias: str,
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    summary = store.get_document_summary(document_id)
    if summary is None:
        raise SummaryEmbeddingError(
            status_code=404,
            error_code="cx.document_summary_not_found",
            detail=f"Document summary was not found: {document_id}",
        )

    summary_text = store.get_summary_text(summary["document_summary_id"])
    if summary_text is None:
        raise SummaryEmbeddingError(
            status_code=409,
            error_code="cx.summary_text_unavailable",
            detail=f"Private summary text was not found: {summary['document_summary_id']}",
            retryable=True,
        )

    mo_response = mo_client.create_embeddings(
        [summary_text],
        alias=embedding_alias,
        request_id=request_id,
        trace_id=trace_id,
    )
    return store_summary_embedding_index(
        document_id=document_id,
        summary=summary,
        mo_response=mo_response,
        store=store,
        request_id=request_id,
        trace_id=trace_id,
    )


def store_summary_embedding_index(
    *,
    document_id: str,
    summary: dict[str, Any],
    mo_response: dict[str, Any],
    store: ContentIngestionStore,
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    response_items = mo_response.get("data", [])
    if not isinstance(response_items, list) or len(response_items) != 1:
        raise SummaryEmbeddingError(
            status_code=502,
            error_code="cx.summary_embedding_response_invalid",
            detail="MO embedding response must include exactly one summary embedding.",
            retryable=True,
        )

    vector = embedding_vector_from_item(response_items[0])
    now = _utc_now()
    record = {
        "summary_embedding_schema_version": "cx_document_summary_embedding.v1",
        "document_id": document_id,
        "document_summary_id": summary["document_summary_id"],
        "trace_id": trace_id,
        "request_id": request_id,
        "provider_alias": mo_response["alias"],
        "model_revision": mo_response["model_revision"],
        "deployment_id": mo_response["deployment_id"],
        "summary_text_sha256": summary["summary_text_sha256"],
        "embedding_sha256": sha256_json({"embedding": vector}),
        "vector_dimension": len(vector),
        "usage": mo_response.get("usage", {}),
        "created_at": now,
        "updated_at": now,
    }
    return store.save_summary_embedding_index(record, embedding_vector=vector)


def embedding_vector_from_item(item: Any) -> list[float]:
    if not isinstance(item, dict):
        raise SummaryEmbeddingError(
            status_code=502,
            error_code="cx.summary_embedding_response_invalid",
            detail="MO summary embedding item must be an object.",
            retryable=True,
        )
    vector = item.get("embedding")
    if not isinstance(vector, list) or not vector or not all(
        isinstance(value, int | float) and not isinstance(value, bool)
        for value in vector
    ):
        raise SummaryEmbeddingError(
            status_code=502,
            error_code="cx.summary_embedding_response_invalid",
            detail="MO summary embedding vector must be a non-empty numeric list.",
            retryable=True,
        )
    return [float(value) for value in vector]


def sha256_json(value: dict[str, Any]) -> str:
    return sha256_text(json.dumps(value, sort_keys=True, separators=(",", ":")))


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
        detail="CX requires a valid service claim.",
        type_uri="https://nex-platform.local/problems/authentication-failed",
    )


def _summary_embedding_problem_response(
    request: Request,
    exc: SummaryEmbeddingError,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Summary embedding request failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/summary-embedding-failed",
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
