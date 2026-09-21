from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any

import pytest
from sqlalchemy.exc import SQLAlchemyError

from nex_cx.access_context import CxAccessContext
from nex_cx.lexical_candidates import (
    LexicalCandidateStoreError,
    PostgresLexicalCandidateStore,
)


class FakeMappings:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def all(self) -> list[dict[str, Any]]:
        return self._rows


class FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> FakeMappings:
        return FakeMappings(self._rows)


class FakeSession(AbstractContextManager["FakeSession"]):
    def __init__(
        self,
        rows: list[dict[str, Any]],
        error: Exception | None = None,
    ) -> None:
        self.rows = rows
        self.error = error
        self.statement = ""
        self.parameters: dict[str, Any] = {}

    def __enter__(self) -> "FakeSession":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, statement: object, parameters: dict[str, Any]) -> FakeResult:
        if self.error is not None:
            raise self.error
        self.statement = str(statement)
        self.parameters = parameters
        return FakeResult(self.rows)


def access_context() -> CxAccessContext:
    return CxAccessContext(
        caller_service_id="nex-cx",
        tenant_id="tenant-a",
        subject_id="owner-a",
        request_id="request-a",
        trace_id="a" * 32,
        scopes=("service:call",),
    )


def candidate_row() -> dict[str, Any]:
    return {
        "content_object_id": "11111111-1111-1111-1111-111111111111",
        "chunk_set_id": "22222222-2222-2222-2222-222222222222",
        "chunk_id": "33333333-3333-3333-3333-333333333333",
        "ordinal": 1,
        "start_offset": 10,
        "end_offset": 20,
        "text_sha256": "f" * 64,
        "text_preview": "authorized preview",
        "matched_terms": ["alpha", "beta"],
        "bm25_score": 1.234567891,
    }


def test_search_binds_owner_scope_and_maps_bm25_candidate() -> None:
    session = FakeSession([candidate_row()])
    store = PostgresLexicalCandidateStore(lambda: session)  # type: ignore[arg-type]

    result = store.search(
        access_context=access_context(),
        query_terms=["Alpha", "alpha", " beta "],
        content_object_ids=[
            candidate_row()["content_object_id"],
            candidate_row()["content_object_id"],
        ],
        limit=10,
    )

    assert result == [
        {
            "lexical_candidate_schema_version": "cx_lexical_candidate.v1",
            "candidate_source": "postgresql_bm25",
            "content_object_id": candidate_row()["content_object_id"],
            "chunk_set_id": candidate_row()["chunk_set_id"],
            "chunk_id": candidate_row()["chunk_id"],
            "ordinal": 1,
            "start_offset": 10,
            "end_offset": 20,
            "text_sha256": "f" * 64,
            "text_preview": "authorized preview",
            "matched_terms": ["alpha", "beta"],
            "bm25_score": 1.23456789,
        }
    ]
    assert "content.lifecycle_status = 'ACTIVE'" in session.statement
    assert "content.tenant_ref_id = :tenant_id" in session.statement
    assert "content.owner_subject_ref_id = :owner_subject_id" in session.statement
    assert session.parameters["tenant_id"] == "tenant-a"
    assert session.parameters["owner_subject_id"] == "owner-a"
    assert session.parameters["query_terms"] == ["alpha", "beta"]
    assert session.parameters["scope_all"] is False
    assert session.parameters["content_object_ids"] == [
        candidate_row()["content_object_id"]
    ]


def test_search_supports_all_owner_scope_and_empty_query() -> None:
    session = FakeSession([])
    store = PostgresLexicalCandidateStore(lambda: session)  # type: ignore[arg-type]

    assert store.search(
        access_context=access_context(),
        query_terms=[],
        limit=5,
    ) == []
    assert session.statement == ""

    store.search(
        access_context=access_context(),
        query_terms=["alpha"],
        content_object_ids=None,
        limit=5,
    )
    assert session.parameters["scope_all"] is True
    assert session.parameters["content_object_ids"] == []


@pytest.mark.parametrize("terms", ["alpha", [""], [None], [str(i) for i in range(65)]])
def test_search_rejects_invalid_query_terms(terms: object) -> None:
    store = PostgresLexicalCandidateStore(lambda: FakeSession([]))  # type: ignore[arg-type]

    with pytest.raises(LexicalCandidateStoreError) as captured:
        store.search(
            access_context=access_context(),
            query_terms=terms,  # type: ignore[arg-type]
            limit=5,
        )

    assert captured.value.error_code == "CX_LEXICAL_QUERY_INVALID"


@pytest.mark.parametrize("scope", ["id", [""], [None]])
def test_search_rejects_invalid_content_scope(scope: object) -> None:
    store = PostgresLexicalCandidateStore(lambda: FakeSession([]))  # type: ignore[arg-type]

    with pytest.raises(LexicalCandidateStoreError) as captured:
        store.search(
            access_context=access_context(),
            query_terms=["alpha"],
            content_object_ids=scope,  # type: ignore[arg-type]
            limit=5,
        )

    assert captured.value.error_code == "CX_LEXICAL_SCOPE_INVALID"


@pytest.mark.parametrize(
    ("parameters", "error_code"),
    [
        ({"limit": 0}, "CX_LEXICAL_LIMIT_INVALID"),
        ({"limit": True}, "CX_LEXICAL_LIMIT_INVALID"),
        ({"limit": 501}, "CX_LEXICAL_LIMIT_INVALID"),
        ({"limit": 5, "k1": 0}, "CX_BM25_POLICY_INVALID"),
        ({"limit": 5, "k1": True}, "CX_BM25_POLICY_INVALID"),
        ({"limit": 5, "b": -0.1}, "CX_BM25_POLICY_INVALID"),
        ({"limit": 5, "b": True}, "CX_BM25_POLICY_INVALID"),
        ({"limit": 5, "b": 1.1}, "CX_BM25_POLICY_INVALID"),
    ],
)
def test_search_rejects_invalid_policy_parameters(
    parameters: dict[str, object],
    error_code: str,
) -> None:
    store = PostgresLexicalCandidateStore(lambda: FakeSession([]))  # type: ignore[arg-type]

    with pytest.raises(LexicalCandidateStoreError) as captured:
        store.search(
            access_context=access_context(),
            query_terms=["alpha"],
            **parameters,  # type: ignore[arg-type]
        )

    assert captured.value.error_code == error_code


def test_search_redacts_database_failure() -> None:
    session = FakeSession([], SQLAlchemyError("secret database detail"))
    store = PostgresLexicalCandidateStore(lambda: session)  # type: ignore[arg-type]

    with pytest.raises(LexicalCandidateStoreError) as captured:
        store.search(
            access_context=access_context(),
            query_terms=["alpha"],
            limit=5,
        )

    assert captured.value.error_code == "CX_LEXICAL_SEARCH_UNAVAILABLE"
    assert "secret" not in captured.value.detail
