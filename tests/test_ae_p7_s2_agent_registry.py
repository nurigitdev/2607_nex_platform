from __future__ import annotations

from datetime import UTC, datetime
from threading import Lock

import pytest
import nex_ae_api.agent_identity as identity_module
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token
from nex_ae_api.agent_identity import (
    AgentIdentityRepositoryError,
    SqlAlchemyAgentIdentityRegistry,
)
from nex_ae_api.agent_registry_api import register_agent_registry_routes


NOW = datetime(2026, 10, 18, 3, 0, tzinfo=UTC)


def _sessions():
    engine = create_engine(
        "sqlite+pysqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE ae_agent_identity (
                tenant_id TEXT NOT NULL, agent_id TEXT NOT NULL,
                schema_version TEXT NOT NULL, agent_type TEXT NOT NULL,
                profile_ref TEXT NOT NULL, status TEXT NOT NULL,
                project_id TEXT, created_at TEXT NOT NULL,
                version INTEGER NOT NULL,
                PRIMARY KEY (tenant_id, agent_id)
            )
        """))
        connection.execute(text("""
            CREATE UNIQUE INDEX ux_ae_active_pa_project
            ON ae_agent_identity (tenant_id, project_id)
            WHERE agent_type = 'PA' AND status = 'ACTIVE'
        """))
    return sessionmaker(bind=engine, expire_on_commit=False)


def _ids():
    values = iter(
        (
            "11111111-1111-4111-8111-111111111111",
            "22222222-2222-4222-8222-222222222222",
            "33333333-3333-4333-8333-333333333333",
            "44444444-4444-4444-8444-444444444444",
        )
    )
    lock = Lock()

    def factory():
        with lock:
            return next(values)

    return factory


def _registry():
    return SqlAlchemyAgentIdentityRegistry(
        _sessions(), id_factory=_ids(), clock=lambda: NOW
    )


def test_s2_register_list_status_and_active_pa_lifecycle():
    registry = _registry()
    ca = registry.register_agent(
        tenant_id="tenant-a", agent_type="CA", profile_ref="profile-ca"
    )
    pa = registry.register_agent(
        tenant_id="tenant-a",
        agent_type="PA",
        profile_ref="profile-pa",
        project_id="project-a",
    )
    ea = registry.register_agent(
        tenant_id="tenant-a",
        agent_type="EA",
        profile_ref="profile-ea",
        project_id="project-a",
    )

    assert registry.get_agent(tenant_id="tenant-a", agent_id=ca["agent_id"]) == ca
    assert registry.get_agent(tenant_id="tenant-b", agent_id=ca["agent_id"]) is None
    assert [item["agent_type"] for item in registry.list_eligible_agents(tenant_id="tenant-a")] == [
        "CA",
        "PA",
        "EA",
    ]
    assert registry.resolve_active_pa(tenant_id="tenant-a", project_id="project-a") == pa
    assert registry.list_eligible_agents(
        tenant_id="tenant-a", agent_type="EA", project_id="project-a"
    ) == [ea]

    suspended = registry.set_agent_status(
        tenant_id="tenant-a",
        agent_id=pa["agent_id"],
        status="SUSPENDED",
        expected_version=1,
    )
    assert suspended["version"] == 2
    assert registry.resolve_active_pa(tenant_id="tenant-a", project_id="project-a") is None
    replacement = registry.register_agent(
        tenant_id="tenant-a",
        agent_type="PA",
        profile_ref="profile-pa-2",
        project_id="project-a",
    )
    assert replacement["status"] == "ACTIVE"
    assert len(
        registry.list_eligible_agents(tenant_id="tenant-a", status=None)
    ) == 4


def test_s2_active_pa_uniqueness_and_version_conflicts_fail_closed():
    registry = _registry()
    pa = registry.register_agent(
        tenant_id="tenant-a",
        agent_type="PA",
        profile_ref="profile-pa",
        project_id="project-a",
    )
    with pytest.raises(AgentIdentityRepositoryError) as duplicate:
        registry.register_agent(
            tenant_id="tenant-a",
            agent_type="PA",
            profile_ref="profile-pa-2",
            project_id="project-a",
        )
    assert duplicate.value.error_code == "ae.active_pa_conflict"

    with pytest.raises(AgentIdentityRepositoryError) as stale:
        registry.set_agent_status(
            tenant_id="tenant-a",
            agent_id=pa["agent_id"],
            status="SUSPENDED",
            expected_version=2,
        )
    assert stale.value.error_code == "ae.agent_identity_version_conflict"


@pytest.mark.parametrize(
    "operation",
    (
        lambda registry: registry.register_agent(
            tenant_id="tenant", agent_type="IA", profile_ref="profile"
        ),
        lambda registry: registry.register_agent(
            tenant_id="tenant", agent_type="PA", profile_ref="profile"
        ),
        lambda registry: registry.list_eligible_agents(
            tenant_id="tenant", agent_type="IA"
        ),
        lambda registry: registry.list_eligible_agents(
            tenant_id="tenant", status="UNKNOWN"
        ),
        lambda registry: registry.list_eligible_agents(tenant_id="tenant", limit=0),
        lambda registry: registry.set_agent_status(
            tenant_id="tenant", agent_id="missing", status="UNKNOWN", expected_version=1
        ),
    ),
)
def test_s2_invalid_registry_inputs_are_typed(operation):
    with pytest.raises(AgentIdentityRepositoryError) as error:
        operation(_registry())
    assert error.value.error_code == "ae.agent_identity_input_invalid"


def test_s2_internal_api_enforces_caller_roles_and_tenant_scope():
    registry = _registry()
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    register_agent_registry_routes(app, registry=registry)
    client = TestClient(app)
    ag = issue_mock_service_token(service_id="nex-ag", audience="nex-ae-api")
    wc = issue_mock_service_token(service_id="nex-wc", audience="nex-ae-api")
    mo = issue_mock_service_token(service_id="nex-mo", audience="nex-ae-api")
    ag_headers = {"Authorization": f"Bearer {ag.access_token}"}
    wc_headers = {"Authorization": f"Bearer {wc.access_token}"}

    created = client.post(
        "/internal/v1/tenants/tenant-a/agents",
        headers=ag_headers,
        json={"agent_type": "PA", "profile_ref": "profile-pa", "project_id": "project-a"},
    )
    assert created.status_code == 201
    agent_id = created.json()["agent_id"]
    assert client.get(
        f"/internal/v1/tenants/tenant-a/agents/{agent_id}", headers=wc_headers
    ).status_code == 200
    listing = client.get(
        "/internal/v1/tenants/tenant-a/agents?agent_type=PA&project_id=project-a",
        headers=wc_headers,
    )
    assert len(listing.json()["agents"]) == 1
    assert client.get(
        "/internal/v1/tenants/tenant-a/projects/project-a/active-pa",
        headers=wc_headers,
    ).json()["agent_id"] == agent_id
    assert client.get(
        f"/internal/v1/tenants/tenant-b/agents/{agent_id}", headers=wc_headers
    ).status_code == 404
    assert client.post(
        "/internal/v1/tenants/tenant-a/agents",
        headers=wc_headers,
        json={"agent_type": "CA", "profile_ref": "profile"},
    ).status_code == 403
    assert client.get(
        "/internal/v1/tenants/tenant-a/agents",
        headers={"Authorization": f"Bearer {mo.access_token}"},
    ).status_code == 403
    assert client.get("/internal/v1/tenants/tenant-a/agents").status_code == 401

    duplicate = client.post(
        "/internal/v1/tenants/tenant-a/agents",
        headers=ag_headers,
        json={"agent_type": "PA", "profile_ref": "duplicate", "project_id": "project-a"},
    )
    assert duplicate.status_code == 409
    changed = client.patch(
        f"/internal/v1/tenants/tenant-a/agents/{agent_id}/status",
        headers=ag_headers,
        json={"status": "SUSPENDED", "expected_version": 1},
    )
    assert changed.status_code == 200
    assert changed.json()["status"] == "SUSPENDED"
    assert client.patch(
        f"/internal/v1/tenants/tenant-a/agents/{agent_id}/status",
        headers=ag_headers,
        json={"status": "ACTIVE", "expected_version": 1},
    ).status_code == 409
    assert client.get(
        "/internal/v1/tenants/tenant-a/projects/project-a/active-pa",
        headers=wc_headers,
    ).status_code == 404
    assert client.get(
        "/internal/v1/tenants/tenant-a/projects/project-a/active-pa"
    ).status_code == 401
    assert client.get(
        "/internal/v1/tenants/tenant-a/agents?agent_type=IA", headers=wc_headers
    ).status_code == 400


def test_s2_api_fails_closed_without_postgres_registry():
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    register_agent_registry_routes(app, registry=None)
    token = issue_mock_service_token(service_id="nex-wc", audience="nex-ae-api")
    response = TestClient(app).get(
        "/internal/v1/tenants/tenant-a/agents",
        headers={"Authorization": f"Bearer {token.access_token}"},
    )
    assert response.status_code == 503
    ag = issue_mock_service_token(service_id="nex-ag", audience="nex-ae-api")
    ag_headers = {"Authorization": f"Bearer {ag.access_token}"}
    assert TestClient(app).post(
        "/internal/v1/tenants/tenant-a/agents",
        headers=ag_headers,
        json={"agent_type": "CA", "profile_ref": "profile"},
    ).status_code == 503
    assert TestClient(app).get(
        "/internal/v1/tenants/tenant-a/agents/missing",
        headers={"Authorization": f"Bearer {token.access_token}"},
    ).status_code == 503
    assert TestClient(app).patch(
        "/internal/v1/tenants/tenant-a/agents/missing/status",
        headers=ag_headers,
        json={"status": "SUSPENDED", "expected_version": 1},
    ).status_code == 503
    assert TestClient(app).get(
        "/internal/v1/tenants/tenant-a/projects/project-a/active-pa",
        headers={"Authorization": f"Bearer {token.access_token}"},
    ).status_code == 503


def test_s2_status_guards_ia_missing_and_expected_version():
    sessions = _sessions()
    registry = SqlAlchemyAgentIdentityRegistry(sessions, clock=lambda: NOW)
    with sessions.begin() as session:
        session.execute(
            text("""
                INSERT INTO ae_agent_identity (
                    tenant_id, agent_id, schema_version, agent_type, profile_ref,
                    status, project_id, created_at, version
                ) VALUES ('tenant-a', 'ia-1', '2.1', 'IA', 'profile-ia',
                          'ACTIVE', NULL, '2026-10-18T03:00:00Z', 1)
            """)
        )
    with pytest.raises(AgentIdentityRepositoryError) as ia_error:
        registry.set_agent_status(
            tenant_id="tenant-a", agent_id="ia-1", status="SUSPENDED", expected_version=1
        )
    assert ia_error.value.error_code == "ae.agent_identity_managed_by_assignment"
    with pytest.raises(AgentIdentityRepositoryError) as missing:
        registry.set_agent_status(
            tenant_id="tenant-a", agent_id="missing", status="SUSPENDED", expected_version=1
        )
    assert missing.value.error_code == "ae.agent_identity_not_found"
    with pytest.raises(AgentIdentityRepositoryError):
        registry.set_agent_status(
            tenant_id="tenant-a", agent_id="ia-1", status="SUSPENDED", expected_version=False
        )


def test_s2_repository_database_errors_and_reload_conflict(monkeypatch):
    empty = create_engine("sqlite+pysqlite://", future=True)
    broken = SqlAlchemyAgentIdentityRegistry(sessionmaker(bind=empty))
    operations = (
        lambda: broken.register_agent(
            tenant_id="tenant", agent_type="CA", profile_ref="profile"
        ),
        lambda: broken.get_agent(tenant_id="tenant", agent_id="agent"),
        lambda: broken.list_eligible_agents(tenant_id="tenant"),
        lambda: broken.set_agent_status(
            tenant_id="tenant", agent_id="agent", status="SUSPENDED", expected_version=1
        ),
    )
    for operation in operations:
        with pytest.raises(AgentIdentityRepositoryError) as error:
            operation()
        assert error.value.retryable is True

    registry = _registry()
    monkeypatch.setattr(identity_module, "_load_identity", lambda *args: None)
    with pytest.raises(AgentIdentityRepositoryError) as conflict:
        registry.register_agent(
            tenant_id="tenant", agent_type="CA", profile_ref="profile"
        )
    assert conflict.value.error_code == "ae.agent_identity_write_conflict"


def test_s2_active_pa_invariant_guard(monkeypatch):
    registry = _registry()
    monkeypatch.setattr(
        registry,
        "list_eligible_agents",
        lambda **kwargs: [{"agent_id": "a"}, {"agent_id": "b"}],
    )
    with pytest.raises(AgentIdentityRepositoryError) as error:
        registry.resolve_active_pa(tenant_id="tenant", project_id="project")
    assert error.value.error_code == "ae.active_pa_invariant_broken"
