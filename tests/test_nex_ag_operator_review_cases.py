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
    ALLOWED_CASE_ACTIONS,
    ALLOWED_CASE_PRIORITIES,
    ALLOWED_CASE_STATUSES,
    OPERATOR_REVIEW_CASE_ACTION_MUTATION_SCHEMA_VERSION,
    OPERATOR_REVIEW_CASE_ACTION_OUTCOMES_SCHEMA_VERSION,
    OPERATOR_REVIEW_CASE_ACTION_RECORDED_EVENT_TYPE,
    OPERATOR_REVIEW_CASE_ACTION_ADMISSION_SCHEMA_VERSION,
    OPERATOR_REVIEW_CASE_ACTION_SCHEMA_VERSION,
    OPERATOR_REVIEW_CASE_AGING_SCHEMA_VERSION,
    OPERATOR_REVIEW_CASE_ASSIGNMENT_WORKLOAD_SCHEMA_VERSION,
    OPERATOR_REVIEW_CASE_CLOSURE_PACKET_SCHEMA_VERSION,
    OPERATOR_REVIEW_CASE_EVIDENCE_LINKS_SCHEMA_VERSION,
    OPERATOR_REVIEW_CASE_QUEUE_SCHEMA_VERSION,
    OPERATOR_REVIEW_CASE_RECORDED_EVENT_TYPE,
    OPERATOR_REVIEW_CASE_ROLLUP_SCHEMA_VERSION,
    OPERATOR_REVIEW_CASE_SCHEMA_VERSION,
    OPERATOR_REVIEW_CASE_SLA_POLICY_SCHEMA_VERSION,
    OPERATOR_REVIEW_CASE_TIMELINE_SCHEMA_VERSION,
    OPERATOR_REVIEW_CASE_WORKBENCH_DETAIL_SCHEMA_VERSION,
    OperatorReviewCaseService,
    OperatorReviewCaseStore,
    SqlAlchemyOperatorReviewCaseStore,
    _operator_review_case_filter_clause,
    _case_queue_item_matches_query,
    _case_elapsed_seconds,
    _latest_case_action_summary,
    _operator_review_case_record_params,
    _operator_review_case_select_sql,
    _case_sla_state_sort_rank,
    _target_status_for_case_action,
    apply_operator_review_case_action,
    build_operator_review_case_action_mutation_response,
    build_operator_review_case_action_outcome_projection,
    build_operator_review_case_action_record,
    build_operator_review_case_action_admission_projection,
    build_operator_review_case_aging_projection,
    build_operator_review_case_assignment_workload_projection,
    build_operator_review_case_closure_packet,
    build_operator_review_case_evidence_links_projection,
    build_operator_review_case_list_response,
    build_operator_review_case_mutation_response,
    build_operator_review_case_queue_projection,
    build_operator_review_case_record,
    build_operator_review_case_rollup_metrics,
    build_operator_review_case_sla_policy_projection,
    build_operator_review_case_timeline_projection,
    build_operator_review_case_workbench_detail_projection,
    default_operator_review_case_store,
    emit_operator_review_case_action_event,
    emit_operator_review_case_event,
    operator_review_case_action_id,
    operator_review_case_action_metadata,
    operator_review_case_action_request_signature,
    operator_review_case_assignment_ref,
    operator_review_case_idempotency_signature,
    operator_review_case_metadata,
    operator_review_case_source_ref,
    register_operator_review_case_routes,
    required_case_action_idempotency_key,
    required_case_idempotency_key,
)
from nex_ag.operator_reviews import (
    OperatorEvidenceExportStore,
    OperatorReviewNoteStore,
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


def sample_action_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "action_type": "ACKNOWLEDGE",
        "operator_ref": {
            "operator_type": "user",
            "operator_id": "employee-0001",
            "tenant_id": "local-tenant",
        },
        "reason_codes": ["operator_review_follow_up"],
        "action_comment": "Operator acknowledged the review case.",
        "metadata": {"source_view": "operator_review_case_detail"},
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


def sample_note_record(**overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "operator_note_schema_version": "ag_operator_review_note.v1",
        "operator_note_id": "note-0662-a",
        "target_service": "nex-ag",
        "target_kind": "operator_review_workbench",
        "target_id": "target-0642",
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "operator_ref": {
            "operator_type": "user",
            "operator_id": "employee-0662",
            "tenant_id": "local-tenant",
        },
        "note_status": "ACTIVE",
        "note_type": "FOLLOW_UP",
        "severity": "HIGH",
        "operator_note_hash": sha256_text("raw-secret-note-0662"),
        "operator_note_preview": "Bounded note preview.",
        "reason_codes": ["operator_review_follow_up"],
        "metadata": {
            "raw_operator_note_stored": False,
            "storage_path": "/tmp/raw-note-should-not-leak",
            "idempotency_key_hash": sha256_text("idem-note-should-not-leak"),
        },
        "raw_operator_note": "raw-secret-note-0662",
        "created_at": "2026-09-11T00:01:00Z",
        "updated_at": "2026-09-11T00:03:00Z",
    }
    record.update(overrides)
    return record


def sample_evidence_export_record(**overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "export_schema_version": "ag_redacted_evidence_export.v1",
        "export_id": "export-0662-a",
        "target_service": "nex-ag",
        "target_kind": "operator_review_workbench",
        "target_id": "target-0642",
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "operator_ref": {
            "operator_type": "user",
            "operator_id": "employee-0662",
            "tenant_id": "local-tenant",
        },
        "export_status": "READY",
        "export_format": "json",
        "redaction_profile": "ag_redacted_manifest_v1",
        "evidence_manifest": {
            "items": [
                {
                    "evidence_type": "operator_note",
                    "raw_evidence_body": "raw-export-body-should-not-leak",
                }
            ]
        },
        "evidence_hash": sha256_text("redacted-export-0662"),
        "evidence_item_count": 1,
        "metadata": {
            "storage_uri": "s3://private/raw-export-should-not-leak",
            "database_url": "postgresql://secret-should-not-leak",
        },
        "created_at": "2026-09-11T00:02:00Z",
        "updated_at": "2026-09-11T00:02:30Z",
    }
    record.update(overrides)
    return record


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
    note_store: Any | None = None,
    export_store: Any | None = None,
    audit_event_store: InMemoryOperationalEventStore | None = None,
) -> tuple[TestClient, Any, InMemoryOperationalEventStore]:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    selected_store = store or OperatorReviewCaseStore()
    selected_event_store = audit_event_store or InMemoryOperationalEventStore()
    register_operator_review_case_routes(
        app,
        store=selected_store,
        note_store=note_store,
        export_store=export_store,
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


def test_case_rollup_metrics_correlate_actions_and_attention_safely() -> None:
    service = OperatorReviewCaseService(OperatorReviewCaseStore())
    open_case = service.create_case(
        sample_case_payload(
            assignment_ref=None,
            case_priority="HIGH",
            metadata={"debug_source": "rollup"},
        ),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0646-open-case",
    )["case"]
    urgent_case = service.create_case(
        sample_case_payload(
            case_priority="URGENT",
            assignment_ref={
                "assignee_type": "user",
                "assignee_id": "employee-0646",
            },
        ),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0646-urgent-case",
    )["case"]
    resolved = service.create_case(
        sample_case_payload(
            case_status="RESOLVED",
            case_priority="LOW",
            resolution_comment="Closed with a hash only summary.",
        ),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0646-resolved-case",
    )["case"]

    assigned = service.apply_action(
        urgent_case["case_id"],
        sample_action_payload(
            action_type="ASSIGN",
            assignment_ref={
                "assignee_type": "user",
                "assignee_id": "employee-0646",
            },
            action_comment="Assign this urgent case without leaking raw text.",
        ),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0646-assign",
    )
    case_list = service.list_cases(request_id=REQUEST_ID, trace_id=TRACE_ID)

    rollup = build_operator_review_case_rollup_metrics(case_list)

    assert rollup["rollup_schema_version"] == OPERATOR_REVIEW_CASE_ROLLUP_SCHEMA_VERSION
    assert rollup["summary"] == {
        "case_count": 3,
        "open_case_count": 2,
        "closed_case_count": 1,
        "assigned_case_count": 1,
        "urgent_case_count": 1,
        "unassigned_open_case_count": 1,
        "actioned_case_count": 1,
        "attention_case_count": 2,
        "latest_updated_at": case_list["summary"]["latest_updated_at"],
    }
    assert rollup["by_case_status"] == {"ASSIGNED": 1, "RESOLVED": 1, "OPEN": 1}
    assert rollup["by_case_priority"] == {"URGENT": 1, "LOW": 1, "HIGH": 1}
    assert rollup["by_last_action_type"] == {"ASSIGN": 1}
    assert rollup["attention"]["by_status"] == {"BLOCKED": 1, "OPEN": 1}
    assert rollup["attention"]["items"][0]["case_id"] == assigned["case"]["case_id"]
    assert rollup["attention"]["items"][0]["last_action_type"] == "ASSIGN"
    assert rollup["attention"]["items"][1]["case_id"] == open_case["case_id"]
    assert resolved["case_id"] not in {
        item["case_id"] for item in rollup["attention"]["items"]
    }
    assert rollup["redaction"]["idempotency_keys_included"] is False
    serialized = json.dumps(rollup)
    assert "Assign this urgent case" not in serialized
    assert "Closed with a hash only summary." not in serialized
    assert "idem-0646" not in serialized


def test_case_rollup_metrics_handles_reopened_cases_and_malformed_last_action() -> None:
    reopened = build_case(
        sample_case_payload(
            case_id="case-reopened-rollup",
            case_status="REOPENED",
            assignment_ref={
                "assignee_type": "user",
                "assignee_id": "employee-reopen",
            },
        )
    )
    reopened["metadata"]["last_action"] = {
        "request_signature": {"case_id": "case-reopened-rollup"},
        "record": {
            "action_id": "action-reopened-rollup",
            "action_type": "REOPEN",
            "from_status": "RESOLVED",
            "to_status": "REOPENED",
            "acted_at": "2026-09-11T05:00:00Z",
            "operator_ref": "malformed-operator-ref",
            "assignment_ref": {"assignee_id": "employee-reopen"},
            "reason_codes": ["operator_requested_reopen"],
            "action_comment_hash": sha256_text("safe reopen summary"),
            "resolution_hash": None,
        },
    }
    case_list = build_operator_review_case_list_response(
        [reopened],
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    rollup = build_operator_review_case_rollup_metrics(case_list)

    assert rollup["summary"]["case_count"] == 1
    assert rollup["summary"]["actioned_case_count"] == 1
    assert rollup["attention"]["by_status"] == {"ATTENTION": 1}
    assert rollup["attention"]["items"][0]["reason_codes"] == [
        "reopened_case_requires_review"
    ]
    assert rollup["attention"]["items"][0]["recommended_actions"] == [
        "review_reopened_case"
    ]
    assert rollup["by_last_action_type"] == {"REOPEN": 1}


def test_case_queue_projection_prioritizes_attention_and_redacts_payloads() -> None:
    service = OperatorReviewCaseService(OperatorReviewCaseStore())
    open_case = service.create_case(
        sample_case_payload(
            case_id="case-queue-open",
            assignment_ref=None,
            case_priority="MEDIUM",
        ),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0652-open",
    )["case"]
    urgent_case = service.create_case(
        sample_case_payload(
            case_id="case-queue-urgent",
            case_priority="URGENT",
            assignment_ref={
                "assignee_type": "user",
                "assignee_id": "employee-0652",
                "tenant_id": "local-tenant",
            },
        ),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0652-urgent",
    )["case"]
    resolved_case = service.create_case(
        sample_case_payload(
            case_id="case-queue-resolved",
            case_status="RESOLVED",
            case_priority="LOW",
            resolution_comment="Queue projection should keep only a preview.",
        ),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0652-resolved",
    )["case"]
    assigned = service.apply_action(
        urgent_case["case_id"],
        sample_action_payload(
            action_type="ASSIGN",
            assignment_ref={
                "assignee_type": "user",
                "assignee_id": "employee-0652",
                "tenant_id": "local-tenant",
            },
            action_comment="Queue projection must not leak this raw action comment.",
        ),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0652-action",
    )

    case_list = build_operator_review_case_list_response(
        [open_case, assigned["case"], resolved_case],
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    queue = build_operator_review_case_queue_projection(case_list)

    assert queue["case_queue_schema_version"] == OPERATOR_REVIEW_CASE_QUEUE_SCHEMA_VERSION
    assert queue["summary"] == {
        "case_count": 3,
        "open_case_count": 2,
        "closed_case_count": 1,
        "assigned_case_count": 1,
        "urgent_case_count": 1,
        "attention_case_count": 2,
        "unassigned_open_case_count": 1,
        "by_attention_status": {"BLOCKED": 1, "OPEN": 1, "OK": 1},
        "by_case_status": {"ASSIGNED": 1, "OPEN": 1, "RESOLVED": 1},
        "by_case_priority": {"URGENT": 1, "MEDIUM": 1, "LOW": 1},
        "latest_updated_at": max(
            assigned["case"]["updated_at"],
            open_case["updated_at"],
            resolved_case["updated_at"],
        ),
    }
    assert [item["case_id"] for item in queue["items"]] == [
        assigned["case"]["case_id"],
        open_case["case_id"],
        resolved_case["case_id"],
    ]
    assert queue["items"][0]["attention_status"] == "BLOCKED"
    assert queue["items"][0]["latest_action"]["action_type"] == "ASSIGN"
    assert queue["items"][0]["recommended_actions"] == [
        "prioritize_urgent_operator_review_case",
        "resolve_or_dismiss_after_review",
    ]
    assert queue["items"][1]["attention_reason_codes"] == [
        "open_case_requires_triage",
        "open_case_unassigned",
    ]
    assert queue["items"][2]["attention_status"] == "OK"
    assert queue["paths"]["case_queue_path"] == "/admin/v1/operator-review/cases/queue"
    assert queue["redaction"]["action_history_shape"] == "operational_events_first"

    serialized = json.dumps(queue)
    assert "Queue projection must not leak" not in serialized
    assert "idem-0652" not in serialized
    assert '"action_comment":' not in serialized


def test_case_queue_projection_handles_empty_and_malformed_refs() -> None:
    malformed = build_case(sample_case_payload(case_id="case-queue-malformed"))
    malformed["assignment_ref"] = "bad-assignment"
    malformed["source_ref"] = "bad-source"
    malformed["operator_ref"] = "bad-operator"

    empty = build_operator_review_case_queue_projection(
        build_operator_review_case_list_response(
            [],
            request_id=REQUEST_ID,
            trace_id=None,
        )
    )
    queue = build_operator_review_case_queue_projection(
        build_operator_review_case_list_response(
            [malformed],
            request_id=REQUEST_ID,
            trace_id=None,
        )
    )

    assert empty["summary"]["latest_updated_at"] is None
    assert empty["items"] == []
    assert queue["items"][0]["operator_ref"] == {
        "operator_type": None,
        "operator_id": None,
        "tenant_id": None,
    }
    assert queue["items"][0]["assignment_ref"] == {
        "assignee_type": None,
        "assignee_id": None,
        "tenant_id": None,
    }
    assert queue["items"][0]["source_ref"] == {
        "source_type": None,
        "source_id": None,
        "source_service": None,
        "workbench_path": None,
    }
    assert build_operator_review_case_queue_projection(
        build_operator_review_case_list_response(
            [{**malformed, "case_priority": None}],
            request_id=REQUEST_ID,
            trace_id=None,
        ),
        sort_by="priority",
    )["items"][0]["case_priority"] is None


def test_case_queue_projection_filters_searches_and_sorts() -> None:
    service = OperatorReviewCaseService(OperatorReviewCaseStore())
    open_case = service.create_case(
        sample_case_payload(
            case_id="case-0653-open",
            assignment_ref=None,
            case_priority="MEDIUM",
            target_ref={
                "target_service": "nex-ag",
                "target_kind": "operator_review_workbench",
                "target_id": "target-0653-open",
            },
        ),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0653-open",
    )["case"]
    urgent_case = service.create_case(
        sample_case_payload(
            case_id="case-0653-urgent",
            case_priority="URGENT",
            assignment_ref={
                "assignee_type": "user",
                "assignee_id": "employee-0653",
                "tenant_id": "local-tenant",
            },
        ),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0653-urgent",
    )["case"]
    resolved_case = service.create_case(
        sample_case_payload(
            case_id="case-0653-resolved",
            case_status="RESOLVED",
            case_priority="LOW",
            target_ref={
                "target_service": "nex-cx",
                "target_kind": "retrieval_package",
                "target_id": "retrieval-0653",
            },
            resolution_comment="safe searchable resolution preview",
        ),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0653-resolved",
    )["case"]
    assigned = service.apply_action(
        urgent_case["case_id"],
        sample_action_payload(
            action_type="ASSIGN",
            assignment_ref={
                "assignee_type": "user",
                "assignee_id": "employee-0653",
            },
        ),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0653-action",
    )["case"]
    case_list = build_operator_review_case_list_response(
        [open_case, assigned, resolved_case],
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    filtered = build_operator_review_case_queue_projection(
        case_list,
        latest_action_type="ASSIGN",
        attention_status="BLOCKED",
        search="employee-0653",
        sort_by="updated_at",
        sort_direction="desc",
    )
    priority_sorted = build_operator_review_case_queue_projection(
        case_list,
        sort_by="priority",
        sort_direction="desc",
    )
    status_sorted = build_operator_review_case_queue_projection(
        case_list,
        sort_by="status",
        sort_direction="asc",
    )
    case_id_sorted = build_operator_review_case_queue_projection(
        case_list,
        sort_by="case_id",
        sort_direction="desc",
    )
    search_resolved = build_operator_review_case_queue_projection(
        case_list,
        search="retrieval-0653",
    )

    assert filtered["filters"] == {
        "latest_action_type": "ASSIGN",
        "attention_status": "BLOCKED",
        "q": "employee-0653",
    }
    assert filtered["sort"] == {"sort_by": "updated_at", "sort_direction": "desc"}
    assert [item["case_id"] for item in filtered["items"]] == [assigned["case_id"]]
    assert [item["case_priority"] for item in priority_sorted["items"]] == [
        "URGENT",
        "MEDIUM",
        "LOW",
    ]
    assert [item["case_status"] for item in status_sorted["items"]] == [
        "ASSIGNED",
        "OPEN",
        "RESOLVED",
    ]
    assert [item["case_id"] for item in case_id_sorted["items"]] == sorted(
        [open_case["case_id"], assigned["case_id"], resolved_case["case_id"]],
        reverse=True,
    )
    assert [item["case_id"] for item in search_resolved["items"]] == [
        resolved_case["case_id"]
    ]
    assert _case_queue_item_matches_query(filtered["items"][0], " ") is True
    assert (
        _case_queue_item_matches_query(
            {**filtered["items"][0], "latest_action": "bad-action-shape"},
            assigned["case_id"],
        )
        is True
    )


@pytest.mark.parametrize(
    ("kwargs", "error_code"),
    [
        (
            {"attention_status": "STALE"},
            "ag.operator_review_note_attention_status_unsupported",
        ),
        (
            {"latest_action_type": "ESCALATE"},
            "ag.operator_review_note_latest_action_type_unsupported",
        ),
        ({"sort_by": "age"}, "ag.operator_review_note_sort_by_unsupported"),
        (
            {"sort_direction": "sideways"},
            "ag.operator_review_note_sort_direction_unsupported",
        ),
    ],
)
def test_case_queue_projection_rejects_invalid_controls(
    kwargs: dict[str, str],
    error_code: str,
) -> None:
    case_list = build_operator_review_case_list_response(
        [build_case()],
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    with pytest.raises(OperatorReviewNoteError) as exc:
        build_operator_review_case_queue_projection(case_list, **kwargs)

    assert exc.value.status_code == 422
    assert exc.value.error_code == error_code


def test_case_sla_policy_projection_exposes_read_model_policy_only() -> None:
    policy = build_operator_review_case_sla_policy_projection(
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert policy["case_sla_policy_schema_version"] == (
        OPERATOR_REVIEW_CASE_SLA_POLICY_SCHEMA_VERSION
    )
    assert policy["policy_id"] == "operator_review_case_sla_default_v1"
    assert policy["trace_id"] == TRACE_ID
    assert policy["evaluation"] == {
        "mode": "read_model_only",
        "clock": "utc",
        "terminal_statuses": ["RESOLVED", "DISMISSED"],
        "open_statuses": ["OPEN", "ACKNOWLEDGED", "ASSIGNED", "REOPENED"],
        "notification_delivery": "deferred",
        "external_incident_sync": "deferred",
        "escalation_persistence": "read_model_first",
    }
    assert [item["priority"] for item in policy["rules"]] == [
        "LOW",
        "MEDIUM",
        "HIGH",
        "URGENT",
    ]
    urgent = policy["rules"][-1]
    assert urgent["sla_class"] == "immediate_operator_attention"
    assert urgent["warning_after_seconds"] == 900
    assert urgent["overdue_after_seconds"] == 3600
    assert urgent["escalation_level"] == "BLOCKED"
    assert policy["summary"] == {
        "rule_count": 4,
        "priority_order": ["LOW", "MEDIUM", "HIGH", "URGENT"],
        "minimum_warning_after_seconds": 900,
        "minimum_overdue_after_seconds": 3600,
    }
    assert {
        item["reason_code"]: item["recommended_action"]
        for item in policy["reason_mappings"]
    } == {
        "urgent_case_not_closed": "prioritize_urgent_operator_review_case",
        "open_case_unassigned": "assign_case_owner",
        "reopened_case_requires_review": "review_reopened_case",
        "assigned_case_in_progress": "resolve_or_dismiss_after_review",
    }
    assert policy["paths"]["case_sla_policy_path"] == (
        "/admin/v1/operator-review/cases/sla-policy"
    )
    assert policy["paths"]["case_escalations_path"] == (
        "/admin/v1/operator-review/cases/escalations"
    )
    assert policy["redaction"]["policy_payload_shape"] == (
        "priority_thresholds_reason_mappings_only"
    )
    serialized = json.dumps(policy)
    assert "nuri1004" not in serialized
    assert "/data/nex-platform" not in serialized


def test_case_sla_policy_service_wrapper() -> None:
    service = OperatorReviewCaseService(OperatorReviewCaseStore())

    policy = service.get_case_sla_policy(
        request_id=REQUEST_ID,
        trace_id=None,
    )

    assert policy["case_sla_policy_schema_version"] == (
        OPERATOR_REVIEW_CASE_SLA_POLICY_SCHEMA_VERSION
    )
    assert policy["trace_id"] is None
    assert policy["summary"]["rule_count"] == 4


def test_case_aging_projection_computes_sla_state_and_stale_assignment() -> None:
    urgent = build_case(
        sample_case_payload(
            case_id="case-0683-urgent",
            case_priority="URGENT",
            assignment_ref={
                "assignee_type": "user",
                "assignee_id": "employee-0683",
                "tenant_id": "local-tenant",
            },
        ),
        idempotency_key="idem-0683-urgent",
        created_at="2026-09-11T00:00:00Z",
    )
    assigned, _action = apply_operator_review_case_action(
        urgent,
        sample_action_payload(
            action_type="ASSIGN",
            assignment_ref={
                "assignee_type": "user",
                "assignee_id": "employee-0683",
                "tenant_id": "local-tenant",
            },
        ),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0683-assign",
        acted_at="2026-09-11T00:00:00Z",
    )
    warning_case = build_case(
        sample_case_payload(
            case_id="case-0683-warning",
            case_status="ACKNOWLEDGED",
            case_priority="HIGH",
            assignment_ref=None,
        ),
        idempotency_key="idem-0683-warning",
        created_at="2026-09-12T06:00:00Z",
    )
    malformed = {
        **build_case(
            sample_case_payload(
                case_id="case-0683-malformed",
                case_status="OPEN",
                case_priority="LOW",
                assignment_ref=None,
            ),
            idempotency_key="idem-0683-malformed",
            created_at="not-a-date",
        ),
        "updated_at": "also-not-a-date",
    }
    closed = build_case(
        sample_case_payload(
            case_id="case-0683-closed",
            case_status="RESOLVED",
            case_priority="MEDIUM",
            assignment_ref=None,
            resolution_text="Closed for aging projection.",
            closed_at="2026-09-11T02:00:00Z",
        ),
        idempotency_key="idem-0683-closed",
        created_at="2026-09-11T00:00:00Z",
    )
    case_list = build_operator_review_case_list_response(
        [assigned, warning_case, malformed, closed],
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    aging = build_operator_review_case_aging_projection(
        case_list,
        now="2026-09-12T12:00:00Z",
    )

    assert aging["case_aging_schema_version"] == OPERATOR_REVIEW_CASE_AGING_SCHEMA_VERSION
    assert aging["policy_id"] == "operator_review_case_sla_default_v1"
    assert aging["reference_time"] == "2026-09-12T12:00:00Z"
    assert aging["summary"] == {
        "case_count": 4,
        "open_case_count": 3,
        "closed_case_count": 1,
        "watch_case_count": 1,
        "warning_case_count": 1,
        "overdue_case_count": 1,
        "stale_assignment_count": 1,
        "max_age_seconds": 129600,
    }
    by_case_id = {item["case_id"]: item for item in aging["items"]}
    assert by_case_id["case-0683-urgent"]["sla_state"] == "OVERDUE"
    assert by_case_id["case-0683-urgent"]["stale_assignment"] is True
    assert by_case_id["case-0683-urgent"]["inactivity_seconds"] == 129600
    assert by_case_id["case-0683-warning"]["sla_state"] == "WARNING"
    assert by_case_id["case-0683-malformed"]["age_seconds"] == 0
    assert by_case_id["case-0683-malformed"]["sla_state"] == "WATCH"
    assert by_case_id["case-0683-closed"]["closed"] is True
    assert by_case_id["case-0683-closed"]["sla_state"] == "CLOSED"
    assert by_case_id["case-0683-closed"]["age_seconds"] == 7200
    assert aging["items"][0]["case_id"] == "case-0683-urgent"
    assert aging["paths"]["case_aging_path"] == "/admin/v1/operator-review/cases/aging"
    assert aging["redaction"]["aging_payload_shape"] == (
        "timestamps_thresholds_and_safe_refs_only"
    )
    serialized = json.dumps(aging)
    assert "Closed for aging projection" not in serialized
    assert "idem-0683" not in serialized


def test_case_aging_service_wrapper_defaults_reference_time() -> None:
    service = OperatorReviewCaseService(OperatorReviewCaseStore())
    service.create_case(
        sample_case_payload(case_id="case-0683-service", case_priority="MEDIUM"),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0683-service",
    )

    aging = service.aging_cases(
        request_id=REQUEST_ID,
        trace_id=None,
        now="2026-09-11T01:00:00Z",
    )

    assert aging["case_aging_schema_version"] == OPERATOR_REVIEW_CASE_AGING_SCHEMA_VERSION
    assert aging["trace_id"] is None
    assert aging["summary"]["case_count"] == 1
    assert aging["items"][0]["reference_time"] == "2026-09-11T01:00:00Z"


def test_case_aging_projection_handles_ok_and_timestamp_edges() -> None:
    ok_case = build_case(
        sample_case_payload(
            case_id="case-0683-ok",
            case_status="ACKNOWLEDGED",
            case_priority="LOW",
            assignment_ref={
                "assignee_type": "user",
                "assignee_id": "employee-0683-ok",
                "tenant_id": "local-tenant",
            },
        ),
        idempotency_key="idem-0683-ok",
        created_at="2026-09-12T11:59:00",
    )
    case_list = build_operator_review_case_list_response(
        [ok_case],
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    aging = build_operator_review_case_aging_projection(
        case_list,
        now="2026-09-12T12:00:00Z",
    )

    assert aging["items"][0]["sla_state"] == "OK"
    assert aging["items"][0]["age_seconds"] == 60
    assert _case_elapsed_seconds(None, "2026-09-12T12:00:00Z") == 0
    assert _case_elapsed_seconds(
        "2026-09-12T11:00:00",
        "2026-09-12T12:00:00Z",
    ) == 3600
    assert _case_elapsed_seconds(
        "2026-09-12T13:00:00Z",
        "2026-09-12T12:00:00Z",
    ) == 0
    assert _case_sla_state_sort_rank("UNKNOWN") == 5


def test_case_workbench_detail_projection_exposes_safe_action_controls() -> None:
    service = OperatorReviewCaseService(OperatorReviewCaseStore())
    created = service.create_case(
        sample_case_payload(
            case_id="case-0654-detail",
            case_priority="URGENT",
            assignment_ref=None,
        ),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0654-detail",
    )["case"]
    assigned = service.apply_action(
        created["case_id"],
        sample_action_payload(
            action_type="ASSIGN",
            action_comment="Assigning this case for workbench detail review.",
            assignment_ref={
                "assignee_type": "user",
                "assignee_id": "employee-0654",
            },
        ),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0654-action",
    )["case"]

    detail = build_operator_review_case_workbench_detail_projection(
        assigned,
        operator_note_records=[sample_note_record()],
        evidence_export_records=[sample_evidence_export_record()],
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        evidence_source_status="READY",
    )

    assert detail["case_workbench_detail_schema_version"] == (
        OPERATOR_REVIEW_CASE_WORKBENCH_DETAIL_SCHEMA_VERSION
    )
    assert detail["case"]["case_id"] == created["case_id"]
    assert detail["case"]["attention_status"] == "BLOCKED"
    assert detail["case"]["assignment_ref"]["assignee_id"] == "employee-0654"
    assert detail["latest_action"]["action_type"] == "ASSIGN"
    assert detail["latest_action"]["assignee_id"] == "employee-0654"
    assert [item["action_type"] for item in detail["action_controls"]["available_actions"]] == [
        "ASSIGN",
        "RESOLVE",
        "DISMISS",
    ]
    assert [item["action_type"] for item in detail["action_controls"]["blocked_actions"]] == [
        "ACKNOWLEDGE",
        "REOPEN",
    ]
    assert detail["action_controls"]["available_action_count"] == 3
    assert detail["action_controls"]["blocked_actions"][0]["blocked_reason"] == (
        "ACKNOWLEDGE cannot transition from ASSIGNED."
    )
    assert detail["action_controls"]["available_actions"][0][
        "requires_assignment_ref"
    ] is True
    assert detail["action_controls"]["available_actions"][1][
        "requires_resolution_comment"
    ] is True
    assert detail["evidence_links"]["planned_schema_version"] == (
        OPERATOR_REVIEW_CASE_EVIDENCE_LINKS_SCHEMA_VERSION
    )
    assert detail["evidence_links"]["inline_items_included"] is False
    assert detail["evidence_links"]["summary"]["evidence_source_status"] == "READY"
    assert detail["evidence_links"]["summary"]["total_link_count"] == 2
    assert detail["action_admission"]["planned_schema_version"] == (
        OPERATOR_REVIEW_CASE_ACTION_ADMISSION_SCHEMA_VERSION
    )
    assert detail["action_admission"]["inline_items_included"] is False
    assert detail["action_admission"]["summary"]["admitted_action_count"] == 3
    assert detail["action_admission"]["links"]["case_action_admission_path"] == (
        f"/admin/v1/operator-review/cases/{created['case_id']}/action-admission"
    )
    assert detail["timeline"]["action_history_shape"] == "operational_events_first"
    assert detail["links"]["case_evidence_links_path"] == (
        f"/admin/v1/operator-review/cases/{created['case_id']}/evidence-links"
    )
    assert detail["links"]["case_action_admission_path"] == (
        f"/admin/v1/operator-review/cases/{created['case_id']}/action-admission"
    )
    assert detail["redaction"]["metadata_payload_included"] is False

    serialized = json.dumps(detail)
    assert "Assigning this case" not in serialized
    assert "idem-0654" not in serialized
    assert '"action_comment":' not in serialized
    assert "raw-secret-note-0662" not in serialized
    assert "raw-export-body-should-not-leak" not in serialized


def test_case_workbench_detail_projection_handles_closed_and_malformed_source() -> None:
    resolved = build_case(
        sample_case_payload(
            case_status="RESOLVED",
            resolution_comment="Closed with bounded preview only.",
        )
    )
    resolved["source_ref"] = "bad-source"
    detail = build_operator_review_case_workbench_detail_projection(
        resolved,
        request_id=REQUEST_ID,
        trace_id=None,
    )
    malformed = {
        **resolved,
        "case_status": "UNKNOWN",
        "case_id": "case-0654-malformed",
    }
    malformed_detail = build_operator_review_case_workbench_detail_projection(
        malformed,
        request_id=REQUEST_ID,
        trace_id=None,
    )

    assert detail["trace_id"] is None
    assert detail["case"]["source_ref"] == {
        "source_type": None,
        "source_id": None,
        "source_service": None,
        "workbench_path": None,
    }
    assert detail["resolution"]["resolution_hash"] == resolved["resolution_hash"]
    assert detail["resolution"]["resolution_preview"] == "Closed with bounded preview only."
    assert detail["action_controls"]["available_actions"][0]["action_type"] == "REOPEN"
    assert malformed_detail["action_controls"]["available_actions"] == []
    assert malformed_detail["action_controls"]["blocked_action_count"] == 5
    assert malformed_detail["action_controls"]["blocked_actions"][0][
        "blocked_reason"
    ] == "ACKNOWLEDGE cannot transition from UNKNOWN."


def test_case_evidence_links_projection_filters_sorts_and_redacts() -> None:
    case = build_case()
    matching_note = sample_note_record()
    matching_export = sample_evidence_export_record()
    unrelated_note = sample_note_record(
        operator_note_id="note-0662-other",
        target_id="target-other",
        updated_at="2026-09-11T00:04:00Z",
    )
    unrelated_export = sample_evidence_export_record(
        export_id="export-0662-other",
        target_service="nex-cx",
        updated_at="2026-09-11T00:05:00Z",
    )

    projection = build_operator_review_case_evidence_links_projection(
        case,
        operator_note_records=[unrelated_note, matching_note],
        evidence_export_records=[unrelated_export, matching_export],
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert projection["case_evidence_links_schema_version"] == (
        OPERATOR_REVIEW_CASE_EVIDENCE_LINKS_SCHEMA_VERSION
    )
    assert projection["case"]["case_id"] == case["case_id"]
    assert projection["summary"]["operator_note_count"] == 1
    assert projection["summary"]["redacted_evidence_export_count"] == 1
    assert projection["summary"]["total_link_count"] == 2
    assert [item["link_type"] for item in projection["items"]] == [
        "operator_review_note",
        "redacted_evidence_export",
    ]
    assert projection["items"][0]["detail_path"].endswith("/notes/note-0662-a")
    assert projection["items"][1]["detail_path"].endswith(
        "/evidence-exports/export-0662-a"
    )
    assert projection["redaction"]["metadata_payload_included"] is False
    assert projection["redaction"]["evidence_payload_shape"] == (
        "safe_refs_hashes_and_bounded_previews_only"
    )

    serialized = json.dumps(projection)
    assert "raw-secret-note-0662" not in serialized
    assert "raw-export-body-should-not-leak" not in serialized
    assert "raw-note-should-not-leak" not in serialized
    assert "postgresql://secret-should-not-leak" not in serialized
    assert "idem-note-should-not-leak" not in serialized
    assert "evidence_manifest" not in serialized
    assert '"metadata":' not in serialized


def test_case_evidence_links_projection_handles_empty_limit_and_missing_ids() -> None:
    case = build_case()
    note_without_id = sample_note_record(
        operator_note_id=None,
        updated_at="2026-09-11T00:04:00Z",
    )
    export_without_id = sample_evidence_export_record(
        export_id=None,
        evidence_item_count=None,
        updated_at="2026-09-11T00:05:00Z",
    )

    limited = build_operator_review_case_evidence_links_projection(
        case,
        operator_note_records=[note_without_id],
        evidence_export_records=[export_without_id],
        request_id=REQUEST_ID,
        trace_id=None,
        limit=1,
        source_status="READY",
    )
    empty = build_operator_review_case_evidence_links_projection(
        case,
        operator_note_records=[],
        evidence_export_records=[],
        request_id=REQUEST_ID,
        trace_id=None,
        source_status="NOT_CONFIGURED",
    )

    assert limited["trace_id"] is None
    assert limited["summary"]["total_link_count"] == 2
    assert limited["summary"]["returned_link_count"] == 1
    assert limited["items"][0]["link_type"] == "redacted_evidence_export"
    assert limited["items"][0]["link_id"] is None
    assert limited["items"][0]["detail_path"] is None
    assert limited["items"][0]["evidence_item_count"] == 0
    assert empty["summary"]["evidence_source_status"] == "NOT_CONFIGURED"
    assert empty["summary"]["latest_updated_at"] is None
    assert empty["items"] == []


def test_case_service_evidence_links_reads_target_scoped_stores() -> None:
    class CapturingNoteStore:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def list_notes(self, **kwargs: Any) -> list[dict[str, Any]]:
            self.calls.append(kwargs)
            return [sample_note_record()]

    class CapturingExportStore:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def list_exports(self, **kwargs: Any) -> list[dict[str, Any]]:
            self.calls.append(kwargs)
            return [sample_evidence_export_record()]

    case_store = OperatorReviewCaseStore()
    service = OperatorReviewCaseService(case_store)
    case = service.create_case(
        sample_case_payload(case_id="case-0662-service"),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0662-service",
    )["case"]
    note_store = CapturingNoteStore()
    export_store = CapturingExportStore()

    projection = service.get_case_evidence_links(
        case["case_id"],
        note_store=note_store,
        export_store=export_store,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        limit=3,
    )
    no_sources = service.get_case_evidence_links(
        case["case_id"],
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert note_store.calls == [
        {
            "target_service": "nex-ag",
            "target_kind": "operator_review_workbench",
            "target_id": "target-0642",
            "limit": 3,
        }
    ]
    assert export_store.calls == [
        {
            "target_service": "nex-ag",
            "target_kind": "operator_review_workbench",
            "target_id": "target-0642",
            "limit": 3,
        }
    ]
    assert projection["summary"]["evidence_source_status"] == "READY"
    assert projection["summary"]["returned_link_count"] == 2
    assert no_sources["summary"]["evidence_source_status"] == "NOT_CONFIGURED"
    assert no_sources["items"] == []


def test_case_service_workbench_detail_embeds_lightweight_evidence_and_admission() -> None:
    class CapturingNoteStore:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def list_notes(self, **kwargs: Any) -> list[dict[str, Any]]:
            self.calls.append(kwargs)
            return [sample_note_record()]

    case_store = OperatorReviewCaseStore()
    service = OperatorReviewCaseService(case_store)
    case = service.create_case(
        sample_case_payload(case_id="case-0666-service"),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0666-service",
    )["case"]
    note_store = CapturingNoteStore()

    detail = service.get_case_workbench_detail(
        case["case_id"],
        note_store=note_store,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        evidence_limit=1,
    )

    assert note_store.calls == [
        {
            "target_service": "nex-ag",
            "target_kind": "operator_review_workbench",
            "target_id": "target-0642",
            "limit": 1,
        }
    ]
    assert detail["evidence_links"]["summary"]["evidence_source_status"] == "PARTIAL"
    assert detail["evidence_links"]["summary"]["operator_note_count"] == 1
    assert detail["evidence_links"]["summary"]["redacted_evidence_export_count"] == 0
    assert detail["evidence_links"]["inline_items_included"] is False
    assert detail["action_admission"]["summary"]["preflight_only"] is True
    assert detail["action_admission"]["summary"]["admitted_action_count"] == 4


def test_case_action_admission_projection_lists_preflight_decisions() -> None:
    case = build_case(sample_case_payload(case_id="case-0664-open"))
    case["metadata"]["raw_prompt"] = "raw prompt should not leak"
    case["metadata"]["database_url"] = "postgresql://admission-secret"

    admission = build_operator_review_case_action_admission_projection(
        case,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert admission["case_action_admission_schema_version"] == (
        OPERATOR_REVIEW_CASE_ACTION_ADMISSION_SCHEMA_VERSION
    )
    assert admission["requested_action"] is None
    assert admission["summary"]["current_status"] == "OPEN"
    assert admission["summary"]["admitted_action_count"] == 4
    assert admission["summary"]["blocked_action_count"] == 1
    assert admission["summary"]["preflight_only"] is True
    assert admission["summary"]["mutation_route_authoritative"] is True
    by_action = {item["action_type"]: item for item in admission["items"]}
    assert by_action["ACKNOWLEDGE"]["admitted"] is True
    assert by_action["ASSIGN"]["requires_assignment_ref"] is True
    assert by_action["RESOLVE"]["requires_resolution_comment"] is True
    assert by_action["REOPEN"]["admitted"] is False
    assert by_action["REOPEN"]["blocked_reason"] == (
        "REOPEN cannot transition from OPEN."
    )

    serialized = json.dumps(admission)
    assert "raw prompt should not leak" not in serialized
    assert "postgresql://admission-secret" not in serialized
    assert '"metadata":' not in serialized


def test_case_action_admission_projection_handles_requested_and_closed_cases() -> None:
    resolved = build_case(
        sample_case_payload(
            case_id="case-0664-resolved",
            case_status="RESOLVED",
            resolution_comment="Raw resolution comment must not leak.",
        )
    )

    assign_admission = build_operator_review_case_action_admission_projection(
        resolved,
        request_id=REQUEST_ID,
        trace_id=None,
        action_type="ASSIGN",
    )
    reopen_admission = build_operator_review_case_action_admission_projection(
        resolved,
        request_id=REQUEST_ID,
        trace_id=None,
        action_type="REOPEN",
    )

    assert assign_admission["trace_id"] is None
    assert assign_admission["summary"]["requested_action_type"] == "ASSIGN"
    assert assign_admission["summary"]["requested_action_admitted"] is False
    assert assign_admission["requested_action"]["blocked_reason"] == (
        "ASSIGN cannot transition from RESOLVED."
    )
    assert assign_admission["summary"]["admitted_action_count"] == 0
    assert assign_admission["summary"]["blocked_action_count"] == 1
    assert reopen_admission["summary"]["requested_action_admitted"] is True
    assert reopen_admission["requested_action"]["target_status"] == "REOPENED"
    assert "Raw resolution comment" not in json.dumps(assign_admission)


def test_case_action_admission_service_and_invalid_action_type() -> None:
    service = OperatorReviewCaseService(OperatorReviewCaseStore())
    created = service.create_case(
        sample_case_payload(case_id="case-0664-service"),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0664-service",
    )["case"]

    admission = service.get_case_action_admission(
        created["case_id"],
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        action_type="RESOLVE",
    )

    assert admission["requested_action"]["action_type"] == "RESOLVE"
    assert admission["requested_action"]["admitted"] is True
    assert admission["requested_action"]["requires_resolution_comment"] is True
    with pytest.raises(OperatorReviewNoteError) as exc:
        service.get_case_action_admission(
            created["case_id"],
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
            action_type="ESCALATE",
        )
    assert exc.value.status_code == 422
    assert exc.value.error_code == "ag.operator_review_case_action_type_unsupported"


def test_case_timeline_projection_filters_and_redacts_operational_events() -> None:
    service = OperatorReviewCaseService(OperatorReviewCaseStore())
    event_store = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id="nex-ag", store=event_store)
    created = service.create_case(
        sample_case_payload(case_id="case-0655-timeline"),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0655-case",
    )["case"]
    emit_operator_review_case_event(emitter, created)
    assigned = service.apply_action(
        created["case_id"],
        sample_action_payload(
            action_type="ASSIGN",
            action_comment="Sensitive action comment should stay out.",
            assignment_ref={
                "assignee_type": "user",
                "assignee_id": "employee-0655",
            },
        ),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0655-action",
    )["case"]
    action = assigned["metadata"]["last_action"]["record"]
    emit_operator_review_case_action_event(emitter, action, assigned)
    resolved = service.apply_action(
        assigned["case_id"],
        sample_action_payload(
            action_type="RESOLVE",
            action_comment="Sensitive terminal action text should stay out.",
            resolution_comment="Sensitive resolution body should stay out.",
        ),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0655-resolve",
    )["case"]
    resolved_action = resolved["metadata"]["last_action"]["record"]
    emit_operator_review_case_action_event(emitter, resolved_action, resolved)
    emitter.emit(
        event_type="ag.unrelated",
        severity="INFO",
        message="Unrelated event.",
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
        subject_ref={"type": "other", "id": "other"},
        details={"case_id": "other"},
        created_at="2026-09-11T00:00:01Z",
    )

    timeline = build_operator_review_case_timeline_projection(
        resolved,
        event_store=event_store,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    limited = build_operator_review_case_timeline_projection(
        resolved,
        event_store=event_store,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        limit=1,
    )

    assert timeline["case_timeline_schema_version"] == (
        OPERATOR_REVIEW_CASE_TIMELINE_SCHEMA_VERSION
    )
    assert timeline["summary"]["timeline_status"] == "READY"
    assert timeline["summary"]["event_count"] == 3
    assert timeline["summary"]["case_recorded_event_count"] == 1
    assert timeline["summary"]["case_action_event_count"] == 2
    assert timeline["summary"]["status_transition_count"] == 2
    assert timeline["summary"]["assignment_action_count"] == 1
    assert timeline["summary"]["terminal_action_count"] == 1
    assert timeline["summary"]["first_event_at"] == timeline["items"][0]["created_at"]
    assert timeline["summary"]["latest_event_at"] == timeline["items"][2]["created_at"]
    assert [item["event_type"] for item in timeline["items"]] == [
        OPERATOR_REVIEW_CASE_RECORDED_EVENT_TYPE,
        OPERATOR_REVIEW_CASE_ACTION_RECORDED_EVENT_TYPE,
        OPERATOR_REVIEW_CASE_ACTION_RECORDED_EVENT_TYPE,
    ]
    assert [item["sequence"] for item in timeline["items"]] == [1, 2, 3]
    assert timeline["items"][0]["timeline_kind"] == "CASE_RECORDED"
    assert timeline["items"][0]["action_outcome"] == {
        "outcome_source": "operator_review_case_recorded_event",
        "action_id": None,
        "action_type": None,
        "from_status": None,
        "to_status": None,
        "status_changed": False,
        "assignment_changed": False,
        "resolution_recorded": False,
        "terminal_action": False,
    }
    assert timeline["items"][1]["details"]["action_type"] == "ASSIGN"
    assert timeline["items"][1]["details"]["assignee_id"] == "employee-0655"
    assert timeline["items"][1]["details"]["action_comment_hash"] == (
        action["action_comment_hash"]
    )
    assert timeline["items"][1]["timeline_kind"] == "CASE_ACTION"
    assert timeline["items"][1]["action_outcome"] == {
        "outcome_source": "operator_review_case_action_event",
        "action_id": action["action_id"],
        "action_type": "ASSIGN",
        "from_status": "OPEN",
        "to_status": "ASSIGNED",
        "status_changed": True,
        "assignment_changed": True,
        "resolution_recorded": False,
        "terminal_action": False,
    }
    assert timeline["items"][2]["details"]["action_type"] == "RESOLVE"
    assert timeline["items"][2]["details"]["resolution_hash"] == (
        resolved_action["resolution_hash"]
    )
    assert timeline["items"][2]["action_outcome"]["terminal_action"] is True
    assert timeline["items"][2]["action_outcome"]["resolution_recorded"] is True
    assert timeline["items"][2]["redaction"] == {
        "raw_event_details_included": False,
        "raw_case_comment_included": False,
        "raw_action_comment_included": False,
        "raw_resolution_comment_included": False,
        "raw_prompt_included": False,
        "raw_generation_output_included": False,
        "raw_source_text_included": False,
        "storage_paths_included": False,
        "provider_payloads_included": False,
        "database_urls_included": False,
        "tokens_included": False,
        "idempotency_keys_included": False,
        "metadata_payload_included": False,
        "timeline_item_payload_shape": "whitelisted_operational_event_fields",
    }
    assert limited["summary"]["event_count"] == 1
    serialized = json.dumps(timeline)
    assert "Sensitive action comment" not in serialized
    assert "Sensitive terminal action text" not in serialized
    assert "Sensitive resolution body" not in serialized
    assert "idem-0655" not in serialized
    assert '"action_comment":' not in serialized


def test_case_action_outcome_projection_summarizes_safe_lifecycle_facts() -> None:
    service = OperatorReviewCaseService(OperatorReviewCaseStore())
    event_store = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id="nex-ag", store=event_store)
    created = service.create_case(
        sample_case_payload(case_id="case-0673-outcomes", assignment_ref=None),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0673-case",
    )["case"]
    emit_operator_review_case_event(emitter, created)
    assigned = service.apply_action(
        created["case_id"],
        sample_action_payload(
            action_type="ASSIGN",
            action_comment="Raw assignment text must stay out.",
            assignment_ref={
                "assignee_type": "user",
                "assignee_id": "employee-0673",
            },
        ),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0673-assign",
    )["case"]
    emit_operator_review_case_action_event(
        emitter,
        assigned["metadata"]["last_action"]["record"],
        assigned,
    )
    resolved = service.apply_action(
        assigned["case_id"],
        sample_action_payload(
            action_type="RESOLVE",
            action_comment="Raw resolve action text must stay out.",
            resolution_comment="Raw resolution text must stay out.",
        ),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0673-resolve",
    )["case"]
    emit_operator_review_case_action_event(
        emitter,
        resolved["metadata"]["last_action"]["record"],
        resolved,
    )

    outcomes = build_operator_review_case_action_outcome_projection(
        resolved,
        event_store=event_store,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    limited = build_operator_review_case_action_outcome_projection(
        resolved,
        event_store=event_store,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        limit=1,
    )
    service_outcomes = service.get_case_action_outcomes(
        resolved["case_id"],
        event_store=event_store,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert outcomes["case_action_outcomes_schema_version"] == (
        OPERATOR_REVIEW_CASE_ACTION_OUTCOMES_SCHEMA_VERSION
    )
    assert outcomes["case"]["case_id"] == resolved["case_id"]
    assert outcomes["case"]["case_status"] == "RESOLVED"
    assert outcomes["case"]["assignment_ref"]["assignee_id"] == "employee-0673"
    assert outcomes["summary"]["outcome_status"] == "READY"
    assert outcomes["summary"]["action_count"] == 2
    assert outcomes["summary"]["status_transition_count"] == 2
    assert outcomes["summary"]["assignment_action_count"] == 1
    assert outcomes["summary"]["terminal_action_count"] == 1
    assert outcomes["summary"]["resolution_recorded_count"] == 1
    assert outcomes["summary"]["latest_action_type"] == "RESOLVE"
    assert outcomes["summary"]["latest_to_status"] == "RESOLVED"
    assert outcomes["summary"]["source_projection"] == (
        "case_timeline_operational_events"
    )
    assert [item["sequence"] for item in outcomes["items"]] == [2, 3]
    assert outcomes["items"][0]["action_type"] == "ASSIGN"
    assert outcomes["items"][0]["assignment_changed"] is True
    assert outcomes["items"][0]["operator_ref"] == {
        "operator_type": "user",
        "operator_id": "employee-0001",
    }
    assert outcomes["items"][0]["assignment_ref"]["assignee_id"] == "employee-0673"
    assert outcomes["items"][1]["terminal_action"] is True
    assert outcomes["items"][1]["resolution_recorded"] is True
    assert outcomes["items"][1]["redaction"]["raw_event_details_included"] is False
    assert limited["summary"]["action_count"] == 1
    assert service_outcomes["summary"] == outcomes["summary"]

    serialized = json.dumps(outcomes)
    assert "Raw assignment text" not in serialized
    assert "Raw resolve action text" not in serialized
    assert "Raw resolution text" not in serialized
    assert "idem-0673" not in serialized
    assert '"metadata":' not in serialized


def test_case_assignment_workload_projection_groups_safe_assignee_signals() -> None:
    service = OperatorReviewCaseService(OperatorReviewCaseStore())
    unassigned = service.create_case(
        sample_case_payload(
            case_id="case-0674-unassigned",
            case_priority="URGENT",
            assignment_ref=None,
        ),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0674-unassigned",
    )["case"]
    assigned = service.create_case(
        sample_case_payload(
            case_id="case-0674-assigned",
            assignment_ref={
                "assignee_type": "user",
                "assignee_id": "employee-0674",
                "tenant_id": "local-tenant",
            },
        ),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0674-assigned",
    )["case"]
    resolved = service.apply_action(
        assigned["case_id"],
        sample_action_payload(
            action_type="RESOLVE",
            action_comment="Raw workload action text should stay out.",
            resolution_comment="Raw workload resolution should stay out.",
        ),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0674-resolve",
    )["case"]
    case_list = build_operator_review_case_list_response(
        [unassigned, resolved],
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    workload = build_operator_review_case_assignment_workload_projection(case_list)
    service_workload = service.assignment_workload_cases(
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        limit=10,
    )

    assert workload["case_assignment_workload_schema_version"] == (
        OPERATOR_REVIEW_CASE_ASSIGNMENT_WORKLOAD_SCHEMA_VERSION
    )
    assert workload["summary"]["case_count"] == 2
    assert workload["summary"]["workload_group_count"] == 2
    assert workload["summary"]["assigned_workload_group_count"] == 1
    assert workload["summary"]["unassigned_case_count"] == 1
    assert workload["summary"]["open_case_count"] == 1
    assert workload["summary"]["closed_case_count"] == 1
    assert workload["summary"]["urgent_case_count"] == 1
    assert workload["summary"]["attention_case_count"] == 1
    assert workload["items"][0]["assignee_ref"] == {
        "assignee_type": None,
        "assignee_id": None,
        "tenant_id": None,
    }
    assert workload["items"][0]["blocked_case_count"] == 1
    assert workload["items"][0]["recommended_actions"] == [
        "acknowledge_or_assign_case",
        "assign_case_owner",
        "prioritize_urgent_operator_review_case",
    ]
    assert workload["items"][1]["assignee_ref"]["assignee_id"] == "employee-0674"
    assert workload["items"][1]["closed_case_count"] == 1
    assert workload["items"][1]["actioned_case_count"] == 1
    assert workload["items"][1]["by_last_action_type"] == {"RESOLVE": 1}
    assert service_workload["summary"] == workload["summary"]

    serialized = json.dumps(workload)
    assert "Raw workload action text" not in serialized
    assert "Raw workload resolution" not in serialized
    assert "idem-0674" not in serialized
    assert '"metadata":' not in serialized


def test_case_closure_packet_assembles_redaction_safe_lifecycle_evidence() -> None:
    service = OperatorReviewCaseService(OperatorReviewCaseStore())
    event_store = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id="nex-ag", store=event_store)
    created = service.create_case(
        sample_case_payload(case_id="case-0675-closure"),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0675-case",
    )["case"]
    emit_operator_review_case_event(emitter, created)
    resolved = service.apply_action(
        created["case_id"],
        sample_action_payload(
            action_type="RESOLVE",
            action_comment="Raw closure action text should stay out.",
            resolution_comment="Raw closure resolution should stay out.",
        ),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0675-resolve",
    )["case"]
    emit_operator_review_case_action_event(
        emitter,
        resolved["metadata"]["last_action"]["record"],
        resolved,
    )

    packet = build_operator_review_case_closure_packet(
        resolved,
        event_store=event_store,
        operator_note_records=[sample_note_record()],
        evidence_export_records=[sample_evidence_export_record()],
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        evidence_source_status="READY",
    )
    service_packet = service.get_case_closure_packet(
        resolved["case_id"],
        event_store=event_store,
        note_store=SimpleNamespace(
            list_notes=lambda **_: [sample_note_record()]
        ),
        export_store=SimpleNamespace(
            list_exports=lambda **_: [sample_evidence_export_record()]
        ),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    open_case = service.create_case(
        sample_case_payload(case_id="case-0675-open", assignment_ref=None),
        request_id=REQUEST_ID,
        trace_id=None,
        idempotency_key="idem-0675-open",
    )["case"]
    open_packet = build_operator_review_case_closure_packet(
        open_case,
        event_store=InMemoryOperationalEventStore(),
        operator_note_records=[],
        evidence_export_records=[],
        request_id=REQUEST_ID,
        trace_id=None,
    )

    assert packet["case_closure_packet_schema_version"] == (
        OPERATOR_REVIEW_CASE_CLOSURE_PACKET_SCHEMA_VERSION
    )
    assert packet["case"]["case_id"] == resolved["case_id"]
    assert packet["summary"]["closure_status"] == "CLOSED"
    assert packet["summary"]["closure_ready"] is True
    assert packet["summary"]["blocking_reason_count"] == 0
    assert packet["summary"]["terminal_action_count"] == 1
    assert packet["summary"]["evidence_link_count"] == 2
    assert packet["summary"]["timeline_event_count"] == 2
    assert packet["resolution"]["resolution_hash"] == resolved["resolution_hash"]
    assert packet["resolution"]["resolution_preview"] is None
    assert packet["resolution"]["resolution_preview_included"] is False
    assert packet["lifecycle"]["closure_state"] == {
        "closure_status": "CLOSED",
        "closure_ready": True,
        "blocking_reasons": [],
        "requires_persistence": False,
        "action_history_source": "service_operational_events",
        "evidence_source": "ag_op_notes_and_ag_ev_exports",
    }
    assert packet["lifecycle"]["action_outcomes"][0]["terminal_action"] is True
    assert packet["evidence"]["summary"]["total_link_count"] == 2
    assert service_packet["summary"] == packet["summary"]
    assert open_packet["trace_id"] is None
    assert open_packet["summary"]["closure_status"] == "OPEN"
    assert open_packet["summary"]["closure_ready"] is False
    assert open_packet["lifecycle"]["closure_state"]["blocking_reasons"] == [
        "case_not_closed",
        "terminal_action_missing",
        "resolution_hash_missing",
        "evidence_link_missing",
    ]

    serialized = json.dumps(packet)
    assert "Raw closure action text" not in serialized
    assert "Raw closure resolution" not in serialized
    assert "raw-secret-note-0662" not in serialized
    assert "raw-export-body-should-not-leak" not in serialized
    assert "idem-0675" not in serialized
    assert '"metadata":' not in serialized


def test_case_timeline_projection_reports_unavailable_source_and_subject_match() -> None:
    record = build_case(sample_case_payload(case_id="case-0655-subject"))
    event_store = InMemoryOperationalEventStore()
    event_store.append(
        {
            "event_schema_version": "operational_event.v1",
            "event_id": "event-0655-subject",
            "service_id": "nex-ag",
            "event_type": OPERATOR_REVIEW_CASE_RECORDED_EVENT_TYPE,
            "severity": "INFO",
            "message": "Subject-only event.",
            "trace_id": TRACE_ID,
            "request_id": REQUEST_ID,
            "subject_ref": {
                "type": "operator_review_case",
                "id": record["case_id"],
            },
            "details": {"case_id": None},
            "created_at": "2026-09-11T00:00:00Z",
        }
    )
    event_store.append(
        {
            "event_schema_version": "operational_event.v1",
            "event_id": "event-0655-subject-action",
            "service_id": "nex-ag",
            "event_type": OPERATOR_REVIEW_CASE_ACTION_RECORDED_EVENT_TYPE,
            "severity": "INFO",
            "message": "Subject-only action event.",
            "trace_id": TRACE_ID,
            "request_id": REQUEST_ID,
            "subject_ref": {
                "type": "operator_review_case",
                "id": record["case_id"],
            },
            "details": {},
            "created_at": "2026-09-11T00:00:01Z",
        }
    )

    class BrokenEventStore:
        def list_events(self, **_: Any) -> list[dict[str, Any]]:
            raise OperationalEventError(
                error_code="operational_event.store_unavailable",
                detail="store unavailable",
                status_code=503,
            )

    class UnexpectedBrokenEventStore:
        def list_events(self, **_: Any) -> list[dict[str, Any]]:
            raise RuntimeError("unexpected failure")

    class MalformedEventStore:
        def list_events(self, **_: Any) -> list[dict[str, Any]]:
            return [
                {
                    "event_id": "event-0655-malformed",
                    "event_type": OPERATOR_REVIEW_CASE_RECORDED_EVENT_TYPE,
                    "details": "bad-details",
                    "subject_ref": "bad-subject",
                    "created_at": "2026-09-11T00:00:01Z",
                }
            ]

    subject_timeline = build_operator_review_case_timeline_projection(
        record,
        event_store=event_store,
        request_id=REQUEST_ID,
        trace_id=None,
    )
    unavailable = build_operator_review_case_timeline_projection(
        record,
        event_store=BrokenEventStore(),
        request_id=REQUEST_ID,
        trace_id=None,
    )
    generic_unavailable = build_operator_review_case_timeline_projection(
        record,
        event_store=UnexpectedBrokenEventStore(),
        request_id=REQUEST_ID,
        trace_id=None,
    )
    malformed = build_operator_review_case_timeline_projection(
        record,
        event_store=MalformedEventStore(),
        request_id=REQUEST_ID,
        trace_id=None,
    )
    unavailable_outcomes = build_operator_review_case_action_outcome_projection(
        record,
        event_store=BrokenEventStore(),
        request_id=REQUEST_ID,
        trace_id=None,
    )

    assert subject_timeline["items"][0]["event_id"] == "event-0655-subject"
    assert subject_timeline["items"][0]["details"]["case_id"] is None
    assert subject_timeline["items"][1]["sequence"] == 2
    assert subject_timeline["items"][1]["timeline_kind"] == "CASE_ACTION"
    assert subject_timeline["items"][1]["action_outcome"] == {
        "outcome_source": "operator_review_case_action_event",
        "action_id": None,
        "action_type": None,
        "from_status": None,
        "to_status": None,
        "status_changed": False,
        "assignment_changed": False,
        "resolution_recorded": False,
        "terminal_action": False,
    }
    assert unavailable["summary"]["timeline_status"] == "UNAVAILABLE"
    assert unavailable["summary"]["event_count"] == 0
    assert unavailable["summary"]["source_error"] == {
        "error_code": "operational_event.store_unavailable",
        "detail": "store unavailable",
        "status_code": 503,
    }
    assert generic_unavailable["summary"]["source_error"]["error_code"] == (
        "ag.operator_review_case_timeline_unavailable"
    )
    assert malformed["summary"]["timeline_status"] == "READY"
    assert malformed["summary"]["event_count"] == 0
    assert unavailable_outcomes["trace_id"] is None
    assert unavailable_outcomes["summary"]["outcome_status"] == "UNAVAILABLE"
    assert unavailable_outcomes["summary"]["action_count"] == 0
    assert unavailable_outcomes["summary"]["source_error"] == {
        "error_code": "operational_event.store_unavailable",
        "detail": "store unavailable",
        "status_code": 503,
    }


def test_case_idempotency_signature_is_safe_and_stable() -> None:
    record = build_case()
    signature = operator_review_case_idempotency_signature(record)

    assert signature["target_id"] == "target-0642"
    assert signature["source_ref"]["source_type"] == "operator_review_workbench"
    assert signature["metadata"]["idempotency_key_stored"] is False
    assert "idem-0642-case" not in str(signature)


@pytest.mark.parametrize("action_type", ALLOWED_CASE_ACTIONS)
def test_case_action_type_registry_is_explicit(action_type: str) -> None:
    assert action_type in {
        "CREATE_CASE",
        "ACKNOWLEDGE",
        "ASSIGN",
        "RESOLVE",
        "DISMISS",
        "REOPEN",
    }


def test_case_action_record_resolves_and_redacts_comments() -> None:
    record = build_case()
    action = build_operator_review_case_action_record(
        record,
        sample_action_payload(
            action_type="RESOLVE",
            resolution_comment="Resolved after reviewing redacted evidence.",
        ),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0644-resolve",
        acted_at="2026-09-11T02:00:00Z",
    )
    updated, applied = apply_operator_review_case_action(
        record,
        sample_action_payload(
            action_type="RESOLVE",
            resolution_comment="Resolved after reviewing redacted evidence.",
        ),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0644-resolve",
        acted_at="2026-09-11T02:00:00Z",
    )

    assert action["case_action_schema_version"] == (
        OPERATOR_REVIEW_CASE_ACTION_SCHEMA_VERSION
    )
    assert action["action_type"] == "RESOLVE"
    assert action["from_status"] == "OPEN"
    assert action["to_status"] == "RESOLVED"
    assert action["resolution_hash"] == sha256_text(
        "Resolved after reviewing redacted evidence."
    )
    assert action["resolution_preview"] == (
        "Resolved after reviewing redacted evidence."
    )
    assert action["metadata"]["action_history_storage"] == (
        "operational_events_first"
    )
    assert action["metadata"]["idempotency_key_stored"] is False
    assert updated["case_status"] == "RESOLVED"
    assert updated["closed_at"] == "2026-09-11T02:00:00Z"
    assert updated["resolution_hash"] == action["resolution_hash"]
    assert applied == action
    assert '"resolution_comment"' not in json.dumps(action)


def test_case_action_service_applies_replays_and_conflicts() -> None:
    store = OperatorReviewCaseStore()
    service = OperatorReviewCaseService(store)
    case = service.create_case(
        sample_case_payload(),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0644-case",
    )["case"]

    acknowledged = service.apply_action(
        case["case_id"],
        sample_action_payload(),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0644-action",
    )
    replayed = service.apply_action(
        case["case_id"],
        sample_action_payload(),
        request_id="request-replay",
        trace_id=None,
        idempotency_key="idem-0644-action",
    )

    assert acknowledged["case_action_mutation_schema_version"] == (
        OPERATOR_REVIEW_CASE_ACTION_MUTATION_SCHEMA_VERSION
    )
    assert acknowledged["idempotency_status"] == "NEW"
    assert acknowledged["case"]["case_status"] == "ACKNOWLEDGED"
    assert acknowledged["case"]["metadata"]["last_action"]["record"] == (
        acknowledged["action"]
    )
    assert replayed["idempotency_status"] == "REPLAYED"
    assert replayed["action"] == acknowledged["action"]
    assert replayed["request_id"] == "request-replay"

    with pytest.raises(OperatorReviewNoteError) as conflict:
        service.apply_action(
            case["case_id"],
            sample_action_payload(action_comment="Different action comment."),
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
            idempotency_key="idem-0644-action",
        )
    assert conflict.value.status_code == 409
    assert conflict.value.error_code == (
        "ag.operator_review_case_action_idempotency_conflict"
    )


def test_case_action_service_assign_resolve_and_reopen_transitions() -> None:
    service = OperatorReviewCaseService(OperatorReviewCaseStore())
    case = service.create_case(
        sample_case_payload(),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0644-flow-case",
    )["case"]

    assigned = service.apply_action(
        case["case_id"],
        sample_action_payload(
            action_type="ASSIGN",
            assignment_ref={
                "assignee_type": "user",
                "assignee_id": "employee-assign-0644",
                "tenant_id": "local-tenant",
            },
        ),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0644-assign",
    )
    resolved = service.apply_action(
        case["case_id"],
        sample_action_payload(
            action_type="RESOLVE",
            resolution_comment="Resolution stored as a bounded safe preview.",
        ),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0644-resolve-flow",
    )
    reopened = service.apply_action(
        case["case_id"],
        sample_action_payload(action_type="REOPEN"),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0644-reopen",
    )

    assert assigned["case"]["case_status"] == "ASSIGNED"
    assert assigned["case"]["assignment_ref"]["assignee_id"] == "employee-assign-0644"
    assert resolved["case"]["case_status"] == "RESOLVED"
    assert resolved["case"]["closed_at"] is not None
    assert reopened["case"]["case_status"] == "REOPENED"
    assert reopened["case"]["closed_at"] is None


def test_case_action_mutation_response_and_signature_helpers() -> None:
    record = build_case()
    action = build_operator_review_case_action_record(
        record,
        sample_action_payload(),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0644-helper",
        acted_at="2026-09-11T03:00:00Z",
    )
    response = build_operator_review_case_action_mutation_response(
        {**record, "case_status": "ACKNOWLEDGED"},
        action,
        idempotency_status="NEW",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    signature = operator_review_case_action_request_signature(
        record["case_id"],
        sample_action_payload(),
    )

    assert response["summary"]["action_type"] == "ACKNOWLEDGE"
    assert response["summary"]["to_status"] == "ACKNOWLEDGED"
    assert signature["action_comment_hash"] == sha256_text(
        "Operator acknowledged the review case."
    )
    assert operator_review_case_action_id(
        record["case_id"],
        "idem-0644-helper",
    ) == action["action_id"]
    assert required_case_action_idempotency_key("  idem-action  ") == "idem-action"
    assert operator_review_case_action_metadata(None)["raw_prompt_stored"] is False


def test_case_action_validation_rejects_invalid_requests() -> None:
    service = OperatorReviewCaseService(OperatorReviewCaseStore())
    case = service.create_case(
        sample_case_payload(),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0644-invalid-case",
    )["case"]

    invalid_requests = [
        (
            sample_action_payload(action_type=None),
            "ag.operator_review_case_action_type_required",
        ),
        (
            sample_action_payload(action_type="CREATE_CASE"),
            "ag.operator_review_case_action_create_case_unsupported",
        ),
        (
            sample_action_payload(action_type="UNKNOWN"),
            "ag.operator_review_case_action_type_unsupported",
        ),
        (
            sample_action_payload(action_type="ASSIGN"),
            "ag.operator_review_case_assignment_required",
        ),
        (
            sample_action_payload(action_type="RESOLVE", action_comment=None),
            "ag.operator_review_case_resolution_comment_required",
        ),
        (
            sample_action_payload(raw_prompt="do not store this"),
            "ag.operator_review_note_sensitive_payload",
        ),
        (
            sample_action_payload(metadata=["not-object"]),
            "ag.operator_review_case_action_metadata_invalid",
        ),
    ]

    for payload, error_code in invalid_requests:
        with pytest.raises(OperatorReviewNoteError) as exc:
            service.apply_action(
                case["case_id"],
                payload,
                request_id=REQUEST_ID,
                trace_id=TRACE_ID,
                idempotency_key=f"idem-0644-invalid-{error_code}",
            )
        assert exc.value.error_code == error_code

    with pytest.raises(OperatorReviewNoteError) as missing_idem:
        service.apply_action(
            case["case_id"],
            sample_action_payload(),
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
            idempotency_key=None,
        )
    assert missing_idem.value.error_code == (
        "ag.operator_review_case_action_idempotency_key_required"
    )


def test_case_action_private_guard_helpers_cover_malformed_metadata() -> None:
    assert _latest_case_action_summary({"metadata": None}) is None
    assert _latest_case_action_summary({"metadata": {"last_action": None}}) is None
    assert _latest_case_action_summary(
        {"metadata": {"last_action": {"request_signature": {}}}}
    ) is None
    assert _latest_case_action_summary(
        {"metadata": {"last_action": {"record": {}, "request_signature": None}}}
    ) is None

    with pytest.raises(OperatorReviewNoteError) as exc:
        _target_status_for_case_action("CREATE_CASE", "OPEN")
    assert exc.value.error_code == "ag.operator_review_case_action_type_unsupported"


def test_case_action_validation_rejects_invalid_transition() -> None:
    service = OperatorReviewCaseService(OperatorReviewCaseStore())
    case = service.create_case(
        sample_case_payload(case_status="RESOLVED"),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0644-resolved-case",
    )["case"]

    with pytest.raises(OperatorReviewNoteError) as exc:
        service.apply_action(
            case["case_id"],
            sample_action_payload(action_type="ACKNOWLEDGE"),
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
            idempotency_key="idem-0644-invalid-transition",
        )

    assert exc.value.status_code == 409
    assert exc.value.error_code == "ag.operator_review_case_action_transition_invalid"


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


def test_operator_review_case_service_rollup_reuses_list_filters() -> None:
    service = OperatorReviewCaseService(OperatorReviewCaseStore())
    service.create_case(
        sample_case_payload(),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0646-rollup-open",
    )
    service.create_case(
        sample_case_payload(
            case_status="DISMISSED",
            case_priority="LOW",
            target_ref={
                "target_service": "nex-cx",
                "target_kind": "retrieval_package",
                "target_id": "retrieval-rollup",
            },
            resolution_comment="Dismissed as duplicate.",
        ),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0646-rollup-dismissed",
    )

    rollup = service.rollup_cases(
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        target_service="nex-cx",
        case_status="DISMISSED",
    )

    assert rollup["summary"]["case_count"] == 1
    assert rollup["summary"]["closed_case_count"] == 1
    assert rollup["summary"]["attention_case_count"] == 0
    assert rollup["by_target_service"] == {"nex-cx": 1}


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


def test_emit_operator_review_case_action_event_records_safe_event() -> None:
    event_store = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id="nex-ag", store=event_store)
    record = build_case(sample_case_payload(case_id="case-action-event"))
    updated, action = apply_operator_review_case_action(
        record,
        sample_action_payload(
            action_type="RESOLVE",
            resolution_comment="Action completed with safe summary only.",
        ),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-action-event",
        acted_at="2026-09-11T04:00:00Z",
    )

    result = emit_operator_review_case_action_event(emitter, action, updated)
    events = event_store.list_events(
        event_type=OPERATOR_REVIEW_CASE_ACTION_RECORDED_EVENT_TYPE
    )

    assert result.ok is True
    assert len(events) == 1
    assert events[0]["subject_ref"] == {
        "type": "operator_review_case_action",
        "id": action["action_id"],
    }
    assert events[0]["details"] == {
        "case_id": "case-action-event",
        "action_id": action["action_id"],
        "action_type": "RESOLVE",
        "from_status": "OPEN",
        "to_status": "RESOLVED",
        "case_status": "RESOLVED",
        "target_service": "nex-ag",
        "target_kind": "operator_review_workbench",
        "target_id": "target-0642",
        "operator_type": "user",
        "operator_id": "employee-0001",
        "assignee_id": "employee-0002",
        "reason_count": 1,
        "action_comment_hash": action["action_comment_hash"],
        "resolution_hash": action["resolution_hash"],
    }
    assert "resolution_preview" not in events[0]["details"]


def test_emit_operator_review_case_action_event_uses_safe_failure_result() -> None:
    class FailingEventStore:
        def append(self, event: dict[str, Any]) -> dict[str, Any]:
            raise OperationalEventError(
                error_code="operational_event.store_unavailable",
                detail="store unavailable",
                status_code=503,
            )

    record = build_case()
    updated, action = apply_operator_review_case_action(
        record,
        sample_action_payload(),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-action-event-failure",
    )
    emitter = OperationalEventEmitter(service_id="nex-ag", store=FailingEventStore())

    result = emit_operator_review_case_action_event(emitter, action, updated)

    assert result.ok is False
    assert result.error_code == "operational_event.store_unavailable"


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


def test_operator_review_case_action_route_applies_replays_and_emits_event() -> None:
    client, store, event_store = build_route_client()
    created = client.post(
        "/admin/v1/operator-review/cases",
        headers={**admin_auth_headers(), "Idempotency-Key": "idem-route-case-0645"},
        json=sample_case_payload(),
    )
    case_id = created.json()["case"]["case_id"]

    applied = client.post(
        f"/admin/v1/operator-review/cases/{case_id}/actions",
        headers={**admin_auth_headers(), "Idempotency-Key": "idem-route-action-0645"},
        json=sample_action_payload(),
    )
    replayed = client.post(
        f"/admin/v1/operator-review/cases/{case_id}/actions",
        headers={**admin_auth_headers(), "Idempotency-Key": "idem-route-action-0645"},
        json=sample_action_payload(),
    )

    assert applied.status_code == 201
    assert applied.json()["idempotency_status"] == "NEW"
    assert applied.json()["case"]["case_status"] == "ACKNOWLEDGED"
    assert applied.json()["action"]["action_type"] == "ACKNOWLEDGE"
    assert replayed.status_code == 200
    assert replayed.json()["idempotency_status"] == "REPLAYED"
    assert replayed.json()["action"] == applied.json()["action"]
    assert store.get(case_id)["case_status"] == "ACKNOWLEDGED"
    assert event_store.summary()["total"] == 2
    assert len(
        event_store.list_events(
            event_type=OPERATOR_REVIEW_CASE_ACTION_RECORDED_EVENT_TYPE
        )
    ) == 1


def test_operator_review_case_rollup_route_precedes_detail_route_and_filters() -> None:
    client, _, _ = build_route_client()
    created = client.post(
        "/admin/v1/operator-review/cases",
        headers={**admin_auth_headers(), "Idempotency-Key": "idem-route-case-0646"},
        json=sample_case_payload(assignment_ref=None, case_priority="URGENT"),
    )
    case_id = created.json()["case"]["case_id"]

    rollup = client.get(
        "/admin/v1/operator-review/cases/rollups?target_service=nex-ag",
        headers=service_auth_headers(),
    )
    invalid = client.get(
        "/admin/v1/operator-review/cases/rollups?case_priority=CRITICAL",
        headers=service_auth_headers(),
    )
    unauthorized = client.get("/admin/v1/operator-review/cases/rollups")

    assert rollup.status_code == 200
    assert rollup.json()["rollup_schema_version"] == (
        OPERATOR_REVIEW_CASE_ROLLUP_SCHEMA_VERSION
    )
    assert rollup.json()["summary"]["case_count"] == 1
    assert rollup.json()["attention"]["items"][0]["case_id"] == case_id
    assert rollup.json()["paths"]["case_rollup_path"] == (
        "/admin/v1/operator-review/cases/rollups"
    )
    assert invalid.status_code == 422
    assert invalid.json()["error_code"] == (
        "ag.operator_review_note_case_priority_unsupported"
    )
    assert unauthorized.status_code == 401


def test_operator_review_case_queue_route_precedes_detail_route_and_filters() -> None:
    client, _, _ = build_route_client()
    created = client.post(
        "/admin/v1/operator-review/cases",
        headers={**admin_auth_headers(), "Idempotency-Key": "idem-route-case-0652"},
        json=sample_case_payload(assignment_ref=None, case_priority="URGENT"),
    )
    case_id = created.json()["case"]["case_id"]

    queue = client.get(
        "/admin/v1/operator-review/cases/queue?target_service=nex-ag",
        headers=service_auth_headers(),
    )
    filtered_empty = client.get(
        "/admin/v1/operator-review/cases/queue?case_status=RESOLVED",
        headers=service_auth_headers(),
    )
    invalid = client.get(
        "/admin/v1/operator-review/cases/queue?operator_type=robot",
        headers=service_auth_headers(),
    )
    unauthorized = client.get("/admin/v1/operator-review/cases/queue")

    assert queue.status_code == 200
    assert queue.json()["case_queue_schema_version"] == (
        OPERATOR_REVIEW_CASE_QUEUE_SCHEMA_VERSION
    )
    assert queue.json()["items"][0]["case_id"] == case_id
    assert queue.json()["items"][0]["attention_status"] == "BLOCKED"
    assert queue.json()["paths"]["case_detail_path_template"] == (
        "/admin/v1/operator-review/cases/{case_id}"
    )
    assert filtered_empty.status_code == 200
    assert filtered_empty.json()["summary"]["case_count"] == 0
    assert invalid.status_code == 422
    assert invalid.json()["error_code"] == (
        "ag.operator_review_note_operator_type_unsupported"
    )
    assert unauthorized.status_code == 401


def test_operator_review_case_workbench_detail_route_is_protected_and_safe() -> None:
    note_store = OperatorReviewNoteStore()
    export_store = OperatorEvidenceExportStore()
    client, _, _ = build_route_client(
        note_store=note_store,
        export_store=export_store,
    )
    created = client.post(
        "/admin/v1/operator-review/cases",
        headers={**admin_auth_headers(), "Idempotency-Key": "idem-route-case-0654"},
        json=sample_case_payload(
            case_priority="URGENT",
            resolution_comment="Route detail must expose only the bounded preview.",
        ),
    )
    case_id = created.json()["case"]["case_id"]
    note_store.save(sample_note_record(operator_note_id="note-route-0666-detail"))
    export_store.save(
        sample_evidence_export_record(export_id="export-route-0666-detail")
    )

    detail = client.get(
        f"/admin/v1/operator-review/cases/{case_id}/workbench-detail",
        headers=service_auth_headers(),
    )
    missing = client.get(
        "/admin/v1/operator-review/cases/missing/workbench-detail",
        headers=service_auth_headers(),
    )
    unauthorized = client.get(
        f"/admin/v1/operator-review/cases/{case_id}/workbench-detail"
    )

    assert detail.status_code == 200
    assert detail.json()["case_workbench_detail_schema_version"] == (
        OPERATOR_REVIEW_CASE_WORKBENCH_DETAIL_SCHEMA_VERSION
    )
    assert detail.json()["case"]["case_id"] == case_id
    assert detail.json()["links"]["case_action_path"] == (
        f"/admin/v1/operator-review/cases/{case_id}/actions"
    )
    assert detail.json()["links"]["case_evidence_links_path"] == (
        f"/admin/v1/operator-review/cases/{case_id}/evidence-links"
    )
    assert detail.json()["links"]["case_action_admission_path"] == (
        f"/admin/v1/operator-review/cases/{case_id}/action-admission"
    )
    assert detail.json()["evidence_links"]["summary"]["evidence_source_status"] == (
        "READY"
    )
    assert detail.json()["evidence_links"]["summary"]["total_link_count"] == 2
    assert detail.json()["action_admission"]["summary"]["preflight_only"] is True
    assert detail.json()["redaction"]["raw_resolution_comment_included"] is False
    assert "Route detail must expose only" in detail.json()["resolution"][
        "resolution_preview"
    ]
    assert missing.status_code == 404
    assert unauthorized.status_code == 401
    serialized = json.dumps(detail.json())
    assert "idem-route-case-0654" not in serialized
    assert "raw-secret-note-0662" not in serialized
    assert "raw-export-body-should-not-leak" not in serialized


def test_operator_review_case_evidence_links_route_is_protected_and_safe() -> None:
    note_store = OperatorReviewNoteStore()
    export_store = OperatorEvidenceExportStore()
    client, _, _ = build_route_client(
        note_store=note_store,
        export_store=export_store,
    )
    created = client.post(
        "/admin/v1/operator-review/cases",
        headers={**admin_auth_headers(), "Idempotency-Key": "idem-route-case-0663"},
        json=sample_case_payload(),
    )
    case_id = created.json()["case"]["case_id"]
    note_store.save(sample_note_record(operator_note_id="note-route-0663-a"))
    note_store.save(
        sample_note_record(
            operator_note_id="note-route-0663-other",
            target_id="target-other",
            updated_at="2026-09-11T00:04:00Z",
        )
    )
    export_store.save(sample_evidence_export_record(export_id="export-route-0663-a"))

    evidence_links = client.get(
        f"/admin/v1/operator-review/cases/{case_id}/evidence-links?limit=1",
        headers=service_auth_headers(),
    )
    missing = client.get(
        "/admin/v1/operator-review/cases/missing/evidence-links",
        headers=service_auth_headers(),
    )
    unauthorized = client.get(
        f"/admin/v1/operator-review/cases/{case_id}/evidence-links"
    )

    assert evidence_links.status_code == 200
    payload = evidence_links.json()
    assert payload["case_evidence_links_schema_version"] == (
        OPERATOR_REVIEW_CASE_EVIDENCE_LINKS_SCHEMA_VERSION
    )
    assert payload["case"]["case_id"] == case_id
    assert payload["summary"]["operator_note_count"] == 1
    assert payload["summary"]["redacted_evidence_export_count"] == 1
    assert payload["summary"]["returned_link_count"] == 1
    assert payload["links"]["case_evidence_links_path"] == (
        f"/admin/v1/operator-review/cases/{case_id}/evidence-links"
    )
    assert payload["redaction"]["raw_operator_note_included"] is False
    assert missing.status_code == 404
    assert unauthorized.status_code == 401

    serialized = json.dumps(payload)
    assert "raw-secret-note-0662" not in serialized
    assert "raw-export-body-should-not-leak" not in serialized
    assert "postgresql://secret-should-not-leak" not in serialized
    assert "idem-route-case-0663" not in serialized


def test_operator_review_case_action_admission_route_is_protected_and_safe() -> None:
    client, store, _ = build_route_client()
    created = client.post(
        "/admin/v1/operator-review/cases",
        headers={**admin_auth_headers(), "Idempotency-Key": "idem-route-case-0665"},
        json=sample_case_payload(),
    )
    case_id = created.json()["case"]["case_id"]
    stored_case = store.get(case_id)
    stored_case["metadata"]["raw_action_comment"] = "raw action comment leak"
    stored_case["metadata"]["database_url"] = "postgresql://admission-route-secret"
    store.save(stored_case)

    admission = client.get(
        f"/admin/v1/operator-review/cases/{case_id}/action-admission"
        "?action_type=RESOLVE",
        headers=service_auth_headers(),
    )
    invalid = client.get(
        f"/admin/v1/operator-review/cases/{case_id}/action-admission"
        "?action_type=ESCALATE",
        headers=service_auth_headers(),
    )
    missing = client.get(
        "/admin/v1/operator-review/cases/missing/action-admission",
        headers=service_auth_headers(),
    )
    unauthorized = client.get(
        f"/admin/v1/operator-review/cases/{case_id}/action-admission"
    )

    assert admission.status_code == 200
    payload = admission.json()
    assert payload["case_action_admission_schema_version"] == (
        OPERATOR_REVIEW_CASE_ACTION_ADMISSION_SCHEMA_VERSION
    )
    assert payload["case"]["case_id"] == case_id
    assert payload["summary"]["requested_action_type"] == "RESOLVE"
    assert payload["summary"]["requested_action_admitted"] is True
    assert payload["requested_action"]["requires_resolution_comment"] is True
    assert payload["links"]["case_action_admission_path"] == (
        f"/admin/v1/operator-review/cases/{case_id}/action-admission"
    )
    assert invalid.status_code == 422
    assert invalid.json()["error_code"] == (
        "ag.operator_review_case_action_type_unsupported"
    )
    assert missing.status_code == 404
    assert unauthorized.status_code == 401

    serialized = json.dumps(payload)
    assert "raw action comment leak" not in serialized
    assert "postgresql://admission-route-secret" not in serialized
    assert "idem-route-case-0665" not in serialized
    assert '"metadata":' not in serialized


def test_operator_review_case_timeline_route_reads_audit_events() -> None:
    client, _, event_store = build_route_client()
    created = client.post(
        "/admin/v1/operator-review/cases",
        headers={**admin_auth_headers(), "Idempotency-Key": "idem-route-case-0655"},
        json=sample_case_payload(),
    )
    case_id = created.json()["case"]["case_id"]
    applied = client.post(
        f"/admin/v1/operator-review/cases/{case_id}/actions",
        headers={**admin_auth_headers(), "Idempotency-Key": "idem-route-action-0655"},
        json=sample_action_payload(action_comment="Route timeline raw text."),
    )

    timeline = client.get(
        f"/admin/v1/operator-review/cases/{case_id}/timeline",
        headers=service_auth_headers(),
    )
    limited = client.get(
        f"/admin/v1/operator-review/cases/{case_id}/timeline?limit=1",
        headers=service_auth_headers(),
    )
    missing = client.get(
        "/admin/v1/operator-review/cases/missing/timeline",
        headers=service_auth_headers(),
    )
    unauthorized = client.get(
        f"/admin/v1/operator-review/cases/{case_id}/timeline"
    )

    assert applied.status_code == 201
    assert timeline.status_code == 200
    assert timeline.json()["case_timeline_schema_version"] == (
        OPERATOR_REVIEW_CASE_TIMELINE_SCHEMA_VERSION
    )
    assert timeline.json()["summary"]["event_count"] == 2
    assert [item["event_type"] for item in timeline.json()["items"]] == [
        OPERATOR_REVIEW_CASE_RECORDED_EVENT_TYPE,
        OPERATOR_REVIEW_CASE_ACTION_RECORDED_EVENT_TYPE,
    ]
    assert timeline.json()["items"][1]["sequence"] == 2
    assert timeline.json()["items"][1]["timeline_kind"] == "CASE_ACTION"
    assert timeline.json()["items"][1]["action_outcome"]["status_changed"] is True
    assert timeline.json()["items"][1]["redaction"]["raw_event_details_included"] is False
    assert limited.json()["summary"]["event_count"] == 1
    assert missing.status_code == 404
    assert unauthorized.status_code == 401
    assert event_store.summary()["total"] == 2
    assert "Route timeline raw text" not in json.dumps(timeline.json())


def test_operator_review_case_closure_packet_route_is_protected_and_safe() -> None:
    note_store = OperatorReviewNoteStore()
    export_store = OperatorEvidenceExportStore()
    client, _, event_store = build_route_client(
        note_store=note_store,
        export_store=export_store,
    )
    created = client.post(
        "/admin/v1/operator-review/cases",
        headers={**admin_auth_headers(), "Idempotency-Key": "idem-route-case-0676"},
        json=sample_case_payload(),
    )
    case_id = created.json()["case"]["case_id"]
    note_store.save(sample_note_record(operator_note_id="note-route-0676"))
    export_store.save(sample_evidence_export_record(export_id="export-route-0676"))
    applied = client.post(
        f"/admin/v1/operator-review/cases/{case_id}/actions",
        headers={**admin_auth_headers(), "Idempotency-Key": "idem-route-action-0676"},
        json=sample_action_payload(
            action_type="RESOLVE",
            action_comment="Route closure action text must stay out.",
            resolution_comment="Route closure resolution text must stay out.",
        ),
    )

    packet = client.get(
        f"/admin/v1/operator-review/cases/{case_id}/closure-packet",
        headers=service_auth_headers(),
    )
    limited = client.get(
        f"/admin/v1/operator-review/cases/{case_id}/closure-packet"
        "?evidence_limit=1&timeline_limit=1",
        headers=service_auth_headers(),
    )
    missing = client.get(
        "/admin/v1/operator-review/cases/missing/closure-packet",
        headers=service_auth_headers(),
    )
    unauthorized = client.get(
        f"/admin/v1/operator-review/cases/{case_id}/closure-packet"
    )

    assert applied.status_code == 201
    assert packet.status_code == 200
    assert packet.json()["case_closure_packet_schema_version"] == (
        OPERATOR_REVIEW_CASE_CLOSURE_PACKET_SCHEMA_VERSION
    )
    assert packet.json()["summary"]["closure_ready"] is True
    assert packet.json()["summary"]["evidence_link_count"] == 2
    assert packet.json()["summary"]["timeline_event_count"] == 2
    assert packet.json()["paths"]["case_closure_packet_path"] == (
        f"/admin/v1/operator-review/cases/{case_id}/closure-packet"
    )
    assert packet.json()["resolution"]["resolution_preview"] is None
    assert packet.json()["redaction"]["closure_packet_storage"] == (
        "read_model_only_not_persisted"
    )
    assert limited.json()["summary"]["evidence_link_count"] == 2
    assert limited.json()["evidence"]["summary"]["returned_link_count"] == 1
    assert limited.json()["summary"]["timeline_event_count"] == 1
    assert missing.status_code == 404
    assert unauthorized.status_code == 401
    assert event_store.summary()["total"] == 2
    serialized = json.dumps(packet.json())
    assert "Route closure action text" not in serialized
    assert "Route closure resolution text" not in serialized
    assert "idem-route" not in serialized
    assert '"metadata":' not in serialized


def test_operator_review_case_action_route_rejects_auth_invalid_and_missing() -> None:
    client, _, _ = build_route_client()
    created = client.post(
        "/admin/v1/operator-review/cases",
        headers={**admin_auth_headers(), "Idempotency-Key": "idem-route-invalid-case"},
        json=sample_case_payload(),
    )
    case_id = created.json()["case"]["case_id"]

    missing_auth = client.post(
        f"/admin/v1/operator-review/cases/{case_id}/actions",
        json=sample_action_payload(),
    )
    non_admin = client.post(
        f"/admin/v1/operator-review/cases/{case_id}/actions",
        headers={**non_admin_auth_headers(), "Idempotency-Key": "idem-non-admin"},
        json=sample_action_payload(),
    )
    missing_idempotency = client.post(
        f"/admin/v1/operator-review/cases/{case_id}/actions",
        headers=admin_auth_headers(),
        json=sample_action_payload(),
    )
    invalid_action = client.post(
        f"/admin/v1/operator-review/cases/{case_id}/actions",
        headers={**admin_auth_headers(), "Idempotency-Key": "idem-invalid-action"},
        json=sample_action_payload(action_type="ASSIGN"),
    )
    missing_case = client.post(
        "/admin/v1/operator-review/cases/missing/actions",
        headers={**admin_auth_headers(), "Idempotency-Key": "idem-missing-case"},
        json=sample_action_payload(),
    )

    assert missing_auth.status_code == 401
    assert non_admin.status_code == 403
    assert non_admin.json()["error_code"] == "AG_OPERATOR_REVIEW_ADMIN_ROLE_REQUIRED"
    assert missing_idempotency.status_code == 422
    assert missing_idempotency.json()["error_code"] == (
        "ag.operator_review_case_action_idempotency_key_required"
    )
    assert invalid_action.status_code == 422
    assert invalid_action.json()["error_code"] == (
        "ag.operator_review_case_assignment_required"
    )
    assert missing_case.status_code == 404
    assert missing_case.json()["error_code"] == "ag.operator_review_case_not_found"


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
