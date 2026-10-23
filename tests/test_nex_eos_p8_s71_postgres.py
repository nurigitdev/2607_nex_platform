from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
from nex_eos import (
    EOS_APPROVAL_DECISION_TABLE,
    EOS_APPROVAL_INSTANCE_TABLE,
    EOS_APPROVAL_POLICY_STAGE_TABLE,
    EOS_APPROVAL_POLICY_TABLE,
    EOS_APPROVAL_STAGE_TABLE,
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_NVT_PROJECT_TABLE,
    EOS_ORG_UNIT_TABLE,
    EOS_POSITION_ASSIGNMENT_TABLE,
    EOS_POSITION_TABLE,
    EOS_PROJECT_TABLE,
    ApprovalInstanceInput,
    ApprovalPolicyInput,
    ApprovalPolicyStageInput,
    EosApproverResolutionService,
    EosBusinessFormalWcAdapter,
    NvtProjectInput,
    OrgUnitInput,
    PositionAssignmentInput,
    PositionInput,
    ProjectInput,
    SqlAlchemyEosApprovalInstanceRepository,
    SqlAlchemyEosApprovalPolicyRepository,
    SqlAlchemyEosOrganizationRepository,
    SqlAlchemyEosProjectRepository,
    build_eos_database_runtime,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from nex_wc.approvals import (
    ApprovalWorkItemService,
    SqlAlchemyApprovalWorkItemRepository,
)
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

EOS_DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
WC_DATABASE_URL = os.getenv("NEX_WC_TEST_DATABASE_URL", "")
SMOKE_ENABLED = (
    os.getenv("NEX_EOS_P8_S71_POSTGRES_SMOKE") == "1"
    or os.getenv("NEX_EOS_P8_S72_POSTGRES_SMOKE") == "1"
)
TENANT = "p8-s71-pg"
INSTANCE_ID = "73000000-0000-4000-8000-000000000001"
POLICY_ID = "73000000-0000-4000-8000-000000000002"
OPERATION_ID = "73000000-0000-4000-8000-000000000003"
ORG_ID = "73000000-0000-4000-8000-000000000004"
NVT_ID = "73000000-0000-4000-8000-000000000005"
PROJECT_ID = "73000000-0000-4000-8000-000000000006"
POSITION_ID = "73000000-0000-4000-8000-000000000007"
ASSIGNMENT_ID = "73000000-0000-4000-8000-000000000008"
NOW = datetime(2026, 10, 23, 13, 0, tzinfo=UTC)
PAYLOAD_HASH = semantic_sha256_hash_ref({"amount": "1500.00"})
INTENT_HASH = semantic_sha256_hash_ref({"write": "voucher-draft"})

pytestmark = pytest.mark.skipif(
    not EOS_DATABASE_URL or not WC_DATABASE_URL or not SMOKE_ENABLED,
    reason="Protected P8-S71 EOS/WC PostgreSQL smoke is disabled",
)

EOS_TABLES = (
    EOS_APPROVAL_DECISION_TABLE,
    EOS_APPROVAL_STAGE_TABLE,
    EOS_APPROVAL_INSTANCE_TABLE,
    EOS_APPROVAL_POLICY_STAGE_TABLE,
    EOS_APPROVAL_POLICY_TABLE,
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_PROJECT_TABLE,
    EOS_NVT_PROJECT_TABLE,
    EOS_POSITION_ASSIGNMENT_TABLE,
    EOS_POSITION_TABLE,
    EOS_ORG_UNIT_TABLE,
)


class RepositoryClient:
    def __init__(self, repository):
        self._service = ApprovalWorkItemService(repository)

    def create_or_get(self, work_item):
        return self._service.create_or_get(work_item)


def _cleanup_eos(runtime) -> dict[str, int]:
    with runtime.engine.begin() as connection:
        for table in EOS_TABLES:
            connection.execute(table.delete().where(table.c.tenant_id == TENANT))
    with runtime.engine.connect() as connection:
        return {
            table.name: connection.execute(
                select(func.count())
                .select_from(table)
                .where(table.c.tenant_id == TENANT)
            ).scalar_one()
            for table in EOS_TABLES
        }


def _cleanup_wc(engine) -> dict[str, int]:
    tables = ("wc_approval_outbox", "wc_approval_decision", "wc_approval_work_item")
    with engine.begin() as connection:
        for table_name in tables:
            connection.execute(
                text(f"DELETE FROM {table_name} WHERE tenant_id = :tenant_id"),
                {"tenant_id": TENANT},
            )
    with engine.connect() as connection:
        return {
            table_name: connection.execute(
                text(
                    f"SELECT count(*) FROM {table_name} " "WHERE tenant_id = :tenant_id"
                ),
                {"tenant_id": TENANT},
            ).scalar_one()
            for table_name in tables
        }


def test_s71_actual_eos_wc_postgres_projection_restart_and_zero_residue() -> None:
    eos_target = make_url(EOS_DATABASE_URL)
    wc_target = make_url(WC_DATABASE_URL)
    assert (eos_target.username, eos_target.database) == (
        "nex_eos_user",
        "nex_eos_test",
    )
    assert (wc_target.username, wc_target.database) == (
        "nex_wc_user",
        "nex_wc_test",
    )
    eos = build_eos_database_runtime(
        environ={"NEX_EOS_TEST_DATABASE_URL": EOS_DATABASE_URL},
        database_env="NEX_EOS_TEST_DATABASE_URL",
    )
    wc_engine = create_engine(WC_DATABASE_URL, pool_pre_ping=True)
    wc_sessions = sessionmaker(
        bind=wc_engine,
        autoflush=False,
        expire_on_commit=False,
    )
    _cleanup_eos(eos)
    _cleanup_wc(wc_engine)
    try:
        with eos.engine.connect() as connection:
            assert tuple(
                connection.execute(
                    text("SELECT current_database(), current_user")
                ).one()
            ) == ("nex_eos_test", "nex_eos_user")
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM schema_migrations "
                        "WHERE version = '2510_eos_approval_instance'"
                    )
                ).scalar_one()
                == 1
            )
        with wc_engine.connect() as connection:
            assert tuple(
                connection.execute(
                    text("SELECT current_database(), current_user")
                ).one()
            ) == ("nex_wc_test", "nex_wc_user")
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM schema_migrations "
                        "WHERE version = '1006_wc_approval_foundation'"
                    )
                ).scalar_one()
                == 1
            )

        organization = SqlAlchemyEosOrganizationRepository(eos.session_factory)
        organization.create_org_unit(
            OrgUnitInput(
                TENANT,
                ORG_ID,
                "P8-S71-PG-FINANCE",
                "P8-S71 PostgreSQL Finance",
                "TEAM",
                NOW - timedelta(days=1),
            )
        )
        organization.create_position(
            PositionInput(TENANT, POSITION_ID, "TEAM_LEAD", ORG_ID)
        )
        organization.assign_position(
            PositionAssignmentInput(
                TENANT,
                ASSIGNMENT_ID,
                POSITION_ID,
                {"type": "oa.user", "id": "employee-p8-s72-approver"},
                NOW - timedelta(hours=1),
            )
        )
        projects = SqlAlchemyEosProjectRepository(eos.session_factory)
        projects.create_nvt_project(
            NvtProjectInput(TENANT, NVT_ID, "P8-S71-PG-NVT", "P8-S71 PG NVT")
        )
        projects.create_project(
            ProjectInput(
                TENANT,
                PROJECT_ID,
                "P8-S71-PG-PROJECT",
                "P8-S71 PG Project",
                nvt_project_id=NVT_ID,
            )
        )
        SqlAlchemyEosApprovalPolicyRepository(eos.session_factory).create_policy(
            ApprovalPolicyInput(
                tenant_id=TENANT,
                approval_policy_id=POLICY_ID,
                policy_key="finance.voucher.p8-s71-pg",
                name="P8-S71 protected policy",
                approval_domain="BUSINESS_FORMAL",
                effective_from=NOW - timedelta(days=1),
                stages=(
                    ApprovalPolicyStageInput("TEAM_LEAD"),
                    ApprovalPolicyStageInput("GROUP_LEAD"),
                ),
            )
        )
        with eos.engine.begin() as connection:
            connection.execute(
                EOS_BUSINESS_OPERATION_TABLE.insert().values(
                    tenant_id=TENANT,
                    business_operation_id=OPERATION_ID,
                    idempotency_key="p8-s71-pg-operation",
                    operation="CREATE_VOUCHER_DRAFT",
                    payload_hash=PAYLOAD_HASH,
                    commit_state="COMMITTED",
                    result_json={"voucher_id": "p8-s71-pg-voucher"},
                    created_at=NOW - timedelta(minutes=1),
                    committed_at=NOW - timedelta(seconds=30),
                )
            )
        eos_instances = SqlAlchemyEosApprovalInstanceRepository(
            eos.session_factory, clock=lambda: NOW
        )
        instance, _ = eos_instances.create_or_get_instance(
            ApprovalInstanceInput(
                tenant_id=TENANT,
                approval_instance_id=INSTANCE_ID,
                idempotency_key="p8-s71-pg-approval",
                approval_policy_id=POLICY_ID,
                business_operation_id=OPERATION_ID,
                protected_operation_ref="eos:business-operation:p8-s71-pg",
                payload_hash=PAYLOAD_HASH,
                write_intent_hash=INTENT_HASH,
                requester_ref={"type": "oa.user", "id": "employee-p8-s71"},
                org_unit_id=ORG_ID,
                project_id=PROJECT_ID,
                correlation_id="p8-s71-pg-correlation",
                causation_id="p8-s71-pg-causation",
                expires_at=NOW + timedelta(days=7),
            )
        )
        wc_repository = SqlAlchemyApprovalWorkItemRepository(wc_sessions)
        adapter = EosBusinessFormalWcAdapter(
            approval_instances=eos_instances,
            approver_resolution=EosApproverResolutionService(
                organization, clock=lambda: NOW
            ),
            wc_client=RepositoryClient(wc_repository),
            clock=lambda: NOW,
        )
        projected = adapter.project_active_stage(
            tenant_id=TENANT, approval_instance_id=INSTANCE_ID
        )
        assert projected["created"] is True
        assert (
            projected["approval_stage_id"] == instance["stages"][0]["approval_stage_id"]
        )
        assert projected["work_item"]["approval_domain"] == "BUSINESS_FORMAL"
        assert projected["work_item"]["target_role_ref"] == "TEAM_LEAD"
        assert (
            projected["work_item"]["target_approver_ref"] == "employee-p8-s72-approver"
        )

        restarted_wc = SqlAlchemyApprovalWorkItemRepository(wc_sessions)
        restarted = EosBusinessFormalWcAdapter(
            approval_instances=SqlAlchemyEosApprovalInstanceRepository(
                eos.session_factory, clock=lambda: NOW
            ),
            approver_resolution=EosApproverResolutionService(
                SqlAlchemyEosOrganizationRepository(eos.session_factory),
                clock=lambda: NOW + timedelta(minutes=1),
            ),
            wc_client=RepositoryClient(restarted_wc),
            clock=lambda: NOW + timedelta(minutes=1),
        )
        replay = restarted.project_active_stage(
            tenant_id=TENANT, approval_instance_id=INSTANCE_ID
        )
        assert replay["created"] is False
        assert replay["work_item"] == projected["work_item"]
        assert (
            restarted_wc.get_by_source(
                tenant_id=TENANT,
                approval_domain="BUSINESS_FORMAL",
                source_ref=projected["work_item"]["source_ref"],
            )
            == projected["work_item"]
        )
        assert (
            restarted_wc.get_by_source(
                tenant_id="other-tenant",
                approval_domain="BUSINESS_FORMAL",
                source_ref=projected["work_item"]["source_ref"],
            )
            is None
        )
    finally:
        wc_residue = _cleanup_wc(wc_engine)
        eos_residue = _cleanup_eos(eos)
        wc_engine.dispose()
        eos.dispose()
    assert wc_residue == {
        "wc_approval_outbox": 0,
        "wc_approval_decision": 0,
        "wc_approval_work_item": 0,
    }
    assert eos_residue == {table.name: 0 for table in EOS_TABLES}
