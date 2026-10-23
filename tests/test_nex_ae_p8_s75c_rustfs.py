from __future__ import annotations

import os
from datetime import UTC, datetime
from io import BytesIO
from uuid import uuid4

import pytest
from nex_ae_api.voucher_attachment_storage import VoucherAttachmentObjectGateway
from nex_ae_api.voucher_attachments import SqlAlchemyVoucherAttachmentRepository
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
ENDPOINT = os.getenv("NEX_AE_P8_S75C_RUSTFS_ENDPOINT")
ACCESS_KEY = os.getenv("NEX_AE_P8_S75C_RUSTFS_ACCESS_KEY")
SECRET_KEY = os.getenv("NEX_AE_P8_S75C_RUSTFS_SECRET_KEY")
SMOKE_ENABLED = os.getenv("NEX_AE_P8_S75C_RUSTFS_SMOKE") == "1"
BUCKET = "nex-ae-p8-s75c"

pytestmark = pytest.mark.skipif(
    not all((DATABASE_URL, ENDPOINT, ACCESS_KEY, SECRET_KEY, SMOKE_ENABLED)),
    reason="Protected P8-S75C PostgreSQL and RustFS smoke is disabled",
)


def test_actual_rustfs_put_resolve_read_delete_with_ae_postgres() -> None:
    assert DATABASE_URL is not None
    assert ENDPOINT is not None
    assert ACCESS_KEY is not None
    assert SECRET_KEY is not None
    assert make_url(DATABASE_URL).database == "nex_ae_test"
    suffix = uuid4().hex
    tenant_id = f"tenant-p8-s75c-{suffix}"
    owner_id = f"employee-{suffix[:12]}"
    batch_id = str(uuid4())
    attachment_id = str(uuid4())
    payload = b"actual RustFS P8-S75C immutable Voucher evidence"
    settings = ObjectStorageSettings(
        owner="nex-ae-api",
        endpoint_url=ENDPOINT,
        bucket=BUCKET,
        access_key=ACCESS_KEY,
        secret_key=SECRET_KEY,
    )
    client = build_s3_client(settings)
    receipt = bootstrap_private_bucket(client, bucket=BUCKET)
    assert receipt.versioning_enabled is True
    store = S3ObjectStore(client, settings)
    engine = create_engine(DATABASE_URL, poolclass=NullPool)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    repository = SqlAlchemyVoucherAttachmentRepository(
        factory, clock=lambda: datetime(2026, 10, 23, 14, 0, tzinfo=UTC)
    )
    gateway = VoucherAttachmentObjectGateway(store, repository)
    key = build_owner_object_key(
        payload_family="voucher-evidence",
        tenant_id=tenant_id,
        subject_id=owner_id,
        content_id=attachment_id,
        suffix="bin",
    )
    try:
        with engine.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT count(*) FROM schema_migrations "
                    "WHERE version = '2513_ae_voucher_attachment'"
                )
            ).scalar_one() == 1
        repository.create_batch(
            {
                "schema_version": "ae_voucher_attachment_batch.v1",
                "attachment_batch_id": batch_id,
                "tenant_id": tenant_id,
                "owner_subject_ref": {"type": "oa.user", "id": owner_id},
                "conversation_id": str(uuid4()),
                "interaction_id": str(uuid4()),
                "trace": {
                    "trace_id": f"trace-{suffix}",
                    "correlation_id": f"correlation-{suffix}",
                    "causation_id": f"causation-{suffix}",
                },
            }
        )
        repository.register_item(
            {
                "tenant_id": tenant_id,
                "attachment_batch_id": batch_id,
                "attachment_id": attachment_id,
                "display_name": "actual-rustfs-receipt.pdf",
                "media_type": "application/pdf",
                "size_bytes": len(payload),
            }
        )
        resolved = gateway.publish(
            tenant_id=tenant_id,
            attachment_batch_id=batch_id,
            attachment_id=attachment_id,
            source=BytesIO(payload),
        )
        assert store.head(key) is not None
        replay = gateway.resolve(
            requester_service="nex-eos",
            tenant_id=tenant_id,
            object_ref=resolved["object_ref"],
            required_purpose="EOS_VOUCHER_ATTACHMENT",
            authenticated=True,
        )
        assert {key: value for key, value in replay.items() if key != "resolved_at"} == {
            key: value for key, value in resolved.items() if key != "resolved_at"
        }
        assert gateway.read_for_owner(
            tenant_id=tenant_id,
            owner_subject_id=owner_id,
            object_ref=resolved["object_ref"],
        ) == payload
    finally:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM ae_voucher_attach_batch "
                    "WHERE tenant_id = :tenant_id"
                ),
                {"tenant_id": tenant_id},
            )
        store.delete(key)
        assert store.head(key) is None
        engine.dispose()
