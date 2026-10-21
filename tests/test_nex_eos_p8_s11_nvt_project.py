from __future__ import annotations

from pathlib import Path

import pytest
from nex_eos import (
    EOS_METADATA,
    EosProjectError,
    NvtProjectInput,
    NvtProjectUpdate,
    SqlAlchemyEosProjectRepository,
)
from run_migrations import load_migrations
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
NVT_ID = "40000000-0000-4000-8000-000000000001"


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


def _nvt(**overrides):
    values = {
        "tenant_id": "tenant-a",
        "nvt_project_id": NVT_ID,
        "nvt_project_code": "NVT-GOLDEN-A",
        "name": "Golden A",
    }
    values.update(overrides)
    return NvtProjectInput(**values)


def test_s11_migration_is_separate_from_ordinary_project() -> None:
    migration = next(
        item
        for item in load_migrations("nex-eos")
        if item.version == "2503_eos_nvt_project"
    )
    compact = " ".join(migration.sql.lower().split())

    assert "create table if not exists eos_nvt_project" in compact
    assert "unique (tenant_id, nvt_project_code)" in compact
    assert "create table if not exists eos_project" not in compact
    assert "token" not in compact


def test_nvt_code_is_unique_per_tenant_but_identity_is_tenant_scoped(
    repository: SqlAlchemyEosProjectRepository,
) -> None:
    first = repository.create_nvt_project(_nvt())
    second = repository.create_nvt_project(_nvt(tenant_id="tenant-b"))

    assert first["version"] == second["version"] == 1
    assert repository.get_nvt_project(
        tenant_id="tenant-a", nvt_project_id=NVT_ID
    )["tenant_id"] == "tenant-a"
    assert repository.get_nvt_project(
        tenant_id="tenant-b", nvt_project_id=NVT_ID
    )["tenant_id"] == "tenant-b"

    with pytest.raises(EosProjectError) as duplicate:
        repository.create_nvt_project(
            _nvt(nvt_project_id="40000000-0000-4000-8000-000000000002")
        )
    assert duplicate.value.error_code == "EOS_NVT_PROJECT_CONFLICT"


def test_active_filter_and_optimistic_versioning(
    repository: SqlAlchemyEosProjectRepository,
) -> None:
    repository.create_nvt_project(_nvt())
    updated = repository.update_nvt_project(
        NvtProjectUpdate(
            tenant_id="tenant-a",
            nvt_project_id=NVT_ID,
            expected_version=1,
            name="Golden A revised",
            status="INACTIVE",
        )
    )

    assert updated["name"] == "Golden A revised"
    assert updated["status"] == "INACTIVE"
    assert updated["version"] == 2
    assert repository.get_nvt_project(
        tenant_id="tenant-a", nvt_project_id=NVT_ID, active_only=True
    ) is None
    assert repository.get_nvt_project(
        tenant_id="tenant-a", nvt_project_id=NVT_ID
    )["version"] == 2

    with pytest.raises(EosProjectError) as stale:
        repository.update_nvt_project(
            NvtProjectUpdate(
                tenant_id="tenant-a",
                nvt_project_id=NVT_ID,
                expected_version=1,
                status="ACTIVE",
            )
        )
    assert stale.value.error_code == "EOS_NVT_PROJECT_VERSION_CONFLICT"


def test_update_is_tenant_isolated_and_not_found_is_explicit(
    repository: SqlAlchemyEosProjectRepository,
) -> None:
    repository.create_nvt_project(_nvt())

    with pytest.raises(EosProjectError) as missing:
        repository.update_nvt_project(
            NvtProjectUpdate(
                tenant_id="tenant-b",
                nvt_project_id=NVT_ID,
                expected_version=1,
                status="INACTIVE",
            )
        )
    assert missing.value.error_code == "EOS_NVT_PROJECT_NOT_FOUND"
    assert repository.get_nvt_project(
        tenant_id="tenant-b", nvt_project_id=NVT_ID
    ) is None


@pytest.mark.parametrize(
    "value",
    (
        _nvt(tenant_id="bad tenant"),
        _nvt(nvt_project_id="not-uuid"),
        _nvt(nvt_project_code="bad code"),
        _nvt(name=" "),
        _nvt(status="DELETED"),
        _nvt(version=0),
        _nvt(version=2),
    ),
)
def test_create_validation_fails_closed(
    repository: SqlAlchemyEosProjectRepository,
    value: NvtProjectInput,
) -> None:
    with pytest.raises(EosProjectError) as error:
        repository.create_nvt_project(value)
    assert error.value.error_code == "EOS_PROJECT_INVALID"


def test_update_requires_a_change_and_positive_expected_version(
    repository: SqlAlchemyEosProjectRepository,
) -> None:
    repository.create_nvt_project(_nvt())
    for update in (
        NvtProjectUpdate("tenant-a", NVT_ID, 1),
        NvtProjectUpdate("tenant-a", NVT_ID, 0, status="ACTIVE"),
        NvtProjectUpdate("tenant-a", NVT_ID, 1, name=" "),
        NvtProjectUpdate("tenant-a", NVT_ID, 1, status="UNKNOWN"),
    ):
        with pytest.raises(EosProjectError) as error:
            repository.update_nvt_project(update)
        assert error.value.error_code == "EOS_PROJECT_INVALID"


def test_database_errors_are_redacted() -> None:
    class BrokenSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, _statement):
            raise SQLAlchemyError("private detail")

    repository = SqlAlchemyEosProjectRepository(lambda: BrokenSession())  # type: ignore[arg-type]
    with pytest.raises(EosProjectError) as error:
        repository.get_nvt_project(tenant_id="tenant-a", nvt_project_id=NVT_ID)

    assert error.value.error_code == "EOS_PROJECT_PERSISTENCE_FAILED"
    assert "private detail" not in error.value.detail


def test_create_and_update_database_failures_are_redacted() -> None:
    class BrokenSession:
        def execute(self, _statement):
            raise SQLAlchemyError("private write detail")

        def commit(self):
            return None

        def rollback(self):
            return None

        def close(self):
            return None

    repository = SqlAlchemyEosProjectRepository(lambda: BrokenSession())  # type: ignore[arg-type]

    with pytest.raises(EosProjectError) as create_error:
        repository.create_nvt_project(_nvt())
    assert create_error.value.error_code == "EOS_PROJECT_PERSISTENCE_FAILED"
    assert "private write detail" not in create_error.value.detail

    with pytest.raises(EosProjectError) as update_error:
        repository.update_nvt_project(
            NvtProjectUpdate(
                tenant_id="tenant-a",
                nvt_project_id=NVT_ID,
                expected_version=1,
                status="INACTIVE",
            )
        )
    assert update_error.value.error_code == "EOS_PROJECT_PERSISTENCE_FAILED"
    assert "private write detail" not in update_error.value.detail
