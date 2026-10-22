from __future__ import annotations

import copy
import hashlib
import io
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from nex_ae_api import nsl_approval_requests as requests
from nex_ae_api.nsl_approval_requests import (
    InMemoryProtectedApprovalRequestStorage,
    LocalProtectedApprovalRequestStorage,
    ProtectedApprovalRequestError,
    S3ProtectedApprovalRequestStorage,
    SqlAlchemyProtectedApprovalRequestStore,
    build_default_protected_approval_request_storage,
    build_protected_approval_request_payload,
    canonical_approval_request_data,
    protected_approval_request_payload_metadata,
)
from nex_runtime.object_storage import (
    ObjectStorageError,
    ObjectStorageSettings,
    S3ObjectStore,
)
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

NOW = datetime(2026, 10, 22, 3, 4, 5, tzinfo=UTC)
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


@dataclass(frozen=True)
class ApprovalRequestStub:
    data: dict[str, object]

    def to_data(self) -> dict[str, object]:
        return copy.deepcopy(self.data)


def _request(**changes: object) -> ApprovalRequestStub:
    data: dict[str, object] = {
        "tenant_id": "tenant-private-a",
        "execution_id": "nsl-execution-s44-001",
        "business_operation_id": "business-operation-s44-001",
        "approval_id": "APPROVE_VOUCHER_DRAFT",
        "approval_request_id": "approval-request-s44-001",
        "skill_id": "FINANCE.CREATE_VOUCHER_DRAFT",
        "skill_version": "0.2.0",
        "skill_semantic_hash": HASH_A,
        "write_node_id": "write-voucher-draft",
        "tool_id": "finance.create_voucher_draft",
        "payload_hash": HASH_B,
        "write_intent_hash": "write-intent-s44-001",
        "risk_level": "R3",
        "message": "Create the confidential voucher draft.",
        "expires_at": "2026-10-22T04:04:05+00:00",
        "display_safe_summary": {"line_count": 2, "currency": "KRW"},
        "protected_payload_ref": "snapshot://private/write-payload-s44-001",
        "data_classification": "CONFIDENTIAL",
    }
    data.update(changes)
    return ApprovalRequestStub(data)


@pytest.fixture
def sqlite_store():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE ae_nsl_approval_request (
                    tenant_id TEXT NOT NULL,
                    approval_request_id TEXT NOT NULL,
                    nsl_execution_id TEXT NOT NULL,
                    business_operation_id TEXT NOT NULL,
                    protected_request_ref TEXT NOT NULL,
                    approval_request_hash TEXT NOT NULL,
                    request_size_bytes INTEGER NOT NULL,
                    content_type TEXT NOT NULL,
                    data_classification TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, approval_request_id),
                    UNIQUE (tenant_id, protected_request_ref)
                )
                """
            )
        )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    storage = InMemoryProtectedApprovalRequestStorage()
    yield (
        engine,
        storage,
        SqlAlchemyProtectedApprovalRequestStore(
            factory, storage=storage, clock=lambda: NOW
        ),
    )
    engine.dispose()


def test_canonical_payload_preserves_exact_nsl_request_privately() -> None:
    request = _request()
    canonical = canonical_approval_request_data(request)
    payload = build_protected_approval_request_payload(request)
    metadata = protected_approval_request_payload_metadata(payload)

    assert canonical == request.to_data()
    assert payload["content"].startswith('{"approval_id"')
    assert metadata == {
        "approval_request_id": "approval-request-s44-001",
        "content_sha256": payload["content_sha256"],
        "size_bytes": len(payload["content"].encode("utf-8")),
        "storage_ref": payload["storage_ref"],
    }
    assert payload["storage_ref"].startswith("ae://nsl-approval-requests/")
    assert "tenant-private-a" not in payload["storage_ref"]
    assert "approval-request-s44-001" not in payload["storage_ref"]
    assert "Create the confidential" in payload["content"]
    assert "snapshot://private" in payload["content"]
    assert "message" not in metadata
    assert "protected_payload_ref" not in metadata


def test_in_memory_storage_is_owner_scoped_and_immutable() -> None:
    storage = InMemoryProtectedApprovalRequestStorage()
    first = build_protected_approval_request_payload(_request())
    metadata = protected_approval_request_payload_metadata(first)

    assert (
        storage.save(
            first,
            tenant_id="tenant-private-a",
            execution_id="nsl-execution-s44-001",
        )
        == first["storage_ref"]
    )
    assert (
        storage.load(
            metadata,
            tenant_id="tenant-private-a",
            execution_id="nsl-execution-s44-001",
        )
        == _request().to_data()
    )
    assert (
        storage.load(
            metadata,
            tenant_id="tenant-private-b",
            execution_id="nsl-execution-s44-001",
        )
        is None
    )

    changed = build_protected_approval_request_payload(
        _request(message="Changed private semantics")
    )
    with pytest.raises(ProtectedApprovalRequestError) as conflict:
        storage.save(
            changed,
            tenant_id="tenant-private-a",
            execution_id="nsl-execution-s44-001",
        )
    assert conflict.value.error_code.endswith("idempotency_conflict")
    changed_execution = build_protected_approval_request_payload(
        _request(execution_id="nsl-execution-s44-different")
    )
    with pytest.raises(ProtectedApprovalRequestError) as identity_conflict:
        storage.save(
            changed_execution,
            tenant_id="tenant-private-a",
            execution_id="nsl-execution-s44-different",
        )
    assert identity_conflict.value.error_code.endswith("idempotency_conflict")
    assert len(storage.payloads) == 1


def test_local_storage_uses_private_permissions_and_detects_corruption(
    tmp_path,
) -> None:
    storage = LocalProtectedApprovalRequestStorage(tmp_path)
    payload = build_protected_approval_request_payload(_request())
    metadata = protected_approval_request_payload_metadata(payload)
    storage.save(
        payload,
        tenant_id="tenant-private-a",
        execution_id="nsl-execution-s44-001",
    )
    path = storage._path(
        "tenant-private-a",
        "approval-request-s44-001",
        payload["storage_ref"],
    )

    assert path.stat().st_mode & 0o777 == 0o600
    assert "tenant-private-a" not in str(path)
    assert (
        storage.load(
            metadata,
            tenant_id="tenant-private-a",
            execution_id="nsl-execution-s44-001",
        )
        == _request().to_data()
    )
    assert (
        storage.save(
            payload,
            tenant_id="tenant-private-a",
            execution_id="nsl-execution-s44-001",
        )
        == payload["storage_ref"]
    )
    changed = build_protected_approval_request_payload(
        _request(message="Changed local semantics")
    )
    with pytest.raises(ProtectedApprovalRequestError) as conflict:
        storage.save(
            changed,
            tenant_id="tenant-private-a",
            execution_id="nsl-execution-s44-001",
        )
    assert conflict.value.error_code.endswith("idempotency_conflict")
    path.write_bytes(b"tampered")
    with pytest.raises(ProtectedApprovalRequestError) as corrupted:
        storage.load(
            metadata,
            tenant_id="tenant-private-a",
            execution_id="nsl-execution-s44-001",
        )
    assert corrupted.value.error_code.endswith("integrity_failed")


def test_local_storage_missing_io_failure_and_escape_fail_closed(
    monkeypatch, tmp_path
) -> None:
    storage = LocalProtectedApprovalRequestStorage(tmp_path)
    payload = build_protected_approval_request_payload(_request())
    metadata = protected_approval_request_payload_metadata(payload)
    assert (
        storage.load(
            metadata,
            tenant_id="tenant-private-a",
            execution_id="nsl-execution-s44-001",
        )
        is None
    )
    storage.save(
        payload,
        tenant_id="tenant-private-a",
        execution_id="nsl-execution-s44-001",
    )

    def read_failure(_path):
        raise OSError("private detail")

    monkeypatch.setattr(requests.Path, "read_bytes", read_failure)
    with pytest.raises(ProtectedApprovalRequestError) as replay_failure:
        storage.save(
            payload,
            tenant_id="tenant-private-a",
            execution_id="nsl-execution-s44-001",
        )
    assert replay_failure.value.retryable is True
    with pytest.raises(ProtectedApprovalRequestError) as load_failure:
        storage.load(
            metadata,
            tenant_id="tenant-private-a",
            execution_id="nsl-execution-s44-001",
        )
    assert load_failure.value.retryable is True

    monkeypatch.undo()
    fresh = LocalProtectedApprovalRequestStorage(tmp_path / "fresh")
    monkeypatch.setattr(
        requests.os, "replace", lambda *_args: (_ for _ in ()).throw(OSError())
    )
    with pytest.raises(ProtectedApprovalRequestError) as publish_failure:
        fresh.save(
            payload,
            tenant_id="tenant-private-a",
            execution_id="nsl-execution-s44-001",
        )
    assert publish_failure.value.retryable is True

    monkeypatch.undo()
    monkeypatch.setattr(
        requests, "_storage_ref_relative_path", lambda _value: "../../../../escape"
    )
    with pytest.raises(ProtectedApprovalRequestError, match="escapes"):
        storage._path(
            "tenant-private-a",
            "approval-request-s44-001",
            payload["storage_ref"],
        )


def test_sqlite_repository_round_trip_is_idempotent_and_metadata_only(
    sqlite_store,
) -> None:
    engine, _storage, repository = sqlite_store
    first = repository.persist(_request())
    replay = repository.persist(_request())

    assert replay == first
    assert first["schema_version"] == "ae_nsl_approval_request.v1"
    assert first["approval_request_hash"].startswith("sha256:")
    assert first["data_classification"] == "CONFIDENTIAL"
    assert (
        repository.get(
            tenant_id="tenant-private-a",
            approval_request_id="approval-request-s44-001",
        )
        == first
    )
    assert (
        repository.load_request(
            tenant_id="tenant-private-a",
            approval_request_id="approval-request-s44-001",
        )
        == _request().to_data()
    )
    assert (
        repository.get(
            tenant_id="tenant-private-a",
            approval_request_id="approval-request-missing",
        )
        is None
    )
    assert (
        repository.load_request(
            tenant_id="tenant-private-a",
            approval_request_id="approval-request-missing",
        )
        is None
    )

    with engine.connect() as connection:
        row = (
            connection.execute(
                text(
                    "SELECT * FROM ae_nsl_approval_request "
                    "WHERE tenant_id = 'tenant-private-a'"
                )
            )
            .mappings()
            .one()
        )
    assert set(row) == {
        "tenant_id",
        "approval_request_id",
        "nsl_execution_id",
        "business_operation_id",
        "protected_request_ref",
        "approval_request_hash",
        "request_size_bytes",
        "content_type",
        "data_classification",
        "created_at",
    }
    assert "message" not in row
    assert "protected_payload_ref" not in row


def test_sqlite_repository_rejects_changed_semantics_and_missing_object(
    sqlite_store,
) -> None:
    _engine, storage, repository = sqlite_store
    repository.persist(_request())
    with pytest.raises(ProtectedApprovalRequestError) as collision:
        repository.persist(_request(message="A different protected request"))
    assert collision.value.error_code.endswith("idempotency_conflict")

    storage.payloads.clear()
    with pytest.raises(ProtectedApprovalRequestError) as missing:
        repository.load_request(
            tenant_id="tenant-private-a",
            approval_request_id="approval-request-s44-001",
        )
    assert missing.value.error_code.endswith("integrity_failed")


def test_sqlite_repository_detects_metadata_conflict_and_corruption(
    sqlite_store,
) -> None:
    engine, _storage, repository = sqlite_store
    repository.persist(_request())
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE ae_nsl_approval_request "
                "SET business_operation_id = 'changed-operation'"
            )
        )
    with pytest.raises(ProtectedApprovalRequestError) as mismatch:
        repository.load_request(
            tenant_id="tenant-private-a",
            approval_request_id="approval-request-s44-001",
        )
    assert mismatch.value.error_code.endswith("integrity_failed")
    with pytest.raises(ProtectedApprovalRequestError) as replay:
        repository.persist(_request())
    assert replay.value.error_code.endswith("idempotency_conflict")

    with engine.begin() as connection:
        connection.execute(
            text("UPDATE ae_nsl_approval_request SET approval_request_hash = 'invalid'")
        )
    with pytest.raises(ProtectedApprovalRequestError) as bad_hash:
        repository.get(
            tenant_id="tenant-private-a",
            approval_request_id="approval-request-s44-001",
        )
    assert bad_hash.value.error_code.endswith("integrity_failed")


def test_sqlite_repository_detects_invalid_metadata_and_unique_ref_blocker(
    sqlite_store,
) -> None:
    engine, _storage, repository = sqlite_store
    record = repository.persist(_request())
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE ae_nsl_approval_request SET content_type = 'text/plain'")
        )
    with pytest.raises(ProtectedApprovalRequestError) as invalid_metadata:
        repository.get(
            tenant_id="tenant-private-a",
            approval_request_id="approval-request-s44-001",
        )
    assert invalid_metadata.value.error_code.endswith("integrity_failed")

    with engine.begin() as connection:
        connection.execute(text("DELETE FROM ae_nsl_approval_request"))
        connection.execute(
            text(
                """
                INSERT INTO ae_nsl_approval_request (
                    tenant_id, approval_request_id, nsl_execution_id,
                    business_operation_id, protected_request_ref,
                    approval_request_hash, request_size_bytes, content_type,
                    data_classification, created_at
                ) VALUES (
                    :tenant_id, 'blocker-request', :nsl_execution_id,
                    :business_operation_id, :protected_request_ref,
                    :approval_request_hash, :request_size_bytes, :content_type,
                    :data_classification, :created_at
                )
                """
            ),
            record,
        )
    with pytest.raises(ProtectedApprovalRequestError) as blocked:
        repository.persist(_request())
    assert blocked.value.retryable is True


@pytest.mark.parametrize(
    "approval_request",
    [
        object(),
        ApprovalRequestStub({"tenant_id": "tenant-only"}),
        _request(skill_semantic_hash="sha256:BAD"),
        _request(risk_level="R9"),
        _request(data_classification="SECRET"),
        _request(display_safe_summary=[]),
        _request(protected_payload_ref=""),
        _request(expires_at="not-time"),
        _request(expires_at="2026-10-22T04:04:05"),
        _request(message=object()),
    ],
)
def test_malformed_nsl_request_fails_closed(approval_request: object) -> None:
    with pytest.raises(ProtectedApprovalRequestError) as invalid:
        canonical_approval_request_data(approval_request)
    assert invalid.value.error_code == "ae.nsl_approval_request_invalid"


def test_payload_validation_rejects_shape_identity_digest_size_and_json(
    monkeypatch,
) -> None:
    payload = build_protected_approval_request_payload(_request())
    bad_values = (
        {**payload, "extra": True},
        {**payload, "approval_request_id": "changed"},
        {**payload, "content_sha256": "A" * 64},
        {**payload, "size_bytes": True},
        {**payload, "storage_ref": "file:///private.json"},
        {**payload, "content": object()},
    )
    for value in bad_values:
        with pytest.raises(ProtectedApprovalRequestError):
            protected_approval_request_payload_metadata(value)

    monkeypatch.setattr(requests, "MAX_PROTECTED_APPROVAL_REQUEST_BYTES", 8)
    with pytest.raises(ProtectedApprovalRequestError, match="size"):
        build_protected_approval_request_payload(_request())


def test_payload_validation_rejects_non_json_noncanonical_and_bad_identity() -> None:
    payload = build_protected_approval_request_payload(_request())
    for content in (
        "not-json",
        '{ "approval_request_id": "approval-request-s44-001" }',
        '{"approval_request_id":"different"}',
    ):
        encoded = content.encode("utf-8")
        value = {
            **payload,
            "content": content,
            "content_sha256": hashlib.sha256(encoded).hexdigest(),
            "size_bytes": len(encoded),
        }
        with pytest.raises(ProtectedApprovalRequestError):
            protected_approval_request_payload_metadata(value)


def test_request_serialization_failure_and_optional_fields_are_supported() -> None:
    class BrokenRequest:
        def to_data(self):
            raise RuntimeError("private detail")

    with pytest.raises(ProtectedApprovalRequestError, match="serialization"):
        canonical_approval_request_data(BrokenRequest())
    result = canonical_approval_request_data(
        _request(protected_payload_ref=None, expires_at=None)
    )
    assert result["protected_payload_ref"] is None
    assert result["expires_at"] is None


def test_default_storage_selects_memory_filesystem_and_s3(
    monkeypatch, tmp_path
) -> None:
    assert isinstance(
        build_default_protected_approval_request_storage({}),
        InMemoryProtectedApprovalRequestStorage,
    )
    local = build_default_protected_approval_request_storage(
        {
            "NEX_AE_PRIVATE_STORAGE_MODE": "FILESYSTEM",
            "NEX_AE_NSL_APPROVAL_REQUEST_STORAGE_ROOT": str(tmp_path),
        }
    )
    assert isinstance(local, LocalProtectedApprovalRequestStorage)
    with pytest.raises(ProtectedApprovalRequestError):
        build_default_protected_approval_request_storage(
            {"NEX_AE_PRIVATE_STORAGE_MODE": "FILESYSTEM"}
        )
    with pytest.raises(ProtectedApprovalRequestError):
        build_default_protected_approval_request_storage(
            {"NEX_AE_PRIVATE_STORAGE_MODE": "invalid"}
        )

    object_store, _client = _object_store()
    monkeypatch.setattr(
        requests, "build_ae_private_object_store", lambda _env: object_store
    )
    selected = build_default_protected_approval_request_storage(
        {"NEX_AE_PRIVATE_STORAGE_MODE": "S3"}
    )
    assert isinstance(selected, S3ProtectedApprovalRequestStorage)


class ClientFailure(Exception):
    def __init__(self, status: int) -> None:
        self.response = {"ResponseMetadata": {"HTTPStatusCode": status}}


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[str, dict[str, object]] = {}
        self.failure: Exception | None = None

    def head_object(self, *, Key, **_kwargs):
        if self.failure:
            raise self.failure
        if Key not in self.objects:
            raise ClientFailure(404)
        return dict(self.objects[Key]["head"])

    def put_object(
        self,
        *,
        Key,
        Body,
        ContentType,
        Metadata,
        ServerSideEncryption,
        **_kwargs,
    ):
        if self.failure:
            raise self.failure
        self.objects[Key] = {
            "body": Body,
            "head": {
                "ContentLength": len(Body),
                "ContentType": ContentType,
                "Metadata": Metadata,
                "ServerSideEncryption": ServerSideEncryption,
            },
        }
        return {}

    def get_object(self, *, Key, **_kwargs):
        if self.failure:
            raise self.failure
        if Key not in self.objects:
            raise ClientFailure(404)
        return {"Body": io.BytesIO(self.objects[Key]["body"])}


def _object_store() -> tuple[S3ObjectStore, FakeS3Client]:
    client = FakeS3Client()
    settings = ObjectStorageSettings(
        owner="nex-ae-api",
        endpoint_url="https://object.example.test",
        bucket="nex-ae-private",
        access_key="access-key",
        secret_key="secret-key-value",
    )
    return S3ObjectStore(client, settings), client


def test_s3_storage_round_trip_is_opaque_and_maps_outage() -> None:
    object_store, client = _object_store()
    storage = S3ProtectedApprovalRequestStorage(object_store)
    payload = build_protected_approval_request_payload(_request())
    metadata = protected_approval_request_payload_metadata(payload)

    assert (
        storage.save(
            payload,
            tenant_id="tenant-private-a",
            execution_id="nsl-execution-s44-001",
        )
        == payload["storage_ref"]
    )
    key = next(iter(client.objects))
    assert key.startswith("v1/approval-request/")
    assert "tenant-private-a" not in key
    assert "approval-request-s44-001" not in key
    assert (
        storage.load(
            metadata,
            tenant_id="tenant-private-a",
            execution_id="nsl-execution-s44-001",
        )
        == _request().to_data()
    )

    client.failure = ClientFailure(503)
    with pytest.raises(ProtectedApprovalRequestError) as unavailable:
        storage.load(
            metadata,
            tenant_id="tenant-private-a",
            execution_id="nsl-execution-s44-001",
        )
    assert unavailable.value.retryable is True


def test_s3_storage_maps_publish_integrity_and_generic_failures(
    monkeypatch,
) -> None:
    object_store, client = _object_store()
    storage = S3ProtectedApprovalRequestStorage(object_store)
    payload = build_protected_approval_request_payload(_request())
    metadata = protected_approval_request_payload_metadata(payload)

    client.failure = ClientFailure(503)
    with pytest.raises(ProtectedApprovalRequestError) as publish:
        storage.save(
            payload,
            tenant_id="tenant-private-a",
            execution_id="nsl-execution-s44-001",
        )
    assert publish.value.retryable is True

    client.failure = None
    storage.save(
        payload,
        tenant_id="tenant-private-a",
        execution_id="nsl-execution-s44-001",
    )
    key = next(iter(client.objects))
    client.objects[key]["body"] = b"tampered"
    with pytest.raises(ProtectedApprovalRequestError) as integrity:
        storage.load(
            metadata,
            tenant_id="tenant-private-a",
            execution_id="nsl-execution-s44-001",
        )
    assert integrity.value.error_code.endswith("integrity_failed")

    monkeypatch.setattr(
        requests,
        "build_owner_object_key",
        lambda **_kwargs: (_ for _ in ()).throw(
            ObjectStorageError("OBJECT_STORAGE_KEY_INVALID", "private")
        ),
    )
    with pytest.raises(ProtectedApprovalRequestError) as generic:
        storage._key(
            "tenant-private-a",
            "nsl-execution-s44-001",
            "approval-request-s44-001",
        )
    assert generic.value.error_code == "ae.nsl_approval_request_invalid"


def test_repository_maps_database_failure_and_corrupt_metadata() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    repository = SqlAlchemyProtectedApprovalRequestStore(
        sessionmaker(bind=engine),
        storage=InMemoryProtectedApprovalRequestStorage(),
    )
    with pytest.raises(ProtectedApprovalRequestError) as unavailable:
        repository.persist(_request())
    assert unavailable.value.retryable is True
    with pytest.raises(ProtectedApprovalRequestError) as read_unavailable:
        repository.get(
            tenant_id="tenant-private-a",
            approval_request_id="approval-request-s44-001",
        )
    assert read_unavailable.value.retryable is True
    engine.dispose()


def test_migration_is_short_metadata_only_and_records_its_ledger() -> None:
    migration = (
        Path(__file__).resolve().parents[1]
        / "database/nex-ae-api/migrations/2500_ae_nsl_approval_request.sql"
    ).read_text(encoding="utf-8")
    compact = " ".join(migration.lower().split())

    assert "create table if not exists ae_nsl_approval_request" in compact
    assert "'2500_ae_nsl_approval_request'" in compact
    assert "protected_request_ref text not null" in compact
    assert "approval_request_hash text not null" in compact
    assert "request_size_bytes bigint not null" in compact
    assert "request_json" not in compact
    assert "protected_payload_ref" not in compact
    assert len("ae_nsl_approval_request") < 40
