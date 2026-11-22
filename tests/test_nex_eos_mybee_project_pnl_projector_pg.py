from __future__ import annotations

import os
import uuid
from datetime import date, timedelta
from decimal import Decimal

import psycopg
import pytest
import test_nex_eos_mybee_allocation_pg as allocation_fixture
import test_nex_eos_mybee_cost_pool as source_fixture
from nex_eos import (
    EOS_PROJECT_COMPANY_BINDING_TABLE,
    EosCostAllocationService,
    EosCostSourcePoolService,
    EosProjectPnlProjector,
    ProjectPnlRebuildRequest,
    SqlAlchemyEosBusinessTransactionCoordinator,
    SqlAlchemyEosCostSourceFactsSource,
    SqlAlchemyEosCostSourcePoolRepository,
    SqlAlchemyEosProjectPnlProjectionSource,
    SqlAlchemyEosProjectPnlRepository,
)
from nex_runtime import psycopg_database_url
from psycopg import sql
from run_migrations import run_service_migrations
from sqlalchemy import create_engine, make_url

DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
POSTGRES_SMOKE = os.getenv("NEX_EOS_MYBEE_S7_02A_POSTGRES_SMOKE") == "1"


@pytest.mark.skipif(
    not DATABASE_URL or not POSTGRES_SMOKE,
    reason="Protected W60 S7-02A EOS PostgreSQL smoke is disabled",
)
def test_actual_postgres_direct_allocation_projector_rebuild_and_replay() -> None:
    schema_name = f"mybee_w60_s702a_{uuid.uuid4().hex}"
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
        posting = source_fixture.posting_fixture
        _engine, sessions, candidates, command, _authorization = posting._runtime(
            engine=engine
        )
        with sessions.begin() as session:
            session.execute(
                EOS_PROJECT_COMPANY_BINDING_TABLE.insert().values(
                    tenant_id=posting.TENANT,
                    binding_id=str(uuid.uuid4()),
                    project_id=posting.PROJECT_ID,
                    company_id=posting.COMPANY_ID,
                    valid_from=date(2026, 1, 1),
                    valid_until=None,
                    approved_proof_hash=posting.PROOF_HASH,
                    state="APPROVED",
                    version=1,
                    created_at=posting.NOW,
                    updated_at=posting.NOW,
                )
            )
        command.execute(posting._payload(), caller=posting.CALLER)
        posting_service, post_payload = posting._prepare_atomic_posting(
            sessions, candidates
        )
        committed = posting_service.execute(posting.CANDIDATE_ID, post_payload)
        source_service = EosCostSourcePoolService(
            source=SqlAlchemyEosCostSourceFactsSource(sessions),
            repository=SqlAlchemyEosCostSourcePoolRepository(sessions),
            clock=lambda: posting.NOW,
        )
        source_pool = source_service.admit(
            tenant_id=posting.TENANT,
            company_id=posting.COMPANY_ID,
            journal_id=committed["result"]["journal_id"],
            journal_line_no=1,
            payload=source_fixture._payload(
                source_kind="SERVICE",
                allocation_mode="MANAGEMENT_ALLOCATION",
            ),
        )
        allocation_fixture._seed_plan_and_second_project(
            sessions, source_kind="SERVICE"
        )
        allocation = EosCostAllocationService(
            session_factory=sessions,
            coordinator=SqlAlchemyEosBusinessTransactionCoordinator(
                sessions,
                id_factory=lambda: str(uuid.uuid4()),
                clock=lambda: posting.NOW,
            ),
            clock=lambda: posting.NOW,
        )
        allocation_result = allocation.run(
            tenant_id=posting.TENANT,
            company_id=posting.COMPANY_ID,
            payload=allocation_fixture._allocation_payload(
                pool_id=source_pool["pool_id"],
                period_id="32000000-0000-4000-8000-000000000021",
            ),
        )
        assert (
            allocation_result["allocated_total"]
            == source_pool["eligible_amount_functional"]
        )

        projector = EosProjectPnlProjector(
            source=SqlAlchemyEosProjectPnlProjectionSource(sessions),
            sink=SqlAlchemyEosProjectPnlRepository(sessions),
        )
        request = ProjectPnlRebuildRequest(
            tenant_id=posting.TENANT,
            company_id=posting.COMPANY_ID,
            project_id=posting.PROJECT_ID,
            project_code=posting.PROJECT_CODE,
            period_id="32000000-0000-4000-8000-000000000021",
            projection_version=1,
            functional_currency="KRW",
            as_of=posting.NOW + timedelta(minutes=1),
            evaluated_at=posting.NOW + timedelta(minutes=1),
        )
        created = projector.rebuild(request)
        replay = projector.rebuild(request)
        expected = (
            Decimal(source_pool["eligible_amount_functional"]) / Decimal(2)
        ).quantize(Decimal("0.0001"))
        assert replay == created
        assert created["posted_allocated_cost"] == format(expected, ".4f")
        assert created["operating_unallocated_cost"] == "0.0000"
        assert created["reconciliation_status"] == "VERIFIED"
        assert created["freshness_status"] == "CURRENT"
        assert created["posting_watermark"].startswith("sha256:")
        assert created["allocation_watermark"].startswith("sha256:")
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
