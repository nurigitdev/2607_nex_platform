from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
import nex_ae_api.voucher_attachments as voucher_attachments
from nex_ae_api.voucher_attachments import (
    ATTACHMENT_BATCH_SCHEMA_VERSION,
    MAX_ATTACHMENT_BATCH_BYTES,
    MAX_ATTACHMENT_COUNT,
    MAX_ATTACHMENT_FILE_BYTES,
    SqlAlchemyVoucherAttachmentRepository,
    VoucherAttachmentPersistenceError,
)
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


NOW = datetime(2026, 10, 23, 11, 0, tzinfo=UTC)
TENANT = "tenant-p8-s75b"
BATCH_ID = "75b00000-0000-4000-8000-000000000001"
CONVERSATION_ID = "75b00000-0000-4000-8000-000000000002"
INTERACTION_ID = "75b00000-0000-4000-8000-000000000003"


def _batch(**changes):
    value = {
        "schema_version": ATTACHMENT_BATCH_SCHEMA_VERSION,
        "attachment_batch_id": BATCH_ID,
        "tenant_id": TENANT,
        "owner_subject_ref": {"type": "oa.user", "id": "employee-1001"},
        "conversation_id": CONVERSATION_ID,
        "interaction_id": INTERACTION_ID,
        "trace": {
            "trace_id": "trace-p8-s75b",
            "correlation_id": "correlation-p8-s75b",
            "causation_id": "causation-p8-s75b",
        },
    }
    value.update(changes)
    return value


def _item(index=1, **changes):
    value = {
        "tenant_id": TENANT,
        "attachment_batch_id": BATCH_ID,
        "attachment_id": f"75b00000-0000-4000-8001-{index:012d}",
        "display_name": f"receipt-{index}.pdf",
        "media_type": "application/pdf",
        "size_bytes": 1024,
    }
    value.update(changes)
    return value


@pytest.fixture
def sqlite_repository():
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
                    FOREIGN KEY (tenant_id, attachment_batch_id)
                        REFERENCES ae_voucher_attach_batch (
                            tenant_id, attachment_batch_id
                        ) ON DELETE CASCADE,
                    UNIQUE (tenant_id, object_ref)
                )
                """
            )
        )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield engine, factory, SqlAlchemyVoucherAttachmentRepository(
        factory, clock=lambda: NOW
    )
    engine.dispose()


def test_migration_uses_short_metadata_only_tables() -> None:
    migration = (
        Path(__file__).resolve().parents[1]
        / "database/nex-ae-api/migrations/2513_ae_voucher_attachment.sql"
    ).read_text(encoding="utf-8")
    compact = " ".join(migration.lower().split())
    assert "create table if not exists ae_voucher_attach_batch" in compact
    assert "create table if not exists ae_voucher_attachment" in compact
    assert "attachment_count between 0 and 20" in compact
    assert "total_size_bytes between 0 and 104857600" in compact
    for forbidden in ("binary_data", "content_bytes", "presigned_url", "secret_key"):
        assert forbidden not in compact


def test_batch_and_item_exact_replay_survive_repository_restart(
    sqlite_repository,
) -> None:
    _engine, factory, repository = sqlite_repository
    created = repository.create_batch(_batch())
    replay = repository.create_batch(_batch())
    assert replay == created
    assert created["state"] == "DRAFT"
    assert created["attachment_count"] == 0

    first_item = repository.register_item(_item())
    replay_item = repository.register_item(_item())
    assert replay_item == first_item
    assert first_item["state"] == "UPLOADING"
    assert first_item["scan_status"] == "PENDING"

    restarted = SqlAlchemyVoucherAttachmentRepository(factory, clock=lambda: NOW)
    restored = restarted.get_batch(
        tenant_id=TENANT, attachment_batch_id=BATCH_ID
    )
    assert restored is not None
    assert restored["state"] == "UPLOADING"
    assert restored["attachment_count"] == 1
    assert restored["total_size_bytes"] == 1024
    assert restored["items"] == [first_item]


def test_batch_and_item_semantic_conflicts_are_rejected(sqlite_repository) -> None:
    _engine, _factory, repository = sqlite_repository
    repository.create_batch(_batch())
    with pytest.raises(VoucherAttachmentPersistenceError) as batch_conflict:
        repository.create_batch(
            _batch(owner_subject_ref={"type": "oa.user", "id": "employee-2002"})
        )
    assert batch_conflict.value.status_code == 409

    repository.register_item(_item())
    with pytest.raises(VoucherAttachmentPersistenceError) as item_conflict:
        repository.register_item(_item(display_name="changed.pdf"))
    assert item_conflict.value.status_code == 409


def test_interaction_identity_is_unique(sqlite_repository) -> None:
    _engine, _factory, repository = sqlite_repository
    repository.create_batch(_batch())
    with pytest.raises(VoucherAttachmentPersistenceError) as conflict:
        repository.create_batch(
            _batch(attachment_batch_id="75b00000-0000-4000-8000-000000000099")
        )
    assert conflict.value.status_code == 409


def test_count_and_batch_size_limits_are_atomic(sqlite_repository) -> None:
    engine, _factory, repository = sqlite_repository
    repository.create_batch(_batch())
    for index in range(1, MAX_ATTACHMENT_COUNT + 1):
        repository.register_item(_item(index))
    with pytest.raises(VoucherAttachmentPersistenceError) as count_error:
        repository.register_item(_item(MAX_ATTACHMENT_COUNT + 1))
    assert count_error.value.status_code == 413

    with engine.connect() as connection:
        count = connection.execute(
            text("SELECT count(*) FROM ae_voucher_attachment")
        ).scalar_one()
    assert count == MAX_ATTACHMENT_COUNT

    other = _batch(
        attachment_batch_id="75b00000-0000-4000-8000-000000000090",
        interaction_id="75b00000-0000-4000-8000-000000000091",
    )
    repository.create_batch(other)
    for index in range(1, 5):
        repository.register_item(
            _item(
                index + 100,
                attachment_batch_id=other["attachment_batch_id"],
                size_bytes=MAX_ATTACHMENT_FILE_BYTES,
            )
        )
    with pytest.raises(VoucherAttachmentPersistenceError) as byte_error:
        repository.register_item(
            _item(
                200,
                attachment_batch_id=other["attachment_batch_id"],
                size_bytes=1,
            )
        )
    assert byte_error.value.status_code == 413
    assert MAX_ATTACHMENT_BATCH_BYTES == 4 * MAX_ATTACHMENT_FILE_BYTES


@pytest.mark.parametrize(
    "value",
    (
        None,
        {},
        _batch(schema_version="bad"),
        _batch(owner_subject_ref={"type": "service", "id": "employee-1001"}),
        _batch(trace={"trace_id": "only"}),
        _batch(conversation_id="bad"),
    ),
)
def test_invalid_batch_input_fails_closed(sqlite_repository, value) -> None:
    _engine, _factory, repository = sqlite_repository
    with pytest.raises(VoucherAttachmentPersistenceError) as error:
        repository.create_batch(value)
    assert error.value.status_code == 422


def test_invalid_owner_shape_and_error_string_fail_closed(sqlite_repository) -> None:
    _engine, _factory, repository = sqlite_repository
    with pytest.raises(VoucherAttachmentPersistenceError) as error:
        repository.create_batch(_batch(owner_subject_ref=None))
    assert str(error.value) == "Voucher attachment owner is invalid."


@pytest.mark.parametrize(
    "changes",
    (
        {"size_bytes": 0},
        {"size_bytes": True},
        {"size_bytes": MAX_ATTACHMENT_FILE_BYTES + 1},
        {"display_name": "../receipt.pdf"},
        {"media_type": "not-media"},
        {"attachment_id": "bad"},
    ),
)
def test_invalid_item_input_fails_closed(sqlite_repository, changes) -> None:
    _engine, _factory, repository = sqlite_repository
    repository.create_batch(_batch())
    with pytest.raises(VoucherAttachmentPersistenceError) as error:
        repository.register_item(_item(**changes))
    assert error.value.status_code in {413, 422}


def test_non_object_item_input_fails_closed(sqlite_repository) -> None:
    _engine, _factory, repository = sqlite_repository
    with pytest.raises(VoucherAttachmentPersistenceError) as error:
        repository.register_item(None)
    assert error.value.status_code == 422


def test_missing_and_locked_batch_reject_item(sqlite_repository) -> None:
    engine, _factory, repository = sqlite_repository
    with pytest.raises(VoucherAttachmentPersistenceError) as missing:
        repository.register_item(_item())
    assert missing.value.status_code == 404

    repository.create_batch(_batch())
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE ae_voucher_attach_batch SET state = 'LOCKED', "
                "locked_at = :locked_at, attachment_manifest_hash = :hash"
            ),
            {"locked_at": NOW, "hash": "sha256:" + "a" * 64},
        )
    with pytest.raises(VoucherAttachmentPersistenceError) as locked:
        repository.register_item(_item())
    assert locked.value.status_code == 409


def test_missing_read_and_database_failure_are_safe(sqlite_repository) -> None:
    engine, _factory, repository = sqlite_repository
    assert repository.get_batch(
        tenant_id=TENANT, attachment_batch_id=BATCH_ID
    ) is None
    engine.dispose()
    with pytest.raises(VoucherAttachmentPersistenceError) as error:
        repository.get_batch(tenant_id=TENANT, attachment_batch_id=BATCH_ID)
    assert error.value.error_code == "ae.voucher_attachment.persistence_unavailable"
    assert "sqlite" not in error.value.detail.lower()


def test_create_and_register_database_failures_are_redacted(sqlite_repository) -> None:
    engine, _factory, repository = sqlite_repository
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE ae_voucher_attachment"))
        connection.execute(text("DROP TABLE ae_voucher_attach_batch"))

    with pytest.raises(VoucherAttachmentPersistenceError) as create_error:
        repository.create_batch(_batch())
    assert create_error.value.status_code == 503
    assert create_error.value.retryable is True

    with pytest.raises(VoucherAttachmentPersistenceError) as register_error:
        repository.register_item(_item())
    assert register_error.value.status_code == 503
    assert "sqlite" not in register_error.value.detail.lower()


def test_corrupt_persisted_states_fail_integrity_validation(sqlite_repository) -> None:
    engine, _factory, repository = sqlite_repository
    repository.create_batch(_batch())
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE ae_voucher_attach_batch SET state = 'CORRUPT'")
        )
    with pytest.raises(VoucherAttachmentPersistenceError) as batch_error:
        repository.get_batch(tenant_id=TENANT, attachment_batch_id=BATCH_ID)
    assert batch_error.value.error_code == "ae.voucher_attachment.integrity_failed"

    with engine.begin() as connection:
        connection.execute(text("UPDATE ae_voucher_attach_batch SET state = 'DRAFT'"))
    repository.register_item(_item())
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE ae_voucher_attachment SET scan_status = 'CORRUPT'")
        )
    with pytest.raises(VoucherAttachmentPersistenceError) as item_error:
        repository.get_batch(tenant_id=TENANT, attachment_batch_id=BATCH_ID)
    assert item_error.value.error_code == "ae.voucher_attachment.integrity_failed"


def test_wire_time_accepts_datetime_and_rejects_invalid_text() -> None:
    assert voucher_attachments._wire_time(NOW) == "2026-10-23T11:00:00Z"
    with pytest.raises(VoucherAttachmentPersistenceError) as error:
        voucher_attachments._wire_time("not-a-time")
    assert error.value.status_code == 500


class _FakeExecuteResult:
    def __init__(self, rowcount: int = 1) -> None:
        self.rowcount = rowcount


class _FakeSession:
    def __init__(self, results=(), error: Exception | None = None) -> None:
        self._results = iter(results)
        self._error = error

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, *_args, **_kwargs):
        if self._error is not None:
            raise self._error
        return next(self._results, _FakeExecuteResult())

    def commit(self) -> None:
        return None


def _fake_repository(session: _FakeSession) -> SqlAlchemyVoucherAttachmentRepository:
    return SqlAlchemyVoucherAttachmentRepository(lambda: session, clock=lambda: NOW)


def _persisted_batch() -> dict[str, object]:
    return {"state": "DRAFT", "attachment_count": 0, "total_size_bytes": 0}


def test_defensive_missing_rows_and_concurrent_update_are_rejected(monkeypatch) -> None:
    monkeypatch.setattr(voucher_attachments, "_load_batch", lambda *_args, **_kwargs: None)
    with pytest.raises(VoucherAttachmentPersistenceError) as missing_create:
        _fake_repository(_FakeSession()).create_batch(_batch())
    assert missing_create.value.status_code == 503

    monkeypatch.setattr(
        voucher_attachments, "_load_batch", lambda *_args, **_kwargs: _persisted_batch()
    )
    monkeypatch.setattr(voucher_attachments, "_load_item", lambda *_args, **_kwargs: None)
    with pytest.raises(VoucherAttachmentPersistenceError) as concurrent:
        _fake_repository(
            _FakeSession((_FakeExecuteResult(), _FakeExecuteResult(rowcount=0)))
        ).register_item(_item())
    assert concurrent.value.status_code == 409

    with pytest.raises(VoucherAttachmentPersistenceError) as missing_item:
        _fake_repository(
            _FakeSession((_FakeExecuteResult(), _FakeExecuteResult(rowcount=1)))
        ).register_item(_item())
    assert missing_item.value.status_code == 503


def test_register_integrity_error_is_a_redacted_conflict(monkeypatch) -> None:
    monkeypatch.setattr(
        voucher_attachments, "_load_batch", lambda *_args, **_kwargs: _persisted_batch()
    )
    monkeypatch.setattr(voucher_attachments, "_load_item", lambda *_args, **_kwargs: None)
    repository = _fake_repository(
        _FakeSession(error=IntegrityError("insert", {}, RuntimeError("private")))
    )
    with pytest.raises(VoucherAttachmentPersistenceError) as error:
        repository.register_item(_item())
    assert error.value.status_code == 409
    assert "private" not in error.value.detail


def test_create_sqlalchemy_base_error_is_unavailable() -> None:
    repository = _fake_repository(
        _FakeSession(error=SQLAlchemyError("private database detail"))
    )
    with pytest.raises(VoucherAttachmentPersistenceError) as error:
        repository.create_batch(_batch())
    assert error.value.status_code == 503
    assert "private" not in error.value.detail


def test_batch_clock_and_read_identity_validation(sqlite_repository) -> None:
    _engine, factory, _repository = sqlite_repository
    invalid_clock = SqlAlchemyVoucherAttachmentRepository(
        factory, clock=lambda: datetime(2026, 10, 23, 11, 0)
    )
    with pytest.raises(VoucherAttachmentPersistenceError) as timestamp:
        invalid_clock.create_batch(_batch())
    assert timestamp.value.status_code == 422

    repository = SqlAlchemyVoucherAttachmentRepository(factory, clock=lambda: NOW)
    with pytest.raises(VoucherAttachmentPersistenceError):
        repository.get_batch(tenant_id="bad tenant", attachment_batch_id=BATCH_ID)
    with pytest.raises(VoucherAttachmentPersistenceError):
        repository.get_batch(tenant_id=TENANT, attachment_batch_id="bad")


def test_uuid_fixture_is_unique_for_parallel_smoke() -> None:
    assert uuid4() != uuid4()
