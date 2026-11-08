from __future__ import annotations

import inspect
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

import nex_ae_api.agent_identity as identity_module
import pytest
from jsonschema import Draft202012Validator
from nex_ae_api.agent_identity import (
    AgentIdentityRepositoryError,
    ResolvedIaIdentity,
    SqlAlchemyAgentIdentityRegistry,
)
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
FROZEN_SCHEMA = ROOT / (
    "docs/frozen/v2.1/10_PLATFORM_v2.1/03_NORMATIVE_V2_1_CONTRACTS/"
    "NeX_Platform_v2.1_Controlled_Amendment_Batch02_CP02_CP06/AE/"
    "agent-identity-v2.1.schema.json"
)
MIGRATION = ROOT / "database/nex-ae-api/migrations/2001_ae_agent_identity.sql"
NOW = datetime(2026, 10, 13, 1, 2, 3, tzinfo=UTC)


def _session_factory(url: str = "sqlite+pysqlite://"):
    engine = create_engine(
        url,
        future=True,
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys = ON"))
        connection.execute(text("""
            CREATE TABLE ae_agent_identity (
                tenant_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                schema_version TEXT NOT NULL,
                agent_type TEXT NOT NULL,
                profile_ref TEXT NOT NULL,
                status TEXT NOT NULL,
                project_id TEXT,
                created_at TEXT NOT NULL,
                version INTEGER NOT NULL,
                PRIMARY KEY (tenant_id, agent_id)
            )
        """))
        connection.execute(text("""
            CREATE TABLE ae_ia_principal_assignment (
                assignment_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                principal_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                version INTEGER NOT NULL,
                UNIQUE (tenant_id, principal_id),
                UNIQUE (tenant_id, agent_id),
                FOREIGN KEY (tenant_id, agent_id)
                    REFERENCES ae_agent_identity (tenant_id, agent_id)
            )
        """))
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _ids(*values: str):
    items = iter(values)
    lock = Lock()

    def factory() -> str:
        with lock:
            return next(items)

    return factory


def test_lazy_provisioning_is_idempotent_and_matches_frozen_contract() -> None:
    sessions = _session_factory()
    registry = SqlAlchemyAgentIdentityRegistry(
        sessions,
        id_factory=_ids(
            "11111111-1111-4111-8111-111111111111",
            "22222222-2222-4222-8222-222222222222",
        ),
        clock=lambda: NOW,
    )

    first = registry.resolve_or_provision_ia(
        tenant_id="tenant-a",
        principal_id="principal-a",
        profile_ref="urn:nex:agent-profile:ia:default:v1",
    )
    repeated = registry.resolve_or_provision_ia(
        tenant_id="tenant-a",
        principal_id="principal-a",
        profile_ref="urn:nex:agent-profile:ia:ignored-on-replay",
    )

    assert repeated == first
    assert first.identity == {
        "schema_version": "2.1",
        "tenant_id": "tenant-a",
        "agent_id": "11111111-1111-4111-8111-111111111111",
        "agent_type": "IA",
        "profile_ref": "urn:nex:agent-profile:ia:default:v1",
        "status": "ACTIVE",
        "project_id": None,
        "created_at": "2026-10-13T01:02:03Z",
        "version": 1,
    }
    Draft202012Validator(json.loads(FROZEN_SCHEMA.read_text())).validate(
        first.identity
    )
    assert registry.resolve_ia(
        tenant_id="tenant-a", principal_id="principal-a"
    ) == first
    assert registry.resolve_ia(
        tenant_id="tenant-a", principal_id="missing"
    ) is None
    with sessions() as session:
        assert session.execute(text("SELECT count(*) FROM ae_agent_identity")).scalar() == 1
        assert session.execute(
            text("SELECT count(*) FROM ae_ia_principal_assignment")
        ).scalar() == 1


def test_concurrent_lazy_provisioning_keeps_one_identity(tmp_path: Path) -> None:
    sessions = _session_factory(f"sqlite+pysqlite:///{tmp_path / 'identity.db'}")
    registry = SqlAlchemyAgentIdentityRegistry(sessions)

    def resolve() -> str:
        return registry.resolve_or_provision_ia(
            tenant_id="tenant-a",
            principal_id="principal-a",
            profile_ref="urn:nex:agent-profile:ia:default:v1",
        ).identity["agent_id"]

    with ThreadPoolExecutor(max_workers=4) as executor:
        resolved_ids = list(executor.map(lambda _: resolve(), range(8)))

    assert len(set(resolved_ids)) == 1
    with sessions() as session:
        assert session.execute(text("SELECT count(*) FROM ae_agent_identity")).scalar() == 1
        assert session.execute(
            text("SELECT count(*) FROM ae_ia_principal_assignment")
        ).scalar() == 1


@pytest.mark.parametrize(
    ("statement", "error_code"),
    [
        (
            "UPDATE ae_ia_principal_assignment SET status = 'REVOKED'",
            "ae.ia_assignment_inactive",
        ),
        (
            "UPDATE ae_agent_identity SET status = 'SUSPENDED'",
            "ae.ia_identity_ineligible",
        ),
        (
            "UPDATE ae_agent_identity SET agent_type = 'PA', project_id = 'project-a'",
            "ae.ia_identity_ineligible",
        ),
    ],
)
def test_resolution_fails_closed_for_ineligible_assignment(
    statement: str,
    error_code: str,
) -> None:
    sessions = _session_factory()
    registry = SqlAlchemyAgentIdentityRegistry(sessions)
    registry.resolve_or_provision_ia(
        tenant_id="tenant-a",
        principal_id="principal-a",
        profile_ref="profile-a",
    )
    with sessions.begin() as session:
        session.execute(text(statement))

    with pytest.raises(AgentIdentityRepositoryError) as exc_info:
        registry.resolve_ia(tenant_id="tenant-a", principal_id="principal-a")
    assert exc_info.value.error_code == error_code
    assert exc_info.value.retryable is False


def test_invalid_input_and_database_failure_are_typed() -> None:
    registry = SqlAlchemyAgentIdentityRegistry(_session_factory())
    signature = inspect.signature(registry.resolve_or_provision_ia)
    assert "agent_id" not in signature.parameters

    for values in (
        {"tenant_id": "", "principal_id": "p", "profile_ref": "profile"},
        {"tenant_id": "t", "principal_id": " ", "profile_ref": "profile"},
        {"tenant_id": "t", "principal_id": "p", "profile_ref": ""},
    ):
        with pytest.raises(AgentIdentityRepositoryError) as exc_info:
            registry.resolve_or_provision_ia(**values)
        assert exc_info.value.error_code == "ae.agent_identity_input_invalid"

    empty_engine = create_engine("sqlite+pysqlite://", future=True)
    unavailable = SqlAlchemyAgentIdentityRegistry(sessionmaker(bind=empty_engine))
    for operation in (
        lambda: unavailable.resolve_ia(tenant_id="t", principal_id="p"),
        lambda: unavailable.resolve_or_provision_ia(
            tenant_id="t", principal_id="p", profile_ref="profile"
        ),
    ):
        with pytest.raises(AgentIdentityRepositoryError) as exc_info:
            operation()
        assert exc_info.value.error_code == "ae.agent_identity_store_unavailable"
        assert exc_info.value.retryable is True
        assert str(exc_info.value) == "AE agent identity store is unavailable."


def test_provisioning_fails_retryably_when_assignment_cannot_be_reloaded(
    monkeypatch,
) -> None:
    registry = SqlAlchemyAgentIdentityRegistry(_session_factory())
    monkeypatch.setattr(identity_module, "_load_resolution", lambda *args: None)

    with pytest.raises(AgentIdentityRepositoryError) as exc_info:
        registry.resolve_or_provision_ia(
            tenant_id="tenant-a",
            principal_id="principal-a",
            profile_ref="profile-a",
        )

    assert exc_info.value.error_code == "ae.ia_assignment_write_conflict"
    assert exc_info.value.retryable is True


def test_assignment_race_discards_candidate_and_reloads_winner(monkeypatch) -> None:
    sessions = _session_factory()
    winner = SqlAlchemyAgentIdentityRegistry(
        sessions,
        id_factory=_ids(
            "11111111-1111-4111-8111-111111111111",
            "22222222-2222-4222-8222-222222222222",
        ),
        clock=lambda: NOW,
    ).resolve_or_provision_ia(
        tenant_id="tenant-a",
        principal_id="principal-a",
        profile_ref="winner-profile",
    )
    real_load = identity_module._load_resolution
    first_load = True

    def miss_once(*args):
        nonlocal first_load
        if first_load:
            first_load = False
            return None
        return real_load(*args)

    monkeypatch.setattr(identity_module, "_load_resolution", miss_once)
    contender = SqlAlchemyAgentIdentityRegistry(
        sessions,
        id_factory=_ids(
            "33333333-3333-4333-8333-333333333333",
            "44444444-4444-4444-8444-444444444444",
        ),
        clock=lambda: NOW,
    )

    resolved = contender.resolve_or_provision_ia(
        tenant_id="tenant-a",
        principal_id="principal-a",
        profile_ref="loser-profile",
    )

    assert resolved == winner
    with sessions() as session:
        assert session.execute(text("SELECT count(*) FROM ae_agent_identity")).scalar() == 1


def test_provisioning_preserves_typed_identity_validation_failure(monkeypatch) -> None:
    calls = 0

    def load(*args):
        nonlocal calls
        calls += 1
        if calls == 1:
            return None
        return ResolvedIaIdentity(
            identity={
                "agent_type": "IA",
                "status": "SUSPENDED",
                "project_id": None,
            },
            assignment={"status": "ACTIVE"},
        )

    registry = SqlAlchemyAgentIdentityRegistry(_session_factory())
    monkeypatch.setattr(identity_module, "_load_resolution", load)

    with pytest.raises(AgentIdentityRepositoryError) as exc_info:
        registry.resolve_or_provision_ia(
            tenant_id="tenant-a",
            principal_id="principal-a",
            profile_ref="profile-a",
        )
    assert exc_info.value.error_code == "ae.ia_identity_ineligible"


def test_datetime_value_normalizes_datetime_instances() -> None:
    assert identity_module._datetime_value(NOW) == "2026-10-13T01:02:03Z"


def test_migration_uses_canonical_names_and_constraints() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS ae_agent_identity" in sql
    assert "CREATE TABLE IF NOT EXISTS ae_ia_principal_assignment" in sql
    assert "ae_ia_identities" not in sql
    assert "UNIQUE (tenant_id, principal_id)" in sql
    assert "UNIQUE (tenant_id, agent_id)" in sql
    assert "agent_type = 'IA' AND project_id IS NULL" in sql
    assert "2001_ae_agent_identity" in sql
