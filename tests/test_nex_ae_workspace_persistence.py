from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import nex_ae_api.workspace_persistence as persistence
from nex_ae_api.workspace_persistence import (
    SqlAlchemyWorkspaceRepository,
    WorkspaceRepositoryError,
)


def session_factory(*, with_schema: bool = True):
    engine = create_engine("sqlite+pysqlite://", future=True)
    if with_schema:
        with engine.begin() as connection:
            connection.execute(text("""
                CREATE TABLE ae_workspaces (
                    workspace_id TEXT PRIMARY KEY,
                    workspace_schema_version TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    locale TEXT NOT NULL,
                    chat_document_id TEXT NOT NULL UNIQUE,
                    runtime_defaults TEXT NOT NULL,
                    activity_count INTEGER NOT NULL,
                    last_activity_type TEXT,
                    trace_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """))
            connection.execute(text("""
                CREATE TABLE ae_workspace_activities (
                    activity_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    activity_schema_version TEXT NOT NULL,
                    activity_type TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """))
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def workspace(**overrides):
    record = {
        "workspace_schema_version": "ae_workspace_state.v1",
        "workspace_id": "11111111-1111-4111-8111-111111111111",
        "tenant_id": "tenant-a",
        "owner_user_id": "user-a",
        "title": "Workspace A",
        "locale": "ko-KR",
        "chat_document_id": "22222222-2222-4222-8222-222222222222",
        "runtime_defaults": {"execution_mode": "GROUNDED_ANSWER"},
        "activity_summary": {
            "activity_count": 1,
            "last_activity_type": "workspace.created",
        },
        "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
        "request_id": "request-a",
        "created_at": "2026-09-27T00:00:00Z",
        "updated_at": "2026-09-27T00:00:00Z",
    }
    return {**record, **overrides}


def activity(**overrides):
    record = {
        "activity_schema_version": "ae_workspace_activity.v1",
        "activity_id": "33333333-3333-4333-8333-333333333333",
        "workspace_id": "11111111-1111-4111-8111-111111111111",
        "activity_type": "workspace.created",
        "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
        "request_id": "request-a",
        "summary": "Workspace created.",
        "metadata": {"source": "test"},
        "created_at": "2026-09-27T00:00:00Z",
    }
    return {**record, **overrides}


def test_repository_creates_reads_and_lists_initial_activity() -> None:
    repository = SqlAlchemyWorkspaceRepository(session_factory())

    created = repository.create_workspace(workspace(), activity())
    loaded = repository.get_workspace(created["workspace_id"])
    activities = repository.list_activities(created["workspace_id"])

    assert created == workspace()
    assert loaded == workspace()
    assert activities == [activity()]


def test_create_is_idempotent_and_rejects_cross_owner_collision() -> None:
    repository = SqlAlchemyWorkspaceRepository(session_factory())
    repository.create_workspace(workspace(), activity())

    repeated = repository.create_workspace(
        workspace(title="Ignored retry title"),
        activity(activity_id="44444444-4444-4444-8444-444444444444"),
    )
    assert repeated == workspace()
    assert len(repository.list_activities(workspace()["workspace_id"])) == 1

    with pytest.raises(WorkspaceRepositoryError) as exc:
        repository.create_workspace(
            workspace(owner_user_id="user-b"),
            activity(activity_id="55555555-5555-4555-8555-555555555555"),
        )
    assert exc.value.error_code == "ae.workspace_owner_conflict"


def test_create_fails_retryably_when_conflicting_row_cannot_be_reloaded(
    monkeypatch,
) -> None:
    repository = SqlAlchemyWorkspaceRepository(session_factory())
    repository.create_workspace(workspace(), activity())
    monkeypatch.setattr(persistence, "_load_workspace", lambda *args: None)

    with pytest.raises(WorkspaceRepositoryError) as exc:
        repository.create_workspace(workspace(), activity())

    assert exc.value.error_code == "ae.workspace_write_conflict"
    assert exc.value.retryable is True


def test_append_activity_updates_summary_and_is_idempotent() -> None:
    repository = SqlAlchemyWorkspaceRepository(session_factory())
    repository.create_workspace(workspace(), activity())
    appended = activity(
        activity_id="66666666-6666-4666-8666-666666666666",
        activity_type="chat.interaction.completed",
        summary="Chat completed.",
        created_at="2026-09-27T00:01:00Z",
    )

    assert repository.append_activity(appended) == appended
    assert repository.append_activity(appended) == appended
    loaded = repository.get_workspace(workspace()["workspace_id"])
    assert loaded["activity_summary"] == {
        "activity_count": 2,
        "last_activity_type": "chat.interaction.completed",
    }
    assert len(repository.list_activities(workspace()["workspace_id"])) == 2
    assert repository.append_activity(activity(workspace_id="missing")) is None
    assert repository.list_activities("missing") is None
    assert repository.get_workspace("missing") is None


def test_repository_wraps_database_errors_and_error_string() -> None:
    repository = SqlAlchemyWorkspaceRepository(session_factory(with_schema=False))

    for operation in (
        lambda: repository.create_workspace(workspace(), activity()),
        lambda: repository.get_workspace(workspace()["workspace_id"]),
        lambda: repository.append_activity(activity()),
        lambda: repository.list_activities(workspace()["workspace_id"]),
    ):
        with pytest.raises(WorkspaceRepositoryError) as exc:
            operation()
        assert exc.value.error_code == "ae.workspace_store_unavailable"
        assert exc.value.retryable is True
        assert str(exc.value) == "AE workspace store is unavailable."


def test_sql_helpers_cover_postgres_json_and_datetime_paths() -> None:
    assert "CAST(:runtime_defaults AS jsonb)" in persistence._workspace_insert_sql(
        "postgresql"
    )
    assert "CAST(:metadata AS jsonb)" in persistence._activity_insert_sql("postgresql")
    assert persistence._json_value('{"value": 1}') == {"value": 1}
    assert persistence._json_value({"value": 2}) == {"value": 2}
    assert persistence._datetime_value(
        datetime(2026, 9, 27, tzinfo=UTC)
    ) == "2026-09-27T00:00:00Z"
