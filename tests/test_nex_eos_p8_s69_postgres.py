from __future__ import annotations

import os
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from nex_eos import (
    EOS_ACCOUNT_TABLE,
    EOS_APPROVAL_POLICY_STAGE_TABLE,
    EOS_APPROVAL_POLICY_TABLE,
    EOS_NVT_PROJECT_TABLE,
    EOS_PROJECT_TABLE,
    AccountInput,
    ApprovalPolicyInput,
    ApprovalPolicySelection,
    ApprovalPolicyStageInput,
    NvtProjectInput,
    ProjectInput,
    SqlAlchemyEosAccountRepository,
    SqlAlchemyEosApprovalPolicyRepository,
    SqlAlchemyEosProjectRepository,
    build_eos_database_runtime,
)
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url

DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
SMOKE_ENABLED = os.getenv("NEX_EOS_P8_S69_POSTGRES_SMOKE") == "1"
TENANT = "p8-s69-pg"
POLICY_ID = "b1000000-0000-4000-8000-000000000001"
NVT_ID = "b2000000-0000-4000-8000-000000000001"
PROJECT_ID = "b3000000-0000-4000-8000-000000000001"
ACCOUNT_ID = "b4000000-0000-4000-8000-000000000001"
NOW = datetime(2026, 10, 23, 10, 0, tzinfo=UTC)

pytestmark = pytest.mark.skipif(
    not DATABASE_URL or not SMOKE_ENABLED,
    reason="Protected P8-S69 PostgreSQL smoke is disabled",
)

TABLES = (
    EOS_APPROVAL_POLICY_STAGE_TABLE,
    EOS_APPROVAL_POLICY_TABLE,
    EOS_ACCOUNT_TABLE,
    EOS_PROJECT_TABLE,
    EOS_NVT_PROJECT_TABLE,
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


def test_s69_actual_postgres_policy_restart_selection_and_zero_residue() -> None:
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
                        "WHERE version = '2509_eos_approval_policy'"
                    )
                ).scalar_one()
                == 1
            )

        projects = SqlAlchemyEosProjectRepository(runtime.session_factory)
        projects.create_nvt_project(
            NvtProjectInput(TENANT, NVT_ID, "P8-S69-NVT", "P8-S69 NVT")
        )
        projects.create_project(
            ProjectInput(
                TENANT,
                PROJECT_ID,
                "P8-S69-PROJECT",
                "P8-S69 Project",
                nvt_project_id=NVT_ID,
            )
        )
        SqlAlchemyEosAccountRepository(runtime.session_factory).create_account(
            AccountInput(
                TENANT,
                ACCOUNT_ID,
                "P8-S69-EXPENSE",
                "P8-S69 expense",
                "EXPENSE",
                "OPERATING_EXPENSE",
                date(2026, 1, 1),
            )
        )
        repository = SqlAlchemyEosApprovalPolicyRepository(runtime.session_factory)
        created = repository.create_policy(
            ApprovalPolicyInput(
                tenant_id=TENANT,
                approval_policy_id=POLICY_ID,
                policy_key="finance.voucher.p8-s69",
                name="P8-S69 protected policy",
                approval_domain="BUSINESS_FORMAL",
                risk_level="HIGH",
                minimum_amount=Decimal("100.00"),
                maximum_amount=Decimal("1000.00"),
                project_id=PROJECT_ID,
                account_id=ACCOUNT_ID,
                transaction_type="FINANCE.CREATE_VOUCHER_DRAFT",
                effective_from=NOW,
                stages=(
                    ApprovalPolicyStageInput("TEAM_LEAD"),
                    ApprovalPolicyStageInput("GROUP_LEAD"),
                ),
            )
        )

        restarted = SqlAlchemyEosApprovalPolicyRepository(runtime.session_factory)
        assert (
            restarted.get_policy(tenant_id=TENANT, approval_policy_id=POLICY_ID)
            == created
        )
        resolved = restarted.resolve_policy(
            ApprovalPolicySelection(
                tenant_id=TENANT,
                approval_domain="BUSINESS_FORMAL",
                risk_level="HIGH",
                amount=Decimal("250.00"),
                project_id=PROJECT_ID,
                account_ids=(ACCOUNT_ID,),
                transaction_type="FINANCE.CREATE_VOUCHER_DRAFT",
                effective_at=NOW,
            )
        )
        assert resolved["approval_policy_id"] == POLICY_ID
        assert [stage["position_type"] for stage in resolved["stages"]] == [
            "TEAM_LEAD",
            "GROUP_LEAD",
        ]
        assert (
            restarted.resolve_policy(
                ApprovalPolicySelection(
                    tenant_id="other-tenant",
                    approval_domain="BUSINESS_FORMAL",
                    risk_level="HIGH",
                    amount=Decimal("250.00"),
                    transaction_type="FINANCE.CREATE_VOUCHER_DRAFT",
                    effective_at=NOW,
                )
            )
            is None
        )
    finally:
        residue = _cleanup(runtime)
        runtime.dispose()
    assert residue == {table.name: 0 for table in TABLES}
