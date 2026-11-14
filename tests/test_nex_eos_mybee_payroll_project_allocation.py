from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from nex_eos import (
    EOS_ACCOUNTING_PERIOD_TABLE,
    EOS_COST_ALLOCATION_ADJUSTMENT_TABLE,
    EOS_COST_ALLOCATION_LINE_TABLE,
    EOS_COST_ALLOCATION_PLAN_LINE_TABLE,
    EOS_COST_ALLOCATION_PLAN_TABLE,
    EOS_COST_SOURCE_POOL_TABLE,
    EOS_LABOR_EFFORT_LINE_TABLE,
    EOS_LABOR_EFFORT_SNAPSHOT_TABLE,
    EOS_METADATA,
    EOS_PAYROLL_POST_EVIDENCE_TABLE,
    EOS_PAYROLL_PROJECT_ALLOCATION_TABLE,
    EosCostAllocationError,
    EosCostAllocationService,
    InMemoryEosBusinessTransactionCoordinator,
    PayrollProjectAdjustmentRequest,
    PayrollProjectAllocationRequest,
    SqlAlchemyEosBusinessTransactionCoordinator,
)
from nex_eos import payroll_project_allocations as allocation_module
from nex_eos import project_pnl_projector as projector_module
from nex_eos.payroll_project_allocations import (
    EosPayrollProjectAllocationError,
    EosPayrollProjectAllocationService,
    SqlAlchemyEosPayrollProjectAllocationRepository,
)
from nex_eos.project_pnl import build_project_pnl_records
from nex_eos.project_pnl_projector import (
    ProjectPnlAllocationFact,
    ProjectPnlLaborAdjustmentFact,
    ProjectPnlPayrollAllocationFact,
    ProjectPnlRebuildRequest,
    ProjectPnlSourcePoolFact,
    ProjectPnlSourceSnapshot,
    build_direct_allocation_projection,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from run_migrations import load_migrations
from sqlalchemy import create_engine, delete, func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

TENANT = "W602"
COMPANY_ID = "76500000-0000-4000-8000-000000000001"
PROJECT_A = "76500000-0000-4000-8000-000000000002"
PROJECT_B = "76500000-0000-4000-8000-000000000003"
PROJECT_C = "76500000-0000-4000-8000-000000000014"
PROJECT_CODE_A = "W602D260001"
PROJECT_CODE_B = "W602D260002"
PROJECT_CODE_C = "W602D260003"
PERIOD_ID = "76500000-0000-4000-8000-000000000004"
POOL_ID = "76500000-0000-4000-8000-000000000005"
JOURNAL_ID = "76500000-0000-4000-8000-000000000006"
ACCOUNT_ID = "76500000-0000-4000-8000-000000000007"
SOURCE_OPERATION_ID = "76500000-0000-4000-8000-000000000008"
EVIDENCE_ID = "76500000-0000-4000-8000-000000000009"
SNAPSHOT_1 = "76500000-0000-4000-8000-000000000010"
SNAPSHOT_2 = "76500000-0000-4000-8000-000000000011"
SNAPSHOT_3 = "76500000-0000-4000-8000-000000000013"
PLAN_ID = "76500000-0000-4000-8000-000000000012"
WORK_A = "FL0012004"
WORK_B = "FL0013001"
NOW = datetime(2026, 11, 14, 10, 0, tzinfo=UTC)
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64


def _runtime(*, basis_kind: str = "ACTUAL_APPROVED", units=("60", "40")):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    _seed(sessions, basis_kind=basis_kind, units=units)
    coordinator = SqlAlchemyEosBusinessTransactionCoordinator(
        sessions,
        id_factory=lambda: str(uuid.uuid4()),
        clock=lambda: NOW,
    )
    cost_service = EosCostAllocationService(
        session_factory=sessions,
        coordinator=coordinator,
        clock=lambda: NOW,
    )
    repository = SqlAlchemyEosPayrollProjectAllocationRepository(
        sessions, clock=lambda: NOW
    )
    service = EosPayrollProjectAllocationService(
        repository=repository,
        cost_allocation_service=cost_service,
        coordinator=coordinator,
    )
    return engine, sessions, repository, service


def _seed(sessions, *, basis_kind: str, units) -> None:
    policy_hash = HASH_B
    snapshot_hash = HASH_C
    line_values = _effort_lines(SNAPSHOT_1, units)
    targets = _targets(snapshot_hash, policy_hash, line_values)
    with sessions.begin() as session:
        session.execute(
            EOS_ACCOUNTING_PERIOD_TABLE.insert().values(
                tenant_id=TENANT,
                company_id=COMPANY_ID,
                period_id=PERIOD_ID,
                fiscal_year=2026,
                period_no=11,
                start_date=date(2026, 11, 1),
                end_date=date(2026, 11, 30),
                state="OPEN",
                version=1,
                close_proof_ref=None,
                closed_at=None,
                ledger_cutoff_watermark=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.execute(
            EOS_COST_SOURCE_POOL_TABLE.insert().values(
                tenant_id=TENANT,
                company_id=COMPANY_ID,
                pool_id=POOL_ID,
                journal_id=JOURNAL_ID,
                journal_line_no=1,
                eligible_component_id=f"ACCOUNT:{ACCOUNT_ID}",
                source_business_operation_id=SOURCE_OPERATION_ID,
                source_project_id=PROJECT_A,
                source_project_code=PROJECT_CODE_A,
                source_kind="PAYROLL",
                allocation_mode="MANAGEMENT_ALLOCATION",
                source_amount_functional=Decimal("1000.0000"),
                eligible_amount_functional=Decimal("1000.0000"),
                functional_currency="KRW",
                account_id=ACCOUNT_ID,
                account_category="EXPENSE",
                monetary_class="NON_MONETARY",
                recognition_date=date(2026, 11, 14),
                recognized_at=NOW,
                period_id=PERIOD_ID,
                source_record_ref="eos.journal:payroll:line:1",
                source_hash=HASH_A,
                eligibility_policy_hash=policy_hash,
                pool_state="OPEN",
                source_journal_hash=HASH_C,
                created_at=NOW,
            )
        )
        session.execute(
            EOS_PAYROLL_POST_EVIDENCE_TABLE.insert().values(
                tenant_id=TENANT,
                company_id=COMPANY_ID,
                evidence_id=EVIDENCE_ID,
                payroll_run_id="payroll-run:2026-11",
                payroll_period_start=date(2026, 11, 1),
                payroll_period_end=date(2026, 11, 30),
                revision=1,
                pool_id=POOL_ID,
                journal_id=JOURNAL_ID,
                journal_line_no=1,
                period_id=PERIOD_ID,
                eligible_component_id=f"ACCOUNT:{ACCOUNT_ID}",
                payroll_component_class="BASE_SALARY",
                organization_ref="org:engineering",
                account_id=ACCOUNT_ID,
                eligible_amount_functional=Decimal("1000.0000"),
                functional_currency="KRW",
                payroll_source_ref="payroll-sor:2026-11",
                payroll_source_hash=HASH_A,
                approval_ref="payroll-approval:2026-11",
                approval_hash=HASH_B,
                posting_mapping_hash=HASH_C,
                reconciliation_state="VERIFIED",
                privacy_class="PAYROLL_AGGREGATE",
                evidence_hash=HASH_A,
                recorded_at=NOW,
            )
        )
        _insert_snapshot(
            session,
            snapshot_id=SNAPSHOT_1,
            revision=1,
            basis_kind=basis_kind,
            snapshot_hash=snapshot_hash,
            line_values=line_values,
        )
        _insert_plan(
            session,
            revision=1,
            basis_kind=(
                "ACTUAL_WORK" if basis_kind == "ACTUAL_APPROVED" else "APPROVED_PLAN"
            ),
            plan_hash=HASH_A,
            targets=targets,
        )


def _effort_lines(snapshot_id: str, units) -> list[dict]:
    values = []
    for index, (project_id, code, work_code, amount) in enumerate(
        (
            (PROJECT_A, PROJECT_CODE_A, WORK_A, units[0]),
            (PROJECT_B, PROJECT_CODE_B, WORK_B, units[1]),
        ),
        start=1,
    ):
        line_hash = semantic_sha256_hash_ref(
            {"domain": "TEST-LABOR-LINE", "snapshot": snapshot_id, "line": index}
        )
        values.append(
            {
                "tenant_id": TENANT,
                "company_id": COMPANY_ID,
                "snapshot_id": snapshot_id,
                "line_no": index,
                "project_id": project_id,
                "project_code": code,
                "work_code": work_code,
                "organization_ref": "org:engineering",
                "grade_band": "G4",
                "cost_cohort": "engineering-g4",
                "effort_units": Decimal(amount).quantize(Decimal("0.0001")),
                "population_count": 4,
                "minimum_population": 3,
                "ordinary_view_suppressed": False,
                "work_assignment_id": None,
                "basis_source_ref": f"labor-sor:{snapshot_id}:line:{index}",
                "basis_source_hash": HASH_A,
                "line_hash": line_hash,
            }
        )
    return values


def _targets(snapshot_hash: str, policy_hash: str, lines) -> list[dict]:
    total = sum((Decimal(str(item["effort_units"])) for item in lines), Decimal())
    values = []
    for item in lines:
        basis = Decimal(str(item["effort_units"])).quantize(Decimal("0.0001"))
        ratio = (basis / total).quantize(Decimal("0.000000000001"))
        eligibility_hash = semantic_sha256_hash_ref(
            {
                "domain": "EOS-PAYROLL-ALLOCATION-ELIGIBILITY-V1",
                "snapshot_hash": snapshot_hash,
                "project_id": item["project_id"],
                "project_code": item["project_code"],
                "basis_units": format(basis, "f"),
                "line_hashes": [item["line_hash"]],
                "policy_hash": policy_hash,
            }
        )
        values.append(
            {
                "project_id": item["project_id"],
                "project_code": item["project_code"],
                "work_code": item["work_code"],
                "basis_units": basis,
                "allocation_ratio": ratio,
                "eligibility_hash": eligibility_hash,
            }
        )
    return values


def _insert_snapshot(
    session,
    *,
    snapshot_id: str,
    revision: int,
    basis_kind: str,
    snapshot_hash: str,
    line_values,
) -> None:
    session.execute(
        EOS_LABOR_EFFORT_SNAPSHOT_TABLE.insert().values(
            tenant_id=TENANT,
            company_id=COMPANY_ID,
            snapshot_id=snapshot_id,
            effort_period_start=date(2026, 11, 1),
            effort_period_end=date(2026, 11, 30),
            revision=revision,
            basis_kind=basis_kind,
            effort_unit="MAN_DAY",
            source_ref=f"labor-sor:snapshot:{snapshot_id}",
            source_hash=HASH_A,
            evidence_cutoff_at=NOW,
            approval_ref=f"labor-approval:{revision}",
            approval_hash=HASH_B,
            state="APPROVED",
            approved_at=NOW,
            privacy_class="LABOR_AGGREGATE",
            snapshot_hash=snapshot_hash,
            created_at=NOW,
        )
    )
    session.execute(EOS_LABOR_EFFORT_LINE_TABLE.insert(), line_values)


def _insert_plan(
    session,
    *,
    revision: int,
    basis_kind: str,
    plan_hash: str,
    targets,
) -> None:
    session.execute(
        EOS_COST_ALLOCATION_PLAN_TABLE.insert().values(
            tenant_id=TENANT,
            company_id=COMPANY_ID,
            plan_id=PLAN_ID,
            plan_revision=revision,
            source_kind="PAYROLL",
            scope_type="PROJECT_SET",
            basis_kind=basis_kind,
            rule_release_hash=HASH_B,
            basis_source_ref=f"eos.labor-effort-snapshot:{revision}",
            basis_source_hash=HASH_C,
            effective_start=date(2026, 11, 1),
            effective_end=date(2026, 11, 30),
            approved_by="finance-controller",
            approved_proof=f"eos.approval-proof:payroll:{revision}",
            state="APPROVED",
            plan_hash=plan_hash,
            created_at=NOW,
        )
    )
    session.execute(
        EOS_COST_ALLOCATION_PLAN_LINE_TABLE.insert(),
        [
            {
                "tenant_id": TENANT,
                "company_id": COMPANY_ID,
                "plan_id": PLAN_ID,
                "plan_revision": revision,
                "line_no": index,
                **target,
                "confidentiality_class": "RESTRICTED",
                "line_hash": semantic_sha256_hash_ref(
                    {
                        "domain": "TEST-PAYROLL-PLAN-LINE",
                        "revision": revision,
                        "project_id": target["project_id"],
                    }
                ),
            }
            for index, target in enumerate(targets, start=1)
        ],
    )


def _request(**overrides) -> PayrollProjectAllocationRequest:
    value = PayrollProjectAllocationRequest(
        tenant_id=TENANT,
        company_id=COMPANY_ID,
        payroll_evidence_id=EVIDENCE_ID,
        effort_snapshot_id=SNAPSHOT_1,
        plan_id=PLAN_ID,
        plan_revision=1,
        policy_hash=HASH_B,
        residual_treatment="RETAIN_UNALLOCATED",
    )
    return replace(value, **overrides)


def _insert_replacement(
    sessions,
    *,
    basis_kind: str = "ACTUAL_APPROVED",
    units=("50", "50"),
    revision: int = 2,
    snapshot_id: str = SNAPSHOT_2,
    snapshot_hash: str = HASH_A,
    plan_revision: int = 2,
    plan_hash: str = HASH_C,
) -> None:
    line_values = _effort_lines(snapshot_id, units)
    targets = _targets(snapshot_hash, HASH_B, line_values)
    with sessions.begin() as session:
        _insert_snapshot(
            session,
            snapshot_id=snapshot_id,
            revision=revision,
            basis_kind=basis_kind,
            snapshot_hash=snapshot_hash,
            line_values=line_values,
        )
        _insert_plan(
            session,
            revision=plan_revision,
            basis_kind=(
                "ACTUAL_WORK" if basis_kind == "ACTUAL_APPROVED" else "APPROVED_PLAN"
            ),
            plan_hash=plan_hash,
            targets=targets,
        )


def test_migration_extends_existing_adjustment_authority_and_is_append_only():
    migration = next(
        item
        for item in load_migrations("nex-eos")
        if item.version == "2545_eos_payroll_project_allocation"
    )
    compact = " ".join(migration.sql.lower().split())
    assert "create table if not exists eos_payroll_project_alloc" in compact
    assert "alter table eos_cost_allocation_adjustment" in compact
    assert "add column if not exists payroll_allocation_id" in compact
    assert "drop constraint if exists ck_eos_project_pnl_component_semantics" in compact
    assert "'labor_adjustment' ) and rollup_class = 'allocated_cost'" in compact
    assert "trg_eos_payroll_alloc_immutable" in compact
    assert "trg_eos_cost_adjustment_immutable" in compact
    assert all(
        item.name is None or len(item.name) <= 63
        for table in (
            EOS_PAYROLL_PROJECT_ALLOCATION_TABLE,
            EOS_COST_ALLOCATION_ADJUSTMENT_TABLE,
        )
        for item in table.constraints
    )


def test_actual_payroll_allocation_preserves_residual_and_exact_replay():
    engine, sessions, _repository, service = _runtime()
    try:
        request = _request(residual_effort_units=Decimal("25.0000"))
        created = service.allocate(request)
        replay = service.allocate(request)
        assert created["disposition"] == "CREATED"
        assert replay["disposition"] == "EXACT_REPLAY"
        assert created["allocation_status"] == "CONFIRMED"
        assert created["allocated_total"] == "800.0000"
        assert created["residual_total"] == "200.0000"
        assert created["cost_allocation"]["allocated_total"] == "800.0000"
        assert created["cost_allocation"]["unallocated_total"] == "200.0000"
        with sessions() as session:
            amounts = list(
                session.scalars(
                    select(
                        EOS_COST_ALLOCATION_LINE_TABLE.c.allocated_amount_functional
                    ).order_by(EOS_COST_ALLOCATION_LINE_TABLE.c.line_no)
                )
            )
            assert amounts == [Decimal("480.0000"), Decimal("320.0000")]
            assert (
                session.scalar(
                    select(func.count()).select_from(
                        EOS_PAYROLL_PROJECT_ALLOCATION_TABLE
                    )
                )
                == 1
            )
    finally:
        engine.dispose()


def test_indirect_overhead_allocates_all_payroll_without_hiding_residual_effort():
    engine, _sessions, _repository, service = _runtime()
    try:
        result = service.allocate(
            _request(
                residual_treatment="ALLOCATE_INDIRECT_OVERHEAD",
                residual_effort_units=Decimal("25.0000"),
            )
        )
        assert result["allocated_total"] == "1000.0000"
        assert result["residual_total"] == "0.0000"
        assert result["residual_effort_units"] == "25.0000"
    finally:
        engine.dispose()


def test_plan_fallback_to_actual_creates_append_only_adjustments_and_replays():
    engine, sessions, _repository, service = _runtime(
        basis_kind="APPROVED_PLAN_FALLBACK"
    )
    try:
        initial = service.allocate(_request())
        assert initial["allocation_status"] == "PROVISIONAL"
        line_values = _effort_lines(SNAPSHOT_2, ("50", "50"))
        targets = _targets(HASH_A, HASH_B, line_values)
        with sessions.begin() as session:
            _insert_snapshot(
                session,
                snapshot_id=SNAPSHOT_2,
                revision=2,
                basis_kind="ACTUAL_APPROVED",
                snapshot_hash=HASH_A,
                line_values=line_values,
            )
            _insert_plan(
                session,
                revision=2,
                basis_kind="ACTUAL_WORK",
                plan_hash=HASH_C,
                targets=targets,
            )
        command = PayrollProjectAdjustmentRequest(
            tenant_id=TENANT,
            company_id=COMPANY_ID,
            supersedes_allocation_id=initial["allocation_id"],
            effort_snapshot_id=SNAPSHOT_2,
            plan_id=PLAN_ID,
            plan_revision=2,
            policy_hash=HASH_B,
            residual_treatment="RETAIN_UNALLOCATED",
        )
        adjusted = service.adjust(command)
        replay = service.adjust(command)
        assert adjusted["disposition"] == "CREATED"
        assert replay["disposition"] == "EXACT_REPLAY"
        assert adjusted["allocation_status"] == "CONFIRMED"
        assert adjusted["adjustment_kind"] == "PROVISIONAL_TO_ACTUAL"
        assert adjusted["adjustment_count"] == 2
        with sessions() as session:
            deltas = list(
                session.scalars(
                    select(EOS_COST_ALLOCATION_ADJUSTMENT_TABLE.c.delta_amount)
                    .where(
                        EOS_COST_ALLOCATION_ADJUSTMENT_TABLE.c.payroll_allocation_id
                        == adjusted["allocation_id"]
                    )
                    .order_by(EOS_COST_ALLOCATION_ADJUSTMENT_TABLE.c.target_project_id)
                )
            )
            assert deltas == [Decimal("-100.0000"), Decimal("100.0000")]
            assert (
                session.scalar(
                    select(func.count()).select_from(
                        EOS_PAYROLL_PROJECT_ALLOCATION_TABLE
                    )
                )
                == 2
            )
    finally:
        engine.dispose()


def test_confirmed_actual_correction_records_delta_and_blocks_old_revision():
    engine, sessions, _repository, service = _runtime()
    try:
        initial = service.allocate(_request())
        _insert_replacement(sessions)
        command = PayrollProjectAdjustmentRequest(
            tenant_id=TENANT,
            company_id=COMPANY_ID,
            supersedes_allocation_id=initial["allocation_id"],
            effort_snapshot_id=SNAPSHOT_2,
            plan_id=PLAN_ID,
            plan_revision=2,
            policy_hash=HASH_B,
            residual_treatment="RETAIN_UNALLOCATED",
        )
        adjusted = service.adjust(command)
        assert adjusted["adjustment_kind"] == "ACTUAL_CORRECTION"
        changed_command = replace(command, residual_effort_units=Decimal("10.0000"))
        with pytest.raises(EosPayrollProjectAllocationError, match="latest revision"):
            service.adjust(changed_command)
    finally:
        engine.dispose()


def test_later_actual_correction_uses_accumulated_adjustment_state():
    engine, sessions, _repository, service = _runtime()
    try:
        initial = service.allocate(_request())
        _insert_replacement(sessions, units=("50", "50"))
        first = service.adjust(
            PayrollProjectAdjustmentRequest(
                tenant_id=TENANT,
                company_id=COMPANY_ID,
                supersedes_allocation_id=initial["allocation_id"],
                effort_snapshot_id=SNAPSHOT_2,
                plan_id=PLAN_ID,
                plan_revision=2,
                policy_hash=HASH_B,
                residual_treatment="RETAIN_UNALLOCATED",
            )
        )
        _insert_replacement(
            sessions,
            units=("70", "30"),
            revision=3,
            snapshot_id=SNAPSHOT_3,
            snapshot_hash=HASH_B,
            plan_revision=3,
            plan_hash=HASH_B,
        )
        second = service.adjust(
            PayrollProjectAdjustmentRequest(
                tenant_id=TENANT,
                company_id=COMPANY_ID,
                supersedes_allocation_id=first["allocation_id"],
                effort_snapshot_id=SNAPSHOT_3,
                plan_id=PLAN_ID,
                plan_revision=3,
                policy_hash=HASH_B,
                residual_treatment="RETAIN_UNALLOCATED",
            )
        )
        assert second["allocation_revision"] == 3
        assert second["adjustment_kind"] == "ACTUAL_CORRECTION"
        assert second["adjustment_count"] == 2
    finally:
        engine.dispose()


def test_initial_record_persistence_guards_result_and_existing_identity():
    engine, _sessions, repository, service = _runtime()
    try:
        prepared = repository.prepare(_request())
        with pytest.raises(EosPayrollProjectAllocationError, match="batch differs"):
            repository.record_initial(prepared, {"batch_id": str(uuid.uuid4())})
        with pytest.raises(EosPayrollProjectAllocationError, match="was not found"):
            repository.record_initial(prepared, {"batch_id": prepared.batch_id})

        created = service.allocate(_request())
        assert created["disposition"] == "CREATED"
        drifted = replace(prepared, allocation_hash=HASH_B)
        with pytest.raises(
            EosPayrollProjectAllocationError, match="different semantics"
        ):
            repository.record_initial(drifted, {"batch_id": prepared.batch_id})
    finally:
        engine.dispose()


def test_adjustment_rejects_same_semantic_revision_before_mutation(monkeypatch):
    engine, sessions, repository, service = _runtime()
    try:
        initial = service.allocate(_request())
        _insert_replacement(sessions)
        replacement_request = PayrollProjectAllocationRequest(
            tenant_id=TENANT,
            company_id=COMPANY_ID,
            payroll_evidence_id=EVIDENCE_ID,
            effort_snapshot_id=SNAPSHOT_2,
            plan_id=PLAN_ID,
            plan_revision=2,
            policy_hash=HASH_B,
            residual_treatment="RETAIN_UNALLOCATED",
        )
        prepared = repository.prepare(replacement_request)
        monkeypatch.setattr(
            allocation_module,
            "_prepare_in_session",
            lambda *_args: replace(prepared, batch_id=initial["batch_id"]),
        )
        with pytest.raises(EosPayrollProjectAllocationError, match="semantic revision"):
            service.adjust(
                PayrollProjectAdjustmentRequest(
                    tenant_id=TENANT,
                    company_id=COMPANY_ID,
                    supersedes_allocation_id=initial["allocation_id"],
                    effort_snapshot_id=SNAPSHOT_2,
                    plan_id=PLAN_ID,
                    plan_revision=1,
                    policy_hash=HASH_B,
                    residual_treatment="RETAIN_UNALLOCATED",
                )
            )
    finally:
        engine.dispose()


def test_adjustment_rejects_missing_prior_unchanged_and_stale_snapshot():
    engine, sessions, _repository, service = _runtime()
    try:
        initial = service.allocate(_request())
        missing = PayrollProjectAdjustmentRequest(
            tenant_id=TENANT,
            company_id=COMPANY_ID,
            supersedes_allocation_id=str(uuid.uuid4()),
            effort_snapshot_id=SNAPSHOT_2,
            plan_id=PLAN_ID,
            plan_revision=2,
            policy_hash=HASH_B,
            residual_treatment="RETAIN_UNALLOCATED",
        )
        with pytest.raises(EosPayrollProjectAllocationError, match="was not found"):
            service.adjust(missing)

        _insert_replacement(sessions, units=("60", "40"), revision=2)
        unchanged = replace(missing, supersedes_allocation_id=initial["allocation_id"])
        with pytest.raises(EosPayrollProjectAllocationError, match="does not change"):
            service.adjust(unchanged)
    finally:
        engine.dispose()

    engine, sessions, _repository, service = _runtime()
    try:
        initial = service.allocate(_request())
        _insert_replacement(sessions, revision=1)
        stale = PayrollProjectAdjustmentRequest(
            tenant_id=TENANT,
            company_id=COMPANY_ID,
            supersedes_allocation_id=initial["allocation_id"],
            effort_snapshot_id=SNAPSHOT_2,
            plan_id=PLAN_ID,
            plan_revision=2,
            policy_hash=HASH_B,
            residual_treatment="RETAIN_UNALLOCATED",
        )
        with pytest.raises(EosPayrollProjectAllocationError, match="later revision"):
            service.adjust(stale)
    finally:
        engine.dispose()


def test_confirmed_allocation_cannot_regress_to_plan_fallback():
    engine, sessions, _repository, service = _runtime()
    try:
        initial = service.allocate(_request())
        _insert_replacement(
            sessions,
            basis_kind="APPROVED_PLAN_FALLBACK",
            units=("50", "50"),
        )
        command = PayrollProjectAdjustmentRequest(
            tenant_id=TENANT,
            company_id=COMPANY_ID,
            supersedes_allocation_id=initial["allocation_id"],
            effort_snapshot_id=SNAPSHOT_2,
            plan_id=PLAN_ID,
            plan_revision=2,
            policy_hash=HASH_B,
            residual_treatment="RETAIN_UNALLOCATED",
        )
        with pytest.raises(EosPayrollProjectAllocationError, match="regress"):
            service.adjust(command)
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "case",
    [
        "evidence_pending",
        "snapshot_revoked",
        "snapshot_outside_period",
        "no_effort_lines",
        "plan_draft",
        "plan_wrong_kind",
        "plan_wrong_basis",
        "pool_on_hold",
        "pool_wrong_kind",
        "pool_wrong_period",
        "plan_line_missing",
        "plan_line_drift",
    ],
)
def test_persisted_authority_drift_is_rejected(case):
    engine, sessions, repository, _service = _runtime()
    try:
        with sessions.begin() as session:
            if case == "evidence_pending":
                session.execute(
                    update(EOS_PAYROLL_POST_EVIDENCE_TABLE).values(
                        reconciliation_state="PENDING"
                    )
                )
            elif case == "snapshot_revoked":
                session.execute(
                    update(EOS_LABOR_EFFORT_SNAPSHOT_TABLE).values(state="REVOKED")
                )
            elif case == "snapshot_outside_period":
                session.execute(
                    update(EOS_LABOR_EFFORT_SNAPSHOT_TABLE).values(
                        effort_period_start=date(2026, 10, 31)
                    )
                )
            elif case == "no_effort_lines":
                session.execute(delete(EOS_LABOR_EFFORT_LINE_TABLE))
            elif case == "plan_draft":
                session.execute(
                    update(EOS_COST_ALLOCATION_PLAN_TABLE).values(state="DRAFT")
                )
            elif case == "plan_wrong_kind":
                session.execute(
                    update(EOS_COST_ALLOCATION_PLAN_TABLE).values(source_kind="SERVICE")
                )
            elif case == "plan_wrong_basis":
                session.execute(
                    update(EOS_COST_ALLOCATION_PLAN_TABLE).values(
                        basis_kind="APPROVED_PLAN"
                    )
                )
            elif case == "pool_on_hold":
                session.execute(
                    update(EOS_COST_SOURCE_POOL_TABLE).values(pool_state="ON_HOLD")
                )
            elif case == "pool_wrong_kind":
                session.execute(
                    update(EOS_COST_SOURCE_POOL_TABLE).values(source_kind="SERVICE")
                )
            elif case == "pool_wrong_period":
                session.execute(
                    update(EOS_COST_SOURCE_POOL_TABLE).values(
                        period_id=str(uuid.uuid4())
                    )
                )
            elif case == "plan_line_missing":
                session.execute(
                    delete(EOS_COST_ALLOCATION_PLAN_LINE_TABLE).where(
                        EOS_COST_ALLOCATION_PLAN_LINE_TABLE.c.line_no == 2
                    )
                )
            else:
                session.execute(
                    update(EOS_COST_ALLOCATION_PLAN_LINE_TABLE)
                    .where(EOS_COST_ALLOCATION_PLAN_LINE_TABLE.c.line_no == 1)
                    .values(eligibility_hash=HASH_C)
                )
        with pytest.raises(EosPayrollProjectAllocationError):
            repository.prepare(_request())
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "candidate",
    [
        replace(_request(), payroll_evidence_id=str(uuid.uuid4())),
        replace(_request(), effort_snapshot_id=str(uuid.uuid4())),
        replace(_request(), plan_id=str(uuid.uuid4())),
    ],
)
def test_missing_evidence_snapshot_or_plan_is_rejected(candidate):
    engine, _sessions, repository, _service = _runtime()
    try:
        with pytest.raises(EosPayrollProjectAllocationError):
            repository.prepare(candidate)
    finally:
        engine.dispose()


def test_operating_project_residual_is_added_to_governed_target(monkeypatch):
    monkeypatch.setattr(
        allocation_module,
        "_load_project",
        lambda *_args: {"project_code": PROJECT_CODE_A, "status": "ACTIVE"},
    )
    request = _request(
        residual_treatment="OPERATING_PROJECT",
        residual_effort_units=Decimal("25.0000"),
        operating_project_id=PROJECT_A,
        operating_project_code=PROJECT_CODE_A,
    )
    lines = _effort_lines(SNAPSHOT_1, ("60", "40"))
    targets = allocation_module._build_targets(
        None, request, {"snapshot_hash": HASH_C}, lines
    )
    assert [item.basis_units for item in targets] == [
        Decimal("85.0000"),
        Decimal("40.0000"),
    ]
    assert sum((item.allocation_ratio for item in targets), Decimal()) == Decimal(1)


@pytest.mark.parametrize(
    ("project", "message"),
    [
        (None, "authority"),
        ({"project_code": PROJECT_CODE_B, "status": "ACTIVE"}, "authority"),
        ({"project_code": PROJECT_CODE_A, "status": "INACTIVE"}, "active"),
    ],
)
def test_operating_project_authority_fails_closed(monkeypatch, project, message):
    monkeypatch.setattr(allocation_module, "_load_project", lambda *_args: project)
    request = _request(
        residual_treatment="OPERATING_PROJECT",
        residual_effort_units=Decimal("25.0000"),
        operating_project_id=PROJECT_A,
        operating_project_code=PROJECT_CODE_A,
    )
    with pytest.raises(EosPayrollProjectAllocationError, match=message):
        allocation_module._build_targets(
            None,
            request,
            {"snapshot_hash": HASH_C},
            _effort_lines(SNAPSHOT_1, ("60", "40")),
        )


def test_internal_target_guards_reject_missing_operating_project_and_zero_basis():
    request = replace(
        _request(),
        residual_treatment="OPERATING_PROJECT",
        residual_effort_units=Decimal("1.0000"),
    )
    with pytest.raises(EosPayrollProjectAllocationError, match="governed target"):
        allocation_module._build_targets(
            None,
            request,
            {"snapshot_hash": HASH_C},
            _effort_lines(SNAPSHOT_1, ("60", "40")),
        )
    with pytest.raises(EosPayrollProjectAllocationError, match="positive"):
        allocation_module._deterministic_ratios(())
    assert sum(
        allocation_module._deterministic_ratios((Decimal(1), Decimal(1), Decimal(1))),
        Decimal(),
    ) == Decimal(1)


def test_target_builder_accepts_project_level_effort_without_work_code():
    lines = [
        {**item, "work_code": None} for item in _effort_lines(SNAPSHOT_1, ("60", "40"))
    ]
    targets = allocation_module._build_targets(
        None, _request(), {"snapshot_hash": HASH_C}, lines
    )
    assert [item.work_code for item in targets] == [None, None]


@pytest.mark.parametrize(
    ("changes", "detail"),
    [
        ({"policy_hash": HASH_C}, "policy"),
        ({"residual_effort_units": Decimal(-1)}, "non-negative"),
        ({"operating_project_id": PROJECT_A}, "only valid"),
    ],
)
def test_invalid_or_unreleased_allocation_semantics_fail_closed(changes, detail):
    engine, _sessions, repository, _service = _runtime()
    try:
        with pytest.raises(EosPayrollProjectAllocationError) as caught:
            repository.prepare(_request(**changes))
        assert detail.lower() in caught.value.detail.lower()
    finally:
        engine.dispose()


def test_in_memory_adjustment_requires_database_transaction():
    engine, _sessions, repository, cost_service = _runtime()
    try:
        service = EosPayrollProjectAllocationService(
            repository=repository,
            cost_allocation_service=cost_service,
            coordinator=InMemoryEosBusinessTransactionCoordinator(),
        )
        with pytest.raises(EosPayrollProjectAllocationError) as caught:
            service.adjust(
                PayrollProjectAdjustmentRequest(
                    tenant_id=TENANT,
                    company_id=COMPANY_ID,
                    supersedes_allocation_id=str(uuid.uuid4()),
                    effort_snapshot_id=SNAPSHOT_2,
                    plan_id=PLAN_ID,
                    plan_revision=2,
                    policy_hash=HASH_B,
                    residual_treatment="RETAIN_UNALLOCATED",
                )
            )
        assert caught.value.error_code == "EOS_PAYROLL_ALLOCATION_TRANSACTION_REQUIRED"
    finally:
        engine.dispose()


def test_allocate_translates_cost_allocation_failure():
    engine, _sessions, repository, _service = _runtime()

    class _BrokenCostService:
        def run(self, **_kwargs):
            raise EosCostAllocationError(
                "EOS_COST_TEST_FAILURE",
                "allocation failed",
                status_code=409,
                retryable=True,
            )

    try:
        service = EosPayrollProjectAllocationService(
            repository=repository,
            cost_allocation_service=_BrokenCostService(),
            coordinator=InMemoryEosBusinessTransactionCoordinator(),
        )
        with pytest.raises(EosPayrollProjectAllocationError) as caught:
            service.allocate(_request())
        assert caught.value.error_code == "EOS_COST_TEST_FAILURE"
        assert caught.value.retryable is True
    finally:
        engine.dispose()


def test_repository_translates_sqlalchemy_failure(monkeypatch):
    engine, _sessions, repository, _service = _runtime()
    try:
        monkeypatch.setattr(
            allocation_module,
            "_prepare_in_session",
            lambda *_args: (_ for _ in ()).throw(SQLAlchemyError("db unavailable")),
        )
        with pytest.raises(EosPayrollProjectAllocationError) as caught:
            repository.prepare(_request())
        assert caught.value.status_code == 503
        assert caught.value.retryable is True
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "value",
    [
        object(),
        replace(_request(), tenant_id="!bad"),
        replace(_request(), company_id="bad"),
        replace(_request(), plan_revision=0),
        replace(_request(), policy_hash="bad"),
        replace(_request(), residual_treatment="HIDDEN_SPREAD"),
        replace(_request(), residual_effort_units=Decimal("1.00001")),
        replace(
            _request(),
            residual_treatment="OPERATING_PROJECT",
            residual_effort_units=Decimal(0),
        ),
        replace(
            _request(),
            residual_treatment="OPERATING_PROJECT",
            residual_effort_units=Decimal(1),
            operating_project_id=PROJECT_A,
            operating_project_code="bad",
        ),
    ],
)
def test_request_admission_rejects_malformed_values(value):
    with pytest.raises(EosPayrollProjectAllocationError):
        allocation_module._normalize_request(value)


def test_numeric_and_time_admission_edge_cases():
    with pytest.raises(EosPayrollProjectAllocationError, match="decimal"):
        allocation_module._effort("not-a-number")
    with pytest.raises(EosPayrollProjectAllocationError, match="finite"):
        allocation_module._money("NaN")
    with pytest.raises(EosPayrollProjectAllocationError, match="finite"):
        allocation_module._effort("NaN")
    with pytest.raises(EosPayrollProjectAllocationError, match="decimal"):
        allocation_module._money(object())
    with pytest.raises(EosPayrollProjectAllocationError, match="invalid type"):
        allocation_module._normalize_adjustment(object())
    with pytest.raises(EosPayrollProjectAllocationError, match="timezone-aware"):
        allocation_module._aware_time("clock", datetime(2026, 11, 14))  # noqa: DTZ001
    with pytest.raises(EosPayrollProjectAllocationError, match="malformed"):
        allocation_module._wire_time("not-a-time")
    assert allocation_module._wire_time(
        datetime(2026, 11, 14, 10, 0)  # noqa: DTZ001
    ).endswith("Z")


def _pool_fact() -> ProjectPnlSourcePoolFact:
    return ProjectPnlSourcePoolFact(
        pool_id=POOL_ID,
        journal_id=JOURNAL_ID,
        journal_line_no=1,
        source_project_id=PROJECT_A,
        source_project_code=PROJECT_CODE_A,
        source_kind="PAYROLL",
        allocation_mode="MANAGEMENT_ALLOCATION",
        eligible_amount_functional=Decimal("1000.0000"),
        functional_currency="KRW",
        account_id=ACCOUNT_ID,
        account_category="EXPENSE",
        source_record_ref="eos.journal:payroll:line:1",
        source_hash=HASH_A,
        source_journal_hash=HASH_B,
        pool_state="ALLOCATED",
        recognized_at=NOW,
    )


def _allocation_fact(
    project_id, project_code, amount, line_no
) -> ProjectPnlAllocationFact:
    return ProjectPnlAllocationFact(
        batch_id="76500000-0000-4000-8000-000000000020",
        line_no=line_no,
        pool_id=POOL_ID,
        project_id=project_id,
        project_code=project_code,
        work_code=WORK_A if project_id == PROJECT_A else WORK_B,
        allocated_amount_functional=Decimal(amount),
        allocation_mode="MANAGEMENT_ALLOCATION",
        evidence_hash=HASH_A if line_no == 1 else HASH_B,
        reconciliation_hash=HASH_C,
        committed_at=NOW,
    )


def _payroll_link(
    allocation_id, revision, status, supersedes=None
) -> ProjectPnlPayrollAllocationFact:
    return ProjectPnlPayrollAllocationFact(
        allocation_id=allocation_id,
        allocation_revision=revision,
        payroll_evidence_id=EVIDENCE_ID,
        effort_snapshot_id=SNAPSHOT_1 if revision == 1 else SNAPSHOT_2,
        batch_id="76500000-0000-4000-8000-000000000020",
        allocation_status=status,
        residual_treatment="RETAIN_UNALLOCATED",
        allocated_total=Decimal("1000.0000"),
        residual_total=Decimal("0.0000"),
        allocation_hash=HASH_A if revision == 1 else HASH_B,
        supersedes_allocation_id=supersedes,
        evidence_hash=HASH_A,
        snapshot_hash=HASH_B if revision == 1 else HASH_C,
        recorded_at=NOW,
        created_at=NOW,
    )


def _pnl_request(
    *, project_id: str = PROJECT_A, project_code: str = PROJECT_CODE_A
) -> ProjectPnlRebuildRequest:
    return ProjectPnlRebuildRequest(
        tenant_id=TENANT,
        company_id=COMPANY_ID,
        project_id=project_id,
        project_code=project_code,
        period_id=PERIOD_ID,
        projection_version=1,
        functional_currency="KRW",
        as_of=NOW,
        evaluated_at=NOW,
    )


def _labor_adjustment(
    *, allocation_id, project_id, project_code, delta, suffix
) -> ProjectPnlLaborAdjustmentFact:
    return ProjectPnlLaborAdjustmentFact(
        adjustment_id=f"76500000-0000-4000-8000-0000000000{suffix}",
        payroll_allocation_id=allocation_id,
        target_project_id=project_id,
        target_project_code=project_code,
        work_code=WORK_A if project_id == PROJECT_A else WORK_B,
        delta_amount=Decimal(delta),
        adjustment_kind="PROVISIONAL_TO_ACTUAL",
        adjustment_hash=HASH_C,
        created_at=NOW,
    )


def test_projector_replaces_provisional_with_actual_and_sets_watermarks():
    first = "76500000-0000-4000-8000-000000000030"
    second = "76500000-0000-4000-8000-000000000031"
    snapshot = ProjectPnlSourceSnapshot(
        pools=(_pool_fact(),),
        allocations=(
            _allocation_fact(PROJECT_A, PROJECT_CODE_A, "600", 1),
            _allocation_fact(PROJECT_B, PROJECT_CODE_B, "400", 2),
        ),
        payroll_allocations=(
            _payroll_link(first, 1, "PROVISIONAL"),
            _payroll_link(second, 2, "CONFIRMED", first),
        ),
        labor_adjustments=(
            _labor_adjustment(
                allocation_id=second,
                project_id=PROJECT_A,
                project_code=PROJECT_CODE_A,
                delta="-100",
                suffix="41",
            ),
            _labor_adjustment(
                allocation_id=second,
                project_id=PROJECT_B,
                project_code=PROJECT_CODE_B,
                delta="100",
                suffix="42",
            ),
        ),
    )
    request = ProjectPnlRebuildRequest(
        tenant_id=TENANT,
        company_id=COMPANY_ID,
        project_id=PROJECT_A,
        project_code=PROJECT_CODE_A,
        period_id=PERIOD_ID,
        projection_version=1,
        functional_currency="KRW",
        as_of=NOW,
        evaluated_at=NOW,
    )
    draft, components = build_direct_allocation_projection(request, snapshot)
    assert [(item.classification, item.functional_amount) for item in components] == [
        ("POSTED_LABOR_ALLOCATED", Decimal("500.0000"))
    ]
    assert draft.payroll_evidence_watermark is not None
    assert draft.labor_effort_watermark is not None
    assert draft.reconciliation_status == "VERIFIED"


def test_projector_rolls_labor_adjustment_into_confirmed_allocated_cost():
    first = "76500000-0000-4000-8000-000000000030"
    second = "76500000-0000-4000-8000-000000000031"
    snapshot = ProjectPnlSourceSnapshot(
        pools=(_pool_fact(),),
        allocations=(
            _allocation_fact(PROJECT_A, PROJECT_CODE_A, "600", 1),
            _allocation_fact(PROJECT_B, PROJECT_CODE_B, "400", 2),
        ),
        payroll_allocations=(
            _payroll_link(first, 1, "CONFIRMED"),
            _payroll_link(second, 2, "CONFIRMED", first),
        ),
        labor_adjustments=(
            _labor_adjustment(
                allocation_id=second,
                project_id=PROJECT_A,
                project_code=PROJECT_CODE_A,
                delta="100",
                suffix="41",
            ),
            _labor_adjustment(
                allocation_id=second,
                project_id=PROJECT_B,
                project_code=PROJECT_CODE_B,
                delta="-100",
                suffix="42",
            ),
        ),
    )
    request = ProjectPnlRebuildRequest(
        tenant_id=TENANT,
        company_id=COMPANY_ID,
        project_id=PROJECT_A,
        project_code=PROJECT_CODE_A,
        period_id=PERIOD_ID,
        projection_version=1,
        functional_currency="KRW",
        as_of=NOW,
        evaluated_at=NOW,
    )
    draft, components = build_direct_allocation_projection(request, snapshot)
    header, _records = build_project_pnl_records(draft, components)
    assert header["posted_allocated_cost"] == Decimal("700.0000")


def test_projector_supports_project_introduced_by_later_labor_adjustment():
    first = "76500000-0000-4000-8000-000000000030"
    second = "76500000-0000-4000-8000-000000000031"
    snapshot = ProjectPnlSourceSnapshot(
        pools=(_pool_fact(),),
        allocations=(
            _allocation_fact(PROJECT_A, PROJECT_CODE_A, "600", 1),
            _allocation_fact(PROJECT_B, PROJECT_CODE_B, "400", 2),
        ),
        payroll_allocations=(
            _payroll_link(first, 1, "CONFIRMED"),
            _payroll_link(second, 2, "CONFIRMED", first),
        ),
        labor_adjustments=(
            _labor_adjustment(
                allocation_id=second,
                project_id=PROJECT_A,
                project_code=PROJECT_CODE_A,
                delta="-100",
                suffix="43",
            ),
            _labor_adjustment(
                allocation_id=second,
                project_id=PROJECT_C,
                project_code=PROJECT_CODE_C,
                delta="100",
                suffix="44",
            ),
        ),
    )

    draft, components = build_direct_allocation_projection(
        _pnl_request(project_id=PROJECT_C, project_code=PROJECT_CODE_C), snapshot
    )

    assert [(item.classification, item.functional_amount) for item in components] == [
        ("LABOR_ADJUSTMENT", Decimal("100.0000"))
    ]
    assert draft.reconciliation_status == "VERIFIED"


def test_projector_keeps_plan_fallback_provisional_and_residual_explicit():
    first = "76500000-0000-4000-8000-000000000030"
    link = replace(
        _payroll_link(first, 1, "PROVISIONAL"),
        allocated_total=Decimal("800.0000"),
        residual_total=Decimal("200.0000"),
    )
    snapshot = ProjectPnlSourceSnapshot(
        pools=(_pool_fact(),),
        allocations=(
            _allocation_fact(PROJECT_A, PROJECT_CODE_A, "480", 1),
            _allocation_fact(PROJECT_B, PROJECT_CODE_B, "320", 2),
        ),
        payroll_allocations=(link,),
    )
    request = ProjectPnlRebuildRequest(
        tenant_id=TENANT,
        company_id=COMPANY_ID,
        project_id=PROJECT_A,
        project_code=PROJECT_CODE_A,
        period_id=PERIOD_ID,
        projection_version=1,
        functional_currency="KRW",
        as_of=NOW,
        evaluated_at=NOW,
    )
    draft, components = build_direct_allocation_projection(request, snapshot)
    assert {item.classification for item in components} == {
        "LABOR_ALLOCATION_PROVISIONAL",
        "POSTED_PAYROLL_UNALLOCATED",
    }
    assert draft.reconciliation_status == "PARTIAL"


def test_projector_rejects_broken_payroll_revision_chain():
    first = "76500000-0000-4000-8000-000000000030"
    broken = replace(
        _payroll_link(
            "76500000-0000-4000-8000-000000000031",
            2,
            "CONFIRMED",
            first,
        ),
        allocation_revision=3,
    )
    snapshot = ProjectPnlSourceSnapshot(
        pools=(_pool_fact(),),
        allocations=(_allocation_fact(PROJECT_A, PROJECT_CODE_A, "1000", 1),),
        payroll_allocations=(
            _payroll_link(first, 1, "PROVISIONAL"),
            broken,
        ),
    )
    request = ProjectPnlRebuildRequest(
        tenant_id=TENANT,
        company_id=COMPANY_ID,
        project_id=PROJECT_A,
        project_code=PROJECT_CODE_A,
        period_id=PERIOD_ID,
        projection_version=1,
        functional_currency="KRW",
        as_of=NOW,
        evaluated_at=NOW,
    )
    with pytest.raises(RuntimeError, match="revision chain"):
        build_direct_allocation_projection(request, snapshot)


def test_projector_payroll_chain_guards_reject_empty_start_and_regression():
    first = "76500000-0000-4000-8000-000000000030"
    with pytest.raises(RuntimeError, match="empty"):
        projector_module._validate_payroll_chain(())
    with pytest.raises(RuntimeError, match="revision one"):
        projector_module._validate_payroll_chain(
            (_payroll_link(first, 2, "PROVISIONAL"),)
        )
    with pytest.raises(RuntimeError, match="regressed"):
        projector_module._validate_payroll_chain(
            (
                _payroll_link(first, 1, "CONFIRMED"),
                _payroll_link(
                    "76500000-0000-4000-8000-000000000031",
                    2,
                    "PROVISIONAL",
                    first,
                ),
            )
        )


@pytest.mark.parametrize("status", ["PROVISIONAL", "CONFIRMED"])
def test_projector_rejects_payroll_project_code_drift(status):
    snapshot = ProjectPnlSourceSnapshot(
        pools=(_pool_fact(),),
        allocations=(_allocation_fact(PROJECT_A, PROJECT_CODE_B, "1000", 1),),
        payroll_allocations=(
            _payroll_link("76500000-0000-4000-8000-000000000030", 1, status),
        ),
    )
    with pytest.raises(RuntimeError, match="Project Code"):
        build_direct_allocation_projection(_pnl_request(), snapshot)


def test_projector_rejects_nonconserving_payroll_and_adjustment_code_drift():
    first = "76500000-0000-4000-8000-000000000030"
    nonconserving = ProjectPnlSourceSnapshot(
        pools=(_pool_fact(),),
        allocations=(_allocation_fact(PROJECT_A, PROJECT_CODE_A, "900", 1),),
        payroll_allocations=(_payroll_link(first, 1, "CONFIRMED"),),
    )
    with pytest.raises(RuntimeError, match="conserve"):
        build_direct_allocation_projection(_pnl_request(), nonconserving)

    second = "76500000-0000-4000-8000-000000000031"
    drifted = ProjectPnlSourceSnapshot(
        pools=(_pool_fact(),),
        allocations=(
            _allocation_fact(PROJECT_A, PROJECT_CODE_A, "600", 1),
            _allocation_fact(PROJECT_B, PROJECT_CODE_B, "400", 2),
        ),
        payroll_allocations=(
            _payroll_link(first, 1, "CONFIRMED"),
            _payroll_link(second, 2, "CONFIRMED", first),
        ),
        labor_adjustments=(
            _labor_adjustment(
                allocation_id=second,
                project_id=PROJECT_A,
                project_code=PROJECT_CODE_B,
                delta="1",
                suffix="41",
            ),
        ),
    )
    with pytest.raises(RuntimeError, match="Project Code"):
        build_direct_allocation_projection(_pnl_request(), drifted)


def test_projector_preserves_zero_allocated_payroll_as_pending_residual():
    first = "76500000-0000-4000-8000-000000000030"
    link = replace(
        _payroll_link(first, 1, "PROVISIONAL"),
        allocated_total=Decimal("0.0000"),
        residual_total=Decimal("1000.0000"),
    )
    snapshot = ProjectPnlSourceSnapshot(
        pools=(_pool_fact(),),
        allocations=(_allocation_fact(PROJECT_A, PROJECT_CODE_A, "0", 1),),
        payroll_allocations=(link,),
    )
    draft, components = build_direct_allocation_projection(_pnl_request(), snapshot)
    assert [item.classification for item in components] == [
        "POSTED_PAYROLL_UNALLOCATED"
    ]
    assert draft.reconciliation_status == "PENDING"


def test_projector_low_level_persistence_guards_and_naive_time_normalization():
    row = {
        "adjustment_id": "76500000-0000-4000-8000-000000000041",
        "payroll_allocation_id": "76500000-0000-4000-8000-000000000030",
        "target_project_id": PROJECT_A,
        "target_project_code": PROJECT_CODE_A,
        "work_code": WORK_A,
        "delta_amount": Decimal("1.0000"),
        "adjustment_kind": "ACTUAL_CORRECTION",
        "adjustment_hash": HASH_A,
        "created_at": NOW,
    }
    with pytest.raises(RuntimeError, match="incomplete"):
        projector_module._labor_adjustment_fact({**row, "payroll_allocation_id": None})
    assert projector_module._labor_adjustment_fact(row).delta_amount == Decimal(
        "1.0000"
    )
    normalized = projector_module._stored_time(
        "created_at",
        datetime(2026, 11, 14, 10, 0),  # noqa: DTZ001
    )
    assert normalized.tzinfo == UTC


def test_migration_head_and_runtime_exports_are_current():
    migrations = load_migrations("nex-eos")
    assert migrations[-1].version == "2545_eos_payroll_project_allocation"
    assert Path(
        "database/nex-eos/migrations/2545_eos_payroll_project_allocation.sql"
    ).is_file()
