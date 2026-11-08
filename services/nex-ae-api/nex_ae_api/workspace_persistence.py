from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker


@dataclass(frozen=True)
class WorkspaceRepositoryError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class SqlAlchemyWorkspaceRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create_workspace(
        self,
        workspace: dict[str, Any],
        initial_activity: dict[str, Any],
    ) -> dict[str, Any]:
        return self.save_workspace(workspace, initial_activity)

    def save_workspace(
        self,
        workspace: dict[str, Any],
        initial_activity: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            with self._session_factory() as session:
                inserted = session.execute(
                    text(_workspace_insert_sql(_dialect_name(session))),
                    _workspace_params(workspace),
                )
                if int(inserted.rowcount or 0) == 0:
                    existing = _load_workspace(session, workspace["workspace_id"])
                    if existing is None:
                        raise WorkspaceRepositoryError(
                            "ae.workspace_write_conflict",
                            "Workspace insert conflicted without a readable record.",
                            True,
                        )
                    if _owner(existing) != _owner(workspace):
                        raise WorkspaceRepositoryError(
                            "ae.workspace_owner_conflict",
                            "Workspace identifier is already owned by another subject.",
                        )
                    _ensure_default_conversation(session, existing)
                    session.commit()
                    return existing
                _insert_activity(session, initial_activity)
                _ensure_default_conversation(session, workspace)
                session.commit()
                return workspace
        except WorkspaceRepositoryError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def get_workspace(self, workspace_id: str) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                return _load_workspace(session, workspace_id)
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def append_activity(self, activity: dict[str, Any]) -> dict[str, Any] | None:
        return self.append_activity_record(activity)

    def append_activity_record(
        self,
        activity: dict[str, Any],
    ) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                if _load_workspace(session, activity["workspace_id"]) is None:
                    return None
                inserted = _insert_activity(session, activity)
                if int(inserted.rowcount or 0) > 0:
                    session.execute(
                        text(
                            """
                            UPDATE ae_workspaces
                            SET activity_count = activity_count + 1,
                                last_activity_type = :activity_type,
                                updated_at = :created_at
                            WHERE workspace_id = :workspace_id
                            """
                        ),
                        activity,
                    )
                session.commit()
                return activity
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def list_activities(self, workspace_id: str) -> list[dict[str, Any]] | None:
        try:
            with self._session_factory() as session:
                if _load_workspace(session, workspace_id) is None:
                    return None
                rows = (
                    session.execute(
                        text(
                            """
                            SELECT activity_schema_version, activity_id, workspace_id,
                                   activity_type, trace_id, request_id, summary,
                                   metadata, created_at
                            FROM ae_workspace_activities
                            WHERE workspace_id = :workspace_id
                            ORDER BY created_at ASC, activity_id ASC
                            """
                        ),
                        {"workspace_id": workspace_id},
                    )
                    .mappings()
                    .all()
                )
                return [_activity_from_row(row) for row in rows]
        except SQLAlchemyError as exc:
            raise _unavailable() from exc


def _workspace_insert_sql(dialect_name: str) -> str:
    runtime_defaults = (
        "CAST(:runtime_defaults AS jsonb)"
        if dialect_name == "postgresql"
        else ":runtime_defaults"
    )
    return f"""
        INSERT INTO ae_workspaces (
            workspace_id, workspace_schema_version, tenant_id, owner_user_id,
            title, locale, chat_document_id, runtime_defaults, activity_count,
            last_activity_type, trace_id, request_id, created_at, updated_at
        ) VALUES (
            :workspace_id, :workspace_schema_version, :tenant_id, :owner_user_id,
            :title, :locale, :chat_document_id, {runtime_defaults}, :activity_count,
            :last_activity_type, :trace_id, :request_id, :created_at, :updated_at
        ) ON CONFLICT (workspace_id) DO NOTHING
    """


def _activity_insert_sql(dialect_name: str) -> str:
    metadata = "CAST(:metadata AS jsonb)" if dialect_name == "postgresql" else ":metadata"
    return f"""
        INSERT INTO ae_workspace_activities (
            activity_id, workspace_id, activity_schema_version, activity_type,
            trace_id, request_id, summary, metadata, created_at
        ) VALUES (
            :activity_id, :workspace_id, :activity_schema_version, :activity_type,
            :trace_id, :request_id, :summary, {metadata}, :created_at
        ) ON CONFLICT (activity_id) DO NOTHING
    """


def _insert_activity(session: Session, activity: dict[str, Any]) -> Any:
    return session.execute(
        text(_activity_insert_sql(_dialect_name(session))),
        _activity_params(activity),
    )


def _ensure_default_conversation(
    session: Session, workspace: dict[str, Any]
) -> None:
    params = {
        "conversation_id": workspace["chat_document_id"],
        "tenant_id": workspace["tenant_id"],
        "workspace_id": workspace["workspace_id"],
        "owner_user_id": workspace["owner_user_id"],
        "title": workspace["title"],
        "created_at": workspace["created_at"],
        "updated_at": workspace["updated_at"],
    }
    session.execute(
        text(
            """
            INSERT INTO ae_conversations (
                conversation_id, tenant_id, workspace_id, owner_user_id,
                title, status, next_journal_seq, created_at, updated_at, version
            ) VALUES (
                :conversation_id, :tenant_id, :workspace_id, :owner_user_id,
                :title, 'ACTIVE', 1, :created_at, :updated_at, 1
            ) ON CONFLICT (conversation_id) DO NOTHING
            """
        ),
        params,
    )
    scope = (
        session.execute(
            text(
                """
                SELECT tenant_id, workspace_id, owner_user_id
                FROM ae_conversations
                WHERE conversation_id = :conversation_id
                """
            ),
            params,
        )
        .mappings()
        .one_or_none()
    )
    if scope is None or (
        str(scope["tenant_id"]),
        str(scope["workspace_id"]),
        str(scope["owner_user_id"]),
    ) != (
        params["tenant_id"],
        params["workspace_id"],
        params["owner_user_id"],
    ):
        raise WorkspaceRepositoryError(
            "ae.workspace_conversation_conflict",
            "Workspace default Conversation belongs to another scope.",
        )


def _load_workspace(session: Session, workspace_id: str) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                """
                SELECT workspace_schema_version, workspace_id, tenant_id,
                       owner_user_id, title, locale, chat_document_id,
                       runtime_defaults, activity_count, last_activity_type,
                       trace_id, request_id, created_at, updated_at
                FROM ae_workspaces
                WHERE workspace_id = :workspace_id
                """
            ),
            {"workspace_id": workspace_id},
        )
        .mappings()
        .first()
    )
    return None if row is None else _workspace_from_row(row)


def _workspace_params(record: dict[str, Any]) -> dict[str, Any]:
    summary = record.get("activity_summary") or {}
    return {
        **record,
        "workspace_schema_version": record["workspace_schema_version"],
        "runtime_defaults": json.dumps(record.get("runtime_defaults") or {}),
        "activity_count": int(summary.get("activity_count") or 0),
        "last_activity_type": summary.get("last_activity_type"),
    }


def _activity_params(record: dict[str, Any]) -> dict[str, Any]:
    return {
        **record,
        "activity_schema_version": record["activity_schema_version"],
        "metadata": json.dumps(record.get("metadata") or {}),
    }


def _workspace_from_row(row: Any) -> dict[str, Any]:
    return {
        "workspace_schema_version": row["workspace_schema_version"],
        "workspace_id": str(row["workspace_id"]),
        "tenant_id": row["tenant_id"],
        "owner_user_id": row["owner_user_id"],
        "title": row["title"],
        "locale": row["locale"],
        "chat_document_id": str(row["chat_document_id"]),
        "runtime_defaults": _json_value(row["runtime_defaults"]),
        "activity_summary": {
            "activity_count": int(row["activity_count"]),
            "last_activity_type": row["last_activity_type"],
        },
        "trace_id": row["trace_id"],
        "request_id": row["request_id"],
        "created_at": _datetime_value(row["created_at"]),
        "updated_at": _datetime_value(row["updated_at"]),
    }


def _activity_from_row(row: Any) -> dict[str, Any]:
    return {
        "activity_schema_version": row["activity_schema_version"],
        "activity_id": str(row["activity_id"]),
        "workspace_id": str(row["workspace_id"]),
        "activity_type": row["activity_type"],
        "trace_id": row["trace_id"],
        "request_id": row["request_id"],
        "summary": row["summary"],
        "metadata": _json_value(row["metadata"]),
        "created_at": _datetime_value(row["created_at"]),
    }


def _json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _datetime_value(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat().replace("+00:00", "Z")
    return str(value)


def _owner(record: dict[str, Any]) -> tuple[str, str]:
    return record["tenant_id"], record["owner_user_id"]


def _dialect_name(session: Session) -> str:
    bind = session.get_bind()
    return bind.dialect.name


def _unavailable() -> WorkspaceRepositoryError:
    return WorkspaceRepositoryError(
        "ae.workspace_store_unavailable",
        "AE workspace store is unavailable.",
        True,
    )
