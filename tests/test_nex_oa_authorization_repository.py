from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from nex_oa.authorization import OaAuthorizationError
from nex_oa.authorization_repository import (
    InMemoryOaAuthorizationRepository,
    SqlAlchemyOaAuthorizationRepository,
    bind_authorization_session_registry,
    build_authorization_repository_for_runtime,
)
from nex_oa.memberships import InMemoryOaTenantMembershipRegistry
from nex_oa.sessions import InMemoryOaSessionRegistry
import nex_oa.authorization_repository as repository_module
from nex_runtime import PERSISTENCE_MODE_POSTGRES


CONTEXT = {"actor_ref": "nex.service:test", "request_id": "req-1", "trace_id": "trace-1"}


def _populate(repository) -> None:
    repository.upsert_role(
        {"tenant_id": "tenant-a", "role_id": "editor", "scopes": ["doc:read"], "expected_revision": 0},
        context=CONTEXT,
    )
    repository.upsert_group(
        {"tenant_id": "tenant-a", "group_id": "engineering", "expected_revision": 0},
        context=CONTEXT,
    )
    repository.upsert_group_member(
        {"tenant_id": "tenant-a", "group_id": "engineering", "subject_id": "user-a", "expected_revision": 0},
        context=CONTEXT,
    )
    repository.upsert_group_role(
        {"tenant_id": "tenant-a", "group_id": "engineering", "role_id": "editor", "expected_revision": 0},
        context=CONTEXT,
    )


def test_in_memory_repository_is_revisioned_isolated_and_append_only() -> None:
    repository = InMemoryOaAuthorizationRepository()
    _populate(repository)

    role = repository.upsert_role(
        {"tenant_id": "tenant-a", "role_id": "editor", "scopes": ["doc:write"], "expected_revision": 1},
        context=CONTEXT,
    )
    snapshot = repository.authorization_inputs(tenant_id="tenant-a", subject_id="user-a")
    assert role["record"]["revision"] == 2
    assert role["event"]["previous_revision"] == 1
    assert {key: len(value) for key, value in snapshot.items()} == {
        "roles": 1,
        "groups": 1,
        "group_members": 1,
        "group_roles": 1,
    }
    assert len(repository.list_events(tenant_id="tenant-a", limit=2)) == 2
    assert repository.authorization_inputs(tenant_id="tenant-b", subject_id="user-a")["roles"] == []


def test_in_memory_repository_rejects_missing_references_and_bad_context() -> None:
    repository = InMemoryOaAuthorizationRepository()
    with pytest.raises(OaAuthorizationError, match="group"):
        repository.upsert_group_member(
            {"tenant_id": "tenant-a", "group_id": "missing", "subject_id": "user-a"},
            context=CONTEXT,
        )
    repository.upsert_group(
        {"tenant_id": "tenant-a", "group_id": "engineering"}, context=CONTEXT
    )
    with pytest.raises(OaAuthorizationError, match="role"):
        repository.upsert_group_role(
            {"tenant_id": "tenant-a", "group_id": "engineering", "role_id": "missing"},
            context=CONTEXT,
        )
    with pytest.raises(OaAuthorizationError, match="actor_ref"):
        repository.upsert_role(
            {"tenant_id": "tenant-a", "role_id": "editor", "scopes": ["doc:read"]},
            context={},
        )


def _sqlite_repository() -> tuple[SqlAlchemyOaAuthorizationRepository, sessionmaker]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE oa_tenants (tenant_id TEXT PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE oa_tenant_memberships (tenant_id TEXT, subject_ref_type TEXT, subject_id TEXT, PRIMARY KEY (tenant_id, subject_ref_type, subject_id))"))
        connection.execute(text("INSERT INTO oa_tenants VALUES ('tenant-a')"))
        connection.execute(text("INSERT INTO oa_tenant_memberships VALUES ('tenant-a', 'oa.user', 'user-a')"))
        connection.execute(text("CREATE TABLE oa_roles (tenant_id TEXT, role_id TEXT, role_schema_version TEXT, display_name TEXT, description TEXT, status TEXT, revision INTEGER, scopes TEXT, metadata TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (tenant_id, role_id), FOREIGN KEY (tenant_id) REFERENCES oa_tenants(tenant_id))"))
        connection.execute(text("CREATE TABLE oa_groups (tenant_id TEXT, group_id TEXT, group_schema_version TEXT, display_name TEXT, description TEXT, status TEXT, revision INTEGER, metadata TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (tenant_id, group_id), FOREIGN KEY (tenant_id) REFERENCES oa_tenants(tenant_id))"))
        connection.execute(text("CREATE TABLE oa_group_members (tenant_id TEXT, group_id TEXT, subject_ref_type TEXT, subject_id TEXT, status TEXT, revision INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (tenant_id, group_id, subject_id))"))
        connection.execute(text("CREATE TABLE oa_group_roles (tenant_id TEXT, group_id TEXT, role_id TEXT, status TEXT, revision INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (tenant_id, group_id, role_id))"))
        connection.execute(text("CREATE TABLE oa_user_sessions (session_id TEXT PRIMARY KEY, tenant_id TEXT, subject_id TEXT, status TEXT, revoked_at TEXT, updated_at TEXT)"))
        connection.execute(text("CREATE TABLE oa_authz_events (event_id TEXT PRIMARY KEY, event_schema_version TEXT, tenant_id TEXT, event_type TEXT, entity_type TEXT, entity_id TEXT, subject_id TEXT, previous_revision INTEGER, next_revision INTEGER, actor_ref TEXT, request_id TEXT, trace_id TEXT, details TEXT, occurred_at TEXT)"))
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return SqlAlchemyOaAuthorizationRepository(factory), factory


def test_sqlalchemy_repository_round_trip_and_restart() -> None:
    repository, factory = _sqlite_repository()
    _populate(repository)
    restarted = SqlAlchemyOaAuthorizationRepository(factory)
    snapshot = restarted.authorization_inputs(tenant_id="tenant-a", subject_id="user-a")
    events = restarted.list_events(tenant_id="tenant-a")

    assert snapshot["roles"][0]["scopes"] == ["doc:read"]
    assert snapshot["groups"][0]["metadata"] == {}
    assert len(events) == 4
    assert events[0]["details"] == {
        "status": "ACTIVE",
        "revoked_session_count": 0,
    }

    updated = restarted.upsert_group(
        {"tenant_id": "tenant-a", "group_id": "engineering", "display_name": "Engineering Team", "expected_revision": 1},
        context=CONTEXT,
    )
    assert updated["record"]["revision"] == 2


def test_sqlalchemy_repository_revokes_sessions_atomically(monkeypatch) -> None:
    repository, factory = _sqlite_repository()
    _populate(repository)
    with factory.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO oa_user_sessions "
                "(session_id, tenant_id, subject_id, status) "
                "VALUES ('session-a', 'tenant-a', 'user-a', 'ACTIVE')"
            )
        )

    updated = repository.upsert_role(
        {
            "tenant_id": "tenant-a",
            "role_id": "editor",
            "scopes": ["doc:read", "doc:write"],
            "expected_revision": 1,
        },
        context=CONTEXT,
    )
    assert updated["affected_subject_ids"] == ["user-a"]
    assert updated["revoked_session_count"] == 1
    with factory() as session:
        assert session.execute(
            text("SELECT status FROM oa_user_sessions WHERE session_id = 'session-a'")
        ).scalar_one() == "REVOKED"

    with factory.begin() as connection:
        connection.execute(
            text(
                "UPDATE oa_user_sessions SET status = 'ACTIVE', revoked_at = NULL "
                "WHERE session_id = 'session-a'"
            )
        )
    monkeypatch.setattr(
        repository_module,
        "_insert_event",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(SQLAlchemyError("event")),
    )
    with pytest.raises(OaAuthorizationError) as unavailable:
        repository.upsert_role(
            {
                "tenant_id": "tenant-a",
                "role_id": "editor",
                "scopes": ["doc:read"],
                "expected_revision": 2,
            },
            context=CONTEXT,
        )
    assert unavailable.value.status_code == 503
    with factory() as session:
        assert session.execute(
            text("SELECT status FROM oa_user_sessions WHERE session_id = 'session-a'")
        ).scalar_one() == "ACTIVE"


def test_sqlalchemy_repository_maps_validation_and_write_errors(monkeypatch) -> None:
    repository, factory = _sqlite_repository()
    with pytest.raises(OaAuthorizationError) as missing:
        repository.authorization_inputs(tenant_id="", subject_id="user-a")
    assert missing.value.status_code == 400

    repository.upsert_role(
        {"tenant_id": "tenant-a", "role_id": "editor", "scopes": ["doc:read"]},
        context=CONTEXT,
    )
    with pytest.raises(OaAuthorizationError) as stale:
        repository.upsert_role(
            {
                "tenant_id": "tenant-a",
                "role_id": "editor",
                "scopes": ["doc:write"],
                "expected_revision": 0,
            },
            context=CONTEXT,
        )
    assert stale.value.status_code == 409

    monkeypatch.setattr(
        repository_module,
        "_insert_record",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            IntegrityError("insert", {}, RuntimeError("fk"))
        ),
    )
    with pytest.raises(OaAuthorizationError) as integrity:
        repository.upsert_role(
            {
                "tenant_id": "tenant-a",
                "role_id": "editor-integrity",
                "scopes": ["doc:read"],
            },
            context=CONTEXT,
        )
    assert integrity.value.status_code == 409

    monkeypatch.setattr(
        repository_module,
        "_insert_record",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(SQLAlchemyError("write")),
    )
    with pytest.raises(OaAuthorizationError) as unavailable:
        repository.upsert_role(
            {
                "tenant_id": "tenant-a",
                "role_id": "editor-unavailable",
                "scopes": ["doc:read"],
            },
            context=CONTEXT,
        )
    assert unavailable.value.status_code == 503


def test_sqlalchemy_repository_maps_read_errors() -> None:
    repository, factory = _sqlite_repository()
    with factory.begin() as connection:
        connection.execute(text("DROP TABLE oa_roles"))
    with pytest.raises(OaAuthorizationError) as inputs_error:
        repository.authorization_inputs(tenant_id="tenant-a", subject_id="user-a")
    assert inputs_error.value.status_code == 503

    repository, factory = _sqlite_repository()
    with factory.begin() as connection:
        connection.execute(text("DROP TABLE oa_authz_events"))
    with pytest.raises(OaAuthorizationError) as events_error:
        repository.list_events(tenant_id="tenant-a")
    assert events_error.value.status_code == 503


def test_sql_update_revision_guard_and_helper_branches() -> None:
    repository, factory = _sqlite_repository()
    _populate(repository)
    with factory() as session:
        record = {
            "tenant_id": "tenant-a",
            "role_id": "editor",
            "role_schema_version": "oa_role.v1",
            "display_name": "editor",
            "description": None,
            "status": "ACTIVE",
            "revision": 100,
            "previous_revision": 99,
            "scopes": ("doc:write",),
            "metadata": {},
        }
        with pytest.raises(OaAuthorizationError, match="changed"):
            repository_module._update_record(
                session,
                config=repository_module._CONFIGS["ROLE"],
                record=record,
            )

    aware = repository_module._wire_event({"occurred_at": datetime(2026, 1, 1, tzinfo=UTC)})
    naive = repository_module._wire_event({"occurred_at": datetime(2026, 1, 1)})
    assert aware["occurred_at"].endswith("Z")
    assert naive["occurred_at"].endswith("Z")
    assert repository_module._decode_row({"metadata": {}}, ("metadata",)) == {"metadata": {}}

    class Dialect:
        name = "postgresql"

    class Bind:
        dialect = Dialect()

    class Session:
        bind = Bind()

    assert repository_module._json_expression(Session(), "details") == "CAST(:details AS JSONB)"  # type: ignore[arg-type]


@pytest.mark.parametrize("limit", [True, 0, 501, "01", "x"])
def test_event_limit_rejects_invalid_values(limit) -> None:
    repository = InMemoryOaAuthorizationRepository()
    with pytest.raises(OaAuthorizationError, match="limit"):
        repository.list_events(tenant_id="tenant-a", limit=limit)


def test_runtime_builder_selects_memory_and_postgres() -> None:
    class Runtime:
        mode = "memory"
        api_session_factory = None

    assert isinstance(build_authorization_repository_for_runtime(Runtime()), InMemoryOaAuthorizationRepository)  # type: ignore[arg-type]
    _, factory = _sqlite_repository()
    Runtime.mode = PERSISTENCE_MODE_POSTGRES
    Runtime.api_session_factory = factory
    assert isinstance(build_authorization_repository_for_runtime(Runtime()), SqlAlchemyOaAuthorizationRepository)  # type: ignore[arg-type]


def test_unknown_entity_and_incompatible_session_binding_are_safe() -> None:
    repository = InMemoryOaAuthorizationRepository()
    assert repository._affected_subject_ids(
        "UNKNOWN", {"tenant_id": "tenant-a"}
    ) == ()
    assert repository_module._select_affected_subject_ids(
        None,  # type: ignore[arg-type]
        entity_type="UNKNOWN",
        record={"tenant_id": "tenant-a"},
    ) == ()

    bind_authorization_session_registry(repository, object())
    assert repository.session_registry is None
    sessions = InMemoryOaSessionRegistry(InMemoryOaTenantMembershipRegistry())
    bind_authorization_session_registry(repository, sessions)
    assert repository.session_registry is sessions
