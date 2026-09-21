from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from nex_cx.access_context import CxAccessContext
from nex_cx.private_content import (
    CxPrivateContentError,
    build_private_payload_receipt,
)
from nex_cx.vector_index_freshness import (
    build_embedding_profile,
    build_source_snapshot,
    build_vector_index_manifest,
)
from nex_cx.vector_index_publish import VectorIndexPublishError, publish_vector_index
from nex_cx.vector_index_repository import (
    InMemoryVectorIndexRepository,
    SqlAlchemyVectorIndexRepository,
    VectorIndexRepositoryError,
    _manifests_equivalent,
    _timestamp,
)
from nex_runtime import build_engine, build_session_factory


def _manifest(*, dimension: int = 2):
    chunks = [str(uuid4()), str(uuid4())]
    source = build_source_snapshot(
        chunk_set_id=str(uuid4()),
        chunk_policy_id="1000_100",
        source_markdown_sha256="1" * 64,
        chunks=[
            {"chunk_id": chunk, "ordinal": index, "text_sha256": str(index + 2) * 64}
            for index, chunk in enumerate(chunks)
        ],
    )
    profile = build_embedding_profile(
        provider_alias="mock",
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
        trace_id="trace-0935",
        request_id="request-0935",
        observed_at="2026-09-21T13:00:00Z",
    )


def _context(*, owner="owner-a"):
    return CxAccessContext(
        caller_service_id="nex-cx",
        tenant_id="tenant-a",
        subject_id=owner,
        request_id="request-0935",
        trace_id="93500000000000000000000000000001",
        scopes=("service:call",),
    )


def _vectors(manifest):
    return {
        item["chunk_id"]: (float(index == 0), float(index == 1))
        for index, item in enumerate(manifest["source_snapshot"]["chunk_refs"])
    }


class _BoundStore:
    def __init__(self, *, fail_at=None, delete_fails=False):
        self.rows = {}
        self.fail_at = fail_at
        self.delete_fails = delete_fails
        self.put_count = 0
        self.deleted = []

    def put_vector(self, *, access_context, key, vector, expected_sha256):
        self.put_count += 1
        if self.fail_at == self.put_count:
            raise CxPrivateContentError(
                status_code=503,
                error_code="CX_PGVECTOR_STORAGE_UNAVAILABLE",
                detail="unavailable",
                retryable=True,
            )
        self.rows[key.content_id] = tuple(vector)
        return build_private_payload_receipt(
            key=key,
            storage_backend="postgresql-pgvector-v1",
            storage_uri=f"cx-private://pgvector/{uuid4()}",
            sha256=expected_sha256,
            size_bytes=16,
            vector_dimension=len(vector),
        )

    def delete_vector(self, *, access_context, key):
        if self.delete_fails:
            raise CxPrivateContentError(
                status_code=503,
                error_code="CX_PGVECTOR_STORAGE_UNAVAILABLE",
                detail="unavailable",
            )
        self.deleted.append(key.content_id)
        return self.rows.pop(key.content_id, None) is not None


class _Adapter:
    def __init__(self, bound):
        self.bound = bound

    def bind_index(self, manifest):
        return self.bound


def test_publish_vector_index_persists_ready_manifest_and_receipts():
    manifest = _manifest()
    repository = InMemoryVectorIndexRepository()
    bound = _BoundStore()

    ready = publish_vector_index(
        access_context=_context(),
        manifest=manifest,
        vectors_by_chunk_id=_vectors(manifest),
        vector_store=_Adapter(bound),  # type: ignore[arg-type]
        repository=repository,
        observed_at="2026-09-21T13:01:00Z",
    )

    assert ready["status"] == "READY"
    assert ready["payload_count"] == 2
    assert ready["payload_fingerprint"] is not None
    assert ready["checkpoint_version"] == 1
    assert len(bound.rows) == 2
    assert repository.get(
        ready["vector_index_id"], tenant_id="tenant-a", owner_subject_id="owner-a"
    ) == ready


@pytest.mark.parametrize("mutation", ["owner", "status", "set", "dimension"])
def test_publish_vector_index_validates_everything_before_writes(mutation):
    manifest = _manifest()
    vectors = _vectors(manifest)
    context = _context()
    if mutation == "owner":
        context = _context(owner="other")
    elif mutation == "status":
        manifest["status"] = "FAILED"
        manifest["status_reason"] = "BUILD_FAILED"
    elif mutation == "set":
        vectors.pop(next(iter(vectors)))
    else:
        vectors[next(iter(vectors))] = (1.0,)
    bound = _BoundStore()

    with pytest.raises(VectorIndexPublishError):
        publish_vector_index(
            access_context=context,
            manifest=manifest,
            vectors_by_chunk_id=vectors,
            vector_store=_Adapter(bound),  # type: ignore[arg-type]
            repository=InMemoryVectorIndexRepository(),
            observed_at="2026-09-21T13:01:00Z",
        )
    assert bound.put_count == 0


def test_publish_failure_compensates_payloads_and_records_failed_manifest():
    manifest = _manifest()
    repository = InMemoryVectorIndexRepository()
    bound = _BoundStore(fail_at=2)

    with pytest.raises(VectorIndexPublishError) as caught:
        publish_vector_index(
            access_context=_context(),
            manifest=manifest,
            vectors_by_chunk_id=_vectors(manifest),
            vector_store=_Adapter(bound),  # type: ignore[arg-type]
            repository=repository,
            observed_at="2026-09-21T13:01:00Z",
        )

    assert caught.value.error_code == "cx.vector_index.publish_failed"
    assert caught.value.retryable is True
    assert bound.rows == {}
    assert len(bound.deleted) == 1
    failed = repository.get(
        manifest["vector_index_id"], tenant_id="tenant-a", owner_subject_id="owner-a"
    )
    assert failed is not None
    assert failed["status"] == "FAILED"
    assert failed["status_reason"] == "PAYLOAD_PUBLISH_FAILED"


def test_publish_reports_compensation_failure_and_swallows_failed_state_conflict():
    manifest = _manifest()
    base = InMemoryVectorIndexRepository()

    class ConflictRepository:
        def create(self, value):
            return base.create(value)

        def save(self, value, *, expected_checkpoint_version):
            raise VectorIndexRepositoryError("conflict", "conflict", retryable=True)

    bound = _BoundStore(delete_fails=True)
    with pytest.raises(VectorIndexPublishError) as caught:
        publish_vector_index(
            access_context=_context(),
            manifest=manifest,
            vectors_by_chunk_id=_vectors(manifest),
            vector_store=_Adapter(bound),  # type: ignore[arg-type]
            repository=ConflictRepository(),  # type: ignore[arg-type]
            observed_at="2026-09-21T13:01:00Z",
        )
    assert caught.value.retryable is False


def test_publish_rejects_persisted_manifest_conflict_before_payloads():
    manifest = _manifest()

    class DifferentRepository(InMemoryVectorIndexRepository):
        def create(self, value):
            result = deepcopy(value)
            result["request_id"] = "different"
            return result

    bound = _BoundStore()
    with pytest.raises(VectorIndexPublishError) as caught:
        publish_vector_index(
            access_context=_context(),
            manifest=manifest,
            vectors_by_chunk_id=_vectors(manifest),
            vector_store=_Adapter(bound),  # type: ignore[arg-type]
            repository=DifferentRepository(),
            observed_at="2026-09-21T13:01:00Z",
        )
    assert caught.value.error_code == "cx.vector_index.publish_manifest_conflict"
    assert bound.put_count == 0


def test_in_memory_repository_owner_idempotency_and_checkpoint_guards():
    manifest = _manifest()
    repository = InMemoryVectorIndexRepository()
    assert repository.create(manifest) == manifest
    assert repository.create(manifest) == manifest
    assert repository.get(
        manifest["vector_index_id"], tenant_id="tenant-a", owner_subject_id="other"
    ) is None
    assert repository.get("missing", tenant_id="tenant-a", owner_subject_id="owner-a") is None

    changed = deepcopy(manifest)
    changed["request_id"] = "changed"
    with pytest.raises(VectorIndexRepositoryError) as create_conflict:
        repository.create(changed)
    with pytest.raises(VectorIndexRepositoryError) as save_conflict:
        repository.save(manifest, expected_checkpoint_version=0)
    assert create_conflict.value.error_code == "cx.vector_index.create_conflict"
    assert save_conflict.value.retryable is True


def _sqlite_repository(manifest):
    engine = build_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE cx_vector_indexes (
                    vector_index_id TEXT PRIMARY KEY,
                    index_schema_version TEXT NOT NULL,
                    content_object_id TEXT NOT NULL,
                    chunk_set_id TEXT NOT NULL,
                    tenant_ref_type TEXT NOT NULL,
                    tenant_ref_id TEXT NOT NULL,
                    owner_subject_ref_type TEXT NOT NULL,
                    owner_subject_ref_id TEXT NOT NULL,
                    chunk_policy_id TEXT NOT NULL,
                    source_markdown_sha256 TEXT NOT NULL,
                    source_fingerprint TEXT NOT NULL,
                    source_chunk_count INTEGER NOT NULL,
                    provider_alias TEXT NOT NULL,
                    model_profile_id TEXT NOT NULL,
                    model_revision TEXT NOT NULL,
                    deployment_id TEXT NOT NULL,
                    vector_dimension INTEGER NOT NULL,
                    profile_fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL,
                    status_reason TEXT,
                    payload_count INTEGER NOT NULL,
                    payload_fingerprint TEXT,
                    checkpoint_version INTEGER NOT NULL,
                    trace_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    ready_at TEXT
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE cx_chunks (
                    chunk_id TEXT PRIMARY KEY,
                    chunk_set_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    text_sha256 TEXT NOT NULL
                )
                """
            )
        )
        for chunk in manifest["source_snapshot"]["chunk_refs"]:
            connection.execute(
                text(
                    "INSERT INTO cx_chunks (chunk_id, chunk_set_id, ordinal, text_sha256) "
                    "VALUES (:chunk_id, :chunk_set_id, :ordinal, :text_sha256)"
                ),
                {**chunk, "chunk_set_id": manifest["source_snapshot"]["chunk_set_id"]},
            )
    return SqlAlchemyVectorIndexRepository(build_session_factory(engine)), engine


def test_sqlalchemy_repository_create_get_save_and_conflicts():
    manifest = _manifest()
    repository, engine = _sqlite_repository(manifest)
    assert repository.create(manifest) == manifest
    assert repository.create(manifest) == manifest
    assert repository.get(
        manifest["vector_index_id"], tenant_id="tenant-a", owner_subject_id="other"
    ) is None

    changed = deepcopy(manifest)
    changed["request_id"] = "changed"
    with pytest.raises(VectorIndexRepositoryError):
        repository.create(changed)
    with pytest.raises(VectorIndexRepositoryError):
        repository.save(manifest, expected_checkpoint_version=0)

    failed = deepcopy(manifest)
    failed.update(
        status="FAILED",
        status_reason="PAYLOAD_PUBLISH_FAILED",
        checkpoint_version=1,
        updated_at="2026-09-21T13:01:00Z",
    )
    assert repository.save(failed, expected_checkpoint_version=0) == failed
    assert repository.get(
        manifest["vector_index_id"], tenant_id="tenant-a", owner_subject_id="owner-a"
    ) == failed
    with pytest.raises(VectorIndexRepositoryError) as checkpoint:
        repository.save(failed, expected_checkpoint_version=0)
    assert checkpoint.value.error_code == "cx.vector_index.checkpoint_conflict"
    engine.dispose()


@pytest.mark.parametrize("operation", ["create", "get", "save"])
def test_sqlalchemy_repository_maps_database_failures(operation):
    class FailingFactory:
        def __call__(self):
            raise OperationalError("SQL", {}, RuntimeError("private"))

        def begin(self):
            return self()

    repository = SqlAlchemyVectorIndexRepository(FailingFactory())  # type: ignore[arg-type]
    manifest = _manifest()
    if operation == "save":
        manifest.update(
            status="FAILED",
            status_reason="PAYLOAD_PUBLISH_FAILED",
            checkpoint_version=1,
            updated_at="2026-09-21T13:01:00Z",
        )
    with pytest.raises(VectorIndexRepositoryError) as caught:
        if operation == "create":
            repository.create(manifest)
        elif operation == "get":
            repository.get(
                manifest["vector_index_id"],
                tenant_id="tenant-a",
                owner_subject_id="owner-a",
            )
        else:
            repository.save(manifest, expected_checkpoint_version=0)
    assert caught.value.error_code == "cx.vector_index.repository_unavailable"
    assert caught.value.retryable is True


def test_repository_timestamp_normalizes_datetime_values():
    class Timestamp:
        def isoformat(self):
            return "2026-09-21T13:00:00+00:00"

    assert _timestamp(Timestamp()).endswith("+00:00")

    left = _manifest()
    right = deepcopy(left)
    left["created_at"] = "not-a-timestamp"
    right["created_at"] = "also-invalid"
    assert _manifests_equivalent(left, right) is False
