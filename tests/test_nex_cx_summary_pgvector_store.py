from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import OperationalError

from nex_cx.access_context import CxAccessContext
from nex_cx.private_content import (
    CxPrivateContentError,
    CxVectorStore,
    build_private_payload_key,
    sha256_private_vector,
)
from nex_cx.summary_pgvector_store import (
    SUMMARY_PGVECTOR_STORAGE_BACKEND,
    BoundSummaryPgVectorStore,
    SummaryPgVectorStore,
    _parse_pgvector,
    assess_summary_vector_freshness,
    build_summary_pgvector_store,
    build_summary_vector_binding,
)
import nex_cx.summary_pgvector_store as summary_pgvector_store


class _Result:
    def __init__(self, *, one=None, rowcount=-1):
        self._one = one
        self.rowcount = rowcount

    def mappings(self):
        return self

    def one_or_none(self):
        return self._one


class _Session:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, statement, parameters):
        sql = " ".join(str(statement).split())
        identity = parameters["summary_embedding_id"]
        if sql.startswith("SELECT summary_vector_id"):
            return _Result(one=self.rows.get(identity))
        if sql.startswith("INSERT INTO cx_summary_vectors"):
            self.rows[identity] = {
                **parameters,
                "embedding": parameters["embedding"],
                "tenant_ref_id": parameters["tenant_id"],
                "owner_subject_ref_id": parameters["owner_subject_id"],
            }
            return _Result(rowcount=1)
        if sql.startswith("DELETE FROM cx_summary_vectors"):
            removed = self.rows.pop(identity, None)
            return _Result(rowcount=1 if removed is not None else 0)
        raise AssertionError(sql)


class _SessionFactory:
    def __init__(self):
        self.rows = {}

    def __call__(self):
        return _Session(self.rows)

    def begin(self):
        return _Session(self.rows)


def _context(*, owner="owner-0955"):
    return CxAccessContext(
        caller_service_id="nex-cx",
        tenant_id="tenant-0955",
        subject_id=owner,
        request_id="request-0955",
        trace_id="09550000000000000000000000000001",
        scopes=("service:call",),
    )


def _records(*, dimension=3):
    content_id = str(uuid4())
    summary_id = str(uuid4())
    embedding_id = str(uuid4())
    vector = tuple(float(index == 0) for index in range(dimension))
    content = {
        "content_object_id": content_id,
        "lifecycle_status": "ACTIVE",
        "ownership_ref": {
            "tenant_ref": {"type": "oa.tenant", "id": "tenant-0955"},
            "owner_subject_ref": {"type": "oa.user", "id": "owner-0955"},
        },
    }
    summary = {
        "document_summary_id": summary_id,
        "content_object_id": content_id,
        "summary_text_sha256": "a" * 64,
        "status": "READY",
    }
    embedding = {
        "summary_embedding_id": embedding_id,
        "document_summary_id": summary_id,
        "provider_alias": "qwen-embedding-default",
        "model_profile_id": "Qwen3-Embedding-4B",
        "model_revision": "bf16",
        "deployment_id": "mock-0955",
        "vector_dimension": dimension,
        "embedding_sha256": sha256_private_vector(vector),
        "status": "READY",
        "created_at": "2026-09-22T12:00:00Z",
    }
    return content, summary, embedding, vector


def _binding(*, dimension=3):
    content, summary, embedding, vector = _records(dimension=dimension)
    return (
        build_summary_vector_binding(
            access_context=_context(),
            content_object=content,
            summary=summary,
            embedding=embedding,
        ),
        vector,
    )


def _store(binding=None):
    binding = binding or _binding()[0]
    factory = _SessionFactory()
    root = SummaryPgVectorStore(
        factory,  # type: ignore[arg-type]
        redacted_database_url="postgresql://user:***@localhost/test",
        uses_primary_database=True,
    )
    return root.bind_summary(binding), factory


def _key(binding, *, kind="summary_embedding", content_id=None, owner="owner-0955"):
    return build_private_payload_key(
        _context(owner=owner),
        payload_kind=kind,
        content_id=content_id or str(binding.document_summary_id),
    )


def test_summary_pgvector_round_trip_idempotency_freshness_and_delete():
    binding, vector = _binding()
    store, _factory = _store(binding)
    key = _key(binding)

    first = store.put_vector(
        access_context=_context(),
        key=key,
        vector=vector,
        expected_sha256=binding.embedding_sha256,
    )
    second = store.put_vector(
        access_context=_context(),
        key=key,
        vector=vector,
        expected_sha256=binding.embedding_sha256,
    )

    assert isinstance(store, CxVectorStore)
    assert first == second
    assert first.storage_backend == SUMMARY_PGVECTOR_STORAGE_BACKEND
    assert first.storage_uri.endswith(str(binding.summary_vector_id))
    assert store.get_vector(
        access_context=_context(),
        key=key,
        expected_sha256=binding.embedding_sha256,
        expected_dimension=3,
    ) == vector
    assert store.freshness(access_context=_context()) == {
        "freshness_schema_version": "cx_summary_vector_freshness.v1",
        "state": "READY",
        "usable": True,
        "reasons": [],
        "document_summary_id": str(binding.document_summary_id),
        "summary_embedding_id": str(binding.summary_embedding_id),
        "profile_fingerprint": binding.profile_fingerprint,
    }
    assert store.delete_vector(access_context=_context(), key=key) is True
    assert store.delete_vector(access_context=_context(), key=key) is False
    assert store.get_vector(
        access_context=_context(),
        key=key,
        expected_sha256=binding.embedding_sha256,
        expected_dimension=3,
    ) is None


def test_summary_binding_is_deterministic_and_owner_scoped():
    content, summary, embedding, _vector = _records()
    first = build_summary_vector_binding(
        access_context=_context(),
        content_object=content,
        summary=summary,
        embedding=embedding,
    )
    second = build_summary_vector_binding(
        access_context=_context(),
        content_object=content,
        summary=summary,
        embedding=embedding,
    )
    assert first == second
    assert isinstance(first.summary_vector_id, UUID)
    assert len(first.profile_fingerprint) == 64

    with pytest.raises(CxPrivateContentError) as caught:
        build_summary_vector_binding(
            access_context=_context(owner="other-owner"),
            content_object=content,
            summary=summary,
            embedding=embedding,
        )
    assert caught.value.error_code == "CX_PRIVATE_PAYLOAD_NOT_FOUND"


@pytest.mark.parametrize(
    ("mutation", "detail"),
    [
        (lambda c, _s, _e: c.pop("ownership_ref"), "ownership_ref"),
        (lambda c, _s, _e: c["ownership_ref"].update(tenant_ref={"type": "bad", "id": "tenant-0955"}), "types"),
        (lambda c, s, _e: s.update(content_object_id=str(uuid4())), "content lineage"),
        (lambda _c, _s, e: e.update(document_summary_id=str(uuid4())), "embedding lineage"),
        (lambda _c, _s, e: e.update(vector_dimension=True), "dimension"),
        (lambda _c, s, _e: s.update(summary_text_sha256="bad"), "SHA-256"),
        (lambda _c, _s, e: e.update(summary_embedding_id="bad"), "UUID"),
        (lambda _c, _s, e: e.update(provider_alias=""), "non-empty"),
    ],
)
def test_summary_binding_rejects_invalid_lineage(mutation, detail):
    content, summary, embedding, _vector = _records()
    mutation(content, summary, embedding)
    with pytest.raises(CxPrivateContentError) as caught:
        build_summary_vector_binding(
            access_context=_context(),
            content_object=content,
            summary=summary,
            embedding=embedding,
        )
    assert caught.value.status_code == 422
    assert detail.lower() in caught.value.detail.lower()


@pytest.mark.parametrize("field", ["content_status", "summary_status", "embedding_status"])
def test_summary_pgvector_rejects_non_ready_lineage(field):
    binding, vector = _binding()
    binding = replace(binding, **{field: "STALE"})
    store, _factory = _store(binding)
    with pytest.raises(CxPrivateContentError) as caught:
        store.put_vector(
            access_context=_context(),
            key=_key(binding),
            vector=vector,
            expected_sha256=binding.embedding_sha256,
        )
    assert caught.value.error_code == "CX_SUMMARY_VECTOR_NOT_BUILDABLE"


def test_summary_pgvector_rejects_hash_dimension_and_immutable_conflicts():
    binding, vector = _binding()
    store, factory = _store(binding)
    key = _key(binding)

    with pytest.raises(CxPrivateContentError) as digest:
        store.put_vector(
            access_context=_context(),
            key=key,
            vector=vector,
            expected_sha256="0" * 64,
        )
    assert digest.value.error_code == "CX_PRIVATE_VECTOR_IMMUTABLE_CONFLICT"

    with pytest.raises(CxPrivateContentError) as dimension:
        short_digest = sha256_private_vector((1.0, 0.0))
        dimension_binding = replace(binding, embedding_sha256=short_digest)
        dimension_store, _dimension_factory = _store(dimension_binding)
        dimension_store.put_vector(
            access_context=_context(),
            key=_key(dimension_binding),
            vector=(1.0, 0.0),
            expected_sha256=short_digest,
        )
    assert dimension.value.error_code == "CX_PRIVATE_VECTOR_DIMENSION_MISMATCH"

    store.put_vector(
        access_context=_context(),
        key=key,
        vector=vector,
        expected_sha256=binding.embedding_sha256,
    )
    factory.rows[str(binding.summary_embedding_id)]["summary_text_sha256"] = "f" * 64
    with pytest.raises(CxPrivateContentError) as conflict:
        store.put_vector(
            access_context=_context(),
            key=key,
            vector=vector,
            expected_sha256=binding.embedding_sha256,
        )
    assert conflict.value.error_code == "CX_PRIVATE_VECTOR_IMMUTABLE_CONFLICT"


def test_summary_pgvector_enforces_owner_kind_and_summary_identity():
    binding, _vector = _binding()
    store, _factory = _store(binding)
    with pytest.raises(CxPrivateContentError) as owner:
        store.freshness(access_context=_context(owner="other-owner"))
    assert owner.value.error_code == "CX_PRIVATE_PAYLOAD_NOT_FOUND"

    with pytest.raises(CxPrivateContentError) as key_owner:
        store.get_vector(
            access_context=_context(),
            key=_key(binding, owner="other-owner"),
            expected_sha256=binding.embedding_sha256,
            expected_dimension=3,
        )
    assert key_owner.value.error_code == "CX_PRIVATE_PAYLOAD_NOT_FOUND"

    with pytest.raises(CxPrivateContentError) as kind:
        store.storage_uri(_key(binding, kind="chunk_embedding"))
    assert kind.value.error_code == "CX_SUMMARY_PGVECTOR_KIND_INVALID"

    with pytest.raises(CxPrivateContentError) as identity:
        store.storage_uri(_key(binding, content_id=str(uuid4())))
    assert identity.value.error_code == "CX_PRIVATE_PAYLOAD_NOT_FOUND"


@pytest.mark.parametrize("value", [None, True, 0, -1, "3"])
def test_summary_pgvector_get_rejects_invalid_dimension(value):
    binding, _vector = _binding()
    store, _factory = _store(binding)
    with pytest.raises(CxPrivateContentError) as caught:
        store.get_vector(
            access_context=_context(),
            key=_key(binding),
            expected_sha256=binding.embedding_sha256,
            expected_dimension=value,  # type: ignore[arg-type]
        )
    assert caught.value.error_code == "CX_PRIVATE_VECTOR_DIMENSION_INVALID"


def test_summary_freshness_reports_all_current_lineage_changes():
    binding, _vector = _binding()
    stored = {
        "document_summary_id": str(uuid4()),
        "content_object_id": str(uuid4()),
        "tenant_ref_id": "other-tenant",
        "owner_subject_ref_id": "other-owner",
        "summary_text_sha256": "1" * 64,
        "profile_fingerprint": "2" * 64,
        "embedding_sha256": "3" * 64,
        "vector_dimension": 99,
    }
    result = assess_summary_vector_freshness(
        replace(
            binding,
            content_status="DELETED",
            summary_status="STALE",
            embedding_status="FAILED",
        ),
        stored,
    )
    assert result["state"] == "STALE"
    assert result["usable"] is False
    assert result["reasons"] == sorted(
        {
            "CONTENT_LINEAGE_CHANGED",
            "CONTENT_NOT_ACTIVE",
            "EMBEDDING_CHANGED",
            "EMBEDDING_NOT_READY",
            "EMBEDDING_PROFILE_CHANGED",
            "OWNER_SCOPE_CHANGED",
            "SUMMARY_CHANGED",
            "SUMMARY_LINEAGE_CHANGED",
            "SUMMARY_NOT_READY",
            "VECTOR_DIMENSION_CHANGED",
        }
    )
    missing = assess_summary_vector_freshness(binding, None)
    assert missing["reasons"] == ["VECTOR_MISSING"]


@pytest.mark.parametrize("value", [None, "bad", "[bad]"])
def test_summary_pgvector_parser_fails_closed(value):
    with pytest.raises(CxPrivateContentError) as caught:
        _parse_pgvector(value)
    assert caught.value.error_code == "CX_PRIVATE_VECTOR_ENCODING_INVALID"


@pytest.mark.parametrize("operation", ["put", "get", "delete", "freshness"])
def test_summary_pgvector_maps_sqlalchemy_failures(operation):
    class FailingFactory:
        def __call__(self):
            raise OperationalError("SQL secret", {}, RuntimeError("password"))

        def begin(self):
            return self()

    binding, vector = _binding()
    store = BoundSummaryPgVectorStore(  # type: ignore[arg-type]
        FailingFactory(), binding=binding
    )
    with pytest.raises(CxPrivateContentError) as caught:
        if operation == "put":
            store.put_vector(
                access_context=_context(),
                key=_key(binding),
                vector=vector,
                expected_sha256=binding.embedding_sha256,
            )
        elif operation == "get":
            store.get_vector(
                access_context=_context(),
                key=_key(binding),
                expected_sha256=binding.embedding_sha256,
                expected_dimension=3,
            )
        elif operation == "delete":
            store.delete_vector(access_context=_context(), key=_key(binding))
        else:
            store.freshness(access_context=_context())
    assert caught.value.error_code == "CX_SUMMARY_PGVECTOR_STORAGE_UNAVAILABLE"
    assert caught.value.retryable is True
    assert "password" not in caught.value.detail


def test_summary_pgvector_get_rejects_tampered_stored_metadata_and_vector():
    binding, vector = _binding()
    store, factory = _store(binding)
    key = _key(binding)
    store.put_vector(
        access_context=_context(),
        key=key,
        vector=vector,
        expected_sha256=binding.embedding_sha256,
    )
    factory.rows[str(binding.summary_embedding_id)]["vector_dimension"] = 9
    with pytest.raises(CxPrivateContentError) as metadata:
        store.get_vector(
            access_context=_context(),
            key=key,
            expected_sha256=binding.embedding_sha256,
            expected_dimension=3,
        )
    assert metadata.value.error_code == "CX_PRIVATE_VECTOR_DIMENSION_MISMATCH"

    factory.rows[str(binding.summary_embedding_id)]["vector_dimension"] = 3
    factory.rows[str(binding.summary_embedding_id)]["embedding"] = "[broken]"
    with pytest.raises(CxPrivateContentError) as encoding:
        store.get_vector(
            access_context=_context(),
            key=key,
            expected_sha256=binding.embedding_sha256,
            expected_dimension=3,
        )
    assert encoding.value.error_code == "CX_PRIVATE_VECTOR_ENCODING_INVALID"

    short_vector = (1.0, 0.0)
    short_digest = sha256_private_vector(short_vector)
    short_binding = replace(binding, embedding_sha256=short_digest)
    short_store, short_factory = _store(short_binding)
    short_factory.rows[str(short_binding.summary_embedding_id)] = {
        "summary_vector_id": str(short_binding.summary_vector_id),
        "summary_text_sha256": short_binding.summary_text_sha256,
        "profile_fingerprint": short_binding.profile_fingerprint,
        "embedding_sha256": short_binding.embedding_sha256,
        "vector_dimension": short_binding.vector_dimension,
        "embedding": "[1.0,0.0]",
    }
    with pytest.raises(CxPrivateContentError) as vector_length:
        short_store.get_vector(
            access_context=_context(),
            key=_key(short_binding),
            expected_sha256=short_digest,
            expected_dimension=3,
        )
    assert vector_length.value.error_code == "CX_PRIVATE_VECTOR_DIMENSION_MISMATCH"


def test_summary_pgvector_builder_uses_vector_route_and_worker_pool(monkeypatch):
    captured = {}
    settings = SimpleNamespace(
        vector_database_url="postgresql://vector:secret@localhost/vector",
        redacted_vector_database_url="postgresql://vector:***@localhost/vector",
        vector_uses_primary=False,
    )
    monkeypatch.setattr(
        summary_pgvector_store,
        "service_database_settings",
        lambda **kwargs: settings,
    )
    monkeypatch.setattr(
        summary_pgvector_store,
        "database_pool_settings",
        lambda *args, **kwargs: captured.setdefault("pool", object()),
    )
    monkeypatch.setattr(
        summary_pgvector_store,
        "build_engine",
        lambda url, **kwargs: captured.update(url=url, **kwargs) or object(),
    )
    monkeypatch.setattr(
        summary_pgvector_store,
        "build_session_factory",
        lambda _engine: _SessionFactory(),
    )

    store = build_summary_pgvector_store(
        database_env="NEX_CX_TEST_DATABASE_URL", environ={"X": "1"}
    )

    assert store.redacted_database_url.endswith("@localhost/vector")
    assert store.uses_primary_database is False
    assert captured["url"] == settings.vector_database_url
    assert captured["pool_settings"] is captured["pool"]


def test_summary_pgvector_builder_rejects_missing_vector_route(monkeypatch):
    monkeypatch.setattr(
        summary_pgvector_store,
        "service_database_settings",
        lambda **_kwargs: SimpleNamespace(
            vector_database_url=None,
            redacted_vector_database_url=None,
        ),
    )
    with pytest.raises(CxPrivateContentError) as caught:
        build_summary_pgvector_store(environ={})
    assert caught.value.error_code == "CX_VECTOR_DATABASE_CONFIG_INVALID"
