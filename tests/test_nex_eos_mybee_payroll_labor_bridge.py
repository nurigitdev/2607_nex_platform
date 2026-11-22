from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from nex_eos import (
    D12_CATALOG_DIGEST,
    D12_CATALOG_ID,
    D12_CATALOG_VERSION,
    EOS_ACCOUNTING_PERIOD_TABLE,
    EOS_COST_SOURCE_POOL_TABLE,
    EOS_LABOR_EFFORT_LINE_TABLE,
    EOS_LABOR_EFFORT_SNAPSHOT_TABLE,
    EOS_LEGAL_ENTITY_TABLE,
    EOS_METADATA,
    EOS_NVT_PROJECT_TABLE,
    EOS_PAYROLL_POST_EVIDENCE_TABLE,
    EOS_PROJECT_COMPANY_BINDING_TABLE,
    EOS_PROJECT_TABLE,
    EOS_PROJECT_WORK_ASSIGNMENT_TABLE,
    EOS_PROJECT_WORK_CODE_ENTRY_TABLE,
    EOS_PROJECT_WORK_CODE_SET_TABLE,
    LABOR_EFFORT_SNAPSHOT_SCHEMA,
    MANDATORY_D12_CODES_HASH,
    PAYROLL_POSTING_EVIDENCE_SCHEMA,
    EosPayrollLaborBridgeError,
    EosPayrollLaborBridgeService,
    LaborEffortLineInput,
    LaborEffortSnapshotInput,
    PayrollPostingEvidenceInput,
    SqlAlchemyEosPayrollLaborBridgeRepository,
    create_eos_app,
)
from nex_eos import payroll_labor_bridge as bridge_module
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from run_migrations import load_migrations
from sqlalchemy import create_engine, func, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

TENANT = "W601"
COMPANY_ID = "76400000-0000-4000-8000-000000000001"
NVT_ID = "76400000-0000-4000-8000-000000000002"
PROJECT_ID = "76400000-0000-4000-8000-000000000003"
PERIOD_ID = "76400000-0000-4000-8000-000000000004"
POOL_ID = "76400000-0000-4000-8000-000000000005"
JOURNAL_ID = "76400000-0000-4000-8000-000000000006"
ACCOUNT_ID = "76400000-0000-4000-8000-000000000007"
OPERATION_ID = "76400000-0000-4000-8000-000000000008"
WORK_SET_ID = "76400000-0000-4000-8000-000000000009"
ASSIGNMENT_ID = "76400000-0000-4000-8000-000000000010"
PROJECT_CODE = "W601D260001"
WORK_CODE = "FL0012004"
NOW = datetime(2026, 11, 14, 9, 0, tzinfo=UTC)
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64


def _runtime():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    _seed(sessions)
    repository = SqlAlchemyEosPayrollLaborBridgeRepository(sessions)
    service = EosPayrollLaborBridgeService(repository, clock=lambda: NOW)
    return engine, sessions, repository, service


def _seed(sessions) -> None:
    with sessions.begin() as session:
        session.execute(
            EOS_LEGAL_ENTITY_TABLE.insert().values(
                tenant_id=TENANT,
                company_id=COMPANY_ID,
                company_code="W601",
                name="W60 Company",
                functional_currency="KRW",
                presentation_currency="KRW",
                business_timezone="Asia/Seoul",
                status="ACTIVE",
                effective_from=date(2026, 1, 1),
                version=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.execute(
            EOS_NVT_PROJECT_TABLE.insert().values(
                tenant_id=TENANT,
                nvt_project_id=NVT_ID,
                nvt_project_code="W601-NVT",
                name="W60 NVT",
                status="ACTIVE",
                version=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.execute(
            EOS_PROJECT_TABLE.insert().values(
                tenant_id=TENANT,
                project_id=PROJECT_ID,
                project_code=PROJECT_CODE,
                project_request_code="W601R260001",
                purpose_type="D",
                origin="APPROVED_APPLICATION",
                approval_evidence_ref="eos.approval:w60-project",
                approval_evidence_hash=HASH_A,
                project_owner_subject_id="owner-w60",
                project_manager_subject_id="pm-w60",
                agent_sync_state="IN_SYNC",
                authorization_sync_state="IN_SYNC",
                authorization_version=1,
                name="W60 Project",
                parent_project_id=None,
                nvt_project_id=NVT_ID,
                hierarchy_depth=1,
                status="ACTIVE",
                start_date=date(2026, 1, 1),
                end_date=None,
                currency="KRW",
                version=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.execute(
            EOS_PROJECT_COMPANY_BINDING_TABLE.insert().values(
                tenant_id=TENANT,
                binding_id=str(uuid.uuid4()),
                project_id=PROJECT_ID,
                company_id=COMPANY_ID,
                valid_from=date(2026, 1, 1),
                valid_until=None,
                approved_proof_hash=HASH_A,
                state="APPROVED",
                version=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )
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
                source_business_operation_id=OPERATION_ID,
                source_project_id=PROJECT_ID,
                source_project_code=PROJECT_CODE,
                source_kind="PAYROLL",
                allocation_mode="MANAGEMENT_ALLOCATION",
                source_amount_functional=Decimal("12000000.0000"),
                eligible_amount_functional=Decimal("12000000.0000"),
                functional_currency="KRW",
                account_id=ACCOUNT_ID,
                account_category="EXPENSE",
                monetary_class="NON_MONETARY",
                recognition_date=date(2026, 11, 14),
                recognized_at=NOW,
                period_id=PERIOD_ID,
                source_record_ref="eos.journal:payroll:line:1",
                source_hash=HASH_A,
                eligibility_policy_hash=HASH_B,
                pool_state="OPEN",
                source_journal_hash=HASH_C,
                created_at=NOW,
            )
        )
        session.execute(
            EOS_PROJECT_WORK_CODE_SET_TABLE.insert().values(
                tenant_id=TENANT,
                project_id=PROJECT_ID,
                work_set_id=WORK_SET_ID,
                revision=1,
                catalog_id=D12_CATALOG_ID,
                catalog_version=D12_CATALOG_VERSION,
                catalog_digest=D12_CATALOG_DIGEST,
                template_ref="mybee.d12.required-five",
                template_version="1.0.0",
                mandatory_codes_hash=MANDATORY_D12_CODES_HASH,
                approved_proof_hash=HASH_A,
                approved_by_subject_id="owner-w60",
                pm_subject_id="pm-w60",
                pa_agent_id="pa-w60",
                pa_identity_evidence_hash=HASH_B,
                state="APPROVED",
                effective_from=date(2026, 1, 1),
                work_set_hash=HASH_C,
                created_at=NOW,
            )
        )
        session.execute(
            EOS_PROJECT_WORK_CODE_ENTRY_TABLE.insert().values(
                tenant_id=TENANT,
                project_id=PROJECT_ID,
                work_set_id=WORK_SET_ID,
                work_set_revision=1,
                work_code_id=WORK_CODE,
                ordinal=1,
                mandatory=True,
            )
        )
        assignment_hash = semantic_sha256_hash_ref(
            {"domain": "W60-S7-02B-ASSIGNMENT", "id": ASSIGNMENT_ID}
        )
        session.execute(
            EOS_PROJECT_WORK_ASSIGNMENT_TABLE.insert().values(
                tenant_id=TENANT,
                assignment_id=ASSIGNMENT_ID,
                project_id=PROJECT_ID,
                work_set_id=WORK_SET_ID,
                work_set_revision=1,
                work_code_id=WORK_CODE,
                performer_kind="HUMAN",
                subject_ref="employee-private",
                performer_authority_hash=HASH_A,
                assignment_scope="EXECUTE",
                planned_man_days=Decimal("12.5000"),
                planned_grade_id="G4",
                grade_policy_ref="mybee.grade-policy:2026.1",
                grade_policy_hash=HASH_B,
                valid_from=date(2026, 11, 1),
                valid_until=date(2026, 11, 30),
                approved_proof_hash=HASH_A,
                approved_by_subject_id="owner-w60",
                assignment_hash=assignment_hash,
                created_at=NOW,
            )
        )


def _payroll(**overrides) -> PayrollPostingEvidenceInput:
    value = PayrollPostingEvidenceInput(
        tenant_id=TENANT,
        company_id=COMPANY_ID,
        payroll_run_id="payroll-run:2026-11",
        payroll_period_start=date(2026, 11, 1),
        payroll_period_end=date(2026, 11, 30),
        revision=1,
        pool_id=POOL_ID,
        payroll_component_class="BASE_SALARY",
        payroll_source_ref="payroll-sor:run:2026-11",
        payroll_source_hash=HASH_A,
        approval_ref="payroll-approval:2026-11",
        approval_hash=HASH_B,
        organization_ref="org:engineering",
    )
    return replace(value, **overrides)


def _actual_line(**overrides) -> LaborEffortLineInput:
    value = LaborEffortLineInput(
        project_id=PROJECT_ID,
        project_code=PROJECT_CODE,
        work_code=WORK_CODE,
        effort_units=Decimal("18.5000"),
        population_count=2,
        minimum_population=3,
        basis_source_ref="work-sor:approved:project-w60",
        basis_source_hash=HASH_A,
        organization_ref="org:engineering",
        grade_band="G4",
        cost_cohort="engineering-g4",
    )
    return replace(value, **overrides)


def _snapshot(**overrides) -> LaborEffortSnapshotInput:
    value = LaborEffortSnapshotInput(
        tenant_id=TENANT,
        company_id=COMPANY_ID,
        effort_period_start=date(2026, 11, 1),
        effort_period_end=date(2026, 11, 30),
        revision=1,
        basis_kind="ACTUAL_APPROVED",
        effort_unit="MAN_DAY",
        source_ref="labor-sor:snapshot:2026-11",
        source_hash=HASH_A,
        evidence_cutoff_at=NOW - timedelta(minutes=1),
        approval_ref="labor-approval:2026-11",
        approval_hash=HASH_B,
        approved_at=NOW,
        lines=(_actual_line(),),
    )
    return replace(value, **overrides)


def _plan_snapshot(**overrides) -> LaborEffortSnapshotInput:
    line = LaborEffortLineInput(
        project_id=PROJECT_ID,
        project_code=PROJECT_CODE,
        work_code=WORK_CODE,
        effort_units=Decimal("12.5000"),
        population_count=1,
        minimum_population=3,
        work_assignment_id=ASSIGNMENT_ID,
    )
    values = {
        "basis_kind": "APPROVED_PLAN_FALLBACK",
        "source_ref": "eos.work-plan:snapshot:2026-11",
        "source_hash": HASH_C,
        "lines": (line,),
    }
    values.update(overrides)
    return _snapshot(**values)


def test_migration_contract_is_additive_private_and_identifier_safe() -> None:
    migration = next(
        item
        for item in load_migrations("nex-eos")
        if item.version == "2544_eos_payroll_labor_bridge"
    )
    compact = " ".join(migration.sql.lower().split())
    for table in (
        "eos_payroll_post_evidence",
        "eos_labor_effort_snapshot",
        "eos_labor_effort_line",
    ):
        assert f"create table if not exists {table}" in compact
    forbidden = {"subject_ref", "employee_id", "salary", "net_pay", "tax_amount"}
    bridge_columns = {
        column.name
        for table in (
            EOS_PAYROLL_POST_EVIDENCE_TABLE,
            EOS_LABOR_EFFORT_SNAPSHOT_TABLE,
            EOS_LABOR_EFFORT_LINE_TABLE,
        )
        for column in table.columns
    }
    assert forbidden.isdisjoint(bridge_columns)
    assert "eos_reject_payroll_labor_mutation" in compact
    assert compact.count("execute function eos_reject_payroll_labor_mutation()") == 3
    assert all(
        constraint.name is None or len(constraint.name) <= 63
        for table in (
            EOS_PAYROLL_POST_EVIDENCE_TABLE,
            EOS_LABOR_EFFORT_SNAPSHOT_TABLE,
            EOS_LABOR_EFFORT_LINE_TABLE,
        )
        for constraint in table.constraints
    )


def test_payroll_posting_evidence_is_source_derived_replayed_and_loaded() -> None:
    engine, sessions, _repository, service = _runtime()
    try:
        created = service.admit_payroll_posting(_payroll())
        replay = service.admit_payroll_posting(_payroll())
        loaded = service.get_payroll_posting(
            tenant_id=TENANT,
            company_id=COMPANY_ID,
            evidence_id=created["evidence_id"],
        )
        assert created["schema_version"] == PAYROLL_POSTING_EVIDENCE_SCHEMA
        assert created["idempotency_disposition"] == "CREATED"
        assert replay["idempotency_disposition"] == "EXACT_REPLAY"
        assert loaded["evidence_hash"] == created["evidence_hash"]
        assert created["journal_id"] == JOURNAL_ID
        assert created["eligible_amount_functional"] == "12000000.0000"
        assert created["privacy_class"] == "PAYROLL_AGGREGATE"
        with sessions() as session:
            assert (
                session.scalar(
                    select(func.count()).select_from(EOS_PAYROLL_POST_EVIDENCE_TABLE)
                )
                == 1
            )
    finally:
        engine.dispose()


def test_payroll_evidence_conflict_and_ineligible_pool_fail_closed() -> None:
    engine, sessions, _repository, service = _runtime()
    try:
        service.admit_payroll_posting(_payroll())
        with pytest.raises(EosPayrollLaborBridgeError) as conflict:
            service.admit_payroll_posting(
                _payroll(payroll_component_class="BONUS_INCENTIVE")
            )
        assert conflict.value.status_code == 409

        for source_kind, state in (("SERVICE", "OPEN"), ("PAYROLL", "ON_HOLD")):
            with sessions.begin() as session:
                session.execute(
                    update(EOS_COST_SOURCE_POOL_TABLE).values(
                        source_kind=source_kind, pool_state=state
                    )
                )
            changed = _payroll(
                payroll_run_id=f"payroll-run:{source_kind}:{state}", revision=2
            )
            with pytest.raises(EosPayrollLaborBridgeError) as rejected:
                service.admit_payroll_posting(changed)
            assert rejected.value.error_code == "EOS_PAYROLL_LABOR_INELIGIBLE"
            with sessions.begin() as session:
                session.execute(
                    update(EOS_COST_SOURCE_POOL_TABLE).values(
                        source_kind="PAYROLL", pool_state="OPEN"
                    )
                )
    finally:
        engine.dispose()


def test_payroll_source_must_exist_and_preserve_expense_currency_semantics() -> None:
    engine, sessions, _repository, service = _runtime()
    try:
        with pytest.raises(EosPayrollLaborBridgeError) as missing:
            service.admit_payroll_posting(_payroll(pool_id=str(uuid.uuid4())))
        assert missing.value.status_code == 404

        with sessions() as session:
            pool = dict(
                session.execute(select(EOS_COST_SOURCE_POOL_TABLE)).mappings().one()
            )
        for field, value in (
            ("account_category", "LIABILITY"),
            ("functional_currency", "bad"),
        ):
            invalid_pool = {**pool, field: value}
            with pytest.raises(EosPayrollLaborBridgeError) as rejected:
                bridge_module._build_payroll_record(_payroll(), invalid_pool, NOW)
            assert rejected.value.status_code == 409
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "value",
    (
        "not-typed",
        _payroll(tenant_id="bad tenant"),
        _payroll(company_id="not-a-uuid"),
        _payroll(payroll_period_end=date(2026, 10, 31)),
        _payroll(revision=0),
        _payroll(pool_id="bad"),
        _payroll(payroll_component_class="NET_PAY"),
        _payroll(payroll_source_hash="bad"),
        _payroll(organization_ref="bad ref with spaces"),
    ),
)
def test_invalid_payroll_contract_is_rejected(value) -> None:
    engine, _sessions, _repository, service = _runtime()
    try:
        with pytest.raises(EosPayrollLaborBridgeError) as error:
            service.admit_payroll_posting(value)
        assert error.value.status_code == 422
    finally:
        engine.dispose()


def test_actual_labor_snapshot_is_sorted_suppressed_replayed_and_loaded() -> None:
    engine, sessions, _repository, service = _runtime()
    try:
        created = service.admit_labor_effort(_snapshot())
        replay = service.admit_labor_effort(_snapshot())
        loaded = service.get_labor_effort(
            tenant_id=TENANT,
            company_id=COMPANY_ID,
            snapshot_id=created["snapshot_id"],
        )
        assert created["schema_version"] == LABOR_EFFORT_SNAPSHOT_SCHEMA
        assert created["idempotency_disposition"] == "CREATED"
        assert replay["idempotency_disposition"] == "EXACT_REPLAY"
        assert loaded["snapshot_hash"] == created["snapshot_hash"]
        assert created["lines"][0]["ordinary_view_suppressed"] is True
        assert created["lines"][0]["work_assignment_id"] is None
        with sessions() as session:
            assert (
                session.scalar(
                    select(func.count()).select_from(EOS_LABOR_EFFORT_SNAPSHOT_TABLE)
                )
                == 1
            )
            assert (
                session.scalar(
                    select(func.count()).select_from(EOS_LABOR_EFFORT_LINE_TABLE)
                )
                == 1
            )
    finally:
        engine.dispose()


def test_actual_effort_allows_project_level_rollup_without_work_code() -> None:
    engine, _sessions, _repository, service = _runtime()
    try:
        project_level = replace(
            _actual_line(),
            work_code=None,
            population_count=4,
            minimum_population=3,
            basis_source_ref="work-sor:approved:project-level",
        )
        created = service.admit_labor_effort(
            _snapshot(
                revision=2,
                source_ref="labor-sor:snapshot:project-level",
                lines=(project_level,),
            )
        )
        assert created["lines"][0]["work_code"] is None
        assert created["lines"][0]["ordinary_view_suppressed"] is False
    finally:
        engine.dispose()


def test_plan_fallback_is_bound_to_approved_assignment_not_membership() -> None:
    engine, _sessions, _repository, service = _runtime()
    try:
        created = service.admit_labor_effort(_plan_snapshot())
        line = created["lines"][0]
        assert created["basis_kind"] == "APPROVED_PLAN_FALLBACK"
        assert line["effort_units"] == "12.5000"
        assert line["basis_source_ref"] == f"eos.work-assignment:{ASSIGNMENT_ID}"
        assert line["grade_band"] == "G4"
        assert line["ordinary_view_suppressed"] is True

        invalid_lines = (
            replace(_plan_snapshot().lines[0], effort_units=Decimal("12.0000")),
            replace(_plan_snapshot().lines[0], work_assignment_id=None),
            replace(_plan_snapshot().lines[0], work_code="FL0012005"),
        )
        for index, line in enumerate(invalid_lines, start=2):
            with pytest.raises(EosPayrollLaborBridgeError) as rejected:
                service.admit_labor_effort(
                    _plan_snapshot(revision=index, lines=(line,))
                )
            assert rejected.value.status_code in {409, 422}
    finally:
        engine.dispose()


def test_actual_plan_semantics_and_snapshot_conflict_fail_closed() -> None:
    engine, _sessions, _repository, service = _runtime()
    try:
        actual_with_assignment = replace(
            _actual_line(), work_assignment_id=ASSIGNMENT_ID
        )
        with pytest.raises(EosPayrollLaborBridgeError) as disguised:
            service.admit_labor_effort(_snapshot(lines=(actual_with_assignment,)))
        assert disguised.value.status_code == 422

        with pytest.raises(EosPayrollLaborBridgeError) as unit:
            service.admit_labor_effort(_plan_snapshot(effort_unit="HOUR", revision=2))
        assert unit.value.status_code == 422

        service.admit_labor_effort(_snapshot())
        changed_line = replace(_actual_line(), effort_units=Decimal("19.0000"))
        with pytest.raises(EosPayrollLaborBridgeError) as conflict:
            service.admit_labor_effort(_snapshot(lines=(changed_line,)))
        assert conflict.value.status_code == 409
    finally:
        engine.dispose()


def test_effort_duplicate_and_plan_lineage_mismatch_are_rejected() -> None:
    engine, _sessions, _repository, service = _runtime()
    try:
        duplicate = _actual_line()
        with pytest.raises(EosPayrollLaborBridgeError) as duplicated:
            service.admit_labor_effort(_snapshot(lines=(duplicate, duplicate)))
        assert duplicated.value.status_code == 422

        plan = _plan_snapshot().lines[0]
        mismatches = (
            replace(plan, basis_source_ref="eos.work-assignment:wrong"),
            replace(plan, basis_source_hash=HASH_A),
            replace(plan, grade_band="G9"),
        )
        for index, line in enumerate(mismatches, start=10):
            with pytest.raises(EosPayrollLaborBridgeError) as mismatch:
                service.admit_labor_effort(
                    _plan_snapshot(
                        revision=index,
                        source_ref=f"eos.work-plan:snapshot:{index}",
                        lines=(line,),
                    )
                )
            assert mismatch.value.status_code == 422
    finally:
        engine.dispose()


def test_project_company_and_lifecycle_authority_fail_closed() -> None:
    engine, sessions, _repository, service = _runtime()
    try:
        invalid_lines = (
            replace(_actual_line(), project_code="W601M260001"),
            replace(_actual_line(), project_id=str(uuid.uuid4())),
        )
        for index, line in enumerate(invalid_lines, start=2):
            with pytest.raises(EosPayrollLaborBridgeError) as rejected:
                service.admit_labor_effort(
                    _snapshot(
                        revision=index, source_ref=f"labor-sor:{index}", lines=(line,)
                    )
                )
            assert rejected.value.status_code == 409

        with sessions.begin() as session:
            session.execute(
                update(EOS_PROJECT_TABLE)
                .where(EOS_PROJECT_TABLE.c.project_id == PROJECT_ID)
                .values(status="INACTIVE")
            )
        with pytest.raises(EosPayrollLaborBridgeError) as inactive:
            service.admit_labor_effort(
                _snapshot(revision=4, source_ref="labor-sor:inactive")
            )
        assert inactive.value.status_code == 409
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "value",
    (
        "not-typed",
        _snapshot(tenant_id="bad tenant"),
        _snapshot(company_id="bad"),
        _snapshot(effort_period_start=NOW),
        _snapshot(effort_period_end=NOW),
        _snapshot(effort_period_end=date(2026, 10, 31)),
        _snapshot(revision=True),
        _snapshot(basis_kind="MEMBERSHIP"),
        _snapshot(effort_unit="PERSON"),
        _snapshot(source_hash="bad"),
        _snapshot(evidence_cutoff_at=NOW.replace(tzinfo=None)),
        _snapshot(approved_at=NOW.replace(tzinfo=None)),
        _snapshot(approved_at=NOW - timedelta(minutes=2)),
        _snapshot(lines=()),
        _snapshot(lines="bad"),
        _snapshot(lines=("bad",)),
        _snapshot(lines=(replace(_actual_line(), effort_units=Decimal(0)),)),
        _snapshot(lines=(replace(_actual_line(), effort_units=Decimal(-1)),)),
        _snapshot(lines=(replace(_actual_line(), effort_units=Decimal("NaN")),)),
        _snapshot(lines=(replace(_actual_line(), effort_units="bad"),)),
        _snapshot(lines=(replace(_actual_line(), effort_units=Decimal("1.00001")),)),
        _snapshot(lines=(replace(_actual_line(), population_count=0),)),
        _snapshot(lines=(replace(_actual_line(), population_count="bad"),)),
        _snapshot(lines=(replace(_actual_line(), grade_band=""),)),
        _snapshot(lines=(replace(_actual_line(), cost_cohort="x" * 65),)),
        _snapshot(lines=(replace(_actual_line(), project_code="bad"),)),
        _snapshot(lines=(replace(_actual_line(), work_code="bad"),)),
    ),
)
def test_invalid_effort_contract_is_rejected(value) -> None:
    engine, _sessions, _repository, service = _runtime()
    try:
        with pytest.raises(EosPayrollLaborBridgeError) as error:
            service.admit_labor_effort(value)
        assert error.value.status_code in {409, 422}
    finally:
        engine.dispose()


def test_missing_reads_and_persistence_failures_are_typed() -> None:
    engine, _sessions, _repository, service = _runtime()
    try:
        for loader, identity_name in (
            (service.get_payroll_posting, "evidence_id"),
            (service.get_labor_effort, "snapshot_id"),
        ):
            with pytest.raises(EosPayrollLaborBridgeError) as missing:
                loader(
                    tenant_id=TENANT,
                    company_id=COMPANY_ID,
                    **{identity_name: str(uuid.uuid4())},
                )
            assert missing.value.status_code == 404
    finally:
        engine.dispose()

    class BrokenFactory:
        def begin(self):
            raise SQLAlchemyError("offline")

    broken = EosPayrollLaborBridgeService(
        SqlAlchemyEosPayrollLaborBridgeRepository(BrokenFactory()), clock=lambda: NOW
    )
    with pytest.raises(EosPayrollLaborBridgeError) as unavailable:
        broken.admit_payroll_posting(_payroll())
    assert unavailable.value.status_code == 503
    assert unavailable.value.retryable is True

    naive_engine, naive_sessions, _repository, _service = _runtime()
    try:
        naive_clock = EosPayrollLaborBridgeService(
            SqlAlchemyEosPayrollLaborBridgeRepository(naive_sessions),
            clock=lambda: NOW.replace(tzinfo=None),
        )
        with pytest.raises(EosPayrollLaborBridgeError) as naive:
            naive_clock.admit_payroll_posting(_payroll())
        assert naive.value.status_code == 422
    finally:
        naive_engine.dispose()

    with pytest.raises(EosPayrollLaborBridgeError):
        bridge_module._wire_time("not-a-datetime")


def test_repository_race_replay_and_read_failure_paths_are_typed() -> None:
    engine, _sessions, repository, service = _runtime()
    cause = IntegrityError("insert", {}, RuntimeError("race"))
    try:
        payroll = service.admit_payroll_posting(_payroll())
        effort = service.admit_labor_effort(_snapshot())
        replay, created = repository._payroll_race_replay(_payroll(), NOW, cause)
        assert created is False
        assert replay["evidence_id"] == payroll["evidence_id"]
        header, lines, created = repository._snapshot_race_replay(
            _snapshot(), NOW, cause
        )
        assert created is False
        assert header["snapshot_id"] == effort["snapshot_id"]
        assert len(lines) == 1

        with pytest.raises(EosPayrollLaborBridgeError) as missing_payroll_race:
            repository._payroll_race_replay(
                _payroll(revision=2, payroll_run_id="payroll-run:missing"),
                NOW,
                cause,
            )
        assert missing_payroll_race.value.status_code == 503
        with pytest.raises(EosPayrollLaborBridgeError) as missing_effort_race:
            repository._snapshot_race_replay(
                _snapshot(revision=2, source_ref="labor-sor:missing"), NOW, cause
            )
        assert missing_effort_race.value.status_code == 503

        for loader, identity_name in (
            (repository.get_payroll_evidence, "evidence_id"),
            (repository.get_effort_snapshot, "snapshot_id"),
        ):
            with pytest.raises(EosPayrollLaborBridgeError) as invalid_identity:
                loader(
                    tenant_id="bad tenant",
                    company_id=COMPANY_ID,
                    **{identity_name: str(uuid.uuid4())},
                )
            assert invalid_identity.value.status_code == 422
    finally:
        engine.dispose()

    class BrokenReadFactory:
        def __call__(self):
            raise SQLAlchemyError("offline")

    broken = SqlAlchemyEosPayrollLaborBridgeRepository(BrokenReadFactory())
    for loader, identity_name in (
        (broken.get_payroll_evidence, "evidence_id"),
        (broken.get_effort_snapshot, "snapshot_id"),
    ):
        with pytest.raises(EosPayrollLaborBridgeError) as unavailable:
            loader(
                tenant_id=TENANT,
                company_id=COMPANY_ID,
                **{identity_name: str(uuid.uuid4())},
            )
        assert unavailable.value.status_code == 503


def test_runtime_wires_bridge_only_with_database_configuration() -> None:
    app = create_eos_app(environ={"NEX_PROFILE": "test"})
    assert app.state.eos_payroll_labor_bridge_service is None
    assert app.version

    configured = create_eos_app(
        environ={
            "NEX_PROFILE": "test",
            "NEX_EOS_DATABASE_URL": "sqlite+pysqlite:///:memory:",
        }
    )
    assert configured.state.eos_payroll_labor_bridge_service is not None
    configured.state.eos_database_runtime.engine.dispose()


def test_migration_head_manifest_will_reference_bridge() -> None:
    migration_path = Path(
        "database/nex-eos/migrations/2544_eos_payroll_labor_bridge.sql"
    )
    assert migration_path.exists()
    assert migration_path.read_text(encoding="utf-8").strip().endswith("COMMIT;")
