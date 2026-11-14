from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
import test_nex_eos_mybee_project_pnl as persistence_fixture
from nex_eos import (
    EOS_COST_ALLOCATION_ADJUSTMENT_TABLE,
    EOS_COST_ALLOCATION_BATCH_TABLE,
    EOS_COST_ALLOCATION_LINE_TABLE,
    EOS_COST_SOURCE_POOL_TABLE,
    EOS_LABOR_EFFORT_SNAPSHOT_TABLE,
    EOS_PAYROLL_POST_EVIDENCE_TABLE,
    EOS_PAYROLL_PROJECT_ALLOCATION_TABLE,
    EosProjectPnlProjector,
    EosProjectPnlProjectorError,
    ProjectPnlAllocationFact,
    ProjectPnlRebuildRequest,
    ProjectPnlSourcePoolFact,
    ProjectPnlSourceSnapshot,
    SqlAlchemyEosProjectPnlProjectionSource,
    build_direct_allocation_projection,
    build_eos_project_pnl_projector,
    build_project_pnl_records,
    create_eos_app,
)
from nex_eos import project_pnl_projector as projector_module
from sqlalchemy.exc import OperationalError

NOW = persistence_fixture.NOW
TENANT = persistence_fixture.TENANT
COMPANY_ID = persistence_fixture.COMPANY_ID
PROJECT_ID = persistence_fixture.PROJECT_ID
PROJECT_CODE = "W601D260001"
PERIOD_ID = persistence_fixture.PERIOD_ID
ACCOUNT_ID = persistence_fixture.ACCOUNT_ID
HASH_A = persistence_fixture.HASH_A
HASH_B = persistence_fixture.HASH_B


def _request(**overrides) -> ProjectPnlRebuildRequest:
    value = ProjectPnlRebuildRequest(
        tenant_id=TENANT,
        company_id=COMPANY_ID,
        project_id=PROJECT_ID,
        project_code=PROJECT_CODE,
        period_id=PERIOD_ID,
        projection_version=1,
        functional_currency="KRW",
        as_of=NOW,
        evaluated_at=NOW + timedelta(seconds=30),
        stale_after_seconds=120,
    )
    return replace(value, **overrides)


def _pool(
    suffix: int,
    *,
    source_kind: str = "SERVICE",
    allocation_mode: str = "DIRECT",
    amount: str = "100.0000",
    account_category: str = "EXPENSE",
    source_project_id: str = PROJECT_ID,
    source_project_code: str = PROJECT_CODE,
    pool_state: str | None = None,
    currency: str = "KRW",
) -> ProjectPnlSourcePoolFact:
    return ProjectPnlSourcePoolFact(
        pool_id=f"76000000-0000-4000-8000-{suffix:012d}",
        journal_id=f"76100000-0000-4000-8000-{suffix:012d}",
        journal_line_no=suffix,
        source_project_id=source_project_id,
        source_project_code=source_project_code,
        source_kind=source_kind,
        allocation_mode=allocation_mode,
        eligible_amount_functional=Decimal(amount),
        functional_currency=currency,
        account_id=ACCOUNT_ID,
        account_category=account_category,
        source_record_ref=f"eos.journal:line:{suffix}",
        source_hash="sha256:" + f"{suffix % 10}" * 64,
        source_journal_hash="sha256:" + f"{(suffix + 1) % 10}" * 64,
        pool_state=(
            pool_state
            if pool_state is not None
            else "ALLOCATED"
            if allocation_mode == "DIRECT"
            else "OPEN"
        ),
        recognized_at=NOW - timedelta(seconds=suffix),
    )


def _allocation(
    pool: ProjectPnlSourcePoolFact,
    *,
    line_no: int = 1,
    amount: str = "300.0000",
    project_id: str = PROJECT_ID,
    project_code: str = PROJECT_CODE,
    allocation_mode: str = "MANAGEMENT_ALLOCATION",
    work_code: str | None = "FL0004001",
) -> ProjectPnlAllocationFact:
    return ProjectPnlAllocationFact(
        batch_id="76200000-0000-4000-8000-000000000001",
        line_no=line_no,
        pool_id=pool.pool_id,
        project_id=project_id,
        project_code=project_code,
        work_code=work_code,
        allocated_amount_functional=Decimal(amount),
        allocation_mode=allocation_mode,
        evidence_hash=HASH_A,
        reconciliation_hash=HASH_B,
        committed_at=NOW - timedelta(seconds=1),
    )


def _snapshot() -> ProjectPnlSourceSnapshot:
    revenue = _pool(
        1,
        source_kind="REVENUE",
        amount="1000.0000",
        account_category="REVENUE",
    )
    direct = _pool(2, amount="100.0000")
    shared = _pool(
        3,
        source_kind="SHARED_EXPENSE",
        allocation_mode="MANAGEMENT_ALLOCATION",
        amount="400.0000",
        pool_state="ALLOCATED",
    )
    return ProjectPnlSourceSnapshot(
        pools=(shared, direct, revenue),
        allocations=(_allocation(shared),),
    )


def test_projection_is_deterministic_and_conserves_direct_allocation_residual() -> None:
    draft, components = build_direct_allocation_projection(_request(), _snapshot())
    repeated = build_direct_allocation_projection(_request(), _snapshot())
    assert (draft, components) == repeated
    assert draft.reconciliation_status == "PARTIAL"
    assert draft.freshness_status == "CURRENT"
    assert draft.staleness_seconds == 30
    assert draft.posting_watermark.startswith("sha256:")
    assert draft.allocation_watermark.startswith("sha256:")
    assert [item.classification for item in components] == [
        "POSTED_ALLOCATED_COST",
        "POSTED_DIRECT_COST",
        "POSTED_REVENUE",
        "UNALLOCATED",
    ]
    header, lines = build_project_pnl_records(draft, components)
    assert header["posted_revenue"] == Decimal("1000.0000")
    assert header["posted_direct_cost"] == Decimal("100.0000")
    assert header["posted_allocated_cost"] == Decimal("300.0000")
    assert header["operating_unallocated_cost"] == Decimal("100.0000")
    assert header["posted_operating_result"] == Decimal("600.0000")
    assert len(lines) == 4


def test_pending_stale_projection_keeps_full_residual_visible() -> None:
    pool = _pool(
        4,
        allocation_mode="MANAGEMENT_ALLOCATION",
        amount="200.0000",
        pool_state="OPEN",
    )
    draft, components = build_direct_allocation_projection(
        _request(evaluated_at=NOW + timedelta(seconds=121)),
        ProjectPnlSourceSnapshot((pool,), ()),
    )
    assert draft.reconciliation_status == "PENDING"
    assert draft.freshness_status == "STALE"
    assert draft.staleness_seconds == 121
    assert [(item.classification, item.functional_amount) for item in components] == [
        ("UNALLOCATED", Decimal("200.0000"))
    ]


def test_payroll_and_fx_classification_preserve_privacy_and_sign() -> None:
    payroll = _pool(
        5,
        source_kind="PAYROLL",
        allocation_mode="MANAGEMENT_ALLOCATION",
        amount="500.0000",
        pool_state="ALLOCATED",
    )
    fx_loss = _pool(
        6,
        source_kind="FX_GAIN_LOSS",
        amount="20.0000",
        account_category="EXPENSE",
    )
    draft, components = build_direct_allocation_projection(
        _request(),
        ProjectPnlSourceSnapshot(
            (payroll, fx_loss), (_allocation(payroll, amount="450.0000"),)
        ),
    )
    by_class = {item.classification: item for item in components}
    assert by_class["POSTED_LABOR_ALLOCATED"].data_classification == (
        "PAYROLL_SENSITIVE"
    )
    assert by_class["POSTED_PAYROLL_UNALLOCATED"].functional_amount == Decimal(
        "50.0000"
    )
    assert by_class["FX_REALIZED_GAIN_LOSS"].functional_amount == Decimal("-20.0000")
    assert draft.reconciliation_status == "PARTIAL"


def test_negative_reversal_sources_reduce_confirmed_totals() -> None:
    revenue_reversal = _pool(
        7,
        source_kind="REVENUE",
        amount="-30.0000",
        account_category="REVENUE",
    )
    cost_reversal = _pool(8, amount="-10.0000")
    draft, components = build_direct_allocation_projection(
        _request(), ProjectPnlSourceSnapshot((revenue_reversal, cost_reversal), ())
    )
    header, _lines = build_project_pnl_records(draft, components)
    assert header["posted_revenue"] == Decimal("-30.0000")
    assert header["posted_direct_cost"] == Decimal("-10.0000")
    assert header["posted_operating_result"] == Decimal("-20.0000")


@pytest.mark.parametrize(
    ("rebuild_request", "snapshot", "code"),
    [
        (
            _request(),
            ProjectPnlSourceSnapshot((), (_allocation(_pool(9)),)),
            "PROJECT_PNL_SOURCE_DRIFT",
        ),
        (
            _request(),
            ProjectPnlSourceSnapshot(
                (
                    _pool(
                        10,
                        allocation_mode="MANAGEMENT_ALLOCATION",
                        amount="100.0000",
                        pool_state="OPEN",
                    ),
                ),
                (
                    _allocation(
                        _pool(
                            10,
                            allocation_mode="MANAGEMENT_ALLOCATION",
                            amount="100.0000",
                            pool_state="OPEN",
                        ),
                        amount="50.0000",
                    ),
                ),
            ),
            "PROJECT_PNL_SOURCE_DRIFT",
        ),
        (
            _request(),
            ProjectPnlSourceSnapshot(
                (
                    _pool(
                        11,
                        allocation_mode="MANAGEMENT_ALLOCATION",
                        pool_state="ALLOCATED",
                    ),
                ),
                (),
            ),
            "PROJECT_PNL_SOURCE_DRIFT",
        ),
        (
            _request(),
            ProjectPnlSourceSnapshot((_pool(12, currency="USD"),), ()),
            "PROJECT_PNL_REBUILD_BLOCKED",
        ),
        (
            _request(),
            ProjectPnlSourceSnapshot(
                (_pool(13, source_project_code="W601M260001"),), ()
            ),
            "PROJECT_PNL_SOURCE_DRIFT",
        ),
    ],
)
def test_source_drift_and_authority_mismatch_fail_closed(
    rebuild_request, snapshot, code
) -> None:
    with pytest.raises(EosProjectPnlProjectorError) as error:
        build_direct_allocation_projection(rebuild_request, snapshot)
    assert error.value.error_code == code


def test_overallocation_and_unsupported_modes_fail_closed() -> None:
    pool = _pool(
        14,
        allocation_mode="MANAGEMENT_ALLOCATION",
        amount="100.0000",
        pool_state="ALLOCATED",
    )
    with pytest.raises(EosProjectPnlProjectorError) as overallocated:
        build_direct_allocation_projection(
            _request(),
            ProjectPnlSourceSnapshot((pool,), (_allocation(pool, amount="101"),)),
        )
    assert overallocated.value.retryable is True

    with pytest.raises(EosProjectPnlProjectorError) as unsupported:
        build_direct_allocation_projection(
            _request(),
            ProjectPnlSourceSnapshot(
                (pool,),
                (_allocation(pool, amount="100", allocation_mode="GL_COST_TRANSFER"),),
            ),
        )
    assert unsupported.value.error_code == "PROJECT_PNL_REBUILD_BLOCKED"


def test_full_allocation_unrelated_target_on_hold_and_negative_guards() -> None:
    full = _pool(
        15,
        allocation_mode="MANAGEMENT_ALLOCATION",
        amount="100.0000",
        pool_state="ALLOCATED",
    )
    draft, components = build_direct_allocation_projection(
        _request(),
        ProjectPnlSourceSnapshot((full,), (_allocation(full, amount="100"),)),
    )
    assert draft.reconciliation_status == "VERIFIED"
    assert all(item.classification != "UNALLOCATED" for item in components)

    other_project = str(uuid.uuid4())
    draft, components = build_direct_allocation_projection(
        _request(),
        ProjectPnlSourceSnapshot(
            (full,),
            (
                _allocation(
                    full,
                    amount="60",
                    project_id=other_project,
                    project_code="W601D260002",
                ),
            ),
        ),
    )
    assert draft.reconciliation_status == "PARTIAL"
    assert [item.functional_amount for item in components] == [Decimal("40.0000")]

    on_hold = _pool(
        16,
        allocation_mode="MANAGEMENT_ALLOCATION",
        amount="100.0000",
        pool_state="ON_HOLD",
    )
    draft, _components = build_direct_allocation_projection(
        _request(), ProjectPnlSourceSnapshot((on_hold,), ())
    )
    assert draft.reconciliation_status == "BLOCKED"

    negative = _pool(
        17,
        allocation_mode="MANAGEMENT_ALLOCATION",
        amount="-100.0000",
        pool_state="ALLOCATED",
    )
    with pytest.raises(EosProjectPnlProjectorError) as negative_overallocation:
        build_direct_allocation_projection(
            _request(),
            ProjectPnlSourceSnapshot(
                (negative,), (_allocation(negative, amount="-101"),)
            ),
        )
    assert negative_overallocation.value.retryable is True


def test_project_code_mode_and_direct_pool_allocation_drift_are_rejected() -> None:
    managed = _pool(
        18,
        allocation_mode="MANAGEMENT_ALLOCATION",
        pool_state="ALLOCATED",
    )
    with pytest.raises(EosProjectPnlProjectorError) as code_mismatch:
        build_direct_allocation_projection(
            _request(),
            ProjectPnlSourceSnapshot(
                (managed,),
                (_allocation(managed, project_code="W601M260002", amount="100"),),
            ),
        )
    assert code_mismatch.value.retryable is True

    gl_transfer = _pool(19, allocation_mode="GL_COST_TRANSFER")
    draft, components = build_direct_allocation_projection(
        _request(), ProjectPnlSourceSnapshot((gl_transfer,), ())
    )
    assert draft.reconciliation_status == "BLOCKED"
    assert components == ()

    direct = _pool(22)
    with pytest.raises(EosProjectPnlProjectorError) as invalid_allocation:
        build_direct_allocation_projection(
            _request(),
            ProjectPnlSourceSnapshot((direct,), (_allocation(direct, amount="50"),)),
        )
    assert invalid_allocation.value.retryable is True


@pytest.mark.parametrize(
    "rebuild_request",
    [
        _request(as_of=NOW.replace(tzinfo=None)),
        _request(evaluated_at=NOW.replace(tzinfo=None)),
        _request(evaluated_at=NOW - timedelta(seconds=1)),
        _request(projection_version=0),
        _request(projection_version=True),
        _request(projection_version="bad"),
        _request(stale_after_seconds=-1),
        _request(stale_after_seconds=True),
        _request(stale_after_seconds="bad"),
    ],
)
def test_invalid_rebuild_request_is_rejected(rebuild_request) -> None:
    with pytest.raises(EosProjectPnlProjectorError) as error:
        build_direct_allocation_projection(
            rebuild_request, ProjectPnlSourceSnapshot((), ())
        )
    assert error.value.error_code == "PROJECT_PNL_REBUILD_INVALID"
    assert error.value.status_code == 400


def _insert_pool(session, pool: ProjectPnlSourcePoolFact) -> None:
    session.execute(
        EOS_COST_SOURCE_POOL_TABLE.insert().values(
            tenant_id=TENANT,
            company_id=COMPANY_ID,
            pool_id=pool.pool_id,
            journal_id=pool.journal_id,
            journal_line_no=pool.journal_line_no,
            eligible_component_id=f"ACCOUNT:{pool.account_id}",
            source_business_operation_id=str(uuid.uuid4()),
            source_project_id=pool.source_project_id,
            source_project_code=pool.source_project_code,
            source_kind=pool.source_kind,
            allocation_mode=pool.allocation_mode,
            source_amount_functional=pool.eligible_amount_functional,
            eligible_amount_functional=pool.eligible_amount_functional,
            functional_currency=pool.functional_currency,
            account_id=pool.account_id,
            account_category=pool.account_category,
            monetary_class="NON_MONETARY",
            recognition_date=NOW.date(),
            recognized_at=pool.recognized_at,
            period_id=PERIOD_ID,
            source_record_ref=pool.source_record_ref,
            source_hash=pool.source_hash,
            eligibility_policy_hash=HASH_A,
            pool_state=pool.pool_state,
            source_journal_hash=pool.source_journal_hash,
            created_at=pool.recognized_at,
        )
    )


def test_sql_source_and_projector_persist_exact_rebuild() -> None:
    runtime = persistence_fixture._runtime()
    EOS_COST_SOURCE_POOL_TABLE.create(runtime.engine)
    EOS_COST_ALLOCATION_BATCH_TABLE.create(runtime.engine)
    EOS_COST_ALLOCATION_LINE_TABLE.create(runtime.engine)
    EOS_PAYROLL_POST_EVIDENCE_TABLE.create(runtime.engine)
    EOS_LABOR_EFFORT_SNAPSHOT_TABLE.create(runtime.engine)
    EOS_PAYROLL_PROJECT_ALLOCATION_TABLE.create(runtime.engine)
    EOS_COST_ALLOCATION_ADJUSTMENT_TABLE.create(runtime.engine)
    shared = _pool(
        20,
        allocation_mode="MANAGEMENT_ALLOCATION",
        amount="400.0000",
        pool_state="ALLOCATED",
    )
    direct = _pool(21, amount="125.0000")
    allocation = _allocation(shared, amount="300.0000")
    try:
        with runtime.sessions.begin() as session:
            _insert_pool(session, shared)
            _insert_pool(session, direct)
            session.execute(
                EOS_COST_ALLOCATION_BATCH_TABLE.insert().values(
                    tenant_id=TENANT,
                    company_id=COMPANY_ID,
                    batch_id=allocation.batch_id,
                    plan_id=str(uuid.uuid4()),
                    plan_revision=1,
                    period_id=PERIOD_ID,
                    source_set_hash=HASH_A,
                    functional_currency="KRW",
                    state="COMMITTED",
                    allocated_total=Decimal("300.0000"),
                    unallocated_total=Decimal("100.0000"),
                    reconciliation_hash=allocation.reconciliation_hash,
                    business_operation_id=str(uuid.uuid4()),
                    idempotency_key="w60-s7-02a",
                    outbox_event_id=str(uuid.uuid4()),
                    committed_at=allocation.committed_at,
                    created_at=allocation.committed_at,
                )
            )
            session.execute(
                EOS_COST_ALLOCATION_LINE_TABLE.insert().values(
                    tenant_id=TENANT,
                    company_id=COMPANY_ID,
                    batch_id=allocation.batch_id,
                    line_no=allocation.line_no,
                    pool_id=allocation.pool_id,
                    project_id=allocation.project_id,
                    project_code=allocation.project_code,
                    work_code=allocation.work_code,
                    basis_source_ref="eos.evidence:w60",
                    basis_source_hash=HASH_A,
                    basis_units=Decimal("1.0"),
                    allocation_ratio=Decimal("0.75"),
                    allocated_amount_functional=allocation.allocated_amount_functional,
                    rounding_delta=Decimal(0),
                    allocation_mode=allocation.allocation_mode,
                    original_source_line_ref="eos.journal:w60:line:20",
                    evidence_hash=allocation.evidence_hash,
                    status="ALLOCATED",
                )
            )
        projector = EosProjectPnlProjector(
            source=SqlAlchemyEosProjectPnlProjectionSource(runtime.sessions),
            sink=runtime.repository,
        )
        created = projector.rebuild(_request())
        replay = projector.rebuild(_request())
        assert replay == created
        assert created["posted_direct_cost"] == "125.0000"
        assert created["posted_allocated_cost"] == "300.0000"
        assert created["operating_unallocated_cost"] == "100.0000"
        assert created["reconciliation_status"] == "PARTIAL"
    finally:
        runtime.engine.dispose()


def test_duplicate_snapshot_and_direct_state_are_rejected() -> None:
    direct = _pool(23)
    with pytest.raises(EosProjectPnlProjectorError) as duplicate_pool:
        build_direct_allocation_projection(
            _request(), ProjectPnlSourceSnapshot((direct, direct), ())
        )
    assert duplicate_pool.value.retryable is True

    managed = _pool(
        24,
        allocation_mode="MANAGEMENT_ALLOCATION",
        pool_state="ALLOCATED",
    )
    allocation = _allocation(managed, amount="100")
    with pytest.raises(EosProjectPnlProjectorError) as duplicate_allocation:
        build_direct_allocation_projection(
            _request(),
            ProjectPnlSourceSnapshot((managed,), (allocation, allocation)),
        )
    assert duplicate_allocation.value.retryable is True

    invalid_direct = replace(direct, pool_state="OPEN")
    with pytest.raises(EosProjectPnlProjectorError) as direct_state:
        build_direct_allocation_projection(
            _request(), ProjectPnlSourceSnapshot((invalid_direct,), ())
        )
    assert direct_state.value.retryable is True


class _BrokenFactory:
    def __call__(self):
        raise OperationalError("select", {}, RuntimeError("offline"))


def test_sql_source_maps_database_failure_to_retryable_error() -> None:
    source = SqlAlchemyEosProjectPnlProjectionSource(_BrokenFactory())
    with pytest.raises(EosProjectPnlProjectorError) as error:
        source.load(_request())
    assert error.value.error_code == "PROJECT_PNL_SOURCE_UNAVAILABLE"
    assert error.value.retryable is True
    assert error.value.status_code == 503


class _ProjectorErrorFactory:
    def __call__(self):
        raise EosProjectPnlProjectorError(
            "PROJECT_PNL_SOURCE_DRIFT", "drift", status_code=503, retryable=True
        )


def test_source_preserves_typed_error_and_rejects_malformed_stored_time() -> None:
    source = SqlAlchemyEosProjectPnlProjectionSource(_ProjectorErrorFactory())
    with pytest.raises(EosProjectPnlProjectorError) as error:
        source.load(_request())
    assert error.value.error_code == "PROJECT_PNL_SOURCE_DRIFT"
    with pytest.raises(EosProjectPnlProjectorError) as malformed:
        projector_module._stored_time("recognized_at", "not-a-datetime")
    assert malformed.value.retryable is True


def test_builder_composes_sql_source_and_sink() -> None:
    runtime = persistence_fixture._runtime()
    try:
        projector = build_eos_project_pnl_projector(
            runtime.sessions, runtime.repository
        )
        assert isinstance(projector, EosProjectPnlProjector)
        assert isinstance(projector._source, SqlAlchemyEosProjectPnlProjectionSource)
    finally:
        runtime.engine.dispose()


def test_runtime_wires_projector_only_with_database_runtime() -> None:
    app = create_eos_app(environ={"NEX_PROFILE": "test"})
    assert app.state.eos_project_pnl_projector is None
