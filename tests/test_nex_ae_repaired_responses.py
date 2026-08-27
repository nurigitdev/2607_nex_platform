from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import nex_ae_api.repaired_responses as repaired_module
import nex_ae_api.repaired_response_decisions as decision_module
from nex_ae_api.repaired_response_decisions import (
    AE_REPAIRED_RESPONSE_DECISION_COLLECTION_SCHEMA_VERSION,
    AE_REPAIRED_RESPONSE_DECISION_SCHEMA_VERSION,
    DECISION_ACTION_ACCEPT_REPAIR,
    DECISION_ACTION_KEEP_ORIGINAL,
    RepairedResponseDecisionError,
    RepairedResponseDecisionStore,
    SqlAlchemyRepairedResponseDecisionStore,
    actor_claims_ref_from_decision_payload,
    assert_repaired_response_decision_payload_redaction_safe,
    build_repaired_response_decision_collection,
    build_repaired_response_decision_record,
    decision_action_from_payload,
    decision_reason_codes_from_payload,
    default_repaired_response_decision_store,
    find_sensitive_repaired_response_decision_keys,
    register_repaired_response_decision_routes,
    selected_cx_generation_id_for_action,
    submitted_via_from_payload,
    validate_repaired_response_decision_record,
)
from nex_ae_api.repaired_responses import (
    AE_REPAIRED_RESPONSE_HANDOFF_SCHEMA_VERSION,
    DEFAULT_HANDOFF_STATUS,
    RepairedResponseHandoffError,
    RepairedResponseHandoffStore,
    SqlAlchemyRepairedResponseHandoffStore,
    actor_claims_ref_from_payload,
    assert_repaired_response_handoff_redaction_safe,
    build_repaired_response_handoff_record,
    default_repaired_response_handoff_store,
    find_sensitive_repaired_response_handoff_keys,
    presentation_mode_from_payload,
    register_repaired_response_handoff_routes,
    repaired_response_payload_with_path_interaction_id,
    validate_repaired_response_handoff_record,
)
from nex_ae_api.repaired_response_review import (
    AE_REPAIRED_RESPONSE_REVIEW_PROJECTION_SCHEMA_VERSION,
    PRIMARY_REVIEW_ACTIONS,
    RepairedResponseReviewProjectionError,
    assert_repaired_response_review_projection_redaction_safe,
    build_repaired_response_review_collection,
    build_repaired_response_review_projection,
    decision_submit_path_for_handoff,
    find_sensitive_repaired_response_review_projection_keys,
    validate_repaired_response_review_projection,
)
from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token


ROOT = Path(__file__).parents[1]
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


def repaired_response_schema() -> dict[str, Any]:
    return json.loads(
        (
            ROOT
            / "contracts"
            / "schemas"
            / "service"
            / "nex_ae_api"
            / "repaired_response_handoff.v1.schema.json"
        ).read_text(encoding="utf-8")
    )


def repaired_response_review_schema() -> dict[str, Any]:
    return json.loads(
        (
            ROOT
            / "contracts"
            / "schemas"
            / "service"
            / "nex_ae_api"
            / "repaired_response_review_projection.v1.schema.json"
        ).read_text(encoding="utf-8")
    )


def repaired_response_decision_schema() -> dict[str, Any]:
    return json.loads(
        (
            ROOT
            / "contracts"
            / "schemas"
            / "service"
            / "nex_ae_api"
            / "repaired_response_decision.v1.schema.json"
        ).read_text(encoding="utf-8")
    )


def source_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "tenant_id": "tenant-001",
        "workspace_id": "workspace-001",
        "owner_user_id": "user-001",
        "chat_document_id": "chat-doc-001",
        "interaction_id": "interaction-001",
        "original_cx_generation_id": "cx-gen-001",
        "remediation_action_id": "ag-remediation-action-001",
        "handoff_request_id": "ae-repaired-request-001",
        "actor_claims_ref": {
            "actor_type": "user",
            "actor_id": "user-001",
            "tenant_id": "tenant-001",
        },
    }
    payload.update(overrides)
    return payload


def cx_remediation_detail(**overrides: Any) -> dict[str, Any]:
    lineage = {
        "lineage_schema_version": "cx_repaired_generation_lineage.v1",
        "lineage_status": "LINKED",
        "parent_cx_generation_id": "cx-gen-001",
        "root_cx_generation_id": "cx-gen-001",
        "repair_cx_generation_id": "cx-gen-repair-001",
        "remediation_action_id": "ag-remediation-action-001",
        "action_type": "citation_repair",
        "lineage_type": "repair",
        "execution_status": "SUCCEEDED",
        "attempt_no": 1,
        "result_ref": {
            "source_service": "nex-cx",
            "ref_type": "repair_execution",
            "ref_id": "ag-remediation-action-001",
            "relation": "result_of",
        },
        "diagnostics": {
            "lineage_consistent": True,
            "repair_generation_linked": True,
            "result_ref_present": True,
            "result_ref_matches_remediation_action": True,
            "parent_generation_mutated": False,
        },
        "debug_paths": {
            "parent_generation_path": "/api/v1/generations/cx-gen-001",
            "root_generation_path": "/api/v1/generations/cx-gen-001",
            "repair_generation_path": "/api/v1/generations/cx-gen-repair-001",
            "cx_remediation_execution_path": (
                "/api/v1/generations/cx-gen-001/remediation-executions/"
                "ag-remediation-action-001"
            ),
        },
        "redaction_summary": {
            "raw_content_included": False,
            "prompt_text_included": False,
            "evidence_text_included": False,
            "provider_detail_included": False,
        },
    }
    detail = {
        "detail_schema_version": "cx_remediation_execution_detail.v1",
        "projection_status": "READY",
        "checked_at": "2026-08-27T00:00:00Z",
        "parent_cx_generation_id": "cx-gen-001",
        "remediation_action_id": "ag-remediation-action-001",
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "execution_status": "SUCCEEDED",
        "execution": {
            "result_schema_version": "cx_remediation_execution_result.v1",
            "remediation_action_id": "ag-remediation-action-001",
            "parent_cx_generation_id": "cx-gen-001",
            "repair_cx_generation_id": "cx-gen-repair-001",
            "execution_status": "SUCCEEDED",
        },
        "repaired_generation_lineage": lineage,
        "attention_required": False,
        "debug_paths": {},
        "redaction_summary": {
            "raw_content_included": False,
            "prompt_text_included": False,
            "evidence_text_included": False,
            "provider_detail_included": False,
        },
    }
    detail.update(overrides)
    return detail


def repaired_generation_record(**overrides: Any) -> dict[str, Any]:
    record = {
        "record_schema_version": "cx_generation_execution_record.v1",
        "cx_generation_id": "cx-gen-repair-001",
        "status": "COMPLETED",
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "alias": "general-llm-default",
        "provider_capability": "generation",
        "mo_generation_id": "mo-gen-repair-001",
        "request_metadata": {
            "provider_prompt_package_hash": "a" * 64,
            "generation_request_hash": "b" * 64,
            "response_format_type": "text",
            "source_has_messages": True,
            "source_has_prompt": False,
            "grounding_required": True,
            "retrieval_package_id": "cx-ret-001",
            "retrieval_package_hash": "d" * 64,
            "selected_evidence_count": 2,
            "structured_draft_id": "draft-repair-001",
            "draft_validation_status": "VALIDATED",
            "grounded_response_quality_status": "PASS",
            "grounded_response_quality_issue_count": 0,
        },
        "response_metadata": {
            "finish_reason": "STOP",
            "output_hash": "c" * 64,
            "output_preview": "Repaired answer with citation support.",
        },
        "mo_runtime_metadata": {
            "request_id": REQUEST_ID,
            "trace_id": TRACE_ID,
        },
        "usage": {
            "input_tokens": 12,
            "output_tokens": 16,
            "total_tokens": 28,
        },
        "created_at": "2026-08-27T00:00:00Z",
        "updated_at": "2026-08-27T00:00:00Z",
    }
    record.update(overrides)
    return record


def build_handoff(
    *,
    payload: dict[str, Any] | None = None,
    detail: dict[str, Any] | None = None,
    generation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return build_repaired_response_handoff_record(
        source_payload=payload or source_payload(),
        cx_remediation_detail=detail or cx_remediation_detail(),
        repaired_generation_record=generation or repaired_generation_record(),
        handoff_request_id=None,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        created_at="2026-08-27T00:00:00Z",
    )


class FakeCxRepairedResponseSourceClient:
    def __init__(
        self,
        *,
        detail: dict[str, Any] | None = None,
        generation: dict[str, Any] | None = None,
    ) -> None:
        self.detail = detail or cx_remediation_detail()
        self.generation = generation or repaired_generation_record()
        self.calls: list[dict[str, Any]] = []

    def get_remediation_execution_detail(
        self,
        *,
        parent_cx_generation_id: str,
        remediation_action_id: str,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "method": "detail",
                "parent_cx_generation_id": parent_cx_generation_id,
                "remediation_action_id": remediation_action_id,
                "request_id": request_id,
                "trace_id": trace_id,
            }
        )
        return self.detail

    def get_repaired_generation_record(
        self,
        *,
        cx_generation_id: str,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "method": "generation",
                "cx_generation_id": cx_generation_id,
                "request_id": request_id,
                "trace_id": trace_id,
            }
        )
        return self.generation


def auth_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-ag", audience="nex-ae-api")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def build_handoff_test_client(
    *,
    store: RepairedResponseHandoffStore | None = None,
    cx_client: FakeCxRepairedResponseSourceClient | None = None,
) -> tuple[TestClient, RepairedResponseHandoffStore, FakeCxRepairedResponseSourceClient]:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    selected_store = store or RepairedResponseHandoffStore()
    selected_client = cx_client or FakeCxRepairedResponseSourceClient()
    register_repaired_response_handoff_routes(
        app,
        store=selected_store,
        cx_client=selected_client,
    )
    return TestClient(app), selected_store, selected_client


def build_decision_test_client(
    *,
    handoff_store: RepairedResponseHandoffStore | None = None,
    decision_store: RepairedResponseDecisionStore | None = None,
    handoff: dict[str, Any] | None = None,
) -> tuple[
    TestClient,
    dict[str, Any],
    RepairedResponseHandoffStore,
    RepairedResponseDecisionStore,
]:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    selected_handoff_store = handoff_store or RepairedResponseHandoffStore()
    selected_decision_store = decision_store or RepairedResponseDecisionStore()
    selected_handoff = handoff or build_handoff()
    selected_handoff_store.save(selected_handoff)
    register_repaired_response_decision_routes(
        app,
        handoff_store=selected_handoff_store,
        decision_store=selected_decision_store,
    )
    return TestClient(app), selected_handoff, selected_handoff_store, selected_decision_store


def sqlite_handoff_session_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE ae_repaired_response_handoffs (
                    repaired_response_handoff_id TEXT PRIMARY KEY,
                    handoff_schema_version TEXT NOT NULL,
                    handoff_request_id TEXT NOT NULL,
                    handoff_status TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL,
                    chat_document_id TEXT NOT NULL,
                    interaction_id TEXT NOT NULL,
                    original_cx_generation_id TEXT NOT NULL,
                    parent_cx_generation_id TEXT NOT NULL,
                    root_cx_generation_id TEXT NOT NULL,
                    repair_cx_generation_id TEXT NOT NULL,
                    remediation_action_id TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    actor_claims_ref TEXT NOT NULL,
                    source TEXT NOT NULL,
                    repaired_response TEXT NOT NULL,
                    lineage TEXT NOT NULL,
                    user_surface TEXT NOT NULL,
                    links TEXT NOT NULL,
                    redaction_summary TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def sqlite_decision_session_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE ae_repaired_response_decisions (
                    repaired_response_decision_id TEXT PRIMARY KEY,
                    decision_schema_version TEXT NOT NULL,
                    decision_request_id TEXT NOT NULL UNIQUE,
                    decision_status TEXT NOT NULL,
                    decision_action TEXT NOT NULL,
                    repaired_response_handoff_id TEXT NOT NULL,
                    handoff_request_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL,
                    chat_document_id TEXT NOT NULL,
                    interaction_id TEXT NOT NULL,
                    parent_cx_generation_id TEXT NOT NULL,
                    repair_cx_generation_id TEXT NOT NULL,
                    selected_cx_generation_id TEXT NOT NULL,
                    rejected_cx_generation_id TEXT NOT NULL,
                    remediation_action_id TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    actor_claims_ref TEXT NOT NULL,
                    decision_reason_codes TEXT NOT NULL,
                    decision_comment_hash TEXT,
                    decision_comment_preview TEXT,
                    metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def test_build_repaired_response_handoff_record_is_schema_valid_and_raw_safe() -> None:
    record = build_handoff()

    Draft202012Validator(repaired_response_schema()).validate(record)
    assert record["handoff_schema_version"] == AE_REPAIRED_RESPONSE_HANDOFF_SCHEMA_VERSION
    assert record["handoff_status"] == DEFAULT_HANDOFF_STATUS
    assert record["source"]["parent_cx_generation_id"] == "cx-gen-001"
    assert record["source"]["repair_cx_generation_id"] == "cx-gen-repair-001"
    assert record["source"]["result_ref"]["ref_id"] == "ag-remediation-action-001"
    assert record["repaired_response"]["output_hash"] == "c" * 64
    assert record["repaired_response"]["output_preview"] == (
        "Repaired answer with citation support."
    )
    assert record["lineage"]["parent_generation_mutated"] is False
    assert record["user_surface"]["presentation_mode"] == "side_by_side_review"
    assert record["user_surface"]["available_actions"] == [
        "view_original",
        "view_repaired",
        "accept_repair",
        "keep_original",
        "view_lineage",
    ]
    serialized = json.dumps(record, sort_keys=True)
    assert "raw answer body" not in serialized
    assert "hidden prompt" not in serialized
    assert "/data/nex-platform" not in serialized


def test_repaired_response_handoff_store_indexes_unique_handoff_ids() -> None:
    store = RepairedResponseHandoffStore()
    record = build_handoff()

    saved = store.save(record)
    duplicate = store.save(record)

    assert saved == record
    assert duplicate == record
    assert store.get(record["repaired_response_handoff_id"]) == record
    assert store.list_for_interaction(record["interaction_id"]) == [record]
    assert store.list_for_interaction("missing-interaction") == []


def test_sqlalchemy_repaired_response_handoff_store_round_trips_with_sqlite() -> None:
    store = SqlAlchemyRepairedResponseHandoffStore(sqlite_handoff_session_factory())
    record = build_handoff()

    saved = store.save(record)
    loaded = store.get(record["repaired_response_handoff_id"])
    listed = store.list_for_interaction(record["interaction_id"])

    updated = deepcopy(record)
    updated["repaired_response"]["output_preview"] = "Updated safe preview."
    updated["updated_at"] = "2026-08-27T00:01:00Z"
    store.save(updated)
    loaded_after_update = store.get(record["repaired_response_handoff_id"])
    deleted_rows = store.delete(record["repaired_response_handoff_id"])

    assert saved == record
    assert loaded == record
    assert listed == [record]
    assert loaded_after_update == updated
    assert deleted_rows == 1
    assert store.get(record["repaired_response_handoff_id"]) is None


@pytest.mark.parametrize(
    "operation",
    ["save", "get", "list", "delete"],
)
def test_sqlalchemy_repaired_response_handoff_store_maps_database_errors(
    operation: str,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = SqlAlchemyRepairedResponseHandoffStore(
        sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    )
    record = build_handoff()

    with pytest.raises(RepairedResponseHandoffError) as exc_info:
        if operation == "save":
            store.save(record)
        elif operation == "get":
            store.get(record["repaired_response_handoff_id"])
        elif operation == "list":
            store.list_for_interaction(record["interaction_id"])
        else:
            store.delete(record["repaired_response_handoff_id"])

    assert exc_info.value.status_code == 503
    assert exc_info.value.error_code == (
        "ae.repaired_response_handoff_store_unavailable"
    )
    assert exc_info.value.retryable is True


def test_default_repaired_response_handoff_store_uses_persistence_session_factory() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    app.state.nex_persistence = SimpleNamespace(
        api_session_factory=sqlite_handoff_session_factory()
    )

    store = default_repaired_response_handoff_store(app)

    assert isinstance(store, SqlAlchemyRepairedResponseHandoffStore)


def test_default_repaired_response_handoff_store_falls_back_to_memory() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])

    store = default_repaired_response_handoff_store(app)

    assert isinstance(store, RepairedResponseHandoffStore)


def test_repaired_response_handoff_storage_helpers_cover_json_and_dates() -> None:
    record = build_handoff()
    params = repaired_module._handoff_record_params(record)

    assert params["parent_cx_generation_id"] == "cx-gen-001"
    assert params["repair_cx_generation_id"] == "cx-gen-repair-001"
    assert params["remediation_action_id"] == "ag-remediation-action-001"
    assert repaired_module._json_param_expr("source", "postgresql") == (
        "CAST(:source AS jsonb)"
    )
    assert repaired_module._json_param_expr("source", "sqlite") == ":source"
    assert repaired_module._json_value(None, {}) == {}
    assert repaired_module._json_value({"ok": True}, {}) == {"ok": True}
    assert repaired_module._datetime_value(
        repaired_module.datetime(2026, 8, 27, 0, 0, tzinfo=repaired_module.UTC)
    ) == "2026-08-27T00:00:00Z"
    assert repaired_module._datetime_value(
        SimpleNamespace(isoformat=lambda: "2026-08-27T00:00:00+00:00")
    ) == "2026-08-27T00:00:00Z"


def test_repaired_response_handoff_migration_declares_safe_indexes() -> None:
    migration = (
        ROOT
        / "database"
        / "nex-ae-api"
        / "migrations"
        / "0383_ae_repaired_response_handoff_persistence.sql"
    ).read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS ae_repaired_response_handoffs" in migration
    assert "JSONB" in migration
    assert "raw_generation_output" not in migration
    assert "idx_ae_repaired_response_handoffs_owner_time" in migration
    assert "idx_ae_repaired_response_handoffs_interaction_time" in migration


def test_repaired_response_handoff_route_creates_and_reads_record() -> None:
    client, store, cx_client = build_handoff_test_client()

    create_response = client.post(
        "/api/v1/chat/interactions/interaction-001/repaired-response-handoffs",
        json=source_payload(interaction_id="interaction-001"),
        headers=auth_headers(),
    )

    assert create_response.status_code == 202
    created = create_response.json()
    Draft202012Validator(repaired_response_schema()).validate(created)
    assert created["handoff_schema_version"] == AE_REPAIRED_RESPONSE_HANDOFF_SCHEMA_VERSION
    assert created["interaction_id"] == "interaction-001"
    assert created["source"]["repair_cx_generation_id"] == "cx-gen-repair-001"
    assert store.get(created["repaired_response_handoff_id"]) == created
    assert cx_client.calls == [
        {
            "method": "detail",
            "parent_cx_generation_id": "cx-gen-001",
            "remediation_action_id": "ag-remediation-action-001",
            "request_id": REQUEST_ID,
            "trace_id": TRACE_ID,
        },
        {
            "method": "generation",
            "cx_generation_id": "cx-gen-repair-001",
            "request_id": REQUEST_ID,
            "trace_id": TRACE_ID,
        },
    ]

    read_response = client.get(
        (
            "/api/v1/chat/interactions/interaction-001/"
            f"repaired-response-handoffs/{created['repaired_response_handoff_id']}"
        ),
        headers=auth_headers(),
    )

    assert read_response.status_code == 200
    assert read_response.json() == created


def test_repaired_response_handoff_route_defaults_path_interaction_id() -> None:
    client, _store, _cx_client = build_handoff_test_client()
    payload = source_payload(interaction_id=None)

    response = client.post(
        "/api/v1/chat/interactions/interaction-from-path/repaired-response-handoffs",
        json=payload,
        headers=auth_headers(),
    )

    assert response.status_code == 202
    assert response.json()["interaction_id"] == "interaction-from-path"


def test_repaired_response_handoff_route_maps_auth_validation_and_cx_errors() -> None:
    client, store, _cx_client = build_handoff_test_client()

    unauthorized = client.post(
        "/api/v1/chat/interactions/interaction-001/repaired-response-handoffs",
        json=source_payload(interaction_id="interaction-001"),
    )
    assert unauthorized.status_code == 401
    assert unauthorized.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"

    mismatch = client.post(
        "/api/v1/chat/interactions/interaction-001/repaired-response-handoffs",
        json=source_payload(interaction_id="other-interaction"),
        headers=auth_headers(),
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["error_code"] == "ae.repaired_response_interaction_mismatch"

    sensitive = client.post(
        "/api/v1/chat/interactions/interaction-001/repaired-response-handoffs",
        json=source_payload(interaction_id="interaction-001", raw_prompt="hidden"),
        headers=auth_headers(),
    )
    assert sensitive.status_code == 422
    assert sensitive.json()["error_code"] == (
        "ae.cx_repaired_response_source_sensitive_payload"
    )
    assert store.list_for_interaction("interaction-001") == []

    cx_error_client, _store, _cx_client = build_handoff_test_client(
        cx_client=FakeCxRepairedResponseSourceClient(
            detail=cx_remediation_detail(execution_status="RUNNING")
        )
    )
    cx_error = cx_error_client.post(
        "/api/v1/chat/interactions/interaction-001/repaired-response-handoffs",
        json=source_payload(interaction_id="interaction-001"),
        headers=auth_headers(),
    )
    assert cx_error.status_code == 409
    assert cx_error.json()["error_code"] == (
        "ae.repaired_response_execution_not_succeeded"
    )


def test_repaired_response_handoff_detail_route_checks_interaction_scope() -> None:
    client, _store, _cx_client = build_handoff_test_client()
    created = client.post(
        "/api/v1/chat/interactions/interaction-001/repaired-response-handoffs",
        json=source_payload(interaction_id="interaction-001"),
        headers=auth_headers(),
    ).json()

    wrong_scope = client.get(
        (
            "/api/v1/chat/interactions/other-interaction/"
            f"repaired-response-handoffs/{created['repaired_response_handoff_id']}"
        ),
        headers=auth_headers(),
    )
    missing = client.get(
        (
            "/api/v1/chat/interactions/interaction-001/"
            "repaired-response-handoffs/missing-handoff"
        ),
        headers=auth_headers(),
    )
    unauthorized = client.get(
        (
            "/api/v1/chat/interactions/interaction-001/"
            f"repaired-response-handoffs/{created['repaired_response_handoff_id']}"
        )
    )

    assert wrong_scope.status_code == 404
    assert wrong_scope.json()["error_code"] == "ae.repaired_response_handoff_not_found"
    assert missing.status_code == 404
    assert missing.json()["error_code"] == "ae.repaired_response_handoff_not_found"
    assert unauthorized.status_code == 401


def test_repaired_response_payload_with_path_interaction_id_rejects_blank_path() -> None:
    with pytest.raises(RepairedResponseHandoffError) as exc_info:
        repaired_response_payload_with_path_interaction_id({}, "  ")

    assert exc_info.value.status_code == 422
    assert exc_info.value.error_code == "ae.repaired_response_interaction_id_required"


def test_repaired_response_handoff_defaults_ids_actor_and_nullable_refs() -> None:
    detail = cx_remediation_detail()
    detail["repaired_generation_lineage"]["result_ref"] = {
        "source_service": "nex-ag",
        "ref_type": "repair_execution",
        "ref_id": "ag-remediation-action-001",
        "relation": "result_of",
    }
    generation = repaired_generation_record(
        response_metadata={
            "finish_reason": "STOP",
            "output_hash": None,
            "output_preview": "x" * 140,
        },
        request_metadata={
            "grounding_required": False,
            "grounded_response_quality_issue_count": -1,
        },
        usage={},
    )
    record = build_handoff(
        payload=source_payload(
            handoff_request_id=None,
            actor_claims_ref={},
            presentation_mode="append_revision_note",
        ),
        detail=detail,
        generation=generation,
    )

    Draft202012Validator(repaired_response_schema()).validate(record)
    assert record["source"]["result_ref"] is None
    assert record["actor_claims_ref"] == {
        "actor_type": "user",
        "actor_id": "user-001",
        "tenant_id": "tenant-001",
    }
    assert record["repaired_response"]["output_hash"] is None
    assert record["repaired_response"]["output_preview"] == "x" * 120
    assert record["repaired_response"]["quality_summary"] == {
        "grounding_required": False,
        "retrieval_package_id": None,
        "retrieval_package_hash": None,
        "structured_draft_id": None,
        "draft_validation_status": None,
        "grounded_response_quality_status": None,
        "grounded_response_quality_issue_count": 0,
    }
    assert record["user_surface"]["presentation_mode"] == "append_revision_note"


def test_repaired_response_handoff_covers_runtime_default_edges() -> None:
    detail = cx_remediation_detail()
    detail["repaired_generation_lineage"]["result_ref"] = {
        "source_service": "nex-cx",
        "ref_type": "repair_execution",
        "ref_id": "ag-remediation-action-001",
    }
    record = build_repaired_response_handoff_record(
        source_payload=source_payload(handoff_request_id=None),
        cx_remediation_detail=detail,
        repaired_generation_record=repaired_generation_record(
            request_metadata={
                "grounded_response_quality_issue_count": True,
            }
        ),
        handoff_request_id=None,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    Draft202012Validator(repaired_response_schema()).validate(record)
    assert record["created_at"].endswith("Z")
    assert record["updated_at"] == record["created_at"]
    assert record["source"]["result_ref"] is None
    assert (
        record["repaired_response"]["quality_summary"][
            "grounded_response_quality_issue_count"
        ]
        == 0
    )


@pytest.mark.parametrize(
    ("detail_override", "generation_override", "payload_override", "error_code"),
    [
        (
            {"detail_schema_version": "old"},
            {},
            {},
            "ae.repaired_response_cx_detail_invalid",
        ),
        (
            {"execution_status": "RUNNING"},
            {},
            {},
            "ae.repaired_response_execution_not_succeeded",
        ),
        (
            {
                "repaired_generation_lineage": {
                    **cx_remediation_detail()["repaired_generation_lineage"],
                    "lineage_status": "PENDING_REPAIR_GENERATION",
                }
            },
            {},
            {},
            "ae.repaired_response_lineage_not_linked",
        ),
        (
            {
                "repaired_generation_lineage": {
                    **cx_remediation_detail()["repaired_generation_lineage"],
                    "diagnostics": {
                        "lineage_consistent": False,
                        "parent_generation_mutated": False,
                    },
                }
            },
            {},
            {},
            "ae.repaired_response_lineage_invalid",
        ),
        (
            {},
            {"record_schema_version": "old"},
            {},
            "ae.repaired_response_generation_invalid",
        ),
        (
            {},
            {"cx_generation_id": "cx-gen-other"},
            {},
            "ae.repaired_response_generation_mismatch",
        ),
        (
            {},
            {"status": "FAILED"},
            {},
            "ae.repaired_response_generation_not_completed",
        ),
        (
            {},
            {},
            {"original_cx_generation_id": "cx-gen-other"},
            "ae.repaired_response_original_generation_mismatch",
        ),
        (
            {},
            {},
            {"presentation_mode": "raw_replace"},
            "ae.repaired_response_presentation_mode_invalid",
        ),
        (
            {},
            {},
            {"tenant_id": " "},
            "ae.repaired_response_tenant_id_required",
        ),
    ],
)
def test_repaired_response_handoff_rejects_invalid_boundaries(
    detail_override: dict[str, Any],
    generation_override: dict[str, Any],
    payload_override: dict[str, Any],
    error_code: str,
) -> None:
    detail = cx_remediation_detail()
    detail.update(detail_override)
    generation = repaired_generation_record()
    generation.update(generation_override)
    payload = source_payload(**payload_override)

    with pytest.raises(RepairedResponseHandoffError) as exc_info:
        build_handoff(payload=payload, detail=detail, generation=generation)

    assert exc_info.value.error_code == error_code


def test_validate_repaired_response_handoff_record_rejects_mutations() -> None:
    record = build_handoff()

    bad_schema = {**record, "handoff_schema_version": "old"}
    bad_status = {**record, "handoff_status": "PENDING"}
    bad_lineage = deepcopy(record)
    bad_lineage["lineage"]["repair_cx_generation_id"] = "cx-gen-other"
    bad_parent_mutation = deepcopy(record)
    bad_parent_mutation["lineage"]["parent_generation_mutated"] = True
    bad_redaction = deepcopy(record)
    bad_redaction["redaction_summary"]["raw_output_included"] = True

    for candidate, error_code in (
        (bad_schema, "ae.repaired_response_handoff_schema_invalid"),
        (bad_status, "ae.repaired_response_handoff_status_invalid"),
        (bad_lineage, "ae.repaired_response_lineage_mismatch"),
        (bad_parent_mutation, "ae.repaired_response_parent_mutation_forbidden"),
        (bad_redaction, "ae.repaired_response_redaction_invalid"),
    ):
        with pytest.raises(RepairedResponseHandoffError) as exc_info:
            validate_repaired_response_handoff_record(candidate)
        assert exc_info.value.error_code == error_code


def test_repaired_response_handoff_redaction_guard_rejects_sensitive_payloads() -> None:
    with pytest.raises(RepairedResponseHandoffError) as raw_key_error:
        build_handoff(payload=source_payload(raw_prompt="hidden prompt"))

    assert raw_key_error.value.error_code == "ae.repaired_response_sensitive_payload"
    assert find_sensitive_repaired_response_handoff_keys(
        {"items": [{"raw_prompt": "hidden"}]}
    ) == ["items[0].raw_prompt"]

    with pytest.raises(RepairedResponseHandoffError) as content_error:
        assert_repaired_response_handoff_redaction_safe(
            {"safe_key": "raw answer body"}
        )

    assert content_error.value.error_code == "ae.repaired_response_sensitive_payload"


def test_repaired_response_handoff_helpers_cover_optional_edges() -> None:
    assert presentation_mode_from_payload({}) == "side_by_side_review"
    assert presentation_mode_from_payload(
        {"presentation_mode": "replace_answer_candidate"}
    ) == "replace_answer_candidate"
    assert actor_claims_ref_from_payload(
        {
            "tenant_id": "tenant-001",
            "owner_user_id": "user-001",
            "actor_claims_ref": {
                "actor_type": "service",
                "actor_id": "nex-ag",
                "tenant_id": "tenant-001",
            },
        }
    ) == {
        "actor_type": "service",
        "actor_id": "nex-ag",
        "tenant_id": "tenant-001",
    }
    assert str(
        RepairedResponseHandoffError(
            status_code=422,
            error_code="example",
            detail="readable detail",
        )
    ) == "readable detail"


def test_repaired_response_review_projection_is_schema_valid_and_safe() -> None:
    handoff = build_handoff()

    projection = build_repaired_response_review_projection(
        handoff,
        checked_at="2026-08-27T00:02:00Z",
    )

    Draft202012Validator(repaired_response_review_schema()).validate(projection)
    assert projection["projection_schema_version"] == (
        AE_REPAIRED_RESPONSE_REVIEW_PROJECTION_SCHEMA_VERSION
    )
    assert projection["projection_status"] == "READY_FOR_DECISION"
    assert projection["owner_scope"] == {
        "tenant_id": "tenant-001",
        "workspace_id": "workspace-001",
        "owner_user_id": "user-001",
    }
    assert projection["conversation_scope"]["interaction_id"] == "interaction-001"
    assert projection["original_response_ref"] == {
        "cx_generation_id": "cx-gen-001",
        "link": "/api/v1/generations/cx-gen-001",
        "parent_generation_mutated": False,
    }
    assert projection["repaired_response_summary"]["output_hash"] == "c" * 64
    assert projection["repaired_response_summary"]["output_preview"] == (
        "Repaired answer with citation support."
    )
    assert projection["decision_controls"]["primary_actions"] == list(
        PRIMARY_REVIEW_ACTIONS
    )
    assert projection["decision_controls"]["secondary_actions"] == [
        "view_original",
        "view_repaired",
        "view_lineage",
    ]
    assert projection["decision_controls"]["decision_submit_path"] == (
        "/api/v1/chat/interactions/interaction-001/"
        f"repaired-response-handoffs/{handoff['repaired_response_handoff_id']}/"
        "decisions"
    )
    serialized = json.dumps(projection, sort_keys=True)
    assert "raw answer body" not in serialized
    assert "hidden prompt" not in serialized
    assert "/data/nex-platform" not in serialized


def test_repaired_response_review_projection_adds_required_primary_actions() -> None:
    handoff = build_handoff()
    handoff["user_surface"]["available_actions"] = [
        None,
        "",
        "view_lineage",
        "view_lineage",
    ]

    projection = build_repaired_response_review_projection(handoff)

    assert projection["decision_controls"]["available_actions"] == [
        "view_lineage",
        "accept_repair",
        "keep_original",
    ]
    assert projection["decision_controls"]["secondary_actions"] == ["view_lineage"]


def test_repaired_response_review_collection_filters_and_sorts_by_interaction() -> None:
    older = build_handoff()
    newer = deepcopy(older)
    newer["repaired_response_handoff_id"] = "handoff-newer"
    newer["handoff_request_id"] = "request-newer"
    newer["links"]["handoff"] = (
        "/api/v1/chat/interactions/interaction-001/"
        "repaired-response-handoffs/handoff-newer"
    )
    newer["created_at"] = "2026-08-27T00:10:00Z"
    other = deepcopy(older)
    other["interaction_id"] = "other-interaction"

    collection = build_repaired_response_review_collection(
        [older, other, newer],
        interaction_id="interaction-001",
        checked_at="2026-08-27T00:11:00Z",
    )

    assert collection == {
        "collection_schema_version": "ae_repaired_response_review_collection.v1",
        "interaction_id": "interaction-001",
        "items": collection["items"],
        "item_count": 2,
        "checked_at": "2026-08-27T00:11:00Z",
    }
    assert [
        item["repaired_response_handoff_id"] for item in collection["items"]
    ] == ["handoff-newer", older["repaired_response_handoff_id"]]


@pytest.mark.parametrize(
    ("override", "error_code"),
    [
        (
            {"projection_schema_version": "old"},
            "ae.repaired_response_review.schema_version_invalid",
        ),
        (
            {"projection_status": "PENDING"},
            "ae.repaired_response_review.status_invalid",
        ),
        (
            {"owner_scope": {"tenant_id": "", "workspace_id": "w", "owner_user_id": "u"}},
            "ae.repaired_response_review.owner_scope_invalid",
        ),
        (
            {"conversation_scope": {"chat_document_id": "", "interaction_id": "i"}},
            "ae.repaired_response_review.conversation_scope_invalid",
        ),
        (
            {"decision_controls": {"primary_actions": ["keep_original"]}},
            "ae.repaired_response_review.primary_actions_invalid",
        ),
        (
            {
                "decision_controls": {
                    "primary_actions": ["accept_repair", "keep_original"],
                    "available_actions": ["accept_repair", "keep_original", "raw_output"],
                    "secondary_actions": [],
                    "decision_submit_path": (
                        "/api/v1/chat/interactions/i/repaired-response-handoffs/h/decisions"
                    ),
                }
            },
            "ae.repaired_response_review.available_actions_invalid",
        ),
        (
            {
                "decision_controls": {
                    "primary_actions": ["accept_repair", "keep_original"],
                    "available_actions": ["accept_repair", "keep_original"],
                    "secondary_actions": [],
                    "decision_submit_path": "https://example.invalid/decisions",
                }
            },
            "ae.repaired_response_review.decision_path_invalid",
        ),
        (
            {"redaction_summary": {"raw_output_included": True}},
            "ae.repaired_response_review.redaction_invalid",
        ),
    ],
)
def test_validate_repaired_response_review_projection_rejects_invalid_shapes(
    override: dict[str, Any],
    error_code: str,
) -> None:
    projection = build_repaired_response_review_projection(build_handoff())
    projection.update(override)

    with pytest.raises(RepairedResponseReviewProjectionError) as exc_info:
        validate_repaired_response_review_projection(projection)

    assert exc_info.value.error_code == error_code


def test_repaired_response_review_helpers_reject_invalid_inputs() -> None:
    handoff = build_handoff()
    bad_handoff = deepcopy(handoff)
    bad_handoff["handoff_schema_version"] = "old"
    with pytest.raises(RepairedResponseReviewProjectionError) as handoff_error:
        build_repaired_response_review_projection(bad_handoff)
    assert handoff_error.value.error_code == "ae.repaired_response_review.handoff_invalid"

    bad_path_handoff = deepcopy(handoff)
    bad_path_handoff["links"]["handoff"] = "https://example.invalid/handoff"
    with pytest.raises(RepairedResponseReviewProjectionError) as path_error:
        decision_submit_path_for_handoff(bad_path_handoff)
    assert path_error.value.error_code == (
        "ae.repaired_response_review.handoff_path_invalid"
    )

    with pytest.raises(RepairedResponseReviewProjectionError) as interaction_error:
        build_repaired_response_review_collection([handoff], interaction_id="")
    assert interaction_error.value.error_code == (
        "ae.repaired_response_review.interaction_id_required"
    )

    payload = {
        "redaction_summary": {"raw_output_included": False},
        "nested": [{"raw_prompt": "hidden"}],
    }
    assert find_sensitive_repaired_response_review_projection_keys(payload) == [
        "nested[0].raw_prompt"
    ]
    with pytest.raises(RepairedResponseReviewProjectionError) as sensitive_error:
        assert_repaired_response_review_projection_redaction_safe(payload)
    assert sensitive_error.value.error_code == (
        "ae.repaired_response_review.sensitive_key"
    )
    assert str(sensitive_error.value) == sensitive_error.value.detail


def decision_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "decision_action": DECISION_ACTION_ACCEPT_REPAIR,
        "decision_request_id": "decision-request-001",
        "decision_reason_codes": [
            "citation_fixed",
            "prefer_repaired",
            "citation_fixed",
        ],
        "decision_comment": "The repaired response now matches the cited source.",
        "submitted_via": "chat_review",
        "actor_claims_ref": {
            "actor_type": "user",
            "actor_id": "user-001",
            "tenant_id": "tenant-001",
        },
    }
    payload.update(overrides)
    return payload


def build_decision(
    *,
    handoff: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return build_repaired_response_decision_record(
        handoff_record=handoff or build_handoff(),
        decision_payload=payload or decision_payload(),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        created_at="2026-08-27T00:03:00Z",
    )


def test_repaired_response_decision_record_accepts_repair_and_matches_schema() -> None:
    decision = build_decision()

    Draft202012Validator(repaired_response_decision_schema()).validate(decision)
    assert decision["decision_schema_version"] == (
        AE_REPAIRED_RESPONSE_DECISION_SCHEMA_VERSION
    )
    assert decision["decision_status"] == "RECORDED"
    assert decision["decision_action"] == DECISION_ACTION_ACCEPT_REPAIR
    assert decision["selected_cx_generation_id"] == "cx-gen-repair-001"
    assert decision["rejected_cx_generation_id"] == "cx-gen-001"
    assert decision["decision_reason_codes"] == [
        "citation_fixed",
        "prefer_repaired",
    ]
    assert decision["decision_comment_hash"] == (
        "bc016b480c3730112c20228619d60639f03a9099cbe9d7be"
        "07c9ac01d8afcc6f"
    )
    assert decision["decision_comment_preview"] == (
        "The repaired response now matches the cited source."
    )
    assert "decision_comment" not in decision
    assert decision["metadata"] == {
        "submitted_via": "chat_review",
        "raw_prompt_stored": False,
        "raw_generation_output_stored": False,
        "raw_source_text_stored": False,
        "raw_evidence_stored": False,
        "free_text_comment_storage": "hash_and_short_preview_only",
        "parent_generation_mutated": False,
    }


def test_repaired_response_decision_record_keeps_original_with_defaults() -> None:
    decision = build_decision(
        payload=decision_payload(
            decision_action=DECISION_ACTION_KEEP_ORIGINAL,
            decision_request_id=None,
            decision_reason_codes=None,
            decision_comment=None,
            submitted_via="document_detail",
            actor_claims_ref=None,
        )
    )

    assert decision["decision_action"] == DECISION_ACTION_KEEP_ORIGINAL
    assert decision["selected_cx_generation_id"] == "cx-gen-001"
    assert decision["rejected_cx_generation_id"] == "cx-gen-repair-001"
    assert decision["decision_reason_codes"] == ["prefer_original"]
    assert decision["decision_comment_hash"] is None
    assert decision["decision_comment_preview"] is None
    assert decision["actor_claims_ref"] == {
        "actor_type": "user",
        "actor_id": "user-001",
        "tenant_id": "tenant-001",
    }
    assert decision["metadata"]["submitted_via"] == "document_detail"
    assert decision["decision_request_id"] != ""


def test_repaired_response_decision_store_indexes_unique_decisions() -> None:
    store = RepairedResponseDecisionStore()
    decision = build_decision()

    saved = store.save(decision)
    duplicate = store.save(decision)

    assert saved == decision
    assert duplicate == decision
    assert store.get(decision["repaired_response_decision_id"]) == decision
    assert store.list_for_handoff(decision["repaired_response_handoff_id"]) == [
        decision
    ]
    assert store.list_for_interaction(decision["interaction_id"]) == [decision]
    assert store.list_for_handoff("missing") == []
    assert store.list_for_interaction("missing") == []


def test_repaired_response_decision_collection_filters_sorts_and_defaults_time() -> None:
    older = build_decision()
    newer = deepcopy(older)
    newer["repaired_response_decision_id"] = "decision-newer"
    newer["decision_request_id"] = "decision-request-newer"
    newer["created_at"] = "2026-08-27T00:04:00Z"
    other_handoff = deepcopy(older)
    other_handoff["repaired_response_decision_id"] = "decision-other-handoff"
    other_handoff["repaired_response_handoff_id"] = "other-handoff"
    other_interaction = deepcopy(older)
    other_interaction["repaired_response_decision_id"] = "decision-other-interaction"
    other_interaction["interaction_id"] = "other-interaction"

    collection = build_repaired_response_decision_collection(
        [older, other_handoff, newer, other_interaction],
        interaction_id="interaction-001",
        repaired_response_handoff_id=older["repaired_response_handoff_id"],
        checked_at="2026-08-27T00:05:00Z",
    )

    assert collection["collection_schema_version"] == (
        AE_REPAIRED_RESPONSE_DECISION_COLLECTION_SCHEMA_VERSION
    )
    assert collection["item_count"] == 2
    assert collection["checked_at"] == "2026-08-27T00:05:00Z"
    assert [
        item["repaired_response_decision_id"] for item in collection["items"]
    ] == ["decision-newer", older["repaired_response_decision_id"]]


def test_repaired_response_decision_routes_create_list_and_read_record() -> None:
    client, handoff, _handoff_store, decision_store = build_decision_test_client()
    decision_path = (
        f"/api/v1/chat/interactions/{handoff['interaction_id']}/"
        f"repaired-response-handoffs/{handoff['repaired_response_handoff_id']}/"
        "decisions"
    )

    create_response = client.post(
        decision_path,
        json=decision_payload(
            interaction_id=handoff["interaction_id"],
            repaired_response_handoff_id=handoff["repaired_response_handoff_id"],
        ),
        headers=auth_headers(),
    )

    assert create_response.status_code == 202
    created = create_response.json()
    Draft202012Validator(repaired_response_decision_schema()).validate(created)
    assert created["decision_schema_version"] == (
        AE_REPAIRED_RESPONSE_DECISION_SCHEMA_VERSION
    )
    assert created["selected_cx_generation_id"] == "cx-gen-repair-001"
    assert decision_store.get(created["repaired_response_decision_id"]) == created

    list_response = client.get(decision_path, headers=auth_headers())
    assert list_response.status_code == 200
    listed = list_response.json()
    assert listed["collection_schema_version"] == (
        AE_REPAIRED_RESPONSE_DECISION_COLLECTION_SCHEMA_VERSION
    )
    assert listed["item_count"] == 1
    assert listed["items"] == [created]

    detail_response = client.get(
        f"{decision_path}/{created['repaired_response_decision_id']}",
        headers=auth_headers(),
    )
    assert detail_response.status_code == 200
    assert detail_response.json() == created


def test_repaired_response_decision_routes_map_auth_scope_and_payload_errors() -> None:
    client, handoff, _handoff_store, decision_store = build_decision_test_client()
    decision_path = (
        f"/api/v1/chat/interactions/{handoff['interaction_id']}/"
        f"repaired-response-handoffs/{handoff['repaired_response_handoff_id']}/"
        "decisions"
    )

    unauthorized = client.post(decision_path, json=decision_payload())
    wrong_interaction = client.post(
        decision_path.replace("interaction-001", "other-interaction", 1),
        json=decision_payload(),
        headers=auth_headers(),
    )
    invalid_payload = client.post(
        decision_path,
        json=decision_payload(decision_action="archive"),
        headers=auth_headers(),
    )
    sensitive_payload = client.post(
        decision_path,
        json=decision_payload(raw_prompt="hidden"),
        headers=auth_headers(),
    )

    assert unauthorized.status_code == 401
    assert unauthorized.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"
    assert wrong_interaction.status_code == 404
    assert wrong_interaction.json()["error_code"] == (
        "ae.repaired_response_handoff_not_found"
    )
    assert invalid_payload.status_code == 422
    assert invalid_payload.json()["error_code"] == (
        "ae.repaired_response_decision_action_invalid"
    )
    assert sensitive_payload.status_code == 422
    assert sensitive_payload.json()["error_code"] == (
        "ae.repaired_response_decision_sensitive_payload"
    )
    assert decision_store.list_for_handoff(handoff["repaired_response_handoff_id"]) == []


def test_repaired_response_decision_routes_enforce_detail_scope() -> None:
    client, handoff, _handoff_store, decision_store = build_decision_test_client()
    decision = decision_store.save(build_decision(handoff=handoff))
    decision_path = (
        f"/api/v1/chat/interactions/{handoff['interaction_id']}/"
        f"repaired-response-handoffs/{handoff['repaired_response_handoff_id']}/"
        "decisions"
    )
    missing_path = (
        f"/api/v1/chat/interactions/{handoff['interaction_id']}/"
        f"repaired-response-handoffs/{handoff['repaired_response_handoff_id']}/"
        "decisions/missing-decision"
    )
    other_handoff_path = (
        f"/api/v1/chat/interactions/{handoff['interaction_id']}/"
        "repaired-response-handoffs/missing-handoff/"
        f"decisions/{decision['repaired_response_decision_id']}"
    )

    missing = client.get(missing_path, headers=auth_headers())
    wrong_handoff = client.get(other_handoff_path, headers=auth_headers())
    list_wrong_handoff = client.get(
        other_handoff_path.rsplit("/", 1)[0],
        headers=auth_headers(),
    )
    unauthorized_list = client.get(decision_path)
    unauthorized_detail = client.get(
        f"{decision_path}/{decision['repaired_response_decision_id']}"
    )

    assert missing.status_code == 404
    assert missing.json()["error_code"] == "ae.repaired_response_decision_not_found"
    assert wrong_handoff.status_code == 404
    assert wrong_handoff.json()["error_code"] == (
        "ae.repaired_response_handoff_not_found"
    )
    assert list_wrong_handoff.status_code == 404
    assert unauthorized_list.status_code == 401
    assert unauthorized_detail.status_code == 401


def test_sqlalchemy_repaired_response_decision_store_round_trips_with_sqlite() -> None:
    store = SqlAlchemyRepairedResponseDecisionStore(sqlite_decision_session_factory())
    decision = build_decision()

    saved = store.save(decision)
    loaded = store.get(decision["repaired_response_decision_id"])
    by_handoff = store.list_for_handoff(decision["repaired_response_handoff_id"])
    by_interaction = store.list_for_interaction(decision["interaction_id"])
    updated = deepcopy(decision)
    updated["decision_reason_codes"] = ["prefer_repaired", "answer_improved"]
    updated["updated_at"] = "2026-08-27T00:04:00Z"
    store.save(updated)
    loaded_after_update = store.get(decision["repaired_response_decision_id"])
    deleted_rows = store.delete(decision["repaired_response_decision_id"])

    assert saved == decision
    assert loaded == decision
    assert by_handoff == [decision]
    assert by_interaction == [decision]
    assert loaded_after_update == updated
    assert deleted_rows == 1
    assert store.get(decision["repaired_response_decision_id"]) is None


@pytest.mark.parametrize("operation", ["save", "get", "list_handoff", "list_interaction", "delete"])
def test_sqlalchemy_repaired_response_decision_store_maps_database_errors(
    operation: str,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = SqlAlchemyRepairedResponseDecisionStore(
        sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    )
    decision = build_decision()

    with pytest.raises(RepairedResponseDecisionError) as exc_info:
        if operation == "save":
            store.save(decision)
        elif operation == "get":
            store.get(decision["repaired_response_decision_id"])
        elif operation == "list_handoff":
            store.list_for_handoff(decision["repaired_response_handoff_id"])
        elif operation == "list_interaction":
            store.list_for_interaction(decision["interaction_id"])
        else:
            store.delete(decision["repaired_response_decision_id"])

    assert exc_info.value.status_code == 503
    assert exc_info.value.error_code == "ae.repaired_response_decision_store_unavailable"
    assert exc_info.value.retryable is True


def test_default_repaired_response_decision_store_selects_runtime_store() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    app.state.nex_persistence = SimpleNamespace(
        api_session_factory=sqlite_decision_session_factory()
    )

    assert isinstance(
        default_repaired_response_decision_store(app),
        SqlAlchemyRepairedResponseDecisionStore,
    )
    app_without_db = build_service_app(SERVICE_SPECS["nex-ae-api"])
    assert isinstance(
        default_repaired_response_decision_store(app_without_db),
        RepairedResponseDecisionStore,
    )


@pytest.mark.parametrize(
    ("candidate", "error_code"),
    [
        (
            {"decision_schema_version": "old"},
            "ae.repaired_response_decision_schema_invalid",
        ),
        (
            {"decision_status": "PENDING"},
            "ae.repaired_response_decision_status_invalid",
        ),
        (
            {"decision_action": "archive"},
            "ae.repaired_response_decision_action_invalid",
        ),
        (
            {"selected_cx_generation_id": "cx-gen-001"},
            "ae.repaired_response_decision_generation_mismatch",
        ),
        (
            {"selected_cx_generation_id": None},
            "ae.repaired_response_decision_generation_required",
        ),
        (
            {
                "metadata": {
                    "submitted_via": "raw_console",
                    "raw_prompt_stored": False,
                    "raw_generation_output_stored": False,
                    "raw_source_text_stored": False,
                    "raw_evidence_stored": False,
                    "parent_generation_mutated": False,
                }
            },
            "ae.repaired_response_decision_submitter_invalid",
        ),
        (
            {"metadata": {"submitted_via": "chat_review", "raw_prompt_stored": True}},
            "ae.repaired_response_decision_metadata_invalid",
        ),
        (
            {
                "metadata": {
                    "submitted_via": "chat_review",
                    "raw_prompt_stored": False,
                    "raw_generation_output_stored": False,
                    "raw_source_text_stored": False,
                    "raw_evidence_stored": False,
                    "parent_generation_mutated": True,
                }
            },
            "ae.repaired_response_decision_parent_mutation_forbidden",
        ),
    ],
)
def test_validate_repaired_response_decision_record_rejects_invalid_shapes(
    candidate: dict[str, Any],
    error_code: str,
) -> None:
    decision = build_decision()
    decision.update(candidate)

    with pytest.raises(RepairedResponseDecisionError) as exc_info:
        validate_repaired_response_decision_record(decision)

    assert exc_info.value.error_code == error_code


def test_repaired_response_decision_helpers_reject_invalid_inputs() -> None:
    handoff = build_handoff()
    with pytest.raises(RepairedResponseDecisionError) as missing_action:
        decision_action_from_payload({})
    assert missing_action.value.error_code == (
        "ae.repaired_response_decision_action_required"
    )

    with pytest.raises(RepairedResponseDecisionError) as invalid_payload_action:
        decision_action_from_payload({"decision_action": "archive"})
    assert invalid_payload_action.value.error_code == (
        "ae.repaired_response_decision_action_invalid"
    )

    with pytest.raises(RepairedResponseDecisionError) as bad_reason_list:
        decision_reason_codes_from_payload(
            {"decision_reason_codes": "prefer_repaired"},
            action=DECISION_ACTION_ACCEPT_REPAIR,
        )
    assert bad_reason_list.value.error_code == (
        "ae.repaired_response_decision_reason_codes_invalid"
    )

    with pytest.raises(RepairedResponseDecisionError) as bad_reason_code:
        decision_reason_codes_from_payload(
            {"decision_reason_codes": ["unsafe_raw"]},
            action=DECISION_ACTION_ACCEPT_REPAIR,
        )
    assert bad_reason_code.value.error_code == (
        "ae.repaired_response_decision_reason_code_invalid"
    )
    assert decision_reason_codes_from_payload(
        {"decision_reason_codes": [None, "", "prefer_repaired", "prefer_repaired"]},
        action=DECISION_ACTION_ACCEPT_REPAIR,
    ) == ["prefer_repaired"]

    with pytest.raises(RepairedResponseDecisionError) as bad_submitter:
        submitted_via_from_payload({"submitted_via": "raw_console"})
    assert bad_submitter.value.error_code == (
        "ae.repaired_response_decision_submitter_invalid"
    )

    with pytest.raises(RepairedResponseDecisionError) as bad_actor:
        actor_claims_ref_from_decision_payload(
            {"actor_claims_ref": {"tenant_id": "other-tenant"}},
            handoff,
        )
    assert bad_actor.value.error_code == (
        "ae.repaired_response_decision_actor_scope_mismatch"
    )

    with pytest.raises(RepairedResponseDecisionError) as bad_action:
        selected_cx_generation_id_for_action(
            "archive",
            parent_cx_generation_id="parent",
            repair_cx_generation_id="repair",
        )
    assert bad_action.value.error_code == (
        "ae.repaired_response_decision_action_invalid"
    )

    with pytest.raises(RepairedResponseDecisionError) as scope_mismatch:
        build_decision(payload=decision_payload(interaction_id="other-interaction"))
    assert scope_mismatch.value.error_code == (
        "ae.repaired_response_decision_scope_mismatch"
    )

    bad_handoff = deepcopy(handoff)
    bad_handoff["handoff_schema_version"] = "old"
    with pytest.raises(RepairedResponseDecisionError) as handoff_error:
        build_decision(handoff=bad_handoff)
    assert handoff_error.value.error_code == (
        "ae.repaired_response_decision_handoff_invalid"
    )

    payload = {"nested": [{"raw_prompt": "hidden"}]}
    assert find_sensitive_repaired_response_decision_keys(payload) == [
        "nested[0].raw_prompt"
    ]
    with pytest.raises(RepairedResponseDecisionError) as sensitive_error:
        assert_repaired_response_decision_payload_redaction_safe(payload)
    assert sensitive_error.value.error_code == (
        "ae.repaired_response_decision_sensitive_payload"
    )
    assert_repaired_response_decision_payload_redaction_safe(
        {"usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3}}
    )
    assert str(sensitive_error.value) == sensitive_error.value.detail


def test_repaired_response_decision_storage_helpers_and_migration() -> None:
    decision = build_decision()
    params = decision_module._decision_record_params(decision)
    migration = (
        ROOT
        / "database"
        / "nex-ae-api"
        / "migrations"
        / "0387_ae_repaired_response_decision_persistence.sql"
    ).read_text(encoding="utf-8")

    assert params["actor_claims_ref"].startswith("{")
    assert params["decision_reason_codes"].startswith("[")
    assert decision_module._json_param_expr("metadata", "postgresql") == (
        "CAST(:metadata AS jsonb)"
    )
    assert decision_module._json_param_expr("metadata", "sqlite") == ":metadata"
    assert decision_module._json_value(None, []) == []
    assert decision_module._json_value('["prefer_repaired"]', []) == [
        "prefer_repaired"
    ]
    assert decision_module._json_value({"ok": True}, {}) == {"ok": True}
    assert isinstance(decision_module._datetime_value(None), str)
    assert decision_module._datetime_value(
        decision_module.datetime(2026, 8, 27, 0, 0, tzinfo=decision_module.UTC)
    ) == "2026-08-27T00:00:00Z"
    assert decision_module._datetime_value(
        SimpleNamespace(isoformat=lambda: "2026-08-27T00:00:00+00:00")
    ) == "2026-08-27T00:00:00Z"
    assert "CREATE TABLE IF NOT EXISTS ae_repaired_response_decisions" in migration
    assert "decision_action IN ('accept_repair', 'keep_original')" in migration
    assert "idx_ae_repaired_response_decisions_handoff_time" in migration
    assert "idx_ae_repaired_response_decisions_owner_time" in migration
    assert "raw_generation_output" not in migration
