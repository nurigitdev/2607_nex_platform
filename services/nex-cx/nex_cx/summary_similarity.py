from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import math
import re
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_cx.access_context import CxAccessContext
from nex_cx.private_content import sha256_private_vector
from nex_runtime import (
    build_engine,
    build_session_factory,
    database_pool_settings,
    service_database_settings,
)


SUMMARY_SIMILARITY_RESULT_SCHEMA_VERSION = "cx_summary_similarity_result.v1"
SUMMARY_SIMILARITY_CANDIDATE_SCHEMA_VERSION = "cx_summary_similarity_candidate.v1"
MAX_SUMMARY_SIMILARITY_LIMIT = 100
MAX_SUMMARY_VECTOR_DIMENSION = 8192
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class SummarySimilarityError(RuntimeError):
    def __init__(
        self,
        *,
        status_code: int,
        error_code: str,
        detail: str,
        retryable: bool = False,
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.error_code = error_code
        self.detail = detail
        self.retryable = retryable


class PostgresSummarySimilarityStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

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
        vector = _normalize_query_vector(query_vector)
        profile = _query_sha256(profile_fingerprint)
        _validate_limit(limit)
        threshold = _minimum_score(minimum_score)
        excluded_id = _optional_uuid(exclude_content_object_id)
        statement = text(_search_sql(len(vector)))
        try:
            with self._session_factory() as session:
                rows = session.execute(
                    statement,
                    {
                        "tenant_id": access_context.tenant_id,
                        "owner_subject_id": access_context.subject_id,
                        "profile_fingerprint": profile,
                        "vector_dimension": len(vector),
                        "query_embedding": _serialize_pgvector(vector),
                        "minimum_score": threshold,
                        "exclude_content_object_id": excluded_id,
                        "limit": limit,
                    },
                ).mappings().all()
        except SQLAlchemyError as exc:
            raise SummarySimilarityError(
                status_code=503,
                error_code="CX_SUMMARY_SIMILARITY_UNAVAILABLE",
                detail="Owner-scoped summary similarity search is unavailable.",
                retryable=True,
            ) from exc

        candidates = [
            _candidate_from_row(row, rank=rank, profile_fingerprint=profile)
            for rank, row in enumerate(rows, start=1)
        ]
        return {
            "summary_similarity_result_schema_version": (
                SUMMARY_SIMILARITY_RESULT_SCHEMA_VERSION
            ),
            "candidate_source": "postgresql_pgvector_summary",
            "metric": "cosine",
            "query_embedding_sha256": sha256_private_vector(vector),
            "query_dimension": len(vector),
            "profile_fingerprint": profile,
            "minimum_score": threshold,
            "excluded_content_object_id": excluded_id,
            "candidate_count": len(candidates),
            "candidates": candidates,
        }


def build_summary_similarity_store(
    *,
    database_env: str = "NEX_CX_DATABASE_URL",
    environ: Mapping[str, str] | None = None,
    workload: str = "api",
) -> PostgresSummarySimilarityStore:
    settings = service_database_settings(
        service_id="nex-cx",
        database_env=database_env,
        environ=environ,
    )
    if settings.vector_database_url is None:
        raise SummarySimilarityError(
            status_code=500,
            error_code="CX_VECTOR_DATABASE_CONFIG_INVALID",
            detail="CX vector database routing is unavailable.",
        )
    pool = database_pool_settings("nex-cx", workload=workload, environ=environ)
    engine = build_engine(settings.vector_database_url, pool_settings=pool)
    return PostgresSummarySimilarityStore(build_session_factory(engine))


def _search_sql(vector_dimension: int) -> str:
    distance = (
        "summary_vector.embedding::halfvec(2560) "
        "<=> CAST(:query_embedding AS halfvec(2560))"
        if vector_dimension == 2560
        else "summary_vector.embedding <=> CAST(:query_embedding AS vector)"
    )
    return f"""
WITH eligible AS (
    SELECT
        summary_vector.summary_vector_id,
        summary_vector.summary_embedding_id,
        summary_vector.document_summary_id,
        summary_vector.content_object_id,
        summary_vector.summary_text_sha256,
        summary_vector.embedding_sha256,
        summary_vector.vector_dimension,
        content.original_filename,
        content.content_type,
        summary.summary_char_count,
        {distance} AS distance
    FROM cx_summary_vectors AS summary_vector
    JOIN cx_document_summary_embeddings AS summary_embedding
      ON summary_embedding.summary_embedding_id = summary_vector.summary_embedding_id
    JOIN cx_document_summaries AS summary
      ON summary.document_summary_id = summary_vector.document_summary_id
    JOIN cx_content_objects AS content
      ON content.content_object_id = summary_vector.content_object_id
    WHERE content.lifecycle_status = 'ACTIVE'
      AND content.tenant_ref_type = 'oa.tenant'
      AND content.tenant_ref_id = :tenant_id
      AND content.owner_subject_ref_type = 'oa.user'
      AND content.owner_subject_ref_id = :owner_subject_id
      AND summary.status = 'READY'
      AND summary_embedding.status = 'READY'
      AND summary.summary_text_sha256 = summary_vector.summary_text_sha256
      AND summary_embedding.document_summary_id = summary_vector.document_summary_id
      AND summary_embedding.provider_alias = summary_vector.provider_alias
      AND summary_embedding.model_profile_id = summary_vector.model_profile_id
      AND summary_embedding.model_revision = summary_vector.model_revision
      AND summary_embedding.deployment_id = summary_vector.deployment_id
      AND summary_embedding.embedding_sha256 = summary_vector.embedding_sha256
      AND summary_embedding.vector_dimension = summary_vector.vector_dimension
      AND summary_vector.profile_fingerprint = :profile_fingerprint
      AND summary_vector.vector_dimension = :vector_dimension
      AND summary.document_summary_id = (
          SELECT latest.document_summary_id
          FROM cx_document_summaries AS latest
          WHERE latest.content_object_id = summary_vector.content_object_id
          ORDER BY latest.updated_at DESC, latest.document_summary_id DESC
          LIMIT 1
      )
      AND (
          :exclude_content_object_id IS NULL
          OR summary_vector.content_object_id <> CAST(:exclude_content_object_id AS uuid)
      )
),
scored AS (
    SELECT *, 1.0 - distance AS similarity_score
    FROM eligible
)
SELECT *
FROM scored
WHERE similarity_score >= :minimum_score
ORDER BY similarity_score DESC, content_object_id, document_summary_id
LIMIT :limit
"""


def _candidate_from_row(
    row: Mapping[str, Any],
    *,
    rank: int,
    profile_fingerprint: str,
) -> dict[str, Any]:
    identifiers = {
        field: _required_uuid(row.get(field), field)
        for field in (
            "content_object_id",
            "document_summary_id",
            "summary_embedding_id",
        )
    }
    summary_hash = _sha256(row.get("summary_text_sha256"), "summary_text_sha256")
    embedding_hash = _sha256(row.get("embedding_sha256"), "embedding_sha256")
    dimension = _positive_integer(row.get("vector_dimension"), "vector_dimension")
    summary_char_count = _non_negative_integer(
        row.get("summary_char_count"),
        "summary_char_count",
    )
    score = _score(row.get("similarity_score"), "similarity_score")
    distance = _distance(row.get("distance"))
    filename = _required_text(row.get("original_filename"), "original_filename", 512)
    content_type = _required_text(row.get("content_type"), "content_type", 160)
    return {
        "summary_similarity_candidate_schema_version": (
            SUMMARY_SIMILARITY_CANDIDATE_SCHEMA_VERSION
        ),
        "candidate_rank": rank,
        **identifiers,
        "original_filename": filename,
        "content_type": content_type,
        "summary_text_sha256": summary_hash,
        "summary_char_count": summary_char_count,
        "embedding_sha256": embedding_hash,
        "vector_dimension": dimension,
        "profile_fingerprint": profile_fingerprint,
        "similarity_score": round(score, 8),
        "cosine_distance": round(distance, 8),
    }


def _normalize_query_vector(value: Sequence[float]) -> tuple[float, ...]:
    if (
        isinstance(value, (str, bytes, bytearray))
        or not isinstance(value, Sequence)
        or not 1 <= len(value) <= MAX_SUMMARY_VECTOR_DIMENSION
    ):
        raise _invalid_query()
    normalized: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int | float):
            raise _invalid_query()
        number = float(item)
        if not math.isfinite(number):
            raise _invalid_query()
        normalized.append(number)
    return tuple(normalized)


def _validate_limit(value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_SUMMARY_SIMILARITY_LIMIT:
        raise SummarySimilarityError(
            status_code=422,
            error_code="CX_SUMMARY_SIMILARITY_LIMIT_INVALID",
            detail=(
                "Summary similarity limit must be between 1 and "
                f"{MAX_SUMMARY_SIMILARITY_LIMIT}."
            ),
        )


def _score(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _result_invalid(f"{field} must be numeric.")
    score = float(value)
    if not math.isfinite(score) or not -1.0 <= score <= 1.0:
        raise _result_invalid(f"{field} must be between -1 and 1.")
    return score


def _distance(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _result_invalid("distance must be numeric.")
    distance = float(value)
    if not math.isfinite(distance) or not 0.0 <= distance <= 2.0:
        raise _result_invalid("distance must be between 0 and 2.")
    return distance


def _optional_uuid(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise SummarySimilarityError(
            status_code=422,
            error_code="CX_SUMMARY_SIMILARITY_SCOPE_INVALID",
            detail="Excluded content object ID must be a UUID.",
        ) from exc


def _required_uuid(value: Any, field: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _result_invalid(f"{field} must be a UUID.") from exc


def _required_text(value: Any, field: str, max_length: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > max_length:
        raise _result_invalid(f"{field} must be bounded non-empty text.")
    return value.strip()


def _sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise _result_invalid(f"{field} must be a lowercase SHA-256 digest.")
    return value


def _query_sha256(value: Any) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise SummarySimilarityError(
            status_code=422,
            error_code="CX_SUMMARY_SIMILARITY_PROFILE_INVALID",
            detail="Summary similarity profile fingerprint must be a SHA-256 digest.",
        )
    return value


def _minimum_score(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _invalid_score()
    score = float(value)
    if not math.isfinite(score) or not -1.0 <= score <= 1.0:
        raise _invalid_score()
    return score


def _positive_integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _result_invalid(f"{field} must be a positive integer.")
    return value


def _non_negative_integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _result_invalid(f"{field} must be a non-negative integer.")
    return value


def _serialize_pgvector(vector: Sequence[float]) -> str:
    return json.dumps(list(vector), ensure_ascii=True, separators=(",", ":"))


def _invalid_query() -> SummarySimilarityError:
    return SummarySimilarityError(
        status_code=422,
        error_code="CX_SUMMARY_SIMILARITY_QUERY_INVALID",
        detail="Summary similarity query vector must contain bounded finite numbers.",
    )


def _invalid_score() -> SummarySimilarityError:
    return SummarySimilarityError(
        status_code=422,
        error_code="CX_SUMMARY_SIMILARITY_SCORE_INVALID",
        detail="Minimum summary similarity score must be between -1 and 1.",
    )


def _result_invalid(detail: str) -> SummarySimilarityError:
    return SummarySimilarityError(
        status_code=502,
        error_code="CX_SUMMARY_SIMILARITY_RESULT_INVALID",
        detail=detail,
        retryable=True,
    )
