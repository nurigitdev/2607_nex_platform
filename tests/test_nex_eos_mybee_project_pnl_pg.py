from __future__ import annotations

import os
import uuid
from dataclasses import replace
from datetime import timedelta

import psycopg
import pytest
import test_nex_eos_mybee_project_pnl as fixture
from nex_eos import (
    EOS_ACCOUNT_TABLE,
    EOS_ACCOUNTING_PERIOD_TABLE,
    EOS_LEGAL_ENTITY_TABLE,
    EOS_NVT_PROJECT_TABLE,
    EOS_PROJECT_PNL_COMPONENT_TABLE,
    EOS_PROJECT_PNL_PROJECTION_TABLE,
    EOS_PROJECT_TABLE,
    ProjectPnlComponentDraft,
    SqlAlchemyEosProjectPnlRepository,
)
from nex_runtime import psycopg_database_url
from psycopg import sql
from run_migrations import run_service_migrations
from sqlalchemy import create_engine, func, make_url, select
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
POSTGRES_SMOKE = os.getenv("NEX_EOS_MYBEE_S7_02_POSTGRES_SMOKE") == "1"


def _seed_authorities(sessions) -> None:
    with sessions.begin() as session:
        for table, values in (
            (
                EOS_LEGAL_ENTITY_TABLE,
                {
                    "tenant_id": fixture.TENANT,
                    "company_id": fixture.COMPANY_ID,
                    "company_code": "W601",
                    "name": "W60 PostgreSQL Company",
                    "functional_currency": "KRW",
                    "presentation_currency": "KRW",
                    "business_timezone": "Asia/Seoul",
                    "status": "ACTIVE",
                    "effective_from": fixture.NOW.date(),
                    "version": 1,
                    "created_at": fixture.NOW,
                    "updated_at": fixture.NOW,
                },
            ),
            (
                EOS_NVT_PROJECT_TABLE,
                {
                    "tenant_id": fixture.TENANT,
                    "nvt_project_id": fixture.NVT_ID,
                    "nvt_project_code": "W601-NVT",
                    "name": "W60 PostgreSQL NVT",
                    "status": "ACTIVE",
                    "version": 1,
                    "created_at": fixture.NOW,
                    "updated_at": fixture.NOW,
                },
            ),
            (
                EOS_PROJECT_TABLE,
                {
                    "tenant_id": fixture.TENANT,
                    "project_id": fixture.PROJECT_ID,
                    "project_code": "W601D260001",
                    "project_request_code": "W601R260001",
                    "purpose_type": "D",
                    "origin": "APPROVED_APPLICATION",
                    "approval_evidence_ref": "eos.approval:w60-pg-project",
                    "approval_evidence_hash": fixture.HASH_A,
                    "project_owner_subject_id": "employee-owner",
                    "project_manager_subject_id": "employee-pm",
                    "agent_sync_state": "IN_SYNC",
                    "authorization_sync_state": "IN_SYNC",
                    "authorization_version": 1,
                    "name": "W60 PostgreSQL Project",
                    "parent_project_id": None,
                    "nvt_project_id": fixture.NVT_ID,
                    "hierarchy_depth": 1,
                    "status": "ACTIVE",
                    "start_date": fixture.NOW.date(),
                    "end_date": None,
                    "currency": "KRW",
                    "version": 1,
                    "created_at": fixture.NOW,
                    "updated_at": fixture.NOW,
                },
            ),
            (
                EOS_ACCOUNT_TABLE,
                {
                    "tenant_id": fixture.TENANT,
                    "account_id": fixture.ACCOUNT_ID,
                    "account_code": "5100",
                    "name": "Project expense",
                    "category": "EXPENSE",
                    "account_type": "PROJECT_EXPENSE",
                    "status": "ACTIVE",
                    "effective_from": fixture.NOW.date(),
                    "effective_until": None,
                    "version": 1,
                    "created_at": fixture.NOW,
                    "updated_at": fixture.NOW,
                },
            ),
            (
                EOS_ACCOUNTING_PERIOD_TABLE,
                {
                    "tenant_id": fixture.TENANT,
                    "company_id": fixture.COMPANY_ID,
                    "period_id": fixture.PERIOD_ID,
                    "fiscal_year": 2026,
                    "period_no": 11,
                    "start_date": fixture.NOW.date().replace(day=1),
                    "end_date": fixture.NOW.date().replace(day=30),
                    "state": "OPEN",
                    "version": 1,
                    "close_proof_ref": None,
                    "closed_at": None,
                    "ledger_cutoff_watermark": None,
                    "created_at": fixture.NOW,
                    "updated_at": fixture.NOW,
                },
            ),
        ):
            session.execute(table.insert().values(**values))


@pytest.mark.skipif(
    not DATABASE_URL or not POSTGRES_SMOKE,
    reason="Protected W60 S7-02 EOS PostgreSQL smoke is disabled",
)
def test_actual_postgres_projection_version_replay_and_zero_residue() -> None:
    schema_name = f"mybee_w60_s702_{uuid.uuid4().hex}"
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
        assert "2543_eos_project_pnl_projection" in migration.applied
        engine = create_engine(scoped_url, pool_pre_ping=True)
        sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        _seed_authorities(sessions)
        repository = SqlAlchemyEosProjectPnlRepository(sessions)

        first = repository.append(fixture._draft(), fixture._components())
        assert repository.append(fixture._draft(), fixture._components()) == first
        second = repository.append(
            replace(
                fixture._draft(),
                projection_id=str(uuid.uuid4()),
                projection_version=2,
                as_of=fixture.NOW + timedelta(minutes=1),
            ),
            fixture._components()
            + (
                ProjectPnlComponentDraft(
                    classification="MATERIAL_VARIANCE",
                    source_kind="MATERIAL",
                    functional_amount="-10.0000",
                    source_ref="eos.material-variance:w60:pg",
                    source_hash="sha256:" + "9" * 64,
                ),
            ),
        )
        assert second["projection_version"] == 2
        assert (
            repository.get(
                tenant_id=fixture.TENANT,
                company_id=fixture.COMPANY_ID,
                project_id=fixture.PROJECT_ID,
                period_id=fixture.PERIOD_ID,
            )
            == second
        )
        assert (
            repository.get(
                tenant_id=fixture.TENANT,
                company_id=fixture.COMPANY_ID,
                project_id=fixture.PROJECT_ID,
                period_id=fixture.PERIOD_ID,
                projection_version=1,
            )
            == first
        )
        with sessions() as session:
            assert (
                session.scalar(
                    select(func.count()).select_from(EOS_PROJECT_PNL_PROJECTION_TABLE)
                )
                == 2
            )
            assert (
                session.scalar(
                    select(func.count()).select_from(EOS_PROJECT_PNL_COMPONENT_TABLE)
                )
                == 15
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
            assert (
                connection.execute(
                    "SELECT 1 FROM pg_namespace WHERE nspname = %s", (schema_name,)
                ).fetchone()
                is None
            )
