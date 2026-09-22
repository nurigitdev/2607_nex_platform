from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import math
from typing import Any, Protocol

from nex_cx.access_context import CxAccessContext
from nex_cx.lexical_candidates import LexicalCandidateStoreError
from nex_cx.lexical_index import (
    TokenizerUnavailable,
    build_tokenizer_profile,
    tokenize_with,
)
from nex_cx.retrieval_permissions import (
    build_permission_snapshot,
    filter_retrieval_document_scope,
)
from nex_cx.vector_candidates import (
    VectorCandidateError,
    collect_fresh_vector_candidates,
)
from nex_cx.vector_index_repository import VectorIndexRepository
from nex_cx.vector_retrieval_guard import VectorSearchAdapter


HYBRID_CANDIDATE_SET_SCHEMA_VERSION = "cx_hybrid_candidate_set.v1"
DEFAULT_TOKENIZER = "mecab_ko"
DEFAULT_TOKENIZER_FALLBACK = "korean_mixed_v1"
MAX_QUERY_TEXT_LENGTH = 16_000
MAX_LEXICAL_CANDIDATE_LIMIT = 500
MAX_VECTOR_CANDIDATE_LIMIT = 100


class LexicalCandidateSearcher(Protocol):
    def search(
        self,
        *,
        access_context: CxAccessContext,
        query_terms: Sequence[str],
        content_object_ids: Sequence[str] | None,
        limit: int,
    ) -> list[dict[str, Any]]: ...


class HybridCandidateOrchestrationError(RuntimeError):
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


def orchestrate_permission_filtered_candidates(
    *,
    access_context: CxAccessContext,
    query_text: str,
    requested_document_ids: Sequence[str],
    content_objects: Mapping[str, object],
    lexical_store: LexicalCandidateSearcher,
    vector_targets_by_document_id: Mapping[str, Mapping[str, Any]],
    query_vector: Sequence[float] | None,
    vector_repository: VectorIndexRepository,
    vector_store: VectorSearchAdapter,
    lexical_limit: int = 80,
    vector_limit: int = 80,
    scope_type: str = "explicit_document_ids",
    tokenizer_requested: str = DEFAULT_TOKENIZER,
    tokenizer_fallback: str = DEFAULT_TOKENIZER_FALLBACK,
) -> dict[str, Any]:
    query = _query_text(query_text)
    _candidate_limit(
        lexical_limit,
        maximum=MAX_LEXICAL_CANDIDATE_LIMIT,
        field="lexical_limit",
    )
    _candidate_limit(
        vector_limit,
        maximum=MAX_VECTOR_CANDIDATE_LIMIT,
        field="vector_limit",
    )
    if not isinstance(content_objects, Mapping) or not isinstance(
        vector_targets_by_document_id,
        Mapping,
    ):
        raise _invalid_request("Candidate source mappings are invalid.")

    permission_filter = filter_retrieval_document_scope(
        access_context=access_context,
        requested_document_ids=requested_document_ids,
        content_objects=content_objects,
        require_all_visible=True,
    )
    permission_snapshot = build_permission_snapshot(
        access_context=access_context,
        scope_type=scope_type,
        filter_result=permission_filter,
    )
    visible_ids = permission_filter["visible_document_ids"]
    visible_id_set = frozenset(visible_ids)

    query_terms, tokenizer_profile = _tokenize_query(
        query,
        tokenizer_requested=tokenizer_requested,
        tokenizer_fallback=tokenizer_fallback,
    )
    try:
        lexical_candidates = lexical_store.search(
            access_context=access_context,
            query_terms=query_terms,
            content_object_ids=visible_ids,
            limit=lexical_limit,
        )
    except LexicalCandidateStoreError as exc:
        raise HybridCandidateOrchestrationError(
            status_code=503,
            error_code=exc.error_code,
            detail="Owner-scoped lexical candidate search is unavailable.",
            retryable=True,
        ) from exc
    except Exception as exc:
        raise _candidate_search_unavailable() from exc
    lexical_candidates = _validated_lexical_candidates(
        lexical_candidates,
        visible_document_ids=visible_id_set,
        limit=lexical_limit,
    )

    selected_vector_targets, missing_target_count = _selected_vector_targets(
        visible_ids,
        vector_targets_by_document_id,
    )
    vector_result: dict[str, Any]
    if query_vector is None:
        vector_result = _empty_vector_result(status="QUERY_VECTOR_NOT_PROVIDED")
    else:
        try:
            vector_result = collect_fresh_vector_candidates(
                access_context=access_context,
                targets=selected_vector_targets,
                query_vector=query_vector,
                limit=vector_limit,
                repository=vector_repository,
                vector_store=vector_store,
            )
        except VectorCandidateError as exc:
            raise _vector_error(exc) from exc
        _validate_vector_scope(
            vector_result,
            visible_document_ids=visible_id_set,
        )
        vector_result = {
            **vector_result,
            "status": _vector_status(
                vector_result,
                missing_target_count=missing_target_count,
            ),
        }

    return {
        "hybrid_candidate_set_schema_version": HYBRID_CANDIDATE_SET_SCHEMA_VERSION,
        "permission_policy": permission_snapshot["policy_version"],
        "permission_enforced_before_candidates": True,
        "stage_order": [
            "permission_filter",
            "query_tokenization",
            "owner_scoped_bm25",
            "fresh_owner_scoped_vector",
        ],
        "query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
        "query_term_count": len(query_terms),
        "tokenizer_profile": tokenizer_profile,
        "permission_snapshot": permission_snapshot,
        "lexical_candidates": {
            "candidate_source": "postgresql_bm25",
            "candidate_count": len(lexical_candidates),
            "candidates": lexical_candidates,
        },
        "vector_candidates": {
            **vector_result,
            "missing_target_count": missing_target_count,
        },
    }


def _query_text(value: object) -> str:
    if not isinstance(value, str):
        raise _invalid_request("query_text must be a non-empty string.")
    normalized = value.strip()
    if not normalized or len(normalized) > MAX_QUERY_TEXT_LENGTH:
        raise _invalid_request("query_text must be a non-empty string.")
    return normalized


def _candidate_limit(value: object, *, maximum: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise _invalid_request(f"{field} must be between 1 and {maximum}.")
    return value


def _tokenize_query(
    query_text: str,
    *,
    tokenizer_requested: str,
    tokenizer_fallback: str,
) -> tuple[list[str], dict[str, Any]]:
    tokenizer_used = tokenizer_requested
    fallback_used = False
    try:
        terms = tokenize_with(tokenizer_requested, query_text)
    except TokenizerUnavailable:
        tokenizer_used = tokenizer_fallback
        fallback_used = True
        try:
            terms = tokenize_with(tokenizer_fallback, query_text)
        except TokenizerUnavailable as exc:
            raise HybridCandidateOrchestrationError(
                status_code=503,
                error_code="CX_QUERY_TOKENIZER_UNAVAILABLE",
                detail="No configured query tokenizer is available.",
                retryable=False,
            ) from exc
    normalized_terms = sorted({term.strip().lower() for term in terms if term.strip()})
    return normalized_terms, build_tokenizer_profile(
        tokenizer_requested=tokenizer_requested,
        tokenizer_used=tokenizer_used,
        tokenizer_fallback=tokenizer_fallback,
        fallback_used=fallback_used,
    )


def _validated_lexical_candidates(
    candidates: object,
    *,
    visible_document_ids: frozenset[str],
    limit: int,
) -> list[dict[str, Any]]:
    if (
        isinstance(candidates, (str, bytes))
        or not isinstance(candidates, Sequence)
        or len(candidates) > limit
    ):
        raise _candidate_result_invalid()
    validated: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise _candidate_result_invalid()
        content_id = candidate.get("content_object_id")
        chunk_id = candidate.get("chunk_id")
        score = candidate.get("bm25_score")
        if (
            not isinstance(content_id, str)
            or content_id not in visible_document_ids
            or not isinstance(chunk_id, str)
            or not chunk_id
            or isinstance(score, bool)
            or not isinstance(score, int | float)
            or not math.isfinite(float(score))
            or float(score) < 0.0
        ):
            raise _candidate_result_invalid()
        validated.append(dict(candidate))
    return validated


def _selected_vector_targets(
    visible_document_ids: Sequence[str],
    targets_by_document_id: Mapping[str, Mapping[str, Any]],
) -> tuple[list[Mapping[str, Any]], int]:
    selected: list[Mapping[str, Any]] = []
    missing_count = 0
    for document_id in visible_document_ids:
        target = targets_by_document_id.get(document_id)
        if target is None:
            missing_count += 1
            continue
        if (
            not isinstance(target, Mapping)
            or target.get("content_object_id") != document_id
        ):
            raise _candidate_result_invalid()
        selected.append(target)
    return selected, missing_count


def _validate_vector_scope(
    result: object,
    *,
    visible_document_ids: frozenset[str],
) -> None:
    if not isinstance(result, Mapping):
        raise _candidate_result_invalid()
    candidates = result.get("candidates")
    if isinstance(candidates, (str, bytes)) or not isinstance(candidates, Sequence):
        raise _candidate_result_invalid()
    for candidate in candidates:
        if (
            not isinstance(candidate, Mapping)
            or candidate.get("content_object_id") not in visible_document_ids
        ):
            raise _candidate_result_invalid()


def _vector_status(
    result: Mapping[str, Any],
    *,
    missing_target_count: int,
) -> str:
    admitted = result.get("admitted_index_count")
    excluded = result.get("excluded_index_count")
    if admitted:
        return "READY" if not excluded and not missing_target_count else "DEGRADED"
    return "BM25_ONLY"


def _empty_vector_result(*, status: str) -> dict[str, Any]:
    return {
        "vector_candidate_result_schema_version": "cx_vector_candidate_result.v1",
        "candidate_source": "postgresql_pgvector",
        "status": status,
        "query_dimension": None,
        "requested_index_count": 0,
        "admitted_index_count": 0,
        "excluded_index_count": 0,
        "exclusion_counts": {},
        "candidate_count": 0,
        "candidates": [],
    }


def _vector_error(exc: VectorCandidateError) -> HybridCandidateOrchestrationError:
    if exc.error_code in {
        "CX_VECTOR_QUERY_INVALID",
        "CX_VECTOR_CANDIDATE_LIMIT_INVALID",
    }:
        return _invalid_request(exc.detail)
    if exc.error_code == "CX_VECTOR_CANDIDATE_SEARCH_UNAVAILABLE":
        return _candidate_search_unavailable()
    return _candidate_result_invalid()


def _invalid_request(detail: str) -> HybridCandidateOrchestrationError:
    return HybridCandidateOrchestrationError(
        status_code=422,
        error_code="CX_HYBRID_CANDIDATE_REQUEST_INVALID",
        detail=detail,
    )


def _candidate_result_invalid() -> HybridCandidateOrchestrationError:
    return HybridCandidateOrchestrationError(
        status_code=500,
        error_code="CX_HYBRID_CANDIDATE_RESULT_INVALID",
        detail="Permission-filtered candidate lineage validation failed.",
    )


def _candidate_search_unavailable() -> HybridCandidateOrchestrationError:
    return HybridCandidateOrchestrationError(
        status_code=503,
        error_code="CX_HYBRID_CANDIDATE_SEARCH_UNAVAILABLE",
        detail="Permission-filtered candidate search is unavailable.",
        retryable=True,
    )
