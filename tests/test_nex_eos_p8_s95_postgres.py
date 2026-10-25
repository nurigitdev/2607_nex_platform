from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from nex_eos import (
    EOS_NVT_PROJECT_TABLE,
    EOS_PROJECT_MEMBER_TABLE,
    EOS_PROJECT_TABLE,
    EosProjectMembershipError,
    NvtProjectInput,
    ProjectInput,
    ProjectMembershipInput,
    SqlAlchemyEosProjectMembershipRepository,
    SqlAlchemyEosProjectRepository,
    build_eos_database_runtime,
)
from sqlalchemy import select, text

DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
SMOKE_ENABLED = os.getenv("NEX_EOS_P8_S95_POSTGRES_SMOKE") == "1"
TENANT_ID = "p8-s95-pg"
NVT_ID = "8a000000-0000-4000-8000-000000000001"
PROJECT_ID = "8b000000-0000-4000-8000-000000000001"

pytestmark = pytest.mark.skipif(
    not DATABASE_URL or not SMOKE_ENABLED,
    reason="Protected P8-S95 PostgreSQL smoke is disabled",
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


def _member(index: int, subject_id: str, role: str = "MEMBER") -> ProjectMembershipInput:
    return ProjectMembershipInput(
        TENANT_ID,
        f"8c000000-0000-4000-8000-{index:012d}",
        PROJECT_ID,
        subject_id,
        role,
        "operator-s95",
    )


def test_s95_postgres_serializes_add_and_last_owner_remove() -> None:
    runtime = build_eos_database_runtime(
        environ={"NEX_EOS_TEST_DATABASE_URL": DATABASE_URL},
        database_env="NEX_EOS_TEST_DATABASE_URL",
    )
    projects = SqlAlchemyEosProjectRepository(runtime.session_factory)
    repository = SqlAlchemyEosProjectMembershipRepository(runtime.session_factory)
    _cleanup(runtime)
    try:
        with runtime.engine.connect() as connection:
            assert tuple(
                connection.execute(text("SELECT current_database(), current_user")).one()
            ) == ("nex_eos_test", "nex_eos_user")

        projects.create_nvt_project(
            NvtProjectInput(TENANT_ID, NVT_ID, "NVT-S95", "NVT S95")
        )
        projects.create_project(
            ProjectInput(
                TENANT_ID,
                PROJECT_ID,
                "PROJECT-S95",
                "Project S95",
                nvt_project_id=NVT_ID,
            )
        )

        with ThreadPoolExecutor(max_workers=4) as executor:
            added = list(
                executor.map(
                    lambda index: repository.add_membership(
                        _member(index, "member-concurrent")
                    ),
                    range(1, 5),
                )
            )
        assert len({item["project_membership_id"] for item in added}) == 1

        repository.add_membership(_member(10, "owner-a", "OWNER"))
        repository.add_membership(_member(11, "owner-b", "OWNER"))

        def remove_owner(subject_id: str) -> str:
            try:
                result = repository.remove_membership(
                    tenant_id=TENANT_ID,
                    project_id=PROJECT_ID,
                    subject_id=subject_id,
                    removed_by_subject_id="operator-s95",
                )
                return str(result["status"])
            except EosProjectMembershipError as exc:
                return exc.error_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(remove_owner, ("owner-a", "owner-b")))
        assert sorted(outcomes) == ["EOS_PROJECT_LAST_OWNER_REQUIRED", "REMOVED"]

        with runtime.engine.connect() as connection:
            active_owners = connection.execute(
                select(EOS_PROJECT_MEMBER_TABLE.c.project_membership_id).where(
                    EOS_PROJECT_MEMBER_TABLE.c.tenant_id == TENANT_ID,
                    EOS_PROJECT_MEMBER_TABLE.c.project_id == PROJECT_ID,
                    EOS_PROJECT_MEMBER_TABLE.c.member_role == "OWNER",
                    EOS_PROJECT_MEMBER_TABLE.c.status == "ACTIVE",
                )
            ).all()
        assert len(active_owners) == 1
    finally:
        _cleanup(runtime)
        with runtime.engine.connect() as connection:
            residue = connection.execute(
                select(EOS_PROJECT_MEMBER_TABLE.c.project_membership_id).where(
                    EOS_PROJECT_MEMBER_TABLE.c.tenant_id == TENANT_ID
                )
            ).all()
        runtime.dispose()
    assert residue == []
