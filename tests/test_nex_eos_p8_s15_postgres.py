from __future__ import annotations

import os
from datetime import date
from decimal import Decimal

import pytest
from nex_eos import (
    EOS_ACCOUNT_TABLE,
    EOS_NVT_PROJECT_TABLE,
    EOS_PROJECT_TABLE,
    EOS_VOUCHER_DRAFT_LINE_TABLE,
    EOS_VOUCHER_DRAFT_TABLE,
    AccountInput,
    NvtProjectInput,
    ProjectInput,
    SqlAlchemyEosAccountRepository,
    SqlAlchemyEosProjectRepository,
    SqlAlchemyEosVoucherRepository,
    VoucherDraftInput,
    VoucherLineInput,
    build_eos_database_runtime,
)
from sqlalchemy import text

DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
SMOKE_ENABLED = os.getenv("NEX_EOS_P8_S15_POSTGRES_SMOKE") == "1"
TENANT = "p8-s15-pg"
NVT_ID = "75000000-0000-4000-8000-000000000001"
PROJECT_ID = "76000000-0000-4000-8000-000000000001"
DEBIT_ID = "77000000-0000-4000-8000-000000000001"
CREDIT_ID = "77000000-0000-4000-8000-000000000002"
VOUCHER_ID = "78000000-0000-4000-8000-000000000001"

pytestmark = pytest.mark.skipif(
    not DATABASE_URL or not SMOKE_ENABLED,
    reason="Protected P8-S15 PostgreSQL smoke is disabled",
)


def _cleanup(runtime) -> None:
    with runtime.engine.begin() as connection:
        for table in (
            EOS_VOUCHER_DRAFT_LINE_TABLE,
            EOS_VOUCHER_DRAFT_TABLE,
            EOS_ACCOUNT_TABLE,
            EOS_PROJECT_TABLE,
            EOS_NVT_PROJECT_TABLE,
        ):
            connection.execute(table.delete().where(table.c.tenant_id == TENANT))


def test_s15_actual_postgres_balanced_voucher_transaction() -> None:
    runtime = build_eos_database_runtime(
        environ={"NEX_EOS_TEST_DATABASE_URL": DATABASE_URL},
        database_env="NEX_EOS_TEST_DATABASE_URL",
    )
    projects = SqlAlchemyEosProjectRepository(runtime.session_factory)
    accounts = SqlAlchemyEosAccountRepository(runtime.session_factory)
    vouchers = SqlAlchemyEosVoucherRepository(runtime.session_factory)
    _cleanup(runtime)
    try:
        with runtime.engine.connect() as connection:
            assert tuple(
                connection.execute(text("SELECT current_database(), current_user")).one()
            ) == ("nex_eos_test", "nex_eos_user")
            assert connection.execute(
                text(
                    "SELECT count(*) FROM schema_migrations "
                    "WHERE version = '2506_eos_voucher_draft'"
                )
            ).scalar_one() == 1
        projects.create_nvt_project(
            NvtProjectInput(TENANT, NVT_ID, "NVT-S15", "NVT S15")
        )
        projects.create_project(
            ProjectInput(TENANT, PROJECT_ID, "PROJECT", "Project", nvt_project_id=NVT_ID)
        )
        for account_id, code, category in (
            (DEBIT_ID, "TRAVEL", "EXPENSE"),
            (CREDIT_ID, "CASH", "ASSET"),
        ):
            accounts.create_account(
                AccountInput(
                    TENANT,
                    account_id,
                    code,
                    code,
                    category,
                    "GENERAL",
                    date(2026, 1, 1),
                )
            )
        created = vouchers.create_draft(
            VoucherDraftInput(
                TENANT,
                VOUCHER_ID,
                PROJECT_ID,
                date(2026, 10, 21),
                "Protected PostgreSQL draft",
                {"type": "oa.user", "id": "employee-1001"},
                {"type": "nsl.approval_request", "id": "approval-pg"},
                (
                    VoucherLineInput(DEBIT_ID, Decimal("42.50"), "TRAVEL"),
                    VoucherLineInput(CREDIT_ID, Decimal("-42.50"), "CASH"),
                ),
            )
        )
        assert created["state"] == "DRAFT"
        assert len(vouchers.get_draft(tenant_id=TENANT, voucher_id=VOUCHER_ID)["lines"]) == 2
    finally:
        _cleanup(runtime)
        with runtime.engine.connect() as connection:
            residue = connection.execute(
                text("SELECT count(*) FROM eos_voucher_draft WHERE tenant_id = :tenant"),
                {"tenant": TENANT},
            ).scalar_one()
        runtime.dispose()
    assert residue == 0
