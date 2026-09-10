from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from nex_ag.operator_review_cases import (
    AG_OPERATOR_REVIEW_CASE_TABLE,
    ALLOWED_CASE_PRIORITIES,
    ALLOWED_CASE_STATUSES,
    OPERATOR_REVIEW_CASE_RECORDED_EVENT_TYPE,
    OPERATOR_REVIEW_CASE_SCHEMA_VERSION,
    OperatorReviewCaseService,
    OperatorReviewCaseStore,
    SqlAlchemyOperatorReviewCaseStore,
    _operator_review_case_filter_clause,
    _operator_review_case_record_params,
    _operator_review_case_select_sql,
    build_operator_review_case_list_response,
    build_operator_review_case_mutation_response,
    build_operator_review_case_record,
    default_operator_review_case_store,
    emit_operator_review_case_event,
    operator_review_case_assignment_ref,
    operator_review_case_idempotency_signature,
    operator_review_case_metadata,
    operator_review_case_source_ref,
    register_operator_review_case_routes,
    required_case_idempotency_key,
)
from nex_ag.operator_reviews import (
    OperatorReviewNoteError,
    _datetime_value,
    _json_param_expr,
    _json_value,
    sha256_text,
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


def sample_case_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "target_ref": {
            "target_service": "nex-ag",
            "target_kind": "operator_review_workbench",
            "target_id": "target-0642",
        },
        "operator_ref": {
            "operator_type": "user",
            "operator_id": "employee-0001",
            "tenant_id": "local-tenant",
        },
        "case_status": "OPEN",
        "case_priority": "HIGH",
        "source_ref": {
            "source_type": "operator_review_workbench",
            "source_id": "workbench-target-0642",
            "source_service": "nex-ag",
        },
        "assignment_ref": {
            "assignee_type": "user",
            "assignee_id": "employee-0002",
            "tenant_id": "local-tenant",
        },
        "reason_codes": ["active_operator_note", "active_operator_note"],
        "metadata": {"source_view": "operator_review_workbench"},
    }
    payload.update(overrides)
    return payload


def build_case(
    payload: dict[str, Any] | None = None,
    *,
    idempotency_key: str | None = "idem-0642-case",
    created_at: str = "2026-09-11T00:00:00Z",
) -> dict[str, Any]:
    return build_operator_review_case_record(
        sample_case_payload() if payload is None else payload,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key=idempotency_key,
        created_at=created_at,
    )


def sqlite_case_store() -> tuple[SqlAlchemyOperatorReviewCaseStore, Any]:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                f"""
                CREATE TABLE {AG_OPERATOR_REVIEW_CASE_TABLE} (
                    case_id TEXT PRIMARY KEY,
                    case_schema_version TEXT NOT NULL,
                    target_service TEXT NOT NULL,
                    target_kind TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    trace_id TEXT,
                    request_id TEXT NOT NULL,
                    operator_type TEXT NOT NULL,
                    operator_id TEXT NOT NULL,
                    tenant_id TEXT,
                    operator_ref TEXT NOT NULL,
                    case_status TEXT NOT NULL,
                    case_priority TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    assignment_ref TEXT NOT NULL,
                    assignee_id TEXT,
                    reason_codes TEXT NOT NULL,
                    resolution_hash TEXT,
                    resolution_preview TEXT,
                    metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    closed_at TEXT
                )
                """
            )
        )
    return SqlAlchemyOperatorReviewCaseStore(build_session_factory(engine)), engine


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
    selected_store = store or OperatorReviewCaseStore()
    selected_event_store = audit_event_store or InMemoryOperationalEventStore()
    register_operator_review_case_routes(
        app,
        store=selected_store,
        audit_event_store=selected_event_store,
    )
    return TestClient(app), selected_store, selected_event_store


def assert_case_error(payload: dict[str, Any], error_code: str) -> None:
    with pytest.raises(OperatorReviewNoteError) as exc:
        build_case(payload)
    assert exc.value.status_code == 422
    assert exc.value.error_code == error_code


def test_operator_review_case_record_redacts_and_hashes_resolution() -> None:
    record = build_case(
        sample_case_payload(
            case_status="RESOLVED",
            resolution_comment="Operator confirmed the failed export was retried.",
        )
    )

    assert record["case_schema_version"] == OPERATOR_REVIEW_CASE_SCHEMA_VERSION
    assert record["case_status"] == "RESOLVED"
    assert record["case_priority"] == "HIGH"
    assert record["closed_at"] == "2026-09-11T00:00:00Z"
    assert record["resolution_hash"] == sha256_text(
        "Operator confirmed the failed export was retried."
    )
    assert record["resolution_preview"] == (
        "Operator confirmed the failed export was retried."
    )
    assert record["reason_codes"] == ["active_operator_note"]
    assert record["source_ref"] == {
        "source_type": "operator_review_workbench",
        "source_id": "workbench-target-0642",
        "source_service": "nex-ag",
        "workbench_path": "/admin/v1/operator-review/workbench",
    }
    assert record["metadata"]["case_comment_storage"] == "hash_and_short_preview_only"
    assert record["metadata"]["idempotency_key_stored"] is False
    assert "resolution_comment" not in record


@pytest.mark.parametrize("case_status", ALLOWED_CASE_STATUSES)
def test_case_statuses_are_accepted(case_status: str) -> None:
    record = build_case(sample_case_payload(case_status=case_status))

    assert record["case_status"] == case_status
    if case_status in {"RESOLVED", "DISMISSED"}:
        assert record["closed_at"] == "2026-09-11T00:00:00Z"
    else:
        assert record["closed_at"] is None


@pytest.mark.parametrize("case_priority", ALLOWED_CASE_PRIORITIES)
def test_case_priorities_are_accepted(case_priority: str) -> None:
    assert build_case(sample_case_payload(case_priority=case_priority))[
        "case_priority"
    ] == case_priority


def test_case_defaults_source_assignment_trace_and_ids() -> None:
    record = build_operator_review_case_record(
        sample_case_payload(
            case_status=None,
            case_priority=None,
            source_ref=None,
            assignment_ref=None,
            reason_codes=None,
        ),
        request_id=REQUEST_ID,
        trace_id=None,
        idempotency_key=None,
        created_at="2026-09-11T01:00:00Z",
    )
    repeated = build_operator_review_case_record(
        sample_case_payload(source_ref=None, assignment_ref=None),
        request_id=REQUEST_ID,
        trace_id=None,
        idempotency_key=None,
        created_at="2026-09-11T01:00:00Z",
    )

    assert record["case_status"] == "OPEN"
    assert record["case_priority"] == "MEDIUM"
    assert record["trace_id"] is None
    assert record["source_ref"]["source_type"] == "manual"
    assert record["assignment_ref"] == {
        "assignee_type": None,
        "assignee_id": None,
        "tenant_id": None,
    }
    assert record["reason_codes"] == []
    assert record["case_id"] == repeated["case_id"]


def test_case_validation_rejects_sensitive_or_invalid_payloads() -> None:
    assert_case_error(
        sample_case_payload(raw_prompt="do not store this"),
        "ag.operator_review_note_sensitive_payload",
    )
    assert_case_error(
        sample_case_payload(
            source_ref={"source_type": "bad", "source_service": "nex-ag"}
        ),
        "ag.operator_review_note_source_type_unsupported",
    )
    assert_case_error(
        sample_case_payload(source_ref=[]),
        "ag.operator_review_case_source_ref_invalid",
    )
    assert_case_error(
        sample_case_payload(assignment_ref=[]),
        "ag.operator_review_case_assignment_ref_invalid",
    )
    assert_case_error(
        sample_case_payload(assignment_ref={"assignee_type": "user"}),
        "ag.operator_review_case_assignment_ref_incomplete",
    )
    assert_case_error(
        sample_case_payload(metadata=["not-object"]),
        "ag.operator_review_case_metadata_invalid",
    )
    assert_case_error(
        sample_case_payload(case_status="PENDING"),
        "ag.operator_review_note_case_status_unsupported",
    )


def test_case_store_filters_and_delete_in_memory() -> None:
    store = OperatorReviewCaseStore()
    open_case = build_case(sample_case_payload(case_id="case-open"))
    assigned_case = build_case(
        sample_case_payload(
            case_id="case-assigned",
            target_ref={
                "target_service": "nex-cx",
                "target_kind": "retrieval_package",
                "target_id": "retrieval-001",
            },
            case_status="ASSIGNED",
            case_priority="URGENT",
            assignment_ref={
                "assignee_type": "user",
                "assignee_id": "employee-0003",
            },
        ),
        created_at="2026-09-11T01:00:00Z",
    )
    store.save(open_case)
    store.save(assigned_case)

    assert store.get("case-open") == open_case
    assert store.list_cases(target_service="nex-cx") == [assigned_case]
    assert store.list_cases(case_status="OPEN") == [open_case]
    assert store.list_cases(case_priority="URGENT") == [assigned_case]
    assert store.list_cases(assignee_id="employee-0003") == [assigned_case]
    assert store.list_cases(updated_from="2026-09-11T00:30:00Z") == [assigned_case]
    assert store.delete("case-open") == 1
    assert store.delete("case-open") == 0


def test_case_list_and_mutation_response_summaries() -> None:
    resolved = build_case(
        sample_case_payload(
            case_id="case-resolved",
            case_status="RESOLVED",
            case_priority="LOW",
        )
    )
    open_case = build_case(sample_case_payload(case_id="case-open"))

    response = build_operator_review_case_list_response(
        [resolved, open_case],
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    mutation = build_operator_review_case_mutation_response(
        open_case,
        idempotency_status="NEW",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert response["summary"]["count"] == 2
    assert response["summary"]["by_status"] == {"RESOLVED": 1, "OPEN": 1}
    assert response["summary"]["closed_count"] == 1
    assert mutation["summary"]["case_id"] == "case-open"
    assert mutation["idempotency_status"] == "NEW"


def test_case_idempotency_signature_is_safe_and_stable() -> None:
    record = build_case()
    signature = operator_review_case_idempotency_signature(record)

    assert signature["target_id"] == "target-0642"
    assert signature["source_ref"]["source_type"] == "operator_review_workbench"
    assert signature["metadata"]["idempotency_key_stored"] is False
    assert "idem-0642-case" not in str(signature)


def test_operator_review_case_service_creates_replays_and_conflicts() -> None:
    store = OperatorReviewCaseStore()
    service = OperatorReviewCaseService(store)
    payload = sample_case_payload(case_id="caller-supplied-id-is-ignored")

    created = service.create_case(
        payload,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0643-create",
    )
    replayed = service.create_case(
        payload,
        request_id="request-replay",
        trace_id=None,
        idempotency_key="idem-0643-create",
    )

    assert created["idempotency_status"] == "NEW"
    assert replayed["idempotency_status"] == "REPLAYED"
    assert replayed["case"] == created["case"]
    assert replayed["request_id"] == "request-replay"
    assert created["case"]["case_id"] != "caller-supplied-id-is-ignored"
    assert len(store.records) == 1

    with pytest.raises(OperatorReviewNoteError) as exc:
        service.create_case(
            sample_case_payload(case_priority="LOW"),
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
            idempotency_key="idem-0643-create",
        )
    assert exc.value.status_code == 409
    assert exc.value.error_code == "ag.operator_review_case_idempotency_conflict"


def test_operator_review_case_service_lists_filters_and_gets_cases() -> None:
    store = OperatorReviewCaseStore()
    service = OperatorReviewCaseService(store)
    open_case = service.create_case(
        sample_case_payload(),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0643-open",
    )["case"]
    assigned_case = service.create_case(
        sample_case_payload(
            case_status="ASSIGNED",
            case_priority="URGENT",
            target_ref={
                "target_service": "nex-cx",
                "target_kind": "retrieval_package",
                "target_id": "retrieval-0643",
            },
            assignment_ref={
                "assignee_type": "user",
                "assignee_id": "employee-0643",
            },
        ),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0643-assigned",
    )["case"]

    listed = service.list_cases(
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        target_service="nex-cx",
        case_trace_id=TRACE_ID,
        case_status="ASSIGNED",
        case_priority="URGENT",
        operator_type="user",
        operator_id="employee-0001",
        assignee_id="employee-0643",
    )

    assert service.get_case(open_case["case_id"]) == open_case
    assert listed["items"] == [assigned_case]
    assert listed["summary"]["by_status"] == {"ASSIGNED": 1}


@pytest.mark.parametrize(
    ("kwargs", "error_code"),
    [
        (
            {"target_service": "nex-unknown"},
            "ag.operator_review_note_target_service_unsupported",
        ),
        (
            {"case_status": "UNKNOWN"},
            "ag.operator_review_note_case_status_unsupported",
        ),
        (
            {"case_priority": "CRITICAL"},
            "ag.operator_review_note_case_priority_unsupported",
        ),
        (
            {"operator_type": "bot"},
            "ag.operator_review_note_operator_type_unsupported",
        ),
    ],
)
def test_operator_review_case_service_rejects_invalid_filters(
    kwargs: dict[str, Any],
    error_code: str,
) -> None:
    service = OperatorReviewCaseService(OperatorReviewCaseStore())

    with pytest.raises(OperatorReviewNoteError) as exc:
        service.list_cases(
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
            **kwargs,
        )

    assert exc.value.status_code == 422
    assert exc.value.error_code == error_code


def test_operator_review_case_service_requires_idempotency_and_reports_not_found() -> None:
    service = OperatorReviewCaseService(OperatorReviewCaseStore())

    assert required_case_idempotency_key("  idem-case  ") == "idem-case"
    with pytest.raises(OperatorReviewNoteError) as missing_idem:
        service.create_case(
            sample_case_payload(),
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
            idempotency_key=None,
        )
    with pytest.raises(OperatorReviewNoteError) as missing_case:
        service.get_case("missing-case")
    with pytest.raises(OperatorReviewNoteError) as blank_case:
        service.get_case(" ")

    assert missing_idem.value.error_code == (
        "ag.operator_review_case_idempotency_key_required"
    )
    assert missing_case.value.status_code == 404
    assert missing_case.value.error_code == "ag.operator_review_case_not_found"
    assert blank_case.value.error_code == "ag.operator_review_case_case_id_required"


def test_emit_operator_review_case_event_records_safe_operational_event() -> None:
    event_store = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id="nex-ag", store=event_store)
    record = build_case(
        sample_case_payload(
            case_id="case-event",
            case_status="RESOLVED",
            resolution_comment="Resolved with a safe hash-only evidence path.",
        )
    )

    result = emit_operator_review_case_event(emitter, record)
    events = event_store.list_events(
        event_type=OPERATOR_REVIEW_CASE_RECORDED_EVENT_TYPE
    )

    assert result.ok is True
    assert len(events) == 1
    assert events[0]["subject_ref"] == {
        "type": "operator_review_case",
        "id": "case-event",
    }
    assert events[0]["details"] == {
        "case_id": "case-event",
        "target_service": "nex-ag",
        "target_kind": "operator_review_workbench",
        "target_id": "target-0642",
        "case_status": "RESOLVED",
        "case_priority": "HIGH",
        "operator_type": "user",
        "operator_id": "employee-0001",
        "assignee_id": "employee-0002",
        "reason_count": 1,
        "resolution_hash": record["resolution_hash"],
    }
    assert "resolution_preview" not in events[0]["details"]


def test_emit_operator_review_case_event_uses_safe_failure_result() -> None:
    class FailingEventStore:
        def append(self, event: dict[str, Any]) -> dict[str, Any]:
            raise OperationalEventError(
                error_code="operational_event.store_unavailable",
                detail="store unavailable",
                status_code=503,
            )

    emitter = OperationalEventEmitter(service_id="nex-ag", store=FailingEventStore())

    result = emit_operator_review_case_event(emitter, build_case())

    assert result.ok is False
    assert result.error_code == "operational_event.store_unavailable"


def test_operator_review_case_routes_create_replay_list_and_get_records() -> None:
    client, store, event_store = build_route_client()
    headers = {**admin_auth_headers(), "Idempotency-Key": "idem-route-0643"}

    created = client.post(
        "/admin/v1/operator-review/cases",
        headers=headers,
        json=sample_case_payload(),
    )
    replayed = client.post(
        "/admin/v1/operator-review/cases",
        headers={**admin_auth_headers(), "Idempotency-Key": "idem-route-0643"},
        json=sample_case_payload(),
    )
    listed = client.get(
        "/admin/v1/operator-review/cases?target_service=nex-ag",
        headers=service_auth_headers(),
    )
    case_id = created.json()["case"]["case_id"]
    detail = client.get(
        f"/admin/v1/operator-review/cases/{case_id}",
        headers=service_auth_headers(),
    )

    assert created.status_code == 201
    assert created.json()["case"]["case_schema_version"] == (
        OPERATOR_REVIEW_CASE_SCHEMA_VERSION
    )
    assert replayed.status_code == 200
    assert replayed.json()["idempotency_status"] == "REPLAYED"
    assert listed.status_code == 200
    assert listed.json()["summary"]["count"] == 1
    assert detail.status_code == 200
    assert detail.json()["case_id"] == case_id
    assert "idem-route-0643" not in json.dumps(created.json())
    assert len(store.records) == 1
    assert event_store.summary()["total"] == 1


def test_operator_review_case_routes_reject_auth_and_invalid_payloads() -> None:
    client, _, _ = build_route_client()

    missing_auth = client.get("/admin/v1/operator-review/cases")
    non_admin = client.post(
        "/admin/v1/operator-review/cases",
        headers={**non_admin_auth_headers(), "Idempotency-Key": "idem-non-admin"},
        json=sample_case_payload(),
    )
    missing_idempotency = client.post(
        "/admin/v1/operator-review/cases",
        headers=admin_auth_headers(),
        json=sample_case_payload(),
    )
    invalid_payload = client.post(
        "/admin/v1/operator-review/cases",
        headers={**admin_auth_headers(), "Idempotency-Key": "idem-invalid-case"},
        json=sample_case_payload(case_status="UNKNOWN"),
    )
    invalid_filter = client.get(
        "/admin/v1/operator-review/cases?case_status=UNKNOWN",
        headers=service_auth_headers(),
    )
    missing_detail_auth = client.get("/admin/v1/operator-review/cases/missing")

    assert missing_auth.status_code == 401
    assert missing_detail_auth.status_code == 401
    assert non_admin.status_code == 403
    assert non_admin.json()["error_code"] == "AG_OPERATOR_REVIEW_ADMIN_ROLE_REQUIRED"
    assert missing_idempotency.status_code == 422
    assert missing_idempotency.json()["error_code"] == (
        "ag.operator_review_case_idempotency_key_required"
    )
    assert invalid_payload.status_code == 422
    assert invalid_payload.json()["error_code"] == (
        "ag.operator_review_note_case_status_unsupported"
    )
    assert invalid_filter.status_code == 422
    assert invalid_filter.json()["error_code"] == (
        "ag.operator_review_note_case_status_unsupported"
    )


def test_operator_review_case_routes_report_missing_and_store_failures() -> None:
    class FailingStore:
        def get(self, case_id: str) -> None:
            raise OperatorReviewNoteError(
                status_code=503,
                error_code="ag.operator_review_case_store_unavailable",
                detail="store down",
            )

        def list_cases(self, **kwargs: Any) -> list[dict[str, Any]]:
            return []

        def save(self, record: dict[str, Any]) -> dict[str, Any]:
            return record

    client, _, _ = build_route_client()
    failing_client, _, _ = build_route_client(store=FailingStore())

    missing = client.get(
        "/admin/v1/operator-review/cases/missing",
        headers=service_auth_headers(),
    )
    store_failure = failing_client.post(
        "/admin/v1/operator-review/cases",
        headers={**admin_auth_headers(), "Idempotency-Key": "idem-case-fail"},
        json=sample_case_payload(),
    )

    assert missing.status_code == 404
    assert missing.json()["error_code"] == "ag.operator_review_case_not_found"
    assert store_failure.status_code == 503
    assert store_failure.json()["error_code"] == (
        "ag.operator_review_case_store_unavailable"
    )


def test_sqlalchemy_operator_review_case_store_round_trips_sqlite() -> None:
    store, engine = sqlite_case_store()
    try:
        older = build_case(sample_case_payload(case_id="case-sqlite-old"))
        newer = build_case(
            sample_case_payload(
                case_id="case-sqlite-new",
                case_status="ASSIGNED",
                case_priority="URGENT",
                assignment_ref={
                    "assignee_type": "user",
                    "assignee_id": "employee-0099",
                },
            ),
            created_at="2026-09-11T00:10:00Z",
        )
        updated_older = {
            **older,
            "case_status": "ACKNOWLEDGED",
            "updated_at": "2026-09-11T00:20:00Z",
        }

        store.save(older)
        store.save(newer)
        store.save(updated_older)

        assert store.get("case-sqlite-old") == updated_older
        assert store.list_cases(case_status="ASSIGNED") == [newer]
        assert store.list_cases(assignee_id="employee-0099") == [newer]
        assert store.list_cases(
            updated_from="2026-09-11T00:05:00Z",
            updated_to="2026-09-11T00:15:00Z",
        ) == [newer]
        assert store.delete("case-sqlite-new") == 1
        assert store.get("case-sqlite-new") is None
        assert store.delete("missing") == 0
    finally:
        engine.dispose()


def test_case_sql_helpers_and_source_assignment_helpers() -> None:
    case = build_case()
    params = _operator_review_case_record_params(case)
    where, filters = _operator_review_case_filter_clause(
        target_service="nex-ag",
        target_kind="operator_review_workbench",
        target_id="target-0642",
        trace_id=TRACE_ID,
        case_status="OPEN",
        case_priority="HIGH",
        operator_type="user",
        operator_id="employee-0001",
        assignee_id="employee-0002",
        updated_from="2026-09-11T00:00:00Z",
        updated_to="2026-09-11T01:00:00Z",
    )

    assert AG_OPERATOR_REVIEW_CASE_TABLE == "ag_op_cases"
    assert _json_param_expr("metadata", "postgresql") == "CAST(:metadata AS jsonb)"
    assert _json_param_expr("metadata", "sqlite") == ":metadata"
    assert "case_status = :case_status" in where
    assert filters["assignee_id"] == "employee-0002"
    assert params["assignee_id"] == "employee-0002"
    assert '"case_comment_storage"' in params["metadata"]
    assert "FROM ag_op_cases" in _operator_review_case_select_sql("1 = 1")
    assert _json_value("{\"ok\": true}", {}) == {"ok": True}
    assert _datetime_value(datetime(2026, 9, 11, tzinfo=UTC)) == (
        "2026-09-11T00:00:00Z"
    )
    assert operator_review_case_source_ref(None)["source_type"] == "manual"
    assert operator_review_case_assignment_ref(None)["assignee_id"] is None
    assert operator_review_case_metadata(None)["external_incident_sync_deferred"] is True


def test_default_operator_review_case_store_uses_persistence_session_factory() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    session_factory = object()
    app.state.nex_persistence = SimpleNamespace(api_session_factory=session_factory)

    store = default_operator_review_case_store(app)

    assert isinstance(store, SqlAlchemyOperatorReviewCaseStore)
    assert store._session_factory is session_factory
    app_without_persistence = build_service_app(SERVICE_SPECS["nex-ag"])
    assert isinstance(
        default_operator_review_case_store(app_without_persistence),
        OperatorReviewCaseStore,
    )


def test_sqlalchemy_case_store_wraps_sqlalchemy_errors() -> None:
    class BrokenSession:
        def __enter__(self) -> "BrokenSession":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, *args: object, **kwargs: object) -> None:
            raise SQLAlchemyError("boom")

        def get_bind(self) -> object:
            return SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

    store = SqlAlchemyOperatorReviewCaseStore(lambda: BrokenSession())  # type: ignore[arg-type]

    with pytest.raises(OperatorReviewNoteError) as save_exc:
        store.save(build_case())
    with pytest.raises(OperatorReviewNoteError) as get_exc:
        store.get("case-1")
    with pytest.raises(OperatorReviewNoteError) as list_exc:
        store.list_cases()
    with pytest.raises(OperatorReviewNoteError) as delete_exc:
        store.delete("case-1")

    assert save_exc.value.error_code == "ag.operator_review_case_store_unavailable"
    assert get_exc.value.error_code == "ag.operator_review_case_store_unavailable"
    assert list_exc.value.error_code == "ag.operator_review_case_store_unavailable"
    assert delete_exc.value.error_code == "ag.operator_review_case_store_unavailable"
