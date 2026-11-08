from __future__ import annotations

import asyncio
import copy
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from nex_ae_api.delegated_work import SqlAlchemyWaitRegistrationRepository
from nex_ae_api.nsl_approval_publication import P8NSLApprovalPort
from nex_ae_api.nsl_approval_requests import SqlAlchemyProtectedApprovalRequestStore
from nex_wc.approvals import ApprovalWorkItemService, SqlAlchemyApprovalWorkItemRepository
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

AE_DATABASE_URL = os.getenv("NEX_AE_TEST_DATABASE_URL")
WC_DATABASE_URL = os.getenv("NEX_WC_TEST_DATABASE_URL")
SMOKE_ENABLED = os.getenv("NEX_P8_S47_POSTGRES_SMOKE") == "1"

pytestmark = pytest.mark.skipif(
    not SMOKE_ENABLED or not AE_DATABASE_URL or not WC_DATABASE_URL,
    reason="Protected P8-S47 AE/WC PostgreSQL smoke is disabled",
)


class ApprovalRequestStub:
    def __init__(self, data: dict[str, object]) -> None:
        self.data = data

    def to_data(self) -> dict[str, object]:
        return copy.deepcopy(self.data)


class BindingSource:
    def __init__(self, value: dict[str, object]) -> None:
        self.value = value

    def resolve(self, approval_request):
        return dict(self.value)


class ServiceClient:
    def __init__(self, service: ApprovalWorkItemService) -> None:
        self.service = service

    def create_or_get(self, work_item):
        return self.service.create_or_get(work_item)


def test_actual_postgres_publishes_request_wait_and_wc_item_idempotently() -> None:
    assert AE_DATABASE_URL is not None
    assert WC_DATABASE_URL is not None
    suffix = uuid4().hex
    tenant_id = f"tenant-p8-s47-{suffix}"
    agent_id = str(uuid4())
    execution_id = str(uuid4())
    step_id = str(uuid4())
    request_id = f"approval-request-{suffix}"
    nsl_execution_id = f"nsl-execution-{suffix}"
    business_operation_id = f"business-operation-{suffix}"
    ae_engine = create_engine(AE_DATABASE_URL, poolclass=NullPool)
    wc_engine = create_engine(WC_DATABASE_URL, poolclass=NullPool)
    ae_factory = sessionmaker(bind=ae_engine, expire_on_commit=False)
    wc_factory = sessionmaker(bind=wc_engine, expire_on_commit=False)
    request = ApprovalRequestStub(
        {
            "tenant_id": tenant_id,
            "execution_id": nsl_execution_id,
            "business_operation_id": business_operation_id,
            "approval_id": "APPROVE_VOUCHER_DRAFT",
            "approval_request_id": request_id,
            "skill_id": "FINANCE.CREATE_VOUCHER_DRAFT",
            "skill_version": "0.2.0",
            "skill_semantic_hash": "sha256:" + "a" * 64,
            "write_node_id": "write-voucher-draft",
            "tool_id": "finance.create_voucher_draft",
            "payload_hash": "sha256:" + "b" * 64,
            "write_intent_hash": f"write-intent-{suffix}",
            "risk_level": "R3",
            "message": "Protected S47 PostgreSQL smoke request",
            "expires_at": "2026-10-23T12:00:00+00:00",
            "display_safe_summary": {"line_count": 2},
            "protected_payload_ref": f"snapshot://private/{suffix}",
            "data_classification": "CONFIDENTIAL",
        }
    )
    try:
        with ae_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO ae_agent_identity ("
                    "tenant_id, agent_id, agent_type, profile_ref, status"
                    ") VALUES (:tenant_id, :agent_id, 'IA', "
                    "'profile://p8-s47', 'ACTIVE')"
                ),
                {"tenant_id": tenant_id, "agent_id": agent_id},
            )
            connection.execute(
                text(
                    "INSERT INTO ae_agent_execution ("
                    "tenant_id, agent_execution_id, agent_id, agent_type, "
                    "principal_id, trigger_id, source_type, source_ref, state, "
                    "phase, correlation_id, received_at"
                    ") VALUES (:tenant_id, :execution_id, :agent_id, 'IA', "
                    ":principal_id, :trigger_id, 'PROMPT', 'prompt://p8-s47', "
                    "'RUNNING', 'STEP_EXECUTION', :correlation_id, now())"
                ),
                {
                    "tenant_id": tenant_id,
                    "execution_id": execution_id,
                    "agent_id": agent_id,
                    "principal_id": f"approver-{suffix}",
                    "trigger_id": str(uuid4()),
                    "correlation_id": f"corr-{suffix}",
                },
            )
            connection.execute(
                text(
                    "INSERT INTO ae_executable_step ("
                    "tenant_id, executable_step_id, agent_execution_id, step_kind, "
                    "state, legacy_interaction_id, correlation_id"
                    ") VALUES (:tenant_id, :step_id, :execution_id, "
                    "'P4_CHAT_RAG_COMPATIBILITY', 'WAITING', "
                    ":interaction_id, :correlation_id)"
                ),
                {
                    "tenant_id": tenant_id,
                    "step_id": step_id,
                    "execution_id": execution_id,
                    "interaction_id": str(uuid4()),
                    "correlation_id": f"corr-{suffix}",
                },
            )

        port = P8NSLApprovalPort(
            binding_source=BindingSource(
                {
                    "tenant_id": tenant_id,
                    "agent_execution_id": execution_id,
                    "executable_step_id": step_id,
                    "nsl_execution_id": nsl_execution_id,
                    "business_operation_id": business_operation_id,
                    "checkpoint_version": 5,
                    "target_approver_ref": f"approver-{suffix}",
                    "target_role_ref": None,
                    "target_org_scope_ref": None,
                    "target_project_scope_ref": None,
                }
            ),
            request_store=SqlAlchemyProtectedApprovalRequestStore(
                ae_factory,
                clock=lambda: datetime(2026, 10, 22, 12, tzinfo=UTC),
            ),
            wait_repository=SqlAlchemyWaitRegistrationRepository(ae_factory),
            wc_client=ServiceClient(
                ApprovalWorkItemService(SqlAlchemyApprovalWorkItemRepository(wc_factory))
            ),
            clock=lambda: datetime(2026, 10, 22, 12, tzinfo=UTC),
        )

        asyncio.run(port.publish(request))
        asyncio.run(port.publish(request))

        with ae_engine.connect() as connection:
            request_count = connection.execute(
                text(
                    "SELECT count(*) FROM ae_nsl_approval_request "
                    "WHERE tenant_id = :tenant_id"
                ),
                {"tenant_id": tenant_id},
            ).scalar_one()
            wait = (
                connection.execute(
                    text(
                        "SELECT approval_request_id, nsl_execution_id, "
                        "business_operation_id, checkpoint_version "
                        "FROM ae_wait_registration WHERE tenant_id = :tenant_id "
                        "AND wait_type = 'NSL_APPROVAL'"
                    ),
                    {"tenant_id": tenant_id},
                )
                .mappings()
                .one()
            )
        with wc_engine.connect() as connection:
            item = (
                connection.execute(
                    text(
                        "SELECT approval_request_id, nsl_execution_id, "
                        "business_operation_id, protected_request_ref, state "
                        "FROM wc_approval_work_item WHERE tenant_id = :tenant_id"
                    ),
                    {"tenant_id": tenant_id},
                )
                .mappings()
                .one()
            )
        assert request_count == 1
        assert dict(wait) == {
            "approval_request_id": request_id,
            "nsl_execution_id": nsl_execution_id,
            "business_operation_id": business_operation_id,
            "checkpoint_version": 5,
        }
        assert item["approval_request_id"] == request_id
        assert item["nsl_execution_id"] == nsl_execution_id
        assert item["business_operation_id"] == business_operation_id
        assert item["protected_request_ref"].startswith("ae://")
        assert item["state"] == "PENDING"
    finally:
        with wc_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM wc_approval_work_item WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            )
        with ae_engine.begin() as connection:
            for statement in (
                "DELETE FROM ae_wait_registration WHERE tenant_id = :tenant_id",
                "DELETE FROM ae_nsl_approval_request WHERE tenant_id = :tenant_id",
                "DELETE FROM ae_executable_step WHERE tenant_id = :tenant_id",
                "DELETE FROM ae_agent_execution WHERE tenant_id = :tenant_id",
                "DELETE FROM ae_agent_identity WHERE tenant_id = :tenant_id",
            ):
                connection.execute(text(statement), {"tenant_id": tenant_id})
        ae_engine.dispose()
        wc_engine.dispose()
