from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from nex_ae_api.nsl_approval_events import SqlAlchemyNslApprovalEventService
from nex_ae_api.runtime_jobs import SqlAlchemyRuntimeJobQueue
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

DATABASE_URL = os.getenv("NEX_AE_TEST_DATABASE_URL")
ENABLED = os.getenv("NEX_AE_P8_S50_POSTGRES_SMOKE") == "1"


@pytest.mark.skipif(
    not ENABLED or not DATABASE_URL,
    reason="Protected P8-S50 PostgreSQL smoke is disabled",
)
def test_actual_postgres_persists_typed_approval_event_without_fake_result() -> None:
    assert DATABASE_URL is not None
    suffix = uuid4().hex
    tenant_id = f"tenant-p8-s50-{suffix}"
    agent_id = str(uuid4())
    execution_id = str(uuid4())
    step_id = str(uuid4())
    wait_id = str(uuid4())
    event_id = str(uuid4())
    work_item_id = str(uuid4())
    request_id = f"approval-request-{suffix}"
    nsl_execution_id = f"nsl-execution-{suffix}"
    business_operation_id = f"business-operation-{suffix}"
    correlation_id = f"correlation-{suffix}"
    integrity = "sha256:" + "a" * 64
    engine = create_engine(DATABASE_URL, poolclass=NullPool)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with engine.begin() as connection:
            assert connection.execute(
                text(
                    "SELECT count(*) FROM schema_migrations "
                    "WHERE version = '2505_ae_nsl_approval_event_inbox'"
                )
            ).scalar_one() == 1
            connection.execute(
                text(
                    "INSERT INTO ae_agent_identity (tenant_id, agent_id, agent_type, "
                    "profile_ref, status) VALUES (:tenant, :agent, 'IA', "
                    "'profile://p8-s50', 'ACTIVE')"
                ),
                {"tenant": tenant_id, "agent": agent_id},
            )
            connection.execute(
                text(
                    "INSERT INTO ae_agent_execution (tenant_id, agent_execution_id, "
                    "agent_id, agent_type, principal_id, trigger_id, source_type, "
                    "source_ref, state, phase, correlation_id, received_at) VALUES "
                    "(:tenant, :execution, :agent, 'IA', 'employee-p8-s50', :trigger, "
                    "'PROMPT', 'prompt://p8-s50', 'WAITING_APPROVAL', "
                    "'STEP_EXECUTION', :correlation, now())"
                ),
                {
                    "tenant": tenant_id,
                    "execution": execution_id,
                    "agent": agent_id,
                    "trigger": str(uuid4()),
                    "correlation": correlation_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO ae_executable_step (tenant_id, executable_step_id, "
                    "agent_execution_id, step_kind, state, legacy_interaction_id, "
                    "correlation_id) VALUES (:tenant, :step, :execution, "
                    "'P4_CHAT_RAG_COMPATIBILITY', 'WAITING', :interaction, "
                    ":correlation)"
                ),
                {
                    "tenant": tenant_id,
                    "step": step_id,
                    "execution": execution_id,
                    "interaction": str(uuid4()),
                    "correlation": correlation_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO ae_nsl_approval_request (tenant_id, "
                    "approval_request_id, nsl_execution_id, business_operation_id, "
                    "protected_request_ref, approval_request_hash, request_size_bytes, "
                    "content_type, data_classification, created_at, "
                    "approval_request_bytes) VALUES (:tenant, :request, :nsl, "
                    ":business, :protected, :request_hash, 2, 'application/json', "
                    "'INTERNAL', now(), :body)"
                ),
                {
                    "tenant": tenant_id,
                    "request": request_id,
                    "nsl": nsl_execution_id,
                    "business": business_operation_id,
                    "protected": f"ae://nsl-approval-requests/aa/{'b' * 64}.json",
                    "request_hash": "sha256:" + "c" * 64,
                    "body": b"{}",
                },
            )
            connection.execute(
                text(
                    "INSERT INTO ae_wait_registration (wait_id, tenant_id, "
                    "agent_execution_id, executable_step_id, wait_type, external_ref, "
                    "result_contract_ref, state, version, created_at, updated_at, "
                    "nsl_execution_id, business_operation_id, approval_request_id, "
                    "checkpoint_version) VALUES (:wait, :tenant, :execution, :step, "
                    "'NSL_APPROVAL', :request, 'urn:nex:approval-resume:p8:v1', "
                    "'PENDING', 1, now(), now(), :nsl, :business, :request, 7)"
                ),
                {
                    "wait": wait_id,
                    "tenant": tenant_id,
                    "execution": execution_id,
                    "step": step_id,
                    "request": request_id,
                    "nsl": nsl_execution_id,
                    "business": business_operation_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO ae_approval_evidence (tenant_id, agent_execution_id, "
                    "executable_step_id, nsl_execution_id, business_operation_id, "
                    "approval_id, approval_request_id, skill_semantic_hash, decision, "
                    "approver_id, decided_at, expires_at, payload_hash, "
                    "write_intent_hash, approval_work_item_ref, oa_decision_ref, "
                    "protected_request_ref, evidence_integrity, created_at) VALUES "
                    "(:tenant, :execution, :step, :nsl, :business, 'APPROVE_WRITE', "
                    ":request, :skill_hash, 'APPROVE', 'employee-p8-s50', now(), "
                    "now() + interval '1 day', :payload_hash, :intent_hash, :work_item, "
                    "'oa-decision-p8-s50', :protected, :integrity, now())"
                ),
                {
                    "tenant": tenant_id,
                    "execution": execution_id,
                    "step": step_id,
                    "nsl": nsl_execution_id,
                    "business": business_operation_id,
                    "request": request_id,
                    "skill_hash": "sha256:" + "d" * 64,
                    "payload_hash": "sha256:" + "e" * 64,
                    "intent_hash": f"intent-{suffix}",
                    "work_item": work_item_id,
                    "protected": f"ae://nsl-approval-requests/aa/{'b' * 64}.json",
                    "integrity": integrity,
                },
            )

        service = SqlAlchemyNslApprovalEventService(
            sessions,
            runtime_jobs=SqlAlchemyRuntimeJobQueue(sessions),
            clock=lambda: datetime(2026, 10, 22, 14, tzinfo=UTC),
        )
        result = service.ingest(
            {
                "schema_version": "ae_nsl_approval_decided_event.v1",
                "event_id": event_id,
                "event_name": "NSL_APPROVAL_DECIDED",
                "tenant_id": tenant_id,
                "approval_work_item_ref": work_item_id,
                "approval_request_id": request_id,
                "nsl_execution_id": nsl_execution_id,
                "business_operation_id": business_operation_id,
                "decision": "APPROVE",
                "approval_evidence_ref": f"ae-approval-evidence:{request_id}",
                "evidence_integrity": integrity,
                "correlation_id": correlation_id,
                "causation_id": f"decision-{suffix}",
                "occurred_at": "2026-10-22T14:00:00Z",
            }
        )
        assert result["inbox_state"] == "RECEIVED"
        assert result["wait_state"] == "PENDING"
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT event_type, result_id, state FROM ae_external_event_inbox "
                    "WHERE tenant_id = :tenant"
                ),
                {"tenant": tenant_id},
            ).one()
            job_count = connection.execute(
                text(
                    "SELECT count(*) FROM ae_runtime_job WHERE tenant_id = :tenant "
                    "AND job_type = 'RESUME_EXECUTION'"
                ),
                {"tenant": tenant_id},
            ).scalar_one()
        assert tuple(row) == ("NSL_APPROVAL_DECIDED", None, "RECEIVED")
        assert job_count == 0
    finally:
        with engine.begin() as connection:
            for statement in (
                "DELETE FROM ae_runtime_job WHERE tenant_id = :tenant",
                "DELETE FROM ae_external_event_inbox WHERE tenant_id = :tenant",
                "DELETE FROM ae_approval_evidence WHERE tenant_id = :tenant",
                "DELETE FROM ae_wait_registration WHERE tenant_id = :tenant",
                "DELETE FROM ae_nsl_approval_request WHERE tenant_id = :tenant",
                "DELETE FROM ae_executable_step WHERE tenant_id = :tenant",
                "DELETE FROM ae_agent_execution WHERE tenant_id = :tenant",
                "DELETE FROM ae_agent_identity WHERE tenant_id = :tenant",
            ):
                connection.execute(text(statement), {"tenant": tenant_id})
        engine.dispose()
