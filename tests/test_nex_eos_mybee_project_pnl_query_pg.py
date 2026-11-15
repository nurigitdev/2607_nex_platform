from __future__ import annotations

import os
import uuid
from types import SimpleNamespace

import psycopg
import pytest
import test_nex_eos_mybee_project_pnl as fixture
import test_nex_eos_mybee_project_pnl_pg as pg_fixture
from mybee_ax.integrations.nex_pnl_client import admit_project_pnl_projection
from nex_eos import EosProjectPnlQueryService, SqlAlchemyEosProjectPnlRepository
from nex_runtime import psycopg_database_url
from psycopg import sql
from run_migrations import run_service_migrations
from sqlalchemy import create_engine, make_url
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
POSTGRES_SMOKE = os.getenv("NEX_EOS_MYBEE_S7_02F_POSTGRES_SMOKE") == "1"


class Authorizer:
    def authorize(self, **_kwargs):
        return SimpleNamespace(project_code="W601D260001")


@pytest.mark.skipif(
    not DATABASE_URL or not POSTGRES_SMOKE,
    reason="Protected W60 S7-02F EOS PostgreSQL smoke is disabled",
)
def test_actual_postgres_authorized_query_and_mybee_consumer_zero_residue() -> None:
    schema_name = f"mybee_w60_s702f_{uuid.uuid4().hex}"
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
        assert "2547_eos_material_consumption" in migration.applied
        engine = create_engine(scoped_url, pool_pre_ping=True)
        sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        pg_fixture._seed_authorities(sessions)
        repository = SqlAlchemyEosProjectPnlRepository(sessions)
        persisted = repository.append(fixture._draft(), fixture._components())
        service = EosProjectPnlQueryService(
            repository=repository,
            project_authorizer=Authorizer(),
        )
        queried = service.get(
            tenant_id=fixture.TENANT,
            company_id=fixture.COMPANY_ID,
            project_id=fixture.PROJECT_ID,
            period_id=fixture.PERIOD_ID,
            requester_subject_id="employee-pnl-reader",
            correlation_id="w60-s7-02f-pg",
        )
        assert queried == persisted
        admitted = admit_project_pnl_projection(
            queried,
            tenant_id=fixture.TENANT,
            company_id=fixture.COMPANY_ID,
            project_id=fixture.PROJECT_ID,
            project_code="W601D260001",
            period_id=fixture.PERIOD_ID,
        )
        assert admitted["posted_operating_result"] == "600.0000"
        assert admitted["components"][2]["data_classification"] == ("PAYROLL_SENSITIVE")
        assert not any(
            forbidden in component
            for component in admitted["components"]
            for forbidden in ("employee_id", "salary", "payroll_amount")
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
