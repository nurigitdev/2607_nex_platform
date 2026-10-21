from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier

import pytest
from nex_wc.coordination import (
    InMemoryCoordinationRepository,
    SqlAlchemyCoordinationRepository,
    WorkCoordinationService,
)
from nex_wc.work_items import (
    InMemoryWorkItemRepository,
    SqlAlchemyWorkItemRepository,
    WorkItemError,
    WorkItemService,
)
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv("NEX_WC_TEST_DATABASE_URL", "")
SMOKE_ENABLED = os.getenv("NEX_WC_P8_S28_POSTGRES_SMOKE") == "1"

TENANT = "tenant-p8-s28"
PROJECT = "project-p8-s28"
IA_ID = "28100000-0000-4000-8000-000000000001"
PA_ID = "28100000-0000-4000-8000-000000000002"
ROOT_ID = "28200000-0000-4000-8000-000000000001"
PARENT_EXECUTION_ID = "28300000-0000-4000-8000-000000000001"
NOW_DT = datetime(2026, 10, 21, 17, 0, tzinfo=UTC)
NOW = "2026-10-21T17:00:00Z"

postgres_smoke = pytest.mark.skipif(
    not DATABASE_URL or not SMOKE_ENABLED,
    reason="Protected P8-S28 PostgreSQL concurrency smoke is disabled",
)


class Authorization:
    def effective_authorization(self, **_kwargs):
        return {
            "active": True,
            "scopes": ["work:delegate", "work:claim"],
            "revision_hash": "f" * 64,
        }


class Agents:
    def list_agents(self, **_kwargs):
        return [self.get_agent(tenant_id=TENANT, agent_id=PA_ID)]

    def get_agent(self, **_kwargs):
        return {
            "agent_id": PA_ID,
            "agent_type": "PA",
            "project_id": PROJECT,
            "profile_ref": "agent-profile://pa/project-budget-read/v1",
            "status": "ACTIVE",
        }


def _root_payload() -> dict[str, object]:
    return {
        "delegation_spec": {
            "schema_version": "1.0",
            "delegation_id": "delegation-p8-s28-root",
            "tenant_id": TENANT,
            "parent_agent_execution_id": "ia-execution-p8-s28",
            "parent_executable_plan_id": "ia-plan-p8-s28",
            "parent_executable_step_id": "ia-step-p8-s28",
            "delegation_revision": 1,
            "goal": "Create a parent for direct-child budget admission.",
            "work_class": "ANALYSIS",
            "required_agent_type": "PA",
            "required_capability": "FINANCE.PROJECT_BUDGET_CHECK",
            "project_ref": {"entity_type": "PROJECT", "entity_id": PROJECT},
            "project_scope_ref": PROJECT,
            "result_contract_ref": "contract://nex/wc/parent/v1",
            "completion_policy": "OWNER_SUBMITS",
            "correlation_id": "correlation-p8-s28",
        },
        "requester": {"entity_type": "AGENT", "entity_id": IA_ID},
        "accountable_owner": {"entity_type": "USER", "entity_id": "owner-p8"},
    }


def _child_payload(index: int, claim_id: str) -> dict[str, object]:
    return {
        "delegation_spec": {
            "schema_version": "1.1",
            "delegation_id": f"delegation-p8-s28-child-{index}",
            "tenant_id": TENANT,
            "parent_agent_execution_id": PARENT_EXECUTION_ID,
            "parent_executable_plan_id": "pa-plan-p8-s28",
            "parent_executable_step_id": f"pa-step-p8-s28-{index}",
            "delegation_revision": 1,
            "goal": f"Create direct child {index} within the fixed budget.",
            "work_class": "ANALYSIS",
            "required_agent_type": "EA",
            "required_capability": "FINANCE.PROJECT_BUDGET_CHECK",
            "project_ref": {"entity_type": "PROJECT", "entity_id": PROJECT},
            "project_scope_ref": PROJECT,
            "result_contract_ref": "contract://nex/wc/child/v1",
            "completion_policy": "OWNER_SUBMITS",
            "correlation_id": "correlation-p8-s28",
            "parent_work_item_id": ROOT_ID,
            "parent_claim_ref": claim_id,
            "parent_claim_generation": 1,
            "delegating_agent_ref": {"agent_id": PA_ID, "agent_type": "PA"},
        },
        "requester": {"entity_type": "AGENT", "entity_id": PA_ID},
        "accountable_owner": {"entity_type": "USER", "entity_id": "owner-p8"},
    }


def _claim_parent(work_items, coordination_repository):
    WorkItemService(
        work_items,
        authorization_source=Authorization(),
        id_factory=lambda: ROOT_ID,
        clock=lambda: NOW_DT,
        delegation_guard_enabled=True,
    ).create(_root_payload())
    ids = iter(
        (
            "28400000-0000-4000-8000-000000000001",
            "28400000-0000-4000-8000-000000000002",
            "28400000-0000-4000-8000-000000000003",
            "28400000-0000-4000-8000-000000000004",
            "28400000-0000-4000-8000-000000000005",
            "28400000-0000-4000-8000-000000000006",
        )
    )
    coordination = WorkCoordinationService(
        coordination_repository,
        candidate_source=Agents(),
        authorization_source=Authorization(),
        id_factory=lambda: next(ids),
        token_factory=lambda: "p8-s28-lease",
        clock=lambda: NOW_DT,
    )
    coordination.route(tenant_id=TENANT, work_item_id=ROOT_ID, expected_version=1)
    claimed = coordination.claim(
        tenant_id=TENANT, work_item_id=ROOT_ID, expected_version=2
    )
    coordination_repository.mark_handoff_enqueued(
        outbox_id=claimed["outbox_id"],
        event_id=claimed["event_id"],
        job_id="job-p8-s28",
        updated_at=NOW,
    )
    coordination_repository.mark_handoff_delivered(
        outbox_id=claimed["outbox_id"],
        event_id=claimed["event_id"],
        job_id="job-p8-s28",
        updated_at=NOW,
        agent_execution_id=PARENT_EXECUTION_ID,
    )
    return claimed


def test_s28_in_memory_sixth_direct_child_is_denied_and_replay_is_preserved():
    repository = InMemoryWorkItemRepository()
    coordination = InMemoryCoordinationRepository(repository)
    repository.bind_parent_claim_authority_source(coordination)
    claimed = _claim_parent(repository, coordination)
    claim_id = claimed["claim"]["claim_id"]

    results = []
    for index in range(1, 6):
        work_id = f"28500000-0000-4000-8000-{index:012d}"
        results.append(
            WorkItemService(
                repository,
                authorization_source=Authorization(),
                id_factory=lambda value=work_id: value,
                clock=lambda: NOW_DT,
                delegation_guard_enabled=True,
            ).create(_child_payload(index, claim_id))
        )
    assert all(result["created"] for result in results)
    assert repository._lineages.count_children(
        tenant_id=TENANT, parent_work_item_id=ROOT_ID
    ) == 5

    replay = WorkItemService(
        repository,
        authorization_source=Authorization(),
        id_factory=lambda: "28500000-0000-4000-8000-000000000099",
        clock=lambda: NOW_DT,
        delegation_guard_enabled=True,
    ).create(_child_payload(5, claim_id))
    assert replay["created"] is False

    with pytest.raises(WorkItemError) as denied:
        WorkItemService(
            repository,
            authorization_source=Authorization(),
            id_factory=lambda: "28500000-0000-4000-8000-000000000006",
            clock=lambda: NOW_DT,
            delegation_guard_enabled=True,
        ).create(_child_payload(6, claim_id))
    assert denied.value.error_code == "wc.delegation_child_budget_exceeded"
    assert repository.get(
        tenant_id=TENANT,
        work_item_id="28500000-0000-4000-8000-000000000006",
    ) is None


def _cleanup(connection) -> None:
    params = {"tenant_id": TENANT}
    for table in (
        "wc_delegation_lineage",
        "wc_event_outbox",
        "wc_claim",
        "wc_assignment",
        "wc_routing_decision",
        "wc_work_item",
    ):
        connection.execute(text(f"DELETE FROM {table} WHERE tenant_id = :tenant_id"), params)


@postgres_smoke
def test_s28_actual_postgres_concurrent_children_cannot_oversubscribe_budget():
    target = make_url(DATABASE_URL)
    assert target.username == "nex_wc_user"
    assert target.database == "nex_wc_test"
    engine = create_engine(DATABASE_URL, pool_size=8, max_overflow=2)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with engine.begin() as connection:
        _cleanup(connection)
        assert connection.execute(text("SELECT current_database()" )).scalar_one() == "nex_wc_test"
        applied = set(
            connection.execute(text("SELECT version FROM schema_migrations")).scalars()
        )
        assert "1005_wc_assignment_execution" in applied

    try:
        work_items = SqlAlchemyWorkItemRepository(sessions)
        coordination = SqlAlchemyCoordinationRepository(sessions)
        claimed = _claim_parent(work_items, coordination)
        claim_id = claimed["claim"]["claim_id"]
        barrier = Barrier(6)

        def create_child(index: int):
            work_id = f"28600000-0000-4000-8000-{index:012d}"
            service = WorkItemService(
                SqlAlchemyWorkItemRepository(sessions),
                authorization_source=Authorization(),
                id_factory=lambda: work_id,
                clock=lambda: NOW_DT,
                delegation_guard_enabled=True,
            )
            barrier.wait(timeout=10)
            try:
                result = service.create(_child_payload(index, claim_id))
                return ("CREATED", result["work_item"]["work_item_id"])
            except WorkItemError as exc:
                return (exc.error_code, work_id)

        with ThreadPoolExecutor(max_workers=6) as executor:
            outcomes = list(executor.map(create_child, range(1, 7)))

        assert [status for status, _ in outcomes].count("CREATED") == 5
        assert [status for status, _ in outcomes].count(
            "wc.delegation_child_budget_exceeded"
        ) == 1
        with engine.connect() as connection:
            counts = {
                "children": connection.execute(
                    text(
                        "SELECT count(*) FROM wc_delegation_lineage "
                        "WHERE tenant_id = :tenant_id "
                        "AND parent_work_item_id = :parent_work_item_id"
                    ),
                    {"tenant_id": TENANT, "parent_work_item_id": ROOT_ID},
                ).scalar_one(),
                "work_items": connection.execute(
                    text("SELECT count(*) FROM wc_work_item WHERE tenant_id = :tenant_id"),
                    {"tenant_id": TENANT},
                ).scalar_one(),
            }
        assert counts == {"children": 5, "work_items": 6}
    finally:
        with engine.begin() as connection:
            _cleanup(connection)
            assert connection.execute(
                text("SELECT count(*) FROM wc_work_item WHERE tenant_id = :tenant_id"),
                {"tenant_id": TENANT},
            ).scalar_one() == 0
        engine.dispose()
