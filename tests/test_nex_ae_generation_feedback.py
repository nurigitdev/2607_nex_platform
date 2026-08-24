from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from nex_ae_api.generation_feedback import (
    GenerationFeedbackError,
    GenerationFeedbackStore,
    SqlAlchemyGenerationFeedbackStore,
    build_generation_feedback_record,
    default_generation_feedback_store,
    feedback_reason_list,
    payload_with_path_interaction_id,
    quality_issue_refs,
    register_generation_feedback_routes,
)
import nex_ae_api.generation_feedback as feedback_module
from nex_ae_api.generation_feedback_boundary import (
    AE_FEEDBACK_OWNER_SERVICE,
    AG_OPERATOR_DISPOSITION_OWNER_SERVICE,
    CX_GENERATION_LINEAGE_OWNER_SERVICE,
    GENERATION_FEEDBACK_BOUNDARY_DECISION_VERSION,
    GenerationFeedbackBoundaryError,
    assert_feedback_payload_redaction_safe,
    build_generation_feedback_boundary_decision,
    find_sensitive_feedback_keys,
    validate_generation_feedback_boundary_decision,
)
from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token


ROOT = Path(__file__).parents[1]


def generation_feedback_schema() -> dict[str, object]:
    return json.loads(
        (
            ROOT
            / "contracts"
            / "schemas"
            / "service"
            / "nex_ae_api"
            / "generation_feedback.v1.schema.json"
        ).read_text(encoding="utf-8")
    )


def ae_openapi_spec() -> dict[str, object]:
    return yaml.safe_load(
        (ROOT / "contracts" / "openapi" / "nex-ae-api.openapi.yaml").read_text(
            encoding="utf-8"
        )
    )


def auth_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience="nex-ae-api")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": "0189f0ff-8f22-4f72-9b47-b481dc21bb21",
        "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
    }


def build_feedback_test_client() -> tuple[TestClient, GenerationFeedbackStore]:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    store = GenerationFeedbackStore()
    register_generation_feedback_routes(app, store=store)
    return TestClient(app), store


def test_generation_feedback_boundary_decision_assigns_owner_services() -> None:
    decision = validate_generation_feedback_boundary_decision(
        build_generation_feedback_boundary_decision()
    )

    assert decision["decision_schema_version"] == (
        GENERATION_FEEDBACK_BOUNDARY_DECISION_VERSION
    )
    assert decision["owner_services"] == {
        "user_feedback_intake": AE_FEEDBACK_OWNER_SERVICE,
        "generation_lineage": CX_GENERATION_LINEAGE_OWNER_SERVICE,
        "operator_disposition": AG_OPERATOR_DISPOSITION_OWNER_SERVICE,
    }
    assert decision["storage_contract"]["raw_content_policy"] == {
        "raw_user_prompt_stored": False,
        "raw_generation_output_stored": False,
        "raw_source_document_text_stored": False,
        "credential_material_stored": False,
        "free_text_comment_storage": "hash_and_short_preview_only",
    }
    assert "feedback_comment_hash" in decision["storage_contract"]["safe_fields"]
    assert "feedback_comment_preview" in decision["storage_contract"]["safe_fields"]
    assert "raw_prompt" not in decision["storage_contract"]["safe_fields"]


@pytest.mark.parametrize(
    ("override", "error_code"),
    [
        (
            {"decision_schema_version": "bad"},
            "ae.feedback_boundary.schema_version_invalid",
        ),
        (
            {"owner_services": {"user_feedback_intake": "nex-cx"}},
            "ae.feedback_boundary.owner_services_invalid",
        ),
        (
            {
                "storage_contract": {
                    "safe_fields": ["feedback_id"],
                    "raw_content_policy": {"raw_user_prompt_stored": True},
                }
            },
            "ae.feedback_boundary.raw_content_policy_invalid",
        ),
        (
            {
                "storage_contract": {
                    "safe_fields": ["feedback_id", "raw_output"],
                    "raw_content_policy": {
                        "raw_user_prompt_stored": False,
                        "raw_generation_output_stored": False,
                        "raw_source_document_text_stored": False,
                        "credential_material_stored": False,
                    },
                }
            },
            "ae.feedback_boundary.safe_field_sensitive",
        ),
    ],
)
def test_generation_feedback_boundary_decision_rejects_invalid_shape(
    override: dict[str, object],
    error_code: str,
) -> None:
    decision = build_generation_feedback_boundary_decision()
    decision.update(override)

    with pytest.raises(GenerationFeedbackBoundaryError) as exc_info:
        validate_generation_feedback_boundary_decision(decision)

    assert exc_info.value.error_code == error_code


def test_feedback_payload_redaction_guard_reports_nested_sensitive_keys() -> None:
    payload = {
        "feedback_value": "negative",
        "feedback_reasons": ["citation_issue"],
        "metadata": {
            "quality_issue_refs": [{"issue_code": "citation_missing"}],
            "raw_prompt": "should not be stored",
        },
        "comments": [{"raw_generation_output": "should not be stored"}],
    }

    assert find_sensitive_feedback_keys(payload) == [
        "metadata.raw_prompt",
        "comments[0].raw_generation_output",
    ]
    with pytest.raises(GenerationFeedbackBoundaryError) as exc_info:
        assert_feedback_payload_redaction_safe(payload)

    assert exc_info.value.error_code == "ae.feedback_payload.sensitive_key"


def test_feedback_payload_redaction_guard_accepts_hash_and_preview_only() -> None:
    payload = {
        "feedback_value": "negative",
        "feedback_reasons": ["citation_issue"],
        "feedback_comment_hash": "a" * 64,
        "feedback_comment_preview": "Citation [2] did not support the answer.",
        "quality_issue_refs": [{"issue_code": "citation_missing"}],
    }

    assert_feedback_payload_redaction_safe(payload)


def feedback_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "tenant_id": "local-tenant",
        "user_id": "employee-0001",
        "interaction_id": "ae-chat-001",
        "chat_document_id": "ae-chat-doc-001",
        "cx_generation_id": "cx-gen-001",
        "feedback_value": "negative",
        "feedback_reasons": ["citation_issue", "incomplete", "citation_issue"],
        "feedback_comment": "Citation [2] did not support the answer.",
        "quality_issue_refs": [
            {
                "source_service": "nex-cx",
                "issue_type": "citation_quality",
                "issue_code": "citation_missing",
                "issue_ref_id": "cx-gen-001",
            }
        ],
    }
    payload.update(overrides)
    return payload


def test_generation_feedback_record_hashes_comment_and_matches_schema() -> None:
    record = build_generation_feedback_record(
        feedback_payload(),
        request_id="0189f0ff-8f22-4f72-9b47-b481dc21bb21",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        created_at="2026-08-24T00:00:00Z",
    )

    Draft202012Validator(generation_feedback_schema()).validate(record)
    assert record["feedback_schema_version"] == "ae_generation_feedback.v1"
    assert record["status"] == "RECORDED"
    assert record["feedback_reasons"] == ["citation_issue", "incomplete"]
    assert record["feedback_comment_hash"] == (
        "7e7ea00cfe346b8b19b334702341bf0d8c4eb2d7dabf8086"
        "763feba20375fecd"
    )
    assert record["feedback_comment_preview"] == (
        "Citation [2] did not support the answer."
    )
    assert "feedback_comment" not in record
    assert record["metadata"]["raw_prompt_stored"] is False
    assert record["metadata"]["raw_generation_output_stored"] is False


def test_generation_feedback_record_allows_empty_optional_links() -> None:
    record = build_generation_feedback_record(
        feedback_payload(
            feedback_value="positive",
            feedback_reasons=["helpful"],
            feedback_comment=None,
            chat_document_id="",
            cx_generation_id="",
            quality_issue_refs=None,
            submitted_via="document_detail",
        ),
        request_id="req-001",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        created_at="2026-08-24T00:00:00Z",
    )

    assert record["chat_document_id"] is None
    assert record["cx_generation_id"] is None
    assert record["feedback_comment_hash"] is None
    assert record["feedback_comment_preview"] is None
    assert record["quality_issue_refs"] == []
    assert record["metadata"]["submitted_via"] == "document_detail"


def test_generation_feedback_record_ignores_non_string_optional_values() -> None:
    record = build_generation_feedback_record(
        feedback_payload(
            chat_document_id=123,
            cx_generation_id=object(),
            submitted_via=object(),
        ),
        request_id="req-001",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        created_at="2026-08-24T00:00:00Z",
    )

    assert record["chat_document_id"] is None
    assert record["cx_generation_id"] is None
    assert record["metadata"]["submitted_via"] == "chat"


@pytest.mark.parametrize(
    ("override", "error_code"),
    [
        ({"tenant_id": ""}, "ae.generation_feedback_tenant_id_required"),
        (
            {"feedback_value": "angry"},
            "ae.generation_feedback_feedback_value_unsupported",
        ),
        (
            {"feedback_reasons": "citation_issue"},
            "ae.generation_feedback_reasons_invalid",
        ),
        (
            {"feedback_reasons": ["unsupported"]},
            "ae.generation_feedback_reason_unsupported",
        ),
        (
            {"quality_issue_refs": "bad"},
            "ae.generation_feedback_quality_refs_invalid",
        ),
        (
            {"quality_issue_refs": [{"source_service": "nex-cx"}]},
            "ae.generation_feedback_issue_type_required",
        ),
        (
            {"raw_prompt": "never persist"},
            "ae.generation_feedback_sensitive_payload",
        ),
    ],
)
def test_generation_feedback_record_rejects_invalid_payloads(
    override: dict[str, object],
    error_code: str,
) -> None:
    with pytest.raises(GenerationFeedbackError) as exc_info:
        build_generation_feedback_record(
            feedback_payload(**override),
            request_id="req-001",
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            created_at="2026-08-24T00:00:00Z",
        )

    assert exc_info.value.error_code == error_code


def test_generation_feedback_error_string_is_detail() -> None:
    error = GenerationFeedbackError(
        status_code=422,
        error_code="ae.generation_feedback_test",
        detail="feedback detail",
    )

    assert str(error) == "feedback detail"


def test_feedback_reason_list_accepts_missing_and_rejects_bad_items() -> None:
    assert feedback_reason_list(None) == []

    with pytest.raises(GenerationFeedbackError) as exc_info:
        feedback_reason_list([""])

    assert exc_info.value.error_code == "ae.generation_feedback_reason_invalid"


def test_quality_issue_refs_rejects_non_object_items() -> None:
    with pytest.raises(GenerationFeedbackError) as exc_info:
        quality_issue_refs(["bad"])

    assert exc_info.value.error_code == "ae.generation_feedback_quality_ref_invalid"


def test_generation_feedback_store_indexes_unique_feedback_ids() -> None:
    store = GenerationFeedbackStore()
    record = build_generation_feedback_record(
        feedback_payload(),
        request_id="req-001",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        created_at="2026-08-24T00:00:00Z",
    )

    store.save(record)
    store.save(record)

    assert store.get(record["feedback_id"]) == record
    assert store.list_for_interaction("ae-chat-001") == [record]
    assert store.list_for_interaction("missing") == []


def sqlite_feedback_session_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE ae_generation_feedback (
                    feedback_id TEXT PRIMARY KEY,
                    feedback_schema_version TEXT NOT NULL,
                    status TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    interaction_id TEXT NOT NULL,
                    chat_document_id TEXT,
                    cx_generation_id TEXT,
                    trace_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    feedback_value TEXT NOT NULL,
                    feedback_reasons TEXT NOT NULL,
                    feedback_comment_hash TEXT,
                    feedback_comment_preview TEXT,
                    quality_issue_refs TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
        )
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def test_sqlalchemy_generation_feedback_store_round_trips_with_sqlite() -> None:
    store = SqlAlchemyGenerationFeedbackStore(sqlite_feedback_session_factory())
    record = build_generation_feedback_record(
        feedback_payload(),
        request_id="req-001",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        created_at="2026-08-24T00:00:00Z",
    )

    saved = store.save(record)
    loaded = store.get(record["feedback_id"])
    listed = store.list_for_interaction(record["interaction_id"])
    deleted_rows = store.delete(record["feedback_id"])

    assert saved == record
    assert loaded == record
    assert listed == [record]
    assert deleted_rows == 1
    assert store.get(record["feedback_id"]) is None


@pytest.mark.parametrize(
    "operation",
    ["save", "get", "list", "delete"],
)
def test_sqlalchemy_generation_feedback_store_maps_database_errors(
    operation: str,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = SqlAlchemyGenerationFeedbackStore(
        sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    )
    record = build_generation_feedback_record(
        feedback_payload(),
        request_id="req-001",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        created_at="2026-08-24T00:00:00Z",
    )

    with pytest.raises(GenerationFeedbackError) as exc_info:
        if operation == "save":
            store.save(record)
        elif operation == "get":
            store.get(record["feedback_id"])
        elif operation == "list":
            store.list_for_interaction(record["interaction_id"])
        else:
            store.delete(record["feedback_id"])

    assert exc_info.value.status_code == 503
    assert exc_info.value.error_code == "ae.generation_feedback_store_unavailable"


def test_default_generation_feedback_store_uses_persistence_session_factory() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    session_factory = sqlite_feedback_session_factory()
    app.state.nex_persistence = SimpleNamespace(api_session_factory=session_factory)

    store = default_generation_feedback_store(app)

    assert isinstance(store, SqlAlchemyGenerationFeedbackStore)


def test_payload_with_path_interaction_id_rejects_mismatch() -> None:
    with pytest.raises(GenerationFeedbackError) as exc_info:
        payload_with_path_interaction_id(
            {"interaction_id": "payload-interaction"},
            "path-interaction",
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.error_code == "ae.generation_feedback_interaction_mismatch"


def test_payload_with_path_interaction_id_rejects_blank_path() -> None:
    with pytest.raises(GenerationFeedbackError) as exc_info:
        payload_with_path_interaction_id({}, "   ")

    assert exc_info.value.error_code == "ae.generation_feedback_interaction_id_required"


def test_generation_feedback_storage_helpers_cover_postgres_and_null_values() -> None:
    assert feedback_module._json_param_expr("metadata", "postgresql") == (
        "CAST(:metadata AS jsonb)"
    )
    assert feedback_module._json_value(None, []) == []
    assert feedback_module._json_value({"ok": True}, {}) == {"ok": True}
    assert feedback_module._datetime_value(
        feedback_module.datetime(2026, 8, 24, 0, 0, tzinfo=feedback_module.UTC)
    ) == "2026-08-24T00:00:00Z"
    assert feedback_module._datetime_value(
        SimpleNamespace(isoformat=lambda: "2026-08-24T00:00:00+00:00")
    ) == "2026-08-24T00:00:00Z"


def test_generation_feedback_route_records_lists_and_reads_feedback() -> None:
    client, store = build_feedback_test_client()

    create_response = client.post(
        "/api/v1/chat/interactions/ae-chat-001/feedback",
        json=feedback_payload(interaction_id="ae-chat-001"),
        headers=auth_headers(),
    )

    assert create_response.status_code == 202
    created = create_response.json()
    Draft202012Validator(generation_feedback_schema()).validate(created)
    assert created["interaction_id"] == "ae-chat-001"
    assert created["feedback_comment_hash"] is not None
    assert store.get(created["feedback_id"]) == created

    list_response = client.get(
        "/api/v1/chat/interactions/ae-chat-001/feedback",
        headers=auth_headers(),
    )
    assert list_response.status_code == 200
    listed = list_response.json()
    assert listed["feedback_schema_version"] == "ae_generation_feedback_list.v1"
    assert listed["items"] == [created]

    get_response = client.get(
        f"/api/v1/chat/interactions/ae-chat-001/feedback/{created['feedback_id']}",
        headers=auth_headers(),
    )
    assert get_response.status_code == 200
    assert get_response.json() == created


def test_generation_feedback_route_defaults_path_interaction_id() -> None:
    client, _store = build_feedback_test_client()

    response = client.post(
        "/api/v1/chat/interactions/ae-chat-from-path/feedback",
        json=feedback_payload(interaction_id=None),
        headers=auth_headers(),
    )

    assert response.status_code == 202
    assert response.json()["interaction_id"] == "ae-chat-from-path"


def test_generation_feedback_route_maps_auth_and_validation_errors() -> None:
    client, store = build_feedback_test_client()

    unauthorized = client.post(
        "/api/v1/chat/interactions/ae-chat-001/feedback",
        json=feedback_payload(),
    )
    assert unauthorized.status_code == 401
    assert unauthorized.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"

    mismatch = client.post(
        "/api/v1/chat/interactions/ae-chat-001/feedback",
        json=feedback_payload(interaction_id="other-interaction"),
        headers=auth_headers(),
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["error_code"] == "ae.generation_feedback_interaction_mismatch"

    sensitive = client.post(
        "/api/v1/chat/interactions/ae-chat-001/feedback",
        json=feedback_payload(raw_prompt="never store this"),
        headers=auth_headers(),
    )
    assert sensitive.status_code == 422
    assert sensitive.json()["error_code"] == "ae.generation_feedback_sensitive_payload"
    assert store.list_for_interaction("ae-chat-001") == []

    unauthorized_list = client.get("/api/v1/chat/interactions/ae-chat-001/feedback")
    unauthorized_detail = client.get(
        "/api/v1/chat/interactions/ae-chat-001/feedback/feedback-id"
    )
    assert unauthorized_list.status_code == 401
    assert unauthorized_detail.status_code == 401


def test_generation_feedback_detail_route_returns_not_found_for_wrong_scope() -> None:
    client, _store = build_feedback_test_client()
    created = client.post(
        "/api/v1/chat/interactions/ae-chat-001/feedback",
        json=feedback_payload(),
        headers=auth_headers(),
    ).json()

    wrong_scope = client.get(
        f"/api/v1/chat/interactions/other-chat/feedback/{created['feedback_id']}",
        headers=auth_headers(),
    )
    missing = client.get(
        "/api/v1/chat/interactions/ae-chat-001/feedback/missing-feedback",
        headers=auth_headers(),
    )

    assert wrong_scope.status_code == 404
    assert wrong_scope.json()["error_code"] == "ae.generation_feedback_not_found"
    assert missing.status_code == 404
    assert missing.json()["error_code"] == "ae.generation_feedback_not_found"


def test_generation_feedback_openapi_paths_are_registered() -> None:
    spec = ae_openapi_spec()
    paths = spec["paths"]

    feedback_collection = paths["/api/v1/chat/interactions/{interaction_id}/feedback"]
    feedback_detail = paths[
        "/api/v1/chat/interactions/{interaction_id}/feedback/{feedback_id}"
    ]

    assert feedback_collection["post"]["operationId"] == "createAeGenerationFeedback"
    assert feedback_collection["get"]["operationId"] == "listAeGenerationFeedback"
    assert feedback_detail["get"]["operationId"] == "getAeGenerationFeedback"
    assert feedback_collection["post"]["responses"]["202"]["content"][
        "application/json"
    ]["schema"]["properties"]["feedback_schema_version"] == {
        "const": "ae_generation_feedback.v1"
    }
