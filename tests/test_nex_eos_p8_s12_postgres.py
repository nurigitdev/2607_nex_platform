from __future__ import annotations

import os

import pytest
from nex_eos import (
    EOS_NVT_PROJECT_TABLE,
    EOS_PROJECT_TABLE,
    EosProjectError,
    NvtProjectInput,
    ProjectInput,
    SqlAlchemyEosProjectRepository,
    build_eos_database_runtime,
)
from sqlalchemy import text

DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
SMOKE_ENABLED = os.getenv("NEX_EOS_P8_S12_POSTGRES_SMOKE") == "1"
TENANT_A = "p8-s12-pg-a"
TENANT_B = "p8-s12-pg-b"
NVT_ID = "43000000-0000-4000-8000-000000000001"
MOTHER_ID = "44000000-0000-4000-8000-000000000001"
CHILD_ID = "44000000-0000-4000-8000-000000000002"
GRANDCHILD_ID = "44000000-0000-4000-8000-000000000003"

pytestmark = pytest.mark.skipif(
    not DATABASE_URL or not SMOKE_ENABLED,
    reason="Protected P8-S12 PostgreSQL smoke is disabled",
)


def _cleanup(runtime) -> None:
    with runtime.engine.begin() as connection:
        connection.execute(
            EOS_PROJECT_TABLE.delete().where(
                EOS_PROJECT_TABLE.c.tenant_id.in_((TENANT_A, TENANT_B))
            )
        )
        connection.execute(
            EOS_NVT_PROJECT_TABLE.delete().where(
                EOS_NVT_PROJECT_TABLE.c.tenant_id.in_((TENANT_A, TENANT_B))
            )
        )


def test_s12_actual_postgres_hierarchy_and_tenant_isolation() -> None:
    runtime = build_eos_database_runtime(
        environ={"NEX_EOS_TEST_DATABASE_URL": DATABASE_URL},
        database_env="NEX_EOS_TEST_DATABASE_URL",
    )
    repository = SqlAlchemyEosProjectRepository(runtime.session_factory)
    _cleanup(runtime)
    try:
        with runtime.engine.connect() as connection:
            assert tuple(
                connection.execute(text("SELECT current_database(), current_user")).one()
            ) == ("nex_eos_test", "nex_eos_user")
            assert connection.execute(
                text(
                    "SELECT count(*) FROM schema_migrations "
                    "WHERE version = '2504_eos_project_hierarchy'"
                )
            ).scalar_one() == 1

        repository.create_nvt_project(
            NvtProjectInput(TENANT_A, NVT_ID, "NVT-PG", "NVT PostgreSQL")
        )
        mother = repository.create_project(
            ProjectInput(TENANT_A, MOTHER_ID, "MOTHER", "Mother", nvt_project_id=NVT_ID)
        )
        child = repository.create_project(
            ProjectInput(TENANT_A, CHILD_ID, "CHILD", "Child", parent_project_id=MOTHER_ID)
        )
        grandchild = repository.create_project(
            ProjectInput(
                TENANT_A,
                GRANDCHILD_ID,
                "GRANDCHILD",
                "Grandchild",
                parent_project_id=CHILD_ID,
            )
        )
        assert [mother["hierarchy_depth"], child["hierarchy_depth"], grandchild["hierarchy_depth"]] == [1, 2, 3]

        with pytest.raises(EosProjectError) as cross_tenant:
            repository.create_project(
                ProjectInput(
                    TENANT_B,
                    "44000000-0000-4000-8000-000000000004",
                    "CROSS",
                    "Cross tenant",
                    parent_project_id=MOTHER_ID,
                )
            )
        assert cross_tenant.value.error_code == "EOS_PROJECT_PARENT_NOT_FOUND"
    finally:
        _cleanup(runtime)
        with runtime.engine.connect() as connection:
            residue = connection.execute(
                text(
                    "SELECT count(*) FROM eos_project "
                    "WHERE tenant_id IN (:tenant_a, :tenant_b)"
                ),
                {"tenant_a": TENANT_A, "tenant_b": TENANT_B},
            ).scalar_one()
        runtime.dispose()
    assert residue == 0
