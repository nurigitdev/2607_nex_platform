from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from types import SimpleNamespace

from nex_ag.audit_retention_archive import (
    AG_ARCHIVE_RECEIPT_SCHEMA_VERSION,
    AgArchiveReceiptError,
    InMemoryAgArchiveReceiptStore,
    MockAgArchiveAdapter,
    SqlAlchemyAgArchiveReceiptStore,
    build_ag_archive_receipt,
)


def _hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _candidate() -> dict:
    payload = {"event_id": "event-1", "created_at": "2024-01-01T00:00:00Z"}
    import nex_ag.audit_retention_archive as archive

    return {
        "source_kind": "operational_event",
        "source_id": "event-1",
        "content_sha256": archive._sha256_json(payload),
        "payload": payload,
    }


def _external_result(content_hash: str) -> dict:
    return {
        "provider_mode": "external",
        "recoverable": True,
        "object_ref": "s3://private-bucket/private-object",
        "content_sha256": content_hash,
        "receipt_sha256": _hash("provider-receipt"),
    }


def _sealed_receipt() -> dict:
    candidate = _candidate()
    return build_ag_archive_receipt(
        candidate=candidate,
        provider_result=_external_result(candidate["content_sha256"]),
        archived_at="2026-01-01T00:00:00Z",
        grace_days=30,
    )


def test_external_receipt_is_sealed_redacted_and_deterministic() -> None:
    first = _sealed_receipt()
    second = _sealed_receipt()

    assert first == second
    assert first["receipt_schema_version"] == AG_ARCHIVE_RECEIPT_SCHEMA_VERSION
    assert first["archive_status"] == "SEALED"
    assert first["archive_provider_mode"] == "external"
    assert first["purge_after"] == "2026-01-31T00:00:00Z"
    assert first["metadata"]["recoverable"] is True
    assert "private-bucket" not in str(first)
    assert len(first["archive_object_ref_hash"]) == 64


def test_mock_adapter_builds_non_purgeable_mocked_receipt() -> None:
    candidate = _candidate()
    provider_result = MockAgArchiveAdapter().archive(
        candidate=candidate,
        payload=candidate["payload"],
    )

    receipt = build_ag_archive_receipt(
        candidate=candidate,
        provider_result=provider_result,
        archived_at="2026-01-01T00:00:00+00:00",
        grace_days=30,
    )

    assert receipt["archive_status"] == "MOCKED"
    assert receipt["purge_after"] is None
    assert receipt["metadata"]["recoverable"] is False
    assert "mock://" not in str(receipt)


def test_mock_adapter_rejects_payload_hash_mismatch() -> None:
    with pytest.raises(AgArchiveReceiptError) as exc_info:
        MockAgArchiveAdapter().archive(
            candidate=_candidate(),
            payload={"different": True},
        )

    assert exc_info.value.error_code == (
        "ag.retention.archive_payload_hash_mismatch"
    )
    assert str(exc_info.value) == exc_info.value.detail


@pytest.mark.parametrize(
    ("candidate_change", "provider_change", "grace_days", "error_code"),
    [
        ({"source_kind": "invalid"}, {}, 30, "ag.retention.archive_source_kind_invalid"),
        ({"source_id": ""}, {}, 30, "ag.retention.archive_field_required"),
        ({"content_sha256": "bad"}, {}, 30, "ag.retention.archive_hash_invalid"),
        ({}, {"provider_mode": "invalid"}, 30, "ag.retention.archive_provider_mode_invalid"),
        ({}, {"content_sha256": "b" * 64}, 30, "ag.retention.archive_receipt_hash_mismatch"),
        ({}, {"object_ref": ""}, 30, "ag.retention.archive_field_required"),
        ({}, {"receipt_sha256": "bad"}, 30, "ag.retention.archive_hash_invalid"),
        ({}, {"recoverable": "yes"}, 30, "ag.retention.archive_recoverability_invalid"),
        ({}, {"recoverable": False}, 30, "ag.retention.external_archive_not_recoverable"),
        ({}, {}, 0, "ag.retention.archive_grace_invalid"),
    ],
)
def test_receipt_builder_rejects_invalid_inputs(
    candidate_change: dict,
    provider_change: dict,
    grace_days: int,
    error_code: str,
) -> None:
    candidate = _candidate()
    candidate.update(candidate_change)
    provider = _external_result(_candidate()["content_sha256"])
    provider.update(provider_change)

    with pytest.raises(AgArchiveReceiptError) as exc_info:
        build_ag_archive_receipt(
            candidate=candidate,
            provider_result=provider,
            archived_at="2026-01-01T00:00:00Z",
            grace_days=grace_days,
        )

    assert exc_info.value.error_code == error_code


def test_receipt_builder_rejects_mock_recoverable_and_bad_timestamp() -> None:
    candidate = _candidate()
    provider = {
        **_external_result(candidate["content_sha256"]),
        "provider_mode": "mock",
        "recoverable": True,
    }
    with pytest.raises(AgArchiveReceiptError) as exc_info:
        build_ag_archive_receipt(
            candidate=candidate,
            provider_result=provider,
            archived_at="2026-01-01T00:00:00Z",
            grace_days=30,
        )
    assert exc_info.value.error_code == (
        "ag.retention.mock_archive_recoverability_invalid"
    )

    provider["recoverable"] = False
    with pytest.raises(AgArchiveReceiptError) as exc_info:
        build_ag_archive_receipt(
            candidate=candidate,
            provider_result=provider,
            archived_at="2026-01-01T00:00:00",
            grace_days=30,
        )
    assert exc_info.value.error_code == (
        "ag.retention.archive_timestamp_timezone_required"
    )


def test_in_memory_store_is_idempotent_and_filters() -> None:
    store = InMemoryAgArchiveReceiptStore()
    receipt = _sealed_receipt()

    assert store.save(receipt) == receipt
    assert store.save(receipt) == receipt
    assert store.get(receipt["archive_id"]) == receipt
    assert store.get("missing") is None
    assert store.get_by_source(
        source_kind="operational_event", source_id="event-1"
    ) == receipt
    assert store.get_by_source(
        source_kind="operational_event", source_id="missing"
    ) is None
    assert store.list_receipts(archive_status=" sealed ", limit=1) == [receipt]
    assert store.list_receipts(archive_status="", limit=100) == [receipt]
    assert store.list_receipts(archive_status="FAILED") == []


def test_in_memory_store_rejects_immutable_conflicts() -> None:
    store = InMemoryAgArchiveReceiptStore()
    receipt = _sealed_receipt()
    store.save(receipt)
    changed = deepcopy(receipt)
    changed["source_content_sha256"] = "b" * 64

    with pytest.raises(AgArchiveReceiptError) as exc_info:
        store.save(changed)
    assert exc_info.value.error_code == "ag.retention.archive_receipt_conflict"
    assert exc_info.value.status_code == 409

    changed = deepcopy(receipt)
    changed["archive_id"] = "other-id"
    with pytest.raises(AgArchiveReceiptError):
        store.save(changed)


def test_in_memory_store_accepts_distinct_source_receipts() -> None:
    store = InMemoryAgArchiveReceiptStore()
    first = _sealed_receipt()
    second = deepcopy(first)
    second["archive_id"] = "archive-export"
    second["source_kind"] = "evidence_export"
    second["source_id"] = "export-1"

    store.save(first)
    store.save(second)

    assert len(store.list_receipts()) == 2


@pytest.mark.parametrize("status", ["UNKNOWN", "invalid"])
def test_store_rejects_invalid_status_filter(status: str) -> None:
    with pytest.raises(AgArchiveReceiptError):
        InMemoryAgArchiveReceiptStore().list_receipts(archive_status=status)


@pytest.mark.parametrize("limit", [True, 0, 501])
def test_store_rejects_invalid_limit(limit: object) -> None:
    with pytest.raises(AgArchiveReceiptError):
        InMemoryAgArchiveReceiptStore().list_receipts(limit=limit)  # type: ignore[arg-type]


def _create_receipt_table(engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE ag_ret_archives (
                    archive_id TEXT PRIMARY KEY,
                    receipt_schema_version TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    source_content_sha256 TEXT NOT NULL,
                    archive_provider_mode TEXT NOT NULL,
                    archive_object_ref_hash TEXT NOT NULL,
                    archive_receipt_sha256 TEXT NOT NULL,
                    archive_status TEXT NOT NULL,
                    archived_at TEXT NOT NULL,
                    purge_after TEXT,
                    purged_at TEXT,
                    failure_code TEXT,
                    metadata JSON NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (source_kind, source_id)
                )
                """
            )
        )


def test_sqlalchemy_store_round_trip_and_idempotency() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    _create_receipt_table(engine)
    store = SqlAlchemyAgArchiveReceiptStore(
        sessionmaker(bind=engine, expire_on_commit=False)
    )
    receipt = _sealed_receipt()

    assert store.save(receipt) == receipt
    assert store.save(receipt) == receipt
    assert store.get(receipt["archive_id"]) == receipt
    assert store.get("missing") is None
    assert store.get_by_source(
        source_kind="operational_event", source_id="event-1"
    ) == receipt
    assert store.list_receipts(archive_status="SEALED") == [receipt]
    assert store.list_receipts(archive_status="FAILED") == []
    engine.dispose()


def test_sqlalchemy_store_rejects_source_conflict() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    _create_receipt_table(engine)
    store = SqlAlchemyAgArchiveReceiptStore(sessionmaker(bind=engine))
    receipt = _sealed_receipt()
    store.save(receipt)
    changed = deepcopy(receipt)
    changed["archive_id"] = "different"
    changed["archive_receipt_sha256"] = "b" * 64

    with pytest.raises(AgArchiveReceiptError) as exc_info:
        store.save(changed)

    assert exc_info.value.error_code == "ag.retention.archive_receipt_conflict"
    engine.dispose()


def test_sqlalchemy_store_normalizes_database_failure() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    store = SqlAlchemyAgArchiveReceiptStore(sessionmaker(bind=engine))

    with pytest.raises(AgArchiveReceiptError) as exc_info:
        store.save(_sealed_receipt())
    assert exc_info.value.error_code == (
        "ag.retention.archive_receipt_store_unavailable"
    )
    assert exc_info.value.status_code == 503

    with pytest.raises(AgArchiveReceiptError):
        store.get("missing")
    with pytest.raises(AgArchiveReceiptError):
        store.list_receipts()
    engine.dispose()


def test_sqlalchemy_store_rejects_missing_insert_and_lookup_result() -> None:
    class EmptyResult:
        def mappings(self):
            return self

        def first(self):
            return None

    class EmptySession:
        bind = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, *_args, **_kwargs):
            return EmptyResult()

        def commit(self):
            raise AssertionError("commit must not be reached")

    store = SqlAlchemyAgArchiveReceiptStore(lambda: EmptySession())  # type: ignore[arg-type]

    with pytest.raises(AgArchiveReceiptError) as exc_info:
        store.save(_sealed_receipt())

    assert exc_info.value.error_code == (
        "ag.retention.archive_receipt_store_unavailable"
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("receipt_schema_version", "wrong"),
        ("archive_id", ""),
        ("source_kind", "wrong"),
        ("archive_provider_mode", "wrong"),
        ("archive_status", "wrong"),
        ("metadata", "wrong"),
        ("created_at", "invalid"),
    ],
)
def test_store_rejects_invalid_receipt_records(field: str, value: object) -> None:
    receipt = _sealed_receipt()
    receipt[field] = value

    with pytest.raises(AgArchiveReceiptError):
        InMemoryAgArchiveReceiptStore().save(receipt)


def test_json_hash_normalizes_nested_sequences_and_datetime() -> None:
    import nex_ag.audit_retention_archive as archive

    value = {
        "items": [1, (2, 3)],
        "at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    }

    assert archive._sha256_json(value) == archive._sha256_json(value)
    assert len(archive._sha256_json(value)) == 64


def test_builder_accepts_aware_datetime_and_rejects_missing_timestamp() -> None:
    candidate = _candidate()
    provider = _external_result(candidate["content_sha256"])

    receipt = build_ag_archive_receipt(
        candidate=candidate,
        provider_result=provider,
        archived_at=datetime(2026, 1, 1, tzinfo=timezone.utc),  # type: ignore[arg-type]
        grace_days=1,
    )
    assert receipt["archived_at"] == "2026-01-01T00:00:00Z"

    with pytest.raises(AgArchiveReceiptError) as exc_info:
        build_ag_archive_receipt(
            candidate=candidate,
            provider_result=provider,
            archived_at=None,  # type: ignore[arg-type]
            grace_days=1,
        )
    assert exc_info.value.error_code == (
        "ag.retention.archive_timestamp_invalid"
    )


def test_receipt_row_accepts_driver_decoded_metadata() -> None:
    import nex_ag.audit_retention_archive as archive

    receipt = _sealed_receipt()
    row = deepcopy(receipt)
    row["archived_at"] = datetime(2026, 1, 1, tzinfo=timezone.utc)
    row["purge_after"] = datetime(2026, 1, 31, tzinfo=timezone.utc)
    row["created_at"] = datetime(2026, 1, 1, tzinfo=timezone.utc)
    row["updated_at"] = datetime(2026, 1, 1, tzinfo=timezone.utc)

    assert archive._receipt_from_row(receipt) == receipt
    assert archive._receipt_from_row(row) == receipt
