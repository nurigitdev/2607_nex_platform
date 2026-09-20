from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from nex_ag.audit_retention import _sha256_json, build_ag_audit_retention_policy
from nex_ag.audit_retention_archive import InMemoryAgArchiveReceiptStore
from nex_ag.audit_retention_purge import (
    AgRetentionPurgeError,
    InMemoryAgRetentionPurgeStore,
    SqlAlchemyAgRetentionPurgeStore,
    _source_delete_sql,
    _source_select_sql,
    execute_ag_retention_purge,
)


def _source() -> dict:
    return {
        "event_id": "event-1",
        "service_id": "nex-ag",
        "event_type": "test",
        "severity": "INFO",
        "trace_id": None,
        "request_id": None,
        "subject_type": None,
        "subject_id": None,
        "message": "private",
        "details": {},
        "created_at": "2024-01-01T00:00:00Z",
    }


def _receipt(*, status: str = "SEALED", purge_after: str = "2026-01-01T00:00:00Z") -> dict:
    return {
        "receipt_schema_version": "ag_archive_receipt.v1",
        "archive_id": "archive-1",
        "source_kind": "operational_event",
        "source_id": "event-1",
        "source_content_sha256": _sha256_json(_source()),
        "archive_provider_mode": "external",
        "archive_object_ref_hash": "a" * 64,
        "archive_receipt_sha256": "b" * 64,
        "archive_status": status,
        "archived_at": "2025-12-01T00:00:00Z",
        "purge_after": purge_after,
        "purged_at": None,
        "failure_code": None,
        "metadata": {"recoverable": True},
        "created_at": "2025-12-01T00:00:00Z",
        "updated_at": "2025-12-01T00:00:00Z",
    }


def _store(*, receipt: dict | None = None, source: dict | None = None):
    receipt_store = InMemoryAgArchiveReceiptStore()
    if receipt is not None:
        receipt_store.save(receipt)
    records = (
        {("operational_event", "event-1"): source}
        if source is not None
        else {}
    )
    return InMemoryAgRetentionPurgeStore(
        receipt_store=receipt_store,
        source_records=records,
    )


def _execute_policy() -> dict:
    return build_ag_audit_retention_policy(
        {
            "NEX_AG_ARCHIVE_PROVIDER_MODE": "external",
            "NEX_AG_RETENTION_EXECUTE_ENABLED": "true",
        }
    )


def test_dry_run_reports_eligible_without_mutation() -> None:
    store = _store(receipt=_receipt(), source=_source())

    result = execute_ag_retention_purge(
        store=store,
        policy=_execute_policy(),
        source_kind="operational_event",
        source_id="event-1",
        as_of="2026-02-01T00:00:00Z",
    )

    assert result["status"] == "ELIGIBLE"
    assert result["mode"] == "DRY_RUN"
    assert result["deleted_count"] == 0
    assert ("operational_event", "event-1") in store.source_records
    assert "private" not in str(result)


def test_execute_requires_policy_and_confirmation() -> None:
    store = _store(receipt=_receipt(), source=_source())
    disabled = execute_ag_retention_purge(
        store=store,
        policy=build_ag_audit_retention_policy({}),
        source_kind="operational_event",
        source_id="event-1",
        as_of="2026-02-01T00:00:00Z",
        mode="EXECUTE",
        confirmation="PURGE",
    )
    unconfirmed = execute_ag_retention_purge(
        store=store,
        policy=_execute_policy(),
        source_kind="operational_event",
        source_id="event-1",
        as_of="2026-02-01T00:00:00Z",
        mode="execute",
    )

    assert disabled["status"] == "BLOCKED"
    assert disabled["reason"] == "execute_disabled"
    assert unconfirmed["status"] == "BLOCKED"
    assert unconfirmed["reason"] == "confirmation_required"


def test_execute_purges_and_retry_is_idempotent_noop() -> None:
    store = _store(receipt=_receipt(), source=_source())
    kwargs = {
        "store": store,
        "policy": _execute_policy(),
        "source_kind": "operational_event",
        "source_id": "event-1",
        "as_of": "2026-02-01T00:00:00Z",
        "mode": "EXECUTE",
        "confirmation": "PURGE",
    }

    first = execute_ag_retention_purge(**kwargs)
    second = execute_ag_retention_purge(**kwargs)

    assert first["status"] == "PURGED"
    assert first["deleted_count"] == 1
    assert second["status"] == "NOOP"
    assert second["idempotent_noop"] is True
    assert second["deleted_count"] == 0


@pytest.mark.parametrize(
    ("receipt", "source", "reason"),
    [
        (None, _source(), "receipt_missing"),
        (_receipt(status="MOCKED", purge_after=None), _source(), "receipt_not_sealed"),
        (_receipt(purge_after="2026-03-01T00:00:00Z"), _source(), "archive_grace_active"),
        (_receipt(), None, "source_missing"),
        (_receipt(), {**_source(), "message": "changed"}, "source_hash_mismatch"),
    ],
)
def test_dry_run_reports_blocking_reason(
    receipt: dict | None,
    source: dict | None,
    reason: str,
) -> None:
    result = execute_ag_retention_purge(
        store=_store(receipt=receipt, source=source),
        policy=_execute_policy(),
        source_kind="operational_event",
        source_id="event-1",
        as_of="2026-02-01T00:00:00Z",
    )

    assert result["status"] == "BLOCKED"
    assert result["reason"] == reason


def test_assessment_covers_external_and_purged_inconsistency_guards() -> None:
    receipt = _receipt()
    receipt["archive_provider_mode"] = "mock"
    store = _store(receipt=receipt, source=_source())
    assert store.assess(
        source_kind="operational_event",
        source_id="event-1",
        as_of="2026-02-01T00:00:00Z",
    )["reason"] == "external_receipt_required"

    receipt = _receipt()
    receipt["purge_after"] = None
    store = _store(receipt=receipt, source=_source())
    assert store.assess(
        source_kind="operational_event",
        source_id="event-1",
        as_of="2026-02-01T00:00:00Z",
    )["reason"] == "purge_after_missing"

    receipt = _receipt(status="PURGED")
    receipt["purged_at"] = "2026-01-15T00:00:00Z"
    store = _store(receipt=receipt, source=_source())
    assert store.assess(
        source_kind="operational_event",
        source_id="event-1",
        as_of="2026-02-01T00:00:00Z",
    )["reason"] == "purged_source_present"

    blocked = _store(source=_source()).purge(
        source_kind="operational_event",
        source_id="event-1",
        as_of="2026-02-01T00:00:00Z",
    )
    assert blocked["reason"] == "receipt_missing"
    assert blocked["deleted_count"] == 0


@pytest.mark.parametrize(
    ("source_kind", "source_id", "as_of", "mode"),
    [
        ("invalid", "event-1", "2026-02-01T00:00:00Z", "DRY_RUN"),
        ("operational_event", "", "2026-02-01T00:00:00Z", "DRY_RUN"),
        ("operational_event", "event-1", "invalid", "DRY_RUN"),
        ("operational_event", "event-1", "2026-02-01T00:00:00", "DRY_RUN"),
        ("operational_event", "event-1", "2026-02-01T00:00:00Z", "invalid"),
    ],
)
def test_service_rejects_invalid_inputs(
    source_kind: str,
    source_id: str,
    as_of: str,
    mode: str,
) -> None:
    with pytest.raises(AgRetentionPurgeError):
        execute_ag_retention_purge(
            store=_store(),
            policy=_execute_policy(),
            source_kind=source_kind,
            source_id=source_id,
            as_of=as_of,
            mode=mode,
        )


def test_service_rejects_invalid_policy() -> None:
    with pytest.raises(AgRetentionPurgeError) as exc_info:
        execute_ag_retention_purge(
            store=_store(),
            policy={},
            source_kind="operational_event",
            source_id="event-1",
            as_of="2026-02-01T00:00:00Z",
        )
    assert exc_info.value.error_code == "ag.retention.purge_policy_invalid"
    assert str(exc_info.value) == exc_info.value.detail


def _create_tables(engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE service_operational_events (
                    event_id TEXT PRIMARY KEY, service_id TEXT, event_type TEXT,
                    severity TEXT, trace_id TEXT, request_id TEXT,
                    subject_type TEXT, subject_id TEXT, message TEXT,
                    details JSON, created_at TEXT
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE ag_ev_exports (
                    export_id TEXT PRIMARY KEY, export_schema_version TEXT,
                    target_service TEXT, target_kind TEXT, target_id TEXT,
                    trace_id TEXT, request_id TEXT, operator_type TEXT,
                    operator_id TEXT, tenant_id TEXT, operator_ref JSON,
                    export_status TEXT, export_format TEXT,
                    redaction_profile TEXT, evidence_manifest JSON,
                    evidence_hash TEXT, evidence_item_count INTEGER,
                    metadata JSON, created_at TEXT, updated_at TEXT
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE ag_ret_archives (
                    archive_id TEXT PRIMARY KEY,
                    receipt_schema_version TEXT, source_kind TEXT, source_id TEXT,
                    source_content_sha256 TEXT, archive_provider_mode TEXT,
                    archive_object_ref_hash TEXT, archive_receipt_sha256 TEXT,
                    archive_status TEXT, archived_at TEXT, purge_after TEXT,
                    purged_at TEXT, failure_code TEXT, metadata JSON,
                    created_at TEXT, updated_at TEXT,
                    UNIQUE (source_kind, source_id)
                )
                """
            )
        )


def _seed_sqlite(engine) -> None:
    source = _source()
    receipt = _receipt()
    receipt["source_content_sha256"] = _sha256_json(
        {**source, "details": json.dumps(source["details"])}
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO service_operational_events
                    (event_id, service_id, event_type, severity, trace_id,
                     request_id, subject_type, subject_id, message, details,
                     created_at)
                VALUES (:event_id, :service_id, :event_type, :severity,
                        :trace_id, :request_id, :subject_type, :subject_id,
                        :message, :details, :created_at)
                """
            ),
            {**source, "details": json.dumps(source["details"])},
        )
        connection.execute(
            text(
                """
                INSERT INTO ag_ret_archives
                    (archive_id, receipt_schema_version, source_kind, source_id,
                     source_content_sha256, archive_provider_mode,
                     archive_object_ref_hash, archive_receipt_sha256,
                     archive_status, archived_at, purge_after, purged_at,
                     failure_code, metadata, created_at, updated_at)
                VALUES (:archive_id, :receipt_schema_version, :source_kind,
                        :source_id, :source_content_sha256,
                        :archive_provider_mode, :archive_object_ref_hash,
                        :archive_receipt_sha256, :archive_status, :archived_at,
                        :purge_after, :purged_at, :failure_code, :metadata,
                        :created_at, :updated_at)
                """
            ),
            {**receipt, "metadata": json.dumps(receipt["metadata"])},
        )


def test_sqlalchemy_store_executes_atomic_sqlite_purge() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    _create_tables(engine)
    _seed_sqlite(engine)
    store = SqlAlchemyAgRetentionPurgeStore(sessionmaker(bind=engine))

    dry_run = store.assess(
        source_kind="operational_event",
        source_id="event-1",
        as_of="2026-02-01T00:00:00Z",
    )
    result = execute_ag_retention_purge(
        store=store,
        policy=_execute_policy(),
        source_kind="operational_event",
        source_id="event-1",
        as_of="2026-02-01T00:00:00Z",
        mode="EXECUTE",
        confirmation="PURGE",
    )
    retry = execute_ag_retention_purge(
        store=store,
        policy=_execute_policy(),
        source_kind="operational_event",
        source_id="event-1",
        as_of="2026-02-01T00:00:00Z",
        mode="EXECUTE",
        confirmation="PURGE",
    )

    assert dry_run["eligible"] is True
    assert result["status"] == "PURGED"
    assert retry["status"] == "NOOP"
    with engine.begin() as connection:
        assert connection.execute(
            text("SELECT count(*) FROM service_operational_events")
        ).scalar_one() == 0
        assert connection.execute(
            text("SELECT archive_status FROM ag_ret_archives")
        ).scalar_one() == "PURGED"
    engine.dispose()


def test_sqlalchemy_store_returns_blocker_without_mutation() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    _create_tables(engine)
    _seed_sqlite(engine)
    store = SqlAlchemyAgRetentionPurgeStore(sessionmaker(bind=engine))

    result = store.purge(
        source_kind="operational_event",
        source_id="event-1",
        as_of="2025-12-15T00:00:00Z",
    )

    assert result["reason"] == "archive_grace_active"
    assert result["deleted_count"] == 0
    engine.dispose()


def test_sqlalchemy_store_rolls_back_concurrent_delete_change() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    _create_tables(engine)
    _seed_sqlite(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TRIGGER ignore_event_delete
                BEFORE DELETE ON service_operational_events
                BEGIN
                    SELECT RAISE(IGNORE);
                END
                """
            )
        )
    store = SqlAlchemyAgRetentionPurgeStore(sessionmaker(bind=engine))

    with pytest.raises(AgRetentionPurgeError) as exc_info:
        store.purge(
            source_kind="operational_event",
            source_id="event-1",
            as_of="2026-02-01T00:00:00Z",
        )

    assert exc_info.value.error_code == "ag.retention.purge_concurrent_change"
    assert exc_info.value.status_code == 409
    with engine.begin() as connection:
        assert connection.execute(
            text("SELECT archive_status FROM ag_ret_archives")
        ).scalar_one() == "SEALED"
    engine.dispose()


def test_sqlalchemy_store_normalizes_database_failure() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    store = SqlAlchemyAgRetentionPurgeStore(sessionmaker(bind=engine))

    with pytest.raises(AgRetentionPurgeError) as exc_info:
        store.assess(
            source_kind="operational_event",
            source_id="event-1",
            as_of="2026-02-01T00:00:00Z",
        )
    assert exc_info.value.error_code == "ag.retention.purge_store_unavailable"
    assert exc_info.value.status_code == 503

    with pytest.raises(AgRetentionPurgeError):
        store.purge(
            source_kind="operational_event",
            source_id="event-1",
            as_of="2026-02-01T00:00:00Z",
        )
    engine.dispose()


def test_sql_helpers_cover_both_sources_and_invalid_kind() -> None:
    assert "service_operational_events" in _source_select_sql("operational_event")
    assert "ag_ev_exports" in _source_select_sql("evidence_export")
    assert "service_operational_events" in _source_delete_sql("operational_event")
    assert "ag_ev_exports" in _source_delete_sql("evidence_export")
    with pytest.raises(AgRetentionPurgeError):
        _source_select_sql("invalid")
    with pytest.raises(AgRetentionPurgeError):
        _source_delete_sql("invalid")


def test_timestamp_helper_accepts_datetime_and_rejects_none() -> None:
    import nex_ag.audit_retention_purge as purge

    assert purge._timestamp(
        purge._parse_timestamp(
            datetime(2026, 1, 1, tzinfo=timezone.utc), field="at"
        )
    ) == "2026-01-01T00:00:00Z"
    with pytest.raises(AgRetentionPurgeError):
        purge._parse_timestamp(None, field="at")
