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
    EOS_PROJECT_TABLE,
    ApprovalInstanceInput,
    ApprovalPolicyInput,
    ApprovalPolicyStageInput,
    NvtProjectInput,
    OrgUnitInput,
    ProjectInput,
    SqlAlchemyEosApprovalInstanceRepository,
    SqlAlchemyEosApprovalPolicyRepository,
    SqlAlchemyEosOrganizationRepository,
    SqlAlchemyEosProjectRepository,
    build_eos_database_runtime,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url

DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
SMOKE_ENABLED = os.getenv("NEX_EOS_P8_S70_POSTGRES_SMOKE") == "1"
TENANT = "p8-s70-pg"
INSTANCE_ID = "71000000-0000-4000-8000-000000000001"
POLICY_ID = "71000000-0000-4000-8000-000000000002"
OPERATION_ID = "71000000-0000-4000-8000-000000000003"
ORG_ID = "71000000-0000-4000-8000-000000000004"
NVT_ID = "71000000-0000-4000-8000-000000000005"
PROJECT_ID = "71000000-0000-4000-8000-000000000006"
NOW = datetime(2026, 10, 23, 11, 0, tzinfo=UTC)
PAYLOAD_HASH = semantic_sha256_hash_ref({"amount": "1250.00"})
INTENT_HASH = semantic_sha256_hash_ref({"write": "voucher-draft"})

pytestmark = pytest.mark.skipif(
    not DATABASE_URL or not SMOKE_ENABLED,
    reason="Protected P8-S70 PostgreSQL smoke is disabled",
)

TABLES = (
    EOS_APPROVAL_DECISION_TABLE,
    EOS_APPROVAL_STAGE_TABLE,
    EOS_APPROVAL_INSTANCE_TABLE,
    EOS_APPROVAL_POLICY_STAGE_TABLE,
    EOS_APPROVAL_POLICY_TABLE,
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_PROJECT_TABLE,
    EOS_NVT_PROJECT_TABLE,
    EOS_ORG_UNIT_TABLE,
)


def _cleanup(runtime) -> dict[str, int]:
    with runtime.engine.begin() as connection:
        for table in TABLES:
            connection.execute(table.delete().where(table.c.tenant_id == TENANT))
    with runtime.engine.connect() as connection:
        return {
            table.name: connection.execute(
                select(func.count())
                .select_from(table)
                .where(table.c.tenant_id == TENANT)
            ).scalar_one()
            for table in TABLES
        }


def test_s70_actual_postgres_snapshot_restart_replay_and_zero_residue() -> None:
    target = make_url(DATABASE_URL)
    assert target.username == "nex_eos_user"
    assert target.database == "nex_eos_test"
    runtime = build_eos_database_runtime(
        environ={"NEX_EOS_TEST_DATABASE_URL": DATABASE_URL},
        database_env="NEX_EOS_TEST_DATABASE_URL",
    )
    _cleanup(runtime)
    try:
        with runtime.engine.connect() as connection:
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

        SqlAlchemyEosOrganizationRepository(runtime.session_factory).create_org_unit(
            OrgUnitInput(
                TENANT,
                ORG_ID,
                "P8-S70-PG-FINANCE",
                "P8-S70 PostgreSQL Finance",
                "TEAM",
                NOW - timedelta(days=1),
            )
        )
        projects = SqlAlchemyEosProjectRepository(runtime.session_factory)
        projects.create_nvt_project(
            NvtProjectInput(TENANT, NVT_ID, "P8-S70-PG-NVT", "P8-S70 PG NVT")
        )
        projects.create_project(
            ProjectInput(
                TENANT,
                PROJECT_ID,
                "P8-S70-PG-PROJECT",
                "P8-S70 PG Project",
                nvt_project_id=NVT_ID,
            )
        )
        policy = SqlAlchemyEosApprovalPolicyRepository(runtime.session_factory)
        policy.create_policy(
            ApprovalPolicyInput(
                tenant_id=TENANT,
                approval_policy_id=POLICY_ID,
                policy_key="finance.voucher.p8-s70-pg",
                name="P8-S70 protected policy",
                approval_domain="BUSINESS_FORMAL",
                effective_from=NOW - timedelta(days=1),
                stages=(
                    ApprovalPolicyStageInput("TEAM_LEAD"),
                    ApprovalPolicyStageInput("GROUP_LEAD"),
                ),
            )
        )
        with runtime.engine.begin() as connection:
            connection.execute(
                EOS_BUSINESS_OPERATION_TABLE.insert().values(
                    tenant_id=TENANT,
                    business_operation_id=OPERATION_ID,
                    idempotency_key="p8-s70-pg-operation",
                    operation="CREATE_VOUCHER_DRAFT",
                    payload_hash=PAYLOAD_HASH,
                    commit_state="COMMITTED",
                    result_json={"voucher_id": "p8-s70-pg-voucher"},
                    created_at=NOW - timedelta(minutes=1),
                    committed_at=NOW - timedelta(seconds=30),
                )
            )

        request = ApprovalInstanceInput(
            tenant_id=TENANT,
            approval_instance_id=INSTANCE_ID,
            idempotency_key="p8-s70-pg-approval",
            approval_policy_id=POLICY_ID,
            business_operation_id=OPERATION_ID,
            protected_operation_ref="eos:business-operation:p8-s70-pg",
            payload_hash=PAYLOAD_HASH,
            write_intent_hash=INTENT_HASH,
            requester_ref={"type": "oa.user", "id": "employee-p8-s70"},
            org_unit_id=ORG_ID,
            project_id=PROJECT_ID,
            correlation_id="p8-s70-pg-correlation",
            causation_id="p8-s70-pg-causation",
            expires_at=NOW + timedelta(days=7),
        )
        repository = SqlAlchemyEosApprovalInstanceRepository(
            runtime.session_factory, clock=lambda: NOW
        )
        created, was_created = repository.create_or_get_instance(request)
        assert was_created is True
        assert [stage["state"] for stage in created["stages"]] == [
            "ACTIVE",
            "WAITING",
        ]

        restarted = SqlAlchemyEosApprovalInstanceRepository(
            runtime.session_factory, clock=lambda: NOW
        )
        replay, replay_created = restarted.create_or_get_instance(request)
        assert replay_created is False
        assert replay == created
        assert (
            restarted.get_instance(tenant_id=TENANT, approval_instance_id=INSTANCE_ID)
            == created
        )
        assert (
            restarted.get_active_stage(
                tenant_id=TENANT, approval_instance_id=INSTANCE_ID
            )["stage_order"]
            == 1
        )
        assert (
            restarted.list_decisions(tenant_id=TENANT, approval_instance_id=INSTANCE_ID)
            == []
        )
        assert (
            restarted.get_instance(
                tenant_id="other-tenant", approval_instance_id=INSTANCE_ID
            )
            is None
        )
    finally:
        residue = _cleanup(runtime)
        runtime.dispose()
    assert residue == {table.name: 0 for table in TABLES}
