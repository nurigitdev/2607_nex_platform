from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from nex_ag.audit_retention import (
    AG_AUDIT_RETENTION_POLICY_ID,
    AG_AUDIT_RETENTION_POLICY_SCHEMA_VERSION,
    AG_AUDIT_RETENTION_RECEIPT_TABLE,
    AgRetentionCandidateError,
    InMemoryAgRetentionCandidateStore,
    SqlAlchemyAgRetentionCandidateStore,
    AgAuditRetentionPolicyError,
    build_ag_audit_retention_policy,
    build_ag_retention_candidate_page,
)


def test_default_policy_is_dry_run_and_mock_safe() -> None:
    policy = build_ag_audit_retention_policy({})

    assert policy["policy_schema_version"] == (
        AG_AUDIT_RETENTION_POLICY_SCHEMA_VERSION
    )
    assert policy["policy_id"] == AG_AUDIT_RETENTION_POLICY_ID
    assert policy["sources"] == [
        {
            "source_kind": "operational_event",
            "table_name": "service_operational_events",
            "identity_field": "event_id",
            "timestamp_field": "created_at",
            "retention_days": 365,
        },
        {
            "source_kind": "evidence_export",
            "table_name": "ag_ev_exports",
            "identity_field": "export_id",
            "timestamp_field": "updated_at",
            "retention_days": 365,
        },
    ]
    assert policy["archive"] == {
        "provider_mode": "mock",
        "recoverable_payload_required": True,
        "sealed_receipt_required": True,
        "receipt_table": AG_AUDIT_RETENTION_RECEIPT_TABLE,
        "digest_algorithm": "sha256",
        "grace_days": 30,
        "raw_payload_in_receipt": False,
    }
    assert policy["purge"] == {
        "dry_run_default": True,
        "execute_enabled": False,
        "explicit_confirmation_required": True,
        "same_transaction_recheck_required": True,
        "batch_size": 100,
        "hard_max_batch_size": 500,
    }


def test_policy_accepts_external_execute_overrides() -> None:
    policy = build_ag_audit_retention_policy(
        {
            "NEX_AG_AUDIT_EVENT_RETENTION_DAYS": "730",
            "NEX_AG_EVIDENCE_EXPORT_RETENTION_DAYS": "180",
            "NEX_AG_ARCHIVE_GRACE_DAYS": "15",
            "NEX_AG_RETENTION_BATCH_SIZE": "250",
            "NEX_AG_ARCHIVE_PROVIDER_MODE": " EXTERNAL ",
            "NEX_AG_RETENTION_EXECUTE_ENABLED": "yes",
        }
    )

    assert [item["retention_days"] for item in policy["sources"]] == [730, 180]
    assert policy["archive"]["provider_mode"] == "external"
    assert policy["archive"]["grace_days"] == 15
    assert policy["purge"]["execute_enabled"] is True
    assert policy["purge"]["batch_size"] == 250


@pytest.mark.parametrize(
    "environ",
    [
        {"NEX_AG_AUDIT_EVENT_RETENTION_DAYS": "29"},
        {"NEX_AG_AUDIT_EVENT_RETENTION_DAYS": "3651"},
        {"NEX_AG_EVIDENCE_EXPORT_RETENTION_DAYS": "0"},
        {"NEX_AG_ARCHIVE_GRACE_DAYS": "366"},
        {"NEX_AG_RETENTION_BATCH_SIZE": "501"},
    ],
)
def test_policy_rejects_out_of_range_values(environ: dict[str, str]) -> None:
    with pytest.raises(AgAuditRetentionPolicyError) as exc_info:
        build_ag_audit_retention_policy(environ)

    assert exc_info.value.error_code == "ag.retention.policy_value_out_of_range"
    assert str(exc_info.value) == exc_info.value.detail


@pytest.mark.parametrize("raw", ["invalid", "1.5"])
def test_policy_rejects_non_integer_value(raw: str) -> None:
    with pytest.raises(AgAuditRetentionPolicyError) as exc_info:
        build_ag_audit_retention_policy(
            {"NEX_AG_AUDIT_EVENT_RETENTION_DAYS": raw}
        )

    assert exc_info.value.error_code == "ag.retention.policy_value_invalid"


def test_empty_values_use_defaults_and_false_alias_is_supported() -> None:
    policy = build_ag_audit_retention_policy(
        {
            "NEX_AG_AUDIT_EVENT_RETENTION_DAYS": " ",
            "NEX_AG_ARCHIVE_PROVIDER_MODE": "",
            "NEX_AG_RETENTION_EXECUTE_ENABLED": "off",
        }
    )

    assert policy["sources"][0]["retention_days"] == 365
    assert policy["archive"]["provider_mode"] == "mock"
    assert policy["purge"]["execute_enabled"] is False


def test_policy_rejects_archive_grace_longer_than_retention() -> None:
    with pytest.raises(AgAuditRetentionPolicyError) as exc_info:
        build_ag_audit_retention_policy(
            {
                "NEX_AG_AUDIT_EVENT_RETENTION_DAYS": "30",
                "NEX_AG_ARCHIVE_GRACE_DAYS": "31",
            }
        )

    assert exc_info.value.error_code == (
        "ag.retention.archive_grace_exceeds_retention"
    )


def test_policy_rejects_execute_with_mock_archive_provider() -> None:
    with pytest.raises(AgAuditRetentionPolicyError) as exc_info:
        build_ag_audit_retention_policy(
            {"NEX_AG_RETENTION_EXECUTE_ENABLED": "true"}
        )

    assert exc_info.value.error_code == (
        "ag.retention.execute_requires_external_archive"
    )


def test_policy_rejects_invalid_provider_mode() -> None:
    with pytest.raises(AgAuditRetentionPolicyError) as exc_info:
        build_ag_audit_retention_policy(
            {"NEX_AG_ARCHIVE_PROVIDER_MODE": "filesystem"}
        )

    assert exc_info.value.error_code == (
        "ag.retention.archive_provider_mode_invalid"
    )
    assert "external, mock" in exc_info.value.detail


@pytest.mark.parametrize("raw", ["sometimes", "2"])
def test_policy_rejects_invalid_boolean(raw: str) -> None:
    with pytest.raises(AgAuditRetentionPolicyError) as exc_info:
        build_ag_audit_retention_policy(
            {"NEX_AG_RETENTION_EXECUTE_ENABLED": raw}
        )

    assert exc_info.value.error_code == "ag.retention.policy_boolean_invalid"


@pytest.mark.parametrize("raw", ["1", "true", "on"])
def test_boolean_true_aliases_require_external_mode(raw: str) -> None:
    policy = build_ag_audit_retention_policy(
        {
            "NEX_AG_ARCHIVE_PROVIDER_MODE": "external",
            "NEX_AG_RETENTION_EXECUTE_ENABLED": raw,
        }
    )

    assert policy["purge"]["execute_enabled"] is True


@pytest.mark.parametrize("raw", ["0", "false", "no"])
def test_boolean_false_aliases_are_supported(raw: str) -> None:
    policy = build_ag_audit_retention_policy(
        {"NEX_AG_RETENTION_EXECUTE_ENABLED": raw}
    )

    assert policy["purge"]["execute_enabled"] is False


def _event(event_id: str, created_at: object, message: str = "private") -> dict:
    return {
        "event_id": event_id,
        "created_at": created_at,
        "message": message,
        "details": {"credential": "private"},
        "tags": ["audit", "retention"],
    }


def _export(export_id: str, updated_at: object) -> dict:
    return {
        "export_id": export_id,
        "updated_at": updated_at,
        "evidence_manifest": {"raw": "private"},
    }


def test_candidate_page_selects_old_records_in_stable_order_without_raw_data() -> None:
    page = build_ag_retention_candidate_page(
        event_records=[
            _event("event-new", "2025-12-31T00:00:00Z"),
            _event("event-old", "2024-01-01T00:00:00Z"),
        ],
        export_records=[_export("export-old", "2024-01-02T00:00:00+00:00")],
        policy=build_ag_audit_retention_policy({}),
        as_of="2026-01-01T00:00:00Z",
        limit=10,
    )

    assert page["candidate_count"] == 2
    assert page["eligible_count"] == 2
    assert page["has_more"] is False
    assert [item["source_id"] for item in page["items"]] == [
        "event-old",
        "export-old",
    ]
    assert all(item["archive_status"] == "UNARCHIVED" for item in page["items"])
    assert all(item["purge_eligible"] is False for item in page["items"])
    assert "private" not in str(page)
    assert len(page["items"][0]["candidate_id"]) == 64
    assert len(page["items"][0]["content_sha256"]) == 64


def test_candidate_page_reports_invalid_records_and_bounds_limit() -> None:
    page = build_ag_retention_candidate_page(
        event_records=[
            _event("", "2024-01-01T00:00:00Z"),
            _event("bad-time", "invalid"),
            _event("old-a", "2024-01-01T00:00:00Z"),
            _event("old-b", "2024-01-02T00:00:00Z"),
        ],
        export_records=[],
        policy=build_ag_audit_retention_policy({}),
        as_of="2026-01-01T00:00:00Z",
        limit=1,
    )

    assert page["invalid_record_count"] == 2
    assert page["candidate_count"] == 1
    assert page["eligible_count"] == 2
    assert page["has_more"] is True


def test_in_memory_candidate_store_uses_policy_default_limit() -> None:
    policy = build_ag_audit_retention_policy(
        {"NEX_AG_RETENTION_BATCH_SIZE": "1"}
    )
    store = InMemoryAgRetentionCandidateStore(
        event_records=[
            _event("event-1", datetime(2024, 1, 1, tzinfo=timezone.utc)),
            _event("event-2", datetime(2024, 1, 2, tzinfo=timezone.utc)),
        ]
    )

    page = store.list_candidates(policy=policy, as_of="2026-01-01T00:00:00Z")

    assert page["limit"] == 1
    assert page["candidate_count"] == 1
    assert page["has_more"] is True


@pytest.mark.parametrize("as_of", ["", "invalid", "2026-01-01T00:00:00"])
def test_candidate_page_rejects_invalid_as_of(as_of: str) -> None:
    with pytest.raises(AgRetentionCandidateError):
        build_ag_retention_candidate_page(
            event_records=[],
            export_records=[],
            policy=build_ag_audit_retention_policy({}),
            as_of=as_of,
        )


@pytest.mark.parametrize("limit", [True, 0, -1, "1", 501])
def test_candidate_page_rejects_invalid_limit(limit: object) -> None:
    with pytest.raises(AgRetentionCandidateError):
        build_ag_retention_candidate_page(
            event_records=[],
            export_records=[],
            policy=build_ag_audit_retention_policy({}),
            as_of="2026-01-01T00:00:00Z",
            limit=limit,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "policy",
    [
        {},
        {"sources": "bad", "purge": {"batch_size": 1, "hard_max_batch_size": 1}},
        {
            "sources": [{"source_kind": "operational_event"}],
            "purge": {"batch_size": 1, "hard_max_batch_size": 1},
        },
        {
            "sources": [],
            "purge": {"batch_size": True, "hard_max_batch_size": 1},
        },
    ],
)
def test_candidate_page_rejects_invalid_policy(policy: dict) -> None:
    with pytest.raises(AgRetentionCandidateError):
        build_ag_retention_candidate_page(
            event_records=[],
            export_records=[],
            policy=policy,
            as_of="2026-01-01T00:00:00Z",
        )


def _create_candidate_tables(engine) -> None:
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


def test_sqlalchemy_candidate_store_reads_sqlite_sources() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    _create_candidate_tables(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO service_operational_events
                    (event_id, service_id, event_type, severity, message,
                     details, created_at)
                VALUES ('event-old', 'nex-ag', 'test', 'INFO', 'private',
                        '{}', '2024-01-01T00:00:00Z')
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO ag_ev_exports
                    (export_id, export_schema_version, target_service,
                     target_kind, target_id, request_id, operator_type,
                     operator_id, operator_ref, export_status, export_format,
                     redaction_profile, evidence_manifest, evidence_hash,
                     evidence_item_count, metadata, created_at, updated_at)
                VALUES ('export-old', 'ag_redacted_evidence_export.v1',
                        'nex-ag', 'audit', 'target', 'request', 'service',
                        'nex-ag', '{}', 'READY', 'json',
                        'ag_redacted_manifest_v1', '{}',
                        'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                        0, '{}', '2024-01-02T00:00:00Z',
                        '2024-01-02T00:00:00Z')
                """
            )
        )
    store = SqlAlchemyAgRetentionCandidateStore(
        sessionmaker(bind=engine, expire_on_commit=False)
    )

    page = store.list_candidates(
        policy=build_ag_audit_retention_policy({}),
        as_of="2026-01-01T00:00:00Z",
        limit=10,
    )

    assert [item["source_id"] for item in page["items"]] == [
        "event-old",
        "export-old",
    ]
    engine.dispose()


def test_sqlalchemy_candidate_store_normalizes_database_failure() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    store = SqlAlchemyAgRetentionCandidateStore(sessionmaker(bind=engine))

    with pytest.raises(AgRetentionCandidateError) as exc_info:
        store.list_candidates(
            policy=build_ag_audit_retention_policy({}),
            as_of="2026-01-01T00:00:00Z",
        )

    assert exc_info.value.error_code == (
        "ag.retention.candidate_store_unavailable"
    )
    assert exc_info.value.status_code == 503
    assert str(exc_info.value) == exc_info.value.detail
    assert "service_operational_events" not in exc_info.value.detail
    engine.dispose()
