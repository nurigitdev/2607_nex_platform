from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from nex_ae_api.workspace import (
    DEFAULT_TENANT_ID,
    DEFAULT_USER_ID,
    WorkspaceError,
    WorkspaceStateStore,
    build_workspace_state,
    owner_scope_from_payload,
    register_workspace_routes,
    runtime_defaults_from_payload,
    workspace_title_from_payload,
)
from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


def auth_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience="nex-ae-api")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def build_client() -> tuple[TestClient, WorkspaceStateStore]:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    store = WorkspaceStateStore()
    register_workspace_routes(app, store=store)
    return TestClient(app), store


def test_build_workspace_state_uses_korean_defaults() -> None:
    workspace = build_workspace_state(
        {"title": "  분석 작업공간  "},
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert workspace["tenant_id"] == DEFAULT_TENANT_ID
    assert workspace["owner_user_id"] == DEFAULT_USER_ID
    assert workspace["title"] == "분석 작업공간"
    assert workspace["locale"] == "ko-KR"
    assert workspace["runtime_defaults"]["prompt_binding_id"] == "ae.grounded_chat.default"
    assert workspace["activity_summary"]["activity_count"] == 1


def test_workspace_state_accepts_runtime_overrides() -> None:
    workspace = build_workspace_state(
        {
            "tenant_id": "tenant-a",
            "owner_user_id": "user-a",
            "title": "Report",
            "runtime_defaults": {
                "locale": "en-US",
                "execution_mode": "GENERAL_ANSWER",
                "template_id": "memo",
                "output_contract_id": "memo_v1",
                "retrieval_profile": {"search_strategy": "bm25"},
                "generation_alias": "general-llm-default",
            },
        },
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert workspace["tenant_id"] == "tenant-a"
    assert workspace["owner_user_id"] == "user-a"
    assert workspace["locale"] == "en-US"
    assert workspace["runtime_defaults"]["execution_mode"] == "GENERAL_ANSWER"
    assert workspace["runtime_defaults"]["retrieval_profile"] == {"search_strategy": "bm25"}


def test_workspace_validation_rejects_invalid_owner_title_and_runtime() -> None:
    assert owner_scope_from_payload({}) == (DEFAULT_TENANT_ID, DEFAULT_USER_ID)
    assert owner_scope_from_payload({"tenant_id": " t ", "user_id": " u "}) == ("t", "u")
    assert workspace_title_from_payload({"title": "x" * 140}) == "x" * 120

    invalid_payloads = [
        {"tenant_id": "", "user_id": "user-a"},
        {"tenant_id": "tenant-a", "owner_user_id": ""},
        {"title": ""},
        {"runtime_defaults": []},
        {"runtime_defaults": {"locale": ""}},
    ]
    for payload in invalid_payloads:
        with pytest.raises(WorkspaceError):
            build_workspace_state(payload, request_id=REQUEST_ID, trace_id=TRACE_ID)


def test_runtime_defaults_accepts_none_as_defaults() -> None:
    defaults = runtime_defaults_from_payload({"runtime_defaults": None})

    assert defaults["locale"] == "ko-KR"
    assert defaults["retrieval_profile"] == {"search_strategy": "hybrid"}


def test_workspace_store_records_activity_and_readback() -> None:
    store = WorkspaceStateStore()
    workspace = store.create_workspace(
        payload={"title": "분석 작업공간"},
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    activity = store.append_activity(
        workspace_id=workspace["workspace_id"],
        activity_type="chat.interaction.created",
        request_id="request-002",
        trace_id=TRACE_ID,
        summary="Chat interaction created.",
        metadata={"interaction_id": "chat-001"},
    )

    assert store.get_workspace(workspace["workspace_id"]) == workspace
    assert activity["metadata"] == {"interaction_id": "chat-001"}
    assert len(store.list_activities(workspace["workspace_id"])) == 2

    with pytest.raises(WorkspaceError):
        store.append_activity(
            workspace_id="missing",
            activity_type="chat.interaction.created",
            request_id="request-002",
            trace_id=TRACE_ID,
            summary="Missing.",
        )
    assert store.list_activities("missing") is None


def test_workspace_routes_create_read_activity_and_require_auth() -> None:
    client, store = build_client()

    unauthorized = client.post("/api/v1/workspaces", json={"title": "분석"})
    created = client.post(
        "/api/v1/workspaces",
        json={
            "title": "분석",
            "tenant_id": "tenant-a",
            "owner_user_id": "user-a",
        },
        headers=auth_headers(),
    )
    workspace = created.json()
    readback = client.get(
        f"/api/v1/workspaces/{workspace['workspace_id']}",
        headers=auth_headers(),
    )
    activity = client.get(
        f"/api/v1/workspaces/{workspace['workspace_id']}/activity",
        headers=auth_headers(),
    )

    assert unauthorized.status_code == 401
    assert created.status_code == 200
    assert store.get_workspace(workspace["workspace_id"]) == workspace
    assert readback.status_code == 200
    assert readback.json()["workspace_id"] == workspace["workspace_id"]
    assert activity.status_code == 200
    assert activity.json()["activities"][0]["activity_type"] == "workspace.created"


def test_workspace_routes_report_invalid_and_missing() -> None:
    client, _ = build_client()

    invalid = client.post(
        "/api/v1/workspaces",
        json={"title": "x", "tenant_id": ""},
        headers=auth_headers(),
    )
    missing_workspace = client.get("/api/v1/workspaces/missing", headers=auth_headers())
    missing_activity = client.get(
        "/api/v1/workspaces/missing/activity",
        headers=auth_headers(),
    )

    assert invalid.status_code == 400
    assert invalid.json()["error_code"] == "ae.workspace_owner_invalid"
    assert missing_workspace.status_code == 404
    assert missing_workspace.json()["error_code"] == "ae.workspace_not_found"
    assert missing_activity.status_code == 404
