from __future__ import annotations

import uuid
from contextlib import nullcontext
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
import test_nex_eos_mybee_project_pnl as fixture
from nex_eos.cost_allocations import EOS_COST_ALLOCATION_BATCH_TABLE
from nex_eos.payroll_labor_bridge import (
    EOS_LABOR_EFFORT_LINE_TABLE,
    EOS_LABOR_EFFORT_SNAPSHOT_TABLE,
)
from nex_eos.payroll_project_allocations import EOS_PAYROLL_PROJECT_ALLOCATION_TABLE
from nex_eos.pnl_privacy import (
    EOS_PNL_PRIVACY_GUARD_TABLE,
    EosPnlPrivacyError,
    EosProjectPnlPrivacyGuard,
    InMemoryPnlPrivacyRepository,
    PnlPrivacyGuardAdmission,
    PnlPrivacyPopulationFact,
    SqlAlchemyEosPnlPrivacyRepository,
)
from nex_eos.project_authorization import EosProjectAuthorizationEvidence
from run_migrations import load_migrations
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

NOW = datetime(2026, 11, 15, 10, 0, tzinfo=UTC)
SUBJECT = "employee-pnl-reader"


def _projection() -> dict:
    runtime = fixture._runtime()
    try:
        return runtime.repository.append(fixture._draft(), fixture._components())
    finally:
        runtime.engine.dispose()


def _authorization() -> EosProjectAuthorizationEvidence:
    return EosProjectAuthorizationEvidence(
        decision_ref="oa-decision:s7-03",
        project_code="W601D260001",
        project_role="MANAGER",
        project_status="ACTIVE",
        source_version=1,
        projection_event_hash="sha256:" + "1" * 64,
        authorization_revision_hash="sha256:" + "2" * 64,
        decided_at=NOW.isoformat(),
    )


def _fact(**overrides) -> PnlPrivacyPopulationFact:
    values = {
        "snapshot_id": "10000000-0000-0000-0000-000000000001",
        "line_no": 1,
        "population_count": 5,
        "minimum_population": 3,
        "ordinary_view_suppressed": False,
        "line_hash": "sha256:" + "3" * 64,
    }
    values.update(overrides)
    return PnlPrivacyPopulationFact(**values)


def _protect(
    guard: EosProjectPnlPrivacyGuard,
    projection: dict,
    *,
    subject_id: str = SUBJECT,
    historical: bool = False,
):
    return guard.protect(
        projection,
        subject_id=subject_id,
        authorization=_authorization(),
        historical_version_requested=historical,
        observed_at=NOW,
    )


def test_safe_payroll_aggregate_is_pinned_and_exact_replay_is_allowed() -> None:
    projection = _projection()
    repository = InMemoryPnlPrivacyRepository(facts=(_fact(),))
    guard = EosProjectPnlPrivacyGuard(repository)

    assert _protect(guard, projection) == projection
    assert _protect(guard, projection) == projection
    assert len(repository.guards) == 1
    admission = next(iter(repository.guards.values()))
    assert admission.population_floor == 5
    assert admission.minimum_population == 3
    assert admission.payroll_component_count == 3
    assert admission.privacy_fingerprint.startswith("sha256:")
    assert admission.authorization_decision_hash.startswith("sha256:")


def test_privacy_migration_is_current_inventory_head_and_append_only() -> None:
    migrations = load_migrations("nex-eos")
    assert migrations[-1].version == "2548_eos_pnl_privacy_guard"
    migration = Path(
        "database/nex-eos/migrations/2548_eos_pnl_privacy_guard.sql"
    ).read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS eos_pnl_privacy_guard" in migration
    assert "eos_reject_pnl_privacy_guard_mutation" in migration
    assert "BEFORE UPDATE OR DELETE" in migration


@pytest.mark.parametrize(
    ("facts", "historical", "reason"),
    [
        ((), False, "POPULATION_EVIDENCE_MISSING"),
        ((_fact(population_count=2),), False, "SMALL_CELL_SUPPRESSED"),
        ((_fact(ordinary_view_suppressed=True),), False, "SMALL_CELL_SUPPRESSED"),
        ((_fact(),), True, "HISTORICAL_VERSION_DIFFERENCE"),
    ],
)
def test_privacy_guard_denies_missing_small_suppressed_and_historical_cells(
    facts, historical, reason
) -> None:
    guard = EosProjectPnlPrivacyGuard(InMemoryPnlPrivacyRepository(facts=facts))
    with pytest.raises(EosPnlPrivacyError) as caught:
        _protect(guard, _projection(), historical=historical)
    assert caught.value.error_code == "PAYROLL_PRIVACY_DENIED"
    assert caught.value.status_code == 403
    assert caught.value.reason_code == reason
    assert "population" not in caught.value.detail.lower()


def test_changed_payroll_fingerprint_is_denied_but_subject_scope_is_independent() -> (
    None
):
    projection = _projection()
    repository = InMemoryPnlPrivacyRepository(facts=(_fact(),))
    guard = EosProjectPnlPrivacyGuard(repository)
    _protect(guard, projection)

    changed = deepcopy(projection)
    changed["components"][2]["source_hash"] = "sha256:" + "9" * 64
    changed["components"][2]["component_hash"] = "sha256:" + "8" * 64
    with pytest.raises(EosPnlPrivacyError) as caught:
        _protect(guard, changed)
    assert caught.value.reason_code == "PAYROLL_FINGERPRINT_CHANGED"

    assert _protect(guard, changed, subject_id="employee-pnl-reader-2") == changed
    assert len(repository.guards) == 2


def test_non_payroll_projection_needs_no_population_admission() -> None:
    projection = _projection()
    projection["components"] = [
        item
        for item in projection["components"]
        if item["source_kind"] != "PAYROLL"
        and item["data_classification"] != "PAYROLL_SENSITIVE"
    ]
    repository = InMemoryPnlPrivacyRepository()
    assert _protect(EosProjectPnlPrivacyGuard(repository), projection) == projection
    assert repository.guards == {}


def test_sqlalchemy_repository_loads_population_and_persists_guard() -> None:
    runtime = fixture._runtime()
    try:
        projection = runtime.repository.append(fixture._draft(), fixture._components())
        for table in (
            EOS_LABOR_EFFORT_SNAPSHOT_TABLE,
            EOS_LABOR_EFFORT_LINE_TABLE,
            EOS_COST_ALLOCATION_BATCH_TABLE,
            EOS_PAYROLL_PROJECT_ALLOCATION_TABLE,
            EOS_PNL_PRIVACY_GUARD_TABLE,
        ):
            table.create(runtime.engine)
        snapshot_id = str(uuid.uuid4())
        batch_id = str(uuid.uuid4())
        plan_id = str(uuid.uuid4())
        with runtime.sessions.begin() as session:
            session.execute(
                EOS_LABOR_EFFORT_SNAPSHOT_TABLE.insert().values(
                    tenant_id=fixture.TENANT,
                    company_id=fixture.COMPANY_ID,
                    snapshot_id=snapshot_id,
                    effort_period_start=NOW.date(),
                    effort_period_end=NOW.date(),
                    revision=1,
                    basis_kind="ACTUAL_APPROVED",
                    effort_unit="MAN_DAY",
                    source_ref="labor-sor:aggregate",
                    source_hash="sha256:" + "4" * 64,
                    evidence_cutoff_at=fixture.NOW,
                    approval_ref="approval:aggregate",
                    approval_hash="sha256:" + "5" * 64,
                    state="APPROVED",
                    approved_at=fixture.NOW,
                    privacy_class="LABOR_AGGREGATE",
                    snapshot_hash="sha256:" + "6" * 64,
                    created_at=fixture.NOW,
                )
            )
            session.execute(
                EOS_LABOR_EFFORT_LINE_TABLE.insert().values(
                    tenant_id=fixture.TENANT,
                    company_id=fixture.COMPANY_ID,
                    snapshot_id=snapshot_id,
                    line_no=1,
                    project_id=fixture.PROJECT_ID,
                    project_code="W601D260001",
                    work_code=None,
                    organization_ref="org:engineering",
                    grade_band="G4",
                    cost_cohort="engineering-g4",
                    effort_units=Decimal("20.0000"),
                    population_count=5,
                    minimum_population=3,
                    ordinary_view_suppressed=False,
                    work_assignment_id=None,
                    basis_source_ref="labor-sor:aggregate:line:1",
                    basis_source_hash="sha256:" + "7" * 64,
                    line_hash="sha256:" + "8" * 64,
                )
            )
            session.execute(
                EOS_COST_ALLOCATION_BATCH_TABLE.insert().values(
                    tenant_id=fixture.TENANT,
                    company_id=fixture.COMPANY_ID,
                    batch_id=batch_id,
                    plan_id=plan_id,
                    plan_revision=1,
                    period_id=fixture.PERIOD_ID,
                    source_set_hash="sha256:" + "9" * 64,
                    functional_currency="KRW",
                    state="COMMITTED",
                    allocated_total=Decimal("300.0000"),
                    unallocated_total=Decimal("25.0000"),
                    reconciliation_hash="sha256:" + "a" * 64,
                    business_operation_id=str(uuid.uuid4()),
                    idempotency_key="privacy-test",
                    outbox_event_id=None,
                    committed_at=fixture.NOW,
                    created_at=fixture.NOW,
                )
            )
            session.execute(
                EOS_PAYROLL_PROJECT_ALLOCATION_TABLE.insert().values(
                    tenant_id=fixture.TENANT,
                    company_id=fixture.COMPANY_ID,
                    allocation_id=str(uuid.uuid4()),
                    allocation_revision=1,
                    payroll_evidence_id=str(uuid.uuid4()),
                    effort_snapshot_id=snapshot_id,
                    plan_id=plan_id,
                    plan_revision=1,
                    batch_id=batch_id,
                    basis_kind="ACTUAL_APPROVED",
                    allocation_status="CONFIRMED",
                    residual_treatment="RETAIN_UNALLOCATED",
                    project_effort_units=Decimal("20.0000"),
                    residual_effort_units=Decimal("0.0000"),
                    allocated_total=Decimal("300.0000"),
                    residual_total=Decimal("25.0000"),
                    policy_hash="sha256:" + "b" * 64,
                    allocation_hash="sha256:" + "c" * 64,
                    supersedes_allocation_id=None,
                    created_at=fixture.NOW,
                )
            )

        repository = SqlAlchemyEosPnlPrivacyRepository(runtime.sessions)
        facts = repository.population_facts(
            tenant_id=fixture.TENANT,
            company_id=fixture.COMPANY_ID,
            project_id=fixture.PROJECT_ID,
            period_id=fixture.PERIOD_ID,
            as_of=fixture.NOW,
        )
        assert facts == (
            PnlPrivacyPopulationFact(
                snapshot_id=snapshot_id,
                line_no=1,
                population_count=5,
                minimum_population=3,
                ordinary_view_suppressed=False,
                line_hash="sha256:" + "8" * 64,
            ),
        )
        guard = EosProjectPnlPrivacyGuard(repository)
        assert _protect(guard, projection) == projection
        assert _protect(guard, projection) == projection
        with runtime.sessions() as session:
            assert (
                session.execute(
                    select(func.count()).select_from(EOS_PNL_PRIVACY_GUARD_TABLE)
                ).scalar_one()
                == 1
            )
    finally:
        runtime.engine.dispose()


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: value.update(components=None),
        lambda value: value.update(components=["invalid"]),
        lambda value: value.update(as_of="not-a-timestamp"),
        lambda value: value.update(as_of="2026-11-15T10:00:00"),
    ],
)
def test_malformed_projection_privacy_evidence_fails_closed(mutator) -> None:
    projection = _projection()
    mutator(projection)
    guard = EosProjectPnlPrivacyGuard(InMemoryPnlPrivacyRepository(facts=(_fact(),)))
    with pytest.raises(EosPnlPrivacyError) as caught:
        _protect(guard, projection)
    assert caught.value.error_code == "PNL_PRIVACY_UNAVAILABLE"
    assert caught.value.status_code == 503
    assert caught.value.retryable is True


def _admission() -> PnlPrivacyGuardAdmission:
    return PnlPrivacyGuardAdmission(
        tenant_id=fixture.TENANT,
        company_id=fixture.COMPANY_ID,
        subject_id=SUBJECT,
        project_id=fixture.PROJECT_ID,
        period_id=fixture.PERIOD_ID,
        projection_id=fixture.PROJECTION_ID,
        projection_version=1,
        privacy_fingerprint="sha256:" + "a" * 64,
        population_floor=5,
        minimum_population=3,
        payroll_component_count=3,
        authorization_decision_hash="sha256:" + "b" * 64,
        admitted_at=NOW,
    )


def test_sqlalchemy_repository_maps_read_and_write_failures() -> None:
    class BrokenFactory:
        def __call__(self):
            raise SQLAlchemyError("read offline")

        def begin(self):
            raise SQLAlchemyError("write offline")

    repository = SqlAlchemyEosPnlPrivacyRepository(BrokenFactory())
    with pytest.raises(EosPnlPrivacyError, match="evidence is unavailable"):
        repository.population_facts(
            tenant_id=fixture.TENANT,
            company_id=fixture.COMPANY_ID,
            project_id=fixture.PROJECT_ID,
            period_id=fixture.PERIOD_ID,
            as_of=NOW,
        )
    with pytest.raises(EosPnlPrivacyError, match="persistence is unavailable"):
        repository.admit_guard(_admission())


@pytest.mark.parametrize("replay_mode", ["existing", "missing", "offline"])
def test_sqlalchemy_repository_resolves_or_fails_closed_on_insert_race(
    monkeypatch, replay_mode
) -> None:
    class RaceFactory:
        def begin(self):
            raise IntegrityError("insert", {}, RuntimeError("duplicate"))

        def __call__(self):
            return nullcontext(object())

    admission = _admission()

    def replay(_session, _value):
        if replay_mode == "offline":
            raise SQLAlchemyError("replay offline")
        if replay_mode == "missing":
            return None
        return vars(admission)

    from nex_eos import pnl_privacy as privacy_module

    monkeypatch.setattr(privacy_module, "_guard_row", replay)
    repository = SqlAlchemyEosPnlPrivacyRepository(RaceFactory())
    if replay_mode == "existing":
        assert repository.admit_guard(admission) == (admission, False)
        return
    with pytest.raises(EosPnlPrivacyError) as caught:
        repository.admit_guard(admission)
    assert caught.value.error_code == "PNL_PRIVACY_UNAVAILABLE"
    assert caught.value.retryable is True
