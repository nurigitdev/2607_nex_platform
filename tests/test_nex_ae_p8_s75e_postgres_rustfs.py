from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from nex_ae_api.voucher_attachment_api import register_voucher_attachment_routes
from nex_ae_api.voucher_attachment_storage import VoucherAttachmentObjectGateway
from nex_ae_api.voucher_attachments import SqlAlchemyVoucherAttachmentRepository
from nex_runtime import (
    DEFAULT_USER_SCOPE,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_user_token,
)
from nex_runtime.object_storage import (
    ObjectStorageSettings,
    S3ObjectStore,
    build_owner_object_key,
    build_s3_client,
)
from nex_runtime.object_storage_lifecycle import bootstrap_private_bucket
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

DATABASE_URL = os.getenv("NEX_AE_TEST_DATABASE_URL")
ENDPOINT = os.getenv("NEX_AE_P8_S75E_RUSTFS_ENDPOINT")
ACCESS_KEY = os.getenv("NEX_AE_P8_S75E_RUSTFS_ACCESS_KEY")
SECRET_KEY = os.getenv("NEX_AE_P8_S75E_RUSTFS_SECRET_KEY")
SMOKE_ENABLED = os.getenv("NEX_AE_P8_S75E_PROTECTED_SMOKE") == "1"
BUCKET = "nex-ae-p8-s75e"

pytestmark = pytest.mark.skipif(
    not all((DATABASE_URL, ENDPOINT, ACCESS_KEY, SECRET_KEY, SMOKE_ENABLED)),
    reason="Protected P8-S75E PostgreSQL and RustFS manifest smoke is disabled",
)


def test_actual_postgres_rustfs_manifest_lock_and_replay() -> None:
    assert DATABASE_URL is not None
    assert ENDPOINT is not None
    assert ACCESS_KEY is not None
    assert SECRET_KEY is not None
    assert make_url(DATABASE_URL).database == "nex_ae_test"
    suffix = uuid4().hex
    tenant_id = f"tenant-p8-s75e-{suffix}"
    owner_id = f"employee-{suffix[:12]}"
    batch_id = str(uuid4())
    attachment_id = str(uuid4())
    payload = b"actual PostgreSQL and RustFS P8-S75E locked receipt"
    settings = ObjectStorageSettings(
        owner="nex-ae-api",
        endpoint_url=ENDPOINT,
        bucket=BUCKET,
        access_key=ACCESS_KEY,
        secret_key=SECRET_KEY,
    )
    object_client = build_s3_client(settings)
    assert bootstrap_private_bucket(object_client, bucket=BUCKET).versioning_enabled
    store = S3ObjectStore(object_client, settings)
    engine = create_engine(DATABASE_URL, poolclass=NullPool)
    repository = SqlAlchemyVoucherAttachmentRepository(
        sessionmaker(bind=engine, expire_on_commit=False),
        clock=lambda: datetime(2026, 10, 23, 16, 30, tzinfo=UTC),
    )
    gateway = VoucherAttachmentObjectGateway(store, repository)
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    register_voucher_attachment_routes(app, repository=repository, gateway=gateway)
    token = issue_mock_user_token(
        tenant_id=tenant_id,
        user_id=owner_id,
        scopes=[DEFAULT_USER_SCOPE],
        roles=["employee"],
    )
    headers = {"Authorization": f"Bearer {token.access_token}"}
    batch_path = f"/api/v1/voucher-attachments/batches/{batch_id}"
    key = build_owner_object_key(
        payload_family="voucher-evidence",
        tenant_id=tenant_id,
        subject_id=owner_id,
        content_id=attachment_id,
        suffix="bin",
    )
    try:
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM schema_migrations "
                        "WHERE version = '2513_ae_voucher_attachment'"
                    )
                ).scalar_one()
                == 1
            )
        with TestClient(app) as client:
            assert (
                client.post(
                    "/api/v1/voucher-attachments/batches",
                    headers=headers,
                    json={
                        "attachment_batch_id": batch_id,
                        "conversation_id": str(uuid4()),
                        "interaction_id": str(uuid4()),
                    },
                ).status_code
                == 201
            )
            uploaded = client.post(
                f"{batch_path}/items",
                headers=headers,
                data={"attachment_id": attachment_id},
                files={"file": ("locked-receipt.pdf", payload, "application/pdf")},
            )
            assert uploaded.status_code == 201, uploaded.text
            assert (
                client.post(f"{batch_path}/finalize", headers=headers).json()["state"]
                == "READY"
            )
            locked = client.post(f"{batch_path}/lock", headers=headers)
            assert locked.status_code == 200
            manifest = locked.json()
            assert manifest["attachment_count"] == 1
            assert manifest["items"][0]["attachment_id"] == attachment_id
            assert manifest["attachment_manifest_hash"].startswith("sha256:")
            assert client.post(f"{batch_path}/lock", headers=headers).json() == manifest
            assert (
                client.get(
                    f"{batch_path}/items/{attachment_id}/content", headers=headers
                ).content
                == payload
            )
            assert (
                client.delete(
                    f"{batch_path}/items/{attachment_id}", headers=headers
                ).status_code
                == 409
            )
            assert (
                client.post(
                    f"{batch_path}/items",
                    headers=headers,
                    data={"attachment_id": str(uuid4())},
                    files={"file": ("late.pdf", b"late", "application/pdf")},
                ).status_code
                == 409
            )
        with engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        "SELECT state, attachment_manifest_hash, locked_at "
                        "FROM ae_voucher_attach_batch WHERE tenant_id = :tenant_id "
                        "AND attachment_batch_id = :batch_id"
                    ),
                    {"tenant_id": tenant_id, "batch_id": batch_id},
                )
                .mappings()
                .one()
            )
            assert row["state"] == "LOCKED"
            assert (
                row["attachment_manifest_hash"] == manifest["attachment_manifest_hash"]
            )
            assert row["locked_at"] is not None
            assert store.head(key) is not None
    finally:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM ae_voucher_attach_batch WHERE tenant_id = :tenant_id"
                ),
                {"tenant_id": tenant_id},
            )
        store.delete(key)
        engine.dispose()
