from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from nex_oa.federated_identities import (
    OaFederationError,
    build_external_identity_link,
    build_federation_provider,
)
from nex_oa.federated_identity_repository import (
    InMemoryOaFederatedIdentityRepository,
    SqlAlchemyOaFederatedIdentityRepository,
    build_federated_identity_repository_for_runtime,
)
from nex_runtime import PERSISTENCE_MODE_POSTGRES
import run_oa_federated_identity_persistence as runner


NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _records() -> tuple[dict[str, object], dict[str, object]]:
    provider = build_federation_provider(
        {
            "provider_id": "company-oidc",
            "issuer": "https://id.example.test",
            "client_id": "nex-platform",
            "discovery_url": "https://id.example.test/.well-known/openid-configuration",
            "display_name": "Company OIDC",
        },
        now=NOW,
    )
    identity = build_external_identity_link(
        {
            "provider_id": "company-oidc",
            "external_subject": "opaque-subject",
            "tenant_id": "company",
            "subject_id": "employee-1001",
        },
        provider=provider,
        now=NOW,
    )
    return provider, identity


def test_in_memory_repository_round_trip_filters_and_guards() -> None:
    provider, identity = _records()
    repository = InMemoryOaFederatedIdentityRepository()
    assert repository.get_provider("missing") is None
    assert repository.find_identity(provider_id="company-oidc", external_subject_digest="0" * 64) is None

    repository.save_provider(provider)
    repository.save_identity(identity)
    assert repository.get_provider("company-oidc") == provider
    assert len(repository.list_providers()) == 1
    assert len(repository.list_identities()) == 1
    assert len(repository.list_identities(provider_id="company-oidc")) == 1
    assert len(repository.list_identities(tenant_id="company")) == 1
    assert repository.list_identities(provider_id="other") == []

    updated_provider = {
        **provider,
        "status": "DISABLED",
        "previous_revision": 1,
        "revision": 2,
    }
    updated_identity = {
        **identity,
        "status": "DISABLED",
        "previous_revision": 1,
        "revision": 2,
    }
    assert repository.save_provider(updated_provider)["status"] == "DISABLED"
    assert repository.save_identity(updated_identity)["status"] == "DISABLED"
    assert "previous_revision" not in repository.get_provider("company-oidc")

    with pytest.raises(OaFederationError, match="changed"):
        repository.save_provider({**provider, "previous_revision": 1, "revision": 3})
    with pytest.raises(OaFederationError, match="changed"):
        repository.save_identity({**identity, "previous_revision": 1, "revision": 3})


def test_in_memory_repository_rejects_missing_provider_and_remap() -> None:
    provider, identity = _records()
    repository = InMemoryOaFederatedIdentityRepository()
    with pytest.raises(OaFederationError) as missing:
        repository.save_identity(identity)
    assert missing.value.status_code == 404
    repository.save_provider(provider)
    repository.save_identity(identity)
    with pytest.raises(OaFederationError, match="remapping"):
        repository.save_identity(
            {
                **identity,
                "subject_id": "employee-2002",
                "previous_revision": 1,
                "revision": 2,
            }
        )


def _sqlite_repository() -> tuple[SqlAlchemyOaFederatedIdentityRepository, sessionmaker]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE oa_fed_providers (provider_id TEXT PRIMARY KEY, provider_schema_version TEXT, issuer TEXT UNIQUE, client_id TEXT, discovery_url TEXT, display_name TEXT, status TEXT, revision INTEGER, created_at TEXT, updated_at TEXT)"))
        connection.execute(text("CREATE TABLE oa_fed_identities (provider_id TEXT, external_subject_digest TEXT, identity_schema_version TEXT, tenant_id TEXT, subject_ref_type TEXT, subject_id TEXT, status TEXT, revision INTEGER, created_at TEXT, updated_at TEXT, PRIMARY KEY (provider_id, external_subject_digest), UNIQUE (provider_id, tenant_id, subject_id))"))
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return SqlAlchemyOaFederatedIdentityRepository(factory), factory


def test_sqlalchemy_repository_round_trip_restart_updates_and_filters() -> None:
    provider, identity = _records()
    repository, factory = _sqlite_repository()
    repository.save_provider(provider)
    repository.save_identity(identity)
    restarted = SqlAlchemyOaFederatedIdentityRepository(factory)

    assert restarted.get_provider("company-oidc")["issuer"] == provider["issuer"]
    assert restarted.find_identity(
        provider_id="company-oidc",
        external_subject_digest=identity["external_subject_digest"],
    )["subject_id"] == "employee-1001"
    assert len(restarted.list_providers()) == 1
    assert len(restarted.list_identities()) == 1
    assert len(restarted.list_identities(provider_id="company-oidc", tenant_id="company")) == 1

    restarted.save_provider({**provider, "status": "DISABLED", "previous_revision": 1, "revision": 2})
    restarted.save_identity({**identity, "status": "DISABLED", "previous_revision": 1, "revision": 2})
    assert restarted.get_provider("company-oidc")["status"] == "DISABLED"
    assert restarted.list_identities(tenant_id="other") == []


def test_sqlalchemy_repository_maps_conflicts_stale_writes_and_outage() -> None:
    provider, identity = _records()
    repository, factory = _sqlite_repository()
    repository.save_provider(provider)
    with pytest.raises(OaFederationError) as duplicate:
        repository.save_provider(provider)
    assert duplicate.value.status_code == 409
    repository.save_identity(identity)
    with pytest.raises(OaFederationError) as identity_duplicate:
        repository.save_identity(identity)
    assert identity_duplicate.value.status_code == 409
    with pytest.raises(OaFederationError, match="changed"):
        repository.save_provider({**provider, "previous_revision": 99, "revision": 100})
    with pytest.raises(OaFederationError, match="changed"):
        repository.save_identity({**identity, "previous_revision": 99, "revision": 100})

    with factory.begin() as connection:
        connection.execute(text("DROP TABLE oa_fed_identities"))
    with pytest.raises(OaFederationError) as unavailable:
        repository.list_identities()
    assert unavailable.value.status_code == 503
    with pytest.raises(OaFederationError):
        repository.save_identity(identity)

    with factory.begin() as connection:
        connection.execute(text("DROP TABLE oa_fed_providers"))
    with pytest.raises(OaFederationError):
        repository.list_providers()
    with pytest.raises(OaFederationError):
        repository.save_provider({**provider, "previous_revision": 1, "revision": 2})


def test_repository_builder_validation_and_decode_helpers() -> None:
    class Runtime:
        mode = "memory"
        api_session_factory = None

    assert isinstance(
        build_federated_identity_repository_for_runtime(Runtime()),
        InMemoryOaFederatedIdentityRepository,
    )
    Runtime.mode = PERSISTENCE_MODE_POSTGRES
    with pytest.raises(RuntimeError):
        build_federated_identity_repository_for_runtime(Runtime())
    repository, factory = _sqlite_repository()
    Runtime.api_session_factory = factory
    assert isinstance(
        build_federated_identity_repository_for_runtime(Runtime()),
        SqlAlchemyOaFederatedIdentityRepository,
    )

    import nex_oa.federated_identity_repository as module

    with pytest.raises(OaFederationError):
        module._required_value(" spaced ", "provider_id")
    with pytest.raises(OaFederationError):
        module._digest("not-a-digest")
    decoded = module._decode_row(
        {"created_at": datetime(2026, 1, 1), "updated_at": NOW}
    )
    assert decoded["created_at"] == "2026-01-01T00:00:00Z"
    assert decoded["updated_at"] == "2026-01-01T00:00:00Z"
    assert repository.list_providers() == []


def test_persistence_smoke_empty_repository_and_cli(monkeypatch, capsys, tmp_path) -> None:
    evidence = runner.run_oa_federated_identity_persistence()
    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert evidence["summary"]["table_count"] == 2
    assert runner.summary_line(evidence).startswith(
        "oa_federated_identity_persistence=pass checks=13/13 tables=2"
    )
    empty = runner.run_oa_federated_identity_persistence(tmp_path)
    assert empty["status"] == "FAIL"
    assert empty["summary"]["table_count"] == 0
    assert runner._table_body("", "missing") == ""
    monkeypatch.setattr(runner, "run_oa_federated_identity_persistence", lambda: evidence)
    assert runner.main(["--summary"]) == 0
    assert "next=1285" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        runner, "run_oa_federated_identity_persistence", lambda: {"status": "FAIL"}
    )
    assert runner.main([]) == 1
