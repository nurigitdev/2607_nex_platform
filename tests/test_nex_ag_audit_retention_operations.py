from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from nex_ag.audit_retention import (
    InMemoryAgRetentionCandidateStore,
    build_ag_audit_retention_policy,
)
from nex_ag.audit_retention_archive import InMemoryAgArchiveReceiptStore
from nex_ag.audit_retention_operations import (
    AG_AUDIT_RETENTION_OPERATIONS_PATH,
    AG_AUDIT_RETENTION_OPERATIONS_SCHEMA_VERSION,
    AG_AUDIT_RETENTION_PURGE_PATH,
    build_ag_audit_retention_operations_projection,
    build_ag_audit_retention_runtime_stores,
    register_ag_audit_retention_routes,
)
from nex_ag.audit_retention_purge import InMemoryAgRetentionPurgeStore
from nex_runtime import (
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
    issue_mock_user_token,
)


def _headers(*, roles: list[str] | None = None) -> dict[str, str]:
    issued = issue_mock_user_token(
        tenant_id="local-tenant",
        user_id="employee-0001",
        audience="nex-ag",
        roles=roles or ["admin"],
    )
    return {"Authorization": f"Bearer {issued.access_token}"}


def _event(event_id: str = "event-1") -> dict:
    return {
        "event_id": event_id,
        "created_at": "2024-01-01T00:00:00Z",
        "message": "private",
        "details": {"secret": "private"},
    }


def _receipt(*, status: str, source_id: str, purge_after: str | None) -> dict:
    return {
        "receipt_schema_version": "ag_archive_receipt.v1",
        "archive_id": f"archive-{source_id}",
        "source_kind": "operational_event",
        "source_id": source_id,
        "source_content_sha256": "a" * 64,
        "archive_provider_mode": "external" if status != "MOCKED" else "mock",
        "archive_object_ref_hash": "b" * 64,
        "archive_receipt_sha256": "c" * 64,
        "archive_status": status,
        "archived_at": "2025-01-01T00:00:00Z",
        "purge_after": purge_after,
        "purged_at": None,
        "failure_code": "provider_failed" if status == "FAILED" else None,
        "metadata": {"recoverable": status != "MOCKED"},
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
    }


def test_projection_reports_ready_empty_state() -> None:
    projection = build_ag_audit_retention_operations_projection(
        policy=build_ag_audit_retention_policy({}),
        candidate_store=InMemoryAgRetentionCandidateStore(),
        receipt_store=InMemoryAgArchiveReceiptStore(),
        as_of="2026-01-01T00:00:00Z",
    )

    assert projection["projection_schema_version"] == (
        AG_AUDIT_RETENTION_OPERATIONS_SCHEMA_VERSION
    )
    assert projection["projection_status"] == "READY"
    assert projection["attention_reasons"] == []
    assert projection["receipts"]["returned_count"] == 0
    assert projection["privacy"] == {
        "raw_payload_included": False,
        "object_reference_included": False,
        "credentials_included": False,
        "confirmation_included": False,
    }


def test_projection_reports_candidates_failures_and_purge_ready_receipts() -> None:
    receipt_store = InMemoryAgArchiveReceiptStore()
    receipt_store.save(
        _receipt(
            status="SEALED",
            source_id="event-sealed",
            purge_after="2025-12-01T00:00:00Z",
        )
    )
    receipt_store.save(
        _receipt(status="FAILED", source_id="event-failed", purge_after=None)
    )
    projection = build_ag_audit_retention_operations_projection(
        policy=build_ag_audit_retention_policy({}),
        candidate_store=InMemoryAgRetentionCandidateStore(
            event_records=[_event()]
        ),
        receipt_store=receipt_store,
        as_of="2026-01-01T00:00:00Z",
    )

    assert projection["projection_status"] == "ATTENTION"
    assert projection["attention_reasons"] == [
        "UNARCHIVED_RETENTION_CANDIDATES",
        "ARCHIVE_FAILURES",
        "PURGE_READY_RECEIPTS",
    ]
    assert projection["receipts"]["status_counts"]["SEALED"] == 1
    assert projection["receipts"]["status_counts"]["FAILED"] == 1
    assert projection["receipts"]["purge_ready_count"] == 1
    assert "archive_object_ref_hash" not in str(projection)
    assert "private" not in str(projection)


def test_projection_reports_invalid_candidate_source_rows() -> None:
    projection = build_ag_audit_retention_operations_projection(
        policy=build_ag_audit_retention_policy({}),
        candidate_store=InMemoryAgRetentionCandidateStore(
            event_records=[{"event_id": "", "created_at": "invalid"}]
        ),
        receipt_store=InMemoryAgArchiveReceiptStore(),
        as_of="2026-01-01T00:00:00Z",
    )

    assert projection["attention_reasons"] == ["INVALID_SOURCE_ROWS"]


def test_projection_ignores_unknown_status_and_missing_sealed_due_date() -> None:
    class ReceiptStore:
        def list_receipts(self, *, limit: int):
            assert limit == 5
            return [
                {
                    "archive_id": "unknown",
                    "archive_status": "UNKNOWN",
                    "purge_after": None,
                },
                {
                    "archive_id": "sealed",
                    "archive_status": "SEALED",
                    "purge_after": None,
                },
            ]

    projection = build_ag_audit_retention_operations_projection(
        policy=build_ag_audit_retention_policy({}),
        candidate_store=InMemoryAgRetentionCandidateStore(),
        receipt_store=ReceiptStore(),
        as_of="2026-01-01T00:00:00Z",
        limit=5,
    )

    assert projection["receipts"]["status_counts"]["SEALED"] == 1
    assert projection["receipts"]["purge_ready_count"] == 0


def _build_client(*, execute_enabled: bool = False):
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    source = _event()
    candidate_store = InMemoryAgRetentionCandidateStore(event_records=[source])
    receipt_store = InMemoryAgArchiveReceiptStore()
    receipt = _receipt(
        status="SEALED",
        source_id="event-1",
        purge_after="2025-01-01T00:00:00Z",
    )
    import nex_ag.audit_retention as retention

    receipt["source_content_sha256"] = retention._sha256_json(source)
    receipt_store.save(receipt)
    purge_store = InMemoryAgRetentionPurgeStore(
        receipt_store=receipt_store,
        source_records={("operational_event", "event-1"): source},
    )
    policy = build_ag_audit_retention_policy(
        {
            "NEX_AG_ARCHIVE_PROVIDER_MODE": (
                "external" if execute_enabled else "mock"
            ),
            "NEX_AG_RETENTION_EXECUTE_ENABLED": (
                "true" if execute_enabled else "false"
            ),
        }
    )
    register_ag_audit_retention_routes(
        app,
        candidate_store=candidate_store,
        receipt_store=receipt_store,
        purge_store=purge_store,
        policy=policy,
    )
    return TestClient(app), purge_store


def test_routes_require_authentication_and_admin_role() -> None:
    client, _store = _build_client()

    unauthorized = client.get(AG_AUDIT_RETENTION_OPERATIONS_PATH)
    unauthorized_post = client.post(
        AG_AUDIT_RETENTION_PURGE_PATH,
        json={},
    )
    forbidden = client.get(
        AG_AUDIT_RETENTION_OPERATIONS_PATH,
        headers=_headers(roles=["user"]),
    )

    assert unauthorized.status_code == 401
    assert unauthorized_post.status_code == 401
    assert forbidden.status_code == 403


def test_operations_and_dry_run_routes_return_safe_projection() -> None:
    client, _store = _build_client()

    projection = client.get(
        AG_AUDIT_RETENTION_OPERATIONS_PATH,
        headers=_headers(),
        params={"as_of": "2026-01-01T00:00:00Z", "limit": 10},
    )
    dry_run = client.post(
        AG_AUDIT_RETENTION_PURGE_PATH,
        headers=_headers(),
        json={
            "source_kind": "operational_event",
            "source_id": "event-1",
            "as_of": "2026-01-01T00:00:00Z",
        },
    )

    assert projection.status_code == 200
    assert projection.json()["projection_status"] == "ATTENTION"
    assert dry_run.status_code == 200
    assert dry_run.json()["status"] == "ELIGIBLE"
    assert dry_run.json()["confirmation_included"] is False


def test_service_token_and_default_timestamp_are_supported() -> None:
    client, _store = _build_client()
    issued = issue_mock_service_token(service_id="nex-oa", audience="nex-ag")

    response = client.get(
        AG_AUDIT_RETENTION_OPERATIONS_PATH,
        headers={"Authorization": f"Bearer {issued.access_token}"},
    )

    assert response.status_code == 200
    assert response.json()["checked_at"].endswith("Z")


def test_execute_route_purges_with_explicit_confirmation() -> None:
    client, store = _build_client(execute_enabled=True)

    response = client.post(
        AG_AUDIT_RETENTION_PURGE_PATH,
        headers=_headers(),
        json={
            "source_kind": "operational_event",
            "source_id": "event-1",
            "as_of": "2026-01-01T00:00:00Z",
            "mode": "EXECUTE",
            "confirmation": "PURGE",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "PURGED"
    assert store.source_records == {}


def test_routes_normalize_invalid_payload_and_projection_error() -> None:
    client, _store = _build_client()

    unsupported = client.post(
        AG_AUDIT_RETENTION_PURGE_PATH,
        headers=_headers(),
        json={"source_kind": "operational_event", "unsupported": True},
    )
    invalid_time = client.get(
        AG_AUDIT_RETENTION_OPERATIONS_PATH,
        headers=_headers(),
        params={"as_of": "invalid"},
    )

    assert unsupported.status_code == 400
    assert unsupported.json()["error_code"] == (
        "ag.retention.purge_fields_unsupported"
    )
    assert invalid_time.status_code == 400
    assert invalid_time.json()["error_code"] == (
        "ag.retention.timestamp_invalid"
    )


def test_runtime_store_builder_selects_memory_and_sqlalchemy_adapters() -> None:
    memory = build_ag_audit_retention_runtime_stores(SimpleNamespace())
    engine = create_engine("sqlite+pysqlite:///:memory:")
    sql = build_ag_audit_retention_runtime_stores(
        SimpleNamespace(api_session_factory=sessionmaker(bind=engine))
    )

    assert isinstance(memory["candidate_store"], InMemoryAgRetentionCandidateStore)
    assert memory["purge_store"].receipt_store is memory["receipt_store"]
    assert sql["candidate_store"].__class__.__name__ == (
        "SqlAlchemyAgRetentionCandidateStore"
    )
    assert sql["receipt_store"].__class__.__name__ == (
        "SqlAlchemyAgArchiveReceiptStore"
    )
    assert sql["purge_store"].__class__.__name__ == (
        "SqlAlchemyAgRetentionPurgeStore"
    )
    engine.dispose()


def test_projection_timestamp_accepts_datetime_and_rejects_naive() -> None:
    import nex_ag.audit_retention_operations as operations
    from datetime import datetime, timezone
    import pytest

    assert operations._parse_timestamp(
        datetime(2026, 1, 1, tzinfo=timezone.utc)
    ).tzinfo is not None
    with pytest.raises(Exception):
        operations._parse_timestamp(datetime(2026, 1, 1))
    with pytest.raises(Exception):
        operations._parse_timestamp("invalid")
    with pytest.raises(Exception):
        operations._parse_timestamp(None)
    assert operations._utc_now().endswith("Z")
