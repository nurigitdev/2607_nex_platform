from __future__ import annotations

import os

import pytest
from nex_eos import (
    EOS_NVT_PROJECT_TABLE,
    EOS_PROJECT_MEMBER_TABLE,
    EOS_PROJECT_TABLE,
    NvtProjectInput,
    ProjectInput,
    ProjectMembershipInput,
    SqlAlchemyEosProjectMembershipRepository,
    SqlAlchemyEosProjectRepository,
    build_eos_database_runtime,
)
from sqlalchemy import text

DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
SMOKE_ENABLED = os.getenv("NEX_EOS_P8_S94_POSTGRES_SMOKE") == "1"
TENANT_ID = "p8-s94-pg"
NVT_ID = "84000000-0000-4000-8000-000000000001"
PROJECT_ID = "85000000-0000-4000-8000-000000000001"
MEMBERSHIP_ID = "86000000-0000-4000-8000-000000000001"

pytestmark = pytest.mark.skipif(
    not DATABASE_URL or not SMOKE_ENABLED,
    reason="Protected P8-S94 PostgreSQL smoke is disabled",
)


def _cleanup(runtime) -> None:
    with runtime.engine.begin() as connection:
        connection.execute(
            EOS_PROJECT_MEMBER_TABLE.delete().where(
                EOS_PROJECT_MEMBER_TABLE.c.tenant_id == TENANT_ID
            )
        )
        connection.execute(
            EOS_PROJECT_TABLE.delete().where(EOS_PROJECT_TABLE.c.tenant_id == TENANT_ID)
        )
        connection.execute(
            EOS_NVT_PROJECT_TABLE.delete().where(
                EOS_NVT_PROJECT_TABLE.c.tenant_id == TENANT_ID
            )
        )


def test_s94_actual_postgres_migration_persistence_and_cleanup() -> None:
    runtime = build_eos_database_runtime(
        environ={"NEX_EOS_TEST_DATABASE_URL": DATABASE_URL},
        database_env="NEX_EOS_TEST_DATABASE_URL",
    )
    projects = SqlAlchemyEosProjectRepository(runtime.session_factory)
    memberships = SqlAlchemyEosProjectMembershipRepository(runtime.session_factory)
    _cleanup(runtime)
    try:
        with runtime.engine.connect() as connection:
            assert tuple(
                connection.execute(text("SELECT current_database(), current_user")).one()
            ) == ("nex_eos_test", "nex_eos_user")
            assert connection.execute(
                text(
                    "SELECT count(*) FROM schema_migrations "
                    "WHERE version = '2514_eos_project_member'"
                )
            ).scalar_one() == 1

        projects.create_nvt_project(
            NvtProjectInput(TENANT_ID, NVT_ID, "NVT-S94", "NVT S94")
        )
        projects.create_project(
            ProjectInput(
                TENANT_ID,
                PROJECT_ID,
                "PROJECT-S94",
                "Project S94",
                nvt_project_id=NVT_ID,
            )
        )
        memberships.create_membership(
            ProjectMembershipInput(
                TENANT_ID,
                MEMBERSHIP_ID,
                PROJECT_ID,
                "subject-s94",
                "OWNER",
                "operator-s94",
            )
        )
        loaded = memberships.get_membership(
            tenant_id=TENANT_ID,
            project_membership_id=MEMBERSHIP_ID,
        )
        assert loaded is not None
        assert loaded["project_id"] == PROJECT_ID
        assert loaded["subject_id"] == "subject-s94"
        assert loaded["member_role"] == "OWNER"
    finally:
        _cleanup(runtime)
        with runtime.engine.connect() as connection:
            residue = connection.execute(
                text(
                    "SELECT count(*) FROM eos_project_member "
                    "WHERE tenant_id = :tenant_id"
                ),
                {"tenant_id": TENANT_ID},
            ).scalar_one()
        runtime.dispose()
    assert residue == 0
