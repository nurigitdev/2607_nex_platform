from __future__ import annotations

import json
import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from nex_wc.coordination import SqlAlchemyCoordinationRepository, WorkCoordinationService
from nex_wc.work_items import SqlAlchemyWorkItemRepository, WorkItemService


pytestmark = pytest.mark.skipif(
    not os.getenv("NEX_WC_TEST_DATABASE_URL"),
    reason="NEX_WC_TEST_DATABASE_URL is required for protected WC PostgreSQL smoke",
)
NOW = datetime(2026, 10, 18, 4, 30, tzinfo=UTC)
TENANT = "p7-s3-pg-tenant"
AGENT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa3"
PROFILE = "agent-profile://pa/project-budget-read/v1"


class _Agents:
    candidate = {
        "schema_version": "2.1",
        "tenant_id": TENANT,
        "agent_id": AGENT_ID,
        "agent_type": "PA",
        "profile_ref": PROFILE,
        "status": "ACTIVE",
        "project_id": "project-s3-pg",
        "created_at": "2026-10-18T04:00:00Z",
        "version": 1,
    }

    def list_agents(self, **kwargs):
        return [dict(self.candidate)]

    def get_agent(self, **kwargs):
        return dict(self.candidate)


class _Authorization:
    def effective_authorization(self, **kwargs):
        return {"active": True, "scopes": ["work:claim"], "revision_hash": "b" * 64}


def _payload():
    return {
        "delegation_spec": {
            "schema_version": "1.0",
            "delegation_id": "delegation-s3-pg",
            "tenant_id": TENANT,
            "parent_agent_execution_id": "parent-execution-s3-pg",
            "parent_executable_plan_id": "parent-plan-s3-pg",
            "parent_executable_step_id": "parent-step-s3-pg",
            "delegation_revision": 1,
            "goal": "Check project budget",
            "work_class": "ANALYSIS",
            "required_agent_type": "PA",
            "required_capability": "FINANCE.PROJECT_BUDGET_CHECK",
            "project_ref": {"entity_type": "PROJECT", "entity_id": "project-s3-pg"},
            "project_scope_ref": "project-s3-pg",
            "result_contract_ref": "urn:nex:result:budget:1",
            "completion_policy": "OWNER_SUBMITS",
            "correlation_id": "trace-s3-pg",
            "causation_id": "cause-s3-pg",
        },
        "requester": {"entity_type": "USER", "entity_id": "requester-s3-pg"},
        "accountable_owner": {"entity_type": "USER", "entity_id": "owner-s3-pg"},
    }


def _cleanup(connection):
    params = {"tenant_id": TENANT}
    connection.execute(text("DELETE FROM wc_event_outbox WHERE tenant_id = :tenant_id"), params)
    connection.execute(text("DELETE FROM wc_claim WHERE tenant_id = :tenant_id"), params)
    connection.execute(text("DELETE FROM wc_assignment WHERE tenant_id = :tenant_id"), params)
    connection.execute(text("DELETE FROM wc_routing_decision WHERE tenant_id = :tenant_id"), params)
    connection.execute(text("DELETE FROM wc_work_item WHERE tenant_id = :tenant_id"), params)


def test_s3_actual_postgres_atomic_claim_restart_and_zero_residue():
    engine = create_engine(os.environ["NEX_WC_TEST_DATABASE_URL"])
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    ids = iter(
        (
            "11111111-1111-4111-8111-111111111133",
            "22222222-2222-4222-8222-222222222233",
            "33333333-3333-4333-8333-333333333333",
            "44444444-4444-4444-8444-444444444433",
            "55555555-5555-4555-8555-555555555533",
            "66666666-6666-4666-8666-666666666633",
            "77777777-7777-4777-8777-777777777733",
        )
    )
    with engine.begin() as connection:
        _cleanup(connection)
    try:
        item = WorkItemService(
            SqlAlchemyWorkItemRepository(sessions),
            id_factory=lambda: next(ids),
            clock=lambda: NOW,
        ).create(_payload())["work_item"]
        service = WorkCoordinationService(
            SqlAlchemyCoordinationRepository(sessions),
            candidate_source=_Agents(),
            authorization_source=_Authorization(),
            id_factory=lambda: next(ids),
            token_factory=lambda: "s3-postgres-lease-secret",
            clock=lambda: NOW,
        )
        assert service.route(
            tenant_id=TENANT, work_item_id=item["work_item_id"], expected_version=1
        )["decision"] == "ROUTED"
        claimed = service.claim(
            tenant_id=TENANT, work_item_id=item["work_item_id"], expected_version=2
        )
        assert claimed["claim"]["claim_generation"] == 1

        restarted = SqlAlchemyCoordinationRepository(sessions).get_work_item(
            tenant_id=TENANT, work_item_id=item["work_item_id"]
        )
        assert restarted["work_item"]["state"] == "ASSIGNED"
        with engine.begin() as connection:
            counts = {
                table: connection.execute(
                    text(f"SELECT count(*) FROM {table} WHERE tenant_id = :tenant_id"),
                    {"tenant_id": TENANT},
                ).scalar_one()
                for table in (
                    "wc_work_item",
                    "wc_routing_decision",
                    "wc_assignment",
                    "wc_claim",
                    "wc_event_outbox",
                )
            }
            raw = connection.execute(
                text("SELECT event_payload::text FROM wc_event_outbox WHERE tenant_id = :tenant_id"),
                {"tenant_id": TENANT},
            ).scalar_one()
        assert set(counts.values()) == {1}
        assert "s3-postgres-lease-secret" not in raw
        assert "CLAIM_EXECUTION_HANDOFF" not in json.dumps(claimed["claim"])
    finally:
        with engine.begin() as connection:
            _cleanup(connection)
            remaining = connection.execute(
                text("SELECT count(*) FROM wc_work_item WHERE tenant_id = :tenant_id"),
                {"tenant_id": TENANT},
            ).scalar_one()
        engine.dispose()
    assert remaining == 0


def test_s3_actual_postgres_repository_conflicts_are_fail_closed():
    engine = create_engine(os.environ["NEX_WC_TEST_DATABASE_URL"])
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    repository = SqlAlchemyCoordinationRepository(sessions)
    with engine.begin() as connection:
        _cleanup(connection)
    try:
        assert repository.get_work_item(
            tenant_id=TENANT, work_item_id="00000000-0000-4000-8000-000000000001"
        ) is None
        with pytest.raises(Exception) as missing_route:
            repository.save_routing_decision(
                tenant_id=TENANT,
                work_item_id="00000000-0000-4000-8000-000000000001",
                expected_version=1,
                decision={"decision": "UNROUTABLE"},
            )
        assert getattr(missing_route.value, "error_code", None) == "wc.work_item_not_found"

        item = WorkItemService(
            SqlAlchemyWorkItemRepository(sessions),
            id_factory=lambda: "11111111-1111-4111-8111-111111111134",
            clock=lambda: NOW,
        ).create(_payload())["work_item"]
        with pytest.raises(Exception) as stale_route:
            repository.save_routing_decision(
                tenant_id=TENANT,
                work_item_id=item["work_item_id"],
                expected_version=2,
                decision={"decision": "UNROUTABLE"},
            )
        assert getattr(stale_route.value, "error_code", None) == "wc.work_item_route_conflict"

        service = WorkCoordinationService(
            repository,
            candidate_source=_Agents(),
            authorization_source=_Authorization(),
            id_factory=iter(
                (
                    "22222222-2222-4222-8222-222222222234",
                    "33333333-3333-4333-8333-333333333334",
                )
            ).__next__,
            clock=lambda: NOW,
        )
        route = service.route(
            tenant_id=TENANT, work_item_id=item["work_item_id"], expected_version=1
        )
        with pytest.raises(Exception) as drifted_route:
            repository.commit_claim(
                tenant_id=TENANT,
                work_item_id=item["work_item_id"],
                expected_version=2,
                selected_agent={**_Agents.candidate, "agent_id": "different-agent"},
                authorization={
                    "subject_id": "requester-s3-pg",
                    "revision_hash": "b" * 64,
                    "checked_at": "2026-10-18T04:30:00Z",
                },
                identifiers={
                    "assignment_id": "44444444-4444-4444-8444-444444444434",
                    "claim_id": "55555555-5555-4555-8555-555555555534",
                    "handoff_id": "66666666-6666-4666-8666-666666666634",
                    "outbox_id": "77777777-7777-4777-8777-777777777734",
                    "event_id": "88888888-8888-4888-8888-888888888834",
                },
                lease_verifier="sha256:" + "d" * 64,
                lease_expires_at="2026-10-18T04:35:00Z",
                now="2026-10-18T04:30:00Z",
            )
        assert route["decision"] == "ROUTED"
        assert getattr(drifted_route.value, "error_code", None) == "wc.routing_decision_not_claimable"
    finally:
        with engine.begin() as connection:
            _cleanup(connection)
        engine.dispose()
