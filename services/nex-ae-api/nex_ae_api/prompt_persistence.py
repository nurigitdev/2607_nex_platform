from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker


@dataclass(frozen=True)
class PromptRepositoryError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class SqlAlchemyAePromptRegistryStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save_template(self, record: dict[str, Any]) -> dict[str, Any]:
        try:
            with self._session_factory() as session:
                session.execute(text(_template_upsert_sql()), record)
                saved = _load_template_by_key(
                    session,
                    service_id=record["service_id"],
                    purpose=record["purpose"],
                    name=record["name"],
                )
                session.commit()
                return _required_saved(saved)
        except PromptRepositoryError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def save_template_version(self, record: dict[str, Any]) -> dict[str, Any]:
        try:
            with self._session_factory() as session:
                params = {
                    **record,
                    "metadata": json.dumps(
                        record.get("metadata") or {},
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                }
                session.execute(
                    text(_version_upsert_sql(_dialect_name(session))),
                    params,
                )
                saved = _load_template_version_by_key(session, record)
                session.commit()
                return _required_saved(saved)
        except PromptRepositoryError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def save_binding(self, record: dict[str, Any]) -> dict[str, Any]:
        try:
            with self._session_factory() as session:
                session.execute(text(_binding_upsert_sql()), record)
                saved = _load_binding(session, record["binding_key"])
                session.commit()
                return _required_saved(saved)
        except PromptRepositoryError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

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
                params = {
                    **record,
                    "metadata": json.dumps(
                        record.get("metadata") or {},
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                }
                session.execute(
                    text(_render_event_insert_sql(_dialect_name(session))),
                    params,
                )
                saved = _load_render_event(session, record["prompt_render_event_id"])
                session.commit()
                return _required_saved(saved)
        except PromptRepositoryError:
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
                        FROM ae_prompt_bindings
                        ORDER BY binding_key ASC
                        """
                    )
                ).mappings()
                return [_binding_from_row(row) for row in rows]
        except SQLAlchemyError as exc:
            raise _unavailable() from exc


def _template_upsert_sql() -> str:
    return """
        INSERT INTO ae_prompt_templates (
            prompt_template_id, service_id, purpose, name, owner_domain,
            status, created_at, updated_at
        ) VALUES (
            :prompt_template_id, :service_id, :purpose, :name, :owner_domain,
            :status, :created_at, :updated_at
        )
        ON CONFLICT (service_id, purpose, name) DO UPDATE SET
            owner_domain = excluded.owner_domain,
            status = excluded.status,
            updated_at = excluded.updated_at
    """


def _version_upsert_sql(dialect_name: str) -> str:
    metadata = "CAST(:metadata AS jsonb)" if dialect_name == "postgresql" else ":metadata"
    return f"""
        INSERT INTO ae_prompt_template_versions (
            prompt_template_version_id, prompt_template_id, version, role,
            segment_order, content, content_sha256, model_capability, metadata,
            status, created_at
        ) VALUES (
            :prompt_template_version_id, :prompt_template_id, :version, :role,
            :segment_order, :content, :content_sha256, :model_capability,
            {metadata}, :status, :created_at
        )
        ON CONFLICT (prompt_template_id, version, role, segment_order)
        DO UPDATE SET
            content = excluded.content,
            content_sha256 = excluded.content_sha256,
            model_capability = excluded.model_capability,
            metadata = excluded.metadata,
            status = excluded.status
    """


def _binding_upsert_sql() -> str:
    return """
        INSERT INTO ae_prompt_bindings (
            prompt_binding_id, binding_key, prompt_template_version_id,
            service_id, purpose, status, bound_at
        ) VALUES (
            :prompt_binding_id, :binding_key, :prompt_template_version_id,
            :service_id, :purpose, :status, :bound_at
        )
        ON CONFLICT (binding_key) DO UPDATE SET
            prompt_template_version_id = excluded.prompt_template_version_id,
            service_id = excluded.service_id,
            purpose = excluded.purpose,
            status = excluded.status,
            bound_at = excluded.bound_at
    """


def _render_event_insert_sql(dialect_name: str) -> str:
    metadata = "CAST(:metadata AS jsonb)" if dialect_name == "postgresql" else ":metadata"
    return f"""
        INSERT INTO ae_prompt_render_events (
            prompt_render_event_id, prompt_binding_id,
            prompt_template_version_id, trace_id, request_id,
            rendered_prompt_hash, rendered_prompt_preview, user_prompt_hash,
            output_hash, metadata, created_at
        ) VALUES (
            :prompt_render_event_id, :prompt_binding_id,
            :prompt_template_version_id, :trace_id, :request_id,
            :rendered_prompt_hash, :rendered_prompt_preview, :user_prompt_hash,
            :output_hash, {metadata}, :created_at
        ) ON CONFLICT (prompt_render_event_id) DO NOTHING
    """


def _load_template_by_key(
    session: Session,
    *,
    service_id: str,
    purpose: str,
    name: str,
) -> dict[str, Any] | None:
    row = session.execute(
        text(
            """
            SELECT prompt_template_id, service_id, purpose, name, owner_domain,
                   status, created_at, updated_at
            FROM ae_prompt_templates
            WHERE service_id = :service_id AND purpose = :purpose AND name = :name
            """
        ),
        {"service_id": service_id, "purpose": purpose, "name": name},
    ).mappings().first()
    return None if row is None else _template_from_row(row)


def _load_template_version_by_key(
    session: Session,
    record: dict[str, Any],
) -> dict[str, Any] | None:
    row = session.execute(
        text(
            """
            SELECT prompt_template_version_id, prompt_template_id, version,
                   role, segment_order, content, content_sha256,
                   model_capability, metadata, status, created_at
            FROM ae_prompt_template_versions
            WHERE prompt_template_id = :prompt_template_id
              AND version = :version AND role = :role
              AND segment_order = :segment_order
            """
        ),
        record,
    ).mappings().first()
    return None if row is None else _version_from_row(row)


def _load_template_version(
    session: Session,
    version_id: str,
) -> dict[str, Any] | None:
    row = session.execute(
        text(
            """
            SELECT prompt_template_version_id, prompt_template_id, version,
                   role, segment_order, content, content_sha256,
                   model_capability, metadata, status, created_at
            FROM ae_prompt_template_versions
            WHERE prompt_template_version_id = :version_id
            """
        ),
        {"version_id": version_id},
    ).mappings().first()
    return None if row is None else _version_from_row(row)


def _load_binding(session: Session, binding_key: str) -> dict[str, Any] | None:
    row = session.execute(
        text(
            """
            SELECT prompt_binding_id, binding_key, prompt_template_version_id,
                   service_id, purpose, status, bound_at
            FROM ae_prompt_bindings
            WHERE binding_key = :binding_key
            """
        ),
        {"binding_key": binding_key},
    ).mappings().first()
    return None if row is None else _binding_from_row(row)


def _load_render_event(session: Session, event_id: str) -> dict[str, Any] | None:
    row = session.execute(
        text(
            """
            SELECT e.prompt_render_event_id, e.prompt_binding_id,
                   e.prompt_template_version_id, e.trace_id, e.request_id,
                   e.rendered_prompt_hash, e.rendered_prompt_preview,
                   e.user_prompt_hash, e.output_hash, e.metadata, e.created_at,
                   b.binding_key, b.service_id, b.purpose
            FROM ae_prompt_render_events e
            LEFT JOIN ae_prompt_bindings b
              ON b.prompt_binding_id = e.prompt_binding_id
            WHERE e.prompt_render_event_id = :event_id
            """
        ),
        {"event_id": event_id},
    ).mappings().first()
    return None if row is None else _render_event_from_row(row)


def _template_from_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    return {
        **data,
        "prompt_template_id": str(data["prompt_template_id"]),
        "created_at": _datetime_value(data["created_at"]),
        "updated_at": _datetime_value(data["updated_at"]),
    }


def _version_from_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    return {
        **data,
        "prompt_template_version_id": str(data["prompt_template_version_id"]),
        "prompt_template_id": str(data["prompt_template_id"]),
        "segment_order": int(data["segment_order"]),
        "metadata": _json_value(data["metadata"], {}),
        "summary_max_chars": None,
        "summary_hard_limit_chars": None,
        "created_at": _datetime_value(data["created_at"]),
    }


def _binding_from_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    return {
        **data,
        "prompt_binding_id": str(data["prompt_binding_id"]),
        "prompt_template_version_id": str(data["prompt_template_version_id"]),
        "bound_at": _datetime_value(data["bound_at"]),
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


def _required_saved(record: dict[str, Any] | None) -> dict[str, Any]:
    if record is None:
        raise PromptRepositoryError(
            "ae.prompt_registry_write_conflict",
            "Prompt registry write completed without a readable record.",
            True,
        )
    return record


def _json_value(value: Any, default: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return default if value is None else value


def _datetime_value(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat().replace("+00:00", "Z")
    return str(value)


def _dialect_name(session: Session) -> str:
    return session.get_bind().dialect.name


def _unavailable() -> PromptRepositoryError:
    return PromptRepositoryError(
        "ae.prompt_registry_unavailable",
        "AE prompt registry is unavailable.",
        True,
    )
