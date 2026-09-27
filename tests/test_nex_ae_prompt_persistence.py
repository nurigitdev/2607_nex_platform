from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import nex_ae_api.prompt_persistence as persistence
from nex_ae_api.prompt_persistence import (
    PromptRepositoryError,
    SqlAlchemyAePromptRegistryStore,
)
from nex_ae_api.prompts import (
    AE_PROMPT_SEEDS,
    AE_DOCUMENT_GENERATION_BINDING,
    AE_DOCUMENT_SUMMARY_BINDING,
    AE_GENERAL_ANSWER_BINDING,
    AE_GROUNDED_CHAT_BINDING,
    seed_ae_prompt_registry,
)
from nex_runtime.prompts import (
    PromptRegistryStore,
    build_prompt_binding,
    build_prompt_template,
    build_prompt_template_version,
    render_prompt_from_binding,
    seed_prompt_registry,
)


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"


def session_factory(*, with_schema: bool = True):
    engine = create_engine("sqlite+pysqlite://", future=True)
    if with_schema:
        with engine.begin() as connection:
            _create_schema(connection)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _create_schema(connection) -> None:
    connection.execute(text("""
        CREATE TABLE ae_prompt_templates (
            prompt_template_id TEXT PRIMARY KEY,
            service_id TEXT NOT NULL,
            purpose TEXT NOT NULL,
            name TEXT NOT NULL,
            owner_domain TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (service_id, purpose, name)
        )
    """))
    connection.execute(text("""
        CREATE TABLE ae_prompt_template_versions (
            prompt_template_version_id TEXT PRIMARY KEY,
            prompt_template_id TEXT NOT NULL,
            version TEXT NOT NULL,
            role TEXT NOT NULL,
            segment_order INTEGER NOT NULL,
            content TEXT NOT NULL,
            content_sha256 TEXT NOT NULL,
            model_capability TEXT NOT NULL,
            metadata TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE (prompt_template_id, version, role, segment_order)
        )
    """))
    connection.execute(text("""
        CREATE TABLE ae_prompt_bindings (
            prompt_binding_id TEXT PRIMARY KEY,
            binding_key TEXT NOT NULL UNIQUE,
            prompt_template_version_id TEXT NOT NULL,
            service_id TEXT NOT NULL,
            purpose TEXT NOT NULL,
            status TEXT NOT NULL,
            bound_at TEXT NOT NULL
        )
    """))
    connection.execute(text("""
        CREATE TABLE ae_prompt_render_events (
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
    """))


def test_registry_seeds_four_bindings_idempotently_and_survives_restart() -> None:
    factory = session_factory()
    first = SqlAlchemyAePromptRegistryStore(factory)
    seeded = seed_ae_prompt_registry(first)
    repeated = seed_ae_prompt_registry(first)
    restarted = SqlAlchemyAePromptRegistryStore(factory)

    assert len(seeded) == 4
    assert [item["binding_key"] for item in restarted.list_bindings()] == sorted(
        [
            AE_GENERAL_ANSWER_BINDING,
            AE_GROUNDED_CHAT_BINDING,
            AE_DOCUMENT_SUMMARY_BINDING,
            AE_DOCUMENT_GENERATION_BINDING,
        ]
    )
    assert [item["prompt_binding_id"] for item in repeated] == [
        item["prompt_binding_id"] for item in seeded
    ]
    binding = restarted.get_binding(AE_GROUNDED_CHAT_BINDING)
    version = restarted.get_template_version(binding["prompt_template_version_id"])
    assert version["version"] == "v1"
    assert version["metadata"]["retrieval_required"] is True
    assert restarted.get_binding("missing") is None
    assert restarted.get_template_version("missing") is None


def test_render_event_is_durable_idempotent_and_excludes_raw_user_prompt() -> None:
    factory = session_factory()
    store = SqlAlchemyAePromptRegistryStore(factory)
    seed_ae_prompt_registry(store)

    rendered = render_prompt_from_binding(
        store,
        binding_key=AE_GENERAL_ANSWER_BINDING,
        variables={},
        request_id="request-1024",
        trace_id=TRACE_ID,
        user_prompt="private user message",
    )
    repeated = store.save_render_event(rendered["render_event"])
    restarted = SqlAlchemyAePromptRegistryStore(factory)
    loaded = restarted.get_render_event(repeated["prompt_render_event_id"])

    assert loaded == repeated
    assert loaded["binding_key"] == AE_GENERAL_ANSWER_BINDING
    assert loaded["user_prompt_hash"] is not None
    assert "private user message" not in str(loaded)
    assert restarted.get_render_event("missing") is None


def test_repository_wraps_database_errors_and_error_string() -> None:
    store = SqlAlchemyAePromptRegistryStore(session_factory(with_schema=False))
    operations = (
        lambda: seed_ae_prompt_registry(store),
        lambda: store.get_binding("missing"),
        lambda: store.get_template_version("missing"),
        lambda: store.get_render_event("missing"),
        store.list_bindings,
    )
    for operation in operations:
        with pytest.raises(PromptRepositoryError) as raised:
            operation()
        assert raised.value.error_code == "ae.prompt_registry_unavailable"
        assert raised.value.retryable is True
        assert str(raised.value) == "AE prompt registry is unavailable."


def test_helpers_cover_postgres_json_datetime_and_missing_write(monkeypatch) -> None:
    assert "CAST(:metadata AS jsonb)" in persistence._version_upsert_sql(
        "postgresql"
    )
    assert "CAST(:metadata AS jsonb)" in persistence._render_event_insert_sql(
        "postgresql"
    )
    assert persistence._json_value('{"value": 1}', {}) == {"value": 1}
    assert persistence._json_value(None, {}) == {}
    assert persistence._json_value({"value": 2}, {}) == {"value": 2}
    assert persistence._datetime_value(
        datetime(2026, 9, 28, tzinfo=UTC)
    ) == "2026-09-28T00:00:00Z"
    with pytest.raises(PromptRepositoryError) as raised:
        persistence._required_saved(None)
    assert raised.value.error_code == "ae.prompt_registry_write_conflict"

    factory = session_factory()
    store = SqlAlchemyAePromptRegistryStore(factory)
    monkeypatch.setattr(persistence, "_load_template_by_key", lambda *args, **kwargs: None)
    with pytest.raises(PromptRepositoryError):
        seed_ae_prompt_registry(store)


def _registry_records() -> tuple[dict, dict, dict, dict]:
    seed = AE_PROMPT_SEEDS[0]
    template = build_prompt_template(seed)
    version = build_prompt_template_version(seed, template)
    binding = build_prompt_binding(seed, version)
    memory = PromptRegistryStore()
    seed_prompt_registry(memory, [seed])
    event = render_prompt_from_binding(
        memory,
        binding_key=seed.binding_key,
        variables={},
        request_id="request-error-path",
        trace_id=TRACE_ID,
    )["render_event"]
    return template, version, binding, event


@pytest.mark.parametrize(
    ("method_name", "record_index"),
    [
        ("save_template_version", 1),
        ("save_binding", 2),
        ("save_render_event", 3),
    ],
)
def test_each_write_method_wraps_sqlalchemy_errors(
    method_name: str,
    record_index: int,
) -> None:
    records = _registry_records()
    store = SqlAlchemyAePromptRegistryStore(session_factory(with_schema=False))

    with pytest.raises(PromptRepositoryError) as raised:
        getattr(store, method_name)(records[record_index])

    assert raised.value.error_code == "ae.prompt_registry_unavailable"


@pytest.mark.parametrize(
    ("method_name", "loader_name", "record_index"),
    [
        ("save_template_version", "_load_template_version_by_key", 1),
        ("save_binding", "_load_binding", 2),
        ("save_render_event", "_load_render_event", 3),
    ],
)
def test_each_write_method_preserves_repository_errors(
    monkeypatch,
    method_name: str,
    loader_name: str,
    record_index: int,
) -> None:
    template, version, binding, event = _registry_records()
    records = (template, version, binding, event)
    store = SqlAlchemyAePromptRegistryStore(session_factory())
    store.save_template(template)
    if method_name == "save_render_event":
        store.save_template_version(version)
        store.save_binding(binding)
    monkeypatch.setattr(persistence, loader_name, lambda *args, **kwargs: None)

    with pytest.raises(PromptRepositoryError) as raised:
        getattr(store, method_name)(records[record_index])

    assert raised.value.error_code == "ae.prompt_registry_write_conflict"
