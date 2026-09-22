from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import re
from typing import Any, Protocol
from uuid import NAMESPACE_URL, uuid5

from nex_cx.access_context import CxAccessContext
from nex_cx.api_ownership import owner_scoped_record
from nex_cx.hybrid_ranking import (
    DEFAULT_HYBRID_RANKING_POLICY,
    HybridRankingPolicy,
    PermissionAwareRerankClient,
    rank_permission_filtered_candidates,
)
from nex_cx.retrieval_permissions import PERMISSION_POLICY_ID


HYBRID_RETRIEVAL_RUNTIME_SCHEMA_VERSION = "cx_hybrid_retrieval_runtime.v1"
RETRIEVAL_PACKAGE_SCHEMA_VERSION = "cx_retrieval_context_package.v1"
DEFAULT_LOW_CONFIDENCE_THRESHOLD = 0.2
MAX_TOP_K = 20
MAX_QUERY_TEXT_LENGTH = 16_000
ALLOWED_PURPOSES = {
    "search",
    "grounded_answer",
    "summary",
    "document_generation",
    "confidence_probe",
}
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class HybridCandidateProvider(Protocol):
    def build_candidate_set(
        self,
        *,
        access_context: CxAccessContext,
        query_text: str,
        requested_document_ids: Sequence[str],
    ) -> dict[str, Any]: ...


class AuthorizedEvidenceMaterializer(Protocol):
    def load_authorized_texts(
        self,
        *,
        access_context: CxAccessContext,
        chunk_refs: Sequence[Mapping[str, str]],
    ) -> list[dict[str, Any]]: ...

    def load_authorized_evidence(
        self,
        *,
        access_context: CxAccessContext,
        chunk_refs: Sequence[Mapping[str, str]],
    ) -> list[dict[str, Any]]: ...


class HybridRetrievalPackageRuntime(Protocol):
    def build_package(
        self,
        payload: Mapping[str, Any],
        *,
        access_context: CxAccessContext,
    ) -> dict[str, Any]: ...


class HybridRetrievalPackageError(RuntimeError):
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


@dataclass(frozen=True)
class PermissionFilteredHybridPackageRuntime:
    candidate_provider: HybridCandidateProvider
    evidence_materializer: AuthorizedEvidenceMaterializer
    rerank_client: PermissionAwareRerankClient | None = None
    reranker_alias: str = "mock-reranker-default"
    ranking_policy: HybridRankingPolicy = DEFAULT_HYBRID_RANKING_POLICY
    now_factory: Callable[[], str] | None = None

    def build_package(
        self,
        payload: Mapping[str, Any],
        *,
        access_context: CxAccessContext,
    ) -> dict[str, Any]:
        request = _request(payload)
        try:
            candidate_set = self.candidate_provider.build_candidate_set(
                access_context=access_context,
                query_text=request["query_text"],
                requested_document_ids=request["document_ids"],
            )
        except HybridRetrievalPackageError:
            raise
        except Exception as exc:
            raise HybridRetrievalPackageError(
                status_code=503,
                error_code="CX_HYBRID_CANDIDATE_PROVIDER_UNAVAILABLE",
                detail="Permission-filtered hybrid candidates are unavailable.",
                retryable=True,
            ) from exc

        ranked = rank_permission_filtered_candidates(
            access_context=access_context,
            query_text=request["query_text"],
            candidate_set=candidate_set,
            policy=self.ranking_policy,
            text_loader=(
                self.evidence_materializer
                if self.rerank_client is not None
                else None
            ),
            rerank_client=self.rerank_client,
            reranker_alias=self.reranker_alias,
        )
        evidence_items = _materialize_evidence(
            access_context=access_context,
            ranked_candidates=ranked["candidates"][: request["top_k"]],
            materializer=self.evidence_materializer,
            include_neighbors=request["include_neighbors"],
        )
        return _build_package(
            access_context=access_context,
            request=request,
            candidate_set=candidate_set,
            ranked=ranked,
            evidence_items=evidence_items,
            now=(self.now_factory or _utc_now)(),
        )


def _request(payload: object) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise _request_invalid()
    query_text = payload.get("query_text") or payload.get("user_prompt")
    if not isinstance(query_text, str):
        raise _request_invalid()
    query_text = query_text.strip()
    if not query_text or len(query_text) > MAX_QUERY_TEXT_LENGTH:
        raise _request_invalid()
    document_scope = payload.get("document_scope")
    if not isinstance(document_scope, Mapping):
        raise _request_invalid()
    document_ids = _unique_identifiers(document_scope.get("document_ids"))
    if not document_ids:
        raise _request_invalid()
    top_k = payload.get("top_k", 5)
    if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= MAX_TOP_K:
        raise _request_invalid()
    purpose = payload.get("purpose", "search")
    if purpose not in ALLOWED_PURPOSES:
        raise _request_invalid()
    include_neighbors = payload.get("include_neighbors", False)
    if not isinstance(include_neighbors, bool):
        raise _request_invalid()
    include_source_preview = payload.get("include_source_preview", True)
    if not isinstance(include_source_preview, bool):
        raise _request_invalid()
    return {
        "query_text": query_text,
        "document_ids": document_ids,
        "top_k": top_k,
        "purpose": purpose,
        "include_neighbors": include_neighbors,
        "include_source_preview": include_source_preview,
    }


def _materialize_evidence(
    *,
    access_context: CxAccessContext,
    ranked_candidates: Sequence[Mapping[str, Any]],
    materializer: AuthorizedEvidenceMaterializer,
    include_neighbors: bool,
) -> list[dict[str, Any]]:
    if not ranked_candidates:
        return []
    refs = [
        {
            "content_object_id": candidate["content_object_id"],
            "chunk_id": candidate["chunk_id"],
        }
        for candidate in ranked_candidates
    ]
    try:
        records = materializer.load_authorized_evidence(
            access_context=access_context,
            chunk_refs=refs,
        )
    except Exception as exc:
        raise HybridRetrievalPackageError(
            status_code=503,
            error_code="CX_AUTHORIZED_EVIDENCE_UNAVAILABLE",
            detail="Authorized retrieval evidence is unavailable.",
            retryable=True,
        ) from exc
    by_key = _validated_evidence_records(records, refs=refs)
    evidence: list[dict[str, Any]] = []
    for rank, candidate in enumerate(ranked_candidates, start=1):
        key = (candidate["content_object_id"], candidate["chunk_id"])
        record = by_key[key]
        if (
            candidate.get("text_sha256") is not None
            and candidate["text_sha256"] != record["text_sha256"]
        ):
            raise _evidence_lineage_invalid()
        evidence.append(
            {
                "evidence_id": str(
                    uuid5(
                        NAMESPACE_URL,
                        "cx-hybrid-evidence:"
                        f"{key[0]}:{key[1]}:{rank}:{record['text_sha256']}",
                    )
                ),
                "rank": rank,
                "content_object_id": key[0],
                "content_version_id": record["text_sha256"],
                "chunk_id": key[1],
                "chunk_policy_id": record["chunk_policy_id"],
                "source_anchor": {
                    "type": "character_range",
                    "start_offset": record["start_offset"],
                    "end_offset": record["end_offset"],
                },
                "citation_label": f"[{rank}]",
                "text": record["chunk_text"],
                "neighbor_context": (
                    [{"policy": "not_loaded_in_s95"}]
                    if include_neighbors
                    else []
                ),
                "scores": dict(candidate["scores"]),
                "matched_terms": record["matched_terms"],
                "permission_result": {
                    "visible": True,
                    "reason": "PRIVATE_OWNER_ACTIVE",
                    "policy_version": PERMISSION_POLICY_ID,
                },
                "quality_flags": [],
            }
        )
    return evidence


def _validated_evidence_records(
    records: object,
    *,
    refs: Sequence[Mapping[str, str]],
) -> dict[tuple[str, str], dict[str, Any]]:
    if isinstance(records, (str, bytes)) or not isinstance(records, Sequence):
        raise _evidence_lineage_invalid()
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, Mapping):
            raise _evidence_lineage_invalid()
        content_id = _identifier_or_none(record.get("content_object_id"))
        chunk_id = _identifier_or_none(record.get("chunk_id"))
        chunk_policy_id = _identifier_or_none(record.get("chunk_policy_id"))
        text = record.get("chunk_text")
        text_sha256 = record.get("text_sha256")
        start_offset = record.get("start_offset")
        end_offset = record.get("end_offset")
        matched_terms = record.get("matched_terms", [])
        if (
            content_id is None
            or chunk_id is None
            or chunk_policy_id is None
            or (content_id, chunk_id) in by_key
            or not isinstance(text, str)
            or not text
            or not _valid_sha256(text_sha256)
            or hashlib.sha256(text.encode("utf-8")).hexdigest() != text_sha256
            or isinstance(start_offset, bool)
            or not isinstance(start_offset, int)
            or start_offset < 0
            or isinstance(end_offset, bool)
            or not isinstance(end_offset, int)
            or end_offset < start_offset
            or not _valid_terms(matched_terms)
        ):
            raise _evidence_lineage_invalid()
        by_key[(content_id, chunk_id)] = {
            "chunk_policy_id": chunk_policy_id,
            "chunk_text": text,
            "text_sha256": text_sha256,
            "start_offset": start_offset,
            "end_offset": end_offset,
            "matched_terms": list(matched_terms),
        }
    expected = {(ref["content_object_id"], ref["chunk_id"]) for ref in refs}
    if set(by_key) != expected:
        raise _evidence_lineage_invalid()
    return by_key


def _build_package(
    *,
    access_context: CxAccessContext,
    request: Mapping[str, Any],
    candidate_set: Mapping[str, Any],
    ranked: Mapping[str, Any],
    evidence_items: list[dict[str, Any]],
    now: str,
) -> dict[str, Any]:
    status, no_answer_reason = _retrieval_status(evidence_items)
    policy = ranked["ranking_policy"]
    policy_hash = _sha256_json(policy)
    rerank_applied = ranked["rerank_state"] == "APPLIED"
    ranker_mix = (
        "weighted_rrf_vector_bm25_with_rerank"
        if rerank_applied
        else policy["policy_id"]
    )
    vector_result = candidate_set["vector_candidates"]
    query_dimension = vector_result.get("query_dimension")
    embedding_provided = (
        isinstance(query_dimension, int)
        and not isinstance(query_dimension, bool)
        and query_dimension > 0
    )
    embedding_sha256 = candidate_set.get("query_vector_sha256")
    if embedding_sha256 is not None and not _valid_sha256(embedding_sha256):
        raise _candidate_metadata_invalid()
    visible_ids = ranked["permission_snapshot"]["scope_applied"]["document_ids"]
    score_summary = _score_summary(
        evidence_items,
        ranker_mix=ranker_mix,
        rerank_applied=rerank_applied,
        policy_id=policy["policy_id"],
    )
    package_hash = _sha256_json(
        {
            "query_sha256": ranked["query_sha256"],
            "purpose": request["purpose"],
            "permission_snapshot": ranked["permission_snapshot"],
            "ranking_policy": policy,
            "evidence": [
                {
                    "evidence_id": item["evidence_id"],
                    "content_version_id": item["content_version_id"],
                    "final_score": item["scores"]["final_score"],
                }
                for item in evidence_items
            ],
        }
    )
    package = {
        "retrieval_package_schema_version": RETRIEVAL_PACKAGE_SCHEMA_VERSION,
        "retrieval_runtime_schema_version": HYBRID_RETRIEVAL_RUNTIME_SCHEMA_VERSION,
        "retrieval_package_id": str(
            uuid5(NAMESPACE_URL, f"cx-hybrid-retrieval:{package_hash}")
        ),
        "package_hash": package_hash,
        "status": status,
        "trace_id": access_context.trace_id,
        "request_id": access_context.request_id,
        "query_text": request["query_text"],
        "persistence_payload_policy": "hash_only_private_owner",
        "query_embedding_snapshot": {
            "provided": embedding_provided,
            "embedding_sha256": embedding_sha256,
            "vector_dimension": query_dimension if embedding_provided else 0,
        },
        "purpose": request["purpose"],
        "retrieval_profile": {
            "search_strategy": "permission_filtered_hybrid",
            "embedding_profile": {
                "index_status": vector_result.get("status"),
                "query_embedding_provided": embedding_provided,
                "query_embedding_sha256": embedding_sha256,
                "vector_dimension": query_dimension if embedding_provided else 0,
            },
            "bm25_tokenizer": candidate_set["tokenizer_profile"].get(
                "bm25_tokenizer"
            ),
            "bm25_tokenizer_profile": candidate_set["tokenizer_profile"],
            "reranker_profile": ranked["reranker_profile"],
            "chunk_policy": "chunk_1000_100",
            "source_context_policy": {
                "include_neighbors_supported": False,
                "neighbor_policy": "not_loaded_in_s95",
            },
            "confidence_policy": {
                "low_confidence_threshold": DEFAULT_LOW_CONFIDENCE_THRESHOLD,
            },
            "quality_policy": {
                **policy,
                "policy_version": "0001",
                "policy_hash": policy_hash,
                "policy_source": "cx_permission_filtered_hybrid_runtime",
                "ranker_mix": policy["policy_id"],
                "reranked_ranker_mix": "weighted_rrf_vector_bm25_with_rerank",
                "low_confidence_threshold": DEFAULT_LOW_CONFIDENCE_THRESHOLD,
            },
        },
        "permission_snapshot": dict(ranked["permission_snapshot"]),
        "evidence_items": evidence_items,
        "source_summary": {
            "source_count": len(visible_ids),
            "document_count": len(visible_ids),
            "chunk_count": ranked["candidate_count"],
            "source_types": ["cx.content_object"] if visible_ids else [],
        },
        "score_summary": score_summary,
        "no_answer_reason": no_answer_reason,
        "warnings": _warnings(candidate_set, ranked),
        "created_at": now,
        "updated_at": now,
    }
    return owner_scoped_record(access_context, package)


def _score_summary(
    evidence_items: Sequence[Mapping[str, Any]],
    *,
    ranker_mix: str,
    rerank_applied: bool,
    policy_id: str,
) -> dict[str, Any]:
    scores = [float(item["scores"]["final_score"]) for item in evidence_items]
    if not scores:
        return {
            "best_score": 0.0,
            "score_spread": 0.0,
            "ranker_mix": ranker_mix,
            "rerank_state": "APPLIED" if rerank_applied else "NOT_APPLIED",
            "confidence_bucket": "NO_ANSWER",
            "quality_policy_id": policy_id,
            "low_confidence_threshold": DEFAULT_LOW_CONFIDENCE_THRESHOLD,
        }
    best = max(scores)
    worst = min(scores)
    return {
        "best_score": best,
        "score_spread": round(best - worst, 8),
        "ranker_mix": ranker_mix,
        "rerank_state": "APPLIED" if rerank_applied else "NOT_APPLIED",
        "confidence_bucket": (
            "READY" if best >= DEFAULT_LOW_CONFIDENCE_THRESHOLD else "LOW_CONFIDENCE"
        ),
        "quality_policy_id": policy_id,
        "low_confidence_threshold": DEFAULT_LOW_CONFIDENCE_THRESHOLD,
    }


def _retrieval_status(
    evidence_items: Sequence[Mapping[str, Any]],
) -> tuple[str, str | None]:
    if not evidence_items:
        return "NO_ANSWER", "no_permission_admitted_candidates"
    best = float(evidence_items[0]["scores"]["final_score"])
    if best < DEFAULT_LOW_CONFIDENCE_THRESHOLD:
        return "LOW_CONFIDENCE", "best_score_below_threshold"
    return "READY", None


def _warnings(
    candidate_set: Mapping[str, Any],
    ranked: Mapping[str, Any],
) -> list[str]:
    warnings: list[str] = []
    vector_status = candidate_set["vector_candidates"].get("status")
    if vector_status != "READY":
        warnings.append(f"vector_retrieval_{str(vector_status).lower()}")
    if ranked["rerank_state"] != "APPLIED":
        warnings.append("rerank_not_applied")
    return warnings


def _unique_identifiers(value: object) -> list[str]:
    if not isinstance(value, list):
        raise _request_invalid()
    normalized = [_identifier_or_none(item) for item in value]
    if any(item is None for item in normalized) or len(normalized) != len(set(normalized)):
        raise _request_invalid()
    return [item for item in normalized if item is not None]


def _valid_terms(value: object) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, str) and bool(item.strip()) for item in value
    )


def _identifier_or_none(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized if normalized and len(normalized) <= 160 else None


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256_PATTERN.fullmatch(value) is not None


def _sha256_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _request_invalid() -> HybridRetrievalPackageError:
    return HybridRetrievalPackageError(
        status_code=422,
        error_code="CX_HYBRID_RETRIEVAL_REQUEST_INVALID",
        detail="Permission-filtered hybrid retrieval request is invalid.",
    )


def _evidence_lineage_invalid() -> HybridRetrievalPackageError:
    return HybridRetrievalPackageError(
        status_code=500,
        error_code="CX_AUTHORIZED_EVIDENCE_LINEAGE_INVALID",
        detail="Authorized retrieval evidence lineage validation failed.",
    )


def _candidate_metadata_invalid() -> HybridRetrievalPackageError:
    return HybridRetrievalPackageError(
        status_code=500,
        error_code="CX_HYBRID_CANDIDATE_METADATA_INVALID",
        detail="Hybrid candidate metadata validation failed.",
    )
