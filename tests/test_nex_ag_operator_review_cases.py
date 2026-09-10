from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from nex_ag.operator_review_cases import (
    AG_OPERATOR_REVIEW_CASE_TABLE,
    ALLOWED_CASE_PRIORITIES,
    ALLOWED_CASE_STATUSES,
    OPERATOR_REVIEW_CASE_SCHEMA_VERSION,
    OperatorReviewCaseStore,
    SqlAlchemyOperatorReviewCaseStore,
    _operator_review_case_filter_clause,
    _operator_review_case_record_params,
    _operator_review_case_select_sql,
    build_operator_review_case_list_response,
    build_operator_review_case_mutation_response,
    build_operator_review_case_record,
    default_operator_review_case_store,
    operator_review_case_assignment_ref,
    operator_review_case_idempotency_signature,
    operator_review_case_metadata,
    operator_review_case_source_ref,
)
from nex_ag.operator_reviews import (
    OperatorReviewNoteError,
    _datetime_value,
    _json_param_expr,
    _json_value,
    sha256_text,
)
from nex_runtime import SERVICE_SPECS, build_engine, build_service_app, build_session_factory


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
