from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from nex_ae_api.agent_identity import (
    AgentIdentityRepositoryError,
    SqlAlchemyAgentIdentityRegistry,
)


pytestmark = pytest.mark.skipif(
    not os.getenv("NEX_AE_TEST_DATABASE_URL"),
    reason="NEX_AE_TEST_DATABASE_URL is required for protected AE PostgreSQL smoke",
)


def test_s2_actual_postgres_registry_restart_unique_pa_and_zero_residue():
    engine = create_engine(os.environ["NEX_AE_TEST_DATABASE_URL"])
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    tenant_id = "p7-s2-pg-tenant"
    ids = iter(
        (
            "77777777-7777-4777-8777-777777777721",
            "77777777-7777-4777-8777-777777777722",
        )
    )
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM ae_agent_identity WHERE tenant_id = :tenant_id"),
            {"tenant_id": tenant_id},
        )
    try:
        registry = SqlAlchemyAgentIdentityRegistry(
            sessions,
            id_factory=lambda: next(ids),
            clock=lambda: datetime(2026, 10, 18, 3, 30, tzinfo=UTC),
        )
        pa = registry.register_agent(
            tenant_id=tenant_id,
            agent_type="PA",
            profile_ref="urn:nex:profile:pa:p7-s2",
            project_id="project-p7-s2",
        )
        restarted = SqlAlchemyAgentIdentityRegistry(
            sessions, id_factory=lambda: next(ids)
        )
        assert restarted.resolve_active_pa(
            tenant_id=tenant_id, project_id="project-p7-s2"
        ) == pa
        with pytest.raises(AgentIdentityRepositoryError) as duplicate:
            restarted.register_agent(
                tenant_id=tenant_id,
                agent_type="PA",
                profile_ref="urn:nex:profile:pa:duplicate",
                project_id="project-p7-s2",
            )
        assert duplicate.value.error_code == "ae.active_pa_conflict"
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM ae_agent_identity WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            )
            remaining = connection.execute(
                text("SELECT count(*) FROM ae_agent_identity WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            ).scalar_one()
        engine.dispose()
    assert remaining == 0
