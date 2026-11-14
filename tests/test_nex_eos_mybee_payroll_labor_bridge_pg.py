from __future__ import annotations

import os
import uuid
from datetime import date, timedelta
from decimal import Decimal

import psycopg
import pytest
import test_nex_eos_mybee_cost_pool as source_fixture
from nex_eos import (
    EOS_LABOR_EFFORT_LINE_TABLE,
    EOS_LABOR_EFFORT_SNAPSHOT_TABLE,
    EOS_PAYROLL_POST_EVIDENCE_TABLE,
    EOS_PROJECT_COMPANY_BINDING_TABLE,
    EosCostSourcePoolService,
    EosPayrollLaborBridgeService,
    LaborEffortLineInput,
    LaborEffortSnapshotInput,
    PayrollPostingEvidenceInput,
    SqlAlchemyEosCostSourceFactsSource,
    SqlAlchemyEosCostSourcePoolRepository,
    SqlAlchemyEosPayrollLaborBridgeRepository,
)
from nex_runtime import psycopg_database_url
from psycopg import sql
from run_migrations import run_service_migrations
from sqlalchemy import create_engine, func, make_url, select, update
from sqlalchemy.exc import DBAPIError

DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
POSTGRES_SMOKE = os.getenv("NEX_EOS_MYBEE_S7_02B_POSTGRES_SMOKE") == "1"


@pytest.mark.skipif(
    not DATABASE_URL or not POSTGRES_SMOKE,
    reason="Protected W60 S7-02B EOS PostgreSQL smoke is disabled",
)
def test_actual_postgres_payroll_labor_bridge_replay_privacy_and_immutability() -> None:
    schema_name = f"mybee_w60_s702b_{uuid.uuid4().hex}"
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
        assert "2544_eos_payroll_labor_bridge" in migration.applied
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
                source_kind="PAYROLL",
                allocation_mode="MANAGEMENT_ALLOCATION",
            ),
        )
        bridge = EosPayrollLaborBridgeService(
            SqlAlchemyEosPayrollLaborBridgeRepository(sessions),
            clock=lambda: posting.NOW + timedelta(minutes=2),
        )
        payroll_input = PayrollPostingEvidenceInput(
            tenant_id=posting.TENANT,
            company_id=posting.COMPANY_ID,
            payroll_run_id="payroll-run:protected:2026-11",
            payroll_period_start=date(2026, 11, 1),
            payroll_period_end=date(2026, 11, 30),
            revision=1,
            pool_id=source_pool["pool_id"],
            payroll_component_class="BASE_SALARY",
            payroll_source_ref="payroll-sor:protected:2026-11",
            payroll_source_hash=posting.PROOF_HASH,
            approval_ref="payroll-approval:protected:2026-11",
            approval_hash=posting.PROOF_HASH,
            organization_ref="org:protected-engineering",
        )
        payroll = bridge.admit_payroll_posting(payroll_input)
        assert (
            bridge.admit_payroll_posting(payroll_input)["idempotency_disposition"]
            == "EXACT_REPLAY"
        )
        assert payroll["journal_id"] == committed["result"]["journal_id"]
        assert (
            payroll["eligible_amount_functional"]
            == source_pool["eligible_amount_functional"]
        )

        effort_input = LaborEffortSnapshotInput(
            tenant_id=posting.TENANT,
            company_id=posting.COMPANY_ID,
            effort_period_start=date(2026, 11, 1),
            effort_period_end=date(2026, 11, 30),
            revision=1,
            basis_kind="ACTUAL_APPROVED",
            effort_unit="MAN_DAY",
            source_ref="labor-sor:protected:2026-11",
            source_hash=posting.PROOF_HASH,
            evidence_cutoff_at=posting.NOW,
            approval_ref="labor-approval:protected:2026-11",
            approval_hash=posting.PROOF_HASH,
            approved_at=posting.NOW + timedelta(minutes=1),
            lines=(
                LaborEffortLineInput(
                    project_id=posting.PROJECT_ID,
                    project_code=posting.PROJECT_CODE,
                    work_code=None,
                    effort_units=Decimal("20.0000"),
                    population_count=2,
                    minimum_population=3,
                    basis_source_ref="labor-sor:protected:project-line",
                    basis_source_hash=posting.PROOF_HASH,
                    organization_ref="org:protected-engineering",
                    grade_band="G4",
                    cost_cohort="engineering-g4",
                ),
            ),
        )
        effort = bridge.admit_labor_effort(effort_input)
        assert (
            bridge.admit_labor_effort(effort_input)["idempotency_disposition"]
            == "EXACT_REPLAY"
        )
        assert effort["lines"][0]["ordinary_view_suppressed"] is True
        assert effort["lines"][0]["work_assignment_id"] is None

        with sessions() as session:
            counts = tuple(
                session.scalar(select(func.count()).select_from(table))
                for table in (
                    EOS_PAYROLL_POST_EVIDENCE_TABLE,
                    EOS_LABOR_EFFORT_SNAPSHOT_TABLE,
                    EOS_LABOR_EFFORT_LINE_TABLE,
                )
            )
        assert counts == (1, 1, 1)

        with pytest.raises(DBAPIError), sessions.begin() as session:
            session.execute(
                update(EOS_PAYROLL_POST_EVIDENCE_TABLE).values(
                    reconciliation_state="BLOCKED"
                )
            )
        with psycopg.connect(psycopg_url) as connection:
            private_columns = connection.execute(
                """
                SELECT column_name
                  FROM information_schema.columns
                 WHERE table_schema = %s
                   AND table_name IN (
                       'eos_payroll_post_evidence',
                       'eos_labor_effort_snapshot',
                       'eos_labor_effort_line'
                   )
                   AND column_name IN (
                       'employee_id', 'subject_ref', 'salary', 'net_pay',
                       'tax_amount', 'bank_account'
                   )
                """,
                (schema_name,),
            ).fetchall()
        assert private_columns == []
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
