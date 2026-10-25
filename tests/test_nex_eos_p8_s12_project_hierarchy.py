from __future__ import annotations

from datetime import date, datetime

import pytest
from nex_eos import (
    EOS_METADATA,
    EOS_PROJECT_MAX_DEPTH,
    EOS_PROJECT_TABLE,
    EosProjectError,
    NvtProjectInput,
    NvtProjectUpdate,
    ProjectInput,
    SqlAlchemyEosProjectRepository,
)
from run_migrations import load_migrations
from sqlalchemy import create_engine, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

NVT_ID = "41000000-0000-4000-8000-000000000001"
INACTIVE_NVT_ID = "41000000-0000-4000-8000-000000000002"
MOTHER_ID = "42000000-0000-4000-8000-000000000001"
CHILD_ID = "42000000-0000-4000-8000-000000000002"
GRANDCHILD_ID = "42000000-0000-4000-8000-000000000003"
DEPTH_FOUR_ID = "42000000-0000-4000-8000-000000000004"


@pytest.fixture
def repository() -> SqlAlchemyEosProjectRepository:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    return SqlAlchemyEosProjectRepository(
        sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    )


def _seed_nvt(repository: SqlAlchemyEosProjectRepository, tenant="tenant-a"):
    return repository.create_nvt_project(
        NvtProjectInput(tenant, NVT_ID, "NVT-ONE", "NVT One")
    )


def _project(project_id, project_code, **overrides):
    values = {
        "tenant_id": "tenant-a",
        "project_id": project_id,
        "project_code": project_code,
        "name": project_code,
        "currency": "KRW",
    }
    values.update(overrides)
    return ProjectInput(**values)


def _seed_depth_three(repository: SqlAlchemyEosProjectRepository) -> None:
    _seed_nvt(repository)
    repository.create_project(
        _project(MOTHER_ID, "MOTHER", nvt_project_id=NVT_ID)
    )
    repository.create_project(
        _project(CHILD_ID, "CHILD", parent_project_id=MOTHER_ID)
    )
    repository.create_project(
        _project(GRANDCHILD_ID, "GRANDCHILD", parent_project_id=CHILD_ID)
    )


def test_s12_migration_declares_bounded_project_hierarchy() -> None:
    migration = next(
        item
        for item in load_migrations("nex-eos")
        if item.version == "2504_eos_project_hierarchy"
    )
    compact = " ".join(migration.sql.lower().split())

    assert "create table if not exists eos_project" in compact
    assert "foreign key (tenant_id, nvt_project_id)" in compact
    assert "foreign key (tenant_id, parent_project_id)" in compact
    assert "hierarchy_depth between 1 and 3" in compact
    assert "parent_project_id is null and nvt_project_id is not null" in compact
    assert "parent_project_id is not null and nvt_project_id is null" in compact


def test_depth_one_two_three_pass_and_depth_four_is_denied(
    repository: SqlAlchemyEosProjectRepository,
) -> None:
    _seed_depth_three(repository)

    assert repository.get_project(
        tenant_id="tenant-a", project_id=MOTHER_ID
    )["hierarchy_depth"] == 1
    assert repository.get_project(
        tenant_id="tenant-a", project_id=CHILD_ID
    )["hierarchy_depth"] == 2
    assert repository.get_project(
        tenant_id="tenant-a", project_id=GRANDCHILD_ID
    )["hierarchy_depth"] == EOS_PROJECT_MAX_DEPTH

    with pytest.raises(EosProjectError) as denied:
        repository.create_project(
            _project(
                DEPTH_FOUR_ID,
                "DEPTH-FOUR",
                parent_project_id=GRANDCHILD_ID,
            )
        )
    assert denied.value.error_code == "EOS_PROJECT_DEPTH_EXCEEDED"


def test_mother_and_child_lineage_shapes_fail_closed(
    repository: SqlAlchemyEosProjectRepository,
) -> None:
    _seed_nvt(repository)

    invalid = (
        _project(MOTHER_ID, "NO-NVT"),
        _project(
            MOTHER_ID,
            "SELF",
            parent_project_id=MOTHER_ID,
        ),
        _project(
            CHILD_ID,
            "BOTH",
            parent_project_id=MOTHER_ID,
            nvt_project_id=NVT_ID,
        ),
    )
    expected = (
        "EOS_PROJECT_INVALID",
        "EOS_PROJECT_CYCLE",
        "EOS_PROJECT_INVALID",
    )
    for value, error_code in zip(invalid, expected, strict=True):
        with pytest.raises(EosProjectError) as denied:
            repository.create_project(value)
        assert denied.value.error_code == error_code


def test_parent_and_nvt_are_tenant_scoped_and_active(
    repository: SqlAlchemyEosProjectRepository,
) -> None:
    _seed_nvt(repository)
    repository.create_project(
        _project(MOTHER_ID, "MOTHER", nvt_project_id=NVT_ID)
    )

    with pytest.raises(EosProjectError) as wrong_parent:
        repository.create_project(
            _project(
                CHILD_ID,
                "WRONG-TENANT",
                tenant_id="tenant-b",
                parent_project_id=MOTHER_ID,
            )
        )
    assert wrong_parent.value.error_code == "EOS_PROJECT_PARENT_NOT_FOUND"

    with pytest.raises(EosProjectError) as missing_nvt:
        repository.create_project(
            _project(
                CHILD_ID,
                "MISSING-NVT",
                nvt_project_id="41000000-0000-4000-8000-000000000002",
            )
        )
    assert missing_nvt.value.error_code == "EOS_NVT_PROJECT_NOT_FOUND"

    repository.create_nvt_project(
        NvtProjectInput("tenant-a", INACTIVE_NVT_ID, "NVT-INACTIVE", "Inactive NVT")
    )
    repository.update_nvt_project(
        NvtProjectUpdate("tenant-a", INACTIVE_NVT_ID, 1, status="INACTIVE")
    )
    with pytest.raises(EosProjectError) as inactive_nvt:
        repository.create_project(
            _project(CHILD_ID, "INACTIVE-NVT", nvt_project_id=INACTIVE_NVT_ID)
        )
    assert inactive_nvt.value.error_code == "EOS_NVT_PROJECT_NOT_ACTIVE"


def test_existing_corrupt_cycle_is_detected_before_child_insert() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    repository = SqlAlchemyEosProjectRepository(factory)
    _seed_depth_three(repository)
    with engine.begin() as connection:
        connection.execute(
            update(EOS_PROJECT_TABLE)
            .where(EOS_PROJECT_TABLE.c.project_id == MOTHER_ID)
            .values(parent_project_id=CHILD_ID, nvt_project_id=None)
        )

    with pytest.raises(EosProjectError) as cycle:
        repository.create_project(
            _project(DEPTH_FOUR_ID, "CYCLE-PROBE", parent_project_id=MOTHER_ID)
        )
    assert cycle.value.error_code == "EOS_PROJECT_CYCLE"


@pytest.mark.parametrize(
    "overrides",
    (
        {"project_id": "bad"},
        {"project_code": "bad code"},
        {"name": " "},
        {"status": "DELETED"},
        {"currency": "KR"},
        {"start_date": datetime(2026, 1, 1)},
        {"end_date": "2026-12-31"},
        {"start_date": date(2026, 2, 1), "end_date": date(2026, 1, 1)},
        {"version": 0},
        {"version": 2},
    ),
)
def test_project_input_validation_fails_closed(
    repository: SqlAlchemyEosProjectRepository,
    overrides,
) -> None:
    _seed_nvt(repository)
    values = {
        "project_id": MOTHER_ID,
        "project_code": "MOTHER",
        "nvt_project_id": NVT_ID,
    }
    values.update(overrides)
    with pytest.raises(EosProjectError) as error:
        repository.create_project(_project(**values))
    assert error.value.error_code == "EOS_PROJECT_INVALID"


def test_project_code_conflict_and_active_filter(
    repository: SqlAlchemyEosProjectRepository,
) -> None:
    _seed_nvt(repository)
    repository.create_project(
        _project(MOTHER_ID, "MOTHER", nvt_project_id=NVT_ID, status="INACTIVE")
    )
    assert repository.get_project(
        tenant_id="tenant-a", project_id=MOTHER_ID, active_only=True
    ) is None
    with pytest.raises(EosProjectError) as conflict:
        repository.create_project(
            _project(CHILD_ID, "MOTHER", nvt_project_id=NVT_ID)
        )
    assert conflict.value.error_code == "EOS_PROJECT_CONFLICT"


def test_project_database_errors_are_redacted() -> None:
    class BrokenSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, _statement):
            raise SQLAlchemyError("private project detail")

    repository = SqlAlchemyEosProjectRepository(lambda: BrokenSession())  # type: ignore[arg-type]
    with pytest.raises(EosProjectError) as error:
        repository.get_project(tenant_id="tenant-a", project_id=MOTHER_ID)
    assert error.value.error_code == "EOS_PROJECT_PERSISTENCE_FAILED"
    assert "private project detail" not in error.value.detail
