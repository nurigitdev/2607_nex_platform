from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from nex_eos import (
    EOS_METADATA,
    EOS_PROJECT_MEMBER_ROLES,
    EOS_PROJECT_MEMBER_STATUSES,
    EosProjectMembershipError,
    NvtProjectInput,
    ProjectInput,
    ProjectMembershipInput,
    SqlAlchemyEosProjectMembershipRepository,
    SqlAlchemyEosProjectRepository,
)
from run_migrations import load_migrations
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

NVT_ID = "81000000-0000-4000-8000-000000000001"
PROJECT_ID = "82000000-0000-4000-8000-000000000001"
MEMBERSHIP_ID = "83000000-0000-4000-8000-000000000001"


@pytest.fixture
def repositories():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    projects = SqlAlchemyEosProjectRepository(factory)
    memberships = SqlAlchemyEosProjectMembershipRepository(factory)
    projects.create_nvt_project(
        NvtProjectInput("tenant-a", NVT_ID, "NVT-A", "NVT A")
    )
    projects.create_project(
        ProjectInput(
            "tenant-a",
            PROJECT_ID,
            "PROJECT-A",
            "Project A",
            nvt_project_id=NVT_ID,
        )
    )
    return memberships


def _input(**overrides) -> ProjectMembershipInput:
    values = {
        "tenant_id": "tenant-a",
        "project_membership_id": MEMBERSHIP_ID,
        "project_id": PROJECT_ID,
        "subject_id": "subject-a",
        "member_role": "OWNER",
        "created_by_subject_id": "operator-a",
    }
    values.update(overrides)
    return ProjectMembershipInput(**values)


def test_s94_migration_declares_project_membership_foundation() -> None:
    migration = next(
        item
        for item in load_migrations("nex-eos")
        if item.version == "2514_eos_project_member"
    )
    compact = " ".join(migration.sql.lower().split())

    assert "create table if not exists eos_project_member" in compact
    assert "foreign key (tenant_id, project_id)" in compact
    assert "unique (tenant_id, project_id, subject_id)" in compact
    assert "status in ('active', 'removed')" in compact
    assert "member_role in ('owner', 'manager', 'member', 'viewer')" in compact
    assert "ix_eos_project_member_project" in compact
    assert "ix_eos_project_member_subject" in compact


def test_create_and_get_active_membership(repositories) -> None:
    created = repositories.create_membership(_input())
    loaded = repositories.get_membership(
        tenant_id="tenant-a", project_membership_id=MEMBERSHIP_ID
    )

    assert created["status"] == "ACTIVE"
    assert created["member_role"] == "OWNER"
    assert created["valid_to"] is None
    assert loaded is not None
    assert loaded["subject_id"] == "subject-a"
    assert loaded["version"] == 1


def test_removed_membership_requires_complete_terminal_shape(repositories) -> None:
    removed_at = datetime.now(UTC)
    created = repositories.create_membership(
        _input(
            status="removed",
            valid_from=removed_at - timedelta(days=1),
            valid_to=removed_at,
            removed_by_subject_id="operator-b",
        )
    )
    assert created["status"] == "REMOVED"
    assert created["removed_by_subject_id"] == "operator-b"


@pytest.mark.parametrize(
    "overrides",
    (
        {"project_membership_id": "bad"},
        {"project_id": "bad"},
        {"subject_id": " "},
        {"member_role": "ADMIN"},
        {"status": "DELETED"},
        {"version": 0},
        {"version": 2},
        {"valid_from": datetime(2026, 1, 1, tzinfo=UTC).replace(tzinfo=None)},
        {"valid_to": datetime.now(UTC)},
        {"removed_by_subject_id": "operator-b"},
        {"status": "REMOVED"},
        {
            "status": "REMOVED",
            "valid_from": datetime.now(UTC),
            "valid_to": datetime.now(UTC) - timedelta(days=1),
            "removed_by_subject_id": "operator-b",
        },
    ),
)
def test_membership_validation_fails_closed(repositories, overrides) -> None:
    with pytest.raises(EosProjectMembershipError) as denied:
        repositories.create_membership(_input(**overrides))
    assert denied.value.error_code == "EOS_PROJECT_MEMBERSHIP_INVALID"


def test_project_scope_and_subject_relationship_are_enforced(repositories) -> None:
    with pytest.raises(EosProjectMembershipError) as missing:
        repositories.create_membership(
            _input(project_id="82000000-0000-4000-8000-000000000099")
        )
    assert missing.value.error_code == "EOS_PROJECT_NOT_FOUND"

    repositories.create_membership(_input())
    with pytest.raises(EosProjectMembershipError) as duplicate:
        repositories.create_membership(
            _input(project_membership_id="83000000-0000-4000-8000-000000000002")
        )
    assert duplicate.value.error_code == "EOS_PROJECT_MEMBERSHIP_CONFLICT"

    assert repositories.get_membership(
        tenant_id="tenant-b", project_membership_id=MEMBERSHIP_ID
    ) is None


def test_declared_role_and_status_sets_are_frozen() -> None:
    assert EOS_PROJECT_MEMBER_ROLES == {"OWNER", "MANAGER", "MEMBER", "VIEWER"}
    assert EOS_PROJECT_MEMBER_STATUSES == {"ACTIVE", "REMOVED"}


def test_membership_database_errors_are_redacted() -> None:
    class BrokenSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, _statement):
            raise SQLAlchemyError("private membership detail")

    repository = SqlAlchemyEosProjectMembershipRepository(  # type: ignore[arg-type]
        lambda: BrokenSession()
    )
    with pytest.raises(EosProjectMembershipError) as error:
        repository.get_membership(
            tenant_id="tenant-a", project_membership_id=MEMBERSHIP_ID
        )
    assert error.value.error_code == "EOS_PROJECT_MEMBERSHIP_PERSISTENCE_FAILED"
    assert "private membership detail" not in error.value.detail


def test_membership_create_database_errors_are_redacted() -> None:
    class BrokenSession:
        def execute(self, _statement):
            raise SQLAlchemyError("private create detail")

        def rollback(self) -> None:
            pass

        def close(self) -> None:
            pass

    repository = SqlAlchemyEosProjectMembershipRepository(  # type: ignore[arg-type]
        lambda: BrokenSession()
    )
    with pytest.raises(EosProjectMembershipError) as error:
        repository.create_membership(_input())
    assert error.value.error_code == "EOS_PROJECT_MEMBERSHIP_PERSISTENCE_FAILED"
    assert "private create detail" not in error.value.detail
