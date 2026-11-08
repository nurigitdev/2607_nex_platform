from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from nex_eos import (
    EOS_METADATA,
    EOS_PROJECT_TABLE,
    EosProjectMembershipError,
    NvtProjectInput,
    ProjectInput,
    ProjectMembershipInput,
    SqlAlchemyEosProjectMembershipRepository,
    SqlAlchemyEosProjectRepository,
)
from sqlalchemy import create_engine, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

NVT_ID = "87000000-0000-4000-8000-000000000001"
PROJECT_ID = "88000000-0000-4000-8000-000000000001"
OWNER_A_ID = "89000000-0000-4000-8000-000000000001"
OWNER_B_ID = "89000000-0000-4000-8000-000000000002"


@pytest.fixture
def runtime():
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
        NvtProjectInput("tenant-a", NVT_ID, "NVT-S95", "NVT S95")
    )
    projects.create_project(
        ProjectInput(
            "tenant-a",
            PROJECT_ID,
            "PROJECT-S95",
            "Project S95",
            nvt_project_id=NVT_ID,
        )
    )
    return engine, memberships


def _member(
    *,
    membership_id: str = OWNER_A_ID,
    subject_id: str = "owner-a",
    role: str = "OWNER",
    tenant_id: str = "tenant-a",
    project_id: str = PROJECT_ID,
) -> ProjectMembershipInput:
    return ProjectMembershipInput(
        tenant_id,
        membership_id,
        project_id,
        subject_id,
        role,
        "operator-a",
    )


def test_add_replay_remove_replay_and_reactivation_are_stable(runtime) -> None:
    _engine, repository = runtime
    created = repository.add_membership(_member())
    replay = repository.add_membership(
        _member(membership_id="89000000-0000-4000-8000-000000000099")
    )
    assert replay["project_membership_id"] == created["project_membership_id"]
    assert replay["version"] == 1

    repository.add_membership(
        _member(membership_id=OWNER_B_ID, subject_id="owner-b")
    )
    removed = repository.remove_membership(
        tenant_id="tenant-a",
        project_id=PROJECT_ID,
        subject_id="owner-a",
        removed_by_subject_id="operator-b",
    )
    remove_replay = repository.remove_membership(
        tenant_id="tenant-a",
        project_id=PROJECT_ID,
        subject_id="owner-a",
        removed_by_subject_id="operator-c",
    )
    assert removed["status"] == "REMOVED"
    assert remove_replay["version"] == 2
    assert remove_replay["valid_to"].replace(tzinfo=UTC) == removed["valid_to"]

    reactivated = repository.add_membership(_member())
    active_replay = repository.add_membership(_member())
    assert reactivated["project_membership_id"] == OWNER_A_ID
    assert reactivated["status"] == "ACTIVE"
    assert reactivated["version"] == 3
    assert reactivated["valid_to"] is None
    assert active_replay["version"] == 3


def test_add_rejects_role_change_in_active_and_removed_states(runtime) -> None:
    _engine, repository = runtime
    repository.add_membership(_member())
    with pytest.raises(EosProjectMembershipError) as active_conflict:
        repository.add_membership(_member(role="MANAGER"))
    assert active_conflict.value.error_code == "EOS_PROJECT_MEMBERSHIP_ROLE_CONFLICT"

    repository.add_membership(
        _member(membership_id=OWNER_B_ID, subject_id="owner-b")
    )
    repository.remove_membership(
        tenant_id="tenant-a",
        project_id=PROJECT_ID,
        subject_id="owner-a",
        removed_by_subject_id="operator-b",
    )
    with pytest.raises(EosProjectMembershipError) as removed_conflict:
        repository.add_membership(_member(role="VIEWER"))
    assert removed_conflict.value.error_code == "EOS_PROJECT_MEMBERSHIP_ROLE_CONFLICT"


def test_add_maps_membership_identity_collision_to_conflict(runtime) -> None:
    _engine, repository = runtime
    repository.add_membership(_member())
    with pytest.raises(EosProjectMembershipError) as conflict:
        repository.add_membership(_member(subject_id="owner-b"))
    assert conflict.value.error_code == "EOS_PROJECT_MEMBERSHIP_CONFLICT"


def test_active_project_cannot_lose_last_owner(runtime) -> None:
    _engine, repository = runtime
    repository.add_membership(_member())
    with pytest.raises(EosProjectMembershipError) as denied:
        repository.remove_membership(
            tenant_id="tenant-a",
            project_id=PROJECT_ID,
            subject_id="owner-a",
            removed_by_subject_id="operator-b",
        )
    assert denied.value.error_code == "EOS_PROJECT_LAST_OWNER_REQUIRED"


def test_inactive_project_may_remove_last_owner(runtime) -> None:
    engine, repository = runtime
    repository.add_membership(_member())
    with engine.begin() as connection:
        connection.execute(
            update(EOS_PROJECT_TABLE)
            .where(
                EOS_PROJECT_TABLE.c.tenant_id == "tenant-a",
                EOS_PROJECT_TABLE.c.project_id == PROJECT_ID,
            )
            .values(status="INACTIVE")
        )
    removed = repository.remove_membership(
        tenant_id="tenant-a",
        project_id=PROJECT_ID,
        subject_id="owner-a",
        removed_by_subject_id="operator-b",
    )
    assert removed["status"] == "REMOVED"


def test_add_and_remove_fail_closed_for_missing_or_inactive_scope(runtime) -> None:
    engine, repository = runtime
    with pytest.raises(EosProjectMembershipError) as missing_project:
        repository.add_membership(
            _member(project_id="88000000-0000-4000-8000-000000000099")
        )
    assert missing_project.value.error_code == "EOS_PROJECT_NOT_FOUND"

    with pytest.raises(EosProjectMembershipError) as missing_member:
        repository.remove_membership(
            tenant_id="tenant-a",
            project_id=PROJECT_ID,
            subject_id="missing",
            removed_by_subject_id="operator-a",
        )
    assert missing_member.value.error_code == "EOS_PROJECT_MEMBERSHIP_NOT_FOUND"

    with engine.begin() as connection:
        connection.execute(
            update(EOS_PROJECT_TABLE)
            .where(
                EOS_PROJECT_TABLE.c.tenant_id == "tenant-a",
                EOS_PROJECT_TABLE.c.project_id == PROJECT_ID,
            )
            .values(status="INACTIVE")
        )
    with pytest.raises(EosProjectMembershipError) as inactive:
        repository.add_membership(_member())
    assert inactive.value.error_code == "EOS_PROJECT_INACTIVE"


@pytest.mark.parametrize(
    "call",
    (
        lambda repository: repository.add_membership(
            ProjectMembershipInput(
                "tenant-a",
                OWNER_A_ID,
                PROJECT_ID,
                "owner-a",
                "OWNER",
                "operator-a",
                status="REMOVED",
                valid_from=datetime.now(UTC) - timedelta(days=1),
                valid_to=datetime.now(UTC),
                removed_by_subject_id="operator-b",
            )
        ),
        lambda repository: repository.remove_membership(
            tenant_id="tenant-a",
            project_id=PROJECT_ID,
            subject_id="owner-a",
            removed_by_subject_id=" ",
        ),
        lambda repository: repository.remove_membership(
            tenant_id="tenant-a",
            project_id=PROJECT_ID,
            subject_id="owner-a",
            removed_by_subject_id="operator-a",
            removed_at=datetime.now(UTC).replace(tzinfo=None),
        ),
    ),
)
def test_lifecycle_inputs_fail_closed(runtime, call) -> None:
    _engine, repository = runtime
    with pytest.raises(EosProjectMembershipError) as denied:
        call(repository)
    assert denied.value.error_code == "EOS_PROJECT_MEMBERSHIP_INVALID"


def test_lifecycle_database_errors_are_redacted() -> None:
    class BrokenSession:
        def execute(self, _statement):
            raise SQLAlchemyError("private lifecycle detail")

        def rollback(self) -> None:
            pass

        def close(self) -> None:
            pass

    repository = SqlAlchemyEosProjectMembershipRepository(  # type: ignore[arg-type]
        lambda: BrokenSession()
    )
    with pytest.raises(EosProjectMembershipError) as add_error:
        repository.add_membership(_member())
    assert add_error.value.error_code == "EOS_PROJECT_MEMBERSHIP_PERSISTENCE_FAILED"
    assert "private lifecycle detail" not in add_error.value.detail

    with pytest.raises(EosProjectMembershipError) as remove_error:
        repository.remove_membership(
            tenant_id="tenant-a",
            project_id=PROJECT_ID,
            subject_id="owner-a",
            removed_by_subject_id="operator-a",
        )
    assert remove_error.value.error_code == "EOS_PROJECT_MEMBERSHIP_PERSISTENCE_FAILED"


@pytest.mark.parametrize("operation", ("add", "remove"))
def test_lifecycle_optimistic_update_conflicts_fail_closed(
    monkeypatch, operation
) -> None:
    class Result:
        rowcount = 0

    class StaleSession:
        def execute(self, _statement):
            return Result()

        def rollback(self) -> None:
            pass

        def close(self) -> None:
            pass

    repository = SqlAlchemyEosProjectMembershipRepository(  # type: ignore[arg-type]
        lambda: StaleSession()
    )
    monkeypatch.setattr(repository, "_locked_project_status", lambda *_args, **_kw: "ACTIVE")
    monkeypatch.setattr(
        repository,
        "_locked_subject_membership",
        lambda *_args, **_kw: {
            "tenant_id": "tenant-a",
            "project_membership_id": OWNER_A_ID,
            "project_id": PROJECT_ID,
            "subject_id": "owner-a",
            "member_role": "MEMBER",
            "status": "REMOVED" if operation == "add" else "ACTIVE",
            "valid_from": datetime.now(UTC) - timedelta(days=1),
            "valid_to": datetime.now(UTC) if operation == "add" else None,
            "version": 2,
            "created_by_subject_id": "operator-a",
            "removed_by_subject_id": "operator-b" if operation == "add" else None,
            "created_at": datetime.now(UTC) - timedelta(days=1),
            "updated_at": datetime.now(UTC),
        },
    )

    with pytest.raises(EosProjectMembershipError) as conflict:
        if operation == "add":
            repository.add_membership(_member(role="MEMBER"))
        else:
            repository.remove_membership(
                tenant_id="tenant-a",
                project_id=PROJECT_ID,
                subject_id="owner-a",
                removed_by_subject_id="operator-a",
            )
    assert conflict.value.error_code == "EOS_PROJECT_MEMBERSHIP_VERSION_CONFLICT"
