from __future__ import annotations

from copy import deepcopy
import math
from typing import Any
from uuid import uuid4

import pytest

from nex_cx.access_context import CxAccessContext
from nex_cx.vector_candidates import (
    VectorCandidateError,
    collect_fresh_vector_candidates,
)
from nex_cx.vector_index_freshness import (
    build_embedding_profile,
    build_source_snapshot,
    build_vector_index_manifest,
    build_vector_payload_snapshot,
    mark_vector_index_ready,
)
from nex_cx.vector_index_repository import InMemoryVectorIndexRepository
from nex_cx.vector_retrieval_guard import VectorRetrievalError


def _context(*, owner: str = "owner-a") -> CxAccessContext:
    return CxAccessContext(
        caller_service_id="nex-cx",
        tenant_id="tenant-a",
        subject_id=owner,
        request_id="request-0944",
        trace_id="94400000000000000000000000000001",
        scopes=("service:call",),
    )


def _parts(
    *,
    owner: str = "owner-a",
    status: str = "READY",
    chunk_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    chunk_id = chunk_id or str(uuid4())
    source = build_source_snapshot(
        chunk_set_id=str(uuid4()),
        chunk_policy_id="1000_100",
        source_markdown_sha256="1" * 64,
        chunks=[{"chunk_id": chunk_id, "ordinal": 0, "text_sha256": "2" * 64}],
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
        owner_subject_ref={"type": "oa.user", "id": owner},
        source_snapshot=source,
        embedding_profile=profile,
        trace_id="trace-0944",
        request_id="request-0944",
        observed_at="2026-09-22T01:00:00Z",
    )
    receipt = {
        "chunk_id": chunk_id,
        "embedding_sha256": "3" * 64,
        "vector_dimension": 2,
        "storage_uri": f"cx-private://pgvector/{uuid4()}",
    }
    if status == "READY":
        manifest = mark_vector_index_ready(
            manifest,
            payload_receipts=[receipt],
            observed_at="2026-09-22T01:01:00Z",
        )
    target = {
        "vector_index_id": manifest["vector_index_id"],
        "content_object_id": manifest["content_object_id"],
        "source_snapshot": source,
        "embedding_profile": profile,
        "permission_decision": {
            "visible": True,
            "policy_version": "cx.private_owner_active.v1",
        },
    }
    return target, manifest, receipt, source


class _Bound:
    def __init__(self, snapshot: dict[str, Any], matches: list[dict[str, Any]]) -> None:
        self.snapshot = snapshot
        self.matches = matches
        self.search_calls = 0

    def payload_snapshot(self, *, access_context: CxAccessContext) -> dict[str, Any]:
        assert access_context.tenant_id == "tenant-a"
        return deepcopy(self.snapshot)

    def search(
        self,
        *,
        access_context: CxAccessContext,
        query_vector: tuple[float, ...],
        limit: int,
    ) -> list[dict[str, Any]]:
        self.search_calls += 1
        assert access_context.subject_id == "owner-a"
        assert query_vector == (1.0, 0.0)
        return deepcopy(self.matches[:limit])


class _Store:
    def __init__(self, bounds: dict[str, _Bound]) -> None:
        self.bounds = bounds

    def bind_index(self, manifest: dict[str, Any]) -> _Bound:
        return self.bounds[manifest["vector_index_id"]]


def _run(
    parts: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]],
    *,
    matches: dict[str, list[dict[str, Any]]] | None = None,
    context: CxAccessContext | None = None,
    limit: int = 10,
) -> tuple[dict[str, Any], dict[str, _Bound]]:
    repository = InMemoryVectorIndexRepository()
    bounds: dict[str, _Bound] = {}
    targets: list[dict[str, Any]] = []
    for target, manifest, receipt, _source in parts:
        repository.create(manifest)
        index_id = manifest["vector_index_id"]
        bounds[index_id] = _Bound(
            build_vector_payload_snapshot([receipt]),
            (matches or {}).get(
                index_id,
                [{"chunk_id": receipt["chunk_id"], "score": 0.75, "distance": 0.25}],
            ),
        )
        targets.append(target)
    return (
        collect_fresh_vector_candidates(
            access_context=context or _context(),
            targets=targets,
            query_vector=(1, 0),
            limit=limit,
            repository=repository,
            vector_store=_Store(bounds),
        ),
        bounds,
    )


def test_collects_fresh_candidates_with_global_deterministic_ranking() -> None:
    first = _parts()
    second = _parts()
    matches = {
        first[1]["vector_index_id"]: [
            {"chunk_id": first[2]["chunk_id"], "score": 0.4, "distance": 0.6}
        ],
        second[1]["vector_index_id"]: [
            {"chunk_id": second[2]["chunk_id"], "score": 0.9, "distance": 0.1}
        ],
    }

    result, bounds = _run([first, second], matches=matches, limit=1)

    assert result["vector_candidate_result_schema_version"] == "cx_vector_candidate_result.v1"
    assert result["candidate_source"] == "postgresql_pgvector"
    assert result["query_dimension"] == 2
    assert result["requested_index_count"] == 2
    assert result["admitted_index_count"] == 2
    assert result["excluded_index_count"] == 0
    assert result["exclusion_counts"] == {}
    assert result["candidate_count"] == 1
    assert result["candidates"][0] == {
        "vector_candidate_schema_version": "cx_vector_candidate.v1",
        "candidate_source": "postgresql_pgvector",
        "content_object_id": second[1]["content_object_id"],
        "vector_index_id": second[1]["vector_index_id"],
        "chunk_id": second[2]["chunk_id"],
        "vector_rank": 1,
        "vector_score": 0.9,
        "vector_distance": 0.1,
        "candidate_rank": 1,
    }
    assert all(bound.search_calls == 1 for bound in bounds.values())


def test_excludes_unready_and_owner_hidden_indexes_without_leaking_ids() -> None:
    building = _parts(status="BUILDING")
    foreign = _parts(owner="owner-b")

    result, bounds = _run([building, foreign])

    assert result["candidates"] == []
    assert result["admitted_index_count"] == 0
    assert result["excluded_index_count"] == 2
    assert result["exclusion_counts"] == {
        "INDEX_NOT_FOUND": 1,
        "INDEX_NOT_READY": 1,
    }
    assert all(bound.search_calls == 0 for bound in bounds.values())
    assert foreign[1]["vector_index_id"] not in str(result)


def test_excludes_source_drift_with_metadata_only_reason() -> None:
    stale = _parts()
    stale[0]["source_snapshot"] = build_source_snapshot(
        chunk_set_id=stale[3]["chunk_set_id"],
        chunk_policy_id=stale[3]["chunk_policy_id"],
        source_markdown_sha256="4" * 64,
        chunks=stale[3]["chunk_refs"],
    )

    result, bounds = _run([stale])

    assert result["exclusion_counts"] == {"SOURCE_CHANGED": 1}
    assert result["candidates"] == []
    assert next(iter(bounds.values())).search_calls == 0


def test_deduplicates_same_chunk_by_score_then_index_id() -> None:
    shared_chunk = str(uuid4())
    first = _parts(chunk_id=shared_chunk)
    second = _parts(chunk_id=shared_chunk)
    for part in (first, second):
        part[0]["content_object_id"] = "shared-content"
        part[1]["content_object_id"] = "shared-content"
    ordered = sorted([first, second], key=lambda part: part[1]["vector_index_id"])
    matches = {
        part[1]["vector_index_id"]: [
            {"chunk_id": shared_chunk, "score": 0.8, "distance": 0.2}
        ]
        for part in ordered
    }

    result, _bounds = _run(ordered, matches=matches)

    assert result["candidate_count"] == 1
    assert result["candidates"][0]["vector_index_id"] == ordered[0][1]["vector_index_id"]


@pytest.mark.parametrize(
    "targets",
    [
        "target",
        [None],
        [{"vector_index_id": "id"}],
        [
            {
                "vector_index_id": "id",
                "content_object_id": "content",
                "source_snapshot": {"chunk_refs": []},
                "embedding_profile": {"vector_dimension": 2},
                "permission_decision": {
                    "visible": False,
                    "policy_version": "cx.private_owner_active.v1",
                },
            }
        ],
    ],
)
def test_rejects_invalid_or_unadmitted_targets(targets: object) -> None:
    with pytest.raises(VectorCandidateError) as captured:
        collect_fresh_vector_candidates(
            access_context=_context(),
            targets=targets,  # type: ignore[arg-type]
            query_vector=(1.0, 0.0),
            limit=1,
            repository=InMemoryVectorIndexRepository(),
            vector_store=_Store({}),
        )

    assert captured.value.error_code == "CX_VECTOR_TARGETS_INVALID"


def test_rejects_duplicate_indexes_malformed_chunks_and_excess_targets() -> None:
    target, _manifest, _receipt, _source = _parts()
    malformed = deepcopy(target)
    malformed["source_snapshot"]["chunk_refs"] = [{"chunk_id": "same"}, {"chunk_id": "same"}]
    no_dimension = deepcopy(target)
    no_dimension["embedding_profile"].pop("vector_dimension")
    wrong_dimension = deepcopy(target)
    wrong_dimension["embedding_profile"]["vector_dimension"] = 3
    boolean_dimension = deepcopy(target)
    boolean_dimension["embedding_profile"]["vector_dimension"] = True
    no_chunks = deepcopy(target)
    no_chunks["source_snapshot"]["chunk_refs"] = "wrong"
    bad_chunk = deepcopy(target)
    bad_chunk["source_snapshot"]["chunk_refs"] = [None]
    for targets in (
        [target, target],
        [malformed],
        [no_dimension],
        [wrong_dimension],
        [boolean_dimension],
        [no_chunks],
        [bad_chunk],
        [target] * 101,
    ):
        with pytest.raises(VectorCandidateError) as captured:
            collect_fresh_vector_candidates(
                access_context=_context(),
                targets=targets,
                query_vector=(1.0, 0.0),
                limit=1,
                repository=InMemoryVectorIndexRepository(),
                vector_store=_Store({}),
            )
        assert captured.value.error_code == "CX_VECTOR_TARGETS_INVALID"


@pytest.mark.parametrize(
    "query",
    ["vector", [], [True], [math.nan], [math.inf], [1.0] * 8193],
)
def test_rejects_invalid_query_vectors(query: object) -> None:
    with pytest.raises(VectorCandidateError) as captured:
        collect_fresh_vector_candidates(
            access_context=_context(),
            targets=[],
            query_vector=query,  # type: ignore[arg-type]
            limit=1,
            repository=InMemoryVectorIndexRepository(),
            vector_store=_Store({}),
        )

    assert captured.value.error_code == "CX_VECTOR_QUERY_INVALID"


@pytest.mark.parametrize("limit", [True, 0, 101, 1.5])
def test_rejects_invalid_limits(limit: object) -> None:
    with pytest.raises(VectorCandidateError) as captured:
        collect_fresh_vector_candidates(
            access_context=_context(),
            targets=[],
            query_vector=(1.0,),
            limit=limit,  # type: ignore[arg-type]
            repository=InMemoryVectorIndexRepository(),
            vector_store=_Store({}),
        )

    assert captured.value.error_code == "CX_VECTOR_CANDIDATE_LIMIT_INVALID"


@pytest.mark.parametrize(
    "mutate",
    [
        None,
        lambda target, result: result.update(vector_index_id="wrong"),
        lambda target, result: result.update(content_object_id="wrong"),
        lambda target, result: result.update(freshness={"retrieval_usable": False}),
        lambda target, result: result.update(matches="wrong"),
        lambda target, result: result.update(matches=[None]),
        lambda target, result: result.update(matches=[{"chunk_id": "foreign", "score": 1.0, "distance": 0.0}]),
        lambda target, result: result.update(matches=[{"chunk_id": next(iter(target["source_chunk_ids"])), "score": math.nan, "distance": 0.0}]),
        lambda target, result: result.update(matches=[{"chunk_id": next(iter(target["source_chunk_ids"])), "score": 1.0, "distance": True}]),
    ],
)
def test_rejects_malformed_guard_results(monkeypatch, mutate) -> None:
    target, _manifest, receipt, _source = _parts()

    def fake_search(**_kwargs):
        normalized_target = {
            **target,
            "source_chunk_ids": frozenset({receipt["chunk_id"]}),
        }
        result: Any = {
            "vector_index_id": target["vector_index_id"],
            "content_object_id": target["content_object_id"],
            "freshness": {"retrieval_usable": True},
            "matches": [
                {"chunk_id": receipt["chunk_id"], "score": 1.0, "distance": 0.0}
            ],
        }
        if mutate is None:
            return "wrong"
        mutate(normalized_target, result)
        return result

    monkeypatch.setattr("nex_cx.vector_candidates.search_fresh_vector_index", fake_search)
    with pytest.raises(VectorCandidateError) as captured:
        collect_fresh_vector_candidates(
            access_context=_context(),
            targets=[target],
            query_vector=(1.0, 0.0),
            limit=1,
            repository=InMemoryVectorIndexRepository(),
            vector_store=_Store({}),
        )

    assert captured.value.error_code == "CX_VECTOR_CANDIDATE_RESULT_INVALID"


def test_unexpected_guard_errors_are_redacted(monkeypatch) -> None:
    target, _manifest, _receipt, _source = _parts()

    def unexpected(**_kwargs):
        raise RuntimeError("private database detail")

    monkeypatch.setattr("nex_cx.vector_candidates.search_fresh_vector_index", unexpected)
    with pytest.raises(VectorCandidateError) as captured:
        collect_fresh_vector_candidates(
            access_context=_context(),
            targets=[target],
            query_vector=(1.0, 0.0),
            limit=1,
            repository=InMemoryVectorIndexRepository(),
            vector_store=_Store({}),
        )

    assert captured.value.error_code == "CX_VECTOR_CANDIDATE_SEARCH_UNAVAILABLE"
    assert "private" not in captured.value.detail


def test_unexpected_retrieval_error_is_redacted(monkeypatch) -> None:
    target, _manifest, _receipt, _source = _parts()

    def unexpected(**_kwargs):
        raise VectorRetrievalError(
            status_code=422,
            error_code="UNEXPECTED",
            detail="private detail",
        )

    monkeypatch.setattr("nex_cx.vector_candidates.search_fresh_vector_index", unexpected)
    with pytest.raises(VectorCandidateError) as captured:
        collect_fresh_vector_candidates(
            access_context=_context(),
            targets=[target],
            query_vector=(1.0, 0.0),
            limit=1,
            repository=InMemoryVectorIndexRepository(),
            vector_store=_Store({}),
        )

    assert captured.value.error_code == "CX_VECTOR_CANDIDATE_SEARCH_UNAVAILABLE"


@pytest.mark.parametrize("freshness", [None, {}])
def test_not_ready_without_reason_uses_generic_exclusion(
    monkeypatch,
    freshness,
) -> None:
    target, _manifest, _receipt, _source = _parts()

    def not_ready(**_kwargs):
        raise VectorRetrievalError(
            status_code=409,
            error_code="CX_VECTOR_INDEX_NOT_READY",
            detail="not ready",
            freshness=freshness,
        )

    monkeypatch.setattr("nex_cx.vector_candidates.search_fresh_vector_index", not_ready)
    result = collect_fresh_vector_candidates(
        access_context=_context(),
        targets=[target],
        query_vector=(1.0, 0.0),
        limit=1,
        repository=InMemoryVectorIndexRepository(),
        vector_store=_Store({}),
    )

    assert result["exclusion_counts"] == {"INDEX_NOT_READY": 1}
