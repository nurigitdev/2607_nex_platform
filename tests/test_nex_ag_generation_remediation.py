from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from nex_ag.generation_remediation import (
    REMEDIATION_CANDIDATE_PROJECTION_SCHEMA_VERSION,
    REMEDIATION_ACTION_SCHEMA_VERSION,
    GenerationRemediationError,
    GenerationRemediationTaskStore,
    SqlAlchemyGenerationRemediationTaskStore,
    build_generation_remediation_candidate_projection,
    build_generation_remediation_action,
    build_generation_remediation_action_list_response,
    default_generation_remediation_task_store,
    emit_generation_remediation_task_event,
    evidence_summary,
    hash_list,
    preview_list,
    reason_code_list,
    register_generation_remediation_task_routes,
    result_ref,
    source_ref_list,
    update_generation_remediation_action_status,
    _datetime_value,
    _json_param_expr,
    _json_value,
    _normalize_remediation_list_limit,
)
from nex_runtime import (
    InMemoryOperationalEventStore,
    OperationalEventEmitter,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
)


ROOT = Path(__file__).parents[1]


def auth_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience="nex-ag")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": "0189f0ff-8f22-4f72-9b47-b481dc21bb21",
        "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
    }


def build_route_client(
    *,
    store: Any | None = None,
    audit_event_store: InMemoryOperationalEventStore | None = None,
) -> tuple[TestClient, Any, InMemoryOperationalEventStore]:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    selected_store = store or GenerationRemediationTaskStore()
    selected_event_store = audit_event_store or InMemoryOperationalEventStore()
    register_generation_remediation_task_routes(
        app,
        store=selected_store,
        audit_event_store=selected_event_store,
    )
    return TestClient(app), selected_store, selected_event_store


def sqlite_remediation_store() -> tuple[SqlAlchemyGenerationRemediationTaskStore, Any]:
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE ag_generation_remediation_tasks (
                    remediation_action_id TEXT PRIMARY KEY,
                    action_schema_version TEXT NOT NULL,
                    cx_generation_id TEXT NOT NULL,
                    tenant_id TEXT,
                    trace_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    action_status TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    owner_type TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    owner_tenant_id TEXT,
                    owner_ref TEXT NOT NULL,
                    reason_codes TEXT NOT NULL,
                    source_refs TEXT NOT NULL,
                    evidence TEXT NOT NULL,
                    result_ref TEXT,
                    metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
    return SqlAlchemyGenerationRemediationTaskStore(sessionmaker(bind=engine)), engine


def remediation_action_schema() -> dict[str, object]:
    return json.loads(
        (
            ROOT
            / "contracts"
            / "schemas"
            / "generation"
            / "ag_generation_remediation_action.v1.schema.json"
        ).read_text(encoding="utf-8")
    )


def remediation_action_example() -> dict[str, object]:
    return json.loads(
        (
            ROOT
            / "contracts"
            / "examples"
            / "generation"
            / "ag_generation_remediation_action.citation_repair.json"
        ).read_text(encoding="utf-8")
    )


def remediation_action_negative_example() -> dict[str, object]:
    return json.loads(
        (
            ROOT
            / "contracts"
            / "tests"
            / "negative"
            / "generation"
            / "ag_generation_remediation_action.raw_output_field.json"
        ).read_text(encoding="utf-8")
    )


def ag_openapi_spec() -> dict[str, object]:
    return yaml.safe_load(
        (ROOT / "contracts" / "openapi" / "nex-ag.openapi.yaml").read_text(
            encoding="utf-8"
        )
    )


def action_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "remediation_action_id": "ag-remediation-action-test",
        "tenant_id": "local-tenant",
        "action_type": "citation_repair",
        "priority": "HIGH",
        "reason_codes": [
            "negative_user_feedback",
            "citation_quality",
            "citation_quality",
        ],
        "owner_ref": {
            "owner_type": "user",
            "owner_id": "employee-0001",
        },
        "source_refs": [
            {
                "source_service": "nex-ae-api",
                "ref_type": "feedback",
                "ref_id": "ae-feedback-001",
                "relation": "caused_by",
            },
            {
                "source_service": "nex-ag",
                "ref_type": "operator_disposition",
                "ref_id": "ag-gq-disposition-001",
                "relation": "recommended_by",
            },
        ],
        "evidence_previews": [
            "Citation [2] did not support the generated answer.",
        ],
        "action_source": "operator_disposition",
    }
    payload.update(overrides)
    return payload


def build_action(**overrides: object) -> dict[str, object]:
    return build_generation_remediation_action(
        action_payload(**overrides),
        cx_generation_id="cx-gen-001",
        request_id="0189f0ff-8f22-4f72-9b47-b481dc21bb21",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        created_at="2026-08-25T00:00:00Z",
    )


def rollup_item(**overrides: object) -> dict[str, object]:
    item: dict[str, object] = {
        "cx_generation_id": "cx-gen-001",
        "tenant_id": "local-tenant",
        "attention_status": "OPEN",
        "severity": "WARNING",
        "quality": {
            "count": 1,
            "attention_required": True,
            "max_severity": "WARNING",
            "coverage_statuses": ["READY"],
            "boundary_statuses": ["OK"],
            "issue_codes": ["CITATION_MISSING"],
            "recommended_actions": ["repair_citation"],
        },
        "feedback": {
            "count": 1,
            "negative_count": 1,
            "latest_feedback_id": "ae-feedback-001",
        },
        "disposition": {
            "count": 1,
            "latest_disposition_id": "ag-gq-disposition-001",
            "latest_status": "IN_REPAIR",
            "latest_action": "needs_cx_repair",
        },
    }
    item.update(overrides)
    return item


def build_projection(items: list[dict[str, object]], **overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "rollup_items": items,
        "request_id": "0189f0ff-8f22-4f72-9b47-b481dc21bb21",
        "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
        "checked_at": "2026-08-25T00:00:00Z",
    }
    kwargs.update(overrides)
    return build_generation_remediation_candidate_projection(**kwargs)


def test_generation_remediation_action_example_matches_contract() -> None:
    Draft202012Validator(remediation_action_schema()).validate(
        remediation_action_example()
    )


def test_generation_remediation_negative_example_rejects_raw_output_field() -> None:
    with pytest.raises(ValidationError):
        Draft202012Validator(remediation_action_schema()).validate(
            remediation_action_negative_example()
        )


def test_generation_remediation_action_builder_matches_contract() -> None:
    action = build_action()

    Draft202012Validator(remediation_action_schema()).validate(action)
    assert action["action_schema_version"] == REMEDIATION_ACTION_SCHEMA_VERSION
    assert action["action_status"] == "PROPOSED"
    assert action["priority"] == "HIGH"
    assert action["reason_codes"] == [
        "negative_user_feedback",
        "citation_quality",
    ]
    assert action["owner_ref"] == {
        "owner_type": "user",
        "owner_id": "employee-0001",
        "tenant_id": "local-tenant",
    }
    assert action["metadata"] == {
        "action_source": "operator_disposition",
        "raw_prompt_stored": False,
        "raw_generation_output_stored": False,
        "raw_source_document_text_stored": False,
        "raw_feedback_comment_stored": False,
        "raw_operator_note_stored": False,
        "free_text_storage": "hash_and_short_preview_only",
    }
    assert action["evidence"]["raw_evidence_stored"] is False
    assert action["evidence"]["evidence_hashes"][0]


def test_generation_remediation_action_builder_defaults_owner_priority_and_id() -> None:
    action = build_generation_remediation_action(
        {
            "tenant_id": "local-tenant",
            "action_type": "retry_generation",
            "reason_codes": ["generation_quality"],
        },
        cx_generation_id="cx-gen-defaults",
        request_id="request-defaults",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        created_at="2026-08-25T00:00:00Z",
    )

    assert action["remediation_action_id"]
    assert action["priority"] == "NORMAL"
    assert action["owner_ref"] == {
        "owner_type": "service",
        "owner_id": "nex-ag",
        "tenant_id": "local-tenant",
    }
    assert action["source_refs"] == []
    assert action["result_ref"] is None


def test_generation_remediation_action_builder_accepts_result_ref() -> None:
    action = build_action(
        result_ref={
            "source_service": "nex-cx",
            "ref_type": "repair_execution",
            "ref_id": "cx-repair-run-001",
        },
        action_status="COMPLETED",
    )

    Draft202012Validator(remediation_action_schema()).validate(action)
    assert action["result_ref"] == {
        "source_service": "nex-cx",
        "ref_type": "repair_execution",
        "ref_id": "cx-repair-run-001",
        "relation": "result_of",
    }


def test_generation_remediation_in_memory_store_saves_lists_and_deletes() -> None:
    store = GenerationRemediationTaskStore()
    first = build_action(remediation_action_id="ag-remediation-001")
    second = build_generation_remediation_action(
        action_payload(
            remediation_action_id="ag-remediation-002",
            action_type="retry_generation",
        ),
        cx_generation_id="cx-gen-002",
        request_id="request-002",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        created_at="2026-08-25T00:00:00Z",
    )

    assert store.save(first) == first
    assert store.save(second) == second
    assert store.get("ag-remediation-001") == first
    assert store.list_for_generation("cx-gen-001") == [first]
    assert [
        item["remediation_action_id"] for item in store.list_recent(limit=1)
    ] == ["ag-remediation-001"]
    assert store.list_for_generation("missing") == []
    assert store.delete("missing") == 0
    assert store.delete("ag-remediation-001") == 1
    assert store.get("ag-remediation-001") is None


def test_generation_remediation_in_memory_store_reindexes_existing_action() -> None:
    store = GenerationRemediationTaskStore()
    original = build_action(remediation_action_id="ag-remediation-reindex")
    moved = build_generation_remediation_action(
        action_payload(remediation_action_id="ag-remediation-reindex"),
        cx_generation_id="cx-gen-reindexed",
        request_id="request-reindexed",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        created_at="2026-08-25T00:00:00Z",
    )

    store.save(original)
    store.save(moved)

    assert store.list_for_generation("cx-gen-001") == []
    assert store.list_for_generation("cx-gen-reindexed") == [moved]


def test_generation_remediation_list_response_sorts_and_summarizes() -> None:
    older = build_action(
        remediation_action_id="ag-remediation-older",
        action_type="citation_repair",
    )
    newer = build_action(
        remediation_action_id="ag-remediation-newer",
        action_type="retry_generation",
    )
    newer["updated_at"] = "2026-08-25T00:01:00Z"
    newer["action_status"] = "ASSIGNED"

    response = build_generation_remediation_action_list_response(
        [older, newer],
        cx_generation_id="cx-gen-001",
        request_id="request-list",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
    )

    assert response["action_list_schema_version"] == (
        "ag_generation_remediation_action_list.v1"
    )
    assert [item["remediation_action_id"] for item in response["items"]] == [
        "ag-remediation-newer",
        "ag-remediation-older",
    ]
    assert response["summary"] == {
        "count": 2,
        "by_status": {"ASSIGNED": 1, "PROPOSED": 1},
        "by_action_type": {"citation_repair": 1, "retry_generation": 1},
        "latest_updated_at": "2026-08-25T00:01:00Z",
    }


def test_generation_remediation_status_update_allows_valid_transition() -> None:
    record = build_action()
    updated = update_generation_remediation_action_status(
        record,
        {
            "action_status": "ASSIGNED",
            "evidence_previews": ["Task was assigned to the CX repair queue."],
            "result_ref": {
                "source_service": "nex-cx",
                "ref_type": "repair_execution",
                "ref_id": "cx-repair-run-001",
            },
        },
        request_id="request-update",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        updated_at="2026-08-25T00:05:00Z",
    )

    assert updated["action_status"] == "ASSIGNED"
    assert updated["request_id"] == "request-update"
    assert updated["updated_at"] == "2026-08-25T00:05:00Z"
    assert updated["evidence"]["evidence_previews"] == [
        "Task was assigned to the CX repair queue."
    ]
    assert updated["result_ref"] == {
        "source_service": "nex-cx",
        "ref_type": "repair_execution",
        "ref_id": "cx-repair-run-001",
        "relation": "result_of",
    }


def test_generation_remediation_status_update_rejects_invalid_transition() -> None:
    record = build_action(action_status="COMPLETED")

    with pytest.raises(GenerationRemediationError) as exc_info:
        update_generation_remediation_action_status(
            record,
            {"action_status": "IN_PROGRESS"},
            request_id="request-invalid-transition",
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.error_code == (
        "ag.generation_remediation_status_transition_invalid"
    )


def test_generation_remediation_status_update_rejects_sensitive_payload() -> None:
    with pytest.raises(GenerationRemediationError) as exc_info:
        update_generation_remediation_action_status(
            build_action(),
            {
                "action_status": "ASSIGNED",
                "raw_generation_output": "do not persist raw generated text",
            },
            request_id="request-redaction",
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.error_code == "ag.generation_remediation_sensitive_payload"


def test_emit_generation_remediation_task_event_records_safe_event() -> None:
    event_store = InMemoryOperationalEventStore()
    audit_emitter = OperationalEventEmitter(service_id="nex-ag", store=event_store)
    result = emit_generation_remediation_task_event(
        audit_emitter,
        build_action(),
        event_type="ag.generation_remediation.task_recorded",
    )

    assert result.ok is True
    event = event_store.list_events()[0]
    assert event["event_type"] == "ag.generation_remediation.task_recorded"
    assert event["details"]["action_type"] == "citation_repair"
    assert "raw_generation_output" not in event["details"]


def test_generation_remediation_routes_create_list_get_and_update() -> None:
    client, store, event_store = build_route_client()
    create_response = client.post(
        "/admin/v1/generation-audit/generations/cx-gen-001/remediation-tasks",
        headers=auth_headers(),
        json=action_payload(remediation_action_id="ag-remediation-route"),
    )
    list_response = client.get(
        "/admin/v1/generation-audit/generations/cx-gen-001/remediation-tasks",
        headers=auth_headers(),
    )
    get_response = client.get(
        (
            "/admin/v1/generation-audit/generations/cx-gen-001"
            "/remediation-tasks/ag-remediation-route"
        ),
        headers=auth_headers(),
    )
    patch_response = client.patch(
        (
            "/admin/v1/generation-audit/generations/cx-gen-001"
            "/remediation-tasks/ag-remediation-route"
        ),
        headers=auth_headers(),
        json={"action_status": "ASSIGNED"},
    )

    assert create_response.status_code == 202
    assert list_response.status_code == 200
    assert list_response.json()["summary"]["count"] == 1
    assert get_response.status_code == 200
    assert patch_response.status_code == 200
    assert patch_response.json()["action_status"] == "ASSIGNED"
    assert store.get("ag-remediation-route")["action_status"] == "ASSIGNED"
    assert [
        event["event_type"] for event in event_store.list_events()
    ] == [
        "ag.generation_remediation.task_status_updated",
        "ag.generation_remediation.task_recorded",
    ]


def test_generation_remediation_routes_reject_auth_invalid_and_cross_generation() -> None:
    client, _, _ = build_route_client()
    create_unauthorized = client.post(
        "/admin/v1/generation-audit/generations/cx-gen-001/remediation-tasks",
        json=action_payload(remediation_action_id="ag-remediation-auth-create"),
    )
    unauthorized = client.get(
        "/admin/v1/generation-audit/generations/cx-gen-001/remediation-tasks"
    )
    get_unauthorized = client.get(
        (
            "/admin/v1/generation-audit/generations/cx-gen-001"
            "/remediation-tasks/ag-remediation-auth-get"
        )
    )
    patch_unauthorized = client.patch(
        (
            "/admin/v1/generation-audit/generations/cx-gen-001"
            "/remediation-tasks/ag-remediation-auth-patch"
        ),
        json={"action_status": "ASSIGNED"},
    )
    invalid = client.post(
        "/admin/v1/generation-audit/generations/cx-gen-001/remediation-tasks",
        headers=auth_headers(),
        json={"action_type": "citation_repair", "raw_generation_output": "bad"},
    )
    client.post(
        "/admin/v1/generation-audit/generations/cx-gen-001/remediation-tasks",
        headers=auth_headers(),
        json=action_payload(remediation_action_id="ag-remediation-private"),
    )
    missing = client.get(
        (
            "/admin/v1/generation-audit/generations/cx-gen-other"
            "/remediation-tasks/ag-remediation-private"
        ),
        headers=auth_headers(),
    )
    bad_transition = client.patch(
        (
            "/admin/v1/generation-audit/generations/cx-gen-001"
            "/remediation-tasks/ag-remediation-private"
        ),
        headers=auth_headers(),
        json={"action_status": "COMPLETED"},
    )
    missing_patch = client.patch(
        (
            "/admin/v1/generation-audit/generations/cx-gen-other"
            "/remediation-tasks/ag-remediation-private"
        ),
        headers=auth_headers(),
        json={"action_status": "ASSIGNED"},
    )

    assert create_unauthorized.status_code == 401
    assert unauthorized.status_code == 401
    assert get_unauthorized.status_code == 401
    assert patch_unauthorized.status_code == 401
    assert invalid.status_code == 422
    assert invalid.json()["error_code"] == "ag.generation_remediation_sensitive_payload"
    assert missing.status_code == 404
    assert bad_transition.status_code == 409
    assert missing_patch.status_code == 404


def test_generation_remediation_route_reports_store_failures() -> None:
    class FailingStore:
        def save(self, record: dict[str, Any]) -> dict[str, Any]:
            raise GenerationRemediationError(
                status_code=503,
                error_code="ag.generation_remediation_store_unavailable",
                detail="store down",
            )

        def get(self, remediation_action_id: str) -> None:
            return None

        def list_for_generation(self, cx_generation_id: str) -> list[dict[str, Any]]:
            raise GenerationRemediationError(
                status_code=503,
                error_code="ag.generation_remediation_store_unavailable",
                detail="store down",
            )

    client, _, _ = build_route_client(store=FailingStore())
    create_response = client.post(
        "/admin/v1/generation-audit/generations/cx-gen-001/remediation-tasks",
        headers=auth_headers(),
        json=action_payload(remediation_action_id="ag-remediation-store-failed"),
    )
    list_response = client.get(
        "/admin/v1/generation-audit/generations/cx-gen-001/remediation-tasks",
        headers=auth_headers(),
    )

    assert create_response.status_code == 503
    assert list_response.status_code == 503


def test_generation_remediation_get_route_reports_store_failure() -> None:
    class FailingGetStore:
        def save(self, record: dict[str, Any]) -> dict[str, Any]:
            return record

        def get(self, remediation_action_id: str) -> None:
            raise GenerationRemediationError(
                status_code=503,
                error_code="ag.generation_remediation_store_unavailable",
                detail="store down",
            )

        def list_for_generation(self, cx_generation_id: str) -> list[dict[str, Any]]:
            return []

    client, _, _ = build_route_client(store=FailingGetStore())
    response = client.get(
        (
            "/admin/v1/generation-audit/generations/cx-gen-001"
            "/remediation-tasks/ag-remediation-store-failed"
        ),
        headers=auth_headers(),
    )

    assert response.status_code == 503


def test_sqlalchemy_generation_remediation_store_round_trips_sqlite() -> None:
    store, engine = sqlite_remediation_store()
    try:
        first = build_action(remediation_action_id="ag-remediation-sql-001")
        second = build_generation_remediation_action(
            action_payload(
                remediation_action_id="ag-remediation-sql-002",
                action_type="retry_generation",
            ),
            cx_generation_id="cx-gen-sql-002",
            request_id="request-sql-002",
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            created_at="2026-08-25T00:00:00Z",
        )

        store.save(first)
        store.save(second)
        loaded = store.get("ag-remediation-sql-001")
        listed = store.list_for_generation("cx-gen-001")
        recent = store.list_recent(limit=10)

        assert loaded == first
        assert [item["remediation_action_id"] for item in listed] == [
            "ag-remediation-sql-001"
        ]
        assert [item["remediation_action_id"] for item in recent] == [
            "ag-remediation-sql-001",
            "ag-remediation-sql-002",
        ]
        first["action_status"] = "ASSIGNED"
        first["updated_at"] = "2026-08-25T00:05:00Z"
        store.save(first)
        assert store.get("ag-remediation-sql-001")["action_status"] == "ASSIGNED"
        assert store.list_recent(limit=0)[0]["remediation_action_id"] == (
            "ag-remediation-sql-001"
        )
        assert store.delete("missing") == 0
        assert store.delete("ag-remediation-sql-001") == 1
    finally:
        engine.dispose()


def test_sqlalchemy_generation_remediation_store_wraps_sql_failures() -> None:
    store, engine = sqlite_remediation_store()
    engine.dispose()

    for operation in (
        lambda: store.save(build_action(remediation_action_id="ag-remediation-sql-down")),
        lambda: store.get("ag-remediation-sql-down"),
        lambda: store.list_for_generation("cx-gen-001"),
        lambda: store.list_recent(limit=1),
        lambda: store.delete("ag-remediation-sql-down"),
    ):
        with pytest.raises(GenerationRemediationError) as exc_info:
            operation()
        assert exc_info.value.status_code == 503
        assert exc_info.value.error_code == (
            "ag.generation_remediation_store_unavailable"
        )


def test_default_generation_remediation_store_uses_persistence_session_factory() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    session_factory = object()
    app.state.nex_persistence = SimpleNamespace(api_session_factory=session_factory)

    store = default_generation_remediation_task_store(app)

    assert isinstance(store, SqlAlchemyGenerationRemediationTaskStore)
    app_without_persistence = build_service_app(SERVICE_SPECS["nex-ag"])
    assert isinstance(
        default_generation_remediation_task_store(app_without_persistence),
        GenerationRemediationTaskStore,
    )


def test_generation_remediation_sql_helpers_cover_json_and_datetime_paths() -> None:
    assert _json_param_expr("metadata", "postgresql") == "CAST(:metadata AS jsonb)"
    assert _json_param_expr("metadata", "sqlite") == ":metadata"
    assert _json_value("{\"ok\": true}", {}) == {"ok": True}
    assert _json_value(None, []) == []
    assert _json_value({"already": "decoded"}, {}) == {"already": "decoded"}
    assert _datetime_value(datetime(2026, 8, 25, tzinfo=UTC)) == "2026-08-25T00:00:00Z"
    assert _datetime_value(date(2026, 8, 25)) == "2026-08-25"
    assert _datetime_value("2026-08-25T00:00:00Z") == "2026-08-25T00:00:00Z"
    assert _normalize_remediation_list_limit("bad") == 500
    assert _normalize_remediation_list_limit(-5) == 1
    assert _normalize_remediation_list_limit(501) == 500


def test_nex_ag_openapi_includes_generation_remediation_task_routes() -> None:
    spec = ag_openapi_spec()
    paths = spec["paths"]

    assert (
        "/admin/v1/generation-audit/generations/{cx_generation_id}/remediation-tasks"
        in paths
    )
    assert (
        "/admin/v1/generation-audit/generations/{cx_generation_id}"
        "/remediation-tasks/{remediation_action_id}"
    ) in paths
    assert "AgGenerationRemediationAction" in spec["components"]["schemas"]


@pytest.mark.parametrize(
    ("overrides", "error_code"),
    [
        ({}, "ag.generation_remediation_action_type_required"),
        (
            {"action_type": "unknown"},
            "ag.generation_remediation_action_type_unsupported",
        ),
        (
            {"action_type": "citation_repair", "action_status": "DONE"},
            "ag.generation_remediation_action_status_unsupported",
        ),
        (
            {"action_type": "citation_repair", "priority": "SOON"},
            "ag.generation_remediation_priority_unsupported",
        ),
        (
            {"action_type": "citation_repair", "owner_ref": "bad"},
            "ag.generation_remediation_owner_ref_invalid",
        ),
        (
            {"action_type": "citation_repair", "reason_codes": "bad"},
            "ag.generation_remediation_reason_codes_invalid",
        ),
        (
            {"action_type": "citation_repair", "reason_codes": ["bad"]},
            "ag.generation_remediation_reason_code_unsupported",
        ),
        (
            {"action_type": "citation_repair", "source_refs": "bad"},
            "ag.generation_remediation_source_refs_invalid",
        ),
        (
            {"action_type": "citation_repair", "source_refs": ["bad"]},
            "ag.generation_remediation_source_ref_invalid",
        ),
        (
            {"action_type": "citation_repair", "result_ref": "bad"},
            "ag.generation_remediation_result_ref_invalid",
        ),
        (
            {
                "action_type": "citation_repair",
                "result_ref": {
                    "source_service": "nex-ae-api",
                    "ref_type": "repair_execution",
                    "ref_id": "bad-result-source",
                },
            },
            "ag.generation_remediation_source_service_unsupported",
        ),
        (
            {"action_type": "citation_repair", "evidence_hashes": ["not-sha"]},
            "ag.generation_remediation_evidence_hash_invalid",
        ),
        (
            {"action_type": "citation_repair", "raw_generation_output": "bad"},
            "ag.generation_remediation_sensitive_payload",
        ),
    ],
)
def test_generation_remediation_action_builder_rejects_invalid_payloads(
    overrides: dict[str, object],
    error_code: str,
) -> None:
    with pytest.raises(GenerationRemediationError) as exc_info:
        build_generation_remediation_action(
            overrides,
            cx_generation_id="cx-gen-001",
            request_id="request-invalid",
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            created_at="2026-08-25T00:00:00Z",
        )

    assert exc_info.value.error_code == error_code


def test_generation_remediation_error_stringifies_detail() -> None:
    error = GenerationRemediationError(
        status_code=422,
        error_code="ag.generation_remediation_test",
        detail="human readable detail",
    )

    assert str(error) == "human readable detail"


def test_generation_remediation_action_builder_requires_generation_id() -> None:
    with pytest.raises(GenerationRemediationError) as exc_info:
        build_generation_remediation_action(
            {"action_type": "retry_generation"},
            cx_generation_id=" ",
            request_id="request-invalid",
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        )

    assert exc_info.value.error_code == (
        "ag.generation_remediation_cx_generation_id_required"
    )


def test_generation_remediation_list_helpers_cover_invalid_and_dedup_paths() -> None:
    assert reason_code_list(["other", "other"]) == ["other"]
    assert source_ref_list(None) == []
    assert evidence_summary(
        {
            "evidence_hashes": ["a" * 64, "a" * 64],
            "evidence_previews": ["preview", "preview"],
        }
    ) == {
        "evidence_hashes": ["a" * 64],
        "evidence_previews": ["preview"],
        "raw_evidence_stored": False,
    }

    with pytest.raises(GenerationRemediationError):
        hash_list("bad")
    with pytest.raises(GenerationRemediationError):
        preview_list("bad")
    with pytest.raises(GenerationRemediationError):
        result_ref({"source_service": "nex-cx", "ref_type": "bad", "ref_id": "x"})


def test_generation_remediation_candidate_projection_builds_citation_repair() -> None:
    projection = build_projection([rollup_item()])
    candidate = projection["items"][0]
    action = candidate["action"]

    Draft202012Validator(remediation_action_schema()).validate(action)
    assert projection["projection_schema_version"] == (
        REMEDIATION_CANDIDATE_PROJECTION_SCHEMA_VERSION
    )
    assert projection["summary"] == {
        "candidate_count": 1,
        "returned_count": 1,
        "by_action_type": {"citation_repair": 1},
        "by_priority": {"HIGH": 1},
        "skipped_count": 0,
    }
    assert candidate["candidate_reason"] == "operator_requested_cx_repair"
    assert action["action_type"] == "citation_repair"
    assert action["reason_codes"] == [
        "negative_user_feedback",
        "operator_requested_repair",
        "citation_quality",
    ]
    assert action["metadata"]["action_source"] == "operator_disposition"
    assert action["source_refs"] == [
        {
            "source_service": "nex-ag",
            "ref_type": "generation_quality",
            "ref_id": "cx-gen-001",
            "relation": "caused_by",
        },
        {
            "source_service": "nex-ae-api",
            "ref_type": "feedback",
            "ref_id": "ae-feedback-001",
            "relation": "caused_by",
        },
        {
            "source_service": "nex-ag",
            "ref_type": "operator_disposition",
            "ref_id": "ag-gq-disposition-001",
            "relation": "recommended_by",
        },
    ]


def test_generation_remediation_candidate_projection_selects_retrieval_repair() -> None:
    projection = build_projection(
        [
            rollup_item(
                cx_generation_id="cx-gen-retrieval",
                severity="ERROR",
                quality={
                    "count": 1,
                    "attention_required": True,
                    "issue_codes": ["NO_ANSWER_FOR_SCOPE"],
                    "coverage_statuses": ["NO_ANSWER"],
                    "boundary_statuses": [],
                    "recommended_actions": ["repair_retrieval"],
                },
                feedback={"negative_count": 0},
                disposition={"latest_status": None, "latest_action": None},
            )
        ]
    )
    action = projection["items"][0]["action"]

    assert action["action_type"] == "retrieval_repair"
    assert action["priority"] == "URGENT"
    assert action["reason_codes"] == ["retrieval_quality"]
    assert action["metadata"]["action_source"] == "candidate_projection"


def test_generation_remediation_candidate_projection_selects_retry_generation() -> None:
    projection = build_projection(
        [
            rollup_item(
                cx_generation_id="cx-gen-retry",
                quality={
                    "count": 1,
                    "attention_required": True,
                    "issue_codes": ["METADATA_GAP_CX_GROUNDED_RESPONSE_QUALITY_FIELDS"],
                    "coverage_statuses": [],
                    "boundary_statuses": [],
                    "recommended_actions": [],
                },
                feedback={"negative_count": 0},
                disposition={
                    "latest_disposition_id": "ag-gq-disposition-retry",
                    "latest_action": "needs_cx_repair",
                    "latest_status": "IN_REPAIR",
                },
            )
        ]
    )
    action = projection["items"][0]["action"]

    assert action["action_type"] == "retry_generation"
    assert action["reason_codes"] == [
        "operator_requested_repair",
        "generation_quality",
        "metadata_gap",
    ]


def test_generation_remediation_candidate_projection_uses_operator_followup() -> None:
    projection = build_projection(
        [
            rollup_item(
                cx_generation_id="cx-gen-feedback-only",
                quality={
                    "count": 0,
                    "attention_required": False,
                    "issue_codes": [],
                    "coverage_statuses": [],
                    "boundary_statuses": [],
                    "recommended_actions": [],
                },
                feedback={"negative_count": 3, "latest_feedback_id": "ae-feedback-003"},
                disposition={"latest_action": None, "latest_disposition_id": None},
            )
        ]
    )
    action = projection["items"][0]["action"]

    assert projection["items"][0]["candidate_reason"] == (
        "negative_feedback_needs_triage"
    )
    assert action["action_type"] == "operator_followup"
    assert action["priority"] == "HIGH"
    assert action["reason_codes"] == ["negative_user_feedback"]


def test_generation_remediation_candidate_projection_skips_closed_ok_and_missing_ids() -> None:
    projection = build_projection(
        [
            rollup_item(cx_generation_id="cx-gen-ok", attention_status="OK"),
            rollup_item(cx_generation_id="cx-gen-closed", attention_status="CLOSED"),
            rollup_item(cx_generation_id=" "),
        ]
    )

    assert projection["items"] == []
    assert projection["summary"]["candidate_count"] == 0
    assert projection["summary"]["skipped_count"] == 3


def test_generation_remediation_candidate_projection_sorts_and_limits_candidates() -> None:
    projection = build_projection(
        [
            rollup_item(
                cx_generation_id="cx-gen-normal",
                severity="INFO",
                feedback={"negative_count": 0},
                disposition={"latest_action": None},
                quality={"count": 1, "attention_required": True, "issue_codes": []},
            ),
            rollup_item(
                cx_generation_id="cx-gen-urgent",
                severity="ERROR",
                quality={"count": 1, "attention_required": True, "issue_codes": []},
            ),
        ],
        limit=1,
    )

    assert projection["summary"]["candidate_count"] == 2
    assert projection["summary"]["returned_count"] == 1
    assert projection["items"][0]["cx_generation_id"] == "cx-gen-urgent"


def test_generation_remediation_candidate_projection_accepts_generator_and_bad_limit() -> None:
    projection = build_generation_remediation_candidate_projection(
        rollup_items=(item for item in [rollup_item()]),
        request_id="request-generator",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        limit="bad",  # type: ignore[arg-type]
    )

    assert projection["summary"]["returned_count"] == 1
    assert projection["redaction_summary"] == {
        "raw_prompt_included": False,
        "raw_generation_output_included": False,
        "raw_feedback_comment_included": False,
        "raw_operator_note_included": False,
    }


def test_generation_remediation_candidate_projection_covers_operator_branches() -> None:
    projection = build_projection(
        [
            rollup_item(
                cx_generation_id="cx-gen-ae-followup",
                disposition={
                    "latest_disposition_id": "ag-gq-disposition-ae",
                    "latest_action": "needs_ae_followup",
                    "latest_status": "IN_REPAIR",
                },
            ),
            rollup_item(
                cx_generation_id="cx-gen-escalated",
                severity="INFO",
                quality={"count": 0, "attention_required": False},
                feedback={"negative_count": 0},
                disposition={
                    "latest_disposition_id": "ag-gq-disposition-escalated",
                    "latest_action": "escalated",
                    "latest_status": "ESCALATED",
                },
            ),
            rollup_item(
                cx_generation_id="cx-gen-in-progress",
                attention_status="IN_PROGRESS",
                severity="INFO",
                quality={"count": 0, "attention_required": False},
                feedback={"negative_count": "not-a-number"},
                disposition={},
            ),
            rollup_item(
                cx_generation_id="cx-gen-open-fallback",
                severity="INFO",
                quality={
                    "count": 1,
                    "attention_required": True,
                    "issue_codes": ["UNCLASSIFIED_WARNING"],
                },
                feedback={"negative_count": 0},
                disposition={},
            ),
            rollup_item(
                cx_generation_id="cx-gen-no-signal",
                severity="INFO",
                quality={"count": 0, "attention_required": False},
                feedback={"negative_count": 0},
                disposition={},
            ),
        ],
        limit=10,
    )
    items = {item["cx_generation_id"]: item for item in projection["items"]}

    assert items["cx-gen-ae-followup"]["candidate_reason"] == (
        "operator_requested_ae_followup"
    )
    assert items["cx-gen-ae-followup"]["action"]["action_type"] == "operator_followup"
    assert items["cx-gen-escalated"]["candidate_reason"] == (
        "operator_escalated_generation_quality"
    )
    assert items["cx-gen-escalated"]["action"]["action_type"] == "prompt_policy_review"
    assert items["cx-gen-escalated"]["action"]["priority"] == "URGENT"
    assert items["cx-gen-escalated"]["action"]["reason_codes"] == [
        "operator_requested_repair",
        "policy_review",
    ]
    assert items["cx-gen-in-progress"]["candidate_reason"] == (
        "open_operator_disposition_in_progress"
    )
    assert items["cx-gen-in-progress"]["action"]["priority"] == "HIGH"
    assert items["cx-gen-open-fallback"]["action"]["action_type"] == "retry_generation"
    assert items["cx-gen-no-signal"]["candidate_reason"] == (
        "attention_signal_needs_triage"
    )
    assert items["cx-gen-no-signal"]["action"]["reason_codes"] == ["other"]


def test_generation_remediation_validation_helpers_cover_invalid_scalar_branches() -> None:
    with pytest.raises(GenerationRemediationError) as reason_exc:
        reason_code_list([" "])
    assert reason_exc.value.error_code == "ag.generation_remediation_reason_code_invalid"

    with pytest.raises(GenerationRemediationError) as choice_exc:
        build_action(action_status=" ")
    assert choice_exc.value.error_code == "ag.generation_remediation_action_status_invalid"
