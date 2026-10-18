from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from nex_ae_api.agent_execution import (
    AgentExecutionAdmissionService,
    SqlAlchemyAgentExecutionRepository,
)
from nex_ae_api.agent_identity import SqlAlchemyAgentIdentityRegistry
from nex_runtime import (
    InMemoryWorkerHeartbeatStore,
    SqlAlchemyJobQueue,
    WorkerHeartbeatEmitter,
)
from nex_wc.coordination import SqlAlchemyCoordinationRepository, WorkCoordinationService
from nex_wc.handoff_delivery import (
    enqueue_pending_handoffs,
    run_handoff_delivery_worker_once,
)
from nex_wc.work_items import SqlAlchemyWorkItemRepository, WorkItemService


pytestmark = pytest.mark.skipif(
    not os.getenv("NEX_WC_TEST_DATABASE_URL")
    or not os.getenv("NEX_AE_TEST_DATABASE_URL"),
    reason="NEX_WC_TEST_DATABASE_URL and NEX_AE_TEST_DATABASE_URL are required",
)

NOW_DT = datetime(2026, 10, 18, 8, 0, tzinfo=UTC)
NOW = "2026-10-18T08:00:00Z"
TENANT = "p7-s4-pg-tenant"
PROJECT = "p7-s4-pg-project"
REQUESTER = "p7-s4-pg-requester"
AGENT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaa44"
EXECUTION_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbb44"
PROFILE = "agent-profile://pa/project-budget-read/v1"


class _Agents:
    def __init__(self, registry):
        self.registry = registry

    def list_agents(self, *, tenant_id, agent_type, project_id):
        return self.registry.list_eligible_agents(
            tenant_id=tenant_id,
            agent_type=agent_type,
            project_id=project_id,
        )

    def get_agent(self, *, tenant_id, agent_id):
        return self.registry.get_agent(tenant_id=tenant_id, agent_id=agent_id)


class _Authorization:
    def effective_authorization(self, **kwargs):
        return {"active": True, "scopes": ["work:claim"], "revision_hash": "e" * 64}


class _DirectClient:
    def __init__(self, admission):
        self.admission = admission

    def deliver(self, envelope):
        result = self.admission.admit_claimed_work(
            event_id=envelope["event_id"],
            requester_ref=envelope["requester_ref"],
            handoff=envelope["handoff"],
        )
        return {"agent_execution_id": result.execution["agent_execution_id"]}


def _payload():
    return {
        "delegation_spec": {
            "schema_version": "1.0",
            "delegation_id": "p7-s4-pg-delegation",
            "tenant_id": TENANT,
            "parent_agent_execution_id": "p7-s4-pg-parent-execution",
            "parent_executable_plan_id": "p7-s4-pg-parent-plan",
            "parent_executable_step_id": "p7-s4-pg-parent-step",
            "delegation_revision": 1,
            "goal": "Check project budget",
            "work_class": "ANALYSIS",
            "required_agent_type": "PA",
            "required_capability": "FINANCE.PROJECT_BUDGET_CHECK",
            "project_ref": {"entity_type": "PROJECT", "entity_id": PROJECT},
            "project_scope_ref": PROJECT,
            "result_contract_ref": "urn:nex:result:budget:1",
            "completion_policy": "OWNER_SUBMITS",
            "correlation_id": "p7-s4-pg-trace",
            "causation_id": "p7-s4-pg-cause",
        },
        "requester": {"entity_type": "USER", "entity_id": REQUESTER},
        "accountable_owner": {"entity_type": "USER", "entity_id": REQUESTER},
    }


def _cleanup_wc(connection):
    params = {"tenant_id": TENANT}
    job_ids = connection.execute(
        text("SELECT enqueued_job_id FROM wc_event_outbox WHERE tenant_id = :tenant_id"),
        params,
    ).scalars().all()
    if job_ids:
        connection.execute(
            text("DELETE FROM service_jobs WHERE job_id = ANY(:job_ids)"),
            {"job_ids": job_ids},
        )
    connection.execute(text("DELETE FROM wc_event_outbox WHERE tenant_id = :tenant_id"), params)
    connection.execute(text("DELETE FROM wc_claim WHERE tenant_id = :tenant_id"), params)
    connection.execute(text("DELETE FROM wc_assignment WHERE tenant_id = :tenant_id"), params)
    connection.execute(text("DELETE FROM wc_routing_decision WHERE tenant_id = :tenant_id"), params)
    connection.execute(text("DELETE FROM wc_work_item WHERE tenant_id = :tenant_id"), params)


def _cleanup_ae(connection):
    params = {"tenant_id": TENANT}
    connection.execute(text("DELETE FROM ae_claim_handoff_inbox WHERE tenant_id = :tenant_id"), params)
    connection.execute(text("DELETE FROM ae_agent_execution WHERE tenant_id = :tenant_id"), params)
    connection.execute(text("DELETE FROM ae_agent_identity WHERE tenant_id = :tenant_id"), params)


def test_s4_actual_postgres_wc_job_to_ae_execution_restart_and_zero_residue():
    wc_engine = create_engine(os.environ["NEX_WC_TEST_DATABASE_URL"])
    ae_engine = create_engine(os.environ["NEX_AE_TEST_DATABASE_URL"])
    wc_sessions = sessionmaker(bind=wc_engine, expire_on_commit=False)
    ae_sessions = sessionmaker(bind=ae_engine, expire_on_commit=False)
    with wc_engine.begin() as connection:
        _cleanup_wc(connection)
    with ae_engine.begin() as connection:
        _cleanup_ae(connection)

    try:
        registry = SqlAlchemyAgentIdentityRegistry(
            ae_sessions, id_factory=lambda: AGENT_ID, clock=lambda: NOW_DT
        )
        registry.register_agent(
            tenant_id=TENANT,
            agent_type="PA",
            profile_ref=PROFILE,
            project_id=PROJECT,
        )
        admission_ids = iter(
            (EXECUTION_ID, "cccccccc-cccc-4ccc-8ccc-cccccccccc44")
        )
        admission = AgentExecutionAdmissionService(
            identities=registry,
            executions=SqlAlchemyAgentExecutionRepository(ae_sessions),
            mode="required",
            id_factory=lambda: next(admission_ids),
            clock=lambda: NOW_DT,
        )

        work_ids = iter(
            (
                "11111111-1111-4111-8111-111111111144",
                "22222222-2222-4222-8222-222222222244",
                "33333333-3333-4333-8333-333333333344",
                "44444444-4444-4444-8444-444444444444",
                "55555555-5555-4555-8555-555555555544",
                "66666666-6666-4666-8666-666666666644",
                "77777777-7777-4777-8777-777777777744",
            )
        )
        item = WorkItemService(
            SqlAlchemyWorkItemRepository(wc_sessions),
            id_factory=lambda: next(work_ids),
            clock=lambda: NOW_DT,
        ).create(_payload())["work_item"]
        wc_repository = SqlAlchemyCoordinationRepository(wc_sessions)
        coordination = WorkCoordinationService(
            wc_repository,
            candidate_source=_Agents(registry),
            authorization_source=_Authorization(),
            id_factory=lambda: next(work_ids),
            token_factory=lambda: "p7-s4-pg-lease",
            clock=lambda: NOW_DT,
        )
        coordination.route(
            tenant_id=TENANT, work_item_id=item["work_item_id"], expected_version=1
        )
        claimed = coordination.claim(
            tenant_id=TENANT, work_item_id=item["work_item_id"], expected_version=2
        )

        queue = SqlAlchemyJobQueue(wc_sessions)
        jobs = enqueue_pending_handoffs(
            store=wc_repository, queue=queue, clock=lambda: NOW_DT
        )
        assert len(jobs) == 1
        heartbeat = WorkerHeartbeatEmitter(
            service_id="nex-wc",
            worker_id="p7-s4-pg-worker",
            worker_type="wc.claim_handoff.delivery.worker",
            store=InMemoryWorkerHeartbeatStore(),
            started_at=NOW,
        )
        run = run_handoff_delivery_worker_once(
            queue=queue,
            store=wc_repository,
            client=_DirectClient(admission),
            heartbeat_emitter=heartbeat,
            worker_id="p7-s4-pg-worker",
            clock=lambda: NOW,
        )
        assert run.status == "SUCCEEDED"
        assert run.handler_result["agent_execution_id"] == EXECUTION_ID

        restarted_ae = SqlAlchemyAgentExecutionRepository(ae_sessions).get(
            TENANT, EXECUTION_ID
        )
        restarted_event = SqlAlchemyCoordinationRepository(wc_sessions).load_handoff_event(
            outbox_id=claimed["outbox_id"], event_id=claimed["event_id"]
        )
        assert restarted_ae["source_type"] == "CLAIMED_WORKITEM"
        assert restarted_ae["claim_ref"] == claimed["claim"]["claim_id"]
        assert restarted_event["delivery_state"] == "DELIVERED"
        with ae_engine.begin() as connection:
            assert connection.execute(
                text("SELECT count(*) FROM ae_claim_handoff_inbox WHERE tenant_id = :tenant_id"),
                {"tenant_id": TENANT},
            ).scalar_one() == 1
    finally:
        with wc_engine.begin() as connection:
            _cleanup_wc(connection)
            wc_remaining = connection.execute(
                text("SELECT count(*) FROM wc_work_item WHERE tenant_id = :tenant_id"),
                {"tenant_id": TENANT},
            ).scalar_one()
        with ae_engine.begin() as connection:
            _cleanup_ae(connection)
            ae_remaining = connection.execute(
                text("SELECT count(*) FROM ae_agent_identity WHERE tenant_id = :tenant_id"),
                {"tenant_id": TENANT},
            ).scalar_one()
        wc_engine.dispose()
        ae_engine.dispose()
    assert (wc_remaining, ae_remaining) == (0, 0)
