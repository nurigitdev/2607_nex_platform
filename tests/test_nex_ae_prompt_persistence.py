from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import nex_ae_api.prompt_persistence as persistence
import pytest
from nex_ae_api.prompt_persistence import (
    PromptRepositoryError,
    SqlAlchemyAePromptRegistryStore,
)
from nex_ae_api.prompts import (
    AE_CONTEXT_CANDIDATE_BINDING,
    AE_DOCUMENT_GENERATION_BINDING,
    AE_DOCUMENT_SUMMARY_BINDING,
    AE_GENERAL_ANSWER_BINDING,
    AE_GROUNDED_CHAT_BINDING,
    AE_INTENT_RESOLUTION_BINDING,
    AE_PLAN_BUILDER_BINDING,
    AE_PROMPT_SEEDS,
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
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

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
    connection.execute(text("""
        CREATE TABLE ae_prompt_binding_history (
            binding_change_id TEXT PRIMARY KEY,
            binding_key TEXT NOT NULL,
            old_prompt_template_version_id TEXT NOT NULL,
            new_prompt_template_version_id TEXT NOT NULL,
            changed_by TEXT NOT NULL,
            reason TEXT NOT NULL,
            correlation_id TEXT NOT NULL,
            changed_at TEXT NOT NULL,
            UNIQUE (binding_key, correlation_id)
        )
    """))


def test_registry_seeds_configured_bindings_idempotently_and_survives_restart() -> None:
    factory = session_factory()
    first = SqlAlchemyAePromptRegistryStore(factory)
    seeded = seed_ae_prompt_registry(first)
    repeated = seed_ae_prompt_registry(first)
    restarted = SqlAlchemyAePromptRegistryStore(factory)

    assert len(seeded) == len(AE_PROMPT_SEEDS)
    assert [item["binding_key"] for item in restarted.list_bindings()] == sorted(
        [
            AE_GENERAL_ANSWER_BINDING,
            AE_GROUNDED_CHAT_BINDING,
            AE_DOCUMENT_SUMMARY_BINDING,
            AE_DOCUMENT_GENERATION_BINDING,
            AE_INTENT_RESOLUTION_BINDING,
            AE_CONTEXT_CANDIDATE_BINDING,
            AE_PLAN_BUILDER_BINDING,
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
    assert "CAST(:metadata AS jsonb)" in persistence._version_insert_sql(
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


def test_template_version_insert_is_idempotent_but_never_overwrites_content() -> None:
    store = SqlAlchemyAePromptRegistryStore(session_factory())
    seed = AE_PROMPT_SEEDS[0]
    template = store.save_template(build_prompt_template(seed))
    first = build_prompt_template_version(seed, template)

    assert store.save_template_version(first) == store.save_template_version(first)

    changed_seed = replace(seed, content=f"{seed.content} changed")
    changed = build_prompt_template_version(changed_seed, template)
    with pytest.raises(PromptRepositoryError) as raised:
        store.save_template_version(changed)

    assert raised.value.error_code == "ae.prompt_template_version_immutable_conflict"
    assert store.get_template_version(first["prompt_template_version_id"])[
        "content"
    ] == seed.content


def test_binding_activation_is_atomic_cas_and_keeps_exact_provenance_snapshot() -> None:
    factory = session_factory()
    store = SqlAlchemyAePromptRegistryStore(
        factory,
        id_factory=lambda: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        clock=lambda: datetime(2026, 10, 13, tzinfo=UTC),
    )
    seed = AE_PROMPT_SEEDS[0]
    template = store.save_template(build_prompt_template(seed))
    first = store.save_template_version(build_prompt_template_version(seed, template))
    binding = store.save_binding(build_prompt_binding(seed, first))
    before = store.get_prompt_provenance(seed.binding_key)

    second_seed = replace(seed, version="v2", content=f"{seed.content} v2")
    second = store.save_template_version(
        build_prompt_template_version(second_seed, template)
    )
    changed = store.activate_binding(
        binding_key=seed.binding_key,
        new_prompt_template_version_id=second["prompt_template_version_id"],
        expected_prompt_template_version_id=first["prompt_template_version_id"],
        changed_by="operator-1",
        reason="P5 activation test",
        correlation_id="correlation-1",
    )

    assert changed["changed"] is True
    assert changed["history"]["old_prompt_template_version_id"] == first[
        "prompt_template_version_id"
    ]
    assert changed["binding"]["prompt_template_version_id"] == second[
        "prompt_template_version_id"
    ]
    assert before["prompt_template_version_id"] == binding[
        "prompt_template_version_id"
    ]
    assert before["prompt_content_sha256"] == first["content_sha256"]
    assert store.get_prompt_provenance(seed.binding_key)[
        "prompt_template_version_id"
    ] == second["prompt_template_version_id"]

    repeated = store.activate_binding(
        binding_key=seed.binding_key,
        new_prompt_template_version_id=second["prompt_template_version_id"],
        expected_prompt_template_version_id=first["prompt_template_version_id"],
        changed_by="operator-2",
        reason="idempotent replay",
        correlation_id="correlation-2",
    )
    assert repeated == {
        "changed": False,
        "binding": changed["binding"],
        "history": None,
    }
    with factory() as session:
        assert session.execute(
            text("SELECT count(*) FROM ae_prompt_binding_history")
        ).scalar_one() == 1


def test_binding_activation_rejects_stale_expected_current_version() -> None:
    factory = session_factory()
    store = SqlAlchemyAePromptRegistryStore(factory)
    seed = AE_PROMPT_SEEDS[0]
    template = store.save_template(build_prompt_template(seed))
    first = store.save_template_version(build_prompt_template_version(seed, template))
    store.save_binding(build_prompt_binding(seed, first))
    second_seed = replace(seed, version="v2", content=f"{seed.content} v2")
    second = store.save_template_version(
        build_prompt_template_version(second_seed, template)
    )

    with pytest.raises(PromptRepositoryError) as raised:
        store.activate_binding(
            binding_key=seed.binding_key,
            new_prompt_template_version_id=second["prompt_template_version_id"],
            expected_prompt_template_version_id="ffffffff-ffff-4fff-8fff-ffffffffffff",
            changed_by="operator",
            reason="stale activation",
            correlation_id="correlation-stale",
        )

    assert raised.value.error_code == "ae.prompt_binding_version_conflict"
    assert store.get_binding(seed.binding_key)["prompt_template_version_id"] == first[
        "prompt_template_version_id"
    ]


@pytest.mark.parametrize("failure_target", ["history", "pointer"])
def test_binding_activation_rolls_back_history_and_pointer_on_fault(
    failure_target: str,
) -> None:
    factory = session_factory()
    store = SqlAlchemyAePromptRegistryStore(factory)
    seed = AE_PROMPT_SEEDS[0]
    template = store.save_template(build_prompt_template(seed))
    first = store.save_template_version(build_prompt_template_version(seed, template))
    store.save_binding(build_prompt_binding(seed, first))
    second_seed = replace(seed, version="v2", content=f"{seed.content} v2")
    second = store.save_template_version(
        build_prompt_template_version(second_seed, template)
    )
    trigger_target = (
        "ae_prompt_binding_history" if failure_target == "history" else "ae_prompt_bindings"
    )
    trigger_operation = "INSERT" if failure_target == "history" else "UPDATE"
    with factory() as session:
        session.execute(text(f"""
            CREATE TRIGGER fail_{failure_target}
            BEFORE {trigger_operation} ON {trigger_target}
            BEGIN SELECT RAISE(ABORT, 'injected failure'); END
        """))
        session.commit()

    with pytest.raises(PromptRepositoryError) as raised:
        store.activate_binding(
            binding_key=seed.binding_key,
            new_prompt_template_version_id=second["prompt_template_version_id"],
            expected_prompt_template_version_id=first["prompt_template_version_id"],
            changed_by="operator",
            reason="fault injection",
            correlation_id=f"correlation-{failure_target}",
        )

    assert raised.value.error_code == "ae.prompt_registry_unavailable"
    assert store.get_binding(seed.binding_key)["prompt_template_version_id"] == first[
        "prompt_template_version_id"
    ]
    with factory() as session:
        assert session.execute(
            text("SELECT count(*) FROM ae_prompt_binding_history")
        ).scalar_one() == 0


def test_startup_seed_does_not_move_an_operator_managed_binding() -> None:
    factory = session_factory()
    store = SqlAlchemyAePromptRegistryStore(factory)
    seed = AE_PROMPT_SEEDS[0]
    template = store.save_template(build_prompt_template(seed))
    first = store.save_template_version(build_prompt_template_version(seed, template))
    store.save_binding(build_prompt_binding(seed, first))
    second_seed = replace(seed, version="v2", content=f"{seed.content} v2")
    second = store.save_template_version(
        build_prompt_template_version(second_seed, template)
    )
    store.activate_binding(
        binding_key=seed.binding_key,
        new_prompt_template_version_id=second["prompt_template_version_id"],
        expected_prompt_template_version_id=first["prompt_template_version_id"],
        changed_by="operator",
        reason="managed rollout",
        correlation_id="managed-rollout",
    )

    seeded = store.save_binding(build_prompt_binding(seed, first))

    assert seeded["prompt_template_version_id"] == second[
        "prompt_template_version_id"
    ]


def test_binding_activation_rejects_missing_inactive_and_cross_template_targets() -> None:
    factory = session_factory()
    store = SqlAlchemyAePromptRegistryStore(factory)
    seed = AE_PROMPT_SEEDS[0]
    template = store.save_template(build_prompt_template(seed))
    first = store.save_template_version(build_prompt_template_version(seed, template))
    store.save_binding(build_prompt_binding(seed, first))

    with pytest.raises(PromptRepositoryError) as missing:
        store.activate_binding(
            binding_key="ae.missing",
            new_prompt_template_version_id=first["prompt_template_version_id"],
            expected_prompt_template_version_id=first[
                "prompt_template_version_id"
            ],
            changed_by="operator",
            reason="missing",
            correlation_id="missing-binding",
        )
    assert missing.value.error_code == "ae.prompt_binding_not_found"

    other_seed = AE_PROMPT_SEEDS[1]
    other_template = store.save_template(build_prompt_template(other_seed))
    other = store.save_template_version(
        build_prompt_template_version(other_seed, other_template)
    )
    store.save_binding(build_prompt_binding(other_seed, other))
    with pytest.raises(PromptRepositoryError) as mismatch:
        store.activate_binding(
            binding_key=seed.binding_key,
            new_prompt_template_version_id=other["prompt_template_version_id"],
            expected_prompt_template_version_id=first[
                "prompt_template_version_id"
            ],
            changed_by="operator",
            reason="cross template",
            correlation_id="cross-template",
        )
    assert mismatch.value.error_code == "ae.prompt_binding_template_mismatch"

    with factory.begin() as session:
        session.execute(
            text(
                "UPDATE ae_prompt_template_versions SET status = 'RETIRED' "
                "WHERE prompt_template_version_id = :id"
            ),
            {"id": other["prompt_template_version_id"]},
        )
    with pytest.raises(PromptRepositoryError) as inactive:
        store.get_prompt_provenance(other_seed.binding_key)
    assert inactive.value.error_code == "ae.prompt_template_version_ineligible"

    retired_seed = replace(seed, version="v2", content=f"{seed.content} v2")
    retired = store.save_template_version(
        build_prompt_template_version(retired_seed, template)
    )
    with factory.begin() as session:
        session.execute(
            text(
                "UPDATE ae_prompt_template_versions SET status = 'RETIRED' "
                "WHERE prompt_template_version_id = :id"
            ),
            {"id": retired["prompt_template_version_id"]},
        )
    with pytest.raises(PromptRepositoryError) as retired_target:
        store.activate_binding(
            binding_key=seed.binding_key,
            new_prompt_template_version_id=retired["prompt_template_version_id"],
            expected_prompt_template_version_id=first[
                "prompt_template_version_id"
            ],
            changed_by="operator",
            reason="retired target",
            correlation_id="retired-target",
        )
    assert retired_target.value.error_code == "ae.prompt_template_version_ineligible"


def test_binding_activation_and_template_version_inputs_fail_closed() -> None:
    store = SqlAlchemyAePromptRegistryStore(session_factory())
    seed = AE_PROMPT_SEEDS[0]
    template = store.save_template(build_prompt_template(seed))
    version = build_prompt_template_version(seed, template)
    invalid_version = {**version, "content_sha256": "bad"}
    with pytest.raises(PromptRepositoryError) as invalid_hash:
        store.save_template_version(invalid_version)
    assert invalid_hash.value.error_code == "ae.prompt_template_version_invalid"

    invalid_content = {**version, "content": f"{version['content']} changed"}
    with pytest.raises(PromptRepositoryError) as invalid_digest:
        store.save_template_version(invalid_content)
    assert invalid_digest.value.error_code == "ae.prompt_template_version_invalid"

    with pytest.raises(PromptRepositoryError) as invalid_change:
        store.activate_binding(
            binding_key=seed.binding_key,
            new_prompt_template_version_id="not-a-uuid",
            expected_prompt_template_version_id=version[
                "prompt_template_version_id"
            ],
            changed_by="operator",
            reason="invalid",
            correlation_id="invalid-change",
        )
    assert invalid_change.value.error_code == "ae.prompt_binding_change_invalid"

    with pytest.raises(PromptRepositoryError) as empty_change:
        store.activate_binding(
            binding_key=" ",
            new_prompt_template_version_id=version[
                "prompt_template_version_id"
            ],
            expected_prompt_template_version_id=version[
                "prompt_template_version_id"
            ],
            changed_by="operator",
            reason="invalid",
            correlation_id="invalid-change",
        )
    assert empty_change.value.error_code == "ae.prompt_binding_change_invalid"


def test_binding_activation_rolls_back_when_pointer_cas_or_history_reload_fails(
    monkeypatch,
) -> None:
    factory = session_factory()
    store = SqlAlchemyAePromptRegistryStore(factory)
    seed = AE_PROMPT_SEEDS[0]
    template = store.save_template(build_prompt_template(seed))
    first = store.save_template_version(build_prompt_template_version(seed, template))
    store.save_binding(build_prompt_binding(seed, first))
    second_seed = replace(seed, version="v2", content=f"{seed.content} v2")
    second = store.save_template_version(
        build_prompt_template_version(second_seed, template)
    )
    arguments = {
        "binding_key": seed.binding_key,
        "new_prompt_template_version_id": second["prompt_template_version_id"],
        "expected_prompt_template_version_id": first[
            "prompt_template_version_id"
        ],
        "changed_by": "operator",
        "reason": "fault injection",
        "correlation_id": "cas-failure",
    }

    monkeypatch.setattr(
        persistence,
        "_binding_pointer_cas_sql",
        lambda: "UPDATE ae_prompt_bindings SET bound_at = bound_at WHERE 0 = 1",
    )
    with pytest.raises(PromptRepositoryError) as cas_failure:
        store.activate_binding(**arguments)
    assert cas_failure.value.error_code == "ae.prompt_binding_version_conflict"
    assert store.get_binding(seed.binding_key)["prompt_template_version_id"] == first[
        "prompt_template_version_id"
    ]
    with factory() as session:
        assert session.execute(
            text("SELECT count(*) FROM ae_prompt_binding_history")
        ).scalar_one() == 0


def test_binding_activation_rolls_back_when_history_cannot_be_reloaded(
    monkeypatch,
) -> None:
    factory = session_factory()
    store = SqlAlchemyAePromptRegistryStore(factory)
    seed = AE_PROMPT_SEEDS[0]
    template = store.save_template(build_prompt_template(seed))
    first = store.save_template_version(build_prompt_template_version(seed, template))
    store.save_binding(build_prompt_binding(seed, first))
    second_seed = replace(seed, version="v2", content=f"{seed.content} v2")
    second = store.save_template_version(
        build_prompt_template_version(second_seed, template)
    )
    monkeypatch.setattr(persistence, "_load_binding_history", lambda *args: None)

    with pytest.raises(PromptRepositoryError) as raised:
        store.activate_binding(
            binding_key=seed.binding_key,
            new_prompt_template_version_id=second["prompt_template_version_id"],
            expected_prompt_template_version_id=first[
                "prompt_template_version_id"
            ],
            changed_by="operator",
            reason="history reload",
            correlation_id="history-reload",
        )

    assert raised.value.error_code == "ae.prompt_registry_write_conflict"
    assert store.get_binding(seed.binding_key)["prompt_template_version_id"] == first[
        "prompt_template_version_id"
    ]


def test_prompt_provenance_wraps_database_errors() -> None:
    empty_factory = session_factory()
    store = SqlAlchemyAePromptRegistryStore(empty_factory)

    with pytest.raises(PromptRepositoryError) as missing:
        store.get_prompt_provenance("ae.missing")
    assert missing.value.error_code == "ae.prompt_binding_not_found"
    with empty_factory() as session:
        assert persistence._load_binding_history(session, "missing") is None

    unavailable_store = SqlAlchemyAePromptRegistryStore(
        session_factory(with_schema=False)
    )

    with pytest.raises(PromptRepositoryError) as raised:
        unavailable_store.get_prompt_provenance("ae.missing")

    assert raised.value.error_code == "ae.prompt_registry_unavailable"


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

    expected = (
        "ae.prompt_template_version_write_conflict"
        if method_name == "save_template_version"
        else "ae.prompt_registry_write_conflict"
    )
    assert raised.value.error_code == expected
