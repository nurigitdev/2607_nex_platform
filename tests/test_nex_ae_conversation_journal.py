from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import nex_ae_api.conversation_journal as journal_module
import pytest
from nex_ae_api.conversation_journal import (
    ConversationJournalError,
    InMemoryConversationContentStorage,
    LocalConversationContentStorage,
    S3ConversationContentStorage,
    SqlAlchemyConversationJournal,
    build_conversation_content_payload,
    build_default_conversation_content_storage,
    conversation_content_metadata,
)
from nex_ae_api.private_object_store import AePrivateObjectStorageError
from nex_runtime.object_storage import ObjectStorageError
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / (
    "database/nex-ae-api/migrations/2002_ae_conversation_journal.sql"
)
WORKSPACE_ID = "11111111-1111-4111-8111-111111111111"
CONVERSATION_A = "22222222-2222-4222-8222-222222222222"
CONVERSATION_B = "33333333-3333-4333-8333-333333333333"
MESSAGE_A = "44444444-4444-4444-8444-444444444444"
MESSAGE_B = "55555555-5555-4555-8555-555555555555"
EVENT_A = "66666666-6666-4666-8666-666666666666"
NOW = "2026-10-13T02:00:00Z"


def _session_factory(*, with_schema: bool = True):
    engine = create_engine("sqlite+pysqlite://", future=True)
    if with_schema:
        with engine.begin() as connection:
            connection.execute(text("PRAGMA foreign_keys = ON"))
            connection.execute(text("""
                CREATE TABLE ae_workspaces (
                    workspace_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL
                )
            """))
            connection.execute(
                text("INSERT INTO ae_workspaces VALUES (:id, 'tenant-a', 'user-a')"),
                {"id": WORKSPACE_ID},
            )
            connection.execute(text("""
                CREATE TABLE ae_conversations (
                    conversation_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    next_journal_seq INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    UNIQUE (tenant_id, conversation_id)
                )
            """))
            connection.execute(text("""
                CREATE TABLE ae_conversation_messages (
                    message_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    journal_seq INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content_ref TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    content_type TEXT NOT NULL,
                    legacy_interaction_id TEXT,
                    supersedes_message_id TEXT,
                    correlation_id TEXT NOT NULL,
                    causation_id TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE (conversation_id, journal_seq)
                )
            """))
            connection.execute(text("""
                CREATE TABLE ae_conversation_events (
                    event_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    journal_seq INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    event_data TEXT NOT NULL,
                    supersedes_event_id TEXT,
                    correlation_id TEXT NOT NULL,
                    causation_id TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE (conversation_id, journal_seq)
                )
            """))
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _conversation(conversation_id: str = CONVERSATION_A, **overrides):
    return {
        "conversation_id": conversation_id,
        "tenant_id": "tenant-a",
        "workspace_id": WORKSPACE_ID,
        "owner_user_id": "user-a",
        "title": f"Conversation {conversation_id[-1]}",
        "status": "ACTIVE",
        "created_at": NOW,
        "updated_at": NOW,
        **overrides,
    }


def _message(message_id: str = MESSAGE_A, **overrides):
    return {
        "message_id": message_id,
        "tenant_id": "tenant-a",
        "owner_user_id": "user-a",
        "conversation_id": CONVERSATION_A,
        "role": "USER",
        "content_type": "text/plain; charset=utf-8",
        "legacy_interaction_id": None,
        "supersedes_message_id": None,
        "correlation_id": "correlation-a",
        "causation_id": None,
        "created_at": NOW,
        **overrides,
    }


def _event(event_id: str = EVENT_A, **overrides):
    return {
        "event_id": event_id,
        "tenant_id": "tenant-a",
        "owner_user_id": "user-a",
        "conversation_id": CONVERSATION_A,
        "event_type": "interaction.accepted",
        "event_data": {"interaction_id": "interaction-a"},
        "supersedes_event_id": None,
        "correlation_id": "correlation-a",
        "causation_id": None,
        "created_at": NOW,
        **overrides,
    }


def _repository(*, sessions=None, storage=None):
    return SqlAlchemyConversationJournal(
        sessions or _session_factory(),
        storage or InMemoryConversationContentStorage(),
    )


def test_workspace_owns_multiple_project_neutral_conversations() -> None:
    repository = _repository()

    first = repository.create_conversation(_conversation())
    second = repository.create_conversation(_conversation(CONVERSATION_B))
    repeated = repository.create_conversation(_conversation(title="Ignored retry"))
    listed = repository.list_conversations(
        tenant_id="tenant-a",
        owner_user_id="user-a",
        workspace_id=WORKSPACE_ID,
    )

    assert repeated == first
    assert {item["conversation_id"] for item in listed} == {
        CONVERSATION_A,
        CONVERSATION_B,
    }
    assert second["workspace_id"] == first["workspace_id"] == WORKSPACE_ID
    assert all("project_id" not in item for item in listed)


def test_default_chat_document_identity_can_be_used_as_conversation_id() -> None:
    repository = _repository()
    default = repository.create_conversation(_conversation(WORKSPACE_ID))

    assert default["conversation_id"] == WORKSPACE_ID
    assert default["next_journal_seq"] == 1
    assert default["version"] == 1


def test_conversation_creation_enforces_workspace_owner_and_collision() -> None:
    sessions = _session_factory()
    repository = _repository(sessions=sessions)
    repository.create_conversation(_conversation())

    for record in (
        _conversation(CONVERSATION_B, owner_user_id="user-b"),
        _conversation(CONVERSATION_B, tenant_id="tenant-b"),
        _conversation(CONVERSATION_B, workspace_id=MESSAGE_A),
        _conversation(owner_user_id="user-b"),
    ):
        with pytest.raises(ConversationJournalError) as exc_info:
            repository.create_conversation(record)
        assert exc_info.value.error_code == "ae.conversation_scope_forbidden"

    with sessions.begin() as session:
        session.execute(
            text("INSERT INTO ae_workspaces VALUES (:id, 'tenant-a', 'user-a')"),
            {"id": MESSAGE_A},
        )
    with pytest.raises(ConversationJournalError) as collision:
        repository.create_conversation(_conversation(workspace_id=MESSAGE_A))
    assert collision.value.error_code == "ae.conversation_scope_forbidden"


def test_messages_and_events_share_order_without_raw_database_content() -> None:
    sessions = _session_factory()
    storage = InMemoryConversationContentStorage()
    repository = _repository(sessions=sessions, storage=storage)
    repository.create_conversation(_conversation())

    message = repository.append_message(_message(), content="개인 원문 prompt")
    event = repository.append_event(_event())
    correction = repository.append_message(
        _message(
            MESSAGE_B,
            role="ASSISTANT",
            supersedes_message_id=MESSAGE_A,
            causation_id=MESSAGE_A,
        ),
        content="정정된 답변",
    )
    entries = repository.list_entries(
        tenant_id="tenant-a",
        owner_user_id="user-a",
        conversation_id=CONVERSATION_A,
    )

    assert [entry["journal_seq"] for entry in entries] == [1, 2, 3]
    assert [entry["entry_kind"] for entry in entries] == [
        "MESSAGE",
        "EVENT",
        "MESSAGE",
    ]
    assert correction["supersedes_message_id"] == MESSAGE_A
    assert repository.load_message_content(
        tenant_id="tenant-a", owner_user_id="user-a", message_id=MESSAGE_A
    ) == "개인 원문 prompt"
    assert "content" not in message
    assert "storage_ref" not in event
    with sessions() as session:
        persisted = str(
            session.execute(text("SELECT * FROM ae_conversation_messages")).all()
        )
    assert "개인 원문 prompt" not in persisted


def test_message_and_event_retries_are_idempotent_but_collisions_fail() -> None:
    repository = _repository()
    repository.create_conversation(_conversation())
    message = repository.append_message(_message(), content="same")
    event = repository.append_event(_event())

    assert repository.append_message(_message(), content="same") == message
    assert repository.append_event(_event()) == event
    with pytest.raises(ConversationJournalError) as message_conflict:
        repository.append_message(_message(), content="different")
    assert message_conflict.value.error_code == "ae.conversation_journal_write_conflict"
    with pytest.raises(ConversationJournalError) as event_conflict:
        repository.append_event(_event(event_type="different"))
    assert event_conflict.value.error_code == "ae.conversation_journal_write_conflict"


def test_owner_isolation_and_inactive_conversation_fail_closed() -> None:
    sessions = _session_factory()
    storage = InMemoryConversationContentStorage()
    repository = _repository(sessions=sessions, storage=storage)
    repository.create_conversation(_conversation())
    repository.append_message(_message(), content="private")

    assert repository.list_entries(
        tenant_id="tenant-a",
        owner_user_id="user-b",
        conversation_id=CONVERSATION_A,
    ) == []
    assert repository.load_message_content(
        tenant_id="tenant-a", owner_user_id="user-b", message_id=MESSAGE_A
    ) is None
    assert repository.load_message_content(
        tenant_id="tenant-a", owner_user_id="user-a", message_id=MESSAGE_B
    ) is None
    with sessions.begin() as session:
        session.execute(text("UPDATE ae_conversations SET status = 'ARCHIVED'"))
    with pytest.raises(ConversationJournalError) as exc_info:
        repository.append_event(_event())
    assert exc_info.value.error_code == "ae.conversation_scope_forbidden"


class _WrongRefStorage(InMemoryConversationContentStorage):
    def save(self, payload, *, tenant_id, owner_user_id):
        super().save(payload, tenant_id=tenant_id, owner_user_id=owner_user_id)
        return "ae://conversation-journal/wrong/ref/value.txt"


def test_storage_reference_mismatch_and_database_failure_leave_no_residue() -> None:
    wrong = _WrongRefStorage()
    repository = _repository(storage=wrong)
    repository.create_conversation(_conversation())
    with pytest.raises(ConversationJournalError) as mismatch:
        repository.append_message(_message(), content="private")
    assert mismatch.value.error_code == "ae.conversation_journal_invalid"
    assert wrong.payloads == {}

    storage = InMemoryConversationContentStorage()
    unavailable = _repository(sessions=_session_factory(with_schema=False), storage=storage)
    with pytest.raises(ConversationJournalError) as failure:
        unavailable.append_message(_message(), content="private")
    assert failure.value.error_code == "ae.conversation_journal_store_unavailable"
    assert failure.value.retryable is True
    assert storage.payloads == {}


def test_event_data_rejects_private_content_recursively() -> None:
    repository = _repository()
    repository.create_conversation(_conversation())

    for event_data in (
        {"prompt": "secret"},
        {"nested": {"response": "secret"}},
        {"items": [{"raw_content": "secret"}]},
        "not-an-object",
    ):
        with pytest.raises(ConversationJournalError) as exc_info:
            repository.append_event(_event(event_data=event_data))
        assert exc_info.value.error_code == "ae.conversation_journal_invalid"


def test_memory_content_storage_is_owner_scoped_and_integrity_checked() -> None:
    storage = InMemoryConversationContentStorage()
    payload = build_conversation_content_payload(entry_id=MESSAGE_A, content="hello")
    metadata = conversation_content_metadata(payload)

    assert storage.save(payload, tenant_id="tenant-a", owner_user_id="user-a") == (
        payload["storage_ref"]
    )
    assert storage.load(
        metadata, tenant_id="tenant-a", owner_user_id="user-a"
    ) == "hello"
    assert storage.load(
        metadata, tenant_id="tenant-a", owner_user_id="user-b"
    ) is None
    key = next(iter(storage.payloads))
    storage.payloads[key] = b"tampered"
    with pytest.raises(ConversationJournalError) as integrity:
        storage.load(metadata, tenant_id="tenant-a", owner_user_id="user-a")
    assert integrity.value.error_code == "ae.conversation_content_integrity_failed"
    storage.payloads[key] = b"\xff"
    with pytest.raises(ConversationJournalError):
        storage.load(metadata, tenant_id="tenant-a", owner_user_id="user-a")
    assert storage.delete(
        metadata, tenant_id="tenant-a", owner_user_id="user-a"
    ) is True
    assert storage.delete(
        metadata, tenant_id="tenant-a", owner_user_id="user-a"
    ) is False


def test_local_content_storage_round_trip_permissions_and_owner_path(
    tmp_path: Path,
) -> None:
    storage = LocalConversationContentStorage(tmp_path)
    payload = build_conversation_content_payload(entry_id=MESSAGE_A, content="hello")
    metadata = conversation_content_metadata(payload)

    storage.save(payload, tenant_id="tenant-a", owner_user_id="user-a")
    path = storage._path("tenant-a", "user-a", payload["storage_ref"])
    other_path = storage._path("tenant-a", "user-b", payload["storage_ref"])
    assert path != other_path
    assert path.stat().st_mode & 0o777 == 0o600
    assert storage.load(
        metadata, tenant_id="tenant-a", owner_user_id="user-a"
    ) == "hello"
    assert storage.load(
        metadata, tenant_id="tenant-a", owner_user_id="user-b"
    ) is None
    assert storage.delete(
        metadata, tenant_id="tenant-a", owner_user_id="user-a"
    ) is True
    assert storage.delete(
        metadata, tenant_id="tenant-a", owner_user_id="user-a"
    ) is False


def test_default_storage_and_payload_validation(tmp_path: Path, monkeypatch) -> None:
    assert isinstance(build_default_conversation_content_storage({}), InMemoryConversationContentStorage)
    configured = build_default_conversation_content_storage(
        {"NEX_AE_CONVERSATION_STORAGE_ROOT": str(tmp_path)}
    )
    assert isinstance(configured, LocalConversationContentStorage)
    with pytest.raises(ConversationJournalError):
        build_default_conversation_content_storage(
            {"NEX_AE_PRIVATE_STORAGE_MODE": "FILESYSTEM"}
        )
    monkeypatch.setenv("NEX_AE_CONVERSATION_STORAGE_ROOT", str(tmp_path))
    assert isinstance(build_default_conversation_content_storage(), LocalConversationContentStorage)

    valid = build_conversation_content_payload(entry_id=MESSAGE_A, content="hello")
    for invalid in (
        {**valid, "storage_ref": "bad"},
        {**valid, "content_sha256": "bad"},
        {**valid, "size_bytes": True},
        {**valid, "size_bytes": -1},
        {**valid, "content": 3},
        {**valid, "extra": True},
    ):
        with pytest.raises(ConversationJournalError):
            conversation_content_metadata(invalid)
    with pytest.raises(ConversationJournalError):
        build_conversation_content_payload(entry_id="bad/id", content="x")
    with pytest.raises(ConversationJournalError):
        build_conversation_content_payload(entry_id=MESSAGE_A, content=3)  # type: ignore[arg-type]
    with pytest.raises(ConversationJournalError):
        build_conversation_content_payload(
            entry_id=MESSAGE_A, content="x", content_type="application/json"
        )
    monkeypatch.setattr(journal_module, "MAX_CONVERSATION_CONTENT_BYTES", 1)
    with pytest.raises(ConversationJournalError):
        build_conversation_content_payload(entry_id=MESSAGE_A, content="too long")


class _ObjectStore:
    def __init__(self):
        self.objects = {}
        self.failure = None

    def put_immutable(self, **kwargs):
        if self.failure:
            raise self.failure
        self.objects[kwargs["key"]] = kwargs["payload"]

    def get_bytes(self, **kwargs):
        if self.failure:
            raise self.failure
        return self.objects.get(kwargs["key"])

    def head(self, key):
        if self.failure:
            raise self.failure
        return object() if key in self.objects else None

    def delete(self, key):
        if self.failure:
            raise self.failure
        self.objects.pop(key, None)


def test_s3_content_storage_round_trip_owner_scope_and_error_mapping(
    monkeypatch,
) -> None:
    object_store = _ObjectStore()
    storage = S3ConversationContentStorage(object_store)  # type: ignore[arg-type]
    payload = build_conversation_content_payload(entry_id=MESSAGE_A, content="hello")
    metadata = conversation_content_metadata(payload)

    assert storage.save(payload, tenant_id="tenant-a", owner_user_id="user-a") == (
        payload["storage_ref"]
    )
    assert storage.load(
        metadata, tenant_id="tenant-a", owner_user_id="user-a"
    ) == "hello"
    assert storage.load(
        metadata, tenant_id="tenant-a", owner_user_id="user-b"
    ) is None
    assert storage.delete(
        metadata, tenant_id="tenant-a", owner_user_id="user-b"
    ) is False
    assert storage.delete(
        metadata, tenant_id="tenant-a", owner_user_id="user-a"
    ) is True

    for error, code in (
        (
            ObjectStorageError("OBJECT_STORAGE_UNAVAILABLE", "down", retryable=True),
            "ae.conversation_content_store_unavailable",
        ),
        (
            ObjectStorageError("OBJECT_STORAGE_INTEGRITY_MISMATCH", "bad"),
            "ae.conversation_content_integrity_failed",
        ),
        (
            ObjectStorageError("OBJECT_STORAGE_FORBIDDEN", "bad"),
            "ae.conversation_journal_invalid",
        ),
    ):
        object_store.failure = error
        with pytest.raises(ConversationJournalError) as exc_info:
            storage.save(payload, tenant_id="tenant-a", owner_user_id="user-a")
        assert exc_info.value.error_code == code
    object_store.failure = ObjectStorageError(
        "OBJECT_STORAGE_UNAVAILABLE", "down", retryable=True
    )
    with pytest.raises(ConversationJournalError):
        storage.load(metadata, tenant_id="tenant-a", owner_user_id="user-a")
    with pytest.raises(ConversationJournalError):
        storage.delete(metadata, tenant_id="tenant-a", owner_user_id="user-a")

    object_store.failure = None
    monkeypatch.setattr(
        journal_module,
        "build_ae_private_object_store",
        lambda env: object_store,
    )
    selected = build_default_conversation_content_storage(
        {"NEX_AE_PRIVATE_STORAGE_MODE": "S3"}
    )
    assert isinstance(selected, S3ConversationContentStorage)


def test_s3_configuration_and_owner_key_fail_closed(monkeypatch) -> None:
    monkeypatch.setattr(
        journal_module,
        "build_ae_private_object_store",
        lambda env: (_ for _ in ()).throw(
            AePrivateObjectStorageError("ae.bad_s3", "bad configuration")
        ),
    )
    with pytest.raises(ConversationJournalError) as configuration:
        build_default_conversation_content_storage(
            {"NEX_AE_PRIVATE_STORAGE_MODE": "S3"}
        )
    assert configuration.value.error_code == "ae.bad_s3"

    monkeypatch.setattr(
        journal_module,
        "build_owner_object_key",
        lambda **kwargs: (_ for _ in ()).throw(
            ObjectStorageError("OBJECT_STORAGE_KEY_INVALID", "bad key")
        ),
    )
    with pytest.raises(ConversationJournalError) as key_failure:
        S3ConversationContentStorage._key("tenant-a", "user-a", MESSAGE_A)
    assert key_failure.value.error_code == "ae.conversation_journal_invalid"


def test_local_storage_wraps_write_read_and_delete_failures(
    tmp_path: Path,
    monkeypatch,
) -> None:
    storage = LocalConversationContentStorage(tmp_path)
    payload = build_conversation_content_payload(entry_id=MESSAGE_A, content="hello")
    metadata = conversation_content_metadata(payload)

    def fail_tempfile(*args, **kwargs):
        raise OSError("tempfile unavailable")

    monkeypatch.setattr(journal_module.tempfile, "NamedTemporaryFile", fail_tempfile)
    with pytest.raises(ConversationJournalError) as before_write:
        storage.save(payload, tenant_id="tenant-a", owner_user_id="user-a")
    assert before_write.value.error_code == "ae.conversation_content_store_unavailable"
    monkeypatch.undo()

    monkeypatch.setattr(journal_module.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("replace")))
    with pytest.raises(ConversationJournalError):
        storage.save(payload, tenant_id="tenant-a", owner_user_id="user-a")
    assert not list(tmp_path.rglob("*.tmp"))
    monkeypatch.undo()

    storage.save(payload, tenant_id="tenant-a", owner_user_id="user-a")
    monkeypatch.setattr(Path, "read_bytes", lambda self: (_ for _ in ()).throw(OSError("read")))
    with pytest.raises(ConversationJournalError):
        storage.load(metadata, tenant_id="tenant-a", owner_user_id="user-a")
    monkeypatch.undo()

    monkeypatch.setattr(Path, "unlink", lambda self, **kwargs: (_ for _ in ()).throw(OSError("delete")))
    with pytest.raises(ConversationJournalError):
        storage.delete(metadata, tenant_id="tenant-a", owner_user_id="user-a")


def test_storage_reference_parser_rejects_malformed_values() -> None:
    for value in (
        None,
        "wrong://aa/bb/value.txt",
        "ae://conversation-journal/aa/bb",
        "ae://conversation-journal/aa/../value.txt",
        "ae://conversation-journal/aa/bb/value.bin",
    ):
        with pytest.raises(ConversationJournalError):
            journal_module._storage_ref_relative_path(value)


def test_post_write_reload_failures_are_typed_and_message_content_is_cleaned(
    monkeypatch,
) -> None:
    sessions = _session_factory()
    storage = InMemoryConversationContentStorage()
    repository = _repository(sessions=sessions, storage=storage)

    monkeypatch.setattr(journal_module, "_load_conversation", lambda *args: None)
    with pytest.raises(ConversationJournalError) as conversation_failure:
        repository.create_conversation(_conversation())
    assert conversation_failure.value.error_code == "ae.conversation_journal_write_conflict"
    monkeypatch.undo()
    repository.create_conversation(_conversation())

    monkeypatch.setattr(journal_module, "_load_message", lambda *args: None)
    with pytest.raises(ConversationJournalError) as message_failure:
        repository.append_message(_message(), content="private")
    assert message_failure.value.error_code == "ae.conversation_journal_write_conflict"
    assert storage.payloads == {}
    monkeypatch.undo()

    monkeypatch.setattr(journal_module, "_load_event", lambda *args: None)
    with pytest.raises(ConversationJournalError) as event_failure:
        repository.append_event(_event())
    assert event_failure.value.error_code == "ae.conversation_journal_write_conflict"


def test_invalid_records_and_unavailable_repository_are_typed() -> None:
    repository = _repository()
    invalid_conversations = (
        _conversation(title=""),
        _conversation(status="UNKNOWN"),
        _conversation(conversation_id="bad/id"),
        _conversation(owner_user_id=""),
    )
    for record in invalid_conversations:
        with pytest.raises(ConversationJournalError):
            repository.create_conversation(record)

    repository.create_conversation(_conversation())
    with pytest.raises(ConversationJournalError):
        repository.append_message(_message(role="UNKNOWN"), content="x")
    with pytest.raises(ConversationJournalError):
        repository.list_conversations(
            tenant_id="", owner_user_id="user-a", workspace_id=WORKSPACE_ID
        )
    with pytest.raises(ConversationJournalError):
        repository.list_entries(
            tenant_id="tenant-a", owner_user_id="user-a", conversation_id="bad/id"
        )
    with pytest.raises(ConversationJournalError):
        repository.load_message_content(
            tenant_id="tenant-a", owner_user_id="user-a", message_id="bad/id"
        )

    unavailable = _repository(sessions=_session_factory(with_schema=False))
    for operation in (
        lambda: unavailable.create_conversation(_conversation()),
        lambda: unavailable.list_conversations(
            tenant_id="tenant-a", owner_user_id="user-a", workspace_id=WORKSPACE_ID
        ),
        lambda: unavailable.append_event(_event()),
        lambda: unavailable.list_entries(
            tenant_id="tenant-a",
            owner_user_id="user-a",
            conversation_id=CONVERSATION_A,
        ),
        lambda: unavailable.load_message_content(
            tenant_id="tenant-a", owner_user_id="user-a", message_id=MESSAGE_A
        ),
    ):
        with pytest.raises(ConversationJournalError) as exc_info:
            operation()
        assert exc_info.value.error_code == "ae.conversation_journal_store_unavailable"
        assert str(exc_info.value) == "AE Conversation journal store is unavailable."


def test_helpers_cover_datetime_postgres_and_optional_lineage() -> None:
    assert "CAST(:event_data AS jsonb)" in journal_module._event_insert_sql("postgresql")
    assert "CAST(:event_data AS jsonb)" not in journal_module._event_insert_sql("sqlite")
    assert journal_module._datetime_value(
        datetime(2026, 10, 13, tzinfo=UTC)
    ) == "2026-10-13T00:00:00Z"
    assert journal_module._string_or_none(None) is None
    assert journal_module._string_or_none(MESSAGE_A) == MESSAGE_A
    assert journal_module._optional_safe_id(None) is None
    assert journal_module._optional_text(None) is None
    with pytest.raises(ConversationJournalError):
        journal_module._optional_text(" ")


def test_migration_is_project_neutral_private_and_append_only() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    lowered = sql.lower()

    assert "create table if not exists ae_conversations" in lowered
    assert "create table if not exists ae_conversation_messages" in lowered
    assert "create table if not exists ae_conversation_events" in lowered
    assert "project_id" not in lowered
    assert "conversation_week" not in lowered
    assert " content text" not in lowered
    assert "before update or delete" in lowered
    assert "supersedes_message_id" in lowered
    assert "supersedes_event_id" in lowered
    assert "2002_ae_conversation_journal" in lowered
    assert len("ae_conversation_messages") <= 30
    assert len("ae_conversation_events") <= 30
