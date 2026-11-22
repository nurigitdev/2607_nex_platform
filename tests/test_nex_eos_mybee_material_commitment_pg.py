from __future__ import annotations

import os
import uuid
from datetime import timedelta

import psycopg
import pytest
import test_nex_eos_mybee_material_commitment as fixture
import test_nex_eos_mybee_voucher_candidate as posting
from nex_eos import (
    EOS_MATERIAL_ATTRIBUTION_TABLE,
    EOS_MATERIAL_COMMITMENT_TABLE,
    ProjectPnlRebuildRequest,
    SqlAlchemyEosProjectPnlProjectionSource,
    SqlAlchemyEosProjectPnlRepository,
    build_eos_project_pnl_projector,
)
from nex_runtime import psycopg_database_url
from psycopg import sql
from run_migrations import run_service_migrations
from sqlalchemy import create_engine, func, make_url, select, update
from sqlalchemy.exc import DBAPIError

DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
POSTGRES_SMOKE = os.getenv("NEX_EOS_MYBEE_S7_02D_POSTGRES_SMOKE") == "1"


@pytest.mark.skipif(
    not DATABASE_URL or not POSTGRES_SMOKE,
    reason="Protected W60 S7-02D EOS PostgreSQL smoke is disabled",
)
def test_actual_postgres_material_commitment_projection_and_immutability() -> None:
    schema_name = f"mybee_w60_s702d_{uuid.uuid4().hex}"
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
        assert "2546_eos_material_commitment" in migration.applied
        engine = create_engine(scoped_url, pool_pre_ping=True)
        _engine, sessions, service, journal_id = fixture._runtime_for_engine(engine)
        created = service.admit(fixture._input(journal_id))
        assert created["disposition"] == "CREATED"
        assert service.admit(fixture._input(journal_id))["disposition"] == "EXACT_REPLAY"

        source = SqlAlchemyEosProjectPnlProjectionSource(sessions)
        request = ProjectPnlRebuildRequest(
            posting.TENANT,
            posting.COMPANY_ID,
            posting.PROJECT_ID,
            posting.PROJECT_CODE,
            created["period_id"],
            1,
            "KRW",
            posting.NOW + timedelta(minutes=10),
            posting.NOW + timedelta(minutes=10),
        )
        projection = build_eos_project_pnl_projector(
            sessions, SqlAlchemyEosProjectPnlRepository(sessions)
        ).rebuild(request)
        assert projection["material_commitment_watermark"] is not None
        assert projection["posted_direct_cost"] == "0.0000"
        assert projection["posted_allocated_cost"] == "0.0000"
        assert projection["components"][0]["classification"] == "MATERIAL_COMMITTED"
        assert len(source.load(request).material_commitments) == 3

        with sessions() as session:
            assert session.execute(
                select(func.count()).select_from(EOS_MATERIAL_COMMITMENT_TABLE)
            ).scalar_one() == 1
            assert session.execute(
                select(func.count()).select_from(EOS_MATERIAL_ATTRIBUTION_TABLE)
            ).scalar_one() == 3
            with pytest.raises(DBAPIError):
                session.execute(
                    update(EOS_MATERIAL_COMMITMENT_TABLE)
                    .where(
                        EOS_MATERIAL_COMMITMENT_TABLE.c.commitment_id
                        == created["commitment_id"]
                    )
                    .values(reconciliation_state="BLOCKED")
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
