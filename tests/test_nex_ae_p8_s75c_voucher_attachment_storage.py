from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from io import BytesIO, StringIO

import pytest
from nex_ae_api import voucher_attachments
from nex_ae_api.voucher_attachment_storage import (
    ATTACHMENT_PURPOSE,
    VoucherAttachmentObjectGateway,
    VoucherAttachmentStorageError,
)
from nex_ae_api.voucher_attachments import (
    ATTACHMENT_BATCH_SCHEMA_VERSION,
    MAX_ATTACHMENT_FILE_BYTES,
    SqlAlchemyVoucherAttachmentRepository,
    VoucherAttachmentPersistenceError,
)
from nex_runtime.object_storage import (
    ObjectStorageError,
    ObjectStorageSettings,
    S3ObjectStore,
    build_owner_object_key,
)
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

NOW = datetime(2026, 10, 23, 13, 0, tzinfo=UTC)
TENANT = "tenant-p8-s75c"
BATCH_ID = "75c00000-0000-4000-8000-000000000001"
ATTACHMENT_ID = "75c00000-0000-4000-8000-000000000002"
OWNER = "employee-1001"
PAYLOAD = b"P8-S75C immutable voucher evidence"


class _Body(BytesIO):
    pass


class _FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[str, dict[str, object]] = {}
        self.put_count = 0

    def head_bucket(self, **_kwargs):
        return {}

    def head_object(self, *, Key, **_kwargs):
        try:
            value = self.objects[Key]
        except KeyError as exc:
            exc.response = {"ResponseMetadata": {"HTTPStatusCode": 404}}
            raise
        return {
            "ContentLength": len(value["payload"]),
            "ContentType": value["content_type"],
            "Metadata": {"sha256": value["sha256"]},
            "ServerSideEncryption": value["encryption"],
            "VersionId": value["version_id"],
        }

    def put_object(self, *, Key, Body, **kwargs):
        payload = Body if isinstance(Body, bytes) else Body.read()
        self.put_count += 1
        version_id = f"version-{self.put_count}"
        self.objects[Key] = {
            "payload": payload,
            "content_type": kwargs["ContentType"],
            "sha256": kwargs["Metadata"]["sha256"],
            "encryption": kwargs["ServerSideEncryption"],
            "version_id": version_id,
        }
        return {"VersionId": version_id}

    def get_object(self, *, Key, **_kwargs):
        try:
            value = self.objects[Key]
        except KeyError as exc:
            exc.response = {"ResponseMetadata": {"HTTPStatusCode": 404}}
            raise
        return {"Body": _Body(value["payload"])}

    def delete_object(self, *, Key, **_kwargs):
        self.objects.pop(Key, None)
        return {"VersionId": "deleted-version"}


@pytest.fixture
def storage_boundary():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE ae_voucher_attach_batch (
                    tenant_id TEXT NOT NULL,
                    attachment_batch_id TEXT NOT NULL,
                    owner_subject_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    interaction_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    attachment_count INTEGER NOT NULL,
                    total_size_bytes INTEGER NOT NULL,
                    attachment_manifest_hash TEXT,
                    locked_at TEXT,
                    trace_id TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    causation_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, attachment_batch_id),
                    UNIQUE (tenant_id, conversation_id, interaction_id)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE ae_voucher_attachment (
                    tenant_id TEXT NOT NULL,
                    attachment_batch_id TEXT NOT NULL,
                    attachment_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    content_sha256 TEXT,
                    object_ref TEXT,
                    object_version_ref TEXT,
                    scan_status TEXT NOT NULL,
                    evidence_ref TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, attachment_batch_id, attachment_id),
                    UNIQUE (tenant_id, object_ref)
                )
                """
            )
        )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    repository = SqlAlchemyVoucherAttachmentRepository(factory, clock=lambda: NOW)
    client = _FakeS3Client()
    store = S3ObjectStore(
        client,
        ObjectStorageSettings(
            owner="nex-ae-api",
            endpoint_url="https://object.test",
            bucket="nex-ae-private",
            access_key="test-access",
            secret_key="test-secret-value",
        ),
    )
    gateway = VoucherAttachmentObjectGateway(store, repository)
    yield engine, repository, client, store, gateway
    engine.dispose()


def _batch(**changes):
    value = {
        "schema_version": ATTACHMENT_BATCH_SCHEMA_VERSION,
        "attachment_batch_id": BATCH_ID,
        "tenant_id": TENANT,
        "owner_subject_ref": {"type": "oa.user", "id": OWNER},
        "conversation_id": "75c00000-0000-4000-8000-000000000003",
        "interaction_id": "75c00000-0000-4000-8000-000000000004",
        "trace": {
            "trace_id": "trace-p8-s75c",
            "correlation_id": "correlation-p8-s75c",
            "causation_id": "causation-p8-s75c",
        },
    }
    value.update(changes)
    return value


def _item(attachment_id=ATTACHMENT_ID, **changes):
    value = {
        "tenant_id": TENANT,
        "attachment_batch_id": BATCH_ID,
        "attachment_id": attachment_id,
        "display_name": "receipt.pdf",
        "media_type": "application/pdf",
        "size_bytes": len(PAYLOAD),
    }
    value.update(changes)
    return value


def _register(repository, *, attachment_id=ATTACHMENT_ID, **changes):
    repository.create_batch(_batch())
    repository.register_item(_item(attachment_id, **changes))


def test_stream_store_publishes_without_materializing_and_replays(storage_boundary):
    _engine, _repository, client, store, _gateway = storage_boundary
    key = build_owner_object_key(
        payload_family="voucher-evidence",
        tenant_id=TENANT,
        subject_id=OWNER,
        content_id=ATTACHMENT_ID,
        suffix="bin",
    )
    digest = hashlib.sha256(PAYLOAD).hexdigest()
    first = store.put_immutable_stream(
        key=key,
        source=BytesIO(PAYLOAD),
        expected_sha256=digest,
        expected_size_bytes=len(PAYLOAD),
        max_size_bytes=1024,
        content_type="application/pdf",
    )
    replay = store.put_immutable_stream(
        key=key,
        source=BytesIO(PAYLOAD),
        expected_sha256=digest,
        expected_size_bytes=len(PAYLOAD),
        max_size_bytes=1024,
        content_type="application/pdf",
    )
    assert first == replay
    assert first.server_side_encryption == "AES256"
    assert client.put_count == 1


@pytest.mark.parametrize(
    ("source", "size", "digest", "code"),
    (
        (BytesIO(PAYLOAD), len(PAYLOAD) + 1, hashlib.sha256(PAYLOAD).hexdigest(), "OBJECT_STORAGE_INTEGRITY_MISMATCH"),
        (BytesIO(PAYLOAD), len(PAYLOAD), "0" * 64, "OBJECT_STORAGE_INTEGRITY_MISMATCH"),
        (StringIO("text"), 4, hashlib.sha256(b"text").hexdigest(), "OBJECT_STORAGE_STREAM_INVALID"),
    ),
)
def test_stream_store_rejects_size_hash_and_non_bytes(
    storage_boundary, source, size, digest, code
) -> None:
    _engine, _repository, _client, store, _gateway = storage_boundary
    with pytest.raises(ObjectStorageError) as error:
        store.put_immutable_stream(
            key="v1/voucher-evidence/aa/object.bin",
            source=source,
            expected_sha256=digest,
            expected_size_bytes=size,
            max_size_bytes=1024,
            content_type="application/pdf",
        )
    assert error.value.code == code


def test_gateway_publish_resolve_read_and_exact_replay(storage_boundary) -> None:
    _engine, repository, client, _store, gateway = storage_boundary
    _register(repository)
    resolved = gateway.publish(
        tenant_id=TENANT,
        attachment_batch_id=BATCH_ID,
        attachment_id=ATTACHMENT_ID,
        source=BytesIO(PAYLOAD),
    )
    replay = gateway.publish(
        tenant_id=TENANT,
        attachment_batch_id=BATCH_ID,
        attachment_id=ATTACHMENT_ID,
        source=BytesIO(b"ignored-on-safe-replay"),
    )
    assert replay["object_ref"] == resolved["object_ref"]
    assert resolved["purpose"] == ATTACHMENT_PURPOSE
    assert resolved["authenticated"] is True
    assert resolved["immutable"] is True
    assert "bucket" not in resolved and "key" not in resolved
    assert client.put_count == 1
    assert gateway.read_for_owner(
        tenant_id=TENANT,
        owner_subject_id=OWNER,
        object_ref=resolved["object_ref"],
    ) == PAYLOAD
    assert gateway.resolve(
        requester_service="nex-eos",
        tenant_id=TENANT,
        object_ref=resolved["object_ref"],
        required_purpose=ATTACHMENT_PURPOSE,
        authenticated=True,
    )["content_sha256"] == hashlib.sha256(PAYLOAD).hexdigest()


def test_gateway_rejects_wrong_authority_owner_tenant_and_purpose(
    storage_boundary,
) -> None:
    _engine, repository, _client, _store, gateway = storage_boundary
    _register(repository)
    resolved = gateway.publish(
        tenant_id=TENANT,
        attachment_batch_id=BATCH_ID,
        attachment_id=ATTACHMENT_ID,
        source=BytesIO(PAYLOAD),
    )
    for values in (
        {"requester_service": "nex-cx", "authenticated": True},
        {"requester_service": "nex-eos", "authenticated": False},
    ):
        with pytest.raises(VoucherAttachmentStorageError) as forbidden:
            gateway.resolve(
                tenant_id=TENANT,
                object_ref=resolved["object_ref"],
                required_purpose=ATTACHMENT_PURPOSE,
                **values,
            )
        assert forbidden.value.status_code == 403
    with pytest.raises(VoucherAttachmentStorageError) as purpose:
        gateway.resolve(
            requester_service="nex-eos",
            tenant_id=TENANT,
            object_ref=resolved["object_ref"],
            required_purpose="CX_DOCUMENT",
            authenticated=True,
        )
    assert purpose.value.status_code == 403
    with pytest.raises(VoucherAttachmentStorageError) as owner:
        gateway.read_for_owner(
            tenant_id=TENANT,
            owner_subject_id="employee-2002",
            object_ref=resolved["object_ref"],
        )
    assert owner.value.status_code == 403
    with pytest.raises(VoucherAttachmentStorageError) as tenant:
        gateway.resolve(
            requester_service="nex-eos",
            tenant_id="tenant-other",
            object_ref=resolved["object_ref"],
            required_purpose=ATTACHMENT_PURPOSE,
            authenticated=True,
        )
    assert tenant.value.status_code == 404


def test_gateway_rejects_size_media_and_object_metadata_tamper(storage_boundary) -> None:
    engine, repository, client, _store, gateway = storage_boundary
    _register(repository)
    with pytest.raises(VoucherAttachmentStorageError) as size_error:
        gateway.publish(
            tenant_id=TENANT,
            attachment_batch_id=BATCH_ID,
            attachment_id=ATTACHMENT_ID,
            source=BytesIO(PAYLOAD + b"x"),
        )
    assert size_error.value.status_code == 422

    resolved = gateway.publish(
        tenant_id=TENANT,
        attachment_batch_id=BATCH_ID,
        attachment_id=ATTACHMENT_ID,
        source=BytesIO(PAYLOAD),
    )
    stored = next(iter(client.objects.values()))
    stored["sha256"] = "0" * 64
    with pytest.raises(VoucherAttachmentStorageError) as integrity:
        gateway.resolve(
            requester_service="nex-eos",
            tenant_id=TENANT,
            object_ref=resolved["object_ref"],
            required_purpose=ATTACHMENT_PURPOSE,
            authenticated=True,
        )
    assert integrity.value.status_code == 500

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE ae_voucher_attachment SET scan_status = 'UNAVAILABLE' "
                "WHERE attachment_id = :attachment_id"
            ),
            {"attachment_id": ATTACHMENT_ID},
        )
    with pytest.raises(VoucherAttachmentStorageError) as admission:
        gateway.read_for_owner(
            tenant_id=TENANT,
            owner_subject_id=OWNER,
            object_ref=resolved["object_ref"],
        )
    assert admission.value.status_code == 500


def test_unreferenced_cleanup_is_allowed_but_ready_object_is_protected(
    storage_boundary,
) -> None:
    _engine, repository, client, store, gateway = storage_boundary
    _register(repository)
    key = build_owner_object_key(
        payload_family="voucher-evidence",
        tenant_id=TENANT,
        subject_id=OWNER,
        content_id=ATTACHMENT_ID,
        suffix="bin",
    )
    store.put_immutable_stream(
        key=key,
        source=BytesIO(PAYLOAD),
        expected_sha256=hashlib.sha256(PAYLOAD).hexdigest(),
        expected_size_bytes=len(PAYLOAD),
        max_size_bytes=1024,
        content_type="application/pdf",
    )
    assert gateway.cleanup_unreferenced(
        tenant_id=TENANT,
        attachment_batch_id=BATCH_ID,
        attachment_id=ATTACHMENT_ID,
    ) is True
    assert client.objects == {}
    assert gateway.cleanup_unreferenced(
        tenant_id=TENANT,
        attachment_batch_id=BATCH_ID,
        attachment_id=ATTACHMENT_ID,
    ) is False

    gateway.publish(
        tenant_id=TENANT,
        attachment_batch_id=BATCH_ID,
        attachment_id=ATTACHMENT_ID,
        source=BytesIO(PAYLOAD),
    )
    with pytest.raises(VoucherAttachmentStorageError) as protected:
        gateway.cleanup_unreferenced(
            tenant_id=TENANT,
            attachment_batch_id=BATCH_ID,
            attachment_id=ATTACHMENT_ID,
        )
    assert protected.value.status_code == 409


def test_repository_publication_guards_and_resolution(storage_boundary) -> None:
    _engine, repository, _client, _store, _gateway = storage_boundary
    with pytest.raises(VoucherAttachmentPersistenceError) as missing_batch:
        repository.publish_item(
            tenant_id=TENANT,
            attachment_batch_id=BATCH_ID,
            attachment_id=ATTACHMENT_ID,
            content_sha256="a" * 64,
            object_ref="objref:ae:voucher:" + "a" * 64,
            object_version_ref=None,
        )
    assert missing_batch.value.status_code == 404

    repository.create_batch(_batch())
    with pytest.raises(VoucherAttachmentPersistenceError) as missing:
        repository.publish_item(
            tenant_id=TENANT,
            attachment_batch_id=BATCH_ID,
            attachment_id=ATTACHMENT_ID,
            content_sha256="a" * 64,
            object_ref="objref:ae:voucher:" + "a" * 64,
            object_version_ref=None,
        )
    assert missing.value.status_code == 404

    repository.register_item(_item())
    first = repository.publish_item(
        tenant_id=TENANT,
        attachment_batch_id=BATCH_ID,
        attachment_id=ATTACHMENT_ID,
        content_sha256="a" * 64,
        object_ref="objref:ae:voucher:" + "a" * 64,
        object_version_ref=None,
    )
    assert repository.publish_item(
        tenant_id=TENANT,
        attachment_batch_id=BATCH_ID,
        attachment_id=ATTACHMENT_ID,
        content_sha256="a" * 64,
        object_ref="objref:ae:voucher:" + "a" * 64,
        object_version_ref=None,
    ) == first
    with pytest.raises(VoucherAttachmentPersistenceError) as conflict:
        repository.publish_item(
            tenant_id=TENANT,
            attachment_batch_id=BATCH_ID,
            attachment_id=ATTACHMENT_ID,
            content_sha256="b" * 64,
            object_ref="objref:ae:voucher:" + "a" * 64,
            object_version_ref=None,
        )
    assert conflict.value.status_code == 409
    assert repository.resolve_object_ref(
        tenant_id=TENANT, object_ref=first["object_ref"]
    )["attachment_id"] == ATTACHMENT_ID
    assert repository.resolve_object_ref(
        tenant_id="tenant-other", object_ref=first["object_ref"]
    ) is None


def test_repository_publication_rejects_locked_and_non_publishable_state(
    storage_boundary,
) -> None:
    engine, repository, _client, _store, _gateway = storage_boundary
    _register(repository)
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE ae_voucher_attach_batch SET state = 'LOCKED', "
                "locked_at = :locked_at, attachment_manifest_hash = :digest"
            ),
            {"locked_at": NOW, "digest": "sha256:" + "a" * 64},
        )
    with pytest.raises(VoucherAttachmentPersistenceError) as locked:
        repository.publish_item(
            tenant_id=TENANT,
            attachment_batch_id=BATCH_ID,
            attachment_id=ATTACHMENT_ID,
            content_sha256="a" * 64,
            object_ref="objref:ae:voucher:" + "a" * 64,
            object_version_ref=None,
        )
    assert locked.value.status_code == 409

    with engine.begin() as connection:
        connection.execute(text("UPDATE ae_voucher_attach_batch SET state = 'DRAFT'"))
        connection.execute(
            text("UPDATE ae_voucher_attachment SET state = 'QUARANTINED'")
        )
    with pytest.raises(VoucherAttachmentPersistenceError) as item_state:
        repository.publish_item(
            tenant_id=TENANT,
            attachment_batch_id=BATCH_ID,
            attachment_id=ATTACHMENT_ID,
            content_sha256="a" * 64,
            object_ref="objref:ae:voucher:" + "a" * 64,
            object_version_ref=None,
        )
    assert item_state.value.status_code == 409


@pytest.mark.parametrize(
    "changes",
    (
        {"content_sha256": "bad"},
        {"object_ref": "s3://private/key"},
        {"scan_status": "PENDING"},
        {"object_version_ref": "bad version"},
    ),
)
def test_repository_publication_validates_metadata(storage_boundary, changes) -> None:
    _engine, repository, _client, _store, _gateway = storage_boundary
    _register(repository)
    values = {
        "tenant_id": TENANT,
        "attachment_batch_id": BATCH_ID,
        "attachment_id": ATTACHMENT_ID,
        "content_sha256": "a" * 64,
        "object_ref": "objref:ae:voucher:" + "a" * 64,
        "object_version_ref": None,
        "scan_status": "CLEAN",
    }
    values.update(changes)
    with pytest.raises(VoucherAttachmentPersistenceError) as error:
        repository.publish_item(**values)
    assert error.value.status_code == 422


def test_repository_resolution_database_failure_is_redacted(storage_boundary) -> None:
    engine, repository, _client, _store, _gateway = storage_boundary
    engine.dispose()
    with pytest.raises(VoucherAttachmentPersistenceError) as error:
        repository.resolve_object_ref(
            tenant_id=TENANT, object_ref="objref:ae:voucher:" + "a" * 64
        )
    assert error.value.status_code == 503
    assert "sqlite" not in error.value.detail.lower()


def test_resolved_record_rejects_non_ready_state() -> None:
    row = {
        "tenant_id": TENANT,
        "attachment_batch_id": BATCH_ID,
        "owner_subject_id": OWNER,
        "attachment_id": ATTACHMENT_ID,
        "state": "UPLOADING",
        "display_name": "receipt.pdf",
        "media_type": "application/pdf",
        "size_bytes": len(PAYLOAD),
        "content_sha256": None,
        "object_ref": None,
        "object_version_ref": None,
        "scan_status": "PENDING",
        "evidence_ref": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    with pytest.raises(VoucherAttachmentPersistenceError) as error:
        voucher_attachments._resolved_record(row)
    assert error.value.status_code == 500


def test_registered_media_policy_is_frozen(storage_boundary) -> None:
    _engine, repository, _client, _store, _gateway = storage_boundary
    repository.create_batch(_batch())
    with pytest.raises(VoucherAttachmentPersistenceError) as error:
        repository.register_item(_item(media_type="application/x-executable"))
    assert error.value.status_code == 422


class _OversizedSource:
    def __init__(self) -> None:
        self._remaining = MAX_ATTACHMENT_FILE_BYTES + 1

    def read(self, maximum: int) -> bytes:
        if self._remaining <= 0:
            return b""
        count = min(maximum, self._remaining)
        self._remaining -= count
        return b"x" * count


def test_gateway_enforces_bounded_spool_without_batch_materialization(
    storage_boundary,
) -> None:
    _engine, repository, _client, _store, gateway = storage_boundary
    _register(repository)
    with pytest.raises(VoucherAttachmentStorageError) as error:
        gateway.publish(
            tenant_id=TENANT,
            attachment_batch_id=BATCH_ID,
            attachment_id=ATTACHMENT_ID,
            source=_OversizedSource(),
        )
    assert error.value.status_code == 413


class _UnreadableSource:
    def read(self, _maximum: int) -> bytes:
        raise OSError("private source detail")


def test_gateway_input_stream_failures_are_safe(storage_boundary) -> None:
    _engine, repository, _client, _store, gateway = storage_boundary
    _register(repository)
    for source in (_UnreadableSource(), StringIO("text"), BytesIO(b"")):
        with pytest.raises(VoucherAttachmentStorageError) as error:
            gateway.publish(
                tenant_id=TENANT,
                attachment_batch_id=BATCH_ID,
                attachment_id=ATTACHMENT_ID,
                source=source,
            )
        assert error.value.status_code == 422
        assert "private" not in error.value.detail


def test_gateway_missing_and_non_publishable_records_fail_closed(
    storage_boundary,
) -> None:
    engine, repository, _client, _store, gateway = storage_boundary
    with pytest.raises(VoucherAttachmentStorageError) as missing_batch:
        gateway.publish(
            tenant_id=TENANT,
            attachment_batch_id=BATCH_ID,
            attachment_id=ATTACHMENT_ID,
            source=BytesIO(PAYLOAD),
        )
    assert missing_batch.value.status_code == 404

    repository.create_batch(_batch())
    with pytest.raises(VoucherAttachmentStorageError) as missing_item:
        gateway.publish(
            tenant_id=TENANT,
            attachment_batch_id=BATCH_ID,
            attachment_id=ATTACHMENT_ID,
            source=BytesIO(PAYLOAD),
        )
    assert missing_item.value.status_code == 404

    repository.register_item(_item())
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE ae_voucher_attachment SET state = 'QUARANTINED'")
        )
    with pytest.raises(VoucherAttachmentStorageError) as blocked:
        gateway.publish(
            tenant_id=TENANT,
            attachment_batch_id=BATCH_ID,
            attachment_id=ATTACHMENT_ID,
            source=BytesIO(PAYLOAD),
        )
    assert blocked.value.status_code == 409


def test_gateway_translates_storage_and_persistence_failures(
    storage_boundary, monkeypatch
) -> None:
    _engine, repository, _client, store, gateway = storage_boundary
    _register(repository)
    monkeypatch.setattr(
        store,
        "put_immutable_stream",
        lambda **_kwargs: (_ for _ in ()).throw(
            ObjectStorageError(
                "OBJECT_STORAGE_UNAVAILABLE", "private object detail", retryable=True
            )
        ),
    )
    with pytest.raises(VoucherAttachmentStorageError) as storage_error:
        gateway.publish(
            tenant_id=TENANT,
            attachment_batch_id=BATCH_ID,
            attachment_id=ATTACHMENT_ID,
            source=BytesIO(PAYLOAD),
        )
    assert storage_error.value.status_code == 503
    assert storage_error.value.retryable is True
    assert "private" not in storage_error.value.detail

    monkeypatch.undo()
    monkeypatch.setattr(
        repository,
        "publish_item",
        lambda **_kwargs: (_ for _ in ()).throw(
            VoucherAttachmentPersistenceError(
                "ae.voucher_attachment.persistence_unavailable",
                "Voucher attachment persistence is unavailable.",
                503,
                True,
            )
        ),
    )
    with pytest.raises(VoucherAttachmentStorageError) as persistence_error:
        gateway.publish(
            tenant_id=TENANT,
            attachment_batch_id=BATCH_ID,
            attachment_id=ATTACHMENT_ID,
            source=BytesIO(PAYLOAD),
        )
    assert persistence_error.value.status_code == 503
    assert persistence_error.value.retryable is True


def test_gateway_read_cleanup_and_resolve_storage_failures(
    storage_boundary, monkeypatch
) -> None:
    _engine, repository, client, store, gateway = storage_boundary
    _register(repository)
    resolved = gateway.publish(
        tenant_id=TENANT,
        attachment_batch_id=BATCH_ID,
        attachment_id=ATTACHMENT_ID,
        source=BytesIO(PAYLOAD),
    )
    monkeypatch.setattr(
        store,
        "get_bytes",
        lambda **_kwargs: (_ for _ in ()).throw(
            ObjectStorageError("OBJECT_STORAGE_GET_FAILED", "private")
        ),
    )
    with pytest.raises(VoucherAttachmentStorageError) as read_error:
        gateway.read_for_owner(
            tenant_id=TENANT,
            owner_subject_id=OWNER,
            object_ref=resolved["object_ref"],
        )
    assert read_error.value.status_code == 503

    monkeypatch.setattr(store, "get_bytes", lambda **_kwargs: None)
    with pytest.raises(VoucherAttachmentStorageError) as missing_read:
        gateway.read_for_owner(
            tenant_id=TENANT,
            owner_subject_id=OWNER,
            object_ref=resolved["object_ref"],
        )
    assert missing_read.value.status_code == 500

    monkeypatch.undo()
    client.objects.clear()
    with pytest.raises(VoucherAttachmentStorageError) as missing_object:
        gateway.resolve(
            requester_service="nex-eos",
            tenant_id=TENANT,
            object_ref=resolved["object_ref"],
            required_purpose=ATTACHMENT_PURPOSE,
            authenticated=True,
        )
    assert missing_object.value.status_code == 500


def test_gateway_repository_read_failures_are_translated(
    storage_boundary, monkeypatch
) -> None:
    _engine, repository, _client, _store, gateway = storage_boundary
    persistence = VoucherAttachmentPersistenceError(
        "ae.voucher_attachment.persistence_unavailable",
        "Voucher attachment persistence is unavailable.",
        503,
        True,
    )
    monkeypatch.setattr(
        repository,
        "get_batch",
        lambda **_kwargs: (_ for _ in ()).throw(persistence),
    )
    with pytest.raises(VoucherAttachmentStorageError) as batch_error:
        gateway.publish(
            tenant_id=TENANT,
            attachment_batch_id=BATCH_ID,
            attachment_id=ATTACHMENT_ID,
            source=BytesIO(PAYLOAD),
        )
    assert batch_error.value.retryable is True

    monkeypatch.setattr(
        repository,
        "resolve_object_ref",
        lambda **_kwargs: (_ for _ in ()).throw(persistence),
    )
    with pytest.raises(VoucherAttachmentStorageError) as resolve_error:
        gateway.resolve(
            requester_service="nex-eos",
            tenant_id=TENANT,
            object_ref="objref:ae:voucher:" + "a" * 64,
            required_purpose=ATTACHMENT_PURPOSE,
            authenticated=True,
        )
    assert resolve_error.value.status_code == 503


def test_cleanup_storage_failure_and_error_string(storage_boundary, monkeypatch) -> None:
    _engine, repository, _client, store, gateway = storage_boundary
    _register(repository)
    monkeypatch.setattr(
        store,
        "head",
        lambda _key: (_ for _ in ()).throw(
            ObjectStorageError("OBJECT_STORAGE_HEAD_FAILED", "private")
        ),
    )
    with pytest.raises(VoucherAttachmentStorageError) as error:
        gateway.cleanup_unreferenced(
            tenant_id=TENANT,
            attachment_batch_id=BATCH_ID,
            attachment_id=ATTACHMENT_ID,
        )
    assert str(error.value) == "Voucher attachment object storage is unavailable."


@pytest.mark.parametrize(
    ("code", "status"),
    (
        ("OBJECT_STORAGE_IMMUTABLE_CONFLICT", 409),
        ("OBJECT_STORAGE_INTEGRITY_MISMATCH", 422),
    ),
)
def test_storage_validation_error_mapping(storage_boundary, monkeypatch, code, status):
    _engine, repository, _client, store, gateway = storage_boundary
    _register(repository)
    monkeypatch.setattr(
        store,
        "put_immutable_stream",
        lambda **_kwargs: (_ for _ in ()).throw(ObjectStorageError(code, "private")),
    )
    with pytest.raises(VoucherAttachmentStorageError) as error:
        gateway.publish(
            tenant_id=TENANT,
            attachment_batch_id=BATCH_ID,
            attachment_id=ATTACHMENT_ID,
            source=BytesIO(PAYLOAD),
        )
    assert error.value.status_code == status
    assert "private" not in error.value.detail
