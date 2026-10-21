from __future__ import annotations

import os
from datetime import date

import pytest
from nex_eos import (
    EOS_ACCOUNT_TABLE,
    AccountInput,
    SqlAlchemyEosAccountRepository,
    build_eos_database_runtime,
)
from sqlalchemy import text

DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
SMOKE_ENABLED = os.getenv("NEX_EOS_P8_S14_POSTGRES_SMOKE") == "1"
TENANT = "p8-s14-pg"
ACCOUNT_ID = "62000000-0000-4000-8000-000000000001"

pytestmark = pytest.mark.skipif(
    not DATABASE_URL or not SMOKE_ENABLED,
    reason="Protected P8-S14 PostgreSQL smoke is disabled",
)


def test_s14_actual_postgres_effective_account_and_zero_residue() -> None:
    runtime = build_eos_database_runtime(
        environ={"NEX_EOS_TEST_DATABASE_URL": DATABASE_URL},
        database_env="NEX_EOS_TEST_DATABASE_URL",
    )
    repository = SqlAlchemyEosAccountRepository(runtime.session_factory)
    with runtime.engine.begin() as connection:
        connection.execute(
            EOS_ACCOUNT_TABLE.delete().where(EOS_ACCOUNT_TABLE.c.tenant_id == TENANT)
        )
    try:
        with runtime.engine.connect() as connection:
            assert tuple(
                connection.execute(text("SELECT current_database(), current_user")).one()
            ) == ("nex_eos_test", "nex_eos_user")
            assert connection.execute(
                text(
                    "SELECT count(*) FROM schema_migrations "
                    "WHERE version = '2505_eos_account'"
                )
            ).scalar_one() == 1
        repository.create_account(
            AccountInput(
                TENANT,
                ACCOUNT_ID,
                "TRAVEL",
                "Travel expense",
                "EXPENSE",
                "OPERATING_EXPENSE",
                date(2026, 1, 1),
            )
        )
        assert repository.get_effective_account(
            tenant_id=TENANT,
            account_id=ACCOUNT_ID,
            effective_at=date(2026, 10, 21),
        )["account_code"] == "TRAVEL"
        assert repository.get_effective_account(
            tenant_id="other-tenant",
            account_id=ACCOUNT_ID,
            effective_at=date(2026, 10, 21),
        ) is None
    finally:
        with runtime.engine.begin() as connection:
            connection.execute(
                EOS_ACCOUNT_TABLE.delete().where(
                    EOS_ACCOUNT_TABLE.c.tenant_id == TENANT
                )
            )
        with runtime.engine.connect() as connection:
            residue = connection.execute(
                text("SELECT count(*) FROM eos_account WHERE tenant_id = :tenant"),
                {"tenant": TENANT},
            ).scalar_one()
        runtime.dispose()
    assert residue == 0
