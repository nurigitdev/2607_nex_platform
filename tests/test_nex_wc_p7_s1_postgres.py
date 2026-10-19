from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from nex_wc.work_items import SqlAlchemyWorkItemRepository, WorkItemError, WorkItemService


pytestmark = pytest.mark.skipif(
    not os.getenv("NEX_WC_TEST_DATABASE_URL"),
    reason="NEX_WC_TEST_DATABASE_URL is required for protected WC PostgreSQL smoke",
)


class _Authorization:
    def effective_authorization(self, **_kwargs):
        return {
            "active": True,
            "scopes": ["work:delegate"],
            "revision_hash": "a" * 64,
        }


def _payload(goal: str = "Produce a margin report"):
    return {
        "delegation_spec": {
            "schema_version": "1.0",
            "delegation_id": "p7-s1-pg-delegation",
            "tenant_id": "p7-s1-pg-tenant",
            "parent_agent_execution_id": "p7-s1-parent-execution",
            "parent_executable_plan_id": "p7-s1-parent-plan",
            "parent_executable_step_id": "p7-s1-parent-step",
            "delegation_revision": 1,
            "goal": goal,
            "work_class": "REPORTING",
            "required_agent_type": "PA",
            "required_capability": "project.margin.read",
            "project_ref": {"entity_type": "PROJECT", "entity_id": "project-pg"},
            "project_scope_ref": "project-pg",
            "result_contract_ref": "urn:nex:result:margin:1",
            "completion_policy": "OWNER_SUBMITS",
            "correlation_id": "p7-s1-pg-trace",
            "causation_id": None,
        },
        "requester": {"entity_type": "AGENT", "entity_id": "ia-pg"},
        "accountable_owner": {"entity_type": "USER", "entity_id": "user-pg"},
    }


def test_s1_actual_postgres_upsert_select_restart_and_zero_residue():
    engine = create_engine(os.environ["NEX_WC_TEST_DATABASE_URL"])
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    tenant_id = "p7-s1-pg-tenant"
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM wc_work_item WHERE tenant_id = :tenant_id"),
            {"tenant_id": tenant_id},
        )
    try:
        service = WorkItemService(
            SqlAlchemyWorkItemRepository(sessions),
            authorization_source=_Authorization(),
            id_factory=lambda: "77777777-7777-4777-8777-777777777771",
            clock=lambda: datetime(2026, 10, 18, 2, 0, tzinfo=UTC),
        )
        created = service.create(_payload())
        repeated = service.create(_payload())
        assert created["created"] is True
        assert repeated["created"] is False
        assert repeated["work_item"]["work_item_id"] == created["work_item"]["work_item_id"]

        restarted = WorkItemService(
            SqlAlchemyWorkItemRepository(sessions),
            authorization_source=_Authorization(),
        )
        loaded = restarted.get(
            tenant_id=tenant_id,
            work_item_id=created["work_item"]["work_item_id"],
        )
        assert loaded["goal"] == "Produce a margin report"
        with pytest.raises(WorkItemError) as conflict:
            restarted.create(_payload("Conflicting semantic goal"))
        assert conflict.value.error_code == "wc.work_item_idempotency_conflict"
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM wc_work_item WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            )
            remaining = connection.execute(
                text("SELECT count(*) FROM wc_work_item WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            ).scalar_one()
        engine.dispose()
    assert remaining == 0
