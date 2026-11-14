from __future__ import annotations

import os
import uuid
from datetime import date, timedelta
from decimal import Decimal

import psycopg
import pytest
import test_nex_eos_mybee_cost_pool as source_fixture
from nex_eos import (
    EOS_COST_ALLOCATION_ADJUSTMENT_TABLE,
    EOS_COST_ALLOCATION_PLAN_LINE_TABLE,
    EOS_COST_ALLOCATION_PLAN_TABLE,
    EOS_PAYROLL_PROJECT_ALLOCATION_TABLE,
    EOS_PROJECT_COMPANY_BINDING_TABLE,
    EosCostAllocationService,
    EosCostSourcePoolService,
    EosPayrollLaborBridgeService,
    EosPayrollProjectAllocationService,
    EosProjectPnlProjector,
    LaborEffortLineInput,
    LaborEffortSnapshotInput,
    PayrollPostingEvidenceInput,
    PayrollProjectAdjustmentRequest,
    PayrollProjectAllocationRequest,
    ProjectPnlRebuildRequest,
    SqlAlchemyEosBusinessTransactionCoordinator,
    SqlAlchemyEosCostSourceFactsSource,
    SqlAlchemyEosCostSourcePoolRepository,
    SqlAlchemyEosPayrollLaborBridgeRepository,
    SqlAlchemyEosPayrollProjectAllocationRepository,
    SqlAlchemyEosProjectPnlProjectionSource,
    SqlAlchemyEosProjectPnlRepository,
)
from nex_runtime import psycopg_database_url
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from psycopg import sql
from run_migrations import run_service_migrations
from sqlalchemy import create_engine, func, make_url, select, update
from sqlalchemy.exc import DBAPIError

DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
POSTGRES_SMOKE = os.getenv("NEX_EOS_MYBEE_S7_02C_POSTGRES_SMOKE") == "1"
PLAN_ID = "76500000-0000-4000-8000-000000000021"


def _insert_plan(sessions, *, posting, snapshot: dict, revision: int) -> None:
    line = snapshot["lines"][0]
    basis_units = Decimal(line["effort_units"]).quantize(Decimal("0.0001"))
    basis_kind = (
        "ACTUAL_WORK"
        if snapshot["basis_kind"] == "ACTUAL_APPROVED"
        else "APPROVED_PLAN"
    )
    eligibility_hash = semantic_sha256_hash_ref(
        {
            "domain": "EOS-PAYROLL-ALLOCATION-ELIGIBILITY-V1",
            "snapshot_hash": snapshot["snapshot_hash"],
            "project_id": line["project_id"],
            "project_code": line["project_code"],
            "basis_units": format(basis_units, "f"),
            "line_hashes": [line["line_hash"]],
            "policy_hash": posting.PROOF_HASH,
        }
    )
    plan_hash = semantic_sha256_hash_ref(
        {
            "domain": "TEST-W60-S7-02C-PAYROLL-PLAN",
            "snapshot_hash": snapshot["snapshot_hash"],
            "revision": revision,
        }
    )
    with sessions.begin() as session:
        session.execute(
            EOS_COST_ALLOCATION_PLAN_TABLE.insert().values(
                tenant_id=posting.TENANT,
                company_id=posting.COMPANY_ID,
                plan_id=PLAN_ID,
                plan_revision=revision,
                source_kind="PAYROLL",
                scope_type="PROJECT_SET",
                basis_kind=basis_kind,
                rule_release_hash=posting.PROOF_HASH,
                basis_source_ref=f"eos.labor-effort-snapshot:{snapshot['snapshot_id']}",
                basis_source_hash=snapshot["snapshot_hash"],
                effective_start=date(2026, 11, 1),
                effective_end=date(2026, 11, 30),
                approved_by="finance-controller",
                approved_proof=f"eos.approval-proof:payroll:{revision}",
                state="APPROVED",
                plan_hash=plan_hash,
                created_at=posting.NOW + timedelta(minutes=revision),
            )
        )
        session.execute(
            EOS_COST_ALLOCATION_PLAN_LINE_TABLE.insert().values(
                tenant_id=posting.TENANT,
                company_id=posting.COMPANY_ID,
                plan_id=PLAN_ID,
                plan_revision=revision,
                line_no=1,
                project_id=line["project_id"],
                project_code=line["project_code"],
                work_code=line["work_code"],
                basis_units=basis_units,
                allocation_ratio=Decimal("1.000000000000"),
                eligibility_hash=eligibility_hash,
                confidentiality_class="RESTRICTED",
                line_hash=semantic_sha256_hash_ref(
                    {
                        "domain": "TEST-W60-S7-02C-PAYROLL-PLAN-LINE",
                        "plan_revision": revision,
                        "project_id": line["project_id"],
                    }
                ),
            )
        )


@pytest.mark.skipif(
    not DATABASE_URL or not POSTGRES_SMOKE,
    reason="Protected W60 S7-02C EOS PostgreSQL smoke is disabled",
)
def test_actual_postgres_labor_adjustment_residual_and_pnl_rebuild() -> None:
    schema_name = f"mybee_w60_s702c_{uuid.uuid4().hex}"
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
        assert "2545_eos_payroll_project_allocation" in migration.applied
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
        payroll = bridge.admit_payroll_posting(
            PayrollPostingEvidenceInput(
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
        )

        def effort_input(*, revision: int, basis_kind: str) -> LaborEffortSnapshotInput:
            return LaborEffortSnapshotInput(
                tenant_id=posting.TENANT,
                company_id=posting.COMPANY_ID,
                effort_period_start=date(2026, 11, 1),
                effort_period_end=date(2026, 11, 30),
                revision=revision,
                basis_kind=basis_kind,
                effort_unit="MAN_DAY",
                source_ref=f"labor-sor:protected:2026-11:{revision}",
                source_hash=posting.PROOF_HASH,
                evidence_cutoff_at=posting.NOW,
                approval_ref=f"labor-approval:protected:2026-11:{revision}",
                approval_hash=posting.PROOF_HASH,
                approved_at=posting.NOW + timedelta(minutes=revision),
                lines=(
                    LaborEffortLineInput(
                        project_id=posting.PROJECT_ID,
                        project_code=posting.PROJECT_CODE,
                        work_code=None,
                        effort_units=Decimal("20.0000"),
                        population_count=4,
                        minimum_population=3,
                        basis_source_ref=f"labor-sor:protected:line:{revision}",
                        basis_source_hash=posting.PROOF_HASH,
                        organization_ref="org:protected-engineering",
                        grade_band="G4",
                        cost_cohort="engineering-g4",
                    ),
                ),
            )

        initial_snapshot = bridge.admit_labor_effort(
            effort_input(revision=1, basis_kind="ACTUAL_APPROVED")
        )
        _insert_plan(sessions, posting=posting, snapshot=initial_snapshot, revision=1)
        coordinator = SqlAlchemyEosBusinessTransactionCoordinator(
            sessions,
            id_factory=lambda: str(uuid.uuid4()),
            clock=lambda: posting.NOW + timedelta(minutes=3),
        )
        allocation = EosPayrollProjectAllocationService(
            repository=SqlAlchemyEosPayrollProjectAllocationRepository(
                sessions, clock=lambda: posting.NOW + timedelta(minutes=3)
            ),
            cost_allocation_service=EosCostAllocationService(
                session_factory=sessions,
                coordinator=coordinator,
                clock=lambda: posting.NOW + timedelta(minutes=3),
            ),
            coordinator=coordinator,
        )
        initial_request = PayrollProjectAllocationRequest(
            tenant_id=posting.TENANT,
            company_id=posting.COMPANY_ID,
            payroll_evidence_id=payroll["evidence_id"],
            effort_snapshot_id=initial_snapshot["snapshot_id"],
            plan_id=PLAN_ID,
            plan_revision=1,
            policy_hash=posting.PROOF_HASH,
            residual_treatment="RETAIN_UNALLOCATED",
            residual_effort_units=Decimal("10.0000"),
        )
        initial = allocation.allocate(initial_request)
        assert initial["allocation_status"] == "CONFIRMED"
        assert initial["residual_total"] != "0.0000"
        assert allocation.allocate(initial_request)["disposition"] == "EXACT_REPLAY"

        actual = bridge.admit_labor_effort(
            effort_input(revision=2, basis_kind="ACTUAL_APPROVED")
        )
        _insert_plan(sessions, posting=posting, snapshot=actual, revision=2)
        adjustment_request = PayrollProjectAdjustmentRequest(
            tenant_id=posting.TENANT,
            company_id=posting.COMPANY_ID,
            supersedes_allocation_id=initial["allocation_id"],
            effort_snapshot_id=actual["snapshot_id"],
            plan_id=PLAN_ID,
            plan_revision=2,
            policy_hash=posting.PROOF_HASH,
            residual_treatment="RETAIN_UNALLOCATED",
        )
        adjusted = allocation.adjust(adjustment_request)
        assert adjusted["allocation_status"] == "CONFIRMED"
        assert adjusted["adjustment_kind"] == "ACTUAL_CORRECTION"
        assert adjusted["adjustment_count"] == 1
        assert adjusted["residual_total"] == "0.0000"
        assert allocation.adjust(adjustment_request)["disposition"] == "EXACT_REPLAY"

        projector = EosProjectPnlProjector(
            source=SqlAlchemyEosProjectPnlProjectionSource(sessions),
            sink=SqlAlchemyEosProjectPnlRepository(sessions),
        )
        projection_request = ProjectPnlRebuildRequest(
            tenant_id=posting.TENANT,
            company_id=posting.COMPANY_ID,
            project_id=posting.PROJECT_ID,
            project_code=posting.PROJECT_CODE,
            period_id=source_pool["period_id"],
            projection_version=1,
            functional_currency="KRW",
            as_of=posting.NOW + timedelta(minutes=10),
            evaluated_at=posting.NOW + timedelta(minutes=10),
        )
        projection = projector.rebuild(projection_request)
        assert (
            projection["posted_allocated_cost"]
            == source_pool["eligible_amount_functional"]
        )
        assert projection["operating_unallocated_cost"] == "0.0000"
        assert projection["reconciliation_status"] == "VERIFIED"
        assert projection["payroll_evidence_watermark"].startswith("sha256:")
        assert projection["labor_effort_watermark"].startswith("sha256:")

        with sessions() as session:
            counts = (
                session.scalar(
                    select(func.count()).select_from(
                        EOS_PAYROLL_PROJECT_ALLOCATION_TABLE
                    )
                ),
                session.scalar(
                    select(func.count()).select_from(
                        EOS_COST_ALLOCATION_ADJUSTMENT_TABLE
                    )
                ),
            )
        assert counts == (2, 1)
        with pytest.raises(DBAPIError), sessions.begin() as session:
            session.execute(
                update(EOS_PAYROLL_PROJECT_ALLOCATION_TABLE).values(
                    allocation_status="PROVISIONAL"
                )
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
