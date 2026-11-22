from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from nex_ae_api.agent_execution import (
    AgentExecutionAdmissionService,
    SqlAlchemyAgentExecutionRepository,
)
from nex_ae_api.agent_identity import SqlAlchemyAgentIdentityRegistry
from nex_ae_api.intent_policy import resolve_validated_intent_candidate
from nex_ae_api.work_intent import (
    SqlAlchemyWorkIntentRepository,
    build_work_intent_from_claimed_work,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from nex_wc.coordination import (
    SqlAlchemyCoordinationRepository,
    WorkCoordinationService,
)
from nex_wc.work_items import (
    SqlAlchemyWorkItemRepository,
    WorkItemError,
    WorkItemService,
)
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

pytestmark = pytest.mark.skipif(
    not os.getenv("NEX_WC_TEST_DATABASE_URL")
    or not os.getenv("NEX_AE_TEST_DATABASE_URL"),
    reason="NEX_WC_TEST_DATABASE_URL and NEX_AE_TEST_DATABASE_URL are required",
)

ROOT = Path(__file__).resolve().parents[1]
CONTEXT_EXAMPLE = (
    ROOT
    / "contracts"
    / "examples"
    / "service"
    / "ae_work_intent.business_transaction.v1_2.json"
)
TENANT = "cp-m1-01b3-pg"
PROJECT_ID = "77777777-7777-4777-8777-777777777777"
OWNER = "employee-100"
IA_AGENT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa3"
PA_AGENT_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb3"
WORK_ITEM_ID = "11111111-1111-4111-8111-1111111111b3"
BACKGROUND_EXECUTION_ID = "22222222-2222-4222-8222-2222222222b3"
BACKGROUND_WORK_INTENT_ID = "33333333-3333-4333-8333-3333333333b3"
NOW_DT = datetime(2026, 11, 16, 7, 0, tzinfo=UTC)
NOW = "2026-11-16T07:00:00Z"


class _Authorization:
    def effective_authorization(self, **_kwargs):
        return {
            "active": True,
            "scopes": ["work:delegate", "work:claim"],
            "revision_hash": "e" * 64,
        }


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


def _context() -> dict:
    return json.loads(CONTEXT_EXAMPLE.read_text(encoding="utf-8"))[
        "business_request_context"
    ]


def _payload(context: dict | None = None) -> dict:
    selected = context or _context()
    return {
        "work_item_id": WORK_ITEM_ID,
        "delegation_spec": {
            "schema_version": "1.2",
            "delegation_id": "cp-m1-01b3-delegation",
            "tenant_id": TENANT,
            "parent_agent_execution_id": (
                "44444444-4444-4444-8444-4444444444b3"
            ),
            "parent_executable_plan_id": "55555555-5555-4555-8555-5555555555b3",
            "parent_executable_step_id": "66666666-6666-4666-8666-6666666666b3",
            "delegation_revision": 1,
            "goal": "Prepare the admitted Project transaction.",
            "work_class": "BUSINESS_TRANSACTION",
            "required_agent_type": "PA",
            "required_capability": "FINANCE.VOUCHER.APPROVE_AND_POST",
            "project_ref": {"entity_type": "PROJECT", "entity_id": PROJECT_ID},
            "project_scope_ref": PROJECT_ID,
            "result_contract_ref": (
                "contract://nex/mybee/finance/journal-posting-result/v1"
            ),
            "completion_policy": "OWNER_SUBMITS",
            "correlation_id": "cp-m1-01b3-correlation",
            "causation_id": "66666666-6666-4666-8666-6666666666b3",
            "business_request_context": selected,
            "business_context_hash": selected["context_hash"],
        },
        "requester": {"entity_type": "AGENT", "entity_id": IA_AGENT_ID},
        "accountable_owner": {"entity_type": "USER", "entity_id": OWNER},
    }


def _cleanup_wc(connection) -> None:
    params = {"tenant_id": TENANT}
    connection.execute(
        text("DELETE FROM wc_event_outbox WHERE tenant_id = :tenant_id"), params
    )
    connection.execute(text("DELETE FROM wc_claim WHERE tenant_id = :tenant_id"), params)
    connection.execute(
        text("DELETE FROM wc_assignment WHERE tenant_id = :tenant_id"), params
    )
    connection.execute(
        text("DELETE FROM wc_routing_decision WHERE tenant_id = :tenant_id"), params
    )
    connection.execute(
        text("DELETE FROM wc_delegation_lineage WHERE tenant_id = :tenant_id"),
        params,
    )
    connection.execute(
        text("DELETE FROM wc_work_item WHERE tenant_id = :tenant_id"), params
    )


def _cleanup_ae(connection) -> None:
    params = {"tenant_id": TENANT}
    connection.execute(text("DELETE FROM ae_work_intent WHERE tenant_id = :tenant_id"), params)
    connection.execute(
        text("DELETE FROM ae_claim_handoff_inbox WHERE tenant_id = :tenant_id"),
        params,
    )
    connection.execute(
        text("DELETE FROM ae_agent_execution WHERE tenant_id = :tenant_id"), params
    )
    connection.execute(
        text("DELETE FROM ae_agent_identity WHERE tenant_id = :tenant_id"), params
    )


def test_01b3_actual_postgres_context_persistence_restart_replay_and_zero_residue():
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
            ae_sessions,
            id_factory=lambda: PA_AGENT_ID,
            clock=lambda: NOW_DT,
        )
        registry.register_agent(
            tenant_id=TENANT,
            agent_type="PA",
            profile_ref="agent-profile://nex-platform/project-agent/v1",
            project_id=PROJECT_ID,
        )

        work_items = SqlAlchemyWorkItemRepository(wc_sessions)
        item_service = WorkItemService(
            work_items,
            authorization_source=_Authorization(),
            clock=lambda: NOW_DT,
        )
        created = item_service.create(_payload())
        restarted = SqlAlchemyWorkItemRepository(wc_sessions).get(
            tenant_id=TENANT, work_item_id=WORK_ITEM_ID
        )
        assert restarted is not None
        assert restarted["delegation_spec"]["business_request_context"] == _context()

        changed = _context()
        changed["transaction"]["amount"] = "2451.00"
        changed["context_hash"] = semantic_sha256_hash_ref(
            {key: value for key, value in changed.items() if key != "context_hash"}
        )
        with pytest.raises(WorkItemError) as conflict:
            item_service.create(_payload(changed))
        assert conflict.value.error_code == "wc.work_item_idempotency_conflict"

        identifiers = iter(
            (
                "77777777-7777-4777-8777-7777777777b3",
                "88888888-8888-4888-8888-8888888888b3",
                "99999999-9999-4999-8999-9999999999b3",
                "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaab3",
                "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb4",
                "cccccccc-cccc-4ccc-8ccc-ccccccccccb3",
            )
        )
        coordination_repository = SqlAlchemyCoordinationRepository(wc_sessions)
        coordination = WorkCoordinationService(
            coordination_repository,
            candidate_source=_Agents(registry),
            authorization_source=_Authorization(),
            id_factory=lambda: next(identifiers),
            token_factory=lambda: "cp-m1-01b3-lease",
            clock=lambda: NOW_DT,
        )
        routed = coordination.route(
            tenant_id=TENANT,
            work_item_id=created["work_item"]["work_item_id"],
            expected_version=1,
        )
        assert routed["decision"] == "ROUTED"
        claimed = coordination.claim(
            tenant_id=TENANT,
            work_item_id=created["work_item"]["work_item_id"],
            expected_version=2,
        )
        assert claimed["planning_source"]["business_request_context"] == _context()

        admission = AgentExecutionAdmissionService(
            identities=registry,
            executions=SqlAlchemyAgentExecutionRepository(ae_sessions),
            mode="required",
            id_factory=lambda: BACKGROUND_EXECUTION_ID,
            clock=lambda: NOW_DT,
        )
        admitted = admission.admit_claimed_work(
            event_id=claimed["event_id"],
            requester_ref=OWNER,
            handoff=claimed["handoff"],
            planning_source=claimed["planning_source"],
        )
        assert admitted.execution is not None
        restarted_source = SqlAlchemyAgentExecutionRepository(
            ae_sessions
        ).get_claimed_planning_source(TENANT, BACKGROUND_EXECUTION_ID)
        assert restarted_source == claimed["planning_source"]

        decision = resolve_validated_intent_candidate(
            {
                "intent_label": "FINANCE.VOUCHER.APPROVE_AND_POST",
                "suggested_execution_mode": "GENERAL_ANSWER",
                "confidence": 0.96,
            }
        )
        intent = build_work_intent_from_claimed_work(
            execution_id=BACKGROUND_EXECUTION_ID,
            actor_ref=f"OA:SUBJECT:{OWNER}",
            received_at=NOW,
            planning_source=restarted_source,
            intent_decision=decision,
            input_context_hash="sha256:" + "9" * 64,
            work_intent_id=BACKGROUND_WORK_INTENT_ID,
        )
        intents = SqlAlchemyWorkIntentRepository(ae_sessions)
        intents.save(tenant_id=TENANT, work_intent=intent, created_at=NOW)
        assert SqlAlchemyWorkIntentRepository(ae_sessions).get(
            tenant_id=TENANT,
            work_intent_id=BACKGROUND_WORK_INTENT_ID,
        ) == intent
    finally:
        with ae_engine.begin() as connection:
            _cleanup_ae(connection)
            assert connection.execute(
                text(
                    "SELECT count(*) FROM ae_agent_execution "
                    "WHERE tenant_id = :tenant_id"
                ),
                {"tenant_id": TENANT},
            ).scalar_one() == 0
        with wc_engine.begin() as connection:
            _cleanup_wc(connection)
            assert connection.execute(
                text("SELECT count(*) FROM wc_work_item WHERE tenant_id = :tenant_id"),
                {"tenant_id": TENANT},
            ).scalar_one() == 0
        wc_engine.dispose()
        ae_engine.dispose()
