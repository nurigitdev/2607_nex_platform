from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from nex_wc.work_items import (
    SqlAlchemyWorkItemRepository,
    WorkItemError,
    WorkItemService,
)
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

pytestmark = pytest.mark.skipif(
    not os.getenv("NEX_WC_TEST_DATABASE_URL"),
    reason="NEX_WC_TEST_DATABASE_URL is required for protected WC PostgreSQL smoke",
)


class _Authorization:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def effective_authorization(self, **kwargs):
        self.calls.append(dict(kwargs))
        return {
            "active": True,
            "scopes": ["work:delegate"],
            "revision_hash": "a" * 64,
        }


def _payload(
    goal: str = "Produce a margin report",
    *,
    requester: str = "ia-pg",
):
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
        "requester": {"entity_type": "AGENT", "entity_id": requester},
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
        authorization = _Authorization()
        repository = SqlAlchemyWorkItemRepository(sessions)
        service = WorkItemService(
            repository,
            authorization_source=authorization,
            id_factory=lambda: "77777777-7777-4777-8777-777777777771",
            clock=lambda: datetime(2026, 10, 18, 2, 0, tzinfo=UTC),
        )
        created = service.create(_payload())
        repeated = service.create(_payload())
        assert created["created"] is True
        assert repeated["created"] is False
        assert (
            repeated["work_item"]["work_item_id"]
            == created["work_item"]["work_item_id"]
        )
        assert authorization.calls == [
            {"tenant_id": tenant_id, "subject_id": "ia-pg"},
            {"tenant_id": tenant_id, "subject_id": "ia-pg"},
        ]

        restarted_repository = SqlAlchemyWorkItemRepository(sessions)
        restarted = WorkItemService(
            restarted_repository,
            authorization_source=authorization,
        )
        loaded = restarted.get(
            tenant_id=tenant_id,
            work_item_id=created["work_item"]["work_item_id"],
        )
        assert loaded["goal"] == "Produce a margin report"
        persisted = restarted_repository.get(
            tenant_id=tenant_id,
            work_item_id=created["work_item"]["work_item_id"],
        )
        assert persisted is not None
        assert persisted["create_authorization_revision_hash"] == "a" * 64
        assert datetime.fromisoformat(
            persisted["create_authorization_checked_at"]
        ) == datetime(2026, 10, 18, 2, 0, tzinfo=UTC)
        assert persisted["create_authorized_subject_id"] == "ia-pg"

        with pytest.raises(WorkItemError) as requester_conflict:
            restarted.create(_payload(requester="ia-other"))
        assert (
            requester_conflict.value.error_code == "wc.work_item_idempotency_conflict"
        )
        assert requester_conflict.value.status_code == 409
        assert requester_conflict.value.retryable is False

        with pytest.raises(WorkItemError) as conflict:
            restarted.create(_payload("Conflicting semantic goal"))
        assert conflict.value.error_code == "wc.work_item_idempotency_conflict"
        assert authorization.calls[-2:] == [
            {"tenant_id": tenant_id, "subject_id": "ia-other"},
            {"tenant_id": tenant_id, "subject_id": "ia-pg"},
        ]

        with engine.begin() as connection:
            database_identity = connection.execute(
                text("SELECT current_database(), current_user")
            ).one()
            work_items = (
                connection.execute(
                    text(
                        "SELECT work_item, create_authorization_revision_hash, "
                        "create_authorized_subject_id FROM wc_work_item "
                        "WHERE tenant_id = :tenant_id"
                    ),
                    {"tenant_id": tenant_id},
                )
                .mappings()
                .all()
            )
            migration_present = connection.execute(
                text(
                    "SELECT count(*) FROM schema_migrations "
                    "WHERE version = '1003_wc_work_item_authorization'"
                )
            ).scalar_one()
        assert tuple(database_identity) == ("nex_wc_test", "nex_wc_user")
        assert len(work_items) == 1
        assert work_items[0]["work_item"]["requester"]["entity_id"] == "ia-pg"
        assert work_items[0]["create_authorization_revision_hash"] == "a" * 64
        assert work_items[0]["create_authorized_subject_id"] == "ia-pg"
        assert migration_present == 1
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
