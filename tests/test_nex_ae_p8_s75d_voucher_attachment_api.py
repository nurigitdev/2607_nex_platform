from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from nex_ae_api.voucher_attachment_api import register_voucher_attachment_routes
from nex_ae_api.voucher_attachment_storage import VoucherAttachmentObjectGateway
from nex_ae_api.voucher_attachments import (
    SqlAlchemyVoucherAttachmentRepository,
    VoucherAttachmentPersistenceError,
)
from nex_runtime import (
    DEFAULT_USER_SCOPE,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
    issue_mock_user_token,
)
from nex_runtime.object_storage import ObjectStorageSettings, S3ObjectStore
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

TENANT = "tenant-p8-s75d"
OWNER = "employee-1001"
BATCH_ID = "75d00000-0000-4000-8000-000000000001"
CONVERSATION_ID = "75d00000-0000-4000-8000-000000000002"
INTERACTION_ID = "75d00000-0000-4000-8000-000000000003"
ATTACHMENT_ID = "75d00000-0000-4000-8000-000000000004"
REQUEST_ID = "75d00000-0000-4000-8000-000000000005"
TRACE_ID = "75d00000000040008000000000000006"
PAYLOAD = b"P8-S75D protected receipt"


class _Body(BytesIO):
    pass


class _S3Client:
    def __init__(self) -> None:
        self.objects: dict[str, dict[str, object]] = {}
        self.version = 0

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
            "ServerSideEncryption": "AES256",
            "VersionId": value["version_id"],
        }

    def put_object(self, *, Key, Body, **kwargs):
        self.version += 1
        self.objects[Key] = {
            "payload": Body.read(),
            "content_type": kwargs["ContentType"],
            "sha256": kwargs["Metadata"]["sha256"],
            "version_id": f"version-{self.version}",
        }
        return {"VersionId": f"version-{self.version}"}

    def get_object(self, *, Key, **_kwargs):
        try:
            value = self.objects[Key]
        except KeyError as exc:
            exc.response = {"ResponseMetadata": {"HTTPStatusCode": 404}}
            raise
        return {
            "ContentLength": len(value["payload"]),
            "Body": _Body(value["payload"]),
        }

    def delete_object(self, *, Key, **_kwargs):
        self.objects.pop(Key, None)
        return {"VersionId": "deleted"}


@pytest.fixture
def api_boundary():
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
    repository = SqlAlchemyVoucherAttachmentRepository(
        factory, clock=lambda: datetime(2026, 10, 23, 15, 0, tzinfo=UTC)
    )
    object_client = _S3Client()
    store = S3ObjectStore(
        object_client,
        ObjectStorageSettings(
            owner="nex-ae-api",
            endpoint_url="https://object.test",
            bucket="nex-ae-private",
            access_key="test-access",
            secret_key="test-secret-value",
        ),
    )
    gateway = VoucherAttachmentObjectGateway(store, repository)
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    register_voucher_attachment_routes(
        app, repository=repository, gateway=gateway
    )
    with TestClient(app) as client:
        yield engine, repository, object_client, client
    engine.dispose()


def _headers(*, tenant=TENANT, owner=OWNER):
    token = issue_mock_user_token(
        tenant_id=tenant,
        user_id=owner,
        scopes=[DEFAULT_USER_SCOPE],
        roles=["employee"],
    )
    return {
        "Authorization": f"Bearer {token.access_token}",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def _create_batch(client: TestClient, *, batch_id=BATCH_ID, headers=None):
    return client.post(
        "/api/v1/voucher-attachments/batches",
        headers=headers or _headers(),
        json={
            "attachment_batch_id": batch_id,
            "conversation_id": CONVERSATION_ID,
            "interaction_id": INTERACTION_ID,
        },
    )


def _upload(client: TestClient, *, attachment_id=ATTACHMENT_ID, **changes):
    content = changes.pop("content", PAYLOAD)
    content_type = changes.pop("content_type", "application/pdf")
    filename = changes.pop("filename", "receipt.pdf")
    return client.post(
        f"/api/v1/voucher-attachments/batches/{BATCH_ID}/items",
        headers=_headers(),
        data={"attachment_id": attachment_id, **changes},
        files={"file": (filename, content, content_type)},
    )


def test_zero_file_batch_create_get_and_finalize(api_boundary) -> None:
    _engine, _repository, _objects, client = api_boundary
    created = _create_batch(client)
    assert created.status_code == 201
    assert created.json()["owner_subject_ref"]["id"] == OWNER
    observed = client.get(
        f"/api/v1/voucher-attachments/batches/{BATCH_ID}", headers=_headers()
    )
    assert observed.status_code == 200
    assert observed.json()["items"] == []
    finalized = client.post(
        f"/api/v1/voucher-attachments/batches/{BATCH_ID}/finalize",
        headers=_headers(),
    )
    assert finalized.status_code == 200
    assert finalized.json()["state"] == "READY"


def test_file_upload_replay_progress_preview_download_and_remove(api_boundary) -> None:
    _engine, _repository, objects, client = api_boundary
    assert _create_batch(client).status_code == 201
    uploaded = _upload(client)
    assert uploaded.status_code == 201
    item = uploaded.json()["attachment"]
    assert item["state"] == "READY"
    assert item["object_ref"].startswith("objref:ae:voucher:")
    assert len(objects.objects) == 1

    replay = _upload(client)
    assert replay.status_code == 200
    assert replay.json()["attachment"] == item
    assert len(objects.objects) == 1

    progress = client.get(
        f"/api/v1/voucher-attachments/batches/{BATCH_ID}", headers=_headers()
    )
    assert progress.json()["attachment_count"] == 1
    assert progress.json()["total_size_bytes"] == len(PAYLOAD)

    content_path = (
        f"/api/v1/voucher-attachments/batches/{BATCH_ID}/items/"
        f"{ATTACHMENT_ID}/content"
    )
    preview = client.get(content_path, headers=_headers())
    assert preview.status_code == 200
    assert preview.content == PAYLOAD
    assert preview.headers["cache-control"] == "private, no-store"
    assert preview.headers["content-disposition"].startswith("inline;")
    download = client.get(content_path, headers=_headers(), params={"download": "true"})
    assert download.status_code == 200
    assert download.headers["content-disposition"].startswith("attachment;")

    removed = client.delete(
        f"/api/v1/voucher-attachments/batches/{BATCH_ID}/items/{ATTACHMENT_ID}",
        headers=_headers(),
    )
    assert removed.status_code == 200
    assert removed.json()["state"] == "REMOVED"
    assert objects.objects == {}
    assert client.delete(
        f"/api/v1/voucher-attachments/batches/{BATCH_ID}/items/{ATTACHMENT_ID}",
        headers=_headers(),
    ).status_code == 200


def test_many_files_finalize_and_partial_batch_rejection(api_boundary) -> None:
    _engine, repository, _objects, client = api_boundary
    assert _create_batch(client).status_code == 201
    second_id = "75d00000-0000-4000-8000-000000000007"
    assert _upload(client).status_code == 201
    assert _upload(
        client,
        attachment_id=second_id,
        content=b"second receipt",
        filename="second.png",
        content_type="image/png",
    ).status_code == 201
    finalized = client.post(
        f"/api/v1/voucher-attachments/batches/{BATCH_ID}/finalize",
        headers=_headers(),
    )
    assert finalized.status_code == 200
    assert finalized.json()["attachment_count"] == 2

    other_batch = "75d00000-0000-4000-8000-000000000008"
    created = client.post(
        "/api/v1/voucher-attachments/batches",
        headers=_headers(),
        json={
            "attachment_batch_id": other_batch,
            "conversation_id": "75d00000-0000-4000-8000-000000000009",
            "interaction_id": "75d00000-0000-4000-8000-000000000010",
        },
    )
    assert created.status_code == 201
    repository.register_item(
        {
            "tenant_id": TENANT,
            "attachment_batch_id": other_batch,
            "attachment_id": "75d00000-0000-4000-8000-000000000011",
            "display_name": "pending.pdf",
            "media_type": "application/pdf",
            "size_bytes": 10,
        }
    )
    partial = client.post(
        f"/api/v1/voucher-attachments/batches/{other_batch}/finalize",
        headers=_headers(),
    )
    assert partial.status_code == 409


def test_owner_and_service_authorization_fail_closed(api_boundary) -> None:
    _engine, _repository, _objects, client = api_boundary
    assert _create_batch(client).status_code == 201
    assert _upload(client).status_code == 201
    path = (
        f"/api/v1/voucher-attachments/batches/{BATCH_ID}/items/"
        f"{ATTACHMENT_ID}/content"
    )
    assert client.get(path).status_code == 401
    assert client.get(path, headers=_headers(owner="employee-2002")).status_code == 404

    wc = issue_mock_service_token(service_id="nex-wc", audience="nex-ae-api")
    service_headers = {
        "Authorization": f"Bearer {wc.access_token}",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }
    reviewed = client.get(path, headers=service_headers, params={"tenant_id": TENANT})
    assert reviewed.status_code == 200
    assert reviewed.content == PAYLOAD

    cx = issue_mock_service_token(service_id="nex-cx", audience="nex-ae-api")
    service_headers["Authorization"] = f"Bearer {cx.access_token}"
    assert client.get(
        path, headers=service_headers, params={"tenant_id": TENANT}
    ).status_code == 403
    assert _create_batch(client, headers=service_headers).status_code == 403


def test_invalid_media_size_and_unavailable_runtime(api_boundary) -> None:
    _engine, _repository, _objects, client = api_boundary
    assert _create_batch(client).status_code == 201
    invalid = _upload(
        client,
        filename="program.exe",
        content_type="application/x-executable",
    )
    assert invalid.status_code == 422
    assert invalid.json()["error_code"] == "ae.voucher_attachment.invalid"

    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    register_voucher_attachment_routes(app, repository=None, gateway=None)
    with TestClient(app) as unavailable:
        assert _create_batch(unavailable).status_code == 503
        batch_path = f"/api/v1/voucher-attachments/batches/{BATCH_ID}"
        assert unavailable.get(batch_path, headers=_headers()).status_code == 503
        assert unavailable.post(
            f"{batch_path}/items",
            headers=_headers(),
            files={"file": ("receipt.pdf", PAYLOAD, "application/pdf")},
        ).status_code == 503
        assert unavailable.delete(
            f"{batch_path}/items/{ATTACHMENT_ID}", headers=_headers()
        ).status_code == 503
        assert unavailable.post(
            f"{batch_path}/finalize", headers=_headers()
        ).status_code == 503
        assert unavailable.get(
            f"{batch_path}/items/{ATTACHMENT_ID}/content", headers=_headers()
        ).status_code == 503


def test_route_error_and_missing_item_paths_are_explicit(api_boundary) -> None:
    _engine, _repository, _objects, client = api_boundary
    invalid = client.post(
        "/api/v1/voucher-attachments/batches",
        headers=_headers(),
        json={"conversation_id": "bad", "interaction_id": "bad"},
    )
    assert invalid.status_code == 422
    missing_path = (
        f"/api/v1/voucher-attachments/batches/{BATCH_ID}/items/"
        f"{ATTACHMENT_ID}"
    )
    assert client.get(
        f"/api/v1/voucher-attachments/batches/{BATCH_ID}", headers=_headers()
    ).status_code == 404
    assert client.delete(missing_path, headers=_headers()).status_code == 404
    assert client.post(
        f"/api/v1/voucher-attachments/batches/{BATCH_ID}/finalize",
        headers=_headers(),
    ).status_code == 404

    assert _create_batch(client).status_code == 201
    assert client.get(f"{missing_path}/content", headers=_headers()).status_code == 404
    assert client.post(
        f"/api/v1/voucher-attachments/batches/{BATCH_ID}/items",
        files={"file": ("receipt.pdf", PAYLOAD, "application/pdf")},
    ).status_code == 401
    assert client.delete(missing_path).status_code == 401
    assert client.post(
        f"/api/v1/voucher-attachments/batches/{BATCH_ID}/finalize"
    ).status_code == 401


def test_service_preview_requires_tenant_and_existing_scope(api_boundary) -> None:
    _engine, _repository, _objects, client = api_boundary
    wc = issue_mock_service_token(service_id="nex-wc", audience="nex-ae-api")
    headers = {
        "Authorization": f"Bearer {wc.access_token}",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }
    path = (
        f"/api/v1/voucher-attachments/batches/{BATCH_ID}/items/"
        f"{ATTACHMENT_ID}/content"
    )
    assert client.get(path, headers=headers).status_code == 403
    assert client.get(
        path, headers=headers, params={"tenant_id": TENANT}
    ).status_code == 404


def test_repository_remove_and_finalize_state_guards(api_boundary) -> None:
    engine, repository, _objects, client = api_boundary
    with pytest.raises(VoucherAttachmentPersistenceError) as missing_batch:
        repository.remove_item(
            tenant_id=TENANT,
            attachment_batch_id=BATCH_ID,
            attachment_id=ATTACHMENT_ID,
        )
    assert missing_batch.value.status_code == 404
    with pytest.raises(VoucherAttachmentPersistenceError) as missing_finalize:
        repository.finalize_batch(
            tenant_id=TENANT, attachment_batch_id=BATCH_ID
        )
    assert missing_finalize.value.status_code == 404

    assert _create_batch(client).status_code == 201
    with pytest.raises(VoucherAttachmentPersistenceError) as missing_item:
        repository.remove_item(
            tenant_id=TENANT,
            attachment_batch_id=BATCH_ID,
            attachment_id=ATTACHMENT_ID,
        )
    assert missing_item.value.status_code == 404

    assert _upload(client).status_code == 201
    ready = repository.finalize_batch(
        tenant_id=TENANT, attachment_batch_id=BATCH_ID
    )
    assert repository.finalize_batch(
        tenant_id=TENANT, attachment_batch_id=BATCH_ID
    ) == ready
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE ae_voucher_attach_batch SET state = 'LOCKED', "
                "locked_at = :locked_at, attachment_manifest_hash = :digest"
            ),
            {"locked_at": datetime.now(UTC), "digest": "sha256:" + "a" * 64},
        )
    with pytest.raises(VoucherAttachmentPersistenceError) as locked_remove:
        repository.remove_item(
            tenant_id=TENANT,
            attachment_batch_id=BATCH_ID,
            attachment_id=ATTACHMENT_ID,
        )
    assert locked_remove.value.status_code == 409
    with pytest.raises(VoucherAttachmentPersistenceError) as locked_finalize:
        repository.finalize_batch(
            tenant_id=TENANT, attachment_batch_id=BATCH_ID
        )
    assert locked_finalize.value.status_code == 409


def test_finalize_detects_aggregate_integrity_drift(api_boundary) -> None:
    engine, _repository, _objects, client = api_boundary
    assert _create_batch(client).status_code == 201
    assert _upload(client).status_code == 201
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE ae_voucher_attach_batch SET attachment_count = 2")
        )
    response = client.post(
        f"/api/v1/voucher-attachments/batches/{BATCH_ID}/finalize",
        headers=_headers(),
    )
    assert response.status_code == 500
    assert response.json()["error_code"] == "ae.voucher_attachment.integrity_failed"
