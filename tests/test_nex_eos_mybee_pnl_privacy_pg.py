from __future__ import annotations

import os
import uuid
from copy import deepcopy
from types import SimpleNamespace

import psycopg
import pytest
import test_nex_eos_mybee_project_pnl as fixture
import test_nex_eos_mybee_project_pnl_pg as pg_fixture
from nex_eos import (
    EOS_PNL_PRIVACY_GUARD_TABLE,
    EosPnlPrivacyError,
    EosProjectPnlPrivacyGuard,
    EosProjectPnlQueryError,
    EosProjectPnlQueryService,
    PnlPrivacyPopulationFact,
    SqlAlchemyEosPnlPrivacyRepository,
    SqlAlchemyEosProjectPnlRepository,
)
from nex_runtime import psycopg_database_url
from psycopg import sql
from run_migrations import run_service_migrations
from sqlalchemy import create_engine, func, make_url, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
POSTGRES_SMOKE = os.getenv("NEX_EOS_MYBEE_S7_03_POSTGRES_SMOKE") == "1"


class Authorizer:
    def authorize(self, **_kwargs):
        return SimpleNamespace(
            decision_ref="oa-decision:s7-03-pg",
            project_code="W601D260001",
            project_role="MANAGER",
            project_status="ACTIVE",
            source_version=1,
            projection_event_hash="sha256:" + "1" * 64,
            authorization_revision_hash="sha256:" + "2" * 64,
            decided_at="2026-11-15T00:00:00+00:00",
        )


class ProtectedRepository:
    def __init__(self, persistent: SqlAlchemyEosPnlPrivacyRepository) -> None:
        self._persistent = persistent

    def population_facts(self, **_kwargs):
        return (
            PnlPrivacyPopulationFact(
                snapshot_id="10000000-0000-0000-0000-000000000001",
                line_no=1,
                population_count=5,
                minimum_population=3,
                ordinary_view_suppressed=False,
                line_hash="sha256:" + "3" * 64,
            ),
        )

    def admit_guard(self, value):
        return self._persistent.admit_guard(value)


@pytest.mark.skipif(
    not DATABASE_URL or not POSTGRES_SMOKE,
    reason="Protected W60 S7-03 EOS PostgreSQL smoke is disabled",
)
def test_actual_postgres_privacy_guard_replay_and_zero_residue() -> None:
    schema_name = f"mybee_w60_s703_{uuid.uuid4().hex}"
    psycopg_url = psycopg_database_url(DATABASE_URL)
    with psycopg.connect(psycopg_url, autocommit=True) as connection:
        assert connection.execute(
            "SELECT current_database(), current_user"
        ).fetchone() == ("nex_eos_test", "nex_eos_user")
        connection.execute(
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name))
        )
    scoped_url = (
        make_url(DATABASE_URL)
        .update_query_dict({"options": f"-csearch_path={schema_name}"})
        .render_as_string(hide_password=False)
    )
    engine = None
    try:
        migration = run_service_migrations(
            "nex-eos", database_url=scoped_url, profile="test"
        )
        assert "2548_eos_pnl_privacy_guard" in migration.applied
        engine = create_engine(scoped_url, pool_pre_ping=True)
        sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        pg_fixture._seed_authorities(sessions)
        projection_repository = SqlAlchemyEosProjectPnlRepository(sessions)
        projection = projection_repository.append(
            fixture._draft(), fixture._components()
        )
        persistent = SqlAlchemyEosPnlPrivacyRepository(sessions)
        guard = EosProjectPnlPrivacyGuard(ProtectedRepository(persistent))
        service = EosProjectPnlQueryService(
            repository=projection_repository,
            project_authorizer=Authorizer(),
            privacy_guard=guard,
        )
        query = {
            "tenant_id": fixture.TENANT,
            "company_id": fixture.COMPANY_ID,
            "project_id": fixture.PROJECT_ID,
            "period_id": fixture.PERIOD_ID,
            "requester_subject_id": "employee-pnl-reader",
            "correlation_id": "w60-s7-03-pg",
        }
        assert service.get(**query) == projection
        assert service.get(**query) == projection
        with pytest.raises(EosProjectPnlQueryError) as historical:
            service.get(**query, projection_version=1)
        assert historical.value.error_code == "PAYROLL_PRIVACY_DENIED"

        changed = deepcopy(projection)
        changed["components"][2]["source_hash"] = "sha256:" + "9" * 64
        changed["components"][2]["component_hash"] = "sha256:" + "8" * 64
        with pytest.raises(EosPnlPrivacyError) as changed_guard:
            guard.protect(
                changed,
                subject_id="employee-pnl-reader",
                authorization=Authorizer().authorize(),
                historical_version_requested=False,
            )
        assert changed_guard.value.reason_code == "PAYROLL_FINGERPRINT_CHANGED"

        with sessions() as session:
            assert (
                session.execute(
                    select(func.count()).select_from(EOS_PNL_PRIVACY_GUARD_TABLE)
                ).scalar_one()
                == 1
            )
            assert (
                session.execute(
                    select(func.count())
                    .select_from(EOS_PNL_PRIVACY_GUARD_TABLE)
                    .where(EOS_PNL_PRIVACY_GUARD_TABLE.c.tenant_id == "OTHER")
                ).scalar_one()
                == 0
            )
        with pytest.raises(DBAPIError), sessions.begin() as session:
            session.execute(
                update(EOS_PNL_PRIVACY_GUARD_TABLE).values(population_floor=6)
            )
    finally:
        if engine is not None:
            engine.dispose()
        with psycopg.connect(psycopg_url, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema_name)
                )
            )
            assert connection.execute(
                "SELECT to_regnamespace(%s)", (schema_name,)
            ).fetchone() == (None,)
