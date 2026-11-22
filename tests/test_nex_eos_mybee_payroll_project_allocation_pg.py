from __future__ import annotations

import os
import uuid
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from json import dumps
from math import ceil
from pathlib import Path
from time import perf_counter

import psycopg
import pytest
import test_nex_eos_mybee_cost_pool as source_fixture
from mybee_ax.integrations.nex_pnl_client import admit_project_pnl_projection
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
    EosProjectPnlPrivacyGuard,
    EosProjectPnlProjector,
    EosProjectPnlQueryService,
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
    SqlAlchemyEosPnlPrivacyRepository,
    SqlAlchemyEosProjectPnlProjectionSource,
    SqlAlchemyEosProjectPnlRepository,
)
from nex_eos.project_authorization import EosProjectAuthorizationEvidence
from nex_runtime import psycopg_database_url
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from psycopg import sql
from run_migrations import run_service_migrations
from sqlalchemy import create_engine, func, make_url, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
POSTGRES_SMOKE = os.getenv("NEX_EOS_MYBEE_S7_02C_POSTGRES_SMOKE") == "1"
PLAN_ID = "76500000-0000-4000-8000-000000000021"
PERFORMANCE_REPORT = os.getenv("NEX_MYBEE_W60_PERFORMANCE_REPORT", "")
_REBUILD_SAMPLES = 20
_READ_SAMPLES = 50
_READ_CONCURRENCY = 50
_REBUILD_P95_BUDGET_MS = 30_000.0
_READ_P95_BUDGET_MS = 2_000.0


class _PnlAuthorizer:
    def __init__(self, *, project_code: str, now) -> None:
        self._evidence = EosProjectAuthorizationEvidence(
            decision_ref="oa-decision:w60-s7-03a",
            project_code=project_code,
            project_role="OWNER",
            project_status="ACTIVE",
            source_version=1,
            projection_event_hash="sha256:" + "1" * 64,
            authorization_revision_hash="sha256:" + "2" * 64,
            decided_at=now.isoformat(),
        )

    def authorize(self, **kwargs):
        assert kwargs["action"] == "project:pnl:read"
        return self._evidence


def _nearest_rank(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, ceil(len(ordered) * percentile) - 1)]


def _plan_indexes(value: object) -> set[str]:
    indexes: set[str] = set()
    if isinstance(value, Mapping):
        index_name = value.get("Index Name")
        if isinstance(index_name, str):
            indexes.add(index_name)
        for child in value.values():
            indexes.update(_plan_indexes(child))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for child in value:
            indexes.update(_plan_indexes(child))
    return indexes


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


def test_w60_performance_helpers_and_budgets_are_stable() -> None:
    assert _nearest_rank([8.0, 2.0, 4.0, 6.0], 0.95) == 8.0
    assert _plan_indexes(
        [
            {
                "Plan": {
                    "Node Type": "Limit",
                    "Plans": [
                        {
                            "Node Type": "Index Scan",
                            "Index Name": "ix_eos_project_pnl_lookup",
                        }
                    ],
                }
            }
        ]
    ) == {"ix_eos_project_pnl_lookup"}
    assert _REBUILD_SAMPLES >= 20
    assert _READ_SAMPLES == _READ_CONCURRENCY == 50
    assert _REBUILD_P95_BUDGET_MS == 30_000.0
    assert _READ_P95_BUDGET_MS == 2_000.0


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
        rebuild_latencies_ms: list[float] = []
        projection = None
        for projection_version in range(1, _REBUILD_SAMPLES + 1):
            started = perf_counter()
            projection = projector.rebuild(
                replace(
                    projection_request,
                    projection_version=projection_version,
                )
            )
            rebuild_latencies_ms.append((perf_counter() - started) * 1000.0)
        assert projection is not None
        assert (
            projection["posted_allocated_cost"]
            == source_pool["eligible_amount_functional"]
        )
        assert projection["operating_unallocated_cost"] == "0.0000"
        assert projection["reconciliation_status"] == "VERIFIED"
        assert projection["payroll_evidence_watermark"].startswith("sha256:")
        assert projection["labor_effort_watermark"].startswith("sha256:")
        rebuild_p95_ms = _nearest_rank(rebuild_latencies_ms, 0.95)
        assert rebuild_p95_ms <= _REBUILD_P95_BUDGET_MS

        engine.dispose()
        engine = create_engine(scoped_url, pool_pre_ping=True)
        sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        restarted_projector = EosProjectPnlProjector(
            source=SqlAlchemyEosProjectPnlProjectionSource(sessions),
            sink=SqlAlchemyEosProjectPnlRepository(sessions),
        )
        replay = restarted_projector.rebuild(
            replace(
                projection_request,
                projection_version=_REBUILD_SAMPLES,
            )
        )
        assert replay == projection

        query_service = EosProjectPnlQueryService(
            repository=SqlAlchemyEosProjectPnlRepository(sessions),
            project_authorizer=_PnlAuthorizer(
                project_code=posting.PROJECT_CODE,
                now=posting.NOW,
            ),
            privacy_guard=EosProjectPnlPrivacyGuard(
                SqlAlchemyEosPnlPrivacyRepository(sessions)
            ),
        )
        query = {
            "tenant_id": posting.TENANT,
            "company_id": posting.COMPANY_ID,
            "project_id": posting.PROJECT_ID,
            "period_id": source_pool["period_id"],
            "requester_subject_id": "w60-pnl-reader",
        }
        protected = query_service.get(
            **query,
            correlation_id="w60-s7-03a-prime",
        )
        assert protected == projection
        admitted = admit_project_pnl_projection(
            protected,
            tenant_id=posting.TENANT,
            company_id=posting.COMPANY_ID,
            project_id=posting.PROJECT_ID,
            project_code=posting.PROJECT_CODE,
            period_id=source_pool["period_id"],
        )
        assert (
            admitted["posted_allocated_cost"]
            == (source_pool["eligible_amount_functional"])
        )

        def protected_read(sample: int) -> tuple[float, str]:
            started = perf_counter()
            result = query_service.get(
                **query,
                correlation_id=f"w60-s7-03a-read-{sample}",
            )
            return (perf_counter() - started) * 1000.0, result["projection_hash"]

        with ThreadPoolExecutor(max_workers=_READ_CONCURRENCY) as executor:
            reads = tuple(executor.map(protected_read, range(_READ_SAMPLES)))
        read_latencies_ms = [latency for latency, _hash in reads]
        assert {projection_hash for _latency, projection_hash in reads} == {
            projection["projection_hash"]
        }
        read_p95_ms = _nearest_rank(read_latencies_ms, 0.95)
        assert read_p95_ms <= _READ_P95_BUDGET_MS

        with sessions.begin() as session:
            session.execute(text("SET LOCAL enable_seqscan = off"))
            plan = session.execute(
                text(
                    "EXPLAIN (FORMAT JSON) "
                    "SELECT projection_id FROM eos_project_pnl_projection "
                    "WHERE tenant_id = :tenant_id "
                    "AND company_id = :company_id "
                    "AND project_id = :project_id "
                    "AND period_id = :period_id "
                    "ORDER BY projection_version DESC LIMIT 1"
                ),
                {
                    "tenant_id": posting.TENANT,
                    "company_id": posting.COMPANY_ID,
                    "project_id": posting.PROJECT_ID,
                    "period_id": source_pool["period_id"],
                },
            ).scalar_one()
        plan_indexes = _plan_indexes(plan)
        assert "ix_eos_project_pnl_lookup" in plan_indexes

        performance = {
            "schema_version": "mybee.w60_s7_03a_performance.v1",
            "status": "PASS",
            "rebuild_samples": _REBUILD_SAMPLES,
            "rebuild_p95_ms": round(rebuild_p95_ms, 3),
            "rebuild_p95_budget_ms": _REBUILD_P95_BUDGET_MS,
            "read_samples": _READ_SAMPLES,
            "read_concurrency": _READ_CONCURRENCY,
            "read_p95_ms": round(read_p95_ms, 3),
            "read_p95_budget_ms": _READ_P95_BUDGET_MS,
            "projection_index_names": sorted(plan_indexes),
            "restart_rebuild_exact_replay": True,
            "actual_population_evidence": True,
        }
        if PERFORMANCE_REPORT:
            report_path = Path(PERFORMANCE_REPORT)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                dumps(performance, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

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
