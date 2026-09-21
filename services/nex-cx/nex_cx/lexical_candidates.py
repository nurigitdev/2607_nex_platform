from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_cx.access_context import CxAccessContext


LEXICAL_CANDIDATE_SCHEMA_VERSION = "cx_lexical_candidate.v1"
DEFAULT_BM25_K1 = 1.2
DEFAULT_BM25_B = 0.75
MAX_QUERY_TERMS = 64
MAX_CANDIDATE_LIMIT = 500


class LexicalCandidateStoreError(RuntimeError):
    def __init__(self, *, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


class PostgresLexicalCandidateStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def search(
        self,
        *,
        access_context: CxAccessContext,
        query_terms: Sequence[str],
        content_object_ids: Sequence[str] | None = None,
        limit: int,
        k1: float = DEFAULT_BM25_K1,
        b: float = DEFAULT_BM25_B,
    ) -> list[dict[str, Any]]:
        terms = _normalize_query_terms(query_terms)
        scoped_ids = _normalize_content_ids(content_object_ids)
        _validate_search_parameters(limit=limit, k1=k1, b=b)
        if not terms:
            return []
        try:
            with self._session_factory() as session:
                rows = session.execute(
                    text(_BM25_SQL),
                    {
                        "tenant_id": access_context.tenant_id,
                        "owner_subject_id": access_context.subject_id,
                        "scope_all": scoped_ids is None,
                        "content_object_ids": scoped_ids or [],
                        "query_terms": terms,
                        "k1": k1,
                        "b": b,
                        "limit": limit,
                    },
                ).mappings().all()
        except SQLAlchemyError as exc:
            raise LexicalCandidateStoreError(
                error_code="CX_LEXICAL_SEARCH_UNAVAILABLE",
                detail="Owner-scoped lexical candidate search is unavailable.",
            ) from exc
        return [_candidate_from_row(row) for row in rows]


_BM25_SQL = """
WITH eligible_chunks AS (
    SELECT
        chunk.chunk_id,
        chunk.chunk_set_id,
        chunk.content_object_id,
        chunk.ordinal,
        chunk.start_offset,
        chunk.end_offset,
        chunk.text_sha256,
        chunk.text_preview
    FROM cx_chunks AS chunk
    JOIN cx_content_objects AS content
      ON content.content_object_id = chunk.content_object_id
    WHERE content.lifecycle_status = 'ACTIVE'
      AND content.tenant_ref_type = 'oa.tenant'
      AND content.tenant_ref_id = :tenant_id
      AND content.owner_subject_ref_type = 'oa.user'
      AND content.owner_subject_ref_id = :owner_subject_id
      AND (
          :scope_all
          OR chunk.content_object_id = ANY(CAST(:content_object_ids AS uuid[]))
      )
),
chunk_lengths AS (
    SELECT
        eligible.*,
        COALESCE(SUM(posting.occurrence_count), 0)::double precision AS chunk_length
    FROM eligible_chunks AS eligible
    LEFT JOIN cx_lexical_postings AS posting
      ON posting.chunk_id = eligible.chunk_id
    GROUP BY
        eligible.chunk_id,
        eligible.chunk_set_id,
        eligible.content_object_id,
        eligible.ordinal,
        eligible.start_offset,
        eligible.end_offset,
        eligible.text_sha256,
        eligible.text_preview
),
corpus AS (
    SELECT
        COUNT(*)::double precision AS corpus_size,
        GREATEST(AVG(chunk_length), 1.0) AS average_chunk_length
    FROM chunk_lengths
),
matched AS (
    SELECT
        chunk.*,
        term.term,
        posting.occurrence_count::double precision AS term_frequency,
        COUNT(*) OVER (PARTITION BY term.term)::double precision
            AS document_frequency,
        corpus.corpus_size,
        corpus.average_chunk_length
    FROM chunk_lengths AS chunk
    JOIN cx_lexical_postings AS posting
      ON posting.chunk_id = chunk.chunk_id
    JOIN cx_lexical_terms AS term
      ON term.lexical_term_id = posting.lexical_term_id
     AND term.chunk_set_id = chunk.chunk_set_id
    CROSS JOIN corpus
    WHERE term.term = ANY(CAST(:query_terms AS text[]))
),
scored AS (
    SELECT
        chunk_id,
        chunk_set_id,
        content_object_id,
        ordinal,
        start_offset,
        end_offset,
        text_sha256,
        text_preview,
        ARRAY_AGG(DISTINCT term ORDER BY term) AS matched_terms,
        SUM(
            LN(
                1.0 + (
                    corpus_size - document_frequency + 0.5
                ) / (document_frequency + 0.5)
            ) * (
                term_frequency * (:k1 + 1.0)
            ) / (
                term_frequency + :k1 * (
                    1.0 - :b + :b * chunk_length / average_chunk_length
                )
            )
        ) AS bm25_score
    FROM matched
    GROUP BY
        chunk_id,
        chunk_set_id,
        content_object_id,
        ordinal,
        start_offset,
        end_offset,
        text_sha256,
        text_preview
)
SELECT *
FROM scored
WHERE bm25_score > 0.0
ORDER BY bm25_score DESC, ordinal ASC, chunk_id ASC
LIMIT :limit
"""


def _candidate_from_row(row: Any) -> dict[str, Any]:
    return {
        "lexical_candidate_schema_version": LEXICAL_CANDIDATE_SCHEMA_VERSION,
        "candidate_source": "postgresql_bm25",
        "content_object_id": str(row["content_object_id"]),
        "chunk_set_id": str(row["chunk_set_id"]),
        "chunk_id": str(row["chunk_id"]),
        "ordinal": int(row["ordinal"]),
        "start_offset": int(row["start_offset"]),
        "end_offset": int(row["end_offset"]),
        "text_sha256": str(row["text_sha256"]),
        "text_preview": str(row["text_preview"]),
        "matched_terms": list(row["matched_terms"]),
        "bm25_score": round(float(row["bm25_score"]), 8),
    }


def _normalize_query_terms(values: Sequence[str]) -> list[str]:
    if isinstance(values, str):
        raise _invalid_query()
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise _invalid_query()
        term = value.strip().lower()
        if term not in seen:
            normalized.append(term)
            seen.add(term)
    if len(normalized) > MAX_QUERY_TERMS:
        raise _invalid_query()
    return normalized


def _normalize_content_ids(values: Sequence[str] | None) -> list[str] | None:
    if values is None:
        return None
    if isinstance(values, str):
        raise _invalid_scope()
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise _invalid_scope()
        content_id = value.strip()
        if content_id not in seen:
            normalized.append(content_id)
            seen.add(content_id)
    return normalized


def _validate_search_parameters(*, limit: int, k1: float, b: float) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_CANDIDATE_LIMIT:
        raise LexicalCandidateStoreError(
            error_code="CX_LEXICAL_LIMIT_INVALID",
            detail=f"Lexical candidate limit must be between 1 and {MAX_CANDIDATE_LIMIT}.",
        )
    if isinstance(k1, bool) or not isinstance(k1, int | float) or k1 <= 0:
        raise LexicalCandidateStoreError(
            error_code="CX_BM25_POLICY_INVALID",
            detail="BM25 k1 must be greater than zero.",
        )
    if isinstance(b, bool) or not isinstance(b, int | float) or not 0 <= b <= 1:
        raise LexicalCandidateStoreError(
            error_code="CX_BM25_POLICY_INVALID",
            detail="BM25 b must be between zero and one.",
        )


def _invalid_query() -> LexicalCandidateStoreError:
    return LexicalCandidateStoreError(
        error_code="CX_LEXICAL_QUERY_INVALID",
        detail="Lexical query terms must be a bounded list of non-empty strings.",
    )


def _invalid_scope() -> LexicalCandidateStoreError:
    return LexicalCandidateStoreError(
        error_code="CX_LEXICAL_SCOPE_INVALID",
        detail="Lexical content scope must contain non-empty identifiers.",
    )
