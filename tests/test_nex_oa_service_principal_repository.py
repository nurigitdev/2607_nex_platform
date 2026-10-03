from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from nex_oa.service_principal_repository import (
    InMemoryOaServicePrincipalRepository,
    SqlAlchemyOaServicePrincipalRepository,
    build_service_principal_repository_for_runtime,
)
from nex_oa.service_principals import OaServicePrincipalError
from nex_runtime import PERSISTENCE_MODE_POSTGRES


def _principal(revision: int = 1, previous: int = 0) -> dict[str, object]:
    return {
        "principal_schema_version": "oa_service_principal.v1",
        "principal_id": "ae-runtime",
        "service_id": "nex-ae-api",
        "display_name": "AE Runtime",
        "status": "ACTIVE",
        "allowed_audiences": ("nex-cx", "nex-oa"),
        "allowed_scopes": ("document:read",),
        "previous_revision": previous,
        "revision": revision,
    }


def _credential(identifier: str = "cred-1", **overrides: object) -> dict[str, object]:
    return {
        "credential_schema_version": "oa_service_credential.v1",
        "credential_id": identifier,
        "principal_id": "ae-runtime",
        "secret_hash": "$argon2id$v=19$m=65536,t=3,p=4$hash",
        "secret_hint": identifier[-4:],
        "status": "ACTIVE",
        "issued_at": 1_000,
        "expires_at": 2_000,
        "grace_until": None,
        "previous_revision": 0,
        "revision": 1,
        **overrides,
    }


def test_in_memory_repository_round_trip_filters_and_revision_guards() -> None:
    repository = InMemoryOaServicePrincipalRepository()
    repository.save_principal(_principal())
    repository.create_credential(_credential())

    assert repository.get_principal("AE-RUNTIME")["service_id"] == "nex-ae-api"
    assert len(repository.list_principals()) == 1
    assert len(repository.list_principals(service_id="NEX-AE-API")) == 1
    assert repository.list_principals(service_id="nex-cx") == []
    assert repository.get_credential("cred-1")["secret_hint"] == "ed-1"
    assert len(repository.list_credentials(principal_id="ae-runtime")) == 1
    assert repository.active_credential_count(principal_id="ae-runtime", at_epoch=1_500) == 1
    assert repository.active_credential_count(principal_id="ae-runtime", at_epoch=2_000) == 0

    updated = repository.save_principal(_principal(revision=2, previous=1))
    transitioned = repository.save_credential(
        {
            "credential_id": "cred-1",
            "status": "REVOKED",
            "grace_until": None,
            "previous_revision": 1,
            "revision": 2,
        }
    )
    assert updated["revision"] == 2
    assert transitioned["status"] == "REVOKED"

    with pytest.raises(OaServicePrincipalError, match="changed"):
        repository.save_principal(_principal(revision=100, previous=99))
    with pytest.raises(OaServicePrincipalError, match="changed"):
        repository.save_credential(
            {"credential_id": "cred-1", "previous_revision": 1, "revision": 3}
        )


def test_in_memory_repository_rejects_missing_duplicate_and_active_limit() -> None:
    repository = InMemoryOaServicePrincipalRepository()
    assert repository.get_principal("missing") is None
    assert repository.get_credential("missing") is None
    with pytest.raises(OaServicePrincipalError) as missing:
        repository.create_credential(_credential())
    assert missing.value.status_code == 404

    repository.save_principal(_principal())
    repository.create_credential(_credential("cred-1", expires_at=5_000))
    with pytest.raises(OaServicePrincipalError, match="already exists"):
        repository.create_credential(_credential("cred-1"))
    repository.create_credential(_credential("cred-2", expires_at=5_000))
    with pytest.raises(OaServicePrincipalError) as limit:
        repository.create_credential(_credential("cred-3", expires_at=5_000))
    assert limit.value.error_code == "oa.service_credential_active_limit"
    with pytest.raises(OaServicePrincipalError) as absent:
        repository.save_credential({"credential_id": "missing", "revision": 2})
    assert absent.value.status_code == 404


def _sqlite_repository() -> tuple[SqlAlchemyOaServicePrincipalRepository, sessionmaker]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE oa_service_principals (principal_id TEXT PRIMARY KEY, principal_schema_version TEXT, service_id TEXT, display_name TEXT, status TEXT, allowed_audiences TEXT, allowed_scopes TEXT, revision INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        connection.execute(text("CREATE TABLE oa_service_creds (credential_id TEXT PRIMARY KEY, credential_schema_version TEXT, principal_id TEXT, secret_hash TEXT, secret_hint TEXT, status TEXT, issued_at TIMESTAMP, expires_at TIMESTAMP, grace_until TIMESTAMP, last_used_at TIMESTAMP, revision INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return SqlAlchemyOaServicePrincipalRepository(factory), factory


def test_sqlalchemy_repository_round_trip_restart_and_filters() -> None:
    repository, factory = _sqlite_repository()
    repository.save_principal(_principal())
    repository.create_credential(_credential())
    restarted = SqlAlchemyOaServicePrincipalRepository(factory)

    principal = restarted.get_principal("ae-runtime")
    credential = restarted.get_credential("cred-1")
    assert principal["allowed_audiences"] == ["nex-cx", "nex-oa"]
    assert credential["issued_at"] == 1_000
    assert len(restarted.list_principals()) == 1
    assert len(restarted.list_principals(service_id="nex-ae-api")) == 1
    assert len(restarted.list_credentials(principal_id="ae-runtime")) == 1
    assert restarted.active_credential_count(principal_id="ae-runtime", at_epoch=1_500) == 1

    restarted.save_principal(_principal(revision=2, previous=1))
    restarted.save_credential(
        {
            "credential_id": "cred-1",
            "status": "ROTATING",
            "grace_until": 1_800,
            "previous_revision": 1,
            "revision": 2,
        }
    )
    assert restarted.get_credential("cred-1")["grace_until"] == 1_800


def test_sqlalchemy_repository_guards_missing_limit_and_stale_writes() -> None:
    repository, _ = _sqlite_repository()
    with pytest.raises(OaServicePrincipalError) as missing:
        repository.create_credential(_credential())
    assert missing.value.status_code == 404
    repository.save_principal(_principal())
    repository.create_credential(_credential("cred-1", expires_at=5_000))
    repository.create_credential(_credential("cred-2", expires_at=5_000))
    with pytest.raises(OaServicePrincipalError) as limit:
        repository.create_credential(_credential("cred-3", expires_at=5_000))
    assert limit.value.error_code == "oa.service_credential_active_limit"
    with pytest.raises(OaServicePrincipalError, match="changed"):
        repository.save_principal(_principal(revision=100, previous=99))
    with pytest.raises(OaServicePrincipalError, match="changed"):
        repository.save_credential(
            {"credential_id": "missing", "status": "REVOKED", "revision": 2, "previous_revision": 1}
        )


def test_sqlalchemy_repository_maps_integrity_and_database_errors(monkeypatch) -> None:
    repository, factory = _sqlite_repository()
    repository.save_principal(_principal())
    with pytest.raises(OaServicePrincipalError) as conflict:
        repository.save_principal(_principal())
    assert conflict.value.status_code == 409

    with pytest.raises(OaServicePrincipalError) as credential_conflict:
        repository.create_credential(_credential())
        repository.create_credential(_credential())
    assert credential_conflict.value.status_code == 409

    with pytest.raises(OaServicePrincipalError, match="changed"):
        repository.save_credential(
            {
                "credential_id": "cred-1",
                "status": "REVOKED",
                "grace_until": None,
                "revision": 100,
                "previous_revision": 99,
            }
        )

    with factory.begin() as connection:
        connection.execute(text("DROP TABLE oa_service_creds"))
    with pytest.raises(OaServicePrincipalError) as read_error:
        repository.list_credentials(principal_id="ae-runtime")
    assert read_error.value.status_code == 503
    with pytest.raises(OaServicePrincipalError) as count_error:
        repository.active_credential_count(principal_id="ae-runtime", at_epoch=1_000)
    assert count_error.value.status_code == 503
    with pytest.raises(OaServicePrincipalError) as create_error:
        repository.create_credential(_credential("cred-2"))
    assert create_error.value.status_code == 503
    with pytest.raises(OaServicePrincipalError) as save_error:
        repository.save_credential(
            {
                "credential_id": "cred-1",
                "status": "REVOKED",
                "grace_until": None,
                "revision": 2,
                "previous_revision": 1,
            }
        )
    assert save_error.value.status_code == 503

    with factory.begin() as connection:
        connection.execute(text("DROP TABLE oa_service_principals"))
    with pytest.raises(OaServicePrincipalError) as principal_error:
        repository.save_principal(_principal(revision=2, previous=1))
    assert principal_error.value.status_code == 503

    repository, _ = _sqlite_repository()
    repository.save_principal(_principal())
    monkeypatch.setattr(
        repository,
        "_session_factory",
        lambda: (_ for _ in ()).throw(SQLAlchemyError("offline")),
    )
    with pytest.raises(SQLAlchemyError):
        repository.create_credential(_credential())


def test_repository_builder_and_timestamp_helpers() -> None:
    class Runtime:
        mode = "memory"
        api_session_factory = None

    assert isinstance(
        build_service_principal_repository_for_runtime(Runtime()),
        InMemoryOaServicePrincipalRepository,
    )
    _, factory = _sqlite_repository()
    Runtime.mode = PERSISTENCE_MODE_POSTGRES
    Runtime.api_session_factory = factory
    assert isinstance(
        build_service_principal_repository_for_runtime(Runtime()),
        SqlAlchemyOaServicePrincipalRepository,
    )

    import nex_oa.service_principal_repository as module

    aware = datetime(2026, 1, 1, tzinfo=UTC)
    naive = datetime(2026, 1, 1)
    assert module._timestamp(aware) is aware
    assert module._timestamp(naive).tzinfo is UTC
    assert module._timestamp(None) is None
    assert module._epoch(aware.isoformat()) == module._epoch(aware)
    assert module._epoch(1000) == 1000

    class Dialect:
        name = "postgresql"

    class Bind:
        dialect = Dialect()

    class Session:
        bind = Bind()

    session = Session()
    assert module._json_value(session, "value") == "CAST(:value AS JSONB)"  # type: ignore[arg-type]
    assert module._principal_lock_suffix(session) == " FOR UPDATE"  # type: ignore[arg-type]
    assert module._decode_row({"value": {}}, ("value",), ()) == {"value": {}}
