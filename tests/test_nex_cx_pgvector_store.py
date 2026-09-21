from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError

from nex_cx.access_context import CxAccessContext
from nex_cx.pgvector_store import (
    PGVECTOR_STORAGE_BACKEND,
    BoundPgVectorCxVectorStore,
    PgVectorCxVectorStore,
    _parse_pgvector,
    build_pgvector_cx_vector_store,
    build_pgvector_index_binding,
)
from nex_cx.private_content import (
    CxPrivateContentError,
    CxVectorStore,
    build_private_payload_key,
    sha256_private_vector,
)
from nex_cx.vector_index_freshness import (
    build_embedding_profile,
    build_source_snapshot,
    build_vector_index_manifest,
    mark_vector_index_ready,
)
import nex_cx.pgvector_store as pgvector_store


class _Result:
    def __init__(self, *, one=None, rows=(), rowcount=-1):
        self._one = one
        self._rows = list(rows)
        self.rowcount = rowcount

    def mappings(self):
        return self

    def one_or_none(self):
        return self._one

    def all(self):
        return self._rows


class _Session:
    def __init__(self, rows: dict[tuple[str, str], dict[str, object]]):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, statement, parameters):
        sql = " ".join(str(statement).split())
        identity = (parameters["vector_index_id"], parameters.get("chunk_id", ""))
        if sql.startswith("SELECT embedding_sha256"):
            return _Result(one=self.rows.get(identity))
        if sql.startswith("INSERT INTO cx_vectors"):
            self.rows[identity] = {
                "embedding": parameters["embedding"],
                "embedding_sha256": parameters["embedding_sha256"],
                "vector_dimension": parameters["vector_dimension"],
                "chunk_id": parameters["chunk_id"],
            }
            return _Result(rowcount=1)
        if sql.startswith("SELECT embedding::text"):
            return _Result(one=self.rows.get(identity))
        if sql.startswith("DELETE FROM cx_vectors"):
            removed = self.rows.pop(identity, None)
            return _Result(rowcount=1 if removed is not None else 0)
        if sql.startswith("SELECT chunk_id"):
            rows = [
                {
                    "chunk_id": row["chunk_id"],
                    "embedding_sha256": row["embedding_sha256"],
                    "distance": 0.125,
                }
                for row in self.rows.values()
            ]
            return _Result(rows=rows[: parameters["limit"]])
        raise AssertionError(sql)


class _SessionFactory:
    def __init__(self):
        self.rows: dict[tuple[str, str], dict[str, object]] = {}

    def __call__(self):
        return _Session(self.rows)

    def begin(self):
        return _Session(self.rows)


def _manifest(*, dimension: int = 3):
    chunk_ids = [str(uuid4()), str(uuid4())]
    source = build_source_snapshot(
        chunk_set_id=str(uuid4()),
        chunk_policy_id="1000_100",
        source_markdown_sha256="1" * 64,
        chunks=[
            {"chunk_id": chunk_id, "ordinal": ordinal, "text_sha256": str(ordinal + 2) * 64}
            for ordinal, chunk_id in enumerate(chunk_ids)
        ],
    )
    profile = build_embedding_profile(
        provider_alias="mock-embedding",
        model_profile_id="qwen-test",
        model_revision="test",
        deployment_id="local",
        vector_dimension=dimension,
    )
    return build_vector_index_manifest(
        content_object_id=str(uuid4()),
        tenant_ref={"type": "oa.tenant", "id": "tenant-a"},
        owner_subject_ref={"type": "oa.user", "id": "owner-a"},
        source_snapshot=source,
        embedding_profile=profile,
        trace_id="trace-0934",
        request_id="request-0934",
        observed_at="2026-09-21T12:00:00Z",
    )


def _context(*, owner: str = "owner-a"):
    return CxAccessContext(
        caller_service_id="nex-cx",
        tenant_id="tenant-a",
        subject_id=owner,
        request_id="request-0934",
        trace_id="93400000000000000000000000000001",
        scopes=("service:call",),
    )


def _store(manifest=None):
    factory = _SessionFactory()
    adapter = PgVectorCxVectorStore(
        factory,  # type: ignore[arg-type]
        redacted_database_url="postgresql://user:***@localhost/db",
        uses_primary_database=True,
    )
    return adapter.bind_index(manifest or _manifest()), factory


def _key(manifest, *, content_id=None, kind="chunk_embedding"):
    return build_private_payload_key(
        _context(),
        payload_kind=kind,
        content_id=content_id or manifest["source_snapshot"]["chunk_refs"][0]["chunk_id"],
    )


def test_bound_pgvector_store_round_trip_idempotency_search_and_delete():
    manifest = _manifest()
    store, _factory = _store(manifest)
    key = _key(manifest)
    vector = (1.0, 0.0, 0.0)
    checksum = sha256_private_vector(vector)

    first = store.put_vector(
        access_context=_context(), key=key, vector=vector, expected_sha256=checksum
    )
    second = store.put_vector(
        access_context=_context(), key=key, vector=vector, expected_sha256=checksum
    )

    assert isinstance(store, CxVectorStore)
    assert first == second
    assert first.storage_backend == PGVECTOR_STORAGE_BACKEND
    assert first.vector_dimension == 3
    assert store.get_vector(
        access_context=_context(),
        key=key,
        expected_sha256=checksum,
        expected_dimension=3,
    ) == vector
    assert store.search(access_context=_context(), query_vector=vector, limit=1) == [
        {
            "chunk_id": key.content_id,
            "embedding_sha256": checksum,
            "distance": 0.125,
            "score": 0.875,
        }
    ]
    assert store.delete_vector(access_context=_context(), key=key) is True
    assert store.delete_vector(access_context=_context(), key=key) is False
    assert store.get_vector(
        access_context=_context(), key=key, expected_sha256=checksum, expected_dimension=3
    ) is None


def test_pgvector_store_rejects_immutable_conflict_and_dimension_mismatch():
    manifest = _manifest()
    store, _factory = _store(manifest)
    key = _key(manifest)
    vector = (1.0, 0.0, 0.0)
    store.put_vector(
        access_context=_context(),
        key=key,
        vector=vector,
        expected_sha256=sha256_private_vector(vector),
    )

    with pytest.raises(CxPrivateContentError) as conflict:
        store.put_vector(
            access_context=_context(),
            key=key,
            vector=(0.0, 1.0, 0.0),
            expected_sha256=sha256_private_vector((0.0, 1.0, 0.0)),
        )
    with pytest.raises(CxPrivateContentError) as put_dimension:
        store.put_vector(
            access_context=_context(),
            key=_key(manifest, content_id=manifest["source_snapshot"]["chunk_refs"][1]["chunk_id"]),
            vector=(1.0, 0.0),
            expected_sha256=sha256_private_vector((1.0, 0.0)),
        )
    with pytest.raises(CxPrivateContentError) as get_dimension:
        store.get_vector(
            access_context=_context(),
            key=key,
            expected_sha256=sha256_private_vector(vector),
            expected_dimension=2,
        )

    assert conflict.value.error_code == "CX_PRIVATE_VECTOR_IMMUTABLE_CONFLICT"
    assert put_dimension.value.error_code == "CX_PRIVATE_VECTOR_DIMENSION_MISMATCH"
    assert get_dimension.value.error_code == "CX_PRIVATE_VECTOR_DIMENSION_MISMATCH"


@pytest.mark.parametrize("limit", [True, 0, 101, "1"])
def test_pgvector_search_rejects_invalid_limit(limit):
    store, _factory = _store()
    with pytest.raises(CxPrivateContentError) as caught:
        store.search(access_context=_context(), query_vector=(1.0, 0.0, 0.0), limit=limit)
    assert caught.value.error_code == "CX_VECTOR_SEARCH_LIMIT_INVALID"


def test_pgvector_store_enforces_owner_kind_chunk_status_and_query_dimension():
    manifest = _manifest()
    store, _factory = _store(manifest)
    valid_key = _key(manifest)
    cases = []
    with pytest.raises(CxPrivateContentError) as owner:
        store.get_vector(
            access_context=_context(owner="other"),
            key=valid_key,
            expected_sha256="0" * 64,
            expected_dimension=3,
        )
    cases.append(owner.value.error_code)
    with pytest.raises(CxPrivateContentError) as kind:
        store.storage_uri(_key(manifest, kind="summary_embedding"))
    cases.append(kind.value.error_code)
    with pytest.raises(CxPrivateContentError) as chunk:
        store.storage_uri(_key(manifest, content_id=str(uuid4())))
    cases.append(chunk.value.error_code)
    with pytest.raises(CxPrivateContentError) as query_dimension:
        store.search(access_context=_context(), query_vector=(1.0,), limit=1)
    cases.append(query_dimension.value.error_code)

    ready = mark_vector_index_ready(
        manifest,
        payload_receipts=[
            {
                "chunk_id": item["chunk_id"],
                "embedding_sha256": "9" * 64,
                "vector_dimension": 3,
                "storage_uri": f"cx-private://pgvector/{uuid4()}",
            }
            for item in manifest["source_snapshot"]["chunk_refs"]
        ],
        observed_at="2026-09-21T12:01:00Z",
    )
    ready_store, _factory = _store(ready)
    with pytest.raises(CxPrivateContentError) as status:
        ready_store.put_vector(
            access_context=_context(),
            key=_key(ready),
            vector=(1.0, 0.0, 0.0),
            expected_sha256=sha256_private_vector((1.0, 0.0, 0.0)),
        )
    cases.append(status.value.error_code)

    assert cases == [
        "CX_PRIVATE_PAYLOAD_NOT_FOUND",
        "CX_PGVECTOR_KIND_INVALID",
        "CX_PRIVATE_PAYLOAD_NOT_FOUND",
        "CX_PRIVATE_VECTOR_DIMENSION_MISMATCH",
        "CX_VECTOR_INDEX_NOT_BUILDING",
    ]


@pytest.mark.parametrize("value", [None, True, 0, -1, "3"])
def test_pgvector_get_rejects_invalid_expected_dimension(value):
    manifest = _manifest()
    store, _factory = _store(manifest)
    with pytest.raises(CxPrivateContentError) as caught:
        store.get_vector(
            access_context=_context(),
            key=_key(manifest),
            expected_sha256="0" * 64,
            expected_dimension=value,  # type: ignore[arg-type]
        )
    assert caught.value.error_code == "CX_PRIVATE_VECTOR_DIMENSION_INVALID"


def test_pgvector_binding_rejects_non_uuid_manifest_identifiers():
    manifest = _manifest()
    manifest["content_object_id"] = "not-a-uuid"
    with pytest.raises(CxPrivateContentError) as caught:
        build_pgvector_index_binding(manifest)
    assert caught.value.error_code == "CX_VECTOR_IDENTIFIER_INVALID"


@pytest.mark.parametrize("value", [None, "not-vector", "[bad]"])
def test_pgvector_parser_fails_closed(value):
    with pytest.raises(CxPrivateContentError) as caught:
        _parse_pgvector(value)
    assert caught.value.error_code == "CX_PRIVATE_VECTOR_ENCODING_INVALID"


def test_pgvector_store_maps_sqlalchemy_failures_without_leaking_details():
    class FailingFactory:
        def __call__(self):
            raise OperationalError("SELECT secret", {}, RuntimeError("password"))

        def begin(self):
            return self()

    manifest = _manifest()
    binding = build_pgvector_index_binding(manifest)
    store = BoundPgVectorCxVectorStore(FailingFactory(), binding=binding)  # type: ignore[arg-type]
    with pytest.raises(CxPrivateContentError) as caught:
        store.get_vector(
            access_context=_context(),
            key=_key(manifest),
            expected_sha256="0" * 64,
            expected_dimension=3,
        )
    assert caught.value.status_code == 503
    assert caught.value.retryable is True
    assert "password" not in caught.value.detail


@pytest.mark.parametrize("operation", ["put", "delete", "search"])
def test_pgvector_store_maps_each_sqlalchemy_failure(operation):
    class FailingFactory:
        def __call__(self):
            raise OperationalError("SQL", {}, RuntimeError("private"))

        def begin(self):
            return self()

    manifest = _manifest()
    store = BoundPgVectorCxVectorStore(  # type: ignore[arg-type]
        FailingFactory(), binding=build_pgvector_index_binding(manifest)
    )
    key = _key(manifest)
    vector = (1.0, 0.0, 0.0)
    with pytest.raises(CxPrivateContentError) as caught:
        if operation == "put":
            store.put_vector(
                access_context=_context(),
                key=key,
                vector=vector,
                expected_sha256=sha256_private_vector(vector),
            )
        elif operation == "delete":
            store.delete_vector(access_context=_context(), key=key)
        else:
            store.search(access_context=_context(), query_vector=vector, limit=1)
    assert caught.value.error_code == "CX_PGVECTOR_STORAGE_UNAVAILABLE"


def test_pgvector_search_enforces_bound_owner_and_uses_2560_index_branch():
    manifest = _manifest(dimension=2560)
    store, _factory = _store(manifest)
    with pytest.raises(CxPrivateContentError) as caught:
        store.search(
            access_context=_context(owner="other"),
            query_vector=[0.0] * 2560,
            limit=1,
        )
    assert caught.value.error_code == "CX_PRIVATE_PAYLOAD_NOT_FOUND"

    assert store.search(
        access_context=_context(), query_vector=[0.0] * 2560, limit=1
    ) == []


def test_pgvector_store_builder_uses_vector_route_and_worker_pool(monkeypatch):
    captured = {}
    settings = SimpleNamespace(
        vector_database_url="postgresql://vector:secret@localhost/vector",
        redacted_vector_database_url="postgresql://vector:***@localhost/vector",
        vector_uses_primary=False,
    )
    monkeypatch.setattr(pgvector_store, "service_database_settings", lambda **kwargs: settings)
    monkeypatch.setattr(
        pgvector_store,
        "database_pool_settings",
        lambda *args, **kwargs: captured.setdefault("pool", object()),
    )
    monkeypatch.setattr(
        pgvector_store,
        "build_engine",
        lambda url, **kwargs: captured.update(url=url, **kwargs) or object(),
    )
    monkeypatch.setattr(pgvector_store, "build_session_factory", lambda _engine: _SessionFactory())

    store = build_pgvector_cx_vector_store(
        database_env="NEX_CX_TEST_DATABASE_URL", environ={"X": "1"}
    )

    assert store.redacted_database_url.endswith("@localhost/vector")
    assert store.uses_primary_database is False
    assert captured["url"] == settings.vector_database_url
    assert captured["pool_settings"] is captured["pool"]


def test_pgvector_store_builder_rejects_missing_vector_route(monkeypatch):
    monkeypatch.setattr(
        pgvector_store,
        "service_database_settings",
        lambda **_kwargs: SimpleNamespace(
            vector_database_url=None,
            redacted_vector_database_url=None,
        ),
    )
    with pytest.raises(CxPrivateContentError) as caught:
        build_pgvector_cx_vector_store(environ={})
    assert caught.value.error_code == "CX_VECTOR_DATABASE_CONFIG_INVALID"
