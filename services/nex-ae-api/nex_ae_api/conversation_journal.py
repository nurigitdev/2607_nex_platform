from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from nex_runtime.object_storage import (
    ObjectStorageError,
    S3ObjectStore,
    build_owner_object_key,
)
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_ae_api.private_object_store import (
    AePrivateObjectStorageError,
    ae_private_storage_mode,
    build_ae_private_object_store,
)

CONVERSATION_STORAGE_ENV = "NEX_AE_CONVERSATION_STORAGE_ROOT"
CONVERSATION_STORAGE_SCHEME = "ae://conversation-journal/"
MAX_CONVERSATION_CONTENT_BYTES = 16 * 1024 * 1024
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PRIVATE_EVENT_KEYS = frozenset(
    {"content", "prompt", "response", "raw_content", "message_text"}
)


@dataclass(frozen=True)
class ConversationJournalError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class ConversationContentStorage(Protocol):
    def save(
        self,
        payload: Mapping[str, Any],
        *,
        tenant_id: str,
        owner_user_id: str,
    ) -> str:
        ...

    def load(
        self,
        metadata: Mapping[str, Any],
        *,
        tenant_id: str,
        owner_user_id: str,
    ) -> str | None:
        ...

    def delete(
        self,
        metadata: Mapping[str, Any],
        *,
        tenant_id: str,
        owner_user_id: str,
    ) -> bool:
        ...


def build_conversation_content_payload(
    *,
    entry_id: str,
    content: str,
    content_type: str = "text/plain; charset=utf-8",
) -> dict[str, Any]:
    normalized_id = _required_safe_id(entry_id)
    if not isinstance(content, str):
        raise _invalid("Conversation content must be a string.")
    if not isinstance(content_type, str) or not content_type.strip().startswith("text/"):
        raise _invalid("Conversation content type must be textual.")
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_CONVERSATION_CONTENT_BYTES:
        raise _invalid("Conversation content exceeds its storage boundary.")
    digest = hashlib.sha256(encoded).hexdigest()
    return {
        "entry_id": normalized_id,
        "content_type": content_type.strip(),
        "content": content,
        "content_sha256": digest,
        "size_bytes": len(encoded),
        "storage_ref": (
            f"{CONVERSATION_STORAGE_SCHEME}{digest[:2]}/{digest[2:4]}/"
            f"{normalized_id}.txt"
        ),
    }


def conversation_content_metadata(payload: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _validate_content_payload(payload, require_content=True)
    return {key: value for key, value in normalized.items() if key != "content"}


@dataclass
class InMemoryConversationContentStorage:
    payloads: dict[tuple[str, str, str], bytes] = field(default_factory=dict)

    def save(
        self,
        payload: Mapping[str, Any],
        *,
        tenant_id: str,
        owner_user_id: str,
    ) -> str:
        normalized = _validate_content_payload(payload, require_content=True)
        key = _owner_key(tenant_id, owner_user_id, normalized["storage_ref"])
        self.payloads[key] = str(normalized["content"]).encode("utf-8")
        return str(normalized["storage_ref"])

    def load(
        self,
        metadata: Mapping[str, Any],
        *,
        tenant_id: str,
        owner_user_id: str,
    ) -> str | None:
        normalized = _validate_content_payload(metadata, require_content=False)
        payload = self.payloads.get(
            _owner_key(tenant_id, owner_user_id, normalized["storage_ref"])
        )
        return None if payload is None else _decode_and_verify(payload, normalized)

    def delete(
        self,
        metadata: Mapping[str, Any],
        *,
        tenant_id: str,
        owner_user_id: str,
    ) -> bool:
        normalized = _validate_content_payload(metadata, require_content=False)
        key = _owner_key(tenant_id, owner_user_id, normalized["storage_ref"])
        return self.payloads.pop(key, None) is not None


@dataclass(frozen=True)
class LocalConversationContentStorage:
    root: Path

    def save(
        self,
        payload: Mapping[str, Any],
        *,
        tenant_id: str,
        owner_user_id: str,
    ) -> str:
        normalized = _validate_content_payload(payload, require_content=True)
        path = self._path(tenant_id, owner_user_id, normalized["storage_ref"])
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary.write(str(normalized["content"]).encode("utf-8"))
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            temporary_path.chmod(0o600)
            os.replace(temporary_path, path)
            path.chmod(0o600)
        except OSError as exc:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise _unavailable() from exc
        return str(normalized["storage_ref"])

    def load(
        self,
        metadata: Mapping[str, Any],
        *,
        tenant_id: str,
        owner_user_id: str,
    ) -> str | None:
        normalized = _validate_content_payload(metadata, require_content=False)
        path = self._path(tenant_id, owner_user_id, normalized["storage_ref"])
        if not path.exists():
            return None
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise _unavailable() from exc
        return _decode_and_verify(payload, normalized)

    def delete(
        self,
        metadata: Mapping[str, Any],
        *,
        tenant_id: str,
        owner_user_id: str,
    ) -> bool:
        normalized = _validate_content_payload(metadata, require_content=False)
        path = self._path(tenant_id, owner_user_id, normalized["storage_ref"])
        if not path.exists():
            return False
        try:
            path.unlink()
        except OSError as exc:
            raise _unavailable() from exc
        return True

    def _path(self, tenant_id: str, owner_user_id: str, storage_ref: object) -> Path:
        owner_hash = hashlib.sha256(
            f"{_required_owner(tenant_id)}\0{_required_owner(owner_user_id)}".encode()
        ).hexdigest()
        relative = _storage_ref_relative_path(storage_ref)
        root = self.root.resolve()
        path = root.joinpath(owner_hash[:2], owner_hash, *relative.split("/")).resolve(
            strict=False
        )
        if not path.is_relative_to(root):
            raise _invalid("Conversation storage reference escapes its root.")
        return path


@dataclass(frozen=True)
class S3ConversationContentStorage:
    object_store: S3ObjectStore

    def save(
        self,
        payload: Mapping[str, Any],
        *,
        tenant_id: str,
        owner_user_id: str,
    ) -> str:
        normalized = _validate_content_payload(payload, require_content=True)
        encoded = str(normalized["content"]).encode("utf-8")
        try:
            self.object_store.put_immutable(
                key=self._key(tenant_id, owner_user_id, normalized["entry_id"]),
                payload=encoded,
                expected_sha256=str(normalized["content_sha256"]),
                content_type=str(normalized["content_type"]),
            )
        except ObjectStorageError as exc:
            raise _object_storage_error(exc) from exc
        return str(normalized["storage_ref"])

    def load(
        self,
        metadata: Mapping[str, Any],
        *,
        tenant_id: str,
        owner_user_id: str,
    ) -> str | None:
        normalized = _validate_content_payload(metadata, require_content=False)
        try:
            payload = self.object_store.get_bytes(
                key=self._key(tenant_id, owner_user_id, normalized["entry_id"]),
                expected_sha256=str(normalized["content_sha256"]),
                expected_size_bytes=int(normalized["size_bytes"]),
                max_size_bytes=MAX_CONVERSATION_CONTENT_BYTES,
            )
        except ObjectStorageError as exc:
            raise _object_storage_error(exc) from exc
        return None if payload is None else _decode_and_verify(payload, normalized)

    def delete(
        self,
        metadata: Mapping[str, Any],
        *,
        tenant_id: str,
        owner_user_id: str,
    ) -> bool:
        normalized = _validate_content_payload(metadata, require_content=False)
        key = self._key(tenant_id, owner_user_id, normalized["entry_id"])
        try:
            if self.object_store.head(key) is None:
                return False
            self.object_store.delete(key)
        except ObjectStorageError as exc:
            raise _object_storage_error(exc) from exc
        return True

    @staticmethod
    def _key(tenant_id: str, owner_user_id: str, entry_id: object) -> str:
        try:
            return build_owner_object_key(
                payload_family="conversation-journal",
                tenant_id=_required_owner(tenant_id),
                subject_id=_required_owner(owner_user_id),
                content_id=_required_safe_id(entry_id),
                suffix="txt",
            )
        except ObjectStorageError as exc:
            raise _object_storage_error(exc) from exc


def build_default_conversation_content_storage(
    environ: Mapping[str, str] | None = None,
) -> ConversationContentStorage:
    env = os.environ if environ is None else environ
    try:
        mode = ae_private_storage_mode(env)
        if mode == "S3":
            return S3ConversationContentStorage(build_ae_private_object_store(env))
    except AePrivateObjectStorageError as exc:
        raise ConversationJournalError(
            exc.error_code,
            exc.detail,
            exc.retryable,
        ) from exc
    root = env.get(CONVERSATION_STORAGE_ENV)
    if mode == "FILESYSTEM" and (not isinstance(root, str) or not root.strip()):
        raise _invalid("AE Conversation journal filesystem root is required.")
    if not isinstance(root, str) or not root.strip():
        return InMemoryConversationContentStorage()
    return LocalConversationContentStorage(Path(root.strip()))


class SqlAlchemyConversationJournal:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        content_storage: ConversationContentStorage,
    ) -> None:
        self._session_factory = session_factory
        self._content_storage = content_storage

    def create_conversation(self, record: Mapping[str, Any]) -> dict[str, Any]:
        params = _conversation_params(record)
        try:
            with self._session_factory() as session:
                workspace = session.execute(
                    text(
                        """
                        SELECT tenant_id, owner_user_id FROM ae_workspaces
                        WHERE workspace_id = :workspace_id
                        """
                    ),
                    params,
                ).mappings().first()
                if workspace is None or (
                    workspace["tenant_id"], workspace["owner_user_id"]
                ) != (params["tenant_id"], params["owner_user_id"]):
                    raise _forbidden("Workspace ownership does not admit Conversation creation.")
                inserted = session.execute(text(_CONVERSATION_INSERT_SQL), params)
                saved = _load_conversation(session, params["conversation_id"])
                if saved is None:
                    raise _write_conflict()
                if int(inserted.rowcount or 0) == 0 and _conversation_owner(saved) != (
                    params["tenant_id"], params["owner_user_id"], params["workspace_id"]
                ):
                    raise _forbidden("Conversation identifier belongs to another scope.")
                session.commit()
                return saved
        except ConversationJournalError:
            raise
        except SQLAlchemyError as exc:
            raise _repository_unavailable() from exc

    def list_conversations(
        self,
        *,
        tenant_id: str,
        owner_user_id: str,
        workspace_id: str,
    ) -> list[dict[str, Any]]:
        try:
            with self._session_factory() as session:
                rows = session.execute(
                    text(
                        """
                        SELECT conversation_id, tenant_id, workspace_id,
                               owner_user_id, title, status, next_journal_seq,
                               created_at, updated_at, version
                        FROM ae_conversations
                        WHERE tenant_id = :tenant_id
                          AND owner_user_id = :owner_user_id
                          AND workspace_id = :workspace_id
                        ORDER BY updated_at DESC, conversation_id ASC
                        """
                    ),
                    {
                        "tenant_id": _required_owner(tenant_id),
                        "owner_user_id": _required_owner(owner_user_id),
                        "workspace_id": _required_safe_id(workspace_id),
                    },
                ).mappings().all()
                return [_conversation_from_row(row) for row in rows]
        except ConversationJournalError:
            raise
        except SQLAlchemyError as exc:
            raise _repository_unavailable() from exc

    def append_message(
        self,
        record: Mapping[str, Any],
        *,
        content: str,
    ) -> dict[str, Any]:
        payload = build_conversation_content_payload(
            entry_id=str(record.get("message_id") or ""),
            content=content,
            content_type=str(record.get("content_type") or "text/plain; charset=utf-8"),
        )
        metadata = conversation_content_metadata(payload)
        params = _message_params(record, metadata)
        saved_ref = self._content_storage.save(
            payload,
            tenant_id=params["tenant_id"],
            owner_user_id=params["owner_user_id"],
        )
        if saved_ref != metadata["storage_ref"]:
            self._content_storage.delete(
                metadata,
                tenant_id=params["tenant_id"],
                owner_user_id=params["owner_user_id"],
            )
            raise _invalid("Conversation storage returned an inconsistent reference.")
        try:
            with self._session_factory() as session:
                existing = _load_message(session, params["message_id"])
                if existing is not None:
                    return _require_same_message(existing, params)
                params["journal_seq"] = _allocate_sequence(session, params)
                session.execute(text(_message_insert_sql()), params)
                saved = _load_message(session, params["message_id"])
                if saved is None:
                    raise _write_conflict()
                session.commit()
                return saved
        except ConversationJournalError:
            self._delete_uncommitted_content(metadata, params)
            raise
        except SQLAlchemyError as exc:
            self._delete_uncommitted_content(metadata, params)
            raise _repository_unavailable() from exc

    def append_event(self, record: Mapping[str, Any]) -> dict[str, Any]:
        params = _event_params(record)
        try:
            with self._session_factory() as session:
                existing = _load_event(session, params["event_id"])
                if existing is not None:
                    return _require_same_event(existing, params)
                params["journal_seq"] = _allocate_sequence(session, params)
                session.execute(text(_event_insert_sql(_dialect_name(session))), params)
                saved = _load_event(session, params["event_id"])
                if saved is None:
                    raise _write_conflict()
                session.commit()
                return saved
        except ConversationJournalError:
            raise
        except SQLAlchemyError as exc:
            raise _repository_unavailable() from exc

    def list_entries(
        self,
        *,
        tenant_id: str,
        owner_user_id: str,
        conversation_id: str,
    ) -> list[dict[str, Any]]:
        scope = {
            "tenant_id": _required_owner(tenant_id),
            "owner_user_id": _required_owner(owner_user_id),
            "conversation_id": _required_safe_id(conversation_id),
        }
        try:
            with self._session_factory() as session:
                if _owned_conversation(session, scope) is None:
                    return []
                messages = session.execute(text(_LIST_MESSAGES_SQL), scope).mappings().all()
                events = session.execute(text(_LIST_EVENTS_SQL), scope).mappings().all()
                entries = [_message_from_row(row) for row in messages]
                entries.extend(_event_from_row(row) for row in events)
                return sorted(entries, key=lambda item: int(item["journal_seq"]))
        except ConversationJournalError:
            raise
        except SQLAlchemyError as exc:
            raise _repository_unavailable() from exc

    def load_message_content(
        self,
        *,
        tenant_id: str,
        owner_user_id: str,
        message_id: str,
    ) -> str | None:
        try:
            with self._session_factory() as session:
                message = _load_message(session, _required_safe_id(message_id))
                if message is None or (
                    message["tenant_id"], message["owner_user_id"]
                ) != (_required_owner(tenant_id), _required_owner(owner_user_id)):
                    return None
        except ConversationJournalError:
            raise
        except SQLAlchemyError as exc:
            raise _repository_unavailable() from exc
        return self._content_storage.load(
            _content_metadata_from_message(message),
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
        )

    def _delete_uncommitted_content(
        self,
        metadata: Mapping[str, Any],
        params: Mapping[str, Any],
    ) -> None:
        self._content_storage.delete(
            metadata,
            tenant_id=str(params["tenant_id"]),
            owner_user_id=str(params["owner_user_id"]),
        )


_CONVERSATION_INSERT_SQL = """
    INSERT INTO ae_conversations (
        conversation_id, tenant_id, workspace_id, owner_user_id,
        title, status, next_journal_seq, created_at, updated_at, version
    ) VALUES (
        :conversation_id, :tenant_id, :workspace_id, :owner_user_id,
        :title, :status, 1, :created_at, :updated_at, 1
    ) ON CONFLICT (conversation_id) DO NOTHING
"""

_LIST_MESSAGES_SQL = """
    SELECT m.*, c.owner_user_id
    FROM ae_conversation_messages AS m
    JOIN ae_conversations AS c ON c.conversation_id = m.conversation_id
    WHERE m.tenant_id = :tenant_id AND c.owner_user_id = :owner_user_id
      AND m.conversation_id = :conversation_id
"""

_LIST_EVENTS_SQL = """
    SELECT e.*, c.owner_user_id
    FROM ae_conversation_events AS e
    JOIN ae_conversations AS c ON c.conversation_id = e.conversation_id
    WHERE e.tenant_id = :tenant_id AND c.owner_user_id = :owner_user_id
      AND e.conversation_id = :conversation_id
"""


def _message_insert_sql() -> str:
    return """
        INSERT INTO ae_conversation_messages (
            message_id, tenant_id, conversation_id, journal_seq, role,
            content_ref, content_sha256, size_bytes, content_type,
            legacy_interaction_id, supersedes_message_id, correlation_id,
            causation_id, created_at
        ) VALUES (
            :message_id, :tenant_id, :conversation_id, :journal_seq, :role,
            :storage_ref, :content_sha256, :size_bytes, :content_type,
            :legacy_interaction_id, :supersedes_message_id, :correlation_id,
            :causation_id, :created_at
        )
    """


def _event_insert_sql(dialect_name: str) -> str:
    event_data = "CAST(:event_data AS jsonb)" if dialect_name == "postgresql" else ":event_data"
    return f"""
        INSERT INTO ae_conversation_events (
            event_id, tenant_id, conversation_id, journal_seq, event_type,
            event_data, supersedes_event_id, correlation_id, causation_id,
            created_at
        ) VALUES (
            :event_id, :tenant_id, :conversation_id, :journal_seq, :event_type,
            {event_data}, :supersedes_event_id, :correlation_id, :causation_id,
            :created_at
        )
    """


def _allocate_sequence(session: Session, params: Mapping[str, Any]) -> int:
    row = session.execute(
        text(
            """
            UPDATE ae_conversations
            SET next_journal_seq = next_journal_seq + 1,
                updated_at = :created_at,
                version = version + 1
            WHERE tenant_id = :tenant_id
              AND owner_user_id = :owner_user_id
              AND conversation_id = :conversation_id
              AND status = 'ACTIVE'
            RETURNING next_journal_seq - 1 AS journal_seq
            """
        ),
        params,
    ).mappings().first()
    if row is None:
        raise _forbidden("Active owner-scoped Conversation was not found.")
    return int(row["journal_seq"])


def _load_conversation(session: Session, conversation_id: str) -> dict[str, Any] | None:
    row = session.execute(
        text(
            """
            SELECT conversation_id, tenant_id, workspace_id, owner_user_id,
                   title, status, next_journal_seq, created_at, updated_at, version
            FROM ae_conversations WHERE conversation_id = :conversation_id
            """
        ),
        {"conversation_id": conversation_id},
    ).mappings().first()
    return None if row is None else _conversation_from_row(row)


def _owned_conversation(session: Session, scope: Mapping[str, Any]) -> Any:
    return session.execute(
        text(
            """
            SELECT conversation_id FROM ae_conversations
            WHERE tenant_id = :tenant_id AND owner_user_id = :owner_user_id
              AND conversation_id = :conversation_id
            """
        ),
        scope,
    ).first()


def _load_message(session: Session, message_id: str) -> dict[str, Any] | None:
    row = session.execute(
        text(
            """
            SELECT m.*, c.owner_user_id
            FROM ae_conversation_messages AS m
            JOIN ae_conversations AS c ON c.conversation_id = m.conversation_id
            WHERE m.message_id = :message_id
            """
        ),
        {"message_id": message_id},
    ).mappings().first()
    return None if row is None else _message_from_row(row)


def _load_event(session: Session, event_id: str) -> dict[str, Any] | None:
    row = session.execute(
        text(
            """
            SELECT e.*, c.owner_user_id
            FROM ae_conversation_events AS e
            JOIN ae_conversations AS c ON c.conversation_id = e.conversation_id
            WHERE e.event_id = :event_id
            """
        ),
        {"event_id": event_id},
    ).mappings().first()
    return None if row is None else _event_from_row(row)


def _conversation_params(record: Mapping[str, Any]) -> dict[str, Any]:
    title = record.get("title")
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 120:
        raise _invalid("Conversation title is invalid.")
    status = record.get("status", "ACTIVE")
    if status not in {"ACTIVE", "ARCHIVED"}:
        raise _invalid("Conversation status is invalid.")
    return {
        "conversation_id": _required_safe_id(record.get("conversation_id")),
        "tenant_id": _required_owner(record.get("tenant_id")),
        "workspace_id": _required_safe_id(record.get("workspace_id")),
        "owner_user_id": _required_owner(record.get("owner_user_id")),
        "title": title.strip(),
        "status": status,
        "created_at": _required_text("created_at", record.get("created_at")),
        "updated_at": _required_text("updated_at", record.get("updated_at")),
    }


def _message_params(
    record: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    role = record.get("role")
    if role not in {"USER", "ASSISTANT", "SYSTEM", "TOOL"}:
        raise _invalid("Conversation message role is invalid.")
    return {
        **metadata,
        "message_id": _required_safe_id(record.get("message_id")),
        "tenant_id": _required_owner(record.get("tenant_id")),
        "owner_user_id": _required_owner(record.get("owner_user_id")),
        "conversation_id": _required_safe_id(record.get("conversation_id")),
        "role": role,
        "legacy_interaction_id": _optional_safe_id(record.get("legacy_interaction_id")),
        "supersedes_message_id": _optional_safe_id(record.get("supersedes_message_id")),
        "correlation_id": _required_text("correlation_id", record.get("correlation_id")),
        "causation_id": _optional_text(record.get("causation_id")),
        "created_at": _required_text("created_at", record.get("created_at")),
    }


def _event_params(record: Mapping[str, Any]) -> dict[str, Any]:
    event_data = record.get("event_data") or {}
    if not isinstance(event_data, Mapping) or _contains_private_key(event_data):
        raise _invalid("Conversation event data contains private content.")
    return {
        "event_id": _required_safe_id(record.get("event_id")),
        "tenant_id": _required_owner(record.get("tenant_id")),
        "owner_user_id": _required_owner(record.get("owner_user_id")),
        "conversation_id": _required_safe_id(record.get("conversation_id")),
        "event_type": _required_text("event_type", record.get("event_type")),
        "event_data": json.dumps(event_data, ensure_ascii=False, sort_keys=True),
        "supersedes_event_id": _optional_safe_id(record.get("supersedes_event_id")),
        "correlation_id": _required_text("correlation_id", record.get("correlation_id")),
        "causation_id": _optional_text(record.get("causation_id")),
        "created_at": _required_text("created_at", record.get("created_at")),
    }


def _conversation_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "conversation_id": str(row["conversation_id"]),
        "tenant_id": row["tenant_id"],
        "workspace_id": str(row["workspace_id"]),
        "owner_user_id": row["owner_user_id"],
        "title": row["title"],
        "status": row["status"],
        "next_journal_seq": int(row["next_journal_seq"]),
        "created_at": _datetime_value(row["created_at"]),
        "updated_at": _datetime_value(row["updated_at"]),
        "version": int(row["version"]),
    }


def _message_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "entry_kind": "MESSAGE",
        "message_id": str(row["message_id"]),
        "tenant_id": row["tenant_id"],
        "owner_user_id": row["owner_user_id"],
        "conversation_id": str(row["conversation_id"]),
        "journal_seq": int(row["journal_seq"]),
        "role": row["role"],
        "content_ref": row["content_ref"],
        "content_sha256": row["content_sha256"],
        "size_bytes": int(row["size_bytes"]),
        "content_type": row["content_type"],
        "legacy_interaction_id": _string_or_none(row["legacy_interaction_id"]),
        "supersedes_message_id": _string_or_none(row["supersedes_message_id"]),
        "correlation_id": row["correlation_id"],
        "causation_id": row["causation_id"],
        "created_at": _datetime_value(row["created_at"]),
    }


def _event_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    event_data = row["event_data"]
    return {
        "entry_kind": "EVENT",
        "event_id": str(row["event_id"]),
        "tenant_id": row["tenant_id"],
        "owner_user_id": row["owner_user_id"],
        "conversation_id": str(row["conversation_id"]),
        "journal_seq": int(row["journal_seq"]),
        "event_type": row["event_type"],
        "event_data": json.loads(event_data) if isinstance(event_data, str) else event_data,
        "supersedes_event_id": _string_or_none(row["supersedes_event_id"]),
        "correlation_id": row["correlation_id"],
        "causation_id": row["causation_id"],
        "created_at": _datetime_value(row["created_at"]),
    }


def _require_same_message(
    existing: dict[str, Any],
    params: Mapping[str, Any],
) -> dict[str, Any]:
    expected = (
        params["tenant_id"],
        params["owner_user_id"],
        params["conversation_id"],
        params["content_sha256"],
    )
    actual = (
        existing["tenant_id"],
        existing["owner_user_id"],
        existing["conversation_id"],
        existing["content_sha256"],
    )
    if actual != expected:
        raise _write_conflict()
    return existing


def _require_same_event(
    existing: dict[str, Any],
    params: Mapping[str, Any],
) -> dict[str, Any]:
    event_data = json.loads(str(params["event_data"]))
    if (
        existing["tenant_id"],
        existing["owner_user_id"],
        existing["conversation_id"],
        existing["event_type"],
        existing["event_data"],
    ) != (
        params["tenant_id"],
        params["owner_user_id"],
        params["conversation_id"],
        params["event_type"],
        event_data,
    ):
        raise _write_conflict()
    return existing


def _content_metadata_from_message(message: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "entry_id": message["message_id"],
        "content_type": message["content_type"],
        "content_sha256": message["content_sha256"],
        "size_bytes": message["size_bytes"],
        "storage_ref": message["content_ref"],
    }


def _validate_content_payload(
    value: Mapping[str, Any],
    *,
    require_content: bool,
) -> dict[str, Any]:
    expected = {
        "entry_id",
        "content_type",
        "content_sha256",
        "size_bytes",
        "storage_ref",
    }
    if require_content:
        expected.add("content")
    if set(value) != expected:
        raise _invalid("Conversation content payload shape is invalid.")
    entry_id = _required_safe_id(value.get("entry_id"))
    digest = value.get("content_sha256")
    size = value.get("size_bytes")
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        raise _invalid("Conversation content hash is invalid.")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise _invalid("Conversation content size is invalid.")
    expected_ref = (
        f"{CONVERSATION_STORAGE_SCHEME}{digest[:2]}/{digest[2:4]}/{entry_id}.txt"
    )
    if value.get("storage_ref") != expected_ref:
        raise _invalid("Conversation content reference is inconsistent.")
    normalized = dict(value)
    if require_content:
        content = value.get("content")
        if not isinstance(content, str):
            raise _invalid("Conversation content must be a string.")
        _verify_content(content.encode("utf-8"), digest, size)
    return normalized


def _decode_and_verify(payload: bytes, metadata: Mapping[str, Any]) -> str:
    try:
        content = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _integrity_error() from exc
    _verify_content(payload, str(metadata["content_sha256"]), int(metadata["size_bytes"]))
    return content


def _verify_content(payload: bytes, digest: str, size: int) -> None:
    if len(payload) != size or hashlib.sha256(payload).hexdigest() != digest:
        raise _integrity_error()


def _storage_ref_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value.startswith(CONVERSATION_STORAGE_SCHEME):
        raise _invalid("Conversation storage reference is invalid.")
    relative = value.removeprefix(CONVERSATION_STORAGE_SCHEME)
    parts = relative.split("/")
    if (
        len(parts) != 3
        or any(part in {"", ".", ".."} for part in parts)
        or any(_SAFE_ID.fullmatch(part) is None for part in parts)
        or not parts[-1].endswith(".txt")
    ):
        raise _invalid("Conversation storage reference is invalid.")
    return relative


def _owner_key(tenant_id: str, owner_user_id: str, storage_ref: object) -> tuple[str, str, str]:
    return (
        _required_owner(tenant_id),
        _required_owner(owner_user_id),
        _storage_ref_relative_path(storage_ref),
    )


def _contains_private_key(value: Mapping[str, Any]) -> bool:
    for key, item in value.items():
        if str(key).lower() in _PRIVATE_EVENT_KEYS:
            return True
        if isinstance(item, Mapping) and _contains_private_key(item):
            return True
        if isinstance(item, list) and any(
            isinstance(nested, Mapping) and _contains_private_key(nested)
            for nested in item
        ):
            return True
    return False


def _conversation_owner(record: Mapping[str, Any]) -> tuple[str, str, str]:
    return record["tenant_id"], record["owner_user_id"], record["workspace_id"]


def _required_safe_id(value: object) -> str:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value.strip()) is None:
        raise _invalid("Conversation identifier is invalid.")
    return value.strip()


def _optional_safe_id(value: object) -> str | None:
    return None if value is None else _required_safe_id(value)


def _required_owner(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 255:
        raise _invalid("Conversation owner scope is invalid.")
    return value.strip()


def _required_text(field: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"Conversation {field} is invalid.")
    return value.strip()


def _optional_text(value: object) -> str | None:
    return None if value is None else _required_text("lineage", value)


def _datetime_value(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat().replace("+00:00", "Z")
    return str(value)


def _string_or_none(value: Any) -> str | None:
    return None if value is None else str(value)


def _dialect_name(session: Session) -> str:
    return session.get_bind().dialect.name


def _invalid(detail: str) -> ConversationJournalError:
    return ConversationJournalError("ae.conversation_journal_invalid", detail)


def _forbidden(detail: str) -> ConversationJournalError:
    return ConversationJournalError("ae.conversation_scope_forbidden", detail)


def _write_conflict() -> ConversationJournalError:
    return ConversationJournalError(
        "ae.conversation_journal_write_conflict",
        "Conversation journal write conflicted with an existing identity.",
    )


def _repository_unavailable() -> ConversationJournalError:
    return ConversationJournalError(
        "ae.conversation_journal_store_unavailable",
        "AE Conversation journal store is unavailable.",
        True,
    )


def _object_storage_error(exc: ObjectStorageError) -> ConversationJournalError:
    if exc.retryable:
        return _unavailable()
    if exc.code in {
        "OBJECT_STORAGE_IMMUTABLE_CONFLICT",
        "OBJECT_STORAGE_INTEGRITY_MISMATCH",
        "OBJECT_STORAGE_METADATA_INVALID",
        "OBJECT_STORAGE_SIZE_MISMATCH",
    }:
        return _integrity_error()
    return _invalid("AE Conversation object-storage operation failed.")


def _unavailable() -> ConversationJournalError:
    return ConversationJournalError(
        "ae.conversation_content_store_unavailable",
        "AE Conversation content storage is unavailable.",
        True,
    )


def _integrity_error() -> ConversationJournalError:
    return ConversationJournalError(
        "ae.conversation_content_integrity_failed",
        "AE Conversation content integrity verification failed.",
    )
