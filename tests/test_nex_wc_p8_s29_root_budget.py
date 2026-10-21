from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from nex_wc import work_items as work_item_module
from nex_wc.coordination import (
    InMemoryCoordinationRepository,
    SqlAlchemyCoordinationRepository,
    WorkCoordinationService,
)
from nex_wc.delegation_lineage import (
    DelegationLineageError,
    SqlAlchemyDelegationLineageRepository,
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
SMOKE_ENABLED = os.getenv("NEX_WC_P8_S29_POSTGRES_SMOKE") == "1"

TENANT = "tenant-p8-s29"
PROJECT = "project-p8-s29"
IA_ID = "29100000-0000-4000-8000-000000000001"
PA_A_ID = "29100000-0000-4000-8000-000000000002"
PA_B_ID = "29100000-0000-4000-8000-000000000003"
PA_C_ID = "29100000-0000-4000-8000-000000000004"
ROOT_ID = "29200000-0000-4000-8000-000000000001"
NOW_DT = datetime(2026, 10, 21, 18, 0, tzinfo=UTC)
NOW = "2026-10-21T18:00:00Z"

postgres_smoke = pytest.mark.skipif(
    not DATABASE_URL or not SMOKE_ENABLED,
    reason="Protected P8-S29 PostgreSQL concurrency smoke is disabled",
)


class Authorization:
    def effective_authorization(self, **_kwargs):
        return {
            "active": True,
            "scopes": ["work:delegate", "work:claim"],
            "revision_hash": "9" * 64,
        }


class Agents:
    def __init__(self, agent_id: str):
        self._agent_id = agent_id

    def list_agents(self, **_kwargs):
        return [self.get_agent(tenant_id=TENANT, agent_id=self._agent_id)]

    def get_agent(self, **_kwargs):
        return {
            "agent_id": self._agent_id,
            "agent_type": "PA",
            "project_id": PROJECT,
            "profile_ref": "agent-profile://pa/project-budget-read/v1",
            "status": "ACTIVE",
        }


def _stable_uuid(label: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"nex-p8-s29:{label}"))


def _root_payload() -> dict[str, object]:
    return {
        "delegation_spec": {
            "schema_version": "1.0",
            "delegation_id": "delegation-p8-s29-root",
            "tenant_id": TENANT,
            "parent_agent_execution_id": "ia-execution-p8-s29",
            "parent_executable_plan_id": "ia-plan-p8-s29",
            "parent_executable_step_id": "ia-step-p8-s29",
            "delegation_revision": 1,
            "goal": "Create the root for descendant-budget admission.",
            "work_class": "ANALYSIS",
            "required_agent_type": "PA",
            "required_capability": "FINANCE.PROJECT_BUDGET_CHECK",
            "project_ref": {"entity_type": "PROJECT", "entity_id": PROJECT},
            "project_scope_ref": PROJECT,
            "result_contract_ref": "contract://nex/wc/root-budget/v1",
            "completion_policy": "OWNER_SUBMITS",
            "correlation_id": "correlation-p8-s29",
        },
        "requester": {"entity_type": "AGENT", "entity_id": IA_ID},
        "accountable_owner": {"entity_type": "USER", "entity_id": "owner-p8"},
    }


def _child_payload(sequence: int, parent: dict[str, str]) -> dict[str, object]:
    return {
        "delegation_spec": {
            "schema_version": "1.1",
            "delegation_id": f"delegation-p8-s29-child-{sequence}",
            "tenant_id": TENANT,
            "parent_agent_execution_id": parent["execution_id"],
            "parent_executable_plan_id": "pa-plan-p8-s29",
            "parent_executable_step_id": f"pa-step-p8-s29-{sequence}",
            "delegation_revision": 1,
            "goal": f"Create root-budget descendant {sequence}.",
            "work_class": "ANALYSIS",
            "required_agent_type": "PA",
            "required_capability": "FINANCE.PROJECT_BUDGET_CHECK",
            "project_ref": {"entity_type": "PROJECT", "entity_id": PROJECT},
            "project_scope_ref": PROJECT,
            "result_contract_ref": "contract://nex/wc/root-budget-child/v1",
            "completion_policy": "OWNER_SUBMITS",
            "correlation_id": "correlation-p8-s29",
            "parent_work_item_id": parent["work_item_id"],
            "parent_claim_ref": parent["claim_id"],
            "parent_claim_generation": 1,
            "delegating_agent_ref": {
                "agent_id": parent["agent_id"],
                "agent_type": "PA",
            },
        },
        "requester": {"entity_type": "AGENT", "entity_id": parent["agent_id"]},
        "accountable_owner": {"entity_type": "USER", "entity_id": "owner-p8"},
    }


def _create_root(repository) -> None:
    WorkItemService(
        repository,
        authorization_source=Authorization(),
        id_factory=lambda: ROOT_ID,
        clock=lambda: NOW_DT,
        delegation_guard_enabled=True,
    ).create(_root_payload())


def _activate_parent(
    repository,
    coordination_repository,
    work_item_id: str,
    index: int,
    agent_id: str,
):
    coordination = WorkCoordinationService(
        coordination_repository,
        candidate_source=Agents(agent_id),
        authorization_source=Authorization(),
        id_factory=lambda: str(uuid4()),
        token_factory=lambda: _stable_uuid(f"lease-{index}"),
        clock=lambda: NOW_DT,
    )
    coordination.route(tenant_id=TENANT, work_item_id=work_item_id, expected_version=1)
    claimed = coordination.claim(
        tenant_id=TENANT, work_item_id=work_item_id, expected_version=2
    )
    execution_id = _stable_uuid(f"execution-{index}")
    coordination_repository.mark_handoff_enqueued(
        outbox_id=claimed["outbox_id"],
        event_id=claimed["event_id"],
        job_id=f"job-p8-s29-{index}",
        updated_at=NOW,
    )
    coordination_repository.mark_handoff_delivered(
        outbox_id=claimed["outbox_id"],
        event_id=claimed["event_id"],
        job_id=f"job-p8-s29-{index}",
        updated_at=NOW,
        agent_execution_id=execution_id,
    )
    return {
        "work_item_id": work_item_id,
        "claim_id": claimed["claim"]["claim_id"],
        "execution_id": execution_id,
        "agent_id": agent_id,
    }


def _create_child(repository, sequence: int, parent: dict[str, str]):
    work_item_id = _stable_uuid(f"work-item-{sequence}")
    result = WorkItemService(
        repository,
        authorization_source=Authorization(),
        id_factory=lambda: work_item_id,
        clock=lambda: NOW_DT,
        delegation_guard_enabled=True,
    ).create(_child_payload(sequence, parent))
    assert result["created"] is True
    return work_item_id


def _build_root_with_49_descendants(repository, coordination_repository):
    _create_root(repository)
    root = _activate_parent(
        repository, coordination_repository, ROOT_ID, 0, PA_A_ID
    )

    level_one = [_create_child(repository, index, root) for index in range(1, 6)]
    level_one_authority = [
        _activate_parent(
            repository, coordination_repository, work_id, index, PA_B_ID
        )
        for index, work_id in enumerate(level_one, start=1)
    ]

    sequence = 6
    level_two = []
    for parent in level_one_authority:
        for _ in range(5):
            level_two.append(_create_child(repository, sequence, parent))
            sequence += 1

    level_two_authority = [
        _activate_parent(
            repository,
            coordination_repository,
            work_id,
            index + 10,
            PA_C_ID,
        )
        for index, work_id in enumerate(level_two[:5])
    ]
    for parent in level_two_authority[:3]:
        for _ in range(5):
            _create_child(repository, sequence, parent)
            sequence += 1
    for _ in range(4):
        _create_child(repository, sequence, level_two_authority[3])
        sequence += 1
    assert sequence == 50
    return level_two_authority[3], level_two_authority[4]


def test_s29_in_memory_root_budget_denies_descendant_51_and_preserves_replay():
    repository = InMemoryWorkItemRepository()
    coordination = InMemoryCoordinationRepository(repository)
    repository.bind_parent_claim_authority_source(coordination)
    parent_at_four, parent_at_zero = _build_root_with_49_descendants(
        repository, coordination
    )

    payload = _child_payload(50, parent_at_four)
    admitted = WorkItemService(
        repository,
        authorization_source=Authorization(),
        id_factory=lambda: _stable_uuid("work-item-50"),
        clock=lambda: NOW_DT,
        delegation_guard_enabled=True,
    ).create(payload)
    assert admitted["created"] is True
    assert repository._lineages.count_descendants(
        tenant_id=TENANT, root_work_item_id=ROOT_ID
    ) == 50

    replay = WorkItemService(
        repository,
        authorization_source=Authorization(),
        id_factory=lambda: _stable_uuid("replay-work-item-50"),
        clock=lambda: NOW_DT,
        delegation_guard_enabled=True,
    ).create(payload)
    assert replay["created"] is False

    denied_id = _stable_uuid("work-item-51")
    with pytest.raises(WorkItemError) as denied:
        WorkItemService(
            repository,
            authorization_source=Authorization(),
            id_factory=lambda: denied_id,
            clock=lambda: NOW_DT,
            delegation_guard_enabled=True,
        ).create(_child_payload(51, parent_at_zero))
    assert denied.value.error_code == "wc.delegation_root_budget_exceeded"
    assert repository.get(tenant_id=TENANT, work_item_id=denied_id) is None


def test_s29_sqlalchemy_descendant_count_and_failure_mapping():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE wc_delegation_lineage (
                tenant_id TEXT NOT NULL, work_item_id TEXT NOT NULL,
                root_work_item_id TEXT NOT NULL, parent_work_item_id TEXT NULL,
                parent_claim_ref TEXT NULL, parent_claim_generation INTEGER NULL,
                delegating_agent_id TEXT NOT NULL, delegating_agent_type TEXT NOT NULL,
                parent_agent_execution_id TEXT NOT NULL, delegation_depth INTEGER NOT NULL,
                policy_ref TEXT NOT NULL, policy_hash TEXT NOT NULL,
                created_at TEXT NOT NULL, PRIMARY KEY (tenant_id, work_item_id)
            )
        """))
        connection.execute(
            text(
                "INSERT INTO wc_delegation_lineage VALUES "
                "(:tenant, :root, :root, NULL, NULL, NULL, :agent, 'IA', "
                "'execution-root', 1, 'policy', 'hash', :created), "
                "(:tenant, :child, :root, :root, :claim, 1, :agent, 'PA', "
                "'execution-child', 2, 'policy', 'hash', :created)"
            ),
            {
                "tenant": TENANT,
                "root": ROOT_ID,
                "child": _stable_uuid("count-child"),
                "claim": _stable_uuid("count-claim"),
                "agent": PA_A_ID,
                "created": NOW,
            },
        )
    try:
        assert SqlAlchemyDelegationLineageRepository(sessions).count_descendants(
            tenant_id=TENANT, root_work_item_id=ROOT_ID
        ) == 1
    finally:
        engine.dispose()

    class BrokenSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, *_args, **_kwargs):
            from sqlalchemy.exc import OperationalError

            raise OperationalError("SELECT", {}, Exception("offline"))

    with pytest.raises(DelegationLineageError) as unavailable:
        SqlAlchemyDelegationLineageRepository(lambda: BrokenSession()).count_descendants(
            tenant_id=TENANT, root_work_item_id=ROOT_ID
        )
    assert unavailable.value.error_code == "wc.delegation_lineage_store_unavailable"


def test_s29_root_lock_serializes_and_missing_root_fails_closed():
    calls = []

    class FoundResult:
        def scalar_one_or_none(self):
            return ROOT_ID

    class MissingResult:
        def scalar_one_or_none(self):
            return None

    class Session:
        def __init__(self, result):
            self._result = result

        def execute(self, *_args, **_kwargs):
            calls.append(str(_args[0]))
            return self._result

    work_item_module._lock_delegation_root_in_session(
        Session(FoundResult()), tenant_id=TENANT, root_work_item_id=ROOT_ID
    )
    assert "FOR UPDATE" in calls[-1]

    with pytest.raises(WorkItemError) as missing:
        work_item_module._lock_delegation_root_in_session(
            Session(MissingResult()), tenant_id=TENANT, root_work_item_id=ROOT_ID
        )
    assert missing.value.error_code == "wc.delegation_lineage_invalid"


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
def test_s29_actual_postgres_cross_parent_concurrency_cannot_exceed_root_budget():
    target = make_url(DATABASE_URL)
    assert target.username == "nex_wc_user"
    assert target.database == "nex_wc_test"
    engine = create_engine(DATABASE_URL, pool_size=12, max_overflow=2)
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
        parent_at_four, parent_at_zero = _build_root_with_49_descendants(
            work_items, coordination
        )
        barrier = Barrier(2)

        def create_competing_child(sequence: int, parent: dict[str, str]):
            service = WorkItemService(
                SqlAlchemyWorkItemRepository(sessions),
                authorization_source=Authorization(),
                id_factory=lambda: _stable_uuid(f"work-item-{sequence}"),
                clock=lambda: NOW_DT,
                delegation_guard_enabled=True,
            )
            barrier.wait(timeout=10)
            try:
                result = service.create(_child_payload(sequence, parent))
                return "CREATED" if result["created"] else "REPLAYED"
            except WorkItemError as exc:
                return exc.error_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = (
                executor.submit(create_competing_child, 50, parent_at_four),
                executor.submit(create_competing_child, 51, parent_at_zero),
            )
            outcomes = [future.result(timeout=20) for future in futures]

        assert outcomes.count("CREATED") == 1
        assert outcomes.count("wc.delegation_root_budget_exceeded") == 1
        with engine.connect() as connection:
            counts = {
                "descendants": connection.execute(
                    text(
                        "SELECT count(*) FROM wc_delegation_lineage "
                        "WHERE tenant_id = :tenant_id "
                        "AND root_work_item_id = :root_id "
                        "AND work_item_id <> :root_id"
                    ),
                    {"tenant_id": TENANT, "root_id": ROOT_ID},
                ).scalar_one(),
                "work_items": connection.execute(
                    text("SELECT count(*) FROM wc_work_item WHERE tenant_id = :tenant_id"),
                    {"tenant_id": TENANT},
                ).scalar_one(),
            }
        assert counts == {"descendants": 50, "work_items": 51}
    finally:
        with engine.begin() as connection:
            _cleanup(connection)
            assert connection.execute(
                text("SELECT count(*) FROM wc_work_item WHERE tenant_id = :tenant_id"),
                {"tenant_id": TENANT},
            ).scalar_one() == 0
        engine.dispose()
