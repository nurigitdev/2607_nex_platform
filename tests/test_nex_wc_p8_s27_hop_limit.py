from __future__ import annotations

from datetime import UTC, datetime

import pytest
from nex_wc.coordination import InMemoryCoordinationRepository, WorkCoordinationService
from nex_wc.delegation_lineage import initial_delegation_policy
from nex_wc.work_items import InMemoryWorkItemRepository, WorkItemError, WorkItemService

TENANT = "tenant-p8-s27"
PROJECT = "project-p8-s27"
IA_ID = "27100000-0000-4000-8000-000000000001"
PA_ID = "27100000-0000-4000-8000-000000000002"
CLAIM_AGENT_ID = "27100000-0000-4000-8000-000000000003"
ROOT_ID = "27200000-0000-4000-8000-000000000001"
DEPTH10_ID = "27200000-0000-4000-8000-000000000010"
CHILD_ID = "27200000-0000-4000-8000-000000000011"
PARENT_ID = "27200000-0000-4000-8000-000000000009"
CLAIM_ID = "27300000-0000-4000-8000-000000000010"
EXECUTION_ID = "27400000-0000-4000-8000-000000000010"
NOW_DT = datetime(2026, 10, 21, 16, 0, tzinfo=UTC)
NOW = "2026-10-21T16:00:00Z"


class Authorization:
    def effective_authorization(self, **_kwargs):
        return {
            "active": True,
            "scopes": ["work:delegate", "work:claim"],
            "revision_hash": "e" * 64,
        }


class Agents:
    def list_agents(self, **_kwargs):
        return [self.get_agent(tenant_id=TENANT, agent_id=PA_ID)]

    def get_agent(self, **_kwargs):
        return {
            "agent_id": CLAIM_AGENT_ID,
            "agent_type": "PA",
            "project_id": PROJECT,
            "profile_ref": "agent-profile://pa/project-budget-read/v1",
            "status": "ACTIVE",
        }


def _first_payload(delegation_id: str) -> dict[str, object]:
    return {
        "delegation_spec": {
            "schema_version": "1.0",
            "delegation_id": delegation_id,
            "tenant_id": TENANT,
            "parent_agent_execution_id": "ia-execution-p8-s27",
            "parent_executable_plan_id": "ia-plan-p8-s27",
            "parent_executable_step_id": "ia-step-p8-s27",
            "delegation_revision": 1,
            "goal": "Exercise an admitted depth-ten WorkItem.",
            "work_class": "ANALYSIS",
            "required_agent_type": "PA",
            "required_capability": "FINANCE.PROJECT_BUDGET_CHECK",
            "project_ref": {"entity_type": "PROJECT", "entity_id": PROJECT},
            "project_scope_ref": PROJECT,
            "result_contract_ref": "contract://nex/wc/depth/v1",
            "completion_policy": "OWNER_SUBMITS",
            "correlation_id": "correlation-p8-s27",
        },
        "requester": {"entity_type": "AGENT", "entity_id": IA_ID},
        "accountable_owner": {"entity_type": "USER", "entity_id": "owner-p8"},
    }


def _complete_depth_ten_lineage() -> list[dict[str, object]]:
    policy = initial_delegation_policy()
    rows = []
    for depth in range(1, 11):
        work_item_id = f"27200000-0000-4000-8000-{depth:012d}"
        parent_id = (
            None
            if depth == 1
            else f"27200000-0000-4000-8000-{depth - 1:012d}"
        )
        rows.append(
            {
                "schema_version": "wc_delegation_lineage.v1",
                "tenant_id": TENANT,
                "work_item_id": work_item_id,
                "root_work_item_id": ROOT_ID,
                "parent_work_item_id": parent_id,
                "parent_claim_ref": (
                    None
                    if depth == 1
                    else f"27300000-0000-4000-8000-{depth:012d}"
                ),
                "parent_claim_generation": None if depth == 1 else 1,
                "delegating_agent_ref": {
                    "agent_id": (
                        IA_ID
                        if depth == 1
                        else f"27700000-0000-4000-8000-{depth:012d}"
                    ),
                    "agent_type": "IA" if depth == 1 else "PA",
                },
                "parent_agent_execution_id": f"execution-p8-s27-{depth}",
                "delegation_depth": depth,
                "policy_ref": policy["policy_ref"],
                "policy_hash": policy["policy_hash"],
                "created_at": NOW,
            }
        )
    return rows


def _nested_payload() -> dict[str, object]:
    return {
        "delegation_spec": {
            "schema_version": "1.1",
            "delegation_id": "delegation-p8-s27-denied-child",
            "tenant_id": TENANT,
            "parent_agent_execution_id": EXECUTION_ID,
            "parent_executable_plan_id": "pa-plan-p8-s27",
            "parent_executable_step_id": "pa-step-p8-s27",
            "delegation_revision": 1,
            "goal": "This prospective depth-eleven child must be denied.",
            "work_class": "ANALYSIS",
            "required_agent_type": "EA",
            "required_capability": "FINANCE.PROJECT_BUDGET_CHECK",
            "project_ref": {"entity_type": "PROJECT", "entity_id": PROJECT},
            "project_scope_ref": PROJECT,
            "result_contract_ref": "contract://nex/wc/depth-child/v1",
            "completion_policy": "OWNER_SUBMITS",
            "correlation_id": "correlation-p8-s27",
            "parent_work_item_id": DEPTH10_ID,
            "parent_claim_ref": CLAIM_ID,
            "parent_claim_generation": 1,
            "delegating_agent_ref": {"agent_id": PA_ID, "agent_type": "PA"},
        },
        "requester": {"entity_type": "AGENT", "entity_id": PA_ID},
        "accountable_owner": {"entity_type": "USER", "entity_id": "owner-p8"},
    }


def test_s27_prospective_depth_eleven_is_denied_with_zero_child():
    repository = InMemoryWorkItemRepository()
    for lineage in _complete_depth_ten_lineage():
        repository._lineages.create(lineage)
    service = WorkItemService(
        repository,
        authorization_source=Authorization(),
        id_factory=lambda: CHILD_ID,
        clock=lambda: NOW_DT,
        delegation_guard_enabled=True,
    )

    with pytest.raises(WorkItemError) as denied:
        service.create(_nested_payload())
    assert denied.value.error_code == "wc.delegation_hop_limit_exceeded"
    assert repository.get(tenant_id=TENANT, work_item_id=CHILD_ID) is None
    assert repository.get_lineage(tenant_id=TENANT, work_item_id=CHILD_ID) is None


def test_s27_current_depth_ten_work_item_can_still_route_and_claim():
    repository = InMemoryWorkItemRepository()
    WorkItemService(
        repository,
        authorization_source=Authorization(),
        id_factory=lambda: DEPTH10_ID,
        clock=lambda: NOW_DT,
    ).create(_first_payload("delegation-p8-s27-depth-ten"))
    for lineage in _complete_depth_ten_lineage():
        repository._lineages.create(lineage)
    coordination_repository = InMemoryCoordinationRepository(repository)
    repository.bind_parent_claim_authority_source(coordination_repository)
    ids = iter(
        (
            "27500000-0000-4000-8000-000000000001",
            "27500000-0000-4000-8000-000000000002",
            "27500000-0000-4000-8000-000000000003",
            "27500000-0000-4000-8000-000000000004",
            "27500000-0000-4000-8000-000000000005",
            "27500000-0000-4000-8000-000000000006",
        )
    )
    coordination = WorkCoordinationService(
        coordination_repository,
        candidate_source=Agents(),
        authorization_source=Authorization(),
        id_factory=lambda: next(ids),
        token_factory=lambda: "p8-s27-lease",
        clock=lambda: NOW_DT,
    )

    coordination.route(tenant_id=TENANT, work_item_id=DEPTH10_ID, expected_version=1)
    result = coordination.claim(
        tenant_id=TENANT, work_item_id=DEPTH10_ID, expected_version=2
    )
    assert result["work_item"]["state"] == "ASSIGNED"
    assert repository.get_lineage(
        tenant_id=TENANT, work_item_id=DEPTH10_ID
    )["delegation_depth"] == 10


def test_s27_claim_does_not_increment_first_level_depth():
    repository = InMemoryWorkItemRepository()
    coordination_repository = InMemoryCoordinationRepository(repository)
    repository.bind_parent_claim_authority_source(coordination_repository)
    WorkItemService(
        repository,
        authorization_source=Authorization(),
        id_factory=lambda: ROOT_ID,
        clock=lambda: NOW_DT,
        delegation_guard_enabled=True,
    ).create(_first_payload("delegation-p8-s27-root"))
    ids = iter(
        (
            "27600000-0000-4000-8000-000000000001",
            "27600000-0000-4000-8000-000000000002",
            "27600000-0000-4000-8000-000000000003",
            "27600000-0000-4000-8000-000000000004",
            "27600000-0000-4000-8000-000000000005",
            "27600000-0000-4000-8000-000000000006",
        )
    )
    coordination = WorkCoordinationService(
        coordination_repository,
        candidate_source=Agents(),
        authorization_source=Authorization(),
        id_factory=lambda: next(ids),
        token_factory=lambda: "p8-s27-root-lease",
        clock=lambda: NOW_DT,
    )
    before = repository.get_lineage(tenant_id=TENANT, work_item_id=ROOT_ID)
    coordination.route(tenant_id=TENANT, work_item_id=ROOT_ID, expected_version=1)
    coordination.claim(tenant_id=TENANT, work_item_id=ROOT_ID, expected_version=2)
    after = repository.get_lineage(tenant_id=TENANT, work_item_id=ROOT_ID)
    assert before == after
    assert after["delegation_depth"] == 1
