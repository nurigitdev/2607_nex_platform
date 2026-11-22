from __future__ import annotations

import json
import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.skipif(
    not os.getenv("NEX_AE_TEST_DATABASE_URL"),
    reason="NEX_AE_TEST_DATABASE_URL is required for protected PostgreSQL smoke",
)

TENANT = "cp-m1-6b1a1-pg"
AGENT_ID = "11111111-1111-4111-8111-111111116b11"
EXECUTION_ID = "22222222-2222-4222-8222-222222226b11"
TRIGGER_ID = "33333333-3333-4333-8333-333333336b11"
WORK_INTENT_ID = "44444444-4444-4444-8444-444444446b11"
CONTEXT_ID = "55555555-5555-4555-8555-555555556b11"
WORKSPACE_ID = "66666666-6666-4666-8666-666666666b11"
CONVERSATION_ID = "77777777-7777-4777-8777-777777776b11"
INTERACTION_ID = "88888888-8888-4888-8888-888888886b11"
CHECKPOINT_ID = "99999999-9999-4999-8999-999999996b11"
WAIT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa6b11"
MISSING_BINDING_WAIT_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbb6b11"
EVENT_ID = "cp-m1-6b1a1-business-event"
MISSING_BINDING_EVENT_ID = "cp-m1-6b1a1-unbound-event"
NOW = "2026-11-17T03:00:00+00:00"
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64
HASH_D = "sha256:" + "d" * 64
HASH_E = "sha256:" + "e" * 64
HASH_F = "sha256:" + "f" * 64
COORDINATOR_ID = "MYBEE.M1.TRANSACTION_PREPARATION"
COORDINATOR_VERSION = "1.0.0"


def _checkpoint_projection() -> dict[str, object]:
    return {
        "schema_version": "ae.product_preparation_checkpoint.v1",
        "checkpoint_id": CHECKPOINT_ID,
        "checkpoint_version": 1,
        "agent_execution_id": EXECUTION_ID,
        "work_intent_id": WORK_INTENT_ID,
        "agent_context_id": CONTEXT_ID,
        "stage": "WAITING_BUSINESS_APPROVAL",
        "stage_kind": "WAITING",
        "checkpoint_hash": HASH_F,
    }


def _seed_lineage(connection) -> None:
    connection.execute(
        text(
            """
            INSERT INTO ae_agent_identity (
                tenant_id, agent_id, agent_type, profile_ref, status,
                project_id, created_at, version
            ) VALUES (
                :tenant_id, :agent_id, 'IA', :profile_ref, 'ACTIVE',
                NULL, :now, 1
            )
            """
        ),
        {
            "tenant_id": TENANT,
            "agent_id": AGENT_ID,
            "profile_ref": "agent-profile://nex-platform/ia/product-preparation/v1",
            "now": NOW,
        },
    )
    connection.execute(
        text(
            """
            INSERT INTO ae_agent_execution (
                tenant_id, agent_execution_id, agent_id, agent_type,
                principal_id, trigger_id, source_type, source_ref, state,
                phase, version, correlation_id, received_at, created_at,
                updated_at
            ) VALUES (
                :tenant_id, :execution_id, :agent_id, 'IA', :principal_id,
                :trigger_id, 'PROMPT', :source_ref, 'RUNNING', 'PLAN_BUILD',
                1, :correlation_id, :now, :now, :now
            )
            """
        ),
        {
            "tenant_id": TENANT,
            "execution_id": EXECUTION_ID,
            "agent_id": AGENT_ID,
            "principal_id": "employee-6b1a1",
            "trigger_id": TRIGGER_ID,
            "source_ref": "IA:INTERACTION:" + INTERACTION_ID,
            "correlation_id": "cp-m1-6b1a1-correlation",
            "now": NOW,
        },
    )
    intent = {
        "schema_version": "1.2",
        "work_intent_id": WORK_INTENT_ID,
        "execution_id": EXECUTION_ID,
        "intent_revision": 1,
        "intent_hash": HASH_A,
    }
    connection.execute(
        text(
            """
            INSERT INTO ae_work_intent (
                tenant_id, work_intent_id, intent_revision,
                agent_execution_id, source_ref, actor_ref,
                compatibility_execution_mode, work_class, intent_hash,
                intent_json, created_at
            ) VALUES (
                :tenant_id, :work_intent_id, 1, :execution_id, :source_ref,
                :actor_ref, 'GENERAL_ANSWER', 'BUSINESS_TRANSACTION',
                :intent_hash, CAST(:intent_json AS JSONB), :now
            )
            """
        ),
        {
            "tenant_id": TENANT,
            "work_intent_id": WORK_INTENT_ID,
            "execution_id": EXECUTION_ID,
            "source_ref": "WC:WORK_ITEM:cp-m1-6b1a1",
            "actor_ref": "OA:SUBJECT:employee-6b1a1",
            "intent_hash": HASH_A,
            "intent_json": json.dumps(intent),
            "now": NOW,
        },
    )
    context = {
        "schema_version": "1.1",
        "context_id": CONTEXT_ID,
        "context_generation": 1,
        "execution_id": EXECUTION_ID,
        "context_hash": HASH_B,
    }
    connection.execute(
        text(
            """
            INSERT INTO ae_agent_context (
                tenant_id, context_id, context_generation,
                agent_execution_id, work_intent_id, work_intent_revision,
                work_intent_hash, principal_id, agent_id, workspace_id,
                conversation_id, interaction_id, context_hash, context_json,
                built_at
            ) VALUES (
                :tenant_id, :context_id, 1, :execution_id, :work_intent_id,
                1, :work_intent_hash, :principal_id, :agent_id,
                :workspace_id, :conversation_id, :interaction_id,
                :context_hash, CAST(:context_json AS JSONB), :now
            )
            """
        ),
        {
            "tenant_id": TENANT,
            "context_id": CONTEXT_ID,
            "execution_id": EXECUTION_ID,
            "work_intent_id": WORK_INTENT_ID,
            "work_intent_hash": HASH_A,
            "principal_id": "employee-6b1a1",
            "agent_id": AGENT_ID,
            "workspace_id": WORKSPACE_ID,
            "conversation_id": CONVERSATION_ID,
            "interaction_id": INTERACTION_ID,
            "context_hash": HASH_B,
            "context_json": json.dumps(context),
            "now": NOW,
        },
    )


def _insert_checkpoint(connection) -> None:
    connection.execute(
        text(
            """
            INSERT INTO ae_product_prep_checkpoint (
                tenant_id, checkpoint_id, checkpoint_schema_version,
                checkpoint_version, agent_execution_id, requester_ref,
                work_intent_id, work_intent_revision, work_intent_hash,
                agent_context_id, context_generation, context_hash,
                business_context_hash, capability_id, capability_version,
                capability_release_ref, capability_registration_hash,
                coordinator_id, coordinator_version,
                coordinator_registration_hash,
                preparation_adapter_source_identity,
                materializer_source_identity, stage, stage_kind,
                authority_refs, idempotency_key, correlation_id,
                checkpoint_projection, checkpoint_hash, created_at
            ) VALUES (
                :tenant_id, :checkpoint_id, :schema_version, 1,
                :execution_id, :requester_ref, :work_intent_id, 1,
                :work_intent_hash, :context_id, 1, :context_hash,
                :business_context_hash, :capability_id, :capability_version,
                :capability_release_ref, :capability_registration_hash,
                :coordinator_id, :coordinator_version,
                :coordinator_registration_hash, :adapter_identity,
                :materializer_identity, 'WAITING_BUSINESS_APPROVAL',
                'WAITING', CAST(:authority_refs AS JSONB), :idempotency_key,
                :correlation_id, CAST(:checkpoint_projection AS JSONB),
                :checkpoint_hash, :now
            )
            """
        ),
        {
            "tenant_id": TENANT,
            "checkpoint_id": CHECKPOINT_ID,
            "schema_version": "ae.product_preparation_checkpoint.v1",
            "execution_id": EXECUTION_ID,
            "requester_ref": "employee-6b1a1",
            "work_intent_id": WORK_INTENT_ID,
            "work_intent_hash": HASH_A,
            "context_id": CONTEXT_ID,
            "context_hash": HASH_B,
            "business_context_hash": HASH_C,
            "capability_id": "FINANCE.VOUCHER.APPROVE_AND_POST",
            "capability_version": "1.0.0",
            "capability_release_ref": "release://mybee/d04/v1",
            "capability_registration_hash": HASH_D,
            "coordinator_id": COORDINATOR_ID,
            "coordinator_version": COORDINATOR_VERSION,
            "coordinator_registration_hash": HASH_E,
            "adapter_identity": "nex-ae:m1-preparation-adapter:v1",
            "materializer_identity": "nex-ae:m1-plan-materializer:v1",
            "authority_refs": "[]",
            "idempotency_key": "cp-m1-6b1a1-checkpoint-v1",
            "correlation_id": "cp-m1-6b1a1-correlation",
            "checkpoint_projection": json.dumps(_checkpoint_projection()),
            "checkpoint_hash": HASH_F,
            "now": NOW,
        },
    )


def _insert_wait(connection, wait_id: str) -> None:
    connection.execute(
        text(
            """
            INSERT INTO ae_wait_registration (
                wait_id, tenant_id, agent_execution_id, executable_step_id,
                wait_type, external_ref, result_contract_ref, state, version,
                created_at, updated_at, resume_target_kind, wait_contract_ref
            ) VALUES (
                :wait_id, :tenant_id, :execution_id, NULL,
                'PRODUCT_PREPARATION', :authority_ref, NULL, 'PENDING', 1,
                :now, :now, 'PRODUCT_COORDINATOR', :wait_contract_ref
            )
            """
        ),
        {
            "wait_id": wait_id,
            "tenant_id": TENANT,
            "execution_id": EXECUTION_ID,
            "authority_ref": "EOS:APPROVAL_CASE:case-6b1a1",
            "wait_contract_ref": "contract://nex/ae/product-preparation-wait/v1",
            "now": NOW,
        },
    )


def _insert_wait_binding(connection) -> None:
    connection.execute(
        text(
            """
            INSERT INTO ae_product_prep_wait_binding (
                tenant_id, wait_id, checkpoint_id, checkpoint_hash,
                coordinator_id, coordinator_version,
                coordinator_registration_hash, expected_event_type,
                authority_kind, authority_ref, agent_execution_id,
                work_intent_id, binding_hash, created_at
            ) VALUES (
                :tenant_id, :wait_id, :checkpoint_id, :checkpoint_hash,
                :coordinator_id, :coordinator_version, :coordinator_hash,
                'BUSINESS_APPROVAL_CHANGED', 'BUSINESS_FORMAL',
                :authority_ref, :execution_id, :work_intent_id,
                :binding_hash, :now
            )
            """
        ),
        {
            "tenant_id": TENANT,
            "wait_id": WAIT_ID,
            "checkpoint_id": CHECKPOINT_ID,
            "checkpoint_hash": HASH_F,
            "coordinator_id": COORDINATOR_ID,
            "coordinator_version": COORDINATOR_VERSION,
            "coordinator_hash": HASH_E,
            "authority_ref": "EOS:APPROVAL_CASE:case-6b1a1",
            "execution_id": EXECUTION_ID,
            "work_intent_id": WORK_INTENT_ID,
            "binding_hash": HASH_D,
            "now": NOW,
        },
    )


def _insert_event(connection, event_id: str) -> None:
    connection.execute(
        text(
            """
            INSERT INTO ae_external_event_inbox (
                tenant_id, event_id, event_type, event_semantic_hash,
                external_ref, result_id, result_contract_ref, event_payload,
                state, received_at, event_family
            ) VALUES (
                :tenant_id, :event_id, 'BUSINESS_APPROVAL_CHANGED',
                :event_hash, :authority_ref, NULL, NULL,
                CAST(:event_payload AS JSONB), 'RECEIVED', :now,
                'PRODUCT_PREPARATION'
            )
            """
        ),
        {
            "tenant_id": TENANT,
            "event_id": event_id,
            "event_hash": HASH_C,
            "authority_ref": "EOS:APPROVAL_CASE:case-6b1a1",
            "event_payload": json.dumps(
                {
                    "schema_version": "ae.product_preparation_event.v1",
                    "event_id": event_id,
                    "authority_ref": "EOS:APPROVAL_CASE:case-6b1a1",
                }
            ),
            "now": NOW,
        },
    )


def _insert_event_binding(connection) -> None:
    connection.execute(
        text(
            """
            INSERT INTO ae_product_prep_event_binding (
                tenant_id, event_id, wait_id, checkpoint_id,
                checkpoint_hash, coordinator_id, coordinator_version,
                coordinator_registration_hash, authority_kind,
                notification_ref, agent_execution_id, work_intent_id,
                binding_hash, created_at
            ) VALUES (
                :tenant_id, :event_id, :wait_id, :checkpoint_id,
                :checkpoint_hash, :coordinator_id, :coordinator_version,
                :coordinator_hash, 'BUSINESS_FORMAL', :notification_ref,
                :execution_id, :work_intent_id, :binding_hash, :now
            )
            """
        ),
        {
            "tenant_id": TENANT,
            "event_id": EVENT_ID,
            "wait_id": WAIT_ID,
            "checkpoint_id": CHECKPOINT_ID,
            "checkpoint_hash": HASH_F,
            "coordinator_id": COORDINATOR_ID,
            "coordinator_version": COORDINATOR_VERSION,
            "coordinator_hash": HASH_E,
            "notification_ref": "EOS:OUTBOX:event-6b1a1",
            "execution_id": EXECUTION_ID,
            "work_intent_id": WORK_INTENT_ID,
            "binding_hash": HASH_B,
            "now": NOW,
        },
    )


def _expect_savepoint_failure(connection, operation) -> None:
    nested = connection.begin_nested()
    try:
        with pytest.raises(DBAPIError):
            operation()
            connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    finally:
        nested.rollback()
        connection.execute(text("SET CONSTRAINTS ALL DEFERRED"))


def test_actual_postgres_generalized_envelopes_and_typed_bindings() -> None:
    engine = create_engine(os.environ["NEX_AE_TEST_DATABASE_URL"])
    connection = engine.connect()
    transaction = connection.begin()
    try:
        migration = connection.execute(
            text(
                "SELECT count(*) FROM schema_migrations "
                "WHERE version = '2517_ae_product_preparation_resume'"
            )
        ).scalar_one()
        assert migration == 1
        assert connection.execute(
            text(
                "SELECT count(*) FROM ae_wait_registration "
                "WHERE resume_target_kind IS NULL OR wait_contract_ref IS NULL"
            )
        ).scalar_one() == 0
        assert connection.execute(
            text(
                "SELECT count(*) FROM ae_external_event_inbox "
                "WHERE event_family IS NULL"
            )
        ).scalar_one() == 0

        _seed_lineage(connection)
        _insert_checkpoint(connection)
        _insert_wait(connection, WAIT_ID)
        _insert_wait_binding(connection)
        _insert_event(connection, EVENT_ID)
        _insert_event_binding(connection)
        connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        connection.execute(text("SET CONSTRAINTS ALL DEFERRED"))

        saved = connection.execute(
            text(
                """
                SELECT wait.resume_target_kind, wait.wait_type,
                       event.event_family, checkpoint.stage
                FROM ae_wait_registration AS wait
                JOIN ae_product_prep_wait_binding AS binding
                  ON binding.tenant_id = wait.tenant_id
                 AND binding.wait_id = wait.wait_id
                JOIN ae_product_prep_checkpoint AS checkpoint
                  ON checkpoint.tenant_id = binding.tenant_id
                 AND checkpoint.checkpoint_id = binding.checkpoint_id
                JOIN ae_product_prep_event_binding AS event_binding
                  ON event_binding.tenant_id = binding.tenant_id
                 AND event_binding.wait_id = binding.wait_id
                JOIN ae_external_event_inbox AS event
                  ON event.tenant_id = event_binding.tenant_id
                 AND event.event_id = event_binding.event_id
                WHERE wait.tenant_id = :tenant_id AND wait.wait_id = :wait_id
                """
            ),
            {"tenant_id": TENANT, "wait_id": WAIT_ID},
        ).mappings().one()
        assert dict(saved) == {
            "resume_target_kind": "PRODUCT_COORDINATOR",
            "wait_type": "PRODUCT_PREPARATION",
            "event_family": "PRODUCT_PREPARATION",
            "stage": "WAITING_BUSINESS_APPROVAL",
        }

        _expect_savepoint_failure(
            connection,
            lambda: _insert_wait(connection, MISSING_BINDING_WAIT_ID),
        )
        _expect_savepoint_failure(
            connection,
            lambda: _insert_event(connection, MISSING_BINDING_EVENT_ID),
        )
        _expect_savepoint_failure(
            connection,
            lambda: connection.execute(
                text(
                    "UPDATE ae_product_prep_checkpoint SET stage = 'READY_FOR_D04' "
                    "WHERE tenant_id = :tenant_id AND checkpoint_id = :checkpoint_id"
                ),
                {"tenant_id": TENANT, "checkpoint_id": CHECKPOINT_ID},
            ),
        )
    finally:
        transaction.rollback()
        connection.close()
        engine.dispose()
