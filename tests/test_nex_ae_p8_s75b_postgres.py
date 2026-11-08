from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from nex_ae_api.voucher_attachments import SqlAlchemyVoucherAttachmentRepository
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool


DATABASE_URL = os.getenv("NEX_AE_TEST_DATABASE_URL")
SMOKE_ENABLED = os.getenv("NEX_AE_P8_S75B_POSTGRES_SMOKE") == "1"

pytestmark = pytest.mark.skipif(
    not DATABASE_URL or not SMOKE_ENABLED,
    reason="Protected P8-S75B PostgreSQL smoke is disabled",
)


def test_actual_ae_postgres_attachment_persistence_and_restart() -> None:
    assert DATABASE_URL is not None
    assert make_url(DATABASE_URL).database == "nex_ae_test"
    suffix = uuid4().hex
    tenant_id = f"tenant-p8-s75b-{suffix}"
    batch_id = str(uuid4())
    item_id = str(uuid4())
    engine = create_engine(DATABASE_URL, poolclass=NullPool)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    repository = SqlAlchemyVoucherAttachmentRepository(
        factory, clock=lambda: datetime(2026, 10, 23, 11, 30, tzinfo=UTC)
    )
    batch = {
        "schema_version": "ae_voucher_attachment_batch.v1",
        "attachment_batch_id": batch_id,
        "tenant_id": tenant_id,
        "owner_subject_ref": {"type": "oa.user", "id": "employee-1001"},
        "conversation_id": str(uuid4()),
        "interaction_id": str(uuid4()),
        "trace": {
            "trace_id": f"trace-{suffix}",
            "correlation_id": f"correlation-{suffix}",
            "causation_id": f"causation-{suffix}",
        },
    }
    item = {
        "tenant_id": tenant_id,
        "attachment_batch_id": batch_id,
        "attachment_id": item_id,
        "display_name": "actual-postgres-receipt.pdf",
        "media_type": "application/pdf",
        "size_bytes": 2048,
    }
    try:
        with engine.connect() as connection:
            migration = connection.execute(
                text(
                    "SELECT count(*) FROM schema_migrations "
                    "WHERE version = '2513_ae_voucher_attachment'"
                )
            ).scalar_one()
        assert migration == 1
        first = repository.create_batch(batch)
        assert repository.create_batch(batch) == first
        first_item = repository.register_item(item)
        assert repository.register_item(item) == first_item

        restarted = SqlAlchemyVoucherAttachmentRepository(factory)
        restored = restarted.get_batch(
            tenant_id=tenant_id, attachment_batch_id=batch_id
        )
        assert restored is not None
        assert restored["attachment_count"] == 1
        assert restored["items"][0]["attachment_id"] == item_id

        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT b.attachment_count, count(a.attachment_id) AS item_count "
                    "FROM ae_voucher_attach_batch b "
                    "LEFT JOIN ae_voucher_attachment a "
                    "ON a.tenant_id = b.tenant_id "
                    "AND a.attachment_batch_id = b.attachment_batch_id "
                    "WHERE b.tenant_id = :tenant_id "
                    "GROUP BY b.attachment_count"
                ),
                {"tenant_id": tenant_id},
            ).mappings().one()
        assert rows == {"attachment_count": 1, "item_count": 1}
    finally:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM ae_voucher_attach_batch "
                    "WHERE tenant_id = :tenant_id"
                ),
                {"tenant_id": tenant_id},
            )
        engine.dispose()
