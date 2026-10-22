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
from nex_ae_api.platform_approval_evidence import (
    SqlAlchemyPlatformApprovalEvidenceRepository,
    build_platform_approval_evidence,
)
from nex_wc.approvals import (
    ApprovalDecisionAuthorizer,
    ApprovalDecisionService,
    ApprovalWorkItemService,
    SqlAlchemyApprovalWorkItemRepository,
)
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

AE_DATABASE_URL = os.getenv("NEX_AE_TEST_DATABASE_URL")
WC_DATABASE_URL = os.getenv("NEX_WC_TEST_DATABASE_URL")
SMOKE_ENABLED = os.getenv("NEX_P8_S48_POSTGRES_SMOKE") == "1"

pytestmark = pytest.mark.skipif(
    not SMOKE_ENABLED or not AE_DATABASE_URL or not WC_DATABASE_URL,
    reason="Protected P8-S48 AE/WC PostgreSQL smoke is disabled",
)


class ApprovalRequestStub:
    def __init__(self, data: dict[str, object]) -> None:
        self.data = data

    def to_data(self) -> dict[str, object]:
        return copy.deepcopy(self.data)


class BindingSource:
    def __init__(self, value: dict[str, object]) -> None:
        self.value = value

    def resolve(self, _approval_request):
        return dict(self.value)


class ServiceClient:
    def __init__(self, service: ApprovalWorkItemService) -> None:
        self.service = service

    def create_or_get(self, work_item):
        return self.service.create_or_get(work_item)


class AuthorizationSource:
    def __init__(self, *, tenant_id: str, subject_id: str) -> None:
        self.tenant_id = tenant_id
        self.subject_id = subject_id

    def effective_authorization(self, **_kwargs):
        return {
            "active": True,
            "tenant_id": self.tenant_id,
            "subject_id": self.subject_id,
            "scopes": ["approval:decide"],
            "roles": [],
            "revision_hash": "f" * 64,
            "decision_ref": "oa-decision-p8-s48-postgres",
        }


def test_actual_postgres_persists_immutable_platform_approval_evidence() -> None:
    assert AE_DATABASE_URL is not None
    assert WC_DATABASE_URL is not None
    suffix = uuid4().hex
    tenant_id = f"tenant-p8-s48-{suffix}"
    agent_id = str(uuid4())
    agent_execution_id = str(uuid4())
    executable_step_id = str(uuid4())
    approval_request_id = f"approval-request-{suffix}"
    nsl_execution_id = f"nsl-execution-{suffix}"
    business_operation_id = f"business-operation-{suffix}"
    approver_id = f"employee-{suffix[:12]}"
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
            "approval_request_id": approval_request_id,
            "skill_id": "FINANCE.CREATE_VOUCHER_DRAFT",
            "skill_version": "0.2.0",
            "skill_semantic_hash": "sha256:" + "a" * 64,
            "write_node_id": "write-voucher-draft",
            "tool_id": "finance.create_voucher_draft",
            "payload_hash": "sha256:" + "b" * 64,
            "write_intent_hash": f"write-intent-{suffix}",
            "risk_level": "R3",
            "message": "Protected S48 PostgreSQL smoke request",
            "expires_at": "2026-10-23T12:00:00Z",
            "display_safe_summary": {"line_count": 2},
            "protected_payload_ref": f"snapshot://private/{suffix}",
            "data_classification": "CONFIDENTIAL",
        }
    )
    try:
        with ae_engine.begin() as connection:
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM schema_migrations "
                        "WHERE version = '2504_ae_approval_evidence'"
                    )
                ).scalar_one()
                == 1
            )
            connection.execute(
                text(
                    "INSERT INTO ae_agent_identity ("
                    "tenant_id, agent_id, agent_type, profile_ref, status"
                    ") VALUES (:tenant_id, :agent_id, 'IA', "
                    "'profile://p8-s48', 'ACTIVE')"
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
                    ":principal_id, :trigger_id, 'PROMPT', 'prompt://p8-s48', "
                    "'RUNNING', 'STEP_EXECUTION', :correlation_id, now())"
                ),
                {
                    "tenant_id": tenant_id,
                    "execution_id": agent_execution_id,
                    "agent_id": agent_id,
                    "principal_id": approver_id,
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
                    "step_id": executable_step_id,
                    "execution_id": agent_execution_id,
                    "interaction_id": str(uuid4()),
                    "correlation_id": f"corr-{suffix}",
                },
            )

        request_store = SqlAlchemyProtectedApprovalRequestStore(
            ae_factory,
            clock=lambda: datetime(2026, 10, 22, 11, 55, tzinfo=UTC),
        )
        wait_repository = SqlAlchemyWaitRegistrationRepository(ae_factory)
        wc_repository = SqlAlchemyApprovalWorkItemRepository(wc_factory)
        port = P8NSLApprovalPort(
            binding_source=BindingSource(
                {
                    "tenant_id": tenant_id,
                    "agent_execution_id": agent_execution_id,
                    "executable_step_id": executable_step_id,
                    "nsl_execution_id": nsl_execution_id,
                    "business_operation_id": business_operation_id,
                    "checkpoint_version": 8,
                    "target_approver_ref": approver_id,
                    "target_role_ref": None,
                    "target_org_scope_ref": None,
                    "target_project_scope_ref": None,
                }
            ),
            request_store=request_store,
            wait_repository=wait_repository,
            wc_client=ServiceClient(ApprovalWorkItemService(wc_repository)),
            clock=lambda: datetime(2026, 10, 22, 11, 55, tzinfo=UTC),
        )
        asyncio.run(port.publish(request))

        work_item = wc_repository.get_by_source(
            tenant_id=tenant_id,
            approval_domain="NSL_WRITE",
            source_ref=approval_request_id,
        )
        assert work_item is not None
        decision_service = ApprovalDecisionService(
            wc_repository,
            authorizer=ApprovalDecisionAuthorizer(
                AuthorizationSource(tenant_id=tenant_id, subject_id=approver_id),
                clock=lambda: datetime(2026, 10, 22, 11, 59, tzinfo=UTC),
            ),
            clock=lambda: datetime(2026, 10, 22, 12, tzinfo=UTC),
        )
        decision = decision_service.decide(
            tenant_id=tenant_id,
            approval_work_item_id=work_item["approval_work_item_id"],
            decision="APPROVE",
            decided_by=approver_id,
        )["decision"]
        terminal_item = wc_repository.get(
            tenant_id=tenant_id,
            approval_work_item_id=work_item["approval_work_item_id"],
        )
        protected = request_store.get(
            tenant_id=tenant_id,
            approval_request_id=approval_request_id,
        )
        canonical_request = request_store.load_request(
            tenant_id=tenant_id,
            approval_request_id=approval_request_id,
        )
        wait = wait_repository.get(
            tenant_id=tenant_id,
            agent_execution_id=agent_execution_id,
            executable_step_id=executable_step_id,
            wait_type="NSL_APPROVAL",
        )
        assert terminal_item is not None
        assert protected is not None
        assert canonical_request is not None
        assert wait is not None

        evidence = build_platform_approval_evidence(
            approval_request=canonical_request,
            protected_request=protected,
            wait_registration=wait,
            approval_work_item=terminal_item,
            approval_decision=decision,
            created_at=datetime(2026, 10, 22, 12, 1, tzinfo=UTC),
        )
        evidence_repository = SqlAlchemyPlatformApprovalEvidenceRepository(ae_factory)
        first = evidence_repository.create_or_get(evidence)
        replay = evidence_repository.create_or_get(evidence)

        assert first == replay
        assert first["approval_request_id"] == approval_request_id
        assert first["approval_work_item_ref"] == work_item["approval_work_item_id"]
        assert first["decision"] == "APPROVE"
        with ae_engine.connect() as connection:
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM ae_approval_evidence "
                        "WHERE tenant_id = :tenant_id"
                    ),
                    {"tenant_id": tenant_id},
                ).scalar_one()
                == 1
            )
    finally:
        with ae_engine.begin() as connection:
            for statement in (
                "DELETE FROM ae_approval_evidence WHERE tenant_id = :tenant_id",
                "DELETE FROM ae_wait_registration WHERE tenant_id = :tenant_id",
                "DELETE FROM ae_nsl_approval_request WHERE tenant_id = :tenant_id",
                "DELETE FROM ae_executable_step WHERE tenant_id = :tenant_id",
                "DELETE FROM ae_agent_execution WHERE tenant_id = :tenant_id",
                "DELETE FROM ae_agent_identity WHERE tenant_id = :tenant_id",
            ):
                connection.execute(text(statement), {"tenant_id": tenant_id})
        with wc_engine.begin() as connection:
            for statement in (
                "DELETE FROM wc_approval_outbox WHERE tenant_id = :tenant_id",
                "DELETE FROM wc_approval_decision WHERE tenant_id = :tenant_id",
                "DELETE FROM wc_approval_work_item WHERE tenant_id = :tenant_id",
            ):
                connection.execute(text(statement), {"tenant_id": tenant_id})
        ae_engine.dispose()
        wc_engine.dispose()
