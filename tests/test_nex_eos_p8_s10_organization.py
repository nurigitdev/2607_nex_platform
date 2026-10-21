from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from nex_eos import (
    EOS_METADATA,
    EOS_ORG_UNIT_TABLE,
    EosOrganizationError,
    OrgUnitInput,
    PositionAssignmentInput,
    PositionInput,
    SqlAlchemyEosOrganizationRepository,
)
from nex_eos.app import create_eos_app
from run_migrations import load_migrations
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
COMPANY_ID = "10000000-0000-4000-8000-000000000001"
TEAM_ID = "10000000-0000-4000-8000-000000000002"
POSITION_ID = "20000000-0000-4000-8000-000000000001"
ASSIGNMENT_ID = "30000000-0000-4000-8000-000000000001"


@pytest.fixture
def repository() -> SqlAlchemyEosOrganizationRepository:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    return SqlAlchemyEosOrganizationRepository(
        sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    )


def _unit(**overrides):
    values = {
        "tenant_id": "tenant-a",
        "org_unit_id": COMPANY_ID,
        "org_unit_code": "COMPANY-A",
        "name": "Company A",
        "org_unit_type": "COMPANY",
        "effective_from": NOW,
    }
    values.update(overrides)
    return OrgUnitInput(**values)


def _position(**overrides):
    values = {
        "tenant_id": "tenant-a",
        "position_id": POSITION_ID,
        "position_type": "CEO",
        "org_unit_id": COMPANY_ID,
    }
    values.update(overrides)
    return PositionInput(**values)


def _assignment(**overrides):
    values = {
        "tenant_id": "tenant-a",
        "position_assignment_id": ASSIGNMENT_ID,
        "position_id": POSITION_ID,
        "principal_ref": {"type": "oa.user", "id": "employee-1001"},
        "effective_from": NOW,
    }
    values.update(overrides)
    return PositionAssignmentInput(**values)


def _seed_position(repository: SqlAlchemyEosOrganizationRepository) -> None:
    repository.create_org_unit(_unit())
    repository.create_position(_position())


def test_s10_migration_declares_bounded_organization_schema() -> None:
    migrations = load_migrations("nex-eos")
    migration = next(
        item for item in migrations if item.version == "2502_eos_organization_core"
    )
    compact = " ".join(migration.sql.lower().split())

    assert "create table if not exists eos_org_unit" in compact
    assert "create table if not exists eos_position" in compact
    assert "create table if not exists eos_position_assignment" in compact
    assert "where status = 'active'" in compact
    assert "credential" not in compact
    assert "secret" not in compact

    identifiers = [
        line.split()[-1]
        for line in migration.sql.splitlines()
        if "constraint " in line.lower() or "index if not exists " in line.lower()
    ]
    assert identifiers
    assert all(len(identifier) <= 63 for identifier in identifiers)


def test_effective_assignment_and_inactive_periods(
    repository: SqlAlchemyEosOrganizationRepository,
) -> None:
    _seed_position(repository)
    created = repository.assign_position(
        _assignment(effective_until=NOW + timedelta(days=30))
    )

    assert created["principal_ref_type"] == "oa.user"
    assert created["principal_id"] == "employee-1001"
    assert (
        repository.effective_assignment(
            tenant_id="tenant-a",
            position_id=POSITION_ID,
            effective_at=NOW + timedelta(days=1),
        )["position_assignment_id"]
        == ASSIGNMENT_ID
    )
    assert (
        repository.effective_assignment(
            tenant_id="tenant-a",
            position_id=POSITION_ID,
            effective_at=NOW - timedelta(seconds=1),
        )
        is None
    )
    assert (
        repository.effective_assignment(
            tenant_id="tenant-a",
            position_id=POSITION_ID,
            effective_at=NOW + timedelta(days=30),
        )
        is None
    )


def test_inactive_assignment_is_not_effective(
    repository: SqlAlchemyEosOrganizationRepository,
) -> None:
    _seed_position(repository)
    repository.assign_position(_assignment(status="INACTIVE"))

    assert (
        repository.effective_assignment(
            tenant_id="tenant-a", position_id=POSITION_ID, effective_at=NOW
        )
        is None
    )


def test_duplicate_active_assignment_is_denied(
    repository: SqlAlchemyEosOrganizationRepository,
) -> None:
    _seed_position(repository)
    repository.assign_position(_assignment())

    with pytest.raises(EosOrganizationError) as error:
        repository.assign_position(
            _assignment(
                position_assignment_id="30000000-0000-4000-8000-000000000002",
                principal_ref={"type": "oa.user", "id": "employee-1002"},
            )
        )

    assert error.value.error_code == "EOS_ACTIVE_POSITION_ASSIGNED"
    assert error.value.status_code == 409


def test_parent_and_position_refs_are_tenant_scoped(
    repository: SqlAlchemyEosOrganizationRepository,
) -> None:
    repository.create_org_unit(_unit())

    with pytest.raises(EosOrganizationError) as parent_error:
        repository.create_org_unit(
            _unit(
                tenant_id="tenant-b",
                org_unit_id=TEAM_ID,
                org_unit_code="TEAM-B",
                org_unit_type="TEAM",
                parent_org_unit_id=COMPANY_ID,
            )
        )
    assert parent_error.value.error_code == "EOS_ORG_PARENT_NOT_FOUND"

    with pytest.raises(EosOrganizationError) as position_error:
        repository.create_position(_position(tenant_id="tenant-b"))
    assert position_error.value.error_code == "EOS_ORG_UNIT_NOT_FOUND"

    repository.create_position(_position())
    with pytest.raises(EosOrganizationError) as assignment_error:
        repository.assign_position(_assignment(tenant_id="tenant-b"))
    assert assignment_error.value.error_code == "EOS_POSITION_NOT_FOUND"


@pytest.mark.parametrize(
    "principal_ref",
    (
        "employee-1001",
        {"type": "oa.user"},
        {"type": "oa.service", "id": "nex-ae-api"},
        {"type": "oa.user", "id": "bad id"},
        {"type": "oa.user", "id": "employee-1", "extra": "value"},
    ),
)
def test_assignment_requires_exact_oa_user_ref_shape(
    repository: SqlAlchemyEosOrganizationRepository,
    principal_ref,
) -> None:
    _seed_position(repository)

    with pytest.raises(EosOrganizationError) as error:
        repository.assign_position(_assignment(principal_ref=principal_ref))

    assert error.value.error_code == "EOS_ORGANIZATION_INVALID"
    assert error.value.status_code == 422


@pytest.mark.parametrize(
    "value",
    (
        _unit(org_unit_id="not-uuid"),
        _unit(org_unit_code="bad code"),
        _unit(name=" "),
        _unit(org_unit_type="DIVISION"),
        _unit(status="DELETED"),
        _unit(effective_from=NOW, effective_until=NOW),
        _unit(effective_from=datetime(2026, 1, 1)),
        _unit(version=0),
    ),
)
def test_org_unit_validation_fails_closed(
    repository: SqlAlchemyEosOrganizationRepository,
    value: OrgUnitInput,
) -> None:
    with pytest.raises(EosOrganizationError) as error:
        repository.create_org_unit(value)
    assert error.value.error_code == "EOS_ORGANIZATION_INVALID"


def test_conflicting_codes_and_position_types_are_denied(
    repository: SqlAlchemyEosOrganizationRepository,
) -> None:
    repository.create_org_unit(_unit())
    with pytest.raises(EosOrganizationError) as unit_conflict:
        repository.create_org_unit(
            _unit(org_unit_id=TEAM_ID, name="Duplicate code")
        )
    assert unit_conflict.value.error_code == "EOS_ORGANIZATION_CONFLICT"

    repository.create_position(_position())
    with pytest.raises(EosOrganizationError) as position_conflict:
        repository.create_position(
            _position(position_id="20000000-0000-4000-8000-000000000002")
        )
    assert position_conflict.value.error_code == "EOS_ORGANIZATION_CONFLICT"


def test_unexpected_database_failure_is_redacted() -> None:
    class BrokenSession:
        def execute(self, _statement):
            raise SQLAlchemyError("private database detail")

    with pytest.raises(EosOrganizationError) as error:
        SqlAlchemyEosOrganizationRepository._insert(
            BrokenSession(),  # type: ignore[arg-type]
            EOS_ORG_UNIT_TABLE,
            {},
        )

    assert error.value.error_code == "EOS_ORGANIZATION_PERSISTENCE_FAILED"
    assert error.value.status_code == 503
    assert "private database detail" not in error.value.detail


def test_app_wires_sql_organization_only_with_database_runtime() -> None:
    without_database = create_eos_app(
        environ={
            "NEX_EOS_SERVICE_ID": "nex-eos",
            "NEX_PROFILE": "test",
            "NEX_VERSION": "2.1.0-p8-s10",
            "NEX_BUILD_SHA": "p8s10test",
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
        }
    )
    assert without_database.state.eos_organization is None

    engine = create_engine("sqlite+pysqlite:///:memory:")
    from nex_eos import dependencies

    original = dependencies.build_eos_database_runtime
    try:
        class Runtime:
            session_factory = sessionmaker(bind=engine)

        dependencies.build_eos_database_runtime = lambda **_kwargs: Runtime()
        with_database = create_eos_app(
            environ={
                "NEX_EOS_SERVICE_ID": "nex-eos",
                "NEX_PROFILE": "test",
                "NEX_VERSION": "2.1.0-p8-s10",
                "NEX_BUILD_SHA": "p8s10test",
                "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
                "NEX_EOS_DATABASE_URL": "sqlite+pysqlite:///:memory:",
            }
        )
    finally:
        dependencies.build_eos_database_runtime = original
    assert isinstance(
        with_database.state.eos_organization,
        SqlAlchemyEosOrganizationRepository,
    )
