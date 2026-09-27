from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from nex_ae_api.workspace import (
    DEFAULT_TENANT_ID,
    DEFAULT_USER_ID,
    DEFAULT_WORKSPACE_STORE,
    WorkspaceError,
    WorkspaceStateStore,
    build_default_workspace_store,
    build_workspace_activity,
    build_workspace_state,
    owner_scope_from_payload,
    register_workspace_routes,
    runtime_defaults_from_payload,
    workspace_title_from_payload,
)
from nex_ae_api.workspace_persistence import SqlAlchemyWorkspaceRepository
from nex_runtime import (
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
    issue_mock_user_token,
)


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


def auth_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience="nex-ae-api")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def user_headers(tenant_id: str, user_id: str) -> dict[str, str]:
    issued = issue_mock_user_token(tenant_id=tenant_id, user_id=user_id)
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


def test_workspace_store_is_idempotent_and_rejects_owner_collision() -> None:
    store = WorkspaceStateStore()
    original = build_workspace_state(
        {
            "workspace_id": "workspace-a",
            "tenant_id": "tenant-a",
            "owner_user_id": "user-a",
        },
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    initial = build_workspace_activity(
        workspace_id="workspace-a",
        activity_type="workspace.created",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        summary="Created.",
        created_at="2026-09-27T00:00:00Z",
    )

    assert store.save_workspace(original, initial) == original
    assert store.save_workspace(original, initial) == original
    assert store.append_activity_record(initial) == initial
    assert len(store.list_activities("workspace-a")) == 1

    conflicting = {**original, "owner_user_id": "user-b"}
    with pytest.raises(WorkspaceError) as exc:
        store.save_workspace(conflicting, initial)
    assert exc.value.error_code == "ae.workspace_owner_conflict"

    with pytest.raises(WorkspaceError) as exc:
        store.append_activity_record({**initial, "workspace_id": "missing"})
    assert exc.value.error_code == "ae.workspace_not_found"


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


def test_default_workspace_store_falls_back_to_memory() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])

    assert build_default_workspace_store(app) is DEFAULT_WORKSPACE_STORE


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

    assert client.get("/api/v1/workspaces/missing").status_code == 401
    assert client.get("/api/v1/workspaces/missing/activity").status_code == 401


def test_browser_workspace_routes_derive_owner_and_hide_cross_owner_records() -> None:
    client, _ = build_client()
    owner = user_headers("tenant-a", "user-a")
    other = user_headers("tenant-a", "user-b")

    created = client.post(
        "/api/v1/workspaces",
        json={"title": "Private workspace"},
        headers=owner,
    )
    workspace = created.json()

    assert created.status_code == 200
    assert workspace["tenant_id"] == "tenant-a"
    assert workspace["owner_user_id"] == "user-a"
    assert client.get(
        f"/api/v1/workspaces/{workspace['workspace_id']}", headers=owner
    ).status_code == 200
    assert client.get(
        f"/api/v1/workspaces/{workspace['workspace_id']}", headers=other
    ).status_code == 404
    assert client.get(
        f"/api/v1/workspaces/{workspace['workspace_id']}/activity", headers=other
    ).status_code == 404


def test_browser_workspace_route_rejects_payload_owner_mismatch() -> None:
    client, _ = build_client()

    response = client.post(
        "/api/v1/workspaces",
        json={
            "title": "Private workspace",
            "tenant_id": "tenant-a",
            "owner_user_id": "user-b",
        },
        headers=user_headers("tenant-a", "user-a"),
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "ae.browser_owner_scope_mismatch"


def test_workspace_routes_select_sql_repository_from_runtime() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE ae_workspaces (
                workspace_id TEXT PRIMARY KEY, workspace_schema_version TEXT NOT NULL,
                tenant_id TEXT NOT NULL, owner_user_id TEXT NOT NULL, title TEXT NOT NULL,
                locale TEXT NOT NULL, chat_document_id TEXT NOT NULL UNIQUE,
                runtime_defaults TEXT NOT NULL, activity_count INTEGER NOT NULL,
                last_activity_type TEXT, trace_id TEXT NOT NULL, request_id TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )
        """))
        connection.execute(text("""
            CREATE TABLE ae_workspace_activities (
                activity_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL,
                activity_schema_version TEXT NOT NULL, activity_type TEXT NOT NULL,
                trace_id TEXT NOT NULL, request_id TEXT NOT NULL, summary TEXT NOT NULL,
                metadata TEXT NOT NULL, created_at TEXT NOT NULL
            )
        """))
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    app.state.nex_persistence = SimpleNamespace(api_session_factory=factory)

    selected = build_default_workspace_store(app)
    register_workspace_routes(app)
    response = TestClient(app).post(
        "/api/v1/workspaces",
        json={"title": "Durable workspace"},
        headers=user_headers("tenant-a", "user-a"),
    )

    assert isinstance(selected, SqlAlchemyWorkspaceRepository)
    assert isinstance(app.state.ae_workspace_store, SqlAlchemyWorkspaceRepository)
    assert response.status_code == 200
    assert app.state.ae_workspace_store.get_workspace(
        response.json()["workspace_id"]
    )["owner_user_id"] == "user-a"


def test_workspace_routes_map_repository_unavailability() -> None:
    engine = create_engine("sqlite+pysqlite://", future=True)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    app.state.nex_persistence = SimpleNamespace(api_session_factory=factory)
    register_workspace_routes(app)
    client = TestClient(app)

    created = client.post(
        "/api/v1/workspaces",
        json={"title": "Unavailable"},
        headers=user_headers("tenant-a", "user-a"),
    )
    readback = client.get(
        "/api/v1/workspaces/missing",
        headers=user_headers("tenant-a", "user-a"),
    )

    assert created.status_code == 503
    assert created.json()["error_code"] == "ae.workspace_store_unavailable"
    assert readback.status_code == 503
