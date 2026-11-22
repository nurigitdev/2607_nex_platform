from __future__ import annotations

import os
import uuid
from datetime import timedelta

import psycopg
import pytest
import test_nex_eos_mybee_material_commitment as commitment_fixture
import test_nex_eos_mybee_material_consumption as fixture
import test_nex_eos_mybee_voucher_candidate as posting
from nex_eos import (
    EOS_MATERIAL_CONSUMPTION_TABLE,
    EOS_MATERIAL_RELEASE_TABLE,
    EosMaterialConsumptionService,
    ProjectPnlRebuildRequest,
    SqlAlchemyEosMaterialConsumptionRepository,
    SqlAlchemyEosProjectPnlRepository,
    build_eos_project_pnl_projector,
)
from nex_runtime import psycopg_database_url
from psycopg import sql
from run_migrations import run_service_migrations
from sqlalchemy import create_engine, func, make_url, select, update
from sqlalchemy.exc import DBAPIError

DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
POSTGRES_SMOKE = os.getenv("NEX_EOS_MYBEE_S7_02E_POSTGRES_SMOKE") == "1"


@pytest.mark.skipif(
    not DATABASE_URL or not POSTGRES_SMOKE,
    reason="Protected W60 S7-02E EOS PostgreSQL smoke is disabled",
)
def test_actual_postgres_material_consumption_release_and_pnl_reconciliation() -> None:
    schema_name = f"mybee_w60_s702e_{uuid.uuid4().hex}"
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
        _engine, sessions, commitments, journal_id = (
            commitment_fixture._runtime_for_engine(engine)
        )
        commitment = commitments.admit(commitment_fixture._input(journal_id))
        period_id = fixture._seed_pool(sessions, journal_id)
        service = EosMaterialConsumptionService(
            SqlAlchemyEosMaterialConsumptionRepository(
                sessions, clock=lambda: posting.NOW + timedelta(minutes=8)
            )
        )
        created = service.reconcile(fixture._input(commitment))
        assert created["disposition"] == "CREATED"
        assert service.reconcile(fixture._input(commitment))["disposition"] == (
            "EXACT_REPLAY"
        )

        request = ProjectPnlRebuildRequest(
            posting.TENANT,
            posting.COMPANY_ID,
            posting.PROJECT_ID,
            posting.PROJECT_CODE,
            period_id,
            1,
            "KRW",
            posting.NOW + timedelta(minutes=10),
            posting.NOW + timedelta(minutes=10),
        )
        projection = build_eos_project_pnl_projector(
            sessions, SqlAlchemyEosProjectPnlRepository(sessions)
        ).rebuild(request)
        assert projection["posted_direct_cost"] == "1100.0000"
        assert [
            (item["classification"], item["functional_amount"])
            for item in projection["components"]
        ] == [
            ("MATERIAL_COMMITTED", "3000.0000"),
            ("POSTED_DIRECT_COST", "1100.0000"),
        ]

        with sessions() as session:
            assert session.scalar(
                select(func.count()).select_from(EOS_MATERIAL_CONSUMPTION_TABLE)
            ) == 1
            assert session.scalar(
                select(func.count()).select_from(EOS_MATERIAL_RELEASE_TABLE)
            ) == 1
            with pytest.raises(DBAPIError):
                session.execute(
                    update(EOS_MATERIAL_CONSUMPTION_TABLE)
                    .where(
                        EOS_MATERIAL_CONSUMPTION_TABLE.c.consumption_id
                        == created["consumption_id"]
                    )
                    .values(reconciliation_state="VERIFIED")
                )
                session.flush()
            session.rollback()
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
