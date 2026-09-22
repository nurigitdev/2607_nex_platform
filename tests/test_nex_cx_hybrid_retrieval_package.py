from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any

from fastapi.testclient import TestClient
import pytest

from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token
from nex_cx.access_context import CxAccessContext
from nex_cx.hybrid_ranking import HybridRankingError, HybridRankingPolicy
from nex_cx.hybrid_retrieval_package import (
    HybridRetrievalPackageError,
    MAX_QUERY_TEXT_LENGTH,
    PermissionFilteredHybridPackageRuntime,
)
from nex_cx.ingestion import ContentIngestionStore
from nex_cx.retrieval import register_retrieval_routes
from nex_cx.retrieval_persistence import build_retrieval_package_persistence_preview


QUERY = "owner private retrieval"
DOC_ID = "content-owner-one"
CHUNK_ONE = "chunk-one"
CHUNK_TWO = "chunk-two"
TEXTS = {
    CHUNK_ONE: "private evidence one",
    CHUNK_TWO: "private evidence two",
}


def _payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "query_text": QUERY,
        "document_scope": {"document_ids": [DOC_ID]},
        "top_k": 2,
        "purpose": "grounded_answer",
        "include_neighbors": False,
        "include_source_preview": True,
    }
    payload.update(overrides)
    return payload


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _evidence_record(chunk_id: str) -> dict[str, Any]:
    text = TEXTS.get(chunk_id, "unexpected text")
    ordinal = 0 if chunk_id == CHUNK_ONE else 1
    return {
        "content_object_id": DOC_ID,
        "chunk_id": chunk_id,
        "chunk_policy_id": "chunk_1000_100",
        "chunk_text": text,
        "text_sha256": _digest(text),
        "start_offset": ordinal * 100,
        "end_offset": ordinal * 100 + len(text),
        "matched_terms": ["private"],
    }


class FakeCandidateProvider:
    def __init__(self, candidate_set: object | None = None, error: Exception | None = None) -> None:
        self.candidate_set = candidate_set
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def build_candidate_set(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return deepcopy(self.candidate_set or _candidate_set())


class FakeMaterializer:
    def __init__(
        self,
        *,
        evidence: object | None = None,
        text_error: Exception | None = None,
        evidence_error: Exception | None = None,
    ) -> None:
        self.evidence = evidence
        self.text_error = text_error
        self.evidence_error = evidence_error
        self.text_calls: list[dict[str, Any]] = []
        self.evidence_calls: list[dict[str, Any]] = []

    def load_authorized_texts(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.text_calls.append(kwargs)
        if self.text_error is not None:
            raise self.text_error
        return [_text_record(ref["chunk_id"]) for ref in kwargs["chunk_refs"]]

    def load_authorized_evidence(self, **kwargs: Any) -> Any:
        self.evidence_calls.append(kwargs)
        if self.evidence_error is not None:
            raise self.evidence_error
        if self.evidence is not None:
            return deepcopy(self.evidence)
        return [
            _evidence_record(ref["chunk_id"])
            for ref in reversed(kwargs["chunk_refs"])
        ]


class FakeReranker:
    def rerank_documents(self, query: str, documents: list[str], **_kwargs: Any) -> dict[str, Any]:
        return {
            "alias": "mock-reranker",
            "results": [
                {"index": index, "score": round(0.95 - index * 0.1, 2)}
                for index in range(len(documents))
            ],
        }


def test_runtime_builds_owner_scoped_persistence_compatible_package() -> None:
    provider = FakeCandidateProvider()
    materializer = FakeMaterializer()
    runtime = _runtime(provider=provider, materializer=materializer)

    package = runtime.build_package(
        _payload(top_k=1, include_neighbors=True),
        access_context=_context(),
    )

    assert package["retrieval_runtime_schema_version"] == "cx_hybrid_retrieval_runtime.v1"
    assert package["status"] == "READY"
    assert package["tenant_ref_type"] == "oa.tenant"
    assert package["tenant_ref_id"] == "tenant-one"
    assert package["owner_subject_ref_type"] == "oa.user"
    assert package["owner_subject_ref_id"] == "owner-one"
    assert package["permission_snapshot"]["policy_version"] == "cx.private_owner_active.v1"
    assert package["retrieval_profile"]["quality_policy"]["vector_weight"] == 0.7
    assert package["score_summary"]["rerank_state"] == "APPLIED"
    assert package["evidence_items"][0]["neighbor_context"] == [
        {"policy": "not_loaded_in_s95"}
    ]
    assert package["evidence_items"][0]["permission_result"]["reason"] == (
        "PRIVATE_OWNER_ACTIVE"
    )
    assert provider.calls[0]["requested_document_ids"] == [DOC_ID]
    assert materializer.evidence_calls[0]["access_context"] == _context()

    preview = build_retrieval_package_persistence_preview(package)
    serialized = json.dumps(preview)
    assert QUERY not in serialized
    assert TEXTS[CHUNK_ONE] not in serialized
    assert preview["header"]["query_text_preview"] is None
    assert preview["evidence_items"][0]["evidence_text_preview"] is None
    assert preview["header"]["retrieval_policy_id"] == (
        "weighted_rrf_vector_bm25_v1"
    )
    assert preview["header"]["permission_snapshot_hash"]


def test_runtime_is_deterministic_except_for_injected_clock() -> None:
    runtime = _runtime()

    first = runtime.build_package(_payload(), access_context=_context())
    second = runtime.build_package(_payload(), access_context=_context())

    assert first == second
    assert len(first["package_hash"]) == 64
    assert first["query_embedding_snapshot"] == {
        "provided": True,
        "embedding_sha256": "e" * 64,
        "vector_dimension": 2,
    }


def test_runtime_uses_utc_clock_by_default() -> None:
    runtime = PermissionFilteredHybridPackageRuntime(
        candidate_provider=FakeCandidateProvider(),
        evidence_materializer=FakeMaterializer(),
        rerank_client=FakeReranker(),
    )

    package = runtime.build_package(_payload(), access_context=_context())

    assert package["created_at"].endswith("+00:00")


def test_runtime_builds_no_answer_without_materializing_evidence() -> None:
    candidate_set = _candidate_set()
    candidate_set["lexical_candidates"] = {
        "candidate_source": "postgresql_bm25",
        "candidate_count": 0,
        "candidates": [],
    }
    candidate_set["vector_candidates"].update(
        {"status": "BM25_ONLY", "candidate_count": 0, "candidates": []}
    )
    materializer = FakeMaterializer(evidence_error=AssertionError("must not load"))
    runtime = _runtime(
        provider=FakeCandidateProvider(candidate_set),
        materializer=materializer,
        reranker=None,
    )

    package = runtime.build_package(_payload(), access_context=_context())

    assert package["status"] == "NO_ANSWER"
    assert package["no_answer_reason"] == "no_permission_admitted_candidates"
    assert package["score_summary"]["confidence_bucket"] == "NO_ANSWER"
    assert package["warnings"] == [
        "vector_retrieval_bm25_only",
        "rerank_not_applied",
    ]
    assert materializer.evidence_calls == []


def test_runtime_reports_low_confidence_for_bm25_only_low_weight() -> None:
    candidate_set = _candidate_set()
    candidate_set["vector_candidates"].update(
        {"status": "BM25_ONLY", "candidate_count": 0, "candidates": []}
    )
    runtime = _runtime(
        provider=FakeCandidateProvider(candidate_set),
        reranker=None,
        policy=HybridRankingPolicy(vector_weight=0.9, bm25_weight=0.1),
    )

    package = runtime.build_package(_payload(top_k=1), access_context=_context())

    assert package["status"] == "LOW_CONFIDENCE"
    assert package["no_answer_reason"] == "best_score_below_threshold"
    assert package["score_summary"]["confidence_bucket"] == "LOW_CONFIDENCE"


@pytest.mark.parametrize(
    "payload",
    [
        "bad",
        {},
        {"query_text": 1, "document_scope": {"document_ids": [DOC_ID]}},
        {"query_text": " ", "document_scope": {"document_ids": [DOC_ID]}},
        {
            "query_text": "x" * (MAX_QUERY_TEXT_LENGTH + 1),
            "document_scope": {"document_ids": [DOC_ID]},
        },
        {"query_text": QUERY},
        {"query_text": QUERY, "document_scope": "bad"},
        {"query_text": QUERY, "document_scope": {"document_ids": "bad"}},
        {"query_text": QUERY, "document_scope": {"document_ids": []}},
        {"query_text": QUERY, "document_scope": {"document_ids": [""]}},
        {"query_text": QUERY, "document_scope": {"document_ids": [DOC_ID, DOC_ID]}},
        {**_payload(), "top_k": True},
        {**_payload(), "top_k": 0},
        {**_payload(), "top_k": 21},
        {**_payload(), "purpose": "bad"},
        {**_payload(), "include_neighbors": "yes"},
        {**_payload(), "include_source_preview": "yes"},
    ],
)
def test_runtime_rejects_invalid_requests(payload: object) -> None:
    with pytest.raises(HybridRetrievalPackageError) as exc:
        _runtime().build_package(payload, access_context=_context())  # type: ignore[arg-type]

    assert exc.value.status_code == 422
    assert exc.value.error_code == "CX_HYBRID_RETRIEVAL_REQUEST_INVALID"


def test_runtime_accepts_user_prompt_alias_and_supported_purposes() -> None:
    payload = _payload()
    payload.pop("query_text")
    payload["user_prompt"] = QUERY
    payload["purpose"] = "confidence_probe"

    package = _runtime().build_package(payload, access_context=_context())

    assert package["query_text"] == QUERY
    assert package["purpose"] == "confidence_probe"


def test_candidate_provider_errors_are_preserved_or_redacted() -> None:
    expected = HybridRetrievalPackageError(
        status_code=409,
        error_code="EXPECTED",
        detail="expected",
    )
    with pytest.raises(HybridRetrievalPackageError) as preserved:
        _runtime(provider=FakeCandidateProvider(error=expected)).build_package(
            _payload(), access_context=_context()
        )
    with pytest.raises(HybridRetrievalPackageError) as redacted:
        _runtime(
            provider=FakeCandidateProvider(error=RuntimeError("SECRET_PROVIDER"))
        ).build_package(_payload(), access_context=_context())

    assert preserved.value is expected
    assert redacted.value.error_code == "CX_HYBRID_CANDIDATE_PROVIDER_UNAVAILABLE"
    assert redacted.value.retryable is True
    assert "SECRET_PROVIDER" not in redacted.value.detail


def test_evidence_loader_failure_is_redacted() -> None:
    runtime = _runtime(
        materializer=FakeMaterializer(
            evidence_error=RuntimeError("SECRET_EVIDENCE")
        )
    )

    with pytest.raises(HybridRetrievalPackageError) as exc:
        runtime.build_package(_payload(), access_context=_context())

    assert exc.value.error_code == "CX_AUTHORIZED_EVIDENCE_UNAVAILABLE"
    assert exc.value.retryable is True
    assert "SECRET_EVIDENCE" not in exc.value.detail


@pytest.mark.parametrize(
    "records",
    [
        "bad",
        ["bad"],
        [{**_evidence_record(CHUNK_ONE), "content_object_id": ""}],
        [{**_evidence_record(CHUNK_ONE), "content_object_id": None}],
        [{**_evidence_record(CHUNK_ONE), "chunk_id": ""}],
        [{**_evidence_record(CHUNK_ONE), "chunk_policy_id": ""}],
        [_evidence_record(CHUNK_ONE), _evidence_record(CHUNK_ONE)],
        [{**_evidence_record(CHUNK_ONE), "chunk_text": None}],
        [{**_evidence_record(CHUNK_ONE), "chunk_text": ""}],
        [{**_evidence_record(CHUNK_ONE), "text_sha256": "bad"}],
        [{**_evidence_record(CHUNK_ONE), "text_sha256": "0" * 64}],
        [{**_evidence_record(CHUNK_ONE), "start_offset": True}],
        [{**_evidence_record(CHUNK_ONE), "start_offset": -1}],
        [{**_evidence_record(CHUNK_ONE), "end_offset": True}],
        [{**_evidence_record(CHUNK_ONE), "end_offset": -1}],
        [{**_evidence_record(CHUNK_ONE), "matched_terms": "bad"}],
        [{**_evidence_record(CHUNK_ONE), "matched_terms": [""]}],
        [_evidence_record("unexpected")],
    ],
)
def test_evidence_lineage_validation_is_fail_closed(records: object) -> None:
    with pytest.raises(HybridRetrievalPackageError) as exc:
        _runtime(
            materializer=FakeMaterializer(evidence=records),
            policy=HybridRankingPolicy(rerank_candidate_limit=1),
        ).build_package(_payload(top_k=1), access_context=_context())

    assert exc.value.error_code == "CX_AUTHORIZED_EVIDENCE_LINEAGE_INVALID"


def test_evidence_lineage_rejects_ranked_hash_mismatch() -> None:
    candidate_set = _candidate_set()
    candidate_set["lexical_candidates"]["candidates"][0]["text_sha256"] = "f" * 64

    with pytest.raises(HybridRetrievalPackageError) as exc:
        _runtime(
            provider=FakeCandidateProvider(candidate_set),
            reranker=None,
        ).build_package(_payload(top_k=1), access_context=_context())

    assert exc.value.error_code == "CX_AUTHORIZED_EVIDENCE_LINEAGE_INVALID"


def test_candidate_embedding_hash_must_be_valid() -> None:
    candidate_set = _candidate_set()
    candidate_set["query_vector_sha256"] = "bad"

    with pytest.raises(HybridRetrievalPackageError) as exc:
        _runtime(provider=FakeCandidateProvider(candidate_set)).build_package(
            _payload(), access_context=_context()
        )

    assert exc.value.error_code == "CX_HYBRID_CANDIDATE_METADATA_INVALID"


def test_route_uses_hardened_runtime_and_existing_package_store() -> None:
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    store = ContentIngestionStore()
    register_retrieval_routes(app, store=store, hybrid_runtime=_runtime())
    client = TestClient(app)

    response = client.post(
        "/api/v1/retrieval/context",
        json=_payload(top_k=1),
        headers=_headers(),
    )

    assert response.status_code == 200
    package = response.json()
    assert package["retrieval_runtime_schema_version"] == "cx_hybrid_retrieval_runtime.v1"
    assert store.get_retrieval_package(package["retrieval_package_id"]) == package

    loaded = client.get(
        f"/api/v1/retrieval/context/{package['retrieval_package_id']}",
        headers=_headers(),
    )
    assert loaded.status_code == 200
    assert loaded.json()["package_hash"] == package["package_hash"]


@pytest.mark.parametrize(
    "error",
    [
        HybridRetrievalPackageError(
            status_code=422,
            error_code="CX_RUNTIME_INVALID",
            detail="invalid",
        ),
        HybridRankingError(
            status_code=502,
            error_code="CX_RANKING_INVALID",
            detail="invalid",
            retryable=True,
        ),
    ],
)
def test_route_maps_hardened_runtime_errors(error: Exception) -> None:
    class FailingRuntime:
        def build_package(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            raise error

    app = build_service_app(SERVICE_SPECS["nex-cx"])
    register_retrieval_routes(
        app,
        store=ContentIngestionStore(),
        hybrid_runtime=FailingRuntime(),
    )

    response = TestClient(app).post(
        "/api/v1/retrieval/context",
        json=_payload(),
        headers=_headers(),
    )

    assert response.status_code == error.status_code  # type: ignore[attr-defined]
    assert response.json()["error_code"] == error.error_code  # type: ignore[attr-defined]


def _runtime(
    *,
    provider: FakeCandidateProvider | None = None,
    materializer: FakeMaterializer | None = None,
    reranker: FakeReranker | None | object = ...,
    policy: HybridRankingPolicy = HybridRankingPolicy(),
) -> PermissionFilteredHybridPackageRuntime:
    actual_reranker = FakeReranker() if reranker is ... else reranker
    return PermissionFilteredHybridPackageRuntime(
        candidate_provider=provider or FakeCandidateProvider(),
        evidence_materializer=materializer or FakeMaterializer(),
        rerank_client=actual_reranker,  # type: ignore[arg-type]
        ranking_policy=policy,
        now_factory=lambda: "2026-09-22T08:00:00+00:00",
    )


def _context() -> CxAccessContext:
    return CxAccessContext(
        caller_service_id="nex-ae-api",
        tenant_id="tenant-one",
        subject_id="owner-one",
        request_id="request-0947",
        trace_id="94700000000000000000000000000001",
        scopes=("service:call",),
    )


def _candidate_set() -> dict[str, Any]:
    return {
        "hybrid_candidate_set_schema_version": "cx_hybrid_candidate_set.v1",
        "permission_policy": "cx.private_owner_active.v1",
        "permission_enforced_before_candidates": True,
        "query_sha256": _digest(QUERY),
        "query_vector_sha256": "e" * 64,
        "tokenizer_profile": {
            "bm25_tokenizer": "mecab_ko",
            "fallback_used": False,
        },
        "permission_snapshot": {
            "permission_snapshot_schema_version": "cx_retrieval_permission_snapshot.v1",
            "actor_type": "oa.user",
            "actor_id": "owner-one",
            "tenant_ref": {"type": "oa.tenant", "id": "tenant-one"},
            "scope_applied": {"type": "document_ids", "document_ids": [DOC_ID]},
            "visible_document_count": 1,
            "policy_version": "cx.private_owner_active.v1",
        },
        "lexical_candidates": {
            "candidate_source": "postgresql_bm25",
            "candidate_count": 2,
            "candidates": [
                _lexical(CHUNK_ONE, 2.0),
                _lexical(CHUNK_TWO, 1.0),
            ],
        },
        "vector_candidates": {
            "candidate_source": "postgresql_pgvector",
            "status": "READY",
            "query_dimension": 2,
            "candidate_count": 2,
            "candidates": [
                _vector(CHUNK_ONE, 0.9),
                _vector(CHUNK_TWO, 0.8),
            ],
        },
    }


def _lexical(chunk_id: str, score: float) -> dict[str, Any]:
    return {
        "lexical_candidate_schema_version": "cx_lexical_candidate.v1",
        "candidate_source": "postgresql_bm25",
        "content_object_id": DOC_ID,
        "chunk_id": chunk_id,
        "text_sha256": _digest(TEXTS[chunk_id]),
        "bm25_score": score,
    }


def _vector(chunk_id: str, score: float) -> dict[str, Any]:
    return {
        "vector_candidate_schema_version": "cx_vector_candidate.v1",
        "candidate_source": "postgresql_pgvector",
        "content_object_id": DOC_ID,
        "chunk_id": chunk_id,
        "vector_score": score,
    }


def _text_record(chunk_id: str) -> dict[str, Any]:
    text = TEXTS[chunk_id]
    return {
        "content_object_id": DOC_ID,
        "chunk_id": chunk_id,
        "chunk_text": text,
        "text_sha256": _digest(text),
    }


def _headers() -> dict[str, str]:
    token = issue_mock_service_token(
        service_id="nex-ae-api",
        audience="nex-cx",
    ).access_token
    return {
        "Authorization": f"Bearer {token}",
        "X-NEX-Tenant-ID": "tenant-one",
        "X-NEX-Subject-ID": "owner-one",
        "X-Request-ID": "request-0947",
        "traceparent": "00-94700000000000000000000000000001-00f067aa0ba902b7-01",
    }
