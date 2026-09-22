from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from typing import Any

from nex_cx.access_context import CxAccessContext
from nex_cx.retrieval_permissions import (
    RetrievalPermissionError,
    build_evidence_permission_result,
)
from nex_cx.vector_index_repository import VectorIndexRepository
from nex_cx.vector_retrieval_guard import (
    VectorRetrievalError,
    VectorSearchAdapter,
    search_fresh_vector_index,
)


VECTOR_CANDIDATE_RESULT_SCHEMA_VERSION = "cx_vector_candidate_result.v1"
VECTOR_CANDIDATE_SCHEMA_VERSION = "cx_vector_candidate.v1"
MAX_VECTOR_TARGETS = 100
MAX_VECTOR_DIMENSION = 8192
MAX_VECTOR_CANDIDATE_LIMIT = 100


class VectorCandidateError(RuntimeError):
    def __init__(self, *, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


def collect_fresh_vector_candidates(
    *,
    access_context: CxAccessContext,
    targets: Sequence[Mapping[str, Any]],
    query_vector: Sequence[float],
    limit: int,
    repository: VectorIndexRepository,
    vector_store: VectorSearchAdapter,
) -> dict[str, Any]:
    normalized_vector = _normalize_query_vector(query_vector)
    normalized_targets = _normalize_targets(
        targets,
        query_dimension=len(normalized_vector),
    )
    _validate_limit(limit)

    candidates_by_chunk: dict[tuple[str, str], dict[str, Any]] = {}
    exclusion_counts: dict[str, int] = {}
    admitted_index_count = 0
    for target in normalized_targets:
        try:
            result = search_fresh_vector_index(
                access_context=access_context,
                vector_index_id=target["vector_index_id"],
                source_snapshot=target["source_snapshot"],
                embedding_profile=target["embedding_profile"],
                query_vector=normalized_vector,
                limit=limit,
                repository=repository,
                vector_store=vector_store,
            )
        except VectorRetrievalError as exc:
            reason = _expected_exclusion_reason(exc)
            if reason is None:
                raise _unavailable() from exc
            exclusion_counts[reason] = exclusion_counts.get(reason, 0) + 1
            continue
        except Exception as exc:
            raise _unavailable() from exc

        admitted_index_count += 1
        for candidate in _candidates_from_result(target, result):
            key = (candidate["content_object_id"], candidate["chunk_id"])
            current = candidates_by_chunk.get(key)
            if current is None or _candidate_precedes(candidate, current):
                candidates_by_chunk[key] = candidate

    ordered = sorted(
        candidates_by_chunk.values(),
        key=lambda item: (
            -item["vector_score"],
            item["content_object_id"],
            item["chunk_id"],
            item["vector_index_id"],
        ),
    )[:limit]
    ranked = [
        {**candidate, "candidate_rank": rank}
        for rank, candidate in enumerate(ordered, start=1)
    ]
    requested_count = len(normalized_targets)
    return {
        "vector_candidate_result_schema_version": (
            VECTOR_CANDIDATE_RESULT_SCHEMA_VERSION
        ),
        "candidate_source": "postgresql_pgvector",
        "query_dimension": len(normalized_vector),
        "requested_index_count": requested_count,
        "admitted_index_count": admitted_index_count,
        "excluded_index_count": requested_count - admitted_index_count,
        "exclusion_counts": dict(sorted(exclusion_counts.items())),
        "candidate_count": len(ranked),
        "candidates": ranked,
    }


def _normalize_targets(
    targets: Sequence[Mapping[str, Any]],
    *,
    query_dimension: int,
) -> list[dict[str, Any]]:
    if isinstance(targets, (str, bytes)) or not isinstance(targets, Sequence):
        raise _invalid_targets()
    if len(targets) > MAX_VECTOR_TARGETS:
        raise _invalid_targets()
    normalized: list[dict[str, Any]] = []
    seen_index_ids: set[str] = set()
    for target in targets:
        if not isinstance(target, Mapping):
            raise _invalid_targets()
        vector_index_id = _non_empty_string(target.get("vector_index_id"))
        content_object_id = _non_empty_string(target.get("content_object_id"))
        source_snapshot = target.get("source_snapshot")
        embedding_profile = target.get("embedding_profile")
        permission_decision = target.get("permission_decision")
        if (
            vector_index_id is None
            or content_object_id is None
            or not isinstance(source_snapshot, Mapping)
            or not isinstance(embedding_profile, Mapping)
            or not isinstance(permission_decision, Mapping)
            or vector_index_id in seen_index_ids
        ):
            raise _invalid_targets()
        try:
            build_evidence_permission_result(permission_decision)
        except RetrievalPermissionError as exc:
            raise _invalid_targets() from exc
        vector_dimension = embedding_profile.get("vector_dimension")
        if (
            isinstance(vector_dimension, bool)
            or not isinstance(vector_dimension, int)
            or vector_dimension != query_dimension
        ):
            raise _invalid_targets()
        chunk_refs = source_snapshot.get("chunk_refs")
        if not isinstance(chunk_refs, list):
            raise _invalid_targets()
        chunk_ids = _source_chunk_ids(chunk_refs)
        normalized.append(
            {
                "vector_index_id": vector_index_id,
                "content_object_id": content_object_id,
                "source_snapshot": dict(source_snapshot),
                "embedding_profile": dict(embedding_profile),
                "source_chunk_ids": chunk_ids,
            }
        )
        seen_index_ids.add(vector_index_id)
    return normalized


def _normalize_query_vector(value: Sequence[float]) -> tuple[float, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise _invalid_query_vector()
    if not 1 <= len(value) <= MAX_VECTOR_DIMENSION:
        raise _invalid_query_vector()
    normalized: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int | float):
            raise _invalid_query_vector()
        number = float(item)
        if not math.isfinite(number):
            raise _invalid_query_vector()
        normalized.append(number)
    return tuple(normalized)


def _validate_limit(limit: int) -> None:
    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= MAX_VECTOR_CANDIDATE_LIMIT
    ):
        raise VectorCandidateError(
            error_code="CX_VECTOR_CANDIDATE_LIMIT_INVALID",
            detail=(
                "Vector candidate limit must be between 1 and "
                f"{MAX_VECTOR_CANDIDATE_LIMIT}."
            ),
        )


def _source_chunk_ids(chunk_refs: list[Any]) -> frozenset[str]:
    chunk_ids: set[str] = set()
    for item in chunk_refs:
        if not isinstance(item, Mapping):
            raise _invalid_targets()
        chunk_id = _non_empty_string(item.get("chunk_id"))
        if chunk_id is None or chunk_id in chunk_ids:
            raise _invalid_targets()
        chunk_ids.add(chunk_id)
    return frozenset(chunk_ids)


def _candidates_from_result(
    target: Mapping[str, Any],
    result: object,
) -> list[dict[str, Any]]:
    if not isinstance(result, Mapping):
        raise _malformed_result()
    if (
        result.get("vector_index_id") != target["vector_index_id"]
        or result.get("content_object_id") != target["content_object_id"]
    ):
        raise _malformed_result()
    freshness = result.get("freshness")
    matches = result.get("matches")
    if (
        not isinstance(freshness, Mapping)
        or freshness.get("retrieval_usable") is not True
        or isinstance(matches, (str, bytes))
        or not isinstance(matches, Sequence)
    ):
        raise _malformed_result()
    candidates: list[dict[str, Any]] = []
    for local_rank, match in enumerate(matches, start=1):
        if not isinstance(match, Mapping):
            raise _malformed_result()
        chunk_id = _non_empty_string(match.get("chunk_id"))
        score = _finite_number(match.get("score"))
        distance = _finite_number(match.get("distance"))
        if (
            chunk_id is None
            or chunk_id not in target["source_chunk_ids"]
            or score is None
            or distance is None
        ):
            raise _malformed_result()
        candidates.append(
            {
                "vector_candidate_schema_version": VECTOR_CANDIDATE_SCHEMA_VERSION,
                "candidate_source": "postgresql_pgvector",
                "content_object_id": target["content_object_id"],
                "vector_index_id": target["vector_index_id"],
                "chunk_id": chunk_id,
                "vector_rank": local_rank,
                "vector_score": round(score, 8),
                "vector_distance": round(distance, 8),
            }
        )
    return candidates


def _candidate_precedes(candidate: Mapping[str, Any], current: Mapping[str, Any]) -> bool:
    return (
        -candidate["vector_score"],
        candidate["vector_index_id"],
    ) < (
        -current["vector_score"],
        current["vector_index_id"],
    )


def _expected_exclusion_reason(exc: VectorRetrievalError) -> str | None:
    if exc.status_code == 404 and exc.error_code == "CX_VECTOR_INDEX_NOT_FOUND":
        return "INDEX_NOT_FOUND"
    if exc.status_code == 409 and exc.error_code == "CX_VECTOR_INDEX_NOT_READY":
        if exc.freshness is not None:
            reason = exc.freshness.get("reason")
            if isinstance(reason, str) and reason:
                return reason
        return "INDEX_NOT_READY"
    return None


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _non_empty_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized if normalized and len(normalized) <= 160 else None


def _invalid_targets() -> VectorCandidateError:
    return VectorCandidateError(
        error_code="CX_VECTOR_TARGETS_INVALID",
        detail=(
            "Vector targets must be unique, permission-admitted index metadata."
        ),
    )


def _invalid_query_vector() -> VectorCandidateError:
    return VectorCandidateError(
        error_code="CX_VECTOR_QUERY_INVALID",
        detail="Query vector must be a bounded sequence of finite numbers.",
    )


def _malformed_result() -> VectorCandidateError:
    return VectorCandidateError(
        error_code="CX_VECTOR_CANDIDATE_RESULT_INVALID",
        detail="Fresh vector candidate result failed lineage validation.",
    )


def _unavailable() -> VectorCandidateError:
    return VectorCandidateError(
        error_code="CX_VECTOR_CANDIDATE_SEARCH_UNAVAILABLE",
        detail="Fresh vector candidate search is unavailable.",
    )
