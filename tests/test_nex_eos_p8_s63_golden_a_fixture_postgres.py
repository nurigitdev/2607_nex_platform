from __future__ import annotations

import os
from pathlib import Path

import pytest
from nex_eos import (
    SqlAlchemyEosAccountRepository,
    SqlAlchemyEosOrganizationRepository,
    SqlAlchemyEosProjectRepository,
)
from nex_oa.memberships import SqlAlchemyOaTenantMembershipRegistry
from nex_oa.subjects import SqlAlchemyOaSubjectRegistry
from p8_golden_a_fixture import (
    golden_a_residue_counts,
    load_golden_a_fixture,
    reset_golden_a_fixture,
    seed_golden_a_fixture,
)
from run_migrations import load_migrations, run_service_migrations
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[1]
OA_DATABASE_URL = os.getenv("NEX_OA_TEST_DATABASE_URL", "")
EOS_DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
SMOKE_ENABLED = os.getenv("NEX_P8_S63_GOLDEN_A_POSTGRES_GATE") == "1"

pytestmark = pytest.mark.skipif(
    not OA_DATABASE_URL or not EOS_DATABASE_URL or not SMOKE_ENABLED,
    reason="Protected P8-S63 Golden A PostgreSQL gate is disabled",
)


def _assert_database_target(database_url: str, *, user: str, database: str) -> None:
    target = make_url(database_url)
    assert target.username == user
    assert target.database == database


def _assert_current_migrations(engine, service_id: str) -> None:
    expected = {migration.version for migration in load_migrations(service_id)}
    with engine.connect() as connection:
        actual = set(
            connection.execute(text("SELECT version FROM schema_migrations")).scalars()
        )
    assert expected <= actual


def test_s63_actual_postgres_fixture_is_resettable_and_deterministic() -> None:
    _assert_database_target(
        OA_DATABASE_URL,
        user="nex_oa_user",
        database="nex_oa_test",
    )
    _assert_database_target(
        EOS_DATABASE_URL,
        user="nex_eos_user",
        database="nex_eos_test",
    )
    run_service_migrations("nex-oa", database_url=OA_DATABASE_URL, profile="test")
    run_service_migrations("nex-eos", database_url=EOS_DATABASE_URL, profile="test")

    oa_engine = create_engine(OA_DATABASE_URL, poolclass=NullPool)
    eos_engine = create_engine(EOS_DATABASE_URL, poolclass=NullPool)
    oa_factory = sessionmaker(bind=oa_engine, expire_on_commit=False)
    eos_factory = sessionmaker(bind=eos_engine, expire_on_commit=False)
    fixture = load_golden_a_fixture()
    subjects = SqlAlchemyOaSubjectRegistry(oa_factory)
    memberships = SqlAlchemyOaTenantMembershipRegistry(
        oa_factory,
        subject_registry=subjects,
    )
    organization = SqlAlchemyEosOrganizationRepository(eos_factory)
    projects = SqlAlchemyEosProjectRepository(eos_factory)
    accounts = SqlAlchemyEosAccountRepository(eos_factory)

    reset_golden_a_fixture(fixture, oa_engine=oa_engine, eos_engine=eos_engine)
    try:
        _assert_current_migrations(oa_engine, "nex-oa")
        _assert_current_migrations(eos_engine, "nex-eos")
        with oa_engine.connect() as connection:
            assert tuple(
                connection.execute(
                    text("SELECT current_database(), current_user")
                ).one()
            ) == ("nex_oa_test", "nex_oa_user")
        with eos_engine.connect() as connection:
            assert tuple(
                connection.execute(
                    text("SELECT current_database(), current_user")
                ).one()
            ) == ("nex_eos_test", "nex_eos_user")

        first = seed_golden_a_fixture(
            fixture,
            memberships=memberships,
            organization=organization,
            projects=projects,
            accounts=accounts,
        )
        seeded_counts = golden_a_residue_counts(
            fixture,
            oa_engine=oa_engine,
            eos_engine=eos_engine,
        )
        assert seeded_counts["nex-oa"] == {
            "oa_tenants": 1,
            "oa_subjects": 2,
            "oa_tenant_memberships": 2,
        }
        assert seeded_counts["nex-eos"] == {
            "eos_nvt_project": 1,
            "eos_project": 2,
            "eos_account": 2,
            "eos_org_unit": 4,
            "eos_position": 1,
            "eos_position_assignment": 1,
        }

        reset_counts = reset_golden_a_fixture(
            fixture,
            oa_engine=oa_engine,
            eos_engine=eos_engine,
        )
        assert all(
            value == 0
            for service in reset_counts.values()
            for value in service.values()
        )
        second = seed_golden_a_fixture(
            fixture,
            memberships=memberships,
            organization=organization,
            projects=projects,
            accounts=accounts,
        )
        assert second == first
    finally:
        residue = reset_golden_a_fixture(
            fixture,
            oa_engine=oa_engine,
            eos_engine=eos_engine,
        )
        oa_engine.dispose()
        eos_engine.dispose()

    assert all(value == 0 for service in residue.values() for value in service.values())
