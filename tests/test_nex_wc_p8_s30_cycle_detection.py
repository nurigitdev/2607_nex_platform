from __future__ import annotations

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from nex_wc.coordination import (
    CoordinationError,
    InMemoryCoordinationRepository,
    WorkCoordinationService,
)
from nex_wc.delegation_lineage import (
    DelegationLineageError,
    SqlAlchemyDelegationLineageRepository,
    initial_delegation_policy,
)
from nex_wc.work_items import InMemoryWorkItemRepository, WorkItemService
from sqlalchemy.exc import OperationalError

TENANT = "tenant-p8-s30"
PROJECT = "project-p8-s30"
IA_ID = "30100000-0000-4000-8000-000000000001"
PA_A_ID = "30100000-0000-4000-8000-000000000002"
PA_B_ID = "30100000-0000-4000-8000-000000000003"
PA_C_ID = "30100000-0000-4000-8000-000000000004"
ROOT_ID = "30200000-0000-4000-8000-000000000001"
CHILD_ID = "30200000-0000-4000-8000-000000000002"
GRANDCHILD_ID = "30200000-0000-4000-8000-000000000003"
NOW_DT = datetime(2026, 10, 21, 19, 0, tzinfo=UTC)
NOW = "2026-10-21T19:00:00Z"


class Authorization:
    def effective_authorization(self, **_kwargs):
        return {
            "active": True,
            "scopes": ["work:delegate", "work:claim"],
            "revision_hash": "a" * 64,
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
    return str(uuid5(NAMESPACE_URL, f"nex-p8-s30:{label}"))


def _payload(
    delegation_id: str, parent: dict[str, str] | None = None
) -> dict[str, object]:
    spec = {
        "schema_version": "1.0" if parent is None else "1.1",
        "delegation_id": delegation_id,
        "tenant_id": TENANT,
        "parent_agent_execution_id": (
            "ia-execution-p8-s30" if parent is None else parent["execution_id"]
        ),
        "parent_executable_plan_id": "plan-p8-s30",
        "parent_executable_step_id": f"step-{delegation_id}",
        "delegation_revision": 1,
        "goal": f"Exercise cycle-safe delegation {delegation_id}.",
        "work_class": "ANALYSIS",
        "required_agent_type": "PA",
        "required_capability": "FINANCE.PROJECT_BUDGET_CHECK",
        "project_ref": {"entity_type": "PROJECT", "entity_id": PROJECT},
        "project_scope_ref": PROJECT,
        "result_contract_ref": "contract://nex/wc/cycle/v1",
        "completion_policy": "OWNER_SUBMITS",
        "correlation_id": "correlation-p8-s30",
    }
    requester_id = IA_ID
    if parent is not None:
        spec.update(
            {
                "parent_work_item_id": parent["work_item_id"],
                "parent_claim_ref": parent["claim_id"],
                "parent_claim_generation": 1,
                "delegating_agent_ref": {
                    "agent_id": parent["agent_id"],
                    "agent_type": "PA",
                },
            }
        )
        requester_id = parent["agent_id"]
    return {
        "delegation_spec": spec,
        "requester": {"entity_type": "AGENT", "entity_id": requester_id},
        "accountable_owner": {"entity_type": "USER", "entity_id": "owner-p8"},
    }


def _create(repository, work_item_id: str, payload, *, guard: bool = True):
    result = WorkItemService(
        repository,
        authorization_source=Authorization(),
        id_factory=lambda: work_item_id,
        clock=lambda: NOW_DT,
        delegation_guard_enabled=guard,
    ).create(payload)
    assert result["created"] is True


def _coordination(repository, candidate_id: str) -> WorkCoordinationService:
    return WorkCoordinationService(
        repository,
        candidate_source=Agents(candidate_id),
        authorization_source=Authorization(),
        id_factory=lambda: str(uuid4()),
        token_factory=lambda: _stable_uuid(f"lease-{candidate_id}-{uuid4()}"),
        clock=lambda: NOW_DT,
    )


def _claim_and_ack(
    repository,
    work_item_id: str,
    candidate_id: str,
    execution_label: str,
) -> dict[str, str]:
    service = _coordination(repository, candidate_id)
    service.route(tenant_id=TENANT, work_item_id=work_item_id, expected_version=1)
    claimed = service.claim(
        tenant_id=TENANT, work_item_id=work_item_id, expected_version=2
    )
    execution_id = _stable_uuid(execution_label)
    repository.mark_handoff_enqueued(
        outbox_id=claimed["outbox_id"],
        event_id=claimed["event_id"],
        job_id=f"job-{execution_label}",
        updated_at=NOW,
    )
    repository.mark_handoff_delivered(
        outbox_id=claimed["outbox_id"],
        event_id=claimed["event_id"],
        job_id=f"job-{execution_label}",
        updated_at=NOW,
        agent_execution_id=execution_id,
    )
    return {
        "work_item_id": work_item_id,
        "claim_id": claimed["claim"]["claim_id"],
        "execution_id": execution_id,
        "agent_id": candidate_id,
    }


def _a_to_b_chain():
    work_items = InMemoryWorkItemRepository()
    coordination = InMemoryCoordinationRepository(work_items)
    work_items.bind_parent_claim_authority_source(coordination)
    _create(work_items, ROOT_ID, _payload("root"))
    root = _claim_and_ack(coordination, ROOT_ID, PA_A_ID, "execution-a")
    _create(work_items, CHILD_ID, _payload("child", root))
    child = _claim_and_ack(coordination, CHILD_ID, PA_B_ID, "execution-b")
    _create(work_items, GRANDCHILD_ID, _payload("grandchild", child))
    return work_items, coordination


def test_s30_a_to_b_to_a_claim_is_denied_with_zero_claim_authority():
    work_items, repository = _a_to_b_chain()
    service = _coordination(repository, PA_A_ID)
    service.route(
        tenant_id=TENANT, work_item_id=GRANDCHILD_ID, expected_version=1
    )

    with pytest.raises(CoordinationError) as denied:
        service.claim(
            tenant_id=TENANT,
            work_item_id=GRANDCHILD_ID,
            expected_version=2,
        )
    assert denied.value.error_code == "wc.delegation_cycle_detected"
    record = work_items.get(tenant_id=TENANT, work_item_id=GRANDCHILD_ID)
    assert record["state"] == "ROUTED" and record["version"] == 2
    key = (TENANT, GRANDCHILD_ID)
    assert repository._claims.get(key, []) == []
    assert key not in repository._assignments
    assert all(
        row["work_item_id"] != GRANDCHILD_ID
        for row in repository._outbox.values()
    )
    assert work_items._lineages.ancestor_agent_refs(
        tenant_id=TENANT, work_item_id=GRANDCHILD_ID
    ) == [
        {"agent_id": PA_B_ID, "agent_type": "PA"},
        {"agent_id": PA_A_ID, "agent_type": "PA"},
        {"agent_id": IA_ID, "agent_type": "IA"},
    ]


def test_s30_non_ancestor_candidate_and_historical_work_item_remain_claimable():
    work_items, repository = _a_to_b_chain()
    service = _coordination(repository, PA_C_ID)
    service.route(
        tenant_id=TENANT, work_item_id=GRANDCHILD_ID, expected_version=1
    )
    claimed = service.claim(
        tenant_id=TENANT, work_item_id=GRANDCHILD_ID, expected_version=2
    )
    assert claimed["assignment"]["agent_id"] == PA_C_ID

    historical_id = "30200000-0000-4000-8000-000000000010"
    _create(
        work_items,
        historical_id,
        _payload("historical-no-lineage"),
        guard=False,
    )
    historical = _coordination(repository, PA_A_ID)
    historical.route(
        tenant_id=TENANT, work_item_id=historical_id, expected_version=1
    )
    result = historical.claim(
        tenant_id=TENANT, work_item_id=historical_id, expected_version=2
    )
    assert result["work_item"]["state"] == "ASSIGNED"


def test_s30_incomplete_ancestor_chain_fails_closed_without_claim():
    work_items = InMemoryWorkItemRepository()
    repository = InMemoryCoordinationRepository(work_items)
    malformed_id = "30200000-0000-4000-8000-000000000020"
    _create(work_items, malformed_id, _payload("malformed-lineage"), guard=False)
    policy = initial_delegation_policy()
    work_items._lineages.create(
        {
            "schema_version": "wc_delegation_lineage.v1",
            "tenant_id": TENANT,
            "work_item_id": malformed_id,
            "root_work_item_id": "30200000-0000-4000-8000-000000000099",
            "parent_work_item_id": "30200000-0000-4000-8000-000000000098",
            "parent_claim_ref": "30300000-0000-4000-8000-000000000020",
            "parent_claim_generation": 1,
            "delegating_agent_ref": {"agent_id": PA_B_ID, "agent_type": "PA"},
            "parent_agent_execution_id": "malformed-execution",
            "delegation_depth": 2,
            "policy_ref": policy["policy_ref"],
            "policy_hash": policy["policy_hash"],
            "created_at": NOW,
        }
    )
    service = _coordination(repository, PA_C_ID)
    service.route(tenant_id=TENANT, work_item_id=malformed_id, expected_version=1)
    with pytest.raises(CoordinationError) as denied:
        service.claim(
            tenant_id=TENANT, work_item_id=malformed_id, expected_version=2
        )
    assert denied.value.error_code == "wc.delegation_lineage_invalid"
    assert repository._claims.get((TENANT, malformed_id), []) == []


def test_s30_sqlalchemy_ancestor_projection_and_store_failure_mapping():
    rows = [
        {
            "work_item_id": CHILD_ID,
            "root_work_item_id": ROOT_ID,
            "parent_work_item_id": ROOT_ID,
            "delegating_agent_id": PA_A_ID,
            "delegating_agent_type": "PA",
            "delegation_depth": 2,
        },
        {
            "work_item_id": ROOT_ID,
            "root_work_item_id": ROOT_ID,
            "parent_work_item_id": None,
            "delegating_agent_id": IA_ID,
            "delegating_agent_type": "IA",
            "delegation_depth": 1,
        },
    ]

    class Result:
        def mappings(self):
            return self

        def all(self):
            return rows

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, *_args, **_kwargs):
            return Result()

    projected = SqlAlchemyDelegationLineageRepository(
        lambda: Session()
    ).ancestor_agent_refs(tenant_id=TENANT, work_item_id=CHILD_ID)
    assert projected == [
        {"agent_id": PA_A_ID, "agent_type": "PA"},
        {"agent_id": IA_ID, "agent_type": "IA"},
    ]

    class BrokenSession(Session):
        def execute(self, *_args, **_kwargs):
            raise OperationalError("SELECT", {}, Exception("offline"))

    with pytest.raises(DelegationLineageError) as unavailable:
        SqlAlchemyDelegationLineageRepository(
            lambda: BrokenSession()
        ).ancestor_agent_refs(tenant_id=TENANT, work_item_id=CHILD_ID)
    assert unavailable.value.error_code == "wc.delegation_lineage_store_unavailable"
