from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
from nex_eos import (
    EOS_ORG_UNIT_TABLE,
    EOS_POSITION_ASSIGNMENT_TABLE,
    EOS_POSITION_TABLE,
    EosOrganizationError,
    OrgUnitInput,
    PositionAssignmentInput,
    PositionInput,
    SqlAlchemyEosOrganizationRepository,
    build_eos_database_runtime,
)
from sqlalchemy import text

DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
SMOKE_ENABLED = os.getenv("NEX_EOS_P8_S10_POSTGRES_SMOKE") == "1"
TENANT_A = "p8-s10-pg-a"
TENANT_B = "p8-s10-pg-b"
NOW = datetime(2026, 10, 21, 9, 30, tzinfo=UTC)
ORG_ID = "a0000000-0000-4000-8000-000000000001"
POSITION_ID = "b0000000-0000-4000-8000-000000000001"
ASSIGNMENT_ID = "c0000000-0000-4000-8000-000000000001"

pytestmark = pytest.mark.skipif(
    not DATABASE_URL or not SMOKE_ENABLED,
    reason="Protected P8-S10 PostgreSQL smoke is disabled",
)


def _cleanup(runtime) -> None:
    with runtime.engine.begin() as connection:
        for table in (
            EOS_POSITION_ASSIGNMENT_TABLE,
            EOS_POSITION_TABLE,
            EOS_ORG_UNIT_TABLE,
        ):
            connection.execute(table.delete().where(table.c.tenant_id.in_((TENANT_A, TENANT_B))))


def test_s10_actual_postgres_organization_scope_and_assignment_policy() -> None:
    runtime = build_eos_database_runtime(
        environ={"NEX_EOS_TEST_DATABASE_URL": DATABASE_URL},
        database_env="NEX_EOS_TEST_DATABASE_URL",
    )
    repository = SqlAlchemyEosOrganizationRepository(runtime.session_factory)
    _cleanup(runtime)
    try:
        with runtime.engine.connect() as connection:
            assert tuple(
                connection.execute(text("SELECT current_database(), current_user")).one()
            ) == ("nex_eos_test", "nex_eos_user")
            assert connection.execute(
                text(
                    "SELECT count(*) FROM schema_migrations "
                    "WHERE version = '2502_eos_organization_core'"
                )
            ).scalar_one() == 1

        repository.create_org_unit(
            OrgUnitInput(
                tenant_id=TENANT_A,
                org_unit_id=ORG_ID,
                org_unit_code="PG-COMPANY",
                name="PostgreSQL Company",
                org_unit_type="COMPANY",
                effective_from=NOW,
            )
        )
        repository.create_position(
            PositionInput(
                tenant_id=TENANT_A,
                position_id=POSITION_ID,
                position_type="CEO",
                org_unit_id=ORG_ID,
            )
        )
        repository.assign_position(
            PositionAssignmentInput(
                tenant_id=TENANT_A,
                position_assignment_id=ASSIGNMENT_ID,
                position_id=POSITION_ID,
                principal_ref={"type": "oa.user", "id": "employee-pg-1"},
                effective_from=NOW,
            )
        )

        effective = repository.effective_assignment(
            tenant_id=TENANT_A,
            position_id=POSITION_ID,
            effective_at=NOW + timedelta(seconds=1),
        )
        assert effective is not None
        assert effective["principal_id"] == "employee-pg-1"

        with pytest.raises(EosOrganizationError) as duplicate:
            repository.assign_position(
                PositionAssignmentInput(
                    tenant_id=TENANT_A,
                    position_assignment_id="c0000000-0000-4000-8000-000000000002",
                    position_id=POSITION_ID,
                    principal_ref={"type": "oa.user", "id": "employee-pg-2"},
                    effective_from=NOW,
                )
            )
        assert duplicate.value.error_code == "EOS_ACTIVE_POSITION_ASSIGNED"

        with pytest.raises(EosOrganizationError) as cross_tenant:
            repository.create_position(
                PositionInput(
                    tenant_id=TENANT_B,
                    position_id="b0000000-0000-4000-8000-000000000002",
                    position_type="CEO",
                    org_unit_id=ORG_ID,
                )
            )
        assert cross_tenant.value.error_code == "EOS_ORG_UNIT_NOT_FOUND"

        with runtime.engine.connect() as connection:
            counts = connection.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM eos_org_unit WHERE tenant_id = :tenant), "
                    "(SELECT count(*) FROM eos_position WHERE tenant_id = :tenant), "
                    "(SELECT count(*) FROM eos_position_assignment WHERE tenant_id = :tenant)"
                ),
                {"tenant": TENANT_A},
            ).one()
        assert tuple(counts) == (1, 1, 1)
    finally:
        _cleanup(runtime)
        with runtime.engine.connect() as connection:
            residue = connection.execute(
                text(
                    "SELECT count(*) FROM eos_org_unit "
                    "WHERE tenant_id IN (:tenant_a, :tenant_b)"
                ),
                {"tenant_a": TENANT_A, "tenant_b": TENANT_B},
            ).scalar_one()
        runtime.dispose()
    assert residue == 0
