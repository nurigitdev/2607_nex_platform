from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class RetrievalPolicyError(Exception):
    status_code: int
    error_code: str
    detail: str


CURRENT_POLICY_ID = "retrieval_quality_v1"
WEIGHTED_RRF_POLICY_ID = "weighted_rrf_vector_bm25_v1"
THRESHOLD_DECISION_SCHEMA_VERSION = "retrieval_threshold_decision.v1"


def threshold_decision_checkpoint(
    *,
    decision_id: str,
    canonical_low_confidence_threshold: float,
) -> dict[str, Any]:
    return {
        "decision_schema_version": THRESHOLD_DECISION_SCHEMA_VERSION,
        "decision_id": decision_id,
        "decision_status": "OBSERVE",
        "canonical_low_confidence_threshold": canonical_low_confidence_threshold,
        "candidate_low_confidence_threshold": None,
        "live_smoke_override_threshold": 0.0,
        "minimum_live_samples_before_change": 20,
        "review_owner_service": "nex-ag",
        "operator_action": "collect_live_score_samples",
        "evidence_sources": [
            "Slice 0297 protected_live_rag_score_calibration.v1",
            "Slice 0299 ag_retrieval_score_calibration.v1",
        ],
        "decision_note": (
            "Keep the canonical low-confidence threshold unchanged until "
            "additional live RAG score samples justify a policy update."
        ),
    }


DEFAULT_RETRIEVAL_POLICIES: tuple[dict[str, Any], ...] = (
    {
        "policy_schema_version": "retrieval_policy.v1",
        "policy_id": CURRENT_POLICY_ID,
        "version": "0001",
        "status": "ACTIVE",
        "lifecycle": "current_runtime",
        "owner_service": "nex-ag",
        "applies_to_service": "nex-cx",
        "description": "Current CX mock-first retrieval ranking policy.",
        "ranker": {
            "method": "bm25_with_embedding_presence",
            "bm25_weight": 0.85,
            "embedding_presence_weight": 0.15,
            "embedding_presence_score": 0.5,
            "vector_weight": 0.0,
            "rrf_k": None,
        },
        "candidate_limits": {
            "default_top_k": 5,
            "max_top_k": 20,
            "vector_candidate_limit": 0,
            "bm25_candidate_limit": 50,
            "rerank_candidate_limit": 50,
        },
        "confidence": {
            "low_confidence_threshold": 0.2,
        },
        "threshold_decision": threshold_decision_checkpoint(
            decision_id="retrieval_quality_v1_threshold_0001",
            canonical_low_confidence_threshold=0.2,
        ),
        "tokenizer_profile": {
            "bm25_tokenizer": "mecab_ko",
            "bm25_tokenizer_fallback": "korean_mixed_v1",
            "query_tokenizer_policy": "fallback_safe_current_slice",
            "dictionary_profile": "runtime_default",
            "dictionary_path_env": "MECAB_DICDIR",
        },
        "provider_aliases": {
            "embedding_alias": "mock-embedding-default",
            "reranker_alias": "mock-reranker-default",
        },
        "request_override_policy": {
            "allowed": True,
            "scope": "test_and_smoke_only_until_policy_publish",
        },
    },
    {
        "policy_schema_version": "retrieval_policy.v1",
        "policy_id": WEIGHTED_RRF_POLICY_ID,
        "version": "0001",
        "status": "CANDIDATE",
        "lifecycle": "planned_runtime",
        "owner_service": "nex-ag",
        "applies_to_service": "nex-cx",
        "description": "Planned weighted RRF policy for vector and BM25 retrieval.",
        "ranker": {
            "method": "weighted_rrf",
            "vector_weight": 0.7,
            "bm25_weight": 0.3,
            "rrf_k": 60,
            "embedding_presence_weight": 0.0,
            "embedding_presence_score": 0.0,
        },
        "candidate_limits": {
            "default_top_k": 5,
            "max_top_k": 20,
            "vector_candidate_limit": 80,
            "bm25_candidate_limit": 80,
            "rerank_candidate_limit": 50,
        },
        "confidence": {
            "low_confidence_threshold": 0.2,
        },
        "threshold_decision": threshold_decision_checkpoint(
            decision_id="weighted_rrf_vector_bm25_v1_threshold_0001",
            canonical_low_confidence_threshold=0.2,
        ),
        "tokenizer_profile": {
            "bm25_tokenizer": "mecab_ko",
            "bm25_tokenizer_fallback": "korean_mixed_v1",
            "query_tokenizer_policy": "match_index_tokenizer_with_fallback",
            "dictionary_profile": "mecab-ko-dic",
            "dictionary_path_env": "MECAB_DICDIR",
        },
        "provider_aliases": {
            "embedding_alias": "mock-embedding-default",
            "reranker_alias": "mock-reranker-default",
        },
        "request_override_policy": {
            "allowed": False,
            "scope": "admin_publish_only",
        },
    },
)


def list_retrieval_policy_records(
    policies: tuple[dict[str, Any], ...] = DEFAULT_RETRIEVAL_POLICIES,
) -> list[dict[str, Any]]:
    return [finalize_retrieval_policy(policy) for policy in policies]


def active_retrieval_policy_record(
    policies: tuple[dict[str, Any], ...] = DEFAULT_RETRIEVAL_POLICIES,
) -> dict[str, Any]:
    active = [
        policy
        for policy in policies
        if policy.get("status") == "ACTIVE"
    ]
    if len(active) != 1:
        raise RetrievalPolicyError(
            status_code=500,
            error_code="retrieval_policy.active_policy_invalid",
            detail="Exactly one active retrieval policy is required.",
        )
    return finalize_retrieval_policy(active[0])


def retrieval_policy_by_id(
    policy_id: str,
    policies: tuple[dict[str, Any], ...] = DEFAULT_RETRIEVAL_POLICIES,
) -> dict[str, Any]:
    for policy in policies:
        if policy.get("policy_id") == policy_id:
            return finalize_retrieval_policy(policy)
    raise RetrievalPolicyError(
        status_code=404,
        error_code="retrieval_policy.not_found",
        detail=f"Retrieval policy was not found: {policy_id}",
    )


def finalize_retrieval_policy(policy: dict[str, Any]) -> dict[str, Any]:
    validate_retrieval_policy(policy)
    canonical = json.loads(json.dumps(policy, sort_keys=True))
    canonical["policy_hash"] = retrieval_policy_hash(canonical)
    canonical["updated_at"] = canonical.get("updated_at", _utc_now())
    return canonical


def retrieval_policy_hash(policy: dict[str, Any]) -> str:
    payload = {
        key: value
        for key, value in policy.items()
        if key not in {"policy_hash", "updated_at"}
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def validate_retrieval_policy(policy: dict[str, Any]) -> None:
    _required_string(policy, "policy_schema_version", expected="retrieval_policy.v1")
    _required_string(policy, "policy_id")
    _required_string(policy, "version")
    status = _required_string(policy, "status")
    if status not in {"ACTIVE", "CANDIDATE", "RETIRED"}:
        raise RetrievalPolicyError(
            status_code=422,
            error_code="retrieval_policy.status_invalid",
            detail="Retrieval policy status must be ACTIVE, CANDIDATE, or RETIRED.",
        )
    ranker = _required_mapping(policy, "ranker")
    method = _required_string(ranker, "method")
    if method == "bm25_with_embedding_presence":
        _bounded_float(ranker, "bm25_weight")
        _bounded_float(ranker, "embedding_presence_weight")
        _bounded_float(ranker, "embedding_presence_score")
    elif method == "weighted_rrf":
        _bounded_float(ranker, "vector_weight")
        _bounded_float(ranker, "bm25_weight")
        _positive_int(ranker, "rrf_k")
    else:
        raise RetrievalPolicyError(
            status_code=422,
            error_code="retrieval_policy.ranker_method_invalid",
            detail=f"Unsupported retrieval ranker method: {method}",
        )

    limits = _required_mapping(policy, "candidate_limits")
    _positive_int(limits, "default_top_k")
    _positive_int(limits, "max_top_k")
    if limits["default_top_k"] > limits["max_top_k"]:
        raise RetrievalPolicyError(
            status_code=422,
            error_code="retrieval_policy.top_k_invalid",
            detail="default_top_k must be less than or equal to max_top_k.",
        )
    _non_negative_int(limits, "vector_candidate_limit")
    _positive_int(limits, "bm25_candidate_limit")
    _positive_int(limits, "rerank_candidate_limit")
    _bounded_float(_required_mapping(policy, "confidence"), "low_confidence_threshold")
    tokenizer = _required_mapping(policy, "tokenizer_profile")
    _required_string(tokenizer, "bm25_tokenizer")
    _required_string(tokenizer, "bm25_tokenizer_fallback")
    aliases = _required_mapping(policy, "provider_aliases")
    _required_string(aliases, "embedding_alias")
    _required_string(aliases, "reranker_alias")
    _validate_threshold_decision(policy)


def _validate_threshold_decision(policy: dict[str, Any]) -> None:
    decision = policy.get("threshold_decision")
    if decision is None:
        return
    if not isinstance(decision, dict):
        raise RetrievalPolicyError(
            status_code=422,
            error_code="retrieval_policy.field_invalid",
            detail="threshold_decision must be an object.",
        )
    _required_string(
        decision,
        "decision_schema_version",
        expected=THRESHOLD_DECISION_SCHEMA_VERSION,
    )
    _required_string(decision, "decision_id")
    status = _required_string(decision, "decision_status")
    if status not in {"OBSERVE", "ADOPT", "REJECT"}:
        raise RetrievalPolicyError(
            status_code=422,
            error_code="retrieval_policy.field_invalid",
            detail="decision_status must be OBSERVE, ADOPT, or REJECT.",
        )
    _bounded_float(decision, "canonical_low_confidence_threshold")
    _optional_bounded_float(decision, "candidate_low_confidence_threshold")
    _optional_bounded_float(decision, "live_smoke_override_threshold")
    _positive_int(decision, "minimum_live_samples_before_change")
    _required_string(decision, "review_owner_service")
    _required_string(decision, "operator_action")
    _required_string(decision, "decision_note")
    _required_string_list(decision, "evidence_sources")


def _required_string(
    payload: dict[str, Any],
    field_name: str,
    *,
    expected: str | None = None,
) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise RetrievalPolicyError(
            status_code=422,
            error_code="retrieval_policy.field_invalid",
            detail=f"{field_name} must be a non-empty string.",
        )
    value = value.strip()
    if expected is not None and value != expected:
        raise RetrievalPolicyError(
            status_code=422,
            error_code="retrieval_policy.field_invalid",
            detail=f"{field_name} must be {expected}.",
        )
    return value


def _required_mapping(payload: dict[str, Any], field_name: str) -> dict[str, Any]:
    value = payload.get(field_name)
    if not isinstance(value, dict):
        raise RetrievalPolicyError(
            status_code=422,
            error_code="retrieval_policy.field_invalid",
            detail=f"{field_name} must be an object.",
        )
    return value


def _bounded_float(payload: dict[str, Any], field_name: str) -> float:
    value = payload.get(field_name)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise RetrievalPolicyError(
            status_code=422,
            error_code="retrieval_policy.field_invalid",
            detail=f"{field_name} must be numeric.",
        )
    numeric = float(value)
    if numeric < 0.0 or numeric > 1.0:
        raise RetrievalPolicyError(
            status_code=422,
            error_code="retrieval_policy.field_invalid",
            detail=f"{field_name} must be between 0.0 and 1.0.",
        )
    return numeric


def _optional_bounded_float(
    payload: dict[str, Any],
    field_name: str,
) -> float | None:
    if payload.get(field_name) is None:
        return None
    return _bounded_float(payload, field_name)


def _positive_int(payload: dict[str, Any], field_name: str) -> int:
    value = payload.get(field_name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RetrievalPolicyError(
            status_code=422,
            error_code="retrieval_policy.field_invalid",
            detail=f"{field_name} must be a positive integer.",
        )
    return value


def _non_negative_int(payload: dict[str, Any], field_name: str) -> int:
    value = payload.get(field_name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RetrievalPolicyError(
            status_code=422,
            error_code="retrieval_policy.field_invalid",
            detail=f"{field_name} must be a non-negative integer.",
        )
    return value


def _required_string_list(payload: dict[str, Any], field_name: str) -> list[str]:
    value = payload.get(field_name)
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise RetrievalPolicyError(
            status_code=422,
            error_code="retrieval_policy.field_invalid",
            detail=f"{field_name} must be a list of non-empty strings.",
        )
    return [item.strip() for item in value]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
