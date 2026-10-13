from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from nex_runtime.prompts import sha256_text
from nex_runtime.semantic_hashes import validate_sha256_digest
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
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._id_factory = id_factory or (lambda: str(uuid4()))
        self._clock = clock or (lambda: datetime.now(UTC))

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
        _validate_template_version(record)
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
                    text(_version_insert_sql(_dialect_name(session))),
                    params,
                )
                saved = _load_template_version_by_key(session, record)
                _require_matching_template_version(saved, record)
                session.commit()
                return saved
        except PromptRepositoryError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def save_binding(self, record: dict[str, Any]) -> dict[str, Any]:
        try:
            with self._session_factory() as session:
                session.execute(text(_binding_insert_sql()), record)
                saved = _load_binding(session, record["binding_key"])
                session.commit()
                return _required_saved(saved)
        except PromptRepositoryError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def activate_binding(
        self,
        *,
        binding_key: str,
        new_prompt_template_version_id: str,
        expected_prompt_template_version_id: str,
        changed_by: str,
        reason: str,
        correlation_id: str,
        binding_change_id: str | None = None,
        changed_at: str | None = None,
    ) -> dict[str, Any]:
        params = {
            "binding_change_id": _required_uuid(
                "binding_change_id", binding_change_id or self._id_factory()
            ),
            "binding_key": _required_text("binding_key", binding_key),
            "new_prompt_template_version_id": _required_uuid(
                "new_prompt_template_version_id",
                new_prompt_template_version_id,
            ),
            "expected_prompt_template_version_id": _required_uuid(
                "expected_prompt_template_version_id",
                expected_prompt_template_version_id,
            ),
            "changed_by": _required_text("changed_by", changed_by),
            "reason": _required_text("reason", reason),
            "correlation_id": _required_text("correlation_id", correlation_id),
            "changed_at": _required_text(
                "changed_at", changed_at or _utc_now(self._clock())
            ),
        }
        try:
            with self._session_factory() as session:
                current = _load_binding_for_update(session, binding_key)
                if current is None:
                    raise PromptRepositoryError(
                        "ae.prompt_binding_not_found",
                        "Prompt binding was not found.",
                    )
                current_version_id = current["prompt_template_version_id"]
                if current_version_id == new_prompt_template_version_id:
                    return {"changed": False, "binding": current, "history": None}
                if current_version_id != expected_prompt_template_version_id:
                    raise PromptRepositoryError(
                        "ae.prompt_binding_version_conflict",
                        "Prompt binding changed before activation.",
                        True,
                    )
                current_version = _load_template_version(session, current_version_id)
                target = _load_template_version(
                    session, new_prompt_template_version_id
                )
                if target is None or target["status"] != "ACTIVE":
                    raise PromptRepositoryError(
                        "ae.prompt_template_version_ineligible",
                        "Target prompt template version is not active.",
                    )
                if (
                    current_version is None
                    or current_version["prompt_template_id"]
                    != target["prompt_template_id"]
                ):
                    raise PromptRepositoryError(
                        "ae.prompt_binding_template_mismatch",
                        "Prompt binding cannot switch across prompt templates.",
                    )

                params["old_prompt_template_version_id"] = current_version_id
                session.execute(text(_binding_history_insert_sql()), params)
                updated = session.execute(text(_binding_pointer_cas_sql()), params)
                if int(updated.rowcount or 0) != 1:
                    raise PromptRepositoryError(
                        "ae.prompt_binding_version_conflict",
                        "Prompt binding changed before activation.",
                        True,
                    )
                saved = _required_saved(_load_binding(session, binding_key))
                history = _required_saved(
                    _load_binding_history(session, params["binding_change_id"])
                )
                session.commit()
                return {"changed": True, "binding": saved, "history": history}
        except PromptRepositoryError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def get_prompt_provenance(self, binding_key: str) -> dict[str, Any]:
        try:
            with self._session_factory() as session:
                binding = _load_binding(session, binding_key)
                if binding is None or binding["status"] != "ACTIVE":
                    raise PromptRepositoryError(
                        "ae.prompt_binding_not_found",
                        "Prompt binding was not found or is inactive.",
                    )
                version = _load_template_version(
                    session, binding["prompt_template_version_id"]
                )
                if version is None or version["status"] != "ACTIVE":
                    raise PromptRepositoryError(
                        "ae.prompt_template_version_ineligible",
                        "Bound prompt template version is not active.",
                    )
                return {
                    "prompt_binding_key": binding["binding_key"],
                    "prompt_template_version_id": version[
                        "prompt_template_version_id"
                    ],
                    "prompt_content_sha256": version["content_sha256"],
                }
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


def _version_insert_sql(dialect_name: str) -> str:
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
        ON CONFLICT DO NOTHING
    """


def _binding_insert_sql() -> str:
    return """
        INSERT INTO ae_prompt_bindings (
            prompt_binding_id, binding_key, prompt_template_version_id,
            service_id, purpose, status, bound_at
        ) VALUES (
            :prompt_binding_id, :binding_key, :prompt_template_version_id,
            :service_id, :purpose, :status, :bound_at
        )
        ON CONFLICT DO NOTHING
    """


def _binding_history_insert_sql() -> str:
    return """
        INSERT INTO ae_prompt_binding_history (
            binding_change_id, binding_key,
            old_prompt_template_version_id, new_prompt_template_version_id,
            changed_by, reason, correlation_id, changed_at
        ) VALUES (
            :binding_change_id, :binding_key,
            :old_prompt_template_version_id, :new_prompt_template_version_id,
            :changed_by, :reason, :correlation_id, :changed_at
        )
    """


def _binding_pointer_cas_sql() -> str:
    return """
        UPDATE ae_prompt_bindings
        SET prompt_template_version_id = :new_prompt_template_version_id,
            bound_at = :changed_at
        WHERE binding_key = :binding_key
          AND prompt_template_version_id = :expected_prompt_template_version_id
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


def _load_binding_for_update(
    session: Session, binding_key: str
) -> dict[str, Any] | None:
    suffix = " FOR UPDATE" if _dialect_name(session) == "postgresql" else ""
    row = session.execute(
        text(
            """
            SELECT prompt_binding_id, binding_key, prompt_template_version_id,
                   service_id, purpose, status, bound_at
            FROM ae_prompt_bindings
            WHERE binding_key = :binding_key
            """
            + suffix
        ),
        {"binding_key": binding_key},
    ).mappings().first()
    return None if row is None else _binding_from_row(row)


def _load_binding_history(session: Session, change_id: str) -> dict[str, Any] | None:
    row = session.execute(
        text(
            """
            SELECT binding_change_id, binding_key,
                   old_prompt_template_version_id,
                   new_prompt_template_version_id,
                   changed_by, reason, correlation_id, changed_at
            FROM ae_prompt_binding_history
            WHERE binding_change_id = :change_id
            """
        ),
        {"change_id": change_id},
    ).mappings().first()
    if row is None:
        return None
    data = dict(row)
    return {
        **data,
        "binding_change_id": str(data["binding_change_id"]),
        "old_prompt_template_version_id": str(
            data["old_prompt_template_version_id"]
        ),
        "new_prompt_template_version_id": str(
            data["new_prompt_template_version_id"]
        ),
        "changed_at": _datetime_value(data["changed_at"]),
    }


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


def _require_matching_template_version(
    saved: dict[str, Any] | None,
    requested: dict[str, Any],
) -> None:
    if saved is None:
        raise PromptRepositoryError(
            "ae.prompt_template_version_write_conflict",
            "Prompt template version could not be reloaded after insertion.",
            True,
        )
    immutable_fields = (
        "prompt_template_id",
        "version",
        "role",
        "segment_order",
        "content",
        "content_sha256",
        "model_capability",
        "metadata",
        "status",
    )
    if any(saved[field] != requested[field] for field in immutable_fields):
        raise PromptRepositoryError(
            "ae.prompt_template_version_immutable_conflict",
            "Prompt template version already exists with different content.",
        )


def _validate_template_version(record: dict[str, Any]) -> None:
    try:
        digest = validate_sha256_digest(record.get("content_sha256"))
    except ValueError as exc:
        raise PromptRepositoryError(
            "ae.prompt_template_version_invalid",
            "Prompt template version content_sha256 is invalid.",
        ) from exc
    if not isinstance(record.get("content"), str) or sha256_text(record["content"]) != digest:
        raise PromptRepositoryError(
            "ae.prompt_template_version_invalid",
            "Prompt template version content does not match content_sha256.",
        )


def _required_text(field: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PromptRepositoryError(
            "ae.prompt_binding_change_invalid",
            f"{field} must be a non-empty string.",
        )
    return value.strip()


def _required_uuid(field: str, value: Any) -> str:
    value = _required_text(field, value)
    try:
        UUID(value)
    except ValueError as exc:
        raise PromptRepositoryError(
            "ae.prompt_binding_change_invalid",
            f"{field} must be a UUID string.",
        ) from exc
    return value


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


def _utc_now(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _unavailable() -> PromptRepositoryError:
    return PromptRepositoryError(
        "ae.prompt_registry_unavailable",
        "AE prompt registry is unavailable.",
        True,
    )
