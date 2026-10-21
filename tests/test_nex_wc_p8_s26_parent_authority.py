from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from nex_runtime import InMemoryJobQueue
from nex_wc import coordination as coordination_module
from nex_wc import work_items as work_item_module
from nex_wc.coordination import (
    CoordinationError,
    InMemoryCoordinationRepository,
    SqlAlchemyCoordinationRepository,
    WorkCoordinationService,
)
from nex_wc.handoff_delivery import (
    HandoffDeliveryError,
    enqueue_pending_handoffs,
    run_handoff_delivery_job,
)
from nex_wc.work_items import (
    InMemoryWorkItemRepository,
    SqlAlchemyWorkItemRepository,
    WorkItemError,
    WorkItemService,
)

TENANT = "tenant-p8-s26"
PROJECT = "project-p8-s26"
IA_ID = "26100000-0000-4000-8000-000000000001"
PA_ID = "26100000-0000-4000-8000-000000000002"
OTHER_PA_ID = "26100000-0000-4000-8000-000000000003"
ROOT_ID = "26200000-0000-4000-8000-000000000001"
CHILD_ID = "26200000-0000-4000-8000-000000000002"
PARENT_EXECUTION_ID = "26300000-0000-4000-8000-000000000001"
NOW_DT = datetime(2026, 10, 21, 15, 0, tzinfo=UTC)
NOW = "2026-10-21T15:00:00Z"


class Authorization:
    def effective_authorization(self, **_kwargs):
        return {
            "active": True,
            "scopes": ["work:delegate", "work:claim"],
            "revision_hash": "d" * 64,
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


def _first_payload() -> dict[str, object]:
    return {
        "delegation_spec": {
            "schema_version": "1.0",
            "delegation_id": "delegation-p8-s26-root",
            "tenant_id": TENANT,
            "parent_agent_execution_id": "ia-execution-p8-s26",
            "parent_executable_plan_id": "ia-plan-p8-s26",
            "parent_executable_step_id": "ia-step-p8-s26",
            "delegation_revision": 1,
            "goal": "Create a claimed parent for nested delegation.",
            "work_class": "ANALYSIS",
            "required_agent_type": "PA",
            "required_capability": "FINANCE.PROJECT_BUDGET_CHECK",
            "project_ref": {"entity_type": "PROJECT", "entity_id": PROJECT},
            "project_scope_ref": PROJECT,
            "result_contract_ref": "contract://nex/wc/parent/v1",
            "completion_policy": "OWNER_SUBMITS",
            "correlation_id": "correlation-p8-s26",
        },
        "requester": {"entity_type": "AGENT", "entity_id": IA_ID},
        "accountable_owner": {"entity_type": "USER", "entity_id": "owner-p8"},
    }


def _nested_payload(**overrides) -> dict[str, object]:
    spec = {
        "schema_version": "1.1",
        "delegation_id": "delegation-p8-s26-child",
        "tenant_id": TENANT,
        "parent_agent_execution_id": PARENT_EXECUTION_ID,
        "parent_executable_plan_id": "pa-plan-p8-s26",
        "parent_executable_step_id": "pa-step-p8-s26",
        "delegation_revision": 1,
        "goal": "Create one nested delegated child.",
        "work_class": "ANALYSIS",
        "required_agent_type": "EA",
        "required_capability": "FINANCE.PROJECT_BUDGET_CHECK",
        "project_ref": {"entity_type": "PROJECT", "entity_id": PROJECT},
        "project_scope_ref": PROJECT,
        "result_contract_ref": "contract://nex/wc/child/v1",
        "completion_policy": "OWNER_SUBMITS",
        "correlation_id": "correlation-p8-s26",
        "parent_work_item_id": ROOT_ID,
        "parent_claim_ref": overrides.pop("parent_claim_ref"),
        "parent_claim_generation": overrides.pop("parent_claim_generation", 1),
        "delegating_agent_ref": {
            "agent_id": PA_ID,
            "agent_type": "PA",
        },
    }
    spec.update(overrides)
    return {
        "delegation_spec": spec,
        "requester": {"entity_type": "AGENT", "entity_id": PA_ID},
        "accountable_owner": {"entity_type": "USER", "entity_id": "owner-p8"},
    }


def _claimed_parent():
    work_items = InMemoryWorkItemRepository()
    coordination = InMemoryCoordinationRepository(work_items)
    work_items.bind_parent_claim_authority_source(coordination)
    root_service = WorkItemService(
        work_items,
        authorization_source=Authorization(),
        id_factory=lambda: ROOT_ID,
        clock=lambda: NOW_DT,
        delegation_guard_enabled=True,
    )
    root_service.create(_first_payload())
    ids = iter(
        (
            "26400000-0000-4000-8000-000000000001",
            "26400000-0000-4000-8000-000000000002",
            "26400000-0000-4000-8000-000000000003",
            "26400000-0000-4000-8000-000000000004",
            "26400000-0000-4000-8000-000000000005",
            "26400000-0000-4000-8000-000000000006",
        )
    )
    service = WorkCoordinationService(
        coordination,
        candidate_source=Agents(),
        authorization_source=Authorization(),
        id_factory=lambda: next(ids),
        token_factory=lambda: "p8-s26-lease",
        clock=lambda: NOW_DT,
    )
    service.route(tenant_id=TENANT, work_item_id=ROOT_ID, expected_version=1)
    claim = service.claim(tenant_id=TENANT, work_item_id=ROOT_ID, expected_version=2)
    coordination.mark_handoff_enqueued(
        outbox_id=claim["outbox_id"],
        event_id=claim["event_id"],
        job_id="job-p8-s26",
        updated_at=NOW,
    )
    coordination.mark_handoff_delivered(
        outbox_id=claim["outbox_id"],
        event_id=claim["event_id"],
        job_id="job-p8-s26",
        updated_at=NOW,
        agent_execution_id=PARENT_EXECUTION_ID,
    )
    return work_items, coordination, claim


def _child_service(work_items, *, clock=lambda: NOW_DT):
    return WorkItemService(
        work_items,
        authorization_source=Authorization(),
        id_factory=lambda: CHILD_ID,
        clock=clock,
        delegation_guard_enabled=True,
    )


def test_s26_nested_child_requires_and_persists_current_parent_authority():
    work_items, _, claim = _claimed_parent()
    result = _child_service(work_items).create(
        _nested_payload(parent_claim_ref=claim["claim"]["claim_id"])
    )
    lineage = work_items.get_lineage(tenant_id=TENANT, work_item_id=CHILD_ID)

    assert result["created"] is True
    assert lineage is not None
    assert lineage["root_work_item_id"] == ROOT_ID
    assert lineage["parent_work_item_id"] == ROOT_ID
    assert lineage["parent_claim_ref"] == claim["claim"]["claim_id"]
    assert lineage["parent_claim_generation"] == 1
    assert lineage["parent_agent_execution_id"] == PARENT_EXECUTION_ID
    assert lineage["delegation_depth"] == 2


@pytest.mark.parametrize(
    ("mutate", "spec_changes", "clock"),
    [
        (lambda repo, key: repo._claims[key][0].update(state="EXPIRED"), {}, lambda: NOW_DT),
        (lambda repo, key: None, {"parent_claim_generation": 2}, lambda: NOW_DT),
        (
            lambda repo, key: repo._claims[key][0].update(
                lease_expires_at=(NOW_DT - timedelta(seconds=1)).isoformat()
            ),
            {},
            lambda: NOW_DT,
        ),
        (lambda repo, key: repo._assignments[key].update(status="RELEASED"), {}, lambda: NOW_DT),
        (lambda repo, key: repo._assignments[key].update(agent_id=OTHER_PA_ID), {}, lambda: NOW_DT),
        (
            lambda repo, key: repo._assignments[key].update(
                agent_execution_id="different-execution"
            ),
            {},
            lambda: NOW_DT,
        ),
    ],
)
def test_s26_stale_parent_authority_creates_zero_child(mutate, spec_changes, clock):
    work_items, coordination, claim = _claimed_parent()
    mutate(coordination, (TENANT, ROOT_ID))
    payload = _nested_payload(
        parent_claim_ref=claim["claim"]["claim_id"], **spec_changes
    )

    with pytest.raises(WorkItemError) as denied:
        _child_service(work_items, clock=clock).create(payload)
    assert denied.value.error_code == "wc.delegation_parent_authority_stale"
    assert work_items.get(tenant_id=TENANT, work_item_id=CHILD_ID) is None
    assert work_items.get_lineage(tenant_id=TENANT, work_item_id=CHILD_ID) is None


def test_s26_requester_and_parent_identity_must_match_nested_lineage():
    work_items, _, claim = _claimed_parent()
    payload = _nested_payload(parent_claim_ref=claim["claim"]["claim_id"])
    payload["requester"] = {"entity_type": "AGENT", "entity_id": OTHER_PA_ID}
    with pytest.raises(WorkItemError) as requester:
        _child_service(work_items).create(payload)
    assert requester.value.error_code == "wc.delegation_parent_authority_stale"

    payload = _nested_payload(
        parent_claim_ref=claim["claim"]["claim_id"],
        parent_work_item_id="26200000-0000-4000-8000-000000000099",
    )
    with pytest.raises(WorkItemError) as parent:
        _child_service(work_items).create(payload)
    assert parent.value.error_code == "wc.delegation_parent_authority_stale"


def test_s26_delegation_spec_versions_are_fail_closed():
    payload = _first_payload()["delegation_spec"]
    payload["parent_work_item_id"] = ROOT_ID
    with pytest.raises(WorkItemError):
        _child_service(InMemoryWorkItemRepository()).create(
            {
                "delegation_spec": payload,
                "requester": {"entity_type": "AGENT", "entity_id": IA_ID},
                "accountable_owner": {"entity_type": "USER", "entity_id": "owner"},
            }
        )

    nested = _nested_payload(parent_claim_ref="26400000-0000-4000-8000-000000000003")
    del nested["delegation_spec"]["delegating_agent_ref"]
    with pytest.raises(WorkItemError):
        _child_service(InMemoryWorkItemRepository()).create(nested)


def test_s26_handoff_delivery_requires_and_acknowledges_execution_identity():
    work_items, coordination, claim = _claimed_parent()
    authority = coordination.get_parent_claim_authority(
        tenant_id=TENANT, claim_id=claim["claim"]["claim_id"]
    )
    assert authority is not None
    assert authority["agent_execution_id"] == PARENT_EXECUTION_ID

    class MissingExecutionClient:
        def deliver(self, _envelope):
            return {}

    event = coordination._outbox[(TENANT, claim["outbox_id"])]
    event["delivery_state"] = "PENDING"
    event["enqueued_job_id"] = None
    coordination._assignments[(TENANT, ROOT_ID)]["agent_execution_id"] = None
    job = enqueue_pending_handoffs(
        store=coordination, queue=InMemoryJobQueue(), clock=lambda: NOW_DT
    )[0]
    with pytest.raises(HandoffDeliveryError) as missing:
        run_handoff_delivery_job(
            job, store=coordination, client=MissingExecutionClient(), clock=lambda: NOW_DT
        )
    assert missing.value.error_code == "wc.handoff_value_invalid"


def test_s26_execution_acknowledgement_is_immutable():
    _, coordination, claim = _claimed_parent()
    with pytest.raises(CoordinationError) as conflict:
        coordination.mark_handoff_delivered(
            outbox_id=claim["outbox_id"],
            event_id=claim["event_id"],
            job_id="job-p8-s26",
            updated_at=NOW,
            agent_execution_id="different-execution",
        )
    assert conflict.value.error_code == "wc.handoff_execution_conflict"


def test_s26_migration_reuses_assignment_and_creates_no_second_table():
    migration = (
        __import__("pathlib").Path(__file__).parents[1]
        / "database/nex-wc/migrations/1005_wc_assignment_execution.sql"
    ).read_text(encoding="utf-8")
    assert "ALTER TABLE wc_assignment" in migration
    assert "agent_execution_id" in migration
    assert "CREATE TABLE" not in migration


def test_s26_sql_child_admission_locks_parent_authority_before_insert(monkeypatch):
    work_items, _, claim = _claimed_parent()
    _child_service(work_items).create(
        _nested_payload(parent_claim_ref=claim["claim"]["claim_id"])
    )
    record = work_items.get(tenant_id=TENANT, work_item_id=CHILD_ID)
    lineage = work_items.get_lineage(tenant_id=TENANT, work_item_id=CHILD_ID)
    assert record is not None and lineage is not None
    calls = []

    class Result:
        rowcount = 1

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, statement, _params):
            calls.append(str(statement))
            return Result()

        def commit(self):
            calls.append("COMMIT")

    authority = {
        "work_item_id": ROOT_ID,
        "claim_id": claim["claim"]["claim_id"],
        "claim_assignment_id": claim["claim"]["assignment_id"],
        "claim_generation": 1,
        "claim_state": "ACTIVE",
        "lease_expires_at": (NOW_DT + timedelta(minutes=5)).isoformat(),
        "assignment_id": claim["claim"]["assignment_id"],
        "assignment_claim_generation": 1,
        "assignment_status": "ACTIVE",
        "agent_id": PA_ID,
        "agent_type": "PA",
        "agent_execution_id": PARENT_EXECUTION_ID,
    }
    monkeypatch.setattr(
        work_item_module,
        "_load_parent_claim_authority_in_session",
        lambda *_args, **_kwargs: calls.append("AUTHORITY") or authority,
    )
    monkeypatch.setattr(
        work_item_module,
        "_load_by_semantic_key",
        lambda *_args, **_kwargs: record,
    )
    monkeypatch.setattr(
        work_item_module,
        "create_delegation_lineage_in_session",
        lambda *_args, **_kwargs: calls.append("LINEAGE") or (lineage, True),
    )
    saved, created = SqlAlchemyWorkItemRepository(lambda: Session()).create(
        record, lineage=lineage
    )
    assert saved == record and created is True
    assert calls[0] == "AUTHORITY"
    assert calls[-2:] == ["LINEAGE", "COMMIT"]
    assert "FOR UPDATE OF claim, assignment" in work_item_module._SELECT_PARENT_CLAIM_AUTHORITY_SQL


def test_s26_sql_execution_ack_is_atomic_and_conflict_safe(monkeypatch):
    outbox = {
        "tenant_id": TENANT,
        "outbox_id": "outbox",
        "event_id": "event",
        "work_item_id": ROOT_ID,
        "event_type": "CLAIM_EXECUTION_HANDOFF",
        "event_payload": {"assignment_ref": "assignment"},
        "delivery_state": "DELIVERED",
        "enqueued_job_id": "job",
        "created_at": NOW,
        "updated_at": NOW,
    }

    class Result:
        def __init__(self, rowcount):
            self.rowcount = rowcount

    class Session:
        def __init__(self, rowcount):
            self.rowcount = rowcount
            self.committed = False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, *_args, **_kwargs):
            return Result(self.rowcount)

        def commit(self):
            self.committed = True

    monkeypatch.setattr(
        coordination_module,
        "_transition_handoff_outbox_in_session",
        lambda *_args, **_kwargs: outbox,
    )
    session = Session(1)
    saved = SqlAlchemyCoordinationRepository(lambda: session).mark_handoff_delivered(
        outbox_id="outbox",
        event_id="event",
        job_id="job",
        updated_at=NOW,
        agent_execution_id=PARENT_EXECUTION_ID,
    )
    assert saved == outbox
    assert session.committed is True

    with pytest.raises(CoordinationError) as conflict:
        SqlAlchemyCoordinationRepository(lambda: Session(0)).mark_handoff_delivered(
            outbox_id="outbox",
            event_id="event",
            job_id="job",
            updated_at=NOW,
            agent_execution_id=PARENT_EXECUTION_ID,
        )
    assert conflict.value.error_code == "wc.handoff_execution_conflict"
