from __future__ import annotations

import os

import pytest
from nex_eos import (
    EOS_NVT_PROJECT_TABLE,
    EOS_PROJECT_TABLE,
    NvtProjectInput,
    ProjectInput,
    SqlAlchemyEosProjectRepository,
    build_eos_database_runtime,
)

DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
SMOKE_ENABLED = os.getenv("NEX_EOS_P8_S13_POSTGRES_SMOKE") == "1"
TENANT = "p8-s13-pg"
NVT_ID = "53000000-0000-4000-8000-000000000001"
MOTHER_ID = "54000000-0000-4000-8000-000000000001"
CHILD_ID = "54000000-0000-4000-8000-000000000002"
DEEP_ID = "54000000-0000-4000-8000-000000000003"

pytestmark = pytest.mark.skipif(
    not DATABASE_URL or not SMOKE_ENABLED,
    reason="Protected P8-S13 PostgreSQL smoke is disabled",
)


def _cleanup(runtime) -> None:
    with runtime.engine.begin() as connection:
        connection.execute(
            EOS_PROJECT_TABLE.delete().where(EOS_PROJECT_TABLE.c.tenant_id == TENANT)
        )
        connection.execute(
            EOS_NVT_PROJECT_TABLE.delete().where(
                EOS_NVT_PROJECT_TABLE.c.tenant_id == TENANT
            )
        )


def test_s13_actual_postgres_recursive_resolution() -> None:
    runtime = build_eos_database_runtime(
        environ={"NEX_EOS_TEST_DATABASE_URL": DATABASE_URL},
        database_env="NEX_EOS_TEST_DATABASE_URL",
    )
    repository = SqlAlchemyEosProjectRepository(runtime.session_factory)
    _cleanup(runtime)
    try:
        repository.create_nvt_project(
            NvtProjectInput(TENANT, NVT_ID, "NVT-S13", "NVT S13")
        )
        repository.create_project(
            ProjectInput(TENANT, MOTHER_ID, "MOTHER", "Mother", nvt_project_id=NVT_ID)
        )
        repository.create_project(
            ProjectInput(TENANT, CHILD_ID, "CHILD", "Child", parent_project_id=MOTHER_ID)
        )
        repository.create_project(
            ProjectInput(TENANT, DEEP_ID, "DEEP", "Deep", parent_project_id=CHILD_ID)
        )

        projects = repository.list_projects_for_nvt(
            tenant_id=TENANT, nvt_project_id=NVT_ID
        )
        resolved = repository.resolve_nvt_project(
            tenant_id=TENANT, project_id=DEEP_ID
        )
        assert [item["hierarchy_depth"] for item in projects] == [1, 2, 3]
        assert resolved is not None and resolved["nvt_project_id"] == NVT_ID
    finally:
        _cleanup(runtime)
        with runtime.engine.connect() as connection:
            assert connection.execute(
                EOS_PROJECT_TABLE.select().where(
                    EOS_PROJECT_TABLE.c.tenant_id == TENANT
                )
            ).first() is None
        runtime.dispose()
