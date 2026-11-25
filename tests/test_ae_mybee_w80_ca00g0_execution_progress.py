from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
from nex_ae_api import interaction_execution_progress as progress_api
from nex_ae_api.interaction_execution_progress import (
    InteractionExecutionProgressError,
    InteractionProgressRecorder,
    SqlAlchemyInteractionExecutionProgressSource,
    project_interaction_execution_progress,
    register_interaction_execution_progress_routes,
)
from nex_ae_api.route_auth import (
    AeFacadeRouteAuthContext,
    BrowserUserAuthContext,
)
from nex_ae_api.workspace import build_workspace_activity
from nex_ae_api.workspace_persistence import WorkspaceRepositoryError
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

INTERACTION_ID = "10000000-0000-4000-8000-000000000001"
WORKSPACE_ID = "20000000-0000-4000-8000-000000000001"
TRACE_ID = "1" * 32
NOW = datetime(2026, 11, 25, 1, 2, 3, tzinfo=UTC)


class _ActivityStore:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, object]] = {}

    def append_activity_record(self, activity):
        self.records.setdefault(activity["activity_id"], activity)
        return self.records[activity["activity_id"]]


class _FailingActivityStore:
    def __init__(self, *, missing: bool = False) -> None:
        self.missing = missing

    def append_activity_record(self, _activity):
        if self.missing:
            return
        raise WorkspaceRepositoryError("workspace.failed", "store failed", True)


def test_progress_recorder_is_deterministic_replay_safe_and_private() -> None:
    store = _ActivityStore()
    recorder = InteractionProgressRecorder(store, clock=lambda: NOW)
    values = {
        "workspace_id": WORKSPACE_ID,
        "interaction_id": INTERACTION_ID,
        "event_code": "IA_INTENT_STARTED",
        "state": "STARTED",
        "request_id": "request-1",
        "trace_id": TRACE_ID,
        "agent_type": "IA",
        "source_ref": "AE:AGENT_EXECUTION:one:INTENT:STARTED",
    }

    first = recorder.append(**values)
    replay = recorder.append(**values)

    assert first["activity_id"] == replay["activity_id"]
    assert len(store.records) == 1
    assert first["metadata"] == {
        "interaction_id": INTERACTION_ID,
        "event_code": "IA_INTENT_STARTED",
        "state": "STARTED",
        "agent_type": "IA",
        "source_ref": "AE:AGENT_EXECUTION:one:INTENT:STARTED",
        "terminal": False,
        "private_payload_included": False,
    }
    assert "prompt" not in json.dumps(first).lower()

    sink = recorder.semantic_sink(
        workspace_id=WORKSPACE_ID,
        interaction_id=INTERACTION_ID,
        agent_type="pa",
        request_id="request-1",
        trace_id=TRACE_ID,
        source_ref="AE:AGENT_EXECUTION:one:PA",
    )
    sink("plan", "completed")
    assert any(
        record["metadata"]["event_code"] == "PA_PLAN_COMPLETED"
        for record in store.records.values()
    )


def test_progress_recorder_translates_repository_failures() -> None:
    common = {
        "workspace_id": WORKSPACE_ID,
        "interaction_id": INTERACTION_ID,
        "event_code": "IA_INTENT_STARTED",
        "state": "STARTED",
        "request_id": "request-1",
        "trace_id": TRACE_ID,
    }
    with pytest.raises(InteractionExecutionProgressError) as failed:
        InteractionProgressRecorder(_FailingActivityStore()).append(**common)
    assert str(failed.value) == "store failed"
    assert failed.value.retryable is True
    assert (
        InteractionProgressRecorder(_FailingActivityStore()).append_observation(
            **common
        )
        is None
    )

    with pytest.raises(InteractionExecutionProgressError) as missing:
        InteractionProgressRecorder(
            _FailingActivityStore(missing=True)
        ).append(**common)
    assert missing.value.error_code == "ae.interaction_progress_workspace_missing"

    with pytest.raises(InteractionExecutionProgressError) as invalid:
        InteractionProgressRecorder(_ActivityStore()).append(
            **{**common, "event_code": ""}
        )
    assert invalid.value.error_code == "ae.interaction_progress_field_invalid"


def test_progress_projection_orders_boundaries_and_applies_cursor() -> None:
    started = build_workspace_activity(
        workspace_id=WORKSPACE_ID,
        activity_type="chat.interaction.started",
        request_id="request-1",
        trace_id=TRACE_ID,
        summary="started",
        metadata={"interaction_id": INTERACTION_ID, "status": "PENDING"},
        created_at="2026-11-25T01:02:03Z",
        activity_id="30000000-0000-4000-8000-000000000001",
    )
    intent = build_workspace_activity(
        workspace_id=WORKSPACE_ID,
        activity_type="agent.execution.progress",
        request_id="request-1",
        trace_id=TRACE_ID,
        summary="intent",
        metadata={
            "interaction_id": INTERACTION_ID,
            "event_code": "IA_INTENT_STARTED",
            "state": "STARTED",
            "agent_type": "IA",
            "source_ref": "AE:INTENT",
            "terminal": False,
        },
        created_at="2026-11-25T01:02:03Z",
        activity_id="30000000-0000-4000-8000-000000000002",
    )
    unrelated = {**intent, "metadata": {**intent["metadata"], "interaction_id": "other"}}

    projection = project_interaction_execution_progress(
        interaction_id=INTERACTION_ID,
        workspace_id=WORKSPACE_ID,
        activities=[intent, unrelated, started],
        execution={"state": "RUNNING"},
        after_sequence=1,
    )

    assert projection["next_sequence"] == 2
    assert [event["event_code"] for event in projection["events"]] == [
        "IA_INTENT_STARTED"
    ]
    assert projection["events"][0]["sequence"] == 2
    assert projection["terminal"] is False
    _validate_contract({**projection, "events": project_interaction_execution_progress(
        interaction_id=INTERACTION_ID,
        workspace_id=WORKSPACE_ID,
        activities=[intent, started],
        execution={"state": "RUNNING"},
    )["events"]})


def test_progress_projection_stops_on_terminal_result() -> None:
    result = build_workspace_activity(
        workspace_id=WORKSPACE_ID,
        activity_type="agent.result.published",
        request_id="request-2",
        trace_id=TRACE_ID,
        summary="published",
        metadata={
            "interaction_ref": f"AE:CHAT_INTERACTION:{INTERACTION_ID}",
        },
        created_at="2026-11-25T01:04:03Z",
        activity_id="30000000-0000-4000-8000-000000000003",
    )

    projection = project_interaction_execution_progress(
        interaction_id=INTERACTION_ID,
        workspace_id=WORKSPACE_ID,
        activities=[result],
        execution={"state": "SUCCEEDED"},
    )

    assert projection["terminal"] is True
    assert projection["status"] == "SUCCEEDED"
    assert projection["events"][0]["event_code"] == "RESULT_PUBLISHED"


@pytest.mark.parametrize(
    ("activity_type", "expected_status"),
    [
        ("chat.interaction.no_answer", "NO_ANSWER"),
        ("chat.interaction.failed", "FAILED"),
        ("chat.interaction.completed", "COMPLETED"),
    ],
)
def test_progress_projection_maps_terminal_interaction_states(
    activity_type: str,
    expected_status: str,
) -> None:
    projection = project_interaction_execution_progress(
        interaction_id=INTERACTION_ID,
        workspace_id=WORKSPACE_ID,
        activities=[
            {
                "activity_id": "30000000-0000-4000-8000-000000000004",
                "activity_type": activity_type,
                "metadata": json.dumps(
                    {"interaction_id": INTERACTION_ID, "status": expected_status}
                ),
                "created_at": "2026-11-25T01:05:03",
            },
            {
                "activity_id": "30000000-0000-4000-8000-000000000005",
                "activity_type": "unprojected.activity",
                "metadata": {"interaction_id": INTERACTION_ID},
                "created_at": NOW,
            },
        ],
    )

    assert projection["terminal"] is True
    assert projection["status"] == expected_status
    assert len(projection["events"]) == 1

    malformed = project_interaction_execution_progress(
        interaction_id=INTERACTION_ID,
        workspace_id=WORKSPACE_ID,
        activities=[
            {
                "activity_id": "30000000-0000-4000-8000-000000000009",
                "activity_type": "agent.execution.progress",
                "metadata": "[]",
                "created_at": NOW,
            },
            {
                "activity_id": "30000000-0000-4000-8000-000000000010",
                "activity_type": "agent.execution.progress",
                "metadata": None,
                "created_at": NOW,
            },
        ],
    )
    assert malformed["events"] == []


def test_sql_source_enforces_owner_scope_and_projects_durable_rows() -> None:
    session_factory = _sqlite_progress_session_factory()
    source = SqlAlchemyInteractionExecutionProgressSource(session_factory)

    projection = source.project_owner_progress(
        tenant_id="VO00",
        owner_user_id="owner-1",
        interaction_id=INTERACTION_ID,
    )

    assert projection is not None
    assert projection["terminal"] is True
    assert projection["status"] == "SUCCEEDED"
    assert projection["events"][0]["event_code"] == "IA_INTENT_STARTED"
    assert source.project_owner_progress(
        tenant_id="VO00",
        owner_user_id="other-owner",
        interaction_id=INTERACTION_ID,
    ) is None

    with pytest.raises(InteractionExecutionProgressError) as invalid_cursor:
        source.project_owner_progress(
            tenant_id="VO00",
            owner_user_id="owner-1",
            interaction_id=INTERACTION_ID,
            after_sequence=-1,
        )
    assert invalid_cursor.value.error_code == "ae.interaction_progress_cursor_invalid"

    with pytest.raises(InteractionExecutionProgressError) as invalid_id:
        source.project_owner_progress(
            tenant_id="VO00",
            owner_user_id="owner-1",
            interaction_id="not-a-uuid",
        )
    assert invalid_id.value.error_code == "ae.interaction_progress_field_invalid"


def test_sql_source_translates_database_unavailability() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    source = SqlAlchemyInteractionExecutionProgressSource(
        sessionmaker(bind=engine, expire_on_commit=False)
    )

    with pytest.raises(InteractionExecutionProgressError) as failure:
        source.project_owner_progress(
            tenant_id="VO00",
            owner_user_id="owner-1",
            interaction_id=INTERACTION_ID,
        )
    assert failure.value.error_code == "ae.interaction_progress_store_unavailable"
    assert failure.value.retryable is True


def test_progress_route_is_browser_owner_scoped_and_cursor_aware(monkeypatch) -> None:
    calls = []
    source = SimpleNamespace(
        project_owner_progress=lambda **values: calls.append(values)
        or project_interaction_execution_progress(
            interaction_id=INTERACTION_ID,
            workspace_id=WORKSPACE_ID,
            activities=[],
        )
    )
    app = FastAPI()
    register_interaction_execution_progress_routes(app, source=source)
    browser = BrowserUserAuthContext(
        tenant_id="VO00",
        user_id="owner-1",
        scopes=("workspace:use",),
        roles=("employee",),
    )
    monkeypatch.setattr(
        progress_api,
        "authorize_ae_facade_route_request",
        lambda *_args, **_kwargs: AeFacadeRouteAuthContext(
            auth_mode="browser_user",
            browser_context=browser,
        ),
    )

    response = TestClient(app).get(
        f"/api/v1/chat/interactions/{INTERACTION_ID}/execution-progress",
        params={"after_sequence": 4},
    )

    assert response.status_code == 200
    assert calls == [{
        "tenant_id": "VO00",
        "owner_user_id": "owner-1",
        "interaction_id": INTERACTION_ID,
        "after_sequence": 4,
    }]


def test_progress_route_rejects_service_missing_source_and_invalid_cursor(monkeypatch) -> None:
    app = FastAPI()
    register_interaction_execution_progress_routes(app, source=None)
    monkeypatch.setattr(
        progress_api,
        "authorize_ae_facade_route_request",
        lambda *_args, **_kwargs: AeFacadeRouteAuthContext(
            auth_mode="service",
            service_claims=SimpleNamespace(service_id="nex-ag"),
        ),
    )
    route = f"/api/v1/chat/interactions/{INTERACTION_ID}/execution-progress"
    assert TestClient(app).get(route).status_code == 403

    browser = BrowserUserAuthContext(
        tenant_id="VO00",
        user_id="owner-1",
        scopes=("workspace:use",),
        roles=("employee",),
    )
    monkeypatch.setattr(
        progress_api,
        "authorize_ae_facade_route_request",
        lambda *_args, **_kwargs: AeFacadeRouteAuthContext(
            auth_mode="browser_user",
            browser_context=browser,
        ),
    )
    assert TestClient(app).get(route).status_code == 503

    invalid_app = FastAPI()
    register_interaction_execution_progress_routes(
        invalid_app,
        source=SimpleNamespace(
            project_owner_progress=lambda **_values: (_ for _ in ()).throw(
                InteractionExecutionProgressError(
                    "ae.interaction_progress_cursor_invalid",
                    "bounded failure",
                )
            )
        ),
    )
    assert TestClient(invalid_app).get(route).status_code == 400

    missing_app = FastAPI()
    register_interaction_execution_progress_routes(
        missing_app,
        source=SimpleNamespace(project_owner_progress=lambda **_values: None),
    )
    assert TestClient(missing_app).get(route).status_code == 404

    unavailable_app = FastAPI()
    register_interaction_execution_progress_routes(
        unavailable_app,
        source=SimpleNamespace(
            project_owner_progress=lambda **_values: (_ for _ in ()).throw(
                InteractionExecutionProgressError(
                    "ae.interaction_progress_store_unavailable",
                    "store unavailable",
                    True,
                )
            )
        ),
    )
    assert TestClient(unavailable_app).get(route).status_code == 503

    unauthorized_app = FastAPI()
    register_interaction_execution_progress_routes(unauthorized_app, source=None)
    monkeypatch.setattr(
        progress_api,
        "authorize_ae_facade_route_request",
        lambda *_args, **_kwargs: JSONResponse({"detail": "no"}, status_code=401),
    )
    assert TestClient(unauthorized_app).get(route).status_code == 401


def _sqlite_progress_session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE ae_workspaces (workspace_id TEXT, tenant_id TEXT, "
            "owner_user_id TEXT)"
        ))
        connection.execute(text(
            "CREATE TABLE ae_chat_interactions (chat_interaction_id TEXT, "
            "workspace_id TEXT, tenant_id TEXT, user_id TEXT)"
        ))
        connection.execute(text(
            "CREATE TABLE ae_workspace_activities (activity_id TEXT, "
            "workspace_id TEXT, activity_type TEXT, summary TEXT, metadata TEXT, "
            "created_at TEXT)"
        ))
        connection.execute(text(
            "CREATE TABLE ae_agent_execution (tenant_id TEXT, "
            "legacy_interaction_id TEXT, principal_id TEXT, state TEXT, "
            "phase TEXT, updated_at TEXT)"
        ))
        connection.execute(
            text("INSERT INTO ae_workspaces VALUES (:workspace, 'VO00', 'owner-1')"),
            {"workspace": WORKSPACE_ID},
        )
        connection.execute(
            text(
                "INSERT INTO ae_chat_interactions VALUES "
                "(:interaction, :workspace, 'VO00', 'owner-1')"
            ),
            {"interaction": INTERACTION_ID, "workspace": WORKSPACE_ID},
        )
        connection.execute(
            text(
                "INSERT INTO ae_workspace_activities VALUES "
                "(:activity, :workspace, 'agent.execution.progress', 'intent', "
                ":metadata, '2026-11-25T01:02:03Z')"
            ),
            {
                "activity": "30000000-0000-4000-8000-000000000006",
                "workspace": WORKSPACE_ID,
                "metadata": json.dumps({
                    "interaction_id": INTERACTION_ID,
                    "event_code": "IA_INTENT_STARTED",
                    "state": "STARTED",
                }),
            },
        )
        connection.execute(
            text(
                "INSERT INTO ae_agent_execution VALUES "
                "('VO00', :interaction, 'owner-1', 'SUCCEEDED', "
                "'RESULT_VERIFY', '2026-11-25T01:03:03Z')"
            ),
            {"interaction": INTERACTION_ID},
        )
    return sessionmaker(bind=engine, expire_on_commit=False)


def _validate_contract(value: dict[str, object]) -> None:
    path = Path(
        "contracts/schemas/service/nex_ae_api/interaction_execution_progress.v1.schema.json"
    )
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
