from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
    validate_authorization_header,
)

from nex_cx.ingestion import ContentIngestionStore, CxStorageConfig, build_storage_config

SUPPORTED_TOKENIZERS = {"mecab_ko", "korean_mixed_v1"}
KOREAN_MIXED_PATTERN = re.compile(r"[가-힣]+|[A-Za-z0-9]+")
MECAB_DICTIONARY_ENV = "MECAB_DICDIR"


@dataclass(frozen=True)
class LexicalIndexError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False


class TokenizerUnavailable(Exception):
    pass


def register_lexical_index_routes(
    app: FastAPI,
    *,
    store: ContentIngestionStore,
    storage_config: CxStorageConfig | None = None,
) -> None:
    config = storage_config or build_storage_config()

    @app.post("/api/v1/documents/{document_id}/lexical-index/run", response_model=None)
    def run_lexical_index(
        document_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_cx_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        try:
            return build_and_store_lexical_index(
                document_id,
                store=store,
                storage_config=config,
                request_id=request_id_from_headers(request),
                trace_id=trace_id_from_headers(request),
            )
        except LexicalIndexError as exc:
            return _lexical_problem_response(request, exc)

    @app.get("/api/v1/documents/{document_id}/lexical-index", response_model=None)
    def get_lexical_index(
        document_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_cx_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        lexical_index = store.get_lexical_index(document_id)
        if lexical_index is None:
            return _lexical_problem_response(
                request,
                LexicalIndexError(
                    status_code=404,
                    error_code="cx.lexical_index_not_found",
                    detail=f"Lexical index was not found: {document_id}",
                ),
            )
        return lexical_index


def build_and_store_lexical_index(
    document_id: str,
    *,
    store: ContentIngestionStore,
    storage_config: CxStorageConfig,
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    chunk_set = store.get_chunk_set(document_id)
    if chunk_set is None:
        raise LexicalIndexError(
            status_code=404,
            error_code="cx.chunk_set_not_found",
            detail=f"Chunk set was not found: {document_id}",
        )

    chunk_texts = ordered_chunk_texts(chunk_set, store)
    lexical_index = build_lexical_index(
        document_id=document_id,
        chunk_set=chunk_set,
        chunk_texts=chunk_texts,
        tokenizer_requested=storage_config.bm25_tokenizer,
        tokenizer_fallback=storage_config.bm25_tokenizer_fallback,
        request_id=request_id,
        trace_id=trace_id,
    )
    return store.save_lexical_index(lexical_index)


def ordered_chunk_texts(
    chunk_set: dict[str, Any],
    store: ContentIngestionStore,
) -> list[tuple[dict[str, Any], str]]:
    ordered_chunks = sorted(chunk_set["chunks"], key=lambda chunk: chunk["ordinal"])
    result: list[tuple[dict[str, Any], str]] = []
    for chunk in ordered_chunks:
        text = store.get_chunk_text(chunk["chunk_id"])
        if text is None:
            raise LexicalIndexError(
                status_code=409,
                error_code="cx.chunk_text_unavailable",
                detail=f"Chunk text was not found: {chunk['chunk_id']}",
                retryable=True,
            )
        result.append((chunk, text))
    return result


def build_lexical_index(
    *,
    document_id: str,
    chunk_set: dict[str, Any],
    chunk_texts: list[tuple[dict[str, Any], str]],
    tokenizer_requested: str,
    tokenizer_fallback: str,
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    terms_by_chunk: list[tuple[dict[str, Any], list[str]]] = []
    tokenizer_used = tokenizer_requested
    fallback_used = False
    try:
        for chunk, text in chunk_texts:
            terms_by_chunk.append((chunk, tokenize_with(tokenizer_requested, text)))
    except TokenizerUnavailable:
        fallback_used = True
        tokenizer_used = tokenizer_fallback
        try:
            terms_by_chunk = [
                (chunk, tokenize_with(tokenizer_fallback, text))
                for chunk, text in chunk_texts
            ]
        except TokenizerUnavailable as exc:
            raise LexicalIndexError(
                status_code=500,
                error_code="cx.tokenizer_unavailable",
                detail=f"No configured tokenizer is available: {tokenizer_fallback}",
            ) from exc

    postings = build_postings(terms_by_chunk)
    now = _utc_now()
    return {
        "lexical_index_schema_version": "cx_lexical_index.v1",
        "document_id": document_id,
        "trace_id": trace_id,
        "request_id": request_id,
        "tokenizer_requested": tokenizer_requested,
        "tokenizer_used": tokenizer_used,
        "tokenizer_fallback": tokenizer_fallback,
        "fallback_used": fallback_used,
        "tokenizer_profile": build_tokenizer_profile(
            tokenizer_requested=tokenizer_requested,
            tokenizer_used=tokenizer_used,
            tokenizer_fallback=tokenizer_fallback,
            fallback_used=fallback_used,
        ),
        "chunk_count": chunk_set["chunk_count"],
        "unique_token_count": len(postings),
        "postings": postings,
        "created_at": now,
        "updated_at": now,
    }


def tokenize_with(tokenizer: str, text: str) -> list[str]:
    if tokenizer not in SUPPORTED_TOKENIZERS:
        raise TokenizerUnavailable(f"Unsupported tokenizer: {tokenizer}")
    if tokenizer == "mecab_ko":
        return _mecab_ko_tokens(text)
    return korean_mixed_v1_tokens(text)


def query_terms_for_lexical_index(
    lexical_index: dict[str, Any],
    query_text: str,
) -> set[str]:
    tokenizer_used = _tokenizer_name_or_default(
        lexical_index.get("tokenizer_used"),
        default="korean_mixed_v1",
    )
    tokenizer_fallback = _tokenizer_name_or_default(
        lexical_index.get("tokenizer_fallback"),
        default="korean_mixed_v1",
    )
    try:
        return set(tokenize_with(tokenizer_used, query_text))
    except TokenizerUnavailable:
        try:
            return set(tokenize_with(tokenizer_fallback, query_text))
        except TokenizerUnavailable:
            return set(korean_mixed_v1_tokens(query_text))


def build_tokenizer_profile(
    *,
    tokenizer_requested: str,
    tokenizer_used: str,
    tokenizer_fallback: str,
    fallback_used: bool,
) -> dict[str, Any]:
    return {
        "bm25_tokenizer_requested": tokenizer_requested,
        "bm25_tokenizer": tokenizer_used,
        "bm25_tokenizer_fallback": tokenizer_fallback,
        "fallback_used": fallback_used,
        "query_tokenizer_policy": "match_index_tokenizer_with_fallback",
        "dictionary_profile": dictionary_profile_for_tokenizer(tokenizer_used),
        "dictionary_path_env": MECAB_DICTIONARY_ENV if tokenizer_used == "mecab_ko" else None,
        "dictionary_path_configured": bool(os.getenv(MECAB_DICTIONARY_ENV))
        if tokenizer_used == "mecab_ko"
        else False,
    }


def dictionary_profile_for_tokenizer(tokenizer: str) -> str:
    if tokenizer == "mecab_ko":
        return "mecab-ko-dic"
    if tokenizer == "korean_mixed_v1":
        return "none_regex_korean_mixed_v1"
    return "unknown"


def korean_mixed_v1_tokens(text: str) -> list[str]:
    return [
        match.group(0).lower()
        for match in KOREAN_MIXED_PATTERN.finditer(text)
        if match.group(0).strip()
    ]


def build_postings(
    terms_by_chunk: list[tuple[dict[str, Any], list[str]]],
) -> list[dict[str, Any]]:
    postings: dict[str, dict[str, Any]] = {}
    for chunk, terms in terms_by_chunk:
        counts: dict[str, int] = {}
        for term in terms:
            counts[term] = counts.get(term, 0) + 1
        for term, count in counts.items():
            posting = postings.setdefault(
                term,
                {
                    "term": term,
                    "document_frequency": 0,
                    "occurrences": [],
                },
            )
            posting["document_frequency"] += 1
            posting["occurrences"].append(
                {
                    "chunk_id": chunk["chunk_id"],
                    "ordinal": chunk["ordinal"],
                    "count": count,
                }
            )
    return sorted(postings.values(), key=lambda item: item["term"])


def _mecab_ko_tokens(text: str) -> list[str]:
    try:
        import MeCab  # type: ignore[import-not-found]
    except ImportError as exc:
        raise TokenizerUnavailable("MeCab ko tokenizer is not installed.") from exc

    tagger = MeCab.Tagger()
    parsed = tagger.parse(text)
    if not parsed:
        return []
    tokens = []
    for line in parsed.splitlines():
        if line == "EOS":
            continue
        token = line.split("\t", maxsplit=1)[0].strip().lower()
        if token:
            tokens.append(token)
    return tokens


def _tokenizer_name_or_default(value: Any, *, default: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


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


def _lexical_problem_response(
    request: Request,
    exc: LexicalIndexError,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Lexical index request failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/lexical-index-failed",
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
