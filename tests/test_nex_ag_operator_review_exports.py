from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from nex_ag.operator_reviews import (
    AG_EVIDENCE_EXPORT_TABLE,
    ALLOWED_EVIDENCE_REDACTION_STATUSES,
    ALLOWED_EVIDENCE_TYPES,
    ALLOWED_EXPORT_FORMATS,
    ALLOWED_EXPORT_STATUSES,
    OPERATOR_EVIDENCE_EXPORT_RECORDED_EVENT_TYPE,
    OPERATOR_EVIDENCE_EXPORT_SCHEMA_VERSION,
    OPERATOR_EVIDENCE_EXPORT_MUTATION_SCHEMA_VERSION,
    OperatorEvidenceExportService,
    OperatorEvidenceExportStore,
    OperatorReviewNoteStore,
    OperatorReviewNoteError,
    SqlAlchemyOperatorEvidenceExportStore,
    build_operator_evidence_export_list_response,
    build_operator_evidence_export_mutation_response,
    build_operator_evidence_export_record,
    default_operator_evidence_export_store,
    emit_operator_evidence_export_event,
    evidence_export_idempotency_signature,
    evidence_manifest,
    optional_hex_hash,
    register_operator_review_note_routes,
    required_export_idempotency_key,
    sha256_json,
    _datetime_value,
    _json_param_expr,
    _json_value,
)
from nex_runtime import (
    InMemoryOperationalEventStore,
    OperationalEventEmitter,
    OperationalEventError,
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


def export_schema() -> dict[str, Any]:
    return json.loads(
        (
            CONTRACTS_ROOT
            / "schemas/generation/ag_redacted_evidence_export.v1.schema.json"
        ).read_text(encoding="utf-8")
    )


def export_example() -> dict[str, Any]:
    return json.loads(
        (
            CONTRACTS_ROOT
            / "examples/generation/ag_redacted_evidence_export.worker_result.json"
        ).read_text(encoding="utf-8")
    )


def sample_export_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "target_ref": {
            "target_service": "nex-ae-api",
            "target_kind": "operator_control.worker_result",
            "target_id": "worker-result-001",
        },
        "operator_ref": {
            "operator_type": "user",
            "operator_id": "employee-0001",
            "tenant_id": "local-tenant",
        },
        "export_format": "json",
        "export_status": "READY",
        "evidence_refs": [
            {
                "source_service": "nex-ae-api",
                "evidence_type": "worker_result",
                "evidence_id": "worker-result-001",
                "relation": "primary",
                "content_hash": "a" * 64,
                "redaction_status": "HASH_ONLY",
            },
            {
                "source_service": "nex-ae-api",
                "evidence_type": "worker_result",
                "evidence_id": "worker-result-001",
                "relation": "duplicate",
                "content_hash": "b" * 64,
                "redaction_status": "REDACTED",
            },
            {
                "source_service": "nex-ag",
                "evidence_type": "operator_note",
                "evidence_id": "ag-op-note-001",
                "relation": "operator_context",
            },
        ],
        "metadata": {"source_view": "operations_dashboard"},
    }
    payload.update(overrides)
    return payload


def build_export(
    payload: dict[str, Any] | None = None,
    *,
    idempotency_key: str | None = "idem-0626-export",
    created_at: str = "2026-09-10T00:00:00Z",
) -> dict[str, Any]:
    return build_operator_evidence_export_record(
        sample_export_payload() if payload is None else payload,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key=idempotency_key,
        created_at=created_at,
    )


def sqlite_export_store() -> tuple[SqlAlchemyOperatorEvidenceExportStore, Any]:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                f"""
                CREATE TABLE {AG_EVIDENCE_EXPORT_TABLE} (
                    export_id TEXT PRIMARY KEY,
                    export_schema_version TEXT NOT NULL,
                    target_service TEXT NOT NULL,
                    target_kind TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    trace_id TEXT,
                    request_id TEXT NOT NULL,
                    operator_type TEXT NOT NULL,
                    operator_id TEXT NOT NULL,
                    tenant_id TEXT,
                    operator_ref TEXT NOT NULL,
                    export_status TEXT NOT NULL,
                    export_format TEXT NOT NULL,
                    redaction_profile TEXT NOT NULL,
                    evidence_manifest TEXT NOT NULL,
                    evidence_hash TEXT NOT NULL,
                    evidence_item_count INTEGER NOT NULL,
                    metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
    return SqlAlchemyOperatorEvidenceExportStore(build_session_factory(engine)), engine


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


def build_export_route_client(
    *,
    export_store: Any | None = None,
    audit_event_store: InMemoryOperationalEventStore | None = None,
) -> tuple[TestClient, Any, InMemoryOperationalEventStore]:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    selected_export_store = export_store or OperatorEvidenceExportStore()
    selected_event_store = audit_event_store or InMemoryOperationalEventStore()
    register_operator_review_note_routes(
        app,
        store=OperatorReviewNoteStore(),
        export_store=selected_export_store,
        audit_event_store=selected_event_store,
    )
    return TestClient(app), selected_export_store, selected_event_store


def assert_export_error(payload: dict[str, Any], error_code: str) -> None:
    with pytest.raises(OperatorReviewNoteError) as exc:
        build_export(payload)
    assert exc.value.status_code == 422
    assert exc.value.error_code == error_code


def test_redacted_evidence_export_record_matches_contract_and_hashes() -> None:
    record = build_export()

    Draft202012Validator(export_schema()).validate(record)
    assert record["export_schema_version"] == OPERATOR_EVIDENCE_EXPORT_SCHEMA_VERSION
    assert record["export_status"] == "READY"
    assert record["export_format"] == "json"
    assert record["redaction_profile"] == "ag_redacted_manifest_v1"
    assert record["evidence_item_count"] == 2
    assert record["evidence_hash"] == sha256_json(record["evidence_manifest"])
    assert record["metadata"] == {
        "source_view": "operations_dashboard",
        "raw_evidence_body_stored": False,
        "raw_prompt_stored": False,
        "raw_generation_output_stored": False,
        "raw_source_text_stored": False,
        "storage_paths_included": False,
        "export_storage": "redacted_manifest_plus_hashes",
        "idempotency_key_hash": record["metadata"]["idempotency_key_hash"],
        "idempotency_key_stored": False,
    }
    assert "idem-0626-export" not in json.dumps(record)
    assert "evidence_refs" not in record


def test_redacted_evidence_export_example_matches_schema_and_manifest_hash() -> None:
    example = export_example()

    Draft202012Validator(export_schema()).validate(example)
    assert example["evidence_hash"] == sha256_json(example["evidence_manifest"])
    assert example["metadata"]["raw_evidence_body_stored"] is False
    assert example["metadata"]["storage_paths_included"] is False


@pytest.mark.parametrize("export_status", ALLOWED_EXPORT_STATUSES)
def test_export_statuses_are_accepted(export_status: str) -> None:
    assert build_export(sample_export_payload(export_status=export_status))[
        "export_status"
    ] == export_status


@pytest.mark.parametrize("export_format", ALLOWED_EXPORT_FORMATS)
def test_export_formats_are_accepted(export_format: str) -> None:
    assert build_export(sample_export_payload(export_format=export_format))[
        "export_format"
    ] == export_format


@pytest.mark.parametrize("evidence_type", ALLOWED_EVIDENCE_TYPES)
def test_evidence_types_are_accepted(evidence_type: str) -> None:
    payload = sample_export_payload(
        evidence_refs=[
            {
                "source_service": "nex-ag",
                "evidence_type": evidence_type,
                "evidence_id": f"{evidence_type}-001",
            }
        ]
    )

    record = build_export(payload)

    assert record["evidence_manifest"]["items"][0]["evidence_type"] == evidence_type


@pytest.mark.parametrize("redaction_status", ALLOWED_EVIDENCE_REDACTION_STATUSES)
def test_evidence_redaction_statuses_are_accepted(redaction_status: str) -> None:
    payload = sample_export_payload(
        evidence_refs=[
            {
                "source_service": "nex-ag",
                "evidence_type": "operator_note",
                "evidence_id": "ag-op-note-001",
                "redaction_status": redaction_status,
            }
        ]
    )

    record = build_export(payload)

    assert record["evidence_manifest"]["items"][0]["redaction_status"] == (
        redaction_status
    )


def test_evidence_manifest_deduplicates_refs_and_defaults_redaction() -> None:
    manifest = evidence_manifest(sample_export_payload()["evidence_refs"])

    assert manifest["item_count"] == 2
    assert manifest["raw_payloads_included"] is False
    assert manifest["storage_paths_included"] is False
    assert manifest["items"][0]["content_hash"] == "a" * 64
    assert manifest["items"][1]["content_hash"] is None
    assert manifest["items"][1]["redaction_status"] == "METADATA_ONLY"


def test_export_id_can_be_supplied_or_derived_from_idempotency_key() -> None:
    supplied = build_export(sample_export_payload(export_id="ag-export-supplied"))
    first = build_export(idempotency_key="stable-export-key")
    second = build_export(idempotency_key="stable-export-key")
    content_based = build_export(idempotency_key=None)

    assert supplied["export_id"] == "ag-export-supplied"
    assert first["export_id"] == second["export_id"]
    assert content_based["export_id"] != first["export_id"]


def test_export_record_defaults_metadata_when_absent() -> None:
    payload = sample_export_payload()
    payload.pop("metadata")

    record = build_export(payload, idempotency_key=None)

    assert record["metadata"] == {
        "raw_evidence_body_stored": False,
        "raw_prompt_stored": False,
        "raw_generation_output_stored": False,
        "raw_source_text_stored": False,
        "storage_paths_included": False,
        "export_storage": "redacted_manifest_plus_hashes",
    }


def test_export_idempotency_signature_uses_safe_stable_fields() -> None:
    record = build_export()

    signature = evidence_export_idempotency_signature(record)

    assert signature == {
        "target_service": "nex-ae-api",
        "target_kind": "operator_control.worker_result",
        "target_id": "worker-result-001",
        "operator_type": "user",
        "operator_id": "employee-0001",
        "export_format": "json",
        "redaction_profile": "ag_redacted_manifest_v1",
        "evidence_hash": record["evidence_hash"],
        "metadata": record["metadata"],
    }


@pytest.mark.parametrize(
    ("payload", "error_code"),
    [
        ({}, "ag.operator_review_note_target_ref_required"),
        (
            sample_export_payload(evidence_refs=None),
            "ag.evidence_export_refs_required",
        ),
        (
            sample_export_payload(evidence_refs="not-list"),
            "ag.evidence_export_refs_invalid",
        ),
        (
            sample_export_payload(evidence_refs=[]),
            "ag.evidence_export_refs_empty",
        ),
        (
            sample_export_payload(evidence_refs=["not-object"]),
            "ag.evidence_export_ref_invalid",
        ),
        (
            sample_export_payload(
                evidence_refs=[
                    {
                        "source_service": "nex-unknown",
                        "evidence_type": "worker_result",
                        "evidence_id": "worker-result-001",
                    }
                ]
            ),
            "ag.operator_review_note_source_service_unsupported",
        ),
        (
            sample_export_payload(
                evidence_refs=[
                    {
                        "source_service": "nex-ag",
                        "evidence_type": "unknown",
                        "evidence_id": "evidence-001",
                    }
                ]
            ),
            "ag.operator_review_note_evidence_type_unsupported",
        ),
        (
            sample_export_payload(
                evidence_refs=[
                    {
                        "source_service": "nex-ag",
                        "evidence_type": "operator_note",
                        "evidence_id": "ag-op-note-001",
                        "content_hash": "A" * 64,
                    }
                ]
            ),
            "ag.evidence_export_content_hash_invalid",
        ),
        (
            sample_export_payload(export_status="UNKNOWN"),
            "ag.operator_review_note_export_status_unsupported",
        ),
        (
            sample_export_payload(export_format="tar"),
            "ag.operator_review_note_export_format_unsupported",
        ),
        (
            sample_export_payload(metadata="not-object"),
            "ag.evidence_export_metadata_invalid",
        ),
        (
            sample_export_payload(metadata={"storage_path": "/data/raw.bin"}),
            "ag.operator_review_note_sensitive_payload",
        ),
        (
            sample_export_payload(raw_prompt="show the raw prompt"),
            "ag.operator_review_note_sensitive_payload",
        ),
    ],
)
def test_export_record_rejects_invalid_or_sensitive_payloads(
    payload: dict[str, Any],
    error_code: str,
) -> None:
    assert_export_error(payload, error_code)


def test_export_record_rejects_blank_request_id() -> None:
    with pytest.raises(OperatorReviewNoteError) as exc:
        build_operator_evidence_export_record(
            sample_export_payload(),
            request_id=" ",
            trace_id=TRACE_ID,
        )

    assert exc.value.error_code == "ag.operator_review_note_request_id_required"


def test_optional_hex_hash_accepts_blank_and_rejects_bad_hashes() -> None:
    assert optional_hex_hash(None) is None
    assert optional_hex_hash("  ") is None
    assert optional_hex_hash("0" * 64) == "0" * 64
    with pytest.raises(OperatorReviewNoteError):
        optional_hex_hash("not-a-sha")


def test_in_memory_export_store_filters_orders_and_deletes() -> None:
    store = OperatorEvidenceExportStore()
    older = build_export(created_at="2026-09-10T00:00:00Z")
    newer = build_export(
        sample_export_payload(target_ref={**sample_export_payload()["target_ref"]}),
        idempotency_key="idem-0626-newer",
        created_at="2026-09-10T00:01:00Z",
    )
    failed = build_export(
        sample_export_payload(
            export_status="FAILED",
            target_ref={
                "target_service": "nex-cx",
                "target_kind": "processing_run",
                "target_id": "cx-run-001",
            },
            operator_ref={
                "operator_type": "service",
                "operator_id": "nex-ag",
                "tenant_id": None,
            },
        ),
        idempotency_key="idem-0626-failed",
        created_at="2026-09-10T00:02:00Z",
    )
    store.save(older)
    store.save(newer)
    store.save(failed)

    listed = store.list_exports(target_service="nex-ae-api")
    filtered = store.list_exports(
        export_status="FAILED",
        operator_type="service",
        operator_id="nex-ag",
        limit=5,
    )
    ranged = store.list_exports(
        updated_from="2026-09-10T00:01:30Z",
        updated_to="2026-09-10T00:02:30Z",
    )

    assert [record["export_id"] for record in listed] == [
        newer["export_id"],
        older["export_id"],
    ]
    assert filtered == [failed]
    assert ranged == [failed]
    assert store.get(older["export_id"]) == older
    assert store.delete(older["export_id"]) == 1
    assert store.delete(older["export_id"]) == 0


def test_export_list_response_summarizes_status_format_and_empty_state() -> None:
    ready = build_export(created_at="2026-09-10T00:00:00Z")
    failed = build_export(
        sample_export_payload(export_status="FAILED", export_format="jsonl"),
        idempotency_key="idem-0626-list-failed",
        created_at="2026-09-10T00:01:00Z",
    )

    response = build_operator_evidence_export_list_response(
        [ready, failed],
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    empty = build_operator_evidence_export_list_response(
        [],
        request_id=REQUEST_ID,
        trace_id=None,
    )

    assert [item["export_id"] for item in response["items"]] == [
        failed["export_id"],
        ready["export_id"],
    ]
    assert response["summary"]["by_status"] == {"FAILED": 1, "READY": 1}
    assert response["summary"]["by_format"] == {"jsonl": 1, "json": 1}
    assert response["summary"]["latest_updated_at"] == failed["updated_at"]
    assert empty["summary"]["count"] == 0
    assert empty["summary"]["latest_updated_at"] is None


def test_export_mutation_response_summarizes_record_and_validates_status() -> None:
    record = build_export()

    response = build_operator_evidence_export_mutation_response(
        record,
        idempotency_status="NEW",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert response["export_mutation_schema_version"] == (
        OPERATOR_EVIDENCE_EXPORT_MUTATION_SCHEMA_VERSION
    )
    assert response["export"] == record
    assert response["summary"] == {
        "export_id": record["export_id"],
        "target_service": "nex-ae-api",
        "target_kind": "operator_control.worker_result",
        "target_id": "worker-result-001",
        "export_status": "READY",
        "export_format": "json",
        "evidence_item_count": 2,
    }
    with pytest.raises(OperatorReviewNoteError) as exc:
        build_operator_evidence_export_mutation_response(
            record,
            idempotency_status="STALE",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    assert exc.value.error_code == "ag.operator_review_note_idempotency_status_unsupported"


def test_export_service_creates_replays_and_rejects_conflicting_idempotency() -> None:
    store = OperatorEvidenceExportStore()
    service = OperatorEvidenceExportService(store)
    payload = sample_export_payload(export_id="caller-supplied-id-is-ignored")

    created = service.create_export(
        payload,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0627-create",
    )
    replayed = service.create_export(
        payload,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0627-create",
    )

    assert created["idempotency_status"] == "NEW"
    assert replayed["idempotency_status"] == "REPLAYED"
    assert created["export"] == replayed["export"]
    assert created["export"]["export_id"] != "caller-supplied-id-is-ignored"
    assert len(store.records) == 1

    with pytest.raises(OperatorReviewNoteError) as exc:
        service.create_export(
            sample_export_payload(export_format="jsonl"),
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
            idempotency_key="idem-0627-create",
        )
    assert exc.value.status_code == 409
    assert exc.value.error_code == "ag.evidence_export_idempotency_conflict"


def test_export_service_lists_filters_and_gets_exports() -> None:
    store = OperatorEvidenceExportStore()
    service = OperatorEvidenceExportService(store)
    ready = service.create_export(
        sample_export_payload(),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0627-ready",
    )["export"]
    failed = service.create_export(
        sample_export_payload(
            export_status="FAILED",
            target_ref={
                "target_service": "nex-cx",
                "target_kind": "processing_run",
                "target_id": "cx-run-001",
            },
            operator_ref={
                "operator_type": "service",
                "operator_id": "nex-ag",
                "tenant_id": None,
            },
        ),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0627-failed",
    )["export"]

    ready_list = service.list_exports(
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        target_service="nex-ae-api",
        target_kind="operator_control.worker_result",
        target_id="worker-result-001",
        export_trace_id=TRACE_ID,
        export_status="READY",
        operator_type="user",
        operator_id="employee-0001",
        limit=10,
    )
    failed_list = service.list_exports(
        request_id=REQUEST_ID,
        trace_id=None,
        target_service="nex-cx",
        export_status="FAILED",
        operator_type="service",
    )

    assert ready_list["items"] == [ready]
    assert failed_list["items"] == [failed]
    assert service.get_export(ready["export_id"]) == ready


@pytest.mark.parametrize(
    ("kwargs", "error_code"),
    [
        (
            {"target_service": "nex-unknown"},
            "ag.operator_review_note_target_service_unsupported",
        ),
        (
            {"export_status": "UNKNOWN"},
            "ag.operator_review_note_export_status_unsupported",
        ),
        (
            {"operator_type": "bot"},
            "ag.operator_review_note_operator_type_unsupported",
        ),
    ],
)
def test_export_service_list_rejects_invalid_filters(
    kwargs: dict[str, Any],
    error_code: str,
) -> None:
    service = OperatorEvidenceExportService(OperatorEvidenceExportStore())

    with pytest.raises(OperatorReviewNoteError) as exc:
        service.list_exports(
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
            **kwargs,
        )

    assert exc.value.status_code == 422
    assert exc.value.error_code == error_code


def test_export_service_requires_idempotency_key_and_reports_not_found() -> None:
    service = OperatorEvidenceExportService(OperatorEvidenceExportStore())

    assert required_export_idempotency_key("  idem-export  ") == "idem-export"
    with pytest.raises(OperatorReviewNoteError) as exc:
        service.create_export(
            sample_export_payload(),
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
            idempotency_key=None,
        )
    assert exc.value.status_code == 422
    assert exc.value.error_code == "ag.evidence_export_idempotency_key_required"

    with pytest.raises(OperatorReviewNoteError) as missing:
        service.get_export("missing-export")
    assert missing.value.status_code == 404
    assert missing.value.error_code == "ag.evidence_export_not_found"

    with pytest.raises(OperatorReviewNoteError) as blank:
        service.get_export(" ")
    assert blank.value.error_code == "ag.operator_review_note_export_id_required"


def test_emit_operator_evidence_export_event_records_safe_event() -> None:
    event_store = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id="nex-ag", store=event_store)
    record = build_export(sample_export_payload(export_id="export-event"))

    result = emit_operator_evidence_export_event(emitter, record)
    events = event_store.list_events(
        event_type=OPERATOR_EVIDENCE_EXPORT_RECORDED_EVENT_TYPE
    )

    assert result.ok is True
    assert len(events) == 1
    assert events[0]["subject_ref"] == {
        "type": "operator_evidence_export",
        "id": "export-event",
    }
    assert events[0]["details"] == {
        "export_id": "export-event",
        "target_service": "nex-ae-api",
        "target_kind": "operator_control.worker_result",
        "target_id": "worker-result-001",
        "export_status": "READY",
        "export_format": "json",
        "redaction_profile": "ag_redacted_manifest_v1",
        "evidence_hash": record["evidence_hash"],
        "evidence_item_count": 2,
        "operator_type": "user",
        "operator_id": "employee-0001",
    }
    assert "evidence_manifest" not in events[0]["details"]


def test_emit_operator_evidence_export_event_uses_safe_failure_result() -> None:
    class FailingEventStore:
        def append(self, event: dict[str, Any]) -> dict[str, Any]:
            raise OperationalEventError(
                error_code="operational_event.store_unavailable",
                detail="store unavailable",
                status_code=503,
            )

    emitter = OperationalEventEmitter(service_id="nex-ag", store=FailingEventStore())

    result = emit_operator_evidence_export_event(emitter, build_export())

    assert result.ok is False
    assert result.error_code == "operational_event.store_unavailable"


def test_operator_evidence_export_routes_create_replay_list_and_get() -> None:
    client, store, event_store = build_export_route_client()
    headers = {**admin_auth_headers(), "Idempotency-Key": "idem-route-0628"}

    created = client.post(
        "/admin/v1/operator-review/evidence-exports",
        headers=headers,
        json=sample_export_payload(),
    )
    replayed = client.post(
        "/admin/v1/operator-review/evidence-exports",
        headers={**admin_auth_headers(), "Idempotency-Key": "idem-route-0628"},
        json=sample_export_payload(),
    )
    listed = client.get(
        "/admin/v1/operator-review/evidence-exports?target_service=nex-ae-api",
        headers=service_auth_headers(),
    )
    export_id = created.json()["export"]["export_id"]
    detail = client.get(
        f"/admin/v1/operator-review/evidence-exports/{export_id}",
        headers=service_auth_headers(),
    )

    assert created.status_code == 201
    Draft202012Validator(export_schema()).validate(created.json()["export"])
    assert replayed.status_code == 200
    assert replayed.json()["idempotency_status"] == "REPLAYED"
    assert listed.status_code == 200
    assert listed.json()["summary"]["count"] == 1
    assert detail.status_code == 200
    assert detail.json()["export_id"] == export_id
    assert "evidence_refs" not in created.json()["export"]
    assert "idem-route-0628" not in json.dumps(created.json())
    assert len(store.records) == 1
    assert event_store.summary()["total"] == 1


def test_operator_evidence_export_routes_reject_auth_and_invalid_payloads() -> None:
    client, _, _ = build_export_route_client()

    missing_auth = client.get("/admin/v1/operator-review/evidence-exports")
    non_admin = client.post(
        "/admin/v1/operator-review/evidence-exports",
        headers={**non_admin_auth_headers(), "Idempotency-Key": "idem-non-admin"},
        json=sample_export_payload(),
    )
    missing_idempotency = client.post(
        "/admin/v1/operator-review/evidence-exports",
        headers=admin_auth_headers(),
        json=sample_export_payload(),
    )
    invalid_payload = client.post(
        "/admin/v1/operator-review/evidence-exports",
        headers={**admin_auth_headers(), "Idempotency-Key": "idem-invalid-export"},
        json=sample_export_payload(export_status="UNKNOWN"),
    )
    invalid_filter = client.get(
        "/admin/v1/operator-review/evidence-exports?export_status=UNKNOWN",
        headers=service_auth_headers(),
    )
    missing_detail_auth = client.get(
        "/admin/v1/operator-review/evidence-exports/missing"
    )

    assert missing_auth.status_code == 401
    assert missing_detail_auth.status_code == 401
    assert non_admin.status_code == 403
    assert non_admin.json()["error_code"] == "AG_OPERATOR_REVIEW_ADMIN_ROLE_REQUIRED"
    assert missing_idempotency.status_code == 422
    assert missing_idempotency.json()["error_code"] == (
        "ag.evidence_export_idempotency_key_required"
    )
    assert invalid_payload.status_code == 422
    assert invalid_payload.json()["error_code"] == (
        "ag.operator_review_note_export_status_unsupported"
    )
    assert invalid_filter.status_code == 422
    assert invalid_filter.json()["error_code"] == (
        "ag.operator_review_note_export_status_unsupported"
    )


def test_operator_evidence_export_routes_report_missing_and_store_failures() -> None:
    class FailingExportStore:
        def get(self, export_id: str) -> None:
            raise OperatorReviewNoteError(
                status_code=503,
                error_code="ag.evidence_export_store_unavailable",
                detail="store down",
            )

        def list_exports(self, **kwargs: Any) -> list[dict[str, Any]]:
            return []

        def save(self, record: dict[str, Any]) -> dict[str, Any]:
            return record

    client, _, _ = build_export_route_client()
    failing_client, _, _ = build_export_route_client(export_store=FailingExportStore())

    missing = client.get(
        "/admin/v1/operator-review/evidence-exports/missing",
        headers=service_auth_headers(),
    )
    store_failure = failing_client.post(
        "/admin/v1/operator-review/evidence-exports",
        headers={**admin_auth_headers(), "Idempotency-Key": "idem-export-fail"},
        json=sample_export_payload(),
    )

    assert missing.status_code == 404
    assert missing.json()["error_code"] == "ag.evidence_export_not_found"
    assert store_failure.status_code == 503
    assert store_failure.json()["error_code"] == "ag.evidence_export_store_unavailable"


def test_sqlalchemy_export_store_roundtrips_and_updates_sqlite() -> None:
    store, engine = sqlite_export_store()
    record = build_export(created_at="2026-09-10T00:00:00Z")
    updated = {
        **record,
        "export_status": "FAILED",
        "updated_at": "2026-09-10T00:03:00Z",
    }

    store.save(record)
    store.save(updated)
    fetched = store.get(record["export_id"])
    listed = store.list_exports(
        target_service="nex-ae-api",
        target_kind="operator_control.worker_result",
        target_id="worker-result-001",
        trace_id=TRACE_ID,
        export_status="FAILED",
        operator_type="user",
        operator_id="employee-0001",
        updated_from="2026-09-10T00:02:00Z",
        updated_to="2026-09-10T00:04:00Z",
        limit=10,
    )

    assert fetched == updated
    assert listed == [updated]
    assert store.get("missing-export") is None
    assert store.list_exports(export_status="READY") == []
    assert store.delete(record["export_id"]) == 1
    assert store.delete(record["export_id"]) == 0
    engine.dispose()


def test_sqlalchemy_export_store_reports_unavailable() -> None:
    class FailingSessionFactory:
        def __call__(self) -> "FailingSessionFactory":
            return self

        def __enter__(self) -> "FailingSessionFactory":
            raise SQLAlchemyError("boom")

        def __exit__(self, *_args: object) -> None:
            return None

    store = SqlAlchemyOperatorEvidenceExportStore(FailingSessionFactory())  # type: ignore[arg-type]
    record = build_export()

    for action in (
        lambda: store.save(record),
        lambda: store.get(record["export_id"]),
        lambda: store.list_exports(),
        lambda: store.delete(record["export_id"]),
    ):
        with pytest.raises(OperatorReviewNoteError) as exc:
            action()
        assert exc.value.status_code == 503
        assert exc.value.error_code == "ag.evidence_export_store_unavailable"


def test_default_export_store_uses_persistence_when_available() -> None:
    app_without_persistence = FastAPI()
    app_with_persistence = FastAPI()
    _, engine = sqlite_export_store()
    app_with_persistence.state.nex_persistence = type(
        "Persistence",
        (),
        {"api_session_factory": build_session_factory(engine)},
    )()

    fallback = default_operator_evidence_export_store(app_without_persistence)
    persisted = default_operator_evidence_export_store(app_with_persistence)

    assert isinstance(fallback, OperatorEvidenceExportStore)
    assert isinstance(persisted, SqlAlchemyOperatorEvidenceExportStore)
    engine.dispose()


def test_export_sql_helpers_handle_json_and_datetime_values() -> None:
    assert _json_param_expr("metadata", "postgresql") == "CAST(:metadata AS jsonb)"
    assert _json_param_expr("metadata", "sqlite") == ":metadata"
    assert _json_value(None, {"fallback": True}) == {"fallback": True}
    assert _json_value('{"ok": true}', {}) == {"ok": True}
    assert _json_value({"already": "decoded"}, {}) == {"already": "decoded"}
    assert _datetime_value("2026-09-10T00:00:00Z") == "2026-09-10T00:00:00Z"
