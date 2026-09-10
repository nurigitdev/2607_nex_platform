from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from nex_ag.operator_reviews import (
    AG_OPERATOR_NOTE_TABLE,
    ALLOWED_NOTE_SEVERITIES,
    ALLOWED_NOTE_STATUSES,
    ALLOWED_NOTE_TYPES,
    OPERATOR_REVIEW_NOTE_RECORDED_EVENT_TYPE,
    OperatorReviewNoteError,
    OperatorReviewNoteService,
    OperatorReviewNoteStore,
    SqlAlchemyOperatorReviewNoteStore,
    build_operator_review_note_list_response,
    build_operator_review_note_mutation_response,
    build_operator_review_note_record,
    default_operator_review_note_store,
    emit_operator_review_note_event,
    find_sensitive_operator_review_note_keys,
    normalize_limit,
    operator_note_idempotency_signature,
    operator_note_preview,
    register_operator_review_note_routes,
    required_idempotency_key,
    sha256_text,
    _datetime_value,
    _json_param_expr,
    _json_value,
)
from nex_runtime import (
    InMemoryOperationalEventStore,
    OperationalEventError,
    OperationalEventEmitter,
    SERVICE_SPECS,
    build_engine,
    build_service_app,
    build_session_factory,
    issue_mock_service_token,
    issue_mock_user_token,
)


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"
CONTRACTS_ROOT = Path(__file__).resolve().parents[1] / "contracts"


def operator_note_schema() -> dict[str, Any]:
    return json.loads(
        (
            CONTRACTS_ROOT
            / "schemas/generation/ag_operator_review_note.v1.schema.json"
        ).read_text(encoding="utf-8")
    )


def sample_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "target_ref": {
            "target_service": "nex-ae-api",
            "target_kind": "artifact_retention.scheduler_daemon",
            "target_id": "daemon-run-001",
        },
        "operator_ref": {
            "operator_type": "user",
            "operator_id": "employee-0001",
            "tenant_id": "local-tenant",
        },
        "operator_note": "AE scheduler daemon worker result needs operator follow-up.",
        "note_type": "OBSERVATION",
        "severity": "MEDIUM",
        "reason_codes": [
            "worker_result_attention",
            "operator_follow_up",
            "worker_result_attention",
        ],
        "metadata": {"source_view": "operations_dashboard"},
    }
    payload.update(overrides)
    return payload


def build_record(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return build_operator_review_note_record(
        sample_payload() if payload is None else payload,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        created_at="2026-09-10T00:00:00Z",
    )


def sqlite_operator_note_store() -> tuple[SqlAlchemyOperatorReviewNoteStore, Any]:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE ag_op_notes (
                    operator_note_id TEXT PRIMARY KEY,
                    operator_note_schema_version TEXT NOT NULL,
                    target_service TEXT NOT NULL,
                    target_kind TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    trace_id TEXT,
                    request_id TEXT NOT NULL,
                    operator_type TEXT NOT NULL,
                    operator_id TEXT NOT NULL,
                    tenant_id TEXT,
                    operator_ref TEXT NOT NULL,
                    note_status TEXT NOT NULL,
                    note_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    operator_note_hash TEXT NOT NULL,
                    operator_note_preview TEXT NOT NULL,
                    reason_codes TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
    return SqlAlchemyOperatorReviewNoteStore(build_session_factory(engine)), engine


def service_auth_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience="nex-ag")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def admin_auth_headers() -> dict[str, str]:
    issued = issue_mock_user_token(
        tenant_id="local-tenant",
        user_id="employee-0001",
        audience="nex-ag",
        roles=["admin"],
    )
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def non_admin_auth_headers() -> dict[str, str]:
    issued = issue_mock_user_token(
        tenant_id="local-tenant",
        user_id="employee-0002",
        audience="nex-ag",
        roles=["viewer"],
    )
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def build_route_client(
    *,
    store: Any | None = None,
    audit_event_store: InMemoryOperationalEventStore | None = None,
) -> tuple[TestClient, Any, InMemoryOperationalEventStore]:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    selected_store = store or OperatorReviewNoteStore()
    selected_event_store = audit_event_store or InMemoryOperationalEventStore()
    register_operator_review_note_routes(
        app,
        store=selected_store,
        audit_event_store=selected_event_store,
    )
    return TestClient(app), selected_store, selected_event_store


def assert_operator_note_error(payload: dict[str, Any], error_code: str) -> None:
    with pytest.raises(OperatorReviewNoteError) as exc:
        build_record(payload)
    assert exc.value.status_code == 422
    assert exc.value.error_code == error_code


def test_operator_review_note_record_matches_contract_and_redacts_raw_note() -> None:
    record = build_record()

    Draft202012Validator(operator_note_schema()).validate(record)
    assert record["operator_note_schema_version"] == "ag_operator_review_note.v1"
    assert record["target_service"] == "nex-ae-api"
    assert record["note_status"] == "ACTIVE"
    assert record["severity"] == "MEDIUM"
    assert record["operator_note_hash"] == sha256_text(
        "AE scheduler daemon worker result needs operator follow-up."
    )
    assert record["operator_note_preview"] == (
        "AE scheduler daemon worker result needs operator follow-up."
    )
    assert record["reason_codes"] == [
        "worker_result_attention",
        "operator_follow_up",
    ]
    assert record["metadata"] == {
        "source_view": "operations_dashboard",
        "raw_operator_note_stored": False,
        "operator_note_storage": "hash_and_short_preview_only",
    }
    assert "operator_note" not in record


@pytest.mark.parametrize("note_status", ALLOWED_NOTE_STATUSES)
def test_note_statuses_are_accepted(note_status: str) -> None:
    assert build_record(sample_payload(note_status=note_status))["note_status"] == note_status


@pytest.mark.parametrize("note_type", ALLOWED_NOTE_TYPES)
def test_note_types_are_accepted(note_type: str) -> None:
    assert build_record(sample_payload(note_type=note_type))["note_type"] == note_type


@pytest.mark.parametrize("severity", ALLOWED_NOTE_SEVERITIES)
def test_note_severities_are_accepted(severity: str) -> None:
    assert build_record(sample_payload(severity=severity))["severity"] == severity


def test_note_id_can_be_supplied_or_derived_deterministically() -> None:
    supplied = build_record(sample_payload(operator_note_id="ag-op-note-supplied"))
    derived_one = build_record()
    derived_two = build_record()

    assert supplied["operator_note_id"] == "ag-op-note-supplied"
    assert derived_one["operator_note_id"] == derived_two["operator_note_id"]
    assert derived_one["operator_note_id"] != supplied["operator_note_id"]


def test_optional_defaults_and_nullable_trace_are_supported() -> None:
    record = build_operator_review_note_record(
        sample_payload(
            operator_ref={
                "operator_type": "service",
                "operator_id": "nex-ag",
            },
            note_status=None,
            note_type=None,
            severity=None,
            reason_codes=None,
            metadata=None,
        ),
        request_id=REQUEST_ID,
        trace_id=None,
        created_at="2026-09-10T00:00:00Z",
    )

    Draft202012Validator(operator_note_schema()).validate(record)
    assert record["trace_id"] is None
    assert record["operator_ref"] == {
        "operator_type": "service",
        "operator_id": "nex-ag",
        "tenant_id": None,
    }
    assert record["note_status"] == "ACTIVE"
    assert record["note_type"] == "OBSERVATION"
    assert record["severity"] == "INFO"
    assert record["reason_codes"] == []


def test_record_builder_uses_idempotency_key_without_storing_it() -> None:
    record = build_operator_review_note_record(
        sample_payload(),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0623-create",
        created_at="2026-09-10T00:00:00Z",
    )
    replay = build_operator_review_note_record(
        sample_payload(operator_note="AE scheduler daemon worker result changed."),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0623-create",
        created_at="2026-09-10T00:01:00Z",
    )

    assert record["operator_note_id"] == replay["operator_note_id"]
    assert record["metadata"]["idempotency_key_hash"] == sha256_text(
        "idem-0623-create"
    )
    assert record["metadata"]["idempotency_key_stored"] is False
    assert "idem-0623-create" not in json.dumps(record)


def test_idempotency_helpers_normalize_key_and_signature() -> None:
    record = build_record(sample_payload(operator_note_id="note-signature"))
    signature = operator_note_idempotency_signature(record)

    assert required_idempotency_key("  idem-0623  ") == "idem-0623"
    assert signature["target_service"] == "nex-ae-api"
    assert signature["operator_id"] == "employee-0001"
    assert signature["operator_note_hash"] == record["operator_note_hash"]


def test_operator_note_preview_is_trimmed_and_bounded() -> None:
    note = f"  {'a' * 300}  "

    assert operator_note_preview(note) == "a" * 240
    assert operator_note_preview(None) is None


def test_in_memory_store_filters_and_deletes_notes() -> None:
    store = OperatorReviewNoteStore()
    first = build_record(sample_payload(operator_note_id="note-001"))
    second = build_operator_review_note_record(
        sample_payload(
            operator_note_id="note-002",
            target_ref={
                "target_service": "nex-cx",
                "target_kind": "processing_run",
                "target_id": "cx-run-001",
            },
            note_status="RESOLVED",
            severity="LOW",
        ),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        created_at="2026-09-10T00:10:00Z",
    )

    store.save(first)
    store.save(first)
    store.save(second)

    assert store.get("note-001") == first
    assert store.list_notes(target_service="nex-ae-api") == [first]
    assert store.list_notes(target_kind="processing_run") == [second]
    assert store.list_notes(target_id="missing") == []
    assert store.list_notes(note_status="RESOLVED") == [second]
    assert store.list_notes(
        updated_from="2026-09-10T00:05:00Z",
        updated_to="2026-09-10T00:15:00Z",
    ) == [second]
    assert store.list_notes(updated_to="2026-09-09T23:59:59Z") == []
    assert store.list_notes(operator_type="user", operator_id="employee-0001") == [
        second,
        first,
    ]
    assert store.list_notes(limit=1) == [second]
    assert store.delete("missing") == 0
    assert store.delete("note-001") == 1
    assert store.get("note-001") is None


def test_operator_note_list_response_sorts_and_summarizes_records() -> None:
    older = build_record(
        sample_payload(operator_note_id="note-old", severity="HIGH", note_status="ACTIVE")
    )
    newer = build_operator_review_note_record(
        sample_payload(
            operator_note_id="note-new",
            severity="LOW",
            note_status="RESOLVED",
        ),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        created_at="2026-09-10T00:10:00Z",
    )

    response = build_operator_review_note_list_response(
        [older, newer],
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert response["operator_note_list_schema_version"] == (
        "ag_operator_review_note_list.v1"
    )
    assert [item["operator_note_id"] for item in response["items"]] == [
        "note-new",
        "note-old",
    ]
    assert response["summary"] == {
        "count": 2,
        "by_status": {"RESOLVED": 1, "ACTIVE": 1},
        "by_severity": {"LOW": 1, "HIGH": 1},
        "latest_updated_at": "2026-09-10T00:10:00Z",
    }


def test_operator_note_list_response_handles_empty_records() -> None:
    response = build_operator_review_note_list_response(
        [],
        request_id=REQUEST_ID,
        trace_id=None,
    )

    assert response["trace_id"] is None
    assert response["items"] == []
    assert response["summary"] == {
        "count": 0,
        "by_status": {},
        "by_severity": {},
        "latest_updated_at": None,
    }


def test_operator_note_mutation_response_summarizes_record() -> None:
    record = build_record(sample_payload(operator_note_id="note-mutation"))

    response = build_operator_review_note_mutation_response(
        record,
        idempotency_status="NEW",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert response["operator_note_mutation_schema_version"] == (
        "ag_operator_review_note_mutation.v1"
    )
    assert response["idempotency_status"] == "NEW"
    assert response["operator_note"] == record
    assert response["summary"] == {
        "operator_note_id": "note-mutation",
        "target_service": "nex-ae-api",
        "target_kind": "artifact_retention.scheduler_daemon",
        "target_id": "daemon-run-001",
        "note_status": "ACTIVE",
        "severity": "MEDIUM",
    }


def test_operator_review_note_service_creates_replays_and_conflicts() -> None:
    store = OperatorReviewNoteStore()
    service = OperatorReviewNoteService(store)

    created = service.create_note(
        sample_payload(),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0623-create",
    )
    replayed = service.create_note(
        sample_payload(),
        request_id="request-replay",
        trace_id=None,
        idempotency_key="idem-0623-create",
    )

    assert created["idempotency_status"] == "NEW"
    assert replayed["idempotency_status"] == "REPLAYED"
    assert replayed["operator_note"] == created["operator_note"]
    assert replayed["request_id"] == "request-replay"
    assert len(store.records) == 1
    with pytest.raises(OperatorReviewNoteError) as exc:
        service.create_note(
            sample_payload(operator_note="Different note with same idempotency key."),
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
            idempotency_key="idem-0623-create",
        )
    assert exc.value.status_code == 409
    assert exc.value.error_code == "ag.operator_review_note_idempotency_conflict"


def test_operator_review_note_service_lists_and_gets_records() -> None:
    service = OperatorReviewNoteService(OperatorReviewNoteStore())
    first = service.create_note(
        sample_payload(severity="HIGH"),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0623-first",
    )["operator_note"]
    second = service.create_note(
        sample_payload(
            target_ref={
                "target_service": "nex-cx",
                "target_kind": "processing_run",
                "target_id": "cx-run-001",
            },
            note_status="RESOLVED",
            severity="LOW",
        ),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0623-second",
    )["operator_note"]

    listed = service.list_notes(
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        target_service="nex-cx",
        note_status="RESOLVED",
        operator_type="user",
        operator_id="employee-0001",
    )

    assert service.get_note(first["operator_note_id"]) == first
    assert listed["items"] == [second]
    assert listed["summary"]["by_status"] == {"RESOLVED": 1}


def test_operator_review_note_service_rejects_invalid_controls() -> None:
    service = OperatorReviewNoteService(OperatorReviewNoteStore())

    with pytest.raises(OperatorReviewNoteError) as missing_idem:
        service.create_note(
            sample_payload(),
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
            idempotency_key=None,
        )
    with pytest.raises(OperatorReviewNoteError) as invalid_status:
        service.list_notes(
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
            note_status="UNKNOWN",
        )
    with pytest.raises(OperatorReviewNoteError) as invalid_target:
        service.list_notes(
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
            target_service="unknown",
        )
    with pytest.raises(OperatorReviewNoteError) as missing_record:
        service.get_note("missing")
    with pytest.raises(OperatorReviewNoteError) as blank_record_id:
        service.get_note(" ")

    assert missing_idem.value.error_code == (
        "ag.operator_review_note_idempotency_key_required"
    )
    assert invalid_status.value.error_code == (
        "ag.operator_review_note_note_status_unsupported"
    )
    assert invalid_target.value.error_code == (
        "ag.operator_review_note_target_service_unsupported"
    )
    assert missing_record.value.status_code == 404
    assert missing_record.value.error_code == "ag.operator_review_note_not_found"
    assert blank_record_id.value.error_code == (
        "ag.operator_review_note_operator_note_id_required"
    )


def test_emit_operator_review_note_event_records_safe_operational_event() -> None:
    event_store = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id="nex-ag", store=event_store)
    record = build_record(sample_payload(operator_note_id="note-event"))

    result = emit_operator_review_note_event(emitter, record)
    events = event_store.list_events(event_type=OPERATOR_REVIEW_NOTE_RECORDED_EVENT_TYPE)

    assert result.ok is True
    assert len(events) == 1
    assert events[0]["subject_ref"] == {
        "type": "operator_review_note",
        "id": "note-event",
    }
    assert events[0]["details"] == {
        "operator_note_id": "note-event",
        "target_service": "nex-ae-api",
        "target_kind": "artifact_retention.scheduler_daemon",
        "target_id": "daemon-run-001",
        "note_status": "ACTIVE",
        "note_type": "OBSERVATION",
        "severity": "MEDIUM",
        "operator_type": "user",
        "operator_id": "employee-0001",
        "reason_count": 2,
        "operator_note_hash": record["operator_note_hash"],
    }
    assert "operator_note_preview" not in events[0]["details"]


def test_emit_operator_review_note_event_uses_safe_failure_result() -> None:
    class FailingEventStore:
        def append(self, event: dict[str, Any]) -> dict[str, Any]:
            raise OperationalEventError(
                error_code="operational_event.store_unavailable",
                detail="store unavailable",
                status_code=503,
            )

    emitter = OperationalEventEmitter(service_id="nex-ag", store=FailingEventStore())

    result = emit_operator_review_note_event(emitter, build_record())

    assert result.ok is False
    assert result.error_code == "operational_event.store_unavailable"


def test_operator_review_note_routes_create_replay_list_and_get_records() -> None:
    client, store, event_store = build_route_client()
    headers = {**admin_auth_headers(), "Idempotency-Key": "idem-route-0624"}

    created = client.post(
        "/admin/v1/operator-review/notes",
        headers=headers,
        json=sample_payload(),
    )
    replayed = client.post(
        "/admin/v1/operator-review/notes",
        headers={**admin_auth_headers(), "Idempotency-Key": "idem-route-0624"},
        json=sample_payload(),
    )
    listed = client.get(
        "/admin/v1/operator-review/notes?target_service=nex-ae-api",
        headers=service_auth_headers(),
    )
    note_id = created.json()["operator_note"]["operator_note_id"]
    detail = client.get(
        f"/admin/v1/operator-review/notes/{note_id}",
        headers=service_auth_headers(),
    )

    assert created.status_code == 201
    Draft202012Validator(operator_note_schema()).validate(created.json()["operator_note"])
    assert replayed.status_code == 200
    assert replayed.json()["idempotency_status"] == "REPLAYED"
    assert listed.status_code == 200
    assert listed.json()["summary"]["count"] == 1
    assert detail.status_code == 200
    assert detail.json()["operator_note_id"] == note_id
    assert len(store.records) == 1
    assert event_store.summary()["total"] == 1


def test_operator_review_note_routes_reject_auth_and_invalid_payloads() -> None:
    client, _, _ = build_route_client()

    missing_auth = client.get("/admin/v1/operator-review/notes")
    non_admin = client.post(
        "/admin/v1/operator-review/notes",
        headers={**non_admin_auth_headers(), "Idempotency-Key": "idem-non-admin"},
        json=sample_payload(),
    )
    missing_idempotency = client.post(
        "/admin/v1/operator-review/notes",
        headers=admin_auth_headers(),
        json=sample_payload(),
    )
    invalid_payload = client.post(
        "/admin/v1/operator-review/notes",
        headers={**admin_auth_headers(), "Idempotency-Key": "idem-invalid"},
        json=sample_payload(note_status="UNKNOWN"),
    )
    invalid_filter = client.get(
        "/admin/v1/operator-review/notes?note_status=UNKNOWN",
        headers=service_auth_headers(),
    )
    missing_detail_auth = client.get("/admin/v1/operator-review/notes/missing")

    assert missing_auth.status_code == 401
    assert missing_detail_auth.status_code == 401
    assert non_admin.status_code == 403
    assert non_admin.json()["error_code"] == "AG_OPERATOR_REVIEW_ADMIN_ROLE_REQUIRED"
    assert missing_idempotency.status_code == 422
    assert missing_idempotency.json()["error_code"] == (
        "ag.operator_review_note_idempotency_key_required"
    )
    assert invalid_payload.status_code == 422
    assert invalid_payload.json()["error_code"] == (
        "ag.operator_review_note_note_status_unsupported"
    )
    assert invalid_filter.status_code == 422
    assert invalid_filter.json()["error_code"] == (
        "ag.operator_review_note_note_status_unsupported"
    )


def test_operator_review_note_routes_report_missing_and_store_failures() -> None:
    class FailingStore:
        def get(self, operator_note_id: str) -> None:
            raise OperatorReviewNoteError(
                status_code=503,
                error_code="ag.operator_review_note_store_unavailable",
                detail="store down",
            )

        def list_notes(self, **kwargs: Any) -> list[dict[str, Any]]:
            return []

    client, _, _ = build_route_client()
    failing_client, _, _ = build_route_client(store=FailingStore())

    missing = client.get(
        "/admin/v1/operator-review/notes/missing",
        headers=service_auth_headers(),
    )
    store_failure = failing_client.post(
        "/admin/v1/operator-review/notes",
        headers={**admin_auth_headers(), "Idempotency-Key": "idem-store-fail"},
        json=sample_payload(),
    )

    assert missing.status_code == 404
    assert missing.json()["error_code"] == "ag.operator_review_note_not_found"
    assert store_failure.status_code == 503
    assert store_failure.json()["error_code"] == (
        "ag.operator_review_note_store_unavailable"
    )


def test_sqlalchemy_operator_note_store_round_trips_sqlite() -> None:
    store, engine = sqlite_operator_note_store()
    try:
        older = build_record(sample_payload(operator_note_id="note-sqlite-old"))
        newer = build_operator_review_note_record(
            sample_payload(
                operator_note_id="note-sqlite-new",
                target_ref={
                    "target_service": "nex-cx",
                    "target_kind": "processing_run",
                    "target_id": "cx-run-001",
                },
                note_status="RESOLVED",
                severity="LOW",
            ),
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
            created_at="2026-09-10T00:10:00Z",
        )
        updated_older = {
            **older,
            "note_status": "SUPERSEDED",
            "updated_at": "2026-09-10T00:20:00Z",
        }

        store.save(older)
        store.save(newer)
        store.save(updated_older)

        loaded = store.get("note-sqlite-old")
        listed = store.list_notes(target_service="nex-cx")
        traced = store.list_notes(trace_id=TRACE_ID, operator_id="employee-0001")
        ranged = store.list_notes(
            updated_from="2026-09-10T00:05:00Z",
            updated_to="2026-09-10T00:15:00Z",
        )
        deleted = store.delete("note-sqlite-new")

        assert loaded == updated_older
        assert listed == [newer]
        assert [record["operator_note_id"] for record in traced] == [
            "note-sqlite-old",
            "note-sqlite-new",
        ]
        assert ranged == [newer]
        assert deleted == 1
        assert store.get("note-sqlite-new") is None
        assert store.delete("missing") == 0
    finally:
        engine.dispose()


def test_operator_note_sql_helpers_cover_postgres_json_and_value_normalization() -> None:
    assert AG_OPERATOR_NOTE_TABLE == "ag_op_notes"
    assert _json_param_expr("metadata", "postgresql") == "CAST(:metadata AS jsonb)"
    assert _json_param_expr("metadata", "sqlite") == ":metadata"
    assert _json_value("{\"ok\": true}", {}) == {"ok": True}
    assert _json_value(None, []) == []
    assert _json_value({"already": "decoded"}, {}) == {"already": "decoded"}
    assert _datetime_value(datetime(2026, 9, 10, tzinfo=UTC)) == (
        "2026-09-10T00:00:00Z"
    )
    assert _datetime_value(date(2026, 9, 10)) == "2026-09-10"
    assert _datetime_value("2026-09-10T00:00:00Z") == "2026-09-10T00:00:00Z"


def test_default_operator_review_note_store_uses_persistence_session_factory() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    session_factory = object()
    app.state.nex_persistence = SimpleNamespace(api_session_factory=session_factory)

    store = default_operator_review_note_store(app)

    assert isinstance(store, SqlAlchemyOperatorReviewNoteStore)
    assert store._session_factory is session_factory
    app_without_persistence = build_service_app(SERVICE_SPECS["nex-ag"])
    assert isinstance(
        default_operator_review_note_store(app_without_persistence),
        OperatorReviewNoteStore,
    )


def test_sqlalchemy_operator_note_store_reports_unavailable_errors() -> None:
    class FailingSession:
        def __enter__(self) -> "FailingSession":
            raise SQLAlchemyError("database unavailable")

        def __exit__(self, *args: object) -> None:
            return None

    store = SqlAlchemyOperatorReviewNoteStore(lambda: FailingSession())

    for action in (
        lambda: store.save(build_record()),
        lambda: store.get("note"),
        lambda: store.list_notes(),
        lambda: store.delete("note"),
    ):
        with pytest.raises(OperatorReviewNoteError) as exc:
            action()
        assert exc.value.status_code == 503
        assert exc.value.error_code == "ag.operator_review_note_store_unavailable"


@pytest.mark.parametrize(
    ("payload", "error_code"),
    [
        ({}, "ag.operator_review_note_target_ref_required"),
        (
            sample_payload(
                target_ref={
                    "target_service": "not-supported",
                    "target_kind": "x",
                    "target_id": "y",
                }
            ),
            "ag.operator_review_note_target_service_unsupported",
        ),
        (
            sample_payload(
                target_ref={
                    "target_service": "nex-ag",
                    "target_kind": " ",
                    "target_id": "y",
                }
            ),
            "ag.operator_review_note_target_kind_required",
        ),
        (
            sample_payload(
                target_ref={
                    "target_service": "nex-ag",
                    "target_kind": "x",
                    "target_id": " ",
                }
            ),
            "ag.operator_review_note_target_id_required",
        ),
        (
            sample_payload(operator_ref=None),
            "ag.operator_review_note_operator_ref_required",
        ),
        (
            sample_payload(operator_ref={"operator_type": "bot", "operator_id": "x"}),
            "ag.operator_review_note_operator_type_unsupported",
        ),
        (
            sample_payload(operator_ref={"operator_type": "user", "operator_id": " "}),
            "ag.operator_review_note_operator_id_required",
        ),
        (
            sample_payload(operator_note=" "),
            "ag.operator_review_note_operator_note_required",
        ),
        (
            sample_payload(note_status="UNKNOWN"),
            "ag.operator_review_note_note_status_unsupported",
        ),
        (
            sample_payload(note_type="UNKNOWN"),
            "ag.operator_review_note_note_type_unsupported",
        ),
        (
            sample_payload(severity="UNKNOWN"),
            "ag.operator_review_note_severity_unsupported",
        ),
        (
            sample_payload(reason_codes="operator_follow_up"),
            "ag.operator_review_note_reasons_invalid",
        ),
        (
            sample_payload(reason_codes=["operator_follow_up", " "]),
            "ag.operator_review_note_reason_invalid",
        ),
        (
            sample_payload(metadata="private"),
            "ag.operator_review_note_metadata_invalid",
        ),
        (
            sample_payload(raw_operator_note="private note"),
            "ag.operator_review_note_sensitive_payload",
        ),
        (
            sample_payload(metadata={"nested": {"raw_prompt": "private prompt"}}),
            "ag.operator_review_note_sensitive_payload",
        ),
    ],
)
def test_invalid_operator_review_note_payloads_raise_explicit_errors(
    payload: dict[str, Any],
    error_code: str,
) -> None:
    assert_operator_note_error(payload, error_code)


def test_blank_request_id_is_rejected() -> None:
    with pytest.raises(OperatorReviewNoteError) as exc:
        build_operator_review_note_record(
            sample_payload(),
            request_id=" ",
            trace_id=TRACE_ID,
        )

    assert exc.value.error_code == "ag.operator_review_note_request_id_required"


def test_operator_review_note_error_stringifies_detail() -> None:
    exc = OperatorReviewNoteError(
        status_code=422,
        error_code="ag.operator_review_note_example",
        detail="human readable detail",
    )

    assert str(exc) == "human readable detail"


def test_sensitive_key_finder_reports_nested_paths() -> None:
    payload = {
        "ok": True,
        "items": [
            {"raw_text": "private"},
            {"nested": {"api_key": "secret"}},
        ],
    }

    assert find_sensitive_operator_review_note_keys(payload) == [
        "items[0].raw_text",
        "items[1].nested.api_key",
    ]


def test_limit_normalization_bounds_values() -> None:
    assert normalize_limit(None) == 50
    assert normalize_limit(0) == 1
    assert normalize_limit(600) == 500
