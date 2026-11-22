from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from nex_ae_api.product_preparation_persistence import (
    ProductPreparationPersistenceError,
    SqlAlchemyGeneralizedWaitEventRepository,
    SqlAlchemyProductPreparationCheckpointRepository,
    product_preparation_wait_envelope,
    seal_product_preparation_checkpoint,
    seal_product_preparation_event,
    seal_product_preparation_event_binding,
    seal_product_preparation_wait_binding,
)
from nex_ae_api.runtime_jobs import SqlAlchemyRuntimeJobQueue
from nex_ae_api.runtime_resume import (
    SqlAlchemyProductPreparationResumeService,
    SqlAlchemyResumeRouteSource,
)
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

DATABASE_URL = os.getenv("NEX_AE_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="NEX_AE_TEST_DATABASE_URL is required for protected PostgreSQL smoke",
)

TENANT = "cp-m1-6b1a2-pg"
AGENT_ID = "11111111-1111-4111-8111-111111116b12"
EXECUTION_ID = "22222222-2222-4222-8222-222222226b12"
TRIGGER_ID = "33333333-3333-4333-8333-333333336b12"
WORK_INTENT_ID = "44444444-4444-4444-8444-444444446b12"
CONTEXT_ID = "55555555-5555-4555-8555-555555556b12"
WORKSPACE_ID = "66666666-6666-4666-8666-666666666b12"
CONVERSATION_ID = "77777777-7777-4777-8777-777777776b12"
INTERACTION_ID = "88888888-8888-4888-8888-888888886b12"
CHECKPOINT_ID = "99999999-9999-4999-8999-999999996b12"
CHECKPOINT_2_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa6b12"
WAIT_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbb6b12"
EVENT_ID = "cp-m1-6b1a2-business-event"
NOW = "2026-11-17T07:00:00Z"
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64
HASH_D = "sha256:" + "d" * 64
COORDINATOR_ID = "MYBEE.M1.TRANSACTION_PREPARATION"
COORDINATOR_VERSION = "1.0.0"


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
            "principal_id": "employee-6b1a2",
            "trigger_id": TRIGGER_ID,
            "source_ref": "IA:INTERACTION:" + INTERACTION_ID,
            "correlation_id": "cp-m1-6b1a2-correlation",
            "now": NOW,
        },
    )
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
            "source_ref": "WC:WORK_ITEM:cp-m1-6b1a2",
            "actor_ref": "OA:SUBJECT:employee-6b1a2",
            "intent_hash": HASH_A,
            "intent_json": '{"schema_version":"1.2"}',
            "now": NOW,
        },
    )
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
            "principal_id": "employee-6b1a2",
            "agent_id": AGENT_ID,
            "workspace_id": WORKSPACE_ID,
            "conversation_id": CONVERSATION_ID,
            "interaction_id": INTERACTION_ID,
            "context_hash": HASH_B,
            "context_json": '{"schema_version":"1.1"}',
            "now": NOW,
        },
    )


def _checkpoint_base(**changes):
    value = {
        "tenant_id": TENANT,
        "checkpoint_id": CHECKPOINT_ID,
        "checkpoint_schema_version": "ae.product_preparation_checkpoint.v1",
        "checkpoint_version": 1,
        "previous_checkpoint_id": None,
        "previous_checkpoint_hash": None,
        "agent_execution_id": EXECUTION_ID,
        "requester_ref": "employee-6b1a2",
        "work_intent_id": WORK_INTENT_ID,
        "work_intent_revision": 1,
        "work_intent_hash": HASH_A,
        "agent_context_id": CONTEXT_ID,
        "context_generation": 1,
        "context_hash": HASH_B,
        "business_context_hash": HASH_C,
        "capability_id": "FINANCE.VOUCHER.APPROVE_AND_POST",
        "capability_version": "1.0.0",
        "capability_release_ref": "release://mybee/d04/v1",
        "capability_registration_hash": HASH_D,
        "coordinator_id": COORDINATOR_ID,
        "coordinator_version": COORDINATOR_VERSION,
        "coordinator_registration_hash": HASH_A,
        "preparation_adapter_source_identity": "nex-ae:m1-preparation-adapter:v1",
        "materializer_source_identity": "nex-ae:m1-plan-materializer:v1",
        "stage": "WAITING_BUSINESS_APPROVAL",
        "stage_kind": "WAITING",
        "authority_refs": [
            {
                "authority_kind": "BUSINESS_FORMAL",
                "authority_ref": "wc://approval/case-6b1a2",
            }
        ],
        "idempotency_key": "product-preparation:6b1a2:v1",
        "correlation_id": "correlation-6b1a2",
        "causation_id": None,
        "created_at": NOW,
    }
    value.update(changes)
    return value


def _wait(checkpoint):
    envelope = product_preparation_wait_envelope(
        {
            "tenant_id": TENANT,
            "wait_id": WAIT_ID,
            "agent_execution_id": EXECUTION_ID,
            "external_ref": "wc://approval/case-6b1a2",
            "wait_contract_ref": "contract://nex/ae/product-preparation-wait/v1",
            "created_at": NOW,
        }
    )
    binding = seal_product_preparation_wait_binding(
        {
            "tenant_id": TENANT,
            "wait_id": WAIT_ID,
            "checkpoint_id": checkpoint["checkpoint_id"],
            "checkpoint_hash": checkpoint["checkpoint_hash"],
            "coordinator_id": COORDINATOR_ID,
            "coordinator_version": COORDINATOR_VERSION,
            "coordinator_registration_hash": HASH_A,
            "expected_event_type": "BUSINESS_APPROVAL_CHANGED",
            "authority_kind": "BUSINESS_FORMAL",
            "authority_ref": "wc://approval/case-6b1a2",
            "agent_execution_id": EXECUTION_ID,
            "work_intent_id": WORK_INTENT_ID,
            "created_at": NOW,
        }
    )
    return envelope, binding


def _event(checkpoint):
    envelope = seal_product_preparation_event(
        {
            "tenant_id": TENANT,
            "event_id": EVENT_ID,
            "event_type": "BUSINESS_APPROVAL_CHANGED",
            "external_ref": "wc://approval/case-6b1a2",
            "event_payload": {
                "schema_version": "ae.product_preparation_notification.v1",
                "notification_ref": "wc-event://decision/6b1a2",
            },
            "received_at": NOW,
        }
    )
    binding = seal_product_preparation_event_binding(
        {
            "tenant_id": TENANT,
            "event_id": EVENT_ID,
            "wait_id": WAIT_ID,
            "checkpoint_id": checkpoint["checkpoint_id"],
            "checkpoint_hash": checkpoint["checkpoint_hash"],
            "coordinator_id": COORDINATOR_ID,
            "coordinator_version": COORDINATOR_VERSION,
            "coordinator_registration_hash": HASH_A,
            "authority_kind": "BUSINESS_FORMAL",
            "notification_ref": "wc-event://decision/6b1a2",
            "agent_execution_id": EXECUTION_ID,
            "work_intent_id": WORK_INTENT_ID,
            "created_at": NOW,
        }
    )
    return envelope, binding


def test_actual_postgres_repository_api_is_atomic_replayable_and_zero_residue() -> None:
    assert DATABASE_URL is not None
    engine = create_engine(DATABASE_URL, poolclass=NullPool)
    connection = engine.connect()
    transaction = connection.begin()
    sessions = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    checkpoints = SqlAlchemyProductPreparationCheckpointRepository(sessions)
    envelopes = SqlAlchemyGeneralizedWaitEventRepository(sessions)
    try:
        migration_count = connection.execute(
            text(
                "SELECT count(*) FROM schema_migrations "
                "WHERE version = '2517_ae_product_preparation_resume'"
            )
        ).scalar_one()
        assert migration_count == 1
        _seed_lineage(connection)

        first = checkpoints.append(
            seal_product_preparation_checkpoint(_checkpoint_base())
        )
        wait, wait_binding = _wait(first)
        saved_wait = envelopes.register_wait(wait, product_binding=wait_binding)
        event, event_binding = _event(first)
        saved_event = envelopes.accept_event(event, product_binding=event_binding)

        assert saved_wait["wait"]["state"] == "PENDING"
        assert saved_event["event"]["state"] == "RECEIVED"
        assert (
            envelopes.load_product_wait_context(tenant_id=TENANT, wait_id=WAIT_ID)[
                "checkpoint"
            ]["checkpoint_hash"]
            == first["checkpoint_hash"]
        )
        assert (
            envelopes.load_product_event_context(tenant_id=TENANT, event_id=EVENT_ID)[
                "wait_binding"
            ]["wait_id"]
            == WAIT_ID
        )
        assert envelopes.register_wait(wait, product_binding=wait_binding) == saved_wait
        assert (
            envelopes.accept_event(event, product_binding=event_binding) == saved_event
        )

        second = checkpoints.append(
            seal_product_preparation_checkpoint(
                _checkpoint_base(
                    checkpoint_id=CHECKPOINT_2_ID,
                    checkpoint_version=2,
                    previous_checkpoint_id=first["checkpoint_id"],
                    previous_checkpoint_hash=first["checkpoint_hash"],
                    stage="WAITING_ACCOUNTING_APPROVAL",
                    idempotency_key="product-preparation:6b1a2:v2",
                    causation_id=EVENT_ID,
                    created_at="2026-11-17T07:05:00Z",
                )
            )
        )
        assert (
            checkpoints.latest(
                tenant_id=TENANT,
                agent_execution_id=EXECUTION_ID,
                coordinator_id=COORDINATOR_ID,
                coordinator_version=COORDINATOR_VERSION,
            )["checkpoint_id"]
            == second["checkpoint_id"]
        )

        changed_event = seal_product_preparation_event(
            {
                "tenant_id": TENANT,
                "event_id": EVENT_ID,
                "event_type": "BUSINESS_APPROVAL_CHANGED",
                "external_ref": "wc://approval/case-6b1a2",
                "event_payload": {
                    "schema_version": "ae.product_preparation_notification.v1",
                    "notification_ref": "wc-event://decision/changed",
                },
                "received_at": "2026-11-17T07:10:00Z",
            }
        )
        changed_binding = seal_product_preparation_event_binding(
            {
                "tenant_id": TENANT,
                "event_id": EVENT_ID,
                "wait_id": WAIT_ID,
                "checkpoint_id": first["checkpoint_id"],
                "checkpoint_hash": first["checkpoint_hash"],
                "coordinator_id": COORDINATOR_ID,
                "coordinator_version": COORDINATOR_VERSION,
                "coordinator_registration_hash": HASH_A,
                "authority_kind": "BUSINESS_FORMAL",
                "notification_ref": "wc-event://decision/changed",
                "agent_execution_id": EXECUTION_ID,
                "work_intent_id": WORK_INTENT_ID,
                "created_at": "2026-11-17T07:10:00Z",
            }
        )
        with pytest.raises(ProductPreparationPersistenceError) as conflict:
            envelopes.accept_event(changed_event, product_binding=changed_binding)
        assert conflict.value.error_code.endswith("_conflict")

        counts = (
            connection.execute(
                text(
                    """
                SELECT
                    (SELECT count(*) FROM ae_product_prep_checkpoint
                     WHERE tenant_id = :tenant_id) AS checkpoints,
                    (SELECT count(*) FROM ae_product_prep_wait_binding
                     WHERE tenant_id = :tenant_id) AS wait_bindings,
                    (SELECT count(*) FROM ae_product_prep_event_binding
                     WHERE tenant_id = :tenant_id) AS event_bindings
                """
                ),
                {"tenant_id": TENANT},
            )
            .mappings()
            .one()
        )
        assert dict(counts) == {
            "checkpoints": 2,
            "wait_bindings": 1,
            "event_bindings": 1,
        }
    finally:
        transaction.rollback()
        connection.close()

    with engine.connect() as verification:
        residue = verification.execute(
            text(
                """
                SELECT
                    (SELECT count(*) FROM ae_product_prep_checkpoint
                     WHERE tenant_id = :tenant_id)
                  + (SELECT count(*) FROM ae_wait_registration
                     WHERE tenant_id = :tenant_id)
                  + (SELECT count(*) FROM ae_external_event_inbox
                     WHERE tenant_id = :tenant_id)
                """
            ),
            {"tenant_id": TENANT},
        ).scalar_one()
        assert residue == 0
    engine.dispose()


def test_actual_postgres_product_event_match_and_route_are_restart_safe() -> None:
    assert DATABASE_URL is not None
    engine = create_engine(DATABASE_URL, poolclass=NullPool)
    connection = engine.connect()
    transaction = connection.begin()
    sessions = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    checkpoints = SqlAlchemyProductPreparationCheckpointRepository(sessions)
    envelopes = SqlAlchemyGeneralizedWaitEventRepository(sessions)
    resume = SqlAlchemyProductPreparationResumeService(
        sessions,
        runtime_jobs=SqlAlchemyRuntimeJobQueue(sessions),
        clock=lambda: datetime(2026, 11, 17, 8, tzinfo=UTC),
    )
    try:
        _seed_lineage(connection)
        checkpoint = checkpoints.append(
            seal_product_preparation_checkpoint(_checkpoint_base())
        )
        wait, wait_binding = _wait(checkpoint)
        envelopes.register_wait(wait, product_binding=wait_binding)
        event, event_binding = _event(checkpoint)
        envelopes.accept_event(event, product_binding=event_binding)

        first = resume.reconcile(tenant_id=TENANT, event_id=EVENT_ID)
        restarted = SqlAlchemyProductPreparationResumeService(
            sessions,
            runtime_jobs=SqlAlchemyRuntimeJobQueue(sessions),
            clock=lambda: datetime(2026, 11, 17, 9, tzinfo=UTC),
        ).reconcile(tenant_id=TENANT, event_id=EVENT_ID)
        route = SqlAlchemyResumeRouteSource(sessions).resolve(
            tenant_id=TENANT,
            runtime_job_id=first["resume_runtime_job_id"],
        )

        assert restarted == first
        assert route.resume_target_kind == "PRODUCT_COORDINATOR"
        assert route.executable_step_id is None
        assert (
            connection.execute(
                text(
                    "SELECT count(*) FROM ae_runtime_job "
                    "WHERE tenant_id = :tenant_id AND wait_id = :wait_id"
                ),
                {"tenant_id": TENANT, "wait_id": WAIT_ID},
            ).scalar_one()
            == 1
        )
    finally:
        transaction.rollback()
        connection.close()

    with engine.connect() as verification:
        residue = verification.execute(
            text(
                "SELECT "
                "(SELECT count(*) FROM ae_runtime_job WHERE tenant_id = :tenant_id) + "
                "(SELECT count(*) FROM ae_wait_registration WHERE tenant_id = :tenant_id) + "
                "(SELECT count(*) FROM ae_external_event_inbox WHERE tenant_id = :tenant_id) + "
                "(SELECT count(*) FROM ae_product_prep_checkpoint WHERE tenant_id = :tenant_id)"
            ),
            {"tenant_id": TENANT},
        ).scalar_one()
        assert residue == 0
    engine.dispose()
