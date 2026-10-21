from __future__ import annotations

import os

import pytest
from nex_eos import (
    EOS_NVT_PROJECT_TABLE,
    EosProjectError,
    NvtProjectInput,
    NvtProjectUpdate,
    SqlAlchemyEosProjectRepository,
    build_eos_database_runtime,
)
from sqlalchemy import text

DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
SMOKE_ENABLED = os.getenv("NEX_EOS_P8_S11_POSTGRES_SMOKE") == "1"
TENANT_A = "p8-s11-pg-a"
TENANT_B = "p8-s11-pg-b"
NVT_ID = "d0000000-0000-4000-8000-000000000001"

pytestmark = pytest.mark.skipif(
    not DATABASE_URL or not SMOKE_ENABLED,
    reason="Protected P8-S11 PostgreSQL smoke is disabled",
)


def _cleanup(runtime) -> None:
    with runtime.engine.begin() as connection:
        connection.execute(
            EOS_NVT_PROJECT_TABLE.delete().where(
                EOS_NVT_PROJECT_TABLE.c.tenant_id.in_((TENANT_A, TENANT_B))
            )
        )


def test_s11_actual_postgres_nvt_identity_state_and_versioning() -> None:
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
                    "WHERE version = '2503_eos_nvt_project'"
                )
            ).scalar_one() == 1

        for tenant in (TENANT_A, TENANT_B):
            repository.create_nvt_project(
                NvtProjectInput(
                    tenant_id=tenant,
                    nvt_project_id=NVT_ID,
                    nvt_project_code="NVT-PG-GOLDEN-A",
                    name="PostgreSQL Golden A",
                )
            )

        updated = repository.update_nvt_project(
            NvtProjectUpdate(
                tenant_id=TENANT_A,
                nvt_project_id=NVT_ID,
                expected_version=1,
                status="INACTIVE",
            )
        )
        assert updated["version"] == 2
        assert repository.get_nvt_project(
            tenant_id=TENANT_A, nvt_project_id=NVT_ID, active_only=True
        ) is None
        assert repository.get_nvt_project(
            tenant_id=TENANT_B, nvt_project_id=NVT_ID, active_only=True
        )["version"] == 1

        with pytest.raises(EosProjectError) as stale:
            repository.update_nvt_project(
                NvtProjectUpdate(
                    tenant_id=TENANT_A,
                    nvt_project_id=NVT_ID,
                    expected_version=1,
                    name="stale update",
                )
            )
        assert stale.value.error_code == "EOS_NVT_PROJECT_VERSION_CONFLICT"
    finally:
        _cleanup(runtime)
        with runtime.engine.connect() as connection:
            residue = connection.execute(
                text(
                    "SELECT count(*) FROM eos_nvt_project "
                    "WHERE tenant_id IN (:tenant_a, :tenant_b)"
                ),
                {"tenant_a": TENANT_A, "tenant_b": TENANT_B},
            ).scalar_one()
        runtime.dispose()
    assert residue == 0
