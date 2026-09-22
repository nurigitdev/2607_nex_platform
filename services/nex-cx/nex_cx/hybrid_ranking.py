from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import math
import re
from typing import Any, Protocol

from nex_cx.access_context import CxAccessContext
from nex_cx.hybrid_candidate_orchestration import (
    HYBRID_CANDIDATE_SET_SCHEMA_VERSION,
)
from nex_cx.retrieval_permissions import (
    PERMISSION_POLICY_ID,
    PERMISSION_SNAPSHOT_SCHEMA_VERSION,
)


HYBRID_RANKED_SET_SCHEMA_VERSION = "cx_hybrid_ranked_candidate_set.v1"
HYBRID_RANKED_CANDIDATE_SCHEMA_VERSION = "cx_hybrid_ranked_candidate.v1"
WEIGHTED_RRF_POLICY_ID = "weighted_rrf_vector_bm25_v1"
DEFAULT_VECTOR_WEIGHT = 0.7
DEFAULT_BM25_WEIGHT = 0.3
DEFAULT_RRF_K = 60
DEFAULT_RERANK_CANDIDATE_LIMIT = 50
MAX_RERANK_CANDIDATE_LIMIT = 100
MAX_QUERY_TEXT_LENGTH = 16_000
MAX_CHUNK_TEXT_LENGTH = 64_000
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class HybridRankingPolicy:
    policy_id: str = WEIGHTED_RRF_POLICY_ID
    vector_weight: float = DEFAULT_VECTOR_WEIGHT
    bm25_weight: float = DEFAULT_BM25_WEIGHT
    rrf_k: int = DEFAULT_RRF_K
    rerank_candidate_limit: int = DEFAULT_RERANK_CANDIDATE_LIMIT


DEFAULT_HYBRID_RANKING_POLICY = HybridRankingPolicy()


class AuthorizedChunkTextLoader(Protocol):
    def load_authorized_texts(
        self,
        *,
        access_context: CxAccessContext,
        chunk_refs: Sequence[Mapping[str, str]],
    ) -> list[dict[str, Any]]: ...


class PermissionAwareRerankClient(Protocol):
    def rerank_documents(
        self,
        query: str,
        documents: list[str],
        *,
        alias: str,
        top_n: int,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]: ...


class HybridRankingError(RuntimeError):
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


def rank_permission_filtered_candidates(
    *,
    access_context: CxAccessContext,
    query_text: str,
    candidate_set: Mapping[str, Any],
    policy: HybridRankingPolicy = DEFAULT_HYBRID_RANKING_POLICY,
    text_loader: AuthorizedChunkTextLoader | None = None,
    rerank_client: PermissionAwareRerankClient | None = None,
    reranker_alias: str = "mock-reranker-default",
) -> dict[str, Any]:
    query = _query_text(query_text)
    _validate_policy(policy)
    permission_snapshot, visible_ids = _permission_continuity(
        access_context,
        candidate_set,
    )
    query_sha256 = hashlib.sha256(query.encode("utf-8")).hexdigest()
    if candidate_set.get("query_sha256") != query_sha256:
        raise _permission_continuity_invalid()

    lexical = _channel_candidates(
        candidate_set.get("lexical_candidates"),
        channel="bm25",
        expected_source="postgresql_bm25",
        expected_schema="cx_lexical_candidate.v1",
        score_field="bm25_score",
        visible_ids=visible_ids,
    )
    vector = _channel_candidates(
        candidate_set.get("vector_candidates"),
        channel="vector",
        expected_source="postgresql_pgvector",
        expected_schema="cx_vector_candidate.v1",
        score_field="vector_score",
        visible_ids=visible_ids,
    )
    ranked = _fuse_weighted_rrf(lexical, vector, policy=policy)

    reranker_profile = {
        "status": "NOT_REQUESTED",
        "provider_alias": None,
        "model_revision": None,
        "deployment_id": None,
    }
    if rerank_client is not None and ranked:
        if text_loader is None:
            raise HybridRankingError(
                status_code=500,
                error_code="CX_AUTHORIZED_TEXT_LOADER_REQUIRED",
                detail="Reranking requires the owner-scoped private text loader.",
            )
        ranked, reranker_profile = _rerank_authorized_window(
            access_context=access_context,
            query_text=query,
            candidates=ranked,
            text_loader=text_loader,
            rerank_client=rerank_client,
            reranker_alias=_non_empty_string(reranker_alias),
            request_id=access_context.request_id,
            trace_id=access_context.trace_id,
            limit=policy.rerank_candidate_limit,
        )

    return {
        "ranked_candidate_set_schema_version": HYBRID_RANKED_SET_SCHEMA_VERSION,
        "permission_policy": PERMISSION_POLICY_ID,
        "permission_snapshot": permission_snapshot,
        "permission_continuity_verified": True,
        "query_sha256": query_sha256,
        "ranking_policy": {
            "policy_id": policy.policy_id,
            "vector_weight": policy.vector_weight,
            "bm25_weight": policy.bm25_weight,
            "rrf_k": policy.rrf_k,
            "rerank_candidate_limit": policy.rerank_candidate_limit,
        },
        "candidate_count": len(ranked),
        "rerank_state": reranker_profile["status"],
        "reranker_profile": reranker_profile,
        "candidates": ranked,
    }


def _permission_continuity(
    access_context: CxAccessContext,
    candidate_set: object,
) -> tuple[dict[str, Any], frozenset[str]]:
    if not isinstance(candidate_set, Mapping):
        raise _permission_continuity_invalid()
    if (
        candidate_set.get("hybrid_candidate_set_schema_version")
        != HYBRID_CANDIDATE_SET_SCHEMA_VERSION
        or candidate_set.get("permission_enforced_before_candidates") is not True
        or candidate_set.get("permission_policy") != PERMISSION_POLICY_ID
    ):
        raise _permission_continuity_invalid()
    snapshot = candidate_set.get("permission_snapshot")
    if not isinstance(snapshot, Mapping):
        raise _permission_continuity_invalid()
    tenant_ref = snapshot.get("tenant_ref")
    scope_applied = snapshot.get("scope_applied")
    if (
        snapshot.get("permission_snapshot_schema_version")
        != PERMISSION_SNAPSHOT_SCHEMA_VERSION
        or snapshot.get("policy_version") != PERMISSION_POLICY_ID
        or snapshot.get("actor_type") != "oa.user"
        or snapshot.get("actor_id") != access_context.subject_id
        or not isinstance(tenant_ref, Mapping)
        or tenant_ref.get("type") != "oa.tenant"
        or tenant_ref.get("id") != access_context.tenant_id
        or not isinstance(scope_applied, Mapping)
        or scope_applied.get("type") != "document_ids"
    ):
        raise _permission_continuity_invalid()
    visible_ids = _unique_string_list(scope_applied.get("document_ids"))
    if snapshot.get("visible_document_count") != len(visible_ids):
        raise _permission_continuity_invalid()
    return dict(snapshot), frozenset(visible_ids)


def _channel_candidates(
    wrapper: object,
    *,
    channel: str,
    expected_source: str,
    expected_schema: str,
    score_field: str,
    visible_ids: frozenset[str],
) -> list[dict[str, Any]]:
    if not isinstance(wrapper, Mapping):
        raise _candidate_set_invalid()
    values = wrapper.get("candidates")
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise _candidate_set_invalid()
    if wrapper.get("candidate_count") != len(values):
        raise _candidate_set_invalid()
    if wrapper.get("candidate_source") != expected_source:
        raise _candidate_set_invalid()

    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for value in values:
        if not isinstance(value, Mapping):
            raise _candidate_set_invalid()
        content_id = _identifier_or_none(value.get("content_object_id"))
        chunk_id = _identifier_or_none(value.get("chunk_id"))
        score = _finite_number_or_none(value.get(score_field))
        if content_id is None or chunk_id is None or score is None:
            raise _candidate_set_invalid()
        key = (content_id, chunk_id)
        if (
            value.get(f"{channel if channel == 'vector' else 'lexical'}_candidate_schema_version")
            != expected_schema
            or value.get("candidate_source") != expected_source
            or content_id not in visible_ids
            or key in seen
            or (channel == "bm25" and score <= 0.0)
        ):
            raise _candidate_set_invalid()
        seen.add(key)
        text_sha256 = value.get("text_sha256")
        if text_sha256 is not None and not _valid_sha256(text_sha256):
            raise _candidate_set_invalid()
        normalized.append(
            {
                "key": key,
                "content_object_id": content_id,
                "chunk_id": chunk_id,
                "score": score,
                "text_sha256": text_sha256,
            }
        )
    return sorted(
        normalized,
        key=lambda item: (-item["score"], item["content_object_id"], item["chunk_id"]),
    )


def _fuse_weighted_rrf(
    lexical: Sequence[Mapping[str, Any]],
    vector: Sequence[Mapping[str, Any]],
    *,
    policy: HybridRankingPolicy,
) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for rank, candidate in enumerate(lexical, start=1):
        by_key[candidate["key"]] = _ranked_candidate(
            candidate,
            bm25_rank=rank,
            vector_rank=None,
            bm25_score=candidate["score"],
            vector_score=None,
        )
    for rank, candidate in enumerate(vector, start=1):
        current = by_key.get(candidate["key"])
        if current is None:
            by_key[candidate["key"]] = _ranked_candidate(
                candidate,
                bm25_rank=None,
                vector_rank=rank,
                bm25_score=None,
                vector_score=candidate["score"],
            )
            continue
        current["scores"]["vector_rank"] = rank
        current["scores"]["vector_score"] = candidate["score"]
        current["channel_presence"].append("vector")
        if current["text_sha256"] is None:
            current["text_sha256"] = candidate["text_sha256"]
        elif (
            candidate["text_sha256"] is not None
            and candidate["text_sha256"] != current["text_sha256"]
        ):
            raise _candidate_set_invalid()

    for candidate in by_key.values():
        raw_score, normalized_score = _weighted_rrf_score(
            bm25_rank=candidate["scores"]["bm25_rank"],
            vector_rank=candidate["scores"]["vector_rank"],
            policy=policy,
        )
        candidate["scores"].update(
            {
                "rrf_score": raw_score,
                "rrf_normalized_score": normalized_score,
                "rerank_score": None,
                "final_score": normalized_score,
            }
        )
    ordered = sorted(
        by_key.values(),
        key=lambda item: (
            -item["scores"]["final_score"],
            item["scores"]["vector_rank"] or math.inf,
            item["scores"]["bm25_rank"] or math.inf,
            item["content_object_id"],
            item["chunk_id"],
        ),
    )
    return [{**candidate, "rank": rank} for rank, candidate in enumerate(ordered, 1)]


def _ranked_candidate(
    candidate: Mapping[str, Any],
    *,
    bm25_rank: int | None,
    vector_rank: int | None,
    bm25_score: float | None,
    vector_score: float | None,
) -> dict[str, Any]:
    return {
        "ranked_candidate_schema_version": HYBRID_RANKED_CANDIDATE_SCHEMA_VERSION,
        "content_object_id": candidate["content_object_id"],
        "chunk_id": candidate["chunk_id"],
        "text_sha256": candidate["text_sha256"],
        "channel_presence": ["bm25"] if bm25_rank is not None else ["vector"],
        "scores": {
            "bm25_score": bm25_score,
            "vector_score": vector_score,
            "bm25_rank": bm25_rank,
            "vector_rank": vector_rank,
        },
    }


def _weighted_rrf_score(
    *,
    bm25_rank: int | None,
    vector_rank: int | None,
    policy: HybridRankingPolicy,
) -> tuple[float, float]:
    raw_score = 0.0
    if bm25_rank is not None:
        raw_score += policy.bm25_weight / (policy.rrf_k + bm25_rank)
    if vector_rank is not None:
        raw_score += policy.vector_weight / (policy.rrf_k + vector_rank)
    maximum = (policy.bm25_weight + policy.vector_weight) / (policy.rrf_k + 1)
    return round(raw_score, 8), round(raw_score / maximum, 8)


def _rerank_authorized_window(
    *,
    access_context: CxAccessContext,
    query_text: str,
    candidates: list[dict[str, Any]],
    text_loader: AuthorizedChunkTextLoader,
    rerank_client: PermissionAwareRerankClient,
    reranker_alias: str,
    request_id: str,
    trace_id: str,
    limit: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    window = candidates[:limit]
    refs = [
        {
            "content_object_id": candidate["content_object_id"],
            "chunk_id": candidate["chunk_id"],
        }
        for candidate in window
    ]
    try:
        loaded = text_loader.load_authorized_texts(
            access_context=access_context,
            chunk_refs=refs,
        )
    except Exception as exc:
        raise HybridRankingError(
            status_code=503,
            error_code="CX_PRIVATE_CHUNK_TEXT_UNAVAILABLE",
            detail="Authorized private chunk text is unavailable for reranking.",
            retryable=True,
        ) from exc
    documents, hashes = _authorized_documents(window, loaded)
    try:
        response = rerank_client.rerank_documents(
            query_text,
            documents,
            alias=reranker_alias,
            top_n=len(documents),
            request_id=request_id,
            trace_id=trace_id,
        )
    except Exception as exc:
        raise HybridRankingError(
            status_code=503,
            error_code="CX_RERANKER_UNAVAILABLE",
            detail="The authorized reranking provider is unavailable.",
            retryable=True,
        ) from exc
    reranked, profile = _apply_rerank_response(
        window,
        response,
        hashes=hashes,
        configured_alias=reranker_alias,
    )
    ordered = reranked + candidates[len(window) :]
    return [{**candidate, "rank": rank} for rank, candidate in enumerate(ordered, 1)], profile


def _authorized_documents(
    candidates: Sequence[Mapping[str, Any]],
    loaded: object,
) -> tuple[list[str], dict[tuple[str, str], str]]:
    if isinstance(loaded, (str, bytes)) or not isinstance(loaded, Sequence):
        raise _private_text_lineage_invalid()
    by_key: dict[tuple[str, str], tuple[str, str]] = {}
    for record in loaded:
        if not isinstance(record, Mapping):
            raise _private_text_lineage_invalid()
        content_id = _identifier_or_none(record.get("content_object_id"))
        chunk_id = _identifier_or_none(record.get("chunk_id"))
        text = record.get("chunk_text")
        text_sha256 = record.get("text_sha256")
        if (
            content_id is None
            or chunk_id is None
            or (content_id, chunk_id) in by_key
            or not isinstance(text, str)
            or not text
            or len(text) > MAX_CHUNK_TEXT_LENGTH
            or not _valid_sha256(text_sha256)
            or hashlib.sha256(text.encode("utf-8")).hexdigest() != text_sha256
        ):
            raise _private_text_lineage_invalid()
        key = (content_id, chunk_id)
        by_key[key] = (text, text_sha256)

    requested_keys = [
        (candidate["content_object_id"], candidate["chunk_id"])
        for candidate in candidates
    ]
    if set(by_key) != set(requested_keys):
        raise _private_text_lineage_invalid()
    documents: list[str] = []
    hashes: dict[tuple[str, str], str] = {}
    for candidate, key in zip(candidates, requested_keys, strict=True):
        text, text_sha256 = by_key[key]
        expected = candidate.get("text_sha256")
        if expected is not None and expected != text_sha256:
            raise _private_text_lineage_invalid()
        documents.append(text)
        hashes[key] = text_sha256
    return documents, hashes


def _apply_rerank_response(
    candidates: Sequence[Mapping[str, Any]],
    response: object,
    *,
    hashes: Mapping[tuple[str, str], str],
    configured_alias: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not isinstance(response, Mapping):
        raise _rerank_response_invalid()
    results = response.get("results")
    if isinstance(results, (str, bytes)) or not isinstance(results, Sequence):
        raise _rerank_response_invalid()
    if len(results) != len(candidates):
        raise _rerank_response_invalid()
    scored: list[tuple[float, int, dict[str, Any]]] = []
    seen_indexes: set[int] = set()
    for result in results:
        if not isinstance(result, Mapping):
            raise _rerank_response_invalid()
        index = result.get("index")
        score = _finite_number_or_none(result.get("score"))
        if (
            isinstance(index, bool)
            or not isinstance(index, int)
            or not 0 <= index < len(candidates)
            or index in seen_indexes
            or score is None
            or not 0.0 <= score <= 1.0
        ):
            raise _rerank_response_invalid()
        seen_indexes.add(index)
        candidate = dict(candidates[index])
        key = (candidate["content_object_id"], candidate["chunk_id"])
        candidate["text_sha256"] = hashes[key]
        candidate["scores"] = {
            **candidate["scores"],
            "rerank_score": score,
            "final_score": score,
        }
        scored.append((score, index, candidate))
    ordered = [item[2] for item in sorted(scored, key=lambda item: (-item[0], item[1]))]
    return ordered, {
        "status": "APPLIED",
        "provider_alias": _optional_identifier(response.get("alias")) or configured_alias,
        "model_revision": _optional_identifier(response.get("model_revision")),
        "deployment_id": _optional_identifier(response.get("deployment_id")),
    }


def _validate_policy(policy: object) -> None:
    if not isinstance(policy, HybridRankingPolicy):
        raise _policy_invalid()
    if (
        policy.policy_id != WEIGHTED_RRF_POLICY_ID
        or isinstance(policy.rrf_k, bool)
        or not isinstance(policy.rrf_k, int)
        or not 1 <= policy.rrf_k <= 10_000
        or isinstance(policy.rerank_candidate_limit, bool)
        or not isinstance(policy.rerank_candidate_limit, int)
        or not 1 <= policy.rerank_candidate_limit <= MAX_RERANK_CANDIDATE_LIMIT
    ):
        raise _policy_invalid()
    weights = (policy.vector_weight, policy.bm25_weight)
    if any(
        isinstance(weight, bool)
        or not isinstance(weight, int | float)
        or not math.isfinite(float(weight))
        or not 0.0 <= float(weight) <= 1.0
        for weight in weights
    ) or not math.isclose(sum(weights), 1.0, abs_tol=1e-9):
        raise _policy_invalid()


def _query_text(value: object) -> str:
    if not isinstance(value, str):
        raise _request_invalid()
    normalized = value.strip()
    if not normalized or len(normalized) > MAX_QUERY_TEXT_LENGTH:
        raise _request_invalid()
    return normalized


def _unique_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        raise _permission_continuity_invalid()
    normalized = [_identifier_or_none(item) for item in value]
    if any(item is None for item in normalized) or len(normalized) != len(set(normalized)):
        raise _permission_continuity_invalid()
    return [item for item in normalized if item is not None]


def _identifier_or_none(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > 160:
        return None
    return normalized


def _non_empty_string(value: object) -> str:
    normalized = _identifier_or_none(value)
    if normalized is None:
        raise _request_invalid()
    return normalized


def _optional_identifier(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise _rerank_response_invalid()
    normalized = value.strip()
    if not normalized or len(normalized) > 160:
        raise _rerank_response_invalid()
    return normalized


def _finite_number_or_none(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256_PATTERN.fullmatch(value) is not None


def _request_invalid() -> HybridRankingError:
    return HybridRankingError(
        status_code=422,
        error_code="CX_HYBRID_RANKING_REQUEST_INVALID",
        detail="Hybrid ranking request is invalid.",
    )


def _policy_invalid() -> HybridRankingError:
    return HybridRankingError(
        status_code=500,
        error_code="CX_HYBRID_RANKING_POLICY_INVALID",
        detail="Weighted RRF policy is invalid.",
    )


def _permission_continuity_invalid() -> HybridRankingError:
    return HybridRankingError(
        status_code=500,
        error_code="CX_RETRIEVAL_PERMISSION_CONTINUITY_INVALID",
        detail="Permission continuity validation failed before ranking.",
    )


def _candidate_set_invalid() -> HybridRankingError:
    return HybridRankingError(
        status_code=500,
        error_code="CX_HYBRID_CANDIDATE_SET_INVALID",
        detail="Permission-filtered candidate set validation failed.",
    )


def _private_text_lineage_invalid() -> HybridRankingError:
    return HybridRankingError(
        status_code=500,
        error_code="CX_PRIVATE_CHUNK_TEXT_LINEAGE_INVALID",
        detail="Authorized private chunk text lineage validation failed.",
    )


def _rerank_response_invalid() -> HybridRankingError:
    return HybridRankingError(
        status_code=502,
        error_code="CX_RERANK_RESPONSE_INVALID",
        detail="Reranker response validation failed.",
        retryable=True,
    )
