from __future__ import annotations

from copy import deepcopy
import math
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError

from nex_cx.access_context import CxAccessContext
from nex_cx.private_content import sha256_private_vector
from nex_cx.summary_similarity import (
    PostgresSummarySimilarityStore,
    SummarySimilarityError,
    _search_sql,
    build_summary_similarity_store,
)
import nex_cx.summary_similarity as summary_similarity


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows


class _Session:
    def __init__(self, rows, capture):
        self.rows = rows
        self.capture = capture

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, statement, parameters):
        self.capture.update(sql=" ".join(str(statement).split()), parameters=parameters)
        return _Result(self.rows)


class _SessionFactory:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.capture = {}

    def __call__(self):
        return _Session(self.rows, self.capture)


def _context(*, owner="owner-0956"):
    return CxAccessContext(
        caller_service_id="nex-cx",
        tenant_id="tenant-0956",
        subject_id=owner,
        request_id="request-0956",
        trace_id="09560000000000000000000000000001",
        scopes=("service:call",),
    )


def _row(*, score=0.875, distance=0.125, dimension=3):
    return {
        "summary_vector_id": str(uuid4()),
        "summary_embedding_id": str(uuid4()),
        "document_summary_id": str(uuid4()),
        "content_object_id": str(uuid4()),
        "summary_text_sha256": "a" * 64,
        "embedding_sha256": "b" * 64,
        "vector_dimension": dimension,
        "original_filename": "quarterly-report.pdf",
        "content_type": "application/pdf",
        "summary_char_count": 640,
        "distance": distance,
        "similarity_score": score,
    }


def test_owner_scoped_summary_similarity_returns_safe_ranked_candidates():
    rows = [_row(score=0.9, distance=0.1), _row(score=0.75, distance=0.25)]
    factory = _SessionFactory(rows)
    store = PostgresSummarySimilarityStore(factory)  # type: ignore[arg-type]
    query = (1.0, 0.0, 0.0)
    profile = "c" * 64
    excluded = str(uuid4())

    result = store.search(
        access_context=_context(),
        query_vector=query,
        profile_fingerprint=profile,
        limit=5,
        minimum_score=0.5,
        exclude_content_object_id=excluded,
    )

    assert result["summary_similarity_result_schema_version"] == (
        "cx_summary_similarity_result.v1"
    )
    assert result["query_embedding_sha256"] == sha256_private_vector(query)
    assert result["query_dimension"] == 3
    assert result["candidate_count"] == 2
    assert [item["candidate_rank"] for item in result["candidates"]] == [1, 2]
    assert result["candidates"][0]["similarity_score"] == 0.9
    assert all("embedding" not in item for item in result["candidates"])
    assert factory.capture["parameters"] == {
        "tenant_id": "tenant-0956",
        "owner_subject_id": "owner-0956",
        "profile_fingerprint": profile,
        "vector_dimension": 3,
        "query_embedding": "[1.0,0.0,0.0]",
        "minimum_score": 0.5,
        "exclude_content_object_id": excluded,
        "limit": 5,
    }
    sql = factory.capture["sql"]
    for token in (
        "content.lifecycle_status = 'ACTIVE'",
        "content.tenant_ref_id = :tenant_id",
        "content.owner_subject_ref_id = :owner_subject_id",
        "summary.status = 'READY'",
        "summary_embedding.status = 'READY'",
        "summary.summary_text_sha256 = summary_vector.summary_text_sha256",
        "summary.document_summary_id = ( SELECT latest.document_summary_id",
        "summary_vector.profile_fingerprint = :profile_fingerprint",
    ):
        assert token in sql


def test_summary_similarity_empty_result_and_2560_hnsw_shape():
    factory = _SessionFactory()
    result = PostgresSummarySimilarityStore(factory).search(  # type: ignore[arg-type]
        access_context=_context(),
        query_vector=[0.0] * 2560,
        profile_fingerprint="d" * 64,
        limit=1,
    )
    assert result["candidate_count"] == 0
    assert result["candidates"] == []
    assert result["excluded_content_object_id"] is None
    assert "embedding::halfvec(2560)" in factory.capture["sql"]
    assert "halfvec(2560)" in _search_sql(2560)
    assert "CAST(:query_embedding AS vector)" in _search_sql(3)


@pytest.mark.parametrize(
    "query",
    [None, "vector", b"vector", bytearray(b"x"), [], [0.0] * 8193, [True], ["1"], [math.inf]],
)
def test_summary_similarity_rejects_invalid_query(query):
    store = PostgresSummarySimilarityStore(_SessionFactory())  # type: ignore[arg-type]
    with pytest.raises(SummarySimilarityError) as caught:
        store.search(
            access_context=_context(),
            query_vector=query,  # type: ignore[arg-type]
            profile_fingerprint="a" * 64,
            limit=1,
        )
    assert caught.value.status_code == 422
    assert caught.value.error_code == "CX_SUMMARY_SIMILARITY_QUERY_INVALID"


@pytest.mark.parametrize("limit", [True, 0, 101, "1"])
def test_summary_similarity_rejects_invalid_limit(limit):
    with pytest.raises(SummarySimilarityError) as caught:
        PostgresSummarySimilarityStore(_SessionFactory()).search(  # type: ignore[arg-type]
            access_context=_context(),
            query_vector=(1.0,),
            profile_fingerprint="a" * 64,
            limit=limit,
        )
    assert caught.value.error_code == "CX_SUMMARY_SIMILARITY_LIMIT_INVALID"


@pytest.mark.parametrize("score", [True, -1.1, 1.1, math.nan, "0.5"])
def test_summary_similarity_rejects_invalid_minimum_score(score):
    with pytest.raises(SummarySimilarityError) as caught:
        PostgresSummarySimilarityStore(_SessionFactory()).search(  # type: ignore[arg-type]
            access_context=_context(),
            query_vector=(1.0,),
            profile_fingerprint="a" * 64,
            limit=1,
            minimum_score=score,
        )
    assert caught.value.error_code == "CX_SUMMARY_SIMILARITY_SCORE_INVALID"


def test_summary_similarity_rejects_invalid_profile_and_exclusion():
    store = PostgresSummarySimilarityStore(_SessionFactory())  # type: ignore[arg-type]
    with pytest.raises(SummarySimilarityError) as profile:
        store.search(
            access_context=_context(),
            query_vector=(1.0,),
            profile_fingerprint="bad",
            limit=1,
        )
    with pytest.raises(SummarySimilarityError) as scope:
        store.search(
            access_context=_context(),
            query_vector=(1.0,),
            profile_fingerprint="a" * 64,
            limit=1,
            exclude_content_object_id="bad",
        )
    assert profile.value.error_code == "CX_SUMMARY_SIMILARITY_PROFILE_INVALID"
    assert scope.value.error_code == "CX_SUMMARY_SIMILARITY_SCOPE_INVALID"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("content_object_id", "bad"),
        ("document_summary_id", None),
        ("summary_embedding_id", "bad"),
        ("summary_text_sha256", "bad"),
        ("embedding_sha256", "bad"),
        ("vector_dimension", True),
        ("summary_char_count", -1),
        ("similarity_score", 2.0),
        ("similarity_score", True),
        ("distance", -0.1),
        ("distance", "0.1"),
        ("original_filename", ""),
        ("content_type", "x" * 161),
    ],
)
def test_summary_similarity_fails_closed_for_malformed_rows(field, value):
    row = _row()
    row[field] = value
    store = PostgresSummarySimilarityStore(_SessionFactory([row]))  # type: ignore[arg-type]
    with pytest.raises(SummarySimilarityError) as caught:
        store.search(
            access_context=_context(),
            query_vector=(1.0, 0.0, 0.0),
            profile_fingerprint="a" * 64,
            limit=1,
        )
    assert caught.value.status_code == 502
    assert caught.value.error_code == "CX_SUMMARY_SIMILARITY_RESULT_INVALID"
    assert caught.value.retryable is True


def test_summary_similarity_maps_database_errors_without_secret_detail():
    class FailingFactory:
        def __call__(self):
            raise OperationalError("SELECT private", {}, RuntimeError("password"))

    with pytest.raises(SummarySimilarityError) as caught:
        PostgresSummarySimilarityStore(FailingFactory()).search(  # type: ignore[arg-type]
            access_context=_context(),
            query_vector=(1.0,),
            profile_fingerprint="a" * 64,
            limit=1,
        )
    assert caught.value.status_code == 503
    assert caught.value.retryable is True
    assert "password" not in caught.value.detail


def test_summary_similarity_builder_uses_vector_route_and_api_pool(monkeypatch):
    captured = {}
    settings = SimpleNamespace(vector_database_url="postgresql://vector/db")
    monkeypatch.setattr(
        summary_similarity,
        "service_database_settings",
        lambda **kwargs: settings,
    )
    monkeypatch.setattr(
        summary_similarity,
        "database_pool_settings",
        lambda *args, **kwargs: captured.setdefault("pool", object()),
    )
    monkeypatch.setattr(
        summary_similarity,
        "build_engine",
        lambda url, **kwargs: captured.update(url=url, **kwargs) or object(),
    )
    monkeypatch.setattr(
        summary_similarity,
        "build_session_factory",
        lambda _engine: _SessionFactory(),
    )

    store = build_summary_similarity_store(environ={"X": "1"})

    assert isinstance(store, PostgresSummarySimilarityStore)
    assert captured["url"] == settings.vector_database_url
    assert captured["pool_settings"] is captured["pool"]


def test_summary_similarity_builder_rejects_missing_vector_route(monkeypatch):
    monkeypatch.setattr(
        summary_similarity,
        "service_database_settings",
        lambda **_kwargs: SimpleNamespace(vector_database_url=None),
    )
    with pytest.raises(SummarySimilarityError) as caught:
        build_summary_similarity_store(environ={})
    assert caught.value.error_code == "CX_VECTOR_DATABASE_CONFIG_INVALID"
