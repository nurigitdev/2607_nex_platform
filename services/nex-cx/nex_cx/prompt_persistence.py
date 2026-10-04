from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker


@dataclass(frozen=True)
class CxPromptRepositoryError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class SqlAlchemyCxPromptRegistryStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get_binding(self, binding_key: str) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                return _load_binding(session, binding_key)
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def get_template_version(
        self,
        prompt_template_version_id: str,
    ) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                return _load_template_version(session, prompt_template_version_id)
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def save_render_event(self, record: dict[str, Any]) -> dict[str, Any]:
        try:
            with self._session_factory() as session:
                metadata = json.dumps(
                    record.get("metadata") or {},
                    ensure_ascii=False,
                    sort_keys=True,
                )
                metadata_value = (
                    "CAST(:metadata AS jsonb)"
                    if session.get_bind().dialect.name == "postgresql"
                    else ":metadata"
                )
                session.execute(
                    text(
                        f"""
                        INSERT INTO cx_prompt_render_events (
                            prompt_render_event_id, prompt_binding_id,
                            prompt_template_version_id, trace_id, request_id,
                            rendered_prompt_hash, rendered_prompt_preview,
                            user_prompt_hash, output_hash, metadata, created_at
                        ) VALUES (
                            :prompt_render_event_id, :prompt_binding_id,
                            :prompt_template_version_id, :trace_id, :request_id,
                            :rendered_prompt_hash, :rendered_prompt_preview,
                            :user_prompt_hash, :output_hash, {metadata_value},
                            :created_at
                        ) ON CONFLICT (prompt_render_event_id) DO NOTHING
                        """
                    ),
                    {**record, "metadata": metadata},
                )
                saved = _load_render_event(
                    session, str(record["prompt_render_event_id"])
                )
                session.commit()
                if saved is None:
                    raise CxPromptRepositoryError(
                        "cx.prompt_render_event_write_conflict",
                        "CX prompt render event was not readable after write.",
                        True,
                    )
                return saved
        except CxPromptRepositoryError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def get_render_event(
        self,
        prompt_render_event_id: str,
    ) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                return _load_render_event(session, prompt_render_event_id)
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def list_bindings(self) -> list[dict[str, Any]]:
        try:
            with self._session_factory() as session:
                rows = session.execute(
                    text(
                        """
                        SELECT prompt_binding_id, binding_key,
                               prompt_template_version_id, service_id, purpose,
                               status, bound_at
                        FROM cx_prompt_bindings
                        ORDER BY binding_key ASC
                        """
                    )
                ).mappings()
                return [_binding_from_row(row) for row in rows]
        except SQLAlchemyError as exc:
            raise _unavailable() from exc


def _load_binding(session: Session, binding_key: str) -> dict[str, Any] | None:
    row = session.execute(
        text(
            """
            SELECT prompt_binding_id, binding_key, prompt_template_version_id,
                   service_id, purpose, status, bound_at
            FROM cx_prompt_bindings
            WHERE binding_key = :binding_key
            """
        ),
        {"binding_key": binding_key},
    ).mappings().first()
    return None if row is None else _binding_from_row(row)


def _load_template_version(
    session: Session, version_id: str
) -> dict[str, Any] | None:
    row = session.execute(
        text(
            """
            SELECT prompt_template_version_id, prompt_template_id, version,
                   role, segment_order, content, content_sha256,
                   model_capability, summary_max_chars,
                   summary_hard_limit_chars, metadata, status, created_at
            FROM cx_prompt_template_versions
            WHERE prompt_template_version_id = :version_id
            """
        ),
        {"version_id": version_id},
    ).mappings().first()
    return None if row is None else _version_from_row(row)


def _load_render_event(session: Session, event_id: str) -> dict[str, Any] | None:
    row = session.execute(
        text(
            """
            SELECT e.prompt_render_event_id, e.prompt_binding_id,
                   e.prompt_template_version_id, e.trace_id, e.request_id,
                   e.rendered_prompt_hash, e.rendered_prompt_preview,
                   e.user_prompt_hash, e.output_hash, e.metadata, e.created_at,
                   b.binding_key, b.service_id, b.purpose
            FROM cx_prompt_render_events e
            LEFT JOIN cx_prompt_bindings b
              ON b.prompt_binding_id = e.prompt_binding_id
            WHERE e.prompt_render_event_id = :event_id
            """
        ),
        {"event_id": event_id},
    ).mappings().first()
    return None if row is None else _render_event_from_row(row)


def _binding_from_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    return {
        **data,
        "prompt_binding_id": str(data["prompt_binding_id"]),
        "prompt_template_version_id": str(data["prompt_template_version_id"]),
        "bound_at": _datetime_value(data["bound_at"]),
    }


def _version_from_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    return {
        **data,
        "prompt_template_version_id": str(data["prompt_template_version_id"]),
        "prompt_template_id": str(data["prompt_template_id"]),
        "segment_order": int(data["segment_order"]),
        "metadata": _json_value(data["metadata"], {}),
        "created_at": _datetime_value(data["created_at"]),
    }


def _render_event_from_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    return {
        "prompt_render_event_schema_version": "prompt_render_event.v1",
        "prompt_render_event_id": str(data["prompt_render_event_id"]),
        "service_id": data["service_id"],
        "prompt_binding_id": str(data["prompt_binding_id"]),
        "prompt_template_version_id": str(data["prompt_template_version_id"]),
        "binding_key": data["binding_key"],
        "purpose": data["purpose"],
        "trace_id": data["trace_id"],
        "request_id": data["request_id"],
        "rendered_prompt_hash": data["rendered_prompt_hash"],
        "rendered_prompt_preview": data["rendered_prompt_preview"],
        "user_prompt_hash": data["user_prompt_hash"],
        "output_hash": data["output_hash"],
        "metadata": _json_value(data["metadata"], {}),
        "created_at": _datetime_value(data["created_at"]),
    }


def _json_value(value: Any, default: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return default if value is None else value


def _datetime_value(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat().replace("+00:00", "Z")
    return str(value)


def _unavailable() -> CxPromptRepositoryError:
    return CxPromptRepositoryError(
        "cx.prompt_registry_unavailable",
        "CX prompt registry is unavailable.",
        True,
    )
