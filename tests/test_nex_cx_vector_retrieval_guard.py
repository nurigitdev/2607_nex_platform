from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest

from nex_cx.access_context import CxAccessContext
from nex_cx.vector_index_freshness import (
    VectorIndexContractError,
    build_embedding_profile,
    build_source_snapshot,
    build_vector_index_manifest,
    build_vector_payload_snapshot,
    mark_vector_index_ready,
)
from nex_cx.vector_index_repository import InMemoryVectorIndexRepository
from nex_cx.vector_retrieval_guard import (
    VectorRetrievalError,
    search_fresh_vector_index,
)


def _context(*, owner: str = "owner-a") -> CxAccessContext:
    return CxAccessContext(
        caller_service_id="nex-cx",
        tenant_id="tenant-a",
        subject_id=owner,
        request_id="request-0937",
        trace_id="93700000000000000000000000000001",
        scopes=("service:call",),
    )


def _parts(*, status: str = "READY"):
    source = build_source_snapshot(
        chunk_set_id=str(uuid4()),
        chunk_policy_id="1000_100",
        source_markdown_sha256="1" * 64,
        chunks=[
            {"chunk_id": str(uuid4()), "ordinal": 0, "text_sha256": "2" * 64}
        ],
    )
    profile = build_embedding_profile(
        provider_alias="mock",
        model_profile_id="qwen-test",
        model_revision="test",
        deployment_id="local",
        vector_dimension=2,
    )
    manifest = build_vector_index_manifest(
        content_object_id=str(uuid4()),
        tenant_ref={"type": "oa.tenant", "id": "tenant-a"},
        owner_subject_ref={"type": "oa.user", "id": "owner-a"},
        source_snapshot=source,
        embedding_profile=profile,
        trace_id="trace-0937",
        request_id="request-0937",
        observed_at="2026-09-21T15:00:00Z",
    )
    receipt = {
        "chunk_id": source["chunk_refs"][0]["chunk_id"],
        "embedding_sha256": "3" * 64,
        "vector_dimension": 2,
        "storage_uri": f"cx-private://pgvector/{uuid4()}",
    }
    if status == "READY":
        manifest = mark_vector_index_ready(
            manifest,
            payload_receipts=[receipt],
            observed_at="2026-09-21T15:01:00Z",
        )
    return source, profile, manifest, receipt


class _BoundSearch:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.search_calls = 0

    def payload_snapshot(self, *, access_context):
        assert access_context == _context()
        return deepcopy(self.snapshot)

    def search(self, *, access_context, query_vector, limit):
        self.search_calls += 1
        assert access_context == _context()
        assert query_vector == (1.0, 0.0)
        assert limit == 4
        return [{"chunk_id": "chunk-a", "score": 1.0, "distance": 0.0}]


class _Adapter:
    def __init__(self, bound):
        self.bound = bound
        self.bound_manifest = None

    def bind_index(self, manifest):
        self.bound_manifest = deepcopy(manifest)
        return self.bound


def _search(source, profile, manifest, receipt, *, context=None, snapshot=None):
    repository = InMemoryVectorIndexRepository()
    repository.create(manifest)
    bound = _BoundSearch(snapshot or build_vector_payload_snapshot([receipt]))
    result = search_fresh_vector_index(
        access_context=context or _context(),
        vector_index_id=manifest["vector_index_id"],
        source_snapshot=source,
        embedding_profile=profile,
        query_vector=(1.0, 0.0),
        limit=4,
        repository=repository,
        vector_store=_Adapter(bound),
    )
    return result, bound


def test_fresh_owner_scoped_vector_index_searches_after_payload_verification():
    source, profile, manifest, receipt = _parts()
    result, bound = _search(source, profile, manifest, receipt)

    assert result["retrieval_schema_version"] == "cx_vector_retrieval.v1"
    assert result["vector_index_id"] == manifest["vector_index_id"]
    assert result["content_object_id"] == manifest["content_object_id"]
    assert result["freshness"]["retrieval_usable"] is True
    assert result["matches"][0]["score"] == 1.0
    assert bound.search_calls == 1


def test_owner_mismatch_is_indistinguishable_from_missing_index():
    source, profile, manifest, receipt = _parts()
    repository = InMemoryVectorIndexRepository()
    repository.create(manifest)
    bound = _BoundSearch(build_vector_payload_snapshot([receipt]))

    with pytest.raises(VectorRetrievalError) as caught:
        search_fresh_vector_index(
            access_context=_context(owner="other"),
            vector_index_id=manifest["vector_index_id"],
            source_snapshot=source,
            embedding_profile=profile,
            query_vector=(1.0, 0.0),
            limit=1,
            repository=repository,
            vector_store=_Adapter(bound),
        )

    assert caught.value.status_code == 404
    assert caught.value.error_code == "CX_VECTOR_INDEX_NOT_FOUND"
    assert caught.value.freshness is None
    assert bound.search_calls == 0


@pytest.mark.parametrize(
    ("drift", "reason", "retryable"),
    [
        ("building", None, True),
        ("source", "SOURCE_CHANGED", False),
        ("profile", "MODEL_REVISION_CHANGED", False),
        ("count", "PAYLOAD_COUNT_MISMATCH", False),
        ("fingerprint", "PAYLOAD_FINGERPRINT_MISMATCH", False),
    ],
)
def test_search_rejects_unready_or_drifted_index_before_vector_query(
    drift, reason, retryable
):
    source, profile, manifest, receipt = _parts(
        status="BUILDING" if drift == "building" else "READY"
    )
    current_source = deepcopy(source)
    current_profile = deepcopy(profile)
    snapshot = build_vector_payload_snapshot([receipt])
    if drift == "source":
        current_source = build_source_snapshot(
            chunk_set_id=source["chunk_set_id"],
            chunk_policy_id=source["chunk_policy_id"],
            source_markdown_sha256="4" * 64,
            chunks=source["chunk_refs"],
        )
    elif drift == "profile":
        current_profile = build_embedding_profile(
            provider_alias=profile["provider_alias"],
            model_profile_id=profile["model_profile_id"],
            model_revision="changed",
            deployment_id=profile["deployment_id"],
            vector_dimension=2,
        )
    elif drift == "count":
        snapshot = {"payload_count": 0, "payload_fingerprint": snapshot["payload_fingerprint"]}
    elif drift == "fingerprint":
        snapshot = {"payload_count": 1, "payload_fingerprint": "5" * 64}
    repository = InMemoryVectorIndexRepository()
    repository.create(manifest)
    bound = _BoundSearch(snapshot)

    with pytest.raises(VectorRetrievalError) as caught:
        search_fresh_vector_index(
            access_context=_context(),
            vector_index_id=manifest["vector_index_id"],
            source_snapshot=current_source,
            embedding_profile=current_profile,
            query_vector=(1.0, 0.0),
            limit=4,
            repository=repository,
            vector_store=_Adapter(bound),
        )

    assert caught.value.status_code == 409
    assert caught.value.error_code == "CX_VECTOR_INDEX_NOT_READY"
    assert caught.value.retryable is retryable
    assert caught.value.freshness["reason"] == reason
    assert reason or "INDEX_NOT_READY" in caught.value.detail
    assert bound.search_calls == 0


def test_payload_snapshot_validation_and_exception_traceback_compatibility():
    _source, _profile, _manifest, receipt = _parts()
    with pytest.raises(VectorIndexContractError) as invalid:
        build_vector_payload_snapshot("not-a-sequence")  # type: ignore[arg-type]
    with pytest.raises(VectorIndexContractError) as duplicate:
        build_vector_payload_snapshot([receipt, receipt])
    try:
        raise VectorIndexContractError("code", "detail")
    except VectorIndexContractError as caught:
        caught.__traceback__ = caught.__traceback__
        assert str(caught) == "detail"
    assert invalid.value.error_code == "cx.vector_index.payload_receipts_invalid"
    assert duplicate.value.error_code == "cx.vector_index.payload_set_mismatch"
