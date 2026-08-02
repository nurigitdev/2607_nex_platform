from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
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

from nex_cx.ingestion import ContentIngestionStore, CxStorageConfig
from nex_cx.ingestion import build_storage_config, sha256_text


@dataclass(frozen=True)
class ChunkingError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False


def register_chunking_routes(
    app: FastAPI,
    *,
    store: ContentIngestionStore,
    storage_config: CxStorageConfig | None = None,
) -> None:
    config = storage_config or build_storage_config()

    @app.post("/api/v1/documents/{document_id}/chunks/run", response_model=None)
    def run_chunks(
        document_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_cx_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        try:
            return build_and_store_chunk_set(
                document_id,
                store=store,
                storage_config=config,
                request_id=request_id_from_headers(request),
                trace_id=trace_id_from_headers(request),
            )
        except ChunkingError as exc:
            return _chunking_problem_response(request, exc)

    @app.get("/api/v1/documents/{document_id}/chunks", response_model=None)
    def get_chunks(
        document_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_cx_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        chunk_set = store.get_chunk_set(document_id)
        if chunk_set is None:
            return _chunking_problem_response(
                request,
                ChunkingError(
                    status_code=404,
                    error_code="cx.chunk_set_not_found",
                    detail=f"Chunk set was not found: {document_id}",
                ),
            )
        return chunk_set


def build_and_store_chunk_set(
    document_id: str,
    *,
    store: ContentIngestionStore,
    storage_config: CxStorageConfig,
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    extraction = store.get_extraction_result(document_id)
    if extraction is None:
        raise ChunkingError(
            status_code=404,
            error_code="cx.extraction_result_not_found",
            detail=f"Extraction result was not found: {document_id}",
        )

    markdown_path = Path(extraction["extracted_markdown_path"])
    if not markdown_path.exists():
        raise ChunkingError(
            status_code=409,
            error_code="cx.extracted_markdown_missing",
            detail=f"Extracted Markdown file was not found: {markdown_path}",
            retryable=True,
        )

    markdown_text = markdown_path.read_text(encoding="utf-8")
    return store_chunk_set(
        document_id=document_id,
        extraction=extraction,
        markdown_text=markdown_text,
        store=store,
        storage_config=storage_config,
        request_id=request_id,
        trace_id=trace_id,
    )


def store_chunk_set(
    *,
    document_id: str,
    extraction: dict[str, Any],
    markdown_text: str,
    store: ContentIngestionStore,
    storage_config: CxStorageConfig,
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    chunks = chunk_text(
        markdown_text,
        chunk_size=storage_config.chunk_size,
        chunk_overlap=storage_config.chunk_overlap,
    )
    now = _utc_now()
    chunk_items, private_text = build_chunk_items(
        chunks,
        document_id=document_id,
    )
    chunk_set = {
        "chunk_set_schema_version": "cx_chunk_set.v1",
        "document_id": document_id,
        "extraction_job_id": extraction["job_id"],
        "trace_id": trace_id,
        "request_id": request_id,
        "chunk_policy": storage_config.chunk_policy,
        "chunk_size": storage_config.chunk_size,
        "chunk_overlap": storage_config.chunk_overlap,
        "source_markdown_sha256": extraction["extracted_markdown_sha256"],
        "chunk_count": len(chunk_items),
        "chunks": chunk_items,
        "created_at": now,
        "updated_at": now,
    }
    return store.save_chunk_set(chunk_set, chunk_texts=private_text)


def chunk_text(
    text: str,
    *,
    chunk_size: int,
    chunk_overlap: int,
) -> list[dict[str, Any]]:
    validate_chunk_policy(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    if not text:
        return []

    chunks: list[dict[str, Any]] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(
            {
                "start_offset": start,
                "end_offset": end,
                "text": text[start:end],
            }
        )
        if end == len(text):
            break
        start = end - chunk_overlap
    return chunks


def validate_chunk_policy(
    *,
    chunk_size: int,
    chunk_overlap: int,
) -> None:
    if chunk_size <= 0:
        raise ChunkingError(
            status_code=500,
            error_code="cx.chunk_policy_invalid",
            detail="chunk_size must be positive.",
        )
    if chunk_overlap < 0:
        raise ChunkingError(
            status_code=500,
            error_code="cx.chunk_policy_invalid",
            detail="chunk_overlap must be non-negative.",
        )
    if chunk_overlap >= chunk_size:
        raise ChunkingError(
            status_code=500,
            error_code="cx.chunk_policy_invalid",
            detail="chunk_overlap must be smaller than chunk_size.",
        )


def build_chunk_items(
    chunks: list[dict[str, Any]],
    *,
    document_id: str,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    public_chunks: list[dict[str, Any]] = []
    private_text: dict[str, str] = {}
    for ordinal, chunk in enumerate(chunks):
        text = chunk["text"]
        text_sha256 = sha256_text(text)
        chunk_id = str(uuid5(NAMESPACE_URL, f"cx-chunk:{document_id}:{ordinal}:{text_sha256}"))
        public_chunks.append(
            {
                "chunk_id": chunk_id,
                "ordinal": ordinal,
                "start_offset": chunk["start_offset"],
                "end_offset": chunk["end_offset"],
                "char_count": len(text),
                "text_sha256": text_sha256,
                "text_preview": text[:120],
            }
        )
        private_text[chunk_id] = text
    return public_chunks, private_text


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


def _chunking_problem_response(
    request: Request,
    exc: ChunkingError,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Content chunking request failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/content-chunking-failed",
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
