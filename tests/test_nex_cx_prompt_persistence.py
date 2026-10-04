from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from nex_cx.prompt_persistence import (
    CxPromptRepositoryError,
    SqlAlchemyCxPromptRegistryStore,
)
import nex_cx.prompt_persistence as persistence
from nex_cx.prompts import (
    CX_DOCUMENT_SUMMARY_BINDING,
    DEFAULT_CX_PROMPT_STORE,
    build_default_cx_prompt_store,
)
from nex_runtime.prompts import render_prompt_from_binding


TEMPLATE_ID = "11111111-1111-4111-8111-111111111111"
VERSION_ID = "22222222-2222-4222-8222-222222222222"
BINDING_ID = "33333333-3333-4333-8333-333333333333"
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"


def _store() -> tuple[SqlAlchemyCxPromptRegistryStore, object]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE cx_prompt_template_versions (
                    prompt_template_version_id TEXT PRIMARY KEY,
                    prompt_template_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    role TEXT NOT NULL,
                    segment_order INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    model_capability TEXT NOT NULL,
                    summary_max_chars INTEGER,
                    summary_hard_limit_chars INTEGER,
                    metadata TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE cx_prompt_bindings (
                    prompt_binding_id TEXT PRIMARY KEY,
                    binding_key TEXT NOT NULL UNIQUE,
                    prompt_template_version_id TEXT NOT NULL,
                    service_id TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    status TEXT NOT NULL,
                    bound_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE cx_prompt_render_events (
                    prompt_render_event_id TEXT PRIMARY KEY,
                    prompt_binding_id TEXT,
                    prompt_template_version_id TEXT,
                    trace_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    rendered_prompt_hash TEXT NOT NULL,
                    rendered_prompt_preview TEXT,
                    user_prompt_hash TEXT,
                    output_hash TEXT,
                    metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO cx_prompt_template_versions VALUES (
                    :version_id, :template_id, 'v1', 'system', 0,
                    'Summarize under {summary_max_chars} characters.',
                    :content_hash, 'summary', 900, 1000, '{}', 'ACTIVE',
                    '2026-10-05T00:00:00Z'
                )
                """
            ),
            {
                "version_id": VERSION_ID,
                "template_id": TEMPLATE_ID,
                "content_hash": "a" * 64,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO cx_prompt_bindings VALUES (
                    :binding_id, :binding_key, :version_id, 'nex-cx',
                    'document_summary', 'ACTIVE', '2026-10-05T00:00:00Z'
                )
                """
            ),
            {
                "binding_id": BINDING_ID,
                "binding_key": CX_DOCUMENT_SUMMARY_BINDING,
                "version_id": VERSION_ID,
            },
        )
    return SqlAlchemyCxPromptRegistryStore(sessionmaker(bind=engine)), engine


def test_store_reads_seeded_binding_and_persists_render_event() -> None:
    store, engine = _store()

    binding = store.get_binding(CX_DOCUMENT_SUMMARY_BINDING)
    version = store.get_template_version(VERSION_ID)
    rendered = render_prompt_from_binding(
        store,
        binding_key=CX_DOCUMENT_SUMMARY_BINDING,
        variables={"summary_max_chars": 900},
        request_id="request-1350",
        trace_id=TRACE_ID,
        output_text="safe output",
    )
    event_id = rendered["render_event"]["prompt_render_event_id"]

    assert binding is not None and binding["prompt_binding_id"] == BINDING_ID
    assert version is not None and version["summary_hard_limit_chars"] == 1000
    assert rendered["rendered_prompt"] == "Summarize under 900 characters."
    assert store.get_render_event(event_id) == rendered["render_event"]
    assert store.list_bindings() == [binding]
    assert store.get_binding("missing") is None
    assert store.get_template_version("missing") is None
    assert store.get_render_event("missing") is None
    engine.dispose()


def test_store_maps_database_failures_to_safe_error() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    store = SqlAlchemyCxPromptRegistryStore(sessionmaker(bind=engine))

    calls = (
        lambda: store.get_binding("missing"),
        lambda: store.get_template_version("missing"),
        lambda: store.get_render_event("missing"),
        store.list_bindings,
        lambda: store.save_render_event(
            {
                "prompt_render_event_id": "event",
                "prompt_binding_id": "binding",
                "prompt_template_version_id": "version",
                "trace_id": TRACE_ID,
                "request_id": "request",
                "rendered_prompt_hash": "a" * 64,
                "rendered_prompt_preview": "preview",
                "user_prompt_hash": None,
                "output_hash": None,
                "metadata": {},
                "created_at": "2026-10-05T00:00:00Z",
            }
        ),
    )
    for call in calls:
        with pytest.raises(CxPromptRepositoryError) as exc_info:
            call()
        assert exc_info.value.error_code == "cx.prompt_registry_unavailable"
        assert exc_info.value.retryable is True
        assert str(exc_info.value) == "CX prompt registry is unavailable."
    engine.dispose()


def test_render_event_write_conflict_is_safe(monkeypatch) -> None:
    store, engine = _store()
    monkeypatch.setattr(persistence, "_load_render_event", lambda *args: None)

    with pytest.raises(CxPromptRepositoryError) as exc_info:
        store.save_render_event(_render_event())

    assert exc_info.value.error_code == "cx.prompt_render_event_write_conflict"
    assert exc_info.value.retryable is True
    engine.dispose()


def test_render_event_uses_postgres_jsonb_cast(monkeypatch) -> None:
    class FakeSession:
        def __init__(self) -> None:
            self.statements: list[str] = []

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def get_bind(self):
            return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        def execute(self, statement, params):
            self.statements.append(str(statement))

        def commit(self) -> None:
            return None

    session = FakeSession()
    store = SqlAlchemyCxPromptRegistryStore(lambda: session)
    expected = _render_event()
    monkeypatch.setattr(
        persistence,
        "_load_render_event",
        lambda *args: expected,
    )

    assert store.save_render_event(expected) == expected
    assert "CAST(:metadata AS jsonb)" in session.statements[0]


def test_value_normalizers_cover_datetime_none_and_native_json() -> None:
    timestamp = datetime(2026, 10, 5, tzinfo=UTC)

    assert persistence._datetime_value(timestamp) == "2026-10-05T00:00:00Z"
    assert persistence._json_value(None, {"default": True}) == {"default": True}
    assert persistence._json_value({"native": True}, {}) == {"native": True}


def test_default_store_follows_service_persistence_runtime() -> None:
    memory_app = SimpleNamespace(state=SimpleNamespace())
    assert build_default_cx_prompt_store(memory_app) is DEFAULT_CX_PROMPT_STORE

    _, engine = _store()
    factory = sessionmaker(bind=engine)
    postgres_app = SimpleNamespace(
        state=SimpleNamespace(
            nex_persistence=SimpleNamespace(api_session_factory=factory)
        )
    )
    selected = build_default_cx_prompt_store(postgres_app)

    assert isinstance(selected, SqlAlchemyCxPromptRegistryStore)
    engine.dispose()


def _render_event() -> dict[str, object]:
    return {
        "prompt_render_event_id": "44444444-4444-4444-8444-444444444444",
        "prompt_binding_id": BINDING_ID,
        "prompt_template_version_id": VERSION_ID,
        "trace_id": TRACE_ID,
        "request_id": "request-1350",
        "rendered_prompt_hash": "b" * 64,
        "rendered_prompt_preview": "preview",
        "user_prompt_hash": None,
        "output_hash": "c" * 64,
        "metadata": {"safe": True},
        "created_at": "2026-10-05T00:00:00Z",
    }
